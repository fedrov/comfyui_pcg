"""
COP noise -- backend-neutral (numpy or torch/CUDA).

A 3D-only port of the four noise types in `attribnoise`. **Not a redesign**: hash, gradient table,
fade curve and normalization constants are all copied verbatim, so that the GPU path computes the same noise as the geometry side.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why port it instead of calling the original directly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`attribnoise.fractal_noise` is hard-wired to numpy + float64 + uint64:

    · torch **simply doesn't have** uint64 bitwise ops (uint64 in torch is only a placeholder type)
    · float64 on consumer GPUs runs at 1/32 ~ 1/64 the speed of fp32; using it on the GPU defeats the purpose
    · things like `np.select` / `np.einsum` need rewriting

So it's rewritten here, but **line by line against** the original, and tests compare the two point by point.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The hash is **bit-identical** on both backends; the interpolation isn't
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
splitmix64 uses int64 wrap-around multiplication + masked logical right shift to emulate uint64 exactly (details in
backend.py). So "which cell gets which random number" is exactly the same on both sides -- the noise **pattern** is
identical.

What differs is the interpolation afterwards: the numpy path uses float64, the torch path float32. Measured max
difference ~1e-6, invisible to the eye, but `np.array_equal` fails. The previous batch's "COP noise is **bit-identical**
to the geometry side" therefore only holds on the `exact` backend -- the only thing lost in moving to the GPU,
so a toggle was kept instead of quietly changing it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3D only
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COP is 2D; sample points are always "uv plane + a z offset", so 4D is never needed. The 4D set
(for animation) stays in `attribnoise`; use the exact backend when it's needed. With the dimension-generic loop
removed, the corners are a hard-coded 8 / 27, which saves a pile of dynamic branches on the GPU.
"""
from __future__ import annotations

import itertools

import numpy as np

from . import backend as bk

NOISE_TYPES = ("value", "perlin", "simplex", "worley", "worley_f2f1")
FRACTALS = ("none", "standard", "terrain", "hybrid_terrain")
# pcg100 c3_noise: two types for COP only (attribnoise doesn't have them; NOISE_TYPES is kept identical
# to it). white = Houdini's White (Random): one constant random value per cell, no interpolation;
# torus = Houdini's Torus: 4D simplex on a flat torus -- it isn't a new basis function but a
# coordinate mapping "simplex + wrap both u and v into circles", so it's handled in generate.noise and
# by the time it gets here it has become simplex4
NOISE_TYPES_COP = NOISE_TYPES + ("white", "torus")
# Worley distance metrics (the three entries of Houdini's Metric menu, in docs order)
METRICS = ("euclidean", "manhattan", "chebyshev")

