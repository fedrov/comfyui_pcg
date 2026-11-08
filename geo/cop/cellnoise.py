"""
Worley Noise / Cellular Noise (Copernicus, including the 3D versions) -- pcg100 c3_noise.

COP Noise's worley mode only outputs a scalar "1 − 2·F1", while in Houdini these two are **separate nodes**
with their own set of outputs:

    Worley Noise    dist1 / dist2 / border / center / id
    Cellular Noise  noise (shaped by border via Gap / Bevel) / border / center / id

So it's a separate module, rather than being stuffed into noise.py's path that is bit-aligned with the geometry side.

━━ Coordinates (different from Houdini, stated explicitly)
"Image coordinates" here are: x = u (image width = 1), y = v·H/W (aspect preserved). The docs don't pin down Houdini's canonical
image coordinate range; we normalize by image width, consistent with COP Noise Extra. Element Size /
Offset / Tile Size / the center output are all in this unit. If a pos layer is connected its values are used as coordinates: 2 channels =
2D, 3 channels = 3D (that's how world coordinates are fed into Worley Noise 3D / Cellular Noise 3D).

━━ Algorithm
First divide by Element Size (× Element Scale) to get into "cell space", one feature point per cell:

    rectangular / grid      feature point = cell + 0.5 + (h − 0.5)·jitter       h ∈ [0,1)³ hash
    hexagonal (2D only)     the same expression in skewed coordinates, then multiplied by the triangular lattice basis
                            a = (1, 0), b = (½, √3/2). With jitter = 0 it's a regular triangular lattice,
                            whose Voronoi cells are exactly regular hexagons -- the docs' "simplicial grid"

Search range: 5×5 neighbouring cells in 2D, 5×5×5 in 3D (all candidates fetched at once, vectorized). border needs
**all** Voronoi neighbours of the nearest point; for jitter ≤ 1 this range was measured to be enough (see the SEARCH comment),
for jitter > 1 it's not guaranteed -- Houdini likewise warns of artifacts.

border (Euclidean): the **exact** distance to the perpendicular bisector planes of the nearest two feature points = min_j ((r₁+r_j)/2 · n̂_j),
where r is the vector from the pixel to a feature point, n̂_j = (r_j − r₁)/|r_j − r₁| (Íñigo Quílez's two-pass method, done here
in one pass). With Round Border / Smooth Edge > 0 the min is replaced by a polynomial smooth-min (k = that value,
in cell units) -- the docs only say "larger = rounder edges"; the formula is our own.
Under Manhattan / Chebyshev the bisector "plane" isn't flat and has no simple exact formula: border is estimated as (d2 − d1)/2
(0 where equidistant from both points). The Houdini docs say border is exact; here it is **not** under those two metrics.

Distance units: cell-space distance × Element Size (scalar). With Element Scale all 1 that's the real distance in image
coordinates; when anisotropic it's the "pre-stretch" distance -- consistent with the anisotropy of "scale coordinates then compute noise".

id: hash of the nearest feature point's cell, low 32 bits taken as a **signed** integer (docs: may be negative).

━━ Tiling
With Tile on, the cell count per axis is n = round(Tile Size / Element Size) (at least 1), and Element Size
is changed to Tile Size / n -- the docs' "Element Size is rounded to keep it tileable". Cell coordinates are taken modulo n
before hashing, so the period is exactly Tile Size. The hexagonal lattice is incompatible with tiling (a triangular lattice doesn't close in a rectangle);
enabling both raises an error.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

from . import backend as bk
from .noise import cell_hash, _to01, METRICS

LATTICES = ("rectangular", "hexagonal")
SHAPE_MODES = ("absolute", "relative")

# Search radius (cells): 5×5 in 2D, 5×5×5 in 3D. Measured (jitter = 1, 200k points in 2D, 30k in 3D)
# bit-identical to ±4 / ±5; with ±1, F2 / border are wrong (47 of 200k points in 2D).
# Tests compare it enlarged / shrunk
SEARCH = {2: 2, 3: 2}

_HEX = np.array([[1.0, 0.5], [0.0, math.sqrt(3.0) / 2.0]])   # columns are the lattice basis a, b
_HEX_INV = np.linalg.inv(_HEX)


def _hash_cells(C, seed, salt):
    """(..., D) integer cell coordinates -> int64 hash (third dimension 0 when D = 2)."""
    xp = bk.NUMPY
    cz = C[..., 2] if C.shape[-1] > 2 else np.zeros(C.shape[:-1], np.int64)
    return cell_hash(xp, C[..., 0], C[..., 1], cz, int(seed), salt)


def _dist(r, metric):
    if metric == "euclidean":
        return np.sqrt((r * r).sum(-1))
    if metric == "manhattan":
        return np.abs(r).sum(-1)
    if metric == "chebyshev":
        return np.abs(r).max(-1)
    raise ValueError(f"Metric must be one of {METRICS}")


def _smin(d, k):
    """Polynomial smooth-min along the last dimension (plain min when k ≤ 0)."""
    if k <= 0:
        return d.min(-1)
    order = np.sort(d, -1)
    res = order[..., 0]
    for j in range(1, order.shape[-1]):
        b = order[..., j]
        h = np.clip(0.5 + 0.5 * (b - res) / k, 0.0, 1.0)
        res = b * (1 - h) + res * h - k * h * (1 - h)
    return res


def cell_fields(P, size=0.1, scale=(1.0, 1.0, 1.0), jitter=1.0,
                jitter_scale=(1.0, 1.0, 1.0), metric="euclidean",
                lattice="rectangular", seed=0, offset=(0.0, 0.0, 0.0),
                tile=None, round_border=0.0, chunk=None):
    """
    P: (N, D) image / world coordinates, D = 2 or 3. Returns a dict:
      d1, d2, border (N,)  -- units see the file header
      center (N, D)        -- coordinates of the nearest feature point (same space as P)
      id (N,)              -- signed 32-bit integer as float
    tile: None, or (D,) Tile Size (rectangular only).
    """
    P = np.asarray(P, np.float64)
    N, D = P.shape
    if D not in (2, 3):
        raise ValueError("position needs 2 or 3 components")
    if metric not in METRICS:
        raise ValueError(f"Metric must be one of {METRICS}")
    if lattice not in LATTICES:
        raise ValueError(f"Lattice must be one of {LATTICES}")
    hexa = lattice == "hexagonal"
    if hexa and D != 2:
        raise ValueError("the Hexagonal lattice is 2D only (3D would need a tetrahedral lattice, not implemented)")
    if hexa and tile is not None:
        raise ValueError("the Hexagonal lattice cannot tile: a triangular lattice doesn't close in a rectangular period")
    es = float(size)
    if es <= 0:
        raise ValueError("Element Size must be > 0")
    cs = es * np.asarray(scale, np.float64).reshape(-1)[:D]       # cell width per axis
    period = None
    if tile is not None:
        ts = np.asarray(tile, np.float64).reshape(-1)[:D]
        period = np.maximum(1, np.round(ts / cs)).astype(np.int64)
        cs = ts / period
    jit = float(jitter) * np.asarray(jitter_scale, np.float64).reshape(-1)[:D]
    off = np.asarray(offset, np.float64).reshape(-1)[:D]
    R = SEARCH[D]
    offs = np.array(list(itertools.product(range(-R, R + 1), repeat=D)),
                    np.int64)                                    # (K, D)
    K = len(offs)
    chunk = chunk or max(1, (1 << 22) // (K * D))
    out = {"d1": np.empty(N), "d2": np.empty(N), "border": np.empty(N),
           "center": np.empty((N, D)), "id": np.empty(N)}
    for s0 in range(0, N, chunk):
        Q = (P[s0:s0 + chunk] - off) / cs                        # cell space
        S = Q @ _HEX_INV.T if hexa else Q                        # skewed coordinates
        base = np.floor(S).astype(np.int64)
        C = base[:, None, :] + offs[None]                        # (n, K, D)
        Ch = C % period if period is not None else C
        h = np.stack([_to01(bk.NUMPY, _hash_cells(Ch, seed, 1 + a))
                      for a in range(D)], -1)
        F = C + 0.5 + (h - 0.5) * jit                            # feature points in skewed coordinates
        if hexa:
            F = F @ _HEX.T
        r = F - Q[:, None, :]                                    # pixel -> feature point
        d = _dist(r, metric)
        o2 = np.argpartition(d, 1, axis=1)[:, :2]
        d01 = np.take_along_axis(d, o2, 1)
        sw = d01[:, 1] < d01[:, 0]
        i1 = np.where(sw, o2[:, 1], o2[:, 0])
        d1 = np.minimum(d01[:, 0], d01[:, 1])
        d2 = np.maximum(d01[:, 0], d01[:, 1])
        r1 = np.take_along_axis(r, i1[:, None, None], 1)[:, 0]
        if metric == "euclidean":
            dv = r - r1[:, None, :]
            ln = np.sqrt((dv * dv).sum(-1))
            same = ln < 1e-12
            ln = np.where(same, 1.0, ln)
            b = ((0.5 * (r + r1[:, None, :])) * dv).sum(-1) / ln
            # a point has no bisector with itself. Use a large finite number instead of inf: in smooth-min
            # inf·0 gives NaN
            b = np.where(same, 1e30, b)
            border = _smin(b, float(round_border))
        else:
            border = 0.5 * (d2 - d1)
        c1 = np.take_along_axis(Ch, i1[:, None, None], 1)[:, 0]
        hid = _hash_cells(c1, seed, 13) & 0xFFFFFFFF
        sl = slice(s0, s0 + len(Q))
        out["d1"][sl] = d1 * es
        out["d2"][sl] = d2 * es
        out["border"][sl] = border * es
        out["center"][sl] = (Q + r1) * cs + off
        out["id"][sl] = np.where(hid >= 1 << 31, hid - (1 << 32), hid)
    return out


def cellular_shape(border, d1, mode="absolute", gap=0.0, bevel=0.05):
    """
    Cellular Noise shaping (docs: Gap shrinks the cells until they vanish; larger Bevel = pointier tops, smaller = flat tops with hard edges).

      absolute  s = border − Gap/2      (image coordinates; Gap is the total gap width between two cells)
      relative  s = border/(border + d1) − Gap   (0 = cell boundary, 1 = at the feature point)
      value = clamp(s / Bevel, 0, 1); Bevel = 0 gives a hard 0/1 edge.

    The docs only give the two endpoints of relative normalization ("0 is the boundary, 1 is the cell centre"), not how to interpolate --
    here border/(border + d1) is used: exactly 1 at the feature point (d1 = 0), exactly 0 at the boundary (border = 0),
    monotonic along the line from the feature point to the boundary. Bevel Ramp is not implemented (linear slope).
    """
    if mode not in SHAPE_MODES:
        raise ValueError(f"Shape Mode must be one of {SHAPE_MODES}")
    if mode == "absolute":
        s = border - 0.5 * float(gap)
    else:
        s = border / np.maximum(border + d1, 1e-12) - float(gap)
    bv = float(bevel)
    if bv <= 0:
        return (s > 0).astype(np.float64)
    return np.clip(s / bv, 0.0, 1.0)


# ═══════════════════════════════════════════════════════════ image output
def _positions(img, pos_layer, xres, yres):
    """No pos layer: (u, v·H/W) at pixel centres; with one: that layer's values (2 or 3 channels)."""
    from .pattern import _base, _pix
    from .pixel import getn
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    pl = str(pos_layer).strip()
    if pl:
        if like is None:
            raise ValueError("Pos Layer needs the cop input connected")
        a = getn(like, pl)
        if a.shape[2] not in (2, 3):
            raise ValueError("Pos Layer needs 2 or 3 channels")
        return out, like, a.reshape(-1, a.shape[2]), W, H
    u, v = _pix(W, H)
    return out, like, np.stack([u, v * (H / W)], -1).reshape(-1, 2), W, H


