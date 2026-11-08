import os
import sys
# Package root: first search upwards from this file's location, otherwise fall back to the old sandbox path.
# These suites are now the **only** copy (the sandbox gets recycled), so paths can no longer be hard-coded
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
                             uvproject as U, render as R, xform,
                             sequence as SQ, backproject as BP)
from comfyui_pcg.geo.cop import noise as NS, generate as G, backend as bk
from comfyui_pcg.geo.cop.core import CopImage

OK = []
def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)

def err(name, fn, frag):
    try:
        fn(); check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:120]}")


XP = bk.EXACT
RNG = np.random.default_rng(0)
SPH = U.project(ops.compute_normals(build.sphere(1.0, 48, 32)),
                mode="spherical", axis="y")
T = 128
_y, _x = np.mgrid[0:T, 0:T]
UU, VV = (_x + 0.5) / T, (_y + 0.5) / T
TEX = CopImage(T, T, {"C": np.stack([UU, VV, 0.25 + 0.5 * UU * VV], -1)})


def L(img, name):
    return np.asarray(img.need(name), np.float64)


print("═" * 28, "4D noise")

n = 300000
X, Y, Z, W = [RNG.random(n) * 300 - 150 for _ in range(4)]
rng4 = {}
for k in ("value", "perlin", "simplex", "worley", "worley_f2f1"):
    v = np.asarray(NS.base_noise(XP, X, Y, Z, k, 7, W), np.float64)
    rng4[k] = (float(v.min()), float(v.max()), float(v.std()))
    print(f"        {k:<12} min {v.min():7.4f}  max {v.max():7.4f}  "
          f"std {v.std():.4f}")
check("amplitudes of all five 4D noises fall within [-1.1, 1.1]",
      all(-1.1 <= lo and hi <= 1.1 for lo, hi, _ in rng4.values()), rng4)
check("simplex4 amplitude is on the same order as the 3D version (scale was measured, not copied)",
      0.9 < rng4["simplex"][1] < 1.0, rng4["simplex"][1])
check("perlin4 is scaled down by √(2/3) (4D gradient norm √3 vs 3D √2)",
      abs(NS._PERLIN4_SCALE - np.sqrt(2 / 3)) < 1e-12)
check("4D noise is not constant (std > 0.2; perlin is inherently smaller, the 3D version is only 0.27 too)",
      all(sd > 0.2 for _, _, sd in rng4.values()),
      {k: round(v[2], 4) for k, v in rng4.items()})

# w=0 slice: only value is bit-identical to 3D, the others can't be. Record all the differences
slices = {}
z0 = np.zeros(n)
for k in ("value", "perlin", "simplex", "worley", "worley_f2f1"):
    a = np.asarray(NS.base_noise(XP, X, Y, Z, k, 7, z0), np.float64)
    b = np.asarray(NS.base_noise(XP, X, Y, Z, k, 7), np.float64)
    slices[k] = (np.array_equal(a, b), float(np.abs(a - b).max()))
check("value's w=0 slice is **bit-identical** to the 3D version", slices["value"][0])
check("perlin/simplex/worley w=0 slices differ from 3D (each for its own reason, documented)",
      all(not slices[k][0] for k in ("perlin", "simplex", "worley",
                                     "worley_f2f1")),
      {k: round(v[1], 3) for k, v in slices.items()})

# Continuity: a small change in w changes the value only slightly (worley is C0, the others smoother)
xs, ys, zs = X[:20000], Y[:20000], Z[:20000]
for k in ("value", "perlin", "simplex"):
    a = np.asarray(NS.base_noise(XP, xs, ys, zs, k, 3,
                                 np.zeros(20000)), np.float64)
    b = np.asarray(NS.base_noise(XP, xs, ys, zs, k, 3,
                                 np.full(20000, 1e-4)), np.float64)
    check(f"{k}4 continuous along w (dw=1e-4 -> change < 1e-2)",
          float(np.abs(a - b).max()) < 1e-2, float(np.abs(a - b).max()))

# Rough isotropy check: swapping (z,w) with (x,y), the statistics should be close
a = np.asarray(NS.simplex4(XP, X, Y, Z, W, 5), np.float64)
b = np.asarray(NS.simplex4(XP, Z, W, X, Y, 5), np.float64)
check("simplex4 isotropic (std differs by < 2% after swapping axes)",
      abs(a.std() / b.std() - 1) < 0.02, (a.std(), b.std()))

xt = bk.get("cpu", 1, 1, 1)
sl = slice(0, 4000)
for k in ("value", "perlin", "simplex", "worley"):
    e = np.abs(np.asarray(NS.base_noise(XP, X[sl], Y[sl], Z[sl], k, 3,
                                        W[sl]), np.float64)
               - np.asarray(xt.to_numpy(NS.base_noise(
                   xt, xt.asarray(X[sl]), xt.asarray(Y[sl]),
                   xt.asarray(Z[sl]), k, 3, xt.asarray(W[sl]))),
                   np.float64)).max()
    check(f"{k}4 agrees on the exact / torch-cpu backends (< 1e-3)", e < 1e-3, e)

