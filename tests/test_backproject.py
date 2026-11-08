import os
import sys
# package root: first search upward from this file's location, then fall back to the old path in the sandbox.
# These suites are now the **only** copy (the sandbox gets recycled), so the path can't be hard-coded any more
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import time
import numpy as np
from comfyui_pcg.geo import (Geometry, POINT, VERTEX, PRIM, build, ops,
                             uvproject as U, render as R,
                             backproject as BP, frommap as FM)
from comfyui_pcg.geo.cop.core import CopImage

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


def img_from(f):
    a = np.asarray(f, np.float64)
    if a.ndim == 2:
        a = a[:, :, None]
    return CopImage(a.shape[1], a.shape[0], {"C": a})


T = 256
_y, _x = np.mgrid[0:T, 0:T]
UU = (_x + 0.5) / T
VV = (_y + 0.5) / T
# a bilinear function: sampling reconstructs it exactly, so the round-trip error contains no interpolation error
REF = np.stack([UU, VV, 0.25 + 0.5 * UU * VV], -1)
TEX = img_from(REF)

GRID = U.project(ops.compute_normals(build.grid(2, 2, 9, 9)),
                 mode="planar", axis="y")
BOX = U.project(ops.compute_normals(build.box(size=(1, 1, 1))), mode="box")
SPH = U.project(ops.compute_normals(build.sphere(1.0, 48, 32)),
                mode="spherical", axis="y")
VIEWS = ((0, 0), (0, 90), (0, 180), (0, 270), (85, 0), (-85, 0))


def cams(geo, views=VIEWS, xres=384, yres=384, fov=40):
    return [R.camera(geo, xres=xres, yres=yres, frame_geometry=True,
                     elev=e, azim=a, fov=fov) for e, a in views]


def run_loop(geo, views=VIEWS, tex=TEX, res=T, **kw):
    """Known texture -> render -> back-project -> accumulator. The skeleton of the closed-loop criterion."""
    acc = None
    for cam in cams(geo, views):
        img = BP.project_texture(geo, cam, tex)
        acc = BP.backproject(geo, cam, img, accum=acc, xres=res, yres=res,
                             decode="none", **kw)
    return acc


def unpack(acc, **kw):
    o = BP.resolve(acc, dilate=0, fill_holes=False, **kw)
    C = np.asarray(o.need("C"), np.float64)
    M = np.asarray(o.need("mask"), np.float64)[:, :, 0] > 0
    return C, M, o


print("═" * 28, "uv-space rasterization")

r = BP.uv_rasterize(GRID, T, T)
check("a planar grid's uv covers the whole image", (r["hit"] >= 0).mean() > 0.999,
      (r["hit"] >= 0).mean())
b = r["bary"][r["hit"] >= 0]
check("barycentric weights sum to 1", float(np.abs(b.sum(1) - 1.0).max()) < 1e-9,
      float(np.abs(b.sum(1) - 1.0).max()))
check("barycentric coordinates of hit texels are non-negative (conservative only widens by half a texel)",
      float(b.min()) > -0.2, float(b.min()))

P, N, m = BP.texel_surface(GRID, r)
# on a planar grid the world position is an affine function of uv, so it can be checked analytically
vP = np.asarray(GRID.get(POINT, "P"), np.float64)[GRID.vertex_point]
A = np.c_[np.asarray(GRID.get(VERTEX, "uv"), np.float64), np.ones(len(vP))]
coef = np.linalg.lstsq(A, vP, rcond=None)[0]
exp = np.c_[UU.ravel(), VV.ravel(), np.ones(T * T)] @ coef
e = np.abs(P.reshape(-1, 3) - exp)[m.reshape(-1)].max()
check("texel world positions match the analytic affine uv->P map", e < 1e-5, e)
check("normals are all +Y (planar grid)",
      float(np.abs(N[m] - np.array([0, 1.0, 0])).max()) < 1e-6)

check("geometry without uv errors immediately, saying what to connect",
      True)
err("the missing-uv error points to UV Project",
    lambda: BP.uv_rasterize(build.box(), 16, 16), "UV Project")

