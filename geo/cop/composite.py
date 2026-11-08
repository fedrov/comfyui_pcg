"""
COP compositing: blend modes, alpha over, masks.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`over` is not the same kind of thing as the other blend modes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
add / multiply / screen are **per-component functions** f(a,b); alpha only enters at the end via
`lerp(a, f(a,b), α)`. `over`, however, is Porter–Duff compositing, which computes **a new
alpha**:

    C = Cb·αb + Ca·αa·(1−αb)
    α = αb + αa·(1−αb)

Implementing over as "interpolate by alpha" is wrong when both layers are semi-transparent -- the result's alpha
gets stuck at the lower layer's alpha, and stacking three layers of fog gives the wrong density. So over has its own path here,
and requires the foreground to carry alpha (treated as 1 if absent).

`over` uses **unpremultiplied** (straight) alpha: input RGB doesn't carry the alpha factor; the formula
multiplies it in itself. Premultiplied is faster and more robust, but IMAGE on the ComfyUI side is unpremultiplied, and converting back and forth
at the boundary is more error-prone, so the whole chain is uniformly unpremultiplied and only this one formula multiplies.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Resolution and channel count: **aligned automatically, but only when it can be done sensibly**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When resolutions differ, the **second input** is resampled to the first (Houdini's COP also conforms to the first input).
For channel counts only 1 channel broadcasts automatically -- compositing a mask with RGB naturally wants broadcasting, but there's no guessing between 3 and 4:
it's either wanted alpha or miswired, and guessing wrong costs more than an error.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No clamping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`add` giving 1.7 means 1.7, `subtract` giving −0.3 means −0.3. Clamping in intermediate steps would destroy
HDR, SDFs, normals and the like, and clamped values can never be recovered. Clamping only happens at the export step,
and it can be turned off.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, DEFAULT_LAYER, match_channels, conform
from . import backend as bk

MODES = ("over", "add", "subtract", "difference", "multiply", "divide",
         "screen", "overlay", "softlight", "darken", "lighten", "atop",
         "xor", "replace",
         # pcg100: the entries of Houdini Blend COP's Mode menu we didn't have before (appended at the end;
         # workflows store values by token, so old graphs are unaffected). Blend = the existing replace,
         # Maximum / Minimum = the existing lighten / darken; no duplicate tokens added
         "under", "hypot", "exclusion", "hardlight", "dodge", "burn")


def _blend(a, b, mode, xp=None):
    """
    Per-component blending. a is the lower layer (background), b is the upper layer (foreground).

    over / atop / xor aren't here -- they modify alpha; they're Porter–Duff compositing,
    a different kind of thing from "per-component functions".
    """
    xp = xp or bk.backend_of(a)
    if mode == "add":
        return a + b
    if mode == "subtract":
        return a - b
    if mode == "difference":
        return xp.abs(a - b)
    if mode == "multiply":
        return a * b
    if mode == "divide":
        eps = xp.full(tuple(b.shape), 1e-8)
        return a / xp.where(xp.abs(b) < 1e-8, eps, b)
    if mode == "screen":
        return a + b - a * b
    if mode == "overlay":
        return xp.where(a < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    if mode == "softlight":
        return xp.where(b < 0.5, a - (1 - 2 * b) * a * (1 - a),
                        a + (2 * b - 1) * (xp.sqrt(xp.abs(a)) - a))
    if mode == "darken":
        return xp.minimum(a, b)
    if mode == "lighten":
        return xp.maximum(a, b)
    if mode == "replace":
        return b
    if mode == "hypot":
        # treat (bg, fg) per channel as a 2D vector and take its length
        return xp.sqrt(a * a + b * b)
    if mode == "exclusion":
        # docs, verbatim: the sum minus twice the product
        return a + b - 2 * a * b
    if mode == "hardlight":
        # overlay's test switches to the **foreground**: multiply when fg < 0.5, otherwise screen
        return xp.where(b < 0.5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    if mode == "dodge":
        # colour dodge bg / (1 − fg). Not clamped to 1 (COP never clamps); where fg = 1,
        # pad with 1e-8 like divide, so no inf
        d = 1 - b
        eps = xp.full(tuple(b.shape), 1e-8)
        return a / xp.where(xp.abs(d) < 1e-8, eps, d)
    if mode == "burn":
        # colour burn 1 − (1 − bg) / fg
        eps = xp.full(tuple(b.shape), 1e-8)
        return 1 - (1 - a) / xp.where(xp.abs(b) < 1e-8, eps, b)
    raise ValueError(f"Mode must be one of {MODES}")


def _split_alpha(a, xp):
    """(rgb, alpha). 4 channels are split, otherwise alpha is 1."""
    if a.shape[2] == 4:
        return a[..., :3], a[..., 3:4]
    return a, xp.full((int(a.shape[0]), int(a.shape[1]), 1), 1.0)


def porter_duff(bg, fg, mode="over", xp=None):
    """
    Porter–Duff compositing. **Unpremultiplied** alpha; the formula multiplies it in itself.

    over:  C = Cb·αb + Cf·αf·(1−αb) ,  α = αb + αf·(1−αb)

    Note this is not "interpolate by alpha": when both layers are semi-transparent, interpolation leaves the result's alpha stuck at
    the lower layer's alpha, and stacking a few layers of fog gives the wrong density.
    """
    xp = xp or bk.backend_of(bg)
    cb, ab = _split_alpha(bg, xp)
    cf, af = _split_alpha(fg, xp)
    cb, cf = match_channels(cb, cf, xp)
    if mode == "over":
        # here bg is **on top**: Houdini / Nuke's over is "the second input over the first",
        # so fg = the second input. Below everything is written as fg over bg
        out_a = af + ab * (1 - af)
        num = cf * af + cb * ab * (1 - af)
    elif mode == "atop":
        out_a = ab
        num = (cf * af + cb * (1 - af)) * ab
    elif mode == "xor":
        out_a = af * (1 - ab) + ab * (1 - af)
        num = cf * af * (1 - ab) + cb * ab * (1 - af)
    else:
        raise ValueError(f"Porter-Duff only supports over / atop / xor, got {mode}")
    safe = xp.where(out_a < 1e-8, xp.full(tuple(out_a.shape), 1.0), out_a)
    return xp.concat([num / safe, out_a], -1)


def _by_length(a, b, longer, xp):
    """
    Compare Lengths: compare the whole pixel as a vector by length, taking a or b **as a whole** (not per channel).
    On equal lengths a (background) is kept -- the docs don't say how ties are broken.
    """
    la = xp.sum(a * a, -1)
    lb = xp.sum(b * b, -1)
    pick = (lb > la) if longer else (lb < la)
    pick = xp.reshape(pick, tuple(pick.shape) + (1,))
    return xp.where(pick, b, a)


def composite(bg, fg, mode="over", opacity=1.0, layer=DEFAULT_LAYER,
              fg_layer="", mask=None, mask_layer="mask",
              output_layer="", keep_other_layers=True, swap=False,
              compare_lengths=False, channels=(True, True, True, True)):
    """
    Composite fg onto bg.

    mode=over/atop/xor/under go through Porter–Duff (computing a new alpha); the rest are per-component
    blends interpolated back by opacity × mask.

    Three things added in pcg100 following Houdini Blend:
      swap             Swap FG and BG: the two inputs' **values** are swapped (resolution still follows the first input)
      compare_lengths  only for darken / lighten (Houdini's Minimum / Maximum):
                       pick whole pixels by vector length instead of per channel
      channels         four toggles Red / Green / Blue / Alpha: disabled channels keep the background value
    """
    if bg is None and fg is None:
        return CopImage()
    if bg is None:
        return fg.copy()
    if fg is None:
        return bg.copy()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")

    fg = conform(fg, bg)
    if fg.device != bg.device:
        fg = fg.to_device(bg.device if bg.device != "numpy" else "numpy")
    xp = bg.backend
    name = str(layer).strip() or DEFAULT_LAYER
    fname = str(fg_layer).strip() or name
    a = bg.need(name)
    b = fg.need(fname)
    if swap:
        # docs: "Swaps the values of the foreground and background". After swapping, the "original value"
        # blended back is also the swapped background (= the original foreground) -- the docs don't say which is the base
        # when Mask < 1; taken literally here: values are swapped first, everything after is unchanged
        a, b = b, a

    drop_alpha = False
    if mode in ("over", "atop", "xor", "under"):
        # under = background over foreground ("the foreground tucked under the background's alpha"), i.e. over
        # with the two inputs swapped
        r = porter_duff(b, a, "over", xp) if mode == "under" \
            else porter_duff(a, b, mode, xp)
        # Porter–Duff always outputs 4 channels (alpha is part of what it computes). If the lower layer had
        # no alpha it is dropped **at the very end** -- dropping it before the opacity/mask interpolation would
        # leave the two sides of the interpolation with mismatched channel counts
        drop_alpha = a.shape[2] < 4
        if drop_alpha:
            a = xp.concat([a, xp.full((int(a.shape[0]), int(a.shape[1]), 1),
                                      1.0)], -1)
            if a.shape[2] != r.shape[2]:
                a, _ = match_channels(a, r, xp)
    else:
        a2, b2 = match_channels(a, b, xp)
        if compare_lengths and mode in ("darken", "lighten"):
            r = _by_length(a2, b2, mode == "lighten", xp)
        else:
            r = _blend(a2, b2, mode, xp)
        a = a2

    w = float(opacity)
    if mask is not None:
        mimg = conform(mask, bg)
        if mimg.device != bg.device:
            mimg = mimg.to_device(bg.device)
        m = mimg.need(str(mask_layer).strip() or "mask")
        if m.shape[2] != 1 and m.shape[2] != r.shape[2]:
            m = m[..., :1]
        w = w * m
    C = int(r.shape[2])
    on = ([bool(c) for c in channels][:4] + [True] * C)[:C]
    if not all(on):
        # disabled channels get weight × 0 = keep the background. Single-channel layers only look at Red, two-channel at Red / Green;
        # channels from the 5th on have no corresponding Houdini toggle and are always enabled
        w = w * xp.reshape(xp.asarray(np.asarray(on, np.float64)), (1, 1, C))
    if not (isinstance(w, float) and w == 1.0):
        base = a
        if base.shape[2] != r.shape[2]:
            base, _ = match_channels(base, r, xp)
            base = xp.broadcast_to(base, tuple(r.shape))
        r = base + (r - base) * w
    if drop_alpha:
        r = r[..., :3]

    out = bg.copy() if keep_other_layers else CopImage(bg.xres, bg.yres)
    out.set(str(output_layer).strip() or name, r)
    return out


def layer_math(img, layer=DEFAULT_LAYER, op="multiply", value=(1.0,),
               output_layer=""):
    """Operate on a layer with a constant -- the most common few, saving a Composite node each time."""
    if img is None:
        return CopImage()
    xp = img.backend
    name = str(layer).strip() or DEFAULT_LAYER
    a = img.need(name)
    v = np.asarray(value, np.float64).reshape(1, 1, -1)
    if v.shape[2] != 1 and v.shape[2] != a.shape[2]:
        v = v[:, :, :1]
    vb = xp.broadcast_to(xp.asarray(v), tuple(a.shape)) \
        if v.shape[2] == a.shape[2] else xp.broadcast_to(
            xp.asarray(v), (int(a.shape[0]), int(a.shape[1]), 1))
    a2, b2 = match_channels(a, vb, xp)
    r = _blend(a2, b2, op, xp)
    out = img.copy()
    out.set(str(output_layer).strip() or name, r)
    return out
