"""
pcg75: curves and surfaces -- Circle Spline, PolySpline, Ballistic Path, PolyLoft,
Cross Section Surface.

━━ Circle Spline (blended circular-arc spline)
Through every three adjacent points there is a circle. Segment i (p_i -> p_{i+1}) has two candidate arcs: circle C1 through
(p_{i-1}, p_i, p_{i+1}) and circle C2 through (p_i, p_{i+1}, p_{i+2}), each taking the part from p_i to p_{i+1}
(parameterized uniformly by central angle). The two arcs are blended by w = sin^2(pi*t/2):
    X(t) = (1 − w)·C₁(t) + w·C₂(t)
w has zero first derivative at both ends, so at p_i the curve's tangent and curvature are **exactly** those of the circle through (p_{i-1}, p_i, p_{i+1})
-- the segments on both sides use the same circle at this point, G2 continuous (measured with finite differences in the tests).
Points already on one circle -> the two circles coincide and the result is that circle (exactly); three collinear points -> that "circle"
degenerates into a line and the arc becomes a line segment. On open curves the first segment has only C2 and the last only C1.

━━ PolySpline
Polyline -> a smooth spline polyline through (or approximating) the points, with Divisions samples per segment:
  catmull_rom   interpolating. alpha is the exponent of the knot spacing: 0 uniform, 0.5 centripetal (no loops, no
                cusps), 1 chordal; evaluated with the Barry-Goldman pyramid
  bspline       uniform cubic B-spline, **approximating** (doesn't pass through interior points, smoother, C2)
  interpolate   uniform cubic B-spline, first solving a tridiagonal (cyclic tridiagonal when closed) system for control points so the curve
                passes exactly through every input point -- interpolating and C2
On open curves phantom points p_-1 = 2p_0 - p_1 are added at both ends, so all three start at the first point and end at the last
point. All numeric point attributes use the same weights as P (Cd and the like are smoothed along); integers / strings take the source
point nearest in parameter.

━━ Ballistic Path
Each point launches a projectile; the output is trajectory polylines (points carry time, v; source point attributes are carried over).
  velocity      uses point attribute v as initial velocity, flying for duration seconds
  target_time   points of the second input (paired by index) are targets; flight time flight_time, initial velocity solved for
  target_angle  targets as above, given an elevation angle (relative to "horizontal" = the plane perpendicular to gravity), speed solved for
Air drag is linear (a = g - k*v), with an analytic solution:
    v(t) = v∞ + (v₀ − v∞)e^{−kt},  p(t) = p₀ + v∞t + (v₀ − v∞)(1 − e^{−kt})/k,  v∞ = g/k
so the inverse for target_time is closed-form too; target_angle uses the parabola formula without drag and bisects on
speed with drag. Unreachable targets (elevation too low) produce no line and are counted in the report.
With ground on, trajectories are cut at the "ground" (height ground_height, measured along -g) -- solving a quadratic without drag,
bisection with drag, so the landing point is exactly on the ground; with collision geometry connected each segment is ray-intersected and cut at the first hit --
hitting the chord is not hitting the curve, so the hit segment is subdivided four more rounds (16 parts each) to find the first small chord
that hits; the chord's sagitta shrinks 256 times per round, so the final landing point lies on the true trajectory (< 1e-5 from RK4).

━━ PolyLoft
Connects faces / lines **using existing points** (unlike Skin: Skin creates new points, here not a single point is added):
  faces        lays faces between adjacent curves. Same point count -> quads; different -> triangles zipped by normalized arc length
               (nothing is missed)
  cross_lines  connects the i-th point of each curve into a "cross line"
  grid_lines   cross lines + the original curves, giving a wire net
wrap also connects the last curve with the first.

━━ Cross Section Surface (Gordon surface)
Two families of curves woven into a net: sections (first input) and guides (second input). Each section and each
guide intersect at a point X_ij (the midpoint of the two polylines' closest points; when they don't truly intersect the report gives the max gap). Along each
curve the parameter is remapped by the intersections into "the j-th intersection is at parameter j", then
    S(s,t) = L_sections(s,t) + L_guides(s,t) − T(s,t)
L_sections is the loft of the sections along t, L_guides the loft of the guides along s, T the tensor-product interpolation
of the intersections (all three use the same interpolation: linear or cubic = Catmull-Rom). This is the Gordon surface's
Boolean sum: **the surface passes exactly through every curve of the net** (regardless of interpolation, verified in the tests), using the information
of the other family as well, beyond a loft of one family (Skin). With closed sections the surface is closed in s, with closed guides
closed in t. Without guides connected it degenerates to a loft along the sections.
Parts of curves beyond the outermost intersections don't take part (the surface is bounded by the net's outer frame). Outputs a quad mesh + point attribute uv.
"""
from __future__ import annotations

import math

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .groups import resolve

# The last four were added in pcg100 following Houdini PolySpline's Spline Type (Special Bezier / Special Smooth
# Bezier have only names in the docs and no definition, not done)
SPLINE_BASES = ("catmull_rom", "bspline", "interpolate",
                "bezier", "degree2_bezier", "cardinal", "linear")
SPLINE_CLOSE = ("off", "on", "if_polygon_does")
SPLINE_DIVISION = ("standard", "even_length", "even_x", "even_y", "even_z")
BALLISTIC_MODES = ("velocity", "target_time", "target_angle")
LOFT_FORMS = ("faces", "cross_lines", "grid_lines")
CSS_INTERP = ("cubic", "linear")


# ═══════════════════════════════════════════════════════════ shared
def _P(geo):
    return (np.asarray(geo.get(POINT, "P"), np.float64) if geo is not None
            and geo.npoints else np.zeros((0, 3)))


def _curves(geo, group=""):
    """Selected polygon / polyline prims -> [(prim, point number array, closed)]."""
    sel = resolve(geo, PRIM, group)
    out = []
    for i in np.nonzero(sel)[0].tolist():
        if int(geo.prim_type[i]) != PRIM_POLY:
            continue
        pts = np.asarray(geo.prim_points(i), np.int64)
        if len(pts) < 2:
            continue
        out.append((i, pts, bool(geo.prim_closed[i]) and len(pts) >= 3))
    return out


def _float_stack(geo):
    names, cols = [], []
    for k, v in geo.attribs[POINT].items():
        if is_string(v):
            continue
        names.append(k)
        cols.append(v.shape[1])
    X = (np.concatenate([np.asarray(geo.attribs[POINT][k], np.float64)
                         for k in names], 1) if names
         else np.zeros((geo.npoints, 0)))
    return names, cols, X


