"""
Light transport helpers for the rendered looks (pcg125): what separates "a lit model" from "a photograph of a place".

The first Outdoor look lit every surface with one sun (hard-edged shadow map) plus a constant sky-coloured ambient
dimmed by screen-space AO. That is why streets looked like a level editor: a constant ambient has no direction, so
the underside of a balcony, a narrow street and an open roof all get the same fill. This module adds the three terms
that matter, all still rasterization in numpy:

  sky_dome       **the sky as an area light with shadows**. The sky hemisphere is sampled in K directions; for each a
                 depth map of the scene is rendered and every visible pixel asks "can I see the sky that way?". The
                 irradiance is the sum of sky radiance x cosine x visibility -- narrow streets are darker than
                 squares, eaves cast soft sky shadows, a wall facing the bright horizon near the sun is warmer than
                 one facing away. Directions that are blocked return **bounce light** instead of black: the average
                 colour of the scene lit by sun and sky (one diffuse bounce, energy conserving), which is what fills
                 shadowed streets with warm light on a sunny day.
  sun_shadow     **soft sun shadows with contact hardening** (percentage-closer soft shadows, Fernando 2005): a
                 blocker search estimates how far the occluder is, the penumbra widens with that distance. A lamp
                 post's shadow is crisp at its foot and soft at its tip, as in a photograph.
  depth_map      the depth-only rasterizer behind both (orthographic, float32, triangles pre-cut once). Sub-pixel
                 triangles are splatted as points so that foliage still casts shadow in a coarse map.

and the sky itself:

  sky            analytic sky: Rayleigh-like gradient whose colours follow the sun's elevation (blue noon, warm low
                 sun, red-orange horizon toward a setting sun), a Mie glow and the sun disc
  sun_light      colour and strength of the sunlight after the atmosphere (air mass by Kasten & Young 1989)
  clouds         procedural cumulus layer on a plane overhead (domain-warped value-noise fbm), lit toward the sun
  post           bloom (bright light bleeding, in linear light), a gentle vignette

Everything is deterministic (fixed direction sets and hashes): the same scene renders the same picture.
"""
from __future__ import annotations

import numpy as np

from .core import POINT


# ══════════════════════════════════════════════════════════════════ triangles, depth maps
def soup(geo):
    """
    Cut the geometry into triangles once. Returns (tri_soup tuple for rasterize(soup=...), (P float32 (n, 3),
    tri int (T, 3)) for depth_map()).
    """
    from .spatial import tri_soup
    ts = tri_soup(geo, "")
    P = np.ascontiguousarray(np.asarray(geo.get(POINT, "P"), np.float32)[:, :3])
    return ts, (P, ts[0])


def basis(d):
    """Right / up vectors of an orthographic camera looking along -d (d = unit direction **toward** the light)."""
    d = np.asarray(d, np.float64)
    a = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.95 else np.array([1.0, 0.0, 0.0])
    r = np.cross(a, d)
    r /= np.linalg.norm(r)
    u = np.cross(d, r)
    return r, u


