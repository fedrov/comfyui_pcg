"""
The HeightField family: Mask by Feature / Terrace / Thermal Erosion / HeightField
to Mesh.

━━ Criteria
  · Mask: when slope / direction on a plane falls in the soft edge, the value equals the **closed form** of smoothstep;
    a hard edge equals the boolean test per pixel; curvature modes classify ridges / gullies correctly; with an explicit reference value tiles agree
  · Terrace: sharpness = 0 is bit-identical; monotonically non-decreasing; level boundaries fixed; only cuts, never fills;
    sharpness -> 1 approaches a pure staircase
  · Thermal erosion: **mass conservation** (in every configuration); terrain gentler than the talus angle is bit-identical; a
    tall column collapses into a cone whose slope = tan(talus angle); the excess decreases monotonically with iterations
  · To mesh: sampling the COP at the uv returns the pixel value **bit-exactly**; face normals +Y; point normals match the
    normals the mesh computes itself; uv handedness matches UV Project (planar, y), and build.grid now
    matches too (noted in pcg49, fixed in pcg56)
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
from comfyui_pcg.geo.cop import terrain as TR            # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg.geo import frommap as FM                # noqa: E402
from comfyui_pcg.geo import ops as OPS                   # noqa: E402
from comfyui_pcg.geo import uvproject as UVP             # noqa: E402
from comfyui_pcg.geo import build as BUILD               # noqa: E402
from comfyui_pcg.geo.core import POINT, VERTEX           # noqa: E402
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


def sstep(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


W, H = 64, 48
TEX = 1.0 / W
J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                   np.arange(H, dtype=np.float64))
X, Y = (J + 0.5) * TEX, (I + 0.5) * TEX
rng = np.random.default_rng(3)


# ═══════════════════════════════════════════════════ 1. Mask by Feature
sec("Mask by Feature")
bumpy = rng.random((H, W)) * 0.05
m = L(TR.mask_by_feature(himg(bumpy), use_slope=False), "mask")
check("no criterion enabled: mask is all 1", bool((m == 1.0).all()))
t30 = math.tan(math.radians(30))
plane30 = -t30 * X                      # downhill towards +u, slope 30°
for lo, hi, f, want in ((20, 90, 0, 1.0), (40, 90, 0, 0.0), (32, 90, 5, None),
                        (0, 27, 5, None)):
    mm = L(TR.mask_by_feature(himg(plane30), slope_min=lo, slope_max=hi,
                              slope_falloff=f), "mask")
    if want is None:
        want = sstep((30 - (lo - f)) / f) if lo > 30 else sstep(
            ((hi + f) - 30) / f)
    check(f"30° slope, slope range [{lo},{hi}] soft edge {f}: value = {want:.4f}",
          float(np.abs(mm - want).max()) < 1e-9, f"{float(mm.mean()):.6f}")
hb = L(TR.mask_by_feature(himg(bumpy), use_slope=False, use_height=True,
                          height_min=0.02, height_max=0.03), "mask")[..., 0]
check("hard height range equals the boolean test per pixel (endpoints included)",
      bool((hb == ((bumpy >= 0.02) & (bumpy <= 0.03))).all()))
check("  height is judged by the **height value**, not multiplied by strength",
      bool((L(TR.mask_by_feature(himg(bumpy), strength=7.0, use_slope=False,
                                 use_height=True, height_min=0.02,
                                 height_max=0.03), "mask")[..., 0]
            == hb).all()))
for dirv, spread, fo, want in ((0, 45, 0, 1.0), (180, 45, 0, 0.0),
                               (60, 45, 30, sstep(1 - (60 - 45) / 30))):
    mm = L(TR.mask_by_feature(himg(plane30), use_slope=False, use_aspect=True,
                              aspect_dir=dirv, aspect_spread=spread,
                              aspect_falloff=fo), "mask")
    check(f"direction: downhill towards 0°, target {dirv}° ±{spread}° soft edge {fo} -> {want:.3f}",
          float(np.abs(mm - want).max()) < 1e-9, f"{float(mm.mean()):.6f}")
check("  flat ground has no direction, counts as 0",
      float(L(TR.mask_by_feature(himg(np.zeros((H, W))), use_slope=False,
                                 use_aspect=True, aspect_spread=180),
              "mask").max()) == 0.0)
ridge = -3.0 * (X - 0.5) ** 2 + 0.2 * Y
valley = 3.0 * (X - 0.5) ** 2 + 0.2 * Y
for surf, name, mode, want in ((ridge, "ridge", "ridges", 1), (valley, "valley",
                                                            "ridges", 0),
                               (valley, "valley", "gullies", 1),
                               (ridge, "ridge", "gullies", 0)):
    mm = L(TR.mask_by_feature(himg(surf), use_slope=False, curvature=mode,
                              curv_falloff=0.1, curv_reference=1.0),
           "mask")[..., 0]
    mid = float(mm[5:-5, W // 2 - 2:W // 2 + 2].mean())
    check(f"curvature {mode} on a {name} -> {want}", abs(mid - want) < 1e-6,
          f"{mid:.4f}")
wav = 0.05 * np.sin(2 * np.pi * 3 * X) * np.cos(2 * np.pi * 2 * Y) + 0.1 * X
kw = dict(use_slope=False, curvature="ridges", curv_blur=0.0,
          curv_reference=40.0)
full = L(TR.mask_by_feature(himg(wav), **kw), "mask")[..., 0]
crop = L(TR.mask_by_feature(himg(wav[:, 16:]), world_size=48 * TEX, **kw),
         "mask")[..., 0]
check("with an explicit Curv Reference tiles agree (bit-identical inside)",
      bool((full[1:-1, 17:-1] == crop[1:-1, 1:-1]).all()))
crop_auto = L(TR.mask_by_feature(himg(wav[:, 16:]), world_size=48 * TEX,
                                 use_slope=False, curvature="ridges",
                                 curv_blur=0.0), "mask")[..., 0]
full_auto = L(TR.mask_by_feature(himg(wav), use_slope=False,
                                 curvature="ridges", curv_blur=0.0),
              "mask")[..., 0]
check("  negative control: with auto normalization (each tile's own 90th percentile) they don't match up",
      float(np.abs(full_auto[1:-1, 17:-1] - crop_auto[1:-1, 1:-1]).max())
      > 1e-4)
a1 = L(TR.mask_by_feature(himg(plane30), slope_min=32, slope_falloff=5),
       "mask")
a2 = L(TR.mask_by_feature(himg(plane30), use_slope=False, use_aspect=True,
                          aspect_dir=60, aspect_spread=45,
                          aspect_falloff=30), "mask")
both = L(TR.mask_by_feature(himg(plane30), slope_min=32, slope_falloff=5,
                            use_aspect=True, aspect_dir=60, aspect_spread=45,
                            aspect_falloff=30), "mask")
check("several criteria multiply (AND)", float(np.abs(both - a1 * a2).max()) < 1e-12)
check("Invert = 1 − mask", float(np.abs(
    L(TR.mask_by_feature(himg(plane30), slope_min=32, slope_falloff=5,
                         invert=True), "mask") - (1 - a1)).max()) < 1e-12)
err("malformed Curvature raises", lambda: TR.mask_by_feature(himg(bumpy),
                                                      curvature="both"),
    "Curvature")


# ═══════════════════════════════════════════════════ 2. Terrace
sec("Terrace")
ramp = np.linspace(-0.3, 1.3, W * H).reshape(H, W)
check("Sharpness = 0 is bit-identical",
      bool((L(TR.terrace(himg(ramp), sharpness=0.0), "C")[..., 0]
            == ramp).all()))
for sh in (0.3, 0.7, 0.95, 1.0):
    tt = L(TR.terrace(himg(ramp), step=0.25, sharpness=sh), "C")[..., 0].ravel()
    check(f"sharpness={sh}: monotonically non-decreasing", bool((np.diff(tt) >= -1e-12).all()))
    check(f"  only cuts, never fills (output ≤ input)", bool((tt <= ramp.ravel() + 1e-12).all()))
bnd = np.array([[-0.25, 0.0, 0.25, 0.5, 0.75, 1.0]])
check("level boundaries offset + k·step fixed (bit-identical)",
      bool((L(TR.terrace(himg(bnd), step=0.25, sharpness=0.8), "C")[..., 0]
            == bnd).all()))
bnd2 = np.array([[0.1, 0.35, 0.6]])
check("  same with an offset (offset 0.1)",
      float(np.abs(L(TR.terrace(himg(bnd2), step=0.25, offset=0.1,
                                sharpness=0.8), "C")[..., 0] - bnd2).max())
      < 1e-12)
t1 = L(TR.terrace(himg(ramp), step=0.25, sharpness=1.0), "C")[..., 0]
fl = np.floor(ramp / 0.25) * 0.25
frac = ramp / 0.25 - np.floor(ramp / 0.25)
check("Sharpness = 1 approaches a pure staircase (the first 99% of each level hugs the tread)",
      float(np.abs(t1 - fl)[frac < 0.99].max()) < 1e-4,
      f"{float(np.abs(t1 - fl)[frac < 0.99].max()):.1e}")
mimg = himg(ramp, mk=(J < 32).astype(float))
tm = L(TR.terrace(mimg, step=0.25, mask_layer="mk"), "C")[..., 0]
tfull = L(TR.terrace(himg(ramp), step=0.25), "C")[..., 0]
check("Mask: unchanged where the mask is 0, terraced where it is 1",
      bool((tm[:, 32:] == ramp[:, 32:]).all())
      and float(np.abs(tm[:, :32] - tfull[:, :32]).max()) < 1e-12)
err("Step ≤ 0 raises", lambda: TR.terrace(himg(ramp), step=0), "Step")
err("Sharpness out of range raises", lambda: TR.terrace(himg(ramp), sharpness=1.5),
    "Sharpness")


# ═══════════════════════════════════════════════════ 3. Thermal Erosion
sec("Thermal Erosion")
gentle = 0.3 * X + 0.1 * np.sin(4 * Y)             # slope far below tan 35°
check("gentler than the talus angle everywhere: bit-identical",
      bool((L(TR.thermal_erode(himg(gentle), talus_angle=35,
                               iterations=30), "C")[..., 0] == gentle).all()))
check("Iterations = 0 / Rate = 0: bit-identical",
      bool((L(TR.thermal_erode(himg(bumpy * 50), iterations=0), "C")[..., 0]
            == bumpy * 50).all())
      and bool((L(TR.thermal_erode(himg(bumpy * 50), rate=0.0), "C")[..., 0]
                == bumpy * 50).all()))
rough = rng.random((H, W)) * 0.3
for tl in (False, True):
    for nb in (8, 4):
        oo = L(TR.thermal_erode(himg(rough), iterations=40, tile=tl,
                                neighbours=nb), "C")[..., 0]
        check(f"mass conservation (tile={tl}, {nb} neighbourhood)",
              abs(float(oo.sum()) - float(rough.sum())) < 1e-9
              * float(rough.sum()), f"diff {abs(oo.sum() - rough.sum()):.1e}")
        check(f"  and it actually moved", float(np.abs(oo - rough).max()) > 1e-3)


def max_excess(h, talus, texel=TEX, tile=False):
    T = math.tan(math.radians(talus))
    p = np.pad(h, 1, mode="wrap" if tile else "edge")
    Hh, Ww = h.shape
    worst = 0.0
    for dx, dy in TR._DIRS8:
        nb = p[1 + dy:1 + dy + Hh, 1 + dx:1 + dx + Ww]
        e = h - nb - T * texel * math.hypot(dx, dy)
        if not tile:
            if dx == 1:
                e[:, -1] = -1
            if dx == -1:
                e[:, 0] = -1
            if dy == 1:
                e[-1, :] = -1
            if dy == -1:
                e[0, :] = -1
        worst = max(worst, float(e.max()))
    return worst


ex = [max_excess(L(TR.thermal_erode(himg(rough), iterations=n), "C")[..., 0],
                 35) for n in (0, 10, 40, 160)]
check("excess over the talus angle decreases monotonically with iterations", ex[0] > ex[1] > ex[2] > ex[3],
      " > ".join(f"{v:.4f}" for v in ex))
N = 64
spike = np.zeros((N, N))
spike[N // 2, N // 2] = 60.0
cone = L(TR.thermal_erode(himg(spike), world_size=float(N), talus_angle=35,
                          iterations=3000, rate=0.5), "C")[..., 0]
T35 = math.tan(math.radians(35))
row = cone[N // 2]
nz = np.nonzero(row > 1e-6)[0]
steps = -np.diff(row[N // 2:nz.max() + 1])
check("tall column collapses into a cone: mass conserved", abs(cone.sum() - 60.0) < 1e-9)
check("  the cone has converged: every neighbour pair exceeds the talus angle by < 1e-3",
      max_excess(cone, 35, 1.0) < 1e-3, f"{max_excess(cone, 35, 1.0):.1e}")
check("  cone slope = tan(talus angle) (drops ≈ 0.700 per pixel along the axis)",
      float(np.abs(steps[:-2] - T35).max()) < 0.02,
      f"{np.round(steps[:6], 3).tolist()}")
kk = np.arange(1, 20)
c0 = N // 2
# The first version compared with cone[::-1, ::-1], which flips about 31.5, not about the apex at 32 -- the test itself was wrong
check("  the cone is symmetric: transpose and left/right, up/down reflections about the apex are all **bit-identical**",
      bool((cone == cone.T).all())
      and bool((cone[c0, c0 + kk] == cone[c0, c0 - kk]).all())
      and bool((cone[c0 + kk, c0] == cone[c0 - kk, c0]).all()))
hd = himg(rough * 3, hard=np.ones((H, W)))
check("Hardness = 1 (bedrock): nothing moves",
      bool((L(TR.thermal_erode(hd, iterations=20, hardness_layer="hard"),
              "C")[..., 0] == rough * 3).all()))
hh2 = himg(rough * 3, hard=(J < 32).astype(float))
o2 = TR.thermal_erode(hh2, iterations=20, hardness_layer="hard")
check("  half bedrock: the bedrock half only gets material **deposited** (never carried away)",
      bool((L(o2, "C")[..., 0][:, :31] >= rough[:, :31] * 3 - 1e-12).all()))
db = TR.thermal_erode(himg(rough * 3), iterations=40)
dd = L(db, "debris")[..., 0]
chg = L(db, "C")[..., 0] - rough * 3
check("debris = net deposition (≥ 0, exactly the positive part of the change)",
      float(dd.min()) >= 0 and float(np.abs(dd - np.maximum(chg, 0)).max())
      < 1e-12)
a_ = L(TR.thermal_erode(himg(rough), iterations=30), "C")[..., 0]
b_ = L(TR.thermal_erode(himg(rough * 4), world_size=4.0, iterations=30),
       "C")[..., 0]
check("scale invariant: height and World Size both ×4, output exactly ×4",
      float(np.abs(b_ - 4 * a_).max()) < 1e-9)
err("Rate > 1 raises (would oscillate)", lambda: TR.thermal_erode(himg(rough),
                                                           rate=1.5), "Rate")
err("Talus ≥ 90 raises", lambda: TR.thermal_erode(himg(rough),
                                                talus_angle=90), "Talus")
err("malformed Neighbours raises", lambda: TR.thermal_erode(himg(rough),
                                                    neighbours=6),
    "Neighbours")


# ═══════════════════════════════════════════════════ 4. HeightField to Mesh
sec("HeightField to Mesh")
src = himg(bumpy * 10, erosion=rng.random((H, W)) * 2 - 1,
           C3=rng.random((H, W, 3)))
src = CopImage(W, H, {"C": np.asarray(src.need("C")),
                      "erosion": np.asarray(src.need("erosion")),
                      "col": rng.random((H, W, 3))})
g = TR.to_mesh(src, strength=0.5, attribs="erosion Cd=col")
P = np.asarray(g.get(POINT, "P"), np.float64)
check("point count = pixel count, prim count = (W−1)(H−1)",
      g.npoints == W * H and g.nprims == (W - 1) * (H - 1))
uv = np.asarray(g.get(POINT, "uv"), np.float64)
samp = np.asarray(FM.sample_layer(src, uv.astype(np.float32), "C"),
                  np.float64).reshape(-1)
check("sampling the COP at each point's uv returns that pixel's value bit-exactly",
      float(np.abs(samp - bumpy.ravel() * 10).max()) < 1e-6,
      f"{float(np.abs(samp - bumpy.ravel() * 10).max()):.1e}(float32 uv)")
# Attributes are always stored as (N, C) -- single channel is (N, 1), not (N,). The first version compared against (N,) directly,
# which broadcast into an N×N matrix
check("  P.y = height value × strength, height attribute = height value",
      float(np.abs(P[:, 1] - bumpy.ravel() * 5).max()) < 1e-5
      and float(np.abs(np.asarray(g.get(POINT, "height")).reshape(-1)
                       - bumpy.ravel() * 10).max()) < 1e-5)
check("  centered, width = World Size (pixel centers are (W−1)·texel apart)",
      abs(P[:, 0].min() + P[:, 0].max()) < 1e-6
      and abs(P[:, 0].max() - P[:, 0].min() - (W - 1) * TEX) < 1e-6)
first, last = P[0], P[(H - 1) * W]
check("v towards −Z: the top row of the image (row H−1) is on the −Z side", last[2] < first[2])
mesh_n = np.asarray(OPS.compute_normals(TR.to_mesh(himg(np.zeros((H, W))),
                                                   normals=False),
                                        "point").get(POINT, "N"), np.float64)
check("flat ground: normals the mesh computes itself are all +Y (winding correct)",
      float(np.abs(mesh_n - [0, 1, 0]).max()) < 1e-6)
smooth = 0.05 * np.sin(6 * X) * np.cos(5 * Y)
gm = TR.to_mesh(himg(smooth))
Ncop = np.asarray(gm.get(POINT, "N"), np.float64).reshape(H, W, 3)
Nmesh = np.asarray(OPS.compute_normals(TR.to_mesh(himg(smooth),
                                                  normals=False),
                                       "point").get(POINT, "N"),
                   np.float64).reshape(H, W, 3)
e_n = float(np.abs(Ncop - Nmesh)[2:-2, 2:-2].max())
check("point normals (from the height gradient) match the mesh's own averaged ones (interior)", e_n < 5e-3,
      f"{e_n:.1e}")
cd = np.asarray(g.get(POINT, "Cd"), np.float64)
check("Attribs: Cd=col renamed and carried over (3 channels), erosion keeps its name (1 channel)",
      cd.shape == (W * H, 3)
      and float(np.abs(cd - L(src, "col").reshape(-1, 3)).max()) < 1e-6
      and np.asarray(g.get(POINT, "erosion")).shape == (W * H, 1))
g4 = TR.to_mesh(himg(bumpy), step=4)
check("Step = 4: point values are exactly those pixels' values (no interpolation)",
      g4.npoints == (H // 4) * (W // 4)
      and float(np.abs(np.asarray(g4.get(POINT, "height"),
                                  np.float64).reshape(-1)
                       - bumpy[::4, ::4].ravel()).max()) < 1e-7)


def signed(uv_pts, faces):
    a, b, c = uv_pts[faces[:, 0]], uv_pts[faces[:, 1]], uv_pts[faces[:, 2]]
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                  - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))


def quads(geo):
    return np.asarray(geo.vertex_point).reshape(-1, 4)


try:
    fq = quads(gm)
    s_ours = float(np.sign(signed(uv, fq[: (W - 1) * (H - 1)]).mean()))
    pj = UVP.project(TR.to_mesh(himg(smooth)), "planar", "y", cls=VERTEX,
                     name="uvp")
    uvp_v = np.asarray(pj.get(VERTEX, "uvp"), np.float64)
    tri = uvp_v.reshape(-1, 4, 2)
    s_proj = float(np.sign((0.5 * ((tri[:, 1, 0] - tri[:, 0, 0])
                                   * (tri[:, 2, 1] - tri[:, 0, 1])
                                   - (tri[:, 1, 1] - tri[:, 0, 1])
                                   * (tri[:, 2, 0] - tri[:, 0, 0]))).mean()))
    gg = BUILD.grid(1, 1, 8, 8)
    s_grid = float(np.sign(signed(np.asarray(gg.get(POINT, "uv"),
                                             np.float64), quads(gg)).mean()))
    check("uv handedness matches UV Project (planar, y)", s_ours == s_proj,
          f"ours {s_ours:+.0f}, uv project {s_proj:+.0f}")
    check("  build.grid's uv handedness now matches too (noted in pcg49, fixed in pcg56)",
          s_grid == s_proj, f"grid {s_grid:+.0f}")
except Exception as ex:
    check("uv handedness comparison", False, f"{type(ex).__name__}: {ex}")
err("Step too large (less than 2×2 left) raises", lambda: TR.to_mesh(himg(bumpy), step=64),
    "Step")
err("malformed Attribs (empty dst) raises", lambda: TR.to_mesh(himg(bumpy),
                                                     attribs="=C"), "attribute spec")


# ═══════════════════════════════════════════════════ 5. Backend / nodes / timing
sec("backend / nodes / timing")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    b32 = CopImage(W, H, {"C": (rough * 0.6).astype(np.float32)[:, :, None]})
    tb_ = b32.to_device("cpu")
    for nm, fn, lay in (
            ("mask(slope+aspect)", lambda i: TR.mask_by_feature(
                i, use_aspect=True), "mask"),
            ("mask(curvature)", lambda i: TR.mask_by_feature(
                i, use_slope=False, curvature="ridges"), "mask"),
            ("terrace", lambda i: TR.terrace(i, step=0.1), "C"),
            ("thermal", lambda i: TR.thermal_erode(i, iterations=20), "C")):
        try:
            gg_, cc_ = fn(tb_), fn(b32)
            d_ = float(np.abs(L(gg_, lay) - L(cc_, lay)).max())
            check(f"[torch] {nm}: matches, and still on torch",
                  d_ < 1e-4 and gg_.backend.is_torch, f"{d_:.1e}")
        except Exception as ex:
            check(f"[torch] {nm}", False, f"{type(ex).__name__}: {ex}")
names = ["MaskByFeature", "Terrace", "ThermalErosion", "HeightfieldToMesh"]
check("all four nodes registered, all under PCG/cop",
      all(MAP[f"PCG_COP{n}"].CATEGORY == "PCG/cop" for n in names))
r = MAP["PCG_COPHeightfieldToMesh"]().run(himg(bumpy), "C", 1.0, 1.0, 2,
                                          True, True, "")
r = r["result"] if isinstance(r, dict) else r
check("HeightField to Mesh node outputs GEOMETRY", r[0].npoints > 0)
big = CopImage(1024, 1024, {"C": (np.random.default_rng(1).random(
    (1024, 1024)) * 0.3).astype(np.float32)[:, :, None]})
t0 = time.time()
TR.thermal_erode(big, iterations=20)
dt = time.time() - t0
check(f"Thermal 1024² × 20 iterations {dt:.2f} s (limit 60 s)", dt < 60)
t0 = time.time()
TR.mask_by_feature(big, curvature="ridges", use_aspect=True)
dt = time.time() - t0
check(f"Mask by Feature 1024² (slope + direction + curvature)  {dt:.2f} s (limit 20 s)",
      dt < 20)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
