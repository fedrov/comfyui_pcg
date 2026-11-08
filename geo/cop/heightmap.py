"""
The heightmap family: height <-> normal / AO / shadow / caustics / refraction, plus compositing and conversion of normals.

Counterparts of Copernicus's Height to Normal / Normal to Height / Height to Ambient
Occlusion / Height to Shadow / Height to Caustics / Refract from Height /
Combine Normals / Convert Normal.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One scale: strength x height value = world height, world_size = world width of the whole image
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The eight nodes of this family **share the same pair of scale parameters**, with the same defaults:

    world height  = height value × strength
    pixel spacing = world_size / width     (pixels are square)

So `Height to Normal` and `Normal to Height` with the same parameters are an exact inverse pair; the "slope" and "elevation" in AO,
shadow and caustics are also computed on the same world scale. If each node invented its own
"strength", after tuning the normals you would have to guess the multiplier all over again for AO.

A direct corollary (pinned in the tests): **scaling height and world_size up together by s**, normals,
AO and shadow don't change by a single pixel -- they depend only on angles.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Normals are **signed** vectors, tangent space, +Y = +v (OpenGL / "green up")
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The `N` layer stores [-1,1] unit vectors, not colours packed into 0-1 -- the same convention as the N from Render Pass
and ControlImage's normal kind; packing happens only at the exit. Normal maps read in from ComfyUI
are packed, so connect `COP Convert Normal` (packed -> signed) first.

COP row 0 is v=0 (the bottom), so the difference along rows **is directly** ∂h/∂v, no flip needed.
This is exactly the payoff of core.py fixing "v up": the DirectX convention (green down) is just a toggle on Convert Normal,
not a pile of `-gy` scattered everywhere.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Borders: tile=True treats them as periodic; with False, one-sided differences at the border
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With clamp padding, a central difference at the border gives (h1 − h0)/2 for the outermost ring -- **half**
the true slope. So a slope texture would have a ring of "flatter" normals along each of its four edges, i.e. a ring of
seams once applied. Here, after clamp padding, the outermost ring is multiplied by 2, turning it exactly back into the one-sided difference h1 − h0, so on a slope it is
**exact per pixel** (the tests include the border ring).

tile=True treats it as periodic -- that is how to set it for seamless textures. Then the neighbour of the right edge is the left edge;
if the image itself isn't seamless, a steep slope appears at the edge, and that is a problem with the image, not the operator.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What goes through the backend, what is numpy-only
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Through the op table (runs on both numpy / torch): Height to Normal, AO, Shadow, Refract,
Combine Normals, Convert Normal.

numpy-only (an image on CUDA makes one round trip):
  · Normal to Height -- needs an FFT, which the op table doesn't have
  · Caustics        -- needs bincount (accumulating photon landing points); torch's scatter_add is
                      non-deterministic on the GPU (the order of atomic adds varies), so running the same image twice
                      differs in the last digit, and caching would be pointless
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from .filters import _conv1d
from .transform import _cos_sin

GRADIENTS = ("central", "sobel")
INTEGRATORS = ("spectral", "exact")
BLENDS = ("rnm", "whiteout", "udn", "linear")
ENCODINGS = ("signed", "packed")


# ═══════════════════════════════════════════════════════════════════ helpers
def _texel(world_size, W):
    ws = float(world_size)
    if not ws > 0.0:
        raise ValueError(f"World Size must be > 0, got {world_size}")
    return ws / float(W)


def _height(img, layer, strength):
    """Takes **channel 0** of the height layer, times strength -> (H,W,1) world height.

    Multi-channel layers only use channel 0. A greyscale image read in from ComfyUI has 3 channels (R=G=B),
    and channel 0 is it; for a genuinely colour image, connect COP Luminance first -- no silent greyscale conversion here,
    the decision of which channel is the "height" should be visible in the graph.
    """
    a = img.need(layer)
    return a[:, :, 0:1] * float(strength)


def _diff(xp, a, axis, tile):
    """Central difference along one axis (per pixel). When not tiling, degenerates to a one-sided difference at the border."""
    n = int(a.shape[axis])
    if n == 1:
        return a * 0.0
    p = xp.pad_axis(a, 1, axis, "wrap" if tile else "clamp")
    hi = [slice(None)] * 3
    lo = [slice(None)] * 3
    hi[axis] = slice(2, 2 + n)
    lo[axis] = slice(0, n)
    d = (p[tuple(hi)] - p[tuple(lo)]) * 0.5
    if not tile:
        # After clamp padding the outermost ring is (h1-h0)/2; times 2 is exactly the one-sided difference -- see the file header
        s = np.ones(n)
        s[0] = s[-1] = 2.0
        sh = [1, 1, 1]
        sh[axis] = n
        d = d * xp.reshape(xp.asarray(s), tuple(sh))
    return d


def _grad(xp, h, tile, method="central"):
    """(gx, gy): per-pixel height differences. gy is along +v (increasing row)."""
    if method not in GRADIENTS:
        raise ValueError(f"Method must be one of {GRADIENTS}")
    gx = _diff(xp, h, 1, tile)
    gy = _diff(xp, h, 0, tile)
    if method == "sobel":
        # Add a [1,2,1]/4 smoothing along the other axis -- together this is Sobel divided by 8,
        # matching COP Edge Detect's normalization. On a slope the gradient is constant and smoothing a constant gives
        # itself, so Sobel is still exact per pixel on slopes
        k = np.array([0.25, 0.5, 0.25])
        b = "wrap" if tile else "clamp"
        gx = _conv1d(xp, gx, k, 0, b)
        gy = _conv1d(xp, gy, k, 1, b)
    return gx, gy


def _unit3(xp, x, y, z):
    inv = 1.0 / xp.sqrt(x * x + y * y + z * z)
    return x * inv, y * inv, z * inv


class _Shift:
    """
    Bilinear sampling of the whole image at one **constant** offset: out[i,j] = a(j + fx, i + fy).

    AO and shadow both "walk k steps in one direction, sampling the whole image once per step", with the same offset for every pixel.
    Bilinear sampling is then **a constant weighted sum of four slices** -- pad the image once by the largest step,
    and every step after that is just slicing (views in numpy, zero-copy), with no per-pixel gather.
    An order of magnitude faster than the general `filters.sample`, and exact on slopes (bilinear interpolation of a linear function
    is itself).

    With tile=False, out-of-bounds samples are not "padded values" but **invalid**: `inside()` gives
    a 0/1 mask, and the caller excludes them. Letting clamp-padded values take part in AO / shadow would
    invent a wall at the image border (padding amounts to treating outside the image as a plateau as high as the edge).
    """

    def __init__(self, xp, a, reach, tile):
        self.xp = xp
        self.H, self.W = int(a.shape[0]), int(a.shape[1])
        self.R = int(math.ceil(float(reach))) + 2
        m = "wrap" if tile else "clamp"
        self.p = xp.pad_axis(xp.pad_axis(a, self.R, 0, m), self.R, 1, m)

    def at(self, fx, fy):
        R, H, W = self.R, self.H, self.W
        x0, y0 = math.floor(fx), math.floor(fy)
        tx, ty = fx - x0, fy - y0
        acc = None
        for dx, wx in ((x0, 1.0 - tx), (x0 + 1, tx)):
            if wx == 0.0:
                continue
            for dy, wy in ((y0, 1.0 - ty), (y0 + 1, ty)):
                if wy == 0.0:
                    continue
                s = self.p[R + dy:R + dy + H, R + dx:R + dx + W]
                w = wx * wy
                t = s if w == 1.0 else s * w
                acc = t if acc is None else acc + t
        return acc

    def inside(self, fx, fy):
        """1 where the sample lies within [0, W-1] × [0, H-1], otherwise 0. (H,W,1)."""
        xp, H, W = self.xp, self.H, self.W
        j = np.arange(W) + fx
        i = np.arange(H) + fy
        vx = ((j >= 0) & (j <= W - 1)).astype(np.float64)
        vy = ((i >= 0) & (i <= H - 1)).astype(np.float64)
        return (xp.reshape(xp.asarray(vy), (H, 1, 1))
                * xp.reshape(xp.asarray(vx), (1, W, 1)))


def _out(img, keep):
    return img.copy() if keep else CopImage(img.xres, img.yres)


# ═══════════════════════════════════════════════════════ Height to Normal
def normal_from_grad(xp, gx, gy, k):
    """Per-pixel height difference × k (= strength / texel, separate from what's already in gx) -> unit normal."""
    nx, ny, nz = _unit3(xp, gx * (-k), gy * (-k), xp.ones(tuple(gx.shape)))
    return xp.concat([nx, ny, nz], -1)


def height_to_normal(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                     method="central", tile=False, out_layer="N", keep=True):
    """
    Height -> tangent-space normal `N = normalize(−∂h/∂x, −∂h/∂y, 1)`, ∂ on the world scale.

    Criterion (**per pixel** in the tests, including the border ring): on a slope `h = a·x + b·y`, every
    pixel's normal equals `normalize(−a, −b, 1)` exactly. Central differences and Sobel are both exact on linear functions,
    and so are one-sided differences -- so this criterion has no tolerance to hide anything in.

    `sobel` adds a smoothing in the perpendicular direction, more robust for noisy heightmaps (scans, AI-generated); `central`
    is sharper, and forms an exact inverse pair with the exact mode of `Normal to Height`.
    """
    if img is None:
        return CopImage()
    xp = img.backend
    k = 1.0 / _texel(world_size, img.xres)
    gx, gy = _grad(xp, _height(img, layer, strength), bool(tile), method)
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "N", normal_from_grad(xp, gx, gy, k))
    return out


