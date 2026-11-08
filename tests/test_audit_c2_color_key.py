"""
pcg100 · c2_color_key: a batch of COP keying / color nodes filled in per the SideFX docs.

  Chroma Key      Method gains Chromakey (hue / saturation / luminance ranges + Rolloff) / Channel Separation;
                  Invert, Preview
  Despill         new node: removes spill only (Bias / Luminance / Mask), plus a spill layer
  Illegal Pixel   Illegal Pixels gains blend / zero / highlight / isolate; Detect / Rule
  Random          Range Values gains Min/Max (per component, RGB / HSV) / Color Ramp / Specific Values
  Equalize        new node: range remap by min / max / average (not histogram equalization)
  Histogram Plot  new node: draws the histogram as an image + counts
  Compare Mask    new node: boolean / soft mask
  Mono to RGB     new node: through a color ramp
  Mono to HF      new node: scale + offset
  Segment by Value  mode gains cast (the Cast of Mono to ID)

All checked against hand-computed numbers; the "bit-identical to before the change at default values" checks recompute
with the old implementation from the baseline commit (pcg99 baseline) and compare.
"""
import importlib.util
import os
import subprocess
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
from comfyui_pcg.geo.cop import pixel as PX, solve as SV, colorkey as CK  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402

OK = []
BASE = "a9e114d"            # pcg99 baseline: the commit before this batch was started


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def img(**layers):
    """Layer name = (H,W) or (H,W,C) array. Row 0 is the bottom of the image."""
    first = np.asarray(next(iter(layers.values())))
    im = CopImage(first.shape[1], first.shape[0])
    for k, v in layers.items():
        PX.put(im, k, np.asarray(v, np.float64))
    return im


def L(im, name):
    return PX.getn(im, name)


def near(a, b, tol=1e-6):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return a.shape == b.shape and bool(np.allclose(a, b, atol=tol, rtol=0,
                                                   equal_nan=True))


def raises(fn, has=""):
    """has: text the error message must contain (distinguishes "our own check caught it" from numpy happening to blow up later)."""
    try:
        fn()
    except ValueError as e:
        return has in str(e)
    return False


def old_module(rel):
    """The old file from the baseline commit, loaded as another module in the same package (relative imports keep working)."""
    src = subprocess.run(["git", "-C", _R, "show", f"{BASE}:{rel}"],
                         capture_output=True, text=True, check=True).stdout
    name = "comfyui_pcg.geo.cop._base_" + os.path.basename(rel)[:-3]
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "comfyui_pcg.geo.cop"
    exec(compile(src, rel, "exec"), mod.__dict__)
    return mod


try:
    OLD_PX = old_module("comfyui_pcg/geo/cop/pixel.py")
    OLD_SV = old_module("comfyui_pcg/geo/cop/solve.py")
except (subprocess.CalledProcessError, FileNotFoundError):
    # The device layout (the user's ComfyUI) has no git repository, so the baseline commit is unavailable. Then the "bit-identical
    # to before the change" checks degrade to comparing with itself, which always passes and means nothing -- say so; the real baseline comparison runs in the sandbox that has git.
    print(f"  (note: baseline commit {BASE} unavailable (no git); the bit-identical-to-before checks degrade to self-comparison and do not count)")
    OLD_PX, OLD_SV = PX, SV
RNG = np.random.default_rng(7)


def same_layers(a, b):
    return a.names == b.names and all(
        np.array_equal(L(a, n), L(b, n), equal_nan=True) for n in a.names)


def node(name, **kw):
    """Run through the node class: parameters not given take the INPUT_TYPES defaults (this is what checks default = old behaviour)."""
    cls = M[name]
    it = cls.INPUT_TYPES()
    args = {}
    for k, v in {**it.get("required", {}), **it.get("optional", {})}.items():
        if k in kw:
            args[k] = kw[k]
        elif isinstance(v[0], list):
            args[k] = (v[1] if len(v) > 1 else {}).get("default", v[0][0])
        elif len(v) > 1 and "default" in v[1]:
            args[k] = v[1]["default"]
    return cls().run(**args)


# ═════════════════════════════════════════════════════════ Chroma Key
sec("Chroma Key: default (distance) bit-identical to before the change")
rgb0 = RNG.random((6, 7, 3))
im0 = img(C=rgb0)
check("node default parameters == baseline chroma_key",
      same_layers(node("PCG_COPChromaKey", cop=im0)[0], OLD_PX.chroma_key(im0)))
check("  also identical with a different key / tolerance / premultiply",
      same_layers(node("PCG_COPChromaKey", cop=im0, key_color="0 0 1", tolerance=0.3,
                       softness=0.2, despill=0.5, premultiply=True)[0],
                  OLD_PX.chroma_key(im0, key="0 0 1", tolerance=0.3, softness=0.2,
                                    despill=0.5, premultiply_out=True)))
it = M["PCG_COPChromaKey"].INPUT_TYPES()["required"]
check("  old parameters kept their positions, new parameters all appended",
      list(it)[:10] == ["cop", "layer", "key_color", "tolerance", "softness", "despill",
                        "out_layer", "alpha_layer", "premultiply", "method"]
      and it["method"][0][0] == "distance")


def hsv(h_deg, s=1.0, v=1.0):
    return PX.hsv_to_rgb(np.asarray([[[h_deg / 360.0, s, v]]]))[0, 0]


def matte(pixels, **kw):
    im = img(C=np.asarray(pixels, np.float64).reshape(1, -1, 3))
    kw.setdefault("despill", 0.0)
    return L(PX.chroma_key(im, **kw), "alpha")[0, :, 0]


sec("Chroma Key: Chromakey (HSV ranges)")
px = [hsv(120), hsv(0), hsv(160), hsv(155), hsv(175)]
ck = dict(method="chromakey", hue=(90, 150), sat=(0.3, 1.0), lum=(0.0, 1.0))
m = matte(px, rolloff=(20, 0.1, 0.1), interpolation="linear", **ck)
check("pure green in range -> 0; red -> 1; hue 10° out of range (Rolloff 20) -> 0.5; 5° -> 0.25; 25° -> 1",
      near(m, [0, 1, 0.5, 0.25, 1]), m)
want = {"ease_in": 1 - (1 - 0.25 ** 2), "ease_out": 1 - 0.75 ** 2,
        "smooth": 1 - (0.75 ** 2 * (3 - 1.5)), "gaussian": 1 - np.exp(-4.5 * 0.0625)}
for k, w in want.items():
    got = matte(px, rolloff=(20, 0.1, 0.1), interpolation=k, **ck)
    check(f"  Interpolation = {k}: 5° out of range matte = {w:.5f}, 0 in range, 1 outside Rolloff",
          near(got[[0, 1, 3, 4]], [0, 1, w, 1]), got)
check("  the five Interpolations differ pairwise at 5° (negative control)",
      len({round(float(matte(px, rolloff=(20, .1, .1), interpolation=k, **ck)[3]), 5)
           for k in CK.ROLLOFFS}) == 5)
check("  bad Interpolation -> error (does not silently fall back to gaussian)",
      raises(lambda: matte(px, rolloff=(20, .1, .1), interpolation="cubic", **ck), "Interpolation"))
check("  Rolloff = 0 is a hard edge: 5° out of range is 1",
      near(matte(px, rolloff=(0, 0.1, 0.1), **ck), [0, 1, 1, 1, 1]))
check("  Hue 350..10 wraps through 0°: red (0°) keyed out, cyan (180°) kept; 10..350 the other way round",
      near(matte([hsv(0), hsv(180)], method="chromakey", hue=(350, 10), sat=(0, 1),
                 lum=(0, 1), rolloff=(0, 0, 0)), [0, 1])
      and near(matte([hsv(0.0001), hsv(180)], method="chromakey", hue=(10, 350),
                     sat=(0, 1), lum=(0, 1), rolloff=(0, 0, 0)), [1, 0]))
check("  Hue range width ≥ 360: the whole circle counts",
      near(matte([hsv(0), hsv(180), hsv(300)], method="chromakey", hue=(0, 360),
                 sat=(0, 1), lum=(0, 1), rolloff=(0, 0, 0)), [0, 0, 0]))
m = matte([hsv(120, 0.25), hsv(120, 0.2), hsv(120, 0.6)], rolloff=(0, 0.1, 0.1), **ck)
check("  saturation 0.25 (min 0.3, Rolloff 0.1) -> 0.5; 0.2 -> 1; 0.6 -> 0", near(m, [0.5, 1, 0]), m)
# Rec.709 luminance of pure green is 0.7152: max 0.5 -> 0.2152 out of range
m = matte([hsv(120)] * 3, method="chromakey", hue=(90, 150), sat=(0.3, 1.0),
          lum=(0.0, 0.5), rolloff=(0, 0, 0.4304))
check("  luminance 0.2152 out of range, Rolloff 0.4304 -> 0.5", near(m, [0.5] * 3), m)
check("  luminance max 0.5, Rolloff 0.1: pure green (0.7152) kept; widening the range to 1 keys it out (negative control)",
      near(matte([hsv(120)], method="chromakey", hue=(90, 150), sat=(0.3, 1),
                 lum=(0, 0.5), rolloff=(0, 0, 0.1)), [1])
      and near(matte([hsv(120)], rolloff=(0, 0, 0.1), **ck), [0]))
check("  saturation Rolloff = 0: 0.05 out of range is a hard 1 (mutation: d <= 1)",
      near(matte([hsv(120, 0.25), hsv(120, 0.6)], rolloff=(0, 0, 0), **ck), [1, 0]))
check("  Hue 350..10 is 20° wide (not 340°): 40° is out of range, 5° / 355° in range",
      near(matte([hsv(40), hsv(5), hsv(355)], method="chromakey", hue=(350, 10), sat=(0, 1),
                 lum=(0, 1), rolloff=(0, 0, 0)), [1, 0, 0]))
check("  chromakey does not read Tolerance / Softness / Threshold / Width (hidden in the panel)",
      near(matte(px, rolloff=(20, .1, .1), tolerance=9, softness=9, threshold=0.9,
                 width=3, **ck), matte(px, rolloff=(20, .1, .1), **ck)))

sec("Chroma Key:Channel Separation")
px = [(0, 1, 0), (0.5, 0.5, 0.5), (0.2, 0.8, 0.4), (0.1, 0.6, 0.1), (0.1, 0.56, 0.1)]
cs = dict(method="channel_separation", key="0 1 0")
m = matte(px, threshold=0.5, width=0.2, **cs)
# s = G - max(R,B): 1, 0, 0.4, 0.5, 0.46 -> matte = 1 - s: 0, 1, 0.6, 0.5, 0.54
check("Threshold 0.5 / Width 0.2 (fit 0.4..0.6): pure green 0, grey 1, 0.6->1, 0.5->0.5, 0.54->0.7",
      near(m, [0, 1, 1, 0.5, 0.7]), m)