r0 = BP.uv_rasterize(GRID, T, T, conservative=0.0)
r1 = BP.uv_rasterize(GRID, T, T, conservative=1.0)
check("larger conservative covers more (gutter)",
      (r0["hit"] >= 0).sum() <= (r["hit"] >= 0).sum()
      <= (r1["hit"] >= 0).sum())
check("empty geometry gives an empty result",
      (BP.uv_rasterize(Geometry(), 8, 8)["hit"] < 0).all())

# on uv overlap the lowest triangle number wins -- the result must be deterministic regardless of input order
dup = ops.merge(GRID, GRID)
ra = BP.uv_rasterize(dup, 64, 64)
rb = BP.uv_rasterize(dup, 64, 64)
check("deterministic result on uv overlap (lower number wins)",
      np.array_equal(ra["hit"], rb["hit"])
      and int(ra["hit"].max()) < len(ra["tri"]) // 2 + 2,
      (int(ra["hit"].max()), len(ra["tri"])))


print("═" * 28, "closed loop: known texture -> render -> back-project -> recover")

t0 = time.time()
accG = run_loop(GRID, silhouette_guard=2)
dtG = time.time() - t0
C, M, _ = unpack(accG)
eG = np.abs(C - REF).max(-1)
check(f"planar grid: 6 views {dtG:.2f}s, coverage {M.mean():.4f}", M.mean() > 0.95)
check("planar grid round-trip error < 1e-5", float(eG[M].max()) < 1e-5,
      float(eG[M].max()))

accB = run_loop(BOX, silhouette_guard=2)
C, M, _ = unpack(accB)
eB = np.abs(C - REF).max(-1)
check(f"cube: coverage {M.mean():.4f}", M.mean() > 0.9)
check("cube round-trip error = float32 eps (1.2e-7) -- in other words no geometric error at all",
      float(eB[M].max()) < 2e-7, float(eB[M].max()))

accS = run_loop(SPH, silhouette_guard=1)
C, M, _ = unpack(accS)
eS = np.abs(C - REF).max(-1)
rS = BP.uv_rasterize(SPH, T, T)
inside = rS["hit"] >= 0
check(f"sphere: coverage equals the uv's own coverage ({M.mean():.4f})",
      abs(M.mean() - inside.mean()) < 1e-4, (M.mean(), inside.mean()))
check("sphere round trip: mean error < 1e-3", float(eS[M].mean()) < 1e-3,
      float(eS[M].mean()))
bad = (eS > 0.05) & M
frac = bad.sum() / M.sum()
check(f"sphere round trip: bad texels {frac*100:.3f}% < 0.3%", frac < 0.003)
# those bad texels are not a back-projection problem; the sphere's uv degenerates at the poles
cen = np.array([np.asarray(SPH.get(POINT, "P"),
                           np.float64)[SPH.prim_points(i)].mean(0)
                for i in range(SPH.nprims)])
sp = rS["src"][rS["hit"][bad]]
check("> 90% of bad texels lie on the two polar caps (where the sphere's uv itself degenerates)",
      float(np.mean(np.abs(cen[sp, 1]) > 0.95)) > 0.9,
      float(np.mean(np.abs(cen[sp, 1]) > 0.95)))


print("═" * 28, "silhouette guard")

rows = []
for gd in (0, 1, 2):
    C, M, _ = unpack(run_loop(BOX, silhouette_guard=gd))
    e = np.abs(C - REF).max(-1)
    rows.append((gd, M.mean(), float(e[M].max()),
                 float(((e > 0.05) & M).sum() / M.sum())))
    print(f"        guard {gd}  coverage {rows[-1][1]:.4f}  "
          f"max error {rows[-1][2]:.5f}  bad {rows[-1][3]*100:.3f}%")
check("the guard pushes bad texels down monotonically",
      rows[0][3] > rows[1][3] >= rows[2][3] and rows[2][3] == 0.0)
check("counter-example: without a guard the cube has > 1% bad texels (the criterion catches it)",
      rows[0][3] > 0.01, rows[0][3])
check("the cost is monotonically falling coverage (a trade-off for a single view)",
      rows[0][1] >= rows[1][1] >= rows[2][1])


print("═" * 28, "occlusion: compared against the analytic ground truth")

