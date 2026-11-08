"""
Completing Copernicus batch A: the per-pixel bundle (pixel.py + the 24 nodes in nodes_cop2.py).

━━ Criteria (everything that can be written in closed form is)
  · color: default parameters identity bit for bit; exposure +1 = x2; contrast around pivot (pivot unchanged);
    gamma and Levels in the same direction; saturation 0 = Rec.709 luminance, and luminance unchanged at any saturation;
    HSV round trip error 1e-12, hue rotated 360° returns to the original; alpha unchanged; mask blends proportionally
  · channels: mono->rgba->rgb->mono round trip; too few channels raises; split / join round trip bit for bit;
    swizzle constants and reordering
  · vectors: dot / cross match numpy on random vectors; cross ⟂ both inputs; normalize gives length
    1; reflect preserves length; rotate_3d preserves length and 90° around z turns x into y; tangent->world->
    tangent round trip; a tangent-space vector (0,0,1) transformed to world is N
  · functions produce no nan; logic equal has a tolerance; mask combine screen <= 1 and >= max
  · premultiply -> unpremultiply round trip (where alpha > 0), alpha = 0 gives 0
  · tone mapping monotonic, within [0,1], reinhard_extended maps white to 1
  · keying: key-color pixels alpha = 0, far colors = 1; after despill G <= mean of max(R,B)
  · layers: rename / copy / delete / keep; merge resamples when resolutions differ
  · Align: stretch to the same resolution bit for bit; fit preserves aspect ratio
  · Wrangle: @C = @C*2; @u @v are pixel centers; new layers created automatically; errors include the translated code
  · Random: id mode same id same value, reproducible bit for bit; values in [min, max)
  · Convert Depth: z -> distance -> z round trip; center pixel z = distance; the factor at the edges is
    √(1+x²+y²); disparity = 1/z; z component of position = z
  · comparison table: every one of the 357 Houdini nodes has a status, referenced nodes are all registered
"""
import math
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo.cop import CopImage                 # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
from comfyui_pcg.geo.cop import levels as LV             # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def L(img, name):
    return PX.getn(img, name)


def mk(**lay):
    first = next(iter(lay.values()))
    H, W = first.shape[:2]
    return CopImage(W, H, {k: np.asarray(v, np.float64) for k, v in
                           lay.items()})


rng = np.random.default_rng(3)
H, W = 24, 32
rgba = rng.random((H, W, 4)) * 1.5 - 0.2
rgba[..., 3] = rng.random((H, W))
im = mk(C=rgba, m=rng.random((H, W, 1)))

# ═══════════════════════════════════════════════════════ color
sec("color correction")
o = PX.color_correct(im, "C")
check("default parameters identity bit for bit", np.array_equal(L(o, "C"), rgba))
o = PX.color_correct(im, "C", exposure=1.0)
check("exposure +1 = RGB x 2, alpha unchanged",
      np.allclose(L(o, "C")[..., :3], rgba[..., :3] * 2)
      and np.array_equal(L(o, "C")[..., 3], rgba[..., 3]))
o = PX.color_correct(mk(C=np.full((2, 2, 3), 0.18)), "C", contrast=3.0,
                     pivot=0.18)
check("contrast around pivot: the value at pivot is unchanged", np.allclose(L(o, "C"), 0.18))
g = PX.color_correct(mk(C=np.full((1, 1, 1), 0.25)), "C", gamma=2.0)
lv = LV.levels(mk(C=np.full((1, 1, 1), 0.25)), gamma=2.0)
check("gamma 2 = 0.25^(1/2) = 0.5, same direction as Levels (brighter)",
      abs(L(g, "C")[0, 0, 0] - 0.5) < 1e-12
      and abs(L(g, "C")[0, 0, 0] - float(np.asarray(lv.need("C"))[0, 0, 0]))
      < 1e-6)