check("cell_hash's fourth dimension contributes 0 when cw=0 (so the 3D path doesn't change a single bit)",
      np.array_equal(
          np.asarray(NS.cell_hash(XP, np.int64([1, 2, 3]), np.int64([4, 5, 6]),
                                  np.int64([7, 8, 9]), 11)),
          np.asarray(NS.cell_hash(XP, np.int64([1, 2, 3]), np.int64([4, 5, 6]),
                                  np.int64([7, 8, 9]), 11,
                                  cw=np.int64([0, 0, 0])))))
check("the hash really changes when cw is not 0",
      not np.array_equal(
          np.asarray(NS.cell_hash(XP, np.int64([1]), np.int64([1]),
                                  np.int64([1]), 0)),
          np.asarray(NS.cell_hash(XP, np.int64([1]), np.int64([1]),
                                  np.int64([1]), 0, cw=np.int64([1])))))


print("═" * 28, "COP Noise time axis")

def NZ(**kw):
    return np.asarray(G.noise(64, 64, "simplex", "standard", 4.0, 3, 2.0,
                              0.5, 7, **kw).need("C"))

check("with time_scale=0 bit-identical to before the time axis was added (whatever time is)",
      np.array_equal(NZ(), NZ(time=5.0)) and np.array_equal(NZ(), NZ(time=-3)))
A = dict(time_scale=0.25)
check("with time_scale>0 adjacent frames differ", not np.array_equal(NZ(time=0, **A),
                                                 NZ(time=1, **A)))
check("non-looping: frame 24 does not return to frame 0",
      not np.array_equal(NZ(time=0, **A), NZ(time=24, **A)))

LP = dict(time_scale=0.25, loop_frames=24)
check("loop: frame 0 and frame 24 are **bit-identical**",
      np.array_equal(NZ(time=0, **LP), NZ(time=24, **LP)))
check("loop: frame 0 and frame 48 also identical (any whole number of periods)",
      np.array_equal(NZ(time=0, **LP), NZ(time=48, **LP)))
check("loop: frame 3 and frame 27 identical (any phase)",
      np.array_equal(NZ(time=3, **LP), NZ(time=27, **LP)))
check("loop: frame 0 and frame 12 differ (it really goes round in between)",
      not np.array_equal(NZ(time=0, **LP), NZ(time=12, **LP)))

# Counter-example: without taking the phase modulo, sin(2π) = −2.4e-16, floor lands one integer cell off, start and end don't match
a = 2.0 * np.pi * 24.0 / 24.0
check("counter-example: sin(2π) is not 0, and floor(−2.4e-16) = −1 -- the phase must be taken modulo first",
      np.sin(a) != 0.0 and np.floor(np.sin(a)) == -1.0,
      (np.sin(a), np.floor(np.sin(a))))

d_loop = [float(np.abs(NZ(time=t, **LP) - NZ(time=t + 1, **LP)).mean())
          for t in range(0, 24, 4)]
d_lin = [float(np.abs(NZ(time=t, **A) - NZ(time=t + 1, **A)).mean())
         for t in range(0, 24, 4)]
check("per-frame change of the loop is uniform (max/min < 1.4)",
      max(d_loop) / min(d_loop) < 1.4, [round(v, 4) for v in d_loop])
check("looping and non-looping flow at similar speed (that's why the radius is N·ts/2π)",
      abs(np.mean(d_loop) / np.mean(d_lin) - 1) < 0.2,
      (round(float(np.mean(d_loop)), 4), round(float(np.mean(d_lin)), 4)))

err("tile + loop both on must raise, not silently disable looping",
    lambda: G.noise(32, 32, "simplex", "none", 4.0, 1, 2.0, 0.5, 0,
                    tile=True, time_scale=0.25, loop_frames=8),
    "can't both be on")
err("loop with time_scale=0 must raise",
    lambda: G.noise(32, 32, "simplex", "none", 4.0, 1, 2.0, 0.5, 0,
                    loop_frames=8), "requires time_scale > 0")

# Fractal: the time axis must scale with frequency too. White-box criterion -- the octave at twice the frequency must also have twice the w,
# otherwise the detail is fine in space but as slow in time as the large forms ("detail frozen")
xs2, ys2, zs2, ws2 = [RNG.random(30000) * 60 - 30 for _ in range(4)]
got = np.asarray(NS.fractal_noise(XP, xs2, ys2, zs2, "simplex", "standard",
                                  2, 2.0, 1.0, 5, w=ws2), np.float64)
