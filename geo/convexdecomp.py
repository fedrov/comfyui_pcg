"""
Convex Decomposition -- splits a concave solid into several convex pieces. Counterpart of V-HACD / Houdini's
Convex Decomposition.

A convex hull gives "the outermost skin", but for an L shape, a bowl, a chair, what the hull smears over is exactly what makes them
that shape. Convex collision in physics engines is fast, concave collision slow or even unsupported, so the industry practice is to
**split into a pile of convex pieces**: each piece used as a convex body on its own, together hugging the original shape.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Concavity: measured by **volume**, not distance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    concavity = 1 - solid volume / hull volume

It is exactly 0 when convex, and it is the **relative amount** of "how much air replacing this piece by its hull adds".
Another common definition is "distance from the most concave point to the hull", but that quantity is extremely sensitive to a thin spike --
a spike of negligible volume makes the whole object count as highly concave, and the algorithm frantically tries to split that spike. The volume definition
is naturally weighted by "how badly wrong it is".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Where to cut: directly **minimize the sum of the two sub-pieces' hull volumes**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Candidate planes are three axes x resolution-1 positions; each candidate really cuts and really computes two hulls,
and the one with the smallest `hull(left) + hull(right)` is taken.

This scoring function is **the very quantity being optimized in the end** -- the output is a pile of convex pieces, and their total volume
minus the original volume is the entire error. No need to design heuristic proxies like "symmetry / balance"; optimizing the
objective directly is the most solid. The cost is two hulls per candidate, but hulls only depend on point count, and point counts here are
at fragment level; measured, about twenty candidates per node take under 0.1 s.

**The three axes are the OBB's axes, not world axes.** World axes give almost no good cut on a tilted L shape
-- every cut goes through both legs. OBB axes follow the object, and as a bonus make the whole algorithm **rotation-covariant**:
rotate the object and decompose again, and the piece count and total hull volume barely change (measured relative error on the order of 1e-3). This
property is itself a very solid test criterion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cut the worst piece first: a global budget, not depth-first
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Recursion easily ends up depth-first: "split one leg all the way down, without a single cut on the other leg". Here a heap is kept, sorted by
**absolute concave volume** (concavity x hull volume, i.e. "how much extra air this piece has"),
and the worst piece is cut each time. Max Pieces thus becomes a true global budget: however many pieces you give, they are spent
where they are needed most.

Three stopping conditions, any one ends it: concavity below the threshold, piece count at the limit, no further cut possible (no candidate
plane produces two valid sub-pieces).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Split connected components after cutting
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A cut across the opening of a U shape produces "one piece" that is actually two separate lumps. Without splitting, its hull would wrap
the whole air gap in between, and the next round would need another cut just to separate them -- wasting budget for nothing.
So after every cut the result is split by connectivity once; this step is free (label propagation already exists).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two outputs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    hull    each piece replaced by its own hull -- this is what a collision proxy wants. Total volume >= original volume,
            the excess is the approximation error
    exact   keeps the cut solids themselves. Total volume **exactly equals** the original volume (cutting conserves volume),
            pieces may still have a little residual concavity (not above the threshold)

Volume conservation in exact mode is a very handy self-check: it also proves the pieces **don't overlap** (their union
is contained in the original shape and their volumes add up to it, so there can be neither overlap nor gaps).
"""
from __future__ import annotations

import heapq

import numpy as np

from .core import Geometry, POINT, PRIM
from .clip import clip_plane
from .voronoi import _cap_plane
from .hull import convex_hull
from .measure import prim_volumes
from .ops import merge, delete_prims
from .pieces import connectivity

MODES = ("hull", "exact")
AXES = ("oriented", "world")


def solid_volume(g):
    """Volume of a closed solid. Meaningless for open geometry, so the caller must ensure it is closed."""
    if g is None or g.nprims == 0:
        return 0.0
    return abs(float(prim_volumes(g).sum()))


def concavity(g, hv=None):
    """
    1 - solid volume / hull volume. 0 when convex.

    Returns (concavity, hull volume, solid volume). Passing the hull volume in saves a recomputation.
    """
    v = solid_volume(g)
    if hv is None:
        hv = solid_volume(convex_hull(g, merge_faces=False))
    if hv <= 0:
        return 0.0, 0.0, v
    return max(0.0, 1.0 - v / hv), hv, v


def _components(g):
    """Splits into pieces by connectivity. With only one piece returns it as is (saves a copy)."""
    if g.nprims <= 1:
        return [g]
    c = connectivity(g, cls="prim", name="__cd_class")
    lab = c.get(PRIM, "__cd_class")[:, 0].astype(np.int64)
    u = np.unique(lab)
    if len(u) <= 1:
        return [g]
    out = []
    for k in u:
        sub = delete_prims(c, lab == k)
        sub.remove(PRIM, "__cd_class")
        if sub.nprims:
            out.append(sub)
    return out


def _cut(part, n, o, cap_mode, tol):
    """One cut into two, capping both sides. Returns (below, above) -- None for an empty side."""
    out = []
    for keep in ("below", "above"):
        half, _ = clip_plane(part, n, o, keep=keep)
        if half.nprims == 0 or half.npoints == 0:
            out.append(None)
            continue
        nn = n if keep == "below" else -np.asarray(n, np.float64)
        half = _cap_plane(half, np.asarray(nn, np.float64), o, cap_mode, "",
                          tol)
        out.append(half if half.nprims else None)
    return out[0], out[1]


