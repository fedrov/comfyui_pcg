"""
PolyFill -- fill holes. Matches Houdini's PolyFill SOP.

Clip, Blast and Delete all leave openings, and almost every later step wants closed geometry: volume needs it closed,
booleans need it closed, Voronoi fragments without their openings filled are a pile of paper sheets. So this piece was always missing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The direction of the boundary loop decides the direction of the fill face -- and it is **reversed**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Boundary half-edges run along **the winding of the existing faces**. For the fill face to agree with the neighbouring normals, the vertex loop must be strung
**reversed**. Getting this backwards does not raise and the face count is right, only the filled patch's normals point inward -- a black hole when rendered,
the opposite sign when computing volume. So the test directly checks "after filling, the volume is positive and equals the analytic value".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Three fill methods
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ngon       cap with one polygon. No points added, the first choice for planar holes
    fan        add a point at the hole's center and fan-triangulate. Use for non-planar holes, where ngon would twist
    triangles  ear-clip into triangles, no points added

pcg98 adds the three quad modes from Houdini's Fill Mode:

    quad_fan   Quadrilateral Fan: add a center point, one quad per two edges (with an odd edge count one triangle remains at the end)
    quads      Quadrilaterals: no points added, fold the loop into two chains and connect them cell by cell (with an odd count one end is a triangle).
               Like ngon, only suitable for convex, nearly flat holes
    quad_grid  Quadrilateral Grid: treat the loop as the four sides of a quad patch and fill the inside with an a x b quad grid by Coons
               interpolation. The four corners are chosen automatically (the split with the largest sum of turning angles); with an odd edge count no grid can be laid,
               falls back to quads

When the hole is not flat, the ngon face is itself twisted (non-planar), which shows when triangulated downstream;
fan adds a center point and behaves, at the cost of one extra point. The default is ngon, because the most common holes (from cutting)
lie in a plane anyway.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .topology import topology

MODES = ("ngon", "fan", "triangles", "quad_fan", "quads", "quad_grid")


def boundary_loops(geo):
    """
    List of boundary loops, each a sequence of **point numbers** (following the boundary half-edge direction).

    Boundary half-edge = an edge used by only one face. Its successor is "the boundary half-edge starting at this one's end" --
    on a manifold boundary each point has exactly one in and one out, so this successor is unique. On a non-manifold boundary (several loops
    hanging on one point) one is picked arbitrarily without raising, but such geometry has other problems anyway.
    """
    t = topology(geo)
    if geo.nvertices == 0 or t.nedges == 0:
        return []
    he_ok = t.he_valid & (t.he_edge >= 0)
    bnd = np.nonzero(he_ok & t.boundary[np.maximum(t.he_edge, 0)])[0]
    if not len(bnd):
        return []
    vp = geo.vertex_point
    nxt = geo.next_corner().astype(np.int64)
    start = vp[bnd].astype(np.int64)
    end = vp[nxt[bnd]].astype(np.int64)

    # start -> half-edge. When a point has several, keep the last one (non-manifold boundary, arbitrary pick)
    by_start = np.full(geo.npoints, -1, np.int64)
    by_start[start] = np.arange(len(bnd))

    loops, used = [], np.zeros(len(bnd), bool)
    for i in range(len(bnd)):
        if used[i]:
            continue
        loop, k = [], i
        while k >= 0 and not used[k]:
            used[k] = True
            loop.append(int(start[k]))
            k = int(by_start[end[k]])
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _plane_of(P, idx):
    """(normal, origin, max deviation). Decides whether a hole is flat."""
    Q = P[idx]
    o = Q.mean(0)
    _, _, Vt = np.linalg.svd(Q - o, full_matrices=False)
    n = Vt[2]
    return n, o, float(np.abs((Q - o) @ n).max())


def fill(geo, mode="ngon", max_sides=0, output_group="",
         planar_tol=-1.0, loops=None):
    """
    Fill all boundary loops.

    With max_sides > 0 only holes with at most that many edges are filled -- the common need is "fill small holes, do not
    seal the whole opening of the model". With planar_tol >= 0 only sufficiently flat holes are filled.

    When loops is given only these loops are filled (a list of point-number lists), without searching -- Voronoi fills after each cut
    and only wants to fill the loops lying on that cut plane, leaving other openings alone.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if loops is None:
        loops = boundary_loops(geo)
    if not loops:
        return geo.copy()
    P = geo.get(POINT, "P").astype(np.float64)
    ms = int(max_sides)
    tol = float(planar_tol)

    keep = []
    for lp in loops:
        if ms > 0 and len(lp) > ms:
            continue
        if tol >= 0:
            if _plane_of(P, np.asarray(lp, np.int64))[2] > tol:
                continue
        keep.append(lp)
    if not keep:
        return geo.copy()

    g = geo.copy()
    new_pts, new_ring, used = [], [], []     # newly added points, which loop each belongs to, the loops themselves
    faces = []
    npt = geo.npoints
    for lp in keep:
        idx = np.asarray(lp, np.int64)
        # **Reversed**: boundary half-edges follow the original faces' winding; the fill face must be strung the opposite way to face outward
        rev = idx[::-1]
        if mode == "ngon":
            faces.append(rev)
        elif mode == "fan":
            c = npt + len(new_pts)
            new_pts.append(P[idx].mean(0))
            new_ring.append(len(used))
            faces += [np.array([c, rev[i], rev[(i + 1) % len(rev)]], np.int64)
                      for i in range(len(rev))]
        elif mode == "triangles":              # ear clipping
            faces += _earcut(P, rev)
        elif mode == "quad_fan":
            c = npt + len(new_pts)
            new_pts.append(P[idx].mean(0))
            new_ring.append(len(used))
            n = len(rev)
            faces += [np.array([c, rev[i], rev[i + 1], rev[(i + 2) % n]], np.int64)
                      for i in range(0, n - 1, 2)]
            if n % 2:
                faces.append(np.array([c, rev[n - 1], rev[0]], np.int64))
        elif mode == "quads" or len(rev) % 2:      # an odd edge count cannot form a grid
            faces += _quad_strip(rev)
        else:                                  # quad_grid
            pts, fs = _quad_grid(P, rev, npt + len(new_pts))
            new_pts += list(pts)
            new_ring += [len(used)] * len(pts)
            faces += fs
        used.append(lp)

    if new_pts:
        add = np.asarray(new_pts, np.float64)
        # Change the point count first, then write attributes -- Geometry.set validates row counts, the wrong order raises immediately
        g._npoints = geo.npoints + len(add)
        rings = [np.asarray(used[r], np.int64) for r in new_ring]   # the loop each new point belongs to
        for k, v in geo.attribs[POINT].items():
            if is_string(v):
                pad = np.asarray([np.asarray(v)[r[0], 0] for r in rings]
                                 ).reshape(-1, 1)
                g.set(POINT, k, np.concatenate([np.asarray(v), pad], 0),
                      owned=True)
                continue
            # New points' attributes take the mean of the loop around the hole -- far more sensible than zero. P is given separately:
            # the center point is the loop's centroid, the points inside quad_grid are interpolated positions
            pad = add if k == "P" else np.stack([v[r].astype(np.float64).mean(0) for r in rings], 0)
            g.set(POINT, k, np.concatenate([v, pad.astype(v.dtype)], 0),
                  owned=True)
        for k, v in geo.groups[POINT].items():
            g.set_group(POINT, k, np.concatenate(
                [v, np.zeros(len(add), bool)]))

    sizes = np.array([len(f) for f in faces], np.int64)
    flat = np.concatenate(faces).astype(np.int32)
    _old_nv, old_nf = geo.nvertices, geo.nprims
    g.set_topology(
        np.concatenate([geo.vertex_point, flat]).astype(np.int32),
        np.concatenate([geo.prim_offset,
                        geo.nvertices + np.cumsum(sizes)]).astype(np.int32),
        np.concatenate([geo.prim_closed, np.ones(len(faces), bool)]),
        np.concatenate([geo.prim_type,
                        np.full(len(faces), PRIM_POLY, geo.prim_type.dtype)]))
    for k, v in geo.attribs[VERTEX].items():
        pad = (np.zeros((int(sizes.sum()), v.shape[1]), v.dtype)
               if not is_string(v)
               else np.full((int(sizes.sum()), 1), "", dtype=v.dtype))
        g.set(VERTEX, k, np.concatenate([v, pad], 0), owned=True)
    for k, v in geo.groups[VERTEX].items():
        g.set_group(VERTEX, k, np.concatenate(
            [v, np.zeros(int(sizes.sum()), bool)]))
    for k, v in geo.attribs[PRIM].items():
        pad = (np.zeros((len(faces), v.shape[1]), v.dtype) if not is_string(v)
               else np.full((len(faces), 1), "", dtype=v.dtype))
        g.set(PRIM, k, np.concatenate([v, pad], 0), owned=True)
    for k, v in geo.groups[PRIM].items():
        g.set_group(PRIM, k, np.concatenate([v, np.zeros(len(faces), bool)]))
    if str(output_group).strip():
        m = np.zeros(old_nf + len(faces), bool)
        m[old_nf:] = True
        g.set_group(PRIM, str(output_group).strip(), m)
    g.prim_data = dict(geo.prim_data)
    g.edge_groups = dict(geo.edge_groups)
    g.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return g


