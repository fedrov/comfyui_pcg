"""
UV Project -- generate UVs by projection. Mirrors Houdini's UV Texture SOP.

Before this there was not a single UV node in the whole set: Grid has built-in uv and Sweep can generate uv, but given geometry from
elsewhere there was nothing to do. This is the first piece of the texturing line.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UV is written as a **vertex attribute** by default, not point
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A point can correspond to **several positions** in UV space -- on both sides of a seam, on UV island boundaries. A point
attribute can only store one value per point, which cannot hold such discontinuities; vertex attributes are stored per "corner", so the same point can have
different uvs on different faces, and only then can seams be represented.

This is not academic purism: cylindrical / spherical projections **inevitably** produce seams, and written as a point attribute the column of faces at the seam
would have u interpolated from 0.98 all the way back to 0.02, smearing the whole texture across sideways. See below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Seam repair: the atan2 jump must be fixed **within each face**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cylindrical / spherical u = atan2(...)/2π jumps from 1 back to 0 on the ±π line. For faces crossing that line, the four
corners' u would be (0.98, 0.99, 0.01, 0.02) -- when rasterized the texture gets swept backwards a full turn.

Fix: check each face's u span, and if it exceeds 0.5 add 1 to **the smaller half**. That face's u becomes
(0.98, 0.99, 1.01, 1.02), continuous. The cost is that seam faces' u leave [0,1], but texture addressing is
repeat, so that does not matter -- whereas not fixing it leaves an error clearly visible to the eye.

**Only vertex attributes can do this step**, showing once again that uv should be vertex.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
box projection: choose the axis per face normal, not per point
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Six-sided projection must pick the "most head-on" axis for each face. Pick it by **face normal** (one axis for the whole face), not
by point normals -- the latter would put a face's four corners onto different projection planes, tearing that face apart in UV space.
After picking, it naturally splits into 6 UV islands; connect UV Layout to pack them.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, PRIM_POLY
from .groups import resolve
from .ops import prim_normals, euler_matrix, xform_matrix, XFORM_ORDERS, ROTATE_ORDERS

MODES = ("planar", "cylindrical", "spherical", "box", "face", "rows_columns",
         "toroidal", "plastic_wrap")
AXES = ("x", "y", "z")
CLASSES = (VERTEX, POINT)
_AXIS_VEC = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]),
             "z": np.array([0, 0, 1.0])}


def _frame(axis):
    """Build a right-handed orthonormal basis for the projection axis, returning (u direction, v direction, axis)."""
    w = np.asarray(_AXIS_VEC[axis] if isinstance(axis, str) else axis,
                   np.float64).reshape(3)
    ln = np.linalg.norm(w)
    if ln < 1e-12:
        raise ValueError("The projection axis is a zero vector.")
    w = w / ln
    a = np.array([0.0, 1.0, 0.0]) if abs(w[1]) < 0.9 else np.array([1.0, 0, 0])
    u = np.cross(a, w)
    u /= max(np.linalg.norm(u), 1e-12)
    return u, np.cross(w, u), w


def _fit01(uv, keep_aspect=True):
    """Pull uv into [0,1]. With keep_aspect both directions use the same scale, without distortion."""
    if not len(uv):
        return uv
    lo = uv.min(0)
    span = uv.max(0) - lo
    if keep_aspect:
        s = 1.0 / max(float(span.max()), 1e-12)
        return (uv - lo) * s
    return (uv - lo) / np.maximum(span, 1e-12)


def _seam_fix(uv, prim_sizes, col=0, period=1.0, degenerate=None):
    """
    Repair the atan2 jump per face: if the span within a face exceeds half a period, add one period to the smaller half.

    degenerate marks corners on **poles**. Poles are singularities of the cylindrical/spherical parameterization -- there
    x=y=0 and the angle atan2 gives is pure floating-point noise; besides, a pole's fan triangle already
    spans several longitudes, which "adding a period" cannot rescue. Instead the pole corner's u is set directly to the average of the other corners
    of the same face, so that triangle degenerates to a vertical line in UV rather than spanning the whole image.

    This whole step only makes sense for vertex attributes -- point attributes have one value per point and cannot be repaired.
    """
    if not len(uv):
        return uv
    out = uv.copy()
    c = out[:, col].copy()
    nf = len(prim_sizes)
    src = np.repeat(np.arange(nf, dtype=np.int64), prim_sizes)
    good = (np.ones(len(c), bool) if degenerate is None
            else ~np.asarray(degenerate, bool))

    hi = np.full(nf, -np.inf)
    lo = np.full(nf, np.inf)
    np.maximum.at(hi, src[good], c[good])
    np.minimum.at(lo, src[good], c[good])
    wrapped = np.isfinite(hi) & ((hi - lo) > 0.5 * period)
    if wrapped.any():
        bump = wrapped[src] & good & (c < lo[src] + 0.5 * period)
        c[bump] += period

    if degenerate is not None and (~good).any():
        cnt = np.bincount(src[good], minlength=nf)
        tot = np.bincount(src[good], weights=c[good], minlength=nf)
        mean = tot / np.maximum(cnt, 1)
        c[~good] = mean[src[~good]]
    out[:, col] = c
    return out


PROJECTOR_MODES = ("planar", "cylindrical", "spherical", "toroidal", "plastic_wrap")


def project(geo, mode="planar", axis="y", cls=VERTEX, name="uv",
            translate=(0.0, 0.0), rotate=0.0, scale=(1.0, 1.0),
            fit=True, keep_aspect=True, fix_seams=True, group="",
            projector=None, u_range=(0.0, 1.0), v_range=(0.0, 1.0),
            inner_radius=0.25):
    """
    Generate UVs by projection. Writes a vertex attribute by default -- see the module notes for why.

    With fit on, the result is pulled into [0,1]; keep_aspect decides whether both directions share one scale
    (no distortion) or each fills the range.

    pcg100: when projector = dict(translate, rotate, scale, pivot, xform_order, rotate_order) is given,
    Houdini UV Project semantics are used instead -- the projector is a **unit-size** shape (orthographic: a square of side 1 centered at the origin;
    cylinder: radius 1, height 1; sphere: unit sphere; torus: outer radius 0.5, inner radius inner_radius), placed into the scene with this TRS.
    Points are first transformed back into the projector's local space and then projected, **no longer** centered on the bounding box and without Fit to 0-1; the parameters on the projector
    (0..1) are then mapped by U Range / V Range: uv = (parameter − start) / (end − start), i.e. the left / right edges of the texture
    land at projector parameters u_range[0] / u_range[1]. Only applies to planar / cylindrical / spherical /
    toroidal / plastic_wrap (box / face / rows_columns are not UV Project projection types).
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES} -- UV only makes sense on points or corners.")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("Attribute Name is empty.")
    P = geo.get(POINT, "P")
    if P is None or geo.npoints == 0:
        return geo.copy()
    if cls == VERTEX and geo.nvertices == 0:
        return geo.copy()

    Pf = P.astype(np.float64)
    if mode == "rows_columns":
        uv_pt = _rows_columns(geo)
        uv = uv_pt[geo.vertex_point] if cls == VERTEX else uv_pt
        seam_col = None
    elif mode == "face":
        if cls != VERTEX:
            raise ValueError("face mode fills 0..1 per face and can only write a vertex attribute.")
        uv = _face_square(geo)
        seam_col = None
    elif mode == "box":
        if cls != VERTEX:
            raise ValueError(
                "box mode chooses the projection axis per **face**, so a point on different faces lands on different planes -- "
                "it can only write a vertex attribute.")
        uv = _box(geo, Pf)
        seam_col = None
    else:
        eu, ev, ew = _frame(axis)
        use_proj = projector is not None
        if use_proj:
            # transform points back into the projector's local space (inverse of the Transform matrix). No centering: the projector sets its own position
            M4 = xform_matrix(projector.get("translate", (0, 0, 0)),
                              projector.get("rotate", (0, 0, 0)),
                              projector.get("scale", (1, 1, 1)),
                              pivot=projector.get("pivot", (0, 0, 0)),
                              xform_order=projector.get("xform_order", "srt"),
                              rotate_order=projector.get("rotate_order", "xyz"),
                              invert=True)
            Q = Pf @ M4[:3, :3] + M4[3, :3]
        else:
            Q = Pf - Pf.mean(0)
        x = Q @ eu
        y = Q @ ev
        z = Q @ ew
        pole = None
        if mode == "planar":
            # the projector is a square of side 1 centered at the origin: parameter = local coordinate + 0.5
            uv_pt = np.stack([x, y], 1) + (0.5 if use_proj else 0.0)
            seam_col = None
        else:
            # distance to the axis. Close to 0 = pole, where atan2 is pure noise
            rad = np.hypot(x, y)
            pole = rad < 1e-6 * max(float(rad.max()), 1e-12)
            ang = (np.arctan2(y, x) / (2 * np.pi)) % 1.0
            if mode == "cylindrical":
                uv_pt = np.stack([ang, z + (0.5 if use_proj else 0.0)], 1)
            elif mode == "toroidal":
                # donut: u goes once around the main axis, v once around the tube. Major radius R = midpoint of the max and min "distance to the axis"
                # (for a standard torus that is exactly its major radius); v's zero is at the outer equator, increasing toward +axis
                R = (0.5 * (0.5 + float(inner_radius)) if use_proj   # radius of the tube's center line
                     else 0.5 * (float(rad.max()) + float(rad.min())))
                uv_pt = np.stack([ang, (np.arctan2(z, rad - R) / (2 * np.pi)) % 1.0], 1)
                pole = None                        # no point on a torus lies on the axis
            elif mode == "plastic_wrap":
                # Like wrapping plastic film down from the +axis end: points facing +axis land at the texture center, the farther away (the larger the
                # angle turned) the farther from the center, and the back (−axis) is pinched into a ring on the circle of radius 0.5. There is only that one pinch point on the back,
                # no seam. (Houdini's Plastic Wrap has no published formula; this is an azimuthal equidistant projection following its description)
                r = np.linalg.norm(Q, axis=1)
                th = np.arccos(np.clip(z / np.maximum(r, 1e-12), -1, 1)) / np.pi      # 0 (front) ~ 1 (back)
                d = np.stack([x, y], 1) / np.maximum(rad, 1e-12)[:, None]
                d = np.where(pole[:, None], np.array([1.0, 0.0]), d)     # points on the axis have no azimuth: the front one is at the center anyway,
                uv_pt = 0.5 + 0.5 * th[:, None] * d                       # the back pinch point lands anywhere on the circle
                pole = None
            else:                                 # spherical
                r = np.linalg.norm(Q, axis=1)
                uv_pt = np.stack([ang, 1.0 - np.arccos(np.clip(
                    z / np.maximum(r, 1e-12), -1, 1)) / np.pi], 1)
            seam_col = None if mode == "plastic_wrap" else 0
        uv = uv_pt[geo.vertex_point] if cls == VERTEX else uv_pt
        if pole is not None and cls == VERTEX:
            pole = pole[geo.vertex_point]

    if seam_col is not None and fix_seams and cls == VERTEX:
        uv = _seam_fix(uv, geo.prim_sizes(), seam_col, 1.0, pole)
        if mode == "toroidal":                    # the loop around the tube has a seam too
            uv = _seam_fix(uv, geo.prim_sizes(), 1, 1.0, None)
        # cannot be repaired on point attributes (one value per point); not done here, and not pretended

    proj_on = projector is not None and mode in PROJECTOR_MODES
    if proj_on:
        # U / V Range: map projector parameters [start, end] onto the texture's [0, 1]. No Fit to 0-1 -- the projector is the placement
        u0, u1 = (float(x) for x in u_range)
        v0, v1 = (float(x) for x in v_range)
        du = u1 - u0 if abs(u1 - u0) > 1e-12 else 1e-12
        dv = v1 - v0 if abs(v1 - v0) > 1e-12 else 1e-12
        uv = (uv - np.array([u0, v0])) / np.array([du, dv])
    elif fit:
        uv = _fit01(uv, keep_aspect)

    # ── transform in UV space: rotate around pivot first, then scale, finally translate
    ang = np.radians(float(rotate))
    if abs(ang) > 1e-12:
        c, s = np.cos(ang), np.sin(ang)
        # Houdini's Angle rotates around (0.5, 0.5); in projector mode, like Fit, it rotates around the image center
        piv = np.array([0.5, 0.5]) if (fit or proj_on) else uv.mean(0)
        d = uv - piv
        uv = np.stack([d[:, 0] * c - d[:, 1] * s,
                       d[:, 0] * s + d[:, 1] * c], 1) + piv
    uv = uv * np.asarray(scale, np.float64).reshape(2) \
        + np.asarray(translate, np.float64).reshape(2)

    g = geo.copy()
    cur = geo.get(cls, nm)
    sel = resolve(geo, cls, group)
    if cur is not None and cur.shape[1] >= 2 and not sel.all():
        base = cur.astype(np.float64)[:, :2]
        uv = np.where(sel[:, None], uv, base)
    elif not sel.all():
        uv = np.where(sel[:, None], uv, 0.0)
    g.set(cls, nm, uv.astype(np.float32), owned=True)
    return g