# ═══════════════════════════════════════════════════════ Normal to Height
def _integrate(gx, gy, method):
    """
    Integrates height from a gradient field on a periodic domain: `argmin_h Σ |D h − g|²`, solved in one step in the Fourier domain.

        Ĥ = (conj(D̂x)·Ĝx + conj(D̂y)·Ĝy) / (|D̂x|² + |D̂y|²)

    The two modes differ only in what D̂ is:

      exact     D̂ = i·sin ω  -- exactly the frequency response of the **central difference**. An exact inverse of Height to
                Normal (central, tile): any height field converted there and back
                is restored per pixel (except for the 4 modes described below). The cost is that sin ω tends to 0 near ω->π,
                so for **inconsistent** normal maps (AI-generated, hand-painted) the components near there
                get amplified into a checkerboard pattern
      spectral  D̂ = i·ω      -- classic Frankot-Chellappa. Only one zero at DC,
                far more robust for inconsistent input. The cost is that it treats the central difference as the true derivative: a sine of frequency
                ω is restored with sin(ω)/ω times the amplitude -- 2.5% off at a period of 16 pixels,
                36% off at a period of 4 pixels. This ratio is **analytic**, and the tests use it as the criterion

    The exact mode has 4 modes that fundamentally can't be restored: DC (0,0), and the three "checkerboard" modes (π,0), (0,π), (π,π)
    -- the central difference responds to them with 0, so the gradient carries no information about them at all.
    These 4 modes are simply set to zero; not a bug, but information theory.
    """
    Hh, Ww = gx.shape
    wx = 2.0 * np.pi * np.fft.fftfreq(Ww)
    wy = 2.0 * np.pi * np.fft.fftfreq(Hh)
    if method == "exact":
        dx, dy = np.sin(wx), np.sin(wy)
    else:
        dx, dy = wx, wy
    DX = (1j * dx)[None, :]
    DY = (1j * dy)[:, None]
    den = (np.abs(DX) ** 2 + np.abs(DY) ** 2)
    num = np.conj(DX) * np.fft.fft2(gx) + np.conj(DY) * np.fft.fft2(gy)
    # sin(π) in floating point is 1.2e-16, not 0 -- without a threshold those "zero modes" would be
    # amplified into astronomical numbers by a 1e-32 denominator. The smallest **legitimate** denominator is sin²(2π/N),
    # still 1.5e-7 at N=16384, so a threshold of 1e-12 is far enough from both
    ok = den > 1e-12
    Hf = np.where(ok, num / np.where(ok, den, 1.0), 0.0)
    return np.real(np.fft.ifft2(Hf))


