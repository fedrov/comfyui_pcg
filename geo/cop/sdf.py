"""
SDF from Mask -- turns any black-and-white mask back into a **signed distance field**.

This is the most useful node in COP, because a distance field can do everything a black-and-white image can't:

    stroke         |d| < w                      width accurate to sub-pixel, and resolution independent
    dilate/erode   d - r                        r is in **pixels**, not "how much blur"
    bevel/feather  smoothstep(-w, w, d)         give the edge width directly, no trial-and-error blur radius
    union/int/diff min / max / max(a, -b)       the result **is still** a correct distance field
    iso bands      quantize(d)                  contour lines, terrain terracing, cel-shading outlines

In an SD pipeline it is the step that "turns an AI-made mask into a controllable geometric quantity": feed in a segmented
mask, dilate by 8 pixels for an inpaint transition band, or take |d|<2 to get a clean ring of outline
to feed ControlNet.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two implementations, because their trade-offs **really** differ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**exact** (default) -- Felzenszwalb & Huttenlocher's lower-envelope algorithm. Splits the 2D distance transform
into two 1D passes: rows first, then columns. The 1D step finds the lower envelope of a family of parabolas
`(q-p)^2 + f(p)`, swept in O(N) with a monotonic stack. The result is the **exact** Euclidean distance,
not an approximation; it can be compared point by point against brute-force O(N^2) to 1e-12.

    It is numpy-only. The algorithm itself is **sequential** (stack advance depends on the previous column) and can't become
    a chain of gathers. The vectorization here is "all rows in parallel, loop along columns", so the Python level has
    O(W) loop iterations -- 1024 wide = 2048 numpy calls, tens of milliseconds, acceptable;
    at 8192 it starts to hurt.

**jfa** -- Jump Flooding. Pure gathers, so it runs on numpy / torch / CUDA alike;
on GPU it's O(log N) passes of 9 samples each, much faster than exact.

    The cost is that it is **not exact**. The classic JFA counterexample is "propagation blocked by a seed that is nearer but in the wrong
    direction". Measured at 256^2, pixel by pixel against exact:

    ```
                       sparse random seeds (8)    solid circle (r=70)
        jfa_plus=0     max 1.63 px / 0.028%       0.263 px / 0.166%
        jfa_plus=1     no error measured          0.189 px / 0.111%
        jfa_plus=2     no error measured          0.189 px / 0.085%
        jfa_plus=4     ——                        0.189 px / 0.085%
    ```

    The thing to remember from this table is that **the two columns differ**. Looking only at the left column you'd conclude "JFA+1 is exact",
    but that's because sparse point seeds propagate too short a distance to ever reach the range where JFA
    goes wrong; switch to a solid circle that must propagate seventy-odd pixels and an inherent 0.19 px
    miss shows up immediately -- and raising plus to 4 doesn't improve it, so it isn't a matter of too few extra passes.

    "Random tests pass" doesn't prove correctness. The default is still 2 (cheap, and it really does help in sparse
    cases), but for correctness use exact.

One more counterintuitive point: **on numpy, jfa is slower than exact**. A 1024^2 circle: exact 0.33 s,
jfa 3.1 s -- JFA trades O(N log N) memory accesses for O(1) parallel depth, a deal that only
pays off when you really have thousands of cores. jfa is meant for CUDA; on CPU there's no reason to pick it.

So: for correctness on CPU, use exact; if the image is already on the GPU, use jfa.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Half-pixel correction: the boundary lies **between** two pixels
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Distances are measured from **pixel centers**, so the outside pixel right at the boundary measures 1.0 and the inside one 1.0,
while the real boundary between them is at 0.5. Used as-is, the zero isosurface would be **offset outward by half a pixel**:
strokes always look one ring too thick, dilation always goes a bit too far.

`half_pixel=True` (default) subtracts 0.5 from the distance on both sides. This also means **pixels right at the boundary
get +-0.5, not 0** -- which is correct: no pixel center lies exactly on the boundary.

An analytic circle of radius 140 px on 512^2, statistics binned by true distance to the boundary (outside, px):

```
    distance band  bias uncorr.   bias corrected  rms uncorr.  rms corrected
    0–1         +0.5464        +0.0464        0.6019      0.2568
    1–2         +0.3914        −0.1086        0.4347      0.2181
    2–4         +0.3371        −0.1629        0.3833      0.2445
    4–8         +0.2918        −0.2082        0.3399      0.2716
    8–16        +0.2499        −0.2501        0.2963      0.2964
    16–40       +0.2124        −0.2876        0.2623      0.3261
    40–100      +0.1851        −0.3149        0.2381      0.3487
```

Two things need spelling out, both counterintuitive:

  · **The correction doesn't move the zero isosurface**. It is symmetric inside/outside: +-1 becomes +-0.5, the zero crossing
    stays put -- under both settings the radius linearly interpolated along a row is exactly 140.0000.
    So if you use the SDF as a **threshold** (`d < 0`) it makes no difference; the correction affects the **values**
    (stroke width, dilation distance, feather radius), which are the reason to use an SDF in the first place
  · The correction is a big win **near the boundary** (0-2 px): +0.55 -> +0.05. In the far field it slightly
    overshoots (+0.19 -> -0.31). That's no loss -- the precision a distance field needs is concentrated near
    the boundary anyway; nobody can see 0.3 px in the far field

The remaining far-field bias (+0.19 uncorrected) isn't this step's fault: it is the **mask's own**
aliasing. A pixelated circle is stair-stepped, so the nearest interior pixel center is on average a bit farther than the true boundary.
Pushing it lower would require an anti-aliased mask and sub-pixel interpolation from its gray values -- work of another
order of magnitude; not done here, but also not pretended to be done.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Units: pixels or uv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`uv` is **divided by the short side**, the same convention as `generate.aspect_coords` / COP Shape's SDF.
So if COP Shape draws a circle with radius=0.3, it is baked into a mask, and this node computes the SDF back,
the values are comparable with the layer Shape outputs directly (the tests compare them). Dividing by width or by height
would break this on non-square images.
"""
from __future__ import annotations

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk

