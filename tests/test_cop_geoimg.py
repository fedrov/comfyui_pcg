"""
Completing Copernicus batch F: geometry <-> image / heightfield / visualization / sequence (geoimg.py + hfvis.py
+ the 13 nodes in nodes_cop2.py). With this batch done, todo = 0 in the Copernicus comparison table.

━━ Criteria
  · Layer to Points: points coincide one by one with those of HeightField to Mesh (same coordinate convention),
    height = value x Scale, attributes are the pixel values; scatter never lands where density is 0
  · Points from Blobs: disc centroid = circle center, area = pixel count, radius = √(area/π),
    numbered by descending area, per-blob mean
  · Rasterize Curves: coverage of a straight segment = L·w + π(w/2)^2 (round caps); fill area of a closed square
    = square area; Width Attrib x2 -> line width x2; attributes interpolated linearly along the line
  · GSplats: total α of a single isotropic Gaussian = opacity·2πσ^2 (for small opacity); rotating 90° around Y
    swaps the x and z scales; front ones occlude back ones
  · Bake: high = low translated by d along the normal -> displacement ≡ d, tangent-space normal ≡ (0,0,1);
    tangent-space normal of a sine high mesh = analytic normal; tangents unit and ⟂ N; baked attributes = interpolation; Dilate
    expands outward but mask does not expand
  · Light: planar normal -> Albedo·(Ambient + sin(elev)·I); point light N·L = 1 at the pixel directly below;
    only Ambient left in the shadow behind a wall
  · HF Clip: hard = np.clip; soft knee unchanged bit for bit within [lo + s, hi - s], monotonic, C¹
  · HF Project: a flat slab projected down = slab height / Strength; identity Transform 3D = original height;
    raise by 0.1 = original height + 0.1
  · Strata: Strength 0 is identity; no tilt, no noise, no random hardness = Terrace (per pixel)
  · Visualize: both ends of the color ramp; +u velocity is red; LIC correlation along the flow direction > perpendicular
  · Contact Sheet: frame k lands in row (k // cols), column (k % cols) (first row at the top)
  · Wipe: t = 0 / 1 both ends bit-identical; linear reveals left to right; dissolve's B share ≈ t
  · sequences: reverse twice = unchanged; loop shift by n = unchanged; hold; retime first/last frames bit-identical, middle
    linear; after loop the jump where end meets start is smaller than before
"""
import json
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
from comfyui_pcg.geo.cop import geoimg as GI             # noqa: E402
from comfyui_pcg.geo.cop import hfvis as HV              # noqa: E402
from comfyui_pcg.geo.cop import terrain as TR            # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT         # noqa: E402
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


def polyline(pts, closed=False):
    g = Geometry.from_points(np.asarray(pts, np.float32))
    g.set_topology(np.arange(len(pts), dtype=np.int32),
                   np.array([0, len(pts)], np.int32), np.array([closed]))
    return g


rng = np.random.default_rng(21)
W, H = 48, 32
J, I = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))

# ═══════════════════════════════════════════════════════ image -> points
sec("Layer to Points / Points from Blobs")
hgt = rng.random((H, W, 1))
col = rng.random((H, W, 3))
im = mk(C=col, h=hgt)
g = GI.layer_to_points(im, "pixels", height_layer="h", height_scale=2.0,
                       attribs="C h", world_size=3.0)
mesh = TR.to_mesh(im, "h", 2.0, 3.0, 1, True, False)
check("pixels: points coincide one by one with HeightField to Mesh's points (same coordinate convention)",
      np.allclose(g.get(POINT, "P"), mesh.get(POINT, "P"), atol=1e-6))
check("  attributes are the pixel values (C -> Cd)", np.allclose(g.get(POINT, "Cd"),
                                           col.reshape(-1, 3), atol=1e-6)
      and np.allclose(g.get(POINT, "h")[:, 0], hgt.ravel(), atol=1e-6))
m = np.zeros((H, W, 1)); m[5:9, 10:20] = 1
g2 = GI.layer_to_points(mk(C=col, m=m), "pixels", "m")
check("  filtered by Mask Layer: point count = number of mask pixels", g2.npoints == 40)
g3 = GI.layer_to_points(mk(C=col, m=m), "pixels", stride=4)
check("  Stride 4: 48x32 -> 12x8 points", g3.npoints == 96)
dens = np.zeros((H, W, 1)); dens[:, 24:] = 1
g4 = GI.layer_to_points(mk(d=dens), "scatter", count=300, density_layer="d",
                        attribs="")
uvs = g4.get(POINT, "uv")
check("scatter: scattered by density, no points in the left half where density is 0, enough points",
      g4.npoints == 300 and uvs[:, 0].min() >= 0.5, (g4.npoints,
                                                     uvs[:, 0].min()))

