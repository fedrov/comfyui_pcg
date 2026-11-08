"""
Shared spatial-query layer -- bucket grid / closest point / ray intersection.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why a separate layer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scatter's relaxation, Fuse's merging, Attribute Transfer's sampling and Ray's projection really ask
the same three questions: "who is within the radius", "who is closest", "what does this ray hit". Previously each module wrote its own
grid hash, and fixing one bug meant fixing it three times. Unified here.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Keys use an **exact linear index**, not a hash
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The old `(x*73856093) ^ (y*19349663) ^ (z*83492791)` collides: two unrelated cells
land on the same key. For "pairs within a radius" that only adds a few candidates, filtered away by the exact distance; but for
a **per-sample weighted** operator like Attribute Transfer, duplicated pairs from collisions count the same source point twice,
and the weights are wrong. Deduplicating needs a sort, which costs more than not colliding.

Changed to key = ((i+OFF) * 2^20 + (j+OFF)) * 2^20 + (k+OFF): each coordinate gets 20 bits,
the product 2^60 < 2^63 does not overflow, and **different cells always get different keys**. Coordinates are first clamped to ±2^19; points out of range
merge into the border cell -- clamping is monotonic, two points ≤ 1 cell apart are still ≤ 1 cell apart after clamping, and the query's
27-neighbourhood still covers them, just with a few more candidates.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Closest point uses **multiple resolutions**, not an enlarged neighbourhood
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Where is the closest triangle" has no a-priori radius. Enlarging the search neighbourhood (±1 -> ±2 -> ±4) costs
(2m+1)^3, i.e. 729 lookups at m=4. Instead: **double the cell size, neighbourhood always ±1**: rebuilding the buckets each round
is O(T), but there are always only 27 lookups, and once cells get large few unresolved points remain.

Criterion: with cell size h this round, if the current best distance ≤ h, the answer is settled -- anything within distance h
differs by at most 1 in cell coordinates, so it must be in the ±1 neighbourhood, and every item is bucketed into **all** cells its AABB covers.
"""
from __future__ import annotations

import numpy as np
from itertools import chain

from .npcompat import select as _select  # np.select breaks if a node pack rebinds np.bool

from .core import VERTEX, PRIM
from .groups import resolve
from .ops import _gather_blocks

_OFF = 1 << 19
_BITS = 1 << 20
# An item whose AABB spans this many cells is not bucketed; it is kept separately as a "large item" and compared against every query.
# Without this cap, one giant triangle spanning the whole scene would stuff hundreds of thousands of records into the buckets.
_MAX_CELLS_PER_ITEM = 256
_CHUNK = 1 << 18                       # query chunking, bounds peak memory of candidate pairs


def cell_key(c):
    """(N,3) integer cell coordinates -> (N,) int64 unique keys."""
    c = np.clip(np.asarray(c, np.int64), -_OFF + 1, _OFF - 1) + _OFF
    return (c[:, 0] * _BITS + c[:, 1]) * _BITS + c[:, 2]


class Bucket:
    """Inverted index bucketed by key. Construction O(n log n), queries are pure searchsorted + gather."""
    __slots__ = ("uniq", "starts", "counts", "items")

    def __init__(self, keys, items):
        keys = np.asarray(keys, np.int64).reshape(-1)
        items = np.asarray(items, np.int64).reshape(-1)
        order = np.argsort(keys, kind="stable")
        ks = keys[order]
        self.items = items[order]
        if len(ks):
            uniq, starts = np.unique(ks, return_index=True)
            self.uniq = uniq
            self.starts = starts.astype(np.int64)
            self.counts = (np.append(starts[1:], len(ks)).astype(np.int64)
                           - self.starts)
        else:
            self.uniq = np.zeros(0, np.int64)
            self.starts = np.zeros(0, np.int64)
            self.counts = np.zeros(0, np.int64)

    def query(self, qkeys, qidx):
        """qkeys/qidx have equal length. Returns two parallel arrays (query index, item hit)."""
        z = np.zeros(0, np.int64)
        if not len(self.uniq) or not len(qkeys):
            return z, z.copy()
        pos = np.searchsorted(self.uniq, qkeys)
        pc = np.clip(pos, 0, len(self.uniq) - 1)
        hit = np.nonzero((pos < len(self.uniq)) & (self.uniq[pc] == qkeys))[0]
        if not len(hit):
            return z, z.copy()
        p = pos[hit]
        cnt = self.counts[p]
        return (np.repeat(np.asarray(qidx, np.int64)[hit], cnt),
                self.items[_gather_blocks(self.starts[p], cnt)])


