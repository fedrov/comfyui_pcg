"""
Paths and networks (pcg67, batch B): Find Shortest Path, Group Find Path, Curve Intersect,
Connect Adjacent Pieces.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shortest path: the mesh's edges are the graph
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Graph = the deduplicated undirected edges from topology (both face edges and polyline edges count). Edge weight:

    w = base x (1 + Cost Weight . average of the cost attribute at both ends) x (1 + Slope Weight . |slope|)

  base        edge length with use_length, otherwise 1 per edge (counting "hops")
  cost attrib a scalar on points, e.g. moisture or vegetation density on terrain -- the path avoids it
  slope       |the edge's component along Up| / edge length; when pathfinding on terrain it makes the path follow contours

Weights must be positive (a precondition of Dijkstra): edges with a multiplier <= 0 raise an error rather than being silently clamped -- a negative
cost attribute usually means upstream normalization went wrong, and clamping to 0 would let the path cross places it should avoid.

Dijkstra is a pure-Python heap (the plugin does not depend on scipy). The adjacency list is converted to Python lists before entering the loop
-- fetching numpy scalars one by one in the loop is several times slower. Stops early once all targets are popped. A 256^2 terrain
grid (65k points) takes under a second.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Curve intersection: grid bucketing + exact segment tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Segments go into spatial's grid by their (tolerance-padded) bounding boxes, pairs within the same cell are matched, deduplicated, then each pair
gets an exact test -- planar modes (xz / xy / yz) use the parametric solution of 2D segment intersection, 3d mode uses the
closest-point distance between the two segments <= tolerance. Intersections on an existing vertex (parameter within 1e-9 of an end) merge into that vertex
instead of inserting zero-length segments.
"""
from __future__ import annotations

import heapq
import math
import re

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, PRIM_POLY
from .groups import resolve
from .topology import topology
from . import curveframe as _cf
from . import spatial as _sp

# pcg100 appends Houdini Output Paths' other three modes at the end (nearest_end = From each start to any end,
# each_pair = From each start to each end; sequence is ours)
PATH_MODES = ("nearest_end", "each_pair", "sequence", "any_to_any", "any_start_to_each_end",
              "corresponding")
PATH_OUTPUTS = ("paths", "merge", "group")
# pcg100 appends start_end_pairs at the end (Houdini's Paths between Start/End Pairs in Base Group)
GFP_MODES = ("shortest_path", "boundary_loop", "start_end_pairs")
INTERSECT_PLANES = ("3d", "xz", "xy", "yz")
# The last two were added in pcg100 after Houdini's Method: cut (cut apart, left and right groups pick odd/even pieces separately) / extract (take intersection points)
INTERSECT_OUTPUTS = ("points", "split", "cut", "extract")
INTERSECT_KEEP = ("keep_all", "keep_odd", "keep_even", "keep_none")
INTERSECT_AFFECT = ("left", "right", "both")
CONNECT_MODES = ("points", "piece_centroids", "piece_points")


# ═══════════════════════════════════════════════════════════ graph
def edge_weights(geo, use_length=True, cost_attribute="", cost_weight=1.0,
                 slope_weight=0.0, up=(0, 1, 0)):
    """(E,2) edges, (E,) weights."""
    t = topology(geo)
    E = t.edge_points.astype(np.int64)
    if not len(E):
        return E, np.zeros(0)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    d = P[E[:, 1]] - P[E[:, 0]]
    ln = np.linalg.norm(d, axis=1)
    w = ln.copy() if use_length else np.ones(len(E))
    name = str(cost_attribute).strip()
    if name:
        a = geo.get(POINT, name)
        if a is None:
            raise KeyError(f"No cost attribute '{name}' on points")
        c = np.asarray(a, np.float64)[:, 0]
        w = w * (1.0 + float(cost_weight) * 0.5 * (c[E[:, 0]] + c[E[:, 1]]))
    if float(slope_weight) != 0.0:
        u = np.asarray(up, np.float64)
        u = u / max(np.linalg.norm(u), 1e-12)
        sl = np.abs(d @ u) / np.where(ln > 0, ln, 1.0)
        w = w * (1.0 + float(slope_weight) * sl)
    if not np.all(w > 0):
        bad = int((w <= 0).sum())
        raise ValueError(f"{bad} edges have cost <= 0 -- shortest path requires positive costs. "
                         "Check the value range of the cost attribute (negative?) or the sign of Cost Weight")
    return E, w


def _directed_graph(geo, E, w, prim_cost_attribute="", point_cost_attribute="",
                    omit_distance=False, surface_prims="", directed_prims="",
                    edges_to_avoid=""):
    """
    pcg100 Houdini costs / surface constraints -> directed edges (src, dst, w).

    E / w are the result of edge_weights (the old "base x multiplier" part; with omit_distance this whole part counts as 0). On top of that:
      + Primitive Cost   the attribute value of the prim the edge belongs to (when several prims share the edge, the lowest-numbered one;
                         with Surface Primitives, only among prims in the group)
      + Point Cost       added when walking **into** this point (not for the start point itself) -- docs: "paths passing through the point add it";
                         the docs do not say whether the start counts as "passing through", here it does not
    Surface Primitives: only edges of these prims can be walked. Directed Primitives: edges that appear only in directed prims can only be walked
    in the prim's direction; if the same edge is also in another (non-directed) prim, both directions are allowed. Edges to Avoid: an edge group, not walked.
    """
    from .groups import resolve_edges
    t = topology(geo)
    n = geo.npoints
    vp = geo.vertex_point.astype(np.int64)
    nxt = geo.next_corner()
    vprim = geo.vertex_prim().astype(np.int64)
    hv = np.nonzero(t.he_valid)[0]
    he_e = t.he_edge[hv].astype(np.int64)            # half-edge -> edge number (same order as E: both are topology's edges)
    he_from, _he_to, he_prim = vp[hv], vp[nxt[hv]], vprim[hv]
    surf = (resolve(geo, PRIM, surface_prims) if str(surface_prims or "").strip()
            else np.ones(geo.nprims, bool))
    use = surf[he_prim]
    dirp = (resolve(geo, PRIM, directed_prims, empty_is_all=False)
            if str(directed_prims or "").strip() else np.zeros(geo.nprims, bool))
    ne = len(E)
    both = np.zeros(ne, bool)                        # has a non-directed half-edge: both directions allowed
    np.logical_or.at(both, he_e[use & ~dirp[he_prim]], True)
    fwd = np.zeros(ne, bool)                         # direction E[k,0] -> E[k,1] allowed by some directed prim
    bwd = np.zeros(ne, bool)
    dd = use & dirp[he_prim]
    same = he_from == E[he_e, 0]
    np.logical_or.at(fwd, he_e[dd & same], True)
    np.logical_or.at(bwd, he_e[dd & ~same], True)
    ok_f, ok_b = both | fwd, both | bwd
    if str(edges_to_avoid or "").strip():
        for nm in str(edges_to_avoid).split():
            if nm not in geo.edge_groups:
                raise KeyError(f"Edges to Avoid: no edge group '{nm}'. Existing: {sorted(geo.edge_groups) or '(none)'}")
        from .groups import edge_mask
        bad = edge_mask(geo, resolve_edges(geo, edges_to_avoid))
        ok_f, ok_b = ok_f & ~bad, ok_b & ~bad
    base = np.zeros(ne) if omit_distance else np.asarray(w, np.float64)
    if str(prim_cost_attribute or "").strip():
        a = geo.get(PRIM, prim_cost_attribute)
        if a is None or a.dtype.kind not in "fiu":
            raise KeyError(f"Primitive Cost Attribute: no numeric prim attribute '{prim_cost_attribute}'")
        pc = np.asarray(a, np.float64)[:, 0]
        first = np.full(ne, np.iinfo(np.int64).max)
        np.minimum.at(first, he_e[use], he_prim[use])
        has = first < geo.nprims
        base = base + np.where(has, pc[np.where(has, first, 0)], 0.0)
    ptc = np.zeros(n)
    if str(point_cost_attribute or "").strip():
        a = geo.get(POINT, point_cost_attribute)
        if a is None or a.dtype.kind not in "fiu":
            raise KeyError(f"Point Cost Attribute: no numeric point attribute '{point_cost_attribute}'")
        ptc = np.asarray(a, np.float64)[:, 0]
    src = np.concatenate([E[ok_f, 0], E[ok_b, 1]])
    dst = np.concatenate([E[ok_f, 1], E[ok_b, 0]])
    ww = np.concatenate([base[ok_f], base[ok_b]]) + ptc[dst]
    if np.any(ww < 0):
        raise ValueError(f"{int((ww < 0).sum())} edges have cost < 0 -- shortest path requires non-negative costs. "
                         "Check the Point / Primitive Cost attributes")
    return src, dst, ww


