"""
The image-analysis family: slope / aspect, curvature, statistics, histogram equalization and matching, connectivity segmentation, image comparison.

Mirrors Copernicus's Slope Direction / Curvature / Statistics / Equalize /
Segment by Connectivity / Compare. It comes after the height-map family, for two reasons:

  · curvature and slope are the raw material of **HeightField Mask by Feature** -- the next family's terrain masks
    are built on them (the erosion filter blog also says splitting ridges and gullies by curvature is more robust than by elevation)
  · statistics and comparison fill the missing half of pcg49's evaluation loop: that side can only score by **geometric** criteria,
    and can't express "does this image look like the reference image"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Second-derivative borders: pad by quadratic extrapolation, not clamp
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The height-map family's first differences use one-sided differences at the border, exact on slopes. Curvature needs second derivatives, where one-sided differences
aren't enough: with clamp padding the outermost ring's h_xx is h1 − h0 (a first-order quantity), and in a bowl it reports a ring of
fake "ridges".

Here one ring is padded by **quadratic polynomial extrapolation**: h[−1] = 3h0 − 3h1 + h2. Any quadratic surface (including
the cross term xy) is exact on the padded ring, so the first and second derivatives from central differences are exact on
**every pixel** (border included) -- tests compare quadratic surfaces pixel by pixel against analytic curvature, error
on the order of 1e-13. Falls back to clamp when width or height is under 3 pixels.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Curvature sign: **convex is positive**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Conventions vary (GIS packages even contradict each other). Here it's unified as "peaks and ridges positive, pits and gullies
negative" -- "greater than 0 is a ridge" is the hardest to mix up when making masks. Top of a spherical cap of radius R: mean curvature +1/R,
Gaussian curvature +1/R².

    mean        mean curvature, the average of the two principal curvatures
    gaussian    Gaussian curvature, the product of the two principal curvatures (negative at saddles; unrelated to convexity)
    profile     normal-section curvature along the aspect (steepest direction) -- whether the slope is steepening or flattening
    tangential  normal-section curvature perpendicular to the aspect -- whether the surface bulges (spur) or dips (gully) crosswise
    plan        curvature of the contour line itself (in the horizontal plane) -- whether water spreads out or converges

One check ties the first three together: profile and tangential are normal-section curvatures in two **orthogonal** directions,
and by Euler's formula their average **identically equals** the mean curvature. Tests compare it pixel by pixel.

On flat ground (slope 0) the aspect is undefined, and profile / tangential / plan are 0.
"""
from __future__ import annotations

import json
import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from .filters import _conv1d, gaussian_kernel
from .heightmap import _height, _texel

CURVATURES = ("mean", "gaussian", "profile", "tangential", "plan")
SLOPE_UNITS = ("degrees", "tangent", "normalized")
HIST_MODES = ("equalize", "match")


# ═══════════════════════════════════════════════════════════ derivatives
def _pad(xp, a, axis, tile):
    """Pad one ring. tile -> periodic; otherwise quadratic extrapolation (n ≥ 3), see the file header."""
    n = int(a.shape[axis])
    if tile:
        return xp.pad_axis(a, 1, axis, "wrap")
    if n < 3:
        return xp.pad_axis(a, 1, axis, "clamp")

    def take(i):
        sl = [slice(None)] * 3
        sl[axis] = slice(i, i + 1) if i >= 0 else slice(n + i, n + i + 1)
        return a[tuple(sl)]
    lo = take(0) * 3.0 - take(1) * 3.0 + take(2)
    hi = take(-1) * 3.0 - take(-2) * 3.0 + take(-3)
    return xp.concat([lo, a, hi], axis)


def derivatives(xp, h, tile):
    """(hx, hy, hxx, hyy, hxy), per-pixel differences (not yet divided by pixel spacing). h is (H,W,1)."""
    p = _pad(xp, _pad(xp, h, 0, tile), 1, tile)
    c = p[1:-1, 1:-1]
    hx = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5
    hy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5
    hxx = p[1:-1, 2:] - c * 2.0 + p[1:-1, :-2]
    hyy = p[2:, 1:-1] - c * 2.0 + p[:-2, 1:-1]
    hxy = (p[2:, 2:] - p[2:, :-2] - p[:-2, 2:] + p[:-2, :-2]) * 0.25
    return hx, hy, hxx, hyy, hxy


