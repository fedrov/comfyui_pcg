"""
pcg100 audit pack c5_heightfield: the HeightField COP family, filled in after checking the SideFX docs.

  HeightField Terrace     PCG_COPTerrace
  HeightField Slump       PCG_COPThermalErosion
  HeightField Strata      PCG_COPStrata
  HeightField Mask by Feature  PCG_COPMaskByFeature
  HeightField Project     PCG_COPHFProject
  HeightField Visualize   PCG_COPVisualize

"Bit-identical to before the change at defaults" uses digests of the same set of calls from before the change (commit 9e3fb92), hard-coded in GOLDEN
(arrays are rounded to 5 decimals before hashing); `--digests` prints the current digests. Independent of git.
"""
import hashlib
import math
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
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def near(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def defaults(n):
    out = {}
    for k, v in M[n].INPUT_TYPES()["required"].items():
        if isinstance(v[0], list):
            out[k] = v[0][0]
        elif len(v) > 1 and isinstance(v[1], dict) and "default" in v[1]:
            out[k] = v[1]["default"]
    return out


_DUMP = {}


def dig(im):
    _DUMP[len(_DUMP)] = {k: np.asarray(im.need(k)).copy() for k in im.names}
    h = hashlib.sha1()
    for k in sorted(im.names):
        a = np.asarray(im.need(k))
        h.update(f"{k}/{a.dtype}/{a.shape}".encode())
        h.update(np.ascontiguousarray(np.round(a.astype(np.float64), 5)
                                      + 0.0).tobytes())
    return h.hexdigest()[:16]


def L(im, k):
    return np.asarray(im.need(k), np.float64)[..., 0]


def terrain(W=48, H=40):
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    u, v = (J + 0.5) / W, (I + 0.5) / H
    h = (0.5 + 0.25 * np.sin(6.1 * u + 1.3) * np.cos(4.7 * v - 0.4)
         + 0.35 * np.exp(-((u - 0.4) ** 2 + (v - 0.6) ** 2) / 0.02)
         - 0.2 * np.exp(-((u - 0.75) ** 2 + (v - 0.3) ** 2) / 0.01))
    m = np.clip(u * 1.3 - 0.1, 0, 1)
    vel = np.stack([np.cos(3 * v), np.sin(4 * u)], -1)
    return CopImage(W, H, {"C": h[..., None].astype(np.float32),
                           "m": m[..., None].astype(np.float32),
                           "vel": vel.astype(np.float32)})


def run(n, img=None, **kw):
    a = defaults(n)
    a.update(kw)
    return M[n]().run(img if img is not None else terrain(), **a)


def box_geo(cx=0.0, cz=0.0, s=0.3, y0=0.0, y1=1.0):
    from comfyui_pcg.geo import build
    return build.box(size=(s, y1 - y0, s), center=(cx, (y0 + y1) / 2, cz),
                     divisions=(2, 2, 2))


# ═══════════════════════════════════════════════════ Regression: identical to before the change at defaults
GOLDEN = {
    "terrace/0": "019dfedac6000889",
    "terrace/1": "c1874a0edd06f881",
    "terrace/2": "5220d65ad183b7f7",
    "thermal/0": "07dfa3f2c1638691",
    "thermal/1": "e798de19d5c72ece",
    "thermal/2": "325c6a45bcea54a8",
    "strata/0": "31ff741d7d9f07ba",
    "strata/1": "a2b5f4db320b901b",
    "mbf/0": "3256d9c4e43ac51a",
    "mbf/1": "3837f0e6700c1b7e",
    "mbf/2": "9536624761b71785",
    "proj/xform": "e1dc35e96dc885d9",
    "proj/max": "3e66196c95c80082",
    "proj/min": "d243da81da98a69a",
    "proj/add": "2ad07f35235f2e5f",
    "proj/replace": "71b8b6e3da913caf",
    "vis/0": "59333a8edac5a0a7",
    "vis/1": "db14609ff14b467e",
    "vis/2": "bf1ac646bae01ac1",
    "vis/3": "a317b419726b3097",
}


def current_digests():
    R = {}
    R["terrace/0"] = dig(run("PCG_COPTerrace")[0])
    R["terrace/1"] = dig(run("PCG_COPTerrace", step=0.07, offset=0.03,
                             sharpness=0.9, mask_layer="m")[0])
    R["terrace/2"] = dig(run("PCG_COPTerrace", sharpness=0.0)[0])
    for i, kw in enumerate([{}, {"neighbours": "4", "tile": True},
                            {"hardness_layer": "m", "talus_angle": 20.0,
                             "rate": 0.9, "strength": 0.5}]):
        k = dict(iterations=15, compute="cpu")
        k.update(kw)
        R[f"thermal/{i}"] = dig(run("PCG_COPThermalErosion", **k)[0])
    R["strata/0"] = dig(run("PCG_COPStrata")[0])
    R["strata/1"] = dig(run("PCG_COPStrata", tilt="0.3 -0.2", noise_amount=0.05,
                            rand_seed=4, hardness_random=0.9)[0])
    R["mbf/0"] = dig(run("PCG_COPMaskByFeature")[0])
    R["mbf/1"] = dig(run("PCG_COPMaskByFeature", use_height=True, height_min=0.4,
                         height_falloff=0.1, use_aspect=True,
                         curvature="ridges", invert=True)[0])
    R["mbf/2"] = dig(run("PCG_COPMaskByFeature", use_slope=False,
                         curvature="gullies", curv_reference=3.0, tile=True)[0])
    R["proj/xform"] = dig(run("PCG_COPHFProject", translate="0.1 0.2 0",
                              rotate="0 30 0", scale="1 1.5 1")[0])
    for md in ["max", "min", "add", "replace"]:
        R[f"proj/{md}"] = dig(run("PCG_COPHFProject", mode=md,
                                  geo=box_geo(0.1, -0.1, 0.4, 0.2, 0.9))[0])
    R["vis/0"] = dig(run("PCG_COPVisualize")[0])
    R["vis/1"] = dig(run("PCG_COPVisualize", ramp="viridis", lo=0.2, hi=0.9,
                         contour_interval=0.1, hillshade=0.0)[0])
    R["vis/2"] = dig(run("PCG_COPVisualize", layer="vel", mode="velocity_hsv")[0])
    R["vis/3"] = dig(run("PCG_COPVisualize", layer="vel", mode="velocity_arrows",
                         arrow_spacing=8, scale=5.0)[0])
    return R


if "--dump" in sys.argv:          # for development: save the full arrays, compare before/after bit by bit
    current_digests()
    np.savez(sys.argv[sys.argv.index("--dump") + 1],
             **{f"{i}/{k}": a for i, d in _DUMP.items() for k, a in d.items()})
    sys.exit(0)

if "--digests" in sys.argv:
    for k, v in current_digests().items():
        print(f'    "{k}": "{v}",')
    sys.exit(0)

sec("Regression: identical to before the change at defaults (hard-coded digests)")
now = current_digests()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})


