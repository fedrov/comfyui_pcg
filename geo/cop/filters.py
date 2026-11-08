"""
Basic COP filters: resampling and blur. Backend-neutral (numpy / torch / CUDA).

Both are things "everyone can write", and both have one spot everyone gets wrong.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Resampling: coordinates must be converted using **pixel centres**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
To shrink W columns to W' columns, the most common formula is `x = i * (W-1)/(W'-1)` (endpoint-aligned). It is
wrong for **scaling**: pixels are not points but cells with width. The correct conversion is

    x = (i + 0.5) * W / W' − 0.5

One example makes the difference clear: shrinking 2 columns to 1, endpoint alignment gives x=0 (only the left pixel),
centre alignment gives x=0.5 (half of each pixel). Upscaling is the same -- endpoint alignment stretches away the outermost half
pixel, and tiling images get misaligned at the seams.

`uv_grid` uses the same convention (pixel centres); the two must agree, otherwise "generate noise then
scale" and "generate scaled noise directly" won't match.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Blur: **separable**, and the Gaussian kernel radius must follow sigma
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2D Gaussian = 1D convolution horizontally then 1D vertically, O(N·k) instead of O(N·k²). At k=31 that's 31x.

The kernel radius cannot be hard-coded. Truncating at 2σ loses 4.6% of the energy, visible as a hard ring on
large-sigma soft glows. Here we use **ceil(3σ)** (0.3% lost), and **renormalize** the truncated kernel.

"Blur doesn't change average brightness" is the best check for this node, but it **only holds with wrap (periodic)
borders**, and that needs saying clearly:

```
                sigma=1      sigma=4      sigma=12
wrap            -2.8e-9      0            -1.9e-9     ← exactly conserved
clamp           -1.4e-6      +4.7e-4      +5.0e-3
black           -3.7e-4      -1.1e-3      -2.4e-4
```

clamp and black both **fabricate** data outside the image (copy edges / pad black), so of course the mean
changes -- that's not a bug, it's the definition of the boundary condition. So tests verify conservation with wrap, and use clamp's
offset as a negative control (proving this check really tests the border handling, rather than holding for anything).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
On the GPU it is still written this way, not switched to conv2d
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
torch has `F.conv2d`, in theory faster than "shift and accumulate". It's not used here because:

    · conv2d only takes NCHW; (H,W,C) would need permuting back and forth, and the channel count is arbitrary (1/2/3/4)
    · border modes don't match (circular only exists in F.pad; conv2d itself only pads with zeros)
    · the accumulation form is **the same code** on both backends, with identical numerics; switching to cuDNN adds
      a suspect of "results differ slightly between the two", which is exactly what this GPU move most wanted to avoid

Shift-and-accumulate on the GPU is bandwidth-bound anyway; k element-wise multiply-adds, no speed lost where it matters.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, check_res
from . import backend as bk

BORDERS = ("clamp", "wrap", "black")


def _axis_index(n_out, n_in, border):
    """Position of output pixel i in the input (pixel-centre convention); returns (i0, i1, frac)."""
    x = (np.arange(n_out, dtype=np.float64) + 0.5) * n_in / n_out - 0.5
    i0 = np.floor(x).astype(np.int64)
    f = (x - i0)
    i1 = i0 + 1
    if border == "wrap":
        return i0 % n_in, i1 % n_in, f
    return np.clip(i0, 0, n_in - 1), np.clip(i1, 0, n_in - 1), f


def resize(img, xres, yres, border="clamp"):
    """Bilinear resample to a new resolution. All layers together."""
    if img is None:
        return CopImage()
    x, y = check_res(xres, yres)
    if (x, y) == img.res:
        return img.copy()
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    xp = img.backend
    ix0, ix1, fx = _axis_index(x, img.xres, border)
    iy0, iy1, fy = _axis_index(y, img.yres, border)
    FX = xp.reshape(xp.asarray(fx), (1, x, 1))
    FY = xp.reshape(xp.asarray(fy), (y, 1, 1))
    out = CopImage(x, y)
    for k in img.names:
        a = img.get(k)
        r = (xp.outer_index(a, iy0, ix0) * (1 - FY) * (1 - FX)
             + xp.outer_index(a, iy0, ix1) * (1 - FY) * FX
             + xp.outer_index(a, iy1, ix0) * FY * (1 - FX)
             + xp.outer_index(a, iy1, ix1) * FY * FX)
        out.set(k, r)
    return out


def sample(a, u, v, border="clamp", xp=None):
    """
    Bilinear sampling of layer a at uv (0-1, v up). u/v have the same shape; returns (..., C).

    The uv-to-pixel-centre conversion is `x = u*W − 0.5`, the same as resize uses -- if the two
    disagree, "sample after scaling" and "scale after sampling" differ by half a pixel.
    """
    xp = xp or bk.backend_of(a)
    H, W = int(a.shape[0]), int(a.shape[1])
    x = xp.asarray(u) * W - 0.5
    y = xp.asarray(v) * H - 0.5
    x0 = xp.to_i64(xp.floor(x))
    y0 = xp.to_i64(xp.floor(y))
    fx = (x - xp.asarray(x0))
    fy = (y - xp.asarray(y0))
    fx = xp.reshape(fx, tuple(fx.shape) + (1,))
    fy = xp.reshape(fy, tuple(fy.shape) + (1,))
    x1, y1 = x0 + 1, y0 + 1
    vx0 = vx1 = vy0 = vy1 = None
    if border == "wrap":
        x0, x1 = xp.mod_i64(x0, W), xp.mod_i64(x1, W)
        y0, y1 = xp.mod_i64(y0, H), xp.mod_i64(y1, H)
    else:
        if border == "black":
            # **that single sample point** outside the image counts as 0 (zero padding), not the whole sample.
            # Before pcg58 this was "if any of the four points is out of bounds the whole thing is 0": an identity transform with
            # black border would blacken the entire last row and last column (the right / top neighbours of those two rows of pixel
            # centres lie outside the image, even though their weight is 0)
            def _v(i, n):
                ok = (i >= 0) & (i < n)
                return xp.reshape(xp.where(ok, xp.full(tuple(ok.shape), 1.0),
                                           xp.full(tuple(ok.shape), 0.0)),
                                  tuple(ok.shape) + (1,))
            vx0, vx1, vy0, vy1 = _v(x0, W), _v(x1, W), _v(y0, H), _v(y1, H)
        x0 = xp.to_i64(xp.clip(xp.asarray(x0), 0, W - 1))
        x1 = xp.to_i64(xp.clip(xp.asarray(x1), 0, W - 1))
        y0 = xp.to_i64(xp.clip(xp.asarray(y0), 0, H - 1))
        y1 = xp.to_i64(xp.clip(xp.asarray(y1), 0, H - 1))
    w00 = (1 - fy) * (1 - fx)
    w10 = (1 - fy) * fx
    w01 = fy * (1 - fx)
    w11 = fy * fx
    if vx0 is not None:
        w00 = w00 * vx0 * vy0
        w10 = w10 * vx1 * vy0
        w01 = w01 * vx0 * vy1
        w11 = w11 * vx1 * vy1
    r = (xp.index2(a, y0, x0) * w00 + xp.index2(a, y0, x1) * w10
         + xp.index2(a, y1, x0) * w01 + xp.index2(a, y1, x1) * w11)
    return r


def gaussian_kernel(sigma):
    """
    1D Gaussian kernel, radius **ceil(3σ)**, normalized. Always computed on the CPU (a few hundred numbers).

    Truncating at 2σ loses 4.6% of the energy, visible as a hard ring on large-sigma soft glows; 3σ loses only 0.3%.
    After truncation it must be renormalized, otherwise the whole image darkens as sigma grows.
    """
    s = float(sigma)
    if s <= 0:
        return np.ones(1, np.float64)
    r = int(np.ceil(3.0 * s))
    t = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (t / s) ** 2)
    return k / k.sum()


def _conv1d(xp, a, k, axis, border):
    """1D convolution along one axis. a is (H,W,C)."""
    r = (len(k) - 1) // 2
    if r == 0:
        return a
    p = xp.pad_axis(a, r, axis, border)
    n = int(a.shape[axis])
    out = None
    for j, w in enumerate(k):
        if w == 0.0:
            continue
        sl = [slice(None)] * 3
        sl[axis] = slice(j, j + n)
        term = float(w) * p[tuple(sl)]
        out = term if out is None else out + term
    return out


def blur(img, sigma=2.0, border="clamp", layers=""):
    """
    Gaussian blur. **Separable**: horizontal then vertical, O(N·k) instead of O(N·k²).

    sigma is in pixels. Leave layers empty to blur all layers, otherwise only those listed (space-separated).
    """
    if img is None:
        return CopImage()
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    s = float(sigma)
    if s <= 0:
        return img.copy()
    xp = img.backend
    want = [n for n in str(layers).split() if n] or img.names
    k = gaussian_kernel(s)
    out = img.copy()
    for name in want:
        a = img.need(name)
        out.set(name, _conv1d(xp, _conv1d(xp, a, k, 1, border), k, 0, border))
    return out