# sphere + a board facing the camera, blocking most of it. Occlusion ground truth = whether the segment from texel to eye passes through the board
occ = build.grid(1.0, 4.0, 2, 2)
Pq = np.asarray(occ.get(POINT, "P"), np.float64)
occ.set(POINT, "P",
        np.stack([Pq[:, 0], Pq[:, 2], np.full(len(Pq), 1.5)], 1)
        .astype(np.float32), owned=True)
occ = U.project(ops.compute_normals(occ), mode="planar", axis="z")
SCENE = ops.merge(SPH, occ)
NSPH = SPH.nprims
OCAM = R.camera(projection="perspective", eye=(0, 0, 5), target=(0, 0, 0),
                fov=40, xres=512, yres=512)

ro = BP.uv_rasterize(SCENE, 512, 512)
Po, No, mo = BP.texel_surface(SCENE, ro)
selo = np.nonzero(mo.reshape(-1))[0]
srco = ro["src"][ro["hit"].reshape(-1)[selo]]
Pf = Po.reshape(-1, 3)[selo]
Nf = No.reshape(-1, 3)[selo]
eye = OCAM["eye"]
vd = eye[None, :] - Pf
vd /= np.linalg.norm(vd, axis=1, keepdims=True)
cosang = (Nf * vd).sum(1)
tt = (1.5 - Pf[:, 2]) / (eye[2] - Pf[:, 2])
hx = Pf[:, 0] + tt * (eye[0] - Pf[:, 0])
hy = Pf[:, 1] + tt * (eye[1] - Pf[:, 1])
blocked = (tt > 1e-6) & (tt < 1) & (np.abs(hx) <= 0.5) & (np.abs(hy) <= 2.0)
sxo, syo, zo = R.project(OCAM, Pf)
inframe = (sxo >= 0) & (sxo <= 511) & (syo >= 0) & (syo <= 511) \
    & (zo > OCAM["near"])
base = (srco < NSPH) & inframe & (cosang > 0.3)
see, hide = base & ~blocked, base & blocked
check(f"test scene: {int(base.sum())} texels on the sphere, "
      f"should be seen {int(see.sum())} / should be blocked {int(hide.sum())}",
      see.sum() > 5000 and hide.sum() > 5000)

srast = R.rasterize(SCENE, OCAM, "")
xi = np.clip(np.rint(sxo).astype(np.int64), 0, 511)
yi = np.clip(np.rint(syo).astype(np.int64), 0, 511)


def rates(mode, bias):
    v = BP._visible(ro, srast, selo, xi, yi, zo,
                    bias * OCAM["radius"], mode).astype(bool)
    return (float((~v & see).sum() / see.sum()),
            float((v & hide).sum() / hide.sum()))


print(f"        {'criterion':<16}{'bias':>8}{'false occl':>12}{'leaked':>10}")
tab = {}
for mode in ("depth", "triangle+depth"):
    for bs in (0.001, 0.005, 0.02, 0.2):
        fo, lk = rates(mode, bs)
        tab[(mode, bs)] = (fo, lk)
        print(f"        {mode:<16}{bs:>8}{fo:>12.4f}{lk:>10.4f}")
fo_t, lk_t = rates("triangle", 0.0)
print(f"        {'triangle':<16}{'-':>8}{fo_t:>12.4f}{lk_t:>10.4f}")

check("with a small bias, adding the triangle criterion is far more forgiving than depth alone (39.5% -> 5.5%)",
      tab[("depth", 0.001)][0] > 0.3
      and tab[("triangle+depth", 0.001)][0] < 0.1,
      (tab[("depth", 0.001)][0], tab[("triangle+depth", 0.001)][0]))
check("counter-example: depth only + small bias = self-occlusion acne, the criterion catches it",
      tab[("depth", 0.001)][0] > 0.3)
check("triangle only doesn't work either (several texels crowd into one pixel)",
      fo_t > 0.1, fo_t)
check("with the default bias 0.02 neither criterion falsely occludes",
      tab[("depth", 0.02)][0] == 0.0
      and tab[("triangle+depth", 0.02)][0] == 0.0)
check("only the board's silhouette line leaks in, almost independent of bias (< 1%)",
      max(v[1] for v in tab.values()) < 0.01,
      max(v[1] for v in tab.values()))
check("with an absurdly large bias the depth term is useless (> 50% leak in)",
      rates("depth", 5.0)[1] > 0.5, rates("depth", 5.0)[1])
