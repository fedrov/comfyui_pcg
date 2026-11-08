"""
Plane clipping -- the Clip SOP, plus Divide's Bricker option.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What is really valuable here is the "corner reference", not the clipping itself
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A cut **creates new points**, and every attribute on a new point has to be interpolated from the two ends -- position, normal, UV,
point groups, edge groups, none can be left out. divide.py's "corners of new faces point back to original corners" is not enough
here; it can only express "pick an existing corner".

So here each corner is written as **(a, b, t)**:

    t == 0        it is the original corner a
    0 < t < 1     a new corner interpolated between corners a and b

_build_flat() turns these references into geometry in one go: point attributes interpolated by t, vertex attributes interpolated along this face's
own traversal direction, point groups take the intersection of the two ends, cut edge groups are split into several segments. Any operator that can
emit corner references never has to write attribute interpolation again.

**New points are deduplicated by "edge + parameter", and the parameter is always computed in the (lower point number, higher point number) direction.**
This is the only guarantee that both sides of a cut share the same point: two adjacent faces traverse the same edge in opposite directions, and the
t each computes is t and 1-t, which in floating point are not guaranteed to be exactly complementary; normalized to the canonical direction, both sides compute
the same key and coordinates bit for bit. Get this wrong and the cut looks fine, until a Fuse reveals the seam is full of duplicate points.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two implementation trade-offs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) Concave faces are ear-clipped before cutting. Sutherland-Hodgman is only correct for convex polygons; concave polygons come out
   self-intersecting (the two sides of the cut joined by a zero-width "bridge"). Triangles are always convex, so concave faces are ear-clipped first.
   The cost is that cut concave faces become a pile of triangles; if needed, connect Divide's Remove Shared Edges downstream
   to merge them back -- the two nodes are meant to be used together anyway.

2) Bricker = calling clip one cut at a time. With several consecutive cuts, the second cut's points land on **new edges** made by the first
   cut, and (a,b,t) can only express points on original edges. Rather than upgrading the representation to "carry around
   a whole row of interpolated attribute values", the geometry is rebuilt after every cut -- that way the next cut always faces
   a well-formed Geometry, corner references are always valid, and shared points always match up.
   The cost is one rebuild per cut, but faces that don't straddle take the fully vectorized fast path, so it is cheap in practice.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import euler_matrix, _gather_blocks, delete_points
from .divide import _ear_clip, _plane_basis, convex_mask

MAX_PRIMS = 4_000_000           # Bricker's fragment limit, so a too-fine grid doesn't blow up memory


# ═══════════════════════════════════════════════════════════ corner references -> geometry
def _build_flat(geo, A, B, T, sizes, src_prim, closed, share_points=True):
    """
    A/B/T : (NV',) reference of each new corner. T==0 means "it is the original corner A"
    sizes / src_prim / closed : corner count / source face / closed or not, for each new face

    With share_points=False cut points are not deduplicated; each place gets its own new point -- corresponding to Houdini Bricker
    with Shared Edges turned off.
    """
    A = np.asarray(A, np.int64)
    B = np.asarray(B, np.int64)
    T = np.asarray(T, np.float64)
    sizes = np.asarray(sizes, np.int64)
    src_prim = np.asarray(src_prim, np.int64)
    closed = np.asarray(closed, bool)
    if not len(sizes):
        out = geo.copy()
        out.set_topology(np.zeros(0, np.int32), np.zeros(1, np.int32),
                         np.zeros(0, bool))
        out.attribs[VERTEX], out.attribs[PRIM] = {}, {}
        out.groups[VERTEX], out.groups[PRIM] = {}, {}
        return out

    vp = geo.vertex_point
    new = T > 0.0

    pa, pb = vp[A], vp[B]
    lo = np.minimum(pa, pb)
    hi = np.maximum(pa, pb)
    tt = np.where(pa <= pb, T, 1.0 - T)          # parameter always in lower point -> higher point direction

    if new.any():
        idx_new = np.nonzero(new)[0]
        if share_points:
            key = np.stack([lo[idx_new], hi[idx_new],
                            np.round(tt[idx_new] * 1e9)], 1).astype(np.int64)
            uniq, inv = np.unique(key, axis=0, return_inverse=True)
            inv = inv.reshape(-1)
            nnew = len(uniq)
            first = np.zeros(nnew, np.int64)      # each new point takes the first reference where it appears
            first[inv[::-1]] = np.arange(len(inv) - 1, -1, -1)
            rep = idx_new[first]
        else:
            nnew = len(idx_new)
            inv = np.arange(nnew, dtype=np.int64)
            rep = idx_new
        n_lo, n_hi = lo[rep], hi[rep]
        n_t = tt[rep][:, None]
    else:
        nnew, inv = 0, np.zeros(0, np.int64)
        n_lo = n_hi = np.zeros(0, np.int64)
        n_t = np.zeros((0, 1))

    corner_point = vp[A].astype(np.int64).copy()
    if nnew:
        corner_point[new] = geo.npoints + inv

    out = Geometry()
    out._resize_points(geo.npoints + nnew)
    out.set_topology(corner_point.astype(np.int32),
                     np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                     closed, geo.prim_type[src_prim])

    # ---- point attributes: old points unchanged, new points interpolated in the canonical direction ----
    for k, v in geo.attribs[POINT].items():
        if nnew == 0:
            out.set(POINT, k, v)
        elif is_string(v):                        # strings can't be interpolated, take the nearer end
            add = np.where(n_t[:, 0] < 0.5, v[n_lo, 0], v[n_hi, 0])
            out.set(POINT, k, np.concatenate([v[:, 0], add])[:, None])
        else:
            add = (v[n_lo].astype(np.float64) * (1 - n_t)
                   + v[n_hi].astype(np.float64) * n_t)
            out.set(POINT, k, np.concatenate([v, add.astype(v.dtype)]),
                    owned=True)
    for k, v in geo.groups[POINT].items():
        # A cut point is in the group only if both ends are -- otherwise a cut would spread the group along the seam for no reason
        add = (v[n_lo] & v[n_hi]) if nnew else np.zeros(0, bool)
        out.set_group(POINT, k, np.concatenate([v, add]))

    # ---- vertex attributes: interpolated along this face's own traversal direction ----
    Tc = T[:, None]
    for k, v in geo.attribs[VERTEX].items():
        if is_string(v):
            out.set(VERTEX, k, np.where(Tc < 0.5, v[A], v[B]))
        else:
            out.set(VERTEX, k, (v[A].astype(np.float64) * (1 - Tc)
                                + v[B].astype(np.float64) * Tc
                                ).astype(v.dtype), owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, np.where(new, v[A] & v[B], v[A]))

    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[src_prim], owned=True)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[src_prim])
    out.prim_data = geo.remap_prim_data(src_prim)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])

    # ---- edge groups: a cut edge is split into several segments ----
    if geo.edge_groups:
        cuts = {}
        for i in range(nnew):
            cuts.setdefault((int(n_lo[i]), int(n_hi[i])), []).append(
                (float(n_t[i, 0]), geo.npoints + i))
        for name, pairs in geo.edge_groups.items():
            outp = []
            for p, q in np.asarray(pairs, np.int64).reshape(-1, 2).tolist():
                mid = [m for _, m in sorted(cuts.get((min(p, q), max(p, q)), []))]
                if p > q:
                    mid = mid[::-1]
                chain = [p] + mid + [q]
                outp.extend(zip(chain[:-1], chain[1:]))
            out.set_edge_group(name, np.asarray(outp, np.int32).reshape(-1, 2))
    return out


# ═══════════════════════════════════════════════════════════════ cutting a single face
def _sh(corners, d, side, eps):
    """
    Sutherland-Hodgman, keeping the side where side*d >= 0. corners are **original corner indices**,
    d is each corner's signed distance. Only correct for convex polygons -- concave faces are ear-clipped by the caller first.
    """
    n = len(corners)
    out = []
    for i in range(n):
        j = (i + 1) % n
        dc, dn = d[i] * side, d[j] * side
        if dc >= -eps:
            out.append((corners[i], corners[i], 0.0))
        if (dc > eps and dn < -eps) or (dc < -eps and dn > eps):
            t = dc / (dc - dn)
            out.append((corners[i], corners[j],
                        float(min(max(t, 1e-9), 1 - 1e-9))))
    return out if len(out) >= 3 else []


def _sh_open(corners, d, side, eps):
    """Polyline version: keeps the continuous runs on this side, each run becoming its own polyline."""
    n = len(corners)
    runs, cur = [], []
    for i in range(n):
        if d[i] * side >= -eps:
            cur.append((corners[i], corners[i], 0.0))
        if i + 1 < n:
            dc, dn = d[i] * side, d[i + 1] * side
            if (dc > eps and dn < -eps) or (dc < -eps and dn > eps):
                t = dc / (dc - dn)
                cut = (corners[i], corners[i + 1],
                       float(min(max(t, 1e-9), 1 - 1e-9)))
                cur.append(cut)
                if len(cur) >= 2:
                    runs.append(cur)
                cur = [cut]
    if len(cur) >= 2:
        runs.append(cur)
    return runs


# ═══════════════════════════════════════════════════════════════ Clip
def clip_plane(geo, normal, origin, group_mask=None, keep="below",
               eps=None, share_points=True, dpt=None, info=None):
    """
    Cuts with one plane; returns (new geometry, which side of the plane each new face is on).

    keep: below / above / both. Faces outside the group are kept as they are, not cut at all.
    This is the kernel shared by Clip and Bricker -- the upper layer only computes planes and collects groups.

    If dpt is given it is used as each **point**'s signed distance to the plane (Clip Attribute / Snapping Tolerance
    both compute the distance in the upper layer and pass it in); otherwise it is computed from P. info is a dict; if given,
    `cut` is written into it: whether each new face was produced by this cut (needed by the Clipped Primitives group).
    """
    n = np.asarray(normal, np.float64).reshape(3)
    ln = float(np.linalg.norm(n))
    if ln < 1e-12:
        raise ValueError("The clipping plane normal cannot be a zero vector.")
    n = n / ln
    o = np.asarray(origin, np.float64).reshape(3)
    P = geo.get(POINT, "P").astype(np.float64)
    # One distance per **point**
    dpt = (P - o) @ n if dpt is None else np.asarray(dpt, np.float64).reshape(-1)
    if eps is None:
        mn, mx = geo.bbox()
        eps = max(float(np.max(np.abs(np.asarray(mx, np.float64)
                                      - np.asarray(mn, np.float64)))), 1.0) * 1e-9

    sel = (np.ones(geo.nprims, bool) if group_mask is None
           else np.asarray(group_mask, bool))
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    vprim = geo.vertex_prim()
    dv = dpt[geo.vertex_point]
    lo = np.full(geo.nprims, np.inf)
    hi = np.full(geo.nprims, -np.inf)
    np.minimum.at(lo, vprim, dv)
    np.maximum.at(hi, vprim, dv)

    want = {"below": -1, "above": 1, "both": 0}[keep]
    straddle = sel & (lo < -eps) & (hi > eps)
    side = np.where(lo >= -eps, 1, -1)             # which side the non-straddling faces are on
    # Faces carried over unchanged: those outside the group are always kept (the group means "cut only these"),
    # non-straddling faces inside the group depend on whether they are on the kept side
    intact = ~straddle & (~sel | (want == 0) | (side == want))

    keep_idx = np.nonzero(intact)[0]
    parts_A = [_gather_blocks(starts[keep_idx], sizes[keep_idx])]
    parts_size = [sizes[keep_idx]]
    parts_src = [keep_idx]
    parts_closed = [geo.prim_closed[keep_idx]]
    parts_side = [np.where(sel[keep_idx], side[keep_idx], 0)]

    conv = convex_mask(geo)
    loop_A, loop_B, loop_T = [], [], []
    loop_size, loop_src, loop_closed, loop_side = [], [], [], []
    for i in np.nonzero(straddle)[0]:
        s, e = int(starts[i]), int(starts[i] + sizes[i])
        corners = list(range(s, e))
        d = [float(dpt[geo.vertex_point[c]]) for c in corners]
        is_closed = bool(geo.prim_closed[i])

        pieces = []                                # (refs, side)
        if not is_closed:
            if want <= 0:
                pieces += [(r, -1) for r in _sh_open(corners, d, -1, eps)]
            if want >= 0:
                pieces += [(r, +1) for r in _sh_open(corners, d, +1, eps)]
        elif conv[i]:
            for sd in ((-1, +1) if want == 0 else (want,)):
                r = _sh(corners, d, sd, eps)
                if r:
                    pieces.append((r, sd))
        else:
            # Concave face: ear-clip into triangles first then cut each; triangles are always convex
            tris = _ear_clip(_plane_basis(geo.get(POINT, "P")[geo.prim_points(i)]))
            for t in tris:
                tc = [corners[x] for x in t]
                td = [d[x] for x in t]
                for sd in ((-1, +1) if want == 0 else (want,)):
                    r = _sh(tc, td, sd, eps)
                    if r:
                        pieces.append((r, sd))
        for refs, sd in pieces:
            arr = np.asarray(refs, np.float64)
            loop_A.append(arr[:, 0]); loop_B.append(arr[:, 1]); loop_T.append(arr[:, 2])
            loop_size.append(len(refs))
            loop_src.append(i)
            loop_closed.append(is_closed and len(refs) >= 3)
            loop_side.append(sd)

    # Untouched faces: A/B are both its own corners, T=0
    keep_corner = parts_A[0]
    A = np.concatenate([keep_corner] + loop_A)
    B = np.concatenate([keep_corner] + loop_B)
    T = np.concatenate([np.zeros(len(keep_corner))] + loop_T)
    sz = np.concatenate(parts_size + [np.asarray(loop_size, np.int64)])
    sp = np.concatenate(parts_src + [np.asarray(loop_src, np.int64)])
    cl = np.concatenate(parts_closed + [np.asarray(loop_closed, bool)])
    sd = np.concatenate(parts_side + [np.asarray(loop_side, np.int64)])

    order = np.argsort(sp, kind="stable")          # new faces sorted back into the positions of their source faces
    if info is not None:
        info["cut"] = (np.arange(len(sp)) >= len(keep_idx))[order]
    off = np.concatenate([[0], np.cumsum(sz)])[:-1]
    gather = _gather_blocks(off[order], sz[order])
    out = _build_flat(geo, A[gather], B[gather], T[gather], sz[order],
                      sp[order], cl[order], share_points)

    # Points left behind by the cut-away half must be removed. Only those "used before, unused now"; points that were already isolated
    # stay -- isolated points are valid geometry and must not be punished along with them.
    was = np.zeros(geo.npoints, bool)
    if geo.nvertices:
        was[geo.vertex_point] = True
    now = np.zeros(out.npoints, bool)
    if out.nvertices:
        now[out.vertex_point] = True
    lost = np.zeros(out.npoints, bool)
    lost[:geo.npoints] = was & ~now[:geo.npoints]
    if lost.any():
        # Only unreferenced points are deleted, so no prim disappears because of it and the side mapping is unchanged
        out = delete_points(out, ~lost)
    return out, sd[order]


ORIENTS = ("direction", "transform")


def _plane_coords(geo, name):
    """Clip Attribute -> (npoints,3) float64 "coordinates". Docs: the first three components are used as X Y Z,
    padded with 0 if fewer than three (a single-component attribute only looks at the plane's intersection with the X axis)."""
    a = geo.get(POINT, name)
    if a is None:
        have = sorted(geo.attribs[POINT].keys())
        raise KeyError(f"No Clip Attribute '{name}' on points. Existing: {have}")
    if is_string(a):
        raise ValueError(f"Clip Attribute '{name}' is a string attribute and cannot be clipped by.")
    X = np.zeros((geo.npoints, 3), np.float64)
    k = min(3, a.shape[1])
    X[:, :k] = a[:, :k]
    return X, k


def _seam_loops(geo, sub, on):
    """
    The **openings** of the faces in sub along the plane, joined into loops. Returns (list of loops, number of edges that couldn't be joined into a loop).

    Opening edges = edges with both ends on the plane that are used by only one face in sub. Faces lying entirely
    on the plane (on whichever side) don't own openings, and the edges they occupy aren't openings either -- there
    is already a face there, nothing to fill. Loops run **opposite** to the half-edge of the adjacent face, so the filled face has
    the same winding as it and its normal points outward.
    """
    vp = geo.vertex_point.astype(np.int64)
    nxt = geo.next_corner()
    vprim = geo.vertex_prim()
    a, b = vp, vp[nxt]
    flat = np.bincount(vprim[~on[vp]], minlength=geo.nprims) == 0     # all corners on the plane
    edge = np.asarray(geo.prim_closed, bool)[vprim] & on[a] & on[b] & (a != b)
    key = np.minimum(a, b) * (geo.npoints + 1) + np.maximum(a, b)
    # The edges of faces lying on the plane are also in this "occupied" table, so they are excluded too
    m = edge & sub[vprim] & ~np.isin(key, key[edge & flat[vprim]])
    a, b, key = a[m], b[m], key[m]
    if not len(a):
        return [], 0
    _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    one = cnt[inv.reshape(-1)] == 1
    a, b = a[one], b[one]
    # Filled faces run b -> a. A point can have more than one outgoing edge (two openings meeting at this point): on walking back to
    # a point already visited on this path, the loop in between is cut off as its own loop
    nxt_of = {}
    for p, q in zip(a.tolist(), b.tolist()):
        nxt_of.setdefault(q, []).append(p)
    loops, used = [], 0
    while nxt_of:
        start = next(iter(nxt_of))
        path, pos, cur = [start], {start: 0}, start
        while cur in nxt_of:
            cand = nxt_of[cur]
            n_ = cand.pop()
            if not cand:
                del nxt_of[cur]
            if n_ in pos:
                k = pos[n_]
                # At least 3 points: 1 is impossible (a != b), 2 would have to be the same edge once each way,
                # and such edges were already filtered out above as "used twice"
                lp = path[k:]
                loops.append(lp)
                used += len(lp)
                for x in lp[1:]:
                    del pos[x]
                path = path[:k + 1]
            else:
                pos[n_] = len(path)
                path.append(n_)
            cur = n_
    return loops, int(len(a) - used)


def _in_poly(q, poly):
    """Whether a point is inside a 2-D polygon (ray casting)."""
    x, y = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    c = (y > q[1]) != (y2 > q[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = x + (q[1] - y) * (x2 - x) / (y2 - y)
    return bool(np.count_nonzero(c & (q[0] < xi)) % 2)


def _cap_faces(geo, sub, on, X, n_cap):
    """
    Fill Polygons along Clipping Plane: fills the openings of the faces in sub with faces whose normals point along n_cap.
    Returns (point-number lists of the faces, number not filled).

    Loops counter-clockwise around n_cap are outer contours, clockwise ones are holes (the direction of the opening edges already guarantees this).
    A prim has only one vertex loop and can't hold a face with holes, so a hole is merged into the outer contour enclosing it
    with a "bridge" walked twice there and back (bridged between the closest pair of points) -- area and normal are correct,
    and downstream triangulation accepts it. Where two openings meet at a point they are cut apart there and filled separately.
    Holes with no outer contour found, and edges that can't be joined into loops, are not filled; their counts are returned.
    """
    loops, bad = _seam_loops(geo, sub, on)
    if not loops:
        return [], bad
    u, v = _plane_axes(n_cap)
    outer, holes = [], []
    for lp in loops:
        q = np.stack([X[lp] @ u, X[lp] @ v], 1)
        ar = 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], -1)
                                - np.roll(q[:, 0], -1) * q[:, 1]))
        (outer if ar > 0 else holes).append([list(lp), q, abs(ar)])
    for lp, q, _ in holes:
        host = [o for o in outer if _in_poly(q[0], o[1])]
        if not host:
            bad += 1
            continue
        h = min(host, key=lambda o: o[2])           # the innermost ring
        d = np.linalg.norm(h[1][:, None, :] - q[None, :, :], axis=2)
        i, j = np.unravel_index(int(np.argmin(d)), d.shape)
        h[0] = h[0][:i + 1] + lp[j:] + lp[:j + 1] + h[0][i:]
        h[1] = np.concatenate([h[1][:i + 1], q[j:], q[:j + 1], h[1][i:]])
    return [o[0] for o in outer], bad


