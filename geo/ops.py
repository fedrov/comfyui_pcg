"""SOP-level operations. All are pure functions: take a Geometry, return a new Geometry, never modify in place."""
from __future__ import annotations

import math

import numpy as np

from .core import (Geometry, POINT, VERTEX, PRIM, DETAIL, EDGE, CLASSES,
                   PRIM_POLY, PRIM_PACKED, PRIM_NURBS_CURVE, PRIM_NURBS_SURF,
                   PRIM_BEZIER_CURVE, PRIM_BEZIER_SURF, SPLINE_TYPES,
                   is_string)
from . import groups as _grp


# ---------------------------------------------------------------- transform
ROTATE_ORDERS = ("xyz", "xzy", "yxz", "yzx", "zxy", "zyx")


def euler_matrix(rx, ry, rz, order="xyz"):
    """
    Degrees; returns (3,3) acting on column vectors (p' = M p; row-vector form p @ M.T).

    order is the **sequence**, same meaning as Houdini's Rotate Order: "xyz" = rotate about
    X first, then Y, then Z, M = Rz.Ry.Rx. Houdini's Transform / Copy and
    Transform / all primitives default to Rx Ry Rz.

    Before pcg85 the default was "zyx" with a comment claiming "matches Houdini", but it actually rotated Z first (M = Rx.Ry.Rz),
    which disagrees with Houdini whenever two or more axes are non-zero: (0,0,1) rotated by rx = ry = 90 deg
    gives (0,-1,0) in Houdini, previously (1,0,0). A test pins this down with that point.
    """
    if order not in ROTATE_ORDERS:
        raise ValueError(f"Rotate Order must be one of {ROTATE_ORDERS}, got {order!r}")
    cx, sx = np.cos(np.radians(rx)), np.sin(np.radians(rx))
    cy, sy = np.cos(np.radians(ry)), np.sin(np.radians(ry))
    cz, sz = np.cos(np.radians(rz)), np.sin(np.radians(rz))
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], np.float32)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], np.float32)
    M = np.eye(3, dtype=np.float32)
    for ax in order:
        M = {"x": Rx, "y": Ry, "z": Rz}[ax] @ M
    return M


XFORM_ORDERS = ("srt", "str", "rst", "rts", "tsr", "trs")


def xform_matrix(translate=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1), shear=(0, 0, 0),
                 uniform_scale=1.0, pivot=(0, 0, 0), pivot_rotate=(0, 0, 0),
                 xform_order="srt", rotate_order="xyz", invert=False):
    """
    The matrix of Houdini's Transform SOP, (4,4) float64, **row-vector** convention: p' = [p, 1] @ M.

        M = T(-pivot) . PR^-1 . [S.Sh, R, T multiplied in Transform Order sequence] . PR . T(pivot)

    Transform Order "srt" = scale first, then rotate, then translate. S is scale x uniform_scale; Sh is shear
    (xy, xz, yz): x += xy.y + xz.z, y += yz.z (computed in one step with scale, right after it). PR is Pivot Rotate:
    scale / rotate happen in the rotated pivot frame. Translation is also wrapped inside PR -- this follows Houdini's matrix construction
    (UT_Matrix4::xform sandwiches the whole SRT between the pivot transforms); it does not matter when Pivot Rotate is 0.
    """
    if xform_order not in XFORM_ORDERS:
        raise ValueError(f"Transform Order must be one of {XFORM_ORDERS}, got {xform_order!r}")

    def lin(L):
        M = np.eye(4)
        M[:3, :3] = L
        return M

    def tr(v):
        M = np.eye(4)
        M[3, :3] = np.asarray(v, np.float64)
        return M

    sh = np.eye(3)
    sh[1, 0], sh[2, 0], sh[2, 1] = [float(x) for x in shear]
    part = {
        "s": lin(np.diag(np.asarray(scale, np.float64) * float(uniform_scale)) @ sh),
        "r": lin(euler_matrix(*rotate, order=rotate_order).astype(np.float64).T),
        "t": tr(translate),
    }
    M = np.eye(4)
    for k in xform_order:
        M = M @ part[k]
    PR = lin(euler_matrix(*pivot_rotate, order=rotate_order).astype(np.float64).T)
    M = tr(-np.asarray(pivot, np.float64)) @ PR.T @ M @ PR @ tr(pivot)
    return np.linalg.inv(M) if invert else M


def transform(geo, translate=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1),
              pivot=(0, 0, 0), group=None, rotate_order="xyz", xform_order="srt",
              shear=(0, 0, 0), uniform_scale=1.0, pivot_rotate=(0, 0, 0), invert=False):
    g = geo.copy()
    P = g.get_w(POINT, "P")
    extra = (xform_order != "srt" or any(float(x) for x in shear) or float(uniform_scale) != 1.0
             or any(float(x) for x in pivot_rotate) or invert)
    if extra:
        M4 = xform_matrix(translate, rotate, scale, shear, uniform_scale, pivot, pivot_rotate,
                          xform_order, rotate_order, invert)
        M = M4[:3, :3].T.astype(np.float32)          # normals / vectors below use M in the column-vector convention
        new = (np.asarray(P, np.float64) @ M4[:3, :3] + M4[3, :3]).astype(np.float32)
    else:
        # The only path before pcg98 (SRT, pivot translate only): kept as is, results of old workflows do not change by a single bit
        piv = np.asarray(pivot, np.float32)
        M = euler_matrix(*rotate, order=rotate_order) \
            @ np.diag(np.asarray(scale, np.float32))
        new = (P - piv) @ M.T + piv + np.asarray(translate, np.float32)
    # guess: point group / point attribute first, otherwise treat as a primitive group (Houdini's Group Type default)
    mask = _grp.resolve_points_guess(geo, group)
    if not mask.all():
        P[mask] = new[mask]
        new = P
    g.set(POINT, "P", new, owned=True)

    # Direction attributes. In the row-vector convention points are p @ M.T, so:
    #   normals N use the inverse transpose: n' = n @ M^{-1} (column-vector form M^{-T} n)
    #   tangent vectors up / v behave like points: d' = d @ M.T
    # Before pcg67 normals were multiplied by the **transpose** of M^{-T}, i.e. the transpose of M^{-1} transposed again --
    # for a pure rotation this rotates normals in exactly the **opposite direction** (rotate 90 deg about z: points go to +y, normals to -y),
    # and regardless of group, normals outside the selected points rotated too. Found when checking directions
    # against it while writing Copy and Transform
    for name, kind in (("N", "normal"), ("up", "dir"), ("v", "vec")):
        a = g.get(POINT, name)
        if a is None or a.shape[1] != 3:
            continue
        a64 = np.asarray(a, np.float64)
        M64 = M.astype(np.float64)
        w = a64 @ np.linalg.inv(M64) if kind == "normal" else a64 @ M64.T
        if kind != "vec":
            ln = np.linalg.norm(w, axis=1, keepdims=True)
            w = w / np.where(ln == 0, 1, ln)
        if not mask.all():
            w = np.where(mask[:, None], w, a64)
        g.set(POINT, name, w.astype(a.dtype), owned=True)
    # Packed primitives (pcg121): the piece turns with its point -- M_new = A @ M (column-vector convention; A is the
    # linear part used for the points above). Only the pieces whose point is in the group.
    if g.nprims and (g.prim_type == PRIM_PACKED).any() and g.has(PRIM, "packedxform"):
        pk = np.nonzero(g.prim_type == PRIM_PACKED)[0]
        vpt = g.vertex_point[g.prim_offset[pk].astype(np.int64)]
        pk = pk[mask[vpt]]
        if len(pk):
            X = np.asarray(g.get(PRIM, "packedxform"), np.float64).reshape(-1, 3, 3).copy()
            X[pk] = np.einsum("ij,njk->nik", M.astype(np.float64), X[pk])
            g.set(PRIM, "packedxform", X.reshape(-1, 9), owned=True)
    return g


# ---------------------------------------------------------------- merge
def merge(*geos):
    geos = [g for g in geos if g is not None and (g.npoints or g.nprims)]
    if not geos:
        return Geometry()
    if len(geos) == 1:
        return geos[0].copy()

    out = Geometry()
    ptoff, vtoff = 0, 0
    vps, offs, closeds, types = [], [], [], []
    for g in geos:
        vps.append(g.vertex_point + ptoff)
        offs.append(g.prim_offset[1:] + vtoff)
        closeds.append(g.prim_closed)
        types.append(g.prim_type)
        ptoff += g.npoints
        vtoff += g.nvertices
    out._resize_points(ptoff)
    out.set_topology(np.concatenate(vps) if vps else np.zeros(0, np.int32),
                     np.concatenate([[0]] + offs).astype(np.int32),
                     np.concatenate(closeds), np.concatenate(types))

    # Union of attributes; attributes missing on some input are filled with 0 (Houdini does the same)
    for cls in (POINT, VERTEX, PRIM):
        names = {}
        for g in geos:
            for k, v in g.attribs[cls].items():
                names.setdefault(k, (v.shape[1], v.dtype))
        for k, (c, dt) in names.items():
            parts = []
            for g in geos:
                a = g.get(cls, k)
                n = g.count(cls)
                parts.append(a if a is not None else np.zeros((n, c), dt))
            out.set(cls, k, np.concatenate(parts), owned=True)
    # Groups are unioned too. merge is called repeatedly inside carve / spline_to_polygons / polyextrude;
    # if it drops groups, a whole swath downstream loses them -- this is the place that most needs guarding.
    # If an input does not have a group, all its elements are treated as not in the group.
    for cls in (POINT, VERTEX, PRIM):
        names = []
        for g in geos:
            for k in g.groups[cls]:
                if k not in names:
                    names.append(k)
        for k in names:
            out.set_group(cls, k, np.concatenate([
                g.groups[cls][k] if k in g.groups[cls]
                else np.zeros(g.count(cls), bool) for g in geos]))

    for g in geos:                                  # detail attributes: later overrides earlier
        for k, v in g.attribs[DETAIL].items():
            out.attribs[DETAIL][k] = v
    # Edge groups: merge after offsetting each input's point numbers
    ptoff2 = 0
    for g in geos:
        for k, v in g.edge_groups.items():
            cur = out.edge_groups.get(k)
            add = (np.asarray(v, np.int32) + ptoff2) if len(v) \
                else np.zeros((0, 2), np.int32)
            out.edge_groups[k] = np.concatenate(
                [cur, add]) if cur is not None and len(cur) else add
        ptoff2 += g.npoints
    for k in list(out.edge_groups):
        out.set_edge_group(k, out.edge_groups[k])

    poff = 0                                        # side channels follow the prim offset
    for g in geos:
        for i, d in g.prim_data.items():
            out.prim_data[poff + int(i)] = dict(d)
        poff += g.nprims
    return out


# ---------------------------------------------------- delete / extract (Blast)
def delete_prims(geo, keep_mask, keep_points=False):
    """
    keep_mask: (nprims,) bool. By default also deletes points that become orphaned.

    With keep_points=True no points are deleted (corresponds to Keep Points on Houdini's Delete SOP):
    "delete all faces and keep only the point cloud to scatter trees on" is a legitimate use.
    """
    keep = np.asarray(keep_mask, bool)
    sizes = geo.prim_sizes()
    vsel = np.repeat(keep, sizes)                   # (NV,) which vertices to keep

    old_vp = geo.vertex_point[vsel]
    used = (np.arange(geo.npoints, dtype=np.int64) if keep_points
            else np.unique(old_vp))
    remap = np.full(geo.npoints, -1, np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)

    out = Geometry()
    out._resize_points(len(used))
    new_sizes = sizes[keep]
    out.set_topology(remap[old_vp],
                     np.concatenate([[0], np.cumsum(new_sizes)]).astype(np.int32),
                     geo.prim_closed[keep], geo.prim_type[keep])

    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[used], owned=True)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[vsel], owned=True)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[keep], owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v[used])
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[vsel])
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[keep])
    out.prim_data = geo.remap_prim_data(np.nonzero(keep)[0])
    out.edge_groups = geo.remap_edge_groups(remap, out.npoints)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


def delete_points(geo, keep_mask):
    """
    Delete points. Semantics match Houdini: deleted points also delete the prims that reference them, but **points that are kept
    always stay**, even if no prim references them anymore -- orphan points are valid geometry.

    Previously this took a shortcut through delete_prims, which cleans up orphan points, so "keep only 1 point"
    would first delete every face, then delete that point too as an orphan, outputting 0 points.
    """
    keep = np.asarray(keep_mask, bool)
    idx = np.nonzero(keep)[0]
    remap = np.full(geo.npoints, -1, np.int32)
    remap[idx] = np.arange(len(idx), dtype=np.int32)

    out = Geometry()
    out._resize_points(len(idx))
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[idx], owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v[idx])

    if geo.nprims and geo.nvertices:
        sizes = geo.prim_sizes()
        vok = keep[geo.vertex_point].astype(np.int8)
        # A prim survives only if all its points are kept
        pk = np.minimum.reduceat(vok, geo.prim_offset[:-1]).astype(bool)
        vsel = np.repeat(pk, sizes)
        new_sizes = sizes[pk]
        out.set_topology(
            remap[geo.vertex_point[vsel]],
            np.concatenate([[0], np.cumsum(new_sizes)]).astype(np.int32),
            geo.prim_closed[pk], geo.prim_type[pk])
        for k, v in geo.attribs[VERTEX].items():
            out.set(VERTEX, k, v[vsel], owned=True)
        for k, v in geo.attribs[PRIM].items():
            out.set(PRIM, k, v[pk], owned=True)
        for k, v in geo.groups[VERTEX].items():
            out.set_group(VERTEX, k, v[vsel])
        for k, v in geo.groups[PRIM].items():
            out.set_group(PRIM, k, v[pk])
        out.prim_data = geo.remap_prim_data(np.nonzero(pk)[0])

    out.edge_groups = geo.remap_edge_groups(remap, out.npoints)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


def carry_attribs(src, out, pt_src=None, prim_src=None, vtx_src=None,
                  skip_point=("P",), edges=True):
    """
    Carry src's attributes and groups onto out by "source index" (out's topology is already built).

    pt_src / prim_src / vtx_src: which element of src each point / prim / vertex of out comes from,
    -1 = no source (numbers filled with 0, strings with "", not selected in groups). None = do not carry this class.
    detail attributes are carried as-is. With edges=True, src's edge groups are mapped through pt_src, keeping only
    edges that actually exist in out. Used by operators that rebuild topology, like PolyBevel / Boolean --
    they used to output only P and lose all other attributes and groups.
    """
    from .core import is_string as _iss

    def take(v, idx):
        v = np.asarray(v)
        ok = idx >= 0
        r = v[np.where(ok, idx, 0)]
        if not ok.all():
            r = r.copy()
            r[~ok] = "" if v.dtype.kind in "UO" else (False if v.dtype == bool else 0)
        return r

    for cls, idx in ((POINT, pt_src), (PRIM, prim_src), (VERTEX, vtx_src)):
        if idx is None or src.count(cls) == 0:
            continue
        idx = np.asarray(idx, np.int64)
        if len(idx) != out.count(cls):
            raise ValueError(f"carry_attribs: {cls} source count {len(idx)} != {out.count(cls)}")
        for k, v in src.attribs[cls].items():
            if cls == POINT and k in skip_point:
                continue
            if k in out.attribs[cls]:
                continue
            if _iss(v):
                out.set_string(cls, k, take(v, idx))
            else:
                out.set(cls, k, take(v, idx), owned=True)
        for k, m in src.groups[cls].items():
            if k in out.groups[cls]:
                continue
            out.set_group(cls, k, take(np.asarray(m, bool), idx))
    for k, v in src.attribs[DETAIL].items():
        out.attribs[DETAIL].setdefault(k, v)
    if edges and pt_src is not None and src.edge_groups and out.nvertices:
        from . import topology as _tp
        ps = np.asarray(pt_src, np.int64)
        t = _tp.topology(out)
        E = np.asarray(t.edge_points, np.int64)
        if len(E):
            sa, sb = ps[E[:, 0]], ps[E[:, 1]]
            ok = (sa >= 0) & (sb >= 0) & (sa != sb)
            n1 = src.npoints + 1
            key = np.minimum(sa, sb) * n1 + np.maximum(sa, sb)
            for k, pairs in src.edge_groups.items():
                if k in out.edge_groups:
                    continue
                pr = np.sort(np.asarray(pairs, np.int64).reshape(-1, 2), axis=1)
                hit = ok & np.isin(key, pr[:, 0] * n1 + pr[:, 1])
                out.set_edge_group(k, E[hit].astype(np.int32))


def vertex_sources(src, out, prim_src, pt_src):
    """
    Source vertex of each out vertex: the corner of the source prim whose point = the source point;
    if not found (a newly created point not on the source face), take the source prim's first corner. -1 when there is no source prim.
    """
    vp = np.asarray(out.vertex_point, np.int64)
    vpr = np.asarray(out.vertex_prim(), np.int64)
    sp = np.asarray(prim_src, np.int64)[vpr]
    spt = np.asarray(pt_src, np.int64)[vp]
    look = {}
    svp = np.asarray(src.vertex_point, np.int64)
    svr = np.asarray(src.vertex_prim(), np.int64)
    for h in range(len(svp) - 1, -1, -1):
        look[(int(svr[h]), int(svp[h]))] = h
    off = np.asarray(src.prim_offset, np.int64)
    res = np.full(len(vp), -1, np.int64)
    for i in range(len(vp)):
        p = int(sp[i])
        if p < 0:
            continue
        res[i] = look.get((p, int(spt[i])), int(off[p]))
    return res


def _blend(geo, cls, name, new, mask):
    """Elements outside group keep their original value. If there is no original value, keep the computed result."""
    if mask.all():
        return new
    old = geo.get(cls, name)
    if old is None or old.shape != new.shape:
        return new
    out = np.array(new, copy=True)
    out[~mask] = old[~mask]
    return out


# ---------------------------------------------------------------- normals
def prim_normals(geo, normalize=True):
    """
    (nprims,3) primitive normals, Newell's method.

    Why not a cross product: the cross product is only correct for planar triangles; once an ngon is non-planar (very common in PCG)
    the result depends on which three points you pick. Newell's method sums over the whole edge loop and gives the best normal in the
    least-squares sense even for non-planar polygons, and unnormalized its length is exactly 2x area -- so area weighting
    comes for free.
    """
    P = geo.get(POINT, "P")
    if geo.nprims == 0:
        return np.zeros((0, 3), np.float32)
    vp = geo.vertex_point
    nxt = geo.next_corner()
    a, b = P[vp], P[vp[nxt]]
    cr = np.empty_like(a)
    cr[:, 0] = (a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2])
    cr[:, 1] = (a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0])
    cr[:, 2] = (a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1])
    pn = np.zeros((geo.nprims, 3), np.float32)
    np.add.at(pn, geo.vertex_prim(), cr)
    pn *= 0.5                                   # -> length = area
    pn[~geo.prim_closed] = 0.0                  # polylines have no face normal
    if normalize:
        l = np.linalg.norm(pn, axis=1, keepdims=True)
        pn = pn / np.where(l == 0, 1, l)
    return pn.astype(np.float32)


def prim_centers(geo):
    """(nprims,3) average vertex position of each prim. Used for drawing prim normals and labeling prim numbers."""
    if geo.nprims == 0:
        return np.zeros((0, 3), np.float32)
    P = geo.get(POINT, "P")
    c = np.zeros((geo.nprims, 3), np.float32)
    np.add.at(c, geo.vertex_prim(), P[geo.vertex_point])
    return c / np.maximum(geo.prim_sizes(), 1)[:, None]