def depth_map(T, d, center, radius, res):
    """
    Orthographic depth map seen from direction d (looking along -d), framing the sphere (center, radius).

    Returns (depth (res, res) float32, inf where empty; meta dict for lookup()). Depth = distance along -d from the
    plane through `center` shifted `radius` toward the light (so larger = further from the light).
    """
    r, u = basis(d)
    d = np.asarray(d, np.float64)
    size = 2.0 * radius
    sc = res / size
    meta = {"r": r, "u": u, "d": d, "c": np.asarray(center, np.float64), "radius": float(radius), "res": int(res)}
    depth = np.full(res * res, np.inf, np.float32)
    Pp, tri = T
    if not len(tri):
        return depth.reshape(res, res), meta
    # project the points once, then gather per corner (columns, not a (T, 3) reduce: that is several times slower)
    Q = Pp.astype(np.float64) - meta["c"]
    px_ = ((Q @ r) * sc + res * 0.5).astype(np.float32)
    py_ = ((Q @ u) * sc + res * 0.5).astype(np.float32)
    pz_ = (radius - Q @ d).astype(np.float32)
    del Q
    i0, i1, i2 = tri[:, 0], tri[:, 1], tri[:, 2]
    sx = (px_[i0], px_[i1], px_[i2])
    sy = (py_[i0], py_[i1], py_[i2])
    z = (pz_[i0], pz_[i1], pz_[i2])
    x0 = np.minimum(np.minimum(sx[0], sx[1]), sx[2])
    x1 = np.maximum(np.maximum(sx[0], sx[1]), sx[2])
    y0 = np.minimum(np.minimum(sy[0], sy[1]), sy[2])
    y1 = np.maximum(np.maximum(sy[0], sy[1]), sy[2])
    on = (x1 >= 0) & (x0 < res) & (y1 >= 0) & (y0 < res)
    small = on & ((x1 - x0) < 1.5) & ((y1 - y0) < 1.5)
    # sub-pixel triangles: one splat at the centroid
    s = np.nonzero(small)[0]
    if len(s):
        cx = np.clip(((sx[0][s] + sx[1][s] + sx[2][s]) * (1 / 3)).astype(np.int64), 0, res - 1)
        cy = np.clip(((sy[0][s] + sy[1][s] + sy[2][s]) * (1 / 3)).astype(np.int64), 0, res - 1)
        np.minimum.at(depth, cy * res + cx, np.minimum(np.minimum(z[0][s], z[1][s]), z[2][s]))
    big = np.nonzero(on & ~small)[0]
    if len(big):
        ix0 = np.clip(np.floor(x0[big]), 0, res - 1).astype(np.int32)
        ix1 = np.clip(np.floor(x1[big]), 0, res - 1).astype(np.int32)
        iy0 = np.clip(np.floor(y0[big]), 0, res - 1).astype(np.int32)
        iy1 = np.clip(np.floor(y1[big]), 0, res - 1).astype(np.int32)
        del x0, x1, y0, y1, on, small
        bw = ix1 - ix0 + 1
        area = (bw * (iy1 - iy0 + 1)).astype(np.int64)
        del ix1, iy1
        cum = np.cumsum(area)
        step = 1 << 20
        start = 0
        while start < len(big):
            base = cum[start - 1] if start else 0
            stop = int(np.searchsorted(cum, base + step, side="right"))
            stop = max(stop, start + 1)
            sl = slice(start, stop)
            a = area[sl]
            n = int(a.sum())
            tid = np.repeat(np.arange(start, stop), a)
            first = np.cumsum(a) - a
            loc = np.arange(n) - np.repeat(first, a)
            w_ = bw[tid]
            px = (ix0[tid] + loc % w_).astype(np.int64)
            py = (iy0[tid] + loc // w_).astype(np.int64)
            t = big[tid]
            ax, ay = sx[0][t], sy[0][t]
            bx, by = sx[1][t], sy[1][t]
            cx, cy = sx[2][t], sy[2][t]
            qx = px.astype(np.float32) + 0.5
            qy = py.astype(np.float32) + 0.5
            den = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            ok = np.abs(den) > 1e-12
            den = np.where(ok, den, 1.0)
            w1 = ((qx - ax) * (cy - ay) - (qy - ay) * (cx - ax)) / den
            w2 = ((bx - ax) * (qy - ay) - (by - ay) * (qx - ax)) / den
            w0 = 1.0 - w1 - w2
            # slightly conservative: a pixel whose centre is within half a pixel of an edge still gets the triangle
            # (no pinholes between neighbours, thin slivers still cast shadow). Half a pixel in barycentric units
            # is 0.5 / altitude = 0.5 x edge length / |den|, per edge
            ad = np.abs(den)
            e0 = -np.minimum(0.5 * np.hypot(cx - bx, cy - by) / ad, 1.0)
            e1 = -np.minimum(0.5 * np.hypot(ax - cx, ay - cy) / ad, 1.0)
            e2 = -np.minimum(0.5 * np.hypot(bx - ax, by - ay) / ad, 1.0)
            ok &= (w0 >= e0) & (w1 >= e1) & (w2 >= e2)
            w0, w1, w2 = np.clip(w0, 0, 1), np.clip(w1, 0, 1), np.clip(w2, 0, 1)
            zz = (w0 * z[0][t] + w1 * z[1][t] + w2 * z[2][t]) / np.maximum(w0 + w1 + w2, 1e-6)
            np.minimum.at(depth, (py * res + px)[ok], zz[ok])
            start = stop
    return depth.reshape(res, res), meta


def project(meta, P):
    """World points (n, 3) -> (x, y) in depth-map pixels (float) and depth z."""
    Q = np.asarray(P, np.float64) - meta["c"]
    sc = meta["res"] / (2.0 * meta["radius"])
    return (Q @ meta["r"]) * sc + meta["res"] * 0.5, (Q @ meta["u"]) * sc + meta["res"] * 0.5, \
        meta["radius"] - Q @ meta["d"]


def lookup(depth, meta, P, N, bias_texels=1.5):
    """Visibility 0..1 of world points P (normals N) from the map's direction: 2x2 bilinear percentage-closer."""
    res = meta["res"]
    texel = 2.0 * meta["radius"] / res
    Pn = np.asarray(P, np.float64) + np.asarray(N, np.float64) * (texel * bias_texels)
    x, y, z = project(meta, Pn)
    x -= 0.5
    y -= 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    zb = (z - texel * 0.5).astype(np.float32)
    out = np.zeros(len(Pn), np.float32)
    for oy, wy in ((0, 1 - fy), (1, fy)):
        for ox, wx in ((0, 1 - fx), (1, fx)):
            xi, yi = x0 + ox, y0 + oy
            ins = (xi >= 0) & (xi < res) & (yi >= 0) & (yi < res)
            dv = np.full(len(Pn), np.inf, np.float32)
            dv[ins] = depth[yi[ins], xi[ins]]
            out += (zb <= dv) * (wx * wy)
    return out


# ══════════════════════════════════════════════════════════════════ sun shadow (PCSS)
_POISSON = np.array([
    [-0.613, 0.617], [0.170, -0.040], [-0.299, 0.791], [0.645, 0.493], [-0.651, 0.717], [0.421, 0.027],
    [-0.817, -0.271], [-0.705, -0.668], [0.977, -0.108], [0.063, 0.142], [0.203, 0.214], [-0.667, 0.581],
    [0.412, -0.975], [0.537, -0.473], [-0.264, -0.418], [0.791, 0.190], [-0.241, 0.997], [-0.814, 0.914],
    [0.199, 0.786], [0.143, -0.141], [-0.101, -0.819], [0.896, 0.412], [-0.326, -0.106], [-0.908, 0.241]])


def sun_shadow(depth, meta, P, N, offset=None, softness=0.012, max_px=24.0):
    """
    Percentage-closer soft shadows. softness = tan of the light's angular radius, enlarged from the real sun's
    0.0047 so the penumbra reads at picture scale. Returns 0..1 (1 = lit).

      1. blocker search: mean depth of the map texels in front of the receiver, in a window that grows with the
         receiver's depth range
      2. penumbra width = (receiver - blocker) x softness, in texels (clamped to max_px)
      3. percentage-closer filtering over a Poisson disc of that radius

    Fully lit and deep-shadow pixels are detected in step 1 and skip step 3.
    """
    res = meta["res"]
    texel = 2.0 * meta["radius"] / res
    n = np.asarray(N, np.float64)
    ndl = n @ meta["d"]
    push = texel * 1.5 if offset is None else np.maximum(texel * 1.5, np.asarray(offset, np.float64))
    Pn = np.asarray(P, np.float64) + n * (push * np.where(ndl < 0, -1.0, 1.0))[:, None]
    x, y, z = project(meta, Pn)
    z = z.astype(np.float32)
    bias = np.float32(texel)
    # deterministic per-pixel rotation of the disc (interleaved gradient noise on the map position)
    ang = 6.2831853 * np.modf(52.9829189 * np.modf(0.06711056 * x + 0.00583715 * y)[0])[0]
    ca, sa = np.cos(ang).astype(np.float32), np.sin(ang).astype(np.float32)

    def tap(k, rad):
        ox = _POISSON[k, 0] * ca - _POISSON[k, 1] * sa
        oy = _POISSON[k, 0] * sa + _POISSON[k, 1] * ca
        xi = np.floor(x + ox * rad).astype(np.int64)
        yi = np.floor(y + oy * rad).astype(np.int64)
        ins = (xi >= 0) & (xi < res) & (yi >= 0) & (yi < res)
        dv = np.full(len(z), np.inf, np.float32)
        dv[ins] = depth[yi[ins], xi[ins]]
        return dv

    search = np.float32(min(max_px, max(3.0, softness * meta["radius"] * 0.5 / texel)))
    zsum = np.zeros(len(z), np.float32)
    cnt = np.zeros(len(z), np.float32)
    nb = 12
    for k in range(nb):
        dv = tap(k, search)
        blk = dv < z - bias
        zsum += np.where(blk, dv, 0.0)
        cnt += blk
    out = np.ones(len(z), np.float32)
    part = cnt > 0
    if not part.any():
        return out
    idx = np.nonzero(part)[0]
    zb = zsum[idx] / cnt[idx]
    rad = np.clip((z[idx] - zb) * softness / texel, 1.0, max_px).astype(np.float32)
    # restrict the taps to the pixels that have a blocker
    x, y, z, ca, sa = x[idx], y[idx], z[idx], ca[idx], sa[idx]
    lit = np.zeros(len(idx), np.float32)
    nt = len(_POISSON)
    for k in range(nt):
        lit += tap(k, rad) >= z - bias
    out[idx] = lit / nt
    return out


# ══════════════════════════════════════════════════════════════════ sky
def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def sun_light(L):
    """Linear RGB irradiance of the sun on a surface facing it, after the atmosphere (relative air mass)."""
    s = float(L[1])
    zen = np.degrees(np.arccos(np.clip(s, -1, 1)))
    m = 1.0 / (max(s, 0.0) + 0.50572 * max(96.07995 - zen, 0.1) ** -1.6364)         # Kasten & Young 1989
    T = np.exp(-np.array([0.035, 0.075, 0.170]) * m)
    return 3.4 * T * float(_smooth(-0.06, 0.05, s))


def sky(D, L, sun=True):
    """
    D (n, 3) unit rays -> (n, 3) linear sky radiance (no clouds). Colours follow the sun's elevation: a high sun
    gives a deep blue zenith over a pale horizon; a low sun dims and warms the dome and turns the horizon toward the
    sun orange. Below the horizon: the horizon colour, darkened (distant ground haze).
    """
    D = np.asarray(D, np.float64)
    L = np.asarray(L, np.float64)
    s = float(L[1])
    low = 1.0 - float(_smooth(0.0, 0.42, s))                    # 1 at the horizon, 0 for a high sun
    day = float(_smooth(-0.1, 0.25, s))
    zen = np.array([0.06, 0.24, 0.60]) * (1 - low) + np.array([0.10, 0.20, 0.42]) * low
    hor = np.array([0.40, 0.68, 0.95]) * (1 - low) + np.array([0.74, 0.66, 0.60]) * low
    y = D[:, 1:2]
    t = np.clip(y, 0.0, 1.0) ** 0.42
    col = hor[None] + (zen - hor)[None] * t
    cos = np.clip(D @ L, -1.0, 1.0)[:, None]
    # toward a low sun the horizon band glows orange
    Lh = L.copy()
    Lh[1] = 0.0
    lh = np.linalg.norm(Lh)
    if lh > 1e-6 and low > 0:
        Dh = D.copy()
        Dh[:, 1] = 0.0
        Dh /= np.maximum(np.linalg.norm(Dh, axis=1, keepdims=True), 1e-9)
        az = np.clip(Dh @ (Lh / lh), -1, 1)[:, None]
        band = np.exp(-np.clip(y, 0, 1) * 5.5) * (0.5 + 0.5 * az) ** 2
        col = col + (low * 0.9) * band * (np.array([1.0, 0.50, 0.20]) - col * 0.6)
    col = np.where(y < 0, hor[None] * (0.6 + 0.4 * np.exp(np.minimum(y, 0) * 8.0)), col)
    col = col * (0.25 + 0.75 * day)
    sc = sun_light(L) / 3.4
    glow = np.exp((cos - 1.0) / 0.06) * 0.6 + np.exp((cos - 1.0) / 0.5) * (0.12 + 0.2 * low)
    col = col + glow * sc[None] * np.array([1.0, 0.86, 0.66])[None]
    if sun:
        col = col + (np.exp((cos - 1.0) / 0.00025) * 45.0) * sc[None]
    return col * 1.4


def _hash2(ix, iy, seed):
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + int(seed) * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF).astype(np.float32) / np.float32(0xFFFFFF)


