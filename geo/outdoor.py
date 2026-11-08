"""
"Outdoor" look for Geometry Preview (pcg123): an environment shot instead of an object on a studio floor.

The studio look (geo/studio.py) frames one object with an orthographic camera in a grey cyclorama -- right for an
asset turnaround, wrong for a street or a valley, where the picture is about scale and depth. This look adds:

  - a **perspective camera**: the Camera node's (any fov / eye / target, so a street can be shot at eye level), or,
    without one, an automatic camera at Elevation / Azimuth that frames the geometry with a 35° lens
  - a **sky**: zenith-to-horizon gradient, a sun disc and its glow; what is not geometry is sky
  - **sun + sky light**: a warm sun (direction from Sun Elevation / Azimuth, world space, so the light stays put when the
    camera moves) with shadows, a blue sky dome as fill (dimmed by ambient occlusion), warm bounce from the ground
  - **aerial perspective**: distant surfaces fade toward the horizon colour (Haze), which is what makes a 2 km terrain
    read as 2 km and not as a table model
  - optionally a **ground plane** to the horizon at the bottom of the geometry (Ground Color), so a city block sits in
    a landscape instead of floating
  - PBR (orm / roughness / metallic textures) reflects the sky instead of a softbox: glass shows the sky, wet roofs the sun

Everything is linear light, then the same filmic curve and sRGB as the studio look. Pure numpy, reuses the studio
rasterizer, shadow map, AO and texture code.
"""
from __future__ import annotations

import numpy as np

from .core import POINT
from . import studio as S

SKY_ZENITH = np.array([0.11, 0.27, 0.64])
SKY_HORIZON = np.array([0.64, 0.74, 0.88])
GROUND_DEFAULT = (0.32, 0.31, 0.27)


def sun_dir(elev, azim):
    e, a = np.radians(float(elev)), np.radians(float(azim))
    return np.array([np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)])


def sky_radiance(D, L, sun=True):
    """D (n, 3) unit view rays -> (n, 3) linear sky radiance; below the horizon the horizon colour, darkened."""
    y = D[:, 1:2]
    t = np.clip(y, 0.0, 1.0) ** 0.45
    col = SKY_HORIZON[None] + (SKY_ZENITH - SKY_HORIZON)[None] * t
    col = np.where(y < 0, SKY_HORIZON[None] * (0.75 + 0.25 * np.exp(np.minimum(y, 0) * 8.0)), col)
    cos = np.clip(D @ L, -1.0, 1.0)[:, None]
    # warm glow around the sun (Mie-ish), brighter near the horizon
    glow = np.exp((cos - 1.0) / 0.08) * 0.55 + np.exp((cos - 1.0) / 0.6) * 0.12
    col = col + glow * np.array([1.0, 0.82, 0.6])[None]
    if sun:
        col = col + (np.exp((cos - 1.0) / 0.00025) * 40.0) * np.array([1.0, 0.95, 0.85])[None]
    return col * 1.25


def _env(L):
    """Environment for PBR reflections: the sky, blurred toward the dome average with roughness, plus the sun lobe."""
    def env(R, rough, Ldir, V=None):
        sharp = sky_radiance(R, L, sun=False)
        y = np.clip(R[:, 1:2], -1, 1)
        avg = np.where(y > 0, np.array([0.60, 0.64, 0.70])[None],
                       np.array(GROUND_DEFAULT)[None] * 0.6)
        r = np.clip(rough, 0, 1)[:, None]
        base = sharp * (1 - r) + avg * r
        w0, w = 0.0015, 0.0015 + 0.6 * np.clip(rough, 0, 1) ** 2
        lobe = np.exp((R @ L - 1.0) / w) * (w0 / w)
        return base + (60.0 * lobe)[:, None] * np.array([1.0, 0.93, 0.82])[None]
    return env


