"""
pcg79: Primitive Split, Edge Cusp, PolySplit -- cutting open / splitting points in the topology.

━━ Primitive Split
Splits points by a prim attribute: when a point is shared by several faces whose attribute values differ (difference > Tolerance, chained comparison),
the point is split into several, one per class of faces. String attributes compare by equality. Faces outside group still share points with each other
(they count as one class), but are separated from faces inside the group -- equivalent to "cut out the group and split it by attribute".
Typical use: cut a mesh open along the boundaries by name / material id, so the normals and uvs of the pieces don't bleed into each other.

━━ Edge Cusp
Cuts open along edges: faces on both sides of the selected edges no longer share endpoints. Edges is an edge group (empty = all edges); with Min Angle > 0
the dihedral angle must also be >= this angle (0 = edge group only). After splitting, the faces around each point are divided into fans by "can be connected
across uncut edges", one point per fan; points not touching a cut edge are untouched (a bow-tie where two faces meet at only one point
is not split either -- that is not what this node is for). Compute Normals also writes area-weighted point normals, so the cut edges
become hard edges. Facet's split-points-by-angle option is a special case of it (edge group = all, Min Angle = threshold).

━━ PolySplit
(Since pcg100 there is also Path Type = Edge Loop, Houdini's location syntax, Edge Percentage; see poly_split's docstring)
Cuts faces at the given locations. Locations are space-separated:
    12  or  p12        point 12
    3-7@0.25           at t = 0.25 on the edge from point 3 to point 7 (0 at the 3 end); @ omitted = midpoint
Two adjacent locations must be on the same face, which is cut in two along the line between them; if the two points already form an edge it is skipped.
New points on an edge are inserted into **all** faces on both sides of that edge (no T-junctions), with point and vertex attributes interpolated by t.
Close Path connects the last location back to the first. With Edge Group non-empty, the new edges are written as an edge group.
Two adjacent locations not on the same face raise an error (no pathfinding -- when there are several paths any guess may be wrong;
just give a few more locations in between).
"""
from __future__ import annotations

import re

import numpy as np

from .core import POINT, PRIM, VERTEX, is_string
from .groups import resolve, resolve_edges, edge_mask
from .topology import topology, edge_angles
from .facet import _labels, _split_points


# ═══════════════════════════════════════════════════════ Primitive Split
def primitive_split(geo, attribute="name", tolerance=0.0, group=""):
    """Returns (geometry, report)."""
    name = str(attribute).strip()
    a = geo.get(PRIM, name)
    if a is None:
        raise KeyError(f"No attribute '{name}' on prim. Existing: "
                       f"{sorted(geo.attribs[PRIM].keys()) or '(none)'}")
    nv = geo.nvertices
    if not nv:
        return geo.copy(), {"split_points": 0}
    if is_string(a):
        _, code = np.unique(np.asarray(a)[:, 0], return_inverse=True)
        A = code.reshape(-1, 1).astype(np.float64)
        tol = 0.0
    else:
        A = np.asarray(a, np.float64)
        tol = float(tolerance)
    vp = geo.vertex_point.astype(np.int64)
    vprim = geo.vertex_prim().astype(np.int64)
    inside = resolve(geo, PRIM, group)[vprim]
    Av = np.where(inside[:, None], A[vprim], 0.0)
    keys = tuple(Av[:, c] for c in range(Av.shape[1] - 1, -1, -1))
    order = np.lexsort(keys + (inside, vp))
    vs, As, ins = vp[order], Av[order], inside[order]
    new = np.ones(nv, bool)
    if nv > 1:
        same = (vs[1:] == vs[:-1]) & (ins[1:] == ins[:-1])
        close = np.abs(As[1:] - As[:-1]).max(1) <= tol
        new[1:] = ~(same & close)
    cls = np.empty(nv, np.int64)
    cls[order] = np.cumsum(new) - 1
    before = geo.npoints
    g = _split_points(geo, cls, int(cls.max()) + 1)
    return g, {"split_points": int(g.npoints - before)}


