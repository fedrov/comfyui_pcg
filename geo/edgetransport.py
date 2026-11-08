"""
Edge Transport (pcg82): transports / accumulates attributes along edges outwards from roots.

First a tree "from the roots" is built:
    curves    each curve (polyline prim) walks from its first vertex to its last -- the root is the start of each line (if Root Group
              is given, points in the group are used as starts: the polyline walks from the end in the group towards the other)
    network   shortest paths over the whole edge network from the points in Root Group (Dijkstra by edge length); each point's "parent"
              is the previous point on its shortest path. With several roots each point belongs to its nearest root
Then along the tree:
    copy       value = value at the root (copies the root's attribute all the way down)
    sum        value = sum of the attribute along the path from the root to this point (both ends included)
    distance   value = path length from the root to this point (accumulated like sum, but adding edge lengths; no Attribute needed)
    average    value = average of the attribute along the path (sum / number of points on the path)
Unreachable points (not connected to any root) get 0 and go into the point group Unreached Group.
The "falloff" kind of AttribFade is a different thing (weights by distance, no accumulation).

━━ pcg100: the five Houdini-semantics modes (appended at the end of Operation; the old four are unchanged)
The old four are not Houdini's Operations (old sum includes the point itself, Houdini's Total doesn't, and the root is 0). New modes:
    transport            value = parent's value; root takes New Root Value (zero / hold)
    transport_from_root  value = root's value; root takes New Root Value
    total                value = sum of ancestors' values (excluding itself, root = 0). Integrate a Constant Value treats each point's value as 1,
                         Scale by Edge Length further multiplies by edge length -- both on gives the distance along edges
    maximum / minimum    value = max / min over itself and its ancestors; the root keeps its own value
Also added: Direction (forward root -> tip / backward tip -> root, multiple children combined by Edge Merge Method),
Edge Split Method (forward with several children at a point: copy = each child gets the full value / split = shared equally),
Normalization (per_component = each connected piece normalized to 0-1 separately / global = all together).
Method gains parent_attribute (tree built from parents given by an integer point attribute); network's Root Choice gains
first_point / last_point (start from the lowest / highest point number, then pick the lowest / highest among unreached points as new roots).
"""
from __future__ import annotations

import heapq

import numpy as np

from .core import POINT, PRIM, is_string
from .groups import resolve

ET_OPS = ("distance", "copy", "sum", "average",
          "transport", "transport_from_root", "total", "maximum", "minimum")
H_OPS = ("transport", "transport_from_root", "total", "maximum", "minimum")
ET_METHODS = ("network", "curves", "parent_attribute")
ROOT_CHOICES = ("group", "first_point", "last_point")
DIRECTIONS = ("forward", "backward")
NORMALIZATIONS = ("per_component", "global")
NEW_ROOT_VALUES = ("zero", "hold")
SPLIT_METHODS = ("copy", "split")
MERGE_METHODS = ("add", "maximum", "minimum")


def _network_tree(geo, roots, allowed=None, reseed=None):
    """
    allowed: only walk on these points (Point Group); reseed = "first" / "last": after a round, pick the
    lowest / highest point number among the not-yet-reached (allowed) points as a new root and continue (Root Choice's First / Last Point).
    """
    from .adjacency import adjacency
    n = geo.npoints
    off, nb, w = adjacency(geo, POINT, weighted=True)
    dist = np.full(n, np.inf)
    parent = np.full(n, -1, np.int64)
    root = np.full(n, -1, np.int64)
    depth = np.zeros(n, np.int64)
    done = np.zeros(n, bool)
    ok = np.ones(n, bool) if allowed is None else np.asarray(allowed, bool)
    seeds = list(np.nonzero(roots & ok)[0])
    while True:
        h = []
        for r in seeds:
            dist[r] = 0.0
            root[r] = r
            h.append((0.0, int(r), int(r)))
        heapq.heapify(h)
        _dijkstra(h, off, nb, w, dist, parent, root, done, ok, depth)
        if reseed is None:
            break
        left = np.nonzero(ok & ~done)[0]
        if not len(left):
            break
        seeds = [int(left[0] if reseed == "first" else left[-1])]
    # Sort by distance, then by depth on ties: parents always come before children. With several rounds distance restarts from 0 each round and parent and child are in the same round,
    # so it still holds. Before pcg100 it sorted by distance only, and on zero-length edges (coincident points) a child could come before its parent, losing accumulated values
    order = np.lexsort((depth, np.where(done, dist, np.inf)))
    order = order[done[order]]
    return parent, root, order