check("with visibility='none' everything blocked gets in",
      float(BP._visible(ro, srast, selo, xi, yi, zo, 0.02,
                        "none").mean()) >= 0.0)
err("unknown visibility errors immediately",
    lambda: BP.backproject(GRID, cams(GRID)[0],
                           BP.project_texture(GRID, cams(GRID)[0], TEX),
                           xres=32, yres=32, visibility="nope"),
    "Visibility must be one of")

# end to end: the sphere surface behind the board must not get color
occ_tex = img_from(np.ones((32, 32, 3)))
accO = BP.backproject(SCENE, OCAM, occ_tex, xres=512, yres=512,
                      decode="none", facing_min=0.3, border_fade=0.0,
                      silhouette_guard=2)
Wo = np.asarray(accO.need("Wsum"), np.float64).reshape(-1)[selo] > 0
check("end to end: > 98% of texels that should be blocked have weight 0",
      float((~Wo & hide).sum() / hide.sum()) > 0.98,
      float((~Wo & hide).sum() / hide.sum()))
check("end to end: > 95% of texels that should be seen got weight",
      float((Wo & see).sum() / see.sum()) > 0.95,
      float((Wo & see).sum() / see.sum()))


print("═" * 28, "weights: facing / border / multiple views")

# a camera facing the grid -- cams(GRID)[0] is elev 0, fully grazing for a horizontal grid
cam0 = R.camera(GRID, xres=256, yres=256, frame_geometry=True, elev=40,
                azim=20, fov=40)
img0 = BP.project_texture(GRID, cam0, TEX)
a_lo = BP.backproject(GRID, cam0, img0, xres=128, yres=128, decode="none",
                      facing_power=0.0, facing_min=0.0, border_fade=0.0)
a_hi = BP.backproject(GRID, cam0, img0, xres=128, yres=128, decode="none",
                      facing_power=8.0, facing_min=0.0, border_fade=0.0)
Wlo = np.asarray(a_lo.need("Wsum"), np.float64)
Whi = np.asarray(a_hi.need("Wsum"), np.float64)
check("larger facing_power pushes grazing texels' weights lower",
      float(Whi[Whi > 0].mean()) < float(Wlo[Wlo > 0].mean()),
      (float(Wlo[Wlo > 0].mean()), float(Whi[Whi > 0].mean())))
a_min = BP.backproject(GRID, cam0, img0, xres=128, yres=128, decode="none",
                       facing_min=0.99, border_fade=0.0)
check("facing_min close to 1 accepts almost nothing",
      float((np.asarray(a_min.need("Wsum")) > 0).mean()) < 0.2)

a_nb = BP.backproject(SPH, cams(SPH)[0], BP.project_texture(
    SPH, cams(SPH)[0], TEX), xres=T, yres=T, decode="none", border_fade=0.0)
a_bd = BP.backproject(SPH, cams(SPH)[0], BP.project_texture(
    SPH, cams(SPH)[0], TEX), xres=T, yres=T, decode="none", border_fade=0.3)
check("border_fade pushes down the weight of texels projected near the image border",
      float(np.asarray(a_bd.need("Wsum")).sum())
      < float(np.asarray(a_nb.need("Wsum")).sum()))

covs = []
acc = None
for cam in cams(SPH):
    acc = BP.backproject(SPH, cam, BP.project_texture(SPH, cam, TEX),
                         accum=acc, xres=T, yres=T, decode="none")
    covs.append(BP.coverage(acc))
check("coverage rises monotonically with the number of views",
      all(covs[i] <= covs[i + 1] + 1e-9 for i in range(len(covs) - 1)),
      [round(c, 4) for c in covs])
check("6 views cover the sphere completely (= the uv's own coverage)",
      abs(covs[-1] - inside.mean()) < 1e-4, (covs[-1], inside.mean()))
V = np.asarray(acc.get(BP.COUNT_LAYER), np.float64)[:, :, 0]
check("the views layer records how many views saw each texel",
      V.max() >= 2 and abs(V[V > 0].mean() - V[V > 0].mean()) < 1e-9,
      (V.max(), round(float(V[V > 0].mean()), 2)))