y709 = (rgba[..., :3] * np.asarray(LV.LUMA_709)).sum(-1)
for s_ in (0.0, 0.4, 2.5):
    o = PX.color_correct(im, "C", saturation=s_)
    yo = (L(o, "C")[..., :3] * np.asarray(LV.LUMA_709)).sum(-1)
    check(f"saturation {s_}: Rec.709 luminance unchanged" + (" (0 = all three channels equal the luminance)"
                                          if s_ == 0 else ""),
          np.allclose(yo, y709, atol=1e-12) and (
              s_ != 0 or np.allclose(L(o, "C")[..., 0], y709)))
pos = rng.random((H, W, 3))
check("RGB->HSV->RGB round trip 1e-12",
      np.allclose(PX.hsv_to_rgb(PX.rgb_to_hsv(pos)), pos, atol=1e-12))
hv = PX.rgb_to_hsv(np.array([[[1.0, 0.0, 0.5]]]))
check(f"hue in [0, 1): hue of magenta (1, 0, 0.5) = 330° ({hv[0, 0, 0] * 360:.1f}°)",
      abs(hv[0, 0, 0] * 360 - 330) < 1e-9
      and float(PX.rgb_to_hsv(pos)[..., 0].min()) >= 0)
o = PX.color_correct(mk(C=pos), "C", hue_shift=360.0)
check("hue rotated 360° returns to the original", np.allclose(L(o, "C"), pos, atol=1e-12))
o = PX.color_correct(mk(C=np.array([[[1.0, 0, 0]]])), "C", hue_shift=120.0)
check("pure red rotated 120° = pure green", np.allclose(L(o, "C"), [[[0, 1, 0]]], atol=1e-12))
o = PX.color_correct(im, "C", exposure=1.0, mask_layer="m")
check("mask blends proportionally: out = a + (ax2 - a)·m",
      np.allclose(L(o, "C")[..., :3], rgba[..., :3] * (1 + L(im, "m"))))
check("  the mask layer itself is not corrected", np.array_equal(L(o, "m"), L(im, "m")))
o = PX.invert(im, "C")
check("Invert: 1 - x, alpha not inverted by default",
      np.allclose(L(o, "C")[..., :3], 1 - rgba[..., :3])
      and np.array_equal(L(o, "C")[..., 3], rgba[..., 3]))
o = PX.clamp(im, "C", 0.2, 0.7)
check("Clamp into [0.2, 0.7]", float(L(o, "C").min()) >= 0.2 - 1e-7
      and float(L(o, "C").max()) <= 0.7 + 1e-7)
err("Clamp min > max", lambda: PX.clamp(im, "C", 1, 0), "Min")

# ═══════════════════════════════════════════════════════ channels
sec("channels")
mono = rng.random((H, W, 1))
im1 = mk(C=mono)
o = PX.channel_convert(im1, "C", "mono_to_rgba", "x", alpha=0.3)
x = L(o, "x")
check("mono->rgba: all three channels are the original value, alpha = the given value",
      x.shape[2] == 4 and np.allclose(x[..., :3], mono)
      and np.allclose(x[..., 3], 0.3))
o2 = PX.channel_convert(PX.channel_convert(o, "x", "rgba_to_rgb", "y"), "y",
                        "rgb_to_mono_average", "z")
check("mono->rgba->rgb->mono (average) round trip", np.allclose(L(o2, "z"), mono))
uv = rng.random((H, W, 2))
o = PX.channel_convert(mk(C=uv), "C", "uv_to_rgb", "c", fill=0.25)
check("uv→rgb:rg = uv,b = Fill", np.allclose(L(o, "c")[..., :2], uv)
      and np.allclose(L(o, "c")[..., 2], 0.25))
err("too few channels raises (rgb converted as rgba)",
    lambda: PX.channel_convert(mk(C=pos), "C", "rgba_to_rgb"), "needs at least 4")
o = PX.channel_split(im, "C")
check("split: four layers C.r C.g C.b C.a", all(f"C.{c}" in o for c in "rgba"))
o2 = PX.channel_join(o, "C.r C.g C.b C.a", "J")
check("  split -> join round trip (float32 storage)",
      np.allclose(L(o2, "J"), rgba, atol=1e-6))