def _world_derivs(img, layer, strength, world_size, tile):
    xp = img.backend
    t = _texel(world_size, img.xres)
    hx, hy, hxx, hyy, hxy = derivatives(xp, _height(img, layer, strength),
                                        bool(tile))
    k1, k2 = 1.0 / t, 1.0 / (t * t)
    return xp, hx * k1, hy * k1, hxx * k2, hyy * k2, hxy * k2


def _out(img, keep):
    return img.copy() if keep else CopImage(img.xres, img.yres)


# ═══════════════════════════════════════════════════════ Slope & Aspect
def slope_aspect(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                 units="degrees", tile=False, slope_layer="slope",
                 aspect_layer="aspect", dir_layer="slope_dir", keep=True):
    """
    Slope, aspect, downhill direction.

      slope_layer   slope: degrees (0~90°) / tangent (|∇h|, world scale) /
                    normalized (0~1, = degrees / 90)
      aspect_layer  aspect in degrees: the **downhill** direction, 0° = +u, 90° = +v, range (−180, 180].
                    0 on flat ground
      dir_layer     downhill unit vector (u, v), 2 channels. (0, 0) on flat ground. Feed it into COP Distort
                    for "drag downhill", into Scatter's orientation to place things along the slope

    Check: on a slope h = a·x + b·y the slope is exactly atan(√(a²+b²)) and the aspect exactly
    atan2(−b, −a). Derivatives pad the border by quadratic extrapolation, so quadratic surfaces are exact even at the border.

    Leave any output layer name empty to skip that layer.
    """
    if img is None:
        return CopImage()
    if units not in SLOPE_UNITS:
        raise ValueError(f"Units must be one of {SLOPE_UNITS}")
    xp, hx, hy, _, _, _ = _world_derivs(img, layer, strength, world_size,
                                        tile)
    g = xp.sqrt(hx * hx + hy * hy)
    out = _out(img, keep)
    if str(slope_layer).strip():
        if units == "tangent":
            s = g
        else:
            s = xp.arctan2(g, xp.ones(tuple(g.shape))) * (180.0 / math.pi)
            if units == "normalized":
                s = s * (1.0 / 90.0)
        out.set(str(slope_layer).strip(), s)
    flat = g <= 1e-300
    if str(aspect_layer).strip():
        a = xp.arctan2(hy * -1.0, hx * -1.0) * (180.0 / math.pi)
        out.set(str(aspect_layer).strip(), xp.where(flat, g * 0.0, a))
    if str(dir_layer).strip():
        inv = xp.where(flat, g * 0.0, 1.0 / xp.where(flat, g * 0.0 + 1.0, g))
        out.set(str(dir_layer).strip(),
                xp.concat([hx * inv * -1.0, hy * inv * -1.0], -1))
    return out


# ═══════════════════════════════════════════════════════════ Curvature
def curvature_from(xp, hx, hy, hxx, hyy, hxy, kind):
    """World-scale derivatives -> curvature (convex positive). Formulas in the file header."""
    if kind not in CURVATURES:
        raise ValueError(f"Kind must be one of {CURVATURES}")
    p = hx * hx + hy * hy
    q = p + 1.0
    if kind == "mean":
        return ((hy * hy + 1.0) * hxx - hx * hy * hxy * 2.0
                + (hx * hx + 1.0) * hyy) * -0.5 / (q * xp.sqrt(q))
    if kind == "gaussian":
        return (hxx * hyy - hxy * hxy) / (q * q)
    flat = p <= 1e-300
    ps = xp.where(flat, p * 0.0 + 1.0, p)
    along = hxx * hx * hx + hxy * hx * hy * 2.0 + hyy * hy * hy
    across = hxx * hy * hy - hxy * hx * hy * 2.0 + hyy * hx * hx
    if kind == "profile":
        v = along * -1.0 / (ps * q * xp.sqrt(q))
    elif kind == "tangential":
        v = across * -1.0 / (ps * xp.sqrt(q))
    else:                                         # plan
        v = across * -1.0 / (ps * xp.sqrt(ps))
    return xp.where(flat, p * 0.0, v)