_MULT = (0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F)
# Multiplier dedicated to the 4th dimension (time). **It must be a different constant**, and the term is 0 when cw=0 --
# so 4D noise on the w=0 slice is **bit-identical** to 3D noise, and "adding a time axis" won't change
# all existing static assets
_MULT_W = 0x94D049BB
_GRAD3 = np.array([[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
                   [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                   [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1]],
                  np.float64)
_F3, _G3 = 1.0 / 3.0, 1.0 / 6.0
_TWO53 = float(1 << 53)


def _mix(xp, x):
    """splitmix64. Overflow (wrap-around) is part of the algorithm; both backends rely on int64 wrap-around."""
    x = xp.xor_i64(x, xp.lshr_i64(x, 33))
    x = xp.mul_i64(x, 0xFF51AFD7ED558CCD)
    x = xp.xor_i64(x, xp.lshr_i64(x, 33))
    x = xp.mul_i64(x, 0xC4CEB9FE1A85EC53)
    x = xp.xor_i64(x, xp.lshr_i64(x, 33))
    return x


def cell_hash(xp, cx, cy, cz, seed=0, salt=0, cw=None):
    """
    (...,) integer cell coordinates -> int64 hash. Bit-identical to attribnoise._cell_hash.

    If cw is given, one more dimension (time) is mixed in. With cw all 0 the term contributes 0, so the w=0 slice is
    bit-identical to the 3D version -- the only compatibility 4D noise must preserve.
    """
    base = (int(seed) * 0x165667B1 + int(salt) * 0x27D4EB2F)
    base = (base + (1 << 63)) % (1 << 64) - (1 << 63)     # wrap around to int64
    k = xp.add_i64(xp.mul_i64(cx, _MULT[0]), base)
    k = xp.add_i64(k, xp.mul_i64(cy, _MULT[1]))
    k = xp.add_i64(k, xp.mul_i64(cz, _MULT[2]))
    if cw is not None:
        k = xp.add_i64(k, xp.mul_i64(cw, _MULT_W))
    return _mix(xp, k)


def _to01(xp, h):
    """hash -> [0,1)."""
    return xp.asarray(xp.lshr_i64(h, 11)) / _TWO53


def _grad_table(xp):
    return xp.asarray(_GRAD3)


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _corner_weight(xp, u, corner):
    w = None
    for k in range(len(corner)):
        wk = u[k] if corner[k] else (1.0 - u[k])
        w = wk if w is None else w * wk
    return w


def value_noise(xp, x, y, z, seed=0):
    """Random values at the eight lattice points, interpolated with the quintic fade curve."""
    fx, fy, fz = xp.floor(x), xp.floor(y), xp.floor(z)
    ix, iy, iz = xp.to_i64(fx), xp.to_i64(fy), xp.to_i64(fz)
    u = [_fade(x - fx), _fade(y - fy), _fade(z - fz)]
    n = None
    for c in itertools.product((0, 1), repeat=3):
        h = cell_hash(xp, ix + c[0], iy + c[1], iz + c[2], seed)
        term = _corner_weight(xp, u, c) * _to01(xp, h)
        n = term if n is None else n + term
    return n * 2.0 - 1.0


def perlin(xp, x, y, z, seed=0):
    """Classic gradient noise: directions are placed on lattice points; what's interpolated is "where this direction points"."""
    fx, fy, fz = xp.floor(x), xp.floor(y), xp.floor(z)
    ix, iy, iz = xp.to_i64(fx), xp.to_i64(fy), xp.to_i64(fz)
    rx, ry, rz = x - fx, y - fy, z - fz
    u = [_fade(rx), _fade(ry), _fade(rz)]
    tbl = _grad_table(xp)
    n = None
    for c in itertools.product((0, 1), repeat=3):
        h = cell_hash(xp, ix + c[0], iy + c[1], iz + c[2], seed)
        g = xp.gather_rows(tbl, xp.umod_i64(h, 12))
        dot = (g[..., 0] * (rx - c[0]) + g[..., 1] * (ry - c[1])
               + g[..., 2] * (rz - c[2]))
        term = _corner_weight(xp, u, c) * dot
        n = term if n is None else n + term
    return n


def _sel(xp, conds, vals, default):
    """Backend-neutral np.select: nest where from back to front."""
    out = xp.full(conds[0].shape, float(default))
    for c, v in zip(reversed(conds), reversed(vals)):
        out = xp.where(c, xp.full(conds[0].shape, float(v)), out)
    return out


def simplex(xp, x, y, z, seed=0):
    """3D simplex noise. The corner order picks one of six cases from the ordering of x/y/z."""
    s = (x + y + z) * _F3
    fx, fy, fz = xp.floor(x + s), xp.floor(y + s), xp.floor(z + s)
    ix, iy, iz = xp.to_i64(fx), xp.to_i64(fy), xp.to_i64(fz)
    t = (fx + fy + fz) * _G3
    x0, y0, z0 = x - (fx - t), y - (fy - t), z - (fz - t)

    ge_xy, ge_yz, ge_xz = x0 >= y0, y0 >= z0, x0 >= z0
    lt = lambda a: ~a if isinstance(a, np.ndarray) else ~a          # noqa
    conds = [ge_xy & ge_yz,
             ge_xy & (~ge_yz) & ge_xz,
             ge_xy & (~ge_xz),
             (~ge_xy) & (~ge_yz),
             (~ge_xy) & ge_yz & (~ge_xz)]
    o1 = [_sel(xp, conds, [1, 1, 0, 0, 0], 0),
          _sel(xp, conds, [0, 0, 0, 0, 1], 1),
          _sel(xp, conds, [0, 0, 1, 1, 0], 0)]
    o2 = [_sel(xp, conds, [1, 1, 1, 0, 0], 1),
          _sel(xp, conds, [1, 0, 0, 1, 1], 1),
          _sel(xp, conds, [0, 1, 1, 1, 1], 0)]

    zero = [xp.full(x0.shape, 0.0)] * 3
    one = [xp.full(x0.shape, 1.0)] * 3
    corners = [
        (zero, [x0, y0, z0]),
        (o1, [x0 - o1[0] + _G3, y0 - o1[1] + _G3, z0 - o1[2] + _G3]),
        (o2, [x0 - o2[0] + 2 * _G3, y0 - o2[1] + 2 * _G3,
              z0 - o2[2] + 2 * _G3]),
        (one, [x0 - 1.0 + 3 * _G3, y0 - 1.0 + 3 * _G3, z0 - 1.0 + 3 * _G3]),
    ]
    tbl = _grad_table(xp)
    n = None
    for off, xi in corners:
        tt = 0.6 - (xi[0] * xi[0] + xi[1] * xi[1] + xi[2] * xi[2])
        h = cell_hash(xp, ix + xp.to_i64(off[0]), iy + xp.to_i64(off[1]),
                      iz + xp.to_i64(off[2]), seed)
        g = xp.gather_rows(tbl, xp.umod_i64(h, 12))
        dot = g[..., 0] * xi[0] + g[..., 1] * xi[1] + g[..., 2] * xi[2]
        term = xp.where(tt > 0, (tt ** 4) * dot, xp.full(tt.shape, 0.0))
        n = term if n is None else n + term
    return n * 32.0


def _jit(xp, c, h, jitter):
    """
    Feature point position within a cell. jitter = 1 is the old form c + h (random over the whole cell, bit-identical);
    otherwise per Houdini's Jitter: scale the random offset about the cell centre, 0 = regular grid.
    """
    if jitter == 1.0:
        return xp.asarray(c) + h
    return xp.asarray(c) + (0.5 + (h - 0.5) * jitter)


def _metric(xp, ds, metric):
    """List of displacement components -> distance. euclidean uses the old form (bit-identical)."""
    if metric == "euclidean":
        acc = None
        for d in ds:
            acc = d * d if acc is None else acc + d * d
        return xp.sqrt(acc)
    if metric == "manhattan":
        acc = None
        for d in ds:
            acc = xp.abs(d) if acc is None else acc + xp.abs(d)
        return acc
    if metric == "chebyshev":
        acc = None
        for d in ds:
            acc = xp.abs(d) if acc is None else xp.maximum(acc, xp.abs(d))
        return acc
    raise ValueError(f"Metric must be one of {METRICS}")


def _rng(mode, metric):
    """
    Neighbour-cell search range. Default ±1 (27 / 81 cells). F2 + Manhattan's diamond unit ball reaches far,
    so the second-nearest point can lie in the next ring out (measured 0.49% wrong before) -- that mode searches ±2 (125 / 625 cells).
    Only that mode gets slower; everything else is bit-identical.
    """
    if mode == "f2f1" and metric == "manhattan":
        return (-2, -1, 0, 1, 2)
    return (-1, 0, 1)


def worley(xp, x, y, z, seed=0, mode="f1", metric="euclidean", jitter=1.0):
    """
    Cellular noise: distance to the nearest feature point. One random feature point per cell, 27 neighbouring cells searched.

    All 27 neighbours are unrolled (hard-coded 3D); on the GPU that's 27 branch-free element-wise passes.

    metric / jitter (pcg100): the Metric and Jitter of Houdini Fractal Noise's two Worley modes.
    The defaults euclidean / 1.0 take the original lines, bit-identical. With jitter > 1 feature points
    can escape the 27-neighbour search range -- the Houdini docs likewise warn of artifacts. Measured with jitter = 1,
    100k points against a 125-neighbour brute force: F1 correct for all three metrics; F2 correct for Euclidean / Chebyshev, Manhattan
    0.49% wrong with 27 neighbours (the diamond unit ball reaches far; the second-nearest point is occasionally in the next ring) -- so
    the worley_f2f1 + manhattan mode searches 125 neighbours (see _rng); the rest remain 27.
    """
    ix, iy, iz = xp.to_i64(xp.floor(x)), xp.to_i64(xp.floor(y)), \
        xp.to_i64(xp.floor(z))
    big = 1e30
    b1 = xp.full(x.shape, big)
    b2 = xp.full(x.shape, big)
    jitter = float(jitter)
    for c in itertools.product(_rng(mode, metric), repeat=3):
        cx, cy, cz = ix + c[0], iy + c[1], iz + c[2]
        px = _jit(xp, cx, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 1)), jitter)
        py = _jit(xp, cy, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 2)), jitter)
        pz = _jit(xp, cz, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 3)), jitter)
        dx, dy, dz = x - px, y - py, z - pz
        d = _metric(xp, (dx, dy, dz), metric)
        b2 = xp.minimum(b2, xp.maximum(b1, d))
        b1 = xp.minimum(b1, d)
    if mode == "f2f1":
        return xp.clip((b2 - b1) * 2.0 - 1.0, -1.0, 1.0)
    return xp.clip(1.0 - 2.0 * b1, -1.0, 1.0)




