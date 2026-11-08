"""
pcg98 (part 2): PolyFill / Normal / Resample / Sweep / PolyExtrude gain options Houdini has that were missing here.

  PolyFill     Fill Mode gets three quad modes: Quadrilateral Fan / Quadrilaterals / Quadrilateral Grid
  Normal       Weighting Method (By Face Area / Each Vertex Equally / By Vertex Angle), Add Normals to Detail
  Resample     Treat Polygons As (Straight Edges / Subdivision Curves / Interpolating Curves),
               Maximum Segment Length together with Maximum Segments
  Sweep        Surface Type gets Alternating Triangles / Rows / Columns / Rows and Columns / Points; End Cap Type = Grid
  PolyExtrude  Extrusion Mode = Point Normal

Output at default values is the same as before (new parameters appended at the end). Every new option is checked against hand-computed numbers.
"""
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo import build, ops, polyfill as PF  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def tri_(g):
    P, T = P_(g), g.triangles()
    return P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]


def area(g):
    a, b, c = tri_(g)
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def volume(g):
    a, b, c = tri_(g)
    return float((a * np.cross(b, c)).sum() / 6.0)


def closed_manifold(g):
    """Every edge is used by exactly two faces, in opposite directions."""
    seen = {}
    for k in range(g.nprims):
        pts = g.prim_points(k)
        for i in range(len(pts)):
            e = (int(pts[i]), int(pts[(i + 1) % len(pts)]))
            seen[e] = seen.get(e, 0) + 1
    return all(v == 1 for v in seen.values()) and all((b, a) in seen for (a, b) in seen)


def run(nid, **over):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def names(nid):
    it = M[nid].INPUT_TYPES()
    return [k for part in ("required", "optional") for k in it.get(part, {})]


close = lambda a, b, e=1e-5: np.allclose(a, b, atol=e)          # noqa: E731

sec("old workflows unchanged: new parameters at the end, old dropdown values still in place")
# pcg100: Normal got six more after weighting (test_audit_s1_group_delete.py covers them)
tails = {"PCG_Normal": ["weighting", "group_type", "normal_name", "compute_normals", "keep_zero", "make_unit",
                        "reverse"], "PCG_Resample": ["treat_polygons_as", "use_max_segments", "max_segments",
                                          # pcg100 s3_curves added eight more (test_audit_s3_curves.py covers them)
                                          "measure_method", "measure", "maintain_prim_order", "resample_by_edge",
                                          "attrib_override", "maintain_last_vertex", "randomize_first",
                                          "subdivide_later"],
         "PCG_Sweep": ["end_cap_type", "cross"], "PCG_PolyExtrude": ["extrusion_mode", "spine"]}
bad = [k for k, v in tails.items() if names(k)[-len(v):] != v]
check("Normal / Resample / Sweep / PolyExtrude: new widgets come after all old widgets", not bad, bad)
it = lambda k, n: list(M[k].INPUT_TYPES()["required"][n][0])     # noqa: E731
check("dropdowns only gain options at the end: PolyFill's Fill Mode, Sweep's Surface Type, Normal's Add Normals to still start with the original ones",
      it("PCG_PolyFill", "mode")[:3] == ["ngon", "fan", "triangles"] and it("PCG_Sweep", "surface_type")[:2] == ["quads", "triangles"]
      and it("PCG_Normal", "add_to")[:3] == ["point", "vertex", "prim"] and it("PCG_Resample", "treat_polygons_as")[0] == "straight_edges"
      and it("PCG_PolyExtrude", "extrusion_mode")[0] == "prim_edge_normal" and it("PCG_Sweep", "end_cap_type")[0] == "single_polygon"
      and list(M["PCG_Normal"].INPUT_TYPES()["optional"]["weighting"][0])[0] == "by_face_area")