def _adj_directed(n, src, dst, w):
    order = np.argsort(src, kind="stable")
    off = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=n))])
    return off.tolist(), dst[order].tolist(), w[order].tolist()


def _adjacency(n, E, w):
    """Adjacency list of the undirected graph (Python lists, converted before entering the loop)."""
    src = np.concatenate([E[:, 0], E[:, 1]])
    dst = np.concatenate([E[:, 1], E[:, 0]])
    ww = np.concatenate([w, w])
    order = np.argsort(src, kind="stable")
    off = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=n))])
    return off.tolist(), dst[order].tolist(), ww[order].tolist()


def dijkstra(adj, sources, targets=None):
    """
    Multi-source Dijkstra. Returns (dist list, prev list, root list). root[i] = which
    source i was reached from (with multiple sources, used to know "which target is nearest"). If targets is given, stops early once they have all
    been popped.
    """
    off, nbr, wt = adj
    n = len(off) - 1
    INF = float("inf")
    dist = [INF] * n
    prev = [-1] * n
    root = [-1] * n
    heap = []
    for s in sources:
        s = int(s)
        if dist[s] > 0:
            dist[s] = 0.0
            root[s] = s
            heap.append((0.0, s))
    heapq.heapify(heap)
    left = set(int(t) for t in targets) if targets is not None else None
    done = [False] * n
    while heap:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        if left is not None:
            left.discard(u)
            if not left:
                break
        for k in range(off[u], off[u + 1]):
            v = nbr[k]
            nd = d + wt[k]
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                root[v] = root[u]
                heapq.heappush(heap, (nd, v))
    return dist, prev, root


def _trace(prev, end):
    path = [end]
    while prev[path[-1]] != -1:
        path.append(prev[path[-1]])
    return path[::-1]


def ordered_points(geo, spec):
    """
    Group specifier -> point numbers **in the written order**. "12 5 40" means 12 -> 5 -> 40 (Group Find Path
    connects in this order); when a group name / range / expression is written, falls back to ascending point number.
    """
    s = str(spec).strip()
    if s and all(re.fullmatch(r"-?\d+", t) for t in s.split()):
        n = geo.npoints
        out = []
        for t in s.split():
            i = int(t)
            if -n <= i < n:
                out.append(i % n)
        return out
    return np.nonzero(resolve(geo, POINT, s, empty_is_all=False))[0].tolist()


def _paths_geometry(geo, paths, info):
    """Path -> polyline. Points are copied from the source geometry (P and all point attributes), info is written on the prim."""
    P = np.asarray(geo.get(POINT, "P"))
    pts = np.concatenate([np.asarray(p, np.int64) for p in paths])
    out = Geometry.from_mesh(P[pts], [], closed=False)
    off = np.concatenate([[0], np.cumsum([len(p) for p in paths])])
    out.set_topology(np.arange(len(pts), dtype=np.int32), off.astype(np.int32),
                     np.zeros(len(paths), bool))
    for k, v in geo.attribs[POINT].items():
        if k != "P":
            out.set(POINT, k, v[pts], owned=True)
    out.set(POINT, "srcpt", pts[:, None].astype(np.int32), owned=True)
    for k, vals in info.items():
        out.set(PRIM, k, np.asarray(vals).reshape(len(paths), -1), owned=True)
    return out


