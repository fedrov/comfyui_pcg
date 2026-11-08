"""
Copiers and lathe (pcg67, batch A): Copy and Transform, Revolve, Copy to Curves, Chain.

━━ All go through Copy to Points
Copy and Transform, Copy to Curves and Chain all "first compute a set of target points (position +
orientation + piece number), then hand them to copyto.copy_to_points". That way how attributes are merged, how normals are rotated, how pieces
are picked and how copynum is written is **the same code** as Copy to Points -- you never get "normals copied with Copy
and Transform are right, but skewed with Copy to Curves".

  Copy and Transform   target point k carries the transform attribute = M^k (accumulated transform)
  Copy to Curves       target points taken along the curve by count / spacing, orient = Orient Along Curve's
                       RMF frame
  Chain                target points placed one after another by **each link's own length**; the link centre sits at the midpoint of the chord,
                       +Z along the chord, adjacent links rotated an extra Roll Step about the tangent (chain links alternating 90 deg)

Revolve really builds topology and is written separately: each cross-section point is rotated into a ring, and quads are laid between adjacent rings.
"""
from __future__ import annotations

import math

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import euler_matrix, delete_prims, delete_points
from . import copyto as _cp
from . import curveframe as _cf


def _set_copy_attr(g, name):
    """copy_to_points writes copynum; rename it / drop it."""
    name = str(name).strip()
    for cls in (POINT, PRIM):
        v = g.get(cls, "copynum")
        if v is None:
            continue
        if name != "copynum":
            g.remove(cls, "copynum")
            if name:
                g.set(cls, name, v, owned=True)
    return g


def _targets(P, M=None, orient=None, extra=None):
    """
    Builds a target point cloud: P, optional transform / orient, and other point attributes.
    M is a column-vector matrix (p' = M @ p); the transform attribute is stored in Houdini's row-vector convention, so M^T is written.
    """
    t = Geometry.from_points(np.asarray(P, np.float64).reshape(-1, 3))
    if M is not None:
        t.set(POINT, "transform",
              np.transpose(np.asarray(M, np.float64).reshape(-1, 3, 3), (0, 2, 1))
              .reshape(-1, 9).astype(np.float32),
              owned=True)
    if orient is not None:
        t.set(POINT, "orient", np.asarray(orient, np.float32), owned=True)
    for k, v in (extra or {}).items():
        if is_string(v):
            t.set_string(POINT, k, [str(x) for x in np.asarray(v).reshape(-1)])
        else:
            t.set(POINT, k, v, owned=True)
    return t


# ═══════════════════════════════════════════════════════ Copy and Transform
def copy_and_transform(geo, copies=2, translate=(0, 0, 0), rotate=(0, 0, 0),
                       scale=(1, 1, 1), uniform_scale=1.0, pivot=(0, 0, 0),
                       copy_attribute="copynum"):
    """
    Counterpart of Houdini's Copy and Transform. copies copies in total (**including the original**, copy 0 is unchanged);
    copy k applies the same transform M k times:

        M = translate t . about pivot (rotate R . scale S)       p -> R S (p - pivot) + pivot + t

    Rotation order is the same as Transform (PCG)'s default (euler_matrix, Rx Ry Rz, X first). The k-th power multiplies the affine matrix repeatedly, so
    "each copy rotates 30 deg then moves up 1" gives a spiral staircase, and "each copy scales by 0.9" gives a string of
    ever-smaller nesting dolls, rather than an approximation computing t*k and R^k separately.
    copy_attribute writes each copy's index (one on point and one on prim); empty means not written.
    """
    n = int(copies)
    if n < 0:
        raise ValueError("Copies cannot be negative")
    if geo is None or n == 0 or geo.npoints == 0:
        return Geometry()
    R = euler_matrix(*[float(x) for x in rotate]).astype(np.float64)
    S = np.diag(np.asarray(scale, np.float64) * float(uniform_scale))
    L = R @ S
    piv = np.asarray(pivot, np.float64)
    A = np.eye(4)
    A[:3, :3] = L
    A[:3, 3] = piv - L @ piv + np.asarray(translate, np.float64)
    mats = [np.eye(4)]
    for _ in range(1, n):
        mats.append(A @ mats[-1])
    mats = np.stack(mats)
    # copy_to_points' formula is M @ (p - pivot) + T, with pivot 0 and T = the translation part
    tgt = _targets(mats[:, :3, 3], mats[:, :3, :3])
    out = _cp.copy_to_points(geo, tgt, target_attribs="")
    return _set_copy_attr(out, copy_attribute)


# ═══════════════════════════════════════════════════════ Revolve
REVOLVE_SURFACES = ("quads", "triangles")