def normal_to_height(img, layer="N", strength=1.0, world_size=1.0,
                     method="spectral", tile=False, out_layer="height",
                     keep=True):
    """
    Normal -> height. The inverse of `Height to Normal`: with the same strength / world_size,
    the restored height **differs from the original by a constant** (the output has mean 0).

    With tile=False, **mirror extension** is used: the gradient field is assembled with even symmetry into a 2W×2H periodic field and solved,
    equivalent to a Neumann boundary (zero normal derivative at the border). This lets non-seamless images be integrated too, but near the
    border it is approximate -- the border slope from one-sided differences doesn't match the mirror extension's assumption of
    "zero slope at the border".

    **Here the exact mode is actually worse** (measured, pinned in the tests): on a 64² slope spectral's error
    is 0.2% of the amplitude and concentrated at the edges (only 0.04% left 4 pixels in); exact is 0.8%
    **and doesn't decay**. The reason is that the gradient is inconsistent at the mirror seams, and exact's weakness near ω->π
    amplifies it and spreads it over the whole image. So: exact is exact when tiling, use spectral when not tiling. Conversely,
    for a bump that is already flat at the border, both modes are nearly exact without tiling -- there is no
    inconsistency at the seams to speak of.

    Pixels whose normal z component is <= 0.01 (almost tangent to the surface, or facing down) are clamped to 0.01, otherwise
    the slope −nx/nz blows up. The number of clamped pixels goes into the report, not silently.
    """
    if img is None:
        return CopImage()
    if method not in INTEGRATORS:
        raise ValueError(f"Method must be one of {INTEGRATORS}")
    s = float(strength)
    if s == 0.0:
        raise ValueError("Strength cannot be 0 (height is divided by it)")
    texel = _texel(world_size, img.xres)
    a = img.need(layer)
    if a.shape[2] < 3:
        raise ValueError(f"Normal layer '{layer}' has only {a.shape[2]} channels, needs 3. "
                         f"For normal maps with only the xy channels, connect COP Convert Normal first "
                         f"with Reconstruct Z on.")
    xp = img.backend
    N = np.asarray(bk.backend_of(a).to_numpy(a), np.float64)
    nz = N[:, :, 2]
    clamped = int((nz < 0.01).sum())
    nz = np.maximum(nz, 0.01)
    # World slope -> per-pixel difference of height values (strength divided out, consistent with the forward direction)
    gx = -N[:, :, 0] / nz * (texel / s)
    gy = -N[:, :, 1] / nz * (texel / s)
    H, W = gx.shape
    if tile:
        h = _integrate(gx, gy, method)
    else:
        # Even extension: h even-symmetric about the border => ∂h/∂x is **odd**-symmetric about vertical borders, ∂h/∂y
        # even; likewise horizontally. The flip here is for the extension and is cropped back right away -- not the same thing as
        # the "flip v only at the exit" rule in core.py
        ex = np.concatenate([gx, -np.flip(gx, 1)], 1)
        ey = np.concatenate([gy, np.flip(gy, 1)], 1)
        ex = np.concatenate([ex, np.flip(ex, 0)], 0)
        ey = np.concatenate([ey, -np.flip(ey, 0)], 0)
        h = _integrate(ex, ey, method)[:H, :W]
    h = h - h.mean()
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "height",
            xp.asarray(h.astype(np.float32)[:, :, None]))
    out_report = {"clamped_nz": clamped, "pixels": H * W}
    return out, out_report