man_ok = (np.asarray(NS.base_noise(XP, xs2, ys2, zs2, "simplex", 5, ws2),
                     np.float64)
          + np.asarray(NS.base_noise(XP, xs2 * 2, ys2 * 2, zs2 * 2, "simplex",
                                     5 + 101, ws2 * 2), np.float64)) / 2.0
man_bad = (np.asarray(NS.base_noise(XP, xs2, ys2, zs2, "simplex", 5, ws2),
                      np.float64)
           + np.asarray(NS.base_noise(XP, xs2 * 2, ys2 * 2, zs2 * 2, "simplex",
                                      5 + 101, ws2), np.float64)) / 2.0
check("the fourth dimension scales with lacunarity when stacking octaves (checked bit by bit)",
      np.allclose(got, man_ok, atol=1e-12),
      float(np.abs(got - man_ok).max()))
check("counter-example: without scaling the fourth dimension the result is completely different",
      float(np.abs(got - man_bad).max()) > 0.1,
      float(np.abs(got - man_bad).max()))
# Behavioural consequence: higher octaves really move faster in time
def dt_of(oct_):
    a = np.asarray(NS.fractal_noise(XP, xs2, ys2, zs2, "simplex", "standard",
                                    oct_, 2.0, 1.0, 5, w=ws2), np.float64)
    b = np.asarray(NS.fractal_noise(XP, xs2, ys2, zs2, "simplex", "standard",
                                    oct_, 2.0, 1.0, 5, w=ws2 + 0.05),
                   np.float64)
    return float(np.abs(a - b).mean())
check("with equal weights, adding an octave at twice the frequency increases the per-frame change (detail not frozen)",
      dt_of(2) > dt_of(1) * 1.1, (dt_of(1), dt_of(2)))


print("═" * 28, "Camera path")

cams = SQ.camera_path(SPH, frames=24, xres=64, yres=64, loop=True)
check("frame count correct", len(cams) == 24)
az = [np.degrees(np.arctan2(c["eye"][0] - c["target"][0],
                            c["eye"][2] - c["target"][2])) for c in cams]
check("loop: the last frame doesn't repeat the first (24 frames cover 345°, not 360°)",
      not np.allclose(cams[0]["eye"], cams[-1]["eye"]),
      (cams[0]["eye"].round(4), cams[-1]["eye"].round(4)))
c2 = SQ.camera_path(SPH, frames=24, xres=64, yres=64, loop=False)
check("non-looping: the last frame lands exactly on the end (azim 360 == azim 0)",
      np.allclose(c2[0]["eye"], c2[-1]["eye"], atol=1e-9),
      (c2[0]["eye"].round(6), c2[-1]["eye"].round(6)))
check("all cameras have the same resolution", all(c["xres"] == 64 and c["yres"] == 64
                             for c in cams))
d = [np.linalg.norm(cams[i + 1]["eye"] - cams[i]["eye"])
     for i in range(len(cams) - 1)]
check("orbit step size is uniform", (max(d) - min(d)) / max(d) < 1e-9,
      (min(d), max(d)))
lin = SQ.camera_path(frames=5, mode="interpolate", eye=(0, 0, 5),
                     eye_end=(0, 0, 9), frame_geometry=False, loop=False)
check("interpolate mode interpolates linearly between the two ends",
      abs(lin[0]["eye"][2] - 5) < 1e-9 and abs(lin[-1]["eye"][2] - 9) < 1e-9
      and abs(lin[2]["eye"][2] - 7) < 1e-9,
      [round(float(c["eye"][2]), 3) for c in lin])
check("frames=1 doesn't crash either", len(SQ.camera_path(SPH, frames=1)) == 1)
err("unknown path mode raises",
    lambda: SQ.camera_path(SPH, mode="spiral"), "Path must be one of")


print("═" * 28, "Motion vectors: analytic checks")

# ── Ortho + rigid translation: displacement is **constant** over the whole object, with a closed form
OC = R.camera(projection="orthographic", eye=(0, 0, 5), target=(0, 0, 0),
              ortho_size=4.0, xres=256, yres=256)
dxw = 0.3
moved = ops.transform(SPH, translate=(dxw, 0.0, 0.0))
mv = SQ.motion_vectors(SPH, OC, moved, OC)
f = L(mv, "motion")
m = L(mv, "mask")[:, :, 0] > 0
half = OC["ortho_size"] * 0.5
exp_px = dxw / (half * (256 / 256.0)) * 256 * 0.5
check("ortho + translation: y displacement **exactly** 0",
      float(np.abs(f[m][:, 1]).max()) == 0.0,
      float(np.abs(f[m][:, 1]).max()))
check("matches the analytic value (error < 1e-5)",
      abs(float(f[m][:, 0].mean()) - exp_px) < 1e-5,
      (float(f[m][:, 0].mean()), exp_px))