NORMAL_WEIGHTS = ("by_face_area", "each_vertex_equally", "by_vertex_angle")


NORMAL_GROUP_TYPES = ("guess", "point", "vertex", "prim", "edge")


def normal_sop(geo, add_to="point", cusp_angle=60.0, group="",
               weighting="by_face_area", group_type="guess", name="N",
               compute=True, keep_zero=False, make_unit=False, reverse=False):
    """
    The full set of Normal SOP toggles (pcg100), a wrapper around compute_normals:

      group_type   guess = what it always did: Group is parsed directly as the Add Normals to class
                   (Houdini's Guess is "treat as a primitive group when unsure"; not copied here so that old graphs stay unchanged).
                   When a type is given explicitly, parse as that class, then expand to the Add Normals to class --
                   "touching counts": primitive group -> its points / vertices, point group -> vertices / primitives using those points, edge group -> endpoints ...
      name         which attribute to write to (Override Normal)
      compute      off = do not compute, only apply the next two steps to the existing attribute
      keep_zero    where the computed result is a zero vector (orphan points, degenerate faces), keep the input's value
      make_unit    normalize existing normals in the group; docs: this item is greyed out when Compute Normals is on
                   (computed normals are already unit length), so it only takes effect when compute is off
      reverse      multiply normals in the group by -1 (done last)

    With Add Normals to = Detail there are no "elements in the group", so Group has no effect.
    """
    if group_type not in NORMAL_GROUP_TYPES:
        raise ValueError(f"Group Type must be one of {NORMAL_GROUP_TYPES}")
    name = str(name).strip() or "N"
    if add_to == "detail":
        mask = np.ones(1, bool)
        gsel = None
    elif group_type == "guess" or not str(group).strip():
        mask = _grp.resolve(geo, add_to, group)
        gsel = group
    else:
        from . import grouppromote as _gp
        sel = (_grp.resolve_edges(geo, group) if group_type == "edge"
               else _grp.resolve(geo, group_type, group))
        mask = gsel = np.asarray(_gp.convert(geo, group_type, add_to, sel), bool)
    old = geo.get(add_to, name)
    if compute:
        g = compute_normals(geo, add_to, cusp_angle, group=gsel,
                            weighting=weighting, name=name)
        if keep_zero and old is not None:
            new = g.get(add_to, name)
            if new is not None and new.shape == old.shape:
                zero = mask & ~np.any(np.asarray(new) != 0, axis=1)
                if zero.any():
                    w = np.array(new, copy=True)
                    w[zero] = old[zero]
                    g.set(add_to, name, w, owned=True)
    else:
        g = geo.copy()
    cur = g.get(add_to, name)
    unit = make_unit and not compute
    if cur is None or is_string(cur) or cur.shape[1] < 3 or not (unit or reverse):
        return g
    w = np.array(cur, np.float64)
    if unit:
        ln = np.linalg.norm(w[:, :3], axis=1)
        ok = mask & (ln > 0)
        w[ok, :3] /= ln[ok, None]
    if reverse:
        w[mask, :3] *= -1.0
    g.set(add_to, name, w.astype(cur.dtype), owned=True)
    return g


def _corner_weights(geo, area, weighting):
    """How much weight each corner gives to the normal of its face (Weighting Method of Houdini's Normal SOP)."""
    if weighting not in NORMAL_WEIGHTS:
        raise ValueError(f"Weighting Method must be one of {NORMAL_WEIGHTS}, got {weighting!r}")
    vprim = geo.vertex_prim()
    if weighting == "by_face_area":
        return area[vprim]
    if weighting == "each_vertex_equally":
        return np.ones(len(vprim))        # a degenerate face (area 0) has a unit normal of 0, so no weight makes any difference
    # by_vertex_angle: the angle between the two edges at this corner. When a big triangle and a thin sliver share a point,
    # area weighting is biased by the big one; angle weighting only looks at the "opening angle" each takes up at this point
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    nxt = geo.next_corner()
    prv = np.empty_like(nxt)
    prv[nxt] = np.arange(len(nxt))
    here = P[geo.vertex_point]
    a = P[geo.vertex_point[nxt]] - here
    b = P[geo.vertex_point[prv]] - here
    la = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    ang = np.arccos(np.clip((a * b).sum(1) / np.where(la == 0, 1, la), -1.0, 1.0))
    return ang


def compute_normals(geo, add_to="point", cusp_angle=60.0, group=None,
                    weighting="by_face_area", name="N"):
    """
    Matches Houdini's Normal SOP.

    add_to:
      point  -- area-weighted smooth point normals. One normal per point, **hard edges are impossible**.
      vertex -- one normal per corner, grouped by cusp_angle. This is the only way to
                get hard edges, and also what Houdini's viewport actually uses to display hard edges.
      prim   -- one normal per face. Used for computations like copy/align, not for shading.
      detail -- one normal for the whole geometry: the sum of all face area normals, normalized (the "facing" of a patch of ground).

    weighting (point / vertex modes): by_face_area (what it always did) / each_vertex_equally /
    by_vertex_angle, see _corner_weights.

    group may be a group specifier (parsed as the add_to class) or a boolean mask directly;
    name is which attribute to write to (Houdini's Override Normal), default N.

    cusp_angle only applies in vertex mode: a corner only accumulates neighbouring faces whose angle to
    its own face is below this value. A 90-degree cube at a 60-degree threshold merges nothing -> all hard edges;
    neighbouring faces on a sphere have small angles -> all merged -> smooth. This is Houdini's behaviour.
    """
    g = geo.copy()
    if add_to == "detail":
        tot = prim_normals(geo, normalize=False).astype(np.float64).sum(0) if geo.nprims else np.zeros(3)
        ln = float(np.linalg.norm(tot))
        g.set(DETAIL, name, (tot / ln if ln > 0 else np.array([0.0, 1.0, 0.0]))[None, :].astype(np.float32),
              owned=True)
        return g
    gmask = (np.asarray(group, bool) if isinstance(group, np.ndarray)
             else _grp.resolve(geo, add_to, group))
    if geo.nprims == 0 or geo.npoints == 0:
        if add_to == "point":
            g.set(POINT, name, np.tile([0, 1, 0], (geo.npoints, 1)).astype(np.float32))
        return g

    area_n = prim_normals(geo, normalize=False)      # length = area
    vprim = geo.vertex_prim()
    vp = geo.vertex_point

    if add_to == "prim":
        l = np.linalg.norm(area_n, axis=1, keepdims=True)
        g.set(PRIM, name, _blend(geo, PRIM, name, area_n / np.where(l == 0, 1, l),
                                gmask), owned=True)
        return g

    if add_to == "point":
        N = np.zeros((geo.npoints, 3), np.float32)
        if weighting == "by_face_area":
            np.add.at(N, vp, area_n[vprim])          # area weighting comes directly from the length
        else:
            ar = np.linalg.norm(area_n, axis=1)
            un = area_n / np.where(ar[:, None] == 0, 1, ar[:, None])
            np.add.at(N, vp, (un[vprim] * _corner_weights(geo, ar, weighting)[:, None]).astype(np.float32))
        l = np.linalg.norm(N, axis=1, keepdims=True)
        g.set(POINT, name, _blend(geo, POINT, name, N / np.where(l == 0, 1, l),
                                 gmask), owned=True)
        return g

    # ---- vertex: group by cusp angle ----
    cos_cusp = float(np.cos(np.radians(np.clip(cusp_angle, 0.0, 180.0))))
    area = np.linalg.norm(area_n, axis=1)
    unit = area_n / np.where(area[:, None] == 0, 1, area[:, None])

    cw = _corner_weights(geo, area, weighting)
    vn = np.zeros((geo.nvertices, 3), np.float32)
    counts = np.bincount(vp, minlength=geo.npoints)
    order = np.argsort(vp, kind="stable")            # gather corners by their point
    off = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)

    for k in np.unique(counts[counts > 0]):
        pts = np.nonzero(counts == k)[0]
        # (m,k) all corners of this point
        cor = order[off[pts][:, None] + np.arange(k)[None, :]]
        fn = unit[vprim[cor]]                        # (m,k,3) normal of each one's face
        w = cw[cor]                                  # (m,k)   weights (area by default)
        # (m,k,k) pairwise angle cosines: corner i only accepts faces at a small enough angle to it
        dot = np.einsum("mki,mji->mkj", fn, fn)
        acc = (dot >= cos_cusp) * w[:, None, :]
        vn[cor] = np.einsum("mkj,mji->mki", acc.astype(np.float32), fn)

    l = np.linalg.norm(vn, axis=1, keepdims=True)
    g.set(VERTEX, name, _blend(geo, VERTEX, name, vn / np.where(l == 0, 1, l),
                              gmask), owned=True)
    return g


def measure_area(geo):
    """Add a float area attribute to each prim."""
    g = geo.copy()
    P = g.get(POINT, "P")
    sizes = g.prim_sizes()
    area = np.zeros(g.nprims, np.float32)
    for i in range(g.nprims):                       # with many faces, switch to vectorizing by size buckets
        if not g.prim_closed[i] or sizes[i] < 3:
            continue
        idx = g.prim_points(i)
        v = P[idx]
        area[i] = 0.5 * np.linalg.norm(
            np.cross(v[1:-1] - v[0], v[2:] - v[0]), axis=1).sum()
    g.set(PRIM, "area", area, owned=True)
    return g


# ---------------------------------------------------------------- scatter
def scatter(geo, count=100, seed=0, density_attrib=""):
    """
    Scatter points on the surface weighted by area, output a point cloud carrying N / sourceprim / uv (barycentric coordinates).
    density_attrib: name of a float point attribute used to weight by a density map.
    """
    tri = geo.triangles()
    P = geo.get(POINT, "P")
    if len(tri) == 0:
        return Geometry()

    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)

    if density_attrib and geo.has(POINT, density_attrib):
        d = geo.get(POINT, density_attrib)[:, 0]
        area = area * np.clip(d[tri].mean(1), 0, None)

    total = area.sum()
    if total <= 0:
        return Geometry()

    rng = np.random.default_rng(int(seed))
    cdf = np.cumsum(area)
    idx = np.searchsorted(cdf, rng.random(int(count)) * total)
    idx = np.clip(idx, 0, len(tri) - 1)

    u = rng.random(int(count)).astype(np.float32)
    v = rng.random(int(count)).astype(np.float32)
    flip = u + v > 1.0
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]

    pos = a[idx] + u[:, None] * (b[idx] - a[idx]) + v[:, None] * (c[idx] - a[idx])

    out = Geometry.from_points(pos)
    n = cr[idx]
    l = np.linalg.norm(n, axis=1, keepdims=True)
    out.set(POINT, "N", n / np.where(l == 0, 1, l), owned=True)
    out.set(POINT, "sourceprim", idx.astype(np.int32), owned=True)
    out.set(POINT, "uv", np.stack([u, v], 1), owned=True)

    # Interpolate the source geometry's point attributes with barycentric coordinates (consistent with Houdini's scatter)
    w = np.stack([1 - u - v, u, v], 1)[:, :, None]
    for k, arr in geo.attribs[POINT].items():
        if k in ("P", "N"):
            continue
        if arr.dtype.kind in "fi":
            out.set(POINT, k, (arr[tri[idx]] * w).sum(1), owned=True)
    return out


# ------------------------------------------------------- Copy to Points
def frames_from_points(pts, up=(0, 1, 0)):
    """
    Build a 3x3 matrix per point from N / up / scale / pscale.
    Convention matches Houdini: the copy's +Z axis aligns with N.
    """
    n = pts.npoints
    N = pts.get(POINT, "N")
    if N is None:
        M = np.tile(np.eye(3, dtype=np.float32), (n, 1, 1))
    else:
        z = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-8)
        u = np.tile(np.asarray(up, np.float32), (n, 1))
        # When up and N are collinear, switch to another up to avoid degeneracy
        bad = np.abs((z * u).sum(1)) > 0.999
        u[bad] = np.array([1, 0, 0], np.float32)
        x = np.cross(u, z)
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-8)
        y = np.cross(z, x)
        M = np.stack([x, y, z], axis=2).astype(np.float32)   # column vectors are the basis

    s = np.ones((n, 3), np.float32)
    if pts.has(POINT, "scale"):
        sc = pts.get(POINT, "scale")
        s = s * (sc if sc.shape[1] == 3 else sc)
    if pts.has(POINT, "pscale"):
        s = s * pts.get(POINT, "pscale")
    return M * s[:, None, :]


def copy_to_points(src, pts, up=(0, 1, 0)):
    """Copy src onto each point of pts. The transform comes from N / up / pscale / scale."""
    n = pts.npoints
    if n == 0 or src.npoints == 0:
        return Geometry()
    m = src.npoints
    M = frames_from_points(pts, up)                          # (n,3,3)
    sp = src.get(POINT, "P")                                 # (m,3)
    Pt = pts.get(POINT, "P")                                 # (n,3)

    newP = np.einsum("nij,mj->nmi", M, sp) + Pt[:, None, :]  # (n,m,3)

    out = Geometry()
    out._resize_points(n * m)
    out.set(POINT, "P", newP.reshape(-1, 3).astype(np.float32), owned=True)

    if src.nprims:
        vp = (src.vertex_point[None, :] +
              (np.arange(n, dtype=np.int32) * m)[:, None]).reshape(-1)
        step = src.prim_offset[-1]
        off = (src.prim_offset[1:][None, :] +
               (np.arange(n, dtype=np.int32) * step)[:, None]).reshape(-1)
        out.set_topology(vp, np.concatenate([[0], off]).astype(np.int32),
                         np.tile(src.prim_closed, n), np.tile(src.prim_type, n))

    # src's point attributes are tiled, pts' point attributes are repeated (copied points inherit the template point)
    for k, v in src.attribs[POINT].items():
        if k == "P":
            continue
        arr = np.tile(v, (n, 1))
        if k == "N":
            arr = np.einsum("nij,mj->nmi", M, v).reshape(-1, 3)
        out.set(POINT, k, arr, owned=True)
    for k, v in pts.attribs[POINT].items():
        if k in ("P",) or out.has(POINT, k):
            continue
        out.set(POINT, k, np.repeat(v, m, axis=0), owned=True)
    for k, v in src.attribs[PRIM].items():
        out.set(PRIM, k, np.tile(v, (n, 1)), owned=True)
    out.set(PRIM, "copynum",
            np.repeat(np.arange(n, dtype=np.int32), src.nprims), owned=True)
    return out


def _gather_blocks(starts, sizes):
    """
    Gather index for variable-length blocks: given each block's start and length, expand into one contiguous index array.
    prims are variable-length; every "reorder / extract by prim" operation ultimately comes down to this formula.
    """
    sizes = np.asarray(sizes, np.int64)
    if not len(sizes):
        return np.zeros(0, np.int64)
    off = np.concatenate([[0], np.cumsum(sizes)])
    return np.repeat(np.asarray(starts, np.int64) - off[:-1], sizes) + \
        np.arange(int(off[-1]), dtype=np.int64)


# ------------------------------------------------------------------ Sweep
def _section_local(geo: Geometry, prim_i: int):
    """
    Convert a cross-section curve to **2D coordinates in its plane**, and also report whether it is closed.

    Does not assume which plane the cross-section is drawn in -- builds a local frame from the two principal axes of the best-fit plane.
    Hard-coding "the cross-section is in the XY plane" would flatten any cross-section from circle / carve / other nodes
    whose orientation differs, and that is far too common in real wiring.
    """
    idx = geo.prim_points(prim_i)
    P = geo.get(POINT, "P")[idx].astype(np.float64)
    c = P.mean(0)
    Q = P - c
    # The smallest singular value direction is the plane normal; the other two principal axes are local x/y
    try:
        _, _, vt = np.linalg.svd(Q, full_matrices=False)
        ax1, ax2 = vt[0], vt[1]
    except np.linalg.LinAlgError:
        ax1, ax2 = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    return np.stack([Q @ ax1, Q @ ax2], 1), bool(geo.prim_closed[prim_i])


def _builtin_section(shape, cols, radius):
    """Built-in cross-sections, returns (2D points, closed)."""
    if shape == "square_tube":
        r = radius
        return np.array([[-r, -r], [r, -r], [r, r], [-r, r]]), True
    if shape == "ribbon":
        return np.array([[-radius, 0.0], [radius, 0.0]]), False
    n = max(3, int(cols))
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([np.cos(a), np.sin(a)], 1) * radius, True


SWEEP_SURFACES = ("quads", "triangles", "alternating_triangles", "rows", "columns",
                  "rows_and_columns", "points")
SWEEP_CAPS = ("single_polygon", "grid")


