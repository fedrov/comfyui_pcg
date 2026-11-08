"""
Refine SOP -- add / remove points / subdivide on curves at parametric positions.

Division of labour with Resample: Resample "resamples the whole curve" and discards all the original points; Refine
"**inserts between the existing points**", leaving the original points, attributes and numbers untouched. Inserting a point on each side of a corner before rounding,
densifying one segment on its own, pruning redundant points from a hand-drawn curve -- these are all Refine's job.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
New points are represented by **corner references (a, b, alpha)**, rather than by computing coordinates directly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The same approach as clip.py: a new point is recorded as "at alpha between the original a and b", so P,
uv, Cd and vertex attributes are all carried over by the same line of interpolation code; adding an attribute type needs no change here.

More importantly **point numbers do not change**: new points are always appended at the end and existing point indices are kept, so
the vertex lists of unselected prims do not change by a single character, and points are not split apart by a rebuild. Rebuilding geometry per prim
and merging (Resample's approach) would duplicate shared mesh points into several copies,
harmless on curves, a disaster on faces.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Three modes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    refine     insert one point each at First U / Second U
    subdivide  divide the segment [First U, Second U] evenly into U Divisions parts
    unrefine   the reverse: delete points that "barely change the shape if deleted" (Douglas-Peucker criterion)

Spacing decides how u is measured: uniform_domain divides evenly by **vertex index** (consistent with Houdini's
domain), uniform_arc by **arc length**. On curves with uneven point spacing the two differ a lot --
u=0.5 under the index parameter is "the first half of the points", under the arc-length parameter "halfway along".

V direction is not implemented: that field corresponds to the second parametric direction of parametric surfaces (NURBS surfaces), and in this model
polygon meshes have no global (u,v) parameterization, so a value there would have no definite meaning.
"""
from __future__ import annotations

import numpy as np

from .core import (Geometry, POINT, VERTEX, PRIM, DETAIL, SPLINE_TYPES,
                   PRIM_TYPE_NAMES, is_string)
from .groups import resolve
from .ops import delete_points

MODES = ("refine", "unrefine", "subdivide")
SPACING = ("uniform_domain", "uniform_arc")


def _params(P, closed, arc):
    """Parameter value of each corner (closed curves get an extra 1.0, corresponding to wrapping back to the start)."""
    Q = np.concatenate([P, P[:1]]) if closed else P
    n = len(Q)
    if n < 2:
        return np.zeros(n)
    if not arc:
        return np.linspace(0.0, 1.0, n)
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0),
                                                        axis=1))])
    return d / d[-1] if d[-1] > 1e-12 else np.linspace(0.0, 1.0, n)


def _insert_us(mode, use_a, a, use_b, b, divs):
    """List of parameter values to insert (excluding 0 and 1)."""
    out = []
    if mode == "subdivide":
        lo = float(a) if use_a else 0.0
        hi = float(b) if use_b else 1.0
        if hi < lo:
            lo, hi = hi, lo
        k = max(1, int(divs))
        us = list(np.linspace(lo, hi, k + 1))
        if not use_a:
            us = us[1:]
        if not use_b:
            us = us[:-1]
        out = us
    else:
        if use_a:
            out.append(float(a))
        if use_b:
            out.append(float(b))
    return [u for u in out if 1e-9 < u < 1.0 - 1e-9]


