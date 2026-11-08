"""
Divide SOP -- split polygons into smaller ones, or the reverse: merge them / take the dual.

Four independent operations:

    Convex Polygons        split ngons into faces with <= N edges (N=3 is triangulation)
    Triangulate Non-Planar force-triangulate non-planar primitives
    Remove Shared Edges    the reverse: remove interior edges and merge primitives back into big ngons
    Compute Dual           take the dual mesh; primitive centers become points, points become primitives

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why not reuse Convert(PCG)'s triangulation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
core.triangles() is fan triangulation: connect point 0 to every other point. Fine for convex polygons,
but concave polygons grow triangles that stick out of the shape -- and concave ngons are everywhere in the output of
boolean, polybevel and carve; the README lists this as a known limitation too.

Divide is the node in Houdini **dedicated** to this job, so here we do it right: test convexity first; convex ones
go through the fan (O(n), and the vast majority of primitives are convex); concave ones go through **ear clipping**, cutting only true ears
(convex corner at the vertex + no other vertex inside the triangle), so the result always lies inside the original polygon.

No mapbox_earcut: a 60-line ear clipping implementation covers everything needed here, while one more
dependency that needs compiling would leave ComfyUI portable users unable to install.

The ear selection strategy maps to Houdini's two toggles: by default take the first valid ear (fastest);
Avoid Small Angles takes the ear whose "smallest interior angle is largest"; Don't Generate Slivers puts
ears with tiny area last. With both on, ears are ranked by smallest angle, and too-small area is an outright veto.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bricker, and Smooth which isn't implemented
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
* Bricker Polygons uses clip.py's plane-cutting machinery (clip.bricker): cuts primitives into bricks with three sets of
  parallel planes spaced by Brick Size; new vertex attributes are interpolated along edges. (This docstring once still said "not implemented".)
* Smooth Polygons is not implemented -- that is subdivision, not splitting; use the Subdivide node.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .groups import resolve
from .topology import topology
from .ops import prim_normals, _gather_blocks, euler_matrix, match_names


# ═══════════════════════════════════════════════════════════════ planarize / convexity test
def _plane_basis(P):
    """(n,3) -> (n,2) local coordinates on the best-fit plane."""
    c = P.mean(0)
    Q = (P - c).astype(np.float64)
    try:
        _, _, vt = np.linalg.svd(Q, full_matrices=False)
        ax1, ax2 = vt[0], vt[1]
    except np.linalg.LinAlgError:
        ax1, ax2 = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    return np.stack([Q @ ax1, Q @ ax2], 1)


def _signed_area(V):
    x, y = V[:, 0], V[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _is_convex(V, eps=1e-12):
    a = V
    b = np.roll(V, -1, axis=0)
    c = np.roll(V, -2, axis=0)
    cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - b[:, 1]) - \
         (b[:, 1] - a[:, 1]) * (c[:, 0] - b[:, 0])
    nz = cr[np.abs(cr) > eps]
    return len(nz) == 0 or bool((nz > 0).all() or (nz < 0).all())


def _fan(n, k):
    """Split a convex polygon into k-gons: take [0, i .. i+k-2] chunk by chunk. k=3 is an ordinary fan."""
    if n <= k:
        return [list(range(n))]
    out, i = [], 1
    while i < n - 1:
        j = min(i + k - 2, n - 1)
        out.append([0] + list(range(i, j + 1)))
        i = j
    return out


# ═══════════════════════════════════════════════════════════════ ear clipping
def _tri_min_angle(a, b, c):
    """Negated cosine of the triangle's smallest interior angle -- larger means "fatter". Using cosines saves three arccos calls."""
    e = [b - a, c - b, a - c]
    l = [float(np.hypot(*v)) for v in e]
    if min(l) < 1e-15:
        return -1.0
    cs = [
        -float(np.dot(e[0], e[2])) / (l[0] * l[2]),
        -float(np.dot(e[1], e[0])) / (l[1] * l[0]),
        -float(np.dot(e[2], e[1])) / (l[2] * l[1]),
    ]
    return -max(cs)          # largest cosine = smallest angle