# ═════════════════════════════════════════════════════ Height to AO
def height_to_ao(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                 radius=16.0, directions=8, steps=8, intensity=1.0,
                 tile=False, out_layer="ao", keep=True):
    """
    Ambient occlusion on a height field (horizon-based). 1 = fully unoccluded, 0 = fully black.

    Each pixel walks `steps` steps in each of `directions` directions (at most `radius` pixels), finds
    the maximum elevation angle "above the tangent plane", takes its sine, attenuates by distance, and averages over directions.

    **Elevation is measured relative to the tangent plane**, not the horizontal. Relative to the horizontal, every point of an entire slope
    would be "blocked" looking uphill -- yet physically an infinite slope has no occlusion anywhere.
    Relative to the tangent plane:

      · any slope (including steep ones)  AO is **exactly** 1
      · convex (peaks, `h = −r²`)  AO exactly 1 -- every surrounding point is below the tangent plane
      · concave (pits, `h = +r²`)  AO < 1, and darker with greater curvature

    These three plus "invariant when height and world_size are scaled together" are this node's criteria.

    With tile=False, samples outside the image don't take part (not treated as a plateau as high as the edge -- that would give the image's downhill
    edges an extra invented ring of occlusion). The cost is `directions × steps` whole-image operations, 64 by default.
    """
    if img is None:
        return CopImage()
    D, S = int(directions), int(steps)
    if D < 1 or S < 1:
        raise ValueError("Directions and Steps must both be >= 1")
    if D > 64 or S > 64:
        raise ValueError(f"Directions × Steps is capped at 64 × 64, got {D} × {S}"
                         f" -- each combination is one whole-image operation")
    r = float(radius)
    if not r > 0.0:
        raise ValueError("Radius must be > 0 (pixels)")
    xp = img.backend
    texel = _texel(world_size, img.xres)
    h = _height(img, layer, strength)
    gx, gy = _grad(xp, h, bool(tile))
    smp = _Shift(xp, h, r, bool(tile))
    occ = None
    for d in range(D):
        c, s = _cos_sin(360.0 * d / D)
        best = None
        for k in range(S):
            f = (k + 0.5) / S
            t = r * f
            fx, fy = c * t, s * t
            dist = t * texel
            # Height above the tangent plane: exactly 0 on a slope. gx/gy are per-pixel height differences;
            # times the pixel offset gives the tangent plane's height there -- not converting to world slope first and back
            # saves two roundings
            rel = (smp.at(fx, fy) - h - (gx * fx + gy * fy)) / dist
            o = rel / xp.sqrt(rel * rel + 1.0)          # sin(atan(rel))
            o = xp.maximum(o, 0.0) * (1.0 - f * f)
            if not tile:
                o = o * smp.inside(fx, fy)
            best = o if best is None else xp.maximum(best, o)
        occ = best if occ is None else occ + best
    ao = xp.clip(1.0 - occ * (float(intensity) / D), 0.0, 1.0)
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "ao", ao)
    return out


# ═════════════════════════════════════════════════════ Height to Shadow
def height_to_shadow(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                     azimuth=45.0, elevation=30.0, softness=0.0,
                     max_distance=64.0, step=1.0, tile=False,
                     invert=False, out_layer="shadow", keep=True):
    """
    Shadows on a height field. **1 = in shadow**, 0 = lit (mask semantics, consistent with ID Masks).
    To multiply directly onto colour, turn on `invert` to get 1 = lit.

    `azimuth` is the direction the light comes **from** (0° = from +u, 90° = from +v), `elevation`
    is the sun's elevation angle. Each pixel walks towards the light up to `max_distance` pixels, and is in shadow if any sample's
    elevation exceeds the sun's elevation.

    Criteria: for a wall of height H with light from straight to the side, the shadow length is exactly `H / tan(elevation)`
    (in world scale), counted per pixel in the tests; at elevation = 90° the whole image has not a single shadow
    pixel; flat ground has none at all.

    softness is the sun's **angular radius** (degrees). 0 = hard shadow; above 0, a smoothstep between `elevation ± softness`
    -- a first-order approximation treating the sun as a disk of finite size, not an area-light integral.
    """
    if img is None:
        return CopImage()
    e = float(elevation)
    if not 0.0 < e <= 90.0:
        raise ValueError("Elevation must be in (0, 90] degrees")
    md, st = float(max_distance), float(step)
    if not st > 0.0 or not md > 0.0:
        raise ValueError("Max Distance and Step must both be > 0 (pixels)")
    n = int(math.ceil(md / st))
    if n > 4096:
        raise ValueError(f"Would take {n} steps (limit 4096) -- increase Step or decrease "
                         f"Max Distance. Each step is one whole-image sample")
    xp = img.backend
    texel = _texel(world_size, img.xres)
    h = _height(img, layer, strength)
    out = _out(img, keep)
    if e >= 90.0 and float(softness) <= 0.0:
        out.set(str(out_layer).strip() or "shadow",
                h * 0.0 + (1.0 if invert else 0.0))
        return out
    c, s = _cos_sin(azimuth)
    smp = _Shift(xp, h, md, bool(tile))
    m = None                                  # maximum slope towards the light
    if not tile:
        # The outermost ring on the light-facing side: the first step towards the light already leaves the image, so there are no samples,
        # and steep slopes facing away from the light (self-shadowing / the terminator) in that ring would be judged lit. Fall back on the one-sided
        # slope in the **direction away from the light** -- on a slope that is the slope's own gradient. Only affects pixels whose first step
        # leaves the image; the other pixels start at −∞, unaffected
        first = smp.inside(c * st, s * st)
        back_ok = smp.inside(-c * st, -s * st)
        back = (h - smp.at(-c * st, -s * st)) / (st * texel)
        use = (1.0 - first) * back_ok
        m = back * use + (use - 1.0) * 1e30
    for k in range(1, n + 1):
        t = min(k * st, md)
        fx, fy = c * t, s * t
        slope = (smp.at(fx, fy) - h) / (t * texel)
        if not tile:
            ins = smp.inside(fx, fy)
            slope = slope * ins + (ins - 1.0) * 1e30     # outside the image = −∞
        m = slope if m is None else xp.maximum(m, slope)
    soft = float(softness)
    if soft <= 0.0:
        # Hard shadows compare slopes directly without atan -- the wall criterion requires per-pixel exactness
        sh = xp.where(m > math.tan(math.radians(e)), h * 0.0 + 1.0, h * 0.0)
    else:
        ang = xp.arctan2(m, xp.ones(tuple(m.shape)))
        lo = math.radians(e - soft)
        hi = math.radians(e + soft)
        u = xp.clip((ang - lo) / (hi - lo), 0.0, 1.0)
        sh = u * u * (3.0 - 2.0 * u)
    if invert:
        sh = 1.0 - sh
    out.set(str(out_layer).strip() or "shadow", sh)
    return out


