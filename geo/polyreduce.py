"""
PolyReduce SOP -- quadric error metric (QEM) edge-collapse decimation.

Matches Houdini's PolyReduce. The algorithm is Garland-Heckbert 1997, which to this day is still
the foundation of every commercial decimator (Simplygon, InstaLOD, Houdini, Blender's Decimate all use it).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quadric error: turning "how far from the original surface" into a 4x4 matrix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The squared distance from a point v to a plane p=(a,b,c,d) is (p^T v)^2 = v^T(p p^T)v. **This is a quadratic form**,
and quadratic forms can be added -- so "the sum of squared distances to a bunch of planes" is still a 4x4 matrix:

    Q_v = sum_{faces f containing v}  area_f . K_f      K_f = p_f p_f^T

When collapsing an edge the Qs of the two ends are simply added, and the new point's error is v^T(Q1+Q2)v. **Error accumulates
along the collapses**, so the 100th collapse knows how far it already is from the original surface and does not keep gnawing
at the same spot -- this is exactly why QEM is so much better than "pick the shortest edge each time".

The optimal new position is the point minimizing v^TQv, i.e. solving A v = -b (A is the upper-left 3x3 of Q). When A is nearly singular
(flat regions, points on edges) there is no unique solution, so it falls back to the cheapest of the two endpoints and the midpoint.

Area weighting is not in the original paper but is now standard practice: without weighting, the planes of dense small-face regions are
counted repeatedly, and detail areas actually get gnawed away more easily.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Boundaries and creases: add a "virtual wall"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Looking only at faces, the area near the mesh's outer rim is flat, and QEM would happily gnaw the boundary into a jagged edge -- a flat
Grid reduced to 10% degenerates into a few big triangles, losing the outline entirely. Garland-Heckbert's fix is to add, for each
boundary edge, **a plane through the edge perpendicular to the surface**, with a high weight; pulling the boundary in then costs
a huge price, so it is kept.

Creases (edge groups) and UV seams use the same trick -- they are all "this line must not move". So Boundary Weight /
Crease Weight are two entry points into the same mechanism.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two vetoes: link condition and normal flip
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The collapse with the lowest error is not necessarily a **valid** collapse. Two cases that must be blocked:

  * **Link condition**. The necessary and sufficient condition for collapsing (a,b) to preserve manifoldness is
    `link(a) ∩ link(b) == link(edge ab)` -- in plain words: the common neighbours of a and b must be exactly
    the one or two points opposite that edge. With one extra common neighbour, after collapsing there would be an edge shared by three
    faces, the mesh would no longer be manifold, and every later node relying on half-edges would break.
    This condition is cheap (intersection of two small sets), but **a decimator that skips it quietly produces broken geometry**.

  * **Normal flip**. Low error does not mean faces have not flipped -- a collapse on a thin sliver often flips the surrounding
    triangles entirely, rendering as a black spot. So each is checked: after the affected triangles move to the new
    position, the dot product of their normal with the original must not become negative.

If either check fails, the edge is **permanently marked as not collapsible** rather than having its priority lowered --
topology does not become valid by waiting a bit longer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why this node is **greedy and serial**, rather than vectorized like the other nodes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All other nodes in this suite "compute the whole batch at once". Decimation cannot: each collapse changes the neighbours' Q and the neighbouring edges'
costs, and which edge to collapse next depends on the previous result -- **it is inherently serial**.

What can be done is a batched version: each round picks a set of mutually non-adjacent edges and collapses them together, O(log n) rounds. GPU
decimators all do this. The cost is slightly lower quality (choices in the same round cannot see each other), and non-adjacency is not even
safe enough -- if two edges' endpoints are each other's common neighbours, each is valid alone but together they produce non-
manifold geometry, so the conflict graph would need to be expanded by another ring.

Greedy + heap was chosen here: the quality is that of the reference implementation, and each collapse does very little work (change about ten
triangles, update six or seven edges), so Python's constant overhead spread over these small operations is acceptable. Measurements
are in the README. To go faster you would have to change language, not algorithm.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Preserve UVs (pcg84): LODs sharing one set of textures
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A game asset's LOD1 / LOD2 must use **the same** baked textures as LOD0, so the UVs cannot be re-unwrapped; they can only be
reduced from LOD0 with the UVs carried along as is. Previously vertex attributes were "carried by surviving corners" during decimation: after b merged into a,
corners that pointed at b now point at a, but the attributes were still those of b's corner -- UVs all scrambled. With Preserve UVs on:

  . only **half-edge collapses** are done (the new position is one of the two endpoints, no optimal point is sought) -- the surviving point does not move,
    so its UV stays exact. Engine-side LOD generators like meshoptimizer do the same
  . when b merges into a, corners that pointed at b take the attributes of a's corner **in the deleted triangle** (that
    triangle contains both a and b and lies in the same UV island as b, so what is taken is exactly a's UV on that island)
  . points on UV seams (the same point has different vertex attributes on different corners: uv, hard-edge normals) are all locked
    -- the islands on both sides of a seam each have their own UVs and must not be kneaded together by collapsing
  . the cost is giving up the precision of optimal, and with many seam points it cannot reduce as far

The heap uses **lazy invalidation**: when an edge's cost changes, the old record is not searched for in the heap (heaps do not support deletion by key);
a new one is pushed directly, and when popped it is checked against the current value recorded in `cur_cost`; mismatches are discarded.
"""
from __future__ import annotations