m = matte(px, threshold=0.5, width=0.0, **cs)
check("  Width 0 = hard threshold (matte > Threshold)", near(m, [0, 1, 1, 0, 1]), m)
m = matte([(0, 0.5, 0), (0, 0.25, 0)], threshold=0.5, width=0.0, **cs)
check("  Width 0: a matte exactly equal to Threshold is not kept (strict >), and no nan", near(m, [0, 1]), m)
m = matte(px, threshold=0.55, width=0.0, **cs)
check("  Threshold 0.55: the 0.54 one flips to 0", near(m, [0, 1, 1, 0, 0]), m)
m = matte([(0.5, 0.25, 1.0), (0.2, 0.1, 0.2)], method="channel_separation",
          key="0 0.5 1", threshold=0.5, width=1.0)
# screen color (0,0.5,1): k = B, reference difference 0.5; pixel difference 0.5 -> s = 1; difference 0 -> s = 0
check("  a non-pure Screen Color normalizes by its own channel difference", near(m, [0, 1]), m)
check("  grey Screen Color (no dominant channel) -> error",
      raises(lambda: matte(px, method="channel_separation", key="0.5 0.5 0.5")))
check("  channel_separation does not read Hue / Sat / Lum / Rolloff / Interpolation / Tolerance",
      near(matte(px, threshold=0.5, width=0.2, hue=(0, 1), sat=(0.9, 1), lum=(5, 6),
                 rolloff=(1, 1, 1), interpolation="gaussian", tolerance=7, **cs),
           matte(px, threshold=0.5, width=0.2, **cs)))
check("  the three Methods give different results on the same image (negative control)",
      not near(matte(px, **cs), matte(px, method="distance"))
      and not near(matte(px, **cs), matte(px, method="chromakey"))
      and not near(matte(px, method="chromakey"), matte(px, method="distance")))
check("  bad Method -> error", raises(lambda: matte(px, method="nope")))

sec("Chroma Key:Invert / Preview")
for meth in ("distance", "chromakey", "channel_separation"):
    a, b = matte(px, method=meth, width=0.2), matte(px, method=meth, width=0.2, invert=True)
    check(f"Invert({meth}): matte becomes 1 - matte, and it really changed", near(a + b, np.ones(5))
          and not near(a, b))
im = img(C=np.asarray(px, np.float64).reshape(1, -1, 3))
a = matte(px, threshold=0.5, width=0.2, **cs)[:, None]
out = L(PX.chroma_key(im, despill=0.0, threshold=0.5, width=0.2, preview=True,
                      preview_color="1 0 1", **cs), "C")[0]
check("Preview: color · matte + Preview Color · (1 - matte)",
      near(out, np.asarray(px) * a + np.asarray([1, 0, 1.0]) * (1 - a)), out)
check("  Preview off: color layer unchanged (not premultiplied, not tinted)",
      near(L(PX.chroma_key(im, despill=0.0, threshold=0.5, width=0.2, **cs), "C")[0], px))
out2 = L(PX.chroma_key(im, despill=0.0, threshold=0.5, width=0.2, preview=True,
                       preview_color="0 0 0", **cs), "C")[0]
check("  Preview Color set to black = the premultiplied result",
      near(out2, np.asarray(px) * a) and not near(out2, out)
      and near(out2, L(PX.chroma_key(im, despill=0.0, threshold=0.5, width=0.2,
                                     premultiply_out=True, **cs), "C")[0]))
r = node("PCG_COPChromaKey", cop=im, method="channel_separation", threshold=0.5,
         width=0.2, despill=0.0, invert=True, show_matte=True, preview_color="1 0 1")[0]
check("  the node passes parameters straight through to geo (Method / Threshold / Width / Invert / Preview)",
      near(L(r, "alpha")[0, :, 0], 1 - a[:, 0])
      and near(L(r, "C")[0], np.asarray(px) * (1 - a) + np.asarray([1, 0, 1.0]) * a))
r = node("PCG_COPChromaKey", cop=img(C=np.asarray([hsv(120), hsv(165), hsv(120, 0.25),
                                                    hsv(120, 1, 1.5)]).reshape(1, 4, 3)),
         method="chromakey", hue_min=100, hue_max=140, sat_min=0.3, sat_max=1.0,
         lum_min=0.0, lum_max=1.0, hue_rolloff=50, sat_rolloff=0.1, lum_rolloff=0.1456,
         interpolation="linear", despill=0.0)[0]
# 4th: green with v = 1.5, luminance 1.0728, 0.0728 above max -> weight 0.5
check("  node: hue_min/max, sat_min/max, lum_min/max and the three rolloffs each wired to their own",
      near(L(r, "alpha")[0, :, 0], [0, 0.5, 0.5, 0.5]), L(r, "alpha")[0, :, 0])

r = node("PCG_COPChromaKey", cop=img(C=np.asarray([hsv(120, 1.0, 0.5), hsv(120, 0.5),
                                                    hsv(120, 0.5, 0.5)]).reshape(1, 3, 3)),
         method="chromakey", hue_min=90, hue_max=150, sat_min=0.0, sat_max=0.6,
         lum_min=0.0, lum_max=0.5, hue_rolloff=0, sat_rolloff=0, lum_rolloff=0,
         despill=0.0, show_matte=True, preview_color="0 0 1")[0]
# 1st: saturation 1 exceeds 0.6; luminance: (0.5,1,0.5) 0.8576, (0.25,0.5,0.25) 0.4288 -> only the 3rd is in the luminance range
check("  node: sat_max / lum_max / preview_color each wired to their own",
      near(L(r, "alpha")[0, :, 0], [1, 1, 0])
      and near(L(r, "C")[0, 2], [0, 0, 1]), L(r, "alpha")[0, :, 0])

# ═════════════════════════════════════════════════════════ Despill
sec("Despill (new node)")
src = np.asarray([[(0.2, 0.9, 0.6, 0.3), (0.5, 0.4, 0.7, 1.0), (0.3, 0.8, 0.3, 0.5)]])
im = img(C=src)
r = CK.despill(im, bias=0.5)
check("Bias 0.5: G pressed down to (R+B)/2; non-green pixels untouched; alpha unchanged",
      near(L(r, "C")[0], [(0.2, 0.4, 0.6, 0.3), (0.5, 0.4, 0.7, 1.0), (0.3, 0.3, 0.3, 0.5)]),
      L(r, "C")[0])
check("  spill layer = the removed color (G component only); no alpha layer generated",
      near(L(r, "spill")[0], [(0, 0.5, 0), (0, 0, 0), (0, 0.5, 0)])
      and r.names == ["C", "spill"], r.names)
g0 = L(CK.despill(im, bias=0.0), "C")[0, :, 1]
g1 = L(CK.despill(im, bias=1.0), "C")[0, :, 1]
check("  Bias 0 leans red (limit = R), 1 leans blue (limit = B); the pure-color (R = B) pixel shows no change",
      near(g0, [0.2, 0.4, 0.3]) and near(g1, [0.6, 0.4, 0.3]), (g0, g1))
r = CK.despill(im, bias=0.5, luminance=1.0)
w = np.asarray([0.2126, 0.7152, 0.0722])
check("  Luminance 1: Rec.709 luminance restored to the original; the same amount added to all three channels",
      near((L(r, "C")[0, :, :3] * w).sum(-1), (src[0, :, :3] * w).sum(-1))
      and near(L(r, "C")[0, 0, :3], np.asarray([0.2, 0.4, 0.6]) + 0.7152 * 0.5))
check("  Luminance 0.5 adds back half (differs from both 0 and 1)",
      near(L(CK.despill(im, luminance=0.5), "C")[0, 0, :3],
           np.asarray([0.2, 0.4, 0.6]) + 0.5 * 0.7152 * 0.5))
check("  the spill layer does not include the luminance added back",
      near(L(r, "spill")[0], [(0, 0.5, 0), (0, 0, 0), (0, 0.5, 0)]))
check("  Mask 0.5: removes only half; Mask 0: original image",
      near(L(CK.despill(im, mask=0.5), "C")[0, :, 1], [0.65, 0.4, 0.55])
      and near(L(CK.despill(im, mask=0.0), "C"), src))
im2 = img(C=src, bl=np.asarray([[0.0, 1.0, 1.0]]), ml=np.asarray([[0.5, 1.0, 0.0]]))
check("  Bias Layer multiplies Bias per pixel (0 -> leans red)",
      near(L(CK.despill(im2, bias=0.5, bias_layer="bl"), "C")[0, :, 1], [0.2, 0.4, 0.3]))
check("  Mask Layer multiplies Mask per pixel",
      near(L(CK.despill(im2, mask_layer="ml"), "C")[0, :, 1], [0.65, 0.4, 0.8]))
check("  Spill Color blue: B is suppressed (limit (R+G)/2)",
      near(L(CK.despill(im, spill_color="0 0 1"), "C")[0, :, :3],
           [(0.2, 0.9, 0.55), (0.5, 0.4, 0.45), (0.3, 0.8, 0.3)]))
r = CK.despill(im, out_layer="clean", spill_layer="")
check("  with a separate Output Layer the source layer is untouched; empty Spill Layer means no spill output",
      r.names == ["C", "clean"] and near(L(r, "C"), src), r.names)
rgb3 = img(C=src[..., :3])
check("  RGB (3-channel) layers work too, result equals the first three channels of RGBA",
      near(L(CK.despill(rgb3), "C"), L(CK.despill(im), "C")[..., :3]))
check("  2-channel / single-channel (image width ≥ 3) -> error",
      raises(lambda: CK.despill(img(C=np.ones((2, 4, 2)))))
      and raises(lambda: CK.despill(img(C=np.ones((2, 4))))))
im3 = img(C=src, two=np.full((1, 3), 2.0))
check("  Bias × Bias Layer above 1 clamped to 1 (= leans blue, no extrapolation)",
      near(L(CK.despill(im3, bias=1.0, bias_layer="two"), "C")[0, :, 1], [0.6, 0.4, 0.3]))
check("  Mask × Mask Layer above 1 clamped to 1 (never over-removes)",
      near(L(CK.despill(im3, mask=1.0, mask_layer="two"), "C")[0, :, 1], [0.4, 0.4, 0.3]))
check("  single-channel layer -> error (needs RGB)",
      raises(lambda: CK.despill(img(C=np.ones((2, 2))))))
r = node("PCG_COPDespill", cop=im2, bias=1.0, luminance=1.0, mask=0.5, bias_layer="bl",
         mask_layer="ml", spill_color="0 1 0", out_layer="o", spill_layer="s")[0]
