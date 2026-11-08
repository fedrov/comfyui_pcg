"""
Erosion filter -- **not a simulation**: a stateless per-pixel filter that looks eroded.

The idea comes from Rune Skovbo Johansen's March 2026 "Advanced Terrain Erosion Filter"
(blog blog.runevision.com, Shadertoy wXcfWn), and the Clay John (2018) /
Fewes (2023) line it builds on. **This is a reimplementation from the mechanism described in the blog; not a single line of the original
code was copied** -- the original code is MPL-2.0 (per-file weak copyleft), so a rewrite from the description isn't bound by it;
the Clay John / Fewes Shadertoy licenses couldn't be verified, and Shadertoy's default
CC BY-NC-SA rules out copying even more. The specific formulas below for the kernel, weights, mask and fade are all our own,
and where they differ from the original is noted in the respective comments.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mechanism: downslope stripes, each layer re-oriented by "the slope after adding the previous layers"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each pixel holds two things: current height h and current slope g (world scale). One layer (octave) does:

  1. flow direction d = -g / |g|, the stripes' "across" direction n ⊥ d
  2. lay a cosine stripe along n: constant along the flow, oscillating across it -- a row of downslope
     gullies and ridges
  3. stripe strength is set by **slope**: no gullies on flat ground, deepest gullies on steep slopes
  4. add this layer's gullies to the height; **also add the analytic derivative of this layer's gullies to the slope**

Step 4 is the key to the whole thing. The slope of a gully wall points across (⊥ the flow); once added to g, the flow
direction the next layer sees on the gully wall **bends toward the gully floor** -- so the next, finer layer's gullies follow the previous layer's big gullies,
growing tributaries on the big gullies' walls. That's where the tree-like branching comes from, with no global flow accumulation needed.

Why the derivative is added analytically rather than re-differencing the height map after each layer: the finest layers' stripe wavelength is only
two or three pixels, where finite differences are already inaccurate (for a sine with a 4-pixel wavelength, central differences give a slope
of only 64% of the true value), and grid aliasing would also leak into the next layer's flow direction.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The stripe itself: blend one random "kernel" per cell, then normalize
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The plane is cut into cells by wavelength, each with a random pivot point c. At pixel p, each kernel contributes a wave through its own
pivot varying along n: phase φ = 2π·((p - c)·n)/λ. The (cos φ, sin φ) of the 16 neighboring cells (4x4)
are blended with distance weights, then **normalized to a unit vector**.

Normalization is the soul of this step: summing several cosines with different phases directly makes the amplitude swing (adding when in phase,
cancelling when out of phase); blending the 2D vector (cos, sin) and normalizing keeps the amplitude at 1, leaving only the phase
varying smoothly.

Weight is `exp(-2r^2) - exp(-2·1.5^2)`, r in cells, dropping to 0 **exactly** at r = 1.5.
The 4x4 block is [floor(u - 1.5), +3], and any pixel is at least 1.5 cells from the nearest pivot outside the block --
so the block choice has **no effect** on the result: the cell entering or leaving when the block shifts already has weight 0. This property
makes tiled generation stitch seamlessly (pinned in the tests). The original's weight is another "exp minus a constant" shape;
the coefficients here are our own.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Flat ground, peaks, valley floors: mask + fade target
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Flat ground has no flow direction and the stripe direction is random, so stripes are faded out by slope:

    m = 1 − (1 − clamp(|g|·steepness, 0, 1))²      (ease-out)
    F = lerp(target, stripe, m)

On flats m->0 and F falls back to the "fade target". With target `altitude` it maps height to [-1, 1]:
peaks +1 (fade into ridges), valley floors -1 (fade into gullies) -- a peak becomes a smooth ridge rather than a patch of noise.
Each layer's F becomes the next layer's target, so finer layers stay gullies at the bottom of big gullies and stay
ridges on top of big ridges. With `none` the target is 0: **flat ground doesn't move at all** (bit-exact in the tests).

The ease-out shape is one discussed in the blog (a square root causes discontinuities near peaks); it is used directly here.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What's lost compared with a simulation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · **No continuous river network**. Stripes are interpolated, so a gully may break off halfway down a slope; water doesn't
    actually collect at the lowest point. A real river network needs flow accumulation (stream power), which is another node
  · No deposition; valley floors don't get filled in
  · Gully depth depends only on **local** slope, not on how much water accumulates upstream -- so big river valleys aren't deeper than tributaries

What you get in return: stateless, independent per pixel, one pass, tileable generation, runs through the op table (on the
GPU if there is one).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tile and tiled generation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With tile=True the cell count is rounded to an integer (per layer) and the hash is taken modulo the cell count -- the stripe field itself is periodic,
so seamless input gives seamless output. With tile=False the cells extend infinitely in world space; together with the origin
parameter a large terrain can be split into several images computed separately and stitched without seams (the fade target needs an explicit
height range, otherwise each image uses its own min/max).
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from .filters import _conv1d, gaussian_kernel
from .heightmap import _grad, _height, _texel
from .noise import cell_hash, _to01

FADES = ("altitude", "none")
# weight reaches zero at 1.5 cells -- see "The stripe itself" in the file header
_R_CELLS = 1.5
_W_FLOOR = math.exp(-2.0 * _R_CELLS * _R_CELLS)
_SALT_U, _SALT_V = 31, 32


def _ease_out(xp, t):
    t = xp.clip(t, 0.0, 1.0)
    u = 1.0 - t
    return 1.0 - u * u


def _pivot_table(c0x, c1x, c0y, c1y, octave, seed, nwx, nwy):
    """
    Random pivot offsets (within the cell, [0,1)) for cells [c0x, c1x] x [c0y, c1y], as (Ny, Nx, 2) numpy.

    Computed once on numpy with an int64 hash, so both backends get **the same table** -- it's the same hash as
    noise.py's cell_hash, so numpy / torch results differ only by float32
    rounding. When nwx / nwy are not None, taken modulo the cell count (tile).
    """
    npb = bk.NUMPY
    xs = np.arange(c0x, c1x + 1, dtype=np.int64)
    ys = np.arange(c0y, c1y + 1, dtype=np.int64)
    if nwx:
        xs = np.mod(xs, nwx)
    if nwy:
        ys = np.mod(ys, nwy)
    CX, CY = np.meshgrid(xs, ys)
    CZ = np.full_like(CX, int(octave))
    ou = np.asarray(_to01(npb, cell_hash(npb, CX, CY, CZ, seed, _SALT_U)),
                    np.float64)
    ov = np.asarray(_to01(npb, cell_hash(npb, CX, CY, CZ, seed, _SALT_V)),
                    np.float64)
    return np.stack([ou, ov], -1)


def stripes(xp, u, v, nx, ny, cell_x, cell_y, lam, octave, seed=0,
            wrap=None):
    """
    Directional stripes. Returns the unit vector (cos Φ, sin Φ) as two (H, W) arrays.

      u  (W,) numpy: position of each column, **in cells** (world x / cell_x)
      v  (H,) numpy: position of each row, in cells
      nx, ny (H, W): direction the stripes vary along (unit vector, or zero vector)
      lam: wavelength (world units); cell_x / cell_y: cell size (world units)
      wrap: when (Nx, Ny), taken modulo the cell count

    Apart from the random pivots and the direction n, every quantity depends only on the row or column -- so the pivots go into a small per-cell table,
    and each kernel fetches once with "outer-product indexing" (np.ix_ style) instead of hashing 16 times per pixel.
    """
    u = np.asarray(u, np.float64)
    v = np.asarray(v, np.float64)
    bx = np.floor(u - _R_CELLS).astype(np.int64)       # bottom-left corner of the 4x4 block
    by = np.floor(v - _R_CELLS).astype(np.int64)
    c0x, c1x = int(bx.min()), int(bx.max()) + 3
    c0y, c1y = int(by.min()), int(by.max()) + 3
    nwx, nwy = (wrap if wrap else (None, None))
    T = xp.asarray(_pivot_table(c0x, c1x, c0y, c1y, octave, seed, nwx, nwy))
    k = 2.0 * math.pi / float(lam)
    # phase = k·((p - c)·n) = k·(du·cell_x·nx + dv·cell_y·ny), du/dv in cells
    ax = nx * (k * float(cell_x))
    ay = ny * (k * float(cell_y))
    C = None
    S = None
    for j in range(4):
        cy = by + j
        dv0 = xp.reshape(xp.asarray(v - cy), (-1, 1))        # (H,1)
        iy = cy - c0y
        for i in range(4):
            cx = bx + i
            du0 = xp.reshape(xp.asarray(u - cx), (1, -1))    # (1,W)
            ix = cx - c0x
            off = xp.outer_index(T, iy, ix)                   # (H,W,2)
            du = du0 - off[:, :, 0]
            dv = dv0 - off[:, :, 1]
            w = xp.maximum(xp.exp((du * du + dv * dv) * -2.0) - _W_FLOOR,
                           0.0)
            ph = du * ax + dv * ay
            c = w * xp.cos(ph)
            s = w * xp.sin(ph)
            C = c if C is None else C + c
            S = s if S is None else S + s
    ln = xp.sqrt(C * C + S * S)
    ok = ln > 1e-12
    inv = xp.where(ok, 1.0 / xp.where(ok, ln, ln * 0.0 + 1.0), ln * 0.0)
    # where all kernels cancel out (very rare), use (1, 0): phase 0, stripe value 1
    return xp.where(ok, C * inv, ln * 0.0 + 1.0), S * inv


def _cells(extent, lam, tile):
    """Cell size and cell count per layer. With tile the cell count is rounded and the cell slightly stretched to divide evenly."""
    if tile:
        n = max(1, int(round(extent / lam)))
        return extent / n, n
    return lam, None


def erode(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
          amplitude=0.01, wavelength=48.0, octaves=5, lacunarity=2.0,
          gain=0.35, steepness=2.0, flow_blur=0.25, fade="altitude",
          height_min=0.0, height_max=0.0, seed=0, tile=False, origin_x=0.0,
          origin_y=0.0, out_layer=DEFAULT_LAYER, mask_layer="erosion",
          keep=True, trace=None):
    """
    Erosion filter. On the returned image:

      out_layer   eroded height (**height values**, same units as the input -- strength divided back out;
                  by default overwrites the input layer, so a downstream Height to Normal needs no parameter changes)
      mask_layer  normalized erosion amount, [-1, 1]: ridges > 0, gullies < 0. Use it for texture layering
                  (gravel in gullies, grass on ridges). Leave empty to skip the output

    Parameters (world-scale conventions match the height-map family: height value x strength = world height,
    world_size = world width of the whole image):

      amplitude    depth of the coarsest layer's gullies (world units). Multiplied by gain each layer down
      wavelength   spacing of the coarsest layer's gullies (**pixels**). Divided by lacunarity each layer down
      steepness    slope is multiplied by this and passed through ease-out as the mask. Larger means gentler slopes also get gullies
      flow_blur    when each layer decides the flow direction, the **input** slope is first blurred to flow_blur x that layer's
                   wavelength. 0 = no blur (the original's approach). See "flow direction must be viewed at scale" below
      fade         altitude: flats fade into ridges / gullies by height; none: flats don't move at all
      height_min/max  height range used by altitude (height values). When equal, the image's own
                   min / max is used -- tiled generation must give explicit values, otherwise each tile uses its own
      origin_x/y   world coordinates of this image's bottom-left corner. In tiled generation each tile gives its own offset
      trace        for tests: pass in a list, and each layer appends one
                   {"nx", "ny", "mask", "lam"}. Not exposed on the node

    gain defaults to 0.35 rather than fractal noise's customary 0.5: when gain x lacunarity = 1 every layer's gullies
    have **exactly the same** maximum slope (amplitude x 2π / wavelength), and five layers stacked give equally steep clutter over the whole screen
    (the first version did exactly that; it only showed up once rendered). Below 1, finer layers are gentler, like real terrain.
    """
    if img is None:
        return CopImage()
    s = float(strength)
    if s == 0.0:
        raise ValueError("Strength can't be 0 (the output has to be divided back to height values)")
    if fade not in FADES:
        raise ValueError(f"Fade must be one of {FADES}")
    no = int(octaves)
    if not 0 <= no <= 12:
        raise ValueError("Octaves must be between 0 and 12")
    wl = float(wavelength)
    if not wl >= 1.0:
        raise ValueError("Wavelength must be at least 1 pixel")
    lac = float(lacunarity)
    if not lac > 1.0:
        raise ValueError("Lacunarity must be > 1 (each layer finer)")
    xp = img.backend
    W, H = img.xres, img.yres
    texel = _texel(world_size, W)
    tile = bool(tile)
    h = _height(img, layer, s)                       # (H,W,1) world height
    gx, gy = _grad(xp, h, tile)
    bx0 = gx * (1.0 / texel)                         # input world slope (H,W,1)
    by0 = gy * (1.0 / texel)
    gx = gy = None                                   # accumulated gully slope over the layers
    h2 = h[:, :, 0]
    fb = float(flow_blur)
    if fb < 0.0:
        raise ValueError("Flow Blur can't be negative")
    border = "wrap" if tile else "clamp"

    if fade == "altitude":
        lo, hi = float(height_min) * s, float(height_max) * s
        if hi < lo:
            lo, hi = hi, lo
        if hi == lo:
            lo, hi = xp.fmin_scalar(h2), xp.fmax_scalar(h2)
        if hi > lo:
            t = xp.clip((h2 - lo) * (2.0 / (hi - lo)) - 1.0, -1.0, 1.0)
        else:
            t = h2 * 0.0
    else:
        t = h2 * 0.0

    # world coordinates of each column / row (pixel centers)
    X = float(origin_x) + (np.arange(W, dtype=np.float64) + 0.5) * texel
    Y = float(origin_y) + (np.arange(H, dtype=np.float64) + 0.5) * texel
    Wx, Wy = W * texel, H * texel

    acc = h2 * 0.0
    a = float(amplitude)
    lam = wl * texel
    tot = 0.0
    k_st = float(steepness)
    for o in range(no):
        if a == 0.0:
            break
        cx, nxc = _cells(Wx, lam, tile)
        cy, nyc = _cells(Wy, lam, tile)
        # ── flow direction must be viewed at scale ────────────────────────────
        # undulations in the input much smaller than this layer's wavelength (small bumps, fine noise in AI height maps) shouldn't
        # decide where this layer's gullies flow: they make the flow direction turn back and forth within one gully's width, and the stripes
        # curl up into clumps of "worms". So the input slope is first blurred by this layer's wavelength, then the
        # gully slope accumulated from the earlier (all coarser) layers is added. The original's input is an analytic
        # smooth function and never hits this problem; real raster height maps always do
        sig = fb * lam / texel
        if sig > 0.3:
            k = gaussian_kernel(sig)
            bgx = _conv1d(xp, _conv1d(xp, bx0, k, 1, border), k, 0, border)
            bgy = _conv1d(xp, _conv1d(xp, by0, k, 1, border), k, 0, border)
        else:
            bgx, bgy = bx0, by0
        gx = bgx[:, :, 0] if gx is None else bgx[:, :, 0] + gx
        gy = bgy[:, :, 0] if gy is None else bgy[:, :, 0] + gy
        sl = xp.sqrt(gx * gx + gy * gy)
        inv = xp.where(sl > 1e-12, 1.0 / xp.maximum(sl, 1e-12), sl * 0.0)
        # flow direction d = -g/|g|, stripes' across direction n = d rotated 90 deg
        dx, dy = gx * (-1.0) * inv, gy * (-1.0) * inv
        nx, ny = dy * (-1.0), dx
        c, sn = stripes(xp, X / cx, Y / cy, nx, ny, cx, cy, lam, o, seed,
                        (nxc, nyc) if tile else None)
        m = _ease_out(xp, sl * k_st)
        if trace is not None:
            trace.append({"nx": nx, "ny": ny, "mask": m, "lam": lam,
                          "cos": c})
        F = t + m * (c - t)
        acc = acc + F * a
        # analytic derivative of this layer's gullies: d(cos Φ)/dp = -sin Φ · (2π/λ) · n, times mask and
        # amplitude. The derivatives of m and the target t themselves are ignored -- they vary slowly, and all that's needed here is
        # "where the next layer should flow", not an exact surface derivative
        q = sn * (m * (-a * 2.0 * math.pi / lam))
        # the next layer recomputes from "blurred input slope + gullies so far", so what's stored here is
        # only the gullies' part
        gx = gx - bgx[:, :, 0] + q * nx
        gy = gy - bgy[:, :, 0] + q * ny
        t = F
        tot += a
        a *= float(gain)
        lam /= lac
    out = img.copy() if keep else CopImage(W, H)
    out.set(str(out_layer).strip() or DEFAULT_LAYER,
            xp.reshape((h2 + acc) * (1.0 / s), (H, W, 1)))
    if str(mask_layer).strip():
        ml = acc * (1.0 / tot) if tot > 0 else acc
        out.set(str(mask_layer).strip(), xp.reshape(ml, (H, W, 1)))
    return out