def row(vals, **extra):
    """A height map one pixel row high (values given one by one), easy to compute by hand."""
    a = np.asarray(vals, np.float64)
    lay = {"C": a[None, :, None].astype(np.float32)}
    for k, v in extra.items():
        lay[k] = np.asarray(v, np.float64)[None, :, None].astype(np.float32)
    return CopImage(a.size, 1, lay)


def terr(vals, extra=None, **kw):
    img = row(vals, **(extra or {}))
    return L(run("PCG_COPTerrace", img, **kw)[0], "C")[0]


# ═══════════════════════════════════════════════════ HeightField Terrace
sec("Terrace:Method = Number of Terraces")
# [0.25, 0.85] in 3 terraces -> step 0.2, boundaries 0.25 / 0.45 / 0.65 / 0.85; sharpness 0.5 -> p = 2
r = terr([0.1, 0.5, 0.7, 0.84, 0.9], method="num_terraces", terraces=3,
         min_height=0.25, max_height=0.85, sharpness=0.5)
check("0.5 → 0.45 + 0.2·0.25² = 0.4625", near(r[1], 0.4625, 1e-6), r[1])
check("0.7 → 0.65 + 0.2·0.25² = 0.6625", near(r[2], 0.6625, 1e-6), r[2])
check("0.1 / 0.9 outside the range unchanged", r[0] == np.float32(0.1) and r[4] == np.float32(0.9), r)
check("0.84 (just below Max) -> 0.65 + 0.2·0.95^2, close to Max",
      near(r[3], 0.65 + 0.2 * 0.95 ** 2, 1e-6), r[3])
r2 = terr([0.5], method="step_size", step=0.2, sharpness=0.5)
check("negative control: Step Size (unbounded, boundaries 0 / 0.2 / 0.4 ...) 0.5 -> 0.45", near(r2[0], 0.45, 1e-6), r2)
r3 = terr([0.5], method="num_terraces", terraces=2, min_height=0.25,
          max_height=0.85, sharpness=0.5)
check("negative control: Terraces = 2 (step 0.3) 0.5 -> 0.25 + 0.3·(0.25/0.3)^2",
      near(r3[0], 0.25 + 0.3 * (0.25 / 0.3) ** 2, 1e-6), r3)
r4 = terr([0.52], method="num_terraces", terraces=3, min_height=0.25,
          max_height=0.85, sharpness=0.5, offset=0.1)
check("Offset shifts on top of Min: boundaries 0.35 / 0.55 -> 0.52 -> 0.35 + 0.2·0.85^2",
      near(r4[0], 0.35 + 0.2 * 0.85 ** 2, 1e-6), r4)
r4 = terr([0.25, 0.85], step=0.2, limit_range=True, min_height=0.25,
          max_height=0.85, sharpness=0.5, offset=0.1)
check("range endpoints are included: with Offset 0.1, 0.25 -> 0.15 + 0.2·0.5^2 = 0.2, 0.85 -> 0.75 + 0.2·0.5^2 = 0.8",
      near(r4[0], 0.2, 1e-6) and near(r4[1], 0.8, 1e-6), r4)
r5 = terr([0.5], method="num_terraces", terraces=3, min_height=0.25,
          max_height=0.85, sharpness=0.5, step=0.05)
check("Number of Terraces does not read Step", near(r5[0], 0.4625, 1e-6), r5)
try:
    terr([0.5], method="num_terraces", min_height=0.5, max_height=0.5)
    check("Max <= Min raises", False)
except ValueError as e:
    check("Max <= Min raises", "Max Height" in str(e), e)

sec("Terrace: Limit Range (also only within [Min, Max] under Step Size)")
r = terr([0.1, 0.5, 0.9], step=0.2, sharpness=0.5, limit_range=True,
         min_height=0.25, max_height=0.85)
check("the first boundary in the range is at Min: 0.5 -> 0.4625", near(r[1], 0.4625, 1e-6), r)
check("outside the range unchanged", r[0] == np.float32(0.1) and r[2] == np.float32(0.9), r)
r = terr([0.1, 0.5, 0.9], step=0.2, sharpness=0.5, limit_range=False,
         min_height=0.25, max_height=0.85)
check("negative control: turned off -> 0.1 -> 0.2·0.5^2 = 0.05, 0.9 -> 0.8 + 0.2·0.5^2 = 0.85 are both changed",
      near(r[0], 0.05, 1e-6) and near(r[2], 0.85, 1e-6), r)
r = terr([0.25, 0.85], step=0.2, sharpness=0.5, limit_range=True,
         min_height=0.25, max_height=0.85)
check("range includes both endpoints (values on the boundary unchanged)", near(r[0], 0.25, 1e-7) and near(r[1], 0.85, 1e-6), r)
r = terr([0.3], step=0.2, sharpness=0.5, limit_range=True,
         min_height=0.25, max_height=0.85, offset=0.0)
check("with Offset 0 the first terrace in the range starts at Min: 0.3 -> 0.25 + 0.2·0.25^2 = 0.2625",
      near(r[0], 0.2625, 1e-6), r)

sec("Terrace:Random Step")
ramp_ = np.linspace(-0.3, 1.3, 1601)
a = terr(ramp_, step=0.1, sharpness=0.8, random_step=0.8, rand_seed=3)
b = terr(ramp_, step=0.1, sharpness=0.8)
check("monotonically non-decreasing", bool(np.all(np.diff(a) >= -1e-7)))
check("only cuts, never fills (<= input)", bool(np.all(a <= ramp_.astype(np.float32) + 1e-7)))
check("negative control: differs from Random Step 0", float(np.abs(a - b).max()) > 1e-3)
c = terr(ramp_, step=0.1, sharpness=0.8, random_step=0.8, rand_seed=4)
check("a different seed gives a different result", float(np.abs(a - c).max()) > 1e-3)
d = terr(ramp_, step=0.1, sharpness=0.8, random_step=0.0, rand_seed=4)
check("with Random Step 0 the seed has no effect (bit-identical to the old behaviour)", np.array_equal(b, d))
# hand-computed: boundary b_k = 0.1·(k + 0.8·(r_k - 1/2)); check the f^p formula at each terrace's midpoint
from comfyui_pcg.geo.cop.pattern import rnd       # noqa: E402
ks = np.arange(-5, 16)
bk = 0.1 * (ks + 0.8 * (rnd(ks, 3, 1) - 0.5))
p_ = 1.0 / (1.0 - 0.8)
mid = (bk[:-1] + bk[1:]) / 2
want = bk[:-1] + (bk[1:] - bk[:-1]) * 0.5 ** p_
got = terr(mid[4:16], step=0.1, sharpness=0.8, random_step=0.8, rand_seed=3)
check("each terrace midpoint -> b_k + (b_{k+1} - b_k)·0.5^p (hand-computed boundaries)",
      float(np.abs(got - want[4:16]).max()) < 2e-6, float(np.abs(got - want[4:16]).max()))