def find_shortest_path(geo, start_group="", end_group="", mode="nearest_end",
                       use_length=True, cost_attribute="", cost_weight=1.0,
                       slope_weight=0.0, up=(0, 1, 0), output="paths",
                       group_name="path", close_sequence=False, max_cost=None,
                       prim_cost_attribute="", point_cost_attribute="", omit_distance=False,
                       surface_prims="", directed_prims="", edges_to_avoid=""):
    """
    Matches Houdini's Find Shortest Path.

    mode:
      nearest_end  each start goes to the target **nearest to it** (one multi-source Dijkstra expanding from all targets
                   at once, so it runs only once no matter how many starts)
      each_pair    one path from each start to each end
      sequence     chain the start group in written order (0 -> 1 -> 2 ...), the end group is not used;
                   close_sequence additionally goes from the last back to the first
    output:
      paths   only output paths (polylines, points are copies of the source points with srcpt; prims carry cost / length /
              startpt / endpt)
      merge   source geometry + paths
      group   no new geometry, writes edge group group_name and a point group of the same name on the source geometry
    Unreachable ones (disconnected) are skipped and counted in the report. Returns (geometry, report).

    pcg100 additions (Houdini Output Paths' other three modes + Path Costs / Surface Constraints):
      any_to_any             the **single** lowest-cost path among all starts to all ends
      any_start_to_each_end  one per end: from the start nearest to it (lowest cost)
      corresponding          starts and ends paired one-to-one in written order (counts must be equal)
      max_cost               paths costing more than this count as unreachable (Max Search Path Cost); None = unlimited
      prim_cost_attribute / point_cost_attribute / omit_distance / surface_prims /
      directed_prims / edges_to_avoid   see _directed_graph
    """
    if mode not in PATH_MODES:
        raise ValueError(f"Mode must be one of {PATH_MODES}")
    if output not in PATH_OUTPUTS:
        raise ValueError(f"Output must be one of {PATH_OUTPUTS}")
    if geo is None or geo.npoints == 0:
        return Geometry(), {"paths": 0}
    E, w = edge_weights(geo, use_length, cost_attribute, cost_weight,
                        slope_weight, up)
    if not len(E):
        raise ValueError("Geometry has no edges (a point cloud?) -- shortest path walks along edges")
    extra = any(str(x or "").strip() for x in (prim_cost_attribute, point_cost_attribute,
                                               surface_prims, directed_prims, edges_to_avoid)) \
        or omit_distance
    if extra:
        src, dst, ww = _directed_graph(geo, E, w, prim_cost_attribute, point_cost_attribute,
                                       omit_distance, surface_prims, directed_prims, edges_to_avoid)
        adj = _adj_directed(geo.npoints, src, dst, ww)
        radj = _adj_directed(geo.npoints, dst, src, ww)     # reversed graph: expand backward from the ends
    else:
        adj = _adjacency(geo.npoints, E, w)
        radj = adj
    INF = float("inf")
    lim = INF if max_cost is None else float(max_cost)

    def bad(c):
        return c == INF or c > lim

    starts = ordered_points(geo, start_group)
    if not starts:
        raise ValueError("Start group is empty -- enter a point group name, or write point numbers in order "
                         "(e.g. '0 57 120')")
    pairs = []                                   # (start, end, path, cost)
    unreachable = 0
    if mode == "sequence":
        seq = list(starts) + ([starts[0]] if close_sequence and
                              len(starts) > 2 else [])
        for a, b in zip(seq[:-1], seq[1:]):
            dist, prev, _ = dijkstra(adj, [a], [b])
            if bad(dist[b]):
                unreachable += 1
                continue
            pairs.append((a, b, _trace(prev, b), dist[b]))
    else:
        ends = ordered_points(geo, end_group)
        if not ends:
            raise ValueError("End group is empty -- enter a point group name or point numbers; to just "
                             "chain the start group in order, use Mode sequence")
        if mode == "nearest_end":
            dist, prev, root = dijkstra(radj, ends, starts)
            for a in starts:
                if bad(dist[a]):
                    unreachable += 1
                    continue
                path = _trace(prev, a)[::-1]            # expanded from the end, so reverse
                pairs.append((a, root[a], path, dist[a]))
        elif mode == "each_pair":
            for a in starts:
                dist, prev, _ = dijkstra(adj, [a], ends)
                for b in ends:
                    if bad(dist[b]):
                        unreachable += 1
                        continue
                    pairs.append((a, b, _trace(prev, b), dist[b]))
        elif mode in ("any_start_to_each_end", "any_to_any"):
            # Expand from all starts at once (multi-source); each end knows which start it came from
            dist, prev, _ = dijkstra(adj, starts, ends)
            got = [(b, dist[b]) for b in ends if not bad(dist[b])]
            unreachable += len(ends) - len(got)
            if mode == "any_to_any":
                unreachable = 0 if got else 1
                # For ends with equal cost, take the one written first
                got = [min(got, key=lambda x: x[1])] if got else []
            for b, c in got:
                path = _trace(prev, b)
                pairs.append((path[0], b, path, c))       # which start the path departs from
        else:                                           # corresponding
            if len(starts) != len(ends):
                raise ValueError(f"corresponding requires start count = end count, got {len(starts)} and {len(ends)}")
            for a, b in zip(starts, ends):
                dist, prev, _ = dijkstra(adj, [a], [b])
                if bad(dist[b]):
                    unreachable += 1
                    continue
                pairs.append((a, b, _trace(prev, b), dist[b]))
    rep = {"paths": len(pairs), "unreachable": unreachable,
           "total_cost": float(sum(p[3] for p in pairs))}
    if output == "group":
        g = geo.copy()
        edges = [(p[k], p[k + 1]) for _, _, p, _ in pairs
                 for k in range(len(p) - 1)]
        g.set_edge_group(group_name, np.asarray(edges, np.int64).reshape(-1, 2))
        pm = np.zeros(geo.npoints, bool)
        for _, _, p, _ in pairs:
            pm[p] = True
        g.set_group(POINT, group_name, pm)
        return g, rep
    if not pairs:
        return (geo.copy() if output == "merge" else Geometry()), rep
    Pp = np.asarray(geo.get(POINT, "P"), np.float64)
    lengths = [float(np.linalg.norm(np.diff(Pp[p], axis=0), axis=1).sum())
               for _, _, p, _ in pairs]
    info = {"startpt": np.array([p[0] for p in pairs], np.int32),
            "endpt": np.array([p[1] for p in pairs], np.int32),
            "cost": np.array([p[3] for p in pairs], np.float32),
            "length": np.array(lengths, np.float32)}
    paths = _paths_geometry(geo, [p[2] for p in pairs], info)
    if output == "merge":
        from .ops import merge
        return merge(geo, paths), rep
    return paths, rep


def _blocked_adjacency(n, E, w, blocked):
    keep = ~(blocked[E[:, 0]] | blocked[E[:, 1]])
    return _adjacency(n, E[keep], w[keep])


def _gfp_segments(geo, segs, use_length, cost_attribute, cost_weight, avoid, block0):
    """
    Walk the shortest path segment by segment; with avoid, each segment avoids points already used by earlier segments (except this segment's own two endpoints) --
    Houdini's Avoid Self Intersection: "priority by Base Group order". block0 are points blocked by the Collision Group
    (endpoints themselves excepted). Returns (list of paths, number of unreachable segments).
    """
    n = geo.npoints
    E, w = edge_weights(geo, use_length, cost_attribute, cost_weight)
    used = np.zeros(n, bool)
    paths, miss = [], 0
    for a, b in segs:
        blk = block0 | used if avoid else block0.copy()
        blk[[a, b]] = False
        dist, prev, _ = dijkstra(_blocked_adjacency(n, E, w, blk), [a], [b])
        if dist[b] == float("inf"):
            miss += 1
            continue
        path = _trace(prev, b)
        paths.append(path)
        used[path] = True
    return paths, miss


