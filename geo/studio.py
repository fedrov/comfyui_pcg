"""
"Studio" look for Preview Image (PCG) (pcg110): a presentable still of a geometry, still pure numpy.

What the basic preview lacks and this adds:
  - smooth shading from point / vertex N (the basic one shades flat per face)
  - a key light with **shadows** (shadow map from the light, 3x3 PCF), a sky / ground hemisphere fill, a soft
    specular highlight, all in linear light, then a filmic curve and sRGB
  - **ambient occlusion** from the depth buffer (screen space, a dozen directions at two radii)
  - a ground plane under the object that only catches shadow and occlusion and fades into a vertical **gradient
    background**, so objects sit on something instead of floating in black
  - **textures**: BaseColor images mapped by a prim material attribute and the uv attribute (wrap repeat, bilinear,
    sRGB decoded), the same "slot = path" idea as Export Mesh; everything without a texture keeps its Cd
  - **PBR when roughness / metallic are given** (pcg116): an orm, roughness or metallic texture switches the surface
    to metal-rough shading -- GGX highlight from the key light plus a reflected studio environment (sky / ground
    gradient and a softbox), Schlick Fresnel through the analytic environment BRDF, F0 = 0.04 for dielectrics and
    BaseColor for metals. Without them the shading is the plain look below, unchanged: a dark tinted glass or a
    scratched metal has nothing to show in a diffuse-only render and came out as black plastic
  - supersampling (render at k x the size, box-filter down) for clean edges

Same orthographic camera direction as the basic preview, but framed on the object's projected extent (with a small
margin), so wide images of wide subjects are filled.
"""
from __future__ import annotations

import os

import numpy as np

from .core import POINT, PRIM, VERTEX, is_string


EXPOSURE = 1.0
# Rasterizer batch size: the default (16 M candidate pairs) is tuned for speed on big meshes; at supersampled
# resolutions a few screen-filling triangles already reach it and the batch arrays take over a gigabyte
_PAIRS = 1 << 21

# ─────────────────────────────────────────────────────────────── colour
def srgb_to_linear(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def filmic(x):
    """ACES fitted curve (Narkowicz): gentle shoulder, keeps saturated colours from clipping to white."""
    x = np.maximum(x, 0.0)
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0)


# ─────────────────────────────────────────────────────────────── textures
TEX_SLOTS = ("basecolor", "normal", "orm", "ao", "roughness", "metallic",
             # detail maps (as in an engine's terrain / detail texturing): up to four tiled maps blended by a
             # weights layer, multiplying the base colour (0.5 = no change) and bending the normal
             "detail1", "detail2", "detail3", "detail4",
             "detail_normal1", "detail_normal2", "detail_normal3", "detail_normal4",
             "detail_weights", "detail_tiling", "detail_triplanar")
_DETAIL_SLOTS = tuple(s_ for s_ in TEX_SLOTS if s_.startswith("detail"))
_PBR_SLOTS = ("orm", "roughness", "metallic")
_DETAIL_BLOCK = 1 << 20          # pixels per block of detail mapping


def parse_textures(text):
    """
    'slot = path' lines, the same syntax as Export Mesh's Textures: slot is basecolor, normal (tangent space,
    OpenGL +Y), orm (R = AO, G = roughness, B = metallic, as Export Mesh packs it), or one of ao / roughness /
    metallic on its own (first channel); {material} in the path is replaced by each face's material name. A value
    '@layer' takes that layer of the COP image connected to the node instead of a file (e.g. straight from COP Bake
    Textures, so no file has to be written first); '@ao roughness metallic' packs several layers like a file.
    '#' starts a comment.

    Detail maps: detail1..4 are tiled colour maps read linear, mean 0.5 = no change (the base colour is multiplied by
    2 x detail, Unity's "Detail Albedo x2"); detail_normal1..4 tangent-space normals; detail_weights a layer or file
    on the mesh uv whose channels 1..4 say how much of each detail applies (where they sum below 1 the rest is
    untouched); detail_tiling how many times the detail repeats across the uv range (a number). They sharpen close
    views of a large terrain whose own texture is a metre or so per texel; far away the detail's mips average to
    0.5 and flat, so it fades by itself. detail_triplanar = a size in world units projects the detail from the
    three axes instead (one tile per that size, blended by the normal): on a cliff the uv of a top-down terrain
    stretches a tile into streaks down the slope; projected from the side it keeps its shape.
    """
    out = {}
    for line in str(text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"Textures: expected 'slot = path', got {line!r}")
        k, v = (x.strip() for x in line.split("=", 1))
        if k.lower() not in TEX_SLOTS or not v:
            raise ValueError(f"Textures: slot must be one of {TEX_SLOTS} with a path, got {line!r}")
        if k.lower() in ("detail_tiling", "detail_triplanar"):
            try:
                float(v)
            except ValueError:
                raise ValueError(f"Textures: {k.lower()} takes a number, got {v!r}") from None
        out[k.lower()] = v
    return out


def load_texture(path, root=None, srgb=True):
    """Image -> (H, W, 3) float, row 0 = bottom (v up, as uv); sRGB decoded when srgb. 16-bit and grey are fine."""
    from PIL import Image
    p = path if os.path.isabs(path) or not root else os.path.join(root, path)
    im = Image.open(p)
    a = np.asarray(im)
    if a.dtype == np.uint16 or im.mode.startswith("I"):
        a = a.astype(np.float64) / 65535.0
    else:
        a = a.astype(np.float64) / 255.0
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, -1)
    a = a[..., :3]
    return np.ascontiguousarray((srgb_to_linear(a) if srgb else a)[::-1], np.float32)