def _point_in_tri(p, a, b, c, eps=1e-14):
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    neg = (d1 < -eps) or (d2 < -eps) or (d3 < -eps)
    pos = (d1 > eps) or (d2 > eps) or (d3 > eps)
    return not (neg and pos)


def _ear_clip(V, avoid_slivers=False, avoid_small_angles=False):
    """
    Ear-clipping triangulation of a simple polygon. V is (n,2); returns a number of (i,j,k) local index triples.

    Ear = convex corner at the vertex, with no other vertex inside the triangle. Clip one at a time, finishing with the last three points.
    When no ear can be found at all (self-intersecting / degenerate), fall back to a fan so there is always output -- a triangulation failure
    throwing mid-pipeline is worse than a few skewed triangles.
    """
    n = len(V)
    idx = list(range(n))
    # Ear clipping requires counter-clockwise order. If the polygon is clockwise in this 2D basis, flip it first and flip back after clipping --
    # otherwise the clipped triangles' winding is opposite to the source primitive and the normals all face inward
    flipped = _signed_area(V) < 0
    if flipped:
        idx.reverse()
    scan = avoid_slivers or avoid_small_angles
    area_eps = max(abs(_signed_area(V)), 1e-30) * 1e-6

    tris = []
    while len(idx) > 3:
        best, best_score = -1, -np.inf
        m = len(idx)
        for a in range(m):
            i0, i1, i2 = idx[a - 1], idx[a], idx[(a + 1) % m]
            A, B, C = V[i0], V[i1], V[i2]
            cr = (B[0] - A[0]) * (C[1] - B[1]) - (B[1] - A[1]) * (C[0] - B[0])
            if cr <= 0:                        # concave corner, not an ear
                continue
            if any(_point_in_tri(V[j], A, B, C)
                   for j in idx if j not in (i0, i1, i2)):
                continue
            if not scan:                       # no selection: clip the first valid ear
                best = a
                break
            area = 0.5 * cr
            score = _tri_min_angle(A, B, C) if avoid_small_angles else area
            if avoid_slivers and area < area_eps:
                score -= 1e6                   # very thin ears go last
            if score > best_score:
                best_score, best = score, a
        if best < 0:                           # degenerate: finish with a fan
            break
        a = best
        m = len(idx)
        tris.append((idx[a - 1], idx[a], idx[(a + 1) % m]))
        idx.pop(a)

    if len(idx) == 3:
        tris.append(tuple(idx))
    elif len(idx) > 3:
        tris.extend((idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1))
    return [t[::-1] for t in tris] if flipped else tris