def _dp_keep(P, closed, lo, hi, t, tol):
    """
    Douglas-Peucker-style removal one point at a time: each round deletes the point with "the smallest distance to the line through its two neighbours",
    until the smallest distance exceeds tolerance. Only points with parameters in [lo, hi] are considered.

    Deleting all points below tol at once is wrong -- in a run of dense points, each point
    on its own is close to its neighbours' line, and deleting them all straightens the whole run. Deleting one at a time and recomputing neighbours after each,
    the error is measured relative to the **final** polyline.
    """
    keep = np.ones(len(P), bool)
    movable = (t[:len(P)] >= lo - 1e-9) & (t[:len(P)] <= hi + 1e-9)
    if not closed:
        movable[0] = movable[-1] = False       # endpoints cannot move, or the curve would get shorter
    while True:
        idx = np.nonzero(keep & movable)[0]
        if not len(idx):
            return keep
        alive = np.nonzero(keep)[0]
        pos = np.searchsorted(alive, idx)
        if closed:
            prev = alive[(pos - 1) % len(alive)]
            nxt = alive[(pos + 1) % len(alive)]
        else:
            ok = (pos > 0) & (pos < len(alive) - 1)
            idx, pos = idx[ok], pos[ok]
            if not len(idx):
                return keep
            prev, nxt = alive[pos - 1], alive[pos + 1]
        a, b, c = P[prev], P[idx], P[nxt]
        ab = c - a
        L2 = np.einsum("ij,ij->i", ab, ab)
        s = np.clip(np.einsum("ij,ij->i", b - a, ab) /
                    np.where(L2 < 1e-24, 1.0, L2), 0.0, 1.0)
        dist = np.linalg.norm(b - (a + s[:, None] * ab), axis=1)
        j = int(np.argmin(dist))
        if dist[j] > float(tol) or len(alive) <= (3 if closed else 2):
            return keep
        keep[idx[j]] = False


