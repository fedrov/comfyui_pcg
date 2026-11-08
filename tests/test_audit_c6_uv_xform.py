"""
pcg100 audit pack c6_uv_xform: a batch of COP UV / coordinate / transform nodes completed per the SideFX docs.

  UV Map / UV Map by ID   PCG_COPUVMap gains UV Space (Texture / Image / Pixel), U/V Border /
                          Shift / Cycles, a uvscale output, by-ID Mode (UV Map / Center / Minimum /
                          Maximum / Size), Auto Scale, Zero Negative IDs, connected islands
  UV to Polar / Polar to UV   new node PCG_COPPolarCoords (pure coordinate conversion, Angle Units)
  Space Transform         new node PCG_COPSpaceTransform
  Sphere Sample           new node PCG_COPSphereSample
  Transform 3D            new node PCG_COPTransform3D
  Align / Align Pixels    new nodes PCG_COPAlignWindow / PCG_COPAlignPixels
  Bend                    new node PCG_COPBend
  Position Map            new node PCG_COPPositionMap

References are all hand-computable coordinates / angles / lengths. "Bit-identical to before the change at defaults" uses digests of the same calls from before the change,
hard-coded in GOLDEN (arrays rounded to 5 decimals then hashed); `--digests` prints the current digests. No dependency on git.
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
from comfyui_pcg.panel_specs import SPECS               # noqa: E402
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
    """INPUT_TYPES defaults (combos use {"default": …}, otherwise the first item)."""
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
    r = M[n]().run(**a)
    return r[0]


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


def id_img():
    """Two id pieces (1, 2) + one negative id piece (−3) + a piece with the same value as 1 but not connected, the rest 0."""
    ids = np.zeros((12, 16))
    ids[1:4, 2:8] = 1          # 6×3
    ids[6:11, 9:12] = 2        # 3×5
    ids[8:10, 1:3] = -3        # 2×2
    ids[9:11, 13:15] = 1       # not connected to the 1 above, 2×2
    return img_with(16, 12, id=ids)


# ═══════════════════════════════════════════════════ Regression: same as before the change at defaults
GOLDEN = {
    "uvmap/0": "e8ec5d1df8974204",
    "uvmap/1": "41dd1d4da3eac73c",
    "uvmap/2": "d4dda788c45fcf04",
    "uvmap/3": "ce1fc6d6fe6b4978",
}


def current_digests():
    R = {}
    n = "PCG_COPUVMap"
    base = {"mode": "identity", "id_layer": "id", "fit": "fit", "scale": "1 1",
            "offset": "0 0", "rotate": 0.0, "out_layer": "uv",
            "resolution_x": 24, "resolution_y": 16}
    for i, e in enumerate([{}, {"scale": "2 0.5", "offset": "0.1 -0.2", "rotate": 30.0},
                           {"mode": "by_id", "fit": "fit"},
                           {"mode": "by_id", "fit": "stretch"}]):
        kw = dict(base)
        kw.update(e)
        a = defaults(n)
        a.update(kw)
        if kw["mode"] == "by_id":
            a["cop"] = id_img()
        R[f"uvmap/{i}"] = dig(M[n]().run(**a)[0])
    return R


if "--digests" in sys.argv:
    for k, v in current_digests().items():
        print(f'    "{k}": "{v}",')
    sys.exit(0)

sec("Regression: same as before the change at defaults (hard-coded digests)")
now = current_digests()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})


# ═══════════════════════════════════════════════════ UV Map / UV Map by ID
UVM = "PCG_COPUVMap"
W_, H_ = 24, 16


def uvm(**kw):
    a = dict(resolution_x=W_, resolution_y=H_)
    a.update(kw)
    return run(UVM, **a)


J_, I_ = np.meshgrid(np.arange(W_) + 0.5, np.arange(H_) + 0.5)

sec("UV Map:UV Space")
t = L(uvm(), "uv")
check("Texture: pixel centers ((j+.5)/W, (i+.5)/H)",
      near(t[..., 0], J_ / W_, 1e-6) and near(t[..., 1], I_ / H_, 1e-6))
im_ = L(uvm(uv_space="image"), "uv")
check("Image: −1…1 spans the long side (24), short side ±16/24; bottom-left pixel (−23/24, −15/24)",
      near(im_[0, 0], [-23 / 24, -15 / 24], 1e-6)
      and near(im_[-1, -1], [23 / 24, 15 / 24], 1e-6))
px_ = L(uvm(uv_space="pixel"), "uv")
check("Pixel: first bottom-left pixel center (0.5, 0.5), top-right (23.5, 15.5)",
      near(px_[0, 0], [0.5, 0.5], 1e-6) and near(px_[-1, -1], [23.5, 15.5], 1e-6))
check("negative control: the three spaces all give different results",
      not near(t, im_) and not near(t, px_) and not near(im_, px_))
iw = L(uvm(uv_space="image", resolution_x=16, resolution_y=24), "uv")
check("Image portrait: long side is y, v spans ±23/24, u only reaches ±15/24",
      near(iw[-1, -1], [15 / 24, 23 / 24], 1e-6))

sec("UV Map:Shift / Cycles / Border")
u0 = J_ / W_
c3 = L(uvm(u_cycles=3.0, u_border="wrap"), "uv")[..., 0]
check("Texture + Wrap + U Cycles 3:u = frac(3u)", near(c3, np.mod(3 * u0, 1.0), 1e-6))
c3e = L(uvm(u_cycles=3.0), "uv")[..., 0]
check("negative control: Extend doesn't fold, u = 3u", near(c3e, 3 * u0, 1e-5))
cs = L(uvm(u_shift=0.5, u_border="clamp"), "uv")[..., 0]
check("Clamp + Shift 0.5:u = min(u + 0.5, 1)", near(cs, np.minimum(u0 + 0.5, 1.0), 1e-6))
mi = L(uvm(u_cycles=2.0, u_border="mirror"), "uv")[..., 0]
check("Mirror + Cycles 2: t = 2u, folded to 2 − t where t > 1",
      near(mi, np.where(2 * u0 <= 1, 2 * u0, 2 - 2 * u0), 1e-6))
sc = L(uvm(u_shift=0.25, u_cycles=2.0), "uv")[..., 0]
check("Shift before Cycles: (u + 0.25) × 2", near(sc, (u0 + 0.25) * 2, 1e-5))
v0 = (I_ - 8) * 2 / 24
iv = L(uvm(uv_space="image", v_cycles=2.0, v_border="wrap"), "uv")[..., 1]
check("Image + Wrap + V Cycles 2: folds back periodically within the canonical range −1…1",
      near(iv, np.mod(2 * v0 + 1, 2.0) - 1, 1e-6))
check("V settings don't affect U", near(L(uvm(uv_space="image", v_cycles=2.0, v_border="wrap"),
                                  "uv")[..., 0], im_[..., 0], 1e-7))
pc = L(uvm(uv_space="pixel", u_shift=100.0, u_border="clamp"), "uv")[..., 0]
check("Pixel + Clamp: canonical range is [0, W], clamped to 24", near(pc, 24.0))

sec("UV Map:uvscale")
s1 = L(uvm(uvscale_layer="uvscale"), "uvscale")
check("identity mapping uvscale = 1", near(s1, 1.0, 1e-6))
check("no uvscale layer by default", "uvscale" not in uvm().names)
check("Cycles 3 → uvscale = 3", near(L(uvm(uvscale_layer="s", u_cycles=3.0), "s"), 3.0, 1e-6))
check("Scale 2 0.5, rotate 30° → largest singular value 2",
      near(L(uvm(uvscale_layer="s", scale="2 0.5", rotate=30.0), "s"), 2.0, 1e-5))
# non-square image + image space + rotation: cross-check with a numerical Jacobian (interior pixels, extend)
r_ = uvm(uv_space="image", rotate=30.0, uvscale_layer="s", u_cycles=1.5)
uvr, sr = L(r_, "uv"), L(r_, "s")[..., 0]
Ja = np.array([[uvr[5, 6, 0] - uvr[5, 5, 0], uvr[6, 5, 0] - uvr[5, 5, 0]],
               [uvr[5, 6, 1] - uvr[5, 5, 1], uvr[6, 5, 1] - uvr[5, 5, 1]]])
Ji = np.diag([2 / 24, 2 / 24])                       # per-pixel derivative of the identity mapping in image space
check("Image + rotation + Cycles: uvscale = largest singular value of (actual Jacobian × identity Jacobian⁻¹)",
      near(sr[0, 0], np.linalg.svd(Ja @ np.linalg.inv(Ji), compute_uv=False)[0], 1e-4),
      (sr[0, 0], np.linalg.svd(Ja @ np.linalg.inv(Ji), compute_uv=False)[0]))

sec("UV Map by ID")
ii = id_img()


def byid(**kw):
    a = dict(mode="by_id", cop=ii, uvscale_layer="s")
    a.update(kw)
    return run(UVM, **a)


st = byid(fit="stretch")
u_, s_ = L(st, "uv"), L(st, "s")[..., 0]
# island 2: columns 9..11, rows 6..10 (3 × 5)
check("Stretch: island 2 bottom-left pixel uv = (0.5/3, 0.5/5)", near(u_[6, 9], [0.5 / 3, 0.5 / 5], 1e-6))
check("Stretch uvscale = max(16/3, 12/5)", near(s_[6, 9], 16 / 3, 1e-5))
check("background uv = 0, uvscale = 0", near(u_[0, 0], [0, 0]) and s_[0, 0] == 0)
check("Zero Negative IDs on (default): the −3 piece is treated as background", near(u_[8, 1], [0, 0]))
nz = L(byid(fit="stretch", zero_negative_ids=False), "uv")
check("Zero Negative IDs off: −3 is its own island, bottom-left pixel (0.25, 0.25)", near(nz[8, 1], [0.25, 0.25], 1e-6))
# the two id-1 pieces aren't connected: combined bounding box columns 2..14, rows 1..10 (13 × 10)
check("no connectivity split (default): the two 1 pieces share one bounding box", near(u_[1, 2], [0.5 / 13, 0.5 / 10], 1e-6))
cn = L(byid(fit="stretch", connected=True), "uv")
check("Split Disconnected: each has its own bounding box (bottom-left pixel of the 6×3 one = (0.5/6, 0.5/3))",
      near(cn[1, 2], [0.5 / 6, 0.5 / 3], 1e-6) and near(cn[9, 13], [0.25, 0.25], 1e-6))
fi = byid()
check("Fit (old default): island 2 uvscale = 16/5", near(L(fi, "s")[6, 9, 0], 16 / 5, 1e-5))
ib = byid(uv_space="image")
check("Image: island 2 fitted into [−1,1]² proportionally, bottom-left pixel ((9.5−10.5)·2/5, (6.5−8.5)·2/5)",
      near(L(ib, "uv")[6, 9], [-0.4, -0.8], 1e-6))
check("Image: uvscale = long side / island long side = 16/5", near(L(ib, "s")[6, 9, 0], 3.2, 1e-5))
check("Fit is not read in Image", near(L(ib, "uv"), L(byid(uv_space="image", fit="stretch"), "uv")))
na = byid(auto_scale=False)
check("Auto Scale off (Texture): origin at the island's bottom-left, whole-image texture units",
      near(L(na, "uv")[6, 9], [0.5 / 16, 0.5 / 12], 1e-6) and near(L(na, "s")[6, 9, 0], 1.0))
nai = byid(auto_scale=False, uv_space="image")
check("Auto Scale off (Image): origin at the island center, whole-image image units",
      near(L(nai, "uv")[6, 9], [-2 / 16, -4 / 16], 1e-6))
cy = L(byid(fit="stretch", u_cycles=2.0, u_border="wrap"), "uv")
check("by ID + Cycles 2 + Wrap: island 2 rightmost column u = frac(2 × 2.5/3)",
      near(cy[6, 11, 0], np.mod(2 * 2.5 / 3, 1.0), 1e-6))
exp = {"center": (10.5 / 16, 8.5 / 12), "minimum": (9 / 16, 6 / 12),
       "maximum": (12 / 16, 11 / 12), "size": (3 / 16, 5 / 12)}
for k, val in exp.items():
    r = byid(id_mode=k)
    check(f"Mode {k} (Texture): every pixel of island 2 is the bounding box {k}",
          near(L(r, "uv")[6:11, 9:12].reshape(-1, 2) - np.asarray(val), 0, 1e-6))
check("Mode center(Image):((10.5−8)·2/16, (8.5−6)·2/16)",
      near(L(byid(id_mode="center", uv_space="image"), "uv")[7, 10], [5 / 16, 5 / 16], 1e-6))
check("Mode size(Image):(3·2/16, 5·2/16)",
      near(L(byid(id_mode="size", uv_space="image"), "uv")[7, 10], [6 / 16, 10 / 16], 1e-6))
check("statistic modes don't apply Shift",
      near(L(byid(id_mode="center", u_shift=0.3), "uv"), L(byid(id_mode="center"), "uv")))
check("statistic modes have uvscale = 1", near(L(byid(id_mode="size"), "s")[6:11, 9:12], 1.0))
check("Stretch + V Cycles 3: uvscale = max(16/3, 3·12/5) = 7.2 (v axis dominates)",
      near(L(byid(fit="stretch", v_cycles=3.0), "s")[6, 9, 0], 7.2, 1e-5))
check("Stretch + U Cycles −2: uvscale takes the absolute value = 2·16/3",
      near(L(byid(fit="stretch", u_cycles=-2.0), "s")[6, 9, 0], 32 / 3, 1e-5))
dg_ = np.zeros((4, 4))
dg_[0, 0] = dg_[1, 1] = 5          # touching only diagonally
dgr = L(run(UVM, mode="by_id", cop=img_with(4, 4, id=dg_), connected=True, fit="stretch"), "uv")
check("Split Disconnected uses 4-connectivity: two only-diagonally-adjacent pixels are each their own island (each uv = 0.5, 0.5)",
      near(dgr[0, 0], [0.5, 0.5]) and near(dgr[1, 1], [0.5, 0.5]))
try:
    byid(uv_space="pixel")
    check("by ID + Pixel raises", False)
except ValueError:
    check("by ID + Pixel raises", True)

sec("UV Map: node / panel")
it = M[UVM].INPUT_TYPES()["required"]
check("new widgets appended at the end, old order unchanged",
      list(it)[:9] == ["mode", "id_layer", "fit", "scale", "offset", "rotate", "out_layer",
                       "resolution_x", "resolution_y"])
check("Border menu is Houdini's four items, default extend", it["u_border"][0] == ["clamp", "mirror", "wrap", "extend"]
      and it["u_border"][1]["default"] == "extend")
check("panel check_layout is empty", PANEL.check_layout(UVM, M[UVM].INPUT_TYPES()) == [])


sec("UV Map: uvscale vs numerical Jacobian (non-square image, non-uniform scale, each space)")


def num_scale(sp, **kw):
    r_ = uvm(uv_space=sp, uvscale_layer="s", **kw)
    uvr = L(r_, "uv")
    Ja = np.array([[uvr[5, 6, 0] - uvr[5, 5, 0], uvr[6, 5, 0] - uvr[5, 5, 0]],
                   [uvr[5, 6, 1] - uvr[5, 5, 1], uvr[6, 5, 1] - uvr[5, 5, 1]]])
    k = {"texture": (1 / 24, 1 / 16), "image": (2 / 24, 2 / 24), "pixel": (1.0, 1.0)}[sp]
    want = np.linalg.svd(Ja @ np.linalg.inv(np.diag(k)), compute_uv=False)[0]
    return L(r_, "s")[0, 0, 0], want


for sp in ("texture", "image", "pixel"):
    got, want = num_scale(sp, scale="2 0.5", rotate=30.0, v_cycles=1.3)
    check(f"{sp}: Scale 2 0.5 + rotate 30° + V Cycles 1.3", abs(got - want) < 1e-3, (got, want))
ic = L(uvm(uv_space="image", u_shift=-0.5, u_border="clamp"), "uv")[..., 0]
check("Image + Clamp: u lower bound −1", near(ic, np.clip(im_[..., 0] - 0.5, -1, 1), 1e-6)
      and ic.min() == -1.0)

# ═══════════════════════════════════════════════════ UV to Polar / Polar to UV
PC = "PCG_COPPolarCoords"
pts = np.array([[1, 0], [0, 1], [-1, 0], [0, -1], [3, 4], [1, -1e-17]], np.float64)
pim = img_with(6, 1, uv=pts[None])

sec("UV to Polar")
r = run(PC, cop=pim)
ang, ln = L(r, "angle")[0, :, 0], L(r, "length")[0, :, 0]
check("Circles (default): +x 0, +y 0.25, −x 0.5, −y 0.75 (counterclockwise)",
      near(ang[:4], [0, 0.25, 0.5, 0.75], 1e-7))
check("Length = |uv|", near(ln[:5], [1, 1, 1, 1, 5], 1e-6))
check("angle falls in [0, 1): a point just below +x does not output 1.0", 0 <= ang[5] < 1, ang[5])
check("angle / length are both single-channel", L(r, "angle").shape[2] == 1 and L(r, "length").shape[2] == 1)
dg = L(run(PC, cop=pim, angle_units="degrees"), "angle")[0, :, 0]
rd = L(run(PC, cop=pim, angle_units="radians"), "angle")[0, :, 0]
check("Degrees:90 / 180 / 270", near(dg[1:4], [90, 180, 270], 1e-4))
check("Radians:π/2", near(rd[1], math.pi / 2, 1e-6))
check("(3,4):atan2(4,3)", near(dg[4], math.degrees(math.atan2(4, 3)), 1e-4))
o = L(run(PC, cop=img_with(1, 1, uv=[[[0.5, 1.5]]]), origin="0.5 0.5"), "angle")[0, 0, 0]
check("Origin 0.5 0.5: angle of (0.5, 1.5) is 0.25", near(o, 0.25, 1e-7))

sec("Polar to UV")
pol = img_with(3, 1, angle=[[0.25, 0.5, 0.125]], length=[[2.0, 1.0, math.sqrt(2)]])
r = L(run(PC, cop=pol, direction="polar_to_uv"), "uv")[0]
check("Circles: 0.25 turn, length 2 → (0, 2); 0.5 turn → (−1, 0); 1/8 turn √2 → (1, 1)",
      near(r, [[0, 2], [-1, 0], [1, 1]], 1e-6))
rc = L(run(PC, cop=pol, direction="polar_to_uv", angle_layer="", angle=0.0), "uv")[0]
check("empty Angle layer name → uses the Angle constant (0): all on +x", near(rc[:, 1], 0, 1e-7)
      and near(rc[:, 0], [2, 1, math.sqrt(2)], 1e-6))
rl = L(run(PC, cop=pol, direction="polar_to_uv", length_layer="", length=3.0), "uv")[0]
check("empty Length layer name → uses the Length constant", near(np.hypot(rl[:, 0], rl[:, 1]), 3.0, 1e-6))
check("with a layer given, the constant isn't read", near(r, L(run(PC, cop=pol, direction="polar_to_uv", angle=0.3,
                                        length=9.0), "uv")[0]))
dd = img_with(1, 1, angle=[[90.0]], length=[[1.0]])
check("Degrees:90° → (0, 1)", near(L(run(PC, cop=dd, direction="polar_to_uv",
                                         angle_units="degrees"), "uv")[0, 0], [0, 1], 1e-6))
check("negative control: the same 90 interpreted as Circles gives a different result",
      not near(L(run(PC, cop=dd, direction="polar_to_uv"), "uv")[0, 0], [0, 1], 1e-3))
rng = np.random.default_rng(1)
ruv = rng.uniform(-3, 3, (5, 7, 2))
rt = run(PC, cop=img_with(7, 5, uv=ruv), origin="0.2 -0.1", angle_units="radians")
back = L(run(PC, cop=rt, direction="polar_to_uv", uv_layer="uv2", origin="0.2 -0.1",
             angle_units="radians"), "uv2")
check("round trip: UV → Polar → UV returns the original", near(back, L(rt, "uv"), 1e-5))
check("panel check_layout is empty", PANEL.check_layout(PC, M[PC].INPUT_TYPES()) == [])

# ═══════════════════════════════════════════════════ Space Transform
STN = "PCG_COPSpaceTransform"
sec("Space Transform")
sv = img_with(3, 1, uv=[[[0, 0], [1, 1], [0.5, 0.5]]])
base24 = CopImage(24, 16)


def stx(src, dst, val, **kw):
    im = img_with(1, 1, P=[[val]])
    a = dict(cop=im, layer="P", src_space=src, dst_space=dst)
    a.setdefault("src_ref", base24)
    a.setdefault("dst_ref", base24)
    a.update(kw)
    return L(run(STN, **a), kw.get("out_layer") or "P")[0, 0]


check("texture → image(24×16):(0,0) → (−1, −2/3)", near(stx("texture", "image", [0, 0]),
                                                      [-1, -2 / 3], 1e-6))
check("texture → image:(1,1) → (1, 2/3)", near(stx("texture", "image", [1, 1]), [1, 2 / 3], 1e-6))
check("texture → pixel:(0.5,0.5) → (12, 8)", near(stx("texture", "pixel", [0.5, 0.5]), [12, 8], 1e-5))
check("pixel → texture,src_ref 48×32:(12, 8) → (0.25, 0.25)",
      near(stx("pixel", "texture", [12, 8], src_ref=CopImage(48, 32)), [0.25, 0.25], 1e-6))
check("texture → pixel,dst_ref 48×32:(0.5,0.5) → (24, 16)",
      near(stx("texture", "pixel", [0.5, 0.5], dst_ref=CopImage(48, 32)), [24, 16], 1e-5))
check("image → pixel (portrait 16×24): (0,0) → image center (8, 12)",
      near(stx("image", "pixel", [0, 0], src_ref=CopImage(16, 24), dst_ref=CopImage(16, 24)),
           [8, 12], 1e-5))
check("Position: texture → image (1, 0) → (1, −2/3)",
      near(stx("texture", "image", [1, 0]), [1, -2 / 3], 1e-6))
check("Vector: texture → image (1, 0) → (2, 0) (linear part only)",
      near(stx("texture", "image", [1, 0], vector_type="vector"), [2, 0], 1e-6))
check("Vector: image → pixel (1, 1) → (12, 12)",
      near(stx("image", "pixel", [1, 1], vector_type="vector"), [12, 12], 1e-5))
check("Buffer = Pixel, World = Image",
      near(stx("texture", "buffer", [0.3, 0.7]), stx("texture", "pixel", [0.3, 0.7]))
      and near(stx("texture", "world", [0.3, 0.7]), stx("texture", "image", [0.3, 0.7])))
check("3rd channel kept as is", near(stx("texture", "image", [0.5, 0.5, 7.0]), [0, 0, 7], 1e-6))
r3 = rng.uniform(-2, 2, 2)
rr = r3
for a_, b_ in (("texture", "image"), ("image", "pixel"), ("pixel", "world"), ("world", "texture")):
    rr = stx(a_, b_, rr)
check("full circle back (texture → image → pixel → world → texture)", near(rr, r3, 1e-4))
ow = run(STN, cop=sv, layer="uv", src_space="texture", dst_space="pixel", out_layer="px")
check("with an Output Layer name given, writes separately and leaves the original layer untouched",
      near(L(ow, "uv"), L(sv, "uv")) and near(L(ow, "px")[0, 1], [3, 1], 1e-6))
check("without ref, uses coord's own resolution (3×1)",
      near(L(run(STN, cop=sv, layer="uv", src_space="texture", dst_space="pixel"), "uv")[0, 2],
           [1.5, 0.5], 1e-6))
check("panel check_layout is empty", PANEL.check_layout(STN, M[STN].INPUT_TYPES()) == [])

# ═══════════════════════════════════════════════════ Position Map
PM = "PCG_COPPositionMap"
sec("Position Map")


def pmap(**kw):
    a = dict(resolution_x=24, resolution_y=16)
    a.update(kw)
    return L(run(PM, **a), "pos")


p0 = pmap()
check("Position: 3 channels, bottom-left (−23/24, −15/24, 0), top-right (23/24, 15/24, 0)",
      p0.shape == (16, 24, 3) and near(p0[0, 0], [-23 / 24, -15 / 24, 0], 1e-6)
      and near(p0[-1, -1], [23 / 24, 15 / 24, 0], 1e-6))
check("View Direction: every pixel (0, 0, −1)", near(pmap(source_position="view_direction"),
                                                np.broadcast_to([0, 0, -1], (16, 24, 3))))
xw = pmap(x_cycles=3.0, x_border="wrap")[..., 0]
check("X Wrap + Cycles 3: folded back into [−1, 1]", near(xw, np.mod(3 * p0[..., 0] + 1, 2) - 1, 1e-6))
check("negative control: Extend doesn't fold", near(pmap(x_cycles=3.0)[..., 0], 3 * p0[..., 0], 1e-5))
check("Z Shift 0.5:z = 0.5;Shift 2 + Clamp:z = 1",
      near(pmap(z_shift=0.5)[..., 2], 0.5) and near(pmap(z_shift=2.0, z_border="clamp")[..., 2], 1.0))
ym = pmap(y_shift=1.5, y_border="mirror")[..., 1]
yy = p0[..., 1] + 1.5
check("Y Mirror: the part beyond 1 folds back to 2 − y", near(ym, np.where(yy > 1, 2 - yy, yy), 1e-6))
check("Z Mirror (view_direction, Shift −0.5): −1.5 folds to −0.5",
      near(pmap(source_position="view_direction", z_shift=-0.5, z_border="mirror")[..., 2], -0.5))
check("Y Cycles 2 acts only on y", near(pmap(y_cycles=2.0, x_cycles=3.0)[..., 1], 2 * p0[..., 1], 1e-5))
check("size_ref sets the resolution", L(run(PM, size_ref=img_with(10, 6, C=np.zeros((6, 10)))), "pos").shape == (6, 10, 3))
check("panel check_layout is empty", PANEL.check_layout(PM, M[PM].INPUT_TYPES()) == [])


# ═══════════════════════════════════════════════════ Sampling with Filter (warp3d.fsample)
from comfyui_pcg.geo.cop import warp3d as WP            # noqa: E402

sec("Filter / Border(fsample)")
row = np.array([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0])[None, :, None]


def fs(x, filt="bilinear", b="clamp"):
    return float(WP.fsample(row, np.array([x]), np.array([0.0]), filt, b, "clamp")[0, 0])


check("Point:1.4 → a[1],1.6 → a[2]", fs(1.4, "point") == 1.0 and fs(1.6, "point") == 4.0)
check("Box (unit footprint) = Point", fs(1.4, "box") == 1.0 and fs(1.6, "box") == 4.0)
check("Bilinear 1.25 = 0.75·a1 + 0.25·a2", near(fs(1.25), 0.75 * 1 + 0.25 * 4))
check("Bartlett (unit footprint) = Bilinear", near(fs(1.25, "bartlett"), fs(1.25)))
check("Catmull-Rom interpolates at integer points (= a[3])", near(fs(3.0, "catmull_rom"), 1.0))
check("Catmull-Rom half cell: (−a2 + 9a3 + 9a4 − a5)/16",
      near(fs(3.5, "catmull_rom"), (-4 + 9 * 1 + 9 * 5 - 9) / 16))
check("B-spline integer point: (a2 + 4a3 + a4)/6", near(fs(3.0, "bspline"), (4 + 4 * 1 + 5) / 6))
check("B-spline half cell: 23/48·(a3 + a4) + 1/48·(a2 + a5)",
      near(fs(3.5, "bspline"), 23 / 48 * (1 + 5) + 1 / 48 * (4 + 9)))
check("Mitchell integer point: (a2 + 16a3 + a4)/18", near(fs(3.0, "mitchell"), (4 + 16 * 1 + 5) / 18))
check("Constant: x = −1 is 0; Clamp: a[0]; Wrap: a[7]; Mirror: a[0]; Mirror x = −2: a[1]",
      fs(-1, "point", "constant") == 0 and fs(-1, "point", "clamp") == 3
      and fs(-1, "point", "wrap") == 6 and fs(-1, "point", "mirror") == 3
      and fs(-2, "point", "mirror") == 1)
check("Mirror on the right: x = 8 → a[7], x = 9 → a[6]",
      fs(8, "point", "mirror") == 6 and fs(9, "point", "mirror") == 2)
check("Constant + Bilinear at −0.5: half weight = 0.5·a0", near(fs(-0.5, "bilinear", "constant"), 1.5))

# ═══════════════════════════════════════════════════ Sphere Sample
SS = "PCG_COPSphereSample"
sec("Sphere Sample")
sw_, sh_ = 64, 32
U_, V_ = np.meshgrid((np.arange(sw_) + 0.5) / sw_, (np.arange(sh_) + 0.5) / sh_)
llsrc = img_with(sw_, sh_, C=np.stack([U_, V_], -1))


def ss(**kw):
    a = dict(source=llsrc, resolution_x=33, resolution_y=33, filter="bilinear")
    a.update(kw)
    return run(SS, **a)


def ll(d):
    d = np.asarray(d, float) / np.linalg.norm(d)
    return 0.5 + math.atan2(-d[2], d[0]) / (2 * math.pi), 0.5 + math.asin(d[1]) / math.pi


X33, Y33 = WP.image_coords(33, 33)
o_ = ss(projection="orthographic")
ms = L(o_, "mask")[..., 0]
check("orthographic unit sphere: mask = pixel center falls inside the unit circle", np.array_equal(ms > 0.5, X33 ** 2 + Y33 ** 2 <= 1))
x_, y_ = X33[16, 20], Y33[16, 20]
want = ll([x_, y_, math.sqrt(1 - x_ * x_ - y_ * y_)])
check("orthographic: the hit point's direction looks up the latlong map (pixel (16, 20))", near(L(o_, "transform")[16, 20], want, 2e-3),
      (L(o_, "transform")[16, 20], want))
check("front center u = 0.25, v = 0.5 (the plugin's latlong convention)",
      near(L(o_, "transform")[16, 16], [0.25, 0.5], 1e-3))
check("missed pixels = 0", near(L(o_, "transform")[0, 0], 0))
r45 = ss(projection="orthographic", rotate="0 45 0")
check("Rotate Y 45°: center pixel u goes from 0.25 to 0.125", near(L(r45, "transform")[16, 16, 0], 0.125, 1e-3))
us_ = L(ss(projection="orthographic", uniform_scale=0.5), "mask")[..., 0]
check("Uniform Scale 0.5: disc radius 0.5", np.array_equal(us_ > 0.5, X33 ** 2 + Y33 ** 2 <= 0.25))
check("Scale 0.5 0.5 0.5 = Uniform Scale 0.5",
      np.array_equal(us_, L(ss(projection="orthographic", scale="0.5 0.5 0.5"), "mask")[..., 0]))
tr_ = L(ss(projection="orthographic", uniform_scale=0.5, translate="0.5 0 0"), "mask")[..., 0]
check("Translate 0.5: circle center moves to x = 0.5", np.array_equal(tr_ > 0.5, (X33 - 0.5) ** 2 + Y33 ** 2 <= 0.25))
o1 = L(ss(projection="orthographic", uniform_scale=0.5, translate="0.5 0 0", rotate="0 0 90"), "mask")
o2 = L(ss(projection="orthographic", uniform_scale=0.5, translate="0.5 0 0", rotate="0 0 90",
          xform_order="trs"), "mask")
check("Transform Order: srt and trs (trs translates first, then rotates 90°, then scales 0.5, center at (0, 0.25)) differ",
      not near(o1, o2) and np.array_equal(o2[..., 0] > 0.5, X33 ** 2 + (Y33 - 0.25) ** 2 <= 0.25))
r1 = L(ss(projection="orthographic", rotate="30 40 0"), "transform")
r2 = L(ss(projection="orthographic", rotate="30 40 0", rotate_order="zyx"), "transform")
check("different Rotate Order, different result", not near(r1, r2, 1e-3))
pm_ = L(ss(), "mask")[..., 0]
check("perspective (camera distance 2): silhouette r² < 4/3", np.array_equal(pm_ > 0.5, (X33 ** 2 + Y33 ** 2) * 3 < 4))
check("negative control: perspective and orthographic masks differ", not np.array_equal(pm_, ms))
pc_ = L(ss(camera_distance=5.0), "mask")[..., 0]
check("Camera Distance 5: silhouette r² < 25/24", np.array_equal(pc_ > 0.5, (X33 ** 2 + Y33 ** 2) * 24 < 25))
ce = ss(celestial=True)
d_ = np.array([X33[16, 20], Y33[16, 20], -2.0])
check("sphere behind the perspective camera (Translate z 5): no hits, mask all 0",
      near(L(ss(translate="0 0 5"), "mask"), 0))
check("celestial sphere: mask all 1", near(L(ce, "mask"), 1.0))
check("celestial sphere (perspective): ray direction looks up the table", near(L(ce, "transform")[16, 20], ll(d_), 2e-3))
check("celestial sphere unaffected by Translate / Scale",
      near(L(ce, "transform"), L(ss(celestial=True, translate="3 1 0", uniform_scale=0.2), "transform")))
check("celestial sphere affected by Rotate", not near(L(ce, "transform"), L(ss(celestial=True, rotate="0 45 0"),
                                                         "transform"), 1e-3))
check("celestial sphere + orthographic: the whole image has one value",
      np.ptp(L(ss(celestial=True, projection="orthographic"), "transform")[..., 0]) < 1e-9)
noise = img_with(16, 8, C=np.random.default_rng(3).random((8, 16)))
check("Filter: point and bilinear give different results",
      not near(L(ss(source=noise), "transform"), L(ss(source=noise, filter="point"), "transform")))
check("size_ref sets the resolution", L(ss(size_ref=img_with(10, 6, C=np.zeros((6, 10)))), "mask").shape[:2]
      == (6, 10))
try:
    run(SS, source=None)
    check("no source connected raises", False)
except ValueError:
    check("no source connected raises", True)
check("panel check_layout is empty", PANEL.check_layout(SS, M[SS].INPUT_TYPES()) == [])

# ═══════════════════════════════════════════════════ Transform 3D
T3 = "PCG_COPTransform3D"
sec("Transform 3D(Rasterize)")
src16 = np.random.default_rng(5).random((16, 16))
im16 = img_with(16, 16, C=src16)


def t3(**kw):
    a = dict(cop=im16)
    a.update(kw)
    return L(run(T3, **a), "C")[..., 0]


check("identity (Box default): bit-identical", np.array_equal(t3(), np.asarray(im16.need("C"))[..., 0]))
sh2 = t3(translate="0.25 0 0")          # 1 pixel = 2/16 = 0.125
check("Translate 0.25 = shift right 2 pixels, left two columns 0 (Auto = Clip)",
      near(sh2[:, 2:], src16[:, :-2], 1e-6) and near(sh2[:, :2], 0))
check("Wrap:np.roll", near(t3(translate="0.25 0 0", border="wrap"), np.roll(src16, 2, 1), 1e-6))
check("Clamp: left two columns = column 0", near(t3(translate="0.25 0 0", border="clamp")[:, :2],
                                   src16[:, :1].repeat(2, 1), 1e-6))
mi_ = t3(translate="0.25 0 0", border="mirror")
check("Mirror: column 0 = source column 1, column 1 = source column 0",
      near(mi_[:, 0], src16[:, 1], 1e-6) and near(mi_[:, 1], src16[:, 0], 1e-6))
hc = t3(translate="0.0625 0 0", filter="bilinear", border="constant")
hk = t3(translate="0.0625 0 0", filter="bilinear", border="clip")
check("Constant vs Clip (half pixel): Constant edge column fades by half, Clip doesn't bleed black",
      near(hc[:, 0], 0.5 * src16[:, 0], 1e-6) and near(hk[:, 0], src16[:, 0], 1e-6))
check("Auto = Clip", near(t3(translate="0.0625 0 0", filter="bilinear"), hk))
check("Invert: translation reversed", near(t3(translate="0.25 0 0", invert=True, border="wrap"),
                            np.roll(src16, -2, 1), 1e-6))
r90 = t3(rotate="0 0 90")
ii_, jj_ = np.meshgrid(np.arange(16), np.arange(16), indexing="ij")
check("Rotate Z 90°:out[i, j] = src[15 − j, i]", near(r90, src16[15 - jj_, ii_], 1e-6))
pv = t3(rotate="0 0 90", pivot="0.5 0.5 0")
check("Pivot changes the rotation center (differs from rotating about the origin)", not near(pv, r90, 1e-3))
# rotate 90° about (0.5, 0.5): src = R⁻¹(q − p) + p
X16, Y16 = WP.image_coords(16, 16)
sx_, sy_ = (Y16 - 0.5) + 0.5, -(X16 - 0.5) + 0.5
pxs, pys = WP.image_to_pixel(sx_, sy_, 16, 16)
inb = (pxs > -0.5) & (pxs < 15.5) & (pys > -0.5) & (pys < 15.5)
ref_ = np.where(inb, src16[np.clip(np.rint(pys).astype(int), 0, 15),
                           np.clip(np.rint(pxs).astype(int), 0, 15)], 0)
check("Pivot (0.5, 0.5): per pixel matches R⁻¹(q − p) + p", near(pv, ref_, 1e-6))
gx = np.tile(np.arange(16, dtype=float), (16, 1))
gimg = img_with(16, 16, C=gx)
s2_ = L(run(T3, cop=gimg, scale="2 1 1", filter="bilinear"), "C")[..., 0]
want_x, _ = WP.image_to_pixel(X16 / 2, Y16, 16, 16)
check("Scale X 2: samples the source at x/2 (gradient image)", near(s2_, want_x, 1e-5))
check("Uniform Scale 2 = Scale 2 2 2", near(t3(uniform_scale=2.0), t3(scale="2 2 2")))
sr_ = L(run(T3, cop=gimg, shear="0.5 0 0", filter="bilinear", border="clamp"), "C")[..., 0]
wx_, _ = WP.image_to_pixel(X16 - 0.5 * Y16, Y16, 16, 16)
check("Shear XY 0.5: x' = x + 0.5·y (per pixel on a gradient image)", near(sr_, np.clip(wx_, 0, 15), 1e-5))
check("Transform Order: srt vs trs differ",
      not near(t3(translate="0.25 0 0", scale="0.5 0.5 1"),
               t3(translate="0.25 0 0", scale="0.5 0.5 1", xform_order="trs")))
check("Rotate Order: xyz vs zyx differ",
      not near(t3(rotate="30 20 10"), t3(rotate="30 20 10", rotate_order="zyx")))
check("Rotate Y 90° (edge-on to the orthographic camera): all 0", near(t3(rotate="0 90 0"), 0))
check("perspective: plane behind the camera (Translate z 3) → all 0", near(t3(translate="0 0 3", perspective=True), 0))
check("edge-on to the camera + Clamp / Wrap: missed pixels are still 0 (borders don't apply)",
      near(t3(rotate="0 90 0", border="clamp"), 0) and near(t3(rotate="0 90 0", border="wrap"), 0))
check("perspective + identity: same as the original", near(t3(perspective=True, filter="bilinear"), src16, 1e-5))
pz = L(run(T3, cop=gimg, translate="0 0 -2", perspective=True, filter="bilinear",
           border="clamp"), "C")[..., 0]
wz_, _ = WP.image_to_pixel(X16 * 2, Y16, 16, 16)
check("perspective + pushed back 2 (distance 4): image shrinks by half, samples the source at 2x", near(pz, np.clip(wz_, 0, 15), 1e-5))
check("negative control: pushing back in orthographic changes nothing", near(t3(translate="0 0 -2"), src16, 1e-6))
check("Filter: catmull_rom and bilinear differ on a subpixel translation",
      not near(t3(translate="0.03 0.02 0", filter="catmull_rom"),
               t3(translate="0.03 0.02 0", filter="bilinear")))
check("Layers moves only the named layer", near(L(run(T3, cop=img_with(16, 16, C=src16, D=src16), layers="D",
                                     translate="0.25 0 0"), "C")[..., 0], src16, 1e-6))
check("panel check_layout is empty", PANEL.check_layout(T3, M[T3].INPUT_TYPES()) == [])

# ═══════════════════════════════════════════════════ Align
AW = "PCG_COPAlignWindow"
sec("Align (align by window)")
s84 = np.arange(32, dtype=float).reshape(4, 8) + 1
src84 = img_with(8, 4, C=s84)
ref88 = img_with(8, 8, C=np.zeros((8, 8)))


def aw(**kw):
    a = dict(source=src84, size_ref=ref88)
    a.update(kw)
    return L(run(AW, **a), "C")[..., 0]


def placed(r0):
    z = np.zeros((8, 8))
    z[r0:r0 + 4] = s84
    return z


check("default Center / Same: source placed on rows 2–5", near(aw(), placed(2), 1e-6))
check("Justify Y Min: placed on rows 0–3", near(aw(justify_y="min"), placed(0), 1e-6))
check("Justify Y Max: rows 4–7", near(aw(justify_y="max"), placed(4), 1e-6))
check("Justify Min → Goal Center: source bottom edge to the reference center line, rows 4–7",
      near(aw(justify_y="min", goal_y="center"), placed(4), 1e-6))
check("Justify None: doesn't move (= original position rows 2–5)", near(aw(justify_y="none", goal_y="max"), placed(2), 1e-6))
check("output resolution = size_ref", aw().shape == (8, 8))
check("Offset 0.25 0: shift right 1 pixel", near(aw(offset="0.25 0")[2:6, 1:], s84[:, :-1], 1e-6))
gy = img_with(8, 4, C=np.tile(np.arange(4, dtype=float)[:, None], (1, 8)))
nu = L(run(AW, source=gy, size_ref=ref88, scale_to_fit=True, uniform_scale=False), "C")[..., 0]
X8, Y8 = WP.image_coords(8, 8)
_, py8 = WP.image_to_pixel(X8, Y8 / 2, 8, 4)
check("Scale to Fit non-uniform: y stretched 2× to fill (interior rows match the gradient)", near(nu[2:6], py8[2:6], 1e-6))
ux_ = aw(scale_to_fit=True)
check("Scale to Fit uniform + Scale X: ratio 1, unchanged", near(ux_, aw(), 1e-9))
uy_ = L(run(AW, source=gy, size_ref=ref88, scale_to_fit=True, scale_axis="y"), "C")[..., 0]
_, pyy = WP.image_to_pixel(X8 / 2, Y8 / 2, 8, 4)
check("Scale to Fit uniform + Scale Y: both axes ×2", near(uy_[2:6], pyy[2:6], 1e-6))
tp = aw(justify_with="target_point", target_point="0.5 0.5", target_size="1 1")
_, = [0]
check("Target Point (0.5, 0.5): source center moves there",
      near(tp, aw(offset="0.5 0.5"), 1e-6))
check("Units Texture (0.75, 0.75) = Image (0.5, 0.5)",
      near(aw(justify_with="target_point", units="texture", target_point="0.75 0.75"), tp, 1e-9))
check("Units Pixels (6, 6) = Image (0.5, 0.5)",
      near(aw(justify_with="target_point", units="pixels", target_point="6 6"), tp, 1e-9))
check("Units Texture Size: 0.5 = Image 1 (8×8)",
      near(aw(justify_with="target_point", units="texture", target_point="0.5 0.5",
              target_size="0.5 0.5", scale_to_fit=True),
           aw(justify_with="target_point", target_point="0 0", target_size="1 1", scale_to_fit=True)))
r84 = img_with(8, 4, C=np.zeros((4, 8)))
check("Units Pixels on a non-square reference (8×4): (6, 3) = Image (0.5, 0.25)",
      near(aw(size_ref=r84, justify_with="target_point", units="pixels", target_point="6 3"),
           aw(size_ref=r84, justify_with="target_point", target_point="0.5 0.25")))
gxs = img_with(8, 4, C=np.tile(np.arange(8, dtype=float), (4, 1)))
jm = L(run(AW, source=gxs, size_ref=ref88, scale_to_fit=True, scale_axis="y", justify_x="min"),
       "C")[..., 0]
pjm, _ = WP.image_to_pixel((X8 - 1) / 2, Y8 / 2, 8, 4)
check("scale first, then Justify: after Scale Y ×2 the left side −2 aligns to −1 (shift right 1; x gradient image, interior source columns)",
      near(jm[1:7, 1:], pjm[1:7, 1:], 1e-6) and pjm[0, 1] > 0)
check("Units World = Image",
      near(aw(justify_with="target_point", units="world", target_point="0.5 0.5"), tp, 1e-12))
tf = L(run(AW, source=gy, size_ref=ref88, justify_with="target_point", target_point="0 0",
           target_size="1 1", scale_to_fit=True), "C")[..., 0]
_, pyt = WP.image_to_pixel(X8 * 2, Y8 * 2, 8, 4)
check("Target Size 1 + Scale to Fit (Scale X): source shrinks to half width",
      near(tf[3:5, 2:6], pyt[3:5, 2:6], 1e-6) and near(tf[:, 0], 0))
check("without size_ref: reference = itself, by default it's the original image",
      near(L(run(AW, source=src84), "C")[..., 0], s84, 1e-6))
check("panel check_layout is empty", PANEL.check_layout(AW, M[AW].INPUT_TYPES()) == [])

# ═══════════════════════════════════════════════════ Align Pixels
AP = "PCG_COPAlignPixels"
sec("Align Pixels")
s42 = np.arange(8, dtype=float).reshape(2, 4) + 1
src42 = img_with(4, 2, C=s42)


def ap(**kw):
    a = dict(source=src42, size_ref=ref88)
    a.update(kw)
    return L(run(AP, **a), "C")[..., 0]


def at_(r0, c0, a=s42):
    z = np.zeros((8, 8))
    h, w = a.shape
    rr0, rr1 = max(r0, 0), min(r0 + h, 8)
    cc0, cc1 = max(c0, 0), min(c0 + w, 8)
    z[rr0:rr1, cc0:cc1] = a[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0]
    return z


check("default (snap Min, Justify Center → reference center): placed at (row 3, column 2), pixels bit-identical",
      np.array_equal(ap(), at_(3, 2)))
check("Justify None: snap only -- original window bottom-left (column 0, row 2)",
      np.array_equal(ap(justify_x="none", justify_y="none"), at_(2, 0)))
check("Side Max: snap top-right -- (column 4, row 4)",
      np.array_equal(ap(justify_x="none", justify_y="none", side_x="max", side_y="max"), at_(4, 4)))
check("Side Center: (column 2, row 3)",
      np.array_equal(ap(justify_x="none", justify_y="none", side_x="center", side_y="center"),
                     at_(3, 2)))
check("Side X Min, Side Y Max each control their own axis: (column 0, row 4)",
      np.array_equal(ap(justify_x="none", justify_y="none", side_x="min", side_y="max"), at_(4, 0)))
check("Original: after snapping with Side Max, align the Min edge back to the original window's Min edge → (column 0, row 2)",
      np.array_equal(ap(side_x="max", side_y="max", justify_with="original", justify_x="min",
                        justify_y="min"), at_(2, 0)))
check("Target Point (Pixels 1 1) + Justify Min: bottom-left corner to (1, 1)",
      np.array_equal(ap(justify_with="target_point", target_point="1 1", justify_x="min",
                        justify_y="min"), at_(1, 1)))
check("Target Point Image (0, 0) + Center = reference center",
      np.array_equal(ap(justify_with="target_point", units="image", target_point="0 0"), at_(3, 2)))
check("Target Point Texture (0.5, 0.5) same as above",
      np.array_equal(ap(justify_with="target_point", units="texture", target_point="0.5 0.5"),
                     at_(3, 2)))
check("Goal Max (Justify Min): left side to the reference's right side → entirely out of bounds", np.array_equal(
    ap(justify_x="min", goal_x="max"), at_(3, 8)))
check("Offset 1 −1 (pixels)", np.array_equal(ap(offset="1 -1"), at_(2, 3)))
check("Offset rounded: 0.4 = 0", np.array_equal(ap(offset="0.4 0"), ap()))
check("partially out of bounds copies only the overlap", np.array_equal(ap(offset="5 0"), at_(3, 7)))
check("without size_ref: stays in its own raster", np.array_equal(L(run(AP, source=src42), "C")[..., 0], s42))
check("panel check_layout is empty", PANEL.check_layout(AP, M[AP].INPUT_TYPES()) == [])

# ═══════════════════════════════════════════════════ Bend
BD = "PCG_COPBend"
sec("Bend")
GW = 32
Gs, Gt = np.meshgrid((np.arange(GW) + 0.5) / GW, (np.arange(GW) + 0.5) / GW)
gst = img_with(GW, GW, C=np.stack([Gs, Gt, np.ones_like(Gs)], -1))  # each pixel stores its own texture coordinate + 1 (< 1 where the edge fades out)
XG, YG = WP.image_coords(GW, GW)


def bd(**kw):
    a = dict(source=gst, mask_layer="m")
    a.update(kw)
    r = run(BD, **a)
    return L(r, "C"), L(r, "m")[..., 0]


def bez3(p0, p1, p2, p3, s):
    s = s[..., None]
    return (1 - s) ** 3 * p0 + 3 * (1 - s) ** 2 * s * p1 + 3 * (1 - s) * s ** 2 * p2 + s ** 3 * p3


def coons(B, T, Lf, R, c00, c10, c01, c11, s, t):
    S, Tt = s[..., None], t[..., None]
    return ((1 - Tt) * B(s) + Tt * T(s) + (1 - S) * Lf(t) + S * R(t)
            - ((1 - S) * (1 - Tt) * c00 + S * (1 - Tt) * c10 + (1 - S) * Tt * c01 + S * Tt * c11))


def inv_ok(st, m, F):
    """Patch F evaluated at the recovered (s, t) should return to the pixel's own position (only source-interior pixels unaffected by the edge fade)."""
    inner = (m > 0.5) & (st[..., 2] > 1 - 1e-6)
    q = F(st[..., 0], st[..., 1])
    err = np.hypot(q[..., 0] - XG, q[..., 1] - YG)[inner]
    return inner.sum() > 50 and err.max() < 1e-4, (int(inner.sum()), float(err.max()))


