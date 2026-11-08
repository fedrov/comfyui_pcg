"""
Attribute Noise SOP -- adds noise to attributes. Comes with a vectorized noise library.

This is where "mountains" come from: connect it to a Grid, turn on Noise Along Vector, push along N, and a flat grid mesh
becomes terrain. Also used to jitter Cd / pscale / any attribute.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Noise must be **a function of position**, not "generate N random numbers"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For the same world position the noise value must be the same no matter where the point came from, what its number is, or whether
something was deleted upstream. So the random values at cell corners always come from a **hash of integer cell coordinates** (splitmix64 bit mixing), with no state and no
pre-generated permutation table. That way two pieces of geometry sample the same value at their seam and join without a visible seam;
the np.random approach cannot do this.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Four noise types, 3D and 4D share one code path
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    value    random values on grid points, quintic fade interpolation. Cheapest, most visibly grid-like
    perlin   **gradients** on grid points, interpolating directions -- the blockiness of value noise is gone
    simplex  simplex grid, only 4 corners in 3D (perlin needs 8), no axis-aligned directionality
    worley   distance to the nearest feature point. Cells / cracks / stones, a completely different family from the other three

Sample points are (N, D) arrays with D = 3 or 4. **Animation is the fourth dimension**: the same noise is translated along the fourth axis
and the image flows continuously. Neither "change the seed over time" nor "translate along x" can do this --
the former is completely unrelated frame to frame, the latter makes the pattern slide sideways; only an extra dimension gives "evolving in place".

The value / perlin / worley implementations are naturally dimension-independent (2^D corners / 3^D neighbour cells); simplex's
3D and 4D use two different corner-order derivations and are written separately.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fractals: three ways of layering, differing in "where the detail is added"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    standard        fBm: octaves **added with equal weight**. Uniformly rough everywhere, like a sea surface
    terrain         multifractal: octaves **multiplied**. Higher areas more rugged, lower areas flatter
    hybrid_terrain  hybrid multifractal: multiplied + weights clamped to 1. Sharp ridges, flat valley floors

The latter two are the original formulas of Musgrave's terrain fractals. Multiplying means "this layer's amplitude is set by the previous layer's
height" -- which is exactly how real erosion works: exposed high ground weathers more, valley floors fill flat with sediment.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The steps one noise evaluation goes through; the order matters
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    sample position = (position attribute + Offset + VEXpression) / Element Size
    Warping     **pushes the sample positions askew** with another noise (domain warping), before evaluation
    fractal     produces the raw value in [-1, 1]
    Bias/Gain   squashes/stretches in 0..1 space, changes the **distribution**
    Remap Ramp  also in 0..1 space, changes the **shape** (can make plateaus, cliffs)
    Abs/Invert  absolute value gives ridge lines, invert turns valleys into ridges
    Range/amp   maps to the final value range
    Normalize   stretches the results of the selected elements exactly to the given range
    Clamp / Operation / Blend

Bias/Gain and Remap Ramp both work in 0..1 space so that their parameters are independent of the amplitude: tune the shape,
then the amplitude, and the shape doesn't change. Done in the final value range, every change of Amplitude would require retuning the curve.
"""
from __future__ import annotations

import itertools

import numpy as np

from .npcompat import select as _select  # np.select breaks if a node pack rebinds np.bool

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve
from .ops import match_names, prim_centers
from . import ramp as _ramp

NOISE_TYPES = ("value", "perlin", "simplex", "worley", "worley_f2f1")
# pcg100 s6: Houdini's Manhattan / Chebyshev Cellular. Only used by the new Attribute Adjust
# family and the extended menu of Attribute Noise; NOISE_TYPES itself is unchanged -- Fracture Detail and
# the old Attribute Adjust menus reference it directly, and changing it would break their panel specs
NOISE_TYPES_X = NOISE_TYPES + ("manhattan", "manhattan_f2f1",
                               "chebyshev", "chebyshev_f2f1")
