"""
pcg100 · c3_noise: a batch of Copernicus noise added after checking the SideFX docs.

  Fractal Noise (3D)   COP Noise gets Metric / Jitter (both Worley modes), White / Torus noise types,
                       tiling in v (u+v = flat torus), a Post Processing section
  Worley Noise (3D)    new node PCG_COPWorleyNoise: dist1 / dist2 / border / center / id
  Cellular Noise (3D)  new node PCG_COPCellularNoise: Gap / Bevel / Shape Mode
  Crystal / Bubble / Cloud / Phasor   COP Noise Extra gets Amplitude / Center / Post Processing,
                       Crystal's Metric / Jitter, Phasor's Type / Periodic Function
  Fractal Sample       new node PCG_COPFractalSample

Noise has no bit-exact Houdini reference; the tests use statistical properties (mean / range), the shape of Metric's iso-distance surfaces,
F1 <= F2, tileability, seed determinism and small hand-computed examples.

"Bit-identical to before the change at defaults": digests computed by the same set of calls before the change (commit c87c5d9) are hard-coded in GOLDEN,
independent of git; `--digests` prints the current digests.
"""
import hashlib
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def L(img, name):
    a = img.need(name)
    return np.asarray(img.backend.to_numpy(a) if hasattr(img, "backend") else a,
                      np.float64)


def dig(img):
    h = hashlib.sha1()
    for k in sorted(img.names):
        a = np.ascontiguousarray(np.asarray(L(img, k), np.float32))
        h.update(f"{k}/{a.shape}".encode())
        h.update(a.tobytes())
    return h.hexdigest()[:16]


# ════════════════════════════════════════════ Digests of the old calls (computed before the change)
# only call with the **old signature**'s positional arguments, so they run both before and after the change
def golden_calls():
    out = {}
    N = M["PCG_COPNoise"]()
    for nt in ("value", "perlin", "simplex", "worley", "worley_f2f1"):
        for fr in ("none", "standard", "terrain", "hybrid_terrain"):
            (im,) = N.run(40, 24, nt, fr, 3.0, 3, 2.0, 0.5, 1.3, 0.2, 2,
                          False, 0.1, 0.2, 0.3, "C", 5, "numpy")
            out[f"noise/{nt}/{fr}"] = dig(im)
    (im,) = N.run(32, 32, "simplex", "standard", 4.0, 2, 2.0, 0.5, 1.0, 0.0,
                  1, True, 0.0, 0.0, 0.0, "C", 3, "numpy")
    out["noise/tile_u"] = dig(im)
    (im,) = N.run(32, 32, "worley", "standard", 4.0, 2, 2.0, 0.5, 1.0, 0.0,
                  1, True, 0.0, 0.0, 0.0, "C", 3, "numpy", 0.3, 2.0, 0)
    out["noise/tile_u_time"] = dig(im)
    (im,) = N.run(32, 32, "perlin", "standard", 4.0, 2, 2.0, 0.5, 1.0, 0.0,
                  1, False, 0.0, 0.0, 0.0, "C", 3, "numpy", 0.25, 5.0, 12)
    out["noise/loop"] = dig(im)
    X = M["PCG_COPNoiseExtra"]()
    for kind in ("bubble", "crystal", "phasor", "curl", "curl_3d", "cloud"):
        (im,) = X.run(kind, 6.0, "0.1 0.2 0.3", 2, 0.8, 0.7, 1.0, 2.0, 15.0,
                      30.0, 2, "", 0.5, 0.2, False, 4, "noise", 40, 24, "cpu")
        out[f"extra/{kind}"] = dig(im)
    (im,) = X.run("cloud", 6.0, "0 0 0", 3, 0.8, 0.7, 1.0, 2.0, 15.0,
                  30.0, 2, "", 0.3, 0.1, True, 1, "noise", 24, 24, "cpu")
    out["extra/cloud_billow"] = dig(im)
    return out


GOLDEN = {
    "noise/value/none": "87edf38e6296ada4",
    "noise/value/standard": "543ddfb954270638",
    "noise/value/terrain": "5221fc2800955f84",
    "noise/value/hybrid_terrain": "0d6acea2d3e51daf",
    "noise/perlin/none": "d2d524b0f8cb473e",
    "noise/perlin/standard": "f8632f41c60bb79b",
    "noise/perlin/terrain": "8937e2fbb6fc4efa",
    "noise/perlin/hybrid_terrain": "ec73cd2eb2595a0a",
    "noise/simplex/none": "5d011cd6f83d5ead",
    "noise/simplex/standard": "d22fa81d817e175a",
    "noise/simplex/terrain": "ebedc1b570e067b1",
    "noise/simplex/hybrid_terrain": "cce739fe4180f236",
    "noise/worley/none": "5d1dbad3fec6f04e",
    "noise/worley/standard": "ab1ad0eeef3c4696",
    "noise/worley/terrain": "8bb152238d46c1a2",
    "noise/worley/hybrid_terrain": "5b75e1cdfa5cab5e",
    "noise/worley_f2f1/none": "59ac17eb119b700b",
    "noise/worley_f2f1/standard": "f5343ba4728d32e1",
    "noise/worley_f2f1/terrain": "d2e106ff65bbc413",
    "noise/worley_f2f1/hybrid_terrain": "44a1259ee4fc2097",
    "noise/tile_u": "873debcac612c1a6",
    "noise/tile_u_time": "41553c2f464dae08",
    "noise/loop": "d62275e9d2c2235b",
    "extra/bubble": "2b0d301644cf4a6e",
    "extra/crystal": "98017b9d6ce48db0",
    "extra/phasor": "dbf539fc055dae21",
    "extra/curl": "777bee040442bd61",
    "extra/curl_3d": "29f5b8ecdf3fdcc6",
    "extra/cloud": "0d64b24d8e249090",
    "extra/cloud_billow": "9d4cbc87e9ec0247",
}

if "--digests" in sys.argv:
    for k, v in golden_calls().items():
        print(f'    "{k}": "{v}",')
    sys.exit(0)

from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.panel_specs import SPECS               # noqa: E402
from comfyui_pcg.geo.cop import noise as NS, noisepost as PP  # noqa: E402
from comfyui_pcg.geo.cop import generate as G, backend as BK   # noqa: E402

XP = BK.NUMPY


def A(*v):
    return np.asarray(v, np.float64)


def panel_ok(k):
    it = M[k].INPUT_TYPES()
    bad = PANEL.check_layout(k, it)
    widgets = [w for w, v in it["required"].items() if v[0] != "COPIMAGE"]
    miss = set(widgets) - set(SPECS[k]["order"]) - {"cop"}
    check(f"{k}: panel self-check empty, every widget is in order", not bad and not miss,
          bad or sorted(miss))


def menu_ok(k, key):
    have = M[k].INPUT_TYPES()["required"][key][0]
    mm = SPECS[k]["inputs"][key]["menu"]
    check(f"{k}.{key}: panel menu tokens match the node one to one", list(mm) == list(have),
          (have, list(mm)))


# ═════════════════════════════════════════════════════════════ Regression
sec("Bit-identical to before the change at defaults (hard-coded digests)")
now = golden_calls()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) == 30 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})

# ═════════════════════════════════════════════════════ Post Processing
sec("Post Processing: hand-computed value for each step")
x = A(-0.4, 0.25, 0.5, 0.75)
ap = lambda **k: PP.apply(XP, x.copy(), **k)            # noqa: E731
check("Fold = |x|", np.allclose(ap(fold=True), [0.4, 0.25, 0.5, 0.75]))
check("Complement = 1 − x", np.allclose(ap(complement=True), [1.4, 0.75, 0.5, 0.25]))
check("Bias 0.25: x^2 (ln .25/ln .5 = 2), odd extension for negatives",
      np.allclose(ap(pp_bias=0.25), [-0.16, 0.0625, 0.25, 0.5625]), ap(pp_bias=0.25))
check("Bias 0.75 pulls 0.5 toward 1 (> 0.5), Bias 0.25 toward 0",
      ap(pp_bias=0.75)[2] > 0.5 > ap(pp_bias=0.25)[2])
