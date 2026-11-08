"""
pcg82: Soft Peak, Bulge, Magnet, Fractal, Scatter and Align, Edge Transport, Volume Rasterize
Attributes, HeightField Mask by Object, HeightField Cutout by Object.

Checks do not rely on the implementation itself (a linear Ramp gives the weight an analytic form w = 1 - d/r):
  Soft Peak        points in the group are pushed exactly Distance; within the radius pushed Distance·(1 - d/r); outside the radius unchanged bit for bit
  Bulge            single magnet: pushed Magnitude·(1 - d/r) along y; with radial the horizontal distance becomes d + M(1 - d/r);
                   two coincident magnets = one (max, not summed); pscale sets each magnet's radius; surface uses distance to the surface
  Magnet           displacement = w·T; with rotation only, every point's distance to the pivot is unchanged (angles are interpolated; negative control: interpolating results collapses)
  Fractal          original points do not move; new points at level k move <= Scale·Roughness^k; with fixed boundary boundary points have y = 0;
                   same seed same result; vector direction only moves that one component
  Scatter and Align  N perpendicular to the face, up perpendicular to N, the matrix from orient = [x, up, N] (same reading as Copy to Points);
                   point count per the formula of each of the three modes; without rotation up = Up parameter projected onto the tangent plane; Tilt angle is bounded; after Avoid Overlap
                   any two points are at least the sum of their pscales apart
  Edge Transport   on a straight line distance = arc length; on a grid distance from a corner = Manhattan distance; sum / average / copy
                   match hand computation; multiple roots go to the nearest root; disconnected parts go to unreached
  Volume Rasterize points on grid points: kernel (1 - d/r)^2 matches per cell; constant attributes exact everywhere; linear attributes recovered exactly on a symmetric lattice
  HF Mask / Cutout footprint texel count by hand; intersect / above / below by box height; feather half-way = 0.5;
                   carve digs down to the box bottom, fill raises to the box top, floating / buried boxes change nothing; Strength conversion
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

from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import deform3 as D3               # noqa: E402
from comfyui_pcg.geo import scatteralign as SA          # noqa: E402
from comfyui_pcg.geo import edgetransport as ET         # noqa: E402
from comfyui_pcg.geo import volraster as VR             # noqa: E402
from comfyui_pcg.geo.cop import hfobject as HO          # noqa: E402
from comfyui_pcg.geo.cop import CopImage                # noqa: E402
from comfyui_pcg.geo.cop.pixel import put, getn         # noqa: E402
from comfyui_pcg.geo.volume import volume_info          # noqa: E402
from comfyui_pcg.geo.xform import quat_to_mat, point_matrices  # noqa: E402
from comfyui_pcg.geo.spatial import closest_surface, tri_soup  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def PP(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def raises(fn, msg=""):
    try:
        fn()
    except (ValueError, KeyError) as ex:
        return msg in str(ex)
    return False


LIN = ("0:0  1:1", "linear")

# ═══════════════════════════════════════════════════════════ Soft Peak
print("═" * 28, "Soft Peak")
g = build.grid(4, 4, 21, 21)
P = PP(g)
d = np.linalg.norm(P, axis=1)
g.set_group(POINT, "c", d < 1e-6)
o, rep = D3.soft_peak(g, "c", 0.5, 1.0, "euclidean", *LIN)
Q = PP(o)
check("points in the group pushed exactly Distance along the normal (+Y)", abs(Q[d < 1e-6, 1][0] - 0.5) < 1e-6)
inn = (d > 1e-6) & (d < 1.0)
check("  within the radius pushed Distance·(1 - d/r) (linear Ramp)",
      np.abs(Q[inn, 1] - 0.5 * (1 - d[inn])).max() < 1e-6)
check("  outside the radius unchanged bit for bit, xz unchanged",
      np.array_equal(Q[d >= 1.0], P[d >= 1.0]) and np.abs(Q[:, [0, 2]] - P[:, [0, 2]]).max() == 0)
row = np.abs(P[:, 2]) < 1e-9
o2, _ = D3.soft_peak(g, "c", 0.5, 1.0, "distance", *LIN)
check("  metric = distance: along the row through the center (geodesic = straight line) same as euclidean",
      np.abs(PP(o2)[row, 1] - Q[row, 1]).max() < 1e-6)
sph = build.sphere(1.0, 24, 16)
Ps = PP(sph)
top = int(np.argmax(Ps[:, 1]))
sph.set_group(POINT, "top", np.arange(sph.npoints) == top)
o, _ = D3.soft_peak(sph, "top", 0.3, 0.5)
check("  on a sphere: the top vertex pushed radially by 0.3", abs(np.linalg.norm(PP(o)[top]) - 1.3) < 1e-5)
gN = ops.compute_normals(g, "point")
o, _ = D3.soft_peak(gN, "c", 0.5, 1.0, "euclidean", *LIN, update_normals=True,
                    weight_attribute="w")
N = np.asarray(o.get(POINT, "N"))
check("  Update Normals: an input with N is recomputed after the push (normals on the bump's slope tilt); weight written as a point attribute",
      np.abs(N[inn][:, [0, 2]]).max() > 0.1
      and np.abs(np.asarray(o.get(POINT, "w"))[inn, 0] - (1 - d[inn])).max() < 1e-6)
g3 = g.copy()
g3.set(POINT, "N", np.tile([0, 3, 0], (g.npoints, 1)).astype(np.float32))
o, _ = D3.soft_peak(g3, "c", 0.5, 1.0, "euclidean", *LIN, update_normals=False)
check("  N not unit length (length 3) still only pushes Distance (normalized first)", abs(PP(o)[d < 1e-6, 1][0] - 0.5) < 1e-6)
check("  no group given -> error", raises(lambda: D3.soft_peak(g, "", 0.5, 1.0), "point group"))

# ═══════════════════════════════════════════════════════════ Bulge
print("═" * 28, "Bulge")
m = Geometry.from_points(np.zeros((1, 3)))
o, rep = D3.bulge(g, m, 0.3, "normal", "points", 1.0, True, *LIN)
Q = PP(o)
check("single magnet (radius 1): pushed Magnitude·(1 - d/r) along y, unchanged outside the radius",
      np.abs(Q[:, 1] - np.where(d < 1, 0.3 * (1 - d), 0)).max() < 1e-6
      and np.array_equal(Q[d >= 1], P[d >= 1]))
o, _ = D3.bulge(g, m, 0.3, "radial", "points", 1.0, True, *LIN)
Q = PP(o)
dq = np.linalg.norm(Q[:, [0, 2]], axis=1)
check("  radial: horizontal distance becomes d + M(1 - d/r)",
      np.abs(dq[inn] - (d[inn] + 0.3 * (1 - d[inn]))).max() < 1e-6)
m2 = Geometry.from_points(np.zeros((2, 3)))
check("  two coincident magnets = one (max, not summed)",
      np.abs(PP(D3.bulge(g, m2, 0.3, "normal", "points", 1.0, True, *LIN)[0])
             - PP(D3.bulge(g, m, 0.3, "normal", "points", 1.0, True, *LIN)[0])).max() == 0)
mp = Geometry.from_points(np.array([[-1.5, 0, 0], [1.5, 0, 0]]))
mp.set(POINT, "pscale", np.array([[0.5], [1.0]], np.float32))
o, _ = D3.bulge(g, mp, 1.0, "normal", "points", 1.0, True, *LIN)
Q = PP(o)
dl = np.linalg.norm(P - [-1.5, 0, 0], axis=1)
dr = np.linalg.norm(P - [1.5, 0, 0], axis=1)
want = np.maximum(np.clip(1 - dl / 0.5, 0, None), np.clip(1 - dr / 1.0, 0, None))
check("  pscale sets each magnet's radius (left 0.5, right 1)", np.abs(Q[:, 1] - want).max() < 1e-6)
o, _ = D3.bulge(g, mp, 1.0, "normal", "points", 1.0, False, *LIN)
want2 = np.maximum(np.clip(1 - dl, 0, None), np.clip(1 - dr, 0, None))
check("  Use pscale off: all use Radius", np.abs(PP(o)[:, 1] - want2).max() < 1e-6)
plane = build.grid(10, 10, 2, 2)
plane = ops.transform(plane, translate=(0, 0, 0), rotate=(90, 0, 0))   # xy plane (z = 0)
o, _ = D3.bulge(g, plane, 0.2, "normal", "surface", 0.5, True, *LIN)
dz = np.abs(P[:, 2])
check("  surface type: by distance to the magnet surface / Radius (upright plane z = 0, radius 0.5)",
      np.abs(PP(o)[:, 1] - np.where(dz < 0.5, 0.2 * (1 - dz / 0.5), 0)).max() < 1e-6)
o, _ = D3.bulge(g, m, 1.0, "normal", "points", 1.0, True, "0:0.2  1:1", "linear")
o2, _ = D3.bulge(g, plane, 1.0, "normal", "surface", 0.5, True, "0:0.2  1:1", "linear")
check("  with a Ramp not 0 at the edge (0:0.2), nothing outside the radius moves at all (both points / surface)",
      np.array_equal(PP(o)[d >= 1], P[d >= 1]) and np.array_equal(PP(o2)[dz >= 0.5], P[dz >= 0.5])
      and abs(PP(o)[d < 1e-6, 1][0] - 1.0) < 1e-6)
o, _ = D3.bulge(g, mp, 1.0, "normal", "points", 2.0, True, *LIN)
want3 = np.maximum(np.clip(1 - dl / 1.0, 0, None), np.clip(1 - dr / 2.0, 0, None))
check("  radius = pscale x Radius (Radius 2: left 1, right 2)", np.abs(PP(o)[:, 1] - want3).max() < 1e-6)
mr = Geometry.from_points(np.array([[-1.0, 0, 0], [1.0, 0, 0]]))
o, _ = D3.bulge(g, mr, 0.1, "radial", "points", 1.0, True, *LIN)
Q = PP(o)
dlr = np.minimum(np.linalg.norm(P - [-1, 0, 0], axis=1), np.linalg.norm(P - [1, 0, 0], axis=1))
near_m = np.where((np.linalg.norm(P - [-1, 0, 0], axis=1)
                   < np.linalg.norm(P - [1, 0, 0], axis=1))[:, None], [-1.0, 0, 0], [1.0, 0, 0])
sel_ = (dlr < 0.9) & (dlr > 1e-6)
away = (P - near_m)[sel_]
away /= np.linalg.norm(away, axis=1, keepdims=True)
mv = (Q - P)[sel_]
mv /= np.linalg.norm(mv, axis=1, keepdims=True)
check("  radial, two magnets: each point is pushed away from the **nearest** magnet",
      np.abs(np.einsum("ij,ij->i", mv, away) - 1).max() < 1e-6)
g2 = g.copy()
g2.set_group(POINT, "left", P[:, 0] < 0)
o, _ = D3.bulge(g2, m, 0.3, "normal", "points", 1.0, True, *LIN, group="left")
check("  points outside the group do not move", np.array_equal(PP(o)[P[:, 0] >= 0], P[P[:, 0] >= 0]))
check("  errors: empty magnet, surface magnet without primitives, bad direction",
      raises(lambda: D3.bulge(g, Geometry(), 0.3))
      and raises(lambda: D3.bulge(g, m, 0.3, magnet_type="surface"))
      and raises(lambda: D3.bulge(g, m, 0.3, direction="up")))

# ═══════════════════════════════════════════════════════════ Magnet
print("═" * 28, "Magnet")
o, _ = D3.magnet(g, m, (0, 1, 0), radius=1.0, ramp=LIN[0], ramp_mode=LIN[1])
w = np.clip(1 - d, 0, None)
check("displacement = w · Translate", np.abs(PP(o) - P - w[:, None] * [0, 1, 0]).max() < 1e-6)
o, _ = D3.magnet(g, m, (0, 0, 0), rotate=(0, 90, 0), radius=1.0, ramp=LIN[0],
                 ramp_mode=LIN[1])
Q = PP(o)
check("rotation only: every point's distance to the pivot is unchanged (angles are interpolated)",
      np.abs(np.linalg.norm(Q, axis=1) - d).max() < 1e-6)
ang = np.arctan2(Q[inn, 2], Q[inn, 0]) - np.arctan2(P[inn, 2], P[inn, 0])
ang = (ang + np.pi) % (2 * np.pi) - np.pi
check("  angle rotated = w · 90° (around Y)", np.abs(np.abs(ang) - np.radians(90) * w[inn]).max() < 1e-5)
lerp = P + 0.5 * (P @ np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]]).T - P)
check("  negative control: interpolating results (lerp(P, RP, 0.5)) collapses the distance to the pivot to 0.71x",
      abs(np.linalg.norm(lerp[inn], axis=1) / d[inn] - math.sqrt(0.5)).max() < 1e-6)
o, _ = D3.magnet(g, m, (0, 0, 0), scale=(2, 2, 2), radius=10.0, ramp="0:1  1:1",
                 ramp_mode="linear")
check("Ramp constant 1: the whole piece scaled 2x around the pivot", np.abs(PP(o) - 2 * P).max() < 1e-5)
mo = Geometry.from_points(np.array([[1.0, 0, 0]]))
o1, _ = D3.magnet(g, mo, (0, 0, 0), scale=(2, 2, 2), radius=10.0, ramp="0:1  1:1",
                  ramp_mode="linear", pivot_mode="origin")
o2, _ = D3.magnet(g, mo, (0, 0, 0), scale=(2, 2, 2), radius=10.0, ramp="0:1  1:1",
                  ramp_mode="linear", pivot_mode="custom", pivot=(0, 0, 1))
o3, _ = D3.magnet(g, mo, (0, 0, 0), scale=(2, 2, 2), radius=10.0, ramp="0:1  1:1",
                  ramp_mode="linear")
check("  Pivot: origin / custom / magnet_center each scale around their own center",
      np.abs(PP(o1) - 2 * P).max() < 1e-5
      and np.abs(PP(o2) - ((P - [0, 0, 1]) * 2 + [0, 0, 1])).max() < 1e-5
      and np.abs(PP(o3) - ((P - [1, 0, 0]) * 2 + [1, 0, 0])).max() < 1e-5)

# ═══════════════════════════════════════════════════════════ Fractal
print("═" * 28, "Fractal")
q = build.grid(2, 2, 3, 3)
o, rep = D3.fractal(q, 3, 0.2, 0.5, seed=4)
Q = PP(o)
check("the original 9 points do not move (midpoint displacement only pushes new points)", np.array_equal(Q[:9], PP(q)))
t_o = __import__("comfyui_pcg.geo.topology", fromlist=["topology"]).topology(o)
bnd = np.zeros(o.npoints, bool)
bnd[t_o.edge_points[t_o.boundary].reshape(-1)] = True
check("  Fixed Boundary: points on the open boundary all have y 0, interior points were pushed",
      np.abs(Q[bnd, 1]).max() == 0 and np.abs(Q[~bnd, 1]).max() > 0.01)
from comfyui_pcg.geo.subdivide import subdivide    # noqa: E402
sizes = [9]
gg = q
for _ in range(3):
    gg = subdivide(gg, 1, "linear")
    sizes.append(gg.npoints)
# each level's random numbers are taken by [seed, level], so fractal(k+1) = pushing level k's new points on subdivide(fractal(k))
lvl_ok = True
for k in range(3):
    before = subdivide(D3.fractal(q, k, 0.2, 0.5, seed=4)[0], 1, "linear")
    after = D3.fractal(q, k + 1, 0.2, 0.5, seed=4)[0]
    dlt = np.linalg.norm(PP(after) - PP(before), axis=1)
    lvl_ok &= (dlt[:sizes[k]].max() == 0 and dlt[sizes[k]:].max() <= 0.2 * 0.5 ** k + 1e-6
               and dlt[sizes[k]:].max() > 0.2 * 0.5 ** k * 0.5)
check("  level k: only this level's new points are pushed, displacement <= Scale·Roughness^k (not a single old point moves)", lvl_ok)
check("  same seed same result, different seed differs",
      np.array_equal(PP(D3.fractal(q, 3, 0.2, 0.5, seed=4)[0]), Q)
      and not np.array_equal(PP(D3.fractal(q, 3, 0.2, 0.5, seed=5)[0]), Q))
ov, _ = D3.fractal(q, 2, 0.2, 0.5, "vector", (0, 0, 1), False, 1)
check("  vector direction: only z moves; with Fixed Boundary off boundary points move too",
      np.abs(PP(ov)[:, :2] - PP(subdivide(subdivide(q, 1, "linear"), 1, "linear"))[:, :2]).max() == 0
      and np.abs(PP(ov)[:, 2] - PP(subdivide(subdivide(q, 1, "linear"), 1, "linear"))[:, 2]).max() > 0)
o0, _ = D3.fractal(q, 3, 0.2, 0.0, seed=4)
check("  Roughness 0: only the first level moves (the next two are just linear subdivision)",
      np.array_equal(PP(o0), PP(subdivide(subdivide(D3.fractal(q, 1, 0.2, 0.0, seed=4)[0],
                                                     1, "linear"), 1, "linear"))))
qN = q.copy()
qN.set(POINT, "N", np.tile([1, 0, 0], (9, 1)).astype(np.float32))
oN, _ = D3.fractal(qN, 1, 0.2, 0.5, seed=4)
check("  input carrying a wrong N (1,0,0): normals computed from the current shape (flat -> only moves along y), the incoming N is not used",
      np.array_equal(PP(oN)[:, [0, 2]], PP(subdivide(q, 1, "linear"))[:, [0, 2]])
      and np.abs(PP(oN)[:, 1]).max() > 0.01)
check("  Divisions 0 = unchanged", np.array_equal(PP(D3.fractal(q, 0)[0]), PP(q)))

# ═══════════════════════════════════════════════════════ Scatter and Align
print("═" * 28, "Scatter and Align")
pl = build.grid(4, 4, 5, 5)
A = 16.0
o, rep = SA.scatter_align(pl, "count", count=300, scale_min=0.02, scale_max=0.06,
                          up=(1, 0, 0), rotate_random=0, seed=3)
N = np.asarray(o.get(POINT, "N"), np.float64)
U = np.asarray(o.get(POINT, "up"), np.float64)
ps = np.asarray(o.get(POINT, "pscale"))[:, 0]
Mq = quat_to_mat(np.asarray(o.get(POINT, "orient"), np.float64))
check("count: exactly 300; pscale in [Min, Max]", o.npoints == 300
      and ps.min() >= 0.02 and ps.max() <= 0.06)
check("  N is the face normal (0,1,0); with Rotate Random = 0 up = Up parameter projected onto the tangent plane = (1,0,0)",
      np.abs(np.abs(N[:, 1]) - 1).max() < 1e-6 and np.abs(U - [1, 0, 0]).max() < 1e-6)
check("  the matrix from orient = [x, up, N], matching how Copy to Points lays things out from N / up",
      np.abs(Mq[:, :, 2] - N).max() < 1e-5 and np.abs(Mq[:, :, 1] - U).max() < 1e-5
      and np.abs(point_matrices(o)[0] / ps[:, None, None] - Mq).max() < 1e-5)
o, _ = SA.scatter_align(pl, "count", count=300, up=(1, 0, 0), rotate_random=360, seed=3)
U = np.asarray(o.get(POINT, "up"), np.float64)
a = np.degrees(np.arctan2(U[:, 2], U[:, 0]))
check("  Rotate Random 360: the angle of up around N covers ±180 (each 90° quadrant has over 15%)",
      all(((a >= lo) & (a < lo + 90)).mean() > 0.15 for lo in (-180, -90, 0, 90)))
o, _ = SA.scatter_align(pl, "count", count=300, up=(1, 0, 0), rotate_random=90, seed=3)
U = np.asarray(o.get(POINT, "up"), np.float64)
a = np.degrees(np.arctan2(-U[:, 2], U[:, 0]))
check("  Rotate Random 90: rotated ±45° around N (both sides present)",
      np.abs(a).max() <= 45 + 1e-4 and a.min() < -20 and a.max() > 20, (a.min(), a.max()))
o, _ = SA.scatter_align(pl, "count", count=300, tilt=20, seed=3)
N = np.asarray(o.get(POINT, "N"), np.float64)
tl = np.degrees(np.arccos(np.clip(np.abs(N[:, 1]), 0, 1)))
check("  Tilt 20: normals tilted 0..20°, and some really are tilted", tl.max() <= 20 + 1e-4 and tl.max() > 10)
check("  up always perpendicular to N", np.abs(np.einsum("ij,ij->i", N,
                                          np.asarray(o.get(POINT, "up")))).max() < 1e-5)
o, rep = SA.scatter_align(pl, "density", density=7.5)
check("density: point count = Density x area", o.npoints == 120)
o, rep = SA.scatter_align(pl, "coverage", coverage=0.4, scale_min=0.05, scale_max=0.1)
e2 = (0.05 ** 2 + 0.05 * 0.1 + 0.1 ** 2) / 3
check("coverage: point count = Coverage·A / (π·E[s^2]), actual coverage within 10% of the target",
      o.npoints == round(0.4 * A / (math.pi * e2)) and abs(rep["coverage"] / 0.4 - 1) < 0.1,
      (o.npoints, rep["coverage"]))
sph = build.sphere(1.0, 32, 20)
o, rep = SA.scatter_align(sph, "count", count=150, scale_min=0.06, scale_max=0.1,
                          avoid_overlap=True, relax_iterations=60, seed=2)
X = PP(o)
ps = np.asarray(o.get(POINT, "pscale"))[:, 0]
D = np.linalg.norm(X[:, None] - X[None], axis=2)
need = ps[:, None] + ps[None]
np.fill_diagonal(D, np.inf)
dist = closest_surface(X, PP(sph), tri_soup(sph)[0])[1]
check("Avoid Overlap: any two points are at least the sum of their pscales apart, points still on the surface",
      (D >= need * (1 - 1e-3)).all() and dist.max() < 1e-6, float((D / need).min()))
N = np.asarray(o.get(POINT, "N"), np.float64)
tri_s = tri_soup(sph)[0]
Ps_ = PP(sph)
ti = closest_surface(X, Ps_, tri_s)[0]
fn = np.cross(Ps_[tri_s[ti, 1]] - Ps_[tri_s[ti, 0]], Ps_[tri_s[ti, 2]] - Ps_[tri_s[ti, 0]])
fn /= np.linalg.norm(fn, axis=1, keepdims=True)
fn *= np.sign(np.einsum("ij,ij->i", fn, X))[:, None]
check("  after the push N becomes the face normal of the triangle at the new position (outward)", np.abs(N - fn).max() < 1e-5,
      float(np.abs(N - fn).max()))
o, _ = SA.scatter_align(sph, "count", count=150, scale_min=0.04, scale_max=0.06,
                        avoid_overlap=True, overlap_scale=1.5, relax_iterations=80, seed=2)
X = PP(o)
ps = np.asarray(o.get(POINT, "pscale"))[:, 0]
D = np.linalg.norm(X[:, None] - X[None], axis=2)
np.fill_diagonal(D, np.inf)
check("  Overlap Scale 1.5: spacing >= 1.5 x sum of pscales", (D >= 1.5 * (ps[:, None] + ps[None]) * (1 - 1e-3)).all(),
      float((D / (ps[:, None] + ps[None])).min()))
inv = ops.compute_normals(sph, "point")
inv = ops.reverse_prims(inv)                                   # winding reversed, but point normals still outward
o, _ = SA.scatter_align(inv, "count", count=80, avoid_overlap=True, relax_iterations=5, seed=2)
check("  source geometry with reversed winding, point normals outward: after the push N still outward (keeps the original side, does not flip with the face)",
      (np.einsum("ij,ij->i", np.asarray(o.get(POINT, "N"), np.float64), PP(o)) > 0.9).all())
check("  same seed same result", np.array_equal(PP(SA.scatter_align(pl, seed=9)[0]),
                                    PP(SA.scatter_align(pl, seed=9)[0])))
check("  errors: Min > Max, bad mode, no primitives",
      raises(lambda: SA.scatter_align(pl, scale_min=0.2, scale_max=0.1))
      and raises(lambda: SA.scatter_align(pl, "grid"))
      and raises(lambda: SA.scatter_align(build.line())))

# ═══════════════════════════════════════════════════════════ Edge Transport
print("═" * 28, "Edge Transport")
ln = build.line((0, 0, 0), (1, 0, 0), 3.0, 5)
o, rep = ET.edge_transport(ln, "", "distance", "curves")
check("curves / distance: on a straight line = arc length 0, .75, 1.5, 2.25, 3",
      np.allclose(np.asarray(o.get(POINT, "transport"))[:, 0], [0, .75, 1.5, 2.25, 3]))
ln2 = ln.copy()
ln2.set_group(POINT, "end", np.arange(5) == 4)
o, _ = ET.edge_transport(ln2, "", "distance", "curves", "end")
check("  Root Group at the far end: walks backwards", np.allclose(np.asarray(o.get(POINT, "transport"))[:, 0],
                                              [3, 2.25, 1.5, .75, 0]))
ln.set(POINT, "a", np.arange(5, dtype=np.float32).reshape(-1, 1) + 1)
s_ = np.asarray(ET.edge_transport(ln, "a", "sum", "curves")[0].get(POINT, "a"))[:, 0]
av = np.asarray(ET.edge_transport(ln, "a", "average", "curves")[0].get(POINT, "a"))[:, 0]
cp = np.asarray(ET.edge_transport(ln, "a", "copy", "curves", output="c")[0].get(POINT, "c"))[:, 0]
check("sum / average / copy: 1,3,6,10,15 / 1,1.5,2,2.5,3 / all 1",
      np.allclose(s_, [1, 3, 6, 10, 15]) and np.allclose(av, [1, 1.5, 2, 2.5, 3])
      and np.allclose(cp, 1))
gr = build.grid(4, 4, 5, 5)
Pg = PP(gr)
corner = int(np.argmin(Pg[:, 0] + Pg[:, 2]))
gr.set_group(POINT, "root", np.arange(25) == corner)
o, rep = ET.edge_transport(gr, "", "distance", "network", "root")
man = np.abs(Pg[:, 0] - Pg[corner, 0]) + np.abs(Pg[:, 2] - Pg[corner, 2])
check("network: path length from a corner on a grid = Manhattan distance", np.allclose(
    np.asarray(o.get(POINT, "transport"))[:, 0], man, atol=1e-6))
other = int(np.argmax(Pg[:, 0] + Pg[:, 2]))
gr.set_group(POINT, "two", np.isin(np.arange(25), [corner, other]))
o, _ = ET.edge_transport(gr, "", "distance", "network", "two")
man2 = np.abs(Pg[:, 0] - Pg[other, 0]) + np.abs(Pg[:, 2] - Pg[other, 2])
rt = np.asarray(o.get(POINT, "transport_root"))[:, 0]
dd = np.asarray(o.get(POINT, "transport"))[:, 0]
check("  two roots: each point goes to the root with the shorter path, distance takes the smaller",
      np.allclose(dd, np.minimum(man, man2), atol=1e-6)
      and ((man < man2 - 1e-9) <= (rt == corner)).all()
      and ((man2 < man - 1e-9) <= (rt == other)).all())
gr.set(POINT, "v", np.tile([1, 2, 3], (25, 1)).astype(np.float32))
o, _ = ET.edge_transport(gr, "v", "sum", "network", "root")
hops = np.round(man / 1.0).astype(int) + 1
check("  vector attribute sum: each component accumulated separately (= number of points on the path x (1,2,3))",
      np.allclose(np.asarray(o.get(POINT, "v")), hops[:, None] * [1, 2, 3]))
# grid spacing 0.3 (3.3 / 11) is inexact in floating point, sums along two equal-length paths differ on the order of 1e-16 -- even then the "parent with the smaller point number" rule must hold
gt = build.grid(3.3, 3.3, 12, 12)
Pt = PP(gt)
ct = int(np.argmin(Pt[:, 0] + Pt[:, 2]))
gt.set_group(POINT, "root", np.arange(gt.npoints) == ct)
gt.set(POINT, "a", np.random.default_rng(7).integers(1, 9, (gt.npoints, 1)).astype(np.float32))
o, _ = ET.edge_transport(gt, "a", "sum", "network", "root")
av_ = np.asarray(gt.get(POINT, "a"))[:, 0]
hop = np.round((np.abs(Pt[:, 0] - Pt[ct, 0]) + np.abs(Pt[:, 2] - Pt[ct, 2])) / 0.3).astype(int)
from comfyui_pcg.geo.topology import point_neighbours  # noqa: E402
off_, nb_ = point_neighbours(gt)
exp = np.zeros(gt.npoints)
for p_ in np.argsort(hop, kind="stable"):
    if p_ == ct:
        exp[p_] = av_[p_]
        continue
    preds = [int(q_) for q_ in nb_[off_[p_]:off_[p_ + 1]] if hop[q_] == hop[p_] - 1]
    exp[p_] = exp[min(preds)] + av_[p_]
check("  several shortest paths (grid, spacing inexact in floating point): the parent with the smaller point number is chosen; sum matches hand computation by that rule",
      np.allclose(np.asarray(o.get(POINT, "a"))[:, 0], exp))
two_pieces = ops.merge(build.grid(1, 1, 2, 2), build.grid(1, 1, 2, 2, center=(5, 0, 0)))
two_pieces.set_group(POINT, "r", np.arange(8) == 0)
o, rep = ET.edge_transport(two_pieces, "", "distance", "network", "r")
un = np.asarray(o.get_group(POINT, "unreached"))
check("  the disconnected piece: goes into the unreached group, value 0", un[4:].all() and not un[:4].any()
      and np.asarray(o.get(POINT, "transport"))[4:].max() == 0 and rep["unreached"] == 4)
lines2 = ops.merge(build.line((0, 0, 0), (1, 0, 0), 1.0, 3), build.line((0, 1, 0), (1, 0, 0), 1.0, 3))
lines2.set_group(POINT, "r", np.arange(6) == 0)
o, rep = ET.edge_transport(lines2, "", "distance", "curves", "r")
check("  curves with a Root Group: lines with neither end a root are not reached", rep["unreached"] == 3
      and np.asarray(o.get_group(POINT, "unreached"))[3:].all())
check("  errors: network without a root, no attribute, bad operation",
      raises(lambda: ET.edge_transport(gr, "", "distance", "network"), "Root Group")
      and raises(lambda: ET.edge_transport(gr, "nope", "sum", "network", "root"))
      and raises(lambda: ET.edge_transport(gr, "", "max", "network", "root")))

# ═══════════════════════════════════════════════════════ Volume Rasterize
print("═" * 28, "Volume Rasterize Attributes")
one = Geometry.from_points(np.array([[0.5, 0.25, -0.3]]))
one.set(POINT, "Cd", np.array([[1, 0.5, 0.25]], np.float32))
v, rep = VR.rasterize_attributes(one, "Cd", 0.05, 0.2, False)
names = [str(x) for x in np.asarray(v.get(PRIM, "name"))[:, 0]]
vox, org, cell = volume_info(v, names.index("density"))
rz, ry, rx = vox.shape
Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx), indexing="ij")
Wd = org + np.stack([X, Y, Z], -1) * cell
dd = np.linalg.norm(Wd - [0.5, 0.25, -0.3], axis=-1)
check("single point: density per cell = (1 - d/r)^2 (point on a grid point, center = 1)",
      np.abs(vox - np.clip(1 - dd / 0.2, 0, None) ** 2).max() < 1e-6 and abs(vox.max() - 1) < 1e-6)
off_pt = Geometry.from_points(np.array([[0.512, 0.2533, -0.3071]]))
org2 = volume_info(VR.rasterize_attributes(off_pt, "", 0.05, 0.2, False)[0], 0)[1]
check("  grid aligned to world coordinates (when the point is not on a grid point the origin is still a whole multiple of Voxel Size)",
      np.abs(org2 / 0.05 - np.round(org2 / 0.05)).max() < 1e-6)
check("  vector attributes split into Cd.x / Cd.y / Cd.z, density first", names == ["density", "Cd.x", "Cd.y", "Cd.z"])
cy = volume_info(v, names.index("Cd.y"))[0]
check("  attribute volume = kernel-weighted average: exactly 0.5 where the kernel covers, 0 elsewhere",
      np.abs(cy[vox > 0] - 0.5).max() < 1e-6 and np.abs(cy[vox == 0]).max() == 0)
lat = np.stack(np.meshgrid(*[np.arange(-10, 11) * 0.025] * 3, indexing="ij"), -1).reshape(-1, 3)
cl = Geometry.from_points(lat)
cl.set(POINT, "a", (2 * lat[:, 0] + 1).reshape(-1, 1).astype(np.float32))
cl.set(POINT, "density", np.full((len(lat), 1), 0.5, np.float32))
v, _ = VR.rasterize_attributes(cl, "a", 0.05, 0.1, False)
names = [str(x) for x in np.asarray(v.get(PRIM, "name"))[:, 0]]
va, org, cell = volume_info(v, names.index("a"))
rz, ry, rx = va.shape
Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx), indexing="ij")
Wd = org + np.stack([X, Y, Z], -1) * cell
inner = (np.abs(Wd) <= 0.15 + 1e-9).all(-1)
check("linear attribute a = 2x + 1 on a symmetric lattice: interior cells recovered exactly",
      inner.sum() > 100 and np.abs(va[inner] - (2 * Wd[inner][:, 0] + 1)).max() < 1e-5)
dv = volume_info(v, names.index("density"))[0]
v1, _ = VR.rasterize_attributes(cl.copy(), "a", 0.05, 0.1, False, density_attribute="nope")
check("  density attribute multiplied in (0.5x); without the attribute it counts as 1",
      np.abs(dv - 0.5 * volume_info(v1, 0)[0]).max() < 1e-6)
twop = Geometry.from_points(np.array([[0, 0, 0], [1, 0, 0.0]]))
twop.set(POINT, "pscale", np.array([[0.1], [0.3]], np.float32))
v, rep = VR.rasterize_attributes(twop, "", 0.05, 0.0, True)
dv, org, cell = volume_info(v, 0)
Z, Y, X = np.meshgrid(*[np.arange(n) for n in dv.shape], indexing="ij")
Wd = org + np.stack([X, Y, Z], -1) * cell
lit = dv > 0
reach = np.minimum(np.linalg.norm(Wd - [0, 0, 0], axis=-1) / 0.1,
                   np.linalg.norm(Wd - [1, 0, 0], axis=-1) / 0.3)
check("  pscale sets each point's kernel radius (0.1 and 0.3; pscale is float32, 0.3 is stored as 0.30000001)",
      (reach[lit] < 1 + 1e-6).all() and (reach[~lit] >= 1 - 1e-6).all())
check("  errors: no attribute, all radii 0",
      raises(lambda: VR.rasterize_attributes(one, "nope"))
      and raises(lambda: VR.rasterize_attributes(one, "", radius=0, use_pscale=False)))

# ═══════════════════════════════════════════════════════ HF Mask / Cutout
print("═" * 28, "HeightField by Object")
W_ = 64
img = CopImage(W_, W_)
put(img, "C", np.zeros((W_, W_)), None)
cx = (np.arange(W_) + 0.5) / W_ - 0.5
inside1 = np.abs(cx) < 0.15
foot = np.outer(inside1, inside1)
b_mid = build.box((0.3, 0.3, 0.3), (0, 0.05, 0))                  # y ∈ [-0.1, 0.2] crosses the ground
b_up = build.box((0.3, 0.3, 0.3), (0, 0.5, 0))                    # floating
b_dn = build.box((0.3, 0.3, 0.3), (0, -0.5, 0))                   # buried
o, rep = HO.mask_by_object(img, b_mid, "C", "footprint")
check("footprint: texel centers inside the box projection are exactly 1 (%d by hand)" % foot.sum(),
      np.array_equal(getn(o, "mask")[..., 0] > 0.5, foot) and rep["masked_texels"] == foot.sum())
res = {}
for nm, b in (("mid", b_mid), ("up", b_up), ("dn", b_dn)):
    res[nm] = [int(HO.mask_by_object(img, b, "C", mo)[1]["masked_texels"])
               for mo in ("intersect", "above", "below")]
n_ = int(foot.sum())
check("intersect / above / below by the box height relative to the ground",
      res == {"mid": [n_, 0, 0], "up": [0, n_, 0], "dn": [0, 0, n_]}, res)
o, _ = HO.mask_by_object(img, b_mid, "C", "footprint", feather=0.1)
mv = getn(o, "mask")[..., 0]
from comfyui_pcg.geo.cop.sdf import distance_exact    # noqa: E402
dpx = distance_exact(foot)
half = np.abs(dpx - 0.05 * W_) < 0.5
check("  Feather 0.1: 1 inside; ≈ 0.5 at half the feather width from the mask; 0 beyond the feather width",
      np.all(mv[foot] == 1) and np.abs(mv[half] - 0.5).max() < 0.12
      and np.all(mv[dpx >= 0.1 * W_] == 0), float(np.abs(mv[half] - 0.5).max()))
tt_ = np.clip(1 - dpx / (0.1 * W_), 0, 1)
check("  the feather curve is smoothstep (matches values computed per texel from the exact distance)",
      np.abs(mv[~foot] - (tt_ * tt_ * (3 - 2 * tt_))[~foot]).max() < 1e-6)
b_off = build.box((0.2, 0.3, 0.2), (0.2, 0.05, 0.3))
o, _ = HO.mask_by_object(img, b_off, "C", "footprint")
cz = -((np.arange(W_) + 0.5) / W_ - 0.5)                     # z of row i: top of the image = +z
want_off = np.outer(np.abs(cz - 0.3) < 0.1, np.abs(cx - 0.2) < 0.1)
check("  orientation convention same as HeightField Project: x to the right, z toward the top of the image (an off-center box lands top-right)",
      np.array_equal(getn(o, "mask")[..., 0] > 0.5, want_off))
o, _ = HO.mask_by_object(img, b_mid, "C", "footprint", invert=True)
check("  Invert", np.array_equal(getn(o, "mask")[..., 0] > 0.5, ~foot))
o, rep = HO.cutout_by_object(img, b_mid, "C", "carve")
h = getn(o, "C")[..., 0]
check("carve: a box crossing the ground digs the ground down to the box bottom -0.1, outside unchanged bit for bit, _cut layer = the changed area",
      np.abs(h[foot] + 0.1).max() < 1e-6 and np.all(h[~foot] == 0)
      and np.array_equal(getn(o, "C_cut")[..., 0] > 0.5, foot))
check("  floating / buried boxes do not change the ground",
      HO.cutout_by_object(img, b_up, "C", "carve")[1]["changed_texels"] == 0
      and HO.cutout_by_object(img, b_dn, "C", "carve")[1]["changed_texels"] == 0)
o, _ = HO.cutout_by_object(img, b_mid, "C", "fill")
check("fill: raised to the box top 0.2; a floating box does not pull the ground up",
      np.abs(getn(o, "C")[..., 0][foot] - 0.2).max() < 1e-6
      and HO.cutout_by_object(img, b_up, "C", "fill")[1]["changed_texels"] == 0)
o, _ = HO.cutout_by_object(img, b_mid, "C", "both")
check("both: dig then fill = ground replaced by the box top", np.abs(getn(o, "C")[..., 0][foot] - 0.2).max() < 1e-6)
img2 = CopImage(W_, W_)
put(img2, "C", np.full((W_, W_), 0.05), None)                      # Strength 2 -> world height 0.1
o, _ = HO.cutout_by_object(img2, b_mid, "C", "carve", strength=2.0)
check("  Strength conversion: the layer stores world height / Strength (dug to -0.1 -> stores -0.05)",
      np.abs(getn(o, "C")[..., 0][foot] + 0.05).max() < 1e-6)
check("  errors: no geometry connected, bad mode",
      raises(lambda: HO.mask_by_object(img, None))
      and raises(lambda: HO.cutout_by_object(img, b_mid, "C", "dig")))

# ═════════════════════════════════════════════════════════════ nodes
print("═" * 28, "nodes")


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
gc = g.copy()
for k, kw in {"PCG_SoftPeak": dict(geo=gc, group="c"),
              "PCG_Bulge": dict(geo=g, magnet=m), "PCG_Magnet": dict(geo=g, magnet=m),
              "PCG_Fractal": dict(geo=q), "PCG_ScatterAlign": dict(geo=pl),
              "PCG_EdgeTransport": dict(geo=gr, root_group="root"),
              "PCG_VolumeRasterizeAttribs": dict(geo=one),
              "PCG_COPHFMaskByObject": dict(cop=img, geo=b_mid),
              "PCG_COPHFCutoutByObject": dict(cop=img, geo=b_mid)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if r[0] is None:
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 9 nodes run with default parameters (with the needed inputs connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
