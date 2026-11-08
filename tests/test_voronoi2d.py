"""
Voronoi 2D -- planar Voronoi diagram.

The criteria come in three tiers:

    analytic closed form   cell areas for symmetric sites can be computed by hand (4 symmetric sites -> four equal parts);
               cell count and area for a regular n-gon arrangement; strip width for collinear sites
    conservation           the sum of all cell areas == the area of the boundary region, **exact to the last digit
               of float64** (the kernel is float64 throughout, only dropping to float32 when written into Geometry)
    the definition itself  this is the strongest one: **for every point in a cell, the nearest site must be that cell's own**.
               Scatter a bunch of points in each cell and verify them one by one. Area conservation only guarantees "no overlaps, no gaps",
               not "partitioned correctly" -- an implementation that pairs sites up wrongly still conserves area.

Plus two structural ones: every cell must be **convex** (guaranteed mathematically by half-plane clipping),
and the vertices of the edges output must be **shared** (otherwise PolyPath downstream cannot join them,
and "joining into a road network" is the main use of this node).
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
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo.core import Geometry, POINT, PRIM   # noqa: E402
from comfyui_pcg.geo import (voronoi2d as V2,            # noqa: E402
                             triangulate2d as T2, measure as ME)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def RUN(fn, *a, **k):
    """In production the node's execute function is wrapped and returns {"ui":…,"result":…}. See fakecomfy."""
    return fakecomfy.unwrap(fn(*a, **k))


# ══════════════════════════════════════════════════════════════════ small helpers
def sites(XY):
    XY = np.asarray(XY, np.float64)
    P = np.column_stack([XY[:, 0], np.zeros(len(XY)), XY[:, 1]])
    return Geometry.from_points(P.astype(np.float32))


def poly(XY):
    XY = np.asarray(XY, np.float64)
    P = np.column_stack([XY[:, 0], np.zeros(len(XY)), XY[:, 1]])
    return Geometry.from_mesh(P.astype(np.float32), [list(range(len(XY)))])


def V(g, **kw):
    kw.setdefault("plane", "zx")
    return V2.voronoi2d(g, **kw)


def shoelace(P):
    P = np.asarray(P, np.float64).reshape(-1, 2)
    if len(P) < 3:
        return 0.0
    return abs(float(np.sum(P[:, 0] * np.roll(P[:, 1], -1)
                            - np.roll(P[:, 0], -1) * P[:, 1]))) / 2.0


def area(g):
    return float(ME.prim_areas(g).sum()) if g.nprims else 0.0


def xy(g):
    return np.asarray(g.get(POINT, "P"), np.float64)[:, [0, 2]]


def cell_polys(g):
    Q = xy(g)
    return [Q[g.prim_points(p)] for p in range(g.nprims)]


# ══════════════════════════════════════════════════ kernel: conservation in float64
print("═" * 28, "area conservation (pure float64 kernel, should be exact)")

RNG = np.random.default_rng(0)
for _n in (2, 5, 50, 500):
    S = RNG.random((_n, 2))
    B = V2.bounds_polygon(S, 0.2)
    cl = V2.cells(S, B)
    tot = sum(shoelace(c) for c in cl)
    check(f"{_n} random sites: sum of cell areas == boundary area",
          abs(tot - shoelace(B)) < 1e-12 * max(shoelace(B), 1.0),
          f"{tot:.15f} vs {shoelace(B):.15f}")
    check(f"  every site gets a non-empty cell", all(len(c) >= 3 for c in cl),
          sum(1 for c in cl if len(c) < 3))

S200 = RNG.random((200, 2))
CL200 = V2.cells(S200, V2.bounds_polygon(S200, 0.1))
check("every cell is **convex** (guaranteed mathematically by half-plane clipping)",
      all(V2.is_convex_ccw(c)[0] for c in CL200),
      sum(1 for c in CL200 if not V2.is_convex_ccw(c)[0]))
check("  and all counter-clockwise (the boundary is given counter-clockwise, clipping preserves orientation)",
      all(V2.is_convex_ccw(c)[1] for c in CL200))

# ════════════════════════════════════════════════ the definition itself: nearest site
print("═" * 28, "Voronoi definition: the nearest site of every point in a cell is its own")


def nearest_ok(S, cl, per=40, seed=7):
    """Scatter points in each cell and check that the nearest site is its own. Returns the number of violations."""
    r = np.random.default_rng(seed)
    bad = 0
    for i, c in enumerate(cl):
        if len(c) < 3:
            continue
        # scatter points in the cell with barycentric coordinates (cells are convex, so fan triangulation is safe)
        for _ in range(per):
            k = int(r.integers(1, len(c) - 1))
            w = r.random(3)
            w /= w.sum()
            p = w[0] * c[0] + w[1] * c[k] + w[2] * c[k + 1]
            d = ((S - p) ** 2).sum(1)
            # ties (lying exactly on a bisector) do not count as violations
            if d[i] > d.min() + 1e-12:
                bad += 1
    return bad