# ═══════════════════════════════════════════════════════ PolyFill
sec("PolyFill:Quadrilateral Fan / Quadrilaterals / Quadrilateral Grid")
oct_area = 2 * np.sqrt(2.0)                       # regular octagon of radius 1
tube8 = build.tube(1.0, 1.0, 2.0, cols=8, rows=2, caps=False)
ref = volume(PF.fill(tube8, "ngon"))
check("octagonal tube (no caps): Single Polygon closes it, volume = 2·2√2, closed", close(ref, 2 * oct_area, 1e-4) and closed_manifold(PF.fill(tube8, "ngon")))
for mode, npt, sizes in (("quad_fan", 2, [4] * 8), ("quads", 0, [4] * 6), ("quad_grid", 2, [4] * 8)):
    g = PF.fill(tube8, mode, output_group="cap")
    cap = g.groups[PRIM]["cap"]
    check(f"  {mode}: each of the two holes filled with {len(sizes) // 2} quads, {npt} points added; same volume, closed, normals outward (positive volume)",
          g.npoints == tube8.npoints + npt and g.prim_sizes()[cap].tolist() == sizes and close(volume(g), ref, 1e-4)
          and closed_manifold(g), (g.npoints - tube8.npoints, g.prim_sizes()[cap].tolist(), volume(g)))
g = PF.fill(tube8, "quad_fan")
check("  quad_fan / quad_grid add points at the hole centers (0, ±1, 0)", close(sorted(P_(g)[-2:, 1].tolist()), [-1, 1]) and close(P_(g)[-2:, [0, 2]], 0)
      and close(P_(PF.fill(tube8, "quad_grid"))[-2:, [0, 2]], 0))
tube7 = build.tube(1.0, 1.0, 2.0, cols=7, rows=2, caps=False)
r7 = volume(PF.fill(tube7, "ngon"))
for mode, sizes in (("quad_fan", [3, 4, 4, 4]), ("quads", [3, 4, 4]), ("quad_grid", [3, 4, 4])):
    g = PF.fill(tube7, mode, output_group="cap")
    cap = g.groups[PRIM]["cap"]
    check(f"  heptagon hole, {mode}: quads + one leftover triangle"
          + ("; an odd edge count can't be gridded, falls back to quads (no points added)" if mode == "quad_grid" else ""),
          sorted(g.prim_sizes()[cap][:len(sizes)].tolist()) == sizes and close(volume(g), r7, 1e-4) and closed_manifold(g)
          and (mode == "quad_fan" or g.npoints == tube7.npoints), g.prim_sizes()[cap].tolist())
gr = build.grid(4.0, 4.0, 5, 5)                    # 4×4 cells, grid spacing 1
quads = gr.vertex_point.reshape(-1, 4)
ctr = P_(gr)[quads].mean(1)
hole2 = (np.abs(ctr[:, 0]) < 1) & (np.abs(ctr[:, 2]) < 1)            # the middle 2×2
holed = ops.delete_prims(gr, ~hole2)
f = PF.fill(holed, "quad_grid", max_sides=8, output_group="cap")
cap = f.groups[PRIM]["cap"]
check("middle 2×2 cells cut out of a plane (square hole, 8 edges): Quadrilateral Grid fills 4 quads + 1 point, exactly the original grid point (0,0,0); "
      "the outer boundary (16 edges) is blocked by Max Hole Sides and not filled", int(cap.sum()) == 4 and f.npoints == holed.npoints + 1
      and close(P_(f)[-1], [0, 0, 0]) and close(area(f), 16.0), (int(cap.sum()), P_(f)[-1].tolist(), area(f)))
