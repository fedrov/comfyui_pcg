"""
Is a point inside a closed mesh -- scattering inside volumes and selecting inside volumes both need this answered first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ray parity, but **reusing the existing ray_cast**, hopping forward one hit at a time
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cast a ray from the point in one direction and count surface crossings: odd means inside, even means outside.

The catch is that `spatial.ray_cast` only returns the **nearest** hit, while we need all of them. Writing an
"all hits" version would mean building another acceleration structure; a different approach avoids that -- **after a hit, move the origin
slightly past the hit point and cast again**, until nothing is hit. Each round is still one batched ray_cast, with only the
still-active points taking part. Convex bodies finish in two rounds, complex shapes in about ten.

The cost is passing the same points through the acceleration structure several times; the gain is not maintaining a second intersection code path, and with
intersection code, writing it twice guarantees one copy is wrong.

**The forward step size matters**: for numerical robustness `ray_cast` accepts hits with t >= -1e-6, and
that is an **absolute** tolerance. Step less than that and the next shot hits the same triangle again with t still -1e-7 -- spinning
in place until the limit (measured: 64 times). So the step has a lower bound of 4e-6.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vote over several directions, because **grazing hits** are bound to happen
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When a ray passes exactly through an edge or a vertex, that crossing is counted 0 or 2 times and the parity flips. On axis-aligned
meshes this is not a rare event -- cast along +Y through a regular cube and almost every ray grazes an edge.

The fix is to cast **three uncorrelated oblique directions** and take the majority. The chance of all three hitting the same degenerate spot
is negligible, and the cost is just three times the rays -- a very good trade compared to deriving a robust set of predicates.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT
from .spatial import ray_cast, tri_soup

# The directions must be **truly irregular**. The first version casually used (1,1,1)/sqrt(3) -- exactly the cube's body diagonal,
# which from the centre hits a vertex exactly, bouncing in that corner 128 times without getting out. Axis-aligned
# models are the most common input; any direction with small integer ratios (1,1,1), (1,2,1), (0,1,0) is a landmine.
# The three below use arbitrarily chosen irrational ratios, each normalized
_DIRS = np.array([[0.31229, 0.81773, 0.48311],
                  [-0.72113, 0.44331, 0.53211],
                  [0.60193, -0.21371, 0.76951]])
_DIRS = _DIRS / np.linalg.norm(_DIRS, axis=1, keepdims=True)


def _crossings(Q, d, P, tri, eps, max_hits=64):
    """
    (crossing count, whether this result is trustworthy). After a hit move the origin past it and cast again, until nothing is hit.

    Hitting the limit means the ray is stuck at a degenerate spot (repeatedly grazing an edge or a vertex);
    that vote is discarded and left to the other directions -- a parity counted by force would be wrong.
    """
    n = len(Q)
    cnt = np.zeros(n, np.int64)
    idx = np.arange(n)
    O = Q.copy()
    for _ in range(int(max_hits)):
        if not len(idx):
            break
        hit, t, _ = ray_cast(O[idx], np.tile(d, (len(idx), 1)), P, tri)
        ok = hit >= 0
        if not ok.any():
            idx = idx[:0]
            break
        cnt[idx[ok]] += 1
        # Move forward and cast again. **The step must exceed ray_cast's backward tolerance**: for numerical robustness it
        # accepts hits with t >= -1e-6 (an **absolute** tolerance); step less than that and the next shot
        # hits the same triangle again with t still -1e-7, spinning in place 64 times without getting out (measured)
        O[idx[ok]] = O[idx[ok]] + d * np.maximum(t[ok] + eps, eps)[:, None]
        idx = idx[ok]
    bad = np.zeros(n, bool)
    bad[idx] = True            # hit the limit before finishing
    return cnt, ~bad


def prepare(geo, group=""):
    """
    (P, tri) -- a triangle soup, to feed inside_mesh repeatedly.

    Triangulation itself runs ear clipping, tens of milliseconds for a few thousand faces; scattering inside a volume tries several batches,
    and re-triangulating every batch is pure waste (measured: scattering 300 points inside a sphere took 4.0s, 0.2s with caching).
    """
    tri, _, _ = tri_soup(geo, group)
    return geo.get(POINT, "P").astype(np.float64), tri


def inside_mesh(Q, geo, group="", directions=3, eps=None, soup=None):
    """
    (n,) bool: whether these points are inside the closed mesh.

    directions is the number of voting directions (1..3). **Default 3** -- grazing hits on axis-aligned meshes
    are a certainty, and with a single direction a whole row of points is misclassified.

    If soup is given it is used directly (see prepare), without re-triangulating.
    """
    Q = np.asarray(Q, np.float64).reshape(-1, 3)
    if not len(Q) or geo is None or geo.nprims == 0:
        return np.zeros(len(Q), bool)
    P, tri = prepare(geo, group) if soup is None else soup
    if not len(tri):
        return np.zeros(len(Q), bool)
    if eps is None:
        mn, mx = geo.bbox()
        size = float(np.max(np.asarray(mx, np.float64)
                            - np.asarray(mn, np.float64)))
        # The 4e-6 lower bound leaves margin over ray_cast's -1e-6 absolute backward tolerance.
        # Side effect: features thinner than that are skipped -- shells that thin can't hold up in floating point anyway
        eps = max(4e-6, max(size, 1.0) * 1e-6)

    k = int(np.clip(directions, 1, len(_DIRS)))
    yes = np.zeros(len(Q), np.int64)
    tot = np.zeros(len(Q), np.int64)
    for i in range(k):
        c, good = _crossings(Q, _DIRS[i], P, tri, eps)
        yes += (c & 1) & good
        tot += good
    return yes * 2 > np.maximum(tot, 1)


def bbox_samples(geo, n, rng, pad=0.0):
    """Scatters n points uniformly in the geometry's bounding box. Candidate source for scattering inside a volume."""
    mn, mx = geo.bbox()
    mn = np.asarray(mn, np.float64) - pad
    mx = np.asarray(mx, np.float64) + pad
    return mn + (mx - mn) * rng.random((int(n), 3))