err("join with more than 4 channels raises",
    lambda: PX.channel_join(o, "C C.r", "x"), "at most 4")
o = PX.swizzle(im, "C", "bgr1", "s")
s_ = L(o, "s")
check("swizzle bgr1: channel reorder + constant 1",
      np.allclose(s_[..., 0], rgba[..., 2], atol=1e-6)
      and np.allclose(s_[..., 2], rgba[..., 0], atol=1e-6)
      and np.all(s_[..., 3] == 1))
err("swizzle of a nonexistent channel", lambda: PX.swizzle(im1, "C", "g"), "can't take")
err("swizzle with an unrecognized character", lambda: PX.swizzle(im, "C", "q"), "Unrecognized")

# ═══════════════════════════════════════════════════════ vectors
sec("vectors")
A = rng.standard_normal((H, W, 3))
B = rng.standard_normal((H, W, 3))
iv = mk(A=A, B=B)
d = L(PX.vector_math(iv, "A", "B", "dot", "d"), "d")[..., 0]
check("dot = Σ a·b", np.allclose(d, (A * B).sum(-1), atol=1e-5))
c = L(PX.vector_math(iv, "A", "B", "cross", "c"), "c")
check("cross = np.cross, and perpendicular to both inputs",
      np.allclose(c, np.cross(A, B), atol=1e-5)
      and float(np.abs((c * A).sum(-1)).max()) < 1e-4)
n = L(PX.vector_math(iv, "A", "", "normalize", "n"), "n")
check("normalize gives length 1", np.allclose(np.linalg.norm(n, axis=-1), 1,
                                     atol=1e-6))
r = L(PX.vector_math(iv, "A", "B", "reflect", "r"), "r")
check("reflect preserves length", np.allclose(np.linalg.norm(r, axis=-1),
                                    np.linalg.norm(A, axis=-1), atol=1e-5))
dv = L(PX.vector_math(iv, "A", "0 0 0", "divide", "q"), "q")
check("division by 0 gives 0 (no inf / nan)", np.all(dv == 0))
rot = L(PX.vector_transform(iv, "A", "rotate_3d", rotate="10 20 30",
                            out_layer="R"), "R")
check("rotate_3d preserves length", np.allclose(np.linalg.norm(rot, axis=-1),
                                      np.linalg.norm(A, axis=-1), atol=1e-5))
ex = mk(V=np.broadcast_to(np.array([1.0, 0, 0]), (2, 2, 3)).copy())
check("  rotating 90° around z turns +x into +y",
      np.allclose(L(PX.vector_transform(ex, "V", "rotate_3d",
                                        rotate="0 0 90"), "V"),
                  [0, 1, 0], atol=1e-7))
check("rotate_2d 90°:(1,0) → (0,1)",
      np.allclose(L(PX.vector_transform(ex, "V", "rotate_2d", angle=90),
                    "V")[..., :2], [0, 1], atol=1e-7))
Nn = rng.standard_normal((H, W, 3))
Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
it = mk(V=A, N=Nn)
w_ = PX.vector_transform(it, "V", "tangent_to_world", out_layer="Vw")
t_ = PX.vector_transform(w_, "Vw", "world_to_tangent", out_layer="Vt")
check("tangent -> world -> tangent round trip", np.allclose(L(t_, "Vt"), A,
                                                   atol=1e-5))
z_ = mk(V=np.broadcast_to(np.array([0, 0, 1.0]), (H, W, 3)).copy(), N=Nn)
check("  tangent-space (0,0,1) transformed to world is N",
      np.allclose(L(PX.vector_transform(z_, "V", "tangent_to_world"), "V"),
                  Nn, atol=1e-6))
basis = mk(V=np.array([[[1.0, 0, 0], [0, 1.0, 0]]]),
           N=np.array([[[0, 0, 1.0], [0, 0, 1.0]]]))