check("Gain 0.75: 0.25 -> bias(0.5, 0.25)/2 = 0.125; 0.75 -> 0.875; 0.5 unchanged",
      np.allclose(ap(gain=0.75)[1:], [0.125, 0.5, 0.875]), ap(gain=0.75))
check("Gain 0.25 squeezes both ends toward the middle (0.25 -> > 0.25)", ap(gain=0.25)[1] > 0.25)
check("Gamma 2 = x^2 (> 1 darkens, per the docs), odd extension for negatives",
      np.allclose(ap(gamma=2.0), [-0.16, 0.0625, 0.25, 0.5625]))
check("Contrast 2 around 0.5: 0.75 -> 1.0, 0.25 -> 0",
      np.allclose(ap(contrast=2.0), [-1.3, 0.0, 0.5, 1.0]))
check("Clamp Min 0 / Clamp Max 0.6 each act only when their toggle is on",
      np.allclose(ap(use_clamp_min=True, clamp_min=0.0), [0, 0.25, 0.5, 0.75])
      and np.allclose(ap(use_clamp_max=True, clamp_max=0.6), [-0.4, 0.25, 0.5, 0.6])
      and np.allclose(ap(clamp_min=0.3, clamp_max=0.3), x))
check("order Fold -> Complement: -0.4 -> 0.4 -> 0.6 (reversed it would be 1.4)",
      np.isclose(ap(fold=True, complement=True)[0], 0.6))
check("order Contrast -> Clamp: amplify first, then clamp",
      np.allclose(ap(contrast=2.0, use_clamp_min=True, clamp_min=0.0,
                     use_clamp_max=True, clamp_max=1.0), [0, 0, 0.5, 1.0]))
check("order Gamma -> Contrast (reversed, 0.75 would be 1.0^2 = 1.0 instead of 0.625)",
      np.isclose(ap(gamma=2.0, contrast=2.0)[3], 0.625))
check("all defaults: run returns the same object unchanged", PP.run(XP, x, {}) is x)
check("toggling each parameter alone changes the output",
      all(not np.allclose(PP.run(XP, x.copy(), kw), x) for kw in
          (dict(fold=True), dict(complement=True), dict(pp_bias=0.4), dict(gain=0.6),
           dict(gamma=2.0), dict(contrast=0.5), dict(use_clamp_min=True),
           dict(use_clamp_max=True, clamp_max=0.6))))
check("Gain 0.75 takes the lower branch at 0.4: bias(0.8, 0.25)/2 = 0.32; at 0.6, 1 - 0.32",
      np.allclose(PP.apply(XP, A(0.4, 0.6), gain=0.75), [0.32, 0.68]))
b0 = PP.apply(XP, A(0.0, 0.3, 1.0), pp_bias=0.0)
b1 = PP.apply(XP, A(0.0, 0.3, 1.0), pp_bias=1.0)
check("Bias at the endpoints 0 / 1 does not raise or give NaN (clamped into the open interval)",
      np.all(np.isfinite(b0)) and np.all(np.isfinite(b1)) and b0[1] < 1e-6
      and b1[1] > 0.99, (b0, b1))
try:
    PP.pick({"fodl": True})
    check("a misspelled parameter name raises", False)
except TypeError:
    check("a misspelled parameter name raises", True)

# ═══════════════════════════════════════════════════ New COP Noise items
sec("Worley: Metric / Jitter (hand-computed: with jitter = 0 the feature points are at cell centers)")
p3 = [A(0.3), A(0.2), A(0.5)]                # nearest cell center (0.5, 0.5, 0.5)
f1 = {m: float(NS.worley(XP, *p3, 0, "f1", m, 0.0)[0]) for m in NS.METRICS}
check("Euclidean:1 − 2·√(0.2² + 0.3²)", np.isclose(f1["euclidean"], 1 - 2 * np.sqrt(0.13)), f1)
check("Manhattan:1 − 2·(0.2 + 0.3)", np.isclose(f1["manhattan"], 0.0), f1)
check("Chebyshev:1 − 2·max(0.2, 0.3)", np.isclose(f1["chebyshev"], 0.4), f1)
# iso-distance shape: with jitter 0 F1's contours around a cell center are circle / diamond / square
ang = np.linspace(0, 2 * np.pi, 64, endpoint=False)
r = 0.3
cx_, cy_ = 0.5 + r * np.cos(ang), 0.5 + r * np.sin(ang)
z_ = np.full_like(ang, 0.5)
sq = np.maximum(np.abs(np.cos(ang)), np.abs(np.sin(ang)))
dia = np.abs(np.cos(ang)) + np.abs(np.sin(ang))


def dist(m, px, py):
    return (1 - np.asarray(NS.worley(XP, px, py, z_, 0, "f1", m, 0.0))) / 2


check("Euclidean iso-distance line is a circle (distance is constant r on the circle)",
      np.allclose(dist("euclidean", cx_, cy_), r))
dm = dist("manhattan", 0.5 + r * np.cos(ang) / dia, 0.5 + r * np.sin(ang) / dia)
check("Manhattan iso-distance line is a diamond (distance is constant r on |dx|+|dy| = r)", np.allclose(dm, r))
dc = dist("chebyshev", 0.5 + r * np.cos(ang) / sq, 0.5 + r * np.sin(ang) / sq)
check("Chebyshev iso-distance line is a square", np.allclose(dc, r))
check("negative control: Manhattan is not constant on the circle", np.ptp(dist("manhattan", cx_, cy_)) > 0.05)
rng = np.random.default_rng(1)
P = [rng.uniform(-5, 5, 4000) for _ in range(3)]
d1 = np.asarray(NS.worley(XP, *P, 3, "f1", "euclidean", 1.0))
d1b = np.asarray(NS.worley(XP, *P, 3, "f1", "euclidean", 0.5))
check("Jitter 0.5 and 1 give different results (negative control)", not np.allclose(d1, d1b))
check("Jitter 0: regular grid, F1 <= sqrt(3)/2 at any point (farthest from the cell center)",
      np.all((1 - np.asarray(NS.worley(XP, *P, 3, "f1", "euclidean", 0.0))) / 2
             <= np.sqrt(3) / 2 + 1e-12))
for m in NS.METRICS:
    a1 = np.asarray(NS.worley(XP, *P, 3, "f1", m, 0.7))
    a2 = np.asarray(NS.worley(XP, *P, 3, "f2f1", m, 0.7))
    check(f"{m}: F2 - F1 >= 0 (f2f1 maps to >= -1) and F1 in [-1,1]",
          np.all(a2 >= -1) and np.all(np.abs(a1) <= 1))
w4a = np.asarray(NS.worley4(XP, *P, P[0] * 0 + 0.3, 3, "f1", "chebyshev", 0.0))
w4b = np.asarray(NS.worley4(XP, *P, P[0] * 0 + 0.3, 3, "f1", "euclidean", 0.0))
w4j = np.asarray(NS.worley4(XP, A(0.3), A(0.2), A(0.5), A(0.4), 0, "f1", "euclidean", 0.0))
check("4D Worley jitter 0: feature points at 4D cell centers, F1 = sqrt(0.2^2+0.3^2+0.1^2)",
      np.isclose((1 - w4j[0]) / 2, np.sqrt(0.14)), w4j)
check("4D Worley also reads Metric (Chebyshev != Euclidean, and the Chebyshev distance is smaller)",
      not np.allclose(w4a, w4b) and np.all(w4a >= w4b - 1e-12))
try:
    NS.worley(XP, *p3, 0, "f1", "taxicab")
    check("unknown Metric raises", False)
except ValueError:
    check("unknown Metric raises", True)

sec("White (Random)")
xs = rng.uniform(-20, 20, 20000)
wv = np.asarray(NS.white(XP, xs, xs * 0.7, xs * 0 + 0.2, 9))
wv2 = np.asarray(NS.white(XP, np.floor(xs) + 0.99, np.floor(xs * 0.7) + 0.01,
                          xs * 0 + 0.9, 9))
