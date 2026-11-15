"""
Grunge maps (Copernicus, Houdini 22): fourteen layered-noise generators for dirt and wear -- masks and building
blocks for rust, stains, bark, streaks. One mono layer each, 0..1 before the Range section.

Every map is built in "pattern space": the image coordinates (x = u, y = v x H / W, as COP Worley Noise) minus
Offset, scaled so that one unit is one element, with a whole number of elements per Tile Size (Element Size is
rounded to fit, as Houdini does to keep the pattern tileable). All noises are periodic over the tile (periodic
Perlin, periodic Worley: geo.wrangle), domain warps are periodic too, so with Tile Size = the image the map tiles.

Sections, in Houdini's order:
    Range            x = contrast(x, Mask Contrast); out = Amplitude * x + Center
    Pattern          Element Size, Offset, Tile Size
    <the map's own>  Primary / Secondary / Tertiary ... controls, Seed
    Post Processing  the shared noise post-processing (noisepost)

The parameter names of Drips, Bark Strips, Leaking Streaks and Rusty Surface are Houdini's; the documentation of
the other maps does not list theirs, so those follow the same Primary / Secondary / Tertiary scheme. The formulas
are our own throughout (SideFX does not publish them): the maps look alike in kind, not pixel for pixel.

"Down" is -v (drips and streaks run toward the bottom of the image, row 0 = the smallest v).
"""
from __future__ import annotations

import numpy as np

from ..wrangle import perlin3_periodic, worley3_periodic, _hash01


def _ss(a, b, x):
    d = np.asarray(b - a, np.float64)
    t = np.clip((x - a) / np.where(d == 0, 1e-12, d), 0.0, 1.0)
    return t * t * (3 - 2 * t)


class _Space:
    """Pattern space of one map: coordinates (in elements), the period, the seed."""

    def __init__(self, x, y, nx, ny, seed):
        self.x, self.y, self.nx, self.ny, self.seed = x, y, int(nx), int(ny), int(seed)

    def pn(self, kx=1, ky=None, z=0.0, wx=0.0, wy=0.0):
        """Periodic Perlin 0..1 at kx (ky) cycles per element; wx / wy warp the lookup (in elements)."""
        ky = kx if ky is None else ky
        p = np.stack([(self.x + wx) * kx, (self.y + wy) * ky,
                      np.full(self.x.shape, z + 7.31 * self.seed)], -1)
        return perlin3_periodic(p, (self.nx * kx, self.ny * ky, 0))

    def fbm(self, k=1, z=0.0, octaves=4, rough=0.5, wx=0.0, wy=0.0, ridged=False):
        out, amp, tot = 0.0, 1.0, 0.0
        for o in range(int(octaves)):
            n = self.pn(k * 2 ** o, None, z + 3.7 * o, wx, wy)
            if ridged:
                n = 1.0 - np.abs(2.0 * n - 1.0)
            out = out + amp * n
            tot += amp
            amp *= rough
        return out / tot

    def wor(self, kx=1, ky=None, salt=0, wx=0.0, wy=0.0):
        """Periodic 2D Worley at kx (ky) cells per element: f1, f2, id (0..1), vector to the feature point."""
        ky = kx if ky is None else ky
        p = np.stack([(self.x + wx) * kx, (self.y + wy) * ky], -1)
        return worley3_periodic(p, (self.nx * kx, self.ny * ky, 0), 1.0, self.seed * 16 + salt)


def _rand(i, salt):
    return _hash01(i * 977.0 + salt * 13.7 + 1.0, 0)


# ══════════════════════════════════════════════════════════════════ the fourteen maps
def _aurora(s, p):
    wx = p["primary_distortion"] * 1.5 * (s.pn(1, None, 0.3) - 0.5)
    cur = 1 - np.abs(2 * s.pn(2, 1, 1.1, wx) - 1)                     # curtains: ridges of a low noise
    cur = cur ** (1 + 4 * p["streak_sharpness"])
    rays = s.pn(14, 1, 2.3, wx * 1.2)                                 # fine vertical rays inside them
    rays = _ss(0.25, 0.75, rays)
    fade = _ss(0.25, 0.8, s.pn(1, 2, 3.9, wx * 0.5))                  # they brighten and die along their length
    glow = s.fbm(1, 5.1, 3, 0.5)
    return np.clip(cur * (0.35 + 0.65 * rays) * fade + p["secondary_mask"] * 0.35 * glow * fade, 0, 1)


