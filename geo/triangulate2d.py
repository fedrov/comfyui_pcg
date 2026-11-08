"""
Triangulate 2D SOP -- Delaunay / constrained Delaunay triangulation of planar point sets.

Roughly three kinds of use:

    point cloud -> faces   a mesh after scattering (terrain, initial cloth mesh, block subdivision)
    outline -> faces       fill a closed polyline loop with faces, and with **good** triangles (PolyFill makes a fan)
    concave hull           triangulation with alpha pruning, getting a "looks right" outer outline from a point cloud

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
How Delaunay is computed: paraboloid lifting, then **reusing the existing 3D convex hull**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No hand-written Bowyer-Watson, no S-hull either. It uses this equivalence:

    lift (x, y) to (x, y, x² + y²) -- i.e. onto the unit paraboloid,
    then the **triangles of the lower convex hull** projected back to the plane are exactly the Delaunay triangulation.

Why it holds: point d lying inside the circumcircle of a,b,c is equivalent to the lifted d' lying **below** the plane a'b'c'.
These two things are not "about the same", they are **the same determinant**:

    incircle(a,b,c,d) = | ax−dx  ay−dy  (a−d)² |     orient3d(a',b',c',d')
                        | bx−dx  by−dy  (b−d)² |  ≡  determinant of
                        | cx−dx  cy−dy  (c−d)² |

So the convex hull algorithm's own orientation test **is** Delaunay's empty-circumcircle test. Not an approximation,
an algebraic identity. Measured: 400 points, 781 triangles, incircle determinant computed against all points,
worst value 0.0 -- not 1e-12, an exact 0.

The benefit of this route is not just less code: `hull.convex_hull_indices` is an already tested piece,
with degenerate seeds and coplanar handling built in. Writing our own Bowyer-Watson would mean stepping into all those pits again.

Costs:
- Lifting **squares** the coordinate range. So points are first normalized to the unit box, then lifted;
  z ∈ [0, 2] and xy ∈ [0, 1] are of the same magnitude, so the hull's eps is meaningful.
  Without normalizing, an input spanning 1000 lifts to z ~ 1e6, eps follows z entirely,
  and in xy there is effectively no tolerance.
- The hull is O(n log n) but with Python dict overhead. Measured 0.66 s for 3000 points,
  good enough; tens of thousands of points get noticeably slow, at that scale Fuse to downsample first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Constrained edges (CDT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Constrained" means: this edge **must** appear in the output, even if it violates Delaunay.
The input polygon boundary is the natural constraint -- without constraints, the triangles filling a concave polygon
stick outside the polygon (Delaunay triangulates the **convex hull** and knows nothing about your outline).

Uses Anglada's cavity re-triangulation:

1. skip constrained edge (a,b) if it is already in the mesh
2. otherwise start from a, find the triangle "whose other two vertices lie on opposite sides of ab", walk along ab,
   collecting the triangles crossed and the left and right vertex chains
3. delete those triangles, giving a cavity polygon **with ab as a chord**
4. re-triangulate the upper and lower sub-polygons each by Delaunay (recursively find the vertex "with no other point in the circumcircle")

What the recursion in step 4 (Anglada's triangulatePseudopolygonDelaunay) guarantees:
the result is as Delaunay as possible **without violating constraints**. This is called "constrained Delaunay",
not "Delaunay"; the difference is that no empty-circle test is done across constrained edges.

**Pitfalls actually hit** (each has a negative control left in the tests):

- When walking triangles, "other two vertices on opposite sides" must use the **sign** of orient2d, not
  "the parameter projected onto ab lies in 0..1". The latter misses obtuse triangles near a.
- If the endpoints of a constrained edge are not points of the mesh (e.g. the constraint comes from another geometry), the result is silently wrong --
  so constrained edges are always given by **point number**, and an error is raised if one cannot be found.
- The cavity may degenerate to only 3 vertices (crossing just one triangle); the recursion must bottom out at length 3,
  not only at length 2 -- length 2 is an edge, with no triangle to build.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Inside / outside classification
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Constrained edges split the triangles into **regions** (connected across unconstrained edges, cut across constrained ones), then
BFS runs on the **region adjacency graph**: crossing a constrained edge adds 1 to the depth. Even depth is outside, odd is inside --
i.e. the even-odd fill rule.

The first version did "flood fill from the convex hull boundary; whatever is reachable is outside", which on inputs with holes
is **wrong**: the outer frame is itself a constrained edge and happens to equal the convex hull, so not a single seed is found,
`remove_outside` removes nothing, and a 4x4 with a 2x2 hole measured area 16 instead of 12.
Nesting depends on depth parity, not on "reachable or not".

More robust than "computing winding numbers": winding numbers require constrained edges forming consistently oriented closed loops, while user-given constraints are often
open chains or randomly oriented. The even-odd rule only requires constrained edges to **close into loops** to block the fill.
When they cannot block it (open chains, or an outline whose ends were not quite welded) the whole mesh is classified as outside
and removed down to nothing -- in that case it **errors explicitly** and points to Fuse, instead of silently returning empty geometry:
users have no way to guess the real cause of a "node produced no output" symptom.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
alpha pruning -- a concave hull from a point cloud
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The outer outline of a Delaunay triangulation is always the **convex hull**. For a concave shape, "too large" triangles must be deleted.
Two criteria:

    max_circumradius   delete if the circumradius exceeds the threshold -- this is the alpha shape,
                       α = 1/r. Theoretically the most orthodox.
    max_edge_length    delete if the longest edge exceeds the threshold -- more intuitive, easier to tune.

Both are "smaller threshold deletes more", and in the extreme they delete the whole mesh. So threshold 0 is interpreted as "no pruning",
not "delete everything" -- otherwise the default parameters would output empty geometry and users would just think the node is broken.
"""
import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve
from . import hull as _hull
from . import polyexpand2d as _pe

