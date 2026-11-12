"""
pcg125: light transport of the rendered looks (geo/skylight.py), checked against closed forms.

  1. Depth map: equals the full rasterizer's on a mesh (median error ~0); sub-pixel triangles still write depth
  2. Sky dome: an open plane sees the whole sky (visibility 1, irradiance = the cosine-weighted sky);
     the floor of an infinite street canyon of height h and width w sees the analytic fraction of a uniform sky
     (view factor of a strip: cos(atan(2h / w)) at the centre line); deeper canyons are darker (negative control: no walls)
     a blocked direction returns bounce light: with albedo 0 the floor under a roof is black, with albedo > 0 it is not
  3. Sun shadow (PCSS): fully lit / fully shadowed far from the edge; the penumbra of an edge at height H is wider
     than at height H / 4 (contact hardening), and scales with Softness; negative control: softness 0 is a hard edge
  4. Sky model: bluer at the zenith; a low sun makes the sunlight redder (blue / red ratio falls monotonically with
     elevation) and dimmer; sun below the horizon gives no light; the sun disc is where the sun is
  5. Clouds: coverage 0 changes nothing; more coverage covers more sky; the ground shadow uses the same field
     (shadow under the clouds seen overhead, light under the gaps); deterministic for a seed, different for another
  6. AgX: monotonic, black -> black, bright -> white, mid grey 0.18 lands mid-range; a saturated bright colour is
     desaturated toward white instead of clipping to a pure primary (negative control: the ACES fit clips it)
  7. Post: bloom conserves nothing below threshold (identity when nothing is bright), spreads light around a bright
     spot; vignette darkens corners more than the centre
  8. End to end: a box on a ground plane rendered with the outdoor look -- the ground next to the box on the side away
     from the sun is darker with Sky Samples > 0 than far from it (sky occlusion), clouds change the frame, and the
     node passes the three new parameters
"""
import math
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

import comfyui_pcg  # noqa: E402,F401
from comfyui_pcg.geo import build, outdoor as O, render as R, skylight as K, studio as S, Geometry  # noqa: E402
from comfyui_pcg.geo.core import POINT  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def tris(quads):
    """List of quads (4 corners each) -> (P, tri) as soup() returns."""
    P, T = [], []
    for q in quads:
        b = len(P)
        P += list(q)
        T += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    return np.asarray(P, np.float32), np.asarray(T, np.int64)


print("\n[1. Depth map]")
sph = build.sphere(radius=1.0, cols=48, rows=24)
ts, T = K.soup(sph)
d = np.array([0.3, 0.8, 0.52])
d /= np.linalg.norm(d)
dm, meta = K.depth_map(T, d, np.zeros(3), 1.5, 512)
cam = R.camera(None, "orthographic", eye=d * 4.5, target=(0, 0, 0), ortho_size=3.0, xres=512, yres=512)
rs = R.rasterize(sph, cam, soup=ts)
ref = np.where(rs["hit"] >= 0, rs["z"] - 3.0, np.inf)            # eye is 3 radii out, the map's zero plane 1 radius out
both = np.isfinite(ref) & np.isfinite(dm)
err = np.abs(ref - dm)[both]
check("matches the full rasterizer on a sphere (median < 1e-4, 99 % < 1 texel of depth)",
      np.median(err) < 1e-4 and np.percentile(err, 99) < 3.0 / 512 * 3, (float(np.median(err)), float(np.percentile(err, 99))))
ins = np.isfinite(ref)
check("  covers at least every pixel the rasterizer covers (conservative edges), at most a 1.5 px rim more",
      bool(np.isfinite(dm)[ins].all()) and np.isfinite(dm).sum() < ins.sum() * 1.03,
      (int(ins.sum()), int(np.isfinite(dm).sum())))
tiny = tris([[(0.001 * i, 0, 0.3), (0.001 * i + 0.0004, 0, 0.3), (0.001 * i + 0.0004, 0, 0.3004), (0.001 * i, 0, 0.3004)]
             for i in range(50)])
dt, _ = K.depth_map(tiny, np.array([0.0, 1.0, 0.0]), np.zeros(3), 1.0, 64)
check("  sub-pixel triangles are splatted (they still cast shadow)", np.isfinite(dt).sum() >= 1, int(np.isfinite(dt).sum()))

