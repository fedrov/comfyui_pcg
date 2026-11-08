"""
Subdivide SOP -- Catmull-Clark / Loop / linear subdivision.

Mirrors Houdini's Subdivide (and the Smooth Polygons option in Divide). Three algorithms:

    catmull_clark  polygons with any number of sides -> one quad per corner. **The limit surface is a B-spline**,
                   the default choice for hard-surface rounding and blowing a low-poly model up into a high-poly one
    loop           triangles only -> one into four. The limit surface is a box spline; on triangle meshes it beats
                   Catmull-Clark, because CC cuts each triangle into three skewed quads
    linear         cuts without smoothing (face centers + edge midpoints). Adds density but **does not change the shape**, for
                   cases that will displace it themselves later (subdivide, then add noise for terrain)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The three Catmull-Clark stencils
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    face point F   average of all points of the face
    edge point E   (two endpoints + face points on both sides) / 4        boundary edge: midpoint of its endpoints
    point update   (F_avg + 2·R_avg + (n-3)·P) / n     n = valence, R = edge midpoints

Points on the boundary (and creases) follow another rule: (P_prev + 6P + P_next) / 8, looking only at the two neighbours
along boundary edges. **Points with more than two boundary edges are corners and stay put** -- without this rule a cube's
corners get rounded off, while people subdividing a cube usually want those eight corners kept.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A crease is just "treat it as a boundary"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creases come from three places: **edge groups** (`crease_group`, infinitely sharp), dihedral angle (`auto_crease_angle`,
infinitely sharp, recomputed every round -- after subdividing the shape changes and so does the test; for stability use an edge group), and since pcg79
**fractional crease weights**: the vertex attribute `creaseweight` (written by the Crease node; an edge's weight is the larger of the values on its two
half-edge start vertices). The rule for weight s is DeRose 98 / OpenSubdiv's semi-sharp creases:
    s ≥ 1   treated as sharp this round (edge point = midpoint, endpoints use the crease rule)
    0<s<1   smooth and sharp results blended linearly by s (edge points, and endpoints -- an endpoint's blend factor is the average of all its
            crease edge weights)
    After each round of subdivision the child edges' weight = s − 1 (smooth once it reaches 0), written back to the output creaseweight
So an edge with s = 2 is sharp for the first two rounds, then rounds off: a small fillet more than an infinitely sharp crease, common in hard surface.
With s ≥ the subdivision depth the result is **exactly the same** as an infinitely sharp edge-group crease (compared bit by bit in the tests).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
How attributes are carried over
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    point   **through the same stencils as P** (OpenSubdiv calls it vertex interpolation).
            Cd gets smoothed along with it, which is right -- otherwise colors would show steps after subdividing
    vertex  linear interpolation (corner = original, edge point = average of both ends, face point = average over the face). uv is a
            vertex attribute, and linear interpolation is exactly the behaviour it should have
    prim    new faces inherit from the source face
    detail  carried over as is

**Do uvs on seams get smeared**? No -- vertex attributes are stored per corner, and the two sides of a seam are already
two different corners, each interpolated on its own. That is exactly why uv should be a vertex attribute and not a point attribute.
"""
from __future__ import annotations

import numpy as np

from .core import (Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY,
                   is_string)
from .groups import resolve
from .topology import topology, edge_angles

ALGORITHMS = ("catmull_clark", "loop", "linear")
# How boundaries are handled -- the three options of OpenSubdiv's vtx boundary interpolation
#   edge_corner  boundaries are crease curves, **points with total valence 2 are corners and stay put** (default)
#   edge_only    boundaries are crease curves, corners also follow the curve (get rounded off)
#   smooth       boundaries are not creases, the whole patch shrinks inward (almost never what you want; kept for comparison)
BOUNDARY = ("edge_corner", "edge_only", "smooth")


# ══════════════════════════════════════════════════════════ small helpers
def _avg_by(idx, vals, n):
    """Average vals grouped by idx. vals is (K, C)."""
    cnt = np.bincount(idx, minlength=n).astype(np.float64)
    out = np.stack([np.bincount(idx, weights=vals[:, c], minlength=n)
                    for c in range(vals.shape[1])], 1)
    return out / np.maximum(cnt, 1.0)[:, None]