annotations = {}

PLANE_MODES = ("fit_plane", "xy", "zx", "yz", "specify_plane")
CONSTRAIN_MODES = ("none", "input_polygons", "edge_group")
REGION_MODES = ("keep_all", "remove_outside", "remove_inside",
                "remove_outside_and_inside")


# ══════════════════════════════════════════════════════════════════ plane basis
def _basis(P, mode, origin, normal, distance):
    """
    (origin, e1, e2, normal). The three axis-aligned modes are shortcuts for specify_plane --
    "XY plane" on the parameter panel is far easier to use than "set the normal to (0,0,1)".
    """
    if mode == "xy":
        return _pe.plane_basis(P, "specify_plane", origin, (0, 0, 1), distance)
    if mode == "zx":
        return _pe.plane_basis(P, "specify_plane", origin, (0, 1, 0), distance)
    if mode == "yz":
        return _pe.plane_basis(P, "specify_plane", origin, (1, 0, 0), distance)
    if mode in ("fit_plane", "specify_plane"):
        return _pe.plane_basis(P, mode, origin, normal, distance)
    raise ValueError(f"Plane must be one of {PLANE_MODES}")


def project(P, mode="fit_plane", origin=(0, 0, 0), normal=(0, 1, 0),
            distance=0.0):
    """(N,3) -> (N,2) plane coordinates, plus the basis."""
    P = np.asarray(P, np.float64).reshape(-1, 3)
    o, e1, e2, n = _basis(P, mode, origin, normal, distance)
    d = P - o
    return np.column_stack([d @ e1, d @ e2]), (o, e1, e2, n)


# ══════════════════════════════════════════════════════════════ Delaunay
HULL_TOL = 1e-12
"""
Tolerance passed to `hull.convex_hull_indices`. **Its default 1e-6 must not be used.**

The hull treats "point-to-face distance > eps" as outside, eps = tol x scale. That tolerance is reasonable for
"computing a convex hull" but disastrous for Delaunay: after lifting, a point almost co-circular with its neighbours
is only about 1e-8 from that face, so it is treated as "on the face" and swallowed -- it **disappears from the triangulation**,
with no error.

Measured over eight input kinds x 3 seeds (random, Gaussian, regular grid, jittered grid, circle, wavy outline,
wavy outline + interior scatter, two-scale clusters), with a full triangulation validity check as the criterion:

    tol=1e-6    random and regular grid pass; Gaussian has empty-circle violations; jittered grid 60 violations;
                wavy outline **boundary forks**, area differs from the hull by 5e-5;
                two-scale clusters **169 of 400 points missing**
    tol=1e-9    all eight pass
    tol=1e-12   all eight pass, same time

The time is the same because eps only affects the "outside or not" decision, not the algorithm's complexity.

There is also a **testing lesson** worth recording here: area conservation **passes** on gauss and grid_jit,
while the empty-circle criterion fails on those two. In other words a conservation check like "the pieces' areas add up"
cannot detect triangulation quality problems at all -- it only guarantees that the pieces fit without overlaps or gaps.
Testing Delaunay requires actually checking empty circumcircles.
"""