def sweep(backbone: Geometry, cross: Geometry | None = None,
          shape="round_tube", cols=8, radius=0.1, surface_type="quads",
          group=None, cross_group=None, reverse_cross=False,
          up=(0, 1, 0), roll=0.0, full_twists=0.0, partial_twist=0.0,
          scale_start=1.0, scale_end=1.0, use_pscale=True,
          stretch_around_turns=True, max_stretch=10.0,
          end_caps=False, cap_group="endcaps",
          uv_attrib="", end_cap_type="single_polygon") -> Geometry:
    """
    Matches Houdini's Sweep: sweep a cross-section along a backbone curve.

    Frames use rotation-minimizing frames, so there is no twisting at turns. The cross-section plane is determined by its own principal axes,
    not assumed to be drawn in any particular plane.

    stretch_around_turns: at turns, stretch the cross-section along the turn plane by 1/cos(half turn angle),
    so the tube's **apparent thickness** stays constant. Without stretching the inside gets pinched -- the most
    common sweep artifact; Houdini has it on by default too. max_stretch prevents stretching to infinity at sharp turns.

    surface_type (Houdini's Surface Primitive Type): quads / triangles / alternating_triangles
    are faces; rows = one polyline loop per cross-section, columns = polylines along the backbone, rows_and_columns outputs both;
    points is points only. The line / point modes have no end caps.

    end_cap_type: single_polygon (one n-gon) / grid (the cross-section loop is the boundary of a quad patch filled with a quad grid,
    see polyfill._quad_grid; when the cross-section point count is odd or below 4 no grid can be laid, falls back to an n-gon).
    """
    if surface_type not in SWEEP_SURFACES:
        raise ValueError(f"Surface Type must be one of {SWEEP_SURFACES}, got {surface_type!r}")
    if end_cap_type not in SWEEP_CAPS:
        raise ValueError(f"End Cap Type must be one of {SWEEP_CAPS}, got {end_cap_type!r}")
    sel = _grp.resolve(backbone, PRIM, group)
    if backbone.nprims == 0 or not sel.any():
        return backbone.copy()

    # Cross-section: from the second input or a built-in shape
    if shape == "second_input" and cross is not None and cross.nprims:
        csel = _grp.resolve(cross, PRIM, cross_group)
        ci = int(np.nonzero(csel)[0][0]) if csel.any() else 0
        sec2d, sec_closed = _section_local(cross, ci)
    else:
        sec2d, sec_closed = _builtin_section(shape, cols, radius)
    if reverse_cross:
        sec2d = sec2d[::-1]
    nu = len(sec2d)
    if nu < 2:
        return backbone.copy()

    P = backbone.get(POINT, "P").astype(np.float64)
    pscale = backbone.get(POINT, "pscale")
    parts = []

    for pi in np.nonzero(sel)[0]:
        idx = backbone.prim_points(pi)
        pts = P[idx]
        closed = bool(backbone.prim_closed[pi]) and len(pts) >= 3
        if closed:
            pts = np.concatenate([pts, pts[:1]])
        if len(pts) < 2:
            continue

        tan, E1, E2 = rmf_frames(pts, up)
        nv = len(pts)

        # Arc-length parameter, used to interpolate scale/twist along the curve
        d = np.concatenate([[0.0],
                            np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        tpar = d / d[-1] if d[-1] > 0 else np.zeros(nv)

        sc = scale_start + (scale_end - scale_start) * tpar
        if use_pscale and pscale is not None:
            ps = pscale[idx, 0].astype(np.float64)
            if closed:
                ps = np.concatenate([ps, ps[:1]])
            sc = sc * ps

        # Stretch factor at turns: determined by half the angle between the tangents of adjacent segments
        stretch = np.ones(nv)
        if stretch_around_turns and nv > 2:
            seg = np.diff(pts, axis=0)
            seg /= np.maximum(np.linalg.norm(seg, axis=1, keepdims=True), 1e-12)
            cosang = np.clip((seg[:-1] * seg[1:]).sum(1), -1, 1)
            half = np.arccos(cosang) * 0.5
            inner = np.clip(1.0 / np.maximum(np.cos(half), 1e-6), 1, max_stretch)
            stretch[1:-1] = inner
            if closed:
                stretch[0] = stretch[-1] = 1.0

        ang = np.radians(roll) + tpar * (
            full_twists * 2 * np.pi + np.radians(partial_twist))

        rings = np.empty((nv, nu, 3))
        for k in range(nv):
            ca, sa = np.cos(ang[k]), np.sin(ang[k])
            loc = sec2d @ np.array([[ca, sa], [-sa, ca]])
            loc = loc * sc[k]
            loc = loc * np.array([stretch[k], 1.0])   # stretch along the turn plane
            rings[k] = pts[k] + loc[:, 0:1] * E1[k] + loc[:, 1:2] * E2[k]

        if closed:
            rings = rings[:-1]
            nv -= 1

        allp = rings.reshape(-1, 3)
        faces, kinds, fclosed = [], [], []
        rows = list(range(nv)) + ([0] if closed else [])
        ucount = nu if sec_closed else nu - 1
        lines = surface_type in ("rows", "columns", "rows_and_columns")
        if lines:
            if surface_type != "columns":             # one loop per cross-section
                for r in range(nv):
                    faces.append([r * nu + c for c in range(nu)])
                    kinds.append(0); fclosed.append(sec_closed)
            if surface_type != "rows":                # lines along the backbone
                for c in range(nu):
                    faces.append([r * nu + c for r in range(nv)])
                    kinds.append(0); fclosed.append(closed)
        elif surface_type != "points":
            for r in range(len(rows) - 1):
                a0, b0 = rows[r] * nu, rows[r + 1] * nu
                for c in range(ucount):
                    c2 = (c + 1) % nu
                    q = [a0 + c, a0 + c2, b0 + c2, b0 + c]
                    if surface_type == "triangles" or (surface_type == "alternating_triangles"
                                                       and (r + c) % 2 == 0):
                        faces.append([q[0], q[1], q[2]])
                        faces.append([q[0], q[2], q[3]])
                        kinds += [0, 0]
                    elif surface_type == "alternating_triangles":   # the other diagonal
                        faces.append([q[0], q[1], q[3]])
                        faces.append([q[1], q[2], q[3]])
                        kinds += [0, 0]
                    else:
                        faces.append(q)
                        kinds.append(0)
            fclosed = [True] * len(faces)

            if end_caps and sec_closed and not closed:
                for loop in (list(range(nu))[::-1], [(nv - 1) * nu + c for c in range(nu)]):
                    if end_cap_type == "grid" and nu >= 4 and nu % 2 == 0:
                        from .polyfill import _quad_grid
                        pts_new, fs = _quad_grid(allp, np.asarray(loop, np.int64), len(allp))
                        if pts_new:
                            allp = np.concatenate([allp, np.asarray(pts_new)])
                        faces += [list(map(int, f)) for f in fs]
                        kinds += [1] * len(fs)
                        fclosed += [True] * len(fs)
                    else:
                        faces.append(loop)
                        kinds.append(1)
                        fclosed.append(True)

        g = Geometry()
        g._resize_points(len(allp))
        g.set(POINT, "P", allp.astype(np.float32), owned=True)
        if faces:
            sz = np.array([len(f) for f in faces], np.int32)
            g.set_topology(np.concatenate([np.asarray(f, np.int32) for f in faces]),
                           np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                           np.asarray(fclosed, bool))
        nring = nv * nu                               # number of points on the rings (points added by the end cap grids come after)
        if cap_group and end_caps and faces:
            g.set_group(PRIM, cap_group, np.asarray(kinds) == 1)
        if uv_attrib:
            uu = (np.arange(nu) / max(nu - 1, 1) if not sec_closed
                  else np.arange(nu) / nu)
            uv = np.stack([np.tile(uu, nv), np.repeat(tpar[:nv], nu)], 1)
            if len(allp) > nring:                     # points inside the end caps: uv is the cross-section center (0.5, v of that end)
                extra = np.zeros((len(allp) - nring, 2))
                half_n = (len(allp) - nring) // 2
                extra[:, 0] = 0.5
                extra[half_n:, 1] = tpar[nv - 1]
                uv = np.concatenate([uv, extra])
            g.set(POINT, uv_attrib, uv.astype(np.float32), owned=True)
        parts.append(g)

    return merge(*parts) if parts else Geometry()


# ------------------------------------------------------------------- Skin
def skin(geo, group=None, connectivity="quads", v_wrap=False,
         output="polygons", v_order=4, keep_prims=False, every_n=0,
         auto_resample=True, resample_to=0):
    """
    Matches Houdini's Skin: skin between a set of cross-section curves.

    Cross-sections are sorted by prim number and a layer of faces is laid between each adjacent pair. When the cross-sections are closed, the U direction wraps too.

    auto_resample is a deviation from Houdini: Houdini requires all cross-sections to have the same point count and errors out
    otherwise. Here they are resampled to the same count by default -- in real work cross-sections often come from different
    sources whose point counts naturally do not match, and adding a Resample by hand every time is tedious. Turn it off for strict behaviour.

    With output="nurbs" a single NURBS surface prim is output: order 2 in U (the surface passes exactly through
    the cross-section points), v_order in V to smooth across cross-sections -- exactly the semantics of a loft.
    """
    from . import nurbs as _nb
    sel = _grp.resolve(geo, PRIM, group)
    idxs = [int(i) for i in np.nonzero(sel)[0]]
    if len(idxs) < 2:
        return geo.copy()

    P = geo.get(POINT, "P").astype(np.float64)
    sections, closed_u = [], []
    for i in idxs:
        pid = geo.prim_points(i)
        t = int(geo.prim_type[i])
        if t in (PRIM_NURBS_CURVE, PRIM_BEZIER_CURVE):
            uo = int(geo.get(PRIM, "uorder")[i, 0]) \
                if geo.get(PRIM, "uorder") is not None else 4
            bs = "bezier" if t == PRIM_BEZIER_CURVE else "nurbs"
            n = max(len(pid), 2) * 8
            pts = _nb.tessellate_curve(P[pid], uo, n, None, bs,
                                       geo.pdata(i, "knots_u")).astype(np.float64)
            sections.append(pts)
            closed_u.append(False)
        else:
            if len(pid) < 2:
                continue
            sections.append(P[pid])
            closed_u.append(bool(geo.prim_closed[i]))
    if len(sections) < 2:
        return geo.copy()

    # Align point counts
    target = int(resample_to) if resample_to > 0 else max(len(s_) for s_ in sections)
    if auto_resample or resample_to > 0:
        aligned = []
        for pts, cl in zip(sections, closed_u):
            if len(pts) == target and resample_to <= 0:
                aligned.append(pts)
                continue
            loop = np.concatenate([pts, pts[:1]]) if cl else pts
            d = np.concatenate([[0.0], np.cumsum(
                np.linalg.norm(np.diff(loop, axis=0), axis=1))])
            if d[-1] <= 0:
                aligned.append(np.repeat(pts[:1], target, 0))
                continue
            # Closed cross-sections are sampled to target points (excluding the repeated closing point)
            tt = (np.linspace(0, d[-1], target, endpoint=False) if cl
                  else np.linspace(0, d[-1], target))
            aligned.append(np.stack([np.interp(tt, d, loop[:, k])
                                     for k in range(3)], 1))
        sections = aligned
    else:
        n0 = len(sections[0])
        if any(len(s_) != n0 for s_ in sections):
            raise RuntimeError(
                "Cross-sections have different point counts, cannot skin. Turn on auto_resample to align them automatically, "
                "or add a Resample first to unify the point count.")
        target = n0

    wrap_u = bool(closed_u[0])
    groups_of = ([sections[i:i + int(every_n)]
                  for i in range(0, len(sections), int(every_n))]
                 if every_n and every_n > 1 else [sections])

    parts = []
    if keep_prims:
        parts.append(geo.copy())
    elif (~sel).any():
        parts.append(delete_prims(geo, ~sel))

    for grp in groups_of:
        if len(grp) < 2:
            continue
        nv, nu = len(grp), target
        pts = np.concatenate(grp)

        if output == "nurbs":
            g = Geometry.from_points(pts.astype(np.float32))
            g.set_topology(np.arange(nu * nv, dtype=np.int32),
                           np.array([0, nu * nv], np.int32),
                           np.ones(1, bool),
                           np.array([PRIM_NURBS_SURF], np.uint8))
            g.set(PRIM, "nu", np.array([[nu]], np.int32), owned=True)
            g.set(PRIM, "nv", np.array([[nv]], np.int32), owned=True)
            # order 2 in U: the surface passes exactly through the cross-section points; smooth across cross-sections in V
            g.set(PRIM, "uorder", np.array([[2]], np.int32), owned=True)
            g.set(PRIM, "vorder",
                  np.array([[int(np.clip(v_order, 2, nv))]], np.int32), owned=True)
            parts.append(g)
            continue

        faces = []
        rows = list(range(nv)) + ([0] if v_wrap and nv > 2 else [])
        cols = nu if wrap_u else nu - 1
        for r in range(len(rows) - 1):
            a0, b0 = rows[r] * nu, rows[r + 1] * nu
            for c in range(cols):
                c2 = (c + 1) % nu
                q = [a0 + c, a0 + c2, b0 + c2, b0 + c]
                if connectivity == "triangles":
                    faces.append([q[0], q[1], q[2]])
                    faces.append([q[0], q[2], q[3]])
                else:
                    faces.append(q)
        if faces:
            parts.append(Geometry.from_mesh(pts.astype(np.float32),
                                            np.asarray(faces, np.int32)))
    return merge(*parts) if parts else Geometry()


# --------------------------------------------------------------- Resample
RESAMPLE_TREAT = ("straight_edges", "subdivision_curves", "interpolating_curves")
# pcg100: Houdini's Method (what length is measured by) and Measure (along arc / along chord)
RESAMPLE_METHODS = ("even_length", "even_x", "even_y", "even_z")
RESAMPLE_MEASURES = ("along_arc", "along_chord")


def _rs_positions(T, use_len, L, use_seg, nseg, even_last, keep_last):
    """
    Sample positions over a span of length T (starting at 0; the unit is "the metric used to measure length").
    use_len / use_seg correspond to Houdini's two toggles Maximum Segment Length / Maximum Segments:
    both on = by length, switch to exactly nseg segments if exceeded; only segments on = exactly nseg segments.
    keep_last (Maintain Last Vertex) only matters for "by length, not even": whether to keep the end point when the tail is shorter than a step.
    """
    if use_len:
        if even_last:
            n = max(1, int(round(T / L)))
            pos = np.linspace(0.0, T, n + 1)
        else:
            pos = np.arange(0.0, T, L)
            tail = T - pos[-1]
            # arange excludes the end: when the tail is exactly a full step the end point is a sample anyway, needed even with Maintain Last Vertex off
            if tail > 1e-9 and (keep_last or abs(tail - L) <= 1e-9 * max(L, 1.0)):
                pos = np.append(pos, T)
        if use_seg and len(pos) - 1 > nseg:
            pos = np.linspace(0.0, T, nseg + 1)
        return pos
    return np.linspace(0.0, T, max(1, nseg) + 1)


def _rs_metric_to_arc(dm, d, pos):
    """Metric position -> arc-length position. dm is non-decreasing (with Even X a segment where x does not change is a plateau in dm):
    take the first position that reaches this metric (searchsorted left), so plateau segments are never chosen.
    The only exception is the end point: the position where the metric is used up always goes to the curve's end -- otherwise a tail of the curve
    where x does not change would be dropped entirely (the docs do not say how to handle plateaus; this is our own choice)."""
    m = len(dm)
    j = np.clip(np.searchsorted(dm, pos, "left") - 1, 0, m - 2)
    seg = dm[j + 1] - dm[j]
    u = np.where(seg > 0, (pos - dm[j]) / np.where(seg > 0, seg, 1.0), 0.0)
    arc = d[j] + np.clip(u, 0.0, 1.0) * (d[j + 1] - d[j])
    return np.where(pos >= dm[-1], d[-1], arc)


def _rs_first_chord(Q, r):
    """Starting from Q[0], the first position on the polyline at straight-line distance exactly r from Q[0] (segment index, in-segment parameter); None if there is none."""
    dist = np.linalg.norm(Q[1:] - Q[0], axis=1)
    hit = np.nonzero(dist >= r)[0]
    if not len(hit):
        return None
    # The first vertex at distance >= r from the start is j + 1: Q[j] is still inside the sphere (for j = 0 that is the start), so this segment has length > 0
    # and the sphere surface exits exactly once on this segment
    j = int(hit[0])
    A, dv = Q[j], Q[j + 1] - Q[j]
    a = float(dv @ dv)
    w = A - Q[0]
    b, c = 2.0 * float(w @ dv), float(w @ w) - r * r
    u = (-b + math.sqrt(max(b * b - 4 * a * c, 0.0))) / (2 * a)   # start is inside the sphere, the larger root is the exit point
    return j, u


def _rs_chord_params(Qm, use_len, L, use_seg, nseg, even_last, keep_last):
    """Along Chord: straight-line distances between adjacent samples (the distance on that axis for Even X/Y/Z) are equal.
    Uses PolySpline's _march / _even_params. Returns [(segment index, in-segment parameter)]."""
    from .curves2 import _march, _even_params
    end = (len(Qm) - 2, 1.0)
    if use_len:
        if even_last:
            par, rem = _march(Qm, L)
            # Segment count is rounded the same way as Along Arc: whole steps + what fraction of a step the tail is, rounded
            n = max(1, int(round(len(par) - 1 + rem / L)))
            par = _even_params(Qm, 0.0, n)
        else:
            par, rem = _march(Qm, L)
            if rem <= 1e-9 * max(L, 1.0):
                par[-1] = end
            elif keep_last:
                par.append(end)
        if use_seg and len(par) - 1 > nseg:
            par = _even_params(Qm, 0.0, nseg)
        return par
    return _even_params(Qm, 0.0, max(1, nseg))


def _rs_subdiv_cv(Q, closed):
    """Output as Polygon Curves to be Subdivided Later: solve (c- + 4c + c+)/6 = q,
    so that when these points are subdivided again as a uniform cubic B-spline (the kind used by Treat Polygons As = Subdivision Curves,
    with reflected ghost points at both ends of open curves, so the end points stay put) the limit curve passes exactly through the samples."""
    from .curves2 import _solve_interp
    if len(Q) < 3:
        return Q
    return _solve_interp(Q, closed)


def resample(geo, group=None, by_length=True, length=0.1, segments=10,
             even_last=True, only_points=False, spline_samples=16,
             dist_attrib="", tangent_attrib="", curveu_attrib="",
             curvenum_attrib="", treat_as="straight_edges", max_segments=0,
             measure_method="even_length", measure="along_arc",
             maintain_prim_order=False, by_edge=False, attrib_override=False,
             maintain_last=True, randomize_first=False, subdivide_later=False):
    """
    Matches Houdini's Resample: resample curves by equal length or equal count.

    NURBS / Bezier curves are **evaluated on the curve itself first and then sampled**, rather than measured on the control polygon --
    the control polygon is far from the actual curve, and evenly dividing it gives samples that are not on the curve.

    even_last corresponds to Even Last Segment Same Length: after rounding the segment count, total length / count is divided evenly,
    every segment the same length; when off, step strictly by length, leaving a short last segment.

    Closed polygons are sampled around the whole loop (including the closing edge), and the output stays closed.

    treat_as (Houdini's Treat Polygons As): what kind of curve the polygon polyline is treated as before measuring length and sampling.
      straight_edges        the polyline itself (default)
      subdivision_curves    a uniform cubic B-spline with these points as control points -- the curve is pulled inward, does not pass through the middle points, passes through the two end points
      interpolating_curves  a Catmull-Rom spline through every point
    The latter two first densify the polyline with PolySpline's machinery (spline_samples per segment), then sample as with straight edges;
    point attributes are interpolated along with the spline.

    max_segments > 0 (in Houdini both Maximum Segment Length and Maximum Segments are checked):
    when the segment count computed from length exceeds it, switch to exactly max_segments evenly divided segments.

    pcg100 additions to match Houdini (all defaults = previous behaviour):
      measure_method   Method: even_length measures the real length; even_x/y/z measure only the length along that axis
      measure          Measure: along_arc measures along the curve (the curve length between two samples is equal);
                       along_chord measures the straight-line distance between two samples
      maintain_prim_order  unselected prims stay in their original position. When off they come before the resampled results -- the previous behaviour,
                       and also what the docs say Houdini does when it is off (the resampled ones go after the untouched ones)
      by_edge          Resample by Polygon Edge: each edge is resampled separately, all original corners are kept
      attrib_override  prim attributes segment_length / num_segments override Length / Segments; <= 0 turns that toggle off
      maintain_last    Maintain Last Vertex: when by length and not even, keep the original curve's end point even if the tail is shorter than a step
      randomize_first  Randomize First Segment Length: first segment length = Length x a random number (seeded by prim number)
      subdivide_later  Output as Polygon Curves to be Subdivided Later
    """
    from . import nurbs as _nb
    if treat_as not in RESAMPLE_TREAT:
        raise ValueError(f"Treat Polygons As must be one of {RESAMPLE_TREAT}, got {treat_as!r}")
    if measure_method not in RESAMPLE_METHODS:
        raise ValueError(f"Method must be one of {RESAMPLE_METHODS}, got {measure_method!r}")
    if measure not in RESAMPLE_MEASURES:
        raise ValueError(f"Measure must be one of {RESAMPLE_MEASURES}, got {measure!r}")
    sel = _grp.resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()
    orig = np.arange(geo.nprims)                 # each prim's number in the input (used for ordering and random seeds)
    if treat_as != "straight_edges":
        from . import curves2 as _c2
        tmp, oname = "__resample_sel", "__resample_orig"
        g0 = geo.copy()
        g0.set_group(PRIM, tmp, sel & (geo.prim_type == PRIM_POLY))
        g0.set(PRIM, oname, np.arange(geo.nprims, dtype=np.int64)[:, None], owned=True)
        g1 = _c2.poly_spline(g0, tmp, "bspline" if treat_as == "subdivision_curves" else "catmull_rom",
                             0.5, max(1, int(spline_samples)))[0]
        m1 = g1.groups[PRIM].get(tmp)
        both = np.zeros(g1.nprims, bool) if m1 is None else np.array(m1, bool)
        both |= _grp.resolve(g1, PRIM, group) & (g1.prim_type != PRIM_POLY)   # selected NURBS / Bezier as before
        g1.groups[PRIM].pop(tmp, None)
        orig = np.asarray(g1.attribs[PRIM].pop(oname))[:, 0].astype(np.int64)
        geo, sel = g1, both

    P = geo.get(POINT, "P").astype(np.float64)
    pt_attrs = {k: v for k, v in geo.attribs[POINT].items() if k != "P"}
    curve_no = 0
    ax = None if measure_method == "even_length" else "xyz".index(measure_method[-1])
    a_len = geo.get(PRIM, "segment_length") if attrib_override else None
    a_num = geo.get(PRIM, "num_segments") if attrib_override else None
    untouched = ~sel
    out_parts, keys = [], []

    for i in np.nonzero(sel)[0]:
        idx = geo.prim_points(i)
        t = int(geo.prim_type[i])
        closed = bool(geo.prim_closed[i])

        # Two toggles + values; prim attributes can override per prim (Allow Primitive Attributes to Override)
        use_len, L = bool(by_length), max(float(length), 1e-9)
        nseg = int(max_segments) if by_length else max(1, int(segments))
        use_seg = (not by_length) or nseg > 0
        if a_len is not None:
            v = float(np.asarray(a_len)[i].ravel()[0])
            use_len, L = v > 0, max(v, 1e-9)
        if a_num is not None:
            v = int(np.asarray(a_num)[i].ravel()[0])
            use_seg, nseg = v > 0, v
        if not use_len and not use_seg:
            untouched = untouched.copy()
            untouched[i] = True                  # both toggles turned off by attributes: this one is not resampled, left as is
            continue

        if t in (PRIM_NURBS_CURVE, PRIM_BEZIER_CURVE):
            uo = int(geo.get(PRIM, "uorder")[i, 0]) \
                if geo.get(PRIM, "uorder") is not None else 4
            bs = "bezier" if t == PRIM_BEZIER_CURVE else "nurbs"
            dense = max(8, len(idx) * int(spline_samples))
            poly = _nb.tessellate_curve(P[idx], uo, dense, None, bs,
                                        geo.pdata(i, "knots_u")).astype(np.float64)
            src_idx = None                      # points on the evaluated curve do not correspond to original points
        else:
            poly = P[idx]
            if closed and len(poly) >= 3:
                poly = np.concatenate([poly, poly[:1]])
            src_idx = idx
        if len(poly) < 2:
            continue

        d = np.concatenate([[0.0],
                            np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))])
        total = float(d[-1])
        if total <= 1e-12:
            continue

        keep_last = bool(maintain_last) or closed      # the end of a closed curve is its start, always needed
        rnd = None
        if randomize_first and use_len:
            # Houdini: seeded by prim number. Here the prim number in the input is used; (0, 1] avoids a zero-length first segment
            rnd = L * (1.0 - np.random.default_rng(int(orig[i])).random())
        edge_mode = bool(by_edge) and treat_as == "straight_edges" and src_idx is not None
        if ax is None:
            dm, Qm = d, poly
        else:
            dm = np.concatenate([[0.0], np.cumsum(np.abs(np.diff(poly[:, ax])))])
            Qm = np.zeros_like(poly)
            Qm[:, ax] = poly[:, ax]
        T = float(dm[-1])

        if edge_mode:
            # Each edge sampled separately, corners kept. Edges are straight, so along arc and along chord are the same; random first segment not used
            ps = []
            for k in range(len(poly) - 1):
                e = float(dm[k + 1] - dm[k])
                loc = (_rs_positions(e, use_len, L, use_seg, nseg, even_last, True)
                       if e > 1e-12 else np.array([0.0, e]))
                fr = loc / e if e > 1e-12 else np.array([0.0, 1.0])
                ps.append(d[k] + fr[:-1] * (d[k + 1] - d[k]))
            ps.append([total])
            pos = np.concatenate(ps)
        elif T <= 1e-12:
            pos = np.array([0.0, total])         # no extent along that axis: keep only start and end
        elif measure == "along_chord":
            if rnd is not None and (h := _rs_first_chord(Qm, rnd)) is not None:
                j0, u0 = h
                hp = Qm[j0] + u0 * (Qm[j0 + 1] - Qm[j0])
                # From the first sample on, the remaining polyline proceeds as usual; (the measure-zero case where the sample is exactly the end produces an extra coincident end point)
                sub = np.concatenate([hp[None], Qm[j0 + 1:]])
                par = _rs_chord_params(sub, use_len, L, use_seg, nseg, even_last, keep_last)
                par = [(0, 0.0)] + [(j0, u0 + u * (1 - u0)) if j == 0 else (j0 + j, u) for j, u in par]
            else:
                par = _rs_chord_params(Qm, use_len, L, use_seg, nseg, even_last, keep_last)
            jj = np.array([p[0] for p in par], np.int64)
            uu = np.array([p[1] for p in par], np.float64)
            pos = d[jj] + uu * (d[jj + 1] - d[jj])
        else:
            if rnd is not None and T > rnd:
                pm = np.concatenate([[0.0], rnd + _rs_positions(
                    T - rnd, use_len, L, use_seg, nseg, even_last, keep_last)])
            else:
                pm = _rs_positions(T, use_len, L, use_seg, nseg, even_last, keep_last)
            pos = pm if ax is None else _rs_metric_to_arc(dm, d, pm)

        if closed:
            pos = pos[:-1]                      # the closing point coincides with the start, drop it

        Q = np.stack([np.interp(pos, d, poly[:, k]) for k in range(3)], 1)
        Qo = _rs_subdiv_cv(Q, closed) if (subdivide_later and not only_points) else Q
        g = (Geometry.from_points(Qo.astype(np.float32)) if only_points
             else Geometry.from_mesh(
                 Qo.astype(np.float32),
                 [np.arange(len(Q), dtype=np.int32)], closed=closed))

        # Point attributes are interpolated linearly along the curve. When the original point order is known, interpolate by arc-length parameter;
        # points from evaluating a curve have no correspondence and can only be interpolated from the end points -- this needs to be stated clearly,
        # otherwise users would assume attributes follow point by point on NURBS too.
        for k, v in pt_attrs.items():
            if is_string(v):
                src = v[src_idx] if src_idx is not None else v[idx]
                pick = np.clip(np.searchsorted(d, pos) - 1, 0, len(src) - 1) \
                    if src_idx is not None else np.zeros(len(pos), int)
                g.set_string(POINT, k, src[pick, 0])
            elif src_idx is not None:
                vv = v[src_idx].astype(np.float64)
                if closed:
                    vv = np.concatenate([vv, vv[:1]])
                g.set(POINT, k, np.stack(
                    [np.interp(pos, d, vv[:, c]) for c in range(vv.shape[1])],
                    1).astype(np.float32), owned=True)

        if dist_attrib:
            g.set(POINT, dist_attrib, pos[:, None].astype(np.float32), owned=True)
        if curveu_attrib:
            g.set(POINT, curveu_attrib,
                  (pos / total)[:, None].astype(np.float32), owned=True)
        if curvenum_attrib:
            g.set(POINT, curvenum_attrib,
                  np.full((len(Q), 1), curve_no, np.float32), owned=True)
        if tangent_attrib and len(Q) >= 2:
            tg = np.gradient(Q, axis=0)
            if closed:
                tg = np.roll(Q, -1, 0) - np.roll(Q, 1, 0)
            tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-12)
            g.set(POINT, tangent_attrib, tg.astype(np.float32), owned=True)

        # prim attributes and groups are copied from the source prim
        if not only_points:
            for k, v in geo.attribs[PRIM].items():
                g.set(PRIM, k, v[i:i + 1], owned=True)
            for k, v in geo.groups[PRIM].items():
                g.set_group(PRIM, k, np.array([bool(v[i])]))
        out_parts.append(g)
        keys.append(int(orig[i]))
        curve_no += 1

    parts = ([delete_prims(geo, untouched)] if untouched.any() else []) + out_parts
    out = merge(*parts) if parts else Geometry()
    if maintain_prim_order and not only_points:
        # Untouched prims are inserted back at their input numbers (point numbers stay, only prims are ordered). Ordering is needed even with no untouched prims:
        # with Treat Polygons As densifying, selected NURBS / Bezier are moved ahead of the polygons
        # (when only points are output the resampled ones have no prims, so there is nothing to order)
        kk = np.concatenate([orig[untouched], np.asarray(keys, np.int64)])
        out = _apply_prim_order(out, np.argsort(kk, kind="stable"))
    return out