import heapq
from math import sqrt

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .groups import resolve, resolve_edges
from .topology import topology

# The last two were added in pcg100 after Houdini's Target (Percentage of point count / Output point count)
TARGETS = ("percentage", "triangle_count", "point_percentage", "point_count")
POSITIONS = ("optimal", "midpoint", "endpoint")


# ══════════════════════════════════════════════════════════ quadrics
def face_quadrics(P, tris):
    """(m,4,4) area.pp^T for each triangle, and (m,) areas."""
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    area = 0.5 * ln
    nrm = n / np.where(ln[:, None] < 1e-30, 1.0, ln[:, None])
    d = -np.einsum("ij,ij->i", nrm, a)
    p = np.concatenate([nrm, d[:, None]], 1)          # (m,4)
    return area[:, None, None] * np.einsum("ij,ik->ijk", p, p), area


def _plane_quadric(p0, p1, nrm, weight):
    """
    Quadric of the "wall" through p0-p1 perpendicular to nrm, multiplied by the weight.

    Both boundaries and creases rely on it: pulling this line away costs weight times as much.
    """
    e = p1 - p0
    le = np.linalg.norm(e, axis=1)
    ok = le > 1e-30
    w = np.cross(e, nrm)
    lw = np.linalg.norm(w, axis=1)
    w = w / np.where(lw[:, None] < 1e-30, 1.0, lw[:, None])
    d = -np.einsum("ij,ij->i", w, p0)
    p = np.concatenate([w, d[:, None]], 1)
    q = np.einsum("ij,ik->ijk", p, p)
    # Use the edge length as the scale, matching the units of the area weighting; otherwise the meaning of weight drifts with model size
    return q * (weight * le * le)[:, None, None] * ok[:, None, None]


def vertex_quadrics(P, tris, npt, boundary_pairs=(), boundary_normals=None,
                    boundary_weight=1.0, crease_pairs=(),
                    crease_normals=None, crease_weight=1.0):
    """(n,4,4) Q of each point."""
    fq, area = face_quadrics(P, tris)
    Q = np.zeros((npt, 4, 4))
    for k in range(3):
        np.add.at(Q, tris[:, k], fq)
    for pairs, nrms, w in ((boundary_pairs, boundary_normals,
                            boundary_weight),
                           (crease_pairs, crease_normals, crease_weight)):
        if len(pairs) and w > 0:
            pq = _plane_quadric(P[pairs[:, 0]], P[pairs[:, 1]], nrms, w)
            np.add.at(Q, pairs[:, 0], pq)
            np.add.at(Q, pairs[:, 1], pq)
    return Q, area


