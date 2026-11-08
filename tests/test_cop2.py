"""
COP batch two: Transform / Levels / Morph / SDF from Mask.

Criteria are picked the same way as in the earlier batches -- **prove what can be proven, measure what can't and write the numbers down**:

    - bit-exact: rotate 90° == np.rot90, integer-pixel translate == np.roll, flip, crop,
      tile, Levels identity, Sharpen amount=0
    - analytic closed form: edge detection on `f = a·x + b·y` gives gx exactly equal to a; Laplacian on
      `f = a·x²` exactly equals 2a
    - brute-force cross-check: exact EDT against O(N²) per-point nearest distance, error must be 0
    - cross-module identity: dilation by a disk of radius r == `EDT ≤ r`, bit-exact
    - mathematical properties: morphological duality (erode(a) == -dilate(-a)), opening idempotent,
      extensivity, separability of the box structuring element
    - negative controls: every criterion must be able to **catch** the error it is meant to catch. JFA error without the extra passes,
      rotation shear without aspect correction, endpoint-aligned resampling are all run here as counterexamples
"""
import os
import sys
# Package root: first search upwards from this file's location, fall back to the old sandbox path if not found.
# These suites are now the **only** copy (the sandbox gets recycled), so paths can no longer be hard-coded
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np
from comfyui_pcg.geo.cop import (CopImage, generate as G, filters as F,
                                 transform as T, levels as LV, morph as MP,
                                 sdf as SD, backend as BK)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


RNG = np.random.default_rng(0)
XP = BK.NUMPY


def L(img, name="C"):
    return np.asarray(img.need(name))


def img_rand(w=64, h=64, c=3, seed=0):
    r = np.random.default_rng(seed)
    return CopImage(w, h, {"C": r.random((h, w, c)).astype(np.float32)})


# ══════════════════════════════════════════════════════════════ Transform
print("═" * 28, "Transform")

A = img_rand(64, 64, 3, 1)
a = L(A)

r90 = L(T.transform(A, rotate=90.0))
# v up + counterclockwise lands on the array as exactly one direction of np.rot90. **Bit-exact**, because
# cos/sin of 90° are snapped to exact 0/±1, so sample coordinates land on integers
which = ("rot90(+1)" if np.array_equal(r90, np.rot90(a, 1)) else
         "rot90(-1)" if np.array_equal(r90, np.rot90(a, -1)) else "neither")
check("rotate 90° is **bit-identical** to np.rot90", which != "neither", which)
check("rotating 90° four times returns the original (bit-exact)",
      np.array_equal(L(T.transform(T.transform(T.transform(
          T.transform(A, rotate=90.0), rotate=90.0), rotate=90.0),
          rotate=90.0)), a))
check("rotate 180° == flip both ways (bit-exact)",
      np.array_equal(L(T.transform(A, rotate=180.0)), a[::-1, ::-1]))

# Negative control: without snapping cos(90°) = 6.12e-17 and every pixel gets touched by interpolation
c90, s90 = T._cos_sin(90.0)
check("_cos_sin(90) gives exact 0 and 1", (c90, s90) == (0.0, 1.0),
      (c90, s90))
check("negative control: np.cos(radians(90)) is **not** 0",
      float(np.cos(np.radians(90.0))) != 0.0,
      float(np.cos(np.radians(90.0))))
c30, s30 = T._cos_sin(30.0)
check("non-multiples of 90° go through trig as usual",
      abs(c30 - np.cos(np.radians(30))) < 1e-15 and abs(s30 - 0.5) < 1e-15)
c45, _ = T._cos_sin(45.0 + 1e-6)
check("snapping only takes deviations within 1e-9, doesn't swallow 45°",
      abs(c45 - np.cos(np.radians(45.0 + 1e-6))) < 1e-15)

for dx in (1, 5, 17, -3):
    check(f"translate {dx} pixels (wrap) == np.roll, bit-exact",
          np.array_equal(L(T.transform(A, translate=(dx, 0),
                                       units="pixels", border="wrap")),
                         np.roll(a, dx, axis=1)))
check("vertical translate likewise (v up, so +y moves up)",
      np.array_equal(L(T.transform(A, translate=(0, 7), units="pixels",
                                   border="wrap")), np.roll(a, 7, axis=0)))
check("1.0 in uv units == one full width (translating a full width wraps back to the original)",
      np.array_equal(L(T.transform(A, translate=(1.0, 0), units="uv",
                                   border="wrap")), a))
check("2.0 in normalized units == one full width",
      np.array_equal(L(T.transform(A, translate=(2.0, 0),
                                   units="normalized", border="wrap")), a))
check("doing nothing is the identity (bit-exact)",
      np.array_equal(L(T.transform(A)), a))

# Aspect correction: after rotating 90° on a non-square image, **circles in the picture stay circles**
NX, NY = 128, 64
sq = G.shape(NX, NY, "circle", radius=0.3)
rot = T.transform(sq, rotate=90.0, layers="mask")
m = np.asarray(rot.need("mask"))[:, :, 0] > 0.5
ys, xs = np.nonzero(m)
# After short-side normalization a circle of r=0.3 has diameter 0.6·min(W,H) = 38.4 pixels, the same in both directions
ext_x, ext_y = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
check("rotate 90° on a non-square image: the circle isn't squashed into an ellipse",
      abs(ext_x - ext_y) <= 1, f"{ext_x} x {ext_y}")
check("  and the diameter is exactly 0.6·short side", abs(ext_y - 0.6 * NY) <= 1.5,
      f"{ext_y} vs {0.6 * NY}")

# Negative control: rotating 45° directly in uv shears. Work out by hand the difference between the two approaches for the same point
u = np.array([0.9, 0.5])                      # a point in the middle of the right side
th = np.radians(45.0)
R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
naive = R @ (u - 0.5)                          # wrong: rotate directly in uv
s = min(NX, NY)
q = (u - 0.5) * np.array([NX / s, NY / s])     # right: convert to aspect first
good = (R @ q) * np.array([s / NX, s / NY])
check("negative control: rotating directly in uv and with aspect correction are **really different**",
      float(np.abs(naive - good).max()) > 0.1,
      f"difference {float(np.abs(naive - good).max()):.3f} uv")