# ---------------------------------------------------------------- Reverse
def reverse_prims(geo, group=None, mode="reverse", u_offset=0, v_offset=0):
    """
    Matches Houdini's Reverse: reorder the vertices of prims.

    The whole operator comes down to **computing a corner permutation for each prim**, then reordering vertex_point,
    all vertex attributes and vertex groups together by that permutation. That way, whether it is a plain reversal or
    a U/V transform of a surface, all follow-up processing takes the same path and no class of data is missed.

    mode:
      reverse    reverse vertex order -- the normal flips with it, the most common use
      reverse_u  same as reverse for polygons; flips columns of the (nu,nv) grid for surfaces
      reverse_v  only meaningful for surfaces, flips rows
      swap_uv    only meaningful for surfaces, transposes (nu/nv and the knot vectors are swapped together)
      shift      cyclic shift. For closed polygons it changes "which point it starts at"; the shape is unchanged --
                 used to align the seams of sweep / copy to points
    """
    if mode == "none" or geo.nprims == 0:
        return geo.copy()
    sel = _grp.resolve(geo, PRIM, group)
    if not sel.any():
        return geo.copy()

    sizes = geo.prim_sizes()
    nu_a, nv_a = geo.get(PRIM, "nu"), geo.get(PRIM, "nv")
    perm = np.arange(geo.nvertices, dtype=np.int64)
    swapped = []

    for i in np.nonzero(sel)[0]:
        o, n = int(geo.prim_offset[i]), int(sizes[i])
        is_surf = (int(geo.prim_type[i]) in (PRIM_NURBS_SURF, PRIM_BEZIER_SURF)
                   and nu_a is not None and nv_a is not None)
        if is_surf:
            nu, nv = int(nu_a[i, 0]), int(nv_a[i, 0])
            if nu * nv != n:
                continue
            g = np.arange(n).reshape(nv, nu)
            if mode in ("reverse", "reverse_u"):
                g = g[:, ::-1]
            if mode in ("reverse", "reverse_v"):
                g = g[::-1, :]
            if mode == "swap_uv":
                g = g.T
                swapped.append(i)
            if mode == "shift":
                g = np.roll(g, (int(v_offset), int(u_offset)), axis=(0, 1))
            local = g.reshape(-1)
        elif mode in ("reverse", "reverse_u"):
            local = np.arange(n)[::-1]
        elif mode == "shift":
            local = np.roll(np.arange(n), -int(u_offset))
        else:
            continue                        # reverse_v / swap_uv are meaningless for polygons
        perm[o:o + n] = o + local

    out = geo.copy()
    out.set_topology(geo.vertex_point[perm], geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[perm], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[perm])

    if swapped:
        # After transposing, nu/nv and the knot vectors of both directions must be swapped too, otherwise surface evaluation
        # interprets the control points with the wrong grid size and the result is complete garbage
        nu2 = np.array(nu_a, copy=True)
        nv2 = np.array(nv_a, copy=True)
        for i in swapped:
            nu2[i, 0], nv2[i, 0] = int(nv_a[i, 0]), int(nu_a[i, 0])
            ku = geo.pdata(i, "knots_u")
            kv = geo.pdata(i, "knots_v")
            if ku is not None or kv is not None:
                out.set_pdata(i, "knots_u", kv)
                out.set_pdata(i, "knots_v", ku)
            uo = geo.get(PRIM, "uorder")
            vo = geo.get(PRIM, "vorder")
            if uo is not None and vo is not None:
                u2 = np.array(uo, copy=True)
                v2 = np.array(vo, copy=True)
                u2[i, 0], v2[i, 0] = int(vo[i, 0]), int(uo[i, 0])
                out.set(PRIM, "uorder", u2, owned=True)
                out.set(PRIM, "vorder", v2, owned=True)
        out.set(PRIM, "nu", nu2, owned=True)
        out.set(PRIM, "nv", nv2, owned=True)
    return out


# -------------------------------------------------------------------- Sort
def _sort_order(geo, cls, mode, pos, seed=0, offset=0,
                axis=(0, 1, 0), center=None, target=(0, 0, 0),
                attrib="", component=0, expression=""):
    """
    Compute a sort permutation. pos is the representative position of this class of elements (P for points, centroid for primitives).
    Returns None when not sorting.
    """
    n = len(pos)
    if n == 0 or mode in ("none", "no_change"):
        return None
    idx = np.arange(n)

    if mode == "reverse":
        return idx[::-1]
    if mode == "shift":
        return np.roll(idx, -int(offset))
    if mode == "random":
        return np.random.default_rng(int(seed)).permutation(n)
    if mode in ("x", "y", "z"):
        return np.argsort(pos[:, "xyz".index(mode)], kind="stable")
    if mode == "proximity":
        t = np.asarray(target, np.float64)
        return np.argsort(np.linalg.norm(pos - t, axis=1), kind="stable")
    if mode == "along_vector":
        v = np.asarray(axis, np.float64)
        v = v / max(np.linalg.norm(v), 1e-12)
        return np.argsort(pos @ v, kind="stable")
    if mode == "attribute":
        a = geo.get(cls, attrib)
        if a is None:
            return None
        col = np.asarray(a)
        if is_string(col):
            return np.argsort(col[:, 0], kind="stable")
        c = int(np.clip(component, 0, col.shape[1] - 1))
        return np.argsort(col[:, c], kind="stable")
    if mode == "expression":
        from . import wrangle as _w
        key = _w.eval_expr(geo, expression, cls)
        if key is None:
            return None
        return np.argsort(np.asarray(key, np.float64).reshape(-1), kind="stable")
    if mode == "spatial_locality":
        # Morton code: quantize the three coordinates and interleave their bits. Adjacent codes correspond to spatially adjacent elements,
        # giving good cache locality during traversal and better vertex cache behaviour when exported to an engine.
        mn, mx = pos.min(0), pos.max(0)
        q = ((pos - mn) / np.maximum(mx - mn, 1e-12) * 1023).astype(np.uint64)

        def spread(v):
            v = (v | (v << np.uint64(16))) & np.uint64(0x030000FF)
            v = (v | (v << np.uint64(8))) & np.uint64(0x0300F00F)
            v = (v | (v << np.uint64(4))) & np.uint64(0x030C30C3)
            v = (v | (v << np.uint64(2))) & np.uint64(0x09249249)
            return v
        code = spread(q[:, 0]) | (spread(q[:, 1]) << np.uint64(1)) \
            | (spread(q[:, 2]) << np.uint64(2))
        return np.argsort(code, kind="stable")
    if mode == "circular":
        # Sort by angle around an axis. A scattered ring of points needs this to be connected into a correct polygon loop --
        # sorting by X/Y/Z only gives a zigzag.
        ax = np.asarray(axis, np.float64)
        ax = ax / max(np.linalg.norm(ax), 1e-12)
        c = np.asarray(center if center is not None else pos.mean(0), np.float64)
        e1 = np.cross(ax, [0.0, 0.0, 1.0])
        if np.linalg.norm(e1) < 1e-6:
            e1 = np.cross(ax, [1.0, 0.0, 0.0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(ax, e1)
        v = pos - c
        ang = np.arctan2(v @ e2, v @ e1)
        return np.argsort(ang, kind="stable")
    return None


def _apply_point_order(geo, order):
    """Reorder points to a new order. Everything that references point numbers must follow."""
    inv = np.empty(len(order), np.int32)
    inv[order] = np.arange(len(order), dtype=np.int32)
    out = Geometry()
    out._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[order], owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v[order])
    out.set_topology(inv[geo.vertex_point], geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    for cls in (VERTEX, PRIM):
        for k, v in geo.attribs[cls].items():
            out.set(cls, k, v, owned=True)
        for k, v in geo.groups[cls].items():
            out.set_group(cls, k, v)
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    # Edge groups store point pairs; when point numbers change they must be remapped
    for k, v in geo.edge_groups.items():
        out.set_edge_group(k, inv[np.asarray(v, np.int64)] if len(v) else v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


def _apply_prim_order(geo, order):
    """Reorder primitives to a new order. vertex attributes follow their corners."""
    sizes = geo.prim_sizes()
    corner = _gather_blocks(geo.prim_offset[:-1][order], sizes[order])
    sz = sizes[order].astype(np.int32)
    out = Geometry()
    out._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v, owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    out.set_topology(geo.vertex_point[corner],
                     np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                     geo.prim_closed[order], geo.prim_type[order])
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[corner], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[corner])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[order], owned=True)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[order])
    out.prim_data = geo.remap_prim_data(order)
    out.edge_groups = dict(geo.edge_groups)      # point numbers unchanged
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


def sort_geo(geo, point_mode="none", prim_mode="none",
             point_reverse=False, prim_reverse=False,
             seed=0, offset=0, axis=(0, 1, 0), use_center=False,
             center=(0, 0, 0), target=(0, 0, 0),
             point_attrib="", prim_attrib="", component=0,
             point_expr="", prim_expr="",
             points_by_vertex_order=False, prim=None):
    """
    Matches Houdini's Sort. It changes **numbering**; the geometry shape is unchanged.

    circular is a sort by angle around an axis: a scattered ring of points needs it to connect into a correct polygon loop;
    sorting by X/Y/Z only gives a zigzag.

    prim: the primitive sort's own set {seed, offset, axis, use_center, center, target,
    component} (Houdini's Primitive Sort has its own set). Missing keys / not given fall back to the point ones.
    """
    pp = {"seed": seed, "offset": offset, "axis": axis, "use_center": use_center,
          "center": center, "target": target, "component": component}
    pp.update(prim or {})
    g = geo.copy()
    if points_by_vertex_order and g.nvertices:
        # Renumber points in the order their vertices appear in primitives. Common before exporting to an engine or stripifying.
        seen, order = set(), []
        for v in g.vertex_point.tolist():
            if v not in seen:
                seen.add(v)
                order.append(v)
        order += [i for i in range(g.npoints) if i not in seen]
        g = _apply_point_order(g, np.asarray(order, np.int64))

    if point_mode not in ("none", "no_change") and g.npoints:
        o = _sort_order(g, POINT, point_mode, g.get(POINT, "P").astype(np.float64),
                        seed, offset, axis,
                        np.asarray(center, np.float64) if use_center else None,
                        target, point_attrib, component, point_expr)
        if o is not None:
            g = _apply_point_order(g, o[::-1] if point_reverse else o)

    if prim_mode not in ("none", "no_change") and g.nprims:
        o = _sort_order(g, PRIM, prim_mode, prim_centers(g).astype(np.float64),
                        pp["seed"], pp["offset"], pp["axis"],
                        np.asarray(pp["center"], np.float64) if pp["use_center"] else None,
                        pp["target"], prim_attrib, pp["component"], prim_expr)
        if o is not None:
            g = _apply_prim_order(g, o[::-1] if prim_reverse else o)
    return g