check("same value everywhere within one cell (no interpolation)", np.array_equal(wv, wv2))
cells = rng.integers(-10000, 10000, (3, 50000)).astype(np.float64) + 0.5
wc = np.asarray(NS.white(XP, *cells, 4))
check("range [-1, 1), mean ~ 0, variance ~ 1/3 (uniform distribution)",
      wc.min() >= -1 and wc.max() < 1 and abs(wc.mean()) < 0.02
      and abs(wc.var() - 1 / 3) < 0.01, (wc.mean(), wc.var()))
vn = np.asarray(NS.value_noise(XP, *(np.floor(cells)), 4))
check("White and same-seed Value noise lattice values are not the same sequence (salt offsets them)",
      not np.allclose(np.asarray(NS.white(XP, *cells, 4)), vn))
check("seed determinism: same seed identical, different seed different",
      np.array_equal(wc, np.asarray(NS.white(XP, *cells, 4)))
      and not np.array_equal(wc, np.asarray(NS.white(XP, *cells, 5))))
w4 = np.asarray(NS.white(XP, *cells, 4, w=cells[0] * 0 + 1.5))
w40 = np.asarray(NS.white(XP, *cells, 4, w=cells[0] * 0 + 0.5))
check("given w it mixes in one more dimension: in the w cell [1,2) the values differ, in the w cell [0,1) it equals the 3D version "
      "(keeps w=0 slice compatibility like value4)",
      not np.array_equal(wc, w4) and np.array_equal(wc, w40))

sec("Tiling: Tile V / both / Torus")
uv0 = rng.uniform(0, 1, (300, 2))
for tu, tv in ((True, False), (False, True), (True, True)):
    c0 = G.tile_coords(XP, uv0, 4.0, [0.1, 0.2, 0.3], tu, tv)
    su = G.tile_coords(XP, uv0 + [1, 0], 4.0, [0.1, 0.2, 0.3], tu, tv)
    sv = G.tile_coords(XP, uv0 + [0, 1], 4.0, [0.1, 0.2, 0.3], tu, tv)
    eq = lambda a, b: all((p is None and q is None) or np.allclose(p, q, atol=1e-9)
                          for p, q in zip(a, b))           # noqa: E731
    check(f"tile_u={tu} tile_v={tv}: u+1 {'same point' if tu else 'different point'}, "
          f"v+1 {'same point' if tv else 'different point'}", eq(c0, su) == tu and eq(c0, sv) == tv)
c2 = G.tile_coords(XP, uv0, 4.0, [0, 0, 0], True, True)
check("both: the 4D coordinates lie on two circles of radius F/2pi (flat torus)",
      np.allclose(np.hypot(c2[0], c2[1]), 4 / (2 * np.pi))
      and np.allclose(np.hypot(c2[2], c2[3]), 4 / (2 * np.pi)))
N = M["PCG_COPNoise"]()
base = (96, 64, "simplex", "standard", 3.0, 3, 2.0, 0.5, 1.0, 0.0, 1, True,
        0.0, 0.0, 0.0, "C", 2, "numpy", 0.0, 0.0, 0)
(t1,) = N.run(*base, "euclidean", 1.0, True)
(t2,) = N.run(*base[:2], "torus", *base[3:11], False, *base[12:], "euclidean", 1.0, False)
check("Torus = simplex + Tile U + Tile V (bit-identical, and both Tile toggles are ignored)",
      np.array_equal(L(t1, "C"), L(t2, "C")))
(t0,) = N.run(*base, "euclidean", 1.0, False)
check("negative control: an image with only Tile U differs from the two-way one", not np.array_equal(L(t0, "C"), L(t1, "C")))


def seam(img, axis):
    a = L(img, "C")[..., 0]
    d_in = np.abs(np.diff(a, axis=axis)).mean()
    edge = np.abs(a.take(0, axis) - a.take(-1, axis)).mean()
    return edge / d_in


check("two-way tiling: jumps across the left/right and top/bottom seams are the same order as neighbouring pixels inside (< 1.6x)",
      seam(t1, 1) < 1.6 and seam(t1, 0) < 1.6, (seam(t1, 1), seam(t1, 0)))
(tn,) = N.run(*base[:11], False, *base[12:])
check("negative control: without tiling the seam jump is clearly larger (> 4x)",
      seam(tn, 1) > 4 and seam(tn, 0) > 4, (seam(tn, 1), seam(tn, 0)))
(tvv,) = N.run(*base[:11], False, *base[12:], "euclidean", 1.0, True)
check("only Tile V: seamless top/bottom, not left/right", seam(tvv, 0) < 1.6 and seam(tvv, 1) > 4,
      (seam(tvv, 0), seam(tvv, 1)))
st = L(t1, "C")
check("Torus statistics: mean ~ 0, within [-1, 1]", abs(st.mean()) < 0.15 and np.abs(st).max() <= 1,
      st.mean())
for bad_args, why in (((0.3, 1.0, 0), "two-way tiling + time_scale > 0"),
                      ((0.3, 1.0, 12), "Tile V + loop")):
    try:
        N.run(*base[:11], bad_args[2] == 0, *base[12:18], *bad_args,
              "euclidean", 1.0, True)
        check(f"{why} raises (5D)", False)
    except ValueError:
        check(f"{why} raises (5D)", True)
(tt,) = N.run(*base[:11], False, *base[12:18], 0.3, 2.0, 0, "euclidean", 1.0, True)
check("only Tile V can carry time (4D w = time)", tt.res == (96, 64))

sec("COP Noise node: Metric / Jitter / Post wired up")
wb = (32, 32, "worley", "none", 4.0, 1, 2.0, 0.5, 1.0, 0.0, 1, False, 0.0, 0.0,
      0.5, "C", 2, "numpy", 0.0, 0.0, 0)
(w_e,) = N.run(*wb)
(w_m,) = N.run(*wb, "manhattan")
(w_j,) = N.run(*wb, "euclidean", 0.0)
check("Metric / Jitter change the node output", not np.array_equal(L(w_e, "C"), L(w_m, "C"))
      and not np.array_equal(L(w_e, "C"), L(w_j, "C")))
(w_p,) = N.run(*wb, fold=True, gamma=2.0, use_clamp_max=True, clamp_max=0.5)
check("Post comes after Amplitude / Center, equal to applying it by hand to the old output",
      np.allclose(L(w_p, "C"), np.minimum(np.abs(L(w_e, "C")) ** 2, 0.5), atol=1e-6))
for fr in ("standard", "terrain", "hybrid_terrain"):
    wf = (*wb[:3], fr, *wb[4:5], 3, *wb[6:])
    (fe,) = N.run(*wf)
    (fm,) = N.run(*wf, "chebyshev")
    (fj,) = N.run(*wf, "euclidean", 0.3)
    check(f"Fractal {fr}: every octave reads Metric / Jitter",
          not np.array_equal(L(fe, "C"), L(fm, "C"))
          and not np.array_equal(L(fe, "C"), L(fj, "C")))
(h1,) = N.run(*wb[:3], "hybrid_terrain", 4.0, 1, *wb[6:], "manhattan", 0.3)
(n1,) = N.run(*wb[:3], "none", 4.0, 1, *wb[6:], "manhattan", 0.3)
check("Hybrid Terrain with only 1 octave = non-fractal (hand-computed: (n+o)·1/1 - o), the first octave also reads Metric",
      np.allclose(L(h1, "C"), L(n1, "C"), atol=1e-6))
(o0,) = N.run(*base[:11], False, *base[12:], "euclidean", 1.0, True)
(o1,) = N.run(*base[:11], False, 0.7, *base[13:], "euclidean", 1.0, True)
check("with only Tile V, Offset X still translates in u (negative control: changing offset_x must change the image)",
      not np.array_equal(L(o0, "C"), L(o1, "C")))
(sx,) = N.run(*base[:2], "simplex", *base[3:11], False, *base[12:], "manhattan", 0.3)
check("non-Worley types do not read Metric / Jitter (bit-identical to default, so hiding them in the panel is right)",
      np.array_equal(L(sx, "C"), L(tn, "C")))