def _curve_geometry(geo, pieces, extra=None):
    """
    pieces: [(source prim, float attribute rows (m,C), nearest source point numbers (m,), nearest source corners (m,), closed)]
    Float attributes are written back by row, integers / strings take the nearest source point; prim attributes come from the source prim.
    extra: {name: (m_total, k) array} extra point attributes.
    """
    names, cols, _ = _float_stack(geo)
    out = Geometry()
    if not pieces:
        return out
    rows = np.concatenate([p[1] for p in pieces])
    near = np.concatenate([p[2] for p in pieces]).astype(np.int64)
    ncor = np.concatenate([p[3] for p in pieces]).astype(np.int64)
    n = len(rows)
    out._resize_points(n)
    off = 0
    fl = {}
    for k, c in zip(names, cols):
        fl[k] = (off, c)
        off += c
    for k, v in geo.attribs[POINT].items():
        if k in fl and v.dtype.kind not in "iub":
            o, c = fl[k]
            out.set(POINT, k, rows[:, o:o + c].astype(v.dtype), owned=True)
        else:
            out.set(POINT, k, np.asarray(v)[near], owned=True)
    for k, m in geo.groups[POINT].items():
        out.set_group(POINT, k, np.asarray(m)[near])
    sizes = np.array([len(p[1]) for p in pieces], np.int64)
    src = np.array([p[0] for p in pieces], np.int64)
    out.set_topology(np.arange(n, dtype=np.int32),
                     np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                     np.array([p[4] for p in pieces], bool),
                     np.full(len(pieces), PRIM_POLY, np.uint8))
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, np.asarray(v)[ncor], owned=True)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, np.asarray(v)[src], owned=True)
    for k, m in geo.groups[PRIM].items():
        out.set_group(PRIM, k, np.asarray(m)[src])
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    for k, v in (extra or {}).items():
        out.set(POINT, k, np.asarray(v, np.float32), owned=True)
    return out


def _passthrough(geo, sel_prims):
    """Unselected / unprocessable prims are kept as they are (merged with the new curves)."""
    from .ops import delete_prims
    keep = np.ones(geo.nprims, bool)
    keep[list(sel_prims)] = False
    return delete_prims(geo, keep) if keep.any() else None


def _merge_with(rest, g):
    from .ops import merge
    return merge(rest, g) if rest is not None and rest.nprims else g


# ═══════════════════════════════════════════════════════════ Circle Spline
def _circle(a, b, c):
    """Circle through a,b,c: (centre, unit normal) -- the normal direction makes a->b->c counter-clockwise; None if collinear."""
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    nn = float(n @ n)
    if nn <= 1e-24 * float(ab @ ab) * float(ac @ ac) or nn <= 1e-300:
        return None
    C = a + (float(ac @ ac) * np.cross(n, ab) + float(ab @ ab) *
             np.cross(ac, n)) / (2.0 * nn)
    return C, n / math.sqrt(nn)


def _arc(p, q, circ, t):
    """Arc on the circle from p in the positive direction to q, parameterized uniformly by central angle; a line segment when circ is None."""
    if circ is None:
        return p + t[:, None] * (q - p)
    C, nh = circ
    u = p - C
    v = np.cross(nh, u)
    w = q - C
    phi = math.atan2(float(np.cross(u, w) @ nh), float(u @ w))
    if phi <= 0:
        phi += 2 * math.pi
    a = t * phi
    return C + np.cos(a)[:, None] * u + np.sin(a)[:, None] * v


# pcg100: Houdini's Spline Type / Helix Type. Hybrid and Ellipse have only one sentence in the docs, no definition to follow, not done
CIRCLE_TYPES = ("circle", "helix")
HELIX_TYPES = ("directional", "balanced", "blended")


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-300 else None


def _helix_axis(a, b, c, helix_type):
    """
    Helix axis direction of three points (a, b, c) (the docs' three kinds):
      directional  a -> c
      balanced     a->b and b->c are equally long measured along the axis: d.(a - 2b + c) = 0; the direction satisfying it that is closest to a->c
      blended      the two blended by the angle abc at b: 180 deg = directional, 0 deg = balanced
    Degenerate (a, c coincide) returns None -- the caller falls back to a circle.
    """
    dd = _unit(c - a)
    if dd is None:
        return None
    if helix_type == "directional":
        return dd
    n = _unit(a - 2 * b + c)
    db = dd if n is None else _unit(dd - float(dd @ n) * n)
    if db is None:
        db = dd
    if helix_type == "balanced":
        return db
    ua, uc = _unit(a - b), _unit(c - b)
    ang = math.acos(max(-1.0, min(1.0, float(ua @ uc)))) if ua is not None and uc is not None else math.pi
    w = ang / math.pi
    # db is dd projected onto the plane perpendicular to n, db.dd > 0, so the blend can't be a zero vector
    return _unit((1 - w) * db + w * dd)


def _helix_half(p, q, d, t):
    """
    Half-turn helix about axis d from p to q: in the plane perpendicular to d, the projections of p and q are the two ends of a diameter, rotating right-handed about d
    by half a turn (angle uniform in t); the coordinate along the axis is linear in t. When the projections coincide (p, q lined up along the axis) it is a line segment.
    """
    pa, qa = float(p @ d), float(q @ d)
    pp, qp = p - pa * d, q - qa * d
    ctr = 0.5 * (pp + qp)
    u = pp - ctr                                     # its length is the radius; 0 when the projections coincide, so the result naturally degenerates to a segment
    ax = ((1 - t) * pa + t * qa)[:, None] * d
    v = np.cross(d, u)
    th = math.pi * t
    return ctr + np.cos(th)[:, None] * u + np.sin(th)[:, None] * v + ax


