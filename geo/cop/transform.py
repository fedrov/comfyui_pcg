"""
COP geometric transforms: translate / rotate / scale, flip, crop, tile, warp by vector field.

All of them are **inverse mappings**: iterate over output pixels, compute their coordinates in the input, sample once. Forward mapping (iterating
over the input and "throwing" pixels to the output) leaves holes and overlaps -- the most common beginner's pitfall.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rotation must happen in **aspect-corrected** space
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Multiplying by a rotation matrix directly in uv ([0,1]²) **shears** on non-square images: rotating a 1024x512
image by 45° turns squares in the picture into parallelograms. Because one uv unit is
1024 pixels in x and 512 pixels in y, the space isn't isometric.

So first switch to the `generate.aspect_coords` coordinates (**normalized by the short side**, short side
[−0.5,0.5], long side extended by the aspect ratio), rotate there, then switch back. COP Shape uses the same coordinates,
so "draw a circle then rotate 30°" matches "directly draw an ellipse rotated by 30°".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Multiples of 90° must give **exact** 0/±1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`np.cos(np.radians(90))` = 6.123233995736766e-17, not 0. Left alone, "rotate
90°" becomes a resample with a 6e-17 shear: every pixel gets touched by bilinear interpolation, and data that should be
moved bit-exactly gets blurred -- so slightly that the eye would never see it, only exposed in tests like "rotate four times
and get back the original".

So `_cos_sin` **snaps** multiples of 90° to exact 0/±1. After snapping, a 90° rotation's
sample coordinates land on integers, bilinear weights are 0 and 1, and the output is **bit-identical** to `np.rot90`.

Likewise, pure translation (no rotation or scale) takes a **fast path**, directly `gx = j − tx`, without the round trip through aspect space.
Integer-pixel translation is then also a bit-exact move, equivalent to `np.roll`.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Downscaling aliases, and this **doesn't pretend** to solve it
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
At scale=0.25 one output pixel covers a 4x4 input area, and bilinear only looks at 2x2 of it -- you get
moiré. The correct approach is mip / anisotropic prefiltering according to the scale ratio, which is a whole system.
The advice here: **insert COP Blur (sigma ≈ 0.5/scale) before scaling down**; the result is on par with mip,
and the parameters are in your hands. Documenting this clearly beats quietly adding a half-baked mip.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, check_res, DEFAULT_LAYER
from . import backend as bk
from .filters import BORDERS, sample

FILTERS = ("bilinear", "closest")
UNITS = ("uv", "pixels", "normalized")


# ═══════════════════════════════════════════════════════════════════ utilities
def _want(img, layers):
    """Which layers to process. Empty = all; named ones are need()-ed first so wrong names fail immediately."""
    names = [n for n in str(layers).split() if n]
    for n in names:
        img.need(n)
    return names or img.names


def _cos_sin(deg):
    """
    cos/sin of an angle, **with multiples of 90° snapped to exact 0/±1**.

    `cos(radians(90)) = 6.12e-17`. Without snapping, a 90° rotation becomes a resample with a tiny shear,
    every pixel touched by interpolation -- imperceptible, but the cleanest check, "rotating 90° should equal np.rot90",
    would be lost.
    """
    d = float(deg) % 360.0
    q = int(round(d / 90.0)) % 4
    if abs(d - q * 90.0) < 1e-9 or abs(d - 360.0) < 1e-9:
        return [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)][q]
    r = np.radians(d)
    return float(np.cos(r)), float(np.sin(r))


def _delta(t, units, W, H, s):
    """translation -> increment in aspect space (short side length = 1)."""
    tx, ty = float(t[0]), float(t[1])
    if units == "pixels":
        return tx / s, ty / s
    if units == "uv":
        return tx * W / s, ty * H / s
    if units == "normalized":
        return tx * 0.5 * W / s, ty * 0.5 * H / s
    raise ValueError(f"Units must be one of {UNITS}")


def _px(t, units, W, H):
    """translation -> pixels (fast path only)."""
    tx, ty = float(t[0]), float(t[1])
    if units == "pixels":
        return tx, ty
    if units == "uv":
        return tx * W, ty * H
    if units == "normalized":
        return tx * W * 0.5, ty * H * 0.5
    raise ValueError(f"Units must be one of {UNITS}")


def resample(img, gx, gy, border="clamp", filter="bilinear", names=None,
             xp=None):
    """
    Sample the image at the given **input pixel coordinates** (gx, gy). gx/gy have the same shape (Ho, Wo).

    Coordinates are pixel indices (0 = centre of the first pixel); the conversion to `filters.sample`'s uv convention
    is `u = (gx + 0.5) / W` -- the whole plugin has only this one convention; a mismatch gives a half-pixel offset.

    Returns {layer name: (Ho,Wo,C)}.
    """
    xp = xp or img.backend
    W, H = img.xres, img.yres
    names = list(names if names is not None else img.names)
    if filter not in FILTERS:
        raise ValueError(f"Filter must be one of {FILTERS}")
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    out = {}
    if filter == "closest":
        # +0.5 then floor = round to the nearest pixel centre
        xi = xp.to_i64(xp.floor(gx + 0.5))
        yi = xp.to_i64(xp.floor(gy + 0.5))
        oob = None
        if border == "wrap":
            xi, yi = xp.mod_i64(xi, W), xp.mod_i64(yi, H)
        else:
            if border == "black":
                oob = (xi < 0) | (xi >= W) | (yi < 0) | (yi >= H)
            xi = xp.to_i64(xp.clip(xp.asarray(xi), 0, W - 1))
            yi = xp.to_i64(xp.clip(xp.asarray(yi), 0, H - 1))
        for n in names:
            r = xp.index2(img.need(n), yi, xi)
            if oob is not None:
                m = xp.reshape(oob, tuple(oob.shape) + (1,))
                r = xp.where(m, xp.full(tuple(r.shape), 0.0), r)
            out[n] = r
        return out
    u = (gx + 0.5) / W
    v = (gy + 0.5) / H
    for n in names:
        out[n] = sample(img.need(n), u, v, border, xp)
    return out


def _pixel_grid(W, H, xp):
    """Two (H,W) arrays: each pixel's column index j and row index i, as floats."""
    j = xp.broadcast_to(xp.reshape(xp.arange(W), (1, W)), (H, W))
    i = xp.broadcast_to(xp.reshape(xp.arange(H), (H, 1)), (H, W))
    return j, i


