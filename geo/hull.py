"""
Convex Hull -- 3D convex hull (quickhull). Modelled on Houdini's Convex Hull SOP.

More uses than it looks: collision proxies, turning a cloud of scattered points into a solid, Bound's oriented mode,
and exact answers to questions like "how much space does this pile of points take up".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
quickhull: each time pick the **farthest** point, not just any point
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Build a tetrahedron from four extreme points
    2. Each face records "which points are outside me"
    3. Pick a face that still has outside points, and take its **farthest** outside point as the new vertex
    4. Find all faces **visible** from that vertex and delete them; their boundary (the horizon) is joined with the new vertex
       into a ring of new faces
    5. Reassign the outside points of the deleted faces to the new faces, go back to 3

"Take the farthest" is the key to quickhull's speed: the farthest point is definitely on the final hull, and it removes a large patch of
faces at once. Picking any outside point also converges, but each step advances only a little, degrading to O(n^2).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Visible faces must be found **by flood fill from the current face**, not by scanning the whole table
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The first version took the easy route: each round, dot the new vertex against **all** faces to pick out the visible ones. Two consequences:

**Slow.** Scanning the whole table for every added vertex, O(n*F); 3000 sphere points (the worst case, every point on
the hull) took 12.3 s. After switching to flood fill along adjacency, only the visible faces themselves are touched: the same input in 0.5 s.

**Wrong, and the fatal kind of wrong.** The visible set from a full scan is **not guaranteed connected** -- float noise makes
some nearly coplanar face far away also report "visible", so the visible region is two separate patches whose boundaries are
**two independent loops**. And the next step is "join each horizon edge with the new vertex into a face"; what two loops produce
isn't a closed polyhedron: measured, a 32x24 sphere (float32 points, the points on a ring nearly coplanar)
got cut into 9940 faces with 2442 boundary edges -- the output wasn't a closed shell at all.

Starting from the current face and expanding only along adjacency, the visible set is naturally connected and the horizon naturally one loop. This requires maintaining
a directed edge -> face table: face (i,j,k) owns directed edges (i,j), (j,k), (k,i), and its neighbour across (i,j)
is `edge_face[(j,i)]`. Building the table costs three dict writes per face, in exchange for correctness.

The horizon is still determined by directed edges: an edge (a,b) of a visible face, if `edge_face[(b,a)]` is not in the visible set,
is a segment of the horizon.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tolerance: the input is float32; 1e-9 is self-deception
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Geometry's P is float32; at unit scale the coordinate error is already 6e-8. Using 1e-9 as the "outside the face" threshold
amounts to treating quantization noise as real protrusion: in a ring of points that should be coplanar, a few always "stick out" by 1e-8,
growing a pile of zero-area slivers. The default tol is **1e-6** (relative to the bounding scale) -- two orders of magnitude above float32
noise, yet far below any real feature.

The same reasoning applies to the **rank** test: for an exactly collinear float32 polyline, the second singular value is around
1e-7; compared against 1e-9 it'd be classed "planar", and 20 collinear points produced a pentagon.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Degenerate input doesn't error; output drops a dimension
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Coplanar points have no 3D convex hull. Forcing it gives a zero-volume "sliver" or simply crashes, so first look at the
point cloud's **rank**:

    rank 3   normal quickhull
    rank 2   2D convex hull on the best-fit plane, output one polygon
    rank 1   output a line segment
    rank 0   output a point

Houdini just gives empty geometry here. Dropping a dimension is more useful: a pile of coplanar scattered points becomes one polygon,
exactly what you want when drawing a plot outline.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Merging coplanar triangles into polygons: the directed-edge trick again
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
quickhull only emits triangles, so a cube comes out as 12 triangles. `merge_coplanar` groups faces with
the same normal and offset; among the group's directed edges, those whose "reverse edge is also in the group" are interior diagonals,
and the rest chained end-to-end are the outline of that patch -- the cube goes back to 6 quads.

The criterion is the **face's plane equation**, not adjacency, so two disconnected patches on the same plane fall into
one group; separating them relies on "how many loops the outline forms". This can't happen on a convex hull (the intersection of a convex set with a plane
is connected), but the code handles multiple loops, so it won't go silently wrong if later used on non-convex input.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT


def _rank(Q, tol):
    """The point cloud's rank (0..3), and the best-fit orthonormal basis (column vectors, sorted by importance)."""
    if len(Q) < 2:
        return 0, np.eye(3)
    c = Q.mean(0)
    D = Q - c
    w, V = np.linalg.eigh(D.T @ D)
    V = np.ascontiguousarray(V[:, ::-1])        # eigenvalues from large to small
    w = w[::-1]
    scale = max(float(np.abs(D).max()), 1e-30)
    # singular value = sqrt(eigenvalue). Noise accumulation grows with sqrt(n); the threshold scales with it
    thr = tol * scale * np.sqrt(max(len(Q), 1))
    r = int(np.count_nonzero(np.sqrt(np.maximum(w, 0.0)) > thr))
    return r, V