def revolve(geo, group="", origin=(0, 0, 0), axis=(0, 1, 0), start_angle=0.0,
            end_angle=360.0, divisions=16, end_caps=False,
            surface="quads", reverse=False, pole_tolerance=1e-6,
            uv_attribute=""):
    """
    Counterpart of Houdini's Revolve: a cross-section curve rotated about an axis, with faces laid between adjacent rings (lathe).

    - With a full 360 deg the first and last rings are the same ring, so points aren't duplicated (otherwise a whole row of zero-area faces along the seam,
      with nan normals). divisions is the number of segments per revolution
    - **Points of the cross-section on the axis are placed only once** (distance to axis < pole_tolerance). A semicircle revolves into
      a sphere with one point at each pole, and faces touching the poles automatically degenerate from quads to triangles -- otherwise
      the poles would be a ring of coincident points and zero-area quads, breaking normals, subdivision and UVs
    - With a closed cross-section (a loop) both the U and V directions are loops, and the result is a torus
    - end_caps: when not a full revolution and the cross-section is closed, the cross-section is capped at the start and end positions
    - Orientation: with the cross-section drawn bottom to top (along the axis' positive direction) on the positive side of the axis, normals point outward; if reversed use reverse
    - if uv_attribute is given, a vertex uv is written: u = fraction of the swept angle, v = fraction of arc length along the cross-section
    The cross-section's point attributes are carried in full onto every ring; the source prim's attributes onto every face it sweeps out.
    """
    if surface not in REVOLVE_SURFACES:
        raise ValueError(f"Surface must be one of {REVOLVE_SURFACES}")
    if geo is None or geo.npoints == 0:
        return Geometry()
    ax = np.asarray(axis, np.float64)
    if np.linalg.norm(ax) < 1e-12:
        raise ValueError("Axis cannot be a zero vector")
    ax = ax / np.linalg.norm(ax)
    org = np.asarray(origin, np.float64)
    a0, a1 = math.radians(float(start_angle)), math.radians(float(end_angle))
    sweep = a1 - a0
    full = abs(abs(sweep) - 2 * math.pi) < 1e-9 or abs(sweep) > 2 * math.pi
    D = max(1, int(divisions))
    nring = D if full else D + 1
    angs = a0 + sweep * np.arange(nring) / D

    Pall = np.asarray(geo.get(POINT, "P"), np.float64)
    curves = _cf.curve_prims(geo, group)
    if not curves:
        return Geometry()

    newP, pt_src, faces, face_src, face_uv = [], [], [], [], []
    base = 0
    for pi, pts, closed in curves:
        Q = Pall[pts]
        rel = Q - org
        h = rel @ ax                                  # height along the axis
        radial = rel - np.outer(h, ax)
        rdist = np.linalg.norm(radial, axis=1)
        pole = rdist < float(pole_tolerance)
        m = len(pts)
        # New point number of each cross-section point on each ring; a pole column shares one point
        idx = np.full((nring, m), -1, np.int64)
        cnt = 0
        for j in range(m):
            if pole[j]:
                idx[:, j] = base + cnt
                newP.append(org + h[j] * ax + radial[j])
                pt_src.append(pts[j])
                cnt += 1
        for r in range(nring):
            c, s = math.cos(angs[r]), math.sin(angs[r])
            rot = (radial * c + np.cross(ax, radial) * s
                   + np.outer(radial @ ax, ax) * (1 - c))
            for j in range(m):
                if not pole[j]:
                    idx[r, j] = base + cnt
                    newP.append(org + h[j] * ax + rot[j])
                    pt_src.append(pts[j])
                    cnt += 1
        base += cnt
        # Arc-length fraction along the cross-section (the v of uv)
        Qc = np.vstack([Q, Q[:1]]) if closed else Q
        seg = np.linalg.norm(np.diff(Qc, axis=0), axis=1)
        sv = np.concatenate([[0.0], np.cumsum(seg)])
        sv = sv / sv[-1] if sv[-1] > 0 else sv
        nseg = m if closed else m - 1
        for r in range(D):
            r2 = (r + 1) % nring
            u0, u1 = r / D, (r + 1) / D
            for j in range(nseg):
                j2 = (j + 1) % m
                quad = [idx[r, j], idx[r2, j], idx[r2, j2], idx[r, j2]]
                uvq = [(u0, sv[j]), (u1, sv[j]), (u1, sv[j + 1]), (u0, sv[j + 1])]
                if reverse:
                    quad, uvq = quad[::-1], uvq[::-1]
                # Remove adjacent duplicate points (quads degenerate into triangles at the poles)
                keep = [k for k in range(4) if quad[k] != quad[(k + 1) % 4]]
                q2 = [quad[k] for k in keep]
                uv2 = [uvq[k] for k in keep]
                if len(set(q2)) < 3:
                    continue                          # both points on the axis: the whole segment is the axis
                if surface == "triangles" and len(q2) == 4:
                    for tri in ((0, 1, 2), (0, 2, 3)):
                        faces.append([q2[t] for t in tri])
                        face_uv.append([uv2[t] for t in tri])
                        face_src.append(pi)
                else:
                    faces.append(q2)
                    face_uv.append(uv2)
                    face_src.append(pi)
        if end_caps and closed and not full and m >= 3:
            for r, flip in ((0, True), (nring - 1, False)):
                cap = list(idx[r])
                if flip != bool(reverse):
                    cap = cap[::-1]
                if len(set(cap)) >= 3:
                    faces.append(cap)
                    face_uv.append([(0.0, 0.0)] * len(cap))
                    face_src.append(pi)

    out = Geometry.from_mesh(np.asarray(newP), faces, closed=True) if faces \
        else Geometry.from_points(np.asarray(newP))
    pt_src = np.asarray(pt_src, np.int64)
    for k, v in geo.attribs[POINT].items():
        if k != "P":
            out.set(POINT, k, v[pt_src], owned=True)
    if faces:
        fs = np.asarray(face_src, np.int64)
        for k, v in geo.attribs[PRIM].items():
            out.set(PRIM, k, v[fs], owned=True)
        name = str(uv_attribute).strip()
        if name:
            uv = np.array([p for f in face_uv for p in f], np.float32)
            out.set(VERTEX, name, np.hstack([uv, np.zeros((len(uv), 1),
                                                          np.float32)]),
                    owned=True)
    return out