# Round trip: rotate +θ then -θ, the interior should come back (edges get polluted by the border, only the middle is checked).
#
# **Use a smooth image, not white noise.** The first version tried `img_rand` and went red with max error 0.57
# -- that's not a bug: every pixel of white noise sits at the Nyquist frequency, bilinear resampling can't keep
# it in the first place, losing half the energy over two round trips is **correct** behavior. Resampling criteria only hold on band-limited signals.
# This tripped us twice in this batch (the float32/float64 cross-check below is the same pitfall).
sy_, sx_ = np.mgrid[0:64, 0:64] / 64.0
SMOOTH = CopImage(64, 64, {"C": np.stack(
    [0.5 + 0.4 * np.sin(6 * sx_) * np.cos(5 * sy_),
     0.5 + 0.3 * np.cos(4 * sx_ + 3 * sy_),
     sx_ * 0.6 + sy_ * 0.3], -1).astype(np.float32)})
sm = L(SMOOTH)
rt = L(T.transform(T.transform(SMOOTH, rotate=23.0), rotate=-23.0))
cen = (slice(12, 52), slice(12, 52))
check("rotate +23° then -23°, the middle region comes back (the cost of two bilinear passes)",
      float(np.abs(rt[cen] - sm[cen]).max()) < 0.02,
      f"max {float(np.abs(rt[cen] - sm[cen]).max()):.5f}")
check("  and the mean error is an order of magnitude smaller",
      float(np.abs(rt[cen] - sm[cen]).mean()) < 0.003,
      f"mean {float(np.abs(rt[cen] - sm[cen]).mean()):.6f}")
check("negative control: the same round trip on white noise has a much larger error (resampling criteria need band-limited signals)",
      float(np.abs(L(T.transform(T.transform(A, rotate=23.0),
                                 rotate=-23.0))[cen] - a[cen]).max()) > 0.2)

# Scale: enlarge 2× then shrink back. **Only the central quarter can be checked** -- resolution doesn't change,
# enlarging 2× crops away three quarters of the outer picture, and after shrinking back that part is filled by the border,
# it can't come back anyway. The first version compared 12..52; the 0.12 "error" was entirely in the cropped ring
z = L(T.transform(T.transform(SMOOTH, scale=(2.0, 2.0)), scale=(0.5, 0.5)))
keep = (slice(20, 44), slice(20, 44))
check("enlarge 2× then shrink by 0.5, the central region that **wasn't cropped** matches",
      float(np.abs(z[keep] - sm[keep]).max()) < 0.03,
      f"max {float(np.abs(z[keep] - sm[keep]).max()):.5f}")
check("negative control: the cropped outer part really doesn't come back (filled by the border)",
      float(np.abs(z[:8] - sm[:8]).max()) > 0.05,
      f"max {float(np.abs(z[:8] - sm[:8]).max()):.4f}")
err("scale = 0 raises on the spot", lambda: T.transform(A, scale=(0.0, 1.0)),
    "cannot be 0")
err("wrong border raises and lists the options",
    lambda: T.transform(A, border="mirror"), "Border must be one of")
err("wrong filter raises", lambda: T.transform(A, filter="bicubic"),
    "Filter must be one of")
err("wrong units raises", lambda: T.transform(A, translate=(1, 0),
                                        units="inches"), "Units must be one of")

# closest sampling: same as bilinear for integer translations (weights all 0/1)
check("with integer translation closest and bilinear give the same result",
      np.array_equal(L(T.transform(A, translate=(4, 3), units="pixels",
                                   filter="closest", border="wrap")),
                     L(T.transform(A, translate=(4, 3), units="pixels",
                                   filter="bilinear", border="wrap"))))

# layers filter
two = CopImage(32, 32, {"C": RNG.random((32, 32, 3)).astype(np.float32),
                        "mask": RNG.random((32, 32, 1)).astype(np.float32)})
tw = T.transform(two, translate=(5, 0), units="pixels", layers="C")
check("layers not listed in layers are passed through as is (**the same array**, not even copied)",
      L(tw, "mask") is two.need("mask"))
check("the listed layer really changed",
      not np.array_equal(L(tw, "C"), L(two, "C")))
err("a nonexistent layer name in layers raises on the spot",
    lambda: T.transform(two, layers="nope"), "no 'nope' layer")

print("═" * 28, "Flip / Crop / Tile")

fl = T.flip(A, horizontal=True)
check("horizontal flip bit-exact", np.array_equal(L(fl), a[:, ::-1]))
check("vertical flip bit-exact", np.array_equal(L(T.flip(A, False, True)), a[::-1]))
check("flipping twice returns the original", np.array_equal(L(T.flip(fl, horizontal=True)), a))
check("flipping both == rotate 180°",
      np.array_equal(L(T.flip(A, True, True)),
                     L(T.transform(A, rotate=180.0))))

cr = T.crop(A, 8, 12, 16, 20)
check("crop resolution is (xres, yres)", cr.res == (16, 20), cr.res)
check("crop content bit-identical", np.array_equal(L(cr), a[12:32, 8:24]))
check("origin at bottom left: y=0 takes row 0",
      np.array_equal(L(T.crop(A, 0, 0, 8, 8)), a[:8, :8]))
pad = T.crop(A, -4, -4, 72, 72, border="black")
check("negative coordinates + larger resolution = pad outwards", pad.res == (72, 72), pad.res)
check("  the padding is 0", float(np.abs(np.asarray(pad.need("C"))[:4]).max()) == 0)
check("  the middle block is still the original (bit-exact)",
      np.array_equal(np.asarray(pad.need("C"))[4:68, 4:68], a))
