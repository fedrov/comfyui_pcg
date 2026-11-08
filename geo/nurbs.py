"""
NURBS evaluation core. Pure numpy, vectorized.

How the data is stored in the existing model:
    NURBS surface = one prim whose vertices are the **control point grid**, row-major (u fastest).
    prim attributes nu / nv give the grid size, uorder / vorder give the orders.
    Weights are the point attribute w (default 1); with weights it is rational, without it is a B-spline.
    The knot vector is **not stored**; it is derived from (n, order) -- a uniform clamped knot vector is fully determined by those two numbers.

Not storing knot vectors is a deliberate trade-off: Houdini allows arbitrary non-uniform knots, which would require attaching
variable-length data to the prim, and this model's attributes are fixed-size (N,C) arrays that cannot hold it. Uniform clamped covers
every case the Convert SOP actually produces; real non-uniform knots would first need a variable-length per-prim side channel
added to Geometry, which is a separate piece of work.

Order follows Houdini's definition: order = degree + 1. order 2 = polyline,
order 4 = cubic, the usual default for surfaces.
"""
from __future__ import annotations

import numpy as np


def clamped_knots(n: int, order: int) -> np.ndarray:
    """
    Uniform clamped knot vector for n control points and the given order, length n + order.
    Each end is repeated order times, so the curve passes through the first and last control points.
    """
    order = int(np.clip(order, 2, n))
    inner = n - order                      # number of interior knots
    kv = np.concatenate([
        np.zeros(order),
        (np.arange(1, inner + 1) / (inner + 1)) if inner > 0 else np.zeros(0),
        np.ones(order),
    ])
    return kv.astype(np.float64)


