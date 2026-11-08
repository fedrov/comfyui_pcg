"""
Control Image -- packs COP layers into IMAGE / MASK following ControlNet conventions.

This is the **semantic translation layer** between PCG and diffusion models. Type conversion (COPIMAGE -> IMAGE) is mechanical;
`bridge.py` does it in ten lines. The hard part is **conventions**: the same depth map with the direction flipped, the wrong space,
or an extra transfer curve applied, and the output completely ignores it -- and **no error is raised**.

So these conventions are gathered in this one file, each with the reason spelled out.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Depth: **near = white**, and it is inverse depth
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Depth ControlNets were trained on the output of MiDaS-style monocular depth networks, and that output is **relative inverse
depth**: near is bright, far is dark, normalized overall to 0-1.

A renderer, however, gives camera-space z: **large in the distance**. Sent directly, that is "near black, far white", exactly backwards --
the control signal is still there, but its direction is reversed, and the model inverts front/back relationships. This is the classic silent failure:
the image looks like a depth map, and the output is just wrong.

So the default is `1 - normalized z`. The normalization range defaults to the min/max of the **pixels covered by the mask** --
the same thing as MiDaS-style "relative depth", and it adapts automatically to the object's actual thickness. For a fixed range
(animation must not flicker frame to frame), fill in near/far by hand.

The background (pixels with no hit) defaults to **0** (= farthest = black). 0 rather than 1 matters: with 1
the model assumes there is something pressed against the lens around the frame.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Normals: camera space + packing + flippable green channel
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The normal-map convention is `n*0.5+0.5`, and the space must be **camera space** (Render Pass gives this by default).
A world-space normal map changes entirely when the camera moves, so ControlNet can't use it.

Whether green points up or down is a historical legacy: OpenGL style (+Y up) and DirectX style (+Y down)
are split about half and half, and different normal ControlNets / preprocessors disagree too. So there is a toggle, rather than picking one default
and pretending it is universal. **The symptom is lighting/bumps reversed overall**, not a crash -- so it must be one click to switch.

The background is **(0.5, 0.5, 1.0)** -- the packed normal of a plane facing the camera. With black, the background would be
treated as a surface with a weird orientation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Line art: extracted from **discontinuities in depth and normals**, not image edge detection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The usual approach is to render a shaded image and run Canny. But we have exact geometry, so two kinds of line can be separated directly:

    large depth gradient   ->  **contour lines** (object edges, occlusion)
    large normal gradient  ->  **crease lines** (hard edges, structural breaks)

Each gets its own weight before being combined, which is far cleaner than Canny -- Canny treats material texture, noise and shading
gradients all as edges. And the two kinds can be tuned separately: architecture wants creases, characters want contours.

Line colour conventions are not uniform (black-on-white / white-on-black both exist), so there is invert.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Linear vs sRGB: **no curve on control images, curve on colour images**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COP is linear internally; ComfyUI's IMAGE is in practice "display-referred" (the VAE saw
sRGB-style 0-1 during training). So there is an easy-to-confuse boundary:

    depth / normal / lineart / id    **no** sRGB. They are **data**;
                                     ControlNet was trained in this packed space
    color / albedo for img2img        **needs it**. Without it, linear 0.5 sent over
                                     is taken as a mid-grey much darker than intended

So the `srgb` toggle defaults on only for the `color` kind and off for the others. Mixing it up raises no error;
it just shifts overall brightness by a notch.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Resolution aligned to 8
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The latent is downsampled by /8, so a size that is not a multiple of 8 gets silently rescaled somewhere. Here we proactively resize to the **nearest**
multiple of 8 (moves at most 4 pixels, composition essentially unchanged); `align=0` turns it off.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This stage always uses numpy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every other COP module is backend-neutral; this one is not. The reason is simple: Control Image is the **exit
of the chain**, the data has to go back to the CPU for ComfyUI regardless, and doing these few steps on the GPU and transferring back saves
next to nothing, while costing an extra copy of the code and an extra "both sides give the same result" test.
"""
from __future__ import annotations

import numpy as np

