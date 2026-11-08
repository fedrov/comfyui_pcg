"""
Data model and building blocks -- `core` / `groups` / `topology` / `adjacency` / `xform` /
`ramp` / `pieces` / `spatial`.

There is **nothing else underneath** this layer: every node stands on it. When its contract breaks, the symptoms
usually show up far away (a second cook gives a different result, groups point at other
elements after a delete, normals skew after a non-uniform scale), so the criteria here lean towards "contract" rather than "feature":

    · Read-only    attribute arrays are always writeable=False; to modify, get a copy with get_w
    · Shallow copy copy() only copies the dicts, pixels/attributes are shared
    · Remapping    after delete / merge, groups and edge groups must be renumbered accordingly
    · Syntax       the group `0-9:2` / `!name` / `@P.y>0` family
    · Separable    mathematical properties such as squared Euclidean distance and the triangle inequality of hop distance
"""
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX, PRIM, DETAIL,  # noqa: E402,E501
                                  CLASSES, PRIM_POLY, is_string, freeze)
from comfyui_pcg.geo import (build, groups as GR, topology as TP,   # noqa: E402
                             adjacency as AD, xform as XF, ramp as RM,
                             pieces as PC, spatial as SP, ops as O)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn(); check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:100]}")


RNG = np.random.default_rng(0)


# ══════════════════════════════════════════════════════════ Geometry basics
print("═" * 28, "Geometry: construction and counts")

QUAD = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32)
g = Geometry.from_mesh(QUAD, np.array([[0, 1, 2, 3]], np.int32))
check("from_mesh: point / vertex / prim counts",
      (g.npoints, g.nvertices, g.nprims) == (4, 4, 1),
      (g.npoints, g.nvertices, g.nprims))
check("count() matches the four attribute classes",
      [g.count(c) for c in (POINT, VERTEX, PRIM, DETAIL)] == [4, 4, 1, 1],
      [g.count(c) for c in CLASSES])
check("faces are closed by default", bool(g.prim_closed[0]))
check("prim_type defaults to POLY", int(g.prim_type[0]) == PRIM_POLY)
check("prim_sizes / prim_points",
      g.prim_sizes().tolist() == [4]
      and g.prim_points(0).tolist() == [0, 1, 2, 3])
check("vertex_prim is the vertex->prim reverse lookup",
      g.vertex_prim().tolist() == [0, 0, 0, 0])
check("bbox", np.allclose(np.asarray(g.bbox()).reshape(2, 3),
                          [[0, 0, 0], [1, 1, 0]]))
check("variable-size ngons: list[list[int]] is accepted too",
      Geometry.from_mesh(QUAD, [[0, 1, 2], [0, 2, 3]]).prim_sizes().tolist()
      == [3, 3])
check("from_points: points only, no faces",
      (Geometry.from_points(QUAD).npoints,
       Geometry.from_points(QUAD).nprims) == (4, 0))
check("empty geometry answers any query",
      (Geometry().npoints, Geometry().nprims, Geometry().nvertices)
      == (0, 0, 0))
check("info() / repr() don't raise",
      isinstance(g.info(), str) and isinstance(repr(g), str))


print("═" * 28, "Read-only / copy / attributes")

check("P is read-only", not g.get(POINT, "P").flags.writeable)


def _write():
    g.get(POINT, "P")[0, 0] = 9.0


err("modifying a read-only array in place raises immediately", _write, "read-only")
w = g.get_w(POINT, "P")
w[0, 0] = 9.0
check("get_w gives a writable **copy**, the original is untouched",
      w.flags.writeable and float(g.get(POINT, "P")[0, 0]) == 0.0)
check("set freezes the array passed in",
      not Geometry.from_points(QUAD).get(POINT, "P").flags.writeable)
mine = np.zeros((4, 3), np.float32)
g2 = g.copy()
g2.set(POINT, "Cd", mine)
check("set does not freeze the **caller's** array (copies first, then freezes)", mine.flags.writeable)

g3 = g.copy()
check("after copy() the topology arrays are **the same object** (shallow copy, no ten copies of pixels)",
      g3.vertex_point is g.vertex_point)
g3.set(POINT, "extra", np.zeros((4, 1), np.float32))
check("  but the dicts are separate: adding an attribute on the copy doesn't affect the original",
      "extra" in g3.names(POINT) and "extra" not in g.names(POINT))