# ═══════════════════════════════════════════════════════ copy along curves
# curve_points was added in pcg100 to follow Houdini: copy onto the curve's existing points (copy_to_curve_points)
CURVE_COPY_MODES = ("count", "spacing", "curve_points")
MAX_LINKS = 100000


def _sample(P, closed, T, U, d):
    """
    Position, tangent and up on the polyline at arc length d (may be an array). The tangent is the direction of the segment it lies on
    (exact on a polyline); up is linearly interpolated between the RMF ups of the two end points, then projected onto the tangent's normal plane.
    """
    Q = np.vstack([P, P[:1]]) if closed else P
    Tq = np.vstack([T, T[:1]]) if closed else T
    Uq = np.vstack([U, U[:1]]) if closed else U
    seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    d = np.clip(np.asarray(d, np.float64), 0.0, s[-1])
    k = np.clip(np.searchsorted(s, d, side="right") - 1, 0, len(seg) - 1)
    f = np.where(seg[k] > 0, (d - s[k]) / np.where(seg[k] > 0, seg[k], 1), 0)
    pos = Q[k] + (Q[k + 1] - Q[k]) * f[:, None]
    tan = _cf._unit(Q[k + 1] - Q[k])
    zero = np.linalg.norm(Q[k + 1] - Q[k], axis=1) < 1e-12
    tan[zero] = Tq[k][zero]
    up = Uq[k] * (1 - f[:, None]) + Uq[k + 1] * f[:, None]
    up = _cf._unit(up - tan * np.einsum("ij,ij->i", up, tan)[:, None])
    return pos, tan, up, s[-1]


def _roll(tan, up, ang):
    return _cf._unit(_cf._rotate_about(up, tan, ang))


def _piece_table(src, attr):
    """Source pieces: [(key, sub-geometry, [min, max] along local Z, centre)]; without a piece attribute the whole thing is one piece."""
    name = str(attr).strip()
    pieces = []
    if name:
        cls, skey = _cp._source_piece_keys(src, name)
        if skey is None:
            raise KeyError(f"The source geometry has no piece attribute '{name}'")
        for val in list(dict.fromkeys(skey.tolist())):       # keep the order of first appearance
            pick = skey == val
            sub = delete_prims(src, pick) if cls == PRIM else \
                delete_points(src, pick)
            pieces.append((val, sub))
    else:
        pieces.append((None, src))
    out = []
    for val, sub in pieces:
        P = np.asarray(sub.get(POINT, "P"), np.float64)
        lo, hi = P.min(0), P.max(0)
        out.append((val, sub, (lo[2], hi[2]), (lo + hi) * 0.5))
    return out