def _common(P, element_size, element_scale, jitter, jitter_scale, metric,
            lattice, seed, offset, tile, tile_size, round_border):
    from .pixel import _vec
    D = P.shape[1]
    return cell_fields(P, element_size, _vec(element_scale, 3), jitter,
                       _vec(jitter_scale, 3), metric, lattice, seed,
                       _vec(offset, 3), _vec(tile_size, 3)[:D] if tile else None,
                       round_border)


def worley_noise(img=None, element_size=0.1, element_scale="1 1 1",
                 jitter=1.0, jitter_scale="1 1 1", lattice="rectangular",
                 metric="euclidean", round_border=0.0, offset="0 0 0",
                 tile=False, tile_size="1 1 1", pos_layer="", seed=0,
                 prefix="", post=None, xres=512, yres=512):
    """
    Houdini Worley Noise (= Worley Noise 3D when the pos layer has 3 channels). Layer name = prefix + these names:
      dist1 / dist2  distance to the nearest / second-nearest feature point (Post Processing only applies to these two layers)
      border         distance to the cell boundary (SDF, positive inside the cell)
      center         coordinates of the nearest feature point (2 or 3 channels)
      id             hash of the nearest cell (signed integer)
    """
    from .pixel import put
    from . import noisepost as _pp
    out, like, P, W, H = _positions(img, pos_layer, xres, yres)
    f = _common(P, element_size, element_scale, jitter, jitter_scale, metric,
                lattice, seed, offset, tile, tile_size, round_border)
    pre = str(prefix).strip()
    for k in ("d1", "d2"):
        put(out, pre + "dist" + k[1], _pp.run(bk.NUMPY, f[k], post or {})
            .reshape(H, W), like)
    put(out, pre + "border", f["border"].reshape(H, W), like)
    put(out, pre + "center", f["center"].reshape(H, W, -1), like)
    put(out, pre + "id", f["id"].reshape(H, W), like)
    return out