# pixel 0: bias 1·0 = 0 -> limit R = 0.2, removes 0.7; mask 0.5·0.5 = 0.25 -> removes 0.175
check("  node: every parameter wired to the right place",
      near(L(r, "s")[0, 0], (0, 0.175, 0))
      and near(L(r, "o")[0, 0, :3], np.asarray([0.2, 0.725, 0.6]) + 0.7152 * 0.175),
      L(r, "o")[0, 0])
dd = node("PCG_COPDespill", cop=im)[0]
check("  node defaults: Mask 1 / Spill green / Bias 0.5 / Luminance 0",
      near(L(dd, "C"), L(CK.despill(im, bias=0.5), "C")) and "spill" in dd.names)

# ═════════════════════════════════════════════════════════ Illegal Pixel
sec("Illegal Pixel: default (replace) bit-identical to before the change")
bad = RNG.random((5, 6, 3)) - 0.3
bad[1, 2, 0] = np.nan
bad[3, 4, 1] = np.inf
bad[0, 0, 2] = -np.inf
imb = img(C=bad)
o1, rep1 = M["PCG_COPIllegalPixel"]().run(imb, "", 0.0, 1.0, 0.0, False)
o0, rep0 = OLD_PX.illegal_pixel(imb)
import json                                             # noqa: E402
check("node given only the old 6 parameters == baseline (image and report)",
      same_layers(o1, o0) and json.loads(rep1) == rep0, rep1)
o1 = node("PCG_COPIllegalPixel", cop=imb, nan=0.5, pos_inf=2.0, neg_inf=-2.0,
          clamp_negative=True)[0]
check("  also identical with different replacement values / Clamp Negative",
      same_layers(o1, OLD_PX.illegal_pixel(imb, "", 0.5, 2.0, -2.0, True)[0]))

sec("Illegal Pixel: the four Houdini modes")
g = np.arange(9, dtype=np.float64).reshape(3, 3) + 1.0          # 1..9, center is 5
g[1, 1] = np.nan
r, rep = PX.illegal_pixel(img(C=g), mode="blend")
check("blend: the center NaN <- average of its 8 neighbours (45 - 5)/8 = 5; the rest untouched; flagged = 1",
      near(L(r, "C")[..., 0], np.arange(9).reshape(3, 3) + 1.0) and rep == {"C": {"flagged": 1}},
      rep)
row = np.asarray([[1.0, np.nan, np.nan, np.nan, 5.0]])
r, rep = PX.illegal_pixel(img(C=row), mode="blend")
check("  a contiguous bad region is filled ring by ring inwards: 1 ? ? ? 5 -> 1 1 3 5 5",
      near(L(r, "C")[0, :, 0], [1, 1, 3, 5, 5]) and rep["C"]["flagged"] == 3,
      L(r, "C")[0, :, 0])
c2 = np.asarray([[1.0, 2.0], [np.nan, 4.0]])
r, _ = PX.illegal_pixel(img(C=c2), mode="blend")
check("  a corner pixel has only 3 neighbours: (1 + 2 + 4)/3", near(L(r, "C")[1, 0, 0], 7 / 3))
r, rep = PX.illegal_pixel(img(C=np.full((2, 2), np.nan)), mode="blend")
check("  everything bad (no good pixel to borrow from) -> 0, no infinite loop",
      near(L(r, "C"), np.zeros((2, 2, 1))) and rep["C"]["flagged"] == 4)
rgbb = np.full((2, 3, 3), 0.25)
rgbb[0, 1, 2] = np.nan
rgbb[1, 2, 0] = np.inf
rgbb[1, 0, 1] = -np.inf
imr = img(C=rgbb)
bm = np.zeros((2, 3), bool)
bm[0, 1] = bm[1, 2] = bm[1, 0] = True
r, rep = PX.illegal_pixel(imr, mode="zero")
check("zero: a bad **pixel** is cleared entirely (one bad component clears all three), good ones untouched; counted per pixel",
      near(L(r, "C"), np.where(bm[..., None], [0.0] * 3, 0.25)) and rep["C"]["flagged"] == 3, rep)
r, _ = PX.illegal_pixel(imr, mode="highlight", highlight="1 0.5 0")
check("highlight: bad pixels = Highlight Color, good ones unchanged",
      near(L(r, "C"), np.where(bm[..., None], [1, 0.5, 0], 0.25)))
r, _ = PX.illegal_pixel(imr, mode="isolate", highlight="1 0.5 0")
check("isolate: bad pixels = Highlight Color, good ones cleared",
      near(L(r, "C"), np.where(bm[..., None], [1, 0.5, 0], 0.0)))
r, _ = PX.illegal_pixel(imr, mode="highlight", highlight="0 0 1")
check("  changing Highlight Color changes the result (negative control)",
      near(L(r, "C"), np.where(bm[..., None], [0, 0, 1], 0.25)))
rgba = np.full((1, 2, 4), 0.25)
rgba[0, 0, 0] = np.nan
r, _ = PX.illegal_pixel(img(C=rgba), mode="highlight", highlight="1 0 0")
check("  RGBA layer: flagged pixels get alpha 1", near(L(r, "C")[0], [(1, 0, 0, 1), (0.25,) * 4]))
mono = np.asarray([[np.nan, 0.5]])
r, _ = PX.illegal_pixel(img(C=mono), mode="isolate", highlight="0.7 0 0")
check("  single-channel layer: takes the first component of Highlight Color", near(L(r, "C")[0, :, 0], [0.7, 0]))

sec("Illegal Pixel:Detect / Rule")
nm = np.zeros((2, 3), bool)
nm[0, 1] = True
check("Detect = nan: catches only NaN (1); inf: only ±Inf (2); nan_inf: 3",
      [PX.illegal_pixel(imr, mode="zero", detect=d)[1]["C"]["flagged"]
       for d in ("nan", "inf", "nan_inf")] == [1, 2, 3])
r, _ = PX.illegal_pixel(imr, mode="isolate", detect="nan", highlight="1 1 1")
check("  the nan mode flags exactly the NaN pixel", near(L(r, "C")[..., 0], nm.astype(float)))
v = np.asarray([[-1.0, 0.0, 0.5, 1.0, 2.0]])
imv = img(C=v)
want = {"less": [1, 1, 0, 0, 0], "less_equal": [1, 1, 1, 0, 0], "greater": [0, 0, 0, 1, 1],
        "greater_equal": [0, 0, 1, 1, 1], "equal": [0, 0, 1, 0, 0]}
for rule, w in want.items():
    r, rep = PX.illegal_pixel(imv, mode="isolate", detect="custom", rule=rule, value=0.5,
                              highlight="1 1 1")
    check(f"Custom / {rule} 0.5 → {w}", near(L(r, "C")[0, :, 0], w)
          and rep["C"]["flagged"] == sum(w), L(r, "C")[0, :, 0])
r, _ = PX.illegal_pixel(imv, mode="isolate", detect="custom", rule="less", value=1.5,
                        highlight="1 1 1")
check("  Value set to 1.5: less catches two more (negative control)", near(L(r, "C")[0, :, 0], [1, 1, 1, 1, 0]))
r, rep = PX.illegal_pixel(img(C=mono), mode="zero", detect="custom", rule="equal", value=0.5)
check("  Custom cannot catch NaN (NaN compares false with everything): 0.5 cleared, NaN still there",
      np.isnan(L(r, "C")[0, 0, 0]) and L(r, "C")[0, 1, 0] == 0 and rep["C"]["flagged"] == 1)
check("  bad Detect / Rule / Illegal Pixels -> error",
      raises(lambda: PX.illegal_pixel(imv, mode="zero", detect="x"))
      and raises(lambda: PX.illegal_pixel(imv, mode="zero", detect="custom", rule="x"))
      and raises(lambda: PX.illegal_pixel(imv, mode="x")))
r, _ = PX.illegal_pixel(imr, mode="zero", nan=9, posinf=9, neginf=9, clamp_negative=True)
check("  the four Houdini modes do not read the replacement values / Clamp Negative (hidden in the panel)",
      near(L(r, "C"), np.where(bm[..., None], [0.0] * 3, 0.25)))
im2l = img(C=g, D=row.repeat(3, 0)[:, :3])
r, rep = PX.illegal_pixel(im2l, layers="C", mode="zero")
check("  Layers with only C ticked: NaN in layer D untouched", np.isnan(L(r, "D")).any() and list(rep) == ["C"])
r, rep = M["PCG_COPIllegalPixel"]().run(imv, "", 0.0, 1.0, 0.0, False, "isolate", "0.5 0 0",
                                        "custom", "greater_equal", 1.0)
check("  node: mode / highlight_color / detect / rule / value each wired to their own",
      near(L(r, "C")[0, :, 0], [0, 0, 0, 0.5, 0.5]) and json.loads(rep) == {"C": {"flagged": 2}},
      rep)

# ═════════════════════════════════════════════════════════ Random
sec("Random: default (shared) bit-identical to before the change")
for kw in (dict(), dict(channels="3", rand_seed=5, min=-1.0, max=2.0),
           dict(channels="4", resolution_x=9, resolution_y=4)):
    a = node("PCG_COPRandom", **kw)[0]
    b = OLD_PX.random_layer(None, "pixel", "id", int(kw.get("channels", 1)),
                            kw.get("rand_seed", 0), kw.get("min", 0.0), kw.get("max", 1.0),
                            "random", kw.get("resolution_x", 512), kw.get("resolution_y", 512))
    check(f"node defaults + {kw or '{}'} == baseline", same_layers(a, b))
ids = np.asarray([[0, 0, 3, 3, -2, -2, 7, -1]], np.float64)
imi = img(id=ids)
check("  id mode also identical", same_layers(
    node("PCG_COPRandom", mode="id", channels="3", cop=imi)[0],
    OLD_PX.random_layer(imi, "id", "id", 3, 0, 0.0, 1.0, "random", 512, 512)))

sec("Random: Houdini's Range Values")
KW = dict(xres=64, yres=64, seed=3)
u = L(PX.random_layer(None, channels=3, **KW), "random")          # three uniform numbers in 0~1
r = L(PX.random_layer(None, channels=3, range_values="min_max", range_min="0 10 -5",
                      range_max="1 11 -3", **KW), "random")
check("min_max / RGB: each component has its own [min, max] -- exactly min + u · (max - min)",
      near(r, np.asarray([0, 10, -5.0]) + u * np.asarray([1, 1, 2.0]), 1e-5)
      and r[..., 1].min() >= 10 and r[..., 1].max() <= 11 and r[..., 2].max() <= -3)
check("  differs from the shared mode (one lo / hi pair shared) (negative control)",
      not near(r, L(PX.random_layer(None, channels=3, lo=0.0, hi=1.0, **KW), "random")))
r = L(PX.random_layer(None, channels=3, range_values="min_max", color_model="hsv",
                      range_min="120 1 1", range_max="120 1 1", **KW), "random")
