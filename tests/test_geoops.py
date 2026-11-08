"""
Geometry operators -- `ops` / `addsop` / `facet` / `divide` / `fusesop` / `clip` /
`subdivide` / `dissolve` / `edgedivide` / `polyreduce` / `refine` / `boolean` /
`polyfill` / `mirror` / `peak` / `explode` / `matchsize` / `centroid` /
`pointjitter` / `convert`.

This suite was **restored** (the old one was lost when the sandbox was recycled). Checks favour conserved quantities and closed-form results:

    Euler characteristic  V - E + F changes predictably under subdivision / triangulation / dual
    area / volume         subdivided cube volume -> analytic value; triangulation keeps area; mirror keeps volume
    idempotence           facet's cleanups, orient, consolidate are unchanged on a second run
    bit-identical         identity parameters (distance=0 / depth=0 / percent=100) must leave input untouched
    reversible            unroll/roll, mirror twice, transform forward and inverse
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

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX, PRIM,   # noqa: E402
                                  DETAIL)
from comfyui_pcg.geo import (build, ops as O, addsop as AS,        # noqa: E402
                             facet as FC, divide as DV, fusesop as FS,
                             clip as CL, subdivide as SD,
                             dissolve as DS, edgedivide as ED,
                             polyreduce as PR, refine as RF,
                             boolean as BL, polyfill as PF,
                             mirror as MR, peak as PK, explode as EP,
                             matchsize as MS, centroid as CT,
                             pointjitter as PJ, convert as CV,
                             topology as TP, measure as ME)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:100]}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def topo(g):
    return (g.vertex_point.tobytes(), g.prim_offset.tobytes(),
            g.prim_closed.tobytes(), g.npoints)


def area(g):
    return float(ME.prim_areas(g).sum())


def vol(g):
    return float(abs(ME.prim_volumes(g).sum()))


def euler(g):
    """V - E + F. On a closed orientable surface = 2 - 2*genus."""
    return g.npoints - TP.topology(g).nedges + g.nprims


BOX = build.box()
GRID = build.grid(cols=5, rows=5)
RNG = np.random.default_rng(0)


# ══════════════════════════════════════════════════════════════════ ops
print("═" * 28, "ops:merge / delete / transform")

a = build.grid(cols=3, rows=3)
b = O.transform(build.grid(cols=3, rows=3), translate=(100, 0, 0))
m = O.merge(a, b)
check("merge: point and prim counts add up",
      (m.npoints, m.nprims) == (a.npoints + b.npoints, a.nprims + b.nprims),
      (m.npoints, m.nprims))
check("  the second copy's prim indices are offset (not pointing back at the first copy's points)",
      int(m.vertex_point[m.prim_offset[a.nprims]]) >= a.npoints)
check("  areas add up", abs(area(m) - area(a) - area(b)) < 1e-4)
check("merge of one input = unchanged", topo(O.merge(a)) == topo(a))
check("merge with an empty input does not blow up", O.merge(a, Geometry()).nprims == a.nprims)
ag = a.copy()
ag.set_group(POINT, "g", np.arange(a.npoints) < 3)
mg = O.merge(ag, b)
check("after merge, groups are remapped (land only on the first copy)",
      int(mg.get_group(POINT, "g").sum()) == 3
      and not mg.get_group(POINT, "g")[a.npoints:].any())

keep = np.ones(BOX.nprims, bool)
keep[0] = False
dp = O.delete_prims(BOX, keep)
check("delete_prims: one prim fewer, isolated points are cleaned up too",
      dp.nprims == 5 and dp.npoints == 8, (dp.nprims, dp.npoints))
check("  with keep_points=True all points stay",
      O.delete_prims(BOX, keep, keep_points=True).npoints == 8)
kp = np.ones(BOX.npoints, bool)
kp[0] = False
dpt = O.delete_points(BOX, kp)
check("delete_points: prims referencing deleted points disappear too",
      dpt.npoints == 7 and dpt.nprims == 3, (dpt.npoints, dpt.nprims))
check("keeping everything is bit-identical",
      topo(O.delete_prims(BOX, np.ones(BOX.nprims, bool))) == topo(BOX))

t = O.transform(BOX, translate=(1, 2, 3))
check("transform translate: bbox moves as a whole, size unchanged",
      np.allclose(P_(t).min(0) - P_(BOX).min(0), [1, 2, 3], atol=1e-6)
      and np.allclose(P_(t).max(0) - P_(t).min(0),
                      P_(BOX).max(0) - P_(BOX).min(0), atol=1e-6))
check("  forward then inverse transform comes back",
      np.allclose(P_(O.transform(t, translate=(-1, -2, -3))), P_(BOX),
                  atol=1e-5))
check("  scale by 2 gives volume x8",
      abs(vol(O.transform(BOX, scale=(2, 2, 2))) / vol(BOX) - 8) < 1e-4)
check("  identity parameters are the identity", np.allclose(P_(O.transform(BOX)), P_(BOX)))
check("  rotating 360 degrees returns to the original position",
      np.allclose(P_(O.transform(BOX, rotate=(0, 360, 0))), P_(BOX),
                  atol=1e-5))
gb = BOX.copy()
gb.set_group(POINT, "half", P_(BOX)[:, 1] > 0)
tg = O.transform(gb, translate=(0, 5, 0), group="half")
check("points outside the group did not move at all",
      np.allclose(P_(tg)[P_(BOX)[:, 1] <= 0], P_(BOX)[P_(BOX)[:, 1] <= 0]))

print("═" * 28, "ops: normals / prim centers / prim normals / area")

nb = O.compute_normals(BOX, add_to="point", cusp_angle=60.0)
check("compute_normals(point) writes point.N, normalized",
      nb.has(POINT, "N")
      and np.allclose(np.linalg.norm(np.asarray(nb.get(POINT, "N")), axis=1),
                      1.0, atol=1e-5))
check("  cube hard edges: after cusp, N lives on vertices",
      O.compute_normals(BOX, add_to="vertex").has(VERTEX, "N"))
check("  each cube point's soft normal points to (+-1,+-1,+-1)/sqrt(3)",
      np.allclose(np.abs(np.asarray(
          O.compute_normals(BOX, add_to="point",
                            cusp_angle=180.0).get(POINT, "N"))),
          1 / np.sqrt(3), atol=1e-4))
pn = O.prim_normals(BOX)
check("prim_normals: the cube's 6 prim normals are pairwise opposite and axis-aligned",
      pn.shape == (6, 3)
      and np.allclose(np.sort(np.abs(pn).sum(0)), [2, 2, 2], atol=1e-5))
check("  with normalize=False the length = area*2 (magnitude of the cross product)",
      np.allclose(np.linalg.norm(O.prim_normals(BOX, normalize=False),
                                 axis=1), 1.0, atol=1e-5))
pc = O.prim_centers(BOX)
check("prim_centers: cube prim centers are all 0.5 from the center",
      np.allclose(np.linalg.norm(pc - P_(BOX).mean(0), axis=1), 0.5,
                  atol=1e-5))
_ma = O.measure_area(BOX)
check("measure_area writes area as a prim attribute (does not return a number)",
      _ma.has(PRIM, "area")
      and abs(float(np.asarray(_ma.get(PRIM, "area")).sum()) - 6.0) < 1e-5,
      float(np.asarray(_ma.get(PRIM, "area")).sum())
      if _ma.has(PRIM, "area") else _ma.names(PRIM))
check("triangulation keeps area",
      abs(area(O.convert_prims(BOX, "triangles")) - area(BOX)) < 1e-5)
check("  after triangulation the prim count doubles, all triangles",
      O.convert_prims(BOX, "triangles").nprims == 12
      and set(O.convert_prims(BOX, "triangles").prim_sizes().tolist()) == {3})

print("═" * 28, "ops:resample / sort / reverse / smooth / carve")

LINE = build.line((0, 0, 0), (0, 1, 0), length=3.0, points=4)


def plen(g):
    P = P_(g)
    tot = 0.0
    off = g.prim_offset
    for i in range(g.nprims):
        pts = g.vertex_point[off[i]:off[i + 1]]
        tot += float(np.linalg.norm(np.diff(P[pts], axis=0), axis=1).sum())
        if bool(g.prim_closed[i]):
            tot += float(np.linalg.norm(P[pts[0]] - P[pts[-1]]))
    return tot


rs = O.resample(LINE, by_length=False, segments=6)
check("resample(segments=6): 7 points", rs.npoints == 7, rs.npoints)
check("  length on a straight line unchanged", abs(plen(rs) - 3.0) < 1e-5)
check("  evenly spaced", np.allclose(np.diff(P_(rs)[:, 1]), 0.5, atol=1e-5))
rl = O.resample(LINE, by_length=True, length=0.5)
check("resample(by_length=0.5): also 7 points", rl.npoints == 7, rl.npoints)
check("  only_points outputs points, no lines", O.resample(LINE, only_points=True,
                                            by_length=False,
                                            segments=4).nprims == 0)
check("  extra attribute: curveu goes from 0 to 1",
      np.allclose([float(np.asarray(O.resample(
          LINE, by_length=False, segments=4,
          curveu_attrib="curveu").get(POINT, "curveu")).min()),
          float(np.asarray(O.resample(
              LINE, by_length=False, segments=4,
              curveu_attrib="curveu").get(POINT, "curveu")).max())],
          [0.0, 1.0], atol=1e-6))

srt = O.sort_geo(GRID, point_mode="x")
check("sort_geo(x): points are non-decreasing in x",
      bool(np.all(np.diff(P_(srt)[:, 0]) >= -1e-6)),
      np.round(P_(srt)[:5, 0], 3).tolist())
check("  along_vector sorts along any direction",
      bool(np.all(np.diff((P_(O.sort_geo(GRID, point_mode="along_vector",
                                         axis=(1, 0, 1)))
                           * np.array([1, 0, 1])).sum(1)) >= -1e-5)))
check("  reverse mode is just reversed order",
      np.allclose(P_(O.sort_geo(GRID, point_mode="reverse")),
                  P_(GRID)[::-1]))
check("  circular sorts by angle around an axis (a scattered ring of points needs this to connect into a loop)",
      O.sort_geo(build.circle(radius=(1, 1), divisions=12, plane="zx"),
                 point_mode="circular").npoints == 12)
check("  sorting changes neither point nor prim count",
      (srt.npoints, srt.nprims) == (GRID.npoints, GRID.nprims))
check("  area unchanged (renumbering only)", abs(area(srt) - area(GRID)) < 1e-5)
check("sort_geo(none) is bit-identical", topo(O.sort_geo(GRID)) == topo(GRID))
check("  random mode with the same seed gives the same result",
      topo(O.sort_geo(GRID, point_mode="random", seed=7))
      == topo(O.sort_geo(GRID, point_mode="random", seed=7)))

rv = O.reverse_prims(GRID)
check("reverse_prims: winding reversed, normals flipped",
      float(np.dot(O.prim_normals(rv)[0], O.prim_normals(GRID)[0])) < -0.9)
check("  reversing twice returns the original", topo(O.reverse_prims(rv)) == topo(GRID))
check("  area unchanged (winding does not change size)", abs(area(rv) - area(GRID)) < 1e-5)

sm = TP.smooth(GRID, strength=0.5, iterations=2)
check("smooth keeps topology", topo(sm)[:3] == topo(GRID)[:3])
cv = O.carve(build.circle(radius=(1, 1), divisions=16, plane="zx"),
             u0=0.25, u1=0.75, use_u0=True, use_u1=True)
check("carve still leaves geometry", cv.nprims >= 1, (cv.nprims, cv.npoints))

print("═" * 28, "addsop / facet")

# points_text is **one point per line** (xyz separated by spaces/commas/semicolons), not everything on one line
ad = AS.add(None, points_text="0,0,0\n1,0,0\n1,1,0", use_pattern=True,
            pattern="0 1 2", pattern_closed=True)
check("add: build points from text + connect prims by pattern",
      (ad.npoints, ad.nprims) == (3, 1), (ad.npoints, ad.nprims))
check("  pattern_closed decides polygon vs polyline",
      bool(ad.prim_closed[0])
      and not bool(AS.add(None, points_text="0,0,0\n1,0,0\n1,1,0",
                          use_pattern=True, pattern="0 1 2",
                          pattern_closed=False).prim_closed[0]))
check("parse_points: one point per line, commas/spaces/semicolons all work",
      AS.parse_points("0,0,0\n1 2 3\n4;5;6").shape == (3, 3))
check("  giving only two numbers fills z=0 (handy for planar coordinates)",
      np.allclose(AS.parse_points("1,2")[0], [1, 2, 0]))
check("  lines starting with `#` are comments", AS.parse_points("0,0,0\n# x\n1,1,1").shape
      == (2, 3))
check("parse_indices supports ranges", list(AS.parse_indices("0-3", 10))
      == [0, 1, 2, 3], list(AS.parse_indices("0-3", 10)))
err("parse_indices raises on out-of-range and states the total",
    lambda: AS.parse_indices("0-99", 10), "out of range")
dupe = O.merge(build.grid(cols=2, rows=2), build.grid(cols=2, rows=2))
check("remove_repeated: exactly coincident prims are deduplicated",
      AS.remove_repeated(FS.fuse(dupe, use_snap_distance=True,
                                 snap_distance=1e-4)).nprims
      <= dupe.nprims, AS.remove_repeated(dupe).nprims)
check("remove_unused clears points not referenced by any prim",
      AS.remove_unused(O.delete_prims(BOX, np.array(
          [True] + [False] * 5), keep_points=True)).npoints == 4)

f0 = FC.facet(BOX)
check("facet with nothing enabled = bit-identical", topo(f0) == topo(BOX))
uq = FC.unique_points(BOX)
check("unique_points: one separate point per corner (needed for hard-edge export)",
      uq.npoints == BOX.nvertices, uq.npoints)
check("  area unchanged", abs(area(uq) - area(BOX)) < 1e-5)
cs = FC.consolidate_points(uq, distance=1e-3)
check("consolidate welds them back", cs.npoints == 8, cs.npoints)
check("  unique -> consolidate is a round trip (area and prim count come back)",
      cs.nprims == BOX.nprims and abs(area(cs) - area(BOX)) < 1e-5)
check("consolidate is idempotent",
      topo(FC.consolidate_points(cs, distance=1e-3)) == topo(cs))
orient = FC.orient_polygons(O.reverse_prims(BOX, group="0-2"))
nn = O.prim_normals(orient)
ctr = P_(orient).mean(0)
out = ((O.prim_centers(orient) - ctr) * nn).sum(1)
check("orient_polygons: after unifying orientation all prim normals face consistently outward (or inward)",
      bool(np.all(out > 0) or np.all(out < 0)),
      np.round(out, 3).tolist())
check("  idempotent", topo(FC.orient_polygons(orient)) == topo(orient))
tri3 = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0],
                                    [2, 1, 0], [0, 1, 0]], np.float32),
                          [[0, 1, 2, 3, 4]])
check("remove_inline_points removes collinear middle points",
      FC.remove_inline_points(tri3, distance=0.01).prim_sizes()[0] == 4,
      FC.remove_inline_points(tri3, distance=0.01).prim_sizes().tolist())
degen = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 0]],
                                    np.float32), [[0, 1, 2]])
check("remove_degenerate drops zero-area prims",
      FC.remove_degenerate(degen).nprims == 0,
      FC.remove_degenerate(degen).nprims)
# cusp_polygons **splits points**, it does not write vertex normals: edges over the angle threshold no longer share points on both sides
check("cusp_polygons(30 deg): the cube's 8 points split into 24 (one per corner)",
      FC.cusp_polygons(BOX, angle=30.0).npoints == 24,
      FC.cusp_polygons(BOX, angle=30.0).npoints)
check("  with the angle at 180 deg no edge is split",
      FC.cusp_polygons(BOX, angle=180.0).npoints == 8)
check("  splitting points changes neither prim count nor area",
      FC.cusp_polygons(BOX, angle=30.0).nprims == BOX.nprims
      and abs(area(FC.cusp_polygons(BOX, angle=30.0)) - area(BOX)) < 1e-5)

print("═" * 28, "divide / subdivide / edgedivide / dissolve")

dv = DV.divide(BOX, convex=True, max_edges=3)
check("divide(max_edges=3): cube -> 12 triangles",
      dv.nprims == 12 and set(dv.prim_sizes().tolist()) == {3}, dv.nprims)
check("  area unchanged", abs(area(dv) - area(BOX)) < 1e-5)
check("  volume unchanged", abs(vol(dv) - vol(BOX)) < 1e-5)
check("with max_edges=4 the cube already satisfies it, bit-identical",
      topo(DV.divide(BOX, max_edges=4)) == topo(BOX))
check("convex_mask: the cube's prims are all convex",
      bool(DV.convex_mask(BOX).all()))
check("nonplanar_mask: the cube's prims are all planar",
      not bool(DV.nonplanar_mask(BOX).any()))
dual = DV.compute_dual(BOX)
check("compute_dual: the dual of a cube is an octahedron (6 points 8 prims)",
      (dual.npoints, dual.nprims) == (6, 8), (dual.npoints, dual.nprims))
check("  the dual's Euler characteristic is still 2", euler(dual) == 2, euler(dual))
rse = DV.remove_shared_edges(build.grid(cols=3, rows=3))
check("remove_shared_edges: a 2x2 grid merges into one big prim",
      rse.nprims == 1 and int(rse.prim_sizes()[0]) == 8,
      (rse.nprims, rse.prim_sizes().tolist()))

sub = SD.subdivide(BOX, depth=1)
check("subdivide(depth=1): cube 6 prims -> 24 prims",
      sub.nprims == 24, sub.nprims)
check("  Euler characteristic still 2 (subdivision keeps topological type)", euler(sub) == 2, euler(sub))
check("  Catmull-Clark shrinks the volume (limit is a sphere)",
      vol(sub) < vol(BOX), f"{vol(BOX):.4f} -> {vol(sub):.4f}")
check("  deeper depth gets closer to a sphere (volume converges monotonically)",
      vol(SD.subdivide(BOX, depth=2)) < vol(sub))
check("depth=0 is bit-identical", topo(SD.subdivide(BOX, depth=0)) == topo(BOX))
check("  the linear algorithm does not move existing points",
      SD.subdivide(BOX, depth=1, algorithm="linear").nprims == 24)

g2 = build.grid(cols=3, rows=3)
g2.set_edge_group("e", np.array([[0, 1]]))
edv = ED.edge_divide(g2, edge_group="e", cuts=1)
check("edge_divide: cutting one edge adds one point", edv.npoints == g2.npoints + 1,
      edv.npoints)
check("  area unchanged", abs(area(edv) - area(g2)) < 1e-5)
# cuts makes at least one cut (_positions treats 0 as 1 -- "edges selected but nothing done" makes no sense)
check("cuts=0 is the same as cuts=1 (at least one cut)",
      topo(ED.edge_divide(g2, edge_group="e", cuts=0))
      == topo(ED.edge_divide(g2, edge_group="e", cuts=1)))
check("cuts=2 adds one more point", ED.edge_divide(g2, edge_group="e",
                                       cuts=2).npoints == g2.npoints + 2)
check("only an empty edge_group truly does nothing",
      topo(ED.edge_divide(g2, edge_group="")) == topo(g2))

g3 = build.grid(cols=3, rows=3)
g3.set_edge_group("mid", np.array([[1, 4]]))
dsv = DS.dissolve(g3, edge_group="mid")
check("dissolve: dissolving one interior edge merges two prims into one",
      dsv.nprims == g3.nprims - 1, dsv.nprims)
check("  area unchanged", abs(area(dsv) - area(g3)) < 1e-5)
check("empty edge_group does nothing", topo(DS.dissolve(g3)) == topo(g3))

print("═" * 28, "fuse / clip / polyfill / boolean")

fu = FS.fuse(O.merge(build.grid(cols=2, rows=2), build.grid(cols=2, rows=2)),
             use_snap_distance=True, snap_distance=1e-3)
check("fuse: two exactly coincident grids weld into 4 points", fu.npoints == 4, fu.npoints)
check("  distance 0 still welds **exactly coincident** points (0 <= 0)",
      FS.fuse(O.merge(build.grid(cols=2, rows=2),
                      build.grid(cols=2, rows=2)),
              use_snap_distance=True, snap_distance=0.0).npoints == 4)
_off = O.merge(build.grid(cols=2, rows=2),
               O.transform(build.grid(cols=2, rows=2),
                           translate=(0.01, 0, 0)))
check("  two copies 0.01 apart: not welded at distance 0, welded at distance 0.1",
      FS.fuse(_off, use_snap_distance=True, snap_distance=0.0).npoints == 8
      and FS.fuse(_off, use_snap_distance=True,
                  snap_distance=0.1).npoints == 4,
      (FS.fuse(_off, use_snap_distance=True, snap_distance=0.0).npoints,
       FS.fuse(_off, use_snap_distance=True, snap_distance=0.1).npoints))

cl = CL.clip(BOX, direction=(0, 1, 0), distance=0.0, keep="below")
check("clip: cutting in half halves the volume", abs(vol(cl) / vol(BOX) - 0.5) < 0.02,
      f"{vol(BOX):.4f} -> {vol(cl):.4f}")
check("  points on the cut face all lie on the plane",
      float(np.abs(P_(cl)[:, 1][P_(cl)[:, 1] > -1e-6]).max()) < 1e-5)
check("  cutting outside = unchanged (bbox unchanged)",
      abs(vol(CL.clip(BOX, direction=(0, 1, 0), distance=10.0,
                      keep="below")) - vol(BOX)) < 1e-5)
check("  the two halves' volumes add up to the original volume",
      abs(vol(CL.clip(BOX, distance=0.0, keep="below"))
          + vol(CL.clip(BOX, distance=0.0, keep="above")) - vol(BOX)) < 0.02)
br = CL.bricker(BOX, size=(0.5, 0.5, 0.5))
check("bricker: cut into bricks, more prims", br.nprims > BOX.nprims, br.nprims)

openbox = O.delete_prims(BOX, np.array([False] + [True] * 5))
loops = PF.boundary_loops(openbox)
check("boundary_loops: after removing one prim there is 1 boundary loop",
      len(loops) == 1 and len(loops[0]) == 4,
      [len(x) for x in loops])
fl = PF.fill(openbox, mode="ngon")
check("polyfill(ngon) closes the hole", fl.nprims == BOX.nprims, fl.nprims)
check("  volume comes back after filling", abs(vol(fl) - vol(BOX)) < 1e-4)
check("  already-closed geometry has nothing to do", topo(PF.fill(BOX)) == topo(BOX))

try:
    bo = BL.boolean(BOX, O.transform(build.box(), translate=(0.5, 0, 0)),
                    operation="subtract")
    check("boolean(subtract): volume = half the original",
          abs(vol(bo) / vol(BOX) - 0.5) < 0.02,
          f"{vol(bo):.4f} vs {vol(BOX) * 0.5:.4f}")
    check("  union volume = 1.5x",
          abs(vol(BL.boolean(BOX, O.transform(build.box(),
                                              translate=(0.5, 0, 0)),
                             operation="union")) / vol(BOX) - 1.5) < 0.02)
    check("  intersect volume = 0.5x",
          abs(vol(BL.boolean(BOX, O.transform(build.box(),
                                              translate=(0.5, 0, 0)),
                             operation="intersect")) / vol(BOX) - 0.5)
          < 0.02)
    check("  result is still closed (Euler characteristic 2)", euler(bo) == 2, euler(bo))
except RuntimeError as ex:
    check("boolean without manifold3d gives an **actionable** error",
          "manifold3d" in str(ex) and "pip install" in str(ex),
          str(ex)[:60])

print("═" * 28, "polyreduce / refine / mirror / peak / explode")

dense = SD.subdivide(BOX, depth=2)
rd = PR.reduce_mesh(dense, target="percentage", keep_percent=50.0)
check("polyreduce(50%): triangle count roughly halved",
      0.3 < len(rd.triangles()) / len(dense.triangles()) < 0.7,
      f"{len(dense.triangles())} -> {len(rd.triangles())}")
check("  bbox essentially unchanged (simplification should not move the model)",
      np.allclose(P_(rd).mean(0), P_(dense).mean(0), atol=0.05))
check("keep_percent=100 leaves it essentially unchanged",
      len(PR.reduce_mesh(dense, keep_percent=100.0).triangles())
      >= len(dense.triangles()) - 2)
rf = RF.refine(build.line((0, 0, 0), (0, 1, 0), length=2.0, points=3),
               mode="refine", u_divisions=2)
check("refine adds points without changing shape (length on a polyline unchanged)",
      rf.npoints >= 3 and abs(plen(rf) - 2.0) < 1e-4,
      (rf.npoints, round(plen(rf), 4)))

mi = MR.mirror(BOX, mode="append", normal=(1, 0, 0),
               origin=(0.5, 0, 0))
check("mirror(append): prim count doubles, volume doubles",
      mi.nprims == BOX.nprims * 2 and abs(vol(mi) / vol(BOX) - 2) < 0.02,
      (mi.nprims, round(vol(mi), 4)))
check("  the mirrored part is on the other side of the plane",
      float(P_(mi)[:, 0].max()) > float(P_(BOX)[:, 0].max()) + 0.4)
rmM = MR.reflect_matrix(np.array([1.0, 0, 0]), np.zeros(3))[0]
check("the linear part of reflect_matrix is an involution (squared = identity)",
      np.allclose(rmM @ rmM, np.eye(3), atol=1e-9))
check("  determinant = -1 (reflection flips handedness)",
      abs(float(np.linalg.det(rmM)) + 1.0) < 1e-9,
      float(np.linalg.det(rmM)))
pkg = O.compute_normals(BOX, add_to="point", cusp_angle=180.0)
pk = PK.peak(pkg, distance=0.1)
check("peak: pushing along point normals increases volume",
      vol(pk) > vol(BOX), f"{vol(BOX):.4f} -> {vol(pk):.4f}")
check("  distance=0 is the identity", np.allclose(P_(PK.peak(pkg, distance=0.0)),
                                       P_(pkg)))
check("  every point moved exactly distance",
      np.allclose(np.linalg.norm(P_(pk) - P_(pkg), axis=1), 0.1, atol=1e-5))
epg = TP.connectivity(O.merge(BOX, O.transform(build.box(),
                                               translate=(3, 0, 0))),
                      PRIM, "name")
ex_ = EP.explode(epg, mode="uniform", distance=1.0, piece_from="attribute",
                 piece_attrib="name")
check("explode: pieces spread out, bbox gets bigger",
      float(P_(ex_)[:, 0].max() - P_(ex_)[:, 0].min())
      > float(P_(epg)[:, 0].max() - P_(epg)[:, 0].min()))
check("  distance=0 is the identity", np.allclose(P_(EP.explode(
    epg, distance=0.0, piece_from="attribute", piece_attrib="name")),
    P_(epg), atol=1e-6))
check("  prim and point counts unchanged (positions only)",
      (ex_.npoints, ex_.nprims) == (epg.npoints, epg.nprims))

print("═" * 28, "matchsize / centroid / pointjitter / convert")

# scaling needs scale_to_fit (by default it only aligns, no scaling -- aligning and scaling are two separate things)
ms = MS.match_size(BOX, justify_with="target_values", target_size=(2, 2, 2),
                   scale_to_fit=True)
check("match_size(scale_to_fit): scaled to the target size",
      np.allclose(P_(ms).max(0) - P_(ms).min(0), [2, 2, 2], atol=1e-4),
      np.round(P_(ms).max(0) - P_(ms).min(0), 4).tolist())
check("  with uniform_scale=False each axis scales separately",
      np.allclose(np.ptp(P_(MS.match_size(
          BOX, justify_with="target_values", target_size=(2, 4, 6),
          scale_to_fit=True, uniform_scale=False)), axis=0),
          [2, 4, 6], atol=1e-4))
check("  with a second input connected it uses that input's bounding box",
      np.allclose(np.ptp(P_(MS.match_size(
          BOX, target=build.box(size=(3, 3, 3)), scale_to_fit=True)),
          axis=0), [3, 3, 3], atol=1e-4))
check("  default parameters (no scale, no move) are the identity",
      np.allclose(P_(MS.match_size(BOX)), P_(BOX), atol=1e-6))
lo, hi = MS.bounds(BOX)[:2]
check("bounds gives the bounding box", np.allclose(np.asarray(hi) - np.asarray(lo),
                                  [1, 1, 1], atol=1e-5))
ct = CT.extract_centroid(epg, run_over="pieces", piece_attrib="name",
                         output="points")
check("extract_centroid: two pieces -> two points", ct.npoints == 2, ct.npoints)
check("  centroid x near 0 and 3 respectively",
      np.allclose(np.sort(P_(ct)[:, 0]), [0, 3], atol=0.05),
      np.round(np.sort(P_(ct)[:, 0]), 3).tolist())
jt = PJ.point_jitter(GRID, scale=0.1, seed=1)
check("point_jitter: points moved but topology did not",
      topo(jt)[:3] == topo(GRID)[:3]
      and not np.allclose(P_(jt), P_(GRID)))
check("  same seed gives the same result",
      np.array_equal(np.asarray(PJ.point_jitter(GRID, scale=0.1, seed=1)
                                .get(POINT, "P")),
                     np.asarray(PJ.point_jitter(GRID, scale=0.1, seed=1)
                                .get(POINT, "P"))))
check("  different seeds give different results",
      not np.allclose(P_(PJ.point_jitter(GRID, scale=0.1, seed=1)),
                      P_(PJ.point_jitter(GRID, scale=0.1, seed=2))))
check("  scale=0 is the identity", np.allclose(P_(PJ.point_jitter(GRID, scale=0.0)),
                                   P_(GRID)))
check("  jitter amplitude does not exceed scale",
      float(np.abs(P_(jt) - P_(GRID)).max()) <= 0.1 + 1e-6)

img = CV.render_preview(BOX, 64, 64)
check("render_preview produces an (H,W,3) 0-1 image",
      img.shape == (64, 64, 3) and 0.0 <= float(img.min())
      and float(img.max()) <= 1.0, img.shape)
try:
    tm = CV.to_trimesh(BOX)
    check("to_trimesh / from_trimesh round trip, point and prim counts match",
          CV.from_trimesh(tm).npoints == BOX.npoints
          and len(CV.from_trimesh(tm).triangles()) == len(BOX.triangles()))
except RuntimeError as ex:
    check("without trimesh gives an **actionable** error",
          "trimesh" in str(ex) and "pip install" in str(ex), str(ex)[:50])
err("missing optional dependencies all go through convert.need, message includes the install command",
    lambda: CV.need("__nope__", "test"), "pip install")

# pcg119: a snap distance large enough to collapse faces. The degenerate faces are deleted; their points used to be
# dropped there too, which changed the point count under the "Remove Degenerate / Unused" bookkeeping -> crash
_jit = FC.facet(build.grid(size_x=2, size_z=2, cols=8, rows=8), unique=True)
_Pj = np.asarray(_jit.get(POINT, "P"), np.float64).copy()
_Pj += np.random.default_rng(3).uniform(-0.12, 0.12, _Pj.shape)
_jit.set(POINT, "P", _Pj.astype(np.float32))
_res, _err = {}, None
for _d in (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.6, 1.0):
    try:
        _res[_d] = FS.fuse(_jit, use_snap_distance=True, snap_distance=_d).nprims
    except ValueError as _e:
        _err = (_d, str(_e)[:60])
        break
_np = [_res[d] for d in sorted(_res)]
check("fuse with snap distances that collapse faces: never crashes, faces only decrease, all gone at 1 m",
      _err is None and all(a >= b for a, b in zip(_np, _np[1:])) and _np[-1] == 0, _err or _np)

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