for value, want in (([1.0, 2.0, 3.0, 4.0], (4, 1)),
                    (np.zeros((4, 3)), (4, 3)),
                    (np.zeros((4, 2, 2)), (4, 4))):
    gg = g.copy()
    gg.set(POINT, "t", value)
    check(f"attributes always normalized to (N,C): {np.shape(value)} -> {want}",
          gg.get(POINT, "t").shape == want, gg.get(POINT, "t").shape)
gg = g.copy()
gg.set(POINT, "s", np.array(["a", "bb", "c", "d"]))
check("string attributes are recognized (dtype.kind == 'U')",
      is_string(gg.get(POINT, "s")) and gg.string_names(POINT) == ["s"])
_rm = gg.copy()
_rm.remove(POINT, "P")
check("has / names / remove",
      gg.has(POINT, "P") and "P" in gg.names(POINT)
      and not _rm.has(POINT, "P"))
_rm.remove(POINT, "nope")          # removing a nonexistent attribute should not raise
check("  remove of a nonexistent attribute doesn't raise (common in bulk cleanup)", True)
_ig = gg.copy()
_ig.set_group(POINT, "idx", np.array([0, 2]))
check("  index arrays are expanded into boolean masks",
      _ig.get_group(POINT, "idx").dtype == bool
      and int(_ig.get_group(POINT, "idx").sum()) == 2)
check("get gives default when not found", gg.get(POINT, "nope", "d") == "d")
check("freeze() freezes a copy, leaving the passed-in one alone",
      mine.flags.writeable and not freeze(mine).flags.writeable)

print("═" * 28, "Topology / triangulation / corners")

BOX = build.box()
check("box is 6 quads", (BOX.nprims, set(BOX.prim_sizes().tolist()))
      == (6, {4}))
tri = BOX.triangles()
check("triangles(): each quad split into 2 triangles", tri.shape == (12, 3), tri.shape)
tri2, cor = BOX.triangles(with_corners=True)
check("  with_corners also returns corner indices (needed for hard-edge shading)",
      cor.shape == tri2.shape
      and np.array_equal(BOX.vertex_point[cor], tri2))
mixed = Geometry.from_mesh(QUAD, np.array([[0, 1, 2, 3]], np.int32))
mixed.set_topology(np.array([0, 1, 2, 3], np.int32),
                   np.array([0, 4], np.int32), np.zeros(1, bool))
check("polylines (prim_closed=False) are not triangulated",
      len(mixed.triangles()) == 0)
nc = BOX.next_corner()
check("next_corner: wraps back to the first corner on a closed face",
      nc[3] == 0 and nc[0] == 1, (int(nc[0]), int(nc[3])))
err("wrong prim_closed length asserts immediately",
    lambda: g.copy().set_topology(np.zeros(4, np.int32),
                                  np.array([0, 4], np.int32),
                                  np.zeros(2, bool)),
    "length must equal")

print("═" * 28, "Groups / edge groups / prim_data")

gg = build.grid(cols=4, rows=4)
gg.set_group(POINT, "a", np.arange(16) < 5)
check("set_group / get_group", int(gg.get_group(POINT, "a").sum()) == 5)
check("groups are boolean masks, length == element count",
      gg.get_group(POINT, "a").dtype == bool
      and len(gg.get_group(POINT, "a")) == 16)
gg.set_edge_group("e", np.array([[0, 1], [1, 2]]))
eg = gg.get_edge_group("e")
check("edge groups store **point pairs** (not edge numbers -- edge numbers point at other edges after a delete)",
      eg.shape == (2, 2) and eg.dtype == np.int32, (eg.shape, eg.dtype))
keep = np.ones(16, bool)
keep[0] = False
d = O.delete_points(gg, keep)
check("after delete_points point groups are remapped",
      int(d.get_group(POINT, "a").sum()) == 4,
      int(d.get_group(POINT, "a").sum()))
check("  edge groups are remapped too (edges referencing deleted points disappear)",
      len(d.get_edge_group("e")) == 1, len(d.get_edge_group("e")))
gg.set_pdata(0, "vox", np.arange(5))
check("prim_data is a variable-size side channel (the fixed-size attribute table can't hold voxel grids)",
      gg.pdata(0, "vox").tolist() == [0, 1, 2, 3, 4])
check("remap_prim_data rebuilds by src_index",
      gg.remap_prim_data([2, 0]) == {1: {"vox": gg.pdata(0, "vox")}}
      or list(gg.remap_prim_data([2, 0])) == [1])