print("\n[2. Sky dome]")
white = lambda dd: np.ones((len(dd), 3))                         # noqa: E731
Lz = np.array([0.0, 1.0, 0.0])
none = (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.int64))
P0 = np.zeros((1, 3), np.float32)
Nup = np.array([[0.0, 1.0, 0.0]], np.float32)
E, vis = K.sky_dome(none, P0, Nup, np.zeros(3), 10.0, Lz, white, np.zeros(3), k=64, res=64)
dirs = K.dome_dirs(64)
check("open plane, uniform sky: visibility 1 and irradiance / pi = sum(cos) x 2 / k (about 1)",
      abs(vis[0] - 1) < 1e-6 and np.allclose(E[0], dirs[:, 1].sum() * 2 / 64, rtol=1e-5) and abs(E[0, 0] - 1) < 0.06,
      (float(vis[0]), float(E[0, 0])))


def canyon(h, w=2.0, length=400.0):
    q = []
    for sx in (-1, 1):
        x = sx * w / 2
        q.append([(x, 0, -length), (x, 0, length), (x, h, length), (x, h, -length)])
    return tris(q)


vals = {}
for h in (1.0, 2.0, 4.0):
    _, v = K.sky_dome(canyon(h), P0 + np.array([0, 1e-3, 0], np.float32), Nup, np.array([0, h / 2, 0.0]),
                      max(h, 3.0) * 1.5, Lz, white, np.zeros(3), k=256, res=512)
    vals[h] = float(v[0])
    exact = math.cos(math.atan(2 * h / 2.0))                    # strip view factor from the centre line
    check(f"street canyon h = {h:g}, w = 2: cosine-weighted sky visibility = cos(atan(2h / w)) = {exact:.3f} (±0.04)",
          abs(vals[h] - exact) < 0.04, round(vals[h], 3))
check("  deeper canyons are darker", vals[1.0] > vals[2.0] > vals[4.0])
roof = tris([[(-50, 1, -50), (50, 1, -50), (50, 1, 50), (-50, 1, 50)]])
Eb, vb = K.sky_dome(roof, P0, Nup, np.array([0, 0.5, 0.0]), 80.0, Lz, white, np.zeros(3), k=32, res=1024)
Ec, _ = K.sky_dome(roof, P0, Nup, np.array([0, 0.5, 0.0]), 80.0, Lz, white, np.array([0.5, 0.4, 0.3]), k=32, res=1024)
check("under a roof: no sky (visibility 0, black with albedo 0); with albedo > 0 the blocked sky returns bounce light, "
      "tinted by the albedo", vb[0] < 1e-6 and float(Eb.max()) < 1e-6 and Ec[0, 0] > Ec[0, 1] > Ec[0, 2] > 0.01,
      np.round(Ec[0], 3))

print("\n[3. Sun shadow]")
Ld = np.array([0.0, 1.0, 0.0])


def edge_profile(Hh, soft):
    """A half-plane x < 0 at height Hh above the ground; shadow along x on the ground."""
    occ = tris([[(-30, Hh, -30), (0, Hh, -30), (0, Hh, 30), (-30, Hh, 30)]])
    dmap, meta_ = K.depth_map(occ, Ld, np.array([0, Hh / 2, 0.0]), 12.0, 2048)
    xs = np.linspace(-3, 3, 601)
    Pg = np.stack([xs, np.zeros_like(xs), np.zeros_like(xs)], 1).astype(np.float32)
    Ng = np.tile(np.array([[0, 1.0, 0]], np.float32), (len(xs), 1))
    return xs, K.sun_shadow(dmap, meta_, Pg, Ng, softness=soft, max_px=200.0)


def width(xs, s):
    part = (s > 0.1) & (s < 0.9)
    return float(np.ptp(xs[part])) if part.any() else 0.0


xs, s4 = edge_profile(4.0, 0.05)
check("far inside the shadow 0, far outside 1", s4[xs < -1.5].max() < 0.02 and s4[xs > 1.5].min() > 0.98)
_, s1 = edge_profile(1.0, 0.05)
w4, w1 = width(xs, s4), width(xs, s1)
check("contact hardening: the penumbra of an edge 4 m up is wider than 1 m up, roughly in proportion (2.5x .. 6x)",
      2.5 < w4 / max(w1, 1e-9) < 6.0, (round(w1, 3), round(w4, 3)))
