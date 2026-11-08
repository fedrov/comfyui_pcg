"""
Dissolve SOP -- delete the selected edges and merge the primitives on either side into one.

Same machinery as Divide's Remove Shared Edges, **different granularity**: that one works by "primitive group"
-- every interior edge between the selected primitives is merged away; this one works by **edge group**, only the edges you pick are merged.
The latter is the more common one in low-poly work: pick a few edges on a quad mesh and dissolve them to get the edge flow you want.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Merge a whole region at once, not edge by edge
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If the selected edges form a connected set (e.g. a whole edge loop), the primitives on both sides join into one connected piece. Merging edge by edge
would go "merge A and B, then merge the result with C", rebuilding topology at every step, and the intermediate state may not be a valid polygon.
Here the primitives are first grouped into regions through the selected edges, then each region's **boundary half-edges** are chained end-to-end into loops in one go.

Only regions that yield exactly **one** loop are merged: two loops means the region has a hole, and a prim only has
one vertex loop, so it cannot store a face with a hole. Such regions are left as they are, not forced -- consistent with how
Remove Shared Edges handles it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Remove Inline Points: clean up "fake vertices" after merging
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After dissolving an edge, the two endpoints of that edge are often left with only two edges passing through them, collinear -- they
contribute nothing to the shape, they just give the primitive two extra vertices. **This is the half of Dissolve most easily overlooked**:
without cleaning them, dissolving a few edges on a quad mesh lowers the primitive count but not the vertex count, and later subdivision/UV
work carries all these redundant points along.

The criterion is an **angle**, not "exactly collinear": computed edges are rarely exactly collinear in floating point, so a tolerance
(default 0.1 deg) is what makes it practical.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Boundary edges are skipped, and you are told about it
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
An edge with only one primitive (the mesh's outer rim) has no "primitives on both sides" to merge. Houdini deletes it and turns that primitive into an
open polyline; here we skip it instead, because "selected an edge loop and the geometry turned into a pile of polylines" looks more like an accident.
The number skipped is written to the detail attribute `dissolve_skipped`, so it doesn't happen silently.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve_edges, edge_mask
from .topology import topology
from .divide import _rebuild
from .ops import _gather_blocks


def _components(nprims, a, b):
    """Group primitives into regions via the given adjacency pairs and return labels. Pointer jumping, same as Connectivity."""
    lab = np.arange(nprims, dtype=np.int64)
    if not len(a):
        return lab
    for _ in range(64):
        prev = lab
        m = np.minimum(lab[a], lab[b])
        lab = lab.copy()
        np.minimum.at(lab, a, m)
        np.minimum.at(lab, b, m)
        lab = lab[lab]
        if np.array_equal(lab, prev):
            break
    return lab


def inline_mask(geo, tol_degrees=0.1, protect=None):
    """
    (npoints,) bool: which points are "fake vertices" -- exactly two edges pass through, and the two edges are nearly collinear.

    Points in protect never count (used to guard points in a group, or feature points that must explicitly be kept).
    """
    t = topology(geo)
    P = geo.get(POINT, "P")
    n = geo.npoints
    if P is None or t.nedges == 0:
        return np.zeros(n, bool)
    val = np.diff(t.pt_edge_off)
    cand = np.nonzero(val == 2)[0]
    out = np.zeros(n, bool)
    if not len(cand):
        return out
    # two edges of each candidate point -> two "other ends"
    e0 = t.pt_edge[t.pt_edge_off[cand]].astype(np.int64)
    e1 = t.pt_edge[t.pt_edge_off[cand] + 1].astype(np.int64)
    ep = t.edge_points.astype(np.int64)
    o0 = np.where(ep[e0, 0] == cand, ep[e0, 1], ep[e0, 0])
    o1 = np.where(ep[e1, 0] == cand, ep[e1, 1], ep[e1, 0])
    Pf = P.astype(np.float64)
    u = Pf[o0] - Pf[cand]
    v = Pf[o1] - Pf[cand]
    lu = np.linalg.norm(u, axis=1)
    lv = np.linalg.norm(v, axis=1)
    ok = (lu > 1e-12) & (lv > 1e-12)
    cosang = np.zeros(len(cand))
    cosang[ok] = np.einsum("ij,ij->i", u[ok], v[ok]) / (lu[ok] * lv[ok])
    # the two edges point in opposite directions = three points collinear = cos close to -1
    ang = np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0)))
    out[cand[ok & (ang >= 180.0 - float(tol_degrees))]] = True
    if protect is not None:
        out &= ~np.asarray(protect, bool)
    return out


def remove_inline(geo, tol_degrees=0.1, protect=None):
    """Remove fake vertices from each primitive's vertex loop (the points themselves stay, unless orphaned points are deleted in another pass)."""
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    drop = inline_mask(geo, tol_degrees, protect)
    if not drop.any():
        return geo.copy()
    keep = ~drop[geo.vertex_point]
    sizes = geo.prim_sizes()
    vprim = geo.vertex_prim().astype(np.int64)
    # use bincount rather than add.reduceat: empty prims make reduceat miscount (old bug)
    new_sizes = np.bincount(vprim[keep], minlength=geo.nprims)
    # if only two points would remain it is no longer a face; that primitive is kept unchanged
    bad = new_sizes < 3
    if bad.any():
        keep = keep | np.repeat(bad, sizes)
        new_sizes = np.bincount(vprim[keep], minlength=geo.nprims)
    from .divide import _rebuild_flat
    return _rebuild_flat(geo, np.nonzero(keep)[0], new_sizes,
                         np.arange(geo.nprims, dtype=np.int64),
                         np.asarray(geo.prim_closed, bool))