# ═══════════════════════════════════════════════════════════════ Transform
def transform(img, translate=(0.0, 0.0), rotate=0.0, scale=(1.0, 1.0),
              pivot=(0.5, 0.5), units="uv", border="clamp",
              filter="bilinear", layers=""):
    """
    Translate / rotate / scale. Resolution unchanged; parts outside the frame are handled by border.

    The order is **scale first, then rotate, then translate** (about pivot, given in uv). Forward:

        p_out = R(θ) · S · (p_in − pivot) + pivot + T

    What's implemented is its inverse (looking up the input for each output pixel):

        p_in = S⁻¹ · R(−θ) · (p_out − pivot − T) + pivot

    scale > 1 **enlarges** (content gets bigger). θ is in **counter-clockwise** degrees -- v is up, so
    this is the mathematically positive direction; it looks opposite to ComfyUI nodes with v down, which is a matter of
    coordinate system definition, not a bug.

    Layers not listed in layers are **passed through as is**, not resampled. Mind SDF layers: translation and rotation don't change
    distance values, scaling does -- after scaling that layer is no longer a correct SDF (distances weren't multiplied accordingly);
    for a correct SDF change COP Shape's parameters instead of transforming its output.
    """
    if img is None:
        return CopImage()
    xp = img.backend
    W, H = img.xres, img.yres
    s = float(min(W, H))
    names = _want(img, layers)
    c, sn = _cos_sin(rotate)
    sx, sy = float(scale[0]), float(scale[1])
    if sx == 0.0 or sy == 0.0:
        raise ValueError("Scale cannot be 0 -- the inverse mapping divides by it.")
    j, i = _pixel_grid(W, H, xp)

    if c == 1.0 and sn == 0.0 and sx == 1.0 and sy == 1.0:
        # fast path for pure translation: no round trip through aspect space, so integer-pixel translation is a
        # **bit-exact move** (sample coordinates land exactly on integers, bilinear weights are 0/1)
        tx, ty = _px(translate, units, W, H)
        gx, gy = j - tx, i - ty
    else:
        pu, pv = float(pivot[0]), float(pivot[1])
        dx, dy = _delta(translate, units, W, H, s)
        # output pixel centre -> uv -> aspect coordinates
        ax = ((j + 0.5) / W - pu) * (W / s) - dx
        ay = ((i + 0.5) / H - pv) * (H / s) - dy
        # R(−θ) then S⁻¹
        bx = (ax * c + ay * sn) / sx
        by = (-ax * sn + ay * c) / sy
        # aspect -> uv -> input pixel coordinates
        gx = (bx * (s / W) + pu) * W - 0.5
        gy = (by * (s / H) + pv) * H - 0.5

    got = resample(img, gx, gy, border, filter, names, xp)
    out = img.copy()
    for k, v in got.items():
        out.set(k, v)
    return out