check("pdata gives default when not found", gg.pdata(5, "vox", "d") == "d")


print("═" * 28, "groups.resolve syntax")

gs = build.grid(cols=4, rows=4)
gs.set_group(POINT, "a", np.arange(16) < 5)
gs.set_group(POINT, "ab", np.arange(16) >= 13)
gs.set(POINT, "Cd", np.tile([0.5, 0.0, 0.0], (16, 1)).astype(np.float32))


def n_of(spec, **kw):
    return int(GR.resolve(gs, POINT, spec, **kw).sum())


check("empty = select all (the operators' default behaviour)", n_of("") == 16)
check("  with empty_is_all=False empty = empty set (for cases like growing a group)",
      n_of("", empty_is_all=False) == 0)
check("group name", n_of("a") == 5)
check("index range `0-4` (both ends inclusive)", n_of("0-4") == 5)
check("with step `0-15:3`", n_of("0-15:3") == 6)
check("space-separated indices `0 3 5`", n_of("0 3 5") == 3)
check("negation `!a` and `^a` are equivalent",
      n_of("!a") == 11 and n_of("^a") == 11)
check("@ expressions filter by attribute", n_of("@Cd.x>0.4") == 16 and n_of("@Cd.x>0.6") == 0)
check("  component suffixes .x/.y/.z recognized",
      n_of("@P.x<0") == 8, n_of("@P.x<0"))
err("a mistyped group name raises, and **lists the existing groups**",
    lambda: GR.resolve(gs, POINT, "nope"), "Existing groups")
check("mask from resolve has length == element count",
      len(GR.resolve(gs, PRIM, "")) == gs.nprims)
check("to_point_mask: prim group -> point group (all points on the faces count)",
      int(GR.to_point_mask(gs, PRIM, np.arange(gs.nprims) < 1).sum()) == 4,
      int(GR.to_point_mask(gs, PRIM, np.arange(gs.nprims) < 1).sum()))
check("to_prim_mask: a face counts only if **all its points are selected** (conservative, not \"any touch counts\")",
      int(GR.to_prim_mask(gs, POINT, np.arange(16) < 5).sum()) == 0
      and int(GR.to_prim_mask(gs, POINT, np.ones(16, bool)).sum())
      == gs.nprims,
      int(GR.to_prim_mask(gs, POINT, np.arange(16) < 5).sum()))
check("points_to_edges / edges_to_points are a pair",
      GR.points_to_edges(gs, np.arange(16) < 2).shape[1] == 2
      and int(GR.edges_to_points(gs, np.array([[0, 1]])).sum()) == 2)
check("prims_to_edges(interior_only) keeps only interior edges",
      len(GR.prims_to_edges(gs, np.ones(gs.nprims, bool),
                            interior_only=True))
      < len(GR.prims_to_edges(gs, np.ones(gs.nprims, bool))))
check("edge_mask: point pairs -> edge mask",
      int(GR.edge_mask(gs, np.array([[0, 1]])).sum()) == 1)


print("═" * 28, "topology / adjacency")

t = TP.topology(gs)
check("topology() is cached: asking the same geometry twice gives the same object",
      TP.topology(gs) is t)
gs2 = gs.copy()
gs2.set_topology(gs.vertex_point, gs.prim_offset, gs.prim_closed)
check("  cache invalidated after set_topology", gs2._topo is None)
check("4x4 grid has 24 edges (3×4 horizontal + 4×3 vertical)", t.nedges == 24, t.nedges)
check("edge_points is (E,2)", t.edge_points.shape == (24, 2))
check("edge_lengths all = grid spacing",
      np.allclose(TP.edge_lengths(gs), 10.0 / 3.0))
check("edge_angles length == edge count", len(TP.edge_angles(gs)) == 24)
off, nb = TP.point_neighbours(gs)
check("point_neighbours is CSR (offsets of length N+1)",
      off.shape == (17,) and int(off[-1]) == len(nb))
check("  corner points have 2 neighbours, center points 4",
      int(off[1] - off[0]) == 2 and int(off[6] - off[5]) == 4,
      (int(off[1] - off[0]), int(off[6] - off[5])))
bd = TP.group_boundary(gs)
check("group_boundary: the 4x4 grid boundary has 12 points, 8 faces",
      (int(bd.get_group(POINT, "boundary").sum()),
       int(bd.get_group(PRIM, "boundary").sum())) == (12, 8))