def _vnoise(x, y, seed):
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    x0 = x0.astype(np.int64)
    y0 = y0.astype(np.int64)
    a = _hash2(x0, y0, seed)
    b = _hash2(x0 + 1, y0, seed)
    c = _hash2(x0, y0 + 1, seed)
    d = _hash2(x0 + 1, y0 + 1, seed)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def fbm2(x, y, seed=0, octaves=5):
    """2-D value-noise fbm in 0..1 (lacunarity 2.03, gain 0.5), each octave rotated to hide the lattice."""
    out = np.zeros(np.shape(x), np.float32)
    amp, tot = 0.5, 0.0
    for o in range(octaves):
        out += amp * _vnoise(x, y, seed + o * 17)
        tot += amp
        x, y = (0.8 * x - 0.6 * y) * 2.03 + 11.3, (0.6 * x + 0.8 * y) * 2.03 - 4.7
        amp *= 0.5
    return out / tot


def _cloud_density(u, v, seed, octaves=6):
    wx = fbm2(u * 0.5 + 9.0, v * 0.5, seed + 101, 3) - 0.5
    wy = fbm2(u * 0.5, v * 0.5 + 5.0, seed + 202, 3) - 0.5
    return fbm2(u + 1.6 * wx, v + 1.6 * wy, seed, octaves), wx, wy


