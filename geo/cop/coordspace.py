"""
Copernicus coordinate spaces (pcg100 c6): conversion between Texture / Image / Pixel (/ Buffer / World),
plus the Border · Shift · Cycles post-processing shared by UV Map / Position Map.

Our CopImage only has a resolution, not Houdini's metadata (data window ≠ display window,
pixel scale, the layer's own camera / world transform). So the conventions here are:
  · data window = display window = the whole image (Source Data / Display give the same result)
  · Buffer = Pixel (no pixel scale)
  · World = Image (no camera; equivalent to the default orthographic camera looking at a [−1,1] image on the z = 0 plane)
All of this is written in the docstrings of the nodes that use it, and hinted on the panels too.

Space definitions (consistent with the plugin's existing image space convention, see transform.crop_window / fx.mirror):
  texture  bottom-left 0, top-right 1, each axis normalized separately (pixels of non-square images are not square)
  image    origin at the image centre, −1 ... 1 spans the **long side**, short side proportional (pixels are square)
  pixel    the centre of the first bottom-left pixel is (0.5, 0.5), +1 per pixel right / up
"""
from __future__ import annotations

import numpy as np

SPACES = ("texture", "image", "pixel")
BORDERS = ("clamp", "mirror", "wrap", "extend")


def tex_to_space(space, u, v, W, H):
    """texture coordinates → space coordinates (affine, the two axes independent)."""
    if space == "texture":
        return u, v
    if space == "image":
        L = float(max(W, H))
        return (u - 0.5) * (2.0 * W / L), (v - 0.5) * (2.0 * H / L)
    if space == "pixel":
        return u * W, v * H
    raise ValueError(f"UV Space must be one of {SPACES}")


def space_scale(space, W, H):
    """Linear part (diagonal) of tex_to_space: d(space)/d(texture)."""
    if space == "texture":
        return 1.0, 1.0
    if space == "image":
        L = float(max(W, H))
        return 2.0 * W / L, 2.0 * H / L
    return float(W), float(H)


def canonical(space, W, H):
    """
    The "canonical range" used by Border: the docs give texture 0..1, image −1..1. The docs give nothing for pixel;
    here we use [0, W] / [0, H] (= the texture range in pixel units).
    """
    if space == "texture":
        return (0.0, 1.0), (0.0, 1.0)
    if space == "image":
        return (-1.0, 1.0), (-1.0, 1.0)
    return (0.0, float(W)), (0.0, float(H))


def border(t, mode, lo, hi):
    """
    What to do outside [lo, hi] (Houdini's Border menu):
      clamp   clamp to the nearest edge
      mirror  fold back and forth about the edges (period 2·(hi − lo))
      wrap    repeat from the other side (period hi − lo)
      extend  do nothing
    """
    if mode == "extend":
        return t
    if mode == "clamp":
        return np.clip(t, lo, hi)
    P = hi - lo
    if mode == "wrap":
        return lo + np.mod(t - lo, P)
    if mode == "mirror":
        m = np.mod(t - lo, 2.0 * P)
        return lo + np.where(m <= P, m, 2.0 * P - m)
    raise ValueError(f"Border must be one of {BORDERS}")


def shift_cycles_border(t, shift, cycles, mode, lo, hi):
    """
    (t + Shift) × Cycles, then folded back into [lo, hi] by Border.

    The docs only say both come before Border ("prior to the border correction"), not whether Shift
    or Cycles comes first. Here Shift comes first (Shift translates the "position", Cycles scales the "position";
    translate the position first, then scale). With defaults 0 / 1 both are identities, bit-identical.
    """
    s, c = float(shift), float(cycles)
    if s != 0.0:
        t = t + s
    if c != 1.0:
        t = t * c
    return border(t, mode, lo, hi)


def check_border(*modes):
    for b in modes:
        if b not in BORDERS:
            raise ValueError(f"Border must be one of {BORDERS}")