from ..npcompat import select as _select  # np.select breaks if a node pack rebinds np.bool

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from . import filters as _flt

KINDS = ("depth", "normal", "lineart", "mask", "id", "color", "raw",
         "height")
DEFAULT_LAYER_FOR = {"depth": "depth", "normal": "N", "lineart": "depth",
                     "mask": "mask", "id": "id", "color": "C", "raw": "C",
                     "height": "C"}


def _np(img, name):
    lay = img.need(name)
    return np.asarray(bk.backend_of(lay).to_numpy(lay), np.float32)


def _coverage(img, mask_layer):
    name = str(mask_layer).strip()
    if name and name in img:
        return _np(img, name)[..., 0] > 0.5
    return None


def srgb_encode(a):
    """Linear -> sRGB. Piecewise function, not a 2.2 power -- the dark segment is linear."""
    a = np.clip(np.asarray(a, np.float32), 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92,
                    1.055 * np.power(np.maximum(a, 1e-8), 1 / 2.4) - 0.055)


def depth_control(img, layer="depth", mask_layer="mask", near=0.0, far=0.0,
                  invert=True, background=0.0, gamma=1.0):
    """
    Camera-space z -> 0-1 inverse depth (near = white).

    With near/far left at 0, normalizes automatically by the min/max of pixels **inside the mask** -- exactly the MiDaS-style
    relative-depth approach, and it fits the object's thickness automatically. For frame-stable animation, fill them in by hand.
    """
    z = _np(img, layer)[..., 0].astype(np.float64)
    cov = _coverage(img, mask_layer)
    if cov is None:
        cov = np.isfinite(z) & (z != 0.0)
    if not cov.any():
        return np.zeros(z.shape, np.float32)
    lo = float(near) if float(near) > 0 else float(z[cov].min())
    hi = float(far) if float(far) > 0 else float(z[cov].max())
    if hi - lo < 1e-9:
        hi = lo + 1e-9
    t = np.clip((z - lo) / (hi - lo), 0.0, 1.0)
    if invert:
        t = 1.0 - t                      # near = white, the MiDaS convention
    if abs(float(gamma) - 1.0) > 1e-6:
        t = np.power(np.clip(t, 0.0, 1.0), 1.0 / max(float(gamma), 1e-6))
    return np.where(cov, t, float(background)).astype(np.float32)


def height_control(img, layer="C", mask_layer="mask", lo=0.0, hi=0.0,
                   invert=False, background=0.0, gamma=1.0):
    """
    Height field -> depth control image (**high = white**). A kind added in pcg56.

    Looking orthographically straight down at terrain, what is closer to the camera is higher: the "near =
    white" a depth ControlNet wants becomes "high = white" in a top view. The depth kind is for a renderer's camera z (large far away, needs inverting);
    feeding a height layer straight to it comes out **reversed** -- mountains become pits, with no error. So it gets its own kind, instead of making people
    remember a counter-intuitive combination like "height needs invert".

    lo / hi (reusing the near / far inputs) left at 0 normalize by the min / max **inside the mask** (the whole image if there is no mask layer);
    for tiled generation or stable animation, fill them in by hand. A top-down terrain image also works directly with the normal kind:
    the tangent-space normals from Height to Normal (+Y = +v) are exactly the camera-space
    normals of a top-down camera.
    """
    h = _np(img, layer)[..., 0].astype(np.float64)
    cov = _coverage(img, mask_layer)
    if cov is None:
        cov = np.isfinite(h)
    if not cov.any():
        return np.zeros(h.shape, np.float32)
    if float(hi) > float(lo):
        a, b = float(lo), float(hi)
    else:
        a, b = float(h[cov].min()), float(h[cov].max())
    if b - a < 1e-12:
        b = a + 1e-12
    t = np.clip((h - a) / (b - a), 0.0, 1.0)
    if invert:
        t = 1.0 - t
    if abs(float(gamma) - 1.0) > 1e-6:
        t = np.power(t, 1.0 / max(float(gamma), 1e-6))
    return np.where(cov, t, float(background)).astype(np.float32)


