"""
Extract Centroid SOP -- condenses each piece of geometry into one point.

Pieces come from pieces.py (the For-Each iteration source), so splitting by name / by class /
by connected piece / by primitive / by point is **the same implementation** in both nodes, and you never get
"For-Each thinks there are 5 pieces, Extract Centroid thinks 6".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Center of Mass is **area-weighted**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A point average is biased by mesh density: the same box with one face subdivided into 100 sections and the other five a single quad each
has a point average clearly pulled towards the subdivided face. Area weighting is independent of mesh density; that is the real "centroid".

Algorithmically it uses fan triangulation + **signed** area: for simple polygons the sum of signed areas equals exactly the
polygon area, and the weighted centroid equals exactly the polygon centroid -- also for concave ones, no ear clipping needed.
(This is an identity of the triangulation, independent of whether the triangles fall inside or outside the shape.)

One deviation from Houdini: for **closed** pieces Houdini computes the volume centroid; here it is always the surface
area centroid. They coincide on symmetric parts; asymmetric solid pieces will differ. A volume centroid needs the
divergence theorem machinery first; worth adding once there is a separate Measure SOP.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, DETAIL, is_string
from .ops import prim_normals, match_names
from . import pieces as _pieces

METHODS = ("center_of_mass", "bounding_box", "average_position")


def _piece_labels(geo, run_over, piece_attrib, piece_elements, group):
    """
    Returns (element class, piece number per element, piece count, value per piece).
    detail mode means "the whole geometry is one piece".
    """
    if run_over == "detail":
        # The whole geometry (within the group) is one piece. Before pcg85 detail ignored group and counted everything
        elem = "primitives" if geo.nprims else "points"
        lab = np.zeros(max(geo.count(PRIM if geo.nprims else POINT), 0), np.int64)
        if str(group or "").strip():
            from .groups import resolve
            m = resolve(geo, PRIM if geo.nprims else POINT, group)
            lab[~m] = -1
            if not m.any():
                return elem, lab, 0, []
        return elem, lab, 1, [0]

    elem, order, starts, values = _pieces.plan(
        geo, run_over, piece_attrib, piece_elements, 0, group)
    cls = POINT if elem == "points" else PRIM
    lab = np.full(geo.count(cls), -1, np.int64)
    if order is not None and len(values):
        for i in range(len(values)):
            lab[order[int(starts[i]):int(starts[i + 1])]] = i
    return elem, lab, len(values), values


def _centroids(geo, elem, lab, nblk, method):
    """One (3,) centroid per piece."""
    P = geo.get(POINT, "P").astype(np.float64)
    out = np.zeros((nblk, 3))
    if nblk == 0:
        return out

    # First compute a "point average"; it is both the answer for average_position and the fallback for other methods
    # When pieces are primitives one point can belong to several pieces (adjacent primitives share points): dedupe by (piece, point) pairs before averaging.
    # It used to be "stamp one piece number on each point", so shared points only counted for the last piece written -- extracting per-primitive centres
    # then got neighbouring centres all wrong (on corner points, even the origin); that is how modular building slots went crooked
    if elem == "points":
        pl, pp = lab, np.arange(geo.npoints)
    else:
        vl = lab[geo.vertex_prim()] if geo.nvertices else np.zeros(0, np.int64)
        key = np.unique(vl * max(geo.npoints, 1) + geo.vertex_point)
        pl, pp = key // max(geo.npoints, 1), key % max(geo.npoints, 1)
    ok = pl >= 0
    pl, pp = pl[ok], pp[ok]
    cnt = np.bincount(pl, minlength=nblk).astype(np.float64)
    avg = np.zeros((nblk, 3))
    for k in range(3):
        avg[:, k] = np.bincount(pl, weights=P[pp, k], minlength=nblk)
    avg /= np.maximum(cnt, 1)[:, None]

    # With per-point pieces Bounding Box still takes the bbox centre of those points (before pcg85 it always fell back to the point average);
    # only the area-weighted Center of Mass falls back to the point average when there are no primitives
    if method == "bounding_box":
        lo = np.full((nblk, 3), np.inf)
        hi = np.full((nblk, 3), -np.inf)
        np.minimum.at(lo, pl, P[pp])
        np.maximum.at(hi, pl, P[pp])
        bad = ~np.isfinite(lo).all(1)
        res = (lo + hi) * 0.5
        res[bad] = avg[bad]
        return res
    if method == "average_position" or elem == "points" or geo.nprims == 0:
        return avg

    # ---- center_of_mass: area-weighted ----
    tri, cor = geo.triangles(with_corners=True)
    if not len(tri):
        return avg
    vprim = geo.vertex_prim()
    tprim = vprim[cor[:, 0]]
    tlab = lab[tprim]
    keep = tlab >= 0
    if not keep.any():
        return avg
    tri, tprim, tlab = tri[keep], tprim[keep], tlab[keep]
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    # Signed area: sign taken relative to the owning primitive's normal, so "flipped" triangles of concave faces cancel out automatically
    pn = prim_normals(geo).astype(np.float64)
    sa = 0.5 * np.einsum("ij,ij->i", np.cross(b - a, c - a), pn[tprim])
    cen = (a + b + c) / 3.0
    wsum = np.bincount(tlab, weights=sa, minlength=nblk)
    acc = np.zeros((nblk, 3))
    for k in range(3):
        acc[:, k] = np.bincount(tlab, weights=sa * cen[:, k], minlength=nblk)
    good = np.abs(wsum) > 1e-12
    res = avg.copy()
    res[good] = acc[good] / wsum[good][:, None]
    return res


def extract_centroid(geo, run_over="pieces", piece_attrib="name",
                     piece_elements="primitives", method="center_of_mass",
                     output="points", attrib_name="centroid",
                     transfer_attribs="", transfer_groups="", group=""):
    """
    output="points"    a point cloud with one point per piece, carrying the piece value and transferred attributes / groups
    output="attribute" the original geometry unchanged, with each piece's centroid written as an attribute on the piece itself
    """
    if geo is None or (geo.npoints == 0 and geo.nprims == 0):
        return Geometry()
    elem, lab, nblk, values = _piece_labels(geo, run_over, piece_attrib,
                                            piece_elements, group)
    if nblk == 0:
        return Geometry() if output == "points" else geo.copy()
    cen = _centroids(geo, elem, lab, nblk, method)
    cls = POINT if elem == "points" else PRIM

    if output == "attribute":
        g = geo.copy()
        if attrib_name is None:           # Centroid Attribute toggle is off: don't write
            return g
        name = str(attrib_name).strip() or "centroid"
        v = np.zeros((geo.count(cls), 3), np.float32)
        m = lab >= 0
        v[m] = cen[lab[m]]
        g.set(cls, name, v, owned=True)
        return g

    out = Geometry.from_points(cen.astype(np.float32))
    # Piece value: pieces mode carries the name of that attribute itself, other modes record the source number
    if run_over == "pieces":
        vals = np.asarray(values)
        nm = str(piece_attrib).strip() or "name"
        if vals.dtype.kind == "U":
            out.set_string(POINT, nm, vals)
        else:
            out.set(POINT, nm, vals.astype(np.float32)
                    if vals.dtype.kind == "f" else vals.astype(np.int32),
                    owned=True)
    elif run_over in ("primitives", "points"):
        out.set(POINT, "sourceprim" if elem == "primitives" else "sourcepoint",
                np.asarray(values, np.int32), owned=True)
    elif run_over == "connectivity":
        out.set(POINT, "class", np.asarray(values, np.int32), owned=True)

    # Transfer attributes / groups: take the value of the lowest-numbered element in each piece
    first = np.full(nblk, -1, np.int64)
    idx = np.nonzero(lab >= 0)[0]
    first[lab[idx][::-1]] = idx[::-1]
    have = first >= 0
    src = np.where(have, first, 0)
    for nm in match_names(list(geo.attribs[cls].keys()), transfer_attribs):
        if nm == "P":
            continue
        a = geo.attribs[cls][nm]
        out.set(POINT, nm, a[src], owned=False)
    for nm in match_names(list(geo.groups[cls].keys()), transfer_groups):
        out.set_group(POINT, nm, geo.groups[cls][nm][src] & have)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    return out