a, b, c = tri_(f)
check("  filled faces face the same way as their surroundings (normals all +Y)", (np.cross(b - a, c - a)[:, 1] > 0).all())
orig = {frozenset(map(tuple, np.round(P_(gr)[q], 4))) for q in quads[hole2]}
got = {frozenset(map(tuple, np.round(P_(f)[f.prim_points(k)], 4))) for k in np.nonzero(cap)[0]}
check("  the four corners are picked right: the 4 filled quads are exactly the 4 cells that were cut out", orig == got)
gr6 = build.grid(6.0, 6.0, 7, 7)
quads6 = gr6.vertex_point.reshape(-1, 4)
ctr6 = P_(gr6)[quads6].mean(1)
hole32 = (ctr6[:, 0] > -2) & (ctr6[:, 0] < 1) & (np.abs(ctr6[:, 2]) < 1)   # a 3×2 rectangular hole, 10 edges
h32 = ops.delete_prims(gr6, ~hole32)
f = PF.fill(h32, "quad_grid", max_sides=10, output_group="cap")
cap = f.groups[PRIM]["cap"]
orig = {frozenset(map(tuple, np.round(P_(gr6)[q], 4))) for q in quads6[hole32]}
got = {frozenset(map(tuple, np.round(P_(f)[f.prim_points(k)], 4))) for k in np.nonzero(cap)[0]}
check("  3×2 rectangular hole (10 edges): fills 6 quads + 2 points, identical to the 6 cells cut out (Coons interpolation on a rectangle gives evenly spaced grid points)",
      int(cap.sum()) == 6 and f.npoints == h32.npoints + 2 and orig == got, (int(cap.sum()), f.npoints - h32.npoints))
check("  new points' uv is the average of the hole's boundary loop (has values, right row count)", f.get(POINT, "uv") is not None and len(f.get(POINT, "uv")) == f.npoints
      and np.isfinite(np.asarray(f.get(POINT, "uv"))).all())
sq = PF.fill(ops.delete_prims(gr, ~(np.abs(ctr[:, 0] - 0.5) + np.abs(ctr[:, 2] - 0.5) < 0.1)), "quad_grid", max_sides=4, output_group="cap")
gr8 = build.grid(8.0, 4.0, 9, 5)
q8 = gr8.vertex_point.reshape(-1, 4)
c8 = P_(gr8)[q8].mean(1)
two_h = (np.abs(c8[:, 2]) < 1) & ((np.abs(c8[:, 0] + 2) < 1) | (np.abs(c8[:, 0] - 2) < 1))     # two 2×2 holes, centers at x = ∓2
for mode in ("quad_fan", "quad_grid", "fan"):
    f2 = PF.fill(ops.delete_prims(gr8, ~two_h), mode, max_sides=8)
    newp, newuv = P_(f2)[-2:], np.asarray(f2.get(POINT, "uv"), np.float64)[-2:]
    olduv = np.asarray(gr8.get(POINT, "uv"), np.float64)
    want = [olduv[np.argmin(np.linalg.norm(P_(gr8) - p, axis=1))] for p in newp]      # the original uv of the grid point at each hole's center
    check(f"  two holes, {mode}: each hole's new point takes the average of **its own** loop (= the original uv of the hole-center grid point), not bleeding into the other hole",
          close(sorted(newp[:, 0].tolist()), [-2, 2]) and close(newuv, want, 1e-5), (newp[:, 0].tolist(), newuv.tolist()))
check("  only one cell cut out (4 edges): one quad filled, no points added", int(sq.groups[PRIM]["cap"].sum()) == 1 and sq.npoints == gr.npoints)
check("node: Fill Mode dropdown has 6 items, Houdini's names on the panel", it("PCG_PolyFill", "mode") == list(PF.MODES) and len(PF.MODES) == 6
      and all(x in str(PANEL.panel_model("PCG_PolyFill", M["PCG_PolyFill"].INPUT_TYPES()))
              for x in ("Quadrilateral Fan", "Quadrilaterals", "Quadrilateral Grid")))
try:
    PF.fill(tube8, "hexagons")
    check("Mode set to something else: error", False)
except ValueError:
    check("Mode set to something else: error", True)