_NEIGH27 = np.array([(dx, dy, dz) for dx in (-1, 0, 1)
                     for dy in (-1, 0, 1) for dz in (-1, 0, 1)], np.int64)


def _box_bucket(lo, hi, h):
    """
    Lay items into cells of size h by AABB. Returns (Bucket, item indices of large items).

    Cells spanned = product of span over the three axes; one repeat + modulo/division flattens the variable-length triple loop
    into one dimension, with no Python loop.
    """
    n = len(lo)
    if n == 0:
        return Bucket(np.zeros(0, np.int64), np.zeros(0, np.int64)), \
            np.zeros(0, np.int64)
    clo = np.floor(lo / h).astype(np.int64)
    chi = np.floor(hi / h).astype(np.int64)
    span = np.maximum(chi - clo + 1, 1)
    cnt = span.prod(1)
    big = np.nonzero(cnt > _MAX_CELLS_PER_ITEM)[0]
    sel = np.nonzero(cnt <= _MAX_CELLS_PER_ITEM)[0]
    if not len(sel):
        return Bucket(np.zeros(0, np.int64), np.zeros(0, np.int64)), big
    c = cnt[sel]
    tot = int(c.sum())
    owner = np.repeat(sel, c)
    off = np.concatenate([[0], np.cumsum(c)])
    local = np.arange(tot, dtype=np.int64) - np.repeat(off[:-1], c)
    sx = np.repeat(span[sel, 0], c)
    sy = np.repeat(span[sel, 1], c)
    i = local % sx
    j = (local // sx) % sy
    k = local // (sx * sy)
    cells = np.repeat(clo[sel], c, axis=0) + np.stack([i, j, k], 1)
    return Bucket(cell_key(cells), owner), big


# ═══════════════════════════════════════════════════════ pairs within radius (point vs point)
def neighbors_within(Q, P, radius):
    """
    Returns (query point index, source point index, distance), only pairs with distance ≤ radius.

    Q and P are two different point sets (for self-pairing pass the same array; i==j is included and the caller filters it).
    """
    z = np.zeros(0, np.int64)
    Q = np.asarray(Q, np.float64).reshape(-1, 3)
    P = np.asarray(P, np.float64).reshape(-1, 3)
    if not len(Q) or not len(P) or radius <= 0:
        return z, z.copy(), np.zeros(0)
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        cKDTree = None
    if cKDTree is not None:
        # scipy's KD tree does the pair search in C (10-50x the bucket path below). Output sorted by (query, source)
        # so the order is deterministic and independent of the tree layout.
        tp = cKDTree(P)
        tq = tp if Q is P else cKDTree(Q)
        r = tq.sparse_distance_matrix(tp, float(radius), output_type="ndarray")
        qi, pi, d = r["i"].astype(np.int64), r["j"].astype(np.int64), r["v"].astype(np.float64)
        o = np.lexsort((pi, qi))
        return qi[o], pi[o], d[o]
    b = Bucket(cell_key(np.floor(P / radius).astype(np.int64)),
               np.arange(len(P)))
    qa, pa, da = [], [], []
    for s in range(0, len(Q), _CHUNK):
        idx = np.arange(s, min(s + _CHUNK, len(Q)), dtype=np.int64)
        c = np.floor(Q[idx] / radius).astype(np.int64)
        for d in _NEIGH27:
            qi, pi = b.query(cell_key(c + d), idx)
            if not len(qi):
                continue
            dist = np.linalg.norm(Q[qi] - P[pi], axis=1)
            m = dist <= radius
            if m.any():
                qa.append(qi[m]); pa.append(pi[m]); da.append(dist[m])
    if not qa:
        return z, z.copy(), np.zeros(0)
    return np.concatenate(qa), np.concatenate(pa), np.concatenate(da)


# ═══════════════════════════════════════════════════════════ generic nearest query
def nearest(Q, lo, hi, evaluate, npayload=0, max_dist=0.0, cell=0.0):
    """
    Find the nearest item for each query point.

    lo/hi     : (T,3) AABB of each item
    evaluate  : f(qi, ti) -> (dist (M,), payload (M,npayload)) -- exact distance
    max_dist  : when >0, anything beyond this distance counts as not found, and the number of search rounds drops **sharply**
    Returns (item index (nq,), -1 if not found, distance (nq,), payload (nq,npayload))

    Three steps, and the order matters:

      1. First query one round on the **fine grid**. Query points close to the surface (shrink-wrap, Ray's minimum distance,
         the majority in practice) are settled in one round, costing only 27 lookups x two or three items per cell.
      2. Those not yet settled query one round on the **coarse grid** to get an **upper bound** -- this step need not be exact,
         it just needs some distance that really exists.
      3. With an upper bound d, we know which level to query precisely: the ±1 neighbourhood of the level h = 2^ceil(log2(d))
         is guaranteed to cover radius d. Group by level; each point queries **only its own level** once.

    Step 3 is the key. Plainly "doubling the cells, everyone moving together" makes a distant query point
    walk through every level along the way, and on coarse levels each cell holds a large patch of faces -- costing several times
    the final level, all spent on candidates doomed to be discarded.

    Before candidates go into evaluate they pass an **AABB distance prefilter**: if the distance from the point to the item's bounding box
    is already worse than the current best, computing it exactly is wasted work. Bounding-box distance is three maximums,
    cheaper than any exact distance.

    Cost model: a query point at distance d from the surface must look at O((d/sample spacing)^2) triangles --
    that is determined by "how many faces are within radius d", and no acceleration structure saves more than a constant.
    The real way to save time is to give a Max Distance.
    """
    Q = np.asarray(Q, np.float64).reshape(-1, 3)
    nq = len(Q)
    best_i = np.full(nq, -1, np.int64)
    best_d = np.full(nq, np.inf)
    best_p = np.zeros((nq, npayload))
    if not nq or not len(lo):
        return best_i, best_d, best_p

    lo = np.asarray(lo, np.float64).reshape(-1, 3)
    hi = np.asarray(hi, np.float64).reshape(-1, 3)
    gmn = np.minimum(lo.min(0), Q.min(0))
    gmx = np.maximum(hi.max(0), Q.max(0))
    diag = float(np.linalg.norm(gmx - gmn)) or 1.0
    if cell <= 0:
        # the starting cell size is the average item size, with a lower bound so the cell count does not become astronomical
        cell = max(float(np.mean(np.linalg.norm(hi - lo, axis=1))) or 0.0,
                   diag / 1024.0)
    lim = max_dist if max_dist > 0 else np.inf

    def _update(qi, ti):
        if not len(qi):
            return
        q = Q[qi]
        gap = np.maximum(lo[ti] - q, 0.0) + np.maximum(q - hi[ti], 0.0)
        keep = np.einsum("ij,ij->i", gap, gap) < np.minimum(best_d[qi], lim) ** 2
        if not keep.all():
            qi, ti = qi[keep], ti[keep]
            if not len(qi):
                return
        d, pl = evaluate(qi, ti)
        # among several candidates for the same query point take the minimum. After lexsort the first of each group is the best.
        order = np.lexsort((d, qi))
        qs = qi[order]
        first = np.ones(len(qs), bool)
        first[1:] = qs[1:] != qs[:-1]
        sel = order[first]
        better = d[sel] < best_d[qi[sel]]
        if better.any():
            s = sel[better]
            best_i[qi[s]] = ti[s]
            best_d[qi[s]] = d[s]
            if npayload:
                best_p[qi[s]] = pl[s]

    def _round(active, h):
        bucket, big = _box_bucket(lo, hi, h)
        for s in range(0, len(active), _CHUNK):
            idx = active[s:s + _CHUNK]
            c = np.floor(Q[idx] / h).astype(np.int64)
            for d in _NEIGH27:
                _update(*bucket.query(cell_key(c + d), idx))
            if len(big):
                _update(np.repeat(idx, len(big)), np.tile(big, len(idx)))

    def _level(d):
        """Smallest level cell size needed to cover radius d."""
        k = np.clip(np.ceil(np.log2(np.maximum(d, cell) / cell)), 0, 40)
        return cell * np.exp2(k)

    def _kd_finish(act, cKDTree):
        """
        Settle the remaining query points with a KD tree over the item AABB centres (scipy).

        1. The k nearest centres give a real distance (evaluated exactly) -- a tight upper bound d.
        2. Every item that can be closer than d has its centre within d + (largest half diagonal) of the query point,
           so one ball query lists all candidates; the AABB prefilter in _update discards most of them unevaluated.
        Compared with the level grid below, the candidate region is a ball of radius ~d instead of a cube of side 3*2^k >= 3d
        (about 50x the volume), and every point is visited once instead of once per level.
        Items far larger than the rest (a ground plane under small rocks) would inflate the ball radius for everyone:
        they are always evaluated instead.
        """
        cen = (lo + hi) * 0.5
        rad = np.linalg.norm(hi - lo, axis=1) * 0.5
        rcut = max(float(np.percentile(rad, 99)) * 4.0, cell)
        bigm = rad > rcut
        big, small = np.nonzero(bigm)[0], np.nonzero(~bigm)[0]
        if not len(small):
            for s in range(0, len(act), max(1, _CHUNK // max(len(big), 1))):
                idx = act[s:s + max(1, _CHUNK // max(len(big), 1))]
                _update(np.repeat(idx, len(big)), np.tile(big, len(idx)))
            return
        tree = cKDTree(cen[small])
        rmax = float(rad[small].max())
        k = min(8, len(small))
        for s in range(0, len(act), 8192):
            idx = act[s:s + 8192]
            _, nn = tree.query(Q[idx], k=k)
            nn = np.asarray(nn).reshape(len(idx), -1)
            _update(np.repeat(idx, nn.shape[1]), small[nn.ravel()])
            if len(big):
                _update(np.repeat(idx, len(big)), np.tile(big, len(idx)))
            r = np.minimum(best_d[idx], lim) + rmax
            cnt = np.asarray(tree.query_ball_point(Q[idx], r, return_length=True), np.int64)
            # fetch the candidate lists in slices of bounded pair count (Python lists of ints are the memory cost here)
            e0 = 0
            while e0 < len(idx):
                e1, tot = e0, 0
                while e1 < len(idx) and (tot + cnt[e1] <= _CHUNK or e1 == e0):
                    tot += int(cnt[e1])
                    e1 += 1
                if tot:
                    lists = tree.query_ball_point(Q[idx[e0:e1]], r[e0:e1], return_sorted=False)
                    c = np.fromiter((len(x) for x in lists), np.int64, len(lists))
                    ti = np.fromiter(chain.from_iterable(lists), np.int64, int(c.sum()))
                    _update(np.repeat(idx[e0:e1], c), small[ti])
                e0 = e1

    active = np.arange(nq, dtype=np.int64)
    _round(active, cell)
    active = active[best_d[active] > min(cell, lim)]
    if len(active):
        try:
            from scipy.spatial import cKDTree
        except ImportError:                     # no scipy: the level grid below does the same job, only slower
            cKDTree = None
        if cKDTree is not None:
            _kd_finish(active, cKDTree)
            active = active[:0]

    h = max(cell * 2.0, diag / 32.0)
    while len(active) and h <= 4.0 * diag:
        _round(active, h)
        d = best_d[active]
        undone = (d > h) & (h < lim)
        active = active[undone]
        if not len(active):
            break
        # those that already have an upper bound: jump straight to their own level, query once, and they are settled
        has = best_i[active] >= 0
        far = active[has]
        active = active[~has]
        if len(far):
            hl = np.minimum(_level(best_d[far]), _level(lim) if lim < np.inf
                            else np.inf)
            for u in np.unique(hl):
                _round(far[hl == u], float(u))
        h *= 2.0
    if max_dist > 0:
        miss = best_d > max_dist
        best_i[miss] = -1
        best_d[miss] = np.inf
        best_p[miss] = 0.0
    return best_i, best_d, best_p


# ═══════════════════════════════════════════════════════════════ triangles
def tri_soup(geo, group=""):
    """
    Cut the selected primitives into triangles. Returns ((T,3) point numbers, (T,) source prim, (T,3) corner numbers).

    Borrows Divide's ear clipping so concave ngons are cut correctly. Two temporary prim/vertex attributes carry the original numbers
    across -- after triangulation this correspondence cannot be reconstructed, it can only be recorded beforehand.
    """
    from . import divide as _divide
    z3 = np.zeros((0, 3), np.int32)
    sel = resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return z3, np.zeros(0, np.int64), z3.copy()
    tmp = geo.copy()
    tmp.set(PRIM, "__srcprim__", np.arange(geo.nprims, dtype=np.int32),
            owned=True)
    tmp.set(VERTEX, "__srccorner__",
            np.arange(geo.nvertices, dtype=np.int32), owned=True)
    tmp.set_group(PRIM, "__trisel__", sel)
    tri = _divide.convex_polygons(tmp, "__trisel__", 3, False, 1e-4,
                                  False, False, True)
    keep = (tri.prim_sizes() == 3) & tri.prim_closed \
        & tri.get_group(PRIM, "__trisel__")
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return z3, np.zeros(0, np.int64), z3.copy()
    corner = _gather_blocks(tri.prim_offset[:-1][idx], np.full(len(idx), 3))
    src_corner = tri.get(VERTEX, "__srccorner__")
    return (tri.vertex_point[corner].reshape(-1, 3).astype(np.int32),
            tri.get(PRIM, "__srcprim__")[idx, 0].astype(np.int64),
            (src_corner[corner, 0].reshape(-1, 3).astype(np.int32)
             if src_corner is not None else z3.copy()))


def tri_verts(P, tri):
    P = np.asarray(P, np.float64)
    return P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]


def closest_on_tri(P0, ab, ac, d1, d2, d3, d4, d5, d6):
    """
    Ericson's seven-region classification; returns the barycentric coordinates (v, w) of the closest point on the triangle.

    Computing only interior barycentrics and clamping to [0,1] is wrong: when the point lies outside a vertex region, the clamped position
    ends up somewhere on an edge it should not be. Each of the seven regions has its own formula, all picked at once with np.select.
    """
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    def _div(x, y):
        return x / np.where(np.abs(y) < 1e-30, 1e-30, y)

    den = va + vb + vc
    v_in, w_in = _div(vb, den), _div(vc, den)
    t_ab = np.clip(_div(d1, d1 - d3), 0, 1)
    t_ac = np.clip(_div(d2, d2 - d6), 0, 1)
    t_bc = np.clip(_div(d4 - d3, (d4 - d3) + (d5 - d6)), 0, 1)
    zero, one = np.zeros_like(d1), np.ones_like(d1)
    conds = [(d1 <= 0) & (d2 <= 0),
             (d3 >= 0) & (d4 <= d3),
             (d6 >= 0) & (d5 <= d6),
             (vc <= 0) & (d1 >= 0) & (d3 <= 0),
             (vb <= 0) & (d2 >= 0) & (d6 <= 0),
             (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)]
    v = _select(conds, [zero, one, zero, t_ab, zero, 1 - t_bc], default=v_in)
    w = _select(conds, [zero, zero, one, zero, t_ac, t_bc], default=w_in)
    return v, w


def closest_surface(Q, P, tri, max_dist=0.0):
    """
    Closest point on a triangle soup for each query point.
    Returns (triangle index (n,), -1 if none, distance (n,), position (n,3), barycentric uv (n,2)).
    """
    Q = np.asarray(Q, np.float64).reshape(-1, 3)
    tri = np.asarray(tri, np.int64).reshape(-1, 3)
    if not len(tri) or not len(Q):
        return (np.full(len(Q), -1, np.int64), np.full(len(Q), np.inf),
                Q.copy(), np.zeros((len(Q), 2)))
    A, B, C = tri_verts(P, tri)
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)

    def ev(qi, ti):
        a, b, c = A[ti], B[ti], C[ti]
        p = Q[qi]
        ab, ac = b - a, c - a
        ap, bp, cp = p - a, p - b, p - c
        v, w = closest_on_tri(
            p, ab, ac,
            np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap),
            np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp),
            np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp))
        pos = a + v[:, None] * ab + w[:, None] * ac
        return np.linalg.norm(pos - p, axis=1), np.concatenate(
            [pos, v[:, None], w[:, None]], 1)

    ti, dist, pl = nearest(Q, lo, hi, ev, npayload=5, max_dist=max_dist)
    pos = np.where((ti >= 0)[:, None], pl[:, :3], Q)
    return ti, dist, pos, pl[:, 3:5]