# ---------------------------------------------------------- pure Python for the hot loop
#
# The functions below **deliberately avoid numpy**. They handle one point, one triangle at a time, and at this scale numpy
# is all overhead: one np.cross(3-vectors) takes about 5 us, np.linalg.cond does an SVD
# at about 50 us -- and both are called a dozen times per collapse. Rewritten as hand-written floats, the same sphere is 10x faster.
# The setup phase (face quadrics, boundary walls) is still batched numpy, where numpy pays off.
#
# Quadrics packed into 10 numbers (the upper triangle of the symmetric 4x4):
#     (a11, a12, a13, b1, a22, a23, b2, a33, b3, c)

def _q10(Q):
    """(4,4) -> 10-tuple."""
    return (Q[0, 0], Q[0, 1], Q[0, 2], Q[0, 3], Q[1, 1], Q[1, 2], Q[1, 3],
            Q[2, 2], Q[2, 3], Q[3, 3])


def _qadd(p, q):
    return (p[0] + q[0], p[1] + q[1], p[2] + q[2], p[3] + q[3], p[4] + q[4],
            p[5] + q[5], p[6] + q[6], p[7] + q[7], p[8] + q[8], p[9] + q[9])


def _qcost(q, x, y, z):
    """v^TQv expanded."""
    a11, a12, a13, b1, a22, a23, b2, a33, b3, c = q
    return (a11 * x * x + a22 * y * y + a33 * z * z
            + 2.0 * (a12 * x * y + a13 * x * z + a23 * y * z)
            + 2.0 * (b1 * x + b2 * y + b3 * z) + c)


def _qsolve(q):
    """
    Solve A v = -b (Cramer's rule). Returns None when A is ill-conditioned -- on flat regions A is nearly singular,
    and a forced solution can fly hundreds of meters away; falling back to an endpoint is better.
    """
    a11, a12, a13, b1, a22, a23, b2, a33, b3, _ = q
    det = (a11 * (a22 * a33 - a23 * a23)
           - a12 * (a12 * a33 - a23 * a13)
           + a13 * (a12 * a23 - a22 * a13))
    scale = max(abs(a11), abs(a22), abs(a33), abs(a12), abs(a13), abs(a23))
    if scale <= 0.0 or abs(det) < 1e-10 * scale * scale * scale:
        return None
    r1, r2, r3 = -b1, -b2, -b3
    x = (r1 * (a22 * a33 - a23 * a23)
         - a12 * (r2 * a33 - a23 * r3)
         + a13 * (r2 * a23 - a22 * r3)) / det
    y = (a11 * (r2 * a33 - a23 * r3)
         - r1 * (a12 * a33 - a23 * a13)
         + a13 * (a12 * r3 - r2 * a13)) / det
    z = (a11 * (a22 * r3 - r2 * a23)
         - a12 * (a12 * r3 - r2 * a13)
         + r1 * (a12 * a23 - a22 * a13)) / det
    return x, y, z


def _best_pos(q, ax, ay, az, bx, by, bz, mode):
    """Choose the new position. Returns (x, y, z, cost)."""
    if mode == "midpoint":
        cands = [(0.5 * (ax + bx), 0.5 * (ay + by), 0.5 * (az + bz))]
    elif mode == "endpoint":
        cands = [(ax, ay, az), (bx, by, bz)]
    elif mode == "optimal":
        v = _qsolve(q)
        if v is not None:
            # A is a sum of pp^T, naturally positive semi-definite; _qsolve has already blocked ill-conditioned cases,
            # so the solution is the **global minimum** of this quadric -- the midpoint and endpoints cannot be
            # lower, so there is no need to compute three more. This cuts _qcost on the hot path from 4 calls to 1
            return v[0], v[1], v[2], max(_qcost(q, v[0], v[1], v[2]), 0.0)
        cands = [(0.5 * (ax + bx), 0.5 * (ay + by), 0.5 * (az + bz)),
                 (ax, ay, az), (bx, by, bz)]
    else:
        raise ValueError(f"Position must be one of {POSITIONS}")
    best, bc = cands[0], _qcost(q, *cands[0])
    for v in cands[1:]:
        c = _qcost(q, *v)
        if c < bc:
            best, bc = v, c
    return best[0], best[1], best[2], max(bc, 0.0)


