"""
Ray SOP -- project points onto the surface of another geometry.

The two main uses in PCG:
  * dropping scattered points onto terrain (Project Rays, pointing down);
  * shrink wrapping / conforming (Minimum Distance, points move to the nearest surface).

Both modes share the second half (compute hit -> move point -> write attributes -> transfer attributes) and differ only in how the first half
finds hits, so the code is one trunk plus one branch. Intersection and closest-point queries both live in spatial.py.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Points that miss **stay where they are**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Not moved to the origin, not deleted -- points outside the terrain edge and points blocked by Max Distance belong to
this category; they are left in place, and together with hit_group downstream decides whether to delete or keep them. This is also
Houdini's behaviour.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
hitprimuv is the barycentric coordinate on a **triangle**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The collision geometry is cut into triangles before intersecting, so barycentric coordinates are naturally relative to that triangle. Houdini gives
uv relative to the original face. The two agree on triangle meshes and differ on quad meshes -- so attribute interpolation
here **uses the triangle's three corners directly**, without going through uv, and the result is independent of the face's edge count.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .groups import resolve
from .ops import match_names
from . import spatial as _sp

METHODS = ("minimum_distance", "project_rays")


def _tri_normals(P, tri):
    n = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(ln < 1e-20, 1.0, ln)


def _bary(uv):
    """(v, w) -> weights of the three corners (A, B, C)."""
    return np.stack([1.0 - uv[:, 0] - uv[:, 1], uv[:, 0], uv[:, 1]], 1)


def ray(geo, collision=None, group="", method="minimum_distance",
        direction=(0.0, -1.0, 0.0), use_normals=False, reverse=False,
        both_directions=False, farthest=False, max_distance=0.0,
        transform_points=True, scale=1.0, lift=0.0,
        hit_group="", dist_attrib="", hitprim_attrib="",
        hituv_attrib="", hitpos_attrib="", normal_attrib="",
        transfer_attribs=""):
    """
    Project geo's points onto collision's surface.

    With method='project_rays' the direction comes from direction, or with use_normals=True from the points'
    N attribute (negated by reverse). both_directions allows hitting faces behind.
    scale is the fraction of the movement (1 = go to the hit, 0.5 = halfway), lift raises a bit further along the hit normal.
    """
    if geo is None:
        return Geometry()
    out = geo.copy()
    if collision is None or geo.npoints == 0:
        return out
    tri, tri_prim, _ = _sp.tri_soup(collision)
    if not len(tri):
        return out
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")

    CP = collision.get(POINT, "P").astype(np.float64)
    P = geo.get(POINT, "P").astype(np.float64)
    sel = np.nonzero(resolve(geo, POINT, group))[0].astype(np.int64)
    if not len(sel):
        return out
    Q = P[sel]

    if method == "minimum_distance":
        ti, dist, pos, uv = _sp.closest_surface(Q, CP, tri, max_distance)
        signed = dist
    else:
        if use_normals:
            N = geo.get(POINT, "N")
            if N is None:
                raise KeyError(
                    "Use Point Normals is on, but the points have no N attribute -- "
                    "add a Normal (PCG) node first.")
            D = N[sel].astype(np.float64)
        else:
            D = np.tile(np.asarray(direction, np.float64).reshape(1, 3),
                        (len(sel), 1))
        if reverse:
            D = -D
        if np.linalg.norm(D, axis=1).max() < 1e-12:
            raise ValueError("Ray direction is a zero vector.")
        ti, t, uv = _sp.ray_cast(Q, D, CP, tri, farthest, max_distance,
                                 both_directions)
        Dn = D / np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-30)
        pos = Q + Dn * t[:, None]
        signed = t                      # in projection mode distance is signed: hits in the reverse direction are negative
        dist = np.abs(t)

    hit = ti >= 0
    TN = _tri_normals(CP, tri)
    hitN = np.zeros((len(sel), 3))
    hitN[hit] = TN[ti[hit]]
    # If the collision geometry has its own N, use the interpolated one so normals are smooth; otherwise use the geometric normal
    cN = collision.get(POINT, "N")
    if cN is not None and cN.shape[1] == 3 and hit.any():
        w = _bary(uv[hit])
        v = np.einsum("ij,ijk->ik", w,
                      cN[tri[ti[hit]]].astype(np.float64))
        ln = np.linalg.norm(v, axis=1, keepdims=True)
        hitN[hit] = v / np.where(ln < 1e-20, 1.0, ln)

    if transform_points and hit.any():
        newP = np.array(P, np.float64)
        idx = sel[hit]
        newP[idx] = (Q[hit] + float(scale) * (pos[hit] - Q[hit])
                     + float(lift) * hitN[hit])
        out.set(POINT, "P", newP.astype(np.float32), owned=True)

    def _put(name, values, dtype=np.float32, fill=0.0):
        nm = str(name).strip()
        if not nm:
            return
        cols = 1 if values.ndim == 1 else values.shape[1]
        cur = out.get(POINT, nm)
        base = (np.full((geo.npoints, cols), fill, np.float64)
                if cur is None or cur.shape[1] != cols
                else cur.astype(np.float64))
        base = np.array(base, np.float64)
        base[sel] = values.reshape(len(sel), cols)
        out.set(POINT, nm, base.astype(dtype), owned=True)

    _put(dist_attrib, np.where(hit, signed, 0.0))
    _put(hitprim_attrib, np.where(hit, tri_prim[np.maximum(ti, 0)], -1),
         np.int32, -1)
    _put(hituv_attrib, np.where(hit[:, None], uv, 0.0))
    _put(hitpos_attrib, np.where(hit[:, None], pos, Q))
    _put(normal_attrib, np.where(hit[:, None], hitN, 0.0))
    if str(hit_group).strip():
        m = np.zeros(geo.npoints, bool)
        m[sel[hit]] = True
        out.set_group(POINT, str(hit_group).strip(), m)

    # ---- interpolate attributes over from the collision surface
    names = [n for n in match_names(list(collision.attribs[POINT].keys()),
                                    transfer_attribs) if n != "P"]
    if names and hit.any():
        corners = tri[ti[hit]]                    # (h,3) point numbers
        w = _bary(uv[hit])
        near = corners[np.arange(len(corners)), np.argmax(w, axis=1)]
        for nm in names:
            a = collision.attribs[POINT][nm]
            cur = out.get(POINT, nm)
            if is_string(a):
                base = (np.full(geo.npoints, "", dtype=a.dtype)
                        if cur is None or not is_string(cur)
                        else np.array(cur, dtype=a.dtype)[:, 0])
                base[sel[hit]] = a[near, 0]       # strings take the nearest corner
                out.set(POINT, nm, base.reshape(-1, 1), owned=True)
                continue
            C = a.shape[1]
            base = (np.zeros((geo.npoints, C)) if cur is None
                    or cur.shape[1] != C else np.array(cur, np.float64))
            base[sel[hit]] = np.einsum("ij,ijk->ik", w,
                                       a[corners].astype(np.float64))
            dt = a.dtype if cur is None else cur.dtype
            out.set(POINT, nm,
                    (np.rint(base) if dt.kind in "iub" else base).astype(dt),
                    owned=True)
    return out