MODES = ("exact", "jfa")
UNITS = ("pixels", "uv")
SIGNS = ("signed", "outside", "inside", "unsigned")
# distance when there are no seeds. Larger than the diagonal of any legal image, yet far from the float32 limit
NOSEED = 1.0e9
_INF = 1.0e20


# ══════════════════════════════════════════════════ Exact EDT (lower envelope, numpy)
def _edt1d_sq(f):
    """
    1D squared distance transform along **axis=1**: `d[q] = min_p ((q-p)^2 + f[p])`.

    Each row of f is independent. This is Felzenszwalb & Huttenlocher's (2012) lower-envelope algorithm:
    treat each p as a parabola `(q-p)^2 + f[p]`, find their lower envelope with a monotonic stack, then sweep along q
    once to read it out. Both passes are O(N).

    Vectorized as "**all rows in parallel, loop along columns**". Rows don't interfere, so the stack-top pointer
    `k` is an (R,) vector and pops are done with masks. The cost is that every iteration of the while loop recomputes s for
    all rows (only the masked ones actually use it); in exchange there is no Python-level
    per-row loop -- the taller the image, the better the deal.
    """
    f = np.ascontiguousarray(np.asarray(f, np.float64))
    R, N = f.shape
    if N == 1:
        return f.copy()
    rows = np.arange(R)
    v = np.zeros((R, N), np.int64)          # stack: vertex position of the k-th parabola
    z = np.empty((R, N + 1), np.float64)    # stack: intersections of adjacent parabolas
    z[:, 0] = -_INF
    z[:, 1] = _INF
    k = np.zeros(R, np.int64)
    for q in range(1, N):
        fq = f[:, q] + float(q) * q
        s = None
        while True:
            vk = v[rows, k]
            s = (fq - (f[rows, vk] + vk.astype(np.float64) ** 2)) \
                / (2.0 * (q - vk))
            pop = (k > 0) & (s <= z[rows, k])
            if not pop.any():
                break
            k = np.where(pop, k - 1, k)
        k = k + 1
        v[rows, k] = q
        z[rows, k] = s
        z[rows, k + 1] = _INF
    d = np.empty((R, N), np.float64)
    k = np.zeros(R, np.int64)
    for q in range(N):
        while True:
            adv = z[rows, k + 1] < q
            if not adv.any():
                break
            k = np.where(adv, k + 1, k)
        vk = v[rows, k]
        d[:, q] = (q - vk) ** 2 + f[rows, vk]
    return d


