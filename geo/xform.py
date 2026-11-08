"""
Instance transform attributes -- implements Houdini's convention of "attributes on points decide how copies are placed".

Copy to Points, Instance and Copy Stamp use **the same** attribute names and the same composition order,
so it is factored into its own layer: a future Instance node, or a debug node that "only computes matrices without copying geometry",
can call this directly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Attribute table (matches Houdini's instance attributes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    P          position (required)
    pivot      centre of rotation and scale, in **the source geometry's local coordinates**
    scale      per-axis scale (vec3), or a scalar
    pscale     uniform scale, multiplied with scale
    rot        quaternion, an extra rotation in local space first
    orient     quaternion, overall orientation -- **when present N / up / v are ignored entirely**
    N          orientation: the copy's +Z aligns to N
    up         used with N: the copy's +Y aligns to up as closely as possible
    v          without N, v is used as N (velocity direction)
    trans      an extra translation on top of P
    transform  3x3 (9 numbers) or 4x4 (16 numbers), **overrides all the rotation and scale above**

Composition order:

    P' = P + trans + R_orient · ( R_rot · ( S · (p_src - pivot) ) )

Read out: move to pivot, then scale, then the local rot, then the overall orient, finally translate into place.
rot is **inside** orient, which is Houdini's rule -- rot is "this copy turns itself a bit"
(e.g. giving each tree a random Y rotation), orient is "place it at the target point's orientation". Reversed,
the random rotation would turn around world axes and the trees would tilt.

Quaternions are stored as (x, y, z, w), as in Houdini.
"""
from __future__ import annotations

import numpy as np

from .core import POINT

# Attribute names that take part in the transform. Copy to Points must exclude them when copying target point attributes --
# otherwise copies carry a meaningless orient / pscale, and a downstream Copy would apply them twice.
INSTANCE_ATTRIBS = ("P", "pivot", "scale", "pscale", "rot", "orient",
                    "N", "up", "v", "trans", "transform")


def _norm(v, eps=1e-12):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), eps)


def quat_to_mat(q):
    """(n,4) quaternions (x,y,z,w) -> (n,3,3) rotation matrices (column basis, M @ p)."""
    q = _norm(np.asarray(q, np.float64).reshape(-1, 4))
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w),
                  2 * (x * z + y * w)], 1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z),
                  2 * (y * z - x * w)], 1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w),
                  1 - 2 * (x * x + y * y)], 1)], 1)


def look_at(N, up):
    """
    Orthonormal basis with N -> +Z, up -> +Y, returned as (n,3,3) column-basis matrices.

    When up and N are collinear the basis degenerates, so a temporary up is substituted. **Per point**, not for the whole batch --
    on terrain only a few points have normals pointing straight up, and swapping for the whole batch would make all other points' orientations jump.
    """
    z = _norm(np.asarray(N, np.float64).reshape(-1, 3))
    u = np.asarray(up, np.float64).reshape(-1, 3) * np.ones_like(z)
    u = _norm(u)
    bad = np.abs(np.einsum("ij,ij->i", z, u)) > 0.9999
    if bad.any():
        alt = np.where(np.abs(z[:, 0:1]) < 0.9,
                       np.array([1.0, 0, 0]), np.array([0, 1.0, 0]))
        u = np.where(bad[:, None], alt, u)
    x = _norm(np.cross(u, z))
    y = np.cross(z, x)
    return np.stack([x, y, z], axis=2)          # column vectors as basis


def _col(pts, name, dim):
    a = pts.get(POINT, name)
    if a is None:
        return None
    a = np.asarray(a, np.float64)
    if a.shape[1] == 1 and dim > 1:             # a scalar means the same on every axis
        return np.repeat(a, dim, axis=1)
    if a.shape[1] < dim:
        return None
    return a[:, :dim]


def point_matrices(pts, up=(0, 1, 0), use_orientations=True):
    """
    Read point attributes and give each point's (M (n,3,3), T (n,3), pivot (n,3)).

    A point p on the copy ends up at:  M @ (p - pivot) + T
    use_orientations=False keeps only the translation -- corresponding to Houdini's
    "Transform Using Target Point Orientations" turned off.
    """
    n = pts.npoints
    eye = np.tile(np.eye(3), (n, 1, 1))
    P = _col(pts, "P", 3)
    if P is None:
        P = np.zeros((n, 3))
    trans = _col(pts, "trans", 3)
    T = P + (trans if trans is not None else 0.0)
    pivot = _col(pts, "pivot", 3)
    pivot = pivot if pivot is not None else np.zeros((n, 3))
    if not use_orientations or n == 0:
        return eye, T, pivot

    xf = pts.get(POINT, "transform")
    if xf is not None and xf.shape[1] in (9, 16):
        # the transform attribute rules; all other rotation/scale attributes are ignored (Houdini's rule)
        # Houdini convention: row vectors, row-major, p' = p · M (4×4 translation in the 4th row).
        # Internally column vectors M @ p are used, so it is transposed on read (it used not to be, and rotations went the wrong way)
        a = np.asarray(xf, np.float64)
        if a.shape[1] == 9:
            M = np.transpose(a.reshape(n, 3, 3), (0, 2, 1))
        else:
            m4 = a.reshape(n, 4, 4)
            M = np.transpose(m4[:, :3, :3], (0, 2, 1))
            T = T + m4[:, 3, :3]
        return M, T, pivot

    orient = _col(pts, "orient", 4)
    if orient is not None:
        M = quat_to_mat(orient)
    else:
        N = _col(pts, "N", 3)
        if N is None:
            N = _col(pts, "v", 3)
        if N is None:
            M = eye
        else:
            u = _col(pts, "up", 3)
            M = look_at(N, u if u is not None else np.asarray(up, np.float64))

    rot = _col(pts, "rot", 4)
    if rot is not None:
        M = M @ quat_to_mat(rot)                # rot is the inner one: spin itself first, then orient

    s = np.ones((n, 3))
    sc = _col(pts, "scale", 3)
    if sc is not None:
        s = s * sc
    ps = _col(pts, "pscale", 1)
    if ps is not None:
        s = s * ps
    if not np.allclose(s, 1.0):
        M = M * s[:, None, :]                   # column scaling = scale first, then rotate
    return M, T, pivot


def apply_matrices(p, M, T, pivot):
    """(m,3) source points × (n,·) per-point transforms -> (n,m,3)."""
    q = p[None, :, :] - pivot[:, None, :]
    return np.einsum("nij,nmj->nmi", M, q) + T[:, None, :]


def normal_matrices(M):
    """Direction attributes (N / up / v) use the inverse transpose so they do not skew under non-uniform scale."""
    try:
        return np.linalg.inv(M).transpose(0, 2, 1)
    except np.linalg.LinAlgError:
        out = np.empty_like(M)
        for i in range(len(M)):
            try:
                out[i] = np.linalg.inv(M[i]).T
            except np.linalg.LinAlgError:
                out[i] = M[i]
        return out
