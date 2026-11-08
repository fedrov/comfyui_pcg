"""
Deform (Twist / Bend / Taper / Squash / Shear), Soft Transform, Spherify,
Torus, Ends.

Almost every criterion in this batch is an **analytic closed form**: deformations are elementary per-point functions, so whatever you want to check
you can work out the right answer by hand, no "compare against the previous version". So hardly any tolerance below is picked out of thin air.

At the end there is also a section checking the **build.py primitives**. That isn't part of this batch; it plugs a hole: when the sandbox was
reclaimed 23 old suites were lost, and this batch touched build.py (adding Torus), which happened to fall in an area with no regression
protection.
"""
import os
import sys
# Package root: first search upward from this file's location, then fall back to the old sandbox path.
# These suites are now the **only** copy (the sandbox gets reclaimed), so paths can't be hard-coded any more
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM
from comfyui_pcg.geo import (build, deform as D, ends as E, ops as O,
                             measure as M)

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


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def same(a, b):
    return np.array_equal(np.asarray(a.get(POINT, "P")),
                          np.asarray(b.get(POINT, "P")))


def ang_between(a, b):
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return np.degrees(np.arccos(np.clip((a * b).sum(1), -1, 1)))


TUBE = build.tube(radius1=1.0, radius2=1.0, height=4.0, cols=24, rows=9)
P0 = P_(TUBE)
T = (P0[:, 1] - P0[:, 1].min()) / (P0[:, 1].max() - P0[:, 1].min())


# ══════════════════════════════════════════════════════════════════ Twist
print("═" * 28, "Twist")

tw = D.deform(TUBE, "twist", axis="y", angle=90.0)
P1 = P_(tw)
check("distance to the axis completely unchanged (as a rotation should be)",
      float(np.abs(np.hypot(P1[:, 0], P1[:, 2])
                   - np.hypot(P0[:, 0], P0[:, 2])).max()) < 1e-6,
      f"{float(np.abs(np.hypot(P1[:, 0], P1[:, 2]) - np.hypot(P0[:, 0], P0[:, 2])).max()):.2e}")
check("axial coordinate untouched **bit for bit**",
      np.array_equal(P1[:, 1], P0[:, 1]))
a0 = np.arctan2(P0[:, 2], P0[:, 0])
a1 = np.arctan2(P1[:, 2], P1[:, 0])
da = (a1 - a0 + np.pi) % (2 * np.pi) - np.pi
# atan2(z,x) is a **left-handed** angle about +Y, so a right-handed positive rotation decreases it -- the first time
# the test was written this sign was backwards, and the reported "error" was exactly π
check("rotation angle is exactly −angle×t (atan2(z,x) is a left-handed angle, opposite sign)",
      float(np.abs(da + np.radians(90.0) * T).max()) < 1e-6,
      f"{float(np.abs(da + np.radians(90.0) * T).max()):.2e}")
one = build.points_from_array(np.array([[1.0, 0, 0], [1.0, 1.0, 0]]))
r = D.deform(one, "twist", axis="y", angle=90.0, use_range=True,
             range_start=0.0, range_end=1.0)
check("right-hand rule: rotating 90° about +Y, (1,1,0) -> (0,1,−1)",
      np.allclose(P_(r)[1], [0, 1, -1], atol=1e-6), np.round(P_(r)[1], 6))
check("angle=0 is the **bit-for-bit** identity", same(D.deform(TUBE, "twist", angle=0.0),
                                    TUBE))
check("negative control: at angle=1e-9 it's no longer bit-identical (proves the previous check isn't because nothing was done)",
      not same(D.deform(TUBE, "twist", angle=1e-9), TUBE))


# ═══════════════════════════════════════════════════════════════════ Bend
print("═" * 28, "Bend")