S = 64
Js, Is = np.meshgrid(np.arange(S) + 0.5, np.arange(S) + 0.5)
blob = np.zeros((S, S, 1))
blob[np.hypot(Js - 20, Is - 40) < 9] = 1
blob[np.hypot(Js - 48, Is - 16) < 5] = 1
blob[2, 2] = 1
val = np.stack([Js / S, Is / S], -1)
gb, nb = GI.points_from_blobs(mk(mask=blob, v=val), value_layer="v",
                              min_area=2, plane="xy", world_size=2.0)
area = np.ravel(gb.get(POINT, "area"))
check("blobs: min_area 2 filters out single pixels, 2 blobs left, in descending area order",
      nb == 2 and area[0] > area[1] and
      list(np.ravel(gb.get(POINT, "blob_id"))) == [1, 2])
P = gb.get(POINT, "P")
check("  centroid = circle center (xy plane, world 2: x = (u - ½)·2)",
      np.allclose(P[0, :2], [(20 / S - 0.5) * 2, (40 / S - 0.5) * 2],
                  atol=1e-6), P[0])
check("  area = pixel count; radius = √(area·pixel area/π)",
      area[0] == blob[np.hypot(Js - 20, Is - 40) < 9].sum() and
      np.isclose(np.ravel(gb.get(POINT, "radius"))[0], math.sqrt(
          area[0] * (2 / S) ** 2 / math.pi), rtol=1e-6))
check("  per-blob mean (v layer) = uv of the circle center", np.allclose(gb.get(POINT, "v")[0],
                                             [20 / S, 40 / S], atol=1e-6))

# ═══════════════════════════════════════════════════════ curves / Gaussian splats
sec("Rasterize Curves / GSplats")
Wc = 128
# xy plane, world 1: x ∈ [-½, ½] maps to u ∈ [0, 1]
ln = polyline([[-0.3, 0.0, 0.0], [0.3, 0.0, 0.0]])
wv = 4.0
r = L(GI.rasterize_curves(None, ln, wv, plane="xy", xres=Wc, yres=Wc),
      "curves")
Lp = 0.6 * Wc
ana = Lp * wv + math.pi * (wv / 2) ** 2
check("straight segment: coverage = L·w + π(w/2)^2 (round caps, ±2%)", abs(r.sum() / ana - 1)
      < 0.02, r.sum() / ana)
ln.set(POINT, "width", np.array([2.0, 2.0], np.float32))
r2 = L(GI.rasterize_curves(None, ln, wv, "width", plane="xy", xres=Wc,
                           yres=Wc), "curves")
check("  Width Attrib = 2: coverage about x2 (±5%)", abs(r2.sum() / r.sum() - 2)
      < 0.1, r2.sum() / r.sum())
ln.set(POINT, "Cd", np.array([[0, 0, 0], [1, 1, 1]], np.float32))
ra = GI.rasterize_curves(None, ln, wv, attrib="Cd", plane="xy", xres=Wc,
                         yres=Wc)
cd = L(ra, "curves_Cd")
check("  attribute interpolated along the line: midpoint ≈ ½, quarter point ≈ ¼ (direction correct)",
      abs(cd[64, 64, 0] - 0.5) < 0.02 and abs(cd[64, 45, 0] - 0.25) < 0.03,
      (cd[64, 64, 0], cd[64, 45, 0]))
sq = polyline([[-0.25, -0.25, 0], [0.25, -0.25, 0], [0.25, 0.25, 0],
               [-0.25, 0.25, 0]], closed=True)
rf = L(GI.rasterize_curves(None, sq, 0.0, fill=True, plane="xy", xres=Wc,
                           yres=Wc), "curves")
check("closed square fill (line width 0): area = 64^2 (±1 row)",
      abs(rf.sum() - 64 * 64) <= 2 * 64, rf.sum())
cen = L(GI.rasterize_curves(None, sq, 2.0, plane="xy", xres=Wc, yres=Wc),
        "curves")
check("  without fill the middle is empty", cen[64, 64, 0] == 0 and rf[64, 64, 0] == 1)

gs = Geometry.from_points(np.array([[0.0, 0.0, 0.0]], np.float32))
sig = 0.05
gs.set(POINT, "scale", np.array([[sig, sig, sig]], np.float32))
gs.set(POINT, "opacity", np.array([0.05], np.float32))
o, n = GI.rasterize_splats(None, gs, "xz", xres=Wc, yres=Wc)
al = L(o, "C_alpha")[..., 0]
sp = sig * Wc
ana = 0.05 * 2 * math.pi * (sp * sp + 0.09)
check("single Gaussian: total α = opacity·2π(σ^2 + 0.3^2) (small opacity, ±2%)",
      abs(al.sum() / ana - 1) < 0.02, al.sum() / ana)
