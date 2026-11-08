"""
Bound -- bounding box / bounding sphere / minimum-volume oriented bounding box. Counterpart of Houdini's Bound SOP.

The three modes are three accuracy levels for the same problem:

    box       axis-aligned bounding box. Fastest and most common, but absurdly bloated as soon as the object is tilted
    sphere    bounding sphere. Rotation-invariant, the easiest for coarse culling (broad phase)
    oriented  minimum-volume oriented bounding box (OBB). Tight-fitting, at the cost of computing a convex hull first

For a thin rod lying at 45 deg, the axis-aligned box can have more than ten times the volume of the OBB -- using it as a collision proxy
means counting a big chunk of the surrounding air as solid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OBB: no need to sweep all orientations; trying the **faces of the convex hull** is enough
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
O'Rourke's result: the minimum-volume oriented bounding box always has **one face flush with some face of the convex hull**.
The 2-D version is more familiar -- "the minimum-area bounding rectangle always has one side flush with some edge of the convex hull"; the
rotating calipers in UV Layout use exactly that.

So the enumeration is finite:

    for each face of the convex hull
        use its normal as one axis and project the hull vertices onto that plane
        do a 2-D minimum-area rectangle in the plane (rotating calipers again) -> the other two axes
        extent along the normal = box height
        volume = area * height, keep the smallest

Only **convex hull vertices** take part: the bounding box is determined only by the outermost points; interior points don't affect the result at all.
The hull of a 50k-point cloud may have only a few dozen vertices, which makes the enumeration much cheaper.

An honest approximation: when the face count exceeds `max_normals`, only the normals of the largest faces are kept. For sphere-like input where
every face normal is different, enumerating 700 orientations is pure waste -- and a sphere's OBB is roughly a
cube anyway, so trying fewer directions makes little difference. Angular man-made objects have few faces once coplanar faces are merged
(6 for a cube), so they always take the exact path.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bounding sphere: start with Ritter, then tighten by "moving a little towards the farthest point"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The exact minimum bounding sphere (Welzl) is a recursive algorithm with a pile of degenerate cases to handle. Here, two steps:

    1. Ritter: take a pair of farthest-apart points as the diameter, then expand point by point
    2. Badoiu-Clarkson: repeat "move the centre 1/k towards the current farthest point"

BC converges at **O(1/k)**, truly slow: on a regular tetrahedron 64 rounds still leave 3.4e-3, reaching 1e-5
takes four thousand rounds -- and each round is a scan over all points, 2.5 s for 20k points.

So two phases: first 64 coarse rounds to locate, then **keep only the shell beyond 0.85 times the max distance from the coarse centre**
(the minimum sphere is determined only by the outermost few points, interior points don't matter at all), and run the full
2048 rounds on that small subset. Measured: regular tetrahedron error 1.7e-6, cube's eight corners exact, 20k points 0.10 s / 200k points
0.86 s.

Finally there is **one more safety net**, computed over **all** points: the shell filtering is heuristic; if it ever misses a
decisive point, this expands the radius back -- the result can only be slightly larger than optimal, it never misses a point. "Bounding"
cannot be compromised.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The output carries detail attributes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The box/sphere itself is for people to look at; what downstream really uses are the numbers:

    bound_center (3)   centre
    bound_size   (3)   size in three directions (three diameters for the sphere)
    bound_rot    (9)   row-major rotation matrix; the three rows are the three axes (identity for box/sphere)
    bound_volume (1)   volume

With bound_rot you can straighten the object, or align other things to it, without computing it again.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, DETAIL
from . import build

MODES = ("box", "sphere", "oriented")


def _points(geo, group):
    from .groups import resolve
    P = geo.get(POINT, "P")
    if P is None or geo.npoints == 0:
        return np.zeros((0, 3), np.float64)
    sel = resolve(geo, POINT, group)
    return np.asarray(P, np.float64)[sel]


def _hull2d(V):
    """2-D convex hull (Andrew monotone chain); returns points counter-clockwise."""
    p = np.unique(V, axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2:
                a, b = out[-2], out[-1]
                if ((b[0] - a[0]) * (q[1] - a[1])
                        - (b[1] - a[1]) * (q[0] - a[0])) > 0:
                    break
                out.pop()
            out.append(q)
        return out
    return np.asarray(half(p)[:-1] + half(list(p[::-1]))[:-1])


def min_rect(V):
    """
    2-D minimum-area bounding rectangle. Returns (angle, width, height, centre).

    Rotating calipers: the minimum-area rectangle always has one side flush with some hull edge, so only hull edges are tried.
    The angle is "the rotation needed to bring that hull edge level"; width and height are measured in the coordinate system **after rotation**.
    """
    V = np.asarray(V, np.float64)
    if len(V) == 0:
        return 0.0, 0.0, 0.0, np.zeros(2)
    h = _hull2d(V)
    if len(h) < 3:
        lo, hi = V.min(0), V.max(0)
        return 0.0, float(hi[0] - lo[0]), float(hi[1] - lo[1]), (lo + hi) / 2
    e = np.roll(h, -1, axis=0) - h
    ang = np.arctan2(e[:, 1], e[:, 0])
    c, s = np.cos(-ang), np.sin(-ang)
    # (E,H): rotate the whole hull by -ang[i] and measure its bounding box
    X = np.outer(c, h[:, 0]) - np.outer(s, h[:, 1])
    Y = np.outer(s, h[:, 0]) + np.outer(c, h[:, 1])
    w = X.max(1) - X.min(1)
    ht = Y.max(1) - Y.min(1)
    i = int(np.argmin(w * ht))
    cx = (X[i].max() + X[i].min()) / 2
    cy = (Y[i].max() + Y[i].min()) / 2
    a = float(ang[i])
    ca, sa = np.cos(a), np.sin(a)
    # The centre was computed in the rotated frame; rotate it back
    ctr = np.array([cx * ca - cy * sa, cx * sa + cy * ca])
    return a, float(w[i]), float(ht[i]), ctr


def _bc(Q, c, iters):
    """Badoiu-Clarkson: each round moves 1/(k+1) towards the current farthest point."""
    for k in range(1, int(iters) + 1):
        far = Q[int(np.argmax(((Q - c) ** 2).sum(1)))]
        c = c + (far - c) / (k + 1)
    return c


def min_sphere(Q, iters=2048, probe=64, shell=0.85):
    """
    Approximate minimum bounding sphere. Ritter start + Badoiu-Clarkson tightening + safety-net expansion.

    Returns (center, radius). Convergence is O(1/k): measured on a regular tetrahedron, 64 rounds give error 3.4e-3,
    1024 rounds 2.1e-4, 4096 rounds 5.4e-5. Accuracy needs more iterations, but each round is a scan over all points;
    4096 rounds on 20k points take 2.5 s -- unacceptable.

    So **two phases**: probe rounds for coarse location, then keep only the shell "far enough from the coarse centre"
    (the minimum sphere is determined only by the outermost few points, interior points don't matter at all), and run the full
    iters rounds on that much smaller subset. 20k points in 0.09 s, with the same accuracy as iterating over everything.

    The final expansion is mandatory, and computed over **all** points: the shell filtering is heuristic; if it ever misses
    a decisive point, this expands the radius back -- the result can only be slightly larger than optimal, it never misses a point.
    "Bounding" cannot be compromised.
    """
    Q = np.asarray(Q, np.float64)
    if len(Q) == 0:
        return np.zeros(3), 0.0
    if len(Q) == 1:
        return Q[0].copy(), 0.0
    # Ritter: from one point find the farthest, from that find the farthest, use the pair as the diameter
    a = Q[int(np.argmax(((Q - Q[0]) ** 2).sum(1)))]
    b = Q[int(np.argmax(((Q - a) ** 2).sum(1)))]
    c = (a + b) / 2
    r = float(np.linalg.norm(b - a) / 2)
    for q in Q:
        d = float(np.linalg.norm(q - c))
        if d > r:
            c = c + (d - r) / (2 * d) * (q - c)
            r = (r + d) / 2
    c = _bc(Q, c, probe)
    d2 = ((Q - c) ** 2).sum(1)
    S = Q[d2 >= d2.max() * float(shell) ** 2]
    c = _bc(S if len(S) >= 2 else Q, c, iters)
    r = float(np.sqrt(((Q - c) ** 2).sum(1).max()))
    return c, r


def oriented_frame(Q, tol=1e-6, max_normals=256):
    """
    Minimum-volume oriented bounding box. Returns (center, size(3), R(3,3) whose rows are the three axes).

    Only hull vertices are used and only the normals of hull faces are tried -- O'Rourke: the optimal box always has one face flush with
    some hull face. With too many faces the top max_normals by area are taken; the result is then "approximately optimal".
    """
    from .hull import convex_hull_indices, _rank
    Q = np.asarray(Q, np.float64)
    if len(Q) < 4:
        mn, mx = Q.min(0), Q.max(0)
        return (mn + mx) / 2, mx - mn, np.eye(3)
    r, V = _rank(Q, tol)
    if r < 3:
        # Degenerate: the principal axes are the best frame, there is no volume to optimize
        c = Q.mean(0)
        L = (Q - c) @ V
        mn, mx = L.min(0), L.max(0)
        return c + V @ ((mn + mx) / 2), mx - mn, V.T.copy()

    tri = convex_hull_indices(np.unique(Q, axis=0), tol)
    U = np.unique(Q, axis=0)
    if not len(tri):
        c = Q.mean(0)
        L = (Q - c) @ V
        mn, mx = L.min(0), L.max(0)
        return c + V @ ((mn + mx) / 2), mx - mn, V.T.copy()
    W = U[np.unique(tri)]                      # only hull vertices take part

    A, B, C = U[tri[:, 0]], U[tri[:, 1]], U[tri[:, 2]]
    N = np.cross(B - A, C - A)
    area2 = np.linalg.norm(N, axis=1)
    keep = area2 > 0
    N, area2 = N[keep], area2[keep]
    N = N / area2[:, None]
    # Deduplicate normals (merging coplanar faces), then take the top max_normals by area
    key = np.round(N / max(np.sqrt(tol), 1e-4)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True,
                              return_inverse=True)
    w = np.bincount(inv.reshape(-1), weights=area2)
    order = np.argsort(-w)[:int(max_normals)]
    cand = N[first[order]]

    best = None
    for n in cand:
        # Some arbitrary vector not parallel to n, crossed to get an orthonormal basis in the plane
        t = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 \
            else np.array([0.0, 1.0, 0.0])
        u = np.cross(n, t)
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        proj = np.c_[W @ u, W @ v]
        a, w2, h2, ctr = min_rect(proj)
        hn = W @ n
        depth = float(hn.max() - hn.min())
        volume = w2 * h2 * depth
        if best is None or volume < best[0]:
            ca, sa = np.cos(a), np.sin(a)
            # The two axes after levelling, rotated back to 3-D
            e1 = ca * u + sa * v
            e2 = -sa * u + ca * v
            c3 = ctr[0] * u + ctr[1] * v + n * ((hn.max() + hn.min()) / 2)
            best = (volume, c3, np.array([w2, h2, depth]),
                    np.stack([e1, e2, n]))
    return best[1], best[2], best[3]


def _tag(g, center, size, R, volume):
    g.set(DETAIL, "bound_center",
          np.asarray(center, np.float32).reshape(1, 3), owned=True)
    g.set(DETAIL, "bound_size",
          np.asarray(size, np.float32).reshape(1, 3), owned=True)
    g.set(DETAIL, "bound_rot",
          np.asarray(R, np.float32).reshape(1, 9), owned=True)
    g.set(DETAIL, "bound_volume",
          np.array([[float(volume)]], np.float32), owned=True)
    return g


def bound(geo, mode="box", group="", padding=(0.0, 0.0, 0.0),
          uniform_padding=0.0, divisions=(1, 1, 1), sphere_cols=24,
          sphere_rows=16, tol=1e-6, max_normals=256):
    """
    Bounding box / bounding sphere / minimum-volume OBB.

    padding is the amount pushed outward in each of the three directions (per side, consistent with Houdini -- padding 0.1 means
    0.1 is added on each side, 0.2 to the total size); uniform_padding pushes all three directions together.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    Q = _points(geo, group)
    if len(Q) == 0:
        raise ValueError("Bound needs at least one point -- the input is empty, or the group selects nothing.")

    pad = np.asarray(padding, np.float64).reshape(3) + float(uniform_padding)

    if mode == "sphere":
        c, r = min_sphere(Q)
        r = float(r + max(float(pad.max()), 0.0))
        g = build.sphere(radius=max(r, 1e-9), cols=int(max(3, sphere_cols)),
                         rows=int(max(2, sphere_rows)), center=tuple(c))
        return _tag(g, c, np.full(3, 2 * r), np.eye(3),
                    4.0 / 3.0 * np.pi * r ** 3)

    if mode == "oriented":
        c, size, R = oriented_frame(Q, tol, max_normals)
        size = np.maximum(size + 2 * pad, 0.0)
        g = build.box(size=tuple(size), center=(0, 0, 0),
                      divisions=tuple(int(max(2, d)) for d in divisions))
        P = np.asarray(g.get(POINT, "P"), np.float64)
        g.set(POINT, "P", (P @ R + c).astype(np.float32), owned=True)
        return _tag(g, c, size, R, float(np.prod(size)))

    mn, mx = Q.min(0) - pad, Q.max(0) + pad
    size = np.maximum(mx - mn, 0.0)
    c = (mn + mx) / 2
    g = build.box(size=tuple(size), center=tuple(c),
                  divisions=tuple(int(max(2, d)) for d in divisions))
    return _tag(g, c, size, np.eye(3), float(np.prod(size)))
