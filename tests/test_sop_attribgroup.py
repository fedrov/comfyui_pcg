"""
pcg76: attributes, groups, points -- Attribute Composite, Attribute Mirror, Group from Attribute
Boundary, Partition, Tangent Field, Adaptive Prune, Point Replicate, Point Velocity.

Checks do not rely on the implementation itself:
  Attribute Composite   every mode correct on several hand-computed values; α / α attribute / pairing by id (shuffled, missing ids)
  Attribute Mirror      symmetric mesh: left side = the right side's function evaluated at the mirrored point; vectors reflected, quaternions still proper
                        rotations; on an asymmetric mesh surface mode is exact for linear attributes (negative control: nearest point is not exact)
  Group from Attr Bdry  grid in four quadrants -> 8 edges of the cross; uv seams; steps in point attributes; tolerance
  Partition             every element lands in exactly one group; floats / minus signs / odd characters in group names; colliding names merged
  Tangent Field         plane with one guide -> equals the guide everywhere; on a cylinder an axial / circumferential guide transported everywhere
                        is right; cross field 30° mod 90°; curvature alignment; on a sphere singularity index sum = n·χ (1 -> 2,
                        4 -> 8), torus 0
  Adaptive Prune        pairwise spacing of the kept points ≥ radius; every removed point neighbours a kept point of higher priority;
                        with variable radius the density follows
  Point Replicate       distributions in ball / on sphere / disk / gaussian (radial distribution, normal orthogonality, standard deviation);
                        random numbers seeded by id, removing one source point leaves the other clusters unchanged
  Point Velocity        translation exact; central difference of a rotation = analytic formula; constant acceleration exact; pairing by id
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

from comfyui_pcg.geo import attribgroup as AG           # noqa: E402
from comfyui_pcg.geo import tangentfield as TF          # noqa: E402
from comfyui_pcg.geo import pointops2 as PO             # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
from comfyui_pcg.geo.xform import quat_to_mat           # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, VERTEX, DETAIL  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

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


def Pd(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def A(g, cls, n):
    return np.asarray(g.get(cls, n), np.float64)


def pts(P):
    return Geometry.from_points(np.asarray(P, np.float32))


rng = np.random.default_rng(0)
# ═══════════════════════════════════════════════════════ Attribute Composite
sec("Attribute Composite")
g = pts(np.zeros((5, 3)))
Av = np.array([0.2, 0.5, 0.8, 0.0, 1.0])
Bv = np.array([0.6, 0.5, 0.3, 0.4, 0.25])
g.set(POINT, "a", Av[:, None].astype(np.float32))
g.set(POINT, "b", Bv[:, None].astype(np.float32))
want = {
    "over": Bv, "add": Av + Bv, "subtract": Av - Bv, "multiply": Av * Bv,
    "divide": Av / Bv, "screen": 1 - (1 - Av) * (1 - Bv),
    "overlay": np.array([2 * 0.2 * 0.6, 1 - 2 * 0.5 * 0.5, 1 - 2 * 0.2 * 0.7,
                         0.0, 1 - 2 * 0 * 0.75]),
    "min": np.minimum(Av, Bv), "max": np.maximum(Av, Bv),
    "difference": np.abs(Av - Bv), "average": (Av + Bv) / 2}
bad = []
for m, w in want.items():
    o, _ = AG.attribute_composite(g, None, "point", "a", "b", "out", m)
    if np.abs(A(o, POINT, "out")[:, 0] - w).max() > 1e-6:
        bad.append(m)
check("all 11 modes correct on hand-computed values (overlay splits into two branches at A < 0.5)", not bad, bad)
o, _ = AG.attribute_composite(g, None, "point", "a", "b", "out", "multiply", 0.25)
check("α = 0.25:A + 0.25·(A·B − A)", np.abs(A(o, POINT, "out")[:, 0] -
                                         (Av + 0.25 * (Av * Bv - Av))).max() < 1e-6)
z = pts(np.zeros((1, 3)))
z.set(POINT, "a", np.array([[1.0]], np.float32))
z.set(POINT, "b", np.array([[0.0]], np.float32))
o, _ = AG.attribute_composite(z, None, "point", "a", "b", "o", "divide")
check("divide: keeps A when dividing by 0", A(o, POINT, "o")[0, 0] == 1.0)
bg = pts(np.zeros((4, 3)))
bg.set(POINT, "Cd", np.full((4, 3), 0.5, np.float32))
bg.set(POINT, "id", np.array([[10], [11], [12], [13]], np.int32))
fg = pts(np.zeros((3, 3)))
fg.set(POINT, "Cd", np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32))
fg.set(POINT, "id", np.array([[12], [10], [99]], np.int32))
fg.set(POINT, "mask", np.array([[1.0], [0.5], [1.0]], np.float32))
o, r = AG.attribute_composite(bg, fg, "point", "Cd", "Cd", "Cd", "over", 1.0,
                              "mask", "attribute", "id")
C = A(o, POINT, "Cd")
check("pairing by id (foreground shuffled, with extra ids): matched ones blended by the α attribute, unmatched ones unchanged",
      np.allclose(C[0], [0.25, 0.75, 0.25]) and np.allclose(C[2], [1, 0, 0]) and
      np.allclose(C[1], 0.5) and np.allclose(C[3], 0.5) and r["matched"] == 2,
      C.round(3).tolist())
fd = fg.copy()
fd.set(POINT, "id", np.array([[12], [12], [99]], np.int32))
o, _ = AG.attribute_composite(bg, fd, "point", "Cd", "Cd", "Cd", "over", 1.0, "",
                              "attribute", "id")
check("same id twice in the foreground: the first one is used", np.allclose(A(o, POINT, "Cd")[2], [1, 0, 0]))
fk = fg.copy()
fk.set(POINT, "mask", np.array([[2.0], [-1.0], [1.0]], np.float32))
o, _ = AG.attribute_composite(bg, fk, "point", "Cd", "Cd", "Cd", "over", 1.0, "mask")
check("α clamped to [0,1] (α attribute 2 treated as 1, −1 as 0)",
      np.allclose(A(o, POINT, "Cd")[0], [1, 0, 0]) and
      np.allclose(A(o, POINT, "Cd")[1], 0.5))
o, r = AG.attribute_composite(bg, fg, "point", "Cd", "Cd", "Cd", "over")
check("pairing by index: foreground has only 3 points, the 4th is unchanged", np.allclose(A(o, POINT, "Cd")[3], 0.5)
      and np.allclose(A(o, POINT, "Cd")[:3], A(fg, POINT, "Cd")) and
      r["unmatched"] == 1)
o, _ = AG.attribute_composite(bg, fg, "point", "Cd", "mask", "Cd", "multiply")
check("single-component foreground broadcast to three components", np.allclose(A(o, POINT, "Cd")[:3],
                                  0.5 * np.array([[1], [0.5], [1]])))
o, _ = AG.attribute_composite(bg, fg, "point", "nothere", "Cd", "new", "over", 0.5)
check("missing background attribute treated as 0 (over writes a new attribute by α)",
      np.allclose(A(o, POINT, "new")[:3], 0.5 * A(fg, POINT, "Cd")))
sg = pts(np.zeros((2, 3)))
sg.set_string(POINT, "nm", np.array([["a"], ["b"]]))
sf = pts(np.zeros((2, 3)))
sf.set_string(POINT, "nm", np.array([["X"], ["Y"]]))
sf.set(POINT, "al", np.array([[1.0], [0.2]], np.float32))
o, _ = AG.attribute_composite(sg, sf, "point", "nm", "nm", "nm", "over", 1.0, "al")
check("strings: α > 0.5 takes the foreground", o.get(POINT, "nm")[:, 0].tolist() == ["X", "b"])
err("strings can't add", lambda: AG.attribute_composite(sg, sf, "point", "nm", "nm",
                                                   "nm", "add"), "over")
bx = build.box((1, 1, 1))
bx.set(PRIM, "w", np.arange(6, dtype=np.float32)[:, None])
o, _ = AG.attribute_composite(bx, None, "prim", "w", "w", "w2", "multiply")
check("prim class", np.allclose(A(o, PRIM, "w2")[:, 0], np.arange(6) ** 2))
dg = pts(np.zeros((1, 3)))
dg.set(DETAIL, "k", np.array([[2.0]], np.float32))
o, _ = AG.attribute_composite(dg, None, "detail", "k", "k", "k", "add")
check("detail class", A(o, DETAIL, "k")[0, 0] == 4.0)

# ═══════════════════════════════════════════════════════ Attribute Mirror
sec("Attribute Mirror")
gr = build.grid(4, 2, 9, 5)
P = Pd(gr)


def f3(x, z):
    return np.c_[x, z, x * z]


Cd = np.where((P[:, 0] > 0)[:, None], f3(P[:, 0], P[:, 2]), 9.0)
gr.set(POINT, "Cd", Cd.astype(np.float32))
gr.set(POINT, "N", np.tile([1.0, 2, 3], (gr.npoints, 1)).astype(np.float32))
R0 = np.linalg.qr(rng.normal(size=(3, 3)))[0]
R0 *= np.sign(np.linalg.det(R0))
from comfyui_pcg.geo.curveframe import mat_to_quat  # noqa: E402
q0 = mat_to_quat(R0[None])[0]
gr.set(POINT, "orient", np.tile(q0, (gr.npoints, 1)).astype(np.float32))
o, r = AG.attribute_mirror(gr, "Cd N orient")
Q = A(o, POINT, "Cd")
L = P[:, 0] < 0
check("symmetric grid: left Cd = the right side's function at the mirrored point",
      np.abs(Q[L] - f3(-P[L, 0], P[L, 2])).max() < 1e-6, r["mirrored_points"])
check("  points on the right and on the plane unchanged", np.abs(Q[~L] - Cd[~L]).max() == 0)
check("N reflected across the plane: (1,2,3) -> (−1,2,3)", np.allclose(A(o, POINT, "N")[L], [-1, 2, 3]))
H = np.diag([-1.0, 1, 1])
Rm = quat_to_mat(A(o, POINT, "orient")[L])
check("orient: R' = H·R·H, determinant still +1 (proper rotation, not a mirror)",
      np.abs(Rm - H @ R0 @ H).max() < 1e-5 and
      np.abs(np.linalg.det(Rm) - 1).max() < 1e-5)
o2, _ = AG.attribute_mirror(gr, "Cd", source_side="negative")
check("Source Side = negative: the other way round (left 9 copied to the right)",
      np.allclose(A(o2, POINT, "Cd")[P[:, 0] > 0], 9.0))
# Asymmetric mesh: fine on the right, coarse on the left, interior points jittered
xs = np.r_[np.linspace(-1, -1 / 3, 3), -0.05, 0.0, np.linspace(0, 1, 9)[1:]]
zs = np.linspace(-1, 1, 7)
XX, ZZ = np.meshgrid(xs, zs)
Pa = np.c_[XX.ravel(), np.zeros(XX.size), ZZ.ravel()]
inner = (np.abs(Pa[:, 0]) < 0.99) & (np.abs(Pa[:, 0]) > 0.06) & \
    (np.abs(Pa[:, 2]) < 0.99)
Pa[inner] += np.c_[rng.uniform(-0.03, 0.03, inner.sum()), np.zeros(inner.sum()),
                   rng.uniform(-0.05, 0.05, inner.sum())]
nx = len(xs)
faces = [[j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i]
         for j in range(len(zs) - 1) for i in range(nx - 1)]
asym = Geometry.from_mesh(Pa.astype(np.float32), faces)
lin = 2 * Pa[:, 0] + 3 * Pa[:, 2] + 1
asym.set(POINT, "h", np.where(Pa[:, 0] >= 0, lin, -5)[:, None].astype(np.float32))
L = Pa[:, 0] < -1e-6
o, r = AG.attribute_mirror(asym, "h", lookup="surface")
es = np.abs(A(o, POINT, "h")[L, 0] - (-2 * Pa[L, 0] + 3 * Pa[L, 2] + 1)).max()
check("asymmetric mesh + surface: linear attributes exact (barycentric interpolation; also right for the column hugging the plane at x = −0.05)",
      es < 1e-5, es)
sh = asym.copy()
sh.set(POINT, "h", np.where(Pa[:, 0] > 0.02, lin, -5)[:, None].astype(np.float32))
o, r = AG.attribute_mirror(sh, "h", origin=(0.02, 0, 0), lookup="surface")
Ls = Pa[:, 0] < 0.02
eg = np.abs(A(o, POINT, "h")[Ls, 0] - (2 * (0.04 - Pa[Ls, 0]) + 3 * Pa[Ls, 2] + 1))
check("when the plane (x = 0.02) cuts through the middle of triangles, triangles straddling the plane are not used (the other corner holds the unmirrored old value −5)"
      ": the error is only the thin strip where no surface is found (< 0.5), not dragged towards −5", eg.max() < 0.5,
      eg.max())
o, r = AG.attribute_mirror(asym, "h", lookup="closest_point")
ec = np.abs(A(o, POINT, "h")[L, 0] - (-2 * Pa[L, 0] + 3 * Pa[L, 2] + 1)).max()
check("  negative control: nearest-point mode is not exact on an asymmetric mesh", ec > 0.02, ec)
o, r = AG.attribute_mirror(asym, "h", lookup="closest_point", max_distance=0.01)
check("Max Distance: points whose mirror position is too far from the source are unchanged, and counted",
      r["too_far"] > 0 and r["too_far"] + r["mirrored_points"] == L.sum())
gr.set_group(POINT, "lower", P[:, 2] < 0)
o, r = AG.attribute_mirror(gr, "Cd", group="lower")
Q = A(o, POINT, "Cd")
check("group only restricts points on the side being written", np.allclose(Q[(P[:, 0] < 0) & (P[:, 2] > 0)], 9)
      and np.abs(Q[(P[:, 0] < 0) & (P[:, 2] < 0)] -
                 f3(-P[(P[:, 0] < 0) & (P[:, 2] < 0), 0],
                    P[(P[:, 0] < 0) & (P[:, 2] < 0), 2])).max() < 1e-6)
tilt = gr.copy()
Rt = np.linalg.qr(rng.normal(size=(3, 3)))[0]
tilt.set(POINT, "P", (P @ Rt.T + [0.3, -0.2, 0.1]).astype(np.float32))
o, _ = AG.attribute_mirror(tilt, "Cd", origin=(0.3, -0.2, 0.1),
                           direction=tuple(Rt[:, 0]))
check("grid rotated as a whole with the plane rotated along: same result",
      np.abs(A(o, POINT, "Cd") - A(AG.attribute_mirror(gr, "Cd")[0], POINT, "Cd"))
      .max() < 1e-5)

# ═══════════════════════════════════════════════════════ Group from Attr Boundary
sec("Group from Attribute Boundary")
g4 = build.grid(4, 4, 5, 5)
cen = np.array([Pd(g4)[g4.prim_points(i)].mean(0) for i in range(g4.nprims)])
g4.set_string(PRIM, "name", np.array([f"q{int(x > 0)}{int(z > 0)}"
                                      for x, _, z in cen]))
o, r = AG.group_from_attribute_boundary(g4, "name")
e = o.get_edge_group("boundary")
Pe = Pd(g4)[e]
check("four quadrants: 8 edges on the cross", len(e) == 8 and
      all(abs(a[0]) < 1e-6 and abs(b[0]) < 1e-6 or abs(a[2]) < 1e-6 and
          abs(b[2]) < 1e-6 for a, b in Pe), r)
o, r = AG.group_from_attribute_boundary(g4, "name", include_unshared=True)
check("Include Unshared: plus 16 outer border edges", r["boundary_edges"] == 24)
o, _ = AG.group_from_attribute_boundary(g4, "name", group_type="points")
check("group_type = points: the 9 points on the cross",
      int(o.get_group(POINT, "boundary").sum()) == 9)
o, _ = AG.group_from_attribute_boundary(g4, "name", group_type="prims")
check("group_type = prims: the 12 faces next to the cross",
      int(o.get_group(PRIM, "boundary").sum()) == 12)
tb = build.tube(1, 1, 2, cols=8, rows=3)
Pt = Pd(tb)
vp = tb.vertex_point
ang = np.arctan2(Pt[:, 2], Pt[:, 0]) % (2 * np.pi)
uv = []
for i in range(tb.nprims):
    pp = tb.prim_points(i)
    a = ang[pp]
    if a.max() - a.min() > np.pi:
        a = np.where(a < np.pi, a + 2 * np.pi, a)
    uv += [[x / (2 * np.pi), 0] for x in a]
tb.set(VERTEX, "uv", np.asarray(uv, np.float32))
o, r = AG.group_from_attribute_boundary(tb, "uv", "vertex")
e = o.get_edge_group("boundary")
check("vertex uv: 2 vertical edges on the seam (3 rows of points -> 2 segments)", len(e) == 2 and
      np.allclose(ang[e.reshape(-1)], 0), (len(e), r))
gh = build.grid(4, 4, 5, 5)
gh.set(POINT, "h", (Pd(gh)[:, 0] > 0.1).astype(np.float32)[:, None])
o, r = AG.group_from_attribute_boundary(gh, "h", "point")
check("step in a point attribute: the 5 horizontal edges where x crosses 0.1", r["boundary_edges"] == 5)
gh.set(POINT, "h2", (Pd(gh)[:, 0] > 0.1).astype(np.float32)[:, None] * 1e-7)
o, r = AG.group_from_attribute_boundary(gh, "h2", "point", tolerance=1e-5)
check("differences within the tolerance don't count", r["boundary_edges"] == 0)
err("no such attribute: raises", lambda: AG.group_from_attribute_boundary(g4, "zz"),
    "has no attribute")

# ═══════════════════════════════════════════════════════ Partition
sec("Partition")
pg = build.grid(3, 3, 4, 4)
names = np.array(["a b", "1x", "a b", "c", "c", "c", "1x", "a_b", "a b"])
pg.set_string(PRIM, "name", names)
o, r = AG.partition(pg, "name")
grps = {k: v for k, v in o.groups[PRIM].items() if k.startswith("grp_")}
cover = np.sum([v for v in grps.values()], axis=0)
check("every prim lands in exactly one group", (cover == 1).all())
check("group names: spaces become _, 'a b' and 'a_b' collide and merge", set(grps) == {"grp_a_b", "grp_1x",
                                                    "grp_c"} and r["merged"] == 1,
      (sorted(grps), r))
check("  the merged group holds prims of both values", int(grps["grp_a_b"].sum()) == 4)
pp = pts(np.zeros((4, 3)))
pp.set(POINT, "v", np.array([[0.5], [-1.25], [0.5], [3]], np.float32))
o, r = AG.partition(pp, "v", "point", "$ATTR")
check("floats / minus signs / leading digits: _0_5, m1_25, _3 (with the minus sign as m it no longer starts with a digit)",
      set(r["groups"]) == {"_0_5", "m1_25", "_3"}, r["groups"])
pv = pts(np.zeros((3, 3)))
pv.set(POINT, "c", np.array([[1, 0, 0], [1, 0, 0], [0, 2, 1]], np.float32))
o, r = AG.partition(pv, "c", "point", "g$ATTR")
check("vectors: components joined with _", set(r["groups"]) == {"g1_0_0", "g0_2_1"})
err("no $ATTR in Rule: raises", lambda: AG.partition(pg, "name", "prim", "grp"),
    "$ATTR")

# ═══════════════════════════════════════════════════════ Tangent Field
sec("Tangent Field")
pl = build.grid(4, 4, 15, 15)
G = np.zeros((pl.npoints, 3))
G[37] = [1, 0.4, 0.3]                 # has a normal component: gets projected onto the tangent plane
pl.set(POINT, "gd", G.astype(np.float32))
o, r = TF.tangent_field(pl, 1, "gd")
V = A(o, POINT, "tangent")
want = np.array([1, 0, 0.3]) / np.linalg.norm([1, 0, 0.3])
check("plane + one guide: equals the guide everywhere (projected onto the tangent plane)", np.abs(V - want).max() < 1e-6 and
      r["energy"] < 1e-10, np.abs(V - want).max())
cyl = build.tube(1, 1, 4, cols=24, rows=12)
Pc = Pd(cyl)
Gc = np.zeros((cyl.npoints, 3))
Gc[5] = [0, 1, 0]
cyl.set(POINT, "gd", Gc.astype(np.float32))
o, r = TF.tangent_field(cyl, 1, "gd")
V = A(o, POINT, "tangent")
check("cylinder + one axial guide: transported everywhere along the axis (same direction)", V[:, 1].min() > 0.9999,
      V[:, 1].min())
circ_dir = np.c_[-Pc[:, 2], np.zeros(len(Pc)), Pc[:, 0]]
circ_dir /= np.linalg.norm(circ_dir, axis=1, keepdims=True)
Gc2 = np.zeros((cyl.npoints, 3))
Gc2[5] = circ_dir[5]
cyl.set(POINT, "gd2", Gc2.astype(np.float32))
o, r = TF.tangent_field(cyl, 1, "gd2")
V = A(o, POINT, "tangent")
dots_ = np.einsum("ij,ij->i", V, circ_dir)
check("cylinder + one circumferential guide: circumferential everywhere, consistent winding", dots_.min() > 0.999,
      dots_.min())
N = np.c_[Pc[:, 0], np.zeros(len(Pc)), Pc[:, 2]]
check("output is unit tangent vectors (orthogonal to the normal)", np.abs(np.linalg.norm(V, axis=1) - 1).max()
      < 1e-5 and np.abs(np.einsum("ij,ij->i", V, N)).max() < 1e-5)
G4 = np.zeros((pl.npoints, 3))
G4[100] = [math.cos(math.radians(30)), 0, math.sin(math.radians(30))]
pl.set(POINT, "g4", G4.astype(np.float32))
o, r = TF.tangent_field(pl, 4, "g4")
V = A(o, POINT, "tangent")
a4 = np.degrees(np.arctan2(V[:, 2], V[:, 0])) % 90
check("cross field (n = 4): every point's direction ≡ 30° (mod 90°)",
      np.abs(((a4 - 30) + 45) % 90 - 45).max() < 1e-4, a4[:3])
o, r = TF.tangent_field(cyl, 2, align="min_curvature")
V = A(o, POINT, "tangent")
check("curvature alignment min_curvature: along the axis on a cylinder", np.abs(V[:, 1]).min() > 0.999,
      np.abs(V[:, 1]).min())
o, r = TF.tangent_field(cyl, 2, align="max_curvature")
V = A(o, POINT, "tangent")
check("  max_curvature: circumferential", np.abs(V[:, 1]).max() < 1e-3, np.abs(V[:, 1]).max())
o, r = TF.tangent_field(build.sphere(1, 48, 40), 2, align="max_curvature")
check("on a sphere (isotropic) curvature alignment imposes no direction: singularity count = the minimal 2χ = 4",
      r["singularities"] == 4 and r["index_sum"] == 4, r)
sph = build.sphere(1, 24, 16)
o1, r1 = TF.tangent_field(sph, 1)
o4, r4 = TF.tangent_field(sph, 4)
check("sphere n = 1: singularity index sum = χ = 2 (two of them)", r1["index_sum"] == 2 and
      r1["singularities"] == 2, r1)
check("sphere n = 4: index sum = 4χ = 8 (eight of +1/4)", r4["index_sum"] == 8 and
      r4["singularities"] == 8, r4)
o, rt = TF.tangent_field(build.torus(1, 0.4, 16, 32), 1)
check("torus n = 1: index sum = 0", rt["index_sum"] == 0, rt)
Ns = A(ops.compute_normals(sph), POINT, "N")
check("unit tangent vectors on the sphere too (orthogonal to point normals)",
      np.abs(np.einsum("ij,ij->i", A(o1, POINT, "tangent"), Ns)).max() < 1e-5)
Gn = np.zeros((cyl.npoints, 3))
Gn[5] = [Pc[5, 0], 0, Pc[5, 2]]                   # exactly along the normal: projects to 0 on the tangent plane
cyl.set(POINT, "gn", Gn.astype(np.float32))
o, r = TF.tangent_field(cyl, 1, "gn")
check("a guide along the normal projects to zero on the tangent plane: not counted as a guide", r["guided_points"] == 0)
err("curvature alignment needs n ≥ 2", lambda: TF.tangent_field(cyl, 1, align="min_curvature"),
    "Symmetry ≥ 2")

# ═══════════════════════════════════════════════════════ Adaptive Prune
sec("Adaptive Prune")
Pp = np.c_[rng.uniform(0, 1, 3000), np.zeros(3000), rng.uniform(0, 1, 3000)]
cloud = pts(Pp)
pri = rng.uniform(0, 1, 3000)
cloud.set(POINT, "pri", pri[:, None].astype(np.float32))
o, r = PO.adaptive_prune(cloud, 0.05, "", "attribute", "pri", mode="group")
kept = ~o.get_group(POINT, "pruned")
K = Pp[kept]
D = np.linalg.norm(K[:, None] - K[None], axis=-1) + np.eye(len(K)) * 9
check("pairwise spacing of kept points ≥ radius", D.min() >= 0.05 - 1e-9, (D.min(), r))
bad = 0
for i in np.nonzero(~kept)[0]:
    d = np.linalg.norm(Pp[kept] - Pp[i], axis=1)
    if not ((d < 0.05) & (pri[kept] > pri[i])).any():
        bad += 1
check("every removed point neighbours a kept point of higher priority (maximal: nothing removed that could have stayed)", bad == 0,
      bad)
check("the highest-priority point is always kept", kept[np.argmax(pri)])
o, r = PO.adaptive_prune(cloud, 0.05)
check("delete mode: point count = number kept", o.npoints == r["kept"])
o2, _ = PO.adaptive_prune(cloud, 0.05, rand_seed=0)
o3, _ = PO.adaptive_prune(cloud, 0.05, rand_seed=1)
check("random: same seed reproducible, different seed gives a different result", np.array_equal(Pd(o), Pd(o2)) and
      not (o.npoints == o3.npoints and np.array_equal(Pd(o), Pd(o3))))
cloud.set(POINT, "rs", np.where(Pp[:, 0] < 0.5, 0.4, 1.6)[:, None]
          .astype(np.float32))
o, r = PO.adaptive_prune(cloud, 0.05, "rs")
Pk = Pd(o)
nl, nr = (Pk[:, 0] < 0.45).sum(), (Pk[:, 0] > 0.55).sum()
check("variable radius: the half with a 4x smaller radius keeps far more points (> 8x)", nl > 8 * nr, (nl, nr))
Kv = Pk
rv = np.where(Kv[:, 0] < 0.5, 0.02, 0.08)
D = np.linalg.norm(Kv[:, None] - Kv[None], axis=-1) + np.eye(len(Kv)) * 9
check("  with variable radius spacing ≥ the larger of the two points' radii", (D >= np.maximum(rv[:, None], rv[None])
                                  - 1e-7).all())
cloud.set_group(POINT, "half", Pp[:, 2] < 0.5)
o, r = PO.adaptive_prune(cloud, 0.05, group="half")
check("no point outside the group is removed", int((Pd(o)[:, 2] >= 0.5).sum()) == int((Pp[:, 2] >= 0.5)
                                                                .sum()))

# ═══════════════════════════════════════════════════════ Point Replicate
sec("Point Replicate")
src = pts(np.array([[0, 0, 0], [5, 0, 0], [0, 5, 0]]))
src.set(POINT, "Cd", np.eye(3, dtype=np.float32))
o, r = PO.point_replicate(src, 4000, radius=1.0, shape="sphere")
Q = Pd(o)
s_ = o.get(POINT, "source")[:, 0]
d = np.linalg.norm(Q - Pd(src)[s_], axis=1)
check("sphere: 3 × 4000 points, all within the radius", o.npoints == 12000 and d.max() <= 1 + 1e-6)
check("  uniform in the ball: 1/8 have radius < 1/2", abs((d < 0.5).mean() - 0.125) < 0.01,
      (d < 0.5).mean())
check("  inherits source point attributes, writes source", np.allclose(A(o, POINT, "Cd"), np.eye(3)[s_]))
o, _ = PO.point_replicate(src, 500, radius=0.7, shape="shell")
d = np.linalg.norm(Pd(o) - Pd(src)[o.get(POINT, "source")[:, 0]], axis=1)
check("shell: all on the sphere", np.abs(d - 0.7).max() < 1e-5)
sn = src.copy()
nn = np.array([[0, 0, 1], [1, 1, 0], [0.3, -1, 0.2]], float)
nn /= np.linalg.norm(nn, axis=1, keepdims=True)
sn.set(POINT, "N", nn.astype(np.float32))
o, _ = PO.point_replicate(sn, 4000, radius=1.0, shape="disk")
si = o.get(POINT, "source")[:, 0]
off = Pd(o) - Pd(sn)[si]
d = np.linalg.norm(off, axis=1)
check("disk: offsets perpendicular to each point's N", np.abs(np.einsum("ij,ij->i", off, nn[si])).max()
      < 1e-5)
check("  uniform in the disk: half have radius < 1/√2", abs((d < 2 ** -0.5).mean() - 0.5) < 0.015,
      (d < 2 ** -0.5).mean())
o, _ = PO.point_replicate(src, 20000, radius=0.3, shape="gaussian")
off = Pd(o) - Pd(src)[o.get(POINT, "source")[:, 0]]
check("gaussian: standard deviation per axis = radius", np.abs(off.std(0) - 0.3).max() < 0.01,
      off.std(0))
sp = src.copy()
sp.set(POINT, "pscale", np.array([[1], [2], [3]], np.float32))
sp.set(POINT, "n", np.array([[1], [0], [7]], np.float32))
o, r = PO.point_replicate(sp, 0, "n", 0.5, shape="shell")
d = np.linalg.norm(Pd(o) - Pd(sp)[o.get(POINT, "source")[:, 0]], axis=1)
check("count from an attribute (1, 0, 7), radius × pscale", o.npoints == 8 and
      np.allclose(d, 0.5 * np.array([1] + [3] * 7), atol=1e-5))
ids = src.copy()
ids.set(POINT, "id", np.array([[7], [8], [9]], np.int32))
oa, _ = PO.point_replicate(ids, 5)
two = ops.delete_points(ids, np.array([True, False, True]))
ob, _ = PO.point_replicate(two, 5)
check("with id, removing one source point leaves the other points' clusters unchanged",
      np.allclose(Pd(oa)[:5], Pd(ob)[:5]) and np.allclose(Pd(oa)[10:], Pd(ob)[5:]))
o, _ = PO.point_replicate(src, 5, keep_original=True)
check("keep_original: original points come first", o.npoints == 18 and
      np.allclose(Pd(o)[:3], Pd(src)))
o2, _ = PO.point_replicate(src, 5, rand_seed=3)
check("different seed gives a different result", not np.allclose(Pd(o2), Pd(PO.point_replicate(src, 5)[0])))

# ═══════════════════════════════════════════════════════ Point Velocity
sec("Point Velocity")
cur = pts(rng.uniform(-1, 1, (50, 3)))
a = np.array([0.1, -0.2, 0.05])
prev = pts(Pd(cur) - a)
nxt = pts(Pd(cur) + a)
o, r = PO.point_velocity(cur, prev, None, "auto", 24)
check("translation + only the previous frame: backward, v = displacement × fps", r["method"] == "backward" and
      np.abs(A(o, POINT, "v") - a * 24).max() < 1e-5)
o, r = PO.point_velocity(cur, prev, nxt, "auto", 24)
check("both present: auto picks central", r["method"] == "central" and
      np.abs(A(o, POINT, "v") - a * 24).max() < 1e-5)
w, dt = 2.0, 1 / 30
th = rng.uniform(0, 2 * np.pi, 20)


def ring(t):
    return pts(np.c_[np.cos(th + w * t), np.zeros(20), np.sin(th + w * t)])


o, _ = PO.point_velocity(ring(0), ring(-dt), ring(dt), "central", 30)
vt = w * np.c_[-np.sin(th), np.zeros(20), np.cos(th)] * math.sin(w * dt) / (w * dt)
check("central difference of a rotation = ω·r·sin(ωdt)/(ωdt) (tangential)", np.abs(A(o, POINT, "v") - vt)
      .max() < 1e-5)
p0, v0, acc = np.array([1.0, 2, 3]), np.array([0.5, 4, -1]), np.array([0, -9.8, 0])


def at(t):
    return pts((p0 + v0 * t + 0.5 * acc * t * t)[None])


o, _ = PO.point_velocity(at(0), at(-0.1), at(0.1), "central", 10,
                         compute_accel=True)
check("constant acceleration: central v = v₀, accel = a (exact)",
      np.abs(A(o, POINT, "v")[0] - v0).max() < 1e-4 and
      np.abs(A(o, POINT, "accel")[0] - acc).max() < 1e-3)
cur.set(POINT, "id", np.arange(50, dtype=np.int32)[:, None])
perm = rng.permutation(50)[:45]
pv = pts(Pd(cur)[perm] - a)
pv.set(POINT, "id", perm.astype(np.int32)[:, None])
o, r = PO.point_velocity(cur, pv, None, "backward", 24, "attribute", "id")
V = A(o, POINT, "v")
miss = np.setdiff1d(np.arange(50), perm)
check("pairing by id (previous frame shuffled, 5 points missing): matched ones exact, missing ones v = 0 and in no_velocity",
      np.abs(V[perm] - a * 24).max() < 1e-5 and np.abs(V[miss]).max() == 0 and
      set(np.nonzero(o.get_group(POINT, "no_velocity"))[0].tolist()) ==
      set(miss.tolist()) and r["unmatched"] == 5)
pd_ = pts(np.r_[Pd(cur)[:2] - a, Pd(cur)[:1] + 5])
pd_.set(POINT, "id", np.array([[0], [1], [0]], np.int32))
o, r = PO.point_velocity(cur, pd_, None, "backward", 24, "attribute", "id")
check("duplicate id in the previous frame: the first one is used", np.abs(A(o, POINT, "v")[0] - a * 24).max() < 1e-5)
err("no frames connected: raises", lambda: PO.point_velocity(cur), "Connect at least one")
err("central with a frame missing: raises", lambda: PO.point_velocity(cur, prev, None, "central"),
    "next")
err("acceleration needs two frames", lambda: PO.point_velocity(cur, prev, None, "backward",
                                          compute_accel=True), "both the previous and next frames")

# ═══════════════════════════════════════════════════════ Nodes
sec("Nodes")
NEW = {"PCG_AttribComposite": "PCG/attribute", "PCG_AttribMirror": "PCG/attribute",
       "PCG_GroupFromAttribBoundary": "PCG/group", "PCG_Partition": "PCG/group",
       "PCG_TangentField": "PCG/attribute", "PCG_AdaptivePrune": "PCG/scatter",
       "PCG_PointReplicate": "PCG/scatter", "PCG_PointVelocity": "PCG/attribute"}
check("all 8 nodes registered, in the right category",
      all(k in MAP and MAP[k].CATEGORY == v for k, v in NEW.items()))
bad = [k for k in NEW for nm_ in MAP[k].INPUT_TYPES()["required"]
       if nm_ in ("seed", "class")]
check("no widget named seed / class", not bad, bad)


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
for k, kw in {"PCG_AttribComposite": dict(geo=bg, fg=fg),
              "PCG_AttribMirror": dict(geo=gr), "PCG_GroupFromAttribBoundary":
              dict(geo=g4), "PCG_Partition": dict(geo=pg),
              "PCG_TangentField": dict(geo=sph), "PCG_AdaptivePrune": dict(geo=cloud),
              "PCG_PointReplicate": dict(geo=src),
              "PCG_PointVelocity": dict(geo=cur, prev=prev)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 8 nodes run with default parameters (with the required inputs connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