check("boundaries really moved (not evenly spaced)", float(np.ptp(np.diff(bk))) > 0.01)
e = terr([0.25, 0.8499], method="num_terraces", terraces=3, min_height=0.25,
         max_height=0.85, sharpness=0.5, random_step=1.0, rand_seed=9)
check("Number of Terraces: the Min / Max boundaries are pinned (0.25 unchanged, just below Max is close to Max)",
      near(e[0], 0.25, 1e-7) and e[1] > 0.845, e)
e2 = terr([0.7], method="num_terraces", terraces=3, min_height=0.25,
          max_height=0.85, sharpness=0.5, random_step=1.0, rand_seed=9)
e3 = terr([0.7], method="num_terraces", terraces=3, min_height=0.25,
          max_height=0.85, sharpness=0.5, random_step=0.0)
check("under Number of Terraces the middle boundaries still move", abs(float(e2[0] - e3[0])) > 1e-4, (e2, e3))

# brute-force reference: build boundaries over a very wide k range and find each value's terrace one by one -- pins down whether _jittered_terrace taking only
# the boundaries in [floor(min t) - 1, floor(max t) + 2] is enough
from comfyui_pcg.geo.cop import terrain as TR      # noqa: E402
bad = 0
rng = np.random.default_rng(1)
for sd in range(40):
    hv = float(rng.uniform(-1, 2))
    kk = np.arange(-40, 41)
    bb = 0.13 * (kk + 1.0 * (rnd(kk, sd, 1) - 0.5)) + 0.02
    i = np.searchsorted(bb, hv, side="right") - 1
    ref = bb[i] + (bb[i + 1] - bb[i]) * ((hv - bb[i]) / (bb[i + 1] - bb[i])) ** 3
    got = TR._jittered_terrace(np.array([hv]), 0.02, 0.13, 3.0, 1.0, sd, None)[0]
    bad += abs(got - ref) > 1e-12
check("single-pixel image (min t = max t): 40 seeds x Random Step 1 all match the brute-force reference", bad == 0, bad)
z = terr(ramp_, step=0.1, sharpness=0.0, random_step=0.7, rand_seed=3)
check("Sharpness 0 + Random Step > 0 is still bit-identical", np.array_equal(z, ramp_.astype(np.float32)))
try:
    TR.terrace(row([0.5]), random_step=1.5)
    check("Random Step > 1 raises", False)
except ValueError as e:
    check("Random Step > 1 raises", "Random Step" in str(e), e)

sec("Terrace:Mask")
r = terr([0.5], step=0.2, sharpness=0.5, mask=0.5)
check("Mask 0.5, no Mask Layer: 0.5 + 0.5·(0.45 - 0.5) = 0.475", near(r[0], 0.475, 1e-6), r)
r = terr([0.5, 0.5], {"mm": [0.4, 1.0]}, step=0.2, sharpness=0.5, mask=0.5,
         mask_layer="mm")
check("Mask multiplies the Mask Layer: weights 0.2 / 0.5",
      near(r[0], 0.5 - 0.2 * 0.05, 1e-6) and near(r[1], 0.475, 1e-6), r)
r = terr([0.5], step=0.2, sharpness=0.5, mask=0.0)
check("Mask 0 = unchanged", near(r[0], 0.5, 1e-7), r)

sec("Terrace: panel")
check("check_layout is empty", PANEL.check_layout("PCG_COPTerrace",
                                              M["PCG_COPTerrace"].INPUT_TYPES()) == [])


def _finish():
    print(f"\n{sum(OK)}/{len(OK)} passed")
    sys.exit(0 if all(OK) else 1)


# ═══════════════════════════════════════════════════ HeightField Slump
def slump(vals, extra=None, **kw):
    img = row(vals, **(extra or {}))
    k = dict(compute="cpu", world_size=float(len(vals)), neighbours="4",
             talus_angle=45.0, rate=1.0, iterations=1)
    k.update(kw)
    return run("PCG_COPThermalErosion", img, **k)[0]


sec("Slump: Debris Source = layer (bedrock stays, only debris slides)")
# one row of 3 pixels, pixel spacing 1, angle of repose 45 deg (tan = 1), Rate 1: excess e = 3 - 0 - 1 = 2,
# move rate·max(e)/2 = 1, 0.5 to each side
o = slump([0, 0, 0], {"d": [0, 3, 0]}, debris_source="layer", debris_input="d")
check("flat bedrock + a debris column 3 thick: debris -> [0.5, 2, 0.5]",
      np.allclose(L(o, "debris")[0], [0.5, 2, 0.5], atol=1e-6), L(o, "debris")[0])
check("output height = bedrock + debris", np.allclose(L(o, "C")[0], [0.5, 2, 0.5], atol=1e-6))
o = slump([0, 2.5, 0], {"d": [0, 0.5, 0]}, debris_source="layer", debris_input="d")
check("bedrock column 2.5 + debris 0.5: wants to move 1 but only 0.5 available -> debris [0.25, 0, 0.25]",
      np.allclose(L(o, "debris")[0], [0.25, 0, 0.25], atol=1e-6), L(o, "debris")[0])
check("... output height [0.25, 2.5, 0.25] (bedrock not cut)",
      np.allclose(L(o, "C")[0], [0.25, 2.5, 0.25], atol=1e-6), L(o, "C")[0])
o2 = slump([0, 3, 0])
check("negative control: height mode on the same surface [0,3,0] -> [0.5, 2, 0.5] (the whole column collapses)",
      np.allclose(L(o2, "C")[0], [0.5, 2, 0.5], atol=1e-6), L(o2, "C")[0])
check("... in height mode the debris layer is the net deposition [0.5, 0, 0.5]",
      np.allclose(L(o2, "debris")[0], [0.5, 0, 0.5], atol=1e-6), L(o2, "debris")[0])
o = slump([0, 3, 0], {"d": [0, 0, 0]}, debris_source="layer", debris_input="d",
          iterations=20)
check("without debris a steep cliff does not move at all (bit-identical)", np.array_equal(L(o, "C"), L(row([0, 3, 0]), "C")))
o = slump([0, 0, 0], {"d": [0, 3, 0]}, debris_source="layer", debris_input="d",
          debris_scale=2.0)