def _earcut(P, idx):
    """Ear-clip a loop into triangles. Borrows divide's implementation, so concave holes are cut correctly too."""
    from .divide import _ear_clip, _plane_basis
    tris = _ear_clip(_plane_basis(P[idx]))       # _plane_basis already gives (n,2)
    return [idx[np.asarray(t, np.int64)] for t in tris]


def _quad_strip(rev):
    """No points added: fold the loop into two chains and connect them cell by cell. With odd n one triangle remains at the fold end."""
    n = len(rev)
    out = [np.array([rev[i], rev[i + 1], rev[n - 2 - i], rev[n - 1 - i]], np.int64)
           for i in range((n - 2) // 2)]
    if n % 2:
        m = (n - 1) // 2
        out.append(np.array([rev[m - 1], rev[m], rev[m + 1]], np.int64))
    return out


def _quad_grid(P, rev, first_new):
    """
    The loop (n even; a loop has at least 3 points, so even means >= 4) is treated as the boundary of a quad patch: the four sides have a, b, a, b points (2a + 2b = n).
    Returns (positions of the new interior points [(a-1)(b-1) of them], list of quads); new points are numbered from first_new.

    How the four corners are chosen: among all (a, start) splits, take the one with the **largest sum of turning angles** at the four corners -- the four corners of a square hole
    are its four corners; for a round hole any split is about the same, and the one chosen has a ~ b (ties take the earlier one, trying a outward from n/4).

    Interior points are interpolated as a Coons patch: linear blend of opposite sides minus the bilinear term of the four corners. When the boundary is a planar rectangle
    this gives exactly evenly spaced grid points.
    """
    n = len(rev)
    X = P[rev]
    d0 = X - np.roll(X, 1, 0)
    d1 = np.roll(X, -1, 0) - X
    cosang = (d0 * d1).sum(1) / np.maximum(np.linalg.norm(d0, axis=1) * np.linalg.norm(d1, axis=1), 1e-30)
    turn = np.arccos(np.clip(cosang, -1.0, 1.0))         # turning angle at each point (0 = going straight)
    half = n // 2
    best = None
    for a in sorted(range(1, half), key=lambda a: (abs(a - half / 2.0), a)):
        b = half - a
        for st in range(n):
            score = turn[st] + turn[(st + a) % n] + turn[(st + a + b) % n] + turn[(st + 2 * a + b) % n]
            if best is None or score > best[0] + 1e-9:
                best = (score, a, b, st)
    _, a, b, st = best
    ring = np.roll(np.arange(n), -st)                    # ring[0] is the first corner
    # Grid point (i, j), i = 0..a along the first side, j = 0..b along the second side; points on the boundary are loop points
    grid = np.full((a + 1, b + 1), -1, np.int64)
    grid[:, 0] = ring[0:a + 1]
    grid[a, :] = ring[a:a + b + 1]
    grid[::-1, b] = ring[a + b:2 * a + b + 1]
    grid[0, ::-1] = np.concatenate([ring[2 * a + b:], ring[:1]])
    pts = []
    for i in range(1, a):
        for j in range(1, b):
            u, v = i / a, j / b
            q = ((1 - v) * X[grid[i, 0]] + v * X[grid[i, b]] + (1 - u) * X[grid[0, j]] + u * X[grid[a, j]]
                 - ((1 - u) * (1 - v) * X[grid[0, 0]] + u * (1 - v) * X[grid[a, 0]]
                    + (1 - u) * v * X[grid[0, b]] + u * v * X[grid[a, b]]))
            grid[i, j] = n + len(pts)                    # placeholder "in-loop number n + k" first
            pts.append(q)
    idx = np.concatenate([np.asarray(rev, np.int64), first_new + np.arange(len(pts), dtype=np.int64)])
    faces = [idx[[grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]]]
             for i in range(a) for j in range(b)]
    return pts, faces