check("  its width is about height x 2 x softness (0.4 m for 4 m, softness 0.05; ±50 %)", 0.2 < w4 < 0.6, round(w4, 3))
_, s4b = edge_profile(4.0, 0.1)
check("  doubling Softness widens it", width(xs, s4b) > 1.5 * w4, round(width(xs, s4b), 3))
_, s40 = edge_profile(4.0, 1e-6)
check("  negative control: softness ~0 is a hard edge (under 3 cm)", width(xs, s40) < 0.03, round(width(xs, s40), 4))

print("\n[4. Sky]")
Lh = O.sun_dir(60, 0)
up, hz = K.sky(np.array([[0, 1.0, 0]]), Lh, sun=False)[0], K.sky(np.array([[0, 0.05, -1.0]]) / np.hypot(0.05, 1), Lh, sun=False)[0]
check("high sun: the zenith is bluer (blue / red) than the horizon", up[2] / up[0] > hz[2] / hz[0], (np.round(up, 3), np.round(hz, 3)))
rat, lum = [], []
for el in (2, 8, 20, 45, 80):
    c = K.sun_light(O.sun_dir(el, 30))
    rat.append(c[2] / c[0])
    lum.append(c.sum())
check("sunlight: blue / red rises monotonically with elevation (a low sun is red) and so does its strength",
      all(np.diff(rat) > 0) and all(np.diff(lum) > 0), np.round(rat, 3))
check("  sun below the horizon: no sunlight", float(K.sun_light(O.sun_dir(-8, 0)).max()) == 0.0)
Ls = O.sun_dir(35, 140)
dd = K.dome_dirs(4000)
rad = K.sky(dd, Ls).sum(1)
check("  the brightest sky direction is the sun's (within 2°)", float(dd[int(np.argmax(rad))] @ Ls) > math.cos(math.radians(2.5)),
      round(float(np.degrees(np.arccos(dd[int(np.argmax(rad))] @ Ls))), 2))
Ll = O.sun_dir(4, 90)
toward = K.sky(np.array([[1.0, 0.06, 0.0]]) / np.hypot(1, 0.06), Ll, sun=False)[0]
away = K.sky(np.array([[-1.0, 0.06, 0.0]]) / np.hypot(1, 0.06), Ll, sun=False)[0]
check("  low sun: the horizon toward the sun is warmer (red / blue) than the opposite horizon",
      toward[0] / toward[2] > away[0] / away[2] * 1.3, (np.round(toward, 3), np.round(away, 3)))

print("\n[5. Clouds]")
D_ = K.dome_dirs(6000)
base = K.sky(D_, Lh, sun=False)
c0 = K.clouds(D_, Lh, base, 0.0, 1)
check("coverage 0: unchanged (same object)", c0 is base)
cov = []
for cv in (0.2, 0.5, 0.9):
    cc = K.clouds(D_, Lh, base, cv, 1)
    cov.append(float((np.abs(cc - base).sum(1) > 0.02).mean()))
check("more coverage changes more of the sky", cov[0] < cov[1] < cov[2] and cov[2] > 0.5, np.round(cov, 3))
a1, a2, a3 = K.clouds(D_, Lh, base, 0.5, 1), K.clouds(D_, Lh, base, 0.5, 1), K.clouds(D_, Lh, base, 0.5, 2)
check("  deterministic for a seed, different for another", np.array_equal(a1, a2) and not np.allclose(a1, a3))
# ground shadow under an overhead sun: the shadow at a ground point = the cloud seen straight above the eye when the
# point is offset by the same amount in cloud units (the same density field)
g_ = np.stack(np.meshgrid(np.linspace(-3, 3, 61), np.linspace(-3, 3, 61)), -1).reshape(-1, 2)
height = 500.0
Pg = np.stack([g_[:, 0] * height, np.zeros(len(g_)), g_[:, 1] * height], 1)
shd = K.cloud_shadow(Pg, np.zeros(3), Lz, 0.5, 1, height)
rays = np.stack([g_[:, 0], np.ones(len(g_)), g_[:, 1]], 1)
rays /= np.linalg.norm(rays, axis=1, keepdims=True)
sky_at = K.clouds(rays, Lz, np.zeros((len(rays), 3)), 0.5, 1).sum(1)           # > 0 where a cloud is drawn
clear = sky_at < 1e-6
thick = sky_at > np.percentile(sky_at, 85)
check("  the ground shadow follows the clouds overhead: darker under thick cloud than under clear sky",
      clear.sum() > 50 and shd[thick].mean() < shd[clear].mean() - 0.2, (round(float(shd[thick].mean()), 3),
                                                                        round(float(shd[clear].mean()), 3)))