# ═══════════════════════════════════════════════════════════════ 4D
# The time axis.
#
# Compatibility first, because it's easy to assume wrongly:
#
#   · **Existing 3D workflows don't change by a single bit.** w defaults to None, the 3D path is left
#     untouched, and the "bit-identical to attribnoise" property is fully preserved
#   · **Only value noise's w=0 slice equals the 3D version** (measured bit-identical). The other three
#     can't be equal, each for its own reason:
#       perlin4 must use a 4D gradient table (the 12 3D vectors aren't isotropic in 4D)
#       simplex4's simplicial subdivision itself is different (5 corners vs 4, different skew constants too)
#       worley4's feature points also have a [0,1) random offset in w, so the distance at w=0 isn't 0
#     Measured max difference between the w=0 slice and the 3D version: perlin 1.44 / simplex 2.23 / worley 1.78
#
# So "set time to 0 on the static image to get the original image back" only holds for value.
# Rather than let people find out the hard way, the numbers are written here.
#
# 4D gradients: all permutations of the form (0,±1,±1,±1), 32 in total. Vertices of a 4D regular polytope;
# this is the most standard set in 4D -- the same construction as the 12 in 3D (permutations of ±1,±1,0).
_GRAD4 = np.array(
    [[0, a, b, c] for a in (1, -1) for b in (1, -1) for c in (1, -1)]
    + [[a, 0, b, c] for a in (1, -1) for b in (1, -1) for c in (1, -1)]
    + [[a, b, 0, c] for a in (1, -1) for b in (1, -1) for c in (1, -1)]
    + [[a, b, c, 0] for a in (1, -1) for b in (1, -1) for c in (1, -1)],
    np.float64)
