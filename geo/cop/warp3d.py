"""
COP's "placement / deformation" batch (pcg100 c6): Sphere Sample, Transform 3D, Align, Align Pixels, Bend.

Many of these Copernicus nodes **edit layer metadata** (the layer's position in the world / camera) and only produce
pixels again at Rasterize. Our CopImage has pixels but no metadata, so here everything **outputs pixels directly**: equivalent to always
following up with a Rasterize Layer in Houdini, with the raster being size_ref (source itself if not connected).

Shared conventions (consistent with coordspace):
  · world = image space: a layer is a rectangle on the z = 0 plane, origin at the image center, long side spanning -1...1
  · the default camera looks along -Z. Orthographic: one parallel ray per pixel; perspective: camera at (0, 0, Camera Distance),
    seeing exactly the image-space patch on the z = 0 plane (our own choice; Houdini's camera comes from layer metadata)
  · pixel coordinates: 0 = center of the first pixel (consistent with transform.resample)

Sampling (Filter): Point / Bilinear / Box / Bartlett / Catmull-Rom / Mitchell / B-spline are done as reconstruction kernels.
We don't do footprint filtering when minifying, so at unit footprint Box (radius 0.5) equals Point and Bartlett (a radius-1
triangle) equals Bilinear -- the two pairs differ only when Houdini enlarges the footprint by uvscale; this is noted in the panel help.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage
from .pixel import getn, put, names_of, _vec

FILTERS = ("point", "bilinear", "box", "bartlett", "catmull_rom", "mitchell",
           "bspline")
SAMPLE_BORDERS = ("constant", "clamp", "mirror", "wrap")
XFORM_BORDERS = ("auto", "constant", "clamp", "mirror", "wrap", "clip")
PROJECTIONS = ("perspective", "orthographic")
_ORTHO_Z = 1e6          # origin of orthographic camera rays (far enough that any reasonable translation is in front of it)


# ═══════════════════════════════════════════════════════ Sampling
def _bc(x, B, C):
    """Mitchell-Netravali BC cubic kernel (B = 0, C = 0.5 is Catmull-Rom; 1/3, 1/3 Mitchell; 1, 0 B-spline)."""
    x = np.abs(x)
    x2, x3 = x * x, x * x * x
    a = ((12 - 9 * B - 6 * C) * x3 + (-18 + 12 * B + 6 * C) * x2 + (6 - 2 * B)) / 6.0
    b = ((-B - 6 * C) * x3 + (6 * B + 30 * C) * x2 + (-12 * B - 48 * C) * x
         + (8 * B + 24 * C)) / 6.0
    return np.where(x < 1, a, np.where(x < 2, b, 0.0))


_CUBIC = {"catmull_rom": (0.0, 0.5), "mitchell": (1 / 3, 1 / 3), "bspline": (1.0, 0.0)}


def _index(i, n, mode):
    """Map integer pixel indices back into [0, n) by border mode; returns (indices, valid)."""
    if mode == "wrap":
        return np.mod(i, n), None
    if mode == "mirror":
        m = np.mod(i, 2 * n)
        return np.where(m < n, m, 2 * n - 1 - m), None
    if mode == "constant":
        ok = (i >= 0) & (i < n)
        return np.clip(i, 0, n - 1), ok
    return np.clip(i, 0, n - 1), None              # clamp


def _taps(x, filt):
    """Taps on one axis: returns [(integer position, weight), ...]."""
    if filt in ("point", "box"):
        return [(np.floor(x + 0.5).astype(np.int64), np.ones_like(x))]
    i0 = np.floor(x).astype(np.int64)
    f = x - i0
    if filt in ("bilinear", "bartlett"):
        return [(i0, 1.0 - f), (i0 + 1, f)]
    B, C = _CUBIC[filt]
    return [(i0 + k, _bc(f - k, B, C)) for k in (-1, 0, 1, 2)]


def fsample(a, x, y, filt="bilinear", bx="clamp", by="clamp"):
    """
    Samples a (H, W, C) at pixel coordinates (x, y) (0 = center of the first pixel), returns (..., C).
    Each axis has its own border mode bx / by (constant pads 0 outside the image).
    """
    if filt not in FILTERS:
        raise ValueError(f"Filter must be one of {FILTERS}")
    H, W = a.shape[:2]
    out = np.zeros(np.shape(x) + (a.shape[2],))
    for iy, wy in _taps(np.asarray(y, np.float64), filt):
        jy, oky = _index(iy, H, by)
        for ix, wx in _taps(np.asarray(x, np.float64), filt):
            jx, okx = _index(ix, W, bx)
            w = wy * wx
            if oky is not None:
                w = w * oky
            if okx is not None:
                w = w * okx
            out += a[jy, jx] * w[..., None]
    return out


# ═══════════════════════════════════════════════════════ Coordinates / camera
def image_coords(W, H):
    """Image-space coordinates (X, Y) of each pixel center of the output raster."""
    L = float(max(W, H))
    x = (np.arange(W, dtype=np.float64) + 0.5 - W / 2.0) * (2.0 / L)
    y = (np.arange(H, dtype=np.float64) + 0.5 - H / 2.0) * (2.0 / L)
    return np.meshgrid(x, y)


def image_to_pixel(x, y, W, H):
    """Image space -> pixel coordinates (0 = center of the first pixel)."""
    L = float(max(W, H))
    return x * (L / 2.0) + W / 2.0 - 0.5, y * (L / 2.0) + H / 2.0 - 0.5


def camera_rays(W, H, projection, distance):
    """Per-pixel rays (origin O (H,W,3), direction D (H,W,3))."""
    X, Y = image_coords(W, H)
    if projection == "orthographic":
        O = np.stack([X, Y, np.full_like(X, _ORTHO_Z)], -1)
        D = np.broadcast_to(np.array([0.0, 0.0, -1.0]), O.shape).copy()
    else:
        d = float(distance)
        if not d > 0:
            raise ValueError("Camera Distance must be > 0")
        O = np.broadcast_to(np.array([0.0, 0.0, d]), X.shape + (3,)).copy()
        D = np.stack([X, Y, np.full_like(X, -d)], -1)
    return O, D


def _xform(translate, rotate, scale, shear, uniform_scale, pivot, pivot_rotate,
           xform_order, rotate_order, invert=False):
    """Houdini Transform's 4x4 (row vectors, p' = [p, 1] @ M), using SOP Transform's directly."""
    from ..ops import xform_matrix
    return xform_matrix(_vec(translate, 3), _vec(rotate, 3), _vec(scale, 3),
                        _vec(shear, 3), float(uniform_scale), _vec(pivot, 3),
                        _vec(pivot_rotate, 3), xform_order, rotate_order, invert)