def _hull2d(V, tol):
    """2D convex hull (Andrew monotone chain); returns counter-clockwise indices."""
    idx = np.lexsort((V[:, 1], V[:, 0]))
    scale = max(float(np.abs(V).max()), 1e-30)
    eps = tol * scale * scale

    def half(seq):
        out = []
        for i in seq:
            while len(out) >= 2:
                a, b = V[out[-2]], V[out[-1]]
                q = V[i]
                if ((b[0] - a[0]) * (q[1] - a[1])
                        - (b[1] - a[1]) * (q[0] - a[0])) > eps:
                    break
                out.pop()
            out.append(int(i))
        return out
    lo = half(idx)
    hi = half(idx[::-1])
    return lo[:-1] + hi[:-1]


def _seed_tetra(Q, eps):
    """Initial tetrahedron from four extreme points; returns 4 indices (orientation fixed afterwards)."""
    i0 = int(np.argmin(Q[:, 0]))
    i1 = int(np.argmax(Q[:, 0]))
    if i0 == i1:
        return None
    d = Q[i1] - Q[i0]
    # the point farthest from line i0-i1
    i2 = int(np.argmax(np.linalg.norm(np.cross(Q - Q[i0], d), axis=1)))
    n = np.cross(Q[i1] - Q[i0], Q[i2] - Q[i0])
    ln = float(np.linalg.norm(n))
    if ln <= eps:
        return None
    n /= ln
    # the point farthest from this plane
    h = (Q - Q[i0]) @ n
    i3 = int(np.argmax(np.abs(h)))
    if abs(float(h[i3])) <= eps:
        return None
    return [i0, i1, i2, i3]