check("clamp padding copies the edge pixels",
      np.array_equal(np.asarray(T.crop(A, -3, 0, 67, 64,
                                       border="clamp").need("C"))[:, 0],
                     a[:, 0]))

tl = T.tile(A, 3, 2)
check("resolution after tiling", tl.res == (192, 128), tl.res)
check("tiling is a bit-exact copy",
      all(np.array_equal(np.asarray(tl.need("C"))[
          j * 64:(j + 1) * 64, i * 64:(i + 1) * 64], a)
          for j in range(2) for i in range(3)))
tm = T.tile(A, 2, 1, mirror_u=True)
check("mirror_u: the second copy is mirrored",
      np.array_equal(np.asarray(tm.need("C"))[:, 64:], a[:, ::-1]))
check("  the first copy is still as is", np.array_equal(np.asarray(tm.need("C"))[:, :64], a))
check("after mirror the seam is symmetric left/right (hence seamless)",
      np.array_equal(np.asarray(tm.need("C"))[:, 63],
                     np.asarray(tm.need("C"))[:, 64]))
check("tiles=1x1 is the original", np.array_equal(L(T.tile(A, 1, 1)), a))

print("═" * 28, "Distort")

# Constant field = pure translation, can be cross-checked against transform
H, W = 64, 64
fld = CopImage(W, H, {"C": np.broadcast_to(
    np.array([3.0 / W, 0.0], np.float32), (H, W, 2)).copy()})
d1 = L(T.distort(A, fld, amount=1.0, units="uv", border="wrap"))
d2 = L(T.transform(A, translate=(-3, 0), units="pixels", border="wrap"))
check("constant vector field == the opposite translation (definition of inverse mapping)", np.array_equal(d1, d2))
check("amount=0 is the identity (bit-exact)",
      np.array_equal(L(T.distort(A, fld, amount=0.0)), a))
zero = CopImage(W, H, {"C": np.zeros((H, W, 2), np.float32)})
check("zero field is the identity", np.array_equal(L(T.distort(A, zero, amount=5.0)), a))
err("field with only 1 channel raises and says it needs 2",
    lambda: T.distort(A, CopImage(W, H, {"C": np.zeros((H, W, 1),
                                                       np.float32)})),
    "warping needs 2")
small = CopImage(32, 32, {"C": np.zeros((32, 32, 2), np.float32)})
check("field with a different resolution is conformed automatically (no error)",
      T.distort(A, small, amount=1.0).res == (64, 64))

print("═" * 28, "Levels")

B = img_rand(32, 32, 3, 2)
b = L(B)
check("default parameters are a **bit-exact** identity", np.array_equal(L(LV.levels(B)), b))
check("clamp_input off, rest default is also a bit-exact identity",
      np.array_equal(L(LV.levels(B, clamp_input=False)), b))
inv = L(LV.levels(B, out_black=1.0, out_white=0.0))
check("Out Black=1 / Out White=0 is an inversion",
      float(np.abs(inv - (1.0 - b)).max()) < 1e-6,
      float(np.abs(inv - (1.0 - b)).max()))
# Monotonicity can't be compared with argsort: clamp_input squashes everything < in_black to the same value,
# and the order of ties no longer corresponds to the original order. What's tested is "non-decreasing", not "same permutation"
_ord = np.argsort(b.ravel(), kind="stable")
check("Levels is monotonically non-decreasing (clamp creates ties, so permutations can't be compared)",
      bool(np.all(np.diff(L(LV.levels(B, 0.1, 0.9, 2.2)).ravel()[_ord])
                  >= -1e-7)))
check("  without clamping it's **strictly** monotonic (no ties)",
      bool(np.all(np.diff(L(LV.levels(B, 0.1, 0.9, 2.2,
                                      clamp_input=False)).ravel()[_ord])
                  > 0)))
g = L(LV.levels(B, gamma=2.2))
check("gamma > 1 **brightens** (consistent with Photoshop, not pow(x,gamma))",
      float(g.mean()) > float(b.mean()),
      f"{float(b.mean()):.4f} -> {float(g.mean()):.4f}")
check("  and it's exactly x^(1/2.2)",
      float(np.abs(g - b ** (1 / 2.2)).max()) < 1e-6)

# No clamping + negative numbers: sign must be kept, no nan
NEG = CopImage(16, 16, {"C": ((RNG.random((16, 16, 1)) - 0.5)
                              * 4).astype(np.float32)})
n0 = L(NEG)
ng = L(LV.levels(NEG, gamma=2.2, clamp_input=False))
check("without clamping negative numbers don't become nan", bool(np.isfinite(ng).all()))
check("  and the sign is kept (sign(t)·|t|^g)",
      bool(np.all(np.sign(ng) == np.sign(n0))))
check("  on the positive half-axis same as plain power",
      float(np.abs(ng[n0 > 0] - n0[n0 > 0] ** (1 / 2.2)).max()) < 1e-6)
check("negative control: numpy really gives nan for fractional powers of negative bases",
      bool(np.isnan(np.float64(-0.3) ** np.float64(0.4545))))
check("with clamp_input on, negative numbers are clamped to 0",
      float(L(LV.levels(NEG, gamma=2.2)).min()) >= 0.0)
check("clamp_output clamps to [out_black, out_white]",
      float(L(LV.levels(NEG, clamp_output=True)).max()) <= 1.0
      and float(L(LV.levels(NEG, clamp_output=True)).min()) >= 0.0)
err("in_white == in_black raises", lambda: LV.levels(B, 0.5, 0.5), "cannot equal")
err("gamma <= 0 raises", lambda: LV.levels(B, gamma=0.0), "must be > 0")

check("invert(pivot=1) == 1 − x",
      float(np.abs(L(LV.invert(B)) - (1 - b)).max()) < 1e-7)
check("invert(pivot=0) == negation (swaps inside and outside of an SDF)",
      float(np.abs(L(LV.invert(B, 0.0)) + b).max()) < 1e-7)