# ═══════════════════════════════════════════════════════════ Edge Cusp
def edge_cusp(geo, edges="", min_angle=0.0, compute_normals=False):
    """Returns (geometry, report)."""
    nv = geo.nvertices
    t = topology(geo)
    if not nv or not t.nedges:
        return geo.copy(), {"cut_edges": 0, "split_points": 0}
    cut = edge_mask(geo, resolve_edges(geo, edges))
    if float(min_angle) > 0:
        cut &= edge_angles(geo) >= float(min_angle)
    vp = geo.vertex_point.astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)
    cnt = np.diff(t.edge_he_off)
    eid = np.repeat(np.arange(t.nedges), cnt)
    he = t.edge_he.astype(np.int64)
    first = he[t.edge_he_off[:-1]][eid]
    keep = ~cut[eid]          # includes half-edges paired with themselves: a no-op in union-find, no need to exclude them
    ha, hb = first[keep], he[keep]
    same_dir = vp[ha] == vp[hb]
    pairs = [np.stack([ha, np.where(same_dir, hb, nxt[hb])], 1),
             np.stack([nxt[ha], np.where(same_dir, nxt[hb], hb)], 1)]
    # Points not touching a cut edge: all corners bound together (bow-ties and the like are not split)
    touched = np.zeros(geo.npoints, bool)
    touched[t.edge_points[cut].reshape(-1)] = True
    free = np.nonzero(~touched[vp])[0]
    if len(free) > 1:
        o = free[np.argsort(vp[free], kind="stable")]
        s = vp[o[:-1]] == vp[o[1:]]
        pairs.append(np.stack([o[:-1][s], o[1:][s]], 1))
    cls, k = _labels(nv, np.concatenate(pairs).astype(np.int64))
    before = geo.npoints
    g = _split_points(geo, cls, k)
    if compute_normals:
        from .ops import compute_normals as _cn
        g = _cn(g, "point")
    return g, {"cut_edges": int(cut.sum()), "split_points": int(g.npoints - before)}


# ═══════════════════════════════════════════════════════════ PolySplit
_LOC_P = re.compile(r"^p?(\d+)$")
_LOC_E = re.compile(r"^(\d+)-(\d+)(?:@([-+0-9.eE]+))?$")
# pcg100: Houdini's own syntax (Split Locations in the PolySplit docs): pa-b / pa-b:t by point numbers,
# avb = vertex b of prim a, aeb / aeb:t = edge b of prim a
_LOC_HE = re.compile(r"^p(\d+)-(\d+)(?::([-+0-9.eE]+))?$")
_LOC_HV = re.compile(r"^(\d+)v(\d+)$")
_LOC_HPE = re.compile(r"^(\d+)e(\d+)(?::([-+0-9.eE]+))?$")
_LOC_HF = re.compile(r"^(\d+)f:")
SPLIT_PATH = ("shortest_path", "edge_loop")


def _parse_locations(spec, npts, geo=None):
    out = []

    def edge(tok, a, b, tt):
        if max(a, b) >= npts or a == b:
            raise ValueError(f"Location '{tok}': invalid point numbers")
        if not 0.0 <= tt <= 1.0:
            raise ValueError(f"Location '{tok}': t must be within 0..1")
        if tt <= 1e-9:
            out.append(("p", a))
        elif tt >= 1 - 1e-9:
            out.append(("p", b))
        else:
            out.append(("e", a, b, tt))

    def prim_pts(tok, a):
        if geo is None or a >= geo.nprims:
            raise ValueError(f"Location '{tok}': prim number out of range")
        return [int(x) for x in geo.prim_points(a)]

    for tok in str(spec).replace(",", " ").split():
        m = _LOC_P.match(tok)
        if m:
            p = int(m.group(1))
            if p >= npts:
                raise ValueError(f"Location '{tok}': point number out of range ({npts} points in total)")
            out.append(("p", p))
            continue
        m = _LOC_E.match(tok) or _LOC_HE.match(tok)
        if m:
            edge(tok, int(m.group(1)), int(m.group(2)),
                 float(m.group(3)) if m.group(3) else 0.5)
            continue
        m = _LOC_HV.match(tok)
        if m:
            pts = prim_pts(tok, int(m.group(1)))
            if int(m.group(2)) >= len(pts):
                raise ValueError(f"Location '{tok}': vertex number out of range")
            out.append(("p", pts[int(m.group(2))]))
            continue
        m = _LOC_HPE.match(tok)
        if m:
            # The docs only say "edge b of prim a", not how edges are numbered: from vertex b to the next vertex,
            # with t measured from the vertex b end
            pts = prim_pts(tok, int(m.group(1)))
            b = int(m.group(2))
            if b >= len(pts) or len(pts) < 2:
                raise ValueError(f"Location '{tok}': edge number out of range")
            edge(tok, pts[b], pts[(b + 1) % len(pts)],
                 float(m.group(3)) if m.group(3) else 0.5)
            continue
        if _LOC_HF.match(tok):
            raise ValueError(f"Location '{tok}': locations inside faces (af:u,v) are not implemented; only points and edges can be cut")
        raise ValueError(f"Unrecognized location '{tok}' (syntax: 12 / p12 / 3-7@0.25 / p3-7:0.25 / "
                         f"0v2 / 0e1:0.25)")
    return out