def circle_spline(geo, group="", divisions=8, spline_type="circle", override_attrib=False,
                  helix_type="directional", adjust_arclength=False, arclength_samples=4,
                  curveu_name="", tangent_name=""):
    """
    See the file header. Returns (geometry, report).

    Added in pcg100 to match Houdini (defaults = previous behaviour):
      spline_type      circle (as before) / helix: a helix per three adjacent points (previous point at -180 deg,
                       this point at 0 deg, next point at 180 deg), axis set by helix_type; between two segments still blended by
                       w = sin^2(pi*t/2)
      override_attrib  a string point attribute splinetype (circle / helix) decides which kind the three points centred on this point use;
                       other values (hybrid / ellipse -- not done) and empty strings use spline_type
      adjust_arclength Adjust by Pseudo-Arclength: same point count, moved along the curve to be roughly equidistant by arc length; arc length is measured
                       on a polyline with arclength_samples extra samples between every two output points
      curveu_name / tangent_name  when non-empty, output parameter u (0~1 over the whole curve, by segment index + in-segment parameter) / unit tangent
    """
    if spline_type not in CIRCLE_TYPES:
        raise ValueError(f"Spline Type must be one of {CIRCLE_TYPES}")
    if helix_type not in HELIX_TYPES:
        raise ValueError(f"Helix Type must be one of {HELIX_TYPES}")
    d = max(1, int(divisions))
    P = _P(geo)
    names, cols, X = _float_stack(geo)
    st_attr = geo.attribs[POINT].get("splinetype") if override_attrib else None   # non-string values aren't recognized, fall back to spline_type
    pieces, used, extra_u, extra_t = [], [], [], []
    tt = np.arange(d) / d
    w = np.sin(0.5 * math.pi * tt) ** 2
    pcol = int(np.cumsum([0] + cols)[names.index("P")]) if "P" in names else None
    for pr, pts, closed in _curves(geo, group):
        n = len(pts)
        Q = P[pts]
        nseg = n if closed else n - 1
        circ, kind = [], []
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                circ.append(None)
                kind.append(None)
                continue
            a, b, c = Q[(i - 1) % n], Q[i], Q[(i + 1) % n]
            k = spline_type
            if st_attr is not None:
                v = str(np.asarray(st_attr)[pts[i], 0]).strip().lower()
                k = v if v in CIRCLE_TYPES else spline_type
            ax = _helix_axis(a, b, c, helix_type) if k == "helix" else None
            if ax is not None:
                circ.append(ax)
                kind.append("helix")
            else:
                circ.append(_circle(a, b, c))
                kind.append("circle")

        def half(i, p, q, t):
            # On the curve of the three points centred on point i, the half from p -> q; None = endpoint (no three points)
            if kind[i] == "helix":
                return _helix_half(p, q, circ[i], t)
            return _arc(p, q, circ[i], t)

        def seg_eval(i, t):
            j = (i + 1) % n
            p, q = Q[i], Q[j]
            has1 = closed or i > 0
            has2 = closed or j < n - 1
            A1 = half(i, p, q, t) if has1 else None
            A2 = half(j, p, q, t) if has2 else None
            if A1 is None and A2 is None:
                return p + t[:, None] * (q - p)
            if A1 is None:
                return A2
            if A2 is None:
                return A1
            ww = np.sin(0.5 * math.pi * t) ** 2
            return (1 - ww)[:, None] * A1 + ww[:, None] * A2

        rows, near, cor = [], [], []
        off = int(geo.prim_offset[pr])
        for i in range(nseg):
            j = (i + 1) % n
            p, q = Q[i], Q[j]
            has1 = closed or i > 0
            has2 = closed or j < n - 1
            A1 = half(i, p, q, tt) if has1 else None
            A2 = half(j, p, q, tt) if has2 else None
            if A1 is None and A2 is None:
                seg = p + tt[:, None] * (q - p)
            elif A1 is None:
                seg = A2
            elif A2 is None:
                seg = A1
            else:
                seg = (1 - w)[:, None] * A1 + w[:, None] * A2
            lin = (1 - tt)[:, None] * X[pts[i]] + tt[:, None] * X[pts[j]]
            if pcol is not None:
                lin[:, pcol:pcol + 3] = seg
            rows.append(lin)
            near.append(np.where(tt < 0.5, pts[i], pts[j]))
            cor.append(np.where(tt < 0.5, off + i, off + j))
        if not closed:
            rows.append(X[pts[-1:]])
            near.append(pts[-1:])
            cor.append(np.array([off + n - 1]))
        rows, near, cor = np.concatenate(rows), np.concatenate(near), np.concatenate(cor)
        M = len(rows)
        gpar = np.arange(M, dtype=np.float64) / d            # global parameter: segment index + in-segment parameter
        if adjust_arclength and nseg >= 1:
            # Each segment densely sampled in d*(k+1) parts to measure arc length; target is M equal-arc-length positions, parameters looked up inversely
            K = d * (max(0, int(arclength_samples)) + 1)
            td = np.arange(K) / K
            dense = np.concatenate([seg_eval(i, td) for i in range(nseg)] + [Q[[0 if closed else n - 1]]])
            dpar = np.concatenate([i + td for i in range(nseg)] + [[float(nseg)]])
            sl = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))])
            tot = float(sl[-1])
            if tot > 1e-12:
                tgt = (np.arange(M) * (tot / M)) if closed else np.linspace(0.0, tot, M)
                gpar = np.interp(tgt, sl, dpar)
                si = np.minimum(np.floor(gpar).astype(np.int64), nseg - 1)
                tl = gpar - si
                sj = (si + 1) % n
                rows = (1 - tl)[:, None] * X[pts[si]] + tl[:, None] * X[pts[sj]]
                if pcol is not None:
                    Ps = np.zeros((M, 3))
                    for i in np.unique(si):
                        m = si == i
                        Ps[m] = seg_eval(int(i), tl[m])
                    rows[:, pcol:pcol + 3] = Ps
                near = np.where(tl < 0.5, pts[si], pts[sj])
                cor = np.where(tl < 0.5, off + si, off + sj)
        if curveu_name:
            extra_u.append(gpar / max(nseg, 1))
        if tangent_name:
            h = 1e-5
            si = np.minimum(np.floor(gpar).astype(np.int64), nseg - 1)
            tl = gpar - si
            T = np.zeros((M, 3))
            for i in np.unique(si):
                m = si == i
                t0, t1 = tl[m] - h, tl[m] + h          # evaluate slightly beyond the segment at its ends (arcs / helices are defined there anyway)
                T[m] = seg_eval(int(i), t1) - seg_eval(int(i), t0)
            nn = np.linalg.norm(T, axis=1, keepdims=True)
            extra_t.append(T / np.maximum(nn, 1e-300))
        pieces.append((pr, rows, near, cor, closed))
        used.append(pr)
    extra = {}
    if curveu_name and extra_u:
        extra[curveu_name] = np.concatenate(extra_u)[:, None]
    if tangent_name and extra_t:
        extra[tangent_name] = np.concatenate(extra_t)
    g = _curve_geometry(geo, pieces, extra or None)
    return _merge_with(_passthrough(geo, used), g), {"curves": len(used)}


# ═══════════════════════════════════════════════════════════ PolySpline
def _cr_eval(Y, s, alpha, P4):
    """Barry-Goldman: Y (4,C) values, P4 (4,3) positions (for computing knots), s (m,) in [0,1]."""
    t = [0.0]
    for k in range(3):
        dd = float(np.linalg.norm(P4[k + 1] - P4[k])) ** float(alpha)
        t.append(t[-1] + max(dd, 1e-12))
    t0, t1, t2, t3 = t
    x = t1 + s * (t2 - t1)
    X = x[:, None]

    def lerp(a, b, ta, tb):
        return ((tb - X) * a + (X - ta) * b) / (tb - ta)
    A1 = lerp(Y[0], Y[1], t0, t1)
    A2 = lerp(Y[1], Y[2], t1, t2)
    A3 = lerp(Y[2], Y[3], t2, t3)
    B1 = lerp(A1, A2, t0, t2)
    B2 = lerp(A2, A3, t1, t3)
    return lerp(B1, B2, t1, t2)


def _bspline_seg(Y, s):
    """One segment of a uniform cubic B-spline: control points Y (4,C)."""
    s = s[:, None]
    b0 = (1 - s) ** 3 / 6
    b1 = (3 * s ** 3 - 6 * s ** 2 + 4) / 6
    b2 = (-3 * s ** 3 + 3 * s ** 2 + 3 * s + 1) / 6
    b3 = s ** 3 / 6
    return b0 * Y[0] + b1 * Y[1] + b2 * Y[2] + b3 * Y[3]


