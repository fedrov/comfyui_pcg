"""
Facet SOP -- a set of "retopologize" toggles, executed in a fixed order.

    unique -> consolidate -> orient -> cusp -> inline -> degenerate -> normals

The order isn't arbitrary; it's Houdini's order, and each step depends on the previous one's result:
unique points before consolidating is what lets "coincident-looking but topologically separate" points be merged; unify winding before computing cusp,
otherwise adjacent primitives' normals point one up one down, the angle is always 180 deg, and the whole geometry gets split apart.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One mechanism running through the whole file: corner classification -> rebuild points
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Unique Points and Cusp Polygons look like two things but are essentially one: **assign each corner
a class; corners of the same class share one point**.

    unique : each corner is its own class           -> point count = corner count
    cusp   : merge corners across "smooth edges"     -> automatically split at hard edges

So there's only one _split_points(), shared by both. This is also why the hard edges cusp produces are
**real** hard edges -- the points are actually split, so any point normal computed afterwards is hard, unlike the Normal SOP's
vertex normals which only work at the shading level.

Cusp's class-merging relation is computed with vectorized label propagation (same pointer jumping as Connectivity),
not a Python union-find -- a loop over 100k edges is a difference of seconds here.
"""
from __future__ import annotations

import numpy as np

from .core import (Geometry, POINT, VERTEX, PRIM, DETAIL, freeze)
from .groups import resolve
from .topology import topology
from .ops import prim_normals, compute_normals, delete_prims, delete_points, fuse


# ═══════════════════════════════════════════════════════ shared: rebuild points by corner classification
def _labels(n, pairs):
    """
    Turn the connections in pairs into class numbers 0..k-1.

    Pointer jumping + label propagation, converges in O(log n) rounds, same as topology.connectivity.
    """
    lab = np.arange(n, dtype=np.int64)
    if len(pairs):
        a, b = pairs[:, 0], pairs[:, 1]
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
    return inv, int(inv.max()) + 1 if n else 0


def _remap_edge_groups_split(geo, new_of_corner):
    """
    Rebuild edge groups after splitting points.

    Edge groups store point pairs, and splitting turns one point into several -- point number mapping alone can't recover them.
    But topologically each edge is a half-edge; walking through the half-edge's two corners,
    old and new point pairs line up naturally. One old edge may map to several new edges (the ones split apart); all are kept.
    """
    if not geo.edge_groups:
        return {}
    t = topology(geo)
    nxt = geo.next_corner()
    vp = geo.vertex_point
    h = np.nonzero(t.he_valid)[0]
    if not len(h):
        return {k: freeze(np.zeros((0, 2), np.int32)) for k in geo.edge_groups}
    old = np.sort(np.stack([vp[h], vp[nxt[h]]], 1), axis=1)
    oldkey = old[:, 0].astype(np.int64) * max(geo.npoints, 1) + old[:, 1]
    newp = np.sort(np.stack([new_of_corner[h], new_of_corner[nxt[h]]], 1), axis=1)

    out = {}
    for name, pairs in geo.edge_groups.items():
        if not len(pairs):
            out[name] = freeze(np.zeros((0, 2), np.int32))
            continue
        key = pairs[:, 0].astype(np.int64) * max(geo.npoints, 1) + pairs[:, 1]
        sel = np.isin(oldkey, key)
        out[name] = freeze(np.unique(newp[sel], axis=0).astype(np.int32)
                           if sel.any() else np.zeros((0, 2), np.int32))
    return out