ga = Geometry.from_points(np.array([[0.0, 0.0, 0.0]], np.float32))
ga.set(POINT, "scale", np.array([[0.12, 0.01, 0.03]], np.float32))
o1, _ = GI.rasterize_splats(None, ga, "xz", xres=Wc, yres=Wc)
q = np.array([[0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)]],
             np.float32)                           # rotated 90° around Y
ga.set(POINT, "orient", q)
o2, _ = GI.rasterize_splats(None, ga, "xz", xres=Wc, yres=Wc)
a1 = L(o1, "C_alpha")[..., 0]
a2 = L(o2, "C_alpha")[..., 0]
check("rotated 90° around Y: the ellipse in the plane rotates 90° (x and z scales swap)",
      np.abs(a1 - a2.T).max() < 1e-6 and a1[:, 64].sum() < a1[64, :].sum())
ga.set(POINT, "orient", np.array([[0.0, math.sin(math.pi / 8), 0.0,
                                   math.cos(math.pi / 8)]], np.float32))
o4, _ = GI.rasterize_splats(None, ga, "xz", xres=Wc, yres=Wc)
a4 = L(o4, "C_alpha")[..., 0]
dg = sum(a4[64 + k, 64 + k] for k in range(-20, 21))
ad = sum(a4[64 + k, 64 - k] for k in range(-20, 21))
check("rotated 45° around +Y: major axis along the +u+v diagonal (xz plane v = -Z, right-handed)", dg > 3 * ad,
      (dg, ad))
# second moments vs analytic covariance: Σ = R·S²·Rᵀ projected onto the (u, -… ) plane, plus a 0.3^2 anti-aliasing floor
gm = Geometry.from_points(np.array([[0.0, 0.0, 0.0]], np.float32))
sx_, sz_ = 0.10, 0.06
th_ = math.radians(30)
gm.set(POINT, "scale", np.array([[sx_, 0.01, sz_]], np.float32))
gm.set(POINT, "orient", np.array([[0, math.sin(th_ / 2), 0,
                                   math.cos(th_ / 2)]], np.float32))
gm.set(POINT, "opacity", np.array([0.01], np.float32))
om, _ = GI.rasterize_splats(None, gm, "xz", cutoff=5, xres=Wc, yres=Wc)
am = L(om, "C_alpha")[..., 0]
Jm, Im = np.meshgrid(np.arange(Wc) - 63.5, np.arange(Wc) - 63.5)
wsum = am.sum()
cxx = (am * Jm * Jm).sum() / wsum
cyy = (am * Im * Im).sum() / wsum
cxy = (am * Jm * Im).sum() / wsum
Ry = np.array([[math.cos(th_), 0, math.sin(th_)], [0, 1, 0],
               [-math.sin(th_), 0, math.cos(th_)]])
Sg = Ry @ np.diag([sx_ ** 2, 1e-4, sz_ ** 2]) @ Ry.T * Wc * Wc
ana_c = np.array([[Sg[0, 0], -Sg[0, 2]], [-Sg[0, 2], Sg[2, 2]]]) + 0.09
check("  anisotropic + rotated 30°: second moments of the image = analytic projected covariance (±3%)",
      np.allclose([cxx, cxy, cyy], [ana_c[0, 0], ana_c[0, 1], ana_c[1, 1]],
                  rtol=0.03), ([cxx, cxy, cyy], ana_c.round(2).tolist()))
g2s = Geometry.from_points(np.array([[0, 0.0, 0], [0, 1.0, 0]], np.float32))
g2s.set(POINT, "Cd", np.array([[1, 0, 0], [0, 0, 1]], np.float32))
g2s.set(POINT, "pscale", np.array([0.1, 0.1], np.float32))
o3, _ = GI.rasterize_splats(None, g2s, "xz", xres=Wc, yres=Wc)
c3 = L(o3, "C")[64, 64]
check("front (larger Y) occludes back: the center is blue", c3[2] > 0.95 and c3[0] < 0.05, c3)

# ═══════════════════════════════════════════════════════ baking
sec("Bake Geometry Textures")
flat = CopImage(16, 16, {"h": np.zeros((16, 16, 1))})
low = TR.to_mesh(flat, "h", 1, 1, 1, True, True)
low.set(POINT, "heat", (low.get(POINT, "P")[:, 0] * 2).astype(np.float32))
d0 = 0.07
high = low.copy()
high.set(POINT, "P", (low.get(POINT, "P") + np.array([0, d0, 0]))
         .astype(np.float32))