def group_find_path(geo, points="", mode="shortest_path", close=False,
                    use_length=True, cost_attribute="", cost_weight=1.0,
                    group_name="path", avoid_self_intersection=False, collision_group="",
                    contain_within_collision=False):
    """
    Matches Houdini's Group Find Path: writes an **edge group** (and a point group of the same name) on the source geometry, no new
    geometry.

      shortest_path  shortest path between consecutive points in points, in written order ("12 40 7")
      boundary_loop  the **boundary loop** each point in points lies on (the loop formed by edges used by only one face)
                     -- selects the rim of an opening, the loop around a hole
    Returns (geometry, report).

    pcg100 additions (points only; default = old behaviour):
      start_end_pairs           pair up points (1st and 2nd a pair, 3rd and 4th a pair ...), one path per pair;
                                with close each pair also walks back to form a loop
      avoid_self_intersection   later segments avoid points used by earlier segments (endpoints excepted). Together with close this is Houdini's
                                Close Path: "find a return path that does not intersect the original"; two points can form a loop too
      collision_group           a point group the path does not pass through (endpoints excepted); with contain_within_collision it is reversed,
                                walking only inside the group
    """
    if mode not in GFP_MODES:
        raise ValueError(f"Mode must be one of {GFP_MODES}")
    if not ordered_points(geo, points):
        raise ValueError("Points is empty -- shortest_path needs two or more point numbers written in order "
                         "(e.g. '0 57 120'), boundary_loop needs one point on the boundary")
    new = (mode == "start_end_pairs" or avoid_self_intersection
           or str(collision_group or "").strip())
    if mode == "shortest_path" and not new:
        return find_shortest_path(geo, points, "", "sequence", use_length,
                                  cost_attribute, cost_weight, output="group",
                                  group_name=group_name, close_sequence=close)
    if mode != "boundary_loop":
        seq = ordered_points(geo, points)
        if mode == "start_end_pairs":
            if len(seq) % 2:
                raise ValueError(f"start_end_pairs needs an even number of points (in pairs), got {len(seq)}")
            segs = []
            for a, b in zip(seq[0::2], seq[1::2]):
                segs.append((a, b))
                if close:
                    segs.append((b, a))
        else:
            # Old behaviour: close only with three or more points (with two points the return is the same path); with self-intersection avoidance two points can form a loop too
            ring = close and (len(seq) > 2 or (avoid_self_intersection and len(seq) == 2))
            s2 = list(seq) + ([seq[0]] if ring else [])
            segs = list(zip(s2[:-1], s2[1:]))
        n = geo.npoints
        if str(collision_group or "").strip():
            cm = resolve(geo, POINT, collision_group)
            block0 = ~cm if contain_within_collision else cm
        else:
            block0 = np.zeros(n, bool)
        paths, miss = _gfp_segments(geo, segs, use_length, cost_attribute, cost_weight,
                                    avoid_self_intersection, block0)
        g = geo.copy()
        edges = [(p[k], p[k + 1]) for p in paths for k in range(len(p) - 1)]
        g.set_edge_group(group_name, np.asarray(edges, np.int64).reshape(-1, 2))
        pm = np.zeros(n, bool)
        for p in paths:
            pm[p] = True
        g.set_group(POINT, group_name, pm)
        return g, {"paths": len(paths), "unreachable": miss}
    t = topology(geo)
    g = geo.copy()
    seeds = ordered_points(geo, points)
    face_he = np.zeros(geo.nvertices, bool)
    sizes = geo.prim_sizes()
    face_he[np.repeat(geo.prim_closed & (sizes >= 3), sizes)] = True
    # Boundary edges: exactly one half-edge, and that half-edge belongs to a face (polyline edges do not count)
    bnd = t.boundary.copy()
    if t.nedges:
        he0 = t.edge_he[t.edge_he_off[:-1]]
        bnd &= face_he[he0]
    BE = t.edge_points[bnd].astype(np.int64)
    # Connected components over boundary edges (union-find); the whole component containing a seed point is selected
    parent = np.arange(geo.npoints)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in BE:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = {find(s) for s in seeds}
    keep = np.array([find(a) in roots for a in BE[:, 0]], bool) \
        if len(BE) else np.zeros(0, bool)
    sel = BE[keep]
    g.set_edge_group(group_name, sel)
    pm = np.zeros(geo.npoints, bool)
    pm[sel.reshape(-1)] = True
    g.set_group(POINT, group_name, pm)
    return g, {"edges": int(len(sel)), "loops": len(roots)}


# ═══════════════════════════════════════════════════════════ curve intersection
_AX = {"xz": (0, 2), "xy": (0, 1), "yz": (1, 2)}


def _segments(geo, group):
    """Segments of all curves: (A, B, prim, segment index, arc length at segment start, curve point index table)."""
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    A, B, pr, sk, s0 = [], [], [], [], []
    curves = []
    for pi, pts, closed in _cf.curve_prims(geo, group):
        q = np.concatenate([pts, pts[:1]]) if closed else pts
        a, b = P[q[:-1]], P[q[1:]]
        ln = np.linalg.norm(b - a, axis=1)
        A.append(a); B.append(b)
        pr.append(np.full(len(a), pi)); sk.append(np.arange(len(a)))
        s0.append(np.concatenate([[0.0], np.cumsum(ln)[:-1]]))
        curves.append((pi, pts, closed))
    if not A:
        z = np.zeros((0, 3))
        return z, z, np.zeros(0, int), np.zeros(0, int), np.zeros(0), curves
    return (np.vstack(A), np.vstack(B), np.concatenate(pr),
            np.concatenate(sk), np.concatenate(s0), curves)


def _candidate_pairs(lo, hi, h):
    """Pairs of segments whose bounding boxes fall in the same cell (i < j, deduplicated)."""
    b, big = _sp._box_bucket(lo, hi, h)
    I, J = [], []
    cnt = b.counts
    for c in np.unique(cnt[cnt > 1]):
        cells = np.nonzero(cnt == c)[0]
        items = b.items[(b.starts[cells][:, None] + np.arange(c)[None, :])]
        iu, ju = np.triu_indices(int(c), 1)
        I.append(items[:, iu].reshape(-1)); J.append(items[:, ju].reshape(-1))
    n = len(lo)
    if len(big):                                   # oversized segments: paired with all segments
        for bi in big:
            I.append(np.full(n, bi)); J.append(np.arange(n))
    if not I:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    I, J = np.concatenate(I), np.concatenate(J)
    lo_, hi_ = np.minimum(I, J), np.maximum(I, J)
    m = lo_ != hi_
    key = np.unique(lo_[m] * n + hi_[m])
    return key // n, key % n


