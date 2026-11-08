"""
Convert Line SOP -- breaks primitives into lines.

Every edge becomes its own two-point polyline. Uses: wireframes, feeding a mesh to a spring/cloth solver (hence
restlength), a skeleton for PolyWire / Sweep, or just seeing the topology clearly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A shared edge is output only once
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
An interior edge is shared by two primitives. Emitting segments primitive by primitive, corner by corner would produce
every interior edge twice -- the wireframe looks the same, but a solver gets two overlapping springs and the stiffness silently doubles. So edges are deduplicated by **point pair**.

After deduplication "which primitive this edge belongs to" is no longer unique; prim attributes are taken from **the first primitive that uses it**
(name / material and the like carry over fine); vertex attributes come from the corresponding half-edge, which is exact.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Connect Path
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When on, instead of a pile of two-point segments the edges are **chained into the longest possible polylines**: walking continues through
points of degree 2 and breaks at points whose degree isn't 2. The benefit is that downstream Resample / Carve / Sweep treat the result
as curves, whereas a pile of two-point segments is processed piece by piece in those nodes, with completely different results.

Start from "endpoints" (degree != 2) first and handle the remaining closed loops afterwards; the order can't be reversed -- starting from
a point on a loop would cut an open chain that should be whole into two pieces in the middle.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve
from .ops import delete_points


def _edges(geo, sel):
    """
    All edges on the selected primitives, deduplicated by point pair.
    Returns (point pairs (E,2), source corner of each edge (E,), source prim of each edge (E,)).
    """
    if geo.nvertices == 0:
        z = np.zeros(0, np.int64)
        return np.zeros((0, 2), np.int64), z, z.copy()
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    corner = np.arange(geo.nvertices, dtype=np.int64)
    pr = geo.vertex_prim().astype(np.int64)
    local = corner - np.repeat(starts, sizes)
    nxt = np.repeat(starts, sizes) + (local + 1) % np.repeat(sizes, sizes)
    # The last corner of an open polyline has no "next edge"; wrapping around would create a closing edge that doesn't exist
    keep = sel[pr] & ~((local == np.repeat(sizes, sizes) - 1)
                       & ~geo.prim_closed[pr])
    corner = corner[keep]
    if not len(corner):
        z = np.zeros(0, np.int64)
        return np.zeros((0, 2), np.int64), z, z.copy()
    a = geo.vertex_point[corner].astype(np.int64)
    b = geo.vertex_point[nxt[keep]].astype(np.int64)
    ok = a != b
    corner, a, b = corner[ok], a[ok], b[ok]
    key = np.minimum(a, b) * np.int64(geo.npoints + 1) + np.maximum(a, b)
    _, first = np.unique(key, return_index=True)
    first = np.sort(first)                       # in order of first occurrence, not key order
    return (np.stack([a[first], b[first]], 1), corner[first],
            pr[keep][ok][first])


def _paths(pairs, npoints, close_loops):
    """Chains edges into the longest possible polylines. Returns [(point number sequence, closed?), ...]."""
    n = len(pairs)
    if not n:
        return []
    deg = np.bincount(pairs.reshape(-1), minlength=npoints)
    inc = [[] for _ in range(npoints)]
    for e, (a, b) in enumerate(pairs.tolist()):
        inc[a].append(e)
        inc[b].append(e)
    used = np.zeros(n, bool)

    def walk(start_pt, e0):
        pts = [start_pt]
        cur, node = e0, start_pt
        while not used[cur]:
            used[cur] = True
            a, b = pairs[cur]
            node = int(b) if int(a) == node else int(a)
            pts.append(node)
            nxt = [k for k in inc[node] if not used[k]]
            if len(nxt) != 1 or deg[node] != 2:
                break
            cur = nxt[0]
        return pts

    out = []
    # Open chains first: start from points whose degree isn't 2. Doing loops first would cut an open chain in the middle
    for p in np.nonzero(deg != 2)[0]:
        for e in inc[int(p)]:
            if not used[e]:
                out.append((walk(int(p), e), False))
    for e in range(n):                           # what's left must be isolated closed loops
        if not used[e]:
            pts = walk(int(pairs[e][0]), e)
            closed = len(pts) > 3 and pts[0] == pts[-1]
            out.append((pts[:-1] if (closed and close_loops) else pts,
                        bool(closed and close_loops)))
    return out


def convert_line(geo, group="", keep_group_order=True, connect_path=False,
                 close_isolated_loops=False, remove_unused_points=False,
                 length_attrib="restlength"):
    """
    Breaks the selected primitives into lines. No point moves (unless remove_unused_points), so point attributes are kept as is.

    With keep_group_order=False the output is sorted by point number instead of the order edges appear in the geometry --
    use it when you want a stable numbering independent of the upstream traversal order.
    """
    if geo is None:
        return Geometry()
    sel = resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()
    pairs, corners, src_prim = _edges(geo, sel)
    if not len(pairs):
        return Geometry()
    if not keep_group_order:
        order = np.lexsort((pairs[:, 1], pairs[:, 0]))
        pairs, corners, src_prim = pairs[order], corners[order], src_prim[order]

    g = Geometry()
    g._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        g.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        g.set_group(POINT, k, v)

    if connect_path:
        paths = _paths(pairs, geo.npoints, close_isolated_loops)
        vp = np.concatenate([np.asarray(p, np.int32) for p, _ in paths])
        sz = np.array([len(p) for p, _ in paths], np.int64)
        closed = np.array([c for _, c in paths], bool)
        g.set_topology(vp, np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                       closed)
        # Once chained, one polyline spans several original edges; vertex / prim attributes have no unique source,
        # so they are dropped -- forcing the first edge's value would make downstream think it means something.
    else:
        g.set_topology(pairs.reshape(-1).astype(np.int32),
                       (np.arange(len(pairs) + 1, dtype=np.int32) * 2),
                       np.zeros(len(pairs), bool))
        nxt = geo.next_corner()
        cpair = np.stack([corners, nxt[corners]], 1).reshape(-1)
        for k, v in geo.attribs[VERTEX].items():
            g.set(VERTEX, k, v[cpair], owned=True)
        for k, v in geo.groups[VERTEX].items():
            g.set_group(VERTEX, k, v[cpair])
        for k, v in geo.attribs[PRIM].items():
            g.set(PRIM, k, v[src_prim], owned=True)
        for k, v in geo.groups[PRIM].items():
            g.set_group(PRIM, k, v[src_prim])
    g.attribs[DETAIL] = dict(geo.attribs[DETAIL])

    nm = str(length_attrib).strip()
    if nm:
        P = g.get(POINT, "P")
        if P is not None:
            seg = np.linalg.norm(np.diff(P[g.vertex_point].astype(np.float64),
                                         axis=0), axis=1)
            # Segments inside each prim: only counts when adjacent corners belong to the same prim
            pr = g.vertex_prim()
            same = pr[1:] == pr[:-1]
            L = np.bincount(pr[1:][same], weights=seg[same],
                            minlength=g.nprims)
            if g.nprims and g.prim_closed.any():   # closed loops also need their closing segment
                ci = np.nonzero(g.prim_closed)[0]
                first = g.vertex_point[g.prim_offset[:-1][ci]]
                last = g.vertex_point[g.prim_offset[1:][ci] - 1]
                L[ci] += np.linalg.norm(
                    P[first].astype(np.float64) - P[last].astype(np.float64),
                    axis=1)
            g.set(PRIM, nm, L[:, None].astype(np.float32), owned=True)

    if remove_unused_points:
        used = np.zeros(g.npoints, bool)
        used[g.vertex_point] = True
        if not used.all():
            g = delete_points(g, used)
    return g