def _ear_clip_quads(P4):
    """
    Vectorized version of _plane_basis + _ear_clip (the no-ear-selection mode) for **a batch of quads**.
    P4 (Q,4,3) -> (Q,2,3) local-index triangles; if SVD fails to converge (nan and the like) returns None,
    and the caller falls back to per-quad ear clipping.

    Why it's worth writing separately: concave / twisted quads used to go one by one into Python ear clipping, one
    SVD and a dozen small array ops per quad. For rough heightfield meshes (the non-planar quads out of HeightField to Mesh),
    over 30% of the projections onto the best-fit plane are classed as "concave", and at 1024^2 that's hundreds of thousands of loop iterations --
    COP HF Project (Transform 3D) spent over half its time here on real hardware.

    The logic copies _ear_clip's behaviour at n = 4 step by step:
      1. project onto the best-fit plane (batched SVD, same LAPACK routine as the per-quad calls)
      2. if the signed area < 0, reverse the vertex loop (idx = 3,2,1,0)
      3. find the first ear in order a = 0,1,2,3: corner cr > 0, and the one remaining vertex not inside the triangle
         (_point_in_tri's eps = 1e-14)
      4. clip it, finish with the remaining three points in loop order; with no ear at all, fan (0,1,2)(0,2,3)
      5. if flipped, reverse each triangle back
    Numerically, the projected coordinates use a batched matrix multiply, whose summation order may differ from the per-quad calls by one ulp. For
    quads where every **decision quantity** (signed area, the cr of the four corners, the three d's of point-in-triangle) is farther
    than 1e-9 x scale^2 from its threshold, one ulp can't flip any decision and the result is identical to per-quad ear clipping;
    those too close to a threshold (degenerate quads with three collinear points, duplicate points, zero area and the like) are marked unsafe and the caller
    sends them back to per-quad ear clipping. The first version lacked this step: among random quads on an integer lattice, 3% chose the other
    diagonal -- the per-quad version computed cr = 0.0 (collinear, not an ear), the batched version computed 1.1e-16,
    and cut out a zero-area triangle.

    Returns (tris (Q,2,3), unsafe (Q,) bool); returns None if SVD fails.
    """
    Q = P4.shape[0]
    c = P4.mean(1)
    D = (P4 - c[:, None, :]).astype(np.float64)
    try:
        _, _, vt = np.linalg.svd(D, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    V = np.stack([np.einsum("qij,qj->qi", D, vt[:, 0]),
                  np.einsum("qij,qj->qi", D, vt[:, 1])], -1)      # (Q,4,2)
    x, y = V[..., 0], V[..., 1]
    area2 = (x * np.roll(y, -1, 1)).sum(1) - (y * np.roll(x, -1, 1)).sum(1)
    flipped = area2 < 0
    idx = np.where(flipped[:, None], np.array([3, 2, 1, 0]),
                   np.array([0, 1, 2, 3]))                          # (Q,4)
    ar = np.arange(Q)
    W = V[ar[:, None], idx]                                        # ordered by idx
    ear = np.full(Q, -1, np.int64)
    s2 = np.maximum((V * V).sum(-1).max(1), 1e-300)
    dlt = 1e-9 * s2
    unsafe = np.abs(area2) < dlt
    for a in range(4):
        A, B, C = W[:, (a - 1) % 4], W[:, a], W[:, (a + 1) % 4]
        Pj = W[:, (a + 2) % 4]
        cr = (B[:, 0] - A[:, 0]) * (C[:, 1] - B[:, 1]) - \
            (B[:, 1] - A[:, 1]) * (C[:, 0] - B[:, 0])
        e = 1e-14
        d1 = (Pj[:, 0] - B[:, 0]) * (A[:, 1] - B[:, 1]) - \
            (A[:, 0] - B[:, 0]) * (Pj[:, 1] - B[:, 1])
        d2 = (Pj[:, 0] - C[:, 0]) * (B[:, 1] - C[:, 1]) - \
            (B[:, 0] - C[:, 0]) * (Pj[:, 1] - C[:, 1])
        d3 = (Pj[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - \
            (C[:, 0] - A[:, 0]) * (Pj[:, 1] - A[:, 1])
        # The three terms of d are signed areas of the same point triples as the adjacent corners' cr (only the operation order differs), so
        # at normal scales the d check is covered by the cr check (this term is an equivalent mutant in mutation testing).
        # It stays for very small quads: there _point_in_tri's **absolute** threshold 1e-14 is larger than
        # 1e-9 x scale^2, and when d sits right at +-1e-14 the cr check doesn't catch it
        unsafe |= (np.abs(cr) < dlt) | (np.abs(d1) < e + dlt) | \
            (np.abs(d2) < e + dlt) | (np.abs(d3) < e + dlt)
        neg = (d1 < -e) | (d2 < -e) | (d3 < -e)
        pos = (d1 > e) | (d2 > e) | (d3 > e)
        inside = ~(neg & pos)
        ok = (cr > 0) & ~inside & (ear < 0)
        ear[ok] = a
    # position (index within idx) -> triangle. Clipping ear a: (a-1, a, a+1); the rest is
    # the three left after removing a from idx, in original order
    tri_pos = np.empty((Q, 2, 3), np.int64)
    has = ear >= 0
    a = np.where(has, ear, 0)
    tri_pos[:, 0, 0] = (a - 1) % 4
    tri_pos[:, 0, 1] = a
    tri_pos[:, 0, 2] = (a + 1) % 4
    rest = np.array([[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]])
    tri_pos[:, 1] = rest[a]
    # no ear: fan (0,1,2)(0,2,3)
    tri_pos[~has, 0] = (0, 1, 2)
    tri_pos[~has, 1] = (0, 2, 3)
    tris = np.take_along_axis(idx[:, None, :].repeat(2, 1), tri_pos, 2)
    tris[flipped] = tris[flipped][:, :, ::-1]
    return tris, unsafe


def _merge_to_max(V, tris, max_edges):
    """
    Greedily merge the triangulation back into convex polygons with <= max_edges edges.

    Only merge across **diagonals** (the original polygon's edges can't be removed), and the merged result must still be convex --
    these two rules guarantee the result covers the same region as the original polygon, with no self-intersection or spanning a concave notch.
    """
    polys = [list(t) for t in tris]
    changed = True
    while changed:
        changed = False
        edge_of = {}
        for pi, p in enumerate(polys):
            if p is None:
                continue
            for k in range(len(p)):
                edge_of.setdefault(frozenset((p[k], p[(k + 1) % len(p)])),
                                   []).append(pi)
        for key, owners in edge_of.items():
            if len(owners) != 2:
                continue
            i, j = owners
            pi, pj = polys[i], polys[j]
            if pi is None or pj is None:
                continue
            if len(pi) + len(pj) - 2 > max_edges:
                continue
            merged = _merge_pair(pi, pj, key)
            if merged is None or len(merged) > max_edges:
                continue
            if not _is_convex(V[merged]):
                continue
            polys[i] = merged
            polys[j] = None
            changed = True
            break
    return [p for p in polys if p is not None]


def _merge_pair(p, q, key):
    """Join two polygons into one along a shared edge. The shared edge must be traversed in **opposite** directions on the two sides."""
    a, b = tuple(key)
    def find(poly, u, v):
        for k in range(len(poly)):
            if poly[k] == u and poly[(k + 1) % len(poly)] == v:
                return k
        return -1
    kp = find(p, a, b)
    if kp >= 0:
        kq = find(q, b, a)
        _u, _v = a, b
    else:
        kp = find(p, b, a)
        kq = find(q, a, b)
        _u, _v = b, a
    if kp < 0 or kq < 0:
        return None
    # walk p from v all the way back to u (both ends of the shared edge kept), then append the part of q other than these two points
    out = [p[(kp + 1 + t) % len(p)] for t in range(len(p))]
    out += [q[(kq + 2 + t) % len(q)] for t in range(len(q) - 2)]
    return out if len(out) == len(set(out)) else None


# ═══════════════════════════════════════════════════════════ rebuild from corners
def _rebuild(geo, faces, src_prim, closed):
    """List-form entry point; internally converted to flat arrays and routed through _rebuild_flat."""
    if not faces:
        return _rebuild_flat(geo, np.zeros(0, np.int64), np.zeros(0, np.int64),
                             np.zeros(0, np.int64), np.zeros(0, bool))
    return _rebuild_flat(
        geo, np.concatenate([np.asarray(f, np.int64) for f in faces]),
        np.array([len(f) for f in faces], np.int64),
        np.asarray(src_prim, np.int64), np.asarray(closed, bool))


def _rebuild_flat(geo, src_corner, sizes, src_prim, closed):
    """
    Rebuild geometry from new primitives expressed as "original corner indices".

    This is the same route convert_prims uses: each corner of a new primitive points back to some original corner,
    so vertex attributes are taken via the corner and prim attributes via the source prim, and points don't move at all.
    Output is stably sorted by source prim -- the small primitives cut from one primitive sit where it originally was, rather than
    piling up at the end, so downstream lookups by prim number don't get misaligned.
    """
    if not len(sizes):
        out = geo.copy()
        out.set_topology(np.zeros(0, np.int32), np.zeros(1, np.int32),
                         np.zeros(0, bool))
        out.attribs[VERTEX], out.attribs[PRIM] = {}, {}
        out.groups[VERTEX], out.groups[PRIM] = {}, {}
        return out

    order = np.argsort(src_prim, kind="stable")
    old_start = np.concatenate([[0], np.cumsum(sizes)])[:-1]
    sz = sizes[order]
    new_off = np.concatenate([[0], np.cumsum(sz)]).astype(np.int32)
    corner = src_corner[_gather_blocks(old_start[order], sz)]
    sp = src_prim[order]

    out = Geometry()
    out._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    out.set_topology(geo.vertex_point[corner], new_off, closed[order],
                     geo.prim_type[sp])
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[corner], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[corner])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[sp], owned=True)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[sp])
    out.prim_data = geo.remap_prim_data(sp)
    out.edge_groups = dict(geo.edge_groups)      # point numbers unchanged
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