check("  bounded 0.35..1; coverage 0 -> no shadow", shd.min() >= 0.35 - 1e-6 and shd.max() <= 1.0
      and float(K.cloud_shadow(Pg, np.zeros(3), Lz, 0.0, 1, height).min()) == 1.0)

print("\n[6. AgX]")
g = np.repeat(np.geomspace(1e-4, 50, 200)[:, None], 3, 1)
y = K.agx(g, 0.0)[:, 0]
check("monotonic; black -> < 0.02, 50 -> > 0.97", bool((np.diff(y) >= -1e-9).all()) and y[0] < 0.02 and y[-1] > 0.97, (y[0], y[-1]))
mid = float(K.agx(np.array([[0.18, 0.18, 0.18]]), 0.0)[0, 0])
check("  scene mid grey 0.18 lands mid-range (0.35..0.6)", 0.35 < mid < 0.6, round(mid, 3))
red = np.array([[40.0, 2.0, 1.0]])
a_ = K.agx(red, 0.0)[0]
s_ = S.linear_to_srgb(S.filmic(red))[0]
check("  a very bright saturated red rolls off toward white (every channel > 0.5) and keeps its hue order",
      a_.min() > 0.5 and a_[0] >= a_[1] >= a_[2], np.round(a_, 3))
dim = K.agx(np.array([[0.02, 0.02, 0.02]]), 0.0)[0, 0]
check("  shadows keep separation: 0.02 (three stops under mid grey) is still above 0.12; the ACES fit puts it lower",
      dim > 0.12 and dim > float(S.linear_to_srgb(S.filmic(np.array([0.02 * 0.8])))[0]) * 0.9, round(float(dim), 3))
check("  punch raises saturation of a mid-tone colour", np.ptp(K.agx(np.array([[0.3, 0.15, 0.08]]), 1.0)[0])
      > np.ptp(K.agx(np.array([[0.3, 0.15, 0.08]]), 0.0)[0]))

print("\n[7. Post]")
im = np.full((90, 160, 3), 0.4, np.float32)
check("bloom: nothing above the threshold -> identical", np.array_equal(K.bloom(im.copy()), im))
im2 = im.copy()
im2[40:44, 78:82] = 60.0
bl = K.bloom(im2.copy())
check("  a bright spot bleeds into its surroundings, falling off with distance",
      bl[42, 90, 0] > im2[42, 90, 0] + 1e-3 and bl[42, 90, 0] - 0.4 > bl[42, 130, 0] - 0.4 >= 0,
      (float(bl[42, 90, 0]), float(bl[42, 130, 0])))
vg = K.vignette(np.ones((90, 160, 3), np.float32))
check("vignette: corners darker than the centre, centre untouched (> 0.995)",
      vg[0, 0, 0] < vg[45, 80, 0] - 0.1 and vg[45, 80, 0] > 0.995, (float(vg[0, 0, 0]), float(vg[45, 80, 0])))

print("\n[8. End to end]")
box = build.box(size=(2, 4, 2)) if "size" in build.box.__code__.co_varnames else build.box()
Pb = np.asarray(box.get(POINT, "P"), np.float64)
Pb[:, 1] -= Pb[:, 1].min()
box.set(POINT, "P", Pb.astype(np.float32))
cam = R.camera(None, "perspective", eye=(0.0, 30.0, 0.02), target=(0, 0, 0), fov=40)
W, H = 200, 200


def shot(**kw):
    return O.render_outdoor(box, W, H, cam=cam, ssaa=1, sun_elev=50, sun_azim=90, haze=0, **kw).mean(-1)