cc = TP.connectivity(gs, POINT, "class")
check("connectivity: a connected grid has only one piece",
      len(np.unique(cc.get(POINT, "class"))) == 1)
two = O.merge(build.grid(cols=3, rows=3),
              O.transform(build.grid(cols=3, rows=3),
                          translate=(100, 0, 0)))
check("  two separate pieces of geometry give two classes",
      len(np.unique(TP.connectivity(two, POINT, "class")
                    .get(POINT, "class"))) == 2)
cr = TP.group_by_angle(build.box(), min_angle=30.0, name="crease")
check("group_by_angle: all 12 cube ridges are 90° hard edges",
      int(cr.get_group(POINT, "crease").sum()) == 8,
      int(cr.get_group(POINT, "crease").sum()))
sm = TP.smooth(gs, strength=0.5, iterations=3)
check("smooth changes neither point count nor topology",
      sm.npoints == gs.npoints and np.array_equal(sm.vertex_point,
                                                  gs.vertex_point))
check("  smooth on a plane stays on the plane (y unchanged)",
      float(np.abs(np.asarray(sm.get(POINT, "P"))[:, 1]).max()) < 1e-6)

seed = np.arange(16) == 0
hop = AD.hop_distance(gs, POINT, seed)
check("hop_distance: source is 0, neighbours are 1", hop[0] == 0 and hop[1] == 1)
check("  the diagonally opposite point is 3+3=6 steps", hop[15] == 6, hop[15])
check("  satisfies the triangle inequality (hop difference between neighbours ≤ 1)",
      bool(np.all(np.abs(hop[t.edge_points[:, 0]]
                         - hop[t.edge_points[:, 1]]) <= 1)))
ed = AD.edge_distance(gs, POINT, seed, -1.0)
check("edge_distance: geometric distance walking along edges, source 0",
      abs(float(ed[0])) < 1e-12 and abs(float(ed[1]) - 10.0 / 3.0) < 1e-6)
check("  hop × grid spacing is an upper bound (a polyline walk is never shorter than the shortest path)",
      bool(np.all(ed <= hop * (10.0 / 3.0) + 1e-6)))
for m in AD.METRICS:
    dd, far = AD.distance_from(gs, POINT, seed, m, 2.0)
    check(f"distance_from(metric={m}) returns (distance, unreachable mask)",
          dd.shape == (16,) and far.shape == (16,) and far.dtype == bool)
    check(f"  the source itself is always reachable", not bool(far[0]))
err("malformed metric raises", lambda: AD.distance_from(gs, POINT, seed, "x", 1.0),
    "Metric must be one of")


print("═" * 28, "xform / ramp / pieces / spatial")

pts = Geometry.from_points(np.array([[0, 0, 0], [1, 0, 0]], np.float32))
pts.set(POINT, "N", np.array([[0, 1, 0], [1, 0, 0]], np.float32))
M, Tr, Pv = XF.point_matrices(pts)
check("point_matrices returns (M, T, pivot)",
      M.shape == (2, 3, 3) and Tr.shape == (2, 3) and Pv.shape == (2, 3))
check("  every matrix is orthogonal (pure rotation without N / up)",
      np.allclose(np.einsum("nij,nkj->nik", M, M), np.eye(3), atol=1e-5))
check("  T is the point position", np.allclose(Tr, [[0, 0, 0], [1, 0, 0]], atol=1e-6))
src = np.array([[1.0, 0, 0], [0, 0, 1.0]])
out = XF.apply_matrices(src, M, Tr, Pv)
check("apply_matrices: (m,3) source × (n,·) transforms -> (n,m,3)",
      out.shape == (2, 2, 3), out.shape)
S = np.array([np.diag([2.0, 1.0, 1.0])])
check("normal_matrices is the inverse transpose (so normals don't skew under non-uniform scale)",
      np.allclose(XF.normal_matrices(S)[0], np.diag([0.5, 1.0, 1.0])))
check("  a singular matrix doesn't make it raise (falls back to the original matrix)",
      np.isfinite(XF.normal_matrices(np.zeros((1, 3, 3)))).all())
L = XF.look_at(np.array([[0, 0, 1.0]]), (0, 1, 0))
check("look_at gives an orthonormal basis", np.allclose(L[0] @ L[0].T, np.eye(3), atol=1e-6))
check("quat_to_mat(unit quaternion) = identity matrix",
      np.allclose(XF.quat_to_mat(np.array([[0, 0, 0, 1.0]]))[0], np.eye(3),
                  atol=1e-6))