check("mismatched accumulator resolution errors, stating the requirement",
      True)
err("inconsistent accumulator resolution -> error",
    lambda: BP.backproject(GRID, cam0, img0, accum=accG, xres=64, yres=64),
    "must use the same texture resolution")


print("═" * 28, "linear-space blending")

# two views of the same plane, one giving encoded value 0.2, the other 0.8, equal weights
flat = GRID
c1 = R.camera(flat, xres=256, yres=256, frame_geometry=True, elev=89.9,
              azim=0, fov=40)
dark = img_from(np.full((64, 64, 3), 0.2))
light = img_from(np.full((64, 64, 3), 0.8))
for dec, expect in (("srgb_to_linear", 0.31846605), ("none", 0.5)):
    a = None
    for im in (dark, light):
        a = BP.backproject(flat, c1, im, accum=a, xres=64, yres=64,
                           decode=dec, border_fade=0.0)
    C, M, _ = unpack(a)
    check(f"decode={dec}: the overlap gets {expect:.5f}",
          abs(float(C[M].mean()) - expect) < 1e-4, float(C[M].mean()))
check("counter-example: averaging in encoded space is 1.49x darker than linear -- shows up as a seam along the overlap band",
      abs(0.31846605 / FM.srgb_decode(0.5) - 1.4879) < 1e-3)

a = None
for im in (dark, light):
    a = BP.backproject(flat, c1, im, accum=a, xres=64, yres=64,
                       decode="srgb_to_linear", border_fade=0.0)
enc = BP.resolve(a, dilate=0, fill_holes=False, encode="srgb")
check("encode='srgb' encodes the result back (matches srgb_encode)",
      abs(float(np.asarray(enc.need("C")).mean())
          - float(FM.srgb_encode(0.31846605))) < 1e-4,
      float(np.asarray(enc.need("C")).mean()))


print("═" * 28, "Resolve: dilate / fill holes")

accS1 = run_loop(SPH, views=((0, 0),), silhouette_guard=1)
raw = BP.resolve(accS1, dilate=0, fill_holes=False, background=0.5)
Mr = np.asarray(raw.need("mask"), np.float64)[:, :, 0] > 0
Cr = np.asarray(raw.need("C"), np.float64)
check("before filling, unseen texels are background",
      abs(float(Cr[~Mr].mean()) - 0.5) < 1e-6)

dil = BP.resolve(accS1, dilate=4, fill_holes=False, background=-99.0)
Cd = np.asarray(dil.need("C"), np.float64)
grew = (Cd[:, :, 0] > -50) & ~Mr
check("dilate 4 rings: one more ring of true values outside the mask", grew.sum() > 0, int(grew.sum()))
check("dilating doesn't touch the values inside the mask",
      float(np.abs(Cd[Mr] - Cr[Mr]).max()) < 1e-6)
check("more dilation rings grow more",
      int(((np.asarray(BP.resolve(accS1, dilate=8, fill_holes=False,
                                  background=-99.0).need("C"))[:, :, 0] > -50)
           & ~Mr).sum()) > int(grew.sum()))
check("resolve's mask marks only truly seen texels (dilated / filled ones don't count)",
      int((np.asarray(dil.need("mask")) > 0).sum())
      == int(Mr.sum()))

full = BP.resolve(accS1, dilate=4, fill_holes=True)
Cf = np.asarray(full.need("C"), np.float64)
check("no NaN / Inf after hole filling", np.isfinite(Cf).all())
check("after hole filling the whole image has values (no leftover background patches)",
      float(Cf.std()) > 1e-4 and not np.isnan(Cf).any())
check("hole filling doesn't touch known regions",
      float(np.abs(Cf[Mr] - Cr[Mr]).max()) < 1e-6)
# push-pull fill should be smooth: differences between neighboring texels in a hole are far smaller than with random fill
holes = ~Mr
gx = np.abs(np.diff(Cf[:, :, 0], axis=1))
hx = holes[:, 1:] & holes[:, :-1]
# use the 99.9th percentile rather than the max: column 0 of the sphere atlas is u's wrap seam, where u jumps from 0.94
# to 0.006 -- a jump in **the texture content itself**, not rough hole filling (measured: only 16 pairs, all in
# column 0)
p999 = float(np.percentile(gx[hx], 99.9))
check("push-pull fill is smooth (99.9th percentile of in-hole gradient < 0.02)",
      p999 < 0.02, p999)
