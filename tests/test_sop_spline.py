"""
pcg75: curves and surfaces -- Circle Spline, PolySpline, Ballistic Path, PolyLoft,
Cross Section Surface.

The reference doesn't rely on the implementation itself:
  Circle Spline         points on a circle -> the result is that circle; collinear -> a straight line; passes through every point; at the points
                        the tangent and curvature = the circle through the previous / current / next point (measured by finite differences; negative control: Catmull-Rom's curvature
                        doesn't match)
  PolySpline            Catmull-Rom passes through points, uniform parametrization reproduces straight lines; centripetal doesn't knot (negative control: uniform knots);
                        B-spline knot radius on a regular polygon = r(4 + 2cos(2π/n))/6; interpolate passes through points
                        with a continuous second derivative (negative control: Catmull-Rom's second derivative jumps); Cd = P follows P with the same weights
  Ballistic Path        no drag = the parabola formula; with drag matches small-step RK4 numerical integration; solved initial velocities
                        land exactly on the target (time / elevation angle); unreachable ones are counted; the landing point is exactly on the ground, time =
                        the analytic solution; collisions cut off at the wall
  PolyLoft              no points added; quad count, consistent winding; with different point counts zipper triangles = n₁ + n₂ − 2,
                        no gaps; cross lines are exactly the i-th point of each curve
  Cross Section Surface a net on the hyperbolic paraboloid z = xy: linear and cubic both exact; curved net: the surface passes exactly
                        through every curve; more accurate than lofting a single family (negative control); closed cross-sections -> the tube has no seam gap;
                        a net that doesn't intersect reports the gap; reversed curve directions don't change the result
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

from comfyui_pcg.geo import curves2 as CV               # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, VERTEX  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

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


def Pd(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def pl(P, closed=False):
    return Geometry.from_mesh(np.asarray(P, np.float32), [list(range(len(P)))],
                              closed=closed)


def circ3(a, b, c):
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    C = a + ((ac @ ac) * np.cross(n, ab) + (ab @ ab) * np.cross(ac, n)) / \
        (2 * (n @ n))
    return C, np.linalg.norm(a - C)


def curvature3(a, b, c):
    """Curvature of the circumscribed circle of three points."""
    n = np.linalg.norm(np.cross(b - a, c - a))
    return 2 * n / (np.linalg.norm(b - a) * np.linalg.norm(c - b) *
                    np.linalg.norm(c - a))


def idx_of(Q, p):
    return int(np.argmin(np.linalg.norm(Q - p, axis=1)))


def dist_poly(Q, X, closed=False):
    if closed:
        X = np.vstack([X, X[:1]])
    best = np.full(len(Q), np.inf)
    for j in range(len(X) - 1):
        A, B = X[j], X[j + 1]
        d = B - A
        t = np.clip((Q - A) @ d / (d @ d), 0, 1)
        best = np.minimum(best, np.linalg.norm(A + t[:, None] * d - Q, axis=1))
    return best


rng = np.random.default_rng(0)
# ═══════════════════════════════════════════════════════ Circle Spline
sec("Circle Spline")
th = np.sort(rng.uniform(0, 2 * np.pi, 7))
Rm = np.linalg.qr(rng.normal(size=(3, 3)))[0]
C0 = np.array([0.3, -0.2, 0.5])
ring = C0 + (np.c_[2 * np.cos(th), np.zeros(7), 2 * np.sin(th)]) @ Rm.T
o, r = CV.circle_spline(pl(ring, True), "", 16)
Q = Pd(o)
nrm = Rm[:, 1]
check("points all on one (tilted) circle -> the result is that circle", np.abs(np.linalg.norm(Q - C0, axis=1)
                                              - 2).max() < 1e-5 and
      np.abs((Q - C0) @ nrm).max() < 1e-5,
      np.abs(np.linalg.norm(Q - C0, axis=1) - 2).max())
check("closed: 7 segments × 16 = 112 points, closed", o.npoints == 112 and o.prim_closed[0])
o, r = CV.circle_spline(pl(ring[:5]), "", 16)
Q = Pd(o)
check("an open arc: also on the circle (first and last segments have only one circle)",
      np.abs(np.linalg.norm(Q - C0, axis=1) - 2).max() < 1e-5 and
      o.npoints == 4 * 16 + 1)
big = pl(C0 + np.c_[2 * np.cos(np.radians([0, 200, 250])), np.zeros(3),
                     2 * np.sin(np.radians([0, 200, 250]))] @ Rm.T)
o, _ = CV.circle_spline(big, "", 200)
Q = Pd(o)
Lb = np.linalg.norm(np.diff(Q, axis=0), axis=1).sum()
check("arc over a half circle (0° -> 200°) goes the right way: total length = arc length of 250°",
      abs(Lb - 2 * np.radians(250)) < 1e-3 and
      np.abs(np.linalg.norm(Q - C0, axis=1) - 2).max() < 1e-5, Lb)
lin = np.array([[0, 0, 0], [1, 1, 0], [1.5, 1.5, 0], [4, 4, 0]], float)
o, _ = CV.circle_spline(pl(lin), "", 8)
Q = Pd(o)
check("collinear -> straight line", np.abs(Q[:, 0] - Q[:, 1]).max() < 1e-6 and
      np.abs(Q[:, 2]).max() < 1e-7)
wig = np.c_[np.linspace(0, 6, 8), rng.uniform(-1, 1, 8), rng.uniform(-1, 1, 8)]
wg = pl(wig)
wg.set(POINT, "Cd", np.c_[np.arange(8), np.zeros(8), np.zeros(8)].astype(np.float32))
wg64 = wg.copy()
wg64.set(POINT, "P", wig.astype(np.float64))
o, _ = CV.circle_spline(wg64, "", 1000)
Q = Pd(o)
hits = [idx_of(Q, p) for p in wig]
check("passes through every input point", max(np.linalg.norm(Q[h] - p) for h, p in zip(hits, wig))
      < 1e-9)


def one_sided(Q, h, sgn, m=2):
    """One-sided differences from Q[h] towards one side with m and 2m samples, then extrapolated (error O(h) -> O(h²))."""
    def est(k):
        a, b, c = Q[h], Q[h + sgn * k], Q[h + 2 * sgn * k]
        d = (b - a) * sgn
        return d / np.linalg.norm(d), curvature3(a, b, c)
    d1, k1 = est(m)
    d2, k2 = est(2 * m)
    d = 2 * d1 - d2
    return d / np.linalg.norm(d), 2 * k1 - k2


tang_err, curv_err = 0.0, 0.0
for i in range(1, 7):
    h = hits[i]
    C, R = circ3(wig[i - 1], wig[i], wig[i + 1])
    n = np.cross(wig[i] - wig[i - 1], wig[i + 1] - wig[i - 1])
    tgt = np.cross(n, wig[i] - C)
    tgt /= np.linalg.norm(tgt)
    for sg in (-1, 1):
        d, kap = one_sided(Q, h, sg)
        tang_err = max(tang_err, math.degrees(math.acos(np.clip(d @ tgt, -1, 1))))
        curv_err = max(curv_err, abs(kap * R - 1))
check("at every interior point the tangents on both sides = the tangent of the circle through the three points (< 0.01°)",
      tang_err < 0.01, round(tang_err, 5))
check("curvature on both sides = that circle's curvature (relative error < 0.2%, G2)", curv_err < 2e-3,
      round(curv_err, 5))
oc, _ = CV.poly_spline(wg64, "", "catmull_rom", 0.5, 1000)
Qc = Pd(oc)
cc = 0.0
for i in range(1, 7):
    R = circ3(wig[i - 1], wig[i], wig[i + 1])[1]
    for sg in (-1, 1):
        cc = max(cc, abs(one_sided(Qc, idx_of(Qc, wig[i]), sg)[1] * R - 1))
check("negative control: Catmull-Rom's curvature at the points doesn't match that circle", cc > 0.05, round(cc, 3))
Cd = o.get(POINT, "Cd")[:, 0]
check("numeric point attributes interpolated linearly per segment (Cd.x rises evenly from 0 to 7)",
      np.abs(Cd - np.linspace(0, 7, len(Cd))).max() < 1e-4)
two = ops.merge(pl(wig), build.grid(1, 1, 2, 2))
two.set_group(PRIM, "c", np.array([True, False]))
o, r = CV.circle_spline(two, "c", 8)
check("unselected prims left as they are", o.nprims == 2 and r["curves"] == 1 and
      sorted(o.prim_sizes().tolist()) == [4, 57])

# ═══════════════════════════════════════════════════════ PolySpline
sec("PolySpline")
o, _ = CV.poly_spline(wg, "", "catmull_rom", 0.5, 16)
Q = Pd(o)
check("catmull_rom passes through every point", max(np.linalg.norm(Q - p, axis=1).min() for p in wig)
      < 1e-6)
ev = pl(np.c_[np.arange(6.0), 2 * np.arange(6.0), np.zeros(6)])
o, _ = CV.poly_spline(ev, "", "catmull_rom", 0.0, 4)
Q = Pd(o)
check("uniform Catmull-Rom reproduces a straight line on evenly spaced collinear points (evenly spaced)",
      np.abs(Q[:, 0] - np.linspace(0, 5, 21)).max() < 1e-6 and
      np.abs(Q[:, 1] - 2 * Q[:, 0]).max() < 1e-6)


def selfx(Q):
    X = Q[:, [0, 2]]
    n = len(X) - 1
    c = 0
    for i in range(n):
        for j in range(i + 2, n):
            a, b, e, f = X[i], X[i + 1], X[j], X[j + 1]

            def ccw(p, q, s_):
                return (s_[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (s_[0] - p[0])
            if ccw(a, e, f) * ccw(b, e, f) < 0 and ccw(a, b, e) * ccw(a, b, f) < 0:
                c += 1
    return c


knot = pl(np.array([[0, 0, 0], [0, 0, 1], [0.1, 0, 1.02], [4, 0, 1.0]]))
x0 = selfx(Pd(CV.poly_spline(knot, "", "catmull_rom", 0.0, 64)[0]))
x5 = selfx(Pd(CV.poly_spline(knot, "", "catmull_rom", 0.5, 64)[0]))
check("negative control: uniform parametrization knots (self-intersects) with very uneven point spacing", x0 > 0, x0)
check("centripetal (alpha 0.5) doesn't knot", x5 == 0, x5)
ng = 9
poly9 = pl(np.c_[3 * np.cos(2 * np.pi * np.arange(ng) / ng), np.zeros(ng),
                 3 * np.sin(2 * np.pi * np.arange(ng) / ng)], True)
o, _ = CV.poly_spline(poly9, "", "bspline", 0.5, 8)
Q = Pd(o)
want = 3 * (4 + 2 * math.cos(2 * math.pi / ng)) / 6
check("B-spline: knot radius of a regular nonagon = r(4 + 2cos(2π/n))/6",
      np.abs(np.linalg.norm(Q[::8], axis=1) - want).max() < 1e-5,
      (np.linalg.norm(Q[0]), want))
o, _ = CV.poly_spline(wg, "", "bspline", 0.5, 16)
Q = Pd(o)
check("open B-spline: passes through the end points", np.linalg.norm(Q[0] - wig[0]) < 1e-6 and
      np.linalg.norm(Q[-1] - wig[-1]) < 1e-6)
check("  negative control: doesn't pass through interior points (approximating, not interpolating)",
      np.linalg.norm(Q - wig[3], axis=1).min() > 1e-3)
for cl, geo_ in ((False, wg), (True, pl(wig, True))):
    o, _ = CV.poly_spline(geo_, "", "interpolate", 0.5, 16)
    Q = Pd(o)
    check(f"interpolate({'closed' if cl else 'open'}): passes through every point",
          max(np.linalg.norm(Q - p, axis=1).min() for p in wig) < 1e-5)


def d2_jump(Q, hits):
    out = 0.0
    for h in hits:
        left = Q[h] - 2 * Q[h - 1] + Q[h - 2]
        right = Q[h + 2] - 2 * Q[h + 1] + Q[h]
        out = max(out, np.linalg.norm(left - right) /
                  max(np.linalg.norm(left), np.linalg.norm(right)))
    return out


oi, _ = CV.poly_spline(wg, "", "interpolate", 0.5, 200)
Qi = Pd(oi)
ji = d2_jump(Qi, [idx_of(Qi, wig[i]) for i in range(1, 7)])
oc, _ = CV.poly_spline(wg, "", "catmull_rom", 0.0, 200)
Qc = Pd(oc)
jc = d2_jump(Qc, [idx_of(Qc, wig[i]) for i in range(1, 7)])
check("interpolate has a continuous second derivative at knots (left/right difference < 5%)", ji < 0.05, round(ji, 4))
check("  negative control: Catmull-Rom's second derivative jumps at knots", jc > 0.3, round(jc, 3))
cdg = wg.copy()
cdg.set(POINT, "Cd", wig.astype(np.float32))
for b in CV.SPLINE_BASES:
    o, _ = CV.poly_spline(cdg, "", b, 0.5, 8)
    check(f"{b}: with Cd = P the output Cd is still = P (same weights)",
          np.abs(o.get(POINT, "Cd") - o.get(POINT, "P")).max() < 1e-5)
err("wrong Basis -> error", lambda: CV.poly_spline(wg, "", "nope"), "Basis")

# ═══════════════════════════════════════════════════════ Ballistic Path
sec("Ballistic Path")
g_ = np.array([0, -9.8, 0])
src = Geometry.from_points(np.array([[0, 0, 0], [1, 2, -1]], np.float32))
src.set(POINT, "v", np.array([[3, 5, 0], [1, 4, 2]], np.float32))
src.set(POINT, "Cd", np.array([[1, 0, 0], [0, 1, 0]], np.float32))
o, r = CV.ballistic_path(src, duration=1.5, samples=16)
Q = Pd(o)
t = o.get(POINT, "time")[:, 0]
p0 = np.repeat(np.array([[0, 0, 0], [1, 2, -1]], float), 16, 0)
v0 = np.repeat(np.array([[3, 5, 0], [1, 4, 2]], float), 16, 0)
ana = p0 + v0 * t[:, None] + 0.5 * g_ * t[:, None] ** 2
check("no drag: every sample = p₀ + v₀t + ½gt²", np.abs(Q - ana).max() < 1e-5 and
      r["paths"] == 2, np.abs(Q - ana).max())
check("v on points = v₀ + gt", np.abs(o.get(POINT, "v") - (v0 + g_ * t[:, None])).max()
      < 1e-5)
check("source point attributes carried over, srcpoint on prims",
      np.allclose(o.get(POINT, "Cd")[16:], [0, 1, 0]) and
      o.get(PRIM, "srcpoint")[:, 0].tolist() == [0, 1])


def rk4(p, v, k, T, n=20000):
    h = T / n
    for _ in range(n):
        def f(x):
            return np.r_[x[3:], g_ - k * x[3:]]
        x = np.r_[p, v]
        a = f(x)
        b = f(x + h / 2 * a)
        c = f(x + h / 2 * b)
        d = f(x + h * c)
        x = x + h / 6 * (a + 2 * b + 2 * c + d)
        p, v = x[:3], x[3:]
    return p, v


o, _ = CV.ballistic_path(src, drag=0.7, duration=1.5, samples=16)
pe, ve = rk4(np.zeros(3), np.array([3.0, 5, 0]), 0.7, 1.5)
check("linear drag: end point matches RK4 numerical integration", np.linalg.norm(Pd(o)[15] - pe) < 1e-5 and
      np.linalg.norm(o.get(POINT, "v")[15] - ve) < 1e-4,
      np.linalg.norm(Pd(o)[15] - pe))
tg = Geometry.from_points(np.array([[6, 1, 2], [-2, 0, 3]], np.float32))
for k in (0.0, 0.5):
    o, r = CV.ballistic_path(src, "", "target_time", tg, drag=k, flight_time=1.3)
    end = Pd(o)[[31, 63]]
    check(f"target_time (drag {k}): lands exactly on the target, end time = 1.3",
          np.abs(end - Pd(tg)).max() < 1e-5 and
          abs(o.get(POINT, "time")[31, 0] - 1.3) < 1e-6)
    o, r = CV.ballistic_path(src, "", "target_angle", tg, drag=k, launch_angle=55)
    end = Pd(o)[[31, 63]]
    vv = o.get(POINT, "v")[[0, 32]].astype(float)
    elev = np.degrees(np.arcsin(vv[:, 1] / np.linalg.norm(vv, axis=1)))
    check(f"target_angle (drag {k}): lands on the target, launch elevation = 55°",
          np.abs(end - Pd(tg)).max() < 1e-4 and np.abs(elev - 55).max() < 1e-3,
          (np.abs(end - Pd(tg)).max(), elev))
hi = Geometry.from_points(np.array([[1, 20, 0]], np.float32))
o, r = CV.ballistic_path(src, "", "target_angle", hi, launch_angle=30)
check("elevation too low to reach: no curve, counted (a second point without a paired target counts too)",
      r["unreachable"] == 2 and r["paths"] == 0, r)
o, r = CV.ballistic_path(src, "0", ground=True, duration=10, samples=32)
Q = Pd(o)
T_ana = 2 * 5 / 9.8
check("launch from the ground and land back on it: end height = 0, time = 2v_y/g",
      abs(Q[-1, 1]) < 1e-6 and abs(o.get(POINT, "time")[-1, 0] - T_ana) < 1e-6 and
      r["hit_ground"] == 1, (Q[-1], o.get(POINT, "time")[-1, 0]))
check("  points in between are all above the ground", (Q[1:-1, 1] > 0).all())
o, r = CV.ballistic_path(src, "1", ground=True, ground_height=-3, drag=0.4,
                         duration=10, samples=64)
Q = Pd(o)
check("with drag, ground at −3: landing point exactly on the ground, everything before above it",
      abs(Q[-1, 1] + 3) < 1e-6 and (Q[:-1, 1] > -3).all() and r["hit_ground"] == 1)
o, r = CV.ballistic_path(src, "0", ground=True, drag=0.4, duration=10, samples=64)
Q = Pd(o)
pe2, _ = rk4(np.zeros(3), np.array([3.0, 5, 0]), 0.4, o.get(POINT, "time")[-1, 0])
check("with drag, launching from the ground: lands back on the ground (not counted as landed at the launch moment), landing point matches RK4",
      o.get(POINT, "time")[-1, 0] > 0.5 and abs(Q[-1, 1]) < 1e-6 and
      np.linalg.norm(Q[-1] - pe2) < 1e-5, (o.get(POINT, "time")[-1, 0], Q[-1]))
low = Geometry.from_points(np.array([[0, -1, 0]], np.float32))
low.set(POINT, "v", np.array([[3, 8, 0]], np.float32))
for k in (0.0, 0.4):
    o, r = CV.ballistic_path(low, ground=True, drag=k, duration=10, samples=64)
    Q = Pd(o)
    check(f"crossing up out from below the ground (drag {k}): cut where it falls back down to the ground, not where it crosses upward",
          abs(Q[-1, 1]) < 1e-6 and Q[-1, 0] > 3 and r["hit_ground"] == 1,
          Q[-1])
o, r = CV.ballistic_path(src, "0", ground=True, ground_height=-100, duration=1)
check("negative control: not cut if it doesn't land within the duration", r["hit_ground"] == 0 and
      abs(o.get(POINT, "time")[-1, 0] - 1) < 1e-9)
def wall_at(x):
    w = build.grid(40, 40, 2, 2)
    w.set(POINT, "P", (Pd(w)[:, [1, 2, 0]] + [x, 0, 0]).astype(np.float32))
    return w


o, r = CV.ballistic_path(src, "0", collision=wall_at(2.5), drag=0.5, duration=3,
                         samples=48)
Q = Pd(o)
pe3, _ = rk4(np.zeros(3), np.array([3.0, 5, 0]), 0.5, o.get(POINT, "time")[-1, 0])
check("collision with drag: end point exactly on the wall, and on the true trajectory (< 1e-5 from RK4)",
      abs(Q[-1, 0] - 2.5) < 1e-6 and np.linalg.norm(Q[-1] - pe3) < 1e-5,
      (Q[-1], np.linalg.norm(Q[-1] - pe3)))
up10 = Geometry.from_points(np.array([[0, 0, 0]], np.float32))
up10.set(POINT, "v", np.array([[1, 10, 0]], np.float32))
o, r = CV.ballistic_path(up10, collision=wall_at(1.3), duration=3, samples=16)
Q = Pd(o)
check("short segments near the apex: a ray hitting the wall only beyond the segment end doesn't count (cut on the segment that really hits)",
      abs(Q[-1, 0] - 1.3) < 1e-6 and
      abs(Q[-1, 1] - (10 * 1.3 - 4.9 * 1.3 ** 2)) < 1e-5,
      (Q[-1], 10 * 1.3 - 4.9 * 1.3 ** 2))
wall = build.grid(20, 20, 2, 2)
wall.set(POINT, "P", (Pd(wall)[:, [1, 2, 0]] + [2.5, 0, 0]).astype(np.float32))
o, r = CV.ballistic_path(src, "0", collision=wall, duration=3, samples=48)
Q = Pd(o)
check("collision: cut at the wall (x = 2.5), nothing passes through before",
      abs(Q[-1, 0] - 2.5) < 1e-6 and (Q[:-1, 0] < 2.5).all() and
      r["hit_collision"] == 1, Q[-1])
check("  after the cut still sampled evenly in time with 48 points", o.npoints == 48 and
      np.allclose(np.diff(o.get(POINT, "time")[:-1, 0]),
                  o.get(POINT, "time")[1, 0], atol=1e-6))
side = Geometry.from_points(np.array([[0, 0, 0]], np.float32))
side.set(POINT, "v", np.array([[4, 3, 0]], np.float32))
o, r = CV.ballistic_path(side, gravity=(-9.8, 0, 0), ground=True, duration=5)
check("gravity towards −x: the ground is the x = 0 plane, the path still lands",
      abs(Pd(o)[-1, 0]) < 1e-6 and r["hit_ground"] == 1)
err("no v: error", lambda: CV.ballistic_path(tg), "No vector attribute")
err("target mode without a target connected: error", lambda: CV.ballistic_path(src, "", "target_time"),
    "second input")

# ═══════════════════════════════════════════════════════ PolyLoft
sec("PolyLoft")
rows_ = [np.c_[np.linspace(0, 3, 5), np.zeros(5) + 0.2 * z, np.full(5, z)]
         for z in range(4)]
crv = ops.merge(*[pl(x) for x in rows_])
crv.set(VERTEX, "uv", np.c_[np.arange(crv.nvertices), np.zeros(crv.nvertices)]
        .astype(np.float32))
o, r = CV.poly_loft(crv, "", "faces", keep_original=False)
check("faces: no points added, 3×4 = 12 quads", o.npoints == crv.npoints and
      o.nprims == 12 and set(o.prim_sizes().tolist()) == {4}, r)
Po = Pd(o)
ny = [np.cross(Po[o.prim_points(i)][1] - Po[o.prim_points(i)][0],
               Po[o.prim_points(i)][2] - Po[o.prim_points(i)][0])[1]
      for i in range(o.nprims)]
check("all faces wound consistently", all(np.sign(y) == np.sign(ny[0]) for y in ny))
t = topology(o)
check("manifold: interior edges have exactly two faces", set(np.unique(t.edge_count)) <= {1, 2})
uvo = o.get(VERTEX, "uv")[:, 0]
check("vertex attributes on face corners come from the corner of that point on the curve",
      all(int(crv.vertex_point[int(u)]) == int(p)
          for u, p in zip(uvo, o.vertex_point)))
o, r = CV.poly_loft(crv, "", "faces")
check("keep_original: the original 4 curves are still there", o.nprims == 16)
rings = ops.merge(*[pl(np.c_[np.cos(np.arange(6) * np.pi / 3), np.full(6, z),
                             np.sin(np.arange(6) * np.pi / 3)], True)
                    for z in range(3)])
o, r = CV.poly_loft(rings, "", "faces", keep_original=False)
check("closed curves: each band goes all the way round (2 × 6 = 12 faces), no seam gap",
      o.nprims == 12 and topology(o).boundary.sum() == 12)
o, r = CV.poly_loft(rings, "", "faces", wrap=True, keep_original=False)
check("wrap: the last curve connects back to the first -- a torus, no boundary", o.nprims == 18 and
      topology(o).boundary.sum() == 0)
uneq = ops.merge(pl(np.c_[np.linspace(0, 3, 4), np.zeros(4), np.zeros(4)]),
                 pl(np.c_[np.linspace(0, 3, 9), np.zeros(9), np.ones(9)]))
o, r = CV.poly_loft(uneq, "", "faces", keep_original=False)
t = topology(o)
check("different point counts (4 vs 9): zipper triangles 4 + 9 − 2 = 11, no gaps",
      o.nprims == 11 and set(o.prim_sizes().tolist()) == {3} and
      t.boundary.sum() == 3 + 8 + 2 and o.npoints == 13, r)
area = sum(0.5 * np.linalg.norm(np.cross(Pd(o)[f[1]] - Pd(o)[f[0]],
                                         Pd(o)[f[2]] - Pd(o)[f[0]]))
           for f in (o.prim_points(i) for i in range(o.nprims)))
check("  area = 3 × 1 (covers exactly, no overlap)", abs(area - 3) < 1e-6, area)
xspan = max(np.ptp(Pd(o)[o.prim_points(i), 0]) for i in range(o.nprims))
check("  the zipper follows arc length: no triangle spans more than one segment of the coarser curve (1.0) across",
      xspan <= 1.0 + 1e-6, xspan)
o, r = CV.poly_loft(crv, "", "cross_lines", keep_original=False)
check("cross_lines: 5 cross lines, the k-th = the k-th point of each curve",
      o.nprims == 5 and all(list(o.prim_points(k)) == [k, 5 + k, 10 + k, 15 + k]
                            for k in range(5)) and not o.prim_closed.any())
o, r = CV.poly_loft(crv, "", "grid_lines", keep_original=False)
check("grid_lines: cross lines + original curves = 9", o.nprims == 9)

# ═══════════════════════════════════════════════════════ Cross Section Surface
sec("Cross Section Surface")
xs = np.linspace(-1, 1, 41)


def net(f, ys, xs_g, npts=41):
    S_ = ops.merge(*[pl(np.c_[xs, f(xs, y), np.full(npts, y)]) for y in ys])
    yy = np.linspace(ys[0], ys[-1], npts)
    G_ = ops.merge(*[pl(np.c_[np.full(npts, x), f(x, yy), yy]) for x in xs_g])
    return S_, G_


def hyp(x, y):
    return x * y


ys = np.linspace(-1, 1, 5)
xg = np.linspace(-1, 1, 4)
S_, G_ = net(hyp, ys, xg)
for it in CV.CSS_INTERP:
    o, r = CV.cross_section_surface(S_, G_, interpolation=it)
    Q = Pd(o)
    e = np.abs(Q[:, 1] - Q[:, 0] * Q[:, 2]).max()
    check(f"net on z = xy, {it}: surface exact (error < 1e-5)", e < 1e-5, (e, r["max_gap"]))


def wave(x, y):
    return 0.4 * np.sin(2.5 * x) * np.cos(2 * y) + 0.2 * x * x


ys = np.linspace(-1, 1, 5)
xg = np.linspace(-1, 1, 5)
S_, G_ = net(wave, ys, xg)
o, r = CV.cross_section_surface(S_, G_, interpolation="cubic", divisions_s=8,
                                divisions_t=8)
Q = Pd(o).reshape(r["rows"], r["cols"], 3)
on_s = max(dist_poly(Q[8 * i], np.c_[xs, wave(xs, y), np.full(41, y)]).max()
           for i, y in enumerate(ys))
on_g = max(dist_poly(Q[:, 8 * j], np.c_[np.full(41, x), wave(x, np.linspace(-1, 1, 41)),
                                        np.linspace(-1, 1, 41)]).max()
           for j, x in enumerate(xg))
check("curved net: the corresponding rows of the surface lie on the cross-section curves", on_s < 1e-6, on_s)
check("  the corresponding columns lie on the guide curves (Gordon: passes through both families)", on_g < 1e-6, on_g)
eg = np.abs(Q[..., 1] - wave(Q[..., 0], Q[..., 2])).max()
ol, _ = CV.cross_section_surface(S_, None, interpolation="cubic", divisions_s=8,
                                 divisions_t=8)
Ql = Pd(ol)
el = np.abs(Ql[:, 1] - wave(Ql[:, 0], Ql[:, 2])).max()
olin, _ = CV.cross_section_surface(S_, G_, interpolation="linear")
Qn = Pd(olin)
en = np.abs(Qn[:, 1] - wave(Qn[:, 0], Qn[:, 2])).max()
check("negative control: lofting only the cross-sections (ignoring guides) has a larger error", eg < 0.5 * el, (round(eg, 4),
                                                   round(el, 4)))
check("  linear Gordon is worse than cubic", eg < en, (round(eg, 4), round(en, 4)))
uv = o.get(POINT, "uv")
check("uv within [0,1], 0 and 1 at the corners", uv[:, :2].min() == 0 and
      abs(uv[:, :2].max() - 1) < 1e-6)
# curves drawn in reverse
S2 = S_.copy()
G2 = ops.merge(*[pl(np.c_[np.full(41, x), wave(x, np.linspace(1, -1, 41)),
                          np.linspace(1, -1, 41)]) for x in xg[::-1]])
o2, _ = CV.cross_section_surface(S2, G2, interpolation="cubic", divisions_s=8,
                                 divisions_t=8)
check("guides drawn in reverse, in reverse order: same surface", np.abs(np.sort(Pd(o2), axis=0) -
                                        np.sort(Pd(o), axis=0)).max() < 1e-6)
sh_s = [2, 0, 4, 1, 3]
sh_g = [3, 1, 4, 0, 2]
Ssh = ops.merge(*[pl(np.c_[xs, wave(xs, ys[i]), np.full(41, ys[i])]) for i in sh_s])
Gsh = ops.merge(*[pl(np.c_[np.full(41, xg[j]), wave(xg[j], np.linspace(-1, 1, 41)),
                           np.linspace(-1, 1, 41)]) for j in sh_g])
o3, _ = CV.cross_section_surface(Ssh, Gsh, interpolation="cubic", divisions_s=8,
                                 divisions_t=8)
check("cross-sections and guides both input in shuffled order: sorted automatically by intersections, same surface",
      np.abs(Pd(o3) - Pd(o)).max() < 1e-6)
ol2, _ = CV.cross_section_surface(S_, None, interpolation="linear", divisions_s=8,
                                  divisions_t=8)
Ql2 = Pd(ol2)
el2 = np.abs(Ql2[:, 1] - wave(Ql2[:, 0], Ql2[:, 2])).max()
check("when only lofting, cubic is also more accurate than linear", el < el2, (round(el, 4), round(el2, 4)))
# closed cross-sections: a tube of varying radius
hs = np.linspace(0, 2, 5)
rad = lambda h: 1 + 0.3 * np.sin(2 * h)                          # noqa: E731
angs = np.linspace(0, 2 * np.pi, 48, endpoint=False)
secs = ops.merge(*[pl(np.c_[rad(h) * np.cos(angs), np.full(48, h),
                            rad(h) * np.sin(angs)], True) for h in hs])
hh = np.linspace(0, 2, 61)                     # cross-section heights all lie on the samples
gds = ops.merge(*[pl(np.c_[rad(hh) * np.cos(a), hh, rad(hh) * np.sin(a)])
                  for a in angs[[2, 14, 27, 38]]])     # meridians pass through the cross-section vertices: the net truly intersects
o, r = CV.cross_section_surface(secs, gds, divisions_s=6, divisions_t=6)
t = topology(o)
Q = Pd(o)
check("closed cross-sections -> the tube is closed in s (the boundary is just the top and bottom rings)",
      r["closed_s"] and t.boundary.sum() == 2 * r["cols"], r)
on_ring = max(dist_poly(Q.reshape(r["rows"], r["cols"], 3)[6 * i],
                        np.c_[rad(h) * np.cos(angs), np.full(48, h),
                              rad(h) * np.sin(angs)], True).max()
              for i, h in enumerate(hs))
check("  every cross-section ring is passed through exactly", on_ring < 1e-5, (on_ring, r["max_gap"]))
er = np.abs(np.hypot(Q[:, 0], Q[:, 2]) - rad(Q[:, 1])).max()
check("  close to the true surface of revolution (< 0.02)", er < 0.02, er)
rev = ops.merge(*[pl((np.c_[rad(h) * np.cos(angs), np.full(48, h),
                             rad(h) * np.sin(angs)])[::-1] if i == 2 else
                     np.c_[rad(h) * np.cos(angs), np.full(48, h),
                           rad(h) * np.sin(angs)], True)
                  for i, h in enumerate(hs)])
o2, r2 = CV.cross_section_surface(rev, gds, divisions_s=6, divisions_t=6)
check("  one cross-section ring drawn in reverse: same result", np.abs(np.sort(Pd(o2), axis=0) -
                                     np.sort(Q, axis=0)).max() < 1e-6)
# a net that doesn't intersect
G3 = G_.copy()
G3.set(POINT, "P", (Pd(G_) + [0, 0.05, 0]).astype(np.float32))
o, r = CV.cross_section_surface(S_, G3)
check("net doesn't truly intersect: report the max gap (= 0.05)", abs(r["max_gap"] - 0.05) < 1e-5,
      r["max_gap"])
Qg = Pd(o).reshape(r["rows"], r["cols"], 3)
ds_ = max(dist_poly(Qg[8 * i], np.c_[xs, wave(xs, y), np.full(41, y)]).max()
          for i, y in enumerate(np.linspace(-1, 1, 5)))
dg_ = max(dist_poly(Qg[:, 8 * j], Pd(G3)[41 * j:41 * (j + 1)]).max()
          for j in range(5))
check("  when not intersecting, each family is off by half the gap (intersection = midpoint of the closest points on both, error split in half)",
      abs(ds_ - 0.025) < 1e-3 and abs(dg_ - 0.025) < 1e-3, (ds_, dg_))
for y0, y1, which in ((-0.85, 1.0, "start"), (-1.0, 0.9, "end")):
    yy = np.linspace(y0, y1, 41)
    Gs = ops.merge(*[pl(np.c_[x + 0.3 * (yy + 1), wave(x + 0.3 * (yy + 1), yy), yy])
                     for x in np.linspace(-0.9, 0.4, 4)])
    o, r = CV.cross_section_surface(S_, Gs)
    e, yv = (0, -1.0) if which == "start" else (40, 1.0)
    want = max(dist_poly(Pd(Gs)[41 * j + e:41 * j + e + 1],
                         np.c_[xs, wave(xs, yv), np.full(41, yv)]).min()
               for j in range(4))
    check(f"guides running diagonally whose {which} falls short of the cross-section: gap = true distance from the end point to the cross-section",
          abs(r["max_gap"] - want) < 1e-6, (r["max_gap"], want))
err("no guides and only one cross-section: error",
    lambda: CV.cross_section_surface(pl(rows_[0])), "At least two")

# ═══════════════════════════════════════════════════════ nodes
sec("nodes")
NEW = {"PCG_CircleSpline": "PCG/modify", "PCG_PolySpline": "PCG/modify",
       "PCG_BallisticPath": "PCG/generate", "PCG_PolyLoft": "PCG/generate",
       "PCG_CrossSectionSurface": "PCG/generate"}
check("all 5 nodes registered, in the right category",
      all(k in MAP and MAP[k].CATEGORY == v for k, v in NEW.items()))
bad = [k for k in NEW for nm_ in MAP[k].INPUT_TYPES()["required"]
       if nm_ in ("seed", "class")]
check("no widget called seed / class", not bad, bad)


def unwrap(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


def defaults(cls, **over):
    kw = {}
    for nm_, spec in cls.INPUT_TYPES()["required"].items():
        if nm_ in over:
            kw[nm_] = over[nm_]
        elif isinstance(spec[0], list):
            kw[nm_] = spec[1].get("default", spec[0][0]) if len(spec) > 1 \
                else spec[0][0]
        elif len(spec) > 1 and "default" in spec[1]:
            kw[nm_] = spec[1]["default"]
    kw.update({k: v for k, v in over.items() if k not in kw})
    return kw


bad = []
for k, kw in {"PCG_CircleSpline": dict(geo=wg), "PCG_PolySpline": dict(geo=wg),
              "PCG_BallisticPath": dict(geo=src, collision=wall),
              "PCG_PolyLoft": dict(geo=crv),
              "PCG_CrossSectionSurface": dict(sections=S_, guides=G_)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 5 nodes cook with default parameters (with the needed inputs connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
