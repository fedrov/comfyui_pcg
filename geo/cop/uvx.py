"""
UV / tiling / SDF / ID (batch E): UV Map, UV Sample (including spherical sampling), UV Transform,
UV Inverse, Polar, Hex Tile, Triplanar, Retile, SDF operations, ID conversion.

The UV layer convention is the same across the plugin: 2 channels (u, v), u right, v up, pixel centers at
((j + 0.5)/W, (i + 0.5)/H). "Sampling by UV" is `filters.sample`, with three borders
(clamp / wrap / black).
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage
from .pattern import _base, rnd, _pix
from .pixel import getn, put, names_of, _vec
from .filters import sample, BORDERS

UV_MAP_MODES = ("identity", "by_id")
FIT_MODES = ("stretch", "fit")
ID_UV_MODES = ("uv_map", "center", "minimum", "maximum", "size")
SAMPLE_MODES = ("uv", "latlong", "mirror_ball")
POLAR_DIRS = ("to_polar", "from_polar")
RETILE_MODES = ("shuffle", "seamless")
SDF_OPS = ("union", "intersect", "subtract", "blend", "offset", "onion")
SDF_TO_MONO = ("fill", "outline", "falloff")
ID_MODES = ("mask", "mono", "sdf")


# ═══════════════════════════════════════════════════════════ UV Map
def uv_map(img=None, mode="identity", id_layer="id", fit="fit",
           scale="1 1", offset="0 0", rotate=0.0, out_layer="uv", xres=512,
           yres=512, uv_space="texture", u_border="extend", u_shift=0.0,
           u_cycles=1.0, v_border="extend", v_shift=0.0, v_cycles=1.0,
           uvscale_layer="", id_mode="uv_map", auto_scale=True,
           zero_negative_ids=True, connected=False):
    """
    UV Map / UV Map by ID.
      identity  uv of each pixel center, then transformed by Scale / Rotate (about 0.5, 0.5) / Offset
      by_id     each id's (> 0) bounding box is mapped to [0,1]² separately: stretch fills it, fit keeps
                the aspect ratio with the short side centered -- gives each segmented piece its own full texture. Pixels with id 0
                get uv = 0

    Added in pcg100 c6 (all defaults = old behaviour; see coordspace for the space conventions):
      uv_space        texture / image / pixel (by_id has only the first two, same as Houdini).
                      identity: the old Scale / Rotate / Offset are still done in texture, then
                      converted to this space. by_id + image: the island's bounding box is fitted proportionally into [-1,1]²
                      (docs: "framed to fit the bounding box, so keep pixels square"),
                      so Fit isn't read under image
      u/v_shift, u/v_cycles, u/v_border
                      (uv + Shift) x Cycles, then folded back into the canonical range by Border
                      (texture 0..1, image -1..1, pixel 0..W). The docs don't give Houdini's Border default;
                      we default to extend = no folding, to match the old behaviour
      uvscale_layer   if non-empty, outputs 1-channel uvscale: how many times enlarged relative to "the identity UV Map of this space"
                      (the Jacobian's largest singular value; Cycles, Scale and by_id's island scaling all count).
                      The docs only say "effective scale factor caused by resizing the UV map"
      id_mode         what by_id outputs per pixel: uv_map (relative position within the island) / center /
                      minimum / maximum / size (center / bottom-left / top-right / size of the island's bounding box,
                      measured in uv_space, bounding box at pixel edges). These four don't do Shift / Cycles /
                      Border (the docs don't say they apply to statistics), uvscale = 1
      auto_scale      when off, uv isn't scaled to the island's bounding box: under texture the origin is at the box's bottom-left,
                      measured in whole-image texture units; under image the origin is at the box center, measured in whole-image
                      image units (the docs only have one sentence on "whether to scale to the bounding box"; the origin is our own choice)
      zero_negative_ids  on (default, = old behaviour): negative ids count as 0 (no island); off: negative ids also form islands
      connected       on: disconnected pieces with the same id each count as an island (4-connected) -- Houdini says
                      "each connected ID island"; the old behaviour (off) counts all pixels of one id as one island
    Background (id 0) pixels get uv = 0, uvscale = 0.
    """
    from . import coordspace as CS
    if mode not in UV_MAP_MODES:
        raise ValueError(f"Mode must be one of {UV_MAP_MODES}")
    if uv_space not in CS.SPACES:
        raise ValueError(f"UV Space must be one of {CS.SPACES}")
    CS.check_border(u_border, v_border)
    if id_mode not in ID_UV_MODES:
        raise ValueError(f"ID Mode must be one of {ID_UV_MODES}")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    (ulo, uhi), (vlo, vhi) = CS.canonical(uv_space, W, H)
    cu, cv = float(u_cycles), float(v_cycles)
    if mode == "identity":
        u, v = _pix(W, H)
        uv = np.stack([u, v], -1)
        uv = transform_uv(uv, offset, rotate, scale, "0.5 0.5", False)
        if uv_space != "texture":
            a, b = CS.tex_to_space(uv_space, uv[..., 0], uv[..., 1], W, H)
            uv = np.stack([a, b], -1)
        a = CS.shift_cycles_border(uv[..., 0], u_shift, cu, u_border, ulo, uhi)
        b = CS.shift_cycles_border(uv[..., 1], v_shift, cv, v_border, vlo, vhi)
        uv = np.stack([a, b], -1)
        # Jacobian relative to the identity map: diag(c)·D·Lin·D⁻¹ (D = diagonal scaling from texture -> space,
        # Lin = the linear part of transform_uv: scale first, then rotate)
        sx, sy = _vec(scale, 2)
        th = math.radians(float(rotate))
        c_, s_ = math.cos(th), math.sin(th)
        Lin = np.array([[c_ * sx, -s_ * sy], [s_ * sx, c_ * sy]])
        dx, dy = CS.space_scale(uv_space, W, H)
        D = np.diag([dx, dy])
        J = np.diag([cu, cv]) @ D @ Lin @ np.linalg.inv(D)
        scl = np.full((H, W), float(CS.max_singular(*J.ravel())))
    else:
        if uv_space == "pixel":
            raise ValueError("UV Map by ID's UV Space can only be texture / image")
        if fit not in FIT_MODES:
            raise ValueError(f"Fit must be one of {FIT_MODES}")
        ids = np.rint(getn(out, id_layer)[..., 0]).astype(np.int64)
        if zero_negative_ids:
            ids = np.where(ids < 0, 0, ids)
        uv = np.zeros((H, W, 2))
        scl = np.zeros((H, W))
        J, I = np.meshgrid(np.arange(W, dtype=float), np.arange(H,
                                                                dtype=float))
        Lr = float(max(W, H))
        for m in _islands(ids, connected):
            ys, xs = np.nonzero(m)
            x0, x1 = xs.min(), xs.max() + 1.0
            y0, y1 = ys.min(), ys.max() + 1.0
            bw, bh = x1 - x0, y1 - y0
            if id_mode != "uv_map":
                px = {"center": ((x0 + x1) / 2, (y0 + y1) / 2),
                      "minimum": (x0, y0), "maximum": (x1, y1)}.get(id_mode)
                if uv_space == "texture":
                    val = (bw / W, bh / H) if px is None else (px[0] / W,
                                                                px[1] / H)
                else:
                    val = ((bw * 2 / Lr, bh * 2 / Lr) if px is None else
                           ((px[0] - W / 2) * 2 / Lr, (px[1] - H / 2) * 2 / Lr))
                uv[m, 0], uv[m, 1] = val
                scl[m] = 1.0
                continue
            if uv_space == "texture":
                if not auto_scale:
                    uu = (J[m] + 0.5 - x0) / W
                    vv = (I[m] + 0.5 - y0) / H
                    su = sv = 1.0
                else:
                    if fit == "fit":
                        s = max(bw, bh)
                        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                        x0, y0, bw, bh = cx - s / 2, cy - s / 2, s, s
                    uu = (J[m] + 0.5 - x0) / bw
                    vv = (I[m] + 0.5 - y0) / bh
                    su, sv = W / bw, H / bh
            else:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                s = max(bw, bh) if auto_scale else Lr
                uu = (J[m] + 0.5 - cx) * 2 / s
                vv = (I[m] + 0.5 - cy) * 2 / s
                su = sv = Lr / s
            uv[m, 0] = CS.shift_cycles_border(uu, u_shift, cu, u_border, ulo,
                                              uhi)
            uv[m, 1] = CS.shift_cycles_border(vv, v_shift, cv, v_border, vlo,
                                              vhi)
            scl[m] = max(abs(cu) * su, abs(cv) * sv)
    put(out, str(out_layer).strip() or "uv", uv, like)
    if str(uvscale_layer).strip():
        put(out, uvscale_layer, scl, like)
    return out


def _islands(ids, connected):
    """by_id islands: one per non-zero id; with connected, further split by 4-connectivity."""
    for k in np.unique(ids):
        if k == 0:
            continue
        m = ids == k
        if not connected:
            yield m
            continue
        from .analysis import label
        lab = label(m, 4)
        for j in range(1, int(lab.max()) + 1):
            yield lab == j


def transform_uv(uv, translate="0 0", rotate=0.0, scale="1 1",
                 pivot="0.5 0.5", wrap=False):
    """(...,2) uv: about Pivot, scale first, then rotate counterclockwise, then translate; wrap takes the fractional part."""
    t = _vec(translate, 2)
    s = _vec(scale, 2)
    p = _vec(pivot, 2)
    c, sn = math.cos(math.radians(float(rotate))), math.sin(
        math.radians(float(rotate)))
    x = (uv[..., 0] - p[0]) * s[0]
    y = (uv[..., 1] - p[1]) * s[1]
    r = np.stack([x * c - y * sn + p[0] + t[0],
                  x * sn + y * c + p[1] + t[1]], -1)
    return r - np.floor(r) if wrap else r


def uv_transform(img, layer="uv", translate="0 0", rotate=0.0, scale="1 1",
                 pivot="0.5 0.5", wrap=False, out_layer=""):
    """UV Transform: changes the uv **values**, not the image. Sample with it and the texture moves the opposite way."""
    if img is None:
        return CopImage()
    uv = getn(img, layer)
    if uv.shape[2] < 2:
        raise ValueError("The UV layer needs 2 channels")
    r = transform_uv(uv[..., :2], translate, rotate, scale, pivot, wrap)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, r, img)


# ═══════════════════════════════════════════════════════════ Sampling
def _dir_to_latlong(d):
    """Unit direction -> equirectangular (latlong) uv: u = azimuth (+X at 0.5, around +Y),
    v = elevation (+Y top = 1). Y up, consistent with the plugin's geometry."""
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    n = np.maximum(np.sqrt(x * x + y * y + z * z), 1e-12)
    u = 0.5 + np.arctan2(-z, x) / (2 * math.pi)
    v = 0.5 + np.arcsin(np.clip(y / n, -1, 1)) / math.pi
    return u, v


def _dir_to_mirrorball(d):
    """Mirror ball (camera looking along -Z, direction d reflected off the ball) -> uv."""
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    n = np.maximum(np.sqrt(x * x + y * y + z * z), 1e-12)
    x, y, z = x / n, y / n, z / n
    # the point on the sphere that reflects d has normal n = normalize(d + (0,0,1)) (the reverse of the view ray
    # toward the camera is +Z), |d + ẑ| = √(2(1 + d_z)); its position on the image is n's xy
    m = np.sqrt(np.maximum(2 * (1 + z), 1e-12))
    return 0.5 + 0.5 * x / m, 0.5 + 0.5 * y / m


def uv_sample(img, source, uv_layer="uv", source_layer="C", mode="uv",
              border="wrap", out_layer="sampled"):
    """
    UV Sample / Sphere Sample. Bilinearly samples source at the coordinates in one of img's layers, writing the result as
    a layer of img (resolution follows img).
      uv           uv_layer is a 2-channel uv
      latlong      uv_layer is a 3-channel direction (e.g. normal N, reflection vector), source is
                   an equirectangular environment map (Y up)
      mirror_ball  same as above, source is a mirror-ball photo
    If source isn't connected, samples from img itself.
    """
    if img is None:
        return CopImage()
    if mode not in SAMPLE_MODES:
        raise ValueError(f"Mode must be one of {SAMPLE_MODES}")
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    src = getn(source if source is not None else img, source_layer)
    c = getn(img, uv_layer)
    if mode == "uv":
        if c.shape[2] < 2:
            raise ValueError("uv mode needs a 2-channel UV layer")
        u, v = c[..., 0], c[..., 1]
    else:
        if c.shape[2] < 3:
            raise ValueError(f"{mode} mode needs a 3-channel direction layer")
        u, v = (_dir_to_latlong if mode == "latlong" else
                _dir_to_mirrorball)(c[..., :3])
    out = img.copy()
    return put(out, str(out_layer).strip() or "sampled",
               sample(src, u, v, border), img)


def uv_inverse(img, layer="uv", source_res="0 0", fill=True,
               out_layer="uv_inverse"):
    """
    UV Inverse: the uv layer is a map "output pixel -> source uv"; find its inverse "source pixel -> output uv".
    Method: each output pixel **splats** its own uv (pixel center) onto the source pixel it points to,
    averaging when several land in the same cell; cells nobody lands in are filled by push-pull (fill), and a
    coverage map out_layer_mask is also output. Source Res 0 0 = same as img.
    The inverse only makes sense when the map is roughly one-to-one and not much sparser than the source -- coverage is how to check that.
    """
    if img is None:
        return CopImage()
    c = getn(img, layer)
    H, W = c.shape[:2]
    sw, sh = (int(x) for x in _vec(source_res, 2))
    sw, sh = sw or W, sh or H
    u, v = _pix(W, H)
    jj = np.floor(c[..., 0] * sw).astype(np.int64)
    ii = np.floor(c[..., 1] * sh).astype(np.int64)
    ok = (jj >= 0) & (jj < sw) & (ii >= 0) & (ii < sh)
    idx = ii[ok] * sw + jj[ok]
    cnt = np.bincount(idx, minlength=sw * sh).astype(np.float64)
    su = np.bincount(idx, u[ok], sw * sh)
    sv = np.bincount(idx, v[ok], sw * sh)
    has = cnt > 0
    inv = np.zeros((sw * sh, 2))
    inv[has, 0] = su[has] / cnt[has]
    inv[has, 1] = sv[has] / cnt[has]
    inv = inv.reshape(sh, sw, 2)
    mask = has.reshape(sh, sw)
    if fill and mask.any() and not mask.all():
        from ..backproject import _push_pull
        inv = np.where(mask[..., None], inv, _push_pull(inv, mask))
    out = img.copy() if (sw, sh) == (W, H) else CopImage(sw, sh)
    like = img if (sw, sh) == (W, H) else None
    name = str(out_layer).strip() or "uv_inverse"
    put(out, name, inv, like)
    put(out, name + "_mask", mask.astype(np.float64), like)
    return out


# ═══════════════════════════════════════════════════════════ Polar coordinates
def polar(img, layers="", direction="to_polar", center="0.5 0.5",
          radius=0.5, angle=0.0, border="clamp"):
    """
    UV to Polar / Polar to UV: converts the image between Cartesian and polar coordinates.
      to_polar    output u = angle (0-1 per turn, counterclockwise from Angle), v = radius
                  (0-Radius, by image width). Rings become horizontal bands
      from_polar  the reverse: rolls horizontal bands into rings
    The two directions are inverses (round-tripped in tests). Aspect ratio is kept by the short side: circles stay circles.
    """
    if img is None:
        return CopImage()
    if direction not in POLAR_DIRS:
        raise ValueError(f"Direction must be one of {POLAR_DIRS}")
    W, H = img.xres, img.yres
    cu, cv = _vec(center, 2)
    u, v = _pix(W, H)
    R = float(radius)
    a0 = math.radians(float(angle))
    asp = W / H
    if direction == "to_polar":
        th = a0 + u * 2 * math.pi
        r = v * R
        su = cu + r * np.cos(th)
        sv = cv + r * np.sin(th) * asp
    else:
        dx = u - cu
        dy = (v - cv) / asp
        su = np.mod(np.arctan2(dy, dx) - a0, 2 * math.pi) / (2 * math.pi)
        sv = np.hypot(dx, dy) / max(R, 1e-12)
    out = img.copy()
    for n in names_of(img, layers):
        a = getn(img, n)
        if direction == "from_polar":
            # the angle direction is naturally periodic (u uses wrap); the radius direction follows Border: where the radius exceeds 1,
            # black gives 0, clamp / wrap take the outermost ring
            rr = sample(a, su, np.clip(sv, 0.0, 1.0 - 0.5 / a.shape[0]),
                        "wrap")
            if border == "black":
                rr = np.where((sv > 1.0)[..., None], 0.0, rr)
        else:
            rr = sample(a, su, sv, border)
        put(out, n, rr, img)
    return out


# ═══════════════════════════════════════════════════════════ Hex Tile
def _hex_grid(x, y):
    """
    Barycentric weights of triangles on a hexagonal grid (the hex-tiling scheme of Mikkelsen 2022):
    shear the plane into a triangle grid; each point falls in a triangle whose three vertices are the centers of three adjacent hexagons,
    and the barycentric coordinates are the blend weights of the three copies. Returns (integer coordinates of the three vertices, weights).
    """
    # shear: turn equilateral triangles into right triangles
    k = 2 / math.sqrt(3)
    sx = x - y / math.sqrt(3)
    sy = y * k
    ix, iy = np.floor(sx), np.floor(sy)
    fx, fy = sx - ix, sy - iy
    up = fx + fy > 1
    w1 = np.where(up, 1 - fy, fy)
    w2 = np.where(up, 1 - fx, fx)
    w3 = np.where(up, fx + fy - 1, 1 - fx - fy)
    v1 = (np.where(up, ix + 1, ix), np.where(up, iy, iy + 1))
    v2 = (np.where(up, ix, ix + 1), np.where(up, iy + 1, iy))
    v3 = (np.where(up, ix + 1, ix), np.where(up, iy + 1, iy))
    return (v1, v2, v3), (w1, w2, w3)


def hex_tile(img, source=None, layer="C", tiles=4.0, rotation=180.0,
             contrast=0.6, seed=0, out_layer="hex", xres=0, yres=0):
    """
    Hex Tile: breaks up tiling repetition. The plane is tiled with a hexagonal grid; each hexagon center gets a copy of the texture with random offset and random
    rotation, and the three neighboring copies are blended by barycentric weights; Contrast pushes the weights toward "the largest one wins"
    (w^(1 + 8·contrast) then renormalized): larger means narrower, less blurry seams. Ideally the source is itself tileable.

    Tiles: how many texture periods across the image width. out_layer resolution follows img (or X/Y Res).
    """
    if img is None:
        return CopImage()
    src = getn(source if source is not None else img, layer)
    W = int(xres) or img.xres
    H = int(yres) or img.yres
    out = img.copy() if (W, H) == (img.xres, img.yres) else CopImage(W, H)
    u, v = _pix(W, H)
    x = u * float(tiles)
    y = v * float(tiles) * H / W
    verts, ws = _hex_grid(x, y)
    p = 1 + 8 * min(max(float(contrast), 0.0), 1.0)
    ws = [np.power(np.maximum(w, 0.0), p) for w in ws]
    tot = ws[0] + ws[1] + ws[2]
    acc = 0.0
    for (vx, vy), w in zip(verts, ws):
        key = (vx.astype(np.int64) * 73856093) ^ (vy.astype(np.int64)
                                                   * 19349663)
        ox = rnd(key, seed, 1)
        oy = rnd(key, seed, 2)
        th = math.radians(float(rotation)) * (rnd(key, seed, 3) * 2 - 1)
        c, s = np.cos(th), np.sin(th)
        su = x * c - y * s + ox
        sv = x * s + y * c + oy
        acc = acc + sample(src, su, sv, "wrap") * w[..., None]
    r = acc / tot[..., None]
    put(out, str(out_layer).strip() or "hex", r,
        img if (W, H) == (img.xres, img.yres) else None)
    return out


# ═══════════════════════════════════════════════════════════ Triplanar
def triplanar(img, source=None, p_layer="P", n_layer="N", layer="C",
              scale=1.0, sharpness=4.0, hex=False, tiles_rotation=180.0,
              seed=0, out_layer="triplanar", uv_layer=""):
    """
    Triplanar / Triplanar UV / Triplanar Hex Tile. Given each pixel's world position P and
    normal N (the two layers from Render Pass), the texture is projected once along each of the X, Y and Z axes (onto
    the YZ, XZ and XY planes, coordinates x Scale) and blended by weights |N|^Sharpness normalized.
    Hex: within each projection, hex-tiling also breaks up repetition. If uv_layer is given a name, an extra
    "projection uv of the dominant axis" is output (Triplanar UV).
    """
    if img is None:
        return CopImage()
    P = getn(img, p_layer)[..., :3] * float(scale)
    N = getn(img, n_layer)[..., :3]
    src = getn(source if source is not None else img, layer)
    w = np.abs(N) ** float(sharpness)
    w = w / np.maximum(w.sum(-1, keepdims=True), 1e-12)
    planes = ((P[..., 2], P[..., 1]), (P[..., 0], P[..., 2]),
              (P[..., 0], P[..., 1]))
    acc = 0.0
    for k, (a, b) in enumerate(planes):
        if hex:
            verts, ws = _hex_grid(a, b)
            ws = [np.power(np.maximum(q, 0.0), 5.0) for q in ws]
            tot = ws[0] + ws[1] + ws[2]
            col = 0.0
            for (vx, vy), q in zip(verts, ws):
                key = (vx.astype(np.int64) * 73856093) ^ (
                    vy.astype(np.int64) * 19349663) ^ k
                th = math.radians(float(tiles_rotation)) * (
                    rnd(key, seed, 3) * 2 - 1)
                c, s = np.cos(th), np.sin(th)
                col = col + sample(src, a * c - b * s + rnd(key, seed, 1),
                                   a * s + b * c + rnd(key, seed, 2),
                                   "wrap") * q[..., None]
            col = col / tot[..., None]
        else:
            col = sample(src, a, b, "wrap")
        acc = acc + col * w[..., k:k + 1]
    out = img.copy()
    put(out, str(out_layer).strip() or "triplanar", acc, img)
    if str(uv_layer).strip():
        dom = np.argmax(np.abs(N), -1)
        uu = np.choose(dom, [planes[0][0], planes[1][0], planes[2][0]])
        vv = np.choose(dom, [planes[0][1], planes[1][1], planes[2][1]])
        put(out, uv_layer, np.stack([uu - np.floor(uu), vv - np.floor(vv)],
                                    -1), img)
    return out


# ═══════════════════════════════════════════════════════════ Retile
def retile(img, layers="", mode="shuffle", counts="4 4", rotate=True,
           flip=False, blend=0.25, seed=0):
    """
    Retile.
      shuffle   cut the image into Counts cells and shuffle their positions randomly (optionally also random rotations by multiples of 90° /
                flips) -- cut a tileable material into blocks and rearrange, giving an image of the same style with a different layout.
                Rotating by 90° requires square cells
      seamless  make it tileable: cross-fade with itself shifted by half the image, by "distance to the edge"; at the edges
                only the shifted copy is used (its edge is the original's center, naturally continuous). Blend is the transition band
                as a fraction of half the image
    """
    if img is None:
        return CopImage()
    if mode not in RETILE_MODES:
        raise ValueError(f"Mode must be one of {RETILE_MODES}")
    W, H = img.xres, img.yres
    out = img.copy()
    if mode == "seamless":
        # distance to the edge measured by pixel index: the first / last column is exactly 0 -- at the edge **only**
        # the shifted copy is used, so the seam exactly equals the difference between two adjacent columns at the original's center (measuring by pixel centers
        # would still mix in 1/W of the original at the edge, and the seam difference in the tests came out wrong)
        #
        # **the two directions are done separately** (u first, then v). Originally it blended once with itself "shifted by half in both directions" by
        # min(to left/right edge, to top/bottom edge): the shifted copy has one horizontal and one vertical seam in the very middle, and in
        # the middle column near the top and bottom edges the weight went precisely to the shifted copy -- the seam showed, a segment of a
        # cross in the center of the image (obvious at a glance when making materials). Done separately: the u pass blends only by distance to the left/right edges
        # (the shifted copy's vertical seam is in the middle, where the weight is entirely the original); the v pass does the same on the result that is already
        # seamless in u (a vertical shift doesn't break left/right seamlessness).
        Jx = np.arange(W, dtype=np.float64)[None, :]
        Iy = np.arange(H, dtype=np.float64)[:, None]
        du = np.minimum(Jx, W - 1 - Jx) / max((W - 1) / 2, 1)
        dv = np.minimum(Iy, H - 1 - Iy) / max((H - 1) / 2, 1)
        b = max(float(blend), 1e-6)

        def w_(d):
            t = np.clip(d / b, 0, 1)
            return (t * t * (3 - 2 * t))[..., None]
        wu, wv = w_(du), w_(dv)
        for n in names_of(img, layers):
            a = getn(img, n)
            a = a * wu + np.roll(a, W // 2, 1) * (1 - wu)
            a = a * wv + np.roll(a, H // 2, 0) * (1 - wv)
            put(out, n, a, img)
        return out
    nu, nv = (max(1, int(x)) for x in _vec(counts, 2))
    if W % nu or H % nv:
        raise ValueError(f"{W}x{H} is not divisible by {nu}x{nv}")
    tw, th = W // nu, H // nv
    if rotate and tw != th:
        raise ValueError("Random 90° rotation needs square cells (tw = th)")
    k = np.arange(nu * nv)
    perm = np.argsort(rnd(k, seed, 1), kind="stable")
    rots = (rnd(k, seed, 2) * 4).astype(int) if rotate else np.zeros_like(k)
    flips = rnd(k, seed, 3) < 0.5 if flip else np.zeros(k.size, bool)
    for n in names_of(img, layers):
        a = getn(img, n)
        r = np.empty_like(a)
        for dst in range(nu * nv):
            sj, si = perm[dst] % nu, perm[dst] // nu
            blk = a[si * th:(si + 1) * th, sj * tw:(sj + 1) * tw]
            blk = np.rot90(blk, rots[dst])
            if flips[dst]:
                blk = blk[:, ::-1]
            dj, di = dst % nu, dst // nu
            r[di * th:(di + 1) * th, dj * tw:(dj + 1) * tw] = blk
        put(out, n, r, img)
    return out


# ═══════════════════════════════════════════════════════════ SDF
def smin(a, b, k):
    """Polynomial smooth min (Quilez): k = 0 reduces to min; when the two differ by > k it is just min."""
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def sdf_ops(img, a_layer="sdf", b_layer="sdf_b", op="union", smooth=0.0,
            t=0.5, amount=0.0, out_layer="sdf_out"):
    """
    SDF Blend etc. SDF negative inside, positive outside (COP Shape's convention), units follow the input (Shape outputs
    lengths normalized by the short side).
      union / intersect / subtract   min / max / max(a, -b); Smooth > 0 uses
                                      the polynomial smooth version (rounded transition)
      blend    linear interpolation (1 - t)a + t·b -- morphing between shapes
      offset   a - Amount (positive = grow outward)
      onion    |a| - Amount (becomes a shell 2·Amount thick)
    """
    if img is None:
        return CopImage()
    if op not in SDF_OPS:
        raise ValueError(f"Op must be one of {SDF_OPS}")
    a = getn(img, a_layer)[..., 0]
    k = float(smooth)
    if op in ("union", "intersect", "subtract", "blend"):
        b = getn(img, b_layer)[..., 0]
    if op == "union":
        r = smin(a, b, k)
    elif op == "intersect":
        r = -smin(-a, -b, k)
    elif op == "subtract":
        r = -smin(-a, b, k)
    elif op == "blend":
        r = (1 - float(t)) * a + float(t) * b
    elif op == "offset":
        r = a - float(amount)
    else:
        r = np.abs(a) - float(amount)
    out = img.copy()
    return put(out, str(out_layer).strip() or "sdf_out", r, img)


def sdf_to_mono(img, layer="sdf", mode="fill", width=0.01, units="uv",
                out_layer="mask"):
    """
    SDF to Mono. fill: inside is 1 (linear transition by Width at the edge); outline: lines where |d| < Width/2
    (1-pixel anti-aliased edges); falloff: a glow dropping from 1 to 0 within Width distance outward from the edge. Units: uv = distance
    units by the **short side** (consistent with COP Shape), pixels = in pixels (1 pixel is most stable for anti-aliasing).
    """
    if img is None:
        return CopImage()
    if mode not in SDF_TO_MONO:
        raise ValueError(f"Mode must be one of {SDF_TO_MONO}")
    d = getn(img, layer)[..., 0]
    if units == "pixels":
        d = d * min(img.xres, img.yres)
    elif units != "uv":
        raise ValueError("Units must be one of uv / pixels")
    w = max(float(width), 1e-12)
    px = 1.0 if units == "pixels" else 1.0 / min(img.xres, img.yres)
    if mode == "fill":
        r = np.clip(0.5 - d / w, 0, 1)
    elif mode == "outline":
        # line width Width, 1-pixel anti-aliased edges
        r = np.clip(0.5 - (np.abs(d) - w / 2) / px, 0, 1)
    else:
        r = np.where(d <= 0, 1.0, np.clip(1 - d / w, 0, 1) ** 2)
    out = img.copy()
    return put(out, str(out_layer).strip() or "mask", r, img)


# ═══════════════════════════════════════════════════════════ ID
def id_convert(img, layer="id", mode="mask", ids="1", invert=False,
               normalize=True, out_layer=""):
    """
    ID to Mask / ID to Mono / ID to SDF.
      mask   ids listed in Ids (space-separated, a-b ranges supported) -> 1, others 0
      mono   id -> value: with normalize, mapped to 0-1 by (id - min)/(max - min)
      sdf    with Ids given: signed distance of the union of the selected ids (negative inside, positive outside, in pixels,
             boundary ±0.5; Invert takes the complement). Ids empty or *: each pixel's nearest distance to "a different id"
             (>= 0.5) -- every piece's own interior distance stitched into one image
    """
    if img is None:
        return CopImage()
    if mode not in ID_MODES:
        raise ValueError(f"Mode must be one of {ID_MODES}")
    idv = np.rint(getn(img, layer)[..., 0]).astype(np.int64)
    out = img.copy()
    name = str(out_layer).strip() or f"{layer}_{mode}"
    def parse_ids():
        import re
        want = set()
        for tok in str(ids).replace(",", " ").split():
            mt = re.fullmatch(r"(\d+)-(\d+)", tok)
            if mt:
                want.update(range(int(mt.group(1)), int(mt.group(2)) + 1))
            elif tok != "*":
                want.add(int(tok))
        return want

    if mode == "mask":
        m = np.isin(idv, list(parse_ids()))
        if invert:
            m = ~m
        return put(out, name, m.astype(np.float64), img)
    if mode == "mono":
        v = idv.astype(np.float64)
        if normalize:
            lo, hi = v.min(), v.max()
            v = (v - lo) / max(hi - lo, 1e-12)
        return put(out, name, v, img)
    from .sdf import edt_sq
    want = parse_ids()
    if want:
        # signed distance of the union of the selected ids: negative inside, positive outside, boundary between two pixels (±0.5)
        m = np.isin(idv, list(want))
        if invert:
            m = ~m
        if not m.any() or m.all():
            raise ValueError("The selected ids either have no pixels at all or fill the whole image; "
                             "there is no boundary, so the SDF is undefined")
        d = np.where(m, -(np.sqrt(edt_sq(~m)) - 0.5),
                     np.sqrt(edt_sq(m)) - 0.5)
        return put(out, name, d, img)
    # Ids empty (or *): each pixel's distance to the nearest pixel of "a different id" (>= 0.5; on both sides of a boundary
    # between pieces it's 0.5) -- each piece's own interior distance stitched into one image, for bevels / outlines
    H, W = idv.shape
    d = np.zeros((H, W))
    for k in np.unique(idv):
        mk_ = idv == k
        d[mk_] = np.sqrt(edt_sq(~mk_))[mk_] - 0.5
    return put(out, name, d, img)