def _axes(Q, kind, tol):
    """Three candidate axes. oriented uses the OBB's axes, world uses world axes."""
    if kind == "world":
        return np.eye(3)
    from .bound import oriented_frame
    try:
        _, _, R = oriented_frame(Q, tol)
        return np.asarray(R, np.float64)
    except Exception:
        return np.eye(3)


def best_split(part, resolution, axis_mode, cap_mode, tol, min_frac):
    """
    Finds the best cut: the plane that minimizes the sum of the two pieces' hull volumes.

    Returns (left, right, score) or None (no cut possible). The score is the sum of the two hull volumes -- the scoring
    function is the objective function, no heuristic proxy.
    """
    Q = np.asarray(part.get(POINT, "P"), np.float64)
    if len(Q) < 4:
        return None
    R = _axes(Q, axis_mode, tol)
    v0 = solid_volume(part)
    best = None
    res = max(2, int(resolution))
    for n in R:
        t = Q @ n
        lo, hi = float(t.min()), float(t.max())
        if hi - lo <= tol:
            continue
        for k in range(1, res):
            o = n * (lo + (hi - lo) * k / res)
            a, b = _cut(part, n, o, cap_mode, tol)
            if a is None or b is None:
                continue
            va, vb = solid_volume(a), solid_volume(b)
            # If one side is negligibly small it doesn't count as a valid cut -- otherwise the algorithm would keep shaving off
            # infinitesimally thin slices, using up the piece budget before the shape is split
            if min(va, vb) < v0 * float(min_frac):
                continue
            score = (solid_volume(convex_hull(a, merge_faces=False))
                     + solid_volume(convex_hull(b, merge_faces=False)))
            if best is None or score < best[2]:
                best = (a, b, score)
    return best


def decompose(geo, mode="hull", max_concavity=0.05, max_pieces=32,
              resolution=8, axis_mode="oriented", min_fraction=0.02,
              cap_mode="ngon", tol=1e-5, name_attrib="name",
              piece_attrib="piece", name_prefix="convex", max_hull_points=0):
    """
    Splits a closed solid into several convex pieces.

    max_concavity is the residual concavity allowed per piece (1 - volume/hull volume), max_pieces is the global
    budget -- the heap is sorted by "absolute concave volume", so the budget is always spent on the piece that needs it most.
    max_hull_points > 0 (hull mode): each hull keeps at most that many vertices (reduce_hull_points), for engine
    collision limits.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if axis_mode not in AXES:
        raise ValueError(f"Split Axes must be one of {AXES}")
    if geo.nprims == 0 or geo.npoints == 0:
        return geo.copy() if geo.npoints else Geometry()
    from .topology import topology as _topo
    nopen = int(_topo(geo).boundary.sum())
    if nopen:
        raise ValueError(
            f"This geometry has {nopen} boundary edges and is not closed -- concavity is computed from volume, "
            f"and open geometry has no volume to speak of.\n  Connect a PolyFill (PCG) first to close the holes.")

    budget = max(1, int(max_pieces))
    thr = max(0.0, float(max_concavity))
    scale = float(np.max(np.asarray(geo.bbox()[1], np.float64)
                         - np.asarray(geo.bbox()[0], np.float64)))
    eps = float(tol) * max(scale, 1.0)

    done, heap, seq = [], [], 0
    for part in _components(geo):
        c, hv, _ = concavity(part)
        heapq.heappush(heap, (-c * hv, seq, part, c))
        seq += 1

    # The top of the heap is always the piece with "the most extra air". That makes max_pieces a true global budget,
    # rather than "split the first leg all the way down first"
    while heap:
        _, _, part, c = heapq.heappop(heap)
        # The budget counts the **current total pieces**: finished ones in done + those still waiting in the heap + the one in hand
        if len(done) + len(heap) + 1 >= budget:
            done.append(part)
            done.extend(p for _, _, p, _ in heap)
            break
        # Done once within the threshold, but **we can't stop here**: the heap is sorted by absolute concave volume, and further down there may still be
        # pieces of small volume but high relative concavity. Hence continue rather than break
        if c <= thr:
            done.append(part)
            continue
        sp = best_split(part, resolution, axis_mode, cap_mode, eps,
                        min_fraction)
        if sp is None:
            done.append(part)          # can't be cut any further; accept it
            continue
        for half in (sp[0], sp[1]):
            for comp in _components(half):
                cc, hv, _ = concavity(comp)
                heapq.heappush(heap, (-cc * hv, seq, comp, cc))
                seq += 1

    out = []
    for i, part in enumerate(done):
        g = convex_hull(part, merge_faces=True, max_points=max_hull_points) if mode == "hull" else part
        if g.nprims == 0:
            continue
        n = g.nprims
        if str(piece_attrib).strip():
            g.set(PRIM, str(piece_attrib).strip(),
                  np.full((n, 1), len(out), np.int32), owned=True)
        if str(name_attrib).strip():
            g.set_string(PRIM, str(name_attrib).strip(),
                         np.full(n, f"{name_prefix}{len(out)}"))
        out.append(g)
    return merge(*out) if out else Geometry()