def copy_to_curves(source, curves, group="", mode="count", count=10,
                   spacing=1.0, start_offset=0.0, end_offset=0.0,
                   up=(0, 1, 0), roll=0.0, roll_step=0.0,
                   piece_attribute="", copy_attribute="copynum"):
    """
    Copy along curves: on each curve, points are taken by count (count, both ends included) or spacing (spacing, one every interval
    from the start), orientation = the RMF frame (+Z along the curve, +Y = up), then Copy
    to Points. start / end_offset leave an arc length free at each end. roll_step rotates copy k an extra
    k*roll_step degrees about the tangent. If piece_attribute is given, pieces rotate in turn (copy k uses piece
    k mod piece count); the piece number is written on the target points for Copy to Points to pick.

    k is the copy index **on this curve**, counted from 0 on each curve (same as Chain). Before pcg90 the count ran on across curves:
    the first copy of the second curve continued rotating from the last copy of the first, so adding / deleting a curve changed the
    rotations and piece rotation on every curve after it.
    """
    if mode not in CURVE_COPY_MODES[:2]:
        raise ValueError(f"Mode must be one of {CURVE_COPY_MODES[:2]} (curve_points goes through copy_to_curve_points)")
    if source is None or curves is None or source.npoints == 0:
        return Geometry()
    Pall = np.asarray(curves.get(POINT, "P"), np.float64)
    table = _piece_table(source, piece_attribute)
    pos_l, tan_l, up_l, curve_l, k_l = [], [], [], [], []
    for pi, pts, closed in _cf.curve_prims(curves, group):
        P = Pall[pts]
        T, U, _ = _cf.curve_frames(P, closed, up=up)
        Q = np.vstack([P, P[:1]]) if closed else P
        L = float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())
        a, b = float(start_offset), L - float(end_offset)
        if b < a:
            continue
        if mode == "count":
            c = int(count)
            if c <= 0:
                continue
            if closed and a == 0 and b == L:
                d = np.arange(c) * (L / c)            # closed: don't repeat at the start
            else:
                d = np.linspace(a, b, c) if c > 1 else np.array([(a + b) / 2])
        else:
            sp = float(spacing)
            if not sp > 0:
                raise ValueError("Spacing must be > 0")
            d = np.arange(a, b + 1e-9 * max(L, 1), sp)
            if closed and a == 0 and len(d) > 1 and abs(d[-1] - L) < 1e-9:
                d = d[:-1]
        pos, tan, u2, _ = _sample(P, closed, T, U, d)
        pos_l.append(pos); tan_l.append(tan); up_l.append(u2)
        curve_l.append(np.full(len(d), pi, np.int64))
        k_l.append(np.arange(len(d)))
    if not pos_l:
        return Geometry()
    pos = np.vstack(pos_l); tan = np.vstack(tan_l); upv = np.vstack(up_l)
    k = np.concatenate(k_l)
    ang = math.radians(float(roll)) + math.radians(float(roll_step)) * k
    upv = _roll(tan, upv, ang)
    M = _cf.frame_matrices(tan, upv)
    extra = {"curvenum": np.concatenate(curve_l)[:, None].astype(np.int32)}
    name = str(piece_attribute).strip()
    if name:
        vals = [t[0] for t in table]
        pick = [vals[i % len(vals)] for i in k]
        extra[name] = (np.array([str(v) for v in pick])[:, None]
                       if any(isinstance(v, str) for v in vals)
                       else np.array(pick, np.float64)[:, None])
    tgt = _targets(pos, orient=_cf.mat_to_quat(M), extra=extra)
    out = _cp.copy_to_points(source, tgt, piece_attrib=name,
                             target_attribs="curvenum")
    return _set_copy_attr(out, copy_attribute)


# ─────────────────────────────── pcg100: Copy to Curves with Houdini semantics (copy onto the curve's existing points)
CTC_TANGENTS = ("average", "central_difference", "previous", "next", "z_axis")
CTC_UP = ("curve_normal", "y_axis", "attribute", "custom")
CTC_PER = ("per_edge", "per_unit_distance", "scale_by_attribute", "full_curve_by_edges",
           "full_curve_by_distance")
# In which order the three extra rotations apply (listed first rotates first); the docs don't give the menu's full options and default, see notes
CTC_ROT_ORDERS = ("pyr", "pry", "ypr", "yrp", "rpy", "ryp")


def _ctc_tangents(P, closed, kind, extrapolate):
    n = len(P)
    if kind == "z_axis":
        return np.tile([0.0, 0.0, 1.0], (n, 1))
    if kind == "central_difference":
        e, _, _ = _cf._edges(P, closed)               # sum of the un-normalized previous and next edges
        if closed:
            prev, nxt = np.roll(e, 1, axis=0), e
        else:
            prev, nxt = np.vstack([e[:1], e]), np.vstack([e, e[-1:]])
        s = prev + nxt
        bad = np.linalg.norm(s, axis=1) < 1e-12
        s[bad] = nxt[bad]
        T = _cf._unit(s)
    else:
        T = _cf.curve_tangents(P, closed, kind)
    if extrapolate and not closed and n >= 3 and kind in ("average", "central_difference"):
        # End tangent = the second point's tangent mirrored about the first edge: exact for circular arcs (tangents at both ends of a chord are symmetric about it)
        for i0, i1 in ((0, 1), (n - 1, n - 2)):
            e = _cf._unit(P[i1] - P[i0])
            if np.linalg.norm(P[i1] - P[i0]) > 1e-12:
                t1 = T[i1]
                T[i0] = _cf._unit(2.0 * float(t1 @ e) * e - t1)
    return T