def _point_stack(geo):
    """Stack all numeric point attributes into one big (np, C) array, compute once and split again."""
    names, cols, dts = [], [], []
    for k, v in geo.attribs[POINT].items():
        if is_string(v):
            continue
        names.append(k)
        cols.append(v.shape[1])
        dts.append(v.dtype)
    if not names:
        return names, cols, dts, np.zeros((geo.npoints, 0))
    return names, cols, dts, np.concatenate(
        [geo.attribs[POINT][k].astype(np.float64) for k in names], 1)


def _crease_edges(geo, t, crease_group="", auto_angle=-1.0,
                  boundary="edge_corner"):
    """(E,) bool: which edges count as creases. With boundary='smooth' boundary edges do not count."""
    cr = (np.zeros(t.nedges, bool) if boundary == "smooth"
          else t.boundary.copy())
    gname = str(crease_group or "").strip()
    if gname:
        pairs = geo.get_edge_group(gname)
        if pairs is None:
            have = sorted(geo.edge_groups.keys())
            raise KeyError(f"No edge group '{gname}'. Existing: {have or '(none)'}")
        if len(pairs):
            key = np.sort(np.asarray(pairs, np.int64), axis=1)
            ep = t.edge_points.astype(np.int64)
            k1 = key[:, 0] * (geo.npoints + 1) + key[:, 1]
            k2 = ep[:, 0] * (geo.npoints + 1) + ep[:, 1]
            cr |= np.isin(k2, k1)
    if auto_angle is not None and float(auto_angle) >= 0:
        cr |= edge_angles(geo) >= float(auto_angle)
    return cr


def _crease_sharpness(geo, t, crease_group="", auto_angle=-1.0,
                      boundary="edge_corner", crease_attribute=""):
    """
    (E,) crease sharpness per edge: edge group / auto angle / boundary = inf, otherwise creaseweight (none = 0).
    Also returns the part that comes from the attribute alone (decremented by 1 each round and passed to the next level).
    """
    hard = _crease_edges(geo, t, crease_group, auto_angle, boundary)
    s_attr = np.zeros(t.nedges)
    nm = str(crease_attribute or "").strip()
    a = geo.get(VERTEX, nm) if nm else None
    if a is not None and not is_string(a) and t.nedges:
        w = np.asarray(a, np.float64)[:, 0]
        ok = t.he_valid
        np.maximum.at(s_attr, t.he_edge[ok].astype(np.int64),
                      np.maximum(w[ok], 0.0))
    return np.where(hard, np.inf, s_attr), s_attr, a is not None


def _blend_crease(V, bnd, on_crease, sharp, t, npt):
    """Endpoints: smooth and crease results blended by the average of all its crease edge weights (average ≥ 1 means pure crease)."""
    ce = np.nonzero(sharp > 0)[0]
    if not len(ce):
        return V
    ep = t.edge_points[ce].astype(np.int64)
    ends = np.concatenate([ep[:, 0], ep[:, 1]])
    w = np.minimum(np.concatenate([sharp[ce], sharp[ce]]), 1.0)
    cnt = np.bincount(ends, minlength=npt)
    sig = np.bincount(ends, weights=w, minlength=npt) / np.maximum(cnt, 1)
    sig = np.where(on_crease, sig, 0.0)[:, None]
    return np.where(on_crease[:, None], sig * bnd + (1.0 - sig) * V, V)


