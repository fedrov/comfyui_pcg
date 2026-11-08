"""
Attribute Transform Extract (Houdini / KineFX semantics, pcg100 s7): splits point matrix attributes into component attributes,
then applies Euler filtering to the rotations.

The plugin's original PCG_AttribTransformExtract is "rigid transforms per piece between rest / animated geometries" (more like
Extract Transform per piece), not the same thing as this Houdini node (audit [C]) -- that node is left untouched, this is a new one.

━━ Matrix convention (same as Houdini, and the same as this plugin's Copy to Points / Transform by Attribute,
   see xform.point_matrices): row vectors, row-major, p' = p · H
    9 components   3×3
    16 components  upper-left 3×3 as above, translation in the first three numbers of the 4th row
All decompositions below are done on H,
and are the inverse of ops.xform_matrix (the Transform SOP matrix, row vectors):
    Crack     H = S·Sh, R, T right-multiplied in Transform Order (S diagonal, Sh unit lower-triangular:
              x += xy·y + xz·z, y += yz·z; R = euler_matrix(...)ᵀ)
    Polar     H3 = Stretch · R (Stretch symmetric positive semi-definite; via SVD), translation taken directly from the 4th row
Rotations are output as Euler angles (degrees) in Rotation Order; one matrix corresponds to two Euler solutions plus integer multiples of 360°,
and Euler filtering picks the solution nearest to the "reference angle": the reference = the parent's (already filtered) angle in the hierarchy,
or Hint for points without a parent.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, is_string
from .groups import resolve
from .ops import ROTATE_ORDERS, XFORM_ORDERS, match_names

HIERARCHY = ("none", "topology", "pieces_points")
DECOMPOSITIONS = ("polar", "crack")

_AX = {"x": 0, "y": 1, "z": 2}


def matrix_to_euler(E, order="xyz"):
    """
    Column-vector rotation matrices E (n,3,3) -> angles (n,3) (degrees, stored as x y z components), the inverse of ops.euler_matrix.

    order = (i, j, k) means rotate about i, then j, then k: E = R_k R_j R_i. The axes are permuted to the standard x y z case
    (E' = Pm E Pmᵀ) and the Rz Ry Rx formulas used; for an odd permutation every angle is negated (the mirror flips the handedness).
    """
    if order not in ROTATE_ORDERS:
        raise ValueError(f"Rotation Order must be one of {ROTATE_ORDERS}")
    idx = [_AX[c] for c in order]
    Pm = np.zeros((3, 3))
    for r, c in enumerate(idx):
        Pm[r, c] = 1.0
    par = np.linalg.det(Pm)
    Ep = np.einsum("ab,nbc,dc->nad", Pm, np.asarray(E, np.float64), Pm)
    sb = np.clip(-Ep[:, 2, 0], -1.0, 1.0)
    b = np.arcsin(sb)
    cb = np.sqrt(np.maximum(1.0 - sb * sb, 0.0))
    ok = cb > 1e-9
    a = np.where(ok, np.arctan2(Ep[:, 2, 1], Ep[:, 2, 2]), 0.0)
    # gimbal lock: a is set to 0 and the whole angle goes to c
    c = np.where(ok, np.arctan2(Ep[:, 1, 0], Ep[:, 0, 0]),
                 np.arctan2(-Ep[:, 0, 1], Ep[:, 1, 1]))
    ang = np.degrees(np.stack([a, b, c], 1)) * par
    out = np.zeros_like(ang)
    for k, ax in enumerate(idx):
        out[:, ax] = ang[:, k]
    return out


def _alt_euler(eul, order):
    """The other Tait-Bryan solution of the same rotation: (a + 180, 180 − b, c + 180) (the 1st, 2nd, 3rd axes in rotation order)."""
    idx = [_AX[c] for c in order]
    alt = eul.copy()
    alt[:, idx[0]] += 180.0
    alt[:, idx[1]] = 180.0 - alt[:, idx[1]]
    alt[:, idx[2]] += 180.0
    return alt


def euler_filter(eul, ref, order):
    """For each point pick, among the two solutions (each plus integer multiples of 360°), the one nearest to ref (sum of squared component differences)."""
    best = None
    bd = None
    for cand in (eul, _alt_euler(eul, order)):
        c = cand + 360.0 * np.round((ref - cand) / 360.0)
        d = ((c - ref) ** 2).sum(1)
        if best is None:
            best, bd = c, d
        else:
            take = d < bd - 1e-9
            best = np.where(take[:, None], c, best)
            bd = np.where(take, d, bd)
    return best


def _parents(geo, source, piece_attribute, sel):
    """Each point's parent (−1 = none). Only links selected points."""
    n = geo.npoints
    par = np.full(n, -1, np.int64)
    if source == "none":
        return par
    if source == "topology":
        # on each line (prim) the previous point is the parent; a point on several lines takes its first occurrence
        vp = geo.vertex_point.astype(np.int64)
        off = geo.prim_offset.astype(np.int64)
        for p in range(geo.nprims):
            pts = vp[off[p]:off[p + 1]]
            for a, b in zip(pts[:-1], pts[1:]):
                if par[b] < 0 and a != b and sel[a] and sel[b]:
                    par[b] = a
        # cycle guard (closed lines, first/last): walk the parent chain, break if it comes back to itself
        for i in range(n):
            seen = set()
            j = i
            while j >= 0 and j not in seen:
                seen.add(j)
                j = par[j]
            if j >= 0:
                par[j] = -1
        return par
    # pieces_points: within the same piece, by point number, the previous selected point is the parent
    nm = str(piece_attribute).strip()
    a = geo.get(POINT, nm) if nm else None
    if a is None or (not is_string(a) and np.asarray(a).dtype.kind == "f"):
        keys = np.zeros(n, np.int64)         # docs: missing or not integer / string -> all one piece
    else:
        keys = np.asarray(a)[:, 0]
    last = {}
    for i in np.nonzero(sel)[0]:
        k = keys[i].item() if hasattr(keys[i], "item") else keys[i]
        if k in last:
            par[i] = last[k]
        last[k] = i
    return par


def _depth(par):
    n = len(par)
    d = np.full(n, -1, np.int64)
    for i in range(n):
        chain = []
        j = i
        while j >= 0 and d[j] < 0:
            chain.append(j)
            j = par[j]
        base = d[j] if j >= 0 else -1
        for m in reversed(chain):
            base += 1
            d[m] = base
    return d


def _qr_pos(L):
    """L (n,3,3) = Q U, U upper-triangular with positive diagonal (Q is orthogonal, det may be −1)."""
    Q, U = np.linalg.qr(L)
    s = np.sign(np.einsum("nii->ni", U))
    s[s == 0] = 1.0
    return Q * s[:, None, :], U * s[:, :, None]


def _fix_det(R, A, col):
    """When det R = −1 (the matrix has a mirror): negate column col of R and row col of A together -- the mirror goes onto that scale component."""
    flip = np.linalg.det(R) < 0
    R[flip, :, col] *= -1.0
    A[flip, col, :] *= -1.0
    return R, A


def crack(H, xform_order="srt"):
    """
    Row-vector 4×4 H (n,4,4) -> (t, Rrow, s, shear). Rrow is the rotation in row-vector convention (= Eᵀ).
    Linear part L: when S comes before R (srt / str / tsr) L = A·R, otherwise L = R·A; A = diag(s)·Sh lower-triangular.
    """
    if xform_order not in XFORM_ORDERS:
        raise ValueError(f"Transform Order must be one of {XFORM_ORDERS}")
    L = H[:, :3, :3]
    s_first = xform_order.index("s") < xform_order.index("r")
    if s_first:
        # Lᵀ = Rᵀ Aᵀ, Aᵀ upper-triangular -> QR on Lᵀ
        Q, U = _qr_pos(np.transpose(L, (0, 2, 1)))
        R = np.transpose(Q, (0, 2, 1))
        A = np.transpose(U, (0, 2, 1))
        # L = A R: negate row 2 of R and column 2 of A together (A stays lower-triangular)
        flip = np.linalg.det(R) < 0
        R[flip, 2, :] *= -1.0
        A[flip, :, 2] *= -1.0
    else:
        # L = R A, A lower-triangular: QL decomposition = QR on L J (J is the reversal permutation)
        J = np.eye(3)[::-1]
        Q, U = _qr_pos(L @ J)
        R, A = _fix_det(Q @ J, J @ U @ J, 2)
    s = np.einsum("nii->ni", A).copy()
    sh = A / np.where(np.abs(s) > 1e-300, s, 1.0)[:, :, None]
    shear = np.stack([sh[:, 1, 0], sh[:, 2, 0], sh[:, 2, 1]], 1)
    # translation: 4th row = t · (product of the matrices after T)
    n = len(H)
    after = np.tile(np.eye(3), (n, 1, 1))
    for k in xform_order[xform_order.index("t") + 1:]:
        after = after @ (A if k == "s" else R)
    t = np.einsum("ni,nij->nj", H[:, 3, :3], np.linalg.inv(after))
    return t, R, s, shear


def polar(H):
    """H3 = Stretch · R (row vectors). Returns (R row-vector, Stretch symmetric)."""
    U, S, Vt = np.linalg.svd(H[:, :3, :3])
    d = np.linalg.det(U @ Vt)
    U2 = U.copy()
    U2[:, :, 2] *= np.where(d < 0, -1.0, 1.0)[:, None]
    S2 = S.copy()
    S2[:, 2] *= np.where(d < 0, -1.0, 1.0)
    R = U2 @ Vt
    St = np.einsum("nij,nj,nkj->nik", U2, S2, U2)
    return R, St


def attrib_transform_extract(geo, group="", hierarchy="none", piece_attribute="",
                             hint=(0.0, 0.0, 0.0), decomposition="polar",
                             xform_order="srt", rotate_order="xyz",
                             attributes="transform",
                             t_prefix="", t_suffix="_t", r_prefix="", r_suffix="_r",
                             stretch_prefix="", stretch_suffix="_stretch",
                             s_prefix="", s_suffix="_s", sh_prefix="", sh_suffix="_sh"):
    """Returns (geometry, report). Points outside the group get default values (translate 0, rotate 0, scale 1, shear 0, stretch identity)."""
    if hierarchy not in HIERARCHY:
        raise ValueError(f"Hierarchy Source must be one of {HIERARCHY}")
    if decomposition not in DECOMPOSITIONS:
        raise ValueError(f"Decomposition must be one of {DECOMPOSITIONS}")
    if rotate_order not in ROTATE_ORDERS:
        raise ValueError(f"Rotation Order must be one of {ROTATE_ORDERS}")
    if xform_order not in XFORM_ORDERS:
        raise ValueError(f"Transform Order must be one of {XFORM_ORDERS}")
    n = geo.npoints
    cand = [k for k, v in geo.attribs[POINT].items()
            if not is_string(v) and v.shape[1] in (9, 16)]
    names = match_names(sorted(cand), attributes)
    if not names:
        # In Houdini the node does nothing when Attributes matches no matrix; here it also returns the input unchanged and says so in the report
        return geo.copy(), {"matrices": [], "written": [], "points": 0, "roots": 0,
                            "warning": f"No 9 / 16 component matrix attribute on points matches '{attributes}'"
                                       f" (available: {sorted(cand)})"}
    sel = resolve(geo, POINT, group)
    par = _parents(geo, hierarchy, piece_attribute, sel)
    depth = _depth(par)
    hint = np.asarray(hint, np.float64)
    out = geo.copy()
    written = []

    def put(name, vals, default):
        full = np.empty((n, vals.shape[1]), np.float32)
        full[:] = default
        full[sel] = vals[sel]
        out.set(POINT, name, full, owned=True)
        written.append(name)

    for nm in names:
        a = np.asarray(geo.get(POINT, nm), np.float64)
        H = np.tile(np.eye(4), (n, 1, 1))
        # the attribute is already in Houdini row-vector convention (p' = p·H), use it directly
        if a.shape[1] == 9:
            H[:, :3, :3] = a.reshape(n, 3, 3)
        else:
            H[:] = a.reshape(n, 4, 4)
            H[:, :3, 3] = 0.0
            H[:, 3, 3] = 1.0
        if decomposition == "crack":
            t, Rrow, s, shear = crack(H, xform_order)
        else:
            Rrow, St = polar(H)
            t = H[:, 3, :3]
        eul = matrix_to_euler(np.transpose(Rrow, (0, 2, 1)), rotate_order)
        # Euler filtering: down the hierarchy from the roots, parents filtered first
        filt = eul.copy()
        for lv in range(int(depth.max()) + 1 if n else 0):
            m = depth == lv
            ref = np.where((par[m] >= 0)[:, None], filt[np.maximum(par[m], 0)], hint)
            filt[m] = euler_filter(eul[m], ref, rotate_order)
        if a.shape[1] == 16:
            put(f"{t_prefix}{nm}{t_suffix}", t, 0.0)
        put(f"{r_prefix}{nm}{r_suffix}", filt, 0.0)
        if decomposition == "crack":
            put(f"{s_prefix}{nm}{s_suffix}", s, 1.0)
            put(f"{sh_prefix}{nm}{sh_suffix}", shear, 0.0)
        else:
            put(f"{stretch_prefix}{nm}{stretch_suffix}", St.reshape(n, 9),
                np.eye(3).reshape(-1))
    return out, {"matrices": names, "written": written, "points": int(sel.sum()),
                 "roots": int(((par < 0) & sel).sum())}
