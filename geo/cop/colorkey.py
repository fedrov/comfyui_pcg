"""
pcg100 · c2_color_key batch: Houdini-semantics nodes / modes added following the SideFX docs.

The audit found several of our nodes where "the name matches but they don't do the same thing": Houdini's Equalize is a
**range remap** by min / max / mean (ours is a rank-based histogram equalization), Histogram **draws the histogram
as an image** (ours is equalize / match), Compare outputs a **boolean mask** (ours is SSIM /
PSNR), Mono to RGB goes through a **ramp** (ours copies the channel), and Despill only removes spill, with no alpha output.
The original nodes' behaviour is unchanged (workflows already use them); Houdini's semantics are written here, each as a new node.

The other two sections are modes added to **existing** nodes, moved over from the original functions in pixel.py:
    key_matte       Chroma Key's Chromakey (HSV ranges) / Channel Separation modes
    illegal_fix     Illegal Pixel's Blend / Zero / Highlight / Isolate + Detect / Rule

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Where the docs give no formula
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SideFX's parameter pages only say what each parameter "does", without formulas. Everything we decided ourselves is marked
"not specified in the docs" in the function docstring, and audit_notes/c2_color_key.md has a summary -- when comparing numbers against Houdini,
check that table first; mismatches are most likely there.

Everything is computed in numpy float64 and put back on the original backend (same convention as pixel.py).
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from .levels import LUMA_709
from .pixel import getn, put, _vec, rgb_to_hsv

# ═══════════════════════════════════════════════════════════ small helpers
KEY_METHODS = ("chromakey", "channel_separation")
ROLLOFFS = ("linear", "ease_in", "ease_out", "smooth", "gaussian")


def _layer_or_one(img, name):
    """Optional per-pixel factor layer: empty = 1; if given, channel 0 is used (H,W)."""
    s = str(name).strip()
    if not s:
        return 1.0
    return getn(img, s)[..., 0]


def _rolloff(d, size, interp):
    """
    Distance d to the range boundary (<= 0 = inside the range) -> weight: 1 inside the range, rolling off to 0 within
    size outside it. size = 0 is a hard edge.

    The docs don't give formulas for the five Interpolation modes; here they are defined on x = d / size in [0,1] (0 at the
    range edge):
        linear    1 − x
        ease_in   1 − x²        (flat on the side next to the range, steep outside)
        ease_out  (1 − x)²      (steep on the side next to the range, flat outside)
        smooth    smoothstep(1 − x)
        gaussian  exp(−(3x)²/2), i.e. size = 3 sigma, truncated to 0 at x >= 1
    """
    if interp not in ROLLOFFS:
        raise ValueError(f"Interpolation must be one of {ROLLOFFS}")
    size = float(size)
    if not size > 0:
        return (d <= 0).astype(np.float64)
    x = np.clip(d / size, 0.0, 1.0)
    if interp == "linear":
        w = 1.0 - x
    elif interp == "ease_in":
        w = 1.0 - x * x
    elif interp == "ease_out":
        w = (1.0 - x) ** 2
    elif interp == "smooth":
        t = 1.0 - x
        w = t * t * (3.0 - 2.0 * t)
    else:
        w = np.where(x < 1.0, np.exp(-4.5 * x * x), 0.0)
    return w


def _range_dist(x, lo, hi):
    """Distance from x to the interval [lo, hi] (<= 0 inside the interval). Swapped automatically when lo > hi."""
    lo, hi = min(lo, hi), max(lo, hi)
    return np.maximum(lo - x, x - hi)


def _hue_dist(h_deg, lo, hi):
    """
    Distance from hue (degrees) to [lo, hi] **on the circle**. Hue is a circle: the range 350..10 must wrap across 0 degrees,
    so lo > hi means wrapping around 360 (no swap). With a range width >= 360 the whole circle is included.
    """
    lo, hi = float(lo), float(hi)
    if hi - lo >= 360.0:
        return np.full(np.shape(h_deg), -1.0)
    half = ((hi - lo) % 360.0) / 2.0
    cen = lo + half
    off = (h_deg - cen + 180.0) % 360.0 - 180.0
    return np.abs(off) - half


# ═══════════════════════════════════════════════════════════ Chroma Key
def key_matte(rgb, method, key, hue, sat, lum, roll, interp, threshold, width):
    """
    Chroma Key's two Houdini methods, returning matte (H,W,1): 1 = foreground kept, 0 = keyed out.

    chromakey (Houdini's legacy Chromakey): a pixel counts as "screen" only if its hue (degrees), saturation and luminance each
    fall within their ranges; the three weights are multiplied, matte = 1 − product. Rolloff extends each range
    by a soft edge on both sides. Luminance uses Rec.709 (the docs don't say which luminance).

    channel_separation: the docs only say "key out Screen Color, then threshold the matte with Threshold / Width",
    without a separation formula. Implemented with the most common channel difference: k = the largest channel of Screen Color,
    s = (c[k] − max(other two channels)) / (the same difference of the screen colour itself), pure screen s = 1,
    grey s = 0; matte = 1 − s, then fit to [Threshold − Width/2, Threshold +
    Width/2] (docs example: 0.5 / 0.2 -> input range 0.4..0.6). Width = 0 is a hard threshold,
    kept only where matte > Threshold.
    """
    if method == "chromakey":
        hsv = rgb_to_hsv(rgb)
        y = (rgb * np.asarray(LUMA_709)).sum(-1)
        wh = _rolloff(_hue_dist(hsv[..., 0] * 360.0, hue[0], hue[1]),
                      roll[0], interp)
        ws = _rolloff(_range_dist(hsv[..., 1], sat[0], sat[1]),
                      roll[1], interp)
        wl = _rolloff(_range_dist(y, lum[0], lum[1]), roll[2], interp)
        return (1.0 - wh * ws * wl)[..., None]
    if method != "channel_separation":
        raise ValueError(f"Method must be distance / {KEY_METHODS}")
    kc = _vec(key, 3)
    k = int(np.argmax(kc))
    o = [i for i in range(3) if i != k]
    ref = float(kc[k] - kc[o].max())
    if not ref > 0:
        raise ValueError("Screen Color needs one clearly largest channel (pure grey can't separate a screen)")
    s = (rgb[..., k] - rgb[..., o].max(-1)) / ref
    m = 1.0 - s
    t, w = float(threshold), max(float(width), 0.0)
    if w > 0:
        a = np.clip((m - (t - w / 2.0)) / w, 0.0, 1.0)
    else:
        a = (m > t).astype(np.float64)
    return a[..., None]


# ═══════════════════════════════════════════════════════════ Despill
def despill(img, layer=DEFAULT_LAYER, spill_color="0 1 0", bias=0.5,
            luminance=0.0, mask=1.0, bias_layer="", mask_layer="",
            out_layer="", spill_layer="spill"):
    """
    Houdini's Despill: only removes spill, **no alpha output** (this is how it differs from Chroma Key).

    The docs give no formula; implemented as the standard approach that uniquely matches the parameter descriptions: k = the largest
    channel of Spill Color, the other two channels (in R, G, B order) are a, b:

        limit = a·(1 − Bias) + b·Bias        when removing green, Bias 0 leans red, 1 leans blue (docs' wording)
        new c[k] = min(c[k], limit)          spilled amount = c[k] − new c[k] >= 0

    For pure colours (a = b) Bias has no effect -- consistent with the docs' "no visible change when the colour is pure".
    Luminance: removing part of c[k] lowers Rec.709 luminance by w[k]·spill; adding back
    Luminance x this amount to each of the three channels, = 1 restores exactly the original luminance (docs: "keeps the output as bright as the original").
    Bias Layer **multiplies** Bias per pixel; Mask Layer x Mask is the old/new blend amount.
    Spill Layer outputs the removed colour (source − despilled, before brightening; scaled by the blend amount).
    The docs don't give defaults for Bias / Luminance; 0.5 / 0 are used.
    """
    if img is None:
        return CopImage()
    a = getn(img, layer)
    if a.shape[2] < 3:
        raise ValueError("Despill needs RGB")
    rgb = a[..., :3]
    kc = _vec(spill_color, 3)
    k = int(np.argmax(kc))
    o = [i for i in range(3) if i != k]
    b = np.clip(float(bias) * _layer_or_one(img, bias_layer), 0.0, 1.0)
    lim = rgb[..., o[0]] * (1.0 - b) + rgb[..., o[1]] * b
    removed = np.maximum(rgb[..., k] - lim, 0.0)
    m = np.clip(float(mask) * _layer_or_one(img, mask_layer), 0.0, 1.0)
    removed = removed * m
    spill = np.zeros_like(rgb)
    spill[..., k] = removed
    res = rgb - spill
    res = res + (float(luminance) * LUMA_709[k] * removed)[..., None]
    r = a.copy()
    r[..., :3] = res
    out = img.copy()
    put(out, str(out_layer).strip() or layer, r, img)
    if str(spill_layer).strip():
        put(out, spill_layer, spill, img)
    return out


# ═══════════════════════════════════════════════════════════ Illegal Pixel
ILLEGAL_MODES = ("blend", "zero", "highlight", "isolate")
ILLEGAL_DETECT = ("nan", "inf", "nan_inf", "custom")
ILLEGAL_RULES = ("less", "less_equal", "greater", "greater_equal", "equal")


def illegal_flags(a, detect="nan_inf", rule="less", value=0.0):
    """
    Per-**pixel** bad-pixel flags (H,W): a hit in any channel counts. The docs don't say whether multi-channel layers are judged per pixel
    or per component; Highlight / Isolate colour whole pixels, so it is per pixel throughout.
    Custom's Equal is strict equality (NaN compares false with anything, so Custom can't catch NaN).
    """
    if detect == "nan":
        f = np.isnan(a)
    elif detect == "inf":
        f = np.isinf(a)
    elif detect == "nan_inf":
        f = ~np.isfinite(a)
    elif detect == "custom":
        v = float(value)
        with np.errstate(invalid="ignore"):
            if rule == "less":
                f = a < v
            elif rule == "less_equal":
                f = a <= v
            elif rule == "greater":
                f = a > v
            elif rule == "greater_equal":
                f = a >= v
            elif rule == "equal":
                f = a == v
            else:
                raise ValueError(f"Rule must be one of {ILLEGAL_RULES}")
    else:
        raise ValueError(f"Detect must be one of {ILLEGAL_DETECT}")
    return f.any(-1)


def blend_fill(a, bad):
    """
    Bad pixel <- the mean of the **good** pixels in its 8-neighbourhood; filled ring by ring inward until full (large bad
    regions grow from the edges towards the centre). The docs only say "blend surrounding pixels" without a kernel -- an equally weighted 8-neighbourhood is the plainest
    reading. If the whole image is bad (no good pixels to borrow from), fill with 0.
    """
    H, W, C = a.shape
    val = np.where(bad[..., None], 0.0, a)
    ok = ~bad
    while not ok.all():
        pv = np.pad(val, ((1, 1), (1, 1), (0, 0)))
        pk = np.pad(ok, 1).astype(np.float64)
        s = np.zeros_like(val)
        n = np.zeros((H, W))
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                # The centre cell need not be skipped: the pixel being filled is itself bad, its val is 0 and ok is False,
                # so adding it contributes 0 to both the sum and the count
                s += pv[dy:dy + H, dx:dx + W]
                n += pk[dy:dy + H, dx:dx + W]
        new = ~ok & (n > 0)
        if not new.any():
            break
        val[new] = s[new] / n[new][:, None]
        ok = ok | new
    return val


def illegal_fix(a, mode, highlight="1 0 0", detect="nan_inf", rule="less",
                value=0.0):
    """The four Houdini modes of Illegal Pixels. Returns (new array, bad-pixel count)."""
    bad = illegal_flags(a, detect, rule, value)
    C = a.shape[2]
    if mode == "blend":
        r = blend_fill(a, bad)
    elif mode == "zero":
        r = np.where(bad[..., None], 0.0, a)
    elif mode in ("highlight", "isolate"):
        # Channel 4 is alpha: flagged pixels get 1, otherwise they are invisible after premultiplication
        col = np.ones(C)
        col[:min(C, 3)] = _vec(highlight, 3)[:min(C, 3)]
        base = a if mode == "highlight" else np.zeros_like(a)
        r = np.where(bad[..., None], col.reshape(1, 1, C), base)
    else:
        raise ValueError(f"Illegal Pixels must be replace / {ILLEGAL_MODES}")
    return r, int(bad.sum())


# ═══════════════════════════════════════════════════════════ Equalize
EQ_BY = ("stretch", "min_to_black", "max_to_white", "average", "max_length")
EQ_FIT = ("shift", "scale")
LUM_TYPES = ("sgi", "ntsc", "hdtv", "average", "max", "min", "magnitude",
             "hue", "saturation", "value", "red", "green", "blue", "alpha")
# The three sets of luminance weights are the numbers given verbatim in the docs
_LUM_W = {"sgi": (0.3086, 0.6094, 0.0820), "ntsc": (0.299, 0.587, 0.114),
          "hdtv": (0.2126, 0.7152, 0.0722)}


def luminance_of(a, kind="hdtv"):
    """
    The 14 Luminance Type modes, (H,W,C) -> (H,W). Formulas as in the docs.

    Single-channel layers are treated as grey (v,v,v) (except Magnitude: the docs explicitly say mono takes the absolute value); 2-channel
    layers get 0 for the third component. The Alpha mode needs channel 4 and errors without it (no silent 1).
    """
    if kind not in LUM_TYPES:
        raise ValueError(f"Luminance Type must be one of {LUM_TYPES}")
    C = a.shape[2]
    if kind == "alpha":
        if C < 4:
            raise ValueError("Luminance Type = Alpha needs a 4-channel layer")
        return a[..., 3]
    if kind == "magnitude":
        return np.sqrt((a * a).sum(-1))           # for a single channel this is |v|
    if C == 1:
        rgb = np.repeat(a, 3, -1)
    elif C == 2:
        rgb = np.concatenate([a, np.zeros_like(a[..., :1])], -1)
    else:
        rgb = a[..., :3]
    if kind in _LUM_W:
        return (rgb * np.asarray(_LUM_W[kind])).sum(-1)
    if kind == "average":
        return rgb.mean(-1)
    if kind == "max":
        return rgb.max(-1)
    if kind == "min":
        return rgb.min(-1)
    if kind in ("hue", "saturation", "value"):
        return rgb_to_hsv(rgb)[..., ("hue", "saturation", "value").index(kind)]
    return rgb[..., ("red", "green", "blue").index(kind)]


def _scope(C, red, green, blue, alpha):
    """Channel toggles -> boolean of length C. Single-channel layers only look at Red (it is that single channel)."""
    on = [bool(red), bool(green), bool(blue), bool(alpha)]
    return np.asarray(on[:C] + [True] * max(0, C - 4), bool)


def equalize(img, layer=DEFAULT_LAYER, by="stretch", fit_method="shift",
             lum_type="hdtv", black=0.0, white=1.0, target=0.5, red=True,
             green=True, blue=True, alpha=True, mask=1.0, mask_layer="",
             active_layer="", out_layer=""):
    """
    Houdini's Equalize: measures the minimum / maximum / mean of the image's "luminance" (Luminance Type),
    then shifts or scales **all selected channels** together so that statistic lands on the target. Not histogram
    equalization (that is COP Histogram's equalize).

        stretch       (c − min) · (White − Black)/(max − min) + Black
        min_to_black  shift: c + (Black − min)     scale: c · Black/min
        max_to_white  shift: c + (White − max)     scale: c · White/max
        average       shift: c + (Target − avg)    scale: c · Target/avg
        max_length    c · White/max                (docs: scale so the maximum luminance = White)

    Fit Method only matters for the middle three modes (docs' wording). Statistics are taken only over pixels where Active Layer > 0.5.
    When the denominator is 0 (scale on an all-black image, stretch on a constant image) that step degenerates to no scaling
    -- no inf.

    Not specified in the docs: whether statistics are per channel or by luminance (here one number is measured by Luminance Type and all
    channels use the same coefficients -- per-channel stretching would change hue, and Luminance Type would then be pointless);
    the defaults of Luminance Type and the Alpha toggle (HDTV / on).
    """
    if img is None:
        return CopImage()
    if by not in EQ_BY:
        raise ValueError(f"Equalize By must be one of {EQ_BY}")
    if fit_method not in EQ_FIT:
        raise ValueError(f"Fit Method must be one of {EQ_FIT}")
    a = getn(img, layer)
    L = luminance_of(a, lum_type)
    act = str(active_layer).strip()
    if act:
        sel = getn(img, act)[..., 0] > 0.5
        if not sel.any():
            raise ValueError(f"Active Layer '{act}' has no pixels > 0.5")
        Ls = L[sel]
    else:
        Ls = L.reshape(-1)
    lmin, lmax, lavg = float(Ls.min()), float(Ls.max()), float(Ls.mean())
    bk_, wh_, tg_ = float(black), float(white), float(target)
    mul, add = 1.0, 0.0
    if by == "stretch":
        if lmax > lmin:
            mul = (wh_ - bk_) / (lmax - lmin)
        add = bk_ - lmin * mul
    elif by == "max_length":
        if lmax != 0:
            mul = wh_ / lmax
    else:
        cur, goal = {"min_to_black": (lmin, bk_), "max_to_white": (lmax, wh_),
                     "average": (lavg, tg_)}[by]
        if fit_method == "shift":
            add = goal - cur
        elif cur != 0:
            mul = goal / cur
    new = a * mul + add
    on = _scope(a.shape[2], red, green, blue, alpha)
    m = float(mask) * _layer_or_one(img, mask_layer)
    m = np.broadcast_to(np.asarray(m, np.float64), a.shape[:2])[..., None]
    r = np.where(on.reshape(1, 1, -1), a + (new - a) * m, a)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, r, img)


# ═══════════════════════════════════════════════════════════ Histogram (drawn)
HIST_PLOT_MODES = ("colored_bars", "separate_bars", "graph")
HIST_OUTSIDE = ("discard", "clamp")


def histogram_counts(a, buckets=256, lo=0.0, hi=1.0, outside="discard",
                     scope=None, active=None):
    """
    (H,W,C) -> (counts (4, buckets) of R/G/B/A, number of pixels counted).

    bucket = floor((v − Min)/(Max − Min) · Buckets); v exactly equal to Max goes into the last bucket
    (otherwise pure white on a 0..1 image would always be dropped -- not specified in the docs, our choice). Discard drops
    out-of-range values, Clamp merges them into the first / last bucket. NaN is never counted. Missing channels and disabled channels
    have count 0.
    """
    if outside not in HIST_OUTSIDE:
        raise ValueError(f"Outside Values must be one of {HIST_OUTSIDE}")
    n = int(buckets)
    if n < 1:
        raise ValueError("Buckets must be at least 1")
    lo, hi = float(lo), float(hi)
    if not hi > lo:
        raise ValueError("Maximum must be greater than Minimum")
    H, W, C = a.shape
    sel = np.ones((H, W), bool) if active is None else active
    cnt = np.zeros((4, n), np.float64)
    for c in range(min(C, 4)):
        if scope is not None and not scope[c]:
            continue
        v = a[..., c][sel]
        v = v[~np.isnan(v)]
        if outside == "clamp":
            v = np.clip(v, lo, hi)
        else:
            v = v[(v >= lo) & (v <= hi)]
        b = np.minimum(np.floor((v - lo) / (hi - lo) * n).astype(np.int64),
                       n - 1)
        cnt[c] = np.bincount(b, minlength=n)
    return cnt, int(sel.sum())


def histogram_plot(img, layer=DEFAULT_LAYER, mode="colored_bars", buckets=256,
                   lo=0.0, hi=1.0, outside="discard", scale=10.0, red=True,
                   green=True, blue=True, alpha=True, active_layer="",
                   out_layer="histogram"):
    """
    Houdini's Histogram: **draws** a layer's histogram as an image. Returns (image, counts image).

    Each bucket's value = pixels in the bucket / total pixels counted x Scale (docs: bar height or brightness is by
    "percentage of total pixels"). Column x maps to bucket floor((x + 0.5)/W · Buckets).

        colored_bars   each column's colour = each channel's share in this bucket (one horizontal colour band)
        separate_bars  one horizontal band per channel, greyscale; R at the bottom, alpha (if any) at the top
        graph          bar chart: the share sets the bar **height** (full image height = 1), each channel drawn in
                       its own channel, so the R/G/B bars overlap

    The counts image follows the docs: width = Buckets, height 5, the four rows bottom to top are raw counts of R, G, B, A,
    and column 0 of the top row is the total number of pixels counted. Only pixels with Active Layer >= 0.5 are counted
    (note it is >=; the docs for Equalize say >).

    Not specified in the docs: defaults of Buckets / Scale (256 / 10); whether pixels dropped by Discard still count
    towards the "total" (here they do -- the total is the number of pixels counted, regardless of dropping); the alpha channel of the output layer
    itself in separate_bars (1, otherwise invisible).
    """
    if img is None:
        return CopImage(), CopImage()
    if mode not in HIST_PLOT_MODES:
        raise ValueError(f"Mode must be one of {HIST_PLOT_MODES}")
    a = getn(img, layer)
    H, W, C = a.shape
    on = _scope(C, red, green, blue, alpha)
    act = str(active_layer).strip()
    sel = getn(img, act)[..., 0] >= 0.5 if act else None
    cnt, total = histogram_counts(a, buckets, lo, hi, outside, on, sel)
    n = cnt.shape[1]
    frac = cnt / total * float(scale) if total else np.zeros_like(cnt)
    bx = ((np.arange(W) + 0.5) / W * n).astype(np.int64)     # always < n, no clamp needed
    K = min(C, 4)
    r = np.zeros((H, W, C))
    if mode == "colored_bars":
        r[..., :K] = frac[:K, bx].T[None, :, :]
    elif mode == "separate_bars":
        band = np.arange(H) * K // H                        # always < K
        g = frac[:K][band][:, bx]                       # (H, W)
        r[..., :min(C, 3)] = g[..., None]
        if C >= 4:
            r[..., 3] = 1.0
    else:
        yc = ((np.arange(H) + 0.5) / H)[:, None, None]
        r[..., :K] = (yc <= frac[:K, bx].T[None, :, :]).astype(np.float64)
    out = img.copy()
    put(out, str(out_layer).strip() or "histogram", r, img)
    craw = np.zeros((5, n, 1))
    craw[:4, :, 0] = cnt
    craw[4, 0, 0] = total
    cimg = CopImage(n, 5)
    put(cimg, "counts", craw, img)
    return out, cimg


# ═══════════════════════════════════════════════════════════ Compare (outputs a mask)
CMP_OPS = ("equal", "not_equal", "greater", "greater_equal", "less",
           "less_equal")
CMP_COMPONENTS = ("all", "any")
CMP_FALLOFF = ("none", "linear", "elendt")


def _soft(x, falloff):
    """Shapes the transition amount x in [0,1] by Falloff."""
    x = np.clip(x, 0.0, 1.0)
    if falloff == "linear":
        return x
    return x * x * (3.0 - 2.0 * x)


def compare_mask(img, layer_a=DEFAULT_LAYER, layer_b="", value=0.0,
                 op="equal", components="all", tolerance=0.0,
                 tolerance_layer="", falloff="none", out_layer="mask"):
    """
    Houdini's Compare: compares A and B per pixel, outputs a 0..1 single-channel mask. With Layer B empty it compares against
    Comparison Value (docs: used when the second input is not connected, compared against each channel of A).

    Let d = A − B, tol = Tolerance (per pixel from Tolerance Layer if given). Docs:
    "tolerance is **two-sided** for equality comparisons (==, !=) and **one-sided** for strict inequalities (>, <)";
    Falloff governs pixels that "**fail** the comparison but fall within tolerance" (None is a hard cut, Linear goes from 1
    linearly down to 0). So pixels that pass are always 1, and tolerance only adds a transition on the failing side:

        ==   pass = (d == 0); failing ones within |d| < tol: Linear 1 − |d|/tol
             None (hard cut): |d| <= tol all count as 1
        >    pass = (d > 0); failing ones within −tol < d <= 0: Linear 1 + d/tol
             None: d >= −tol all count as 1 (the tolerance edge is included, consistent with == 's |d| <= tol)
        >=   same as >, except d = 0 itself passes (the two only differ when tol = 0)
        <, <=  same as >, >= with d negated
        !=   1 − (==): within tolerance counts as "equal", so the not-equal mask drops there

    The Elendt docs only say "an S-curve smooth at both ends" without a formula; smoothstep is used instead (Houdini's
    Elendt kernel is not this curve, values in the middle differ slightly). Components: All takes the per-channel
    minimum, Any the maximum (AND / OR for hard masks).

    Not specified in the docs, our choices: whether tolerance still applies in None mode (yes: hard cut at the tolerance edge, otherwise
    == is almost useless on float images); tolerance for >= / <= (same as strict inequality, one-sided); tolerance for != (the
    complement of ==); whether Tolerance Layer replaces or multiplies Tolerance (replaces).
    """
    if img is None:
        return CopImage()
    if op not in CMP_OPS:
        raise ValueError(f"True If must be one of {CMP_OPS}")
    if components not in CMP_COMPONENTS:
        raise ValueError(f"Components must be one of {CMP_COMPONENTS}")
    if falloff not in CMP_FALLOFF:
        raise ValueError(f"Falloff must be one of {CMP_FALLOFF}")
    A = getn(img, layer_a)
    sb = str(layer_b).strip()
    if sb:
        B = getn(img, sb)
        if B.shape[2] == 1:
            B = np.broadcast_to(B, A.shape)
        elif B.shape[2] != A.shape[2]:
            raise ValueError(f"'{sb}' has {B.shape[2]} channels, '{layer_a}' has "
                             f"{A.shape[2]} channels; they don't match (B may be single-channel)")
    else:
        B = float(value)
    d = A - B
    st = str(tolerance_layer).strip()
    tol = np.maximum(getn(img, st)[..., :1] if st else float(tolerance), 0.0)
    tol = np.broadcast_to(np.asarray(tol, np.float64), d.shape)
    pos = tol > 0
    safe = np.where(pos, tol, 1.0)

    def eq(dd):
        if falloff == "none":
            return (np.abs(dd) <= tol).astype(np.float64)
        return np.where(pos, _soft(1.0 - np.abs(dd) / safe, falloff),
                        (dd == 0).astype(np.float64))

    def gt(dd, strict):
        hard = ((dd > 0) if strict else (dd >= 0)).astype(np.float64)
        if falloff == "none":
            return np.where(pos, (dd >= -tol).astype(np.float64), hard)
        return np.where(pos, _soft(1.0 + dd / safe, falloff), hard)

    m = {"equal": lambda: eq(d), "not_equal": lambda: 1.0 - eq(d),
         "greater": lambda: gt(d, True), "less": lambda: gt(-d, True),
         "greater_equal": lambda: gt(d, False),
         "less_equal": lambda: gt(-d, False)}[op]()
    r = m.min(-1) if components == "all" else m.max(-1)
    out = img.copy()
    return put(out, str(out_layer).strip() or "mask", r, img)


# ═══════════════════════════════════════════════════════════ Mono to RGB
MONO_OUTSIDE = ("clamp", "repeat")


def mono_to_rgb(img, layer=DEFAULT_LAYER, compute_range=False, in_min=0.0,
                in_max=1.0, out_min=0.0, out_max=1.0, scale_by_value=False,
                outside="clamp", ramp="0:0,0,0  1:1,1,1", ramp_mode="linear",
                ramp_layer="", out_layer=""):
    """
    Houdini's Mono to RGB: a single-channel value goes through a **ramp** to become RGB (not copying the channel three times
    -- that is COP Channel Convert's mono_to_rgb).

        t   = (v − Input Min)/(Input Max − Input Min)     with Compute Range, uses the image's min / max
        col = ramp(t)          Clamp at End clamps to the ends; Repeat makes out-of-range t cycle
        col = Output Min + col · (Output Max − Output Min)  maps the ramp's 0 / 1 to these two intensities
        col *= t (Scale by Value; uses the **unclamped** t, so out of range it keeps getting brighter -- docs' wording)

    If Ramp Layer is given, the Ramp parameter is not used; colours are instead taken horizontally from **the row at the vertical centre**
    of that layer (docs: sampled along a horizontal line through the image centre). The docs don't specify the sampling; here t = 0 / 1 map to
    the leftmost / rightmost pixel, linearly interpolated in between. When Input Max = Input Min, t is 0.
    Repeat takes the fractional part only for t **outside** the range: t = 1 inside the range is still the ramp's end (otherwise
    pixels exactly equal to Input Max would jump back to the start).
    """
    if img is None:
        return CopImage()
    if outside not in MONO_OUTSIDE:
        raise ValueError(f"Outside Range must be one of {MONO_OUTSIDE}")
    v = getn(img, layer)[..., 0]
    H, W = v.shape
    if compute_range:
        lo, hi = float(v.min()), float(v.max())
    else:
        lo, hi = float(in_min), float(in_max)
    t = (v - lo) / (hi - lo) if hi != lo else np.zeros_like(v)
    if outside == "clamp":
        tc = np.clip(t, 0.0, 1.0)
    else:
        # Take the fractional part, except t = 1 inside the range (stays at the ramp end). Taking the fraction in [0,1) leaves t itself unchanged
        tc = np.where(t == 1.0, 1.0, t - np.floor(t))
    rl = str(ramp_layer).strip()
    if rl:
        src = getn(img, rl)
        row = src[src.shape[0] // 2]
        if row.shape[1] < 3:
            row = np.repeat(row[:, :1], 3, -1)
        p = tc.reshape(-1) * (row.shape[0] - 1)
        i = np.floor(p).astype(np.int64)            # tc ∈ [0,1] → i ∈ [0, W−1]
        j = np.minimum(i + 1, row.shape[0] - 1)
        f = (p - i)[:, None]
        col = row[i, :3] * (1.0 - f) + row[j, :3] * f
    else:
        from ..ramp import parse as _parse, apply as _apply
        pos, val = _parse(str(ramp), 3)
        col = _apply(tc.reshape(-1), pos, val, ramp_mode)
    col = float(out_min) + col * (float(out_max) - float(out_min))
    if scale_by_value:
        col = col * t.reshape(-1, 1)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, col.reshape(H, W, 3),
               img)


# ═══════════════════════════════════════════════════════════ Mono to HeightField
def mono_to_height(img, layer=DEFAULT_LAYER, height_scale=1.0,
                   height_offset=0.0, out_layer="height"):
    """
    Houdini's Mono to HeightField: height = value x Height Scale + Height Offset.
    The docs only say "scale and offset" and **don't say in which order**; multiply first then add (consistent with the HeightField nodes'
    Scale / Offset habit; Offset's unit is the final height). Houdini also sets the layer's Type Info to
    height; our layers have no type metadata, so the convention relies on the layer name (written to height by default).
    """
    if img is None:
        return CopImage()
    v = getn(img, layer)[..., :1]
    out = img.copy()
    return put(out, str(out_layer).strip() or "height",
               v * float(height_scale) + float(height_offset), img)