# ═══════════════════════════════════════════════════════════════ rays
def _moller(O, D, A, B, C, qi, ti, eps=1e-9):
    """Möller–Trumbore. D must already be normalized, so t is the true distance."""
    a = A[ti]
    e1 = B[ti] - a
    e2 = C[ti] - a
    d = D[qi]
    pv = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, pv)
    ok = np.abs(det) > 1e-14
    inv = 1.0 / np.where(ok, det, 1.0)
    s = O[qi] - a
    u = np.einsum("ij,ij->i", s, pv) * inv
    qv = np.cross(s, e1)
    v = np.einsum("ij,ij->i", d, qv) * inv
    t = np.einsum("ij,ij->i", e2, qv) * inv
    ok &= (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps)
    return t, u, v, ok


def _ray_reduce(best_t, best_i, best_uv, qi, ti, t, u, v, ok, farthest,
                tmin, tmax, both=False):
    ok = ok & (t >= tmin[qi]) & (t <= tmax[qi])
    if not ok.any():
        return
    qi, ti, t, u, v = qi[ok], ti[ok], t[ok], u[ok], v[ok]
    # both (accept both directions): compare the **distance** |t|, not the signed t. It used to compare t, so hits behind with t < 0
    # were always "closer", and it always picked the farthest face behind (the exact opposite of the docstring's "nearest surface")
    k = np.abs(t) if both else t
    cur = best_t[qi]
    if both:
        # query points with no hit yet have best_t of ±inf; taking the absolute value would turn farthest's -inf into +inf,
        # and then nothing could beat it -- those without a hit keep the original sentinel value
        cur = np.where(best_i[qi] < 0, cur, np.abs(cur))
    better = (k > cur) if farthest else (k < cur)
    # still need to choose again within the same query point: above only compares against existing results
    order = np.lexsort(((-k if farthest else k), qi))
    qs = qi[order]
    first = np.ones(len(qs), bool)
    first[1:] = qs[1:] != qs[:-1]
    sel = order[first]
    sel = sel[better[sel]]
    if not len(sel):
        return
    best_t[qi[sel]] = t[sel]
    best_i[qi[sel]] = ti[sel]
    best_uv[qi[sel]] = np.stack([u[sel], v[sel]], 1)


