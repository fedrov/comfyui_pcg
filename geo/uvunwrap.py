"""
UV Unwrap -- mirrors Houdini's UV Unwrap SOP.

Not the same as UV Flatten (audit [C]): Unwrap solves no energy at all; it is "partition by plane + orthographic projection + layout":

    1. assign planes: each face picks the plane with **least projection distortion** (wording from the docs). The area ratio of an orthographic projection is
       |face normal · plane normal|, so it picks the plane with the largest absolute dot product
    2. form regions: connected faces projected onto the same plane merge into one region (sharing an edge counts as connected)
    3. layout: regions are laid out without overlap -- Strip lines them up along U, Square fills them into a square from largest to smallest

The default planes are the coordinate planes of the three axes (YZ / ZX / XY), which Rotate can turn as a whole; with a second input its polygons are used as the planes
(filtered by Plane Group).

Our own choices (the docs do not say):
  · faces facing away from their plane would be mirrored by the projection -- here "front / back" are split into two regions and the back's u is negated, so the uv's
    handedness matches the face winding (the same convention as UV Project's box mode)
  · Spacing is "a percentage of the layout space": spacing is computed as a percentage of S = √(sum of the regions' bounding-box areas) (the side length when tiled as a square)
  · Strip sorts by the smallest face number in each region; Square sorts by bounding-box area from largest to smallest, with row width max(S, widest region)
  · the docs do not list the options of Houdini's Planes menu (default plane orientations); here there is only the one "coordinate planes of the three axes"
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .groups import resolve
from .ops import prim_normals, euler_matrix
from .topology import topology

LAYOUTS = ("strip", "square")
SCALES = ("none", "uniform", "stretch")


def _planes(planes_geo, plane_group, rotate, rotate_order):
    """Planes -> (k,3) triples of (u axis, v axis, normal), right-handed."""
    if planes_geo is not None and planes_geo.nprims:
        sel = resolve(planes_geo, PRIM, plane_group)
        N = np.asarray(prim_normals(planes_geo, normalize=True), np.float64)
        P = np.asarray(planes_geo.get(POINT, "P"), np.float64)
        out = []
        for k in np.nonzero(sel)[0]:
            pts = planes_geo.prim_points(int(k))
            if len(pts) < 3 or np.linalg.norm(N[k]) < 0.5:
                continue
            n = N[k] / np.linalg.norm(N[k])
            e = P[pts[1]] - P[pts[0]]
            e = e - (e @ n) * n                       # u along the polygon's first edge
            if np.linalg.norm(e) < 1e-12:
                continue
            u = e / np.linalg.norm(e)
            out.append((u, np.cross(n, u), n))
        if not out:
            raise ValueError("The second input has no polygons (selected by Plane Group) usable as planes.")
        return out
    R = euler_matrix(*[float(x) for x in rotate], order=rotate_order).astype(np.float64)
    I = np.eye(3)
    # the same cyclic pairing as UV Project's box: X face (Y, Z), Y face (Z, X), Z face (X, Y)
    return [(R @ I[(a + 1) % 3], R @ I[(a + 2) % 3], R @ I[a]) for a in range(3)]


def unwrap(geo, planes_geo=None, name="uv", group="", plane_group="",
           layout="strip", scale="none", spacing=5.0, rotate_order="xyz",
           rotate=(0.0, 0.0, 0.0)):
    if geo is None:
        return Geometry()
    if layout not in LAYOUTS:
        raise ValueError(f"Layout must be one of {LAYOUTS}")
    if scale not in SCALES:
        raise ValueError(f"Scale must be one of {SCALES}")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("UV Attribute is empty.")
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    sel = resolve(geo, PRIM, group)
    pl = _planes(planes_geo, plane_group, rotate, rotate_order)
    Nf = np.asarray(prim_normals(geo, normalize=True), np.float64)
    PN = np.stack([n for _, _, n in pl])                       # (k,3)
    d = Nf @ PN.T                                             # (F,k)
    which = np.argmax(np.abs(d), axis=1)
    sgn = np.where(d[np.arange(len(d)), which] < 0, -1, 1)
    label = which * 2 + (sgn < 0)

    # ── regions: selected faces with the same (plane, front/back) label that share an edge join into one piece
    t = topology(geo)
    lab = np.arange(geo.nprims, dtype=np.int64)
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        vprim = geo.vertex_prim().astype(np.int64)
        a = vprim[t.edge_he[t.edge_he_off[two]]]
        b = vprim[t.edge_he[t.edge_he_off[two] + 1]]
        ok = sel[a] & sel[b] & (label[a] == label[b])
        a, b = a[ok], b[ok]
        for _ in range(64):
            prev = lab
            m = np.minimum(lab[a], lab[b])
            lab = lab.copy()
            np.minimum.at(lab, a, m)
            np.minimum.at(lab, b, m)
            lab = lab[lab]
            if np.array_equal(lab, prev):
                break
    regions = np.unique(lab[sel])                             # sorted by smallest face number (Strip's order)

    sizes = geo.prim_sizes()
    vpr = np.repeat(np.arange(geo.nprims), sizes)
    Pv = P[geo.vertex_point]
    uv = np.zeros((geo.nvertices, 2))
    for f_lab in np.unique(label[sel]):
        u, v, _ = pl[f_lab // 2]
        s = -1.0 if f_lab % 2 else 1.0
        m = sel[vpr] & (label[vpr] == f_lab)
        uv[m, 0] = s * (Pv[m] @ u)
        uv[m, 1] = Pv[m] @ v

    # move each region to its own origin
    boxes = []
    vreg = lab[vpr]
    for r in regions:
        m = sel[vpr] & (vreg == r)
        lo = uv[m].min(0)
        uv[m] -= lo
        boxes.append(uv[m].max(0))
    boxes = np.asarray(boxes).reshape(-1, 2)
    S = float(np.sqrt(max(float((boxes[:, 0] * boxes[:, 1]).sum()), 1e-30)))
    gap = max(float(spacing), 0.0) / 100.0 * S
    off = np.zeros_like(boxes)
    if layout == "strip":
        x = 0.0
        for i in range(len(boxes)):
            off[i] = (x, 0.0)
            x += boxes[i, 0] + gap
    else:
        W = max(S, float(boxes[:, 0].max()))
        order = np.argsort(-(boxes[:, 0] * boxes[:, 1]), kind="stable")
        x = y = row_h = 0.0
        for i in order:
            if x > 0.0 and x + boxes[i, 0] > W + 1e-12:
                x, y, row_h = 0.0, y + row_h + gap, 0.0
            off[i] = (x, y)
            x += boxes[i, 0] + gap
            row_h = max(row_h, boxes[i, 1])
    for i, r in enumerate(regions):
        m = sel[vpr] & (vreg == r)
        uv[m] += off[i]

    m = sel[vpr]
    if scale != "none" and m.any():
        lo = uv[m].min(0)
        ext = uv[m].max(0) - lo
        if scale == "uniform":
            uv[m] = (uv[m] - lo) / max(float(ext.max()), 1e-30)
        else:
            uv[m] = (uv[m] - lo) / np.where(ext > 1e-30, ext, 1.0)

    g = geo.copy()
    cur = geo.get(VERTEX, nm)
    if cur is not None and cur.shape[1] >= 2:
        col = np.array(cur, np.float64)
        col[m, :2] = uv[m]
        g.set(VERTEX, nm, col.astype(cur.dtype), owned=True)
    else:
        pt = geo.get(POINT, nm)
        if pt is not None and pt.shape[1] >= 2:
            uv[~m] = np.asarray(pt, np.float64)[geo.vertex_point[~m], :2]
        g.set(VERTEX, nm, uv.astype(np.float32), owned=True)
    return g