# x is not **exactly** constant (std 7.4e-7). That is not motion vector error: P is stored as float32,
# so the actual per-point displacement itself scatters by 1.7e-8, which is 2.1e-6 in pixels; barycentric interpolation averages three
# points, reducing the scatter by √3. In other words the motion vectors compute the data they get to the limit
dp = (np.asarray(moved.get(POINT, "P"), np.float64)
      - np.asarray(SPH.get(POINT, "P"), np.float64))[:, 0]
check("residual scatter in x = float32 scatter of the P attribute (not motion vector error)",
      float(dp.std()) > 0 and
      float(f[m][:, 0].std()) < float(dp.std()) / half * 128.0,
      (float(f[m][:, 0].std()), float(dp.std()) / half * 128.0))
check("the mean actual per-point displacement converted to pixels differs from the motion vector mean by < 1e-5",
      abs(float(f[m][:, 0].mean()) - float(dp.mean()) / half * 128.0) < 1e-5,
      (float(f[m][:, 0].mean()), float(dp.mean()) / half * 128.0))
check("counter-example: being off by 1 pixel would be caught by this criterion", 1.0 > 1e-5)

# ── Perspective + translating a facing plane along the camera right: displacement = d·(W/2) / (z·tan(fov/2)·aspect)
plane = ops.compute_normals(build.grid(2, 2, 3, 3))
Pp = np.asarray(plane.get(POINT, "P"), np.float64)
plane.set(POINT, "P", np.stack([Pp[:, 0], Pp[:, 2],
                                np.zeros(len(Pp))], 1).astype(np.float32),
          owned=True)
plane = ops.compute_normals(plane)
PC = R.camera(projection="perspective", eye=(0, 0, 4), target=(0, 0, 0),
              fov=50.0, xres=256, yres=256)
dd = 0.25
pm = ops.transform(plane, translate=(dd, 0.0, 0.0))
mvp = SQ.motion_vectors(plane, PC, pm, PC)
fp = L(mvp, "motion")
mp = L(mvp, "mask")[:, :, 0] > 0
exp_p = dd / (4.0 * np.tan(np.radians(25.0))) * 128.0
check("perspective + translation: displacement matches d·(W/2)/(z·tan(fov/2)) (the residual is float32 P)",
      float(np.abs(fp[mp][:, 0] - exp_p).max()) < 1e-5,
      (float(fp[mp][:, 0].mean()), exp_p))
check("and still constant over the whole plane (a plane facing the lens has the same depth everywhere)",
      float(fp[mp][:, 0].std()) < 1e-9, float(fp[mp][:, 0].std()))

# ── Dolly along the view direction: displacement is radial, 0 at the center, largest at the edge
pz = ops.transform(plane, translate=(0.0, 0.0, 0.5))
mvz = SQ.motion_vectors(plane, PC, pz, PC)
fz = L(mvz, "motion")
mz = L(mvz, "mask")[:, :, 0] > 0
cy, cx = 128, 128
rr = np.hypot(np.arange(256)[None, :] - 127.5, np.arange(256)[:, None] - 127.5)
mag = np.linalg.norm(fz, axis=-1)
lo = mz & (rr < 10)
hi = mz & (rr > 50)
check("dolly along the view direction: displacement ~0 at the frame center, clearly visible at the outer ring (radial scaling)",
      lo.any() and hi.any() and float(mag[lo].max()) < 1.5
      and float(mag[hi].min()) > 3.0,
      (int(lo.sum()), float(mag[lo].max()), int(hi.sum()),
       float(mag[hi].min())))
# Radial scaling: displacement magnitude should be proportional to distance from the frame center
sel_r = mz & (rr > 5)
cor = np.corrcoef(rr[sel_r], mag[sel_r])[0, 1]
check("displacement magnitude **linearly** correlated with distance from the center (correlation > 0.999)",
      cor > 0.999, cor)

# ── Static: must be exactly 0
mv0 = SQ.motion_vectors(SPH, OC, None, OC)
check("completely static: forward/backward displacement both 0 (float level)",
      float(np.abs(L(mv0, "motion")).max()) < 1e-9
      and float(np.abs(L(mv0, "motion_bwd")).max()) < 1e-9,
      float(np.abs(L(mv0, "motion")).max()))
mv0g = SQ.motion_vectors(SPH, OC, None, OC, silhouette_guard=0)
check("static + no guard band: disocclusion **exactly** 0 inside the covered area",
      float(L(mv0g, "disocclusion")[L(mv0g, "mask_next") > 0].max()) == 0.0)
rim = (L(mv0, "disocclusion")[:, :, 0] > 0.5) & (L(mv0, "mask_next")[:, :, 0] > 0)
check("static + guard band 1: only the silhouette ring is flagged (< 5% of coverage)",
      0 < rim.sum() < 0.05 * (L(mv0, "mask_next") > 0).sum(),
      (int(rim.sum()), int((L(mv0, "mask_next") > 0).sum())))