# ═══════════════════════════════════════════════════════ Normal
sec("Normal:Weighting Method / Detail")
# the origin is shared by two triangles: A on the XY plane (normal +Z) is large and sharp (area 5, angle at the origin atan 0.1);
# B on the XZ plane (normal +Y) is small and blunt (area 0.5, angle 90°)
tw = Geometry.from_mesh(np.array([[0, 0, 0], [10, 0, 0], [10, 1, 0], [0, 0, 1], [1, 0, 0]], np.float32),
                        [np.array([0, 1, 2]), np.array([0, 3, 4])])
angA = np.arctan(0.1)
exp = {"by_face_area": [0, 0.5, 5.0], "each_vertex_equally": [0, 1.0, 1.0], "by_vertex_angle": [0, np.pi / 2, angA]}
for w, v in exp.items():
    v = np.asarray(v) / np.linalg.norm(v)
    n = np.asarray(run("PCG_Normal", geo=tw, add_to="point", weighting=w).get(POINT, "N"), np.float64)[0]
    nv = np.asarray(run("PCG_Normal", geo=tw, add_to="vertex", cusp_angle=180.0, weighting=w).get(VERTEX, "N"), np.float64)[0]
    check(f"{w}: normal at the shared point = {np.round(v, 4).tolist()} (both the point normal and the vertex normal with cusp 180°)", close(n, v, 1e-5) and close(nv, v, 1e-5),
          (n.tolist(), nv.tolist()))
check("  the three weightings really give different results; default (not passed) = By Face Area", close(
    np.asarray(ops.compute_normals(tw).get(POINT, "N"))[0], np.array([0, 0.5, 5]) / np.linalg.norm([0, 0.5, 5])))
check("  points belonging to a single face: every weighting gives that face's normal", all(close(
    np.asarray(run("PCG_Normal", geo=tw, add_to="point", weighting=w).get(POINT, "N"))[[1, 3]], [[0, 0, 1], [0, 1, 0]]) for w in exp))
check("  cusp angle as before: at 60° the two faces (90° apart) are not merged, each vertex normal is its own", close(
    np.asarray(run("PCG_Normal", geo=tw, add_to="vertex", cusp_angle=60.0, weighting="by_vertex_angle").get(VERTEX, "N"))[[0, 3]],
    [[0, 0, 1], [0, 1, 0]]))
qt = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0.2, 0], [0, 1, 0], [0, 0, 1]], np.float32),
                        [np.array([0, 1, 2, 3]), np.array([0, 4, 1])])
# origin: the quad (XY plane, normal +Z) has a 90° angle here (neighbor edges (1,0,0), (0,1,0)); the triangle (XZ plane, normal +Y) is also 90°
nq = np.asarray(ops.compute_normals(qt, "point", weighting="by_vertex_angle").get(POINT, "N"), np.float64)[0]
check("  a quad's angle = the angle between this point's **previous and next neighbor edges** (not to the diagonal point): at the origin quad 90°, triangle 90° -> (0, 1, 1)/√2",
      close(nq, np.array([0, 1, 1]) / np.sqrt(2)), nq.tolist())
deg = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 0, 1], [1, 0, 0.0]], np.float32),
                         [np.array([0, 1, 2]), np.array([0, 3, 4])])            # the first face has three collinear points (area 0)
check("  degenerate faces (area 0) don't count in Each Vertex Equally / By Vertex Angle", all(close(
    np.asarray(ops.compute_normals(deg, "point", weighting=w).get(POINT, "N"))[0], [0, 1, 0]) for w in exp))
tilt = ops.transform(build.grid(2, 2, 3, 3), rotate=(0, 0, 90))
dn = run("PCG_Normal", geo=tilt, add_to="detail")
check("Add Normals to Detail: ground plane stood up (rotated 90° about Z) -> detail N = (−1, 0, 0); point / primitive attributes untouched",
      close(np.asarray(dn.get(DETAIL, "N"))[0], [-1, 0, 0]) and dn.get(POINT, "N") is None and dn.get(PRIM, "N") is None,
      np.asarray(dn.get(DETAIL, "N")).tolist())