# ═══════════════════════════════════════════════════════════ refraction (shared)
def _refract(ix, iy, iz, nx, ny, nz, eta):
    """
    Vector form of Snell's law. I is the incident direction (downward), N the upward normal, eta = n1/n2.

    Only handles going from air into a denser medium (eta <= 1), with no total internal reflection; so k is always > 0.
    """
    cosi = -(nx * ix + ny * iy + nz * iz)
    k = 1.0 - eta * eta * (1.0 - cosi * cosi)
    c = eta * cosi - np.sqrt(np.maximum(k, 0.0)) if isinstance(k, np.ndarray) \
        else eta * cosi - math.sqrt(max(k, 0.0))
    return eta * ix + c * nx, eta * iy + c * ny, eta * iz + c * nz


def _ior(ior):
    v = float(ior)
    if v < 1.0:
        raise ValueError(f"IOR must be >= 1 (from air into water / glass), got {ior}. "
                         f"< 1 means looking out of a denser medium, with total internal reflection, which isn't handled here")
    return v


# ═════════════════════════════════════════════════════ Refract from Height
REFRACT_NORMAL_TYPES = ("signed", "offset")


def refract_from_height(img, layer=DEFAULT_LAYER, strength=1.0,
                        world_size=1.0, depth=0.1, ior=1.33, tile=False,
                        out_layer="refract", keep=True, directional=True,
                        view_azimuth=0.0, view_altitude=90.0,
                        view_position="0 0 10", height_offset=0.0,
                        normal_layer="", normal_type="signed",
                        ground_layer="", ground_offset=0.0, ground_scale=1.0,
                        ray_iterations=8, source_layer="",
                        refract_out_layer="refracted"):
    """
    Looking straight down through a "water surface", how far something at `depth` below appears shifted -> a 2-channel
    **uv offset**. Connect `COP Distort` (Units = uv, Amount = 1) for underwater distortion.

    The view ray enters from straight above, refracts at the water surface by the normal, and travels to the bottom at depth `depth`; the difference between the landing point and the point directly below
    is the offset. Distort samples in reverse ("where should this pixel take its value from"), which is exactly
    "where the view ray lands on the bottom", so no negation is needed.

    Criteria: a calm water surface gives an offset of **exactly 0**; with IOR = 1 the offset is 0 however rough the surface (no
    refraction, no offset); the offset is **linear** in depth; on a slope it shifts uphill (light entering a denser medium
    bends towards the inward normal).

    No Fresnel, no absorption, a single refraction -- this is a distortion field, not rendering.

    Added in pcg100 c7 (Houdini Refract from Height parameters; defaults = old behaviour, taking the original
    code path, bit-for-bit unchanged; if any is not at its default, _refract_ext is used, see the notes there):
    Directional / View Azimuth / View Altitude / View Position, Height Offset,
    the normal layer (Signed / Offset), the ground layer (Ground Offset / Scale, Ray Trace
    Iterations Newton steps), the source layer (sampled by the offset to give the refracted image).
    """
    if img is None:
        return CopImage()
    if normal_type not in REFRACT_NORMAL_TYPES:
        raise ValueError(f"Normal Type must be one of {REFRACT_NORMAL_TYPES}")
    if not (directional and float(view_altitude) == 90.0
            and float(height_offset) == 0.0 and not str(normal_layer).strip()
            and not str(ground_layer).strip()
            and not str(source_layer).strip()):
        return _refract_ext(img, layer, strength, world_size, depth, ior,
                            tile, out_layer, keep, directional, view_azimuth,
                            view_altitude, view_position, height_offset,
                            normal_layer, normal_type, ground_layer,
                            ground_offset, ground_scale, ray_iterations,
                            source_layer, refract_out_layer)
    eta = 1.0 / _ior(ior)
    xp = img.backend
    texel = _texel(world_size, img.xres)
    h = _height(img, layer, strength)
    gx, gy = _grad(xp, h, bool(tile))
    N = normal_from_grad(xp, gx, gy, 1.0 / texel)
    nx, ny, nz = N[:, :, 0:1], N[:, :, 1:2], N[:, :, 2:3]
    cosi = nz                                   # I = (0,0,-1)
    k = xp.maximum(1.0 - eta * eta * (1.0 - cosi * cosi), 0.0)
    c = eta * cosi - xp.sqrt(k)
    tx, ty, tz = c * nx, c * ny, c * nz - eta
    t = xp.maximum(h + float(depth), 0.0) / (-tz)
    ou = tx * t * (1.0 / float(world_size))
    ov = ty * t * (float(img.xres) / (float(world_size) * img.yres))
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "refract", xp.concat([ou, ov], -1))
    return out