def _solve_interp(Y, closed):
    """Solves (c_{i-1} + 4c_i + c_{i+1})/6 = y_i for control points. Open: c = y at both ends (with phantom points)."""
    n = len(Y)
    if closed:
        # Cyclic tridiagonal: reduced to an ordinary tridiagonal by Sherman-Morrison
        if n == 3:
            A = np.array([[4, 1, 1], [1, 4, 1], [1, 1, 4]], float) / 6
            return np.linalg.solve(A, Y)
        a = np.full(n, 1 / 6)
        b = np.full(n, 4 / 6)
        c = np.full(n, 1 / 6)
        gamma = -b[0]
        bb = b.copy()
        bb[0] -= gamma
        bb[-1] -= a[0] * c[-1] / gamma
        x = _thomas(a, bb, c, Y)
        u = np.zeros(n)
        u[0], u[-1] = gamma, c[-1]
        z = _thomas(a, bb, c, u[:, None])
        vx = x[0] + a[0] / gamma * x[-1]
        vz = z[0] + a[0] / gamma * z[-1]
        return x - z * (vx / (1 + vz))[None, :]
    # Open: phantom point c_{-1} = 2c_0 - c_1 turns row 0 into c_0 = y_0, likewise for the last row
    a = np.full(n, 1 / 6)
    b = np.full(n, 4 / 6)
    c = np.full(n, 1 / 6)
    b[0] = b[-1] = 1.0
    c[0] = 0.0
    a[-1] = 0.0
    return _thomas(a, b, c, Y)


def _thomas(a, b, c, d):
    n = len(b)
    cp = np.zeros(n)
    dp = np.zeros_like(d, dtype=np.float64)
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m if i < n - 1 else 0.0
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = np.zeros_like(dp)
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def _bezier_seg(Y, s):
    """de Casteljau: Y (k+1,C) are the control points of one degree-k Bezier segment, s (m,) in [0,1]."""
    lv = [np.repeat(y[None], len(s), 0) for y in Y]
    t = s[:, None]
    while len(lv) > 1:
        lv = [(1 - t) * lv[i] + t * lv[i + 1] for i in range(len(lv) - 1)]
    return lv[0]


def _cardinal_seg(Y, s, tension):
    """
    One Cardinal spline segment (through Y[1], Y[2]): Hermite, tangent m_i = (1 - tension)*(y_{i+1} - y_{i-1})/2.
    tension = 0 is uniform Catmull-Rom, at 1 the tangents are 0 (each segment a straight line, zero speed at both ends).
    """
    k = (1.0 - float(tension)) * 0.5
    m1, m2 = k * (Y[2] - Y[0]), k * (Y[3] - Y[1])
    t = s[:, None]
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * Y[1] + (t3 - 2 * t2 + t) * m1
            + (-2 * t3 + 3 * t2) * Y[2] + (t3 - t2) * m2)


_MARCH_LIMIT = 2_000_000          # even resampling outputs at most this many points; more is taken as a mistyped Segment Length


def _march(Q, L, limit=None):
    """
    Starting from Q[0], walks forward along polyline Q (m,3), each step landing on the first position "whose straight-line distance from the previous sample is exactly L"
    -- so adjacent output points have equal **chord lengths** (not equal arc length along the polyline).
    Returns ([(segment index, in-segment parameter)], distance from the last sample to Q[-1]).
    Even X/Y/Z zero the other two components of Q and use the same function: the chord length becomes the distance along that one axis.
    """
    if limit is None:
        limit = _MARCH_LIMIT
    out = [(0, 0.0)]
    cur = Q[0]
    j, u0, fresh = 0, 0.0, False
    L2 = L * L
    m = len(Q)
    while j < m - 1:
        A, d = Q[j], Q[j + 1] - Q[j]
        a = float(d @ d)
        hit = None
        w = A - cur
        c = float(w @ w) - L2
        if fresh and c >= 0:
            # The previous segment's sphere exit point, in floating point, landed at 1 + eps (didn't count), and in this segment became -eps: the exit point is this vertex.
            # If it isn't caught, all later points are already outside the sphere, all large roots are behind, and this step can never land
            hit = 0.0
        elif a > 1e-300:
            b = 2.0 * float(w @ d)
            disc = b * b - 4 * a * c
            if disc >= 0:
                u = (-b + math.sqrt(disc)) / (2 * a)     # large root: the crossing out of the sphere
                if fresh:
                    # A new segment with its start inside the sphere (c < 0): mathematically the large root must be > 0; computing <= 0 can only be
                    # rounding with the start exactly on the sphere -- also accepted as "the exit point is this vertex". Previously this uniformly required
                    # u > u0 (= 0), so this case was missed and caught by the branch above in the next segment at the next vertex,
                    # making that step's chord a whole short segment longer (happened with a closed circle divided into 6 segments)
                    if u <= 1.0:
                        hit = max(u, 0.0)
                elif u0 < u <= 1.0:
                    hit = u
        if hit is None:
            j, u0, fresh = j + 1, 0.0, True
            continue
        cur = A + d * hit
        u0, fresh = hit, False
        out.append((j, hit))
        if len(out) > limit:
            raise ValueError("Segment Length too small: the resampled point count exceeds the limit")
    return out, float(np.linalg.norm(Q[-1] - cur))


def _even_params(Q, seg_len, ndiv):
    """
    Parameters of equal-chord-length resampling. seg_len > 0: walk with this length; the leftover tail shorter than a step becomes a short last segment
    (the docs don't say what to do with the tail; this way the curve still reaches its end). seg_len = 0: bisect for the step length that "reaches
    the end in exactly ndiv steps". Returns [(segment index, in-segment parameter)]; the last is always the end.
    """
    end = (len(Q) - 2, 1.0)
    if seg_len > 0:
        par, rem = _march(Q, seg_len)
        if rem > 1e-9 * max(seg_len, 1.0):
            par.append(end)
        else:
            par[-1] = end
        return par
    n = int(ndiv)
    tot = float(np.linalg.norm(np.diff(Q, axis=0), axis=1).sum())
    if tot <= 0:
        return [(0, 0.0), end]
    lo, hi = 0.0, tot                     # with step = total polyline length not even one step completes (chord <= arc)
    for _ in range(80):
        mid = 0.5 * (lo + hi)             # halving from tot 80 times never reaches 0
        par, rem = _march_capped(Q, mid, n)
        if len(par) - 1 + rem / mid > n:
            lo = mid                      # more than n steps: step too small
        else:
            hi = mid
    par, _ = _march_capped(Q, hi, n)
    par = par[:n]
    while len(par) < n:                   # numerically just short of n: pad with the end (only for degenerate curves)
        par.append(end)
    return par + [end]


def _march_capped(Q, L, n):
    """_march, but stops after n + 1 steps (the bisection iterations with tiny steps don't have to walk all the way)."""
    try:
        return _march(Q, L, limit=n + 1)
    except ValueError:
        return [None] * (n + 3), 0.0


def _resample(rows, near, cor, par):
    j = np.array([p[0] for p in par], np.int64)
    u = np.array([p[1] for p in par], np.float64)
    r = rows[j] * (1 - u)[:, None] + rows[j + 1] * u[:, None]
    pick = np.where(u < 0.5, j, j + 1)
    return r, near[pick], cor[pick]


