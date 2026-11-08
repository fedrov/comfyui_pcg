"""
Curve frames: Orient Along Curve and PolyFrame (pcg67, the foundation of batch A).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two nodes, two kinds of frames, don't mix them up
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Orient Along Curve   **rotation-minimizing frame** (RMF). Walking along the curve, the frame turns only as much as it
                       "has to". Used for placing things (railings, sleepers, chain links) and sweeping cross-sections;
                       it doesn't suddenly flip over at turns
  PolyFrame            **local** frames: each point / face only looks at its own neighbourhood (two edges, one face,
                       the uv gradient). On curves N is the Frenet principal normal (pointing to the inside
                       of the bend), undefined on straight segments, and it flips at inflection points -- that is its definition,
                       not a bug. For a frame you "can place things with", use Orient Along Curve

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RMF uses the double reflection method (Wang, Juttler, Zheng, Liu 2008)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ops.rmf_frames (used by Sweep) is the "projection method": the previous up is projected onto the next point's normal plane
and renormalized. It is a first-order approximation, losing a little accuracy every step, and the projection degenerates when the tangent turns more than 90 deg.
The double reflection method uses two mirror reflections per step and transports the frame **exactly** from one tangent to the next; the error is
fourth-order, and since reflections are orthogonal transforms the frame always stays orthogonal, with no renormalization needed to "rescue" it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The "holonomy angle" of closed curves
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When an RMF goes once around a closed loop back to the start, the frame generally does **not** return to its original orientation -- it is off by an angle
(always for non-planar loops; only planar loops give 0). Left alone, the frame would suddenly twist between the last point and the first.
The fix is to **spread this angle evenly by arc length** over the whole loop: each point rotates an extra
phi*s/L. That way start and end join up, the twist is distributed evenly, and the tests verify the start and end frames are continuous.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Output conventions (matching Copy to Points)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  N       tangent -- the copy's +Z runs along the curve (Copy to Points takes N as +Z)
  up      the frame's up direction -- the copy's +Y
  orient  quaternion (x,y,z,w) of the same frame, column basis [up x N, up, N]. When orient is present
          Copy to Points ignores N / up; both outputs give the same orientation
  side    X axis (up x N), not written by default
  curveu  normalized arc length 0~1, not written by default
When several curves share a point, the one written last wins (Houdini does the same).
"""
from __future__ import annotations

import math

import numpy as np

from .core import POINT, VERTEX, PRIM, PRIM_VOLUME
from .groups import resolve

TANGENT_TYPES = ("average", "previous", "next")
UP_MODES = ("minimal_rotation", "constant", "attribute")
PF_ENTITIES = ("point", "prim")
PF_STYLES = ("two_edges", "first_edge", "centroid", "uv", "attribute_gradient")

_EPS = 1e-12


def _unit(v):
    v = np.asarray(v, np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n < _EPS, 1.0, n)


def mat_to_quat(M):
    """
    (n,3,3) column-basis rotation matrices -> (n,4) quaternions (x,y,z,w). Inverse of xform.quat_to_mat.

    Shepperd's branch method: picks a denominator by the largest of the trace and the diagonal elements, avoiding division by a tiny number when w is close to 0.
    All four branches are vectorized and merged by masks at the end. w is always taken non-negative
    (q and -q are the same rotation; with a fixed sign tests can compare directly).
    """
    M = np.asarray(M, np.float64).reshape(-1, 3, 3)
    m00, m11, m22 = M[:, 0, 0], M[:, 1, 1], M[:, 2, 2]
    tr = m00 + m11 + m22
    q = np.zeros((len(M), 4))
    c0 = tr > 0
    c1 = ~c0 & (m00 >= m11) & (m00 >= m22)
    c2 = ~c0 & ~c1 & (m11 >= m22)
    c3 = ~c0 & ~c1 & ~c2
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.sqrt(np.maximum(tr + 1.0, 0)) * 2
        q0 = np.stack([(M[:, 2, 1] - M[:, 1, 2]) / s,
                       (M[:, 0, 2] - M[:, 2, 0]) / s,
                       (M[:, 1, 0] - M[:, 0, 1]) / s, 0.25 * s], 1)
        s = np.sqrt(np.maximum(1.0 + m00 - m11 - m22, 0)) * 2
        q1 = np.stack([0.25 * s, (M[:, 0, 1] + M[:, 1, 0]) / s,
                       (M[:, 0, 2] + M[:, 2, 0]) / s,
                       (M[:, 2, 1] - M[:, 1, 2]) / s], 1)
        s = np.sqrt(np.maximum(1.0 + m11 - m00 - m22, 0)) * 2
        q2 = np.stack([(M[:, 0, 1] + M[:, 1, 0]) / s, 0.25 * s,
                       (M[:, 1, 2] + M[:, 2, 1]) / s,
                       (M[:, 0, 2] - M[:, 2, 0]) / s], 1)
        s = np.sqrt(np.maximum(1.0 + m22 - m00 - m11, 0)) * 2
        q3 = np.stack([(M[:, 0, 2] + M[:, 2, 0]) / s,
                       (M[:, 1, 2] + M[:, 2, 1]) / s, 0.25 * s,
                       (M[:, 1, 0] - M[:, 0, 1]) / s], 1)
    for c, qq in ((c0, q0), (c1, q1), (c2, q2), (c3, q3)):
        q[c] = qq[c]
    q *= np.where(q[:, 3:4] < 0, -1.0, 1.0)
    return _unit(q)


