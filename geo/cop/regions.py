"""
The pure-mask part of Regional Prompt: parse "layer: prompt", composite layers, colourize the preview.

CLIP encoding and CONDITIONING assembly live in nodes.py (that part depends on ComfyUI objects); this file
is numpy only, so tests can verify it pixel by pixel.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why by default the base prompt only covers "the remaining area"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When ComfyUI samples, the masked conditionings are **averaged per pixel, weighted by mask value**
(comfy/samplers.py: Σ prediction·weight / (Σ weight + 1e-37)). Therefore:

  · a pixel covered by **no entry at all** -> the denominator is only 1e-37 and the prediction there is 0 -- the output has a
    smeared hole, with no error. So the regions must **cover everything**
  · when the base prompt has no mask (global) it takes part in the average at every pixel, and the regional prompts'
    weight is diluted by half -- the "clear river" entry on the river channel keeps only half its persuasive power

Hence the default is remainder: the base prompt only gets "the remainder", and all masks sum to exactly 1 everywhere.
global is kept for the "overall style words" usage.

Region masks themselves have two legitimate sources, one mode each:

  normalized (default)  the input is **already a partition** (Splat Map output): used as is, remainder =
                     1 − Σ. If somewhere the sum exceeds 1, it is normalized by the sum there -- still
                     = 1 everywhere. The first version only had layered, and using it to composite splat layers was
                     **double compositing**: in a splat transition band rock 0.5, water 0.5, layered pressed rock down to
                     0.25, and the remainder gained 0.25 out of nowhere that went to base (caught by tests)
  layered            the inputs are **independent** masks (several Mask by Feature): composited in the order
                     written, later entries cover earlier ones

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Syntax
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One `layer: prompt` per line, split at the first colon (the prompt may contain more colons). Empty lines and lines starting
with `#` are skipped. **Later lines have higher priority** -- same direction as Splat Map's material order: put water
last and it covers everything. A missing layer raises an error listing the available layers instead of silently becoming an empty mask.
"""
from __future__ import annotations

import numpy as np

from . import backend as bk
from .splat import compose
from .control import id_palette

MODES = ("normalized", "layered")
BASE_MODES = ("remainder", "global")


def parse(text):
    """-> [(layer name, prompt), ...], order = written order = priority from low to high."""
    out = []
    for n, raw in enumerate(str(text).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"line {n} has no colon: '{line[:40]}' -- write it as "
                             f"'layer: prompt'")
        name, prompt = line.split(":", 1)
        name, prompt = name.strip(), prompt.strip()
        if not name:
            raise ValueError(f"line {n} has no layer name before the colon")
        out.append((name, prompt))
    return out


def _layer(img, name):
    if name not in img:
        have = ", ".join(sorted(img.names))
        raise KeyError(f"COP has no layer '{name}'. Available layers: {have}")
    a = img.need(name)
    return np.clip(np.asarray(bk.backend_of(a).to_numpy(a), np.float64)
                   [:, :, 0], 0.0, 1.0)


def region_masks(img, entries, mode="layered", feather=0.0):
    """
    -> (list of effective masks per entry, remainder). COP orientation (row 0 = bottom).

    normalized: as is, normalized by the sum where Σ > 1, remainder = 1 − Σ. layered: layered compositing.
    Both satisfy Σ + remainder = 1. With feather > 0 each layer is Gaussian-blurred (pixels) first.
    """
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    masks = [_layer(img, name) for name, _ in entries]
    if float(feather) > 0 and masks:
        from .core import CopImage
        from .filters import blur
        tmp = CopImage(img.xres, img.yres,
                       {f"m{i}": m[:, :, None] for i, m in enumerate(masks)})
        tmp = blur(tmp, float(feather))
        masks = [np.clip(np.asarray(tmp.need(f"m{i}"), np.float64)[:, :, 0],
                         0.0, 1.0) for i in range(len(masks))]
    if not masks:
        return [], np.ones((img.yres, img.xres))
    if mode == "layered":
        return compose(masks)
    tot = np.sum(np.stack(masks, 0), 0)
    k = np.where(tot > 1.0, 1.0 / np.where(tot > 1.0, tot, 1.0), 1.0)
    effs = [m * k for m in masks]
    rest = np.clip(1.0 - tot * k, 0.0, 1.0)
    return effs, rest


def preview(effs, rest, saturation=0.65, value=0.95):
    """
    Mix the effective masks by their share into one (H,W,3) image, COP orientation. The remainder is dark grey. Colours use the
    same golden-angle palette as Control Image's id mode (entry i = id i+1).
    """
    if not effs:
        return np.repeat((rest * 0.25)[:, :, None], 3, -1)
    pal = id_palette(np.arange(1, len(effs) + 1), saturation, value)
    out = rest[:, :, None] * 0.25
    for i, e in enumerate(effs):
        out = out + e[:, :, None] * pal[i][None, None, :]
    return np.clip(out, 0.0, 1.0)