check("Debris Scale 2: debris column 6, e = 5, move 2.5 -> [1.25, 3.5, 1.25]",
      np.allclose(L(o, "debris")[0], [1.25, 3.5, 1.25], atol=1e-6), L(o, "debris")[0])
o = slump([0, 0, 0], {"d": [0, -1, 0]}, debris_source="layer", debris_input="d")
check("negative debris treated as 0", np.allclose(L(o, "debris")[0], 0, atol=0) and
      np.allclose(L(o, "C")[0], 0, atol=0))
o = slump([0, 0, 0], {"d": [0, 3, 0]}, debris_source="layer", debris_input="d",
          strength=2.0)
# Strength 2: debris world thickness 6, e = 5, move 2.5 -> world [1.25, 3.5, 1.25], divided back by strength
check("Strength conversion: debris goes in as height value x Strength, comes out / Strength",
      np.allclose(L(o, "debris")[0], [0.625, 1.75, 0.625], atol=1e-6), L(o, "debris")[0])

big = terrain(40, 32)
dl = np.clip(np.asarray(big.need("m"))[..., 0] - 0.3, 0, None) * 0.4
bimg = big.copy()
bimg.set("dd", dl[..., None].astype(np.float32))
o = run("PCG_COPThermalErosion", bimg, compute="cpu", iterations=40, rate=0.8,
        talus_angle=30.0, debris_source="layer", debris_input="dd")[0]
dout = L(o, "debris")
check("total debris conserved (40 steps)", near(dout.sum(), dl.sum(), 1e-3 * max(1, dl.sum())),
      (dout.sum(), dl.sum()))
check("debris >= 0 everywhere", float(dout.min()) >= -1e-7, dout.min())
base_ = L(big, "C")
check("output - debris = bedrock (not cut)", np.allclose(L(o, "C") - dout, base_, atol=2e-6))
o = run("PCG_COPThermalErosion", bimg, compute="cpu", iterations=40, rate=0.8,
        talus_angle=30.0, debris_source="layer", debris_input="dd",
        add_debris=False)[0]
check("Add Debris off: output height = input height (bit-identical)", np.array_equal(L(o, "C"), base_))

sec("Slump:Debris Source = constant / Remove Debris")
o = slump([0, 2, 4], debris_source="constant", debris_scale=0.5, iterations=1)
# surface [0.5, 2.5, 4.5]: p0 has no outward neighbour; p1 -> p0 e = 2-1 = 1; p2 -> p1 e = 1
# p2: mx 1 -> wants to move 0.5, has 0.5, all to p1; p1: mx 1 -> moves 0.5 to p0
check("constant debris 0.5 on stepped bedrock [0,2,4], one step -> debris [1, 0.5, 0]",
      np.allclose(L(o, "debris")[0], [1.0, 0.5, 0.0], atol=1e-6), L(o, "debris")[0])
check("... total 1.5 conserved", near(L(o, "debris").sum(), 1.5, 1e-6))
o = slump([0.5, 0.5, 0.5], debris_source="constant", debris_scale=0.5,
          remove_debris=True, iterations=5)
check("Remove Debris: flat input 0.5 containing 0.5 debris -> bedrock 0, output still 0.5",
      np.allclose(L(o, "C")[0], 0.5, atol=1e-7), L(o, "C")[0])
o = slump([0.5, 0.5, 0.5], debris_source="constant", debris_scale=0.5,
          remove_debris=False, iterations=5)
check("negative control: without Remove -> output 1.0 (debris stacked on top)",
      np.allclose(L(o, "C")[0], 1.0, atol=1e-7), L(o, "C")[0])
o = slump([0.5, 0.5, 0.5], debris_source="constant", debris_scale=0.5,
          remove_debris=True, add_debris=False)
check("Remove + no Add: output is only bedrock 0", np.allclose(L(o, "C")[0], 0.0, atol=1e-7))
o = slump([0, 2, 4], debris_source="constant", debris_scale=0.5, strength=2.0)
# Strength 2: bedrock world [0,4,8], debris world 1; p2 -> p1 e = 4 - 1 = 3, wants to move 1.5 but has only 1;
# p1 also has only 1, all to p0 (while receiving p2's 1) -> world debris [2, 1, 0], / 2
check("Constant mode thickness is also converted by Strength -> debris [1, 0.5, 0]",
      np.allclose(L(o, "debris")[0], [1.0, 0.5, 0.0], atol=1e-6), L(o, "debris")[0])
try:
    slump([0, 1, 0], debris_source="bogus")
    check("unknown Debris Source raises", False)
except ValueError as e:
    check("unknown Debris Source raises", "Debris Source" in str(e), e)
try:
    slump([0, 1, 0], debris_source="layer", debris_input=" ")
    check("layer mode without a layer name raises", False)
except ValueError as e:
    check("layer mode without a layer name raises", "Debris Input" in str(e), e)

sec("Slump:Slump Mode = granular")
from comfyui_pcg.geo.cop.pattern import rnd as _rnd   # noqa: E402
o = slump([0, 3, 0], slump_mode="granular", rand_seed=7)
xi = _rnd(np.arange(3), 7, 2)
check("one step by hand: the middle moves 1·xi (xi = rnd(pixel 1, seed, 2)), xi/2 to each side",
      np.allclose(L(o, "C")[0], [0.5 * xi[1], 3 - xi[1], 0.5 * xi[1]], atol=1e-6),
      (L(o, "C")[0], xi[1]))
o2 = slump([0, 3, 0], slump_mode="granular", rand_seed=7, iterations=2)
xi2 = _rnd(np.arange(3, 6), 7, 2)
# second step: middle c = 3 - xi1, sides a = xi1/2; the middle exceeds toward each side by c - a - 1 (if > 0)
c1, a1 = 3 - xi[1], 0.5 * xi[1]
e = max(c1 - a1 - 1, 0)
mv = e * 0.5 * xi2[1]
# the sides could also move outward / toward the middle: they are lower than the middle and have no outward neighbours, so they stay
check("the second step uses a new set of random numbers (step count is hashed): the middle moves another e·xi2/2",
      np.allclose(L(o2, "C")[0], [a1 + mv / 2, c1 - mv, a1 + mv / 2], atol=1e-6),
      L(o2, "C")[0])
gs = run("PCG_COPThermalErosion", big, compute="cpu", iterations=30, rate=0.8,
         talus_angle=25.0, slump_mode="granular", rand_seed=1)[0]
sm = run("PCG_COPThermalErosion", big, compute="cpu", iterations=30, rate=0.8,
         talus_angle=25.0)[0]
g2 = run("PCG_COPThermalErosion", big, compute="cpu", iterations=30, rate=0.8,
         talus_angle=25.0, slump_mode="granular", rand_seed=2)[0]
