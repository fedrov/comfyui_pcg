"""
Voronoi 2D -- planar Voronoi diagram, the dual of Delaunay.

Division of labour with `voronoi.py`: that one is 3D **fracturing** (half-spaces cut solids, producing pieces);
this one is 2D **partitioning** (producing cell polygons and their boundary lines). In city generation
the chain "scatter -> Voronoi -> block boundaries -> PolyExpand2D for road width" uses this one.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Approach: not "connect circumcentres into loops", but **half-plane clipping**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The textbook way: each site's Voronoi cell = the loop of the **circumcentres** of its surrounding Delaunay triangles
in angular order. That works for interior sites, but cells of sites on the convex hull are **unbounded**, needing rays to infinity,
then intersection with the boundary, plus handling circumcentres that fall outside the boundary -- lots of degenerate branches.

This takes another route:

    the Voronoi cell of site p = what remains of the boundary region after cutting it with the perpendicular
    bisector of p and each of its **Delaunay neighbours** q.

It rests on the theorem: a Voronoi cell is uniquely determined by its Delaunay neighbours -- half-planes of non-neighbours cannot cut
it. So each cell needs about 6 cuts on average, not N.

Benefits:
- **There are no unbounded cells**. It starts as a bounded boundary region and stays bounded after cutting;
  sites on the convex hull and interior sites go through exactly the same code path.
- Numerically stable. Only "which side of a line is a point" and segment intersection are used, no runaway circumcentres
  (circumcentres of nearly collinear triangles can be very far away, which is where the loop-connecting approach most easily breaks).
- Same idea as the 3D approach in `voronoi.py` (half-space cuts there too), so the two are consistent.

The cost is that each cell is clipped independently, so an edge shared by adjacent cells is computed twice. In floating point it is usually
bit-identical (same inputs, same order of operations), but intersection points on the boundary are not necessarily. So before output
all cell vertices are **welded together** once -- only after welding is it a mesh with shared vertices,
which downstream PolyPath / Join / PolyExpand2D can connect to.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The boundary region must be **convex**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Half-plane clipping (Sutherland-Hodgman) is only correct for convex polygons: a convex one stays convex after a cut,
a concave one can produce self-intersecting results. So with `boundary="polygon"` **convexity is checked and an error raised**,
rather than silently giving a wrong result -- for a concave boundary, compute the Voronoi first and then Boolean / Clip.

The default `boundary="bounds"` is the sites' bounding box (with optional padding), which is convex by nature.
"""
import numpy as np

from .core import Geometry, POINT, PRIM, DETAIL
from .groups import resolve
from . import triangulate2d as _t2
from . import polyexpand2d as _pe

annotations = {}

OUTPUTS = ("cells", "edges")
BOUNDS = ("bounds", "polygon")


# ══════════════════════════════════════════════════════════════════ building blocks
def circumcenters(XY, tri):
    """
    (T,2) circumcentre of each triangle.

    It is **not** used to build loops here (see module notes), but it is the analytic position of the Voronoi vertices;
    tests compare it with the clipped cell vertices. Degenerate (collinear) triangles give nan.
    """
    XY = np.asarray(XY, np.float64)
    tri = np.asarray(tri, np.int64).reshape(-1, 3)
    if not len(tri):
        return np.zeros((0, 2), np.float64)
    a, b, c = XY[tri[:, 0]], XY[tri[:, 1]], XY[tri[:, 2]]
    bx, by = (b - a).T
    cx, cy = (c - a).T
    d = 2.0 * (bx * cy - by * cx)
    out = np.full((len(tri), 2), np.nan)
    ok = np.abs(d) > 1e-300
    b2 = bx[ok] ** 2 + by[ok] ** 2
    c2 = cx[ok] ** 2 + cy[ok] ** 2
    out[ok, 0] = a[ok, 0] + (b2 * cy[ok] - c2 * by[ok]) / d[ok]
    out[ok, 1] = a[ok, 1] + (c2 * bx[ok] - b2 * cx[ok]) / d[ok]
    return out