def clouds(D, L, base, coverage=0.4, seed=0):
    """
    Composite a cumulus layer over the sky colours `base` (n, 3) for rays D. coverage 0 = clear, 1 = overcast.
    The layer is a plane one "cloud unit" overhead; density is a domain-warped fbm thresholded by coverage, shaded
    lighter toward the sun and darker in the thick parts, fading into the haze at the horizon. Returns (n, 3).
    """
    cov = float(np.clip(coverage, 0.0, 1.0))
    if cov <= 0:
        return base
    D = np.asarray(D, np.float64)
    y = D[:, 1]
    up = y > 0.015
    if not up.any():
        return base
    d = D[up]
    k = 1.0 / (d[:, 1] + 0.09)
    u = d[:, 0] * k * 0.9 + 3.1
    v = d[:, 2] * k * 0.9 - 1.7
    n, wx, wy = _cloud_density(u, v, seed)
    thr = 0.72 - 0.5 * cov
    a = _smooth(thr, thr + 0.16, n)
    # light: compare with the density a little toward the sun -- thinner that way = lit edge
    Lh = np.asarray(L, np.float64)
    n2 = fbm2(u + 1.6 * wx + Lh[0] * 0.35, v + 1.6 * wy + Lh[2] * 0.35, seed, 4)
    lit = _smooth(-0.10, 0.12, n - n2)
    thick = _smooth(thr + 0.05, thr + 0.35, n)
    sc = sun_light(L)
    amb = base[up].mean(0)
    bright = sc[None] * (0.22 + 0.16 * lit[:, None]) + amb[None] * 0.55
    dark = sc[None] * 0.07 + amb[None] * 0.42
    ccol = bright * (1 - 0.75 * thick[:, None]) + dark * (0.75 * thick[:, None])
    fade = _smooth(0.015, 0.22, d[:, 1])
    a = (a * fade * 0.94)[:, None]
    out = np.array(base, np.float64, copy=True)
    out[up] = base[up] * (1 - a) + ccol * a
    return out


