"""
Primitive, Attribute Reorient, DeltaMush.

━━ Primitive
Each selected prim is translated / rotated / scaled about **its own centre** (the average of its points), plus moved
some distance along its own normal (Normal Offset). If Scale Attribute is given it is further multiplied by that prim attribute (e.g. scaling each piece by area or
a random number). With Unshare Points on, the points of selected prims are split first -- when adjacent faces share points,
a point belongs to several prims and "which centre to rotate about" has no answer; without splitting, a shared point follows the transform of the **last**
prim processed (Houdini's Primitive SOP behaves the same way; the mesh gets torn).

━━ Attribute Reorient
The geometry was deformed, but the direction attributes on its points (N, up, v, orient...) are still pre-deformation -- most deformers
don't rotate them (or the attributes were copied from rest later). This uses two same-topology point sets, rest and deformed,
and each point takes itself plus its one-ring neighbours to solve a local best-fit rotation (Kabsch), rotating vector attributes (v' = R*v, length
unchanged) and left-multiplying quaternion attributes (q' = R*q). Attributes are read from deformed; if missing on deformed, from rest.
On curves (collinear neighbourhoods) the twist about the tangent can't be determined, so only the minimal "tangent to tangent" rotation is applied -- a curve
rotated as a whole about its own axis shows no such rotation.

━━ DeltaMush (Mancewicz et al. 2014)
Deformations (skinning, lattice, point deform) often damage detail: wrinkles get flattened, joints collapse. DeltaMush separates "detail"
from "overall shape":
  1. rest and deformed each get the same number of Laplacian smoothing passes, giving two "smooth overall shapes"
  2. detail = rest - smoothed rest, recorded in the **local frames** (vertex normal + tangent) of the smoothed rest
  3. result = smoothed deformed + the same local coordinates restored in the frames of the smoothed deformed
Under a global rigid motion the result is **exactly** deformed (smoothing and frames both follow the rigid motion; verified in the tests);
local bad deformation is absorbed by the smoothing, and detail is reapplied as in rest. The Mask point attribute (0-1) controls how much correction
each point gets (0 = deformed unchanged). Boundary points can be pinned and not smoothed (so open meshes don't shrink inwards).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, VERTEX, is_string
from .groups import resolve
from .ops import euler_matrix, match_names
from .topology import point_neighbours, topology

REORIENT_DEFAULT = "N up v orient"


# ═══════════════════════════════════════════════════════════ Primitive
def _unshare(geo, sel_prim):
    """Gives each corner of the selected prims its own point. Returns new geometry."""
    vp = geo.vertex_point.astype(np.int64)
    vpr = geo.vertex_prim()
    split = sel_prim[vpr]
    n0 = geo.npoints
    src = np.concatenate([np.arange(n0), vp[split]])
    new_vp = vp.copy()
    new_vp[split] = n0 + np.arange(int(split.sum()))
    # Original points used only by selected prims are now unused -- delete them
    used = np.zeros(len(src), bool)
    used[new_vp] = True
    remap = np.full(len(src), -1, np.int64)
    remap[used] = np.arange(int(used.sum()))
    out = Geometry()
    out._resize_points(int(used.sum()))
    out.set_topology(remap[new_vp].astype(np.int32), geo.prim_offset,
                     geo.prim_closed, geo.prim_type)
    keep = src[used]
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[keep], owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v[keep])
    for cls in (VERTEX, PRIM):
        for k, v in geo.attribs[cls].items():
            out.set(cls, k, v)
        for k, v in geo.groups[cls].items():
            out.set_group(cls, k, v)
    out.attribs["detail"] = dict(geo.attribs["detail"])
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    return out


PRIM_ATTR_MODES = ("keep", "add", "remove")
PRIM_CLOSE = ("no_change", "open", "close")
PRIM_VERTEX_OPS = ("none", "reverse", "reverse_u", "reverse_v", "swap_uv", "shift")


def _prim_attr(g, sel, name, mode, value, default):
    """
    Attributes tab of the Primitive SOP: add writes a prim attribute on the selected prims (if the attribute didn't exist, unselected
    prims get default -- in Houdini both Cd and Alpha default to 1); remove deletes the whole prim attribute
    (attributes belong to the whole geometry; you can't delete it "for some faces").
    """
    if mode == "keep":
        return
    if mode == "remove":
        if g.has(PRIM, name):
            g.remove(PRIM, name)
        return
    value = np.asarray(value, np.float32).reshape(1, -1)
    a = g.get(PRIM, name)
    if a is None or is_string(a) or a.shape[1] != value.shape[1]:
        a = np.full((g.nprims, value.shape[1]), default, np.float32)
    else:
        a = np.array(a, np.float32)
    a[sel] = value
    g.set(PRIM, name, a, owned=True)


def _prim_face_hull(g, group, sel, close_u, vertex_op, u_offset, v_offset):
    """Face/Hull tab: Close U (polygons are only open / closed) and the Vertex reorderings (same implementation as the Reverse node)."""
    if close_u != "no_change":
        from .core import PRIM_POLY
        cl = np.array(g.prim_closed, bool)
        cl[sel & (np.asarray(g.prim_type) == PRIM_POLY)] = close_u == "close"
        g.set_topology(g.vertex_point, g.prim_offset, cl, g.prim_type)
    if vertex_op != "none":
        from .ops import reverse_prims
        g = reverse_prims(g, group, vertex_op, u_offset, v_offset)
    return g


def primitive(geo, group="", translate=(0, 0, 0), rotate=(0, 0, 0),
              scale=(1, 1, 1), uniform_scale=1.0, scale_attribute="",
              normal_offset=0.0, unshare_points=True,
              xform_order="srt", rotate_order="xyz", shear=(0, 0, 0), pivot=(0, 0, 0),
              color_mode="keep", color=(1, 1, 1), alpha_mode="keep", alpha=1.0,
              close_u="no_change", vertex_op="none", u_offset=0, v_offset=0):
    """
    Added in pcg100 to match Houdini's Primitive SOP (with defaults it takes the original path, bit-identical results):
      xform_order / rotate_order / shear / pivot   Transform tab; the matrix is the same as the Transform node's
          (ops.xform_matrix), applied in local coordinates "with the prim centre as origin"; pivot is an offset from the centre
      color_mode / alpha_mode   Attributes tab: Keep / Add / Remove the prim attributes Cd, Alpha
      close_u / vertex_op       Face/Hull tab: open / close, Reverse / Shift etc. (done after the transform)
    """
    from .ops import XFORM_ORDERS, ROTATE_ORDERS
    if xform_order not in XFORM_ORDERS:
        raise ValueError(f"Transform Order must be one of {XFORM_ORDERS}")
    if rotate_order not in ROTATE_ORDERS:
        raise ValueError(f"Rotate Order must be one of {ROTATE_ORDERS}")
    for nm, v, allowed in (("Color", color_mode, PRIM_ATTR_MODES),
                           ("Alpha", alpha_mode, PRIM_ATTR_MODES),
                           ("Close U", close_u, PRIM_CLOSE),
                           ("Vertex", vertex_op, PRIM_VERTEX_OPS)):
        if v not in allowed:
            raise ValueError(f"{nm} must be one of {allowed}")
    g = _primitive_xform(geo, group, translate, rotate, scale, uniform_scale,
                         scale_attribute, normal_offset, unshare_points,
                         xform_order, rotate_order, shear, pivot)
    extra = (color_mode != "keep" or alpha_mode != "keep" or close_u != "no_change"
             or vertex_op != "none")
    if not extra:
        return g
    # _unshare doesn't change the number or order of prims, so groups refer to the same prims before and after the transform
    sel = resolve(g, PRIM, group) if str(group).strip() else np.ones(g.nprims, bool)
    _prim_attr(g, sel, "Cd", color_mode, color, 1.0)
    _prim_attr(g, sel, "Alpha", alpha_mode, [alpha], 1.0)
    return _prim_face_hull(g, group, sel, close_u, vertex_op, u_offset, v_offset)


def _primitive_xform(geo, group, translate, rotate, scale, uniform_scale,
                     scale_attribute, normal_offset, unshare_points,
                     xform_order, rotate_order, shear, pivot):
    from .ops import prim_normals, xform_matrix
    from .deformers import _rotate_dirs
    sel = resolve(geo, PRIM, group) if str(group).strip() else \
        np.ones(geo.nprims, bool)
    g = _unshare(geo, sel) if unshare_points else geo.copy()
    if not sel.any():
        return g
    P = np.asarray(g.get(POINT, "P"), np.float64)
    vp = g.vertex_point.astype(np.int64)
    vpr = g.vertex_prim()
    sizes = g.prim_sizes()
    C = np.zeros((g.nprims, 3))
    np.add.at(C, vpr, P[vp])
    C /= np.maximum(sizes, 1)[:, None]
    Nf = prim_normals(g).astype(np.float64)
    R = np.asarray(euler_matrix(*rotate), np.float64)   # same as Transform: Rx Ry Rz (X first), in degrees
    s = np.asarray(scale, np.float64) * float(uniform_scale)
    f = np.ones(g.nprims)
    sa = str(scale_attribute).strip()
    if sa:
        a = g.get(PRIM, sa)
        if a is None or is_string(a):
            raise KeyError(f"No numeric prim attribute '{sa}'")
        f = np.asarray(a, np.float64)[:, 0]
    out = P.copy()
    Mpt = np.tile(np.eye(3), (g.npoints, 1, 1))
    touched = np.zeros(g.npoints, bool)
    vsel = sel[vpr]
    pr = vpr[vsel]
    pts = vp[vsel]
    # When a point belongs to several selected prims, the last one in prim order wins (see the file header)
    o = np.argsort(pr, kind="stable")
    pr, pts = pr[o], pts[o]
    general = (xform_order != "srt" or rotate_order != "xyz"
               or any(float(x) for x in shear) or any(float(x) for x in pivot))
    if not general:
        # The only path before pcg100, kept as is: old workflows' results don't change by a single bit
        M = R * s[None, :]                              # scale first, then rotate
        Mp = M[None] * f[pr][:, None, None]
        newp = np.einsum("nij,nj->ni", Mp, P[pts] - C[pr]) + C[pr] + \
            np.asarray(translate, np.float64) + Nf[pr] * float(normal_offset)
    else:
        # The Scale Attribute factor f is a uniform scale and commutes with the linear part: L(f) = f*L(1); the translation is linear
        # in f (f appears only once, in S), so two matrices with f = 1, 2 determine a + f*b without building one matrix per prim
        us = float(uniform_scale)
        M1 = xform_matrix(translate, rotate, scale, shear, us, pivot, (0, 0, 0),
                          xform_order, rotate_order)
        M2 = xform_matrix(translate, rotate, scale, shear, 2.0 * us, pivot, (0, 0, 0),
                          xform_order, rotate_order)
        tb = M2[3, :3] - M1[3, :3]
        ta = M1[3, :3] - tb
        Mp = M1[:3, :3].T[None] * f[pr][:, None, None]  # column-vector convention, used below to rotate N / up / v
        newp = np.einsum("nij,nj->ni", Mp, P[pts] - C[pr]) + ta + f[pr][:, None] * tb \
            + C[pr] + Nf[pr] * float(normal_offset)
    out[pts] = newp
    Mpt[pts] = Mp
    touched[pts] = True
    src = g
    g2 = g.copy()
    g2.set(POINT, "P", out.astype(np.float32), owned=True)
    _rotate_dirs(src, g2, Mpt, touched)
    return g2


# ═══════════════════════════════════════════════════════════ Reorient
def _ring_rotations(Pr, Pd, off, nb):
    """Per point: itself + one-ring neighbours, best-fit rotation rest -> deformed."""
    from .deformers import _kabsch
    n = len(Pr)
    deg = np.diff(off)
    K = int(deg.max()) + 1 if len(deg) else 1
    idx = np.tile(np.arange(n)[:, None], (1, K))        # missing slots are filled with the point itself
    for k in range(1, K):
        has = deg >= k
        idx[has, k] = nb[off[:-1][has] + k - 1]
    A = Pr[idx]
    B = Pd[idx]
    A = A - A.mean(1, keepdims=True)
    B = B - B.mean(1, keepdims=True)
    R = _kabsch(A, B)
    # Collinear neighbourhoods (points on curves, endpoints with only one neighbour): the twist about the tangent can't be determined; Kabsch
    # gives an arbitrary one. Fall back to "minimal rotation of the rest tangent onto the deformed tangent"
    sv = np.linalg.svd(A, compute_uv=False)
    flat = sv[:, 1] <= 1e-6 * np.maximum(sv[:, 0], 1e-300)
    if flat.any():
        from .registration import _min_rot
        for i in np.nonzero(flat)[0]:
            j = idx[i]
            tr = Pr[j].max(0) - Pr[j].min(0)
            k0, k1 = j[np.argmin(Pr[j] @ tr)], j[np.argmax(Pr[j] @ tr)]
            er, ed = Pr[k1] - Pr[k0], Pd[k1] - Pd[k0]
            R[i] = _min_rot(er, ed) if np.linalg.norm(er) > 0 and \
                np.linalg.norm(ed) > 0 else np.eye(3)
    return R


def attribute_reorient(deformed, rest, attributes=REORIENT_DEFAULT):
    """Returns (geo, report)."""
    from .curveframe import mat_to_quat
    from .xform import quat_to_mat
    if rest.npoints != deformed.npoints:
        raise ValueError(f"rest has {rest.npoints} points, deformed has "
                         f"{deformed.npoints} -- same topology required")
    off, nb = point_neighbours(deformed)
    R = _ring_rotations(np.asarray(rest.get(POINT, "P"), np.float64),
                        np.asarray(deformed.get(POINT, "P"), np.float64), off, nb)
    g = deformed.copy()
    names = set(match_names(set(deformed.attribs[POINT]) | set(rest.attribs[POINT]),
                            attributes))
    done = []
    for nm in sorted(names):
        if nm == "P":
            continue
        a = deformed.get(POINT, nm)
        if a is None:
            a = rest.get(POINT, nm)
        if a is None or is_string(a):
            continue
        v = np.asarray(a, np.float64)
        if v.shape[1] == 3:
            r = np.einsum("nij,nj->ni", R, v)
        elif v.shape[1] == 4:
            r = mat_to_quat(np.einsum("nij,njk->nik", R, quat_to_mat(v)))
        else:
            continue
        g.set(POINT, nm, r.astype(a.dtype), owned=True)
        done.append(nm)
    return g, {"attributes": done, "points": deformed.npoints}


# ═══════════════════════════════════════════════════════════ DeltaMush
def _smooth(P, off, nb, iterations, step, pinned):
    cnt = np.maximum(np.diff(off), 1)[:, None]
    src = np.repeat(np.arange(len(P)), np.diff(off))
    move = (~pinned)[:, None] * float(step)
    X = P.copy()
    for _ in range(int(iterations)):
        acc = np.zeros_like(X)
        np.add.at(acc, src, X[nb])
        X = X + (acc / cnt - X) * move
    return X


def _frames(geo, X, off, nb):
    """(n,3,3) columns = [tangent, bitangent, normal]. Normal = area-weighted vertex normal."""
    from .spatial import tri_soup
    T, _, _ = tri_soup(geo)
    n = len(X)
    N = np.zeros((n, 3))
    if len(T):
        fn = np.cross(X[T[:, 1]] - X[T[:, 0]], X[T[:, 2]] - X[T[:, 0]])
        for k in range(3):
            np.add.at(N, T[:, k], fn)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    N = np.where(ln > 1e-30, N / np.maximum(ln, 1e-30), [0.0, 0.0, 1.0])
    deg = np.diff(off)
    Tg = np.zeros((n, 3))
    ok = np.zeros(n, bool)
    for k in range(int(deg.max()) if len(deg) else 0):   # first neighbour not parallel to the normal
        has = (deg > k) & ~ok
        if not has.any():
            break
        e = X[nb[off[:-1][has] + k]] - X[has]
        e = e - np.einsum("ij,ij->i", e, N[has])[:, None] * N[has]
        le = np.linalg.norm(e, axis=1)
        good = le > 1e-12
        ii = np.nonzero(has)[0][good]
        Tg[ii] = e[good] / le[good][:, None]
        ok[ii] = True
    B = np.cross(N, Tg)
    return np.stack([Tg, B, N], 2), ok


def delta_mush(deformed, rest, iterations=10, step=0.5, pin_boundary=True,
               mask_attribute=""):
    """Returns (geo, report)."""
    if rest.npoints != deformed.npoints:
        raise ValueError(f"rest has {rest.npoints} points, deformed has "
                         f"{deformed.npoints} -- same topology required")
    off, nb = point_neighbours(rest)
    Pr = np.asarray(rest.get(POINT, "P"), np.float64)
    Pd = np.asarray(deformed.get(POINT, "P"), np.float64)
    pinned = np.zeros(len(Pr), bool)
    if pin_boundary:
        t = topology(rest)
        if t.nedges:
            pinned[t.edge_points[t.boundary].reshape(-1)] = True
    Sr = _smooth(Pr, off, nb, iterations, step, pinned)
    Sd = _smooth(Pd, off, nb, iterations, step, pinned)
    Fr, okr = _frames(rest, Sr, off, nb)
    Fd, okd = _frames(deformed, Sd, off, nb)
    local = np.einsum("nji,nj->ni", Fr, Pr - Sr)         # Fr^T (rest - smoothed rest)
    out = Sd + np.einsum("nij,nj->ni", Fd, local)
    ok = okr & okd
    out[~ok] = Pd[~ok]
    mn = str(mask_attribute).strip()
    if mn:
        m = deformed.get(POINT, mn)
        if m is None:
            m = rest.get(POINT, mn)
        if m is None:
            raise KeyError(f"No point attribute '{mn}'")
        w = np.clip(np.asarray(m, np.float64)[:, :1], 0, 1)
        out = Pd * (1 - w) + out * w
    g = deformed.copy()
    g.set(POINT, "P", out.astype(np.float32), owned=True)
    return g, {"iterations": int(iterations), "points": len(Pr),
               "unframed": int((~ok).sum())}
