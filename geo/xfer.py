"""
Attribute Transfer SOP -- transfers attributes from one geometry onto another by distance.

Uses: high-res Cd / uv onto a low-res mesh; a terrain mask onto scattered points; aligning attributes of two geometries at a
seam. In Houdini it is the general "move attributes over" tool, and the backbone of bake-style pipelines.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two independent quantities: **what to blend** and **how much to blend**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What to blend  = the nearest few source elements within the threshold, kernel-weighted averaged into a "target value";
How much  = an alpha determined by the distance of **the nearest** source element, falling from 1 to 0 between threshold and
          threshold-blend_width.

Result = lerp(original value, target value, alpha).

Keeping the two apart makes sense: the sample count controls smoothness (one sample gives hard edges, eight are soft),
blend_width controls **the edge of the influence range**. Combined into one number, tuning "not harsh at the boundary" would
also blur the interior. alpha only looks at the nearest distance, so inside the threshold it is always full strength.

With blend_width = 0 alpha is a hard 0/1 switch: within reach it is fully replaced, out of reach it is untouched --
that is the default, and what "copy the uv over as is" wants.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
String attributes and groups
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strings cannot be weighted-averaged, so they always take the value of **the nearest** source element (unchanged when alpha < 0.5).
Groups likewise: decided by whether the nearest source element is in the group. A weighted vote would also work, but "this point's name is
half treeA, half treeB" is meaningless; taking the nearest is predictable.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import match_names, prim_centers
from . import spatial as _sp

KERNELS = ("uniform", "inverse_distance", "tent", "gaussian", "smooth")


def _weights(d, r, kernel):
    x = np.clip(d / max(r, 1e-12), 0.0, 1.0)
    if kernel == "inverse_distance":
        return 1.0 / np.maximum(d, 1e-9 * max(r, 1e-9))
    if kernel == "tent":
        return np.maximum(1.0 - x, 0.0)
    if kernel == "gaussian":
        return np.exp(-4.5 * x * x)
    if kernel == "smooth":                      # Wyvill, derivative is 0 at both ends
        return (1.0 - x * x) ** 3
    return np.ones_like(x)                      # uniform


def _pairs(Pd, Ps, threshold, max_samples, kd=None, ks=None):
    """
    (target indices, source indices, distances); each target keeps only its nearest max_samples, sorted by ascending distance.

    If kd/ks are given this is Match Attribute: pairs whose values of that attribute differ on the two sides are dropped.
    Pair first, then filter -- not group by attribute first and pair within each group: the attribute may have thousands of values, and grouping would
    split one grid query into thousands of small queries, which is slower.
    """
    qi, si, d = _sp.neighbors_within(Pd, Ps, threshold)
    if not len(qi):
        return qi, si, d
    if kd is not None and ks is not None:
        m = kd[qi] == ks[si]
        qi, si, d = qi[m], si[m], d[m]
        if not len(qi):
            return qi, si, d
    order = np.lexsort((d, qi))
    qi, si, d = qi[order], si[order], d[order]
    if max_samples > 0:
        first = np.ones(len(qi), bool)
        first[1:] = qi[1:] != qi[:-1]
        starts = np.nonzero(first)[0]
        rank = np.arange(len(qi)) - np.repeat(starts, np.diff(
            np.append(starts, len(qi))))
        keep = rank < max_samples
        qi, si, d = qi[keep], si[keep], d[keep]
    return qi, si, d


def _blend_cls(dst, src, cls, names, dsel, ssel, Pd, Ps, threshold,
               blend_width, max_samples, kernel, match_attrib, groups_pat):
    """Transfer for one element class. dsel/ssel are the selected indices on the two sides."""
    if not len(dsel) or not len(ssel):
        return
    kd = ks = None
    if str(match_attrib).strip():
        nm = str(match_attrib).strip()
        ad, as_ = dst.get(cls, nm), src.get(cls, nm)
        if ad is None or as_ is None:
            raise KeyError(
                f"Match Attribute '{nm}' must exist on the {cls} of both sides -- "
                f"destination: {'yes' if ad is not None else 'no'}, "
                f"source: {'yes' if as_ is not None else 'no'}")
        kd = (ad[dsel, 0] if ad.shape[1] == 1
              else np.array([str(r.tolist()) for r in ad[dsel]]))
        ks = (as_[ssel, 0] if as_.shape[1] == 1
              else np.array([str(r.tolist()) for r in as_[ssel]]))

    qi, si, d = _pairs(Pd, Ps, threshold, max_samples, kd, ks)
    n = len(dsel)
    if not len(qi):
        alpha = np.zeros(n)
        nearest = np.zeros(n, np.int64)
        hit = np.zeros(n, bool)
    else:
        first = np.ones(len(qi), bool)
        first[1:] = qi[1:] != qi[:-1]
        f = np.nonzero(first)[0]
        dmin = np.full(n, np.inf)
        nearest = np.zeros(n, np.int64)
        dmin[qi[f]] = d[f]
        nearest[qi[f]] = si[f]
        hit = np.isfinite(dmin)
        if blend_width > 0:
            alpha = np.clip((threshold - dmin) / blend_width, 0.0, 1.0)
        else:
            alpha = hit.astype(np.float64)
        alpha = np.where(hit, alpha, 0.0)
        w = _weights(d, threshold, kernel)
        wsum = np.bincount(qi, weights=w, minlength=n)
        w = w / np.where(wsum[qi] <= 0, 1.0, wsum[qi])

    for nm in names:
        a = src.attribs[cls][nm]
        cur = dst.get(cls, nm)
        if is_string(a):
            out = (np.full(dst.count(cls), "", dtype=a.dtype)
                   if cur is None or not is_string(cur)
                   else np.array(cur, dtype=a.dtype).reshape(-1, 1)[:, 0])
            if len(qi):
                take = hit & (alpha >= 0.5)
                out[dsel[take]] = a[ssel[nearest[take]], 0]
            dst.set(cls, nm, out.reshape(-1, 1), owned=True)
            continue
        C = a.shape[1]
        base = (np.zeros((dst.count(cls), C)) if cur is None or cur.shape[1] != C
                else cur.astype(np.float64))
        if len(qi):
            new = np.zeros((n, C))
            vals = a[ssel][si].astype(np.float64) * w[:, None]
            for c in range(C):
                new[:, c] = np.bincount(qi, weights=vals[:, c], minlength=n)
            sub = base[dsel]
            base = base.copy()
            base[dsel] = sub + alpha[:, None] * (new - sub)
        dt = a.dtype if cur is None else cur.dtype
        if dt.kind in "iub":
            base = np.rint(base)
        dst.set(cls, nm, base.astype(dt), owned=True)

    for nm in match_names(list(src.groups[cls].keys()), groups_pat):
        g = src.groups[cls][nm]
        cur = dst.get_group(cls, nm)
        out = (np.zeros(dst.count(cls), bool) if cur is None
               else np.array(cur, bool))
        if len(qi):
            take = hit & (alpha >= 0.5)
            out[dsel[take]] = g[ssel[nearest[take]]]
        dst.set_group(cls, nm, out)


def _prims_in(geo, pt_idx):
    """Faces whose vertices all fall in pt_idx."""
    if not geo.nprims:
        return np.zeros(0, bool)
    m = np.zeros(geo.npoints, bool)
    m[pt_idx] = True
    if not geo.nvertices:
        return np.zeros(geo.nprims, bool)
    good = m[geo.vertex_point]
    return (np.bincount(geo.vertex_prim(), weights=(~good).astype(np.float64),
                        minlength=geo.nprims) == 0)


def attribute_transfer(dest, source, dst_group="", src_group="",
                       point_attribs="", prim_attribs="", detail_attribs="",
                       point_groups="", prim_groups="",
                       threshold=1.0, blend_width=0.0, max_samples=1,
                       kernel="uniform", match_attrib=""):
    """
    Transfer attributes from source onto dest, returning a new geometry.

    point_attribs / prim_attribs / detail_attribs are name patterns (same as Attribute
    Delete: `uv*`, `* ^P`). Empty = this class is not transferred.
    Prims are paired by **face centroid** distance.
    """
    if dest is None:
        return Geometry()
    if source is None:
        return dest.copy()
    if kernel not in KERNELS:
        raise ValueError(f"kernel must be one of {KERNELS}")
    threshold = float(threshold)
    if threshold <= 0:
        return dest.copy()

    out = dest.copy()
    dsel = np.nonzero(resolve(dest, POINT, dst_group))[0].astype(np.int64)
    ssel = np.nonzero(resolve(source, POINT, src_group))[0].astype(np.int64)
    pnames = match_names(list(source.attribs[POINT].keys()), point_attribs)
    pnames = [n for n in pnames if n != "P"]     # P is not transferred, that would be "moving the points"
    if (pnames or str(point_groups).strip()) and len(dsel) and len(ssel):
        Pd = dest.get(POINT, "P")
        Ps = source.get(POINT, "P")
        if Pd is not None and Ps is not None:
            _blend_cls(out, source, POINT, pnames, dsel, ssel,
                       Pd[dsel].astype(np.float64), Ps[ssel].astype(np.float64),
                       threshold, blend_width, max_samples, kernel,
                       match_attrib, point_groups)

    qnames = match_names(list(source.attribs[PRIM].keys()), prim_attribs)
    if (qnames or str(prim_groups).strip()) and dest.nprims and source.nprims:
        # Groups are **point** groups; at the face level "the whole face is in the group" counts, i.e. a group = a sub-geometry.
        # If touching were enough, boundary faces would be half-dragged in, and the result would depend on how the group was drawn.
        dq = np.nonzero(_prims_in(dest, dsel))[0].astype(np.int64)
        sq = np.nonzero(_prims_in(source, ssel))[0].astype(np.int64)
        _blend_cls(out, source, PRIM, qnames, dq, sq,
                   prim_centers(dest)[dq].astype(np.float64),
                   prim_centers(source)[sq].astype(np.float64),
                   threshold, blend_width, max_samples, kernel,
                   match_attrib, prim_groups)

    for nm in match_names(list(source.attribs[DETAIL].keys()), detail_attribs):
        out.attribs[DETAIL][nm] = source.attribs[DETAIL][nm]
    return out