def _boundary_update(P, t, crease, n_pts, boundary="edge_corner"):
    """
    Point update on creases: (P_prev + 6P + P_next) / 8.

    Returns (new positions, mask of points that should use this rule). Edge cases of the two rules:
      * points with **not** exactly 2 crease edges have no "previous/next neighbour along the curve" and stay put
      * with boundary='edge_corner', points with **total valence 2** (the four corners of a grid) also stay put --
        this is OpenSubdiv's EDGE_AND_CORNER. Without it, after subdividing a Grid
        its four corners get pulled inward, like paper that has been pinched
    """
    ce = np.nonzero(crease)[0]
    upd = P.copy()
    if not len(ce):
        return upd, np.zeros(n_pts, bool)
    ep = t.edge_points[ce].astype(np.int64)
    ends = np.concatenate([ep[:, 0], ep[:, 1]])
    other = np.concatenate([ep[:, 1], ep[:, 0]])
    cnt = np.bincount(ends, minlength=n_pts)
    acc = np.stack([np.bincount(ends, weights=P[other, c], minlength=n_pts)
                    for c in range(P.shape[1])], 1)
    on_crease = cnt > 0
    use = cnt == 2                # exactly two crease edges = an ordinary point on a crease curve
    if boundary == "edge_corner":
        use &= np.diff(t.pt_edge_off) != 2
    upd[use] = (acc[use] + 6.0 * P[use]) / 8.0
    return upd, on_crease


# ══════════════════════════════════════════════════════════ Catmull-Clark / linear
def _cc_once(geo, linear=False, crease_group="", auto_angle=-1.0,
             boundary="edge_corner", crease_attribute=""):
    t = topology(geo)
    npt, nf, ne = geo.npoints, geo.nprims, t.nedges
    nv = geo.nvertices
    if nf == 0 or nv == 0 or ne == 0:
        return geo.copy()

    names, cols, dts, A = _point_stack(geo)          # (npt, C)
    vp = geo.vertex_point.astype(np.int64)
    vprim = geo.vertex_prim().astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)

    sharp, s_attr, has_w = _crease_sharpness(geo, t, crease_group, auto_angle,
                                             boundary, crease_attribute)
    crease = sharp > 0

    # ── face points: average of all points in the face
    F = _avg_by(vprim, A[vp], nf)

    # ── edge points. Interior edge = (two endpoints + face points on both sides)/4; crease/boundary = midpoint
    ep = t.edge_points.astype(np.int64)
    mid = 0.5 * (A[ep[:, 0]] + A[ep[:, 1]])
    E = mid.copy()
    if not linear:
        inner = np.nonzero((t.edge_count == 2) & (sharp < 1))[0]
        if len(inner):
            f1 = vprim[t.edge_he[t.edge_he_off[inner]]]
            f2 = vprim[t.edge_he[t.edge_he_off[inner] + 1]]
            w = sharp[inner][:, None]              # semi-sharp: smooth and midpoint blended by s
            E[inner] = (1.0 - w) * 0.25 * (A[ep[inner, 0]] + A[ep[inner, 1]]
                                           + F[f1] + F[f2]) + w * mid[inner]

    # ── point update
    if linear:
        V = A
    else:
        # F_avg: average of adjacent face points. Uses the point->prim CSR
        pp_cnt = np.diff(t.pt_prim_off)
        pp_src = np.repeat(np.arange(npt, dtype=np.int64), pp_cnt)
        Favg = _avg_by(pp_src, F[t.pt_prim.astype(np.int64)], npt)
        # R_avg: average of adjacent edge midpoints
        pe_cnt = np.diff(t.pt_edge_off)
        pe_src = np.repeat(np.arange(npt, dtype=np.int64), pe_cnt)
        Ravg = _avg_by(pe_src, mid[t.pt_edge.astype(np.int64)], npt)
        val = np.maximum(pe_cnt, 1).astype(np.float64)[:, None]
        V = (Favg + 2.0 * Ravg + (val - 3.0) * A) / val
        V = np.where((pe_cnt == 0)[:, None], A, V)
        bnd, on_crease = _boundary_update(A, t, crease, npt, boundary)
        V = _blend_crease(V, bnd, on_crease, sharp, t, npt)

    NEW = np.concatenate([V, F, E], 0)               # (npt+nf+ne, C)
    P_new = NEW

    # ── topology: each corner emits a quad [v, E(next edge), F(this face), E(previous edge)]
    e_next = t.he_edge[np.arange(nv)].astype(np.int64)
    prev = np.empty(nv, np.int64)
    prev[nxt] = np.arange(nv, dtype=np.int64)
    e_prev = t.he_edge[prev].astype(np.int64)
    quads = np.stack([vp,                            # original point
                      npt + nf + e_next,             # edge point of the next edge
                      npt + vprim,                   # face point of this face
                      npt + nf + e_prev], 1)         # edge point of the previous edge

    out = Geometry()
    out._resize_points(npt + nf + ne)
    off = 0
    for k, c, dt in zip(names, cols, dts):
        col = P_new[:, off:off + c]
        out.set(POINT, k, (np.rint(col) if dt.kind in "iub" else col
                           ).astype(dt), owned=True)
        off += c
    _carry_strings(geo, out, vp[geo.prim_offset[:-1].astype(np.int64)], ep)

    out.set_topology(quads.reshape(-1).astype(np.int32),
                     (np.arange(nv + 1, dtype=np.int32) * 4),
                     np.ones(nv, bool),
                     np.full(nv, PRIM_POLY, geo.prim_type.dtype))

    # ── vertex attributes: corner / next edge midpoint / face average / previous edge midpoint, linear interpolation
    for k, v in geo.attribs[VERTEX].items():
        if is_string(v):
            out.set(VERTEX, k, np.repeat(np.asarray(v)[:, 0], 4
                                         ).reshape(-1, 1), owned=True)
            continue
        a = v.astype(np.float64)
        face_avg = _avg_by(vprim, a, nf)
        cn = 0.5 * (a + a[nxt])                      # midpoint from this corner -> the next corner
        cp = 0.5 * (a + a[prev])
        stacked = np.stack([a, cn, face_avg[vprim], cp], 1).reshape(-1,
                                                                    a.shape[1])
        out.set(VERTEX, k, (np.rint(stacked) if v.dtype.kind in "iub"
                            else stacked).astype(v.dtype), owned=True)

    if has_w:
        # child edge weight = s − 1. The four half-edges of corner [v, E_next, F, E_prev]: v->E_next is a child of e_next,
        # E_prev->v is a child of e_prev, and the middle two are new interior edges (0)
        ch = np.maximum(s_attr - 1.0, 0.0)
        z = np.zeros(nv)
        cw = np.stack([ch[e_next], z, z, ch[e_prev]], 1).reshape(-1, 1)
        out.set(VERTEX, str(crease_attribute).strip(),
                cw.astype(geo.get(VERTEX, str(crease_attribute).strip()).dtype),
                owned=True)
    _carry_groups(geo, out, vp, vprim, ep, npt, nf, ne, nv)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[vprim], owned=True)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.edge_groups = _split_edge_groups(geo, t, npt, nf)
    return out


