"""
UV Shape (pcg100 c4, against SideFX Copernicus UV Shape): generates **parametric coordinates** for a shape.

Not the same thing as COP Shape (SDF): SDF Shape answers "how far is this pixel from the shape", UV Shape answers
"where is this pixel in the shape's **internal coordinate system**". Feed the output into UV Sample to map a square image
into a disk / ring. So per rule [C] it is a separate node (PCG_COPUVShape), and COP Shape is left untouched.

Coordinate convention (same as COP Shape): centred, normalized by the **short side**, short side [−0.5, 0.5]. Radius
is measured in these coordinates, so a disk of 0.5 is inscribed in the short side.

UV value range: the Houdini docs say "sampled UVs are generally between −1 and 1". By default we follow that and output [−1, 1]
(`uv_range = signed`); our own UV Sample takes 0~1, so there is an extra `unit` option
= (uv + 1) / 2. Border is applied in [−1, 1] before the conversion.

Shapes and mappings implemented (the docs have one sentence each; the formulas are the standard ones matching the names, see each function):
  disk     linear / polar / equal_area / squircle / elliptic_arc
  annulus  polar / log
Not implemented: disk conformal (Schwarz–Christoffel, needs elliptic functions), square (2-fold / 4-fold
folding and Vertex orientation are unclear in the docs), horseshoe, spiral, fishscale. See audit_notes.
"""
from __future__ import annotations

import numpy as np

from .pattern import _base
from .pixel import put, _vec

SHAPES = ("disk", "annulus")
DISK_MODES = ("linear", "polar", "equal_area", "squircle", "elliptic_arc")
ANNULUS_MODES = ("polar", "log")
BORDERS = ("clamp", "mirror", "wrap", "extend")
RANGES = ("signed", "unit")


def _coords(W, H):
    """Centred pixel-centre coordinates, normalized by the short side (consistent with generate.aspect_coords, float64)."""
    s = float(min(W, H))
    x = ((np.arange(W, dtype=np.float64) + 0.5) / W - 0.5) * (W / s)
    y = ((np.arange(H, dtype=np.float64) + 0.5) / H - 0.5) * (H / s)
    X, Y = np.meshgrid(x, y)
    return X, Y


# ═══════════════════════════════════════════════════════ disk → square [−1,1]²
def disk_linear(x, y):
    """
    Linear: radial stretch (Fong's Simple Stretching). Concentric circles → concentric squares; a circle of radius r
    maps to a square of "half side r". Cheap, but stretching is greatest along the diagonals (docs, verbatim).
    """
    r = np.hypot(x, y)
    ax, ay = np.abs(x), np.abs(y)
    big = np.maximum(ax, ay)
    k = r / np.where(big > 0, big, 1.0)           # at the origin r = 0, so k doesn't matter (result is 0)
    return x * k, y * k


def disk_polar(x, y):
    """Polar: U = angle / π (−1..1, +x direction is 0), V = 2r − 1 (centre −1, circumference +1)."""
    return np.arctan2(y, x) / np.pi, 2.0 * np.hypot(x, y) - 1.0


def disk_equal_area(x, y):
    """
    Equal Area: inverse of the Shirley–Chiu concentric mapping. Area-preserving -- the Jacobian determinant is
    4/π everywhere (square area 4 over disk area π); tests verify this.
    """
    r = np.hypot(x, y)
    ax, ay = np.abs(x), np.abs(y)
    k = 4.0 / np.pi
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(ax > 0, np.arctan(ay / np.where(ax > 0, ax, 1.0)), 0.0)
        ty = np.where(ay > 0, np.arctan(ax / np.where(ay > 0, ay, 1.0)), 0.0)
    xdom = ax >= ay
    u = np.where(xdom, r, r * k * ty)
    v = np.where(xdom, r * k * tx, r)
    return np.sign(x) * u, np.sign(y) * v