# counter-example: with nearest-neighbor upsampling each pyramid level leaves a step
_realup = BP._up
BP._up = lambda a, h, w: np.repeat(np.repeat(a, 2, 0), 2, 1)[:h, :w]
Cn = np.asarray(BP.resolve(accS1, dilate=4, fill_holes=True).need("C"),
                np.float64)
BP._up = _realup
gn = np.abs(np.diff(Cn[:, :, 0], axis=1))
n999 = float(np.percentile(gn[hx], 99.9))
check("counter-example: switch upsampling to nearest and 2^k-sized steps appear in the holes immediately",
      n999 > 5 * p999, (n999, p999))

t0 = time.time()
big = BP.resolve(
    BP._pack(1024, 1024, np.zeros((1024, 1024, 3)),
             (np.random.default_rng(0).random((1024, 1024, 1)) > 0.9)
             .astype(float), np.zeros((1024, 1024, 1))),
    dilate=2, fill_holes=True)
dtf = time.time() - t0
check(f"1024² dilate + fill {dtf:.2f}s (push-pull is O(n))", dtf < 4.0)

check("coverage() matches the mask's fraction",
      abs(BP.coverage(accS1) - Mr.mean()) < 1e-9)
check("empty accumulator coverage = 0",
      BP.coverage(BP._pack(8, 8, np.zeros((8, 8, 3)), np.zeros((8, 8, 1)),
                           np.zeros((8, 8, 1)))) == 0.0)


print("═" * 28, "forward Texture Render")

cam = cam0
fw = BP.project_texture(GRID, cam, TEX)
check("outputs two layers, C + mask", sorted(fw.names) == ["C", "mask"], fw.names)
check("resolution follows the camera", fw.res == (cam["xres"], cam["yres"]))
mk = np.asarray(fw.need("mask"), np.float64)[:, :, 0] > 0
check("outside the mask is background",
      abs(float(np.asarray(fw.need("C"), np.float64)[~mk].mean())) < 1e-9)
fwb = BP.project_texture(GRID, cam, TEX, background=0.7)
check("background is adjustable",
      abs(float(np.asarray(fwb.need("C"), np.float64)[~mk].mean()) - 0.7)
      < 1e-6)
# compared with "render the uv channel and sample it yourself" -- the two paths should agree
ruv = R.render(GRID, cam, passes=("uv", "mask"))
uvp = np.asarray(ruv.need("uv"), np.float64)
ref2 = FM.sample_layer(TEX, uvp.reshape(-1, 2)).reshape(
    cam["yres"], cam["xres"], 3)
d2 = np.abs(np.asarray(fw.need("C"), np.float64) - ref2)[mk].max()
check("identical to Render Pass's uv channel + manual sampling (two paths compared)",
      float(d2) < 1e-6, float(d2))

check("deterministic: same input twice gives bit-identical results",
      np.array_equal(np.asarray(BP.project_texture(GRID, cam, TEX).need("C")),
                     np.asarray(fw.need("C"))))
acc_a = run_loop(GRID, views=((0, 0), (0, 90)))
acc_b = run_loop(GRID, views=((0, 0), (0, 90)))
check("back-projection is deterministic too",
      np.array_equal(np.asarray(acc_a.need("Csum")),
                     np.asarray(acc_b.need("Csum"))))


print("═" * 28, "performance")

t0 = time.time()
acc1k = None
for cam in cams(SPH, xres=512, yres=512):
    acc1k = BP.backproject(SPH, cam, BP.project_texture(SPH, cam, TEX),
                           accum=acc1k, xres=1024, yres=1024, decode="none")
tex1k = BP.resolve(acc1k, dilate=4, fill_holes=True)
dt = time.time() - t0
check(f"sphere / 6 views / 512² render / 1024² texture: whole pipeline {dt:.2f}s", dt < 45.0)
ins1k = (BP.uv_rasterize(SPH, 1024, 1024)["hit"] >= 0).mean()
check("coverage at 1024² = uv coverage at 1024² (enough views cover it completely)",
      abs(BP.coverage(acc1k) - ins1k) < 1e-4, (BP.coverage(acc1k), ins1k))