def neighbor_lists(tri, n):
    """
    Delaunay neighbours of each point (list[set]).

    A Voronoi cell depends only on Delaunay neighbours, so this step reduces the number of cuts per cell
    from N to about 6 on average -- that is why the whole thing runs fast.
    """
    nb = [set() for _ in range(n)]
    tri = np.asarray(tri, np.int64).reshape(-1, 3)
    for i, j, k in tri:
        nb[i].update((int(j), int(k)))
        nb[j].update((int(i), int(k)))
        nb[k].update((int(i), int(j)))
    return nb


def clip_halfplane(poly, nrm, d):
    """
    Clip a convex polygon by nrm·x <= d, keeping the side that satisfies it. Sutherland-Hodgman.

    poly is (K,2). Entirely inside -> returned unchanged (hot path, avoids needless copies);
    entirely outside -> empty.
    """
    if len(poly) == 0:
        return poly
    s = poly @ nrm - d
    keep = s <= 0.0
    if keep.all():
        return poly
    if not keep.any():
        return poly[:0]
    out = []
    K = len(poly)
    for i in range(K):
        j = (i + 1) % K
        if keep[i]:
            out.append(poly[i])
        if keep[i] != keep[j]:
            t = s[i] / (s[i] - s[j])
            out.append(poly[i] + t * (poly[j] - poly[i]))
    return np.asarray(out, np.float64)


def is_convex_ccw(poly, tol=1e-12):
    """Convexity check. Returns (is convex, is counter-clockwise)."""
    P = np.asarray(poly, np.float64).reshape(-1, 2)
    n = len(P)
    if n < 3:
        return False, False
    cr = np.empty(n)
    for i in range(n):
        a, b, c = P[i], P[(i + 1) % n], P[(i + 2) % n]
        cr[i] = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    pos = cr > tol
    neg = cr < -tol
    return not (pos.any() and neg.any()), bool(pos.any())


def cells(XY, boundary, tol=_t2.HULL_TOL):
    """
    (N,2) sites + (K,2) convex boundary polygon (counter-clockwise) -> list[(Ki,2)], one cell per site.

    A site outside the boundary gets an empty cell -- no error; the caller decides what to do
    (the output just skips it).
    """
    XY = np.ascontiguousarray(XY, np.float64).reshape(-1, 2)
    B = np.ascontiguousarray(boundary, np.float64).reshape(-1, 2)
    n = len(XY)
    if n == 0:
        return []
    if n == 1:
        return [B.copy()]

    tri = _t2.delaunay(XY, tol=tol)
    if len(tri):
        nb = neighbor_lists(tri, n)
    else:
        # All collinear / all coincident: no triangles, so no neighbour table.
        # Fall back to "every site cuts against every other site" -- when collinear there are few sites, O(N²) does not matter,
        # and the result is still a **correct** Voronoi (the neighbour table is only a convenience pruning).
        nb = [set(range(n)) - {i} for i in range(n)]

    out = []
    for i in range(n):
        poly = B
        p = XY[i]
        for j in nb[i]:
            q = XY[j]
            nrm = q - p
            d = float(nrm @ (p + q)) * 0.5
            poly = clip_halfplane(poly, nrm, d)
            if len(poly) == 0:
                break
        out.append(np.asarray(poly, np.float64))
    return out


def bounds_polygon(XY, padding=0.0):
    """Bounding box of the sites (counter-clockwise). Convex by nature, hence the default boundary region."""
    XY = np.asarray(XY, np.float64).reshape(-1, 2)
    if not len(XY):
        return np.zeros((0, 2), np.float64)
    lo = XY.min(0) - float(padding)
    hi = XY.max(0) + float(padding)
    # When all sites coincide the bounding box is a point and nothing is cut out -- give it a little thickness as a fallback
    span = hi - lo
    for k in (0, 1):
        if span[k] <= 0.0:
            lo[k] -= 0.5
            hi[k] += 0.5
    return np.array([[lo[0], lo[1]], [hi[0], lo[1]],
                     [hi[0], hi[1]], [lo[0], hi[1]]], np.float64)