check("min_max / HSV: hue locked at 120°, S = V = 1 -> all pure green", near(r, np.full_like(r, 0) + [0, 1, 0]))
r = L(PX.random_layer(None, channels=3, range_values="min_max", color_model="hsv",
                      range_min="0 0 0.25", range_max="360 0 0.75", **KW), "random")
check("  HSV: S = 0 -> grey, value is exactly 0.25 + u₂ · 0.5",
      near(r, np.repeat(0.25 + u[..., 2:3] * 0.5, 3, -1), 1e-6))
r = L(PX.random_layer(None, channels=3, range_values="min_max", color_model="hsv",
                      range_min="0 1 1", range_max="60 1 1", **KW), "random")
check("  HSV: hue 0..60°, S = V = 1 -> R = 1, B = 0, G = u₀ (red to yellow)",
      near(r, np.stack([np.ones_like(u[..., 0]), u[..., 0], np.zeros_like(u[..., 0])], -1), 1e-6))
check("  same three numbers, Color Model switched to RGB gives a different result (negative control)",
      not near(r, L(PX.random_layer(None, channels=3, range_values="min_max",
                                    range_min="0 1 1", range_max="60 1 1", **KW), "random")))
r = L(PX.random_layer(None, channels=3, range_values="color_ramp",
                      color_ramp="0:1,0,0  1:0,0,1", **KW), "random")
check("color_ramp: one uniform number through the ramp -- (1 - u₀, 0, u₀)",
      near(r, np.stack([1 - u[..., 0], 0 * u[..., 0], u[..., 0]], -1), 1e-6))
r2 = L(PX.random_layer(None, channels=3, range_values="color_ramp",
                       color_ramp="0:1,0,0  1:0,0,1", color_ramp_mode="constant", **KW),
       "random")
check("  Ramp interpolation constant: everything with u₀ < 1 falls on the first key (red)", near(r2, np.zeros_like(r2) + [1, 0, 0]))
r = L(PX.random_layer(None, channels=3, range_values="specific_values",
                      colors="1 0 0 3; 0 0 1 1", **KW), "random")
isred = u[..., 0] < 0.75
check("specific_values: weights 3 : 1 -> u₀ < 0.75 is red, the rest blue; red is ~75%",
      near(r, np.where(isred[..., None], [1, 0, 0], [0, 0, 1.0]))
      and abs(isred.mean() - 0.75) < 0.03, isred.mean())
r = L(PX.random_layer(None, channels=3, range_values="specific_values",
                      colors="1 0 0 3; 0 0 1;", **KW), "random")
check("  some with weights, some without (omitted means 1); a trailing semicolon is not an item",
      near(r, np.where(isred[..., None], [1, 0, 0], [0, 0, 1.0])))
r = L(PX.random_layer(None, channels=3, range_values="specific_values",
                      colors="1 0 0; 0 1 0; 0 0 1; 1 1 0", **KW), "random")
idx = np.minimum((u[..., 0] * 4).astype(int), 3)
check("  weight omitted = 1: the four colors each get one segment of u₀",
      near(r, np.asarray([(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0.0)])[idx]))
r = L(PX.random_layer(None, channels=3, range_values="specific_values",
                      colors="1 0 0 0\n0 1 0 2", **KW), "random")
check("  a color with weight 0 is never picked; newlines also separate", near(r, np.zeros_like(r) + [0, 1, 0]))
check("  Colors empty / missing a component / negative weight / all weights 0 -> error",
      all(raises(lambda c=c: PX.random_layer(None, range_values="specific_values", colors=c,
                                             **KW))
          for c in ("", "1 0", "1 0 0 -1; 0 1 0 2", "1 0 0 0; 0 1 0 0"))
      and raises(lambda: PX.random_layer(None, range_values="specific_values", colors=" ; ", **KW),
                 "is empty"))
check("  bad Range Values / Color Model -> error",
      raises(lambda: PX.random_layer(None, range_values="x", **KW))
      and raises(lambda: PX.random_layer(None, range_values="min_max", color_model="x", **KW)))
for ch, shape in ((1, 3), (3, 3), (4, 4)):
    r = L(PX.random_layer(None, channels=ch, range_values="color_ramp", **KW), "random")
    check(f"  Channels = {ch} -> {shape} channels" + (", alpha always 1" if ch == 4 else ""),
          r.shape[2] == shape and (ch != 4 or near(r[..., 3], np.ones((64, 64)))))
r = L(PX.random_layer(imi, mode="id", channels=3, range_values="specific_values",
                      colors="1 0 0; 0 1 0; 0 0 1"), "random")[0]
check("  id mode: same id, same color", near(r[0], r[1]) and near(r[2], r[3]) and near(r[4], r[5]))
rz = L(PX.random_layer(imi, mode="id", channels=3, range_values="specific_values",
                       colors="1 0 0; 0 1 0; 0 0 1", zero_negative_ids=True), "random")[0]
neg = ids[0] < 0
check("Zero Negative IDs: id < 0 outputs black, the rest unchanged; when off they are not black (negative control)",
      near(rz[neg], np.zeros((3, 3))) and near(rz[~neg], r[~neg]) and r[neg].sum() > 0)
rz = L(PX.random_layer(imi, mode="id", channels=1, zero_negative_ids=True), "random")[0, :, 0]
r1 = L(PX.random_layer(imi, mode="id", channels=1), "random")[0, :, 0]
check("  works in shared mode too", near(rz[neg], [0, 0, 0]) and near(rz[~neg], r1[~neg]) and (r1[neg] > 0).all())
check("  pixel mode does not read it (hidden in the panel)",
      near(L(PX.random_layer(None, zero_negative_ids=True, **KW), "random"),
           L(PX.random_layer(None, **KW), "random")))
r = node("PCG_COPRandom", channels="4", rand_seed=3, resolution_x=64, resolution_y=64,
         range_values="min_max", color_model="hsv", range_min="0 1 1", range_max="60 1 1")[0]
check("  node: range_values / color_model / range_min / range_max each wired to their own",
      near(L(r, "random")[..., 1], u[..., 0], 1e-6) and L(r, "random").shape[2] == 4)
r = node("PCG_COPRandom", mode="id", cop=imi, channels="3", range_values="specific_values",
         colors="0 1 0 1", zero_negative_ids=True)[0]
check("  node: colors / zero_negative_ids",
      near(L(r, "random")[0], np.where(neg[:, None], 0.0, [0, 1, 0])))
r = node("PCG_COPRandom", channels="3", rand_seed=3, resolution_x=64, resolution_y=64,
         range_values="color_ramp", color_ramp="0:0,0,0  1:2,2,2", color_ramp_mode="constant")[0]
check("  node: color_ramp / color_ramp_mode", near(L(r, "random"), np.zeros((64, 64, 3))))

# ═════════════════════════════════════════════════════════ Equalize
sec("Equalize (new node): the 14 Luminance Types")
p = np.asarray([[[0.2, 0.5, 0.8, 0.3]]])
want = {"sgi": 0.3086 * 0.2 + 0.6094 * 0.5 + 0.0820 * 0.8,
        "ntsc": 0.299 * 0.2 + 0.587 * 0.5 + 0.114 * 0.8,
        "hdtv": 0.2126 * 0.2 + 0.7152 * 0.5 + 0.0722 * 0.8,
        "average": 0.5, "max": 0.8, "min": 0.2,
        "magnitude": np.sqrt(0.04 + 0.25 + 0.64 + 0.09),
        "hue": (4 + (0.2 - 0.5) / 0.6) / 6, "saturation": 0.75, "value": 0.8,
        "red": 0.2, "green": 0.5, "blue": 0.8, "alpha": 0.3}
check("all 14 modes present", set(want) == set(CK.LUM_TYPES))
for k, w in want.items():
    check(f"  {k} = {w:.6f}", near(CK.luminance_of(p, k)[0, 0], w, 1e-12), CK.luminance_of(p, k))
check("  Magnitude: RGB uses only three components; single channel takes the absolute value",
      near(CK.luminance_of(p[..., :3], "magnitude")[0, 0], np.sqrt(0.93), 1e-12)
      and near(CK.luminance_of(np.asarray([[[-0.4], [0.3]]]), "magnitude"), [[0.4, 0.3]]))
check("  single-channel layer treated as grey: hdtv / average / max / red are all itself, saturation is 0",
      all(near(CK.luminance_of(np.asarray([[[0.6]]]), k), [[0.6]], 1e-12)
          for k in ("hdtv", "average", "max", "min", "red", "green", "value"))
      and near(CK.luminance_of(np.asarray([[[0.6]]]), "saturation"), [[0.0]]))
check("  2-channel layer pads the third component with 0: average = (a + b)/3, blue = 0",
      near(CK.luminance_of(np.asarray([[[0.3, 0.6]]]), "average"), [[0.3]], 1e-12)
      and near(CK.luminance_of(np.asarray([[[0.3, 0.6]]]), "blue"), [[0.0]]))
check("  the Alpha mode needs 4 channels, errors without; bad mode name errors",
      raises(lambda: CK.luminance_of(p[..., :3], "alpha"), "Alpha")
      and raises(lambda: CK.luminance_of(p, "x"), "Luminance Type"))

sec("Equalize: the five Equalize By × Fit Method")
gv = np.asarray([[0.2, 0.3, 0.6], [0.4, 0.5, 0.4]])               # min 0.2 max 0.6 avg 0.4
gimg = img(C=np.repeat(gv[..., None], 3, -1))


def eq(**kw):
    return L(CK.equalize(gimg, **kw), "C")[..., 0]


check("stretch: min -> Black, max -> White: (c - 0.2)/0.4", near(eq(by="stretch"), (gv - 0.2) / 0.4))
check("  Black 0.1 / White 0.9", near(eq(by="stretch", black=0.1, white=0.9),
                                      (gv - 0.2) / 0.4 * 0.8 + 0.1))
check("  stretch does not read Fit Method / Target (hidden in the panel)",
      near(eq(by="stretch", fit_method="scale", target=9), eq(by="stretch")))
check("min_to_black / shift:c − 0.2;Black 0.1 → c − 0.1",
      near(eq(by="min_to_black"), gv - 0.2) and near(eq(by="min_to_black", black=0.1), gv - 0.1))
check("min_to_black / scale:Black 0.1 → c · 0.1/0.2",
      near(eq(by="min_to_black", fit_method="scale", black=0.1), gv * 0.5))
check("  does not read White / Target", near(eq(by="min_to_black", white=7, target=7), gv - 0.2))
check("max_to_white / shift:c + 0.4;scale:c / 0.6",
      near(eq(by="max_to_white"), gv + 0.4)
      and near(eq(by="max_to_white", fit_method="scale"), gv / 0.6))
