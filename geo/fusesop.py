"""
Fuse SOP -- snap points together by distance, then decide whether to actually weld them.

Houdini's Fuse has three sections, copied here:

    Snap    which points count as "the same point", and which position they snap to
    Fuse    whether to actually merge topology, and how to clean up degenerate primitives afterwards
    Output  which groups to produce, whether to recompute normals

ops.fuse()'s grid-quantized version is **not enough**; it's just a special case of this node:
after quantizing to a grid of size d, two points 0.6d apart but on either side of a cell boundary don't merge, while points 1.7d apart
that fall in the same cell do. Real "pair within radius" needs a neighbourhood search.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Neighbourhood search: uniform grid hashing, no scipy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With the cell size set to the snap distance, all candidate neighbours of a point must lie in its own cell plus the surrounding
26 cells. The approach: sort the target points by cell hash into a CSR, then look up 27 buckets for each source point --
fully vectorized, with variable-length buckets expanded by reusing ops._gather_blocks.

Hash collisions only add candidate pairs, never miss any; the final distance test filters them out.
What really needs guarding against is **a distance set too large**: with big cells, points per cell explode and candidate pairs grow quadratically.
So there's an explicit cap; hitting it raises an error telling you to reduce the distance, instead of letting the machine hang.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One deviation from Houdini
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strictly speaking Houdini's snap is "each point finds one target point of its own", with chain contagion as a side effect;
here we compute the **transitive closure** directly (A next to B, B next to C: all three merge), because that's what the user
wants when pressing Fuse, and it's the only way to get a result that is independent of point order and reproducible.
The Using menu thus becomes "who represents a cluster"; the semantics line up.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import (_gather_blocks, delete_prims, delete_points, compute_normals,
                  match_names)
from .addsop import remove_repeated as _remove_repeated, remove_unused as _remove_unused

MAX_PAIRS = 40_000_000          # candidate pair cap, so a too-large distance doesn't eat all the memory


# ═══════════════════════════════════════════════════════════ neighbourhood search
def _hash3(c):
    return (c[:, 0] * 73856093) ^ (c[:, 1] * 19349663) ^ (c[:, 2] * 83492791)


def _pairs_within(A, B, d, same=False):
    """
    Return all (i, j) with |A[i] - B[j]| <= d. With same=True, A and B are the same point set,
    and only i < j is kept (a point doesn't pair with itself, and a pair isn't counted twice).
    """
    if len(A) == 0 or len(B) == 0 or d <= 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    cell = float(d)
    ca = np.floor(A / cell).astype(np.int64)
    cb = np.floor(B / cell).astype(np.int64)

    kb = _hash3(cb)
    order = np.argsort(kb, kind="stable")
    kb_s = kb[order]
    uniq, starts = np.unique(kb_s, return_index=True)
    ends = np.append(starts[1:], len(kb_s)).astype(np.int64)
    starts = starts.astype(np.int64)

    ia_all, ib_all, total = [], [], 0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k = _hash3(ca + np.array([dx, dy, dz], np.int64))
                pos = np.searchsorted(uniq, k)
                pos_c = np.clip(pos, 0, max(len(uniq) - 1, 0))
                hit = np.nonzero((pos < len(uniq)) & (uniq[pos_c] == k))[0]
                if not len(hit):
                    continue
                p = pos[hit]
                cnt = ends[p] - starts[p]
                n = int(cnt.sum())
                if n == 0:
                    continue
                total += n
                if total > MAX_PAIRS:
                    raise MemoryError(
                        "Fuse candidate point pairs exceed the cap -- snap distance is set too large "
                        "relative to the point density. Reduce the distance, or narrow the scope with group first.")
                ia_all.append(np.repeat(hit, cnt))
                ib_all.append(order[_gather_blocks(starts[p], cnt)])
    if not ia_all:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    ia = np.concatenate(ia_all)
    ib = np.concatenate(ib_all)
    if same:
        keep = ia < ib
        ia, ib = ia[keep], ib[keep]
    dist = np.linalg.norm(A[ia] - B[ib], axis=1)
    keep = dist <= d
    return ia[keep], ib[keep]


def _labels(n, pairs):
    """Connected component labelling. Same pointer jumping as topology.connectivity."""
    lab = np.arange(n, dtype=np.int64)
    if len(pairs):
        a, b = pairs[0], pairs[1]
        for _ in range(64):
            prev = lab
            m = np.minimum(lab[a], lab[b])
            lab = lab.copy()
            np.minimum.at(lab, a, m)
            np.minimum.at(lab, b, m)
            lab = lab[lab]
            if np.array_equal(lab, prev):
                break
    _, inv = np.unique(lab, return_inverse=True)
    inv = inv.reshape(-1)
    return inv, (int(inv.max()) + 1 if n else 0)


# ═══════════════════════════════════════════════════════════ extra pairing conditions
def _filter_match(geo, ia, ib, name, condition, tol):
    """Match Attribute: only two points whose attribute values are equal (or unequal) may snap together."""
    name = str(name).strip()
    if not name or not len(ia):
        return ia, ib
    a = geo.get(POINT, name)
    if a is None:
        have = sorted(geo.attribs[POINT].keys())
        raise KeyError(f"No point attribute '{name}'. Existing: {have or '(none)'}")
    if is_string(a):
        eq = a[ia, 0] == a[ib, 0]
    else:
        eq = np.all(np.abs(a[ia].astype(np.float64) - a[ib].astype(np.float64))
                    <= float(tol), axis=1)
    keep = eq if condition == "equal" else ~eq
    return ia[keep], ib[keep]


def _radius_ok(geo, ia, ib, P, name, base_dist, use_base):
    """
    Radius Attribute: each point carries its own snap radius. A pair's criterion takes the larger of the two radii --
    "my radius reaches you" counts, consistent with Houdini; only when neither reaches does it not count.
    """
    name = str(name).strip()
    if not name or not len(ia):
        return ia, ib
    r = geo.get(POINT, name)
    if r is None:
        have = sorted(geo.attribs[POINT].keys())
        raise KeyError(f"No point attribute '{name}'. Existing: {have or '(none)'}")
    r = r[:, 0].astype(np.float64)
    lim = np.maximum(r[ia], r[ib])
    if use_base:
        lim = np.maximum(lim, float(base_dist))
    d = np.linalg.norm(P[ia] - P[ib], axis=1)
    keep = d <= lim
    return ia[keep], ib[keep]


def _pick_rep(labels, k, P, rule):
    """Pick the representative of a cluster."""
    n = len(labels)
    idx = np.arange(n, dtype=np.int64)
    rep = np.zeros(max(k, 1), np.int64)
    if rule == "greatest_point_number":
        rep[labels] = idx                       # write forward, the largest writes last
    elif rule == "closest":
        # The one closest to the cluster center. The natural counterpart of "Closest Target" under transitive-closure semantics,
        # and independent of point numbering -- a different Sort upstream won't make the result jump
        c = np.zeros((max(k, 1), 3), np.float64)
        np.add.at(c, labels, P)
        c /= np.maximum(np.bincount(labels, minlength=max(k, 1)), 1)[:, None]
        d = np.linalg.norm(P - c[labels], axis=1)
        order = np.argsort(d, kind="stable")[::-1]   # far ones written first, near ones overwrite
        rep[labels[order]] = order
    else:
        rep[labels[::-1]] = idx[::-1]           # write in reverse, the smallest writes last
    return rep


def _apply_positions(geo, labels, k, rep, sel, mode, snap_attribs):
    """Set each point's new position in its cluster per Output Positions, snapping the other specified attributes along the way."""
    g = geo.copy()
    if mode == "keep" or k == 0:
        return g
    names = ["P"] + [n for n in match_names(list(geo.attribs[POINT].keys()),
                                            snap_attribs) if n != "P"]
    cnt = np.maximum(np.bincount(labels, minlength=k), 1)[:, None]
    for name in names:
        v = geo.get(POINT, name)
        if v is None or is_string(v):
            continue
        w = np.array(v, dtype=np.float64)
        if mode == "average":
            acc = np.zeros((k, w.shape[1]))
            np.add.at(acc, labels, w)
            new = acc / cnt
        else:                                   # target: take the representative's value
            new = w[rep]
        w[sel] = new[labels[sel]]
        g.set(POINT, name, w.astype(v.dtype), owned=True)
    return g