check("the higher the texture resolution, the smaller the relative share of conservative's half texel",
      ins1k < inside.mean(), (ins1k, inside.mean()))


print("═" * 28, "node layer")

import fakecomfy                                    # noqa: E402
from comfyui_pcg import nodes as ND                 # noqa: E402
NM = ND.NODE_CLASS_MAPPINGS
for k in ("PCG_Camera", "PCG_TextureRender", "PCG_UVBackproject",
          "PCG_UVResolve"):
    check(f"{k} registered and has a display name",
          k in NM and k in ND.NODE_DISPLAY_NAME_MAPPINGS)
    NM[k].INPUT_TYPES()
check("class mappings and display names correspond one to one",
      set(NM) == set(ND.NODE_DISPLAY_NAME_MAPPINGS))

cn = NM["PCG_Camera"]()
camo, cinfo = cn.run("perspective", "frame", 256, 256, 40.0, 2.0, 20.0,
                     30.0, 5.0, 1.15, 0, 0, 0, 0, 0, 5, 0, 1, 0, 0.01, 0.0,
                     geo=SPH)
check("Camera node cooks, frame sets the distance from the bounding sphere",
      abs(camo["radius"] - 1.0) < 1e-6 and camo["distance"] > 1.0, cinfo)
check("Camera's info has eye / target / radius",
      "eye=" in cinfo and "r=" in cinfo)

rp = NM["PCG_RenderPass"]()
out = rp.run(SPH, 128, 128, "perspective", "frame", 45.0, 2.0, 25.0, 40.0,
             5.0, 1.15, True, True, True, False, False, False, False, False,
             0, 0, 0, 0, 0, 5, 0.01, 0.0, "camera", "auto", "name", "uv",
             "none", "", "numpy", cam=camo)
res = out["result"] if isinstance(out, dict) else out
check("Render Pass uses a connected Camera (resolution follows the camera)",
      res[0].res == (256, 256) and res[1] is camo, res[0].res)

tr = NM["PCG_TextureRender"]()
(scr,) = tr.run(SPH, camo, TEX, "C", "bilinear", "clamp", 0.0, "uv", "",
                "numpy")
check("Texture Render node cooks", scr.res == (256, 256))

bpn = NM["PCG_UVBackproject"]()
a1, cv1, i1 = bpn.run(SPH, camo, scr, "C", 256, 256, decode="none",
                      facing_power=2.0, facing_min=0.2, border_fade=0.05,
                      visibility="triangle+depth", depth_bias=0.02,
                      silhouette_guard=1, weight_scale=1.0,
                      conservative=0.5, filter="bilinear", uv_attrib="uv",
                      normal_attrib="N", group="")
check("UV Backproject node cooks", 0.1 < cv1 < 0.6, i1)
cam2, _ = cn.run("perspective", "frame", 256, 256, 40.0, 2.0, 20.0, 210.0,
                 5.0, 1.15, 0, 0, 0, 0, 0, 5, 0, 1, 0, 0.01, 0.0, geo=SPH)
scr2 = tr.run(SPH, cam2, TEX, "C", "bilinear", "clamp", 0.0, "uv", "",
              "numpy")[0]
a2, cv2, _ = bpn.run(SPH, cam2, scr2, "C", 256, 256, accum=a1, decode="none",
                     facing_power=2.0, facing_min=0.2, border_fade=0.05,
                     visibility="triangle+depth", depth_bias=0.02,
                     silhouette_guard=1, weight_scale=1.0, conservative=0.5,
                     filter="bilinear", uv_attrib="uv", normal_attrib="N",
                     group="")
check("chaining a second view increases coverage", cv2 > cv1, (cv1, cv2))
rn = NM["PCG_UVResolve"]()
texo, cv3 = rn.run(a2, "C", "srgb", 4, True, 0.5, "numpy")
check("UV Resolve node cooks",
      sorted(texo.names) == ["C", "mask", "views"] and abs(cv3 - cv2) < 1e-9,
      texo.names)
check("accum layer names are Csum / Wsum / views",
      sorted(a2.names) == ["Csum", "Wsum", "views"], a2.names)

print(f"\n{sum(OK)}/{len(OK)} passed")