def _cut_piece(pts, cor, A, Bp):
    """Cuts one face (point list, corner list) in two along A-B; returns None if A and B are adjacent or not both on the face."""
    if A not in pts or Bp not in pts:
        return None
    i, j = pts.index(A), pts.index(Bp)
    m = len(pts)
    if (j - i) % m in (1, m - 1):
        return None
    if i > j:
        i, j = j, i
    return (([*pts[i:j + 1]], [*cor[i:j + 1]]),
            ([*pts[j:], *pts[:i + 1]], [*cor[j:], *cor[:i + 1]]))


def _quad_ring(geo, a, b):
    """
    The quad ring starting from directed edge a->b: each quad crossed steps to the opposite edge. Returns
    ([directed edges (x, y)], [(face number, index in the ring of the entry edge, index of the exit edge)], whether it looped back to the start).
    Directed edge directions correspond all the way (between x and the next x is a side edge of a quad), so "t from the x end" is
    on the same side around the whole ring. Stops at non-quads, boundaries and non-manifold edges (> 2 faces).
    """
    faces = {}
    for f in range(geo.nprims):
        if not geo.prim_closed[f]:
            continue
        pts = [int(x) for x in geo.prim_points(f)]
        for i in range(len(pts)):
            x, y = pts[i], pts[(i + 1) % len(pts)]
            faces.setdefault((min(x, y), max(x, y)), []).append((f, i, pts))
    key = lambda x, y: (min(x, y), max(x, y))                    # noqa: E731
    if key(a, b) not in faces:
        raise ValueError(f"Location {a}-{b}: no edge between points {a} and {b}")
    seed = faces[key(a, b)]
    if len(seed) > 2:
        raise ValueError(f"Location {a}-{b}: this edge has {len(seed)} faces (non-manifold), the loop can't be walked")
    ring = [(a, b)]
    quads = []                                   # (face number, entry directed edge, exit directed edge)
    seen = set()

    def walk(first_face, head):
        """head = True: new edges appended at the end of ring; False: at the start. Returns whether it looped back to the start."""
        x, y = a, b
        f, i, pts = first_face
        while True:
            if len(pts) != 4:
                return False
            if f in seen:
                raise ValueError("Edge Loop: this loop crosses itself (the same quad is passed through twice); not implemented")
            seen.add(f)
            # This edge in the face is pts[i]->pts[i+1]; the opposite edge is pts[i+2]->pts[i+3], pts[i] faces pts[i+3]
            if pts[i] == x:
                nx, ny = pts[(i + 3) % 4], pts[(i + 2) % 4]
            else:
                nx, ny = pts[(i + 2) % 4], pts[(i + 3) % 4]
            if key(nx, ny) == key(a, b):
                quads.append((f, (x, y), (a, b)))
                return True
            quads.append((f, (x, y), (nx, ny)))
            if head:
                ring.append((nx, ny))
            else:
                ring.insert(0, (nx, ny))
            nb = [r for r in faces[key(nx, ny)] if r[0] != f]
            if len(nb) != 1:
                return False
            x, y = nx, ny
            f, i, pts = nb[0]

    closed = walk(seed[0], True)
    if not closed and len(seed) == 2:
        walk(seed[1], False)
    at = {e: r for r, e in enumerate(ring)}
    return ring, [(f, at[e0], at[e1]) for f, e0, e1 in quads], closed