def _rotate_about(v, axis, ang):
    """Rodrigues: rotates v by ang radians about the unit axis axis (per row)."""
    c = np.cos(ang)[:, None]
    s = np.sin(ang)[:, None]
    return (v * c + np.cross(axis, v) * s
            + axis * np.einsum("ij,ij->i", axis, v)[:, None] * (1 - c))


# ═══════════════════════════════════════════════════════════ curves
def curve_prims(geo, group=""):
    """
    Prims that can be treated as curves: more than two vertices, not volumes. Returns [(prim, point indices, closed)].
    Closed polygon faces count too (walking once around their edge loop) -- Houdini handles them the same way.
    """
    sel = resolve(geo, PRIM, group)
    sizes = geo.prim_sizes()
    out = []
    for i in np.nonzero(sel & (sizes >= 2)
                        & (geo.prim_type != PRIM_VOLUME))[0]:
        pts = geo.prim_points(int(i)).astype(np.int64)
        out.append((int(i), pts, bool(geo.prim_closed[i]) and len(pts) >= 3))
    return out


def _edges(P, closed):
    """Differences of adjacent points. When closed, one extra closing edge. Zero-length edges reuse the direction of the previous non-zero edge."""
    Q = np.vstack([P, P[:1]]) if closed else P
    e = np.diff(Q, axis=0)
    ln = np.linalg.norm(e, axis=1)
    ok = ln > _EPS
    if not ok.any():
        return e, ln, ok
    idx = np.where(ok, np.arange(len(e)), -1)
    idx = np.maximum.accumulate(idx)
    first = int(np.argmax(ok))
    idx[idx < 0] = first                          # leading zero edges use the first non-zero edge
    return e[idx], ln, ok


def curve_tangents(P, closed, mode="average"):
    """Unit tangent at each point. mode: average (average of the previous and next edge directions) / previous / next."""
    n = len(P)
    if n < 2:
        return np.tile([0.0, 0.0, 1.0], (n, 1))
    e, _, _ = _edges(P, closed)
    d = _unit(e)
    if closed:
        prev = np.roll(d, 1, axis=0)                # previous edge of point i = edge i-1
        nxt = d                                     # next edge of point i = edge i
    else:
        prev = np.vstack([d[:1], d])                # the start has no previous edge: use the next one
        nxt = np.vstack([d, d[-1:]])                # the end has no next edge: use the previous one
    if mode == "previous":
        return prev.copy()
    if mode == "next":
        return nxt.copy()
    s = prev + nxt
    bad = np.linalg.norm(s, axis=1) < 1e-9          # 180 deg reversal: the average cancels out
    s[bad] = nxt[bad]
    return _unit(s)


def _perp(u, t):
    """u with its component along t removed, then normalized; returns a None marker when degenerate (length < 1e-9)."""
    v = u - t * float(u @ t)
    ln = float(np.linalg.norm(v))
    return v / ln if ln > 1e-9 else None


