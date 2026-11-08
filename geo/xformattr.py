"""
Transform by Attribute (pcg79): transforms the geometry itself by a matrix attribute.

The matrix attribute (default transform) is read exactly as in Copy to Points (xform.point_matrices):
    9 components   3×3, row-major, p' = M · p
    16 components  4×4, upper-left 3×3 as above, translation in the first three numbers of the 4th row
Class decides where the matrix comes from:
    detail   one matrix transforms all points
    point    each point uses its own matrix
    prim     each face transforms its points with its own matrix (a point shared by several faces uses the lowest-numbered face's --
             to transform each separately, split first with Facet unique_points)
Invert uses the inverse matrix (applies a transform found by Extract Transform in reverse).
Besides P it also transforms: normals (listed in Normals, default N; searched on points and vertices) with the inverse transpose, then normalized --
normals stay perpendicular to faces after non-uniform scaling (verified in tests); vectors (Vectors, default v up) are multiplied by the 3×3 only, no translation;
orient is multiplied by the matrix's rotation part (scale removed by polar decomposition). Points outside group do not move.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM, VERTEX, DETAIL, is_string
from .groups import resolve

XFORM_CLASSES = ("detail", "point", "prim")


def _matrices(a):
    """
    (n,9|16) -> (n,3,3) M, (n,3) T, such that p' = M @ p + T (column vectors).
    The attribute is stored by Houdini convention: row vectors p' = p · A, so M = A[:3,:3]ᵀ, T = A[3,:3].
    """
    a = np.asarray(a, np.float64)
    if a.shape[1] == 9:
        return np.transpose(a.reshape(-1, 3, 3), (0, 2, 1)).copy(), np.zeros((len(a), 3))
    if a.shape[1] == 16:
        m = a.reshape(-1, 4, 4)
        return np.transpose(m[:, :3, :3], (0, 2, 1)).copy(), m[:, 3, :3].copy()
    raise ValueError(f"A matrix attribute needs 9 or 16 components, this one has {a.shape[1]}")


def _polar_R(M):
    """Rotation part of M = R S (SVD), det corrected to +1."""
    U, _, Vt = np.linalg.svd(M)
    R = U @ Vt
    d = np.linalg.det(R)
    U[:, :, 2] *= np.where(d < 0, -1.0, 1.0)[:, None]
    return U @ Vt


def transform_by_attrib(geo, attribute="transform", cls="point", invert=False,
                        normals="N", vectors="v up", orient=True, group=""):
    """Returns (geometry, report)."""
    from .xform import quat_to_mat
    from .curveframe import mat_to_quat
    if cls not in XFORM_CLASSES:
        raise ValueError(f"Class must be one of {XFORM_CLASSES}")
    name = str(attribute).strip()
    a = geo.get({"detail": DETAIL, "point": POINT, "prim": PRIM}[cls], name)
    if a is None or is_string(a):
        raise KeyError(f"No numeric attribute '{name}' on {cls}")
    M, T = _matrices(a)
    n = geo.npoints
    if cls == "detail":
        idx = np.zeros(n, np.int64)
    elif cls == "point":
        idx = np.arange(n)
    else:
        idx = np.full(n, -1, np.int64)
        vp = geo.vertex_point.astype(np.int64)
        vpr = geo.vertex_prim().astype(np.int64)
        o = np.argsort(vpr, kind="stable")[::-1]          # written in reverse: the last write is from the lowest-numbered face
        idx[vp[o]] = vpr[o]
    has = idx >= 0
    idx = np.where(has, idx, 0)
    if invert:
        Mi = np.linalg.inv(M)
        T = -np.einsum("nij,nj->ni", Mi, T)
        M = Mi
    sel = resolve(geo, POINT, group) & has
    Mp, Tp = M[idx], T[idx]
    g = geo.copy()
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    P2 = np.where(sel[:, None], np.einsum("nij,nj->ni", Mp, P) + Tp, P)
    g.set(POINT, "P", P2.astype(geo.get(POINT, "P").dtype), owned=True)
    NT = np.transpose(np.linalg.inv(Mp), (0, 2, 1))
    vp = geo.vertex_point.astype(np.int64)
    done = []

    def apply(clsn, nm, mats, rows_sel, rows_idx, unit):
        v = geo.get(clsn, nm)
        if v is None or is_string(v) or v.shape[1] < 3:
            return
        V = np.asarray(v, np.float64).copy()
        W = np.einsum("nij,nj->ni", mats[rows_idx], V[:, :3])
        if unit:
            W /= np.maximum(np.linalg.norm(W, axis=1, keepdims=True), 1e-300)
        V[:, :3] = np.where(rows_sel[:, None], W, V[:, :3])
        g.set(clsn, nm, V.astype(v.dtype), owned=True)
        done.append(f"{clsn}.{nm}")
    pid = np.arange(n)
    for nm in str(normals).split():
        apply(POINT, nm, NT, sel, pid, True)
        apply(VERTEX, nm, NT, sel[vp], vp, True)
    for nm in str(vectors).split():
        apply(POINT, nm, Mp, sel, pid, False)
        apply(VERTEX, nm, Mp, sel[vp], vp, False)
    if orient:
        q = geo.get(POINT, "orient")
        if q is not None and not is_string(q) and q.shape[1] >= 4:
            R = _polar_R(Mp)
            Q = mat_to_quat(R @ quat_to_mat(np.asarray(q, np.float64)[:, :4]))
            Q0 = np.asarray(q, np.float64)
            Q0[:, :4] = np.where(sel[:, None], Q, Q0[:, :4])
            g.set(POINT, "orient", Q0.astype(q.dtype), owned=True)
            done.append("point.orient")
    return g, {"points_moved": int(sel.sum()), "transformed": done}
