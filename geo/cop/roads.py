"""
Road network on a height field: least-cost paths that keep to a drivable grade, joined into one network.

What Project Pegasus does with its PE_heightfield_paths asset and what a road engineer does on a contour map: a road
climbs a hillside at a bearable grade, not straight up it -- so the cost of a step grows with its grade, and a step
steeper than Max Grade costs so much that the path takes the long way round (switchbacks appear by themselves).

  network   Prim's algorithm on path costs: start from the first destination; at each round run Dijkstra from the
            whole network built so far (every road cell is a source) and join the destination that is cheapest to
            reach. Roads therefore branch off roads, like a real network, instead of every destination getting its
            own road to every other.
  grid      the height field taken every Step pixels; every grid step up to 4 cells (48 directions), so a road can
            hold a low grade across a steep slope (1:4) instead of only 0 / 45 / 90 degrees.
  cost      length x (1 + Grade Weight x (grade / Max Grade)^2); above Max Grade x 25 more; cells where the Avoid
            Layer is high cost x (1 + Avoid Cost x value); the sea (Block Layer > 0.5) is closed; along roads
            already built x Reuse (< 1: new roads follow old ones where that is nearly as good).
  output    one polyline per joined segment, resampled every Spacing world units and relaxed (no point more than 0.6
            grid cells off the planned path, so switchbacks survive), on the
            terrain (P.y from the height field); point attribute `road_h` = the height smoothed along the road
            (the bed to cut it into), prim attributes `road` (index) and `served` (the destination it joins).

Coordinates are those of COP HeightField to Mesh with Center on (x right, z = -v), so the curves lie on that mesh
and COP Rasterize Curves (plane xz, mapping world, the same World Size) draws them back onto the image.
"""
import numpy as np

from .core import DEFAULT_LAYER
from .pixel import getn

def _moves(r=4):
    """All primitive grid steps up to r cells (gcd 1): on a slope 4x steeper than Max Grade a road has to run at
    1:4 across it, a direction 8 or 16 neighbours do not have -- with them it climbs straight up in steep pieces
    between level ones."""
    from math import gcd
    return [(di, dj) for di in range(-r, r + 1) for dj in range(-r, r + 1)
            if (di or dj) and gcd(abs(di), abs(dj)) == 1]


_MOVES = _moves(4)


def _sample(h, x, y):
    """Bilinear sample of h (H, W) at pixel-index coordinates x (column), y (row)."""
    H, W = h.shape
    x = np.clip(x, 0, W - 1.000001)
    y = np.clip(y, 0, H - 1.000001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    return (h[y0, x0] * (1 - fx) * (1 - fy) + h[y0, x0 + 1] * fx * (1 - fy)
            + h[y0 + 1, x0] * (1 - fx) * fy + h[y0 + 1, x0 + 1] * fx * fy)


def _edges(hg, cell, max_grade, grade_weight, avoid, avoid_cost, block):
    """
    All directed edges of the grid graph: (src, dst, cost) with cost before the road-reuse factor. A step longer than
    one cell is costed cell by cell along its line (the ground between its ends, bilinear): judged by its ends only,
    a 4-cell step would hop over a ridge or a gully at a fine average grade.
    """
    R, C = hg.shape
    idx = np.arange(R * C).reshape(R, C)
    srcs, dsts, costs = [], [], []
    for di, dj in _MOVES:
        i0, i1 = max(0, -di), R - max(0, di)
        j0, j1 = max(0, -dj), C - max(0, dj)
        a = idx[i0:i1, j0:j1].ravel()
        b = idx[i0 + di:i1 + di, j0 + dj:j1 + dj].ravel()
        ia, ja = (a // C).astype(np.float64), (a % C).astype(np.float64)
        n = max(abs(di), abs(dj))
        Ls = cell * float(np.hypot(di, dj)) / n
        c = np.zeros(len(a))
        av = np.zeros(len(a))
        ok = np.ones(len(a), bool)
        h_prev = hg.ravel()[a]
        for k in range(1, n + 1):
            t = k / n
            ri, cj = ia + t * di, ja + t * dj
            h_k = _sample(hg, cj, ri)
            g = np.abs(h_k - h_prev) / Ls
            ck = Ls * (1.0 + grade_weight * (g / max_grade) ** 2)
            c += np.where(g > max_grade, ck * 25.0, ck)
            h_prev = h_k
            near = (np.rint(ri).astype(int) * C + np.rint(cj).astype(int))
            if avoid is not None:
                av += avoid.ravel()[near]
            if block is not None:
                ok &= block.ravel()[near] < 0.5
        if avoid is not None:
            c = c * (1.0 + avoid_cost * (av / n))
        if block is not None:
            ok &= block.ravel()[a] < 0.5
        srcs.append(a[ok])
        dsts.append(b[ok])
        costs.append(c[ok])
    return np.concatenate(srcs), np.concatenate(dsts), np.concatenate(costs)


def _resample(p, spacing):
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 0:
        return p[:1]
    n = max(2, int(np.ceil(s[-1] / spacing)) + 1)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, p[:, k]) for k in range(p.shape[1])], -1)