check("clamp_layer really clamps",
      float(L(LV.clamp_layer(NEG, -0.5, 0.5)).max()) <= 0.5
      and float(L(LV.clamp_layer(NEG, -0.5, 0.5)).min()) >= -0.5)

for n in (2, 3, 4, 8):
    q = np.round(L(LV.quantize(B, steps=n)), 6)
    vals = sorted(set(q.ravel().tolist()))
    check(f"quantize steps={n} gives exactly {n} values, with **both endpoints present**",
          len(vals) == n and abs(vals[0]) < 1e-6 and abs(vals[-1] - 1) < 1e-6,
          vals if len(vals) < 6 else f"{len(vals)} values")
check("steps=1 is a flat color", len(set(L(LV.quantize(B, steps=1)).ravel().tolist()))
      == 1)
check("negative control: the floor(x·N)/N formulation **can't reach** 1.0",
      abs(float(np.floor(np.float64(1.0) * 4) / 4) - 1.0) > 1e-12 or
      len(set(np.round(np.floor(np.linspace(0, 1, 999) * 4) / 4,
                       6).tolist())) == 5,
      "the floor formulation adds an extra level / misses an endpoint")
qs = np.round(L(LV.quantize(NEG, steps=4, lo=0.0, hi=1.0)), 5)
check("values outside the range aren't clamped, quantized on the same grid",
      float(qs.min()) < -0.3 and
      float(np.abs(np.diff(sorted(set(qs.ravel().tolist())))).min() - 1 / 3)
      < 1e-4, f"min {float(qs.min()):.4f}")
err("steps < 1 raises", lambda: LV.quantize(B, steps=0), "at least 1")
err("hi == lo raises", lambda: LV.quantize(B, lo=1.0, hi=1.0), "cannot equal")

# Remap
check("a 1-component ramp is a **per-channel** lookup, channel count unchanged",
      L(LV.remap(B, "0:0 1:1")).shape == b.shape)
check("  identity ramp is the identity",
      float(np.abs(L(LV.remap(B, "0:0 1:1")) - b).max()) < 1e-6)
check("  reversed ramp is an inversion",
      float(np.abs(L(LV.remap(B, "0:1 1:0")) - (1 - b)).max()) < 1e-6)
rc = LV.remap(B, "0:0,0,1  1:1,0,0")
check("multi-component ramps take the 'reduce to a scalar, then look up' path",
      L(rc).shape == (32, 32, 3))
check("  with t from channel 0, the looked-up red component == b[...,0]",
      float(np.abs(L(rc)[:, :, 0] - b[:, :, 0]).max()) < 1e-6)
rl = LV.remap(B, "0:0,0,0  1:1,1,1", t_from="luminance")
lum = (b * np.array(LV.LUMA_709, np.float64)).sum(-1)
check("t_from=luminance uses Rec.709 weights",
      float(np.abs(L(rl)[:, :, 0] - lum).max()) < 1e-6)
check("in_min/in_max stretch the range (that's how SDFs get colored)",
      float(np.abs(L(LV.remap(NEG, "0:0 1:1", in_min=-2.0, in_max=2.0))
                   - (n0 + 2) / 4).max()) < 1e-6)
err("in_max == in_min raises", lambda: LV.remap(B, in_min=1, in_max=1),
    "cannot equal")
err("wrong t_from raises", lambda: LV.remap(B, t_from="alpha"), "T From must be one of")

# Fit / stats / luminance
f01 = L(LV.fit(NEG))
check("fit stretches the measured range to [0,1]",
      abs(float(f01.min())) < 1e-6 and abs(float(f01.max()) - 1) < 1e-6)
check("fit keeps the order (it's an affine transform)",
      np.array_equal(np.argsort(f01.ravel(), kind="stable"),
                     np.argsort(n0.ravel(), kind="stable")))
CST = CopImage(8, 8, {"C": np.full((8, 8, 1), 0.7, np.float32)})
check("a constant layer doesn't divide by 0, gives out_min as is",
      float(np.abs(L(LV.fit(CST, 0.25, 1.0)) - 0.25).max()) < 1e-7)
fp = L(LV.fit(B, per_channel=True))
check("with per_channel **every channel** is stretched fully",
      all(abs(float(fp[:, :, k].min())) < 1e-6
          and abs(float(fp[:, :, k].max()) - 1) < 1e-6 for k in range(3)))
fg = L(LV.fit(B, per_channel=False))
check("negative control: without per-channel only **one** channel touches 0 and 1",
      sum(abs(float(fg[:, :, k].min())) < 1e-6 for k in range(3)) < 3)
st = LV.stats(B)
check("stats' overall min/max agree with numpy",
      abs(st["min"] - float(b.min())) < 1e-7
      and abs(st["max"] - float(b.max())) < 1e-7)
check("length of stats per channel == channel count", len(st["cmin"]) == 3)
lm = LV.luminance(B)
check("luminance is 1 channel", np.asarray(lm.need("lum")).shape == (32, 32, 1))
check("  values are Rec.709 weighted",
      float(np.abs(np.asarray(lm.need("lum"))[:, :, 0] - lum).max()) < 1e-6)
check("  a 1-channel layer just takes channel 0, no error",
      float(np.abs(np.asarray(LV.luminance(NEG).need("lum"))
                   - n0).max()) < 1e-7)
check("luminance keeps the existing layers", "C" in lm)

print("═" * 28, "morphology")

M0 = img_rand(40, 32, 1, 3)
m0 = L(M0)


def mo(**kw):
    return L(MP.morph(M0, **kw))


