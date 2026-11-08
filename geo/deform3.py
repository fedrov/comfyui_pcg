"""
pcg82: Soft Peak, Bulge, Magnet, Fractal -- deformers with falloff.

━━ Soft Peak
Selected points are pushed Distance along their own normals; points within Radius follow with falloff (same soft selection
as Soft Transform: euclidean straight-line distance / distance = geodesic along edges / steps = hop count, Ramp sets the falloff curve).
Normals are the point N, or area-weighted point normals computed on the fly if missing (these are the **pre-deformation** normals, so each point's push
direction isn't affected by the shape after its neighbours were pushed). With Update Normals on, N is recomputed after the push.

━━ Bulge / Magnet
The second input is the "magnet": each magnet point is a spherical zone of influence with radius r (pscale * Radius Scale, Radius when there is
no pscale); point x gets weight w(x) = max_m Ramp(1 - |x - m| / r_m) (0 beyond r). When the magnet is polygonal
(Magnet Type = surface), the distance to the magnet surface is used instead, with Radius as the radius.
  Bulge    P' = P + Magnitude * w * direction; direction = normal (along the point normal) / radial (away from the nearest magnet point)
  Magnet   computes a "transform scaled by w" per point: translation * w, rotation angle * w, scale lerp(1, s, w), around the magnet
           centroid (or the given Pivot) -- it interpolates **parameters**, not results, so rotation doesn't eat the radius (same as Soft Transform)
Writes the point attribute Weight Attribute (empty = not written) for later use.

━━ Fractal
Midpoint displacement: each level first subdivides linearly (face points + edge points, original points don't move), then pushes **the points new at this level**
randomly along the direction by +-Scale * Roughness^level. Direction = normal (point normals of the current mesh) or vector (a given direction). With Fixed Boundary
on, new points on open boundaries aren't pushed (tiled terrain seams don't crack). Random numbers come from "Seed + point number", so the same input gives the same result.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM
from .groups import resolve

MAGNET_TYPES = ("points", "surface")
BULGE_DIRS = ("normal", "radial")
PIVOTS = ("magnet_center", "origin", "custom")
FRACTAL_DIRS = ("normal", "vector")


def _point_normals(geo, fresh=False):
    N = None if fresh else geo.get(POINT, "N")
    if N is not None and N.shape[1] >= 3:
        N = np.asarray(N, np.float64)[:, :3]
    else:
        from .ops import compute_normals
        N = np.asarray(compute_normals(geo, "point").get(POINT, "N"), np.float64)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.where(ln > 1e-12, ln, 1.0)


def _ramp(t, ramp, ramp_mode):
    from .ramp import parse, apply
    pos, val = parse(str(ramp), 1)
    return np.asarray(apply(t, pos, val, ramp_mode), np.float64).reshape(-1)


# ═══════════════════════════════════════════════════════════ Soft Peak
def soft_peak(geo, group="", distance=0.2, radius=1.0, metric="euclidean",
              ramp="0:0  1:1", ramp_mode="smooth", update_normals=True,
              weight_attribute="", soft_type="ramp", tangents=(0.0, 0.0), kernel="links",
              distance_attribute="dist", apply_rolloff=True, lead_normal=False,
              lead_attribute="lead", mask_attribute=""):
    """
    Returns (geometry, report).

    Added in pcg100 (defaults = old behaviour):
      soft_type / tangents / kernel / distance_attribute / apply_rolloff  see deform.soft_falloff
      lead_normal     Translate Along Lead Normal: points are pushed along the normal of "the nearest handle point" (not their own),
                      so the result is a translated block, not a mushroom shape. With Metric = attribute the nearest point comes from
                      lead_attribute (point number, -1 = itself)
      mask_attribute  Mask: Scale by Attribute. Displacement * mask (0 = no move, 1 = full push, linear in between)
    """
    from .deform import soft_falloff, nearest_handle
    if metric != "attribute" and not str(group).strip():
        raise ValueError("Soft Peak needs a point group (the points to push)")
    w, sel = soft_falloff(geo, group, radius, metric, ramp, ramp_mode, soft_type,
                          tangents, kernel, distance_attribute, apply_rolloff)
    N = _point_normals(geo)
    if lead_normal:
        if metric == "attribute":
            lead = _lead_attr(geo, lead_attribute)
        else:
            lead = nearest_handle(geo, sel, metric, radius)
        own = lead < 0
        N = np.where(own[:, None], N, N[np.where(own, 0, lead)])
    k = float(distance) * w
    if str(mask_attribute or "").strip():
        from .deform import _point_attr1
        k = k * _point_attr1(geo, mask_attribute, "Mask Attribute")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    g = geo.copy()
    g.set(POINT, "P", (P + N * k[:, None]).astype(np.float32),
          owned=True)
    if update_normals and geo.has(POINT, "N"):
        from .ops import compute_normals
        g = compute_normals(g, "point")
    if str(weight_attribute).strip():
        g.set(POINT, str(weight_attribute).strip(), w[:, None].astype(np.float32))
    return g, {"moved_points": int((w > 0).sum()), "group_points": int(sel.sum())}


def _lead_attr(geo, name):
    a = geo.get(POINT, str(name or "").strip())
    if a is None or a.dtype.kind not in "iu":
        raise KeyError(f"Lead Point Attribute: no integer point attribute {name!r}")
    lead = np.asarray(a, np.int64)[:, 0]
    bad = (lead >= geo.npoints) | (lead < -1)
    if bad.any():
        raise ValueError(f"Lead Point Attribute {name!r} contains out-of-range point numbers (must be -1 or 0..{geo.npoints - 1})")
    return lead


# ═══════════════════════════════════════════════════════ magnet influence field
def magnet_field(geo, magnet, magnet_type="points", radius=1.0, use_pscale=True,
                 ramp="0:0  1:1", ramp_mode="smooth"):
    """
    Returns (w (n,), nearest magnet point / surface point (n,3)). w is the maximum over all magnets (not the sum: where two magnets
    overlap points aren't pushed twice).
    """
    if magnet_type not in MAGNET_TYPES:
        raise ValueError(f"Magnet Type must be one of {MAGNET_TYPES}")
    if magnet is None or magnet.npoints == 0:
        raise ValueError("Magnet input is empty")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    M = np.asarray(magnet.get(POINT, "P"), np.float64)
    r0 = float(radius)
    if magnet_type == "surface":
        from .spatial import closest_surface, tri_soup
        tri = tri_soup(magnet)[0]
        if not len(tri):
            raise ValueError("Magnet Type = surface needs a magnet with polygons")
        if not r0 > 0:
            raise ValueError("Radius must be > 0")
        _, d, cp, _ = closest_surface(P, M, tri)
        t = d / r0
        w = np.where(t < 1, _ramp(1 - t, ramp, ramp_mode), 0.0)
        return w, cp
    ps = magnet.get(POINT, "pscale") if use_pscale else None
    R = (np.asarray(ps, np.float64)[:, 0] * r0 if ps is not None
         else np.full(len(M), r0))
    if not (R > 0).any():
        raise ValueError("All magnet radii are 0")
    w = np.zeros(len(P))
    near = np.zeros_like(P)
    step = max(1, 2_000_000 // max(len(M), 1))
    for s in range(0, len(P), step):
        Q = P[s:s + step]
        D = np.linalg.norm(Q[:, None] - M[None], axis=2)          # (q, m)
        t = D / np.maximum(R, 1e-300)[None]
        inside = (t < 1) & (R[None] > 0)
        val = np.zeros_like(t)
        if inside.any():
            val[inside] = _ramp(1 - t[inside], ramp, ramp_mode)
        w[s:s + step] = val.max(1)
        k = np.argmin(t, 1)                                    # the "nearest" magnet (normalized by radius)
        near[s:s + step] = M[k]
    return w, near


def bulge(geo, magnet, magnitude=0.5, direction="normal", magnet_type="points",
          radius=1.0, use_pscale=True, ramp="0:0  1:1", ramp_mode="smooth",
          group="", update_normals=True, weight_attribute=""):
    """Returns (geometry, report)."""
    if direction not in BULGE_DIRS:
        raise ValueError(f"Direction must be one of {BULGE_DIRS}")
    w, near = magnet_field(geo, magnet, magnet_type, radius, use_pscale, ramp,
                           ramp_mode)
    w = np.where(resolve(geo, POINT, group), w, 0.0)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    if direction == "normal":
        D = _point_normals(geo)
    else:
        D = P - near
        ln = np.linalg.norm(D, axis=1, keepdims=True)
        D = np.where(ln > 1e-12, D / np.maximum(ln, 1e-300), 0.0)
    g = geo.copy()
    g.set(POINT, "P", (P + D * (float(magnitude) * w)[:, None]).astype(np.float32),
          owned=True)
    if update_normals and geo.has(POINT, "N"):
        from .ops import compute_normals
        g = compute_normals(g, "point")
    if str(weight_attribute).strip():
        g.set(POINT, str(weight_attribute).strip(), w[:, None].astype(np.float32))
    return g, {"moved_points": int((w > 0).sum()), "max_weight": float(w.max(initial=0))}


def magnet(geo, magnet_geo, translate=(0, 0, 0), rotate=(0, 0, 0),
           scale=(1, 1, 1), pivot_mode="magnet_center", pivot=(0, 0, 0),
           magnet_type="points", radius=1.0, use_pscale=True,
           ramp="0:0  1:1", ramp_mode="smooth", group="", weight_attribute=""):
    """Returns (geometry, report)."""
    from .deform import _euler_mats
    if pivot_mode not in PIVOTS:
        raise ValueError(f"Pivot must be one of {PIVOTS}")
    w, _ = magnet_field(geo, magnet_geo, magnet_type, radius, use_pscale, ramp,
                        ramp_mode)
    w = np.where(resolve(geo, POINT, group), w, 0.0)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    if pivot_mode == "magnet_center":
        piv = np.asarray(magnet_geo.get(POINT, "P"), np.float64).mean(0)
    elif pivot_mode == "origin":
        piv = np.zeros(3)
    else:
        piv = np.asarray(pivot, np.float64).reshape(3)
    T = np.asarray(translate, np.float64).reshape(3)
    R = np.radians(np.asarray(rotate, np.float64).reshape(3))
    S = np.asarray(scale, np.float64).reshape(3)
    Mr = _euler_mats(R[0] * w, R[1] * w, R[2] * w)
    k = 1.0 + (S[None] - 1.0) * w[:, None]
    out = np.einsum("nij,nj->ni", Mr, (P - piv) * k) + piv + T[None] * w[:, None]
    g = geo.copy()
    g.set(POINT, "P", out.astype(np.float32), owned=True)
    if geo.has(POINT, "N"):
        from .ops import compute_normals
        g = compute_normals(g, "point")
    if str(weight_attribute).strip():
        g.set(POINT, str(weight_attribute).strip(), w[:, None].astype(np.float32))
    return g, {"moved_points": int((w > 0).sum())}


# ═══════════════════════════════════════════════════════════ Fractal
def fractal(geo, divisions=3, scale=0.2, roughness=0.5, direction="normal",
            vector=(0.0, 1.0, 0.0), fixed_boundary=True, seed=0):
    """Returns (geometry, report)."""
    from .subdivide import subdivide
    from .topology import topology
    if direction not in FRACTAL_DIRS:
        raise ValueError(f"Direction must be one of {FRACTAL_DIRS}")
    if geo.nprims == 0:
        raise ValueError("No primitives to subdivide")
    g = geo
    vec = np.asarray(vector, np.float64).reshape(3)
    if direction == "vector":
        ln = np.linalg.norm(vec)
        if not ln > 0:
            raise ValueError("Vector cannot be 0")
        vec = vec / ln
    amp = float(scale)
    moved = 0
    for lvl in range(max(0, int(divisions))):
        n0 = g.npoints
        g = subdivide(g, 1, "linear", crease_attribute="")
        new = np.arange(n0, g.npoints)
        if fixed_boundary:
            t = topology(g)
            bnd = np.zeros(g.npoints, bool)
            bnd[t.edge_points[t.boundary].reshape(-1)] = True
            new = new[~bnd[new]]
        # Every level starts a fresh random stream from Seed, indexed by point number: new points at this level don't overlap previous levels' point numbers,
        # so they draw from different positions in the stream (it used to open one stream per [seed, level]; mutation testing showed no difference)
        r = np.random.default_rng(int(seed)).uniform(-1.0, 1.0, g.npoints)[new]
        # Subdivision linearly interpolates the old N onto new points, which is wrong after pushing -- recompute from the current shape at every level
        D = _point_normals(g, fresh=True)[new] if direction == "normal" else vec[None]
        P = np.asarray(g.get(POINT, "P"), np.float64)
        P[new] += D * (amp * r)[:, None]
        g = g.copy()
        g.set(POINT, "P", P.astype(np.float32), owned=True)
        moved += len(new)
        amp *= float(roughness)
    if geo.has(POINT, "N"):
        from .ops import compute_normals
        g = compute_normals(g, "point")
    return g, {"points": int(g.npoints), "prims": int(g.nprims), "displaced": moved}