o, rep = GI.bake_textures(low, high, 64, 64, attribs="heat", dilate=0)
m = L(o, "mask")[..., 0] > 0.5
# uv rasterization conservatively expands outward by half a texel: the outermost ring of texels lies slightly outside the mesh,
# and a high mesh of the same size cannot catch the rays of that ring -- only texels within the mesh extent are checked
ext = np.abs(low.get(POINT, "P")[:, 0]).max()
Pb = L(o, "P")
inn = m & (np.abs(Pb[..., 0]) <= ext) & (np.abs(Pb[..., 2]) <= ext)
check("high = low translated by d along the normal -> displacement ≡ d (1e-6)",
      np.abs(L(o, "displacement")[..., 0][inn] - d0).max() < 1e-6)
check("  only the ring outside the mesh is missed (matches the miss count in the report)",
      rep["ray_miss"] == int((m & ~inn).sum()), (rep, int((m & ~inn).sum())))
check("  tangent-space normal ≡ (0, 0, 1) (misses are filled with (0,0,1) too)",
      np.allclose(L(o, "normal_ts")[m],
                                             [0, 0, 1], atol=1e-6))
check("  baked attribute = interpolation (heat = 2x)", np.allclose(L(o, "heat")[..., 0][m],
                                                2 * Pb[..., 0][m], atol=1e-6))
T_ = L(o, "tangent")[m]
N_ = L(o, "N")[m]
check("  tangents unit, ⟂ N", np.allclose(np.linalg.norm(T_, axis=1), 1, atol=1e-6)
      and np.abs((T_ * N_).sum(1)).max() < 1e-6)
Jh, Ih = np.meshgrid(np.arange(96) + 0.5, np.arange(96) + 0.5)
amp, per = 0.02, 12.0
hs = (amp * np.sin(Jh / per))[..., None]
hi_ = TR.to_mesh(CopImage(96, 96, {"h": hs}), "h", 1, 1, 1, True, True)
o2, _ = GI.bake_textures(low, hi_, 64, 64, dilate=0)
nt = L(o2, "normal_ts")
m2 = L(o2, "mask")[..., 0] > 0.5
x = L(o2, "P")[..., 0]
jj = (x + 0.5) * 96                                    # pixel coordinates of the high mesh
slope = amp / per * np.cos(jj / per) * 96              # dh/dx (world)
ana_n = np.stack([-slope, np.zeros_like(slope), np.ones_like(slope)], -1)
ana_n /= np.linalg.norm(ana_n, axis=-1, keepdims=True)
check("sine high mesh: tangent-space normal = analytic normal (±0.03, the high mesh is a polyline approximation)",
      np.abs(nt[m2] - ana_n[m2]).max() < 0.03, np.abs(nt[m2] - ana_n[m2])
      .max())
# invariant under rigid rotation: low and high rotated 90° around X together (stood up), tangent-space normals unchanged
from comfyui_pcg.geo.cop.pixel import _euler                  # noqa: E402
Rx = _euler(90, 0, 0)
lowR, hiR = low.copy(), hi_.copy()
lowR.set(POINT, "P", (low.get(POINT, "P") @ Rx.T).astype(np.float32))
hiR.set(POINT, "P", (hi_.get(POINT, "P") @ Rx.T).astype(np.float32))
for gg in (lowR, hiR):
    if gg.get(POINT, "N") is not None:
        gg.set(POINT, "N", (gg.get(POINT, "N") @ Rx.T).astype(np.float32))
oR, _ = GI.bake_textures(lowR, hiR, 64, 64, dilate=0)
check("  whole thing rotated 90° (stood up): tangent-space normals unchanged (1e-5)",
      np.abs(L(oR, "normal_ts")[m2] - nt[m2]).max() < 1e-5,
      np.abs(L(oR, "normal_ts")[m2] - nt[m2]).max())
bump = CopImage(16, 16, {"h": (0.3 * np.exp(-((np.arange(16)[None, :] - 7.5)
                                                ** 2 + (np.arange(16)[:, None]
                                                        - 7.5) ** 2) / 20))
                         [..., None]})
lowc = TR.to_mesh(bump, "h", 1, 1, 1, True, True)
oc, _ = GI.bake_textures(lowc, None, 64, 64, dilate=0)
mc = L(oc, "mask")[..., 0] > 0.5
Tc, Nc = L(oc, "tangent")[mc], L(oc, "N")[mc]
check("  curved low mesh (point normals vary within a triangle): tangents still ⟂ interpolated normal",
      np.abs((Tc * Nc).sum(1)).max() < 1e-5)
o3, _ = GI.bake_textures(low, None, 64, 64, dilate=3)
m3 = L(o3, "mask")[..., 0] > 0.5
check("Dilate expands outward (N exists outside the mask too), the mask itself does not expand",
      np.array_equal(m3, m) and np.linalg.norm(L(o3, "N")[~m3], axis=-1)
      .max() > 0.5)
err("empty low geometry raises", lambda: GI.bake_textures(Geometry(), None), "empty")