tw = L(PX.vector_transform(basis, "V", "tangent_to_world"), "V")
check("  handedness: with N = +z, tangent-space x -> world +x, y -> world +y (B = N x T, right-handed)",
      np.allclose(tw, [[[1, 0, 0], [0, 1, 0]]], atol=1e-9))
err("cross needs 3 channels", lambda: PX.vector_math(mk(A=uv), "A", "A", "cross"),
    "needs 3 channels")

# ═══════════════════════════════════════════════════════ functions / logic / masks
sec("functions / logic / mask combine")
wild = mk(C=np.array([[[-2.0], [0.0], [3.0]]]))
bad = [f for f in PX.FUNCTIONS
       if not np.all(np.isfinite(L(PX.function(wild, "C", f, 0.0, 0.0),
                                   "C")))]
check("20 functions produce no nan / inf on negatives and 0 (extreme parameters a = b = 0)", not bad,
      bad)
check("frac(-2.25) = 0.75, mod(-1, 3) = 2 (same sign as the divisor)",
      abs(L(PX.function(mk(C=np.full((1, 1, 1), -2.25)), "C", "frac"),
            "C")[0, 0, 0] - 0.75) < 1e-12
      and abs(L(PX.function(mk(C=np.full((1, 1, 1), -1.0)), "C", "mod", 3.0),
                "C")[0, 0, 0] - 2.0) < 1e-12)
eq = mk(C=np.array([[[0.1 + 0.2], [0.3]]]))
check("equal has a tolerance: 0.1+0.2 == 0.3", np.all(L(PX.logic(eq, "C", "0.3",
                                                       "equal"), "mask")
                                             == 1))
lg = L(PX.logic(im, "C", "0.5", "greater", out_layer="g"), "g")[..., 0]
check("multi-channel comparison: 1 only if it holds for all channels",
      np.array_equal(lg, (rgba > 0.5).all(-1).astype(float)))
ma, mb = rng.random((H, W, 1)), rng.random((H, W, 1))
mm = mk(a=ma, b=mb)
sc = L(PX.mask_combine(mm, "a b", "screen", "s"), "s")
check("screen = 1 - (1-a)(1-b), between max(a,b) and 1",
      np.allclose(sc, 1 - (1 - ma) * (1 - mb), atol=1e-6)
      and np.all(sc >= np.maximum(ma, mb) - 1e-6) and np.all(sc <= 1))
check("union = max,intersect = min",
      np.allclose(L(PX.mask_combine(mm, "a b", "union", "u"), "u"),
                  np.maximum(ma, mb), atol=1e-6)
      and np.allclose(L(PX.mask_combine(mm, "a b", "intersect", "i"), "i"),
                      np.minimum(ma, mb), atol=1e-6))

# ═══════════════════════════════════════════════════ premultiply / invalid / tone / keying
sec("premultiply / invalid pixels / tone mapping / keying")
p0 = rng.random((H, W, 4)) + 0.05
p0[0, 0, 3] = 0.0
pm = PX.premultiply(mk(C=p0), "C", "premultiply")
up = L(PX.premultiply(pm, "C", "unpremultiply"), "C")
ok = p0[..., 3] > 0
check("premultiply -> unpremultiply round trip (where alpha > 0)",
      np.allclose(up[ok][:, :3], p0[ok][:, :3], atol=1e-5))
check("  where alpha = 0 unpremultiply gives 0, not nan", np.all(up[0, 0, :3] == 0))
nanimg = mk(C=np.array([[[np.nan], [np.inf], [-np.inf], [-3.0], [0.5]]]))
o, rep = PX.illegal_pixel(nanimg, "C", 0.0, 1.0, 0.0, True)
check("nan / ±inf replaced, negatives clamped to 0; report counts correct",
      np.allclose(L(o, "C")[..., 0], [[0, 1, 0, 0, 0.5]])
      and rep["C"] == {"nan": 1, "posinf": 1, "neginf": 1, "negative": 1})
