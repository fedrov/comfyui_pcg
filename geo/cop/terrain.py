"""
The HeightField family: mask by feature, terrace, thermal erosion (slump), height field to mesh.

Mirrors Houdini's HeightField Mask by Feature / Terrace / Slump (Erode Thermal) /
Convert HeightField. The previous two families (height map, image analysis) and the erosion filter are its raw material: slope and
curvature come from analysis.py, and the scale conventions match the height-map family:

    world height = height value x strength
    pixel spacing = world_size / width

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Height field to mesh: v points toward -Z (north)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COP's row 0 is v=0 (the bottom of the image). When converting to a Y-up mesh, the image's "up" maps to -Z -- so
in Houdini's top view (X right, Z down) the height map is upright, not upside down.

`build.grid`'s uv used to have v toward +Z (pcg49 noted its handedness is opposite to UV Project), so at the time
this file **did not reuse** it and built its own mesh; pcg56 changed build.grid to v toward -Z as well. Criteria (pinned in tests): sampling the COP at each mesh point's uv
gets back that pixel's value bit-exactly; face normals point +Y; uv handedness matches UV Project (planar, y).
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from . import accel as AC
from .filters import _conv1d, gaussian_kernel
from .heightmap import _height, _texel, height_to_normal
from .analysis import derivatives, curvature_from

CURV_MODES = ("off", "ridges", "gullies")
# pcg100: Houdini Mask by Feature's Blend Mode (first item = old behaviour: multiply)
MASK_BLENDS = ("multiply", "add", "average", "minimum", "maximum")
NEIGHBOURS = (8, 4)
_DIRS8 = ((1, 0), (-1, 0), (0, 1), (0, -1),
          (1, 1), (1, -1), (-1, 1), (-1, -1))
_BIG = 1e30


def _out(img, keep):
    return img.copy() if keep else CopImage(img.xres, img.yres)


def _np(a):
    return np.asarray(bk.backend_of(a).to_numpy(a)
                      if not isinstance(a, np.ndarray) else a, np.float64)


# ═════════════════════════════════════════════════════ Mask by Feature
def band(xp, x, lo, hi, falloff):
    """
    Soft interval: 1 inside [lo, hi], smoothstepping to 0 within the falloff width outside.

    falloff = 0 gives a hard interval (endpoints included). lo / hi can be ±inf (one-sided).
    """
    f = float(falloff)
    lo = -_BIG if lo is None or lo == -math.inf else float(lo)
    hi = _BIG if hi is None or hi == math.inf else float(hi)
    if f <= 0.0:
        one = x * 0.0 + 1.0
        zero = x * 0.0
        return xp.where(x >= lo, xp.where(x <= hi, one, zero), zero)
    up = xp.clip((x - (lo - f)) * (1.0 / f), 0.0, 1.0)
    dn = xp.clip(((hi + f) - x) * (1.0 / f), 0.0, 1.0)
    s = xp.minimum(up, dn)
    return s * s * (3.0 - 2.0 * s)


def mask_by_feature(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                    tile=False,
                    use_height=False, height_min=0.0, height_max=1.0,
                    height_falloff=0.0,
                    use_slope=True, slope_min=20.0, slope_max=90.0,
                    slope_falloff=5.0,
                    curvature="off", curv_threshold=0.0, curv_falloff=0.3,
                    curv_blur=2.0, curv_reference=0.0,
                    use_aspect=False, aspect_dir=90.0, aspect_spread=45.0,
                    aspect_falloff=15.0,
                    invert=False, out_layer="mask", keep=True,
                    blend_mode="multiply", smooth_radius=0.0,
                    use_occlusion=False, occ_min=0.2, occ_max=1.0,
                    occ_falloff=0.0, occ_height_scale=1.0, occ_radius=0.1,
                    occ_step_scale=1.0, occ_samples=8):
    """
    Mask by terrain feature. Enabled criteria are **multiplied** (AND); with none enabled the mask is all 1.

      height     [height_min, height_max], in **height values** (not multiplied by strength), soft edge width
              height_falloff
      slope      [slope_min, slope_max], degrees. Default >= 20°: "rock on steep slopes"
      curvature  ridges / gullies: split ridges and gullies by tangential curvature -- **not by elevation**;
              elevation gets it backwards on "high gullies, low ridges". Height is first blurred by curv_blur
              pixels before computing curvature (pixel-level curvature is pure noise); then normalized by a reference value:
              curv_reference > 0 uses it (units 1/world unit; tiled generation should give this),
              otherwise the 90th percentile of |curvature| of **this image** -- so threshold 0 = just splits ridges and gullies,
              positive values = only sharper ridges
      aspect     downslope direction within spread degrees of aspect_dir (degrees, 0° = +u, 90° = +v).
              Flat ground has no aspect and counts as 0

    Soft edges are all smoothstep; falloff = 0 gives hard edges (compared pixel by pixel in the tests).

    Added in pcg100 following Houdini HeightField Mask by Feature (defaults = old behaviour, bit-identical):
      blend_mode     how multiple criteria combine: multiply (old) / add / average / minimum / maximum.
                     add is not clamped (the docs don't say to clamp; the mask can be > 1, and < 0 after Invert)
      smooth_radius  Smooth Radius: blur the height before measuring features, radius in **world units**
                     (Houdini says local space). Gaussian σ = radius / 3 (kernel truncated at 3σ = radius).
                     All criteria use the blurred height; curvature's own curv_blur still adds another layer on top
      use_occlusion  Mask by Occlusion: occlusion = 1 - Height to AO (horizon-based,
                     see heightmap.height_to_ao), 0 = open, 1 = fully blocked. 1 inside [occ_min,
                     occ_max], soft edge occ_falloff. occ_height_scale multiplies the height
                     (exaggerates occlusion), occ_radius = View Radius (world units), occ_samples =
                     number of directions (Sample Count), steps = View Radius in pixels / occ_step_scale
                     (Step Scale is "pixels per step", capped at 64 steps)
    """
    if img is None:
        return CopImage()
    if curvature not in CURV_MODES:
        raise ValueError(f"Curvature must be one of {CURV_MODES}")
    if blend_mode not in MASK_BLENDS:
        raise ValueError(f"Blend Mode must be one of {MASK_BLENDS}")
    xp = img.backend
    texel = _texel(world_size, img.xres)
    raw = img.need(layer)[:, :, 0:1]
    tile = bool(tile)
    sr = float(smooth_radius)
    if sr < 0.0:
        raise ValueError("Smooth Radius can't be negative")
    if sr > 0.0:
        k_ = gaussian_kernel(sr / texel / 3.0)
        b_ = "wrap" if tile else "clamp"
        raw = _conv1d(xp, _conv1d(xp, raw, k_, 1, b_), k_, 0, b_)
    h = raw * float(strength)
    # each criterion's mask is collected in the old code's order; multiply multiplies them in turn -- bit-identical to the old m = m * ...
    feats = []
    if use_height:
        feats.append(band(xp, raw, height_min, height_max, height_falloff))
    need_d = use_slope or use_aspect
    if need_d:
        hx, hy, _, _, _ = derivatives(xp, h, tile)
        hx, hy = hx * (1.0 / texel), hy * (1.0 / texel)
        g = xp.sqrt(hx * hx + hy * hy)
    if use_slope:
        deg = xp.arctan2(g, g * 0.0 + 1.0) * (180.0 / math.pi)
        feats.append(band(xp, deg, slope_min, slope_max, slope_falloff))
    if use_aspect:
        a = math.radians(float(aspect_dir))
        flat = g <= 1e-300
        gs = xp.where(flat, g * 0.0 + 1.0, g)
        # downslope direction = -∇h / |∇h|, angle against the target direction
        cosd = (hx * (-math.cos(a)) + hy * (-math.sin(a))) / gs
        ang = xp.arctan2(xp.sqrt(xp.maximum(1.0 - cosd * cosd, 0.0)),
                         cosd) * (180.0 / math.pi)
        am = band(xp, ang, None, aspect_spread, aspect_falloff)
        feats.append(xp.where(flat, g * 0.0, am))
    if curvature != "off":
        hb = h
        sb = float(curv_blur)
        if sb > 0.0:
            k = gaussian_kernel(sb)
            b = "wrap" if tile else "clamp"
            hb = _conv1d(xp, _conv1d(xp, h, k, 1, b), k, 0, b)
        hx, hy, hxx, hyy, hxy = derivatives(xp, hb, tile)
        k1, k2 = 1.0 / texel, 1.0 / (texel * texel)
        c = curvature_from(xp, hx * k1, hy * k1, hxx * k2, hyy * k2,
                           hxy * k2, "tangential")
        ref = float(curv_reference)
        if not ref > 0.0:
            ref = float(np.percentile(np.abs(_np(c)), 90))
        cn = c * (1.0 / ref) if ref > 0.0 else c * 0.0
        if curvature == "gullies":
            cn = cn * -1.0
        feats.append(band(xp, cn, curv_threshold, None, curv_falloff))
    if use_occlusion:
        from .heightmap import height_to_ao
        # with View Radius <= 0, height_to_ao itself reports "Radius must be > 0"
        rp = float(occ_radius) / texel
        ss = float(occ_step_scale)
        if not ss > 0.0:
            raise ValueError("Step Scale must be > 0")
        steps = int(min(64, max(1, math.ceil(rp / ss))))
        tmp = CopImage(img.xres, img.yres, {"_h": raw})
        ao = height_to_ao(tmp, "_h", float(strength) * float(occ_height_scale),
                          world_size, rp, int(occ_samples), steps, 1.0, tile,
                          "_ao", keep=False).need("_ao")[:, :, 0:1]
        feats.append(band(xp, 1.0 - ao, occ_min, occ_max, occ_falloff))
    m = raw * 0.0 + 1.0
    if blend_mode == "multiply" or not feats:
        for f_ in feats:
            m = m * f_
    elif blend_mode in ("add", "average"):
        m = feats[0]
        for f_ in feats[1:]:
            m = m + f_
        if blend_mode == "average":
            m = m * (1.0 / len(feats))
    elif blend_mode == "minimum":
        m = feats[0]
        for f_ in feats[1:]:
            m = xp.minimum(m, f_)
    else:
        m = feats[0]
        for f_ in feats[1:]:
            m = xp.maximum(m, f_)
    if invert:
        m = 1.0 - m
    out = _out(img, keep)
    out.set(str(out_layer).strip() or "mask", m)
    return out


# ═══════════════════════════════════════════════════════════════ Terrace
TERRACE_METHODS = ("step_size", "num_terraces")


def _jittered_terrace(h, base, st, p, rs, seed, pin):
    """
    Terraces with Random Step > 0: each level's boundary b_k is moved randomly,
    b_k = base + st·(k + rs·(r_k - ½)), r_k = rnd(k, seed) ∈ [0,1).

    With rs <= 1, b_{k+1} - b_k >= st·(1 - rs) >= 0, so the boundaries stay ordered -> still monotonically non-decreasing;
    the average step is still st, so Number of Terraces' level count doesn't change. With pin = (k0, k1) these two
    boundaries don't move (Number of Terraces: the Min + Offset / Max + Offset boundaries are pinned -- with Offset 0
    the outside of the range stays put and both ends connect).
    The docs only say "Random Step scales the random height added to each level, 0 = all levels equal", not how it's added --
    "move the boundaries" was chosen over "per-level step + random amount" because the latter would make the level count disagree with Max Height.
    Computed in numpy float64 (searchsorted isn't in the op table); the result is handed back to the caller to convert to the backend.
    """
    from .pattern import rnd
    t = (h - base) / st
    # |jitter| <= ½ step, so the level k containing h satisfies floor(t) - 1 <= k <= floor(t) + 1, and the k + 1
    # boundary is also needed -- so [floor(min t) - 1, floor(max t) + 2] is exactly enough
    lo = int(math.floor(float(np.min(t)))) - 1
    hi = int(math.floor(float(np.max(t)))) + 2
    ks = np.arange(lo, hi + 1, dtype=np.int64)
    jit = rs * (rnd(ks, int(seed), 1) - 0.5)
    if pin is not None:
        jit = np.where((ks == pin[0]) | (ks == pin[1]), 0.0, jit)
    b = base + st * (ks + jit)
    idx = np.clip(np.searchsorted(b, h, side="right") - 1, 0, len(b) - 2)
    b0, b1 = b[idx], b[idx + 1]
    # w = st·(1 + rs·(r_{k+1} - r_k)) > 0: r is in [0,1), the difference is > -1, rs <= 1, so no division by zero
    w = b1 - b0
    f = (h - b0) / w
    return b0 + w * np.clip(f, 0.0, 1.0) ** p


def terrace(img, layer=DEFAULT_LAYER, step=0.1, offset=0.0, sharpness=0.7,
            mask_layer="", out_layer=DEFAULT_LAYER, keep=True,
            method="step_size", terraces=10, limit_range=False,
            min_height=0.0, max_height=1.0, random_step=0.0, seed=0,
            mask=1.0):
    """
    Terrace: flat treads + steep risers. Done on **height values** (not multiplied by strength).

    The relative position f ∈ [0,1) within each level goes through a power function f^p, p = 1 / (1 - sharpness):

      sharpness = 0     p = 1, identity -- nothing changes
      sharpness → 1     p → ∞, f^p hugs 0 over most of the interval and only rises steeply at the end --
                        flat treads, steep risers; the limit is a pure staircase floor

    Criteria: monotonically non-decreasing (terracing never makes a high spot lower than a low one); each level's boundary value
    offset + k·step stays put; output <= input (only cuts, never fills); identity at sharpness = 0.

    If mask_layer is given, blends between the original height and the terrace by it (e.g. terraces only on steep slopes).

    Added in pcg100 following Houdini HeightField Terrace (defaults = old behaviour, bit-identical):
      method        step_size (old) / num_terraces: step = (Max - Min) / terraces
      limit_range   under step_size, also only work within [min_height, max_height]; num_terraces
                    always works only within this range. The first boundary in the range is at Min + Offset (docs:
                    "steps are generated starting from Min Height"); outside the range nothing changes
      random_step   0-1, each boundary moves randomly by ±random_step·step/2 (see _jittered_terrace)
      seed          seed for random_step (Houdini's Step Seed)
      mask          Houdini's Mask parameter: blend amount, multiplied onto mask_layer (without mask_layer
                    it is a constant blend amount)
    Houdini has no sharpness (its treads are flat; the docs don't say what shape the risers are); this is our extension.
    """
    if img is None:
        return CopImage()
    st = float(step)
    if not st > 0.0:
        raise ValueError("Step must be > 0")
    s = float(sharpness)
    if not 0.0 <= s <= 1.0:
        raise ValueError("Sharpness must be between 0 and 1")
    if method not in TERRACE_METHODS:
        raise ValueError(f"Method must be one of {TERRACE_METHODS}")
    rs = float(random_step)
    if not 0.0 <= rs <= 1.0:
        raise ValueError("Random Step must be between 0 and 1 (> 1 makes boundaries cross and the terraces stop being monotonic)")
    xp = img.backend
    h = img.need(layer)[:, :, 0:1]
    base = float(offset)
    ranged = limit_range or method == "num_terraces"
    lo_h, hi_h = float(min_height), float(max_height)
    pin = None
    if ranged:
        if not hi_h > lo_h:
            raise ValueError("Max Height must be > Min Height")
        base = lo_h + float(offset)
    if method == "num_terraces":
        n = int(terraces)
        if n < 1:
            raise ValueError("Terraces must be at least 1")
        st = (hi_h - lo_h) / n
        pin = (0, n)
    p = 1.0 / max(1.0 - s, 1e-3)
    if rs > 0.0 and p != 1.0:
        hn = _np(h)
        ht = xp.asarray(_jittered_terrace(hn, base, st, p, rs, seed, pin)
                        .astype(np.float32))
    else:
        t = (h - base) * (1.0 / st)
        k = xp.floor(t)
        f = t - k
        # with sharpness = 0 return the input as-is, without going through floor / subtraction -- that would round by 1 ulp
        # and "identity" would no longer be bit-exact
        ht = h if p == 1.0 else (k + f ** p) * st + base
    if ranged:
        # outside the range nothing moves. With num_terraces + Offset 0 both ends land exactly on boundaries and connect;
        # with an Offset, or under step_size when the step doesn't divide the range, both ends have step-like jumps (the docs don't say
        # how Houdini handles the range endpoints; no extra transition is done here)
        inside = (h >= lo_h) * (h <= hi_h)
        ht = xp.where(inside, ht, h)
    ml = str(mask_layer or "").strip()
    mk = float(mask)
    if ml:
        w = xp.clip(img.need(ml)[:, :, 0:1], 0.0, 1.0)
        if mk != 1.0:
            w = w * mk
        ht = h + (ht - h) * w
    elif mk != 1.0:
        ht = h + (ht - h) * mk
    out = _out(img, keep)
    # output single-channel height (consistent with erosion and slump). A 3-channel grayscale image only uses channel 0
    out.set(str(out_layer).strip() or DEFAULT_LAYER, ht)
    return out


# ═══════════════════════════════════════════════ Thermal Erosion(Slump)
SLUMP_MODES = ("smooth", "granular")
DEBRIS_SOURCES = ("height", "layer", "constant")


def thermal_erode(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                  talus_angle=35.0, iterations=50, rate=0.5, neighbours=8,
                  tile=False, hardness_layer="", out_layer=DEFAULT_LAYER,
                  debris_layer="debris", keep=True, compute="auto",
                  slump_mode="smooth", seed=0, debris_source="height",
                  debris_input="debris", debris_scale=1.0,
                  remove_debris=False, add_debris=True):
    """
    Thermal erosion / slump: where steeper than the **angle of repose**, loose material slides down until the slope returns to the angle of repose.

    Each step, each pixel: for each neighbor compute "the height difference beyond the angle of repose"
    `e = h - h_nbr - tan(repose angle)·distance` (0 if < 0), then move
    `rate · max(e) / 2` of material, split among neighbors in proportion to their e. Dividing by 2 guarantees that after the move
    even the steepest pair doesn't flip over (the donor never ends up lower than the receiver).

    Criteria:
      · **mass conservation**: total height is unchanged each step (wraps around with tile; without tile there are no neighbors outside the image,
        so material doesn't flow out)
      · terrain gentler than the angle of repose everywhere doesn't move, **bit-exact**
      · an isolated tall column collapses into a cone whose slope converges to the angle of repose -- that's the definition of the angle of repose
      · after enough iterations, every neighbor pair's excess tends to 0

    hardness_layer (0-1), if given, reduces the movable material: 1 = bedrock, doesn't move at all.
    debris_layer outputs **net deposition** (height values, >= 0) -- scree slopes, talus piles, for texturing.

    The cost is iterations x neighbor count whole-image operations. Runs through the op table, on the GPU when there is one.
    compute (pcg65): auto = if the image is on torch, compute there; if on numpy but large enough and CUDA is available,
    move it over, compute, and move back (only the newly written layers). cpu = always numpy. On GPU it's float32
    (this node's GPU path has always been), differing from numpy on the order of float32 rounding.

    Added in pcg100 following Houdini HeightField Slump (defaults = old behaviour, bit-identical):

      debris_source  height (old): the whole height is loose material, the "thermal erosion" above.
                     layer / constant: Houdini Slump's semantics -- the height is **fixed bedrock**,
                     and only the debris layer slides on top of it. debris = debris_input layer x
                     debris_scale (layer), or debris_scale thick everywhere (constant, docs:
                     "constant when debris isn't connected"). Slope is computed on the bedrock + debris surface, and each step moves
                     no more than the debris currently in that cell -- once the debris has slid off and bedrock is exposed, it stops.
                     Total debris is conserved
      remove_debris  Remove Debris from Input Height: first subtract the debris from the height (use when the input height
                     already includes the debris)
      add_debris     Add Debris to Output Height: output height = bedrock + slid debris; when off
                     only the bedrock is output. In these two modes debris_layer outputs **the slid debris thickness**
                     (Houdini's debris output), not the height mode's "net deposition"
      slump_mode     smooth (old): deterministic; granular: the amount moved per step per cell is multiplied by a
                     [0,1) hash random number (determined by seed, pixel, step) -- the docs only say "slumps in chunks,
                     randomly"; this approach is our own. Still mass-conserving and never overshoots
    debris layer values are "height values" like the height, multiplied by strength to get world height. Houdini's
    Rainfall mode (with water-flow scouring) isn't implemented, see audit_notes.
    """
    if img is None:
        return CopImage()
    orig = img
    img, home, _ = AC.pick_backend(img, compute, 14)
    nb = int(neighbours)
    if nb not in NEIGHBOURS:
        raise ValueError(f"Neighbours must be one of {NEIGHBOURS}")
    ta = float(talus_angle)
    if not 0.0 <= ta < 90.0:
        raise ValueError("Talus Angle must be within [0, 90) degrees")
    r = float(rate)
    if not 0.0 <= r <= 1.0:
        raise ValueError("Rate must be between 0 and 1 (> 1 makes the donor lower than the receiver and oscillates)")
    it = int(iterations)
    if not 0 <= it <= 100000:
        raise ValueError("Iterations must be between 0 and 100000")
    s = float(strength)
    if s == 0.0:
        raise ValueError("Strength can't be 0 (the output has to be divided back to height values)")
    if slump_mode not in SLUMP_MODES:
        raise ValueError(f"Slump Mode must be one of {SLUMP_MODES}")
    if debris_source not in DEBRIS_SOURCES:
        raise ValueError(f"Debris Source must be one of {DEBRIS_SOURCES}")
    xp = img.backend
    W, H = img.xres, img.yres
    texel = _texel(world_size, W)
    tile = bool(tile)
    h0 = _height(img, layer, s)[:, :, 0]
    h = h0
    # debris modes: h is the sliding debris thickness d, bed is the fixed bedrock; in height mode bed = None and h is the height itself
    bed = None
    if debris_source != "height":
        if debris_source == "layer":
            dn = str(debris_input or "").strip()
            if not dn:
                raise ValueError("Debris Source = layer needs a Debris Input layer name")
            d0 = xp.maximum(img.need(dn)[:, :, 0], 0.0) * (float(debris_scale) * s)
        else:
            d0 = h0 * 0.0 + max(float(debris_scale), 0.0) * s
        bed = h0 - d0 if remove_debris else h0
        h = d0
    T = math.tan(math.radians(ta))
    dirs = _DIRS8 if nb == 8 else _DIRS8[:4]
    lim = [T * texel * math.hypot(dx, dy) for dx, dy in dirs]
    valid = []
    for dx, dy in dirs:
        if tile:
            valid.append(None)
            continue
        vx = ((np.arange(W) + dx >= 0) & (np.arange(W) + dx < W)) \
            .astype(np.float64)
        vy = ((np.arange(H) + dy >= 0) & (np.arange(H) + dy < H)) \
            .astype(np.float64)
        valid.append(xp.reshape(xp.asarray(vy), (H, 1))
                     * xp.reshape(xp.asarray(vx), (1, W)))
    soft = None
    hl = str(hardness_layer or "").strip()
    if hl:
        soft = 1.0 - xp.clip(img.need(hl)[:, :, 0], 0.0, 1.0)
    mode = "wrap" if tile else "clamp"
    zmode = "wrap" if tile else "black"

    def pad2(a, m):
        a3 = xp.reshape(a, (H, W, 1))
        return xp.pad_axis(xp.pad_axis(a3, 1, 0, m), 1, 1, m)[:, :, 0]

    granular = slump_mode == "granular"
    if granular:
        from .pattern import rnd
        pid = np.arange(H * W, dtype=np.int64)
    for step_i in range(it):
        surf = h if bed is None else bed + h
        p = pad2(surf, mode)
        exc = []
        for (dx, dy), L, v in zip(dirs, lim, valid):
            e = xp.maximum(surf - p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] - L,
                           0.0)
            exc.append(e if v is None else e * v)
        tot = exc[0]
        mx = exc[0]
        for e in exc[1:]:
            tot = tot + e
            mx = xp.maximum(mx, e)
        amount = mx * (r * 0.5)
        if soft is not None:
            amount = amount * soft
        if granular:
            # one [0,1) random factor per cell per step: it can only move less, so stability and conservation are unaffected
            xi = rnd(pid + step_i * (H * W), int(seed), 2).reshape(H, W)
            amount = amount * xp.asarray(xi)
        if bed is not None:
            # can only move the debris currently in this cell: once it has slid off, bedrock is exposed and it stops cutting down
            amount = xp.minimum(amount, h)
        ok = tot > 0.0
        inv = xp.where(ok, amount / xp.where(ok, tot, tot * 0.0 + 1.0),
                       tot * 0.0)
        gain = None
        for (dx, dy), e in zip(dirs, exc):
            q = pad2(e * inv, zmode)
            # neighbor p + d receives p's share: gain[y, x] = out[y - dy, x - dx]
            g = q[1 - dy:1 - dy + H, 1 - dx:1 - dx + W]
            gain = g if gain is None else gain + g
        h = h - tot * inv + gain
    out = _out(img, keep)
    dl = str(debris_layer or "").strip()
    if bed is not None:
        hout = bed + h if add_debris else bed
        out.set(str(out_layer).strip() or DEFAULT_LAYER,
                xp.reshape(hout * (1.0 / s), (H, W, 1)))
        if dl:
            out.set(dl, xp.reshape(h * (1.0 / s), (H, W, 1)))
    else:
        out.set(str(out_layer).strip() or DEFAULT_LAYER,
                xp.reshape(h * (1.0 / s), (H, W, 1)))
        if dl:
            out.set(dl, xp.reshape(xp.maximum(h - h0, 0.0) * (1.0 / s),
                                   (H, W, 1)))
    return AC.bring_back(orig, img, out, home) if keep else \
        AC.bring_back(CopImage(W, H), img, out, home)


# ═════════════════════════════════════════════════════ HeightField -> mesh
def _parse_attribs(spec):
    """'erosion mask Cd=C' -> [(dst, src)]."""
    out = []
    for tok in str(spec or "").split():
        if "=" in tok:
            d, s_ = tok.split("=", 1)
        else:
            d = s_ = tok
        if not d or not s_:
            raise ValueError(f"Can't parse attribute spec: '{tok}' (expected name or dst=src)")
        out.append((d, s_))
    return out


def to_mesh(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
            step=1, center=True, normals=True, attribs=""):
    """
    Height field -> Y-up mesh (Geometry). One point per **pixel center**, v toward -Z (see file header).

      step     take one point every step pixels (integer decimation, no resampling -- a point's value is
               that pixel's value, nothing interpolated)
      center   put the mesh center at the origin (Houdini's heightfield is also at the origin by default)
      normals  point normals come from the height map's gradient (the same operator as COP Height to Normal,
               tangent space -> world space), not averaged from the mesh faces afterwards
      attribs  bring other layers along as point attributes, space-separated; `dst=src` renames (e.g.
               `Cd=C erosion`)

    Points have uv (pixel centers, consistent with COP's sampling convention) and height (height value).
    """
    from ..core import Geometry, POINT
    if img is None:
        return Geometry()
    stp = int(step)
    if stp < 1:
        raise ValueError("Step must be at least 1")
    W, H = img.xres, img.yres
    texel = _texel(world_size, W)
    hv = _np(img.need(layer))[:, :, 0]
    ii = np.arange(0, H, stp)
    jj = np.arange(0, W, stp)
    if ii.size < 2 or jj.size < 2:
        raise ValueError(f"Only {jj.size}x{ii.size} points left after decimation, need at least 2x2"
                         f" -- lower Step")
    R, C = ii.size, jj.size
    I, J = np.meshgrid(ii, jj, indexing="ij")
    X = (J + 0.5) * texel
    Z = -(I + 0.5) * texel
    if center:
        X = X - W * texel * 0.5
        Z = Z + H * texel * 0.5
    Yh = hv[I, J] * float(strength)
    P = np.stack([X, Yh, Z], -1).reshape(-1, 3)
    r = np.arange(R - 1)[:, None]
    c = np.arange(C - 1)[None, :]
    a = r * C + c
    # a=(i,j) b=(i,j+1) c=(i+1,j+1) d=(i+1,j): b-a = +X, d-a = -Z, normal +Y
    faces = np.stack([a, a + 1, a + C + 1, a + C], -1).reshape(-1, 4)
    g = Geometry.from_mesh(P.astype(np.float32), faces.astype(np.int32))
    uv = np.stack([(J + 0.5) / W, (I + 0.5) / H], -1).reshape(-1, 2)
    g.set(POINT, "uv", uv.astype(np.float32))
    g.set(POINT, "height", hv[I, J].reshape(-1).astype(np.float32))
    if normals:
        n = _np(height_to_normal(img, layer, strength, world_size,
                                 keep=False).need("N"))[I, J]
        # tangent space (u, v, up) -> world (X, Y, Z) = (u, up, -v)
        Nw = np.stack([n[..., 0], n[..., 2], -n[..., 1]], -1).reshape(-1, 3)
        g.set(POINT, "N", Nw.astype(np.float32))
    for dst, src in _parse_attribs(attribs):
        a_ = _np(img.need(src))[I, J]
        a_ = a_.reshape(R * C, -1)
        g.set(POINT, dst, (a_[:, 0] if a_.shape[1] == 1 else a_)
              .astype(np.float32))
    return g
