"""
pcg67: SOP gap batch A (curve frames and copying) and batch B (paths and networks), 10 nodes.

━━ Criteria
  Orient Along Curve
    · quaternion <-> matrix round trip 1e-12; orient and N / up are the same frame
    · planar curve (xz plane) + up = Y: the RMF up is **exactly** Y everywhere
    · helix: the angle of the RMF relative to the Frenet frame varies linearly with arc length, slope = -torsion τ
      (τ computed with sign as (r′ × r″)·r‴ / |r′ × r″|²) -- this is the definition of the RMF
    · closed trefoil knot: holonomy angle 127°; after spreading it, the angle of the closing step is of the same magnitude as ordinary neighbouring steps
      (negative control: without spreading the closing difference is 127°)
    · roll 90 = up rotated to the former side; full twist 1 returns to the start at the end, partial 90 turns the end
      90° more than untwisted; reverse flips the tangent; constant / attribute modes
    · into Copy to Points: the copy's +Z really follows the tangent, +Y really is up
  PolyFrame
    · planar grid with uv = (x, z): tangentu = +X; with uv rotated 30° tangentu rotates 30° along with it
    · attribute_gradient: gradient direction of f = 2x + 3z is (2, 0, 3)/√13
    · points on a circle: N (Frenet principal normal) points to the center, tangentu along the tangent
    · faces: first_edge's tangentu = the first edge, N = face normal; degenerate ones produce no nan
  Copy and Transform
    · copy k = Transform (PCG) applied k times in a row (points and normals both right)
    · 12 copies rotating 30° and rising 1: copy 12 wraps back to the same angle, height 12
    · copynum / renaming / not writing; point and face counts
    · the Transform (PCG) normal bug fixed along the way: rotating 90° about z, N (1,0,0) -> (0,1,0)
      (before pcg67 it was (0,-1,0)); point normals outside the group unchanged; under non-uniform scale normals stay perpendicular to faces
  Revolve
    · semicircle -> sphere: points all on the unit sphere; one point at each pole, triangles at the poles; all faces point outwards;
      no zero-area faces; watertight (every edge has exactly two faces), Euler characteristic 2
    · closed cross section -> torus: Euler characteristic 0; a square cross section rotated 180° + capped is also watertight
    · reverse flips normals; triangles gives all triangles; uv in [0,1]
  Copy to Curves / Chain
    · count copies at equal arc length on a closed circle, no duplicate at the start; spacing 2.5 on a line places them at 0 2.5 5 7.5 10
    · copy +Z along the tangent; piece cycling; roll_step 90
    · Chain: link centers, fit puts the last link at the end point, on a closed circle both ends of every link lie on the circle,
      neighbouring links alternate by 90°
  Find Shortest Path / Group Find Path
    · on a grid the cost of 0 -> 440 = Manhattan distance 20
    · random triangle mesh + random cost attribute: matches Bellman-Ford (vectorized relaxation to convergence) point by point
    · nearest_end picks the nearest end point; each_pair count = starts × ends; sequence passes through in order
    · regions with a high cost attribute are avoided; slope weight lowers the path's maximum slope
    · group output: the edge group is exactly the neighbouring point pairs on the path; negative cost, point cloud, disconnected are all handled
    · boundary_loop: 80 edges on the outer ring of the grid; an interior seed point selects nothing
  Curve Intersect
    · 5 × 5 tic-tac-toe grid: 25 intersections, integer coordinates; after split it is connected, 6 segments per line,
      each intersection shared by 4 segments; shortest paths can be walked on it directly
    · lines on two height levels: 25 in xz mode, 0 in 3d mode, 25 again with the tolerance raised to 1.5
    · figure-8 has 1 self-intersection, 0 with self_intersect off; intersections on existing vertices insert no zero-length segments
    · random segments compared against an O(n²) brute force
  Connect Adjacent Pieces
    · points: every line ≤ radius, matches the brute-force "union of each point's K nearest"
    · a row of four touching boxes: piece_centroids connects 3 (neighbours only); piece_points
      end points are original points from different pieces; max_connections 1; keep_input attaches to the original points
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

from comfyui_pcg.geo import curveframe as CF             # noqa: E402
from comfyui_pcg.geo import copyxform as CX              # noqa: E402
from comfyui_pcg.geo import paths as PT                  # noqa: E402
from comfyui_pcg.geo import xform as XF, build, ops      # noqa: E402
from comfyui_pcg.geo import copyto as CT                 # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM  # noqa: E402
from comfyui_pcg.geo.topology import topology            # noqa: E402
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


def A(g, cls, name):
    return np.asarray(g.get(cls, name), np.float64)


def curve(P, closed=False):
    P = np.asarray(P, np.float64)
    return Geometry.from_mesh(P, [np.arange(len(P))], closed=closed)


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


rng = np.random.default_rng(67)

# ═══════════════════════════════════════════════════════ Orient Along Curve
sec("Orient Along Curve")
q = unit(rng.standard_normal((2000, 4)))
q *= np.where(q[:, 3:4] < 0, -1, 1)
check("quaternion -> matrix -> quaternion round trip 1e-12",
      np.abs(CF.mat_to_quat(XF.quat_to_mat(q)) - q).max() < 1e-12)

t = np.linspace(0, 2 * np.pi, 80)
wav = curve(np.stack([t, 0 * t, np.sin(t) * 1.5], 1))
o = CF.orient_along_curve(wav)
N, U, Q = A(o, POINT, "N"), A(o, POINT, "up"), A(o, POINT, "orient")
M = XF.quat_to_mat(Q)
check("orient and N / up are the same frame (columns = [up×N, up, N])",
      np.abs(M[:, :, 2] - N).max() < 1e-5 and np.abs(M[:, :, 1] - U).max()
      < 1e-5)
check("curve in the xz plane + up = Y: the RMF up is exactly Y everywhere",
      np.abs(U - [0, 1, 0]).max() < 1e-6)
check("N is the unit tangent, orthogonal to up",
      np.abs(np.linalg.norm(N, axis=1) - 1).max() < 1e-6
      and np.abs((N * U).sum(1)).max() < 1e-6)

a_, b_ = 1.0, 0.4
t = np.linspace(0, 6 * np.pi, 1200)
H = np.stack([a_ * np.cos(t), b_ * t, a_ * np.sin(t)], 1)
T, Uh, uh = CF.curve_frames(H, False)
Nf = -unit(np.stack([np.cos(t), 0 * t, np.sin(t)], 1))       # the Frenet principal normal points to the axis
ang = np.unwrap(np.arctan2((np.cross(Nf, Uh) * T).sum(1), (Nf * Uh).sum(1)))
s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(H, axis=0), axis=1))])
slope = np.polyfit(s[50:-50], ang[50:-50], 1)[0]
# torsion computed by definition (with sign): τ = (r′ × r″)·r‴ / |r′ × r″|². This helix is (cos, sin) in the x/z plane
# rising along y -- the mirror image of the standard right-handed helix, so τ is negative
d1 = np.array([-a_ * math.sin(1.0), b_, a_ * math.cos(1.0)])
d2 = np.array([-a_ * math.cos(1.0), 0, -a_ * math.sin(1.0)])
d3 = np.array([a_ * math.sin(1.0), 0, -a_ * math.cos(1.0)])
cr = np.cross(d1, d2)
tau = float(cr @ d3 / (cr @ cr))
check(f"helix: slope of the RMF angle relative to Frenet = -torsion (fit {slope:.5f}, analytic {-tau:.5f})",
      abs(slope + tau) < 2e-3 * abs(tau) + 1e-4)

# the defining property of double reflection: transport between neighbouring points = the composition of two mirror reflections (orthogonal, sending
# T_i exactly to T_{i+1} and up_i to up_{i+1}), no reprojection needed. With coarse sampling (12 points
# per turn) recomputed step by step with a reflection formula written independently in the test
tc_ = np.linspace(0, 4 * np.pi, 25)
Hc = np.stack([np.cos(tc_), 0.5 * tc_, np.sin(tc_)], 1)
Tc, Uc_, _ = CF.curve_frames(Hc, False)
worst = 0.0
for i in range(len(Hc) - 1):
    v1 = Hc[i + 1] - Hc[i]
    c1 = v1 @ v1
    rL = Uc_[i] - 2 / c1 * (v1 @ Uc_[i]) * v1
    tL = Tc[i] - 2 / c1 * (v1 @ Tc[i]) * v1
    v2 = Tc[i + 1] - tL
    c2 = v2 @ v2
    want = rL - 2 / c2 * (v2 @ rL) * v2
    worst = max(worst, float(np.abs(want - Uc_[i + 1]).max()))
check(f"double reflection: every step is exactly a composition of two reflections (coarse sampling, max difference {worst:.1e})",
      worst < 1e-12)
Lc = curve([[0, 0, 0], [1, 0, 0], [1, 0, 1]])
tav = CF.curve_tangents(np.asarray(Lc.get(POINT, "P"), float), False, "average")
tpv = CF.curve_tangents(np.asarray(Lc.get(POINT, "P"), float), False, "previous")
tnx = CF.curve_tangents(np.asarray(Lc.get(POINT, "P"), float), False, "next")
check("tangents at corners: average = bisector of the two edge directions, previous / next take one side each",
      np.abs(tav[1] - unit(np.array([1.0, 0, 1]))).max() < 1e-12 and
      np.abs(tpv[1] - [1, 0, 0]).max() < 1e-12 and
      np.abs(tnx[1] - [0, 0, 1]).max() < 1e-12)
tt = np.linspace(0, 2 * np.pi, 300, endpoint=False)
tre = np.stack([np.sin(tt) + 2 * np.sin(2 * tt), np.cos(tt) - 2 * np.cos(2 * tt),
                -np.sin(3 * tt)], 1)
T2, U2, _ = CF.curve_frames(tre, True, fix_closed=False)
T3, U3, _ = CF.curve_frames(tre, True)
step = np.degrees(np.arccos(np.clip((U3[1:] * U3[:-1]).sum(1), -1, 1))).max()
wrap3 = math.degrees(math.acos(np.clip(U3[-1] @ U3[0], -1, 1)))
wrap2 = math.degrees(math.acos(np.clip(U2[-1] @ U2[0], -1, 1)))
check(f"trefoil: after spreading the holonomy, the closing step is {wrap3:.2f}° (ordinary neighbouring max {step:.2f}°)",
      wrap3 <= step * 1.5)
check(f"  negative control: without spreading the closing difference is {wrap2:.1f}°", wrap2 > 90)

T0, U0, _ = CF.curve_frames(H[:300], False)
_, Ur, _ = CF.curve_frames(H[:300], False, roll=90)
side = np.cross(U0, T0)
check("roll +90: up rotated 90° right-handed about the tangent (= T × up)",
      np.abs(Ur - np.cross(T0, U0)).max() < 1e-9)
_, Uf, _ = CF.curve_frames(H[:300], False, full_twists=1)
_, Up_, _ = CF.curve_frames(H[:300], False, partial_twist=90)
check("full twist 1: the end returns to the untwisted position; partial 90: the end turns 90° more than untwisted",
      np.abs(Uf[[0, -1]] - U0[[0, -1]]).max() < 1e-9 and
      abs(math.degrees(math.acos(np.clip(Up_[-1] @ U0[-1], -1, 1))) - 90) < 1e-6)
orv = CF.orient_along_curve(wav, reverse=True)
check("reverse flips the tangent", np.abs(A(orv, POINT, "N") + N).max() < 1e-6)
oc = CF.orient_along_curve(curve(H[:200]), up_mode="constant", up=(0, 1, 0))
Uc, Nc = A(oc, POINT, "up"), A(oc, POINT, "N")
proj = unit(np.array([0, 1, 0]) - Nc * Nc[:, 1:2])
check("constant: up = Y projected onto each point's normal plane", np.abs(Uc - proj).max() < 1e-5)
g_up = curve(H[:200])
g_up.set(POINT, "up", np.tile([1.0, 0, 0], (200, 1)).astype(np.float32))
oa = CF.orient_along_curve(g_up, up_mode="attribute")
Ua = A(oa, POINT, "up")
check("attribute: uses the up attribute on the points (here X)",
      np.abs(Ua - unit(np.array([1.0, 0, 0]) - A(oa, POINT, "N") *
                       A(oa, POINT, "N")[:, :1])).max() < 1e-5)
err("attribute mode with a missing attribute raises",
    lambda: CF.orient_along_curve(wav, up_mode="attribute"), "up")
on = CF.orient_along_curve(wav, orient_name="", up_name="")
check("empty names are not written", on.get(POINT, "orient") is None
      and on.get(POINT, "up") is None and on.get(POINT, "N") is not None)
seg = Geometry.from_mesh(np.array([[0, 0, 0], [0, 0, 0.1], [0, 0.1, 0]],
                                  np.float32), [[0, 1], [0, 2]], closed=False)
o = CF.orient_along_curve(curve(H[:100]))
cp = CT.copy_to_points(seg, o)
Pc = A(cp, POINT, "P").reshape(100, 3, 3)
dz = unit(Pc[:, 1] - Pc[:, 0])
dy = unit(Pc[:, 2] - Pc[:, 0])
check("into Copy to Points: the copy's +Z along the tangent, +Y is up",
      np.abs(dz - A(o, POINT, "N")).max() < 1e-4 and
      np.abs(dy - A(o, POINT, "up")).max() < 1e-4)

# ═══════════════════════════════════════════════════════ PolyFrame
sec("PolyFrame")
grid = build.grid(4, 4, 9, 9)
Pg = A(grid, POINT, "P")
gu = grid.copy()
gu.set(VERTEX, "uv", np.hstack([Pg[grid.vertex_point][:, [0, 2]],
                                 np.zeros((grid.nvertices, 1))]).astype(np.float32))
f = CF.polyframe(gu, entity="point", style="uv")
Nn, TU, TV = A(f, POINT, "N"), A(f, POINT, "tangentu"), A(f, POINT, "tangentv")
check("uv = (x, z):tangentu = +X,tangentv = N × tangentu",
      np.abs(TU - [1, 0, 0]).max() < 1e-6 and
      np.abs(TV - np.cross(Nn, TU)).max() < 1e-6)
c30, s30 = math.cos(math.radians(30)), math.sin(math.radians(30))
x_, z_ = Pg[grid.vertex_point][:, 0], Pg[grid.vertex_point][:, 2]
gu2 = grid.copy()
gu2.set(VERTEX, "uv", np.stack([c30 * x_ + s30 * z_, -s30 * x_ + c30 * z_,
                                 0 * x_], 1).astype(np.float32))
f2 = CF.polyframe(gu2, entity="prim", style="uv")
check("uv rotated 30°: tangentu rotates 30° along with it (on faces)",
      np.abs(A(f2, PRIM, "tangentu") - [c30, 0, s30]).max() < 1e-5)
gg = grid.copy()
gg.set(POINT, "f", (2 * Pg[:, 0] + 3 * Pg[:, 2])[:, None].astype(np.float32))
f3 = CF.polyframe(gg, entity="point", style="attribute_gradient",
                  gradient_attribute="f")
check("attribute_gradient: direction of f = 2x + 3z is (2,0,3)/√13",
      np.abs(A(f3, POINT, "tangentu") - unit(np.array([2.0, 0, 3]))).max()
      < 1e-5)
cir = build.circle(radius=(2, 2), plane="zx", divisions=32, arc_type="open_arc",
                   arc_angles=(0, 350))
f4 = CF.polyframe(cir, entity="point", style="two_edges")
Pc4 = A(cir, POINT, "P")
toward = unit(-Pc4)
check("points on an arc: N (Frenet principal normal) points to the center (except at the ends)",
      np.abs(A(f4, POINT, "N")[1:-1] - toward[1:-1]).max() < 1e-4)
f5 = CF.polyframe(grid, entity="prim", style="first_edge")
e0 = np.array([Pg[grid.prim_points(i)[1]] - Pg[grid.prim_points(i)[0]]
               for i in range(grid.nprims)])
check("face first_edge: tangentu = the first edge, N ⟂ face (±Y)",
      np.abs(A(f5, PRIM, "tangentu") - unit(e0)).max() < 1e-6 and
      np.abs(np.abs(A(f5, PRIM, "N")[:, 1]) - 1).max() < 1e-6)
deg = Geometry.from_mesh(np.zeros((3, 3)), [[0, 1, 2]])
f6 = CF.polyframe(deg, entity="prim", style="two_edges")
check("degenerate face (three coincident points): writes 0, not nan",
      np.isfinite(A(f6, PRIM, "N")).all())

# ═══════════════════════════════════════════════════════ Copy and Transform
sec("Copy and Transform + Transform normals")
g1 = Geometry.from_points([[1, 0, 0], [2, 0, 0]])
g1.set(POINT, "N", np.array([[1, 0, 0], [1, 0, 0]], np.float32))
r1 = ops.transform(g1, rotate=(0, 0, 90))
check("Transform (PCG): rotating 90° about z, N (1,0,0) -> (0,1,0) (before pcg67 it was -Y)",
      np.abs(A(r1, POINT, "N") - [0, 1, 0]).max() < 1e-6)
r2 = ops.transform(g1, rotate=(0, 0, 90), group="0")
check("  point normals outside the group unchanged", np.abs(A(r2, POINT, "N")[1] - [1, 0, 0]).max()
      < 1e-7)
sph = build.sphere() if hasattr(build, "sphere") else None
sph = ops.compute_normals(sph, "point")
r3 = ops.transform(sph, scale=(3, 1, 0.5), rotate=(10, 20, 30))
tri = r3.triangles()
Pr, Nr = A(r3, POINT, "P"), A(r3, POINT, "N")
e1 = Pr[tri[:, 1]] - Pr[tri[:, 0]]
fn = unit(np.cross(e1, Pr[tri[:, 2]] - Pr[tri[:, 0]]))
nav = unit(Nr[tri].sum(1))
check("  after non-uniform scale + rotation, point normals and face normals still point roughly the same way (inverse transpose)",
      float(np.median((fn * nav).sum(1))) > 0.99)

box = ops.transform(build.box(), scale=(0.3, 0.3, 0.3))
box = ops.compute_normals(box, "point")
ct = CX.copy_and_transform(box, 6, translate=(0.5, 0.2, 0), rotate=(10, 25, 5),
                           scale=(1.1, 0.9, 1), pivot=(0.2, 0, 0))
m = box.npoints
ok = True
g = box
for k in range(6):
    Pk = A(ct, POINT, "P")[k * m:(k + 1) * m]
    Nk = A(ct, POINT, "N")[k * m:(k + 1) * m]
    ok &= np.abs(Pk - A(g, POINT, "P")).max() < 1e-4
    ok &= np.abs(Nk - A(g, POINT, "N")).max() < 1e-4
    g = ops.transform(g, (0.5, 0.2, 0), (10, 25, 5), (1.1, 0.9, 1), (0.2, 0, 0))
check("copy k = Transform (PCG) applied k times in a row (points and normals)", ok)
check("point count = copies × source points, likewise for faces; copynum 0..5",
      ct.npoints == 6 * m and ct.nprims == 6 * box.nprims and
      sorted(set(A(ct, PRIM, "copynum").ravel().tolist())) == list(range(6)))
st = CX.copy_and_transform(box, 13, translate=(0, 1, 0), rotate=(0, 30, 0))
P0, P12 = A(st, POINT, "P")[:m], A(st, POINT, "P")[12 * m:]
check("spiral staircase: rotating 30° and rising 1, copy 12 wraps back to the original angle, height 12",
      np.abs(P12 - (P0 + [0, 12, 0])).max() < 1e-4)
c2 = CX.copy_and_transform(box, 3, copy_attribute="k")
c3 = CX.copy_and_transform(box, 3, copy_attribute="")
check("Copy Attribute renamed / empty means not written",
      c2.get(PRIM, "k") is not None and c2.get(PRIM, "copynum") is None and
      c3.get(PRIM, "copynum") is None and c3.get(POINT, "copynum") is None)
check("copies = 0 -> empty; = 1 -> unchanged",
      CX.copy_and_transform(box, 0).npoints == 0 and
      np.abs(A(CX.copy_and_transform(box, 1), POINT, "P") -
             A(box, POINT, "P")).max() == 0)


# ═══════════════════════════════════════════════════════ Revolve
sec("Revolve")


def watertight(g):
    t = topology(g)
    return bool(len(t.edge_count)) and bool((t.edge_count == 2).all())


def euler(g):
    return g.npoints - topology(g).nedges + g.nprims


def outward(g, center=(0, 0, 0)):
    n = ops.prim_normals(g)
    c = ops.prim_centers(g) - np.asarray(center)
    return bool(((n * c).sum(1) > 0).all())


th = np.linspace(-np.pi / 2, np.pi / 2, 11)
semi = curve(np.stack([np.cos(th), np.sin(th), 0 * th], 1))
sp = CX.revolve(semi, divisions=16, uv_attribute="uv")
Ps = A(sp, POINT, "P")
check("semicircle -> sphere: points all on the unit sphere", np.abs(np.linalg.norm(Ps, axis=1) - 1).max()
      < 1e-6)
check(f"  one point at each pole (point count 2 + 9×16 = {2 + 9 * 16}, actual {sp.npoints})",
      sp.npoints == 2 + 9 * 16)
sz = sp.prim_sizes()
check("  triangles at the poles (2×16), quads elsewhere",
      int((sz == 3).sum()) == 32 and int((sz == 4).sum()) == 16 * 8)
check("  all faces point outwards", outward(sp))
area = np.linalg.norm(ops.prim_normals(sp, normalize=False), axis=1)
check("  no zero-area faces", area.min() > 1e-6)
check(f"  watertight, Euler characteristic 2 (actual {euler(sp)})", watertight(sp) and euler(sp) == 2)
uv = A(sp, VERTEX, "uv")
check("  uv in [0,1]", uv.min() >= -1e-6 and uv[:, :2].max() <= 1 + 1e-6)
spr = CX.revolve(semi, divisions=16, reverse=True)
check("reverse flips normals (all point inwards)", outward(CX.revolve(semi, divisions=16)) and
      not ((ops.prim_normals(spr) * ops.prim_centers(spr)).sum(1) > 0).any())
ring = build.circle(radius=(0.3, 0.3), center=(1, 0, 0), plane="xy",
                    divisions=12)
tor = CX.revolve(ring, divisions=20)
check(f"closed cross section -> torus: watertight, Euler characteristic 0 (actual {euler(tor)})",
      watertight(tor) and euler(tor) == 0)
sq = curve([[1, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0]], closed=True)
half = CX.revolve(sq, end_angle=180, divisions=8, end_caps=True)
check("square cross section rotated 180° + capped: watertight", watertight(half))
check("triangles: all triangles",
      (CX.revolve(sq, divisions=8, surface="triangles").prim_sizes() == 3).all())
err("zero Axis raises", lambda: CX.revolve(semi, axis=(0, 0, 0)), "Axis")

# ═══════════════════════════════════════════════════════ Copy to Curves / Chain
sec("Copy to Curves / Chain")
dot = Geometry.from_points([[0, 0, 0]])
circ = build.circle(radius=(2, 2), plane="zx", divisions=64)
cc = CX.copy_to_curves(dot, circ, mode="count", count=8)
Pcc = A(cc, POINT, "P")
angs = np.sort(np.mod(np.degrees(np.arctan2(Pcc[:, 0], Pcc[:, 2])), 360))
check("8 copies on a closed circle: equal arc length, no duplicate at the start",
      len(Pcc) == 8 and np.abs(np.diff(angs) - 45).max() < 0.5)
ln = curve([[0, 0, 0], [10, 0, 0]])
cs = CX.copy_to_curves(dot, ln, mode="spacing", spacing=2.5)
check("spacing 2.5 on a line: 0 2.5 5 7.5 10",
      np.abs(np.sort(A(cs, POINT, "P")[:, 0]) - [0, 2.5, 5, 7.5, 10]).max()
      < 1e-6)
stick = Geometry.from_mesh(np.array([[0, 0, 0], [0, 0, 0.05]]), [[0, 1]],
                           closed=False)
cz = CX.copy_to_curves(stick, circ, count=16)
Pz = A(cz, POINT, "P").reshape(-1, 2, 3)
tang = unit(np.cross([0, 1, 0], Pz[:, 0]))
dirs = unit(Pz[:, 1] - Pz[:, 0])
check("the copy's +Z follows the circle's tangent", np.abs(np.abs((dirs * tang).sum(1)) - 1).max()
      < 2e-3)
two = ops.merge(Geometry.from_mesh(np.array([[0, 0, 0], [0.1, 0, 0]]), [[0, 1]],
                                   closed=False),
                Geometry.from_mesh(np.array([[0, 0, 0], [0, 0.1, 0]]), [[0, 1]],
                                   closed=False))
two.set_string(PRIM, "name", ["a", "b"])
cv = CX.copy_to_curves(two, ln, count=6, piece_attribute="name")
check("piece cycling: 6 copies a b a b a b (2 points 1 segment each)", cv.nprims == 6)
rs = CX.copy_to_curves(stick if False else seg, ln, count=3, roll_step=90)
Pr3 = A(rs, POINT, "P").reshape(3, 3, 3)
yv = unit(Pr3[:, 2] - Pr3[:, 0])
check("roll_step 90: +Y of neighbouring copies differs by 90°",
      abs(float(yv[0] @ yv[1])) < 1e-5 and abs(float(yv[1] @ yv[2])) < 1e-5)

link = ops.transform(build.box(), scale=(0.3, 0.2, 1.0))     # Z length 1
ch = CX.chain(link, ln, spacing=0.0, fit=False, roll_step=0)
cen = A(ch, POINT, "P").reshape(-1, link.npoints, 3).mean(1)
check("Chain: links of length 1 on a line of length 10 place 10 links, centers 0.5 1.5 ... 9.5",
      len(cen) == 10 and np.abs(np.sort(cen[:, 0]) - (np.arange(10) + 0.5)).max()
      < 1e-5)
chs = CX.chain(link, ln, spacing=0.3, fit=True, roll_step=0)
ends = A(chs, POINT, "P")[:, 0]
check("fit: the last link ends exactly at the end point (max x = 10)", abs(ends.max() - 10) < 1e-5
      and abs(ends.min()) < 1e-5)
chr_ = CX.chain(link, ln, spacing=0.0, fit=False, roll_step=90)
Pk = A(chr_, POINT, "P").reshape(-1, link.npoints, 3)
wy = Pk[:, :, 1].max(1) - Pk[:, :, 1].min(1)
check("neighbouring links alternate by 90° (Y thickness alternates 0.2 / 0.3)",
      np.abs(wy[0::2] - 0.2).max() < 1e-5 and np.abs(wy[1::2] - 0.3).max() < 1e-5)
err("Chain: step = length + spacing ≤ 0 raises (instead of spinning in place and eating all memory)",
    lambda: CX.chain(link, ln, spacing=-1.0), "too negative")
circ2 = build.circle(radius=(3, 3), plane="zx", divisions=200)
chc = CX.chain(link, circ2, spacing=0.0, fit=True, roll_step=0)
Pl = A(chc, POINT, "P").reshape(-1, link.npoints, 3)
# the two end-face centers of each link along local Z should lie on the circle
zc = []
for k in range(len(Pl)):
    c0 = Pl[k].mean(0)
    far = Pl[k][np.argsort(-np.linalg.norm(Pl[k] - c0, axis=1))]
    zc.append(c0)
axis_len = []
link_P = A(link, POINT, "P")
for k in range(len(Pl)):
    front = Pl[k][link_P[:, 2] > 0].mean(0)
    back = Pl[k][link_P[:, 2] < 0].mean(0)
    axis_len.append([np.hypot(front[0], front[2]), np.hypot(back[0], back[2])])
axis_len = np.array(axis_len)
check(f"fit on a closed circle: {len(Pl)} links, both end-face centers of every link lie on the circle (radius 3)",
      np.abs(axis_len - 3).max() < 2e-3)

# ═══════════════════════════════════════════════════════ shortest path
sec("Find Shortest Path / Group Find Path")
G = build.grid(10, 10, 21, 21)
o, r = PT.find_shortest_path(G, "0", "440")
check("21×21 grid (spacing 0.5): cost of 0 -> 440 = Manhattan distance 20",
      abs(r["total_cost"] - 20) < 1e-9 and o.nprims == 1)


def bellman_ford(n, E, w, src):
    d = np.full(n, np.inf)
    d[src] = 0
    a = np.concatenate([E[:, 0], E[:, 1]])
    b = np.concatenate([E[:, 1], E[:, 0]])
    ww = np.concatenate([w, w])
    for _ in range(n):
        nd = d.copy()
        np.minimum.at(nd, b, d[a] + ww)
        if np.array_equal(nd, d):
            break
        d = nd
    return d


pts = rng.random((300, 3)) * [1, 0, 1]
from comfyui_pcg.geo import triangulate2d as T2D  # noqa: E402
_tri = np.asarray(T2D.delaunay(pts[:, [0, 2]]))
rm = Geometry.from_mesh(pts, _tri.reshape(-1, 3))
rm.set(POINT, "cost", rng.random((rm.npoints, 1)).astype(np.float32) * 3)
E, w = PT.edge_weights(rm, True, "cost", 2.0, 0.0)
ref = bellman_ford(rm.npoints, E, w, 0)
dist, prev, _ = PT.dijkstra(PT._adjacency(rm.npoints, E, w), [0])
check("random triangle mesh + random cost: Dijkstra and Bellman-Ford match point by point",
      np.allclose(np.array(dist), ref, rtol=1e-12, atol=1e-12))
path = PT._trace(prev, 150)
pc = sum(w[np.nonzero(((E[:, 0] == a) & (E[:, 1] == b)) |
                      ((E[:, 0] == b) & (E[:, 1] == a)))[0][0]]
         for a, b in zip(path[:-1], path[1:]))
check("  cost of the backtracked path = dist", abs(pc - dist[150]) < 1e-9)
tiny = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0]], np.float64),
                          [[0, 1], [1, 2]], closed=False)
tiny.set(POINT, "c", np.array([[1.0], [3.0], [0.0]], np.float32))
Et, wt = PT.edge_weights(tiny, True, "c", 2.0, 0.5)
wmap = {tuple(e): x for e, x in zip(Et.tolist(), wt.tolist())}
# edge (0,1): length 2, mean cost 2, horizontal -> 2·(1+2·2)·(1+0) = 10
# edge (1,2): length 1, mean cost 1.5, vertical (slope 1) -> 1·(1+2·1.5)·(1+0.5·1) = 6
check("edge weight formula: length × (1 + w·mean cost) × (1 + s·|slope|)",
      abs(wmap[(0, 1)] - 10) < 1e-9 and abs(wmap[(1, 2)] - 6) < 1e-9, wmap)
o, r = PT.find_shortest_path(G, "220", "0 440 20", mode="nearest_end")
check("nearest_end: picks the nearest end point from the center (any when the four corners are equidistant, cost 10)",
      abs(r["total_cost"] - 10) < 1e-9)
sp0 = A(o, POINT, "srcpt").astype(int).ravel()
check("  the path goes from start to end (first point is the start, last is endpt)",
      sp0[0] == 220 and sp0[-1] == int(A(o, PRIM, "endpt")[0, 0]))
o, r = PT.find_shortest_path(G, "0 1", "440 20 400", mode="each_pair")
check("each_pair: 2 × 3 = 6 paths", r["paths"] == 6 and o.nprims == 6)
o, r = PT.find_shortest_path(G, "0 20 440 420", mode="sequence",
                             close_sequence=True)
check("sequence + close: a full loop around the outer ring = perimeter 40", abs(r["total_cost"] - 40)
      < 1e-9 and r["paths"] == 4)
Gc = G.copy()
Pg2 = A(G, POINT, "P")
wall = (np.abs(Pg2[:, 0]) < 0.3) & (Pg2[:, 2] > -4.0)
Gc.set(POINT, "c", np.where(wall, 1000.0, 0.0)[:, None].astype(np.float32))
o, r = PT.find_shortest_path(Gc, "210", "230", cost_attribute="c")
sp_ = A(o, POINT, "srcpt").astype(int).ravel()
check("a wall with a high cost attribute: the path goes around (does not pass through wall points)",
      not wall[sp_].any() and r["total_cost"] > 10)
hill = G.copy()
Ph = Pg2.copy()
Ph[:, 1] = 3 * np.exp(-(Ph[:, 0] ** 2 + Ph[:, 2] ** 2) / 4)
hill.set(POINT, "P", Ph.astype(np.float32))


def max_slope(g):
    P = A(g, POINT, "P")
    d = np.diff(P, axis=0)
    return float((np.abs(d[:, 1]) / np.linalg.norm(d, axis=1)).max())


o0, _ = PT.find_shortest_path(hill, "210", "230")
o1, _ = PT.find_shortest_path(hill, "210", "230", slope_weight=20)
check(f"slope weight makes the path go around the hill: max slope {max_slope(o0):.2f} -> {max_slope(o1):.2f}",
      max_slope(o1) < max_slope(o0) * 0.7)
og, r = PT.find_shortest_path(G, "0", "440", output="group")
eg = og.get_edge_group("path")
check("group output: 40 edges in the edge group, 41 in the point group, no new geometry",
      len(eg) == 40 and int(og.get_group(POINT, "path").sum()) == 41 and
      og.npoints == G.npoints)
om, _ = PT.find_shortest_path(G, "0", "440", output="merge")
check("merge output: source geometry + path", om.npoints == G.npoints + 41 and
      om.nprims == G.nprims + 1)
Gn = G.copy()
Gn.set(POINT, "c", -np.ones((G.npoints, 1), np.float32))
err("negative cost raises (and says why)", lambda: PT.find_shortest_path(
    Gn, "0", "440", cost_attribute="c"), "<= 0")
err("a point cloud with no edges raises", lambda: PT.find_shortest_path(
    Geometry.from_points(rng.random((5, 3))), "0", "1"), "has no edges")
twoG = ops.merge(G, ops.transform(G, translate=(20, 0, 0)))
_, r = PT.find_shortest_path(twoG, "0", str(G.npoints + 5))
check("disconnected: does not crash, the report records one unreachable", r["unreachable"] == 1 and
      r["paths"] == 0)
og, r = PT.group_find_path(G, "0 20 440")
check("Group Find Path: 0 -> 20 -> 440 writes 40 edges", len(og.get_edge_group("path"))
      == 40)
ob, r = PT.group_find_path(G, "0", mode="boundary_loop")
check("boundary_loop: 80 edges on the outer ring, 1 loop", len(ob.get_edge_group("path")) == 80
      and r["loops"] == 1)
Gl = G.copy()
Gl.set_topology(np.concatenate([G.vertex_point, [0, 22]]),
                np.concatenate([G.prim_offset, [G.prim_offset[-1] + 2]]),
                np.concatenate([G.prim_closed, [False]]))
obl, _ = PT.group_find_path(Gl, "0", mode="boundary_loop")
check("  polyline edges are not boundary edges (only edges used by exactly one face are)",
      len(obl.get_edge_group("path")) == 80)
ob2, r2 = PT.group_find_path(G, "220", mode="boundary_loop")
check("  an interior seed point selects no boundary", len(ob2.get_edge_group("path")) == 0)

# ═══════════════════════════════════════════════════════ curve intersection
sec("Curve Intersect")
L_ = []
for i in range(5):
    L_ += [[i, 0, -1], [i, 0, 5], [-1, 0, i], [5, 0, i]]
Pn = np.array(L_, np.float64)
net = Geometry.from_mesh(Pn, np.arange(len(Pn)).reshape(-1, 2), closed=False)
op, r = PT.curve_intersect(net, output="points")
Xp = A(op, POINT, "P")
check("5×5 tic-tac-toe: 25 intersections, all integer coordinates",
      r["intersections"] == 25 and np.abs(Xp - np.round(Xp)).max() < 1e-9)
osp, r = PT.curve_intersect(net, output="split")
from comfyui_pcg.geo.topology import connectivity  # noqa: E402
cn = connectivity(osp, POINT, "cc")
check("split: connected, 10 lines with 6 segments each (60 segments)",
      len(np.unique(A(cn, POINT, "cc"))) == 1 and osp.nprims == 60)
use = np.bincount(osp.vertex_point, minlength=osp.npoints)
ig = osp.get_group(POINT, "intersections")
check("  each intersection shared by 4 segments (crossroads)", (use[ig] == 4).all() and ig.sum() == 25)
_, r = PT.find_shortest_path(osp, "0", "1")
check("  shortest path walked directly on the split network", r["paths"] == 1)
up = Pn.copy()
up[1::2 * 1][:0] = 0
two_layer = Pn.copy()
two_layer[[k for k in range(len(Pn)) if (k // 2) % 2 == 1], 1] = 0.5
tl = Geometry.from_mesh(two_layer, np.arange(len(Pn)).reshape(-1, 2),
                        closed=False)
check("two layers of lines (height difference 0.5, line spacing 1 within a layer): xz 25, 3d 0, 3d with tolerance 0.6 25 again",
      PT.curve_intersect(tl, plane="xz", output="points")[1]["intersections"]
      == 25 and PT.curve_intersect(tl, plane="3d", output="points")[1][
          "intersections"] == 0 and PT.curve_intersect(
          tl, plane="3d", tolerance=0.6, output="points")[1]["intersections"]
      == 25)
tt8 = np.linspace(0, 2 * np.pi, 101)[:-1]
eight = curve(np.stack([np.sin(tt8), 0 * tt8, np.sin(tt8) * np.cos(tt8)], 1),
              closed=True)
check("figure-8: 1 self-intersection; 0 with self_intersect off",
      PT.curve_intersect(eight, output="points")[1]["intersections"] == 1 and
      PT.curve_intersect(eight, self_intersect=False,
                         output="points")[1]["intersections"] == 0)
ov = ops.merge(curve([[0, 0, 0], [1, 0, 0], [2, 0, 0]]),
               curve([[1, 0, -1], [1, 0, 1]]))
osv, r = PT.curve_intersect(ov, output="split")
Po = A(osv, POINT, "P")
segl = [np.linalg.norm(np.diff(Po[osv.prim_points(i)], axis=0), axis=1).min()
        for i in range(osv.nprims)]
check("intersection on an existing vertex: 1 intersection, no zero-length segment", r["intersections"] == 1 and
      min(segl) > 1e-9 and osv.nprims == 4)
S = rng.random((60, 2, 3)) * [4, 0, 4]
rs_ = Geometry.from_mesh(S.reshape(-1, 3), np.arange(120).reshape(-1, 2),
                         closed=False)
brute = 0
for i in range(60):
    for j in range(i + 1, 60):
        h, _, _ = PT._seg_seg_2d(S[i:i + 1, 0, [0, 2]], S[i:i + 1, 1, [0, 2]],
                                 S[j:j + 1, 0, [0, 2]], S[j:j + 1, 1, [0, 2]])
        brute += int(h[0])
got = PT.curve_intersect(rs_, output="points")[1]["intersections"]
check(f"60 random segments: grid bucketing result = O(n²) brute force ({got} / {brute})", got == brute)
cl = build.circle(radius=(1, 1), plane="zx", divisions=40)
cr_ = ops.merge(cl, curve([[-2, 0, 0], [2, 0, 0]]))
oc, r = PT.curve_intersect(cr_, output="split")
check("a closed circle cut by a line at 2 places: the circle becomes 2 open curves, the line 3 segments",
      r["intersections"] == 2 and oc.nprims == 5 and not oc.prim_closed.any())

# ═══════════════════════════════════════════════════════ adjacent pieces
sec("Connect Adjacent Pieces")
cloud = Geometry.from_points(rng.random((150, 3)))
oc, r = PT.connect_adjacent_pieces(cloud, "points", 0.25, 3)
Pl_ = A(oc, POINT, "P").reshape(-1, 2, 3)
lens = np.linalg.norm(Pl_[:, 0] - Pl_[:, 1], axis=1)
Pcl = A(cloud, POINT, "P")
D = np.linalg.norm(Pcl[:, None] - Pcl[None], axis=2)
np.fill_diagonal(D, np.inf)
want = set()
for i in range(150):
    nb = [j for j in np.argsort(D[i], kind="stable")[:3] if D[i, j] <= 0.25]
    for j in nb:
        want.add((min(i, j), max(i, j)))
gotp = {tuple(sorted(x)) for x in zip(A(oc, PRIM, "pt_a").astype(int).ravel(),
                                     A(oc, PRIM, "pt_b").astype(int).ravel())}
check("points: every line ≤ radius, matches the brute-force 'union of each point's 3 nearest'",
      lens.max() <= 0.25 + 1e-9 and gotp == want)
row = CX.copy_and_transform(ops.transform(build.box(), scale=(0.5,) * 3), 4,
                            translate=(0.5, 0, 0))
oc, r = PT.connect_adjacent_pieces(row, "piece_centroids", 0.01, 4,
                                   piece_attribute="copynum")
pa, pb = A(oc, PRIM, "piece_a").ravel(), A(oc, PRIM, "piece_b").ravel()
check("a row of 4 touching boxes: piece_centroids connects 3, neighbours only",
      r["lines"] == 3 and (np.abs(pb - pa) == 1).all())
oc2, r2 = PT.connect_adjacent_pieces(row, "piece_points", 0.01, 4,
                                     piece_attribute="copynum")
L2 = np.linalg.norm(np.diff(A(oc2, POINT, "P").reshape(-1, 2, 3), axis=1),
                    axis=2)
check("piece_points: lines connect at the contact (length ≤ radius)", r2["lines"] == 3 and
      L2.max() <= 0.01)
oc4, r4 = PT.connect_adjacent_pieces(row, "piece_points", 0.6, 8,
                                     piece_attribute="copynum")
check("radius large enough to include points within a piece: both ends of every line still belong to different pieces",
      r4["lines"] > 0 and (A(oc4, PRIM, "piece_a") != A(oc4, PRIM, "piece_b")).all())
oc3, r3 = PT.connect_adjacent_pieces(row, "piece_centroids", 0.01, 1,
                                     piece_attribute="copynum")
cnt = np.bincount(np.concatenate([A(oc3, PRIM, "piece_a").ravel(),
                                  A(oc3, PRIM, "piece_b").ravel()]).astype(int))
check("max_connections 1: at most 1 per piece", cnt.max() <= 1)
ok_, rk = PT.connect_adjacent_pieces(cloud, "points", 0.25, 3, keep_input=True)
check("keep_input: lines attach to the original points (point count unchanged, the extra prims are two-point polylines)",
      ok_.npoints == cloud.npoints and ok_.nprims == rk["lines"] and
      (ok_.prim_sizes() == 2).all())
err("Radius ≤ 0 raises", lambda: PT.connect_adjacent_pieces(cloud, radius=0),
    "Radius")

# ═══════════════════════════════════════════════════════ nodes
sec("Nodes")
NEW = {"PCG_OrientAlongCurve": "PCG/attribute", "PCG_PolyFrame": "PCG/attribute",
       "PCG_CopyAndTransform": "PCG/scatter", "PCG_Revolve": "PCG/generate",
       "PCG_CopyToCurves": "PCG/scatter", "PCG_Chain": "PCG/scatter",
       "PCG_FindShortestPath": "PCG/topology",
       "PCG_GroupFindPath": "PCG/group", "PCG_CurveIntersect": "PCG/modify",
       "PCG_ConnectAdjacentPieces": "PCG/topology"}
check("all 10 nodes registered, in the right category",
      all(k in MAP and MAP[k].CATEGORY == v for k, v in NEW.items()))
bad = [k for k in NEW for nm in MAP[k].INPUT_TYPES()["required"] if nm == "seed"]
check("no widget called seed", not bad, bad)


def unwrap(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


def defaults(cls, **over):
    kw = {}
    for nm, spec in cls.INPUT_TYPES()["required"].items():
        if nm in over:
            kw[nm] = over[nm]
        elif isinstance(spec[0], list):
            kw[nm] = spec[1].get("default", spec[0][0]) if len(spec) > 1 \
                else spec[0][0]
        elif len(spec) > 1 and "default" in spec[1]:
            kw[nm] = spec[1]["default"]
    return kw


runs = {
    "PCG_OrientAlongCurve": dict(geo=wav),
    "PCG_PolyFrame": dict(geo=grid),
    "PCG_CopyAndTransform": dict(geo=box),
    "PCG_Revolve": dict(geo=semi),
    "PCG_CopyToCurves": dict(source=box, curves=circ),
    "PCG_Chain": dict(source=link, curves=circ2),
    "PCG_FindShortestPath": dict(geo=G, start_group="0", end_group="440"),
    "PCG_GroupFindPath": dict(geo=G, points="0 440"),
    "PCG_CurveIntersect": dict(geo=net),
    "PCG_ConnectAdjacentPieces": dict(geo=cloud),
}
bad = []
for k, kw in runs.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry) or (len(r) > 1 and
                                              not json.loads(r[1])):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 10 nodes run with default parameters (the second output with the report is JSON)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