# ═══════════════════════════════════════════════════════ lighting / heightfield
sec("Light / HF Clip / HF Project / Strata")
Nf = np.zeros((H, W, 3)); Nf[..., 2] = 1
alb = rng.random((H, W, 3))
li = L(HV.light(mk(N=Nf, A=alb), "N", "A", elevation=30, intensity=0.8,
                ambient=0.1), "lit")
check("planar normal: Albedo·(Ambient + sin(elev)·I)", np.allclose(
    li, alb * (0.1 + 0.5 * 0.8)))
lp = L(HV.light(mk(N=Nf), "N", light_type="point", position="0.5 0.5",
                ambient=0.0), "lit")[..., 0]
check("point light: N·L largest (≈ 1) at the pixel directly below, darker outward", lp.max() > 0.99 and
      lp[0, 0] < lp.max())
lp2 = L(HV.light(mk(N=Nf), "N", light_type="point", position="0.5 0.5",
                 light_height=0.2, ambient=0.0), "lit")[..., 0]
check("  symmetric in pixel distance (on a 48x32 image, 6 pixels across = 6 pixels down)",
      abs(lp2[16, 30] - lp2[22, 24]) < 1e-3 and abs(lp2[16, 18] - lp2[10, 24])
      < 1e-3, (lp2[16, 30], lp2[22, 24]))
wall = np.zeros((H, W, 1)); wall[:, 20:22] = 0.3
from comfyui_pcg.geo.cop import heightmap as HM          # noqa: E402
wi = HM.height_to_normal(mk(h=wall), "h", 1, 1)
ls = L(HV.light(wi, "N", height_layer="h", azimuth=0, elevation=20,
                ambient=0.1, shadows=True), "lit")[..., 0]
check("a wall blocks the light (light from +u): only Ambient left in the shadow left of the wall",
      np.allclose(ls[:, 12:18], 0.1) and ls[:, 30:40].min() > 0.3)
# point light shadows (raised an error before pcg85). A vertical wall (running the full length along v), light to the right of the wall: the shadow extends from the wall's
# left edge to the left by (lx - x_w)·h / (lz - h) -- similar triangles, analytic solution. h is converted to image-width units by Strength / World
# Size. Each pixel is classified into three kinds by the analytic shadow extent (pixels within 1.5 cells of the boundary are not judged)


def point_shadow_case(col, hw, lx, lz, strength=1.0, ws=1.0, rows=None, wide=2):
    hm = np.zeros((H, W, 1))
    rr = slice(None) if rows is None else rows
    hm[rr, col:col + wide] = hw
    wimg = HM.height_to_normal(mk(h=hm), "h", strength, ws)
    kw = dict(light_type="point", position=f"{lx} 0.5", light_height=lz,
              height_layer="h", ambient=0.1, strength=strength, world_size=ws)
    on = L(HV.light(wimg, "N", shadows=True, **kw), "lit")[..., 0]
    off = L(HV.light(wimg, "N", shadows=False, **kw), "lit")[..., 0]
    h_ = hw * strength / ws
    xw = col / W
    xs = xw - (lx - xw) * h_ / (lz - h_)
    c = (np.arange(W) + 0.5) / W
    ins = (c > xs + 1.5 / W) & (c < xw - 2.0 / W)   # normals within two cells of the wall are tilted by the wall's slope, not counted
    out = (c < xs - 1.5 / W)
    return on, off, ins, out, xs


lps, lpn, inside, outside, xs = point_shadow_case(20, 0.05, 0.9, 0.15)
check("point light shadow: similar triangles between wall and light, only Ambient in the shadow, lit outside it",
      inside.sum() >= 8 and outside.sum() >= 5 and np.allclose(lps[:, inside], 0.1)
      and (lps[:, outside] > 0.2).all() and (lps[:, 24:40] > 0.2).all(),
      (round(xs * W, 2), lps[16, :22].round(2)))
check("  negative control: with Shadows off the same area is bright", (lpn[:, inside] > 0.2).all())
a2 = point_shadow_case(20, 0.05, 0.9, 0.15, strength=2.0, ws=2.0)
check("  Strength / World Size scaled up proportionally: same shadow (only the height / image-width ratio matters)",
      np.array_equal(a2[0], lps))
lph, _, insh, outh, xsh = point_shadow_case(20, 0.05, 0.9, 0.15, ws=2.0)
check("  World Size doubled = wall half as tall: shadow shrinks per the analytic solution to %.1f cells" % (xsh * W),
      np.allclose(lph[:, insh], 0.1) and (lph[:, outh] > 0.2).all()
      and outh.sum() > outside.sum() + 5)
