"""
Edge adjacency structure. polyextrude / bevel / dissolve / subdivide / smooth / connectivity
and operators like them all need it.

The model is **half-edge**, deliberately with half-edge index == corner index:

    half-edge i  points from vertex_point[i] to vertex_point[next_corner[i]]
    it belongs to prim  vertex_prim()[i]

That way half-edges line up with vertex attributes naturally, without an extra mapping table. The last
corner of an open polyline has no outgoing edge (next_corner wraps back to the start), excluded with the valid mask.

Caching: connectivity depends only on the three topology arrays (vertex_point / prim_offset / prim_closed),
not on point positions. So adjacency stays valid after transform or smooth and need not be rebuilt; only
set_topology invalidates it. P-dependent quantities such as lengths and dihedral angles are not cached; they are computed on demand.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, PRIM_POLY


class Topology:
    """Pure connectivity. All arrays are read-only."""

    __slots__ = ("nedges", "edge_points", "he_edge", "he_valid", "he_twin",
                 "edge_he_off", "edge_he", "edge_count", "boundary",
                 "pt_edge_off", "pt_edge", "pt_prim_off", "pt_prim")

    def edges_of_point(self, i):
        return self.pt_edge[self.pt_edge_off[i]:self.pt_edge_off[i + 1]]

    def prims_of_point(self, i):
        return self.pt_prim[self.pt_prim_off[i]:self.pt_prim_off[i + 1]]

    def he_of_edge(self, e):
        return self.edge_he[self.edge_he_off[e]:self.edge_he_off[e + 1]]


def _csr(keys, values, n):
    """Group values by keys, return a CSR of (offsets, sorted_values)."""
    order = np.argsort(keys, kind="stable")
    counts = np.bincount(keys, minlength=n)
    off = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    return off, values[order].astype(np.int32)


def build(geo: Geometry) -> Topology:
    t = Topology()
    nv = geo.nvertices
    vp = geo.vertex_point

    if nv == 0:
        t.nedges = 0
        t.edge_points = np.zeros((0, 2), np.int32)
        t.he_edge = np.zeros(0, np.int32)
        t.he_valid = np.zeros(0, bool)
        t.he_twin = np.zeros(0, np.int32)
        t.edge_he_off = np.zeros(1, np.int64)
        t.edge_he = np.zeros(0, np.int32)
        t.edge_count = np.zeros(0, np.int32)
        t.boundary = np.zeros(0, bool)
        t.pt_edge_off = np.zeros(geo.npoints + 1, np.int64)
        t.pt_edge = np.zeros(0, np.int32)
        t.pt_prim_off = np.zeros(geo.npoints + 1, np.int64)
        t.pt_prim = np.zeros(0, np.int32)
        return t

    nxt = geo.next_corner()
    sizes = geo.prim_sizes()

    # the last corner of an open polyline wraps back to the start; that edge does not exist
    last = np.zeros(nv, bool)
    last[geo.prim_offset[1:] - 1] = True
    valid = ~(last & ~np.repeat(geo.prim_closed, sizes))
    t.he_valid = valid

    pair = np.sort(np.stack([vp, vp[nxt]], 1), axis=1)[valid]
    uniq, inv = np.unique(pair, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    t.nedges = len(uniq)
    t.edge_points = uniq.astype(np.int32)

    he_edge = np.full(nv, -1, np.int32)
    he_edge[valid] = inv
    t.he_edge = he_edge

    # edge -> half-edge CSR. Non-manifold edges (shared by 3 or more faces) can be expressed too
    he_idx = np.nonzero(valid)[0].astype(np.int32)
    t.edge_he_off, t.edge_he = _csr(inv.astype(np.int64), he_idx, t.nedges)
    t.edge_count = np.diff(t.edge_he_off).astype(np.int32)
    t.boundary = t.edge_count == 1

    # opposite edge: only manifold edges with exactly two half-edges have one, others get -1
    twin = np.full(nv, -1, np.int32)
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        a = t.edge_he[t.edge_he_off[two]]
        b = t.edge_he[t.edge_he_off[two] + 1]
        twin[a] = b
        twin[b] = a
    t.he_twin = twin

    # point -> edges: each edge contributes to both endpoints
    ep = t.edge_points
    t.pt_edge_off, t.pt_edge = _csr(
        np.concatenate([ep[:, 0], ep[:, 1]]).astype(np.int64),
        np.concatenate([np.arange(t.nedges), np.arange(t.nedges)]),
        geo.npoints)

    # point -> prims (deduplicated: a prim may reference the same point more than once)
    vprim = geo.vertex_prim()
    key = vp.astype(np.int64) * (geo.nprims + 1) + vprim
    _, first = np.unique(key, return_index=True)
    t.pt_prim_off, t.pt_prim = _csr(vp[first].astype(np.int64), vprim[first],
                                    geo.npoints)
    return t


def topology(geo: Geometry) -> Topology:
    """Cached. Repeatedly fetching adjacency for the same geometry does not rebuild it."""
    t = getattr(geo, "_topo", None)
    if t is None:
        t = build(geo)
        try:
            geo._topo = t
        except AttributeError:
            pass
    return t


# ------------------------------------------------------------ P-dependent quantities
def edge_lengths(geo: Geometry) -> np.ndarray:
    t = topology(geo)
    P = geo.get(POINT, "P")
    if t.nedges == 0:
        return np.zeros(0, np.float32)
    return np.linalg.norm(P[t.edge_points[:, 1]] - P[t.edge_points[:, 0]],
                          axis=1).astype(np.float32)


def edge_angles(geo: Geometry) -> np.ndarray:
    """
    (E,) dihedral angles in degrees. 0 = coplanar, 90 = folded at a right angle.
    Boundary and non-manifold edges return 0 -- they have no "angle between two faces".
    Used by grouping by angle, bevel edge selection, and dissolving flat edges.
    """
    from .ops import prim_normals
    t = topology(geo)
    if t.nedges == 0:
        return np.zeros(0, np.float32)
    ang = np.zeros(t.nedges, np.float32)
    two = np.nonzero(t.edge_count == 2)[0]
    if not len(two):
        return ang
    fn = prim_normals(geo)
    vprim = geo.vertex_prim()
    a = fn[vprim[t.edge_he[t.edge_he_off[two]]]]
    b = fn[vprim[t.edge_he[t.edge_he_off[two] + 1]]]
    ang[two] = np.degrees(np.arccos(np.clip((a * b).sum(1), -1.0, 1.0)))
    return ang


# ------------------------------------------------------------ adjacency operators
def point_neighbours(geo: Geometry):
    """(offsets, neighbours) CSR: the other points each point is directly connected to by an edge."""
    t = topology(geo)
    if t.nedges == 0:
        return np.zeros(geo.npoints + 1, np.int64), np.zeros(0, np.int32)
    ep = t.edge_points
    keys = np.concatenate([ep[:, 0], ep[:, 1]]).astype(np.int64)
    vals = np.concatenate([ep[:, 1], ep[:, 0]])
    return _csr(keys, vals, geo.npoints)


def connectivity(geo: Geometry, cls=POINT, name="class"):
    """
    Connected component labels, mirroring Houdini's Connectivity SOP.

    Uses **pointer jumping + label propagation**, without scipy. Each round pushes labels down to the neighbours' minimum,
    then lab = lab[lab] folds the chains in half, converging in O(log n) rounds rather than O(diameter).
    """
    t = topology(geo)
    n = geo.npoints
    lab = np.arange(n, dtype=np.int64)
    if t.nedges:
        a, b = t.edge_points[:, 0], t.edge_points[:, 1]
        for _ in range(64):
            prev = lab
            m = np.minimum(lab[a], lab[b])
            lab = lab.copy()
            np.minimum.at(lab, a, m)
            np.minimum.at(lab, b, m)
            lab = lab[lab]                       # pointer jumping
            if np.array_equal(lab, prev):
                break
    _, comp = np.unique(lab, return_inverse=True)
    comp = comp.reshape(-1).astype(np.int32)

    g = geo.copy()
    if cls == POINT:
        g.set(POINT, name, comp, owned=True)
    else:                                        # a prim takes the component number of its first point
        starts = geo.prim_offset[:-1]
        g.set(PRIM, name, comp[geo.vertex_point[starts]], owned=True)
    return g


def group_boundary(geo: Geometry, name="boundary"):
    """Boundary: edges referenced by only one face. Outputs a point group and a prim group."""
    t = topology(geo)
    g = geo.copy()
    pm = np.zeros(geo.npoints, bool)
    if t.nedges:
        bp = t.edge_points[t.boundary]
        pm[bp.reshape(-1)] = True
    g.set_group(POINT, name, pm)
    if geo.nprims:
        hit = np.zeros(geo.nprims, bool)
        if t.nedges:
            bhe = t.edge_he[np.repeat(t.boundary, t.edge_count)]
            hit[geo.vertex_prim()[bhe]] = True
        g.set_group(PRIM, name, hit)
    return g


def group_by_angle(geo: Geometry, min_angle=30.0, name="crease", cls=POINT):
    """
    Select edges by dihedral angle, then spread the selected edges onto points or faces.

    The edge group class is not implemented here -- that would need another level on Geometry, touching every operator.
    The actual uses (select hard edges for bevel, select flat edges to dissolve, group by crease) all use edges to
    affect points or faces, so spreading one level is enough. Standalone edge groups can come when really needed.
    """
    t = topology(geo)
    g = geo.copy()
    sel = edge_angles(geo) >= float(min_angle)
    if cls == POINT:
        m = np.zeros(geo.npoints, bool)
        if t.nedges:
            m[t.edge_points[sel].reshape(-1)] = True
    else:
        m = np.zeros(geo.nprims, bool)
        if t.nedges and sel.any():
            he = t.edge_he[np.repeat(sel, t.edge_count)]
            m[geo.vertex_prim()[he]] = True
    g.set_group(cls, name, m)
    return g


def quad_grid_index(geo: Geometry, mask=None):
    """
    Recover structured (u,v) indices from a quad mesh, returning (nv, nu, point_index) or None.

    Converting to a NURBS surface needs the row/column structure of the control points, but our topology only stores a bunch of prims,
    with no metadata like "this is an RxC grid". This rebuilds it via **BFS over the dual graph of quads**:
    assign (0,0)(1,0)(1,1)(0,1) to the four corners of the first quad, then propagate along shared edges
    to neighbours, stepping one cell along the normal direction for each edge crossed. Finally check whether the resulting (i,j)
    exactly fill a rectangle -- if not, this is not a structured grid and None is returned.

    The benefit is independence from prim creation order: grids / tubes / hand-assembled quad patches
    are all recognized, whereas guessing "every cols prims form a row" only works for our own Grid.
    """
    t = topology(geo)
    sizes = geo.prim_sizes()
    sel = np.ones(geo.nprims, bool) if mask is None else np.asarray(mask, bool)
    sel = sel & (sizes == 4) & geo.prim_closed
    if not sel.any():
        return None
    prims = np.nonzero(sel)[0]
    inset = np.zeros(geo.nprims, bool)
    inset[prims] = True

    vprim = geo.vertex_prim()
    coord = {}                                  # point -> (i, j)
    start = int(prims[0])
    c0 = geo.prim_points(start)
    for k, (di, dj) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        coord[int(c0[k])] = (di, dj)

    seen = {start}
    stack = [start]
    while stack:
        pi = stack.pop()
        pts = [int(x) for x in geo.prim_points(pi)]
        off = int(geo.prim_offset[pi])
        for k in range(4):
            a, b = pts[k], pts[(k + 1) % 4]
            if a not in coord or b not in coord:
                return None                     # inconsistent propagation, not a regular grid
            twin = t.he_twin[off + k]
            if twin < 0:
                continue
            nb = int(vprim[twin])
            if not inset[nb] or nb in seen:
                continue
            # crossing this edge steps one cell in the direction "away from this quad"
            ca, cprev = coord[a], coord[pts[(k + 3) % 4]]
            step = (ca[0] - cprev[0], ca[1] - cprev[1])
            npts = [int(x) for x in geo.prim_points(nb)]
            # the position of this edge in the neighbour; note the reversed direction
            try:
                ka = npts.index(b)
            except ValueError:
                return None
            if npts[(ka + 1) % 4] != a:
                return None
            # points that already have coordinates must match. Closed surfaces (boxes, uncapped tubes) coming back around
            # would demand two different coordinates for the same point -- which shows it is not a rectangular grid.
            for pt, cc in ((npts[(ka + 2) % 4],
                            (coord[a][0] + step[0], coord[a][1] + step[1])),
                           (npts[(ka + 3) % 4],
                            (coord[b][0] + step[0], coord[b][1] + step[1]))):
                if pt in coord and coord[pt] != cc:
                    return None
                coord[pt] = cc
            seen.add(nb)
            stack.append(nb)

    if len(seen) != len(prims):
        return None                             # there are disconnected pieces
    ii = np.array([v[0] for v in coord.values()])
    jj = np.array([v[1] for v in coord.values()])
    i0, j0 = ii.min(), jj.min()
    nu, nv = ii.max() - i0 + 1, jj.max() - j0 + 1
    if nu * nv != len(coord):
        return None                             # not a full rectangle
    if (nu - 1) * (nv - 1) != len(prims):
        return None                             # face count does not match: a closed surface rather than a patch
    idx = np.full((nv, nu), -1, np.int32)
    for pt, (i, j) in coord.items():
        idx[j - j0, i - i0] = pt
    if (idx < 0).any():
        return None
    return idx


def _edge_weights(P, a, b, method, tri=None):
    """
    (E,) smoothing weights of undirected edges (a, b), computed from the current P.

    The docs only give a one-sentence description of the three modes, no formulas; this implements the three classic umbrella-operator weights
    (Desbrun et al. 1999 / Fujiwara 1995), with the three mode names mapping one-to-one onto them:
      uniform             w = 1                      "distribute points evenly" (also slides tangentially)
      scale_dominant      w = 1 / |e|                Fujiwara's scale-dependent umbrella, preserves relative edge lengths
      curvature_dominant  w = cot α + cot β          cotangent weights (curvature flow), moves almost only along the normal
    Cotangent weights are computed on fan-triangulated triangles; weights on diagonals (edges not in the original topology) are dropped;
    negative weights from obtuse angles are clamped to 0 (otherwise the iteration diverges). Edges on no triangle (curves)
    use 1/|e| -- which is exactly the discretization of 1D curvature flow.
    """
    d = np.linalg.norm(P[b].astype(np.float64) - P[a].astype(np.float64), axis=1)
    inv = np.where(d > 0, 1.0 / np.where(d > 0, d, 1.0), 0.0)
    if method == "scale_dominant":
        return inv
    # curvature_dominant
    w = inv.copy()
    if tri is None or not len(tri):
        return w
    T = tri
    n = len(P)
    Pd = P.astype(np.float64)
    ekey = np.minimum(a, b).astype(np.int64) * n + np.maximum(a, b)
    uk, inv_k = np.unique(ekey, return_inverse=True)
    cot = np.zeros(len(uk))
    on_tri = np.zeros(len(uk), bool)
    for k in range(3):                                 # corner k faces edge (k+1, k+2)
        o, i, j = T[:, k], T[:, (k + 1) % 3], T[:, (k + 2) % 3]
        u, v = Pd[i] - Pd[o], Pd[j] - Pd[o]
        cr = np.linalg.norm(np.cross(u, v), axis=1)
        c = np.where(cr > 0, (u * v).sum(1) / np.where(cr > 0, cr, 1.0), 0.0)
        tk = np.minimum(i, j).astype(np.int64) * n + np.maximum(i, j)
        pos = np.minimum(np.searchsorted(uk, tk), len(uk) - 1)
        hit = uk[pos] == tk                            # diagonals are not topology edges, drop them
        np.add.at(cot, pos[hit], c[hit])
        on_tri[pos[hit]] = True
    inv_k = inv_k.reshape(-1)
    hit = on_tri[inv_k]
    w[hit] = np.maximum(cot[inv_k][hit], 0.0)
    return w


def _smooth_pass(X, src, nbr, w, move, cnt_inv):
    """One round of umbrella smoothing. w None = uniform weights (bitwise identical to the formula before the change)."""
    acc = np.zeros_like(X)
    if w is None:
        np.add.at(acc, src, X[nbr])
        return (X + (acc * cnt_inv - X) * move).astype(X.dtype)
    acc = acc.astype(np.float64)
    ws = np.zeros(len(X))
    np.add.at(acc, src, X[nbr].astype(np.float64) * w[:, None])
    np.add.at(ws, src, w)
    tgt = np.where(ws[:, None] > 0, acc / np.where(ws > 0, ws, 1.0)[:, None], X)
    return (X + (tgt - X) * move).astype(X.dtype)


def _vertex_graph(geo, V):
    """
    Smoothing graph for vertex attributes (uv and the like): vertices on the same point with exactly equal values merge into one node,
    and nodes are connected along polygon edges. So the two sides of a uv seam are different nodes, each smoothed on its own, not
    pulled together; uv island boundaries = node edges used by only one edge.
    Returns (node_of_vertex, node_point, edges (E,2), boundary_node_mask).
    """
    vp = geo.vertex_point.astype(np.int64)
    key = np.concatenate([vp[:, None].astype(np.float64), V.astype(np.float64)], 1)
    _, first, node = np.unique(key, axis=0, return_index=True, return_inverse=True)
    node = node.reshape(-1)
    t = topology(geo)
    nxt = geo.next_corner()
    hv = np.nonzero(t.he_valid)[0]
    e = np.sort(np.stack([node[hv], node[nxt[hv]]], 1), 1)
    ue, ecount = np.unique(e, axis=0, return_counts=True)
    bnd = np.zeros(len(first), bool)
    bnd[ue[ecount == 1].reshape(-1)] = True
    return node, vp[first], ue, bnd


def recompute_affected_normals(g: Geometry, moved) -> Geometry:
    """
    Houdini's Recompute Affected Normals: recompute N only for points / vertices "sharing a face with a moved point"
    (the face normals changed, so their average normals change too); other N stay as they were. Does nothing if there is no N.
    Point N uses the default area weighting, vertex N uses a 60° cusp (what parameters the original N was computed with is unknown).
    Shared by Smooth / Soft Transform.
    """
    from .ops import compute_normals
    moved = np.asarray(moved, bool)
    if not moved.any():
        return g
    vprim = g.vertex_prim()
    hitp = np.zeros(g.nprims, bool)
    hitp[vprim[moved[g.vertex_point]]] = True
    aff = np.zeros(g.npoints, bool)
    aff[g.vertex_point[hitp[vprim]]] = True
    g = g.copy()
    if g.has(POINT, "N"):
        nn = compute_normals(g, "point").get(POINT, "N")
        N = np.array(g.get(POINT, "N"), copy=True)
        N[aff] = nn[aff]
        g.set(POINT, "N", N, owned=True)
    if g.has(VERTEX, "N"):
        nn = compute_normals(g, "vertex").get(VERTEX, "N")
        N = np.array(g.get(VERTEX, "N"), copy=True)
        av = aff[g.vertex_point]
        N[av] = nn[av]
        g.set(VERTEX, "N", N, owned=True)
    return g


def smooth(geo: Geometry, strength=0.5, iterations=5, group=None,
           pin_boundary=True, method="uniform", pin_group_boundary=False,
           constrained_points="", attributes="P", weight_attribute="",
           recompute_normals=False):
    """
    Laplacian smoothing. Each round moves points toward the (weighted) centroid of their neighbours by strength.

    pin_boundary is on by default: boundary points stay put. Without pinning an open mesh shrinks inward every round,
    and after a few rounds of smoothing the edges are eaten away -- an old problem Houdini's Smooth SOP has to deal with too.

    Added in pcg100 against Smooth 2.0:
      method              Uniform / Scale-Dominant / Curvature-Dominant, see _edge_weights
      pin_group_boundary  Group Boundary of Constrained Boundary: additionally pins the outer rim of the selection
                          (selected points with at least one unselected neighbour)
      constrained_points  additionally pinned points (group specifier)
      attributes          attributes to smooth (space separated, wildcards allowed); float point attributes and vertex attributes
      weight_attribute    per-point strength multiplier (Houdini says values can be large, not a [0,1] mask);
                          our strength is the per-round step, clamped to [0, 1] after multiplying, otherwise the explicit iteration diverges
      recompute_normals   when P is smoothed but N is not and the input has N, recompute N of affected points / vertices
    Houdini's Strength is not a per-round step and has no Iterations; Filter Quality is not implemented (the docs give no algorithm).
    """
    from . import groups as _grp
    import fnmatch
    off, nb = point_neighbours(geo)
    cnt = np.diff(off).astype(np.float32)
    if not len(nb):
        return geo.copy()
    if method not in ("uniform", "scale_dominant", "curvature_dominant"):
        raise ValueError(f"method must be uniform / scale_dominant / curvature_dominant, got {method!r}")

    mask = _grp.resolve(geo, POINT, group)
    sel = mask
    if pin_boundary:
        t = topology(geo)
        if t.nedges:
            bp = np.zeros(geo.npoints, bool)
            bp[t.edge_points[t.boundary].reshape(-1)] = True
            mask = mask & ~bp

    src = np.repeat(np.arange(geo.npoints, dtype=np.int64), cnt.astype(np.int64))
    if pin_group_boundary:
        # selected points with at least one unselected neighbour -- the outer rim of the selection
        outer = np.zeros(geo.npoints, bool)
        np.logical_or.at(outer, src, ~sel[nb])
        mask = mask & ~outer                         # unselected points are not in mask to begin with
    mask = mask & ~_grp.resolve(geo, POINT, constrained_points, empty_is_all=False)

    step = mask.astype(np.float64) * float(strength)      # float64: same precision as move before the change
    if str(weight_attribute or "").strip():
        wa = geo.get(POINT, weight_attribute)
        if wa is None or wa.dtype.kind not in "fiu":
            raise KeyError(f"Smooth: no numeric point attribute {weight_attribute!r} (the weight attribute must be a point attribute)")
        step = np.clip(step * np.asarray(wa, np.float64)[:, 0], 0.0, 1.0)
    move = step[:, None]

    # attributes to smooth: P always per point; other float point attributes, vertex attributes
    pats = str(attributes or "").split()
    pt_names, vx_names = [], []
    for nm in geo.names(POINT):
        a = geo.get(POINT, nm)
        if a.dtype.kind == "f" and any(fnmatch.fnmatchcase(nm, p) for p in pats):
            pt_names.append(nm)
    for nm in geo.names(VERTEX):
        a = geo.get(VERTEX, nm)
        if a.dtype.kind == "f" and any(fnmatch.fnmatchcase(nm, p) for p in pats) \
                and nm not in pt_names:
            vx_names.append(nm)
    for p in pats:
        if not any(ch in p for ch in "*?[") and p not in pt_names and p not in vx_names:
            raise KeyError(f"Smooth: no smoothable float point / vertex attribute {p!r}")

    P0 = np.asarray(geo.get(POINT, "P"))
    P = np.array(P0, copy=True)
    vals = {nm: np.array(geo.get(POINT, nm), copy=True) for nm in pt_names if nm != "P"}
    smooth_P = "P" in pt_names
    inv = 1.0 / np.maximum(cnt, 1)[:, None]

    # vertex attributes: one graph per attribute
    vgraphs = {}
    for nm in vx_names:
        V = np.asarray(geo.get(VERTEX, nm))
        node, npnt, ue, bnd = _vertex_graph(geo, V)
        X = np.zeros((len(npnt), V.shape[1]), V.dtype)
        X[node] = V
        nmove = step[npnt].copy()
        if pin_boundary:
            nmove[bnd] = 0.0
        vs = np.concatenate([ue[:, 0], ue[:, 1]])
        vn = np.concatenate([ue[:, 1], ue[:, 0]])
        vcnt = np.bincount(vs, minlength=len(npnt)).astype(np.float32)
        vgraphs[nm] = [X, node, npnt, vs, vn, nmove[:, None],
                       1.0 / np.maximum(vcnt, 1)[:, None]]

    tri = None
    if method == "curvature_dominant":
        tri = geo.triangles().astype(np.int64)
    for _ in range(max(0, int(iterations))):
        w = None if method == "uniform" else _edge_weights(P, src, nb, method, tri)
        for nm in vals:
            vals[nm] = _smooth_pass(vals[nm], src, nb, w, move, inv)
        for nm, (X, node, npnt, vs, vn, vmove, vinv) in vgraphs.items():
            vw = None
            if w is not None:                          # node edges reuse the weight of the corresponding point edge
                vw = _edge_weights(P, npnt[vs], npnt[vn], method, tri)
            vgraphs[nm][0] = _smooth_pass(X, vs, vn, vw, vmove, vinv)
        if smooth_P:
            P = _smooth_pass(P, src, nb, w, move, inv)

    g = geo.copy()
    if smooth_P:
        g.set(POINT, "P", P, owned=True)
    for nm, v in vals.items():
        g.set(POINT, nm, v, owned=True)
    for nm, (X, node, *_r) in vgraphs.items():
        g.set(VERTEX, nm, X[node], owned=True)

    if recompute_normals and smooth_P and "N" not in pt_names and "N" not in vx_names:
        g = recompute_affected_normals(g, np.any(P != P0, axis=1))
    return g