def _seg_seg_2d(a, b, c, d):
    """Planar segments ab and cd: returns (intersection mask, t, u). Parallel ones do not count (collinear overlap not handled)."""
    r = b - a
    s = d - c
    den = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
    qp = c - a
    ok = np.abs(den) > 1e-15
    dd = np.where(ok, den, 1.0)
    t = (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / dd
    u = (qp[:, 0] * r[:, 1] - qp[:, 1] * r[:, 0]) / dd
    e = 1e-12
    hit = ok & (t >= -e) & (t <= 1 + e) & (u >= -e) & (u <= 1 + e)
    return hit, np.clip(t, 0, 1), np.clip(u, 0, 1)


def _seg_seg_3d(a, b, c, d, tol):
    """3D: closest points between two segments (Ericson 5.1.9); distance <= tol counts as an intersection."""
    d1, d2, r = b - a, d - c, a - c
    A = np.einsum("ij,ij->i", d1, d1)
    E = np.einsum("ij,ij->i", d2, d2)
    F = np.einsum("ij,ij->i", d2, r)
    C = np.einsum("ij,ij->i", d1, r)
    Bv = np.einsum("ij,ij->i", d1, d2)
    den = A * E - Bv * Bv
    s = np.where(den > 1e-18, np.clip((Bv * F - C * E) / np.where(den > 1e-18,
                                                                  den, 1), 0, 1), 0.0)
    t = (Bv * s + F) / np.where(E > 1e-18, E, 1)
    t = np.where(E > 1e-18, t, 0.0)
    s = np.where(t < 0, np.clip(-C / np.where(A > 1e-18, A, 1), 0, 1), s)
    s = np.where(t > 1, np.clip((Bv - C) / np.where(A > 1e-18, A, 1), 0, 1), s)
    t = np.clip(t, 0, 1)
    p1 = a + d1 * s[:, None]
    p2 = c + d2 * t[:, None]
    dist = np.linalg.norm(p1 - p2, axis=1)
    return dist <= tol, s, t


def curve_intersect(geo, group="", plane="xz", tolerance=1e-4,
                    self_intersect=True, output="split",
                    point_group="intersections"):
    """
    Intersect curves pairwise. plane: xz / xy / yz intersect in the projection onto that plane (road networks undulate over
    terrain, so intersecting in top view is correct); 3d requires the two segments to actually come within tolerance.

    output:
      points  output only intersection points: prim_a / prim_b (which two curves), u_a / u_b (arc-length position on each)
      split   **cut the curves at intersections and share the intersection points**: each output segment is an independent open curve,
              and the intersection point is the same point in both curves -- a connected network that Find Shortest Path can
              walk directly. Intersection points go into point group point_group. In planar modes the intersection point is placed at the average height
              of the two curves at that location
    self_intersect: a curve intersecting itself also counts (endpoints shared by adjacent segments do not).
    Returns (geometry, report).
    """
    if plane not in INTERSECT_PLANES:
        raise ValueError(f"Plane must be one of {INTERSECT_PLANES}")
    if output not in INTERSECT_OUTPUTS:
        raise ValueError(f"Output must be one of {INTERSECT_OUTPUTS}")
    if geo is None or geo.npoints == 0:
        return Geometry(), {"intersections": 0}
    A, B, pr, sk, s0, curves = _segments(geo, group)
    if not len(A):
        return geo.copy() if output == "split" else Geometry(), \
            {"intersections": 0}
    tol = max(float(tolerance), 0.0)
    if plane == "3d":
        lo, hi = np.minimum(A, B) - tol, np.maximum(A, B) + tol
    else:
        i0, i1 = _AX[plane]
        A2, B2 = A[:, [i0, i1]], B[:, [i0, i1]]
        z = np.zeros((len(A), 1))
        lo = np.hstack([np.minimum(A2, B2) - tol, z])
        hi = np.hstack([np.maximum(A2, B2) + tol, z])
    ln = np.linalg.norm(B - A, axis=1)
    h = max(float(np.median(ln)) if len(ln) else 1.0, tol * 4, 1e-6)
    I, J = _candidate_pairs(lo, hi, h)
    # Same curve: adjacent segments (sharing an endpoint) never count; without self-intersection the whole curve is excluded
    same = pr[I] == pr[J]
    # The first and last segments of a closed curve also share an endpoint; those of an open curve do not
    wrap_of = {pi: (len(pts) - 1 if closed else -10) for pi, pts, closed in curves}
    wrap = np.array([wrap_of[p] for p in pr[I]], np.int64) if len(I) else \
        np.zeros(0, np.int64)
    dk = np.abs(sk[I] - sk[J])
    adj = same & ((dk == 1) | (dk == wrap))
    keep = ~adj & (~same if not self_intersect else True)
    I, J = I[keep], J[keep]
    if plane == "3d":
        hit, t, u = _seg_seg_3d(A[I], B[I], A[J], B[J], tol)
    else:
        hit, t, u = _seg_seg_2d(A2[I], B2[I], A2[J], B2[J])
    I, J, t, u = I[hit], J[hit], t[hit], u[hit]
    pa = A[I] + (B[I] - A[I]) * t[:, None]
    pb = A[J] + (B[J] - A[J]) * u[:, None]
    X = (pa + pb) * 0.5
    ua = s0[I] + t * ln[I]
    ub = s0[J] + u * ln[J]
    # The same pair of curves at the same position counts only once (an intersection on a vertex is reported once by each adjacent segment)
    if len(X):
        q = np.round(X / max(tol, 1e-9)).astype(np.int64)
        k = np.column_stack([np.minimum(pr[I], pr[J]),
                             np.maximum(pr[I], pr[J]), q])
        _, first = np.unique(k, axis=0, return_index=True)
        first = np.sort(first)
        I, J, X, ua, ub = I[first], J[first], X[first], ua[first], ub[first]
    rep = {"intersections": int(len(X))}
    if output == "points":
        out = Geometry.from_points(X)
        out.set(POINT, "prim_a", pr[I][:, None].astype(np.int32), owned=True)
        out.set(POINT, "prim_b", pr[J][:, None].astype(np.int32), owned=True)
        out.set(POINT, "u_a", ua[:, None].astype(np.float32), owned=True)
        out.set(POINT, "u_b", ub[:, None].astype(np.float32), owned=True)
        return out, rep
    return _split_at(geo, curves, pr, I, J, X, ua, ub, point_group), rep


def _split_at(geo, curves, pr, I, J, X, ua, ub, point_group):
    """Cut curves at intersection points; intersection points become shared new points."""
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    n0 = geo.npoints
    # Cut points on each curve: (arc length, intersection index)
    cuts = {}
    for k in range(len(X)):
        cuts.setdefault(int(pr[I[k]]), []).append((float(ua[k]), k))
        cuts.setdefault(int(pr[J[k]]), []).append((float(ub[k]), k))
    newP = [P]
    xid = np.arange(len(X)) + n0
    newP.append(X)
    src_pt = list(range(n0)) + [-1] * len(X)
    prims, prim_src = [], []
    covered = set()
    for pi, pts, closed in curves:
        covered.add(pi)
        seq = list(pts) + ([pts[0]] if closed else [])
        Q = P[seq]
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0),
                                                             axis=1))])
        cl = sorted(cuts.get(pi, []))
        if not cl:
            prims.append(list(pts) if not closed else list(pts))
            prim_src.append((pi, closed))
            continue
        # Insert intersection points into the vertex sequence; within 1e-9 of an existing vertex, replace that vertex directly
        verts = []
        is_cut = []
        ci = 0
        for j in range(len(seq)):
            while ci < len(cl) and cl[ci][0] < s[j] - 1e-9:
                verts.append(int(xid[cl[ci][1]])); is_cut.append(True); ci += 1
            if ci < len(cl) and abs(cl[ci][0] - s[j]) <= 1e-9:
                verts.append(int(xid[cl[ci][1]])); is_cut.append(True); ci += 1
                while ci < len(cl) and abs(cl[ci][0] - s[j]) <= 1e-9:
                    ci += 1
            else:
                verts.append(int(seq[j])); is_cut.append(False)
        while ci < len(cl):
            verts.append(int(xid[cl[ci][1]])); is_cut.append(True); ci += 1
        if closed:
            verts, is_cut = verts[:-1], is_cut[:-1]      # drop the repeated closing start point
            cidx = [k for k, c in enumerate(is_cut) if c]
            # Closed curve: go around once from the first cut point, cut into len(cidx) segments
            r = cidx[0]
            verts = verts[r:] + verts[:r] + [verts[r]]
            is_cut = is_cut[r:] + is_cut[:r] + [True]
        piece = [verts[0]]
        for k in range(1, len(verts)):
            piece.append(verts[k])
            if is_cut[k] and k < len(verts) - 1 or k == len(verts) - 1:
                if len(piece) >= 2:
                    prims.append(piece)
                    prim_src.append((pi, False))
                piece = [verts[k]]
    # prims that are not curves (faces) are kept as they are
    others = [i for i in range(geo.nprims) if i not in covered]
    for i in others:
        prims.append(geo.prim_points(i).tolist())
        prim_src.append((i, bool(geo.prim_closed[i])))
    allP = np.vstack(newP)
    out = Geometry.from_mesh(allP, prims, closed=False)
    out.set_topology(out.vertex_point, out.prim_offset,
                     np.array([c for _, c in prim_src], bool))
    sp = np.asarray(src_pt)
    has = sp >= 0
    for k, v in geo.attribs[POINT].items():
        if k == "P":
            continue
        a = np.zeros((len(allP), v.shape[1]), v.dtype)
        a[has] = v[sp[has]]
        out.set(POINT, k, a, owned=True)
    src = np.array([i for i, _ in prim_src], np.int64)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[src], owned=True)
    out.set(PRIM, "curvenum", src[:, None].astype(np.int32), owned=True)
    g = np.zeros(len(allP), bool)
    g[xid] = True
    if str(point_group).strip():
        out.set_group(POINT, str(point_group).strip(), g)
    return out