FRACTALS = ("none", "standard", "terrain", "hybrid_terrain")
# pcg100 s6: the later items are Houdini's Set Initial / Minimum / Maximum and the remaining Range Values options
OPERATIONS = ("add", "subtract", "multiply", "set", "set_initial", "minimum", "maximum")
RANGES = ("zero_centered", "zero_to_one", "one_centered",
          "negative", "min_max", "min_range", "middle_range")
ATTRIB_TYPES = ("auto", "float", "vector")
CLASSES = (POINT, VERTEX, PRIM, DETAIL)
RAMP_MODES = _ramp.MODES

_U64 = np.uint64
_MULT = (0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F)


# ═══════════════════════════════════════════════════════════════ hashing
def _mix(x):
    """splitmix64 bit mixing. Overflow is part of the algorithm, not an error."""
    with np.errstate(over="ignore"):
        x = np.asarray(x, _U64).copy()
        x ^= x >> _U64(33)
        x *= _U64(0xFF51AFD7ED558CCD)
        x ^= x >> _U64(33)
        x *= _U64(0xC4CEB9FE1A85EC53)
        x ^= x >> _U64(33)
    return x


def _cell_hash(c, seed=0, salt=0):
    """(N,D) integer cell coordinates -> (N,) uint64. D at most 4."""
    c = np.asarray(c)
    with np.errstate(over="ignore"):
        k = (np.int64(int(seed) * 0x165667B1 + int(salt) * 0x27D4EB2F)
             + np.zeros(len(c), np.int64))
        for d in range(c.shape[1]):
            k = k + c[:, d].astype(np.int64) * np.int64(_MULT[d])
    return _mix(k.astype(_U64))


def _to01(h):
    return (h >> _U64(11)).astype(np.float64) / float(1 << 53)


