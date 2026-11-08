"""
Terrain <-> AI round trip (pcg56) + two pieces of outstanding debt.

━━ Criteria
  · Debt 1, build.grid uv: sampling an asymmetric image with the built-in uv, points in the north (-Z) get the
    top half of the image; matches UV Project point by point (before the fix the two were flipped -- negative control)
  · Debt 2, Geometry Preview: Cd on point / vertex / prim / detail all render;
    objects above are at the top of the image (row 0 = top); no Cd gives a grey shaded model; 500k triangles in seconds
  · Splat Map: the five layers sum to **1 everywhere** (1e-12); layered compositing is a telescoping sum; water covers everything;
    rock only on steep slopes, snow must be high and not steep; sediment uses debris if present, else low flat ground; id =
    argmax; negative control: stacking without compositing makes the sum exceed 1
  · height control image: high = white, row 0 = top row of the COP; negative control: putting it in the depth slot is inverted
  · Regional Prompt: parsing (comments / blank lines / colons inside prompts / error on missing colon / error on missing layer
    listing the existing layers); the masks of all conditionings sum to 1 everywhere; the mask output flips v;
    empty regions are skipped; in global mode base has no mask; falls back for the old CLIP interface
  · Depth -> height field: back-projection matches the analytic formula; disparity and depth paths are equivalent; flat ground
    rendered at a 35° pitch, recovered pitch within < 1e-4° and height flat everywhere; top-down rasterization orientation (far =
    north = up, right = right); MoGe dict path (torch, inf, mask); top_down flips v;
    render a known terrain with the plugin's own renderer and lift it back -- the shape matches
  · Example workflows: generated from the live INPUT_TYPES; every node's widget count, combo values and link
    types are right; after conversion to API format it is **actually run** (core nodes stubbed, PCG nodes all real),
    the AI texture maps back onto the terrain with pixel-accurate orientation (negative control: flipping it vertically makes the error an order of magnitude larger); a muted
    MoGe is removed by the frontend rules and depth is used; unmuted, MoGe is used
"""
import json
import math
import os
import sys
import tempfile
import time

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
from comfyui_pcg.geo.cop import (splat as SP, regions as RG,  # noqa: E402
                                 lift as LF, control as CT, terrain as TR,
                                 backend as BK)
from comfyui_pcg.geo import (build as BUILD, convert as CV,  # noqa: E402
                             render as RD, uvproject as UVP,
                             frommap as FM)
from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX, PRIM,  # noqa: E402
                                  DETAIL)
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

try:
    import torch
except Exception:                                        # noqa: BLE001
    torch = None

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
    a = img.need(name)
    if not isinstance(a, np.ndarray):
        a = BK.backend_of(a).to_numpy(a)
    return np.asarray(a, np.float64)


def himg(h, name="C", **more):
    h = np.asarray(h, np.float64)
    lay = {name: h[:, :, None] if h.ndim == 2 else h}
    for k, v in more.items():
        v = np.asarray(v, np.float64)
        lay[k] = v[:, :, None] if v.ndim == 2 else v
    return CopImage(h.shape[1], h.shape[0], lay)


def R_(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


def npx(a):
    return a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a)


rng = np.random.default_rng(11)


# ═══════════════════════════════════════════════════ 1. Debt: build.grid uv
sec("Debt 1: build.grid uv")
g = BUILD.grid(2.0, 2.0, 9, 9)
tex = np.zeros((16, 16))
tex[8:, :] = 1.0                         # top half of the COP (v > 0.5) = 1
gm, _ = FM.attribute_from_map(g, himg(tex), name="t")
P = np.asarray(gm.get(POINT, "P"))
t = np.asarray(gm.get(POINT, "t"))[:, 0]
north = P[:, 2] < -0.3
south = P[:, 2] > 0.3
check("built-in uv sampling: north (-Z) points get the top half of the image, south points the bottom half",
      bool((t[north] == 1).all() and (t[south] == 0).all()),
      f"north {t[north].mean():.2f} south {t[south].mean():.2f}")
guv = np.asarray(g.get(POINT, "uv"), np.float64)[:, :2]
check("  uv = (x/width + ½, ½ - z/depth): same convention as HeightField to Mesh",
      np.allclose(guv, np.stack([P[:, 0] / 2 + 0.5, 0.5 - P[:, 2] / 2], -1),
                  atol=1e-6))
pj = UVP.project(g, mode="planar", axis="y", cls=POINT, name="uvp")
pu = np.asarray(pj.get(POINT, "uvp"), np.float64)[:, :2]


def _sgn(uv):
    tri = g.triangles()
    a_, b_, c_ = uv[tri[:, 0]], uv[tri[:, 1]], uv[tri[:, 2]]
    return np.sign((b_[:, 0] - a_[:, 0]) * (c_[:, 1] - a_[:, 1])
                   - (b_[:, 1] - a_[:, 1]) * (c_[:, 0] - a_[:, 0]))


check("  same handedness as UV Project (planar, y) (its u runs along Z, v along X, rotated 90°, "
      "but not mirrored; before the fix it was mirrored)", bool((_sgn(guv) == _sgn(pu)).all()))

# ═══════════════════════════════════════════════════ 2. Debt: Geometry Preview
sec("Debt 2: Geometry Preview reads Cd")
quad = Geometry.from_mesh(np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0],
                                    [-1, 1, 0]], np.float32),
                          np.array([[0, 1, 2, 3]], np.int32))
red = np.array([0.9, 0.1, 0.1])
for cls, n in ((POINT, 4), (VERTEX, 4), (PRIM, 1), (DETAIL, 1)):
    q = quad.copy()
    q.set(cls, "Cd", np.tile(red, (n, 1)))
    im = CV.render_preview(q, 64, 64, 0.0, 0.0, "color")
    c = im[32, 32]
    lam = float(np.clip(np.array([0, 0, 1.0]) @ CV._LIGHT, 0, 1))
    want = red * (0.3 + 0.7 * lam)
    check(f"Cd on {cls}: center pixel = Cd × lighting",
          np.allclose(c, want, atol=1e-5), f"{np.round(c, 4)}")
im = CV.render_preview(quad, 64, 64, 0.0, 0.0, "color")
check("  no Cd: grey shaded model (three channels equal)",
      abs(float(im[32, 32, 0]) - float(im[32, 32, 2])) < 1e-9
      and float(im[32, 32, 0]) > 0.2)