def max_singular(a, b, c, d):
    """Largest singular value of the 2×2 matrix [[a, b], [c, d]] (element-wise, broadcastable)."""
    s1 = a * a + b * b + c * c + d * d
    s2 = np.sqrt(np.maximum((a * a + b * b - c * c - d * d) ** 2
                            + 4.0 * (a * c + b * d) ** 2, 0.0))
    return np.sqrt(np.maximum(0.5 * (s1 + s2), 0.0))


# ═══════════════════════════════════════════════════════ UV to Polar / Polar to UV
ANGLE_UNITS = ("radians", "degrees", "circles")
POLAR_DIRS = ("uv_to_polar", "polar_to_uv")
_FULL = {"radians": 2.0 * np.pi, "degrees": 360.0, "circles": 1.0}


def polar_coords(img, direction="uv_to_polar", angle_units="circles",
                 uv_layer="uv", angle_layer="angle", length_layer="length",
                 angle=0.0, length=1.0, origin="0 0"):
    """
    Houdini's UV to Polar / Polar to UV: **only converts the coordinate values stored in the pixels**, does not move pixels
    (to move pixels use UV Map → this → UV Sample, docs verbatim).

      uv_to_polar   reads uv_layer (2 channels), writes angle_layer, length_layer (1 channel each)
      polar_to_uv   reads angle_layer / length_layer (empty layer name = use the Angle / Length constants,
                    matching Houdini's "use the parameter when no angle / length input is connected"), writes uv_layer

    Conventions (the docs only say "measured from the x axis"; the rest is our own): angle 0 = +u direction, counter-clockwise (v up)
    positive; uv_to_polar outputs angles in [0, one full turn) -- the docs say 0~1 for Circles,
    the other two modes use the same range. Origin is our addition (Houdini's origin is just uv = (0, 0)):
    to rotate texture-space uv about the image centre, enter 0.5 0.5.
    """
    from .pixel import getn, put, _vec
    from .core import CopImage
    if img is None:
        return CopImage()
    if direction not in POLAR_DIRS:
        raise ValueError(f"Direction must be one of {POLAR_DIRS}")
    if angle_units not in ANGLE_UNITS:
        raise ValueError(f"Angle Units must be one of {ANGLE_UNITS}")
    full = _FULL[angle_units]
    ox, oy = _vec(origin, 2)
    out = img.copy()
    H, W = img.yres, img.xres
    if direction == "uv_to_polar":
        uv = getn(img, uv_layer)
        if uv.shape[2] < 2:
            raise ValueError("UV layer needs 2 channels")
        x, y = uv[..., 0] - ox, uv[..., 1] - oy
        a = np.mod(np.arctan2(y, x), 2.0 * np.pi) * (full / (2.0 * np.pi))
        a = np.where(a >= full, 0.0, a)          # rounding after mod may land exactly on one full turn
        put(out, str(angle_layer).strip() or "angle", a, img)
        put(out, str(length_layer).strip() or "length", np.hypot(x, y), img)
        return out

    def _mono(name, const):
        name = str(name).strip()
        if not name:
            return np.full((H, W), float(const))
        return getn(img, name)[..., 0]
    th = _mono(angle_layer, angle) * (2.0 * np.pi / full)
    r = _mono(length_layer, length)
    put(out, str(uv_layer).strip() or "uv",
        np.stack([ox + r * np.cos(th), oy + r * np.sin(th)], -1), img)
    return out


# ═══════════════════════════════════════════════════════ Space Transform
XSPACES = ("buffer", "pixel", "texture", "image", "world")
VECTOR_TYPES = ("position", "vector")


def _to_tex(space, W, H):
    """Affine space → texture (two axes): returns (multipliers kx, ky, offsets bx, by), tex = k·x + b."""
    if space in ("buffer", "pixel"):
        return 1.0 / W, 1.0 / H, 0.0, 0.0
    if space == "texture":
        return 1.0, 1.0, 0.0, 0.0
    L = float(max(W, H))                       # image / world
    return L / (2.0 * W), L / (2.0 * H), 0.5, 0.5