st0, m0 = bd()
check("Corners default: identity (square image)", near(st0, L(gst, "C"), 1e-5) and near(m0, 1))
st1, m1 = bd(bottom_left="-0.75 -1", bottom_right="1.25 -1", top_left="-0.75 1", top_right="1.25 1")
check("translating all four corners by 0.25 (handles are offsets, they follow) = shift right 4 pixels (1 pixel = 2/32), left four columns mask 0",
      near(st1[:, 4:], L(gst, "C")[:, :-4], 1e-5) and near(m1[:, :4], 0) and near(m1[:, 4:], 1))
cc = dict(bottom_left="-0.8 -0.9", bottom_right="0.9 -0.6", top_left="-0.6 0.9", top_right="0.7 0.8",
          bl_u="0.5 0.3", br_v="0.2 0.6", tl_u="0.7 -0.3", tr_v="-0.3 -0.5")
stc, mc = bd(**cc)
P = {k: np.asarray([float(x) for x in v.split()]) for k, v in defaults(BD).items()
     if k in ("bl_u", "bl_v", "br_u", "br_v", "tl_u", "tl_v", "tr_u", "tr_v")}
P.update({k: np.asarray([float(x) for x in v.split()]) for k, v in cc.items()})
c00, c10 = P["bottom_left"], P["bottom_right"]
c01, c11 = P["top_left"], P["top_right"]
Fc = lambda s, t: coons(lambda s: bez3(c00, c00 + P["bl_u"], c10 + P["br_u"], c10, s),   # noqa: E731
                        lambda s: bez3(c01, c01 + P["tl_u"], c11 + P["tr_u"], c11, s),
                        lambda t: bez3(c00, c00 + P["bl_v"], c01 + P["tl_v"], c01, t),
                        lambda t: bez3(c10, c10 + P["br_v"], c11 + P["tr_v"], c11, t),
                        c00, c10, c01, c11, s, t)