def poly_spline(geo, group="", basis="catmull_rom", alpha=0.5, divisions=8,
                close="if_polygon_does", division_method="standard",
                segment_length=0.0, output_divisions=0,
                first_cv_count=1, last_cv_count=1, tension=0.5):
    """
    Since pcg100, added to match Houdini's PolySpline:
      basis    bezier / degree2_bezier: polygon points are Bezier control points, one segment per 3 (2), adjacent segments
               sharing endpoints; leftover points at the end that don't fill a segment make one lower-degree segment (not in the docs; this way the curve
               still reaches the last point). cardinal: interpolating, tangent (1 - tension)(p+ - p-)/2. linear: straight segments
      close    off / on / if_polygon_does (= previous behaviour)
      division_method  standard: no resampling; even_length: equal chord length between adjacent points; even_x/y/z: equal distance between adjacent points along
               that axis. Uses Segment Length if non-zero, otherwise Output Divisions; if both are
               0 there is no resampling (the docs say each derives the other; both 0 is undefined)
      first/last_cv_count  how many times the first / last control point is repeated (before spline evaluation)
    """
    if basis not in SPLINE_BASES:
        raise ValueError(f"Basis must be one of {SPLINE_BASES}")
    if close not in SPLINE_CLOSE:
        raise ValueError(f"Close must be one of {SPLINE_CLOSE}")
    if division_method not in SPLINE_DIVISION:
        raise ValueError(f"Division Method must be one of {SPLINE_DIVISION}")
    d = max(1, int(divisions))
    P = _P(geo)
    names, cols, X = _float_stack(geo)
    pcol = int(sum(cols[:names.index("P")]))       # P is always among the float attributes
    s = np.arange(d) / d
    n_first, n_last = max(1, int(first_cv_count)), max(1, int(last_cv_count))
    seg_len, ndiv = max(0.0, float(segment_length)), max(0, int(output_divisions))
    resample = division_method != "standard" and (seg_len > 0 or ndiv > 0)
    pieces, used = [], []
    for pr, pts, closed in _curves(geo, group):
        off = int(geo.prim_offset[pr])
        cors = off + np.arange(len(pts))
        if close != "if_polygon_does":
            closed = close == "on" and len(pts) >= 3
        if n_first > 1 or n_last > 1:
            rep = np.ones(len(pts), np.int64)
            rep[0], rep[-1] = n_first, n_last
            pts, cors = np.repeat(pts, rep), np.repeat(cors, rep)
        n = len(pts)
        Y = X[pts]
        Q = P[pts]
        if basis == "interpolate":
            Y = _solve_interp(Y, closed)     # Q is only for Catmull-Rom knots, unused here
        if closed:
            idx = lambda k: Y[k % n]                    # noqa: E731
            qdx = lambda k: Q[k % n]                    # noqa: E731
        else:
            def idx(k, Y=Y):
                if k < 0:
                    return 2 * Y[0] - Y[1]
                if k >= n:
                    return 2 * Y[-1] - Y[-2]
                return Y[k]

            def qdx(k, Q=Q):
                if k < 0:
                    return 2 * Q[0] - Q[1]
                if k >= n:
                    return 2 * Q[-1] - Q[-2]
                return Q[k]
        rows, near, cor = [], [], []
        if basis in ("bezier", "degree2_bezier"):
            deg = 3 if basis == "bezier" else 2
            ci = np.arange(n + 1) % n if closed else np.arange(n)   # closed: wrap back to the first control point
            for a0 in range(0, len(ci) - 1, deg):
                seg = ci[a0:a0 + deg + 1]                # the last segment may have fewer than deg + 1
                rows.append(_bezier_seg(Y[seg], s))
                k = np.rint(s * (len(seg) - 1)).astype(np.int64)
                near.append(pts[seg[k]])
                cor.append(cors[seg[k]])
        else:
            nseg = n if closed else n - 1
            for i in range(nseg):
                j = (i + 1) % n
                if basis == "linear":
                    rows.append(Y[i] * (1 - s)[:, None] + Y[j] * s[:, None])
                else:
                    Y4 = np.stack([idx(i - 1), idx(i), idx(i + 1), idx(i + 2)])
                    if basis == "catmull_rom":
                        P4 = np.stack([qdx(i - 1), qdx(i), qdx(i + 1), qdx(i + 2)])
                        rows.append(_cr_eval(Y4, s, alpha, P4))
                    elif basis == "cardinal":
                        rows.append(_cardinal_seg(Y4, s, tension))
                    else:
                        rows.append(_bspline_seg(Y4, s))
                near.append(np.where(s < 0.5, pts[i], pts[j]))
                cor.append(np.where(s < 0.5, cors[i], cors[j]))
        if not closed:
            # Every basis ends exactly on the last point: the B-spline has a reflected phantom point,
            # (c- + 4c + 2c - c-)/6 = c; interpolate's last control point equals the last input point
            rows.append(X[pts[-1:]])
            near.append(pts[-1:])
            cor.append(cors[-1:])
        rows, near, cor = np.concatenate(rows), np.concatenate(near), np.concatenate(cor)
        if resample and len(rows) >= 2:
            if closed:                                   # wrap back to the start before sampling, then remove the duplicate end
                rows = np.concatenate([rows, rows[:1]])
                near = np.concatenate([near, near[:1]])
                cor = np.concatenate([cor, cor[:1]])
            Qs = rows[:, pcol:pcol + 3]
            if division_method != "even_length":
                ax = "xyz".index(division_method[-1])
                Qa = np.zeros_like(Qs)
                Qa[:, ax] = Qs[:, ax]
                Qs = Qa
            par = _even_params(Qs, seg_len, ndiv)
            rows, near, cor = _resample(rows, near, cor, par)
            if closed:
                rows, near, cor = rows[:-1], near[:-1], cor[:-1]
        pieces.append((pr, rows, near, cor, closed))
        used.append(pr)
    g = _curve_geometry(geo, pieces)
    return _merge_with(_passthrough(geo, used), g), {"curves": len(used)}


# ═══════════════════════════════════════════════════════════ Ballistic Path
def _traj(p0, v0, g, k, t):
    """t (m,) -> positions (m,3), velocities (m,3). A parabola when k = 0."""
    t = np.asarray(t, np.float64)[:, None]
    if k <= 0:
        return p0 + v0 * t + 0.5 * g * t * t, v0 + g * t
    vi = g / k
    e = np.exp(-k * t)
    return p0 + vi * t + (v0 - vi) * (1 - e) / k, vi + (v0 - vi) * e


def _v_for_time(p0, tgt, g, k, T):
    if k <= 0:
        return (tgt - p0 - 0.5 * g * T * T) / T
    vi = g / k
    return vi + k * (tgt - p0 - vi * T) / (1 - math.exp(-k * T))


