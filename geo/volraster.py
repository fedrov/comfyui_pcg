"""
Volume Rasterize Attributes (pcg82): points -> volume, rasterizing point attributes along the way.

Each point is a sphere kernel of radius r (pscale × Radius Scale; Radius without pscale), kernel weight
k(d) = (1 − d/r)² (same kernel as points_to_volume). Output:
    density     Σ k · the point's density (1 if there is no such attribute) -- a fog volume (positive inside)
    other attributes  kernel-weighted average Σ k·a / Σ k (not a sum: two points with Cd = red overlapping are still red there, not
                 twice as red); cells with Σ k = 0 are filled with 0. Vector attributes are split into name.x / .y / .z (/ .w) scalar volumes,
                 named the same as Houdini dense volumes
Voxels are cubes, grid points aligned to integer multiples of Voxel Size (world space), extent = the points' bounding box expanded by the largest radius.
Attribute from Volume samples back the original values (verified in tests: constant attributes exact everywhere, linear attributes exact when points are dense enough).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .groups import resolve
from .volume import make_volume


def rasterize_attributes(geo, attributes="Cd", voxel_size=0.05, radius=0.1,
                         use_pscale=True, radius_scale=1.0,
                         density_attribute="density", group=""):
    """Returns (volume geometry, report)."""
    from .ops import merge
    vs = float(voxel_size)
    if not vs > 0:
        raise ValueError("Voxel Size must be > 0")
    sel = resolve(geo, POINT, group)
    P = np.asarray(geo.get(POINT, "P"), np.float64)[sel]
    if not len(P):
        raise ValueError("No points to rasterize")
    ps = geo.get(POINT, "pscale") if use_pscale else None
    r = (np.asarray(ps, np.float64)[sel, 0] if ps is not None
         else np.full(len(P), float(radius))) * float(radius_scale)
    if not (r > 0).any():
        raise ValueError("All point radii are 0")
    rmax = float(r.max())
    mn = np.floor((P.min(0) - rmax) / vs) - 1
    mx = np.ceil((P.max(0) + rmax) / vs) + 1
    res = (mx - mn + 1).astype(np.int64)
    if np.prod(res) > 300 ** 3:
        raise ValueError(f"Too many voxels ({res.tolist()}); increase Voxel Size")
    origin = mn * vs
    rx, ry, rz = (int(v) for v in res)
    names = []
    for t in str(attributes).split():
        a = geo.get(POINT, t)
        if a is None or is_string(a):
            raise KeyError(f"No numeric point attribute '{t}'")
        if t != "P":
            names.append(t)
    dname = str(density_attribute).strip() or "density"
    dens_attr = geo.get(POINT, dname)
    dw = (np.asarray(dens_attr, np.float64)[sel, 0] if dens_attr is not None
          and not is_string(dens_attr) else np.ones(len(P)))
    cols = [np.asarray(geo.get(POINT, t), np.float64)[sel] for t in names]
    W = np.zeros((rz, ry, rx))
    D = np.zeros((rz, ry, rx))
    acc = [np.zeros((rz, ry, rx, c.shape[1])) for c in cols]
    R = int(np.ceil(rmax / vs))
    base = np.round((P - origin) / vs).astype(np.int64)
    off = np.arange(-R, R + 1)
    for dz in off:
        for dy in off:
            for dx in off:
                ix = base[:, 0] + dx
                iy = base[:, 1] + dy
                iz = base[:, 2] + dz
                q = origin + np.stack([ix, iy, iz], 1) * vs
                d = np.linalg.norm(q - P, axis=1)
                k = np.clip(1 - d / np.maximum(r, 1e-300), 0, None) ** 2
                ok = (k > 0) & (ix >= 0) & (ix < rx) & (iy >= 0) & (iy < ry) \
                    & (iz >= 0) & (iz < rz)
                if not ok.any():
                    continue
                zz, yy, xx = iz[ok], iy[ok], ix[ok]
                np.add.at(W, (zz, yy, xx), k[ok])
                np.add.at(D, (zz, yy, xx), k[ok] * dw[ok])
                for c, A in zip(cols, acc):
                    np.add.at(A, (zz, yy, xx), k[ok, None] * c[ok])
    size = (res - 1) * vs
    ctr = origin + size / 2

    def vol(arr, nm, fog):
        g = make_volume((rx, ry, rz), size, ctr, fog=fog)
        g.set_pdata(0, "voxels", arr.astype(np.float32))
        g.set_string(PRIM, "name", np.array([nm]))
        return g
    parts = [vol(D, "density", True)]
    suf = ("x", "y", "z", "w")
    for t, A in zip(names, acc):
        avg = np.where(W[..., None] > 0, A / np.maximum(W, 1e-300)[..., None], 0.0)
        if A.shape[-1] == 1:
            parts.append(vol(avg[..., 0], t, False))
        else:
            for c in range(A.shape[-1]):
                parts.append(vol(avg[..., c], f"{t}.{suf[c] if c < 4 else c}", False))
    out = merge(*parts) if len(parts) > 1 else parts[0]
    return out, {"resolution": res.tolist(), "volumes": len(parts),
                 "points": int(len(P)), "radius_max": rmax}