ok_, info = inv_ok(stc, mc, Fc)
check("Corners general case: recovered (s, t) fed into an independently implemented Coons patch = pixel position", ok_, info)
check("negative control: with Corners changed, the result is no longer identity", not near(stc, st0, 1e-3))
check("pixels outside the patch have mask 0 (near the bottom-left corner (−1,−1) is not in the patch)", mc[0, 0] == 0)
sd = dict(side_bottom="0 -0.6", side_right="0.8 0.2", side_top="0.1 1")
sts, mss = bd(mode="sides", **sd)
Q = {k: np.asarray([float(x) for x in v.split()]) for k, v in {**defaults(BD), **sd}.items()
     if k.startswith("side_") or k in ("bottom_left", "bottom_right", "top_left", "top_right")}


def q2(a, mid, b, s):
    c = 2 * mid - (a + b) / 2
    s = s[..., None]
    return (1 - s) ** 2 * a + 2 * (1 - s) * s * c + s * s * b


A0, A1, A2, A3 = Q["bottom_left"], Q["bottom_right"], Q["top_left"], Q["top_right"]
Fs = lambda s, t: coons(lambda s: q2(A0, Q["side_bottom"], A1, s),    # noqa: E731
                        lambda s: q2(A2, Q["side_top"], A3, s),
                        lambda t: q2(A0, Q["side_left"], A2, t),
                        lambda t: q2(A1, Q["side_right"], A3, t), A0, A1, A2, A3, s, t)