def _to_object(O, D, M):
    """Move world rays into object space (multiply by M⁻¹; directions without translation)."""
    Mi = np.linalg.inv(M)
    o = O @ Mi[:3, :3] + Mi[3, :3]
    d = D @ Mi[:3, :3]
    return o, d


def _src_layers(src, layers):
    return [(n, getn(src, n)) for n in names_of(src, layers)]


# ═══════════════════════════════════════════════════════ Sphere Sample
def sphere_sample(size_ref=None, source=None, source_layer="C", filt="bilinear",
                  xform_order="srt", rotate_order="xyz", celestial=False,
                  projection="perspective", translate="0 0 0", rotate="0 0 0",
                  scale="1 1 1", uniform_scale=1.0, camera_distance=2.0,
                  out_layer="transform", mask_layer="mask", xres=512, yres=512):
    """
    Houdini's Sphere Sample: maps source as a lat-long image onto a sphere and looks at it.
      celestial = on   an infinitely distant celestial sphere: the ray direction (affected only by Rotate) looks up the lat-long image directly, mask all 1
      celestial = off  a transformable unit sphere (Translate / Rotate / Scale / Uniform Scale, by Transform
                       Order / Rotate Order); the direction of the hit point looks up the image; mask = hit
    The lat-long convention follows the plugin's UV Sample latlong mode (Y up, +X at u = 0.5); Houdini's docs don't state its convention.
    Celestial + orthographic: all rays point the same way, so the whole image is one color -- a direct consequence of the definition, not a bug.
    """
    from .pattern import _base
    from .uvx import _dir_to_latlong
    if source is None:
        raise ValueError("Sphere Sample needs source (a lat-long image) connected")
    if projection not in PROJECTIONS:
        raise ValueError(f"Projection must be one of {PROJECTIONS}")
    out, like = _base(size_ref, xres, yres)
    W, H = out.xres, out.yres
    O, D = camera_rays(W, H, projection, camera_distance)
    if celestial:
        R = _xform("0 0 0", rotate, "1 1 1", "0 0 0", 1.0, "0 0 0", "0 0 0",
                   xform_order, rotate_order)
        _, d = _to_object(O, D, R)
        dirs, hit = d, np.ones((H, W), bool)
    else:
        M = _xform(translate, rotate, scale, "0 0 0", uniform_scale, "0 0 0",
                   "0 0 0", xform_order, rotate_order)
        if abs(np.linalg.det(M[:3, :3])) < 1e-300:
            raise ValueError("Scale can't contain 0")
        o, d = _to_object(O, D, M)
        a = np.einsum("...i,...i", d, d)
        b = 2.0 * np.einsum("...i,...i", o, d)
        c = np.einsum("...i,...i", o, o) - 1.0
        disc = b * b - 4 * a * c
        sq = np.sqrt(np.maximum(disc, 0.0))
        t0 = (-b - sq) / (2 * a)
        t1 = (-b + sq) / (2 * a)
        t = np.where(t0 > 0, t0, t1)               # when the camera is inside the sphere, take the far intersection
        hit = (disc >= 0) & (t > 0)
        dirs = o + t[..., None] * d
    u, v = _dir_to_latlong(dirs)
    a_ = getn(source, source_layer)
    sh, sw = a_.shape[:2]
    # lat-long: u wraps around, v is clamped at the poles
    r = fsample(a_, u * sw - 0.5, v * sh - 0.5, filt, "wrap", "clamp")
    put(out, str(out_layer).strip() or "transform",
        np.where(hit[..., None], r, 0.0), like)
    if str(mask_layer).strip():
        put(out, mask_layer, hit.astype(np.float64), like)
    return out