def cloud_shadow(P, eye, L, coverage, seed, height):
    """
    Sunlight factor 0.35..1 under the cloud layer of clouds(): the same density field, looked up where the ray from
    P toward the sun crosses the layer (`height` world units above the eye = one cloud unit). Soft-edged, because
    the sun is not a point and clouds are not solid.
    """
    cov = float(np.clip(coverage, 0.0, 1.0))
    if cov <= 0 or L[1] <= 0.02:
        return np.ones(len(P), np.float32)
    Q = (np.asarray(P, np.float64) - np.asarray(eye, np.float64)) / float(height)
    t = (1.0 - Q[:, 1]) / float(L[1])
    u = (Q[:, 0] + L[0] * t) * 0.9 + 3.1
    v = (Q[:, 2] + L[2] * t) * 0.9 - 1.7
    n, _, _ = _cloud_density(u, v, seed, 4)
    thr = 0.72 - 0.5 * cov
    a = _smooth(thr - 0.04, thr + 0.22, n)
    return (1.0 - 0.65 * a).astype(np.float32)


# ══════════════════════════════════════════════════════════════════ sky dome light
def dome_dirs(k=32):
    """k directions on the upper hemisphere (spherical Fibonacci, equal solid angle each), y up."""
    i = np.arange(k) + 0.5
    y = 0.04 + 0.96 * i / k                      # skip the last degrees above the horizon: all haze, long slivers
    phi = i * 2.399963229728653
    r = np.sqrt(np.maximum(1 - y * y, 0))
    return np.stack([r * np.cos(phi), y, r * np.sin(phi)], 1)


