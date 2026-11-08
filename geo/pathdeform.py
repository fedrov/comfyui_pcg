"""
Path Deform SOP (pcg121): bends geometry along a curve.

One axis of the input (the *deform axis*, default +Z) is laid along the curve: a point's coordinate on that axis becomes
an arc length s, the other two coordinates become offsets in the curve's frame at s. The frame is the rotation-
minimising frame of curveframe.curve_frames (the same as Orient Along Curve / Sweep), so long shapes do not twist
unless asked to (Roll / Twist).

  Stretch to Curve   the input's extent along the axis is mapped onto the whole curve (min -> start, max -> end);
                     off: the axis coordinate is the arc length itself (scaled by Scale), starting at Offset
  Offset             slides the shape along the curve (world units, or a fraction of the length with Offset as
                     Fraction)
  past the ends      the shape continues straight along the end tangents (rigid extension, like Houdini), so nothing
                     collapses onto the end point

Frames are interpolated between curve points (position linearly, the frame axes linearly then re-orthonormalised),
so a coarse curve gives a faceted bend: resample the curve for smoothness. Normals / up / v rotate with the frame.
"""
from __future__ import annotations

import numpy as np

from .core import POINT
from .groups import resolve

AXES = ("+z", "-z", "+x", "-x", "+y", "-y")
UP_MODES = ("minimal_rotation", "constant")


def _axis_basis(axis):
    """(along, side, up) unit vectors in the input's space for the deform axis; right-handed."""
    sign = -1.0 if axis.startswith("-") else 1.0
    a = "xyz".index(axis[-1])
    b, c = (a + 1) % 3, (a + 2) % 3
    E = np.eye(3)
    return sign * E[a], sign * E[b], E[c]


def _frames_at(s, S, P, X, Y, T):
    """Position and frame (X side, Y up, T tangent) at arc lengths s; straight extension past the ends."""
    L = S[-1]
    i = np.clip(np.searchsorted(S, s, side="right") - 1, 0, len(S) - 2)
    seg = np.maximum(S[i + 1] - S[i], 1e-30)
    w = np.clip((s - S[i]) / seg, 0.0, 1.0)[:, None]
    pos = P[i] * (1 - w) + P[i + 1] * w
    t = T[i] * (1 - w) + T[i + 1] * w
    u = Y[i] * (1 - w) + Y[i + 1] * w
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-30)
    x = np.cross(u, t)
    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-30)
    u = np.cross(t, x)
    lo, hi = s < 0, s > L
    pos[lo] = P[0] + s[lo, None] * T[0]
    pos[hi] = P[-1] + (s[hi] - L)[:, None] * T[-1]
    for m, k in ((lo, 0), (hi, -1)):
        t[m], x[m], u[m] = T[k], X[k], Y[k]
    return pos, x, u, t


def path_deform(geo, curve, group="", curve_group="", axis="+z", stretch=True, offset=0.0, offset_fraction=False,
                scale=1.0, roll=0.0, twist=0.0, up_mode="minimal_rotation", up=(0.0, 1.0, 0.0), cross_scale=1.0):
    """Returns (geometry, report)."""
    from .curveframe import curve_prims, curve_frames
    if axis not in AXES:
        raise ValueError(f"Deform Axis must be one of {AXES}")
    if up_mode not in UP_MODES:
        raise ValueError(f"Up Mode must be one of {UP_MODES}")
    if curve is None:
        raise ValueError("Path Deform needs a curve (second input)")
    cs = curve_prims(curve, curve_group)
    if not cs:
        raise ValueError("The curve input has no curve (an open or closed polyline with at least two points)")
    _, ids, closed = cs[0]
    CP = np.asarray(curve.get(POINT, "P"), np.float64)[ids]
    if closed:
        CP = np.vstack([CP, CP[:1]])
    T, U, _ = curve_frames(CP, False, up_mode=up_mode, up=up, roll=roll)
    seg = np.linalg.norm(np.diff(CP, axis=0), axis=1)
    S = np.concatenate([[0.0], np.cumsum(seg)])
    L = float(S[-1])
    if L <= 0:
        raise ValueError("The curve has zero length")
    X = np.cross(U, T)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-30)

    out = geo.copy()
    sel = resolve(geo, POINT, group)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    ea, eb, ec = _axis_basis(axis)
    pa, pb, pc = P @ ea, P @ eb, P @ ec
    if stretch:
        lo, hi = float(pa[sel].min()), float(pa[sel].max())
        span = hi - lo if hi > lo else 1.0
        s = (pa - lo) / span * L * float(scale)
    else:
        s = pa * float(scale)
    s = s + (float(offset) * L if offset_fraction else float(offset))
    pos, x, u, t = _frames_at(s, S, CP, X, U, T)
    if twist:
        ang = np.radians(float(twist)) * np.clip(s / L, 0.0, 1.0)
        c, sn = np.cos(ang)[:, None], np.sin(ang)[:, None]
        x, u = x * c + u * sn, u * c - x * sn
    k = float(cross_scale)
    newP = pos + x * (pb * k)[:, None] + u * (pc * k)[:, None]
    Pw = np.where(sel[:, None], newP, P)
    out.set(POINT, "P", Pw.astype(np.float32), owned=True)
    # direction attributes: express in (side, up, along) of the input, re-express in the curve frame
    for name in ("N", "up", "v"):
        a = geo.get(POINT, name)
        if a is None or a.shape[1] != 3:
            continue
        a64 = np.asarray(a, np.float64)
        w = (x * (a64 @ eb)[:, None] + u * (a64 @ ec)[:, None] + t * (a64 @ ea)[:, None])
        if name != "v":
            w /= np.maximum(np.linalg.norm(w, axis=1, keepdims=True), 1e-30)
        out.set(POINT, name, np.where(sel[:, None], w, a64).astype(a.dtype), owned=True)
    rep = {"points": int(sel.sum()), "curve_length": L,
           "beyond_ends": int(((s < 0) | (s > L))[sel].sum())}
    return out, rep