L, N = 4.0, 41
s = np.linspace(0, L, N)
LINE = build.points_from_array(np.stack([np.zeros(N), s, np.zeros(N)], -1))
for deg in (180.0, 90.0, 30.0, 1.0, 1e-3, 1e-6):
    th = np.radians(deg)
    R = L / th
    b = D.deform(LINE, "bend", axis="y", angle=deg, use_range=True,
                 range_start=0.0, range_end=L)
    Q = P_(b)
    rad = np.linalg.norm(Q - np.array([R, 0, 0]), axis=1)
    end = np.array([R * (1 - np.cos(th)), R * np.sin(th), 0.0])
    check(f"θ={deg:<7g}° every point is at distance R from the center, endpoints also match the closed form",
          float(np.abs(rad - R).max()) < 2e-7
          and float(np.linalg.norm(Q[-1] - end)) < 2e-7,
          f"radius error {float(np.abs(rad - R).max()):.2e}")
check("at θ=180° the endpoint lands exactly at (2L/π, 0, 0)",
      np.allclose(P_(D.deform(LINE, "bend", axis="y", angle=180.0,
                              use_range=True, range_start=0.0,
                              range_end=L))[-1],
                  [2 * L / np.pi, 0, 0], atol=1e-6))
check("θ=0 is the **bit-for-bit** identity (the sinc form gives that naturally, no special case needed)",
      same(D.deform(LINE, "bend", angle=0.0), LINE))

# Negative control: catastrophic cancellation of the textbook formula at small angles
naive_err = {}
for deg in (1e-2, 1e-4, 1e-6):
    th = np.radians(deg)
    R = L / th
    phi = th * 1.0
    naive = R - R * np.cos(phi)
    stable = L * 1.0 * (th * 0.5) * np.sinc(phi / (2 * np.pi)) ** 2
    naive_err[deg] = abs(naive - stable) / abs(stable)
check("negative control: relative error of `R − R·cos φ` at θ=1e-6° > 10%",
      naive_err[1e-6] > 0.1, f"{naive_err[1e-6]:.3f}")
check("  θ=1e-4° already has relative error on the order of 1e-5",
      1e-6 < naive_err[1e-4] < 1e-3, f"{naive_err[1e-4]:.2e}")
check("  at θ=1e-2° the two formulas can't be told apart yet (so the problem really is only at small angles)",
      naive_err[1e-2] < 1e-8, f"{naive_err[1e-2]:.2e}")

# Outside the capture region it must be carried along **rigidly**, not by clamping t
s2 = np.linspace(0, 2 * L, 2 * N - 1)
LINE2 = build.points_from_array(
    np.stack([np.zeros(len(s2)), s2, np.zeros(len(s2))], -1))
b2 = P_(D.deform(LINE2, "bend", axis="y", angle=90.0, use_range=True,
                 range_start=0.0, range_end=L))
tail = b2[s2 >= L]
seg = np.linalg.norm(np.diff(tail, axis=0), axis=1)
check("the part outside the region is still **straight** (adjacent segment lengths identical)",
      float(seg.max() - seg.min()) < 1e-6, f"{float(seg.max() - seg.min()):.2e}")
check("  and segment lengths unchanged (= original sample spacing)",
      abs(float(seg.mean()) - (s2[1] - s2[0])) < 1e-6,
      f"{float(seg.mean()):.6f} vs {s2[1] - s2[0]:.6f}")
check("  straight-line distance from the tail to the end of the region = its original length (not squashed)",
      abs(float(np.linalg.norm(b2[-1] - b2[s2 >= L][0])) - L) < 1e-5,
      f"{float(np.linalg.norm(b2[-1] - b2[s2 >= L][0])):.6f} vs {L}")
check("negative control: clamping t instead of rigid extension collapses the whole tail to one point",
      float(np.linalg.norm(b2[-1] - b2[s2 >= L][0])) > L * 0.99)


# ═══════════════════════════════════════════════════════ Taper / Shear
print("═" * 28, "Taper / Shear")

for am in (0.25, 2.0):
    Q = P_(D.deform(TUBE, "taper", axis="y", amount=am))
    k = 1.0 + (am - 1.0) * T
    check(f"taper {am}: lateral radius multiplied by exactly lerp(1, {am}, t)",
          float(np.abs(np.hypot(Q[:, 0], Q[:, 2])
                       - np.hypot(P0[:, 0], P0[:, 2]) * k).max()) < 1e-6)
    check(f"  axial untouched **bit for bit**", np.array_equal(Q[:, 1], P0[:, 1]))