for shape in ("box", "disc"):
    check(f"[{shape}] dilate ≥ original ≥ erode (extensive/anti-extensive)",
          bool((mo(op="dilate", radius=2, shape=shape) >= m0).all()
               and (mo(op="erode", radius=2, shape=shape) <= m0).all()))
    NEGI = CopImage(40, 32, {"C": -m0})
    check(f"[{shape}] duality: erode(a) == -dilate(-a), **bit-exact**",
          np.array_equal(mo(op="erode", radius=2, shape=shape),
                         -np.asarray(MP.morph(NEGI, op="dilate", radius=2,
                                              shape=shape).need("C"))))
    o1 = MP.morph(M0, op="open", radius=2, shape=shape)
    o2 = MP.morph(o1, op="open", radius=2, shape=shape)
    check(f"[{shape}] opening is **idempotent** (open(open(x)) == open(x), bit-exact)",
          np.array_equal(L(o1), L(o2)))
    c1 = MP.morph(M0, op="close", radius=2, shape=shape)
    check(f"[{shape}] closing is idempotent too",
          np.array_equal(L(c1), L(MP.morph(c1, op="close", radius=2,
                                           shape=shape))))
    check(f"[{shape}] gradient == dilate − erode",
          float(np.abs(mo(op="gradient", radius=2, shape=shape)
                       - (mo(op="dilate", radius=2, shape=shape)
                          - mo(op="erode", radius=2, shape=shape))).max())
          < 1e-7)
    check(f"[{shape}] radius=0 is the identity (bit-exact)",
          np.array_equal(mo(op="erode", radius=0, shape=shape), m0))

# Separability of box: cross-checked against brute-force enumeration of rectangular windows
r = 3
pad = np.pad(m0[:, :, 0], r, mode="edge")
brute_min = np.min(np.stack([pad[r + dy:r + dy + 32, r + dx:r + dx + 40]
                             for dy in range(-r, r + 1)
                             for dx in range(-r, r + 1)]), 0)
check("box's two 1D passes == brute-force enumeration of the whole rectangular window (bit-exact)",
      np.array_equal(mo(op="erode", radius=r, shape="box")[:, :, 0],
                     brute_min))
disc_min = np.min(np.stack([pad[r + dy:r + dy + 32, r + dx:r + dx + 40]
                            for dy, dx in MP._disc_offsets(r)]), 0)
check("disc agrees with brute-force enumeration of the disk window (bit-exact)",
      np.array_equal(mo(op="erode", radius=r, shape="disc")[:, :, 0],
                     disc_min))
check("negative control: disc and box results **really differ** (otherwise the separability check would be meaningless)",
      not np.array_equal(disc_min, brute_min))
check("disc offsets are dx²+dy² ≤ r² (r=1 is a cross, 5 of them)",
      len(MP._disc_offsets(1)) == 5, len(MP._disc_offsets(1)))
check("a disk of r=3 has 29 offsets", len(MP._disc_offsets(3)) == 29,
      len(MP._disc_offsets(3)))

# Practical consequences of border
FULL = CopImage(16, 16, {"C": np.ones((16, 16, 1), np.float32)})
check("all-1 image: erosion with clamp border doesn't change it",
      float(np.asarray(MP.morph(FULL, op="erode", radius=2,
                                border="clamp").need("C")).min()) == 1.0)
check("negative control: with black border erosion eats inwards from all four edges",
      float(np.asarray(MP.morph(FULL, op="erode", radius=2,
                                border="black").need("C")).min()) == 0.0)
err("wrong op raises", lambda: MP.morph(M0, op="thin"), "Op must be one of")
err("wrong shape raises", lambda: MP.morph(M0, shape="cross"), "Shape must be one of")
err("negative radius raises", lambda: MP.morph(M0, radius=-1), "cannot be negative")
err("radius above the limit raises, and points to SDF",
    lambda: MP.morph(M0, radius=100), "COP SDF from Mask")

print("═" * 28, "edge detection")

N = 32
gy, gx = np.mgrid[0:N, 0:N]
SA, SB = 0.037, -0.021
RAMP = CopImage(N, N, {"C": (SA * gx + SB * gy)[:, :, None]})
IN = (slice(1, -1), slice(1, -1))
for meth, tol in (("sobel", 1e-15), ("prewitt", 1e-15), ("scharr", 1e-15)):
    e = MP.edge(RAMP, method=meth, components=True)
    ex = np.asarray(e.need("edge_gx"))[IN + (0,)]
    ey = np.asarray(e.need("edge_gy"))[IN + (0,)]
    check(f"[{meth}] on an analytic slope gx is **exactly** the slope",
          float(np.abs(ex - SA).max()) < tol,
          f"{float(np.abs(ex - SA).max()):.2e}")
    check(f"[{meth}] gy likewise", float(np.abs(ey - SB).max()) < tol,
          f"{float(np.abs(ey - SB).max()):.2e}")
    mg = np.asarray(e.need("edge"))[IN + (0,)]
    check(f"[{meth}] magnitude == hypot(a, b)",
          float(np.abs(mg - np.hypot(SA, SB)).max()) < 1e-15)
    dr = np.asarray(e.need("edge_dir"))[IN + (0,)]
    check(f"[{meth}] direction angle == atan2(b, a)",
          float(np.abs(dr - np.arctan2(SB, SA)).max()) < 1e-12)

ratio = float(np.abs(np.asarray(
    MP.edge(RAMP, method="sobel", scale=8.0).need("edge"))[IN + (0,)]
    / np.hypot(SA, SB)).max())
check("negative control: without dividing by the normalization factor sobel's values are exactly 8 times larger",
      abs(ratio - 8.0) < 1e-9, f"{ratio:.6f}")

QUAD = CopImage(N, N, {"C": (0.5 * gx ** 2 - 0.25 * gy ** 2)[:, :, None]})
lp = np.asarray(MP.edge(QUAD, method="laplacian").need("edge"))[IN + (0,)]
check("Laplacian on f = a·x² + b·y² is **exactly** 2a + 2b",
      float(np.abs(lp - (2 * 0.5 + 2 * -0.25)).max()) == 0.0,
      float(np.abs(lp - 0.5).max()))
check("edges of a constant image are 0",
      float(np.abs(np.asarray(MP.edge(CST).need("edge"))).max()) < 1e-9)