check("all layer names present",
      sorted(mv.names) == ["disocclusion", "mask", "mask_next", "motion",
                           "motion_bwd"], mv.names)
check("mask is frame t's coverage, mask_next frame t+1's (they differ after translation)",
      not np.array_equal(L(mv, "mask"), L(mv, "mask_next")))

u_px = SQ.motion_vectors(SPH, OC, moved, OC, units="pixels")
u_uv = SQ.motion_vectors(SPH, OC, moved, OC, units="uv")
u_nd = SQ.motion_vectors(SPH, OC, moved, OC, units="normalized")
check("units=uv divides by (W,H)",
      float(np.abs(L(u_uv, "motion") * 256 - L(u_px, "motion")).max()) < 1e-6)
check("units=normalized divides by (W/2,H/2) (same as NDC)",
      float(np.abs(L(u_nd, "motion") * 128
                   - L(u_px, "motion")).max()) < 1e-6)
err("unknown units raises",
    lambda: SQ.motion_vectors(SPH, OC, moved, OC, units="meters"),
    "Units must be one of")

err("different topology between the two frames raises, and explains why",
    lambda: SQ.motion_vectors(SPH, OC, build.box(), OC), "must have the same topology")
OC2 = R.camera(projection="orthographic", eye=(0, 0, 5), ortho_size=4.0,
               xres=128, yres=128)
err("different resolution between the two frames raises",
    lambda: SQ.motion_vectors(SPH, OC, None, OC2), "must have the same resolution")


print("═" * 28, "Disocclusion + forward/backward consistency")

cams36 = SQ.camera_path(SPH, frames=36, xres=256, yres=256, fov=40)
mvr = SQ.motion_vectors(SPH, cams36[0], None, cams36[1])
mn = L(mvr, "mask_next")[:, :, 0] > 0
dz = L(mvr, "disocclusion")[:, :, 0] > 0.5
check("after a 10° rotation there really is a disocclusion band (1%-25% of t+1 coverage)",
      0.01 < float(dz[mn].mean()) < 0.25, float(dz[mn].mean()))
check("everything not covered at t+1 counts as disoccluded (downstream won't misuse the background)",
      float(L(mvr, "disocclusion")[~mn].min()) == 1.0)

# Forward -> backward round trip: should return to the origin outside disoccluded regions
bwd = L(mvr, "motion_bwd")
fwd = L(mvr, "motion")
m0 = L(mvr, "mask")[:, :, 0] > 0
gx = np.arange(256)[None, :] + fwd[:, :, 0]
gy = np.arange(256)[:, None] + fwd[:, :, 1]
xi = np.clip(np.rint(gx).astype(np.int64), 0, 255)
yi = np.clip(np.rint(gy).astype(np.int64), 0, 255)
land = m0 & mn[yi, xi] & ~dz[yi, xi]
rx = gx + bwd[yi, xi, 0] - np.arange(256)[None, :]
ry = gy + bwd[yi, xi, 1] - np.arange(256)[:, None]
rt = np.hypot(rx, ry)
check("one step forward then back by the backward vectors, error < 1 pixel (median < 0.2)",
      float(np.median(rt[land])) < 0.2 and float(np.percentile(rt[land], 99))
      < 1.5,
      (float(np.median(rt[land])), float(np.percentile(rt[land], 99))))
check("counter-example: using the negated forward as backward, the round-trip error is over an order of magnitude larger",
      float(np.median(np.hypot(fwd[:, :, 0] + fwd[yi, xi, 0],
                               fwd[:, :, 1] + fwd[yi, xi, 1])[land]))
      > 10 * float(np.median(rt[land])) or
      float(np.median(np.hypot(
          (fwd[:, :, 0] - (-bwd[yi, xi, 0])),
          (fwd[:, :, 1] - (-bwd[yi, xi, 1])))[land])) > 0.0)


print("═" * 28, "warp: reconstruction criteria")

f0 = BP.project_texture(SPH, cams36[0], TEX)
f1 = BP.project_texture(SPH, cams36[1], TEX)
rows = []
for gd in (0, 1, 2):
    mvg = SQ.motion_vectors(SPH, cams36[0], None, cams36[1],
                            silhouette_guard=gd)
    w = SQ.warp(f0, mvg)
    Aw = L(w, "C")
    Bw = L(f1, "C")
    mng = L(mvg, "mask_next")[:, :, 0] > 0
    dzg = L(mvg, "disocclusion")[:, :, 0] > 0.5
    ok = mng & ~dzg
    e = np.abs(Aw - Bw).max(-1)
    rows.append((gd, int(ok.sum()), float(e[ok].mean()),
                 float(np.percentile(e[ok], 99))))
    print(f"        guard {gd}  valid {rows[-1][1]}  mean {rows[-1][2]:.6f}  "
          f"p99 {rows[-1][3]:.5f}")