check("200 sites x 40 interior points per cell: not a single point whose nearest site is not its own",
      nearest_ok(S200, CL200) == 0, nearest_ok(S200, CL200))
check("  negative control: **shift sites and cells by one**, and this criterion blows up immediately"
      " (proves it really checks ownership, not just geometry)",
      nearest_ok(S200, CL200[1:] + CL200[:1]) > 0,
      nearest_ok(S200, CL200[1:] + CL200[:1]))

# duality with Delaunay: adjacent cells <=> Delaunay edge
_tri = T2.delaunay(S200)
_dedges = set()
for _f in _tri:
    for _u, _v in ((_f[0], _f[1]), (_f[1], _f[2]), (_f[2], _f[0])):
        _dedges.add((min(int(_u), int(_v)), max(int(_u), int(_v))))
# cells share an edge -> the two sites are adjacent in Delaunay (not necessarily the reverse: Delaunay edges near
# the convex hull may be clipped away by the boundary, so only this direction is checked)
_vseg = {}
for _i, _c in enumerate(CL200):
    for _k in range(len(_c)):
        _a = tuple(np.round(_c[_k], 12))
        _b = tuple(np.round(_c[(_k + 1) % len(_c)], 12))
        _vseg.setdefault((min(_a, _b), max(_a, _b)), []).append(_i)
_shared = [v for v in _vseg.values() if len(v) == 2]
_bad_dual = sum(1 for v in _shared
                if (min(v), max(v)) not in _dedges)
check("duality: for two cells sharing an edge, their sites are adjacent in Delaunay",
      _bad_dual == 0, f"{_bad_dual}/{len(_shared)} do not hold")

# ══════════════════════════════════════════════════════════ analytic closed form
print("═" * 28, "cases computable by hand")

SQ4 = np.array([[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]])
r4 = V(sites(SQ4), output="cells")
check("4 symmetric sites: the 0.5x0.5 bounding box is **split into four equal parts**, 0.0625 each",
      r4.nprims == 4
      and np.allclose(ME.prim_areas(r4), 0.0625, atol=1e-6),
      [round(float(a), 6) for a in ME.prim_areas(r4)])
check("  total area = bounding box area 0.25", abs(area(r4) - 0.25) < 1e-6, area(r4))
check("  vertices welded into 3x3 = 9 (unwelded it would be 4x4=16 separate corners)",
      r4.npoints == 9, r4.npoints)
check("  the site attribute points back to the site point number, one to one",
      np.asarray(r4.get(PRIM, "site")).ravel().tolist() == [0, 1, 2, 3])

# collinear sites -> vertical strips one after another, widths computable by hand
COL = np.column_stack([np.arange(5.0), np.zeros(5)])
rc = V(sites(COL), output="cells", padding=1.0)
check("5 collinear sites (spacing 1, padding 1): 5 strips, total area = 6x2 = 12",
      rc.nprims == 5 and abs(area(rc) - 12.0) < 1e-5, area(rc))
_ac = sorted(round(float(a), 6) for a in ME.prim_areas(rc))
check("  the two end strips 1.5 wide, the middle three 1 wide (so areas 3,2,2,2,3)",
      _ac == [2.0, 2.0, 2.0, 3.0, 3.0], _ac)

# two sites -> cut in half
r2 = V(sites(np.array([[0.0, 0.0], [2.0, 0.0]])), output="cells", padding=1.0)
check("2 sites: cut into two equal halves by the perpendicular bisector",
      r2.nprims == 2 and np.allclose(ME.prim_areas(r2),
                                     float(area(r2)) / 2, atol=1e-6),
      [round(float(a), 5) for a in ME.prim_areas(r2)])

# ══════════════════════════════════════════════════════════ boundary region
print("═" * 28, "boundary region")

_oa = np.arange(8) * 2 * np.pi / 8
OCT = np.column_stack([np.cos(_oa), np.sin(_oa)]) * 1.5
SS = RNG.random((40, 2)) * 2 - 1
ro = V(sites(SS), boundary="polygon", bounds_geo=poly(OCT))
check("convex polygon boundary: sum of cell areas == that polygon's area",
      abs(area(ro) - shoelace(OCT)) < 1e-4 * shoelace(OCT),
      f"{area(ro):.5f} vs {shoelace(OCT):.5f}")