_RAY_CHUNK = 262144


def ray_cast(O, D, P, tri, farthest=False, max_dist=0.0, both=False, cull=0):
    """
    Shoot rays from O along D. D is normalized, so the returned t is the distance.

    With both=True hits in the **opposite direction** (negative t) are also accepted, picking the nearest by **distance** |t| (farthest with farthest),
    for "the nearest surface, whichever side"; the returned t is still signed (negative for the opposite direction).
    cull (pcg100 c8, Face Culling for baking): 1 = ignore hits on **back faces**, −1 = ignore hits on front faces,
    0 = keep both (default, as before). "Back face" = triangle normal (right-handed order A->B->C) points the same way as the ray's **actual direction of travel**;
    for hits with t < 0 the direction of travel is −D. Ignored hits do not block; the ray keeps looking for the next one.
    Returns (triangle index (n,), -1 if missed, t (n,), barycentric uv (n,2)).

    Three paths, chosen from cheapest to most expensive:
      1. small scale -> plain brute force (chunked), no need to build an index;
      2. **uniform direction** -> project the triangles onto the plane perpendicular to the direction and bucket them. Each ray
         is then a point on the projection plane and queries a single cell, so even huge terrains hit in O(1);
      3. varied directions -> 3D grid DDA, advancing cell by cell.
    Orthographic projection (projecting down onto terrain) is Ray's most common use and earns its own path: with DDA
    a ray coming down from the sky would have to traverse every cell along the height axis.
    """
    O = np.asarray(O, np.float64).reshape(-1, 3)
    D = np.asarray(D, np.float64).reshape(-1, 3)
    n = len(O)
    tri = np.asarray(tri, np.int64).reshape(-1, 3)
    # A large batch of rays with varied directions is shot in chunks: each DDA step expands all live rays x the triangles in their cells
    # into candidate pairs at once; four million rays (a 4096x1024 bake) give tens of millions of pairs in one step, blowing memory
    # (measured: killed at 6 GB). 250k rays per chunk, so the peak is independent of image size
    if n > _RAY_CHUNK and len(tri) and np.abs(D - D[0]).max() >= 1e-9:
        parts = [ray_cast(O[s:s + _RAY_CHUNK], D[s:s + _RAY_CHUNK], P, tri,
                          farthest, max_dist, both, cull)
                 for s in range(0, n, _RAY_CHUNK)]
        return (np.concatenate([p[0] for p in parts]),
                np.concatenate([p[1] for p in parts]),
                np.concatenate([p[2] for p in parts]))
    best_i = np.full(n, -1, np.int64)
    best_t = np.full(n, -np.inf if farthest else np.inf)
    best_uv = np.zeros((n, 2))
    if not n or not len(tri):
        return best_i, np.zeros(n), best_uv
    L = np.linalg.norm(D, axis=1, keepdims=True)
    D = D / np.where(L < 1e-30, 1.0, L)
    A, B, C = tri_verts(P, tri)
    lim = max_dist if max_dist > 0 else np.inf
    tmin = np.full(n, -lim if both else -1e-6)
    tmax = np.full(n, lim)
    NG = np.cross(B - A, C - A) if cull else None

    def reduce_(qi, ti):
        if not len(qi):
            return
        t, u, v, ok = _moller(O, D, A, B, C, qi, ti)
        if cull:
            f = np.einsum("ij,ij->i", NG[ti], D[qi]) * np.where(t < 0, -1.0, 1.0)
            ok = ok & ~((f > 0) if cull > 0 else (f < 0))
        _ray_reduce(best_t, best_i, best_uv, qi, ti, t, u, v, ok,
                    farthest, tmin, tmax, both)

    T = len(tri)
    coherent = np.abs(D - D[0]).max() < 1e-9
    # With a uniform direction, projected bucketing is O(T) index build + O(n) queries, brute force is O(n·T).
    # So unless the rays number in single digits and the triangles in the tens, bucketing wins -- just checking whether n·T
    # exceeds the total limit is not enough: 3264 triangles x 300 rays is only 1M, went brute force,
    # and in-volume scattering (which shoots repeatedly) became 20x slower
    if coherent and n > 32 and T > 256:
        _ray_parallel(O, D[0], A, B, C, reduce_)
    elif n * T <= 4_000_000:
        step = max(1, 4_000_000 // max(T, 1))
        for s in range(0, n, step):
            idx = np.arange(s, min(s + step, n), dtype=np.int64)
            reduce_(np.repeat(idx, T), np.tile(np.arange(T, dtype=np.int64),
                                               len(idx)))
    elif coherent:
        _ray_parallel(O, D[0], A, B, C, reduce_)
    else:
        _ray_dda(O, D, A, B, C, reduce_, farthest, best_t, best_i, lim, both)

    miss = best_i < 0
    t_out = np.where(miss, 0.0, best_t)
    return best_i, t_out, best_uv


def _basis(w):
    """Build an orthonormal basis for a direction."""
    a = np.array([1.0, 0, 0]) if abs(w[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, w)
    u /= max(np.linalg.norm(u), 1e-30)
    return u, np.cross(w, u)


def _ray_parallel(O, d, A, B, C, reduce_):
    u, v = _basis(d)
    M = np.stack([u, v], 1)                       # (3,2)
    pa, pb, pc = A @ M, B @ M, C @ M
    lo2 = np.minimum(np.minimum(pa, pb), pc)
    hi2 = np.maximum(np.maximum(pa, pb), pc)
    ext = float(np.max(hi2.max(0) - lo2.min(0))) or 1.0
    h = max(float(np.mean(np.linalg.norm(hi2 - lo2, axis=1))) or 0.0,
            ext / 1024.0)
    # reuse the 3D bucketing: fill the third axis with 0, equivalent to a 2D grid
    z = np.zeros((len(A), 1))
    bucket, big = _box_bucket(np.concatenate([lo2, z], 1),
                              np.concatenate([hi2, z], 1), h)
    Q2 = O @ M
    for s in range(0, len(O), _CHUNK):
        idx = np.arange(s, min(s + _CHUNK, len(O)), dtype=np.int64)
        c = np.floor(np.concatenate(
            [Q2[idx], np.zeros((len(idx), 1))], 1) / h).astype(np.int64)
        reduce_(*bucket.query(cell_key(c), idx))
        if len(big):
            reduce_(np.repeat(idx, len(big)), np.tile(big, len(idx)))


def _ray_dda(O, D, A, B, C, reduce_, farthest, best_t, best_i, lim, both,
             max_steps=4096):
    """
    Amanatides & Woo voxel stepping, vectorized as "all live rays take one step together".

    First clip the rays to the geometry bounding box with the slab method -- otherwise rays flying in from outside the scene
    would spin through hundreds of steps in empty cells.
    """
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    gmn, gmx = lo.min(0), hi.max(0)
    diag = float(np.linalg.norm(gmx - gmn)) or 1.0
    h = max(float(np.mean(np.linalg.norm(hi - lo, axis=1))) or 0.0, diag / 256.0)
    bucket, big = _box_bucket(lo, hi, h)

    inv = 1.0 / np.where(np.abs(D) < 1e-30, 1e-30, D)
    t0 = (gmn - h - O) * inv
    t1 = (gmx + h - O) * inv
    tn = np.minimum(t0, t1).max(1)
    tf = np.maximum(t0, t1).min(1)
    start = np.maximum(tn, -lim if both else 0.0)
    stop = np.minimum(tf, lim)
    active = np.nonzero(tf >= tn)[0]
    if not len(active):
        return
    t_cur = start[active].copy()
    stop_a = stop[active]
    cell = np.floor((O[active] + D[active] * (t_cur[:, None] + 1e-9)) / h
                    ).astype(np.int64)
    stepv = np.sign(D[active]).astype(np.int64)
    tdelta = np.abs(h * inv[active])
    nxt = (cell + (stepv > 0)) * h
    tmax_ax = (nxt - O[active]) * inv[active]
    tmax_ax = np.where(stepv == 0, np.inf, tmax_ax)

    if len(big):
        allq = np.arange(len(O), dtype=np.int64)
        reduce_(np.repeat(allq, len(big)), np.tile(big, len(allq)))

    for _ in range(max_steps):
        if not len(active):
            return
        reduce_(*bucket.query(cell_key(cell), active))
        texit = tmax_ax.min(1)
        keep = texit <= stop_a
        if not farthest:
            # the hit already lies within the segment walked so far -> nothing later can be closer. With both, compare distance: later hits
            # have t ≥ texit, so when texit ≥ 0 their distance is also ≥ texit; when texit < 0 later hits may still have smaller |t|, so do not stop
            bt = np.abs(best_t[active]) if both else best_t[active]
            keep &= ~(best_i[active] >= 0) | (bt > texit)
        if not keep.all():
            active = active[keep]
            if not len(active):
                return
            cell, stepv, tdelta = cell[keep], stepv[keep], tdelta[keep]
            tmax_ax, stop_a, texit = tmax_ax[keep], stop_a[keep], texit[keep]
        ax = np.argmin(tmax_ax, axis=1)
        r = np.arange(len(active))
        cell[r, ax] += stepv[r, ax]
        tmax_ax[r, ax] += tdelta[r, ax]
    # those still unfinished when steps run out get an honest brute-force pass, so hits are not silently missed
    if len(active):
        T = len(A)
        step = max(1, 2_000_000 // max(T, 1))
        for s in range(0, len(active), step):
            idx = active[s:s + step]
            reduce_(np.repeat(idx, T),
                    np.tile(np.arange(T, dtype=np.int64), len(idx)))