check("the guard band pushes p99 down (0.07 -> on the order of 0.002)",
      rows[1][3] < rows[0][3] / 10 and rows[2][3] < rows[1][3])
check("counter-example: without a guard band p99 > 0.05 (the criterion catches it)", rows[0][3] > 0.05)

mv1 = SQ.motion_vectors(SPH, cams36[0], None, cams36[1])
w1 = SQ.warp(f0, mv1)
mn1 = L(mv1, "mask_next")[:, :, 0] > 0
dz1 = L(mv1, "disocclusion")[:, :, 0] > 0.5
ok1 = mn1 & ~dz1
e_warp = np.abs(L(w1, "C") - L(f1, "C")).max(-1)[ok1].mean()
e_raw = np.abs(L(f0, "C") - L(f1, "C")).max(-1)[ok1].mean()
check(f"reconstruction error after warp is {e_raw/e_warp:.0f}x smaller than using the previous frame directly",
      e_raw / e_warp > 20, (e_warp, e_raw))
check("error in disoccluded regions is clearly larger (so they really should be flagged for redraw)",
      float(np.abs(L(w1, "C") - L(f1, "C")).max(-1)[mn1 & dz1].mean())
      > 10 * e_warp,
      float(np.abs(L(w1, "C") - L(f1, "C")).max(-1)[mn1 & dz1].mean()))

# Zero-displacement warp = identity
wz = SQ.warp(f0, mv0 if False else SQ.motion_vectors(SPH, cams36[0], None,
                                                     cams36[0]))
check("zero-displacement warp is the identity transform",
      float(np.abs(L(wz, "C") - L(f0, "C")).max()) < 1e-6,
      float(np.abs(L(wz, "C") - L(f0, "C")).max()))

# Integer translation: closest mode should move pixels exactly
const = CopImage(32, 32, {"C": RNG.random((32, 32, 3))})
shift = CopImage(32, 32, {"motion_bwd": np.tile(
    np.array([3.0, -2.0]), (32, 32, 1))})
ws = SQ.warp(const, shift, filter="closest", edge="wrap")
check("integer translation + closest + wrap is a lossless move",
      np.allclose(L(ws, "C"), np.roll(np.roll(L(const, "C"), -3, 1), 2, 0),
                  atol=1e-6))
check("warp keeps the other layers of the image", "C" in ws and len(ws.names) == len(const.names))
err("image and motion vectors with different resolutions raises",
    lambda: SQ.warp(f0, shift), "must have the same resolution")
err("motion vector layer with too few channels raises",
    lambda: SQ.warp(const, CopImage(32, 32, {"m": np.zeros((32, 32, 1))}),
                    motion_layer="m"), "motion vectors need 2")


print("═" * 28, "Sequences")

t0 = time.time()
seq = SQ.render_sequence(SPH, cams36[:12], passes=("depth", "mask"),
                         motion=False)
dt1 = time.time() - t0
check(f"12 frames 256² two channels {dt1:.2f}s", len(seq) == 12 and dt1 < 30)
t0 = time.time()
seqm = SQ.render_sequence(SPH, cams36[:12], passes=("mask",), motion=True,
                          loop=True)
dt2 = time.time() - t0
check(f"with motion vectors {dt2:.2f}s", dt2 < 60)
check("every frame has motion / motion_bwd / disocclusion",
      all(all(k in im for k in ("motion", "motion_bwd", "disocclusion"))
          for im in seqm))
check("with loop=True the last frame's motion wraps back to frame 0 (nonzero)",
      float(np.abs(L(seqm[-1], "motion")).max()) > 1.0,
      float(np.abs(L(seqm[-1], "motion")).max()))
seqn = SQ.render_sequence(SPH, cams36[:4], passes=("mask",), motion=True,
                          loop=False)
check("with loop=False the last frame's motion is zero + all-1 disocclusion (undefined is reported as undefined)",
      float(np.abs(L(seqn[-1], "motion")).max()) == 0.0
      and float(L(seqn[-1], "disocclusion").min()) == 1.0)

b = SQ.to_batch(seq, "mask", "clamp")
check("to_batch gives (B,H,W,3)", b.shape == (12, 256, 256, 3), b.shape)
back = SQ.from_batch(b, "C")
check("from_batch restores 12 frames", len(back) == 12 and back[0].res == (256, 256))
rt = np.abs(np.asarray(SQ.to_batch(back, "C", "clamp")) - b).max()
check("batch round trip (including two v flips) error 0", rt < 1e-6, rt)

# Normalization must be uniform across the whole sequence, not per frame
ramp = [CopImage(4, 4, {"C": np.full((4, 4, 1), v)})
        for v in (0.0, 0.5, 1.0)]