# ═══════════════════════════════════════════════════════════════ the individual toggles
def nonplanar_mask(geo, tol=1e-4):
    """
    A primitive counts as non-planar when its maximum deviation from its own best-fit plane exceeds tol.

    "Best-fit plane" = through the centroid, with the Newell normal as its normal. For non-planar polygons Newell gives exactly the
    least-squares best normal, so this deviation basically matches an SVD fit, without a separate decomposition per primitive
    -- on a 100k-primitive mesh it's the difference between 0.9 s and 0.02 s.
    """
    n = geo.nprims
    if not n or not geo.nvertices:
        return np.zeros(max(n, 0), bool)
    P = geo.get(POINT, "P")
    vp, vprim = geo.vertex_point, geo.vertex_prim()
    pn = prim_normals(geo)
    c = np.zeros((n, 3), np.float64)
    np.add.at(c, vprim, P[vp])
    c /= np.maximum(geo.prim_sizes(), 1)[:, None]
    dev = np.abs(np.einsum("ij,ij->i", P[vp] - c[vprim], pn[vprim].astype(np.float64)))
    mx = np.zeros(n)
    np.maximum.at(mx, vprim, dev)
    return (mx > float(tol)) & geo.prim_closed & (geo.prim_sizes() > 3)


def convex_mask(geo, eps=1e-7):
    """
    Whether each primitive is convex. Criterion: walking once around the vertex loop, the turn at every corner relative to the primitive normal must
    have the same sign. The turn amount is normalized by sin, so the threshold is independent of the primitive's scale.

    Vectorization is a must: convex primitives go through the fan and only concave ones through ear clipping, and if the "which primitives are convex" step
    were a per-primitive Python loop, all the time saved would be spent again.
    """
    n = geo.nprims
    if not n or not geo.nvertices:
        return np.ones(max(n, 0), bool)
    P = geo.get(POINT, "P").astype(np.float64)
    vp, vprim = geo.vertex_point, geo.vertex_prim()
    nxt = geo.next_corner()
    nn = nxt[nxt]
    e1 = P[vp[nxt]] - P[vp]
    e2 = P[vp[nn]] - P[vp[nxt]]
    cr = np.cross(e1, e2)
    l = np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1)
    s = np.einsum("ij,ij->i", cr, prim_normals(geo).astype(np.float64)[vprim])
    s /= np.where(l == 0, 1, l)
    pos = np.bincount(vprim, weights=(s > eps).astype(np.float64),
                      minlength=n) > 0
    neg = np.bincount(vprim, weights=(s < -eps).astype(np.float64),
                      minlength=n) > 0
    return ~(pos & neg)