check("  closed box (area normals sum to 0) / empty geometry: gives (0, 1, 0), no NaN",
      close(np.asarray(ops.compute_normals(build.box(), "detail").get(DETAIL, "N"))[0], [0, 1, 0])
      and close(np.asarray(ops.compute_normals(Geometry(), "detail").get(DETAIL, "N"))[0], [0, 1, 0]))
try:
    ops.compute_normals(tw, weighting="by_mass")
    check("Weighting set to something else: error", False)
except ValueError as e:
    check("Weighting set to something else: error", "Weighting Method must be one of" in str(e))
ui = PANEL.layout_for("PCG_Normal", M["PCG_Normal"].INPUT_TYPES())[0]
check("panel: Weighting Method hidden in Primitives / Detail modes", ui["weighting"]["hide"] == "{ add_to == prim } { add_to == detail }")

# ═══════════════════════════════════════════════════════ Resample
sec("Resample:Treat Polygons As / Maximum Segments")
L = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [2, 0, 1]], np.float32), [np.arange(4)], closed=False)
L.set(POINT, "w", np.arange(4, dtype=np.float32)[:, None])
R = lambda g=L, **kw: run("PCG_Resample", geo=g, method="segment_count", segments=400, **kw)   # noqa: E731
length = lambda g: float(np.linalg.norm(np.diff(P_(g), axis=0), axis=1).sum())                  # noqa: E731
st, sb, ip = R(), R(treat_polygons_as="subdivision_curves"), R(treat_polygons_as="interpolating_curves")
dmin = lambda g, p: float(np.linalg.norm(P_(g) - np.asarray(p), axis=1).min())                  # noqa: E731
check("Straight Edges (default): bit-identical to not passing the parameter; total length 3", np.array_equal(P_(st), P_(ops.resample(L, None, False, segments=400)))
      and abs(length(st) - 3.0) < 0.01)
check("Subdivision Curves: the points are B-spline control points -- the curve doesn't pass through the corner, closest to (1,0,0) is |P₀ − 2P₁ + P₂| / 6 = √2/6 = 0.2357; both end points still hit",
      abs(dmin(sb, [1, 0, 0]) - np.sqrt(2) / 6) < 2e-3 and close(P_(sb)[0], [0, 0, 0]) and close(P_(sb)[-1], [2, 0, 1]), dmin(sb, [1, 0, 0]))
check("Interpolating Curves: the curve passes through every original point (< 0.003 from both corners), end points hit",
      dmin(ip, [1, 0, 0]) < 3e-3 and dmin(ip, [1, 0, 1]) < 3e-3 and close(P_(ip)[0], [0, 0, 0]) and close(P_(ip)[-1], [2, 0, 1]),
      (dmin(ip, [1, 0, 0]), dmin(ip, [1, 0, 1])))
check("  length: Subdivision cutting corners < straight edges 3 < Interpolating bulging out", length(sb) < 2.8 < 3.0 < length(ip), (length(sb), length(ip)))
check("  sampling divides the **curve's** arc length evenly (every segment the same length)", np.ptp(np.linalg.norm(np.diff(P_(sb), axis=0), axis=1)) < 2e-4
      and np.ptp(np.linalg.norm(np.diff(P_(ip), axis=0), axis=1)) < 2e-4)