def _edge_loops(geo, locs, num_loops, pct, edge_group):
    """
    Path Type = Edge Loop: each location on an edge produces a ring (or a run) of loop edges. Locations are processed in turn, each on the
    result of the previous; locations falling on an already walked loop are skipped (that edge has already been cut).
    """
    from .meshedit import _Build
    n = max(1, int(num_loops))
    rep = {"new_points": 0, "cuts": 0, "loops": 0, "skipped": 0, "closed_loops": 0}
    done = set()
    cuts_all = []
    g = geo
    for loc in locs:
        if loc[0] != "e":
            raise ValueError("Edge Loop: locations must be on edges (3-7@0.25 / p3-7:0.25 / 0e1), "
                             "not points")
        _, a, b, tt = loc
        if (min(a, b), max(a, b)) in done:
            rep["skipped"] += 1
            continue
        ring, quads, closed = _quad_ring(g, a, b)
        if not quads:
            raise ValueError(f"Location {a}-{b}: no quads on either side of this edge, no loop possible")
        done.update((min(x, y), max(x, y)) for x, y in ring)
        # Docs: Number of Loops is how many loops "evenly spaced along the selected edge"; with 1 loop the location's own t (or Edge Percentage) is used
        ts = [k / (n + 1) for k in range(1, n + 1)] if n > 1 else \
            [tt if pct is None else pct]
        B = _Build(g)
        newp = [[B.add_point([x, y], [1.0 - t, t]) for t in ts] for (x, y) in ring]
        ins = {(min(x, y), max(x, y)): (x, y, newp[r]) for r, (x, y) in enumerate(ring)}
        qf = {f: (i0, i1) for f, i0, i1 in quads}
        vp = g.vertex_point.astype(np.int64)
        off = g.prim_offset.astype(np.int64)
        for f in range(g.nprims):
            cs = np.arange(off[f], off[f + 1])
            cl = bool(g.prim_closed[f])
            pts, cor = [], []
            m = len(cs)
            for i in range(m):
                c = int(cs[i])
                pts.append(int(vp[c]))
                cor.append(c)
                if i == m - 1 and not cl:
                    break
                c2 = int(cs[(i + 1) % m])
                u0, v0 = int(vp[c]), int(vp[c2])
                hit = ins.get((min(u0, v0), max(u0, v0)))
                if hit is None:
                    continue
                x, y, ps = hit
                fwd = u0 == x
                for k in (range(len(ts)) if fwd else range(len(ts) - 1, -1, -1)):
                    tau = ts[k] if fwd else 1.0 - ts[k]
                    pts.append(ps[k])
                    cor.append(((c, c2), (1.0 - tau, tau)))
            pieces = [(pts, cor)]
            if f in qf:
                i0, i1 = qf[f]
                for k in range(len(ts)):
                    A, Bp = newp[i0][k], newp[i1][k]
                    for pi, (pp, cc) in enumerate(pieces):
                        two = _cut_piece(pp, cc, A, Bp)
                        if two is not None:
                            pieces[pi:pi + 1] = list(two)
                            cuts_all.append((A, Bp))
                            rep["cuts"] += 1
                            break
            for pp, cc in pieces:
                B.add_face(pp, cc, f, cl)
        # Points are only appended at the end and existing point numbers don't change, so edge endpoint numbers recorded by earlier loops are still valid here
        g = B.geometry()
        rep["new_points"] += len(ring) * len(ts)
        rep["loops"] += len(ts)
        rep["closed_loops"] += len(ts) if closed else 0
    eg = str(edge_group).strip()
    if eg:
        g.set_edge_group(eg, np.asarray(cuts_all, np.int32).reshape(-1, 2))
    return g, rep