def _v_for_angle(p0, tgt, g, k, angle):
    """Fixed elevation angle, solve for speed. None if unreachable. Returns (v0, flight time)."""
    gn = float(np.linalg.norm(g))
    up = -g / gn
    d = tgt - p0
    h = d - (d @ up) * up
    x = float(np.linalg.norm(h))
    y = float(d @ up)
    if x < 1e-12:
        return None
    hd = h / x
    th = math.radians(float(angle))
    dirv = math.cos(th) * hd + math.sin(th) * up
    if k <= 0:
        den = 2 * math.cos(th) ** 2 * (x * math.tan(th) - y)
        if den <= 0:
            return None
        s = math.sqrt(gn * x * x / den)
        return s * dirv, x / (s * math.cos(th))

    # With drag: horizontal x(T) = s cos(theta) (1 - e^{-kT})/k, vertical by the analytic formula; bisect on s
    def height_at_target(s):
        vx = s * math.cos(th)
        r = k * x / vx
        if r >= 1:
            return None
        T = -math.log(1 - r) / k
        pos, _ = _traj(np.zeros(3), s * dirv, g, k, [T])
        return float(pos[0] @ up) - y, T
    lo, hi = 1e-6, 1.0
    for _ in range(200):
        r = height_at_target(hi)
        if r is not None and r[0] > 0:
            break
        hi *= 2
        if hi > 1e9:
            return None
    else:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        r = height_at_target(mid)
        if r is None or r[0] < 0:
            lo = mid
        else:
            hi = mid
    r = height_at_target(hi)
    return hi * dirv, r[1]


def _ground_time(p0, v0, g, k, h0, T):
    """Time of first reaching height h0 (measured along -g); None if not reached within T."""
    gn = float(np.linalg.norm(g))
    up = -g / gn
    if k <= 0:
        # Height is a downward-opening parabola; "crossing down through the ground" is the larger root -- also correct when launching from on (or
        # below) the ground: the root at the start (0 or negative) doesn't count
        a, b, c = -0.5 * gn, float(v0 @ up), float(p0 @ up) - h0
        disc = b * b - 4 * a * c
        if disc < 0:
            return None
        r = (-b - math.sqrt(disc)) / (2 * a)
        return r if 1e-12 * max(T, 1.0) < r <= T else None
    ts = np.linspace(0, T, 1025)
    hs = _traj(p0, v0, g, k, ts)[0] @ up - h0
    down = np.nonzero((hs[1:] <= 0) & (hs[:-1] > 0))[0]
    if not len(down):
        return None
    lo, hi = ts[down[0]], ts[down[0] + 1]
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if float(_traj(p0, v0, g, k, [mid])[0][0] @ up) - h0 > 0:
            lo = mid
        else:
            hi = mid
    return hi


def ballistic_path(geo, group="", mode="velocity", targets=None,
                   v_attribute="v", gravity=(0.0, -9.8, 0.0), drag=0.0,
                   duration=2.0, flight_time=1.0, launch_angle=45.0,
                   samples=32, ground=False, ground_height=0.0,
                   collision=None):
    """See the file header. Returns (geometry, report)."""
    from .spatial import ray_cast, tri_soup
    if mode not in BALLISTIC_MODES:
        raise ValueError(f"Mode must be one of {BALLISTIC_MODES}")
    g = np.asarray(gravity, np.float64)
    if not np.linalg.norm(g) > 0:
        raise ValueError("Gravity cannot be a zero vector (the horizontal plane and the ground are both defined by it)")
    k = max(0.0, float(drag))
    m = max(2, int(samples))
    sel = resolve(geo, POINT, group)
    P = _P(geo)
    ids = np.nonzero(sel)[0]
    if mode == "velocity":
        va = geo.get(POINT, str(v_attribute).strip())
        if va is None or is_string(va) or va.shape[1] < 3:
            raise KeyError(f"No vector attribute '{v_attribute}' on point")
        V = np.asarray(va, np.float64)[:, :3]
    else:
        if targets is None or not targets.npoints:
            raise ValueError("target modes need the second input (target points, paired with launch points by index)")
        TP = _P(targets)
    if collision is not None and collision.nprims:
        ctri, _, _ = tri_soup(collision)
        CP = _P(collision)
    else:
        ctri = None
    names, cols, X = _float_stack(geo)
    pieces, times, vels = [], [], []
    rep = {"paths": 0, "unreachable": 0, "hit_ground": 0, "hit_collision": 0}
    oP = int(np.cumsum([0] + cols)[names.index("P")]) if "P" in names else 0
    for n_, i in enumerate(ids.tolist()):
        p0 = P[i]
        if mode == "velocity":
            v0, T = V[i], float(duration)
        else:
            if n_ >= targets.npoints:
                rep["unreachable"] += 1
                continue
            tgt = TP[n_]
            if mode == "target_time":
                T = float(flight_time)
                if not T > 0:
                    raise ValueError("Flight Time must be > 0")
                v0 = _v_for_time(p0, tgt, g, k, T)
            else:
                r = _v_for_angle(p0, tgt, g, k, launch_angle)
                if r is None:
                    rep["unreachable"] += 1
                    continue
                v0, T = r
        if not T > 0:
            continue
        hit = None
        if ground:
            tg = _ground_time(p0, v0, g, k, float(ground_height), T)
            if tg is not None:
                T, hit = tg, "ground"
        ts = np.linspace(0, T, m)
        pos, vel = _traj(p0, v0, g, k, ts)
        if ctri is not None and len(ctri):
            O = pos[:-1]
            D = pos[1:] - pos[:-1]
            L = np.linalg.norm(D, axis=1)
            ti, tt, _ = ray_cast(O, D / np.maximum(L, 1e-300)[:, None], CP,
                                 ctri, max_dist=float(L.max()) + 1e-9)[:3]
            ok = (ti >= 0) & (tt <= L + 1e-12)
            if ok.any():
                s_ = int(np.nonzero(ok)[0][0])
                # Hitting the chord, not the curve: subdivide this segment 4 more rounds (16 parts each) to find
                # the first small chord that hits; the chord's sagitta shrinks 256 times per round, so the final landing point's distance from the true trajectory is negligible
                ta, tb = ts[s_], ts[s_ + 1]
                for _ in range(4):
                    sub = np.linspace(ta, tb, 17)
                    sp, _ = _traj(p0, v0, g, k, sub)
                    D2 = sp[1:] - sp[:-1]
                    L2 = np.linalg.norm(D2, axis=1)
                    ti2, tt2, _ = ray_cast(sp[:-1], D2 / np.maximum(L2, 1e-300)
                                           [:, None], CP, ctri,
                                           max_dist=float(L2.max()) + 1e-12)[:3]
                    ok2 = (ti2 >= 0) & (tt2 <= L2 + 1e-12)
                    if not ok2.any():
                        break
                    q = int(np.nonzero(ok2)[0][0])
                    f = float(tt2[q] / max(L2[q], 1e-300))
                    Th = sub[q] + f * (sub[q + 1] - sub[q])
                    ta, tb = sub[q], sub[q + 1]
                ts = np.linspace(0, Th, m)
                # The last sample uses p(Th) directly: after four rounds of subdivision the chord-curve difference is on the order of 1e-9,
                # no need to snap it onto the hit point (tried it; no measurable difference)
                pos, vel = _traj(p0, v0, g, k, ts)
                hit = "collision"
        rows = np.repeat(X[i:i + 1], m, 0)
        if "P" in names:
            rows[:, oP:oP + 3] = pos
        pieces.append((0, rows, np.full(m, i), np.zeros(m, np.int64), False))
        times.append(ts)
        vels.append(vel)
        rep["paths"] += 1
        if hit == "ground":
            rep["hit_ground"] += 1
        elif hit == "collision":
            rep["hit_collision"] += 1
    src = Geometry()
    src._resize_points(geo.npoints)
    for kk, v in geo.attribs[POINT].items():
        src.set(POINT, kk, v)
    for kk, mm in geo.groups[POINT].items():
        src.set_group(POINT, kk, mm)
    src.set_topology(np.zeros(1, np.int32), np.array([0, 1], np.int32),
                     np.zeros(1, bool))
    src.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    extra = {}
    if pieces:
        extra = {"time": np.concatenate(times)[:, None],
                 "v": np.concatenate(vels)}
    out = _curve_geometry(src, pieces, extra)
    if pieces:
        srcp = np.array([p[2][0] for p in pieces], np.int32)
        out.set(PRIM, "srcpoint", srcp[:, None], owned=True)
    return out, rep