COL = CopImage(N, N, {"C": np.stack(
    [0.5 + 0.0 * gx, SA * gx, 0.5 + 0.0 * gx], -1)})
check("multi-channel gradients are **per channel** (magnitude = that channel when only one channel varies)",
      float(np.abs(np.asarray(MP.edge(COL).need("edge"))[IN + (0,)]
                   - abs(SA)).max()) < 1e-15)
e2 = MP.edge(RAMP, keep=False)
check("keep=False: only the edge layer remains", e2.names == ["edge"], e2.names)
check("components=False produces no gx/gy/dir",
      MP.edge(RAMP).names == ["C", "edge"], MP.edge(RAMP).names)
err("wrong method raises", lambda: MP.edge(RAMP, method="canny"),
    "Method must be one of")

print("═" * 28, "sharpen / median")

check("sharpen amount=0 is a **bit-exact** identity",
      np.array_equal(L(MP.sharpen(B, 0.0)), b))
check("a constant image stays constant after sharpening (a blurred constant is itself)",
      float(np.abs(L(MP.sharpen(CST, 3.0, 2.0)) - 0.7).max()) < 1e-7)
sh = L(MP.sharpen(B, 1.0, 1.0))
check("sharpening increases contrast (variance grows)", float(sh.var()) > float(b.var()),
      f"{float(b.var()):.5f} -> {float(sh.var()):.5f}")
check("with sigma=0 blur is the identity, so sharpening is too",
      float(np.abs(L(MP.sharpen(B, 2.0, 0.0)) - b).max()) < 1e-7)

check("median radius=0 is the identity (bit-exact)",
      np.array_equal(L(MP.median(B, 0)), b))
check("a constant image stays constant after median",
      float(np.abs(L(MP.median(CST, 2)) - 0.7).max()) < 1e-7)
# The median is always a value that occurs in the window (with an odd number of samples)
SP = np.zeros((16, 16, 1), np.float32)
SP[RNG.random((16, 16)) < 0.1, 0] = 1.0
SPI = CopImage(16, 16, {"C": SP})
md = L(MP.median(SPI, 1))
check("median output only takes values occurring in the window (salt-and-pepper removed, still 0/1)",
      set(np.unique(md).tolist()) <= {0.0, 1.0},
      sorted(set(np.unique(md).tolist()))[:4])
check("  10% salt-and-pepper noise filtered out by the median",
      float(md.sum()) < float(SP.sum()) * 0.35,
      f"{int(SP.sum())} -> {int(md.sum())}")
check("negative control: a blur of the same radius does **not** keep 0/1",
      not set(np.unique(np.asarray(
          F.blur(SPI, 1.0).need("C")).round(6).tolist())) <= {0.0, 1.0})
err("median radius above the limit raises", lambda: MP.median(B, 20), "limit 8")

print("═" * 28, "SDF from Mask -- exact EDT")

# Cross-checked against brute-force O(N²). This is the whole basis for the word "exact"
for hw, dens, sd in ((24, 0.15, 3), (31, 0.02, 4), (17, 0.5, 5)):
    rr = np.random.default_rng(sd)
    msk = rr.random((hw, hw + 7)) < dens
    if not msk.any():
        continue
    d = SD.distance_exact(msk)
    ys, xs = np.nonzero(msk)
    ggy, ggx = np.mgrid[0:hw, 0:hw + 7]
    bf = np.sqrt(((ggy[..., None] - ys) ** 2
                  + (ggx[..., None] - xs) ** 2).min(-1))
    check(f"exact EDT == brute-force nearest distance ({hw}x{hw + 7}, density {dens})",
          float(np.abs(d - bf).max()) == 0.0,
          f"max err {float(np.abs(d - bf).max()):.3e}")

one = np.zeros((9, 9), bool)
one[4, 4] = True
d1p = SD.distance_exact(one)
check("single seed: distance is the Euclidean distance to it",
      float(np.abs(d1p - np.hypot(*np.mgrid[-4:5, -4:5])).max()) == 0.0)
check("no seeds gives NOSEED, neither nan nor 0",
      float(SD.distance_exact(np.zeros((8, 8), bool)).min()) == SD.NOSEED)
check("all seeds: distance all 0",
      float(SD.distance_exact(np.ones((8, 8), bool)).max()) == 0.0)
check("squared distance transform is separable (sqrt of edt_sq == distance_exact)",
      float(np.abs(np.sqrt(SD.edt_sq(one)) - d1p).max()) == 0.0)

print("═" * 28, "SDF from Mask —— JFA")

worst = {}
for plus in (0, 1, 2):
    w, n_bad, tot = 0.0, 0, 0
    for sd in range(4):
        rr = np.random.default_rng(200 + sd)
        msk = rr.random((96, 96)) < 10 ** (-rr.uniform(1.0, 3.0))
        if msk.sum() < 2:
            continue
        ex = SD.distance_exact(msk)
        dj = np.asarray(SD.distance_jfa(
            XP.asarray(msk.astype(np.float32)[:, :, None]), XP, 96, 96,
            plus))[:, :, 0]
        e = np.abs(dj - ex)
        w = max(w, float(e.max()))
        n_bad += int((e > 1e-3).sum())
        tot += e.size
    worst[plus] = (w, 100.0 * n_bad / max(tot, 1))
check("negative control: JFA without extra passes (plus=0) **really is wrong**",
      worst[0][0] > 0.5, f"max {worst[0][0]:.4f} px, {worst[0][1]:.4f}% wrong")
check("JFA+1 shows no measurable error on these samples (note: that doesn't mean exact)",
      worst[1][0] < 1e-3, f"max {worst[1][0]:.2e} px")
check("JFA+2 likewise", worst[2][0] < 1e-3, f"max {worst[2][0]:.2e} px")
check("jump steps halve from the power of 2 ≥ max(W,H) down to 1, then plus extra passes",
      SD._jfa_steps(100, 60, 2) == [64, 32, 16, 8, 4, 2, 1, 2, 1],
      SD._jfa_steps(100, 60, 2))