w = np.asarray(ip.get(POINT, "w")).ravel()
check("  point attributes follow the spline interpolation: w goes monotonically from 0 to 3", close(w[0], 0) and close(w[-1], 3) and (np.diff(w) > -1e-6).all())
sqr = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32), [np.arange(4)], closed=True)
cs = run("PCG_Resample", geo=sqr, method="segment_count", segments=200, treat_polygons_as="subdivision_curves")
ci = run("PCG_Resample", geo=sqr, method="segment_count", segments=200, treat_polygons_as="interpolating_curves")
rad = lambda g: np.linalg.norm(P_(g)[:, [0, 2]] - 0.5, axis=1)                                   # noqa: E731
check("closed square: output still closed, 200 points; Subdivision shrinks to a rounded square inside (all within the square); Interpolating passes through the four corners (bulges out)",
      bool(cs.prim_closed[0]) and cs.npoints == 200 and rad(cs).max() < 0.5 * np.sqrt(2) - 0.1
      and (np.abs(P_(cs)[:, [0, 2]] - 0.5).max() < 0.5) and dmin(ci, [1, 0, 1]) < 5e-3 and bool(ci.prim_closed[0])
      and np.abs(P_(ci)[:, [0, 2]] - 0.5).max() > 0.5, (rad(cs).max(), np.abs(P_(ci)[:, [0, 2]] - 0.5).max()))
two = ops.merge(L, ops.transform(L, translate=(0, 5, 0)))
two.set_group(PRIM, "second", np.array([False, True]))
o = run("PCG_Resample", geo=two, group="second", method="segment_count", segments=50, treat_polygons_as="interpolating_curves")
check("Group: only the selected curve is densely resampled, the other unchanged; no temporary group left behind; the original group still there and still pointing at that curve",
      sorted(o.prim_sizes().tolist()) == [4, 51] and "__resample_sel" not in o.groups[PRIM]
      and o.prim_sizes()[np.asarray(o.groups[PRIM]["second"])].tolist() == [51], (o.prim_sizes().tolist(), list(o.groups[PRIM])))
rs = lambda **kw: run("PCG_Resample", geo=L, method="max_segment_length", length=0.1, **kw)      # noqa: E731
check("Maximum Segments: length 0.1 would give 30 segments; cap 7 -> exactly 7, evenly divided; cap 100 -> still 30; unchecked -> 30",
      rs(use_max_segments=True, max_segments=7).npoints == 8
      and np.array_equal(P_(rs(use_max_segments=True, max_segments=7)), P_(run("PCG_Resample", geo=L, method="segment_count", segments=7)))
      and rs(use_max_segments=True, max_segments=100).npoints == 31 and rs(use_max_segments=False, max_segments=7).npoints == 31,
      rs(use_max_segments=True, max_segments=7).npoints)
check("  cap exactly equal to the computed segment count: unchanged; still capped with Even Last Segment off",
      rs(use_max_segments=True, max_segments=30).npoints == 31
      and run("PCG_Resample", geo=L, method="max_segment_length", length=0.7, even_last_segment=False,
              use_max_segments=True, max_segments=3).npoints == 4)
try:
    ops.resample(L, treat_as="nurbs")
    check("Treat Polygons As set to something else: error", False)
except ValueError as e:
    check("Treat Polygons As set to something else: error", "Treat Polygons As must be one of" in str(e))

# ═══════════════════════════════════════════════════════ Sweep
sec("Sweep:Surface Type / End Cap Type")
bb = Geometry.from_mesh(np.array([[0, 0, 0], [0, 1, 0], [0, 2, 0]], np.float32), [np.arange(3)], closed=False)
S = lambda g=bb, **kw: run("PCG_Sweep", backbone=g, shape="round_tube", cols=8, radius=0.5, **kw)   # noqa: E731
q = S()
check("default (Quadrilaterals): 2 × 8 quads, 3 × 8 points", q.nprims == 16 and (q.prim_sizes() == 4).all() and q.npoints == 24)
at = S(surface_type="alternating_triangles")
tr = S(surface_type="triangles")


def diag_set(g):
    """The diagonal cut in each quad cell (as point-number pairs)."""
    Pn = g.npoints
    quads_e = {tuple(sorted(e)) for k in range(q.nprims) for e in zip(q.prim_points(k), np.roll(q.prim_points(k), -1))}
    out = set()
    for k in range(g.nprims):
        pts = g.prim_points(k)
        for e in zip(pts, np.roll(pts, -1)):
            e = tuple(sorted(map(int, e)))
            if e not in quads_e:
                out.add(e)
    return out