Q = P_(D.deform(TUBE, "shear", axis="y", shear_b=1.5, shear_c=-0.5))
check("shear: axial untouched **bit for bit**", np.array_equal(Q[:, 1], P0[:, 1]))
check("  displacement along the second direction = shear_b × t",
      float(np.abs((Q[:, 0] - P0[:, 0]) - 1.5 * T).max()) < 1e-6)
a_, b_, c_ = D._frame("y", (0, 1, 0))
check("  displacement along the third direction = shear_c × t, direction c = a×b (with axis=y c is **−z**)",
      float(np.abs((Q[:, 2] - P0[:, 2]) - (-0.5) * T * c_[2]).max()) < 1e-6,
      f"c = {np.round(c_, 6).tolist()}")
check("  the frame is right-handed (a×b = c, so a positive rotation about a turns b towards c)",
      np.allclose(np.cross(a_, b_), c_, atol=1e-12))
check("taper amount=1 is the bit-for-bit identity",
      same(D.deform(TUBE, "taper", amount=1.0), TUBE))
check("shear all 0 is the bit-for-bit identity",
      same(D.deform(TUBE, "shear", shear_b=0.0, shear_c=0.0), TUBE))


# ═════════════════════════════════════════════════════════════════ Squash
print("═" * 28, "Squash")

CAP = build.tube(radius1=1.0, radius2=1.0, height=4.0, cols=24, rows=9,
                 caps=True)


def vol(g):
    return float(abs(M.prim_volumes(g).sum()))


v0 = vol(CAP)
for am in (0.25, 0.5, 2.0, 4.0):
    q = D.deform(CAP, "squash", axis="y", amount=am)
    check(f"squash {am}: **volume preserved**",
          abs(vol(q) / v0 - 1) < 1e-6, f"relative change {abs(vol(q) / v0 - 1):.2e}")
Q = P_(D.deform(CAP, "squash", axis="y", amount=2.0))
C0 = P_(CAP)
check("  axial span exactly ×amount",
      abs((Q[:, 1].max() - Q[:, 1].min())
          / (C0[:, 1].max() - C0[:, 1].min()) - 2.0) < 1e-6)
check("  lateral exactly ×1/√amount",
      abs(float((np.hypot(Q[:, 0], Q[:, 2])
                 / np.maximum(np.hypot(C0[:, 0], C0[:, 2]), 1e-9)).max())
          - 1 / np.sqrt(2.0)) < 1e-6)
# Negative control: the version where the lateral scale ramps with t (that's how I wrote it the first time) is far off in volume
tt = (C0[:, 1] - C0[:, 1].min()) / (C0[:, 1].max() - C0[:, 1].min())
for am in (0.5, 2.0):
    perp_ramp = 1.0 + (1.0 / np.sqrt(am) - 1.0) * tt
    g2 = CAP.copy()
    g2.set(POINT, "P", np.stack([C0[:, 0] * perp_ramp,
                                 (C0[:, 1] - C0[:, 1].min()) * am
                                 + C0[:, 1].min(),
                                 C0[:, 2] * perp_ramp],
                                -1).astype(np.float32), owned=True)
    check(f"negative control: the lateral-ramp version is off by > 20% in volume at amount={am}",
          abs(vol(g2) / v0 - 1) > 0.2, f"{abs(vol(g2) / v0 - 1):.3f}")
check("squash amount=1 is the bit-for-bit identity",
      same(D.deform(CAP, "squash", amount=1.0), CAP))
err("squash amount<=0 errors",
    lambda: D.deform(CAP, "squash", amount=-1.0), "must be > 0")


# ═══════════════════════════════════════════════════════════════════ Normals
print("═" * 28, "Normals (finite-difference Jacobian)")