print("═" * 28, "SDF from Mask -- half pixel and units")

NS, RAD = 256, 70.0
ggy, ggx = np.mgrid[0:NS, 0:NS]
dtrue = np.sqrt((ggy + 0.5 - NS / 2) ** 2
                + (ggx + 0.5 - NS / 2) ** 2) - RAD
CIR = CopImage(NS, NS, {"mask": (dtrue < 0).astype(np.float32)[:, :, None]})


def band(d, lo, hi):
    s = (dtrue > lo) & (dtrue <= hi)
    return float((d[s] - dtrue[s]).mean()), float(
        np.sqrt(((d[s] - dtrue[s]) ** 2).mean()))


dF = np.asarray(SD.sdf_from_mask(CIR, "mask", half_pixel=False)
                .need("sdf"))[:, :, 0]
dT = np.asarray(SD.sdf_from_mask(CIR, "mask", half_pixel=True)
                .need("sdf"))[:, :, 0]
b0F, _ = band(dF, 0, 1)
b0T, _ = band(dT, 0, 1)
check("ring along the boundary: without correction the bias is ≈ +0.5 px (where the name 'half pixel' comes from)",
      0.45 < b0F < 0.62, f"{b0F:+.4f}")
check("  after correction it drops within 0.1", abs(b0T) < 0.1, f"{b0T:+.4f}")
check("  the correction reduces the boundary bias by more than an order of magnitude", abs(b0F) > abs(b0T) * 5,
      f"{abs(b0F):.4f} vs {abs(b0T):.4f}")
bfF, _ = band(dF, 40, 100)
bfT, _ = band(dT, 40, 100)
check("the far field overshoots slightly instead -- a known trade-off, not a bug",
      abs(bfT) > abs(bfF), f"raw {bfF:+.4f} / hp {bfT:+.4f}")