_F4 = (np.sqrt(5.0) - 1.0) / 4.0
_G4 = (5.0 - np.sqrt(5.0)) / 20.0
# The scale constant is **measured**: over 2 million random samples the unscaled |value| max is 0.036559,
# reciprocal 27.353 -- 27.0 is used (measured max 0.987, same magnitude as the 3D version's 0.975).
# The 3D side's scale=32 uses the same yardstick. Copy a constant and find the range is 0.7 or 1.4, and
# every remap / threshold downstream has to be retuned, and you only notice by putting the two noises side by side.
_SIMPLEX4_SCALE = 27.0
# perlin4's amplitude also needs damping, otherwise the amplitude jumps when switching noise type. The 4D gradient norm is √3,
# 3D is √2, so scale by **√(2/3)** -- a constant with a reason, not a fitted one.
# (Fitted value: matching the max to the 3D 0.9622 over 3 million samples needs 0.8676, 6% off from 0.8165,
# negligible; better to have one whose origin can be explained.)
_PERLIN4_SCALE = float(np.sqrt(2.0 / 3.0))


def value_noise4(xp, x, y, z, w, seed=0):
    """Random values at sixteen lattice points, quintic fade interpolation. Bit-identical to the 3D version at w=0."""
    fx, fy, fz, fw = xp.floor(x), xp.floor(y), xp.floor(z), xp.floor(w)
    ix, iy, iz, iw = (xp.to_i64(fx), xp.to_i64(fy), xp.to_i64(fz),
                      xp.to_i64(fw))
    u = [_fade(x - fx), _fade(y - fy), _fade(z - fz), _fade(w - fw)]
    n = None
    for c in itertools.product((0, 1), repeat=4):
        h = cell_hash(xp, ix + c[0], iy + c[1], iz + c[2], seed,
                      cw=iw + c[3])
        term = _corner_weight(xp, u, c) * _to01(xp, h)
        n = term if n is None else n + term
    return n * 2.0 - 1.0


