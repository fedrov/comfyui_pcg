"""
Five more noise types (batch C): bubble / crystal / phasor / curl / cloud.

Difference from COP Noise: coordinates are **normalized by image width, aspect preserved** (x = u·F, y = v·F·H/W) --
bubbles and crystals need to be round / square, not squashed by the image's aspect ratio. COP Noise uses uv × F
to stay bit-aligned with the geometry side; that's not needed here.

The 3D ones (Bubble, Crystal Noise 3D, Curl Noise 3D, Cloud Noise 3D) all
**take a slice at z = Offset Z**: feature points / potential fields are 3D, advancing z animates them, and
it's a real 3D volume moving (bubbles grow out of the slice and shrink back), not a 2D image translating.

━━ Where it's computed (pcg65)
Uses accel's compute engine: with Compute = auto, CUDA available and a large enough image it runs on the GPU (torch
**float64**), otherwise numpy (exact backend, float64). The hash is bit-identical on both sides (int64 emulating
uint64 exactly, see backend.py), and all floating point is float64 -- the image is the same with or without the GPU (tests
compare to 1e-9). On real hardware a 1024² bubble takes 7.7 s in numpy, mostly 27 neighbouring cells per pixel
× 6 hashes; pure arithmetic like that is negligible on a GPU.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from . import backend as bk
from . import accel as AC
from .core import check_res
from .noise import fractal_noise, cell_hash, _to01, METRICS
from . import noisepost as _pp
from .pattern import _base, _pix, _put_all
from .pixel import getn, _vec

NOISE_KINDS = ("bubble", "crystal", "phasor", "curl", "curl_3d", "cloud")
# pcg100 c3_noise: Houdini Phasor Noise's Type / Periodic Function. Houdini's second entry
# "Phasor Noise" (docs: Gabor-based, sharper shape) has no definition given; not implemented
PHASOR_TYPES = ("phasor_wave", "gabor_noise", "intensity_field")
PERIODIC = ("sine", "rectangle", "saw")


def _coords(X, W, H, frequency, offset):
    u, v = _pix(W, H)
    f = float(frequency)
    ox, oy, oz = _vec(offset, 3)
    x = X.arr(u * f + ox)
    y = X.arr(v * f * (H / W) + oy)
    return x, y, float(oz)


def _h01(X, cx, cy, cz, seed, salt):
    """Cell coordinates -> [0,1) hash random number (computed on X.ops, bit-identical on both backends)."""
    return _to01(X.ops, cell_hash(X.ops, cx, cy, cz, int(seed), salt))


def _cells3(X, x, y, z, seed, jitter=1.0):
    """
    Iterator over 3×3×3 neighbouring cells: (cell coordinates, displacement to the feature point). z is the slice height (scalar),
    so the z cell coordinate is the same over the whole image -- still hashed as an array so both backends are written the same way.

    jitter (pcg100, only passed by crystal): 1 = the old form (random over the whole cell, bit-identical); otherwise the random offset
    is scaled about the cell centre, 0 = regular grid (Houdini Crystal Noise's Jitter).
    """
    ops = X.ops
    ix, iy = ops.to_i64(X.floor(x)), ops.to_i64(X.floor(y))
    iz = ops.to_i64(X.floor(X.zeros_like(x) + z))
    for c in itertools.product((-1, 0, 1), repeat=3):
        cx, cy, cz = ix + c[0], iy + c[1], iz + c[2]
        hx = _h01(X, cx, cy, cz, seed, 1)
        hy = _h01(X, cx, cy, cz, seed, 2)
        hz = _h01(X, cx, cy, cz, seed, 3)
        if jitter != 1.0:
            j = float(jitter)
            hx, hy, hz = (0.5 + (hx - 0.5) * j, 0.5 + (hy - 0.5) * j,
                          0.5 + (hz - 0.5) * j)
        px = ops.asarray(cx) + hx
        py = ops.asarray(cy) + hy
        pz = ops.asarray(cz) + hz
        yield (cx, cy, cz), (x - px, y - py, z - pz)


def _cid(X, cx, cy, cz):
    """Cell coordinates -> a 24-bit id (for random colouring downstream; collision probability 1 in 16 million)."""
    ops = X.ops
    return ops.asarray(ops.and_i64(cell_hash(ops, cx, cy, cz, 0, 7),
                                   0xFFFFFF))


def bubble(X, x, y, z, seed, radius, density):
    """
    One sphere per cell (probability density), radius radius × (0.5 ~ 1) cells. The value at the slice is the sphere's
    **cross-section height** √(1 − d²/r²) -- as z advances the cross-sections grow out and shrink back one by one. Overlaps take the max.
    With radius ≤ 1 cell, 27 neighbours are guaranteed to cover everything (a sphere's centre is at most 1 cell from its cell, radius at most 1).
    """
    best = X.zeros_like(x)
    bid = X.zeros_like(x)
    for (cx, cy, cz), (dx, dy, dz) in _cells3(X, x, y, z, seed):
        on = _h01(X, cx, cy, cz, seed, 4) < float(density)
        r = float(radius) * (0.5 + 0.5 * _h01(X, cx, cy, cz, seed, 5))
        q = 1.0 - (dx * dx + dy * dy + dz * dz) / X.maximum(r * r, 1e-12)
        h = X.where(on, X.sqrt(X.maximum(q, 0.0)), 0.0)
        m = h > best
        best = X.where(m, h, best)
        bid = X.where(m, _cid(X, cx, cy, cz), bid)
    return {"": best, "id": bid}


def _mdist(X, dx, dy, dz, metric):
    if metric == "euclidean":
        return X.sqrt(dx * dx + dy * dy + dz * dz)
    if metric == "manhattan":
        return X.abs(dx) + X.abs(dy) + X.abs(dz)
    if metric == "chebyshev":
        return X.maximum(X.maximum(X.abs(dx), X.abs(dy)), X.abs(dz))
    raise ValueError(f"Metric must be one of {METRICS}")


def crystal(X, x, y, z, seed, sharpness, metric="euclidean", jitter=1.0):
    """
    Crystal: 3D Voronoi, each cell with a random plane h = r + s·(g · d), g a random unit vector,
    d the displacement to the feature point. Inside a cell it's one sloped facet, between cells there are creases -- a faceted look. _edge is
    F2 − F1 (0 at the creases).

    metric / jitter (pcg100): the distance metric and feature point jitter used to pick "which cell", corresponding to Houdini
    Crystal Noise's Primary Metric / Jitter. **The algorithm itself is still our random-facet one**, not
    Houdini's "two stacked Worley layers" (the docs don't give how they're combined), so the Secondary group is not implemented.
    """
    b1 = X.full(x.shape, math.inf)
    b2 = X.full(x.shape, math.inf)
    val = X.zeros_like(x)
    bid = X.zeros_like(x)
    for (cx, cy, cz), (dx, dy, dz) in _cells3(X, x, y, z, seed, jitter):
        d = _mdist(X, dx, dy, dz, metric)
        gx = _h01(X, cx, cy, cz, seed, 6) * 2 - 1
        gy = _h01(X, cx, cy, cz, seed, 7) * 2 - 1
        gz = _h01(X, cx, cy, cz, seed, 8) * 2 - 1
        gn = X.maximum(X.sqrt(gx * gx + gy * gy + gz * gz), 1e-9)
        h = _h01(X, cx, cy, cz, seed, 9) + float(sharpness) * (
            gx * dx + gy * dy + gz * dz) / gn
        m = d < b1
        b2 = X.where(m, b1, X.minimum(b2, d))
        b1 = X.where(m, d, b1)
        val = X.where(m, h, val)
        bid = X.where(m, _cid(X, cx, cy, cz), bid)
    return {"": val, "id": bid, "edge": b2 - b1}


def phasor(X, x, y, z, seed, stripe_freq, angle, spread, kernels,
           dir_field=None, to_pix=None):
    """
    Phasor noise (Tricard et al. 2019): take only the phase of the **complex sum** of Gabor kernels, sin(phase).
    Compared to Gabor noise, stripe contrast is the same everywhere (Gabor's amplitude fluctuates between kernels,
    so stripes come and go).

    kernels kernels per cell, random positions, direction = angle ± spread·random, frequency stripe_freq
    (stripes per cell), random phase + 2π·z (advancing z = flowing stripes). Gaussian bandwidth b = 1.5/cell; the weight at the
    1-cell cutoff is e^(−π·2.25) ≈ 8e-4, so checking 3×3 neighbours is enough.

    dir_field: (H,W,2) direction field (e.g. the gradient from COP Derivative rotated 90°); if given, the direction is taken
    at each kernel's **centre**, and the stripes follow the field.
    """
    ops = X.ops
    b = 1.5
    ix, iy = ops.to_i64(X.floor(x)), ops.to_i64(X.floor(y))
    zero = ix * 0
    sr = X.zeros_like(x)
    si = X.zeros_like(x)
    a0 = math.radians(float(angle))
    K = max(1, int(kernels))
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            cx, cy = ix + di, iy + dj
            for k in range(K):
                s0 = 10 + 4 * k
                kx = ops.asarray(cx) + _h01(X, cx, cy, zero, seed, s0)
                ky = ops.asarray(cy) + _h01(X, cx, cy, zero, seed, s0 + 1)
                if dir_field is not None:
                    ii, jj = to_pix(kx, ky)
                    dv = dir_field[ii, jj]
                    th = X.arctan2(dv[..., 1], dv[..., 0])
                else:
                    th = a0 + math.radians(float(spread)) * (
                        _h01(X, cx, cy, zero, seed, s0 + 2) - 0.5)
                ph = 2 * math.pi * (_h01(X, cx, cy, zero, seed, s0 + 3)
                                    + float(z))
                dx, dy = x - kx, y - ky
                g = X.exp(-math.pi * b * b * (dx * dx + dy * dy))
                arg = 2 * math.pi * float(stripe_freq) * (
                    X.cos(th) * dx + X.sin(th) * dy) + ph
                sr = sr + g * X.cos(arg)
                si = si + g * X.sin(arg)
    phase = X.arctan2(si, sr)
    return {"": 0.5 + 0.5 * X.sin(phase),
            "phase": phase / (2 * math.pi) + 0.5,
            "amplitude": X.hypot(sr, si),
            "_re": sr}


def phasor_main(X, lay, kernels, ptype="phasor_wave", periodic="sine"):
    """
    pcg100: Houdini Phasor Noise's Type / Periodic Function decide the main layer.

      phasor_wave      periodic function (of phase): sine = 0.5 + 0.5·sin(φ) (the original output, bit-identical),
                       rectangle = 1 where sin(φ) ≥ 0 else 0, saw = φ/2π + ½ (i.e. the _phase layer)
      gabor_noise      0.5 + 0.5·Re(S)/√K -- the real part of the kernels' complex sum, constructive / destructive where they overlap
      intensity_field  |S|/√K -- the intensity field behind the two above

    Where √K comes from (not fitted): K kernels per cell, Gaussian e^(−π b² r²), b = 1.5,
    E[Σg²] = K/(2b²) = K/4.5, so Re(S) has variance half that, K/9, standard deviation √K/3; dividing by √K gives
    "three standard deviations → ±1". This way |2·gabor − 1| ≤ intensity always holds.
    The docs give no formula for Saw's orientation ("linear transition from top to bottom") or Wave Bias (peak position): saw uses the phase
    itself; Wave Bias is not implemented.
    """
    if ptype not in PHASOR_TYPES:
        raise ValueError(f"Phasor Type must be one of {PHASOR_TYPES}")
    if periodic not in PERIODIC:
        raise ValueError(f"Periodic Function must be one of {PERIODIC}")
    k = math.sqrt(max(1, int(kernels)))
    if ptype == "gabor_noise":
        return 0.5 + 0.5 * lay["_re"] / k
    if ptype == "intensity_field":
        return lay["amplitude"] / k
    if periodic == "rectangle":
        return X.where(lay[""] >= 0.5, 1.0, 0.0)
    if periodic == "saw":
        return lay["phase"]
    return lay[""]


def _fbm(X, x, y, z, seed, octaves, rough=0.5):
    zz = z if not isinstance(z, float) else X.zeros_like(x) + z
    return fractal_noise(X.ops, x, y, zz, "simplex", "standard",
                         int(octaves), 2.0, float(rough),
                         int(seed) & 0xFFFFFFFF)


def curl2(X, x, y, z, seed, octaves, eps=1e-3):
    """
    2D curl noise: v = (∂ψ/∂y, −∂ψ/∂x), ψ a simplex fractal. Divergence is identically 0
    (mixed partials commute), so advecting particles / warping images with it won't clump or disperse. Derivatives use
    central differences of ±eps in noise space (the noise is C²; truncation error at 1e-3 is ~1e-6).
    Units: per noise unit; for "per pixel" multiply by Frequency / image width.
    """
    p = lambda a, b: _fbm(X, a, b, z, seed, octaves)       # noqa: E731
    dpx = (p(x + eps, y) - p(x - eps, y)) / (2 * eps)
    dpy = (p(x, y + eps) - p(x, y - eps)) / (2 * eps)
    return {"": X.stack([dpy, -dpx], -1), "potential": p(x, y)}


def curl3(X, x, y, z, seed, octaves, eps=1e-3):
    """
    3D curl noise: ∇ × (ψ₁, ψ₂, ψ₃), three potential fields with different seeds. Outputs three components on the z slice
    (vx, vy, vz) -- divergence-free in the 3D volume; looking only at (vx, vy) on the slice it isn't divergence-free (the
    ∂vz/∂z term is missing); that's slicing, not a bug.
    """
    zz = X.zeros_like(x) + z

    def P(k, a, b, c):
        return _fbm(X, a, b, c, int(seed) + 1013 * k, octaves)

    def d(k, axis):
        e = [0.0, 0.0, 0.0]
        e[axis] = eps
        return (P(k, x + e[0], y + e[1], zz + e[2])
                - P(k, x - e[0], y - e[1], zz - e[2])) / (2 * eps)
    vx = d(2, 1) - d(1, 2)
    vy = d(0, 2) - d(2, 0)
    vz = d(1, 0) - d(0, 1)
    return {"": X.stack([vx, vy, vz], -1)}


def cloud(X, x, y, z, seed, octaves, coverage, softness, billow):
    """
    Clouds: simplex fractal (optionally billow = absolute value, puffier clumps) mapped to 0~1, then cut into density by coverage
    and softness:

        t = (1 − coverage)(1 + s) − s/2,  density = clamp((n − t)/s + ½, 0, 1)

    transition band width s, centre t. t is chosen this way so both ends are **exact**: at coverage 0 the transition band is entirely
    above 1 (n ≤ 1, all empty), at coverage 1 entirely below 0 (n ≥ 0, all full), monotonic
    in between. The first draft used (n − (1 − coverage))/s, which at coverage 1 still left places with n < s empty.
    """
    n = _fbm(X, x, y, z, seed, octaves)
    n01 = X.clip(X.abs(n) if billow else 0.5 + 0.5 * n, 0.0, 1.0)
    s = max(float(softness), 1e-6)
    t = (1.0 - float(coverage)) * (1.0 + s) - s / 2
    d = X.clip((n01 - t) / s + 0.5, 0.0, 1.0)
    return {"": d, "raw": n01}


def noise_extra(img=None, kind="bubble", frequency=8.0, offset="0 0 0",
                octaves=3, radius=0.8, density=0.7, sharpness=1.0,
                stripe_freq=2.0, angle=0.0, spread=30.0, kernels=2,
                direction_layer="", coverage=0.5, softness=0.2, billow=False,
                seed=0, out_layer="noise", xres=512, yres=512,
                compute="auto", metric="euclidean", jitter=1.0,
                phasor_type="phasor_wave", periodic="sine", amplitude=1.0,
                center=0.0, post=None):
    """
    Bubble / Crystal / Phasor / Curl / Cloud. Main layer out_layer, auxiliary layers out_layer_xxx:
      bubble   main = cross-section height 0~1, _id
      crystal  main = facet height, _id, _edge (F2 − F1)
      phasor   main = 0.5 + 0.5·sin(phase), _phase (0~1), _amplitude
      curl     main = 2-channel velocity, _potential (stream function)
      curl_3d  main = 3-channel velocity (z slice)
      cloud    main = density 0~1, _raw
    compute: auto / cpu / cuda (see accel and the file header).

    pcg100 additions (defaults = old behaviour, bit-identical):
      metric / jitter            crystal's cell-picking distance metric, feature point jitter
      phasor_type / periodic     switch phasor's main layer to Gabor / intensity field / square wave / sawtooth (phasor_main)
      amplitude / center / post  only apply to the **main layer**: main × Amplitude + Center, then through
                                 Post Processing (the Range section + post-processing section of each Houdini noise node).
                                 Auxiliary layers (_id / _edge / _phase ...) are untouched
    """
    if kind not in NOISE_KINDS:
        raise ValueError(f"Kind must be one of {NOISE_KINDS}")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    check_res(W, H)
    X, _ = AC.pick(img, compute, W * H, 16)
    x, y, z = _coords(X, W, H, frequency, offset)
    sd = int(seed)
    if kind == "bubble":
        lay = bubble(X, x, y, z, sd, min(max(float(radius), 0.0), 1.0),
                     density)
    elif kind == "crystal":
        lay = crystal(X, x, y, z, sd, sharpness, metric, float(jitter))
    elif kind == "phasor":
        df = None
        dl = str(direction_layer).strip()
        if dl:
            df = getn(out, dl)
            if df.shape[2] < 2:
                raise ValueError("Direction Layer needs a 2-channel vector field")
            df = X.arr(df[..., :2])
        f = float(frequency)
        ox, oy, _ = _vec(offset, 3)

        def to_pix(kx, ky):
            # noise coordinates -> pixel indices (inverse of _coords): x = u·F + ox, y = v·F·H/W + oy
            j = X.ops.to_i64(X.floor((kx - ox) / f * W))
            i = X.ops.to_i64(X.floor((ky - oy) / f * W))
            return X.iclip(i, 0, H - 1), X.iclip(j, 0, W - 1)
        lay = phasor(X, x, y, z, sd, stripe_freq, angle, spread, kernels, df,
                     to_pix)
        lay[""] = phasor_main(X, lay, kernels, phasor_type, periodic)
        del lay["_re"]
    elif kind == "curl":
        lay = curl2(X, x, y, z, sd, octaves)
    elif kind == "curl_3d":
        lay = curl3(X, x, y, z, sd, octaves)
    else:
        lay = cloud(X, x, y, z, sd, octaves, coverage, softness, billow)
    lay = {k: X.np(v) for k, v in lay.items()}
    if float(amplitude) != 1.0 or float(center) != 0.0:
        lay[""] = lay[""] * float(amplitude) + float(center)
    lay[""] = _pp.run(bk.NUMPY, lay[""], post or {})
    return _put_all(out, like, str(out_layer).strip() or "noise", lay)