def zero_radius(d):
    row = d[NS // 2]
    i = int(np.argmax(row[NS // 2:] > 0)) + NS // 2
    t = -row[i - 1] / (row[i] - row[i - 1])
    return (np.arange(NS) + 0.5)[i - 1] + t - NS / 2


check("**the correction doesn't move the zero isosurface** (symmetric inside and out)",
      abs(zero_radius(dF) - zero_radius(dT)) < 1e-9,
      f"{zero_radius(dF):.6f} vs {zero_radius(dT):.6f}")
check("  and the zero isosurface radius is the true radius",
      abs(zero_radius(dT) - RAD) < 1e-3, f"{zero_radius(dT):.6f}")
check("negative inside, positive outside (consistent with COP Shape)",
      dT[NS // 2, NS // 2] < 0 < dT[0, 0])

# uv units: divide by the **short side**
NX2, NY2 = 128, 64
RCT = CopImage(NX2, NY2, {"mask": np.zeros((NY2, NX2, 1), np.float32)})
mk = np.zeros((NY2, NX2, 1), np.float32)
mk[24:40, 56:72] = 1.0
RCT = CopImage(NX2, NY2, {"mask": mk})
dpx = np.asarray(SD.sdf_from_mask(RCT, "mask", units="pixels")
                 .need("sdf"))[:, :, 0]
duv = np.asarray(SD.sdf_from_mask(RCT, "mask", units="uv")
                 .need("sdf"))[:, :, 0]
check("uv units are pixels divided by the **short side** (not squashed on non-square images)",
      float(np.abs(duv * min(NX2, NY2) - dpx).max()) == 0.0)

# Compared against the SDF output directly by COP Shape
SH = G.shape(NS, NS, "circle", radius=RAD / NS)
shm = CopImage(NS, NS, {"mask": np.asarray(SH.need("mask"))})
dre = np.asarray(SD.sdf_from_mask(shm, "mask", units="uv")
                 .need("sdf"))[:, :, 0]
dsh = np.asarray(SH.need("sdf"))[:, :, 0]
sel = np.abs(dsh) < 0.15
check("a circle drawn by COP Shape, baked to a mask and turned back into an SDF, matches Shape's own layer",
      float(np.abs(dre[sel] - dsh[sel]).max()) < 0.01,
      f"max {float(np.abs(dre[sel] - dsh[sel]).max()):.5f} uv "
      f"(= {float(np.abs(dre[sel] - dsh[sel]).max()) * NS:.2f} px)")

# The four sign modes
sg = {s: np.asarray(SD.sdf_from_mask(CIR, "mask", sign=s).need("sdf"))[:, :, 0]
      for s in SD.SIGNS}
check("sign=outside: 0 inside, ≥ 0 outside",
      float(sg["outside"].min()) == 0.0
      and sg["outside"][NS // 2, NS // 2] == 0.0)
check("sign=inside: 0 outside, positive inside (depth)",
      float(sg["inside"].min()) == 0.0
      and sg["inside"][NS // 2, NS // 2] > 0)
check("sign=unsigned == |signed|",
      float(np.abs(sg["unsigned"] - np.abs(sg["signed"])).max()) == 0.0)
check("outside − inside == signed",
      float(np.abs((sg["outside"] - sg["inside"])
                   - sg["signed"]).max()) == 0.0)

# Cross-module identity: disk dilation == EDT ≤ r
rr = np.random.default_rng(11)
BIN = (rr.random((64, 64)) < 0.02)
BI = CopImage(64, 64, {"m": BIN.astype(np.float32)[:, :, None]})
edt = SD.distance_exact(BIN)
for r in (1, 2, 3, 5, 8):
    dil = np.asarray(MP.morph(BI, op="dilate", radius=r, shape="disc",
                              layers="m").need("m"))[:, :, 0] > 0.5
    check(f"cross-module: dilation by a disk of radius {r} == EDT ≤ {r}, **bit-exact**",
          np.array_equal(dil, edt <= r + 1e-9))
check("negative control: a box structuring element does **not** equal EDT ≤ r (circle and square are different things)",
      not np.array_equal(
          np.asarray(MP.morph(BI, op="dilate", radius=3, shape="box",
                              layers="m").need("m"))[:, :, 0] > 0.5,
          edt <= 3 + 1e-9))

# The gap between exact and jfa -- this is **the most valuable negative finding** of this batch.
#
# On the random sparse seeds above JFA+2 showed not a single error, so it was easy to write
# "jfa == exact". Switch to a **solid big circle** (distances propagate seventy-odd pixels) and it shows immediately:
# max difference 0.19 px, 0.085% of pixels wrong, and raising plus to 4 no longer helps -- this is
# JFA's inherent miss, not too few extra passes.
#
# The lesson is that "random tests pass" doesn't prove correctness: sparse point seeds propagate over short distances and never
# get into the regime where JFA goes wrong.
jf = {p: np.asarray(SD.sdf_from_mask(CIR, "mask", mode="jfa",
                                     jfa_plus=p).need("sdf"))
      for p in (0, 2, 4)}
e1 = np.asarray(SD.sdf_from_mask(CIR, "mask", mode="exact").need("sdf"))
gap = {p: float(np.abs(e1 - v).max()) for p, v in jf.items()}
check("on a solid big circle jfa and exact **differ** (the part sparse seeds can't detect)",
      gap[2] > 0.05, f"plus=2 differs by {gap[2]:.4f} px")
check("  but by a limited amount (< 0.3 px), good enough for outlines/expansion",
      gap[2] < 0.3, f"{gap[2]:.4f} px")
check("  raising extra passes from 2 to 4 **no longer improves** -- an inherent miss, not too few passes",
      abs(gap[2] - gap[4]) < 1e-9, f"{gap[2]:.5f} vs {gap[4]:.5f}")
check("  plus=0 is worse than plus=2 (extra passes do help)", gap[0] > gap[2],
      f"{gap[0]:.4f} vs {gap[2]:.4f}")
bad2 = float((np.abs(e1 - jf[2]) > 1e-3).mean()) * 100
check("  the fraction of wrong pixels is small", bad2 < 0.5, f"{bad2:.4f}%")

check("with keep=True the original mask layer is still there", "mask" in
      SD.sdf_from_mask(CIR, "mask"))
check("with keep=False only sdf remains",
      SD.sdf_from_mask(CIR, "mask", keep=False).names == ["sdf"])
check("threshold really moves the boundary",
      not np.array_equal(
          np.asarray(SD.sdf_from_mask(
              CopImage(NS, NS, {"g": (1 - np.clip(np.abs(dtrue) / 80, 0, 1))
                                .astype(np.float32)[:, :, None]}),
              "g", threshold=0.3).need("sdf")),
          np.asarray(SD.sdf_from_mask(
              CopImage(NS, NS, {"g": (1 - np.clip(np.abs(dtrue) / 80, 0, 1))
                                .astype(np.float32)[:, :, None]}),
              "g", threshold=0.7).need("sdf"))))
err("wrong mode raises", lambda: SD.sdf_from_mask(CIR, "mask", mode="fast"),
    "Mode must be one of")
err("wrong sign raises", lambda: SD.sdf_from_mask(CIR, "mask", sign="abs"),
    "Sign must be one of")
err("wrong units raises", lambda: SD.sdf_from_mask(CIR, "mask", units="mm"),
    "Units must be one of")
err("wrong layer name raises and lists the existing layers",
    lambda: SD.sdf_from_mask(CIR, "nope"), "no 'nope' layer. Existing")

print("═" * 28, "backend consistency")

# The same chain should give the same result on the numpy and exact (float64) backends
try:
    EX = CopImage(32, 32, {"C": RNG.random((32, 32, 3))})   # float64
    check("float64 layers aren't silently downgraded to float32",
          EX.need("C").dtype == np.float64, EX.need("C").dtype)
    # Again only smooth images work: on white noise a 1-ulp difference in sample coordinates picks a completely different pixel
    s32 = CopImage(64, 64, {"C": sm})
    s64 = CopImage(64, 64, {"C": np.asarray(sm, np.float64)})
    n32 = L(T.transform(s32, rotate=37.0))
    n64 = np.asarray(T.transform(s64, rotate=37.0).need("C"))
    check("float32 and float64 take the same path, results agree within float32 precision",
          float(np.abs(n32 - n64).max()) < 1e-6,
          f"{float(np.abs(n32 - n64).max()):.2e}")
    check("negative control: the same cross-check on white noise differs much more (a 1-ulp coordinate difference changes the pixel)",
          float(np.abs(L(T.transform(img_rand(64, 64, 3, 9), rotate=37.0))
                       - np.asarray(T.transform(CopImage(64, 64, {
                           "C": np.asarray(L(img_rand(64, 64, 3, 9)),
                                           np.float64)}),
                           rotate=37.0).need("C"))).max()) > 1e-6)
except Exception as ex:
    check("backend consistency", False, f"{type(ex).__name__}: {ex}")

if BK.cuda_available():
    try:
        CU = img_rand(64, 64, 3, 12).to_device("cuda")
        for nm, fn in (("transform", lambda i: T.transform(i, rotate=37.0)),
                       ("levels", lambda i: LV.levels(i, 0.1, 0.9, 1.8)),
                       ("morph", lambda i: MP.morph(i, "dilate", 2)),
                       ("edge", lambda i: MP.edge(i)),
                       ("sdf/jfa", lambda i: SD.sdf_from_mask(
                           i, "C", mode="jfa"))):
            g = fn(CU).to_device("numpy")
            c = fn(img_rand(64, 64, 3, 12))
            k = g.names[-1]
            check(f"[cuda] {nm} agrees with numpy",
                  float(np.abs(np.asarray(g.need(k))
                               - np.asarray(c.need(k))).max()) < 1e-4)
    except Exception as ex:
        check("cuda consistency", False, f"{type(ex).__name__}: {ex}")
else:
    print("  (no CUDA, skipping GPU consistency)")

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