hdr = mk(C=np.linspace(0, 50, 200).reshape(1, 200, 1).repeat(3, 2))
for op in PX.TONEMAPS[:4]:
    y = L(PX.tone_map(hdr, "C", op), "C")[0, :, 0]
    check(f"{op}: monotonic non-decreasing, within [0, 1]",
          np.all(np.diff(y) >= -1e-9) and y.min() >= 0 and y.max() <= 1)
ext = L(PX.tone_map(mk(C=np.full((1, 1, 3), 4.0)), "C", "reinhard_extended",
                    white=4.0), "C")
check("reinhard_extended: white maps to 1", np.allclose(ext, 1.0))
gs = np.zeros((4, 4, 3))
gs[..., 1] = 0.9
gs[0, 0] = [0.8, 0.2, 0.3]
gs[0, 1] = [0.4, 0.7, 0.3]                  # foreground with green spill
k = PX.chroma_key(mk(C=gs), "C", "0 1 0", 0.1, 0.05, 1.0)
al = L(k, "alpha")[..., 0]
check("keying: key color alpha = 0, far color (red) = 1", al[3, 3] == 0 and al[0, 0] == 1)
kc = L(k, "C")
check("  after despill G does not exceed the mean of R, B",
      np.all(kc[..., 1] <= (kc[..., 0] + kc[..., 2]) / 2 + 1e-6))
gs2 = gs.copy()
gs2[1, 1] = [0.0, 0.45, 0.0]                # shadow on the green screen
check("  chroma only: shadows on the green screen (dark green) are keyed out too",
      L(PX.chroma_key(mk(C=gs2), "C", "0 1 0", 0.1, 0.05), "alpha")[1, 1, 0]
      < 0.05)

# ═══════════════════════════════════════════════════════ layers
sec("layer management / merge / align")
o = PX.layer_edit(im, "rename", "C=color")
check("rename", "color" in o and "C" not in o)
o = PX.layer_edit(im, "copy", "C=c2")
check("copy", "c2" in o and "C" in o)
check("delete / keep", PX.layer_edit(im, "delete", "m").names == ["C"]
      and PX.layer_edit(im, "keep", "m").names == ["m"])
err("no layers left after keep raises (i.e. a mistyped layer name)",
    lambda: PX.layer_edit(im, "keep", ""), "No layers left")
small = mk(D=rng.random((12, 16, 1)))
mg = PX.layer_merge(im, small, "", "b_")
check("merge: B's layers resampled to A's resolution, with prefix",
      "b_D" in mg and mg.xres == W and mg.yres == H)
check("  with overwrite off, A's same-named layers are kept",
      np.array_equal(L(PX.layer_merge(im, mk(C=rng.random((H, W, 1))), "C",
                                      "", False), "C"), L(im, "C")))
al_ = PX.align(im, mk(X=np.zeros((H, W, 1))), "stretch")
check("Align stretch to the same resolution: pixel values unchanged", np.allclose(L(al_, "C"),
                                                  L(im, "C"), atol=1e-6))
sq = mk(C=np.ones((10, 10, 1)))
af = PX.align(sq, mk(X=np.zeros((10, 20, 1))), "fit")
col = L(af, "C")[5, :, 0]
check("Align fit: square image into a wide frame, aspect preserved, black on both sides",
      col[0] < 0.01 and col[-1] < 0.01 and col[10] > 0.99)

# ═══════════════════════════════════════════════════════ Wrangle
sec("Wrangle")
o = PX.wrangle(im, "@C = @C * 2")
check("@C = @C * 2", np.allclose(L(o, "C"), rgba * 2, atol=1e-5))
o = PX.wrangle(mk(C=np.zeros((4, 8, 1))), "@uu = @u\n@vv = @v")
check("@u @v are the 0~1 pixel-center coordinates, v up (row 0 = bottom)",
      np.allclose(L(o, "uu")[0, :, 0], (np.arange(8) + 0.5) / 8)
      and np.allclose(L(o, "vv")[:, 0, 0], (np.arange(4) + 0.5) / 4))