def perlin4(xp, x, y, z, w, seed=0):
    """4D gradient noise. Sixteen corners, gradients from the 32 4D directions."""
    fx, fy, fz, fw = xp.floor(x), xp.floor(y), xp.floor(z), xp.floor(w)
    ix, iy, iz, iw = (xp.to_i64(fx), xp.to_i64(fy), xp.to_i64(fz),
                      xp.to_i64(fw))
    rx, ry, rz, rw = x - fx, y - fy, z - fz, w - fw
    u = [_fade(rx), _fade(ry), _fade(rz), _fade(rw)]
    tbl = xp.asarray(_GRAD4)
    n = None
    for c in itertools.product((0, 1), repeat=4):
        h = cell_hash(xp, ix + c[0], iy + c[1], iz + c[2], seed,
                      cw=iw + c[3])
        g = xp.gather_rows(tbl, xp.umod_i64(h, 32))
        dot = (g[..., 0] * (rx - c[0]) + g[..., 1] * (ry - c[1])
               + g[..., 2] * (rz - c[2]) + g[..., 3] * (rw - c[3]))
        term = _corner_weight(xp, u, c) * dot
        n = term if n is None else n + term
    return n * _PERLIN4_SCALE


def simplex4(xp, x, y, z, w, seed=0):
    """
    4D simplex noise. Five corners; corner order is computed by **ranking**, no lookup table.

    The 3D version writes the 6 orderings as 5 boolean conditions and selects. 4D has 24;
    hard-coding them takes 24 lines -- and it's very easy to miscopy one; the miscopied case leaves a regular
    artifact in the noise you won't notice unless you stare. The ranking method: compare every pair of coordinates (6 comparisons), the larger gets rank +1,
    and finally rank >= 3 / >= 2 / >= 1 give the offsets of the 1st / 2nd / 3rd corners. Equivalent, shorter,
    and no hand-copied table.
    """
    s = (x + y + z + w) * _F4
    fx, fy = xp.floor(x + s), xp.floor(y + s)
    fz, fw = xp.floor(z + s), xp.floor(w + s)
    ix, iy = xp.to_i64(fx), xp.to_i64(fy)
    iz, iw = xp.to_i64(fz), xp.to_i64(fw)
    t = (fx + fy + fz + fw) * _G4
    x0, y0 = x - (fx - t), y - (fy - t)
    z0, w0 = z - (fz - t), w - (fw - t)

    one = xp.full(x0.shape, 1.0)
    zero = xp.full(x0.shape, 0.0)

    def gt(a, b):
        return xp.where(a > b, one, zero)

    rx = gt(x0, y0) + gt(x0, z0) + gt(x0, w0)
    ry = (1.0 - gt(x0, y0)) + gt(y0, z0) + gt(y0, w0)
    rz = (1.0 - gt(x0, z0)) + (1.0 - gt(y0, z0)) + gt(z0, w0)
    rw = (1.0 - gt(x0, w0)) + (1.0 - gt(y0, w0)) + (1.0 - gt(z0, w0))

    def ge(r, k):
        return xp.where(r >= float(k), one, zero)

    offs = [[zero, zero, zero, zero],
            [ge(rx, 3), ge(ry, 3), ge(rz, 3), ge(rw, 3)],
            [ge(rx, 2), ge(ry, 2), ge(rz, 2), ge(rw, 2)],
            [ge(rx, 1), ge(ry, 1), ge(rz, 1), ge(rw, 1)],
            [one, one, one, one]]

    tbl = xp.asarray(_GRAD4)
    n = None
    for k, o in enumerate(offs):
        g4 = k * _G4 if k < 4 else 4 * _G4
        xi = [x0 - o[0] + g4, y0 - o[1] + g4,
              z0 - o[2] + g4, w0 - o[3] + g4]
        tt = 0.6 - (xi[0] * xi[0] + xi[1] * xi[1]
                    + xi[2] * xi[2] + xi[3] * xi[3])
        h = cell_hash(xp, ix + xp.to_i64(o[0]), iy + xp.to_i64(o[1]),
                      iz + xp.to_i64(o[2]), seed, cw=iw + xp.to_i64(o[3]))
        g = xp.gather_rows(tbl, xp.umod_i64(h, 32))
        dot = (g[..., 0] * xi[0] + g[..., 1] * xi[1]
               + g[..., 2] * xi[2] + g[..., 3] * xi[3])
        term = xp.where(tt > 0, (tt ** 4) * dot, zero)
        n = term if n is None else n + term
    return n * _SIMPLEX4_SCALE