# thick wall close to the light, far from the pixels: the whole left half is in shadow (the analytic shadow extends off the image), and for the left
# pixels the place blocking the view is in the second half of the path -- an implementation that only walks the first half would judge them lit
lpf, _, insf, _, xsf = point_shadow_case(30, 0.05, 0.95, 0.07, wide=6)
far = (np.arange(W) + 0.5) / W < 2 * 30 / W - 0.95 - 1.0 / W
check("  a blocking wall in the second half of the path (close to the light) still blocks",
      xsf < 0 and far.sum() >= 10 and np.allclose(lpf[:, far & insf], 0.1),
      (round(xsf * W, 2), far.sum()))
# square pillar (only occupying a few middle rows): the shadow falls only on the extension of the pillar's rows -- row index must be taken as v·H
lpp, _, insp, _, _ = point_shadow_case(20, 0.05, 0.9, 0.15, rows=slice(13, 19))
check("  the pillar's shadow only on its own rows: row 16 in shadow, rows 3 / 28 lit",
      np.allclose(lpp[16, insp], 0.1) and (lpp[3, insp] > 0.2).all()
      and (lpp[28, insp] > 0.2).all())
# mirroring: flip terrain and light together left/right / up/down, and the shadow flips exactly too. When the sampling coordinates are off by half a cell (not aligned
# to pixel centers) everything shifts to one side and this does not match
pil = np.zeros((H, W, 1)); pil[12:17, 20:23] = 0.05
def psh(hm, pos):
    return HV._point_shadow(mk(h=hm), "h", 1.0, 1.0, pos, 0.12)
base_ = psh(pil, "0.8 0.35")
check("  mirror symmetry: flipped left/right / up/down, the shadow flips with it (pixel-identical)",
      (base_ == 0).sum() > 10
      and np.array_equal(psh(pil[:, ::-1], "0.2 0.35"), base_[:, ::-1])
      and np.array_equal(psh(pil[::-1], "0.8 0.65"), base_[::-1]))
# a low point light shining on a slope that goes down toward it: the light is lower than points on the slope, but nothing is in between, so the whole face is lit.
# if the sample landing back in the pixel's own cell is not excluded, it shadows itself (the whole area goes black)
sl = 0.8 * (1.0 - (np.arange(W) + 0.5) / W)
slope = np.broadcast_to(sl[None, :, None], (H, W, 1)).copy()
simg = HM.height_to_normal(mk(h=slope), "h", 1, 1)
kws = dict(light_type="point", position="0.95 0.5", light_height=0.8 * 0.05 + 0.05,
           height_layer="h", ambient=0.0)
ls_on = L(HV.light(simg, "N", shadows=True, **kws), "lit")[..., 0]
ls_off = L(HV.light(simg, "N", shadows=False, **kws), "lit")[..., 0]
check("  low point light on a slope going down toward it: points on the slope higher than the light are lit too (no self-shadowing)",
      np.allclose(ls_on[:, 2:40], ls_off[:, 2:40]) and ls_off[:, 2:40].min() > 0.05)
flat = HM.height_to_normal(mk(h=np.zeros((H, W, 1))), "h", 1, 1)
kw = dict(light_type="point", position="0.9 0.5", light_height=0.15,
          height_layer="h", ambient=0.1)
check("  light at the corner of the image (sampling clamped to the last row / last column): no out-of-bounds, no shadow on flat ground",
      (HV._point_shadow(mk(h=np.zeros((H, W, 1))), "h", 1.0, 1.0, "1 1", 0.1) == 1).all())
check("  not a single shadow pixel from a point light on flat ground",
      np.array_equal(L(HV.light(flat, "N", shadows=True, **kw), "lit"),
                     L(HV.light(flat, "N", shadows=False, **kw), "lit")))

hh = np.linspace(-1, 2, 301).reshape(1, 301, 1)
hc = L(HV.hf_clip(mk(h=hh), "h", "both", 0.0, 1.0, 0.0), "h")
check("hard clip = np.clip", np.allclose(hc, np.clip(hh, 0, 1)))
s_ = 0.1
hs_ = L(HV.hf_clip(mk(h=hh), "h", "both", 0.0, 1.0, s_), "h")[0, :, 0]
xv = hh[0, :, 0]
keep = (xv >= s_ + 1e-9) & (xv <= 1 - s_ - 1e-9)
check("soft knee: unchanged bit for bit within [lo + s, hi - s]", np.array_equal(hs_[keep],
                                                     xv[keep]))
check("  monotonic, within [lo, hi]", np.all(np.diff(hs_) >= 0) and hs_.min() >= 0
      and hs_.max() <= 1)
dd = np.diff(hs_) / np.diff(xv)
check("  C¹: slope continuous everywhere (neighbour difference < 0.1)", np.abs(np.diff(dd)).max() < 0.1,
      np.abs(np.diff(dd)).max())
check("  _clipped = amount changed", np.allclose(L(HV.hf_clip(mk(h=hh), "h", "both",
                                                     0, 1, s_), "h_clipped")
                                         [0, :, 0], np.abs(hs_ - xv)))