# ------------------------------------------------------------ attribute delete
def match_names(names, pattern):
    """
    Houdini-style name matching: space-separated items, supports * ? wildcards, a ^ prefix means exclude.

    e.g. "N uv*"      matches N and everything starting with uv
        "* ^P ^N"    everything except P and N
    Exclusions apply after inclusions regardless of order -- "^P *" and "* ^P" give the same result,
    so users do not have to worry about order.
    """
    import fnmatch
    toks = [t for t in str(pattern or "").split() if t]
    if not toks:
        return []
    inc = [t for t in toks if not t.startswith("^")]
    exc = [t[1:] for t in toks if t.startswith("^")]
    out = []
    for n in names:
        if inc and not any(fnmatch.fnmatchcase(n, t) for t in inc):
            continue
        if any(fnmatch.fnmatchcase(n, t) for t in exc):
            continue
        out.append(n)
    return out


def delete_attribs(geo, point="", vertex="", prim="", detail="", invert=False):
    """
    Matches Houdini's Attribute Delete.

    invert corresponds to Delete Non Selected: deletes the ones that did **not** match.

    Point P is always kept -- without a position it is not geometry. Houdini does not allow deleting it either,
    so rather than giving the user an error or a pile of empty arrays, it is simply skipped.
    """
    g = geo.copy()
    for cls, pat in ((POINT, point), (VERTEX, vertex),
                     (PRIM, prim), (DETAIL, detail)):
        names = list(geo.attribs[cls].keys())
        # Empty pattern = leave this class alone. Especially important with invert: treating empty as "delete what did not match"
        # would wipe out the whole class of attributes when the user simply left that field blank.
        if not names or not str(pat or "").strip():
            continue
        hit = set(match_names(names, pat))
        drop = [n for n in names if n not in hit] if invert \
            else [n for n in names if n in hit]
        for n in drop:
            if cls == POINT and n == "P":
                continue
            g.attribs[cls].pop(n, None)
    g._topo = geo._topo
    return g


def delete_groups(geo, point="", vertex="", prim="", edge="", invert=False):
    """
    Matches Houdini's Group Delete. Name matching rules are the same as Attribute Delete.

    Edge groups are handled too -- they are first-class citizens in this model like point/primitive groups; leaving them out
    would make the common operation "clear all groups" leave a pile of edge groups behind.

    An empty field = leave that class alone. Especially important with invert: empty does not mean "select all".
    """
    g = geo.copy()
    for cls, pat in ((POINT, point), (VERTEX, vertex), (PRIM, prim)):
        names = list(geo.groups[cls].keys())
        if not names or not str(pat or "").strip():
            continue
        hit = set(match_names(names, pat))
        for n in ([x for x in names if x not in hit] if invert
                  else [x for x in names if x in hit]):
            g.groups[cls].pop(n, None)

    names = list(geo.edge_groups.keys())
    if names and str(edge or "").strip():
        hit = set(match_names(names, edge))
        for n in ([x for x in names if x not in hit] if invert
                  else [x for x in names if x in hit]):
            g.edge_groups.pop(n, None)
    g._topo = geo._topo
    return g


# ---------------------------------------------------------------- type conversion
def convert_prims(geo, to="triangles", group=None):
    """
    prim type conversion, matching Houdini's Convert SOP -- but only covering types that actually exist
    in this model. NURBS / Bezier are not in this data structure; that needs basis functions, knot vectors, surface evaluation,
    a whole machinery that cannot be faked here.

    to:
      triangles  fan-triangulate the selected faces. prim/vertex attributes are inherited from the source face
      polygons   close the selected polylines into faces
      polylines  open the selected faces into polylines (topology unchanged, just no longer closed)
      points     drop the topology of the selected prims, **all points are kept**

    prim order is preserved: the triangles from triangulating a face are placed at its original position,
    rather than all piled at the end. In procedural pipelines downstream nodes depend on prim numbers.
    """
    sel = _grp.resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()

    if to in ("polygons", "polylines"):
        g = geo.copy()
        pc = np.array(geo.prim_closed, copy=True)
        pc[sel] = (to == "polygons")
        g.set_topology(geo.vertex_point, geo.prim_offset, pc, geo.prim_type)
        return g

    sizes = geo.prim_sizes()
    keep = ~sel
    keep_idx = np.nonzero(keep)[0]
    keep_corner = _gather_blocks(geo.prim_offset[:-1][keep], sizes[keep])

    if to == "points":
        new_sizes = sizes[keep]
        src_corner = keep_corner
        src_prim = keep_idx
        closed = geo.prim_closed[keep]
        ptype = geo.prim_type[keep]
        order = np.argsort(src_prim, kind="stable")
    elif to == "triangles":
        tri, cor = geo.triangles(with_corners=True)
        if len(cor):
            tsrc = geo.vertex_prim()[cor[:, 0]]
            m = sel[tsrc]
            cor, tsrc = cor[m], tsrc[m]
        else:
            tsrc = np.zeros(0, np.int32)
        src_corner = np.concatenate([keep_corner, cor.reshape(-1)]).astype(np.int64)
        src_prim = np.concatenate([keep_idx, tsrc]).astype(np.int64)
        new_sizes = np.concatenate([sizes[keep], np.full(len(tsrc), 3)]).astype(np.int32)
        closed = np.concatenate([geo.prim_closed[keep], np.ones(len(tsrc), bool)])
        ptype = np.concatenate([geo.prim_type[keep],
                                np.full(len(tsrc), PRIM_POLY, np.uint8)])
        order = np.argsort(src_prim, kind="stable")     # keep the original prim order
    else:
        raise ValueError(f"Unknown conversion target: {to}")

    # Reorder the variable-length prim blocks by order
    old_start = np.concatenate([[0], np.cumsum(new_sizes)])[:-1]
    sz = new_sizes[order]
    new_off = np.concatenate([[0], np.cumsum(sz)]).astype(np.int32)
    corner = src_corner[_gather_blocks(old_start[order], sz)]

    out = Geometry()
    out._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v, owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    out.set_topology(geo.vertex_point[corner], new_off, closed[order], ptype[order])
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[corner], owned=True)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[src_prim[order]], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[corner])
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v[src_prim[order]])
    out.prim_data = geo.remap_prim_data(src_prim[order])
    out.edge_groups = dict(geo.edge_groups)          # point numbers unchanged
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


# ------------------------------------------------------------------ NURBS
def to_spline(geo, shape="surface", basis="nurbs", group=None,
              uorder=4, vorder=4, interpolate=False):
    """
    Convert to spline prims. Corresponds to NURBS/Bezier Curve / Surface in Houdini's Convert.

    shape="curve"   each selected prim becomes one curve whose vertices are the control points
    shape="surface" the selected quads must form a **structured grid**; the whole patch becomes one surface prim

    basis="nurbs"   uniform clamped knots
    basis="bezier"  piecewise Bezier knots (interior breakpoint multiplicity order-1). The control point count must satisfy
                    n = segs*(order-1)+1; if not, it is first resampled by chord length to align --
                    Houdini does it by inserting control points; resampling is visually equivalent and much simpler.

    interpolate corresponds to Interpolate Through Hulls:
      False input points are used directly as control points; the surface lies inside the hull and does not pass through the middle points
      True  solve a linear system for control points so the surface **passes through** the original points
    """
    from . import nurbs as _nb
    from . import topology as _tp
    sel = _grp.resolve(geo, PRIM, group)
    P = geo.get(POINT, "P")
    if geo.nprims == 0 or not sel.any():
        return geo.copy()
    is_bez = (basis == "bezier")
    SURF = PRIM_BEZIER_SURF if is_bez else PRIM_NURBS_SURF
    CURVE = PRIM_BEZIER_CURVE if is_bez else PRIM_NURBS_CURVE

    if shape == "surface":
        idx = _tp.quad_grid_index(geo, sel)
        if idx is None:
            raise RuntimeError(
                "Converting to a NURBS surface requires the selected faces to form a structured quad grid.\n"
                "  The current selection does not: it may be triangles, a closed surface (box/sphere/uncapped tube),\n"
                "  or a patch that is not a complete rectangle. Use a Grid first, or use group to select just one patch.")
        nv, nu = idx.shape
        pts = P[idx]                                   # (nv, nu, 3)
        if is_bez:
            # Both directions must be aligned to a valid control point count
            nu2 = _nb.valid_bezier_count(nu, uorder)
            nv2 = _nb.valid_bezier_count(nv, vorder)
            if (nu2, nv2) != (nu, nv):
                pts = np.stack([_nb.resample_points(pts[i], nu2)
                                for i in range(nv)])
                pts = np.stack([_nb.resample_points(pts[:, j], nv2)
                                for j in range(nu2)], 1)
                nu, nv = nu2, nv2
        kvu = kvv = None
        if interpolate:
            cps, kvu, kvv, _, _ = _nb.interpolate_surface(
                pts, uorder, vorder, "bezier" if is_bez else "nurbs",
                return_knots=True)
            cps = cps.reshape(-1, 3)
        else:
            cps = pts.reshape(-1, 3)

        out = Geometry()
        keep = ~sel
        # Unselected prims are kept as they are; the NURBS surface is appended at the end
        base = delete_prims(geo, keep) if keep.any() else Geometry()
        nbase = base.npoints
        allP = np.concatenate([base.get(POINT, "P"), cps]) if nbase else cps
        out._resize_points(len(allP))
        out.set(POINT, "P", allP, owned=True)
        vp = np.concatenate([base.vertex_point,
                             np.arange(nbase, nbase + nu * nv, dtype=np.int32)])
        off = np.concatenate([base.prim_offset, [base.prim_offset[-1] + nu * nv]])
        out.set_topology(vp, off.astype(np.int32),
                         np.concatenate([base.prim_closed, [True]]),
                         np.concatenate([base.prim_type,
                                         [SURF]]).astype(np.uint8))
        # The non-uniform knots computed by interpolation are stored in the side channel and later evaluation must use them,
        # otherwise the surface will not pass through the data points -- the knot vector is part of the solution, not optional decoration.
        if kvu is not None:
            out.set_pdata(out.nprims - 1, "knots_u", kvu)
            out.set_pdata(out.nprims - 1, "knots_v", kvv)
        # For the part not converted to a surface, groups must stay; the new surface prim belongs to no old group
        for k, v in base.groups[PRIM].items():
            out.set_group(PRIM, k, np.concatenate([v, [False]]))
        for k, v in base.groups[POINT].items():
            out.set_group(POINT, k, np.concatenate([v, np.zeros(nu * nv, bool)]))

        for k in ("nu", "nv", "uorder", "vorder"):
            old = base.get(PRIM, k)
            val = {"nu": nu, "nv": nv, "uorder": uorder, "vorder": vorder}[k]
            col = np.zeros((base.nprims, 1), np.int32) if old is None else old
            out.set(PRIM, k, np.concatenate([col, [[val]]]), owned=True)
        return out

    # ---- curves ----
    # Bezier may need a different control point count, which means rebuilding topology; NURBS just changes type in place.
    need_rebuild = is_bez and any(
        _nb.valid_bezier_count(len(geo.prim_points(i)), uorder) !=
        len(geo.prim_points(i)) for i in np.nonzero(sel)[0])

    if not need_rebuild:
        g = geo.copy()
        ptype = np.array(geo.prim_type, copy=True)
        ptype[sel] = CURVE
        old = geo.get(PRIM, "uorder")
        uo = np.array(old, copy=True) if old is not None \
            else np.zeros((geo.nprims, 1), np.int32)
        uo[sel] = uorder
        if interpolate:
            Pw = g.get_w(POINT, "P")
            for i in np.nonzero(sel)[0]:
                idx = geo.prim_points(i)
                if len(idx) >= 2:
                    c, kv, _ = _nb.interpolate_curve(
                        P[idx], uorder, "bezier" if is_bez else "nurbs",
                        return_knots=True)
                    Pw[idx] = c
                    g.set_pdata(int(i), "knots_u", kv)
            g.set(POINT, "P", Pw, owned=True)
        g.set_topology(geo.vertex_point, geo.prim_offset, geo.prim_closed, ptype)
        g.set(PRIM, "uorder", uo, owned=True)
        return g

    parts = [delete_prims(geo, ~sel)] if (~sel).any() else []
    for i in np.nonzero(sel)[0]:
        idx = geo.prim_points(i)
        if len(idx) < 2:
            continue
        m = _nb.valid_bezier_count(len(idx), uorder)
        pts = _nb.resample_points(P[idx], m)
        kv = None
        if interpolate:
            pts, kv, _ = _nb.interpolate_curve(pts, uorder, "bezier",
                                               return_knots=True)
        c = Geometry.from_mesh(pts, [np.arange(m, dtype=np.int32)], closed=False)
        c.set_topology(c.vertex_point, c.prim_offset, c.prim_closed,
                       np.array([CURVE], np.uint8))
        c.set(PRIM, "uorder", np.array([[uorder]], np.int32), owned=True)
        if kv is not None:
            c.set_pdata(0, "knots_u", kv)
        parts.append(c)
    return merge(*parts)


def spline_to_polygons(geo, group=None, u_divs=16, v_divs=16):
    """Tessellate NURBS / Bezier prims into polygons or polylines. Other prims are kept as they are."""
    from . import nurbs as _nb
    sel = _grp.resolve(geo, PRIM, group)
    isn = sel & np.isin(geo.prim_type, SPLINE_TYPES)
    if not isn.any():
        return geo.copy()

    P = geo.get(POINT, "P")
    nu_a, nv_a = geo.get(PRIM, "nu"), geo.get(PRIM, "nv")
    uo_a, vo_a = geo.get(PRIM, "uorder"), geo.get(PRIM, "vorder")
    parts = [delete_prims(geo, ~isn)] if (~isn).any() else []

    for i in np.nonzero(isn)[0]:
        cps = P[geo.prim_points(i)]
        t = int(geo.prim_type[i])
        bs = "bezier" if t in (PRIM_BEZIER_CURVE, PRIM_BEZIER_SURF) else "nurbs"
        if t in (PRIM_NURBS_SURF, PRIM_BEZIER_SURF):
            nu = int(nu_a[i, 0]); nv = int(nv_a[i, 0])
            uo = int(uo_a[i, 0]) if uo_a is not None else 4
            vo = int(vo_a[i, 0]) if vo_a is not None else 4
            pts, faces = _nb.tessellate_surface(
                cps, nu, nv, uo, vo, u_divs, v_divs, None, bs,
                geo.pdata(i, "knots_u"), geo.pdata(i, "knots_v"))
            parts.append(Geometry.from_mesh(pts, faces))
        else:
            uo = int(uo_a[i, 0]) if uo_a is not None else 4
            pts = _nb.tessellate_curve(cps, uo, u_divs, None, bs,
                                       geo.pdata(i, "knots_u"))
            parts.append(Geometry.from_mesh(
                pts, [np.arange(len(pts), dtype=np.int32)], closed=False))
    return merge(*parts)


# ------------------------------------------------------------- PolyExtrude
def _extrude_regions(geo, sel, divide_into):
    """
    Assign each selected prim a "region id". This one concept unifies the two modes
    of Divide Into:

      connected  prims in the same connected piece share one region -> no side walls on interior edges between them,
                 points are shared too, and the extruded front is one connected piece
      individual each prim is its own region -> every edge gets side walls, points are independent

    With region ids, "which edges get side walls" comes down to a single criterion: the region ids on the two sides of the edge differ (or there is only
    one side). No need to write a separate path for each mode.
    """
    from . import topology as _tp
    t = _tp.topology(geo)
    if divide_into == "individual":
        return np.arange(geo.nprims, dtype=np.int64)
    vprim = geo.vertex_prim()
    lab = np.arange(geo.nprims, dtype=np.int64)
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        a = vprim[t.edge_he[t.edge_he_off[two]]]
        b = vprim[t.edge_he[t.edge_he_off[two] + 1]]
        keep = sel[a] & sel[b]
        a, b = a[keep], b[keep]
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


def rmf_frames(pts, up=(0, 1, 0), init=None):
    """
    Compute a **rotation-minimizing frame** (parallel transport) for a sequence of points. Returns (tan, E1, E2).

    You cannot build each point's frame independently with cross(T, up) -- the normal would suddenly flip as soon as the curve turns,
    and the swept surface would twist. A rotation-minimizing frame parallel-transports the previous frame along the tangent,
    rotating only when necessary, so it is continuous along the whole curve.

    If init is given it is used as the starting E1 (projected onto the first point's normal plane), to align the cross-section's initial orientation
    with some known direction.
    """
    P = np.asarray(pts, np.float64)
    n = len(P)
    if n < 2:
        return (np.tile([0, 0, 1.0], (n, 1)),
                np.tile([1.0, 0, 0], (n, 1)),
                np.tile([0, 1.0, 0], (n, 1)))
    tan = np.gradient(P, axis=0)
    tan /= np.maximum(np.linalg.norm(tan, axis=1, keepdims=True), 1e-12)

    e1 = None
    if init is not None:
        e1 = np.asarray(init, np.float64)
        e1 = e1 - tan[0] * float(e1 @ tan[0])
        if np.linalg.norm(e1) < 1e-9:
            e1 = None
    if e1 is None:
        u = np.asarray(up, np.float64)
        if abs(float(tan[0] @ u)) > 0.999:
            u = np.array([1.0, 0.0, 0.0])
        e1 = np.cross(u, tan[0])
    e1 /= max(np.linalg.norm(e1), 1e-12)

    E1 = [e1]
    for k in range(1, n):
        v = E1[-1] - tan[k] * float(E1[-1] @ tan[k])   # project onto the current normal plane
        nv = np.linalg.norm(v)
        E1.append(v / nv if nv > 1e-9 else np.cross(np.asarray(up, np.float64),
                                                    tan[k]))
    E1 = np.stack(E1)
    E1 /= np.maximum(np.linalg.norm(E1, axis=1, keepdims=True), 1e-12)
    return tan, E1, np.cross(tan, E1)


def _spine_frames(spine, n, up=(0, 1, 0), init=None):
    """Resample the spine to n points by arc length, then compute frames."""
    P = np.asarray(spine, np.float64)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    if d[-1] <= 0:
        raise RuntimeError("Spine length is 0")
    t = np.linspace(0, d[-1], n)
    pos = np.stack([np.interp(t, d, P[:, k]) for k in range(3)], 1)
    tan, E1, E2 = rmf_frames(pos, up, init)
    return pos, tan, E1, E2


EXTRUSION_MODES = ("prim_edge_normal", "point_normal")


