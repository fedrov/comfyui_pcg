"""
Copernicus completion batch E: UV / tiling / SDF / ID (uvx.py + the 10 nodes in nodes_cop2.py).

━━ Criteria
  · UV Map: identity = pixel centers; by_id: with stretch each piece's uv exactly covers [½/bw,
    1 − ½/bw], with fit the short side is centered and the aspect ratio is right
  · UV Transform: rotating 90° about the Pivot sends (1, ½) to (½, 1); transform then inverse transform =
    identity; wrap lands in [0, 1)
  · UV Sample: identity uv sampling itself = the original image (per pixel); whole-pixel shift + wrap = np.roll;
    latlong / mirror-ball direction convention (+Y at the top, +X at u = ½, the direction facing the camera at the ball center)
  · UV Inverse: the inverse of a whole-pixel shift = the opposite shift, coverage all 1; sample then sample back with the inverse =
    the original image
  · Polar: to_polar's lookup point is exactly center + r(cos θ, sin θ); to -> from round trip
  · Hex Tile: barycentric weights ≥ 0, sum to 1, (1, 0, 0) at a hexagon center; constant texture -> constant;
    higher Contrast means more pixels dominated by a single copy
  · Triplanar: normals all +Z -> exactly the XY planar projection (per pixel); constant -> constant;
    Sharpness 0 -> the three axes weighted equally
  · Retile: shuffle is a permutation of tiles (each tile used exactly once); seamless seam difference = the difference of the
    original's two center columns (the edges use the half-width-shifted copy)
  · SDF: with smooth 0, union / intersect / subtract = min / max / max(a, −b); the smooth
    version ≤ min, equals min where the gap ≥ k; blend at both ends; fill area = πr²
  · ID: range syntax; invert; SDF of the selected region matches brute-force distance; without a selection the boundary = 0.5
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
from comfyui_pcg.geo.cop import uvx as UX                # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
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
    return PX.getn(img, name)


def mk(**lay):
    first = next(iter(lay.values()))
    H, W = first.shape[:2]
    return CopImage(W, H, {k: np.asarray(v, np.float64) for k, v in
                           lay.items()})


rng = np.random.default_rng(11)
H, W = 40, 56
J, I = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))
U0, V0 = (J + 0.5) / W, (I + 0.5) / H
img = rng.random((H, W, 3))

# ═══════════════════════════════════════════════════════ UV Map / Transform
sec("UV Map / UV Transform")
uv = L(UX.uv_map(None, xres=W, yres=H), "uv")
check("identity = pixel centers", np.allclose(uv[..., 0], U0) and
      np.allclose(uv[..., 1], V0))
uv2 = L(UX.uv_map(None, scale="2 2", xres=W, yres=H), "uv")
check("  scale 2 about (½, ½)", np.allclose(uv2[..., 0], (U0 - 0.5) * 2 + 0.5,
                                         atol=1e-6))
ids = np.zeros((H, W, 1)); ids[5:20, 5:30] = 1; ids[25:37, 40:48] = 2
bi = mk(id=ids)
st = L(UX.uv_map(bi, "by_id", fit="stretch"), "uv")
m1 = ids[..., 0] == 1
check("by_id stretch: piece 1 (25×15) uv covers [½/bw, 1 − ½/bw]",
      np.isclose(st[m1, 0].min(), 0.5 / 25) and np.isclose(
          st[m1, 0].max(), 1 - 0.5 / 25) and np.isclose(
          st[m1, 1].min(), 0.5 / 15), (st[m1, 0].min(), st[m1, 1].min()))
ft = L(UX.uv_map(bi, "by_id", fit="fit"), "uv")
check("by_id fit: keeps the aspect ratio (v span = 15/25), centered",
      np.isclose(ft[m1, 1].max() - ft[m1, 1].min(), 14 / 25) and
      np.isclose((ft[m1, 1].max() + ft[m1, 1].min()) / 2, 0.5))
check("  pixels with id 0 have uv = 0", np.all(st[ids[..., 0] == 0] == 0))
p = np.array([[[1.0, 0.5]]])
r = UX.transform_uv(p, "0 0", 90, "1 1", "0.5 0.5")
check("90° about (½, ½): (1, ½) -> (½, 1)", np.allclose(r, [[[0.5, 1.0]]]))
q = rng.random((10, 10, 2))
fw = UX.transform_uv(q, "0.1 -0.3", 37, "2 0.5", "0.2 0.7")
# Inverse: subtract the translation, rotate by −θ, then divide by the scale (all about the pivot)
bk = UX.transform_uv(fw - np.array([0.1, -0.3]), "0 0", -37, "1 1",
                     "0.2 0.7")
bk = (bk - np.array([0.2, 0.7])) / np.array([2, 0.5]) + np.array([0.2, 0.7])
check("  scale, then rotate, then translate: undoing in reverse order gives the original", np.allclose(bk, q))
w_ = L(UX.uv_transform(mk(uv=uv), "uv", "3.7 -2.2", 10, wrap=True), "uv")
check("  wrap lands in [0, 1)", w_.min() >= 0 and w_.max() < 1)

# ═══════════════════════════════════════════════════════ UV Sample
sec("UV Sample")
base = mk(C=img, uv=np.stack([U0, V0], -1))
s0 = L(UX.uv_sample(base, None, "uv", "C", border="clamp"), "sampled")
check("identity uv sampling itself = the original image (1e-12)", np.abs(s0 - img).max() < 1e-12)
sh = np.stack([U0 + 3 / W, V0 - 2 / H], -1)
s1 = L(UX.uv_sample(mk(C=img, uv=sh), None, "uv", "C", border="wrap"),
       "sampled")
check("shift by (3, −2) pixels + wrap = np.roll", np.abs(
    s1 - np.roll(img, (2, -3), (0, 1))).max() < 1e-12)
src = CopImage(64, 32, {"C": np.stack(np.meshgrid(
    (np.arange(64) + 0.5) / 64, (np.arange(32) + 0.5) / 32), -1)})
dirs = np.array([[[0, 1, 0], [1, 0, 0], [0, 0, -1], [0, -1, 0]]], float)
ll = L(UX.uv_sample(mk(d=dirs), src, "d", "C", "latlong", "clamp"),
       "sampled")[0]
check("latlong: +X at u = ½, −Z at u = ¾ (counter-clockwise about +Y), +Y at the top",
      np.isclose(ll[1, 0], 0.5, atol=0.01) and np.isclose(ll[2, 0], 0.75,
                                                             atol=0.01)
      and ll[0, 1] > 0.98 and ll[3, 1] < 0.02, ll.round(3))
mbd = np.array([[[0, 0, 1], [1, 0, 0]]], float)
mb = L(UX.uv_sample(mk(d=mbd), CopImage(64, 64, {"C": np.stack(
    np.meshgrid((np.arange(64) + 0.5) / 64, (np.arange(64) + 0.5) / 64),
    -1)}), "d", "C", "mirror_ball", "clamp"), "sampled")[0]
check("mirror ball: the direction facing the camera at the ball center; +X at u = ½ + ½·sin45°",
      np.allclose(mb[0], [0.5, 0.5], atol=0.01) and
      np.isclose(mb[1, 0], 0.5 + 0.5 / math.sqrt(2), atol=0.01), mb.round(3))
err("uv layer with too few channels raises", lambda: UX.uv_sample(mk(C=img, uv=img[..., :1]),
                                             None, "uv"), "2-channel")

# ═══════════════════════════════════════════════════════ UV Inverse
sec("UV Inverse")
fw_uv = np.stack([np.mod(U0 + 5 / W, 1), np.mod(V0 + 3 / H, 1)], -1)
iv = UX.uv_inverse(mk(uv=fw_uv), "uv")
ivu = L(iv, "uv_inverse")
check("inverse of a whole-pixel shift = the opposite shift, coverage all 1",
      np.all(L(iv, "uv_inverse_mask") == 1) and
      np.allclose(ivu[..., 0], np.mod(U0 - 5 / W, 1)) and
      np.allclose(ivu[..., 1], np.mod(V0 - 3 / H, 1)))
fwd_img = L(UX.uv_sample(mk(C=img, uv=fw_uv), None, "uv", "C",
                         border="wrap"), "sampled")
back = L(UX.uv_sample(mk(C=fwd_img, uv=ivu), None, "uv", "C", border="wrap"),
         "sampled")
check("  sample with the mapping, then sample back with the inverse = the original image", np.abs(back - img).max() < 1e-9)
half = np.stack([U0 * 0.5, V0 * 0.5], -1)
iv2 = UX.uv_inverse(mk(uv=half), "uv")
cov = L(iv2, "uv_inverse_mask")
check("  mapping squeezed into the lower-left quarter: only that block is covered, the rest is filled in",
      cov[:H // 2, :W // 2].mean() > 0.95 and cov[H // 2:, W // 2:].max() == 0)
iu = L(iv2, "uv_inverse")
jj_ = np.arange(W // 2)
check("  several outputs falling into the same cell are averaged: source column j = average u of output columns 2j, 2j+1",
      np.allclose(iu[0, :W // 2, 0], (2 * jj_ + 1) / W))
check("  uncovered areas are filled in (not 0); with fill off they are 0",
      iu[H - 1, W - 1, 0] > 0.3 and L(UX.uv_inverse(mk(uv=half), "uv",
                                                    fill=False),
                                      "uv_inverse")[H - 1, W - 1, 0] == 0)
iv3 = UX.uv_inverse(mk(uv=half), "uv", source_res="28 20")
check("  if Source Res is given, the output uses that resolution", iv3.xres == 28 and iv3.yres == 20)

# ═══════════════════════════════════════════════════════ Polar
sec("Polar")
S = 96
Js, Is = np.meshgrid(np.arange(S, dtype=float), np.arange(S, dtype=float))
Us, Vs = (Js + 0.5) / S, (Is + 0.5) / S
co = mk(P=np.stack([Us, Vs], -1))
tp = L(UX.polar(co, "P", "to_polar", "0.5 0.5", 0.4, 30, "clamp"), "P")
th = math.radians(30) + Us * 2 * math.pi
ex_u = 0.5 + Vs * 0.4 * np.cos(th)
ex_v = 0.5 + Vs * 0.4 * np.sin(th)
check("to_polar: (u, v) looks up center + v·R·(cos(θ₀ + 2πu), sin(…))",
      np.abs(tp[..., 0] - ex_u).max() < 1e-9 and np.abs(tp[..., 1] - ex_v)
      .max() < 1e-9)
Wr, Hr = 96, 48
Jr, Ir = np.meshgrid(np.arange(Wr, dtype=float), np.arange(Hr, dtype=float))
tr_ = L(UX.polar(mk(P=np.stack([(Jr + 0.5) / Wr, (Ir + 0.5) / Hr], -1)), "P",
                 "to_polar", "0.5 0.5", 0.2, 0, "clamp"), "P")
ru = (tr_[..., 0] - 0.5) * Wr
rv = (tr_[..., 1] - 0.5) * Hr
check("  non-square image (96×48): the lookup points form a circle in **pixel** terms (radius = v·R·W)",
      np.allclose(np.hypot(ru, rv), ((Ir + 0.5) / Hr) * 0.2 * Wr))
smooth = np.sin(Js / 9)[..., None] * np.cos(Is / 7)[..., None] + 1
fp = UX.polar(UX.polar(mk(C=smooth), "C", "to_polar", radius=0.5,
                       angle=30), "C", "from_polar", radius=0.5, angle=30)
rr = np.hypot(Us - 0.5, Vs - 0.5)
sel = (rr > 0.08) & (rr < 0.42)
check("to -> from round trip (inside the ring, smooth image, Angle 30°, ±0.03)",
      np.abs(L(fp, "C")[..., 0] - smooth[..., 0])[sel].max() < 0.03,
      np.abs(L(fp, "C")[..., 0] - smooth[..., 0])[sel].max())
fb = L(UX.polar(mk(C=np.ones((S, S, 1))), "C", "from_polar", radius=0.3,
                border="black"), "C")[..., 0]
check("from_polar + black: 0 beyond the radius", fb[0, 0] == 0 and
      fb[S // 2, S // 2] == 1)

# ═══════════════════════════════════════════════════════ Hex / Triplanar
sec("Hex Tile / Triplanar")
xs = rng.random(5000) * 10
ys = rng.random(5000) * 10
verts, ws = UX._hex_grid(xs, ys)
tot = ws[0] + ws[1] + ws[2]
check("barycentric weights ≥ 0, sum to 1", min(w.min() for w in ws) >= -1e-12 and
      np.allclose(tot, 1))
# Integer points in skewed space are hexagon centers: back to the plane x = sx + sy/2, y = sy·√3/2
cx = np.array([2.0 + 3 / 2, 0.0 + 1 / 2])
cy = np.array([3 * math.sqrt(3) / 2, 1 * math.sqrt(3) / 2])
_, wc = UX._hex_grid(cx + 1e-9, cy + 1e-9)
check("  at a hexagon center, one weight = 1", np.allclose(np.max(np.stack(wc), 0),
                                                 1, atol=1e-6))
ct = L(UX.hex_tile(mk(C=np.full((32, 32, 3), 0.4))), "hex")
check("constant texture -> constant", np.abs(ct - 0.4).max() < 1e-12)
tex = rng.random((32, 32, 1))
hx = L(UX.hex_tile(mk(C=tex), tiles=3, xres=128, yres=128), "hex")
check("  mean ≈ source image mean (±0.05)", abs(hx.mean() - tex.mean()) < 0.05)
verts2, w2 = UX._hex_grid(xs, ys)
dom = [np.mean(np.max(np.stack([np.power(w, 1 + 8 * c) for w in w2]) /
                      np.sum(np.stack([np.power(w, 1 + 8 * c) for w in w2]),
                             0), 0) > 0.9) for c in (0.0, 1.0)]
check("  higher Contrast: more pixels dominated (> 90%) by a single copy", dom[1] > dom[0] + 0.3,
      dom)

Pl = np.stack([Us * 3, Vs * 2, np.full_like(Us, 0.7)], -1)
Nz = np.zeros((S, S, 3)); Nz[..., 2] = 1
srcT = CopImage(16, 16, {"C": rng.random((16, 16, 3))})
tri = L(UX.triplanar(mk(P=Pl, N=Nz), srcT, sharpness=4), "triplanar")
from comfyui_pcg.geo.cop.filters import sample as _smp   # noqa: E402
check("normals all +Z -> exactly the XY planar projection (per pixel)", np.abs(
    tri - _smp(L(srcT, "C"), Pl[..., 0], Pl[..., 1], "wrap")).max() < 1e-12)
Nr = rng.normal(size=(S, S, 3))
tc = L(UX.triplanar(mk(P=Pl, N=Nr), CopImage(4, 4, {"C": np.full(
    (4, 4, 1), 0.3)}), sharpness=3, hex=True), "triplanar")
check("constant -> constant (including hex)", np.abs(tc - 0.3).max() < 1e-12)
t0 = L(UX.triplanar(mk(P=Pl, N=Nr), srcT, sharpness=0), "triplanar")
eq = sum(_smp(L(srcT, "C"), a_, b_, "wrap") for a_, b_ in (
    (Pl[..., 2], Pl[..., 1]), (Pl[..., 0], Pl[..., 2]),
    (Pl[..., 0], Pl[..., 1]))) / 3
check("Sharpness 0 -> the three axes weighted equally", np.abs(t0 - eq).max() < 1e-12)
tuv = L(UX.triplanar(mk(P=Pl, N=Nz), srcT, uv_layer="tuv"), "tuv")
check("  Triplanar UV: dominant axis Z -> fractional part of (x, y)", np.allclose(
    tuv[..., 0], np.mod(Pl[..., 0], 1)) and np.allclose(tuv[..., 1],
                                                        np.mod(Pl[..., 1], 1)))

# ═══════════════════════════════════════════════════════ Retile
sec("Retile")
T64 = rng.random((64, 64, 2))
rt = L(UX.retile(mk(C=T64), "C", "shuffle", "4 4", rotate=False, seed=3),
       "C")
tiles_in = sorted(T64[i:i + 16, j:j + 16].tobytes() for i in range(0, 64, 16)
                  for j in range(0, 64, 16))
tiles_out = sorted(rt[i:i + 16, j:j + 16].tobytes() for i in range(0, 64, 16)
                   for j in range(0, 64, 16))
check("shuffle: a permutation of tiles (each tile used exactly once)", tiles_in == tiles_out)
check("  and it really is shuffled", not np.array_equal(rt, T64))
rr_ = L(UX.retile(mk(C=T64), "C", "shuffle", "4 4", rotate=True, seed=3),
        "C")
check("  90°-rotation version: the multiset of values per cell is unchanged", sorted(np.round(
    rr_[:16, :16].ravel(), 12).tolist()) in [sorted(np.round(
        T64[i:i + 16, j:j + 16].ravel(), 12).tolist()) for i in range(0, 64, 16)
        for j in range(0, 64, 16)])
err("  non-square cells with rotation raises", lambda: UX.retile(mk(C=np.zeros((32, 64, 1))),
                                            "C", "shuffle", "4 4"), "square cells")
grad = np.repeat((J / W)[..., None], 1, -1)
sm_ = L(UX.retile(mk(C=grad), "C", "seamless", blend=0.3), "C")
seam = np.abs(sm_[:, 0] - sm_[:, -1]).max()
check("seamless: left/right seam difference = the difference of the original's two center columns (1 / W)",
      np.isclose(seam, 1 / W), (seam, 1 / W))
a_r = rng.random((H, W, 1))
sr_ = L(UX.retile(mk(C=a_r), "C", "seamless", blend=0.3), "C")
check("  left and right edges use the copy shifted by half the width: row 0, column 0 = original (H/2, W/2)"
      " (u first, then v, done separately)",
      np.isclose(sr_[0, 0], a_r[H // 2, W // 2]) and
      np.isclose(sr_[0, -1], a_r[H // 2, W // 2 - 1]))
# There must be no seam anywhere in the image (including the wrap-around one): a ramp periodic in neither x nor y,
# after which adjacent pixel differences everywhere are on the order of the ramp itself. The old code shifted both directions at once + blended by min,
# and the shifted copy's center cross seam showed up "in the middle column near the top and bottom edges", off by ~1
ramp = (J / W + I / H)[..., None]
sp_ = L(UX.retile(mk(C=ramp), "C", "seamless", blend=0.5), "C")[..., 0]
dx = np.abs(np.diff(np.concatenate([sp_, sp_[:, :1]], 1), axis=1)).max()
dy = np.abs(np.diff(np.concatenate([sp_, sp_[:1]], 0), axis=0)).max()
check("  no seam anywhere (including the wrap-around one): adjacent pixel diff ≤ 4 / side length", dx <= 4 / W and dy <= 4 / H,
      (round(float(dx * W), 2), round(float(dy * H), 2)))
Jx_ = np.arange(W)[None, :]
Iy_ = np.arange(H)[:, None]
du_ = np.minimum(Jx_, W - 1 - Jx_) / ((W - 1) / 2)
dv_ = np.minimum(Iy_, H - 1 - Iy_) / ((H - 1) / 2)
t_ = np.clip(np.minimum(du_, dv_) / 0.5, 0, 1)
w_ = t_ * t_ * (3 - 2 * t_)
old_ = ramp[..., 0] * w_ + np.roll(ramp[..., 0], (H // 2, W // 2), (0, 1)) * (1 - w_)
dx_old = np.abs(np.diff(old_, axis=1)).max()
check("  negative control: the old blend-both-directions-at-once version has a seam in the middle (diff > 0.5)", dx_old > 0.5,
      round(float(dx_old), 3))
check("  center region unchanged", np.allclose(sm_[H // 2 - 2:H // 2 + 2,
                                          W // 2 - 2:W // 2 + 2],
                                      grad[H // 2 - 2:H // 2 + 2,
                                           W // 2 - 2:W // 2 + 2]))

# ═══════════════════════════════════════════════════════ SDF / ID
sec("SDF / ID")
a_ = rng.normal(size=(H, W, 1)); b_ = rng.normal(size=(H, W, 1))
si = mk(sdf=a_, sdf_b=b_)
for op, want in (("union", np.minimum(a_, b_)), ("intersect",
                                                  np.maximum(a_, b_)),
                 ("subtract", np.maximum(a_, -b_))):
    check(f"{op} (smooth 0) = closed form", np.allclose(L(UX.sdf_ops(si, op=op),
                                                "sdf_out"), want))
k = 0.3
su = L(UX.sdf_ops(si, op="union", smooth=k), "sdf_out")
far = np.abs(a_ - b_) >= k
check("smooth union ≤ min, = min where the gap ≥ k",
      np.all(su <= np.minimum(a_, b_) + 1e-12) and
      np.allclose(su[far], np.minimum(a_, b_)[far]))
check("  k/4 below min where the difference is 0", np.isclose(UX.smin(np.array(0.2),
                                                   np.array(0.2), k),
                                             0.2 - k / 4))
check("blend t = 0 / 1 at both ends", np.allclose(L(UX.sdf_ops(si, op="blend", t=0),
                                           "sdf_out"), a_) and
      np.allclose(L(UX.sdf_ops(si, op="blend", t=1), "sdf_out"), b_))
check("offset / onion", np.allclose(L(UX.sdf_ops(si, op="offset",
                                                 amount=0.2), "sdf_out"),
                                    a_ - 0.2) and
      np.allclose(L(UX.sdf_ops(si, op="onion", amount=0.2), "sdf_out"),
                  np.abs(a_) - 0.2))
Sc = 128
Jc, Ic = np.meshgrid(np.arange(Sc) + 0.5, np.arange(Sc) + 0.5)
circ = (np.hypot(Jc - 64, Ic - 64) / Sc - 0.25)[..., None]   # short-side units
fill = L(UX.sdf_to_mono(mk(sdf=circ), "sdf", "fill", 1 / Sc), "mask")
check("fill: circle area = πr² (±0.5%)", abs(fill.sum() / (math.pi * 32 ** 2)
                                       - 1) < 0.005)
ol = L(UX.sdf_to_mono(mk(sdf=circ), "sdf", "outline", 3, "pixels"), "mask")
check("outline 3 pixels: total ≈ perimeter × 3 (±3%)", abs(ol.sum() / (
    2 * math.pi * 32 * 3) - 1) < 0.03, ol.sum() / (2 * math.pi * 32 * 3))
fo = L(UX.sdf_to_mono(mk(sdf=circ), "sdf", "falloff", 0.1), "mask")
check("falloff: 1 inside, decreasing monotonically to 0 outside", fo[64, 64] == 1 and fo[64, 127] < 1
      and fo[0, 0] == 0)

idm = np.array([[0, 1, 2, 3, 4, 5, 6, 7]], float).T[None] * np.ones(
    (1, 1, 1))
idm = np.arange(8, dtype=float).reshape(1, 8, 1)
mm = L(UX.id_convert(mk(id=idm), "id", "mask", "1 3-5"), "id_mask")[0, :, 0]
check("ID to Mask:'1 3-5'", mm.tolist() == [0, 1, 0, 1, 1, 1, 0, 0])
mi = L(UX.id_convert(mk(id=idm), "id", "mask", "1 3-5", invert=True),
       "id_mask")[0, :, 0]
check("  invert", mi.tolist() == [1, 0, 1, 0, 0, 0, 1, 1])
mo = L(UX.id_convert(mk(id=idm), "id", "mono"), "id_mono")[0, :, 0]
check("ID to Mono: normalized to 0~1", np.allclose(mo, np.arange(8) / 7))
blk = np.zeros((30, 30, 1)); blk[8:20, 5:25] = 2; blk[20:26, 10:14] = 5
sd = L(UX.id_convert(mk(id=blk), "id", "sdf", "2"), "id_sdf")[..., 0]
sel2 = blk[..., 0] == 2
Jb, Ib = np.meshgrid(np.arange(30), np.arange(30))
ok = True
for (i, j) in [(10, 10), (15, 3), (2, 2), (22, 12), (8, 5)]:
    other = sel2 != sel2[i, j]
    dmin = np.hypot(Jb[other] - j, Ib[other] - i).min()
    want = -(dmin - 0.5) if sel2[i, j] else dmin - 0.5
    ok &= abs(sd[i, j] - want) < 1e-9
check("ID to SDF (selecting id 2): matches brute-force distance, negative inside, positive outside", ok)
pb = L(UX.id_convert(mk(id=blk), "id", "sdf", ""), "id_sdf")[..., 0]
check("  Ids left empty: distance to other ids ≥ ½, ½ on both sides of the boundary",
      pb.min() == 0.5 and pb[7, 10] == 0.5 and pb[8, 10] == 0.5)
err("  selection covering the whole image raises", lambda: UX.id_convert(mk(id=np.ones((4, 4, 1))),
                                               "id", "sdf", "1"), "SDF")

# ═══════════════════════════════════════════════════════ torch / nodes
sec("torch / nodes")
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
if BK.get("cpu") is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    tb = CopImage(W, H, {"C": img.astype(np.float32),
                         "uv": np.stack([U0, V0], -1).astype(np.float32)}) \
        .to_device("cpu")
    for nm, fn in (("uv_sample", lambda z: UX.uv_sample(z, None, "uv", "C",
                                                        border="clamp")),
                   ("polar", lambda z: UX.polar(z, "C"))):
        o_t = fn(tb)
        o_n = fn(CopImage(W, H, {"C": img.astype(np.float32), "uv": np.stack(
            [U0, V0], -1).astype(np.float32)}))
        ln = "sampled" if nm == "uv_sample" else "C"
        check(f"[torch] {nm}: output still on torch, matches numpy",
              o_t.backend.is_torch and np.allclose(L(o_t, ln), L(o_n, ln),
                                                   atol=1e-5))
E_ = ["PCG_COPUVMap", "PCG_COPUVSample", "PCG_COPUVTransform",
      "PCG_COPUVInverse", "PCG_COPPolar", "PCG_COPHexTile",
      "PCG_COPTriplanar", "PCG_COPRetile", "PCG_COPSDFOps",
      "PCG_COPIDConvert"]
check(f"all {len(E_)} batch E nodes registered, all under PCG/cop",
      all(k in MAP and MAP[k].CATEGORY == "PCG/cop" for k in E_))
bad = [k for k in E_ for nm in MAP[k].INPUT_TYPES()["required"]
       if nm == "seed"]
check("  no widget named seed", not bad, bad)
r = MAP["PCG_COPSDFOps"]().run(si, "sdf", "", "to_fill", 0.0, 0.5, 0.0,
                               0.01, "uv", "m")
r = tuple(r["result"]) if isinstance(r, dict) else r
check("  SDF Ops to_xxx goes through SDF to Mono", "m" in r[0])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