# ═══════════════════════════════════════════════════════ Transform 3D
def transform3d(img, layers="", xform_order="srt", rotate_order="xyz",
                translate="0 0 0", rotate="0 0 0", scale="1 1 1", shear="0 0 0",
                uniform_scale=1.0, pivot="0 0 0", pivot_rotate="0 0 0",
                invert=False, perspective=False, border="auto", filt="box",
                camera_distance=2.0):
    """
    Houdini's Transform 3D, **Rasterize** mode only: the layer is a rectangle on z = 0, placed in 3D by the full
    Houdini transform (Transform Order / Rotate Order / Translate / Rotate / Scale / Shear / Uniform
    Scale / Pivot Translate / Pivot Rotate / Invert; the matrix uses the same function as SOP Transform),
    then shot back to the original raster with the default camera (orthographic; Perspective Camera on = perspective).

    Border: auto = our layers have no border metadata (equivalent to Constant), so per the docs' Constant case Clip is used;
    constant = pad 0 outside the image (edges fade to black by the filter kernel); clip = sample normally inside (clamped), 0 outside, no black bleed.
    Filter defaults to Box (per the docs).
    """
    if img is None:
        return CopImage()
    if border not in XFORM_BORDERS:
        raise ValueError(f"Border must be one of {XFORM_BORDERS}")
    W, H = img.xres, img.yres
    M = _xform(translate, rotate, scale, shear, uniform_scale, pivot,
               pivot_rotate, xform_order, rotate_order, invert)
    if abs(np.linalg.det(M[:3, :3])) < 1e-300:
        raise ValueError("Transform matrix is degenerate (Scale has a 0?)")
    O, D = camera_rays(W, H, "perspective" if perspective else "orthographic",
                       camera_distance)
    o, d = _to_object(O, D, M)
    dz = d[..., 2]
    ok = np.abs(dz) > 1e-12
    t = np.where(ok, -o[..., 2] / np.where(ok, dz, 1.0), -1.0)
    hit = ok & (t > 0)
    px, py = image_to_pixel(o[..., 0] + t * d[..., 0], o[..., 1] + t * d[..., 1],
                            W, H)
    # pixels that miss the plane (plane edge-on to the camera / behind the camera) are 0 regardless of Border (keep below);
    # their t = -1 and px / py are finite, so they're sampled and then discarded, never out of bounds
    bm = {"auto": "clip", "constant": "constant"}.get(border, border)
    keep = hit
    if bm == "clip":
        keep = hit & (px >= -0.5) & (px <= W - 0.5) & (py >= -0.5) & (py <= H - 0.5)
        bm = "clamp"
    out = img.copy()
    for n, a in _src_layers(img, layers):
        r = np.where(keep[..., None], fsample(a, px, py, filt, bm, bm), 0.0)
        put(out, n, r, img)
    return out