def _bark_strips(s, p):
    brk = p["primary_edge_breakup"]
    wx = brk * 0.25 * (s.fbm(3, 0.4, 3, 0.6) - 0.5)
    f1, f2, cid, _ = s.wor(5, 1, 1, wx)                               # strips: cells five times as tall as wide,
    strip = _ss(0.0, 0.08 + 0.5 * (1 - p["strips_inflate"]), f2 - f1)  # side by side; Inflate widens them
    h = strip * (0.65 + 0.35 * _rand(cid, 1))
    k2 = max(1, int(round(4 * p["secondary_size"])))
    cuts = 1 - _ss(0.0, 0.25, np.abs(s.pn(1, k2 * 3, 2.2, wx) - 0.5) * 2)      # horizontal cuts and grooves
    h = h * (1 - p["secondary_mask"] * 0.6 * cuts * _ss(0.4, 0.6, s.pn(2, 2, 2.9)))
    k3 = max(1, int(round(3 * p["tertiary_size"])))
    g1, g2, _, _ = s.wor(k3 * 4, k3, 2, wx * 2)                       # swirls: small cells inside the strips
    h = h * (1 - p["tertiary_mask"] * 0.5 * (1 - _ss(0.0, 0.25, g2 - g1)))
    return np.clip(h, 0, 1)


def _birch_bark(s, p):
    wy = p["primary_distortion"] * 0.3 * (s.pn(2, 1, 0.6) - 0.5)
    base = 0.78 + 0.16 * (s.fbm(1, 1.3, 3, 0.5, 0, wy) - 0.5)        # pale bark
    k = max(1, int(round(3 * p["lenticel_size"])))
    f1, f2, cid, v = s.wor(k, k * 4, 3, 0, wy)                        # lenticels: short dark horizontal dashes
    wide = 0.18 + 0.3 * _rand(cid, 2)
    dash = (1 - _ss(wide * 0.6, wide, np.abs(v[:, 0]))) * (1 - _ss(0.05, 0.14, np.abs(v[:, 1])))
    dash = dash * (_rand(cid, 3) < 0.7)
    peel = _ss(0.55, 0.62, s.fbm(1, 4.4, 3, 0.55, 0, wy * 2))         # peeled patches: darker, with a curled lip
    lip = _ss(0.5, 0.56, s.fbm(1, 4.4, 3, 0.55, 0, wy * 2)) - peel
    h = base * (1 - p["lenticel_mask"] * 0.8 * dash)
    h = h * (1 - p["peel_mask"] * 0.45 * peel) + p["peel_mask"] * 0.2 * lip
    return np.clip(h, 0, 1)


def _drop_layer(s, k, stretch, density, trailing, distortion, salt):
    """Drops (heads) with a trail below each: cells `stretch` times taller than wide, one drop in some of them."""
    wx = distortion * 0.35 / k * (s.pn(k, k * 2, 0.9 + salt) - 0.5) * 2
    f1, f2, cid, v = s.wor(k * stretch, k, salt, wx)
    dx, dy = v[:, 0] / stretch, v[:, 1]                               # to the drop, in cell heights
    on = _rand(cid, 4 + salt) < density
    r = 0.07 + 0.07 * _rand(cid, 5 + salt)
    head = 1 - _ss(r * 0.6, r, np.hypot(dx, dy))
    # the trail hangs below the drop (the drop lies above the pixel: dy > 0), thinning toward its end
    L = 0.15 + 0.8 * trailing * (0.4 + 0.6 * _rand(cid, 6 + salt))
    t = np.clip(dy / L, 0, 1)
    trail = (1 - _ss(r * 0.25, r * 0.7 * (1 - 0.6 * t), np.abs(dx))) * (dy > 0) * (1 - t) ** 0.7
    return np.where(on, np.maximum(head, trail * (0.35 + 0.65 * trailing)), 0.0)


def _drips(s, p):
    a = _drop_layer(s, 2, 3, 0.25 + 0.7 * p["density"], p["primary_trailing"], p["distortion"], 1)
    b = _drop_layer(s, 4, 3, 0.6, p["secondary_trailing"], p["distortion"], 2)
    smudge = _ss(0.5, 0.75, s.fbm(1, 2.2, 3, 0.5))
    g1, _, gid, _ = s.wor(12, None, 3)
    speck = (1 - _ss(0.05, 0.12, g1)) * (_rand(gid, 7) < 0.3)
    h = np.maximum(a, p["secondary_mask"] * 0.5 * b)
    h = np.maximum(h, p["tertiary_mask"] * 0.3 * smudge)
    return np.clip(np.maximum(h, p["speckle_mask"] * speck), 0, 1)