def worley4(xp, x, y, z, w, seed=0, mode="f1", metric="euclidean",
            jitter=1.0):
    """
    4D cellular noise. **81 neighbouring cells** (3⁴), versus 27 in 3D -- 3x the cost, no way around it:
    that's how many diagonal neighbours there are in 4D; skipping a ring misses the true nearest point at some positions,
    showing up as streaks of misalignment along cell boundaries, visible only when animated.
    """
    ix, iy = xp.to_i64(xp.floor(x)), xp.to_i64(xp.floor(y))
    iz, iw = xp.to_i64(xp.floor(z)), xp.to_i64(xp.floor(w))
    big = 1e30
    b1 = xp.full(x.shape, big)
    b2 = xp.full(x.shape, big)
    for c in itertools.product(_rng(mode, metric), repeat=4):
        cx, cy, cz, cw = ix + c[0], iy + c[1], iz + c[2], iw + c[3]
        jt = float(jitter)
        px = _jit(xp, cx, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 1,
                                              cw=cw)), jt)
        py = _jit(xp, cy, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 2,
                                              cw=cw)), jt)
        pz = _jit(xp, cz, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 3,
                                              cw=cw)), jt)
        pw = _jit(xp, cw, _to01(xp, cell_hash(xp, cx, cy, cz, seed, 4,
                                              cw=cw)), jt)
        dx, dy, dz, dw = x - px, y - py, z - pz, w - pw
        d = _metric(xp, (dx, dy, dz, dw), metric)
        b2 = xp.minimum(b2, xp.maximum(b1, d))
        b1 = xp.minimum(b1, d)
    if mode == "f2f1":
        return xp.clip((b2 - b1) * 2.0 - 1.0, -1.0, 1.0)
    return xp.clip(1.0 - 2.0 * b1, -1.0, 1.0)


def white(xp, x, y, z, seed=0, w=None):
    """
    Houdini's White (Random): one constant random value per cell, no interpolation inside the cell, [-1, 1).
    salt is 11, distinct from the 0~4 used by value / worley -- with the same seed it won't produce the same sequence
    as value noise's lattice values. If w is given, one more dimension is mixed in (time / two-way tiling).
    """
    ix, iy, iz = xp.to_i64(xp.floor(x)), xp.to_i64(xp.floor(y)), \
        xp.to_i64(xp.floor(z))
    cw = None if w is None else xp.to_i64(xp.floor(w))
    return _to01(xp, cell_hash(xp, ix, iy, iz, seed, 11, cw=cw)) * 2.0 - 1.0