def curvature(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
              kind="mean", tile=False, scale=1.0, out_layer="curvature",
              keep=True):
    """
    Curvature in 1/world units, **convex positive** (peaks, ridges > 0; pits, gullies < 0).

    `scale` is a multiplier applied at the end -- curvature magnitude changes with scale (1/R); to view it directly as a mask, multiplying by a
    characteristic length makes it dimensionless (e.g. multiply by world_size / 20).

    Checks: on quadratic surfaces all five curvatures equal the analytic values pixel by pixel (border included); on a spherical cap mean curvature → 1/R,
    with second-order convergence in resolution; all 0 on a slope; (profile + tangential)/2 = mean.
    """
    if img is None:
        return CopImage()
    xp, hx, hy, hxx, hyy, hxy = _world_derivs(img, layer, strength,
                                              world_size, tile)
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "curvature",
            curvature_from(xp, hx, hy, hxx, hyy, hxy, kind) * float(scale))
    return out


# ═══════════════════════════════════════════════════════════ Statistics
def _np(a):
    return np.asarray(bk.backend_of(a).to_numpy(a)
                      if not isinstance(a, np.ndarray) else a, np.float64)


def _mask(img, mask_layer, thr=0.5):
    """Pixels where channel 0 of the mask layer > thr. Empty layer name -> None (all)."""
    m = str(mask_layer or "").strip()
    if not m:
        return None
    return _np(img.need(m))[:, :, 0] > float(thr)


def statistics(img, layers="", mask_layer="", percentiles=(1, 50, 99)):
    """
    Per-layer, per-channel statistics -> dict.

    Each channel gets min / max / mean / std / percentiles, plus the count of non-finite values (nan / inf)
    -- those don't take part in the statistics, but **must** be reported: one nan vertex going downstream shows up as
    "some pixel turned black" or "the whole image became nan", miles away from the source.

    std is the population standard deviation (divide by N, not N−1): this describes this image, it isn't estimating a population.
    Percentiles use linear interpolation, consistent with numpy.percentile's default.
    """
    if img is None:
        return {}
    names = [n for n in str(layers).split() if n] or img.names
    m = _mask(img, mask_layer)
    pc = [float(x) for x in percentiles]
    res = {"resolution": [img.xres, img.yres], "layers": {}}
    if m is not None:
        res["coverage"] = float(m.mean())
    for n in names:
        a = _np(img.need(n))
        C = a.shape[2]
        st = {"channels": C, "min": [], "max": [], "mean": [], "std": [],
              "nonfinite": [], "percentiles": {str(p): [] for p in pc}}
        for ch in range(C):
            v = a[:, :, ch]
            v = v[m] if m is not None else v.ravel()
            fin = np.isfinite(v)
            st["nonfinite"].append(int((~fin).sum()))
            v = v[fin]
            if v.size == 0:
                for k in ("min", "max", "mean", "std"):
                    st[k].append(None)
                for p in pc:
                    st["percentiles"][str(p)].append(None)
                continue
            st["min"].append(float(v.min()))
            st["max"].append(float(v.max()))
            st["mean"].append(float(v.mean()))
            st["std"].append(float(v.std()))
            for p, q in zip(pc, np.percentile(v, pc)):
                st["percentiles"][str(p)].append(float(q))
        res["layers"][n] = st
    return res


def stats_report(res):
    """Statistics -> one human-readable line per layer."""
    lines = [f"{res.get('resolution', ['?', '?'])[0]}x"
             f"{res.get('resolution', ['?', '?'])[1]}"
             + (f"  mask coverage {res['coverage'] * 100:.1f}%"
                if "coverage" in res else "")]
    for n, st in res.get("layers", {}).items():
        def f(k):
            return ",".join("—" if x is None else f"{x:.4g}" for x in st[k])
        bad = sum(st["nonfinite"])
        lines.append(f"{n}({st['channels']}): min {f('min')}  max {f('max')}"
                     f"  mean {f('mean')}  std {f('std')}"
                     + (f"  ⚠ {bad} non-finite values" if bad else ""))
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════ histogram equalization / matching
def _ranks(v):
    """
    Ranks (0 ~ N−1), **ties get the average**.

    Without averaging, tied values get different ranks in order of appearance -- a flat-colour region becomes a
    gradient after equalization, its direction depending on pixel storage order. The most classic pitfall of histogram equalization.
    """
    s = np.sort(v)
    lo = np.searchsorted(s, v, "left")
    hi = np.searchsorted(s, v, "right") - 1
    return (lo + hi) * 0.5


def _quantile_at(sorted_ref, pos):
    """Linear interpolation on sorted_ref by **index**. Lands exactly on samples when pos is an integer."""
    M = sorted_ref.size
    pos = np.clip(pos, 0.0, M - 1.0)
    i0 = np.floor(pos).astype(np.int64)
    i1 = np.minimum(i0 + 1, M - 1)
    f = pos - i0
    return sorted_ref[i0] * (1.0 - f) + sorted_ref[i1] * f