def distort(img, field, amount=1.0, field_layer=DEFAULT_LAYER, units="uv",
            border="clamp", filter="bilinear", layers=""):
    """
    Warp per pixel by a **vector image**: `out[p] = img[p + amount · field[p]]`.

    This is the general form of "Distort by Noise" -- plug COP Noise (channels=2) into the second input for
    noise distortion, a hand-painted flow field for directional dragging, motion_bwd for a warp.

    The direction is **inverse**: field says "where in the input this output position should fetch from", so the visual
    effect is **opposite** to treating field as "where to push pixels". Both conventions have their users; inverse was chosen here
    because it has no holes; for the forward effect, negate amount (equivalent for small displacements, not for large
    ones; you can't have both).

    If field's resolution differs it is first conformed to img (bilinear), the same rule as Composite.
    """
    if img is None:
        return CopImage()
    if field is None:
        return img.copy()
    from .core import conform
    field = conform(field, img)
    xp = img.backend
    W, H = img.xres, img.yres
    f = field.need(field_layer)
    if field.backend is not xp:
        # if the two inputs are on different backends, move field over. Move field, not img: img is usually the bulk,
        # and its backend is the answer to "where should this step be computed"
        f = xp.asarray(bk.backend_of(f).to_numpy(f))
    if f.shape[2] < 2:
        raise ValueError(
            f"layer '{field_layer}' only has {f.shape[2]} channels; warping needs 2 (x,y). "
            f"Set COP Noise's Channels to 2.")
    a = float(amount)
    # unit conversion same as translate: uv 1.0 = one full width/height
    if units == "pixels":
        kx = ky = 1.0
    elif units == "uv":
        kx, ky = float(W), float(H)
    elif units == "normalized":
        kx, ky = W * 0.5, H * 0.5
    else:
        raise ValueError(f"Units must be one of {UNITS}")
    j, i = _pixel_grid(W, H, xp)
    gx = j + f[:, :, 0] * (a * kx)
    gy = i + f[:, :, 1] * (a * ky)
    names = _want(img, layers)
    got = resample(img, gx, gy, border, filter, names, xp)
    out = img.copy()
    for k, v in got.items():
        out.set(k, v)
    return out


# ════════════════════════════════════════════════════════════════════ flip
def flip(img, horizontal=False, vertical=False, layers=""):
    """
    Flip. **No sampling**; indices are simply reversed, so it's bit-exact and lossless.

    vertical flips v (row 0 is the bottom, so this is "upside down"), horizontal flips u.
    Both on = 180° rotation.
    """
    if img is None:
        return CopImage()
    xp = img.backend
    out = img.copy()
    for n in _want(img, layers):
        a = img.need(n)
        if horizontal:
            a = xp.flip(a, 1)
        if vertical:
            a = xp.flip(a, 0)
        out.set(n, xp.contiguous(a))
    return out