def cellular_noise(img=None, amplitude=1.0, shift=0.0, element_size=0.1,
                   element_scale="1 1 1", jitter=1.0, jitter_scale="1 1 1",
                   lattice="rectangular", metric="euclidean", smooth_edge=0.0,
                   offset="0 0 0", tile=False, tile_size="1 1 1",
                   shape_mode="absolute", gap=0.0, bevel=0.05, pos_layer="",
                   seed=0, prefix="", post=None, xres=512, yres=512):
    """
    Houdini Cellular Noise (= Cellular Noise 3D when the pos layer has 3 channels).
      noise = Amplitude · shape(border) + Shift, then through Post Processing
      border / center / id as in Worley Noise
    The docs don't give the order of Amplitude / Shift; following the Range section convention (multiply then add).
    """
    from .pixel import put
    from . import noisepost as _pp
    out, like, P, W, H = _positions(img, pos_layer, xres, yres)
    f = _common(P, element_size, element_scale, jitter, jitter_scale, metric,
                lattice, seed, offset, tile, tile_size, smooth_edge)
    # relative mode needs a ratio in cell space; border and d1 are both multiplied by the same Element Size,
    # so the ratio is unaffected and the output-unit values are used directly
    v = cellular_shape(f["border"], f["d1"], shape_mode, gap, bevel)
    v = _pp.run(bk.NUMPY, v * float(amplitude) + float(shift), post or {})
    pre = str(prefix).strip()
    put(out, pre + "noise", v.reshape(H, W), like)
    put(out, pre + "border", f["border"].reshape(H, W), like)
    put(out, pre + "center", f["center"].reshape(H, W, -1), like)
    put(out, pre + "id", f["id"].reshape(H, W), like)
    return out
