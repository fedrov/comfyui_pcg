"""
COP neighbourhood operators: morphology (erode/dilate/open/close), edge detection, sharpen, median.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
box is **separable**, disc isn't -- not implementation laziness, it's mathematics
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A min filter with a rectangular structuring element can be split into "min along rows, then min along columns" -- because the minimum
over a rectangular window equals the minimum of the per-row minima. O(N·r) instead of O(N·r²).

A disc **cannot** be split this way: a circle is not a Cartesian product of row intervals. So disc honestly enumerates every
offset in the window; r=8 is 197 of the (2·8+1)², 197 full-image mins. At r = 20 it's
1257 -- that's the real cost of disc, written here so nobody pulls radius to 50 and then
thinks it has hung.

For large-radius disc erode/dilate, **don't use this node, use SDF**: after `COP SDF from Mask`,
a single `d − r` is a dilation of any radius, at a cost independent of the radius. The morphology node suits r ≤ 8
small touch-ups (removing burrs, filling small holes).

The relationship between the two isn't "roughly the same", it's an **identity**: dilating a binary image with a disc of radius r gives exactly
`EDT ≤ r`. Tests compare this bit-exactly -- it verifies both the morphology and the SDF modules at once.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Edge detection kernels must be **normalized into true derivatives**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The Sobel kernels copied everywhere are integer, and the values they produce are **8 times** the real gradient (Prewitt 6 times,
Scharr 32 times). Without dividing that out:

    · switch kernels and the same image's edge strength differs by 4x; all thresholds need retuning
    · the word "gradient" becomes meaningless; no way to compare against checks like an SDF's |∇d| = 1

So the normalization factor is always divided out here. The cost is smaller values (integer-kernel edges look "brighter");
in return, on an analytic slope `f = a·x + b·y`, gx **exactly** equals a and gy exactly equals b.
That's this node's hardest check, and it's how the tests verify it.

Laplacian is not normalized -- it already is the discrete Laplace operator itself; `∂²f/∂x² + ∂²f/∂y²`
on f = a·x² gives exactly 2a.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Median is numpy-only
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
It needs sorting, and the backend operator table has no sort (adding one would mean verifying stability and NaN behaviour
on both numpy / torch; not worth it). If the image is on CUDA there's one round trip here.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from .filters import BORDERS, _conv1d, blur

OPS = ("erode", "dilate", "open", "close", "gradient")
SHAPES = ("box", "disc")
EDGE_METHODS = ("sobel", "prewitt", "scharr", "laplacian")

# (central difference kernel, smoothing kernel, normalization factor). The first two are the two halves of a separable gradient operator
_EDGE = {
    "sobel":   (np.array([-1.0, 0.0, 1.0]), np.array([1.0, 2.0, 1.0]), 8.0),
    "prewitt": (np.array([-1.0, 0.0, 1.0]), np.array([1.0, 1.0, 1.0]), 6.0),
    "scharr":  (np.array([-1.0, 0.0, 1.0]), np.array([3.0, 10.0, 3.0]), 32.0),
}


def _want(img, layers):
    names = [n for n in str(layers).split() if n]
    for n in names:
        img.need(n)
    return names or img.names


# ═════════════════════════════════════════════════════════════════ morphology
def _minmax1d(xp, a, r, axis, border, take_max):
    """min/max filter of radius r along one axis."""
    p = xp.pad_axis(a, r, axis, border)
    n = int(a.shape[axis])
    out = None
    for j in range(2 * r + 1):
        sl = [slice(None)] * 3
        sl[axis] = slice(j, j + n)
        t = p[tuple(sl)]
        out = t if out is None else (xp.maximum(out, t) if take_max
                                     else xp.minimum(out, t))
    return out


def _disc_offsets(r):
    """Offsets in a disc structuring element. `dx² + dy² ≤ r²`, so r=1 gives 5 (a cross)."""
    o = [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1)
         if dx * dx + dy * dy <= r * r]
    return o


def _minmax2d_disc(xp, a, r, border, take_max):
    """Disc structuring element. Not separable; must enumerate every offset in the window."""
    p = xp.pad_axis(xp.pad_axis(a, r, 0, border), r, 1, border)
    H, W = int(a.shape[0]), int(a.shape[1])
    out = None
    for dy, dx in _disc_offsets(r):
        t = p[r + dy:r + dy + H, r + dx:r + dx + W]
        out = t if out is None else (xp.maximum(out, t) if take_max
                                     else xp.minimum(out, t))
    return out


def _basic(xp, a, r, shape, border, take_max):
    if r <= 0:
        return a
    if shape == "box":
        return _minmax1d(xp, _minmax1d(xp, a, r, 1, border, take_max),
                         r, 0, border, take_max)
    return _minmax2d_disc(xp, a, r, border, take_max)


def morph(img, op="dilate", radius=1, shape="disc", border="clamp",
          layers=""):
    """
    Morphology. radius is in **pixels**; shape picks rectangle or disc.

    `gradient` is `dilate − erode`, i.e. the morphological gradient -- on a binary mask it gives exactly
    an outline of thickness 2r, easier than computing an SDF and taking a band (for small radii).

    The border choice has real consequences: `clamp` (copy edges, default) keeps the image edges out of the erosion;
    `black` treats outside the image as 0, so **erosion eats inward from all four edges**. Which is right depends on "whether outside the image
    is background"; there's no universal answer, so it's a parameter rather than hard-coded.

    These operators hold on greyscale images too (not just binary): erode is the local minimum, dilate the local
    maximum; on a height field that's "flatten peaks / fill valleys".
    """
    if img is None:
        return CopImage()
    if op not in OPS:
        raise ValueError(f"Op must be one of {OPS}")
    if shape not in SHAPES:
        raise ValueError(f"Shape must be one of {SHAPES}")
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    r = int(radius)
    if r < 0:
        raise ValueError("Radius cannot be negative.")
    if r > 64:
        raise ValueError(
            f"Radius {r} is too large (limit 64). disc would enumerate {(2*r+1)**2} offsets -- "
            f"for large radii use COP SDF from Mask then `d − r` instead, at a cost independent of the radius.")
    xp = img.backend
    out = img.copy()
    for n in _want(img, layers):
        a = img.need(n)
        if op == "erode":
            v = _basic(xp, a, r, shape, border, False)
        elif op == "dilate":
            v = _basic(xp, a, r, shape, border, True)
        elif op == "open":
            v = _basic(xp, _basic(xp, a, r, shape, border, False),
                       r, shape, border, True)
        elif op == "close":
            v = _basic(xp, _basic(xp, a, r, shape, border, True),
                       r, shape, border, False)
        else:
            v = (_basic(xp, a, r, shape, border, True)
                 - _basic(xp, a, r, shape, border, False))
        out.set(n, v)
    return out


# ═══════════════════════════════════════════════════════════════ edge detection
def edge(img, layer=DEFAULT_LAYER, method="sobel", border="clamp",
         scale=1.0, out_layer="edge", components=False, keep=True):
    """
    Edge detection. The main output is the **gradient magnitude**; with `components=True` three extra layers gx / gy /
    direction angle are output.

    Layers with more than 1 channel get gradients **per channel**; the magnitude is the root of the sum of squares over all channels (not converting
    to grey first and then taking the gradient). The two approaches differ a lot on colour boundaries: luminance may barely change
    across a red/green boundary, so converting to grey first loses that edge. To work on luminance, insert COP Luminance first.

    `scale` is a multiplier applied at the end. The default 1 gives the **real per-pixel gradient** (on an analytic slope
    gx exactly equals the slope); set it to 4~10 to make edges directly visible.
    """
    if img is None:
        return CopImage()
    if method not in EDGE_METHODS:
        raise ValueError(f"Method must be one of {EDGE_METHODS}")
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    xp = img.backend
    a = img.need(layer)
    H, W = int(a.shape[0]), int(a.shape[1])
    s = float(scale)
    out = img.copy() if keep else CopImage(W, H)
    base = str(out_layer).strip() or "edge"

    if method == "laplacian":
        # not normalized: it already is ∂²f/∂x² + ∂²f/∂y², giving 2a on f = a·x²
        k2 = np.array([1.0, -2.0, 1.0])
        k0 = np.array([0.0, 1.0, 0.0])
        lap = (_conv1d(xp, _conv1d(xp, a, k2, 1, border), k0, 0, border)
               + _conv1d(xp, _conv1d(xp, a, k0, 1, border), k2, 0, border))
        out.set(base, lap * s)
        return out

    d, sm, norm = _EDGE[method]
    # separable: gx = (central difference along x) ∘ (smoothing along y)
    gx = _conv1d(xp, _conv1d(xp, a, d, 1, border), sm, 0, border) / norm
    gy = _conv1d(xp, _conv1d(xp, a, sm, 1, border), d, 0, border) / norm
    mag = xp.sqrt(xp.reshape(xp.sum(gx * gx + gy * gy, -1), (H, W, 1)))
    out.set(base, mag * s)
    if components:
        out.set(base + "_gx", gx * s)
        out.set(base + "_gy", gy * s)
        # direction is only meaningful for channel 0 (a multi-channel "gradient direction" isn't a single vector)
        out.set(base + "_dir", xp.reshape(
            xp.arctan2(gy[:, :, 0], gx[:, :, 0]), (H, W, 1)))
    return out


# ══════════════════════════════════════════════════════════════════ sharpen
def sharpen(img, amount=1.0, sigma=1.0, border="clamp", layers=""):
    """
    Unsharp masking: `out = a + amount · (a − blur(a, sigma))`.

    `amount=0` is a **bit-exact** identity (skipped outright, not a single operation). A constant image is unchanged under any
    parameters -- the blur of a constant is itself, so the difference is 0. These two are this node's checks.

    sigma decides "what scale of detail gets sharpened": 0.5~1 brings out texture, 3~5 brings out contours and volume.
    amount above 2 produces halos on both sides of strong edges (overshoot); that's inherent to the algorithm, not a bug.
    """
    if img is None:
        return CopImage()
    a_amt = float(amount)
    if a_amt == 0.0:
        return img.copy()
    names = _want(img, layers)
    lo = blur(img, float(sigma), border, " ".join(names))
    out = img.copy()
    for n in names:
        a = img.need(n)
        out.set(n, a + (a - lo.need(n)) * a_amt)
    return out


# ══════════════════════════════════════════════════════════════════ median
def median(img, radius=1, shape="disc", border="clamp", layers=""):
    """
    Median filter. Removes salt-and-pepper noise and specks on AI masks, and **doesn't smear edges like a blur does**.

    numpy-only (it needs sorting, which the backend operator table lacks), and O(N·k²·log k) -- r=2
    (13 samples) is already noticeably slower than a blur, r=4 (49) much slower. Don't use it as a blur.

    Identity on constant images and monotonicity (the output is always one of the values in the window) are its checks.
    """
    if img is None:
        return CopImage()
    if shape not in SHAPES:
        raise ValueError(f"Shape must be one of {SHAPES}")
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    r = int(radius)
    if r <= 0:
        return img.copy()
    if r > 8:
        raise ValueError(f"Radius {r} is too large (limit 8) -- median is O(k²·log k); "
                         f"for anything bigger use COP Blur or COP Morph instead.")
    offs = (_disc_offsets(r) if shape == "disc"
            else [(dy, dx) for dy in range(-r, r + 1)
                  for dx in range(-r, r + 1)])
    xp = img.backend
    npb = bk.NUMPY
    out = img.copy()
    for n in _want(img, layers):
        a = img.need(n)
        m = np.asarray(bk.backend_of(a).to_numpy(a))
        H, W = m.shape[0], m.shape[1]
        p = npb.pad_axis(npb.pad_axis(m, r, 0, border), r, 1, border)
        st = np.stack([p[r + dy:r + dy + H, r + dx:r + dx + W]
                       for dy, dx in offs], 0)
        out.set(n, xp.asarray(np.median(st, axis=0)))
    return out