def space_transform(img, layer="uv", vector_type="position", src_space="texture",
                    dst_space="image", out_layer="", src_ref=None, dst_ref=None):
    """
    Houdini's Space Transform: converts the **coordinate values** stored in a layer from one space to another.
    The source space is interpreted at src_ref's resolution, the target space at dst_ref's (if not connected, both use coord's own).

    position goes through the full affine; vector (displacement / velocity) only through the linear part (no translation).
    Only the first two channels (x, y) are converted; a 3rd channel is kept as is -- we have no camera, World is just
    Image (the default orthographic camera looking at the z = 0 plane), so there's nothing to convert in depth. Buffer is the same as Pixel
    (the plugin has no pixel scale). Pixel convention: the first pixel's centre is 0.5 (consistent with UV Map).
    """
    from .pixel import getn, put
    from .core import CopImage
    if img is None:
        return CopImage()
    for s in (src_space, dst_space):
        if s not in XSPACES:
            raise ValueError(f"Space must be one of {XSPACES}")
    if vector_type not in VECTOR_TYPES:
        raise ValueError(f"Vector Type must be one of {VECTOR_TYPES}")
    a = getn(img, layer)
    if a.shape[2] < 2:
        raise ValueError("the coordinate layer needs at least 2 channels")
    # ref only provides a resolution (no layers needed)
    sr = src_ref if src_ref is not None and src_ref.xres > 0 else img
    dr = dst_ref if dst_ref is not None and dst_ref.xres > 0 else img
    k1x, k1y, b1x, b1y = _to_tex(src_space, sr.xres, sr.yres)
    k2x, k2y, b2x, b2y = _to_tex(dst_space, dr.xres, dr.yres)
    if vector_type == "vector":
        b1x = b1y = b2x = b2y = 0.0
    # tex = k1·x + b1;dst = (tex − b2) / k2
    x = (a[..., 0] * k1x + b1x - b2x) / k2x
    y = (a[..., 1] * k1y + b1y - b2y) / k2y
    r = a.copy()
    r[..., 0], r[..., 1] = x, y
    out = img.copy()
    put(out, str(out_layer).strip() or layer, r, img)
    return out


# ═══════════════════════════════════════════════════════ Position Map
SOURCE_POSITIONS = ("position", "view_direction")


def position_map(img=None, source_position="position",
                 x_border="extend", x_shift=0.0, x_cycles=1.0,
                 y_border="extend", y_shift=0.0, y_cycles=1.0,
                 z_border="extend", z_shift=0.0, z_cycles=1.0,
                 out_layer="pos", xres=512, yres=512):
    """
    Houdini's Position Map: each pixel stores a 3D position (a reference position for 3D noise); each axis is
    (P + Shift) × Cycles, then folded by Border back into the cube of side 2 [−1, 1]³.

    We have no camera metadata, so:
      position        the pixel's position in the world = (image x, image y, 0) (World = Image)
      view_direction  the default orthographic camera looks along −Z; every pixel is (0, 0, −1)
    Camera Origin is not implemented: an orthographic camera's origin varies per pixel, but its z depends on the camera, which we don't have.
    The docs don't give the order of Shift / Cycles; as with UV Map, Shift comes first (see shift_cycles_border).
    """
    from .pattern import _base
    from .pixel import put
    if source_position not in SOURCE_POSITIONS:
        raise ValueError(f"Source Position must be one of {SOURCE_POSITIONS}")
    check_border(x_border, y_border, z_border)
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    u = (np.arange(W, dtype=np.float64) + 0.5) / W
    v = (np.arange(H, dtype=np.float64) + 0.5) / H
    U, V = np.meshgrid(u, v)
    if source_position == "position":
        X, Y = tex_to_space("image", U, V, W, H)
        Z = np.zeros_like(X)
    else:
        X, Y, Z = np.zeros_like(U), np.zeros_like(U), -np.ones_like(U)
    P = [shift_cycles_border(c, s, k, b, -1.0, 1.0) for c, s, k, b in
         ((X, x_shift, x_cycles, x_border), (Y, y_shift, y_cycles, y_border),
          (Z, z_shift, z_cycles, z_border))]
    put(out, str(out_layer).strip() or "pos", np.stack(P, -1), like)
    return out