def convex_hull_indices(Q, tol=1e-6, max_iter=1_000_000):
    """
    (F,3) point numbers of the hull triangles, facing outward. Q is the (n,3) deduplicated float64 points.

    Only called on rank-3 input -- degenerate cases are diverted earlier by convex_hull. If no tetrahedron can be built,
    returns an empty array and the caller drops a dimension.
    """
    Q = np.ascontiguousarray(Q, np.float64)
    scale = max(float(np.abs(Q).max()), 1.0)
    eps = float(tol) * scale
    tet = _seed_tetra(Q, eps)
    if tet is None:
        return np.zeros((0, 3), np.int64)

    faces = {}          # fid -> (i,j,k), facing outward
    nrm, off = {}, {}
    outside = {}
    edge_face = {}      # directed edge (i,j) -> the face that owns it
    nid = 0

    def add_face(i, j, k):
        nonlocal nid
        f = nid
        nid += 1
        faces[f] = (i, j, k)
        n = np.cross(Q[j] - Q[i], Q[k] - Q[i])
        ln = float(np.linalg.norm(n))
        n = n / ln if ln > 1e-300 else np.zeros(3)
        nrm[f] = n
        off[f] = float(n @ Q[i])
        edge_face[(i, j)] = edge_face[(j, k)] = edge_face[(k, i)] = f
        return f

    def del_face(f):
        i, j, k = faces.pop(f)
        for e in ((i, j), (j, k), (k, i)):
            if edge_face.get(e) == f:
                del edge_face[e]
        del nrm[f], off[f]
        return outside.pop(f, np.zeros(0, np.int64))

    a, b, c, d = tet
    for tri in ((a, b, c), (a, b, d), (a, c, d), (b, c, d)):
        i, j, k = tri
        n = np.cross(Q[j] - Q[i], Q[k] - Q[i])
        rest = [x for x in tet if x not in tri][0]
        # if the fourth point is in front, flip this face, so all faces face outward
        if n @ (Q[rest] - Q[i]) > 0:
            i, k = k, i
        add_face(i, j, k)

    # each face claims the points "outside it". A point may be outside several faces; claiming once is enough
    pool = np.setdiff1d(np.arange(len(Q)), np.asarray(tet))
    for f in list(faces):
        if not len(pool):
            outside[f] = np.zeros(0, np.int64)
            continue
        m = Q[pool] @ nrm[f] - off[f] > eps
        outside[f] = pool[m]
        pool = pool[~m]

    todo = [f for f in faces if len(outside[f])]
    for _ in range(int(max_iter)):
        while todo and (todo[-1] not in faces or not len(outside[todo[-1]])):
            todo.pop()
        if not todo:
            break
        fid = todo[-1]
        pts = outside[fid]
        apex = int(pts[int(np.argmax(Q[pts] @ nrm[fid] - off[fid]))])

        # visible faces: flood fill from fid along adjacency. **Must flood fill** -- a visible set filtered from the whole table may
        # be disconnected, the horizon then becomes two loops, and the resulting shell is broken
        vis = {fid}
        stack = [fid]
        while stack:
            f = stack.pop()
            i, j, k = faces[f]
            for e in ((j, i), (k, j), (i, k)):
                nb = edge_face.get(e)
                if nb is None or nb in vis:
                    continue
                if Q[apex] @ nrm[nb] - off[nb] > eps:
                    vis.add(nb)
                    stack.append(nb)

        # horizon: the directed edges of visible faces whose opposite face is not visible
        horizon = []
        for f in vis:
            i, j, k = faces[f]
            for e in ((i, j), (j, k), (k, i)):
                if edge_face.get((e[1], e[0])) not in vis:
                    horizon.append(e)

        orphans = [del_face(f) for f in vis]
        newf = [add_face(i, j, apex) for (i, j) in horizon]

        pool = np.concatenate(orphans) if orphans else np.zeros(0, np.int64)
        pool = pool[pool != apex]
        for f in newf:
            if not len(pool):
                outside[f] = np.zeros(0, np.int64)
                continue
            m = Q[pool] @ nrm[f] - off[f] > eps
            outside[f] = pool[m]
            pool = pool[~m]
            if len(outside[f]):
                todo.append(f)
    return np.asarray([faces[f] for f in sorted(faces)], np.int64)


def merge_coplanar(P, tri, tol=1e-6):
    """
    Merge coplanar triangles into one polygon. Returns a list of face point numbers.

    Grouping uses the quantized plane equation (nx,ny,nz,d); within a group the directed edges are collected; those whose reverse edge is also
    in the group are interior diagonals, and the rest chained end-to-end form the outline. A group may yield several loops (coplanar but
    disconnected); one face is output per loop.
    """
    if not len(tri):
        return []
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    N = np.cross(B - A, C - A)
    ln = np.linalg.norm(N, axis=1)
    good = ln > 0
    N = np.where(good[:, None], N / np.where(good, ln, 1.0)[:, None], 0.0)
    D = np.einsum("ij,ij->i", N, A)
    scale = max(float(np.abs(P).max()), 1.0)
    # quantization: angle tolerance ~ sqrt(tol), distance tolerance ~ tol*scale. Different faces on a convex hull
    # differ by a lot, so a looser resolution is safer than a tighter one
    ang = max(np.sqrt(float(tol)), 1e-4)
    key = np.c_[np.round(N / ang), np.round(D / (ang * scale))].astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)

    out = []
    for g in range(int(inv.max()) + 1):
        sel = np.nonzero(inv == g)[0]
        if len(sel) == 1:
            out.append([int(x) for x in tri[sel[0]]])
            continue
        de = set()
        for t in sel:
            i, j, k = (int(x) for x in tri[t])
            de |= {(i, j), (j, k), (k, i)}
        nxt = {}
        for (i, j) in de:
            if (j, i) not in de:
                nxt[i] = j
        while nxt:
            s = next(iter(nxt))
            loop = [s]
            v = nxt.pop(s)
            while v != s and v in nxt:
                loop.append(v)
                v = nxt.pop(v)
            if len(loop) >= 3:
                out.append(loop)
    return out