def bezier_knots(n: int, order: int) -> np.ndarray:
    """
    Knot vector of a piecewise Bezier: each end repeated order times, each interior breakpoint repeated order-1 times.
    This is the only difference between Bezier and NURBS -- basis functions, evaluation and interpolation all share one code path,
    only the knot vector differs. Interior knot multiplicity order-1 keeps adjacent segments only C0 continuous,
    i.e. each segment is independent and the control points are directly the Bezier control points.

    Requires n = segs*(order-1) + 1; if not satisfied, align first with valid_bezier_count.
    """
    o = int(np.clip(order, 2, n))
    segs = max(1, (n - 1) // (o - 1))
    kv = [0.0] * o
    for i in range(1, segs):
        kv += [i / segs] * (o - 1)
    kv += [1.0] * o
    return np.asarray(kv, np.float64)


def valid_bezier_count(n: int, order: int) -> int:
    """Nearest valid Bezier control point count not less than n."""
    o = max(2, int(order))
    segs = max(1, int(np.ceil((n - 1) / (o - 1))))
    return segs * (o - 1) + 1


def averaged_knots(params: np.ndarray, order: int) -> np.ndarray:
    """
    Knot vector from data point parameters (Piegl & Tiller averaging method).

    For global interpolation the knot vector should follow the distribution of the data points rather than be spread uniformly. Uniform knots
    with unevenly spaced data points make the basis matrix nearly singular and the solved control points oscillate wildly -- the denser
    the points, the worse. Averaging guarantees each span contains at least one data parameter, so the matrix is a well-conditioned band matrix.
    """
    t = np.asarray(params, np.float64)
    n = len(t)
    o = int(np.clip(order, 2, n))
    inner = n - o
    kv = np.zeros(n + o)
    kv[-o:] = 1.0
    for j in range(1, inner + 1):
        kv[o + j - 1] = t[j:j + o - 1].mean()
    return kv


def knots_for(kind: str, n: int, order: int,
              custom: np.ndarray | None = None) -> np.ndarray:
    """custom takes precedence. It is the non-uniform knot vector stored in the side channel."""
    if custom is not None:
        kv = np.asarray(custom, np.float64).reshape(-1)
        if len(kv) == n + int(np.clip(order, 2, n)):
            return kv
    return bezier_knots(n, order) if kind == "bezier" else clamped_knots(n, order)


def resample_points(pts: np.ndarray, m: int) -> np.ndarray:
    """Resample a point list to m points by chord length. Used for alignment when the Bezier control point count is constrained."""
    pts = np.asarray(pts, np.float64)
    t = chord_params(pts)
    tt = np.linspace(0, 1, m)
    return np.stack([np.interp(tt, t, pts[:, k]) for k in range(3)], 1)


def basis_matrix(knots: np.ndarray, order: int, n: int,
                 t: np.ndarray) -> np.ndarray:
    """
    (len(t), n) basis function matrix. Cox-de Boor recursion, advanced over the whole parameter vector.

    Writing it straight from the definition blows up on 0/0 (zero denominator at repeated knots), so each term is checked for zero separately --
    this is the standard Cox-de Boor treatment, not an edge case that can be skipped.
    """
    t = np.asarray(t, np.float64).reshape(-1)
    # A parameter on the last knot is assigned to the last span, otherwise searchsorted goes out of bounds
    t = np.clip(t, knots[order - 1], knots[n])
    m = len(t)

    N = np.zeros((m, n + order), np.float64)
    # Degree 0: find the knot span each parameter falls in
    span = np.searchsorted(knots, t, side="right") - 1
    span = np.clip(span, order - 1, n - 1)
    N[np.arange(m), span] = 1.0

    for d in range(1, order):
        Nn = np.zeros_like(N)
        for i in range(n + order - d - 1):
            den1 = knots[i + d] - knots[i]
            den2 = knots[i + d + 1] - knots[i + 1]
            a = ((t - knots[i]) / den1 * N[:, i]) if den1 > 0 else 0.0
            b = ((knots[i + d + 1] - t) / den2 * N[:, i + 1]) if den2 > 0 else 0.0
            Nn[:, i] = a + b
        N = Nn
    return N[:, :n]


def eval_curve(cps: np.ndarray, order: int, t: np.ndarray,
               w: np.ndarray | None = None, kind: str = "nurbs",
               knots: np.ndarray | None = None) -> np.ndarray:
    """(len(t), 3) points on the curve. Rational if w is given."""
    cps = np.asarray(cps, np.float64)
    n = len(cps)
    B = basis_matrix(knots_for(kind, n, order, knots),
                     int(np.clip(order, 2, n)), n, t)
    if w is None:
        return (B @ cps).astype(np.float32)
    w = np.asarray(w, np.float64).reshape(-1, 1)
    num = B @ (cps * w)
    den = B @ w
    return (num / np.maximum(den, 1e-12)).astype(np.float32)


def eval_surface(cps: np.ndarray, nu: int, nv: int, uorder: int, vorder: int,
                 tu: np.ndarray, tv: np.ndarray,
                 w: np.ndarray | None = None, kind: str = "nurbs",
                 ku: np.ndarray | None = None,
                 kv: np.ndarray | None = None) -> np.ndarray:
    """
    Tensor-product surface. cps is (nu*nv, 3), row-major (u fastest).
    Returns (len(tv), len(tu), 3).
    """
    cps = np.asarray(cps, np.float64).reshape(nv, nu, 3)
    uo = int(np.clip(uorder, 2, nu))
    vo = int(np.clip(vorder, 2, nv))
    Bu = basis_matrix(knots_for(kind, nu, uo, ku), uo, nu, tu)    # (mu, nu)
    Bv = basis_matrix(knots_for(kind, nv, vo, kv), vo, nv, tv)    # (mv, nv)
    if w is None:
        # Contract along u first, then along v: two matrix products, no need to build a big (mu*mv, nu*nv) matrix
        tmp = np.einsum("ij,vjc->vic", Bu, cps)               # (nv, mu, 3)
        return np.einsum("kv,vic->kic", Bv, tmp).astype(np.float32)
    W = np.asarray(w, np.float64).reshape(nv, nu, 1)
    tmp = np.einsum("ij,vjc->vic", Bu, cps * W)
    num = np.einsum("kv,vic->kic", Bv, tmp)
    tw = np.einsum("ij,vjc->vic", Bu, W)
    den = np.einsum("kv,vic->kic", Bv, tw)
    return (num / np.maximum(den, 1e-12)).astype(np.float32)


def chord_params(pts: np.ndarray) -> np.ndarray:
    """Chord-length parameterization normalized to [0,1]. Much more stable than uniform parameterization for unevenly spaced points."""
    pts = np.asarray(pts, np.float64)
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    c = np.concatenate([[0.0], np.cumsum(d)])
    total = c[-1]
    return c / total if total > 0 else np.linspace(0, 1, len(pts))


def interpolate_curve(pts: np.ndarray, order: int,
                      kind: str = "nurbs", return_knots=False):
    """
    Global interpolation: solve for control points so the curve **passes through** the given points. Corresponds to Houdini's
    Interpolate Through Hulls turned on.

    The method solves N . P = Q: N is the basis matrix at each data point's parameter, Q are the data points,
    P are the unknown control points. Clamped knots make the first and last points satisfied automatically; the matrix is a well-conditioned band matrix.
    """
    pts = np.asarray(pts, np.float64)
    n = len(pts)
    o = int(np.clip(order, 2, n))
    t = chord_params(pts)
    kv = bezier_knots(n, o) if kind == "bezier" else averaged_knots(t, o)
    N = basis_matrix(kv, o, n, t)
    try:
        cps = np.linalg.solve(N, pts)
    except np.linalg.LinAlgError:
        # Degenerate point lists (duplicate points, dense collinear points) make the matrix singular; fall back to least squares
        cps = np.linalg.lstsq(N, pts, rcond=None)[0]
    return (cps, kv, t) if return_knots else cps


def interpolate_surface(grid: np.ndarray, uorder: int, vorder: int,
                        kind: str = "nurbs", return_knots=False):
    """
    Global surface interpolation. grid is an (nv, nu, 3) grid of data points.
    The tensor product is separable, so solve once per row along u, then once per column along v.
    """
    grid = np.asarray(grid, np.float64)
    nv, nu = grid.shape[:2]
    uo = int(np.clip(uorder, 2, nu))
    vo = int(np.clip(vorder, 2, nv))

    # u direction: parameters are the average chord-length parameters over all rows, so the whole surface uses one set of knots
    tu = np.mean([chord_params(grid[i]) for i in range(nv)], axis=0)
    tv = np.mean([chord_params(grid[:, j]) for j in range(nu)], axis=0)

    kvu = bezier_knots(nu, uo) if kind == "bezier" else averaged_knots(tu, uo)
    kvv = bezier_knots(nv, vo) if kind == "bezier" else averaged_knots(tv, vo)
    Nu = basis_matrix(kvu, uo, nu, tu)
    Nv = basis_matrix(kvv, vo, nv, tv)

    def solve(M, B):
        try:
            return np.linalg.solve(M, B)
        except np.linalg.LinAlgError:
            return np.linalg.lstsq(M, B, rcond=None)[0]

    tmp = np.stack([solve(Nu, grid[i]) for i in range(nv)])       # (nv, nu, 3)
    out = np.stack([solve(Nv, tmp[:, j]) for j in range(nu)], 1)  # (nv, nu, 3)
    return (out, kvu, kvv, tu, tv) if return_knots else out


def tessellate_surface(cps, nu, nv, uorder, vorder, du, dv, w=None,
                       kind="nurbs", ku=None, kv=None):
    """
    Surface -> quad mesh. Returns (points, faces).
    du / dv are the **number of sample points** in each direction, consistent with rows/cols of this package's grid/sphere.
    """
    du, dv = max(2, int(du)), max(2, int(dv))
    tu = np.linspace(0, 1, du)
    tv = np.linspace(0, 1, dv)
    P = eval_surface(cps, nu, nv, uorder, vorder, tu, tv, w, kind,
                     ku, kv).reshape(-1, 3)
    i = np.arange(dv - 1)[:, None]
    j = np.arange(du - 1)[None, :]
    a = i * du + j
    faces = np.stack([a, a + du, a + du + 1, a + 1], -1).reshape(-1, 4)
    return P, faces.astype(np.int32)


def tessellate_curve(cps, order, divs, w=None, kind="nurbs", knots=None):
    """Curve -> polyline point list."""
    divs = max(2, int(divs))
    return eval_curve(cps, order, np.linspace(0, 1, divs), w, kind, knots)


# ------------------------------------------------------------------ splitting
def insert_knot(cps, knots, order, u, times=1):
    """
    Boehm knot insertion. Returns (new control points, new knot vector); the curve shape is **completely unchanged**.

    Carve depends on it: after inserting at parameter u degree times, the curve is "pinned" there,
    and the control point sequence can be cut directly in the middle; both halves are still valid NURBS.
    Subdividing into a polyline can also cut, but then it is no longer a curve -- the type is lost and downstream can no longer change the order.
    """
    cps = np.asarray(cps, np.float64)
    kv = np.asarray(knots, np.float64).copy()
    p = int(order) - 1
    for _ in range(int(times)):
        n = len(cps)
        k = int(np.searchsorted(kv, u, side="right") - 1)
        k = int(np.clip(k, p, n - 1))
        new = np.empty((n + 1, cps.shape[1]), np.float64)
        new[:k - p + 1] = cps[:k - p + 1]
        new[k + 1:] = cps[k:]
        for i in range(k - p + 1, k + 1):
            den = kv[i + p] - kv[i]
            a = 0.0 if den == 0 else (u - kv[i]) / den
            new[i] = (1 - a) * cps[i - 1] + a * cps[i]
        cps = new
        kv = np.insert(kv, k + 1, u)
    return cps, kv


def _multiplicity(kv, u, tol=1e-9):
    return int(np.sum(np.abs(np.asarray(kv) - u) < tol))


def split_curve(cps, knots, order, u):
    """
    Split the curve into two at parameter u; both halves are valid clamped NURBS and the shape is unchanged.

    The method inserts u up to **multiplicity = order**, at which point the knot vector is fully clamped there and the control point sequence
    can be cut directly. Let a be the index of the first occurrence of u after insertion:
        left  = cps[:a],  knots[:a+order]
        right = cps[a:],  knots[a:]
    These two slices were found by numeric search and verified (error 0), not derived -- a version with the index off by one
    has an error of 1.2 and does not raise, the shape just silently changes.
    """
    cps = np.asarray(cps, np.float64)
    kv = np.asarray(knots, np.float64)
    o = int(order)
    need = o - _multiplicity(kv, u)
    if need > 0:
        cps, kv = insert_knot(cps, kv, o, u, need)
    a = int(np.searchsorted(kv, u, side="left"))
    return (cps[:a], kv[:a + o]), (cps[a:], kv[a:])


def subcurve(cps, knots, order, u0, u1):
    """Extract the segment over the parameter interval [u0, u1], still a NURBS. Knots are renormalized to [0,1]."""
    cps = np.asarray(cps, np.float64)
    kv = np.asarray(knots, np.float64)
    o = int(order)
    lo, hi = kv[o - 1], kv[len(cps)]
    u0, u1 = float(min(u0, u1)), float(max(u0, u1))
    u0 = float(np.clip(u0, lo, hi))
    u1 = float(np.clip(u1, lo, hi))
    if u1 - u0 < 1e-12:
        return cps[:1].copy(), np.array([0.0] * o + [1.0] * o)

    if u0 > lo + 1e-12:
        _, (cps, kv) = split_curve(cps, kv, o, u0)
    if u1 < hi - 1e-12:
        (cps, kv), _ = split_curve(cps, kv, o, u1)
    kv = (kv - kv[0]) / max(kv[-1] - kv[0], 1e-12)
    return cps, kv


def arclen_to_param(cps, order, knots, targets, samples=512, kind="nurbs"):
    """
    Map relative arc length to parameter. Corresponds to Houdini's Carve Curves by Relative Arc Length.

    Parameterization is usually not proportional to arc length -- where control points are spaced differently, the same parameter increment
    covers very different actual lengths. Cutting by arc length matches the intuition of "cut off the first quarter".
    """
    t = np.linspace(0, 1, samples)
    P = eval_curve(cps, order, t, None, kind, knots).astype(np.float64)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    total = d[-1]
    if total <= 0:
        return np.asarray(targets, np.float64)
    return np.interp(np.asarray(targets, np.float64), d / total, t)