# ═══════════════════════════════════════════════════════ Align / Align Pixels
JUSTIFY = ("none", "min", "center", "max")
GOALS = ("same", "min", "center", "max")
TARGET_UNITS = ("image", "texture", "pixels", "world")
ALIGN_TARGETS = ("reference", "target_point")
SCALE_AXES = ("x", "y")
_FRAC = {"min": 0.0, "center": 0.5, "max": 1.0}


def _window(W, H):
    """The whole image's rectangle in image space (x0, x1, y0, y1)."""
    L = float(max(W, H))
    return -W / L, W / L, -H / L, H / L


def _units_to_image(units, pt, size, W, H):
    """Convert Target Point / Size from Units to image space (by the reference image's W x H)."""
    if units in ("image", "world"):
        return np.asarray(pt, float), np.asarray(size, float)
    L = float(max(W, H))
    if units == "texture":
        k = np.array([2.0 * W / L, 2.0 * H / L])
        return (np.asarray(pt) - 0.5) * k, np.asarray(size) * k
    if units == "pixels":
        k = np.array([2.0 / L, 2.0 / L])
        return (np.asarray(pt) - np.array([W, H]) / 2.0) * k, np.asarray(size) * k
    raise ValueError(f"Units must be one of {TARGET_UNITS}")


def _justify(a0, a1, b0, b1, just, goal):
    """Translation on one axis: align the just edge of source interval [a0, a1] to the goal edge of target [b0, b1]."""
    if just == "none":
        return 0.0
    g = just if goal == "same" else goal
    src = a0 + _FRAC[just] * (a1 - a0)
    dst = b0 + _FRAC[g] * (b1 - b0)
    return dst - src


def _check_align(justify_x, justify_y, goal_x, goal_y, units):
    for j in (justify_x, justify_y):
        if j not in JUSTIFY:
            raise ValueError(f"Justify must be one of {JUSTIFY}")
    for g in (goal_x, goal_y):
        if g not in GOALS:
            raise ValueError(f"Goal must be one of {GOALS}")
    if units not in TARGET_UNITS:
        raise ValueError(f"Units must be one of {TARGET_UNITS}")