check("granular conserves mass", near(L(gs, "C").sum(), L(big, "C").sum(), 2e-3))
check("negative control: granular != smooth", float(np.abs(L(gs, "C") - L(sm, "C")).max()) > 1e-4)
check("a different seed gives a different result", float(np.abs(L(gs, "C") - L(g2, "C")).max()) > 1e-4)
s1 = run("PCG_COPThermalErosion", big, compute="cpu", iterations=30, rate=0.8,
         talus_angle=25.0, rand_seed=5)[0]
check("smooth mode does not read the seed (bit-identical)", np.array_equal(L(s1, "C"), L(sm, "C")))

sec("Slump: panel")
check("check_layout is empty", PANEL.check_layout(
    "PCG_COPThermalErosion", M["PCG_COPThermalErosion"].INPUT_TYPES()) == [])


# ═══════════════════════════════════════════════════ HeightField Project
def flat(v=0.3, n=20, **extra):
    lay = {"C": np.full((n, n, 1), v, np.float32)}
    for k, a in extra.items():
        lay[k] = np.asarray(a, np.float32)[..., None]
    return CopImage(n, n, lay)


def proj(img=None, **kw):
    k = dict(world_size=1.0)
    k.update(kw)
    o, rep = run("PCG_COPHFProject", img if img is not None else flat(), **k)
    return o


# 20^2 image, World Size 1 -> texel 0.05; a 0.4-wide box covers x, z in (-0.2, 0.2) -> 8 x 8 = 64 texels
IN = np.zeros((20, 20), bool)
IN[6:14, 6:14] = True
BOX = box_geo(0, 0, 0.4, 0.2, 0.9)

sec("Project:Project = Maximum / Minimum Height")
o = proj(geo=BOX, mode="blend", hitmask_layer="hit")
c = L(o, "C")
check("Maximum Height: box top 0.9 projected onto 64 texels", np.allclose(c[IN], 0.9, atol=1e-5) and
      np.allclose(c[~IN], 0.3, atol=1e-7), (c[IN].min(), c[IN].max()))
check("hitmask: exactly those 64 texels are 1, the rest 0", np.array_equal(L(o, "hit") > 0.5, IN)
      and set(np.unique(L(o, "hit"))) == {0.0, 1.0})
o = proj(geo=BOX, mode="blend", project="minimum")
check("negative control: Minimum Height -> box bottom 0.2", np.allclose(L(o, "C")[IN], 0.2, atol=1e-5),
      L(o, "C")[IN][:3])
o = proj(geo=BOX, mode="min", project="minimum")
check("Minimum Height + Blend Mode Minimum (making a valley) -> min(0.3, 0.2) = 0.2",
      np.allclose(L(o, "C")[IN], 0.2, atol=1e-5))
check("no hitmask layer by default", "hitmask" not in proj(geo=BOX).names and
      sorted(proj(geo=BOX).names) == sorted(flat().names))

sec("Project:Max Projection Height")
o = proj(geo=BOX, mode="blend", max_height=0.5)
check("height limit 0.5: box top 0.9 is outside and not projected, hits box bottom 0.2", np.allclose(L(o, "C")[IN], 0.2, atol=1e-5),
      L(o, "C")[IN][:3])
o = proj(geo=box_geo(0, 0, 0.4, 0.6, 0.9), mode="blend", max_height=0.5,
         hitmask_layer="hit")
check("whole box above the height limit -> nothing hit", float(L(o, "hit").sum()) == 0 and
      np.allclose(L(o, "C"), 0.3))
low = box_geo(0, 0, 0.4, -0.9, -0.6)
o = proj(geo=low, mode="blend", max_height=0.5, hitmask_layer="hit")
check("whole box below -limit -> cannot be hit", float(L(o, "hit").sum()) == 0)
o = proj(geo=low, mode="blend", max_height=1.0)
check("negative control: limit 1 -> hits box top -0.6", np.allclose(L(o, "C")[IN], -0.6, atol=1e-5))
o = proj(geo=low, mode="blend", max_height=0.0)
check("limit 0 = unlimited -> -0.6", np.allclose(L(o, "C")[IN], -0.6, atol=1e-5))
o = proj(geo=BOX, mode="blend", max_height=0.3, strength=2.0)
check("the limit is in height values: Strength 2, limit 0.3 = world 0.6 -> box top 0.9 not projected, box bottom 0.2/2 = 0.1",
      np.allclose(L(o, "C")[IN], 0.1, atol=1e-5), L(o, "C")[IN][:3])
o = proj(geo=BOX, mode="blend", max_height=0.5, strength=2.0)
check("negative control: Strength 2, limit 0.5 = world 1.0 -> box top 0.9 is inside -> 0.45",
      np.allclose(L(o, "C")[IN], 0.45, atol=1e-5), L(o, "C")[IN][:3])
try:
    proj(geo=BOX, project="middle")
    check("unknown Project raises", False)
except ValueError as e:
    check("unknown Project raises", "Project" in str(e), e)
o = proj(geo=BOX, mode="blend", max_height=0.5, project="minimum")
check("limit + Minimum: the lowest below 0.5 is still box bottom 0.2", np.allclose(L(o, "C")[IN], 0.2, atol=1e-5))
try:
    proj(geo=BOX, max_height=-1.0)
    check("negative limit raises", False)
except ValueError as e:
    check("negative limit raises", "Max Projection Height" in str(e), e)

sec("Project: Blend / Multiply added to Blend Mode")
o = proj(geo=BOX, mode="blend", fill_value=-1.0)
r_ = proj(geo=BOX, mode="replace", fill_value=-1.0)
check("Blend: unhit areas keep the original height 0.3", np.allclose(L(o, "C")[~IN], 0.3))
check("negative control: Replace fills unhit areas with Fill Value -1", np.allclose(L(r_, "C")[~IN], -1.0))
o = proj(geo=BOX, mode="multiply")
check("Multiply: 0.3 x 0.9 = 0.27, unhit unchanged",
      np.allclose(L(o, "C")[IN], 0.27, atol=1e-5) and np.allclose(L(o, "C")[~IN], 0.3))

sec("Project:Mask / Output Projection Only")
o = proj(geo=BOX, mode="max", mask=0.5)
check("Mask 0.5:0.3 + 0.5·(0.9 − 0.3) = 0.6", np.allclose(L(o, "C")[IN], 0.6, atol=1e-5))
mm = np.zeros((20, 20))
mm[:, 10:] = 1.0
o = proj(flat(mm=mm), geo=BOX, mode="max", mask=0.5, mask_layer="mm")
cc = L(o, "C")
check("Mask multiplies the Mask Layer: left half 0 -> 0.3, right half 0.5 -> 0.6",
      np.allclose(cc[6:14, 6:10], 0.3) and np.allclose(cc[6:14, 10:14], 0.6, atol=1e-5))