check("  White 0.9: shift c + 0.3; does not read Black / Target",
      near(eq(by="max_to_white", white=0.9, black=7, target=7), gv + 0.3))
check("average / shift:Target 0.5 → c + 0.1;scale:c · 0.5/0.4",
      near(eq(by="average", target=0.5), gv + 0.1)
      and near(eq(by="average", fit_method="scale", target=0.5), gv * 1.25))
check("  Target 0.8 -> c + 0.4; does not read Black / White",
      near(eq(by="average", target=0.8, black=7, white=7), gv + 0.4))
check("max_length: c · White/max; does not read Fit Method / Black / Target",
      near(eq(by="max_length"), gv / 0.6)
      and near(eq(by="max_length", white=3.0, fit_method="shift", black=7, target=7), gv * 5))
check("  the five modes differ pairwise (negative control)",
      len({tuple(np.round(eq(by=b, target=0.45, white=0.95).ravel(), 5)) for b in CK.EQ_BY}) == 5)
check("  bad Equalize By / Fit Method -> error",
      raises(lambda: eq(by="x")) and raises(lambda: eq(by="average", fit_method="x")))

sec("Equalize: Luminance Type / channel toggles / Mask / Active")
col = np.asarray([[(0.2, 0.5, 0.8, 0.3), (0.4, 0.1, 0.0, 1.0)]])
cimg = img(C=col)
r = L(CK.equalize(cimg, by="max_to_white", fit_method="scale", lum_type="max"), "C")
check("luminance measures one number, all channels use the same factor (max mode: max 0.8 -> ×1.25), hue unchanged",
      near(r, col * 1.25), r)
r = L(CK.equalize(cimg, by="max_to_white", fit_method="scale", lum_type="red"), "C")
check("  Luminance Type switched to Red: max 0.4 -> ×2.5 (negative control)", near(r, col * 2.5))
r = L(CK.equalize(cimg, by="max_to_white", fit_method="scale", lum_type="alpha"), "C")
check("  Alpha mode: max 1 -> unchanged", near(r, col))
r = L(CK.equalize(cimg, by="max_to_white", fit_method="scale", lum_type="max",
                  red=False, alpha=False), "C")
check("  Red / Alpha off: those two channels unchanged, G / B still multiplied",
      near(r, col * [1, 1.25, 1.25, 1]), r)
r = L(CK.equalize(cimg, by="max_to_white", fit_method="scale", lum_type="max",
                  green=False, blue=False), "C")
check("  Green / Blue off", near(r, col * [1.25, 1, 1, 1.25]))
r = L(CK.equalize(img(C=gv), by="stretch", red=False), "C")[..., 0]
check("  single-channel layer only looks at Red: off means untouched; Green / Blue / Alpha off have no effect",
      near(r, gv) and near(L(CK.equalize(img(C=gv), by="stretch", green=False, blue=False,
                                         alpha=False), "C")[..., 0], (gv - 0.2) / 0.4))
five = np.zeros((2, 3, 5))
five[..., 4] = 0.9
five[..., 0] = [[0.2, 0.4, 0.6]] * 2
r = L(CK.equalize(img(C=five), by="max_to_white", fit_method="scale", lum_type="red",
                  red=False, green=False, blue=False, alpha=False), "C")
check("  5-channel layer: the 5th channel has no toggle and always follows (red max 0.6 -> ×1/0.6); the first four untouched when off",
      near(r[..., 4], np.full((2, 3), 1.5)) and near(r[..., :4], five[..., :4]), r[0, 0])
check("  Mask 0.5: half old, half new; Mask 0: original image",
      near(eq(by="stretch", mask=0.5), (gv + (gv - 0.2) / 0.4) / 2)
      and near(eq(by="stretch", mask=0.0), gv))
act = np.asarray([[0.0, 1.0, 0.5], [1.0, 0.6, 0.0]])            # selects 0.3 0.4 0.5 (0.5 does not count)
ml = np.asarray([[1.0, 0.0, 0.5], [1.0, 1.0, 1.0]])
aimg = img(C=np.repeat(gv[..., None], 3, -1), act=act, ml=ml)
r = L(CK.equalize(aimg, by="stretch", active_layer="act"), "C")[..., 0]
check("  only pixels with Active Layer > 0.5 take part in measuring the range (0.3..0.5); = 0.5 does not count; all pixels are remapped",
      near(r, (gv - 0.3) / 0.2), r)
r = L(CK.equalize(aimg, by="average", target=1.0, active_layer="act"), "C")[..., 0]
check("  the average is also taken only within Active (0.4 -> +0.6)", near(r, gv + 0.6))
check("  nothing selected in Active Layer -> error",
      raises(lambda: CK.equalize(img(C=gv, act=np.zeros((2, 3))), active_layer="act"),
             "Active Layer"))
r = L(CK.equalize(aimg, by="stretch", mask_layer="ml", mask=0.5), "C")[..., 0]
new = (gv - 0.2) / 0.4
check("  Mask Layer multiplies Mask per pixel", near(r, gv + (new - gv) * ml * 0.5))
flat = img(C=np.full((2, 2), 0.3))
check("  constant image stretch (max = min): no scaling, only moved to Black, no inf",
      near(L(CK.equalize(flat, by="stretch", black=0.1), "C")[..., 0], np.full((2, 2), 0.1)))
zero = img(C=np.zeros((2, 2)))
check("  all-black image scale (denominator 0): unchanged, no nan",
      all(near(L(CK.equalize(zero, by=b, fit_method="scale"), "C"), np.zeros((2, 2, 1)))
          for b in ("min_to_black", "max_to_white", "average", "max_length")))
r = CK.equalize(gimg, by="stretch", out_layer="eq")
check("  with a separate Output Layer the source layer is untouched", r.names == ["C", "eq"] and near(L(r, "C")[..., 0], gv))
r = node("PCG_COPEqualize", cop=aimg, equalize_by="max_to_white", fit_method="scale",
         luminance_type="red", black=7.0, white=0.8, target_average=7.0, mask=0.5,
         red=True, green=False, blue=True, alpha=True, active_layer="act",
         mask_layer="ml", out_layer="o")[0]
# max within Active is 0.5 (whole image 0.6) -> ×1.6; mask 0.5 · ml
check("  node: every parameter wired to the right place",
      near(L(r, "o"), np.repeat(gv[..., None], 3, -1)
           + (gv * 0.6 * (ml * 0.5))[..., None] * [1, 0, 1]), L(r, "o")[..., 0])
check("  node defaults: stretch / shift / HDTV / 0 / 1 / all four channels on",
      near(L(node("PCG_COPEqualize", cop=cimg)[0], "C"),
           L(CK.equalize(cimg, by="stretch", lum_type="hdtv"), "C"))
      and not near(L(CK.equalize(cimg, lum_type="hdtv"), "C"),
                   L(CK.equalize(cimg, lum_type="ntsc"), "C")))

# ═════════════════════════════════════════════════════════ Histogram (plot)
sec("Histogram Plot (new node): counts")
H_, W_ = 6, 8
h = np.zeros((H_, W_, 3))
h[..., 0] = np.where(np.arange(W_) < 4, 0.1, 0.6)[None, :]        # 24 of 0.1, 24 of 0.6
h[..., 1] = 1.0                                                   # exactly = Maximum
h[..., 2] = 2.0                                                   # out of range
h[0, 0, 0] = np.nan
himg = img(C=h)
out, cnt = CK.histogram_plot(himg, buckets=4, scale=1.0)
c = L(cnt, "counts")[..., 0]
check("counts image: width = Buckets, height 5; bottom to top R, G, B, A",
      c.shape == (5, 4) and cnt.names == ["counts"], c.shape)
check("  R: bucket 0 has 23 (NaN not counted), bucket 2 has 24; G = Max goes into the last bucket (48)",
      near(c[0], [23, 0, 24, 0]) and near(c[1], [0, 0, 0, 48]), c[:2])
check("  Discard: out-of-range B all dropped; the row for the missing alpha channel is 0; top row col 0 = total pixel count 48",
      near(c[2], [0] * 4) and near(c[3], [0] * 4) and near(c[4], [48, 0, 0, 0]), c[2:])
c2 = L(CK.histogram_plot(himg, buckets=4, outside="clamp")[1], "counts")[..., 0]
check("  Clamp: out-of-range B merged into the last bucket (48); R / G unchanged",
      near(c2[2], [0, 0, 0, 48]) and near(c2[:2], c[:2]))
lowimg = img(C=np.asarray([[-1.0, 0.0, 0.24, 0.25, 0.999, 5.0]]))
cl = L(CK.histogram_plot(lowimg, buckets=4)[1], "counts")[0, :, 0]
cc = L(CK.histogram_plot(lowimg, buckets=4, outside="clamp")[1], "counts")[0, :, 0]
check("  bucket boundary: 0.25 goes to bucket 1; Discard [2,1,0,1]; Clamp merges one at each end [3,1,0,2]",
      near(cl, [2, 1, 0, 1]) and near(cc, [3, 1, 0, 2]), (cl, cc))
cm = L(CK.histogram_plot(lowimg, buckets=2, lo=-1.0, hi=5.0)[1], "counts")[0, :, 0]
check("  Minimum -1 / Maximum 5, 2 buckets: [-1,2) 5, [2,5] 1", near(cm, [5, 1]), cm)
co = L(CK.histogram_plot(himg, buckets=4, red=False)[1], "counts")[..., 0]
check("  Red off: the R row counts are 0, row count unchanged, G unaffected",
      co.shape == (5, 4) and near(co[0], [0] * 4) and near(co[1], c[1]))
co = L(CK.histogram_plot(himg, buckets=4, green=False, blue=False, outside="clamp")[1],
       "counts")[..., 0]
check("  Green / Blue off", near(co[1], [0] * 4) and near(co[2], [0] * 4) and near(co[0], c[0]))
actl = np.zeros((H_, W_))
actl[:, :2] = 1.0
actl[:, 2] = 0.5                                                  # exactly 0.5: counts
actl[:, 3] = 0.49
ca = L(CK.histogram_plot(img(C=h, a=actl), buckets=4, active_layer="a")[1], "counts")[..., 0]
check("  only Active Layer ≥ 0.5 counts (exactly 0.5 counts): 3 cols × 6 rows = 18, R bucket 0 has 17",
      near(ca[4], [18, 0, 0, 0]) and near(ca[0], [17, 0, 0, 0]) and near(ca[1], [0, 0, 0, 18]),
      ca)
rg = np.zeros((2, 2, 4))
rg[..., 3] = [[0.1, 0.1], [0.9, 0.9]]
c4 = L(CK.histogram_plot(img(C=rg), buckets=2)[1], "counts")[..., 0]
check("  RGBA: row 4 is the alpha count; 0 when Alpha is off",
      near(c4[3], [2, 2]) and near(c4[0], [4, 0])
      and near(L(CK.histogram_plot(img(C=rg), buckets=2, alpha=False)[1], "counts")[3, :, 0],
               [0, 0]))