# ─────────────────────────────── pcg100: Houdini semantics (left = Face Group, right = Cutter Group)
def _seg_arrays(geo, curves):
    """Segments of curves: (A, B, curve index, arc length at segment start, segment length)."""
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    A, B, ci, s0 = [], [], [], []
    for k, (pi, pts, closed) in enumerate(curves):
        q = np.concatenate([pts, pts[:1]]) if closed else pts
        a, b = P[q[:-1]], P[q[1:]]
        ln = np.linalg.norm(b - a, axis=1)
        A.append(a); B.append(b); ci.append(np.full(len(a), k))
        s0.append(np.concatenate([[0.0], np.cumsum(ln)[:-1]]))
    if not A:
        z = np.zeros((0, 3))
        return z, z, np.zeros(0, np.int64), np.zeros(0)
    return np.vstack(A), np.vstack(B), np.concatenate(ci), np.concatenate(s0)


def _proj(X, plane):
    """Planar modes: zero the dropped axis before measuring distance (uses the same closest-point function as 3d)."""
    if plane == "3d":
        return X
    Y = np.zeros_like(X)
    i0, i1 = _AX[plane]
    Y[:, i0], Y[:, i1] = X[:, i0], X[:, i1]
    return Y


_HIT_PAIR_LIMIT = 20_000_000      # with Find All off every segment pair must be computed; error above this many pairs rather than eating all memory


def _curve_hits(LA, LB, Lc, Ls, RA, RB, Rc, Rs, plane, tol, find_all):
    """
    Intersections between the left and right segment sets: returns [(left curve, right curve, left arc length, right arc length, point on left, point on right)].
    find_all: all intersections with distance <= tol (same pair of curves at the same position counted once); otherwise each pair of curves takes only **the closest one**
    (docs: with Find All Intersections off only the minimum-distance point is found -- not required to be within tol).
    """
    out = []
    if not len(LA) or not len(RA):
        return out
    LA2, LB2, RA2, RB2 = _proj(LA, plane), _proj(LB, plane), _proj(RA, plane), _proj(RB, plane)
    nl, nr = len(LA), len(RA)
    if find_all:
        # Segment pairs whose bounding boxes (padded by tol) fall in the same cell, then keep only left-right pairs
        A2, B2 = np.vstack([LA2, RA2]), np.vstack([LB2, RB2])
        lo, hi = np.minimum(A2, B2) - tol, np.maximum(A2, B2) + tol
        ln = np.linalg.norm(B2 - A2, axis=1)
        I, J = _candidate_pairs(lo, hi, max(float(np.median(ln)), tol * 4, 1e-6))
        m = (I < nl) & (J >= nl)
        I, J = I[m], J[m] - nl
    else:
        if nl * nr > _HIT_PAIR_LIMIT:
            raise ValueError(f"With Find All Intersections off every segment pair must be compared ({nl}x{nr}), too many")
        I = np.repeat(np.arange(nl), nr)
        J = np.tile(np.arange(nr), nl)
    _, t, u = _seg_seg_3d(LA2[I], LB2[I], RA2[J], RB2[J], np.inf)
    d = np.linalg.norm((LA2[I] + (LB2[I] - LA2[I]) * t[:, None]) - (RA2[J] + (RB2[J] - RA2[J]) * u[:, None]), axis=1)
    lnL = np.linalg.norm(LB - LA, axis=1)
    lnR = np.linalg.norm(RB - RA, axis=1)
    ua = Ls[I] + t * lnL[I]
    ub = Rs[J] + u * lnR[J]
    pa = LA[I] + (LB[I] - LA[I]) * t[:, None]
    pb = RA[J] + (RB[J] - RA[J]) * u[:, None]
    if find_all:
        k = np.nonzero(d <= tol)[0]
        if len(k):
            # An intersection on a vertex is reported once by each adjacent segment: same pair of curves with left arc length differing by < 1e-9.scale counts as one
            key = np.column_stack([Lc[I[k]], Rc[J[k]], np.round(ua[k] / max(tol, 1e-9))])
            _, first = np.unique(key, axis=0, return_index=True)
            k = k[np.sort(first)]
        for q in k:
            out.append((int(Lc[I[q]]), int(Rc[J[q]]), float(ua[q]), float(ub[q]), pa[q], pb[q]))
        return out
    pair = Lc[I] * (int(Rc.max()) + 1) + Rc[J]
    order = np.lexsort((ua, d, pair))                 # per curve pair: smallest distance, then by left arc length
    pair_s = pair[order]
    first = order[np.concatenate([[True], pair_s[1:] != pair_s[:-1]])]
    for q in first:
        out.append((int(Lc[I[q]]), int(Rc[J[q]]), float(ua[q]), float(ub[q]), pa[q], pb[q]))
    return out