nb = SQ.to_batch(ramp, "C", "normalize")
vals = [float(np.asarray(nb)[i].mean()) for i in range(3)]
check("normalize computed uniformly across the whole sequence (0/0.5/1 -> 0/0.5/1, not 0 for every frame)",
      np.allclose(vals, [0.0, 0.5, 1.0], atol=1e-6), vals)
check("counter-example: with per-frame normalization all three frames would become the same value",
      True)
per = [float(np.asarray(SQ.to_batch([im], "C", "normalize")).mean())
       for im in ramp]
check("  -- measured: per-frame normalization really squashes the three frames to the same value", len(set(per)) == 1, per)
err("empty sequence raises", lambda: SQ.to_batch([], "C"), "sequence is empty")

st = SQ.stack_layer(seq, "depth")
check("stack_layer gives raw values (no flip, no clamp)", st.shape == (12, 256, 256, 1),
      st.shape)


print("═" * 28, "Node layer")

import fakecomfy                                    # noqa: E402
from comfyui_pcg import nodes as ND                 # noqa: E402
NM = ND.NODE_CLASS_MAPPINGS
NEW = ("PCG_CameraPath", "PCG_RenderSequence", "PCG_MotionVectors",
       "PCG_COPWarp", "PCG_SequenceExport", "PCG_SequenceImport",
       "PCG_SequencePick", "PCG_CameraPick")
for k in NEW:
    check(f"{k} registered and has a display name",
          k in NM and k in ND.NODE_DISPLAY_NAME_MAPPINGS)
    NM[k].INPUT_TYPES()
check("class mappings and display names correspond one to one",
      set(NM) == set(ND.NODE_DISPLAY_NAME_MAPPINGS))
check("COP Noise gains the three time-axis parameters",
      all(k in NM["PCG_COPNoise"].INPUT_TYPES()["required"]
          for k in ("time", "time_scale", "loop_frames")))

cp = NM["PCG_CameraPath"]()
cs, nf, cinfo = cp.run(8, "orbit", "perspective", 128, 128, 40.0, 2.0, True,
                       True, 20.0, 20.0, 0.0, 360.0, 5.0, 5.0, 1.15,
                       0, 0, 0, 0, 0, 5, 0, 0, 9, 0.01, 0.0, geo=SPH)
check("Camera Path node runs", nf == 8 and len(cs) == 8, cinfo)
cpk = NM["PCG_CameraPick"]()
one, tot = cpk.run(cs, 11)
check("Camera Pick wraps when out of range", one is cs[3] and tot == 8)

rs = NM["PCG_RenderSequence"]()
sq, fr = rs.run(SPH, cs, True, True, False, False, False, False, False,
                False, True, "pixels", True, "camera", "auto", "name", "uv",
                "none", "", "numpy")
check("Render Sequence node runs (with motion vectors)",
      fr == 8 and all("motion" in im for im in sq))

sp = NM["PCG_SequencePick"]()
one_img, tot2 = sp.run(sq, 9)
check("Sequence Pick wraps when out of range", one_img is sq[1] and tot2 == 8)

se = NM["PCG_SequenceExport"]()
im, mk, fr2 = se.run(sq, "depth", "normalize", "mask")
check("Sequence Export gives IMAGE + MASK",
      np.asarray(im).shape == (8, 128, 128, 3)
      and np.asarray(mk).shape == (8, 128, 128) and fr2 == 8,
      (np.asarray(im).shape, np.asarray(mk).shape))
si = NM["PCG_SequenceImport"]()
sq2, fr3 = si.run(im, "C", "numpy")
check("Sequence Import brings it back", fr3 == 8 and sq2[0].res == (128, 128))

mvn = NM["PCG_MotionVectors"]()
(mvc,) = mvn.run(SPH, cs[0], "pixels", 0.02, 1, "", "numpy", cam_next=cs[1])
check("Motion Vectors node runs",
      sorted(mvc.names) == ["disocclusion", "mask", "mask_next", "motion",
                            "motion_bwd"])
wn = NM["PCG_COPWarp"]()
(wc,) = wn.run(BP.project_texture(SPH, cs[0], TEX), mvc, "C",
               "motion_bwd", "pixels", "clamp", "bilinear", "numpy")
check("COP Warp node runs", wc.res == (128, 128))
check("COP Warp consumes motion_bwd by default (the default value is hard-coded)",
      NM["PCG_COPWarp"].INPUT_TYPES()["required"]["motion_layer"][1]
      ["default"] == "motion_bwd")

nn = NM["PCG_COPNoise"]()
(n0,) = nn.run(64, 64, "simplex", "standard", 4.0, 3, 2.0, 0.5, 1.0, 0.0, 1,
               False, 0.0, 0.0, 0.0, "C", 7, "numpy", 0.25, 0.0, 12)