def edt_sq(seed):
    """
    **Squared** Euclidean distance to the nearest True pixel (in pixels). seed is an (H,W) boolean array.

    Separable: rows first, then columns. This works because squared Euclidean distance is itself separable:
    `(dx)^2 + (dy)^2`. Other distances (e.g. Manhattan or max) can't be split this way.

    When all False, returns `_INF` (the caller handles the finish).
    """
    seed = np.asarray(seed, bool)
    f = np.where(seed, 0.0, _INF)
    d = _edt1d_sq(f)
    return _edt1d_sq(np.ascontiguousarray(d.T)).T


def distance_exact(seed):
    """Euclidean distance to the nearest True pixel (pixels). With no seeds, the whole image is NOSEED."""
    seed = np.asarray(seed, bool)
    if not seed.any():
        return np.full(seed.shape, NOSEED, np.float64)
    return np.sqrt(np.maximum(edt_sq(seed), 0.0))


# ═════════════════════════════════════════════════════ JFA (backend-neutral, GPU-capable)
def _jfa_steps(W, H, plus=2):
    """Jump step sizes: halve from a power of 2 >= max(W,H) down to 1, then add plus extra small-step passes."""
    k = 1
    while k < max(int(W), int(H)):
        k *= 2
    k //= 2
    out = []
    while k >= 1:
        out.append(k)
        k //= 2
    # JFA+2: two more passes with k=2 and k=1. Most classic JFA misses are "the correct seed is one cell away
    # diagonally"; small-step passes recover most of them -- but not all, so it is still an approximation
    out += [2, 1][:max(0, int(plus))]
    return out


def distance_jfa(img_seed, xp, W, H, plus=2):
    """
    Jump Flooding to find the nearest seed. `img_seed` is an (H,W,1) backend array; >0.5 counts as a seed.

    Each pass does one gather over 9 offsets, comparing "the nearest seed I know" with "the nearest seed my neighbor
    knows" and keeping the nearer. Everything is elementwise + gather, so numpy / torch / CUDA
    use **the same code**.

    Returns (distance (H,W,1), whether there are any seeds).
    """
    jx = xp.reshape(xp.broadcast_to(
        xp.reshape(xp.arange(W), (1, W)), (H, W)), (H, W, 1))
    iy = xp.reshape(xp.broadcast_to(
        xp.reshape(xp.arange(H), (H, 1)), (H, W)), (H, W, 1))
    big = xp.full((H, W, 1), NOSEED)
    is_seed = img_seed > 0.5
    s = xp.concat([xp.where(is_seed, jx, big),
                   xp.where(is_seed, iy, big)], 2)          # (H,W,2)
    ji = xp.to_i64(jx[:, :, 0])
    ii = xp.to_i64(iy[:, :, 0])
    for k in _jfa_steps(W, H, plus):
        bd = (s[:, :, :1] - jx) ** 2 + (s[:, :, 1:2] - iy) ** 2
        best = s
        for dy in (-k, 0, k):
            for dx in (-k, 0, k):
                if dx == 0 and dy == 0:
                    continue
                nx = xp.to_i64(xp.clip(xp.asarray(ji + dx), 0, W - 1))
                ny = xp.to_i64(xp.clip(xp.asarray(ii + dy), 0, H - 1))
                cand = xp.index2(s, ny, nx)
                d = (cand[:, :, :1] - jx) ** 2 + (cand[:, :, 1:2] - iy) ** 2
                better = d < bd
                bd = xp.where(better, d, bd)
                best = xp.where(xp.broadcast_to(better, (H, W, 2)),
                                cand, best)
        s = best
    bd = (s[:, :, :1] - jx) ** 2 + (s[:, :, 1:2] - iy) ** 2
    return xp.sqrt(bd)