def histogram(img, mode="equalize", reference=None, layers="",
              ref_layer="", mask_layer="", amount=1.0):
    """
    Histogram equalization / matching. Done **by rank**, no binning -- exact, and no binning steps introduced.

      equalize  spread each channel's values evenly by rank over its own original [min, max]. Range unchanged,
                only the distribution flattened
      match     replace each channel's values with the reference image's value **at the same percentile**: the output distribution is the reference
                image's distribution. When a batch of AI textures has inconsistent colours, match them all to the same reference

    Checks:
      · after equalization the sorted values are exactly an arithmetic sequence over [min, max] (when there are no ties)
      · the mapping is **order-preserving**: two pixels with a ≤ b still give a' ≤ b'
      · matching to itself = identity; when both images have the same pixel count, the sorted output **equals element by element** the sorted reference
      · flat-colour regions are not stretched into gradients (ties get the average rank)

    Each channel is done independently -- matching RGB channels separately makes the hue follow the reference, which is usually exactly what you want;
    to match only brightness, convert to luminance first (COP Luminance).

    If mask_layer is given only pixels inside the mask are changed (the reference uses all of its own pixels).
    amount linearly blends between the original and the result. numpy-only (needs sorting).
    """
    if img is None:
        return CopImage()
    if mode not in HIST_MODES:
        raise ValueError(f"Mode must be one of {HIST_MODES}")
    if mode == "match" and reference is None:
        raise ValueError("Match needs a reference image (the reference input)")
    xp = img.backend
    names = [n for n in str(layers).split() if n] or img.names
    m = _mask(img, mask_layer)
    amt = float(amount)
    out = img.copy()
    for n in names:
        a = _np(img.need(n))
        C = a.shape[2]
        res = a.copy()
        if mode == "match":
            rn = str(ref_layer).strip() or n
            r = _np(reference.need(rn))
            if r.shape[2] not in (1, C):
                raise ValueError(
                    f"reference layer '{rn}' has {r.shape[2]} channels, '{n}' has {C} -- "
                    f"they must match, or the reference must be 1 channel (all channels matched to it)")
        for ch in range(C):
            v = a[:, :, ch]
            sel = m if m is not None else np.ones(v.shape, bool)
            x = v[sel]
            ok = np.isfinite(x)
            if ok.sum() < 1:
                continue
            xs = x[ok]
            rk = _ranks(xs)
            N = xs.size
            if mode == "equalize":
                lo, hi = float(xs.min()), float(xs.max())
                y = lo + (hi - lo) * (rk / (N - 1)) if N > 1 else xs
            else:
                rv = r[:, :, ch if r.shape[2] == C else 0].ravel()
                rv = np.sort(rv[np.isfinite(rv)])
                if rv.size == 0:
                    raise ValueError(f"reference layer '{rn}' has no finite values")
                pos = rk * ((rv.size - 1) / (N - 1)) if N > 1 else \
                    np.full(N, (rv.size - 1) * 0.5)
                y = _quantile_at(rv, pos)
            x2 = x.copy()
            x2[ok] = xs + (y - xs) * amt if amt != 1.0 else y
            vv = v.copy()
            vv[sel] = x2
            res[:, :, ch] = vv
        out.set(n, xp.asarray(res))
    return out


# ═══════════════════════════════════════════════════ Segment by Connectivity
def _runs(mask):
    """Contiguous runs in each row: (row, start, end), end exclusive. Sorted by row, start."""
    H, W = mask.shape
    p = np.zeros((H, W + 2), np.int8)
    p[:, 1:-1] = mask
    d = np.diff(p, axis=1)
    rs, s = np.nonzero(d == 1)
    re, e = np.nonzero(d == -1)
    # both sides come out in (row, col) lexicographic order, one-to-one
    return rs.astype(np.int64), s.astype(np.int64), e.astype(np.int64)


def _find(par, i):
    root = i
    while par[root] != root:
        root = par[root]
    while par[i] != root:                    # path compression
        par[i], i = root, par[i]
    return root


def _union(par, a, b):
    ra, rb = _find(par, a), _find(par, b)
    if ra != rb:
        if ra < rb:
            par[rb] = ra
        else:
            par[ra] = rb