SM = O.compute_normals(build.tube(radius1=1.0, radius2=1.0, height=4.0,
                                  cols=32, rows=13),
                       add_to="point", cusp_angle=180.0)
PS = P_(SM)
N0 = np.asarray(SM.get(POINT, "N"), np.float64)
# The **recomputed** normals of the top and bottom rings are the wrong ones (boundary points only have faces on one side), so exclude them in the comparison
inner = ((PS[:, 1] > PS[:, 1].min() + 1e-6)
         & (PS[:, 1] < PS[:, 1].max() - 1e-6))
tol = {"twist": 0.01, "taper": 0.01, "bend": 0.2, "squash": 0.01}
for op, kw in (("twist", dict(angle=90.0)), ("taper", dict(amount=0.3)),
               ("bend", dict(angle=60.0)), ("squash", dict(amount=2.0))):
    d = D.deform(SM, op, axis="y", **kw)
    Nj = np.asarray(d.get(POINT, "N"), np.float64)
    Nr = np.asarray(O.compute_normals(d, add_to="point",
                                      cusp_angle=180.0).get(POINT, "N"),
                    np.float64)
    a = ang_between(Nj, Nr)[inner]
    check(f"[{op}] Jacobian normals == normals recomputed after the deformation",
          float(a.max()) < tol[op], f"max {float(a.max()):.4f}°")
check("normals still unit length",
      abs(float(np.linalg.norm(
          np.asarray(D.deform(SM, "taper", amount=0.3).get(POINT, "N"),
                     np.float64), axis=1).max()) - 1.0) < 1e-6)
# Negative control: missing the "inverse transpose" step
import comfyui_pcg.geo.deform as DD                              # noqa: E402
f = DD._deformer("taper", "y", (0, 1, 0), PS[:, 1].min(), PS[:, 1].max(),
                 {"amount": 0.3})
h = DD.JAC_EPS * float(np.linalg.norm(PS.max(0) - PS.min(0)))
base = f(PS)
J = np.stack([(f(PS + np.eye(3)[k] * h) - base) / h for k in range(3)], -1)
Jn = np.einsum("nij,nj->ni", J, N0)
Nr = np.asarray(O.compute_normals(D.deform(SM, "taper", amount=0.3),
                                  add_to="point",
                                  cusp_angle=180.0).get(POINT, "N"),
                np.float64)
check("negative control: with `J·n` (missing the inverse transpose) normals are off by almost 10°",
      float(ang_between(Jn, Nr)[inner].max()) > 5.0,
      f"{float(ang_between(Jn, Nr)[inner].max()):.3f}°")
check("with normals=none N is completely untouched",
      np.array_equal(np.asarray(D.deform(SM, "taper", amount=0.3,
                                         normals="none").get(POINT, "N")),
                     np.asarray(SM.get(POINT, "N"))))
check("geometry without N doesn't crash either",
      D.deform(LINE, "bend", angle=45.0).npoints == LINE.npoints)


# ═════════════════════════════════════════════════════════════ Frame / group
print("═" * 28, "Frame / group / errors")

up_par = D.deform(TUBE, "bend", axis="y", angle=45.0, up=(0, 1, 0))
check("when up is parallel to axis another one is picked automatically, no nan",
      bool(np.isfinite(P_(up_par)).all()))
check("  same with a zero up vector",
      bool(np.isfinite(P_(D.deform(TUBE, "bend", angle=45.0,
                                   up=(0, 0, 0))).all())))
check("with a different up, the bend direction really changes",
      not np.allclose(P_(D.deform(TUBE, "bend", angle=45.0, up=(1, 0, 0))),
                      P_(D.deform(TUBE, "bend", angle=45.0, up=(0, 0, 1)))))
for ax in D.AXES:
    q = D.deform(TUBE, "twist", axis=ax, angle=60.0)
    fixed = {"x": 0, "y": 1, "z": 2}[ax]
    check(f"with axis={ax} component {fixed} untouched bit for bit",
          np.array_equal(P_(q)[:, fixed], P0[:, fixed]))

