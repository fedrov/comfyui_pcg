"""
Splat Map -- terrain -> a set of material masks that **sum to 1 everywhere**.

The terrain family can already produce any single mask (Mask by Feature), but what downstream needs -- engine
terrain layers, regional prompts for diffusion models, segmentation ControlNet -- is **a complete set of mutually exclusive regions**:
which material each pixel belongs to and how much of each, summing to 1. Single masks are computed independently; stacked together, some
places sum to 2 (both snow and rock), others to 0 (nothing).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layered compositing: later ones cover earlier ones
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With priorities from low to high m_0 ... m_{n−1}, cover from the highest down:

    eff_{n−1} = m_{n−1}
    eff_i     = m_i · Π_{j>i} (1 − m_j)
    remainder = Π_j (1 − m_j)

This is "over-ing layer after layer" in image software. Σ eff + remainder = 1 is a **telescoping sum** and holds
exactly (1e-16 off in tests). Masks are soft; in transition bands two materials share proportionally, no hard cut.

Five default materials (priority low to high):

    grass     remainder (places that are nothing else)
    sediment  deposits: uses the debris layer (thermal erosion output) if given; otherwise "low
              flat ground" (slope < flat_angle and normalized height < sediment_height)
    rock      steep slopes: slope > rock_angle (soft edge rock_falloff degrees)
    snow      above the snow line and not too steep (snow can't stick to very steep places, rock shows through -- so snow
              has higher priority than rock, but snow's own mask is multiplied by a "not steep" term)
    water     lake (lake layer > lake_min) or river (river layer). Highest: the water surface covers everything

Height is normalized to 0~1 over **this image** by default (min~max), so a snow line of 0.75 means "the top
quarter". When generating in tiles each tile has a different min/max and they won't match -- then switch to absolute, and thresholds are
the height values themselves (world height multiplied by Strength).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Output layers
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  <prefix>_<material>   one layer per material, 0~1, the five layers sum to 1
  <prefix>_id       index of the material with the largest share per pixel (0 = grass ... 4 = water). Fed into
                    Control Image's id mode it is a segmentation map (segmentation ControlNet /
                    union's segment mode)
  <prefix>_rgba     rock / snow / sediment / water packed into 4 channels, grass implicitly
                    1 − the rest. This is the common packing for engine terrain layers

Computed in numpy (this is the exit of the chain; results have to go back to the CPU anyway), layers are put back on the original backend.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from .analysis import _world_derivs
from .terrain import band

MATERIALS = ("grass", "sediment", "rock", "snow", "water")
HEIGHT_MODES = ("normalized", "absolute")


def _np(a):
    return np.asarray(bk.backend_of(a).to_numpy(a)
                      if not isinstance(a, np.ndarray) else a, np.float64)


def compose(masks):
    """
    Layered compositing. masks are in priority **from low to high**, each (H,W), clamped to 0~1.

    Returns (list of eff, in the same order as masks; remainder). Σ eff + remainder = 1.
    """
    effs = [None] * len(masks)
    cover = None
    for i in range(len(masks) - 1, -1, -1):
        m = np.clip(np.asarray(masks[i], np.float64), 0.0, 1.0)
        if cover is None:
            cover = np.ones_like(m)
        effs[i] = m * cover
        cover = cover * (1.0 - m)
    return effs, cover


def splat_map(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
              tile=False, height_mode="normalized",
              rock_angle=38.0, rock_falloff=6.0,
              snow_line=0.75, snow_falloff=0.08, snow_max_slope=50.0,
              sediment_layer="debris", sediment_ref=0.0,
              flat_angle=8.0, sediment_height=0.3,
              water_layers="lake river", lake_min=1e-4, lake_falloff=0.0,
              prefix="splat", keep=True):
    """Returns (image, report dict: area share of each material). Parameters are described in the file header."""
    if img is None:
        return CopImage(), {}
    if height_mode not in HEIGHT_MODES:
        raise ValueError(f"Height Mode must be one of {HEIGHT_MODES}")
    xp = img.backend
    s_ = float(strength)
    h = _np(img.need(layer))[:, :, 0] * s_
    _, hx, hy, _, _, _ = _world_derivs(img, layer, strength, world_size,
                                       bool(tile))
    slope = np.degrees(np.arctan(np.hypot(_np(hx), _np(hy))))
    slope = slope.reshape(h.shape)                # the derivative is (H,W,1)
    if height_mode == "normalized":
        lo, hi = float(h.min()), float(h.max())
        hn = (h - lo) / (hi - lo) if hi > lo else np.zeros_like(h)
    else:
        hn = h

    # rock: steep slopes
    rock = band(np, slope, float(rock_angle), math.inf, float(rock_falloff))
    # snow: above the snow line × not too steep
    snow = band(np, hn, float(snow_line), math.inf, float(snow_falloff)) \
        * band(np, slope, -math.inf, float(snow_max_slope),
               float(rock_falloff))
    # sediment
    sl = str(sediment_layer).strip()
    if sl and sl in img:
        d = np.maximum(_np(img.need(sl))[:, :, 0], 0.0)
        ref = float(sediment_ref)
        if not ref > 0:
            pos = d[d > 0]
            ref = float(np.percentile(pos, 90)) if pos.size else 1.0
        t = np.clip(d / ref, 0.0, 1.0)
        sediment = t * t * (3 - 2 * t)
        sed_src = f"layer {sl}"
    else:
        sediment = band(np, slope, -math.inf, float(flat_angle), 2.0) \
            * band(np, hn, -math.inf, float(sediment_height),
                   float(snow_falloff))
        sed_src = "low flat ground"
    # water
    water = np.zeros_like(h)
    used = []
    for name in str(water_layers).split():
        if name not in img:
            continue
        a = _np(img.need(name))[:, :, 0]
        if name == "lake" or name.startswith("lake"):
            f = float(lake_falloff)
            w = band(np, a, float(lake_min), math.inf, f) if f > 0 \
                else (a > float(lake_min)).astype(np.float64)
        else:
            w = np.clip(a, 0.0, 1.0)
        water = np.maximum(water, w)
        used.append(name)

    effs, rest = compose([sediment, rock, snow, water])
    parts = [rest] + effs                         # same order as MATERIALS
    out = img.copy() if keep else CopImage(img.xres, img.yres)
    p = str(prefix).strip() or "splat"
    for name, a in zip(MATERIALS, parts):
        out.set(f"{p}_{name}", xp.asarray(a[:, :, None]))
    stack = np.stack(parts, -1)
    out.set(f"{p}_id", xp.asarray(
        np.argmax(stack, -1).astype(np.float64)[:, :, None]))
    out.set(f"{p}_rgba", xp.asarray(np.stack(
        [parts[2], parts[3], parts[1], parts[4]], -1)))
    rep = {name: float(a.mean()) for name, a in zip(MATERIALS, parts)}
    rep["_sediment_source"] = sed_src
    rep["_water_layers"] = used
    return out, rep