def _any_perp(t):
    a = np.array([1.0, 0, 0]) if abs(t[0]) < 0.9 else np.array([0, 1.0, 0])
    return _unit(np.cross(t, a))


def rmf_double_reflection(P, T, r0):
    """
    Double reflection method. P (n,3) points, T (n,3) unit tangents, r0 the up at the start (already perpendicular to T[0]).
    Returns (n,3) ups. Zero-length segments reuse the previous up, projected onto the new tangent's normal plane.
    """
    n = len(P)
    R = np.empty((n, 3))
    R[0] = r0
    for i in range(n - 1):
        v1 = P[i + 1] - P[i]
        c1 = float(v1 @ v1)
        r, t = R[i], T[i]
        if c1 > _EPS:
            rL = r - (2.0 / c1) * float(v1 @ r) * v1
            tL = t - (2.0 / c1) * float(v1 @ t) * v1
        else:
            rL, tL = r, t
        v2 = T[i + 1] - tL
        c2 = float(v2 @ v2)
        rn = rL - (2.0 / c2) * float(v2 @ rL) * v2 if c2 > _EPS else rL
        q = _perp(rn, T[i + 1])
        R[i + 1] = q if q is not None else _any_perp(T[i + 1])
    return R


def _signed_angle(a, b, axis):
    """Signed angle (radians) from a to b about axis."""
    return math.atan2(float(np.cross(a, b) @ axis), float(a @ b))


def curve_frames(P, closed, tangent_type="average", up_mode="minimal_rotation",
                 up=(0, 1, 0), up_attr=None, roll=0.0, full_twists=0,
                 partial_twist=0.0, fix_closed=True):
    """
    Frames of one curve. Returns (T, U, u): tangent, up, normalized arc length (0~1).

    up_mode:
      minimal_rotation  the up at the start = the up parameter projected onto the normal plane (another axis if parallel),
                        then transported forward by double reflection; closed curves spread the holonomy angle by arc length
      constant          each point projects the up parameter onto its own normal plane; points where the tangent is parallel to up
                        are undefined and reuse the previous point's (transported along the RMF)
      attribute         like constant, but up comes from a point attribute (up_attr, (n,3))
    roll / twist: up is rotated about the tangent by roll + (full_twists*360 + partial_twist)*u degrees.
    """
    P = np.asarray(P, np.float64)
    n = len(P)
    T = curve_tangents(P, closed, tangent_type)
    Q = np.vstack([P, P[:1]]) if closed else P
    seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    L = s[-1]
    u = s[:n] / L if L > _EPS else np.zeros(n)
    upv = _unit(np.asarray(up, np.float64).reshape(3))

    if up_mode == "minimal_rotation":
        r0 = _perp(upv, T[0])
        if r0 is None:
            r0 = _any_perp(T[0])
        U = rmf_double_reflection(P, T, r0)
        if closed and fix_closed and n >= 3:
            # One more step: last point -> first point, to see how far the transported-back up is from the start
            wrap = rmf_double_reflection(np.vstack([P[-1:], P[:1]]),
                                         np.vstack([T[-1:], T[:1]]), U[-1])[1]
            phi = _signed_angle(wrap, U[0], T[0])
            U = _unit(_rotate_about(U, T, phi * u))
    elif up_mode in ("constant", "attribute"):
        src = (np.tile(upv, (n, 1)) if up_mode == "constant"
               else np.asarray(up_attr, np.float64).reshape(n, 3))
        U = np.empty((n, 3))
        prev = None
        for i in range(n):
            q = _perp(src[i], T[i])
            if q is None:
                if prev is None:
                    q = _any_perp(T[i])
                else:
                    q = _perp(prev, T[i])
                    q = q if q is not None else _any_perp(T[i])
            U[i] = q
            prev = q
    else:
        raise ValueError(f"Up mode must be one of {UP_MODES}")

    ang = math.radians(float(roll)) + math.radians(
        float(full_twists) * 360.0 + float(partial_twist)) * u
    ang = np.broadcast_to(np.asarray(ang, np.float64), (n,))
    if np.any(ang != 0):
        U = _unit(_rotate_about(U, T, ang))
    return T, U, u