def align_window(source, size_ref=None, layers="", justify_with="reference",
                 units="image", target_point="0 0", target_size="2 2",
                 justify_x="center", justify_y="center", goal_x="same",
                 goal_y="same", offset="0 0", scale_to_fit=False,
                 uniform_scale=True, scale_axis="x", filt="bilinear"):
    """
    Houdini's Align (align by rectangle). Source rectangle = source's window, target rectangle = size_ref's window
    (justify_with = reference; source itself if size_ref isn't connected), or the rectangle given by Target Point / Size
    (target_point, with Target Point as the **center** and Target Size as width/height -- the docs don't say whether the point is
    the center or a corner; our own choice).

    First Scale to Fit (scale about the source rectangle center; with uniform both axes use the Scale Axis ratio, otherwise each axis
    is stretched to the target's width / height), then translate per axis by Justify / Goal, finally add Offset (image space).
    The result is rasterized onto size_ref's pixel grid (source's if not connected), padding 0 outside.

    We have no data window != display window, so Houdini's Source (Data / Display Window) and
    Justify with's Reference Data / Display Window are merged into one option.
    """
    if source is None:
        return CopImage()
    _check_align(justify_x, justify_y, goal_x, goal_y, units)
    if justify_with not in ALIGN_TARGETS:
        raise ValueError(f"Justify with must be one of {ALIGN_TARGETS}")
    if scale_axis not in SCALE_AXES:
        raise ValueError(f"Scale Axis must be one of {SCALE_AXES}")
    ref = size_ref if size_ref is not None and size_ref.xres > 0 else source
    W, H = ref.xres, ref.yres
    w, h = source.xres, source.yres
    sx0, sx1, sy0, sy1 = _window(w, h)
    if justify_with == "reference":
        tx0, tx1, ty0, ty1 = _window(W, H)
    else:
        c, sz = _units_to_image(units, _vec(target_point, 2), _vec(target_size, 2),
                                W, H)
        tx0, tx1 = c[0] - sz[0] / 2, c[0] + sz[0] / 2
        ty0, ty1 = c[1] - sz[1] / 2, c[1] + sz[1] / 2
    kx = ky = 1.0
    if scale_to_fit:
        fx, fy = (tx1 - tx0) / (sx1 - sx0), (ty1 - ty0) / (sy1 - sy0)
        if uniform_scale:
            kx = ky = fx if scale_axis == "x" else fy
        else:
            kx, ky = fx, fy
        if kx == 0 or ky == 0:
            raise ValueError("Scale to Fit: target size is 0")
    cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
    ax0, ax1 = cx + kx * (sx0 - cx), cx + kx * (sx1 - cx)
    ay0, ay1 = cy + ky * (sy0 - cy), cy + ky * (sy1 - cy)
    ox, oy = _vec(offset, 2)
    dx = _justify(ax0, ax1, tx0, tx1, justify_x, goal_x) + ox
    dy = _justify(ay0, ay1, ty0, ty1, justify_y, goal_y) + oy
    X, Y = image_coords(W, H)
    qx = cx + (X - dx - cx) / kx
    qy = cy + (Y - dy - cy) / ky
    px, py = image_to_pixel(qx, qy, w, h)
    out = CopImage(W, H)
    for n, a in _src_layers(source, layers):
        put(out, n, fsample(a, px, py, filt, "constant", "constant"))
    return out


PIXEL_TARGETS = ("reference", "original", "target_point")


