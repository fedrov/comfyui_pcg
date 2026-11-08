"""
Point Relax (pcg79): push any point cloud apart until there is no overlap within the radius.

Each point is a ball of radius r (pscale x Radius Scale; the Radius parameter if there is no pscale); two points
overlap when distance d < r_i + r_j, and each backs off half (all of it when the other is a fixed point outside the group). Each iteration all
overlapping pairs are computed together and displacements summed; each point moves at most Max Step x r per step (so a tightly packed point does not fly off in one step),
then is projected back onto Surface (if connected). Stops early when there are no more overlaps.

    With Radius = 0 and no pscale the radius is set automatically: with Surface connected, by "N points in a hexagonal arrangement exactly covering
    the surface area" r = sqrt(A / (2.sqrt(3).N)) (exactly no overlap in the ideal arrangement); without it, half the mean nearest-neighbour distance
    (after pushing apart, spacing evens out toward this mean)
    points outside group do not move, but still block others
    two exactly coincident points are pushed apart along a direction determined by point number (deterministic, not random)

Scatter's Relax only handles freshly scattered points and only on the surface; this one takes any points (Copy target points, hand-placed points,
points computed by an earlier step), works without a surface (pushing apart in 3D), and handles points with different pscale sizes.
"""
from __future__ import annotations

import numpy as np

from .core import POINT
from .groups import resolve


def _auto_radius(P, tri, Ps):
    n = len(P)
    if tri is not None and len(tri):
        A, B, C = Ps[tri[:, 0]], Ps[tri[:, 1]], Ps[tri[:, 2]]
        area = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1).sum()
        return float(np.sqrt(area / (2 * np.sqrt(3) * n)))
    from .spatial import nearest

    def ev(qi, ti):
        d = np.linalg.norm(P[qi] - P[ti], axis=1)
        return np.where(qi == ti, np.inf, d), np.zeros((len(qi), 0))
    _, d, _ = nearest(P, P, P, ev)
    d = d[np.isfinite(d)]
    return 0.5 * float(np.mean(d)) if len(d) else 0.0


def point_relax(geo, surface=None, iterations=20, radius=0.0, use_pscale=True,
                radius_scale=1.0, max_step=0.5, group=""):
    """Returns (geometry, report)."""
    from .spatial import neighbors_within, closest_surface, tri_soup
    n = geo.npoints
    if n == 0:
        return geo.copy(), {"iterations": 0}
    P = np.asarray(geo.get(POINT, "P"), np.float64).copy()
    mov = resolve(geo, POINT, group)
    tri = Ps = None
    if surface is not None and surface.nprims:
        tri = np.asarray(tri_soup(surface)[0], np.int64)
        Ps = np.asarray(surface.get(POINT, "P"), np.float64)
        if not len(tri):
            tri = None
    ps = geo.get(POINT, "pscale") if use_pscale else None
    if ps is not None:
        r = np.asarray(ps, np.float64)[:, 0].copy()
    elif float(radius) > 0:
        r = np.full(n, float(radius))
    elif n > 1:
        r = np.full(n, _auto_radius(P, tri, Ps))
    else:
        r = np.zeros(n)
    r = np.maximum(r * float(radius_scale), 0.0)
    if tri is not None:
        _, _, Q, _ = closest_surface(P[mov], Ps, tri)
        P[mov] = Q
    rmax = float(r.max())
    ms = float(max_step)
    it_used, worst = 0, 0.0

    def overlaps(X):
        qi, pi, d = neighbors_within(X, X, 2 * rmax)
        k = (qi < pi) & (d < r[qi] + r[pi]) & (mov[qi] | mov[pi])
        return qi[k], pi[k], d[k]
    first = None
    for it in range(max(0, int(iterations))):
        qi, pi, d = overlaps(P)          # when all radii are 0 no pairs are found and it stops below
        ov = r[qi] + r[pi] - d
        if first is None:
            first = float((ov / np.maximum(r[qi] + r[pi], 1e-300)).max()) \
                if len(ov) else 0.0
        if not len(qi):
            break
        it_used = it + 1
        v = P[qi] - P[pi]
        zero = d < 1e-12
        if zero.any():
            # Coincident points: choose a direction by point number (golden-angle spiral), deterministic
            k = (qi[zero] * 7919 + pi[zero]).astype(np.float64)
            z = 1 - 2 * ((k * 0.6180339887) % 1.0)
            ph = k * 2.399963229728653
            s = np.sqrt(np.maximum(1 - z * z, 0))
            v[zero] = np.stack([s * np.cos(ph), z, s * np.sin(ph)], 1)
            d = np.where(zero, 1.0, d)
        u = v / np.maximum(np.linalg.norm(v, axis=1), 1e-300)[:, None]
        both = mov[qi] & mov[pi]
        wq = np.where(both, 0.5, np.where(mov[qi], 1.0, 0.0)) * ov
        wp = np.where(both, 0.5, np.where(mov[pi], 1.0, 0.0)) * ov
        D = np.zeros_like(P)
        np.add.at(D, qi, u * wq[:, None])
        np.add.at(D, pi, -u * wp[:, None])
        L = np.linalg.norm(D, axis=1)
        lim = ms * r
        D *= np.where(L > lim, lim / np.maximum(L, 1e-300), 1.0)[:, None]
        P += D                           # D of points outside the group is 0 (both weights are 0)
        if tri is not None:
            _, _, Q, _ = closest_surface(P[mov], Ps, tri)
            P[mov] = Q
    qi, pi, d = overlaps(P)
    if len(qi):
        worst = float(((r[qi] + r[pi] - d) / np.maximum(r[qi] + r[pi], 1e-300)).max())
    g = geo.copy()
    g.set(POINT, "P", P.astype(geo.get(POINT, "P").dtype), owned=True)
    return g, {"iterations": it_used, "radius_max": rmax,
               "overlap_before": first or 0.0, "overlap_after": worst,
               "overlapping_pairs": int(len(qi))}