def frame_matrices(T, U):
    """Column basis [X, Y, Z] = [U x T, U, T] -- the same convention as xform.look_at(N=T, up=U)."""
    X = _unit(np.cross(U, T))
    Y = np.cross(T, X)
    return np.stack([X, Y, T], axis=2)


def orient_along_curve(geo, group="", tangent_type="average",
                       up_mode="minimal_rotation", up=(0, 1, 0),
                       up_attribute="up", roll=0.0, full_twists=0,
                       partial_twist=0.0, reverse=False,
                       tangent_name="N", up_name="up", orient_name="orient",
                       side_name="", curveu_name=""):
    """
    Counterpart of Houdini's Orient Along Curve. Writes frames on the points of each curve (see curve_prims).
    reverse flips the tangent (copies face towards the start of the curve). An empty name = that item is not written.
    """
    if tangent_type not in TANGENT_TYPES:
        raise ValueError(f"Tangent Type must be one of {TANGENT_TYPES}")
    if up_mode not in UP_MODES:
        raise ValueError(f"Up mode must be one of {UP_MODES}")
    out = geo.copy()
    n = geo.npoints
    if n == 0:
        return out
    Pall = np.asarray(geo.get(POINT, "P"), np.float64)
    ua = None
    if up_mode == "attribute":
        ua = geo.get(POINT, str(up_attribute).strip())
        if ua is None or ua.shape[1] != 3:
            raise KeyError(f"No 3-component up attribute '{up_attribute}' on points")
        ua = np.asarray(ua, np.float64)
    T = np.zeros((n, 3))
    U = np.zeros((n, 3))
    CU = np.zeros(n)
    hit = np.zeros(n, bool)
    for _, pts, closed in curve_prims(geo, group):
        t, u, cu = curve_frames(Pall[pts], closed, tangent_type, up_mode, up,
                                None if ua is None else ua[pts], roll,
                                full_twists, partial_twist)
        if reverse:
            t = -t
        T[pts], U[pts], CU[pts] = t, u, cu
        hit[pts] = True
    if not hit.any():
        return out

    def put(name, val, keep_old):
        name = str(name).strip()
        if not name:
            return
        cur = out.get(POINT, name)
        dim = val.shape[1]
        base = (np.asarray(cur, np.float32) if cur is not None
                and cur.shape[1] == dim and keep_old
                else np.zeros((n, dim), np.float32))
        base = base.copy()
        base[hit] = val[hit]
        out.set(POINT, name, base, owned=True)

    M = frame_matrices(np.where(hit[:, None], T, [0, 0, 1.0]),
                       np.where(hit[:, None], U, [0, 1.0, 0]))
    put(tangent_name, T, True)
    put(up_name, U, True)
    put(orient_name, mat_to_quat(M), True)
    put(side_name, M[:, :, 0], True)
    put(curveu_name, CU[:, None], True)
    return out


# ═══════════════════════════════════════════════════════════ PolyFrame
def _newell(Pc):
    """Newell normal of a vertex loop (unnormalized, length = 2 x area)."""
    a, b = Pc, np.roll(Pc, -1, axis=0)
    return np.array([((a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2])).sum(),
                     ((a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0])).sum(),
                     ((a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1])).sum()])


def _tri_tangent(p0, p1, p2, w0, w1, w2):
    """
    Gradient direction of some scalar / 2-D quantity with respect to position on a triangle. w is (k,) or (k,2) (uv):
    returns the direction in which w[...,0] increases (for uv that is tangent u). Lengyel's formula:
        e1 = p1 − p0, e2 = p2 − p0, (du1, dv1), (du2, dv2)
        T = (e1·dv2 − e2·dv1) / (du1·dv2 − du2·dv1)
    For scalar fields it degenerates to the gradient within the triangle's plane.
    """
    e1, e2 = p1 - p0, p2 - p0
    if w0.ndim == 2 and w0.shape[1] >= 2:
        du1, dv1 = w1[:, 0] - w0[:, 0], w1[:, 1] - w0[:, 1]
        du2, dv2 = w2[:, 0] - w0[:, 0], w2[:, 1] - w0[:, 1]
        det = du1 * dv2 - du2 * dv1
        ok = np.abs(det) > 1e-20
        T = (e1 * dv2[:, None] - e2 * dv1[:, None]) / np.where(ok, det, 1)[:, None]
        T[~ok] = 0.0
        return T
    # Scalar gradient: grad f lies in the triangle plane, grad f.e1 = df1, grad f.e2 = df2
    f1 = (w1 - w0).reshape(-1)
    f2 = (w2 - w0).reshape(-1)
    a = np.einsum("ij,ij->i", e1, e1)
    b = np.einsum("ij,ij->i", e1, e2)
    c = np.einsum("ij,ij->i", e2, e2)
    det = a * c - b * b
    ok = np.abs(det) > 1e-30
    x = (f1 * c - f2 * b) / np.where(ok, det, 1)
    y = (f2 * a - f1 * b) / np.where(ok, det, 1)
    G = e1 * x[:, None] + e2 * y[:, None]
    G[~ok] = 0.0
    return G