# ════════════════════════════════════════════════════════════════════ crop
CROP_MODES = ("discard_reframe", "discard")
CROP_BORDERS = BORDERS + ("mirror",)
CROP_UNITS = ("pixels", "texture", "image")
CROP_METHODS = ("lower_left_size", "lower_left_upper_right")


def crop_window(W, H, units="pixels", method="lower_left_size",
                corner=(0.0, 0.0), extent=(1.0, 1.0)):
    """
    Houdini Crop's Units × Method -> integer pixel window (x0, y0, w, h), origin bottom-left.

      pixels   pixels directly
      texture  0-1 spans the whole image (a square size doesn't necessarily crop a square)
      image    −1 ... 1 spans the **long side**, origin at the image centre, pixels stay square (Copernicus's
               image space: the display window fitted proportionally into [−1,1]²), so a square size
               crops a square
    method decides whether extent is the top-right corner or the size. Our layers have no sub-pixel data window,
    so both corners are each **rounded to pixel edges** (the docs don't say how Houdini rounds).
    """
    if units not in CROP_UNITS:
        raise ValueError(f"Units must be one of {CROP_UNITS}")
    if method not in CROP_METHODS:
        raise ValueError(f"Method must be one of {CROP_METHODS}")
    ax, ay = float(corner[0]), float(corner[1])
    bx, by = float(extent[0]), float(extent[1])
    if method == "lower_left_size":
        bx, by = ax + bx, ay + by
    if units == "texture":
        ax, bx, ay, by = ax * W, bx * W, ay * H, by * H
    elif units == "image":
        half = 0.5 * max(W, H)
        ax, bx = 0.5 * W + ax * half, 0.5 * W + bx * half
        ay, by = 0.5 * H + ay * half, 0.5 * H + by * half
    x0, y0 = int(np.floor(ax + 0.5)), int(np.floor(ay + 0.5))
    x1, y1 = int(np.floor(bx + 0.5)), int(np.floor(by + 0.5))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(
            f"crop window is empty: bottom-left ({x0}, {y0}), top-right ({x1}, {y1}) (pixels)")
    return x0, y0, x1 - x0, y1 - y0


def _border_index(idx, lo, n, border):
    """
    Fold integer coordinates idx back into [lo, lo+n) by the border rule. Returns (folded coordinates, whether in bounds).
    mirror **reflects at the edge** (the edge pixel repeats once, period 2n), consistent with Houdini's
    "Reflect along the boundaries"; not the kind that skips the edge pixel.
    """
    t = idx - lo
    ok = (t >= 0) & (t < n)
    if border == "wrap":
        t = t % n
    elif border == "mirror":
        t = t % (2 * n)
        t = np.where(t >= n, 2 * n - 1 - t, t)
    else:
        t = np.clip(t, 0, n - 1)
    return t + lo, ok