def refine(geo, group="", mode="refine", use_first_u=True, first_u=0.25,
           use_second_u=False, second_u=0.75, u_divisions=2, count=1,
           spacing="uniform_domain", tolerance=0.01):
    """
    Add or remove points on the selected curves, return new geometry.

    count corresponds to Houdini's NURB Count U (knot multiplicity). Multiplicity is a spline concept; on polygons,
    executed literally it **inserts count coincident points** (producing zero-length edges). It is not secretly changed to 1 here,
    nor does it raise -- the default is 1, other values are taken literally, consistent with Houdini's behaviour.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if spacing not in SPACING:
        raise ValueError(f"spacing must be one of {SPACING}")
    sel = resolve(geo, PRIM, group)
    if geo.nprims == 0 or not sel.any():
        return geo.copy()
    bad = np.nonzero(sel & np.isin(geo.prim_type, SPLINE_TYPES))[0]
    if len(bad):
        kinds = sorted({PRIM_TYPE_NAMES.get(int(geo.prim_type[i]), "?")
                        for i in bad})
        raise ValueError(
            f"The selected prims include spline curves ({', '.join(kinds)}) -- on splines Refine is "
            f"knot insertion, only polygons/polylines are implemented here. Add a "
            f"Convert (PCG) first to convert to polygons.")

    arc = (spacing == "uniform_arc")
    P = geo.get(POINT, "P").astype(np.float64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    sizes = geo.prim_sizes().astype(np.int64)

    new_a, new_b, new_t = [], [], []       # corner references of new points (point numbers a, b and alpha)
    new_ca, new_cb = [], []                # corresponding corner numbers, for vertex attributes
    corner_lists = []                      # new corner sequence of each prim
    keep_corner = np.ones(geo.nvertices, bool)
    npts = geo.npoints

    for i in range(geo.nprims):
        cs = np.arange(starts[i], starts[i] + sizes[i], dtype=np.int64)
        if not sel[i] or sizes[i] < 2:
            corner_lists.append(cs)
            continue
        pts = geo.vertex_point[cs].astype(np.int64)
        closed = bool(geo.prim_closed[i])
        t = _params(P[pts], closed, arc)

        if mode == "unrefine":
            keep = _dp_keep(P[pts], closed,
                            float(first_u) if use_first_u else 0.0,
                            float(second_u) if use_second_u else 1.0,
                            t, tolerance)
            keep_corner[cs[~keep]] = False
            corner_lists.append(cs[keep])
            continue

        us = _insert_us(mode, use_first_u, first_u, use_second_u, second_u,
                        u_divisions)
        rep = 1 if mode != "refine" else max(1, int(count))
        if not us:
            corner_lists.append(cs)
            continue
        us = np.sort(np.asarray(us, np.float64))
        # Which segment each u falls in; segment j lies between corner j and j+1
        j = np.clip(np.searchsorted(t, us, side="right") - 1, 0, len(t) - 2)
        span = t[j + 1] - t[j]
        alpha = np.where(span > 1e-12, (us - t[j]) / np.where(span > 1e-12,
                                                             span, 1.0), 0.0)
        out = []
        for k in range(sizes[i]):
            out.append(cs[k])
            hit = np.nonzero(j == k)[0]
            for h in hit:
                nxt = (k + 1) % sizes[i] if closed else min(k + 1, sizes[i] - 1)
                for _ in range(rep):
                    new_a.append(pts[k]); new_b.append(pts[nxt])
                    new_ca.append(cs[k]); new_cb.append(cs[nxt])
                    new_t.append(alpha[h])
                    out.append(npts + len(new_t) - 1)
        corner_lists.append(np.asarray(out, np.int64))

    g = Geometry()
    nnew = len(new_t)
    g._resize_points(npts + nnew)
    A = np.asarray(new_a, np.int64) if nnew else np.zeros(0, np.int64)
    B = np.asarray(new_b, np.int64) if nnew else np.zeros(0, np.int64)
    W = (np.asarray(new_t, np.float64)[:, None] if nnew
         else np.zeros((0, 1)))
    for k, v in geo.attribs[POINT].items():
        if not nnew:
            g.set(POINT, k, v)
        elif is_string(v):
            g.set(POINT, k, np.concatenate(
                [v, np.where(W[:, 0] < 0.5, v[A, 0], v[B, 0])[:, None]]),
                owned=True)
        else:
            add = v[A].astype(np.float64) * (1 - W) + v[B].astype(np.float64) * W
            g.set(POINT, k, np.concatenate(
                [v.astype(np.float64), np.rint(add) if v.dtype.kind in "iub"
                 else add]).astype(v.dtype), owned=True)
    for k, v in geo.groups[POINT].items():
        g.set_group(POINT, k, np.concatenate(
            [v, (v[A] & v[B]) if nnew else np.zeros(0, bool)]))

    sz = np.array([len(c) for c in corner_lists], np.int64)
    corners = (np.concatenate(corner_lists) if len(corner_lists)
               else np.zeros(0, np.int64))
    off = np.concatenate([[0], np.cumsum(sz)]).astype(np.int32)
    # In the corner sequences, values >= npts are new points. Write every corner uniformly as a (ca, cb, w)
    # corner reference -- old corners are ca == cb, w = 0, so each attribute type below needs just one line of code.
    is_new = corners >= npts
    ci = np.clip(corners, 0, max(geo.nvertices - 1, 0))
    g.set_topology(np.where(is_new, corners, geo.vertex_point[ci]),
                   off, geo.prim_closed, geo.prim_type)
    CA = np.asarray(new_ca, np.int64) if nnew else np.zeros(0, np.int64)
    CB = np.asarray(new_cb, np.int64) if nnew else np.zeros(0, np.int64)
    if nnew:
        kn = np.clip(corners - npts, 0, nnew - 1)
        ca = np.where(is_new, CA[kn], ci)
        cb = np.where(is_new, CB[kn], ci)
        w = np.where(is_new, W[kn, 0], 0.0)
    else:
        ca = cb = ci
        w = np.zeros(len(corners))
    for k, v in geo.attribs[VERTEX].items():
        if is_string(v):
            g.set(VERTEX, k, np.where(w < 0.5, v[ca, 0], v[cb, 0])[:, None],
                  owned=True)
            continue
        mix = (v[ca].astype(np.float64) * (1 - w[:, None])
               + v[cb].astype(np.float64) * w[:, None])
        g.set(VERTEX, k, (np.rint(mix) if v.dtype.kind in "iub" else mix
                          ).astype(v.dtype), owned=True)
    for k, v in geo.groups[VERTEX].items():
        g.set_group(VERTEX, k, v[ca] & v[cb])

    for k, v in geo.attribs[PRIM].items():
        g.set(PRIM, k, v)
    for k, v in geo.groups[PRIM].items():
        g.set_group(PRIM, k, v)
    g.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    g.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    g.edge_groups = dict(geo.edge_groups)

    if mode == "unrefine" and not keep_corner.all():
        used = np.zeros(g.npoints, bool)
        used[g.vertex_point] = True
        was = np.zeros(g.npoints, bool)
        was[geo.vertex_point] = True
        drop = was & ~used                    # only delete points that "were in use and now are used by nothing"
        if drop.any():
            g = delete_points(g, ~drop)
    return g