ok_, info = inv_ok(sts, mss, Fs)
check("Sides: recovered (s, t) fed into an independently implemented quadratic-edge Coons patch = pixel position", ok_, info)
rot = bd(mode="sides", bottom_left="1 -1", bottom_right="1 1", top_left="-1 -1", top_right="-1 1",
         side_bottom="1 0", side_top="-1 0", side_left="0 -1", side_right="0 1")
iG, jG = np.meshgrid(np.arange(GW), np.arange(GW), indexing="ij")
check("Sides rotated 90° (initial guess far from the solution, Newton needs several steps): out[i, j] = src[GW−1−j, i]",
      near(rot[0], L(gst, "C")[GW - 1 - jG, iG], 1e-5) and near(rot[1], 1))
h3 = "0.3333333"
sm, smm = bd(bottom_left="-0.5 -0.5", bottom_right="0.5 -0.5", top_left="-0.5 0.5", top_right="0.5 0.5",
             bl_u=f"{h3} 0", bl_v=f"0 {h3}", br_u=f"-{h3} 0", br_v=f"0 {h3}",
             tl_u=f"{h3} 0", tl_v=f"0 -{h3}", tr_u=f"-{h3} 0", tr_v=f"0 -{h3}")
inside_ = (np.abs(XG) <= 0.5) & (np.abs(YG) <= 0.5)
check("corners shrunk to ±0.5: mask is exactly |x|, |y| ≤ 0.5, output outside is 0",
      np.array_equal(smm > 0.5, inside_) and near(sm[~inside_], 0))