def _ctc_per(kind, val, s, L, n, closed, attr):
    """How the extra angle (degrees) is distributed along the curve: Per Edge / Per Unit Distance / Scale by Attribute / full curve by edge / full curve by length."""
    i = np.arange(n, dtype=np.float64)
    nedge = n if closed else max(n - 1, 1)
    if kind == "per_edge":
        return val * i
    if kind == "per_unit_distance":
        return val * s
    if kind == "scale_by_attribute":
        return val * (attr if attr is not None else np.zeros(n))
    if kind == "full_curve_by_edges":
        return val * i / nedge
    return val * (s / L if L > 1e-12 else np.zeros(n))


def _axis_rot(axis, ang):
    """(n,3,3) rotation by ang radians about a local axis (0 = X outward, 1 = Y up, 2 = Z tangent)."""
    c, s = np.cos(ang), np.sin(ang)
    n = len(ang)
    R = np.tile(np.eye(3), (n, 1, 1))
    a, b = [(1, 2), (2, 0), (0, 1)][axis]
    R[:, a, a], R[:, a, b], R[:, b, a], R[:, b, b] = c, -s, s, c
    return R


def _ramp_attr(curves, name, pi, pts):
    """Attribute used by Scale by Attribute: point / prim / detail all accepted; returns one number per curve point."""
    name = str(name).strip()
    if not name:
        return None
    for cls in (POINT, PRIM, DETAIL):
        v = curves.get(cls, name)
        if v is None or is_string(v):
            continue
        v = np.asarray(v, np.float64)[:, 0]
        if cls == POINT:
            return v[pts]
        if cls == PRIM:
            return np.full(len(pts), v[pi])
        return np.full(len(pts), v[0])
    return None


def _up_target(curves, pi, P, closed, kind, custom, attr):
    if kind == "y_axis":
        return np.array([0.0, 1.0, 0.0])
    if kind == "custom":
        return np.asarray(custom, np.float64).reshape(3)
    if kind == "attribute":
        for cls in (PRIM, DETAIL):
            v = curves.get(cls, str(attr).strip()) if str(attr).strip() else None
            if v is not None and not is_string(v) and v.shape[1] == 3:
                return np.asarray(v, np.float64)[pi if cls == PRIM else 0]
        return np.array([0.0, 1.0, 0.0])               # no such attribute: use the Y axis
    # curve_normal: Newell normal (open curves are also computed as if closed end to start). Straight lines (normal ~ 0) fall back to the Y axis.
    # Threshold: points are stored as float32 (relative precision ~1e-7; far from the origin the absolute error grows with coordinate size),
    # so even collinear points produce an "area" on the order of precision * coordinate size * curve size
    n = np.cross(P, np.roll(P, -1, axis=0)).sum(0)
    ln = float(np.linalg.norm(n))
    diag = float(np.linalg.norm(np.ptp(P, axis=0)))
    return n / ln if ln > 1e-5 * max(diag, float(np.abs(P).max())) * diag else np.array([0.0, 1.0, 0.0])