two = Geometry.from_mesh(np.array([[-1, 0.2, 0], [1, 0.2, 0], [1, 1, 0],
                                   [-1, 1, 0], [-1, -1, 0], [1, -1, 0],
                                   [1, -0.2, 0], [-1, -0.2, 0]], np.float32),
                         np.array([[0, 1, 2, 3], [4, 5, 6, 7]], np.int32))
two.set(PRIM, "Cd", np.array([[1.0, 0, 0], [0, 0, 1.0]]))
im = CV.render_preview(two, 64, 64, 0.0, 0.0, "color")
top, bot = im[:24].reshape(-1, 3).sum(0), im[40:].reshape(-1, 3).sum(0)
check("orientation: the red quad above (+Y) is in the top half, the blue quad below in the bottom half (IMAGE row 0 = top)",
      top[0] > 10 * top[2] and bot[2] > 10 * bot[0])
err("bad Shading raises", lambda: CV.render_preview(quad, 8, 8, 0, 0, "x"),
    "Shading")
check("empty geometry: all black, does not raise",
      float(CV.render_preview(Geometry(), 8, 8).max()) == 0.0)
n_ = 512
xx = (np.arange(n_) + 0.5) / n_
XX, YY = np.meshgrid(xx, xx)
big = TR.to_mesh(himg(0.1 * np.sin(6 * XX) * np.cos(5 * YY)))
t0 = time.time()
im = CV.render_preview(big, 512, 512, 35, 20, "lambert")
dt = time.time() - t0
check(f"512² terrain mesh ({len(big.triangles())} triangles) renders in {dt:.2f} s"
      " (limit 30 s; the old per-triangle loop took minutes)", dt < 30)
if torch is not None:
    r = R_(MAP["PCG_PreviewImage"]().run(quad, 32, 32, 0.0, 0.0, "color",
                                         "Cd"))
    check("node: optional color_attrib input, outputs a (1,H,W,3) IMAGE",
          tuple(r[0].shape) == (1, 32, 32, 3))

# ═══════════════════════════════════════════════════ 3. Splat Map
sec("Splat Map")
H, W = 64, 80
J, I = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))
terr = 0.25 * np.exp(-((J - 40) ** 2 + (I - 32) ** 2) / 300.0) \
    + 0.01 * rng.random((H, W))
lake = np.where((J < 12) & (I < 10), 0.01, 0.0)
river = np.clip(1 - np.abs(J - 60) / 2.0, 0, 1) * (I > 20)
debris = np.where((J > 20) & (J < 30), 0.02, 0.0)
im = himg(terr, lake=lake, river=river, debris=debris)
out, rep = SP.splat_map(im, world_size=1.0)
parts = [L(out, f"splat_{m}")[..., 0] for m in SP.MATERIALS]
tot = sum(parts)
check(f"the five layers sum to 1 everywhere (max deviation {np.abs(tot - 1).max():.1e})",
      float(np.abs(tot - 1).max()) < 1e-12)
check("  every layer is in [0, 1]", all(float(p.min()) >= 0 and float(p.max()) <= 1
                              for p in parts))
wat = parts[4]
check("water covers everything: water = 1 in the lake and on the river, everything else 0",
      bool((wat[lake > 1e-4] == 1).all() and (wat[river == 1] == 1).all()
           and all((p[river == 1] == 0).all() for p in parts[:4])))
ms = [rng.random((5, 7)) for _ in range(4)]
effs, rest = SP.compose(ms)
check("layered compositing: Σ eff + remainder = 1 (telescoping sum), top layer unchanged",
      float(np.abs(sum(effs) + rest - 1).max()) < 1e-12
      and np.array_equal(effs[-1], ms[-1]))
raw_sum = sum(np.clip(m, 0, 1) for m in ms)
check("  negative control: stacking without compositing, the sum reaches "
      f"{raw_sum.max():.2f}(> 1)", float(raw_sum.max()) > 1.5)
# rock: slopes
o2, _ = SP.splat_map(himg(-math.tan(math.radians(60)) * (J + 0.5) / W),
                     water_layers="")
o3, _ = SP.splat_map(himg(-0.1 * (J + 0.5) / W), water_layers="")
check("rock: a 60° slope is all rock (snow excluded by slope), a 6° slope has no rock at all",
      float(L(o2, "splat_rock").min()) > 0.999
      and float(L(o3, "splat_rock").max()) == 0.0)
o4, _ = SP.splat_map(himg(0.02 * (J + 0.5) / W), water_layers="",
                     sediment_layer="", flat_angle=8.0, sediment_height=0.3)