def _galvanized_steel(s, p):
    wx = 0.2 * (s.pn(2, None, 0.2) - 0.5)
    f1, f2, cid, v = s.wor(1, None, 1, wx, wx)                        # spangles: one crystal per cell
    a = _rand(cid, 1) * 2 * np.pi
    facet = v[:, 0] * np.cos(a) + v[:, 1] * np.sin(a)                 # each lit along its own axis
    shade = 0.5 + p["spangle_contrast"] * (_rand(cid, 2) - 0.5)
    feather = np.abs(np.sin((v[:, 0] * np.sin(a) - v[:, 1] * np.cos(a)) * 40 + 6 * facet))   # dendrite lines
    h = shade + p["facet_mask"] * 0.35 * facet + p["facet_mask"] * 0.08 * (feather - 0.5)
    h = h - 0.15 * (1 - _ss(0.0, 0.06, f2 - f1))                      # grain boundaries
    return np.clip(h + p["grain_mask"] * 0.12 * (s.pn(24, None, 3.3) - 0.5), 0, 1)


def _layered_noise(s, p):
    lac = max(2, int(round(p["lacunarity"])))
    wx = wy = 0.0
    out, amp, tot = 0.0, 1.0, 0.0
    for i in range(max(1, int(round(p["layers"])))):
        k = lac ** i
        # each layer is warped by the one before (a stormy sky), and stretched sideways (its reflection in water)
        n = s.fbm(k, 11.3 + 1.7 * i, 3, 0.5, wx, wy * (1 - 0.6 * p["reflection"]))
        out = out + amp * n
        tot += amp
        amp *= p["roughness"]
        wx = p["distortion"] * 0.6 * (n - 0.5) / k
        wy = p["distortion"] * 0.6 * (s.pn(k, None, 9.1 + i) - 0.5) / k
    h = out / tot
    return np.clip(0.5 + (h - 0.5) * 2.2, 0, 1)


def _leaking_streaks(s, p):
    rough = p["primary_roughness"]
    wx = p["primary_distortion"] * 0.12 * (s.fbm(2, 0.5, 3, 0.6) - 0.5) * 2
    src = s.pn(10, 1, 1.4, wx)                                        # streaks: a noise 10 times finer across
    edge = 0.5 + rough * 0.35 * (s.pn(30, 2, 2.1, wx) - 0.5)
    st = _ss(edge - 0.05, edge + 0.12, src)
    run = _ss(0.2, 0.75, s.pn(5, 1, 3.3, wx))                         # each runs for a while, then fades
    h = st * run
    wy = p["secondary_distortion"] * 0.25 * (s.fbm(2, 4.4, 3, 0.6) - 0.5) * 2
    fold = 1 - np.abs(2 * s.pn(1, 3, 5.2, 0, wy) - 1)                 # folds behind them: background stains
    h = np.maximum(h, p["secondary_mask"] * 0.45 * _ss(0.55, 0.95, fold))
    hi = _ss(1 - p["tertiary_balance"] * 0.6, 1.0, src) * run         # highlights along the streak cores
    return np.clip(h * (1 - 0.3 * p["tertiary_mask"]) + p["tertiary_mask"] * 0.45 * hi, 0, 1)


def _moisture(s, p):
    n = s.fbm(1, 0.7, 4, 0.55)
    thr = 0.62 - 0.25 * p["spot_mask"]
    soft = 0.02 + 0.2 * p["edge_softness"]
    spot = _ss(thr - soft, thr + soft, n)                             # damp patches
    f1, f2, cid, _ = s.wor(8, None, 1, 0.1 * (n - 0.5), 0)
    pore = (1 - _ss(0.1, 0.3, f1)) * (_rand(cid, 1) < 0.75)           # a sponge of pores inside them
    f3, _, _, _ = s.wor(20, None, 2)
    fine = 1 - _ss(0.1, 0.3, f3)
    h = spot * (1 - p["porosity"] * 0.7 * np.maximum(pore, 0.5 * fine))
    ring = _ss(thr - soft * 2, thr, n) - spot                         # the tide mark round a drying patch
    return np.clip(h + p["secondary_mask"] * 0.5 * np.clip(ring, 0, 1), 0, 1)