def label(mask, connectivity=8, tile=False):
    """
    Connected component labelling -> (labels (H,W) int64, 0 = background, 1..K, by area from largest to smallest).

    **Union-find over runs**, not per pixel: each row is first cut into contiguous runs (vectorized), and only runs
    in adjacent rows are merged. The Python loop count is the number of runs, not pixels -- a 1024²
    noise mask has about 250k runs, and a flat-colour region is one run per row.

    With 8-connectivity, runs in adjacent rows connect even if they only touch **diagonally** (interval widened by one). With tile, the first and last rows
    and the first and last columns are treated as adjacent.

    Label order is deterministic: by area descending, ties by the position of the first pixel -- the same mask
    always gets the same set of ids, so downstream ID Masks taking "the largest N" is stable.
    """
    mask = np.asarray(mask, bool)
    H, W = mask.shape
    if connectivity not in (4, 8):
        raise ValueError("Connectivity must be 4 or 8")
    rows, s, e = _runs(mask)
    R = rows.size
    lab = np.zeros((H, W), np.int64)
    if R == 0:
        return lab
    par = list(range(R))
    k = 1 if connectivity == 8 else 0
    row_start = np.searchsorted(rows, np.arange(H + 1))

    def link(ya, yb):
        """Merge the runs of row ya with those of row yb pairwise (two pointers, O(runs))."""
        a0, a1 = row_start[ya], row_start[ya + 1]
        b0, b1 = row_start[yb], row_start[yb + 1]
        i, j = a0, b0
        while i < a1 and j < b1:
            if s[i] < e[j] + k and s[j] < e[i] + k:
                _union(par, i, j)
            if e[i] < e[j]:
                i += 1
            else:
                j += 1
        if tile and k:
            # 8-connectivity + tile: column W−1 and column 0 also touch diagonally
            if a1 > a0 and b1 > b0:
                if e[a1 - 1] == W and s[b0] == 0:
                    _union(par, a1 - 1, b0)
                if s[a0] == 0 and e[b1 - 1] == W:
                    _union(par, a0, b1 - 1)

    for y in range(1, H):
        link(y - 1, y)
    if tile and H > 1:
        link(H - 1, 0)
    if tile:
        # runs touching the left and right edges in the same row are adjacent
        for y in range(H):
            a0, a1 = row_start[y], row_start[y + 1]
            if a1 - a0 >= 2 and s[a0] == 0 and e[a1 - 1] == W:
                _union(par, a0, a1 - 1)
    roots = np.array([_find(par, i) for i in range(R)], np.int64)
    lens = e - s
    uniq, inv = np.unique(roots, return_inverse=True)
    area = np.bincount(inv, weights=lens).astype(np.int64)
    first = np.full(uniq.size, np.iinfo(np.int64).max)
    np.minimum.at(first, inv, rows * W + s)
    order = np.lexsort((first, -area))        # area descending, then by first pixel
    newid = np.empty(uniq.size, np.int64)
    newid[order] = np.arange(1, uniq.size + 1)
    rid = newid[inv]
    # paint the runs back: flat indices of all pixels inside runs computed in one go
    tot = int(lens.sum())
    starts = rows * W + s
    off = np.arange(tot) - np.repeat(np.cumsum(lens) - lens, lens)
    lab.ravel()[np.repeat(starts, lens) + off] = np.repeat(rid, lens)
    return lab


def segment(img, layer="mask", threshold=0.5, connectivity=8, min_area=0,
            tile=False, out_layer="id", keep=True):
    """
    Mask -> id layer of connected regions (0 = background, 1..K by area from largest to smallest). Returns (image, report).

    Feed it into ID Masks for "one mask per region" -> regional prompts. Typical chain: a black-and-white mask from AI segmentation
    contains several blobs, and this step separates and numbers them.

    Fragments below `min_area` (pixels) are merged into the background -- AI masks always have some stray dots at the edges.
    """
    if img is None:
        return CopImage(), {"count": 0}
    xp = img.backend
    a = _np(img.need(layer))[:, :, 0]
    m = np.isfinite(a) & (a > float(threshold))
    lab = label(m, int(connectivity), bool(tile))
    K = int(lab.max())
    removed = 0
    if int(min_area) > 0 and K:
        area = np.bincount(lab.ravel(), minlength=K + 1)
        keepi = area >= int(min_area)
        keepi[0] = False
        removed = int((~keepi[1:]).sum())
        # kept ones are renumbered contiguously (order unchanged: already by area descending)
        remap = np.zeros(K + 1, np.int64)
        remap[keepi] = np.arange(1, int(keepi.sum()) + 1)
        lab = remap[lab]
        K = int(lab.max())
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "id",
            xp.asarray(lab.astype(np.float64)[:, :, None]))
    areas = np.bincount(lab.ravel(), minlength=K + 1)[1:].tolist()
    return out, {"count": K, "removed": removed, "areas": areas}