o = proj(flat(mm=mm), geo=BOX, mode="max", mask=1.0, mask_layer="mm")
cc = L(o, "C")
check("Mask 1 + Mask Layer: left half 0.3, right half 0.9",
      np.allclose(cc[6:14, 6:10], 0.3) and np.allclose(cc[6:14, 10:14], 0.9, atol=1e-5))
o = proj(geo=BOX, mode="max", mask=0.0)
check("Mask 0 = unchanged", np.allclose(L(o, "C"), 0.3, atol=0))
o = proj(geo=BOX, mode="add", projection_only=True, fill_value=-2.0, mask=0.0)
check("Output Projection Only: 0.9 where hit (not composited by Add, no Mask), Fill Value where not hit",
      np.allclose(L(o, "C")[IN], 0.9, atol=1e-5) and np.allclose(L(o, "C")[~IN], -2.0))
x0 = proj(translate="0 0.1 0")
x1 = proj(translate="0 0.1 0", mask=0.0)
check("without geo connected (Transform 3D) Mask still works: Mask 0 = unchanged",
      np.allclose(L(x1, "C"), 0.3) and not np.allclose(L(x0, "C"), 0.3))
check("Mode menu: the old four items keep their order, new ones at the end",
      M["PCG_COPHFProject"].INPUT_TYPES()["required"]["mode"][0]
      == ["max", "min", "add", "replace", "blend", "multiply"])

sec("Project: panel")
check("check_layout is empty", PANEL.check_layout(
    "PCG_COPHFProject", M["PCG_COPHFProject"].INPUT_TYPES()) == [])


# ═══════════════════════════════════════════════════ HeightField Mask by Feature
def mbf(img=None, **kw):
    return L(run("PCG_COPMaskByFeature", img, **kw)[0], "mask")


FH = dict(use_height=True, height_min=0.45, height_max=0.7, height_falloff=0.2)
FS = dict(use_slope=True, slope_min=30.0, slope_max=90.0, slope_falloff=20.0)
FC = dict(curvature="ridges", curv_falloff=1.0)
mh = mbf(**FH, use_slope=False)
ms = mbf(**FS)
mc = mbf(**FC, use_slope=False)

sec("Mask by Feature: Blend Mode (reference: masks from running each criterion alone)")
check("reference masks all have fractional values (soft edges in effect)",
      all(((x > 0.01) & (x < 0.99)).sum() > 20 for x in (mh, ms, mc)))
both = dict(**FH, **FS)
check("Multiply = product of the two (old behaviour)", np.allclose(mbf(**both), mh * ms, atol=1e-6))
check("Add = sum (not clamped, can be > 1)", np.allclose(mbf(**both, blend_mode="add"), mh + ms, atol=1e-6)
      and float(mbf(**both, blend_mode="add").max()) > 1.0)
check("Average = mean", np.allclose(mbf(**both, blend_mode="average"), (mh + ms) / 2, atol=1e-6))
check("Minimum", np.allclose(mbf(**both, blend_mode="minimum"), np.minimum(mh, ms), atol=1e-6))
check("Maximum", np.allclose(mbf(**both, blend_mode="maximum"), np.maximum(mh, ms), atol=1e-6))
three = dict(**FH, **FS, **FC)
check("three criteria Average divides by 3", np.allclose(mbf(**three, blend_mode="average"),
                                       (mh + ms + mc) / 3, atol=1e-6))
check("three criteria Minimum / Maximum",
      np.allclose(mbf(**three, blend_mode="minimum"), np.minimum(np.minimum(mh, ms), mc), atol=1e-6)
      and np.allclose(mbf(**three, blend_mode="maximum"), np.maximum(np.maximum(mh, ms), mc), atol=1e-6))
check("Add + Invert = 1 - sum", np.allclose(mbf(**both, blend_mode="add", invert=True),
                                         1 - (mh + ms), atol=1e-6))
check("no criterion enabled: every Blend Mode gives all 1",
      all(np.all(mbf(use_slope=False, blend_mode=b) == 1.0)
          for b in ("multiply", "add", "average", "minimum", "maximum")))
check("with only one criterion enabled every mode equals it",
      all(np.allclose(mbf(**FS, blend_mode=b), ms, atol=1e-7)
          for b in ("add", "average", "minimum", "maximum")))

sec("Mask by Feature:Smooth Radius")
n_ = 41
spike = np.zeros((n_, n_))
spike[20, 20] = 1.0
simg = CopImage(n_, n_, {"C": spike[..., None].astype(np.float32)})
# height band [10, inf), falloff 10 -> mask = smoothstep(h / 10); invert it to recover the blurred height
kw = dict(use_slope=False, use_height=True, height_min=10.0, height_max=1e6,
          height_falloff=10.0, world_size=float(n_))
R_ = 3.0            # world units = 3 pixels -> sigma = 1
m0 = mbf(simg, **kw, smooth_radius=R_)


def inv_ss(m):
    lo, hi = np.zeros_like(m), np.ones_like(m)
    for _ in range(60):
        mid = (lo + hi) / 2
        f = mid * mid * (3 - 2 * mid)
        lo, hi = np.where(f < m, mid, lo), np.where(f < m, hi, mid)
    return (lo + hi) / 2 * 10.0


t_ = np.arange(-3, 4, dtype=np.float64)
k1 = np.exp(-0.5 * t_ ** 2)
k1 /= k1.sum()
got = inv_ss(m0.astype(np.float64))
check("a single height-1 point after blurring: center = k0^2 (sigma = radius / 3 = 1 pixel, kernel cut at 3 sigma)",
      near(got[20, 20], k1[3] ** 2, 2e-5), (got[20, 20], k1[3] ** 2))
check("... one cell over = k0·k1", near(got[20, 21], k1[3] * k1[4], 2e-5), (got[20, 21], k1[3] * k1[4]))
check("... kernel reaches only 3 pixels (the 4th cell is 0)", near(got[20, 24], 0.0, 1e-6))
kw2 = dict(kw, world_size=2.0 * n_)
g2_ = inv_ss(mbf(simg, **kw2, smooth_radius=2 * R_).astype(np.float64))
check("radius in world units: double World Size and radius -> same sigma = 1 pixel",
      near(g2_[20, 20], k1[3] ** 2, 2e-5), g2_[20, 20])
edge = np.zeros((n_, n_))
edge[20, 0] = 1.0
eimg = CopImage(n_, n_, {"C": edge[..., None].astype(np.float32)})
ge = inv_ss(mbf(eimg, **kw, smooth_radius=R_, tile=True).astype(np.float64))
gc = inv_ss(mbf(eimg, **kw, smooth_radius=R_, tile=False).astype(np.float64))
check("Tileable: blur wraps around to the opposite edge (rightmost column = k0·k1)", near(ge[20, n_ - 1], k1[3] * k1[4], 2e-5),
      ge[20, n_ - 1])