(wh,) = N.run(*base[:2], "white", "none", *base[4:11], False, *base[12:])
whv = L(wh, "C")[..., 0]
check("White at Frequency 3: one value per cell (<= 4 distinct values per row)",
      max(len(np.unique(r_)) for r_ in whv) <= 4, max(len(np.unique(r_)) for r_ in whv))
try:
    import torch                                        # noqa: F401
    (cn,) = N.run(*wb[:17], "numpy", 0.0, 0.0, 0, "chebyshev", 0.6, False,
                  pp_bias=0.3, contrast=1.5)
    (ct,) = N.run(*wb[:17], "cpu", 0.0, 0.0, 0, "chebyshev", 0.6, False,
                  pp_bias=0.3, contrast=1.5)
    check("torch backend: Metric / Jitter / Post match numpy (1e-4)",
          np.allclose(L(cn, "C"), L(ct, "C"), atol=1e-4),
          np.abs(L(cn, "C") - L(ct, "C")).max())
except ImportError:
    print("  (torch not installed, skipping the torch comparison)")
panel_ok("PCG_COPNoise")
menu_ok("PCG_COPNoise", "noise_type")
menu_ok("PCG_COPNoise", "metric")

# ═══════════════════════════════════════════════ New Worley / Cellular nodes
from comfyui_pcg.geo.cop import cellnoise as CN        # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX             # noqa: E402

sec("Worley: regular grid with jitter 0 (hand-computed)")
Pr = rng.uniform(0, 1, (6000, 2))
f0 = CN.cell_fields(Pr, 0.1, jitter=0.0)
c = (np.floor(Pr / 0.1) + 0.5) * 0.1
check("center = center of the containing cell", np.allclose(f0["center"], c))
check("dist1 = Euclidean distance to the cell center", np.allclose(f0["d1"], np.linalg.norm(Pr - c, axis=1)))
edge = np.minimum.reduce([Pr[:, 0] - c[:, 0] + 0.05, c[:, 0] + 0.05 - Pr[:, 0],
                          Pr[:, 1] - c[:, 1] + 0.05, c[:, 1] + 0.05 - Pr[:, 1]])
check("border = distance to the square cell's edge (exact)", np.allclose(f0["border"], edge, atol=1e-12))
fm = CN.cell_fields(Pr, 0.1, jitter=0.0, metric="manhattan")
fc = CN.cell_fields(Pr, 0.1, jitter=0.0, metric="chebyshev")
check("Manhattan:dist1 = |dx|+|dy|;Chebyshev:max(|dx|,|dy|)",
      np.allclose(fm["d1"], np.abs(Pr - c).sum(1)) and np.allclose(fc["d1"], np.abs(Pr - c).max(1)))
check("Manhattan / Chebyshev border = (dist2 - dist1)/2",
      np.allclose(fm["border"], (fm["d2"] - fm["d1"]) / 2)
      and np.allclose(fc["border"], (fc["d2"] - fc["d1"]) / 2))
fx = CN.cell_fields(Pr, 0.1, jitter=0.0, offset=(0.03, -0.02, 0))
fx0 = CN.cell_fields(Pr - [0.03, -0.02], 0.1, jitter=0.0)
check("Offset: the whole pattern translates (center translates too)",
      np.allclose(fx["d1"], fx0["d1"]) and np.allclose(fx["center"], fx0["center"] + [0.03, -0.02]))
fa = CN.cell_fields(Pr, 0.1, scale=(2, 1, 1), jitter=0.0)
check("Element Scale 2,1: cell size 0.2 x 0.1, center x = (floor(x/0.2)+1/2)·0.2",
      np.allclose(fa["center"][:, 0], (np.floor(Pr[:, 0] / 0.2) + 0.5) * 0.2)
      and np.allclose(fa["center"][:, 1], c[:, 1]))
fjs = CN.cell_fields(Pr, 0.1, jitter=1.0, jitter_scale=(0, 1, 1))
check("Jitter Scale 0,1: no jitter in x (center x all on the cell center lines), jitter in y",
      np.allclose(((fjs["center"][:, 0] / 0.1) - 0.5) % 1, 0, atol=1e-9)
      and not np.allclose(((fjs["center"][:, 1] / 0.1) - 0.5) % 1, 0, atol=1e-3))

sec("Worley: hexagonal lattice (jitter 0 = regular triangular lattice)")
fh = CN.cell_fields(Pr, 0.1, jitter=0.0, lattice="hexagonal")
uc = np.unique(np.round(fh["center"], 9), axis=0)
dd = np.linalg.norm(uc[:, None] - uc[None], axis=-1)
nn = np.sort(dd, 1)[:, 1]
check("spacing between neighbouring feature points all = Element Size (triangular lattice)", np.allclose(nn, 0.1), (nn.min(), nn.max()))
check("max dist1 = circumradius 0.1/sqrt(3) (regular hexagonal cell)",
      fh["d1"].max() <= 0.1 / np.sqrt(3) + 1e-12 and fh["d1"].max() > 0.055)
check("max border = inradius 0.05", np.isclose(fh["border"].max(), 0.05, atol=2e-3)
      and fh["border"].max() <= 0.05 + 1e-12, fh["border"].max())
check("negative control: the rectangular lattice's max dist1 is close to 0.1/sqrt(2) (square cell)",
      0.065 < f0["d1"].max() <= 0.1 / np.sqrt(2))
for bad_kw, why in ((dict(lattice="hexagonal", tile=(1, 1)), "hexagonal + tiling"),
                    (dict(metric="taxicab"), "unknown Metric"), (dict(lattice="tri"), "unknown lattice")):
    try:
        CN.cell_fields(Pr[:4], 0.1, **bad_kw)
        check(f"{why} raises", False)
    except ValueError:
        check(f"{why} raises", True)
try:
    CN.cell_fields(rng.uniform(0, 1, (4, 3)), 0.1, lattice="hexagonal")
    check("3D hexagonal raises (not implemented)", False)
except ValueError:
    check("3D hexagonal raises (not implemented)", True)

sec("Worley: properties under random jitter")
fr_ = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=3)
check("dist1 ≤ dist2,border ≥ 0", np.all(fr_["d1"] <= fr_["d2"]) and fr_["border"].min() >= 0)
check("border >= (dist2 - dist1)/2 (lower bound of the bisector-plane distance, derived by hand)",
      np.all(fr_["border"] >= (fr_["d2"] - fr_["d1"]) / 2 - 1e-12))
check("dist1 = |P − center|", np.allclose(fr_["d1"], np.linalg.norm(Pr - fr_["center"], axis=1)))
check("id has negatives (signed 32-bit), all integers", fr_["id"].min() < 0 and np.all(fr_["id"] == np.round(fr_["id"])))
check("same id <=> same center", len(np.unique(fr_["id"])) == len(np.unique(np.round(fr_["center"], 9), axis=0)))
fr2 = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=3)
fr3 = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=4)
check("seed determinism", np.array_equal(fr_["d1"], fr2["d1"]) and not np.allclose(fr_["d1"], fr3["d1"]))
fsm = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=3, round_border=0.3)
check("Round Border: smooth-min <= min, and it really changed",
      np.all(fsm["border"] <= fr_["border"] + 1e-12) and not np.allclose(fsm["border"], fr_["border"]))
fsm_m = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=3, round_border=0.3, metric="manhattan")
fm_m = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=3, metric="manhattan")
check("Round Border only acts under Euclidean (hiding it in the panel is right)",
      np.array_equal(fsm_m["border"], fm_m["border"]))
# exactness: where id changes on the image, border is less than a pixel; where border is more than a pixel all four neighbours share the id
W_ = 128
(wi,) = M["PCG_COPWorleyNoise"]().run(0.1, "1 1 1", 1.0, "1 1 1", "rectangular",
                                      "euclidean", 0.0, "0 0 0", False, "1 1 1", "", 7,
                                      "", W_, W_)