def normal_control(img, layer="N", mask_layer="mask", flip_r=False,
                   flip_g=False, flip_b=False, background=(0.5, 0.5, 1.0)):
    """
    Signed normal -> packed into 0-1. The background gets the "facing the camera" (0.5,0.5,1).

    The green-channel orientation is a historical legacy (OpenGL +Y up / DirectX +Y down), and different normal
    ControlNets disagree too, so there is a toggle. Getting it wrong shows as bumps reversed overall; it won't crash.
    """
    N = _np(img, layer).astype(np.float64)
    if N.shape[2] < 3:
        raise ValueError(f"Normal layer '{layer}' has only {N.shape[2]} channels, needs 3")
    N = N[..., :3]
    ln = np.linalg.norm(N, axis=-1, keepdims=True)
    N = N / np.where(ln < 1e-12, 1.0, ln)
    if flip_r:
        N[..., 0] = -N[..., 0]
    if flip_g:
        N[..., 1] = -N[..., 1]
    if flip_b:
        N[..., 2] = -N[..., 2]
    out = np.clip(N * 0.5 + 0.5, 0.0, 1.0)
    cov = _coverage(img, mask_layer)
    if cov is None:
        cov = ln[..., 0] > 1e-9
    bgc = np.asarray(background, np.float64).reshape(1, 1, 3)
    return np.where(cov[:, :, None], out, bgc).astype(np.float32)


def _sobel(a):
    """Gradient magnitude. Borders use clamp (replicate) -- there is no data outside the image, and padding with black would invent a ring of edges."""
    p = np.pad(a, ((1, 1), (1, 1)), mode="edge")
    gx = (p[1:-1, 2:] - p[1:-1, :-2])
    gy = (p[2:, 1:-1] - p[:-2, 1:-1])
    return np.sqrt(gx * gx + gy * gy)


def _erode(mask):
    """Shrink the coverage region by one pixel. Interior terms must be computed on this, otherwise the contour leaks in."""
    out = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                out &= np.roll(np.roll(mask, dy, 0), dx, 1)
    return out


def lineart_control(img, depth_layer="depth", normal_layer="N",
                    mask_layer="mask", silhouette=1.0, crease=1.0,
                    threshold=0.2, softness=0.5, thickness=1,
                    invert=False):
    """
    Extract lines from depth / normal discontinuities: depth gradient = contour, normal gradient = crease.

    Far cleaner than "render an image then Canny" -- Canny treats materials, noise and shading gradients all as edges,
    whereas here the two kinds of line are separate and can be weighted separately.
    """
    cov = _coverage(img, mask_layer)
    inner_ok = _erode(cov) if cov is not None else None
    H = W = None
    sil = cre = None
    if float(silhouette) != 0.0 and str(depth_layer).strip() in img:
        z = _np(img, depth_layer)[..., 0].astype(np.float64)
        # The outer contour comes from the gradient of the **mask**, not of depth: the background depth is 0 (no hit),
        # and computing the gradient of it together with the object makes edge strength depend on an irrelevant quantity, "how far the object is from the camera".
        # The mask gradient is a clean 0/1 step with constant strength -- divide by sqrt(2) to normalize to 0..1
        if cov is not None and cov.any():
            rng = max(float(z[cov].max() - z[cov].min()), 1e-9)
            zz = np.where(cov, (z - float(z[cov].min())) / rng, 0.0)
            # Interior occlusion edges are computed only in the **eroded** coverage region. Without erosion the depth
            # gradient at the contour tends to infinity (edge of a sphere) and smears a fat ring outside the outer contour
            inner = _sobel(zz) * inner_ok
            sil = np.maximum(_sobel(cov.astype(np.float64)) / np.sqrt(2.0),
                             inner)
        else:
            rng = max(float(z.max() - z.min()), 1e-9)
            sil = _sobel(z / rng)
        H, W = sil.shape
    if float(crease) != 0.0 and str(normal_layer).strip() in img:
        N = _np(img, normal_layer)[..., :3].astype(np.float64)
        cre = np.sqrt(sum(_sobel(N[..., k]) ** 2 for k in range(3)))
        # Creases are likewise computed only in the eroded coverage region: normals are 0 in the background, so at the contour they jump from 0 to
        # unit length, gradient 1.414 -- without masking it out even a smooth sphere grows a ring of "creases",
        # and the negative control "a cube has more creases than a sphere" becomes useless (measured 0.227 vs 0.115)
        if inner_ok is not None:
            cre = cre * inner_ok
        H, W = cre.shape
    if sil is None and cre is None:
        raise KeyError(
            f"Line art needs at least one of the layers '{depth_layer}' or '{normal_layer}' -- "
            f"enable the depth / normal channels on Render Pass. Available: {img.names}")
    e = np.zeros((H, W))
    if sil is not None:
        e += float(silhouette) * sil
    if cre is not None:
        e += float(crease) * cre
    th = max(float(threshold), 1e-6)
    sw = max(float(softness), 0.0) * th
    if sw <= 0:
        line = (e > th).astype(np.float64)
    else:
        t = np.clip((e - (th - sw)) / (2 * sw), 0.0, 1.0)
        line = t * t * (3 - 2 * t)
    k = int(max(1, thickness))
    if k > 1:
        # Thicken = max over a k x k neighbourhood. Shifted max, no convolution
        acc = line.copy()
        r = k // 2
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx == 0 and dy == 0:
                    continue
                acc = np.maximum(acc, np.roll(np.roll(line, dy, 0), dx, 1))
        line = acc
    line = np.clip(line, 0.0, 1.0)
    return (1.0 - line if invert else line).astype(np.float32)