def polyextrude(geo, group=None, distance=1.0, inset=0.0, twist=0.0,
                divisions=1, divide_into="connected", direction=None,
                output_front=True, output_back=False, output_side=True,
                front_group="extrudeFront", back_group="extrudeBack",
                side_group="extrudeSide",
                spine=None, spine_up=(0, 1, 0),
                dist_attrib="", inset_attrib="",
                limit_inset=False, common_limit=False,
                front_translate=(0, 0, 0), front_rotate=0.0,
                front_scale=1.0, transform_front=False,
                side_uv=False, uv_style="proportional",
                add_vertex_normals=False, cusp_angle=60.0,
                front_seam_group="", back_seam_group="",
                preserve_groups=True, extrusion_mode="prim_edge_normal"):
    """
    Matches Houdini's PolyExtrude SOP.

    Region ids unify Divide Into: with connected, a connected piece shares one region (no side walls on interior edges,
    points shared); with individual each face is its own region. "Which edges get side walls" comes down to one criterion --
    the region ids on the two sides of the edge differ.

    inset uses angle-bisector miters scaled by 1/sin(half angle), so that every edge moves in by the same perpendicular distance.
    limit_inset clamps the inset **before edges flip**, preventing over-insetting from turning the face inside out.

    If spine is given, extrusion follows the spine using rotation-minimizing frames, with no twisting at turns.
    """
    from . import topology as _tp
    sel = _grp.resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()

    D = max(1, int(divisions))
    t = _tp.topology(geo)
    vprim = geo.vertex_prim()
    P = geo.get(POINT, "P")
    region = _extrude_regions(geo, sel, divide_into)

    hsel = sel[vprim]
    keys = np.stack([region[vprim[hsel]], geo.vertex_point[hsel]], 1)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    nnew = len(uniq)
    base_pt = uniq[:, 1]
    fmap = {(int(r), int(p)): i for i, (r, p) in enumerate(uniq)}

    if extrusion_mode not in EXTRUSION_MODES:
        raise ValueError(f"Extrusion Mode must be one of {EXTRUSION_MODES}, got {extrusion_mode!r}")
    fn = prim_normals(geo)
    if direction is not None:
        d = np.asarray(direction, np.float64)
        pdir = np.tile(d / max(np.linalg.norm(d), 1e-9), (nnew, 1))
    elif extrusion_mode == "point_normal":
        # Houdini's Point Normal mode: each point moves along **its own point normal** (uses the N attribute if present, otherwise computes smooth point normals,
        # with all faces taking part, not just the selected ones). The difference from the default mode is at the selection border: the default only averages normals of selected faces,
        # in this mode border points are also pulled by unselected neighbouring faces; with Individual the same point has the same direction in every face, so the extrusion does not split
        Npt = geo.get(POINT, "N")
        if Npt is None or Npt.shape[1] != 3:
            Npt = compute_normals(geo, add_to="point").get(POINT, "N")
        acc = np.asarray(Npt, np.float64)[base_pt]
        l = np.linalg.norm(acc, axis=1, keepdims=True)
        pdir = acc / np.where(l == 0, 1, l)
    else:
        acc = np.zeros((nnew, 3))
        np.add.at(acc, inv.reshape(-1), fn[vprim[hsel]])
        l = np.linalg.norm(acc, axis=1, keepdims=True)
        pdir = acc / np.where(l == 0, 1, l)

    # ---- Local Control: per-point scaling of distance / inset by attribute ----
    def _scale(name):
        if not name:
            return np.ones(nnew)
        a = geo.get(POINT, name)
        if a is not None:
            return a[base_pt, 0].astype(np.float64)
        a = geo.get(PRIM, name)
        if a is None:
            raise RuntimeError(f"Attribute '{name}' not found (not on point or prim)")
        acc = np.zeros(nnew)
        cnt = np.zeros(nnew)
        np.add.at(acc, inv.reshape(-1), a[vprim[hsel], 0].astype(np.float64))
        np.add.at(cnt, inv.reshape(-1), 1.0)
        return acc / np.maximum(cnt, 1)
    ds = _scale(dist_attrib)
    is_ = _scale(inset_attrib)

    nxt = geo.next_corner()
    twin = t.he_twin
    wall = np.array([h for h in np.nonzero(hsel)[0]
                     if twin[h] < 0 or not sel[vprim[twin[h]]]
                     or region[vprim[twin[h]]] != region[vprim[h]]], np.int64)

    # ---- inset direction: angle-bisector miter ----
    ins = np.zeros((nnew, 3))
    if len(wall):
        acc = {}
        for h in wall:
            r = int(region[vprim[h]])
            pa, pb = int(geo.vertex_point[h]), int(geo.vertex_point[nxt[h]])
            e = P[pb] - P[pa]
            e = e / max(np.linalg.norm(e), 1e-9)
            side = np.cross(fn[vprim[h]], e)
            for pt in (pa, pb):
                acc.setdefault(fmap[(r, pt)], []).append(side)
        for i, lst in acc.items():
            if len(lst) == 2:
                bis = lst[0] + lst[1]
                nb = np.linalg.norm(bis)
                if nb > 1e-9:
                    bis /= nb
                    ins[i] = bis * min(1.0 / max(float(bis @ lst[0]), 1e-3), 8.0)
            else:
                v = np.sum(lst, axis=0)
                nv = np.linalg.norm(v)
                if nv > 1e-9:
                    ins[i] = v / nv

    # ---- Limit Insetting: clamp before edges flip ----
    eff_inset = float(inset)
    if limit_inset and len(wall) and inset != 0.0:
        lim = {}
        for h in wall:
            r = int(region[vprim[h]])
            ia = fmap[(r, int(geo.vertex_point[h]))]
            ib = fmap[(r, int(geo.vertex_point[nxt[h]]))]
            # ia / ib are **new point** indices (0..nnew); the original position must be fetched through base_pt -- this was once written as
            # P[ib] - P[ia], indexing original points with new point indices: it measured two unrelated points; with a single face
            # (new point indices happen to equal original indices) it was accidentally right, with several faces the clamp was wrong, and on big meshes it went out of bounds
            e0 = P[base_pt[ib]] - P[base_pt[ia]]
            L0 = float(np.linalg.norm(e0))
            if L0 < 1e-12:
                continue
            eh = e0 / L0
            rate = float((ins[ib] * is_[ib] - ins[ia] * is_[ia]) @ eh)
            # An edge only has an upper limit when it is shrinking: when t reaches L0/(-rate) this edge collapses to a point
            if rate < -1e-12:
                lim[r] = min(lim.get(r, np.inf), L0 / -rate)
        if lim:
            if common_limit:
                cap = min(lim.values())
                eff_inset = float(np.sign(inset) *
                                  min(abs(inset), cap * 0.999))
            else:
                # Per-region limit: clamp is_ down per region
                for r, cap in lim.items():
                    if abs(inset) > cap:
                        m = uniq[:, 0] == r
                        is_[m] *= cap * 0.999 / abs(inset)

    # ---- layers ----
    layers = [P[base_pt].astype(np.float64)]
    if spine is not None and len(spine) >= 2:
        # Each region initializes its frame with its own in-plane axes and anchors the spine to its own centroid.
        local = np.zeros((nnew, 2))
        frames = {}
        anchor = {}
        for r in np.unique(uniq[:, 0]):
            m = uniq[:, 0] == r
            c = P[base_pt[m]].mean(0)
            n = pdir[m].mean(0)
            n /= max(np.linalg.norm(n), 1e-9)
            a1 = np.cross(n, [0, 0, 1.0])
            if np.linalg.norm(a1) < 1e-6:
                a1 = np.cross(n, [1.0, 0, 0])
            a1 /= np.linalg.norm(a1)
            a2 = np.cross(n, a1)
            v = P[base_pt[m]] - c
            local[m] = np.stack([v @ a1, v @ a2], 1)
            fr = _spine_frames(spine, D + 1, spine_up, init=a1)
            frames[int(r)] = fr
            anchor[int(r)] = c - fr[0][0]
        for k in range(1, D + 1):
            f = k / D
            # In spine mode inset shows up as overall scaling of the cross-section (narrowing/widening along the spine),
            # not as an in-plane miter offset -- the cross-section has already been moved onto the spine's normal plane.
            off = local * (1.0 - np.clip(eff_inset * f * is_, -0.999, 0.999))[:, None]
            q = np.empty((nnew, 3))
            for r in np.unique(uniq[:, 0]):
                m = uniq[:, 0] == r
                pos, tan, E1, E2 = frames[int(r)]
                q[m] = (pos[k] + anchor[int(r)]
                        + off[m, 0:1] * E1[k] + off[m, 1:2] * E2[k])
            layers.append(q)
    else:
        ctr = {int(r): (P[base_pt[uniq[:, 0] == r]].mean(0),
                        pdir[uniq[:, 0] == r].mean(0))
               for r in np.unique(uniq[:, 0])}
        for k in range(1, D + 1):
            f = k / D
            q = P[base_pt] + pdir * (distance * f * ds)[:, None] \
                + ins * (eff_inset * f * is_)[:, None]
            if twist != 0.0:
                ang = np.radians(twist) * f
                for r in np.unique(uniq[:, 0]):
                    m = uniq[:, 0] == r
                    c, ax = ctr[int(r)]
                    ax = ax / max(np.linalg.norm(ax), 1e-9)
                    rel = q[m] - c
                    par = (rel @ ax)[:, None] * ax
                    v = rel - par
                    q[m] = c + par + v * np.cos(ang) + np.cross(ax, v) * np.sin(ang)
            layers.append(q)

    # ---- Transform Extruded Front ----
    if transform_front:
        top = layers[-1]
        for r in np.unique(uniq[:, 0]):
            m = uniq[:, 0] == r
            c = top[m].mean(0)
            ax = pdir[m].mean(0)
            ax = ax / max(np.linalg.norm(ax), 1e-9)
            rel = (top[m] - c) * float(front_scale)
            if front_rotate:
                ang = np.radians(front_rotate)
                par = (rel @ ax)[:, None] * ax
                v = rel - par
                rel = par + v * np.cos(ang) + np.cross(ax, v) * np.sin(ang)
            top[m] = c + rel + np.asarray(front_translate, np.float64)
        layers[-1] = top

    allP = np.concatenate([P] + layers[1:])
    off = [geo.npoints + i * nnew for i in range(D)]

    def lay(k, i):
        return int(base_pt[i]) if k == 0 else int(off[k - 1] + i)

    # srcprim records which input prim each new face comes from. Preserving upstream prim groups depends on it --
    # front/back faces come from the extruded face, side walls from the face owning that edge.
    # srcvtx records which input vertex each new vertex comes from, used to carry vertex attributes (same as above).
    po = geo.prim_offset
    faces, kinds, uvs, srcprim, srcvtx = [], [], [], [], []
    if output_front:
        for i in np.nonzero(sel)[0]:
            r = int(region[i])
            faces.append([lay(D, fmap[(r, int(p))]) for p in geo.prim_points(i)])
            kinds.append(0)
            uvs.append(None)
            srcprim.append(int(i))
            srcvtx.extend(range(po[i], po[i + 1]))
    if output_back:
        for i in np.nonzero(sel)[0]:
            faces.append(list(geo.prim_points(i))[::-1])
            kinds.append(1)
            uvs.append(None)
            srcprim.append(int(i))
            srcvtx.extend(range(po[i + 1] - 1, po[i] - 1, -1))
    if output_side:
        # Side UVs: u accumulates length along the boundary, v along the extrusion direction
        acc_u = {}
        for h in wall:
            r = int(region[vprim[h]])
            a = fmap[(r, int(geo.vertex_point[h]))]
            b = fmap[(r, int(geo.vertex_point[nxt[h]]))]
            L = float(np.linalg.norm(P[base_pt[b]] - P[base_pt[a]]))
            u0 = acc_u.get(r, 0.0)
            u1 = u0 + (L if uv_style == "proportional" else 1.0)
            acc_u[r] = u1
            for k in range(D):
                faces.append([lay(k, a), lay(k, b), lay(k + 1, b), lay(k + 1, a)])
                kinds.append(2)
                srcprim.append(int(vprim[h]))
                srcvtx.extend((int(h), int(nxt[h]), int(nxt[h]), int(h)))
                uvs.append([(u0, k / D), (u1, k / D),
                            (u1, (k + 1) / D), (u0, (k + 1) / D)]
                           if side_uv else None)

    keep = ~sel
    out = Geometry()
    out._resize_points(len(allP))
    out.set(POINT, "P", allP.astype(np.float32), owned=True)
    for k, v in geo.attribs[POINT].items():
        if k == "P":
            continue
        out.set(POINT, k, np.concatenate([v] + [v[base_pt]] * D), owned=True)

    old = [list(geo.prim_points(i)) for i in np.nonzero(keep)[0]]
    allf = old + faces
    if not allf:
        return geo.copy()
    sizes2 = np.array([len(f) for f in allf], np.int32)
    out.set_topology(np.concatenate([np.asarray(f, np.int32) for f in allf]),
                     np.concatenate([[0], np.cumsum(sizes2)]).astype(np.int32),
                     np.ones(len(allf), bool))

    # prim / vertex attributes follow their source (Houdini does too): front, back and side walls all inherit the extruded face's
    # prim attributes -- per-face extrusion heights, per-building ids must still be there after extruding. Previously not a single one
    # was carried, and after one extrusion downstream had only P. vertex attributes: front / back correspond per vertex, side walls take the vertices
    # at the two ends of the edge (unchanged along the extrusion direction).
    keep_idx0 = np.nonzero(keep)[0]
    psrc = np.concatenate([keep_idx0, np.asarray(srcprim, np.int64)]) \
        if srcprim else keep_idx0
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, np.asarray(v)[psrc], owned=True)
    vsrc = np.concatenate(
        [np.arange(po[i], po[i + 1]) for i in keep_idx0]
        + [np.asarray(srcvtx, np.int64)]).astype(np.int64)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, np.asarray(v)[vsrc], owned=True)
    for k, v in geo.attribs[DETAIL].items():
        out.set(DETAIL, k, np.asarray(v).copy(), owned=True)

    kk = np.array([-1] * len(old) + kinds)
    for name, code in ((front_group, 0), (back_group, 1), (side_group, 2)):
        if name:
            out.set_group(PRIM, name, kk == code)

    # Preserve upstream groups (corresponds to Houdini's Preserve Groups, on by default).
    # Without it groups only pass down one level and are all lost in a long chain -- and the whole point of groups is to be
    # referenced repeatedly downstream. Point groups map via "new points inherit source points", primitive groups via srcprim.
    if preserve_groups:
        keep_idx = np.nonzero(keep)[0]
        allsrc = np.concatenate([keep_idx, np.asarray(srcprim, np.int64)]) \
            if srcprim else keep_idx
        # Only front and back faces inherit upstream groups; **side walls do not**.
        # Side walls are new geometry generated by the extrusion, not a continuation of the original faces; the front face is the original face
        # after being pushed out. Houdini has the same semantics -- groups used to be given to side walls too,
        # so highlighting showed the whole tube body selected, contradicting the upstream intent of "only the top face selected".
        inherit = np.concatenate([
            np.ones(len(keep_idx), bool),
            np.asarray(kinds) != 2]) if kinds else np.ones(len(keep_idx), bool)
        for k, v in geo.groups[PRIM].items():
            if k not in (front_group, back_group, side_group):
                out.set_group(PRIM, k, v[allsrc] & inherit)
        # Point groups stay only on **original points**. New layer points are created by the extrusion, not the original points;
        # the original points still exist in the output (the back face loop), so keeping groups on them is least surprising.
        for k, v in geo.groups[POINT].items():
            m = np.zeros(len(allP), bool)
            m[:geo.npoints] = v
            out.set_group(POINT, k, m)

    # Seam point group: the loop of points where side walls meet the front/back faces
    if wall.size and (front_seam_group or back_seam_group):
        idxs = sorted({fmap[(int(region[vprim[h]]), int(pt))]
                       for h in wall
                       for pt in (int(geo.vertex_point[h]),
                                  int(geo.vertex_point[nxt[h]]))})
        if front_seam_group:
            m = np.zeros(len(allP), bool)
            m[[lay(D, i) for i in idxs]] = True
            out.set_group(POINT, front_seam_group, m)
        if back_seam_group:
            m = np.zeros(len(allP), bool)
            m[[lay(0, i) for i in idxs]] = True
            out.set_group(POINT, back_seam_group, m)

    if side_uv and any(u is not None for u in uvs):
        vu = np.zeros((out.nvertices, 2), np.float32)
        base = int(sizes2[:len(old)].sum())
        pos = base
        for f, uv in zip(faces, uvs):
            if uv is not None:
                vu[pos:pos + len(f)] = np.asarray(uv, np.float32)
            pos += len(f)
        out.set(VERTEX, "uv", vu, owned=True)

    if add_vertex_normals:
        out = compute_normals(out, "vertex", cusp_angle)
    return out


def orient_faces(faces, seeds=None):
    """
    Make the winding of a set of faces consistent: each edge must be traversed in **opposite** directions by its two adjacent faces.

    Much more reliable than deriving winding case by case -- bridge faces, vertex faces and arc strips each have their own index order,
    and deriving by hand it is easy to get one class reversed, which does not raise and only shows up in shading. Here, starting from seed faces,
    a BFS over edge adjacency flips a neighbour whenever there is a direction conflict, solving all cases at once.

    Faces given in seeds keep their winding (usually the original faces are the seeds, their orientation is known to be correct).
    Returns the list of faces after flipping.
    """
    faces = [list(f) for f in faces]
    edge_of = {}
    for i, f in enumerate(faces):
        for k in range(len(f)):
            edge_of.setdefault(frozenset((f[k], f[(k + 1) % len(f)])), []).append(i)

    def directed(f):
        return {(f[k], f[(k + 1) % len(f)]) for k in range(len(f))}

    fixed = set(seeds or [0])
    stack = list(fixed)
    while stack:
        i = stack.pop()
        di = directed(faces[i])
        f = faces[i]
        for k in range(len(f)):
            key = frozenset((f[k], f[(k + 1) % len(f)]))
            for j in edge_of.get(key, ()):
                if j == i or j in fixed:
                    continue
                # If a shared edge is traversed in the same direction by two faces, one of them is reversed
                if directed(faces[j]) & di:
                    faces[j] = faces[j][::-1]
                fixed.add(j)
                stack.append(j)
    return faces


# --------------------------------------------------------------- PolyBevel
# "none" was added in pcg100 after Houdini's Shape (only pulls the faces back, no bevel faces)
BEVEL_SHAPES = ("round", "chamfer", "solid", "crease", "none")
BEVEL_SCALING = ("none", "attribute")


