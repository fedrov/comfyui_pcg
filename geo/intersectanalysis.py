"""
Intersection Analysis -- places points where triangles / polylines pass through each other and records where each intersection came from. Matches Houdini's
Intersection Analysis SOP (added in pcg100 s9; it used to point at Boolean's seam mode, which outputs intersection polylines,
has no "intersection source" attributes and requires closed manifolds).

━━ What an intersection point is
Two intersecting triangles meet in a line segment, and each end of the segment is where "an edge of one triangle passes through the other triangle".
So computing the **edge x triangle** crossing points finds every intersection point; each segment of a polyline (open polygon) is also treated as
an "edge" and intersected with triangles. Polylines are not intersected with each other (the docs only mention triangles and / or polylines; lines rarely
meet in 3D).
  - One input only: finds the first input's intersections **with itself**, skipping edges and triangles that share points (adjacent faces touch anyway)
  - Two inputs: edges of the first input x triangles of the second, plus edges of the second x triangles of the first
An edge shared by two triangles is counted only once, recorded on the first prim that uses it.
Closed polygons are fan-triangulated (the docs require closed ones to be triangles; we can compute non-triangles anyway, but concave polygons come out wrong).

━━ Output (points only, input geometry not included)
One point per intersection, with point attributes (all two-part: [prim containing the edge, prim containing the pierced triangle]):
  Input Number      int x2  which input (0 / 1) each of the two prims comes from
  Primitive Number  int x2  prim numbers of the two prims
  Primitive UVW     float x6  parametric coordinates (u, v, w) on the two prims, one after the other: on triangles / polygons these are
                    the barycentric coordinates (u, v) relative to the triangle of its fan triangulation (P = (1-u-v)*P0 + u*P1 + v*P2,
                    P0 is the polygon's first point); on polylines (vertex parameter along the polyline u = segment index + t, 0, 0)
The docs don't say whether these attributes are arrays or tuples, or in which order; the above is our choice. Point Num (docs: "point numbers related
to the intersection") doesn't say which point, so it is not implemented.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_POLY


def _parts(geo, sel):
    """(triangle point numbers (T,3), prim of each triangle, triangle index within the fan, edges (E,2), prim of each edge, edge parameter info)."""
    sizes = geo.prim_sizes()
    vp = np.asarray(geo.vertex_point, np.int64)
    off = geo.prim_offset
    poly = sel & (geo.prim_type == PRIM_POLY) & (sizes >= 2)
    T, Tp, Tk = [], [], []
    E, Ep, Eu = [], [], []                          # Eu: (is polyline segment, segment index)
    for i in np.nonzero(poly)[0]:
        pts = vp[off[i]:off[i + 1]]
        if geo.prim_closed[i] and len(pts) >= 3:
            for k in range(1, len(pts) - 1):
                T.append((pts[0], pts[k], pts[k + 1]))
                Tp.append(i)
                Tk.append(k - 1)
            ring = np.r_[pts, pts[:1]]
            for a, b in zip(ring[:-1], ring[1:]):
                E.append((a, b))
                Ep.append(i)
                Eu.append((0, 0))
        else:
            for s, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
                E.append((a, b))
                Ep.append(i)
                Eu.append((1, s))
    T = np.asarray(T, np.int64).reshape(-1, 3)
    E = np.asarray(E, np.int64).reshape(-1, 2)
    Eu = np.asarray(Eu, np.int64).reshape(-1, 2)
    Ep = np.asarray(Ep, np.int64)
    if len(E):
        # An edge shared by two triangles counts once (first prim that uses it)
        key = np.sort(E, 1)
        _, first = np.unique(key, axis=0, return_index=True)
        first = np.sort(first)
        E, Ep, Eu = E[first], Ep[first], Eu[first]
    return T, np.asarray(Tp, np.int64), np.asarray(Tk, np.int64), E, Ep, Eu


def _seg_tri(P0, P1, A, B, C, eps):
    """
    Intersection of segment P0->P1 with triangle ABC (Moller-Trumbore, t in [0, 1]). Vectorized pairwise.
    Returns (hit, t, u, v): intersection = P0 + t(P1 - P0) = (1-u-v)A + uB + vC.
    Segments coplanar with the triangle don't count (the intersection would be a segment, not a point).
    """
    d = P1 - P0
    e1, e2 = B - A, C - A
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > eps
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = P0 - A
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * np.einsum("ij,ij->i", d, q)
    t = f * np.einsum("ij,ij->i", e2, q)
    tol = 1e-12
    hit = ok & (u >= -tol) & (v >= -tol) & (u + v <= 1 + tol) & (t >= -tol) & (t <= 1 + tol)
    return hit, t, u, v


def _candidate_pairs(elo, ehi, tlo, thi, pad, chunk):
    """
    (edge, triangle) pairs whose bounding boxes overlap (with pad), yielded in chunks, ordered by edge then triangle.

    The plain way tests every edge against every triangle (E x T box tests: 2.5k faces 1 s, 25k faces 30 s). With scipy a
    KD tree over the triangle box centres gives each edge the triangles within (its half diagonal + the largest
    triangle half diagonal) first -- every overlapping box is in that ball -- and the exact box test then runs on those
    only. Same pairs, same order, so the result is identical.
    """
    nE, nT = len(elo), len(tlo)
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        cKDTree = None
    tr = np.linalg.norm(thi - tlo, axis=1) * 0.5
    ok_kd = cKDTree is not None and nE * nT > 4_000_000 and tr.max() <= 8.0 * max(float(np.percentile(tr, 99)), 1e-300)
    if not ok_kd:
        step = max(1, chunk // max(nT, 1))
        for s in range(0, nE, step):
            ei = np.arange(s, min(s + step, nE))
            ov = np.all((elo[ei, None] <= thi[None] + pad) & (ehi[ei, None] >= tlo[None] - pad), axis=2)
            ie, it = np.nonzero(ov)
            yield ei[ie], it
        return
    from itertools import chain
    tree = cKDTree((tlo + thi) * 0.5)
    ec = (elo + ehi) * 0.5
    rad = np.linalg.norm(ehi - elo, axis=1) * 0.5 + float(tr.max()) + pad * np.sqrt(3.0) * 2.0
    step = 8192
    for s in range(0, nE, step):
        ei = np.arange(s, min(s + step, nE))
        lists = tree.query_ball_point(ec[ei], rad[ei], return_sorted=True)
        c = np.fromiter((len(x) for x in lists), np.int64, len(lists))
        if not c.sum():
            continue
        ie = np.repeat(ei, c)
        it = np.fromiter(chain.from_iterable(lists), np.int64, int(c.sum()))
        ov = np.all((elo[ie] <= thi[it] + pad) & (ehi[ie] >= tlo[it] - pad), axis=1)
        ie, it = ie[ov], it[ov]
        o = np.lexsort((it, ie))
        yield ie[o], it[o]


def _cross(PE, E, Ep, Eu, PT, T, Tp, Tk, self_mode, chunk=200_000):
    """All intersecting (edge, triangle) pairs; filtered by bounding boxes first. Returns (position, edge index, triangle index, t, u, v)."""
    if not len(E) or not len(T):
        z = np.zeros(0, np.int64)
        return np.zeros((0, 3)), z, z, np.zeros(0), np.zeros(0), np.zeros(0)
    P0, P1 = PE[E[:, 0]], PE[E[:, 1]]
    A, B, C = PT[T[:, 0]], PT[T[:, 1]], PT[T[:, 2]]
    elo, ehi = np.minimum(P0, P1), np.maximum(P0, P1)
    tlo = np.minimum(np.minimum(A, B), C)
    thi = np.maximum(np.maximum(A, B), C)
    scale = max(float(np.abs(np.r_[PE, PT]).max()), 1.0)
    eps = 1e-14 * scale * scale
    out = []
    for ie, it in _candidate_pairs(elo, ehi, tlo, thi, 1e-9 * scale, chunk):
        if self_mode:
            # Self-intersection: skip when an endpoint of the edge is a point of the triangle (adjacent / same face)
            share = np.zeros(len(ie), bool)
            for k in range(3):
                share |= (E[ie, 0] == T[it, k]) | (E[ie, 1] == T[it, k])
            ie, it = ie[~share], it[~share]
        if not len(ie):
            continue
        hit, t, u, v = _seg_tri(P0[ie], P1[ie], A[it], B[it], C[it], eps)
        ie, it, t, u, v = ie[hit], it[hit], t[hit], u[hit], v[hit]
        X = P0[ie] + t[:, None] * (P1[ie] - P0[ie])
        out.append((X, ie, it, t, u, v))
    if not out:
        z = np.zeros(0, np.int64)
        return np.zeros((0, 3)), z, z, np.zeros(0), np.zeros(0), np.zeros(0)
    res = [np.concatenate([o[k] for o in out]) for k in range(6)]
    # When an edge passes exactly through a diagonal of a polygon's fan triangulation, both fan triangles get a hit -- keep only one
    # per same edge, same prim and same position
    X, ie, it = res[0], res[1], res[2]
    q = np.round(X / (1e-9 * scale)).astype(np.int64)
    key = np.c_[ie, Tp[it], q]
    _, first = np.unique(key, axis=0, return_index=True)
    first = np.sort(first)
    return tuple(r[first] for r in res)


def _edge_uvw(geo, Ep, Eu, E, t):
    """Parametric coordinates of the prim on the edge side: polyline (segment index + t, 0, 0); polygon = barycentric coordinates in its fan triangle."""
    out = np.zeros((len(Ep), 3))
    vp = np.asarray(geo.vertex_point, np.int64)
    off = geo.prim_offset
    for r, (pr, (is_line, seg), (a, b), tt) in enumerate(zip(Ep, Eu, E, t)):
        if is_line:
            out[r] = (seg + tt, 0.0, 0.0)
            continue
        pts = list(vp[off[pr]:off[pr + 1]])
        n = len(pts)
        ia, ib = pts.index(a), pts.index(b)
        # Which fan triangle (0, k, k+1) edge (a, b) lies on: ib = ia + 1 (or wrap-around)
        if ia == 0:                                 # 0 -> 1: triangle k = 1
            k = 1
            bary = {0: 1 - tt, 1: tt}
        elif ib == 0:                               # n-1 -> 0: triangle k = n-2
            k = n - 2
            bary = {n - 1: 1 - tt, 0: tt}
        else:                                       # k -> k+1: triangle k
            k = ia
            bary = {ia: 1 - tt, ib: tt}
        u = bary.get(k, 0.0)
        v = bary.get(k + 1, 0.0)
        out[r] = (u, v, 0.0)
    return out


def intersection_analysis(geo_a, geo_b=None, group_a="", group_b="", input_attr="input",
                          prim_attr="sourceprim", uvw_attr="sourceprimuv"):
    """See the module notes. Returns (point geometry, report)."""
    from .groups import resolve
    if geo_a is None or geo_a.nprims == 0:
        return Geometry(), {"points": 0}
    sa = resolve(geo_a, PRIM, group_a)
    PA = geo_a.get(POINT, "P").astype(np.float64)
    TA, TpA, TkA, EA, EpA, EuA = _parts(geo_a, sa)
    rows = []                                       # (X, edge input, edge prim, edge uvw, triangle input, triangle prim, triangle uvw)
    if geo_b is None:
        X, ie, it, t, u, v = _cross(PA, EA, EpA, EuA, PA, TA, TpA, TkA, True)
        rows.append((X, 0, geo_a, EpA[ie], EuA[ie], EA[ie], t, 0, TpA[it], TkA[it], u, v))
    else:
        sb = resolve(geo_b, PRIM, group_b)
        PB = geo_b.get(POINT, "P").astype(np.float64)
        TB, TpB, TkB, EB, EpB, EuB = _parts(geo_b, sb)
        X, ie, it, t, u, v = _cross(PA, EA, EpA, EuA, PB, TB, TpB, TkB, False)
        rows.append((X, 0, geo_a, EpA[ie], EuA[ie], EA[ie], t, 1, TpB[it], TkB[it], u, v))
        X, ie, it, t, u, v = _cross(PB, EB, EpB, EuB, PA, TA, TpA, TkA, False)
        rows.append((X, 1, geo_b, EpB[ie], EuB[ie], EB[ie], t, 0, TpA[it], TkA[it], u, v))
    Xs, ins, prs, uvs = [], [], [], []
    for X, ei, eg, ep, eu, ee, t, ti, tp, tk, u, v in rows:
        if not len(X):
            continue
        Xs.append(X)
        ins.append(np.c_[np.full(len(X), ei), np.full(len(X), ti)])
        prs.append(np.c_[ep, tp])
        uvs.append(np.c_[_edge_uvw(eg, ep, eu, ee, t), u, v, np.zeros(len(X))])
    if not Xs:
        return Geometry(), {"points": 0}
    out = Geometry.from_points(np.concatenate(Xs))
    if str(input_attr).strip():
        out.set(POINT, str(input_attr).strip(), np.concatenate(ins).astype(np.int32), owned=True)
    if str(prim_attr).strip():
        out.set(POINT, str(prim_attr).strip(), np.concatenate(prs).astype(np.int32), owned=True)
    if str(uvw_attr).strip():
        out.set(POINT, str(uvw_attr).strip(), np.concatenate(uvs).astype(np.float32), owned=True)
    return out, {"points": int(out.npoints)}