check("negative control: without tiling the opposite edge is 0", near(gc[20, n_ - 1], 0.0, 1e-6))
m1 = mbf(simg, **kw)
check("negative control: Smooth Radius 0 -> center is still 1 (mask smoothstep(0.1))",
      near(inv_ss(m1.astype(np.float64))[20, 20], 1.0, 1e-4))
plane = CopImage(40, 30, {"C": np.tile(np.linspace(0, 1, 40), (30, 1))[..., None]
                          .astype(np.float32)})
a_ = mbf(plane, **FS, world_size=2.0)
b_ = mbf(plane, **FS, world_size=2.0, smooth_radius=0.15)
check("blurring the interior of a sloped plane does not change the slope (mask unchanged), clamp at the edges does change it",
      np.allclose(a_[:, 6:-6], b_[:, 6:-6], atol=1e-5))
try:
    mbf(smooth_radius=-1.0)
    check("negative Smooth Radius raises", False)
except ValueError as e:
    check("negative Smooth Radius raises", "Smooth Radius" in str(e), e)

sec("Mask by Feature:Mask by Occlusion")
from comfyui_pcg.geo.cop.heightmap import height_to_ao       # noqa: E402
tim = terrain()
ref = 1.0 - L(height_to_ao(tim, "C", 2.0 * 1.5, 1.0, 0.1 * 48, 6, 5, 1.0, False,
                           "ao"), "ao")
mo = mbf(tim, use_slope=False, use_occlusion=True, occ_min=0.05, occ_max=0.6,
         strength=1.5, occ_height_scale=2.0, occ_radius=0.1, occ_step_scale=1.0,
         occ_samples=6)
check("reference: occlusion = 1 - Height to AO (radius 4.8 pixels, 6 directions, 5 steps, height x 1.5 x 2) varies",
      float(ref.max()) > 0.1 and float(ref.min()) < 0.05, (ref.min(), ref.max()))
check("hard range: mask = [0.05 <= occlusion <= 0.6]",
      np.array_equal(mo > 0.5, (ref >= 0.05) & (ref <= 0.6)) and set(np.unique(mo)) <= {0.0, 1.0},
      int(((mo > 0.5) != ((ref >= 0.05) & (ref <= 0.6))).sum()))
ref2 = 1.0 - L(height_to_ao(tim, "C", 1.5, 1.0, 0.1 * 48, 6, 3, 1.0, False, "ao"), "ao")
mo2 = mbf(tim, use_slope=False, use_occlusion=True, occ_min=0.05, occ_max=0.6,
          strength=1.5, occ_height_scale=1.0, occ_radius=0.1, occ_step_scale=2.0,
          occ_samples=6)
check("Step Scale 2 -> steps ceil(4.8 / 2) = 3; Height Scale 1",
      np.array_equal(mo2 > 0.5, (ref2 >= 0.05) & (ref2 <= 0.6)))
check("negative control: a different Height Scale gives a different mask", not np.array_equal(mo, mo2))
ref3 = 1.0 - L(height_to_ao(tim, "C", 1.5, 1.0, 0.1 * 48, 6, 5, 1.0, True, "ao"), "ao")
mo4 = mbf(tim, use_slope=False, use_occlusion=True, occ_min=0.05, occ_max=0.6,
          strength=1.5, occ_height_scale=1.0, occ_samples=6, tile=True)
check("Tileable passed to the occlusion computation", np.array_equal(mo4 > 0.5, (ref3 >= 0.05) & (ref3 <= 0.6))
      and not np.array_equal(ref3, ref2))
mo3 = mbf(tim, use_slope=False, use_occlusion=True, occ_min=0.05, occ_max=0.6,
          occ_falloff=0.05, strength=1.5, occ_height_scale=2.0, occ_samples=6)
check("Occlusion Falloff gives soft edges", ((mo3 > 0.01) & (mo3 < 0.99)).sum() > 5)
check("flat ground: occlusion 0 -> no pixels within [0.2, 1]", np.all(mbf(flat(), use_slope=False,
                                                       use_occlusion=True) == 0.0))
check("enabled together with Slope (Multiply) = product of the two",
      np.allclose(mbf(tim, **FS, use_occlusion=True, occ_min=0.05, occ_max=0.6,
                      strength=1.5, occ_height_scale=2.0, occ_samples=6),
                  mbf(tim, **FS, strength=1.5) * mo, atol=1e-6))
for bad in (dict(occ_radius=0.0), dict(occ_step_scale=0.0)):
    try:
        mbf(use_occlusion=True, **bad)
        check(f"{bad} raises", False)
    except ValueError as e:
        check(f"{bad} raises", True, e)
try:
    mbf(blend_mode="screen")
    check("unknown Blend Mode raises", False)
except ValueError as e:
    check("unknown Blend Mode raises", "Blend Mode" in str(e), e)

sec("Mask by Feature: panel")
check("check_layout is empty", PANEL.check_layout(
    "PCG_COPMaskByFeature", M["PCG_COPMaskByFeature"].INPUT_TYPES()) == [])


# ═══════════════════════════════════════════════════ HeightField Visualize
def vis(img=None, **kw):
    k = dict(ramp="gray", hillshade=0.0)
    k.update(kw)
    return np.asarray(run("PCG_COPVisualize", img, **k)[0].need("vis"), np.float64)


TI = terrain()
hh = L(TI, "C")
sec("Visualize:Mode(Clamped / Periodic / No Ramp)")
v = vis(TI, lo=0.2, hi=0.6)
check("Clamped (old): grey ramp = clip((h - 0.2)/0.4)",
      np.allclose(v[..., 0], np.clip((hh - 0.2) / 0.4, 0, 1), atol=1e-6))
v = vis(TI, lo=0.0, hi=0.25, range_mode="periodic")
check("Periodic: grey = ((h - 0)/0.25) mod 1", np.allclose(v[..., 0], np.mod(hh / 0.25, 1), atol=1e-6))
check("negative control: Periodic != Clamped", not np.allclose(v, vis(TI, lo=0.0, hi=0.25), atol=1e-3))
v = vis(TI, lo=0.4, hi=0.6, range_mode="no_ramp", ramp="terrain")
want = (hh - 0.4) / 0.2
check("No Ramp: no ramp applied (Terrain not used either), all three channels = (h - 0.4)/0.2, not clamped",
      np.allclose(v, np.repeat(want[..., None], 3, -1), atol=1e-6)
      and float(v.max()) > 1.0 and float(v.min()) < 0.0, (v.min(), v.max()))