Gs2, Gt2 = np.meshgrid((np.arange(32) + 0.5) / 32, (np.arange(16) + 0.5) / 16)
g2 = img_with(32, 16, C=np.stack([Gs2, Gt2], -1))
h6 = "0.6666667"
nsq = L(run(BD, source=g2, bottom_left="-1 -0.5", bottom_right="1 -0.5", top_left="-1 0.5",
            top_right="1 0.5", bl_v=f"0 {h3}", br_v=f"0 {h3}", tl_v=f"0 -{h3}", tr_v=f"0 -{h3}"), "C")
check("non-square image (32×16): corners (±1, ±0.5), vertical handles 1/3 → identity", near(nsq, L(g2, "C"), 1e-5))
check("Sides default = identity", near(bd(mode="sides")[0], L(gst, "C"), 1e-5))
check("Sides doesn't read tangent handles", near(bd(mode="sides", bl_u="0.1 0.5")[0], bd(mode="sides")[0]))
check("Corners doesn't read edge midpoints", near(bd(side_bottom="0 -0.2")[0], st0))

sec("Bend:Angle")
R2 = 2 / math.pi
f = lambda p, both=False: WP.bend_angle_map(np.asarray(p, float), np.zeros(2), np.array([0., 1.]),  # noqa: E731
                                            1.0, 90.0, both)