g = TUBE.copy()
g.set_group(POINT, "top", P0[:, 1] > 0.0)
gq = P_(D.deform(g, "twist", group="top", angle=90.0))
check("points outside group not moved at all (bit for bit)",
      np.array_equal(gq[P0[:, 1] <= 0.0], P0[P0[:, 1] <= 0.0]))
check("points inside group moved", not np.array_equal(gq[P0[:, 1] > 0.0],
                                            P0[P0[:, 1] > 0.0]))
err("wrong op errors and lists the options", lambda: D.deform(TUBE, op="melt"),
    "Op must be one of")
err("wrong axis errors", lambda: D.deform(TUBE, axis="w"), "Axis must be one of")
err("wrong normals errors", lambda: D.deform(TUBE, normals="recompute"),
    "Normals must be one of")
check("empty geometry doesn't crash", D.deform(Geometry()).npoints == 0)
check("None doesn't crash", D.deform(None).npoints == 0)


# ═════════════════════════════════════════════════════════ Soft Transform
print("═" * 28, "Soft Transform")

GRID = build.grid(size_x=10, size_z=10, cols=41, rows=41)
GP = P_(GRID)
sel = np.linalg.norm(GP[:, [0, 2]], axis=1) < 0.3
GRID.set_group(POINT, "handle", sel)
st = D.soft_transform(GRID, "handle", rotate=(0, 90, 0), radius=4.0,
                      falloff_attrib="w")
SP = P_(st)
w = np.asarray(st.get(POINT, "w"), np.float64).ravel()
piv = GP[sel].mean(0)
d0 = np.linalg.norm(GP - piv, axis=1)
d1 = np.linalg.norm(SP - piv, axis=1)
ok = d0 > 1e-6
check("**rotation radius strictly preserved** (interpolate the parameters, not the result)",
      float(np.abs(d1[ok] / d0[ok] - 1).max()) < 1e-6,
      f"max relative change {float(np.abs(d1[ok] / d0[ok] - 1).max()):.2e}")
th = np.radians(90.0)
Mrot = np.array([[np.cos(th), 0, np.sin(th)], [0, 1, 0],
                 [-np.sin(th), 0, np.cos(th)]])
Pl = GP + ((Mrot @ (GP - piv).T).T + piv - GP) * w[:, None]
dl = np.linalg.norm(Pl - piv, axis=1)
mid = (w > 0.45) & (w < 0.55) & ok
check("negative control: `lerp(P, M·P, w)` eats ~29% of the radius at w≈0.5",
      float((1 - dl[mid] / d0[mid]).max()) > 0.25,
      f"{100 * float((1 - dl[mid] / d0[mid]).max()):.1f}%")

dh = np.linalg.norm(GP[:, None, :] - GP[sel][None, :, :], axis=-1).min(1)
check("weight = 1 inside the handle group", float(w[sel].min()) == 1.0)
check("weight = 0 for points farther than radius from the handle group", float(w[dh > 4.0].max()) == 0.0)
check("weight monotonically non-increasing with distance",
      bool(np.all(np.diff(w[np.argsort(dh)]) <= 1e-9)))
check("translate only: the handle group moved exactly by translate",
      np.allclose(P_(D.soft_transform(GRID, "handle", translate=(0, 2, 0),
                                      radius=4.0))[sel] - GP[sel],
                  [0, 2, 0], atol=1e-6))
check("identity parameters (no move, no rotate, no scale) are the bit-for-bit identity",
      same(D.soft_transform(GRID, "handle", radius=4.0), GRID))
# pcg90: empty Group = all points (Houdini's rule); it used to do nothing
check("no group given: all points are the handle, whole thing translated", np.allclose(
    P_(D.soft_transform(GRID, radius=4.0, translate=(0, 5, 0))) - GP, [0, 5, 0], atol=1e-6))