def align_pixels(source, size_ref=None, layers="", side_x="min", side_y="min",
                 justify_with="reference", units="pixels", target_point="0 0",
                 justify_x="center", justify_y="center", goal_x="same",
                 goal_y="same", offset="0 0"):
    """
    Houdini's Align Pixels: (1) snap source onto the reference image's pixel grid (pixels 1:1, no interpolation);
    (2) then align by whole-pixel translation. The result is placed in the reference image's raster (size_ref, source itself if not connected), 0 outside.

    (1) Snap: the Side X / Side Y point (min / center / max --
       the docs don't list the options, so Justify's three are used) of the source window in world (image space) is converted to the reference's pixel coordinates and rounded to the nearest pixel corner; source
       is laid out 1:1 from there.
    (2) Align: source rectangle = the snapped source; target = the reference window (reference), source's original (pre-snap) window
       in the reference (original), or Target Point (by Units; a point, no size -- docs: "since
       resizing isn't possible"). Per-axis translation is rounded to whole pixels; Offset is in pixels, also rounded.
    We have no Data / Display Window distinction, so they're merged (same as Align).
    """
    if source is None:
        return CopImage()
    _check_align(justify_x, justify_y, goal_x, goal_y, units)
    for s in (side_x, side_y):
        if s not in _FRAC:
            raise ValueError("Side must be one of min / center / max")
    if justify_with not in PIXEL_TARGETS:
        raise ValueError(f"Justify with must be one of {PIXEL_TARGETS}")
    ref = size_ref if size_ref is not None and size_ref.xres > 0 else source
    W, H = ref.xres, ref.yres
    w, h = source.xres, source.yres
    L = float(max(W, H))
    sx0, sx1, sy0, sy1 = _window(w, h)
    # source's original window in the reference's pixel coordinates (pixel edges, 0 = bottom-left corner)
    ox0, ox1 = sx0 * L / 2 + W / 2, sx1 * L / 2 + W / 2
    oy0, oy1 = sy0 * L / 2 + H / 2, sy1 * L / 2 + H / 2
    fx, fy = _FRAC[side_x], _FRAC[side_y]
    x0 = int(round(ox0 + fx * (ox1 - ox0) - fx * w))
    y0 = int(round(oy0 + fy * (oy1 - oy0) - fy * h))
    if justify_with == "reference":
        t = (0.0, float(W), 0.0, float(H))
    elif justify_with == "original":
        t = (ox0, ox1, oy0, oy1)
    else:
        p, _ = _units_to_image(units, _vec(target_point, 2), (0.0, 0.0), W, H)
        px_, py_ = p[0] * L / 2 + W / 2, p[1] * L / 2 + H / 2
        t = (px_, px_, py_, py_)
    offx, offy = _vec(offset, 2)
    x0 += int(round(_justify(x0, x0 + w, t[0], t[1], justify_x, goal_x))) + int(round(offx))
    y0 += int(round(_justify(y0, y0 + h, t[2], t[3], justify_y, goal_y))) + int(round(offy))
    out = CopImage(W, H)
    # source pixel (i, j) lands at output (y0 + i, x0 + j); only the overlapping block is copied
    dx0, dx1 = max(x0, 0), min(x0 + w, W)
    dy0, dy1 = max(y0, 0), min(y0 + h, H)
    for n, a in _src_layers(source, layers):
        r = np.zeros((H, W, a.shape[2]))
        if dx1 > dx0 and dy1 > dy0:
            r[dy0:dy1, dx0:dx1] = a[dy0 - y0:dy1 - y0, dx0 - x0:dx1 - x0]
        put(out, n, r)
    return out


# ═══════════════════════════════════════════════════════ Bend
BEND_MODES = ("corners", "sides", "angle")


def _bez3(p0, p1, p2, p3, s):
    s = s[..., None]
    m = 1.0 - s
    return m ** 3 * p0 + 3 * m * m * s * p1 + 3 * m * s * s * p2 + s ** 3 * p3


def _bez2_thru(a, mid, b, s):
    """Quadratic Bezier through a, mid (at s = 0.5) and b: control point 2·mid - (a + b)/2."""
    c = 2.0 * mid - 0.5 * (a + b)
    s = s[..., None]
    m = 1.0 - s
    return m * m * a + 2 * m * s * c + s * s * b


def _coons(bot, top, left, right, P00, P10, P01, P11, s, t):
    """Four boundary curves -> Coons patch (bilinear blend): the boundary is exactly those four curves."""
    S, T = s[..., None], t[..., None]
    lin = ((1 - S) * (1 - T) * P00 + S * (1 - T) * P10 + (1 - S) * T * P01
           + S * T * P11)
    return (1 - T) * bot(s) + T * top(s) + (1 - S) * left(t) + S * right(t) - lin