OPERATIONS = ("selected", "non_selected")
# leave is what this node has always done (regions with holes are left as they are); Houdini has no such option;
# the other two are Create Bridged Polygons / Delete Polygons from Houdini's Bridge menu.
# Create Disjoint Polygons is not implemented: the docs only say "produces disconnected surfaces"; which primitives, and how holes
# are handled, is not stated.
BRIDGE = ("leave", "bridged", "delete")


def _bridged_loop(block, corners, sel_pairs, twin, vp, nxt, vprim, sel):
    """
    Region with holes -> **one** vertex loop (Houdini's Create Bridged Polygons).

    Approach: instead of dissolving all selected edges in the region, dissolve only a **spanning tree** of the primitive adjacency graph -- gluing the
    primitives together one by one along the tree always yields a topological disk whose boundary is a single loop. Selected edges not in the tree remain in the loop,
    traversed once in each direction; most of them are dangling "spikes" (a->b->a), and after removing those one by one, the remaining two-way edges
    are exactly the bridges needed to connect the outer loop to the holes.

    Returns a corner list; returns None when it can't be done, and the caller treats it as leave. Two cases can't be done:
    a pair of adjacent primitives has opposite winding (glued together they don't form an orientable surface, and walking the boundary doesn't give one loop),
    or nothing is left after removing spikes (the whole region is a closed surface, with no boundary).
    """
    # spanning tree: union-find, greedily taking edges in order
    parent = {int(f): int(f) for f in block}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    tree = np.zeros(len(vp), bool)                 # dissolved half-edges
    for a, b in sel_pairs:                         # (half-edge, its opposite)
        if vp[a] != vp[nxt[b]]:
            return None                            # both sides traverse this edge in the same direction: one primitive is flipped
        fa, fb = find(int(vprim[a])), find(int(vprim[b]))
        if fa != fb:
            parent[fa] = fb
            tree[a] = tree[b] = True

    # The spanning tree only takes 2(F-1) half-edges, while F primitives have at least 3F corners, so keep is never empty.
    # Consistently wound primitives glued along a tree form a disk; its boundary half-edges chain end-to-end into exactly one loop,
    # so walking len(keep) steps as below always returns to the start, visiting each corner exactly once -- no need to verify
    keep = [int(c) for c in corners if not tree[c]]
    loop, c = [], keep[0]
    for _ in range(len(keep)):
        loop.append(c)
        c = int(nxt[c])
        while tree[c]:                             # dissolved edge: cross to the opposite primitive and keep walking
            c = int(nxt[int(twin[c])])

    # Remove spikes: ... a b a ... drop b and the preceding a (keep the corner of the later a -- its outgoing edge is the one
    # that really remains). Only remove **selected** edges: an unselected edge must stay even if both sides are in the region; it is not to be dissolved.
    # Do one pass with a stack, then handle the few that straddle the wrap-around point
    st = []
    for c in loop:
        if len(st) >= 2 and sel[st[-2]] and vp[st[-2]] == vp[c]:
            st.pop()
            st[-1] = c
        else:
            st.append(c)
    while len(st) >= 3:
        if sel[st[-2]] and vp[st[-2]] == vp[st[0]]:      # spike tip is the last one
            st = st[:-2]
        elif sel[st[-1]] and vp[st[-1]] == vp[st[1]]:    # spike tip is the first one
            st = st[1:-1]
        else:
            break
    return st if len(st) >= 3 else None