# ═══════════════════════════════════════════════════════════ Compare
def compare(a_img, b_img, layer_a=DEFAULT_LAYER, layer_b="", data_range=1.0,
            sigma=1.5, out_diff="diff", out_ssim="ssim", keep=True):
    """
    Difference between two images. Returns (image, metrics dict). Two layers are added to the image: per-pixel |a − b| and the SSIM map.

      MAE / RMSE   mean absolute error / root mean square error
      PSNR         20·log10(data_range / RMSE), dB. +inf when identical
      SSIM         structural similarity (Wang et al. 2004): Gaussian window σ = 1.5 (radius 5,
                   exactly the paper's 11×11 window), K1 = 0.01, K2 = 0.03,
                   C1 = (K1·L)², C2 = (K2·L)², L = data_range. Computed per channel then averaged

    Borders use clamp (copy edges). Many implementations only average over the region where "the window lies entirely inside the image" --
    that gives slightly different numbers; keep this in mind when comparing the same metric across tools.

    Checks: compared with itself SSIM = 1, MAE = 0, PSNR = +inf; symmetric; adding 0.1 overall gives
    RMSE = 0.1 and PSNR exactly 20 dB; SSIM matches a naive per-window implementation to 1e-12.

    If b has a different resolution it is resampled to a first; 1-to-many channel counts broadcast.
    """
    if a_img is None or b_img is None:
        raise ValueError("Compare needs two images")
    from .core import conform
    b_img = conform(b_img, a_img)
    xp = a_img.backend
    A = a_img.need(layer_a)
    B = b_img.need(str(layer_b).strip() or layer_a)
    if b_img.backend is not xp:
        B = xp.asarray(bk.backend_of(B).to_numpy(B))
    ca, cb = A.shape[2], B.shape[2]
    if ca != cb:
        if ca == 1:
            A = xp.broadcast_to(A, tuple(B.shape))
        elif cb == 1:
            B = xp.broadcast_to(B, tuple(A.shape))
        else:
            raise ValueError(f"channel counts don't match: {ca} and {cb}")
    L = float(data_range)
    if not L > 0:
        raise ValueError("Data Range must be > 0")
    D = A - B
    AD = xp.abs(D)
    k = gaussian_kernel(float(sigma))

    def G(x):
        return _conv1d(xp, _conv1d(xp, x, k, 1, "clamp"), k, 0, "clamp")
    mu_a, mu_b = G(A), G(B)
    saa = G(A * A) - mu_a * mu_a
    sbb = G(B * B) - mu_b * mu_b
    sab = G(A * B) - mu_a * mu_b
    C1, C2 = (0.01 * L) ** 2, (0.03 * L) ** 2
    smap = ((mu_a * mu_b * 2.0 + C1) * (sab * 2.0 + C2)
            / ((mu_a * mu_a + mu_b * mu_b + C1) * (saa + sbb + C2)))
    mae = xp.fmean_scalar(AD)
    mse = xp.fmean_scalar(D * D)
    rmse = math.sqrt(max(mse, 0.0))
    psnr = float("inf") if rmse == 0.0 else 20.0 * math.log10(L / rmse)
    ssim = xp.fmean_scalar(smap)
    out = _out(a_img, keep)
    if str(out_diff).strip():
        out.set(str(out_diff).strip(), AD)
    if str(out_ssim).strip():
        out.set(str(out_ssim).strip(), smap)
    return out, {"mae": mae, "rmse": rmse, "psnr": psnr, "ssim": ssim,
                 "max_abs": xp.fmax_scalar(AD)}


def dumps(obj):
    """Statistics / metrics -> JSON. inf / nan are written as strings -- standard JSON doesn't have them."""
    def fix(x):
        if isinstance(x, float) and not math.isfinite(x):
            return "inf" if x > 0 else ("-inf" if x < 0 else "nan")
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        if isinstance(x, list):
            return [fix(v) for v in x]
        return x
    return json.dumps(fix(obj), ensure_ascii=False, sort_keys=True)