def _patch(mode, c, h, sd):
    """Returns F(s, t) -> (..., 2): Corners (cubic edges + tangent handles) or Sides (quadratic edges through edge midpoints)."""
    P00, P10, P01, P11 = c
    if mode == "corners":
        bl_u, bl_v, br_u, br_v, tl_u, tl_v, tr_u, tr_v = h
        bot = lambda s: _bez3(P00, P00 + bl_u, P10 + br_u, P10, s)      # noqa: E731
        top = lambda s: _bez3(P01, P01 + tl_u, P11 + tr_u, P11, s)      # noqa: E731
        left = lambda t: _bez3(P00, P00 + bl_v, P01 + tl_v, P01, t)     # noqa: E731
        right = lambda t: _bez3(P10, P10 + br_v, P11 + tr_v, P11, t)    # noqa: E731
    else:
        mb, mt, ml, mr = sd
        bot = lambda s: _bez2_thru(P00, mb, P10, s)                     # noqa: E731
        top = lambda s: _bez2_thru(P01, mt, P11, s)                     # noqa: E731
        left = lambda t: _bez2_thru(P00, ml, P01, t)                    # noqa: E731
        right = lambda t: _bez2_thru(P10, mr, P11, t)                   # noqa: E731
    return lambda s, t: _coons(bot, top, left, right, P00, P10, P01, P11, s, t)


def bend_angle_map(p, origin, direction, length, angle, both):
    """
    Forward map of Angle mode (source image coords -> output): the stretch along Capture Direction
    [0, Capture Length] is bent into a circular arc (total turn Bend Angle, bending to the left of the direction); the part beyond
    follows as a rigid rotation, the part before stays put; with Deform in Both Directions the opposite direction bends the same way.
    Same idea as SOP Bend; the docs only describe the parameters, so which side it bends toward and which way the capture interval is measured from the origin are our own choices.
    """
    o = np.asarray(origin, float)
    d = np.asarray(direction, float)
    nd = np.linalg.norm(d)
    if nd == 0:
        raise ValueError("Capture Direction can't be 0")
    d = d / nd
    n = np.array([-d[1], d[0]])
    Lc = float(length)
    th = math.radians(float(angle))
    if Lc <= 0:
        raise ValueError("Capture Length must be > 0")
    if abs(th) < 1e-12:
        return p
    R = Lc / th
    rel = p - o
    a = rel @ d
    b = rel @ n
    out = p.copy()

    def _bent(a_, dd):
        phi = np.clip(a_ / Lc, 0.0, 1.0) * th
        C = o + R * n
        rr = (R - b)[..., None]
        pos = C + rr * (-np.cos(phi)[..., None] * n + np.sin(phi)[..., None] * dd)
        ex = np.maximum(a_ - Lc, 0.0)[..., None]
        tan = np.cos(phi)[..., None] * dd + np.sin(phi)[..., None] * n
        return pos + ex * tan

    fwd = a > 0
    out = np.where(fwd[..., None], _bent(a, d), out)
    if both:
        bwd = a < 0
        out = np.where(bwd[..., None], _bent(-a, -d), out)
    return out


def _newton(F, q, x0, iters=40, lo=None, hi=None):
    """Per-pixel solve of F(x) = q (x and q both (..., 2)), numeric Jacobian + step limit. Returns (x, residual)."""
    x = x0.copy()
    e = 1e-6
    for _ in range(iters):
        f = F(x) - q
        fx = (F(x + [e, 0.0]) - F(x - [e, 0.0])) / (2 * e)
        fy = (F(x + [0.0, e]) - F(x - [0.0, e])) / (2 * e)
        a, b, c, d = fx[..., 0], fy[..., 0], fx[..., 1], fy[..., 1]
        det = a * d - b * c
        ok = np.abs(det) > 1e-14
        det = np.where(ok, det, 1.0)
        dx = np.where(ok, (d * f[..., 0] - b * f[..., 1]) / det, 0.0)
        dy = np.where(ok, (-c * f[..., 0] + a * f[..., 1]) / det, 0.0)
        step = np.stack([dx, dy], -1)
        nrm = np.linalg.norm(step, axis=-1, keepdims=True)
        step = step * np.minimum(1.0, 0.5 / np.maximum(nrm, 1e-300))
        x = x - step
        if lo is not None:
            x = np.clip(x, lo, hi)
    return x, np.linalg.norm(F(x) - q, axis=-1)