def convex_polygons(geo, group="", max_edges=3, triangulate_nonplanar=False,
                    planar_tol=1e-4, avoid_slivers=False,
                    avoid_small_angles=False, do_convex=True):
    """
    Split primitives down to <= max_edges edges. Non-planar primitives (if that option is on) are always split into triangles --
    a non-planar quad has no unique "plane"; only triangles can be said to be coplanar.

    Three routes, an order of magnitude apart in speed:
      primitives left alone   gathered as a block, no loop
      convex ones to split    primitives with the same edge count share one fan template, bucketed by size and broadcast
      concave ones to split   only these are ear-clipped one by one
    In real meshes the third kind is a minority, so triangulating a 100k-primitive quad mesh takes a fraction of a second.
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    sel = resolve(geo, PRIM, group)
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    P = geo.get(POINT, "P")

    target = np.where(bool(do_convex), max(3, int(max_edges)), sizes)
    if triangulate_nonplanar:
        target = np.where(nonplanar_mask(geo, planar_tol), 3, target)
    todo = sel & geo.prim_closed & (sizes > target) & (sizes > 3)
    if not todo.any():
        return geo.copy()

    conv = convex_mask(geo)
    keep = np.nonzero(~todo)[0]
    parts_corner = [_gather_blocks(starts[keep], sizes[keep])]
    parts_size = [sizes[keep]]
    parts_src = [keep]
    parts_closed = [geo.prim_closed[keep]]

    # --- convex primitives: bucket by (edge count, target edge count); each bucket shares one template ---
    fast = np.nonzero(todo & conv)[0]
    for n_, k_ in {(int(sizes[i]), int(target[i])) for i in fast}:
        sub = fast[(sizes[fast] == n_) & (target[fast] == k_)]
        pat = _fan(n_, k_)
        flat = np.concatenate([np.asarray(p, np.int64) for p in pat])
        psz = np.array([len(p) for p in pat], np.int64)
        parts_corner.append((starts[sub][:, None] + flat[None, :]).reshape(-1))
        parts_size.append(np.tile(psz, len(sub)))
        parts_src.append(np.repeat(sub, len(pat)))
        parts_closed.append(np.ones(len(sub) * len(pat), bool))

    # --- concave primitives: quads to triangles go through batched ear clipping (_ear_clip_quads), the rest one by one ---
    slow = np.nonzero(todo & ~conv)[0]
    if not (avoid_slivers or avoid_small_angles):
        q4 = slow[(sizes[slow] == 4) & (target[slow] == 3)]
        if len(q4) > 16:
            corners = starts[q4][:, None] + np.arange(4)[None, :]
            res = _ear_clip_quads(np.asarray(P, np.float64)[
                geo.vertex_point[corners]])
            if res is not None:
                tq, unsafe = res
                ok = ~unsafe
                q_ok = q4[ok]
                parts_corner.append((starts[q_ok][:, None, None] + tq[ok])
                                    .reshape(-1))
                parts_size.append(np.full(2 * len(q_ok), 3, np.int64))
                parts_src.append(np.repeat(q_ok, 2))
                parts_closed.append(np.ones(2 * len(q_ok), bool))
                slow = np.setdiff1d(slow, q_ok)
    for i in slow:
        base, k_ = int(starts[i]), int(target[i])
        V = _plane_basis(P[geo.prim_points(i)])
        tris = _ear_clip(V, avoid_slivers, avoid_small_angles)
        pieces = [list(t) for t in tris]
        if k_ > 3:
            pieces = _merge_to_max(V, pieces, k_)
        parts_corner.append(np.concatenate(
            [np.asarray(p, np.int64) + base for p in pieces]))
        parts_size.append(np.array([len(p) for p in pieces], np.int64))
        parts_src.append(np.full(len(pieces), i, np.int64))
        parts_closed.append(np.ones(len(pieces), bool))

    return _rebuild_flat(geo, np.concatenate(parts_corner),
                         np.concatenate(parts_size),
                         np.concatenate(parts_src),
                         np.concatenate(parts_closed))


def remove_shared_edges(geo, group=""):
    """
    Remove interior edges and merge connected primitives into one big ngon -- Divide's reverse mode.

    The approach: group the selected primitives into regions by shared edges, then chain each region's **boundary half-edges** end-to-end into loops.
    Only regions that yield exactly **one** loop are merged: two loops means the region has a hole, and in this data model
    a prim only has one vertex loop, so it can't store a face with a hole. Such regions are left as they are, not forced.
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    sel = resolve(geo, PRIM, group) & geo.prim_closed
    if sel.sum() < 2:
        return geo.copy()

    t = topology(geo)
    nxt = geo.next_corner()
    vprim = geo.vertex_prim()
    vp = geo.vertex_point

    # connected pieces among primitives: sharing a manifold edge whose both sides are selected counts as connected
    lab = np.arange(geo.nprims, dtype=np.int64)
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        h1 = t.edge_he[t.edge_he_off[two]]
        h2 = t.edge_he[t.edge_he_off[two] + 1]
        f1, f2 = vprim[h1], vprim[h2]
        ok = sel[f1] & sel[f2]
        a, b = f1[ok], f2[ok]
        for _ in range(64):
            prev = lab
            m = np.minimum(lab[a], lab[b])
            lab = lab.copy()
            np.minimum.at(lab, a, m)
            np.minimum.at(lab, b, m)
            lab = lab[lab]
            if np.array_equal(lab, prev):
                break

    # interior half-edges: the opposite exists and both sides are in the same region -- these edges get removed
    tw = t.he_twin
    has = tw >= 0
    interior = np.zeros(geo.nvertices, bool)
    interior[has] = (lab[vprim[has]] == lab[vprim[tw[has]]]) \
        & sel[vprim[has]] & sel[vprim[tw[has]]]

    faces, src, closed = [], [], []
    sizes = geo.prim_sizes()
    starts = geo.prim_offset[:-1]
    done = set()
    for i in range(geo.nprims):
        if not sel[i]:
            faces.append(list(range(int(starts[i]), int(starts[i] + sizes[i]))))
            src.append(i); closed.append(bool(geo.prim_closed[i]))
            continue
        L = int(lab[i])
        if L in done:
            continue
        done.add(L)
        block = np.nonzero((lab == L) & sel)[0]
        corners = _gather_blocks(starts[block], sizes[block])
        bnd = [int(c) for c in corners if not interior[c]]
        if not bnd:                       # closed shell, no boundary loop, can't merge
            for j in block:
                faces.append(list(range(int(starts[j]), int(starts[j] + sizes[j]))))
                src.append(int(j)); closed.append(True)
            continue
        # chain boundary half-edges end-to-end: from c to vp[nxt[c]]; the next one starts from that point
        by_start = {}
        for c in bnd:
            by_start.setdefault(int(vp[c]), []).append(c)
        loops, used = [], set()
        for c0 in bnd:
            if c0 in used:
                continue
            loop, c = [], c0
            while True:
                used.add(c); loop.append(c)
                nxts = by_start.get(int(vp[int(nxt[c])]), [])
                nxts = [x for x in nxts if x not in used]
                if not nxts:
                    break
                c = nxts[0]
            loops.append(loop)
        if len(loops) == 1 and len(loops[0]) == len(bnd):
            faces.append(loops[0])
            src.append(int(block[0])); closed.append(True)
        else:                             # has holes or not closed: keep as is
            for j in block:
                faces.append(list(range(int(starts[j]), int(starts[j] + sizes[j]))))
                src.append(int(j)); closed.append(True)
    return _rebuild(geo, faces, src, closed)