def road_network(img, points, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0, step=4, max_grade=0.12,
                 grade_weight=4.0, avoid_layer="", avoid_cost=4.0, block_layer="", reuse=0.4, smooth=2,
                 spacing=4.0, profile=40.0):
    """-> (Geometry of polylines, report dict). See the module docstring."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra
    from ..core import Geometry, POINT, PRIM

    if img is None or points is None or points.npoints < 2:
        return Geometry(), {"roads": 0, "joined": 0, "unreachable": 0}
    W, H = img.xres, img.yres
    texel = float(world_size) / W
    hv = getn(img, layer)[:, :, 0] * float(strength)
    st = max(1, int(step))
    ii = np.arange(0, H, st)
    jj = np.arange(0, W, st)
    hg = hv[np.ix_(ii, jj)]
    R, C = hg.shape
    cell = texel * st

    def grid_layer(name):
        name = str(name).strip()
        if not name:
            return None
        return np.clip(getn(img, name)[:, :, 0][np.ix_(ii, jj)], 0.0, None)
    avoid, block = grid_layer(avoid_layer), grid_layer(block_layer)
    src, dst, cost0 = _edges(hg, cell, float(max_grade), float(grade_weight), avoid, float(avoid_cost), block)

    # destinations -> nearest grid node (pixel centre convention of HeightField to Mesh, Center on)
    P = np.asarray(points.get(POINT, "P"), np.float64)
    col = (P[:, 0] + W * texel * 0.5) / texel - 0.5
    row = (H * texel * 0.5 - P[:, 2]) / texel - 0.5
    gi = np.clip(np.rint(row / st).astype(int), 0, R - 1)
    gj = np.clip(np.rint(col / st).astype(int), 0, C - 1)
    node = gi * C + gj
    node, first = np.unique(node, return_index=True)
    node = node[np.argsort(first)]                     # keep the input order (the first point starts the network)

    on_road = np.zeros(R * C, bool)
    on_road[node[0]] = True
    joined, segments, served = {int(node[0])}, [], []
    unreachable = 0
    todo = [int(n) for n in node[1:]]
    while todo:
        f = np.where(on_road[src] & on_road[dst], float(reuse), 1.0)
        G = csr_matrix((cost0 * f, (src, dst)), shape=(R * C, R * C))
        sources = np.nonzero(on_road)[0]
        d, pred, _ = dijkstra(G, indices=sources, min_only=True, return_predecessors=True)
        dd = np.array([d[n] for n in todo])
        lost = ~np.isfinite(dd)
        if lost.any():                                 # cut off (another island, enclosed by the Block Layer)
            unreachable += int(lost.sum())
            todo = [t for t, l_ in zip(todo, lost) if not l_]
            dd = dd[~lost]
            if not todo:
                break
        k = int(np.argmin(dd))
        n = todo.pop(k)
        path = [n]
        while not on_road[path[-1]]:
            p_ = pred[path[-1]]
            if p_ < 0:
                break
            path.append(int(p_))
        on_road[path] = True
        joined.add(n)
        segments.append(path[::-1])                     # from the network out to the destination
        served.append(n)

    # polylines in world space
    pts, prims, roads, srv = [], [], [], []
    base = 0
    for r_, (path, n) in enumerate(zip(segments, served)):
        pr = np.array([[(p % C) * st, (p // C) * st] for p in path], np.float64)    # (col, row) pixel indices
        pr = _resample(pr, max(spacing / texel, 0.25))
        # relax: grid paths wobble cell to cell; a few Laplacian passes (ends fixed: they sit on the network and on
        # the destination) straighten them into the sweeping curves a road is built as. No point moves more than
        # 0.6 grid cells from the planned path: unbounded, the passes pull a stack of switchbacks into one straight
        # cut up the slope (a 40 % hillside planned at 10 % came out at 37 %)
        ref = pr.copy()
        lim = 0.6 * st
        for _ in range(int(smooth) * 12):
            if len(pr) < 3:
                break
            pr[1:-1] = 0.5 * pr[1:-1] + 0.25 * (pr[:-2] + pr[2:])
            off = pr - ref
            n_ = np.linalg.norm(off, axis=1, keepdims=True)
            pr = ref + off * np.minimum(1.0, lim / np.maximum(n_, 1e-12))
        # even spacing again (relaxing bunches the points in the bends; the bed is averaged by distance)
        pr = _resample(pr, max(spacing / texel, 0.25))
        h = _sample(hv, pr[:, 0], pr[:, 1])
        # the bed: the ground smoothed along the road over ~Profile world units (cuts the bumps, fills the dips)
        k = max(1, int(round(float(profile) / max(spacing, 1e-6) / 2)))
        if len(h) > 2 * k + 1:
            pad = np.pad(h, k, mode="edge")
            ker = np.ones(2 * k + 1) / (2 * k + 1)
            hb = np.convolve(pad, ker, mode="valid")
        else:
            hb = h.copy()
        X = (pr[:, 0] + 0.5) * texel - W * texel * 0.5
        Z = H * texel * 0.5 - (pr[:, 1] + 0.5) * texel
        pts.append(np.stack([X, hb, Z], -1))
        roads.append(np.full(len(pr), r_))
        srv.append(np.full(len(pr), int(np.nonzero(node == n)[0][0])))
        prims.append(np.arange(base, base + len(pr)))
        base += len(pr)
    if not pts:
        return Geometry(), {"roads": 0, "joined": 1, "unreachable": unreachable}
    allp = np.concatenate(pts)
    g = Geometry.from_mesh(allp.astype(np.float32), [list(p) for p in prims], closed=False)   # open polylines
    g.set(POINT, "road_h", allp[:, 1].astype(np.float32))
    g.set(PRIM, "road", np.arange(len(prims), dtype=np.int32))
    g.set(PRIM, "served", np.array([int(s[0]) for s in srv], np.int32))
    length = float(sum(np.linalg.norm(np.diff(p, axis=0), axis=1).sum() for p in pts))
    return g, {"roads": len(prims), "joined": len(joined), "unreachable": unreachable,
               "length": length, "grid": [int(C), int(R)], "cell": cell}

