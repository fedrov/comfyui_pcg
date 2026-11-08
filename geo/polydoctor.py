"""
PolyDoctor (Houdini semantics, pcg100 s7): diagnose polygon problems item by item, each Ignore / Mark / Repair.

This plugin used to point PolyDoctor at PCG_Clean -- Clean only has "fix" toggles, no "mark / report"; and Fuse
Distance / Remove Unused Points are Clean's parameters. Putting both in one panel would be confusing (Clean's toggles alongside
PolyDoctor's three-way menus), so a separate node is added and Clean is left untouched.

    Ignore  this item is not checked
    Mark    polygons found get valid_poly = 0 (point problems: valid_pt = 0)
    Repair  fix; changed polygons get repaired_poly = 1, valid_poly = 1 (points: repaired_pt = 1)

Only closed polygons are examined (PRIM_POLY and closed); polylines and other prims pass through unchanged with valid = 1.
Repairs run one pass in a fixed order; if a pass changed anything another pass runs, up to Max Passes (docs: repairs may introduce new problems).
See each function for how each item is judged; where the docs are unclear, our own definition is written in the function's docstring.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY
from .ops import delete_prims
from .topology import topology
from . import facet as _fc

PD_MODES = ("ignore", "mark", "repair")
PD_MARK_ONLY = ("ignore", "mark")

_V, _R = "__pd_valid", "__pd_rep"           # markers that follow prims during processing
_VP, _RP = "__pd_vpt", "__pd_rpt"           # markers that follow points


# ═══════════════════════════════════════════════════════════ small helpers
def _is_poly(g):
    return g.prim_closed & (g.prim_type == PRIM_POLY)


def _rebuild(g, items):
    """
    items: [(source prim, vertex index array)...] -> new geometry. Points unchanged; vertex attributes / groups carried by vertex index,
    prim attributes / groups carried by source prim (faces split off all inherit the source face's).
    """
    out = Geometry()
    out._resize_points(g.npoints)
    for k, v in g.attribs[POINT].items():
        out.set(POINT, k, v, owned=False)
    for k, v in g.groups[POINT].items():
        out.set_group(POINT, k, v)
    src = np.array([s for s, _ in items], np.int64)
    vids = (np.concatenate([np.asarray(v, np.int64) for _, v in items])
            if items else np.zeros(0, np.int64))
    sizes = np.array([len(v) for _, v in items], np.int64)
    off = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)
    out.set_topology(g.vertex_point[vids].astype(np.int32), off,
                     g.prim_closed[src] if len(src) else np.zeros(0, bool),
                     g.prim_type[src] if len(src) else np.zeros(0, np.uint8))
    for k, v in g.attribs[VERTEX].items():
        out.set(VERTEX, k, v[vids], owned=True)
    for k, v in g.groups[VERTEX].items():
        out.set_group(VERTEX, k, np.asarray(v)[vids])
    for k, v in g.attribs[PRIM].items():
        out.set(PRIM, k, v[src], owned=True)
    for k, v in g.groups[PRIM].items():
        out.set_group(PRIM, k, np.asarray(v)[src])
    for k, v in g.edge_groups.items():
        out.set_edge_group(k, v)
    out.attribs[DETAIL] = dict(g.attribs[DETAIL])
    return out


def _flag(g, cls, name, mask, value):
    a = np.asarray(g.get(cls, name)).copy()
    a[np.asarray(mask, bool), 0] = value
    g.set(cls, name, a, owned=True)


def _areas(g):
    from .ops import prim_normals
    return np.linalg.norm(prim_normals(g, normalize=False), axis=1)


def _perimeters(g):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    out = np.zeros(g.nprims)
    for i in range(g.nprims):
        Q = P[g.prim_points(i)]
        if len(Q) > 1:
            out[i] = np.linalg.norm(Q - np.roll(Q, -1, 0), axis=1).sum()
    return out


def _poly_edges(g):
    """Polygon edges: (edge number -> two endpoints, list of edge numbers per polygon)."""
    poly = _is_poly(g)
    pairs, owner = [], []
    for i in np.nonzero(poly)[0]:
        p = g.prim_points(int(i))
        for a, b in zip(p, np.roll(p, -1)):
            if a != b:
                pairs.append((min(a, b), max(a, b)))
                owner.append(int(i))
    if not pairs:
        return np.zeros((0, 2), np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64)
    pairs = np.asarray(pairs, np.int64)
    E, inv = np.unique(pairs, axis=0, return_inverse=True)
    return E, inv.reshape(-1), np.asarray(owner, np.int64)


def _collapse_points(g, clusters):
    """clusters: class number per point (-1 = do not move). Points in the same class move to their mean position and are welded into one."""
    n = g.npoints
    cl = np.asarray(clusters, np.int64)
    key = np.where(cl >= 0, cl, -1 - np.arange(n))      # points that do not move are each their own class
    P = np.asarray(g.get(POINT, "P"), np.float64).copy()
    m = cl >= 0
    if m.any():
        u, inv = np.unique(cl[m], return_inverse=True)
        cnt = np.bincount(inv)
        for d in range(3):
            P[np.nonzero(m)[0], d] = (np.bincount(inv, weights=P[m, d]) / cnt)[inv]
    g = g.copy()
    g.set(POINT, "P", P.astype(np.float32), owned=True)
    _flag(g, POINT, _RP, m, 1)
    return _fc._weld(g, key[:, None])


# ═══════════════════════════════════════════════════════════ per-item checks / repairs
def ill_formed(g):
    """
    Docs: "overlapping or degenerate vertices". Defined here as: a polygon with fewer than 3 corners, two adjacent
    corners being the same point (or coincident positions), the same point appearing twice or more in the polygon, or zero area.
    """
    P = np.asarray(g.get(POINT, "P"), np.float64)
    area = _areas(g)
    bad = np.zeros(g.nprims, bool)
    for i in np.nonzero(_is_poly(g))[0]:
        p = g.prim_points(int(i))
        if len(p) < 3 or len(np.unique(p)) != len(p) or area[i] <= 1e-14:
            bad[i] = True
            continue
        Q = P[p]
        if (np.linalg.norm(Q - np.roll(Q, -1, 0), axis=1) <= 1e-12).any():
            bad[i] = True
    return bad


def repair_ill_formed(g, bad):
    """Remove adjacent duplicate corners (same point or coincident position); delete what remains unable to form a face (< 3, still duplicate points, area 0)."""
    P = np.asarray(g.get(POINT, "P"), np.float64)
    items, fixed = [], []
    for i in range(g.nprims):
        v = np.arange(g.prim_offset[i], g.prim_offset[i + 1])
        if not bad[i]:
            items.append((i, v))
            continue
        pts = g.vertex_point[v]
        keep = []
        for k in range(len(v)):
            if keep and (pts[k] == g.vertex_point[keep[-1]]
                         or np.linalg.norm(P[pts[k]] - P[g.vertex_point[keep[-1]]]) <= 1e-12):
                continue
            keep.append(v[k])
        while len(keep) > 1 and (g.vertex_point[keep[0]] == g.vertex_point[keep[-1]] or np.linalg.norm(
                P[g.vertex_point[keep[0]]] - P[g.vertex_point[keep[-1]]]) <= 1e-12):
            keep.pop()
        kp = g.vertex_point[keep]
        if len(keep) < 3 or len(np.unique(kp)) != len(kp):
            continue                                     # deleted
        Q = P[kp]
        nrm = np.cross(Q - Q.mean(0), np.roll(Q, -1, 0) - Q.mean(0)).sum(0)
        if np.linalg.norm(nrm) <= 1e-14:
            continue
        items.append((i, np.asarray(keep)))
        fixed.append(len(items) - 1)
    out = _rebuild(g, items)
    _flag(out, PRIM, _R, np.isin(np.arange(out.nprims), fixed), 1)
    return out


def five_plus(g):
    """Polygons with 5 or more edges."""
    return _is_poly(g) & (g.prim_sizes() >= 5)


def _split_poly(Q):
    """Split by local indices: convex polygons are fanned from point 0 into quads (possibly one triangle left at the end), otherwise ear-clipped into triangles."""
    from .divide import _plane_basis, _is_convex, _ear_clip
    V = _plane_basis(Q)
    n = len(Q)
    if _is_convex(V):
        out, k = [], 1
        while k + 2 <= n - 1:
            out.append((0, k, k + 1, k + 2))
            k += 2
        if k + 1 <= n - 1:
            out.append((0, k, k + 1))
        return out
    return _ear_clip(V)


def repair_split(g, bad):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    items, fixed = [], []
    for i in range(g.nprims):
        v = np.arange(g.prim_offset[i], g.prim_offset[i + 1])
        if not bad[i]:
            items.append((i, v))
            continue
        for t in _split_poly(P[g.vertex_point[v]]):
            items.append((i, v[list(t)]))
            fixed.append(len(items) - 1)
    out = _rebuild(g, items)
    _flag(out, PRIM, _R, np.isin(np.arange(out.nprims), fixed), 1)
    return out


def non_convex(g):
    """Non-convex quads (docs: non-convex quads left after handling 5+ sided ones). Convexity judged in the best-fit plane."""
    from .divide import _plane_basis, _is_convex
    P = np.asarray(g.get(POINT, "P"), np.float64)
    bad = np.zeros(g.nprims, bool)
    for i in np.nonzero(_is_poly(g) & (g.prim_sizes() == 4))[0]:
        bad[i] = not _is_convex(_plane_basis(P[g.prim_points(int(i))]))
    return bad


def overlapping(g, pair):
    """
    Polygons with the same point set (regardless of start point and winding). pair off: the first is kept and the rest are problems; pair on: the whole set counts
    (docs, Pair Overlaps: delete both).
    """
    from .meshfix import _dup_prims
    poly = _is_poly(g)
    keep = _dup_prims(g)
    bad = ~keep & poly
    if pair and bad.any():
        keys = {}
        for i in np.nonzero(poly)[0]:
            keys.setdefault(tuple(sorted(g.prim_points(int(i)).tolist())), []).append(int(i))
        for ids in keys.values():
            if len(ids) > 1:
                bad[ids] = True
    return bad


def small_area_local(g, threshold):
    """area / largest area among edge-sharing neighbours < threshold (docs example: 0.1 = less than a tenth of the neighbours)."""
    area = _areas(g)
    E, inv, owner = _poly_edges(g)
    bad = np.zeros(g.nprims, bool)
    if not len(E):
        return bad
    mx = np.zeros(g.nprims)
    for e in range(len(E)):
        fs = np.unique(owner[inv == e])
        if len(fs) < 2:
            continue
        for f in fs:
            others = fs[fs != f]
            mx[f] = max(mx[f], area[others].max())
    poly = _is_poly(g)
    bad = poly & (mx > 0) & (area < float(threshold) * mx)
    return bad


def repair_collapse_prims(g, bad):
    """Docs: "collapse" the face to a point -- its points move to the center and are welded into one, then collapsed faces are cleaned as for Ill-Formed."""
    cl = np.full(g.npoints, -1, np.int64)
    pairs = []
    for i in np.nonzero(bad)[0]:
        p = g.prim_points(int(i))
        pairs += [(p[0], q) for q in p[1:]]
    lab, _ = _fc._labels(g.npoints, np.asarray(pairs, np.int64).reshape(-1, 2))
    touched = np.zeros(g.npoints, bool)
    for a, b in pairs:
        touched[a] = touched[b] = True
    cl[touched] = lab[touched]
    affected = np.array([touched[g.prim_points(i)].any() for i in range(g.nprims)], bool)
    _flag(g, PRIM, _R, affected, 1)
    g = _collapse_points(g, cl)
    return repair_ill_formed(g, ill_formed(g))


def non_uniform(g, threshold):
    """
    Docs: Uniformity Threshold 0 = very non-uniform, 1 = circle. Here the isoperimetric quotient 4piA / perimeter^2 is used (circle = 1, square
    ~ 0.785, equilateral triangle ~ 0.605, thin sliver -> 0) -- the docs give no formula, this is our own choice.
    """
    area, per = _areas(g), _perimeters(g)
    q = np.where(per > 0, 4 * np.pi * area / np.maximum(per, 1e-300) ** 2, 0.0)
    return _is_poly(g) & (q < float(threshold))


def short_edges(g, global_threshold=None, local_threshold=None):
    """
    Returns (endpoint pairs of short edges (k,2), whether each polygon contains a short edge).
    global: edge length < threshold x bounding box diagonal (docs: "1 = the diameter of the bounding sphere"; the bounding sphere is taken as the bounding box's circumscribed sphere).
    local: edge length < threshold x the longest edge of the polygons containing this edge (the docs only say "compared to adjacent edges").
    """
    E, inv, owner = _poly_edges(g)
    if not len(E):
        return E, np.zeros(g.nprims, bool)
    P = np.asarray(g.get(POINT, "P"), np.float64)
    L = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    if global_threshold is not None:
        diag = np.linalg.norm(P.max(0) - P.min(0)) if len(P) else 0.0
        bad_e = L < float(global_threshold) * diag
    else:
        longest = np.zeros(g.nprims)
        np.maximum.at(longest, owner, L[inv])
        ref = np.zeros(len(E))
        np.maximum.at(ref, inv, longest[owner])
        bad_e = L < float(local_threshold) * ref
    polys = np.zeros(g.nprims, bool)
    polys[owner[bad_e[inv]]] = True
    return E[bad_e], polys


def repair_short_edges(g, E, polys):
    """Docs: short edges collapse to their midpoint. A chain of connected short edges collapses together to the mean position of its points."""
    if not len(E):
        return g
    lab, _ = _fc._labels(g.npoints, E)
    cl = np.full(g.npoints, -1, np.int64)
    pts = np.unique(E.reshape(-1))
    cl[pts] = lab[pts]
    g = g.copy()
    _flag(g, PRIM, _R, polys, 1)
    g = _collapse_points(g, cl)
    return repair_ill_formed(g, ill_formed(g))


def disconnected_points(g):
    """Points not referenced by any prim (docs: "not belonging to any polygon"; points used by polylines do not count)."""
    used = np.zeros(g.npoints, bool)
    used[g.vertex_point] = True
    return ~used


def nonmanifold_points(g):
    """
    Non-manifold points: the surrounding faces do not form a disc / half-disc. Two kinds are recognized here: bowties (a point with several mutually unconnected fans of faces),
    and points on edges shared by 3 or more faces.
    """
    t = topology(g)
    bad = np.zeros(g.npoints, bool)
    if not g.nvertices or not t.nedges:
        return bad
    # Edges shared by 3+ faces need no separate check: such edges do not take part in the pairing below, so the corners at their ends necessarily split into several classes
    nxt = g.next_corner()
    two = np.nonzero(t.edge_count == 2)[0]
    h1 = t.edge_he[t.edge_he_off[two]]
    h2 = t.edge_he[t.edge_he_off[two] + 1]
    vp = g.vertex_point
    same = vp[h1] == vp[h2]
    pa = np.where(same, h2, nxt[h2])
    pb = np.where(same, nxt[h2], h2)
    pairs = np.concatenate([np.stack([h1, pa], 1), np.stack([nxt[h1], pb], 1)])
    cls, _ = _fc._labels(g.nvertices, pairs)
    uniq = np.unique(np.stack([vp, cls], 1), axis=0)
    nclass = np.bincount(uniq[:, 0], minlength=g.npoints)
    bad |= nclass > 1
    return bad


# ═══════════════════════════════════════════════════════════ main function
def self_intersecting(g):
    """(nprims,) bool: polygons an edge of another polygon passes through, or whose edges pass through another
    polygon (Intersection Analysis on the mesh itself; faces sharing a point are not tested against each other)."""
    from .intersectanalysis import intersection_analysis
    bad = np.zeros(g.nprims, bool)
    if not g.nprims:
        return bad
    pts, _ = intersection_analysis(g, None, input_attr="", prim_attr="__pd_si", uvw_attr="")
    if pts.npoints:
        bad[np.asarray(pts.get(POINT, "__pd_si"), np.int64).reshape(-1)] = True
    return bad


def polydoctor(geo, max_passes=10, ill_formed_mode="repair", five_plus_mode="ignore",
               non_convex_mode="ignore", overlapping_mode="repair", pair_overlaps=False,
               local_area_mode="ignore", local_area_threshold=0.1,
               non_uniform_mode="ignore", uniformity_threshold=0.1,
               global_edge_mode="ignore", global_edge_threshold=1e-3,
               local_edge_mode="ignore", local_edge_threshold=0.1,
               disconnected_mode="repair", nonmanifold_mode="ignore",
               valid_poly="valid_poly", repaired_poly="repaired_poly",
               valid_pt="valid_pt", repaired_pt="repaired_pt", create_groups=False,
               self_intersecting_mode="ignore"):
    modes = dict(ill_formed_mode=ill_formed_mode, five_plus_mode=five_plus_mode,
                 non_convex_mode=non_convex_mode, overlapping_mode=overlapping_mode,
                 local_area_mode=local_area_mode, global_edge_mode=global_edge_mode,
                 local_edge_mode=local_edge_mode, disconnected_mode=disconnected_mode,
                 nonmanifold_mode=nonmanifold_mode)
    for k, v in modes.items():
        if v not in PD_MODES:
            raise ValueError(f"{k} must be one of {PD_MODES}")
    if non_uniform_mode not in PD_MARK_ONLY:
        raise ValueError(f"Non-Uniform must be one of {PD_MARK_ONLY} (the docs do not say how to repair it)")
    if self_intersecting_mode not in PD_MARK_ONLY:
        raise ValueError(f"Self-Intersecting must be one of {PD_MARK_ONLY}")
    g = geo.copy()
    g.set(PRIM, _V, np.ones((g.nprims, 1), np.int32), owned=True)
    g.set(PRIM, _R, np.zeros((g.nprims, 1), np.int32), owned=True)
    g.set(POINT, _VP, np.ones((g.npoints, 1), np.int32), owned=True)
    g.set(POINT, _RP, np.zeros((g.npoints, 1), np.int32), owned=True)
    rep = {"passes": 0}
    cnt = {}

    def note(k, m):
        cnt[k] = cnt.get(k, 0) + int(np.count_nonzero(m))

    for _ in range(max(1, int(max_passes))):
        rep["passes"] += 1
        changed = False

        def prim_step(key, mode, bad, repair):
            nonlocal g, changed
            if mode == "ignore" or not bad.any():
                return
            note(key, bad)
            if mode == "mark":
                _flag(g, PRIM, _V, bad, 0)
            else:
                g = repair(g, bad)
                changed = True

        if ill_formed_mode != "ignore":
            prim_step("ill_formed", ill_formed_mode, ill_formed(g), repair_ill_formed)
        if five_plus_mode != "ignore":
            prim_step("five_plus", five_plus_mode, five_plus(g), repair_split)
        if non_convex_mode != "ignore":
            prim_step("non_convex", non_convex_mode, non_convex(g), repair_split)
        if overlapping_mode != "ignore":
            prim_step("overlapping", overlapping_mode, overlapping(g, pair_overlaps),
                      lambda gg, b: delete_prims(gg, ~b, keep_points=True))
        if local_area_mode != "ignore":
            prim_step("local_small_area", local_area_mode,
                      small_area_local(g, local_area_threshold), repair_collapse_prims)
        if non_uniform_mode == "mark":
            b = non_uniform(g, uniformity_threshold)
            note("non_uniform", b)
            _flag(g, PRIM, _V, b, 0)
        for key, mode, kw in (("global_small_edges", global_edge_mode,
                               dict(global_threshold=global_edge_threshold)),
                              ("local_small_edges", local_edge_mode,
                               dict(local_threshold=local_edge_threshold))):
            if mode == "ignore":
                continue
            E, polys = short_edges(g, **kw)
            if not len(E):
                continue
            note(key, polys)
            if mode == "mark":
                # Docs: edge problems are marked on the polygons containing the edge
                _flag(g, PRIM, _V, polys, 0)
            else:
                g = repair_short_edges(g, E, polys)
                changed = True
        if disconnected_mode != "ignore":
            b = disconnected_points(g)
            if b.any():
                note("disconnected_points", b)
                if disconnected_mode == "mark":
                    _flag(g, POINT, _VP, b, 0)
                else:
                    g = delete_prims(g, np.ones(g.nprims, bool), keep_points=False)
                    changed = True
        if nonmanifold_mode != "ignore":
            b = nonmanifold_points(g)
            if b.any():
                note("nonmanifold_points", b)
                if nonmanifold_mode == "repair":
                    from .meshfix import _split_bowties
                    before = g.npoints
                    _flag(g, POINT, _RP, b, 1)
                    g, _ = _split_bowties(g)
                    changed = changed or g.npoints != before
                # Mark mode marks all as invalid; Repair mode marks what remains after repair (points that could not be split apart) as invalid
                left = nonmanifold_points(g)
                _flag(g, POINT, _VP, left, 0)
        if not changed:                     # every repair changes topology; if nothing was repaired, no need for another pass
            break

    # pcg122: polygons that pass through other polygons of the same mesh (mark only -- which of the two to change is
    # a modelling decision). Checked once, on the repaired result.
    if self_intersecting_mode == "mark":
        b = self_intersecting(g)
        note("self_intersecting", b)
        _flag(g, PRIM, _V, b, 0)

    # Repaired faces / points count as valid (docs: repaired is a subset of valid)
    r = np.asarray(g.get(PRIM, _R))[:, 0] > 0
    v = (np.asarray(g.get(PRIM, _V))[:, 0] > 0) | r
    rp = np.asarray(g.get(POINT, _RP))[:, 0] > 0
    vp = (np.asarray(g.get(POINT, _VP))[:, 0] > 0) | rp
    for cls, nm in ((PRIM, _V), (PRIM, _R), (POINT, _VP), (POINT, _RP)):
        g.attribs[cls].pop(nm, None)
    for cls, name, val in ((PRIM, valid_poly, v), (PRIM, repaired_poly, r),
                           (POINT, valid_pt, vp), (POINT, repaired_pt, rp)):
        nm = str(name).strip()
        if not nm:
            continue
        g.set(cls, nm, val.astype(np.int32)[:, None], owned=True)
        if create_groups:
            g.set_group(cls, nm + "_grp", val)
    rep["found"] = cnt
    rep["invalid_polys"] = int((~v).sum())
    rep["repaired_polys"] = int(r.sum())
    rep["invalid_points"] = int((~vp).sum())
    rep["repaired_points"] = int(rp.sum())
    rep["points"] = [geo.npoints, g.npoints]
    rep["prims"] = [geo.nprims, g.nprims]
    return g, rep
