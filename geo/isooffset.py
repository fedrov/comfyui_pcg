"""
IsoOffset -- geometry -> SDF / fog volume / offset iso-surface. Matches Houdini's IsoOffset SOP (added in pcg100 s9).

Previously sop_map pointed IsoOffset at Convert's volume_sdf / volume_fog modes, but Convert lacks IsoOffset's own Mode,
sampling, Offset and bounding box controls; Convert's behaviour stays as is and this node is separate.

━━ Mode (how the distance field is obtained)
  ray_intersect    signed distance (positive outside, negative inside). **Not ray intersection**: uses the same exact SDF
                   as Convert / Reshape SDF (volume.signed_distance: exact narrow-band distance + pseudo-normal / flood fill for the sign).
                   For closed meshes the result equals the ray method; for open meshes that flood through it is unsigned (Houdini's ray method
                   determines inside/outside by hit parity; this doesn't)
  minimum          exact unsigned distance (docs: "only generates a shell, Offset must be greater than 0")
  point_cloud      distance to the nearest input point; signed by (x - p).N when points have N, otherwise unsigned
  implicit_box     exact SDF of the input bounding box
  implicit_sphere  SDF of the bounding sphere: centre = bbox centre, radius = max distance from points to the centre (the docs don't say how
                   the bounding sphere is chosen; this is our choice)
Field = distance - Offset (positive Offset grows outwards; the docs don't state the sign convention). Invert Sign negates the whole field.

━━ Sampling (Uniform Sampling)
  non_uniform        Sampling Divs given per axis
  max_axis / x_axis / y_axis / z_axis   that axis gets Uniform Sampling Divs grid points; the other axes derive from the same voxel
                     size (voxels are cubes; the bbox is expanded symmetrically to whole cells)
  by_size            voxel size given directly as Div Size
Divs is the **number of grid points** (this plugin's volumes are sampled at grid points, with the end points on the bbox corners); in Houdini it is the number of voxels.

━━ Bounding box
Default = the input bbox, expanded by max(Offset, 0) (so offset surfaces aren't clipped). Override Bounds uses
Minimum / Maximum Bound; with a second input connected its bbox is used. Pad Bounds adds one more voxel on each side.

━━ Output
  sdf          volume (fog = 0), value = the field above
  fog          volume (fog = 1), 1 inside, 0 outside, a linear transition one voxel wide near the surface: clamp(1/2 - field / h)
  iso_surface  the field's 0 iso-surface (surface nets, same as Convert), polygons
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM
from .volume import make_volume, signed_distance, volume_to_polygons

OUTPUTS = ("iso_surface", "fog", "sdf")
MODES = ("ray_intersect", "minimum", "point_cloud", "implicit_box", "implicit_sphere")
SAMPLING = ("max_axis", "x_axis", "y_axis", "z_axis", "by_size", "non_uniform")


def _grid(lo, hi, sampling, udivs, divs, div_size):
    """Bbox + sampling mode -> (origin, voxel size (3,), resolution (rx, ry, rz))."""
    size = np.maximum(hi - lo, 1e-9)
    if sampling == "non_uniform":
        res = np.maximum(np.asarray(divs, np.int64), 2)
        return lo, size / (res - 1), res
    if sampling == "by_size":
        h = float(div_size)
        if h <= 0:
            raise ValueError("Div Size must be greater than 0")
    else:
        ax = int(np.argmax(size)) if sampling == "max_axis" else "xyz".index(sampling[0])
        h = size[ax] / max(int(udivs) - 1, 1)
    res = np.maximum(np.ceil(size / h - 1e-9).astype(np.int64) + 1, 2)
    full = (res - 1) * h
    lo = lo - 0.5 * (full - size)                     # expand symmetrically to whole cells
    return lo, np.full(3, h), res


def _box_sdf(Q, lo, hi):
    c, e = 0.5 * (lo + hi), 0.5 * (hi - lo)
    q = np.abs(Q - c) - e
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(1), 0)


def iso_offset(geo, output="sdf", mode="ray_intersect", sampling="max_axis", udivs=30,
               divs=(30, 30, 30), div_size=0.1, offset=0.0, invert=False,
               override_bounds=False, bmin=(-1, -1, -1), bmax=(1, 1, 1), bound_geo=None,
               pad=False, name=""):
    if output not in OUTPUTS:
        raise ValueError(f"Output must be one of {OUTPUTS}")
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if sampling not in SAMPLING:
        raise ValueError(f"Uniform Sampling must be one of {SAMPLING}")
    if geo is None or geo.npoints == 0:
        raise ValueError("IsoOffset input has no points")
    off = float(offset)
    P = geo.get(POINT, "P").astype(np.float64)
    tri = None
    if mode in ("ray_intersect", "minimum"):
        from .spatial import tri_soup
        tri = tri_soup(geo)[0] if geo.nprims else None
        if tri is None or not len(tri):
            raise ValueError(f"{mode} mode needs polygons; for points only use point_cloud")
        used = np.unique(tri)
        lo, hi = P[used].min(0), P[used].max(0)
    else:
        lo, hi = P.min(0), P.max(0)
    if override_bounds:
        if bound_geo is not None and bound_geo.npoints:
            bl, bh = bound_geo.bbox()
            lo, hi = np.asarray(bl, np.float64), np.asarray(bh, np.float64)
        else:
            lo, hi = np.asarray(bmin, np.float64), np.asarray(bmax, np.float64)
        if np.any(hi <= lo):
            raise ValueError("Every component of Maximum Bound must be greater than Minimum Bound")
    else:
        lo, hi = lo - max(off, 0.0), hi + max(off, 0.0)
    origin, cell, res = _grid(lo, hi, sampling, udivs, divs, div_size)
    if pad:
        origin = origin - cell
        res = res + 2
    rx, ry, rz = (int(r) for r in res)
    Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx), indexing="ij")
    Q = origin + np.stack([X, Y, Z], -1).reshape(-1, 3) * cell

    if mode in ("ray_intersect", "minimum"):
        d = signed_distance(P, tri.astype(np.int64), origin, cell, (rx, ry, rz),
                            unsigned=(mode == "minimum")).reshape(-1)
    elif mode == "point_cloud":
        d = _point_cloud(Q, P, geo.get(POINT, "N"))
    elif mode == "implicit_box":
        d = _box_sdf(Q, P.min(0), P.max(0))
    else:
        c = 0.5 * (P.min(0) + P.max(0))
        r = float(np.linalg.norm(P - c, axis=1).max())
        d = np.linalg.norm(Q - c, axis=1) - r
    f = d - off
    if invert:
        f = -f
    f = f.reshape(rz, ry, rx)
    size = (res - 1) * cell
    if output == "fog":
        fog = np.clip(0.5 - f / float(cell.max()), 0.0, 1.0)
        g = make_volume((rx, ry, rz), size, origin + 0.5 * size, 0.0, True)
        g.set_pdata(0, "voxels", fog.astype(np.float32))
    else:
        g = make_volume((rx, ry, rz), size, origin + 0.5 * size, 0.0, False)
        g.set_pdata(0, "voxels", f.astype(np.float32))
        if output == "iso_surface":
            return volume_to_polygons(g, 0.0)
    if str(name).strip():
        g.set_string(PRIM, "name", np.array([str(name).strip()]))
    return g


def _point_cloud(Q, P, N):
    """Distance from each grid point to the nearest input point; signed by (x - p).N when N exists. Blocked brute force."""
    out = np.empty(len(Q))
    step = max(1, 2_000_000 // max(len(P), 1))
    for s in range(0, len(Q), step):
        q = Q[s:s + step]
        D2 = ((q[:, None, :] - P[None]) ** 2).sum(-1)
        k = D2.argmin(1)
        d = np.sqrt(D2[np.arange(len(q)), k])
        if N is not None:
            sg = np.einsum("ij,ij->i", q - P[k], np.asarray(N, np.float64)[k])
            d = np.where(sg < 0, -d, d)
        out[s:s + step] = d
    return out
