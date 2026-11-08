"""
Distance from Geometry / Distance along Geometry SOPs (pcg121).

Distance from Geometry
  Straight-line distance from every point of the input to a reference geometry, written to a point attribute, plus an
  optional 0..1 mask through a falloff ramp. Three reference metrics:
    surface  closest point on the reference's polygons (spatial.closest_surface: exact, KD-tree accelerated)
    edges    closest point on the reference's edges / polylines (curve networks, wire frames)
    points   nearest reference point
  Max Distance clamps: points farther than it get the max value (Houdini writes the clamp value, not a sentinel), and
  the search is bounded by it, which is also what makes it fast.

Distance along Geometry
  Distance from a start group measured **on** the surface (point to point through the mesh), not through space.
    edges     Dijkstra over the edge graph (scipy.sparse.csgraph). Exact path length along edges; on a regular grid it
              overestimates diagonal distances (a staircase: up to 41% (sqrt 2) across a quad grid, ~8% on triangles).
    geodesic  the heat method (Crane, Weischedel, Wardetzky 2013): diffuse heat from the sources for one short step,
              normalise its gradient, and solve a Poisson equation whose solution has that gradient. It follows the
              surface smoothly (no staircase) at the cost of two sparse solves on the triangulated mesh. Exact distances
              are not guaranteed: on a sphere the error is ~0.1%, on a fan-triangulated quad grid ~2% median, up to ~8% at
              worst (the diagonals all lean one way; finer meshes are better). Heat Time scales the diffusion step (1 = mean edge length squared).
  Points not connected to any start point get -1 (they are unreachable), like Houdini.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM, PRIM_POLY
from .groups import resolve

METRICS = ("surface", "edges", "points")
ALONG_METHODS = ("geodesic", "edges")


def _ramp(t, ramp, mode):
    from .ramp import parse, apply
    pos, val = parse(str(ramp), 1)
    return np.asarray(apply(t, pos, val, mode), np.float64).reshape(-1)


def _write(geo, mask_pts, d, dist_attrib, use_max, max_dist, output_mask, mask_attrib, mask_radius, ramp, ramp_mode,
           unreachable=None):
    """Write distance (and mask) onto the selected points; others keep 0 (or an existing attribute)."""
    out = geo.copy()
    n = out.npoints
    name = str(dist_attrib).strip() or "dist"
    old = out.get(POINT, name)
    full = (np.asarray(old, np.float64)[:, 0].copy() if old is not None and old.shape[1] == 1
            else np.zeros(n))
    dd = np.asarray(d, np.float64)
    if use_max and max_dist > 0:
        dd = np.where(np.isfinite(dd), np.minimum(dd, float(max_dist)), float(max_dist))
    if unreachable is not None:
        dd = np.where(unreachable, -1.0, dd)
    full[mask_pts] = dd
    out.set(POINT, name, full.astype(np.float32)[:, None], owned=True)
    if output_mask:
        mname = str(mask_attrib).strip() or "mask"
        r = max(float(mask_radius), 1e-12)
        t = np.clip(dd / r, 0.0, 1.0)
        m = _ramp(t, ramp, ramp_mode)
        if unreachable is not None:
            m = np.where(unreachable, _ramp(np.ones(1), ramp, ramp_mode)[0], m)
        oldm = out.get(POINT, mname)
        fm = (np.asarray(oldm, np.float64)[:, 0].copy() if oldm is not None and oldm.shape[1] == 1
              else np.zeros(n))
        fm[mask_pts] = m
        out.set(POINT, mname, fm.astype(np.float32)[:, None], owned=True)
    return out


def _segments(ref, group=""):
    """(S,2) point pairs of the reference's edges: polygon edges and polyline segments of the selected prims."""
    from .ops import delete_prims
    if str(group).strip():
        ref = delete_prims(ref, resolve(ref, PRIM, group))
    sizes = ref.prim_sizes()
    keep = (ref.prim_type == PRIM_POLY) & (sizes >= 2)
    segs = []
    for i in np.nonzero(keep)[0]:
        p = ref.prim_points(int(i)).astype(np.int64)
        if ref.prim_closed[i] and len(p) >= 3:
            segs.append(np.stack([p, np.roll(p, -1)], 1))
        else:
            segs.append(np.stack([p[:-1], p[1:]], 1))
    if not segs:
        return ref, np.zeros((0, 2), np.int64)
    s = np.unique(np.sort(np.concatenate(segs), 1), axis=0)
    return ref, s