# ══════════════════════════════════════════════════════════════════ main entry
def voronoi2d(geo, group="", plane="fit_plane", plane_origin=(0, 0, 0),
              plane_normal=(0, 1, 0), plane_distance=0.0,
              output="cells", boundary="bounds", padding=0.0,
              bounds_geo=None, fuse_tol=1e-6, hull_tol=_t2.HULL_TOL,
              site_attrib="site", interior_group="interior",
              on_failure="fail_with_error"):
    """
    Planar Voronoi diagram.

    output:
        cells   one closed polygon per site
        edges   cell boundaries as deduplicated segments (each a two-point open polyline). Use this for road networks --
                connect PolyPath (PCG) to join them into long polylines, then PolyExpand2D for road width.

    boundary:
        bounds    bounding box of the sites + padding
        polygon   the first closed polygon of the second input. **Must be convex**;
                  non-convex raises an error (half-plane clipping does not hold for concave polygons, see module notes).

    The output points are **new points** (Voronoi vertices) with no correspondence to the input sites, so point attributes
    are not carried over. Each cell gets a `site` prim attribute pointing back to its site's point number; to move site attributes onto
    the cells, use Attribute Copy by that index.
    """
    if geo is None or geo.npoints == 0:
        return geo.copy() if geo is not None else None
    if output not in OUTPUTS:
        raise ValueError(f"Output must be one of {OUTPUTS}")
    if boundary not in BOUNDS:
        raise ValueError(f"Boundary must be one of {BOUNDS}")

    P = np.asarray(geo.get(POINT, "P"), np.float64).reshape(-1, 3)
    sel = resolve(geo, POINT, group) if group else np.ones(len(P), bool)
    idx = np.nonzero(sel)[0]
    if len(idx) < 1:
        raise ValueError(
            f"No sites to use{' (Group filtered out all points)' if group else ''} -- "
            f"Voronoi needs at least one site.")

    XY, basis = _t2.project(P[idx], plane, plane_origin, plane_normal,
                            plane_distance)
    o, e1, e2, nrm = basis

    # Coincident sites must be merged: for two sites at the same position the perpendicular bisector is degenerate,
    # and both cells get cut to nothing -- showing up as "points were scattered but some cells are missing".
    node, _ = _pe.weld(XY, float(fuse_tol)) if float(fuse_tol) > 0 else \
        (np.unique(XY, axis=0, return_inverse=True)[1].reshape(-1), None)
    node = np.asarray(node, np.int64).reshape(-1)
    reps = np.full(int(node.max()) + 1 if len(node) else 0, -1, np.int64)
    for k in range(len(node) - 1, -1, -1):
        reps[node[k]] = k
    SXY = XY[reps]

    # ── boundary region ──────────────────────────────────────────────────────
    if boundary == "bounds":
        B = bounds_polygon(SXY, padding)
    else:
        # These two cases have different fixes, so the messages are separate:
        #   nothing connected   -> connect something
        #   connected but no primitives -> the wrong thing is connected (e.g. a point cloud)
        if bounds_geo is None:
            raise ValueError(
                "Boundary = polygon needs a closed polygon on the second input.\n"
                "  A Circle / Grid / Convex Hull (PCG) all work, "
                "but it **must be convex**.")
        bp = None
        for pi in range(bounds_geo.nprims):
            if bool(bounds_geo.prim_closed[pi]) and \
                    len(bounds_geo.prim_points(pi)) >= 3:
                bp = pi
                break
        if bp is None:
            raise ValueError(
                f"The second input has no closed polygon -- it has {bounds_geo.npoints} points and "
                f"{bounds_geo.nprims} primitives.\n"
                f"  The boundary must be a **closed face / loop**. If a point cloud is connected, first "
                f"connect a Convex Hull (PCG) or Triangulate 2D (PCG) to turn it into a face.")
        BP = np.asarray(bounds_geo.get(POINT, "P"),
                        np.float64)[bounds_geo.prim_points(bp)]
        B = np.column_stack([(BP - o) @ e1, (BP - o) @ e2])
        conv, ccw = is_convex_ccw(B)
        if not conv:
            raise ValueError(
                "The boundary polygon is not convex -- half-plane clipping only holds for convex polygons; "
                "a concave one produces self-intersecting cells.\n"
                "  For a concave boundary: compute the Voronoi with bounds first, "
                "then trim it with Boolean (PCG) or Clip (PCG).\n"
                "  Or connect a Convex Hull (PCG) first to make the boundary convex.")
        if not ccw:
            B = B[::-1]                    # make it counter-clockwise so the clipping test is correct

    cl = cells(SXY, B, tol=hull_tol)

    # ── vertex welding ──────────────────────────────────────────────────────
    # Each cell is clipped independently, so vertices shared by adjacent cells may differ numerically by a tiny amount.
    # Without welding the output is a pile of separate polygons -- PolyPath / Join cannot connect them,
    # and "connecting into a road network" is exactly this node's main use.
    keep = [(i, c) for i, c in enumerate(cl) if len(c) >= 3]
    if not keep:
        if on_failure == "fail_with_error":
            raise ValueError(
                "Not a single cell was cut out -- are all sites outside the boundary region?\n"
                "  This should not happen with Boundary = bounds; with polygon, check whether "
                "the sites are inside that polygon.")
        return geo.copy()

    allv = np.concatenate([c for _, c in keep], 0)
    # The weld tolerance follows the scale: an absolute value would weld the whole diagram into one point on small geometry
    span = float((B.max(0) - B.min(0)).max())
    vnode, _ = _pe.weld(allv, max(span * 1e-9, 1e-12))
    vnode = np.asarray(vnode, np.int64).reshape(-1)
    nv = int(vnode.max()) + 1
    vrep = np.full(nv, -1, np.int64)
    for k in range(len(vnode) - 1, -1, -1):
        vrep[vnode[k]] = k
    VXY = allv[vrep]

    loops, sites, off = [], [], 0
    for i, c in keep:
        loops.append([int(vnode[off + t]) for t in range(len(c))])
        sites.append(int(idx[reps[i]]))
        off += len(c)

    # back to 3D
    P3 = o + VXY[:, 0:1] * e1 + VXY[:, 1:2] * e2

    if output == "cells":
        return _assemble(geo, P3, loops, True, sites, site_attrib, None)

    # ── edges: deduplicated cell boundary segments ──────────────────────────────────────
    cnt = {}
    for lp in loops:
        for a in range(len(lp)):
            u, v = lp[a], lp[(a + 1) % len(lp)]
            if u == v:
                continue
            k = (min(u, v), max(u, v))
            cnt[k] = cnt.get(k, 0) + 1
    segs = sorted(cnt)
    inter = [i for i, k in enumerate(segs) if cnt[k] >= 2]
    return _assemble(geo, P3, [list(k) for k in segs], False, None, "",
                     (interior_group, inter))


def _assemble(geo, P3, loops, closed, sites, site_attrib, group_spec):
    out = Geometry()
    out._resize_points(len(P3))
    out.set(POINT, "P", np.asarray(P3, np.float32), owned=True)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    sz = np.array([len(l) for l in loops], np.int32)
    out.set_topology(
        np.concatenate([np.asarray(l, np.int32) for l in loops])
        if loops else np.zeros(0, np.int32),
        np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
        np.full(len(loops), bool(closed)))
    if sites is not None and site_attrib:
        out.set(PRIM, site_attrib,
                np.asarray(sites, np.int32).reshape(-1, 1), owned=True)
    if group_spec and group_spec[0]:
        name, members = group_spec
        m = np.zeros(len(loops), bool)
        m[np.asarray(members, np.int64)] = True
        out.set_group(PRIM, name, m)
    return out
