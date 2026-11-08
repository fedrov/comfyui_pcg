"""
Mesh booleans.

The backend is **manifold3d**, not a home-grown implementation. Reason: robust mesh booleans need exact predicates, coplanar
case handling, retriangulation along intersection lines and winding-number classification; a few hundred lines of our own would not necessarily be stable -- a crash on degenerate input (coplanar,
shared edges, near-degenerate triangles) is a crash on the user's model, and hard to track down. manifold3d
is a pure wheel with no system dependencies, and built specifically for this job.

When it can't be installed, a hint that can be followed directly is given instead of an ImportError traceback.

manifold3d requires the input to be a **closed manifold mesh**. It rejects non-closed input; here the status
is translated into plain language, pointing out common causes.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, VERTEX, DETAIL
from . import ops as _ops

_INSTALL = ("manifold3d is required. Run in ComfyUI's python environment:\n"
            "  python_embeded\\\\python.exe -m pip install manifold3d")


def _m3():
    try:
        import manifold3d
    except ImportError:
        raise RuntimeError(_INSTALL)
    return manifold3d


def to_manifold(geo: Geometry, name="Input"):
    """Geometry -> Manifold. Triangulates first and checks closedness."""
    m3 = _m3()
    tri = geo.triangles()
    if tri is None or not len(tri):
        raise RuntimeError(f"{name} has no faces; cannot do a boolean operation")
    # Must be an np.array copy, not ascontiguousarray: this package's attribute arrays are
    # writeable=False (immutability convention), and ascontiguousarray is zero-copy for already contiguous arrays,
    # so the frozen flag carries straight through -- manifold3d's nanobind binding only accepts writable
    # arrays and reports a plain argument type mismatch; nothing in the error says it is caused by read-only.
    P = np.array(geo.get(POINT, "P"), np.float32, order="C")
    T = np.array(tri, np.uint32, order="C")
    man = m3.Manifold(m3.Mesh(P, T))
    st = str(man.status())
    if "NoError" not in st:
        raise RuntimeError(
            f"{name} is not a closed manifold mesh ({st}); booleans need closed volumes.\n"
            "  Common causes: holes in faces, edges referenced by only one face, inconsistent normal orientation, overlapping faces.\n"
            "  Try a Fuse first to weld coincident points, then use Group Create's unshared edges "
            "to check for boundary edges.")
    return man


def from_manifold(man, want_origin=False):
    """
    Manifold -> Geometry. The output is a triangle mesh.

    With want_origin=True also returns the **source id** of each face. manifold3d carries this
    information itself (run_original_id, given per triangle run), exact and free -- far more reliable than guessing afterwards
    by "is the face centre closer to A or to B": near the intersection line the two distances are close anyway,
    so the guessed source is least accurate exactly there, and the intersection line is exactly what we want.
    """
    mesh = man.to_mesh()
    v = np.asarray(mesh.vert_properties, np.float32)
    t = np.asarray(mesh.tri_verts, np.int32)
    if not len(t):
        return (Geometry(), np.zeros(0, np.int64)) if want_origin else Geometry()
    g = Geometry.from_mesh(v[:, :3], t)
    if not want_origin:
        return g
    ri = np.asarray(mesh.run_index, np.int64)
    ro = np.asarray(mesh.run_original_id, np.int64)
    origin = np.zeros(len(t), np.int64)
    for k in range(len(ro)):
        origin[ri[k] // 3: ri[k + 1] // 3] = ro[k]
    return g, origin


def detriangulate(geo: Geometry, tol_deg=0.5, label=None) -> Geometry:
    """
    Merges coplanar adjacent triangles into quads.

    Only merges pairs that are **coplanar and form a convex quad** -- without the convexity check a concave pair merges into
    a self-intersecting quad that flips when triangulated downstream. Full n-gon merging needs region growing plus boundary extraction;
    here only one pairing pass is done, enough to turn the triangle soup from booleans into mostly quads.

    label: (nprims,) labels; only two triangles with the same label are merged. Booleans use it to pass the face
    source (A / B) -- a quad cannot be half in A Inside B and half in B Inside A.
    Primitive groups are carried over from the original faces (a merged quad takes the membership the two share).
    """
    from . import topology as _tp
    if geo.nprims == 0:
        return geo.copy()
    sizes = geo.prim_sizes()
    if not (sizes == 3).all():
        return geo.copy()

    t = _tp.topology(geo)
    ang = _tp.edge_angles(geo)
    P = geo.get(POINT, "P").astype(np.float64)
    vprim = geo.vertex_prim()
    nxt = geo.next_corner()

    used = np.zeros(geo.nprims, bool)
    quads, order, qcorner = [], [], []
    cand = np.nonzero((t.edge_count == 2) & (ang <= tol_deg))[0]
    # Merge the flattest edges first, so "first come, first served" doesn't split up an obviously coplanar pair
    for e in cand[np.argsort(ang[cand])]:
        h, g = t.edge_he[t.edge_he_off[e]], t.edge_he[t.edge_he_off[e] + 1]
        f1, f2 = int(vprim[h]), int(vprim[g])
        if used[f1] or used[f2]:
            continue
        if label is not None and label[f1] != label[f2]:
            continue
        a, b = int(geo.vertex_point[h]), int(geo.vertex_point[nxt[h]])
        c = int(geo.vertex_point[nxt[nxt[h]]])          # third point of f1
        d = int(geo.vertex_point[nxt[nxt[g]]])          # third point of f2
        quad = [a, c, b, d] if False else [c, a, d, b]
        Q = P[quad]
        n = np.cross(Q[1] - Q[0], Q[2] - Q[0])
        nn = np.linalg.norm(n)
        if nn < 1e-12:
            continue
        n /= nn
        # Convexity: the turns at all four edges must have the same sign
        cr = [float(np.cross(Q[(i + 1) % 4] - Q[i],
                             Q[(i + 2) % 4] - Q[(i + 1) % 4]) @ n)
              for i in range(4)]
        if min(cr) <= 0:
            continue
        used[f1] = used[f2] = True
        quads.append(quad)
        order.append(f1)
        qcorner.append([int(nxt[nxt[h]]), int(h), int(nxt[nxt[g]]), int(nxt[h])])

    if not quads:
        return geo.copy()
    keep = np.nonzero(~used)[0]
    faces = [list(geo.prim_points(i)) for i in keep] + quads
    out = Geometry.from_mesh(geo.get(POINT, "P"),
                             np.zeros((0, 3), np.int32))
    out = Geometry()
    out._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v, owned=True)
    sz = np.array([len(f) for f in faces], np.int32)
    out.set_topology(np.concatenate([np.asarray(f, np.int32) for f in faces]),
                     np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                     np.ones(len(faces), bool))
    # Edge groups must be carried over. Quad conversion deletes points no longer referenced, and delete_points also
    # remaps edge group point pairs -- if they aren't attached here, the seam group silently disappears at this step.
    out.edge_groups = dict(geo.edge_groups)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    src = np.concatenate([keep, np.asarray(order, np.int64)])
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, np.asarray(v, bool)[src])
    # prim / vertex attributes and vertex groups (pcg102, previously lost). Quad corners: c a d b
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, np.asarray(v)[src], owned=True)
    vsrc = np.concatenate(
        [np.arange(geo.prim_offset[i], geo.prim_offset[i + 1]) for i in keep]
        + [np.asarray(qcorner, np.int64).reshape(-1)]).astype(np.int64)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, np.asarray(v)[vsrc], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, np.asarray(v, bool)[vsrc])
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return _ops.delete_points(out, np.isin(np.arange(geo.npoints),
                                           out.vertex_point))


def _surface_shell(geo: Geometry, thickness: float) -> Geometry:
    """
    Thickens an open surface into a closed thin shell so it can go into a boolean.

    **Extruded opposite to the normal**, with the original faces left in place -- so after the boolean, the faces lying at the original position
    are the "cut original surface", geometrically exact, with no offset error at all. Extruding forward would push the original faces
    away, and restoring them would only be possible by projection, inaccurate for anything non-planar.

    After extrusion inside and outside are reversed overall (the front was pushed in the negative direction), so the winding is flipped once more.
    """
    g = geo if geo.get(POINT, "N") is not None else _ops.compute_normals(geo, "point")
    sh = _ops.polyextrude(g, distance=-abs(thickness), output_front=True,
                          output_back=True, output_side=True,
                          preserve_groups=False)
    return _ops.reverse_prims(sh, mode="reverse")


def _dist_to(geo: Geometry, ref: Geometry, step: float) -> np.ndarray:
    """Approximate distance from each face centre of result to the surface of ref. step controls the sampling spacing on the reference surface."""
    tri = ref.triangles()
    if tri is None or not len(tri) or geo.nprims == 0:
        return np.full(geo.nprims, np.inf)
    RP = ref.get(POINT, "P").astype(np.float64)
    a, b, c = RP[tri[:, 0]], RP[tri[:, 1]], RP[tri[:, 2]]
    # Scatter points on the reference surface, with density following the tolerance
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    step = max(float(step), 1e-6)
    cnt = np.clip(np.ceil(area / (step * step)).astype(int), 3, 4000)
    rng = np.random.default_rng(0)
    rep = np.repeat(np.arange(len(tri)), cnt)
    u, v = rng.random(len(rep)), rng.random(len(rep))
    fl = u + v > 1
    u[fl], v[fl] = 1 - u[fl], 1 - v[fl]
    samp = np.concatenate([a[rep] + u[:, None] * (b[rep] - a[rep])
                           + v[:, None] * (c[rep] - a[rep]), RP])
    ctr = _ops.prim_centers(geo).astype(np.float64)
    try:
        from scipy.spatial import cKDTree
        d = cKDTree(samp).query(ctr, workers=-1)[0]
    except ImportError:
        d = np.empty(len(ctr))
        blk = max(1, 2_000_000 // max(1, len(samp)))
        for i in range(0, len(ctr), blk):
            ch = ctr[i:i + blk]
            d[i:i + blk] = np.sqrt(
                ((ch[:, None, :] - samp[None, :, :]) ** 2).sum(-1)).min(1)
    return d


def seam_edges(res: Geometry, from_a: np.ndarray) -> np.ndarray:
    """
    Intersection lines: edges whose two sides have different sources. Returns (E,2) point pairs, usable directly as an edge group.

    This is the boundary between the A and B surfaces, which Houdini calls the A-B seam. Same-source A-A / B-B seams
    need finer face-source tracking (which original face split into which pieces); manifold3d doesn't provide that information.
    """
    from . import topology as _tp
    t = _tp.topology(res)
    if t.nedges == 0:
        return np.zeros((0, 2), np.int32)
    vprim = res.vertex_prim()
    keep = np.zeros(t.nedges, bool)
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        f1 = vprim[t.edge_he[t.edge_he_off[two]]]
        f2 = vprim[t.edge_he[t.edge_he_off[two] + 1]]
        keep[two] = from_a[f1] != from_a[f2]
    return np.asarray(t.edge_points[keep], np.int32)


def boolean(a: Geometry, b: Geometry, operation="subtract", direction="a-b",
            detri="none", detri_tol=0.5,
            group_a_inside="", group_a_outside="", group_b="",
            treat_a="solid", treat_b="solid", thickness=0.01,
            seam_group="", group_b_inside="", group_b_outside="",
            keep_attributes=True) -> Geometry:
    """
    Counterpart of Houdini's Boolean.

    operation:
      union / intersect / subtract / shatter

    direction of subtract: a-b / b-a / both (both pieces output, each in its own group)

    shatter cuts the two solids into three pieces: A^B, A-B, B-A; the three pieces share no points and, as in Houdini,
    are told apart by connectivity (connect a Connectivity / Assemble).

    Output primitive groups follow Houdini's definition, **per face**, not per piece:
      A Inside B  = faces from A that are enclosed by B      B Inside A likewise
      A Outside B = faces from A that lie outside B          B Outside A likewise
      group_b     = all faces from B (an extra of this plugin, default name bpolys)
    Before pcg85 whole pieces were grouped (the whole Union result went into aoutsideb, including B's faces),
    inconsistent with Houdini. Whether A's and B's faces in each piece are inside or outside is decided by the operation
    (e.g. the A - B piece = A's faces outside B + B's faces inside A, flipped), so
    no per-face point-in-volume test is needed; splitting A / B by the source ids manifold returns is enough.

    keep_attributes (pcg102): A's / B's point / vertex / prim attributes and groups are carried onto the result (see _carry).
    Previously the result had only P and the primitive groups above.
    """
    _m3()
    a_surf = treat_a == "surface"
    b_surf = treat_b == "surface"
    a_src, b_src = a, b
    A = to_manifold(_surface_shell(a, thickness) if a_surf else a, "Input A")
    B = to_manifold(_surface_shell(b, thickness) if b_surf else b, "Input B")
    # A Manifold constructed from a custom mesh has original_id -1; as_original() must be called first
    # to assign an id, so that run_original_id after the boolean maps back to the source.
    A, B = A.as_original(), B.as_original()
    aid, _bid = A.original_id(), B.original_id()

    # (Manifold, A's faces inside B?, B's faces inside A?)
    U, I, AB, BA = (A + B, False, False), (A ^ B, True, True), \
        (A - B, False, True), (B - A, True, False)
    if operation == "union":
        pieces = [U]
    elif operation == "intersect":
        pieces = [I]
    elif operation == "subtract":
        pieces = {"a-b": [AB], "b-a": [BA]}.get(direction, [AB, BA])
    elif operation == "seam":
        # Intersection lines only need one boolean to locate; union is the most stable: faces from both sides are present and the boundary is complete
        pieces = [U]
    elif operation == "shatter":
        pieces = [I, AB, BA]
    else:
        raise RuntimeError(f"Unknown boolean operation: {operation}")
    face_groups = [(n, frm, ins) for n, frm, ins in (
        (group_a_inside, True, True), (group_a_outside, True, False),
        (group_b_inside, False, True), (group_b_outside, False, False))
        if n and n.strip()]

    tol = max(abs(thickness) * 0.25, 1e-5)
    parts = []
    for man, a_in, b_in in pieces:
        if man.is_empty():
            continue
        g, origin = from_manifold(man, want_origin=True)
        if g.nprims == 0:
            continue

        # surface mode: keep only the faces lying on the original surface. The shell's back and side walls were added
        # temporarily so the boolean can run, and are not part of the result. An absolute tolerance works here -- the other side of the shell
        # is exactly thickness away from the original surface, far from "lying on the original face".
        if a_surf or b_surf:
            keep = np.zeros(g.nprims, bool)
            if a_surf:
                keep |= _dist_to(g, a_src, tol) <= tol
            if b_surf:
                keep |= _dist_to(g, b_src, tol) <= tol
            if keep.any():
                idx = np.nonzero(keep)[0]
                g = _ops.delete_prims(g, keep)
                origin = origin[idx]

        if operation == "seam" or seam_group:
            from_a = origin == aid
            pairs = seam_edges(g, from_a)
            if operation == "seam":
                # Intersection lines are output separately as polyline segments
                if not len(pairs):
                    continue
                P = g.get(POINT, "P")
                used = np.unique(pairs)
                remap = np.full(g.npoints, -1, np.int32)
                remap[used] = np.arange(len(used), dtype=np.int32)
                sg = Geometry.from_mesh(
                    P[used], [[int(remap[x]), int(remap[y])] for x, y in pairs],
                    closed=False)
                parts.append(sg)
                continue
            if seam_group:
                g.set_edge_group(seam_group, pairs)

        from_a = origin == aid          # seam already did continue above, so it never gets here
        if keep_attributes:
            g = _carry(g, from_a, a_src, b_src)
        for n, frm, ins in face_groups:
            hit = (from_a if frm else ~from_a) & ((a_in if frm else b_in) == ins)
            g.set_group(PRIM, n.strip(), hit)
        if group_b and group_b.strip():
            g.set_group(PRIM, group_b.strip(), ~from_a)
        if detri == "quads":
            g = detriangulate(g, detri_tol, label=from_a)
        parts.append(g)
    return _ops.merge(*parts) if parts else Geometry()


# ═══════════════════════════════════════════════ attributes / groups (pcg102)
def _bary(p, A, B, C):
    """Barycentric coordinates (n,3) of p in the plane of triangle ABC (not clamped to the triangle; linear extrapolation in the plane)."""
    v0, v1, v2 = B - A, C - A, p - A
    d00 = np.einsum("ij,ij->i", v0, v0)
    d01 = np.einsum("ij,ij->i", v0, v1)
    d11 = np.einsum("ij,ij->i", v1, v1)
    d20 = np.einsum("ij,ij->i", v2, v0)
    d21 = np.einsum("ij,ij->i", v2, v1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) > 1e-30, den, 1.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return np.stack([1.0 - v - w, v, w], 1)


def _side_src(side, g, rows_tri, rows_vtx):
    """
    The source on side of the triangles of g that belong to side (rows_tri) and of their corners (rows_vtx, (m,3)):
    each triangle finds the original triangle on side containing its centre (boolean output faces are all parts of input faces,
    so the centre always lies in the source face, distance ~ 0), and each corner takes barycentric coordinates on that original triangle.
    Returns (source prim (m,), points of the source triangle (m,3), corners (m,3), barycentrics of each output corner (m,3,3)).
    """
    from .spatial import closest_surface
    T, C = side.triangles(with_corners=True)
    Ps = np.asarray(side.get(POINT, "P"), np.float64)
    Pg = np.asarray(g.get(POINT, "P"), np.float64)
    vp = np.asarray(g.vertex_point, np.int64)
    cen = Pg[vp[rows_vtx]].mean(1)
    ti, _, _, _ = closest_surface(cen, Ps, T)
    ti = np.maximum(ti, 0)
    vpr = side.vertex_prim()
    src_prim = np.asarray(vpr, np.int64)[C[ti, 0]]
    A, B, Cc = (Ps[T[ti, k]] for k in range(3))
    W = np.stack([_bary(Pg[vp[rows_vtx[:, j]]], A, B, Cc) for j in range(3)], 1)
    return src_prim, T[ti].astype(np.int64), C[ti].astype(np.int64), W


def _carry(g, from_a, a, b):
    """
    Restores A's / B's attributes and groups onto the boolean result g (triangles). Previously only P and primitive groups.

    point / vertex float attributes are interpolated by barycentric coordinates on the source triangle; integers, strings and groups take the corner with the
    largest weight (interpolating 2.5 ids makes no sense). prim attributes and groups take the source face's.
    Attributes present on only one side get 0 / "" on the other side's elements. Same names on both sides with mismatched type / component count:
    A wins, B's side gets the default value. Detail attributes: A takes priority. Edge groups are not carried (the topology was cut).
    """
    from .core import VERTEX, DETAIL, is_string
    if g.nprims == 0:
        return g
    sizes = g.prim_sizes()
    if not (sizes == 3).all():
        return g
    nP, nV, nF = g.npoints, g.nvertices, g.nprims
    vtx = np.asarray(g.prim_offset[:-1], np.int64)[:, None] + np.arange(3)[None]   # (nF,3)
    vp = np.asarray(g.vertex_point, np.int64)
    sides = [(a, np.nonzero(from_a)[0]), (b, np.nonzero(~from_a)[0])]
    info = []
    for side, rows in sides:
        if len(rows) and side is not None and side.npoints and side.nprims:
            info.append((side, rows) + _side_src(side, g, rows, vtx[rows]))
        else:
            info.append(None)

    def kind(v):
        return "s" if is_string(v) else ("f" if np.asarray(v).dtype.kind == "f" else "i")

    def compatible(va, vb):
        return vb is not None and va.shape[1] == vb.shape[1] and kind(va) == kind(vb)

    for cls in (PRIM, VERTEX, POINT):
        names = []
        for side in (a, b):
            if side is None:
                continue
            for k in side.attribs[cls]:
                if k not in names and not (cls == POINT and k == "P"):
                    names.append(k)
        n_out = {PRIM: nF, VERTEX: nV, POINT: nP}[cls]
        for nm in names:
            if nm in g.attribs[cls]:
                continue
            va = a.attribs[cls].get(nm) if a is not None else None
            vb = b.attribs[cls].get(nm) if b is not None else None
            ref = va if va is not None else vb
            kd = kind(ref)
            ncol = ref.shape[1]
            if kd == "s":
                res = np.full((n_out, ncol), "", dtype=object)
            else:
                res = np.zeros((n_out, ncol), np.float64)
            for si, it in ((1, info[1]), (0, info[0])):     # A written last, so A wins on shared points
                if it is None:
                    continue
                v = va if si == 0 else vb
                if v is None or (si == 1 and va is not None and not compatible(va, vb)):
                    continue
                side, rows, sp, tp, tc, W = it
                v = np.asarray(v)
                if cls == PRIM:
                    res[rows] = v[sp]
                    continue
                src = tc if cls == VERTEX else tp                   # (m,3) source indices
                if kd == "f":
                    val = np.einsum("mjk,mkc->mjc", W, np.asarray(v, np.float64)[src])
                else:
                    pick = np.take_along_axis(src, np.argmax(W, 2), 1)  # (m,3)
                    val = v[pick]
                if cls == VERTEX:
                    res[vtx[rows].reshape(-1)] = val.reshape(-1, ncol)
                else:
                    res[vp[vtx[rows]].reshape(-1)] = val.reshape(-1, ncol)
            if kd == "s":
                g.set_string(cls, nm, np.array([str(x) for x in res.reshape(-1)], dtype=str)
                             .reshape(res.shape))
            else:
                g.set(cls, nm, res.astype(ref.dtype), owned=True)
        # groups
        gnames = []
        for side in (a, b):
            if side is None:
                continue
            for k in side.groups[cls]:
                if k not in gnames and k not in g.groups[cls]:
                    gnames.append(k)
        for nm in gnames:
            m = np.zeros(n_out, bool)
            for si, it in ((1, info[1]), (0, info[0])):
                if it is None:
                    continue
                side = a if si == 0 else b
                sg = side.groups[cls].get(nm)
                if sg is None:
                    continue
                sg = np.asarray(sg, bool)
                _, rows, sp, tp, tc, W = it
                if cls == PRIM:
                    m[rows] = sg[sp]
                    continue
                src = tc if cls == VERTEX else tp
                pick = np.take_along_axis(src, np.argmax(W, 2), 1)
                if cls == VERTEX:
                    m[vtx[rows].reshape(-1)] = sg[pick].reshape(-1)
                else:
                    m[vp[vtx[rows]].reshape(-1)] = sg[pick].reshape(-1)
            g.set_group(cls, nm, m)
    for side in (a, b):
        if side is None:
            continue
        for k, v in side.attribs[DETAIL].items():
            g.attribs[DETAIL].setdefault(k, v)
    return g