check("Alternating Triangles: 32 triangles, same area as the quads; one diagonal per cell, half the cells cut on a different diagonal than in Triangles mode",
      at.nprims == 32 and (at.prim_sizes() == 3).all() and close(area(at), area(q), 1e-5) and len(diag_set(at)) == 16
      and len(diag_set(at) & diag_set(tr)) == 8, (at.nprims, len(diag_set(at)), len(diag_set(at) & diag_set(tr))))
a, b, c = tri_(at)
check("  no flipped faces (normals all outward)", ((np.cross(b - a, c - a) * ((a + b + c) / 3 * [1, 0, 1])).sum(1) > 0).all())
ro, co, rc, po = (S(surface_type=t) for t in ("rows", "columns", "rows_and_columns", "points"))
check("Rows: one closed polyline per cross-section (3 loops × 8 points, y constant per loop)", ro.nprims == 3 and (ro.prim_sizes() == 8).all() and ro.prim_closed.all()
      and all(np.ptp(P_(ro)[ro.prim_points(k)][:, 1]) < 1e-6 for k in range(3)))
check("Columns: 8 open polylines along the backbone (3 points each, x / z constant)", co.nprims == 8 and (co.prim_sizes() == 3).all() and not co.prim_closed.any()
      and all(np.ptp(P_(co)[co.prim_points(k)][:, [0, 2]], axis=0).max() < 1e-6 for k in range(8)))
check("Rows and Columns: 3 + 8 curves; Points: 24 points, no prims", rc.nprims == 11 and po.nprims == 0 and po.npoints == 24)
check("  point positions in these modes all match the default; no caps when outputting curves / points even with End Caps on", all(np.array_equal(P_(x), P_(q)) for x in (at, tr, ro, co, rc, po))
      and S(surface_type="rows", end_caps=True).nprims == 3 and S(surface_type="points", end_caps=True).nprims == 0
      and not S(surface_type="rows", end_caps=True).groups[PRIM]["endcaps"].any())
ring = build.circle((2.0, 2.0), divisions=12) if "divisions" in build.circle.__code__.co_varnames else None
loop = Geometry.from_mesh(np.array([[2, 0, 0], [0, 0, 2], [-2, 0, 0], [0, 0, -2]], np.float32), [np.arange(4)], closed=True)
cl = S(loop, surface_type="columns")
check("closed backbone: Columns are closed too", cl.nprims == 8 and cl.prim_closed.all() and (cl.prim_sizes() == 4).all())
sp, gd = S(end_caps=True), S(end_caps=True, end_cap_type="grid")
check("End Cap Type = Single Polygon (default): two octagon caps; closed", sp.nprims == 18 and sorted(sp.prim_sizes().tolist())[-2:] == [8, 8] and closed_manifold(sp))
capg = gd.groups[PRIM]["endcaps"]
check("End Cap Type = Grid: 4 quads per cap + 1 center point (the backbone's end point); same volume as single-polygon caps, closed; end cap group has 8 faces",
      gd.nprims == 16 + 8 and (gd.prim_sizes() == 4).all() and gd.npoints == 26 and int(capg.sum()) == 8
      and close(P_(gd)[-2:][np.argsort(P_(gd)[-2:, 1])], [[0, 0, 0], [0, 2, 0]]) and close(volume(gd), volume(sp), 1e-5) and closed_manifold(gd)
      and volume(gd) > 0, (gd.nprims, gd.npoints, volume(gd), volume(sp)))
g7 = run("PCG_Sweep", backbone=bb, shape="round_tube", cols=7, radius=0.5, end_caps=True, end_cap_type="grid")
check("  a 7-point (odd) cross-section can't be gridded: falls back to a single polygon", sorted(g7.prim_sizes().tolist())[-2:] == [7, 7] and g7.npoints == 21)
gu = S(end_caps=True, end_cap_type="grid", use_uv=True, uv_attrib="uv")
uv = np.asarray(gu.get(POINT, "uv"))
check("  Grid caps + UV: the two cap-center points also have uv (u = 0.5, v = 0 / 1 at the two ends), right row count", len(uv) == gu.npoints and close(uv[-2:], [[0.5, 0], [0.5, 1]]),
      uv[-2:].tolist())