def copy_to_curve_points(source, curves, group="", source_group="", source_group_type="guess",
                         piece_attribute="", copy_attribute="copynum", tangent_type="average",
                         closed_continuous=True, extrapolate_ends=False, use_point_attribs=False,
                         target_up="curve_normal", up_at_start=True, use_end_up=False,
                         start_up_attrib="start_up", end_up_attrib="end_up", start_up=(0, 1, 0),
                         end_up=(0, 1, 0), rotate_order="pyr",
                         apply_roll=False, roll=0.0, twist_per="per_edge", full_twists=0, partial_twist=0.0,
                         twist_ramp="", apply_yaw=False, yaw=0.0, yaw_per="per_edge", inc_yaw=0.0,
                         yaw_ramp="", apply_pitch=False, pitch=0.0, pitch_per="per_edge", inc_pitch=0.0,
                         pitch_ramp="", normalize_scales=False, uniform_scale=1.0,
                         stretch_turns=False, max_stretch=10.0, target_attribs=""):
    """
    Houdini's Copy to Curves: copies the source onto **every existing point** of each curve (no resampling).
    Frame: tangent (Tangent Type) + up (target up vector, carried along the curve by RMF; on closed curves the extra twist from going around once is spread out),
    then extra rotations in the curve frame (Roll/Twist about the tangent, Yaw about up, Pitch about outward), then scaling and stretching at turns.
    The result is written as the target points' transform and handed to Copy to Points. Returns geometry.
    """
    for v, ok, nm in ((tangent_type, CTC_TANGENTS, "Tangent Type"), (target_up, CTC_UP, "Target Up Vector"),
                      (twist_per, CTC_PER, "Twist Per"), (yaw_per, CTC_PER, "Yaw Per"),
                      (pitch_per, CTC_PER, "Pitch Per"), (rotate_order, CTC_ROT_ORDERS, "Rotate Order")):
        if v not in ok:
            raise ValueError(f"{nm} must be one of {ok}")
    if source is None or curves is None or source.npoints == 0:
        return Geometry()
    src = _ctc_source(source, source_group, source_group_type)
    if src.npoints == 0:
        return Geometry()
    Pall = np.asarray(curves.get(POINT, "P"), np.float64)
    name = str(piece_attribute).strip()
    table = _piece_table(src, name)
    pos_l, M_l, curve_l, k_l, pidx_l = [], [], [], [], []
    for pi, pts, closed in _cf.curve_prims(curves, group):
        P = Pall[pts]
        n = len(P)
        Q = np.vstack([P, P[:1]]) if closed else P
        seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        L = float(s[-1])
        s = s[:n]
        u = s / L if L > 1e-12 else np.zeros(n)
        T = _ctc_tangents(P, closed, tangent_type, extrapolate_ends)
        if use_point_attribs and curves.get(POINT, "N") is not None:
            T = _cf._unit(np.asarray(curves.get(POINT, "N"), np.float64)[pts])
        up0 = _up_target(curves, pi, P, closed, target_up, start_up, start_up_attrib)
        r0 = _cf._perp(up0, T[0])
        r0 = r0 if r0 is not None else _cf._any_perp(T[0])
        U = _cf.rmf_double_reflection(P, T, r0)
        if closed and closed_continuous and n >= 3:
            wrap = _cf.rmf_double_reflection(np.vstack([P[-1:], P[:1]]),
                                             np.vstack([T[-1:], T[:1]]), U[-1])[1]
            phi = _cf._signed_angle(wrap, U[0], T[0])
            U = _cf._unit(_cf._rotate_about(U, T, phi * u))
        if not up_at_start:
            # Rotate the whole curve's up about the tangent by one common angle, so the angle between each point's up and the target averages to 0 (circular mean)
            a = np.array([_cf._signed_angle(U[i], _cf._perp(up0, T[i]), T[i])
                          if _cf._perp(up0, T[i]) is not None else 0.0 for i in range(n)])
            U = _cf._unit(_cf._rotate_about(U, T, np.full(n, math.atan2(np.sin(a).mean(), np.cos(a).mean()))))
        elif use_end_up:
            up1 = _up_target(curves, pi, P, closed, target_up, end_up, end_up_attrib) \
                if target_up in ("attribute", "custom") else up0
            q = _cf._perp(up1, T[-1])
            if q is not None:
                phi = _cf._signed_angle(U[-1], q, T[-1])
                U = _cf._unit(_cf._rotate_about(U, T, phi * (s / s[-1] if s[-1] > 1e-12 else np.zeros(n))))
        if use_point_attribs and curves.get(POINT, "up") is not None:
            ua = np.asarray(curves.get(POINT, "up"), np.float64)[pts]
            for i in range(n):
                q = _cf._perp(ua[i], T[i])
                if q is not None:
                    U[i] = q
        F = _cf.frame_matrices(T, U)
        if use_point_attribs and curves.get(POINT, "orient") is not None:
            from .xform import quat_to_mat
            F = quat_to_mat(np.asarray(curves.get(POINT, "orient"), np.float64)[pts])
        # Extra rotations (in the curve frame: Roll about the Z tangent, Yaw about the Y up, Pitch about the X outward)
        tw = 360.0 * float(full_twists) + float(partial_twist)
        if closed and closed_continuous and twist_per != "scale_by_attribute":
            # Docs: on closed curves a twist short of a full turn is rounded to full turns (so start and end join up)
            tot = {"per_edge": tw * n, "per_unit_distance": tw * L}.get(twist_per, tw)   # total twist around one loop
            tot_r = 360.0 * round(tot / 360.0)
            tw = tw * (tot_r / tot) if abs(tot) > 1e-12 else 0.0
        rot = {}
        rot["r"] = (math.radians(float(roll)) + np.radians(_ctc_per(
            twist_per, tw, s, L, n, closed, _ramp_attr(curves, twist_ramp, pi, pts)))) if apply_roll else None
        rot["y"] = (math.radians(float(yaw)) + np.radians(_ctc_per(
            yaw_per, float(inc_yaw), s, L, n, closed, _ramp_attr(curves, yaw_ramp, pi, pts)))) if apply_yaw else None
        rot["p"] = (math.radians(float(pitch)) + np.radians(_ctc_per(
            pitch_per, float(inc_pitch), s, L, n, closed, _ramp_attr(curves, pitch_ramp, pi, pts)))) \
            if apply_pitch else None
        R = np.tile(np.eye(3), (n, 1, 1))
        for c in rotate_order:                         # listed first rotates first: R = R_last ... R_first
            if rot[c] is None:
                continue
            ang = np.broadcast_to(np.asarray(rot[c], np.float64), (n,))
            R = _axis_rot({"p": 0, "y": 1, "r": 2}[c], ang) @ R
        M = F @ R
        if use_point_attribs and curves.get(POINT, "rot") is not None:
            from .xform import quat_to_mat
            M = M @ quat_to_mat(np.asarray(curves.get(POINT, "rot"), np.float64)[pts])
        sc = np.ones((n, 3))
        if use_point_attribs and not normalize_scales:
            for nm_, dim in (("scale", 3), ("pscale", 1)):
                v = curves.get(POINT, nm_)
                if v is not None and v.shape[1] == dim:
                    sc = sc * np.asarray(v, np.float64)[pts]
        M = M * (sc * float(uniform_scale))[:, None, :]
        if stretch_turns and n >= 3:
            # At turns, stretch by 1/cos(theta/2) along the "miter direction" (difference of the unit vectors of the previous and next edges, perpendicular to the average tangent in the turn plane)
            e = _cf._unit(np.diff(Q, axis=0))
            if closed:
                ein, eout = np.roll(e, 1, axis=0), e
                idx = np.arange(n)
            else:
                ein, eout = e[:-1], e[1:]
                idx = np.arange(1, n - 1)
            c = np.clip(np.einsum("ij,ij->i", ein, eout), -1.0, 1.0)
            half = np.sqrt(np.maximum((1.0 + c) / 2.0, 0.0))              # cos(θ/2)
            k = np.minimum(1.0 / np.maximum(half, 1e-12), max(float(max_stretch), 1.0))
            m = _cf._unit(eout - ein)                  # on straight parts m = 0, k = 1: S is the identity
            S = np.tile(np.eye(3), (len(idx), 1, 1)) + (k - 1.0)[:, None, None] * np.einsum("ni,nj->nij", m, m)
            M[idx] = S @ M[idx]
        if use_point_attribs and curves.get(POINT, "transform") is not None \
                and curves.get(POINT, "transform").shape[1] == 9:
            M = np.transpose(np.asarray(curves.get(POINT, "transform"), np.float64)[pts]
                             .reshape(n, 3, 3), (0, 2, 1))     # row-vector convention -> column vectors
        pos_l.append(P)
        M_l.append(M)
        curve_l.append(np.full(n, pi, np.int64))
        k_l.append(np.arange(n))
        pidx_l.append(pts)
    if not pos_l:
        return Geometry()
    pos = np.vstack(pos_l)
    M = np.vstack(M_l)
    k = np.concatenate(k_l)
    pidx = np.concatenate(pidx_l)
    extra = {"curvenum": np.concatenate(curve_l)[:, None].astype(np.int32)}
    if use_point_attribs:
        for nm_ in ("trans", "pivot"):
            v = curves.get(POINT, nm_)
            if v is not None and v.shape[1] == 3:
                extra[nm_] = np.asarray(v, np.float64)[pidx].astype(np.float32)
    from .ops import match_names
    tnames = [a for a in match_names(list(curves.attribs[POINT]), target_attribs)
              if a not in ("P", "curvenum") and a not in extra and a != name]
    for a in tnames:
        extra[a] = np.asarray(curves.attribs[POINT][a])[pidx]
    if name:
        own = curves.get(POINT, name)
        if own is not None:
            # Docs: Piece Attribute is an attribute on the **target points**, paired with the source's piece attribute
            extra[name] = np.asarray(own)[pidx]
        else:
            vals = [t[0] for t in table]
            pick = [vals[i % len(vals)] for i in k]
            extra[name] = (np.array([str(v) for v in pick])[:, None]
                           if any(isinstance(v, str) for v in vals)
                           else np.array(pick, np.float64)[:, None])
    tgt = _targets(pos, M=M, extra=extra)
    out = _cp.copy_to_points(src, tgt, piece_attrib=name,
                             target_attribs=" ".join(["curvenum"] + tnames))
    return _set_copy_attr(out, copy_attribute)