def _refract_ext(img, layer, strength, world_size, depth, ior, tile,
                 out_layer, keep, directional, view_azimuth, view_altitude,
                 view_position, height_offset, normal_layer, normal_type,
                 ground_layer, ground_offset, ground_scale, ray_iterations,
                 source_layer, refract_out_layer):
    """
    Full version of Refract from Height (pcg100 c7, numpy). World coordinates: the water-surface point of pixel (j, i) is
    S = ((j+½)·texel, (i+½)·texel, h), texel = World Size / width, z up.

      view ray I   Directional on: looking down in parallel from azimuth Azimuth (0 = +x, counter-clockwise) and altitude Altitude,
               I = −(cos Alt·cos Az, cos Alt·sin Az, sin Alt); Altitude 90 = straight above
               (old behaviour). Off: looking from the point View Position (world coordinates, x y z as above),
               I = normalize(S − V).
      surface  h = height × Strength + Height Offset; the normal comes from the normal layer (Signed as-is / Offset
               first ×2−1, then normalized) or from central differences of height (same as the old version).
      refraction  Snell vector form: T = η·I + (η·cosi − √k)·N, η = 1/IOR, cosi = −I·N.
      bottom   without ground: the plane z = −Depth (old behaviour). With it: z = −Depth + Ground Offset +
               Ground Scale × ground(x, y), starting from the plane solution and doing Ray Trace Iterations Newton steps on
               f(t) = S_z + t·T_z − G(S_xy + t·T_xy), G sampled bilinearly, its gradient by central differences then
               sampled bilinearly. t is clamped to >= 0.
      output   offset = landing xy − S_xy, converted to uv (same convention as the old version); if a source layer is given, it is
               sampled bilinearly at uv + offset and written to Refract Output Layer.
    Not implemented: Ground IOR, Material / dispersion / absorption, reflection / environment map, Space, Kernel Size,
    Filter mentioned in the docs (see the notes). The docs don't state View Position's coordinate system; it is our choice.
    """
    from .filters import sample
    from .pixel import getn, put, _vec
    eta = 1.0 / _ior(ior)
    W, H = img.xres, img.yres
    tex = _texel(world_size, W)
    ws = float(world_size)
    h = getn(img, layer)[..., 0] * float(strength) + float(height_offset)
    if str(normal_layer).strip():
        n = getn(img, normal_layer)[..., :3]
        if normal_type == "offset":
            n = n * 2.0 - 1.0
        N = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-12)
    else:
        from . import backend as bk
        xp = bk.NUMPY
        h3 = h[..., None]
        gx, gy = _grad(xp, h3, bool(tile))
        N = np.asarray(normal_from_grad(xp, gx, gy, 1.0 / tex), np.float64)
    J, I_ = np.meshgrid(np.arange(W, dtype=np.float64),
                        np.arange(H, dtype=np.float64))
    Sx, Sy = (J + 0.5) * tex, (I_ + 0.5) * tex
    if directional:
        az, al = math.radians(float(view_azimuth)), \
            math.radians(float(view_altitude))
        d = np.array([-math.cos(al) * math.cos(az),
                      -math.cos(al) * math.sin(az), -math.sin(al)])
        Iv = np.broadcast_to(d, (H, W, 3))
    else:
        V = _vec(view_position, 3)
        Iv = np.stack([Sx - V[0], Sy - V[1], h - V[2]], -1)
        Iv = Iv / np.maximum(np.linalg.norm(Iv, axis=-1, keepdims=True), 1e-12)
    cosi = -(Iv * N).sum(-1, keepdims=True)
    k = np.maximum(1.0 - eta * eta * (1.0 - cosi * cosi), 0.0)
    T = eta * Iv + (eta * cosi - np.sqrt(k)) * N
    tz = np.minimum(T[..., 2], -1e-12)
    bd = "wrap" if tile else "clamp"
    if str(ground_layer).strip():
        g = getn(img, ground_layer)[..., :1]
        gp = np.pad(g[..., 0], 1, mode="wrap" if tile else "edge")
        dgx = ((gp[1:-1, 2:] - gp[1:-1, :-2]) * 0.5 / tex)[..., None]
        dgy = ((gp[2:, 1:-1] - gp[:-2, 1:-1]) * 0.5 / tex)[..., None]
        z0 = -float(depth) + float(ground_offset)
        gs = float(ground_scale)

        def G(x, y):
            u, v = x / (tex * W), y / (tex * H)
            return (z0 + gs * sample(g, u, v, bd)[..., 0],
                    gs * sample(dgx, u, v, bd)[..., 0],
                    gs * sample(dgy, u, v, bd)[..., 0])
        t = np.maximum(h - z0, 0.0) / (-tz)
        for _ in range(int(ray_iterations)):
            gz, gdx, gdy = G(Sx + t * T[..., 0], Sy + t * T[..., 1])
            f = h + t * T[..., 2] - gz
            fp = T[..., 2] - gdx * T[..., 0] - gdy * T[..., 1]
            fp = np.where(np.abs(fp) > 1e-12, fp, -1e-12)
            t = np.maximum(t - f / fp, 0.0)
    else:
        t = np.maximum(h + float(depth), 0.0) / (-tz)
    ou = T[..., 0] * t / ws
    ov = T[..., 1] * t * (float(W) / (ws * H))
    out = _out(img, keep)
    off = np.stack([ou, ov], -1)
    put(out, str(out_layer).strip() or "refract", off, img)
    if str(source_layer).strip():
        src = getn(img, source_layer)
        u = (J + 0.5) / W + ou
        v = (I_ + 0.5) / H + ov
        put(out, str(refract_out_layer).strip() or "refracted",
            sample(src, u, v, bd), img)
    return out