for bad_kw in (dict(surface_type="hexes"), dict(end_cap_type="fan")):
    try:
        ops.sweep(bb, **bad_kw)
        check(f"{list(bad_kw)[0]} set to something else: error", False)
    except ValueError:
        check(f"{list(bad_kw)[0]} set to something else: error", True)

# ═══════════════════════════════════════════════════════ PolyExtrude
sec("PolyExtrude:Extrusion Mode = Point Normal")
box = build.box((2, 2, 2))
top = np.asarray([np.allclose(P_(box)[box.prim_points(k)][:, 1], 1) for k in range(box.nprims)])
box.set_group(PRIM, "top", top)
E = lambda **kw: run("PCG_PolyExtrude", geo=box, group="top", distance=np.sqrt(3.0), **kw)       # noqa: E731
d0, d1 = E(), E(extrusion_mode="point_normal")
front = lambda g: P_(g)[np.unique(np.concatenate([g.prim_points(k) for k in np.nonzero(g.groups[PRIM]["extrudeFront"])[0]]))]   # noqa: E731
check("default (Primitive/Edge Normal): top face moves √3 along face normal +Y, still 2×2", close(sorted(map(tuple, np.round(front(d0), 4))),
      sorted([(x, 1 + np.sqrt(3), z) for x in (-1, 1) for z in (-1, 1)]), 1e-4))
check("Point Normal: a box corner's point normal is (±1, 1, ±1)/√3 -- each of the top face's four corners moves √3 along its own diagonal, to (±2, 2, ±2), the top opens to 4×4",
      close(sorted(map(tuple, np.round(front(d1), 4))), sorted([(x, 2.0, z) for x in (-2, 2) for z in (-2, 2)]), 1e-4),
      np.round(front(d1), 3).tolist())
bn = box.copy()
bn.set(POINT, "N", np.tile([2.0, 0, 0], (8, 1)).astype(np.float32))      # deliberately not unit length
dn_ = run("PCG_PolyExtrude", geo=bn, group="top", distance=1.0, extrusion_mode="point_normal")
check("  points already have an N attribute: its **direction** is used (all +X, length 2 -> top face still just translated by Distance = 1)", close(sorted(map(tuple, np.round(front(dn_), 4))),
      sorted([(x + 1, 1.0, z) for x in (-1, 1) for z in (-1, 1)]), 1e-4))
dd = run("PCG_PolyExtrude", geo=box, group="top", distance=1.0, extrusion_mode="point_normal", use_direction=True,
         dir_x=0.0, dir_y=0.0, dir_z=1.0)
check("  Direction checked: the direction wins (+Z), Point Normal has no effect", close(sorted(map(tuple, np.round(front(dd), 4))),
      sorted([(x, 1.0, z + 1) for x in (-1, 1) for z in (-1, 1)]), 1e-4))
try:
    ops.polyextrude(box, extrusion_mode="vertex")
    check("Extrusion Mode set to something else: error", False)
except ValueError as e:
    check("Extrusion Mode set to something else: error", "Extrusion Mode must be one of" in str(e))

sec("panel")
for k in ("PCG_PolyFill", "PCG_Normal", "PCG_Resample", "PCG_Sweep", "PCG_PolyExtrude", "PCG_VoronoiFracture"):
    probs = PANEL.check_layout(k, M[k].INPUT_TYPES())
    pm = str(PANEL.panel_model(k, M[k].INPUT_TYPES()))
    lost = [n for n in names(k) if n not in ("geo", "backbone", "cross", "spine", "points") and n not in pm]
    check(f"{k}: spec self-check clean, every parameter is on the panel", not probs and not lost, (probs, lost))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