bd, ids = L(wi, "border")[..., 0], L(wi, "id")[..., 0]
chg = ids[:, 1:] != ids[:, :-1]
check("where id changes (neighbouring pixels across cells) border < 1 pixel", np.all(np.minimum(bd[:, 1:], bd[:, :-1])[chg] < 1 / W_))
inner = bd[1:-1, 1:-1] > 1.0 / W_
same4 = ((ids[1:-1, 1:-1] == ids[:-2, 1:-1]) & (ids[1:-1, 1:-1] == ids[2:, 1:-1])
         & (ids[1:-1, 1:-1] == ids[1:-1, :-2]) & (ids[1:-1, 1:-1] == ids[1:-1, 2:]))
check("where border > 1 pixel all four neighbours are in the same cell (border not overestimated)", np.all(same4[inner]))
check("five output layers, names match Houdini", sorted(wi.names) == ["border", "center", "dist1", "dist2", "id"])
check("center has 2 channels", L(wi, "center").shape[2] == 2)

sec("Worley: checks added from mutation testing")
Pz = A([0.05, 0.05, 0.05], [0.05, 0.05, 0.15])
fz = CN.cell_fields(Pz, 0.1, jitter=0.3, seed=1)
check("3D: feature points of two cells adjacent in z have different xy (the third dimension enters the hash)",
      not np.allclose(fz["center"][0, :2], fz["center"][1, :2]))
for bad, why, word in ((lambda: CN.cell_fields(rng.uniform(0, 1, (3, 4)), 0.1), "4D position", "2 or 3"),
                       (lambda: CN.cell_fields(rng.uniform(0, 1, (3, 3)), 0.1, lattice="hexagonal"),
                        "3D hexagonal", "Hexagonal"),
                       (lambda: CN.cell_fields(Pr[:3], 0.0), "Element Size 0", "Element Size")):
    try:
        bad()
        check(f"{why} raises and states the reason", False)
    except ValueError as e:
        check(f"{why} raises and states the reason", word in str(e), e)
imq = CopImage(4, 4)
PX.put(imq, "P4", np.zeros((4, 4, 4)))
try:
    M["PCG_COPWorleyNoise"]().run(0.1, "1", 1.0, "1", "rectangular", "euclidean", 0.0,
                                  "0", False, "1", "P4", 0, "", 8, 8, cop=imq)
    check("Pos Layer with 4 channels raises", False)
except ValueError as e:
    check("Pos Layer with 4 channels raises", "channels" in str(e))
ftr = CN.cell_fields(Pr, 0.28, jitter=0.0, tile=(1, 1))
check("Tile 1 / Element 0.28: cell count round(3.57) = 4 (not floor's 3)",
      np.allclose(ftr["center"], (np.floor(Pr * 4) + 0.5) / 4))
check("id also changes with the seed (with jitter 0 the nearest cell is seed-independent, yet id still changes -- reseeding changes random colouring)",
      not np.array_equal(fr_["id"], fr3["id"])
      and not np.any(CN.cell_fields(Pr, 0.1, jitter=0.0, seed=1)["id"]
                     == CN.cell_fields(Pr, 0.1, jitter=0.0, seed=2)["id"]))
Pj = rng.uniform(-30, 30, (100000, 2))
P3j = rng.uniform(-20, 20, (20000, 3))
_s0 = dict(CN.SEARCH)
try:
    ref = CN.cell_fields(Pj, 1.0, jitter=1.0, seed=9)
    ref3 = CN.cell_fields(P3j, 1.0, jitter=1.0, seed=9)
    CN.SEARCH.update({2: 4, 3: 3})
    big = CN.cell_fields(Pj, 1.0, jitter=1.0, seed=9)
    big3 = CN.cell_fields(P3j, 1.0, jitter=1.0, seed=9)
    CN.SEARCH.update({2: 1, 3: 1})
    small = CN.cell_fields(Pj, 1.0, jitter=1.0, seed=9)
finally:
    CN.SEARCH.update(_s0)
same = lambda a, b: all(np.array_equal(a[k], b[k]) for k in ("d1", "d2", "border", "id"))  # noqa
check("a 2D / 3D search of +-2 is enough: switching to +-4 / +-3 gives bit-identical results (dist / border / id)",
      same(ref, big) and same(ref3, big3))
check("negative control: shrinking the 2D search to +-1 gives wrong dist2 / border at some points",
      not np.array_equal(ref["d2"], small["d2"])
      and not np.array_equal(ref["border"], small["border"]))
(wr,) = M["PCG_COPWorleyNoise"]().run(0.1, "1 1 1", 0.0, "1 1 1", "rectangular",
                                      "euclidean", 0.0, "0 0 0", True, "1 0.5 1", "", 1,
                                      "", 40, 20)
cy_ = L(wr, "center")[..., 1]
check("non-square image (40x20): y = v·H/W in [0, 0.5], Tile 0.5 -> 5 cells", np.allclose(np.unique(np.round(cy_, 9)),
      (np.arange(5) + 0.5) / 10), np.unique(np.round(cy_, 9)))
(wt3,) = M["PCG_COPWorleyNoise"]().run(0.3, "1 1 1", 0.0, "1 1 1", "rectangular",
                                       "euclidean", 0.0, "0 0 0", True, "1 1 1", "", 1,
                                       "", 24, 24)
check("Tile wired up on the node: Element 0.3 -> 3 cells, center x in {1/6, 1/2, 5/6}",
      np.allclose(np.unique(np.round(L(wt3, "center")[..., 0], 9)), [1 / 6, 0.5, 5 / 6]))

sec("Worley: tiling")
ft = CN.cell_fields(Pr, 0.3, jitter=0.0, tile=(1, 1))
check("Tile 1 / Element 0.3: cell count rounded to 3, Element Size becomes 1/3",
      np.allclose(ft["center"], (np.floor(Pr * 3) + 0.5) / 3))
fta = CN.cell_fields(Pr, 0.07, jitter=1.0, seed=2, tile=(1, 0.5))
ftb = CN.cell_fields(Pr + [1, 0], 0.07, jitter=1.0, seed=2, tile=(1, 0.5))
ftc = CN.cell_fields(Pr + [0, 0.5], 0.07, jitter=1.0, seed=2, tile=(1, 0.5))
check("period exactly equals Tile Size (dist / border / id identical when shifted by x 1, y 0.5)",
      all(np.allclose(fta[k], g[k]) for k in ("d1", "d2", "border", "id") for g in (ftb, ftc)))
check("center shifts by one period too", np.allclose(ftb["center"], fta["center"] + [1, 0]))
fnt = CN.cell_fields(Pr + [1, 0], 0.07, jitter=1.0, seed=2)
check("negative control: without tiling a shift of 1 gives a different result", not np.allclose(fnt["d1"], fta["d1"]))

sec("Worley node: 3D (Pos Layer with 3 channels), Post, prefix")
P3_ = rng.uniform(-1, 1, (16, 24, 3))
im3 = CopImage(24, 16)
PX.put(im3, "P", P3_)
(w3,) = M["PCG_COPWorleyNoise"]().run(0.25, "1 1 1", 0.0, "1 1 1", "rectangular",
                                      "euclidean", 0.0, "0 0 0", False, "1 1 1", "P", 1,
                                      "w_", 99, 99, cop=im3)
P3f = np.asarray(L(im3, "P"))
c3 = (np.floor(P3f / 0.25) + 0.5) * 0.25
check("3D: resolution follows cop, center 3 channels = 3D cell center, dist1 hand-computed",
      w3.res == (24, 16) and np.allclose(L(w3, "w_center"), c3, atol=1e-6)
      and np.allclose(L(w3, "w_dist1")[..., 0], np.linalg.norm(P3f - c3, axis=-1), atol=1e-6))
check("prefix + input layers kept", "P" in w3.names and "w_dist2" in w3.names)
(wp,) = M["PCG_COPWorleyNoise"]().run(0.1, "1 1 1", 1.0, "1 1 1", "rectangular",
                                      "euclidean", 0.0, "0 0 0", False, "1 1 1", "", 7,
                                      "", W_, W_, complement=True)
