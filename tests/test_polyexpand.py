"""
PolyExpand2D's Offset Surfaces (pcg97): the band between the input and the offset lines is filled with triangles.

Everything is checked against **areas you can compute by hand**:
  square 2×2, offset 0.2   inner band = 4 − 1.6² ; outer (mitered, square corners) = 2.4² − 4
  negative offset           inside and outside swap
  offset 1.5 > half width   the wavefront collapses: inside = the whole face, 4; outside = 5² − 4
  L shape (one concave corner)  matches the area enclosed by the two loops of Offset Curves (same offset, both outputs must agree)
  a segment of length 10, offset 1  square caps: 12 × 2
  face with a hole (square ring)  inner band = outer loop shrunk + hole grown, two bands
  7×7 road grid            one band per block + one ring outside
Also: no triangle crosses an input edge / offset line (each triangle's centroid is within offset·√2 of the input, the farthest point of a miter corner);
consistent triangle winding; extra loops from Divisions are edges in the mesh; groups, Edge Distance attribute; Output Inside / Outside;
Winding Number mode; Keep Input; no overlap (sum of areas = union area, counted on a raster).
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
from comfyui_pcg.geo import build                       # noqa: E402
from comfyui_pcg.geo import polyexpand2d as PE          # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402
from comfyui_pcg.panel import panel_model               # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def poly(pts, closed=True):
    P = np.array([[x, 0, z] for x, z in pts], np.float32)
    return Geometry.from_mesh(P, [np.arange(len(P))], closed=closed)


def tris(o):
    P = np.asarray(o.get(POINT, "P"), np.float64)
    return P, o.triangles()


def area(o):
    if not o.nprims:
        return 0.0
    P, T = tris(o)
    return float(0.5 * np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1).sum())


def ring_area(P):
    x, z = P[:, 0], P[:, 2]
    return 0.5 * abs(float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z)))


def covered(o, lo, hi, n=400):
    """Union area counted on a raster (whether each cell center is inside some triangle). Overlapping triangles count once."""
    P, T = tris(o)
    xs = lo + (np.arange(n) + 0.5) * (hi - lo) / n
    gx, gz = np.meshgrid(xs, xs)
    Q = np.stack([gx.ravel(), gz.ravel()], 1)
    hit = np.zeros(len(Q), bool)
    for t in T:
        a, b, c = P[t][:, [0, 2]]
        d = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        u = ((Q[:, 0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (Q[:, 1] - a[1])) / d
        v = ((b[0] - a[0]) * (Q[:, 1] - a[1]) - (Q[:, 0] - a[0]) * (b[1] - a[1])) / d
        hit |= (u >= 0) & (v >= 0) & (u + v <= 1)
    return float(hit.mean() * (hi - lo) ** 2)


def S(g, d, **kw):
    return PE.polyexpand2d(g, output="offset_surfaces", offset=d, **kw)


close = lambda a, b, e=1e-5: abs(a - b) <= e * max(1.0, abs(b))

sec("square 2×2: hand-computed areas")
sq = poly([(0, 0), (2, 0), (2, 2), (0, 2)])
a_in, a_out = 4 - 1.6 ** 2, 2.4 ** 2 - 4
check("offset 0.2 inner band = 4 − 1.6² = 1.44", close(area(S(sq, 0.2, output_outside=False)), a_in),
      area(S(sq, 0.2, output_outside=False)))
check("  outer (mitered: square corners, not round) = 2.4² − 4 = 1.76", close(area(S(sq, 0.2, output_inside=False)), a_out),
      area(S(sq, 0.2, output_inside=False)))
check("  negative control: with round corners the outside would be 4·2·0.2 + π·0.2² = 1.7257, which doesn't match", not close(area(S(sq, 0.2, output_inside=False)),
      1.6 + np.pi * 0.04, 1e-3))
both = S(sq, 0.2)
check("  both sides = sum of both bands; no overlap (same union area counted on a raster)", close(area(both), a_in + a_out)
      and abs(covered(both, -0.5, 2.5) - (a_in + a_out)) < 0.02, (area(both), covered(both, -0.5, 2.5)))
check("  both sides off = empty", S(sq, 0.2, output_inside=False, output_outside=False).nprims == 0)
check("negative offset: inside and outside swap (the inside group grows outward)", close(area(S(sq, -0.2, output_outside=False)), a_out)
      and close(area(S(sq, -0.2, output_inside=False)), a_in))
check("offset 1.5 exceeds half width (shrinks away inward): inside = the whole face, 4; outside = 5² − 4",
      close(area(S(sq, 1.5, output_outside=False)), 4.0) and close(area(S(sq, 1.5, output_inside=False)), 21.0),
      (area(S(sq, 1.5, output_outside=False)), area(S(sq, 1.5, output_inside=False))))
o = S(sq, 0.2)
P, T = tris(o)
n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
check("all triangles, consistent winding (normals have the same sign), none degenerate", (o.prim_sizes() == 3).all() and o.prim_closed.all()
      and (np.sign(n[:, 1]) == np.sign(n[0, 1])).all() and (np.linalg.norm(n, axis=1) > 1e-9).all())
check("Offset Curves mode unchanged: two closed loops", (lambda c: c.nprims == 2 and (c.prim_sizes() == 4).all())(
    PE.polyexpand2d(sq, offset=0.2)))

sec("Divisions, groups, Edge Distance")
o = S(sq, 0.6, divisions=3, output_outside=False, edge_dist_attrib="dist", create_groups=True)
dist = np.round(np.asarray(o.get(POINT, "dist"), np.float64).ravel(), 5)
check("Divisions 3: same area (4 − 0.8²); the two middle loops are points in the mesh, dist attribute 0 / 0.2 / 0.4 / 0.6",
      close(area(o), 4 - 0.64) and np.allclose(sorted(set(dist.tolist())), [0.0, 0.2, 0.4, 0.6]), sorted(set(dist.tolist())))
P, T = tris(o)
dt = dist[T]
check("  no triangle crosses a middle loop (a triangle's three points differ in dist by at most one step of 0.2)",
      float((dt.max(1) - dt.min(1)).max()) <= 0.2 + 1e-5, float((dt.max(1) - dt.min(1)).max()))
d1 = S(sq, 0.6, divisions=1, output_outside=False)
check("  Divisions 1 has fewer triangles than 3", d1.nprims < o.nprims, (d1.nprims, o.nprims))
check("  dist on points agrees with the geometry: dist = distance from the point to the square's boundary", np.allclose(
    dist, np.minimum.reduce([P[:, 0], 2 - P[:, 0], P[:, 2], 2 - P[:, 2]]), atol=1e-5))
o = S(sq, 0.2, create_groups=True)
gi, go = o.groups[PRIM]["inside"], o.groups[PRIM]["outside"]
Pc = np.asarray(o.get(POINT, "P"))[o.triangles()].mean(1)
inside_sq = (Pc[:, 0] > 0) & (Pc[:, 0] < 2) & (Pc[:, 2] > 0) & (Pc[:, 2] < 2)
check("groups: inside = triangles whose centroid is in the square, outside = the rest", (gi == inside_sq).all() and (go == ~inside_sq).all()
      and gi.any() and go.any())
o = S(sq, 0.2, create_groups=True, inside_group="a", outside_group="")
check("  empty group names are not created", "a" in o.groups[PRIM] and len(o.groups[PRIM]) == 1, list(o.groups[PRIM]))
check("  Create Output Groups off: no groups; no attribute name: no attribute", not S(sq, 0.2).groups.get(PRIM)
      and S(sq, 0.2).get(POINT, "dist") is None)

sec("concave corners, open curves, holes, road grid")
L = poly([(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)])
c = PE.polyexpand2d(L, offset=0.3)
Pc = np.asarray(c.get(POINT, "P"), np.float64)
ra = sorted(ring_area(Pc[c.prim_points(i)]) for i in range(c.nprims))
check("L shape: inner band = 7 − area enclosed by the inner loop, outer = area enclosed by the outer loop − 7 (same offset as Offset Curves)",
      close(area(S(L, 0.3, output_outside=False)), 7 - ra[0]) and close(area(S(L, 0.3, output_inside=False)), ra[1] - 7),
      (area(S(L, 0.3, output_outside=False)), 7 - ra[0]))
check("  the outside doesn't overlap at the concave corner (union area = sum of areas)", abs(covered(S(L, 0.3), -1, 5) - area(S(L, 0.3))) < 0.03,
      (covered(S(L, 0.3), -1, 5), area(S(L, 0.3))))
tri_ = poly([(0, 0), (4, 0), (0.4, 1)])                           # a very sharp triangle: the miter corner reaches far
o = S(tri_, 0.1, output_inside=False)
c = PE.polyexpand2d(tri_, offset=0.1, output_inside=False)
Pc = np.asarray(c.get(POINT, "P"), np.float64)
check("sharp corner: the piece the miter sticks out is also in the surface (judging by 'distance to input < offset' would drop it)",
      close(area(o), ring_area(Pc[c.prim_points(0)]) - 2.0, 1e-4)
      and float(np.linalg.norm(np.asarray(o.get(POINT, "P"))[:, [0, 2]] - [4, 0], axis=1).min()) < 1e-6
      and float(np.asarray(o.get(POINT, "P"))[:, 0].max()) > 4.3, (area(o), ring_area(Pc[c.prim_points(0)]) - 2.0))
H = poly([(0, 0), (3, 0), (3, 1), (5, 1), (5, 0), (8, 0), (8, 3), (5, 3), (5, 2), (3, 2), (3, 3), (0, 3)])
check("dumbbell (two 3×3 with a corridor of width 1 between, area 20), offset 0.4: the corridor stays open, leaving a 0.2-wide gap inside",
      close(area(S(H, 0.4, output_outside=False)), 20 - (2 * 2.2 ** 2 + 2.8 * 0.2)), area(S(H, 0.4, output_outside=False)))
check("  offset 0.51 / 0.6: the corridor gets eaten (split event), the region splits in two -- the offset lines are then open chains that don't close, "
      "and some points land exactly on other edges (constrained edges can't be inserted); the area is still right: 20 − 2·(3 − 2d)²",
      close(area(S(H, 0.51, output_outside=False)), 20 - 2 * 1.98 ** 2, 1e-4)
      and close(area(S(H, 0.6, output_outside=False)), 20 - 2 * 1.8 ** 2, 1e-4),
      (area(S(H, 0.51, output_outside=False)), area(S(H, 0.6, output_outside=False))))
check("  and no overlap, nothing filled in between the two squares", abs(covered(S(H, 0.6, output_outside=False), -0.5, 8.5, 600) - (20 - 6.48)) < 0.05,
      covered(S(H, 0.6, output_outside=False), -0.5, 8.5, 600))
line = poly([(0, 0), (10, 0)], closed=False)
o = S(line, 1.0)
check("a segment of length 10, offset 1: square caps, one 12 × 2 = 24 road surface; all counted as outside (no bounded face)",
      close(area(o), 24.0) and close(area(S(line, 1.0, output_inside=False)), 24.0)
      and S(line, 1.0, output_outside=False).nprims == 0, area(o))
check("  Omit End Caps has no effect on surfaces (surfaces need a closed boundary)", close(area(S(line, 1.0, split_to_omit_caps=True)), 24.0))
cross = Geometry.from_mesh(np.array([[-3, 0, 0], [3, 0, 0], [0, 0, -3], [0, 0, 3]], np.float32),
                           [np.array([0, 1]), np.array([2, 3])], closed=False)
check("crossroads (two crossing lines, width 1): area = two 7×1 − the overlapping 1×1 = 13, no overlap",
      close(area(S(cross, 0.5)), 13.0) and abs(covered(S(cross, 0.5), -4, 4) - 13.0) < 0.05, area(S(cross, 0.5)))
ring = Geometry.from_mesh(
    np.array([[0, 0, 0], [6, 0, 0], [6, 0, 6], [0, 0, 6], [2, 0, 2], [4, 0, 2], [4, 0, 4], [2, 0, 4]], np.float32),
    [np.arange(4), np.arange(4, 8)], closed=True)
o = S(ring, 0.5, create_groups=True)
gi = o.groups[PRIM]["inside"]
Pm = np.asarray(o.get(POINT, "P"))[o.triangles()].mean(1)
in_hole = (Pm[:, 0] > 2) & (Pm[:, 0] < 4) & (Pm[:, 2] > 2) & (Pm[:, 2] < 4)
in_ring = (Pm[:, 0] > 0) & (Pm[:, 0] < 6) & (Pm[:, 2] > 0) & (Pm[:, 2] < 6) & ~in_hole
P_, T_ = tris(o)
ta = 0.5 * np.linalg.norm(np.cross(P_[T_[:, 1]] - P_[T_[:, 0]], P_[T_[:, 2]] - P_[T_[:, 0]]), axis=1)
check("square ring (6×6 around 2×2): ring = outer loop shrunk (36 − 25) + small square grown (9 − 4) = 16; inside the small square = 4 − 1 = 3; outermost = 49 − 36 = 13",
      close(ta[in_ring].sum(), 16.0) and close(ta[in_hole].sum(), 3.0) and close(ta[~in_ring & ~in_hole].sum(), 13.0),
      (ta[in_ring].sum(), ta[in_hole].sum(), ta[~in_ring & ~in_hole].sum()))
check("  inside group = those in the two bounded faces (ring, small square), the outermost band is outside", (gi == (in_ring | in_hole)).all())
ow = S(ring, 0.5, create_groups=True, side_determination="winding_number")
gw = ow.groups[PRIM]["inside"]
Pw = np.asarray(ow.get(POINT, "P"))[ow.triangles()].mean(1)
wn_in = (Pw[:, 0] > 0) & (Pw[:, 0] < 6) & (Pw[:, 2] > 0) & (Pw[:, 2] < 6)
check("  Winding Number mode: same geometry, inside judged by the winding number of the input curves (both loops same direction -> everything in the 6×6 is inside, including the small square)",
      close(area(ow), area(o)) and (gw == wn_in).all() and gw[(Pw[:, 0] > 2) & (Pw[:, 0] < 4) & (Pw[:, 2] > 2) & (Pw[:, 2] < 4)].all())
gr = build.grid(10, 10, 8, 8)
o = S(gr, 0.2)
cell = 10 / 7
exp = 49 * (cell ** 2 - (cell - 0.4) ** 2) + (10.4 ** 2 - 100)
check(f"7×7 road grid (49 blocks): one band per block + one ring outside = {exp:.3f}", close(area(o), exp, 1e-4), area(o))
Pg = np.asarray(o.get(POINT, "P"), np.float64)[o.triangles()].mean(1)
gx = np.abs(((Pg[:, 0] + 5) / cell + 0.5) % 1 - 0.5) * cell
gz = np.abs(((Pg[:, 2] + 5) / cell + 0.5) % 1 - 0.5) * cell
check("  every triangle's centroid is less than 0.2 from the nearest grid line (all on the road, nothing filled into the blocks)",
      float(np.minimum(gx, gz).max()) < 0.2, float(np.minimum(gx, gz).max()))

sec("node, panel")
NODE = M["PCG_PolyExpand2D"]
spec = NODE.INPUT_TYPES()["required"]
check("Output dropdown: Offset Curves (default, old workflows unchanged), Offset Surfaces", list(spec["output"][0]) == ["offset_curves", "offset_surfaces"])
kw = {k: (v[0][0] if isinstance(v[0], (list, tuple)) else v[1].get("default")) for k, v in spec.items() if k != "geo"}
r = NODE().run(geo=sq, **{**kw, "output": "offset_surfaces", "offset": 0.2})
r = r["result"][0] if isinstance(r, dict) else r[0]
check("node cooks Offset Surfaces: triangles out, area 3.2", close(area(r), a_in + a_out) and r.prim_closed.all(), area(r))
r = NODE().run(geo=sq, **{**kw, "output": "offset_surfaces", "offset": 0.2, "keep_input_geometry": True})
r = r["result"][0] if isinstance(r, dict) else r[0]
check("  Keep Input Geometry: the input faces merged in front", r.nprims == 17 and r.prim_sizes()[0] == 4)
try:
    PE.polyexpand2d(sq, output="straight_skeleton")
    check("Output set to something else: a clear error", False)
except ValueError as e:
    check("Output set to something else: a clear error", "Straight Skeleton is not implemented" in str(e), e)
check("empty input / no prims: doesn't raise", S(Geometry(), 0.2).nprims == 0 and PE.polyexpand2d(None, output="offset_surfaces") .nprims == 0)
check("offset = 0: empty (unchanged with Keep Input)", S(sq, 0.0).nprims == 0 and S(sq, 0.0, keep_input=True).nprims == 1)
pm = str(panel_model("PCG_PolyExpand2D", NODE.INPUT_TYPES()))
check("panel: dropdown has Offset Surfaces; Omit End Caps only shows in Offset Curves mode",
      "Offset Surfaces" in pm and "output != offset_curves" in pm)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