def polybevel(geo, group=None, distance=0.1, divisions=1, shape="round",
              output_edge_group="edgefilletpolys",
              output_point_group="pointfilletpolys",
              group_type="guess", limit_distance=True,
              ignore_flat=False, max_normal_angle=2.0,
              distance_scaling="none", scale_attribute="pscale",
              convexity=1.0, offset_group=""):
    """
    Matches Houdini's PolyBevel (edge bevel).

    Construction: **each face is inset along its beveled edges, then the gaps are bridged**.
      . face   -> the inset polygon
      . edge   -> a quad between the inset edges on both sides (an arc strip when divisions>1)
      . vertex -> an n-gon around that point

    New points must **leave the original edge and fall inside their own faces**. If the new points were placed on the original edge, the adjacent faces would share
    them and the edge would never split open -- that would just be cutting the vertex (vertex bevel), not the edge. This is the
    step of this operator that is easiest to get wrong.

    Corner positions come from **intersecting the two inset edge lines within the face**, not from walking a fixed distance along the angle bisector.
    Intersection naturally handles three cases: both edges beveled, only one beveled, neither beveled (boundary edges stay
    in place), without a separate branch for each case.

    shape (Houdini's Fillet Shape):
      round    rounded (an arc of divisions segments)
      chamfer  flat bevel, split into divisions segments
      solid    flat bevel, **one face per edge** (ignores divisions)
      crease   does not change shape, only adds an edge loop on each side of every beveled edge: the edge itself stays in place as a crease,
               faces on both sides pull back by distance, and two narrow strips reconnect to the edge. Used as support edges for later subdivision --
               volume and silhouette are the same as before. No caps are needed at vertices (the narrow strips already connect to the original vertices)
      none     only pulls the faces back, no bevel faces (gaps remain at edges and vertices)

    pcg100 additions to match Houdini (with defaults every step's formula is as before, results are bit-identical):
      ignore_flat / max_normal_angle  edges whose two face normals are at an angle below this are not beveled
      distance_scaling = attribute    each point's bevel distance = distance x point attribute scale_attribute
                                      (when the two ends of an edge have different distances, the inset line is no longer parallel to the original edge)
      convexity   how much Round bulges: 1 = circular arc (previous behaviour), 0 = flat, -1 = arc curving inward.
                  The docs only give these three points; in between it interpolates linearly between chord and arc; when not 1, no sphere patch is laid at vertices
                  (sphere patches only hold for circular arcs), an n-gon cap is used instead
      offset_group  non-empty: write the edges between the bevel faces and the pulled-back faces as an edge group with this name
    """
    from . import topology as _tp
    if shape not in BEVEL_SHAPES:
        raise ValueError(f"Shape must be one of {BEVEL_SHAPES}, got {shape!r}")
    if distance_scaling not in BEVEL_SCALING:
        raise ValueError(f"Distance Scaling must be one of {BEVEL_SCALING}")
    convexity = float(np.clip(convexity, -1.0, 1.0))
    # group_type decides how group is interpreted, matching Houdini's Group Type.
    #   edges  an edge group directly -- exactly which edges, the most natural way to select for a bevel
    #   prims  select faces, bevel the edges inside that region
    #   points select points, bevel edges whose two ends are both selected
    #   guess  if the name is found among edge groups treat it as an edge group, otherwise as a primitive group
    t = _tp.topology(geo)
    gt = group_type
    if gt == "guess":
        named = [n for n in str(group or "").split() if n in geo.edge_groups]
        gt = "edges" if named else "prims"

    if gt == "edges":
        pairs = _grp.resolve_edges(geo, group)
        bev_edge0 = _grp.edge_mask(geo, pairs)
        sel = np.ones(geo.nprims, bool)
    elif gt == "points":
        pm = _grp.resolve(geo, POINT, group)
        bev_edge0 = _grp.edge_mask(geo, _grp.points_to_edges(geo, pm))
        sel = np.ones(geo.nprims, bool)
    else:
        sel = _grp.resolve(geo, PRIM, group)
        bev_edge0 = None

    if geo.nprims == 0 or not sel.any() or distance <= 0:
        return geo.copy()
    notflat = None
    if ignore_flat:
        notflat = _tp.edge_angles(geo) >= float(max_normal_angle)
        if bev_edge0 is not None:
            bev_edge0 = bev_edge0 & notflat
    distance0 = distance
    cap = np.inf

    # Distance limit. When the bevel amount exceeds half of an adjacent edge's length, the inset points at both ends cross each other, the face turns inside out,
    # and the result self-intersects -- that is the problem Houdini's Collisions and Limits section solves.
    # Only the most basic rule is done here: clamp to "half the shortest adjacent edge at any endpoint of a beveled edge".
    # It stops the vast majority of collapses, but not global collisions like "two distant bevel faces intersecting each other".
    if limit_distance:
        t0 = _tp.topology(geo)
        L = _tp.edge_lengths(geo)
        for e in np.nonzero(bev_edge0 if bev_edge0 is not None
                            else np.ones(t0.nedges, bool))[0]:
            for pt in t0.edge_points[e]:
                inc = t0.edges_of_point(int(pt))
                if len(inc):
                    cap = min(cap, float(L[inc].min()) * 0.5)
        if np.isfinite(cap):
            distance = min(distance, cap * 0.999)
    # Each point's own distance (Scale by Attribute); None = distance everywhere
    dpt = None
    if distance_scaling == "attribute":
        nm = str(scale_attribute).strip()
        sa = geo.get(POINT, nm) if nm else None
        if sa is None or is_string(sa):
            raise KeyError(f"Distance Scaling: no numeric point attribute '{nm}'")
        dpt = np.maximum(float(distance0) * np.asarray(sa, np.float64)[:, 0], 0.0)
        if np.isfinite(cap):
            dpt = np.minimum(dpt, cap * 0.999)

    def dist_at(p):
        return distance if dpt is None else float(dpt[p])
    vprim = geo.vertex_prim()
    nxt = geo.next_corner()
    P = geo.get(POINT, "P").astype(np.float64)
    fn = prim_normals(geo)
    sizes = geo.prim_sizes()
    D = max(1, int(divisions))
    if shape in ("solid", "none"):
        D = 1
    if shape == "crease":
        D = 2                              # two narrow strips: face -> edge -> face
    # round corners must be fully quad-tiled, each arc must split in half, so divisions is made even.
    # With an odd number the center can only be patched by "dropping points ring by ring", the paired points rotate ring after ring, and pinwheel-like
    # triangle strips appear at corners -- ugly topology, even more visible after subdivision.
    if shape == "round" and D > 1 and D % 2:
        D += 1

    # Beveled edges. Whatever group_type they come from, in the end they must be manifold interior edges --
    # an edge with only one face has no "two sides" and cannot be beveled.
    he_edge = t.he_edge
    manifold = t.edge_count == 2
    if bev_edge0 is not None:
        bev_edge = bev_edge0 & manifold
    else:
        bev_edge = np.zeros(t.nedges, bool)
        for e in np.nonzero(manifold)[0]:
            hs = t.edge_he[t.edge_he_off[e]:t.edge_he_off[e] + 2]
            if sel[vprim[hs[0]]] and sel[vprim[hs[1]]]:
                bev_edge[e] = True
        if notflat is not None:
            bev_edge &= notflat
    # Affected faces = **faces touching any endpoint of a beveled edge**, not just the two on either side.
    # If only the two side faces were re-emitted, faces along the top edge would still use the original points while the side face's corner has already slid along the shared edge,
    # and it would split along that edge. Every face that may be dragged along must be re-emitted through cid(); for corners that did not move at all
    # cid() returns the original point unchanged, so no extra points are introduced.
    if bev_edge.any():
        touched = np.zeros(geo.npoints, bool)
        touched[t.edge_points[bev_edge].reshape(-1)] = True
        sel = np.zeros(geo.nprims, bool)
        sel[vprim[touched[geo.vertex_point]]] = True
    if not bev_edge.any():
        return geo.copy()

    # Compute a candidate point for each corner (intersection of the two inset edge lines within the face)
    # Candidate point of every corner (vectorized over corners; it used to be a Python loop per corner, ~60% of the
    # node's time). Same arithmetic as before: the two inset edge lines of the face, intersected by a 2x2 solve.
    cand = {}                                  # corner -> candidate position
    H = np.nonzero(np.asarray(sel)[np.asarray(vprim)])[0]
    if len(H):
        po = np.asarray(geo.prim_offset)[vprim[H]].astype(np.int64)
        pn = np.asarray(sizes)[vprim[H]].astype(np.int64)
        HP = po + (H - po - 1) % pn
        a_ = np.asarray(geo.vertex_point)[H].astype(np.int64)
        b_ = np.asarray(geo.vertex_point)[np.asarray(nxt)[H]].astype(np.int64)
        c_ = np.asarray(geo.vertex_point)[HP].astype(np.int64)
        nrm = np.asarray(fn)[vprim[H]]
        eo = np.asarray(he_edge)[H]
        ei = np.asarray(he_edge)[HP]
        bo = (eo >= 0) & np.asarray(bev_edge)[np.maximum(eo, 0)]
        bi = (ei >= 0) & np.asarray(bev_edge)[np.maximum(ei, 0)]
        dist_v = (np.full(geo.npoints, float(distance)) if dpt is None else np.asarray(dpt, np.float64))

        def offset_lines(p0i, p1i, beveled):
            p0, p1 = P[p0i], P[p1i]
            d = p1 - p0
            L = np.linalg.norm(d, axis=1)
            deg = L < 1e-12
            d = d / np.where(deg, 1.0, L)[:, None]
            perp = np.cross(nrm, d)
            org = np.where(beveled[:, None], p0 + perp * dist_v[p0i][:, None], p0)
            if dpt is not None:
                var = beveled & (dpt[p0i] != dpt[p1i])
                if var.any():
                    q0 = p0 + perp * dpt[p0i][:, None]
                    q1 = p1 + perp * dpt[p1i][:, None]
                    dd = q1 - q0
                    dd = dd / np.maximum(np.linalg.norm(dd, axis=1), 1e-300)[:, None]
                    org = np.where(var[:, None], q0, org)
                    d = np.where(var[:, None], dd, d)
            org = np.where(deg[:, None], p0, org)
            d = np.where(deg[:, None], np.array([1.0, 0, 0]), d)
            return org, d

        o1, d1 = offset_lines(a_, b_, bo)
        o2, d2 = offset_lines(c_, a_, bi)
        e1 = d2
        e2 = np.cross(nrm, e1)
        dot = lambda x, y: (x * y).sum(1)          # noqa: E731  (same summation order as the 1-D @ before)
        A = np.stack([np.stack([dot(d1, e1), -dot(d2, e1)], 1), np.stack([dot(d1, e2), -dot(d2, e2)], 1)], 1)
        rhs = np.stack([dot(o2 - o1, e1), dot(o2 - o1, e2)], 1)
        try:
            st = np.linalg.solve(A, rhs[:, :, None])[:, :, 0]
            pos = o1 + d1 * st[:, :1]
        except np.linalg.LinAlgError:          # a singular corner somewhere: solve one by one like before
            pos = np.empty_like(o1)
            for k in range(len(H)):
                try:
                    pos[k] = o1[k] + d1[k] * np.linalg.solve(A[k], rhs[k])[0]
                except np.linalg.LinAlgError:
                    pos[k] = (o1[k] + o2[k]) * 0.5
        cand = dict(zip(H.tolist(), pos))

    def prev_corner(h):
        pi = int(vprim[h])
        o, n = int(geo.prim_offset[pi]), int(sizes[pi])
        return o + (h - o - 1) % n

    # Decide which point each corner uses. This step is the key to whether a partial bevel is watertight:
    #   both edges beveled -> this corner is a true inset corner, one point per face
    #   only one beveled   -> the point slides along **the edge that is not beveled** and must be **shared** by the faces on both sides of that edge,
    #                         otherwise it splits along that edge (same position but different point numbers)
    #   neither beveled    -> use the original point as is
    # When shared, take the candidate with the largest slide distance so both sides agree. Houdini exposes this step as
    # Slide on Ring Edges / Asymmetry Tolerance; for now the maximum is taken.
    corner_pt = np.full(geo.nvertices, -1, np.int64)
    newP = []
    newP_src = []                              # which original point each new point comes from (attributes copied)
    shared = {}                                # (point, edge) -> new point number
    slide_best = {}
    for h in cand:
        hp = prev_corner(h)
        a_ = int(geo.vertex_point[h])
        e_out = int(he_edge[h]) if he_edge[h] >= 0 else -1
        e_in = int(he_edge[hp]) if he_edge[hp] >= 0 else -1
        bo = e_out >= 0 and bev_edge[e_out]
        bi = e_in >= 0 and bev_edge[e_in]
        if bo and bi:
            continue
        if not bo and not bi:
            continue
        key = (a_, e_in if bo else e_out)
        d = float(np.linalg.norm(cand[h] - P[a_]))
        if d > slide_best.get(key, (-1, None))[0]:
            slide_best[key] = (d, cand[h])

    for key, (_, pos) in slide_best.items():
        shared[key] = len(newP)
        newP.append(pos)
        newP_src.append(key[0])

    for h in cand:
        hp = prev_corner(h)
        a_ = int(geo.vertex_point[h])
        e_out = int(he_edge[h]) if he_edge[h] >= 0 else -1
        e_in = int(he_edge[hp]) if he_edge[hp] >= 0 else -1
        bo = e_out >= 0 and bev_edge[e_out]
        bi = e_in >= 0 and bev_edge[e_in]
        if bo and bi:
            corner_pt[h] = len(newP)
            newP.append(cand[h])
            newP_src.append(a_)
        elif bo or bi:
            corner_pt[h] = shared[(a_, e_in if bo else e_out)]
        else:
            corner_pt[h] = -1                  # use the original point

    newP = np.asarray(newP, np.float64) if newP else np.zeros((0, 3))
    base = geo.npoints
    extra = []
    extra_src = []                             # points on arcs / sphere patches: source points
    face_src = []                              # which original prim each new face comes from

    def cid(h):
        """Final point number of a corner: -1 means keep the original point."""
        c = int(corner_pt[h])
        return int(geo.vertex_point[h]) if c < 0 else base + c

    faces, kinds = [], []

    # ---- faces: the inset polygons ----
    # When walking each edge, the **slide points** on that edge must be inserted into the vertex sequence. A slide point is where a beveled edge pushed the adjacent corner
    # along an unbeveled edge, landing in the middle of that edge; if only the side that slid counted it as a
    # vertex, the face on the other side would still have one whole edge, so the same edge would be two segments on one side and one on the other --
    # non-manifold. The order along the edge is a -> slide point (a side) -> slide point (b side) -> b.
    for pi in np.nonzero(sel)[0]:
        o, n = int(geo.prim_offset[pi]), int(sizes[pi])
        poly = []
        for k in range(n):
            h = o + k
            hn = o + (k + 1) % n
            poly.append(cid(h))
            e = int(he_edge[h]) if he_edge[h] >= 0 else -1
            if e < 0 or bev_edge[e]:
                continue
            a_, b_ = int(geo.vertex_point[h]), int(geo.vertex_point[hn])
            for pt, tgt in ((a_, cid(h)), (b_, cid(hn))):
                sp = shared.get((pt, e))
                if sp is not None and base + sp != tgt and base + sp not in poly[-1:]:
                    poly.append(base + sp)
        faces.append(poly)
        kinds.append(0)
        face_src.append(int(pi))

    # ---- edges: bridge strips between the two sides ----
    def fillet_axis(pa, n1, n2, dist):
        """
        Fillet axis: the point at distance distance from both faces.

        The original vertex cannot be used as the center -- the arc would then bulge **outward**, sticking out past the original edge, and the bevel
        would add material instead. Let v = pa - c with c at distance d from both faces; by symmetry v lies along
        (n1+n2), giving v = d*(n1+n2)/(1+n1.n2); for a 90 deg edge this reduces to pulling back d along each face.
        """
        dot = float(np.clip(n1 @ n2, -0.999, 1.0))
        return pa - dist * (n1 + n2) / (1.0 + dot)

    def arc(p0, p1, pa, n1, n2, edir, k, dist):
        """Take D+1 points between p0 and p1. round follows an arc, chamfer a straight line."""
        f = k / D
        if shape != "round" or D == 1:
            return p0 * (1 - f) + p1 * f
        # The fillet axis is **a line along the edge**, not a point. It must be projected along the edge direction onto the plane of the arc,
        # otherwise slerp sweeps diagonally in 3D and the middle points drift off that end face as a whole.
        # The arc must be tangent to both faces at p0 and p1: centre c = p0 - r n1 = p1 - r n2. The inset points sit at the
        # bevel distance from the edge *within each face*, which only equals the fillet radius on a 90 deg edge; on any
        # other dihedral a centre at distance `dist` from both faces leaves p0 / p1 off its circle, and the slerp between
        # them then bulges past the faces (on a 135 deg edge with distance 5 cm the rounded top rose 2.5 mm above the
        # original top face). r comes from the two tangent conditions, measured across the edge.
        dn = n1 - n2
        dp = (p0 - p1) - edir * float((p0 - p1) @ edir)
        dd = float(dn @ dn)
        r = float(dp @ dn) / dd if dd > 1e-12 else -1.0
        if r > 1e-9:
            c = 0.5 * ((p0 - r * n1) + (p1 - r * n2))
        else:
            c = fillet_axis(pa, n1, n2, dist)
        c = c + edir * float((p0 - c) @ edir)
        v0, v1 = p0 - c, p1 - c
        r0, r1 = np.linalg.norm(v0), np.linalg.norm(v1)
        if r0 < 1e-12 or r1 < 1e-12:
            return p0 * (1 - f) + p1 * f
        u0, u1 = v0 / r0, v1 / r1
        ang = np.arccos(np.clip(u0 @ u1, -1, 1))
        if ang < 1e-6:
            return p0 * (1 - f) + p1 * f
        w = (np.sin((1 - f) * ang) * u0 + np.sin(f * ang) * u1) / np.sin(ang)
        on_arc = c + w * (r0 * (1 - f) + r1 * f)
        if convexity == 1.0:
            return on_arc
        chord = p0 * (1 - f) + p1 * f           # Convexity: between chord (0) and arc (1); negative flips inward
        return chord + convexity * (on_arc - chord)

    def allpos(h):
        c = int(corner_pt[h])
        return P[int(geo.vertex_point[h])] if c < 0 else newP[c]

    def allP_at(pid):
        """Fetch the position by final point number (original point / inset point / new point on an arc)."""
        if pid < base:
            return P[pid]
        i = pid - base
        return newP[i] if i < len(newP) else extra[i - len(newP)]

    edge_ring = {}       # (edge, endpoint) -> column of point numbers at that endpoint from the F side to the G side
    for e in np.nonzero(bev_edge)[0]:
        if shape == "none":
            break                              # no bevel faces: no bridge strips on edges
        h, g = t.edge_he[t.edge_he_off[e]], t.edge_he[t.edge_he_off[e] + 1]
        a, b = int(t.edge_points[e][0]), int(t.edge_points[e][1])
        # h does not necessarily start at a; take the corner corresponding to each endpoint
        def corner_at(hh, pt):
            return hh if int(geo.vertex_point[hh]) == pt else nxt[hh]
        ha, hb = corner_at(h, a), corner_at(h, b)
        ga, gb = corner_at(g, a), corner_at(g, b)

        ringA, ringB = [], []
        for k in range(D + 1):
            if k == 0:
                ringA.append(cid(ha))
                ringB.append(cid(hb))
            elif k == D:
                ringA.append(cid(ga))
                ringB.append(cid(gb))
            elif shape == "crease":            # the middle column is the original edge (the original two endpoints, no added points)
                ringA.append(a)
                ringB.append(b)
            else:
                n1, n2 = fn[vprim[h]], fn[vprim[g]]
                edir = P[b] - P[a]
                edir = edir / max(np.linalg.norm(edir), 1e-12)
                ringA.append(base + len(newP) + len(extra))
                extra.append(arc(allpos(ha), allpos(ga), P[a], n1, n2, edir, k, dist_at(a)))
                extra_src.append(a)
                ringB.append(base + len(newP) + len(extra))
                extra.append(arc(allpos(hb), allpos(gb), P[b], n1, n2, edir, k, dist_at(b)))
                extra_src.append(b)
        edge_ring[(int(e), a)] = ringA
        edge_ring[(int(e), b)] = ringB
        for k in range(D):
            faces.append([ringA[k], ringB[k], ringB[k + 1], ringA[k + 1]])
            kinds.append(1)
            face_src.append(int(vprim[h]))

    # ---- vertices: the cap around each point ----
    # A cap is needed as soon as the point touches **one** beveled edge. It used to require >=3, so with "bevel only the vertical edges"
    # each vertex had only 1 beveled edge, no cap was generated, and there was a hole there.
    # While walking around, unbeveled edges can be crossed (no arc points added, go straight to the next face).
    # corners of each point on selected faces, ascending -- one stable sort instead of scanning every corner per point
    # (that scan was O(points x corners): 87% of the node's time on a 3k-face sphere)
    _vp_all = np.asarray(geo.vertex_point)
    _ord = np.argsort(_vp_all, kind="stable")
    _ord = _ord[np.asarray(sel)[np.asarray(vprim)[_ord]]]
    _starts = np.searchsorted(_vp_all[_ord], np.arange(geo.npoints + 1))
    for a in range(geo.npoints):
        inc = [e for e in t.edges_of_point(a) if bev_edge[e]]
        if not inc or shape in ("crease", "none"):
            continue
        out_he = _ord[_starts[a]:_starts[a + 1]].tolist()
        if not out_he:
            continue
        ring, arcs_ids, h0 = [], [], out_he[0]
        h, guard, ok = h0, 0, True
        while guard <= len(out_he) + 1:
            guard += 1
            ring.append(cid(h))
            e = int(he_edge[h])
            tw = int(t.he_twin[h])
            if e < 0 or tw < 0:
                ok = False                      # open boundary, cannot walk all the way round
                break
            if bev_edge[e]:
                col = list(edge_ring[(e, a)])
                if col[0] != cid(h):
                    col = col[::-1]
                arcs_ids.append(col)           # a complete arc: F -> ... -> F'
                ring.extend(col[1:-1])
            h = int(nxt[tw])
            if int(geo.vertex_point[h]) != a:
                ok = False
                break
            if h == h0:
                break
        if not ok:
            continue
        # When crossing an unbeveled edge, the two adjacent faces share the same point, which repeats consecutively; remove it
        dedup = [ring[i] for i in range(len(ring))
                 if ring[i] != ring[(i - 1) % len(ring)]]
        if len(dedup) < 3:
            continue

        # With round + multiple divisions, the vertex must become a **sphere patch** rather than a flat n-gon.
        # A flat n-gon collapses into a cone at the corner -- edges are round, the corner is sharp, normals jump at the seam.
        # The sphere center is the point at distance distance from all adjacent faces (least-squares solution); the boundary loop must be
        # gathered toward the pole along the sphere over several rings to meet the rounded edges.
        nb_faces = [int(vprim[h]) for h in out_he]
        cen = None
        da = dist_at(a)
        if shape == "round" and D > 1 and len(nb_faces) >= 3 and convexity == 1.0:
            A = np.stack([fn[f] for f in nb_faces])
            rhs = A @ P[a] - da
            try:
                cen, *_ = np.linalg.lstsq(A, rhs, rcond=None)
                if not np.all(np.isfinite(cen)):
                    cen = None
            except np.linalg.LinAlgError:
                cen = None

        if cen is None:
            faces.append(dedup)
            kinds.append(2)
            face_src.append(nb_faces[0])
            continue

        def onsphere(v):
            n = np.linalg.norm(v)
            return v / n if n > 1e-12 else v

        # Corner sphere patch: **k sectors, each sector one all-quad grid**.
        # Sector boundaries run from the center to each arc's midpoint; the four corners are arc i midpoint / face corner point / arc i+1 midpoint
        # / center. Interior points blend the four boundary curves with Coons patches and are projected back onto the sphere.
        #
        # Concentric rings + dropping points ring by ring makes the paired points rotate ring after ring, producing pinwheel triangle strips at corners.
        # The sector grid does not have this problem, and connects naturally to the quad strips on the edges.
        if D == 1 or len(arcs_ids) < 3:
            faces.append(dedup)
            kinds.append(2)
            face_src.append(nb_faces[0])
            continue

        n_half = D // 2
        pole_dir = onsphere(P[a] - cen)
        center = base + len(newP) + len(extra)
        extra.append(cen + pole_dir * da)
        extra_src.append(a)

        def sph(v, f, u):
            """Rotate from direction v toward direction u by f, landing on the sphere."""
            v, u = onsphere(v), onsphere(u)
            ang = np.arccos(np.clip(v @ u, -1, 1))
            if ang < 1e-7:
                return cen + v * da
            w = (np.sin((1 - f) * ang) * v + np.sin(f * ang) * u) / np.sin(ang)
            return cen + w * da

        K = len(arcs_ids)
        mids = [arcs_ids[i][n_half] for i in range(K)]
        # Radial curves midpoint -> center, shared by adjacent sectors
        radial = []
        for i in range(K):
            v = allP_at(mids[i]) - cen
            col = [mids[i]]
            for j in range(1, n_half):
                col.append(base + len(newP) + len(extra))
                extra.append(sph(v, j / n_half, pole_dir))
                extra_src.append(a)
            col.append(center)
            radial.append(col)

        for i in range(K):
            j = (i + 1) % K
            bottom = arcs_ids[i][n_half:]          # second half of arc i: M_i -> F
            right = arcs_ids[j][:n_half + 1]       # first half of arc j: F -> M_j
            left = radial[i]                       # M_i -> C
            top = radial[j]                        # M_j -> C
            grid = [[None] * (n_half + 1) for _ in range(n_half + 1)]
            for u in range(n_half + 1):
                grid[u][0] = bottom[u]
            for v in range(n_half + 1):
                grid[n_half][v] = right[v] if v < len(right) else top[0]
            for v in range(n_half + 1):
                grid[0][v] = left[v]
            for u in range(n_half + 1):
                grid[u][n_half] = top[n_half - u] if u else left[n_half]
            for u in range(1, n_half):
                for v in range(1, n_half):
                    uu, vv = u / n_half, v / n_half
                    B, T = allP_at(grid[u][0]), allP_at(grid[u][n_half])
                    L, R = allP_at(grid[0][v]), allP_at(grid[n_half][v])
                    c00, c10 = allP_at(grid[0][0]), allP_at(grid[n_half][0])
                    c01, c11 = allP_at(grid[0][n_half]), allP_at(grid[n_half][n_half])
                    q = ((1 - vv) * B + vv * T + (1 - uu) * L + uu * R
                         - ((1 - uu) * (1 - vv) * c00 + uu * (1 - vv) * c10
                            + (1 - uu) * vv * c01 + uu * vv * c11))
                    grid[u][v] = base + len(newP) + len(extra)
                    extra.append(cen + onsphere(q - cen) * da)
                    extra_src.append(a)
            for u in range(n_half):
                for v in range(n_half):
                    quad = [grid[u][v], grid[u + 1][v],
                            grid[u + 1][v + 1], grid[u][v + 1]]
                    quad = [x for t_, x in enumerate(quad) if x != quad[t_ - 1]]
                    if len(quad) >= 3:
                        faces.append(quad)
                        kinds.append(2)
                        face_src.append(nb_faces[0])

    allP = np.concatenate([P, newP] + ([np.asarray(extra)] if extra else []))
    out = Geometry()
    out._resize_points(len(allP))
    out.set(POINT, "P", allP.astype(np.float32), owned=True)
    old = [list(geo.prim_points(i)) for i in np.nonzero(~sel)[0]]
    # Use "the inset faces" as seeds: they inherit the original faces' winding directly, orientation known to be correct
    seeds = list(range(len(old), len(old) + int((np.asarray(kinds) == 0).sum()))) \
        if kinds else [0]
    allf = orient_faces(old + faces, seeds)
    sz = np.array([len(f) for f in allf], np.int32)
    out.set_topology(np.concatenate([np.asarray(f, np.int32) for f in allf]),
                     np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                     np.ones(len(allf), bool))
    kk = np.array([-1] * len(old) + kinds)
    # Attributes and groups (pcg102): points from source points, prims from source prims, vertices from "the corner of the source prim at the same source point".
    # Previously only P was output; uv / Cd / name / groups were all lost
    pt_src = np.concatenate([np.arange(geo.npoints), np.asarray(newP_src, np.int64),
                             np.asarray(extra_src, np.int64)]).astype(np.int64)
    pr_src = np.concatenate([np.nonzero(~sel)[0], np.asarray(face_src, np.int64)]
                            ).astype(np.int64)
    assert len(pt_src) == out.npoints and len(pr_src) == out.nprims
    carry_attribs(geo, out, pt_src, pr_src, vertex_sources(geo, out, pr_src, pt_src))
    if output_edge_group:
        out.set_group(PRIM, output_edge_group, kk == 1)
    if output_point_group:
        out.set_group(PRIM, output_point_group, kk == 2)
    og = str(offset_group or "").strip()
    if og:
        # Offset Group: edges shared by the pulled-back faces (kind 0) and bevel faces (kind 1 / 2)
        def edge_set(want):
            es = set()
            for f, k_ in zip(allf, kk):
                if k_ in want:
                    es.update((min(f[i], f[i - 1]), max(f[i], f[i - 1])) for i in range(len(f)))
            return es
        out.set_edge_group(og, np.array(sorted(edge_set((0,)) & edge_set((1, 2))),
                                        np.int32).reshape(-1, 2))
    # After beveling, all original points are replaced by inset points; keeping them would leave orphan points
    used = np.zeros(out.npoints, bool)
    used[out.vertex_point] = True
    return out if used.all() else delete_points(out, used)