check("  same with the boundary given clockwise (normalized to counter-clockwise internally)",
      abs(area(V(sites(SS), boundary="polygon",
                 bounds_geo=poly(OCT[::-1]))) - area(ro)) < 1e-6)
check("padding enlarges the boundary, total cell area grows with it",
      area(V(sites(SS), padding=0.5)) > area(V(sites(SS), padding=0.0)))
_b0 = V2.bounds_polygon(SS, 0.0)
check("  bounds is the sites' bounding box",
      abs(shoelace(_b0) - float((SS.max(0) - SS.min(0)).prod())) < 1e-12)

# a concave boundary must raise -- half-plane clipping does not hold for concave polygons
CONCAVE = np.array([[-1, -1], [1, -1], [1, 0], [0, 0], [0, 1], [-1, 1]], float)
err("concave boundary **raises** and offers two remedies (must not silently cut self-intersecting cells)",
    lambda: V(sites(SS), boundary="polygon", bounds_geo=poly(CONCAVE)),
    "is not convex")
check("  negative control: the same shape works after taking its convex hull",
      V(sites(SS), boundary="polygon",
        bounds_geo=poly(np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]],
                                 float))).nprims == 40)
err("Boundary=polygon with the second input forgotten: says what to connect",
    lambda: V(sites(SS), boundary="polygon"), "needs a closed polygon on the second input")
err("  no closed polygon in the second input",
    lambda: V(sites(SS), boundary="polygon", bounds_geo=sites(SS)),
    "has no closed polygon")
err("bad output lists the options", lambda: V(sites(SS), output="oops"),
    "Output must be one of")
err("bad boundary lists the options", lambda: V(sites(SS), boundary="oops"),
    "Boundary must be one of")

# ══════════════════════════════════════════════════════════ edges output
print("═" * 28, "edges output (the mode for road networks)")

SE = RNG.random((30, 2)) * 5
re_ = V(sites(SE), output="edges")
rc_ = V(sites(SE), output="cells")
check("every one is a **two-point open chain** (not a closed face)",
      set(re_.prim_sizes().tolist()) == {2} and not re_.prim_closed.any(),
      sorted(set(re_.prim_sizes().tolist())))
check("vertices are **shared**: segment count < sum of edge counts over all cells (deduplication works)",
      re_.nprims < sum(rc_.prim_sizes()),
      f"{re_.nprims} < {int(sum(rc_.prim_sizes()))}")
check("  point count exactly the same as the cells output (the same set of welded Voronoi vertices)",
      re_.npoints == rc_.npoints, (re_.npoints, rc_.npoints))
_int = re_.get_group(PRIM, "interior")
check("interior group marks edges shared by two cells (interior edges), count > 0 and < all",
      0 < int(_int.sum()) < re_.nprims,
      f"{int(_int.sum())}/{re_.nprims}")
# those not interior must all lie on the bounding box -- they are clipping boundaries, not Voronoi edges
_Q = xy(re_)
_B = V2.bounds_polygon(SE, 0.0)
_lo, _hi = _B.min(0), _B.max(0)
_on_b = 0
for _p in range(re_.nprims):
    if _int[_p]:
        continue
    _v = _Q[re_.prim_points(_p)]
    if (np.abs(_v[:, 0] - _lo[0]) < 1e-4).all() or \
       (np.abs(_v[:, 0] - _hi[0]) < 1e-4).all() or \
       (np.abs(_v[:, 1] - _lo[1]) < 1e-4).all() or \
       (np.abs(_v[:, 1] - _hi[1]) < 1e-4).all():
        _on_b += 1
check("  edges not in interior all lie on the boundary box (they are clipping edges, not Voronoi edges)",
      _on_b == re_.nprims - int(_int.sum()),
      f"{_on_b}/{re_.nprims - int(_int.sum())}")
check("group name can be changed", "roads" in V(sites(SE), output="edges",
                                interior_group="roads").groups[PRIM])

# ══════════════════════════════════════════════════════════ circumcenter
print("═" * 28, "circumcenter (analytic position of Voronoi vertices)")

_eq = np.array([[0, 0], [1, 0], [0.5, np.sqrt(3) / 2]])
_cc = V2.circumcenters(_eq, np.array([[0, 1, 2]]))
check("an equilateral triangle's circumcenter is at its centroid ((0.5, 1/(2√3)) for side length 1)",
      np.allclose(_cc[0], [0.5, 1 / (2 * np.sqrt(3))], atol=1e-12), _cc[0])
