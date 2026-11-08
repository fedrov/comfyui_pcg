"""
Shared layer for "distance" along topology: used by both Group Expand / Shrink and Attribute Fade.

Both nodes really ask the same question -- **how far from this set of elements**. Expand uses it as a threshold
(everything <= N steps is included), Fade uses it for a gradient (a curve interpolated by distance). Compute the distance once and
both uses work, so it lives in its own module.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two metrics, giving different answers
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    steps      number of edges hopped (BFS). Good enough on uniform meshes, but tied to mesh density --
               "expand 3 steps" on a subdivided mesh actually covers only half the range
    distance   **geodesic distance** accumulated along edges (Bellman-Ford relaxation). Independent of mesh
               density: "expand 0.5 m" really is 0.5 m

**Not Euclidean distance**: two pieces touching but not connected are infinitely far apart. This is intended --
selections on the two sides of a wall shouldn't bleed into each other, same reasoning as Attribute Blur.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why Bellman-Ford instead of Dijkstra
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Dijkstra needs a priority queue and pops one point at a time -- in pure Python tens of thousands of points mean hundreds of thousands of
heap operations, slower than everything else done to the geometry combined. One Bellman-Ford relaxation round is
"a min over all edges at once", a single `np.minimum.at`; the number of rounds equals the hop count of the longest path,
and fade radii are bounded anyway, so it usually converges in a dozen or so rounds. **Rounds replace the queue.**

The convergence test is "no value decreased in this round", so no wasted rounds; the max_rounds cap is defensive.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM
from .topology import topology, point_neighbours
from .ops import prim_centers

METRICS = ("steps", "distance")


def adjacency(geo, cls=POINT, weighted=False):
    """
    CSR of (offsets, neighbours, weights).

    cls=point walks edges; cls=prim walks **primitive adjacency via shared edges**. With weighted the weights are lengths:
    edge length between points, centroid distance between primitives.
    """
    if cls == POINT:
        off, nb = point_neighbours(geo)
        off = np.asarray(off, np.int64)
        nb = np.asarray(nb, np.int64)
        if not len(nb):
            return off, nb, np.zeros(0)
        if not weighted:
            return off, nb, np.ones(len(nb))
        P = geo.get(POINT, "P")
        if P is None:
            raise KeyError("Geometry has no P attribute; cannot compute distances.")
        src = np.repeat(np.arange(geo.npoints, dtype=np.int64), np.diff(off))
        w = np.linalg.norm(P[src].astype(np.float64)
                           - P[nb].astype(np.float64), axis=1)
        return off, nb, w

    if cls != PRIM:
        raise ValueError("Distance along topology only makes sense for point / prim -- "
                         "vertex and detail have no adjacency to walk.")

    t = topology(geo)
    nf = geo.nprims
    empty = (np.zeros(nf + 1, np.int64), np.zeros(0, np.int64), np.zeros(0))
    if t.nedges == 0 or geo.nvertices == 0:
        return empty
    two = np.nonzero(t.edge_count == 2)[0]
    if not len(two):
        return empty
    vp = geo.vertex_prim().astype(np.int64)
    a = vp[t.edge_he[t.edge_he_off[two]]]
    b = vp[t.edge_he[t.edge_he_off[two] + 1]]
    keys = np.concatenate([a, b])
    vals = np.concatenate([b, a])
    order = np.argsort(keys, kind="stable")
    off = np.concatenate([[0], np.cumsum(np.bincount(keys, minlength=nf))]
                         ).astype(np.int64)
    nb = vals[order]
    if not weighted:
        return off, nb, np.ones(len(nb))
    C = prim_centers(geo).astype(np.float64)
    src = np.repeat(np.arange(nf, dtype=np.int64), np.diff(off))
    return off, nb, np.linalg.norm(C[src] - C[nb], axis=1)


def hop_distance(geo, cls, seed, max_steps=-1):
    """
    BFS. Returns (N,) integer hop counts; seeds are 0, unreachable ones -1.

    max_steps < 0 means walk to the end. With a limit it stops early -- fade only cares about what is within the radius,
    no need to flood the whole geometry.
    """
    n = geo.count(cls)
    d = np.full(n, -1, np.int64)
    seed = np.asarray(seed, bool)
    if not seed.any():
        return d
    d[seed] = 0
    off, nb, _ = adjacency(geo, cls, weighted=False)
    if not len(nb):
        return d
    frontier = np.nonzero(seed)[0]
    step = 0
    while len(frontier) and (max_steps < 0 or step < max_steps):
        step += 1
        # Neighbours of all frontier points fetched at once -- this is the only cost of the BFS layer loop
        cnt = np.diff(off)[frontier]
        idx = np.repeat(off[frontier], cnt) + (
            np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        cand = np.unique(nb[idx])
        cand = cand[d[cand] < 0]
        if not len(cand):
            break
        d[cand] = step
        frontier = cand
    return d


def edge_distance(geo, cls, seed, max_dist=-1.0, max_rounds=10000):
    """
    Geodesic distance accumulated along edges (Bellman-Ford relaxation). Seeds are 0, unreachable ones inf.

    With max_dist >= 0 anything beyond is cut to inf -- both a way to converge early and a way to make "outside the radius
    is unreachable" explicit in the result, rather than leaving lots of large numbers for downstream to judge.
    """
    n = geo.count(cls)
    d = np.full(n, np.inf)
    seed = np.asarray(seed, bool)
    if not seed.any():
        return d
    d[seed] = 0.0
    off, nb, w = adjacency(geo, cls, weighted=True)
    if not len(nb):
        return d
    src = np.repeat(np.arange(n, dtype=np.int64), np.diff(off))
    for _ in range(int(max_rounds)):
        cand = d[src] + w
        if max_dist >= 0:
            cand = np.where(cand > max_dist, np.inf, cand)
        nd = d.copy()
        np.minimum.at(nd, nb, cand)         # one round = relax all edges once simultaneously
        if np.array_equal(np.isinf(nd), np.isinf(d)) and np.allclose(
                nd[~np.isinf(nd)], d[~np.isinf(d)], rtol=0, atol=1e-12):
            break
        d = nd
    return d


def distance_from(geo, cls, seed, metric="steps", radius=3.0):
    """
    Unified entry point: returns (distance array, unreachable mask). Distances are already normalized by metric to
    "which step / how many metres"; anything outside radius counts as unreachable.
    """
    if metric == "steps":
        k = max(0, int(round(radius)))
        d = hop_distance(geo, cls, seed, k)
        unreachable = (d < 0) | (d > k)
        return d.astype(np.float64), unreachable
    if metric == "distance":
        r = float(radius)
        d = edge_distance(geo, cls, seed, r)
        return d, np.isinf(d) | (d > r)
    raise ValueError(f"Metric must be one of {METRICS}")