def base_noise(xp, x, y, z, kind="simplex", seed=0, w=None,
               metric="euclidean", jitter=1.0):
    if kind == "white":
        return white(xp, x, y, z, seed, w)
    if kind in ("worley", "worley_f2f1"):
        mode = "f1" if kind == "worley" else "f2f1"
        if w is not None:
            return worley4(xp, x, y, z, w, seed, mode, metric, jitter)
        return worley(xp, x, y, z, seed, mode, metric, jitter)
    if w is not None:
        if kind == "value":
            return value_noise4(xp, x, y, z, w, seed)
        if kind == "perlin":
            return perlin4(xp, x, y, z, w, seed)
        if kind == "simplex":
            return simplex4(xp, x, y, z, w, seed)
        raise ValueError(f"Noise Type must be one of {NOISE_TYPES_COP}")
    if kind == "value":
        return value_noise(xp, x, y, z, seed)
    if kind == "perlin":
        return perlin(xp, x, y, z, seed)
    if kind == "simplex":
        return simplex(xp, x, y, z, seed)
    raise ValueError(f"Noise Type must be one of {NOISE_TYPES_COP}")


def fractal_noise(xp, x, y, z, kind="simplex", fractal="none", octaves=3,
                  lacunarity=2.0, roughness=0.5, seed=0, offset=0.7,
                  w=None, metric="euclidean", jitter=1.0):
    """
    Multi-octave summation. The three summation modes are exactly the same as in attribnoise.

    If w is given it goes 4D. **The time axis must scale with frequency too** -- otherwise high octaves are fine in space
    but as slow in time as the low octaves, looking like "the details are frozen and only the large forms move",
    the most common flaw of animated noise.
    """
    if fractal == "none":
        return base_noise(xp, x, y, z, kind, seed, w, metric, jitter)
    if fractal not in FRACTALS:
        raise ValueError(f"Fractal must be one of {FRACTALS}")
    n = max(1, int(octaves))
    lac = float(lacunarity)
    # the octave weight is called wt, not w -- w is now the 4th dimension (time). With the same name the time axis would be
    # silently overwritten by a Python list, with the error raised ten lines away
    wt = [float(roughness) ** o for o in range(n)]
    wsum = max(sum(wt), 1e-9)

    if fractal == "standard":
        total = None
        px, py, pz, pw = x, y, z, w
        for o in range(n):
            v = wt[o] * base_noise(xp, px, py, pz, kind, seed + o * 101, pw,
                                       metric, jitter)
            total = v if total is None else total + v
            px, py, pz = px * lac, py * lac, pz * lac
            pw = None if pw is None else pw * lac
        return total / wsum

    if fractal == "terrain":
        v = xp.full(x.shape, 1.0)
        px, py, pz, pw = x, y, z, w
        for o in range(n):
            v = v * (float(offset)
                     + wt[o] * base_noise(xp, px, py, pz, kind,
                                          seed + o * 101, pw, metric, jitter))
            px, py, pz = px * lac, py * lac, pz * lac
            pw = None if pw is None else pw * lac
        base = float(offset) ** n
        return (v - base) / max(base, 1e-9)

    # hybrid_terrain (Musgrave): weight clamped to 1 so ridges don't multiply up without bound
    px, py, pz, pw = x, y, z, w
    result = (base_noise(xp, px, py, pz, kind, seed, pw, metric, jitter)
              + float(offset)) * wt[0]
    weight = result
    px, py, pz = px * lac, py * lac, pz * lac
    pw = None if pw is None else pw * lac
    for o in range(1, n):
        weight = xp.minimum(weight, xp.full(x.shape, 1.0))
        signal = (base_noise(xp, px, py, pz, kind, seed + o * 101, pw,
                              metric, jitter)
                  + float(offset)) * wt[o]
        result = result + weight * signal
        weight = weight * signal
        px, py, pz = px * lac, py * lac, pz * lac
        pw = None if pw is None else pw * lac
    return result / wsum - float(offset)