# ═══════════════════════════════════════════════════════════ PolyLoft
def _zip(A, B, PA, PB, closed):
    """Zips triangles between two runs of points (point numbers A, B, positions PA, PB) by normalized arc length."""
    def params(X):
        Y = np.vstack([X, X[:1]]) if closed else X
        s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(Y, axis=0),
                                                          axis=1))])
        return s / s[-1] if s[-1] > 0 else np.linspace(0, 1, len(s))
    ua, ub = params(PA), params(PB)
    na, nb = len(A), len(B)
    ea = na if closed else na - 1
    eb = nb if closed else nb - 1
    i = j = 0
    faces = []
    while i < ea or j < eb:
        if j >= eb or (i < ea and ua[i + 1] <= ub[j + 1]):
            faces.append([A[i], A[(i + 1) % na], B[j]])
            i += 1
        else:
            faces.append([A[i], B[(j + 1) % nb], B[j]])
            j += 1
    return faces


def poly_loft(geo, group="", form="faces", wrap=False, keep_original=True):
    from .meshedit import _Build
    if form not in LOFT_FORMS:
        raise ValueError(f"Form must be one of {LOFT_FORMS}")
    cv = _curves(geo, group)
    rep = {"curves": len(cv), "faces": 0, "lines": 0}
    B = _Build(geo)
    P = _P(geo)
    used = {pr for pr, _, _ in cv}
    for i in range(geo.nprims):
        if i not in used or keep_original or form == "grid_lines":
            o0, o1 = int(geo.prim_offset[i]), int(geo.prim_offset[i + 1])
            B.add_face([int(geo.vertex_point[c]) for c in range(o0, o1)],
                       list(range(o0, o1)), i, bool(geo.prim_closed[i]))

    def corner_of(pr, k):
        return int(geo.prim_offset[pr]) + int(k)
    pairs = list(zip(cv[:-1], cv[1:]))
    if wrap and len(cv) > 2:
        pairs.append((cv[-1], cv[0]))
    if form == "faces":
        for (pa, A, ca), (pb, Bp, cb) in pairs:
            closed = ca and cb
            if len(A) == len(Bp):
                n = len(A)
                for k in range(n if closed else n - 1):
                    k2 = (k + 1) % n
                    B.add_face([A[k], A[k2], Bp[k2], Bp[k]],
                               [corner_of(pa, k), corner_of(pa, k2),
                                corner_of(pb, k2), corner_of(pb, k)], pa, True)
                    rep["faces"] += 1
            else:
                ia = {int(p): corner_of(pa, k) for k, p in enumerate(A)}
                ib = {int(p): corner_of(pb, k) for k, p in enumerate(Bp)}
                for f in _zip(A, Bp, P[A], P[Bp], closed):
                    B.add_face(f, [ia.get(int(p), ib.get(int(p))) for p in f],
                               pa, True)
                    rep["faces"] += 1
    else:
        nmax = max(len(A) for _, A, _ in cv) if cv else 0
        for k in range(nmax):
            pts, cor = [], []
            for pr, A, _ in cv:
                if k < len(A):
                    pts.append(int(A[k]))
                    cor.append(corner_of(pr, k))
            if wrap and len(pts) > 2:
                closed_line = True
            else:
                closed_line = False
            if len(pts) >= 2:
                B.add_face(pts, cor, cv[0][0], closed_line)
                rep["lines"] += 1
    return B.geometry(sort=False), rep


# ═══════════════════════════════════════════════════════════ Cross Section Surface
def _seg_closest(A0, A1, B0, B1):
    """Closest-point parameters (s, t) and distances of all A segments x B segments. A0/A1 (a,3), B0/B1 (b,3)."""
    d1 = (A1 - A0)[:, None, :]
    d2 = (B1 - B0)[None, :, :]
    r = A0[:, None, :] - B0[None, :, :]
    a = np.einsum("ijk,ijk->ij", d1, d1) + 0 * r[..., 0]
    e = np.einsum("ijk,ijk->ij", d2, d2) + 0 * r[..., 0]
    f = np.einsum("ijk,ijk->ij", d2, r)
    c = np.einsum("ijk,ijk->ij", d1, r)
    b = np.einsum("ijk,ijk->ij", d1, d2)
    den = a * e - b * b
    s = np.where(den > 1e-18 * a * e, (b * f - c * e) / np.where(den > 0, den,
                                                                 1.0), 0.0)
    s = np.clip(s, 0, 1)
    t = np.where(e > 0, (b * s + f) / np.where(e > 0, e, 1.0), 0.0)
    s = np.where(t < 0, np.clip(-c / np.where(a > 0, a, 1.0), 0, 1), s)
    s = np.where(t > 1, np.clip((b - c) / np.where(a > 0, a, 1.0), 0, 1), s)
    t = np.clip(t, 0, 1)
    pa = A0[:, None, :] + s[..., None] * d1
    pb = B0[None, :, :] + t[..., None] * d2
    return s, t, np.linalg.norm(pa - pb, axis=-1), pa, pb


class _Poly:
    def __init__(self, X, closed):
        self.closed = closed
        self.X = np.vstack([X, X[:1]]) if closed else X
        self.s = np.concatenate([[0], np.cumsum(np.linalg.norm(
            np.diff(self.X, axis=0), axis=1))])
        self.L = float(self.s[-1])

    def at(self, u):
        u = np.asarray(u, np.float64)
        if self.closed:
            u = np.mod(u, self.L)
        return np.stack([np.interp(u, self.s, self.X[:, c]) for c in range(3)],
                        -1)