def crop(img, x0=0, y0=0, xres=0, yres=0, border="black",
         mode="discard_reframe", pad=(0, 0, 0, 0)):
    """
    Crop xres × yres starting at (x0, y0). **Coordinate origin is bottom-left** (consistent with all of COP).

    The window can extend outside the image; outside is filled per border (black = 0, clamp = copy edges,
    wrap = periodic extension, mirror = reflect at edge). So it is also "Pad" -- give a negative x0
    and a larger xres to pad outward, no separate node needed.

    Integer coordinates + closest sampling, so the part inside the image is a **bit-exact move**.

    mode (Houdini Crop's Mode):
      discard_reframe  Discard and Reframe to Crop: output resolution = window. The original
                       and only behaviour
      discard          Discard Cropped: resolution **unchanged**, pixels stay in place, everything outside the window
                       is discarded -- discarded areas read outward per border from **the part that's kept**
                       (window ∩ original image); black is 0
    Houdini's third mode Reframe to Crop (data untouched, only the display window changes) requires layers
    to carry data outside the frame; our layers = the frame, so it can't be represented; not implemented.

    pad = (left, right, top, bottom): extra pixels to expand each side of the window (Pixel Padding).
    """
    if img is None:
        return CopImage()
    if mode not in CROP_MODES:
        raise ValueError(f"Mode must be one of {CROP_MODES}")
    if border not in CROP_BORDERS:
        raise ValueError(f"Border must be one of {CROP_BORDERS}")
    w = int(xres) if int(xres) > 0 else img.xres
    h = int(yres) if int(yres) > 0 else img.yres
    pl, pr, pt, pb = (int(v) for v in pad)
    x0, y0 = int(x0) - pl, int(y0) - pb
    w, h = w + pl + pr, h + pt + pb
    xp = img.backend
    if mode == "discard_reframe" and border in BORDERS:
        w, h = check_res(w, h)
        j, i = _pixel_grid(w, h, xp)
        gx = j + float(x0)
        gy = i + float(y0)
        got = resample(img, gx, gy, border, "closest", img.names, xp)
        out = CopImage(w, h)
        for k in img.names:
            out.set(k, got[k])
        return out
    W, H = img.xres, img.yres
    if mode == "discard_reframe":
        # only mirror gets here: data window = the whole original image
        w, h = check_res(w, h)
        ix, okx = _border_index(np.arange(w) + x0, 0, W, border)
        iy, oky = _border_index(np.arange(h) + y0, 0, H, border)
        out = CopImage(w, h)
    else:
        # the part that's kept = window ∩ original image
        kx0, kx1 = max(x0, 0), min(x0 + w, W)
        ky0, ky1 = max(y0, 0), min(y0 + h, H)
        out = CopImage(W, H)
        if kx1 <= kx0 or ky1 <= ky0:
            # window entirely outside the image: nothing kept, no border mode has anything to read
            for k in img.names:
                out.set(k, xp.zeros(tuple(img.need(k).shape)))
            return out
        ix, okx = _border_index(np.arange(W), kx0, kx1 - kx0, border)
        iy, oky = _border_index(np.arange(H), ky0, ky1 - ky0, border)
    inside = oky[:, None] & okx[None, :]
    for k in img.names:
        r = xp.outer_index(img.need(k), iy, ix)
        if border == "black":
            # where instead of multiplying by 0: inf / nan in the original × 0 becomes nan
            m = xp.asarray(inside[:, :, None].astype(np.float64)) > 0.5
            r = xp.where(m, r, xp.full(tuple(r.shape), 0.0))
        out.set(k, r)
    return out


# ════════════════════════════════════════════════════════════════════ tile
def tile(img, nx=2, ny=2, mirror_u=False, mirror_v=False):
    """
    Tile nx × ny copies; output resolution is (W·nx, H·ny). Bit-exact copy, no resampling.

    With mirror on, odd-numbered copies are **mirrored** -- the easiest way to make any image tile
    seamlessly (at the cost of visible mirror symmetry; directional content gives it away).

    Note this is different from COP Noise's tile_u: that one makes the noise **function** periodic,
    resolution unchanged; this one copies the picture several times, increasing the resolution.
    """
    if img is None:
        return CopImage()
    nx, ny = max(1, int(nx)), max(1, int(ny))
    W, H = img.xres, img.yres
    w, h = check_res(W * nx, H * ny)
    xp = img.backend
    # all indices computed in numpy (pure integers, tens of KB), then handed to the backend for the gather
    jj = np.arange(w)
    ii = np.arange(h)
    kx, sxi = jj // W, jj % W
    ky, syi = ii // H, ii % H
    if mirror_u:
        sxi = np.where(kx % 2 == 1, W - 1 - sxi, sxi)
    if mirror_v:
        syi = np.where(ky % 2 == 1, H - 1 - syi, syi)
    out = CopImage(w, h)
    for k in img.names:
        out.set(k, xp.outer_index(img.need(k), syi, sxi))
    return out