def _cut_pieces(P, pts, closed, cuts, keep, tol=0.0):
    """
    Cut a curve at arc lengths cuts and pick pieces by keep. Returns [(vertex table [(i, j, w)], closed)];
    vertex = (1 - w).point i + w.point j. No cut points: the whole curve as is (deleted with keep_none).
    Cut points on the ends of an open curve do not count (nothing can be cut there); cut points closer than Tolerance in arc length merge into one cut
    (when the cutting line passes exactly through a vertex, the two adjacent segments each report one, differing slightly within Tolerance).
    """
    seq = list(pts) + ([pts[0]] if closed else [])
    Q = P[seq]
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))])
    T = float(s[-1])
    eps = max(1e-9 * max(T, 1.0), float(tol))
    c = sorted(cuts)
    if not closed:
        c = [x for x in c if eps < x < T - eps]
    else:
        c = [x % T if T > 0 else 0.0 for x in c]
        c = sorted(c)
    cc = []
    for x in c:
        if not cc or x - cc[-1] > eps:
            cc.append(x)
    if closed and len(cc) > 1 and cc[0] + T - cc[-1] <= eps:
        cc.pop()
    if keep == "keep_none":
        return []
    if not cc:
        return [([(int(p), int(p), 0.0) for p in pts], closed)]
    if closed:                                        # unrolled into two loops, segments [c_k, c_{k+1}], the last one crosses the start
        seq = list(pts) * 2 + [pts[0]]
        Q = P[seq]
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))])
        bounds = [(cc[k], cc[k + 1] if k + 1 < len(cc) else cc[0] + T) for k in range(len(cc))]
    else:
        e = [0.0] + cc + [T]
        bounds = [(e[k], e[k + 1]) for k in range(len(e) - 1)]

    def at(x):
        j = int(np.clip(np.searchsorted(s, x, "right") - 1, 0, len(s) - 2))
        L = s[j + 1] - s[j]
        w = (x - s[j]) / L if L > 0 else 0.0
        return (int(seq[j]), int(seq[j + 1]), float(w))      # searchsorted guarantees x falls in this segment

    out = []
    for k, (a, b) in enumerate(bounds):
        if keep == "keep_odd" and k % 2 == 0 or keep == "keep_even" and k % 2 == 1:
            continue
        inner = [(int(seq[j]), int(seq[j]), 0.0) for j in range(len(s)) if a + eps < s[j] < b - eps]
        out.append(([at(a)] + inner + [at(b)], False))
    return out


def _pieces_geometry(geo, pieces):
    """[(source prim, vertex table, closed)] -> geometry. Each piece has its own points (pieces share none); float point attributes interpolated by w,
    others take the nearer point; prim attributes and groups copied from the source prim."""
    out = Geometry()
    if not pieces:
        return out
    I = np.array([v[0] for _, vs, _ in pieces for v in vs], np.int64)
    J = np.array([v[1] for _, vs, _ in pieces for v in vs], np.int64)
    W = np.array([v[2] for _, vs, _ in pieces for v in vs], np.float64)
    n = len(I)
    out._resize_points(n)
    near = np.where(W < 0.5, I, J)
    for k, v in geo.attribs[POINT].items():
        v = np.asarray(v)
        if v.dtype.kind == "f":
            out.set(POINT, k, ((1 - W)[:, None] * v[I] + W[:, None] * v[J]).astype(v.dtype), owned=True)
        else:
            out.set(POINT, k, v[near], owned=True)
    for k, m in geo.groups[POINT].items():
        out.set_group(POINT, k, np.asarray(m)[near])
    sizes = np.array([len(vs) for _, vs, _ in pieces], np.int64)
    out.set_topology(np.arange(n, dtype=np.int32), np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                     np.array([c for _, _, c in pieces], bool), np.full(len(pieces), PRIM_POLY, np.uint8))
    src = np.array([p for p, _, _ in pieces], np.int64)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, np.asarray(v)[src], owned=True)
    for k, m in geo.groups[PRIM].items():
        out.set_group(PRIM, k, np.asarray(m)[src])
    return out


def curve_intersect_hou(geo, cutter=None, group="", cutter_group="", plane="3d", tolerance=1e-4,
                        method="cut", find_all=True, left_pieces="keep_all", right_pieces="keep_all",
                        affect="left", keep_original=False):
    """
    Houdini's Curve Intersect: left = curves in Face Group of geo, right = curves in Cutter Group of cutter (geo itself if not connected);
    only intersections between left and right are computed (not left-left or right-right; a prim with itself in the same geometry does not count).
      cut      left and right are each cut at intersections, pieces numbered from 0, Left / Right-face Pieces pick all / odd / even / none;
               prims not selected into the left / right group are kept as they are (when cutter is another input, its unselected part is not output -- the docs
               say "Which pieces of the right face to create")
      extract  output intersection points (Affect: those on the left curves, on the right curves, or both); with Keep Original off the left group curves are deleted
    plane is this plugin's extension (3d = Houdini); with find_all off each pair of curves takes only the nearest one. Returns (geometry, report).
    """
    from .ops import merge, delete_prims
    if plane not in INTERSECT_PLANES:
        raise ValueError(f"Plane must be one of {INTERSECT_PLANES}")
    if method not in ("cut", "extract"):
        raise ValueError("method must be cut / extract")
    if left_pieces not in INTERSECT_KEEP or right_pieces not in INTERSECT_KEEP:
        raise ValueError(f"Pieces must be one of {INTERSECT_KEEP}")
    if affect not in INTERSECT_AFFECT:
        raise ValueError(f"Affect must be one of {INTERSECT_AFFECT}")
    if geo is None or geo.npoints == 0:
        return Geometry(), {"intersections": 0}
    same = cutter is None
    rgeo = geo if same else cutter
    L = _cf.curve_prims(geo, group)
    R = _cf.curve_prims(rgeo, cutter_group) if rgeo is not None and rgeo.nprims else []
    lset = {pi for pi, _, _ in L}
    if same:                                          # prims selected by both groups are treated as left
        R = [c for c in R if c[0] not in lset]
    LA, LB, Lc, Ls = _seg_arrays(geo, L)
    RA, RB, Rc, Rs = _seg_arrays(rgeo, R)
    hits = _curve_hits(LA, LB, Lc, Ls, RA, RB, Rc, Rs, plane, max(float(tolerance), 0.0),
                       bool(find_all))
    rep = {"intersections": len(hits)}
    if method == "extract":
        X = []
        if affect in ("left", "both"):
            X += [h[4] for h in hits]
        if affect in ("right", "both"):
            X += [h[5] for h in hits]
        pts = Geometry.from_points(np.asarray(X, np.float64).reshape(-1, 3))
        if keep_original:
            base = geo
        else:
            keep = np.ones(geo.nprims, bool)
            keep[list(lset)] = False
            base = delete_prims(geo, keep)
        return merge(base, pts), rep
    PL = np.asarray(geo.get(POINT, "P"), np.float64)
    lcut, rcut = {}, {}
    for a, b, ua, ub, _, _ in hits:
        lcut.setdefault(a, []).append(ua)
        rcut.setdefault(b, []).append(ub)
    lp = [(pi, vs, cl) for k, (pi, pts, closed) in enumerate(L)
          for vs, cl in _cut_pieces(PL, pts, closed, lcut.get(k, []), left_pieces, tolerance)]
    PR = np.asarray(rgeo.get(POINT, "P"), np.float64) if R else None
    rp = [(pi, vs, cl) for k, (pi, pts, closed) in enumerate(R)
          for vs, cl in _cut_pieces(PR, pts, closed, rcut.get(k, []), right_pieces, tolerance)]
    keep = np.ones(geo.nprims, bool)
    keep[list(lset)] = False
    if same:
        keep[[pi for pi, _, _ in R]] = False
    parts = [delete_prims(geo, keep) if keep.any() else None, _pieces_geometry(geo, lp),
             _pieces_geometry(rgeo, rp) if R else None]
    return merge(*parts), rep