def convex_hull(geo, group="", tol=1e-6, merge_faces=True, max_points=0):
    """
    Convex hull of a point cloud / mesh. Degenerate input drops a dimension (polygon / segment / point), no error.

    merge_faces merges coplanar triangles into polygons -- a cube's hull is 6 quads rather than
    12 triangles. Turn it off for a pure triangle mesh (usually what you want for collision proxies).
    max_points > 0 caps the hull's vertex count (reduce_hull_points: a subset of the points, so it stays inside).
    """
    if geo is None:
        return Geometry()
    P = geo.get(POINT, "P")
    if P is None or geo.npoints == 0:
        return Geometry()
    from .groups import resolve
    sel = resolve(geo, POINT, group)
    Q = np.unique(np.asarray(P, np.float64)[sel], axis=0)
    if len(Q) == 0:
        return Geometry()
    if len(Q) == 1:
        return Geometry.from_points(Q.astype(np.float32))

    tol = float(tol)
    r, V = _rank(Q, tol)
    if r >= 3:
        if int(max_points) > 0:
            tri0 = convex_hull_indices(Q, tol)
            if len(tri0):
                Q = Q[np.unique(tri0)]                 # only the hull's own vertices are candidates
                keep, _ = reduce_hull_points(Q, max_points, tol)
                Q = Q[keep]
        tri = convex_hull_indices(Q, tol)
        if len(tri):
            used = np.unique(tri)
            remap = np.full(len(Q), -1, np.int64)
            remap[used] = np.arange(len(used))
            W = Q[used]
            t2 = remap[tri]
            polys = (merge_coplanar(W, t2, tol) if merge_faces
                     else t2.tolist())
            return Geometry.from_mesh(W.astype(np.float32), polys)
        r = 2                            # can't build a tetrahedron, fall back to planar
    if r == 2:
        c = Q.mean(0)
        uv = (Q - c) @ V[:, :2]
        idx = _hull2d(uv, tol)
        return Geometry.from_mesh(Q[idx].astype(np.float32),
                                  [list(range(len(idx)))])
    # rank 1: a line segment. Take the two endpoints along the principal direction
    t = (Q - Q.mean(0)) @ V[:, 0]
    ends = [int(np.argmin(t)), int(np.argmax(t))]
    if ends[0] == ends[1]:
        return Geometry.from_points(Q[:1].astype(np.float32))
    g = Geometry.from_mesh(Q[ends].astype(np.float32), [[0, 1]])
    g.prim_closed = np.zeros(1, bool)
    return g


def reduce_hull_points(Q, max_points, tol=1e-6):
    """
    pcg111: pick at most max_points of the points Q (n,3) whose convex hull stays as close as possible to the hull
    of all of them -- a collision hull with a vertex budget (Unity rejects convex colliders over 255 triangles, and
    every engine is faster with fewer). Greedy, like a quickhull stopped early: start from the seed tetrahedron, then
    keep adding the point that lies farthest outside the current hull. The result is a subset of Q, so it is inside
    the full hull (never larger) and the leftover error is the distance of the farthest point left outside.
    Returns (indices into Q, max distance of any point of Q outside the reduced hull).
    """
    Q = np.ascontiguousarray(Q, np.float64)
    k = int(max_points)
    n = len(Q)
    if k <= 0 or n <= k:
        return np.arange(n), 0.0
    k = max(k, 4)
    scale = max(float(np.abs(Q).max()), 1.0)
    eps = float(tol) * scale
    tet = _seed_tetra(Q, eps)
    if tet is None:
        return np.arange(n), 0.0
    pick = [int(i) for i in tet]
    err = 0.0
    while True:
        tri = convex_hull_indices(Q[pick], tol)
        if not len(tri):
            break
        A, B, C = (Q[pick][tri[:, j]] for j in range(3))
        N = np.cross(B - A, C - A)
        ln = np.linalg.norm(N, axis=1, keepdims=True)
        ok = ln[:, 0] > 1e-300
        N = N[ok] / ln[ok]
        off = np.einsum("ij,ij->i", N, A[ok])
        d = (Q @ N.T - off).max(1)                  # distance outside the reduced hull (<= 0 inside)
        j = int(np.argmax(d))
        err = max(float(d[j]), 0.0)
        if len(pick) >= k or err <= eps:
            break
        pick.append(j)
    return np.asarray(pick, np.int64), err