Wp = 40
base = mk(C=rng.random((Wp, Wp, 1)) * 0.2)
plate = TR.to_mesh(CopImage(8, 8, {"h": np.full((8, 8, 1), 0.5)}), "h", 1,
                   1.4, 1, True, False)
o, rp = HV.hf_project(base, plate, "C", "replace", 2.0, 1.0)
check("flat slab projected down: height = slab height / Strength (all hit)", np.allclose(
    L(o, "C"), 0.25, atol=1e-6) and rp["hit_texels"] == Wp * Wp)
o, _ = HV.hf_project(base, plate, "C", "max", 1.0, 1.0)
check("  max: maximum with the original height", np.allclose(L(o, "C"), np.maximum(
    L(base, "C"), 0.5), atol=1e-6))
o, rp = HV.hf_project(base, None, "C", strength=1.0, world_size=1.0)
check("identity Transform 3D = original height (1e-6)", np.abs(L(o, "C") - L(base, "C"))
      .max() < 1e-6 and rp["hit_texels"] == Wp * Wp)
o, _ = HV.hf_project(base, None, "C", translate="0 0.1 0")
check("  raise by 0.1 = original height + 0.1", np.allclose(L(o, "C"), L(base, "C") + 0.1,
                                          atol=1e-6))
o, _ = HV.hf_project(base, None, "C", scale="1 2 1")
check("  Y scale 2: stretched around the mean", np.allclose(L(o, "C"), 2 * L(base, "C")
                                        - L(base, "C").mean(), atol=1e-5))

tr = mk(C=rng.random((H, W, 1)) * 0.9)
st0 = L(HV.strata(tr, "C", 0.1, 0.0), "C")
check("Strata: Strength 0 is identity", np.array_equal(st0, L(tr, "C")))
stt = L(HV.strata(tr, "C", 0.1, 1.0, 0.7, "0 0", 0.0, 4.0, 0.0), "C")
ter = L(TR.terrace(tr, "C", 0.1, 0.0, 0.7), "C")
check("  no tilt, no noise, no random hardness = Terrace (1e-9)", np.abs(stt - ter).max()
      < 1e-6, np.abs(stt - ter).max())
flatc = mk(C=np.full((H, W, 1), 0.33))
tl = L(HV.strata(flatc, "C", 0.1, 1.0, 0.0, "0.5 0", 0.0), "C_id")[..., 0]
check("  Tilt: on flat ground the layer index varies along u (layers are slanted)", tl[:, -1].mean() >
      tl[:, 0].mean() and np.all(np.diff(tl, axis=1) >= 0))

# ═══════════════════════════════════════════════════════ visualize / contact sheet / transitions
sec("Visualize / Contact Sheet / Wipe")
ramp_img = mk(h=np.linspace(0, 1, W).reshape(1, W, 1) * np.ones((H, 1, 1)))
v = L(HV.visualize(ramp_img, "h", "height_ramp", "viridis", hillshade=0),
      "vis")
check("color ramp ends: lowest = ramp(0), highest = ramp(1)", np.allclose(
    v[0, 0], HV.ramp(np.array(0.0), "viridis")) and np.allclose(
    v[0, -1], HV.ramp(np.array(1.0), "viridis")))
vel = np.zeros((H, W, 2)); vel[..., 0] = 1
vh = L(HV.visualize(mk(v=vel), "v", "velocity_hsv"), "vis")
check("+u velocity is red", np.allclose(vh[0, 0], [1, 0, 0]))
vl = L(HV.visualize(mk(v=vel), "v", "velocity_lic", lic_length=8),
       "vis")[..., 0]
cx_ = np.corrcoef(vl[:, 10:30].ravel(), vl[:, 13:33].ravel())[0, 1]
cy_ = np.corrcoef(vl[5:25, :].ravel(), vl[8:28, :].ravel())[0, 1]
check("LIC: correlation along the flow direction (u) ≫ perpendicular", cx_ > 0.7 and cy_ < 0.2,
      (cx_, cy_))
va = L(HV.visualize(mk(v=vel * 5), "v", "velocity_arrows", scale=1,
                    arrow_spacing=16), "vis")
check("arrows: something drawn, coverage within 0~1", va.max() > 0.9 and va.min() >= 0)

seq = [CopImage(20, 10, {"C": np.full((10, 20, 1), k / 10.0)})
       for k in range(5)]
cs = HV.contact_sheet(seq, columns=3, padding=2, labels=False)
a_ = L(cs, "C")[..., 0]
check("Contact Sheet size = 3 columns x 2 rows + spacing", cs.xres == 3 * 20 + 4 * 2
      and cs.yres == 2 * 10 + 3 * 2)