def _plane_axes(n):
    """A pair of orthogonal axes (u, v) in the plane, u x v = n."""
    n = np.asarray(n, np.float64)
    t = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(t, n)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _split_sides(geo, side):
    """
    Split Connectivity: points used by faces on both the upper and lower sides (only those riding on the plane -- a face
    entirely on one side shares points with the other side no farther than eps from the plane) get a separate copy for the upper side's faces, so
    the upper and lower halves are no longer connected. Faces outside the group (side = 0) belong to neither side, and points they share are not split.
    Returns the new geometry (face order unchanged).
    """
    from .facet import _split_points
    vp = geo.vertex_point.astype(np.int64)
    vside = side[geo.vertex_prim()]
    lower = np.zeros(geo.npoints, bool)
    lower[vp[vside < 0]] = True
    move = (vside > 0) & lower[vp]
    if not move.any():
        return geo
    cls = np.where(move, vp + geo.npoints, vp)
    uniq, inv = np.unique(cls, return_inverse=True)
    return _split_points(geo, inv.reshape(-1), len(uniq))


def clip(geo, group="", direction=(0.0, 1.0, 0.0), distance=0.0,
         origin=(0.0, 0.0, 0.0), keep="below",
         above_group="", below_group="", seam_group="",
         orient="direction", translate=(0.0, 0.0, 0.0), rotate=(0.0, 0.0, 0.0),
         snap_tolerance=0.0, fill=False, split_connectivity=False,
         clip_attribute="P", clipped_group="", fill_group=""):
    """
    Counterpart of Houdini's Clip SOP: cuts geometry with a plane.

    Plane = the one through origin + distance*n with normal n. keep:
        below  keep only the half behind the normal (Houdini's default)
        above  keep only the front
        both   keep both halves, just cut along the plane -- handy with Connectivity / name

    above_group / below_group are **primitive groups** marking which side each face ends up on after the cut;
    seam_group is an **edge group** holding the edges along the cut -- connect PolyBevel or
    Edge Group Promote right after, no need to find them again. Faces outside the group are kept as they are.

    pcg100 additions (defaults = previous behaviour):
        orient=transform   the plane is given by translate / rotate instead: through translate, with normal
                           (0,1,0) rotated by rotate (order X->Y->Z). **Neither the base normal nor the rotation order
                           is documented by SideFX**; (0,1,0) is Direction's default
        snap_tolerance     points within this distance of the plane are first moved onto it before cutting (only points of faces being cut are moved)
        fill               fills the cut opening with faces (see _cap_faces). With keep=both each side gets one
        split_connectivity with keep=both the upper and lower halves no longer share the points along the cut
        clip_attribute     cuts by another point attribute instead of P (e.g. by uv)
        clipped_group      primitive group: the faces cut by this cut that were kept
        fill_group         primitive group: the filled faces
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    if orient not in ORIENTS:
        raise ValueError(f"Orient Plane with must be one of {ORIENTS}")
    if orient == "transform":
        n = euler_matrix(*np.asarray(rotate, np.float64).reshape(3)) @ np.array([0.0, 1.0, 0.0])
        base = np.asarray(translate, np.float64).reshape(3)
    else:
        n = np.asarray(direction, np.float64).reshape(3)
        base = np.asarray(origin, np.float64).reshape(3)
    ln = float(np.linalg.norm(n))
    if ln < 1e-12:
        raise ValueError("Clip's direction cannot be a zero vector.")
    n = n / ln
    o = base + n * float(distance)

    nm = str(clip_attribute).strip() or "P"
    gmask = resolve(geo, PRIM, group)
    dpt = None
    if nm != "P" or float(snap_tolerance) > 0:
        X, k = _plane_coords(geo, nm)
        dpt = (X - o) @ n
        if float(snap_tolerance) > 0:
            touched = np.zeros(geo.npoints, bool)
            touched[geo.vertex_point[gmask[geo.vertex_prim()]]] = True
            near = touched & (np.abs(dpt) <= float(snap_tolerance))
            if near.any():
                X[near] -= dpt[near, None] * n
                dpt[near] = 0.0
                a = np.array(geo.get(POINT, nm), copy=True)
                a[near, :k] = X[near, :k]
                geo = geo.copy()
                geo.set(POINT, nm, a, owned=True)

    info = {}
    out, side = clip_plane(geo, n, o, gmask, keep, dpt=dpt, info=info)
    cut = info["cut"]

    def on_plane(g):
        # The cut seam = edges with both ends on the plane
        if nm == "P":
            Q = g.get(POINT, "P").astype(np.float64)
            mn, mx = g.bbox()
            ext = np.asarray(mx, np.float64) - np.asarray(mn, np.float64)
        else:
            Q = _plane_coords(g, nm)[0]
            ext = Q.max(0) - Q.min(0) if len(Q) else np.zeros(3)
        tol = max(float(np.max(np.abs(ext))), 1.0) * 1e-6
        return Q, np.abs((Q - o) @ n) <= tol

    if split_connectivity and keep == "both" and out.nvertices:
        # When only one side is kept the other side's faces are already gone and there's nothing to split; this is stated explicitly to match the docs
        out = _split_sides(out, side)
    if seam_group.strip() and out.nvertices:
        Q, on = on_plane(out)
        vpo = out.vertex_point
        nxt = out.next_corner()
        m = on[vpo] & on[vpo[nxt]]
        pairs = np.stack([vpo[m], vpo[nxt][m]], 1)
        out.set_edge_group(seam_group.strip(),
                           pairs[pairs[:, 0] != pairs[:, 1]])
    nfill = 0
    if fill and out.nvertices:
        from .addsop import append_prims
        Q, on = on_plane(out)
        faces, fside, bad = [], [], 0
        for sd in (-1, 1):
            # The lower half's opening faces +n, the upper half's faces -n
            f, b = _cap_faces(out, side == sd, on, Q, -sd * n)
            faces += f
            fside += [sd] * len(f)
            bad += b
        if faces:
            out = append_prims(out, faces, True)
            nfill = len(faces)
            side = np.concatenate([side, np.asarray(fside, side.dtype)])
            cut = np.concatenate([cut, np.zeros(nfill, bool)])
        if bad:
            out.set(DETAIL, "clip_fill_skipped", np.array([[bad]], np.int32), owned=True)
    if above_group.strip():
        out.set_group(PRIM, above_group.strip(), side > 0)
    if below_group.strip():
        out.set_group(PRIM, below_group.strip(), side < 0)
    if str(clipped_group).strip():
        out.set_group(PRIM, str(clipped_group).strip(), cut)
    if str(fill_group).strip():
        out.set_group(PRIM, str(fill_group).strip(),
                      np.arange(out.nprims) >= out.nprims - nfill)
    return out


# ═══════════════════════════════════════════════════════════════ Bricker
def bricker(geo, group="", size=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0),
            angle=(0.0, 0.0, 0.0), shared_edges=True, max_planes=256):
    """
    Counterpart of the Divide SOP's Bricker Polygons: cuts faces into bricks with a 3-D lattice.

    The lattice is given by size / offset / angle; a family of parallel planes cuts along each of the three axes in turn.
    Each cut only ever increases the fragment count, so there is an explicit limit -- so that a size typed as 0.001
    doesn't sit there churning for half an hour.

    With shared_edges off, cut points are not deduplicated and adjacent bricks use their own points (that's what Houdini's toggle
    means); with it on, both sides of a cut share one point and the topology stays connected.
    """
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    s = np.asarray(size, np.float64).reshape(3)
    R = euler_matrix(*np.asarray(angle, np.float64).reshape(3))
    o0 = np.asarray(offset, np.float64).reshape(3)
    g = geo
    gsel = resolve(geo, PRIM, group)
    # Faces outside the group never take part; a prim attribute carries "inside the group or not" through every rebuild
    marker = "__brick_sel__"
    if not gsel.all():
        g = g.copy()
        g.set(PRIM, marker, gsel.astype(np.int32), owned=True)

    for ax in range(3):
        if s[ax] <= 0:
            continue
        nrm = np.ascontiguousarray(R[:, ax], np.float64)
        nrm = nrm / max(float(np.linalg.norm(nrm)), 1e-12)
        P = g.get(POINT, "P").astype(np.float64)
        proj = (P - o0) @ nrm
        m0 = int(np.floor(float(proj.min()) / s[ax])) + 1
        m1 = int(np.ceil(float(proj.max()) / s[ax])) - 1
        if m1 - m0 + 1 > max_planes:
            raise ValueError(
                f"Bricker would make {m1 - m0 + 1} cuts on axis {ax}, exceeding the limit "
                f"{max_planes}. Increase size, or narrow the range with group first.")
        for m in range(m0, m1 + 1):
            mask = (g.get(PRIM, marker)[:, 0] > 0 if g.has(PRIM, marker)
                    else np.ones(g.nprims, bool))
            g, _ = clip_plane(g, nrm, o0 + nrm * (m * s[ax]), mask, "both",
                              share_points=shared_edges)
            if g.nprims > MAX_PRIMS:
                raise ValueError(
                    "Bricker produced more fragments than the limit -- size is too small relative to the model.")
    if g.has(PRIM, marker):
        g = g.copy()
        g.remove(PRIM, marker)
    return g