CTC_SOURCE_GROUP_TYPES = ("guess", "prim", "point")


def _ctc_source(src, group, kind):
    """Source Group: with Guess, use prim if a prim group of that name exists, otherwise points (if neither, parse as prim, consistent with the docs)."""
    g = str(group).strip()
    if not g:
        return src
    if kind == "guess":
        kind = "point" if (g in src.groups[POINT] and g not in src.groups[PRIM]) else "prim"
    if kind == "prim" and src.nprims:
        return delete_prims(src, resolve(src, PRIM, g))
    return delete_points(src, resolve(src, POINT, g))


def chain(source, curves, group="", spacing=0.0, fit=True, roll=0.0,
          roll_step=90.0, up=(0, 1, 0), piece_attribute="",
          copy_attribute="copynum"):
    """
    Counterpart of Houdini's Chain: links placed one after another along the curve. The difference from Copy to Curves is that **how long each
    link is is decided by the link itself** (its bounding box length along local Z) + spacing (negative = links interpenetrate,
    which is how chain links work). The centre of link k sits at the midpoint of the chord over arc length [a_k, a_k + length],
    with +Z along the chord -- on bends both ends of a link land on the curve, instead of poking out along the tangent.
    Adjacent links are rotated an extra roll_step about the chord (chain links default to 90 deg, alternating).

    fit: adds / subtracts a little to spacing uniformly so the last link ends exactly at the curve's end (on closed curves,
    exactly one loop around). Turned off, links are placed until no more fit. Piece rotation is the same as Copy to Curves.
    """
    if source is None or curves is None or source.npoints == 0:
        return Geometry()
    table = _piece_table(source, piece_attribute)
    lens = np.array([max(t[2][1] - t[2][0], 1e-9) for t in table])
    if (lens + float(spacing)).min() <= 1e-9:
        # With a step <= 0 the links spin in place, never fill the curve and never stop (the first demo version ate all the
        # memory this way). Say clearly which number is wrong
        raise ValueError(
            f"Spacing = {float(spacing):g} is too negative: each link advances length + spacing, "
            f"the shortest link is {lens.min():.4g} long, and the step must be > 0. A link's 'length' is its "
            "bounding box along local Z -- chain links must first be laid out along Z")
    Pall = np.asarray(curves.get(POINT, "P"), np.float64)
    pos_l, M_l, piv_l, pick_l, curve_l = [], [], [], [], []
    for pi, pts, closed in _cf.curve_prims(curves, group):
        P = Pall[pts]
        T, U, _ = _cf.curve_frames(P, closed, up=up)
        Q = np.vstack([P, P[:1]]) if closed else P
        L = float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())
        sp = float(spacing)
        # How many links fit: accumulate with piece rotation until no more fit
        starts, which = [], []
        a, k = 0.0, 0
        while True:
            ln = lens[k % len(lens)]
            if a + ln > L + 1e-9:
                break
            if k >= MAX_LINKS:
                raise ValueError(f"More than {MAX_LINKS} links on one curve -- links too short or "
                                 "curve too long, check the units")
            starts.append(a)
            which.append(k % len(lens))
            a += ln + sp
            k += 1
        if not starts:
            continue
        starts = np.array(starts)
        which = np.array(which)
        if fit and len(starts) > 0:
            used = lens[which].sum()
            gaps = len(starts) if closed else len(starts) - 1
            if gaps > 0:
                sp2 = (L - used) / gaps
                starts = np.concatenate([[0.0], np.cumsum(lens[which] + sp2)[:-1]])
        a_pos, _, _, _ = _sample(P, closed, T, U, starts)
        b_pos, _, _, _ = _sample(P, closed, T, U,
                                 np.minimum(starts + lens[which], L))
        chord = _cf._unit(b_pos - a_pos)
        mid = (a_pos + b_pos) * 0.5
        _, _, upm, _ = _sample(P, closed, T, U, starts + lens[which] * 0.5)
        upm = _cf._unit(upm - chord * np.einsum("ij,ij->i", upm, chord)[:, None])
        kk = np.arange(len(starts))
        upm = _roll(chord, upm,
                    math.radians(float(roll)) + math.radians(float(roll_step)) * kk)
        pos_l.append(mid)
        M_l.append(_cf.frame_matrices(chord, upm))
        piv_l.append(np.array([table[w][3] for w in which]))
        pick_l.append(which)
        curve_l.append(np.full(len(starts), pi, np.int64))
    if not pos_l:
        return Geometry()
    pos = np.vstack(pos_l)
    M = np.vstack(M_l)
    extra = {"pivot": np.vstack(piv_l).astype(np.float32),
             "curvenum": np.concatenate(curve_l)[:, None].astype(np.int32)}
    name = str(piece_attribute).strip()
    which = np.concatenate(pick_l)
    if name:
        vals = [t[0] for t in table]
        pick = [vals[i] for i in which]
        extra[name] = (np.array([str(v) for v in pick])[:, None]
                       if any(isinstance(v, str) for v in vals)
                       else np.array(pick, np.float64)[:, None])
    tgt = _targets(pos, orient=_cf.mat_to_quat(M), extra=extra)
    out = _cp.copy_to_points(source, tgt, piece_attrib=name,
                             target_attribs="curvenum")
    return _set_copy_attr(out, copy_attribute)