o = PX.wrangle(im, "@mask = where(@C.x > 0.5, 1.0, 0.0)")
check("new layer created automatically, @C.x takes a component, where instead of if",
      np.array_equal(L(o, "mask")[..., 0], (rgba[..., 0] > 0.5)
                     .astype(float)))
o = PX.wrangle(im, "@C[:, 0] += 1")
check("in-place component modification is written back too", np.allclose(L(o, "C")[..., 0], rgba[..., 0] + 1,
                                      atol=1e-5))
err("error raises with the translated code", lambda: PX.wrangle(im, "@C = nope"),
    "translated Python")

# ═══════════════════════════════════════════════════════ fill / vignette / random
sec("fill / vignette / random")
o = PX.fill(im, "C", "1 0 0 1", "m")
check("Fill blends softly by mask", np.allclose(L(o, "C")[..., 0],
                                     rgba[..., 0] + (1 - rgba[..., 0])
                                     * L(im, "m")[..., 0], atol=1e-6))
v = L(PX.vignette(mk(C=np.ones((21, 21, 3))), "C", 0.5, 0.6, 0.3), "C")
check("vignette: center unchanged, corners pushed down to 1 - amount",
      abs(v[10, 10, 0] - 1) < 1e-9 and abs(v[0, 0, 0] - 0.5) < 1e-6)
ids = np.repeat(np.arange(6), 4).reshape(4, 6).astype(float)
ri = PX.random_layer(mk(id=ids), "id", "id", 3, 7, out_layer="r")
rv = L(ri, "r")
same = all(np.allclose(rv[ids == k], rv[ids == k][0]) for k in range(6))
check("id mode: same id same color", same)
ri2 = PX.random_layer(mk(id=ids), "id", "id", 3, 7, out_layer="r")
check("  same seed reproducible bit for bit, a different seed changes it",
      np.array_equal(L(ri2, "r"), rv)
      and not np.array_equal(L(PX.random_layer(mk(id=ids), "id", "id", 3, 8,
                                               out_layer="r"), "r"), rv))
rp = L(PX.random_layer(None, "pixel", channels=1, seed=1, lo=2, hi=5,
                       xres=64, yres=64), "random")
check("pixel mode creates a new image without an input; values in [min, max), mean ≈ 3.5",
      rp.shape == (64, 64, 1) and rp.min() >= 2 and rp.max() < 5
      and abs(rp.mean() - 3.5) < 0.05)

# ═══════════════════════════════════════════════════════ depth
sec("Convert Depth")
Hd, Wd = 30, 40
zz = 2.0 + rng.random((Hd, Wd))
dimg = mk(depth=zz)
dist = L(PX.convert_depth(dimg, "depth", "z_depth", "distance", 60.0), "depth")
back = L(PX.convert_depth(mk(depth=dist[..., 0]), "depth", "distance",
                          "z_depth", 60.0), "depth")
check("z -> distance -> z round trip", np.allclose(back[..., 0], zz, atol=1e-5))
x_, y_, Lr = PX._ray_len(Wd, Hd, 60.0)
check(f"  the factor is √(1+x²+y²): {Lr[0, 0]:.3f} at the corner (FOV 60°, over 20% difference at the edges)",
      np.allclose(dist[..., 0] / zz, Lr, atol=1e-5) and Lr[0, 0] > 1.2)
dp = L(PX.convert_depth(dimg, "depth", "z_depth", "disparity"), "depth")
check("disparity = 1/z", np.allclose(dp[..., 0], 1 / zz, atol=1e-6))
ps = L(PX.convert_depth(dimg, "depth", "z_depth", "position", 60.0,
                        out_layer="P"), "P")
check("z component of position = z, x/z symmetric on both sides of the center column",
      np.allclose(ps[..., 2], zz, atol=1e-5)
      and np.allclose(ps[:, 0, 0] / zz[:, 0], -ps[:, -1, 0] / zz[:, -1],
                      atol=1e-5))
