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
from . import skylight as K

GROUND_DEFAULT = (0.32, 0.31, 0.27)


HAZE_METRES = 12000.0        # Haze 1: light falls to 1/e over 12 km (a clear, slightly hazy day)


def sun_dir(elev, azim):
    e, a = np.radians(float(elev)), np.radians(float(azim))
    return np.array([np.cos(e) * np.sin(a), np.sin(e), np.cos(e) * np.cos(a)])


def sky_radiance(D, L, sun=True):
    """D (n, 3) unit view rays -> (n, 3) linear sky radiance (clear sky; skylight.sky)."""
    return K.sky(D, L, sun=sun)


def _env(L):
    """Environment for PBR reflections: the sky, blurred toward the dome average with roughness, plus the sun lobe."""
    dd = K.dome_dirs(16)
    dome_avg = (K.sky(dd, L, sun=False) * dd[:, 1:2]).sum(0) / dd[:, 1].sum()
    sunc = K.sun_light(L) / 3.4

    def env(R, rough, Ldir, V=None):
        sharp = sky_radiance(R, L, sun=False)
        y = np.clip(R[:, 1:2], -1, 1)
        avg = np.where(y > 0, dome_avg[None], np.array(GROUND_DEFAULT)[None] * 0.6)
        r = np.clip(rough, 0, 1)[:, None]
        base = sharp * (1 - r) + avg * r
        w0, w = 0.0015, 0.0015 + 0.6 * np.clip(rough, 0, 1) ** 2
        lobe = np.exp((R @ L - 1.0) / w) * (w0 / w)
        return base + (60.0 * lobe)[:, None] * sunc[None]
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
                   report=None, tex_cop=None, clouds=0.0, cloud_seed=0, sky_samples=32, compute="auto"):
    """(H, W, 3) float32 sRGB 0..1, row 0 = top. cam: a Camera node dict (its projection is forced to perspective)."""
    try:                                   # start from a trimmed heap: the render needs a few GB of buffers
        from ..memtrim import trim as _trim
        _trim()
    except ImportError:
        pass
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
    if not have:
        sk_ = K.clouds(D.reshape(-1, 3), L, sky_radiance(D.reshape(-1, 3), L), clouds, cloud_seed)
        return _develop(sk_.reshape(H, W, 3).astype(np.float32), exposure, k)

    ts, T = K.soup(geo)
    rast = R.rasterize(geo, cam, max_pairs=S._PAIRS, soup=ts)
    hit = rast["hit"]
    m = hit >= 0
    dfw = (D @ fwd.astype(np.float32))                      # cos between ray and forward: z -> distance
    dist = np.where(m, rast["z"] / np.maximum(dfw, 1e-6), np.inf).astype(np.float32)
    P = (eye[None, None] + D * np.where(m, dist, 0.0)[..., None]).astype(np.float32)
    # face normals once (Newell, length = area): the per-pixel geometric normal, the fallback of the shading normal,
    # and the face size for the shadow normal offset
    from .ops import prim_normals as _pn
    pn = np.asarray(_pn(geo, normalize=False), np.float32)
    ar = np.linalg.norm(pn, axis=1)
    pn /= np.maximum(ar, 1e-20)[:, None]
    pid = rast["src"][hit[m]]
    FN = np.zeros((H, W, 3), np.float32)
    FN[m] = pn[pid]
    off = np.zeros(m.shape, np.float32)                      # face size per pixel, for the shadow normal offset
    off[m] = 0.5 * np.sqrt(ar[pid])
    del pn, ar, pid
    N = S._smooth_normals(geo, rast, FN)
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
    pbr = {"ao": np.ones((H, W), np.float32), "roughness": np.full((H, W), 0.8, np.float32),
           "metallic": np.zeros((H, W), np.float32)}
    if tex:
        S._apply_textures(geo, rast, alb, N, surf, tex, tex_root, material_attrib, uv_attrib, rep, tex_cop, pbr)
    use_pbr = any(sl in tex for sl in S._PBR_SLOTS)
    rast = None
    if report is not None:
        report.update({k_: sorted(set(v)) for k_, v in rep.items()})

    # sun shadows: the shadow map frames the geometry; the ground plane beyond it is lit
    # the shadow map frames what the camera sees (a big scene shot from inside would get coarse texels otherwise)
    # (receivers are what must be inside the map: the visible surfaces, and the visible ground around the geometry
    # where its shadows fall -- casters anywhere along the light direction are in the map's column anyway)
    recv = surf
    if gplane.any():
        near_g = gplane & (np.linalg.norm(P - center.astype(np.float32)[None, None], axis=-1) < radius * 1.6)
        recv = surf | near_g
        del near_g
    vis_p = P[recv][:: max(1, int(recv.sum()) // 200000)].astype(np.float64) if surf.any() else None
    if vis_p is not None and len(vis_p) > 16:
        sc = np.median(vis_p, 0)
        sr = float(np.percentile(np.linalg.norm(vis_p - sc, axis=1), 97)) * 1.1
        sc_, sr_ = (sc, sr) if sr < radius * 1.6 else (center, radius * 1.6)
    else:
        sc_, sr_ = center, radius
    # ── sun: one 4096² depth map of what the camera sees, soft shadows with contact hardening
    off[gplane] = 0.0
    sres = 4096 if k * max(width, height) > 1500 else 2048
    off = np.minimum(off, 8.0 * sr_ * 2.0 / sres)
    L32 = L.astype(np.float32)
    vi = np.nonzero(valid)
    from .progress import check as _cancel
    _cancel()
    dev = K.torch_device(compute)
    if dev is not None:
        dmap, meta = K.depth_map_t(K.to_device(T, dev), L, sc_, sr_, sres)
        dmap = dmap.cpu().numpy()
    else:
        dmap, meta = K.depth_map(T, L, sc_, sr_, sres)
    sh = np.ones(valid.shape, np.float32)
    step = 1 << 20
    for s0 in range(0, len(vi[0]), step):
        so = (vi[0][s0:s0 + step], vi[1][s0:s0 + step])
        sh[so] = K.sun_shadow(dmap, meta, P[so], FN[so], offset=off[so])
    del dmap
    # Faces turned away from the sun are in their own shadow, faces at a grazing angle fade into it (with
    # smooth-normal shading, treating grazing faces as lit lights single triangles along every terminator of a
    # coarse mesh; the normal offset in sun_shadow handles the acne)
    t_ = np.clip((FN @ L32 + 0.02) / 0.12, 0.0, 1.0)
    sh = sh * (t_ * t_ * (3 - 2 * t_))
    cam_h = max(sr_ * 1.2, 600.0)                           # cloud layer height: by the visible scene, not the bbox
    if clouds > 0:
        for s0 in range(0, len(vi[0]), step):
            so = (vi[0][s0:s0 + step], vi[1][s0:s0 + step])
            sh[so] *= K.cloud_shadow(P[so], eye, L, clouds, cloud_seed, cam_h)

    # ── sky: an area light with shadows and one bounce, at the output resolution (every k-th sample)
    sub = (slice(None, None, k), slice(None, None, k))
    dmed = float(np.median(dist[surf])) if surf.any() else radius
    px_world = dmed * 2 * th / H * k
    Ps, Ns, vs = P[sub], N[sub], valid[sub]
    occ = S._ssao(Ps.astype(np.float32), Ns.astype(np.float32), vs, px_world, max(sr_ * 0.01, px_world * 3))
    occ = occ ** 0.6                                         # contact detail only: the dome carries the large scale
    sun = K.sun_light(L)
    sky_fn = lambda d: K.sky(d, L, sun=False) * (1.0 - 0.25 * float(np.clip(clouds, 0, 1)))  # noqa: E731
    alb_mean = alb[sub][vs].mean(0).astype(np.float64) if vs.any() else np.array([0.3, 0.3, 0.3])
    lit_frac = float(sh[sub][vs].mean()) if vs.any() else 0.5
    Es = np.zeros(vs.shape + (3,), np.float32)
    vis_s = np.ones(vs.shape, np.float32)
    if vs.any() and int(sky_samples) > 0:
        e_, v_ = K.sky_dome(T, Ps[vs], Ns[vs], sc_, sr_, L, sky_fn, alb_mean, k=int(sky_samples),
                            res=512, sun_frac=lit_frac, device=dev)
        Es[vs] = e_
        vis_s[vs] = v_
    elif vs.any():
        dd = K.dome_dirs(16)
        Es[vs] = ((sky_fn(dd) * dd[:, 1:2]).sum(0) / dd[:, 1].sum()).astype(np.float32)[None] \
            * (0.5 + 0.5 * Ns[vs][:, 1:2])
    del T
    Es = np.repeat(np.repeat(Es, k, 0), k, 1)[:H, :W]
    occ = np.repeat(np.repeat(occ, k, 0), k, 1)[:H, :W]
    vis_s = np.repeat(np.repeat(vis_s, k, 0), k, 1)[:H, :W]

    # light from below: the ground, lit by the sun (the share of it not in shadow) and the sky
    dd = K.dome_dirs(16)
    sky_flat = (sky_fn(dd) * dd[:, 1:2]).sum(0) * (2.0 / 16)
    gcol = np.asarray(S.srgb_to_linear(np.asarray(ground_color, np.float64))) if ground else alb_mean
    bounce = gcol * (sun * max(float(L[1]), 0.0) * lit_frac + sky_flat)
    cam_d = float(np.linalg.norm(eye - center))
    env = _env(L)
    lin_img = np.zeros((H, W, 3), np.float32)
    # shading per chunk of pixels: the PBR and haze terms make a dozen float64 (n, 3) temporaries, which over a whole
    # supersampled frame were the render's memory peak (several gigabytes)
    step = 1 << 19
    for s0 in range(0, len(vi[0]), step):
        so = (vi[0][s0:s0 + step], vi[1][s0:s0 + step])
        n_ = N[so].astype(np.float64)
        down = np.clip(0.5 - 0.5 * n_[:, 1:2], 0.0, 1.0)
        amb = Es[so].astype(np.float64) + bounce[None] * down * (0.35 + 0.65 * vis_s[so][:, None])
        lit = np.clip(n_ @ L, 0.0, 1.0) * sh[so]
        occ_s = occ[so] * pbr["ao"][so]
        Dv = D[so].astype(np.float64)
        if use_pbr:
            lin = S._shade_pbr(alb[so], n_, -Dv, L, sun, lit, amb, occ_s,
                               pbr["roughness"][so], pbr["metallic"][so], env=env,
                               spec_occ=occ_s * (0.15 + 0.85 * vis_s[so]))
        else:
            Hh = L[None] - Dv
            Hh /= np.linalg.norm(Hh, axis=1, keepdims=True)
            spec = np.clip((n_ * Hh).sum(1), 0, 1) ** 40 * 0.08
            lin = alb[so] * (sun * lit[:, None] + amb * occ_s[:, None]) + (spec * lit)[:, None] * sun
        # aerial perspective in metres: Haze 1 = light falls to 1/e over HAZE_METRES; the haze glows toward the sun
        # (forward scattering). It used to scale with the bounding box, which a sea quad to the horizon made 60 km wide:
        # the haze then started some 600 km out, and near and far ridges looked the same
        ds = dist[so].astype(np.float64)
        f = 1.0 - np.exp(-float(haze) * ds / HAZE_METRES)
        fogc = _haze_colour(Dv, L, sun)
        lin_img[so] = lin * (1 - f[:, None]) + fogc * f[:, None]
    sk_all = np.nonzero(~valid)
    for s0 in range(0, len(sk_all[0]), step):
        sk = (sk_all[0][s0:s0 + step], sk_all[1][s0:s0 + step])
        Dk = D[sk].astype(np.float64)
        lin_img[sk] = K.clouds(Dk, L, sky_radiance(Dk, L), clouds, cloud_seed)
    return _develop(lin_img, exposure, k)


def _haze_colour(Dv, L, sun):
    """In-scattered light of the haze along view rays Dv (n, 3): the horizon sky, plus a forward-scattering glow
    around the sun (a Henyey-Greenstein-like lobe) and a little sunlight from every direction."""
    base = sky_radiance(_flat(Dv), L, sun=False)
    mu = np.clip(Dv @ L, -1.0, 1.0)[:, None]
    g = 0.76
    hg = (1 - g * g) / (4 * np.pi * np.power(1 + g * g - 2 * g * mu, 1.5))      # 1/(4 pi) .. ~7.7 at mu = 1
    return base * 0.9 + np.asarray(sun)[None] * (0.015 + 0.03 * hg)


def _develop(lin, exposure, k):
    """Linear HDR frame -> display: bloom, vignette, exposure, AgX tone curve, supersample down."""
    lin = K.bloom(lin * np.float32(exposure * 0.8))
    lin = K.vignette(lin)
    img = np.empty_like(lin)
    rows = max(1, (1 << 20) // max(lin.shape[1], 1))
    for r0 in range(0, lin.shape[0], rows):
        img[r0:r0 + rows] = K.agx(lin[r0:r0 + rows])
    return S._finish(img, k)


def _flat(D):
    """View rays flattened toward the horizon: the colour of the haze a ray runs into."""
    F = np.asarray(D, np.float64).copy()
    F[:, 1] = np.clip(F[:, 1], -0.02, 0.06)
    return F / np.linalg.norm(F, axis=1, keepdims=True)