def delaunay(XY, tol=HULL_TOL):
    """
    (N,2) -> (T,3) point numbers of counter-clockwise triangles.

    Paraboloid lifting + lower convex hull. See the module notes: the hull's orientation test **is** incircle,
    so the result is exact Delaunay, not an approximation.

    Degenerate cases: fewer than 3 points, or all collinear -> returns an empty array (there are no triangles).
    Coincident points must be welded **first** -- two points with the same coordinates also coincide after lifting,
    the hull treats them as one point, and a point number goes missing from the triangulation.
    """
    XY = np.ascontiguousarray(XY, np.float64).reshape(-1, 2)
    n = len(XY)
    if n < 3:
        return np.zeros((0, 3), np.int64)

    # Normalize to the unit box. Lifting squares the coordinates; without normalizing the magnitude of z would carry off the hull's
    # eps entirely (an input spanning 1000 lifts to z ~ 1e6, and in xy there is effectively no tolerance).
    lo = XY.min(0)
    span = float((XY.max(0) - lo).max())
    if span <= 0.0:                      # all points coincide
        return np.zeros((0, 3), np.int64)
    U = (XY - lo) / span

    # Collinearity test: rank of the 2D point set. When collinear the lifted points all lie on one parabola,
    # the hull cannot build a tetrahedron and convex_hull_indices returns empty -- but catching it early
    # gives clearer semantics and saves a futile hull computation.
    C = U - U.mean(0)
    sv = np.linalg.svd(C, compute_uv=False)
    if len(sv) < 2 or sv[1] <= 1e-9 * max(sv[0], 1e-300):
        return np.zeros((0, 3), np.int64)

    Q = np.column_stack([U, (U ** 2).sum(1)])

    # ── co-circular degeneracy, must be caught first ───────────────────────────────────────────
    # When the lifted points are **coplanar** the hull cannot build a tetrahedron, and convex_hull_indices returns empty.
    # And "coplanar after lifting" is equivalent to "co-circular originally": the lifted plane z = αx+βy+γ intersected with the paraboloid
    # z = x²+y² solves x²+y² − αx − βy − γ = 0, which is a circle.
    #
    # This is not a rare case, it is the **most common** one: squares, rectangles, rhombi, any regular polygon,
    # isosceles trapezoids all have four co-circular points; with exactly 3 points they are necessarily coplanar.
    # The first version missed this, so the most basic use, "fill a square with triangles",
    # returned empty geometry outright -- while the random scatter tests were all green, because random points are not co-circular.
    #
    # The nice thing about co-circular point sets: **any** triangulation of them is Delaunay (all points lie on the same
    # circumcircle, so the empty-circle test is a boundary case, an equality, for every triangle). And co-circular means
    # every point is a hull vertex, so sorting by angle around the centroid gives the hull order; just cut it as a fan.
    svq = np.linalg.svd(Q - Q.mean(0), compute_uv=False)
    if len(svq) < 3 or svq[2] <= 1e-9 * max(svq[0], 1e-300):
        return _cocircular_fan(U)

    # Qhull for the default (exact) tolerance; an explicitly looser tolerance keeps the Python hull and its semantics
    tri = _qhull_delaunay(U) if float(tol) <= HULL_TOL else None
    if tri is not None:
        return _ccw(U, tri)
    F = _hull.convex_hull_indices(Q, tol=float(tol))
    if len(F) == 0:
        return np.zeros((0, 3), np.int64)

    # Lower shell: outward normal z < 0 after lifting. The hull gives outward normals, and the outward normals of the half
    # **below** the paraboloid point down. The upper shell projected back is a fan triangulation of the hull, not Delaunay.
    A, B, C3 = Q[F[:, 0]], Q[F[:, 1]], Q[F[:, 2]]
    nz = (np.cross(B - A, C3 - A))[:, 2]
    tri = F[nz < 0.0]
    return _ccw(U, tri)


def _qhull_delaunay(U):
    """
    scipy's Qhull Delaunay (the same lifting + lower hull, in C: ~100x the Python hull below on 20k points).

    Returns None -- and the caller uses the Python hull -- without scipy, on a Qhull error, or when Qhull left a point
    out (it reports such points as "coplanar"; the Python hull keeps every point, and the tests rely on that).
    Qz adds a point at infinity, Qhull's own guard for co-circular subsets; Qbb rescales the lifted coordinate.
    """
    try:
        from scipy.spatial import Delaunay
    except ImportError:
        return None
    try:
        d = Delaunay(U, qhull_options="Qbb Qc Qz Q12")
    except Exception:                       # QhullError (precision trouble): the exact-predicate path handles it
        return None
    if len(d.coplanar):
        return None
    return d.simplices.astype(np.int64)


def _cocircular_fan(U):
    """
    Triangulation of a co-circular point set (or exactly 3 points): sort by angle around the centroid, cut as a fan.

    Validity: any triangulation of a co-circular set is Delaunay, because all points lie **on** the same circumcircle,
    so the empty-circle test is exactly an equality for every triangle (incircle determinant = 0),
    and no point lies **inside**.

    Angular order is hull order: the centroid is necessarily inside the point set's convex hull (the centroid of any point set lies in its own hull),
    and every point of a co-circular set is a hull vertex, so sorting by polar angle around the centroid gives the hull loop.
    """
    n = len(U)
    if n < 3:
        return np.zeros((0, 3), np.int64)
    c = U.mean(0)
    order = np.argsort(np.arctan2(U[:, 1] - c[1], U[:, 0] - c[0]),
                       kind="stable")
    tri = np.stack([np.full(n - 2, order[0]), order[1:-1], order[2:]], 1)
    return _ccw(U, tri.astype(np.int64))