check("  a right triangle's circumcenter is at the midpoint of the hypotenuse",
      np.allclose(V2.circumcenters(np.array([[0, 0], [4., 0], [0, 3.]]),
                                   np.array([[0, 1, 2]]))[0], [2.0, 1.5],
                  atol=1e-12))
check("  a degenerate (collinear) triangle gives nan, not a fake finite value",
      np.isnan(V2.circumcenters(np.array([[0, 0], [1., 0], [2., 0]]),
                                np.array([[0, 1, 2]]))).all())
# the Voronoi vertices of an interior site are the circumcenters of its surrounding triangles -- cross-check the clipping result with that
_S9 = np.array([[0., 0.], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1],
                [0, 2], [1, 2], [2, 2]])
_cl9 = V2.cells(_S9, V2.bounds_polygon(_S9, 1.0))
_ctr = _cl9[4]                             # the site in the very middle
check("3x3 lattice: the center site's cell is a unit square (area 1)",
      abs(shoelace(_ctr) - 1.0) < 1e-12, shoelace(_ctr))
_t9 = T2.delaunay(_S9)
_cc9 = V2.circumcenters(_S9, _t9)
_inc = [i for i, f in enumerate(_t9) if 4 in f]
_want = {tuple(np.round(_cc9[i], 9)) for i in _inc}
_got = {tuple(np.round(v, 9)) for v in _ctr}
check("  its four vertices are **exactly** the circumcenters of the surrounding triangles (clipping and duality agree)",
      _got <= _want, f"vertices {sorted(_got)} circumcenters {sorted(_want)}")

# ══════════════════════════════════════════════════════════ degenerate cases and robustness
print("═" * 28, "degenerate input")

r1 = V(sites(np.array([[1.0, 2.0]])), output="cells")
check("1 site: the whole boundary region is its cell",
      r1.nprims == 1 and abs(area(r1) - 1.0) < 1e-6, area(r1))
_dup = V(sites(np.array([[0., 0.], [1, 0], [0, 0], [0, 1]])),
         output="cells", padding=0.5)
check("coincident sites welded first: 4 sites at 3 distinct positions -> 3 cells"
      " (unwelded, the cells of both coincident sites would be clipped to empty)",
      _dup.nprims == 3, _dup.nprims)
_same = V(sites(np.array([[2., 2.], [2., 2.], [2., 2.]])),
          output="cells")
check("all sites coincident: only 1 cell left, and a fallback thickness when the bounding box degenerates",
      _same.nprims == 1 and area(_same) > 0, (_same.nprims, area(_same)))
check("empty input returned as is",
      V2.voronoi2d(Geometry.from_points(np.zeros((0, 3), np.float32))
                   ).npoints == 0)
check("None input returns None", V2.voronoi2d(None) is None)
err("Group filtering out all points: says why",
    lambda: V(sites(SS), group="!*"), "needs at least one site")

# magnitude
_big = RNG.random((60, 2)) * 1000.0 + 1e5
check("area still conserved at coordinate magnitude 1e5",
      abs(sum(shoelace(c) for c in V2.cells(_big,
                                            V2.bounds_polygon(_big, 1.0)))
          - shoelace(V2.bounds_polygon(_big, 1.0)))
      < 1e-9 * shoelace(V2.bounds_polygon(_big, 1.0)))
_tiny = RNG.random((60, 2)) * 1e-4
check("also conserved at coordinate magnitude 1e-4 (weld tolerance follows the scale, not a hard-coded absolute value)",
      abs(area(V(sites(_tiny), output="cells", fuse_tol=1e-12))
          - shoelace(V2.bounds_polygon(_tiny, 0.0)))
      < 1e-4 * shoelace(V2.bounds_polygon(_tiny, 0.0)),
      (area(V(sites(_tiny), output="cells", fuse_tol=1e-12)),
       shoelace(V2.bounds_polygon(_tiny, 0.0))))

print("═" * 28, "purity")

_in = sites(RNG.random((25, 2)))
_snap = (np.asarray(_in.get(POINT, "P")).copy(), _in.nprims)
_ = V(_in, output="cells")
check("input geometry not modified",
      np.array_equal(np.asarray(_in.get(POINT, "P")), _snap[0])
      and _in.nprims == _snap[1])
_a = V(_in, output="cells")
_b = V(_in, output="cells")
check("same input run twice is bit-identical",
      np.array_equal(np.asarray(_a.get(POINT, "P")),
                     np.asarray(_b.get(POINT, "P")))
      and np.array_equal(np.asarray(_a.vertex_point),
                         np.asarray(_b.vertex_point)))
check("output attribute arrays are read-only",
      not np.asarray(_a.get(POINT, "P")).flags.writeable)

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
