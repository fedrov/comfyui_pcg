"""
The bridge between COP and ComfyUI IMAGE.

In the whole plugin, **only this file** may contain `[::-1]`. Inside COP row 0 is the bottom (v points up,
consistent with uv / Houdini); in ComfyUI / PIL / most image libraries row 0 is the top. Flipping must be
concentrated at the boundary -- if it is scattered around, "how many times did we flip" can never be answered again, and the symptom
(image upside down) is far too easy to paper over with "just flip it once more".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Clamping on export is **optional**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ComfyUI's IMAGE convention is 0-1, so it clamps by default. But SDF, normal and displacement layers naturally have
negative values and values above 1; clamping them when you just want a quick Preview gives all black / all white. So:

    clamp=True   plain clamp to 0-1 (default, for normal colour layers)
    normalize    stretch this image's min/max to 0-1 (for viewing SDFs / height fields)
    signed       map [−1,1] to [0,1] (for viewing normals / signed noise)

`normalize` is a **data-dependent** mapping: feed the same node a different frame and the mapping changes. So it is only
for viewing, not for exporting assets -- stating that clearly in the node docs is more useful than a "smarter" default.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
How channel counts are padded
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMAGE needs 3 channels. 1 channel is **copied** three times (greyscale, the only sensible interpretation), 4 channels
drop alpha (ComfyUI's alpha goes through the separate MASK type), 2 channels get a 0 appended.

MASK is provided as well: ComfyUI's MASK is (B,H,W), taking channel 0 of the given layer.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk

EXPORT_MODES = ("clamp", "raw", "normalize", "signed")


def _to_numpy(image):
    """ComfyUI's IMAGE may be a torch tensor, or already numpy."""
    if hasattr(image, "cpu"):
        return image.cpu().numpy()
    return np.asarray(image)


def from_comfy(image, name=DEFAULT_LAYER, batch_index=0, flip=True,
               device="numpy"):
    """
    ComfyUI IMAGE (B,H,W,C) -> CopImage.

    **v is flipped once here**: ComfyUI's row 0 is the top, COP's row 0 is the bottom.
    """
    a = _to_numpy(image)
    if a.ndim == 3:
        a = a[None]
    if a.ndim != 4:
        raise ValueError(f"IMAGE should be (B,H,W,C), got {a.shape}")
    i = int(np.clip(batch_index, 0, a.shape[0] - 1))
    f = np.asarray(a[i], np.float32)
    if flip:
        f = f[::-1]
    f = np.ascontiguousarray(f)
    xp = bk.get(device, f.shape[0] * f.shape[1], 1, f.shape[2])
    return CopImage(f.shape[1], f.shape[0],
                    {str(name).strip() or DEFAULT_LAYER: xp.asarray(f)})


def _fit3(a):
    """Any channel count -> 3 channels. 1 channel copied to greyscale, 4 channels drop alpha, 2 channels get a 0 appended."""
    c = a.shape[2]
    if c == 3:
        return a
    if c == 1:
        return np.repeat(a, 3, axis=2)
    if c >= 4:
        return a[..., :3]
    return np.concatenate([a, np.zeros(a.shape[:2] + (3 - c,), np.float32)],
                          -1)


def _map_range(a, mode):
    if mode == "raw":
        return a
    if mode == "clamp":
        return np.clip(a, 0.0, 1.0)
    if mode == "signed":
        return np.clip(a * 0.5 + 0.5, 0.0, 1.0)
    if mode == "normalize":
        lo, hi = float(a.min()), float(a.max())
        if hi - lo < 1e-12:
            return np.zeros_like(a)
        return (a - lo) / (hi - lo)
    raise ValueError(f"Export Mode must be one of {EXPORT_MODES}")


def to_comfy(img, name=DEFAULT_LAYER, mode="clamp", flip=True):
    """
    One layer of a CopImage -> ComfyUI IMAGE (1,H,W,3) numpy array.

    If the layer is on the GPU it is **moved back to the CPU first**. Reason: ComfyUI's IMAGE is generally passed between nodes
    as a CPU tensor (Preview / Save / most custom nodes call `.numpy()` directly); leaving it in
    VRAM would blow up in someone else's code. Cases that really need to save this transfer (COP feeding a sampler directly) must
    wait until downstream explicitly supports it; we can't gamble on it here.
    """
    if img is None or len(img) == 0:
        return np.zeros((1, 1, 1, 3), np.float32)
    lay = img.need(str(name).strip() or DEFAULT_LAYER)
    a = np.asarray(bk.backend_of(lay).to_numpy(lay), np.float32)
    a = _map_range(a, mode)
    a = _fit3(a)
    if flip:
        a = a[::-1]
    return np.ascontiguousarray(a[None], np.float32)


def to_mask(img, name="mask", mode="clamp", flip=True):
    """One layer of a CopImage -> ComfyUI MASK (1,H,W). Takes channel 0."""
    if img is None or len(img) == 0:
        return np.zeros((1, 1, 1), np.float32)
    lay = img.need(str(name).strip() or "mask")
    a = np.asarray(bk.backend_of(lay).to_numpy(lay), np.float32)
    a = _map_range(a, mode)[..., 0]
    if flip:
        a = a[::-1]
    return np.ascontiguousarray(a[None], np.float32)


def to_preview_float(img, name, flip=True):
    """
    One layer -> (H,W,C) float32 numpy, for the in-node thumbnail.

    **No value-range mapping at all**, passed out as is -- mapping is done in the frontend, so switching clamp /
    signed / normalize does not recompute the whole chain (Substance-style instant feedback depends entirely on this).
    The frontend gets the real values, so it can also read the pixel value under the mouse.

    Whether to flip v is up to the caller: the preview crosses the "Python -> browser" boundary, the same kind of thing as
    from_comfy/to_comfy, so flipping still only happens in this file.
    The default here is **no flip**; the frontend writes the rows in reverse when drawing -- flipping once in the browser is cheaper than
    copying the whole block of memory in Python.
    """
    lay = img.need(str(name).strip() or DEFAULT_LAYER)
    a = np.asarray(bk.backend_of(lay).to_numpy(lay), np.float32)
    if flip:
        a = a[::-1]
    return np.ascontiguousarray(a)


def as_torch(a):
    """numpy -> torch (if installed). ComfyUI downstream generally expects tensors."""
    try:
        import torch
    except ImportError:
        return a
    return torch.from_numpy(np.ascontiguousarray(a))