def _closest_on(pa, pb):
    """Closest points of two polylines: (arc length on a, arc length on b, midpoint, distance)."""
    s, t, dist, xa, xb = _seg_closest(pa.X[:-1], pa.X[1:], pb.X[:-1], pb.X[1:])
    i, j = np.unravel_index(int(np.argmin(dist)), dist.shape)
    ua = pa.s[i] + s[i, j] * (pa.s[i + 1] - pa.s[i])
    ub = pb.s[j] + t[i, j] * (pb.s[j + 1] - pb.s[j])
    return ua, ub, 0.5 * (xa[i, j] + xb[i, j]), float(dist[i, j])


def _interp1(Y, x, closed, cubic):
    """Interpolates node values Y (K, ...) at parameters x (m,). Nodes at 0..K-1 (period K when closed)."""
    K = len(Y)
    x = np.asarray(x, np.float64)
    if closed:
        x = np.mod(x, K)
        i = np.floor(x).astype(np.int64) % K
    else:
        i = np.clip(np.floor(x).astype(np.int64), 0, max(K - 2, 0))
    f = x - np.floor(x) if closed else x - i
    f = f.reshape((-1,) + (1,) * (Y.ndim - 1))

    def get(k):
        if closed:
            return Y[k % K]
        k0 = np.clip(k, 0, K - 1)
        lo = k < 0
        hi = k > K - 1
        out = Y[k0].copy()
        if lo.any():
            out[lo] = 2 * Y[0] - Y[1]
        if hi.any():
            out[hi] = 2 * Y[-1] - Y[-2]
        return out
    if K == 1:
        return np.repeat(Y[:1], len(x), 0)
    y1, y2 = get(i), get(i + 1)
    if not cubic:
        return (1 - f) * y1 + f * y2
    y0, y3 = get(i - 1), get(i + 2)
    f2, f3 = f * f, f * f * f
    return 0.5 * ((2 * y1) + (-y0 + y2) * f + (2 * y0 - 5 * y1 + 4 * y2 - y3) * f2
                  + (-y0 + 3 * y1 - 3 * y2 + y3) * f3)


def _knot_map(u_nodes, closed, L):
    """Piecewise linear map from the arc length u_j of the j-th intersection on the curve -> parameter j (unrolled to increasing when closed)."""
    u = np.asarray(u_nodes, np.float64).copy()
    if closed:
        # This curve may be drawn in the opposite direction to the others: try both increasing and decreasing unrolling, take the one that goes around once
        up, dn = u.copy(), u.copy()
        for j in range(1, len(u)):
            while up[j] <= up[j - 1]:
                up[j] += L
            while dn[j] >= dn[j - 1]:
                dn[j] -= L
        up = np.concatenate([up, [up[0] + L]])
        dn = np.concatenate([dn, [dn[0] - L]])
        return up if up[-2] - up[0] <= dn[0] - dn[-2] else dn
    return u


def cross_section_surface(sections, guides=None, group="", guide_group="",
                          interpolation="cubic", divisions_s=8,
                          divisions_t=8):
    """See the file header. Returns (geometry, report)."""
    if interpolation not in CSS_INTERP:
        raise ValueError(f"Interpolation must be one of {CSS_INTERP}")
    cubic = interpolation == "cubic"
    PA = _P(sections)
    A = [_Poly(PA[pts], cl) for _, pts, cl in _curves(sections, group)]
    if len(A) < 2 and guides is None:
        raise ValueError("At least two cross-section curves are needed")
    if not A:
        raise ValueError("No curves in sections")
    Gs = []
    if guides is not None and guides.nprims:
        PB = _P(guides)
        Gs = [_Poly(PB[pts], cl) for _, pts, cl in _curves(guides, guide_group)]
    ds, dt = max(1, int(divisions_s)), max(1, int(divisions_t))
    rep = {"sections": len(A), "guides": len(Gs)}
    if Gs:
        m, n = len(A), len(Gs)
        UA = np.zeros((m, n))
        UB = np.zeros((m, n))
        Xn = np.zeros((m, n, 3))
        gap = 0.0
        for i in range(m):
            for j in range(n):
                ua, ub, x, dd = _closest_on(A[i], Gs[j])
                UA[i, j], UB[i, j], Xn[i, j] = ua, ub, x
                gap = max(gap, dd)
        rep["max_gap"] = gap
        # guides sorted along cross-section 0; cross-sections sorted along guide 0
        oj = np.argsort(UA[0])
        oi = np.argsort(UB[:, oj[0]])
        A = [A[i] for i in oi]
        Gs = [Gs[j] for j in oj]
        UA, UB, Xn = UA[oi][:, oj], UB[oi][:, oj], Xn[oi][:, oj]
        cs = all(a.closed for a in A)
        ct = all(b.closed for b in Gs)
        ns = n if cs else n - 1
        nt = m if ct else m - 1
        s = np.arange(ns * ds + (0 if cs else 1)) / ds
        t = np.arange(nt * dt + (0 if ct else 1)) / dt
        # Points of each curve at (s or t)
        Ls = np.zeros((m, len(s), 3))
        for i in range(m):
            knots = _knot_map(UA[i], cs, A[i].L)
            Ls[i] = A[i].at(np.interp(s, np.arange(len(knots)), knots))
        Lt = np.zeros((n, len(t), 3))
        for j in range(n):
            knots = _knot_map(UB[:, j], ct, Gs[j].L)
            Lt[j] = Gs[j].at(np.interp(t, np.arange(len(knots)), knots))
        Su = _interp1(Ls, t, ct, cubic)                     # (len t, len s, 3)
        Sv = _interp1(Lt, s, cs, cubic).transpose(1, 0, 2)  # (len t, len s, 3)
        Tx = _interp1(_interp1(Xn.transpose(1, 0, 2), s, cs, cubic)
                      .transpose(1, 0, 2), t, ct, cubic)
        S = Su + Sv - Tx
        us = s / (ns if not cs else n)
        vt = t / (nt if not ct else m)
    else:
        m = len(A)
        cs = all(a.closed for a in A)
        ct = False
        nsamp = ds * 8
        s = np.arange(nsamp + (0 if cs else 1)) / nsamp
        t = np.arange((m - 1) * dt + 1) / dt
        Ls = np.stack([a.at(s * a.L) for a in A])
        S = _interp1(Ls, t, False, cubic)
        us, vt = s, t / (m - 1)
    nt_, ns_ = S.shape[0], S.shape[1]
    V = S.reshape(-1, 3)
    faces = []
    cols = ns_ if cs else ns_ - 1
    rows = nt_ if ct else nt_ - 1
    for r in range(rows):
        r2 = (r + 1) % nt_
        for c in range(cols):
            c2 = (c + 1) % ns_
            faces.append([r * ns_ + c, r * ns_ + c2, r2 * ns_ + c2, r2 * ns_ + c])
    out = Geometry.from_mesh(V.astype(np.float32),
                             np.asarray(faces, np.int32).reshape(-1, 4))
    uu, vv = np.meshgrid(us, vt)
    out.set(POINT, "uv", np.stack([uu.ravel(), vv.ravel(), np.zeros(uu.size)],
                                  1).astype(np.float32), owned=True)
    rep.update({"rows": int(nt_), "cols": int(ns_), "closed_s": bool(cs),
                "closed_t": bool(ct)})
    return out, rep
