"""
Fractal Sample (Copernicus) -- added in pcg100 c3_noise.

Uses a source image as the "basis function": scale it down, rotate, jitter and flip it octave by octave, then stack them. Same
recipe as fractal noise, except each octave samples an image instead of noise. The mapping table used to point this at Attribute Noise (geometry attribute
noise), which is something else, hence a separate node.

━━ How each octave o (starting at 0) samples
    s_o = Lacunarity^o
    θ_o = Angle·(o+1)                      Per Octave (docs: at 30° the third octave is 90°)
        = Angle·(2r − 1)                   Random (docs: -Angle ~ +Angle)
    flip: with Random Flip X / Y on, each octave flips its own coin
    jitter: one [−Jitter, Jitter]² uv offset per octave
    uv_src = R(θ_o)·F_o·((uv − ½)·s_o) + ½ + j_o

Scale / rotate / flip about the image centre. With Maintain Tileable, Lacunarity is rounded to an integer (>= 1) and the angle to a multiple of
90° -- integer scaling and 90° rotation then map the unit cell back onto integer cells, so with Wrap border a tileable source gives
a tileable result (docs: it does not create tiling; the source must already tile).

━━ How octaves are stacked (the docs only give the semantics; the formulas are our own)
    weight w_o = Roughness^o; Bias is subtracted from samples first (docs: "the midpoint subtracted from each sample so the result is centred on 0")
    add       Σ w_o (S_o − b) / Σ w_o
    subtract  [w_0(S_0 − b) − Σ_{o≥1} w_o(S_o − b)] / Σ w_o
    maximum   max_o w_o (S_o − b)                           (not normalized)
    over      S_0 over S_1 over ... (premultiplied RGBA, each layer multiplied by w_o first; Bias not subtracted)
    With Offset with Bias on, b is added back at the end.

    Normalization (dividing by Σw) is our own addition: with 1 octave and zero angle / jitter the output is bit-identical to the source,
    and with several octaves the value range matches the source. The Houdini docs mention "after weight and gain" without saying what gain
    is; not implemented.

━━ Not implemented
    Border is only clamp / wrap / black (Houdini uses the layer's own border attribute, with more types)
    Filter is only bilinear / point; Box and higher area filters are not done -- high octaves are heavy minification and will alias
    the three optional input layers octaves / lacunarity / roughness (per-pixel parameter multipliers) are not implemented
"""
from __future__ import annotations

import math

import numpy as np

from .core import check_res
from .filters import sample as _bilinear, BORDERS
from .pixel import getn, put
from .pattern import rnd
from . import noisepost as _pp
from . import backend as bk

BLEND_MODES = ("add", "subtract", "maximum", "over")
ANGLE_MODES = ("per_octave", "random")
FILTERS = ("bilinear", "point")


def _point(a, u, v, border):
    """Nearest-pixel sampling (same uv -> pixel-centre conversion as filters.sample)."""
    H, W = a.shape[:2]
    j = np.floor(u * W).astype(np.int64)
    i = np.floor(v * H).astype(np.int64)
    if border == "wrap":
        return a[i % H, j % W]
    ok = (i >= 0) & (i < H) & (j >= 0) & (j < W)
    r = a[np.clip(i, 0, H - 1), np.clip(j, 0, W - 1)]
    if border == "black":
        r = np.where(ok[..., None], r, 0.0)
    return r


def octave_params(o, angle, angle_mode, jitter, flip_x, flip_y, seed,
                  tileable):
    """(θ radians, fx, fy, jx, jy) for octave o. Random numbers hash (seed, o), independent of resolution."""
    r = [float(rnd(np.array([o]), seed, k)[0]) for k in range(5)]
    if angle_mode == "per_octave":
        th = float(angle) * (o + 1)
    else:
        th = float(angle) * (2.0 * r[0] - 1.0)
    if tileable:
        th = round(th / 90.0) * 90.0
    fx = -1.0 if (flip_x and r[1] < 0.5) else 1.0
    fy = -1.0 if (flip_y and r[2] < 0.5) else 1.0
    jx = float(jitter) * (2.0 * r[3] - 1.0)
    jy = float(jitter) * (2.0 * r[4] - 1.0)
    return math.radians(th), fx, fy, jx, jy


def fractal_sample(img, source_layer="C", max_octaves=4, lacunarity=2.0,
                   roughness=0.5, bias=0.5, offset_with_bias=True,
                   blend_mode="add", border="wrap", filter_="bilinear",
                   maintain_tileable=False, jitter=0.0, angle=0.0,
                   angle_mode="per_octave", flip_x=False, flip_y=False,
                   seed=0, out_layer="fractal", post=None):
    if img is None or not len(img):
        raise ValueError("Fractal Sample needs cop (source layer)")
    if blend_mode not in BLEND_MODES:
        raise ValueError(f"Blend Mode must be one of {BLEND_MODES}")
    if angle_mode not in ANGLE_MODES:
        raise ValueError(f"Angle mode must be one of {ANGLE_MODES}")
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    if filter_ not in FILTERS:
        raise ValueError(f"Filter must be one of {FILTERS}")
    src = getn(img, source_layer)
    H, W, C = src.shape
    check_res(W, H)
    if blend_mode == "over" and C != 4:
        raise ValueError("Over only makes sense for RGBA (4 channels) (the docs have the same restriction)")
    lac = float(lacunarity)
    if maintain_tileable:
        lac = float(max(1, round(lac)))
    n = max(1, int(max_octaves))
    w = [float(roughness) ** o for o in range(n)]
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    qu, qv = (J + 0.5) / W - 0.5, (I + 0.5) / H - 0.5
    b = float(bias)
    acc = None
    for o in range(n):
        th, fx, fy, jx, jy = octave_params(o, angle, angle_mode, jitter,
                                           flip_x, flip_y, seed,
                                           maintain_tileable)
        s = lac ** o
        x, y = qu * s * fx, qv * s * fy
        c, sn = math.cos(th), math.sin(th)
        u = c * x - sn * y + 0.5 + jx
        v = sn * x + c * y + 0.5 + jy
        S = (_bilinear(src, u, v, border) if filter_ == "bilinear"
             else _point(src, u, v, border))
        if blend_mode == "over":
            layer = S * w[o]
            acc = layer if acc is None else acc + layer * (1.0 - acc[..., 3:4])
            continue
        t = w[o] * (S - b)
        if acc is None:
            acc = t
        elif blend_mode == "add":
            acc = acc + t
        elif blend_mode == "subtract":
            acc = acc - t
        else:
            acc = np.maximum(acc, t)
    if blend_mode in ("add", "subtract"):
        acc = acc / sum(w)
    if blend_mode != "over" and offset_with_bias:
        acc = acc + b
    acc = _pp.run(bk.NUMPY, acc, post or {})
    out = img.copy()
    put(out, str(out_layer).strip() or "fractal", acc, img)
    return out