# ══════════════════════════════════════════════════════════ Loop
def _loop_once(geo, crease_group="", auto_angle=-1.0,
               boundary="edge_corner", crease_attribute=""):
    sizes = geo.prim_sizes()
    if geo.nprims and not np.all(sizes == 3):
        bad = int(np.count_nonzero(sizes != 3))
        raise ValueError(
            f"Loop subdivision takes only triangles; {bad} primitives here are not triangles. "
            f"Connect a Divide (PCG) to triangulate first, or use Catmull-Clark instead.")
    t = topology(geo)
    npt, nf, ne, _nv = geo.npoints, geo.nprims, t.nedges, geo.nvertices
    if nf == 0 or ne == 0:
        return geo.copy()

    names, cols, dts, A = _point_stack(geo)
    vp = geo.vertex_point.astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)
    sharp, s_attr, has_w = _crease_sharpness(geo, t, crease_group, auto_angle,
                                             boundary, crease_attribute)
    crease = sharp > 0
    ep = t.edge_points.astype(np.int64)

    # ── edge points: interior 3/8(a+b) + 1/8(c+d), c/d being the opposite vertices of the triangles on both sides
    mid = 0.5 * (A[ep[:, 0]] + A[ep[:, 1]])
    E = mid.copy()
    inner = np.nonzero((t.edge_count == 2) & (sharp < 1))[0]
    if len(inner):
        h1 = t.edge_he[t.edge_he_off[inner]].astype(np.int64)
        h2 = t.edge_he[t.edge_he_off[inner] + 1].astype(np.int64)
        # in a triangle, the "opposite vertex" of a half-edge is the next point of its next half-edge
        opp1 = vp[nxt[nxt[h1]]]
        opp2 = vp[nxt[nxt[h2]]]
        w = sharp[inner][:, None]
        E[inner] = (1.0 - w) * (0.375 * (A[ep[inner, 0]] + A[ep[inner, 1]])
                                + 0.125 * (A[opp1] + A[opp2])) + w * mid[inner]

    # ── point update: Warren's β. 3/16 for n=3, otherwise 3/(8n)
    pe_cnt = np.diff(t.pt_edge_off)
    pe_src = np.repeat(np.arange(npt, dtype=np.int64), pe_cnt)
    nbr_sum = np.stack(
        [np.bincount(pe_src,
                     weights=(A[ep[:, 0]] + A[ep[:, 1]]
                              )[t.pt_edge.astype(np.int64), c]
                     - A[np.repeat(np.arange(npt), pe_cnt), c],
                     minlength=npt)
         for c in range(A.shape[1])], 1)
    n = np.maximum(pe_cnt, 1).astype(np.float64)
    beta = np.where(pe_cnt == 3, 3.0 / 16.0, 3.0 / (8.0 * n))
    V = (1.0 - n * beta)[:, None] * A + beta[:, None] * nbr_sum
    V = np.where((pe_cnt == 0)[:, None], A, V)
    bnd, on_crease = _boundary_update(A, t, crease, npt, boundary)
    V = _blend_crease(V, bnd, on_crease, sharp, t, npt)

    NEW = np.concatenate([V, E], 0)
    out = Geometry()
    out._resize_points(npt + ne)
    off = 0
    for k, c, dt in zip(names, cols, dts):
        col = NEW[:, off:off + c]
        out.set(POINT, k, (np.rint(col) if dt.kind in "iub" else col
                           ).astype(dt), owned=True)
        off += c
    for k, v in geo.attribs[POINT].items():
        if is_string(v):
            s = np.asarray(v)[:, 0]
            out.set(POINT, k, np.concatenate([s, s[ep[:, 0]]]
                                             ).reshape(-1, 1), owned=True)

    # ── one into four: three corner triangles + the middle one
    c0 = geo.prim_offset[:-1].astype(np.int64)
    c1, c2 = c0 + 1, c0 + 2
    e0 = npt + t.he_edge[c0].astype(np.int64)        # v0-v1
    e1 = npt + t.he_edge[c1].astype(np.int64)        # v1-v2
    e2 = npt + t.he_edge[c2].astype(np.int64)        # v2-v0
    v0, v1, v2 = vp[c0], vp[c1], vp[c2]
    tris = np.concatenate([
        np.stack([v0, e0, e2], 1), np.stack([v1, e1, e0], 1),
        np.stack([v2, e2, e1], 1), np.stack([e0, e1, e2], 1)], 0)
    src = np.tile(np.arange(nf, dtype=np.int64), 4)
    order = np.argsort(src, kind="stable")           # stable sort by source face
    tris, src = tris[order], src[order]
    out.set_topology(tris.reshape(-1).astype(np.int32),
                     np.arange(4 * nf + 1, dtype=np.int32) * 3,
                     np.ones(4 * nf, bool),
                     np.full(4 * nf, PRIM_POLY, geo.prim_type.dtype))

    # ── vertex attributes: corners keep original values, edge points take the average of the corners at both ends
    corner_of = np.stack([c0, c1, c2], 1)
    for k, v in geo.attribs[VERTEX].items():
        if is_string(v):
            s = np.asarray(v)[:, 0]
            blocks = [s[corner_of[:, i]] for i in (0, 1, 2)]
            arr = np.concatenate([
                np.stack([blocks[0], blocks[0], blocks[0]], 1),
                np.stack([blocks[1], blocks[1], blocks[1]], 1),
                np.stack([blocks[2], blocks[2], blocks[2]], 1),
                np.stack([blocks[0], blocks[1], blocks[2]], 1)], 0)[order]
            out.set(VERTEX, k, arr.reshape(-1, 1), owned=True)
            continue
        a = v.astype(np.float64)
        m01 = 0.5 * (a[c0] + a[c1])
        m12 = 0.5 * (a[c1] + a[c2])
        m20 = 0.5 * (a[c2] + a[c0])
        arr = np.concatenate([
            np.stack([a[c0], m01, m20], 1), np.stack([a[c1], m12, m01], 1),
            np.stack([a[c2], m20, m12], 1), np.stack([m01, m12, m20], 1)],
            0)[order].reshape(-1, a.shape[1])
        out.set(VERTEX, k, (np.rint(arr) if v.dtype.kind in "iub"
                            else arr).astype(v.dtype), owned=True)

    if has_w:
        # half-edges of the four triangles: in [v0,e0,e2], v0->e0 is a child of edge 0 and e2->v0 of edge 2;
        # the other two corner triangles rotate likewise; the middle one is all new interior edges
        ch = np.maximum(s_attr - 1.0, 0.0)
        s0 = ch[t.he_edge[c0].astype(np.int64)]
        s1 = ch[t.he_edge[c1].astype(np.int64)]
        s2 = ch[t.he_edge[c2].astype(np.int64)]
        z = np.zeros(nf)
        cw = np.concatenate([np.stack([s0, z, s2], 1), np.stack([s1, z, s0], 1),
                             np.stack([s2, z, s1], 1), np.stack([z, z, z], 1)],
                            0)[order].reshape(-1, 1)
        nm = str(crease_attribute).strip()
        out.set(VERTEX, nm, cw.astype(geo.get(VERTEX, nm).dtype), owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, np.concatenate([v, v[ep[:, 0]] & v[ep[:, 1]]]))
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[src])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[src], owned=True)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.edge_groups = _split_edge_groups(geo, t, npt, 0)
    return out