def distance_from_geometry(geo, ref, group="", ref_group="", metric="surface", dist_attrib="dist", use_max=False,
                           max_dist=1.0, output_mask=False, mask_attrib="mask", mask_radius=1.0,
                           ramp="0:1  1:0", ramp_mode="linear"):
    """Returns (geometry, report)."""
    from . import spatial as S
    if metric not in METRICS:
        raise ValueError(f"Metric must be one of {METRICS}")
    if ref is None:
        raise ValueError("Distance from Geometry needs a reference geometry (second input)")
    sel = resolve(geo, POINT, group)
    Q = np.asarray(geo.get(POINT, "P"), np.float64)[sel]
    md = float(max_dist) if use_max and max_dist > 0 else 0.0
    if metric == "surface":
        from .ops import delete_prims
        r = delete_prims(ref, resolve(ref, PRIM, ref_group)) if str(ref_group).strip() else ref
        tri, _ = r.triangles(with_corners=True)
        if not len(tri):
            raise ValueError("Metric = Surface needs polygons on the reference; use Edges for curves, Points for clouds")
        _, d, _, _ = S.closest_surface(Q, np.asarray(r.get(POINT, "P"), np.float64), tri, max_dist=md)
    elif metric == "edges":
        r, segs = _segments(ref, ref_group)
        if not len(segs):
            raise ValueError("Metric = Edges needs polygons or polylines on the reference")
        RP = np.asarray(r.get(POINT, "P"), np.float64)
        A, B = RP[segs[:, 0]], RP[segs[:, 1]]

        def ev(qi, ti):
            a, ab = A[ti], B[ti] - A[ti]
            den = np.einsum("ij,ij->i", ab, ab)
            t = np.clip(np.einsum("ij,ij->i", Q[qi] - a, ab) / np.where(den > 0, den, 1.0), 0.0, 1.0)
            return np.linalg.norm(a + t[:, None] * ab - Q[qi], axis=1), np.zeros((len(qi), 0))
        _, d, _ = S.nearest(Q, np.minimum(A, B), np.maximum(A, B), ev, max_dist=md)
    else:
        RP = np.asarray(ref.get(POINT, "P"), np.float64)
        if str(ref_group).strip():
            RP = RP[resolve(ref, POINT, ref_group)]
        if not len(RP):
            raise ValueError("The reference has no points")

        def ev(qi, ti):
            return np.linalg.norm(Q[qi] - RP[ti], axis=1), np.zeros((len(qi), 0))
        _, d, _ = S.nearest(Q, RP, RP, ev, max_dist=md)
    out = _write(geo, sel, d, dist_attrib, use_max, max_dist, output_mask, mask_attrib, mask_radius, ramp, ramp_mode)
    fin = np.isfinite(d)
    rep = {"points": int(sel.sum()), "metric": metric,
           "min": float(d[fin].min()) if fin.any() else None, "max": float(d[fin].max()) if fin.any() else None,
           "beyond_max": int((~fin).sum())}
    return out, rep


# ═══════════════════════════════════════════════════════════ along the surface
def _edge_graph(geo):
    from .topology import topology
    from scipy.sparse import coo_matrix
    t = topology(geo)
    E = np.asarray(t.edge_points, np.int64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    w = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    n = geo.npoints
    w = np.where(w > 0, w, 1e-12)                       # csgraph treats explicit zeros as missing edges
    return coo_matrix((np.r_[w, w], (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])), shape=(n, n)).tocsr()


def _dijkstra(geo, src):
    from scipy.sparse.csgraph import dijkstra
    G = _edge_graph(geo)
    return dijkstra(G, directed=False, indices=src, min_only=True)


def _cotan_laplacian(P, tri):
    """Cotangent Laplacian L (positive semi-definite) and lumped (barycentric) mass vector."""
    from scipy.sparse import coo_matrix
    n = len(P)
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    rows, cols, vals = [], [], []
    for (i, j, k), (a, b, c) in (((0, 1, 2), (A, B, C)), ((1, 2, 0), (B, C, A)), ((2, 0, 1), (C, A, B))):
        # angle at vertex k (opposite edge i-j)
        u, v = a - c, b - c
        cr = np.linalg.norm(np.cross(u, v), axis=1)
        cot = np.einsum("ij,ij->i", u, v) / np.maximum(cr, 1e-30)
        w = 0.5 * cot
        ii, jj = tri[:, i], tri[:, j]
        rows += [ii, jj, ii, jj]
        cols += [jj, ii, ii, jj]
        vals += [-w, -w, w, w]
    L = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    area = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
    M = np.bincount(tri.ravel(), weights=np.repeat(area / 3.0, 3), minlength=n)
    return L, M, area


