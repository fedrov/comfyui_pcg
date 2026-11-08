"""
Voronoi Cluster -- glues fragments into bigger chunks. Matches the Cluster part of Houdini's Voronoi Fracture.

Fragments from a pure Voronoi cut are **too regular**: every piece is convex and of similar size; it looks like crystal rather than
broken brick. Real breakage is "big chunks + small chunks + debris", and big chunks have concave, jagged outlines.

The trick is not a different cut but **cutting finer, then gluing neighbouring fragments back together**: cut 200 pieces first, cluster them into
12 heaps, and remove the walls inside each heap. The glued chunks are naturally concave with jagged borders, and the size distribution
comes from the clustering -- much more natural than cutting 12 pieces directly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Gluing back" = fuse points + delete coincident primitive pairs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
In the Voronoi output each fragment has its own points (merge doesn't fuse). Between two pieces of the same heap the wall
is **two back-to-back primitives whose points coincide exactly**. So:

    1. Fuse points per heap; coincident points become one
    2. Find primitive pairs whose **point sets are identical** -- those are interior walls; delete both

Step 2 uses "sorted point number tuples" as keys, so a single unique finds them all without pairwise geometry comparison. Fusing is
a prerequisite: unfused, the two primitives use two different sets of point numbers and the keys don't match.

After deletion, points used only by that wall are orphaned and cleaned up along the way (`delete_prims` already does that).
Points on the wall's **border** are still used by surrounding primitives and are rightly kept -- they are real vertices of the chunk outline,
not leftovers.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .ops import prim_centers, delete_prims, fuse, merge

MODES = ("count", "points")


def assign(centers, seeds):
    """(nf,) assigns each primitive to the nearest cluster seed."""
    d = ((centers[:, None, :] - seeds[None, :, :]) ** 2).sum(-1)
    return np.argmin(d, axis=1)


def _piece_ids(geo, piece_attrib):
    a = geo.get(PRIM, piece_attrib)
    if a is None:
        have = sorted(geo.attribs[PRIM].keys())
        raise KeyError(
            f"prim has no '{piece_attrib}' attribute -- Voronoi Cluster needs fragments first. "
            f"Put a Voronoi Fracture (PCG) before it. Existing: {have or '(none)'}")
    if is_string(a):
        _, inv = np.unique(np.asarray(a)[:, 0], return_inverse=True)
        return inv.reshape(-1).astype(np.int64)
    return a[:, 0].astype(np.int64)


def _drop_shared(g, tol):
    """Fuses points, then deletes primitive pairs with identical point sets -- those are the walls inside heaps."""
    g = fuse(g, tol)
    if g.nprims == 0:
        return g
    sizes = g.prim_sizes()
    starts = g.prim_offset[:-1].astype(np.int64)
    keys = [tuple(sorted(g.vertex_point[s:s + n].tolist()))
            for s, n in zip(starts, sizes)]
    seen = {}
    kill = np.zeros(g.nprims, bool)
    for i, k in enumerate(keys):
        j = seen.get(k)
        if j is None:
            seen[k] = i
        else:
            kill[i] = kill[j] = True     # delete both back-to-back faces
    if not kill.any():
        return g
    # keep_points=False: once the walls are gone, points used only by them are orphaned;
    # keeping them leaves a pile of isolated points (legal but in the way)
    return delete_prims(g, ~kill)


def cluster(geo, mode="count", cluster_count=8, points=None,
            piece_attrib="piece", name_attrib="name", name_prefix="cluster",
            cluster_attrib="cluster", merge_pieces=True, fuse_tol=1e-5,
            rand_seed=0):
    """
    Groups fragments by nearest cluster seed and removes the walls inside each heap.

    With mode=count, cluster_count fragment centroids are picked at random as seeds (picking existing centroids rather than
    scattering randomly guarantees every seed lands on some fragment, so no heap is empty); with mode=points the
    points of the third input are the seeds.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if geo.nprims == 0:
        return geo.copy()
    pid = _piece_ids(geo, str(piece_attrib).strip() or "piece")
    uniq = np.unique(pid)
    C = prim_centers(geo).astype(np.float64)
    # Centroid of each fragment
    pc = np.stack([C[pid == k].mean(0) for k in uniq], 0)

    if mode == "points":
        if points is None or points.npoints == 0:
            raise ValueError("mode=points needs cluster seed points on the second input.")
        seeds = points.get(POINT, "P").astype(np.float64)
    else:
        k = int(np.clip(cluster_count, 1, len(uniq)))
        rng = np.random.default_rng(int(rand_seed) & 0xFFFFFFFF)
        seeds = pc[rng.choice(len(uniq), size=k, replace=False)]

    lab = assign(pc, seeds)                 # which heap each fragment belongs to
    _, lab = np.unique(lab, return_inverse=True)
    lab = lab.reshape(-1)
    pmap = np.full(int(uniq.max()) + 1, 0, np.int64)
    pmap[uniq] = lab
    face_lab = pmap[pid]

    if not merge_pieces:
        g = geo.copy()
        g.set(PRIM, str(cluster_attrib).strip() or "cluster",
              face_lab[:, None].astype(np.int32), owned=True)
        return g

    mn, mx = geo.bbox()
    tol = float(fuse_tol) * max(float(np.max(np.asarray(mx, np.float64)
                                             - np.asarray(mn, np.float64))),
                                1.0)
    out = []
    for c in range(int(face_lab.max()) + 1):
        sub = delete_prims(geo, face_lab == c)
        if sub.nprims == 0:
            continue
        sub = _drop_shared(sub, tol)
        if sub.nprims == 0:
            continue
        n = sub.nprims
        if str(cluster_attrib).strip():
            sub.set(PRIM, str(cluster_attrib).strip(),
                    np.full((n, 1), len(out), np.int32), owned=True)
        if str(name_attrib).strip():
            sub.set_string(PRIM, str(name_attrib).strip(),
                           np.full(n, f"{name_prefix}{len(out)}"))
        out.append(sub)
    return merge(*out) if out else Geometry()