# ═══════════════════════════════════════════════════════ Connect Adjacent Pieces
def connect_adjacent_pieces(geo, mode="points", radius=0.1, max_connections=4,
                            piece_attribute="name", keep_input=False,
                            group=""):
    """
    Matches Houdini's Connect Adjacent Pieces: connects lines (two-point polylines) between things that are "touching".

      points           point to point: one line to each of the max_connections nearest neighbours within the radius
      piece_centroids  piece to piece: two pieces are adjacent if any points are within radius, and a line connects
                       the two pieces' centers (at most max_connections per piece, chosen by nearest distance)
      piece_points     same as above, but the line connects **the closest pair of points** of the two pieces (constraint lands at the contact)
    Lines get restlength (line length) and the piece numbers / point numbers of both ends. keep_input: in points mode the lines attach directly
    to the source geometry's points and are output together; the other two modes create new points without the source geometry. Returns (geometry, report).
    """
    if mode not in CONNECT_MODES:
        raise ValueError(f"Mode must be one of {CONNECT_MODES}")
    if geo is None or geo.npoints == 0:
        return Geometry(), {"lines": 0}
    r = float(radius)
    if not r > 0:
        raise ValueError("Radius must be > 0")
    K = max(1, int(max_connections))
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    sel = np.nonzero(resolve(geo, POINT, group))[0]
    q, p, d = _sp.neighbors_within(P[sel], P[sel], r)
    q, p = sel[q], sel[p]
    m = q != p
    q, p, d = q[m], p[m], d[m]

    def top_k(owner, d, K):
        """Keep the K nearest for each owner (stable)."""
        order = np.lexsort((d, owner))
        o = owner[order]
        rank = np.arange(len(o)) - np.searchsorted(o, o, side="left")
        return order[rank < K]

    if mode == "points":
        pick = top_k(q, d, K)
        a, b = q[pick], p[pick]
        e = np.unique(np.sort(np.stack([a, b], 1), axis=1), axis=0)
        if keep_input:
            g = geo.copy()
            vp = np.concatenate([geo.vertex_point, e.reshape(-1).astype(np.int32)])
            off = np.concatenate([geo.prim_offset,
                                  geo.prim_offset[-1] + 2 * np.arange(1, len(e) + 1)])
            closed = np.concatenate([geo.prim_closed, np.zeros(len(e), bool)])
            ptype = np.concatenate([geo.prim_type, np.zeros(len(e), np.uint8)])
            g.set_topology(vp, off, closed, ptype)
            nold = geo.nprims
            for k, v in geo.attribs[PRIM].items():
                pad = np.zeros((len(e), v.shape[1]), v.dtype)
                g.set(PRIM, k, np.vstack([v, pad]), owned=True)
            for k, v in geo.attribs[VERTEX].items():
                pad = np.zeros((2 * len(e), v.shape[1]), v.dtype)
                g.set(VERTEX, k, np.vstack([v, pad]), owned=True)
            rl = np.zeros((g.nprims, 1), np.float32)
            rl[nold:, 0] = np.linalg.norm(P[e[:, 0]] - P[e[:, 1]], axis=1)
            g.set(PRIM, "restlength", rl, owned=True)
            for gname, gm in list(geo.groups[PRIM].items()):
                g.set_group(PRIM, gname, np.concatenate(
                    [gm, np.zeros(len(e), bool)]))
            return g, {"lines": int(len(e))}
        out = Geometry.from_mesh(P[e.reshape(-1)],
                                 np.arange(2 * len(e)).reshape(-1, 2),
                                 closed=False)
        out.set(PRIM, "restlength", np.linalg.norm(
            P[e[:, 0]] - P[e[:, 1]], axis=1)[:, None].astype(np.float32),
            owned=True)
        out.set(PRIM, "pt_a", e[:, :1].astype(np.int32), owned=True)
        out.set(PRIM, "pt_b", e[:, 1:].astype(np.int32), owned=True)
        return out, {"lines": int(len(e))}

    # ── pieces
    from . import copyto as _cp
    name = str(piece_attribute).strip()
    key = _cp._piece_key(geo, POINT, name) if name else None
    if key is None and name and geo.nprims:
        cls, pk = _cp._source_piece_keys(geo, name)
        if pk is not None:
            # A point's piece number is that of the face it is on; points not on any face are each their own piece (given a key that cannot collide)
            key = np.array([f"__lone{i}" for i in range(geo.npoints)]) \
                if pk.dtype.kind == "U" else -1 - np.arange(geo.npoints)
            key = key.astype(pk.dtype) if pk.dtype.kind != "U" else \
                key.astype(f"<U{max(pk.dtype.itemsize // 4, 16)}")
            key[geo.vertex_point] = np.repeat(pk, geo.prim_sizes())
    if key is None:
        from .topology import connectivity
        c = connectivity(geo, POINT, "__piece__")
        key = np.asarray(c.get(POINT, "__piece__"))[:, 0]
    uniq, pid = np.unique(key, return_inverse=True)
    pid = pid.reshape(-1)
    cross = pid[q] != pid[p]
    q, p, d = q[cross], p[cross], d[cross]
    a_, b_ = pid[q], pid[p]
    lo_, hi_ = np.minimum(a_, b_), np.maximum(a_, b_)
    npc = len(uniq)
    pk = lo_ * npc + hi_
    # For each pair of pieces keep the closest pair of points
    order = np.lexsort((d, pk))
    pk_s = pk[order]
    first = order[np.r_[True, pk_s[1:] != pk_s[:-1]]] if len(order) else order
    pa, pb, dd = lo_[first], hi_[first], d[first]
    qa = np.where(pid[q[first]] == pa, q[first], p[first])
    qb = np.where(pid[q[first]] == pa, p[first], q[first])
    # At most K per piece: from nearest to farthest, connect only if neither end is full
    cnt = np.zeros(npc, np.int64)
    keep = []
    for k in np.argsort(dd, kind="stable"):
        if cnt[pa[k]] < K and cnt[pb[k]] < K:
            keep.append(k)
            cnt[pa[k]] += 1
            cnt[pb[k]] += 1
    keep = np.asarray(keep, np.int64)
    pa, pb, qa, qb = pa[keep], pb[keep], qa[keep], qb[keep]
    if mode == "piece_centroids":
        C = np.zeros((npc, 3))
        np.add.at(C, pid, P)
        C /= np.maximum(np.bincount(pid, minlength=npc), 1)[:, None]
        A_, B_ = C[pa], C[pb]
    else:
        A_, B_ = P[qa], P[qb]
    out = Geometry.from_mesh(np.stack([A_, B_], 1).reshape(-1, 3),
                             np.arange(2 * len(pa)).reshape(-1, 2), closed=False)
    out.set(PRIM, "restlength", np.linalg.norm(A_ - B_, axis=1)[:, None]
            .astype(np.float32), owned=True)
    out.set(PRIM, "piece_a", pa[:, None].astype(np.int32), owned=True)
    out.set(PRIM, "piece_b", pb[:, None].astype(np.int32), owned=True)
    return out, {"lines": int(len(pa)), "pieces": int(npc)}