check("90°, length 1: end of the capture segment (0, 1) → (−2/π, 2/π)", near(f([0, 1]), [-R2, R2], 1e-12))
c45 = math.cos(math.pi / 4)
check("midpoint (0, 0.5) turns 45°: (−R + R·cos45, R·sin45)", near(f([0, 0.5]), [-R2 + R2 * c45, R2 * c45], 1e-12))
check("off-axis point b = −0.1 has radius R + 0.1", near(f([0.1, 0.5]), [-R2 + (R2 + 0.1) * c45, (R2 + 0.1) * c45], 1e-12))
check("beyond the capture segment: goes straight along the end tangent ((0, 1.5) → (−2/π − 0.5, 2/π))",
      near(f([0, 1.5]), [-R2 - 0.5, R2], 1e-12))
check("before the capture origin: unchanged", near(f([0.3, -0.5]), [0.3, -0.5]))
check("Both Directions: bends the same way in the opposite direction ((0, −0.5) → (−R + R·cos45, −R·sin45))",
      near(f([0, -0.5], True), [-R2 + R2 * c45, -R2 * c45], 1e-12))
gim = img_with(GW, GW, C=np.stack([XG, YG, np.ones_like(XG)], -1))  # each pixel stores its own image coordinate + 1
ra = run(BD, source=gim, mode="angle", bend_angle=60.0, capture_origin="0 -0.5",
         capture_direction="1 1", capture_length=0.8, mask_layer="m")