def _weld(geo, labels, k, keep_all_points):
    """
    Merge points by cluster number. With keep_all_points=True no point is deleted; the displaced ones become orphan points
    (corresponds to Houdini's Keep Fused Points).
    """
    # each cluster takes its lowest-numbered point as source; new point numbers follow the original point order -- reproducible
    src = np.zeros(max(k, 1), np.int64)
    src[labels[::-1]] = np.arange(len(labels) - 1, -1, -1)
    order = np.argsort(src, kind="stable")
    remap = np.empty(max(k, 1), np.int32)
    remap[order] = np.arange(max(k, 1), dtype=np.int32)
    idx = remap[labels]

    if keep_all_points:
        # point table unchanged, only the topology is redirected to the representatives -- displaced points remain, just unreferenced
        rep_pt = src[labels].astype(np.int32)
        g = geo.copy()
        g.set_topology(rep_pt[geo.vertex_point], geo.prim_offset,
                       geo.prim_closed, geo.prim_type)
        eg = geo.remap_edge_groups(rep_pt, geo.npoints)
        g.edge_groups = {kk: (v[v[:, 0] != v[:, 1]] if len(v) else v)
                         for kk, v in eg.items()}
        return g

    out = Geometry()
    out._resize_points(k)
    keep = src[order]
    for kk, v in geo.attribs[POINT].items():
        out.set(POINT, kk, v[keep], owned=True)
    out.set_topology(idx[geo.vertex_point], geo.prim_offset, geo.prim_closed,
                     geo.prim_type)
    for cls in (VERTEX, PRIM):
        for kk, v in geo.attribs[cls].items():
            out.set(cls, kk, v)
        for kk, v in geo.groups[cls].items():
            out.set_group(cls, kk, v)
    for kk, v in geo.groups[POINT].items():     # in the group if any point in the cluster was
        m = np.zeros(k, bool)
        np.logical_or.at(m, idx, v)
        out.set_group(POINT, kk, m)
    out.prim_data = {kk: dict(v) for kk, v in geo.prim_data.items()}
    eg = geo.remap_edge_groups(idx.astype(np.int32), k)
    for kk, v in eg.items():
        out.set_edge_group(kk, v[v[:, 0] != v[:, 1]] if len(v) else v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


def _cleanup(g, repeated, degen_unused, all_unused):
    """The three cleanup toggles of the Fuse section."""
    if repeated:
        before = np.zeros(g.npoints, bool)
        if g.nvertices:
            before[g.vertex_point] = True
        g = _remove_repeated(g)
        if g.nprims:                            # prims that can't form a primitive after dedup
            s = g.prim_sizes()
            keep = s >= np.where(g.prim_closed, 3, 2)
            if not keep.all():
                # keep_points: points orphaned here are the "degenerate" ones, removed below only when that toggle is
                # on. Letting delete_prims drop them changed the point count under `before` (a crash when a large
                # snap distance collapsed every face)
                g = delete_prims(g, keep, keep_points=True)
        if degen_unused:
            now = np.zeros(g.npoints, bool)
            if g.nvertices:
                now[g.vertex_point] = True
            lost = before & ~now
            if lost.any():
                g = delete_points(g, ~lost)
    if all_unused:
        g = _remove_unused(g)
    return g


# ═════════════════════════════════════════════════════ clustering for the three snap modes
def _plan_near(src, P, sel, d, use_d, radius_attrib, match_attrib,
               match_condition, match_tolerance):
    """Snap to itself: pair within radius -> cluster by transitive closure."""
    si = np.nonzero(sel)[0]
    # The neighbourhood search radius must cover the **criterion**'s upper bound. With Radius Attribute on, the criterion is
    # max(r_i, r_j), possibly far larger than snap distance -- if the search radius isn't enlarged accordingly,
    # those points never become candidates, and the radius test later has nothing to act on
    search = max(d, 1e-12)
    rname = str(radius_attrib).strip()
    if rname:
        r = src.get(POINT, rname)
        if r is not None and len(r):
            search = max(search, float(np.abs(r[:, 0]).max()))
    ia, ib = _pairs_within(P[si], P[si], search, same=True)
    ia, ib = si[ia], si[ib]
    if rname:                                   # filter by the criterion first
        ia, ib = _radius_ok(src, ia, ib, P, rname, d, use_d)
    elif d > 0:
        keep = np.linalg.norm(P[ia] - P[ib], axis=1) <= d
        ia, ib = ia[keep], ib[keep]
    ia, ib = _radius_ok(src, ia, ib, P, radius_attrib, d, use_d)
    ia, ib = _filter_match(src, ia, ib, match_attrib, match_condition,
                           match_tolerance)
    labels, k = _labels(src.npoints, (ia, ib))
    moved = sel & (np.bincount(labels, minlength=k)[labels] > 1)
    return labels, k, moved, P


def _plan_grid(P, sel, size, offset):
    """Snap to grid points; points landing on the same grid point form a cluster."""
    s = np.asarray(size, np.float64).reshape(3)
    o = np.asarray(offset, np.float64).reshape(3)
    s = np.where(s <= 0, 1.0, s)
    q = np.round((P - o) / s) * s + o
    Q = np.where(sel[:, None], q, P)
    _, labels = np.unique(Q, axis=0, return_inverse=True)
    labels = labels.reshape(-1)
    k = int(labels.max()) + 1 if len(labels) else 0
    moved = sel & (np.linalg.norm(Q - P, axis=1) > 0)
    return labels, k, moved, Q


def _plan_target(src, P, sel, other, osel_spec, d, using, output_positions):
    """
    Snap to points of the second input. **No transitive closure** -- the target points are given, each source point picks one,
    and the picking rule is the Using menu. Source points snapped to the same target naturally form a cluster.
    """
    osel = resolve(other, POINT, osel_spec)
    TP = other.get(POINT, "P")[:, :3].astype(np.float64)
    si, ti = np.nonzero(sel)[0], np.nonzero(osel)[0]
    n = src.npoints
    ia, ib = _pairs_within(P[si], TP[ti], max(d, 1e-12))
    if not len(ia):
        return np.arange(n, dtype=np.int64), n, np.zeros(n, bool), P
    ia, ib = si[ia], ti[ib]
    dist = np.linalg.norm(P[ia] - TP[ib], axis=1)
    key = (dist if using == "closest"
           else -ib.astype(np.float64) if using == "greatest_point_number"
           else ib.astype(np.float64))
    order = np.lexsort((key, ia))               # sort by Using within each source point
    ia, ib = ia[order], ib[order]
    first = np.ones(len(ia), bool)
    first[1:] = ia[1:] != ia[:-1]
    ia, ib = ia[first], ib[first]               # each source point keeps only its best target

    Q = P.copy()
    if output_positions != "keep":
        Q[ia] = (0.5 * (P[ia] + TP[ib]) if output_positions == "average"
                 else TP[ib])
    moved = np.zeros(n, bool)
    moved[ia] = True
    # cluster = the source points snapped to the same target; unsnapped ones are each their own cluster
    key2 = np.full(n, -1, np.int64)
    key2[ia] = ib
    _, labels = np.unique(np.where(key2 >= 0, key2, -1 - np.arange(n)),
                          return_inverse=True)
    labels = labels.reshape(-1)
    return labels, int(labels.max()) + 1, moved, Q


# ═══════════════════════════════════════════════════════════════ main entry point
def fuse(geo, target=None, group="", target_group="", modify_target=False,
         snap_to="near_points", using="least_point_number",
         use_snap_distance=True, snap_distance=0.001,
         output_positions="average",
         radius_attrib="", match_attrib="", match_condition="equal",
         match_tolerance=0.0,
         grid_size=(0.1, 0.1, 0.1), grid_offset=(0.0, 0.0, 0.0),
         fuse_snapped=True, keep_fused=False,
         remove_repeated=True, remove_degenerate_unused=True,
         remove_all_unused=False,
         recompute_normals=True, snapped_group="", snapped_to_group="",
         attribs_to_snap="", position_attrib="P"):
    """
    No second input: points in the group snap to each other and merge.
    With a second input: points in the group snap to points on target -- the two geometries don't become one;
    the second input only provides "where to snap". modify_target reverses this: target is what gets modified and output.

    Setting position_attrib to another 3-component attribute means "judge proximity by another set of coordinates" (Houdini's
    Position Attribute): store a rest first and weld by rest; common for cleanup after deformation.
    """
    if geo is None:
        return Geometry()
    swap = modify_target and target is not None
    src = target if swap else geo
    other = geo if swap else target
    gsel_spec = target_group if swap else group
    osel_spec = group if swap else target_group

    name = str(position_attrib).strip() or "P"
    P = src.get(POINT, name)
    if P is None or P.shape[1] < 3:
        raise KeyError(f"No 3-component point attribute '{name}'; can't judge proximity by it.")
    P = P[:, :3].astype(np.float64)
    if src.npoints == 0:
        return src.copy()
    n = src.npoints
    sel = resolve(src, POINT, gsel_spec)
    d = float(snap_distance) if use_snap_distance else 0.0

    if snap_to == "grid":
        labels, k, moved, Q = _plan_grid(P, sel, grid_size, grid_offset)
    elif snap_to == "near_points" and other is not None:
        labels, k, moved, Q = _plan_target(src, P, sel, other, osel_spec, d,
                                           using, output_positions)
    elif snap_to == "near_points":
        labels, k, moved, Q = _plan_near(src, P, sel, d, use_snap_distance,
                                         radius_attrib, match_attrib,
                                         match_condition, match_tolerance)
    else:                                        # none: snap nothing
        labels, k, moved, Q = np.arange(n, dtype=np.int64), n, np.zeros(n, bool), P

    g = src.copy()
    if not np.array_equal(Q, P):                 # grid / target give new positions directly
        base = src.get(POINT, name)
        g.set(POINT, name, Q.astype(base.dtype), owned=True)
    rep = _pick_rep(labels, k, Q, using)
    g = _apply_positions(g, labels, k, rep, sel, output_positions,
                         attribs_to_snap)

    # groups are set **before merging**; _weld carries them over by "in the group if any point in the cluster was"
    if snapped_group.strip():
        g.set_group(POINT, snapped_group.strip(), moved)
    if snapped_to_group.strip():
        dest = np.zeros(n, bool)
        multi = np.bincount(labels, minlength=max(k, 1))[labels] > 1
        dest[rep[np.unique(labels[multi])]] = True if multi.any() else False
        g.set_group(POINT, snapped_to_group.strip(), dest)

    if fuse_snapped and k < n:
        g = _weld(g, labels, k, keep_fused)

    g = _cleanup(g, remove_repeated, remove_degenerate_unused,
                 remove_all_unused)
    if recompute_normals and g.has(POINT, "N"):
        g = compute_normals(g, "point")
    return g
