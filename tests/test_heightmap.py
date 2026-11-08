"""
The height-map family: Height to Normal / Normal to Height / AO / Shadow / Refract /
Caustics / Combine Normals / Convert Normal.

━━ Almost all criteria are **analytic**, not "looks right"
  · On a slope h = a·x + b·y the normal equals normalize(−a, −b, 1) **per pixel**, including the border ring
  · Normal to Height (exact, tile) and Height to Normal are per-pixel inverses -- even white noise
    is recovered, except for 4 modes that are information-theoretically unrecoverable (the test removes them analytically)
  · spectral mode recovers a sine with an amplitude ratio **exactly** equal to sin(ω)/ω
  · AO: exactly 1 on any slope, bit-exactly 1 on convex surfaces, < 1 on concave ones and monotonic in curvature
  · Shadow: a wall's shadow length is exactly H / tan(elevation), counted per pixel
  · Refraction: the offset on a slope equals Snell's law closed form depth · tan(θ − θr)
  · Caustics: a calm water surface is bit-exactly 1; energy conserved when tiled; convex lenses focus, concave lenses spread
  · Scale invariance: scaling height and world_size together leaves normals / AO / shadow unchanged to the pixel

━━ Every criterion that could fail silently has a reverse control
  · No one-sided differences at the border -> slope textures get only half the slope on all four edges (a naive version is hand-written below,
    proving the criterion catches it)
  · AO not masking samples outside the image -> a spurious dark ring on the downhill edge of a slope (inside() stubbed to all 1)
  · spectral mode **cannot** exactly recover white noise (otherwise the exact criterion above would mean nothing)
"""
import math
import os
import sys
import time

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo.cop import CopImage                 # noqa: E402
from comfyui_pcg.geo.cop import heightmap as HM          # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg.geo.cop import transform as TR          # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def L(img, name):
    return np.asarray(BK.backend_of(img.need(name)).to_numpy(img.need(name))
                      if not isinstance(img.need(name), np.ndarray)
                      else img.need(name), np.float64)


def himg(h, name="C"):
    """float64 height -> image on the EXACT backend. Used wherever a criterion has to be exact."""
    return CopImage(h.shape[1], h.shape[0],
                    {name: np.asarray(h, np.float64)[:, :, None]})


W, H = 64, 48
J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                   np.arange(H, dtype=np.float64))
TEX = 1.0 / W                     # pixel spacing for world_size = 1


# ═══════════════════════════════════════════════════ 1. Height to Normal
sec("Height to Normal")
a, b = 0.7, -0.4                  # world slope
plane = a * J * TEX + b * I * TEX
ref = np.array([-a, -b, 1.0]) / math.sqrt(a * a + b * b + 1)
for m in HM.GRADIENTS:
    N = L(HM.height_to_normal(himg(plane), method=m), "N")
    e = float(np.abs(N - ref).max())
    check(f"[{m}] normal of **every** pixel on the slope = normalize(−a,−b,1)", e < 1e-12,
          f"{e:.1e}")
    eb = float(np.abs(np.concatenate([N[0], N[-1], N[:, 0], N[:, -1]])
                      - ref).max())
    check(f"  [{m}] including the border ring (one-sided differences)", eb < 1e-12, f"{eb:.1e}")

# Reverse control: naive central differences with clamped padding give only half the slope at the edge
p = np.pad(plane, 1, mode="edge")
naive_gx = (p[1:-1, 2:] - p[1:-1, :-2]) / 2 / TEX
check("negative control: naive central differences (clamp padding) give only half the slope at the border",
      abs(naive_gx[5, 0] - a / 2) < 1e-12 and abs(naive_gx[5, 5] - a) < 1e-12,
      f"edge {naive_gx[5, 0]:.3f} vs interior {naive_gx[5, 5]:.3f}")

N32 = L(HM.height_to_normal(CopImage(W, H, {
    "C": plane.astype(np.float32)[:, :, None]})), "N")
# Tolerance comes from the input itself: a height of ~0.7 stored as float32 rounds by 6e-8, adjacent pixel differences are ~0.01,
# so the slope's relative error is ~5e-6. The first version used 1e-6, stricter than float32 can represent
check("float32 path equally exact (tolerance 1e-5, from input rounding)",
      float(np.abs(N32 - ref).max()) < 1e-5,
      f"{float(np.abs(N32 - ref).max()):.1e}")

N = L(HM.height_to_normal(himg(plane)), "N")
check("results are unit vectors", float(np.abs(np.linalg.norm(N, axis=-1) - 1).max())
      < 1e-12)
check("convention: h rising along +u -> N.x < 0; rising along +v -> N.y < 0 (OpenGL, green up)",
      (L(HM.height_to_normal(himg(J * TEX)), "N")[..., 0] < 0).all()
      and (L(HM.height_to_normal(himg(I * TEX)), "N")[..., 1] < 0).all())
N0 = L(HM.height_to_normal(himg(plane), strength=0.0), "N")
check("Strength = 0 -> all (0,0,1)", float(np.abs(N0 - [0, 0, 1]).max())
      == 0.0)