def poly_split(geo, locations="", close_path=False, edge_group="",
               path_type="shortest_path", num_loops=1, use_edge_percentage=False,
               edge_percentage=0.5):
    """
    Returns (geometry, report). Added in pcg100 to match Houdini:
      path_type  shortest_path = the original behaviour (the name is Houdini's, but we **don't do pathfinding**: two adjacent locations
                 must be on the same face); edge_loop = from each location on an edge, insert a loop of edges along the quad ring
      num_loops  read only by Edge Loop: > 1 inserts loops evenly at k/(n+1) along the edge
      use_edge_percentage / edge_percentage  all locations on edges use the same t instead (Houdini's
                 Edge Percentage); not read for multi-loop Edge Loop (locations are evenly spaced then)
    """
    from .meshedit import _Build
    if path_type not in SPLIT_PATH:
        raise ValueError(f"Path Type must be one of {SPLIT_PATH}")
    locs = _parse_locations(locations, geo.npoints, geo)
    pct = None
    if use_edge_percentage:
        pct = float(edge_percentage)
        if not 0.0 < pct < 1.0:
            raise ValueError("Edge Percentage must be between 0 and 1 (exclusive)")
    if path_type == "edge_loop":
        if not locs:
            raise ValueError("Locations needs at least one location on an edge")
        return _edge_loops(geo, locs, num_loops, pct, edge_group)
    if pct is not None:
        locs = [(l[0], l[1], l[2], pct) if l[0] == "e" else l for l in locs]
    if len(locs) < 2:
        raise ValueError("Locations needs at least two locations")
    t = topology(geo)
    n1 = geo.npoints + 1
    ek = {int(a) * n1 + int(b): e
          for e, (a, b) in enumerate(np.sort(t.edge_points, 1).astype(np.int64))}
    B = _Build(geo)
    # New points on edges: only one per edge and location
    on_edge = {}               # edge number -> [(parameter along min->max, new point number)]
    path = []
    for loc in locs:
        if loc[0] == "p":
            path.append(loc[1])
            continue
        _, a, b, tt = loc
        lo, hi = min(a, b), max(a, b)
        e = ek.get(lo * n1 + hi)
        if e is None:
            raise ValueError(f"Location {a}-{b}@{tt}: no edge between points {a} and {b}")
        u = tt if a == lo else 1.0 - tt
        lst = on_edge.setdefault(e, [])
        hit = [p for (uu, p) in lst if abs(uu - u) <= 1e-9]
        if hit:
            path.append(hit[0])
            continue
        p = B.add_point([lo, hi], [1.0 - u, u])
        lst.append((u, p))
        path.append(p)
    # Each face: insert new points on its edges
    vp = geo.vertex_point.astype(np.int64)
    off = geo.prim_offset.astype(np.int64)
    faces = []                 # [point number list, corner list, source prim, closed]
    for f in range(geo.nprims):
        cs = np.arange(off[f], off[f + 1])
        closed = bool(geo.prim_closed[f])
        pts, cor = [], []
        m = len(cs)
        for i in range(m):
            c = int(cs[i])
            pts.append(int(vp[c]))
            cor.append(c)
            if i == m - 1 and not closed:
                break
            c2 = int(cs[(i + 1) % m])
            u0, v0 = int(vp[c]), int(vp[c2])
            e = ek.get(min(u0, v0) * n1 + max(u0, v0))
            if e is None or e not in on_edge:
                continue
            ins = sorted(on_edge[e], reverse=(u0 > v0))
            for (uu, p) in ins:
                tau = uu if u0 < v0 else 1.0 - uu      # parameter along u0 -> v0
                pts.append(p)
                cor.append(((c, c2), (1.0 - tau, tau)))
        faces.append([pts, cor, f, closed])
    # Cut segment by segment
    pairs = list(zip(path[:-1], path[1:]))
    if close_path and len(path) > 2:
        pairs.append((path[-1], path[0]))
    cuts, skipped = [], 0
    for (A, Bp) in pairs:
        if A == Bp:
            continue
        done = False
        adjacent = False
        for fi, (pts, cor, src, closed) in enumerate(faces):
            if not closed or A not in pts or Bp not in pts:
                continue
            i, j = pts.index(A), pts.index(Bp)
            m = len(pts)
            if (j - i) % m in (1, m - 1):
                adjacent = True
                continue
            if i > j:
                i, j = j, i
            f1 = ([*pts[i:j + 1]], [*cor[i:j + 1]])
            f2 = ([*pts[j:], *pts[:i + 1]], [*cor[j:], *cor[:i + 1]])
            faces[fi] = [f1[0], f1[1], src, True]
            faces.insert(fi + 1, [f2[0], f2[1], src, True])
            cuts.append((A, Bp))
            done = True
            break
        if not done:
            if adjacent:
                skipped += 1
                continue
            raise ValueError(f"Locations {A} and {Bp} are not on the same face: PolySplit only cuts "
                             f"within a face; give a few more locations in between")
    for pts, cor, src, closed in faces:
        B.add_face(pts, cor, src, closed)
    g = B.geometry()
    eg = str(edge_group).strip()
    if eg:
        g.set_edge_group(eg, np.asarray(cuts, np.int32).reshape(-1, 2))
    return g, {"new_points": int(B.np - B.n0), "cuts": len(cuts),
               "already_edges": skipped}