sn, sd = L(o4, "splat_snow")[..., 0], L(o4, "splat_sediment")[..., 0]
check("snow up high (normalized height > snow line + soft edge), sediment on low flat ground",
      float(sn[:, -2:].min()) > 0.999 and float(sn[:, :W // 2].max()) == 0
      and float(sd[:, :W // 5].min()) > 0.999)
check(f"  sediment source: uses the debris layer if there is one (report: {rep['_sediment_source']})",
      rep["_sediment_source"] == "layer debris"
      and float(parts[1][(debris > 0) & (river == 0) & (lake == 0)
                         & (parts[2] < 1e-9) & (parts[3] < 1e-9)].min())
      > 0.99)
o5, _ = SP.splat_map(himg(0.02 * (J + 0.5) / W), height_mode="absolute",
                     snow_line=0.015, snow_falloff=0.0, water_layers="",
                     sediment_layer="")
sn5 = L(o5, "splat_snow")[..., 0]
check("absolute: the snow line is the height value itself",
      bool((sn5[:, (0.02 * (np.arange(W) + 0.5) / W) >= 0.015] == 1).all())
      and bool((sn5[:, (0.02 * (np.arange(W) + 0.5) / W) < 0.015]
                == 0).all()))
ids = L(out, "splat_id")[..., 0]
check("splat_id = index of the material with the largest share",
      np.array_equal(ids, np.argmax(np.stack(parts, -1), -1)))
rgba = L(out, "splat_rgba")
check("splat_rgba = (rock, snow, sediment, water), grass is implied as 1 - the rest",
      np.allclose(rgba[..., 0], parts[2]) and np.allclose(rgba[..., 3],
                                                          parts[4])
      and np.allclose(1 - rgba.sum(-1), parts[0], atol=1e-12))
err("bad Height Mode", lambda: SP.splat_map(im, height_mode="x"),
    "Height Mode")

# ═══════════════════════════════════════════════════ 4. height control image
sec("Control Image: height mode")
hh = (I + 0.5) / H                       # higher and higher towards +v (north)
cimg, cm = CT.control_image(himg(hh), "height", mask_layer="", align=0)
c0 = cimg[0, :, :, 0]
check("high = white: IMAGE row 0 (top = north = highest) is 1, the last row is 0",
      abs(float(c0[0].mean()) - 1) < 1e-6 and abs(float(c0[-1].mean())) < 1e-6)
cd_, _ = CT.control_image(himg(hh), "depth", layer="C", mask_layer="",
                          align=0)
check("  negative control: the same height in the depth mode is inverted (mountains become pits)",
      float(cd_[0, 0].mean()) < 0.01 and float(cd_[0, -1].mean()) > 0.99)
cr, _ = CT.control_image(himg(hh), "height", mask_layer="", near=0.25,
                         far=0.75, align=0)
check("  manual range: clamped outside 0.25~0.75, linear in between",
      abs(float(cr[0, H // 2, 0, 0])
          - ((H - 1 - H // 2 + 0.5) / H - 0.25) / 0.5) < 1e-6
      and float(cr[0, 0, 0, 0]) == 1.0)

# ═══════════════════════════════════════════════════ 5. Regional Prompt
sec("Regional Prompt")
ents = RG.parse("# comment\n\nsplat_rock: granite: cliffs\n  splat_water :"
                " river  \n")
check("parse: skips comments and blank lines; splits at the first colon, prompts may contain colons; strips both sides",
      ents == [("splat_rock", "granite: cliffs"), ("splat_water", "river")])
err("a line without a colon raises", lambda: RG.parse("splat_rock granite"), "has no colon")
err("missing layer: raises and lists the existing layers",
    lambda: RG.region_masks(out, [("nope", "x")]), "splat_rock")
e2 = [(f"splat_{m}", m) for m in ("sediment", "rock", "snow", "water")]
effs, rest = RG.region_masks(out, e2, "normalized", 0.0)
check("normalized: splat layers used as-is (effective mask = splat layer), remainder = grass, sum = 1 everywhere",
      all(np.allclose(e, p) for e, p in zip(effs, parts[1:]))
      and np.allclose(rest, parts[0])
      and float(np.abs(sum(effs) + rest - 1).max()) < 1e-12)
effs_l, rest_l = RG.region_masks(out, e2, "layered", 0.0)
dl = max(float(np.abs(e - p).max()) for e, p in zip(effs_l, parts[1:]))
check(f"  negative control: compositing already-partitioned splats with layered = double compositing, off by {dl:.2f} in the transition band"
      " (the first version only had layered, and was wrong exactly like this)", dl > 0.05)
ov = himg(terr, a=np.full((H, W), 0.8), b=np.full((H, W), 0.6))
eo, ro = RG.region_masks(ov, [("a", "x"), ("b", "y")], "normalized", 0.0)
check("  normalized: where the sum is 1.4 it is normalized by the sum (0.8/1.4, 0.6/1.4), remainder 0",
      np.allclose(eo[0], 0.8 / 1.4) and np.allclose(eo[1], 0.6 / 1.4)
      and float(ro.max()) == 0.0)
el, rl = RG.region_masks(ov, [("a", "x"), ("b", "y")], "layered", 0.0)
check("layered: later lines cover earlier ones (b unchanged 0.6, a = 0.8 × 0.4), sum = 1 everywhere",
      np.allclose(el[1], 0.6) and np.allclose(el[0], 0.32)
      and np.allclose(el[0] + el[1] + rl, 1))
effs_f, rest_f = RG.region_masks(out, e2, "layered", 2.0)
check("feather: still sums to 1 everywhere after blurring, but the edges are softer",
      float(np.abs(sum(effs_f) + rest_f - 1).max()) < 1e-12
      and float(np.abs(effs_f[3] - effs[3]).max()) > 0.05)
pv = RG.preview(effs, rest)
check("preview: (H,W,3), the remainder is dark grey", pv.shape == (H, W, 3)
      and np.allclose(pv[rest == 1], 0.25))


class FakeCLIP:
    def __init__(self):
        self.calls = []

    def tokenize(self, t):
        return t

    def encode_from_tokens_scheduled(self, tok):
        self.calls.append(tok)
        return [[torch.full((1, 77, 4), float(len(tok))),
                 {"pooled_output": torch.zeros(1, 4), "text": tok}]]


class OldCLIP:
    def tokenize(self, t):
        return t

    def encode_from_tokens(self, tok, return_pooled=False):
        return torch.ones(1, 77, 4), torch.zeros(1, 4)


if torch is None:
    print("  (no torch, skipping the node part)")
else:
    node = MAP["PCG_RegionalPrompt"]()
    txt = "\n".join(f"{n}: {p}" for n, p in e2)
    cond, pvw, masks, rep_ = R_(node.run(FakeCLIP(), out, "base", txt, 0.8,
                                         "normalized", "remainder", 0.0))
    ms_ = [c[1].get("mask") for c in cond]
    tot_ = sum(npx(m) for m in ms_ if m is not None)
    check(f"node: all {len(cond)} conditionings carry masks that sum to 1 everywhere (the sampler takes a "
          "mask-weighted average; anywhere not covered gets a zero prediction)",
          all(m is not None for m in ms_)
          and float(np.abs(tot_ - 1).max()) < 1e-6, rep_.splitlines()[0])
    texts = [c[1]["text"] for c in cond]
    check("  order: base first, regions in written order; strength and set_area_to_bounds follow core"
          " ConditioningSetMask",
          texts[0] == "base" and texts[1:] == [p for _, p in e2]
          and all(c[1]["mask_strength"] == 0.8
                  and c[1]["set_area_to_bounds"] is False for c in cond))
    wm = npx(cond[-1][1]["mask"])[0]
    check("  output flips v: mask row 0 = top row of the COP",
          np.allclose(wm, parts[4][::-1], atol=1e-6))
    check("  masks output: (region count, H, W), matching the conditioning",
          tuple(masks.shape) == (4, H, W)
          and np.allclose(npx(masks[3]), wm))
    check("  preview:(1,H,W,3)", tuple(pvw.shape) == (1, H, W, 3))
    empty = himg(terr, z=np.zeros((H, W)), o=np.ones((H, W)))
    cond2, _, _, rep2 = R_(node.run(FakeCLIP(), empty, "b", "z: nothing\n"
                                    "o: everything", 1.0, "layered",
                                    "remainder", 0.0))
    check("  empty regions skipped; base unused when the remainder is empty",
          [c[1]["text"] for c in cond2] == ["everything"]
          and "skipped" in rep2 and "unused" in rep2)
    cond3, _, _, _ = R_(node.run(FakeCLIP(), out, "base", txt, 1.0, "layered",
                                 "global", 0.0))
    check("  global: base has no mask", "mask" not in cond3[0][1]
          and cond3[0][1]["text"] == "base")
    cond4, _, _, _ = R_(node.run(OldCLIP(), out, "b", txt, 1.0, "layered",
                                 "remainder", 0.0))
    check("  old CLIP versions (only encode_from_tokens) also work",
          len(cond4) == 5 and "pooled_output" in cond4[0][1])

# ═══════════════════════════════════════════════════ 6. Depth -> height field
sec("Depth / MoGe -> height field")
Hd, Wd = 40, 60
dep = np.full((Hd, Wd), 2.0)
Pd, vd = LF.points_from_depth(dep, 90.0, "depth")
fx = (Wd / 2) / math.tan(math.radians(45))
check("back-projection: z = depth, x = (j + ½ - W/2)/f·z, y points down",
      np.allclose(Pd[..., 2], 2.0)
      and abs(Pd[0, 0, 0] - (0.5 - Wd / 2) / fx * 2) < 1e-12
      and Pd[0, 0, 1] < 0 < Pd[-1, 0, 1])
Pp, vp = LF.points_from_depth(1.0 / dep, 90.0, "disparity", shift=0.0,
                              sky=0.0)
check("  disparity = 1/z, shift = 0: both paths identical point by point",
      np.allclose(Pp, Pd) and vp.all())
Ps, vs = LF.points_from_depth(np.where(J[:Hd, :Wd] < 5, 0.0, 0.5), 60.0,
                              "disparity", sky=0.02)
check("  disparity below sky is sky (invalid)",
      not vs[:, :5].any() and vs[:, 5:].all())
err("FOV out of range", lambda: LF.points_from_depth(dep, 0.5), "FOV")


def render_scene(hfun, pitch_eye=(0.0, 0.75, 1.0), target=(0.0, 0.0, -0.05),
                 n=128, xres=320, yres=240, fov=50.0):
    xs = (np.arange(n) + 0.5) / n
    XX, YY = np.meshgrid(xs, xs)
    hh = hfun(XX, YY)
    msh = TR.to_mesh(himg(hh), world_size=1.0)
    col = np.stack([XX, YY, 0.5 + 0 * XX], -1)
    msh.set(POINT, "Cd", col.reshape(-1, 3))
    cam = RD.camera(None, "perspective", eye=pitch_eye, target=target,
                    fov=fov, xres=xres, yres=yres)
    img = RD.render(msh, cam, passes=("depth", "mask"))
    z = np.asarray(img.need("depth"), np.float64)[:, :, 0]
    m = np.asarray(img.need("mask"), np.float64)[:, :, 0] > 0.5
    rast = RD.rasterize(msh, cam)
    c = CV._attrib_image(msh, rast, "Cd")
    fovx = 2 * math.degrees(math.atan(math.tan(math.radians(fov / 2))
                                      * xres / yres))
    # COP orientation (row 0 = bottom) -> IMAGE / OpenCV orientation (row 0 = top)
    return (np.where(m, z, 0.0)[::-1].copy(), m[::-1].copy(),
            c[::-1].copy(), cam, fovx, hh)


z0, m0, c0_, cam0, fovx0, _ = render_scene(lambda X, Y: 0 * X)
true_pitch = math.degrees(math.asin(-cam0["forward"][1]))
Pf, vf = LF.points_from_depth(z0, fovx0, "depth")
o_, ex, ey, ez, rp = LF.ground_frame(Pf, vf, "fit_plane")
check(f"flat ground, pitch {true_pitch:.2f}°: the plane fit recovers the pitch, off by "
      f"{abs(rp['camera_pitch_deg'] - true_pitch):.1e}°",
      abs(rp["camera_pitch_deg"] - true_pitch) < 1e-4)
check("  the basis is right-handed orthonormal, ex along camera right, ez towards the camera",
      abs(np.linalg.det(np.stack([ex, ey, ez]))) - 1 < 1e-9
      and ex[0] > 0.99 and ez[2] < 0)
hf_flat, Lf, rpf = LF.heightfield_from_points(Pf, vf, None, 128,
                                              "fit_plane", 1.0, True)
hv = L(hf_flat, "C")[..., 0]
check(f"  lifted to a height field, flat everywhere (height range {rpf['height_range']:.1e}, relative to world width "
      f"{Lf:.3f})", rpf["height_range"] < 1e-5 * Lf)
_, _, _, _, rpl = LF.ground_frame(Pf, vf, "camera_level")
check("camera_level: no fit, the normal is the camera up direction",
      rpl["up_mode"] == "camera_level")
zr, mr, _, camr, fxr, _ = render_scene(
    lambda X, Y: 0.15 * np.clip((0.3 - Y) / 0.3, 0, 1))
Pr, vr = LF.points_from_depth(zr, fxr, "depth")
_, _, _, _, rpr = LF.ground_frame(Pr, vr, "fit_plane")
err_r = rpr["camera_pitch_deg"] - true_pitch
check(f"a nearby slope (many pixels, little area) only skews the pitch by {err_r:.1f}° (z² weighted; unweighted"
      " it is -6.3°)", abs(err_r) < 4.0)
wall = np.stack(np.meshgrid(np.linspace(-1, 1, 20), np.linspace(-1, 1, 20)),
                -1)
Pw = np.concatenate([wall, np.full((20, 20, 1), 3.0)], -1)
_, _, eyw, _, rpw = LF.ground_frame(Pw, np.ones((20, 20), bool),
                                    "fit_plane")
check("facing a wall: the plane-fit normal is 90° from camera up, falls back to camera_level",
      "fell back" in rpw["up_mode"] and np.allclose(eyw, [0, -1, 0]))
# rasterization orientation: points land exactly on cell centers
Rn = 8
jj, ii = np.meshgrid(np.arange(Rn), np.arange(Rn))
Xc = (jj + 0.5).ravel().astype(float)
Zc = -(ii + 0.5).ravel().astype(float)          # larger row = further north = more negative Z
Yc = (jj * 10 + ii).ravel().astype(float)
Hm, cov, col, Lw = LF.rasterize(Xc, Yc, Zc, None, Rn, (0, 8, -8, 0))
check("top-down rasterization: points at cell centers land cell by cell; u along +X, v along -Z (north = up)",
      bool(cov.all()) and np.array_equal(Hm, jj * 10.0 + ii))
Hm2, _, _, _ = LF.rasterize(np.r_[Xc, Xc], np.r_[Yc, Yc - 5], np.r_[Zc, Zc],
                            None, Rn, (0, 8, -8, 0))
check("  several points in one cell are averaged (taking the highest gives moire on the hillshade)",
      np.allclose(Hm2, jj * 10.0 + ii - 2.5))
# MoGe dict
if torch is not None:
    pts = torch.from_numpy(Pf[None]).float()
    pts[0, :3] = float("inf")
    mk = torch.from_numpy(vf[None].copy())
    mk[0, :, :2] = False
    geom = {"points": pts, "mask": mk,
            "image": torch.from_numpy(c0_[None]).float()}
    Pm, vm, cm_ = LF.points_from_moge(geom)
    check("MoGe: torch tensors to numpy, inf and mask both count as invalid, the bundled image is used as color",
          not vm[:3].any() and not vm[:, :2].any()
          and vm[3:, 2:].sum() == vf[3:, 2:].sum() and cm_.shape == c0_.shape)
    hfm, Lm, rpm = LF.lift(moge_geometry=geom, resolution=96)
    check("  lift goes through MoGe, outputs C / mask / albedo layers",
          rpm["source"] == "moge" and sorted(hfm.names)
          == ["C", "albedo", "mask"])
err("MoGe dict has no points", lambda: LF.points_from_moge({"x": 1}),
    "points")
err("neither depth nor MoGe connected", lambda: LF.lift(), "at least one")
# top_down
td = np.tile(np.linspace(0, 1, 30)[:, None], (1, 20))    # IMAGE: brighter towards the bottom
htd, rtd = LF.heightfield_top_down(td, "disparity", relief=0.5)
hv = L(htd, "C")[..., 0]
check("top_down: bright disparity = high, flips v (IMAGE bottom -> COP row 0)",
      abs(hv[0].mean() - 0.5) < 1e-12 and abs(hv[-1].mean()) < 1e-12)
htd2, _ = LF.heightfield_top_down(td, "depth", relief=0.5)
check("  depth: dark = high", abs(L(htd2, "C")[0, 0, 0]) < 1e-12)
err("top_down without depth", lambda: LF.lift(mode="top_down"), "top_down")

# end to end: render a known terrain, lift it back
def mountain(X, Y):
    # a mountain in the north-west corner (small u, large v); large v in the COP = north
    return 0.22 * np.exp(-((X - 0.3) ** 2 + (Y - 0.7) ** 2) / 0.02) \
        + 0.02 * np.sin(9 * X) * np.cos(7 * Y)


zt, mt, ct, camt, fovxt, htrue = render_scene(mountain)
Pt, vt = LF.points_from_depth(zt, fovxt, "depth")
hft, Lt, rpt = LF.heightfield_from_points(Pt, vt, ct, 128, "fit_plane", 1.0,
                                          True)
hr = L(hft, "C")[..., 0]
mk_ = L(hft, "mask")[..., 0] > 0.5
q = hr.shape[0] // 2
pk = np.unravel_index(np.argmax(np.where(mk_, hr, -1)), hr.shape)
check(f"end to end: the north-west mountain is still in the north-west after lifting (peak at row {pk[0]}, col {pk[1]}, "
      f"of {hr.shape[0]}; large row = north, small col = west)",
      pk[0] > q and pk[1] < q)
tp_ = math.degrees(math.asin(-camt["forward"][1]))
check(f"  recovered pitch {rpt['camera_pitch_deg']:.2f}° (true {tp_:.2f}°; there is a big mountain far away, "
      "after removing the peaks and refitting the error is < 1°)",
      abs(rpt["camera_pitch_deg"] - tp_) < 1.0)
check(f"  height range {rpt['height_range']:.3f} ≈ true {np.ptp(htrue):.3f}(±25%)",
      abs(rpt["height_range"] / np.ptp(htrue) - 1) < 0.25)
check(f"  coverage {rpt['coverage'] * 100:.0f}%, the rest is filled in; albedo layer present",
      0.3 < rpt["coverage"] < 1.0 and "albedo" in hft)
d_disp = np.where(mt, 1.0 / np.where(mt, zt, 1.0), 0.0)
dn = (d_disp - d_disp[mt].min()) / (d_disp[mt].max() - d_disp[mt].min())
dn = np.where(mt, dn * 0.9 + 0.1, 0.0)           # Depth Anything style normalization
hfd, _, rpd = LF.lift(depth=dn[None, :, :, None].repeat(3, -1),
                      resolution=128, depth_kind="disparity", fov_x=fovxt,
                      shift=0.05)
hdv = L(hfd, "C")[..., 0]
mkd = L(hfd, "mask")[..., 0] > 0.5
pkd = np.unravel_index(np.argmax(np.where(mkd, hdv, -1)), hdv.shape)
check(f"relative disparity (unknown scale / shift) still lifts with the right orientation: peak at row {pkd[0]}, "
      f"col {pkd[1]} (north-west)", pkd[0] > q and pkd[1] < q)

# 8-bit depth (pcg115): Depth Anything through comfyui_controlnet_aux arrives on a 1/255 lattice; every level lifts
# to one arc on the ground, and the far field comes out as streaks. Dequantize restores continuous values.
# smooth "true" disparity changing slowly, as in the far field: one 8-bit level spans ~16 rows
ramp = np.tile(np.linspace(0.3, 0.4, 400)[:, None] ** 1.2, (1, 64))
ramp8 = np.round(ramp * 255) / 255
check("quantization_step: 1/255 for an 8-bit image, 0 for float, a constant or a 2-level mask",
      LF.quantization_step(ramp8) == 1 / 255 and LF.quantization_step(ramp) == 0
      and LF.quantization_step(np.full((20, 20), 0.5)) == 0
      and LF.quantization_step((np.arange(400).reshape(20, 20) % 2).astype(float)) == 0)
dq_, qq = LF.dequantize(ramp8)
e8, edq = np.abs(ramp8 - ramp).mean(), np.abs(dq_ - ramp).mean()
check(f"dequantize: error to the true ramp {e8:.1e} -> {edq:.1e} (< 1/3), never leaves its bin",
      qq == 1 / 255 and edq < e8 / 3 and np.all(np.abs(dq_ - ramp8) <= 0.5 / 255 + 1e-12))
st8 = np.unique(np.round(np.diff(ramp8[:, 0]) * 255)).size
check("  the steps are gone: neighbouring rows differ smoothly (8-bit: 0 or 1 level jumps)",
      st8 == 2 and np.abs(np.diff(dq_[8:-8, 0], 2)).max() < 0.05 / 255)
edge = np.where(np.arange(64)[None, :] < 32, 0.2, 0.8) + 0 * ramp8[:, :1]
edge8 = np.round(edge * 255) / 255
edge8[:, :32] = np.round(ramp8[:, :32] * 0.3 * 255) / 255
dqe, _ = LF.dequantize(edge8)
check("  a silhouette stays sharp (the clamp keeps the far side within half a level)",
      np.abs(dqe[:, 32:] - edge8[:, 32:]).max() <= 0.5 / 255 + 1e-12)
same, q0 = LF.dequantize(ramp)
check("  float input passes through untouched", q0 == 0 and same is not None and np.array_equal(same, ramp))
# end to end: flat ground seen by a camera 1 up, pitched down 12° (FOV 60, 512 x 384). The disparity of a ground
# plane is linear in the row; normalized Depth-Anything style it is exact apart from the 8-bit rounding, and every
# rounded row lifts off the plane -- the bumps of the streaks. Dequantized, the ground is flat again.
Wg, Hg, pg = 512, 384, math.radians(12)
fxg = (Wg / 2) / math.tan(math.radians(30))
yy = (np.arange(Hg)[:, None] + 0.5 - Hg / 2) / fxg + 0 * np.arange(Wg)[None, :]
den = yy * math.cos(pg) + math.sin(pg)
gm = den > 0.02
dg = np.where(gm, den, 0.0)
dg = np.where(gm, (dg - dg[gm].min()) / (dg[gm].max() - dg[gm].min()) * 0.9 + 0.1, 0.0)
rough = {}
for nm, dd, dqf in (("float", dg, True), ("8-bit", np.round(dg * 255) / 255, False),
                    ("8-bit dequantized", np.round(dg * 255) / 255, True)):
    hf_, Lg, rr = LF.lift(depth=dd[None, :, :, None].repeat(3, -1), resolution=128, depth_kind="disparity",
                          fov_x=60.0, shift=0.0, dequant=dqf)
    hv_, mv_ = L(hf_, "C")[..., 0], L(hf_, "mask")[..., 0] > 0.5
    rough[nm] = (float(hv_[mv_].std() / Lg), rr["dequantized"])
check(f"end to end, flat ground: height spread / world width  float {rough['float'][0]:.1e}, 8-bit "
      f"{rough['8-bit'][0]:.1e}, dequantized {rough['8-bit dequantized'][0]:.1e}",
      rough["8-bit"][0] > 5 * rough["8-bit dequantized"][0] and rough["8-bit dequantized"][0] < 1e-4)
check("  the report says whether it dequantized (float input: no)",
      rough["float"][1] == 0 and rough["8-bit dequantized"][1] == 1 / 255 and rough["8-bit"][1] == 0)
if torch is not None:
    r = R_(MAP["PCG_COPHeightfieldFromDepth"]().run(
        "perspective", 96, "depth", fovxt, 0.05, 0.02, "fit_plane", 1.0,
        True, 0.25, 1.0, 0,
        depth=torch.from_numpy(zt[None, :, :, None].repeat(3, -1)).float()))
    check("node: COP + world_size + report", isinstance(r[0], CopImage)
          and r[1] > 0 and "coverage" in r[2], r[2][:60])

# ═══════════════════════════════════════════════════ 7. Example workflows
sec("Example workflows")
import make_workflows as MW                              # noqa: E402

tmpd = tempfile.mkdtemp(prefix="pcg_wf_")
tmpd2 = tempfile.mkdtemp(prefix="pcg_wf_")
paths = MW.main(tmpd)
paths2 = MW.main(tmpd2)
check(f"all {len(MW.WORKFLOWS)} workflows generated, and regenerating is byte-identical",
      len(paths) == len(MW.WORKFLOWS) >= 2 and all(open(a, "rb").read() == open(b, "rb").read()
                              for a, b in zip(paths, paths2)))
wfs = {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8"))
       for p in paths}


def validate(wf):
    probs = []
    ids = {n["id"]: n for n in wf["nodes"]}
    for n in wf["nodes"]:
        if n["type"] == "Note":
            continue
        ins, outs = MW.spec_of(n["type"])
        want = sum(2 if t == "SEED" else 1 for _, t, _ in ins
                   if MW.is_widget(t))
        if len(n["widgets_values"]) != want:
            probs.append(f"{n['type']}: widgets {len(n['widgets_values'])}"
                         f" != {want}")
            continue
        k = 0
        for name, t, _ in ins:
            if not MW.is_widget(t):
                continue
            v = n["widgets_values"][k]
            if isinstance(t, list) and v not in t:
                probs.append(f"{n['type']}.{name} = {v!r} not in the combo")
            k += 2 if t == "SEED" else 1
        if [o["name"] for o in n["outputs"]] != [o for o, _ in outs]:
            probs.append(f"{n['type']}: wrong output name")
    for lid, a, sa, b, sb, t in wf["links"]:
        na, nb = ids[a], ids[b]
        if na["outputs"][sa]["type"] != t or nb["inputs"][sb]["type"] != t:
            probs.append(f"link {lid} type mismatch")
        if nb["inputs"][sb]["link"] != lid or \
                lid not in na["outputs"][sa]["links"]:
            probs.append(f"link {lid} not registered at both ends")
    return probs


for name, wf in wfs.items():
    pr = validate(wf)
    check(f"{name}: widget counts, combo values and link types all correct ({len(wf['nodes'])} nodes, "
          f"{len(wf['links'])} links)", not pr, "; ".join(pr[:3]))
    pcg = [n["type"] for n in wf["nodes"] if n["type"].startswith("PCG_")]
    check("  all PCG nodes registered", all(t in MAP for t in pcg), len(pcg))


def to_api(wf):
    """UI -> API, following the frontend graphToPrompt rules (muted nodes removed, inputs linked to them removed too)."""
    out = {}
    for n in wf["nodes"]:
        if n["type"] == "Note" or n["mode"] in (2, 4):
            continue
        ins, _ = MW.spec_of(n["type"])
        inputs = {}
        k = 0
        for name, t, _ in ins:
            if MW.is_widget(t):
                v = n["widgets_values"][k]
                k += 2 if t == "SEED" else 1
                if t != "UPLOAD":
                    inputs[name] = v
        for i, inp in enumerate(n["inputs"]):
            if inp["link"] is None:
                continue
            lk = [x for x in wf["links"] if x[0] == inp["link"]][0]
            inputs[inp["name"]] = [str(lk[1]), lk[2]]
        out[str(n["id"])] = {"class_type": n["type"], "inputs": inputs}
    for v in out.values():
        for k2, x in list(v["inputs"].items()):
            if isinstance(x, list) and len(x) == 2 and x[0] not in out:
                del v["inputs"][k2]
    return out


# ── stubs for core nodes ────────────────────────────────────────────────────
STATE = {}


def _stub(ntype, fn, ret):
    ins, _ = MW.spec_of(ntype)

    class S:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {}}
        RETURN_TYPES = ret
        FUNCTION = "run"

        def run(self, **kw):
            return fn(**kw)
    S.__name__ = ntype
    return S


PALETTE = {}


def _color(text):
    if text not in PALETTE:
        PALETTE[text] = CT.id_palette([len(PALETTE) + 1])[0]
    return PALETTE[text]


def _decode(samples, vae):
    Wl, Hl = samples["size"]
    img = torch.zeros(1, Hl, Wl, 3)
    for c in samples["conds"]:
        m = c[1].get("mask")
        m = torch.ones(1, Hl, Wl) if m is None else \
            torch.nn.functional.interpolate(m[None].float(), size=(Hl, Wl),
                                            mode="bilinear",
                                            align_corners=False)[0]
        img += m[..., None] * torch.tensor(_color(c[1]["text"]),
                                           dtype=torch.float32)
    STATE["decoded"] = img
    return (img.clamp(0, 1),)


def _scene_image(image, upload=None):
    z, m, c, cam, fovx, h = render_scene(mountain)
    STATE["scene"] = (z, m, cam, fovx)
    return (torch.from_numpy(c[None]).float(),
            torch.from_numpy(m[None].astype(np.float32)))


def _depth_any(image, ckpt_name=None, resolution=512):
    z, m, _, _ = STATE["scene"]
    d = np.where(m, 1.0 / np.where(m, z, 1.0), 0.0)
    d = np.where(m, (d - d[m].min()) / (d[m].max() - d[m].min()) * 0.9 + 0.1,
                 0.0)
    STATE["depth_used"] = True
    return (torch.from_numpy(d[None, :, :, None].repeat(3, -1)).float(),)


def _moge(moge_model, image, **kw):
    z, m, cam, fovx = STATE["scene"]
    P, v = LF.points_from_depth(z, fovx, "depth")
    P = np.where(v[..., None], P, np.inf)
    STATE["moge_used"] = True
    return ({"points": torch.from_numpy(P[None]).float(),
             "mask": torch.from_numpy(v[None]),
             "image": image},)


STUBS = {
    "CheckpointLoaderSimple": _stub("CheckpointLoaderSimple",
                                    lambda ckpt_name: ("MODEL", FakeCLIP(),
                                                       "VAE"),
                                    ("MODEL", "CLIP", "VAE")),
    "CLIPTextEncode": _stub("CLIPTextEncode",
                            lambda text, clip: (
                                clip.encode_from_tokens_scheduled(text),),
                            ("CONDITIONING",)),
    "ControlNetLoader": _stub("ControlNetLoader",
                              lambda control_net_name: ("CN",),
                              ("CONTROL_NET",)),
    "SetUnionControlNetType": _stub("SetUnionControlNetType",
                                    lambda control_net, type: (
                                        control_net + ":" + type,),
                                    ("CONTROL_NET",)),
    "ControlNetApplyAdvanced": _stub(
        "ControlNetApplyAdvanced",
        lambda positive, negative, control_net, image, strength,
        start_percent, end_percent, vae=None: (
            STATE.__setitem__("control", (image, control_net)) or positive,
            negative),
        ("CONDITIONING", "CONDITIONING")),
    "EmptyLatentImage": _stub("EmptyLatentImage",
                              lambda width, height, batch_size: (
                                  {"size": (width, height)},),
                              ("LATENT",)),
    "KSampler": _stub("KSampler",
                      lambda model, seed, steps, cfg, sampler_name, scheduler,
                      positive, negative, latent_image, denoise: (
                          {"size": latent_image["size"], "conds": positive},),
                      ("LATENT",)),
    "VAEDecode": _stub("VAEDecode", _decode, ("IMAGE",)),
    "SaveImage": _stub("SaveImage", lambda images, filename_prefix: (),
                       ()),
    "PreviewImage": _stub("PreviewImage",
                          lambda images: STATE.setdefault(
                              "previews", []).append(images) or (), ()),
    "LoadImage": _stub("LoadImage", _scene_image, ("IMAGE", "MASK")),
    "DepthAnythingV2Preprocessor": _stub("DepthAnythingV2Preprocessor",
                                         _depth_any, ("IMAGE",)),
    "LoadMoGeModel": _stub("LoadMoGeModel", lambda model_name: ("M",),
                           ("MOGE_MODEL",)),
    "MoGeInference": _stub("MoGeInference", _moge, ("MOGE_GEOMETRY",)),
}


def run_api(api):
    classes = dict(MAP)
    classes.update(STUBS)
    ex = fakecomfy.Executor(api, classes)
    res = {}
    for nid in api:
        res[nid] = ex.run(nid)
    return res, ex


if torch is None:
    print("  (no torch, skipping execution)")
else:
    wf1 = wfs["pcg_terrain_to_ai_texture"]
    api1 = to_api(wf1)
    old = os.getcwd()
    os.chdir(tmpd)
    t0 = time.time()
    try:
        res1, ex1 = run_api(api1)
        ok1 = True
    except Exception as ex:                              # noqa: BLE001
        import traceback
        traceback.print_exc()
        ok1, res1 = False, {}
    dt = time.time() - t0
    os.chdir(old)
    check(f"workflow 1 converted to API format really runs ({len(api1)} nodes, {dt:.1f} s;"
          " PCG nodes all real)", ok1)
    if ok1:
        byt = {v["class_type"]: k for k, v in api1.items()}
        cop_c = res1[byt["PCG_COPComposite"]][0]
        spl_c = res1[byt["PCG_COPSplatMap"]][0]
        alb = L(cop_c, "albedo")
        rp_node = res1[byt["PCG_RegionalPrompt"]]
        # expected: colors mixed by the effective masks (COP orientation)
        conds = rp_node[0]
        exp = np.zeros(alb.shape)
        for c in conds:
            m = npx(c[1]["mask"])[0][::-1]
            exp += m[:, :, None] * _color(c[1]["text"])[None, None, :]
        e_ok = float(np.abs(alb - exp).mean())
        e_flip = float(np.abs(alb - exp[::-1]).mean())
        check(f"AI texture back on the terrain: albedo matches the per-region mixed colors pixel by pixel"
              f" (mean error {e_ok:.4f})", e_ok < 0.01)
        check(f"  negative control: flipped vertically the error is {e_flip:.3f} (more than an order of magnitude larger)",
              e_flip > 10 * e_ok)
        img_c, cn_name = STATE["control"]
        hC = L(spl_c, "C")[..., 0]
        ci = npx(img_c)[0, :, :, 0]
        hn_ = (hC - hC.min()) / np.ptp(hC)
        check("  control image = normalized height, IMAGE orientation (vertically flipped vs COP), ControlNet"
              " set to the union depth mode",
              float(np.abs(ci - hn_[::-1]).max()) < 1e-5
              and cn_name.endswith(":depth"))
        msh = res1[byt["PCG_COPHeightfieldToMesh"]][0]
        check("  the mesh carries Cd (from the albedo layer), Geometry Preview produced a color image",
              msh.get(POINT, "Cd") is not None
              and float(npx(STATE["previews"][-1]).std()) > 0.02)
        glb = os.path.join(tmpd, "output", "pcg", "terrain_ai.glb")
        glb2 = os.path.join(tmpd, "pcg", "terrain_ai.glb")
        check("  Export Mesh wrote a glb", os.path.exists(glb)
              or os.path.exists(glb2))

    wf2 = wfs["pcg_image_to_terrain"]
    muted = [n["type"] for n in wf2["nodes"] if n.get("mode") == 2]
    check("workflow 2: the two MoGe nodes are muted by default (a stock install does not have the MoGe "
          "model yet)", sorted(muted) == ["LoadMoGeModel", "MoGeInference"])
    api2 = to_api(wf2)
    lf_id = [k for k, v in api2.items()
             if v["class_type"] == "PCG_COPHeightfieldFromDepth"][0]
    check("  converted to API by the frontend rules: muted nodes removed, the moge_geometry input linked to them removed too",
          "moge_geometry" not in api2[lf_id]["inputs"]
          and "depth" in api2[lf_id]["inputs"])
    STATE.clear()
    try:
        res2, _ = run_api(api2)
        rep2 = res2[lf_id][2]
        ok2 = True
    except Exception as ex:                              # noqa: BLE001
        import traceback
        traceback.print_exc()
        ok2, rep2 = False, ""
    check("  runs, using Depth Anything", ok2 and STATE.get("depth_used")
          and "depth(disparity)" in rep2, rep2[:70])
    for n in wf2["nodes"]:
        if n.get("mode") == 2:
            n["mode"] = 0
    api3 = to_api(wf2)
    STATE.clear()
    try:
        res3, _ = run_api(api3)
        rep3 = res3[lf_id][2]
        cop3 = res3[lf_id][0]
        ok3 = True
    except Exception as ex:                              # noqa: BLE001
        import traceback
        traceback.print_exc()
        ok3, rep3, cop3 = False, "", None
    check("  unmuted: MoGe takes priority", ok3 and STATE.get("moge_used")
          and rep3.startswith("moge"), rep3[:70])
    if ok3:
        h3 = L(cop3, "C")[..., 0]
        m3 = L(cop3, "mask")[..., 0] > 0.5
        q3 = h3.shape[0] // 2
        p3 = np.unravel_index(np.argmax(np.where(m3, h3, -1)), h3.shape)
        check("  lifted terrain: the north-west mountain is still in the north-west (after hydraulic erosion)",
              p3[0] > q3 and p3[1] < q3, str(p3))

# ═══════════════════════════════════════════════════ 8. Registration
sec("Registration")
names = ["PCG_COPSplatMap", "PCG_RegionalPrompt",
         "PCG_COPHeightfieldFromDepth"]
check("all three new nodes registered, all under PCG/cop",
      all(MAP[n].CATEGORY == "PCG/cop" for n in names))
check("Control Image kind gained height (appended at the end, combo values of old workflows unchanged)",
      CT.KINDS[-1] == "height" and CT.KINDS[:7] == (
          "depth", "normal", "lineart", "mask", "id", "color", "raw"))
check("Geometry Preview shading gained color (old values normal / lambert unchanged)",
      CV.SHADINGS == ("normal", "lambert", "color"))

import shutil                                             # noqa: E402
for _d in (tmpd, tmpd2):
    shutil.rmtree(_d, ignore_errors=True)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