pa, ma = L(ra, "C"), L(ra, "m")[..., 0]
Fa = WP.bend_angle_map(pa[..., :2], np.array([0, -0.5]), np.array([1., 1.]), 0.8, 60.0, False)
inner = (ma > 0.5) & (pa[..., 2] > 1 - 1e-6)
check("Angle: the inverted source position maps forward back to the pixel itself", inner.sum() > 300 and
      np.abs(Fa - np.stack([XG, YG], -1))[inner].max() < 1e-4)
check("Angle: pixels before the capture origin unchanged", near(pa[(XG + YG) < -0.6], gim.need("C")[(XG + YG) < -0.6], 1e-6))
check("negative control: Bend Angle 0 = identity", near(L(run(BD, source=gim, mode="angle", bend_angle=0.0), "C"),
                                    L(gim, "C")))
fb = run(BD, source=gim, mode="angle", bend_angle=300.0, capture_origin="0 -1", capture_length=1.0,
         mask_layer="m")
fbm = L(fb, "m")[..., 0]
check("Angle 300° (bent too far, folds over itself): pixels that can't be inverted output 0", (fbm < 0.5).sum() > 20
      and near(L(fb, "C")[fbm < 0.5], 0), int((fbm < 0.5).sum()))
check("no mask layer by default", "m" not in run(BD, source=gst).names)
check("size_ref sets the resolution", L(run(BD, source=gst, size_ref=img_with(10, 6, C=np.zeros((6, 10)))),
                              "C").shape[:2] == (6, 10))
check("Filter: point and bilinear differ",
      not near(L(run(BD, source=noise, **cc), "C"), L(run(BD, source=noise, filter="point", **cc), "C")))
check("panel check_layout is empty", PANEL.check_layout(BD, M[BD].INPUT_TYPES()) == [])


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