def _dijkstra(h, off, nb, w, dist, parent, root, done, ok, depth):
    while h:
        d, p, par = heapq.heappop(h)
        if done[p]:
            continue
        done[p] = True
        for k in range(off[p], off[p + 1]):
            q = int(nb[k])
            if not ok[q]:
                continue
            nd = d + float(w[k])
            # On equal lengths take the parent with the lower point number, so the result is deterministic
            if nd < dist[q] - 1e-12 or (abs(nd - dist[q]) <= 1e-12 and not done[q]
                                        and p < parent[q]):
                dist[q] = nd
                parent[q] = p
                root[q] = root[p]
                depth[q] = depth[p] + 1
                heapq.heappush(h, (nd, q, p))


def _curve_tree(geo, roots, have_roots, prims=None):
    """prims: only walk these curves (Curve Group); None = all."""
    n = geo.npoints
    parent = np.full(n, -1, np.int64)
    root = np.full(n, -1, np.int64)
    order = []
    seen = np.zeros(n, bool)
    for f in range(geo.nprims):
        if prims is not None and not prims[f]:
            continue
        pts = [int(p) for p in geo.prim_points(f)]
        if not pts:
            continue
        if have_roots:
            if roots[pts[-1]] and not roots[pts[0]]:
                pts = pts[::-1]
            elif not roots[pts[0]]:
                continue                            # neither end of this line is a root: unreachable
        r = pts[0]
        if root[r] < 0:
            root[r] = r
            order.append(r)
            seen[r] = True
        for a, b in zip(pts[:-1], pts[1:]):
            if seen[b]:
                continue
            parent[b] = a
            root[b] = root[a] if root[a] >= 0 else r
            order.append(b)
            seen[b] = True
    return parent, root, np.asarray(order, np.int64)


def _parent_tree(geo, parent_attribute, allowed):
    """
    Method = Parent Attribute: each point's parent = an integer point attribute. Points with an invalid point number (out of range / negative), pointing to themselves,
    or whose parent isn't in Point Group become roots; points unreachable from roots (cycles) are not processed.
    """
    n = geo.npoints
    a = geo.get(POINT, str(parent_attribute or "").strip())
    if a is None or a.dtype.kind not in "iu":
        raise KeyError(f"Parent Attribute: no integer point attribute {parent_attribute!r}")
    par = np.asarray(a, np.int64)[:, 0].copy()
    bad = (par < 0) | (par >= n) | (par == np.arange(n))
    par[bad] = -1
    par[(par >= 0) & ~allowed[np.where(par >= 0, par, 0)]] = -1
    parent = np.full(n, -1, np.int64)
    root = np.full(n, -1, np.int64)
    kids = [[] for _ in range(n)]
    for p in np.nonzero(allowed & (par >= 0))[0]:
        kids[par[p]].append(int(p))
    order = []
    for r in np.nonzero(allowed & (par < 0))[0]:
        root[r] = r
        stack = [int(r)]
        while stack:                                # pre-order: parents always come before children
            p = stack.pop()
            order.append(p)
            for c in reversed(kids[p]):
                parent[c] = p
                root[c] = r
                stack.append(c)
    return parent, root, np.asarray(order, np.int64)


def _normalize(out, reached, comp):
    """Linearly normalizes each component to [0, 1] per piece (points with equal comp) or globally (comp all 0); constant pieces get 0."""
    out = out.copy()
    for c in np.unique(comp[reached]):
        m = reached & (comp == c)
        lo, hi = out[m].min(0), out[m].max(0)
        span = hi - lo
        out[m] = np.where(span > 0, (out[m] - lo) / np.where(span > 0, span, 1.0), 0.0)
    return out