# euclidean leaks across gaps, connected doesn't -- the docs say so, verified here
A = build.grid(size_x=2, size_z=2, cols=9, rows=9, center=(-2.0, 0, 0))
B = build.grid(size_x=2, size_z=2, cols=9, rows=9, center=(2.0, 0, 0))
TWO = O.merge(A, B)
TP = P_(TWO)
TWO.set_group(POINT, "h", np.abs(TP[:, 0] + 2.0) < 0.3)
far = TP[:, 0] > 1.0
we, _ = D.soft_falloff(TWO, "h", radius=6.0, metric="euclidean")
wc, _ = D.soft_falloff(TWO, "h", radius=6.0, metric="distance")
check("euclidean: the other piece across a gap **gets moved too** (straight-line distance ignores gaps)",
      float(we[far].max()) > 0.05, f"max weight {float(we[far].max()):.3f}")
check("connected (distance): the other piece's weights are all 0 (can't walk there along edges)",
      float(wc[far].max()) == 0.0)
err("wrong metric errors", lambda: D.soft_falloff(GRID, "handle",
                                            metric="manhattan"),
    "Metric must be one of")


# ═══════════════════════════════════════════════════════════════ Spherify
print("═" * 28, "Spherify")

BOX = build.box(size=(2, 2, 2), divisions=(6, 6, 6))
BP = P_(BOX)
sp = D.spherify(BOX, amount=1.0)
C = BP.mean(0)
rr = np.linalg.norm(P_(sp) - C, axis=1)
check("amount=1: all points land exactly on the same sphere",
      float(rr.std()) < 1e-6, f"radius std {float(rr.std()):.2e}")
check("  radius = the **mean** of the original distances to the center",
      abs(float(rr.mean()) - float(np.linalg.norm(BP - C, axis=1).mean()))
      < 1e-5)
check("given radius is used when set",
      abs(float(np.linalg.norm(P_(D.spherify(BOX, amount=1.0, radius=3.0))
                               - C, axis=1).mean()) - 3.0) < 1e-5)
check("amount=0 is the **bit-for-bit** identity", same(D.spherify(BOX, amount=0.0), BOX))
check("amount=0.5 lands exactly halfway between the original position and the sphere",
      np.allclose(P_(D.spherify(BOX, amount=0.5)),
                  (BP + P_(sp)) / 2.0, atol=1e-5))
ctr = build.points_from_array(np.array([[0.0, 0, 0], [1.0, 0, 0]]))
check("a point exactly at the center has no direction and is left as is (not nan)",
      bool(np.isfinite(P_(D.spherify(ctr, amount=1.0))).all()))


# ══════════════════════════════════════════════════════════════════ Torus
print("═" * 28, "Torus")

R, r = 1.0, 0.3
for n in (16, 64, 256):
    g = build.torus(R, r, rows=n, cols=2 * n)
    Q = P_(g)
    dd = np.abs(np.hypot(np.hypot(Q[:, 0], Q[:, 2]) - R, Q[:, 1]) - r)
    check(f"n={n}: every point is at exactly section_radius from the main circle",
          float(dd.max()) < 1e-6, f"{float(dd.max()):.2e}")
g = build.torus(R, r, rows=256, cols=512)
A, V = float(M.prim_areas(g).sum()), float(abs(M.prim_volumes(g).sum()))
check("surface area converges to the analytic 4π²Rr",
      abs(A / (4 * np.pi ** 2 * R * r) - 1) < 1e-4,
      f"{A:.5f} vs {4 * np.pi ** 2 * R * r:.5f}")
check("volume converges to the analytic 2π²Rr²",
      abs(V / (2 * np.pi ** 2 * R * r * r) - 1) < 1e-3,
      f"{V:.5f} vs {2 * np.pi ** 2 * R * r * r:.5f}")
t8 = build.torus(rows=8, cols=12)
check("no duplicate endpoints in either direction: point count exactly rows×cols",
      t8.npoints == 8 * 12, t8.npoints)
check("  face count is also rows×cols (all quads)",
      t8.nprims == 8 * 12 and set(t8.prim_sizes().tolist()) == {4})
check("  no duplicate points (otherwise zero-area faces would appear on the seam)",
      len(np.unique(np.round(P_(t8), 6), axis=0)) == t8.npoints)