def _ccw(XY, tri):
    """Orient every triangle counter-clockwise. The lower shell projects back clockwise; make it uniform."""
    if len(tri) == 0:
        return np.zeros((0, 3), np.int64)
    a, b, c = XY[tri[:, 0]], XY[tri[:, 1]], XY[tri[:, 2]]
    cr = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - \
         (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    out = tri.copy()
    flip = cr < 0.0
    out[flip, 1], out[flip, 2] = tri[flip, 2], tri[flip, 1]
    return np.ascontiguousarray(out, np.int64)


# ══════════════════════════════════════════════════════════════════ half-edges
class Mesh:
    """
    Half-edge representation of a triangle mesh, following delaunator's convention:

        tri[3t+i]   point number of vertex i of triangle t
        twin[3t+i]  half-edge number of the opposite edge, -1 when there is none (boundary)

    Half-edge h = 3t+i represents the directed edge tri[h] -> tri[3t+(i+1)%3].
    dead[t] marks deleted triangles -- when inserting constraints **the arrays are not rebuilt**,
    a mark is set and use continues, compacted all at once at the end. Rebuilding the index mid-way invalidates every half-edge number,
    the easiest place to go wrong in algorithms of this kind.
    """

    __slots__ = ("XY", "tri", "twin", "dead", "cons")

    def __init__(self, XY, tri):
        self.XY = np.asarray(XY, np.float64).reshape(-1, 2)
        self.tri = [int(v) for t in np.asarray(tri).reshape(-1, 3) for v in t]
        self.dead = [False] * (len(self.tri) // 3)
        self.cons = set()                  # constrained edges, stored as (min, max) point-number pairs
        self.twin = [-1] * len(self.tri)
        self._link()

    # ── basic access ────────────────────────────────────────────────────────
    def ntri(self):
        return len(self.tri) // 3

    def _link(self):
        """Build twin by pairing directed edges. Duplicate directed edges mean the input has flipped triangles."""
        seen = {}
        for h, u in enumerate(self.tri):
            v = self.tri[3 * (h // 3) + (h % 3 + 1) % 3]
            seen[(u, v)] = h
        for h, u in enumerate(self.tri):
            v = self.tri[3 * (h // 3) + (h % 3 + 1) % 3]
            self.twin[h] = seen.get((v, u), -1)

    def edge_of(self, h):
        t, i = h // 3, h % 3
        return self.tri[3 * t + i], self.tri[3 * t + (i + 1) % 3]

    def apex(self, h):
        """The vertex opposite a half-edge."""
        t, i = h // 3, h % 3
        return self.tri[3 * t + (i + 2) % 3]

    def is_cons(self, h):
        u, v = self.edge_of(h)
        return (min(u, v), max(u, v)) in self.cons

    def mark_cons(self, u, v):
        self.cons.add((min(u, v), max(u, v)))

    def has_edge(self, u, v):
        for h in range(len(self.tri)):
            if self.dead[h // 3]:
                continue
            a, b = self.edge_of(h)
            if (a == u and b == v) or (a == v and b == u):
                return True
        return False

    # ── output ────────────────────────────────────────────────────────────
    def triangles(self):
        """Compact into (T,3)."""
        out = [self.tri[3 * t:3 * t + 3]
               for t in range(self.ntri()) if not self.dead[t]]
        return (np.asarray(out, np.int64) if out
                else np.zeros((0, 3), np.int64))

    def add_tri(self, a, b, c):
        self.tri += [int(a), int(b), int(c)]
        self.twin += [-1, -1, -1]
        self.dead.append(False)
        return self.ntri() - 1

    def relink(self):
        """Rebuild twin entirely. Called only once after a batch of additions/deletions."""
        seen = {}
        for h in range(len(self.tri)):
            if self.dead[h // 3]:
                continue
            u, v = self.edge_of(h)
            seen[(u, v)] = h
        self.twin = [-1] * len(self.tri)
        for h in range(len(self.tri)):
            if self.dead[h // 3]:
                continue
            u, v = self.edge_of(h)
            self.twin[h] = seen.get((v, u), -1)


# ══════════════════════════════════════════════════════════ geometric predicates
def _orient(XY, a, b, c):
    """> 0 = c is to the left of ab (counter-clockwise)."""
    ax, ay = XY[a]
    bx, by = XY[b]
    cx, cy = XY[c]
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _in_circle(XY, a, b, c, d):
    """
    > 0 = d is **inside** the circumcircle of abc (counter-clockwise).
    Uses exactly the lifting determinant, the same test as the delaunay() kernel.
    """
    ax, ay = XY[a] - XY[d]
    bx, by = XY[b] - XY[d]
    cx, cy = XY[c] - XY[d]
    return (ax * ax + ay * ay) * (bx * cy - by * cx) \
        - (bx * bx + by * by) * (ax * cy - ay * cx) \
        + (cx * cx + cy * cy) * (ax * by - ay * bx)


# ══════════════════════════════════════════════════════ constrained edge insertion
def _walk(m, a, b):
    """
    Walk from a along ab to b, returning the triangle numbers crossed and the vertex loop of the cavity polygon.

    The loop order is: a, (left chain), b, (right chain reversed) -- i.e. one loop with ab as a chord.
    If the walk fails (hits a constrained edge or gets lost) returns None, and the caller raises the error.
    """
    XY = m.XY
    # start: find a triangle with a as a vertex, out of whose interior ab exits
    start = None
    for h in range(len(m.tri)):
        if m.dead[h // 3] or m.tri[h] != a:
            continue
        t, i = h // 3, h % 3
        u = m.tri[3 * t + (i + 1) % 3]
        v = m.tri[3 * t + (i + 2) % 3]
        if u == b or v == b:
            return [], None             # the edge is already in the mesh
        # "on opposite sides" must use the sign of orient, not the projection parameter -- see the module notes
        if _orient(XY, a, b, u) < 0.0 and _orient(XY, a, b, v) > 0.0:
            start = 3 * t + (i + 1) % 3   # directed edge u->v, the one to cross
            break
    if start is None:
        return None, None

    crossed = [start // 3]
    left = [m.tri[start]]                                  # u, to the right of ab
    right = [m.tri[3 * (start // 3) + (start % 3 + 1) % 3]]  # v, to the left
    h = m.twin[start]
    guard = 0
    while True:
        guard += 1
        if h < 0 or guard > 4 * m.ntri() + 16:
            return None, None
        t = h // 3
        crossed.append(t)
        ap = m.apex(h)
        if ap == b:
            break
        if ap == a:
            # walked back to the start -- meaning the exit-edge rule is wrong, not the input.
            # This defensive check stays, because the first version went wrong exactly here (see below),
            # and the symptom was a "constrained edge cannot be inserted" error that points nowhere near the real cause.
            return None, None
        o = _orient(XY, a, b, ap)
        #
        # Choose the exit edge. The incoming half-edge h represents the directed edge (tri[h] -> tri[h+1]),
        # the triangle is (tri[h], tri[h+1], tri[h+2]) counter-clockwise, apex = tri[h+2].
        # The incoming edge crossed line ab, so tri[h] and tri[h+1] are one left and one right;
        # specifically tri[h] is on the **left** and tri[h+1] on the **right** (in the source triangle it was "right->left",
        # reversed by the twin). The exit edge must also cross ab, so:
        #
        #     apex on the left  -> exit is (tri[h+1], tri[h+2]) = right->left   i.e. (h%3+1)
        #     apex on the right -> exit is (tri[h+2], tri[h])   = right->left   i.e. (h%3+2)
        #
        # The first version had these two branches **swapped**, picking the edge that does **not** cross ab.
        # The result was drifting: in dense point clouds it would loop back to start a after a few steps, or run into an unrelated
        # constrained edge, then report "constrained edge cannot be inserted".
        #
        # Why simple cases do not catch it: in L shapes, stars, framed boxes with holes, the constrained edges are almost all
        # **already in the Delaunay mesh** (early exit), or the cavity crosses only one triangle
        # (reaches b in one step, with no chance to drift). Only "a long constrained edge cutting across a dense point cloud"
        # reproduces it reliably -- the tests include exactly this construction (a diagonal cut across a jittered grid).
        if o > 0.0:                       # apex on the left
            right.append(ap)
            nh = 3 * t + (h % 3 + 1) % 3
        else:                             # apex on the right
            left.append(ap)
            nh = 3 * t + (h % 3 + 2) % 3
        if m.is_cons(nh):
            return None, None             # two constrained edges cross, not handled
        h = m.twin[nh]

    ring = [a] + left + [b] + right[::-1]
    return crossed, ring


def _retri(m, poly, out):
    """
    Anglada's pseudo-polygon Delaunay re-triangulation.

    poly is a **chain** (its ends are the two ends of the chord). Among the interior vertices pick a c
    such that the circumcircle of poly[0], poly[-1], c contains no other point of the chain, then recurse left and right.

    Bottoms out at len == 3 (one triangle). len == 2 is an edge with no triangle to build --
    the first version bottomed out at 2, and dropped that triangle when the cavity crossed only one triangle.

    **The argument order of in_circle is the nastiest pitfall here**. poly is a CCW polygon chain,
    so the emitted triangle (a, poly[k], b) is counter-clockwise; but the first version checked the empty circle with
    `_in_circle(XY, a, b, poly[best], ...)` -- swapping the middle two vertices,
    passing the same triangle **clockwise**, flipping the sign of the whole incircle determinant,
    so "pick the vertex whose circumcircle is emptiest" became "pick the least empty one".

    The result is not "slightly lower quality": picking the wrong vertex in a concave cavity cuts triangles **sticking outside the cavity**,
    duplicating directed edges and scrambling twin pairing, so inserting the next constrained edge gets lost while walking triangles,
    and what gets reported is an error like "constrained edge cannot be inserted" that does not reveal the real cause.

    Even more insidious, **area conservation cannot detect this bug** -- whichever vertex is picked, the total area of the pieces
    is right. Only actually checking the empty-circle criterion reveals it. So the tests specifically include:
    for every unconstrained edge, check that its two opposite vertices do not lie in each other's circumcircle.
    """
    n = len(poly)
    if n < 3:
        return
    if n == 3:
        out.append((poly[0], poly[1], poly[2]))
        return
    a, b = poly[0], poly[-1]
    best = 1
    for k in range(2, n - 1):
        # (a, poly[best], b) is the counter-clockwise order
        if _in_circle(m.XY, a, poly[best], b, poly[k]) > 0.0:
            best = k
    out.append((a, poly[best], b))
    _retri(m, poly[:best + 1], out)
    _retri(m, poly[best:], out)


def insert_constraint(m, a, b):
    """Insert constrained edge (a,b) into the mesh. Returns True if anything was cut."""
    a, b = int(a), int(b)
    if a == b:
        return False
    crossed, ring = _walk(m, a, b)
    if crossed is None:
        raise ValueError(
            f"Constrained edge ({a}, {b}) cannot be inserted -- either two constrained edges cross, "
            f"or a third point lies exactly on this edge.\n"
            f"  For the former: connect a Fuse (PCG) first, or break the intersecting outlines yourself;\n"
            f"  for the latter: make that point part of the constraint chain too.")
    if ring is None:
        m.mark_cons(a, b)
        return False                      # already there

    for t in crossed:
        m.dead[t] = True
    # ring is a loop, a..b is the chord. Split into two chains and re-triangulate each.
    i = ring.index(b)
    fresh = []
    _retri(m, ring[:i + 1], fresh)                    # the a -> b side
    _retri(m, ring[i:] + [ring[0]], fresh)            # the b -> a side
    for (p, q, r) in fresh:
        if abs(_orient(m.XY, p, q, r)) > 0.0:         # drop degenerate ones
            m.add_tri(p, q, r)
    m.relink()
    m.mark_cons(a, b)
    return True


# ══════════════════════════════════════════════════════════ regions / pruning
def regions(m):
    """
    (T,) region number (-1 for dead triangles), plus the number of regions.

    A "region" is a connected piece of the triangle adjacency graph, **cut across constrained edges**.
    """
    nt = m.ntri()
    reg = np.full(nt, -1, np.int64)
    k = 0
    for s in range(nt):
        if m.dead[s] or reg[s] >= 0:
            continue
        reg[s] = k
        stack = [s]
        while stack:
            t = stack.pop()
            for i in range(3):
                h = 3 * t + i
                if m.is_cons(h):
                    continue
                o = m.twin[h]
                if o < 0:
                    continue
                ot = o // 3
                if not m.dead[ot] and reg[ot] < 0:
                    reg[ot] = k
                    stack.append(ot)
        k += 1
    return reg, k


def region_depths(m, reg, nreg):
    """
    (nreg,) **nesting depth** of each region. Even is outside, odd inside -- the even-odd fill rule.

    The first version used "flood fill from the convex hull boundary; whatever is reachable is outside",
    which is **wrong** on inputs with holes: the outer frame is itself a constrained edge and happens to equal the convex hull,
    so not a single seed is found, `remove_outside` removes nothing,
    and a 4x4 with a 2x2 hole measured area 16 instead of 12.

    The right way is BFS on the **region adjacency graph**, adding 1 to the depth for each constrained edge crossed:

        the virtual "infinity" has depth 0
        touching the hull, and that edge is **not** constrained  -> connected to the outside, depth 0
        touching the hull, and that edge **is** constrained      -> already crossed one, depth 1

    Checking a few cases:
        L shape        the hull's diagonal edge is not constrained -> notch region depth 0 (outside), L interior 1 (inside)
        framed hole    outer frame is constrained and is the hull -> annulus depth 1 (inside), hole depth 2 (outside)
        frame+scatter  same as above -> interior depth 1 (inside)
    """
    depth = np.full(nreg, -1, np.int64)
    dq = []
    for h in range(len(m.tri)):
        t = h // 3
        if m.dead[t] or m.twin[h] >= 0:
            continue                      # only half-edges on the hull
        r = int(reg[t])
        d = 1 if m.is_cons(h) else 0
        if depth[r] < 0 or d < depth[r]:
            depth[r] = d
            dq.append(r)
    # push inward layer by layer across constrained edges
    adj = {}
    for h in range(len(m.tri)):
        t = h // 3
        if m.dead[t] or not m.is_cons(h):
            continue
        o = m.twin[h]
        if o < 0:
            continue
        ot = o // 3
        if m.dead[ot]:
            continue
        a, b = int(reg[t]), int(reg[ot])
        if a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    dq = [r for r in dq if depth[r] >= 0]
    while dq:
        nxt = []
        for r in dq:
            for s in adj.get(r, ()):
                if depth[s] < 0:
                    depth[s] = depth[r] + 1
                    nxt.append(s)
        dq = nxt
    depth[depth < 0] = 0                  # isolated regions (should not happen) count as outside
    return depth


def flood_outside(m):
    """(T,) bool: which triangles are **outside** the constraint loops (even nesting depth)."""
    reg, nreg = regions(m)
    if nreg == 0:
        return np.zeros(m.ntri(), bool)
    d = region_depths(m, reg, nreg)
    out = np.zeros(m.ntri(), bool)
    live = reg >= 0
    out[live] = (d[reg[live]] % 2) == 0
    return out


def circumradii(XY, tri):
    """(T,) circumradius. Degenerate triangles get inf."""
    if len(tri) == 0:
        return np.zeros(0, np.float64)
    a, b, c = XY[tri[:, 0]], XY[tri[:, 1]], XY[tri[:, 2]]
    la = np.linalg.norm(b - c, axis=1)
    lb = np.linalg.norm(c - a, axis=1)
    lc = np.linalg.norm(a - b, axis=1)
    cr = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    area = 0.5 * cr
    out = np.full(len(tri), np.inf)
    ok = area > 1e-300
    out[ok] = (la[ok] * lb[ok] * lc[ok]) / (4.0 * area[ok])
    return out


def max_edges(XY, tri):
    """(T,) the longest edge of each triangle."""
    if len(tri) == 0:
        return np.zeros(0, np.float64)
    a, b, c = XY[tri[:, 0]], XY[tri[:, 1]], XY[tri[:, 2]]
    return np.maximum.reduce([np.linalg.norm(b - a, axis=1),
                              np.linalg.norm(c - b, axis=1),
                              np.linalg.norm(a - c, axis=1)])


# ══════════════════════════════════════════════════════════════════ main entry
def triangulate2d(geo, group="", plane="fit_plane", plane_origin=(0, 0, 0),
                  plane_normal=(0, 1, 0), plane_distance=0.0,
                  constrain="input_polygons", constrain_group="",
                  region="remove_outside", max_circumradius=0.0,
                  max_edge_length=0.0, fuse_tol=1e-6, hull_tol=HULL_TOL,
                  keep_input=False, border_group="", constrained_group="",
                  on_failure="fail_with_error"):
    """
    Planar Delaunay / constrained Delaunay triangulation.

    The parameters roughly match Houdini's Triangulate 2D, but are **not** copied item by item:
    here the "constraint source" is an enum (none / input polygons / edge group),
    where Houdini has a toggle plus a group; alpha pruning offers circumradius and longest edge.

    Region handling:
        keep_all                    no removal, output the triangulation of the whole convex hull
        remove_outside              keep only inside the constraint loops -- use this to fill outlines
        remove_inside               keep only outside the constraint loops -- use this to cut holes
        remove_outside_and_inside   remove both, leaving basically just one layer along the constrained edges

    Threshold 0 always means "no pruning". 0 is not "delete everything" -- otherwise default parameters output empty geometry,
    and users would just think the node is broken.
    """
    if geo is None or geo.npoints == 0:
        return geo.copy() if geo is not None else None
    if plane not in PLANE_MODES:
        raise ValueError(f"Plane must be one of {PLANE_MODES}")
    if constrain not in CONSTRAIN_MODES:
        raise ValueError(f"Constrain must be one of {CONSTRAIN_MODES}")
    if region not in REGION_MODES:
        raise ValueError(f"Region must be one of {REGION_MODES}")

    P = np.asarray(geo.get(POINT, "P"), np.float64).reshape(-1, 3)
    sel = resolve(geo, POINT, group) if group else np.ones(len(P), bool)
    idx = np.nonzero(sel)[0]
    if len(idx) < 3:
        if on_failure == "fail_with_error":
            raise ValueError(
                f"Only {len(idx)} points take part in the triangulation, at least 3 are needed. "
                f"{'Group filtered out the points; ' if group else ''}check the input.")
        return geo.copy()

    XY, basis = project(P[idx], plane, plane_origin, plane_normal,
                        plane_distance)

    # Coincident points must be merged first: points with the same coordinates also coincide after lifting, the hull treats them as one point,
    # and a point number goes **silently** missing from the triangulation.
    #
    # Even with Fuse Tolerance = 0 **exactly coincident points are still merged**.
    # This is not optional: two exactly coincident points admit no triangulation at all, and without merging
    # the hull spits out degenerate faces. Measured: 5 points (two pairs exactly coincident, only 3 distinct positions)
    # at tol=0 gave **3** triangles -- 3 distinct points can have at most 1.
    # So tol<=0 is interpreted as "merge only exact coincidences", not "merge nothing".
    if float(fuse_tol) > 0.0:
        node, _ = _pe.weld(XY, float(fuse_tol))
    else:
        _, node = np.unique(XY, axis=0, return_inverse=True)
        node = np.asarray(node, np.int64).reshape(-1)
    reps = np.full(node.max() + 1 if len(node) else 0, -1, np.int64)
    for k in range(len(node) - 1, -1, -1):
        reps[node[k]] = k                 # pick one representative per node (the smallest k)
    NXY = XY[reps]

    tri = delaunay(NXY, tol=float(hull_tol))
    if len(tri) == 0:
        if on_failure == "fail_with_error":
            span = float((XY.max(0) - XY.min(0)).max()) if len(XY) else 0.0
            # Fuse Tolerance is an **absolute** length. An input whose overall size is only 1e-6
            # meeting the default 1e-6 gets welded into one point, then reports "collinear" -- the symptom is identical to real
            # collinearity, but the cause is completely different. So this case is spelled out separately first.
            if len(NXY) < 3 <= len(idx):
                raise ValueError(
                    f"Fuse Tolerance welded {len(idx)} points into {len(NXY)}, "
                    f"not enough points left to triangulate.\n"
                    f"  Fuse Tolerance is an **absolute** length (currently {fuse_tol:g}), "
                    f"while this input's overall size on the projection plane is only {span:g}.\n"
                    f"  Decrease Fuse Tolerance (e.g. {span * 1e-4:g}), "
                    f"or scale the geometry up to a normal size first.")
            raise ValueError(
                "No triangles could be produced -- the participating points are collinear on the projection plane (or all coincide).\n"
                "  Collinear points have no 2D triangulation. Check that Plane is set correctly: "
                "a grid on the XZ plane projected onto the XY plane is a line.\n"
                f"  (points in the triangulation: {len(idx)}, after welding {len(NXY)}, "
                f"size on the plane {span:g})")
        return geo.copy()

    m = Mesh(NXY, tri)

    # ── constrained edges ────────────────────────────────────────────────────────
    cons_pairs = []
    if constrain == "input_polygons":
        for p in range(geo.nprims):
            vs = geo.prim_points(p)
            if len(vs) < 2:
                continue
            closed = bool(geo.prim_closed[p])
            seq = list(vs) + ([int(vs[0])] if closed else [])
            for u, v in zip(seq[:-1], seq[1:]):
                cons_pairs.append((int(u), int(v)))
    elif constrain == "edge_group":
        eg = geo.edge_groups.get(constrain_group)
        if eg is None:
            raise ValueError(
                f"No edge group named {constrain_group!r}. "
                f"Existing: {sorted(geo.edge_groups)}")
        cons_pairs = [(int(u), int(v)) for u, v in np.asarray(eg).reshape(-1, 2)]

    # point numbers must be mapped from the original geometry to the node numbers taking part in the triangulation
    g2n = np.full(len(P), -1, np.int64)
    g2n[idx] = node
    ins = set()
    for (u, v) in cons_pairs:
        if not (0 <= u < len(P) and 0 <= v < len(P)):
            continue
        a, b = int(g2n[u]), int(g2n[v])
        if a < 0 or b < 0 or a == b:
            continue                      # endpoint not in the triangulation, or welded into one point
        ins.add((min(a, b), max(a, b)))
    for (a, b) in sorted(ins):
        insert_constraint(m, a, b)

    # ── region removal ──────────────────────────────────────────────────────
    keep_t = np.ones(m.ntri(), bool)
    keep_t[np.asarray(m.dead, bool)] = False
    if m.cons and region != "keep_all":
        outside = flood_outside(m)
        if region in ("remove_outside", "remove_outside_and_inside"):
            keep_t &= ~outside
        if region in ("remove_inside", "remove_outside_and_inside"):
            keep_t &= outside
        # None left means the constrained edges **do not form a closed loop** -- open chains cannot block the flood fill,
        # so the whole mesh counts as "outside" and remove_outside removes all of it.
        # Silently returning empty geometry here is the worst handling: the user sees "the node produced no output"
        # with no way to guess the outline has a gap. So report it explicitly.
        # Only checked for remove_outside. remove_inside should be empty anyway when "the constraint is the hull boundary"
        # (there are no triangles outside); remove_outside_and_inside removes both ends,
        # so empty is the **expected result**, not an error.
        if not keep_t.any() and region == "remove_outside":
            if on_failure == "fail_with_error":
                raise ValueError(
                    "Not a single triangle left after removal -- the constrained edges do not form a closed loop, "
                    "so they cannot separate inside from outside, and the whole mesh was treated as outside.\n"
                    "  Common causes: the outline is open (the polyline is not closed), "
                    "or some points on the outline are not welded (the two ends miss each other by a hair).\n"
                    "  Fix: connect a Fuse (PCG) to weld them, "
                    "or set Region to Keep All first to check that the triangulation itself is right.")
            keep_t = ~np.asarray(m.dead, bool)

    T = np.asarray([m.tri[3 * t:3 * t + 3]
                    for t in range(m.ntri()) if keep_t[t]], np.int64) \
        if keep_t.any() else np.zeros((0, 3), np.int64)

    # ── alpha pruning ────────────────────────────────────────────────────
    if len(T):
        mask = np.ones(len(T), bool)
        if float(max_circumradius) > 0.0:
            mask &= circumradii(NXY, T) <= float(max_circumradius)
        if float(max_edge_length) > 0.0:
            mask &= max_edges(NXY, T) <= float(max_edge_length)
        T = T[mask]

    return _assemble(geo, idx, reps, T, m, keep_input, border_group,
                     constrained_group)


def _assemble(geo, idx, reps, T, m, keep_input, border_group,
              constrained_group):
    """
    Assemble the output geometry from the triangulation.

    The points are **the original points** (the nodes' representatives), with point numbers untouched, so point attributes and point groups
    carry over as is -- triangulation creates no new points, its biggest difference from nodes like Fracture.

    Vertex attributes are **not carried over**: output vertices have no correspondence with input vertices
    (the triangles are newly assembled), and copying by index would just produce a pile of wrong values. Same for prim attributes.
    This is stated explicitly in the README; it is not an omission.
    """
    n2g = idx[reps] if len(reps) else np.zeros(0, np.int64)
    faces = [list(map(int, f)) for f in (n2g[T] if len(T) else [])]
    if keep_input:
        faces = [list(geo.prim_points(p)) for p in range(geo.nprims)] + faces

    out = Geometry()
    out._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v, owned=True)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])

    if faces:
        sz = np.array([len(f) for f in faces], np.int32)
        out.set_topology(
            np.concatenate([np.asarray(f, np.int32) for f in faces]),
            np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
            np.ones(len(faces), bool))
    else:
        out.set_topology(np.zeros(0, np.int32), np.zeros(1, np.int32),
                         np.zeros(0, bool))
    out.edge_groups = dict(geo.edge_groups)

    if border_group:
        # boundary edges: those used by only one output triangle. Handy for feeding PolyExpand2D
        # or Group Edges.
        ek = {}
        for f in faces:
            for j in range(len(f)):
                u, v = f[j], f[(j + 1) % len(f)]
                k = (min(u, v), max(u, v))
                ek[k] = ek.get(k, 0) + 1
        bd = [k for k, c in ek.items() if c == 1]
        out.set_edge_group(border_group,
                           np.asarray(bd, np.int64).reshape(-1, 2))
    if constrained_group:
        cg = [(int(n2g[a]), int(n2g[b])) for (a, b) in sorted(m.cons)
              if a < len(n2g) and b < len(n2g)]
        out.set_edge_group(constrained_group,
                           np.asarray(cg, np.int64).reshape(-1, 2))
    return out