def _houdini_ops(operation, A, P, parent, root, order, direction, new_root_value,
                 scale_by_edge_length, split_method, merge_method):
    """The five Houdini-semantics modes, see the module notes. A is each point's value (all 1 with Integrate)."""
    n, nc = A.shape
    out = np.zeros((n, nc))
    kids = np.zeros(n, np.int64)
    np.add.at(kids, parent[order][parent[order] >= 0], 1)
    el = np.ones(n)
    has = parent >= 0
    if scale_by_edge_length:
        el[has] = np.linalg.norm(P[has] - P[parent[has]], axis=1)
    start = A if new_root_value == "hold" else np.zeros_like(A)
    if direction == "forward":
        for p in order:
            q = parent[p]
            if q < 0:
                out[p] = (A[p] if operation in ("maximum", "minimum")
                          else 0.0 if operation == "total" else start[p])
                continue
            div = kids[q] if split_method == "split" else 1
            if operation == "transport":
                out[p] = A[q] / div                  # one step: take the parent's **original** value
            elif operation == "transport_from_root":
                out[p] = out[q] / div
            elif operation == "total":
                out[p] = (out[q] + A[q] * el[p]) / div
            elif operation == "maximum":
                out[p] = np.maximum(A[p], out[q])
            else:
                out[p] = np.minimum(A[p], out[q])
        return out
    # backward: tip -> root. Points without children are starting points; multiple children are combined by merge_method
    # (Maximum / Minimum take extremes by themselves and ignore merge_method)
    if operation in ("maximum", "minimum"):
        merge = np.maximum if operation == "maximum" else np.minimum
    else:
        merge = {"add": np.add, "maximum": np.maximum, "minimum": np.minimum}[merge_method]
    acc = {}
    for p in order[::-1]:
        got = acc.pop(p, None)
        if operation in ("maximum", "minimum"):
            f = np.maximum if operation == "maximum" else np.minimum
            out[p] = A[p] if got is None else f(A[p], got)
        elif got is None:
            out[p] = 0.0 if operation == "total" else start[p]
        else:
            out[p] = got
        q = parent[p]
        if q < 0:
            continue
        if operation == "transport":
            send = A[p]
        elif operation == "transport_from_root":
            send = out[p]
        elif operation == "total":
            send = out[p] + A[p] * el[p]
        else:
            send = out[p]
        acc[q] = send if q not in acc else merge(acc[q], send)
    return out


