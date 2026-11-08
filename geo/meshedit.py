"""
pcg74: mesh editing -- edge chain cleanup (Edge Equalize / Edge Straighten / Circle from Edges),
Edge Flip, Rewire Vertices, PolyCut, PolyStitch, Tri Divide.
(Unsubdivide is in unsubdivide.py, Voronoi Split in voronoisplit.py.)

━━ Edge chains
An edge group (point pairs) is first chained up: points whose degree isn't 2 (endpoints, branch points) split the chains. Three kinds of chain:
  open chain             both ends are endpoints or branch points; both ends stay fixed
  pure closed loop       every point has degree 2 (e.g. a ring of edges on a cylinder)
  loop through a branch  starts at a branch point and comes back to the same branch point -- treated as a closed loop, but that branch point is pinned
Chains only move **point positions**; topology is never changed; surrounding primitives follow the points.

━━ Edge Equalize
Points are redistributed along **the original polyline**; the shape (that polyline) doesn't change:
  arc_length  every segment has equal arc length along the original polyline (direct interpolation, done in one step)
  chord       every segment has equal **straight-line distance** (chord length. Where it bends, arc length and chord differ; bisect on c,
              from the start each step finds the first point on the polyline "exactly c from the previous point"; after n steps it lands exactly on the end)
A pure closed loop has no natural starting point: the phase of the whole ring is chosen as the one "minimizing the total arc length all points move" (the mean),
rather than pinning some arbitrary point -- the result doesn't depend on point numbering.

━━ Edge Straighten
The endpoints of an open chain stay fixed; the middle points are placed on the line between the two endpoints. spacing: preserve (by original arc-length ratio, point
order unchanged) / uniform (equal division) / project (perpendicular projection onto the line; bends far from the line can reverse point
order -- as in Houdini, this mode is meant for chains that are "roughly straight already"). Closed loops can't be straightened; they're skipped and
reported.

━━ Circle from Edges
Each closed loop is laid out as a perfect circle: center = mean of the points, plane = the loop's Newell normal (stable for non-planar loops too; the direction
follows the loop's winding -- point order is preserved on the circle), radius average / min / max / custom.
With even_spacing on, points are distributed at equal angles, and the phase of the whole ring is the one "minimizing the sum of squared point movements" (= the circular mean angle
weighted by each point's radius, an analytic solution); with it off, each point keeps its own azimuth in the plane and just moves onto the circle. Open chains are skipped and reported.

━━ Edge Flip
rotate: the two primitives sharing an edge form one big loop, and the edge rotates around the loop by cycles steps -- for two triangles that's the
classic diagonal flip, for two quads it's the quad "edge rotation" (same behaviour as Houdini's Edge Flip). The primitives'
edge counts don't change. Skipped and counted: the new edge already exists (would pinch a duplicate edge), the two primitives' windings disagree, or the edge isn't shared by exactly two primitives.
Within one batch a primitive is flipped only once (first come first served in edge order).
delaunay: only edges with triangles on both sides; flip if the opposite angles sum to > 180 deg (Lawson), until nothing more can be flipped.
Edges where the two primitives' dihedral angle exceeds max_angle aren't flipped (that would change the shape). Opposite angles summing to > 180 deg itself guarantees the quad is convex,
so flipping won't fold (see the note in _delaunay_ok).
Flipped edges are written back to the edge group of the same name (new diagonals replace the old).

━━ Rewire Vertices
Rewire each vertex to the point number given by an integer attribute (vertex first, else the point attribute);
-1 / out of range are left alone. Optionally remove the resulting consecutive duplicate corners and degenerate primitives, and delete unused points.

━━ PolyCut
Walk once around each primitive / polyline along its edges and cut into polylines by one of three rules:
  cut_points   break at points in the point group
  keep_points  keep only edges whose two ends are both in the point group
  threshold    insert a point where a point attribute (first component) crosses the threshold along an edge (attributes linearly interpolated;
               on an edge shared by two adjacent primitives the same point is inserted), keep = all (only break at the threshold) /
               above / below (keep only that side). Points exactly at the threshold count for both sides, and also break
Closed primitives not broken anywhere are kept as is (still primitives); everything else is output as open polylines.

━━ PolyStitch
Two patches of different resolution put together have T-junctions (points on one side lying in the middle of the other side's edges) and thin gaps at the seam:
  1 boundary points within tolerance of each other are welded into one (position averaged)
  2 with snap on, remaining boundary points within tolerance of another's boundary edge are moved onto that edge
  3 other boundary points lying on each boundary edge are inserted in order into that edge's primitive (the primitive gains corners)
Afterwards the edges on both sides of the seam are the same run of points -- manifold, watertight. vertex attributes are interpolated along the edge at inserted points.

━━ Tri Divide
Selected primitives are triangulated first, then subdivided by "longest-edge bisection" (Rivara's LEPP): any triangle whose edge exceeds
max_edge_length or whose area exceeds max_area follows the "longest-edge propagation path" to the terminal edge (the longest edge shared by
the triangles on both sides) and is split at its midpoint -- both sides split together, so the mesh always stays conforming (no T-junctions); only the longest edge is bisected,
so the minimum angle doesn't keep getting worse (Rivara proved a lower bound). Midpoints lie on the original edges, so the surface shape doesn't change at all.
Unselected primitives aren't subdivided, but the midpoints of split edges are inserted into them (they gain a corner, so no cracks).
With delaunay on, Lawson edge flipping is done last (only on edges with both sides selected and dihedral angle <= flip_angle).
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .groups import resolve, resolve_edges, edge_mask
from .topology import topology

EQUALIZE_MEASURES = ("arc_length", "chord")
STRAIGHTEN_SPACING = ("preserve", "uniform", "project")
RADIUS_MODES = ("average", "min", "max", "custom")
FLIP_MODES = ("rotate", "delaunay")
# the last two are Houdini PolyCut's Strategy (Remove / Cut), added in pcg100; the first three are this plugin's originals
CUT_MODES = ("cut_points", "keep_points", "threshold", "remove", "cut")
CUT_TYPES = ("points", "edges")
CUT_DETECT = ("crossing", "change")
CUT_KEEP = ("all", "above", "below")


# ═══════════════════════════════════════════════════════════ weighted rebuild
class _Build:
    """
    New geometry = original points kept as is + appended new points (weighted sums of original points) + new primitives (each corner a weighted sum of
    original corners). Float attributes are interpolated by weight, integer / string ones take the source with the largest weight; a point is in a point group only if all its sources
    are; prim attributes / groups come from the source prim. Several nodes are of the "cut / insert points / reconnect" kind;
    they share this one route so the interpolation rules are written only once.
    """

    def __init__(self, geo):
        self.geo = geo
        self.n0 = geo.npoints
        self.np = geo.npoints
        self.pr, self.ps, self.pw = [], [], []
        self.faces, self.fsrc, self.fclosed = [], [], []
        self.cr, self.cs, self.cw = [], [], []
        self.nc = 0
        self.P = None                 # optional: override the output P (float64)
        self.src = {}                 # new point -> (source points, weights)

    def add_point(self, src, w):
        i = self.np
        self.np += 1
        self.pr.extend([i] * len(src))
        self.ps.extend(int(s) for s in src)
        self.pw.extend(float(x) for x in w)
        self.src[i] = (list(src), list(w))
        return i

    def copy_point(self, p):
        """Duplicate a point (original or new); returns the new point number."""
        if p < self.n0:
            return self.add_point([p], [1.0])
        return self.add_point(*self.src[p])

    def add_face(self, pts, corners, src_prim, closed=True):
        for c in corners:
            if isinstance(c, (int, np.integer)):
                ids, ws = (int(c),), (1.0,)
            else:
                ids, ws = c
            self.cr.extend([self.nc] * len(ids))
            self.cs.extend(int(s) for s in ids)
            self.cw.extend(float(x) for x in ws)
            self.nc += 1
        self.faces.append([int(p) for p in pts])
        self.fsrc.append(int(src_prim))
        self.fclosed.append(bool(closed))

    @staticmethod
    def _dominant(r, s, w, n):
        if not n:
            return np.zeros(0, np.int64)
        o = np.lexsort((-w, r))
        first = o[np.r_[True, r[o][1:] != r[o][:-1]]]
        return s[first]

    @staticmethod
    def _interp(v, r, s, w, n, dom):
        if is_string(v) or v.dtype.kind in "iub":
            return v[dom]
        acc = np.zeros((n, v.shape[1]))
        np.add.at(acc, r, np.asarray(v, np.float64)[s] * w[:, None])
        return acc.astype(v.dtype)

    def geometry(self, sort=True):
        g = self.geo
        n0, n = self.n0, self.np
        nn = n - n0
        pr = np.asarray(self.pr, np.int64) - n0
        ps = np.asarray(self.ps, np.int64)
        pw = np.asarray(self.pw, np.float64)
        dom = self._dominant(pr, ps, pw, nn)
        out = Geometry()
        out._resize_points(n)
        for k, v in g.attribs[POINT].items():
            new = self._interp(v, pr, ps, pw, nn, dom)
            out.set(POINT, k, np.concatenate([v, new]) if nn else v.copy(),
                    owned=True)
        if self.P is not None:
            dt = g.get(POINT, "P").dtype if g.has(POINT, "P") else np.float32
            out.set(POINT, "P", np.asarray(self.P).astype(dt), owned=True)
        for k, m in g.groups[POINT].items():
            allin = np.ones(nn, bool)
            live = pw > 0
            np.logical_and.at(allin, pr[live], np.asarray(m)[ps[live]])
            out.set_group(POINT, k, np.r_[m, allin])

        nf = len(self.faces)
        sizes = np.array([len(f) for f in self.faces], np.int64)
        fsrc = np.asarray(self.fsrc, np.int64)
        order = (np.argsort(fsrc, kind="stable") if sort
                 else np.arange(nf))
        cstart = np.concatenate([[0], np.cumsum(sizes)])
        corner_order = (np.concatenate([np.arange(cstart[i], cstart[i + 1])
                                        for i in order])
                        if nf else np.zeros(0, np.int64))
        vp = (np.concatenate([np.asarray(self.faces[i], np.int64)
                              for i in order]) if nf
              else np.zeros(0, np.int64))
        off = np.concatenate([[0], np.cumsum(sizes[order])]).astype(np.int32)
        sp = fsrc[order]
        out.set_topology(vp.astype(np.int32), off,
                         np.asarray(self.fclosed, bool)[order] if nf
                         else np.zeros(0, bool),
                         g.prim_type[sp] if nf else np.zeros(0, np.uint8))
        cr = np.asarray(self.cr, np.int64)
        cs = np.asarray(self.cs, np.int64)
        cw = np.asarray(self.cw, np.float64)
        cdom = self._dominant(cr, cs, cw, self.nc)
        for k, v in g.attribs[VERTEX].items():
            vals = self._interp(v, cr, cs, cw, self.nc, cdom)
            out.set(VERTEX, k, vals[corner_order], owned=True)
        for k, m in g.groups[VERTEX].items():
            out.set_group(VERTEX, k, np.asarray(m)[cdom][corner_order])
        for k, v in g.attribs[PRIM].items():
            out.set(PRIM, k, v[sp], owned=True)
        for k, m in g.groups[PRIM].items():
            out.set_group(PRIM, k, np.asarray(m)[sp])
        out.prim_data = g.remap_prim_data(sp) if nf else {}
        out.attribs[DETAIL] = dict(g.attribs[DETAIL])
        _keep_edge_groups(g, out)
        return out


def _is_edge(g, pairs):
    """Whether each point pair is an edge in g."""
    pairs = np.asarray(pairs, np.int64).reshape(-1, 2)
    t = topology(g)
    if not len(pairs) or not t.nedges:
        return np.zeros(len(pairs), bool)
    n = g.npoints + 1
    key = np.sort(t.edge_points.astype(np.int64), axis=1)
    k = np.sort(key[:, 0] * n + key[:, 1])
    q = np.sort(pairs, axis=1)
    qk = q[:, 0] * n + q[:, 1]
    pos = np.clip(np.searchsorted(k, qk), 0, len(k) - 1)
    return k[pos] == qk


def _keep_edge_groups(src, out):
    """Edge groups: point numbers carry over; keep only the point pairs that are still edges in the output."""
    for k, v in src.edge_groups.items():
        v = np.asarray(v)
        if not len(v):
            out.set_edge_group(k, v)
            continue
        v = v[(v < out.npoints).all(1)]
        out.set_edge_group(k, v[_is_edge(out, v)] if len(v) else v)


def _P(geo):
    return (np.asarray(geo.get(POINT, "P"), np.float64) if geo.npoints
            else np.zeros((0, 3)))


def _with_P(geo, P):
    g = geo.copy()
    if geo.npoints:
        g.set(POINT, "P", P.astype(geo.get(POINT, "P").dtype), owned=True)
    return g


# ═══════════════════════════════════════════════════════════ edge chains
def _chains(geo, edges, what):
    """Edge group -> [(point list, closed?, start pinned?)]."""
    from .convertline import _paths
    spec = str(edges).strip()
    if not spec:
        raise ValueError(f"{what}: Edges is empty -- enter an edge group name (Group Create's "
                         "edges section, Group Find Path and Group Edges can all make one)")
    pairs = resolve_edges(geo, spec)
    if not len(pairs):
        return []
    t = topology(geo)
    pairs = np.asarray(t.edge_points[edge_mask(geo, pairs)], np.int64)
    out = []
    for pts, closed in _paths(pairs, geo.npoints, True):
        pts = [int(p) for p in pts]
        if not closed and len(pts) > 3 and pts[0] == pts[-1]:
            out.append((pts[:-1], True, True))
        else:
            out.append((pts, bool(closed), False))
    return out


def _arc(X):
    seg = np.linalg.norm(np.diff(X, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def _at(X, s, u):
    """Point at arc length u on the polyline (u may be an array)."""
    u = np.asarray(u, np.float64)
    return np.stack([np.interp(u, s, X[:, c]) for c in range(3)], -1)


def _chord_step(X, s, u, c):
    """Starting from the point at arc length u, search forward along the polyline for the first point exactly c away; return its arc length."""
    q = _at(X, s, u)
    k = int(np.searchsorted(s, u, side="right")) - 1
    k = max(0, min(k, len(X) - 2))
    for j in range(k, len(X) - 1):
        A, B = X[j], X[j + 1]
        d = B - A
        L2 = float(d @ d)
        if L2 <= 0:
            continue
        t0 = (u - s[j]) / (s[j + 1] - s[j]) if j == k else 0.0
        f = A - q
        b = float(f @ d)
        cc = float(f @ f) - c * c
        disc = b * b - L2 * cc
        if disc < 0:
            continue
        t = (-b + math.sqrt(disc)) / L2          # the root exiting from inside the circle outward
        if t0 - 1e-12 <= t <= 1.0:
            return s[j] + t * (s[j + 1] - s[j])
    return math.inf


def _equal_chords(X, s, u0, u1, n):
    """Place n equal-length chords on the polyline segment [u0,u1]; returns n+1 arc lengths (first and last are u0,u1)."""
    def run(c):
        us = [u0]
        for _ in range(n):
            nx = _chord_step(X, s, us[-1], c)
            us.append(nx)
            if nx == math.inf:
                break
        return us

    lo, hi = 0.0, (u1 - u0) / n * (1 + 1e-9)
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        us = run(mid)
        if len(us) < n + 1 or us[-1] >= u1:
            hi = mid
        else:
            lo = mid
    us = run(hi)
    if len(us) < n + 1 or us[-1] == math.inf:
        us = run(lo)
    us = us[:n] + [u1]
    return np.asarray(us, np.float64)


def edge_equalize(geo, edges, measure="arc_length"):
    """See the file header. Returns (geometry, report)."""
    if measure not in EQUALIZE_MEASURES:
        raise ValueError(f"Measure must be one of {EQUALIZE_MEASURES}")
    P = _P(geo)
    newP = P.copy()
    rep = {"chains": 0, "loops": 0, "points_moved": 0}
    for pts, closed, anchored in _chains(geo, edges, "Edge Equalize"):
        idx = pts + [pts[0]] if closed else pts
        m = len(idx) - 1
        if m < 2:
            continue
        X = P[idx]
        s = _arc(X)
        L = float(s[-1])
        if not L > 0:
            continue
        i = np.arange(m + 1)
        if closed and not anchored:
            u0 = float(np.mean(s[:-1] - i[:-1] * L / m))
            X2 = np.vstack([X[:-1], X[:-1], X[-1:]])
            s2 = np.concatenate([s[:-1], s[:-1] + L, [2 * L]])
            u0 = u0 % L
            if measure == "chord":
                us = _equal_chords(X2, s2, u0, u0 + L, m)
            else:
                us = u0 + i * L / m
            Y = _at(X2, s2, us[:-1])
            newP[pts] = Y
        else:
            us = (_equal_chords(X, s, 0.0, L, m) if measure == "chord"
                  else i * L / m)
            Y = _at(X, s, us)
            inner = idx[1:-1]
            newP[inner] = Y[1:-1]
        rep["chains"] += 1
        rep["loops"] += int(closed)
    rep["points_moved"] = int((np.abs(newP - P).max(1) > 0).sum()) \
        if len(P) else 0
    return _with_P(geo, newP), rep


# pcg100: Houdini's Method (target edge length = average / longest / shortest of the selected edges). redistribute = the old behaviour (redistribute along
# the original polyline, total length unchanged), an extension of this plugin, kept as the default
EQUALIZE_METHODS = ("redistribute", "average", "longest", "shortest")
EQUALIZE_GROUP_TYPES = ("guess", "edges", "points", "prims")
_EQ_MAXIT = 1000


def _equalize_pairs(geo, spec, group_type):
    """Group + Group Type -> selected edges (E,2) (edges that really exist in the current topology). Empty = all edges."""
    from .groups import points_to_edges, prims_to_edges
    spec = str(spec).strip()                         # empty: every type resolves to all edges
    t = topology(geo)
    if group_type == "guess":
        names = spec.split()
        if any(n in geo.edge_groups for n in names):
            group_type = "edges"
        elif any(n in geo.groups[PRIM] for n in names) and not any(n in geo.groups[POINT] for n in names):
            group_type = "prims"
        else:
            group_type = "points"
    if group_type == "edges":
        pairs = resolve_edges(geo, spec)
        return np.asarray(t.edge_points[edge_mask(geo, pairs)], np.int64)
    if group_type == "points":
        return np.asarray(points_to_edges(geo, resolve(geo, POINT, spec)), np.int64)
    return np.asarray(prims_to_edges(geo, resolve(geo, PRIM, spec)), np.int64)


def edge_equalize_hou(geo, edges="", method="average", group_type="guess", out_group=""):
    """
    Houdini's Edge Equalize: all selected edges become the same length (Method sets the target: average / longest / shortest).
    The docs don't say which points move or how it's distributed -- here each edge scales about its own midpoint to the target length; a point pulled by several selected edges
    takes the average, iterating until every selected edge's length error is < 1e-9 x target (Jacobi iteration of positional constraints; unconnected edges get there in one step).
    Only endpoints of selected edges move. Zero-length edges have no direction and don't take part (nor count toward the target length). Returns (geometry, report).
    """
    if method not in EQUALIZE_METHODS[1:]:
        raise ValueError(f"Method must be one of {EQUALIZE_METHODS}")
    if group_type not in EQUALIZE_GROUP_TYPES:
        raise ValueError(f"Group Type must be one of {EQUALIZE_GROUP_TYPES}")
    P = _P(geo)
    rep = {"edges": 0, "target": 0.0, "iterations": 0, "max_error": 0.0}
    pairs = _equalize_pairs(geo, edges, group_type) if geo.npoints else np.zeros((0, 2), np.int64)
    out = geo.copy()
    if str(out_group).strip():
        out.set_edge_group(str(out_group).strip(), pairs.astype(np.int32) if len(pairs) else np.zeros((0, 2), np.int32))
    if not len(pairs):
        return out, rep
    a, b = pairs[:, 0], pairs[:, 1]
    ln = np.linalg.norm(P[b] - P[a], axis=1)
    ok = ln > 1e-12
    if not ok.any():
        return out, rep
    a, b, ln = a[ok], b[ok], ln[ok]
    tgt = float({"average": ln.mean(), "longest": ln.max(), "shortest": ln.min()}[method])
    cnt = np.bincount(np.concatenate([a, b]), minlength=len(P)).astype(np.float64)
    X = P.copy()
    it, err = 0, float(np.abs(ln - tgt).max())
    while err > 1e-9 * tgt and it < _EQ_MAXIT:
        d = X[b] - X[a]
        L = np.linalg.norm(d, axis=1)
        corr = (0.5 * (L - tgt) / np.where(L > 1e-300, L, 1.0))[:, None] * d
        delta = np.zeros_like(X)
        np.add.at(delta, a, corr)
        np.add.at(delta, b, -corr)
        X += delta / np.maximum(cnt, 1.0)[:, None]
        it += 1
        err = float(np.abs(np.linalg.norm(X[b] - X[a], axis=1) - tgt).max())
    rep.update(edges=int(len(a)), target=tgt, iterations=it, max_error=err)
    out.set(POINT, "P", X.astype(geo.get(POINT, "P").dtype), owned=True)
    return out, rep


def edge_straighten(geo, edges, spacing="preserve"):
    if spacing not in STRAIGHTEN_SPACING:
        raise ValueError(f"Spacing must be one of {STRAIGHTEN_SPACING}")
    P = _P(geo)
    newP = P.copy()
    rep = {"chains": 0, "skipped_loops": 0, "skipped_degenerate": 0}
    for pts, closed, _ in _chains(geo, edges, "Edge Straighten"):
        if closed:
            rep["skipped_loops"] += 1
            continue
        if len(pts) < 3:
            continue
        X = P[pts]
        A, B = X[0], X[-1]
        d = B - A
        L2 = float(d @ d)
        if not L2 > 0:
            rep["skipped_degenerate"] += 1
            continue
        m = len(pts) - 1
        if spacing == "preserve":
            s = _arc(X)
            f = s / s[-1]
        elif spacing == "uniform":
            f = np.arange(m + 1) / m
        else:
            f = np.clip((X - A) @ d / L2, 0.0, 1.0)
        newP[pts[1:-1]] = A + f[1:-1, None] * d
        rep["chains"] += 1
    return _with_P(geo, newP), rep


def _newell(X):
    Y = np.roll(X, -1, axis=0)
    return np.array([np.sum((X[:, 1] - Y[:, 1]) * (X[:, 2] + Y[:, 2])),
                     np.sum((X[:, 2] - Y[:, 2]) * (X[:, 0] + Y[:, 0])),
                     np.sum((X[:, 0] - Y[:, 0]) * (X[:, 1] + Y[:, 1]))])


def _perp(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    return u / np.linalg.norm(u)


def circle_from_edges(geo, edges, radius_mode="average", radius=1.0,
                      even_spacing=True, rotate=0.0):
    if radius_mode not in RADIUS_MODES:
        raise ValueError(f"Radius Mode must be one of {RADIUS_MODES}")
    P = _P(geo)
    newP = P.copy()
    rep = {"loops": 0, "skipped_open": 0, "radii": []}
    for pts, closed, _ in _chains(geo, edges, "Circle from Edges"):
        if not closed:
            rep["skipped_open"] += 1
            continue
        n = len(pts)
        if n < 3:
            continue
        X = P[pts]
        c = X.mean(0)
        nrm = _newell(X)
        if np.linalg.norm(nrm) < 1e-12 * max(1.0, float(np.abs(X).max())) ** 2:
            w, V = np.linalg.eigh(np.cov((X - c).T))
            nrm = V[:, 0]
        nrm = nrm / np.linalg.norm(nrm)
        d = X - c
        u = d[0] - (d[0] @ nrm) * nrm
        u = u / np.linalg.norm(u) if np.linalg.norm(u) > 1e-300 else _perp(nrm)
        v = np.cross(nrm, u)
        x, y = d @ u, d @ v
        th = np.arctan2(y, x)
        r = np.hypot(x, y)
        R = {"average": float(r.mean()), "min": float(r.min()),
             "max": float(r.max()), "custom": float(radius)}[radius_mode]
        if even_spacing:
            k = np.arange(n)
            step = 2 * np.pi * k / n
            phi = float(np.angle((r * np.exp(1j * (th - step))).sum()))
            th = phi + step
        th = th + math.radians(float(rotate))
        newP[pts] = c + R * (np.cos(th)[:, None] * u + np.sin(th)[:, None] * v)
        rep["loops"] += 1
        rep["radii"].append(round(R, 6))
    return _with_P(geo, newP), rep


# ═══════════════════════════════════════════════════════════ Edge Flip
class _Faces:
    """Mutable primitive table (each primitive is a list of corner numbers) + edge -> primitive index."""

    def __init__(self, geo, valid):
        self.vp = np.asarray(geo.vertex_point, np.int64)
        off = geo.prim_offset
        self.f = [list(range(int(off[i]), int(off[i + 1])))
                  for i in range(geo.nprims)]
        self.valid = valid
        self.emap = defaultdict(set)
        for i in np.nonzero(valid)[0].tolist():
            for e in self.edges(i):
                self.emap[e].add(i)

    def pts(self, i):
        return [int(self.vp[c]) for c in self.f[i]]

    def edges(self, i):
        p = self.pts(i)
        return [(min(a, b), max(a, b)) for a, b in zip(p, p[1:] + p[:1])]

    def replace(self, i, corners):
        for e in self.edges(i):
            self.emap[e].discard(i)
        self.f[i] = corners
        for e in self.edges(i):
            self.emap[e].add(i)


def _rotate_pair(F, a, b, s):
    """Rotate edge (a,b) by s steps around the loop formed by its two adjacent primitives. Returns the new edge on success, else None."""
    fs = F.emap.get((min(a, b), max(a, b)), set())
    if len(fs) != 2:
        return None
    f1, f2 = sorted(fs)
    p1, p2 = F.pts(f1), F.pts(f2)
    n1, n2 = len(p1), len(p2)

    def he(p, x, y):
        for k in range(len(p)):
            if p[k] == x and p[(k + 1) % len(p)] == y:
                return k
        return -1
    k = he(p1, a, b)
    if k < 0:
        a, b = b, a
        k = he(p1, a, b)
    j = he(p2, b, a)
    if k < 0 or j < 0:
        return None                          # windings disagree
    c1, c2 = F.f[f1], F.f[f2]
    Lp, L1, L2 = [], [], []
    for i in range(n1):                      # b ... a (primitive 1)
        q = (k + 1 + i) % n1
        Lp.append(p1[q])
        L1.append(c1[q])
        L2.append(None)
    L2[0], L2[n1 - 1] = c2[j], c2[(j + 1) % n2]
    for i in range(n2 - 2):                  # after a ... before b (primitive 2)
        q = (j + 2 + i) % n2
        Lp.append(p2[q])
        L1.append(None)
        L2.append(c2[q])
    N = n1 + n2 - 2
    s = int(s) % N
    if s == 0:
        return None
    i1 = [(s + i) % N for i in range(n1)]
    i2 = [(n1 - 1 + s + i) % N for i in range(n2)]
    x, y = Lp[i1[0]], Lp[i2[0]]
    if x == y or (min(x, y), max(x, y)) == (min(a, b), max(a, b)):
        return None
    if F.emap.get((min(x, y), max(x, y))):
        return None                          # this edge already exists
    new1 = [Lp[i] for i in i1]
    new2 = [Lp[i] for i in i2]
    if len(set(new1)) < n1 or len(set(new2)) < n2:
        return None
    F.replace(f1, [L1[i] if L1[i] is not None else L2[i] for i in i1])
    F.replace(f2, [L2[i] if L2[i] is not None else L1[i] for i in i2])
    return (min(x, y), max(x, y)), f1, f2


def _angle(P, o, a, b):
    u, v = P[a] - P[o], P[b] - P[o]
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu <= 0 or nv <= 0:
        return 0.0
    return math.acos(max(-1.0, min(1.0, float(u @ v) / (nu * nv))))


def _delaunay_ok(F, P, a, b, max_angle):
    """Triangles on both sides (a,b,c)(b,a,d): should it flip (opposite angles sum > 180 deg, dihedral angle not over max_angle)."""
    fs = F.emap.get((min(a, b), max(a, b)), set())
    if len(fs) != 2:
        return False
    f1, f2 = sorted(fs)
    p1, p2 = F.pts(f1), F.pts(f2)
    if len(p1) != 3 or len(p2) != 3:
        return False
    c = [x for x in p1 if x != a and x != b]
    d = [x for x in p2 if x != a and x != b]
    if len(c) != 1 or len(d) != 1:
        return False
    c, d = c[0], d[0]
    if _angle(P, c, a, b) + _angle(P, d, a, b) <= math.pi + 1e-9:
        return False
    n1 = np.cross(P[p1[1]] - P[p1[0]], P[p1[2]] - P[p1[0]])
    n2 = np.cross(P[p2[1]] - P[p2[0]], P[p2[2]] - P[p2[0]])
    l1, l2 = np.linalg.norm(n1), np.linalg.norm(n2)
    if l1 <= 0 or l2 <= 0:
        return False
    cosd = float(n1 @ n2) / (l1 * l2)
    if cosd < math.cos(math.radians(float(max_angle))):
        return False
    # No need to check "would flipping fold": opposite angles summing to > 180 deg already implies the quad is convex and the two flipped triangles
    # face the same way as the originals. In the plane this is a classic result (the diagonal of a non-convex quad is always Delaunay-legal);
    # in 3D, rotating d about ab into c's plane leaves both angles unchanged, reducing it to the planar case.
    # pcg74 also verified it with 760k random samples (dihedral angles up to 179.9 deg): not a single counterexample.
    return True


def edge_flip(geo, edges="", mode="rotate", cycles=1, max_angle=10.0):
    """See the file header. Returns (geometry, report)."""
    from .divide import _rebuild_flat
    if mode not in FLIP_MODES:
        raise ValueError(f"Mode must be one of {FLIP_MODES}")
    if not geo.nprims:
        return geo.copy(), {"flipped": 0, "skipped": 0}
    P = _P(geo)
    sizes = geo.prim_sizes()
    valid = geo.prim_closed & (sizes >= 3) & (geo.prim_type == PRIM_POLY)
    F = _Faces(geo, valid)
    spec = str(edges).strip()
    pairs = resolve_edges(geo, spec)
    t = topology(geo)
    sel = [tuple(map(int, e)) for e in t.edge_points[edge_mask(geo, pairs)]]
    flipped, skipped = 0, 0
    renamed = {}                                  # old edge -> new edge
    if mode == "rotate":
        touched = set()
        for a, b in sel:
            fs = F.emap.get((a, b), set())
            if len(fs) != 2 or fs & touched:
                skipped += 1
                continue
            r = _rotate_pair(F, a, b, cycles)
            if r is None:
                skipped += 1
                continue
            ne, f1, f2 = r
            touched |= {f1, f2}
            renamed[(a, b)] = ne
            flipped += 1
    else:
        active = set(sel)
        queue = list(sel)
        cap = 50 * max(len(sel), 1)
        while queue and flipped < cap:
            a, b = queue.pop(0)
            if (a, b) not in active:
                continue
            if not _delaunay_ok(F, P, a, b, max_angle):
                continue
            r = _rotate_pair(F, a, b, 1)
            if r is None:
                continue
            ne, f1, f2 = r
            active.discard((a, b))
            active.add(ne)
            renamed[(a, b)] = ne
            flipped += 1
            for f in (f1, f2):
                for e in F.edges(f):
                    if e in active and e != ne:
                        queue.append(e)
        skipped = 0
    src_corner = np.concatenate([np.asarray(c, np.int64) for c in F.f]) \
        if geo.nvertices else np.zeros(0, np.int64)
    out = _rebuild_flat(geo, src_corner, np.array([len(c) for c in F.f]),
                        np.arange(geo.nprims), geo.prim_closed.copy())
    # edge groups: flipped edges are replaced by the new diagonals (following chained flips to the end)
    def final(e):
        seen = 0
        while e in renamed and seen < 10 ** 6:
            e = renamed[e]
            seen += 1
        return e
    for k, v in geo.edge_groups.items():
        v = np.asarray(v)
        if not len(v):
            continue
        new = np.array([final((int(min(x, y)), int(max(x, y)))) for x, y in v],
                       np.int32)
        new = np.unique(new, axis=0)
        out.set_edge_group(k, new[_is_edge(out, new)])
    return out, {"flipped": int(flipped), "skipped": int(skipped)}


# ═══════════════════════════════════════════════════════════ Rewire Vertices
def rewire_vertices(geo, attribute="rewire_to", keep_unused_points=True,
                    remove_degenerate=False):
    from .divide import _rebuild_flat
    name = str(attribute).strip()
    a = geo.get(VERTEX, name) if name else None
    cls = VERTEX
    vp = np.asarray(geo.vertex_point, np.int64)
    if a is None and name:
        a = geo.get(POINT, name)
        cls = POINT
        if a is not None:
            a = np.asarray(a)[vp]
    if a is None or is_string(a):
        raise KeyError(f"No integer attribute '{name}' on either vertex or point")
    tgt = np.rint(np.asarray(a, np.float64)[:, 0]).astype(np.int64)
    ok = (tgt >= 0) & (tgt < geo.npoints)
    new_vp = np.where(ok, tgt, vp)
    g = geo.copy()
    g.set_topology(new_vp.astype(np.int32), geo.prim_offset, geo.prim_closed,
                   geo.prim_type)
    rep = {"attribute_class": cls, "rewired": int((ok & (tgt != vp)).sum()),
           "ignored": int((~ok).sum())}
    if remove_degenerate and g.nvertices:
        keep_c, keep_sz, keep_p = [], [], []
        for i in range(g.nprims):
            o0, o1 = int(g.prim_offset[i]), int(g.prim_offset[i + 1])
            cs = list(range(o0, o1))
            pp = [int(new_vp[c]) for c in cs]
            closed = bool(g.prim_closed[i])
            kc = [c for j, c in enumerate(cs)
                  if j == 0 or pp[j] != pp[j - 1]]
            if closed and len(kc) > 1 and new_vp[kc[-1]] == new_vp[kc[0]]:
                kc = kc[:-1]
            if len(kc) < (3 if closed else 2):
                continue
            keep_c.append(kc)
            keep_sz.append(len(kc))
            keep_p.append(i)
        rep["removed_prims"] = int(g.nprims - len(keep_p))
        rep["removed_corners"] = int(g.nvertices - sum(keep_sz))
        g = _rebuild_flat(g, np.concatenate(keep_c).astype(np.int64)
                          if keep_c else np.zeros(0, np.int64),
                          np.asarray(keep_sz, np.int64),
                          np.asarray(keep_p, np.int64),
                          g.prim_closed[np.asarray(keep_p, np.int64)]
                          if keep_p else np.zeros(0, bool))
    if not keep_unused_points:
        from .addsop import remove_unused
        n = g.npoints
        g = remove_unused(g)
        rep["removed_points"] = int(n - g.npoints)
    for k, v in list(g.edge_groups.items()):
        v = np.asarray(v)
        if len(v):
            g.set_edge_group(k, v[_is_edge(g, v)])
    return g, rep


# ═══════════════════════════════════════════════════════════ PolyCut
def poly_cut(geo, group="", mode="cut_points", points="", attribute="",
             threshold=0.5, keep="all", cut_type="points", cut_edges="",
             detect="crossing", cut_threshold=0.1, keep_closed=False):
    if mode not in CUT_MODES:
        raise ValueError(f"Mode must be one of {CUT_MODES}")
    if mode in ("remove", "cut"):
        return _poly_cut_hou(geo, group, mode, cut_type, points, cut_edges, detect,
                             attribute, threshold, cut_threshold, keep_closed)
    if keep not in CUT_KEEP:
        raise ValueError(f"Keep must be one of {CUT_KEEP}")
    sel = resolve(geo, PRIM, group)
    vp = np.asarray(geo.vertex_point, np.int64)
    if mode == "threshold":
        name = str(attribute).strip()
        a = geo.get(POINT, name) if name else None
        if a is None or is_string(a):
            raise KeyError(f"No numeric point attribute '{name}'")
        val = np.asarray(a, np.float64)[:, 0]
        thr = float(threshold)
    else:
        spec = str(points).strip()
        if not spec:
            raise ValueError("Points is empty -- enter a point group (which points to break at / "
                             "which points to keep edges between)")
        inpt = resolve(geo, POINT, spec)
    B = _Build(geo)
    cross = {}                                  # edge (sorted point pair) -> new point
    rep = {"cut_prims": 0, "polylines": 0, "inserted_points": 0}
    for i in range(geo.nprims):
        o0, o1 = int(geo.prim_offset[i]), int(geo.prim_offset[i + 1])
        cs = list(range(o0, o1))
        closed = bool(geo.prim_closed[i])
        if not sel[i] or len(cs) < 2:
            B.add_face([vp[c] for c in cs], cs, i, closed)
            continue
        # nodes: (point number, corner weights, value)
        nodes = []
        ne = len(cs) if closed else len(cs) - 1
        for j in range(len(cs)):
            c = cs[j]
            p = int(vp[c])
            nodes.append((p, ((c,), (1.0,)),
                          val[p] if mode == "threshold" else 0.0))
            if mode == "threshold" and j < ne:
                c2 = cs[(j + 1) % len(cs)]
                q = int(vp[c2])
                va, vb = val[p] - thr, val[q] - thr
                if va * vb < 0:
                    key = (min(p, q), max(p, q))
                    x, y = key
                    f = (thr - val[x]) / (val[y] - val[x])
                    if key not in cross:
                        cross[key] = B.add_point([x, y], [1 - f, f])
                        rep["inserted_points"] += 1
                    fc = (thr - val[p]) / (val[q] - val[p])
                    nodes.append((cross[key], ((c, c2), (1 - fc, fc)), thr))
        m = len(nodes)
        ne = m if closed else m - 1
        if mode == "cut_points":
            cut = [bool(inpt[n[0]]) if n[0] < geo.npoints else False
                   for n in nodes]
            kept = [True] * ne
        elif mode == "keep_points":
            cut = [False] * m
            kept = [bool(inpt[nodes[j][0]]) and
                    bool(inpt[nodes[(j + 1) % m][0]]) for j in range(ne)]
        else:
            vv = [n[2] for n in nodes]
            if keep == "all":
                cut = [v == thr for v in vv]
                kept = [True] * ne
            else:
                sgn = 1.0 if keep == "above" else -1.0
                cut = [False] * m
                kept = [(vv[j] - thr) * sgn >= 0 and
                        (vv[(j + 1) % m] - thr) * sgn >= 0
                        for j in range(ne)]
        if all(kept) and not any(cut) and m == len(cs):
            B.add_face([vp[c] for c in cs], cs, i, closed)
            continue
        rep["cut_prims"] += 1
        # find a start: right after a broken edge, or at a break point
        if closed:
            start = None
            for j in range(m):
                if not kept[(j - 1) % m] or cut[j]:
                    start = j
                    break
            if start is None:                   # points inserted but nothing broken (can't happen; safety net)
                B.add_face([n[0] for n in nodes], [n[1] for n in nodes], i,
                           True)
                continue
            order = [(start + j) % m for j in range(m)] + [start]
            ek = [kept[(start + j) % m] for j in range(m)]
        else:
            order = list(range(m))
            ek = kept
        run = [order[0]]
        for j in range(1, len(order)):
            nj = order[j]
            if ek[j - 1]:
                run.append(nj)
                if cut[nj] and j < len(order) - 1:
                    if len(run) >= 2:
                        B.add_face([nodes[x][0] for x in run],
                                   [nodes[x][1] for x in run], i, False)
                        rep["polylines"] += 1
                    run = [nj]
            else:
                if len(run) >= 2:
                    B.add_face([nodes[x][0] for x in run],
                               [nodes[x][1] for x in run], i, False)
                    rep["polylines"] += 1
                run = [nj]
        if len(run) >= 2:
            B.add_face([nodes[x][0] for x in run], [nodes[x][1] for x in run],
                       i, False)
            rep["polylines"] += 1
    return B.geometry(), rep


def _poly_cut_hou(geo, group, strategy, cut_type, points, cut_edges, detect,
                  attribute, cut_value, cut_threshold, keep_closed):
    """
    Houdini PolyCut semantics (Strategy = Remove / Cut), a separate system from the three original modes above:

      First find the "failing edges": empty Cut Attribute = all edges; crossing = the attribute crosses Cut Value
      (the two ends strictly on opposite sides), or both ends exactly equal Cut Value; change = attribute difference between the ends > Cut Threshold
      (distance for vector attributes).
      Type = points: Remove deletes both endpoints of a failing edge (along with their neighbouring edges); Cut breaks at both endpoints;
                    Cut Points restricts which points may be deleted / broken.
      Type = edges: Remove deletes the edge; Cut breaks in the middle of the edge -- crossing inserts a point at the linearly interpolated crossing point,
                    change divides the edge into ceil(difference / threshold) pieces (each piece's change doesn't exceed the threshold);
                    Cut Edges restricts which edges may be deleted / broken.
      Keep Polygons Closed: fragments cut from closed polygons are closed too.

    Not stated in the docs, decided here (also listed in the notes):
      - crossing with only one end equal to Cut Value: doesn't count as crossing (product = 0)
      - crossing with a vector attribute: use component 0
      - edges + cut without Cut Attribute (or both ends equal to Cut Value): there's no "middle position" to break at;
        handled as the docs describe the latter case, "delete but don't cut"
      - edges + cut + change: break at every inserted point (that's what Strategy is about: how to break)
      - at a break, the two pieces share that point (consistent with the original cut_points); points deleted by points + remove are really deleted
        if no other primitive uses them, and fragments with only one point aren't output
    """
    if cut_type not in CUT_TYPES:
        raise ValueError(f"Type must be one of {CUT_TYPES}")
    if detect not in CUT_DETECT:
        raise ValueError(f"Detect Edge Changes must be one of {CUT_DETECT}")
    sel = resolve(geo, PRIM, group)
    vp = np.asarray(geo.vertex_point, np.int64)
    name = str(attribute).strip()
    A = None
    if name:
        a = geo.get(POINT, name)
        if a is None or is_string(a):
            raise KeyError(f"No numeric point attribute '{name}'")
        A = np.asarray(a, np.float64)
    cv, ct = float(cut_value), float(cut_threshold)
    by_pt, by_edge = cut_type == "points", cut_type == "edges"
    do_cut = strategy == "cut"
    if A is not None and detect == "change" and by_edge and do_cut and not ct > 0:
        raise ValueError("Cut Threshold must be > 0 (edges are split into pieces whose change doesn't exceed it)")
    okpt = resolve(geo, POINT, points) if by_pt else None
    oked = None
    if by_edge and str(cut_edges).strip() not in ("", "*"):
        oked = {(int(x), int(y)) for x, y in np.sort(resolve_edges(geo, cut_edges), axis=1)}
    B = _Build(geo)
    cross = {}
    gone = np.zeros(geo.npoints, bool)
    rep = {"cut_prims": 0, "polylines": 0, "inserted_points": 0, "removed_points": 0}

    def emit(run, i, was_closed):
        if len(run) < 2:
            return
        cl = bool(keep_closed and was_closed)
        if cl and run[0] == run[-1]:            # the whole ring broken in just one place: closing it gives the original ring
            run = run[:-1]
        cl = cl and len(run) >= 3
        B.add_face([nodes[x][0] for x in run], [nodes[x][1] for x in run], i, cl)
        rep["polylines"] += 1

    for i in range(geo.nprims):
        o0, o1 = int(geo.prim_offset[i]), int(geo.prim_offset[i + 1])
        cs = list(range(o0, o1))
        n = len(cs)
        closed = bool(geo.prim_closed[i])
        if not sel[i] or n < 2:
            B.add_face([vp[c] for c in cs], cs, i, closed)
            continue
        ne = n if closed else n - 1
        pp = [int(vp[c]) for c in cs]
        bad = np.zeros(ne, bool)                 # failing edges
        mid = [True] * ne                        # this edge has a "middle position" that can be broken
        for j in range(ne):
            p, q = pp[j], pp[(j + 1) % n]
            if A is None:
                bad[j], mid[j] = True, False
            elif detect == "crossing":
                va, vb = A[p, 0] - cv, A[q, 0] - cv
                if va == 0 and vb == 0:
                    bad[j], mid[j] = True, False
                else:
                    bad[j] = va * vb < 0
            else:
                bad[j] = float(np.linalg.norm(A[p] - A[q])) > ct
            if oked is not None and (min(p, q), max(p, q)) not in oked:
                bad[j] = False
        if not bad.any():
            B.add_face(pp, cs, i, closed)
            continue
        rep["cut_prims"] += 1
        nodes = [(pp[j], ((cs[j],), (1.0,))) for j in range(n)]
        cut = [False] * n
        kept = [True] * ne
        if by_pt:
            hit = [False] * n
            for j in np.nonzero(bad)[0]:
                for k in (int(j), (int(j) + 1) % n):
                    hit[k] = bool(okpt[pp[k]])
            if do_cut:
                cut = hit
            else:
                kept = [not hit[j] and not hit[(j + 1) % n] for j in range(ne)]
                for k in range(n):
                    if hit[k]:
                        gone[pp[k]] = True
        elif not do_cut:
            kept = [not b for b in bad]
        else:
            # inserting points on edges: the node table is reordered in original order; every inserted point is a break point
            nodes, cut, kept = [], [], []
            for j in range(n):
                nodes.append((pp[j], ((cs[j],), (1.0,))))
                cut.append(False)
                if j >= ne:
                    continue
                if not bad[j]:
                    kept.append(True)
                    continue
                if not mid[j]:
                    kept.append(False)
                    continue
                p, q, c, c2 = pp[j], pp[(j + 1) % n], cs[j], cs[(j + 1) % n]
                if detect == "crossing":
                    fr = [(cv - A[p, 0]) / (A[q, 0] - A[p, 0])]
                else:
                    k = int(math.ceil(float(np.linalg.norm(A[p] - A[q])) / ct))
                    if k > 100000:
                        raise ValueError("Cut Threshold too small: one edge would be split into more than 100,000 pieces")
                    fr = [x / k for x in range(1, k)]
                for x, f in enumerate(fr):
                    # adjacent primitives traverse this edge in opposite directions: stored as a sorted point pair, so the indices are flipped too
                    key = (p, q, x) if p < q else (q, p, len(fr) - 1 - x)
                    if key not in cross:
                        g_ = f if p < q else 1 - f
                        cross[key] = B.add_point([key[0], key[1]], [1 - g_, g_])
                        rep["inserted_points"] += 1
                    nodes.append((cross[key], ((c, c2), (1 - f, f))))
                    cut.append(True)
                    kept.append(True)
                kept.append(True)
        m = len(nodes)
        if closed:
            start = next((j for j in range(m) if not kept[(j - 1) % m] or cut[j]), None)
            if start is None:                    # nothing actually broken (none of the failing edges are in Cut Points)
                B.add_face([x[0] for x in nodes], [x[1] for x in nodes], i, True)
                rep["cut_prims"] -= 1
                continue
            order = [(start + j) % m for j in range(m)] + [start]
            ek = [kept[(start + j) % m] for j in range(m)]
        else:
            order, ek = list(range(m)), kept
            if all(ek) and not any(cut[1:-1]):   # an open curve "broken" only at its two ends: same as not broken
                B.add_face([x[0] for x in nodes], [x[1] for x in nodes], i, False)
                rep["cut_prims"] -= 1
                continue
        run = [order[0]]
        for j in range(1, len(order)):
            nj = order[j]
            if ek[j - 1]:
                run.append(nj)
                if cut[nj] and j < len(order) - 1:
                    emit(run, i, closed)
                    run = [nj]
            else:
                emit(run, i, closed)
                run = [nj]
        emit(run, i, closed)
    g = B.geometry()
    if gone.any():
        used = np.zeros(g.npoints, bool)
        if g.nvertices:
            used[g.vertex_point] = True
        keep = used | ~gone                      # points + remove inserts no points; point numbers correspond one-to-one with the input
        if not keep.all():
            from .ops import delete_points
            rep["removed_points"] = int((~keep).sum())
            g = delete_points(g, keep)
    return g, rep


# ═══════════════════════════════════════════════════════════ PolyStitch
def _pt_seg(Q, A, Bv, tol):
    """All (point, segment, distance, t) with point-to-segment distance <= tol. Bucketed by grid cells."""
    from . import spatial as _sp
    z = np.zeros(0, np.int64)
    if not len(Q) or not len(A):
        return z, z.copy(), np.zeros(0), np.zeros(0)
    L = np.linalg.norm(Bv - A, axis=1)
    h = max(float(np.median(L)) if len(L) else tol, 4 * tol, 1e-12)
    lo = np.minimum(A, Bv) - tol
    hi = np.maximum(A, Bv) + tol
    bucket, big = _sp._box_bucket(lo, hi, h)
    qi, si = bucket.query(_sp.cell_key(np.floor(Q / h).astype(np.int64)),
                          np.arange(len(Q)))
    if len(big):
        qi = np.concatenate([qi, np.repeat(np.arange(len(Q)), len(big))])
        si = np.concatenate([si, np.tile(big, len(Q))])
    if not len(qi):
        return z, z.copy(), np.zeros(0), np.zeros(0)
    d = Bv[si] - A[si]
    L2 = np.einsum("ij,ij->i", d, d)
    tt = np.einsum("ij,ij->i", Q[qi] - A[si], d) / np.where(L2 > 0, L2, 1.0)
    tt = np.clip(tt, 0.0, 1.0)
    dist = np.linalg.norm(A[si] + tt[:, None] * d - Q[qi], axis=1)
    ok = dist <= tol
    return qi[ok], si[ok], dist[ok], tt[ok]


def _boundary_he(geo, sel):
    """Boundary half-edges on selected primitives: (corner, next corner, a, b)."""
    t = topology(geo)
    nv = geo.nvertices
    if not nv:
        z = np.zeros(0, np.int64)
        return z, z, z, z
    he = np.arange(nv)
    ok = t.he_valid & (t.he_edge >= 0)
    ok[ok] &= t.boundary[t.he_edge[ok]]
    vpr = geo.vertex_prim()
    ok &= sel[vpr] & geo.prim_closed[vpr]
    nxt = geo.next_corner()
    c = he[ok]
    vp = np.asarray(geo.vertex_point, np.int64)
    return c, nxt[c].astype(np.int64), vp[c], vp[nxt[c]]


def poly_stitch(geo, group="", tolerance=1e-3, snap=True):
    from .facet import _weld
    from . import spatial as _sp
    tol = float(tolerance)
    if tol < 0:
        raise ValueError("Tolerance must not be negative")
    sel = resolve(geo, PRIM, group)
    P = _P(geo)
    rep = {"welded_points": 0, "snapped_points": 0, "inserted_corners": 0}
    # 1 weld boundary points to each other
    c, cn, a, b = _boundary_he(geo, sel)
    bp = np.unique(np.concatenate([a, b])) if len(a) else np.zeros(0, np.int64)
    lab = np.arange(geo.npoints)
    if len(bp) and tol > 0:
        qi, pi, _ = _sp.neighbors_within(P[bp], P[bp], tol)
        m = qi < pi
        from .meshfix import _uf
        l2, k = _uf(len(bp), np.stack([qi[m], pi[m]], 1))
        rep_idx = np.full(k, len(bp))
        np.minimum.at(rep_idx, l2, np.arange(len(bp)))
        cnt = np.bincount(l2, minlength=k)
        C = np.stack([np.bincount(l2, weights=P[bp, j], minlength=k)
                      for j in range(3)], 1) / cnt[:, None]
        lab[bp] = bp[rep_idx[l2]]
        P[bp] = C[l2]
        rep["welded_points"] = int(len(bp) - k)
    g = _with_P(geo, P)
    if rep["welded_points"]:
        g = _weld(g, lab[:, None])
        sel = resolve(g, PRIM, group) if str(group).strip() else \
            np.ones(g.nprims, bool)
    P = _P(g)
    # 2 snap points onto others' edges
    c, cn, a, b = _boundary_he(g, sel)
    if snap and len(a) and tol > 0:
        bp = np.unique(np.concatenate([a, b]))
        qi, si, dist, tt = _pt_seg(P[bp], P[a], P[b], tol)
        # when the point is an endpoint of this edge, t is exactly 0 or 1, already excluded by the open interval (0,1)
        m = (tt > 0) & (tt < 1)
        if m.any():
            qi, si, dist, tt = qi[m], si[m], dist[m], tt[m]
            o = np.lexsort((dist, qi))
            first = o[np.r_[True, qi[o][1:] != qi[o][:-1]]]
            q, s_, t_ = qi[first], si[first], tt[first]
            moved = dist[first] > 0
            P[bp[q]] = P[a[s_]] + t_[:, None] * (P[b[s_]] - P[a[s_]])
            rep["snapped_points"] = int(moved.sum())
            g = _with_P(g, P)
    # 3 insert T-junction points into edges
    c, cn, a, b = _boundary_he(g, sel)
    B = _Build(g)
    B.P = P
    ins = defaultdict(list)                       # corner -> [(t, point)]
    if len(a):
        bp = np.unique(np.concatenate([a, b]))
        eps = max(tol, 1e-9 * float(np.abs(P).max() if len(P) else 1.0))
        qi, si, dist, tt = _pt_seg(P[bp], P[a], P[b], eps)
        Ls = np.linalg.norm(P[b] - P[a], axis=1)
        for q, s_, t_ in zip(qi.tolist(), si.tolist(), tt.tolist()):
            p = int(bp[q])
            if p == a[s_] or p == b[s_]:
                continue
            if t_ * Ls[s_] <= eps or (1 - t_) * Ls[s_] <= eps:
                continue
            ins[int(c[s_])].append((t_, p))
    vp = np.asarray(g.vertex_point, np.int64)
    nxt = g.next_corner()
    for i in range(g.nprims):
        o0, o1 = int(g.prim_offset[i]), int(g.prim_offset[i + 1])
        pts, cor = [], []
        for cc in range(o0, o1):
            pts.append(int(vp[cc]))
            cor.append(cc)
            if cc in ins:
                c2 = int(nxt[cc])
                seen = set()
                for t_, p in sorted(ins[cc]):
                    if p in seen:
                        continue
                    seen.add(p)
                    pts.append(p)
                    cor.append(((cc, c2), (1 - t_, t_)))
                    rep["inserted_corners"] += 1
        B.add_face(pts, cor, i, bool(g.prim_closed[i]))
    out = B.geometry(sort=False)
    t = topology(out)
    rep["boundary_edges"] = int(t.boundary.sum())
    return out, rep


# ═══════════════════════════════════════════════════════════ Tri Divide
def _lepp_terminal(T, P, emap, i):
    """From triangle i, walk the longest-edge propagation path to the terminal edge; return that edge (sorted point pair)."""
    seen = set()
    while True:
        a, b, c = T[i]
        es = [(a, b), (b, c), (c, a)]
        L = [float(np.sum((P[x] - P[y]) ** 2)) for x, y in es]
        k = int(np.argmax(L))
        e = (min(es[k]), max(es[k]))
        nb = [f for f in emap[e] if f != i]
        if not nb or nb[0] in seen or len(emap[e]) > 2:
            return e
        j = nb[0]
        a2, b2, c2 = T[j]
        es2 = [(a2, b2), (b2, c2), (c2, a2)]
        L2 = [float(np.sum((P[x] - P[y]) ** 2)) for x, y in es2]
        e2 = (min(es2[int(np.argmax(L2))]), max(es2[int(np.argmax(L2))]))
        if e2 == e or max(L2) <= L[k] * (1 + 1e-12):
            return e
        seen.add(i)
        i = j


def tri_divide(geo, group="", max_edge_length=0.0, max_area=0.0,
               delaunay=False, flip_angle=1.0):
    """See the file header. Returns (geometry, report)."""
    from .divide import divide as _divide
    if not geo.nprims:
        return geo.copy(), {"triangles": 0}
    g = geo.copy()
    g.set_group(PRIM, "__td_sel__", resolve(geo, PRIM, group))
    g.set(PRIM, "__td_src__", np.arange(geo.nprims, dtype=np.int32),
          owned=True)
    g.set(VERTEX, "__td_c__", np.arange(geo.nvertices, dtype=np.int32),
          owned=True)
    g = _divide(g, "__td_sel__", True, 3)
    sel = g.get_group(PRIM, "__td_sel__")
    src_prim = np.asarray(g.get(PRIM, "__td_src__"))[:, 0].astype(np.int64)
    src_c = np.asarray(g.get(VERTEX, "__td_c__"))[:, 0].astype(np.int64)
    sizes = g.prim_sizes()
    vp = np.asarray(g.vertex_point, np.int64)
    P = [row for row in _P(g)]                    # growable point table
    Pw = [None] * len(P)                           # new points: (source points, weights)
    tri_mask = sel & (sizes == 3) & g.prim_closed
    # triangles: points + per-corner {source corner: weight} dicts
    T, TC, Tsrc, other, OC, Osrc, Ocl = [], [], [], [], [], [], []
    for i in range(g.nprims):
        o0, o1 = int(g.prim_offset[i]), int(g.prim_offset[i + 1])
        cs = list(range(o0, o1))
        cw = [{int(src_c[c]): 1.0} for c in cs]
        if tri_mask[i]:
            T.append([int(vp[c]) for c in cs])
            TC.append(cw)
            Tsrc.append(int(src_prim[i]))
        else:
            other.append([int(vp[c]) for c in cs])
            OC.append(cw)
            Osrc.append(int(src_prim[i]))
            Ocl.append(bool(g.prim_closed[i]))
    Lmax = float(max_edge_length)
    Amax = float(max_area)
    rep = {"splits": 0, "flips": 0}

    def P_(i):
        return np.asarray(P[i])

    def bad(tri):
        a, b, c = (P_(x) for x in tri)
        if Lmax > 0 and max(np.linalg.norm(a - b), np.linalg.norm(b - c),
                            np.linalg.norm(c - a)) > Lmax * (1 + 1e-12):
            return True
        if Amax > 0 and 0.5 * np.linalg.norm(np.cross(b - a, c - a)) > \
                Amax * (1 + 1e-12):
            return True
        return False

    def mix(d1, d2):
        out = defaultdict(float)
        for d in (d1, d2):
            for k, w in d.items():
                out[k] += 0.5 * w
        return dict(out)

    if Lmax > 0 or Amax > 0:
        for _ in range(200):
            emap = defaultdict(list)
            for i, tri in enumerate(T):
                for x, y in ((tri[0], tri[1]), (tri[1], tri[2]),
                             (tri[2], tri[0])):
                    emap[(min(x, y), max(x, y))].append(i)
            omap = defaultdict(list)
            for i, f in enumerate(other):
                n = len(f)
                for k in range(n if Ocl[i] else n - 1):
                    x, y = f[k], f[(k + 1) % n]
                    omap[(min(x, y), max(x, y))].append(i)
            Parr = np.asarray(P)
            viol = [i for i, tri in enumerate(T) if bad(tri)]
            if not viol:
                break
            terms = []
            seen_e = set()
            for i in viol:
                e = _lepp_terminal(T, Parr, emap, i)
                if e not in seen_e:
                    seen_e.add(e)
                    terms.append(e)
            used = set()
            pick = []
            for e in terms:
                fs = emap[e]
                if any(f in used for f in fs) or len(fs) > 2:
                    continue
                used.update(fs)
                pick.append(e)
            if not pick:
                break
            newT, newTC, newS, kill = [], [], [], set()
            for e in pick:
                x, y = e
                m = len(P)
                P.append(0.5 * (P_(x) + P_(y)))
                Pw.append(((x, y), (0.5, 0.5)))
                for f in emap[e]:
                    tri, cw = T[f], TC[f]
                    for k in range(3):
                        if {tri[k], tri[(k + 1) % 3]} == {x, y}:
                            break
                    p, q, r = tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]
                    cp, cq, cr_ = cw[k], cw[(k + 1) % 3], cw[(k + 2) % 3]
                    cm = mix(cp, cq)
                    newT += [[p, m, r], [m, q, r]]
                    newTC += [[cp, cm, cr_], [cm, cq, cr_]]
                    newS += [Tsrc[f], Tsrc[f]]
                    kill.add(f)
                for f in omap.get(e, []):             # unselected primitives: insert the midpoint
                    poly, cw = other[f], OC[f]
                    n = len(poly)
                    for k in range(n):
                        if {poly[k], poly[(k + 1) % n]} == {x, y}:
                            other[f] = poly[:k + 1] + [m] + poly[k + 1:]
                            OC[f] = cw[:k + 1] + [mix(cw[k], cw[(k + 1) % n])] \
                                + cw[k + 1:]
                            break
                rep["splits"] += 1
            T = [t_ for i, t_ in enumerate(T) if i not in kill] + newT
            TC = [t_ for i, t_ in enumerate(TC) if i not in kill] + newTC
            Tsrc = [t_ for i, t_ in enumerate(Tsrc) if i not in kill] + newS

    if delaunay and T:
        # borrow Edge Flip's Lawson: temporarily assemble a triangles-only geometry
        tg = Geometry.from_mesh(np.asarray(P), [list(t_) for t_ in T])
        F = _Faces(tg, np.ones(len(T), bool))
        Parr = np.asarray(P)
        queue = sorted(F.emap.keys())
        active = set(queue)
        cap = 50 * max(len(queue), 1)
        cw_of = [dict(zip(range(3 * i, 3 * i + 3), TC[i])) for i in
                 range(len(T))]
        corner_w = {}
        for d in cw_of:
            corner_w.update(d)
        while queue and rep["flips"] < cap:
            a, b = queue.pop(0)
            if (a, b) not in active:
                continue
            if not _delaunay_ok(F, Parr, a, b, flip_angle):
                continue
            r = _rotate_pair(F, a, b, 1)
            if r is None:
                continue
            ne, f1, f2 = r
            active.discard((a, b))
            active.add(ne)
            rep["flips"] += 1
            for f in (f1, f2):
                for e in F.edges(f):
                    if e != ne:
                        queue.append(e)
        T = [F.pts(i) for i in range(len(T))]
        TC = [[corner_w[c] for c in F.f[i]] for i in range(len(T))]

    # ── assemble output: original points + new points; primitives = unselected + triangles, sorted by source prim
    B = _Build(geo)
    n0 = geo.npoints
    ext = {}
    for i in range(g.npoints, len(P)):
        (x, y), w = Pw[i]
        ids, ws = [], []
        for s_, ww in ((x, w[0]), (y, w[1])):
            if s_ < n0:
                ids.append(s_)
                ws.append(ww)
            else:
                si, sw = ext[s_]
                ids += si
                ws += [ww * v for v in sw]
        acc = defaultdict(float)
        for s_, ww in zip(ids, ws):
            acc[s_] += ww
        ext[i] = (list(acc.keys()), list(acc.values()))
        B.add_point(ext[i][0], ext[i][1])
    B.P = np.asarray(P) if len(P) else np.zeros((0, 3))
    for poly, cw, s_, cl in zip(other, OC, Osrc, Ocl):
        B.add_face(poly, [(tuple(d.keys()), tuple(d.values())) for d in cw],
                   s_, cl)
    for tri, cw, s_ in zip(T, TC, Tsrc):
        B.add_face(tri, [(tuple(d.keys()), tuple(d.values())) for d in cw],
                   s_, True)
    out = B.geometry()
    for nm in ("__td_sel__",):
        out.groups[PRIM].pop(nm, None)
    rep["triangles"] = len(T)
    rep["points"] = int(out.npoints)
    return out, rep
