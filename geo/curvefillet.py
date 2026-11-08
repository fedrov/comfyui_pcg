"""
Curve Fillet (pcg121): round the corners of polylines with circular arcs.

Houdini does this with PolyBevel on curve points (and the Curve SOP's corner rounding); PolyBevel here works on
polygon edges / points only, so curves get their own node.

At each selected corner P with neighbours A and B the arc is tangent to both segments:
  half angle  h = (angle between PA and PB) / 2
  setback     t = r / tan(h)          (distance from P to the tangent points along each segment)
  centre      C = P + bisector * r / sin(h)
With Limit Radius the setback is capped at half the shorter neighbouring segment, so neighbouring fillets never
overlap (the radius shrinks at that corner instead). Straight (within 0.01 deg) and degenerate corners are left alone.
Closed polylines / polygons have no ends, so every point is a corner; open curves keep their end points.
Arc points copy the corner's point attributes.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, VERTEX, DETAIL, PRIM_POLY
from .groups import resolve


def _arc(P, A, B, r, div, limit):
    d1, d2 = A - P, B - P
    l1, l2 = np.linalg.norm(d1), np.linalg.norm(d2)
    if l1 < 1e-12 or l2 < 1e-12:
        return None
    d1, d2 = d1 / l1, d2 / l2
    cosang = float(np.clip(d1 @ d2, -1.0, 1.0))
    ang = np.arccos(cosang)
    if ang > np.pi - np.radians(0.01) or ang < 1e-6:
        return None
    h = ang / 2.0
    t = r / np.tan(h)
    if limit:
        t = min(t, 0.5 * min(l1, l2))
    rr = t * np.tan(h)
    if rr <= 1e-12:
        return None
    bis = d1 + d2
    bis /= np.linalg.norm(bis)
    C = P + bis * (rr / np.sin(h))
    T1, T2 = P + d1 * t, P + d2 * t
    u, v = T1 - C, T2 - C
    phi = np.arccos(np.clip((u @ v) / (np.linalg.norm(u) * np.linalg.norm(v)), -1.0, 1.0))
    w = np.linspace(0.0, 1.0, max(1, int(div)) + 1)
    s = np.sin(phi)
    if s < 1e-12:
        return np.stack([T1, T2])
    a = np.sin((1 - w) * phi) / s
    b = np.sin(w * phi) / s
    return C + a[:, None] * u + b[:, None] * v


def curve_fillet(geo, group="", points="", radius=0.1, divisions=6, limit=True, include_closed=True):
    """Returns (geometry, report)."""
    sel = resolve(geo, PRIM, group)
    psel = resolve(geo, POINT, points)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    newP, src = [P], [np.arange(geo.npoints)]
    nxt = geo.npoints
    vp, offs, closed = [], [0], []
    vsrc = []
    done = 0
    for i in range(geo.nprims):
        pts = geo.prim_points(i).astype(np.int64)
        start = int(geo.prim_offset[i])
        corners = list(range(start, start + len(pts)))
        is_curve = (geo.prim_type[i] == PRIM_POLY and len(pts) >= 3 and sel[i]
                    and (include_closed or not geo.prim_closed[i]))
        out_pts, out_vsrc = [], []
        if is_curve:
            cl = bool(geo.prim_closed[i])
            n = len(pts)
            for k in range(n):
                p = pts[k]
                interior = cl or 0 < k < n - 1
                arc = None
                if interior and psel[p]:
                    a, b = pts[(k - 1) % n], pts[(k + 1) % n]
                    arc = _arc(P[p], P[a], P[b], float(radius), divisions, limit)
                if arc is None:
                    out_pts.append(p)
                    out_vsrc.append(corners[k])
                else:
                    ids = np.arange(nxt, nxt + len(arc))
                    newP.append(arc)
                    src.append(np.full(len(arc), p))
                    nxt += len(arc)
                    out_pts += ids.tolist()
                    out_vsrc += [corners[k]] * len(arc)
                    done += 1
        else:
            out_pts, out_vsrc = pts.tolist(), corners
        vp += out_pts
        vsrc += out_vsrc
        offs.append(offs[-1] + len(out_pts))
        closed.append(bool(geo.prim_closed[i]))
    allP = np.concatenate(newP)
    srcp = np.concatenate(src)
    vp = np.asarray(vp, np.int64)
    # points in order of first use along the prims (arc points sit between their neighbours), then the input's
    # orphan points (points no prim used before stay, like everywhere else)
    first = np.unique(vp, return_index=True)
    keep = first[0][np.argsort(first[1], kind="stable")]
    orphan = np.nonzero(~np.isin(np.arange(geo.npoints), geo.vertex_point))[0]
    keep = np.concatenate([keep, orphan]).astype(np.int64)
    remap = np.full(len(allP), -1, np.int64)
    remap[keep] = np.arange(len(keep))
    out = Geometry()
    out._resize_points(len(keep))
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[srcp[keep]], owned=True)
    out.set(POINT, "P", allP[keep].astype(np.float32), owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v[srcp[keep]])
    out.set_topology(remap[vp].astype(np.int32), np.asarray(offs, np.int32), np.asarray(closed, bool),
                     geo.prim_type.copy())
    vsrc = np.asarray(vsrc, np.int64)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[vsrc], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[vsrc])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v, owned=True)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v)
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out, {"corners_filleted": done, "points": out.npoints}
