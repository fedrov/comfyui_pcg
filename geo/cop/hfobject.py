"""
HeightField Mask by Object / HeightField Cutout by Object (pcg82).

Grid convention is the same as HeightField Project / HeightField to Mesh: the height field lies on the xz plane, centred, width
World Size; texel (i, j) has its centre at x = (j + 1/2)*texel - W*texel/2, z = -(i + 1/2)*texel +
H*texel/2; world height = layer value x Strength. Each texel casts two vertical rays (top-down and bottom-up)
to get the geometry's **top** y_top and **bottom** y_bot in that column (if a column has several layers, the outermost two are used).

━━ Mask by Object
    footprint   texels covered by the geometry (geometry exists in that column) = 1
    intersect   texels where the geometry passes through the ground: y_bot <= ground height <= y_top
    above       geometry entirely above the ground (overhanging parts)
    below       geometry entirely buried below the ground
Feather > 0: feather the mask edge outward by Feather world units (distance to the mask via exact EDT, smoothstep falloff);
Invert inverts it. Written to Out Layer (default mask).

━━ Cutout by Object
    carve   where the geometry passes through the ground, dig the ground down to its bottom: h <- min(h, y_bot) (only in columns with y_top >= ground;
            things buried entirely underground do not dig a hole down from the surface)
    fill    where the geometry sits on the ground, raise the ground to its top: h <- max(h, y_top) (only in columns with y_bot <= ground;
            overhanging things do not pull the ground up)
    both    carve then fill (the solid part of the geometry becomes terrain: remove the excess below it, fill what's missing above it)
Also writes an Out Layer_cut layer (modified texels = 1, handy for texture painting / scatter avoidance afterwards).
"""
from __future__ import annotations

import numpy as np

from .core import CopImage
from .pixel import getn, put
from ..core import POINT as POINT_

MASK_MODES = ("footprint", "intersect", "above", "below")
CUT_MODES = ("carve", "fill", "both")


def _columns(img, geo, world_size):
    """Top and bottom of the geometry in each texel's column (no geometry = nan)."""
    from ..spatial import tri_soup, ray_cast
    if geo is None or geo.npoints == 0:
        raise ValueError("needs a geometry input")
    tri = tri_soup(geo)[0]
    if not len(tri):
        raise ValueError("geometry has no primitives")
    W, H = img.xres, img.yres
    texel = float(world_size) / W
    J, I = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    X = (J + 0.5) * texel - W * texel * 0.5
    Z = -(I + 0.5) * texel + H * texel * 0.5
    Pg = np.asarray(geo.get(POINT_, "P"), np.float64)
    top = float(Pg[:, 1].max()) + 1.0
    bot = float(Pg[:, 1].min()) - 1.0
    n = X.size
    Od = np.stack([X.ravel(), np.full(n, top), Z.ravel()], -1)
    Ou = np.stack([X.ravel(), np.full(n, bot), Z.ravel()], -1)
    i1, t1, _ = ray_cast(Od, np.tile([0.0, -1.0, 0.0], (n, 1)), Pg, tri)
    i2, t2, _ = ray_cast(Ou, np.tile([0.0, 1.0, 0.0], (n, 1)), Pg, tri)
    yt = np.where(i1 >= 0, top - t1, np.nan).reshape(H, W)
    yb = np.where(i2 >= 0, bot + t2, np.nan).reshape(H, W)
    return yt, yb, texel


def _feather(m, feather_px):
    """Feather a binary mask outward: distance to the mask (texels) 0 -> 1, feather -> 0, smoothstep."""
    if not feather_px > 0 or not m.any():
        return m.astype(np.float64)
    from .sdf import distance_exact
    d = distance_exact(m)
    t = np.clip(1.0 - d / feather_px, 0.0, 1.0)
    return np.where(m, 1.0, t * t * (3 - 2 * t))


def mask_by_object(img, geo, layer="C", mode="footprint", strength=1.0,
                   world_size=1.0, feather=0.0, invert=False, out_layer="mask"):
    """Returns (image, report)."""
    if img is None:
        return CopImage(), {}
    if mode not in MASK_MODES:
        raise ValueError(f"Mode must be one of {MASK_MODES}")
    yt, yb, texel = _columns(img, geo, world_size)
    has = ~np.isnan(yt)
    if mode == "footprint":
        m = has
    else:
        h = getn(img, layer)[..., 0] * float(strength)
        with np.errstate(invalid="ignore"):
            if mode == "intersect":
                m = has & (yb <= h) & (yt >= h)
            elif mode == "above":
                m = has & (yb > h)
            else:
                m = has & (yt < h)
    v = _feather(m, float(feather) / texel)
    if invert:
        v = 1.0 - v
    out = img.copy()
    put(out, str(out_layer).strip() or "mask", v, img)
    return out, {"masked_texels": int(m.sum()), "covered_texels": int(has.sum())}


def cutout_by_object(img, geo, layer="C", mode="carve", strength=1.0,
                     world_size=1.0, out_layer=""):
    """Returns (image, report)."""
    if img is None:
        return CopImage(), {}
    if mode not in CUT_MODES:
        raise ValueError(f"Mode must be one of {CUT_MODES}")
    st = float(strength)
    if st == 0:
        raise ValueError("Strength cannot be 0")
    yt, yb, _ = _columns(img, geo, world_size)
    has = ~np.isnan(yt)
    h0 = getn(img, layer)[..., 0]
    h = h0 * st
    r = h.copy()
    with np.errstate(invalid="ignore"):
        if mode in ("carve", "both"):
            c = has & (yt >= h) & (yb < r)
            r = np.where(c, yb, r)
        if mode in ("fill", "both"):
            f = has & (yb <= r) & (yt > r)
            r = np.where(f, yt, r)
    changed = r != h
    name = str(out_layer).strip() or layer
    out = img.copy()
    put(out, name, np.where(changed, r / st, h0), img)
    put(out, name + "_cut", changed.astype(np.float64), img)
    return out, {"changed_texels": int(changed.sum()),
                 "removed_volume_px": float(np.clip(h - r, 0, None).sum() / st),
                 "added_volume_px": float(np.clip(r - h, 0, None).sum() / st)}