def _soft_quadrics(P, tris, area, soft, weight):
    """
    The Soft Points term: weight . A . |x - p0|^2, A = 1/3 of the area of the triangles around this point.
    The squared distance from a point to its original position is also a quadric: |x - p|^2 = x^Tx - 2p^Tx + p^Tp. Returns (k,4,4).
    """
    A3 = np.zeros(len(P))
    np.add.at(A3, tris.reshape(-1), np.repeat(area / 3.0, 3))
    w = weight * A3[soft]
    ps = P[soft]
    K = np.zeros((len(soft), 4, 4))
    K[:, 0, 0] = K[:, 1, 1] = K[:, 2, 2] = 1.0
    K[:, :3, 3] = K[:, 3, :3] = -ps
    K[:, 3, 3] = np.einsum("ij,ij->i", ps, ps)
    return w[:, None, None] * K


# ══════════════════════════════════════════════════════════ main procedure
def reduce_mesh(geo, target="percentage", keep_percent=50.0,
                target_count=1000, position="optimal",
                boundary_weight=4.0, crease_group="", crease_weight=4.0,
                lock_boundary=False, lock_group="",
                max_normal_flip=90.0, group="", preserve_uvs=False,
                hard_edges="", soft_points="", soft_weight=1.0):
    """
    QEM decimation. The input is triangulated first and the output is triangles.

    keep_percent is the fraction to **keep** (consistent with Houdini's Percent to Keep),
    not the fraction to delete.

    pcg100 additions to match Houdini:
      target       point_percentage / point_count: counted by **points** (points used by faces after triangulation).
                   Houdini says "the final number may be slightly below the target", same here (a collapse occasionally removes more than one point)
      hard_edges   edge group: these edges must not move -- both endpoints are locked (neither moved nor removed), so the edge naturally stays
      soft_points  point group + soft_weight: try to stay in place but may move. Adds a term to these points' quadrics
                   weight . A . |x - p0|^2 (A = 1/3 of the area of the triangles around this point, same units as the face quadrics,
                   so the weight's meaning does not change with model size). The docs only say "try to keep them, larger weight keeps more", no formula given
    """
    if geo is None:
        return Geometry()
    if target not in TARGETS:
        raise ValueError(f"Target must be one of {TARGETS}")
    if position not in POSITIONS:
        raise ValueError(f"Position must be one of {POSITIONS}")
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()

    from .ops import convert_prims
    tri_geo = geo if (geo.prim_sizes() == 3).all() and geo.prim_closed.all() \
        else convert_prims(geo, "triangles")
    if tri_geo.nprims == 0:
        return geo.copy()

    tris = tri_geo.vertex_point.reshape(-1, 3).astype(np.int64).copy()
    P = tri_geo.get(POINT, "P").astype(np.float64).copy()
    npt, m0 = tri_geo.npoints, len(tris)

    by_pts = target in ("point_percentage", "point_count")
    if by_pts:
        m0 = len(np.unique(tris))                 # number of points used by faces
    pct = target in ("percentage", "point_percentage")
    want = (int(round(m0 * float(keep_percent) / 100.0))
            if pct else int(target_count))
    # When counting points keep at least 3 (one triangle): collapsing further would remove the last triangle and output nothing
    want = max(3 if by_pts else 1, min(want, m0))
    if want >= m0:
        return tri_geo.copy()

    t = topology(tri_geo)
    fnrm = _face_normals(P, tris)

    # ── boundary / crease "walls"
    bnd_pairs, bnd_nrm = _wall_edges(tri_geo, t, tris, fnrm, t.boundary)
    cr_mask = np.zeros(t.nedges, bool)
    if str(crease_group).strip():
        from .groups import edge_mask
        cr_mask = edge_mask(tri_geo, resolve_edges(tri_geo, crease_group))
    cr_pairs, cr_nrm = _wall_edges(tri_geo, t, tris, fnrm, cr_mask)

    Q, _ = vertex_quadrics(P, tris, npt, bnd_pairs, bnd_nrm, boundary_weight,
                           cr_pairs, cr_nrm, crease_weight)   # _ = area of each triangle

    soft = None
    if str(soft_points).strip() and float(soft_weight) > 0:
        soft = np.nonzero(resolve(tri_geo, POINT, soft_points))[0]
    if soft is not None and len(soft):
        Q[soft] += _soft_quadrics(P, tris, _, soft, float(soft_weight))

    # ── Locked points: on the boundary, in explicit groups, and touched by faces not in group
    locked = np.zeros(npt, bool)
    if str(hard_edges).strip():
        he = resolve_edges(tri_geo, hard_edges)
        if len(he):
            locked[np.asarray(he, np.int64).reshape(-1)] = True
    if lock_boundary and len(bnd_pairs):
        locked[bnd_pairs.reshape(-1)] = True
    if str(lock_group).strip():
        locked |= resolve(tri_geo, POINT, lock_group)
    if str(group).strip():
        sel = resolve(tri_geo, PRIM, group)
        if not sel.all():
            # Triangles outside the selection must not move at all; lock all their points
            locked[tris[~sel].reshape(-1)] = True
    keep_uv = bool(preserve_uvs) and len(tri_geo.attribs[VERTEX]) > 0
    if keep_uv:
        position = "endpoint"
        locked |= _seam_points(tri_geo)

    # ── Pure-Python structures for the hot loop. With numpy arrays in "fetch one scalar at a time" mode,
    #    every access builds a 0-d scalar object, which alone is enough to double the time
    px = P[:, 0].tolist()
    py = P[:, 1].tolist()
    pz = P[:, 2].tolist()
    Qs = [_q10(Q[i]) for i in range(npt)]
    T = [list(map(int, r)) for r in tris]
    lock = locked.tolist()
    # Attribute source of each of the three corners of each triangle (original vertex row); rewritten on collapse with Preserve UVs
    CS = [[3 * i, 3 * i + 1, 3 * i + 2] for i in range(len(T))]

    v_tris = [set() for _ in range(npt)]
    for i, r in enumerate(T):
        v_tris[r[0]].add(i)
        v_tris[r[1]].add(i)
        v_tris[r[2]].add(i)
    alive_t = np.ones(len(T), bool)
    dead_t = set()
    alive_v = np.zeros(npt, bool)
    alive_v[tris.reshape(-1)] = True
    av = alive_v.tolist()

    cos_lim = float(np.cos(np.radians(
        float(np.clip(max_normal_flip, 0.0, 180.0)))))
    banned = set()
    cur = {}
    heap = []
    for a, b in _edges_of(tris):
        _push(heap, cur, int(a), int(b), px, py, pz, Qs, position, lock)

    live = m0                             # triangle count when counting faces, used point count when counting points
    while live > want and heap:
        c, a, b, vx, vy, vz = heapq.heappop(heap)
        key = (a, b)
        if cur.get(key) != c or key in banned:
            continue                      # lazy invalidation: this record is stale
        if not (av[a] and av[b]):
            continue
        shared = v_tris[a] & v_tris[b]
        if not shared:
            cur.pop(key, None)
            continue
        if not _legal(a, b, shared, v_tris, T, px, py, pz,
                      vx, vy, vz, cos_lim):
            banned.add(key)               # topology does not become valid by waiting a bit longer
            cur.pop(key, None)
            continue

        # ── Collapse: b merges into a, a moves to the new position.
        # When one end is locked and the other free, **the locked one must survive**: merely putting the new position on
        # the locked point is not enough, because the surviving point could later be dragged away by another collapse, and the "locked"
        # point would quietly drift. Locked means "neither moves nor disappears"
        if lock[b] and not lock[a]:
            a, b = b, a               # shared and the validity checks are symmetric, no need to recompute
        elif keep_uv and (vx, vy, vz) == (px[b], py[b], pz[b]) \
                and (vx, vy, vz) != (px[a], py[a], pz[a]):
            a, b = b, a               # half-edge collapse: whoever keeps the position survives
        if keep_uv:
            # a's corner in the deleted triangle -- a's attributes on the same UV island as b
            t0 = next(iter(shared))
            sa = CS[t0][T[t0].index(a)]
            for ti in v_tris[b]:
                if ti in shared:
                    continue
                r = T[ti]
                CS[ti][r.index(b)] = sa
        px[a], py[a], pz[a] = vx, vy, vz
        Qs[a] = _qadd(Qs[a], Qs[b])
        for ti in shared:
            dead_t.add(ti)
            for w in T[ti]:
                v_tris[w].discard(ti)
        for ti in v_tris[b]:
            r = T[ti]
            for j in range(3):
                if r[j] == b:
                    r[j] = a
            v_tris[a].add(ti)
        v_tris[b].clear()
        av[b] = False
        if by_pts:
            # b is gone; if the other points of the deleted triangles are no longer used by any face, they count as removed too (dropped at rebuild)
            live -= 1 + sum(1 for w in {x for ti in shared for x in T[ti]}
                            if w != b and not v_tris[w])
        else:
            live -= len(shared)

        for nb in _neighbours(a, v_tris, T):
            _push(heap, cur, a, nb, px, py, pz, Qs, position, lock, banned)

    alive_t[list(dead_t)] = False
    P = np.stack([np.asarray(px), np.asarray(py), np.asarray(pz)], 1)
    tris = np.asarray(T, np.int64)
    return _rebuild(tri_geo, P, tris, alive_t, alive_v,
                    np.asarray(CS, np.int64) if keep_uv else None)