def _mold_spots(s, p):
    clus = s.fbm(1, 0.9, 3, 0.5)
    lo = 0.75 - 0.6 * p["density"]
    h = np.zeros_like(s.x)
    for i, k in enumerate((3, 7, 15)):
        f1, _, cid, _ = s.wor(k, None, 1 + i)
        # colonies where the cluster noise is high (Cluster 0 = everywhere)
        gate = _ss(lo, lo + 0.15, clus * p["cluster"] + (1 - p["cluster"]) * 0.75)
        on = (_rand(cid, 1 + i) < 0.35 + 0.5 * p["density"]) * gate
        r = 0.12 + 0.25 * _rand(cid, 4 + i)
        core = 1 - _ss(r * 0.5, r, f1)
        halo = (1 - _ss(r, r * 2.2, f1)) * p["halo"] * 0.45
        h = np.maximum(h, on * np.maximum(core, halo) * (1 - 0.25 * i))
    fuzz = s.pn(40, None, 5.5)
    return np.clip(h * (0.8 + 0.4 * fuzz) + p["secondary_mask"] * 0.2 * _ss(0.55, 0.8, clus), 0, 1)


def _pine_bark(s, p):
    wx = p["primary_distortion"] * 0.3 * (s.fbm(2, 0.3, 3, 0.55) - 0.5)
    f1, f2, cid, v = s.wor(2, 1, 1, wx, wx * 0.5)                     # plates, taller than wide
    e = f2 - f1
    w = 0.05 + 0.35 * p["furrow_width"]
    plate = _ss(0.0, w, e)                                            # deep dark furrows between them
    lay = s.fbm(3, 2.2, 3, 0.5, wx) + 0.6 * _rand(cid, 2)
    q = np.floor(lay * 5) / 5                                         # flaky layers: steps across each plate
    flake = 0.55 + 0.45 * (q - q.min()) / max(float(np.ptp(q)), 1e-9)
    h = plate * (flake * p["plate_layers"] + (1 - p["plate_layers"]) * 0.8)
    crack = 1 - _ss(0.0, 0.12, np.abs(s.pn(6, 2, 3.8, wx) - 0.5) * 2)
    return np.clip(h * (1 - p["secondary_mask"] * 0.4 * crack * plate), 0, 1)


def _rust(s, p):
    brk = p["edge_breakup"]
    n = s.fbm(1, 0.2, 5, 0.45 + 0.3 * brk)
    thr = 0.68 - 0.36 * p["coverage"]
    patch = _ss(thr - 0.02, thr + 0.05 + 0.1 * (1 - brk), n)          # blooms of rust with ragged edges
    inner = s.fbm(4, 1.9, 4, 0.6, ridged=True)                        # crusty inside
    f1, _, cid, _ = s.wor(14, None, 1)
    pit = (1 - _ss(0.08, 0.22, f1)) * (_rand(cid, 1) < 0.5)           # pits, also ahead of the patches
    h = patch * (0.6 + 0.4 * inner)
    h = np.maximum(h, p["pitting_mask"] * pit * _ss(thr - 0.2, thr, n))
    return np.clip(h + p["secondary_mask"] * 0.25 * _ss(0.4, 0.9, s.fbm(2, 6.6, 3, 0.5)) * (1 - patch), 0, 1)


def _rusty_surface(s, p):
    # the base layer: sheets of rust, their edges waved along y (Primary) and along x (Secondary)
    wx = p["primary_roughness"] * 0.35 * (s.fbm(2, 0.4, 4, 0.6) - 0.5) * 2
    wy = p["secondary_roughness"] * 0.35 * (s.fbm(2, 1.6, 4, 0.6) - 0.5) * 2
    n = s.fbm(1, 2.8, 4, 0.5, wx, wy)
    h = _ss(0.3, 0.7, n) * (0.7 + 0.3 * s.fbm(6, 3.9, 3, 0.6, wx, wy, ridged=True))
    k = max(1, int(round(3 / max(p["cracks_size"], 0.05))))
    f1, f2, _, _ = s.wor(k * 3, k, 1, wx * 0.5)                       # vertical crack lines: tall narrow cells
    crack = 1 - _ss(0.0, 0.05, f2 - f1)
    return np.clip(h * (1 - p["cracks_mask"] * 0.75 * crack), 0, 1)