check("  no zero-area faces", float(M.prim_areas(t8).min()) > 1e-6)
check("has uv, within [0,1)",
      t8.get(POINT, "uv") is not None
      and 0.0 <= float(np.asarray(t8.get(POINT, "uv")).min())
      and float(np.asarray(t8.get(POINT, "uv")).max()) < 1.0)
for pl in ("zx", "xy", "yz"):
    q = P_(build.torus(1.0, 0.3, 8, 12, plane=pl))
    thin = int(np.argmin(q.max(0) - q.min(0)))
    check(f"plane={pl}: the flattest axis is the section axis",
          abs((q[:, thin].max() - q[:, thin].min()) - 0.6) < 1e-5,
          f"axis {thin} span {q[:, thin].max() - q[:, thin].min():.4f}")
err("wrong plane errors", lambda: build.torus(plane="ab"), "plane must be one of")


# ═══════════════════════════════════════════════════════════════════ Ends
print("═" * 28, "Ends")


def edges(g):
    out = []
    off = g.prim_offset
    for i in range(g.nprims):
        pts = g.vertex_point[off[i]:off[i + 1]].tolist()
        n = len(pts)
        rg = range(n) if bool(g.prim_closed[i]) else range(n - 1)
        for k in rg:
            a, b = int(pts[k]), int(pts[(k + 1) % n])
            out.append((min(a, b), max(a, b)))
    return sorted(out)


def topo(g):
    return (g.vertex_point.tobytes(), g.prim_offset.tobytes(),
            g.prim_closed.tobytes())


CIR = build.circle(radius=(1.0, 1.0), divisions=8, plane="zx")
u = E.ends(CIR, op="unroll")
check("unroll: closed -> open, first point appended again at the end",
      (not bool(u.prim_closed[0])) and int(u.prim_sizes()[0]) == 9
      and u.vertex_point.tolist()[-1] == u.vertex_point.tolist()[0],
      u.vertex_point.tolist())
check("  **edge set completely unchanged** (the only one of the four ops that doesn't change geometry)",
      edges(u) == edges(CIR))
check("unroll -> roll is a topologically **bit-for-bit** identity",
      topo(E.ends(u, op="roll")) == topo(CIR))
check("open: one edge fewer (the closing one)",
      len(edges(E.ends(CIR, op="open"))) == len(edges(CIR)) - 1)
LN = build.line((0, 0, 0), (0, 1, 0), points=5)
check("close: one edge more",
      len(edges(E.ends(LN, op="close"))) == len(edges(LN)) + 1)
check("  and point count unchanged (only the flag flips)",
      E.ends(LN, op="close").npoints == LN.npoints)
TWOP = build.line((0, 0, 0), (0, 1, 0), points=2)
check("two-point prims **may not** be closed (closed would be a zero-area degenerate face)",
      not bool(E.ends(TWOP, op="close").prim_closed[0]))
check("  and no error (errors are more annoying in batch processing)",
      E.ends(TWOP, op="close").nprims == 1)
check("already open, open again is the identity (not even new topology is created)",
      topo(E.ends(LN, op="open")) == topo(LN))
check("roll does nothing on open curves whose first and last points don't coincide",
      topo(E.ends(LN, op="roll")) == topo(LN))
# Tolerance version of roll: first and last are two different point numbers with coinciding coordinates
q = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]],
             np.float32)
G5 = Geometry(5)
G5.set(POINT, "P", q)
G5.set_topology(np.arange(5, dtype=np.int32), np.array([0, 5], np.int32),
                np.zeros(1, bool))
check("roll with tolerance=0 doesn't accept different point numbers", not bool(
    E.ends(G5, op="roll").prim_closed[0]))
check("accepted with a tolerance",
      bool(E.ends(G5, op="roll", tolerance=1e-6).prim_closed[0]))
check("prim count and order untouched (so prim attributes line up)",
      E.ends(CIR, op="unroll").nprims == CIR.nprims)