v = vis(TI, range_mode="periodic")
check("Periodic + automatic range: the highest point t = 1 -> becomes 0 after the modulo",
      near(v[..., 0][hh == hh.max()][0], 0.0, 1e-6))

sec("Visualize:Tint by")
mm_ = L(TI, "m")
v = vis(TI, tint_by="mask", tint_layer="m")
check("Mask: the ramp is applied to the tint layer, automatic range = its own min/max",
      np.allclose(v[..., 0], (mm_ - mm_.min()) / (mm_.max() - mm_.min()), atol=1e-6))
v = vis(TI, tint_by="mask", tint_layer="m", lo=0.5, hi=1.0)
check("Mask + manual range", np.allclose(v[..., 0], np.clip((mm_ - 0.5) / 0.5, 0, 1), atol=1e-6))
col = np.stack([mm_, 1 - mm_, np.full_like(mm_, 0.25)], -1)
CI = TI.copy()
CI.set("Cd", col.astype(np.float32))
v = vis(CI, tint_by="color", tint_layer="Cd", range_mode="periodic", lo=5, hi=6)
check("Color: the tint layer is used directly as colour (ignores Range / Mode)", np.allclose(v, col, atol=1e-6))
v1 = vis(CI, tint_by="color", tint_layer="Cd", hillshade=0.7)
f_ = vis(CI, hillshade=0.7) / np.maximum(vis(CI), 1e-9)
sel = (vis(CI)[..., 0] > 0.05) & (vis(CI, hillshade=0.7)[..., 0] < 0.999)
check("Color + shading: the shading factor still comes from height (same factor as under Height tint)",
      np.allclose(v1[sel], np.clip(col[sel] * f_[sel], 0, 1), atol=1e-5))
gray1 = np.repeat(mm_[..., None], 3, -1)
CI.set("g1", mm_[..., None].astype(np.float32))
vg = vis(CI, tint_by="color", tint_layer="g1")
check("a single-channel Color layer is spread to three channels", vg.shape == gray1.shape and np.allclose(vg, gray1, atol=1e-6),
      vg.shape)
CI.set("hot", (np.ones_like(col) * 1.5).astype(np.float32))
check("Color ignores Mode: under No Ramp the colour is still clamped to 1",
      np.allclose(vis(CI, tint_by="color", tint_layer="hot", range_mode="no_ramp"), 1.0))
check("negative control: Tint by Height (default) ignores the tint layer",
      np.allclose(vis(CI, tint_layer="Cd"), vis(CI), atol=0))
try:
    vis(TI, tint_by="mask")
    check("Mask / Color without a tint layer raises", False)
except ValueError as e:
    check("Mask / Color without a tint layer raises", "Tint Layer" in str(e), e)
for bad in (dict(range_mode="x"), dict(tint_by="x", tint_layer="m")):
    try:
        vis(TI, **bad)
        check(f"{bad} raises", False)
    except ValueError as e:
        check(f"{bad} raises", True, e)
check("speed mode is unaffected by these parameters",
      np.array_equal(vis(TI, layer="vel", mode="velocity_hsv", range_mode="no_ramp",
                         tint_by="mask", tint_layer="m"),
                     vis(TI, layer="vel", mode="velocity_hsv")))

sec("Visualize: panel")
check("check_layout is empty", PANEL.check_layout(
    "PCG_COPVisualize", M["PCG_COPVisualize"].INPUT_TYPES()) == [])


# ═══════════════════════════════════════════════════ HeightField Strata
def strat(vals, extra=None, **kw):
    k = dict(spacing=0.2, sharpness=0.5, hardness_random=0.0, strength=0.8)
    k.update(kw)
    o = run("PCG_COPStrata", row(vals, **(extra or {})), **k)[0]
    return L(o, "C")[0], L(o, "C_id")[0]


sec("Strata:Strata Offset / Mask Layer / Output Strata Only")
# no tilt, no noise, hardness not random -> terraces: p = 1/(1 - 0.5) = 2
r, k_ = strat([0.5])
check("reference (old): 0.5 -> target 0.4 + 0.2·0.5^2 = 0.45, blended back by 0.8 -> 0.46", near(r[0], 0.46, 1e-6), r)
r, k_ = strat([0.53], strata_offset=0.1)
check("Offset 0.1: layer boundaries 0.1 + 0.2k; 0.53 -> f = 0.15 -> target 0.5045 -> 0.53 + 0.8·(-0.0255)",
      near(r[0], 0.53 + 0.8 * (0.5045 - 0.53), 1e-6) and k_[0] == 2, (r, k_))
r0, _ = strat([0.53])
check("negative control: no shift -> 0.53 + 0.8·(0.4845 - 0.53)", near(r0[0], 0.53 + 0.8 * (0.4845 - 0.53), 1e-6), r0)
r, k_ = strat([0.05], strata_offset=0.1)
check("layer index follows the Offset: 0.05 in [-0.1, 0.1) -> layer -1", k_[0] == -1, k_)
r, _ = strat([0.5, 0.5], {"mm": [0.5, 0.0]}, mask_layer="mm")
check("Mask Layer multiplies Strength: 0.5 -> 0.5 + 0.8·0.5·(-0.05) = 0.48; mask 0 unchanged",
      near(r[0], 0.48, 1e-6) and near(r[1], 0.5, 1e-7), r)
r, _ = strat([0.5, 0.5], {"mm": [2.0, -1.0]}, mask_layer="mm")
check("Mask Layer clamped to 0..1 (2 -> 1, -1 -> 0)", near(r[0], 0.46, 1e-6) and near(r[1], 0.5, 1e-7), r)
r, _ = strat([0.5], strata_only=True)
check("Output Strata Only: outputs only the displacement 0.45 - 0.5 = -0.05 (not multiplied by Strength)", near(r[0], -0.05, 1e-6), r)
img_ = terrain()
so = run("PCG_COPStrata", img_, strata_only=True, tilt="0.3 0.1", noise_amount=0.03)[0]
s1 = run("PCG_COPStrata", img_, strength=1.0, tilt="0.3 0.1", noise_amount=0.03)[0]
check("height + strata-only output = the Strength 1 result (holds under tilt + noise too)",
      np.allclose(L(img_, "C") + L(so, "C"), L(s1, "C"), atol=1e-6))
check("Output Strata Only does not read Mask Layer",
      np.array_equal(L(so, "C"), L(run("PCG_COPStrata", img_, strata_only=True, tilt="0.3 0.1",
                                         noise_amount=0.03, mask_layer="m")[0], "C")))

sec("Strata: panel")
check("check_layout is empty", PANEL.check_layout(
    "PCG_COPStrata", M["PCG_COPStrata"].INPUT_TYPES()) == [])

_finish()