# ══════════════════════════════════════════════════════════ SDF from Mask
def sdf_from_mask(img, layer=DEFAULT_LAYER, threshold=0.5, mode="exact",
                  sign="signed", units="pixels", half_pixel=True,
                  jfa_plus=2, out_layer="sdf", keep=True):
    """
    Mask -> signed distance field. **Negative inside, positive outside** (same as COP Shape's SDF).

    For layers with more than 1 channel, **channel 0** is used. To decide by luminance, connect a COP Luminance first --
    quietly doing luminance here would turn "but I connected a red mask" into a mystery.

    `sign`:
        signed    negative inside, positive outside (default)
        outside   outside only, inside is 0 -- "how far from the shape"
        inside    inside only, outside is 0 -- "how deep from the boundary", handy for eroding
        unsigned  |d|, positive both ways -- stroke is simply `d < w`

    `keep=True` keeps the existing layers (the SDF is added as a new layer), so one image can
    carry both the mask and its distance field, and downstream can use whichever it wants.
    """
    if img is None:
        return CopImage()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if units not in UNITS:
        raise ValueError(f"Units must be one of {UNITS}")
    if sign not in SIGNS:
        raise ValueError(f"Sign must be one of {SIGNS}")
    a = img.need(layer)
    W, H = img.xres, img.yres
    xp = img.backend
    th = float(threshold)
    a0 = a[:, :, :1]

    if mode == "exact":
        m = np.asarray(bk.backend_of(a).to_numpy(a0), np.float64)[:, :, 0]
        inside = m >= th
        n_in = int(inside.sum())
        d_out = (distance_exact(inside) if n_in else
                 np.full(inside.shape, NOSEED))
        d_in = (distance_exact(~inside) if n_in < inside.size else
                np.full(inside.shape, NOSEED))
        if half_pixel:
            # the boundary lies between two pixels. Subtract half a pixel on each side so the zero isosurface falls back on the boundary
            d_out = np.maximum(d_out - 0.5, 0.0)
            d_in = np.maximum(d_in - 0.5, 0.0)
        d = np.where(inside, -d_in, d_out)[:, :, None]
        d = xp.asarray(d)
    else:
        inside_f = xp.where(a0 >= th, xp.full((H, W, 1), 1.0),
                            xp.full((H, W, 1), 0.0))
        d_out = distance_jfa(inside_f, xp, W, H, jfa_plus)
        d_in = distance_jfa(1.0 - inside_f, xp, W, H, jfa_plus)
        if half_pixel:
            zero = xp.full((H, W, 1), 0.0)
            d_out = xp.maximum(d_out - 0.5, zero)
            d_in = xp.maximum(d_in - 0.5, zero)
        d = xp.where(a0 >= th, -d_in, d_out)

    if sign == "outside":
        d = xp.maximum(d, xp.full(tuple(d.shape), 0.0))
    elif sign == "inside":
        d = xp.maximum(-d, xp.full(tuple(d.shape), 0.0))
    elif sign == "unsigned":
        d = xp.abs(d)
    if units == "uv":
        # divide by the **short side**, same convention as aspect_coords / COP Shape. Dividing by width or height
        # would squash a circle into an ellipse on non-square images
        d = d / float(min(W, H))
    out = img.copy() if keep else CopImage(W, H)
    out.set(str(out_layer).strip() or "sdf", d)
    return out