check("Post acts only on dist1 / dist2 (Complement: 1 - d), border unchanged",
      np.allclose(L(wp, "dist1"), 1 - L(wi, "dist1"), atol=1e-6)
      and np.allclose(L(wp, "dist2"), 1 - L(wi, "dist2"), atol=1e-6)
      and np.array_equal(L(wp, "border"), L(wi, "border")))
try:
    M["PCG_COPWorleyNoise"]().run(0.1, "1", 1.0, "1", "rectangular", "euclidean", 0.0,
                                  "0", False, "1", "P", 0, "", 8, 8)
    check("Pos Layer given without cop connected raises", False)
except ValueError:
    check("Pos Layer given without cop connected raises", True)
panel_ok("PCG_COPWorleyNoise")
for key in ("lattice", "metric"):
    menu_ok("PCG_COPWorleyNoise", key)

sec("Cellular: shaping (hand-computed)")
# cell 0.1, jitter 0: point (0.08, 0.05) is 0.03 from the center, 0.02 from the right edge
q = A(0.08, 0.05)[None]
fq = CN.cell_fields(q, 0.1, jitter=0.0)
check("hand-computed point: dist1 = 0.03, border = 0.02",
      np.isclose(fq["d1"][0], 0.03) and np.isclose(fq["border"][0], 0.02))
check("Absolute:clamp((0.02 − 0.01/2)/0.03) = 0.5",
      np.isclose(CN.cellular_shape(fq["border"], fq["d1"], "absolute", 0.01, 0.03)[0], 0.5))
check("Relative: 0.02/(0.02+0.03) = 0.4, minus Gap 0.1 = 0.3, / Bevel 0.5 = 0.6",
      np.isclose(CN.cellular_shape(fq["border"], fq["d1"], "relative", 0.1, 0.5)[0], 0.6))
check("Relative endpoints: 1 at the feature point, 0 at the cell border",
      np.isclose(CN.cellular_shape(A(0.05), A(0.0), "relative", 0, 1)[0], 1)
      and CN.cellular_shape(A(0.0), A(0.05), "relative", 0, 1)[0] == 0)
check("Bevel 0 = hard edge 0/1", set(np.unique(CN.cellular_shape(f0["border"], f0["d1"], "absolute", 0.02, 0))) <= {0.0, 1.0})
check("Gap larger than the cell width: cells vanish entirely", CN.cellular_shape(f0["border"], f0["d1"], "absolute", 0.2, 0.01).max() == 0)
try:
    CN.cellular_shape(A(0.1), A(0.1), "percent")
    check("unknown Shape Mode raises", False)
except ValueError:
    check("unknown Shape Mode raises", True)
CEL = M["PCG_COPCellularNoise"]()
cargs = (0.1, "1 1 1", 1.0, "1 1 1", "rectangular", "euclidean", 0.0, "0 0 0", False,
         "1 1 1", "absolute", 0.01, 0.03, "", 7, "", W_, W_)
(ce,) = CEL.run(1.0, 0.0, *cargs)
expect = np.clip((L(wi, "border") - 0.005) / 0.03, 0, 1)
check("node: noise = clamp((border - Gap/2)/Bevel), border/center/id are the same as the Worley node's",
      np.allclose(L(ce, "noise"), expect, atol=1e-6)
      and np.array_equal(L(ce, "border"), L(wi, "border"))
      and np.array_equal(L(ce, "id"), L(wi, "id")))
(ce2,) = CEL.run(2.0, -0.5, *cargs)
check("Amplitude / Shift: multiply first, then add", np.allclose(L(ce2, "noise"), 2 * L(ce, "noise") - 0.5, atol=1e-6))
(ce3,) = CEL.run(1.0, 0.0, *cargs[:10], "relative", *cargs[11:])
check("negative control: Relative and Absolute outputs differ", not np.allclose(L(ce3, "noise"), L(ce, "noise")))
(ce4,) = CEL.run(1.0, 0.0, *cargs[:6], 0.4, *cargs[7:])
check("Smooth Edge changes border and noise", not np.allclose(L(ce4, "border"), L(ce, "border")))
(ce5,) = CEL.run(1.0, 0.0, *cargs, use_clamp_max=True, clamp_max=0.5)
check("Post (Clamp Max) acts on noise", np.allclose(L(ce5, "noise"), np.minimum(L(ce, "noise"), 0.5), atol=1e-6))
check("Cellular outputs four layers", sorted(ce.names) == ["border", "center", "id", "noise"])
panel_ok("PCG_COPCellularNoise")
for key in ("lattice", "metric", "shape_mode"):
    menu_ok("PCG_COPCellularNoise", key)

# ═══════════════════════════════════════════════════════ COP Noise Extra
from comfyui_pcg.geo.cop import noisex as NX            # noqa: E402
sec("Noise Extra: Crystal's Metric / Jitter")
XN = M["PCG_COPNoiseExtra"]()
xa = ("crystal", 4.0, "0 0 0.5", 2, 0.8, 0.7, 1.0, 2.0, 15.0, 30.0, 2, "", 0.5, 0.2,
      False, 4, "noise", 32, 32, "cpu")
(cr0,) = XN.run(*xa)
(crj,) = XN.run(*xa, "euclidean", 0.0)
idj = L(crj, "noise_id")[..., 0]
blk = idj.reshape(4, 8, 4, 8)
check("Jitter 0: feature points at cell centers, cells are the grid cells -- id constant within each 8x8 pixel block (= one cell), different between blocks",
      np.all(blk == blk[:, :1, :, :1]) and len(np.unique(idj)) == 16)
(crm,) = XN.run(*xa, "manhattan")
(crc,) = XN.run(*xa, "chebyshev")
check("Metric changes which cell is picked (Manhattan / Chebyshev id images differ from Euclidean)",
      not np.array_equal(L(crm, "noise_id"), L(cr0, "noise_id"))
      and not np.array_equal(L(crc, "noise_id"), L(cr0, "noise_id")))
check("_edge (F2 - F1) >= 0 under every metric",
      all(L(im_, "noise_edge").min() >= 0 for im_ in (cr0, crm, crc)))
XA = NX.AC.pick(None, "cpu", 4, 1)[0]
md = {m: float(np.asarray(NX._mdist(XA, A(0.1), A(-0.2), A(0.3), m))[0]) for m in NS.METRICS}
check("Crystal's 3D distances (hand-computed): sqrt(0.14) / 0.6 / 0.3",
      np.isclose(md["euclidean"], np.sqrt(0.14)) and np.isclose(md["manhattan"], 0.6)
      and np.isclose(md["chebyshev"], 0.3), md)
xb = ("bubble",) + xa[1:]
(bb0,) = XN.run(*xb)
(bb1,) = XN.run(*xb, "chebyshev", 0.0)
check("Metric / Jitter only for Crystal (Bubble does not read them, hiding them in the panel is right)",
      np.array_equal(L(bb0, "noise"), L(bb1, "noise")))
try:
    NX.crystal(NX.AC.pick(None, "cpu", 4, 1)[0], A(0.1), A(0.1), 0.0, 0, 1.0, "taxicab")
    check("Crystal unknown Metric raises", False)
except ValueError:
    check("Crystal unknown Metric raises", True)

sec("Noise Extra: Phasor's Type / Periodic Function")
pa = ("phasor", 6.0, "0 0 0", 2, 0.8, 0.7, 1.0, 2.0, 15.0, 30.0, 4, "", 0.5, 0.2,
      False, 4, "noise", 64, 64, "cpu")
(ph0,) = XN.run(*pa)
(phs,) = XN.run(*pa, "euclidean", 1.0, "phasor_wave", "sine")
(phr,) = XN.run(*pa, "euclidean", 1.0, "phasor_wave", "rectangle")
(phw,) = XN.run(*pa, "euclidean", 1.0, "phasor_wave", "saw")
(phg,) = XN.run(*pa, "euclidean", 1.0, "gabor_noise")
(phi,) = XN.run(*pa, "euclidean", 1.0, "intensity_field")
m0 = L(ph0, "noise")
check("Phasor Wave + Sine = the original output (bit-identical)", np.array_equal(L(phs, "noise"), m0))
check("Rectangle: only 0 / 1, and = [sine >= 0.5]",
      np.array_equal(L(phr, "noise"), (m0 >= 0.5).astype(np.float64)))