def _split_points(geo, cls_of_corner, k):
    """
    Rebuild the point set from the corner classification. Corners of the same class share one new point.

    Precondition (guaranteed by the caller): corners in one class originally sit on the same original point --
    otherwise there's no answer to whose attributes the new point should inherit.

    Orphan points originally referenced by no corner are kept as is, appended after the new points. Orphan points are valid geometry
    (the Add SOP's "points only" mode exists to produce them), so they mustn't be cleaned up in passing.
    """
    vp = geo.vertex_point
    nv = geo.nvertices
    cls_of_corner = np.asarray(cls_of_corner, np.int64)

    # pick one representative corner per class: write in reverse, so the last write is the smallest corner in that class;
    # output point order therefore follows the original corner order, reproducibly
    rep = np.full(k, 0, np.int64)
    if nv:
        rep[cls_of_corner[::-1]] = np.arange(nv - 1, -1, -1)
    src_new = vp[rep] if nv else np.zeros(0, np.int64)

    used = np.zeros(geo.npoints, bool)
    if nv:
        used[vp] = True
    iso = np.nonzero(~used)[0]
    src_all = np.concatenate([src_new, iso]).astype(np.int64)

    out = Geometry()
    out._resize_points(k + len(iso))
    out.set_topology(cls_of_corner.astype(np.int32), geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    for name, v in geo.attribs[POINT].items():
        out.set(POINT, name, v[src_all], owned=True)
    for name, v in geo.groups[POINT].items():
        out.set_group(POINT, name, v[src_all])
    for cls in (VERTEX, PRIM):
        for name, v in geo.attribs[cls].items():
            out.set(cls, name, v)
        for name, v in geo.groups[cls].items():
            out.set_group(cls, name, v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.prim_data = {kk: dict(vv) for kk, vv in geo.prim_data.items()}
    out.edge_groups = _remap_edge_groups_split(geo, cls_of_corner.astype(np.int32))
    return out


def _ungrouped_chain(geo, prim_mask):
    """
    Chain the corners of out-of-group prims by point -- primitives outside the group keep their original point sharing.

    A group means "sub-geometry" (consistent with Houdini): the operator only works on the geometry within the group, and what is outside
    is kept as is. For point splitting that comes down to two rules: out-of-group corners are tied to each other (this function),
    and in-group and out-of-group corners are never merged (see cusp_polygons). So points on the group boundary get duplicated:
    the in-group side takes the new point, the out-of-group side stays on the original -- same position and attributes, the outside primitives see no difference.
    """
    vprim = geo.vertex_prim()
    ung = np.nonzero(~prim_mask[vprim])[0]
    if len(ung) < 2:
        return np.zeros((0, 2), np.int64)
    vp = geo.vertex_point
    o = ung[np.argsort(vp[ung], kind="stable")]
    same = vp[o[:-1]] == vp[o[1:]]
    return np.stack([o[:-1][same], o[1:][same]], 1).astype(np.int64)


# ═══════════════════════════════════════════════════════════════ the individual toggles
def unique_points(geo, prim_mask=None):
    """One point per corner. Out-of-group corners keep sharing."""
    nv = geo.nvertices
    if nv == 0:
        return geo.copy()
    if prim_mask is None:
        prim_mask = np.ones(geo.nprims, bool)
    vp = geo.vertex_point
    g = prim_mask[geo.vertex_prim()]
    # in-group corners each get a non-colliding key, out-of-group corners use the original point number -> aggregated automatically
    key = np.where(g, geo.npoints + np.arange(nv, dtype=np.int64),
                   vp.astype(np.int64))
    _, inv = np.unique(key, return_inverse=True)
    inv = inv.reshape(-1)
    return _split_points(geo, inv, int(inv.max()) + 1)


def consolidate_points(geo, distance=1e-4, prim_mask=None):
    """
    Weld points together by distance. Points used by out-of-group primitives don't take part.

    When everything is in the group, go straight to ops.fuse -- it's the same thing, no need to maintain a second implementation.
    """
    if distance <= 0 or geo.npoints == 0:
        return geo.copy()
    if prim_mask is None or prim_mask.all():
        return fuse(geo, distance)

    P = geo.get(POINT, "P")
    part = np.zeros(geo.npoints, bool)
    if geo.nvertices:
        part[geo.vertex_point[prim_mask[geo.vertex_prim()]]] = True
    q = np.round(P / distance).astype(np.int64)
    # add an "isolation label" column: participating points get 0, non-participating ones their own point number -- key rows never coincide,
    # so they can't be welded onto anyone, nor can anyone be welded onto them
    tag = np.where(part, 0, np.arange(1, geo.npoints + 1)).astype(np.int64)
    return _weld(geo, np.concatenate([q, tag[:, None]], 1))


def _weld(geo, key_rows):
    """Deduplicate points by (N,K) integer key rows. Points with the same row merge into one; the representative is the smallest original number."""
    _, first, inv = np.unique(key_rows, axis=0, return_index=True,
                              return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(first)                 # new point numbers follow the original point order
    remap = np.empty(len(first), np.int32)
    remap[order] = np.arange(len(first), dtype=np.int32)
    new_idx = remap[inv]
    keep = first[order]

    out = Geometry()
    out._resize_points(len(first))
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[keep], owned=True)
    out.set_topology(new_idx[geo.vertex_point], geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    for cls in (VERTEX, PRIM):
        for k, v in geo.attribs[cls].items():
            out.set(cls, k, v)
        for k, v in geo.groups[cls].items():
            out.set_group(cls, k, v)
    for k, v in geo.groups[POINT].items():    # in the group if any of the welded points was
        m = np.zeros(len(first), bool)
        np.logical_or.at(m, new_idx, v)
        out.set_group(POINT, k, m)
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    eg = geo.remap_edge_groups(new_idx.astype(np.int32), out.npoints)
    for k, v in eg.items():                   # edges whose two ends weld into one point no longer exist
        out.set_edge_group(k, v[v[:, 0] != v[:, 1]] if len(v) else v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


def orient_polygons(geo, prim_mask=None):
    """
    Unify winding: two adjacent primitives must traverse their shared edge in **opposite** directions.

    BFS from the lowest-numbered primitive in each connected piece, flipping a neighbour on direction conflict.
    When flipping, each prim's **first** corner stays put (consistent with Houdini's Reverse),
    so the prim's "starting point" is stable and downstream lookups by corner index don't get misaligned.

    Primitives that are inherently non-orientable, like a Moebius strip: BFS goes with whoever arrives first, no error.
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    if prim_mask is None:
        prim_mask = np.ones(geo.nprims, bool)

    t = topology(geo)
    vp = geo.vertex_point
    vprim = geo.vertex_prim()

    two = np.nonzero(t.edge_count == 2)[0]
    flip = np.zeros(geo.nprims, bool)
    if len(two):
        h1 = t.edge_he[t.edge_he_off[two]]
        h2 = t.edge_he[t.edge_he_off[two] + 1]
        f1, f2 = vprim[h1], vprim[h2]
        ok = (prim_mask[f1] & prim_mask[f2]
              & geo.prim_closed[f1] & geo.prim_closed[f2] & (f1 != f2))
        f1, f2 = f1[ok], f2[ok]
        # two half-edges leaving the same point = shared edge traversed in the same direction = one of them is reversed
        same = (vp[h1[ok]] == vp[h2[ok]])

        # CSR of primitive adjacency (bidirectional)
        a = np.concatenate([f1, f2])
        b = np.concatenate([f2, f1])
        r = np.concatenate([same, same])
        order = np.argsort(a, kind="stable")
        a, b, r = a[order], b[order], r[order]
        off = np.concatenate([[0], np.cumsum(np.bincount(
            a, minlength=geo.nprims))]).astype(np.int64)

        seen = np.zeros(geo.nprims, bool)
        cand = np.nonzero(prim_mask & geo.prim_closed)[0]
        for s in cand:
            if seen[s]:
                continue
            seen[s] = True
            stack = [s]
            while stack:                       # BFS only walks primitive adjacency, total cost O(primitive count)
                i = stack.pop()
                for j in range(off[i], off[i + 1]):
                    nb = b[j]
                    if seen[nb]:
                        continue
                    seen[nb] = True
                    flip[nb] = flip[i] ^ bool(r[j])
                    stack.append(nb)
    if not flip.any():
        return geo.copy()
    return _flip_prims(geo, flip)


def _flip_prims(geo, flip):
    """Reverse the winding of the given prims: first corner stays, the rest are reversed."""
    nv = geo.nvertices
    sizes = geo.prim_sizes()
    starts = np.repeat(geo.prim_offset[:-1], sizes)
    local = np.arange(nv, dtype=np.int64) - starts
    sz = np.repeat(sizes, sizes)
    rev = np.where(local == 0, 0, sz - local)
    perm = np.where(np.repeat(flip, sizes), starts + rev,
                    np.arange(nv, dtype=np.int64))

    out = geo.copy()
    out.set_topology(geo.vertex_point[perm], geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[perm], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[perm])
    return out


def cusp_polygons(geo, angle=60.0, prim_mask=None):
    """
    Split points by dihedral angle: for an edge where the adjacent primitives' normals differ by more than angle, the two sides no longer share points.

    Merge rule (an edge connects four corners pairwise):
        smooth edge e, its two half-edges h1/h2 point in opposite directions
        -> h1 and nxt[h2] sit on the same point, merge them
        -> nxt[h1] and h2 sit on the other point, merge them
    Non-manifold edges (shared by 3 or more primitives) are always hard edges: there's no unique dihedral angle there anyway.

    If a group is given, only edges with both sides in the group take part -- equivalent to cutting the group out and processing it alone.
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    if prim_mask is None:
        prim_mask = np.ones(geo.nprims, bool)

    t = topology(geo)
    nxt = geo.next_corner()
    vprim = geo.vertex_prim()
    pn = prim_normals(geo)
    cos_t = float(np.cos(np.radians(float(np.clip(angle, 0.0, 180.0)))))

    pairs = [_ungrouped_chain(geo, prim_mask)]
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        h1 = t.edge_he[t.edge_he_off[two]]
        h2 = t.edge_he[t.edge_he_off[two] + 1]
        f1, f2 = vprim[h1], vprim[h2]
        dot = np.einsum("ij,ij->i", pn[f1], pn[f2])
        # Only edges with **both sides in the group** can be smooth. Edges crossing the group aren't merged, so the in-group part
        # detaches from the outside along the boundary (same position and attributes, the outside primitives see no difference) --
        # equivalent to "cut the group out and facet it separately", which is what a group means in Houdini
        smooth = (dot >= cos_t) & prim_mask[f1] & prim_mask[f2]
        h1, h2 = h1[smooth], h2[smooth]
        pairs.append(np.stack([h1, nxt[h2]], 1).astype(np.int64))
        pairs.append(np.stack([nxt[h1], h2], 1).astype(np.int64))

    cls, k = _labels(geo.nvertices, np.concatenate(pairs))
    return _split_points(geo, cls, k)


def _drop_corners(geo, kill):
    """Delete the given corners, and clean up the points nobody references as a result (points that were already orphaned stay)."""
    keep = ~kill
    if keep.all():
        return geo.copy()
    # use bincount rather than reduceat to count each prim's remaining corners:
    # reduceat on an empty prim (equal offsets) sums across segments, silently giving wrong counts
    new_sizes = (np.bincount(geo.vertex_prim()[keep], minlength=geo.nprims)
                 if geo.nvertices else np.zeros(geo.nprims, np.int64))

    out = Geometry()
    out._resize_points(geo.npoints)
    out.set_topology(geo.vertex_point[keep],
                     np.concatenate([[0], np.cumsum(new_sizes)]).astype(np.int32),
                     geo.prim_closed, geo.prim_type)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[keep], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[keep])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    out.edge_groups = dict(geo.edge_groups)

    was = np.zeros(geo.npoints, bool)
    if geo.nvertices:
        was[geo.vertex_point] = True
    now = np.zeros(geo.npoints, bool)
    if out.nvertices:
        now[out.vertex_point] = True
    lost = was & ~now
    return delete_points(out, ~lost) if lost.any() else out


def _neighbours(geo):
    """(prev, next, has prev/next neighbours) -- computed on each prim's corner loop; open polyline endpoints have none."""
    nv = geo.nvertices
    sizes = geo.prim_sizes()
    starts = np.repeat(geo.prim_offset[:-1], sizes)
    local = np.arange(nv, dtype=np.int64) - starts
    sz = np.repeat(sizes, sizes)
    nxt = starts + (local + 1) % np.maximum(sz, 1)
    prv = starts + (local - 1) % np.maximum(sz, 1)
    closed = np.repeat(geo.prim_closed, sizes)
    interior = closed | ((local > 0) & (local < sz - 1))
    return prv, nxt, interior, sz, closed


def remove_inline_points(geo, distance=1e-3, prim_mask=None):
    """
    Delete points that "lie on the line between their previous and next points" -- redundant subdivision points in the middle of straight edges.

    The criterion is the point's **perpendicular distance** to the line through its neighbours being below the threshold, not an angle: on a 10 m long
    straight edge a 1 mm offset is an angle close to 180 deg yet visible to the eye; with a distance threshold the units correspond directly to the geometry's
    scale, so it's predictable to tune.

    One pass, using the **original** neighbours. A long run of collinear points is all marked at once, no need to
    iterate; and chain collapses of the "neighbours only become collinear after one is deleted" kind shouldn't happen anyway.
    """
    if geo.nvertices == 0 or distance <= 0:
        return geo.copy()
    if prim_mask is None:
        prim_mask = np.ones(geo.nprims, bool)
    P = geo.get(POINT, "P")
    vp = geo.vertex_point
    prv, nxt, interior, sz, closed = _neighbours(geo)

    a, b, c = P[vp[prv]], P[vp[nxt]], P[vp]
    ab = b - a
    L = np.linalg.norm(ab, axis=1)
    d = np.linalg.norm(np.cross(c - a, ab), axis=1) / np.where(L == 0, 1, L)
    d = np.where(L == 0, np.linalg.norm(c - a, axis=1), d)

    kill = interior & (d < distance) & np.repeat(prim_mask, geo.prim_sizes())
    # don't collapse a prim: closed primitives keep at least 3 corners, polylines at least 2
    if kill.any():
        cnt = np.bincount(geo.vertex_prim()[kill], minlength=geo.nprims)
        floor = np.where(geo.prim_closed, 3, 2)
        bad = (geo.prim_sizes() - cnt) < floor
        if bad.any():
            kill = kill & ~np.repeat(bad, geo.prim_sizes())
    return _drop_corners(geo, kill)


def remove_degenerate(geo, distance=1e-4, remove_bad_prims=True,
                      prim_mask=None):
    """
    Remove degenerates: when two adjacent corners in a prim point to nearly the same position, the latter is redundant;
    prims that can no longer form a primitive after dedup (closed < 3 corners, polyline < 2, zero area)
    are deleted entirely.
    """
    if geo.nvertices == 0:
        return geo.copy()
    if prim_mask is None:
        prim_mask = np.ones(geo.nprims, bool)
    P = geo.get(POINT, "P")
    vp = geo.vertex_point
    prv, nxt, interior, sz, closed = _neighbours(geo)
    sizes = geo.prim_sizes()

    dup = np.linalg.norm(P[vp] - P[vp[prv]], axis=1) < max(distance, 0.0)
    # the first corner of an open polyline has no "previous", so it doesn't take part
    local = np.arange(geo.nvertices, dtype=np.int64) - np.repeat(
        geo.prim_offset[:-1], sizes)
    dup &= (closed | (local > 0)) & np.repeat(prim_mask, sizes)
    g = _drop_corners(geo, dup) if dup.any() else geo.copy()

    if not remove_bad_prims or g.nprims == 0:
        return g
    s = g.prim_sizes()
    floor = np.where(g.prim_closed, 3, 2)
    keep = (s >= floor) | ~prim_mask
    area = np.linalg.norm(prim_normals(g, normalize=False), axis=1)
    flat = g.prim_closed & prim_mask & (area <= max(distance, 1e-12) ** 2 * 0.5)
    keep &= ~flat
    return delete_prims(g, keep) if not keep.all() else g


# ═══════════════════════════════════════════════════════════════ main entry point
def facet(geo, group="", unique=False, consolidate=False, distance=1e-4,
          orient=False, cusp=False, cusp_angle=60.0,
          inline=False, inline_distance=1e-3,
          degenerate=False, degen_distance=1e-4, remove_bad_prims=True,
          post_normals=False, unit_normals=False):
    """
    group is a **prim group**, with the same meaning as in Houdini: the group is processed as an independent piece of sub-geometry,
    and primitives outside it are kept as is -- no winding changes, no corner deletion, and when splitting points the outside side stays on the original points.
    Empty = everything.

    post_normals computes point normals. After cusp the points are actually split, so point normals are naturally
    hard -- which is exactly why the classic Facet + Normal combination gives hard edges.
    """
    g = geo
    pm = resolve(geo, PRIM, group) if str(group).strip() else None
    if pm is not None and pm.all():
        pm = None

    if unique:
        g = unique_points(g, pm)
    if consolidate:
        g = consolidate_points(g, distance, pm)
    if orient:
        g = orient_polygons(g, pm)
    if cusp:
        g = cusp_polygons(g, cusp_angle, pm)
    if inline:
        g = remove_inline_points(g, inline_distance, pm)
    if degenerate:
        g = remove_degenerate(g, degen_distance, remove_bad_prims, pm)
    if g is geo:
        g = geo.copy()

    if post_normals:
        g = compute_normals(g, "point")
    elif unit_normals:
        for cls in (POINT, VERTEX, PRIM):
            N = g.get(cls, "N")
            if N is None or N.shape[1] != 3:
                continue
            l = np.linalg.norm(N, axis=1, keepdims=True)
            g.set(cls, "N", N / np.where(l == 0, 1, l), owned=True)
    return g
