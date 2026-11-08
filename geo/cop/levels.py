"""
COP value-range adjustment: Levels / Remap / Clamp / Quantize / Invert / Fit / Luminance.

This group is all **per-pixel 1D functions**, with no neighbourhood and no resampling, so they compose cleanly:
Levels then Quantize gives a different result from the reverse, but each step only changes values, never positions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
gamma > 1 = **brighter**, consistent with Photoshop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The Levels formula:

    t = (x − in_black) / (in_white − in_black)
    t = t ^ (1 / gamma)                       ← note it's **1/gamma**
    out = out_black + t · (out_white − out_black)

The exponent is inverted so that "pulling gamma right = brighter image". This runs against the `pow(x, gamma)`
intuition, but it's an established convention of image software (Photoshop's middle slider, Nuke's gamma,
Houdini COP's Gamma all go this direction); writing it the other way would make everyone adjust it backwards the first time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Without clamping, powers must **preserve sign**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COP values are unclamped (SDFs are negative, noise is ±1, height is in metres), so t can perfectly well be negative.
`(-0.3) ** 0.4545` gives **nan** in numpy, and nan in torch too -- the whole chain
silently becomes a nan image here, downstream Blur smears the nan around, and what you finally see is all black,
with no way to find the source.

So with `clamp_input=False` we use `sign(t)·|t|^g`: it is continuous at 0, monotonic and odd-symmetric,
and the negative half-axis gets exactly a "symmetric gamma". It's not the mathematically unique correct extension, but it's **the only one
that won't wreck the chain**, and for SDFs it's exactly what you want (compress / stretch inside and outside symmetrically).

Default `clamp_input=True` (photographic usage); turn it off when processing SDF / normals / HDR.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quantize gives **N values**, not N intervals
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`round(x·(N−1))/(N−1)`, so steps=2 gives {0,1}, steps=4 gives {0,⅓,⅔,1} --
both endpoints are kept. Written as `floor(x·N)/N`, steps=4 gives {0,¼,½,¾}, **1.0 is never reached**,
the brightest areas drop one level after posterizing, and it disagrees with "steps=1 should be a constant colour".
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk

T_FROM = ("value", "luminance")
QUANT_MODES = ("round", "floor", "ceil")
# Rec.709 luminance weights. COP is **linear** internally, so weighting directly here is correct;
# using the same weights on sRGB-encoded values is a common mistake (those must be decoded first)
LUMA_709 = (0.2126, 0.7152, 0.0722)


def _want(img, layers):
    names = [n for n in str(layers).split() if n]
    for n in names:
        img.need(n)
    return names or img.names


def _pow_signed(xp, t, g):
    """
    `sign(t)·|t|^g`. Returns as is when g == 1 (avoids two pointless operations and a rounding).

    Sign preservation is for unclamped chains: `(-0.3) ** 0.45` = nan, and nan gets smeared over a large area
    by downstream blurs; by the time you notice, nobody knows which node it came from.
    """
    if g == 1.0:
        return t
    one = xp.full(tuple(t.shape), 1.0)
    sgn = xp.where(t < 0, -one, one)
    return sgn * (xp.abs(t) ** g)


# ══════════════════════════════════════════════════════════════════ Levels
def levels(img, in_black=0.0, in_white=1.0, gamma=1.0, out_black=0.0,
           out_white=1.0, clamp_input=True, clamp_output=False, layers=""):
    """
    Classic Levels. The default parameters are the **identity** (bit-exact identity, see below).

    `clamp_output` is off by default: not clamping intermediate COP results is a global convention; clamp at COP Export
    if needed. A toggle is kept here because Levels is often the "final grading step".
    """
    if img is None:
        return CopImage()
    ib, iw = float(in_black), float(in_white)
    ob, ow = float(out_black), float(out_white)
    g = float(gamma)
    if iw == ib:
        raise ValueError("In White cannot equal In Black -- the difference is a divisor.")
    if g <= 0.0:
        raise ValueError("Gamma must be > 0.")
    xp = img.backend
    out = img.copy()
    identity = (ib == 0.0 and iw == 1.0 and g == 1.0
                and ob == 0.0 and ow == 1.0 and not clamp_input
                and not clamp_output)
    for n in _want(img, layers):
        a = img.need(n)
        if identity:
            out.set(n, a)          # bit-exact as is, not a single float operation
            continue
        t = (a - ib) / (iw - ib)
        if clamp_input:
            t = xp.clip(t, 0.0, 1.0)
        t = _pow_signed(xp, t, 1.0 / g)
        r = ob + t * (ow - ob)
        if clamp_output:
            lo, hi = (ob, ow) if ow >= ob else (ow, ob)
            r = xp.clip(r, lo, hi)
        out.set(n, r)
    return out


def invert(img, pivot=1.0, layers=""):
    """
    `out = pivot − x`. pivot=1 is the usual "invert", pivot=0 is **negation** (swaps the inside and outside
    of an SDF), so this one node is also the SDF flip.
    """
    if img is None:
        return CopImage()
    p = float(pivot)
    out = img.copy()
    for n in _want(img, layers):
        out.set(n, p - img.need(n))
    return out


def clamp_layer(img, lo=0.0, hi=1.0, layers=""):
    """Clamp to [lo, hi]."""
    if img is None:
        return CopImage()
    lo, hi = float(lo), float(hi)
    if hi < lo:
        lo, hi = hi, lo
    xp = img.backend
    out = img.copy()
    for n in _want(img, layers):
        out.set(n, xp.clip(img.need(n), lo, hi))
    return out


def quantize(img, steps=4, mode="round", lo=0.0, hi=1.0, layers=""):
    """
    Posterize into `steps` discrete values. `steps=1` gives a constant lo.

    The interval is [lo, hi]; values outside are **not clamped** and keep being quantized on the same grid (so a quantized
    SDF gives equally spaced concentric bands, exactly what outlining wants).
    """
    if img is None:
        return CopImage()
    n_s = int(steps)
    if n_s < 1:
        raise ValueError("Steps must be at least 1.")
    if mode not in QUANT_MODES:
        raise ValueError(f"Mode must be one of {QUANT_MODES}")
    lo, hi = float(lo), float(hi)
    if hi == lo:
        raise ValueError("Hi cannot equal Lo.")
    xp = img.backend
    out = img.copy()
    for n in _want(img, layers):
        a = img.need(n)
        if n_s == 1:
            out.set(n, xp.full(tuple(a.shape), lo))
            continue
        t = (a - lo) / (hi - lo) * (n_s - 1)
        if mode == "round":
            q = xp.floor(t + 0.5)
        elif mode == "floor":
            q = xp.floor(t)
        else:
            q = -xp.floor(-t)
        out.set(n, lo + q / (n_s - 1) * (hi - lo))
    return out


# ═══════════════════════════════════════════════════════════════════ Remap
def remap(img, ramp="0:0  1:1", ramp_mode="linear", in_min=0.0, in_max=1.0,
          t_from="value", layers=""):
    """
    Feed values through a **ramp lookup table**. Syntax is exactly the same as COP Gradient / Attribute Fade
    (`"0:0  0.5:1  1:0"`; the right side of the colon may be `r,g,b`).

    Two behaviours, chosen **automatically** by the ramp's component count, no toggle:

      · 1-component ramp -> **per-channel** lookup, channel count unchanged. Grey curves, contrast, level
        compression all go this way
      · multi-component ramp -> first reduce the image to a scalar t (`t_from`: channel 0,
        or Rec.709 luminance), then look up N channels. **Grey to false colour** goes this way --
        colouring SDFs, depth and noise all rely on it

    The lookup runs in **numpy**: the table has at most a few dozen points, not worth moving to the GPU, and `ramp.apply`
    only has a numpy implementation anyway. If the image is on CUDA there's one round trip here, a noticeable cost on large images;
    noted here so nobody uses it as a per-frame hot path.
    """
    if img is None:
        return CopImage()
    if t_from not in T_FROM:
        raise ValueError(f"T From must be one of {T_FROM}")
    from ..ramp import parse as _parse, apply as _apply
    lo, hi = float(in_min), float(in_max)
    if hi == lo:
        raise ValueError("In Max cannot equal In Min.")
    first = next((tok for tok in str(ramp).split() if ":" in tok), "0:0")
    nc = max(1, len([c for c in first.split(":", 1)[1].split(",") if c != ""]))
    pos, val = _parse(str(ramp), nc)
    xp = img.backend
    out = img.copy()
    for n in _want(img, layers):
        a = img.need(n)
        npa = np.asarray(bk.backend_of(a).to_numpy(a), np.float64)
        H, W, C = npa.shape
        if nc == 1:
            t = (npa - lo) / (hi - lo)
            v = _apply(np.clip(t, 0.0, 1.0).reshape(-1), pos, val, ramp_mode)
            r = np.asarray(v, np.float64).reshape(H, W, C)
        else:
            if t_from == "luminance" and C >= 3:
                w = np.asarray(LUMA_709, np.float64)
                s = (npa[:, :, :3] * w).sum(-1)
            else:
                s = npa[:, :, 0]
            t = (s - lo) / (hi - lo)
            v = _apply(np.clip(t, 0.0, 1.0).reshape(-1), pos, val, ramp_mode)
            r = np.asarray(v, np.float64).reshape(H, W, nc)
        out.set(n, xp.asarray(r))
    return out


# ═══════════════════════════════════════════════════════════════ statistics / Fit
def stats(img, layer=DEFAULT_LAYER):
    """
    min / max / mean of a layer, both overall and per channel.

    It exists for **visibility**: COP doesn't clamp, so "what range is this image actually in" is
    the first question to ask before hooking up a Preview. Fit uses it too.
    """
    a = img.need(layer)
    xp = bk.backend_of(a)
    ax = (0, 1)
    return {
        "channels": int(a.shape[2]),
        "min": xp.fmin_scalar(a), "max": xp.fmax_scalar(a),
        "mean": xp.fmean_scalar(a),
        "cmin": [float(v) for v in
                 np.asarray(xp.to_numpy(xp.amin(a, ax))).reshape(-1)],
        "cmax": [float(v) for v in
                 np.asarray(xp.to_numpy(xp.amax(a, ax))).reshape(-1)],
    }


def fit(img, out_min=0.0, out_max=1.0, per_channel=False, layers=""):
    """
    Stretch the **measured** min/max to [out_min, out_max]. The easiest step for taking a quick look at noise, SDF, depth
    -- no need to know the range first.

    With `per_channel` off the three channels share one range (preserving hue); turning it on **changes
    colour relationships** (each channel stretched to full range separately). Off by default.

    A constant layer (min == max) outputs out_min as is, no division by 0.
    """
    if img is None:
        return CopImage()
    o0, o1 = float(out_min), float(out_max)
    xp = img.backend
    out = img.copy()
    for n in _want(img, layers):
        a = img.need(n)
        if per_channel:
            lo = xp.reshape(xp.amin(a, (0, 1)), (1, 1, a.shape[2]))
            hi = xp.reshape(xp.amax(a, (0, 1)), (1, 1, a.shape[2]))
            d = hi - lo
            one = xp.full(tuple(d.shape), 1.0)
            t = (a - lo) / xp.where(d == 0, one, d)
            t = xp.where(xp.broadcast_to(d == 0, tuple(a.shape)),
                         xp.full(tuple(a.shape), 0.0), t)
        else:
            lo = xp.fmin_scalar(a)
            hi = xp.fmax_scalar(a)
            if hi == lo:
                out.set(n, xp.full(tuple(a.shape), o0))
                continue
            t = (a - lo) / (hi - lo)
        out.set(n, o0 + t * (o1 - o0))
    return out


def luminance(img, layer=DEFAULT_LAYER, out_layer="lum", weights=LUMA_709):
    """
    RGB -> single-channel luminance (Rec.709). COP is **linear** internally, so direct weighting is correct;
    using the same weights on sRGB-encoded values is a common mistake (they must be decoded first).

    With fewer than 3 channels, channel 0 is taken -- masks and SDFs plugged in shouldn't raise an error.
    """
    if img is None:
        return CopImage()
    a = img.need(layer)
    xp = img.backend
    C = int(a.shape[2])
    if C < 3:
        r = a[:, :, :1]
    else:
        w = xp.reshape(xp.asarray(
            np.asarray(weights, np.float64).reshape(3)), (1, 1, 3))
        r = xp.reshape(xp.sum(a[:, :, :3] * w, -1),
                       (a.shape[0], a.shape[1], 1))
    out = img.copy()
    out.set(str(out_layer).strip() or "lum", r)
    return out