def sky_dome(T, P, N, center, radius, L, sky_fn, albedo_mean, k=32, res=768, sun_frac=0.5, ground=None):
    """
    Diffuse irradiance from the sky with shadows, plus one bounce.

      T            the triangles (second value of soup())
      P, N         (n, 3) world positions / unit normals of the pixels to light
      center, radius   sphere the depth maps frame (the visible part of the scene)
      sky_fn       rays -> radiance
      albedo_mean  (3,) average linear albedo of the visible scene: the colour of the bounce
      ground       optional ground plane height y: an infinite plane, blocks directions from below it (none here:
                   dome directions are all upward) -- kept for symmetry

    Returns (E (n, 3) irradiance / pi, i.e. what multiplies albedo; vis (n,) mean cosine-weighted sky visibility).
    The unoccluded value on an upward surface equals the cosine-weighted mean sky radiance, so the picture's overall
    brightness does not depend on k.
    """
    dirs = dome_dirs(k)
    rad = sky_fn(dirs)                                         # (k, 3)
    n = np.asarray(N, np.float32)
    E = np.zeros((len(P), 3), np.float32)
    vis = np.zeros(len(P), np.float32)
    wsum = np.zeros(len(P), np.float32)
    # radiance of an occluder: the scene lit by the sun (a share of it in shade) and by the open sky
    # (everything here is "irradiance / pi": the number that multiplies an albedo)
    sun_e = sun_light(L) * max(float(L[1]), 0.0)
    sky_e = (rad * dirs[:, 1:2]).sum(0) * (2.0 / k)
    bounce = np.asarray(albedo_mean, np.float64) * (sun_e * sun_frac + sky_e * 0.5)
    for i in range(k):
        dmap, meta = depth_map(T, dirs[i], center, radius, res)
        c = np.maximum(n @ dirs[i].astype(np.float32), 0.0)
        hit = c > 0
        if not hit.any():
            continue
        v = np.zeros(len(P), np.float32)
        v[hit] = lookup(dmap, meta, P[hit], N[hit])
        E += (c * v)[:, None] * rad[i].astype(np.float32)[None] + (c * (1 - v))[:, None] * bounce.astype(np.float32)[None]
        vis += c * v
        wsum += c
    # the hemisphere integral of the cosine is pi; each direction stands for 2 pi / k of solid angle
    E *= 2.0 / k
    vis = np.where(wsum > 0, vis / np.maximum(wsum, 1e-9), 1.0)
    return E, vis


