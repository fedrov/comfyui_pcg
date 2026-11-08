"""
Edge Divide / Loop Cut -- inserts points on edges and connects the new points to cut faces.

Matches Houdini's Edge Divide, plus a loop mode of PolySplit (called Loop Cut / Insert Edge Loop in
other software). Dissolve removes edges, these two add them; they are a pair.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Inserting points" and "connecting" are two different things
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Inserting a point on an edge adds a vertex to the faces on both sides -- always safe, any face can take it.
**Connecting** the new points is the actual cut, and it only has a unique solution when "exactly two edges of this face are cut":
where should a point on one edge connect to? With two edges it is end to end; with three there is no non-arbitrary answer.

So the rules are:

    0 edges cut on the face         unchanged
    2 edges cut + connect           cut into cuts+1 pieces
    anything else (1, 3 or more,
    or connect off)                 only insert points; the face becomes an ngon with more edges

With three or more Houdini connects in a fan to the face centre; that is one choice rather than the unique solution, and it introduces a
new point that isn't on any edge. Not done here; better to let people add a Divide and decide how to cut.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With cuts > 1 the points on the two edges pair up in **reverse order**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Walking around the face's vertex loop, the points on the first cut edge are A_0...A_{k-1} and on the second B_0...B_{k-1}. Because
the loop comes back around, A and B run in opposite directions, so the chords are A_i-B_{k-1-i}. Writing A_i-B_i
cuts the face into a pile of self-intersecting bowties -- the classic sign error in this kind of code.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Loop Cut = walk the loop first, then hand it to Edge Divide
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Starting from an edge, step into the adjacent **quad**, take "the opposite edge" (two steps around the loop),
then cross from it into the next quad -- until returning to the start (closed loop) or hitting a boundary / non-quad.
The collected chain of edges has exactly two per quad, and handing it to Edge Divide with connect gives
a complete edge loop.

**A non-quad ends the loop**, and that isn't laziness: a triangle has no "opposite edge", a pentagon has two,
so the loop naturally breaks there. Blender / Maya behave the same way.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .groups import resolve_edges, edge_mask
from .topology import topology


def _positions(cuts, spec=""):
    """Parametric positions of the cut points. Empty = evenly spaced."""
    if str(spec or "").strip():
        try:
            vals = [float(x) for x in str(spec).replace(",", " ").split()]
        except ValueError:
            raise ValueError(f"Cut Positions contains non-numeric items: '{spec}'")
        vals = [v for v in vals if 0.0 < v < 1.0]
        if not vals:
            raise ValueError(
                "Cut Positions has no valid value -- write parametric positions between 0 and 1, "
                "e.g. '0.25 0.5 0.75'.")
        return np.sort(np.asarray(vals, np.float64))
    k = max(1, int(cuts))
    return (np.arange(1, k + 1, dtype=np.float64)) / (k + 1)


def edge_ring(geo, seed_pairs, max_len=100000):
    """
    Walks the quad loop from the seed edges; returns the (E,2) point pairs of every edge on the loop.

    Only passes through quads. Stops at boundaries, non-manifold edges or non-quads.
    """
    t = topology(geo)
    if t.nedges == 0:
        return np.zeros((0, 2), np.int32)
    sizes = geo.prim_sizes()
    vprim = geo.vertex_prim().astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)
    he_edge = t.he_edge.astype(np.int64)
    seeds = np.nonzero(edge_mask(geo, seed_pairs))[0]
    visited = np.zeros(t.nedges, bool)
    n_hit = 0                       # a counter, not visited.sum() every time -- that is O(E)
    for s in seeds:
        if visited[s]:
            continue
        stack = [int(s)]
        visited[s] = True
        n_hit += 1
        while stack:
            e = stack.pop()
            if n_hit > max_len:
                break
            for hi in range(t.edge_he_off[e], t.edge_he_off[e + 1]):
                h = int(t.edge_he[hi])
                f = int(vprim[h])
                if sizes[f] != 4:
                    continue                    # non-quad: the loop breaks here
                opp = he_edge[nxt[nxt[h]]]      # two steps within the face = the opposite edge
                if opp >= 0 and not visited[opp]:
                    visited[opp] = True
                    n_hit += 1
                    stack.append(int(opp))
    return np.asarray(t.edge_points[visited], np.int32)


def edge_divide(geo, edge_group="", cuts=1, cut_positions="", connect=True,
                output_group="", output_point_group=""):
    """
    Inserts points on the selected edges; where exactly two edges of a face are cut, connects the new points to cut it.

    output_group is **the newly inserted cutting edges** (not the edges that were cut) -- useful for
    a following bevel / extrude of that loop.
    """
    if geo is None:
        return Geometry()
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    pairs = resolve_edges(geo, edge_group) if str(edge_group).strip() \
        else np.zeros((0, 2), np.int32)
    if not len(pairs):
        return geo.copy()

    ts = _positions(cuts, cut_positions)
    k = len(ts)
    t = topology(geo)
    sel_e = edge_mask(geo, pairs)
    if not sel_e.any():
        return geo.copy()

    npt = geo.npoints
    nv = geo.nvertices
    nf = geo.nprims
    vp = geo.vertex_point.astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    ep = t.edge_points.astype(np.int64)

    # Every selected edge gets a range of new point numbers
    slot = np.full(t.nedges, -1, np.int64)
    esel = np.nonzero(sel_e)[0]
    slot[esel] = np.arange(len(esel))
    n_new = len(esel) * k

    # -- attributes of new points: linearly interpolated along the edge
    g_pts = _new_points(geo, ep[esel], ts, npt, n_new)

    # -- how many cut points follow each corner
    he_e = t.he_edge.astype(np.int64)
    c_sel = np.zeros(nv, bool)
    ok = he_e >= 0
    c_sel[ok] = sel_e[he_e[ok]]
    counts = 1 + k * c_sel.astype(np.int64)
    total = int(counts.sum())
    slot_corner = np.repeat(np.arange(nv, dtype=np.int64), counts)
    sub = (np.arange(total, dtype=np.int64)
           - np.repeat(np.cumsum(counts) - counts, counts))   # 0 = the original corner

    ca = slot_corner
    cb = nxt[slot_corner]
    e_of = he_e[ca]
    # An edge's cut points are numbered edge_points[e,0] -> [e,1]; when walking in reverse count backwards
    fwd = np.zeros(total, bool)
    m = sub > 0
    fwd[m] = vp[ca[m]] == ep[e_of[m], 0]
    idx = np.where(fwd, sub - 1, k - sub)
    pt = np.where(sub == 0, vp[ca],
                  npt + np.maximum(slot[e_of], 0) * k + np.clip(idx, 0, k - 1))
    tt = np.where(sub == 0, 0.0,
                  np.where(fwd, ts[np.clip(sub - 1, 0, k - 1)],
                           1.0 - ts[np.clip(k - sub, 0, k - 1)]))

    ext_size = sizes + k * np.add.reduceat(c_sel.astype(np.int64), starts)
    ext_off = np.concatenate([[0], np.cumsum(ext_size)]).astype(np.int64)

    nsel_face = np.add.reduceat(c_sel.astype(np.int64), starts)
    splittable = connect and True
    do_split = (nsel_face == 2) & np.asarray(geo.prim_closed, bool) \
        if splittable else np.zeros(nf, bool)

    parts = []
    if (~do_split).any():
        keep = np.nonzero(~do_split)[0]
        parts.append((_blocks(ext_off[keep], ext_size[keep]),
                      ext_size[keep], keep))
    if do_split.any():
        parts.append(_split_faces(np.nonzero(do_split)[0], sizes, starts,
                                  c_sel, ext_off, k))
    flat = np.concatenate([a for a, _, _ in parts])
    all_sizes = np.concatenate([b for _, b, _ in parts])
    src_prim = np.concatenate([c for _, _, c in parts])
    # Stable sort by source face: the pieces cut from a face stay at its original position instead of piling up at the end
    order = np.argsort(src_prim, kind="stable")
    old_start = np.concatenate([[0], np.cumsum(all_sizes)])[:-1]
    fsizes = all_sizes[order]
    src_prim = src_prim[order]
    flat = flat[_blocks(old_start[order], fsizes)]

    out = g_pts
    out.set_topology(pt[flat].astype(np.int32),
                     np.concatenate([[0], np.cumsum(fsizes)]).astype(np.int32),
                     np.ones(len(fsizes), bool),
                     np.full(len(fsizes), PRIM_POLY, geo.prim_type.dtype))
    for key, v in geo.attribs[VERTEX].items():
        if is_string(v):
            out.set(VERTEX, key, np.asarray(v)[ca[flat]], owned=True)
            continue
        a = v.astype(np.float64)
        lerp = a[ca[flat]] + (a[cb[flat]] - a[ca[flat]]) * tt[flat][:, None]
        out.set(VERTEX, key, (np.rint(lerp) if v.dtype.kind in "iub"
                              else lerp).astype(v.dtype), owned=True)
    for key, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, key, v[ca[flat]])
    for key, v in geo.attribs[PRIM].items():
        out.set(PRIM, key, v[src_prim], owned=True)
    for key, v in geo.groups[PRIM].items():
        out.set_group(PRIM, key, v[src_prim])
    out.prim_data = geo.remap_prim_data(src_prim)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.edge_groups = _split_edge_groups(geo, t, slot, npt, k)

    if str(output_point_group).strip():
        m = np.zeros(out.npoints, bool)
        m[npt:] = True
        out.set_group(POINT, str(output_point_group).strip(), m)
    if str(output_group).strip():
        out.set_edge_group(str(output_group).strip(),
                           _cut_edges(out, npt))
    return out


def loop_cut(geo, edge_group="", cuts=1, cut_positions="",
             output_group="", output_point_group=""):
    """Walks a quad loop from the seed edges, then inserts points and cuts along the whole loop."""
    if geo is None:
        return Geometry()
    if not str(edge_group).strip():
        return geo.copy()
    ring = edge_ring(geo, resolve_edges(geo, edge_group))
    if not len(ring):
        return geo.copy()
    g = geo.copy()
    g.set_edge_group("__ring__", ring)
    out = edge_divide(g, "__ring__", cuts, cut_positions, True,
                      output_group, output_point_group)
    out.edge_groups.pop("__ring__", None)
    return out


# ══════════════════════════════════════════════════════════ internals
def _blocks(starts, sizes):
    """Flat indices of [s0..s0+n0) ++ [s1..s1+n1) ++ ...."""
    if not len(sizes):
        return np.zeros(0, np.int64)
    tot = int(sizes.sum())
    return (np.repeat(starts, sizes)
            + np.arange(tot) - np.repeat(np.cumsum(sizes) - sizes, sizes))


def _new_points(geo, ep_sel, ts, npt, n_new):
    """Builds a geometry with the new points (points only; topology is set later). Point attributes are interpolated along edges."""
    out = Geometry()
    out._resize_points(npt + n_new)
    k = len(ts)
    a = np.repeat(ep_sel[:, 0], k)
    b = np.repeat(ep_sel[:, 1], k)
    w = np.tile(ts, len(ep_sel))[:, None]
    for key, v in geo.attribs[POINT].items():
        if is_string(v):
            s = np.asarray(v)[:, 0]
            out.set(POINT, key, np.concatenate([s, s[a]]).reshape(-1, 1),
                    owned=True)
            continue
        f = v.astype(np.float64)
        add = f[a] + (f[b] - f[a]) * w
        col = np.concatenate([f, add], 0)
        out.set(POINT, key, (np.rint(col) if v.dtype.kind in "iub"
                             else col).astype(v.dtype), owned=True)
    for key, v in geo.groups[POINT].items():
        out.set_group(POINT, key, np.concatenate([v, v[a] & v[b]]))
    return out


def _split_faces(fids, sizes, starts, c_sel, ext_off, k):
    """
    Cuts faces with "exactly two edges cut" into k+1 pieces. Returns (flat indices, size of each piece, source face).

    Bucketed by (face edge count, positions of the two cut edges) -- all faces in a bucket have exactly the same extended vertex loop
    structure, so one template is computed once and broadcast over the bucket. A quad's edge loop has only 6 combinations, so buckets are few.
    """
    if not len(fids):
        return (np.zeros(0, np.int64), np.zeros(0, np.int64),
                np.zeros(0, np.int64))
    pa = np.empty(len(fids), np.int64)
    pb = np.empty(len(fids), np.int64)
    for i, f in enumerate(fids):
        loc = np.nonzero(c_sel[starts[f]:starts[f] + sizes[f]])[0]
        pa[i], pb[i] = loc[0], loc[1]
    key = sizes[fids] * 10000 + pa * 100 + pb

    flat, out_sizes, out_src = [], [], []
    for kk in np.unique(key):
        sub = np.nonzero(key == kk)[0]
        n = int(sizes[fids[sub[0]]])
        a, b = int(pa[sub[0]]), int(pb[sub[0]])
        base = ext_off[fids[sub]][:, None]

        def ext(j, _a=a, _b=b):        # position of original corner j in the extended loop
            return j + k * ((j > _a) + (j > _b))

        A = [a + 1 + i for i in range(k)]          # points on the first cut edge
        B = [ext(b) + 1 + i for i in range(k)]     # points on the second cut edge
        pieces = [[A[i], A[i + 1], B[k - 2 - i], B[k - 1 - i]]
                  for i in range(k - 1)]           # chords A_i-B_{k-1-i}
        pieces.append([A[k - 1]] + [ext(j) for j in range(a + 1, b + 1)]
                      + [B[0]])
        pieces.append([B[k - 1]] + [ext(j) for j in range(b + 1, n)]
                      + [ext(j) for j in range(0, a + 1)] + [A[0]])
        for p in pieces:
            flat.append((base + np.asarray(p, np.int64)[None, :]).reshape(-1))
            out_sizes.append(np.full(len(sub), len(p), np.int64))
            out_src.append(fids[sub])
    return (np.concatenate(flat), np.concatenate(out_sizes),
            np.concatenate(out_src))


def _split_edge_groups(geo, t, slot, npt, k):
    """Cut edges in edge groups must be split into k+1 segments."""
    if not geo.edge_groups:
        return {}
    ep = t.edge_points.astype(np.int64)
    key = ep[:, 0] * (geo.npoints + 1) + ep[:, 1]
    out = {}
    for name, pairs in geo.edge_groups.items():
        if not len(pairs):
            out[name] = np.zeros((0, 2), np.int32)
            continue
        q = np.sort(np.asarray(pairs, np.int64), axis=1)
        qk = q[:, 0] * (geo.npoints + 1) + q[:, 1]
        hit = np.nonzero(np.isin(key, qk))[0]
        cut = hit[slot[hit] >= 0]
        whole = hit[slot[hit] < 0]
        segs = [ep[whole]]
        if len(cut):
            ids = npt + slot[cut][:, None] * k + np.arange(k)[None, :]
            chain = np.concatenate([ep[cut, 0:1], ids, ep[cut, 1:2]], 1)
            segs.append(np.stack([chain[:, :-1].reshape(-1),
                                  chain[:, 1:].reshape(-1)], 1))
        out[name] = np.concatenate(segs).astype(np.int32) if segs else \
            np.zeros((0, 2), np.int32)
    return out


def _cut_edges(out, npt):
    """Newly inserted cutting edges: both endpoints new, or one new and one old but not on the original edge."""
    t = topology(out)
    ep = t.edge_points
    both_new = (ep[:, 0] >= npt) & (ep[:, 1] >= npt)
    return np.asarray(ep[both_new], np.int32)