cs_ = L(CK.histogram_plot(img(C=np.asarray([[0.6, 1.1, 1.4]])), buckets=2, lo=0.5, hi=1.5)[1],
        "counts")[0, :, 0]
check("  Minimum 0.5 / Maximum 1.5, 2 buckets: 0.6 -> bucket 0, 1.1 / 1.4 -> bucket 1", near(cs_, [1, 2]), cs_)
o0, c0 = CK.histogram_plot(img(C=h, a=np.zeros((H_, W_))), buckets=4, active_layer="a")
check("  no pixel at all in Active: counts all 0, image all black (no division by zero)",
      near(L(c0, "counts"), np.zeros((5, 4, 1))) and near(L(o0, "histogram"), np.zeros((H_, W_, 3))))
o = L(CK.histogram_plot(img(C=np.asarray([[0.1, 0.5, 0.5, 0.9]])), buckets=3, scale=1.0)[0],
      "histogram")[0, :, 0]
# column centers (x + 0.5)/4 · 3 = 0.375, 1.125, 1.875, 2.625 -> buckets 0 1 1 2; shares 1/4, 2/4, 2/4, 1/4
check("  4 cols 3 buckets: col -> bucket = 0 1 1 2", near(o, [0.25, 0.5, 0.5, 0.25]), o)
c1 = L(CK.histogram_plot(himg, buckets=1)[1], "counts")[..., 0]
check("  Buckets = 1 is legal: everything in range in that one bucket (R 47, G 48, B 0)",
      c1.shape == (5, 1) and near(c1[:, 0], [47, 48, 0, 0, 48]), c1[:, 0])
o5, c5 = CK.histogram_plot(img(C=five), buckets=2)
check("  5-channel layer: only the first 4 channels counted (counts still 5 rows), image has the source's channel count, 5th channel is 0",
      L(c5, "counts").shape == (5, 2, 1) and near(L(c5, "counts")[:, :, 0],
                                                  [[4, 2], [6, 0], [6, 0], [6, 0], [6, 0]])
      and L(o5, "histogram").shape == (2, 3, 5) and near(L(o5, "histogram")[..., 4], np.zeros((2, 3))))
check("  bad Buckets < 1 / Maximum ≤ Minimum / Mode / Outside -> error",
      raises(lambda: CK.histogram_plot(himg, buckets=0), "Buckets")
      and raises(lambda: CK.histogram_plot(himg, buckets=-1), "Buckets")
      and raises(lambda: CK.histogram_plot(himg, lo=1.0, hi=1.0), "Maximum")
      and raises(lambda: CK.histogram_plot(himg, lo=1.0, hi=0.5), "Maximum")
      and raises(lambda: CK.histogram_plot(himg, mode="x"))
      and raises(lambda: CK.histogram_plot(himg, outside="x")))

sec("Histogram Plot: three drawing modes")
o = L(out, "histogram")
# W = 8, 4 buckets: 2 columns per bucket. R shares: bucket 0 = 23/48, bucket 2 = 24/48; G: bucket 3 = 1
wantR = np.repeat([23 / 48, 0, 0.5, 0], 2)
wantG = np.repeat([0, 0, 0, 1.0], 2)
check("colored_bars: same size and channels as the source; each column's color = each channel's share in that bucket (whole column one color)",
      o.shape == (H_, W_, 3) and near(o[..., 0], np.tile(wantR, (H_, 1)))
      and near(o[..., 1], np.tile(wantG, (H_, 1))) and near(o[..., 2], 0 * o[..., 2]), o[0])
o2 = L(CK.histogram_plot(himg, buckets=4, scale=0.5)[0], "histogram")
check("  Scale multiplies the share (0.5 -> halved)", near(o2, o * 0.5))
check("  source layer untouched, result written to the histogram layer", out.names == ["C", "histogram"]
      and np.array_equal(L(out, "C"), L(himg, "C"), equal_nan=True))
o = L(CK.histogram_plot(himg, mode="separate_bars", buckets=4, scale=1.0)[0], "histogram")
check("separate_bars: one grey horizontal band per channel -- bottom two rows R, middle G, top B",
      near(o[0:2], np.tile(wantR[None, :, None], (2, 1, 3)))
      and near(o[2:4], np.tile(wantG[None, :, None], (2, 1, 3)))
      and near(o[4:6], np.zeros((2, W_, 3))), o[..., 0])
o = L(CK.histogram_plot(img(C=rg.repeat(2, 0).repeat(2, 1)), mode="separate_bars",
                        buckets=2, scale=1.0)[0], "histogram")
check("  RGBA: four bands, alpha on top; the output layer's own alpha is 1",
      near(o[3, :, 0], [0.5, 0.5, 0.5, 0.5]) and near(o[0, :, 0], [1, 1, 0, 0])
      and near(o[..., 3], np.ones((4, 4))), o[..., 0])
o = L(CK.histogram_plot(himg, mode="graph", buckets=4, scale=1.0)[0], "histogram")
# row centers (i + 0.5)/6: share 0.5 -> bottom 3 rows; 23/48 -> bottom 2 rows (3rd row center 0.4167 ≤ 0.479: 3 rows)
check("graph: the share sets the bar height (bottom up) -- R bucket 2 share 0.5 -> bottom 3 rows; G bucket 3 full",
      near(o[:, 4, 0], [1, 1, 1, 0, 0, 0]) and near(o[:, 6, 1], np.ones(6))
      and near(o[:, 2, 0], np.zeros(6)) and near(o[:, 0, 1], np.zeros(6)), o[:, 4, 0])
check("  23/48 = 0.479: the 3 rows with centers at or below 0.4167", near(o[:, 0, 0], [1, 1, 1, 0, 0, 0]))
o = L(CK.histogram_plot(himg, mode="graph", buckets=4, scale=0.5)[0], "histogram")
check("  Scale 0.5: bar height halved (0.25 -> bottom 2 rows: centers 0.083, 0.25)", near(o[:, 4, 0], [1, 1, 0, 0, 0, 0]))
check("  the three Mode images differ pairwise (negative control)",
      len({L(CK.histogram_plot(himg, mode=m_, buckets=4, scale=1.0)[0],
             "histogram").tobytes() for m_ in CK.HIST_PLOT_MODES}) == 3)
wide = img(C=np.tile(np.asarray([0.1, 0.1, 0.1, 0.6])[None, :], (1, 1)))
o = L(CK.histogram_plot(wide, buckets=2, scale=1.0)[0], "histogram")[0, :, 0]
check("  col -> bucket: floor((x + 0.5)/W · Buckets) (4 cols 2 buckets: 0.75 0.75 0.25 0.25)",
      near(o, [0.75, 0.75, 0.25, 0.25]), o)
o, cn = node("PCG_COPHistogramPlot", cop=lowimg, mode="colored_bars", buckets=2, min=-1.0,
             max=5.0, outside="clamp", scale=0.6, out_layer="h")
check("  node: two outputs (image / counts), parameters each wired to their own",
      near(L(cn, "counts")[:, :, 0], [[5, 1], [0, 0], [0, 0], [0, 0], [6, 0]])
      and near(L(o, "h")[0, :, 0], [0.5, 0.5, 0.5, 0.1, 0.1, 0.1]), L(o, "h")[0, :, 0])
o, cn = node("PCG_COPHistogramPlot", cop=himg)
check("  node defaults: colored_bars / 256 buckets / 0..1 / discard / Scale 10 / written to histogram",
      L(cn, "counts").shape == (5, 256, 1)
      and near(L(o, "histogram"), L(CK.histogram_plot(himg, buckets=256, scale=10.0)[0],
                                    "histogram")))

# ═════════════════════════════════════════════════════════ Compare (mask)
sec("Compare Mask (new node)")
d = np.asarray([[-0.2, -0.05, 0.0, 0.05, 0.2]])
dimg = img(C=d)


def cmp_(im=dimg, **kw):
    return L(CK.compare_mask(im, **kw), "mask")[0, :, 0]


want = {"equal": [0, 0, 1, 0, 0], "not_equal": [1, 1, 0, 1, 1], "greater": [0, 0, 0, 1, 1],
        "greater_equal": [0, 0, 1, 1, 1], "less": [1, 1, 0, 0, 0], "less_equal": [1, 1, 1, 0, 0]}
for op, w in want.items():
    check(f"tolerance 0, compared with Comparison Value 0: {op} -> {w}", near(cmp_(op=op), w), cmp_(op=op))
check("  Comparison Value set to 0.05: == only hits the 4th (a value stored as float32 must be written as the same number)",
      near(cmp_(op="equal", value=float(np.float32(0.05))), [0, 0, 0, 1, 0]))
want = {"equal": [0, 1, 1, 1, 0], "not_equal": [1, 0, 0, 0, 1], "greater": [0, 1, 1, 1, 1],
        "greater_equal": [0, 1, 1, 1, 1], "less": [1, 1, 1, 1, 0], "less_equal": [1, 1, 1, 1, 0]}
for op, w in want.items():
    check(f"Tolerance 0.1 / Falloff None (hard cut at the tolerance edge): {op} -> {w}",
          near(cmp_(op=op, tolerance=0.1), w), cmp_(op=op, tolerance=0.1))
want = {"equal": [0, 0.5, 1, 0.5, 0], "not_equal": [1, 0.5, 0, 0.5, 1],
        "greater": [0, 0.5, 1, 1, 1], "greater_equal": [0, 0.5, 1, 1, 1],
        "less": [1, 1, 1, 0.5, 0], "less_equal": [1, 1, 1, 0.5, 0]}
for op, w in want.items():
    got = cmp_(op=op, tolerance=0.1, falloff="linear")
    check(f"Tolerance 0.1 / Linear:{op} -> {w} (passing ones always 1, failing ones fall linearly to 0 within the tolerance)",
          near(got, w), got)
d2 = img(C=np.asarray([[-0.075, -0.025, 0.025, 0.075, 0.3]]))
s25, s75 = 0.25 ** 2 * 2.5, 0.75 ** 2 * 1.5                       # smoothstep(0.25), (0.75)
check("Elendt (smoothstep stand-in): == is 0.84375 / 0.15625 at |d| = 0.025 / 0.075",
      near(cmp_(d2, op="equal", tolerance=0.1, falloff="elendt"), [s25, s75, s75, s25, 0]))
check("  the one-sided transition of > follows the same S curve",
      near(cmp_(d2, op="greater", tolerance=0.1, falloff="elendt"), [s25, s75, 1, 1, 1]))