# ══════════════════════════════════════════════════════════════════ post
def bloom(lin, strength=0.06, threshold=1.0):
    """Light above `threshold` bleeds into its surroundings (three Gaussian scales). lin (H, W, 3) linear, in place."""
    from scipy import ndimage as ndi
    if strength <= 0:
        return lin
    H, W = lin.shape[:2]
    f = max(1, int(round(max(H, W) / 400)))
    h2, w2 = (H // f) * f, (W // f) * f
    small = lin[:h2, :w2].reshape(h2 // f, f, w2 // f, f, 3).mean((1, 3))
    br = np.maximum(small - threshold, 0.0)
    br = np.minimum(br, 30.0)
    if not (br > 0).any():
        return lin
    acc = np.zeros_like(br)
    for sg, wgt in ((1.5, 0.5), (5.0, 0.3), (16.0, 0.2)):
        acc += wgt * ndi.gaussian_filter(br, (sg, sg, 0), mode="nearest")
    up = np.repeat(np.repeat(acc, f, 0), f, 1)
    if f > 1:
        up = ndi.uniform_filter(up, (f, f, 1), mode="nearest")
    lin[:h2, :w2] += (strength * up).astype(lin.dtype)
    return lin


def vignette(lin, amount=0.16):
    """Darken toward the corners (cos^4-like falloff, `amount` at the corner). In place."""
    H, W = lin.shape[:2]
    yy = (np.arange(H, dtype=np.float32) + 0.5) / H * 2 - 1
    xx = (np.arange(W, dtype=np.float32) + 0.5) / W * 2 - 1
    r2 = (yy[:, None] ** 2 + xx[None, :] ** 2) * 0.5
    lin *= (1.0 - amount * r2 * r2 - amount * 0.5 * r2)[..., None]
    return lin


_AGX_IN = np.array([[0.842479062253094, 0.0423282422610123, 0.0423756549057051],
                    [0.0784335999999992, 0.878468636469772, 0.0784336],
                    [0.0792237451477643, 0.0791661274605434, 0.879142973793104]])
_AGX_OUT = np.array([[1.19687900512017, -0.0528968517574562, -0.0529716355144438],
                     [-0.0980208811401368, 1.15190312990417, -0.0980434501171241],
                     [-0.0990297440797205, -0.0989611768448433, 1.15107367264116]])


def agx(lin, punch=1.0):
    """
    Linear scene light (n.., 3) -> display values 0..1 (already encoded, no sRGB curve after it).

    AgX (Troy Sobotka; the polynomial fit of the base curve by Benjamin Wrensch): the picture is formed in a
    log2 range of 16.5 stops through a sigmoid, in a slightly desaturated working space, so bright saturated colours
    roll off toward white the way film does instead of clipping to pure yellow / cyan, and deep shadows keep
    separation. The ACES fit used by the studio look is much steeper: fine for an object on a backdrop, harsh for a
    landscape with a sunlit sky and shadowed streets in one frame. punch > 0 adds the usual "punchy" look on top
    (contrast and saturation), scaled by its value.
    """
    x = np.maximum(np.asarray(lin, np.float64), 0.0) @ _AGX_IN.T
    lo, hi = -12.47393, 4.026069
    x = (np.clip(np.log2(np.maximum(x, 1e-10)), lo, hi) - lo) / (hi - lo)
    x2 = x * x
    x4 = x2 * x2
    x = 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232
    if punch > 0:
        lum = (x * np.array([0.2126, 0.7152, 0.0722])).sum(-1, keepdims=True)
        x = np.power(np.maximum(x, 0.0), 1.0 + 0.3 * punch)
        lum = np.power(np.maximum(lum, 0.0), 1.0 + 0.3 * punch)
        x = lum + (1.0 + 0.35 * punch) * (x - lum)
    return np.clip(x @ _AGX_OUT.T, 0.0, 1.0)


def grade(x, contrast=1.0, saturation=1.05):
    """Display-referred finishing on tone-mapped 0..1 values: a touch of contrast around mid grey and saturation."""
    x = np.clip(x, 0.0, 1.0)
    x = np.clip(0.5 + (x - 0.5) * contrast, 0.0, 1.0)
    lum = (x * np.array([0.2126, 0.7152, 0.0722], x.dtype)).sum(-1, keepdims=True)
    return np.clip(lum + (x - lum) * saturation, 0.0, 1.0)