def disk_squircle(x, y):
    """
    Squircle: Fong's FG-squircular mapping (circle → square; concentric circles map to the Fernández-Guasti
    squircle family). Almost no distortion near the axes, consistent with the docs' "stable distortion near the axes".
    When x or y is 0 the formula is 0/0; take the limit u = x, v = y.
    """
    w = x * x + y * y
    with np.errstate(divide="ignore", invalid="ignore"):
        inner = np.maximum(w * (w - 4.0 * x * x * y * y), 0.0)
        root = np.sqrt(np.maximum(w - np.sqrt(inner), 0.0))
        s = np.sign(x * y) / np.sqrt(2.0)
        axis = (np.abs(x) < 1e-12) | (np.abs(y) < 1e-12)
        u = np.where(axis, x, s * root / np.where(axis, 1.0, y))
        v = np.where(axis, y, s * root / np.where(axis, 1.0, x))
    return u, v


def disk_elliptic_arc(x, y):
    """
    Elliptic Arc: Fong's Elliptical Grid mapping (horizontal / vertical grid lines map to a family of elliptic arcs in the disk).
    The docs only say "elliptic-arc grid mapping"; interpreted this way.

        u = ½√(2 + x² − y² + 2√2·x) − ½√(2 + x² − y² − 2√2·x), v likewise (x and y swapped)
    """
    t = 2.0 * np.sqrt(2.0)
    a = 2.0 + x * x - y * y
    b = 2.0 - x * x + y * y
    u = 0.5 * np.sqrt(np.maximum(a + t * x, 0.0)) \
        - 0.5 * np.sqrt(np.maximum(a - t * x, 0.0))
    v = 0.5 * np.sqrt(np.maximum(b + t * y, 0.0)) \
        - 0.5 * np.sqrt(np.maximum(b - t * y, 0.0))
    return u, v


_DISK = {"linear": disk_linear, "polar": disk_polar,
         "equal_area": disk_equal_area, "squircle": disk_squircle,
         "elliptic_arc": disk_elliptic_arc}


def annulus_uv(x, y, inner, outer, mode):
    """
    U = angle / π; V maps [inner radius, outer radius] to [−1, 1]: polar linear, log by ln(r / inner radius)
    (log mode is conformal: the local du : dv ratio is the same at every radius, so mapped cells don't flatten further out).
    """
    r = np.hypot(x, y)
    u = np.arctan2(y, x) / np.pi
    if mode == "polar":
        v = 2.0 * (r - inner) / (outer - inner) - 1.0
    else:
        with np.errstate(divide="ignore"):
            v = 2.0 * np.log(np.maximum(r, 1e-300) / inner) \
                / np.log(outer / inner) - 1.0
    return u, v


def _raw_uv(x, y, shape, disk_mode, radius, inner, outer, annulus_mode):
    if shape == "disk":
        R = float(radius)
        return _DISK[disk_mode](x / R, y / R)
    return annulus_uv(x, y, inner, outer, annulus_mode)


def _angle_wrap(shape, disk_mode):
    """The modes where U is an angle: U jumps at ±1, so derivatives must take differences modulo period 2."""
    return shape == "annulus" or disk_mode == "polar"


def border(t, mode):
    """What to do outside [−1, 1]: clamp clamps, mirror folds back and forth, wrap has period 2, extend does nothing."""
    if mode == "clamp":
        return np.clip(t, -1.0, 1.0)
    if mode == "wrap":
        return np.mod(t + 1.0, 2.0) - 1.0
    if mode == "mirror":
        m = np.mod(t + 1.0, 4.0)                # period 4: −1→1 forward, 1→−1 backward
        return np.where(m <= 2.0, m, 4.0 - m) - 1.0
    return t


def _xform(u, v, offset, angle, shear, us, vs):
    """
    Transform → scale: first shear u += Shear·v, then rotate about the origin by Angle (degrees), then translate by Offset;
    finally multiply by U / V Scale. The docs put Transform and U/V Scale in two sections without stating the order; here
    Transform comes first.
    """
    if shear:
        u = u + float(shear) * v
    if angle:
        th = np.radians(float(angle))
        c, s = np.cos(th), np.sin(th)
        u, v = u * c - v * s, u * s + v * c
    ox, oy = offset
    return (u + ox) * float(us), (v + oy) * float(vs)


