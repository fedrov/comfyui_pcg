"""
Measure SOP -- measures area / perimeter / volume / curvature, and colours by value along the way.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Area uses Newell, not a sum over fan triangulation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    area vector = 0.5 * sum(vi x vi+1)        area = |area vector|

For planar polygons this is the exact area (concave ones too); for non-planar ngons it equals "the projected area on the best-fit
plane", a meaningful number. Fan triangulation sums the **absolute values** of each triangle's area,
which on concave polygons counts folded-over parts twice and overestimates.

Volume reuses the same formula: a cone from an arbitrary apex over each face, V = (1/3)*(area vector . v0).
On a closed mesh the sum over faces is exactly the enclosed volume, independent of where the reference point is -- the increments
from moving the reference point cancel out on closed meshes. So for a single face the "volume" mode gives a (signed) cone volume,
and only Accumulate to Total gives the volume people actually want.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Visualized Range defaults to **median +- MAD**, not min/max
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With a colour ramp set by min/max, one distorted face (a thousand times the area of the others) squashes the whole picture into blue.
MAD (median absolute deviation) is insensitive to outliers: Width=6 x MAD means "the ramp covers 3 MADs above and below
the median", so the vast majority of elements land in the discriminating part of the ramp while the outliers hit the ends -- exactly
the picture you want when hunting for them.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve
from . import ramp as _rp

ELEMENTS = ("primitives", "points")
MEASURES = ("area", "perimeter", "volume", "curvature", "gaussian_curvature")
ACCUMULATE = ("per_element", "total")
CENTERS = ("median", "mean", "zero")
WIDTH_MODES = ("mad", "stddev", "absolute")
RAMPS = ("blue_white_red", "grayscale", "heat", "custom")
RAMP_MODES = _rp.MODES

_RAMPS = {
    "blue_white_red": ((0.0, (0.0, 0.1, 0.9)), (0.5, (1.0, 1.0, 1.0)),
                       (1.0, (0.9, 0.1, 0.0))),
    "grayscale": ((0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))),
    "heat": ((0.0, (0.0, 0.0, 0.0)), (0.35, (0.7, 0.0, 0.0)),
             (0.7, (1.0, 0.7, 0.0)), (1.0, (1.0, 1.0, 0.9))),
}

DEFAULT_NAMES = {"area": "area", "perimeter": "perimeter",
                 "volume": "volume", "curvature": "curvature",
                 "gaussian_curvature": "curvature"}


def _by_size(geo, fn):
    """Buckets by prim edge count and vectorizes within each bucket. fn(V, closed) -> (m,) results."""
    out = np.zeros(geo.nprims)
    if geo.nprims == 0 or geo.nvertices == 0:
        return out
    P = geo.get(POINT, "P")
    if P is None:
        return out
    P = P.astype(np.float64)
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    for k in np.unique(sizes):
        if k < 2:
            continue
        for cl in (True, False):
            sel = np.nonzero((sizes == k) & (geo.prim_closed == cl))[0]
            if not len(sel):
                continue
            corner = starts[sel][:, None] + np.arange(k)[None, :]
            out[sel] = fn(P[geo.vertex_point[corner]], cl)
    return out


def area_vectors(geo):
    """Area vector 0.5*sum(vi x vi+1) of each face. (nprims, 3)"""
    out = np.zeros((geo.nprims, 3))
    if geo.nprims == 0 or geo.nvertices == 0:
        return out
    P = geo.get(POINT, "P")
    if P is None:
        return out
    P = P.astype(np.float64)
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    for k in np.unique(sizes):
        if k < 3:
            continue
        sel = np.nonzero((sizes == k) & geo.prim_closed)[0]
        if not len(sel):
            continue
        V = P[geo.vertex_point[starts[sel][:, None] + np.arange(k)[None, :]]]
        out[sel] = 0.5 * np.cross(V, np.roll(V, -1, axis=1)).sum(1)
    return out


def prim_areas(geo):
    return np.linalg.norm(area_vectors(geo), axis=1)


def prim_perimeters(geo):
    def fn(V, closed):
        d = np.diff(V, axis=1)
        L = np.linalg.norm(d, axis=2).sum(1)
        if closed:
            L = L + np.linalg.norm(V[:, 0] - V[:, -1], axis=1)
        return L
    return _by_size(geo, fn)


def prim_volumes(geo, origin=None):
    """Signed cone volume of each face, with origin as the apex."""
    av = area_vectors(geo)
    if geo.nprims == 0 or geo.nvertices == 0:
        return np.zeros(geo.nprims)
    P = geo.get(POINT, "P").astype(np.float64)
    if origin is not None:
        P = P - np.asarray(origin, np.float64).reshape(1, 3)
    v0 = P[geo.vertex_point[geo.prim_offset[:-1].astype(np.int64)]]
    return np.einsum("ij,ij->i", av, v0) / 3.0


def point_areas(geo):
    """Dual area of a point: each adjacent face splits its area equally among its corners."""
    out = np.zeros(geo.npoints)
    if geo.nvertices == 0:
        return out
    a = prim_areas(geo) / np.maximum(geo.prim_sizes(), 1)
    np.add.at(out, geo.vertex_point, a[geo.vertex_prim()])
    return out


def mean_curvature(geo):
    """
    Mean curvature from the cotangent Laplacian, with the sign taken from the point normal.

    Cotangent weights rather than uniform weights: uniform weights (neighbour average minus self) on meshes with uneven triangle density
    read "mesh density" as curvature, giving values even on flat areas. Cotangent weights are the standard form of the discrete Laplace-Beltrami
    operator and are largely independent of the triangulation.
    """
    from . import spatial as _sp
    n = geo.npoints
    L = np.zeros((n, 3))
    A = np.zeros(n)
    tri, _, _ = _sp.tri_soup(geo)
    if not len(tri) or geo.get(POINT, "P") is None:
        return np.zeros(n)
    P = geo.get(POINT, "P").astype(np.float64)
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    for i0, i1, i2 in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        # Corner at i0; the cotangent weight goes to the opposite edge (i1, i2)
        u = P[tri[:, i1]] - P[tri[:, i0]]
        v = P[tri[:, i2]] - P[tri[:, i0]]
        cot = (np.einsum("ij,ij->i", u, v) /
               np.maximum(np.linalg.norm(np.cross(u, v), axis=1), 1e-30))
        d = P[tri[:, i2]] - P[tri[:, i1]]
        np.add.at(L, tri[:, i1], cot[:, None] * d)
        np.add.at(L, tri[:, i2], -cot[:, None] * d)
    np.add.at(A, tri.reshape(-1), np.repeat(area / 3.0, 3))
    N = geo.get(POINT, "N")
    if N is None or N.shape[1] != 3:
        from .ops import compute_normals
        N = compute_normals(geo, add_to="point").get(POINT, "N")
    N = np.asarray(N, np.float64)
    # Take the **component of the Laplacian along the normal**, not its magnitude. On a planar mesh dP is not zero --
    # it is a tangential in-plane drift (present whenever a vertex isn't at its neighbours' cotangent-weighted centroid); taking the magnitude would
    # read that drift as curvature, giving fake curvature all over an irregular planar mesh. Projected onto the normal
    # a plane necessarily gives 0 and a sphere 1/r, with the natural sign "convex is positive".
    return -np.einsum("ij,ij->i", L, N) / np.maximum(4.0 * A, 1e-30)


def angle_defect(geo):
    """
    Angle defect of each point (2*pi - the sum of angles around the point; pi for boundary points) and the area assigned to it.

    Area is the **Voronoi area** (the mixed area of Meyer et al.): for non-obtuse triangles a corner gets the sum of
    (squared lengths of the two adjacent edges x cotangent of the opposite angles) / 8 -- i.e. the three regions the circumcentre cuts the triangle into; for obtuse triangles
    the circumcentre lies outside, so the obtuse corner takes half and the other two a quarter each. More accurate than "a third per corner":
    on an icosphere the 12 points with only 5 neighbours get curvature 15% too high with thirds, only 1% with Voronoi areas.
    """
    from . import spatial as _sp
    from . import topology as _tp
    n = geo.npoints
    tri, _, _ = _sp.tri_soup(geo)
    if not len(tri) or geo.get(POINT, "P") is None:
        return np.zeros(n), np.zeros(n)
    P = geo.get(POINT, "P").astype(np.float64)
    ang = np.zeros(n)
    A = np.zeros(n)
    area = 0.5 * np.linalg.norm(np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]]), axis=1)
    angs, cots = [], []
    for i0, i1, i2 in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        u = P[tri[:, i1]] - P[tri[:, i0]]
        v = P[tri[:, i2]] - P[tri[:, i0]]
        cr = np.linalg.norm(np.cross(u, v), axis=1)
        dt = np.einsum("ij,ij->i", u, v)
        angs.append(np.arctan2(cr, dt))
        cots.append(dt / np.maximum(cr, 1e-30))
        np.add.at(ang, tri[:, i0], angs[-1])
    obtuse = np.stack(angs, 1) > np.pi / 2                      # (T,3) which angle is obtuse
    any_ob = obtuse.any(1)
    for i0, i1, i2 in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        e1 = np.einsum("ij,ij->i", P[tri[:, i1]] - P[tri[:, i0]], P[tri[:, i1]] - P[tri[:, i0]])
        e2 = np.einsum("ij,ij->i", P[tri[:, i2]] - P[tri[:, i0]], P[tri[:, i2]] - P[tri[:, i0]])
        vor = (e1 * cots[i2] + e2 * cots[i1]) / 8.0             # edge (i0,i1) is opposite angle i2, edge (i0,i2) opposite angle i1
        share = np.where(any_ob, np.where(obtuse[:, i0], area / 2.0, area / 4.0), vor)
        np.add.at(A, tri[:, i0], share)
    t = _tp.topology(geo)
    full = np.full(n, 2.0 * np.pi)
    full[np.unique(t.edge_points[t.edge_count == 1].reshape(-1))] = np.pi
    return np.where(A > 0, full - ang, 0.0), A


def gaussian_curvature(geo):
    """
    Gaussian curvature: angle defect / area (see angle_defect). Flat areas have an angle sum of exactly 2*pi -> 0; a sphere of radius r -> 1/r^2;
    a saddle -> negative. Unlike mean curvature it doesn't care which way the mesh bends (a cylinder is 0 -- any surface that can be flattened without stretching is 0).
    Boundary points have no "full ring"; following the discrete geodesic curvature, pi replaces 2*pi: a straight boundary -> 0.
    """
    d, A = angle_defect(geo)
    return d / np.where(A > 0, A, 1.0)


def _ramp(t, name, custom="", mode="linear"):
    """
    Colour ramp: a built-in name, or a custom ramp as one line of text.

    Custom syntax "position:r,g,b" separated by spaces, e.g.
        0:0,0,0.5   0.4:0,0.8,0.2   1:1,1,0.6
    ComfyUI has no draggable ramp widget, and ramp data doesn't fit into a float widget either.
    The text form can actually be copy-pasted, put under version control and assembled upstream with expressions.
    """
    if str(name).strip() == "custom":
        pos, val = _rp.parse(custom, 3)
    else:
        stops = _RAMPS.get(str(name).strip())
        if stops is None:
            raise ValueError(
                f"Colour ramp must be one of {RAMPS}; with custom, write a line like "
                f"\"0:0,0,0.5  1:1,1,0.6\" in Custom Ramp.")
        pos = np.array([x[0] for x in stops])
        val = np.array([x[1] for x in stops])
    return _rp.apply(t, pos, val, mode)


def visual_range(vals, use_min=False, min_value=-1.0, use_max=False,
                 max_value=1.0, use_width=True, width=6.0, width_mode="mad",
                 center="median"):
    """Decides the range the colour ramp covers. Returns (lo, hi)."""
    if not len(vals):
        return 0.0, 1.0
    if center == "median":
        c = float(np.median(vals))
    elif center == "mean":
        c = float(np.mean(vals))
    elif center == "zero":
        c = 0.0
    else:
        raise ValueError(f"Center must be one of {CENTERS}")
    if width_mode == "mad":
        s = float(np.median(np.abs(vals - np.median(vals))))
    elif width_mode == "stddev":
        s = float(np.std(vals))
    elif width_mode == "absolute":
        s = 1.0
    else:
        raise ValueError(f"Width unit must be one of {WIDTH_MODES}")
    half = 0.5 * float(width) * s
    if half <= 0:                                # all equal: give a non-collapsed range
        half = max(abs(c) * 0.5, 1e-6)
    lo, hi = (c - half, c + half) if use_width else (float(np.min(vals)),
                                                     float(np.max(vals)))
    if use_min:
        lo = float(min_value)
    if use_max:
        hi = float(max_value)
    if hi <= lo:
        hi = lo + 1e-9
    return lo, hi


def measure(geo, group="", element_type="primitives", measurement="area",
            accumulate="per_element", position_attrib="P",
            attrib_name="", total_attrib="", range_group="",
            use_min=False, min_value=-1.0, use_max=False, max_value=1.0,
            use_width=True, width=6.0, width_mode="mad", center="median",
            color_ramp="blue_white_red", custom_ramp="", ramp_mode="linear",
            color_attrib="", bake_range=False, remap_min=0.0, remap_max=1.0):
    """
    The measured value is written as attrib_name; with color_attrib named it also colours by Visualized Range;
    with total_attrib given, the total is written as a detail attribute.

    With bake_range=True the output attribute is remapped to [remap_min, remap_max] -- corresponding to Houdini's
    Bake Visualized Range Into Output, for use downstream as a 0..1 mask.
    """
    if geo is None:
        return Geometry()
    if element_type not in ELEMENTS:
        raise ValueError(f"Element Type must be one of {ELEMENTS}")
    if measurement not in MEASURES:
        raise ValueError(f"Measure must be one of {MEASURES}")
    if accumulate not in ACCUMULATE:
        raise ValueError(f"Accumulate must be one of {ACCUMULATE}")
    cls = PRIM if element_type == "primitives" else POINT
    if cls == POINT and measurement in ("perimeter", "volume"):
        raise ValueError(
            f"'{measurement}' is a primitive quantity and meaningless on points. Switch Element Type to "
            f"Primitives, or Measure to area / curvature / gaussian_curvature.")

    g = geo.copy()
    pos = str(position_attrib).strip() or "P"
    if pos != "P":
        a = geo.get(POINT, pos)
        if a is None or a.shape[1] != 3:
            have = sorted(geo.attribs[POINT].keys())
            raise KeyError(f"point has no 3D position attribute '{pos}'. Existing: {have}")
        g = g.copy()
        g.set(POINT, "P", a)                     # measure with a different set of coordinates

    if measurement == "area":
        vals = prim_areas(g) if cls == PRIM else point_areas(g)
    elif measurement == "perimeter":
        vals = prim_perimeters(g)
    elif measurement == "volume":
        vals = prim_volumes(g)
    else:
        h = mean_curvature(g) if measurement == "curvature" else gaussian_curvature(g)
        if cls == POINT:
            vals = h
        else:                                    # curvature on primitives = average of the corners
            vals = np.zeros(g.nprims)
            if g.nvertices:
                np.add.at(vals, g.vertex_prim(), h[g.vertex_point])
                vals /= np.maximum(g.prim_sizes(), 1)

    sel = resolve(geo, cls, group)
    out = np.where(sel, vals, 0.0)
    name = str(attrib_name).strip() or DEFAULT_NAMES[measurement]
    total = float(out[sel].sum()) if sel.any() else 0.0

    g = geo.copy()
    if accumulate == "total":
        out = np.where(sel, total, 0.0)

    lo, hi = visual_range(out[sel] if sel.any() else out, use_min, min_value,
                          use_max, max_value, use_width, width, width_mode,
                          center)
    t = np.clip((out - lo) / (hi - lo), 0.0, 1.0)
    inrange = sel & (out >= lo) & (out <= hi)    # must be computed before baking
    if str(color_attrib).strip():
        cd = g.get(POINT if cls == POINT else PRIM, "Cd")
        base = (np.ones((geo.count(cls), 3)) if cd is None or cd.shape[1] != 3
                else cd.astype(np.float64))
        base[sel] = _ramp(t[sel], color_ramp, custom_ramp, ramp_mode)
        g.set(cls, str(color_attrib).strip(), base.astype(np.float32),
              owned=True)
    if bake_range:
        out = float(remap_min) + t * (float(remap_max) - float(remap_min))
    g.set(cls, name, out[:, None].astype(np.float32), owned=True)
    if str(total_attrib).strip():
        g.set(DETAIL, str(total_attrib).strip(), np.array([[total]],
                                                          np.float32))
    if str(range_group).strip():
        g.set_group(cls, str(range_group).strip(), inrange)
    return g