from comfyui_pcg.geo import render as RD, build as BD        # noqa: E402
from comfyui_pcg.geo.core import POINT as _PT                # noqa: E402
_g = BD.grid(6.0, 6.0, 4, 4)
_P = np.asarray(_g.get(_PT, "P"), np.float64)
_P[:, 1] += 0.3 * np.sin(_P[:, 0])                         # not a plane
_g.set(_PT, "P", _P.astype(np.float32))
_cam = RD.camera(None, "perspective", eye=(0.5, 3.0, 2.5), target=(0, 0, 0),
                 fov=55.0, xres=48, yres=36)
_rp = RD.render(_g, _cam, passes=("depth", "mask", "position"))
_z = np.asarray(_rp.need("depth"), np.float64)[..., 0]
_m = np.asarray(_rp.need("mask"), np.float64)[..., 0] > 0.5
_true = np.linalg.norm(np.asarray(_rp.need("P"), np.float64)
                       - _cam["eye"], axis=-1)
_conv = L(PX.convert_depth(CopImage(48, 36, {"depth": _z[..., None],
                                             "mask": _m[..., None]
                                             .astype(float)}),
                           "depth", "z_depth", "distance", 55.0,
                           mask_layer="mask"), "depth")[..., 0]
_d = float(np.abs(_conv - _true)[_m].max() / _true[_m].max())
check(f"independent check: rendering one with Render Pass (non-planar, at an angle), z -> distance matches the true distance computed from the position layer"
      f" (relative diff {_d:.1e})", _d < 1e-5 and _m.sum() > 300)
nz = L(PX.convert_depth(dimg, "depth", "z_depth", "normalized"), "depth")
check("normalized maps min / max to 0~1", abs(nz.min()) < 1e-6
      and abs(nz.max() - 1) < 1e-6)
err("normalized as input needs near < far",
    lambda: PX.convert_depth(dimg, "depth", "normalized", "z_depth"), "near")

# ═══════════════════════════════════════════════════════ torch / nodes
sec("torch / nodes")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    ti = CopImage(W, H, {"C": rgba.astype(np.float32)}).to_device("cpu")
    o = PX.color_correct(ti, "C", exposure=1, saturation=0.5)
    check("[torch] input on torch, output still on torch, matches numpy",
          o.backend.is_torch and np.allclose(
              L(o, "C"), L(PX.color_correct(mk(C=rgba), "C", exposure=1,
                                            saturation=0.5), "C"),
              atol=1e-5))
from comfyui_pcg import nodes_cop2 as N2                  # noqa: E402
check(f"all {len(N2.NODE_CLASS_MAPPINGS)} batch A nodes registered, all under PCG/cop",
      all(k in MAP and MAP[k].CATEGORY == "PCG/cop"
          for k in N2.NODE_CLASS_MAPPINGS))
r = MAP["PCG_COPWrangle"]().run(im, "@C = 1 - @C", 0)
r = tuple(r["result"]) if isinstance(r, dict) else r
check("node runs (Wrangle)", np.allclose(L(r[0], "C"), 1 - rgba, atol=1e-5))

# ═══════════════════════════════════════════════════════ comparison table
sec("Copernicus comparison table")
import copernicus_map as CM                              # noqa: E402
st = {}
for k, (s_, ref) in CM.M.items():
    st[s_] = st.get(s_, 0) + 1
check(f"every one of the 357 Houdini nodes has a status: {st}", len(CM.M) == 357)
miss = [(k, ref) for k, (s_, ref) in CM.M.items()
        if s_ in ("done", "new", "platform") and ref.startswith("PCG_")
        and ref not in MAP]
check("referenced nodes marked done / new / platform are all registered", not miss, miss[:5])
stale = [(k, ref) for k, (s_, ref) in CM.M.items()
         if s_ == "todo" and ref in MAP]
check("those marked todo are not done yet (if done they should be changed to new)", not stale, stale[:5])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