def edge_transport(geo, attribute="", operation="distance", method="network",
                   root_group="", output="", unreached_group="unreached",
                   direction="forward", root_choice="group", point_group="", curve_group="",
                   parent_attribute="parent", normalization="", new_root_value="zero",
                   integrate_constant=False, scale_by_edge_length=False, split_method="copy",
                   merge_method="add"):
    """
    Returns (geometry, report). Parameters added in pcg100: see the module notes; empty normalization = no normalization (Use Normalization off).
    direction / new_root_value / integrate_constant / scale_by_edge_length / split / merge
    only apply to the five Houdini-semantics modes (H_OPS); the old four keep their old behaviour.
    """
    if operation not in ET_OPS:
        raise ValueError(f"Operation must be one of {ET_OPS}")
    if method not in ET_METHODS:
        raise ValueError(f"Method must be one of {ET_METHODS}")
    for v, ok, what in ((direction, DIRECTIONS, "Direction"), (root_choice, ROOT_CHOICES, "Root Choice"),
                        (new_root_value, NEW_ROOT_VALUES, "New Root Value"),
                        (split_method, SPLIT_METHODS, "Edge Split Method"),
                        (merge_method, MERGE_METHODS, "Edge Merge Method"),
                        (normalization or "global", NORMALIZATIONS, "Normalization")):
        if v not in ok:
            raise ValueError(f"{what} must be one of {ok}")
    n = geo.npoints
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    name = str(attribute).strip()
    hop = operation in H_OPS
    if hop:
        a = geo.get(POINT, name) if name else None
        if integrate_constant and operation == "total":
            ncomp = 1 if a is None or is_string(a) else a.shape[1]
            A = np.ones((n, ncomp))
        elif a is None or is_string(a):
            raise KeyError(f"{operation} needs a numeric point attribute (Attribute); no point attribute '{name}'"
                           f" (Total can turn on Integrate a Constant Value and needs no attribute)")
        else:
            A = np.asarray(a, np.float64)
        ncomp = A.shape[1]
    elif operation == "distance":
        A = None
        ncomp = 1
    else:
        a = geo.get(POINT, name) if name else None
        if a is None or is_string(a):
            raise KeyError(f"{operation} needs a numeric point attribute (Attribute); no point attribute '{name}'"
                           f" (for path length only, use distance, which needs no attribute)")
        A = np.asarray(a, np.float64)
        ncomp = A.shape[1]
    have = bool(str(root_group).strip())
    roots = resolve(geo, POINT, root_group) if have else np.zeros(n, bool)
    allowed = resolve(geo, POINT, point_group)       # empty = all
    if method == "network":
        if root_choice == "group":
            if not roots.any():
                raise ValueError("network mode needs a Root Group (which points to start from)")
            parent, root, order = _network_tree(
                geo, roots, None if allowed.all() else allowed)
        else:
            parent, root, order = _network_tree(
                geo, np.zeros(n, bool), allowed,
                reseed="first" if root_choice == "first_point" else "last")
    elif method == "parent_attribute":
        parent, root, order = _parent_tree(geo, parent_attribute, allowed)
    else:
        prims = resolve(geo, PRIM, curve_group) if str(curve_group).strip() else None
        parent, root, order = _curve_tree(geo, roots, have, prims)
    if hop:
        reached = np.zeros(n, bool)
        reached[order] = True
        out = _houdini_ops(operation, A, P, parent, root, order, direction, new_root_value,
                           scale_by_edge_length, split_method, merge_method)
        src = geo.get(POINT, name) if name else None
        # Float attributes keep their precision; integer attributes are kept only when the result is necessarily integral (Transport / Max / Min, no split, no normalization)
        keep = None
        if src is not None and src.dtype.kind == "f":
            keep = src.dtype
        elif (src is not None and src.dtype.kind in "iu" and not normalization
              and (operation in ("maximum", "minimum") or
                   (operation in ("transport", "transport_from_root") and split_method == "copy"))):
            keep = src.dtype
        return _finish(geo, out, A, root, reached, name, output, unreached_group, normalization,
                       method, keep)
    out = np.zeros((n, ncomp))
    cnt = np.zeros(n)
    reached = np.zeros(n, bool)
    for p in order:                                  # parents always come first
        q = parent[p]
        reached[p] = True
        if q < 0:
            if operation == "distance":
                out[p] = 0.0
            else:
                out[p] = A[p]
            cnt[p] = 1
            continue
        if operation == "copy":
            out[p] = out[q]
        elif operation == "distance":
            out[p] = out[q] + np.linalg.norm(P[p] - P[q])
        else:
            out[p] = out[q] + A[p]
        cnt[p] = cnt[q] + 1
    if operation == "average":
        out = out / np.maximum(cnt, 1)[:, None]
    if normalization:
        out = _normalize(out, reached, _components(geo, method, root, normalization))
    oname = str(output).strip() or (name if operation != "distance" and name
                                    else "transport")
    g = geo.copy()
    dt = np.float32 if A is None or A.dtype.kind == "f" else np.float64
    g.set(POINT, oname, out.astype(dt), owned=True)
    g.set(POINT, "transport_root", root[:, None].astype(np.int32), owned=True)
    if str(unreached_group).strip():
        g.set_group(POINT, str(unreached_group).strip(), ~reached)
    return g, {"reached": int(reached.sum()), "unreached": int((~reached).sum()),
               "roots": int(len(np.unique(root[reached]))) if reached.any() else 0}


def _components(geo, method, root, normalization):
    """Pieces for Normalization: global = one piece; per_component = by connected piece (parent_attribute has no edges, so by tree)."""
    if normalization == "global":
        return np.zeros(geo.npoints, np.int64)
    if method == "parent_attribute":
        return root.copy()
    from .topology import connectivity
    return np.asarray(connectivity(geo, POINT, "_c").get(POINT, "_c"), np.int64).reshape(-1)


def _finish(geo, out, A, root, reached, name, output, unreached_group, normalization, method,
            keep_dtype):
    """keep_dtype: output keeps the input attribute's type (integer attributes stay integers under Transport / Max / Min)."""
    if normalization:
        out = _normalize(out, reached, _components(geo, method, root, normalization))
    oname = str(output).strip() or name or "transport"
    g = geo.copy()
    g.set(POINT, oname, out.astype(keep_dtype if keep_dtype is not None else np.float32),
          owned=True)
    g.set(POINT, "transport_root", root[:, None].astype(np.int32), owned=True)
    if str(unreached_group).strip():
        g.set_group(POINT, str(unreached_group).strip(), ~reached)
    return g, {"reached": int(reached.sum()), "unreached": int((~reached).sum()),
               "roots": int(len(np.unique(root[reached]))) if reached.any() else 0}