check("  Linear at the same positions is 0.25 / 0.75 (the three Falloffs all differ, negative control)",
      near(cmp_(d2, op="equal", tolerance=0.1, falloff="linear"), [0.25, 0.75, 0.75, 0.25, 0])
      and near(cmp_(d2, op="equal", tolerance=0.1), [1, 1, 1, 1, 0]))
check("  Tolerance 0.2: wider transition band (negative control)",
      near(cmp_(op="greater", tolerance=0.2, falloff="linear"), [0, 0.75, 1, 1, 1]))
check("  with tolerance 0 Falloff has no effect",
      all(near(cmp_(op=op, falloff=f), cmp_(op=op)) for op in CK.CMP_OPS
          for f in ("linear", "elendt")))
A = np.asarray([[(0.1, 0.5, 0.9), (0.5, 0.5, 0.5), (0.9, 0.9, 0.9)]])
B1 = np.full((1, 3), 0.5)
abimg = img(A=A, B=np.repeat(B1[..., None], 3, -1), b1=B1, t=np.asarray([[0.8, 0.0, 0.0]]))
kw = dict(layer_a="A", layer_b="B")
check("Layer B + Components: All needs every channel to pass (>: [0,0,1]); Any needs one ([1,0,1])",
      near(cmp_(abimg, op="greater", components="all", **kw), [0, 0, 1])
      and near(cmp_(abimg, op="greater", components="any", **kw), [1, 0, 1]))
check("  == :All [0,1,0];Any [1,1,0]",
      near(cmp_(abimg, op="equal", components="all", **kw), [0, 1, 0])
      and near(cmp_(abimg, op="equal", components="any", **kw), [1, 1, 0]))
check("  soft mask: All takes the min, Any the max (>, Tolerance 0.8 Linear: first pixel 0.5 / 1)",
      near(cmp_(abimg, op="greater", tolerance=0.8, falloff="linear", components="all", **kw),
           [0.5, 1, 1])
      and near(cmp_(abimg, op="greater", tolerance=0.8, falloff="linear", components="any",
                    **kw), [1, 1, 1]))
check("  single-channel B: compared against every channel of A",
      near(cmp_(abimg, layer_a="A", layer_b="b1", op="greater", components="any"), [1, 0, 1]))
check("  with Layer B given, Comparison Value is not read (greyed out in the panel)",
      near(cmp_(abimg, op="greater", value=99.0, **kw), [0, 0, 1]))
w4 = np.asarray([[(0.1, 0.5, 0.9), (0.5, 0.5, 0.5), (0.9, 0.9, 0.9), (0.6, 0.6, 0.6)]])
check("  width-4 RGB vs RGB (the channel-count check compares channels, not width)",
      near(cmp_(img(A=w4, B=np.full((1, 4, 3), 0.5)), layer_a="A", layer_b="B", op="greater",
                components="any"), [1, 0, 1, 1]))
check("  B channel count mismatch (2 vs 3) -> error",
      raises(lambda: CK.compare_mask(img(A=A, B=A[..., :2]), layer_a="A", layer_b="B"),
             "don't match"))
check("  Tolerance Layer **replaces** Tolerance per pixel: first pixel tolerance 0.8, the rest 0",
      near(cmp_(abimg, op="greater", falloff="linear", tolerance=5.0, tolerance_layer="t",
                components="all", **kw), [0.5, 0, 1]))
t2 = np.stack([np.asarray([[0.8, 0.0, 0.0]]), np.full((1, 3), 9.0)], -1)
check("  a multi-channel Tolerance Layer uses only the first channel",
      near(cmp_(img(A=A, B=np.repeat(B1[..., None], 3, -1), t=t2), op="greater", falloff="linear",
                tolerance_layer="t", components="all", **kw), [0.5, 0, 1]))
eb = img(C=np.asarray([[-0.25, 0.25, -0.2500001, 0.5]]))
check("  None mode includes the tolerance edge: == and > are both 1 at d = ±0.25 (tolerance 0.25), a bit further out is 0",
      near(cmp_(eb, op="equal", tolerance=0.25), [1, 1, 0, 0])
      and near(cmp_(eb, op="greater", tolerance=0.25), [1, 1, 0, 1]))
check("  bad True If / Components / Falloff -> error",
      raises(lambda: cmp_(op="x")) and raises(lambda: cmp_(components="x"))
      and raises(lambda: cmp_(falloff="x")))
r = CK.compare_mask(abimg, **kw)
check("  output is a single-channel mask layer, source layer untouched", L(r, "mask").shape == (1, 3, 1) and near(L(r, "A"), A))
r = node("PCG_COPCompareMask", cop=abimg, layer_a="A", layer_b="B", value=99.0, tolerance=5.0,
         true_if="less", components="any", falloff="linear", tolerance_layer="t",
         out_layer="m")[0]
# <: d sign-flipped = (0.4, 0, -0.4), (0,0,0), (-0.4 ×3); pixel 0 tolerance 0.8: 1, 1, 0.5 -> any 1
check("  node: every parameter wired to the right place", near(L(r, "m")[0, :, 0], [1, 0, 0]), L(r, "m")[0, :, 0])
r = node("PCG_COPCompareMask", cop=abimg, layer_a="A", layer_b="B", tolerance=0.8,
         true_if="less", components="all", falloff="linear", out_layer="m")[0]
check("  node: tolerance / components", near(L(r, "m")[0, :, 0], [0.5, 1, 0.5]), L(r, "m")[0, :, 0])
check("  node defaults: == / All / None / compared with 0, written to mask",
      near(L(node("PCG_COPCompareMask", cop=dimg)[0], "mask")[0, :, 0], [0, 0, 1, 0, 0]))

# ═════════════════════════════════════════════════════════ Mono to RGB
sec("Mono to RGB (new node)")
mv = np.asarray([[0.0, 0.25, 0.5, 1.0, 1.5, -0.5], [9, 9, 9, 9, 9, 9], [9, 9, 9, 9, 9, 9]])
rampl = np.zeros((3, 6, 3))
rampl[1, :, 1] = np.linspace(0, 1, 6)                             # middle row: green from 0 to 1
rampl[0] = rampl[2] = 7.0                                         # top and bottom rows are distractors
mimg = img(C=mv, rl=rampl)
RAMP = "0:1,0,0  1:0,0,1"


def m2r(**kw):
    kw.setdefault("ramp", RAMP)
    return L(CK.mono_to_rgb(mimg, **kw), "C")[0]


def rb(t):
    t = np.asarray(t, np.float64)
    return np.stack([1 - t, 0 * t, t], -1)


check("through the ramp: t = value (Input 0..1), Clamp at End clamps both ends",
      near(m2r(), rb([0, 0.25, 0.5, 1, 1, 0])), m2r())
check("  output is 3 channels (not the channel copied three times: R ≠ B)", m2r().shape == (6, 3) and not near(m2r()[:, 0], m2r()[:, 2]))
check("Repeat: wraps outside the range (1.5 -> 0.5, -0.5 -> 0.5); 1 inside the range is still the ramp end",
      near(m2r(outside="repeat"), rb([0, 0.25, 0.5, 1, 0.5, 0.5])), m2r(outside="repeat"))
check("  Repeat: 1.25 -> 0.25, 2 -> 0 (only exactly 1 stays at the end)",
      near(L(CK.mono_to_rgb(img(C=np.asarray([[1.25, 2.0, 1.0]])), ramp=RAMP, outside="repeat"),
             "C")[0], rb([0.25, 0, 1])))
check("Input Min / Max = −0.5 / 1.5:t = (v + 0.5)/2",
      near(m2r(in_min=-0.5, in_max=1.5), rb([0.25, 0.375, 0.5, 0.75, 1, 0])))
row0 = img(C=mv[:1])
check("Compute Range: uses the image min / max (-0.5..1.5), does not read Input Min / Max",
      near(L(CK.mono_to_rgb(row0, compute_range=True, in_min=5, in_max=6, ramp=RAMP), "C")[0],
           rb([0.25, 0.375, 0.5, 0.75, 1, 0])))
check("Output Min / Max 0.2 / 0.8: ramp 0 / 1 map to these two intensities (color · 0.6 + 0.2)",
      near(m2r(out_min=0.2, out_max=0.8), rb([0, 0.25, 0.5, 1, 1, 0]) * 0.6 + 0.2))
t_raw = np.asarray([0, 0.25, 0.5, 1, 1.5, -0.5])[:, None]
check("Scale by Value: color × the **unclamped** t (keeps brightening to 1.5× at 1.5)",
      near(m2r(scale_by_value=True), rb([0, 0.25, 0.5, 1, 1, 0]) * t_raw)
      and near(m2r(scale_by_value=True)[4], [0, 0, 1.5]))
check("  Output Min / Max applied first, then multiplied",
      near(m2r(scale_by_value=True, out_min=0.2, out_max=0.8),
           (rb([0, 0.25, 0.5, 1, 1, 0]) * 0.6 + 0.2) * t_raw))
check("Ramp interpolation constant: everything with t < 1 falls on the first key",
      near(m2r(ramp_mode="constant")[:3], [[1, 0, 0]] * 3))
r = m2r(ramp_layer="rl", ramp="0:9,9,9 1:9,9,9")
check("Ramp Layer: samples colors horizontally from that layer's **middle row** (t -> green), does not read the Ramp parameter",
      near(r, np.stack([0 * t_raw[:, 0], np.clip(t_raw[:, 0], 0, 1), 0 * t_raw[:, 0]], -1)), r)
rl1 = np.zeros((3, 6))
rl1[1] = [0, 1, 0, 0, 0, 1]
r = L(CK.mono_to_rgb(img(C=mv, rl=rl1), ramp_layer="rl"), "C")[0]
# t = 0.25 -> position 1.25: 1·0.75 + 0·0.25; t = 0.5 -> position 2.5: 0
check("  Ramp Layer interpolates linearly between pixels; a single-channel ramp layer is treated as grey",
      near(r, np.repeat(np.asarray([0, 0.75, 0, 1, 1, 0])[:, None], 3, 1)), r[:, 0])
rl5 = np.zeros((5, 3, 3))
rl5[2, :, 0] = [0, 0.5, 1]                                        # the middle of 5 rows is row 2
r = L(CK.mono_to_rgb(img(C=np.zeros((5, 3)) + [[0, 0.5, 1]], rl=rl5), ramp_layer="rl"), "C")
check("  Ramp Layer height 5: uses row 2", near(r[0, :, 0], [0, 0.5, 1]) and near(r[..., 1:], 0 * r[..., 1:]))
rl2 = np.zeros((3, 3, 2))
rl2[1, :, 0] = [0, 0.5, 1]
rl2[1, :, 1] = 7.0
r = L(CK.mono_to_rgb(img(C=np.zeros((3, 3)) + [[0, 0.5, 1]], rl=rl2), ramp_layer="rl"), "C")
check("  a 2-channel Ramp Layer is treated as grey (first channel)", near(r[0], np.repeat(np.asarray([[0], [0.5], [1]]), 3, 1)))
rl1b = np.zeros((3, 6, 4))
rl1b[1, :, 0] = [0, 1, 0, 0, 0, 1]
rl1b[1, :, 3] = 5.0                                               # alpha does not enter the color
r = L(CK.mono_to_rgb(img(C=np.asarray([[0.9, 1.0, 2.0]]).repeat(3, 0)[:, [0, 1, 2, 0, 1, 2]],
                         rl=rl1b), ramp_layer="rl", outside="repeat"), "C")[0, :3, 0]