def dissolve(geo, edge_group="", remove_inline_points=True,
             inline_tolerance=0.1, delete_lone_points=False,
             output_boundary_group="", operation="selected", bridge="leave",
             recompute_normals=False):
    """
    Delete the selected edges and merge the primitives on either side into one.

    remove_inline_points is **on** by default: after merging, the endpoints of the former edge usually have only two edges
    passing through, collinear; keeping them just leaves redundant vertices.

    With operation=non_selected, all edges **outside** the group are dissolved (empty group = all edges).
    bridge controls what happens when "a merged region has holes"; see BRIDGE.
    """
    if geo is None:
        return Geometry()
    if operation not in OPERATIONS:
        raise ValueError(f"Operation must be one of {OPERATIONS}")
    if bridge not in BRIDGE:
        raise ValueError(f"Bridge must be one of {BRIDGE}")
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    pairs = resolve_edges(geo, edge_group) if str(edge_group).strip() \
        else np.zeros((0, 2), np.int32)
    if operation == "non_selected":
        t0 = topology(geo)
        pairs = np.asarray(t0.edge_points[~edge_mask(geo, pairs)], np.int32)
    if not len(pairs):
        return geo.copy()

    t = topology(geo)
    sel_e = edge_mask(geo, pairs)
    manifold = t.edge_count == 2
    skipped = int(np.count_nonzero(sel_e & ~manifold))
    sel_e = sel_e & manifold
    if not sel_e.any():
        g = geo.copy()
        if skipped:
            g.set(DETAIL, "dissolve_skipped",
                  np.array([[skipped]], np.int32), owned=True)
        return g

    vprim = geo.vertex_prim().astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)
    vp = geo.vertex_point
    two = np.nonzero(sel_e)[0]
    f1 = vprim[t.edge_he[t.edge_he_off[two]]]
    f2 = vprim[t.edge_he[t.edge_he_off[two] + 1]]
    lab = _components(geo.nprims, f1, f2)

    # half-edges to delete: the edge they belong to is selected (both sides naturally in the same region)
    he_sel = np.zeros(geo.nvertices, bool)
    ok = t.he_edge >= 0
    he_sel[ok] = sel_e[t.he_edge[ok]]

    sizes = geo.prim_sizes()
    starts = geo.prim_offset[:-1].astype(np.int64)
    faces, src, closed = [], [], []
    merged = np.zeros(geo.nprims, bool)
    for L in np.unique(lab):
        block = np.nonzero(lab == L)[0]
        if len(block) == 1:
            i = int(block[0])
            faces.append(list(range(int(starts[i]),
                                    int(starts[i] + sizes[i]))))
            src.append(i)
            closed.append(bool(geo.prim_closed[i]))
            continue
        corners = _gather_blocks(starts[block], sizes[block])
        bnd = [int(c) for c in corners if not he_sel[c]]
        loops = _trace(bnd, vp, nxt) if bnd else []
        if len(loops) == 1 and len(loops[0]) == len(bnd):
            faces.append(loops[0])
            src.append(int(block[0]))
            closed.append(True)
            merged[block] = True
            continue
        if bridge == "delete":
            # Houdini's Delete Polygons: regions with holes are deleted entirely
            continue
        loop = None
        if bridge == "bridged":
            # both half-edges of each selected edge are in there; the second time around both sides are already connected and union-find skips it
            hs = corners[he_sel[corners]]
            loop = _bridged_loop(block, corners, list(zip(hs.tolist(),
                                                         t.he_twin[hs].tolist())),
                                 t.he_twin, vp, nxt, vprim, he_sel)
        if loop is not None:
            faces.append(loop)
            src.append(int(block[0]))
            closed.append(True)
            merged[block] = True
        else:
            # has holes or can't be chained into one loop -- a prim only has one vertex loop, it can't store this
            for j in block:
                faces.append(list(range(int(starts[j]),
                                        int(starts[j] + sizes[j]))))
                src.append(int(j))
                closed.append(bool(geo.prim_closed[j]))

    out = _rebuild(geo, faces, src, closed)
    if str(output_boundary_group).strip():
        # outer rim of the merged big primitive -- useful later for bevelling / extruding that loop
        keep = np.zeros(len(t.edge_points), bool)
        keep[:] = ~sel_e
        inv = t.edge_points[keep & _touches(t, merged, vprim)]
        out.set_edge_group(str(output_boundary_group).strip(), inv)
    if remove_inline_points:
        out = remove_inline(out, inline_tolerance)
    if delete_lone_points:
        from .ops import delete_points
        used = np.zeros(out.npoints, bool)
        if out.nvertices:
            used[out.vertex_point] = True
        out = delete_points(out, used)
    if recompute_normals:
        # the docs only say "recompute normals after deleting"; our reading: whichever class originally carried N is recomputed in place
        # (same convention as Fuse's Recompute Normals); where there is no N, none is created
        from .ops import compute_normals
        for cls in (POINT, VERTEX, PRIM):
            if out.has(cls, "N"):
                out = compute_normals(out, cls)
    if skipped:
        out.set(DETAIL, "dissolve_skipped",
                np.array([[skipped]], np.int32), owned=True)
    return out


def _touches(t, prim_mask, vprim):
    """(E,) bool: at least one side's primitive is in prim_mask."""
    m = np.zeros(t.nedges, bool)
    if not prim_mask.any() or t.nedges == 0:
        return m
    he = t.edge_he
    owner = prim_mask[vprim[he]]
    np.logical_or.at(m, np.repeat(np.arange(t.nedges), t.edge_count), owner)
    return m


def _trace(bnd, vp, nxt):
    """Chain boundary half-edges end-to-end into loops. Returns a list of loops."""
    by_start = {}
    for c in bnd:
        by_start.setdefault(int(vp[c]), []).append(c)
    loops, used = [], set()
    for c0 in bnd:
        if c0 in used:
            continue
        loop, c = [], c0
        while True:
            used.add(c)
            loop.append(c)
            nxts = [x for x in by_start.get(int(vp[int(nxt[c])]), [])
                    if x not in used]
            if not nxts:
                break
            c = nxts[0]
        loops.append(loop)
    return loops