# tile: central differences of a periodic function have the closed form A·sin(2πk/W)·cos(2πkx/W)
k = 3
wave = 0.05 * np.sin(2 * np.pi * k * J / W)
N = L(HM.height_to_normal(himg(wave), tile=True), "N")
gx_true = 0.05 * math.sin(2 * math.pi * k / W) * np.cos(2 * np.pi * k * J / W)
nx_true = -(gx_true / TEX) / np.sqrt((gx_true / TEX) ** 2 + 1)
check("tile: matches the closed-form central difference of a periodic function (including first and last columns)",
      float(np.abs(N[..., 0] - nx_true).max()) < 1e-12,
      f"{float(np.abs(N[..., 0] - nx_true).max()):.1e}")
Nnt = L(HM.height_to_normal(himg(wave), tile=False), "N")
# Looking only at column 0 can't catch it: sin is odd about 0, so in that column the one-sided difference happens to equal the central
# difference (the first version fell into this). The last column has no such coincidence
check("  negative control: the same image without tile has different first and last columns (one-sided differences)",
      float(np.abs(Nnt[:, [0, -1], 0] - nx_true[:, [0, -1]]).max()) > 1e-4)

rng = np.random.default_rng(7)
bumpy = rng.random((H, W)) * 0.02
Na = L(HM.height_to_normal(himg(bumpy)), "N")
Nb = L(HM.height_to_normal(himg(bumpy * 5.0), world_size=5.0), "N")
check("scale invariance: height and World Size both ×5, normals unchanged per pixel",
      float(np.abs(Na - Nb).max()) < 1e-12, f"{float(np.abs(Na - Nb).max()):.1e}")
Nc = L(HM.height_to_normal(himg(bumpy), strength=5.0, world_size=5.0), "N")
check("  multiplying by Strength and by the height value are the same thing",
      float(np.abs(Na - Nc).max()) < 1e-12)

rgb = CopImage(W, H, {"C": np.stack([plane, rng.random((H, W)),
                                     rng.random((H, W))], -1)})
check("multi-channel layers only use channel 0 (noise in G/B doesn't matter)",
      float(np.abs(L(HM.height_to_normal(rgb), "N") - ref).max()) < 1e-6)
check("with keep_layers off only N remains",
      HM.height_to_normal(rgb, keep=False).names == ["N"])
err("World Size = 0 raises", lambda: HM.height_to_normal(rgb, world_size=0),
    "World Size")
err("mistyped layer name lists the existing layers", lambda: HM.height_to_normal(rgb, "nope"),
    "no 'nope' layer")
err("malformed Method raises", lambda: HM.height_to_normal(rgb, method="roberts"),
    "Method must be one of")


# ═══════════════════════════════════════════════════ 2. Normal to Height
sec("Normal to Height")


def null_modes(h):
    """The 4 modes central differences can't see: DC + three checkerboards. exact mode can't recover them."""
    sx = (-1.0) ** J
    sy = (-1.0) ** I
    out = np.full_like(h, h.mean())
    for m in (sx, sy, sx * sy):
        out += m * (h * m).mean()
    return out


def roundtrip(h, method, tile, strength=1.0, world=1.0):
    n = HM.height_to_normal(himg(h), strength=strength, world_size=world,
                            tile=tile)
    o, rep = HM.normal_to_height(n, strength=strength, world_size=world,
                                 method=method, tile=tile)
    return L(o, "height")[..., 0], rep


smooth = (0.04 * np.sin(2 * np.pi * 2 * J / W + 0.3)
          + 0.03 * np.cos(2 * np.pi * 3 * I / H) + 0.01 * np.sin(
              2 * np.pi * (J / W + 2 * I / H)))
rec, rep = roundtrip(smooth, "exact", True)
e = float(np.abs(rec - (smooth - smooth.mean())).max())
check("exact + tile: smooth periodic height recovered per pixel (up to a constant)", e < 1e-6,
      f"{e:.1e}")
check("  output mean is 0", abs(float(rec.mean())) < 1e-6)
check("  the report shows no clamped pixels", rep["clamped_nz"] == 0, rep)

noise = rng.random((H, W)) * 0.01
rec, _ = roundtrip(noise, "exact", True)
e = float(np.abs(rec - (noise - null_modes(noise))).max())
check("exact + tile: even **white noise** recovered per pixel (minus the 4 null modes)", e < 1e-7,
      f"{e:.1e}")
rec_s, _ = roundtrip(noise, "spectral", True)
e_s = float(np.abs(rec_s - (noise - null_modes(noise))).max())
check("  negative control: spectral can't recover white noise (otherwise the previous check means nothing)",
      e_s > 100 * max(e, 1e-12), f"{e_s:.1e}")