# frame k: column k % 3, row k // 3 (first row at the top = larger row)
ok = all(np.allclose(a_[cs.yres - (2 + (k // 3 + 1) * 10 + (k // 3) * 2)
                        + 5, 2 + (k % 3) * 22 + 10], k / 10.0)
         for k in range(5))
check("  frame k in row k // 3 (from the top), column k % 3", ok)

A = mk(C=np.zeros((H, W, 3)))
B = mk(C=np.ones((H, W, 3)))
check("Wipe: t = 0 / 1 is A / B bit for bit", all(
    np.array_equal(L(HV.wipe(A, B, "C", md, 0.0), "C"), L(A, "C")) and
    np.array_equal(L(HV.wipe(A, B, "C", md, 1.0), "C"), L(B, "C"))
    for md in HV.WIPES))
wl_ = L(HV.wipe(A, B, "C", "linear", 0.5, 0, 0.02), "C")[..., 0]
check("  linear 0°, t = ½: left half B, right half A", wl_[:, :20].min() == 1 and
      wl_[:, 28:].max() == 0)
wd = L(HV.wipe(mk(C=np.zeros((64, 64, 1))), mk(C=np.ones((64, 64, 1))), "C",
               "dissolve", 0.3, softness=0.01), "C")
check("  dissolve: B share ≈ t (±0.03)", abs(wd.mean() - 0.3) < 0.03,
      wd.mean())
check("  crossfade = linear mix", np.allclose(L(HV.wipe(A, B, "C", "crossfade",
                                                  0.3), "C"), 0.3))

# ═══════════════════════════════════════════════════════ sequences
sec("sequences")
fr = [CopImage(8, 8, {"C": np.full((8, 8, 1), float(k))}) for k in range(6)]
val = lambda s: [float(L(x, "C")[0, 0, 0]) for x in s]      # noqa: E731
check("reverse twice = unchanged", val(HV.seq_ops(HV.seq_ops(fr, "reverse"),
                                            "reverse")) == val(fr))
check("shift loop by n = unchanged; shift by 2 = pushed back two frames",
      val(HV.seq_ops(fr, "shift", 6, "loop")) == val(fr) and
      val(HV.seq_ops(fr, "shift", 2, "loop")) == [4, 5, 0, 1, 2, 3])
check("  hold: the gap is filled with the first frame", val(HV.seq_ops(fr, "shift", 2, "hold"))
      == [0, 0, 0, 1, 2, 3])
rt = val(HV.seq_ops(fr, "retime", frames=11))
check("retime 6 -> 11: first/last bit-identical, middle linear (0.5 per step)",
      len(rt) == 11 and rt[0] == 0 and rt[-1] == 5 and np.allclose(
          rt, np.arange(11) * 0.5))
lp_ = val(HV.seq_ops(fr, "loop", blend=2))
check("loop blend 2: outputs 4 frames; frame i = tail (m+i) blended toward head (i) by (i+1)/(b+1) -- "
      "frame 0 most resembles original frame 4, following frame 3",
      np.allclose(lp_, [8 / 3, 7 / 3, 2, 3]), lp_)
check("blend: per frame mixed by weight", val(HV.seq_ops(fr, "blend", other=[
    CopImage(8, 8, {"C": np.full((8, 8, 1), 10.0)})] * 6, weight=0.25))
      == [k * 0.75 + 2.5 for k in range(6)])
err("blend without a second sequence raises", lambda: HV.seq_ops(fr, "blend"), "second sequence")

# ═══════════════════════════════════════════════════════ nodes / comparison table
sec("nodes / comparison table")
F_ = ["PCG_COPLayerToPoints", "PCG_COPPointsFromBlobs",
      "PCG_COPRasterizeCurves", "PCG_COPRasterizeSplats",
      "PCG_COPBakeTextures", "PCG_COPLight", "PCG_COPHFClip",
      "PCG_COPHFProject", "PCG_COPStrata", "PCG_COPVisualize",
      "PCG_COPContactSheet", "PCG_COPWipe", "PCG_COPSequenceOps"]
check(f"all {len(F_)} batch F nodes registered, all under PCG/cop",
      all(k in MAP and MAP[k].CATEGORY == "PCG/cop" for k in F_))
bad = [k for k in F_ for nm in MAP[k].INPUT_TYPES()["required"]
       if nm == "seed"]
check("  no widget named seed", not bad, bad)
r = MAP["PCG_COPSequenceOps"]().run(fr, "reverse", 0, "hold", 24, 4, 0.5)
r = tuple(r["result"]) if isinstance(r, dict) else r
check("  Sequence Ops outputs (sequence, frame count)", r[1] == 6 and val(r[0])[0] == 5)
import copernicus_map as CM                              # noqa: E402
st = {}
for k, (s_, ref) in CM.M.items():
    st[s_] = st.get(s_, 0) + 1
check(f"Copernicus comparison table complete: todo = 0 ({st})", st.get("todo", 0) == 0)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