# ══════════════════════════════════════════════════════════ auxiliary data
def _carry_strings(geo, out, first_pt, ep):
    """String attributes cannot be interpolated: face points take the face's first point, edge points the edge's first endpoint."""
    for k, v in geo.attribs[POINT].items():
        if not is_string(v):
            continue
        s = np.asarray(v)[:, 0]
        out.set(POINT, k, np.concatenate([s, s[first_pt], s[ep[:, 0]]]
                                         ).reshape(-1, 1), owned=True)


def _carry_groups(geo, out, vp, vprim, ep, npt, nf, ne, nv):
    """
    Point groups: a new point joins the group only if **all its sources are in the group**.

    Using "any source in the group" would make the selection grow by one ring each subdivision round -- turning "subdivide" into
    "subdivide + expand", and those two things should be kept separate.
    """
    for k, v in geo.groups[POINT].items():
        # face point joins the group <=> no point of the face is outside the group
        fmask = np.bincount(vprim, weights=(~v[vp]).astype(np.float64),
                            minlength=nf) == 0
        out.set_group(POINT, k, np.concatenate(
            [v, fmask, v[ep[:, 0]] & v[ep[:, 1]]]))
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[vprim])
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, np.repeat(v, 4))


def _split_edge_groups(geo, t, npt, nf):
    """An original edge (a,b) becomes (a, E) and (E, b) -- so creases are not lost after one subdivision."""
    if not geo.edge_groups:
        return {}
    base = npt + nf
    ep = t.edge_points.astype(np.int64)
    k2 = ep[:, 0] * (geo.npoints + 1) + ep[:, 1]
    out = {}
    for name, pairs in geo.edge_groups.items():
        if not len(pairs):
            out[name] = np.zeros((0, 2), np.int32)
            continue
        key = np.sort(np.asarray(pairs, np.int64), axis=1)
        k1 = key[:, 0] * (geo.npoints + 1) + key[:, 1]
        hit = np.nonzero(np.isin(k2, k1))[0]
        mids = base + hit
        out[name] = np.concatenate([
            np.stack([ep[hit, 0], mids], 1),
            np.stack([mids, ep[hit, 1]], 1)]).astype(np.int32)
    return out


