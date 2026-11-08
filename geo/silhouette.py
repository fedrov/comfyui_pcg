"""
Extract Silhouette (pcg77): extract outline curves along a view direction.

━━ outline (default): projected outer outline
The geometry is projected along Direction onto the plane through Origin perpendicular to it, and the boundary of the projected region (the **union**
of all projected triangles) is output -- closed polylines, outer loops counter-clockwise and holes clockwise (looking along Direction), with the prim attribute hole
marking holes. The method is exact, not rasterized:
  1 candidate edges: the boundary of the projected region can only lie on "silhouette edges" -- open edges of the mesh, and edges whose two adjacent triangles
    face opposite ways after projection (the border between front and back faces). All other edges are covered on both sides and cannot be boundary
  2 intersect candidate edges pairwise and split them at intersections (each intersection is computed once, both edges use the same point)
  3 take the midpoint of each small segment, nudge it a little to each side, and test whether it is covered by some projected triangle (triangles are bucketed in a grid);
    only segments covered on exactly one side are boundary, oriented so the covered side is on the left
  4 chain end to end into loops; with Simplify on, collinear interior points are removed (a cube seen from the front comes out as 4 points)
Triangles with zero projected area (seen edge-on; the criterion is projected area < 1e-5 x longest edge², i.e. less than 1e-5 radians
from exactly edge-on) do not take part.

━━ contour: 3D contour lines
The boundary of the region of the mesh "facing the viewer" (n·d < 0) -- the edges between front and back faces, and between front faces and faces seen
edge-on -- chained into polylines that stay in 3D (not projected). Include Boundary also adds the open boundary edges touched by the front-facing region.
This is the kind of contour used for NPR outlines.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM

SIL_MODES = ("outline", "contour")


def _basis(d):
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, d)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    return u, v


def _tri_edges(tri):
    """triangle soup -> undirected edges -> [(triangle, whether this edge runs a->b forward in the triangle)]"""
    e = {}
    for t, (a, b, c) in enumerate(tri.tolist()):
        for x, y in ((a, b), (b, c), (c, a)):
            k = (min(x, y), max(x, y))
            e.setdefault(k, []).append(t)
    return e


def _seg_intersections(S, scale):
    """
    Pairwise segment intersection. Returns [(i, j, t_i, "cross", u_j)]: proper crossings and T junctions (one segment's endpoint lies in the
    middle of the other) both count; parallel ones do not (see the note below).
    """
    A, B = S[:, 0], S[:, 1]
    n = len(S)
    out = []
    lo = np.minimum(A, B) - 1e-12 * scale
    hi = np.maximum(A, B) + 1e-12 * scale
    tol = 1e-9
    for i in range(n):
        m = (lo[i + 1:, 0] <= hi[i, 0]) & (hi[i + 1:, 0] >= lo[i, 0]) & \
            (lo[i + 1:, 1] <= hi[i, 1]) & (hi[i + 1:, 1] >= lo[i, 1])
        js = np.nonzero(m)[0] + i + 1
        if not len(js):
            continue
        r = B[i] - A[i]
        rr = float(r @ r)
        for j in js.tolist():
            s_ = B[j] - A[j]
            den = r[0] * s_[1] - r[1] * s_[0]
            q = A[j] - A[i]
            if abs(den) <= 1e-12 * np.sqrt(rr * float(s_ @ s_)):
                # Parallel (including collinear overlap) is not split: at the endpoints of the overlap of two collinear segments there is always a non-collinear
                # candidate edge turning off from there (projected silhouette edges chain into loops), and its intersection with the other segment
                # is a T junction, which is already split below. After deleting the code that used to handle collinear overlap separately,
                # all tests (including 16 kinds of T junctions and partially overlapping L shapes) still passed
                continue
            t = (q[0] * s_[1] - q[1] * s_[0]) / den
            u = (q[0] * r[1] - q[1] * r[0]) / den
            if -tol <= t <= 1 + tol and -tol <= u <= 1 + tol:
                out.append((i, j, min(max(t, 0.0), 1.0), "cross",
                            min(max(u, 0.0), 1.0)))
    return out


def _covered(Q, X2, tri, tb):
    """Whether the points in Q are covered by some projected triangle (strictly inside)."""
    bucket, big, h = tb
    from . import spatial as _sp
    z = np.zeros((len(Q), 1))
    keys = _sp.cell_key(np.floor(np.c_[Q, z] / h).astype(np.int64))
    qi, ti = bucket.query(keys, np.arange(len(Q)))
    if len(big):
        qi = np.concatenate([qi, np.repeat(np.arange(len(Q)), len(big))])
        ti = np.concatenate([ti, np.tile(big, len(Q))])
    cov = np.zeros(len(Q), bool)
    if not len(qi):
        return cov
    a, b, c = X2[tri[ti, 0]], X2[tri[ti, 1]], X2[tri[ti, 2]]
    q = Q[qi]

    def cr(p, s, t):
        return (s[:, 0] - p[:, 0]) * (t[:, 1] - p[:, 1]) - \
            (s[:, 1] - p[:, 1]) * (t[:, 0] - p[:, 0])
    d1, d2, d3 = cr(a, b, q), cr(b, c, q), cr(c, a, q)
    inside = ((d1 > 0) & (d2 > 0) & (d3 > 0)) | ((d1 < 0) & (d2 < 0) & (d3 < 0))
    np.logical_or.at(cov, qi[inside], True)
    return cov


def _simplify(loop, X, tol):
    pts = list(loop)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for k in range(len(pts)):
            a, b, c = X[pts[k - 1]], X[pts[k]], X[pts[(k + 1) % len(pts)]]
            ab, ac = b - a, c - a
            L = np.linalg.norm(ac)
            if L > 0 and abs(ab[0] * ac[1] - ab[1] * ac[0]) / L <= tol and \
                    (ab @ ac) > 0 and (ab @ ac) < L * L:
                pts.pop(k)
                changed = True
                break
    return pts


def extract_silhouette(geo, direction=(0, -1, 0), origin=(0, 0, 0),
                       mode="outline", simplify=True, include_boundary=True,
                       group=""):
    """See the file header. Returns (geometry, report)."""
    from . import spatial as _sp
    if mode not in SIL_MODES:
        raise ValueError(f"Mode must be one of {SIL_MODES}")
    d = np.asarray(direction, np.float64)
    if not np.linalg.norm(d) > 0:
        raise ValueError("Direction cannot be a zero vector")
    d = d / np.linalg.norm(d)
    o = np.asarray(origin, np.float64)
    tri, _, _ = _sp.tri_soup(geo, group)
    if not len(tri):
        raise ValueError("No polygon primitives")
    tri = tri.astype(np.int64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    u, v = _basis(d)
    X2 = np.c_[(P - o) @ u, (P - o) @ v]
    a, b, c = X2[tri[:, 0]], X2[tri[:, 1]], X2[tri[:, 2]]
    area = 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) -
                  (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    scale = max(float(np.abs(X2).max()), 1e-12)
    # Faces seen edge-on: projected area almost 0 relative to their own size (after rotating float32 points, faces that should be exactly edge-on
    # get areas of order 1e-8 with random sign -- an absolute threshold would count them as front / back faces)
    e2 = np.maximum.reduce([((P[tri[:, i]] - P[tri[:, (i + 1) % 3]]) ** 2).sum(1)
                            for i in range(3)])
    live = np.abs(area) > 1e-5 * e2
    edges = _tri_edges(tri)
    if mode == "outline":
        # Merge points that coincide after projection (the top and bottom faces of a cube project to the same square; without merging
        # you get two identical outlines).
        # Tolerance 1e-6 x scale: after rotating float32 points, projections that should coincide differ by about 1e-8
        from .meshfix import _uf
        used = np.unique(tri)
        Z3 = np.c_[X2[used], np.zeros(len(used))]
        qi, pi, _ = _sp.neighbors_within(Z3, Z3, 1e-6 * scale)
        m = qi < pi
        lab, k = _uf(len(used), np.stack([qi[m], pi[m]], 1))
        rep_ = np.full(k, len(used))
        np.minimum.at(rep_, lab, np.arange(len(used)))
        remap = np.arange(len(X2))
        remap[used] = used[rep_[lab]]
        tri = remap[tri]
        edges = _tri_edges(tri)
    rep = {"mode": mode}
    if mode == "contour":
        from .convertline import _paths
        # Boundary of the front-facing region (faces toward the viewer with non-zero projected area): front on one side, not front on the other
        # (back face, edge-on, or no face). Edge-on faces do not count as front faces, so the ring of exactly vertical faces at the
        # equator does not break the contour
        # clockwise in (u, v) after projection = normal opposite to the view direction = facing the viewer
        front = live & (area < 0)
        pairs = []
        for (x, y), ts in edges.items():
            nf = int(front[ts].sum())
            if len(ts) == 1:
                if include_boundary and nf == 1:
                    pairs.append((x, y))
                continue
            if 0 < nf < len(ts):
                pairs.append((x, y))
        if not pairs:
            rep["curves"] = 0
            return Geometry(), rep
        paths = _paths(np.asarray(pairs, np.int64), geo.npoints, True)
        used = sorted({p for pts, _ in paths for p in pts})
        remap = {p: k for k, p in enumerate(used)}
        out = Geometry.from_mesh(P[used].astype(np.float32),
                                 [[remap[p] for p in pts] for pts, _ in paths],
                                 closed=True)
        out.set_topology(out.vertex_point, out.prim_offset,
                         np.array([cl for _, cl in paths], bool))
        rep["curves"] = len(paths)
        return out, rep
    # ── outline
    cand = []
    for (x, y), ts in edges.items():
        ts = [t for t in ts if live[t]]
        if not ts:
            continue
        sg = np.sign(area[ts])
        if len(ts) == 1 or ((sg > 0).any() and (sg < 0).any()) or len(ts) > 2:
            cand.append((x, y))
    if not cand:
        rep["loops"] = 0
        return Geometry(), rep
    cand = np.asarray(cand, np.int64)
    S = np.stack([X2[cand[:, 0]], X2[cand[:, 1]]], 1)
    # Intersections: computed once per pair, both edges share the same point; one falling on a segment endpoint uses that endpoint
    pts = list(X2)
    splits = [[(0.0, int(e[0])), (1.0, int(e[1]))] for e in cand]
    tol = 1e-9
    for i, j, ti, kind, x in _seg_intersections(S, scale):
        uj = x
        if ti <= tol:
            pid = int(cand[i][0])
        elif ti >= 1 - tol:
            pid = int(cand[i][1])
        elif uj <= tol:
            pid = int(cand[j][0])
        elif uj >= 1 - tol:
            pid = int(cand[j][1])
        else:
            pid = len(pts)
            pts.append(S[i, 0] + ti * (S[i, 1] - S[i, 0]))
        if tol < ti < 1 - tol:
            splits[i].append((ti, pid))
        if tol < uj < 1 - tol:
            splits[j].append((uj, pid))
    Xa = np.asarray(pts)
    subs = []
    for sp in splits:
        sp = sorted(sp)
        for (t0, p0), (t1, p1) in zip(sp[:-1], sp[1:]):
            if p0 != p1 and np.linalg.norm(Xa[p1] - Xa[p0]) > 1e-12 * scale:
                subs.append((p0, p1))
    subs = list({(min(p, q), max(p, q)) for p, q in subs})
    subs = np.asarray(subs, np.int64)
    A_, B_ = Xa[subs[:, 0]], Xa[subs[:, 1]]
    mid = 0.5 * (A_ + B_)
    t_ = B_ - A_
    nrm = np.c_[-t_[:, 1], t_[:, 0]]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-300)
    eps = 1e-7 * scale
    L = live.nonzero()[0]
    tl = tri[L]
    lo = np.minimum(np.minimum(X2[tl[:, 0]], X2[tl[:, 1]]), X2[tl[:, 2]])
    hi = np.maximum(np.maximum(X2[tl[:, 0]], X2[tl[:, 1]]), X2[tl[:, 2]])
    h = max(float(np.median(np.max(hi - lo, 1))), 1e-9 * scale)
    z = np.zeros((len(L), 1))
    bucket, big = _sp._box_bucket(np.c_[lo, z], np.c_[hi, z], h)
    tb = (bucket, big, h)
    cl = _covered(mid + eps * nrm, X2, tl, tb)
    cr = _covered(mid - eps * nrm, X2, tl, tb)
    keep = cl != cr
    segs = subs[keep]
    # put the covered side on the left: left = the side of the normal (−t_y, t_x)
    flip = cr[keep]
    segs = np.where(flip[:, None], segs[:, ::-1], segs)
    nxt = {}
    for a_, b_ in segs.tolist():
        nxt.setdefault(a_, []).append(b_)
    loops = []
    used = set()
    for s0, s1 in segs.tolist():
        if (s0, s1) in used:
            continue
        loop = [s0]
        cur, nx = s0, s1
        while True:
            used.add((cur, nx))
            loop.append(nx)
            cands = [w for w in nxt.get(nx, []) if (nx, w) not in used]
            if not cands:
                break
            cur, nx = nx, cands[0]
            if nx == loop[0] and (cur, nx) not in used:
                used.add((cur, nx))
                break
        if loop[-1] == loop[0]:
            loop = loop[:-1]
        if len(loop) >= 3:
            loops.append(loop)
    if simplify:
        loops = [_simplify(lp, Xa, 1e-9 * scale) for lp in loops]
    allp = sorted({p for lp in loops for p in lp})
    remap = {p: k for k, p in enumerate(allp)}
    Y = Xa[allp]
    P3 = o + Y[:, 0:1] * u + Y[:, 1:2] * v
    out = Geometry.from_mesh(P3.astype(np.float32),
                             [[remap[p] for p in lp] for lp in loops], closed=True)
    areas = []
    for lp in loops:
        q = Xa[lp]
        areas.append(0.5 * float((q[:, 0] * np.roll(q[:, 1], -1) -
                                  np.roll(q[:, 0], -1) * q[:, 1]).sum()))
    out.set(PRIM, "hole", (np.asarray(areas) < 0).astype(np.int32)[:, None],
            owned=True)
    out.set(PRIM, "area", np.abs(np.asarray(areas)).astype(np.float32)[:, None],
            owned=True)
    rep.update({"loops": len(loops), "candidates": int(len(cand)),
                "area": float(sum(areas))})
    return out, rep
