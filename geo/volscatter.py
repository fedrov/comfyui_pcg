"""
Scatter in Volume -- scatters points **inside** closed geometry. Counterpart of Houdini's Scatter + Volume.

Only after finishing Voronoi Fracture last round did we find the chain was broken: the existing Scatter scatters on the **surface**,
and with surface points as Voronoi seeds every cell hugs the shell, so the result is a pile of shell shards instead of solid chunks.
To cut solid chunks, the seeds must be inside the volume.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two scatter modes, for completely different use cases
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    random  scatter in the bounding box, discard the ones outside (rejection sampling). The distribution is truly random -- some areas sparse, some dense;
            used for Voronoi it cuts chunks of very different sizes, like a natural break
    grid    a jittered regular grid. Chunks are of similar size, like a man-made cut / brick wall

Rejection sampling efficiency is "volume / bounding box volume". A long thin diagonal rod can drop to a few percent, so batches are added
until there are enough, instead of scattering count/hit-rate at once -- the hit rate is unknown beforehand, and a wrong estimate gives either too few
or ten times too many.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Min Distance uses **grid dart throwing**, not pairwise distance comparison
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For even spacing (Poisson disk), each candidate is checked for "is it far enough from the accepted points". Pairwise is O(n²);
here space is cut into cells of side r/√3 (diagonal exactly r, so at most one accepted point per cell),
and only the 5×5×5 neighbourhood is checked -- O(n). The classic Bridson idea.

The neighbourhood is **±2**, not ±1: with cells this small r/h = √3 ≈ 1.73, so two points closer than r
can be two cells apart. The first version used ±1; asking for 0.12 spacing measured 0.083.

The "generate new candidates around existing points" step is not done here: candidates are sampled uniformly from the interior; acceptance
is a bit lower, but the code is much shorter and the distribution is already even enough for Voronoi.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT
from .inside import inside_mesh, prepare

MODES = ("random", "grid")


def _dart(P, r):
    """
    Grid dart throwing: scan candidates in order, discard those closer than r to an accepted point. Returns a keep mask.

    The cell side is h = r/√3, so a cell's **diagonal is exactly r** and it can hold at most one
    accepted point (so a dict of one point per cell is enough).

    The neighbourhood must be checked at **±2**, not ±1: with cells this small r/h = √3 ≈ 1.73, so a point closer
    than r can be two cells away. The first version only checked ±1; asking for 0.12 spacing measured 0.083 --
    exactly the band between 1 and 2 cells that was missed.
    """
    if r <= 0 or not len(P):
        return np.ones(len(P), bool)
    h = r / np.sqrt(3.0)
    key = np.floor(P / h).astype(np.int64)
    key -= key.min(0)
    occupied = {}
    keep = np.zeros(len(P), bool)
    r2 = r * r
    rng3 = (-2, -1, 0, 1, 2)
    off = [(i, j, k) for i in rng3 for j in rng3 for k in rng3]
    for i in range(len(P)):
        c = (int(key[i, 0]), int(key[i, 1]), int(key[i, 2]))
        ok = True
        for o in off:
            j = occupied.get((c[0] + o[0], c[1] + o[1], c[2] + o[2]))
            if j is not None:
                d = P[i] - P[j]
                if d @ d < r2:
                    ok = False
                    break
        if ok:
            occupied[c] = i
            keep[i] = True
    return keep


def scatter_volume(geo, mode="random", count=100, spacing=0.1, jitter=1.0,
                   min_distance=0.0, rand_seed=0, group="", directions=3,
                   max_attempts=40, max_points=2_000_000):
    """
    Scatter points inside closed geometry. Returns a points-only geometry (with P).

    mode=random rejection-samples in batches until count is reached; mode=grid lays down
    a jittered grid at spacing and discards points outside -- count has no effect then.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if geo.nprims == 0 or geo.nvertices == 0:
        raise ValueError("Scatter in Volume needs closed geometry with primitives -- "
                         "a point cloud does not enclose a volume.")
    # **Check closedness first**. Ray parity is meaningless on open geometry: on a flat Grid,
    # a ray shot from its own plane crosses it once = odd = "inside", so a whole sheet of
    # points stuck to the surface gets scattered, without any error. Better to stop it here
    from .topology import topology as _topo
    nopen = int(_topo(geo).boundary.sum())
    if nopen:
        raise ValueError(
            f"This geometry has {nopen} boundary edges and is not closed -- ray parity cannot tell inside from outside.\n"
            f"  Connect a PolyFill (PCG) first to close the holes.")
    rng = np.random.default_rng(int(rand_seed) & 0xFFFFFFFF)
    soup = prepare(geo, group)          # triangulate once, reused by every batch
    mn, mx = geo.bbox()
    mn = np.asarray(mn, np.float64)
    mx = np.asarray(mx, np.float64)
    span = np.maximum(mx - mn, 1e-12)

    if mode == "grid":
        h = float(spacing)
        if h <= 0:
            raise ValueError("Spacing must be greater than 0.")
        nd = np.maximum(np.floor(span / h).astype(np.int64), 1)
        if int(np.prod(nd + 1)) > int(max_points):
            raise ValueError(
                f"Spacing={h} would lay {int(np.prod(nd + 1))} grid points on this bounding box, "
                f"exceeding the limit {max_points}. Increase Spacing.")
        axes = [mn[k] + (np.arange(nd[k]) + 0.5) * (span[k] / nd[k])
                for k in range(3)]
        G = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
        if jitter > 0:
            G = G + (rng.random(G.shape) - 0.5) * (span / nd) * float(jitter)
        pts = G[inside_mesh(G, geo, group, directions, soup=soup)]
    else:
        want = max(0, int(count))
        if want == 0:
            return Geometry.from_points(np.zeros((0, 3), np.float32))
        got = []
        have = 0
        batch = max(want, 64)
        for _ in range(int(max_attempts)):
            C = mn + span * rng.random((batch, 3))
            keep = C[inside_mesh(C, geo, group, directions, soup=soup)]
            if len(keep):
                got.append(keep)
                have += len(keep)
            if have >= want:
                break
            # Estimate the next batch size from the measured hit rate, plus a 50% margin. The hit rate is unknown beforehand,
            # so it is **estimated while scattering** rather than fixed up front
            rate = max(have / float(batch * (len(got) or 1)), 1e-3)
            batch = int(min(max((want - have) / rate * 1.5, 64), max_points))
        pts = np.concatenate(got) if got else np.zeros((0, 3))
        if len(pts) < want:
            raise ValueError(
                f"Scattered {int(max_attempts)} batches but only {len(pts)} points landed inside (wanted {want})"
                f" -- the geometry may not be closed, or its volume is too small relative to the bounding box. "
                f"Close the holes with PolyFill (PCG) first.")
        pts = pts[:want] if min_distance <= 0 else pts

    if min_distance > 0 and len(pts):
        pts = pts[_dart(pts, float(min_distance))]
        if mode == "random":
            pts = pts[:max(0, int(count))]
    return Geometry.from_points(np.asarray(pts, np.float32))