def bend(source, size_ref=None, layers="", mode="corners", filt="bilinear",
         bl="-1 -1", br="1 -1", tl="-1 1", tr="1 1",
         bl_u="0.6666667 0", bl_v="0 0.6666667", br_u="-0.6666667 0", br_v="0 0.6666667",
         tl_u="0.6666667 0", tl_v="0 -0.6666667", tr_u="-0.6666667 0", tr_v="0 -0.6666667",
         side_bottom="0 -1", side_top="0 1", side_left="-1 0", side_right="1 0",
         bend_angle=45.0, capture_origin="0 0", capture_direction="0 1",
         capture_length=1.0, both_directions=False, mask_layer=""):
    """
    Houdini's Bend (Copernicus, since 21.0). All positions are in image space (-1...1 across the long side).
      corners  four corners + two tangent handles per corner (**offsets relative to the corner**; the docs don't say whether offset or absolute):
               each edge is a cubic Bezier (corner -> corner + handle -> other corner + handle -> other corner), interior blended
               bilinearly as a Coons patch. Default handles = 1/3 of edge length -> straight edges, identity (square image)
      sides    four corners + four edge midpoints: each edge is a quadratic curve through the midpoint, interior also Coons-blended
      angle    see bend_angle_map
    The source image's texture coords (s, t) ∈ [0,1]² cover the patch; each output pixel inverts (s, t) by Newton iteration (when the patch
    folds over itself only one solution is found); pixels with no solution or outside the patch = 0. Default corners are ±1: **for identity on a non-square image the corners must be
    (±W/L, ±H/L)**, because in image space a non-square image's short side doesn't reach ±1. When mask_layer is non-empty a coverage mask is also output.
    Raster = size_ref (source itself if not connected).
    """
    if source is None:
        return CopImage()
    if mode not in BEND_MODES:
        raise ValueError(f"Mode must be one of {BEND_MODES}")
    ref = size_ref if size_ref is not None and size_ref.xres > 0 else source
    W, H = ref.xres, ref.yres
    w, h = source.xres, source.yres
    X, Y = image_coords(W, H)
    q = np.stack([X, Y], -1)
    if mode == "angle":
        F = lambda p: bend_angle_map(p, _vec(capture_origin, 2),        # noqa: E731
                                     _vec(capture_direction, 2), capture_length,
                                     bend_angle, both_directions)
        p, res = _newton(F, q, q.copy())
        ok = res < 1e-6
        px, py = image_to_pixel(p[..., 0], p[..., 1], w, h)
    else:
        c = [_vec(v, 2) for v in (bl, br, tl, tr)]
        hd = [_vec(v, 2) for v in (bl_u, bl_v, br_u, br_v, tl_u, tl_v, tr_u, tr_v)]
        sd = [_vec(v, 2) for v in (side_bottom, side_top, side_left, side_right)]
        P = _patch(mode, c, hd, sd)
        F = lambda st: P(st[..., 0], st[..., 1])                         # noqa: E731
        # initial guess: spread linearly over the four corners' bounding box (the solution for identity)
        cs = np.array(c)
        mn, mx = cs.min(0), cs.max(0)
        span = np.where(mx - mn > 1e-12, mx - mn, 1.0)
        st, res = _newton(F, q, (q - mn) / span, lo=-0.5, hi=1.5)
        e = 1e-9
        ok = (res < 1e-6) & (st[..., 0] >= -e) & (st[..., 0] <= 1 + e) \
            & (st[..., 1] >= -e) & (st[..., 1] <= 1 + e)
        px, py = st[..., 0] * w - 0.5, st[..., 1] * h - 0.5
    out = CopImage(W, H)
    for n, a in _src_layers(source, layers):
        r = fsample(a, px, py, filt, "constant", "constant")
        put(out, n, np.where(ok[..., None], r, 0.0))
    if str(mask_layer).strip():
        put(out, mask_layer, ok.astype(np.float64))
    return out