def _sheets(s, p):
    wx = p["primary_distortion"] * 0.2 * (s.pn(2, None, 0.8) - 0.5)
    h = np.full(s.x.shape, 0.5)
    for i in range(max(1, int(round(p["layers"])))):
        k = 1 + (i % 2)
        f1, f2, cid, v = s.wor(k, None, 1 + i, wx)
        a = _rand(cid, 1 + i) * np.pi
        lx = v[:, 0] * np.cos(a) + v[:, 1] * np.sin(a)
        ly = -v[:, 0] * np.sin(a) + v[:, 1] * np.cos(a)
        half = 0.28 + 0.3 * p["size_variation"] * (_rand(cid, 9 + i) - 0.3)
        d = np.maximum(np.abs(lx) / (half * 1.3), np.abs(ly) / half)   # a turned rectangle per cell: one sheet
        on = (d < 1) & (_rand(cid, 17 + i) < 0.8)
        tone = 0.25 + 0.6 * _rand(cid, 25 + i)
        edge = _ss(0.9, 1.0, d) * p["edge_mask"] * 0.4               # darker along its edge
        h = np.where(on, tone - edge, h)
    return np.clip(h + 0.05 * (s.pn(30, None, 7.7) - 0.5), 0, 1)


def _wipe_trails(s, p):
    h = np.zeros_like(s.x)
    for i, (k, m) in enumerate(((1, p["primary_mask"]), (2, p["secondary_mask"] * 0.6))):
        f1, f2, cid, v = s.wor(k, None, 1 + i)
        # arcs round a centre beside each cell's point: the hand's wiping circles
        cx = v[:, 0] + 0.6 * (_rand(cid, 1 + i) - 0.5)
        cy = v[:, 1] + 0.6 * (_rand(cid, 3 + i) - 0.5)
        r = np.hypot(cx, cy)
        ang = np.arctan2(cy, cx)
        fine = 6 + 24 * p["streak_fineness"]
        q = r * fine                                                # one tone per ring of the cloth's fibres,
        q0 = np.floor(q)                                            # blended from ring to ring (no hard rings)
        t = q - q0
        t = t * t * (3 - 2 * t)
        st = _hash01(q0 + cid * 9973.0, 0) * (1 - t) + _hash01(q0 + 1 + cid * 9973.0, 0) * t
        span = np.pi * (0.25 + 0.75 * p["arc_spread"])
        a0 = _rand(cid, 5 + i) * 2 * np.pi
        da = np.abs((ang - a0 + np.pi) % (2 * np.pi) - np.pi)
        arc = (1 - _ss(span * 0.6, span, da)) * _ss(0.05, 0.2, r) * (1 - _ss(0.5, 0.9, r))
        arc = arc * _ss(0.0, 0.2, f2 - f1)                          # and die out before the next wipe's cell
        h = np.maximum(h, m * arc * (0.25 + 0.75 * st))
    return np.clip(h, 0, 1)


def _P(name, default, lo=0.0, hi=1.0, step=0.01, integer=False):
    return (name, default, lo, hi, step, integer)