def compute_dual(geo, swap_attribs="* ^P"):
    """
    Dual mesh: each primitive becomes a point (its center), each **interior** point becomes a primitive (the centers around it).

    Only interior points are handled -- boundary points don't go all the way around, and Houdini doesn't produce them either. Going around uses the
    half-edge twins: take a half-edge leaving the point, jump to the opposite edge, then take the next corner, and you've turned
    onto the adjacent primitive; one full turn comes back to the start.

    swap_attribs corresponds to "Attributes to Swap": matching prim attributes become new point attributes,
    matching point attributes become new prim attributes -- a "swap" in the true sense.
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return Geometry()
    t = topology(geo)
    nxt = geo.next_corner()
    vprim = geo.vertex_prim()
    vp = geo.vertex_point
    P = geo.get(POINT, "P")

    # new points = primitive centers
    centers = np.zeros((geo.nprims, 3), np.float32)
    np.add.at(centers, vprim, P[vp])
    centers /= np.maximum(geo.prim_sizes(), 1)[:, None]

    # half-edges leaving each point
    order = np.argsort(vp, kind="stable")
    cnt = np.bincount(vp, minlength=geo.npoints)
    off = np.concatenate([[0], np.cumsum(cnt)]).astype(np.int64)
    tw = t.he_twin

    faces, src_pt = [], []
    for p in range(geo.npoints):
        hs = order[off[p]:off[p + 1]]
        if len(hs) < 3:
            continue
        start = int(hs[0])
        loop, h, ok = [], start, True
        for _ in range(len(hs) + 1):
            loop.append(int(vprim[h]))
            prev = int(h)
            # turn onto the adjacent primitive: go via the twin, then take its outgoing edge at the same point
            tprev = int(tw[prev])
            if tprev < 0:
                ok = False
                break
            h = int(nxt[tprev])
            if h == start:
                break
            if vp[h] != p:
                ok = False
                break
        else:
            ok = False
        if ok and len(loop) == len(hs) and len(loop) >= 3:
            faces.append(loop)
            src_pt.append(p)
    if not faces:
        return Geometry.from_points(centers)

    out = Geometry()
    out._resize_points(geo.nprims)
    out.set(POINT, "P", centers, owned=True)
    sizes = np.array([len(f) for f in faces], np.int64)
    out.set_topology(np.concatenate([np.asarray(f, np.int32) for f in faces]),
                     np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                     np.ones(len(faces), bool))

    # attribute swap: prim -> point, point -> prim
    src_pt = np.asarray(src_pt, np.int64)
    for name in match_names(list(geo.attribs[PRIM].keys()), swap_attribs):
        out.set(POINT, name, geo.attribs[PRIM][name], owned=False)
    for name in match_names(list(geo.attribs[POINT].keys()), swap_attribs):
        out.set(PRIM, name, geo.attribs[POINT][name][src_pt], owned=True)
    for name, v in geo.groups[PRIM].items():
        out.set_group(POINT, name, v)
    for name, v in geo.groups[POINT].items():
        out.set_group(PRIM, name, v[src_pt])
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


# ═══════════════════════════════════════════════════════════════ main entry point
def divide(geo, group="", convex=True, max_edges=3,
           triangulate_nonplanar=True, planar_tol=1e-4,
           avoid_slivers=False, avoid_small_angles=False,
           brick=False, brick_size=(1.0, 1.0, 1.0),
           brick_offset=(0.0, 0.0, 0.0), brick_angle=(0.0, 0.0, 0.0),
           brick_shared_edges=True,
           remove_shared=False, dual=False, swap_attribs="* ^P"):
    """
    Order = Houdini's order: split first, then brick, then remove shared edges, and finally take the dual.

    All off is a pass-through. remove_shared together with convex / brick is a meaningful combination:
    chop it up, do something, then merge back.
    """
    g = geo
    if convex or triangulate_nonplanar:
        g = convex_polygons(g, group, max_edges, triangulate_nonplanar,
                            planar_tol, avoid_slivers, avoid_small_angles,
                            convex)
    if brick:
        # lazy import: clip depends on this module's ear clipping and convexity test; importing at the top would be circular
        from . import clip as _clip
        g = _clip.bricker(g, group, brick_size, brick_offset, brick_angle,
                          brick_shared_edges)
    if remove_shared:
        g = remove_shared_edges(g, group)
    if dual:
        g = compute_dual(g, swap_attribs)
    return g.copy() if g is geo else g
