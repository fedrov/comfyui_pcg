"""
Lot Subdivision (after SideFX Labs Lot Subdivision 2.0): cut polygons (city blocks) into lots.

Every selected polygon is cut in two by a straight line, each half again, Iterations times (1 pass -> 2 lots,
2 -> 4, ...); a lot smaller than Minimum Lot Size is not cut further. The cut:

    Alignment = bounding_box    across the longer side of the lot's bounding box in the plane's own axes (for a
                                horizontal block: world X / Z), so every cut is parallel to an axis
    Alignment = longest_edge    perpendicular to the lot's longest edge, so the cuts follow the block's shape
    Irregularity                0: through the middle; 1: anywhere in the middle 80 % (lots of varying size)

The polygons may be concave (a cut can then leave more than two pieces) but must be simple and planar; each is
cut in its own plane. Cluster Lots joins neighbouring lots (sharing an edge) of the same block until Number of
Clusters remain per block: the shared edges go, the outline stays.

Output: one polygon per lot, points shared along common edges (a neighbour's corner on an edge becomes a point of
that edge too, so there are no T-junctions). Prim attributes: `lot` (number within the output), `block` (the
source prim), `area`; the source's prim attributes are copied.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM
from .groups import resolve

ALIGNMENTS = ("bounding_box", "longest_edge")


def _area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def split_polygon(poly, o, d):
    """
    Cut the simple polygon poly (n, 2) by the line through o with direction d. -> list of polygons (same winding).
    Vertices on the line count as on its left. A line that misses the polygon returns [poly].
    """
    poly = np.asarray(poly, np.float64)
    n = len(poly)
    o = np.asarray(o, np.float64)
    d = np.asarray(d, np.float64)
    d = d / max(float(np.linalg.norm(d)), 1e-300)
    s = d[0] * (poly[:, 1] - o[1]) - d[1] * (poly[:, 0] - o[0])     # > 0: left of the line
    side = s >= 0
    if side.all() or not side.any():
        return [poly]
    V, cross, sd = [], [], []                                       # vertices with the crossings inserted
    for i in range(n):
        j = (i + 1) % n
        V.append(poly[i])
        cross.append(False)
        sd.append(bool(side[i]))
        if side[i] != side[j]:
            t = s[i] / (s[i] - s[j])
            V.append(poly[i] + (poly[j] - poly[i]) * t)
            cross.append(True)
            sd.append(None)
    V = np.asarray(V)
    m = len(V)
    ci = [i for i in range(m) if cross[i]]
    ci.sort(key=lambda i: float((V[i] - o) @ d))
    partner = {}
    for a, b in zip(ci[0::2], ci[1::2]):                            # inside the polygon between 1-2, 3-4, ...
        partner[a], partner[b] = b, a
    out = []
    for want in (True, False):
        used = set()
        for st in ci:
            if st in used or sd[(st + 1) % m] is not want:
                continue                                            # a chain on this side starts at st
            loop, c = [], st
            while c not in used:
                used.add(c)
                loop.append(V[c])
                k = (c + 1) % m
                while not cross[k]:
                    loop.append(V[k])
                    k = (k + 1) % m
                loop.append(V[k])                                   # the chain's end crossing; back along the line
                c = partner[k]
            if len(loop) >= 3:
                out.append(np.asarray(loop))
    return out


def _frame(P):
    """Plane of a polygon: centroid, u, v (in-plane axes), n. Horizontal polygons get u = X, v = +-Z."""
    c = P.mean(0)
    q = P - c
    n = np.cross(q, np.roll(q, -1, axis=0)).sum(0)                  # Newell
    ln = float(np.linalg.norm(n))
    if ln < 1e-20:
        raise ValueError("Lot Subdivision: a polygon has no area")
    n = n / ln
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    u = ref - n * (ref @ n)
    u = u / np.linalg.norm(u)
    return c, u, np.cross(n, u), n


def _cut_line(p, alignment, irregularity, rng):
    t = 0.5 + float(np.clip(irregularity, 0.0, 1.0)) * 0.8 * (rng.random() - 0.5)
    if alignment == "longest_edge":
        e = np.roll(p, -1, axis=0) - p
        k = int(np.argmax((e * e).sum(1)))
        a = e[k] / np.linalg.norm(e[k])
    else:
        ext = np.ptp(p, axis=0)
        a = np.array([1.0, 0.0]) if ext[0] >= ext[1] else np.array([0.0, 1.0])
    pr = p @ a
    lo, hi = float(pr.min()), float(pr.max())
    return a * (lo + (hi - lo) * t), np.array([-a[1], a[0]])        # through that point, across the axis a


def subdivide_2d(poly, alignment="bounding_box", min_lot_size=0.0, iterations=3, irregularity=0.0, rng=None):
    """Cut one polygon (n, 2) into lots. -> list of (k, 2) polygons, counter-clockwise like the input."""
    rng = rng or np.random.default_rng(0)
    lots = [np.asarray(poly, np.float64)]
    for _ in range(int(iterations)):
        new = []
        for p in lots:
            if abs(_area(p)) < float(min_lot_size) or len(p) < 3:
                new.append(p)
                continue
            o, d = _cut_line(p, alignment, irregularity, rng)
            new += [q for q in split_polygon(p, o, d) if abs(_area(q)) > 1e-12]
        lots = new
    return lots


def _weld(polys3, tol):
    """Polygons (list of (k, 3)) -> points (N, 3), faces (lists of point numbers) with shared points and no
    T-junctions: a point lying on another polygon's edge is inserted into that edge."""
    allp = np.concatenate(polys3)
    key = np.round(allp / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    P = allp[first]
    faces, k = [], 0
    for p in polys3:
        f = inv[k:k + len(p)].tolist()
        k += len(p)
        f = [a for a, b in zip(f, f[1:] + f[:1]) if a != b]
        faces.append(f)
    from scipy.spatial import cKDTree
    tree = cKDTree(P)
    out = []
    for f in faces:
        g = []
        for a, b in zip(f, f[1:] + f[:1]):
            g.append(a)
            ab = P[b] - P[a]
            L2 = float(ab @ ab)
            if L2 < tol * tol:
                continue
            # candidates: points within half the edge's length of its middle (a KD-tree, not every point)
            cand = np.asarray(tree.query_ball_point((P[a] + P[b]) * 0.5, 0.5 * np.sqrt(L2) + tol), np.int64)
            if len(cand) <= 2:
                continue
            t = ((P[cand] - P[a]) @ ab) / L2
            dist = np.linalg.norm(P[cand] - P[a] - np.outer(t, ab), axis=1)
            ok = (t > 1e-9) & (t < 1 - 1e-9) & (dist < tol) & (cand != a) & (cand != b)
            g += [int(i) for i in cand[ok][np.argsort(t[ok])]]
        out.append(g)
    return P, out


def _cluster(faces, P, areas, k, rng):
    """Join lots that share an edge until k remain. -> list of point loops, list of member lists."""
    n = len(faces)
    lab = list(range(n))
    edge = {}
    adj = [set() for _ in range(n)]
    for i, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            e = (min(a, b), max(a, b))
            if e in edge:
                adj[i].add(edge[e])
                adj[edge[e]].add(i)
            else:
                edge[e] = i

    def find(i):
        while lab[i] != i:
            lab[i] = lab[lab[i]]
            i = lab[i]
        return i
    area = {i: areas[i] for i in range(n)}
    nb = {i: set(adj[i]) for i in range(n)}
    count = n
    while count > max(1, int(k)):
        cand = [i for i in area if nb[i]]
        if not cand:
            break
        # the smallest cluster joins a random neighbour: clusters of even size, in a seeded random arrangement
        i = min(cand, key=lambda c: (area[c], c))
        j = sorted(nb[i])[int(rng.integers(len(nb[i])))]
        lab[j] = i
        area[i] += area.pop(j)
        nb[i] |= nb.pop(j)
        nb[i] -= {i, j}
        for m in nb[i]:
            nb[m].discard(j)
            nb[m].add(i)
        count -= 1
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    loops, members = [], []
    for g in groups.values():
        he = {}
        for i in g:
            f = faces[i]
            for a, b in zip(f, f[1:] + f[:1]):
                if (b, a) in he:
                    del he[(b, a)]                                  # an inner edge: both directions cancel
                else:
                    he[(a, b)] = True
        nxt = {}
        ok = True
        for a, b in he:
            if a in nxt:
                ok = False                                          # the outline touches itself at a point
            nxt[a] = b
        loop = []
        if ok and nxt:
            s0 = next(iter(nxt))
            c = s0
            while True:
                loop.append(c)
                c = nxt.get(c)
                if c is None or c == s0 or len(loop) > len(nxt):
                    break
            ok = c == s0 and len(loop) == len(nxt)                  # one closed outline (no hole)
        if ok:
            # drop points left in the middle of a straight side by the removed edges? keep: neighbours use them
            loops.append(loop)
            members.append(g)
        else:                                                       # a ring or a pinch: leave these lots apart
            for i in g:
                loops.append(list(faces[i]))
                members.append([i])
    return loops, members


def lot_subdivision(geo, group="", alignment="bounding_box", min_lot_size=0.0, iterations=3, seed=0,
                    irregularity=0.0, cluster_lots=False, clusters=4, cluster_seed=0):
    """Cut the polygons of geo (in group) into lots; see the module docstring. -> Geometry, report dict."""
    if alignment not in ALIGNMENTS:
        raise ValueError(f"Alignment must be one of {ALIGNMENTS}")
    if int(iterations) < 0 or int(iterations) > 16:
        raise ValueError("Iterations must be 0..16 (each pass doubles the lots)")
    sel = resolve(geo, PRIM, group)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    off = np.asarray(geo.prim_offset)
    closed = np.asarray(geo.prim_closed)
    span = max(float(np.ptp(P, axis=0).max()) if len(P) else 1.0, 1e-9)
    tol = span * 1e-7
    rng = np.random.default_rng(int(seed))
    crng = np.random.default_rng(int(cluster_seed) + 7919)
    polys, src, areas = [], [], []
    kept = []                                                       # prims passed through (not selected / not faces)
    for i in range(geo.nprims):
        n = int(off[i + 1] - off[i])
        if not sel[i] or not closed[i] or n < 3:
            kept.append(i)
            continue
        Q = P[np.asarray(geo.vertex_point)[off[i]:off[i + 1]]]
        c, u, v, _ = _frame(Q)
        p2 = np.stack([(Q - c) @ u, (Q - c) @ v], 1)
        lots = subdivide_2d(p2, alignment, min_lot_size, iterations, irregularity, rng)
        l3 = [c + np.outer(q[:, 0], u) + np.outer(q[:, 1], v) for q in lots]
        ar = [abs(_area(q)) for q in lots]
        if cluster_lots and len(lots) > max(1, int(clusters)):
            Pw, faces = _weld(l3, tol)
            loops, members = _cluster(faces, Pw, ar, clusters, crng)
            l3 = [Pw[np.asarray(lp)] for lp in loops]
            ar = [sum(ar[m] for m in g) for g in members]
        polys += l3
        areas += ar
        src += [i] * len(l3)
    if not polys:
        return geo.copy(), {"lots": 0, "blocks": 0}
    Pw, faces = _weld(polys, tol)
    out = Geometry.from_mesh(Pw, faces)
    src = np.asarray(src, np.int64)
    for name in geo.names(PRIM):
        a = np.asarray(geo.get(PRIM, name))[src]
        (out.set_string if a.dtype.kind == "U" else out.set)(PRIM, name, a)
    out.set(PRIM, "lot", np.arange(len(faces), dtype=np.int32))
    out.set(PRIM, "block", src.astype(np.int32))
    out.set(PRIM, "area", np.asarray(areas, np.float32))
    if kept:                                                        # prims outside the group pass through
        from .ops import merge, delete_prims
        out = merge(out, delete_prims(geo, np.isin(np.arange(geo.nprims), kept)))
    return out, {"lots": len(faces), "blocks": int(len(np.unique(src))),
                 "area_min": float(min(areas)), "area_max": float(max(areas))}