# kind -> (Houdini node name, the map's own parameters, the function, whether the names are Houdini's)
KINDS = {
    "aurora": ("Grunge Aurora", [_P("primary_distortion", 0.5), _P("streak_sharpness", 0.6),
                                 _P("secondary_mask", 0.4)], _aurora, False),
    "bark_strips": ("Grunge Bark Strips", [
        _P("strips_inflate", 0.5), _P("primary_edge_breakup", 0.5), _P("secondary_mask", 0.5),
        _P("secondary_size", 1.0, 0.25, 4.0, 0.05), _P("tertiary_mask", 0.3),
        _P("tertiary_size", 1.0, 0.25, 4.0, 0.05)], _bark_strips, True),
    "birch_bark": ("Grunge Birch Bark", [_P("lenticel_mask", 0.8), _P("lenticel_size", 1.0, 0.25, 4.0, 0.05),
                                         _P("peel_mask", 0.5), _P("primary_distortion", 0.3)], _birch_bark, False),
    "drips": ("Grunge Drips", [_P("density", 0.5), _P("distortion", 0.3), _P("primary_trailing", 0.6),
                               _P("secondary_mask", 0.5), _P("secondary_trailing", 0.5), _P("tertiary_mask", 0.3),
                               _P("speckle_mask", 0.3)], _drips, True),
    "galvanized_steel": ("Grunge Galvanized Steel", [_P("spangle_contrast", 0.7), _P("facet_mask", 0.5),
                                                     _P("grain_mask", 0.3)], _galvanized_steel, False),
    "layered_noise": ("Grunge Layered Noise", [
        _P("layers", 4, 1, 8, 1, True), _P("lacunarity", 2, 2, 4, 1, True), _P("roughness", 0.55),
        _P("distortion", 0.6), _P("reflection", 0.5)], _layered_noise, False),
    "leaking_streaks": ("Grunge Leaking Streaks", [
        _P("primary_distortion", 0.4), _P("primary_roughness", 0.4), _P("secondary_mask", 0.5),
        _P("secondary_distortion", 0.5), _P("tertiary_mask", 0.4), _P("tertiary_balance", 0.5)],
        _leaking_streaks, True),
    "moisture": ("Grunge Moisture", [_P("spot_mask", 0.5), _P("porosity", 0.5), _P("edge_softness", 0.4),
                                     _P("secondary_mask", 0.4)], _moisture, False),
    "mold_spots": ("Grunge Mold Spots", [_P("density", 0.5), _P("cluster", 0.6), _P("halo", 0.4),
                                         _P("secondary_mask", 0.5)], _mold_spots, False),
    "pine_bark": ("Grunge Pine Bark", [_P("furrow_width", 0.35), _P("plate_layers", 0.6),
                                       _P("primary_distortion", 0.4), _P("secondary_mask", 0.4)], _pine_bark, False),
    "rust": ("Grunge Rust", [_P("coverage", 0.5), _P("edge_breakup", 0.6), _P("pitting_mask", 0.5),
                             _P("secondary_mask", 0.4)], _rust, False),
    "rusty_surface": ("Grunge Rusty Surface", [
        _P("primary_roughness", 0.5), _P("secondary_roughness", 0.5), _P("cracks_mask", 0.5),
        _P("cracks_size", 1.0, 0.25, 4.0, 0.05)], _rusty_surface, True),
    "sheets": ("Grunge Sheets", [_P("layers", 4, 1, 8, 1, True), _P("edge_mask", 0.6), _P("size_variation", 0.5),
                                 _P("primary_distortion", 0.2)], _sheets, False),
    "wipe_trails": ("Grunge Wipe Trails", [_P("primary_mask", 0.8), _P("secondary_mask", 0.5),
                                           _P("streak_fineness", 0.6), _P("arc_spread", 0.6)], _wipe_trails, False),
}


def grunge(img=None, kind="rust", amplitude=1.0, center=0.0, mask_contrast=0.0, element_size=0.25,
           offset="0 0", tile_size="1 1", params=None, seed=0, out_layer="grunge", post=None,
           xres=512, yres=512):
    """One grunge map into out_layer (mono). See the module docstring; params = the map's own parameters
    (missing ones take their defaults; an unknown name is an error)."""
    from .pattern import _base, _pix
    from .pixel import put, _vec
    from . import backend as bk
    from . import noisepost as _pp
    if kind not in KINDS:
        raise ValueError(f"Grunge kind must be one of {tuple(KINDS)}")
    _, spec, fn, _ = KINDS[kind]
    p = {n: d for n, d, *_ in spec}
    bad = set(params or {}) - set(p)
    if bad:
        raise TypeError(f"Grunge {kind}: unknown parameters {sorted(bad)}")
    p.update({k_: float(v) for k_, v in (params or {}).items()})
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    u, v = _pix(W, H)
    off = _vec(offset, 2)
    ts = _vec(tile_size, 2)
    if float(element_size) <= 0 or ts[0] <= 0 or ts[1] <= 0:
        raise ValueError("Element Size and Tile Size must be above 0")
    nx = max(1, int(round(ts[0] / float(element_size))))            # whole elements per tile: the map tiles
    ny = max(1, int(round(ts[1] / float(element_size))))
    x = ((u - off[0]) / ts[0] * nx).reshape(-1)
    y = ((v * (H / W) - off[1]) / ts[1] * ny).reshape(-1)
    h = np.clip(fn(_Space(x, y, nx, ny, seed), p), 0.0, 1.0)
    c = float(np.clip(mask_contrast, 0.0, 0.999))
    if c > 0:                                                       # more extreme, still 0..1
        h = np.clip((h - 0.5 * c) / (1 - c), 0.0, 1.0)
    h = _pp.run(bk.NUMPY, h * float(amplitude) + float(center), post or {})
    put(out, str(out_layer).strip() or "grunge", h.reshape(H, W), like)
    return out