BX = build.box()
check("unroll on faces (closed poly) doesn't turn them into lines either",
      E.ends(BX, op="unroll").nprims == BX.nprims)
err("wrong op errors and lists the options", lambda: E.ends(CIR, op="flip"), "Op must be one of")


# ══════════════════════════════════════════════ build.py primitives (plugging a hole)
print("═" * 28, "build.py primitives")
# When the sandbox was reclaimed 23 old suites were lost. This batch touched build.py (adding Torus), which had no
# regression protection -- this section is a temporary substitute that checks only the most basic things.

gr = build.grid(size_x=4, size_z=6, cols=5, rows=7)
check("grid: cols/rows are **point counts**, not cell counts",
      gr.npoints == 5 * 7 and gr.nprims == 4 * 6,
      f"{gr.npoints} points / {gr.nprims} faces")
gp = P_(gr)
check("  size is exactly size_x × size_z",
      abs((gp[:, 0].max() - gp[:, 0].min()) - 4.0) < 1e-5
      and abs((gp[:, 2].max() - gp[:, 2].min()) - 6.0) < 1e-5)
check("  default zx plane = Y always 0", float(np.abs(gp[:, 1]).max()) < 1e-6)
check("  has uv, range exactly [0,1]",
      gr.get(POINT, "uv") is not None
      and abs(float(np.asarray(gr.get(POINT, "uv")).min())) < 1e-6
      and abs(float(np.asarray(gr.get(POINT, "uv")).max()) - 1.0) < 1e-6)
check("  all quads", set(gr.prim_sizes().tolist()) == {4})

bx = build.box(size=(2, 4, 6))
bp = P_(bx)
check("box: 6 faces by default",
      bx.nprims == 6 and set(bx.prim_sizes().tolist()) == {4}, bx.nprims)
check("  size matches",
      np.allclose(bp.max(0) - bp.min(0), [2, 4, 6], atol=1e-5))
check("  volume = 2×4×6", abs(vol(bx) - 48.0) < 1e-3, vol(bx))
check("  after subdividing, points on shared edges aren't duplicated",
      build.box(divisions=(3, 3, 3)).npoints == 26,
      build.box(divisions=(3, 3, 3)).npoints)

sph = build.sphere(radius=1.0, rows=64, cols=128) \
    if "rows" in build.sphere.__code__.co_varnames else build.sphere()
spp = P_(sph)
rad = np.linalg.norm(spp - spp.mean(0), axis=1)
check("sphere: all points on the same sphere",
      float(rad.std() / max(rad.mean(), 1e-9)) < 1e-4,
      f"relative std {float(rad.std() / rad.mean()):.2e}")
check("  surface area converges to 4πr²",
      abs(float(M.prim_areas(sph).sum()) / (4 * np.pi) - 1) < 0.02,
      f"{float(M.prim_areas(sph).sum()):.4f} vs {4 * np.pi:.4f}")

tb = build.tube(radius1=1.0, radius2=1.0, height=3.0, cols=128, rows=2,
                caps=True)
check("tube: volume converges to πr²h",
      abs(vol(tb) / (np.pi * 3.0) - 1) < 0.01,
      f"{vol(tb):.4f} vs {np.pi * 3.0:.4f}")
check("  top and bottom caps face opposite ways (volume is positive, not cancelled out)", vol(tb) > 0)

ci = build.circle(radius=(1.0, 1.0), divisions=256, plane="zx")
check("circle: a single closed prim", bool(ci.prim_closed[0]))
check("  area converges to πr²",
      abs(float(M.prim_areas(ci).sum()) / np.pi - 1) < 1e-3,
      f"{float(M.prim_areas(ci).sum()):.5f} vs {np.pi:.5f}")
li = build.line((0, 0, 0), (1, 1, 0), length=2.0, points=5)
check("line: open polyline, correct point count",
      li.npoints == 5 and not bool(li.prim_closed[0]))
check("  total length = length",
      abs(float(np.linalg.norm(np.diff(P_(li), axis=0), axis=1).sum()) - 2.0)
      < 1e-5)

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