for period in (16, 8, 4):
    w = 2 * np.pi / period
    Wp = 64
    Jp, Ip = np.meshgrid(np.arange(Wp, dtype=np.float64),
                         np.arange(8, dtype=np.float64))
    hs = 0.01 * np.sin(w * Jp)
    n = HM.height_to_normal(himg(hs), tile=True)
    o, _ = HM.normal_to_height(n, method="spectral", tile=True)
    r = L(o, "height")[..., 0]
    amp = float((r * np.sin(w * Jp)).mean() * 2 / 0.01)
    pred = math.sin(w) / w
    check(f"spectral: sine with period {period} pixels, amplitude ratio = sin(ω)/ω = {pred:.4f}",
          abs(amp - pred) < 1e-5, f"measured {amp:.6f}")

rec, _ = roundtrip(smooth * 3.0, "exact", True, strength=0.25, world=2.0)
check("inverse under the same Strength / World Size (recovers the height **value**, not world height)",
      float(np.abs(rec - (smooth * 3 - (smooth * 3).mean())).max()) < 1e-6)

# Non-tile: mirror extension. The measured numbers are written as criteria -- "right" here is approximately right
plane64 = 0.3 * J * TEX + 0.1 * I * TEX
amp = float(np.ptp(plane64))
rs, _ = roundtrip(plane64, "spectral", False)
es = np.abs(rs - (plane64 - plane64.mean())) / amp
check("non-tile + spectral: slope error < 0.5% of amplitude", float(es.max()) < 5e-3,
      f"{float(es.max()) * 100:.2f}%")
check("  error concentrated at the edges: < 0.1% from 4 pixels in",
      float(es[4:-4, 4:-4].max()) < 1e-3,
      f"{float(es[4:-4, 4:-4].max()) * 100:.3f}%")
re_, _ = roundtrip(plane64, "exact", False)
ee = np.abs(re_ - (plane64 - plane64.mean())) / amp
check("non-tile exact is **actually worse**, and doesn't decay inwards (as stated in the docs)",
      float(ee[4:-4, 4:-4].max()) > 3 * float(es[4:-4, 4:-4].max()),
      f"exact interior {float(ee[4:-4, 4:-4].max()) * 100:.2f}% vs "
      f"spectral {float(es[4:-4, 4:-4].max()) * 100:.3f}%")
# σ² = 20: the edge value is 1.6e-14, truly flat. With σ² = 60 the edge is still 3.4e-6 and the error
# rises to 7e-5 -- the error grows with "how non-flat the border is", which confirms the explanation
bump = np.exp(-((J - 32) ** 2 + (I - 24) ** 2) / 20.0) * 0.05
rb, _ = roundtrip(bump, "exact", False)
check("  a bump already flat at the border: non-tile exact is also nearly exact (no inconsistency at the seam)",
      float(np.abs(rb - (bump - bump.mean())).max()) / float(np.ptp(bump))
      < 1e-6)

tilted = np.zeros((H, W, 3))
tilted[..., 2] = 1.0
tilted[5:9, 5:9] = [0.0, 0.8, -0.6]                 # 16 facing down
o, rep = HM.normal_to_height(CopImage(W, H, {"N": tilted}))
check("pixels with z ≤ 0.01 are clamped, count written to the report", rep["clamped_nz"] == 16, rep)
check("  result still finite after clamping", bool(np.isfinite(L(o, "height")).all()))
err("Strength = 0 raises (it is divided by)",
    lambda: HM.normal_to_height(CopImage(W, H, {"N": tilted}), strength=0),
    "Strength")
err("only 2 channels raises and points to Reconstruct Z",
    lambda: HM.normal_to_height(CopImage(W, H, {"N": tilted[..., :2]})),
    "Reconstruct Z")


# ═══════════════════════════════════════════════════ 3. Height to AO
sec("Height to AO")
steep = 3.0 * J * TEX - 2.0 * I * TEX           # a very steep slope
ao = L(HM.height_to_ao(himg(steep), radius=10), "ao")
check("AO exactly 1 on any slope (including steep ones)", float(ao.min()) > 1 - 1e-12,
      f"min {float(ao.min()):.15f}")
R2 = ((J - W / 2) ** 2 + (I - H / 2) ** 2) * TEX * TEX
dome = -2.0 * R2
ao = L(HM.height_to_ao(himg(dome), radius=10), "ao")
check("convex surface (h = −r²): interior AO **bit-exactly** 1 -- every surrounding point is below the tangent plane",
      bool((ao[1:-1, 1:-1] == 1.0).all()))
# The outermost ring uses one-sided differences, which aren't exact on a quadric (they give the slope half a pixel out);
# measured: only two corners differ, by 7e-16 -- rounding magnitude, not occlusion
check("  border ring also ≥ 1 − 1e-12", float(ao.min()) >= 1 - 1e-12,
      f"{1 - float(ao.min()):.1e}")