def auto_camera(geo, W, H, elev, azim, fov=35.0, margin=1.04):
    """Perspective camera looking from elev / azim at the bounding box centre, as close as the projected box allows."""
    from . import render as R
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    lo, hi = P.min(0), P.max(0)
    ctr = (lo + hi) / 2
    _, r, u, f = R.look_at(R.orbit_eye(ctr, 1.0, elev, azim), ctr)
    sub = P[:: max(1, len(P) // 20000)] - ctr
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) - ctr
    Q = np.concatenate([sub, corners])
    th = np.tan(np.radians(fov / 2)) / margin
    ta = th * W / float(H)
    x, y, z = Q @ r, Q @ u, Q @ f
    d = float(max((np.abs(x) / ta - z).max(), (np.abs(y) / th - z).max(), 1e-3))
    return R.camera(None, "perspective", eye=ctr - f * d, target=ctr, fov=fov, xres=W, yres=H,
                    near=d * 1e-3, far=0.0)


def render_outdoor(geo, width=512, height=512, cam=None, elev=25.0, azim=35.0, color_attrib="Cd", ssaa=2,
                   textures="", tex_root=None, material_attrib="material", uv_attrib="uv", sun_elev=35.0,
                   sun_azim=135.0, haze=1.0, ground=True, ground_color=GROUND_DEFAULT, exposure=1.0,
                   report=None, tex_cop=None):
    """(H, W, 3) float32 sRGB 0..1, row 0 = top. cam: a Camera node dict (its projection is forced to perspective)."""
    from . import render as R
    from .convert import _attrib_image
    k = max(1, min(int(ssaa), 4))
    W, H = int(width) * k, int(height) * k
    L = sun_dir(sun_elev, sun_azim)
    have = geo is not None and geo.npoints > 0 and geo.nprims > 0
    if cam is not None:
        c = dict(cam)
        c.update(projection="perspective", xres=W, yres=H)
        c["near"] = max(float(c.get("near") or 0.0), 1e-3)
        cam = c
    elif have:
        cam = auto_camera(geo, W, H, elev, azim)
    else:
        cam = R.camera(None, "perspective", eye=(0, 2, 8), target=(0, 1, 0), xres=W, yres=H)
    eye, fwd, rgt, up = (np.asarray(cam[k_], np.float64) for k_ in ("eye", "forward", "right", "up"))
    th = np.tan(np.radians(cam["fov"] * 0.5))
    aspect = W / float(H)
    # view ray per pixel (row 0 = bottom, rasterizer convention)
    jj, ii = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    ndx = (jj + 0.5) / W * 2 - 1
    ndy = (ii + 0.5) / H * 2 - 1
    D = (fwd[None, None] + rgt[None, None] * (ndx * th * aspect)[..., None]
         + up[None, None] * (ndy * th)[..., None]).astype(np.float32)
    del jj, ii, ndx, ndy
    D /= np.linalg.norm(D, axis=-1, keepdims=True)
    img = np.zeros((H, W, 3), np.float32)
    if not have:
        img[:] = S.linear_to_srgb(S.filmic(sky_radiance(D.reshape(-1, 3), L).reshape(H, W, 3) * exposure))
        return S._finish(img, k)

    rast = R.rasterize(geo, cam, max_pairs=S._PAIRS)
    hit = rast["hit"]
    m = hit >= 0
    dfw = (D @ fwd.astype(np.float32))                      # cos between ray and forward: z -> distance
    dist = np.where(m, rast["z"] / np.maximum(dfw, 1e-6), np.inf).astype(np.float32)
    P = (eye[None, None] + D * np.where(m, dist, 0.0)[..., None]).astype(np.float32)
    N = S._smooth_normals(geo, rast).astype(np.float32)
    FN = R._face_normals(geo, rast).astype(np.float32)
    flip = (FN * D).sum(-1) > 0
    N[flip] *= -1
    FN[flip] *= -1

    lo, hi = (np.asarray(v, np.float64) for v in geo.bbox())
    center = (lo + hi) / 2
    radius = max(float(np.linalg.norm(hi - lo)) / 2, 1e-6)
    gplane = np.zeros(m.shape, bool)
    if ground:
        gy = lo[1] - 1e-4 * radius
        with np.errstate(divide="ignore", invalid="ignore"):
            tg = ((gy - eye[1]) / D[..., 1]).astype(np.float32)
        gplane = (D[..., 1] < -1e-5) & (tg > 0) & ((~m) | (tg < dist))
        P[gplane] = eye.astype(np.float32)[None] + D[gplane] * tg[gplane][:, None]
        dist[gplane] = tg[gplane]
        N[gplane] = (0.0, 1.0, 0.0)
        FN[gplane] = (0.0, 1.0, 0.0)
        del tg
    surf = m & ~gplane
    valid = surf | gplane

    alb = np.full((H, W, 3), S.srgb_to_linear(np.array([0.72, 0.72, 0.72])), np.float32)
    cd = _attrib_image(geo, rast, str(color_attrib).strip() or "Cd")
    if cd is not None:
        cd = np.repeat(cd, 3, -1) if cd.shape[2] == 1 else cd[..., :3]
        alb[m] = S.srgb_to_linear(cd[m])
    del cd
    alb[gplane] = S.srgb_to_linear(np.asarray(ground_color, np.float64))
    tex = S.parse_textures(textures)
    rep = {"used": [], "missing": []}
    pbr = {"ao": np.ones((H, W), np.float32), "roughness": np.full((H, W), 0.5, np.float32),
           "metallic": np.zeros((H, W), np.float32)}
    if tex:
        S._apply_textures(geo, rast, alb, N, surf, tex, tex_root, material_attrib, uv_attrib, rep, tex_cop, pbr)
    use_pbr = any(sl in tex for sl in S._PBR_SLOTS)
    rast = None
    if report is not None:
        report.update({k_: sorted(set(v)) for k_, v in rep.items()})

    # sun shadows: the shadow map frames the geometry; the ground plane beyond it is lit
    # the shadow map frames what the camera sees (a big scene shot from inside would get coarse texels otherwise)
    vis_p = P[surf][:: max(1, int(surf.sum()) // 200000)].astype(np.float64) if surf.any() else None
    if vis_p is not None and len(vis_p) > 16:
        sc = np.median(vis_p, 0)
        sr = float(np.percentile(np.linalg.norm(vis_p - sc, axis=1), 97)) * 1.1
        sc_, sr_ = (sc, sr) if sr < radius else (center, radius)
    else:
        sc_, sr_ = center, radius
    sh = S._shadow(geo, P, FN, valid, L, sc_, sr_, res=4096 if k * max(width, height) > 1500 else 2048)
    L32 = L.astype(np.float32)
    ndl_g = np.clip(FN @ L32, 0.0, 1.0)
    t_ = np.clip((ndl_g - 0.03) / 0.25, 0.0, 1.0)
    sh = 1.0 - (1.0 - sh) * (t_ * t_ * (3 - 2 * t_))
    # AO: screen space at the output resolution; a world radius relative to the scene, pixel size at the median depth
    sub = (slice(None, None, k), slice(None, None, k))
    dmed = float(np.median(dist[surf])) if surf.any() else radius
    px_world = dmed * 2 * th / H * k
    occ = S._ssao(P[sub].astype(np.float32), N[sub].astype(np.float32), valid[sub], px_world,
                  max(radius * 0.035, px_world * 3))
    occ = np.repeat(np.repeat(occ, k, 0), k, 1)[:H, :W]

    sun = np.array([1.0, 0.93, 0.82]) * 3.2 * max(0.15, min(1.0, L[1] * 2.5))
    sky_amb = np.array([0.42, 0.48, 0.60]) * 0.85
    bounce = np.asarray(S.srgb_to_linear(np.asarray(ground_color, np.float64))) * 0.9
    cam_d = float(np.linalg.norm(eye - center))
    env = _env(L)
    # shading per chunk of pixels: the PBR and haze terms make a dozen float64 (n, 3) temporaries, which over a whole
    # supersampled frame were the render's memory peak (several gigabytes)
    so_all = np.nonzero(valid)
    step = 1 << 19
    for s0 in range(0, len(so_all[0]), step):
        so = (so_all[0][s0:s0 + step], so_all[1][s0:s0 + step])
        n_ = N[so].astype(np.float64)
        up_ = 0.5 + 0.5 * n_[:, 1:2]
        amb = bounce[None] * (1 - up_) + sky_amb[None] * up_
        lit = np.clip(n_ @ L, 0.0, 1.0) * sh[so]
        occ_s = occ[so] * pbr["ao"][so]
        Dv = D[so].astype(np.float64)
        if use_pbr:
            lin = S._shade_pbr(alb[so], n_, -Dv, L, sun, lit, amb, occ_s,
                               pbr["roughness"][so], pbr["metallic"][so], env=env)
        else:
            Hh = L[None] - Dv
            Hh /= np.linalg.norm(Hh, axis=1, keepdims=True)
            spec = np.clip((n_ * Hh).sum(1), 0, 1) ** 40 * 0.08
            lin = alb[so] * (sun * lit[:, None] + amb * occ_s[:, None]) + (spec * lit)[:, None] * sun
        # aerial perspective: in-scattered horizon light over distance (relative to the scene size); haze 0 = none
        ds = dist[so].astype(np.float64)
        f = 1.0 - np.exp(-float(haze) * np.maximum(ds - cam_d * 0.6, 0.0) / (radius * 14.0 + cam_d * 3.0))
        fogc = sky_radiance(_flat(Dv), L, sun=False)
        lin = lin * (1 - f[:, None]) + fogc * f[:, None]
        img[so] = S.linear_to_srgb(S.filmic(lin * exposure))
    sk_all = np.nonzero(~valid)
    for s0 in range(0, len(sk_all[0]), step):
        sk = (sk_all[0][s0:s0 + step], sk_all[1][s0:s0 + step])
        img[sk] = S.linear_to_srgb(S.filmic(sky_radiance(D[sk].astype(np.float64), L) * exposure))
    return S._finish(img, k)


def _flat(D):
    """View rays flattened toward the horizon: the colour of the haze a ray runs into."""
    F = np.asarray(D, np.float64).copy()
    F[:, 1] = np.clip(F[:, 1], -0.02, 0.06)
    return F / np.linalg.norm(F, axis=1, keepdims=True)