# ═════════════════════════════════════════════════════ Height to Caustics
def height_to_caustics(img, layer=DEFAULT_LAYER, strength=1.0,
                       world_size=1.0, depth=0.1, ior=1.33, azimuth=0.0,
                       elevation=90.0, supersample=2, tile=True,
                       out_layer="caustics", keep=True):
    """
    Light spots focused by the water surface onto the bottom. **1 = brightness under a calm surface**, > 1 where focused,
    < 1 where diverging.

    Done by photon tracing: each pixel emits `supersample²` photons, refracted at the surface by the normal,
    landing on the bottom at depth `depth`, "splatted" bilinearly into the 4 pixels around the landing point. Compared with the analytic approach of "computing the
    Jacobian determinant of the mapping and taking its reciprocal", splatting never divides by 0 on caustic lines -- and caustics are exactly
    where the Jacobian is 0.

    Criteria:
      · a calm surface is **exactly** 1 (photons land back where they started, and bilinear splatting of a uniform grid is still
        uniform)
      · with tile, **energy conservation**: the sum of all pixels exactly equals the pixel count
      · a raised bump on the surface is a converging lens, > 1 directly below; a dip is a diverging lens, < 1 directly below
      · with IOR = 1 the whole image ≈ 1 (no refraction, no caustics)

    Oblique light (elevation < 90°) shifts the whole light pattern by `depth·tan(refraction angle)`. Here
    **the shift of a calm surface is subtracted**, so the pattern lines up with the surface above it -- otherwise as soon as the light tilts, the pattern
    slides out of frame as a whole.

    Default tile=True: caustics are almost always used on seamless textures. Without tiling, two things happen: photons landing outside the image
    are lost; and **no photons land in from outside** -- the latter makes the outermost ring darker even for a calm surface
    (with supersample=2, 0.875 at edges and 0.766 at corners; the first version did this, and the tests caught it).
    Now the output is divided by the landing density of the same photons under a calm surface, so a calm surface is exactly 1 at the edges too;
    the cost is that without tiling it is no longer strictly conserved (it wasn't anyway -- photons get lost).

    No Fresnel, no absorption, a single refraction.
    """
    if img is None:
        return CopImage()
    eta = 1.0 / _ior(ior)
    ss = int(supersample)
    if not 1 <= ss <= 8:
        raise ValueError("Supersample must be between 1 and 8")
    e = float(elevation)
    if not 0.0 < e <= 90.0:
        raise ValueError("Elevation must be in (0, 90] degrees")
    xp = img.backend
    texel = _texel(world_size, img.xres)
    ex = bk.EXACT                                  # the splatting step is float64 throughout
    a = img.need(layer)
    h = np.asarray(bk.backend_of(a).to_numpy(a), np.float64)[:, :, 0:1] \
        * float(strength)
    H, W = h.shape[0], h.shape[1]
    tile = bool(tile)
    gx, gy = _grad(ex, h, tile)
    # Light propagation direction: from the sun towards the ground
    c, s = _cos_sin(azimuth)
    ce = 0.0 if e >= 90.0 else math.cos(math.radians(e))
    se = 1.0 if e >= 90.0 else math.sin(math.radians(e))
    lx, ly, lz = -ce * c, -ce * s, -se
    # Refraction direction on a calm surface -- used to subtract the overall shift
    fx0, fy0, fz0 = _refract(lx, ly, lz, 0.0, 0.0, 1.0, eta)
    sh_h, sh_x, sh_y = (_Shift(ex, h, 1, tile), _Shift(ex, gx, 1, tile),
                        _Shift(ex, gy, 1, tile))
    acc = np.zeros(H * W, np.float64)
    ref = np.zeros(H * W, np.float64)            # the same photons under a calm surface
    J = np.arange(W, dtype=np.float64)[None, :]
    I = np.arange(H, dtype=np.float64)[:, None]
    energy = 1.0 / (ss * ss)

    def splat(dst, X, Y):
        x0 = np.floor(X)
        y0 = np.floor(Y)
        fx_, fy_ = X - x0, Y - y0
        x0 = x0.astype(np.int64)
        y0 = y0.astype(np.int64)
        for dx, wx in ((0, 1.0 - fx_), (1, fx_)):
            for dy, wy in ((0, 1.0 - fy_), (1, fy_)):
                xi, yi = x0 + dx, y0 + dy
                w = (wx * wy * energy).ravel()
                if tile:
                    idx = ((yi % H) * W + (xi % W)).ravel()
                    dst += np.bincount(idx, w, H * W)
                else:
                    ok = ((xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)).ravel()
                    idx = (yi * W + xi).ravel()[ok]
                    dst += np.bincount(idx, w[ok], H * W)

    for qy in range(ss):
        oy = (qy + 0.5) / ss - 0.5
        for qx in range(ss):
            ox = (qx + 0.5) / ss - 0.5
            hz = sh_h.at(ox, oy)[:, :, 0]
            nx, ny, nz = _unit3(np, sh_x.at(ox, oy)[:, :, 0] * (-1.0 / texel),
                                sh_y.at(ox, oy)[:, :, 0] * (-1.0 / texel),
                                np.ones((H, W)))
            tx, ty, tz = _refract(lx, ly, lz, nx, ny, nz, eta)
            L = np.maximum(hz + float(depth), 0.0)
            # landing point (pixels) = start + displacement − the same displacement for a calm surface
            X = J + ox + L * (tx / -tz - fx0 / -fz0) / texel
            Y = I + oy + L * (ty / -tz - fy0 / -fz0) / texel
            splat(acc, X, Y)
            if not tile:
                splat(ref, J + ox + 0.0 * X, I + oy + 0.0 * Y)
    if not tile:
        # Without tiling the outermost ring is inherently darker: no photons land in from outside the image. With supersample=2
        # it is 0.875 at edges and 0.875² at corners -- **a calm surface** too (showed up as soon as the tests ran).
        # Dividing by the landing density of the same photons under a calm surface makes "1 = brightness under a calm surface" hold
        # at the edges too. With tile this reference image is exactly 1 everywhere, so it isn't computed
        acc = acc / ref
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "caustics",
            xp.asarray(acc.reshape(H, W, 1).astype(np.float32)))
    return out


# ═══════════════════════════════════════════════════════ Combine Normals
def _xyz(xp, a, name):
    if a.shape[2] < 3:
        raise ValueError(f"Normal layer '{name}' has only {a.shape[2]} channels, needs 3")
    return a[:, :, 0:1], a[:, :, 1:2], a[:, :, 2:3]


