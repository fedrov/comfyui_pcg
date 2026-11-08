"""
pcg100 audit pack c7_filter_sim: a batch of COP filters / simulations added after checking the SideFX docs.

  Feather                      new node PCG_COPFeatherSlope (max slope; Diamond / Square /
                               Octagon / Custom / Circle; two Feather Methods)
  Extrapolate Boundaries       new node PCG_COPExtrapolateBoundaries
  Edge Detect by Contour /
  Depth / Normal               new node PCG_COPEdgeDetectProbe (three modes in one)
  Surface Dither               new node PCG_COPSurfaceDither
  Reaction-Diffusion Block End PCG_COPReactionDiffusion gains the Kenjiro Maginu model, Scale
                               Multiplier, Boundary, Output Correction
  Turing Patterns              new node PCG_COPTuringPatterns (blur + sharpen iterations)
  Heat Distort by Layer        new node PCG_COPHeatDistortByLayer
  Refract from Height          PCG_COPRefractFromHeight gains view direction, Height Offset,
                               Ground layer (Newton iteration), Normal layer, Source sampling
  Ocean Spectrum               PCG_COPOcean gains Depth, Gravity, Spectrum Type (TMA),
                               Amplitude Distribution, Directional Movement, Loop Period

References are all values that can be worked out by hand (slope cones, distances, Snell solution for planar refraction, dispersion relation …). For the three old
nodes that were changed (reaction-diffusion / refraction / ocean), "bit-identical to before the change at defaults" uses digests of the same set of calls before the change,
hard-coded in GOLDEN (arrays rounded to 5 decimals before hashing); `--digests` prints the current digests. Doesn't depend on git.
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
from comfyui_pcg.geo.cop import CopImage                # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def near(a, b, tol=1e-9):
    return np.allclose(np.asarray(a, np.float64), np.asarray(b, np.float64),
                       atol=tol, rtol=0)


def defaults(n):
    """Defaults from INPUT_TYPES (combos use {"default": …}, otherwise the first item)."""
    out = {}
    for k, v in M[n].INPUT_TYPES()["required"].items():
        opt = v[1] if len(v) > 1 and isinstance(v[1], dict) else {}
        if isinstance(v[0], list):
            out[k] = opt.get("default", v[0][0])
        elif "default" in opt:
            out[k] = opt["default"]
    return out


def run(n, **kw):
    a = defaults(n)
    a.update(kw)
    return M[n]().run(**a)


def run0(n, **kw):
    return run(n, **kw)[0]


def L(im, name):
    return np.asarray(im.need(name), np.float64)


def dig(im):
    h = hashlib.sha1()
    for k in sorted(im.names):
        a = np.asarray(im.need(k))
        h.update(f"{k}/{a.dtype}/{a.shape}".encode())
        h.update(np.ascontiguousarray(np.round(a.astype(np.float64), 5)
                                      + 0.0).tobytes())
    return h.hexdigest()[:16]


def img_with(W, H, **layers):
    im = CopImage(W, H)
    for k, a in layers.items():
        a = np.asarray(a, np.float32)
        if a.ndim == 2:
            a = a[..., None]
        im.set(k, a)
    return im


def panel_ok(n):
    bad = PANEL.check_layout(n, M[n].INPUT_TYPES())
    check(f"{n} panel layout correct", not bad, bad)


# ═══════════════════════════════════════════════════ Regression: identical to before the change at defaults
def height_img():
    W, H = 24, 16
    J, I = np.meshgrid(np.arange(W), np.arange(H))
    h = 0.05 * np.sin(J * 0.5) * np.cos(I * 0.4) + 0.02 * J / W
    c = np.stack([J / W, I / H, 0.5 + 0 * J], -1)
    return img_with(W, H, C=c, h=h)


def old_cases():
    """Calls that existed before the change (only old parameters, new parameters all at defaults)."""
    R = {}
    rd = "PCG_COPReactionDiffusion"
    R["rd/gs"] = run0(rd, steps=60, resolution_x=32, resolution_y=24,
                      compute="cpu")
    R["rd/gs_custom"] = run0(rd, preset="custom", feed=0.03, kill=0.06,
                             steps=40, edge="clamp", resolution_x=24,
                             resolution_y=24, rand_seed=3, compute="cpu")
    R["rd/turing"] = run0(rd, mode="turing", steps=5, scales="8 4",
                          resolution_x=32, resolution_y=32, compute="cpu")
    rf = "PCG_COPRefractFromHeight"
    R["refract/0"] = run0(rf, cop=height_img(), layer="h")
    R["refract/1"] = run0(rf, cop=height_img(), layer="h", depth=0.3,
                          ior=1.5, tile=True, out_layer="r2")
    oc = "PCG_COPOcean"
    R["ocean/0"] = run0(oc, resolution_x=32, resolution_y=32)
    R["ocean/1"] = run0(oc, size=50.0, wind_speed=8.0, wind_direction=30.0,
                        align=4.0, small_cut=0.5, time=2.5, choppiness=0.5,
                        rand_seed=7, resolution_x=32, resolution_y=16)
    return {k: dig(v) for k, v in R.items()}


# Digests from running old_cases() before the change (commit f210100)
GOLDEN = {
    "rd/gs": "3d7e11d7485e7ca7",
    "rd/gs_custom": "3f237a9a835d1114",
    "rd/turing": "1ab1d374a7c4daa4",
    "refract/0": "975d5928e8111eda",
    "refract/1": "ced41695f40d9d4a",
    "ocean/0": "5739aff1a93b84f1",
    "ocean/1": "0dc25cf62d64542d",
}

if "--digests" in sys.argv:
    for k, v in old_cases().items():
        print(f'    "{k}": "{v}",')
    sys.exit(0)

sec("regression: changed old nodes bit-identical to before the change with new parameters at defaults")
now = old_cases()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) >= 7 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})


# ═══════════════════════════════════════════════════ Feather
sec("Feather → PCG_COPFeatherSlope")
FS = "PCG_COPFeatherSlope"
W = H = 21
PX = 2.0 / 21
spike = np.zeros((H, W))
spike[10, 10] = 1.0
J, I = np.meshgrid(np.arange(W) - 10, np.arange(H) - 10)
AX, AY = np.abs(J), np.abs(I)
s5 = 1.0 / (5 * PX)                      # drops by 1 every 5 pixels


def fs(src, **kw):
    kw.setdefault("distance", 5 * PX)
    return L(run0(FS, cop=img_with(W, H, mask=src), **kw), "mask")[..., 0]


ref_d = np.maximum(0, 1 - (AX + AY) / 5)
check("Diamond: single pixel -> 1 - s·L1 (diamond cone)", near(fs(spike, direction="diamond"), ref_d, 1e-6))
ref_s = np.maximum(0, 1 - math.sqrt(2) * np.maximum(AX, AY) / 5)
check("Square: 1 - s·√2·max(|Δx|,|Δy|) (square, no checkerboard)",
      near(fs(spike, direction="square"), ref_s, 1e-6))
mx, mn = np.maximum(AX, AY), np.minimum(AX, AY)
ref_o = np.maximum(0, 1 - ((mx - mn) + math.sqrt(2) * mn) / 5)
check("Octagon: 1 - s·(|long|-|short| + √2·short) (regular octagon)",
      near(fs(spike, direction="octagon"), ref_o, 1e-6))
oc = fs(spike, direction="circle")
r = np.hypot(J, I)
drop = 1 - oc
inside = (r / 5) < 0.95
check("Circle: drop between the Euclidean cone s·r and s·r/cos(13.3°) (16-gon)",
      np.all(drop[inside] >= r[inside] / 5 - 1e-6)
      and np.all(drop[inside] <= r[inside] / 5 / math.cos(math.radians(13.29)) + 1e-6))
check("Circle differs from Octagon (negative control)", not near(oc, ref_o, 1e-3))
cx = fs(spike, direction="custom", sweep_px=True)
ref_c = np.zeros((H, W))
ref_c[10, 10:] = np.maximum(0, 1 - np.arange(11) / 5)
check("Custom +X: only propagates towards +X (same row 1 - s·Δx)", near(cx, ref_c, 1e-6))
cq = fs(spike, direction="custom", sweep_px=False, sweep_pxpy=True)
q = (J >= 0) & (I >= 0)
check("Custom +X+Y: only into the +X+Y quadrant (+Y = increasing row number), √2·max slope",
      near(cq, np.where(q, ref_s, 0), 1e-6))
sp0 = np.zeros((H, W))
sp0[0, 3] = 1.0
c0 = fs(sp0, direction="custom", sweep_px=False, sweep_pxpy=True)
check("Custom +X+Y: a bright pixel on the first row (scan start) also propagates along the row towards +X",
      abs(c0[0, 4] - (1 - math.sqrt(2) / 5)) < 1e-6 and c0[0, 2] == 0)
cm = fs(spike, direction="custom", sweep_px=False, sweep_nx=True, sweep_ny=True)
check("Custom -X, -Y: only into the third quadrant (L1)",
      near(cm, np.where((J <= 0) & (I <= 0), ref_d, 0), 1e-6))
for tok, (dx, dy) in (("nxpy", (-1, 1)), ("pxny", (1, -1)), ("nxny", (-1, -1)),
                      ("py", (0, 1))):
    kw = {"sweep_px": False, "sweep_" + tok: True}
    got = fs(spike, direction="custom", **kw)
    want = (np.sign(J) * dx >= 0) & (np.sign(I) * dy >= 0) if dx and dy else \
        ((J == 0) & (np.sign(I) * dy >= 0))
    check(f"Custom {tok}: the reached area lies in the corresponding direction", np.array_equal(got > 0, want & (got > 0))
          and got[10 + dy, 10 + dx] > 0)
# Low to High
dent = 1.0 - spike
lo = fs(dent, high_to_low=False, direction="diamond")
check("High to Low off: dark pixels unchanged, bright pixels pushed down to s·L1", near(lo, 1 - ref_d, 1e-6))
hi = fs(dent, high_to_low=True, direction="diamond")
check("High to Low on (negative control): the dark pit raised by its neighbours to 1 - s·1 pixel, the rest unchanged",
      near(hi, np.where(spike > 0, 0.8, 1.0), 1e-6))
# Method
a1 = fs(spike, method="change_per_distance", change=s5)
check("Change per Distance = 1 / Distance for Unit Change gives the same result",
      near(a1, ref_d, 1e-6))
a2 = fs(spike, method="change_per_distance", change=2 * s5)
check("Change per Distance doubled -> cone half as wide (negative control)",
      near(a2, np.maximum(0, 1 - 2 * (AX + AY) / 5), 1e-6))
# Include Border
ones = np.ones((H, W))
b0 = fs(ones, high_to_low=False)
check("Include Border off: an all-1 image is unchanged", near(b0, 1.0, 1e-9))
b1 = fs(ones, high_to_low=False, include_border=True, border="black")
dist_edge = np.minimum(np.minimum(J + 10, 10 - J), np.minimum(I + 10, 10 - I)) + 1
check("Include Border + Black: the border pulled down by the 0 outside the image = min(1, s·(distance to edge+1))",
      near(b1, np.minimum(1, dist_edge / 5), 1e-6))
b2 = fs(ones, high_to_low=False, include_border=True, border="clamp")
check("Include Border + Clamp: no effect (all 1)", near(b2, 1.0, 1e-9))
edge = np.zeros((H, W))
edge[10, 0] = 1.0
w0 = fs(edge, direction="diamond")
w1 = fs(edge, direction="diamond", include_border=True, border="wrap")
check("Include Border + Wrap: the bright pixel on the left wraps in from the right (right edge = 1 - s)",
      abs(w1[10, W - 1] - (1 - 1 / 5)) < 1e-6 and w0[10, W - 1] == 0)
# Mask
mh = fs(spike, mask=0.5)
check("Mask 0.5: half original, half feathered", near(mh, 0.5 * spike + 0.5 * ref_d, 1e-6))
ml = np.zeros((H, W))
ml[:, 11:] = 1
mm = L(run0(FS, cop=img_with(W, H, mask=spike, m=ml), distance=5 * PX,
            mask_layer="m"), "mask")[..., 0]
check("Mask Layer: feathered only where mask = 1", near(mm, np.where(ml > 0, ref_d, spike), 1e-6))
# Multi-channel / output layer
c2 = np.stack([spike, 1 - spike], -1)
o2 = L(run0(FS, cop=img_with(W, H, C=c2), layer="C", out_layer="F",
            distance=5 * PX), "F")
check("multi-channel done per channel, written to Out Layer", near(o2[..., 0], ref_d, 1e-6) and near(o2[..., 1], np.where(spike > 0, 0.8, 1.0), 1e-6))
# Non-square image: pixel = 2/long side
W2, H2 = 30, 10
sp2 = np.zeros((H2, W2))
sp2[5, 15] = 1
o3 = L(run0(FS, cop=img_with(W2, H2, mask=sp2), distance=0.2), "mask")[..., 0]
check("non-square image: 1 pixel = 2/long side image units (Distance 0.2 = 3 pixels)",
      abs(o3[5, 16] - (1 - (2 / 30) / 0.2)) < 1e-6 and abs(o3[5, 18]) < 1e-6)
try:
    run0(FS, cop=img_with(W, H, mask=spike), distance=0.0)
    check("Distance 0 raises", False)
except ValueError:
    check("Distance 0 raises", True)
panel_ok(FS)


# ═══════════════════════════════════════════════════ Extrapolate Boundaries
sec("Extrapolate Boundaries → PCG_COPExtrapolateBoundaries")
EB = "PCG_COPExtrapolateBoundaries"
W, H = 20, 10
PX = 2.0 / 20
J, I = np.meshgrid(np.arange(W), np.arange(H))
fa = (J < 8).astype(float)
ramp = np.where(J < 8, J.astype(float), 5.0) + 0.1 * I


def eb(**kw):
    kw.setdefault("cop", img_with(W, H, C=ramp, mask=fa))
    kw.setdefault("edge_padding", 3 * PX)
    return run0(EB, **kw)


o = eb()
r = L(o, "C")[..., 0]
want = np.where(J < 8, ramp, np.where(J <= 10, 7 + 0.1 * I, ramp))
check("3-pixel padding: x = 8…10 copy the nearest interior pixel (x = 7), further out unchanged", near(r, want, 1e-5))
check("fillarea layer unchanged (empty Layers = everything except it)", near(L(o, "mask")[..., 0], fa))
r = L(eb(exterior="black"), "C")[..., 0]
check("Exterior = Black: zero beyond the padding", near(r, np.where(J <= 10, want, 0.0), 1e-5))
const = np.where(J < 8, 3.0, -9.0)
r = L(eb(cop=img_with(W, H, C=const, mask=fa), exterior="diffuse_fill"), "C")[..., 0]
check("Exterior = Diffuse Fill: constant interior -> exterior all that constant", near(r, 3.0, 1e-5))
r = L(eb(exterior="diffuse_fill"), "C")[..., 0]
ext = J > 10
check("Diffuse Fill: exterior within the range of known values, differs from Unchanged",
      r[ext].min() >= 7 - 1e-5 and r[ext].max() <= 7.9 + 1e-5 and not near(r[ext], ramp[ext], 1e-3))
r0 = L(eb(exterior="diffuse_fill", diffuse_iterations=0), "C")[..., 0]
r9 = L(eb(exterior="diffuse_fill", diffuse_iterations=500), "C")[..., 0]
check("Diffuse Iterations change the result (0 = nearest-value extrapolation only)", not near(r0, r9, 1e-4))
r = L(eb(edge_offset=2 * PX), "C")[..., 0]
check("Edge Offset 2 pixels: padding takes the value at x = 5",
      near(r, np.where(J < 8, ramp, np.where(J <= 10, 5 + 0.1 * I, ramp)), 1e-5))
r = L(eb(edge_padding=0.0), "C")[..., 0]
check("Edge Padding 0: exterior all unchanged", near(r, ramp, 1e-6))
r = L(eb(inner_side="below_threshold", cop=img_with(W, H, C=ramp, mask=1 - fa)), "C")[..., 0]
check("Inner Side = Below Threshold + inverted fillarea: same result", near(r, want, 1e-5))
r = L(eb(inner_side="below_threshold"), "C")[..., 0]
want_b = np.where(J >= 8, ramp, np.where(J >= 5, 5.0 + 0.1 * I, ramp))
check("Below Threshold (negative control): interior becomes the right half, the left 3 columns padded with the value at x = 8", near(r, want_b, 1e-5))
r = L(eb(cop=img_with(W, H, C=ramp, mask=J / 10.0), threshold=0.55), "C")[..., 0]
check("Threshold: fillarea = x/10 > 0.55 is interior (x ≥ 6), padded 3 columns to the left",
      near(r[:, 3:6], np.repeat((ramp[:, 6])[:, None], 3, 1), 1e-5) and near(r[:, :3], ramp[:, :3], 1e-5))
# Sample Only Present: an isolated interior pixel, stepping back half a pixel diagonally
one = np.zeros((H, W))
one[5, 5] = 1
noise = np.random.default_rng(3).random((H, W))
im = img_with(W, H, C=noise, mask=one)
ra = L(run0(EB, cop=im, edge_padding=2.5 * PX, edge_offset=0.5 * PX,
            sample_only_present=True), "C")[..., 0]
rb = L(run0(EB, cop=im, edge_padding=2.5 * PX, edge_offset=0.5 * PX,
            sample_only_present=False), "C")[..., 0]
nb = np.hypot(J - 5, I - 5) <= 2.5
nb[5, 5] = False
n32 = noise.astype(np.float32).astype(np.float64)
check("Sample Only Present on: only interior pixels used (isolated point -> everything takes its value)",
      near(ra[nb], n32[5, 5], 1e-6))
# Pixel (x 3, y 4): nearest point (5,5), direction (2,1)/√5, then back half a pixel -- fx ≠ fy
fx, fy = 1 / math.sqrt(5), 0.5 / math.sqrt(5)
bl = (n32[5, 5] * (1 - fy) * (1 - fx) + n32[5, 6] * (1 - fy) * fx
      + n32[6, 5] * fy * (1 - fx) + n32[6, 6] * fy * fx)
check("Sample Only Present off (negative control): plain bilinear (x, y weights asymmetric), exterior values mixed in",
      abs(rb[4, 3] - bl) < 1e-5 and abs(rb[4, 3] - n32[5, 5]) > 1e-3)
from comfyui_pcg.geo.cop.filtersim import nearest_seed    # noqa: E402
rs = np.random.default_rng(5).random((23, 31)) < 0.04
d2, sy_, sx_ = nearest_seed(rs)
Ys, Xs = np.nonzero(rs)
JJ, II = np.meshgrid(np.arange(31), np.arange(23))
brute = ((II[..., None] - Ys) ** 2 + (JJ[..., None] - Xs) ** 2).min(-1)
check("nearest seed (lower envelope with indices) agrees with brute force: distances, and indices are seeds at the right distance",
      near(d2, brute) and rs[sy_, sx_].all()
      and near((sy_ - II) ** 2 + (sx_ - JJ) ** 2, brute))
check("interior pixels bit-identical", ra[5, 5] == np.float32(noise[5, 5]))
r = L(eb(mask=0.5), "C")[..., 0]
check("Mask 0.5: half", near(r, 0.5 * ramp + 0.5 * want, 1e-5))
# Non-square image / multiple layers
W2, H2 = 10, 30
fa2 = (np.arange(H2)[:, None] < 10) * np.ones((1, W2))
c2 = np.stack([np.arange(H2)[:, None] * np.ones((1, W2))] * 2, -1)
o2 = run0(EB, cop=img_with(W2, H2, A=c2, B=c2[..., 0], mask=fa2), layers="A",
          edge_padding=2 * (2.0 / 30))
a2 = L(o2, "A")
check("non-square image: Edge Padding converted by the long side (2 pixels), Layers only processes the listed ones",
      near(a2[10:12, :, 0], 9.0) and near(a2[12, :, 0], 12.0)
      and near(L(o2, "B")[..., 0], c2[..., 0]))
try:
    run0(EB, cop=img_with(W, H, C=ramp, mask=fa * 0))
    check("no interior pixels raises", False)
except ValueError:
    check("no interior pixels raises", True)
panel_ok(EB)


# ═══════════════════════════════════════════════════ Edge Detect by Contour / Depth / Normal
sec("Edge Detect by Contour / Depth / Normal → PCG_COPEdgeDetectProbe")
ED = "PCG_COPEdgeDetectProbe"
W, H = 16, 9
J, I = np.meshgrid(np.arange(W), np.arange(H))
step = (J >= 8).astype(float)


def g_ref(h, R, spread):
    """Pixels h pixels horizontally from the boundary: the nearest 'neighbour on the line' is at h."""
    if h > R:
        return 0.0
    if h <= 1:
        return 1.0
    sg = spread * R
    return math.exp(-0.5 * ((h - 1) / sg) ** 2) if sg > 0 else 0.0


def prof(R, spread=0.5):
    h = np.where(J < 8, 8 - J, J - 7)
    return np.vectorize(lambda x: g_ref(x, R, spread))(h)


def ed(src, **kw):
    kw.setdefault("cop", img_with(W, H, id=src))
    return L(run0(ED, **kw), kw.get("out_layer", "edges"))[..., 0]


check("Contour: on both sides of an id boundary, h pixels away = exp(-½((h-1)/(Spread·R))²), 0 beyond R",
      near(ed(step, thickness_scale=3), prof(3), 1e-6))
check("Contour Tolerance 1.5 > id difference 1 (negative control): no line",
      near(ed(step, contour_tolerance=1.5), 0))
check("Edge Spread 0: only pixels right next to the boundary = 1", near(ed(step, thickness_scale=3, edge_spread=0), prof(3, 0)))
check("Edge Spread 2: line more solid", near(ed(step, thickness_scale=3, edge_spread=2), prof(3, 2), 1e-6))
th = np.where(I >= 5, 3.0, 0.0)
r = ed(step, cop=img_with(W, H, id=step, t=th), thickness_layer="t", thickness_scale=1)
check("Thickness Layer: R = Scale × layer value; where the layer = 0 falls back to Min Probe Radius 1",
      near(r[I >= 5], prof(3)[I >= 5], 1e-6) and near(r[I < 5], prof(1)[I < 5]))
r = ed(step, cop=img_with(W, H, id=step, t=th), thickness_layer="t", thickness_scale=1,
       min_probe_radius=2)
check("Min Probe Radius 2: radius at least 2 in thin places too", near(r[I < 5], prof(2)[I < 5], 1e-6))
idm = np.stack([0 * step, step], -1)
check("multi-channel ids compared by Euclidean distance (only channel 1 differing counts too)", near(ed(idm, thickness_scale=3), prof(3), 1e-6))
r = ed(step, blur=1.5, thickness_scale=1, contour_tolerance=0.45)
r0 = ed(step, thickness_scale=1, contour_tolerance=0.45)
check("Blur: blur first, then detect (step softened, line disappears at tolerance 0.45), differs from no blur",
      r.max() == 0 and r0.max() == 1)
dep = np.where(J >= 8, 1.05, 1.0)
check("Depth: Z difference 0.05 > tolerance 0.01 -> lines on both sides",
      near(ed(dep, kind="depth", thickness_scale=3), prof(3), 1e-6))
check("Depth Tolerance 0.1 (negative control): no line", near(ed(dep, kind="depth", depth_tolerance=0.1), 0))
c30 = math.cos(math.radians(30))
nrm = np.where((J >= 8)[..., None], [math.sin(math.radians(30)) * 2, 0, c30 * 2], [0, 0, 1.0])
check("Normal: 30° fold (dot product 0.866 < 0.9) -> line; un-normalized normals are fine",
      near(ed(nrm, kind="normal", thickness_scale=3), prof(3), 1e-6))
check("Normal Tolerance 0.8 (negative control): no line",
      near(ed(nrm, kind="normal", normal_tolerance=0.8), 0))
nrm2 = np.where((J >= 8)[..., None], [0, 0.5, c30], [0, 0, 1.0])
check("Kind switched to Depth only reads channel 0 (negative control: normals folded about the x axis keep channel 0 -> no line)",
      near(ed(nrm2, kind="depth"), 0) and near(ed(nrm2, kind="normal", thickness_scale=3), prof(3), 1e-6))
r = ed(step, out_layer="E2")
check("Out Layer", r.shape == (H, W))
try:
    ed(step, kind="normal")
    check("a 1-channel layer in Normal mode raises", False)
except ValueError:
    check("a 1-channel layer in Normal mode raises", True)
big = ed(step, thickness_scale=1000)
check("radius capped at 64 (doesn't blow up)", big.shape == (H, W) and big.max() == 1)
panel_ok(ED)


# ═══════════════════════════════════════════════════ Surface Dither
sec("Surface Dither → PCG_COPSurfaceDither")
SD = "PCG_COPSurfaceDither"
N = 64
J, I = np.meshgrid(np.arange(N), np.arange(N))
AL = "-0.0078125 -0.0078125"        # minus half a pixel: lattice points land on pixel centers x = 8m


def sd(**kw):
    kw.setdefault("resolution_x", N)
    kw.setdefault("resolution_y", N)
    kw.setdefault("pattern_offset", AL)
    return run0(SD, **kw)


def lattice_sdf(cell_px, rad_keep, rad_go, ox=0.0, oy=0.0):
    """Analytic reference: distance from pixel (x, y) to lattice points m·cell (pixels) - radius, minimum taken."""
    best = np.full((N, N), np.inf)
    for mx in range(-1, N // int(cell_px) + 2):
        for my in range(-1, N // int(cell_px) + 2):
            keep = mx % 2 == 0 and my % 2 == 0
            r = rad_keep if keep else rad_go
            d = np.hypot(J - (mx * cell_px + ox), I - (my * cell_px + oy)) - r
            best = np.minimum(best, d)
    return best


o = sd(output_type="sdf", level_layer="lv", scale_layer="sc", uv_out_layer="cuv")
ref = lattice_sdf(8, 2.0, 2.0)
check("dot spacing 8 pixels (f = 0): SDF = distance to lattice point - ½·0.5·8", near(L(o, "dither")[..., 0], ref, 1e-4))
check("level = log2(8/64) = −3,scale = 1",
      near(L(o, "lv")[..., 0], -3) and near(L(o, "sc")[..., 0], 1.0, 1e-6))
cu = L(o, "cuv")
check("uv output = local coordinates within the cell (u = 0.5 at x = 8m + 4)",
      near(cu[0, 4, 0], 0.5, 1e-5) and near(cu[4, 0, 1], 0.5, 1e-5) and near(cu[0, 0], 0, 1e-5))
D2 = 8 * math.sqrt(2)                # f = 0.5: cell 8 pixels, dot diameter computed from D2
r0 = 0.5 * 0.5 * D2
o = sd(output_type="sdf", density_scale=D2, level_transition=0.5, scale_layer="sc")
check("f = 0.5, Level Transition 0.5: dots about to disappear haven't started shrinking (smoothstep(0.5,1,0.5) = 0)",
      near(L(o, "dither")[..., 0], lattice_sdf(8, r0, r0), 1e-4)
      and near(L(o, "sc")[..., 0], 2 ** -0.5, 1e-6))
o = sd(output_type="sdf", density_scale=D2, level_transition=1.0)
Rb8 = math.sqrt(2) * 8
check("f = 0.5, Level Transition 1: odd lattice points' radius = (r0 + √2·8)·0.5 - √2·8, even lattice points unchanged",
      near(L(o, "dither")[..., 0], lattice_sdf(8, r0, (r0 + Rb8) * 0.5 - Rb8), 1e-4))
o = sd(output_type="sdf", density_scale=D2, level_transition=0.0)
check("Level Transition 0: no shrinking until the level change", near(L(o, "dither")[..., 0], lattice_sdf(8, r0, r0), 1e-4))
D5 = 16 * (1 - 1e-7)                 # f just short of 1: still at k = -3, odd lattice points already gone
D6 = 16 * (1 + 1e-7)                 # just switched to k = -2
a5 = L(sd(output_type="sdf", density_scale=D5, level_layer="lv"), "dither")[..., 0]
o6 = sd(output_type="sdf", density_scale=D6, level_layer="lv")
check("continuous at the level change: f -> 1⁻ leaves only even lattice points, matching the next level's 16-pixel lattice at f = 0",
      near(a5, L(o6, "dither")[..., 0], 1e-4) and near(a5, lattice_sdf(16, 4.0, 4.0), 1e-4)
      and near(L(o6, "lv")[..., 0], -2))
# Surface stable: uv scaled up 2× (object twice as far) -> one level up, screen dot spacing unchanged
check("Pattern Scale ×2: one level up, on-screen dots unchanged (surface stable + constant screen dot spacing)",
      near(L(sd(output_type="sdf", pattern_scale=2.0, pattern_offset="-0.015625 -0.015625"),
             "dither")[..., 0], ref, 1e-4))
check("Pattern Scale ×1.5 (negative control): different",
      not near(L(sd(output_type="sdf", pattern_scale=1.5), "dither")[..., 0], ref, 1e-2))
u0 = np.stack([(J + 0.5) / N, (I + 0.5) / N], -1)
uvimg = img_with(N, N, uv=u0 * 2)
check("UV Layer = 2× texture uv: same as Pattern Scale 2",
      near(L(run0(SD, cop=uvimg, uv_layer="uv", output_type="sdf",
                  pattern_offset="-0.015625 -0.015625"), "dither")[..., 0], ref, 1e-4))
lv = [L(sd(pattern_scale_xy=v, level_layer="lv"), "lv")[0, 0, 0] for v in ("1 1", "1 2", "2 1", "1 0.5")]
check("Pattern Scale XY: level chosen by the **largest** singular value of the Jacobian (1 2 / 2 1 -> -2; 1 0.5 -> -3)",
      lv == [-3, -2, -2, -3], lv)
o = sd(output_type="sdf", pattern_rotate=90.0)
check("Pattern Rotate 90°: lattice is symmetric, just a translation (qx = -v, lattice points land on y = 8m - 1)",
      near(L(o, "dither")[..., 0], lattice_sdf(8, 2.0, 2.0, oy=-1.0), 1e-4))
o = sd(output_type="sdf", pattern_offset="-0.0078125 0.0078125")
check("Pattern Offset moves only v: lattice points land on y = 8m - 1", near(L(o, "dither")[..., 0],
                                                lattice_sdf(8, 2.0, 2.0, oy=-1.0), 1e-4))
o = sd(output_type="sdf", pattern_rotate=45.0)
check("Pattern Rotate 45° (negative control): different", not near(L(o, "dither")[..., 0], ref, 1e-2))
o = sd(output_type="sdf", dot_scale=1.0)
check("Dot Scale 1: radius 4", near(L(o, "dither")[..., 0], lattice_sdf(8, 4.0, 4.0), 1e-4))
dsl = img_with(N, N, ds=np.full((N, N), 0.5))
o = run0(SD, cop=dsl, dotscale_layer="ds", output_type="sdf", pattern_offset=AL)
check("Dot Scale Layer 0.5: radius 1", near(L(o, "dither")[..., 0], lattice_sdf(8, 1.0, 1.0), 1e-4))
m = L(sd(), "dither")[..., 0]
t = np.clip((ref + 0.5) / 1.0, 0, 1)
check("Mask:1 − smoothstep(−½, ½, SDF)", near(m, 1 - t * t * (3 - 2 * t), 1e-4))
m2 = L(sd(iso_offset=1.0, smooth=0.0), "dither")[..., 0]
check("Iso Offset 1, Smooth 0: 1 where SDF < 1 (dots get bigger)", near(m2, (ref < 1.0) * 1.0, 1e-6)
      or near(m2, (ref <= 1.0) * 1.0, 1e-6))
check("Output Type SDF differs from Mask (negative control)", not near(m, ref, 1e-3))
try:
    sd(density_scale=0.0)
    check("Density Scale 0 raises", False)
except ValueError:
    check("Density Scale 0 raises", True)
panel_ok(SD)


# ═══════════════════════════════════════════════════ Reaction-Diffusion Block End
sec("Reaction-Diffusion Block End -> PCG_COPReactionDiffusion (Maginu, Scale, Boundary, Output Correction)")
RD = "PCG_COPReactionDiffusion"
W, H = 24, 16
J, I = np.meshgrid(np.arange(W), np.arange(H))
full = img_with(W, H, s=np.ones((H, W)))


def rd(**kw):
    kw.setdefault("cop", full)
    kw.setdefault("seed_layer", "s")
    kw.setdefault("compute", "cpu")
    return run(RD, **kw)


al, be, ga = 1.0, 0.5, 1.5
o, rep = rd(mode="maginu", steps=1, dt=0.5)
check("Maginu one step (uniform A = 1, B = 0): A' = 1, B' = 0.5·β",
      near(L(o, "rd_a"), 1.0, 1e-6) and near(L(o, "rd_b"), 0.5 * be, 1e-6) and near(L(o, "rd"), 1.0, 1e-6))
o, _ = rd(mode="maginu", steps=2, dt=0.5)
A2, B2 = 1 - 0.25 * be, 0.5 * be + 0.5 * be * (1 - 0.5 * be * ga)
check("Maginu two steps: A = 1 - ¼β, B = ½β + ½β(1 - ½βγ) (B uses the previous step's A)",
      near(L(o, "rd_a"), A2, 1e-6) and near(L(o, "rd_b"), B2, 1e-6))
o, _ = rd(mode="maginu", steps=1, dt=0.5, maginu_alpha=2.0, maginu_beta=0.4, maginu_gamma=3.0,
          cop=img_with(W, H, s=np.ones((H, W)), rd_a=np.full((H, W), 0.5),
                       rd_b=np.full((H, W), 0.2)))
a1 = 0.5 + 0.5 * (2.0 * (0.5 - 0.125) - 0.2)
b1 = 0.2 + 0.5 * 0.4 * (0.5 - 3.0 * 0.2)
check("Maginu continued (reads _a / _b) + α β γ: one-step analytic value", near(L(o, "rd_a"), a1, 1e-6)
      and near(L(o, "rd_b"), b1, 1e-6))
spk = np.zeros((H, W))
spk[5, 5] = 1.0
o, _ = rd(mode="maginu", steps=1, dt=1.0, du=0.3, dv=0.8, maginu_alpha=0.0,
          maginu_beta=0.0, cop=img_with(W, H, rd_a=spk, rd_b=spk))
check("Maginu diffusion: Du governs A, Dv governs B (single point, 9-point Laplacian center -1 -> 1 - D; B's -B term on A counted too)",
      abs(L(o, "rd_a")[5, 5, 0] - (1 - 0.3 - 1.0)) < 1e-6 and abs(L(o, "rd_b")[5, 5, 0] - (1 - 0.8)) < 1e-6)
o, _ = rd(mode="maginu", steps=1, dt=0.5, scale_multiplier=2.0)
check("Scale Multiplier 2: reaction term halved (B' = 0.25·β)", near(L(o, "rd_b"), 0.25 * be, 1e-6))
F, K = 0.0545, 0.062
o, _ = rd(steps=1, scale_multiplier=2.0)
check("Gray-Scott + Scale Multiplier 2:U' = ½ + (−½ + ½F)/2,V' = 1 + (½ − (F+k))/2",
      near(L(o, "rd_u"), 0.5 + (-0.5 + 0.5 * F) / 2, 1e-6)
      and near(L(o, "rd_v"), 1 + (0.5 - (F + K)) / 2, 1e-6))
o, _ = rd(steps=1)
check("Scale Multiplier 1 (negative control): V' = 1 + ½ - (F+k)", near(L(o, "rd_v"), 1.5 - F - K, 1e-6))
sdfx = (J - 10).astype(float)
bimg = img_with(W, H, s=np.ones((H, W)), b=sdfx)
o, _ = rd(cop=bimg, steps=1, boundary_layer="b")
reg = J <= 10
check("Boundary: reacts as usual where SDF ≤ 0, outside the region returns to the rest state U = 1, V = 0",
      near(L(o, "rd_v")[..., 0][reg], 1.5 - F - K, 1e-6) and near(L(o, "rd_v")[..., 0][~reg], 0)
      and near(L(o, "rd_u")[..., 0][~reg], 1))
o, _ = rd(cop=bimg, steps=1, boundary_layer="b", invert_boundary=True)
check("Invert Boundary: reversed (reacts where SDF ≥ 0)",
      near(L(o, "rd_v")[..., 0][J >= 10], 1.5 - F - K, 1e-6) and near(L(o, "rd_v")[..., 0][J < 10], 0))
o, _ = rd(cop=bimg, steps=1, boundary_layer="b", boundary_threshold=3.0)
check("Boundary Threshold 3: region grows to x ≤ 13",
      near(L(o, "rd_v")[..., 0][J <= 13], 1.5 - F - K, 1e-6) and near(L(o, "rd_v")[..., 0][J > 13], 0))
o, _ = rd(cop=bimg, steps=1, boundary_layer="b", boundary_smoothing=2.0)
v = L(o, "rd_v")[0, :, 0]
check("Boundary Smoothing: weights at the edge become a 0~1 transition (monotonic)",
      0 < v[10] < 1.5 - F - K and 0 < v[11] < v[10] and np.all(np.diff(v[6:16]) <= 1e-9))
o, _ = rd(mode="maginu", cop=img_with(W, H, s=np.ones((H, W)), b=sdfx), steps=1, dt=0.5,
          boundary_layer="b")
check("Maginu + Boundary: A = B = 0 outside the region", near(L(o, "rd_a")[..., 0][~reg], 0)
      and near(L(o, "rd_b")[..., 0][~reg], 0) and near(L(o, "rd_b")[..., 0][reg], 0.5 * be, 1e-6)
      and near(L(o, "rd_a")[..., 0][reg], 1, 1e-6))
o, _ = rd(mode="maginu", steps=2, dt=0.5, normalize_model=True)
check("Normalize Model (Maginu): out = (A + 1)/2, state layers unchanged",
      near(L(o, "rd"), (A2 + 1) / 2, 1e-6) and near(L(o, "rd_a"), A2, 1e-6))
o, _ = rd(steps=1, normalize_model=True, invert_output=True)
check("Normalize (Gray-Scott unchanged) + Invert: out = 1 - V", near(L(o, "rd"), 1 - (1.5 - F - K), 1e-6))
o, _ = rd(steps=1, use_clamp_max=True, clamp_max=1.2, use_clamp_min=True, clamp_min=1.3)
check("Clamp Min then Clamp Max (min 1.3, then clamped to 1.2)", near(L(o, "rd"), 1.2, 1e-6))
o, _ = rd(steps=1, use_clamp_max=True, clamp_max=1.2)
check("Clamp Max 1.2: V = 1.38 -> 1.2, state layers not clamped",
      near(L(o, "rd"), 1.2, 1e-6) and near(L(o, "rd_v"), 1.5 - F - K, 1e-6))
o, _ = rd(steps=1, use_clamp_min=True, clamp_min=1.45)
check("Clamp Min 1.45", near(L(o, "rd"), 1.45, 1e-6))
o, _ = rd(mode="maginu", cop=None, seed_layer="", spots=0, steps=3000, du=0.1, dv=1.0,
          resolution_x=48, resolution_y=48)
A = L(o, "rd_a")
check("Maginu default α β γ + Du 0.1, Dv 1: spots grow from noise (A splits into positive and negative phases, doesn't diverge)",
      A.std() > 0.3 and np.abs(A).max() < 2 and (A > 0.3).mean() > 0.1 and (A < -0.3).mean() > 0.1,
      (float(A.std()), float(np.abs(A).max())))
o, _ = rd(mode="maginu", cop=None, seed_layer="", spots=0, steps=0,
          resolution_x=8, resolution_y=8, rand_seed=4)
A0 = L(o, "rd_a")
check("Maginu initial state: ±0.05 noise, B = 0", np.abs(A0).max() <= 0.05 and A0.std() > 0.01
      and near(L(o, "rd_b"), 0))
for bad in ({"mode": "maginu", "du": 1.0, "dt": 1.5}, {"scale_multiplier": 0.0}):
    try:
        rd(steps=1, **bad)
        check(f"raises: {bad}", False)
    except ValueError:
        check(f"raises: {bad}", True)
panel_ok(RD)


# ═══════════════════════════════════════════════════ Turing Patterns
sec("Turing Patterns → PCG_COPTuringPatterns")
TP = "PCG_COPTuringPatterns"
W, H = 12, 6


def tp(src, **kw):
    kw.setdefault("cop", img_with(src.shape[1], src.shape[0], C=src))
    return L(run0(TP, **kw), kw.get("out_layer") or "C")[..., 0]


def box1d_x(a, n, renorm=True):
    """Hand-written horizontal 2n+1 mean, outside the image not read (averaged over the count inside)."""
    out = np.zeros_like(a)
    Wd = a.shape[1]
    for x in range(Wd):
        lo, hi = max(0, x - n), min(Wd, x + n + 1)
        out[:, x] = a[:, lo:hi].mean(1)
    return out


Jt, It = np.meshgrid(np.arange(W), np.arange(H))
stepx = (Jt >= 6).astype(float)
check("Iterations 0: = Gain·original (not clamped)", near(tp(stepx * 3, iterations=0, gain=0.5), stepx * 1.5, 1e-6))
cst = np.full((H, W), 0.3)
check("constant image: blur and sharpen leave it unchanged (Gain 2 -> 0.6)", near(tp(cst, gain=2.0), 0.6, 1e-6))
check("constant image Gain 5: clamped to 1", near(tp(cst, gain=5.0), 1.0, 1e-6))
b = box1d_x(stepx, 1)
ref = np.clip(b + 2.0 * (b - box1d_x(b, 1)), 0, 1)
check("one iteration, Box radius 1, Scale 1 0 (horizontal only), outside not read: matches the hand computation",
      near(tp(stepx, filter="box", radius=1, iterations=1, scale="1 0"), ref, 1e-6))
s2 = 0.25 + 0.5 * stepx
b3 = box1d_x(s2, 1)
ref2 = np.clip(b3 + 2.0 * (b3 - box1d_x(b3, 1)), 0, 1)
ref3 = np.clip(b3 + 0.5 * (b3 - box1d_x(b3, 1)), 0, 1)
check("Power 0.5 (negative control: differs from Power 2, each matches its hand computation)",
      near(tp(s2, filter="box", radius=1, iterations=1, scale="1 0", power=0.5), ref3, 1e-6)
      and near(tp(s2, filter="box", radius=1, iterations=1, scale="1 0"), ref2, 1e-6)
      and not near(ref3, ref2, 1e-3))
check("Scale 0 1 (vertical blur only) on an image varying only along x: each row only averaged vertically = unchanged",
      near(tp(stepx, filter="box", radius=1, iterations=3, scale="0 1"), stepx, 1e-6))
g1 = tp(stepx, filter="gaussian", radius=2, iterations=1, scale="1 0")
b1 = tp(stepx, filter="box", radius=2, iterations=1, scale="1 0")
check("Gaussian differs from Box (negative control)", not near(g1, b1, 1e-3))
tt = np.arange(-2, 3, dtype=float)
gk = np.exp(-0.5 * (tt / (2 / 3)) ** 2)
gk /= gk.sum()


def gx(a):
    out = np.zeros_like(a)
    for x in range(a.shape[1]):
        idx = np.arange(x - 2, x + 3)
        ok = (idx >= 0) & (idx < a.shape[1])
        out[:, x] = (a[:, idx[ok]] * gk[ok]).sum(1) / gk[ok].sum()
    return out


bg = gx(stepx)
check("Gaussian: kernel half width = radius, σ = radius/3, outside not read, normalized by weight",
      near(g1, np.clip(bg + 2 * (bg - gx(bg)), 0, 1), 1e-6))
gi = tp(stepx, filter="box", radius=2 * 1 / 12, units="image", iterations=1, scale="1 0")
check("Units = Image: radius r·long side/2 (2/12 -> 1 pixel)", near(gi, ref, 1e-6))
wr = tp(stepx, filter="box", radius=1, iterations=1, scale="1 0", read_outside=True, border="wrap")
bw_ = (np.roll(stepx, 1, 1) + stepx + np.roll(stepx, -1, 1)) / 3
check("Read Outside + Wrap: the left edge reads the 1 from the right", near(wr, np.clip(bw_ + 2 * (bw_ - (
    np.roll(bw_, 1, 1) + bw_ + np.roll(bw_, -1, 1)) / 3), 0, 1), 1e-6) and not near(wr, ref, 1e-3))
bl = tp(cst, filter="box", radius=1, iterations=1, read_outside=True, border="black")
check("Read Outside + Black: a constant image darkened at the edges by the 0 outside; not darkened when off",
      bl[0, 0] < 0.3 - 1e-3 and near(bl[3, 5], 0.3, 1e-6))
noise = np.random.default_rng(2).random((48, 48))
pat = tp(noise, radius=3, power=8, iterations=30)
mid = ((pat > 0.1) & (pat < 0.9)).mean()
check("noise -> a pattern saturated into two phases (middle values < 20%, both phases > 20%)",
      mid < 0.2 and (pat >= 0.9).mean() > 0.2 and (pat <= 0.1).mean() > 0.2, float(mid))
N96 = 96
noise96 = np.random.default_rng(2).random((N96, N96))


def wavelength(r):
    x = tp(noise96, radius=r, power=8, iterations=30, read_outside=True, border="wrap")
    P = np.abs(np.fft.fft2(x - x.mean())) ** 2
    f = np.fft.fftfreq(N96)
    k = np.hypot(*np.meshgrid(f, f))
    return 1 / ((P * k).sum() / P.sum())


w3, w6 = wavelength(3), wavelength(6)
check("pattern wavelength follows Radius (radius doubled -> mean wavelength about doubled)", 1.6 < w6 / w3 < 2.5, (w3, w6))
mh = tp(stepx, filter="box", radius=1, iterations=1, scale="1 0", mask=0.5)
check("Mask 0.5: half and half with the original", near(mh, 0.5 * stepx + 0.5 * ref, 1e-6))
check("Mask 0.5 + Gain 2 (0 iterations): mixed with the **original**, not with the post-Gain image",
      near(tp(stepx, iterations=0, gain=2.0, mask=0.5), 1.5 * stepx, 1e-6))
check("Box radius 1.4 rounds -> 1 pixel (same as radius 1)",
      near(tp(stepx, filter="box", radius=1.4, iterations=1, scale="1 0"), ref, 1e-6))
check("Box radius 0.4 -> identity blur (only the clip remains)",
      near(tp(stepx * 0.5, filter="box", radius=0.4, iterations=2), stepx * 0.5, 1e-6))
o = run0(TP, cop=img_with(W, H, C=stepx), out_layer="T", iterations=0, gain=2.0)
check("Out Layer: writes a new layer, the original layer unchanged", near(L(o, "T")[..., 0], 2 * stepx) and near(L(o, "C")[..., 0], stepx))
panel_ok(TP)


# ═══════════════════════════════════════════════════ Heat Distort by Layer
sec("Heat Distort by Layer → PCG_COPHeatDistortByLayer")
HD = "PCG_COPHeatDistortByLayer"
N = 32
J, I = np.meshgrid(np.arange(N, dtype=float), np.arange(N, dtype=float))
XI = (J + 0.5) / 16 - 1                  # image x
rampx = J.copy()
rampy = I.copy()
inner = (J >= 4) & (J < N - 4) & (I >= 4) & (I < N - 4)


def hd(**kw):
    kw.setdefault("cop", img_with(N, N, C=np.stack([rampx, rampy], -1), noise=2.0 * XI))
    return run0(HD, **kw)


o = hd()
c = L(o, "C")
check("noise = 2·x_image -> displacement 0.05·2 image = 1.6 pixels along +x: out(x) = src(x - 1.6)",
      near(c[..., 0][inner], (J - 1.6)[inner], 1e-4) and near(c[..., 1][inner], I[inner], 1e-4))
check("noise layer not distorted (empty Layers = everything except noise)", near(L(o, "noise")[..., 0], 2 * XI, 1e-6))
c = L(hd(angle=90.0), "C")
check("Angle 90°: displacement rotated to +y", near(c[..., 1][inner], (I - 1.6)[inner], 1e-4)
      and near(c[..., 0][inner], J[inner], 1e-4))
dirl = np.stack([np.full((N, N), 0.1), np.zeros((N, N))], -1)
c = L(hd(cop=img_with(N, N, C=rampx, noise=np.zeros((N, N)), d=dirl), dir_layer="d", scale=1.0), "C")
check("Dir Layer (0.1, 0) × Scale 1: noise ignored, displacement 1.6 pixels", near(c[..., 0][inner], (J - 1.6)[inner], 1e-4))
c = L(hd(cop=img_with(N, N, C=rampx, noise=2.0 * XI, e=np.full((N, N), 0.5)), effect_layer="e"), "C")
check("Effect Layer 0.5: displacement halved", near(c[..., 0][inner], (J - 0.8)[inner], 1e-4))
c = L(hd(scale_by_timestep=True, timestep=0.5), "C")
check("Scale by Timestep (0.5): displacement × 0.5", near(c[..., 0][inner], (J - 0.8)[inner], 1e-4))
c = L(hd(scale=2.5 / 32, streak_blur=True, step_pixels=1.0), "C")    # displacement 2.5 -> n = 3
check("Streak Blur: averages n+1 = 4 points evenly spaced along the displacement (linear ramp -> half the average displacement)",
      near(c[..., 0][inner], (J - 1.25)[inner], 1e-4))
c2 = L(hd(scale=2.5 / 32), "C")
check("Streak Blur off (negative control): takes the end point", near(c2[..., 0][inner], (J - 2.5)[inner], 1e-4))
# Accurate: displacement field varies linearly along x (dir = (0.5·x_image, 0)), one step vs integrating along the field
dl = np.stack([0.5 * XI, np.zeros((N, N))], -1)
im = img_with(N, N, C=rampx, noise=np.zeros((N, N)), d=dl)
one = L(run0(HD, cop=im, dir_layer="d", scale=1.0), "C")[..., 0]
acc = L(run0(HD, cop=im, dir_layer="d", scale=1.0, accurate=True, step_pixels=0.02), "C")[..., 0]
xe = (XI * np.exp(-0.5) + 1) * 16 - 0.5        # exact solution of dX/dt = -0.5·X, t = 1
check("Accurate off: one step out = src(x - D(x))", near(one[inner], (J - 0.5 * XI * 16)[inner], 1e-4))
check("Accurate on: integrated along the field -> end point ≈ X·e^(-0.5) (curved trajectory; small steps)",
      near(acc[inner], xe[inner], 0.02), float(np.abs(acc - xe)[inner].max()))
# Blur Noise: noise is a step, the gradient exists only at the step; after blurring the gradient spreads
stepn = (J >= 16).astype(float)
cb0 = L(hd(cop=img_with(N, N, C=rampx, noise=stepn), scale=0.01), "C")[..., 0]
cb1 = L(hd(cop=img_with(N, N, C=rampx, noise=stepn), scale=0.01, blur_noise=True,
           blur_noise_size=0.2), "C")[..., 0]
check("Blur Noise: after blurring the step noise, pixels 5 away from the step are pushed too; without blur they don't move",
      abs(cb0[16, 10] - 10) < 1e-6 and cb1[16, 10] < 10 - 1e-3)
dl2 = np.stack([0.01 * XI, np.zeros((N, N))], -1)
cb2 = L(hd(cop=img_with(N, N, C=rampx, noise=stepn, d=dl2), dir_layer="d", scale=1.0,
           blur_noise=True, blur_noise_size=0.2), "C")[..., 0]
check("Blur Noise has no effect when Dir Layer is connected", near(cb2[inner], (J - 0.16 * XI)[inner], 1e-4))
chk = ((J + I) % 2).astype(float)
dconst = np.stack([np.full((N, N), 1.0 / 16), np.zeros((N, N))], -1)   # exactly 1 pixel
im = img_with(N, N, C=chk, noise=np.zeros((N, N)), d=dconst)
bs = L(run0(HD, cop=im, dir_layer="d", scale=1.0, blur_source=True, blur_source_size=1.0 / 16), "C")[..., 0]
from comfyui_pcg.geo.cop.filtersim import _gauss     # noqa: E402
gb = _gauss(chk[..., None].astype(np.float32).astype(float), 1.0)[..., 0]
check("Blur Source: displacement identical everywhere (weight 1) -> blurred first (σ = 1 pixel), then shifted 1 pixel",
      near(bs[inner], np.roll(gb, 1, 1)[inner], 1e-5))
bs0 = L(run0(HD, cop=im, dir_layer="d", scale=1.0), "C")[..., 0]
check("Blur Source off (negative control): the shifted checkerboard is still 0/1", near(bs0[inner], np.roll(chk, 1, 1)[inner], 1e-6))
rgba = np.stack([rampx, rampx, rampx, rampx], -1)
c = L(hd(cop=img_with(N, N, C=rgba, noise=2.0 * XI), chromatic=True), "C")
check("Chromatic Aberration: R / G / B displacement × 1.2 / 1.0 / 0.8, alpha follows G",
      near(c[..., 0][inner], (J - 1.92)[inner], 1e-4) and near(c[..., 1][inner], (J - 1.6)[inner], 1e-4)
      and near(c[..., 2][inner], (J - 1.28)[inner], 1e-4) and near(c[..., 3][inner], (J - 1.6)[inner], 1e-4))
c = L(hd(cop=img_with(N, N, C=rgba, noise=2.0 * XI), chromatic=True, ca_scale=0.5, ca_blue=0.0), "C")
check("CA Scale 0.5, Blue 0", near(c[..., 0][inner], (J - 0.96)[inner], 1e-4)
      and near(c[..., 2][inner], J[inner], 1e-4))
c = L(hd(mask=0.5), "C")
check("Mask 0.5", near(c[..., 0][inner], (J - 0.8)[inner], 1e-4))
YI = (I + 0.5) / 16 - 1
c = L(hd(cop=img_with(N, N, C=np.stack([rampx, rampy], -1), noise=2.0 * YI)), "C")
check("noise varying along y: displacement 1.6 pixels along +y", near(c[..., 1][inner], (I - 1.6)[inner], 1e-4)
      and near(c[..., 0][inner], J[inner], 1e-4))
c = L(hd(cop=img_with(N, N, C=np.stack([rampx, rampy], -1), noise=2.0 * YI), angle=90.0), "C")
check("gradient +y rotated 90° -> -x", near(c[..., 0][inner], (J + 1.6)[inner], 1e-4)
      and near(c[..., 1][inner], I[inner], 1e-4))
W2, H2 = 48, 24
J2, I2 = np.meshgrid(np.arange(W2, dtype=float), np.arange(H2, dtype=float))
c = L(run0(HD, cop=img_with(W2, H2, C=J2, noise=2.0 * ((J2 + 0.5) / 24 - 1))), "C")[..., 0]
check("non-square image: image units by the long side (48 -> 24 pixels per unit, displacement 2.4)",
      near(c[4:-4, 4:-4], (J2 - 2.4)[4:-4, 4:-4], 1e-4))
dly = np.stack([np.zeros((N, N)), 0.5 * YI], -1)
im = img_with(N, N, C=rampy, noise=np.zeros((N, N)), d=dly)
accy = L(run0(HD, cop=im, dir_layer="d", scale=1.0, accurate=True, step_pixels=0.02), "C")[..., 0]
ye = (YI * np.exp(-0.5) + 1) * 16 - 0.5
check("Accurate integrates a field along y correctly too", near(accy[inner], ye[inner], 0.02))
dhalf = np.stack([np.where(J >= 16, 1.0 / 16, 0.0), np.zeros((N, N))], -1)
im = img_with(N, N, C=chk, noise=np.zeros((N, N)), d=dhalf)
bh = L(run0(HD, cop=im, dir_layer="d", scale=1.0, blur_source=True, blur_source_size=1.0 / 16), "C")[..., 0]
check("Blur Source mixed by |D|/max|D|: the half with displacement 0 not blurred, the half with the largest displacement fully blurred",
      near(bh[4:-4, 4:12], chk[4:-4, 4:12], 1e-6)
      and near(bh[4:-4, 20:28], np.roll(gb, 1, 1)[4:-4, 20:28], 1e-5))
panel_ok(HD)


# ═══════════════════════════════════════════════════ Refract from Height
sec("Refract from Height -> PCG_COPRefractFromHeight (view, Height Offset, Normal / Ground / Source layers)")
RF = "PCG_COPRefractFromHeight"
W, H = 32, 16
J, I = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))
tex = 1.0 / W
flat = img_with(W, H, h=np.zeros((H, W)), z=np.zeros((H, W)), src=np.stack(
    [(J + 0.5) / W, (I + 0.5) / H], -1))
inner = (J >= 6) & (J < W - 6) & (I >= 4) & (I < H - 4)


def rf(**kw):
    kw.setdefault("cop", flat)
    kw.setdefault("layer", "h")
    return run0(RF, **kw)


hi_ = height_img()
for tl in (False, True):
    a = L(run0(RF, cop=hi_, layer="h", tile=tl), "refract")
    b = L(run0(RF, cop=img_with(24, 16, h=L(hi_, "h")[..., 0], z=np.zeros((16, 24))), layer="h",
               tile=tl, ground_layer="z", ground_scale=0.0), "refract")
    check(f"full version (all-zero ground connected) agrees with the old path (tile = {tl})", near(a, b, 1e-6))
eta = 1 / 1.33
al = math.radians(45)
st = math.cos(al) * eta
tt = st / math.sqrt(1 - st * st)
o = L(rf(view_altitude=45.0), "refract")
check("calm water, viewed at 45° (Azimuth 0): offset = -Depth·tanθt (towards -x), Snell solution",
      near(o[..., 0], -0.1 * tt / 1.0, 1e-6) and near(o[..., 1], 0, 1e-7))
o = L(rf(view_altitude=45.0, view_azimuth=90.0), "refract")
check("Azimuth 90: offset towards -y (v converted by aspect ratio)", near(o[..., 1], -0.1 * tt * W / H, 1e-6)
      and near(o[..., 0], 0, 1e-7))
o = L(rf(view_altitude=30.0, ior=1.0), "refract")
check("IOR 1, Altitude 30: straight through, offset = -Depth·cot30°",
      near(o[..., 0], -0.1 / math.tan(math.radians(30)), 1e-6))
o = L(rf(view_altitude=45.0, height_offset=0.05), "refract")
check("Height Offset 0.05: water surface raised, path length computed with 0.15", near(o[..., 0], -0.15 * tt, 1e-6))
o = L(rf(height_offset=0.05), "refract")
check("Height Offset viewed from directly above (negative control): calm water offset still 0", near(o, 0, 1e-9))
o = L(rf(directional=False, view_position=f"{(10.5) * tex} {(8.5) * tex} 0.5"), "refract")
r = np.hypot(J - 10, I - 8) * tex
sinI = r / np.hypot(r, 0.5)
sinT = sinI * eta
tanT = sinT / np.sqrt(1 - sinT ** 2)
dirx = np.where(r > 0, (J - 10) * tex / np.where(r > 0, r, 1), 0)
check("Directional off: viewed from View Position, offset 0 directly below, elsewhere Depth·tanθt in the outward direction",
      near(o[8, 10], 0, 1e-9) and near(o[..., 0], 0.1 * tanT * dirx, 1e-6))
# Normal layer: constant tilted normal = normal of a sloped height
a = 0.3
ramp = a * (J + 0.5) * tex
oh = L(run0(RF, cop=img_with(W, H, h=ramp), layer="h"), "refract")
nrm = np.broadcast_to(np.array([-a, 0, 1]) / math.hypot(a, 1), (H, W, 3))
on = L(rf(cop=img_with(W, H, h=ramp, n=nrm), normal_layer="n"), "refract")
check("Normal layer (Signed): same offset as a height field with the same slope", near(on, oh, 1e-5))
oo = L(rf(cop=img_with(W, H, h=ramp, n=nrm * 0.5 + 0.5), normal_layer="n",
          normal_type="offset"), "refract")
check("Normal Type = Offset: ×2-1 first", near(oo, oh, 1e-5))
ob = L(rf(cop=img_with(W, H, h=ramp, n=nrm * 0.5 + 0.5), normal_layer="n"), "refract")
check("Offset layer read as Signed (negative control): different", not near(ob, oh, 1e-3))
# Ground: a tilted bottom plane, viewed obliquely, Newton converges to the analytic solution in one step
c_ = -0.5                                     # bottom gets deeper towards +x (always below the water surface)
gl = c_ * (J + 0.5) * tex
cosA = math.cos(al)
Tv = np.array([-cosA * eta, 0, 0])
Iv = np.array([-cosA, 0, -math.sin(al)])
cosi = math.sin(al)
k = 1 - eta ** 2 * (1 - cosi ** 2)
T = eta * Iv + (eta * cosi - math.sqrt(k)) * np.array([0, 0, 1.0])
X = (J + 0.5) * tex
t = (-0.1 + 0.02 + 0.8 * c_ * X) / (T[2] - 0.8 * c_ * T[0])
og = L(rf(cop=img_with(W, H, h=np.zeros((H, W)), g=gl), view_altitude=45.0, ground_layer="g",
          ground_scale=0.8, ground_offset=0.02), "refract")
check("Ground layer (tilted plane z = -Depth + Offset + Scale·c·x): Newton converges to the ray-plane intersection",
      near(og[..., 0][inner], (T[0] * t)[inner], 1e-6))
og0 = L(rf(cop=img_with(W, H, h=np.zeros((H, W)), g=gl), view_altitude=45.0, ground_layer="g",
           ground_scale=0.8, ground_offset=0.02, ray_iterations=0), "refract")
check("Ray Trace Iterations 0 (negative control): stays at the initial value on the plane z = -Depth + Offset",
      near(og0[..., 0], T[0] * (0.1 - 0.02) / -T[2], 1e-6))
# Source sampling
o = rf(view_altitude=45.0, source_layer="src", refract_out_layer="R")
uv = L(o, "R")
check("Source layer: sampled at uv + offset (linear ramp -> u + ou)",
      near(uv[..., 0][inner], ((J + 0.5) / W - 0.1 * tt)[inner], 1e-6)
      and near(uv[..., 1][inner], ((I + 0.5) / H)[inner], 1e-6))
a = L(run0(RF, cop=hi_, layer="h", height_offset=0.05), "refract")
b = L(run0(RF, cop=hi_, layer="h", depth=0.15), "refract")
check("Height Offset, viewed from directly above, wavy water: same as Depth deepened by the same amount", near(a, b, 1e-6))
on2 = L(rf(cop=img_with(W, H, h=ramp, n=nrm * 3.0), normal_layer="n"), "refract")
check("Normal layer need not be unit length (normalized first)", near(on2, oh, 1e-5))
oa = L(rf(cop=img_with(W, H, h=np.zeros((H, W)), g=gl), view_altitude=45.0, ground_layer="g",
          ground_scale=0.0, ground_offset=0.2), "refract")
check("bottom above the water surface (Ground Offset 0.2): t clamped to 0, offset 0", near(oa, 0, 1e-9))
ow = L(rf(view_altitude=45.0, source_layer="src", refract_out_layer="R", tile=True), "R")
oc = L(rf(view_altitude=45.0, source_layer="src", refract_out_layer="R"), "R")
check("Tile on: sampling wraps (left edge gets the right side's value); when off it clamps to the edge", ow[8, 0, 0] > 0.5 and oc[8, 0, 0] < 0.05)
panel_ok(RF)


# ═══════════════════════════════════════════════════ Ocean Spectrum
sec("Ocean Spectrum -> PCG_COPOcean (Depth, Gravity, TMA, Distribution, Directional Movement, Loop)")
OC = "PCG_COPOcean"
from comfyui_pcg.geo.cop import sim as SIM     # noqa: E402
NO = 64
trap = getattr(np, "trapezoid", None) or getattr(np, "trapz")


def cnear(a, b, tol=1e-12):
    return np.allclose(a, b, atol=tol, rtol=0)


def spec(**kw):
    a = dict(N=NO, M=NO, size=200.0, wind_speed=12.0, wind_dir=0.0, amplitude=8.8e-4,
             align=2.0, small_cut=0.1, seed=1)
    a.update(kw)
    return SIM.ocean_spectrum(**a)


h0, KX, KY, w = spec(gravity=3.7)
k = np.hypot(KX, KY)
check("Gravity 3.7: deep-water dispersion ω = √(gk)", near(w, np.sqrt(3.7 * k), 1e-12))
h0, KX, KY, w = spec(depth=2.0)
check("Depth 2 m: finite-depth dispersion ω = √(gk·tanh(2k))", near(w, np.sqrt(9.81 * k * np.tanh(2 * k)), 1e-12))
check("shallow-water waves slower than deep-water ones (negative control)", np.all(w[k > 0] < np.sqrt(9.81 * k[k > 0])))
hn = spec(distribution="none")[0]
P = np.abs(hn) ** 2
nz = P > 1e-30
check("Distribution None: amplitude constant at √P (random phase)", near(np.abs(hn)[nz], np.sqrt(P[nz]), 1e-15)
      and np.std(np.angle(hn[nz])) > 1.5)
for dist, tol in (("gaussian", 0.1), ("uniform", 0.1), ("log_normal", 0.45)):
    hd_ = spec(distribution=dist)[0]
    ratio = (np.abs(hd_[nz]) ** 2 / P[nz]).mean()
    check(f"Distribution {dist}: E[r²] = 1 (mean energy same as None)", abs(ratio - 1) < tol, round(float(ratio), 3))
hu = spec(distribution="uniform")[0]
check("Uniform: amplitude ≤ √3·√P", np.all(np.abs(hu[nz]) <= math.sqrt(3) * np.sqrt(P[nz]) * (1 + 1e-12)))


def top_share(h):
    e = np.sort((np.abs(h[nz]) ** 2 / P[nz]))[::-1]
    return e[: len(e) // 20].sum() / e.sum()


check("Log Normal concentrates energy in fewer modes (the top 5% of modes have a larger share than with Gaussian)",
      top_share(spec(distribution="log_normal")[0]) > top_share(spec(distribution="gaussian")[0]))
hg = spec()[0]
hd1 = spec(directional_movement=1.0)[0]
dot = KX / np.where(k > 0, k, 1)
check("Directional Movement 1: h0(q) is 0 where q̂·ŵ > 0 (propagating towards -q = against the wind), otherwise unchanged",
      cnear(hd1[dot > 0], 0) and cnear(hd1[dot <= 0], hg[dot <= 0]))
hd5 = spec(directional_movement=0.5)[0]
check("Directional Movement 0.5: upwind amplitude × √0.5", cnear(hd5[dot > 0], hg[dot > 0] * math.sqrt(0.5), 1e-15))


def travel_corr(h0, KX, KY, w):
    f0 = SIM.ocean_fields(h0, KX, KY, w, 0.0, 0.0)
    f1 = SIM.ocean_fields(h0, KX, KY, w, 0.01, 0.0)
    dhdt = (f1["height"] - f0["height"]).ravel()
    return float(np.corrcoef(dhdt, f0["sx"].ravel())[0, 1])


c1 = travel_corr(*spec(directional_movement=1.0))
c0 = travel_corr(*spec())
check("Directional Movement 1: waves run downwind (+x), ∂h/∂t and ∂h/∂x strongly negatively correlated; nearly uncorrelated at 0",
      c1 < -0.8 and abs(c0) < 0.3, (round(c1, 3), round(c0, 3)))
o0 = run0(OC, resolution_x=32, resolution_y=32, loop_period=4.0, time=0.3)
o1 = run0(OC, resolution_x=32, resolution_y=32, loop_period=4.0, time=4.3)
o2 = run0(OC, resolution_x=32, resolution_y=32, time=4.3)
o3 = run0(OC, resolution_x=32, resolution_y=32, time=0.3)
check("Loop Period 4 s: the ocean at t and t + 4 is the same; different without looping",
      near(L(o0, "ocean"), L(o1, "ocean"), 1e-4) and not near(L(o2, "ocean"), L(o3, "ocean"), 1e-3))
check("Loop Period changes ω (differs from non-looping at t = 0.3)", not near(L(o0, "ocean"), L(o3, "ocean"), 1e-4))
# TMA
for sv in (0.0, 3.0, 20.0):
    th = np.linspace(-math.pi, math.pi, 20001)
    D = SIM.hasselmann_spread(th, np.full_like(th, 1.3), 1.0, 12.0, 0.0, 9.81) if sv == 0 else \
        SIM.hasselmann_spread(th, np.full_like(th, 1.0 / (1 + sv)), 1.0, 12.0, 0.5, 9.81)
    check(f"Hasselmann directional spreading integrates to 1 over θ (set {int(sv)})", abs(trap(D, th) - 1) < 1e-3)
U, Fk = 10.0, 100.0
size, NT = 600.0, 128
hT, KX, KY, wT = SIM.ocean_spectrum(NT, NT, size, U, 0.0, 8.8e-4, 2.0, 0.0, 1, spectrum="tma",
                                    fetch_km=Fk, distribution="none")
var = 2 * (np.abs(hT) ** 2).sum()
kmax = math.pi * NT / size
om = np.linspace(1e-3, math.sqrt(9.81 * kmax), 200001)
S, wp = SIM.tma_spectrum(om, U, Fk * 1000, 0.0, 9.81)
m0 = trap(S, om)
check("TMA: height variance 2Σ|h0|² ≈ ∫S(ω)dω (up to the grid's max wavenumber, within 10%)", abs(var / m0 - 1) < 0.1,
      (float(var), float(m0)))
Hs = 4 * math.sqrt(m0)
check("TMA (deep water) = JONSWAP: significant wave height for U 10 m/s, Fetch 100 km is 2~3 m (JONSWAP's order of magnitude)",
      2.0 < Hs < 3.0, Hs)
S5, _ = SIM.tma_spectrum(om, U, Fk * 1000, 5.0, 9.81)
check("TMA shallow water (5 m) Kitaigorodskii attenuation: less energy", trap(S5, om) < 0.8 * m0)
v2 = 2 * (np.abs(SIM.ocean_spectrum(NT, NT, size, U, 0.0, 8.8e-4, 2.0, 0.0, 1, spectrum="tma",
                                     fetch_km=300.0, distribution="none")[0]) ** 2).sum()
check("larger Fetch -> bigger waves", v2 > var)


def mean_cos(h, KX, KY):
    e = np.abs(h) ** 2
    th = np.arctan2(-KY, -KX)
    return float((e * np.cos(th)).sum() / e.sum()), float(e[np.cos(th) < 0].sum() / e.sum())


mc0, up0 = mean_cos(hT, KX, KY)
hs2 = SIM.ocean_spectrum(NT, NT, size, U, 0.0, 8.8e-4, 2.0, 0.0, 1, spectrum="tma",
                         fetch_km=Fk, swell=1.0, distribution="none")[0]
hsn = SIM.ocean_spectrum(NT, NT, size, U, 0.0, 8.8e-4, 2.0, 0.0, 1, spectrum="tma",
                         fetch_km=Fk, swell=-1.0, distribution="none")[0]
mc2, up2 = mean_cos(hs2, KX, KY)
mcn, upn = mean_cos(hsn, KX, KY)
check("TMA energy mostly propagates downwind (propagation direction = -q)", mc0 > 0.5, mc0)
check("Swell > 0 more concentrated downwind; Swell < 0 more spread out, more upwind energy",
      mc2 > mc0 > mcn and upn > up0 >= up2, (mc2, mc0, mcn, upn, up0))
ct = travel_corr(*SIM.ocean_spectrum(NT, NT, size, U, 0.0, 8.8e-4, 2.0, 0.0, 1, spectrum="tma",
                                     fetch_km=Fk))
check("TMA waves run downwind (∂h/∂t and ∂h/∂x negatively correlated)", ct < -0.5, ct)
# Formula checked term by term (JONSWAP / Kitaigorodskii / Hasselmann written out by hand)
g_ = 9.81
U_, F_ = 10.0, 1e5
a_ = 0.076 * (U_ * U_ / (F_ * g_)) ** 0.22
wp_ = 22 * (g_ * g_ / (U_ * F_)) ** (1 / 3)
ws_ = np.array([0.9 * wp_, 1.2 * wp_])
sg_ = np.array([0.07, 0.09])
Sj = a_ * g_ ** 2 / ws_ ** 5 * np.exp(-1.25 * (wp_ / ws_) ** 4) * 3.3 ** np.exp(
    -(ws_ - wp_) ** 2 / (2 * sg_ ** 2 * wp_ ** 2))
check("JONSWAP on both sides of the peak (σ = 0.07 / 0.09) matches the hand computation",
      near(SIM.tma_spectrum(ws_, U_, F_, 0.0, g_)[0], Sj, 1e-12))
hh = 3.0
wq = np.array([0.5, 1.5, 2.5]) / math.sqrt(hh / g_)            # ω_h = 0.5 / 1.5 / 2.5
phi_ = np.array([0.5 * 0.25, 1 - 0.5 * 0.25, 1.0])
check("Kitaigorodskii Φ three pieces (½ω², 1 - ½(2-ω)², 1)",
      near(SIM.tma_spectrum(wq, U_, F_, hh, g_)[0] / SIM.tma_spectrum(wq, U_, F_, 0.0, g_)[0], phi_, 1e-12))
for rr_, s_ in ((0.5, 6.97 * 0.5 ** 4.06), (2.0, 9.77 * 2.0 ** (-2.33 - 1.45 * (12.0 * 1.0 / g_ - 1.17)))):
    Q = 2 ** (2 * s_ - 1) / math.pi * math.gamma(s_ + 1) ** 2 / math.gamma(2 * s_ + 1)
    got = SIM.hasselmann_spread(np.array([0.0, 1.0]), np.array([rr_, rr_]), 1.0, 12.0, 0.0, g_)
    check(f"Hasselmann s(ω/ωp = {rr_}): D(0) = Q(s), D(1) = Q·cos^(2s)(½)",
          near(got, [Q, Q * abs(math.cos(0.5)) ** (2 * s_)], 1e-10))
hp = spec(gravity=3.7, distribution="none")[0]
KXp, KYp = spec()[1], spec()[2]
kp_ = np.hypot(KXp, KYp)
ksp = np.where(kp_ > 0, kp_, 1)
Lg = 12.0 ** 2 / 3.7
Pp = 8.8e-4 * np.exp(-1 / (ksp * Lg) ** 2) / ksp ** 4 * np.abs(KXp / ksp) ** 2 * np.exp(-(ksp * 0.1) ** 2)
Pp = np.where(kp_ > 0, Pp, 0) * (2 * math.pi / 200) ** 2
Pp[NO // 2, :] = 0
Pp[:, NO // 2] = 0
check("Phillips' L = V²/g uses the Gravity parameter", near(np.abs(hp) ** 2, Pp, 1e-12))
hT5, KX, KY, _ = SIM.ocean_spectrum(NT, NT, size, U, 0.0, 8.8e-4, 2.0, 0.0, 1, spectrum="tma",
                                    fetch_km=Fk, distribution="none", depth=5.0)
om5 = np.linspace(1e-3, math.sqrt(9.81 * kmax * math.tanh(kmax * 5.0)), 200001)
m05 = trap(SIM.tma_spectrum(om5, U, Fk * 1000, 5.0, 9.81)[0], om5)
v5 = 2 * (np.abs(hT5) ** 2).sum()
check("TMA finite depth (5 m): variance ≈ ∫S_TMA dω (dω/dk uses the finite-depth group velocity)", abs(v5 / m05 - 1) < 0.1,
      (float(v5), float(m05)))
o = run0(OC, resolution_x=32, resolution_y=32, spectrum_type="tma", size=300.0)
check("node in TMA mode runs and outputs finite values", np.isfinite(L(o, "ocean")).all() and np.abs(L(o, "ocean")).max() > 0.05)
for bad in ({"spectrum": "x"}, {"distribution": "x"}, {"spectrum": "tma", "fetch_km": 0.0}):
    try:
        spec(**bad)
        check(f"raises: {bad}", False)
    except ValueError:
        check(f"raises: {bad}", True)
panel_ok(OC)


# ═══════════════════════════════════════════════════ Summary
n = len(OK)
p = sum(OK)
print(f"\n{p}/{n} passed")
sys.exit(0 if p == n else 1)