def polyframe(geo, group="", entity="point", style="two_edges",
              uv_attribute="uv", gradient_attribute="", orthogonal=True,
              n_name="N", tu_name="tangentu", tv_name="tangentv"):
    """
    Counterpart of Houdini's PolyFrame: writes local frames (N, tangentu, tangentv) on points or faces.

    style (where tangentu comes from):
      two_edges           faces: the first edge; N = first edge x last edge (not Newell).
                          points: on curves the average tangent of the previous and next edges, N is the Frenet principal normal
                          (difference of the previous and next edge directions, pointing to the inside of the bend); points on faces use the outgoing edge
                          of the first corner
      first_edge          faces: the first edge, N = Newell; points: as above, N averaged over adjacent faces
      centroid            faces: from the centre towards the first vertex; points: pointing from the centre of the face they lie on
      uv                  the direction in which uv's u increases (Lengyel tangent, the same definition as a normal map's tangent
                          space); on points accumulated over adjacent triangles weighted by area
      attribute_gradient  the direction in which a scalar attribute increases fastest (in-face gradient)
    orthogonal orthogonalizes tangentu against N; tangentv = N x tangentu. An empty name =
    not written. Degenerate cases (zero area, zero length, no uv variation) write a 0 vector, never nan.
    """
    if entity not in PF_ENTITIES:
        raise ValueError(f"Entity must be one of {PF_ENTITIES}")
    if style not in PF_STYLES:
        raise ValueError(f"Style must be one of {PF_STYLES}")
    out = geo.copy()
    P = np.asarray(geo.get(POINT, "P"), np.float64) if geo.npoints \
        else np.zeros((0, 3))
    sizes = geo.prim_sizes()
    selp = resolve(geo, PRIM, group) & (sizes >= 2) & \
        (geo.prim_type != PRIM_VOLUME)
    faces = selp & geo.prim_closed & (sizes >= 3)

    uvw = gw = None
    if style == "uv":
        name = str(uv_attribute).strip() or "uv"
        uv_v = geo.get(VERTEX, name)
        uv_p = geo.get(POINT, name)
        if uv_v is None and uv_p is None:
            raise KeyError(f"No uv attribute '{name}' (on neither vertex nor point)")
        uvw = (np.asarray(uv_v, np.float64) if uv_v is not None
               else np.asarray(uv_p, np.float64)[geo.vertex_point])
    if style == "attribute_gradient":
        name = str(gradient_attribute).strip()
        a = geo.get(POINT, name) if name else None
        if a is None:
            raise KeyError(f"No point attribute '{name}' (attribute_gradient needs a scalar point attribute)")
        gw = np.asarray(a, np.float64)[:, :1][geo.vertex_point]

    # Fan triangles of each face (corner indices), used by the uv / gradient styles
    def fan(prims):
        cs = []
        for i in prims:
            o, k = int(geo.prim_offset[i]), int(sizes[i])
            for t in range(1, k - 1):
                cs.append((o, o + t, o + t + 1, i))
        return np.asarray(cs, np.int64).reshape(-1, 4)

    if entity == "prim":
        m = geo.nprims
        N = np.zeros((m, 3))
        TU = np.zeros((m, 3))
        for i in np.nonzero(selp)[0]:
            pts = geo.prim_points(int(i))
            Pc = P[pts]
            e0 = Pc[1] - Pc[0]
            nrm = _newell(Pc)
            if style == "two_edges" and len(Pc) >= 3:
                nrm = np.cross(e0, Pc[-1] - Pc[0])
            N[i] = nrm
            if style in ("two_edges", "first_edge"):
                TU[i] = e0
            elif style == "centroid":
                TU[i] = Pc[0] - Pc.mean(0)
        if style in ("uv", "attribute_gradient"):
            F = fan(np.nonzero(faces)[0])
            if len(F):
                vp = geo.vertex_point
                w = uvw if style == "uv" else gw
                G = _tri_tangent(P[vp[F[:, 0]]], P[vp[F[:, 1]]], P[vp[F[:, 2]]],
                                 w[F[:, 0]], w[F[:, 1]], w[F[:, 2]])
                area = 0.5 * np.linalg.norm(np.cross(
                    P[vp[F[:, 1]]] - P[vp[F[:, 0]]],
                    P[vp[F[:, 2]]] - P[vp[F[:, 0]]]), axis=1)
                np.add.at(TU, F[:, 3], G * area[:, None])
        cls, mask = PRIM, selp
    else:
        m = geo.npoints
        N = np.zeros((m, 3))
        TU = np.zeros((m, 3))
        on_face = np.zeros(m, bool)
        vp = geo.vertex_point
        vprim = geo.vertex_prim()
        # Points on faces: N = sum of adjacent faces' Newell normals (length = 2 x area, naturally area-weighted)
        for i in np.nonzero(faces)[0]:
            pts = geo.prim_points(int(i))
            nrm = _newell(P[pts])
            np.add.at(N, pts, nrm)
            on_face[pts] = True
        # tangentu: points on faces
        if style in ("two_edges", "first_edge"):
            nxt = geo.next_corner()
            fc = np.nonzero(faces[vprim])[0]
            big = np.iinfo(np.int64).max
            first = np.full(m, big, np.int64)
            np.minimum.at(first, vp[fc], fc)        # the face corner with the lowest index for each point
            has = first < big
            TU[has] = P[vp[nxt[first[has]]]] - P[has]
        elif style == "centroid":
            for i in np.nonzero(faces)[0]:
                pts = geo.prim_points(int(i))
                c = P[pts].mean(0)
                np.add.at(TU, pts, P[pts] - c)
        else:
            F = fan(np.nonzero(faces)[0])
            if len(F):
                w = uvw if style == "uv" else gw
                G = _tri_tangent(P[vp[F[:, 0]]], P[vp[F[:, 1]]], P[vp[F[:, 2]]],
                                 w[F[:, 0]], w[F[:, 1]], w[F[:, 2]])
                area = 0.5 * np.linalg.norm(np.cross(
                    P[vp[F[:, 1]]] - P[vp[F[:, 0]]],
                    P[vp[F[:, 2]]] - P[vp[F[:, 0]]]), axis=1)
                for k in range(3):
                    np.add.at(TU, vp[F[:, k]], G * area[:, None])
        # Points only on curves: tangent + Frenet principal normal
        for pi, pts, closed in curve_prims(geo, group):
            if faces[pi]:
                continue
            curve_only = ~on_face[pts]
            if not curve_only.any():
                continue
            Pc = P[pts]
            T = curve_tangents(Pc, closed, "average")
            prev = curve_tangents(Pc, closed, "previous")
            nxt = curve_tangents(Pc, closed, "next")
            K = nxt - prev                          # turning direction = principal normal
            TU[pts[curve_only]] = T[curve_only]
            N[pts[curve_only]] = K[curve_only]
        cls = POINT
        mask = np.zeros(m, bool)
        mask[vp[selp[vprim]]] = True

    N = _unit(N)
    if orthogonal:
        TU = TU - N * np.einsum("ij,ij->i", TU, N)[:, None]
    TU = _unit(TU)
    TV = np.cross(N, TU)

    for name, val in ((n_name, N), (tu_name, TU), (tv_name, TV)):
        name = str(name).strip()
        if not name:
            continue
        cur = out.get(cls, name)
        base = (np.asarray(cur, np.float32).copy() if cur is not None
                and cur.shape[1] == 3 else np.zeros((m, 3), np.float32))
        base[mask] = val[mask]
        out.set(cls, name, base, owned=True)
    return out