def combine_normals(img, base_layer="N", detail=None, detail_layer="N",
                    method="rnm", amount=1.0, out_layer="N", keep=True):
    """
    Layers two normal maps: the large-scale `base` + the detail `detail`. Both must be **signed** tangent-space
    normals (connect Convert Normal first for packed ones).

      rnm       Reoriented Normal Mapping (Barré-Brisebois & Hill 2012). **Rotates** the detail
                normal into the base normal's frame -- detail on steep slopes turns with the slope
                instead of being flattened. The default mode
      whiteout  (bx + dx, by + dy, bz · dz) then normalized. Cheap, detail weaker on steep slopes
      udn       (bx + dx, by + dy, bz) then normalized. Cheaper, weaker detail
      linear    base + detail then normalized. The worst, kept only for comparison -- adding a flat detail (0,0,1)
                still bends base towards +z, weakening the slope

    `amount` scales the detail's xy (0 = no detail). Criteria: when the detail is flat (0,0,1),
    rnm / whiteout / udn all return base **unchanged** (linear does not, see above); when base is
    flat, rnm returns detail unchanged; the result is always a unit vector.

    (The first version said "all four modes return base unchanged" here; as soon as the tests ran linear was off by 0.65 --
    the documentation was wrong, not the code.)

    Without detail connected, it is taken from `detail_layer` of the same image; at a different resolution it is resampled to base first.
    """
    if img is None:
        return CopImage()
    if method not in BLENDS:
        raise ValueError(f"Method must be one of {BLENDS}")
    xp = img.backend
    src = img
    if detail is not None:
        from .core import conform
        src = conform(detail, img)
    d = src.need(detail_layer)
    if src.backend is not xp:
        d = xp.asarray(bk.backend_of(d).to_numpy(d))
    bx, by, bz = _unit3(xp, *_xyz(xp, img.need(base_layer), base_layer))
    dx, dy, dz = _xyz(xp, d, detail_layer)
    amt = float(amount)
    dx, dy, dz = _unit3(xp, dx * amt, dy * amt, dz)
    if method == "rnm":
        tx, ty, tz = bx, by, bz + 1.0
        ux, uy, uz = -dx, -dy, dz
        dot = tx * ux + ty * uy + tz * uz
        # tz > 0 when bz > −1; bz = −1 (normal facing down) is not a tangent-space normal in the first place
        q = dot / xp.maximum(tz, 1e-12)
        rx, ry, rz = tx * q - ux, ty * q - uy, tz * q - uz
    elif method == "whiteout":
        rx, ry, rz = bx + dx, by + dy, bz * dz
    elif method == "udn":
        rx, ry, rz = bx + dx, by + dy, bz
    else:
        rx, ry, rz = bx + dx, by + dy, bz + dz
    rx, ry, rz = _unit3(xp, rx, ry, rz)
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "N", xp.concat([rx, ry, rz], -1))
    return out


# ════════════════════════════════════════════════════════ Convert Normal
def convert_normal(img, layer=DEFAULT_LAYER, decode="packed",
                   encode="signed", flip_red=False, flip_green=False,
                   reconstruct_z=False, normalize=True, out_layer="N",
                   keep=True):
    """
    Converts between normal-map conventions. Fixed order:

        decode -> reconstruct z -> flip -> normalize -> encode

      decode / encode  `packed` = 0-1 colour (the kind stored in texture files), `signed` =
                       [-1,1] vectors (the kind used inside this plugin)
      flip_green       OpenGL (+Y up, this plugin) <-> DirectX (+Y down). Getting it wrong
                       shows as bumps reversed in one direction, without an error
      reconstruct_z    reconstructs z = √(1 − x² − y²) from just the xy channels. BC5 / two-channel
                       compressed normal maps store only xy
      normalize        vectors decoded from 8-bit textures are only "roughly length 1"

    Criteria: packed -> signed -> packed is the identity; flipping twice is the bit-for-bit identity; z reconstructed from
    the xy of unit normals matches the original.

    Tangent space <-> world space is not implemented: that needs a per-pixel tangent frame (three layers P / N / uv), and
    the heightmap chain has none of that. For world space, output N directly from Render Pass.
    """
    if img is None:
        return CopImage()
    if decode not in ENCODINGS or encode not in ENCODINGS:
        raise ValueError(f"Decode / Encode must be one of {ENCODINGS}")
    xp = img.backend
    a = img.need(layer)
    need = 2 if reconstruct_z else 3
    if a.shape[2] < need:
        raise ValueError(
            f"'{layer}' has only {a.shape[2]} channels, needs {need}"
            + ("" if reconstruct_z else " -- with only xy, turn on Reconstruct Z"))
    x, y = a[:, :, 0:1], a[:, :, 1:2]
    z = None if reconstruct_z else a[:, :, 2:3]
    if decode == "packed":
        x, y = x * 2.0 - 1.0, y * 2.0 - 1.0
        if z is not None:
            z = z * 2.0 - 1.0
    if reconstruct_z:
        z = xp.sqrt(xp.maximum(1.0 - x * x - y * y, 0.0))
    if flip_red:
        x = -x
    if flip_green:
        y = -y
    if normalize:
        ln = xp.sqrt(x * x + y * y + z * z)
        ln = xp.where(ln < 1e-12, ln * 0.0 + 1.0, ln)
        x, y, z = x / ln, y / ln, z / ln
    if encode == "packed":
        x, y, z = x * 0.5 + 0.5, y * 0.5 + 0.5, z * 0.5 + 0.5
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "N", xp.concat([x, y, z], -1))
    return out