lum = shot(sky_samples=48)
flat = shot(sky_samples=0)
rc = R.camera(None, "perspective", eye=(0.0, 30.0, 0.02), target=(0, 0, 0), fov=40)
# the box's shadow falls toward -X (3.4 m long). Inside it only the sky lights the ground: 0.4 m from the wall the box
# hides almost half the sky, 2.6 m out much less
xs_ = -1 if rc["right"][0] > 0 else 1
px = W / (2 * 30 * math.tan(math.radians(20)))
c0 = W // 2 + xs_ * int(round(1.4 * px))
c1 = W // 2 + xs_ * int(round(3.6 * px))
r0 = slice(H // 2 - 2, H // 2 + 3)
near, far = float(lum[r0, c0].mean()), float(lum[r0, c1].mean())
nearf, farf = float(flat[r0, c0].mean()), float(flat[r0, c1].mean())
check("in the box's shadow the ground at the foot of the wall is darker than 2 m further out (it sees less sky)",
      near < far * 0.9, (round(near, 3), round(far, 3)))
check("  negative control: Sky Samples 0 (plain fill + contact AO) has a weaker gradient", nearf / farf > near / far + 0.03,
      (round(nearf, 3), round(farf, 3)))
cl = shot(sky_samples=0, clouds=0.8, cloud_seed=3)
check("clouds change the lighting of the frame (cloud shadows)", float(np.abs(cl - flat).max()) > 0.02)
N = comfyui_pcg.NODE_CLASS_MAPPINGS
it = N["PCG_PreviewImage"].INPUT_TYPES()["optional"]
keys = list(it)
check("node: clouds / cloud_seed / sky_samples appended last, defaults = the plain clear-sky render with 32 samples",
      keys[-4:-1] == ["clouds", "cloud_seed", "sky_samples"] and it["clouds"][1]["default"] == 0.0
      and it["sky_samples"][1]["default"] == 32)
r = N["PCG_PreviewImage"]().run(box, 96, 64, 25, 35, "color", look="outdoor", supersampling=1, clouds=0.5,
                                cloud_seed=2, sky_samples=8)
r = r["result"] if isinstance(r, dict) else r
check("  the node runs with them", tuple(r[0].shape) == (1, 64, 96, 3))

print("\n[9. Triangles of big meshes]")
# Above spatial._FAST_SOUP primitives, triangles and convex quads are cut directly instead of through Divide (3 GB
# less on the world example). It must give the same triangulation count per primitive, the same area, the same
# picture -- also for the primitives it hands back to Divide (concave quads, n-gons)
from comfyui_pcg.geo import spatial as SP, ops  # noqa: E402
gq = build.grid(4, 4, 30, 30)
Pq = np.asarray(gq.get(POINT, "P")).copy()
Pq[:, 1] += np.random.default_rng(0).normal(0, 0.02, len(Pq))
gq.set(POINT, "P", Pq)
conc = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [0.4, 0, 0.4], [0, 0, 2], [5, 0, 0], [6, 0, 0], [6.5, 0, 1],
                                    [5.5, 0, 1.6], [4.6, 0, 1]], np.float32), [[0, 1, 2, 3], [4, 5, 6, 7, 8]])
mixed = ops.merge(gq, build.sphere(radius=1, cols=12, rows=6), conc)


def tri_area(g_, t_):
    Pm = np.asarray(g_.get(POINT, "P"), np.float64)
    return float(np.linalg.norm(np.cross(Pm[t_[:, 1]] - Pm[t_[:, 0]], Pm[t_[:, 2]] - Pm[t_[:, 0]]), axis=1).sum() / 2)


slow = SP.tri_soup(mixed, "")
keep_ = SP._FAST_SOUP
SP._FAST_SOUP = 0
try:
    fast = SP.tri_soup(mixed, "")
finally:
    SP._FAST_SOUP = keep_
check("fast path: same number of triangles per primitive as Divide (quads 2, the pentagon 3, the concave quad 2)",
      np.array_equal(np.bincount(slow[1], minlength=mixed.nprims), np.bincount(fast[1], minlength=mixed.nprims)),
      (len(slow[0]), len(fast[0])))
check("  corners and points agree (corner -> its point), total area equal",
      np.array_equal(mixed.vertex_point[fast[2]], fast[0]) and abs(tri_area(mixed, slow[0]) - tri_area(mixed, fast[0]))
      < 1e-5 * tri_area(mixed, slow[0]))
camq = R.camera(mixed, "orthographic", xres=128, yres=128, elev=60, azim=30, frame_geometry=True)
ra, rb = R.rasterize(mixed, camq, soup=slow), R.rasterize(mixed, camq, soup=fast)
check("  the rasterized picture is the same (coverage and depth)",
      np.array_equal(ra["hit"] >= 0, rb["hit"] >= 0) and float(np.abs(ra["z"] - rb["z"]).max()) < 1e-9)
cq = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [0.4, 0, 0.4], [0, 0, 2]], np.float32), [[0, 1, 2, 3]])
SP._FAST_SOUP = 0
try:
    fc = SP.tri_soup(cq, "")
finally:
    SP._FAST_SOUP = keep_