def mip_chain(tex):
    """[tex, tex/2, tex/4, ...] by 2x2 averaging (odd sizes drop the last row / column), down to 1 px."""
    out = [tex]
    while min(out[-1].shape[:2]) > 1:
        t = out[-1]
        H, W = (t.shape[0] // 2) * 2, (t.shape[1] // 2) * 2
        out.append(t[:H, :W].reshape(H // 2, 2, W // 2, 2, -1).mean((1, 3), dtype=np.float32))
    return out


def sample_mip(chain, uv, footprint):
    """
    Bilinear from the mip level whose texel matches the pixel's footprint (in level-0 texels), blended linearly with
    the next level (trilinear). Without it a 1 m brick texture seen from afar sparkles into noise.
    """
    lod = np.clip(np.log2(np.maximum(footprint, 1e-9)), 0, len(chain) - 1)
    l0 = np.floor(lod).astype(np.int64)
    f = (lod - l0)[:, None]
    out = np.zeros((len(uv), chain[0].shape[2]))
    for lv in np.unique(l0):
        sel = l0 == lv
        a = sample_wrap(chain[lv], uv[sel])
        b = sample_wrap(chain[min(lv + 1, len(chain) - 1)], uv[sel])
        out[sel] = a * (1 - f[sel]) + b * f[sel]
    return out


def sample_wrap(tex, uv):
    """Bilinear, repeating. uv (N, 2) -> (N, 3)."""
    H, W = tex.shape[:2]
    x = np.mod(uv[:, 0], 1.0) * W - 0.5
    y = np.mod(uv[:, 1], 1.0) * H - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    x0m, x1m = x0 % W, (x0 + 1) % W
    y0m, y1m = y0 % H, (y0 + 1) % H
    return ((tex[y0m, x0m] * (1 - fx) + tex[y0m, x1m] * fx) * (1 - fy)
            + (tex[y1m, x0m] * (1 - fx) + tex[y1m, x1m] * fx) * fy)


# ─────────────────────────────────────────────────────────────── helpers
def _smooth_normals(geo, rast, fn=None):
    """Per-pixel normal (float32): vertex N > point N > face normal (fn: the face-normal image if already made)."""
    from . import render as R
    n = None
    if geo.has(VERTEX, "N"):
        n = R._interp_corner(rast, np.asarray(geo.get(VERTEX, "N"), np.float32)[:, :3]).astype(np.float32)
    elif geo.has(POINT, "N"):
        n = R._interp(rast, np.asarray(geo.get(POINT, "N"), np.float32)[:, :3]).astype(np.float32)
    if fn is None:
        fn = R._face_normals(geo, rast).astype(np.float32)
    if n is None:
        return fn.copy()
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    ok = ln[..., 0] > 1e-8
    n[ok] /= ln[ok]
    n[~ok] = fn[~ok]
    return n


def _shift(a, dy, dx, fill):
    """a shifted by (dy, dx) pixels, out-of-range filled."""
    H, W = a.shape[:2]
    out = np.full_like(a, fill)
    ys = slice(max(dy, 0), H + min(dy, 0))
    yd = slice(max(-dy, 0), H + min(-dy, 0))
    xs = slice(max(dx, 0), W + min(dx, 0))
    xd = slice(max(-dx, 0), W + min(-dx, 0))
    out[yd, xd] = a[ys, xs]
    return out


def _ssao(P, N, valid, px_world, radius_world, samples=12):
    """
    Screen-space AO on world positions (Alchemy-style estimator): for sample points s around a pixel,
    occlusion += max(0, (s - p)·n - bias) / (|s - p|² + eps), with a range falloff. Two radii (contact + broad).
    Returns 0..1 visibility.
    """
    H, W = valid.shape
    occ = np.zeros((H, W))
    cnt = 0
    for rad in (radius_world * 0.25, radius_world):
        rpx = max(1, min(int(round(rad / max(px_world, 1e-12))), max(1, min(H, W) // 6)))
        for k in range(samples):
            a = 2 * np.pi * (k + 0.5 * (rad == radius_world)) / samples
            frac = 0.35 + 0.65 * ((k * 7) % samples) / samples
            dx = int(round(np.cos(a) * rpx * frac))
            dy = int(round(np.sin(a) * rpx * frac))
            if dx == 0 and dy == 0:
                continue
            Ps = _shift(P, dy, dx, 0.0)
            vs = _shift(valid.astype(np.float64), dy, dx, 0.0) > 0.5
            v = Ps - P
            d2 = (v * v).sum(-1)
            dn = (v * N).sum(-1)
            bias = 0.02 * rad
            o = np.maximum(dn - bias, 0.0) / (d2 + 0.01 * rad * rad)
            o *= np.clip(1.0 - d2 / (rad * rad * 4.0), 0.0, 1.0)      # falloff: far samples don't count
            occ += np.where(vs, o * rad, 0.0)
            cnt += 1
    vis = 1.0 - np.clip(occ / max(cnt, 1) * 1.6, 0.0, 0.75)     # never fully black: AO is a soft term
    return np.where(valid, vis, 1.0)


# ─────────────────────────────────────────────────────────────── main
def render_studio(geo, width=512, height=512, elev=25.0, azim=35.0, color_attrib="Cd",
                  ssaa=2, textures="", tex_root=None, material_attrib="material", uv_attrib="uv",
                  shadows=True, ao=True, ground=True, report=None, tex_cop=None, detail_cop=None):
    """
    (H, W, 3) float32 sRGB 0..1, row 0 = top (ComfyUI IMAGE). If report is a dict it receives the texture files
    used and the ones not found ("used" / "missing").
    """
    from . import render as R
    from .convert import _attrib_image
    k = max(1, min(int(ssaa), 4))
    W, H = int(width) * k, int(height) * k
    # background: vertical gradient (display space)
    t = np.linspace(0.0, 1.0, H)[:, None, None]          # 0 = bottom row (rasterizer convention)
    bg_top, bg_bot = np.array([0.36, 0.38, 0.41]), np.array([0.17, 0.175, 0.185])
    img = np.broadcast_to((bg_bot + (bg_top - bg_bot) * t).astype(np.float32), (H, W, 3)).copy()
    if geo is None or geo.npoints == 0 or geo.nprims == 0:
        return _finish(img, k)
    cam = R.camera(geo, "orthographic", xres=W, yres=H, elev=float(elev), azim=float(azim),
                   frame_geometry=True, margin=1.05)
    center, radius = cam["target"], cam["radius"]
    # Frame the projected extent instead of the bounding sphere: a row of objects in a wide image fills it instead of
    # sitting small in the middle (the sphere fits the image height only)
    Pp = np.asarray(geo.get(POINT, "P"), np.float64) - cam["target"]
    xr, yr = Pp @ cam["right"], Pp @ cam["up"]
    cx, cy = (xr.min() + xr.max()) / 2, (yr.min() + yr.max()) / 2
    aspect0 = W / float(H)
    cam["ortho_size"] = max((yr.max() - yr.min()), (xr.max() - xr.min()) / aspect0, 1e-6) * 1.2
    shift = cam["right"] * cx + cam["up"] * cy
    cam["eye"] = cam["eye"] + shift
    cam["target"] = cam["target"] + shift
    rast = R.rasterize(geo, cam, max_pairs=_PAIRS)
    hit = rast["hit"]
    m = hit >= 0

    # world position of every pixel on the view plane, then along the view direction
    half = cam["ortho_size"] * 0.5
    aspect = W / float(H)
    jj, ii = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    ndx = (jj + 0.5) / W * 2 - 1
    ndy = (ii + 0.5) / H * 2 - 1
    base = (cam["eye"][None, None] + cam["right"][None, None] * (ndx * half * aspect)[..., None]
            + cam["up"][None, None] * (ndy * half)[..., None]).astype(np.float32)
    del jj, ii, ndx, ndy
    fwd = cam["forward"]
    P = base + (fwd[None, None] * rast["z"][..., None]).astype(np.float32)
    N = _smooth_normals(geo, rast).astype(np.float32)
    FN = R._face_normals(geo, rast).astype(np.float32)
    # make normals face the camera (double-sided surfaces, flipped faces); the geometric normal decides
    # a face seen from behind turns its normals to the viewer; an authored normal that already faces the viewer stays
    # (grass and foliage cards carry the ground's up as N, so both sides of a blade shade like the ground)
    flip = (FN * fwd).sum(-1) > 0
    N[flip & ((N * fwd).sum(-1) > 0)] *= -1
    FN[flip] *= -1

    # ground plane: y just below the object, catches shadow / AO only
    mn, mx = (np.asarray(v, np.float64) for v in geo.bbox())
    gy = mn[1] - 1e-4 * radius
    gplane = np.zeros(m.shape, bool)
    # (all full-frame buffers stay float32 and are written in place: at a supersampled 1600 x 1066 frame each float64
    # x 3 temporary is 160 MB, and the render used to peak near 3 GB)
    if ground and abs(fwd[1]) > 1e-3:
        tp = ((gy - base[..., 1]) / fwd[1]).astype(np.float32)
        gplane = (tp > 0) & ((~m) | (tp < rast["z"]))
        P[gplane] = base[gplane] + fwd.astype(np.float32)[None] * tp[gplane][:, None]
        N[gplane] = (0.0, 1.0, 0.0)
        FN[gplane] = (0.0, 1.0, 0.0)
        del tp
    del base
    surf = m & ~gplane
    valid = surf | gplane

    # albedo (linear)
    alb = np.full((H, W, 3), srgb_to_linear(np.array([0.72, 0.72, 0.72])), np.float32)
    cd = _attrib_image(geo, rast, str(color_attrib).strip() or "Cd")
    if cd is not None:
        cd = np.repeat(cd, 3, -1) if cd.shape[2] == 1 else cd[..., :3]
        alb[m] = srgb_to_linear(cd[m])
    del cd
    tex = parse_textures(textures)
    rep = {"used": [], "missing": []}
    # material maps; a face without one keeps the defaults (no extra occlusion, roughness 0.5, dielectric)
    pbr = {"ao": np.ones((H, W), np.float32), "roughness": np.full((H, W), 0.5, np.float32),
           "metallic": np.zeros((H, W), np.float32)}
    if tex:
        _apply_textures(geo, rast, alb, N, m, tex, tex_root, material_attrib, uv_attrib, rep, tex_cop, pbr,
                        cop_detail=detail_cop, P=P)
    use_pbr = any(sl in tex for sl in _PBR_SLOTS)
    rast = None                                   # bary / z / hit are not needed past this point
    if report is not None:
        report.update({k: sorted(set(v)) for k, v in rep.items()})

    # lights (key from the upper side, relative to the camera so the look does not depend on azimuth)
    a = np.radians(float(azim) + 50.0)
    e = np.radians(55.0)
    Ldir = np.array([np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)])
    key = np.array([1.0, 0.95, 0.88]) * 1.55
    sky, gnd = np.array([0.42, 0.48, 0.58]) * 0.75, np.array([0.20, 0.18, 0.16]) * 0.75
    L32 = Ldir.astype(np.float32)
    ndl = np.clip(N @ L32, 0.0, 1.0)
    # pcg125: the key is a softbox, not a point -- soft shadows that are crisp at contact and widen with distance
    # (skylight.sun_shadow), from one 2048² depth map
    from . import skylight as K
    T = K.soup(geo)[1] if (shadows or ao) else None
    sh = np.ones(m.shape, np.float32)
    if shadows:
        dmap, meta = K.depth_map(T, Ldir, center, radius * 1.05, 2048)
        vi = np.nonzero(valid)
        stp = 1 << 20
        for s0 in range(0, len(vi[0]), stp):
            sel = (vi[0][s0:s0 + stp], vi[1][s0:s0 + stp])
            sh[sel] = K.sun_shadow(dmap, meta, P[sel], FN[sel], softness=0.07, max_px=48.0)
        del dmap
    # shadow terminator: near the light's horizon a coarse mesh shadows its own facets in steps while the smooth
    # normal says "barely lit" -- fade the shadow in only where the facet clearly faces the light
    ndl_g = np.clip(FN @ L32, 0.0, 1.0)
    t_ = np.clip((ndl_g - 0.05) / 0.3, 0.0, 1.0)
    sh = 1.0 - (1.0 - sh) * (t_ * t_ * (3 - 2 * t_))
    px_world = cam["ortho_size"] / H
    if ao:
        # AO is a soft term: compute it at the output resolution (every k-th supersample) and spread it back
        sub = (slice(None, None, k), slice(None, None, k))
        occ = _ssao(P[sub].astype(np.float32), N[sub].astype(np.float32), valid[sub], px_world * k,
                    radius * 0.18)
        # pcg125: large-scale occlusion from the dome of the studio (24 directions, each a depth map): how much of
        # the surroundings a point can see. Screen-space AO only knows what is on screen and within its radius;
        # this grounds the object (a soft pool of shade under and between things) and darkens deep creases
        vs = valid[sub]
        if vs.any():
            _, dv = K.sky_dome(T, P[sub][vs], N[sub][vs], center, radius * 1.05, Ldir,
                               lambda d_: np.ones((len(d_), 3)), np.zeros(3), k=24, res=384)
            occ = occ ** 0.5
            occ[vs] *= 0.3 + 0.7 * dv
        occ = np.repeat(np.repeat(occ, k, 0), k, 1)[:H, :W]
    else:
        occ = np.ones(m.shape, np.float32)
    # shading only where it is needed (pixels as flat lists): the object, and the part of the ground that shows
    V = -fwd
    Hh = Ldir + V
    Hh /= np.linalg.norm(Hh)
    so = np.nonzero(surf)
    n_ = N[so]
    amb = gnd + (sky - gnd) * (0.5 + 0.5 * n_[:, 1:2])
    spec = np.clip(n_ @ Hh, 0, 1) ** 48 * 0.12
    lit = ndl[so] * sh[so]
    occ_s = occ[so] * pbr["ao"][so]
    if use_pbr:
        lin = _shade_pbr(alb[so], n_, V, Ldir, key, lit, amb, occ_s, pbr["roughness"][so], pbr["metallic"][so])
    else:
        lin = alb[so] * (key * lit[:, None] + amb * occ_s[:, None]) + (spec * lit)[:, None] * key * 0.5
    img[so] = linear_to_srgb(filmic(lin * EXPOSURE))
    if gplane.any():
        gi = np.nonzero(gplane)
        rr = np.hypot(P[gi][:, 0] - center[0], P[gi][:, 2] - center[2])
        fade = np.clip(1.0 - (rr - radius * 0.9) / (radius * 1.2), 0.0, 1.0) ** 1.5
        keep = fade > 0
        ga = gnd + (sky - gnd)                           # ground normal is +y: full sky
        # only the darkening is kept (shadow catcher): ratio of lit ground to unshadowed ground. Chunked: these are
        # most of the frame, and the tone curve makes several float64 copies of each
        gy_, gx_, fw = gi[0][keep], gi[1][keep], fade[keep]
        step = 1 << 20
        for s0 in range(0, len(fw), step):
            go = (gy_[s0:s0 + step], gx_[s0:s0 + step])
            nd = ndl[go][:, None]
            unlit = linear_to_srgb(filmic((key * nd + ga) * EXPOSURE * 0.3))
            glit = linear_to_srgb(filmic((key * nd * sh[go][:, None] + ga * occ[go][:, None]) * EXPOSURE * 0.3))
            ratio = np.clip(glit / np.maximum(unlit, 1e-6), 0, 1)
            w = fw[s0:s0 + step][:, None]
            # the floor under the object is a pool of light (brighter than the backdrop it fades into), and the
            # shadow / occlusion darkening is applied nearly in full so the object visibly stands on it
            img[go] = img[go] * (1 - w) + np.minimum(img[go] * 1.45, 1.0) * (0.22 + 0.78 * ratio) * w
    return _finish(img, k)


# ─────────────────────────────────────────────────────────────── PBR (pcg116)
# The studio as reflections see it (linear radiance): a bright ceiling, a lighter band at the horizon (the walls of
# a cyclorama), the lit floor, and a softbox in the key light's direction
ENV_TOP = np.array([0.95, 0.98, 1.05])
ENV_HORIZON = np.array([0.55, 0.56, 0.58])
ENV_FLOOR = np.array([0.30, 0.29, 0.28])
SOFTBOX = 8.0
STRIP = 2.5           # a tall strip light beside the camera: what vertical glossy faces and spheres reflect
STRIP_AZ = 40.0       # degrees from the camera, toward the side opposite the key


def env_radiance(R, rough, Ldir, V=None):
    """
    The studio around the object as reflections see it: ceiling above, floor below, a horizon whose blur grows with
    roughness, and a softbox toward the key light. For a rough surface the softbox lobe widens and dims by the same
    factor (about energy preserving), so a polished surface shows a small bright window, a satin one a broad sheen.
    R (n, 3) unit, rough (n,) -> (n, 3) linear radiance; V (the direction to the camera) places the strip light.
    """
    k = 0.04 + 0.6 * rough
    y = R[:, 1:2]
    up = np.clip((y + k[:, None]) / (2 * k[:, None]), 0.0, 1.0)
    up = up * up * (3 - 2 * up)
    top = ENV_HORIZON[None] + (ENV_TOP - ENV_HORIZON)[None] * np.clip(y, 0.0, 1.0) ** 0.6
    base = ENV_FLOOR[None] + (top - ENV_FLOOR[None]) * up
    w0, w = 0.04, 0.04 + 0.7 * rough * rough
    lobe = np.exp((R @ Ldir - 1.0) / w) * (w0 / w)
    out = base + (SOFTBOX * lobe)[:, None] * np.array([1.0, 0.97, 0.92])[None]
    if V is not None:
        # strip: narrow in azimuth, tall (from below the horizon to about 40° up), fixed relative to the camera
        vh = np.array([V[0], 0.0, V[2]])
        if np.linalg.norm(vh) > 1e-6:
            vh /= np.linalg.norm(vh)
            side = np.sign(np.cross(vh, np.array([Ldir[0], 0.0, Ldir[2]]))[1]) or 1.0
            a = np.radians(-side * STRIP_AZ)
            S = np.array([vh[0] * np.cos(a) + vh[2] * np.sin(a), 0.0, -vh[0] * np.sin(a) + vh[2] * np.cos(a)])
            rh = R * np.array([1.0, 0.0, 1.0])
            rh /= np.maximum(np.linalg.norm(rh, axis=1, keepdims=True), 1e-9)
            ws = 0.01 + 0.5 * rough * rough
            band = np.exp((rh @ S - 1.0) / ws) * (0.01 / ws) ** 0.5
            yy = R[:, 1]
            tall = np.clip((yy + 0.15) / 0.1, 0, 1) * np.clip((0.65 - yy) / 0.1, 0, 1)
            out = out + (STRIP * band * tall)[:, None]
    return out


def env_brdf(f0, rough, nv):
    """Karis' analytic fit of the split-sum environment BRDF: F0 * A + B, with Schlick Fresnel built in."""
    c0 = np.array([-1.0, -0.0275, -0.572, 0.022])
    c1 = np.array([1.0, 0.0425, 1.04, -0.04])
    r = rough[:, None] * c0[None] + c1[None]
    a004 = np.minimum(r[:, 0] * r[:, 0], np.exp2(-9.28 * nv)) * r[:, 0] + r[:, 1]
    A = -1.04 * a004 + r[:, 2]
    B = 1.04 * a004 + r[:, 3]
    return f0 * A[:, None] + B[:, None]


def _shade_pbr(alb, n, V, Ldir, key, lit, amb, occ, rough, metal, env=None, spec_occ=None):
    """Metal-rough shading of the surface pixels (flat lists). -> (n, 3) linear. env: radiance function of the
    surroundings (default the studio); V is one direction (orthographic) or one per pixel (perspective)."""
    rough = np.clip(rough, 0.03, 1.0).astype(np.float64)
    metal = np.clip(metal, 0.0, 1.0).astype(np.float64)[:, None]
    f0 = 0.04 * (1 - metal) + alb * metal
    diff = alb * (1 - metal)
    V = np.asarray(V, np.float64)
    per = V.ndim == 2
    dot = (lambda a, b: (a * b).sum(-1)) if per else (lambda a, b: a @ b)
    nv = np.clip(dot(n, V), 1e-4, 1.0)
    # key light: GGX D, Smith-GGX correlated visibility, Schlick F
    Hh = Ldir[None] + V if per else Ldir + V
    Hh = Hh / np.linalg.norm(Hh, axis=-1, keepdims=True)
    nh = np.clip(dot(n, Hh), 0.0, 1.0)
    nl = np.clip(n @ Ldir, 0.0, 1.0)
    a2 = (rough * rough) ** 2
    D = a2 / (np.pi * (nh * nh * (a2 - 1) + 1) ** 2)
    vis = 0.5 / np.maximum(nl * np.sqrt(nv * nv * (1 - a2) + a2) + nv * np.sqrt(nl * nl * (1 - a2) + a2), 1e-6)
    vh = np.clip(dot(V, Hh) if per else V @ Hh, 0.0, 1.0)
    F = f0 + (1 - f0) * ((1 - vh) ** 5)[:, None] if per else f0 + (1 - f0) * ((1 - vh) ** 5)
    spec_key = F * (D * vis * nl)[:, None] * np.pi        # lit already carries n·l and the shadow; π: punctual units
    # environment: reflected studio, dimmed by occlusion (specular occlusion ≈ AO)
    Rv = 2 * nv[:, None] * n - (V if per else V[None])
    Rv = Rv / np.linalg.norm(Rv, axis=1, keepdims=True)
    envr = env(Rv, rough, Ldir) if env is not None else env_radiance(Rv, rough, Ldir, V)
    spec_env = env_brdf(f0, rough, nv) * envr * (occ if spec_occ is None else spec_occ)[:, None]
    shadowed = np.where(nl > 1e-6, lit / np.maximum(nl, 1e-6), 0.0)
    return (diff * (key * lit[:, None] + amb * occ[:, None])
            + spec_key * key * shadowed[:, None] + spec_env)


def _cop_texture(cop, layer, slot):
    """
    COP layer -> (H, W, 3) like load_texture: basecolor is already linear; a normal layer is re-encoded to 0..1.
    Several names ('ao roughness metallic') take the first channel of each, packed in that order. A single-value slot
    (ao / roughness / metallic) stays one channel. Read as float32 without a float64 copy: a 4096² terrain set is
    hundreds of megabytes per layer.
    """
    from .cop import backend as _bk
    if cop is None:
        raise ValueError(f"Textures: '@{layer}' needs a COP image connected to the textures input")

    def get(n):
        a = cop.need(str(n).strip())
        return np.asarray(_bk.backend_of(a).to_numpy(a), np.float32)
    names = str(layer).split()
    if len(names) > 1:
        a = np.concatenate([get(n)[..., :1] for n in names[:3]], -1)
        if a.shape[2] < 3:
            a = np.concatenate([a, np.zeros(a.shape[:2] + (3 - a.shape[2],), np.float32)], -1)
    else:
        a = get(layer)
        if slot in ("ao", "roughness", "metallic"):
            return np.ascontiguousarray(a[..., :1])
        if slot == "detail_weights":                   # up to four weights, channel by channel
            return np.ascontiguousarray(a[..., :4])
    if a.shape[2] == 1:
        a = np.repeat(a, 3, -1)
    a = a[..., :3]
    if slot == "normal" and a.min() < -1e-6:          # signed (-1..1, as COP Bake Textures writes it)
        a = a * np.float32(0.5) + np.float32(0.5)
    return np.ascontiguousarray(a, np.float32)


def _material_frames(geo, rast, tgt, uvattr, mattr_values, mat):
    """
    Tangent frames (N, T, handedness) at the pixels tgt, from the corner frames of this material's triangles only
    (meshexport.corner_frames_subset): computing them for the whole scene cost gigabytes for one normal-mapped terrain
    under a forest of proxies. mattr_values None = every triangle.
    """
    from .meshexport import corner_frames_subset
    src = rast["src"]
    if mattr_values is None:
        tri_mask = np.ones(len(src), bool)
    else:
        names = np.asarray(mattr_values)[:, 0]
        prim_ok = np.fromiter((str(x) == mat for x in names), bool, len(names)) if names.dtype == object \
            else names.astype(str) == mat
        tri_mask = prim_ok[src]
    vids, Nc, T4 = corner_frames_subset(geo, uvattr, rast["tri"], rast["cor"], tri_mask)
    t = rast["hit"][tgt]
    w = rast["bary"][tgt]
    ids = np.searchsorted(vids, rast["cor"][t])
    ids = np.minimum(ids, len(vids) - 1)

    def interp(V):
        V = np.asarray(V, np.float32)
        return (V[ids[:, 0]] * w[:, 0:1] + V[ids[:, 1]] * w[:, 1:2] + V[ids[:, 2]] * w[:, 2:3]).astype(np.float32)
    hand = T4[ids[:, 0], 3]
    return interp(Nc), interp(T4[:, :3]), np.where(hand == 0, 1.0, hand).astype(np.float32)


def _masked_interp(rast, idx, values, corner):
    """Interpolate per-point (corner=False) or per-corner values only at the pixels idx -> (n, C) float32."""
    t = rast["hit"][idx]
    w = rast["bary"][idx]
    ids = rast["cor"][t] if corner else rast["tri"][t]
    V = np.asarray(values, np.float32)
    return (V[ids[:, 0]] * w[:, 0:1] + V[ids[:, 1]] * w[:, 1:2] + V[ids[:, 2]] * w[:, 2:3]).astype(np.float32)


def _apply_textures(geo, rast, alb, N, m, tex, root, mattr, uvattr, report, cop=None, pbr=None, cop_detail=None,
                    P=None):
    """
    BaseColor into alb and tangent-space normal maps into N, per face material. The tangent frames are the
    per-corner set Export Mesh writes and COP Bake Textures bakes against (meshexport.corner_frames), so a baked
    normal map shows here exactly as in an engine that reads the file's tangents. A missing file leaves those faces
    as they are (Cd / mesh normal) and is listed in the report. Works on the covered pixels only (flat lists), so a
    large supersampled frame does not need full-image uv / frame buffers. orm / ao / roughness / metallic go into
    the (H, W) arrays of pbr {"ao", "roughness", "metallic"}.
    """
    hit = rast["hit"]
    idx = np.nonzero(m)
    if not len(idx[0]):
        return
    a = geo.get(PRIM, mattr)
    if a is not None and is_string(a):
        # material per pixel as a small integer code (a string per pixel is hundreds of megabytes on a big frame):
        # the names of the prims that are actually visible, numbered
        pid = rast["src"][hit[idx]]
        up, inv = np.unique(pid, return_inverse=True)
        mats, code = np.unique(np.asarray(a)[up, 0].astype(str), return_inverse=True)
        pm = code[inv].astype(np.int32)
        del pid, up, inv, code
    else:
        if any("{material}" in v for v in tex.values()):
            raise ValueError(f"Textures use {{material}} but there is no string prim attribute '{mattr}'")
        mats = np.array([""])
        pm = np.zeros(len(idx[0]), np.int32)
    if geo.has(VERTEX, uvattr):
        uv = _masked_interp(rast, idx, np.asarray(geo.get(VERTEX, uvattr))[:, :2], True)
    elif geo.has(POINT, uvattr):
        uv = _masked_interp(rast, idx, np.asarray(geo.get(POINT, uvattr))[:, :2], False)
    else:
        raise ValueError(f"Textures need a '{uvattr}' attribute (vertex or point)")
    # uv change per pixel (screen-space derivative, within the same face only) -> footprint for mip selection
    uvi = np.zeros(hit.shape + (2,), np.float32)
    uvi[idx] = uv
    dimg = np.zeros(hit.shape, np.float32)
    for ax in (0, 1):
        d = np.abs(np.diff(uvi, axis=ax)).max(-1)
        d = np.where(np.diff(hit, axis=ax) == 0, d, 0.0)
        pad = [(0, 1) if a_ == ax else (0, 0) for a_ in range(2)]
        dimg = np.maximum(dimg, np.pad(d, pad, mode="edge"))
    du = dimg[idx]
    del uvi, dimg
    frames = {}
    cache = {}
    tri = None
    if float(tex.get("detail_triplanar", "0") or 0) > 0 and "detail_weights" in tex and P is not None:
        tri = _triplanar_coords(P, N, hit, idx, float(tex["detail_triplanar"]))

    def fetch(pattern, slot, mat):
        """The mip chain for this slot's texture on this material, or None (missing: listed in the report)."""
        path = pattern.replace("{material}", mat)
        key = (path, slot)
        src = cop_detail if (cop_detail is not None and slot.startswith("detail") and slot != "detail_weights") else cop
        if path.startswith("@"):
            # a layer named per material ('@{material}_albedo') that the image does not have: like a missing
            # file, those faces keep their Cd -- lets one image texture the terrain and leave the trees alone
            if src is not None and "{material}" in pattern and any(n_ not in src for n_ in path[1:].split()):
                report["missing"].append(path)
                return None
            if key not in cache:
                cache[key] = mip_chain(_cop_texture(src, path[1:], "normal" if "normal" in slot else slot))
        else:
            full = path if os.path.isabs(path) or not root else os.path.join(root, path)
            if not os.path.exists(full):
                report["missing"].append(path)
                return None
            if key not in cache:
                cache[key] = mip_chain(load_texture(path, root, srgb=(slot == "basecolor")))
        report["used"].append(path)
        return cache[key]

    def frame_of(mi, mat, tgt):
        if mi not in frames:
            frames[mi] = _material_frames(geo, rast, tgt, uvattr, a if len(mats) > 1 or mat else None, mat)
        return frames[mi]

    for mi, mat in enumerate(str(x) for x in mats):
        sel = pm == mi
        tgt = (idx[0][sel], idx[1][sel])
        for slot, pattern in tex.items():
            if slot in _DETAIL_SLOTS:
                continue
            ch = fetch(pattern, slot, mat)
            if ch is None:
                continue
            v = sample_mip(ch, uv[sel], du[sel] * max(ch[0].shape[:2]))
            if slot == "basecolor":
                alb[tgt] = v
                continue
            if slot == "orm":
                for c, nm in enumerate(("ao", "roughness", "metallic")):
                    pbr[nm][tgt] = v[:, c]
                continue
            if slot in ("ao", "roughness", "metallic"):
                pbr[slot][tgt] = v[:, 0]
                continue
            Nn, Tt, hand = frame_of(mi, mat, tgt)
            n0 = Nn / np.maximum(np.linalg.norm(Nn, axis=-1, keepdims=True), 1e-12)
            t0 = Tt - (Tt * n0).sum(-1, keepdims=True) * n0
            t0 /= np.maximum(np.linalg.norm(t0, axis=-1, keepdims=True), 1e-12)
            b0 = np.cross(n0, t0) * hand[:, None]
            ts = v * 2.0 - 1.0
            ts /= np.maximum(np.linalg.norm(ts, axis=-1, keepdims=True), 1e-12)   # far mips average to shorter vectors
            nw = t0 * ts[:, 0:1] + b0 * ts[:, 1:2] + n0 * ts[:, 2:3]
            N[tgt] = nw / np.maximum(np.linalg.norm(nw, axis=-1, keepdims=True), 1e-12)
        if "detail_weights" in tex:
            # in blocks of pixels: each detail map makes (n, 3) float64 temporaries, a few hundred MB apiece over
            # a supersampled frame
            fr_ = frame_of(mi, mat, tgt) if any(k_.startswith("detail_normal") for k_ in tex) and tri is None else None
            on_ = np.nonzero(sel)[0]
            blk = _DETAIL_BLOCK
            for b0 in range(0, len(on_), blk):
                sb = np.zeros_like(sel)
                sb[on_[b0:b0 + blk]] = True
                tb_ = (idx[0][sb], idx[1][sb])
                fb_ = None if fr_ is None else (lambda *_x, r_=slice(b0, b0 + blk): tuple(v_[r_] for v_ in fr_))
                _apply_detail(tex, fetch, fb_, mi, mat, sb, tb_, uv, du, alb, N, tri)


# triplanar planes: (u axis, v axis) in world space; the top plane matches a terrain's uv (u east, v north = -z)
_TRI_AXES = (((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),       # seen along x
             ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),      # seen along y (from above)
             ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))       # seen along z


def _triplanar_coords(P, N, hit, idx, size):
    """
    Per plane, for the covered pixels (positions in idx) that it weighs on: (positions, uv = P / size on the plane's
    axes, mip footprint = the uv change to the next pixel, as for the mesh uv -- across a face edge too, since P is
    continuous --, blend weight, u axis, v axis). The weights are |n|^4 of the shading normal, normalised: that
    sharpens the seams to a narrow band around 45 degrees. A side plane covers a few % of a terrain, so it keeps
    only those pixels (float32: a supersampled frame has millions).
    """
    n_ = np.abs(N[idx]).astype(np.float32) ** 4
    n_ /= np.maximum(n_.sum(-1, keepdims=True), 1e-12)
    out = []
    for a_, (U, V) in enumerate(_TRI_AXES):
        pos = np.nonzero(n_[:, a_] > 1e-3)[0]
        if not len(pos):
            continue
        U, V = np.asarray(U, np.float32), np.asarray(V, np.float32)
        img = np.stack([P @ U, P @ V], -1) / np.float32(size)
        d_ = np.zeros(hit.shape, np.float32)
        for ax in (0, 1):
            d = np.abs(np.diff(img, axis=ax)).max(-1)
            d = np.where((np.diff(hit, axis=ax) == 0) | (d < 0.5), d, 0.0)    # not across a silhouette
            pad = [(0, 1) if k_ == ax else (0, 0) for k_ in range(2)]
            d_ = np.maximum(d_, np.pad(d, pad, mode="edge"))
        at = (idx[0][pos], idx[1][pos])
        out.append((pos, img[at], d_[at], n_[pos, a_], U.astype(np.float64), V.astype(np.float64)))
        del img, d_
    return out


def _apply_detail(tex, fetch, frame_of, mi, mat, sel, tgt, uv, du, alb, N, tri=None):
    """Detail maps on one material's pixels: see parse_textures. tri: _triplanar_coords (world projection) or None
    (the mesh uv x detail_tiling)."""
    wch = fetch(tex["detail_weights"], "detail_weights", mat)
    if wch is None:
        return
    w = sample_mip(wch, uv[sel], du[sel] * max(wch[0].shape[:2]))
    w = np.clip(w, 0.0, 1.0)
    if tri is not None:
        # this material's share of each plane: its pixels' positions among the selected ones
        at_sel = np.cumsum(sel) - 1
        planes = []
        for pos, uvp, fpp, wp, U, V in tri:
            m_ = sel[pos]
            if m_.any():
                planes.append((uvp[m_].astype(np.float64), fpp[m_].astype(np.float64), U, V,
                               wp[m_].astype(np.float64), at_sel[pos[m_]]))
    else:
        tiling = float(tex.get("detail_tiling", "1"))
        planes = [(uv[sel] * tiling, du[sel] * tiling, None, None, np.ones(len(w)), slice(None))]
    mult = np.ones((len(w), 3))
    nts = np.zeros((len(w), 3))          # uv mode: the tangent-space normal, weighted
    pert = np.zeros((len(w), 3))         # triplanar: the world-space tilt, weighted
    wsum = np.zeros(len(w))
    have_n = False
    for k in range(4):
        if k >= w.shape[1]:
            break
        wk = w[:, k]
        if not wk.any():
            continue
        if f"detail{k + 1}" in tex:
            ch = fetch(tex[f"detail{k + 1}"], f"detail{k + 1}", mat)
            if ch is not None:
                for uvd, dud, U, V, pw, on in planes:
                    d = sample_mip(ch, uvd, dud * max(ch[0].shape[:2]))
                    mult[on] += (wk[on] * pw)[:, None] * (2.0 * d - 1.0)
        if f"detail_normal{k + 1}" in tex:
            ch = fetch(tex[f"detail_normal{k + 1}"], f"detail_normal{k + 1}", mat)
            if ch is not None:
                for uvd, dud, U, V, pw, on in planes:
                    d = sample_mip(ch, uvd, dud * max(ch[0].shape[:2])) * 2.0 - 1.0
                    if U is None:
                        nts[on] += wk[on, None] * d
                    else:
                        # a tangent-space normal (x along the plane's u, y along its v) tilts the surface by
                        # x U + y V (over z): the gradient of the detail's height, the same from either side
                        dz = np.maximum(d[:, 2:3], 0.2)
                        pert[on] += (wk[on] * pw)[:, None] * (d[:, 0:1] * U + d[:, 1:2] * V) / dz
                wsum += wk
                have_n = True
    alb[tgt] = alb[tgt] * np.clip(mult, 0.0, 4.0)
    if not have_n:
        return
    if tri is not None:
        n0 = N[tgt].astype(np.float64)
        n0 /= np.maximum(np.linalg.norm(n0, axis=-1, keepdims=True), 1e-12)
        pert -= (pert * n0).sum(-1, keepdims=True) * n0          # tilt only, within the surface
        nw = n0 + pert
        N[tgt] = nw / np.maximum(np.linalg.norm(nw, axis=-1, keepdims=True), 1e-12)
        return
    # the weighted detail normal (flat where the weights are 0) bends the shaded normal about its own frame
    nts += (1.0 - np.clip(wsum, 0.0, 1.0))[:, None] * np.array([0.0, 0.0, 1.0])
    nts /= np.maximum(np.linalg.norm(nts, axis=-1, keepdims=True), 1e-12)
    Nn, Tt, hand = frame_of(mi, mat, tgt)
    n0 = N[tgt].astype(np.float64)
    n0 /= np.maximum(np.linalg.norm(n0, axis=-1, keepdims=True), 1e-12)
    t0 = Tt - (Tt * n0).sum(-1, keepdims=True) * n0
    t0 /= np.maximum(np.linalg.norm(t0, axis=-1, keepdims=True), 1e-12)
    b0 = np.cross(n0, t0) * hand[:, None]
    nw = t0 * nts[:, 0:1] + b0 * nts[:, 1:2] + n0 * nts[:, 2:3]
    N[tgt] = nw / np.maximum(np.linalg.norm(nw, axis=-1, keepdims=True), 1e-12)


def _finish(img, k):
    if k > 1:
        H, W = img.shape[0] // k, img.shape[1] // k
        img = img[:H * k, :W * k].reshape(H, k, W, k, 3).mean((1, 3))
    return np.ascontiguousarray(np.clip(img, 0, 1)[::-1], np.float32)