# ══════════════════════════════════════════════════════════ entry
def subdivide(geo, depth=1, algorithm="catmull_clark", group="",
              crease_group="", auto_crease_angle=-1.0,
              boundary="edge_corner", output_crease_group="",
              crease_attribute="creaseweight"):
    """
    Subdivide. depth is the iteration count -- face count grows by 4^depth, think twice above 3.

    With a non-empty group **only the selected faces are subdivided**: the selection is split off, subdivided on its own, then merged back with the untouched part.
    T-vertices are left at the border (one side subdivided, the other not), the same as Houdini -- a clean
    transition needs adaptive subdivision, which is a different thing altogether.
    """
    if geo is None:
        return Geometry()
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Algorithm must be one of {ALGORITHMS}")
    if boundary not in BOUNDARY:
        raise ValueError(f"Boundary must be one of {BOUNDARY}")
    d = int(depth)
    if d <= 0 or geo.nprims == 0:
        return geo.copy()
    if d > 6:
        raise ValueError(
            f"Depth={d} would multiply the face count by {4 ** d} -- this is almost certainly a slip. "
            f"The limit is 6.")

    if str(group or "").strip():
        return _subdivide_group(geo, d, algorithm, group, crease_group,
                                auto_crease_angle, boundary,
                                output_crease_group, crease_attribute)

    g = geo
    for _ in range(d):
        g = (_loop_once(g, crease_group, auto_crease_angle, boundary,
                        crease_attribute)
             if algorithm == "loop"
             else _cc_once(g, algorithm == "linear", crease_group,
                           auto_crease_angle, boundary, crease_attribute))
    if str(output_crease_group or "").strip():
        t = topology(g)
        cr = _crease_edges(g, t, crease_group, auto_crease_angle,
                           boundary)
        g = g.copy()
        g.set_edge_group(str(output_crease_group).strip(),
                         t.edge_points[cr])
    return g