_GRAD3 = np.array([[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
                   [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                   [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1]], np.float64)

# The 32 gradients of 4D: each component in turn is 0, the other three are +/-1
def _make_grad4():
    out = []
    for z in range(4):
        for s in itertools.product((1.0, -1.0), repeat=3):
            g = [0.0, 0.0, 0.0, 0.0]
            j = 0
            for k in range(4):
                if k == z:
                    continue
                g[k] = s[j]
                j += 1
            out.append(g)
    return np.array(out, np.float64)


_GRAD4 = _make_grad4()
_GRADS = {3: _GRAD3, 4: _GRAD4}


def _grads(h, D):
    tbl = _GRADS[D]
    return tbl[(h % _U64(len(tbl))).astype(np.int64)]


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _dim(P):
    P = np.asarray(P, np.float64)
    if P.ndim != 2 or P.shape[1] not in (3, 4):
        raise ValueError("Noise sample points must be an (N,3) or (N,4) array.")
    return P


# ═══════════════════════════════════════════════════════════════ noise
def value_noise(P, seed=0):
    """Random values on 2^D grid points, quintic fade interpolation. Dimension-independent."""
    P = _dim(P)
    D = P.shape[1]
    i = np.floor(P).astype(np.int64)
    f = P - i
    u = _fade(f)
    n = np.zeros(len(P))
    for corner in itertools.product((0, 1), repeat=D):
        d = np.array(corner, np.int64)
        v = _to01(_cell_hash(i + d, seed))
        w = np.ones(len(P))
        for k in range(D):
            w = w * (u[:, k] if corner[k] else 1.0 - u[:, k])
        n += w * v
    return n * 2.0 - 1.0


def perlin(P, seed=0):
    """Classic gradient noise. Grid points hold directions; what is interpolated is "where this direction points". Dimension-independent."""
    P = _dim(P)
    D = P.shape[1]
    i = np.floor(P).astype(np.int64)
    f = P - i
    u = _fade(f)
    n = np.zeros(len(P))
    for corner in itertools.product((0, 1), repeat=D):
        d = np.array(corner, np.float64)
        g = _grads(_cell_hash(i + d.astype(np.int64), seed), D)
        r = f - d
        w = np.ones(len(P))
        for k in range(D):
            w = w * (u[:, k] if corner[k] else 1.0 - u[:, k])
        n += w * np.einsum("ij,ij->i", g, r)
    # Normalization constants were measured: raw peak 0.98 in 3D, 1.12 in 4D; after scaling both hug +/-1
    return n if D == 3 else n * 0.89


_F3, _G3 = 1.0 / 3.0, 1.0 / 6.0
_F4 = (np.sqrt(5.0) - 1.0) / 4.0
_G4 = (5.0 - np.sqrt(5.0)) / 20.0


def _simplex3(P, seed):
    s = P.sum(1) * _F3
    i = np.floor(P + s[:, None]).astype(np.int64)
    t = i.sum(1) * _G3
    x0 = P - (i.astype(np.float64) - t[:, None])
    x, y, z = x0[:, 0], x0[:, 1], x0[:, 2]
    # Which of the six simplices it falls in: decided by the ordering of x/y/z
    conds = [(x >= y) & (y >= z),
             (x >= y) & (y < z) & (x >= z),
             (x >= y) & (x < z),
             (x < y) & (y < z),
             (x < y) & (y >= z) & (x < z)]

    def pick(vals, default):
        return _select(conds, vals, default=default).astype(np.float64)

    o1 = np.stack([pick([1, 1, 0, 0, 0], 0), pick([0, 0, 0, 0, 1], 1),
                   pick([0, 0, 1, 1, 0], 0)], 1)
    o2 = np.stack([pick([1, 1, 1, 0, 0], 1), pick([1, 0, 0, 1, 1], 1),
                   pick([0, 1, 1, 1, 1], 0)], 1)
    corners = [(np.zeros((len(P), 3)), x0),
               (o1, x0 - o1 + _G3),
               (o2, x0 - o2 + 2.0 * _G3),
               (np.ones((len(P), 3)), x0 - 1.0 + 3.0 * _G3)]
    return _simplex_sum(i, corners, seed, 3) * 32.0


def _simplex4(P, seed):
    """
    4D simplex noise. The corner order is no longer an enumeration of cases (4D has 24); instead the four coordinates
    are **ranked**: rank >= 3 is added first, >= 2 next, >= 1 after that. The same rule
    holds in 3D too; enumerating the six cases is just more straightforward there.
    """
    s = P.sum(1) * _F4
    i = np.floor(P + s[:, None]).astype(np.int64)
    t = i.sum(1) * _G4
    x0 = P - (i.astype(np.float64) - t[:, None])
    # Ranks must be counted **pairwise**: in each pair exactly one scores. Writing it as "count how many are smaller than me"
    # produces duplicate ranks on ties (e.g. 0,1,1,3) and the corner order breaks -- and ties are not rare at all in real
    # data: after shearing a y=0 Grid several coordinates happen to be equal.
    rank = np.zeros((len(P), 4))
    for a in range(4):
        for b in range(a + 1, 4):
            gt = x0[:, a] > x0[:, b]
            rank[:, a] += gt
            rank[:, b] += ~gt
    o1 = (rank >= 3).astype(np.float64)
    o2 = (rank >= 2).astype(np.float64)
    o3 = (rank >= 1).astype(np.float64)
    corners = [(np.zeros((len(P), 4)), x0),
               (o1, x0 - o1 + _G4),
               (o2, x0 - o2 + 2.0 * _G4),
               (o3, x0 - o3 + 3.0 * _G4),
               (np.ones((len(P), 4)), x0 - 1.0 + 4.0 * _G4)]
    return _simplex_sum(i, corners, seed, 4) * 27.0


def _simplex_sum(i, corners, seed, D):
    n = np.zeros(len(i))
    for off, xi in corners:
        tt = 0.6 - np.einsum("ij,ij->i", xi, xi)
        ok = tt > 0
        if not ok.any():
            continue
        g = _grads(_cell_hash(i + off.astype(np.int64), seed), D)
        n += np.where(ok, (tt ** 4) * np.einsum("ij,ij->i", g, xi), 0.0)
    return n


def simplex(P, seed=0):
    P = _dim(P)
    return _simplex3(P, seed) if P.shape[1] == 3 else _simplex4(P, seed)


def worley(P, seed=0, mode="f1", metric="euclidean"):
    """
    Cellular noise: distance to the nearest feature point. One random feature point per cell, 3^D neighbour cells searched.

    f1 is mapped inverted to [-1,1] (larger values close by), so as with the other noises "larger value = bump";
    f2f1 = F2 - F1 is the classic crack pattern.

    4D searches 81 neighbour cells (27 in 3D), so with animation on this option is noticeably slower; be aware.

    metric: euclidean (default, original behaviour) / manhattan (sum|d|, diamond cells) / chebyshev
    (max|d|, square cells). The three distances have different magnitudes; each is multiplied by a factor to bring the typical F1 back to
    the Euclidean magnitude (measured mean F1 in 3D: Euclidean ~ 0.52, Manhattan ~ 0.74, Chebyshev ~ 0.42, after clamping).
    """
    P = _dim(P)
    D = P.shape[1]
    i = np.floor(P).astype(np.int64)
    b1 = np.full(len(P), np.inf)
    b2 = np.full(len(P), np.inf)
    scale = np.sqrt(3.0 / D)                 # the higher the dimension, the farther the nearest point; compensate
    for corner in itertools.product((-1, 0, 1), repeat=D):
        c = i + np.array(corner, np.int64)
        fp = c.astype(np.float64) + np.stack(
            [_to01(_cell_hash(c, seed, k)) for k in range(1, D + 1)], 1)
        dv = P - fp
        if metric == "manhattan":
            d = np.abs(dv).sum(1) * _METRIC_K["manhattan"]
        elif metric == "chebyshev":
            d = np.abs(dv).max(1) * _METRIC_K["chebyshev"]
        else:
            d = np.linalg.norm(dv, axis=1)
        b2 = np.minimum(b2, np.maximum(b1, d))
        b1 = np.minimum(b1, d)
    if mode == "f2f1":
        return np.clip((b2 - b1) * 2.0 * scale - 1.0, -1.0, 1.0)
    return np.clip(1.0 - 2.0 * b1 * scale, -1.0, 1.0)


_METRIC_K = {"manhattan": 0.70, "chebyshev": 1.24}


def noise(P, kind="simplex", seed=0):
    if kind == "value":
        return value_noise(P, seed)
    if kind == "perlin":
        return perlin(P, seed)
    if kind == "simplex":
        return simplex(P, seed)
    if kind == "worley":
        return worley(P, seed, "f1")
    if kind == "worley_f2f1":
        return worley(P, seed, "f2f1")
    if kind in NOISE_TYPES_X:
        metric, _, f = kind.partition("_")
        return worley(P, seed, f or "f1", metric)
    raise ValueError(f"Noise Type must be one of {NOISE_TYPES}")


# ═══════════════════════════════════════════════════════════════ fractals
def fractal_noise(P, kind="simplex", fractal="none", octaves=3,
                  lacunarity=2.0, roughness=0.5, seed=0, offset=0.7):
    """Multi-octave layering. See the module docstring for how the three modes differ."""
    if fractal == "none":
        return noise(P, kind, seed)
    oct_n = max(1, int(octaves))
    lac = float(lacunarity)
    w = float(roughness) ** np.arange(oct_n)

    if fractal == "standard":
        total = np.zeros(len(P))
        p = P
        for o in range(oct_n):
            total += w[o] * noise(p, kind, seed + o * 101)
            p = p * lac
        return total / max(float(w.sum()), 1e-9)

    if fractal == "terrain":
        # Multifractal: octaves multiplied. High areas get more and more rugged, low areas get flattened
        v = np.ones(len(P))
        p = P
        for o in range(oct_n):
            v = v * (float(offset) + w[o] * noise(p, kind, seed + o * 101))
            p = p * lac
        base = float(offset) ** oct_n
        return (v - base) / max(base, 1e-9)

    if fractal == "hybrid_terrain":
        # Hybrid multifractal (Musgrave): weights clamped to 1 so ridges don't blow up multiplying all the way
        p = P
        result = (noise(p, kind, seed) + float(offset)) * w[0]
        weight = result.copy()
        p = p * lac
        for o in range(1, oct_n):
            weight = np.minimum(weight, 1.0)
            signal = (noise(p, kind, seed + o * 101) + float(offset)) * w[o]
            result = result + weight * signal
            weight = weight * signal
            p = p * lac
        return result / max(float(w.sum()), 1e-9) - float(offset)

    raise ValueError(f"Fractal must be one of {FRACTALS}")


def warp_field(S, kind="simplex", octaves=1, seed=0):
    """
    Displacement field for domain warping: one independent noise per dimension, values in [-1,1].

    Noise is added to the **position**, not to the result -- the latter only blurs the pattern, the former makes the
    texture stretch, curl and fold, a "kneaded" look; one layer is enough, which is also why it is cheap.
    Each dimension must use a different salt, otherwise all axes are displaced equally, which is just a translation and warps nothing.
    """
    D = S.shape[1]
    return np.stack([fractal_noise(S, kind, "standard", max(1, int(octaves)),
                                   2.0, 0.5, int(seed) + 9173 * (k + 1))
                     for k in range(D)], 1)


# ═══════════════════════════════════════════════════════════ value correction
def _bias(t, b):
    b = float(np.clip(b, 1e-4, 1 - 1e-4))
    return np.power(np.clip(t, 0.0, 1.0), np.log(b) / np.log(0.5))


def _gain(t, g):
    t = np.clip(t, 0.0, 1.0)
    return np.where(t < 0.5, 0.5 * _bias(2.0 * t, 1.0 - g),
                    1.0 - 0.5 * _bias(2.0 - 2.0 * t, 1.0 - g))


# ═══════════════════════════════════════════════════════════════ SOP
def _sample_positions(geo, cls, location_attrib):
    """One sample position per element."""
    nm = str(location_attrib).strip() or "P"
    a = geo.get(cls, nm)
    if a is not None and a.shape[1] == 3:
        return a.astype(np.float64)
    P = geo.get(POINT, nm)
    if P is None or P.shape[1] != 3:
        have = sorted(geo.attribs[POINT].keys())
        raise KeyError(f"No 3-D position attribute '{nm}' found. Existing on point: {have}")
    P = P.astype(np.float64)
    if cls == POINT:
        return P
    if cls == VERTEX:
        return P[geo.vertex_point]
    if cls == PRIM:
        return prim_centers(geo).astype(np.float64)
    return P.mean(0, keepdims=True) if len(P) else np.zeros((1, 3))


def _vex_offset(geo, cls, expr, n):
    """VEXpression: evaluates a vector per element and adds it to Offset."""
    from .wrangle import eval_value
    try:
        # broadcast=False: scalars are **not** broadcast to (v, v, v). What is wanted here is a sample position;
        # broadcasting would sample along the diagonal and silently degrade to 1-D noise, better to raise a clear error
        v = eval_value(geo, expr, cls, 3, broadcast=False)
    except ValueError:
        raise
    except Exception as ex:
        raise RuntimeError(
            f"VEXpression evaluation failed: {type(ex).__name__}: {ex}\n"
            f"  expression: {expr}\n"
            f"  it must return a vector, e.g. set(0, @P.y * 0.1, 0)") from ex
    return v


def attribute_noise(geo, group="", attrib_class=POINT, attrib_names="P",
                    use_x=True, use_y=True, use_z=True,
                    noise_along_vector=False, vector_attrib="N",
                    operation="add", range_values="zero_centered",
                    amplitude=0.25,
                    noise_type="simplex", location_attrib="P",
                    element_size=(1.0, 1.0, 1.0),
                    noise_offset=(0.0, 0.0, 0.0), vexpression="",
                    use_animation=False, noise_time=0.0,
                    time_element_size=1.0,
                    fractal="none", octaves=3, lacunarity=2.0,
                    roughness=0.5, fractal_offset=0.7,
                    warp=0.0, warp_element_size=1.0, warp_octaves=1,
                    rand_seed=0, blend=1.0,
                    use_value_correction=False, bias=0.5, gain=0.5,
                    use_remap_ramp=False, remap_ramp="0:0 1:1",
                    ramp_mode="linear",
                    post_absolute=False, post_invert=False,
                    use_normalize=False, normalize_min=0.0, normalize_max=1.0,
                    use_clamp_min=False, clamp_min=0.0,
                    use_clamp_max=False, clamp_max=1.0,
                    blend_attrib="", min_value=0.0, max_value=1.0,
                    middle_value=0.0, range_length=1.0, gamma=1.0, contrast=1.0,
                    attrib_type="auto", unit_length=False, recompute_normals=False):
    """
    Adds noise to attributes. See the module docstring for the order of the steps.

    Element Size is the **wavelength**: larger values give larger patterns (sample positions are divided by it). Per-axis values can create
    stretched strata. With noise_along_vector on, only one scalar noise is computed and pushed along vector_attrib
    (default N) -- that is the "mountain".

    pcg100 s6 additions (defaults = old behaviour):
      Operation   set_initial (leave the attribute alone if it already exists) / minimum / maximum
      Range       negative(−Amp..0)/ min_max / min_range(Min..Min+Length)/
                  middle_range (Middle +/- Length -- full width; the docs explicitly note this differs from
                  Attribute Adjust's half width)
      Gamma / Contrast   in 0..1 space, after Bias/Gain: t^(1/Gamma),
                  (t - 0.5)*Contrast + 0.5; skipped when equal to 1 (bits unchanged)
      blend_attrib  when non-empty, used per element as Blend (clamped 0..1); the constant blend no longer applies
      attrib_type   auto (old behaviour: guess component count from the existing attribute / name) / float (one scalar
                  noise spread across all components) / vector (new attribute gets 3 components, each independent)
      unit_length   normalizes 3-component results; recompute_normals recomputes N afterwards if it exists
    """
    if geo is None:
        return Geometry()
    if attrib_class not in CLASSES:
        raise ValueError(f"Attribute Class must be one of {CLASSES}")
    if operation not in OPERATIONS:
        raise ValueError(f"Operation must be one of {OPERATIONS}")
    if range_values not in RANGES:
        raise ValueError(f"Range Values must be one of {RANGES}")
    if noise_type not in NOISE_TYPES_X:
        raise ValueError(f"Noise Type must be one of {NOISE_TYPES_X}")
    if attrib_type not in ATTRIB_TYPES:
        raise ValueError(f"Attribute Type must be one of {ATTRIB_TYPES}")
    if fractal not in FRACTALS:
        raise ValueError(f"Fractal must be one of {FRACTALS}")

    names = match_names(list(geo.attribs[attrib_class].keys()), attrib_names)
    literal = [t for t in str(attrib_names or "").split()
               if t and not t.startswith("^") and not any(c in t for c in "*?")]
    for t in literal:                            # missing attributes are created
        if t not in names:
            names.append(t)
    if not names:
        have = sorted(geo.attribs[attrib_class].keys())
        raise KeyError(f"{attrib_class} has no attribute matching '{attrib_names}'. "
                       f"Existing: {have or '(none)'}")

    n = geo.count(attrib_class)
    if n == 0:
        return geo.copy()
    Q = _sample_positions(geo, attrib_class, location_attrib)
    off = np.asarray(noise_offset, np.float64).reshape(1, 3)
    if str(vexpression).strip():
        off = off + _vex_offset(geo, attrib_class, vexpression, n)
    es = np.asarray(element_size, np.float64).reshape(1, 3)
    es = np.where(np.abs(es) < 1e-9, 1e-9, es)
    W = Q + off                                  # sample positions in world space
    div = es
    if use_animation:
        # Animation = the fourth dimension. Translating along it makes the whole noise evolve in place instead of sliding sideways
        W = np.concatenate([W, np.full((len(W), 1), float(noise_time))], 1)
        div = np.concatenate(
            [es, [[max(abs(float(time_element_size)), 1e-9)]]], 1)
    S = W / div
    if abs(float(warp)) > 1e-12:
        # warp is a **distance in world units**, so the displacement is taken at world scale first and then divided by the wavelength together --
        # that way changing Element Size doesn't also change the warp strength
        ws = max(abs(float(warp_element_size)), 1e-9)
        S = S + float(warp) * warp_field(W / ws, noise_type, warp_octaves,
                                         int(rand_seed) + 5471) / div

    ramp_stops = None
    if use_remap_ramp:
        ramp_stops = _ramp.parse(remap_ramp, 1)
        if ramp_mode not in RAMP_MODES:
            raise ValueError(f"Ramp interpolation must be one of {RAMP_MODES}")

    def raw(salt):
        v = fractal_noise(S, noise_type, fractal, octaves, lacunarity,
                          roughness, int(rand_seed) + salt, fractal_offset)
        if use_value_correction:                 # done in 0..1 space, then mapped back
            v = _gain(_bias(0.5 * (v + 1.0), bias), gain) * 2.0 - 1.0
        if float(gamma) != 1.0 or float(contrast) != 1.0:
            t = np.clip(0.5 * (v + 1.0), 0.0, 1.0)
            t = t ** (1.0 / max(float(gamma), 1e-6))
            t = (t - 0.5) * float(contrast) + 0.5
            v = t * 2.0 - 1.0
        if ramp_stops is not None:               # likewise in 0..1 space
            v = _ramp.apply(0.5 * (v + 1.0), ramp_stops[0], ramp_stops[1],
                            ramp_mode)[:, 0] * 2.0 - 1.0
        if post_absolute:                        # ridge lines: sharp where it folds over
            v = np.abs(v) * 2.0 - 1.0
        if post_invert:
            v = -v
        # In One Centered, amplitude scales the **deviation from 1**, not the whole value --
        # it is meant for multiply: small fluctuations around 1 are what "multiply by a bit of noise" means
        if range_values == "zero_to_one":
            v = 0.5 * (v + 1.0) * float(amplitude)
        elif range_values == "negative":
            v = -0.5 * (v + 1.0) * float(amplitude)
        elif range_values in ("min_max", "min_range", "middle_range"):
            lo, hi = (
                (float(min_value), float(max_value)) if range_values == "min_max" else
                (float(min_value), float(min_value) + float(range_length))
                if range_values == "min_range" else
                (float(middle_value) - float(range_length),
                 float(middle_value) + float(range_length)))
            v = lo + 0.5 * (v + 1.0) * (hi - lo)
        elif range_values == "one_centered":
            v = 1.0 + v * float(amplitude)
        else:
            v = v * float(amplitude)
        return v

    sel = resolve(geo, attrib_class, group)

    def fit(v):
        """Normalize: stretches the values of the **selected elements** exactly to the given range."""
        if not use_normalize:
            return v
        s = v[sel] if sel.any() else v
        lo, hi = float(np.min(s)), float(np.max(s))
        a, b = float(normalize_min), float(normalize_max)
        if hi - lo < 1e-12:
            return np.full_like(v, 0.5 * (a + b))
        return a + (v - lo) / (hi - lo) * (b - a)

    mask = np.array([bool(use_x), bool(use_y), bool(use_z)])
    g = geo.copy()

    vec = None
    if noise_along_vector:
        nm = str(vector_attrib).strip() or "N"
        a = geo.get(attrib_class, nm)
        if a is None and attrib_class != POINT:
            a = geo.get(POINT, nm)
            if a is not None and attrib_class == VERTEX:
                a = a[geo.vertex_point]
        if a is None or a.shape[1] != 3:
            have = sorted(geo.attribs[attrib_class].keys())
            raise KeyError(
                f"Noise Along Vector is on, but {attrib_class} has no 3-D "
                f"'{nm}' attribute. Existing: {have or '(none)'} -- connect a Normal (PCG) first.")
        v = a.astype(np.float64)
        ln = np.linalg.norm(v, axis=1, keepdims=True)
        vec = v / np.where(ln < 1e-12, 1.0, ln)
        scalar = fit(raw(0))

    for nm in names:
        cur = geo.get(attrib_class, nm)
        if cur is not None:
            C = cur.shape[1]
            base = cur.astype(np.float64)
        else:                                    # new attribute: 3-D if the name looks like a vector
            C = 3 if (vec is not None or attrib_type == "vector" or
                      (attrib_type == "auto" and
                       nm in ("P", "N", "Cd", "v", "up", "scale"))) else 1
            base = np.zeros((n, C))
        if vec is not None and C == 3:
            delta = vec * scalar[:, None]
        elif vec is not None:
            delta = scalar[:, None] * np.ones((1, C))
        elif attrib_type == "float":
            # Float: one 1-D noise spread across all components (Houdini's Attribute Type = Float)
            delta = np.repeat(fit(raw(0))[:, None], C, axis=1)
        else:
            delta = np.stack([fit(raw(k * 7919)) for k in range(C)], 1)
        if C == 3:
            delta = delta * mask[None, :].astype(np.float64)

        if operation == "add":
            out = base + delta
        elif operation == "subtract":
            out = base - delta
        elif operation == "multiply":
            out = base * delta
        elif operation in ("minimum", "maximum"):
            out = (delta.copy() if cur is None else
                   (np.minimum if operation == "minimum" else np.maximum)(base, delta))
            if C == 3:
                out = np.where(mask[None, :], out, base)
        elif operation == "set_initial" and cur is not None:
            out = base.copy()                   # the attribute already exists: Set Initial leaves it alone
        else:
            out = delta.copy()
            if C == 3:                          # set + disabled components = keep original value
                out = np.where(mask[None, :], out, base)
        if use_clamp_min:
            out = np.maximum(out, float(clamp_min))
        if use_clamp_max:
            out = np.minimum(out, float(clamp_max))
        if unit_length and C == 3:
            ln = np.linalg.norm(out, axis=1, keepdims=True)
            out = out / np.where(ln < 1e-12, 1.0, ln)
        if str(blend_attrib or "").strip():
            ba = geo.get(attrib_class, str(blend_attrib).strip())
            if ba is None:
                have = sorted(geo.attribs[attrib_class].keys())
                raise KeyError(f"Blend Attribute '{blend_attrib}' does not exist on {attrib_class}. "
                               f"Existing: {have or '(none)'}")
            out = base + (out - base) * np.clip(ba[:, :1].astype(np.float64), 0.0, 1.0)
        else:
            b = float(np.clip(blend, 0.0, 1.0))
            if b < 1.0:
                out = base + (out - base) * b
        out = np.where(sel[:, None], out, base)
        dt = cur.dtype if cur is not None else np.dtype(np.float32)
        g.set(attrib_class, nm,
              (np.rint(out) if dt.kind in "iub" else out).astype(dt),
              owned=True)
    if recompute_normals:
        from .ops import compute_normals
        for c in (POINT, VERTEX, PRIM, DETAIL):
            if g.get(c, "N") is not None and g.nprims:
                g = compute_normals(g, c)
                break
    return g