check("Saw = phase phi/2pi + 1/2 (same as the _phase layer)",
      np.allclose(L(phw, "noise"), L(ph0, "noise_phase"), atol=1e-6))
g_, i_ = L(phg, "noise"), L(phi, "noise")
amp4 = L(ph0, "noise_amplitude")
check("Intensity Field = |S|/√K(K = 4)", np.allclose(i_, amp4 / 2, atol=1e-6))
check("|2·Gabor - 1| <= Intensity (real part does not exceed the modulus)", np.all(np.abs(2 * g_ - 1) <= i_ + 1e-6))
sd = (2 * g_ - 1).std()
check("Gabor: mean ~ 0.5, std of Re(S)/sqrt(K) ~ 1/3 (variance K/9 derived by hand)",
      abs(g_.mean() - 0.5) < 0.06 and 0.25 < sd < 0.42, (g_.mean(), sd))
check("Gabor ignores the periodic function (Periodic only acts on Phasor Wave)",
      np.array_equal(L(XN.run(*pa, "euclidean", 1.0, "gabor_noise", "saw")[0], "noise"), g_))
check("auxiliary layers are not affected by Type", np.array_equal(L(phg, "noise_phase"), L(ph0, "noise_phase")))
for kw in (dict(ptype="phasor"), dict(periodic="square")):
    try:
        NX.phasor_main(None, {}, 4, **kw)
        check(f"unknown {kw} raises", False)
    except ValueError:
        check(f"unknown {kw} raises", True)

sec("Noise Extra: Amplitude / Center / Post act only on the main layer")
for kind in ("bubble", "cloud", "curl"):
    ka = (kind,) + pa[1:]
    (k0,) = XN.run(*ka)
    (k1,) = XN.run(*ka, "euclidean", 1.0, "phasor_wave", "sine", 2.0, 0.25)
    (k2,) = XN.run(*ka, "euclidean", 1.0, "phasor_wave", "sine", 2.0, 0.25, fold=True)
    aux = [n for n in k0.names if n != "noise"]
    check(f"{kind}: main layer = old x 2 + 0.25, Fold after it; auxiliary layer {aux} unchanged",
          np.allclose(L(k1, "noise"), L(k0, "noise") * 2 + 0.25, atol=1e-6)
          and np.allclose(L(k2, "noise"), np.abs(L(k0, "noise") * 2 + 0.25), atol=1e-6)
          and all(np.array_equal(L(k1, n), L(k0, n)) for n in aux))
(k3,) = XN.run(*(("cloud",) + pa[1:]), "euclidean", 1.0, "phasor_wave", "sine", 1.0, 0.0)
(k4,) = XN.run(*(("cloud",) + pa[1:]), "euclidean", 1.0, "phasor_wave", "sine", 1.0, 0.3)
check("changing only Center (Amplitude still 1) also takes effect", np.allclose(
    L(k4, "noise"), L(XN.run(*(("cloud",) + pa[1:]))[0], "noise") + 0.3, atol=1e-6))
check("Amplitude 1 / Center 0 = old behaviour", np.array_equal(L(k3, "noise"), L(XN.run(*(("cloud",) + pa[1:]))[0], "noise")))
panel_ok("PCG_COPNoiseExtra")
for key in ("metric", "phasor_type", "periodic_function"):
    menu_ok("PCG_COPNoiseExtra", key)

# ═══════════════════════════════════════════════════════ Fractal Sample
from comfyui_pcg.geo.cop import fractalsample as FS     # noqa: E402
sec("Fractal Sample: hand-computed")
FSN = M["PCG_COPFractalSample"]()


def fsr(src, **kw):
    """src (H,W,C) -> result array. kw uses widget names; the rest take defaults."""
    im = CopImage(src.shape[1], src.shape[0])
    PX.put(im, "C", src)
    it = M["PCG_COPFractalSample"].INPUT_TYPES()["required"]
    args = {k: v[1]["default"] if len(v) > 1 and "default" in v[1] else v[0][0]
            for k, v in it.items() if k != "cop"}
    args.update(kw)
    (o,) = FSN.run(im, **args)
    return L(o, "fractal")


src = rng.uniform(0, 1, (16, 16, 3))
src32 = np.asarray(src, np.float32).astype(np.float64)      # put stores float32
check("1 octave, no rotation or jitter: output = source image (both bilinear and point)",
      np.allclose(fsr(src, max_octaves=1), src32, atol=1e-6)
      and np.allclose(fsr(src, max_octaves=1, filter="point"), src32, atol=1e-6))
cst = np.full((8, 8, 1), 0.9)
r2 = dict(max_octaves=2, roughness=0.5)
check("constant 0.9, 2 octaves, Roughness 0.5, Bias 0.5: Add = 0.9",
      np.allclose(fsr(cst, **r2), 0.9, atol=1e-6))
check("Subtract = (0.4 − 0.5·0.4)/1.5 + 0.5 = 0.6333",
      np.allclose(fsr(cst, blend_mode="subtract", **r2), 0.2 / 1.5 + 0.5, atol=1e-6))
check("Maximum = max(0.4, 0.2) + 0.5 = 0.9; with Offset with Bias off = 0.4",
      np.allclose(fsr(cst, blend_mode="maximum", **r2), 0.9, atol=1e-6)
      and np.allclose(fsr(cst, blend_mode="maximum", offset_with_bias=False, **r2), 0.4, atol=1e-6))
check("Add with Offset with Bias off = 0.4", np.allclose(fsr(cst, offset_with_bias=False, **r2), 0.4, atol=1e-6))
check("with Bias 0 Maximum = max(0.9, 0.45) = 0.9; with Bias 0.9 = 0.9 (both terms are 0)",
      np.allclose(fsr(cst, blend_mode="maximum", bias=0.0, **r2), 0.9, atol=1e-6)
      and np.allclose(fsr(cst, blend_mode="maximum", bias=0.9, **r2), 0.9, atol=1e-6))
Wc = 256
uu = (np.arange(Wc) + 0.5) / Wc
cosu = np.broadcast_to(np.cos(2 * np.pi * uu)[None, :, None], (4, Wc, 1)).copy()
got = fsr(cosu, max_octaves=2, roughness=1.0, bias=0.0, offset_with_bias=False)[0, :, 0]
check("the second octave is scaled 2x around the center: (cos 2pi u + cos(2pi(2(u-1/2)+1/2)))/2 = (cos 2pi u - cos 4pi u)/2",
      np.allclose(got, (np.cos(2 * np.pi * uu) - np.cos(4 * np.pi * uu)) / 2, atol=2e-3))
got3 = fsr(cosu, max_octaves=2, lacunarity=3.0, roughness=0.5, bias=0.0,
           offset_with_bias=False)[0, :, 0]
check("Lacunarity 3, Roughness 0.5: (cos 2pi u + 0.5·cos(2pi(3(u-1/2)+1/2)))/1.5",
      np.allclose(got3, (np.cos(2 * np.pi * uu) + 0.5 * np.cos(2 * np.pi * (3 * (uu - 0.5) + 0.5))) / 1.5,
                  atol=2e-3))
sq = rng.uniform(0, 1, (12, 12, 1))
sq32 = np.asarray(sq, np.float32).astype(np.float64)
check("Per Octave, Angle 90, 1 octave: the first octave is already rotated 90 deg (docs: the n-th octave rotates n·Angle) = rot90",
      np.allclose(fsr(sq, max_octaves=1, angle=90.0), np.rot90(sq32), atol=1e-5))