def _heat_geodesic(P, tri, src_mask, t_scale=1.0):
    """Heat-method distance on a triangle mesh. Returns (n,) distances (nan where unreachable)."""
    from scipy.sparse import diags
    from scipy.sparse.linalg import factorized
    n = len(P)
    used = np.zeros(n, bool)
    used[tri.ravel()] = True
    L, M, area = _cotan_laplacian(P, tri)
    E = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    h = float(np.mean(np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)))
    t = float(t_scale) * h * h
    reg = 1e-12 * max(float(M.max()), 1e-30)            # isolated / unused points keep the system non-singular
    Mr = M + np.where(used, 0.0, 1.0)
    solve_heat = factorized((diags(Mr) + t * L).tocsc())
    delta = np.where(src_mask, 1.0, 0.0)
    u = solve_heat(delta)
    # gradient of u per triangle, normalised
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    N = np.cross(B - A, C - A)
    dbl = np.linalg.norm(N, axis=1)
    Nn = N / np.maximum(dbl, 1e-30)[:, None]
    ua, ub, uc = u[tri[:, 0]], u[tri[:, 1]], u[tri[:, 2]]
    grad = (np.cross(Nn, C - B) * ua[:, None] + np.cross(Nn, A - C) * ub[:, None]
            + np.cross(Nn, B - A) * uc[:, None]) / np.maximum(dbl, 1e-30)[:, None]
    gl = np.linalg.norm(grad, axis=1, keepdims=True)
    X = -grad / np.where(gl > 1e-300, gl, 1.0)
    # integrated divergence at each vertex
    div = np.zeros(n)
    for (i, j, k), (a, b, c) in (((0, 1, 2), (A, B, C)), ((1, 2, 0), (B, C, A)), ((2, 0, 1), (C, A, B))):
        # contribution to vertex i from edges e1 = b - a, e2 = c - a with the cotangents of the opposite angles
        e1, e2 = b - a, c - a
        # cot at vertex k (between a-c and b-c) and at vertex j (between a-b and c-b)
        u1, v1 = a - c, b - c
        cot_k = np.einsum("ij,ij->i", u1, v1) / np.maximum(np.linalg.norm(np.cross(u1, v1), axis=1), 1e-30)
        u2, v2 = a - b, c - b
        cot_j = np.einsum("ij,ij->i", u2, v2) / np.maximum(np.linalg.norm(np.cross(u2, v2), axis=1), 1e-30)
        val = 0.5 * (cot_k * np.einsum("ij,ij->i", e1, X) + cot_j * np.einsum("ij,ij->i", e2, X))
        div += np.bincount(tri[:, i], weights=val, minlength=n)
    Lr = (L + diags(np.where(used, 0.0, 1.0)) + reg * diags(np.ones(n))).tocsc()
    phi = factorized(Lr)(div)
    phi = -phi if np.mean(phi[used & src_mask]) > np.mean(phi[used]) else phi
    return phi


def distance_along_geometry(geo, start_group="", method="geodesic", dist_attrib="dist", use_max=False, max_dist=1.0,
                            output_mask=False, mask_attrib="mask", mask_radius=1.0, ramp="0:1  1:0",
                            ramp_mode="linear", heat_time=1.0):
    """Returns (geometry, report)."""
    if method not in ALONG_METHODS:
        raise ValueError(f"Method must be one of {ALONG_METHODS}")
    n = geo.npoints
    if not n:
        return geo.copy(), {"points": 0}
    src = resolve(geo, POINT, start_group, empty_is_all=False)
    if not src.any():
        raise ValueError("Start Points: the group is empty -- name the points distances are measured from")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    D = np.asarray(_dijkstra(geo, np.nonzero(src)[0]), np.float64)
    unreach = ~np.isfinite(D)
    if method == "geodesic":
        tri = np.asarray(geo.triangles(), np.int64)
        if len(tri):
            phi = _heat_geodesic(P, tri, src, heat_time)
            # the Poisson solution is defined up to a constant per connected component: anchor each component at
            # its sources (mean of the sources = 0), keep Dijkstra for points no triangle reaches (curves, stray points)
            from scipy.sparse.csgraph import connected_components
            ncomp, lab = connected_components(_edge_graph(geo), directed=False)
            on_tri = np.zeros(n, bool)
            on_tri[tri.ravel()] = True
            G = D.copy()
            for c in range(ncomp):
                m = (lab == c) & on_tri
                s = m & src
                if not s.any():
                    continue
                G[m] = np.maximum(phi[m] - phi[s].mean(), 0.0)
            G[src] = 0.0
            D = np.where(on_tri & ~unreach, G, D)
    out = _write(geo, np.ones(n, bool), np.where(unreach, 0.0, D), dist_attrib, use_max, max_dist, output_mask,
                 mask_attrib, mask_radius, ramp, ramp_mode, unreachable=unreach)
    fin = ~unreach
    rep = {"points": n, "sources": int(src.sum()), "method": method, "unreachable": int(unreach.sum()),
           "max": float(D[fin].max()) if fin.any() else None}
    return out, rep