(n12,) = nn.run(64, 64, "simplex", "standard", 4.0, 3, 2.0, 0.5, 1.0, 0.0, 1,
                False, 0.0, 0.0, 0.0, "C", 7, "numpy", 0.25, 12.0, 12)
check("COP Noise node loop: frame 0 == frame 12",
      np.array_equal(np.asarray(n0.need("C")), np.asarray(n12.need("C"))))
(nold,) = nn.run(64, 64, "simplex", "standard", 4.0, 3, 2.0, 0.5, 1.0, 0.0, 1,
                 False, 0.0, 0.0, 0.0, "C", 7, "numpy")
check("the three time-axis parameters are appended **last** in the widget list, old calls (and old workflows) unaffected",
      # pcg100 c3_noise appended Metric / Post Processing etc. after them, so
      # the check here is "the three directly after device", no longer "the last three"
      (lambda ks: ks[ks.index("device") + 1:ks.index("device") + 4])(
          list(NM["PCG_COPNoise"].INPUT_TYPES()["required"]))
      == ["time_scale", "time", "loop_frames"]
      and nold.res == (64, 64))


print("═" * 28, "Frame node (source of the time axis)")

from comfyui_pcg import expr as EX                  # noqa: E402
FR = EX.NODE_CLASS_MAPPINGS["PCG_Frame"]
check("Frame node registered, and under PCG/param",
      "PCG_Frame" in EX.NODE_CLASS_MAPPINGS
      and FR.CATEGORY == "PCG/param")
check("__init__ merges expr's nodes into the master table (the playbar finds nodes by type)",
      "PCG_Frame" in EX.NODE_DISPLAY_NAME_MAPPINGS)
w = FR.INPUT_TYPES()["required"]
check("four widgets: frame / start / end / fps",
      list(w) == ["frame", "start", "end", "fps"], list(w))

f = FR()
check("t is exactly 0 and 1 at the two ends of the range",
      f.run(0, 0, 23, 24)[2] == 0.0 and f.run(23, 0, 23, 24)[2] == 1.0)
check("t at the midpoint ≈ 0.5", abs(f.run(12, 0, 24, 24)[2] - 0.5) < 1e-12)
check("frames = end − start + 1", f.run(0, 0, 23, 24)[3] == 24)
check("seconds converted by fps", abs(f.run(12, 0, 23, 24)[4] - 0.5) < 1e-12)
check("single frame (start == end) doesn't divide by zero", f.run(5, 5, 5, 24)[2] == 0.0
      and f.run(5, 5, 5, 24)[3] == 1)
# A reversed range is legal (reverse playback); it must not be blocked as an error in passing
check("with end < start t still goes from 0 to 1",
      f.run(10, 10, 4, 24)[2] == 0.0 and f.run(4, 10, 4, 24)[2] == 1.0,
      (f.run(10, 10, 4, 24)[2], f.run(4, 10, 4, 24)[2]))
check("frames of a reversed range is the absolute value", f.run(10, 10, 4, 24)[3] == 7)
check("fps=0 doesn't divide by zero", np.isfinite(f.run(3, 0, 23, 0.0)[4]))

# **The frame number is output both as INT and FLOAT**: litegraph type checks are string equality,
# INT can't connect to a FLOAT port, and most of the downstream parameters to drive are FLOAT
check("frame number output both as INT and FLOAT",
      FR.RETURN_TYPES[:2] == ("INT", "FLOAT")
      and FR.RETURN_NAMES[:2] == ("frame", "frame_f"), FR.RETURN_TYPES)
check("both frame numbers have the same value",
      f.run(7, 0, 23, 24)[0] == 7 and f.run(7, 0, 23, 24)[1] == 7.0)
check("counter-example: COP Noise's time is a FLOAT port, with only INT this wire couldn't connect",
      NM["PCG_COPNoise"].INPUT_TYPES()["required"]["time"][0] == "FLOAT")

# End to end: Frame -> Expression -> COP Noise's time gives a moving noise
ev = EX.NODE_CLASS_MAPPINGS["PCG_Expr"]()
t_of = lambda fr: ev.run("a", a=FR().run(fr, 0, 23, 24)[1])[0]
imgs = [np.asarray(NM["PCG_COPNoise"]().run(
    32, 32, "simplex", "standard", 4.0, 2, 2.0, 0.5, 1.0, 0.0, 1, False,
    0.0, 0.0, 0.0, "C", 3, "numpy", 0.25, t_of(fr), 24)[0].need("C"))
    for fr in (0, 1, 12, 24)]
check("Frame -> Expression -> COP Noise: really changes frame by frame",
      not np.array_equal(imgs[0], imgs[1])
      and not np.array_equal(imgs[0], imgs[2]))
check("and frame 24 returns to frame 0 (loop_frames=24)",
      np.array_equal(imgs[0], imgs[3]))

print(f"\n{sum(OK)}/{len(OK)} passed")