th = [FS.octave_params(o, 30.0, "per_octave", 0, False, False, 0, False)[0] for o in range(3)]
check("Per Octave 30 deg: three octaves 30 / 60 / 90 deg", np.allclose(np.degrees(th), [30, 60, 90]))
thr = [np.degrees(FS.octave_params(o, 30.0, "random", 0, False, False, s_, False)[0])
       for o in range(4) for s_ in range(30)]
check("Random 30 deg: all within [-30, 30], both positive and negative", max(np.abs(thr)) <= 30 and min(thr) < 0 < max(thr))
tht = [np.degrees(FS.octave_params(o, 30.0, "per_octave", 0, False, False, 0, True)[0]) for o in range(3)]
check("Maintain Tileable: angles snapped to multiples of 90 deg (30/60/90 -> 0/90/90)", np.allclose(tht, [0, 90, 90]))
check("Maintain Tileable: Lacunarity 2.4 -> 2, 2.6 -> 3 (rounded, not truncated)",
      np.array_equal(fsr(src, maintain_tileable=True, lacunarity=2.4),
                     fsr(src, maintain_tileable=True, lacunarity=2.0))
      and np.array_equal(fsr(src, maintain_tileable=True, lacunarity=2.6),
                         fsr(src, maintain_tileable=True, lacunarity=3.0))
      and not np.array_equal(fsr(src, lacunarity=2.4), fsr(src, lacunarity=2.0)))
flips = [fsr(sq, max_octaves=1, random_flip_x=True, rand_seed=k) for k in range(12)]
isf = [np.allclose(f_, sq32[:, ::-1], atol=1e-6) for f_ in flips]
iss = [np.allclose(f_, sq32, atol=1e-6) for f_ in flips]
check("Random Flip X: each seed gives either the original or a left-right mirror, both occur",
      all(a or b for a, b in zip(isf, iss)) and any(isf) and any(iss))
flipy = [fsr(sq, max_octaves=1, random_flip_y=True, rand_seed=k) for k in range(12)]
check("Random Flip Y: either the original or a top-bottom mirror, both occur",
      all(np.allclose(f_, sq32, atol=1e-6) or np.allclose(f_, sq32[::-1], atol=1e-6) for f_ in flipy)
      and any(np.allclose(f_, sq32[::-1], atol=1e-6) for f_ in flipy))
both = [fsr(sq, max_octaves=1, random_flip_x=True, random_flip_y=True, rand_seed=k)
        for k in range(16)]
combos = {(bool(np.allclose(f_, sq32[:, ::-1], atol=1e-6) or np.allclose(f_, sq32[::-1, ::-1], atol=1e-6)),
           bool(np.allclose(f_, sq32[::-1], atol=1e-6) or np.allclose(f_, sq32[::-1, ::-1], atol=1e-6)))
          for f_ in both}
check("the X and Y flips each toss their own coin (all four combinations occur over 16 seeds)", len(combos) == 4, combos)
jp = np.array([FS.octave_params(o, 0.0, "per_octave", 0.3, False, False, s_, False)[3:]
               for o in range(4) for s_ in range(30)])
check("Jitter: x and y offsets within [-0.3, 0.3], each with positives and negatives, and not equal",
      np.abs(jp).max() <= 0.3 and (jp.min(0) < 0).all() and (jp.max(0) > 0).all()
      and not np.allclose(jp[:, 0], jp[:, 1]))
rl = []
for k in range(6):
    jk = fsr(sq, max_octaves=1, jitter=0.4, filter="point", rand_seed=k)
    rl += [(a, b) for a in range(12) for b in range(12)
           if np.allclose(np.roll(sq32, (a, b), (0, 1)), jk, atol=1e-6)]
check("Jitter on the node translates in both u and v (some seeds move up/down, some left/right)",
      any(a for a, b in rl) and any(b for a, b in rl), rl)
jt = fsr(sq, max_octaves=1, jitter=0.4, filter="point", rand_seed=3)
rolls = [(a, b) for a in range(12) for b in range(12)
         if np.allclose(np.roll(sq32, (a, b), (0, 1)), jt, atol=1e-6)]
check("Jitter (Wrap + Point): the first octave translates as a whole (= some np.roll), and is not the original",
      len(rolls) == 1 and rolls[0] != (0, 0), rolls)
jb = fsr(sq, max_octaves=1, jitter=0.4, filter="point", rand_seed=3, border="black")
check("Border Black: the part moved outside the image is 0; Clamp has no 0", (jb == 0).any()
      and not (fsr(sq, max_octaves=1, jitter=0.4, filter="point", rand_seed=3, border="clamp") == 0).any())
rgba = np.zeros((6, 6, 4))
rgba[..., :3], rgba[..., 3] = 0.2, 0.5
ov = fsr(rgba, blend_mode="over", max_octaves=2, roughness=1.0)
check("Over (premultiplied RGBA, constants): RGB 0.2 + 0.2·0.5 = 0.3, A 0.5 + 0.5·0.5 = 0.75 (Bias not subtracted)",
      np.allclose(ov[..., :3], 0.3, atol=1e-6) and np.allclose(ov[..., 3], 0.75, atol=1e-6))
ov2 = fsr(rgba, blend_mode="over", max_octaves=2, roughness=0.5)
check("Over multiplies each layer by its weight first: 0.2 + 0.1·0.5 = 0.25", np.allclose(ov2[..., 0], 0.25, atol=1e-6))
check("seed determinism (Random angle + jitter)",
      np.array_equal(fsr(src, angle_mode="random", angle=40.0, jitter=0.2, rand_seed=5),
                     fsr(src, angle_mode="random", angle=40.0, jitter=0.2, rand_seed=5))
      and not np.array_equal(fsr(src, angle_mode="random", angle=40.0, jitter=0.2, rand_seed=5),
                             fsr(src, angle_mode="random", angle=40.0, jitter=0.2, rand_seed=6)))
check("Post: Complement comes last", np.allclose(fsr(src, complement=True), 1 - fsr(src), atol=1e-6))
tsrc = (np.cos(2 * np.pi * (np.arange(64) + 0.5) / 64)[None, :]
        * np.cos(2 * np.pi * (np.arange(64) + 0.5) / 64)[:, None])[..., None] * 0.4 + 0.5
ft_ = fsr(tsrc, maintain_tileable=True, lacunarity=2.6, angle=35.0, angle_mode="random",
          jitter=0.37, rand_seed=2, max_octaves=4)
fn_ = fsr(tsrc, lacunarity=2.6, angle=35.0, angle_mode="random", jitter=0.37, rand_seed=2,
          max_octaves=4)


def seam2(a, ax):
    a = a[..., 0]
    return np.abs(a.take(0, ax) - a.take(-1, ax)).mean() / np.abs(np.diff(a, axis=ax)).mean()


check("Maintain Tileable (Wrap, tileable source): left/right and top/bottom seams as smooth as inside the image",
      seam2(ft_, 1) < 1.6 and seam2(ft_, 0) < 1.6, (seam2(ft_, 1), seam2(ft_, 0)))
check("negative control: without Maintain Tileable the seams are obvious", max(seam2(fn_, 1), seam2(fn_, 0)) > 2.5,
      (seam2(fn_, 1), seam2(fn_, 0)))
try:
    fsr(src, blend_mode="over")
    check("Over on 3 channels raises and states the reason", False)
except ValueError as e:
    check("Over on 3 channels raises and states the reason", "RGBA" in str(e), e)
for bad in (dict(blend_mode="mul"), dict(angle_mode="x"), dict(border="mirror"), dict(filter_="box")):
    try:
        im_ = CopImage(4, 4)
        PX.put(im_, "C", np.zeros((4, 4, 1)))
        FS.fractal_sample(im_, "C", **bad)
        check(f"unknown {bad} raises", False)
    except ValueError:
        check(f"unknown {bad} raises", True)
try:
    FS.fractal_sample(None)
    check("no cop connected raises", False)
except ValueError:
    check("no cop connected raises", True)
panel_ok("PCG_COPFractalSample")
for key in ("blend_mode", "border", "filter", "angle_mode"):
    menu_ok("PCG_COPFractalSample", key)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