# ══════════════════════════════════════════════════════════ internals
def _face_normals(P, tris):
    n = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    return n / np.where(ln[:, None] < 1e-30, 1.0, ln[:, None])


def _wall_edges(geo, t, tris, fnrm, mask):
    """Selected edges -> (point pairs, normal of the face containing each edge). For _plane_quadric."""
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return np.zeros((0, 2), np.int64), np.zeros((0, 3))
    he = t.edge_he[t.edge_he_off[idx]].astype(np.int64)
    return t.edge_points[idx].astype(np.int64), fnrm[he // 3]


def _edges_of(tris):
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    return np.unique(np.sort(e, axis=1), axis=0)


def _neighbours(a, v_tris, T):
    out = set()
    for ti in v_tris[a]:
        out.update(T[ti])
    out.discard(a)
    return out


def _push(heap, cur, a, b, px, py, pz, Qs, position, lock, banned=None):
    if a > b:
        a, b = b, a
    key = (a, b)
    if banned is not None and key in banned:
        return
    if lock[a] and lock[b]:
        return                            # both ends locked, this edge never moves
    q = _qadd(Qs[a], Qs[b])
    if lock[a]:
        x, y, z = px[a], py[a], pz[a]
        c = _qcost(q, x, y, z)
    elif lock[b]:
        x, y, z = px[b], py[b], pz[b]
        c = _qcost(q, x, y, z)
    else:
        x, y, z, c = _best_pos(q, px[a], py[a], pz[a],
                               px[b], py[b], pz[b], position)
    cur[key] = c
    heapq.heappush(heap, (c, a, b, x, y, z))


def _legal(a, b, shared, v_tris, T, px, py, pz, vx, vy, vz, cos_lim):
    """Link condition + normal flip. A collapse is allowed only if both pass. Hand-written floats, no numpy."""
    if len(shared) > 2:
        return False                      # non-manifold edge, do not touch
    # Link condition: the common neighbours must be exactly the one or two points opposite this edge
    opp = set()
    for ti in shared:
        for w in T[ti]:
            if w != a and w != b:
                opp.add(w)
    if _neighbours(a, v_tris, T) & _neighbours(b, v_tris, T) != opp:
        return False
    # Normal flip: surviving triangles must not flip after moving to the new position
    for src in (a, b):
        for ti in v_tris[src]:
            if ti in shared:
                continue
            i0, i1, i2 = T[ti]
            x0, y0, z0 = px[i0], py[i0], pz[i0]
            x1, y1, z1 = px[i1], py[i1], pz[i1]
            x2, y2, z2 = px[i2], py[i2], pz[i2]
            ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
            wx, wy, wz = x2 - x0, y2 - y0, z2 - z0
            ox = uy * wz - uz * wy
            oy = uz * wx - ux * wz
            oz = ux * wy - uy * wx
            lo = ox * ox + oy * oy + oz * oz
            if lo < 1e-30:
                continue
            if i0 == a or i0 == b:
                x0, y0, z0 = vx, vy, vz
            if i1 == a or i1 == b:
                x1, y1, z1 = vx, vy, vz
            if i2 == a or i2 == b:
                x2, y2, z2 = vx, vy, vz
            ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
            wx, wy, wz = x2 - x0, y2 - y0, z2 - z0
            nx = uy * wz - uz * wy
            ny = uz * wx - ux * wz
            nz = ux * wy - uy * wx
            ln = nx * nx + ny * ny + nz * nz
            if ln < 1e-30:
                return False              # degenerated into a line
            # lo / ln are **squared** lengths, so one square root is needed here. math.sqrt takes about 0.06 us,
            # far cheaper than splitting into cases on the sign of d to avoid it
            if (ox * nx + oy * ny + oz * nz) < cos_lim * sqrt(lo * ln):
                return False
    return True


def _seam_points(geo):
    """The same point has different vertex attributes (any of them) on different corners -> points on UV seams / hard edges."""
    vp = geo.vertex_point.astype(np.int64)
    out = np.zeros(geo.npoints, bool)
    for k, v in geo.attribs[VERTEX].items():
        a = np.asarray(v)
        if a.dtype.kind not in "fiu":
            continue
        a = np.round(a.reshape(len(a), -1).astype(np.float64), 9)
        order = np.lexsort((*a.T[::-1], vp))
        sp, sa = vp[order], a[order]
        same_pt = sp[1:] == sp[:-1]
        diff = (np.abs(sa[1:] - sa[:-1]) > 0).any(1)
        out[sp[1:][same_pt & diff]] = True
    return out


def _rebuild(geo, P, tris, alive_t, alive_v, corner_src=None):
    """
    Compact point numbers and rebuild the geometry. Point attributes are carried along from the original points to the final positions.
    If corner_src is given (Preserve UVs), vertex attributes are taken by it; otherwise carried by surviving corners.
    """
    keep_t = np.nonzero(alive_t)[0]
    used = np.unique(tris[keep_t].reshape(-1)) if len(keep_t) \
        else np.zeros(0, np.int64)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))

    out = Geometry()
    out._resize_points(len(used))
    for k, v in geo.attribs[POINT].items():
        if k == "P":
            out.set(POINT, "P", P[used].astype(v.dtype), owned=True)
        elif is_string(v):
            out.set(POINT, k, np.asarray(v)[used], owned=True)
        else:
            out.set(POINT, k, v[used], owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v[used])

    nt = len(keep_t)
    out.set_topology(remap[tris[keep_t]].reshape(-1).astype(np.int32),
                     np.arange(nt + 1, dtype=np.int32) * 3,
                     np.ones(nt, bool),
                     np.full(nt, PRIM_POLY, geo.prim_type.dtype))
    # vertex attributes: after collapsing, corners no longer match the original points, so they can only be carried by surviving corners
    for k, v in geo.attribs[VERTEX].items():
        if corner_src is not None:
            idx = corner_src[keep_t].reshape(-1)
        else:
            idx = np.repeat(keep_t * 3, 3) + np.tile(np.arange(3), nt)
        out.set(VERTEX, k, np.asarray(v)[idx], owned=True)
    for k, v in geo.groups[VERTEX].items():
        idx = np.repeat(keep_t * 3, 3) + np.tile(np.arange(3), nt)
        out.set_group(VERTEX, k, v[idx])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[keep_t], owned=True)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[keep_t])
    out.prim_data = geo.remap_prim_data(keep_t)
    out.edge_groups = geo.remap_edge_groups(remap.astype(np.int32),
                                            out.npoints)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out