bowls = [L(HM.height_to_ao(himg(kk * R2), radius=10), "ao")[H // 2, W // 2, 0]
         for kk in (0.5, 2.0, 8.0)]
check("concave surface (h = +k·r²): AO < 1, and darker for larger k",
      bowls[0] < 1.0 and bowls[0] > bowls[1] > bowls[2],
      " > ".join(f"{v:.4f}" for v in bowls))
base = L(HM.height_to_ao(himg(bumpy), radius=6), "ao")
check("translation invariant: h + constant leaves AO unchanged",
      float(np.abs(base - L(HM.height_to_ao(himg(bumpy + 3.7), radius=6),
                             "ao")).max()) < 1e-9)
check("scale invariance: height and World Size both ×4, AO unchanged",
      float(np.abs(base - L(HM.height_to_ao(himg(bumpy * 4), world_size=4.0,
                                            radius=6), "ao")).max()) < 1e-9)
check("Intensity = 0 -> all 1",
      bool((L(HM.height_to_ao(himg(bumpy), intensity=0.0), "ao")
            == 1.0).all()))
check("range within [0, 1]", 0.0 <= float(base.min()) and float(base.max()) <= 1.0)

# Reverse control: without masking samples outside the image (inside stubbed to all 1), the slope's downhill edge darkens spuriously
_orig_inside = HM._Shift.inside
HM._Shift.inside = lambda self, fx, fy: self.xp.ones((self.H, self.W, 1))
try:
    ao_bad = L(HM.height_to_ao(himg(steep), radius=10), "ao")
finally:
    HM._Shift.inside = _orig_inside
check("negative control: without masking samples outside the image, a spurious dark ring appears at the slope's edge",
      float(ao_bad.min()) < 0.99 and float(ao_bad[10:-10, 10:-10].min())
      > 1 - 1e-9, f"edge min {float(ao_bad.min()):.3f}")
aot = L(HM.height_to_ao(himg(np.sin(2 * np.pi * J / W)
                             * np.cos(2 * np.pi * 2 * I / H) * 0.05),
                        radius=8, tile=True), "ao")
check("tile: shifting a periodic image by a full turn shifts AO along (no seam)",
      float(np.abs(np.roll(aot, 7, 1) - L(HM.height_to_ao(himg(np.roll(
          np.sin(2 * np.pi * J / W) * np.cos(2 * np.pi * 2 * I / H) * 0.05,
          7, 1)), radius=8, tile=True), "ao")).max()) < 1e-12)
err("Directions = 0 raises", lambda: HM.height_to_ao(himg(bumpy), directions=0),
    ">= 1")
err("Radius ≤ 0 raises", lambda: HM.height_to_ao(himg(bumpy), radius=0),
    "Radius")


# ═══════════════════════════════════════════════════ 4. Height to Shadow
sec("Height to Shadow")
check("flat ground has not a single shadow pixel", float(L(HM.height_to_shadow(
    himg(np.zeros((H, W)))), "shadow").sum()) == 0.0)

E = 30.0
L_px = 10.5                                        # deliberately non-integer
Hw = L_px * TEX * math.tan(math.radians(E))
wall = np.zeros((H, W))
wall[:, 40:44] = Hw
sh = L(HM.height_to_shadow(himg(wall), azimuth=0.0, elevation=E,
                           max_distance=20), "shadow")[..., 0]
row = sh[H // 2]
check("light from +u: shadow length left of the wall = H / tan(E) = 10.5 px -> exactly 10 pixels",
      row[:40].sum() == 10 and row[30:40].all() and not row[29],
      f"shadow columns {np.nonzero(row)[0].tolist()}")
check("  wall top and right side both lit", row[40:].sum() == 0)
check("  every row is the same", bool((sh == sh[0]).all()))
sh2 = L(HM.height_to_shadow(himg(wall), azimuth=180.0, elevation=E,
                            max_distance=20), "shadow")[H // 2, :, 0]
check("light from −u: shadow to the right, also 10 pixels",
      sh2[44:].sum() == 10 and sh2[:44].sum() == 0,
      f"{np.nonzero(sh2)[0].tolist()}")
wallh = np.zeros((H, W))
wallh[30:33, :] = Hw
sh3 = L(HM.height_to_shadow(himg(wallh), azimuth=90.0, elevation=E,
                            max_distance=20), "shadow")[:, W // 2, 0]
check("light from +v: shadow cast towards −v (down), also 10 pixels",
      sh3[:30].sum() == 10 and sh3[20:30].all(),
      f"{np.nonzero(sh3)[0].tolist()}")
check("Elevation = 90°: no shadow at all",
      float(L(HM.height_to_shadow(himg(wall), elevation=90.0),
              "shadow").sum()) == 0.0)
inv = L(HM.height_to_shadow(himg(wall), azimuth=0.0, elevation=E,
                            max_distance=20, invert=True), "shadow")[..., 0]
check("Invert exactly equals 1 − shadow", bool((inv == 1.0 - sh).all()))
shs = L(HM.height_to_shadow(himg(wall * 3), world_size=3.0, azimuth=0.0,
                            elevation=E, max_distance=20), "shadow")[..., 0]
check("scale invariance: wall height and World Size both ×3, shadow unchanged to the pixel",
      bool((shs == sh).all()))
soft = L(HM.height_to_shadow(himg(wall), azimuth=0.0, elevation=E,
                             softness=4.0, max_distance=20), "shadow")[H // 2,
                                                                      :, 0]
check("Softness > 0: a transition between 0 and 1 appears at the shadow edge",
      bool(((soft > 0.01) & (soft < 0.99)).any()) and soft[39] > 0.99
      and soft[:20].max() == 0.0,
      f"{np.round(soft[26:40], 2).tolist()}")
# A steep slope facing away from the light, outermost ring on the light side (the first step leaves the image): fall back on the slope in the light direction
ramp = 2.0 * J * TEX           # rising along +u, slope 63°. Light from +u = backlit
shr = L(HM.height_to_shadow(himg(ramp), azimuth=0.0, elevation=E,
                            max_distance=8), "shadow")[..., 0]
check("backlit steep slope self-shadows entirely -- including the outermost column on the light side (the one with no samples)",
      bool((shr == 1.0).all()), f"lit pixels {int((shr == 0).sum())}")
shl = L(HM.height_to_shadow(himg(ramp), azimuth=180.0, elevation=E,
                            max_distance=8), "shadow")[..., 0]
check("  negative control: the same slope facing the light is entirely lit", float(shl.sum()) == 0.0)
err("Elevation outside (0,90] raises",
    lambda: HM.height_to_shadow(himg(wall), elevation=0), "Elevation")
err("too many steps raises", lambda: HM.height_to_shadow(
    himg(wall), max_distance=5000, step=0.5), "limit 4096")


# ═══════════════════════════════════════════════════ 5. Refract from Height
sec("Refract from Height")
rf = L(HM.refract_from_height(himg(np.zeros((H, W)))), "refract")
check("calm water surface offset **exactly** 0", float(np.abs(rf).max()) == 0.0)
check("  two channels (u, v)", rf.shape[2] == 2)
rf1 = L(HM.refract_from_height(himg(bumpy * 5), ior=1.0), "refract")
check("IOR = 1: however much the surface undulates, offset is 0 (no refraction)",
      float(np.abs(rf1).max()) < 1e-12, f"{float(np.abs(rf1).max()):.1e}")
slope = 0.6
rs_ = L(HM.refract_from_height(himg(slope * J * TEX), depth=0.2, ior=1.33),
        "refract")
th = math.atan(slope)
thr = math.asin(math.sin(th) / 1.33)
# Horizontal displacement where the view ray lands = (h + depth)·tan(θ − θr). h varies per pixel, computed per pixel
closed = (slope * J * TEX + 0.2) * math.tan(th - thr)
check("offset on a slope = Snell closed form (h + depth)·tan(θ − θr), per pixel",
      float(np.abs(rs_[..., 0] - closed).max()) < 1e-12,
      f"{float(np.abs(rs_[..., 0] - closed).max()):.1e}")
check("  offset towards uphill (light entering a denser medium bends towards the inward normal)",
      bool((rs_[..., 0] > 0).all()) and float(np.abs(rs_[..., 1]).max()) == 0)
o1, o2, o3 = (L(HM.refract_from_height(himg(bumpy), depth=d), "refract")
              for d in (1.0, 2.0, 3.0))
check("offset is linear in Depth", float(np.abs((o3 - o1) - 2 * (o2 - o1)).max())
      < 1e-12)
# Non-square image: the uv unit in v must be converted by image height so that pixels are square
Wr, Hr = 64, 32
Jr, Ir = np.meshgrid(np.arange(Wr, dtype=np.float64),
                     np.arange(Hr, dtype=np.float64))
ou = L(HM.refract_from_height(himg(slope * Jr / Wr)), "refract")[..., 0]
ov = L(HM.refract_from_height(himg(slope * Ir / Wr)), "refract")[..., 1]
check("non-square image: same slope, the same **number of pixels** of offset in u and v",
      abs(float(ou[5, 5]) * Wr - float(ov[5, 5]) * Hr) < 1e-12,
      f"{float(ou[5, 5]) * Wr:.4f} vs {float(ov[5, 5]) * Hr:.4f} px")
# Into Distort: a constant offset = a global translation
tex = himg(rng.random((H, W)), "C")
cst = CopImage(W, H, {"C": np.asarray(tex.need("C")),
                      "refract": np.broadcast_to(
                          np.array([3.0 / W, 0.0]), (H, W, 2)).copy()})
moved = L(TR.distort(cst, cst, 1.0, "refract", "uv", "wrap", "bilinear",
                     "C"), "C")
check("into COP Distort(uv, 1.0): a 3-pixel uv offset = global translation by 3 pixels",
      float(np.abs(moved - np.roll(L(tex, "C"), -3, 1)).max()) < 1e-9)
err("IOR < 1 raises (the total internal reflection side is not handled)",
    lambda: HM.refract_from_height(himg(bumpy), ior=0.9), "IOR")


# ═══════════════════════════════════════════════════ 6. Height to Caustics
sec("Height to Caustics")
for ss in (1, 2, 3):
    c = L(HM.height_to_caustics(himg(np.zeros((H, W))), supersample=ss),
          "caustics")
    check(f"calm water surface bit-exactly 1 (supersample={ss})", bool((c == 1.0).all()),
          f"[{float(c.min())}, {float(c.max())}]")
c = L(HM.height_to_caustics(himg(np.zeros((H, W))), elevation=35.0,
                            azimuth=60.0), "caustics")
check("calm water surface also bit-exactly 1 under oblique light", bool((c == 1.0).all()))
# The check above can't catch "forgot to subtract the global translation" -- when tiled, a uniform image shifted is still uniform
# (mutation testing deleted that line and it stayed green). The next two do catch it:
cnt = L(HM.height_to_caustics(himg(np.zeros((H, W))), elevation=35.0,
                              azimuth=60.0, tile=False), "caustics")
check("  non-tile + oblique light + calm water: still bit-exactly 1 (no global translation out of frame)",
      bool((cnt == 1.0).all()), f"[{float(cnt.min())}, {float(cnt.max())}]")
R2c = ((J - W / 2) ** 2 + (I - H / 2) ** 2) * TEX * TEX
lens0 = 0.004 * np.exp(-R2c / 0.004)
co = L(HM.height_to_caustics(himg(lens0), depth=0.1, elevation=35.0,
                             azimuth=0.0), "caustics")[..., 0]
pk_i, pk_j = np.unravel_index(int(np.argmax(co)), co.shape)
thr_ = math.asin(math.sin(math.radians(55.0)) / 1.33)
drift = 0.1 * math.tan(thr_) / TEX
check("  under oblique light the lens's spot is still directly below the lens (without subtracting it would slide "
      f"{drift:.1f} pixels)",
      abs(pk_j - W / 2) <= 1.5 and abs(pk_i - H / 2) <= 1.5,
      f"peak at ({pk_j}, {pk_i}), center ({W // 2}, {H // 2})")
ripple = (0.004 * np.sin(2 * np.pi * 3 * J / W) * np.cos(2 * np.pi * 2 * I / H)
          + 0.002 * np.sin(2 * np.pi * (5 * J / W + 3 * I / H)))
c = L(HM.height_to_caustics(himg(ripple), depth=0.3), "caustics")
check("energy conserved when tiled: sum of all pixels = pixel count",
      abs(float(c.sum()) - W * H) < 1e-3, f"{float(c.sum()):.4f} / {W * H}")
check("  and the pattern really is non-uniform (not conserved just because nothing happened)",
      float(c.max()) > 1.5 and float(c.min()) < 0.7,
      f"[{float(c.min()):.2f}, {float(c.max()):.2f}]")
lens = 0.01 * np.exp(-R2 / 0.01)
cd = L(HM.height_to_caustics(himg(lens), depth=0.1), "caustics")
cb = L(HM.height_to_caustics(himg(-lens), depth=0.1), "caustics")
check("a bump is a converging lens: > 1 directly below", cd[H // 2, W // 2, 0] > 1.05,
      f"{cd[H // 2, W // 2, 0]:.3f}")
check("a dent is a diverging lens: < 1 directly below", cb[H // 2, W // 2, 0] < 0.95,
      f"{cb[H // 2, W // 2, 0]:.3f}")
c1 = L(HM.height_to_caustics(himg(ripple), depth=0.3, ior=1.0), "caustics")
check("IOR = 1: whole image ≈ 1 (no refraction, no caustics)",
      float(np.abs(c1 - 1).max()) < 1e-6, f"{float(np.abs(c1 - 1).max()):.1e}")
cn = L(HM.height_to_caustics(himg(ripple), depth=0.3, tile=False),
       "caustics")
check("non-tile: photons landing outside the image are dropped, total energy ≤ pixel count",
      float(cn.sum()) <= W * H + 1e-6, f"{float(cn.sum()):.2f}")
check("running the same image twice is bit-identical (deterministic bincount, so caching makes sense)",
      bool((L(HM.height_to_caustics(himg(ripple), depth=0.3), "caustics")
            == c).all()))
err("Supersample out of range raises",
    lambda: HM.height_to_caustics(himg(ripple), supersample=9), "Supersample")


# ═══════════════════════════════════════════════════ 7. Combine Normals
sec("Combine Normals")
NB = L(HM.height_to_normal(himg(bumpy * 10)), "N")
ND = L(HM.height_to_normal(himg(rng.random((H, W)) * 0.05)), "N")
flat = np.zeros((H, W, 3))
flat[..., 2] = 1.0
for m in HM.BLENDS:
    r = L(HM.combine_normals(CopImage(W, H, {"N": NB, "D": flat}),
                             "N", None, "D", m), "N")
    e = float(np.abs(r - NB).max())
    if m == "linear":
        # The first version of the docs said "all four modes return the base unchanged" -- wrong. normalize(b + (0,0,1))
        # bends the base towards +z, and a flat detail also weakens the slope. That is exactly why linear is the worst
        check("[linear] flat detail -> does **not** return the base (slope weakened, which is why it's the worst)",
              e > 0.1, f"{e:.2f}")
    else:
        check(f"[{m}] flat detail -> returns the base unchanged", e < 1e-12, f"{e:.1e}")
    r2 = L(HM.combine_normals(CopImage(W, H, {"N": NB, "D": ND}),
                              "N", None, "D", m), "N")
    check(f"  [{m}] results are unit vectors",
          float(np.abs(np.linalg.norm(r2, axis=-1) - 1).max()) < 1e-12)
r = L(HM.combine_normals(CopImage(W, H, {"N": flat, "D": ND}), "N", None, "D",
                         "rnm"), "N")
check("rnm: flat base -> returns the detail unchanged", float(np.abs(r - ND).max()) < 1e-12)
r = L(HM.combine_normals(CopImage(W, H, {"N": NB, "D": ND}), "N", None, "D",
                         "rnm", amount=0.0), "N")
check("Amount = 0 -> returns the base unchanged", float(np.abs(r - NB).max()) < 1e-12)
# At small slopes, combining normals ≈ the normal of the summed heights. The first version used bumpy*0.5 as "small slope", but
# the slope was ~0.6, not small at all. Changed to test the **order of convergence**: halve the slope, error drops to at most 1/4
# (first-order exact = error is a second-order small quantity), which is far stronger than picking a tolerance
h1r = rng.random((H, W))
h2r = rng.random((H, W))


def udn_err(sc):
    n1 = L(HM.height_to_normal(himg(h1r * sc)), "N")
    n2 = L(HM.height_to_normal(himg(h2r * sc)), "N")
    ns = L(HM.height_to_normal(himg((h1r + h2r) * sc)), "N")
    r = L(HM.combine_normals(CopImage(W, H, {"N": n1, "D": n2}), "N", None,
                             "D", "udn"), "N")
    return float(np.abs(r - ns).max())


e1, e2 = udn_err(4e-3), udn_err(2e-3)
check("udn ≈ the normal of summed heights, error is second-order: halving the slope reduces the error to ≤ 1/3.5",
      e1 / e2 > 3.5, f"{e1:.1e} -> {e2:.1e}, ratio {e1 / e2:.2f}")
small = CopImage(32, 24, {"N": np.asarray(flat[:24, :32])})
r = HM.combine_normals(CopImage(W, H, {"N": NB}), "N", small, "N", "rnm")
check("detail at a different resolution is resampled first (flat detail -> still the base)",
      float(np.abs(L(r, "N") - NB).max()) < 1e-12)
err("malformed Method raises", lambda: HM.combine_normals(
    CopImage(W, H, {"N": NB}), method="add"), "Method must be one of")


# ═══════════════════════════════════════════════════ 8. Convert Normal
sec("Convert Normal")
packed = NB * 0.5 + 0.5
s1 = L(HM.convert_normal(CopImage(W, H, {"C": packed})), "N")
check("packed -> signed", float(np.abs(s1 - NB).max()) < 1e-12)
p2 = L(HM.convert_normal(CopImage(W, H, {"N": s1}), "N", "signed", "packed"),
       "N")
check("  signed -> packed round trip is the identity", float(np.abs(p2 - packed).max()) < 1e-12)
f1 = HM.convert_normal(CopImage(W, H, {"N": NB}), "N", "signed", "signed",
                       flip_green=True, normalize=False)
f2 = L(HM.convert_normal(f1, "N", "signed", "signed", flip_green=True,
                         normalize=False), "N")
check("Flip Green twice is bit-identical", bool((f2 == NB).all()))
check("  flipping once only changes y", bool((L(f1, "N")[..., 1] == -NB[..., 1]).all()
                          and (L(f1, "N")[..., [0, 2]] == NB[..., [0, 2]])
                          .all()))
rz = L(HM.convert_normal(CopImage(W, H, {"N": NB[..., :2]}), "N", "signed",
                         "signed", reconstruct_z=True), "N")
check("Reconstruct Z: given only xy, the reconstructed z matches the original",
      float(np.abs(rz - NB).max()) < 1e-12)
unn = NB * 1.07
check("Normalize pulls \"nearly 1\" vectors back to unit length",
      float(np.abs(np.linalg.norm(L(HM.convert_normal(
          CopImage(W, H, {"N": unn}), "N", "signed", "signed"), "N"),
          axis=-1) - 1).max()) < 1e-12)
err("only 2 channels and Reconstruct Z off: raises and points the way",
    lambda: HM.convert_normal(CopImage(W, H, {"N": NB[..., :2]}), "N",
                              "signed"), "Reconstruct Z")


# ═══════════════════════════════════════════════════ 9. The whole chain, through nodes
sec("Whole chain (through real nodes)")
rng2 = np.random.default_rng(3)
src = CopImage(W, H, {"C": (rng2.random((H, W)) * 0.01).astype(np.float64)
                      [:, :, None]})
n1 = MAP["PCG_COPHeightToNormal"]().run(src, "C", 1.0, 1.0, "central", True,
                                        "N", True)
n1 = n1["result"][0] if isinstance(n1, dict) else n1[0]
pk = MAP["PCG_COPConvertNormal"]().run(n1, "N", "signed", "packed", False,
                                       False, False, True, "Npk", True)
pk = pk["result"][0] if isinstance(pk, dict) else pk[0]
up = MAP["PCG_COPConvertNormal"]().run(pk, "Npk", "packed", "signed", False,
                                       False, False, True, "N2", True)
up = up["result"][0] if isinstance(up, dict) else up[0]
bk_ = MAP["PCG_COPNormalToHeight"]().run(up, "N2", 1.0, 1.0, "exact", True,
                                         "height", True)
res = bk_["result"] if isinstance(bk_, dict) else bk_
hh = L(res[0], "height")[..., 0]
h0 = L(src, "C")[..., 0]
e = float(np.abs(hh - (h0 - null_modes(h0))).max())
check("height -> normal -> packed -> signed -> height: recovered per pixel (minus null modes)",
      e < 1e-6, f"{e:.1e}")
check("  Normal to Height node carries a one-line report", isinstance(res[1], str)
      and "z clamped on 0/" in res[1], res[1])
names = ["HeightToNormal", "NormalToHeight", "HeightToAO", "HeightToShadow",
         "RefractFromHeight", "HeightToCaustics", "CombineNormals",
         "ConvertNormal"]
check("all eight nodes registered, all under PCG/cop",
      all(MAP.get(f"PCG_COP{n}") is not None
          and MAP[f"PCG_COP{n}"].CATEGORY == "PCG/cop" for n in names))
dflt = {n: {k: (v[1].get("default") if isinstance(v, tuple) and len(v) > 1
                and isinstance(v[1], dict) else None)
            for k, v in MAP[f"PCG_COP{n}"].INPUT_TYPES()["required"].items()}
        for n in names}
hs = [n for n in names if "strength" in dflt[n]]
check("nodes sharing scale parameters have consistent defaults (strength = world_size = 1)",
      len(hs) == 6 and all(dflt[n]["strength"] == 1.0
                           and dflt[n]["world_size"] == 1.0 for n in hs),
      hs)


# ═══════════════════════════════════════════════════ 10. Backend consistency
sec("Backend consistency (numpy float32 vs torch CPU)")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    base32 = CopImage(W, H, {"C": (rng2.random((H, W)) * 0.05)
                             .astype(np.float32)[:, :, None]})
    tbase = base32.to_device("cpu")
    check("the image really moved to torch", tbase.backend.is_torch, tbase.info())
    ops = [
        ("height_to_normal", lambda i: HM.height_to_normal(i), "N"),
        ("height_to_normal/sobel/tile",
         lambda i: HM.height_to_normal(i, method="sobel", tile=True), "N"),
        ("height_to_ao", lambda i: HM.height_to_ao(i, radius=5), "ao"),
        ("height_to_shadow", lambda i: HM.height_to_shadow(
            i, azimuth=33.0, elevation=20.0, max_distance=12), "shadow"),
        ("height_to_shadow/soft", lambda i: HM.height_to_shadow(
            i, azimuth=33.0, elevation=20.0, softness=3.0,
            max_distance=12), "shadow"),
        ("refract", lambda i: HM.refract_from_height(i), "refract"),
        ("combine", lambda i: HM.combine_normals(
            HM.height_to_normal(i)), "N"),
        ("convert", lambda i: HM.convert_normal(
            HM.height_to_normal(i), "N", "signed", "packed",
            flip_green=True), "N"),
        ("normal_to_height (numpy-only)", lambda i: HM.normal_to_height(
            HM.height_to_normal(i))[0], "height"),
        ("caustics (numpy-only)", lambda i: HM.height_to_caustics(
            i, depth=0.05), "caustics"),
    ]
    for nm, fn, lay in ops:
        try:
            g = fn(tbase)
            c = fn(base32)
            same_dev = g.backend.is_torch
            d = float(np.abs(L(g, lay) - L(c, lay)).max())
            check(f"[torch] {nm}: results match, and still on torch",
                  d < 2e-5 and same_dev, f"{d:.1e}")
        except Exception as ex:
            check(f"[torch] {nm}", False, f"{type(ex).__name__}: {ex}")


# ═══════════════════════════════════════════════════ 11. 1024² timing (informational)
sec("1024² timing (numpy, recorded only)")
big = CopImage(1024, 1024, {"C": (np.random.default_rng(1).random(
    (1024, 1024)) * 0.01).astype(np.float32)[:, :, None]})
bn = HM.height_to_normal(big)
for nm, fn in (("Height to Normal", lambda: HM.height_to_normal(big)),
               ("Normal to Height", lambda: HM.normal_to_height(bn)),
               ("AO 8×8", lambda: HM.height_to_ao(big)),
               ("Shadow 64 steps", lambda: HM.height_to_shadow(big)),
               ("Caustics ss=2", lambda: HM.height_to_caustics(big))):
    t0 = time.time()
    fn()
    dt = time.time() - t0
    check(f"{nm}  {dt:.2f} s (limit 10 s)", dt < 10.0)


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