def _subdivide_group(geo, depth, algorithm, group, crease_group, auto_angle,
                     boundary, out_crease, crease_attribute="creaseweight"):
    """Subdivide only some of the faces: split off, subdivide, merge back."""
    from .ops import delete_prims, merge
    sel = resolve(geo, PRIM, group)
    if sel.all():
        return subdivide(geo, depth, algorithm, "", crease_group, auto_angle,
                         boundary, out_crease, crease_attribute)
    if not sel.any():
        return geo.copy()
    part = delete_prims(geo, sel)
    rest = delete_prims(geo, ~sel)
    part = subdivide(part, depth, algorithm, "", crease_group, auto_angle,
                     boundary, out_crease, crease_attribute)
    return merge(rest, part)


# ══════════════════════════════════════════════════════════ Crease(pcg79)
CREASE_MODES = ("set", "add", "multiply", "max")


def crease(geo, edges="", weight=2.0, mode="set", attribute="creaseweight"):
    """
    Write crease weights on the selected edges (a vertex attribute, written on the start vertex of each half-edge -- the two faces on either side of an edge
    each have a half-edge, both are written). edges is an edge group (empty = all edges).
    mode: set overwrites / add adds / multiply multiplies / max takes the larger. If the attribute does not exist, an all-zero one is created first.
    Returns (geometry, report).
    """
    from .groups import resolve_edges, edge_mask
    if mode not in CREASE_MODES:
        raise ValueError(f"Mode must be one of {CREASE_MODES}")
    nm = str(attribute).strip()
    if not nm:
        raise ValueError("Attribute needs a name")
    t = topology(geo)
    sel = edge_mask(geo, resolve_edges(geo, edges))
    a = geo.get(VERTEX, nm)
    if a is not None and is_string(a):
        raise TypeError(f"Vertex attribute '{nm}' is a string")
    W = (np.asarray(a, np.float64)[:, 0].copy() if a is not None
         else np.zeros(geo.nvertices))
    he = np.nonzero(t.he_valid)[0]
    he = he[sel[t.he_edge[he].astype(np.int64)]]
    w = float(weight)
    if mode == "set":
        W[he] = w
    elif mode == "add":
        W[he] += w
    elif mode == "multiply":
        W[he] *= w
    else:
        W[he] = np.maximum(W[he], w)
    g = geo.copy()
    g.set(VERTEX, nm, np.maximum(W, 0.0).astype(np.float32).reshape(-1, 1),
          owned=True)
    return g, {"edges": int(sel.sum()), "half_edges": int(len(he))}