def id_palette(ids, saturation=0.65, value=0.95):
    """
    Integer id -> clearly distinguishable colours. Hues are scattered by the golden angle, so even adjacent ids differ a lot.

    Random hues collide (birthday problem), and evenly spaced hues require knowing the total in advance. The golden angle avoids both.
    """
    ids = np.asarray(ids, np.float64)
    h = np.mod(ids * 0.6180339887498949, 1.0)
    s = float(saturation)
    v = float(value)
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i = np.mod(i, 6).astype(np.int64)
    # All six sectors are **written out explicitly**, not relying on np.select's default. The correct value for sector 6 (i==5) is
    # (v, p, q); if omitted it falls back to the default (v, p, v) -- and then every hue in the whole 6th sector
    # collapses to the same colour. Measured: id 3 and id 8 collided into the same colour, and the criterion "number of region colours
    # == number of regions + background" caught it immediately
    cs = [i == k for k in range(6)]
    r = _select(cs, [v, q, p, p, t, v])
    g = _select(cs, [t, v, v, q, p, p])
    b = _select(cs, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def id_control(img, layer="id", mask_layer="mask", saturation=0.65,
               value=0.95, background=(0.0, 0.0, 0.0)):
    """id image -> region colour image. For regional prompts / segmentation-type ControlNets."""
    a = _np(img, layer)[..., 0]
    cov = _coverage(img, mask_layer)
    if cov is None:
        cov = a >= 0
    col = id_palette(np.round(a), saturation, value)
    bgc = np.asarray(background, np.float64).reshape(1, 1, 3)
    return np.where(cov[:, :, None], col, bgc).astype(np.float32)


def id_masks(img, layer="id", mask_layer="mask", max_regions=64):
    """
    id image -> **a batch** of MASKs, one per id. ComfyUI's MASK is (B,H,W),
    so "one mask per region" is naturally a batch.

    Hooked up to ConditioningSetMask this gives regional prompts: "this part is terracotta, that part is moss", with boundaries that are
    geometrically exact, not brush-painted -- something image methods simply cannot do.

    Returns (masks (N,H,W), ids (N,)). Sorted by id; when exceeding max_regions, keeps those with the **largest
    area** -- truncation by area rather than by id value, otherwise the main subject gets cut off.
    """
    a = np.round(_np(img, layer)[..., 0]).astype(np.int64)
    cov = _coverage(img, mask_layer)
    if cov is None:
        cov = a >= 0
    vals, counts = np.unique(a[cov], return_counts=True)
    if len(vals) > int(max_regions):
        keep = np.argsort(-counts)[:int(max_regions)]
        vals = np.sort(vals[keep])
    out = np.zeros((max(len(vals), 1),) + a.shape, np.float32)
    for k, v in enumerate(vals):
        out[k] = ((a == v) & cov).astype(np.float32)
    return out, vals.astype(np.int64)


def _align_to(a, align):
    """Resize to the nearest multiple of align. Moves at most align/2 pixels, composition essentially unchanged."""
    k = int(align)
    if k <= 1:
        return a
    H, W = a.shape[:2]
    nh = max(k, int(round(H / k)) * k)
    nw = max(k, int(round(W / k)) * k)
    if (nh, nw) == (H, W):
        return a
    tmp = CopImage(W, H, {"a": a.astype(np.float32)})
    return np.asarray(_flt.resize(tmp, nw, nh).need("a"), np.float32)


def control_image(img, kind="depth", layer="", mask_layer="mask",
                  near=0.0, far=0.0, invert=False, gamma=1.0,
                  background=0.0, flip_r=False, flip_g=False, flip_b=False,
                  silhouette=1.0, crease=1.0, threshold=0.2, softness=0.5,
                  thickness=1, saturation=0.65, value=0.95, srgb=None,
                  align=8, normal_layer="N"):
    """
    COP layer -> (IMAGE (1,H,W,3), MASK (1,H,W)).

    Each kind applies its own set of ControlNet conventions; details at the top of the module.
    """
    if img is None or len(img) == 0:
        return (np.zeros((1, 1, 1, 3), np.float32),
                np.zeros((1, 1, 1), np.float32))
    if kind not in KINDS:
        raise ValueError(f"Kind must be one of {KINDS}")
    name = str(layer).strip() or DEFAULT_LAYER_FOR.get(kind, DEFAULT_LAYER)

    if kind == "depth":
        g = depth_control(img, name, mask_layer, near, far, not invert,
                          background, gamma)
        rgb = np.repeat(g[:, :, None], 3, axis=2)
    elif kind == "height":
        g = height_control(img, name, mask_layer, near, far, invert,
                           background, gamma)
        rgb = np.repeat(g[:, :, None], 3, axis=2)
    elif kind == "normal":
        rgb = normal_control(img, name, mask_layer, flip_r, flip_g, flip_b)
    elif kind == "lineart":
        g = lineart_control(img, name, str(normal_layer).strip() or "N",
                            mask_layer, silhouette, crease,
                            threshold, softness, thickness, invert)
        rgb = np.repeat(g[:, :, None], 3, axis=2)
    elif kind == "mask":
        g = np.clip(_np(img, name)[..., 0], 0.0, 1.0)
        if invert:
            g = 1.0 - g
        rgb = np.repeat(g[:, :, None], 3, axis=2)
    elif kind == "id":
        rgb = id_control(img, name, mask_layer, saturation, value)
    else:                                   # color / raw
        a = _np(img, name)
        if a.shape[2] == 1:
            a = np.repeat(a, 3, axis=2)
        elif a.shape[2] == 2:
            a = np.concatenate([a, np.zeros(a.shape[:2] + (1,), np.float32)],
                               -1)
        rgb = a[..., :3]
        if kind == "color":
            rgb = np.clip(rgb, 0.0, 1.0)
            if srgb is None or srgb:
                rgb = srgb_encode(rgb)
        if invert:
            rgb = 1.0 - rgb
    if kind != "color" and srgb:
        rgb = srgb_encode(np.clip(rgb, 0.0, 1.0))

    cov = _coverage(img, mask_layer)
    msk = (cov.astype(np.float32) if cov is not None
           else np.ones(rgb.shape[:2], np.float32))
    rgb = _align_to(np.clip(rgb, 0.0, 1.0).astype(np.float32), align)
    msk = _align_to(msk[:, :, None], align)[..., 0]
    # NOTE: flip v: COP row 0 is the bottom, IMAGE row 0 is the top. Same boundary and same reason
    # as bridge.to_comfy
    return (np.ascontiguousarray(rgb[::-1][None], np.float32),
            np.ascontiguousarray(msk[::-1][None], np.float32))