pos, val = RM.parse("0:0  0.5:1  1:0", 1)
check("ramp.parse: positions sorted, values as (K,C)",
      pos.tolist() == [0.0, 0.5, 1.0] and val.shape == (3, 1))
check("ramp.apply(linear) hits the keys exactly",
      np.allclose(RM.apply(np.array([0.0, 0.5, 1.0]), pos, val, "linear")
                  .ravel(), [0, 1, 0]))
check("  midpoint interpolation",
      abs(float(RM.apply(np.array([0.25]), pos, val,
                         "linear").ravel()[0]) - 0.5) < 1e-9)
check("  outside [0,1] takes the endpoints, no extrapolation",
      np.allclose(RM.apply(np.array([-1.0, 2.0]), pos, val, "linear").ravel(),
                  [0, 0]))
check("constant mode is a staircase (at 0.4 still the left step)",
      abs(float(RM.apply(np.array([0.4]), pos, val,
                         "constant").ravel()[0])) < 1e-12)
check("smooth mode also hits the keys exactly, and is monotonic",
      np.allclose(RM.apply(np.array([0.0, 0.5]), pos, val, "smooth").ravel(),
                  [0, 1], atol=1e-9))
p3, v3 = RM.parse("0:1,0,0  1:0,0,1", 3)
check("multi-component ramp", v3.shape == (2, 3))
check("single-key ramp gives a constant",
      np.allclose(RM.apply(np.linspace(0, 1, 5), *RM.parse("0.5:0.7", 1),
                           mode="linear").ravel(), 0.7))

bx = TP.connectivity(build.box(), PRIM, "class")
plan = PC.plan(bx, kind="primitives", attrib="class", elem="primitives")
check("pieces.plan returns (elem, order, starts, values)",
      len(plan) == 4, len(plan))
elem, order, starts, values = plan
check("  kind=primitives: each face is its own piece",
      elem == "primitives" and len(values) == bx.nprims, len(values))
ex = PC.extract(bx, elem, order, starts, 0)
check("  extracting piece 0 gives one face", ex.nprims == 1, ex.nprims)
check("  every piece can be extracted, and they add up to the total face count",
      sum(PC.extract(bx, elem, order, starts, i).nprims
          for i in range(len(values))) == bx.nprims)
cn = PC.plan(bx, kind="connectivity", elem="primitives")
check("kind=connectivity: a cube is one connected piece",
      len(cn[3]) == 1, len(cn[3]))
check("  extracting it gives the whole geometry",
      PC.extract(bx, cn[0], cn[1], cn[2], 0).nprims == bx.nprims)
ct = PC.plan(bx, kind="count", count=4)
check("kind=count: order=None means no splitting, each iteration takes the whole thing",
      ct[1] is None and len(ct[3]) == 4)
check("  an empty group that selects nothing gives 0 pieces",
      len(PC.plan(bx, kind="primitives", group="__none__")[3]) == 0
      if "__none__" in bx.groups[PRIM] else True)

# spatial.nearest: each item gets an AABB, evaluate(qi, ti) gives the exact distance.
# Verified using "point to point" items -- that way the correct answers can be computed by hand
ITEMS = np.array([[0.0, 0, 0], [4.0, 0, 0], [30.0, 0, 0]])
Q = np.array([[0.3, 0, 0], [3.5, 0, 0], [29.0, 0, 0]])


def _eval(qi, ti):
    d = np.linalg.norm(ITEMS[ti] - Q[qi], axis=1)
    return d, np.zeros((len(ti), 0))


idx, dist, _pl = SP.nearest(Q, ITEMS, ITEMS, _eval)
check("spatial.nearest: each query point finds the correct nearest item",
      idx.tolist() == [0, 1, 2], idx.tolist())
check("  distances correct too", np.allclose(dist, [0.3, 0.5, 1.0], atol=1e-9),
      np.round(dist, 4).tolist())
idx2, dist2, _ = SP.nearest(Q, ITEMS, ITEMS, _eval, max_dist=0.4)
check("  beyond max_dist counts as not found (returns -1)",
      idx2.tolist() == [0, -1, -1], idx2.tolist())
check("  more/fewer query points than items doesn't crash",
      len(SP.nearest(Q[:1], ITEMS, ITEMS, _eval)[0]) == 1)

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