# ------------------------------------------------------------------ Carve
def _poly_param(P, relative_arc):
    """Polyline parameterization. relative_arc=True uses arc length, otherwise vertex index evenly."""
    n = len(P)
    if n < 2:
        return np.zeros(n)
    if not relative_arc:
        return np.linspace(0.0, 1.0, n)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return d / d[-1] if d[-1] > 0 else np.linspace(0.0, 1.0, n)


def _poly_slice(P, t, u0, u1):
    """Clip a polyline by a parameter interval, adding exact end points at both ends by linear interpolation."""
    if u1 <= u0:
        return np.zeros((0, 3), np.float32)
    keep = (t > u0) & (t < u1)
    pts = [_lerp_at(P, t, u0)]
    if keep.any():
        pts.append(P[keep])
    pts.append(_lerp_at(P, t, u1))
    return np.concatenate([np.atleast_2d(x) for x in pts]).astype(np.float32)


def _lerp_at(P, t, u):
    i = int(np.clip(np.searchsorted(t, u) - 1, 0, len(t) - 2))
    span = t[i + 1] - t[i]
    a = 0.0 if span <= 0 else (u - t[i]) / span
    return P[i] * (1 - a) + P[i + 1] * a


def carve(geo, group=None, u0=0.25, u1=0.75, use_u0=True, use_u1=False,
          v0=0.25, v1=0.75, use_v0=False, use_v1=False,
          relative_arc=False, mode="cut", keep_inside=True, keep_outside=False,
          u_divs=2, v_divs=2):
    """
    Matches Houdini's Carve SOP: cut/extract curves and surfaces at parametric positions.

    mode="cut"      cut at u0/u1 and keep segments according to keep_inside / keep_outside
    mode="extract"  take isoparms: a curve yields a point, a surface yields an isoparm curve

    Interval = [u0 or 0, u1 or 1]: whichever is not enabled, that end is the curve's end point. So with only u0 enabled
    inside = [u0, 1], with only u1 enabled inside = [0, u1] (before pcg90, enabling only u1 was treated as
    [0, 1] and u1 was ignored). extract takes one at each enabled position (two if both are on).

    NURBS / Bezier are cut by **knot insertion**; after cutting they are still curves of the same type and do not degrade into polylines.
    Polygons and polylines are cut by linear interpolation of vertex parameters, with end points landing exactly at the parameter positions.
    """
    from . import nurbs as _nb
    sel = _grp.resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()

    P = geo.get(POINT, "P")
    parts = [delete_prims(geo, ~sel)] if (~sel).any() else []
    lo = float(u0) if use_u0 else 0.0
    hi = float(u1) if use_u1 else 1.0
    lo, hi = min(lo, hi), max(lo, hi)
    at = sorted(float(u) for u, on in ((u0, use_u0), (u1, use_u1)) if on)

    for i in np.nonzero(sel)[0]:
        idx = geo.prim_points(i)
        t = int(geo.prim_type[i])
        pts = P[idx]
        # Each cut segment inherits the source face's groups. merge unions the groups of the segments,
        # so marking them directly on the segments is enough.
        src_groups = {k: bool(v[i]) for k, v in geo.groups[PRIM].items()}

        def tag(gg):
            for k, on in src_groups.items():
                gg.set_group(PRIM, k, np.full(gg.nprims, on, bool))
            return gg

        if t in (PRIM_NURBS_CURVE, PRIM_BEZIER_CURVE):
            uo = int(geo.get(PRIM, "uorder")[i, 0]) if geo.get(PRIM, "uorder") is not None else 4
            bs = "bezier" if t == PRIM_BEZIER_CURVE else "nurbs"
            kv = geo.pdata(i, "knots_u")
            if kv is None:
                kv = _nb.knots_for(bs, len(pts), uo)
            a, b = lo, hi
            if relative_arc:
                a, b = _nb.arclen_to_param(pts, uo, kv, [lo, hi], kind=bs)
            if mode == "extract":                       # neither is on: at is empty, no points output
                us = (_nb.arclen_to_param(pts, uo, kv, at, kind=bs)
                      if relative_arc else at)
                parts.append(Geometry.from_points(
                    _nb.eval_curve(pts, uo, np.asarray(us, np.float64), None, bs, kv)))
                continue
            segs = []
            if keep_inside:
                segs.append(_nb.subcurve(pts, kv, uo, a, b))
            if keep_outside:
                if a > 1e-9:
                    segs.append(_nb.subcurve(pts, kv, uo, 0.0, a))
                if b < 1 - 1e-9:
                    segs.append(_nb.subcurve(pts, kv, uo, b, 1.0))
            for c, k in segs:
                if len(c) < 2:
                    continue
                g = Geometry.from_mesh(c.astype(np.float32),
                                       [np.arange(len(c), dtype=np.int32)],
                                       closed=False)
                g.set_topology(g.vertex_point, g.prim_offset, g.prim_closed,
                               np.array([t], np.uint8))
                g.set(PRIM, "uorder", np.array([[uo]], np.int32), owned=True)
                g.set_pdata(0, "knots_u", k)
                parts.append(tag(g))
            continue

        # ---- polygons / polylines ----
        if geo.prim_closed[i] and len(pts) >= 3:
            pts = np.concatenate([pts, pts[:1]])
        if len(pts) < 2:
            continue
        tp = _poly_param(pts, relative_arc)
        if mode == "extract":
            parts.append(Geometry.from_points(np.array(
                [_lerp_at(pts, tp, u) for u in at], np.float32).reshape(-1, 3)))
            continue
        segs = []
        if keep_inside:
            segs.append(_poly_slice(pts, tp, lo, hi))
        if keep_outside:
            if lo > 1e-9:
                segs.append(_poly_slice(pts, tp, 0.0, lo))
            if hi < 1 - 1e-9:
                segs.append(_poly_slice(pts, tp, hi, 1.0))
        for q in segs:
            if len(q) >= 2:
                parts.append(tag(Geometry.from_mesh(
                    q, [np.arange(len(q), dtype=np.int32)], closed=False)))

    return merge(*parts) if parts else Geometry()


# ---------------------------------------------------------------- fuse
def fuse(geo, distance=1e-4):
    """Deduplicate points by distance quantization (snap mode of Houdini's Fuse SOP)."""
    P = geo.get(POINT, "P")
    if distance <= 0 or geo.npoints == 0:
        return geo.copy()
    q = np.round(P / distance).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first)
    remap = np.empty(len(first), np.int32)
    remap[order] = np.arange(len(first), dtype=np.int32)
    new_idx = remap[inv]

    out = Geometry()
    out._resize_points(len(first))
    keep = first[order]
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[keep], owned=True)
    out.set_topology(new_idx[geo.vertex_point], geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    for cls in (VERTEX, PRIM):
        for k, v in geo.attribs[cls].items():
            out.set(cls, k, v, owned=True)
    # Point groups: if any of the points fused together is in the group, the merged point is in the group.
    # Taking the representative point's value is wrong -- the representative is picked by unique's return order, unrelated to groups.
    for k, v in geo.groups[POINT].items():
        m = np.zeros(len(first), bool)
        np.logical_or.at(m, new_idx, v)
        out.set_group(POINT, k, m)
    for cls in (VERTEX, PRIM):                      # the order of these two classes did not change
        for k, v in geo.groups[cls].items():
            out.set_group(cls, k, v)
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    # After fusing, the two endpoints may become the same point and the edge no longer exists -- remap would dedupe it into
    # a self-loop; filter it out explicitly here
    eg = geo.remap_edge_groups(new_idx.astype(np.int32), out.npoints)
    for k, v in eg.items():
        out.set_edge_group(k, v[v[:, 0] != v[:, 1]] if len(v) else v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out


# ------------------------------------------------------------ attribute promote
def promote(geo, name, src_cls, dst_cls, method="mean"):
    """Move attributes between point <-> prim <-> vertex, corresponds to the Attribute Promote SOP."""
    g = geo.copy()
    a = geo.get(src_cls, name)
    if a is None:
        return g
    vprim = geo.vertex_prim()
    vpt = geo.vertex_point

    if is_string(a):
        # Strings cannot be reduced. Expanding directions work as usual; reducing directions take the first value in each group.
        if src_cls == POINT and dst_cls == VERTEX:
            g.set(dst_cls, name, a[vpt], owned=True)
        elif src_cls == PRIM and dst_cls == VERTEX:
            g.set(dst_cls, name, a[vprim], owned=True)
        elif src_cls == VERTEX and dst_cls == POINT:
            first = np.zeros(geo.npoints, np.int32)
            first[vpt[::-1]] = np.arange(len(vpt), dtype=np.int32)[::-1]
            g.set(dst_cls, name, a[first], owned=True)
        elif src_cls == POINT and dst_cls == PRIM:
            starts = geo.prim_offset[:-1]
            g.set(dst_cls, name, a[vpt[starts]], owned=True)
        else:
            g.set(dst_cls, name, a, owned=True)
        return g

    def reduce_to(idx, vals, n):
        out = np.zeros((n, vals.shape[1]), np.float32)
        cnt = np.zeros((n, 1), np.float32)
        np.add.at(out, idx, vals.astype(np.float32))
        np.add.at(cnt, idx, 1.0)
        if method == "sum":
            return out
        if method == "max":
            m = np.full((n, vals.shape[1]), -np.inf, np.float32)
            np.maximum.at(m, idx, vals)
            return np.where(np.isfinite(m), m, 0)
        return out / np.where(cnt == 0, 1, cnt)

    if src_cls == POINT and dst_cls == PRIM:
        r = reduce_to(vprim, a[vpt], geo.nprims)
    elif src_cls == PRIM and dst_cls == POINT:
        r = reduce_to(vpt, a[vprim], geo.npoints)
    elif src_cls == POINT and dst_cls == VERTEX:
        r = a[vpt]
    elif src_cls == VERTEX and dst_cls == POINT:
        r = reduce_to(vpt, a, geo.npoints)
    elif src_cls == PRIM and dst_cls == VERTEX:
        r = a[vprim]
    elif src_cls == VERTEX and dst_cls == PRIM:
        r = reduce_to(vprim, a, geo.nprims)
    elif dst_cls == DETAIL:
        r = a.mean(0, keepdims=True)
    else:
        r = a
    g.set(dst_cls, name, r, owned=True)
    return g


# ---------------------------------------------------------------- grouping
def group_by_bbox(geo, cls, name, bmin, bmax, invert=False):
    P = geo.get(POINT, "P")
    m = np.all((P >= np.asarray(bmin, np.float32)) &
               (P <= np.asarray(bmax, np.float32)), axis=1)
    if cls == PRIM:
        m = np.minimum.reduceat(m[geo.vertex_point].astype(np.int8),
                                geo.prim_offset[:-1]).astype(bool)
    g = geo.copy()
    g.set_group(cls, name, ~m if invert else m)
    return g
