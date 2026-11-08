"""
UV Smooth (pcg77): relax in uv space.

━━ What it smooths on
uv is a vertex attribute; the same geometric point has two different uvs on the two sides of a seam. So corners are first grouped into wedges: corners on the same
geometric point with the same uv (difference ≤ Tolerance) form one wedge, and smoothing works on wedges -- the two sides of a seam each move
on their own and are not welded together. Edges between wedges come from the faces (polygons fan-triangulated).

━━ Weights
  uniform     weight 1 per edge (umbrella average). Simple and stable, but on irregular meshes it pulls the uv toward "evenly spaced points",
              unrelated to the 3D shape
  cotangent   cotangent weights of the **3D** triangles (cot α + cot β)/2. It has linear precision: on a flat patch in 3D,
              where the uv is linear to begin with (as projected), smoothing keeps that same linear uv (verified in the tests; uniform
              cannot) -- i.e. it only removes distortion "inconsistent with the 3D shape"
The cotangents of the triangles on the two sides of an edge are summed first, and only if the sum is negative (possible on non-Delaunay meshes) is it clamped to a small
positive number, so the iteration stays stable -- the first version clamped each triangle separately, which cut off the negative cotangents of obtuse triangles and lost linear precision
(uv off by 0.04 in the tests).

━━ Two solvers
  relax      Iterations rounds, each moving every free wedge toward its weighted neighbour average by Strength
  harmonic   solve directly to convergence (fixed wedges as boundary conditions, conjugate gradient) -- equivalent to relax with
             infinitely many rounds; islands without fixed points collapse to a point, so Pin Boundary or group is required
Pin Boundary fixes the boundary of each uv island (including seams); points outside group (a point group) are also fixed.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, VERTEX, is_string
from .groups import resolve

UV_WEIGHTS = ("cotangent", "uniform")
UV_SOLVES = ("relax", "harmonic")


def _wedges(vp, uv, tol):
    """Corners on the same point whose uvs differ by ≤ tol (chained) merge into one wedge."""
    n = len(vp)
    order = np.lexsort((uv[:, 1], uv[:, 0], vp))
    vs, us = vp[order], uv[order]
    new = np.ones(n, bool)
    if n > 1:
        same = vs[1:] == vs[:-1]
        close = np.abs(us[1:] - us[:-1]).max(1) <= tol
        new[1:] = ~(same & close)
    w = np.empty(n, np.int64)
    w[order] = np.cumsum(new) - 1
    return w, int(w.max()) + 1 if n else 0


def uv_smooth(geo, uv_attribute="uv", iterations=20, strength=0.5,
              weights="cotangent", solve="relax", pin_boundary=True, group="",
              tolerance=1e-6):
    """See the file header. Returns (geometry, report)."""
    if weights not in UV_WEIGHTS:
        raise ValueError(f"Weights must be one of {UV_WEIGHTS}")
    if solve not in UV_SOLVES:
        raise ValueError(f"Solve must be one of {UV_SOLVES}")
    name = str(uv_attribute).strip()
    a = geo.get(VERTEX, name)
    cls = VERTEX
    if a is None:
        a = geo.get(POINT, name)
        cls = POINT
    if a is None or is_string(a):
        raise KeyError(f"No numeric vertex / point attribute '{name}'")
    A = np.asarray(a, np.float64)
    vp = np.asarray(geo.vertex_point, np.int64)
    uvc = A if cls == VERTEX else A[vp]
    W, nw = _wedges(vp, uvc[:, :2], float(tolerance))
    tri, cor = geo.triangles(with_corners=True)
    tri = np.asarray(tri, np.int64)
    cor = np.asarray(cor, np.int64)
    if not len(tri):
        raise ValueError("No polygon primitives")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    U = np.zeros((nw, 2))
    U[W] = uvc[:, :2]
    tw = W[cor]                                          # (T,3) wedge
    # edges (i,j) and weights
    I, J, Wt = [], [], []
    for k in range(3):
        i, j, o = tw[:, k], tw[:, (k + 1) % 3], k
        if weights == "uniform":
            w = np.ones(len(tri))
        else:
            pa, pb, pc = P[tri[:, k]], P[tri[:, (k + 1) % 3]], P[tri[:, (k + 2) % 3]]
            u, v = pa - pc, pb - pc                     # the opposite corner is at the third point
            cr = np.linalg.norm(np.cross(u, v), axis=1)
            w = 0.5 * np.einsum("ij,ij->i", u, v) / np.maximum(cr, 1e-300)
        del o
        I.append(i)
        J.append(j)
        Wt.append(w)
    I = np.concatenate(I)
    J = np.concatenate(J)
    Wt = np.concatenate(Wt)
    # sum the cotangents of the triangles on both sides of the same edge before clamping (a single obtuse triangle's cotangent is negative, but the sum of both sides
    # is non-negative on a Delaunay mesh -- clamping before summing breaks linear precision)
    key = np.minimum(I, J) * nw + np.maximum(I, J)
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    ws = np.bincount(inv.reshape(-1), weights=Wt, minlength=len(uk))
    if weights == "cotangent":
        ref = float(np.abs(ws).mean()) if len(ws) else 1.0
        ws = np.maximum(ws, 1e-6 * ref)
    I, J, Wt = uk // nw, uk % nw, ws
    # boundary wedges: endpoints of (undirected) wedge edges used by only one triangle
    bk = uk[cnt == 1]
    fixed = np.zeros(nw, bool)
    rep = {"wedges": int(nw)}
    if pin_boundary:
        fixed[bk // nw] = True
        fixed[bk % nw] = True
    sel = resolve(geo, POINT, group)
    wpt = np.zeros(nw, np.int64)
    wpt[W] = vp
    fixed |= ~sel[wpt]
    rep["pinned"] = int(fixed.sum())
    # symmetric adjacency
    ii = np.concatenate([I, J])
    jj = np.concatenate([J, I])
    ww = np.concatenate([Wt, Wt])
    deg = np.bincount(ii, weights=ww, minlength=nw)
    free = ~fixed & (deg > 0)

    def avg(X):
        s = np.stack([np.bincount(ii, weights=ww * X[jj, c], minlength=nw)
                      for c in range(2)], 1)
        return s / np.maximum(deg, 1e-300)[:, None]

    if solve == "relax":
        s = float(strength)
        for _ in range(max(0, int(iterations))):
            U = np.where(free[:, None], U + s * (avg(U) - U), U)
    else:
        if not fixed.any():
            raise ValueError("harmonic needs fixed wedges (turn on Pin Boundary or restrict with group"
                             "), otherwise the whole island collapses to a point")
        # L u = 0 on free, u = given on fixed:(D − A) u_free = A_fixed u_fixed
        fi = np.nonzero(free)[0]
        idx = np.full(nw, -1, np.int64)
        idx[fi] = np.arange(len(fi))

        def apply(x):
            full = np.zeros((nw, 2))
            full[fi] = x
            s = np.stack([np.bincount(ii, weights=ww * full[jj, c], minlength=nw)
                          for c in range(2)], 1)
            return (deg[:, None] * full - s)[fi]
        base = np.where(free[:, None], 0.0, U)
        rhs = np.stack([np.bincount(ii, weights=ww * base[jj, c], minlength=nw)
                        for c in range(2)], 1)[fi]
        x = U[fi].copy()
        r = rhs - apply(x)
        p = r.copy()
        rr = (r * r).sum()
        bn = max(float(np.sqrt((rhs * rhs).sum())), 1e-300)
        it = 0
        for it in range(20000):
            if np.sqrt(rr) <= 1e-12 * bn:
                break
            Ap = apply(p)
            al = rr / (p * Ap).sum()
            x += al * p
            r -= al * Ap
            rr2 = (r * r).sum()
            p = r + rr2 / rr * p
            rr = rr2
        U[fi] = x
        rep["cg_iterations"] = int(it)
    out = geo.copy()
    newc = uvc.copy()
    newc[:, :2] = U[W]
    if cls == VERTEX:
        out.set(VERTEX, name, newc.astype(a.dtype), owned=True)
    else:
        pv = A.copy()
        pv[vp, :2] = newc[:, :2]
        out.set(POINT, name, pv.astype(a.dtype), owned=True)
    rep["moved_wedges"] = int(free.sum())
    return out, rep