# ══════════════════════════════════════════════════════════ modes
def _box(geo, Pf):
    """Six-sided projection. Axis chosen by **face normal** -- choosing by point normals would tear faces apart in UV space."""
    n = prim_normals(geo, normalize=True).astype(np.float64)
    dom = np.argmax(np.abs(n), axis=1)             # the most head-on axis of each face
    sign = np.sign(n[np.arange(len(n)), dom])
    sign[sign == 0] = 1.0
    vp = geo.vertex_point
    sizes = geo.prim_sizes()
    fdom = np.repeat(dom, sizes)
    fsgn = np.repeat(sign, sizes)
    Q = Pf[vp]
    # each axis gets a (u axis, v axis) pair, right-handed; when the face is flipped u is negated to keep orientation consistent
    pairs = np.array([[1, 2], [2, 0], [0, 1]])
    ui = pairs[fdom, 0]
    vi = pairs[fdom, 1]
    idx = np.arange(len(Q))
    return np.stack([Q[idx, ui] * fsgn, Q[idx, vi]], 1)


def _face_square(geo):
    """Each face gets its own 0..1 -- for uses like bricks or cards with one image per piece."""
    sizes = geo.prim_sizes()
    starts = geo.prim_offset[:-1].astype(np.int64)
    src = np.repeat(np.arange(geo.nprims, dtype=np.int64), sizes)
    local = np.arange(geo.nvertices, dtype=np.int64) - starts[src]
    quad = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    out = np.zeros((geo.nvertices, 2))
    isq = sizes[src] == 4
    out[isq] = quad[local[isq] % 4]
    # non-quads: laid out as a regular polygon inside the unit circle, then moved into [0,1]
    other = ~isq
    if other.any():
        a = 2 * np.pi * local[other] / sizes[src][other]
        out[other] = np.stack([0.5 + 0.5 * np.cos(a),
                               0.5 + 0.5 * np.sin(a)], 1)
    return out


def _rows_columns(geo):
    """Structured quad mesh -> uv by rows and columns. Recovered via dual-graph BFS, independent of prim order."""
    from .topology import quad_grid_index
    r = quad_grid_index(geo)
    if r is None:
        raise ValueError(
            "rows_columns needs a structured quad mesh (each point locatable to a row and column). "
            "No row/column structure can be recovered from this geometry -- use planar or another mode.")
    nv, nu = r.shape                        # r is the (nv, nu) table of point numbers
    uv = np.zeros((geo.npoints, 2))
    ii, jj = np.meshgrid(np.arange(nv), np.arange(nu), indexing="ij")
    uv[r.reshape(-1)] = np.stack([(jj / max(nu - 1, 1)).reshape(-1),
                                  (ii / max(nv - 1, 1)).reshape(-1)], 1)
    return uv
