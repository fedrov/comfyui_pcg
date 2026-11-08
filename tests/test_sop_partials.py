"""
pcg79: completing 8 partial nodes into full ones -- Group Combine, Switch-If, Point Relax, Primitive Split,
Transform by Attribute, PolySplit, Edge Cusp, Crease (+ fractional creases in Subdivide).

References do not rely on the implementation itself:
  Group Combine   matches set operations computed directly in numpy element by element; precedence as in Python sets; wildcards; edge groups
  Switch-If       lazy: with test connected only the selected branch is requested; unconnected, if_true first, if_false only if false;
                  every test function matches hand computation
  Point Relax     pushed apart in 3D until no overlap (every pair ≥ r_i + r_j); different pscale; points outside the group do not move;
                  points projected onto a surface stay on it, spacing becomes more even (coefficient of variation of nearest-neighbour distance drops)
  Primitive Split number of split points computed by hand from the boundary lines; strings; tolerance; group
  Transform/Attr  matches direct matrix multiplication; normals stay perpendicular to faces after non-uniform scale; vectors get no translation; orient only rotates;
                  inverse round trip; prim / detail / point; same matrix reading as Copy to Points
  PolySplit       position of new points on edges, uv interpolation, area conservation, points inserted into neighbouring faces (no T-junctions), closed path,
                  skipping pairs that are already edges, errors
  Edge Cusp       cutting a whole box = 24 points; one seam on a grid: points in the middle of the seam split, points at its ends do not; bowties do not split;
                  normals at the cuts are face normals
  Crease          s ≥ level count = infinitely sharp crease of an edge group (bit-identical); s = 0 = smooth; s = 0.5 with one level is
                  exactly the average of smooth and sharp (DeRose's linear blend); child edge weight s - 1; same for Loop
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
from comfyui_pcg.geo import groupcombine as GC          # noqa: E402
from comfyui_pcg.geo import cutsplit as CS              # noqa: E402
from comfyui_pcg.geo import pointrelax as PR            # noqa: E402
from comfyui_pcg.geo import xformattr as XA             # noqa: E402
from comfyui_pcg.geo import subdivide as SD             # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
from comfyui_pcg.geo.xform import point_matrices, quat_to_mat  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, VERTEX, DETAIL  # noqa: E402
from comfyui_pcg import expr as EX                      # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def PP(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def unwrap(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


def raises(fn, exc=(ValueError, KeyError, TypeError, RuntimeError), msg=""):
    try:
        fn()
    except exc as ex:
        return msg in str(ex)
    return False


# ════════════════════════════════════════════════════════ Group Combine
print("═" * 28, "Group Combine")
grid = build.grid(4, 4, 5, 5)
P = PP(grid)
rng = np.random.default_rng(3)
G = {k: rng.random(25) < 0.5 for k in ("a", "b", "c", "p1", "p2")}
gg = grid.copy()
for k, v in G.items():
    gg.set_group(POINT, k, v)
a, b, c = G["a"], G["b"], G["c"]
cases = {"a & b": a & b, "a | b": a | b, "a - b": a & ~b, "a ^ b": a ^ b,
         "!a": ~a, "~a": ~a, "(a | b) & !c": (a | b) & ~c,
         "a | b & c": a | (b & c), "a - b & c": (a & ~b) & c,
         "a ^ b | c": (a ^ b) | c, "a & b ^ c": (a & b) ^ c,
         "*": np.ones(25, bool), "* - a": ~a}
bad = [k for k, v in cases.items()
       if not np.array_equal(GC.combine_mask(gg, "point", k), v)]
check("set operations match numpy computed directly, element by element (13 expressions, incl. precedence)", not bad, bad)
check("  wildcard: p* = p1 | p2",
      np.array_equal(GC.combine_mask(gg, "point", "p* & a"), (G["p1"] | G["p2"]) & a))
out, rep = GC.group_combine(gg, "point", "a & b", "ab")
check("  written as a new group, report has the member count", np.array_equal(out.get_group(POINT, "ab"), a & b)
      and rep["members"] == int((a & b).sum()))
pr = grid.copy()
pa = np.arange(16) % 2 == 0
pb = np.arange(16) < 8
pr.set_group(PRIM, "x", pa)
pr.set_group(PRIM, "y", pb)
check("prim groups", np.array_equal(GC.combine_mask(pr, "prim", "x & !y"), pa & ~pb))
t = topology(grid)
E = t.edge_points
ea = E[:10]
eb = E[5:15]
eg = grid.copy()
eg.set_edge_group("ea", ea)
eg.set_edge_group("eb", eb)
o2, r2 = GC.group_combine(eg, "edge", "ea & eb", "eab")
got = {tuple(sorted(x)) for x in np.asarray(o2.edge_groups["eab"]).tolist()}
want = {tuple(sorted(x)) for x in E[5:10].tolist()}
check("edge groups: intersection = intersection of the two point-pair sets", got == want and r2["total"] == t.nedges, len(got))
vg = grid.copy()
va = np.arange(grid.nvertices) % 3 == 0
vg.set_group(VERTEX, "v1", va)
check("vertex groups", np.array_equal(GC.combine_mask(vg, "vertex", "!v1"), ~va))
check("errors: missing group, odd character, syntax error, empty expression, no output name",
      raises(lambda: GC.combine_mask(gg, "point", "a & zz"))
      and raises(lambda: GC.combine_mask(gg, "point", "a + b"), ValueError, "Unrecognized character")
      and raises(lambda: GC.combine_mask(gg, "point", "a & (b"))
      and raises(lambda: GC.combine_mask(gg, "point", "a b"))
      and raises(lambda: GC.combine_mask(gg, "point", "a - - b"), ValueError)
      and raises(lambda: GC.combine_mask(gg, "point", " "))
      and raises(lambda: GC.group_combine(gg, "point", "a", ""))
      and raises(lambda: GC.combine_mask(gg, "detail", "a")))

# ═══════════════════════════════════════════════════════════ Switch-If
print("═" * 28, "Switch-If")
SW = MAP["PCG_SwitchIf"]()
box = build.box()
box.set(POINT, "Cd", np.tile([0.2, 0.5, 0.9], (8, 1)).astype(np.float32))
box.set_group(PRIM, "top", np.array([True, False, False, False, False, False]))
f = EX.geo_funcs(box, 1)
check("test functions: hasattrib / hasgroup / ngroup / attribmax / min / mean",
      f["hasattrib"]("point", "Cd") == 1 and f["hasattrib"]("point", "N") == 0
      and f["hasattrib"](-1, "point", "Cd") == 1
      and f["hasgroup"]("prim", "top") == 1 and f["hasgroup"]("prim", "no") == 0
      and f["ngroup"]("prim", "top") == 1 and f["ngroup"]("prim", "no") == -1
      and abs(f["attribmax"]("point", "P", 1) - 0.5) < 1e-6
      and abs(f["attribmin"]("point", "P", 1) + 0.5) < 1e-6
      and abs(f["attribmean"]("point", "Cd", 2) - 0.9) < 1e-6)
eg2 = grid.copy()
eg2.set_edge_group("e", E[:3])
check("  ngroup also counts edge groups", EX.geo_funcs(eg2, 1)["ngroup"]("edge", "e") == 3)
r, vals = EX.eval_tests("# comment\nnpoints() == 8\n\nnprims() > 100", box, "all")
check("one test per line, # comments and blank lines skipped; all / any",
      r is False and vals == [True, False]
      and EX.eval_tests("npoints() == 8\nnprims() > 100", box, "any")[0] is True)
check("  no tests / aggregating a string / empty attribute -> error",
      raises(lambda: EX.eval_tests("# only comments", box))
      and raises(lambda: EX.eval_tests("attribmax('point', 'nope') > 0", box))
      and raises(lambda: EX.eval_tests("hasattrib('edge', 'x')", box), msg="class must be one of")
      and raises(lambda: EX.eval_tests("hasattrib('pt', 'x')", box), msg="class must be one of")
      and raises(lambda: EX.eval_tests("attribmax('prim', 'nm') > 0",
                                       (lambda g: (g.set_string(PRIM, "nm", ["x"] * 6), g)[1])(
                                           build.box())), msg="string attribute")
      and raises(lambda: EX.eval_tests("x", box, "some")))
T, F = build.box(), build.grid(1, 1, 2, 2)
kw = dict(tests="npoints() > 5", merge="all", invert=False)
check("lazy: test connected -> only the selected branch is requested",
      SW.check_lazy_status(**kw, test=box, if_true=None, if_false=None) == ["if_true"]
      and SW.check_lazy_status(**kw, test=F, if_true=None, if_false=None) == ["if_false"]
      and SW.check_lazy_status(**kw, test=box, if_true=T, if_false=None) == [])
check("  test not connected: if_true first; tested on it, if_false not needed when true",
      SW.check_lazy_status(**kw, if_true=None, if_false=None) == ["if_true"]
      and SW.check_lazy_status(**kw, if_true=T, if_false=None) == []
      and SW.check_lazy_status(**dict(kw, tests="npoints() > 100"), if_true=T,
                               if_false=None) == ["if_false"])
check("  neither test nor if_true connected: nothing requested (run raises later), no crash",
      SW.check_lazy_status(**kw, if_false=None) == [])
check("  unconnected branches are never requested (keys absent)",
      SW.check_lazy_status(**dict(kw, tests="npoints() > 100"), if_true=T) == [])
o = unwrap(SW.run(**kw, test=box, if_true=T, if_false=F))
check("run: true sends if_true, result = True", o[0].npoints == 8 and o[1] is True)
o = unwrap(SW.run(**dict(kw, invert=True), test=box, if_true=T, if_false=F))
check("  Invert negates", o[0].npoints == 4 and o[1] is False)
o = unwrap(SW.run(**dict(kw, tests="npoints() > 100"), if_true=T))
check("  false with no if_false connected -> empty geometry", o[0].npoints == 0 and o[1] is False)
check("  neither test nor if_true connected -> error", raises(lambda: SW.run(**kw, if_false=F)))

# ═══════════════════════════════════════════════════════════ Point Relax
print("═" * 28, "Point Relax")


def nn(Q):
    D = np.linalg.norm(Q[:, None] - Q[None], axis=2)
    np.fill_diagonal(D, np.inf)
    return D


rng = np.random.default_rng(1)
cl = Geometry.from_points(rng.normal(size=(200, 3)) * 0.3)
o, rep = PR.point_relax(cl, iterations=300, radius=0.1)
D = nn(PP(o))
check("pushed apart in 3D until no overlap: every pair distance ≥ 2r (relative error 1e-4)",
      D.min() >= 0.2 * (1 - 1e-4) and rep["overlap_before"] > 0.5, (D.min(), rep))
ps = np.where(np.arange(200) < 100, 0.05, 0.15)
cl2 = cl.copy()
cl2.set(POINT, "pscale", ps.astype(np.float32))
o, rep = PR.point_relax(cl2, iterations=400)
D = nn(PP(o))
need = ps[:, None] + ps[None, :]
check("  different pscale: every pair ≥ r_i + r_j",
      (D >= need * (1 - 1e-3)).all(), float((D / need).min()))
o3, _ = PR.point_relax(cl2, iterations=400, radius_scale=2.0)
check("  Radius Scale enlarges the radius", (nn(PP(o3)) >= 2 * need * (1 - 1e-3)).all())
ang_ = np.linspace(0, 2 * np.pi, 10, endpoint=False)
ring = np.stack([0.5 * np.cos(ang_), np.zeros(10), 0.5 * np.sin(ang_)], 1)  # spacing 0.31 > 2r
cl3 = Geometry.from_points(np.vstack([PP(cl)[:150], ring]))
fixed = np.arange(160) >= 150
cl3.set_group(POINT, "mv", ~fixed)
o, _ = PR.point_relax(cl3, iterations=300, radius=0.1, group="mv")
D = nn(PP(o))[~fixed]                  # pairs with at least one end in the group (pairs of two outside points don't matter)
check("  points outside the group do not move at all, but still block (points in the group do not overlap them either)",
      np.array_equal(PP(o)[fixed], PP(cl3)[fixed]) and D.min() >= 0.2 * (1 - 1e-3),
      D.min())
same = Geometry.from_points(np.zeros((5, 3)))
o, _ = PR.point_relax(same, iterations=100, radius=0.1)
D = nn(PP(o))
check("  exactly coincident points can also be pushed apart (deterministic direction), two runs give the same result",
      D.min() >= 0.2 * (1 - 1e-3)
      and np.array_equal(PP(o), PP(PR.point_relax(same, iterations=100, radius=0.1)[0])))
# surface
gr = build.grid(4, 4, 30, 30)
N0 = 300
P0 = np.c_[rng.uniform(-2, 2, N0), np.zeros(N0), rng.uniform(-2, 2, N0)]
o, rep = PR.point_relax(Geometry.from_points(P0), surface=gr, iterations=60)
Q = PP(o)
d0, d1 = nn(P0).min(1), nn(Q).min(1)
check("with a surface: points stay on the faces, within the faces' extent",
      np.abs(Q[:, 1]).max() < 1e-9 and np.abs(Q[:, [0, 2]]).max() <= 2 + 1e-9)
check("  spacing more even: coefficient of variation of nearest-neighbour distance 0.5 -> < 0.1, minimum spacing grows several times",
      d0.std() / d0.mean() > 0.4 and d1.std() / d1.mean() < 0.1
      and d1.min() > 5 * d0.min(), (round(d0.std() / d0.mean(), 3),
                                    round(d1.std() / d1.mean(), 3)))
check("  auto radius = half the spacing of a hexagonal packing filling the area √(A / (2√3 N))",
      abs(rep["radius_max"] - math.sqrt(16 / (2 * math.sqrt(3) * N0))) < 1e-9,
      rep["radius_max"])
sph = build.sphere(1.0, 48, 32)
Ps = rng.normal(size=(150, 3))
Ps /= np.linalg.norm(Ps, axis=1, keepdims=True)
o, _ = PR.point_relax(Geometry.from_points(Ps * 1.3), surface=sph, iterations=30)
from comfyui_pcg.geo.spatial import closest_surface, tri_soup   # noqa: E402
dist = closest_surface(PP(o), PP(sph), tri_soup(sph)[0])[1]
check("  pushing on a sphere: every point's distance to the sphere mesh ~ 0 (points starting outside are projected on first)",
      dist.max() < 1e-6, float(dist.max()))
gn = Geometry.from_points(rng.uniform(0, 1, (60, 3)))
d_nn = nn(PP(gn)).min(1).mean()
o, rep = PR.point_relax(gn, iterations=0)
check("  no surface, Radius = 0: auto radius = half the mean nearest-neighbour distance",
      abs(rep["radius_max"] - 0.5 * d_nn) < 1e-9 and np.array_equal(PP(o), PP(gn)),
      (rep["radius_max"], 0.5 * d_nn))
o, rep = PR.point_relax(gn, iterations=50, radius=1e-4)
check("  stops early when nothing overlaps (not a single round of pushing)", rep["iterations"] == 0
      and np.array_equal(PP(o), PP(gn)))
pair = Geometry.from_points(np.array([[0, 0, 0], [0.1, 0, 0.0]]))
o, _ = PR.point_relax(pair, iterations=1, radius=0.1, max_step=10)
Q = PP(o)
check("  one round: both can move -> each backs off half, exactly touching (distance = 2r, midpoint fixed)",
      abs(np.linalg.norm(Q[1] - Q[0]) - 0.2) < 1e-7 and np.abs(Q.mean(0) - [0.05, 0, 0]).max() < 1e-7)
pair.set_group(POINT, "one", np.array([True, False]))
o, _ = PR.point_relax(pair, iterations=1, radius=0.1, max_step=10, group="one")
Q = PP(o)
check("  one round: the other is a fixed point outside the group -> this one backs off the full amount",
      abs(np.linalg.norm(Q[1] - Q[0]) - 0.2) < 1e-7 and np.array_equal(Q[1], PP(pair)[1]))
trio = Geometry.from_points(np.array([[0, 0, 0], [0.05, 0, 0], [5, 0, 0.0]]))
trio.set_group(POINT, "far", np.array([False, False, True]))
o, rep = PR.point_relax(trio, iterations=10, radius=0.1, group="far")
check("  two overlapping points both outside the group do not count: no round of pushing, no overlapping pair in the report",
      rep["iterations"] == 0 and rep["overlapping_pairs"] == 0)
o, _ = PR.point_relax(Geometry.from_points(Ps * 1.3), surface=sph, iterations=0)
check("  with a surface, 0 rounds: points are still projected onto the surface first",
      closest_surface(PP(o), PP(sph), tri_soup(sph)[0])[1].max() < 1e-6)
o, rep = PR.point_relax(cl, iterations=1, radius=0.1, max_step=0.05)
step = np.linalg.norm(PP(o) - PP(cl), axis=1).max()
check("  Max Step: one step moves at most max_step × r", step <= 0.05 * 0.1 * (1 + 1e-5), step)

# ═══════════════════════════════════════════════════════ Primitive Split
print("═" * 28, "Primitive Split")
g3 = build.grid(3, 3, 4, 4)                       # 3×3 faces
cen = np.asarray(ops.prim_centers(g3))
col = (cen[:, 0] > 0.5).astype(np.float32)        # the rightmost column is 1
g3.set(PRIM, "cls", col.reshape(-1, 1))
o, rep = CS.primitive_split(g3, "cls")
check("split by attribute: the 4 points on the boundary line each split into 2 (16 -> 20)",
      o.npoints == 20 and rep["split_points"] == 4, o.npoints)
ok = True
vp, vpr = np.asarray(o.vertex_point), o.vertex_prim()
for p in range(o.npoints):
    ok &= len(set(col[vpr[vp == p]].tolist())) <= 1
check("  after splitting every point belongs to faces of one class only; positions unchanged", ok and np.allclose(
    np.unique(np.round(PP(o), 6), axis=0), np.unique(np.round(PP(g3), 6), axis=0)))
g3s = g3.copy()
g3s.set_string(PRIM, "name", np.where(col > 0, "R", "L"))
check("  string attributes split by equality (Tolerance has no effect on strings)",
      CS.primitive_split(g3s, "name")[0].npoints == 20
      and CS.primitive_split(g3s, "name", 5.0)[0].npoints == 20)
g3t = g3.copy()
g3t.set(PRIM, "cls", (col * 1e-4).reshape(-1, 1))
check("  tolerance: a difference of 1e-4 does not split with tolerance 1e-3, splits with 0",
      CS.primitive_split(g3t, "cls", 1e-3)[0].npoints == 16
      and CS.primitive_split(g3t, "cls", 0)[0].npoints == 20)
diag = g3.copy()
diag.set(PRIM, "cls", np.arange(9, dtype=np.float32).reshape(-1, 1))
check("  every face different = split everything (9 × 4 = 36 points)",
      CS.primitive_split(diag, "cls")[0].npoints == 36)
diag.set_group(PRIM, "left", cen[:, 0] < -0.5)
o, _ = CS.primitive_split(diag, "cls", 0, "left")
# by hand: the 3 faces of the left column are in the group, each its own class; the 6 faces outside the group are one class. Leftmost column of points 1+2+2+1 = 6;
# second column of points touches left faces and outside faces: 2+3+3+2 = 10; the two right columns only touch outside faces: 8. 24 in total
check("  group: only faces in the group split by attribute, the 6 faces outside count as one class and still share points (24 by hand)",
      o.npoints == 24, o.npoints)
check("  missing attribute -> error", raises(lambda: CS.primitive_split(g3, "nope")))

# ═════════════════════════════════════════════════ Transform by Attribute
print("═" * 28, "Transform by Attribute")


def rot(ax, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = ax
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


Rm = rot(np.array([1, 2, 3]) / math.sqrt(14), 40)
S = np.diag([2.0, 0.5, 1.5])
M3 = Rm @ S
Tt = np.array([1.0, -2.0, 0.5])
m4 = np.eye(4)
m4[:3, :3] = M3.T                 # pcg102: attributes stored in Houdini's row-vector convention (p' = p·m4)
m4[3, :3] = Tt
bx = build.box()
bx.set(DETAIL, "transform", m4.reshape(1, 16).astype(np.float32))
o, rep = XA.transform_by_attrib(bx, cls="detail")
check("detail 4×4: Houdini row vector P' = P·M + T (translation in row 4)",
      np.abs(PP(o) - (PP(bx) @ M3.T + Tt)).max() < 1e-5)
bx.set(DETAIL, "transform", M3.T.reshape(1, 9).astype(np.float32))
o, _ = XA.transform_by_attrib(bx, cls="detail")
check("  3×3 read the same way", np.abs(PP(o) - PP(bx) @ M3.T).max() < 1e-5)
one = Geometry.from_points(np.zeros((1, 3)))
one.set(POINT, "transform", m4.reshape(1, 16).astype(np.float32))
Mc, Tc, _ = point_matrices(one)
check("  same way Copy to Points reads transform (same matrix, same translation)",
      np.abs(Mc[0] - M3).max() < 1e-6 and np.abs(Tc[0] - Tt).max() < 1e-6)
# Houdini's own matrix: 90° about Z (the result of maketransform) sends (1,0,0) to (0,1,0)
hz = Geometry.from_points(np.array([[1.0, 0, 0]]))
hz.set(DETAIL, "transform", np.array([[0, 1, 0, -1, 0, 0, 0, 0, 1]], np.float32))
o, _ = XA.transform_by_attrib(hz, cls="detail")
check("pcg102: Houdini's 90° about Z matrix [[0,1,0],[-1,0,0],[0,0,1]] sends (1,0,0) to (0,1,0)",
      np.abs(PP(o)[0] - [0, 1, 0]).max() < 1e-6, PP(o)[0])
hz.set(POINT, "transform", np.array([[0, 1, 0, -1, 0, 0, 0, 0, 1]], np.float32))
Mz, _, _ = point_matrices(hz)
check("  Copy to Points reads it the same way (negative control: the old reading sent it to (0,-1,0))",
      np.abs(Mz[0] @ [1, 0, 0] - [0, 1, 0]).max() < 1e-6
      and np.abs(np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]]) @ [1, 0, 0] - [0, -1, 0]).max() < 1e-9)
fl = build.grid(2, 2, 3, 3)
fl.set(POINT, "N", np.tile([0, 1, 0], (9, 1)).astype(np.float32))
fl.set(POINT, "v", np.tile([1, 0, 0], (9, 1)).astype(np.float32))
fl.set(VERTEX, "N", np.tile([0, 1, 0], (fl.nvertices, 1)).astype(np.float32))
Mn = S @ Rm                       # rotate first, then non-uniform scale: normals are no longer eigenvectors of S
m4n = np.eye(4)
m4n[:3, :3] = Mn.T
m4n[3, :3] = Tt
fl.set(DETAIL, "transform", m4n.reshape(1, 16).astype(np.float32))
o, rep = XA.transform_by_attrib(fl, cls="detail")
Q = PP(o)
fn = np.cross(Q[1] - Q[0], Q[3] - Q[0])
fn /= np.linalg.norm(fn)
Nn = np.asarray(o.get(POINT, "N"), np.float64)
Nv = np.asarray(o.get(VERTEX, "N"), np.float64)
check("non-uniform scale + rotation: point / vertex normals stay perpendicular to the transformed faces (inverse transpose), unit length",
      np.abs(np.abs(Nn @ fn) - 1).max() < 1e-5 and np.abs(np.abs(Nv @ fn) - 1).max() < 1e-5)
Nbad = np.array([0, 1, 0]) @ Mn.T
Nbad /= np.linalg.norm(Nbad)
check("  negative control: normals multiplied directly by M are not perpendicular (the criterion discriminates)", abs(abs(Nbad @ fn) - 1) > 0.01)
check("  vector v only multiplied by the 3×3, no translation",
      np.abs(np.asarray(o.get(POINT, "v")) - np.array([1, 0, 0]) @ Mn.T).max() < 1e-5)
check("  the report lists what was transformed", set(rep["transformed"]) >= {"point.N", "vertex.N", "point.v"})
ob = fl.copy()
ob.set(DETAIL, "transform", m4.reshape(1, 16).astype(np.float32))
ob.set(POINT, "orient", np.tile([0, 0, 0, 1], (9, 1)).astype(np.float32))
o, _ = XA.transform_by_attrib(ob, cls="detail")
Rq = quat_to_mat(np.asarray(o.get(POINT, "orient"), np.float64))
check("orient only multiplied by the rotation part (polar decomposition removes scale)", np.abs(Rq - Rm).max() < 1e-5)
mir = ob.copy()
m_mir = Rm @ np.diag([1.0, 2.0, -3.0])
mir.set(DETAIL, "transform", m_mir.T.reshape(1, 9).astype(np.float32))
om, _ = XA.transform_by_attrib(mir, cls="detail")
Rq2 = quat_to_mat(np.asarray(om.get(POINT, "orient"), np.float64))
check("  matrix with a mirror: takes the nearest rotation (flips the weakest axis) = Rm·diag(-1, 1, -1)",
      np.abs(Rq2 - Rm @ np.diag([-1.0, 1.0, -1.0])).max() < 1e-4,
      float(np.abs(Rq2 - Rm @ np.diag([-1.0, 1.0, -1.0])).max()))
o2, _ = XA.transform_by_attrib(o, cls="detail", invert=True)
check("Invert: transform and invert back = unchanged (P / N / v / orient)",
      np.abs(PP(o2) - PP(ob)).max() < 1e-5
      and np.abs(np.asarray(o2.get(POINT, "N")) - [0, 1, 0]).max() < 1e-5
      and np.abs(np.asarray(o2.get(POINT, "v")) - [1, 0, 0]).max() < 1e-5
      and np.abs(quat_to_mat(np.asarray(o2.get(POINT, "orient"), np.float64))
                 - np.eye(3)).max() < 1e-5)
# point / prim
pm = fl.copy()
mats = np.stack([np.eye(3) * (1 + i) for i in range(9)]).reshape(9, 9)
pm.set(POINT, "transform", mats.astype(np.float32))
o, _ = XA.transform_by_attrib(pm, cls="point", normals="", vectors="")
check("point: each point uses its own matrix", np.abs(PP(o) - PP(fl) * (1 + np.arange(9))[:, None]).max() < 1e-5)
two = ops.merge(build.grid(1, 1, 2, 2, center=(-2, 0, 0)), build.grid(1, 1, 2, 2, center=(2, 0, 0)))
tm = np.stack([np.eye(3).reshape(9), (np.eye(3) * 3).reshape(9)])
two.set(PRIM, "transform", tm.astype(np.float32))
o, _ = XA.transform_by_attrib(two, cls="prim", normals="", vectors="")
check("prim: the points of each face use that face's matrix",
      np.abs(PP(o)[:4] - PP(two)[:4]).max() < 1e-6
      and np.abs(PP(o)[4:] - 3 * PP(two)[4:]).max() < 1e-5)
shared = build.grid(2, 1, 3, 2)
shared.set(PRIM, "transform", tm.astype(np.float32))
o, _ = XA.transform_by_attrib(shared, cls="prim", normals="", vectors="")
mid = np.nonzero(np.abs(PP(shared)[:, 0]) < 1e-9)[0]
check("  shared points use the matrix of the lowest-numbered face (the rule stated in the docs)",
      np.abs(PP(o)[mid] - PP(shared)[mid]).max() < 1e-6)
gp = fl.copy()
gp.set_group(POINT, "half", np.arange(9) < 4)
o, _ = XA.transform_by_attrib(gp, cls="detail", group="half")
check("points outside the group do not move",
      np.abs(PP(o)[4:] - PP(fl)[4:]).max() == 0 and np.abs(PP(o)[:4] - PP(fl)[:4]).max() > 0.1)
check("errors: no matrix attribute, wrong component count, wrong class",
      raises(lambda: XA.transform_by_attrib(build.box(), cls="detail"))
      and raises(lambda: XA.transform_by_attrib(
          (lambda g: (g.set(DETAIL, "transform", np.zeros((1, 4), np.float32)), g)[1])(build.box()),
          cls="detail"))
      and raises(lambda: XA.transform_by_attrib(fl, cls="vertex")))

# ═══════════════════════════════════════════════════════════ PolySplit
print("═" * 28, "PolySplit")
g = build.grid(2, 2, 3, 3)
uv = PP(g)[np.asarray(g.vertex_point)][:, [0, 2]]
g.set(VERTEX, "uv", uv.astype(np.float32))


def area(geo):
    X = PP(geo)
    s = 0.0
    for i in range(geo.nprims):
        Y = X[geo.prim_points(i)]
        s += 0.5 * np.linalg.norm(np.cross(Y, np.roll(Y, -1, 0)).sum(0))
    return s


o, rep = CS.poly_split(g, "0-1@0.25 3-4@0.25 6-7@0.25", edge_group="cut")
Q = PP(o)
check("cutting along two faces: 3 new points, 2 cuts, 4 faces -> 6 faces", rep["new_points"] == 3
      and rep["cuts"] == 2 and o.nprims == 6)
check("  new point on the edge at t = 0.25 (0 at the first point's end)",
      np.abs(Q[9:] - [[-0.75, 0, -1], [-0.75, 0, 0], [-0.75, 0, 1]]).max() < 1e-6)
check("  area conserved", abs(area(o) - area(g)) < 1e-9)
U = np.asarray(o.get(VERTEX, "uv"), np.float64)
Qv = Q[np.asarray(o.vertex_point)][:, [0, 2]]
check("  vertex attributes (uv) interpolated by t: each corner's uv = its position", np.abs(U - Qv).max() < 1e-6)
cut = {tuple(sorted(x)) for x in np.asarray(o.edge_groups["cut"]).tolist()}
check("  Edge Group: the two new edges from the cut", cut == {(9, 10), (10, 11)})
t2 = topology(o)
check("  the new edges really are edges, each with one face on either side (cut through)",
      all(t2.edge_count[i] == 2 for i in range(t2.nedges)
          if tuple(sorted(t2.edge_points[i])) in cut))
o, rep = CS.poly_split(g, "1-4@0.5 3")
sizes = sorted(o.prim_sizes().tolist())
check("no T-junctions: the new point on edge 1-4 is inserted into both faces on either side (one cut, one gets an extra point)",
      o.nprims == 5 and sizes == [3, 4, 4, 4, 5], sizes)
o, rep = CS.poly_split(g, "1-4@0.5 4")
check("  the two cut positions are already adjacent (a new point and its edge end point) = only insert the point, no cut",
      o.nprims == 4 and rep["already_edges"] == 1 and sorted(o.prim_sizes().tolist()) == [4, 4, 5, 5])
t3 = topology(o)
check("  every interior edge has exactly two faces (no dangling edges)",
      (t3.edge_count[~t3.boundary] == 2).all())
o, rep = CS.poly_split(g, "0 4 8")
check("point to point: 0->4->8 two diagonal cuts", o.nprims == 6 and rep["new_points"] == 0)
o, rep = CS.poly_split(g, "0 1")
check("  pairs that are already an edge are skipped", o.nprims == 4 and rep["already_edges"] == 1)
o, rep = CS.poly_split(g, "1-4@0.5 3-4@0.5 4-7@0.5 4-5@0.5", close_path=True)
check("Close Path: a diamond around the center point, the last segment connects back to the first -> 4 cuts, 8 faces",
      rep["cuts"] == 4 and o.nprims == 8 and rep["new_points"] == 4, (rep, o.nprims))
o, rep = CS.poly_split(g, "1-4@0.5 3-4@0.5 4-7@0.5 4-5@0.5", close_path=False)
check("  without Close: one cut fewer", rep["cuts"] == 3 and o.nprims == 7)
o, rep = CS.poly_split(g, "1-0@0.25 4-3@0.25")
check("position written reversed (1-0@0.25): t measured from the point written first",
      np.abs(PP(o)[9:] - [[-0.25, 0, -1], [-0.25, 0, 0]]).max() < 1e-6)
o, rep = CS.poly_split(g, "1-4@0.25 3 1-4@0.75")
t4 = topology(o)
check("  two new points on the same edge, inserted in the right order into two faces running in opposite directions (area conserved, no dangling edges)",
      rep["new_points"] == 2 and abs(area(o) - area(g)) < 1e-9
      and (t4.edge_count[~t4.boundary] == 2).all() and o.prim_sizes().max() == 6)
o, rep = CS.poly_split(g, "0 0 4")
check("  two identical positions in a row count as one (no degenerate face cut)", o.nprims == 5 and rep["cuts"] == 1)
pl = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32),
                        [[0, 2], [0, 1, 2, 3]])
pl.set_topology(np.array([3, 0, 1, 2, 0, 1, 2, 3], np.int32), np.array([0, 4, 8], np.int32),
                np.array([False, True]))
o, rep = CS.poly_split(pl, "0 2")
check("  open polylines are not cut (also when the polyline comes first, the quad after it is what gets cut)",
      rep["cuts"] == 1 and o.nprims == 3 and not o.prim_closed[0]
      and list(o.prim_points(0)) == [3, 0, 1, 2])
o, rep = CS.poly_split(g, "0-1@0 3-4@1")
check("t = 0 / 1 snaps to the end point (no new point)", rep["new_points"] == 0 and rep["cuts"] == 1)
o, rep = CS.poly_split(g, "0-1@0.5 3-4@0.5 1-0@0.5", close_path=False)
check("the same position on the same edge creates only one point (1-0@0.5 = 0-1@0.5)", rep["new_points"] == 2)
check("errors: not on the same face, no such edge, bad syntax, out of range, t out of range, only one position",
      raises(lambda: CS.poly_split(g, "0 8"))
      and raises(lambda: CS.poly_split(g, "0-8@0.5 4"))
      and raises(lambda: CS.poly_split(g, "0 x"))
      and raises(lambda: CS.poly_split(g, "0 99"))
      and raises(lambda: CS.poly_split(g, "0-1@1.5 4"))
      and raises(lambda: CS.poly_split(g, "0")))

# ═══════════════════════════════════════════════════════════ Edge Cusp
print("═" * 28, "Edge Cusp")
o, rep = CS.edge_cusp(build.box(), "", 0, True)
N = np.asarray(o.get(POINT, "N"), np.float64)
X = PP(o)
fnok = True
for i in range(o.nprims):
    pts = o.prim_points(i)
    Y = X[pts]
    n = np.cross(Y[1] - Y[0], Y[2] - Y[0])
    n /= np.linalg.norm(n)
    fnok &= np.abs(N[pts] @ n - 1).max() < 1e-5
check("cutting a whole box: 24 points, each point's normal is the normal of its face", o.npoints == 24 and fnok)
bl = SD.subdivide(build.box(), 1, "linear")
check("  Min Angle 45°: a subdivided box is only cut along the original 12 edges (9 points per face -> 54)",
      CS.edge_cusp(bl, "", 45)[0].npoints == 54
      and CS.edge_cusp(bl, "", 0)[0].npoints == 96)
check("  Min Angle 100°: none of the box's 90° edges are cut",
      CS.edge_cusp(build.box(), "", 100)[0].npoints == 8)
g5 = build.grid(4, 4, 5, 5)
P5 = PP(g5)
col2 = np.nonzero(np.abs(P5[:, 0]) < 1e-9)[0]              # the 5 points of the x = 0 column
zz = P5[col2, 2]
inner = col2[(zz > -1.5) & (zz < 1.5)]                      # the middle 3 points
slit = [(inner[i], inner[i + 1]) for i in range(len(inner) - 1)]
g5.set_edge_group("slit", np.sort(np.asarray(slit), 1))
o, rep = CS.edge_cusp(g5, "slit", 0, False)
check("one seam (not touching the boundary): only the point in the middle of the seam splits in two, the points at its ends do not",
      o.npoints == 26 and rep["cut_edges"] == 2, o.npoints)
full = [(col2[i], col2[i + 1]) for i in range(4)]
g5.set_edge_group("full", np.sort(np.asarray(full), 1))
o, _ = CS.edge_cusp(g5, "full", 0, False)
from comfyui_pcg.geo.topology import connectivity        # noqa: E402
check("  a seam across the whole grid: all 5 points split, the grid breaks into two pieces",
      o.npoints == 30
      and len(np.unique(np.asarray(connectivity(o).get(POINT, "class")))) == 2)
w4 = build.grid(2, 2, 3, 3)
F4 = [list(map(int, w4.prim_points(i))) for i in range(4)]
F4[3] = F4[3][::-1]                               # the bottom-right face has reversed winding
w4r = Geometry.from_mesh(PP(w4), F4)
w4r.set_edge_group("slit", np.array([[1, 4]]))
o, _ = CS.edge_cusp(w4r, "slit", 0)
pos_ok = all(np.allclose(PP(o)[o.prim_points(i)], PP(w4r)[w4r.prim_points(i)])
             for i in range(4))
check("  neighbouring faces with inconsistent winding: still paired by the same point (cut from the boundary to the center, only the boundary point splits)",
      o.npoints == 10 and pos_ok, o.npoints)
bow = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [-1, 0, 0], [-1, 0, -1]],
                                  np.float32), [[0, 1, 2], [0, 3, 4]])
bow.set_edge_group("far", np.array([[1, 2]]))
check("  a bowtie (two faces meeting at a single point) does not split -- that point does not touch a cut edge",
      CS.edge_cusp(bow, "far", 0)[0].npoints == 5)
try:
    CS.edge_cusp(g5, "nope", 0)
    _ok = False
except KeyError as e:
    _ok = "nope" in str(e)
check("  missing edge group = error (since pcg102; previously silently cut nothing)", _ok)

# ═══════════════════════════════════════════════════════════ Crease
print("═" * 28, "Crease")
cb = build.box()
tb = topology(cb)
top_edges = tb.edge_points[np.all(PP(cb)[tb.edge_points][:, :, 1] > 0, axis=1)]
cb.set_edge_group("top", top_edges)
o, rep = SD.crease(cb, "top", 2.5)
W = np.asarray(o.get(VERTEX, "creaseweight"))[:, 0]
check("Crease: 4 edges, 8 half-edges get 2.5, the rest 0",
      rep["edges"] == 4 and rep["half_edges"] == 8
      and (W == 2.5).sum() == 8 and (W == 0).sum() == 16)
o2, _ = SD.crease(o, "top", 2.0, "multiply")
o3, _ = SD.crease(o, "top", 1.0, "add")
o4, _ = SD.crease(o, "top", 3.0, "max")
o5, _ = SD.crease(o, "top", 1.0, "max")
check("  Mode:multiply / add / max",
      np.asarray(o2.get(VERTEX, "creaseweight")).max() == 5.0
      and np.asarray(o3.get(VERTEX, "creaseweight")).max() == 3.5
      and np.asarray(o4.get(VERTEX, "creaseweight")).max() == 3.0
      and np.asarray(o5.get(VERTEX, "creaseweight")).max() == 2.5)
hard = SD.subdivide(cb, 2, crease_group="top")
for s_, d_ in ((2.0, 2), (5.0, 2), (3.0, 3)):
    ow, _ = SD.crease(cb, "top", s_)
    a_ = SD.subdivide(ow, d_)
    b_ = SD.subdivide(cb, d_, crease_group="top")
    if not np.array_equal(PP(a_), PP(b_)):
        break
else:
    s_ = None
check("s ≥ level count: bit-identical to the infinitely sharp crease of an edge group (s=2/5 two levels, s=3 three levels)", s_ is None, s_)
ow0, _ = SD.crease(cb, "top", 0.0)
check("  s = 0: bit-identical to no crease", np.array_equal(PP(SD.subdivide(ow0, 2)), PP(SD.subdivide(cb, 2))))
allw, _ = SD.crease(build.box(), "", 0.5)
half = SD.subdivide(allw, 1)
sm = SD.subdivide(build.box(), 1)
hd = SD.subdivide(build.box(), 1, auto_crease_angle=0.0)
check("  s = 0.5 one level: the result is exactly the average of smooth and fully sharp (DeRose's linear blend, both points and edges)",
      np.abs(PP(half) - 0.5 * (PP(sm) + PP(hd))).max() < 1e-6,
      float(np.abs(PP(half) - 0.5 * (PP(sm) + PP(hd))).max()))
ys = []
for s_ in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
    ow, _ = SD.crease(cb, "top", s_)
    Q = PP(SD.subdivide(ow, 3))
    ys.append(float((Q[:, 0] + Q[:, 1]).max()))          # how far it reaches towards a top edge (x=y=0.5)
Qh = PP(SD.subdivide(cb, 3, crease_group="top"))
check("  higher weight, sharper edge: the reach towards the corner increases strictly monotonically with s, s = 3 catches up with the hard crease (three levels)",
      all(ys[i] < ys[i + 1] for i in range(6))
      and ys[-1] == float((Qh[:, 0] + Qh[:, 1]).max()), [round(y, 4) for y in ys])
ow, _ = SD.crease(cb, "top", 2.5)
one_lvl = SD.subdivide(ow, 1)
sh, sa, has = SD._crease_sharpness(one_lvl, topology(one_lvl), "", -1, "edge_corner",
                                   "creaseweight")
tt = topology(one_lvl)
Y = PP(one_lvl)[tt.edge_points]
on_top_rim = np.all(np.abs(Y[:, :, 1] - Y[:, :, 1].max()) < 1e-9, 1) & \
    np.all(np.max(np.abs(Y[:, :, [0, 2]]), 2) > 0.3, 1)
check("child edge weight = s - 1: the original 4 edges become 8 with 1.5, the rest all 0",
      has and (sa == 1.5).sum() == 8 and set(np.unique(sa).tolist()) == {0.0, 1.5},
      np.unique(sa, return_counts=True))
tri = ops.merge(build.box())
from comfyui_pcg.geo import divide as DV                  # noqa: E402
trib = DV.convex_polygons(build.box(), "", 3, False, 1e-4) \
    if hasattr(DV, "convex_polygons") else None
if trib is not None and (trib.prim_sizes() == 3).all():
    tt0 = topology(trib)
    te = tt0.edge_points[np.all(PP(trib)[tt0.edge_points][:, :, 1] > 0, axis=1)]
    trib.set_edge_group("top", te)
    lw, _ = SD.crease(trib, "top", 4.0)
    check("Loop: s ≥ level count = hard crease of the edge group; child edge weights also reduced by 1",
          np.array_equal(PP(SD.subdivide(lw, 2, "loop")),
                         PP(SD.subdivide(trib, 2, "loop", crease_group="top")))
          and np.asarray(SD.subdivide(lw, 1, "loop").get(VERTEX, "creaseweight")).max() == 3.0)
    lh, _ = SD.crease(trib, "", 0.5)
    check("  Loop s = 0.5 with one level is also the average of smooth and fully sharp",
          np.abs(PP(SD.subdivide(lh, 1, "loop"))
                 - 0.5 * (PP(SD.subdivide(trib, 1, "loop"))
                          + PP(SD.subdivide(trib, 1, "loop", auto_crease_angle=0.0)))).max() < 1e-6)
else:
    check("Loop: triangulation failed (test precondition)", False)
tb2 = topology(cb)
vpr = cb.vertex_prim()
top_face = int(np.argmax(np.asarray(ops.prim_centers(cb))[:, 1]))
top_key = {tuple(sorted(x)) for x in top_edges.tolist()}
hes = [h for h in np.nonzero(tb2.he_valid)[0]
       if tuple(sorted(tb2.edge_points[tb2.he_edge[h]].tolist())) in top_key]
res = []
for side in (True, False):
    Wv = np.zeros(cb.nvertices, np.float32)
    for h in hes:
        if (vpr[h] == top_face) == side:
            Wv[h] = 5.0
    one_side = cb.copy()
    one_side.set(VERTEX, "creaseweight", Wv.reshape(-1, 1))
    res.append(np.array_equal(PP(SD.subdivide(one_side, 2)), PP(hard)))
check("an edge with a weight on only one half-edge: takes the larger of the two sides (same from either side)", all(res), res)
ow5, _ = SD.crease(cb, "top", 5.0, attribute="cw")
check("  Subdivide also reads the weights when subdividing only one group (incl. select all) (custom attribute name)",
      np.array_equal(PP(SD.subdivide(ow5, 2, group="*", crease_attribute="cw")), PP(hard)))
check("empty Crease Attribute = not read (same as no weights)",
      np.array_equal(PP(SD.subdivide(ow, 2, crease_attribute="")), PP(SD.subdivide(cb, 2))))

# ═════════════════════════════════════════════════════════════ nodes
print("═" * 28, "Nodes")


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


named = build.grid(2, 2, 3, 3)
named.set_string(PRIM, "name", ["a", "a", "b", "b"])
named.set_group(POINT, "a", np.arange(9) < 5)
named.set_group(POINT, "b", np.arange(9) > 3)
named.set(POINT, "transform", np.tile(np.eye(3).reshape(9), (9, 1)).astype(np.float32))
bad = []
for k, kw in {"PCG_GroupCombine": dict(geo=named),
              "PCG_SwitchIf": dict(if_true=named),
              "PCG_PointRelax": dict(geo=named),
              "PCG_PrimitiveSplit": dict(geo=named),
              "PCG_TransformByAttrib": dict(geo=named),
              "PCG_PolySplit": dict(geo=build.grid(1, 1, 2, 2)),
              "PCG_EdgeCusp": dict(geo=named),
              "PCG_Crease": dict(geo=named)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if r[0] is None:
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 8 nodes run with default parameters (with the needed inputs connected)", not bad, bad)
sub = MAP["PCG_Subdivide"]
ow, _ = SD.crease(cb, "top", 5.0)
r = unwrap(sub().run(**defaults(sub, geo=ow, depth=2)))
check("the Subdivide node reads creaseweight by default", np.array_equal(PP(r[0]), PP(hard)))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