# t = 0.9 -> position 4.5: 0·0.5 + 1·0.5; t = 1 -> end 1; t = 2 -> Repeat to 0 -> first pixel 0
check("  the last segment of the Ramp Layer is interpolated too; with Repeat t = 1 takes the end pixel; an RGBA ramp layer uses only RGB",
      near(r, [0.5, 1, 0]), r)
check("  Input Max = Input Min: t is 0 (no division by zero)", near(m2r(in_min=1.0, in_max=1.0), rb([0] * 6)))
check("  bad Outside Range -> error", raises(lambda: m2r(outside="x")))
r = CK.mono_to_rgb(mimg, ramp=RAMP, out_layer="rgb")
check("  with a separate Output Layer the source layer is untouched", near(L(r, "C")[..., 0], mv) and L(r, "rgb").shape == (3, 6, 3))
r = node("PCG_COPMonoToRGB", cop=mimg, in_min=-0.5, in_max=1.5, out_min=0.2, out_max=0.8,
         scale_by_value=True, outside="repeat", ramp=RAMP, ramp_mode="linear", out_layer="o")[0]
tt = (mv[0] + 0.5) / 2
check("  node: every parameter wired to the right place", near(L(r, "o")[0], (rb(tt) * 0.6 + 0.2) * tt[:, None]))
r = node("PCG_COPMonoToRGB", cop=row0, compute_range=True, ramp_layer="", ramp_mode="constant",
         ramp=RAMP)[0]
check("  node: compute_range / ramp_mode", near(L(r, "C")[0, :4], [[1, 0, 0]] * 4)
      and near(L(r, "C")[0, 4], [0, 0, 1]))
check("  node: ramp_layer", near(L(node("PCG_COPMonoToRGB", cop=mimg, ramp_layer="rl")[0],
                                 "C")[0, :, 1], np.clip(t_raw[:, 0], 0, 1)))
check("  node defaults: 0..1 black-white ramp -> grey = the clamped value",
      near(L(node("PCG_COPMonoToRGB", cop=mimg)[0], "C")[0],
           np.repeat(np.clip(mv[0], 0, 1)[:, None], 3, 1)))

# ═════════════════════════════════════════════════════════ Mono to HeightField
sec("Mono to HeightField (new node)")
r = CK.mono_to_height(mimg, height_scale=10.0, height_offset=-2.0)
check("height = value × Scale + Offset (multiply first, then add), written to the height layer; source layer untouched",
      near(L(r, "height")[..., 0], mv * 10 - 2, 1e-5) and near(L(r, "C")[..., 0], mv))
check("  not (value + Offset) × Scale (negative control)", not near(L(r, "height")[..., 0], (mv - 2) * 10, 1e-3))
check("  multi-channel layer takes channel 0, output is single-channel",
      L(CK.mono_to_height(img(C=A), height_scale=2.0), "height").shape == (1, 3, 1)
      and near(L(CK.mono_to_height(img(C=A), height_scale=2.0), "height")[0, :, 0],
               A[0, :, 0] * 2))
r = node("PCG_COPMonoToHeightField", cop=mimg, height_scale=3.0, height_offset=1.0,
         out_layer="hh")[0]
check("  node: scale / offset / out_layer", near(L(r, "hh")[..., 0], mv * 3 + 1, 1e-5))
check("  node defaults: Scale 1 / Offset 0 -> height layer = original value",
      near(L(node("PCG_COPMonoToHeightField", cop=mimg)[0], "height")[..., 0], mv))

# ═════════════════════════════════════════════════════════ Mono to ID(cast)
sec("Segment by Value: cast (the Cast of Mono to ID)")
sv = RNG.random((6, 6))
simg = img(C=sv)
for kw in (dict(), dict(mode="step", step=0.25), dict(mode="unique", connected=False)):
    a, na = node("PCG_COPSegmentByValue", cop=simg, **kw)
    b, nb = OLD_SV.segment_by_value(simg, "C", kw.get("mode", "bins"), 8,
                                    kw.get("step", 0.1), kw.get("connected", True), 8, "id")
    check(f"the old three modes bit-identical to before the change {kw or '{}'}", same_layers(a, b) and na == nb, na)
cv = np.asarray([[-1.7, 0.2, 1.9, 3.0, 3.0, -0.4]])
r, n = SV.segment_by_value(img(C=cv), mode="cast")
check("cast: truncates towards 0 (-1.7 -> -1, 1.9 -> 1, -0.4 -> 0), no renumbering; count = number of distinct ids 4",
      near(L(r, "id")[0, :, 0], [-1, 0, 1, 3, 3, 0]) and n == 4, (L(r, "id")[0, :, 0], n))
ru, _ = SV.segment_by_value(img(C=cv), mode="unique", connected=False)
check("  unique mode renumbers (negative control: result differs)", not near(L(ru, "id")[0, :, 0], [-1, 0, 1, 3, 3, 0]))
r2, n2 = SV.segment_by_value(img(C=cv), mode="cast", bins=99, step=5.0, connected=True,
                             connectivity=8)
check("  cast does not read bins / step / connected (hidden in the panel): the two adjacent 3s are neither split nor merged with anything",
      near(L(r2, "id"), L(r, "id")) and n2 == n)
check("  node menu: cast appended at the end, the first three unchanged",
      M["PCG_COPSegmentByValue"].INPUT_TYPES()["required"]["mode"][0]
      == ["bins", "step", "unique", "cast"])
r, n = node("PCG_COPSegmentByValue", cop=img(C=cv), mode="cast", out_layer="k")
check("  node: mode = cast / out_layer", near(L(r, "k")[0, :, 0], [-1, 0, 1, 3, 3, 0]) and n == 4)
check("  bad Mode -> error", raises(lambda: SV.segment_by_value(simg, mode="x")))

# ═════════════════════════════════════════════════════════ Registration / panel
sec("Registration: mapping table, icons, menus")
import copernicus_map as CM                             # noqa: E402
want = {"Despill": "PCG_COPDespill", "Equalize": "PCG_COPEqualize",
        "Histogram": "PCG_COPHistogramPlot", "Compare": "PCG_COPCompareMask",
        "Mono to RGB": "PCG_COPMonoToRGB", "Mono to HeightField": "PCG_COPMonoToHeightField",
        "Chroma Key": "PCG_COPChromaKey", "Illegal Pixel": "PCG_COPIllegalPixel",
        "Random RGB": "PCG_COPRandom", "Mono to ID": "PCG_COPSegmentByValue"}
check("copernicus_map points to the nodes with Houdini semantics, and the nodes are all registered",
      all(CM.M[k][1] == v and v in M for k, v in want.items()),
      {k: CM.M[k][1] for k in want if CM.M[k][1] != want[k]})
js = open(os.path.join(os.path.dirname(sys.modules["comfyui_pcg"].__file__), "web", "pcg_icons.js"), encoding="utf-8").read()
check("all six new nodes have icons, and the icon functions all exist",
      all(f'{n}: "{g_}"' in js and f"\n  {g_}(c) {{" in js for n, g_ in
          (("COPDespill", "despill"), ("COPEqualize", "equalize"),
           ("COPHistogramPlot", "hist_plot"), ("COPCompareMask", "cmp_mask"),
           ("COPMonoToRGB", "mono_rgb"), ("COPMonoToHeightField", "mono_hf"))))
from comfyui_pcg.panel_specs import SPECS              # noqa: E402
for n, key, toks in (("PCG_COPChromaKey", "method", ["distance", "chromakey", "channel_separation"]),
                     ("PCG_COPChromaKey", "interpolation", list(CK.ROLLOFFS)),
                     ("PCG_COPIllegalPixel", "mode", ["replace"] + list(CK.ILLEGAL_MODES)),
                     ("PCG_COPIllegalPixel", "detect", list(CK.ILLEGAL_DETECT)),
                     ("PCG_COPIllegalPixel", "rule", list(CK.ILLEGAL_RULES)),
                     ("PCG_COPRandom", "range_values", list(PX.RANDOM_RANGES)),
                     ("PCG_COPRandom", "color_model", list(PX.RANDOM_MODELS)),
                     ("PCG_COPEqualize", "equalize_by", list(CK.EQ_BY)),
                     ("PCG_COPEqualize", "fit_method", list(CK.EQ_FIT)),
                     ("PCG_COPEqualize", "luminance_type", list(CK.LUM_TYPES)),
                     ("PCG_COPHistogramPlot", "mode", list(CK.HIST_PLOT_MODES)),
                     ("PCG_COPHistogramPlot", "outside", list(CK.HIST_OUTSIDE)),
                     ("PCG_COPCompareMask", "true_if", list(CK.CMP_OPS)),
                     ("PCG_COPCompareMask", "components", list(CK.CMP_COMPONENTS)),
                     ("PCG_COPCompareMask", "falloff", list(CK.CMP_FALLOFF)),
                     ("PCG_COPMonoToRGB", "outside", list(CK.MONO_OUTSIDE)),
                     ("PCG_COPSegmentByValue", "mode", ["bins", "step", "unique", "cast"])):
    have = M[n].INPUT_TYPES()["required"][key][0]
    check(f"{n}.{key}: node menu = {len(toks)} tokens, the panel spec gives each a label",
          have == toks and list(SPECS[n]["inputs"][key]["menu"]) == toks, have)

sec("Panel self-check")
for k in ("PCG_COPChromaKey", "PCG_COPDespill", "PCG_COPIllegalPixel", "PCG_COPRandom",
          "PCG_COPEqualize", "PCG_COPHistogramPlot", "PCG_COPCompareMask", "PCG_COPMonoToRGB",
          "PCG_COPMonoToHeightField", "PCG_COPSegmentByValue"):
    it = M[k].INPUT_TYPES()
    bad_ = PANEL.check_layout(k, it)
    widgets = [w for w, v in it["required"].items() if v[0] != "COPIMAGE"]
    check(f"{k}: spec self-check clean, every widget is in order", not bad_
          and set(SPECS[k]["order"]) == {w for w in widgets if w != "cop"}, bad_
          or sorted(set(widgets) - set(SPECS[k]["order"]) - {"cop"}))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
