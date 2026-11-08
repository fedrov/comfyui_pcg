"""
Height field / visualization / sequences (the other half of batch F): Light, HeightField Clip, HeightField
Project (including Transform 3D), HeightField Strata, Visualize (height / velocity),
Contact Sheet, Wipe, plus sequence operators (Reverse / Time Shift / Time Loop / Time
Blend / Sequence Blend).

Height units match the terrain chain: world height = value x Strength, pixel spacing = World Size / image width.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage
from .pattern import _base, rnd, _pix, render_text, _stamp_max
from .pixel import getn, put, names_of, _vec
from ..core import POINT as POINT_

LIGHT_TYPES = ("directional", "point")
CLIP_MODES = ("below", "above", "both")
PROJECT_MODES = ("replace", "max", "min", "add", "blend", "multiply")
# pcg100: the Project menu of Houdini HeightField Project (take the highest / lowest surface)
PROJECT_PICKS = ("maximum", "minimum")
VIS_MODES = ("height_ramp", "velocity_hsv", "velocity_lic", "velocity_arrows")
RAMPS = ("terrain", "gray", "viridis", "heat")
# pcg100: Houdini HeightField Visualize's Mode (first item = old behaviour: clamp to the ramp ends) and Tint by
VIS_RANGE_MODES = ("clamped", "periodic", "no_ramp")
VIS_TINTS = ("height", "color", "mask")
WIPES = ("linear", "radial", "dissolve", "crossfade")
SEQ_OPS = ("reverse", "shift", "loop", "retime", "blend")


# ═══════════════════════════════════════════════════════════ Lighting
def light(img, normal_layer="N", albedo_layer="", height_layer="",
          light_type="directional", azimuth=135.0, elevation=45.0,
          position="0.5 0.5", light_height=0.5, color="1 1 1",
          intensity=1.0, ambient=0.1, specular=0.0, shininess=32.0,
          shadows=False, strength=1.0, world_size=1.0, out_layer="lit"):
    """
    Light: lights the image with tangent-space normals (z up, the kind COP Height to Normal outputs).
      directional  Azimuth (the direction the light comes **from**, 0° = from +u, 90° = from +v) +
                   Elevation (elevation angle), same convention as Height to Shadow
      point        light at Light Height (as a fraction of image width) directly above Position (uv),
                   direction differs per pixel; no inverse-square falloff (given by Intensity)
    Diffuse max(N·L, 0), Blinn-Phong specular (view looking straight down), constant Ambient.
    With Shadows and a Height Layer: directional multiplies by Height to Shadow's illumination;
    point walks each pixel in a straight line toward the light (_point_shadow), and if terrain rises above the line of sight on the way, it's in shadow.
    (Before pcg85, point + shadows simply raised an error.)
    Result = Albedo x (Ambient + diffuse·color·intensity·lit) + specular·color·intensity·lit.
    """
    if img is None:
        return CopImage()
    if light_type not in LIGHT_TYPES:
        raise ValueError(f"Light Type must be one of {LIGHT_TYPES}")
    N = getn(img, normal_layer)[..., :3]
    N = N / np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-12)
    W, H = img.xres, img.yres
    if light_type == "directional":
        az, el = math.radians(float(azimuth)), math.radians(float(elevation))
        Ld = np.array([math.cos(el) * math.cos(az),
                       math.cos(el) * math.sin(az), math.sin(el)])
        L = np.broadcast_to(Ld, N.shape)
    else:
        u, v = _pix(W, H)
        pu, pv = _vec(position, 2)
        L = np.stack([(pu - u), (pv - v) * H / W,
                      np.full_like(u, float(light_height))], -1)
        L = L / np.maximum(np.linalg.norm(L, axis=-1, keepdims=True), 1e-12)
    ndl = np.clip((N * L).sum(-1), 0, None)
    Hv = L + np.array([0.0, 0.0, 1.0])
    Hv = Hv / np.maximum(np.linalg.norm(Hv, axis=-1, keepdims=True), 1e-12)
    spec = np.clip((N * Hv).sum(-1), 0, None) ** float(shininess) * \
        float(specular) * (ndl > 0)
    lit = np.ones((H, W))
    if shadows and str(height_layer).strip():
        if light_type == "directional":
            from .heightmap import height_to_shadow
            sh = height_to_shadow(img, height_layer, strength, world_size,
                                  azimuth, elevation, invert=True,
                                  out_layer="_sh", keep=False)
            lit = getn(sh, "_sh")[..., 0]
        else:
            lit = _point_shadow(img, height_layer, strength, world_size,
                                position, light_height)
    col = _vec(color, 3) * float(intensity)
    alb = getn(img, albedo_layer)[..., :3] if str(albedo_layer).strip() \
        else np.ones((H, W, 3))
    if alb.shape[2] == 1:
        alb = np.repeat(alb, 3, -1)
    r = alb * (float(ambient) + (ndl * lit)[..., None] * col) \
        + (spec * lit)[..., None] * col
    out = img.copy()
    return put(out, str(out_layer).strip() or "lit", r, img)


def _point_shadow(img, height_layer, strength, world_size, position,
                  light_height, max_steps=512):
    """
    Point light illumination (1 = lit, 0 = in shadow), (H,W).

    Units unified to "image width = 1": pixel (u, v·H/W), terrain height height·Strength / World Size
    (the same world scale directional uses via Height to Shadow), light at
    (Position, Light Height) -- the same point as the L used for lighting above.
    Each pixel walks toward the light in the horizontal plane with steps of about one pixel (step cap max_steps; distant pixels
    take bigger steps); the line-of-sight height at step t is interpolated linearly between the pixel and the light, and if terrain rises above it at any step
    the pixel is in shadow. "Just grazing" (terrain == line of sight) counts as lit -- it only happens when the light skims the surface with N·L = 0,
    so either way the output is the same.

    Terrain at sample points is **bilinearly** interpolated (pixel centers as grid points). Nearest-pixel sampling causes
    shadow acne: when a low point light illuminates a slope facing down toward it, the line of sight is only slightly gentler than the terrain,
    and stair-stepped terrain pops up in the first few cells to block itself, blotching the whole slope black. Bilinear is exact on
    linear slopes, so this self-occlusion disappears (pinned in the tests).
    """
    ws = float(world_size)
    if not ws > 0.0:
        raise ValueError(f"World Size must be > 0, got {world_size}")
    W, H = img.xres, img.yres
    z = getn(img, height_layer)[..., 0] * float(strength) / ws
    u, v = _pix(W, H)
    y = v * H / W
    pu, pv = _vec(position, 2)
    lx, ly, lz = float(pu), float(pv) * H / W, float(light_height)
    dist_px = np.hypot(lx - u, ly - y) * W
    # each pixel walks by its own distance to the light with steps of about one cell (capped at max_steps); pixels already judged
    # in shadow or finished are removed from the active set -- each step only gathers the undecided ones.
    # 512², random undulation, light at the center: a uniform step count for the whole image takes 5.6 s, this way 1.5 s; flat ground with the light at the edge
    # (no pixel drops out early) 4.7 s
    f32 = np.float32
    nk = np.minimum(max_steps, np.maximum(1, np.ceil(dist_px))).astype(np.int64).ravel()
    zr = z.astype(f32).ravel()
    x0 = (u * W - 0.5).astype(f32).ravel()
    y0 = (y * W - 0.5).astype(f32).ravel()
    dx = ((lx - u) * W).astype(f32).ravel()
    dy = ((ly - y) * W).astype(f32).ravel()
    dz = (f32(lz) - zr).astype(f32)
    shadow = np.zeros(H * W, bool)
    act = np.arange(H * W)
    k = 0
    while len(act):
        k += 1
        act = act[nk[act] >= k]
        t = (k / (nk[act] + 1)).astype(f32)
        # sample point in "pixel centers as grid points" coordinates: column = u·W - 0.5, row = v·H - 0.5 = y·W - 0.5
        fx = np.clip(x0[act] + dx[act] * t, 0, W - 1)
        fy = np.clip(y0[act] + dy[act] * t, 0, H - 1)
        j0, i0 = fx.astype(np.int64), fy.astype(np.int64)      # already >= 0, so truncation = floor
        ax, ay = fx - j0, fy - i0          # = 0 when clamped to the last cell, j1 / i1 clamp back to the same cell
        j1, i1 = np.minimum(j0 + 1, W - 1), np.minimum(i0 + 1, H - 1)
        r0, r1 = i0 * W, i1 * W
        top = zr[r0 + j0] + (zr[r0 + j1] - zr[r0 + j0]) * ax
        bot = zr[r1 + j0] + (zr[r1 + j1] - zr[r1 + j0]) * ax
        hit = top + (bot - top) * ay > zr[act] + dz[act] * t
        shadow[act[hit]] = True
        act = act[~hit]                    # affects speed only: pixels judged in shadow needn't keep walking
    lit = np.where(shadow, 0.0, 1.0).reshape(H, W)
    return lit


# ═══════════════════════════════════════════════════════════ Height field
def _knee(x, lo, s):
    """
    Soft max(x, lo): identity for x >= lo + s, equals lo for x <= lo - s, quadratic in between
    lo + (x - lo + s)²/(4s) -- value and slope match at both ends (C¹). s = 0 is a hard clamp.
    """
    if s <= 0:
        return np.maximum(x, lo)
    return np.where(x >= lo + s, x, np.where(
        x <= lo - s, lo, lo + (x - lo + s) ** 2 / (4 * s)))


def hf_clip(img, layer="height", mode="both", min=0.0, max=1.0,  # noqa: A002
            softness=0.0, mask_layer="", out_layer=""):
    """
    HeightField Clip: clamps height into [Min, Max]. Softness > 0 uses a smooth knee (quadratic
    transition, bit-identical above Min + Softness / below Max - Softness, C¹ continuous).
    If Mask Layer is given, blends by it. Also outputs out_layer_clipped: the amount changed (where > 0 is where it was
    cut / raised).
    """
    if img is None:
        return CopImage()
    if mode not in CLIP_MODES:
        raise ValueError(f"Mode must be one of {CLIP_MODES}")
    h = getn(img, layer)[..., 0]
    lo, hi = float(min), float(max)
    s = float(softness)
    r = h.copy()

    if mode in ("below", "both"):
        r = _knee(r, lo, s)
    if mode in ("above", "both"):
        r = -_knee(-r, -hi, s)
    ml = str(mask_layer).strip()
    if ml:
        m = np.clip(getn(img, ml)[..., 0], 0, 1)
        r = h * (1 - m) + r * m
    name = str(out_layer).strip() or layer
    out = img.copy()
    put(out, name, r, img)
    put(out, name + "_clipped", np.abs(r - h), img)
    return out


def hf_project(img, geo=None, layer="height", mode="max", strength=1.0,
               world_size=1.0, translate="0 0 0", rotate="0 0 0",
               scale="1 1 1", fill_value=0.0, out_layer="",
               project="maximum", max_height=0.0, mask=1.0, mask_layer="",
               projection_only=False, hitmask_layer=""):
    """
    HeightField Project / HeightField Transform 3D.
      With geo: rays are shot toward -Y from directly above each texel; the Y of the highest hit ÷ Strength
      is the projected height, merged into layer by Mode (replace / max / min / add); texels with no hit
      are unchanged (replace fills Fill Value). The mesh is the terrain chain's HeightField to
      Mesh convention (xz, world, centered).
      Without geo: Transform 3D -- treats the height field itself as a mesh, transforms it by Translate / Rotate (xyz
      Euler, degrees) / Scale, then projects back onto the same grid (max). So tilting, raising and rotating
      a piece of terrain are real 3D transforms, not image-space distortions.
    Returns (image, report: number of hit texels).

    Added in pcg100 following Houdini HeightField Project (defaults = old behaviour, bit-identical):
      project          maximum (old: first intersection from the top = highest surface) / minimum (the farthest intersection on the same
                       ray = lowest surface, Houdini's Minimum Height)
      max_height       Max Projection Height; when > 0 only the geometry with |height value| <= it is projected:
                       rays start at +max_height and travel at most to -max_height. In **height values**
                       (same units as the output, world = value x Strength); 0 = unlimited (our own choice)
      modes appended   blend (Houdini Blend: hit areas are replaced by the projected height, misses unchanged --
                       unlike replace, Fill Value isn't filled), multiply (at hits base x projection)
      mask / mask_layer  Houdini's Mask: blends between the original height and the result, mask multiplied onto the layer
      projection_only  Output Projection Only: only the projected height (misses filled with Fill Value),
                       not composited with the original height and not through the mask
      hitmask_layer    if a name is given, also outputs hitmask (hit 1, miss 0)
    Without geo (Transform 3D), project / max_height / mask / projection only / hitmask work the same way.
    """
    if img is None:
        return CopImage(), {}
    if mode not in PROJECT_MODES:
        raise ValueError(f"Mode must be one of {PROJECT_MODES}")
    if project not in PROJECT_PICKS:
        raise ValueError(f"Project must be one of {PROJECT_PICKS}")
    mh = float(max_height)
    if mh < 0:
        raise ValueError("Max Projection Height can't be negative (0 = unlimited)")
    from .terrain import to_mesh
    from ..spatial import tri_soup, ray_cast
    W, H = img.xres, img.yres
    base = getn(img, layer)[..., 0] if layer in img else np.zeros((H, W))
    st = float(strength) if float(strength) != 0 else 1.0
    if geo is None:
        g = to_mesh(img, layer, strength, world_size, 1, True, False)
        P = np.asarray(g.get(POINT_, "P"), np.float64)
        from .pixel import _euler
        R = _euler(*_vec(rotate, 3))
        c = P.mean(0)
        P = ((P - c) * _vec(scale, 3)) @ R.T + c + _vec(translate, 3)
        g.set(POINT_, "P", P.astype(np.float32))
        geo = g
        mode_eff = "replace"
    else:
        mode_eff = mode
    Pg = np.asarray(geo.get(POINT_, "P"), np.float64)
    tri, _, _ = tri_soup(geo)
    texel = float(world_size) / W
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    X = (J + 0.5) * texel - W * texel * 0.5
    Z = -(I + 0.5) * texel + H * texel * 0.5
    if mh > 0:
        # rays start at +limit and travel only 2·limit: geometry beyond the limit (above or below) can't be hit
        top = mh * abs(st)
        md = 2.0 * top
    else:
        top = float(Pg[:, 1].max()) + 1.0
        md = 0.0
    O = np.stack([X.ravel(), np.full(X.size, top), Z.ravel()], -1)
    D = np.tile(np.array([0.0, -1.0, 0.0]), (X.size, 1))
    hi_i, hi_t, _ = ray_cast(O, D, Pg, tri, farthest=(project == "minimum"),
                             max_dist=md)
    got = (hi_i >= 0).reshape(H, W)
    yv = (top - hi_t).reshape(H, W) / st
    fill = float(fill_value)
    if projection_only:
        r = np.where(got, yv, fill)
    else:
        if mode_eff == "replace":
            r = np.where(got, yv, fill)
        elif mode_eff == "max":
            r = np.where(got, np.maximum(base, yv), base)
        elif mode_eff == "min":
            r = np.where(got, np.minimum(base, yv), base)
        elif mode_eff == "add":
            r = np.where(got, base + yv, base)
        elif mode_eff == "blend":
            r = np.where(got, yv, base)
        else:
            r = np.where(got, base * yv, base)
        mk = float(mask)
        ml = str(mask_layer or "").strip()
        if ml or mk != 1.0:
            w = mk * (np.clip(getn(img, ml)[..., 0], 0, 1) if ml else 1.0)
            r = base + (r - base) * w
    out = img.copy()
    put(out, str(out_layer).strip() or layer, r, img)
    hl = str(hitmask_layer or "").strip()
    if hl:
        put(out, hl, got.astype(np.float64), img)
    return out, {"hit_texels": int(got.sum())}


def strata(img, layer="height", spacing=0.1, strength=0.8, sharpness=0.7,
           tilt="0 0", noise_amount=0.0, noise_frequency=4.0,
           hardness_random=0.5, seed=0, out_layer="", strata_offset=0.0,
           mask_layer="", strata_only=False):
    """
    HeightField Strata: rock strata. Unlike Terrace, the bedding planes are **not horizontal**: layer coordinate
    s = height + Tilt·(u, v) + noise, layer number = floor(s / Spacing). Each layer gets a random
    "hardness" (Hardness Random controls how much layers differ); hard layers have flatter treads and steeper risers (exponent
    p = 1/(1 - sharpness·hardness)). The result is blended back into the original height by Strength:

        h' = h + Strength · (Spacing·(layer + f^p) - s)

    Strength 0 is identity; with Tilt 0, noise 0 and non-random hardness it's exactly Terrace (compared pixel by pixel
    in tests). Also outputs out_layer_id (layer number).

    Added in pcg100 following Houdini HeightField Strata (defaults = old behaviour, bit-identical):
      strata_offset  Strata Offset: shifts all layer boundaries (height values); boundaries at Offset + k·Spacing
      mask_layer     Houdini's mask input: blend-back amount = Strength x mask (0-1). Houdini's
                     Mask parameter is our Strength
      strata_only    Output Strata Only: not composited with the height, only the strata displacement is output
                     strata = Spacing·(layer + f^p) - s (added to the height it gives the Strength 1
                     result; not multiplied by Strength, not masked)
    """
    if img is None:
        return CopImage()
    h = getn(img, layer)[..., 0]
    W, H = img.xres, img.yres
    u, v = _pix(W, H)
    tx, ty = _vec(tilt, 2)
    s = h + tx * u + ty * v
    if float(noise_amount) != 0:
        from .noise import simplex
        from . import backend as bk
        n = np.asarray(simplex(bk.EXACT, u * float(noise_frequency),
                               v * float(noise_frequency) * H / W,
                               np.zeros_like(u), seed=int(seed)))
        s = s + float(noise_amount) * n
    sp = float(spacing)
    if not sp > 0:
        raise ValueError("Spacing must be > 0")
    so = float(strata_offset)
    q = s / sp if so == 0.0 else (s - so) / sp
    k = np.floor(q)
    f = q - k
    hard = 1.0 - float(hardness_random) * rnd(k.astype(np.int64), seed, 3)
    sh = np.clip(float(sharpness) * hard, 0.0, 0.999)
    p = 1.0 / (1.0 - sh)
    target = sp * (k + np.power(f, p))
    if so != 0.0:
        target = target + so
    if strata_only:
        r = target - s
    else:
        ml = str(mask_layer or "").strip()
        if ml:
            w = np.clip(getn(img, ml)[..., 0], 0.0, 1.0)
            r = h + float(strength) * w * (target - s)
        else:
            r = h + float(strength) * (target - s)
    out = img.copy()
    name = str(out_layer).strip() or layer
    put(out, name, r, img)
    put(out, name + "_id", k, img)
    return out


# ═══════════════════════════════════════════════════════════ Visualization
_RAMP_PTS = {
    "terrain": [(0.0, (0.10, 0.25, 0.55)), (0.30, (0.20, 0.55, 0.75)),
                (0.34, (0.85, 0.80, 0.55)), (0.45, (0.35, 0.60, 0.25)),
                (0.70, (0.45, 0.40, 0.30)), (0.88, (0.60, 0.58, 0.55)),
                (1.0, (0.97, 0.97, 0.98))],
    "gray": [(0.0, (0, 0, 0)), (1.0, (1, 1, 1))],
    "viridis": [(0.0, (0.267, 0.005, 0.329)), (0.25, (0.229, 0.322, 0.546)),
                (0.5, (0.128, 0.567, 0.551)), (0.75, (0.369, 0.789, 0.383)),
                (1.0, (0.993, 0.906, 0.144))],
    "heat": [(0.0, (0, 0, 0)), (0.35, (0.8, 0.1, 0.0)), (0.7, (1.0, 0.8, 0.0)),
             (1.0, (1, 1, 1))],
}


def ramp(t, name):
    pts = _RAMP_PTS[name]
    xs = np.array([p[0] for p in pts])
    cs = np.array([p[1] for p in pts], np.float64)
    t = np.clip(t, 0, 1)
    return np.stack([np.interp(t, xs, cs[:, c]) for c in range(3)], -1)


def _hsv(h, s, v):
    from .pattern import _hsv as hs
    return hs(h, s, v)


def visualize(img, layer="height", mode="height_ramp", ramp_name="terrain",
              lo=0.0, hi=0.0, contour_interval=0.0, hillshade=0.5,
              lic_length=20, arrow_spacing=16, scale=1.0, seed=0,
              out_layer="vis", range_mode="clamped", tint_by="height",
              tint_layer=""):
    """
    HeightField Visualize / Visualize Velocity.
      height_ramp      height through a color ramp by [Lo, Hi] (both 0 = the image's min/max), optionally overlaid with
                       hillshade (Hillshade weight) and contour lines (Contour Interval > 0)
      velocity_hsv     2-channel velocity: hue = direction (+u is red, counterclockwise), value =
                       |v| x Scale (clamped to 1)
      velocity_lic     line integral convolution (Cabral-Leedom 1993): white noise integrated LIC Length steps
                       forward and backward along streamlines and averaged -- texture streaks along the flow
      velocity_arrows  one arrow every Arrow Spacing pixels, length ∝ |v| x Scale

    Added in pcg100 following Houdini HeightField Visualize (height_ramp only; defaults = old behaviour):
      range_mode  Houdini's Mode: clamped (old, Clamped Ramp: outside [Lo, Hi] takes the ramp
                  ends) / periodic (Periodic Ramp: t modulo 1, the ramp cycles) / no_ramp
                  (No Ramp: no ramp, outputs gray t directly, **unclamped**, extrapolating beyond the range --
                  so this mode doesn't clip to [0,1] at the end either)
      tint_by     Tint by: height (old) / mask (ramp applied to channel 0 of tint_layer;
                  when Lo / Hi are both 0 its own min/max is used) / color (tint_layer used directly as color,
                  no ramp, ignoring Range / Mode). Hillshade and contours always come from the height layer
    """
    if img is None:
        return CopImage()
    if mode not in VIS_MODES:
        raise ValueError(f"Mode must be one of {VIS_MODES}")
    a = getn(img, layer)
    H, W = a.shape[:2]
    out = img.copy()
    name = str(out_layer).strip() or "vis"
    if mode == "height_ramp":
        if ramp_name not in RAMPS:
            raise ValueError(f"Ramp must be one of {RAMPS}")
        if range_mode not in VIS_RANGE_MODES:
            raise ValueError(f"Mode must be one of {VIS_RANGE_MODES}")
        if tint_by not in VIS_TINTS:
            raise ValueError(f"Tint by must be one of {VIS_TINTS}")
        h = a[..., 0]
        tl = str(tint_layer or "").strip()
        if tint_by != "height" and not tl:
            raise ValueError("Tint by = color / mask needs a Tint Layer")
        tv = h if tint_by == "height" else getn(img, tl)[..., 0]
        l_, h_ = float(lo), float(hi)
        if l_ == 0 and h_ == 0:
            l_, h_ = float(tv.min()), float(tv.max())
        if tint_by == "height":
            # the hillshade gradient is always normalized by the height range (old behaviour), unchanged when Tint switches layers
            hl_, hh_ = l_, h_
        else:
            hl_, hh_ = float(h.min()), float(h.max())
        t = (tv - l_) / max(h_ - l_, 1e-12)
        if tint_by == "color":
            col = getn(img, tl)[..., :3]
            if col.shape[2] == 1:
                col = np.repeat(col, 3, -1)
            col = col.astype(np.float64)
        elif range_mode == "no_ramp":
            col = np.repeat(t[..., None], 3, -1)
        elif range_mode == "periodic":
            col = ramp(np.mod(t, 1.0), ramp_name)
        else:
            col = ramp(t, ramp_name)
        if float(hillshade) > 0:
            p = np.pad(h, 1, mode="edge")
            gx = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5 / max(hh_ - hl_, 1e-12) * W
            gy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5 / max(hh_ - hl_, 1e-12) * W
            n = np.stack([-gx * 0.02, -gy * 0.02, np.ones_like(gx)], -1)
            n /= np.linalg.norm(n, axis=-1, keepdims=True)
            L = np.array([-0.5, 0.5, 0.707])
            L /= np.linalg.norm(L)
            sh = np.clip((n * L).sum(-1), 0, 1)
            col = col * ((1 - float(hillshade)) + float(hillshade) * sh
                         / L[2])[..., None]
        ci = float(contour_interval)
        if ci > 0:
            from .fx import contour
            c = getn(contour(CopImage(W, H, {"h": h[..., None]}), "h", ci),
                     "contour")[..., 0]
            col = col * (1 - 0.6 * c[..., None])
        if range_mode == "no_ramp" and tint_by != "color":
            return put(out, name, col, img)
        return put(out, name, np.clip(col, 0, 1), img)
    if a.shape[2] < 2:
        raise ValueError("Velocity visualization needs a 2-channel layer")
    vx, vy = a[..., 0], a[..., 1]
    mag = np.hypot(vx, vy)
    if mode == "velocity_hsv":
        hue = np.mod(np.arctan2(vy, vx) / (2 * math.pi), 1.0)
        col = _hsv(hue, np.ones_like(hue), np.clip(mag * float(scale), 0, 1))
        return put(out, name, col, img)
    if mode == "velocity_lic":
        k = np.arange(H * W).reshape(H, W)
        noise = rnd(k, seed, 1)
        ux = vx / np.maximum(mag, 1e-12)
        uy = vy / np.maximum(mag, 1e-12)
        from .filters import sample
        acc = noise.copy()
        cnt = np.ones((H, W))
        J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                           np.arange(H, dtype=np.float64))
        for sgn in (1.0, -1.0):
            x, y = J.copy(), I.copy()
            for _ in range(int(lic_length)):
                d = sample(np.stack([ux, uy], -1), (x + 0.5) / W,
                           (y + 0.5) / H, "clamp")
                x = x + sgn * d[..., 0]
                y = y + sgn * d[..., 1]
                inside = (x >= 0) & (x <= W - 1) & (y >= 0) & (y <= H - 1)
                val = sample(noise[..., None], (x + 0.5) / W, (y + 0.5) / H,
                             "clamp")[..., 0]
                acc += np.where(inside, val, 0.0)
                cnt += inside
        lic = acc / cnt
        lic = (lic - lic.mean()) / max(lic.std(), 1e-12) * 0.18 + 0.5
        return put(out, name, np.clip(lic, 0, 1), img)
    # arrows
    canvas = np.zeros((H, W))
    sp = max(2, int(arrow_spacing))
    Jc, Ic = np.meshgrid(np.arange(W, dtype=np.float64),
                         np.arange(H, dtype=np.float64))

    def _sd(cv, ax, ay, bx, by, wdt):
        # anti-aliased line segment (1 pixel wide), computed only within its bounding box
        from .geoimg import _seg_dist
        x0 = int(max(math.floor(min(ax, bx) - 2), 0))
        x1 = int(min(math.ceil(max(ax, bx) + 2) + 1, W))
        y0 = int(max(math.floor(min(ay, by) - 2), 0))
        y1 = int(min(math.ceil(max(ay, by) + 2) + 1, H))
        if x0 >= x1 or y0 >= y1:
            return
        d, _ = _seg_dist(Jc[y0:y1, x0:x1], Ic[y0:y1, x0:x1], ax, ay, bx, by)
        sl = (slice(y0, y1), slice(x0, x1))
        cv[sl] = np.maximum(cv[sl], np.clip(wdt * 0.5 - d + 0.5, 0, 1))
    for i0 in range(sp // 2, H, sp):
        for j0 in range(sp // 2, W, sp):
            dx, dy = vx[i0, j0] * float(scale), vy[i0, j0] * float(scale)
            ln = math.hypot(dx, dy)
            if ln < 1e-6:
                continue
            if ln > sp * 0.9:
                dx, dy = dx / ln * sp * 0.9, dy / ln * sp * 0.9
                ln = sp * 0.9
            ax, ay = j0 - dx / 2, i0 - dy / 2
            bx, by = j0 + dx / 2, i0 + dy / 2
            hx, hy = -dx / ln, -dy / ln
            segs = [(ax, ay, bx, by),
                    (bx, by, bx + (hx * 0.866 - hy * 0.5) * ln * 0.35,
                     by + (hx * 0.5 + hy * 0.866) * ln * 0.35),
                    (bx, by, bx + (hx * 0.866 + hy * 0.5) * ln * 0.35,
                     by + (-hx * 0.5 + hy * 0.866) * ln * 0.35)]
            for s_ in segs:
                _sd(canvas, *s_, 1.0)
    return put(out, name, canvas, img)


# ═══════════════════════════════════════════════════════════ Contact sheet / transitions
def contact_sheet(seq, layer="C", columns=0, padding=4, background="0 0 0",
                  labels=True, font="", label_size=0, scale=1.0):
    """
    Contact Sheet: lays out each frame (layer Layer) of a sequence in a grid. Columns 0 = chosen automatically to be roughly square.
    Frames may differ in resolution; all are scaled uniformly to the first frame's size x Scale (filters.resize).
    Labels writes the frame number in the top-left corner.
    """
    if not seq:
        raise ValueError("The sequence is empty")
    from .filters import resize
    n = len(seq)
    cols = int(columns) or int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    fw = max(1, int(round(seq[0].xres * float(scale))))
    fh = max(1, int(round(seq[0].yres * float(scale))))
    frames = []
    C = 1
    for im in seq:
        sub = CopImage(im.xres, im.yres, {"x": getn(im, layer)})
        if (im.xres, im.yres) != (fw, fh):
            sub = resize(sub, fw, fh)
        a = getn(sub, "x")
        C = max(C, a.shape[2])
        frames.append(a)
    pad = int(padding)
    Wt = cols * fw + (cols + 1) * pad
    Ht = rows * fh + (rows + 1) * pad
    bg = _vec(background, max(C, 1))
    sheet = np.empty((Ht, Wt, C))
    sheet[:] = bg[:C]
    for k, a in enumerate(frames):
        r, c = divmod(k, cols)
        if a.shape[2] < C:
            a = np.concatenate([a, np.repeat(a[..., -1:], C - a.shape[2],
                                             -1)], -1)
        x0 = pad + c * (fw + pad)
        # the first row is at the **top**: v points up, so row numbers count down from the top
        y0 = Ht - (pad + (r + 1) * fh + r * pad)
        sheet[y0:y0 + fh, x0:x0 + fw] = a
        if labels:
            sz = int(label_size) or max(8, fh // 10)
            g = render_text(str(k), sz, font)[::-1]
            m = np.zeros((Ht, Wt))
            _stamp_max(m, g, x0 + 2, y0 + fh - g.shape[0] - 2)
            sheet = sheet * (1 - m[..., None]) + m[..., None]
    return CopImage(Wt, Ht, {layer: sheet})


def wipe(a, b, layer="C", mode="linear", t=0.5, angle=0.0, softness=0.05,
         center="0.5 0.5", seed=0, out_layer=""):
    """
    Wipe: A -> B transition, t = 0 all A, 1 all B.
      linear     pushes an edge along Angle (softness is the transition band width, uv)
      radial     a circle expanding from Center
      dissolve   dissolves by a per-pixel random threshold (larger softness is "blurrier")
      crossfade  plain blend
    At t = 0 / 1 both ends are bit-exactly A / B. If B's resolution differs from A's it's resampled first.
    """
    if a is None or b is None:
        raise ValueError("Both images A and B must be connected")
    if mode not in WIPES:
        raise ValueError(f"Mode must be one of {WIPES}")
    from .filters import resize
    A = getn(a, layer)
    bb = b if (b.xres, b.yres) == (a.xres, a.yres) else resize(
        CopImage(b.xres, b.yres, {layer: getn(b, layer)}), a.xres, a.yres)
    B = getn(bb, layer)
    C = min(A.shape[2], B.shape[2])
    A, B = A[..., :C], B[..., :C]
    W, H = a.xres, a.yres
    u, v = _pix(W, H)
    tt = float(t)
    s = max(float(softness), 1e-6)
    if mode == "crossfade":
        m = np.full((H, W), tt)
    elif mode == "linear":
        th = math.radians(float(angle))
        d = (u - 0.5) * math.cos(th) + (v - 0.5) * math.sin(th) * H / W
        span = 0.5 * (abs(math.cos(th)) + abs(math.sin(th)) * H / W)
        # the edge travels from -span - s to +span + s: all A at t = 0, all B at t = 1
        edge = -span - s + tt * (2 * span + 2 * s)
        m = np.clip((edge - d) / s + 0.5, 0, 1)
    elif mode == "radial":
        cu, cv = _vec(center, 2)
        r = np.hypot(u - cu, (v - cv) * H / W)
        rmax = float(np.sqrt(max(cu, 1 - cu) ** 2 + (max(cv, 1 - cv) * H / W)
                             ** 2))
        edge = -s + tt * (rmax + 2 * s)
        m = np.clip((edge - r) / s + 0.5, 0, 1)
    else:
        k = np.arange(H * W).reshape(H, W)
        thr = rnd(k, seed, 1)
        m = np.clip((tt * (1 + s) - thr) / s, 0, 1)
    if tt <= 0:
        m = np.zeros((H, W))
    elif tt >= 1:
        m = np.ones((H, W))
    out = a.copy()
    return put(out, str(out_layer).strip() or layer,
               A * (1 - m[..., None]) + B * m[..., None], a)


# ═══════════════════════════════════════════════════════════ Sequences
def _lerp_img(p, q, t):
    """Per-layer linear interpolation between two frames (only layers present in both are interpolated; a layer in only one takes the nearer frame)."""
    out = (p if t < 0.5 else q).copy()
    for n in p.names:
        if n in q and getn(p, n).shape == getn(q, n).shape:
            put(out, n, getn(p, n) * (1 - t) + getn(q, n) * t,
                p if t < 0.5 else q)
    return out


def seq_ops(seq, op="reverse", offset=0, edge="hold", frames=0, blend=4,
            other=None, weight=0.5):
    """
    Reverse / Time Shift / Time Loop / Time Blend / Sequence Blend.
      reverse  plays backward
      shift    moves everything by Offset frames (positive = later); vacated frames follow Edge: hold (extend the first / last
               frame) / loop (cycle)
      loop     makes a seamless loop: the last Blend frames cross-fade with the beginning, outputting N - Blend frames --
               frame N-Blend-1 continues seamlessly into frame 0
      retime   resamples to Frames frames (linear interpolation between adjacent frames, Time Blend). First and last frames are
               bit-identical
      blend    blends frame by frame with the other sequence by Weight (Sequence Blend); frame count is the shorter
    """
    if not seq:
        raise ValueError("The sequence is empty")
    if op not in SEQ_OPS:
        raise ValueError(f"Op must be one of {SEQ_OPS}")
    n = len(seq)
    if op == "reverse":
        return list(seq[::-1])
    if op == "shift":
        o = int(offset)
        if edge not in ("hold", "loop"):
            raise ValueError("Edge must be one of hold / loop")
        return [seq[(i - o) % n] if edge == "loop" else
                seq[min(max(i - o, 0), n - 1)] for i in range(n)]
    if op == "loop":
        b = int(blend)
        if not 0 < b < n:
            raise ValueError(f"Blend must be between 1 and {n - 1}")
        m = n - b
        res = list(seq[:m])
        for i in range(b):
            # output frame i = blend of original frame i and original frame m + i; at i = 0 it's almost all tail
            w = (i + 1) / (b + 1)
            res[i] = _lerp_img(seq[m + i], seq[i], w)
        return res
    if op == "retime":
        f = int(frames)
        if f < 1:
            raise ValueError("Frames must be at least 1")
        if f == 1:
            return [seq[0]]
        res = []
        for k in range(f):
            x = k * (n - 1) / (f - 1)
            i0 = int(math.floor(x))
            t = x - i0
            if i0 >= n - 1:
                res.append(seq[n - 1])
            elif t == 0:
                res.append(seq[i0])
            else:
                res.append(_lerp_img(seq[i0], seq[i0 + 1], t))
        return res
    if not other:
        raise ValueError("blend needs a second sequence connected")
    m = min(n, len(other))
    return [_lerp_img(seq[i], other[i], float(weight)) for i in range(m)]