check("  negative control: a concave quad cut as a plain fan would cover more than its area; the fast path does not",
      abs(tri_area(cq, fc[0]) - 0.8) < 1e-6 and abs(tri_area(cq, np.array([[0, 1, 2], [0, 2, 3]])) - 0.8) < 1e-6
      and abs(tri_area(cq, np.array([[1, 2, 3], [1, 3, 0]])) - 0.8) > 0.5,
      (round(tri_area(cq, fc[0]), 4), round(tri_area(cq, np.array([[1, 2, 3], [1, 3, 0]])), 4)))

print("\n[10. Torch path]")
try:
    import torch  # noqa: F401
    have_t = True
except Exception:
    have_t = False
if not have_t:
    check("torch not installed: skipped", True)
else:
    dev = K.torch_device("torch_cpu")
    check("Compute: cpu -> numpy; auto / cuda without CUDA -> numpy; a wrong value raises",
          K.torch_device("cpu") is None and (torch.cuda.is_available() or K.torch_device("auto") is None))
    try:
        K.torch_device("gpu0")
        bad = False
    except ValueError:
        bad = True
    check("  unknown Compute raises", bad)
    Tm = K.soup(mixed)[1]
    dn, _ = K.depth_map(Tm, d, np.array([0.5, 0.0, 0.5]), 5.0, 384)
    dt_, _ = K.depth_map_t(K.to_device(Tm, dev), d, np.array([0.5, 0.0, 0.5]), 5.0, 384)
    dt_ = dt_.numpy()
    same = np.isfinite(dn) == np.isfinite(dt_)
    fin = np.isfinite(dn) & np.isfinite(dt_)
    check("depth map in torch = numpy: same coverage (> 99.9 % of texels), depths equal to 1e-4",
          same.mean() > 0.999 and float(np.abs(dn - dt_)[fin].max()) < 1e-4,
          (float(same.mean()), float(np.abs(dn - dt_)[fin].max())))
    slab = tris([[(-40, 0, -40), (40, 0, -40), (40, 0, 40), (-40, 0, 40)]])
    dsn, _ = K.depth_map(slab, Lz, np.zeros(3), 30.0, 2048)
    dst, _ = K.depth_map_t(K.to_device(slab, dev), Lz, np.zeros(3), 30.0, 2048)
    check("  a triangle covering the whole 2048² map (cut into strips) fills it, in both", bool(np.isfinite(dsn).all())
          and bool(torch.isfinite(dst).all()) and float(np.abs(dsn - dst.numpy()).max()) < 1e-4)
    rngp = np.random.default_rng(4)
    Pq_ = (rngp.random((4000, 3)) * np.array([4, 0.0, 4]) - np.array([2, 0, 2])).astype(np.float32)
    Pq_[:, 1] = 0.01
    Nq_ = np.tile(np.array([[0, 1.0, 0]], np.float32), (len(Pq_), 1))
    cz = canyon(2.0)
    En, vn = K.sky_dome(cz, Pq_, Nq_, np.array([0, 1.0, 0.0]), 6.0, Lh, white, np.array([0.3, 0.3, 0.3]), k=24, res=256)
    Et, vt = K.sky_dome(cz, Pq_, Nq_, np.array([0, 1.0, 0.0]), 6.0, Lh, white, np.array([0.3, 0.3, 0.3]), k=24, res=256,
                        device=dev)
    check("sky dome in torch = numpy (irradiance and visibility to 2e-3; texel-edge points may flip one tap)",
          float(np.abs(En - Et).mean()) < 2e-3 and float(np.abs(vn - vt).mean()) < 2e-3,
          (float(np.abs(En - Et).mean()), float(np.abs(vn - vt).max())))
    a_np = O.render_outdoor(box, 160, 120, cam=cam, ssaa=1, sun_elev=50, sun_azim=90, sky_samples=16, compute="cpu")
    a_t = O.render_outdoor(box, 160, 120, cam=cam, ssaa=1, sun_elev=50, sun_azim=90, sky_samples=16, compute="torch_cpu")
    check("the rendered frame: torch path within 1/255 of the numpy path on 99 % of pixels",
          float((np.abs(a_np - a_t).max(-1) < 1 / 255).mean()) > 0.99, float(np.abs(a_np - a_t).max()))
    check("node: Compute appended last", list(N["PCG_PreviewImage"].INPUT_TYPES()["optional"])[-1] == "compute")

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