def uv_shape(img=None, shape="disk", disk_mode="linear", radius=0.4,
             annulus_mode="polar", inner_radius=0.2, outer_radius=0.45,
             offset="0 0", angle=0.0, shear=0.0, u_scale=1.0, v_scale=1.0,
             u_border="clamp", v_border="clamp", uv_filter_bound=4.0,
             uv_range="signed", uv_layer="uv", uvscale_layer="uvscale",
             mask_layer="mask", xres=512, yres=512):
    """
    Outputs three layers (empty layer name = not output):
      uv       2 channels, shape-internal coordinates (see uv_range)
      uvscale  1 channel, how fast uv changes per pixel (uv units / pixel, the largest singular value
               of the Jacobian), clamped to UV Filter Bound -- for UV Sample to choose its filter width. The docs
               only say "shows how much the uv is stretched"; the exact quantity is our own; measured in [−1,1] uv,
               unaffected by uv_range
      mask     1 channel, 1 inside the shape, 0 outside (tested at pixel centres, no anti-aliasing; the docs say 1 / 0)
    """
    if shape not in SHAPES:
        raise ValueError(f"Shape must be one of {SHAPES}")
    if disk_mode not in DISK_MODES:
        raise ValueError(f"Disk Mode must be one of {DISK_MODES}")
    if annulus_mode not in ANNULUS_MODES:
        raise ValueError(f"Annulus Mode must be one of {ANNULUS_MODES}")
    for b in (u_border, v_border):
        if b not in BORDERS:
            raise ValueError(f"Border must be one of {BORDERS}")
    if uv_range not in RANGES:
        raise ValueError(f"UV Range must be one of {RANGES}")
    if shape == "disk" and float(radius) <= 0:
        raise ValueError("Radius must be > 0")
    ri, ro = float(inner_radius), float(outer_radius)
    if shape == "annulus" and not (0 < ri < ro):
        raise ValueError("requires 0 < Inner Radius < Outer Radius")

    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    x, y = _coords(W, H)
    off = _vec(offset, 2)
    args = (shape, disk_mode, radius, ri, ro, annulus_mode)

    def full(xx, yy):
        u0, v0 = _raw_uv(xx, yy, *args)
        return _xform(u0, v0, off, angle, shear, u_scale, v_scale)

    u, v = full(x, y)

    if str(uv_layer).strip():
        bu, bv = border(u, u_border), border(v, v_border)
        if uv_range == "unit":
            bu, bv = (bu + 1.0) * 0.5, (bv + 1.0) * 0.5
        put(out, uv_layer, np.stack([bu, bv], -1), like)

    if str(uvscale_layer).strip():
        # central differences, step of half a pixel (coordinate unit = 1 / short-side pixel count)
        h = 0.5 / float(min(W, H))
        ux1, vx1 = full(x + h, y)
        ux0, vx0 = full(x - h, y)
        uy1, vy1 = full(x, y + h)
        uy0, vy0 = full(x, y - h)
        dux, dvx, duy, dvy = ux1 - ux0, vx1 - vx0, uy1 - uy0, vy1 - vy0
        if _angle_wrap(shape, disk_mode):
            # the angle jumps by 2 at ±1 (2·us after U Scale); take the difference modulo that period to the nearest value
            per = 2.0 * abs(float(u_scale)) or 1.0
            dux = dux - per * np.round(dux / per)
            duy = duy - per * np.round(duy / per)
        # per-pixel derivative (the difference spans one pixel), largest singular value of the 2×2 Jacobian
        a, b, c, d = dux, duy, dvx, dvy
        s1 = a * a + b * b + c * c + d * d
        s2 = np.sqrt(np.maximum((a * a + b * b - c * c - d * d) ** 2
                                + 4.0 * (a * c + b * d) ** 2, 0.0))
        sig = np.sqrt(np.maximum(0.5 * (s1 + s2), 0.0))
        put(out, uvscale_layer, np.minimum(sig, float(uv_filter_bound)), like)

    if str(mask_layer).strip():
        r = np.hypot(x, y)
        if shape == "disk":
            m = r <= float(radius)
        else:
            m = (r >= ri) & (r <= ro)
        put(out, mask_layer, m.astype(np.float64), like)
    return out
