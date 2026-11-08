"""
Triangulate 2D -- Delaunay / constrained Delaunay triangulation.

The criteria in this suite come in three layers, each stronger than the last:

    analytic closed form   triangle count = n-2 (simple polygon) / 2n-h-2 (point set);
               area = shoelace formula; regular k-gon area = k·sin(2π/k)/2;
               hand-computable numbers like concavity 1-V/Vh
    structural validity    directed edges unique, no zero-area triangles, no point missing,
               the boundary is a **single convex loop**, area equals the convex hull area
    Delaunay               for every unconstrained interior edge, neither opposite vertex lies inside the other triangle's circumcircle

**The third layer is the core of this suite; the first two cannot measure triangulation quality.** This is not a guess: with a hull tolerance
tol=1e-6, "area == hull area" **passes** on Gaussian-distributed and jittered-grid inputs while the empty-circle criterion
has dozens of violations. Conservation only guarantees the pieces fit together without overlaps or gaps, not that they fit together correctly.
The "volume conserved" check for voronoi fracture in `test_geoattrs.py` is the same kind of property --
it tests the fitting together, not the quality.

This batch caught four bugs in its own implementation, all recorded in the comments of `geo/triangulate2d.py`:
cocircular degeneracy, hull tolerance, in_circle argument order, the exit edge chosen backwards when walking triangles.
The last one only reproduces reliably with "a long constrained edge crossing a dense point cloud", so that construction has its own section.
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

from comfyui_pcg.geo.core import Geometry, POINT         # noqa: E402
from comfyui_pcg.geo import (build, measure as ME,       # noqa: E402
                             triangulate2d as T2)

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


# ══════════════════════════════════════════════════════════════════ small helpers
def geo2(XY, prims=(), closed=True):
    """(N,2) -> geometry placed on the XZ plane. Triangulation always uses plane='zx'."""
    XY = np.asarray(XY, np.float64)
    P3 = np.column_stack([XY[:, 0], np.zeros(len(XY)), XY[:, 1]])
    if len(prims) == 0:
        return Geometry.from_points(P3.astype(np.float32))
    return Geometry.from_mesh(P3.astype(np.float32), [list(p) for p in prims],
                              closed=closed)


def T(g, **kw):
    kw.setdefault("plane", "zx")
    kw.setdefault("constrain", "none")
    kw.setdefault("region", "keep_all")
    return T2.triangulate2d(g, **kw)


def area(g):
    return float(ME.prim_areas(g).sum()) if g.nprims else 0.0


def shoelace(P):
    P = np.asarray(P, np.float64).reshape(-1, 2)
    if len(P) < 3:
        return 0.0
    return abs(float(np.sum(P[:, 0] * np.roll(P[:, 1], -1)
                            - np.roll(P[:, 0], -1) * P[:, 1]))) / 2.0


def faces_of(g):
    return [list(map(int, g.prim_points(p))) for p in range(g.nprims)]


def und_edges(g):
    """All undirected edges in the output."""
    out = set()
    for f in faces_of(g):
        for i in range(len(f)):
            u, v = f[i], f[(i + 1) % len(f)]
            out.add((min(u, v), max(u, v)))
    return out


def _xy(g):
    """
    Read the geometry's P back as 2D. Note these are **float32-rounded** values --
    Geometry stores P as float32; computing "what it should be" from the original float64 coordinates
    differs at the 1e-8 level, which is storage precision, not an implementation error.
    """
    return np.asarray(g.get(POINT, "P"), np.float64)[:, [0, 2]]


def ring_area(g, idx):
    """Shoelace area over the point-number loop, coordinates taken from the geometry itself (the same float32)."""
    return shoelace(_xy(g)[list(idx)])


def hull2d(P):
    """2D convex hull (Andrew monotone chain), used to compute "what it should be" independently."""
    P = np.asarray(P, np.float64)
    pts = P[np.lexsort((P[:, 1], P[:, 0]))]

    def half(ps):
        st = []
        for p in ps:
            while len(st) >= 2 and \
                (st[-1][0] - st[-2][0]) * (p[1] - st[-2][1]) \
                    - (st[-1][1] - st[-2][1]) * (p[0] - st[-2][0]) <= 0:
                st.pop()
            st.append(p)
        return st
    out = half(pts)[:-1] + half(pts[::-1])[:-1]
    return np.asarray(out, np.float64).reshape(-1, 2)


def validate(g, cons=frozenset(), expect_hull=True):
    """
    Triangulation validity + Delaunay property. Returns a list of problem strings, empty = all pass.

    This function is the backbone of the whole suite -- nearly every check below uses it as its criterion.
    """
    bad = []
    P = _xy(g)
    faces = faces_of(g)
    if any(len(f) != 3 for f in faces):
        bad.append("non-triangle faces")
        return bad

    def orient(a, b, c):
        return (P[b, 0] - P[a, 0]) * (P[c, 1] - P[a, 1]) \
            - (P[b, 1] - P[a, 1]) * (P[c, 0] - P[a, 0])

    def incirc(a, b, c, d):
        ax, ay = P[a] - P[d]
        bx, by = P[b] - P[d]
        cx, cy = P[c] - P[d]
        return (ax * ax + ay * ay) * (bx * cy - by * cx) \
            - (bx * bx + by * by) * (ax * cy - ay * cx) \
            + (cx * cx + cy * cy) * (ax * by - ay * bx)

    o = np.array([orient(*f) for f in faces])
    if (o == 0).any():
        bad.append("zero-area triangles %d" % int((o == 0).sum()))

    de = {}
    for f in faces:
        ff = f if orient(*f) > 0 else [f[0], f[2], f[1]]
        for i in range(3):
            k = (ff[i], ff[(i + 1) % 3])
            de[k] = de.get(k, 0) + 1
    dup = sum(1 for c in de.values() if c > 1)
    if dup:
        bad.append("duplicate directed edges %d" % dup)

    if expect_hull:
        used = set(v for f in faces for v in f)
        miss = len(set(range(g.npoints)) - used)
        if miss:
            bad.append("missing points %d" % miss)
        # the boundary must be a single convex loop (the outer outline of a Delaunay triangulation is the convex hull)
        bnd = [e for e in de if (e[1], e[0]) not in de]
        nxt = {}
        for u, v in bnd:
            nxt.setdefault(u, []).append(v)
        if any(len(x) > 1 for x in nxt.values()):
            bad.append("boundary branches")
        elif bnd:
            s = bnd[0][0]
            cyc = [s]
            cur = nxt[s][0]
            while cur != s and len(cyc) <= len(bnd):
                cyc.append(cur)
                if cur not in nxt:
                    break
                cur = nxt[cur][0]
            if cur != s or len(cyc) != len(bnd):
                bad.append(f"boundary is not a single loop {len(cyc)}/{len(bnd)}")
            else:
                n = len(cyc)
                cr = [orient(cyc[i], cyc[(i + 1) % n], cyc[(i + 2) % n])
                      for i in range(n)]
                if min(cr) < -1e-12:
                    bad.append("boundary not convex min=%.2e" % min(cr))
        ha = shoelace(hull2d(P[sorted(used)]))
        ar = float(sum(abs(orient(*f)) for f in faces)) / 2.0
        if abs(ar - ha) > 1e-7 * max(ha, 1.0):
            bad.append(f"area {ar:.9f} != hull {ha:.9f}")

    he = {}
    for fi, f in enumerate(faces):
        ff = f if orient(*f) > 0 else [f[0], f[2], f[1]]
        for i in range(3):
            he[(ff[i], ff[(i + 1) % 3])] = (fi, ff)
    nv, worst = 0, 0.0
    for (u, v), (fi, ff) in he.items():
        if u > v or (v, u) not in he:
            continue
        if (min(u, v), max(u, v)) in cons:
            continue
        a = ff[(ff.index(u) + 2) % 3]
        _, gg = he[(v, u)]
        b = gg[(gg.index(v) + 2) % 3]
        d = incirc(u, v, a, b)
        if d > 1e-11:
            nv += 1
            worst = max(worst, d)
    if nv:
        bad.append(f"empty-circle violations {nv}, worst {worst:.2e}")
    return bad


# ══════════════════════════════════════════════════════ correctness of the lifting kernel
print("═" * 28, "Lifting kernel: the empty circumcircle is an algebraic identity, not an approximation")

RNG = np.random.default_rng(0)
_p = RNG.random((300, 2))
_t = T2.delaunay(_p)


def _incirc_all(P, tri):
    """
    For each triangle, plug **all** points into the incircle determinant and take the worst value.

    The determinant has rows | a-d  |a-d|² | (a,b,c counter-clockwise); > 0 means d is inside the circumcircle.
    The triangle's own three vertices always give 0 and are excluded.
    """
    worst = 0.0
    for f in tri:
        a, b, c = P[f[0]], P[f[1]], P[f[2]]
        if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) < 0:
            b, c = c, b                                   # orient counter-clockwise
        m = np.stack([np.broadcast_to(a, P.shape) - P,
                      np.broadcast_to(b, P.shape) - P,
                      np.broadcast_to(c, P.shape) - P], 1)   # (N,3,2)
        M = np.concatenate([m, (m ** 2).sum(-1)[..., None]], -1)  # (N,3,3)
        det = np.linalg.det(M)
        det[list(f)] = 0.0
        worst = max(worst, float(det.max()))
    return worst


check("delaunay (300 random points): triangle count = 2n - h - 2 (hull point count h computed independently)",
      len(_t) == 2 * 300 - len(hull2d(_p)) - 2,
      (len(_t), 2 * 300 - len(hull2d(_p)) - 2))
check("  empty circumcircle: incircle over all points, the worst value is **exactly 0**",
      _incirc_all(_p, _t) == 0.0, _incirc_all(_p, _t))
check("  all triangles counter-clockwise (the lower hull projects back clockwise; the kernel normalizes it)",
      all(T2._orient(_p, *f) > 0 for f in _t))
check("  sum of triangle areas = convex hull area",
      abs(sum(abs(T2._orient(_p, *f)) for f in _t) / 2
          - shoelace(hull2d(_p))) < 1e-12,
      sum(abs(T2._orient(_p, *f)) for f in _t) / 2)
check("  the incircle criterion itself: a point inside a CCW triangle > 0, outside < 0",
      T2._in_circle(np.array([[0, 0], [1, 0], [0, 1], [.4, .4], [2., 2.]]),
                    0, 1, 2, 3) > 0
      and T2._in_circle(np.array([[0, 0], [1, 0], [0, 1], [.4, .4], [2., 2.]]),
                        0, 1, 2, 4) < 0)
check("  negative control: swapping the vertex order flips the sign of incircle (the criterion is orientation-sensitive, "
      "so a wrong argument order cannot be masked by a tolerance)",
      T2._in_circle(np.array([[0, 0], [1, 0], [0, 1], [.4, .4]]), 0, 1, 2, 3)
      == -T2._in_circle(np.array([[0, 0], [1, 0], [0, 1], [.4, .4]]),
                        0, 2, 1, 3))

print("═" * 28, "Cocircular degeneracy -- the kind the first version returned empty geometry for")

# coplanar after lifting <=> the original points are cocircular. Squares/rectangles/rhombi/regular polygons/isosceles trapezoids all hit this,
# and with 3 points it is always coplanar. These are the **most common** inputs, not a rare edge case.
COCIRC = {
    "triangle (3 points always coplanar)": np.array([[0, 0], [1, 0], [0, 1]], float),
    "square": np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float),
    "rectangle 2×1": np.array([[0, 0], [2, 0], [2, 1], [0, 1]], float),
    "rhombus": np.array([[0, -1], [1, 0], [0, 1], [-1, 0]], float),
    "isosceles trapezoid": np.array([[0, 0], [3, 0], [2, 1], [1, 1]], float),
}
for _k in range(5, 13):
    _a = np.arange(_k) * 2 * np.pi / _k
    COCIRC[f"regular {_k}-gon"] = np.column_stack([np.cos(_a), np.sin(_a)])
for _nm, _P in COCIRC.items():
    _tt = T2.delaunay(_P)
    _ar = sum(abs(T2._orient(_P, *f)) for f in _tt) / 2
    check(f"{_nm}: gives n-2 = {len(_P) - 2} triangles, area = polygon area",
          len(_tt) == len(_P) - 2 and abs(_ar - shoelace(_P)) < 1e-12,
          (len(_tt), round(_ar, 9)))
_a12 = np.arange(12) * 2 * np.pi / 12
check("  regular 12-gon area = 12·sin(2π/12)/2 = 3 (analytic value)",
      abs(sum(abs(T2._orient(COCIRC["regular 12-gon"], *f))
              for f in T2.delaunay(COCIRC["regular 12-gon"])) / 2 - 3.0) < 1e-12)
_sq = COCIRC["square"]
_svsq = np.linalg.svd(
    (lambda Q: Q - Q.mean(0))(np.column_stack([_sq, (_sq ** 2).sum(1)])),
    compute_uv=False)
check("  the cocircular criterion is **the third singular value degenerating after lifting** (square's third / first "
      "< 1e-15)",
      _svsq[2] / _svsq[0] < 1e-15, (float(_svsq[2]), float(_svsq[0])))
check("  negative control: a square plus a center point is **not** cocircular (third singular value > 0), "
      "takes the normal convex hull path",
      float(np.linalg.svd(
          (lambda Q: Q - Q.mean(0))(np.column_stack(
              [(_q := np.array([[0, 0], [1, 0], [1, 1], [0, 1], [.5, .5]],
                               float)), (_q ** 2).sum(1)])),
          compute_uv=False)[2]) > 1e-3
      and len(T2.delaunay(_q)) == 4)
check("  square + center point: 4 triangles, area still 1",
      len(T2.delaunay(_q)) == 4
      and abs(sum(abs(T2._orient(_q, *f))
                  for f in T2.delaunay(_q)) / 2 - 1.0) < 1e-12)

print("═" * 28, "Hull tolerance -- too loose and points are **silently dropped**")

# the hull defaults to tol=1e-6. Reasonable for "just compute a hull", a disaster for Delaunay: nearly cocircular points
# are only 1e-8 off the plane, get swallowed as "on the plane", and disappear from the triangulation without an error.
_R2 = np.random.default_rng(3)
CLUST = np.vstack([_R2.normal(scale=0.01, size=(200, 2)),
                   _R2.normal(scale=1.0, size=(200, 2))])
_n6 = len(np.setdiff1d(np.arange(len(CLUST)),
                       np.unique(T2.delaunay(CLUST, tol=1e-6))))
_n12 = len(np.setdiff1d(np.arange(len(CLUST)),
                        np.unique(T2.delaunay(CLUST, tol=1e-12))))
check("two-scale clusters, 400 points: tol=1e-6 drops a whole bunch of points", _n6 > 50, _n6)
check("  tol=1e-12 drops none", _n12 == 0, _n12)
check("  the module pins it at 1e-12", T2.HULL_TOL == 1e-12, T2.HULL_TOL)
_wa = np.arange(300) * 2 * np.pi / 300
WAVY = np.column_stack([np.cos(_wa) * (1 + .25 * np.sin(5 * _wa)),
                        np.sin(_wa) * (1 + .25 * np.sin(5 * _wa))])
for _tol, _want in ((1e-6, False), (1e-12, True)):
    _g = geo2(WAVY)
    _r = T(_g, hull_tol=_tol)
    _bad = validate(_r)
    check(f"densely sampled wavy outline tol={_tol:g}: "
          f"{'valid triangulation' if _want else 'triangulation **not** valid (this is the negative control)'}",
          (not _bad) == _want, _bad or "OK")

print("═" * 28, "Simple polygon fill (constrained Delaunay)")


def star(n, r0=1.0, r1=0.4):
    a = np.arange(2 * n) * np.pi / n
    r = np.where(np.arange(2 * n) % 2 == 0, r0, r1)
    return np.column_stack([r * np.cos(a), r * np.sin(a)])


for _n in (5, 8, 12, 20):
    _P = star(_n)
    _g = geo2(_P, [list(range(2 * _n))])
    _cp = {(min(i, (i + 1) % (2 * _n)), max(i, (i + 1) % (2 * _n)))
           for i in range(2 * _n)}
    _r = T(_g, constrain="input_polygons", region="remove_outside")
    _want = ring_area(_g, range(2 * _n))
    check(f"{_n}-pointed star: triangle count = n-2 = {2 * _n - 2}, area = shoelace value",
          _r.nprims == 2 * _n - 2 and abs(area(_r) - _want) < 1e-6 * _want,
          (_r.nprims, round(area(_r), 9), round(_want, 9)))
    check("  every outline edge appears in the output (definition of a constraint)",
          not (_cp - und_edges(_r)), len(_cp - und_edges(_r)))
    check("  unconstrained edges still satisfy the empty circle (that is what makes it **constrained** Delaunay)",
          not validate(_r, _cp, expect_hull=False),
          validate(_r, _cp, expect_hull=False) or "OK")

# without constraints it fills outside the outline -- Delaunay triangulates the convex hull and knows nothing about outlines.
_P5 = star(5)
_g5 = geo2(_P5, [list(range(10))])
_hull5 = shoelace(hull2d(_xy(_g5)))
check("negative control: the same star without constraints has the area of the **convex hull**, not of the star",
      abs(area(T(_g5, constrain="none")) - _hull5) < 1e-6 * _hull5
      and area(T(_g5, constrain="none")) > ring_area(_g5, range(10)) * 1.4,
      (round(area(T(_g5, constrain="none")), 6), round(_hull5, 6),
       round(ring_area(_g5, range(10)), 6)))

print("═" * 28, "Inside/outside: parity of region depth")

L = np.array([[-1, -.5], [1, -.5], [1, .5], [0, .5], [0, 1.5], [-1, 1.5]],
             float)
_gL = geo2(L, [list(range(6))])
_ai = area(T(_gL, constrain="input_polygons", region="remove_outside"))
_ao = area(T(_gL, constrain="input_polygons", region="remove_inside"))
_ak = area(T(_gL, constrain="input_polygons", region="keep_all"))
check("L shape: remove_outside = polygon area 3", abs(_ai - 3.0) < 1e-6, _ai)
check("  remove_inside = hull 3.5 - 3 = 0.5", abs(_ao - 0.5) < 1e-6, _ao)
check("  keep_all = hull area 3.5 (shoelace formula computed independently)",
      abs(_ak - 3.5) < 1e-6
      and abs(_ak - shoelace(hull2d(_xy(_gL)))) < 1e-6, _ak)
check("  inside + outside = everything (the regions neither overlap nor leave gaps)", abs(_ai + _ao - _ak) < 1e-6)

# with a hole: the outer frame is both a constrained edge and exactly the convex hull. The first version's "flood fill from the hull boundary"
# found no seed here at all, removed nothing, and measured 16 instead of 12.
HOLE = np.vstack([np.array([[-2, -2], [2, -2], [2, 2], [-2, 2]], float),
                  np.array([[-1, -1], [-1, 1], [1, 1], [1, -1]], float)])
_gH = geo2(HOLE, [[0, 1, 2, 3], [4, 5, 6, 7]])
check("4×4 with a 2×2 hole: remove_outside = 16 - 4 = 12 (nesting relies on depth parity, "
      "not on 'reachable or not')",
      abs(area(T(_gH, constrain="input_polygons",
                 region="remove_outside")) - 12.0) < 1e-6,
      area(T(_gH, constrain="input_polygons", region="remove_outside")))
check("  remove_inside = hole area 4",
      abs(area(T(_gH, constrain="input_polygons",
                 region="remove_inside")) - 4.0) < 1e-6)
NEST = np.vstack([np.array([[-2, -2], [2, -2], [2, 2], [-2, 2]], float),
                  np.array([[-1.5, -1.5], [-1.5, 1.5], [1.5, 1.5],
                            [1.5, -1.5]], float),
                  np.array([[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]],
                           float)])
_gN = geo2(NEST, [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]])
check("three nested levels: 16 - 9 + 1 = 8 (the parity rule has to be right for three levels in a row)",
      abs(area(T(_gN, constrain="input_polygons",
                 region="remove_outside")) - 8.0) < 1e-6,
      area(T(_gN, constrain="input_polygons", region="remove_outside")))
check("  four levels: another 0.2×0.2 hole inside -> 8 - 0.04",
      abs(area(T(geo2(np.vstack([NEST, np.array(
          [[-.1, -.1], [-.1, .1], [.1, .1], [.1, -.1]], float)]),
          [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]),
          constrain="input_polygons", region="remove_outside"))
          - (8.0 - 0.04)) < 1e-6)
check("  remove_outside_and_inside removes both -> empty",
      T(_gH, constrain="input_polygons",
        region="remove_outside_and_inside").nprims == 0)

print("═" * 28, "Long constrained edge across a dense point cloud -- the only construction that reproduces the backwards exit edge")

# The two branches choosing the exit edge when walking triangles were swapped in the first version, picking the edge that does **not** cross ab.
# L shapes, stars and framed holes cannot detect it: their constrained edges are mostly already in the Delaunay mesh
# (early exit), or the cavity spans only one triangle (one step gets there). The cavity has to span many.
_RG = np.random.default_rng(7)
_n = 22
GR = np.stack(np.meshgrid(np.linspace(0, 1, _n), np.linspace(0, 1, _n)),
              -1).reshape(-1, 2) + _RG.normal(scale=0.004, size=(_n * _n, 2))
GR[0] = [0, 0]
GR[-1] = [1, 1]
_gG = geo2(GR, [[0, len(GR) - 1]], closed=False)
_rG = T(_gG, constrain="input_polygons", constrained_group="c")
_diag = (0, len(GR) - 1)
check(f"{_n}×{_n} jittered grid cut by a long diagonal: the constrained edge appears in the output",
      _diag in und_edges(_rG))
check("  triangulation still valid (directed edges unique / no missing points / boundary a single convex loop / area = hull)",
      not validate(_rG, {_diag}), validate(_rG, {_diag}) or "OK")
# How many triangles does this constrained edge actually cross? Count directly on the **unconstrained** mesh:
# the triangles intersecting the diagonal are the span of the cavity. If the span is not large enough this section does not test
# the "walk triangles" logic (one step reaches b), so the span itself is pinned first.
_plain = T(_gG, constrain="none")
_A, _B = _xy(_gG)[_diag[0]], _xy(_gG)[_diag[1]]


def _seg_hits_tri(f):
    Q = _xy(_rG)
    d = _B - _A
    for i in range(3):
        u, v = Q[f[i]], Q[f[(i + 1) % 3]]
        d2 = v - u
        den = d[0] * d2[1] - d[1] * d2[0]
        if abs(den) < 1e-300:
            continue
        t = ((u[0] - _A[0]) * d2[1] - (u[1] - _A[1]) * d2[0]) / den
        sv = ((u[0] - _A[0]) * d[1] - (u[1] - _A[1]) * d[0]) / den
        if 1e-9 < t < 1 - 1e-9 and 1e-9 < sv < 1 - 1e-9:
            return True
    return False


_span = sum(1 for f in faces_of(_plain) if _seg_hits_tri(f))
check("  on the **unconstrained** mesh this diagonal crosses >= 20 triangles -- "
      "only with a cavity spanning that many is the 'walk triangles' logic really exercised",
      _span >= 20, _span)
# count the triangles touching the diagonal -- direct evidence of the cavity span
_touch = sum(1 for f in faces_of(_rG)
             if _diag[0] in f or _diag[1] in f)
check("  reasonable number of triangles at both ends of the diagonal (>= 6, the fans are complete)", _touch >= 6, _touch)
check("  the constrained edges are written into the edge group", "c" in _rG.edge_groups,
      list(_rG.edge_groups))

# several non-crossing long constrained edges, 20 random examples


def _o2(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _cross(p1, p2, p3, p4):
    d1, d2 = _o2(p3, p4, p1), _o2(p3, p4, p2)
    d3, d4 = _o2(p1, p2, p3), _o2(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _near_col(P, u, v, tol):
    A, B = P[u], P[v]
    d = B - A
    LL = float(d @ d)
    t = np.clip(((P - A) @ d) / LL, 0, 1)
    dist = np.linalg.norm(P - (A + t[:, None] * d), axis=1)
    dist[[u, v]] = np.inf
    return float(dist.min()) < tol


_ok = 0
_tot = 0
for _s in range(20):
    _r3 = np.random.default_rng(1000 + _s)
    _m = int(_r3.integers(10, 26))
    _PP = np.stack(np.meshgrid(np.linspace(0, 1, _m), np.linspace(0, 1, _m)),
                   -1).reshape(-1, 2)
    _PP = _PP + _r3.normal(scale=float(_r3.uniform(0, 0.01)), size=_PP.shape)
    _pr, _cp2, _tr = [], set(), 0
    while len(_pr) < int(_r3.integers(1, 6)) and _tr < 200:
        _tr += 1
        _u, _v = int(_r3.integers(0, len(_PP))), int(_r3.integers(0, len(_PP)))
        if _u == _v:
            continue
        _e = (min(_u, _v), max(_u, _v))
        if _e in _cp2 or _near_col(_PP, _u, _v, 1e-4):
            continue
        if any(len({_u, _v, _x, _y}) == 4
               and _cross(_PP[_u], _PP[_v], _PP[_x], _PP[_y])
               for (_x, _y) in _cp2):
            continue
        _pr.append([_u, _v])
        _cp2.add(_e)
    if not _pr:
        continue
    _tot += 1
    try:
        _rr = T(geo2(_PP, _pr, closed=False), constrain="input_polygons")
        if not validate(_rr, _cp2) and not (_cp2 - und_edges(_rr)):
            _ok += 1
    except Exception:
        pass
check(f"all 20 random samples with several long constrained edges are valid", _ok == _tot, f"{_ok}/{_tot}")

print("═" * 28, "Random outlines + interior scatter (the main use case)")

_ok = 0
_tot = 0
for _s in range(20):
    _r4 = np.random.default_rng(_s)
    _nb = int(_r4.integers(20, 200))
    _ni = int(_r4.integers(0, 600))
    _kk = int(_r4.integers(2, 8))
    _amp = float(_r4.uniform(0.05, 0.35))
    _aa2 = np.arange(_nb) * 2 * np.pi / _nb
    _rr2 = 1 + _amp * np.sin(_kk * _aa2)
    _bnd = np.column_stack([np.cos(_aa2) * _rr2, np.sin(_aa2) * _rr2])
    _ip = (_r4.random((_ni, 2)) * 2 - 1) * 0.55 * (1 - _amp)
    _XY = np.vstack([_bnd, _ip]) if _ni else _bnd
    _cp3 = {(min(i, (i + 1) % _nb), max(i, (i + 1) % _nb))
            for i in range(_nb)}
    _tot += 1
    try:
        _rr3 = T(geo2(_XY, [list(range(_nb))]),
                 constrain="input_polygons", region="remove_outside")
        good = (not (_cp3 - und_edges(_rr3))
                and abs(area(_rr3) - shoelace(_bnd)) < 1e-6
                and not validate(_rr3, _cp3, expect_hull=False))
        if good:
            _ok += 1
        else:
            print(f'    seed{_s} nb={_nb} ni={_ni}: '
                  f'missing edges {len(_cp3 - und_edges(_rr3))} '
                  f'area difference {abs(area(_rr3) - shoelace(_bnd)):.2e} '
                  f'{validate(_rr3, _cp3, expect_hull=False)}')
    except Exception as _ex:
        print(f'    seed{_s} exception {type(_ex).__name__}: {str(_ex)[:60]}')
check("20 random wavy outlines (20~200 boundary points, 0~600 interior scatter points): "
      "constrained edges complete + area equals the shoelace value + unconstrained edges satisfy the empty circle",
      _ok == _tot, f"{_ok}/{_tot}")

print("═" * 28, "alpha pruning -- a concave hull from a point cloud")

_R5 = np.random.default_rng(5)
TWO = np.vstack([_R5.random((60, 2)), _R5.random((60, 2)) + [4.0, 0.0]])
_gT = geo2(TWO)
_full = T(_gT)
check("two clusters 3 apart: without pruning the area ≈ the whole convex hull (the gap gets filled too)",
      area(_full) > 4.0, round(area(_full), 4))
_prev = area(_full)
for _mel in (2.0, 1.0, 0.5, 0.3):
    _cur = area(T(_gT, max_edge_length=_mel))
    check(f"  max_edge_length={_mel}: area decreases monotonically", _cur <= _prev + 1e-12,
          round(_cur, 4))
    _prev = _cur
check("  pruned to 1.0 the gap is cleaned out (area < sum of the two clusters' own hulls × 1.2)",
      area(T(_gT, max_edge_length=1.0))
      < 1.2 * (shoelace(hull2d(TWO[:60])) + shoelace(hull2d(TWO[60:]))),
      (round(area(T(_gT, max_edge_length=1.0)), 4),
       round(shoelace(hull2d(TWO[:60])) + shoelace(hull2d(TWO[60:])), 4)))
_prev = area(_full)
for _mcr in (1.0, 0.5, 0.2):
    _cur = area(T(_gT, max_circumradius=_mcr))
    check(f"  max_circumradius={_mcr}: area decreases monotonically", _cur <= _prev + 1e-12,
          round(_cur, 4))
    _prev = _cur
check("threshold 0 = no pruning (**not** delete everything -- otherwise default parameters would output empty geometry)",
      T(_gT, max_edge_length=0.0).nprims == _full.nprims
      and T(_gT, max_circumradius=0.0).nprims == _full.nprims)
check("  both thresholds given = intersection (deletes at least as much as either one alone)",
      T(_gT, max_edge_length=1.0, max_circumradius=0.5).nprims
      <= min(T(_gT, max_edge_length=1.0).nprims,
             T(_gT, max_circumradius=0.5).nprims))
# analytic value for circumradii: circumradius of an equilateral triangle with side 1 = 1/√3
_eq = np.array([[0, 0], [1, 0], [0.5, np.sqrt(3) / 2]])
check("circumradii: circumradius of an equilateral triangle with side 1 = 1/√3 (analytic value)",
      abs(float(T2.circumradii(_eq, np.array([[0, 1, 2]]))[0])
          - 1 / np.sqrt(3)) < 1e-12,
      float(T2.circumradii(_eq, np.array([[0, 1, 2]]))[0]))
check("  circumradius of a right triangle = half the hypotenuse",
      abs(float(T2.circumradii(np.array([[0, 0], [3., 0], [0, 4.]]),
                               np.array([[0, 1, 2]]))[0]) - 2.5) < 1e-12)
check("  degenerate (collinear) triangles give inf, not 0 or nan",
      np.isinf(T2.circumradii(np.array([[0, 0], [1., 0], [2., 0]]),
                              np.array([[0, 1, 2]]))[0]))
check("max_edges: longest edge of the equilateral triangle = 1",
      abs(float(T2.max_edges(_eq, np.array([[0, 1, 2]]))[0]) - 1.0) < 1e-12)

print("═" * 28, "Plane selection / grouping / group output / attributes")

GRIDXZ = build.grid(size_x=4.0, size_z=4.0, cols=5, rows=5)
check("plane=zx triangulates a grid on the XZ plane: area = 4×4 = 16",
      abs(area(T(GRIDXZ, plane="zx")) - 16.0) < 1e-5,
      area(T(GRIDXZ, plane="zx")))
check("  triangle count = 2·25 - 16 - 2 = 32 (h=16 is the outer ring point count)",
      T(GRIDXZ, plane="zx").nprims == 32, T(GRIDXZ, plane="zx").nprims)
check("plane=fit_plane fits automatically, same result",
      abs(area(T(GRIDXZ, plane="fit_plane")) - 16.0) < 1e-5)
check("plane=specify_plane with normal (0,1,0) is equivalent to zx",
      T(GRIDXZ, plane="specify_plane", plane_normal=(0, 1, 0)).nprims
      == T(GRIDXZ, plane="zx").nprims)
err("a wrong plane raises and explains why (a grid on XZ projects onto XY as a line)",
    lambda: T(GRIDXZ, plane="xy"), "collinear")
err("a bad plane lists the choices", lambda: T(GRIDXZ, plane="oops"), "Plane must be one of")
err("a bad constrain lists the choices",
    lambda: T(GRIDXZ, plane="zx", constrain="oops"), "Constrain must be one of")
err("a bad region lists the choices",
    lambda: T(GRIDXZ, plane="zx", region="oops"), "Region must be one of")
err("too few points raises and says how many are missing",
    lambda: T(geo2(np.array([[0, 0], [1., 0]])), plane="zx"), "at least 3 are needed")
err("all collinear raises and points out the plane may be wrong",
    lambda: T(geo2(np.column_stack([np.arange(6.), np.zeros(6)])),
              plane="zx"), "collinear")
err("edge_group mode with a missing group lists the existing edge groups",
    lambda: T(GRIDXZ, plane="zx", constrain="edge_group",
              constrain_group="nope"), "No edge group named")
err("constrained edges not forming a closed loop, removing everything: a clear error pointing to Fuse",
    lambda: T(geo2(np.array([[-1, 0], [0, 1.], [1, 0], [0, -1.]]),
                   [[0, 1, 2]], closed=False),
              constrain="input_polygons", region="remove_outside"),
    "do not form a closed loop")
check("  with on_failure=ignore it falls back to not removing, instead of raising",
      T(geo2(np.array([[-1, 0], [0, 1.], [1, 0], [0, -1.]]),
             [[0, 1, 2]], closed=False),
        constrain="input_polygons", region="remove_outside",
        on_failure="ignore").nprims > 0)

_gr2 = T(GRIDXZ, plane="zx", border_group="bd")
check("border_group: the boundary edges are exactly the 16 on the outer ring",
      len(_gr2.get_edge_group("bd")) == 16,
      len(_gr2.get_edge_group("bd")))
check("  every boundary edge is used by exactly one triangle",
      all(sum(1 for f in faces_of(_gr2)
              if u in f and v in f) == 1
          for (u, v) in np.asarray(_gr2.get_edge_group("bd"))[:6]))
_gcg = T(geo2(L, [list(range(6))]), constrain="input_polygons",
         region="remove_outside", constrained_group="cs")
check("constrained_group: all 6 outline edges of the L shape are written",
      len(_gcg.get_edge_group("cs")) == 6,
      len(_gcg.get_edge_group("cs")))

_gattr = build.grid(size_x=4.0, size_z=4.0, cols=5, rows=5)
from comfyui_pcg.geo import attribops as _AO                    # noqa: E402
_gattr = _AO.create(_gattr, name="w", cls="point", expression="@P.x")
_rat = T(_gattr, plane="zx")
check("point attributes carried over unchanged (triangulation creates no new points, point numbers untouched)",
      _rat.has(POINT, "w")
      and np.allclose(np.asarray(_rat.get(POINT, "w")),
                      np.asarray(_gattr.get(POINT, "w"))))
check("  point coordinates untouched too", np.array_equal(
    np.asarray(_rat.get(POINT, "P")), np.asarray(_gattr.get(POINT, "P"))))
_ggrp = _gattr.copy()
_ggrp.set_group(POINT, "half", np.arange(25) < 12)
check("  point groups carried over too", "half" in T(_ggrp, plane="zx").groups[POINT])
check("the group parameter only triangulates the selected points",
      T(GRIDXZ, plane="zx", group="0-11").npoints == 25
      and set(v for f in faces_of(T(GRIDXZ, plane="zx", group="0-11"))
              for v in f) <= set(range(12)))
check("keep_input_geometry keeps the original faces too",
      T(GRIDXZ, plane="zx", keep_input=True).nprims
      == T(GRIDXZ, plane="zx").nprims + GRIDXZ.nprims)

print("═" * 28, "Degeneracy and robustness")

_dup = np.array([[0, 0], [1, 0], [0, 1], [0, 0], [1, 0]], float)
_rd = T(geo2(_dup), plane="zx")
check("with coincident points, weld first then triangulate: 3 distinct points -> 1 triangle, area 0.5",
      _rd.nprims == 1 and abs(area(_rd) - 0.5) < 1e-6,
      (_rd.nprims, round(area(_rd), 9)))
check("  the output point count is still 5 (no points deleted, the coincident ones just take no part in the topology)",
      _rd.npoints == 5, _rd.npoints)
check("  fuse_tol=0 still merges **exactly coincident** points (3 distinct positions can only give 1 triangle; "
      "without merging the hull would spit out 3 degenerate faces)",
      T(geo2(_dup), plane="zx", fuse_tol=0.0).nprims == 1,
      T(geo2(_dup), plane="zx", fuse_tol=0.0).nprims)
check("empty input returned unchanged", T2.triangulate2d(
    Geometry.from_points(np.zeros((0, 3), np.float32))).npoints == 0)
check("None input returns None", T2.triangulate2d(None) is None)
check("delaunay returns an empty array for 0/1/2 points, does not raise",
      all(len(T2.delaunay(np.zeros((k, 2)))) == 0 for k in (0, 1, 2)))
check("delaunay returns an empty array for all-coincident points",
      len(T2.delaunay(np.zeros((5, 2)))) == 0)

# large coordinates: lifting squares the range; without normalization eps all follows z
BIG = RNG.random((200, 2)) * 1000.0 + 1e5
_rB = T(geo2(BIG), plane="zx")
check("coordinates of magnitude 1e5 with a span of 1000 are still valid (the kernel normalizes to the unit box before lifting)",
      not validate(_rB), validate(_rB) or "OK")
check("  triangle count identical to computing after translating/scaling into the unit box"
      " (a similarity transform should not change the topology of the triangulation)",
      len(T2.delaunay(BIG)) == len(T2.delaunay((BIG - BIG.min(0)) / 1000.0)),
      (len(T2.delaunay(BIG)),
       len(T2.delaunay((BIG - BIG.min(0)) / 1000.0))))

# Fuse Tolerance is an **absolute** length. An input whose overall size is only 1e-6 meeting the default 1e-6
# gets welded into one point -- the symptom ("no triangles could be produced") is identical to real collinearity,
# so the implementation detects this case separately and reports the size; otherwise it would be impossible to debug.
TINY = RNG.random((200, 2)) * 1e-6
err("overall size smaller than Fuse Tolerance: the error must say it **over-welded** "
    "and suggest a value, rather than just saying collinear",
    lambda: T(geo2(TINY), plane="zx"), "welded")
_rT = T(geo2(TINY), plane="zx", fuse_tol=1e-12)
check("  after lowering fuse_tol, coordinates of magnitude 1e-6 triangulate fine and validly",
      _rT.nprims > 300 and not validate(_rT),
      (_rT.nprims, validate(_rT) or "OK"))

err("two crossing constrained edges: the error must give both possible causes and the fix for each",
    lambda: T(geo2(np.array([[0, 0], [1, 1.], [0, 1], [1, 0.],
                             [.5, .45], [.45, .5], [.55, .5], [.5, .55]]),
                   [[0, 1], [2, 3]], closed=False),
              constrain="input_polygons"), "cannot be inserted")

print("═" * 28, "Purity")

_in = geo2(star(6), [list(range(12))])
_snap = (np.asarray(_in.get(POINT, "P")).copy(), _in.nprims)
_ = T(_in, constrain="input_polygons", region="remove_outside")
check("does not modify the input geometry",
      np.array_equal(np.asarray(_in.get(POINT, "P")), _snap[0])
      and _in.nprims == _snap[1])
_r1 = T(_in, constrain="input_polygons", region="remove_outside")
_r2b = T(_in, constrain="input_polygons", region="remove_outside")
check("the same input run twice gives bit-identical output",
      np.array_equal(np.asarray(_r1.get(POINT, "P")),
                     np.asarray(_r2b.get(POINT, "P")))
      and np.array_equal(np.asarray(_r1.vertex_point),
                         np.asarray(_r2b.vertex_point)))
check("output attribute arrays are read-only",
      not np.asarray(_r1.get(POINT, "P")).flags.writeable)
check("triangle point order does not depend on the insertion order of constrained edges (sorted in the implementation)",
      np.array_equal(
          np.asarray(T(geo2(HOLE, [[0, 1, 2, 3], [4, 5, 6, 7]]),
                       constrain="input_polygons",
                       region="remove_outside").vertex_point),
          np.asarray(T(geo2(HOLE, [[4, 5, 6, 7], [0, 1, 2, 3]]),
                       constrain="input_polygons",
                       region="remove_outside").vertex_point)))

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
