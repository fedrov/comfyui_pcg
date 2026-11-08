"""
Attribute Promote SOP -- move attributes between point / vertex / prim / detail.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One correspondence table covers every direction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Four classes paired give 16 directions; writing a branch for each is what the ops.promote version looks like --
adding one reduction method means changing a dozen places, and adding piece grouping is hopeless.

Instead: first build a **(source element, target element) correspondence table**, then do grouped reduction over that table.

    point -> prim    each corner gives a pair (its point, its face)
    vertex -> point  each corner gives a pair (the corner itself, its point)
    X -> detail      every source element maps to the single target 0
    detail -> X      the single source 0 maps to every target

In expanding directions (point->vertex and the like) each target has only one pair, and a reduction method applied to one element is
the element itself, so **expanding and reducing take the same path** and need not be written separately.

Piece Attribute then becomes a single line: change the grouping key from "target element" to "the piece the target element belongs to".
Following Houdini's rule, the piece attribute is read from **New Class** and must be an integer or string.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two modes not implemented
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Houdini's Array of All / Unique Values produce **variable-length array attributes**, while in this model
attributes are always fixed-size (N, C) arrays (see the design notes in core.py) and cannot hold them. Supporting them first requires adding
a class of variable-length attributes to Geometry, which is a separate job.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, CLASSES, is_string
from .ops import match_names

NUMERIC_METHODS = ("maximum", "minimum", "average", "mode", "median",
                   "sum", "sum_of_squares", "root_mean_square",
                   "first_match", "last_match")
STRING_METHODS = ("mode", "first_match", "last_match")


# ═══════════════════════════════════════════════════════════ source -> target correspondence table
def _pairs(geo, src_cls, dst_cls):
    """(source index, target index). Lists pair by pair "this source element affects that target element"."""
    if src_cls == DETAIL and dst_cls == DETAIL:
        return np.zeros(1, np.int64), np.zeros(1, np.int64)
    if src_cls == DETAIL:
        n = geo.count(dst_cls)
        return np.zeros(n, np.int64), np.arange(n, dtype=np.int64)
    if dst_cls == DETAIL:
        n = geo.count(src_cls)
        return np.arange(n, dtype=np.int64), np.zeros(n, np.int64)
    if src_cls == dst_cls:
        n = geo.count(src_cls)
        i = np.arange(n, dtype=np.int64)
        return i, i
    # All the rest go through corners: a corner knows both its point and its face
    nv = geo.nvertices
    table = {POINT: geo.vertex_point.astype(np.int64),
             VERTEX: np.arange(nv, dtype=np.int64),
             PRIM: geo.vertex_prim().astype(np.int64)}
    return table[src_cls], table[dst_cls]


def _piece_labels(geo, cls, name):
    """Assign each target element a piece number by the piece attribute on New Class."""
    a = geo.get(cls, name)
    if a is None:
        have = sorted(geo.attribs[cls].keys())
        raise KeyError(f"No piece attribute '{name}' on {cls}. Existing: {have or '(none)'}")
    if not (is_string(a) or a.dtype.kind in "iub"):
        raise ValueError(
            f"Piece attribute '{name}' is {a.dtype} -- the piece attribute must be an integer or string. "
            f"Float equality is unreliable and the pieces would shatter into fragments.")
    key = a[:, 0] if a.shape[1] == 1 else np.array(
        [str(r.tolist()) for r in a])
    uniq, inv = np.unique(key, return_inverse=True)
    return inv.reshape(-1).astype(np.int64), len(uniq)


# ═══════════════════════════════════════════════════════════════ reduction
def _agg_numeric(v, groups, ng, method):
    """Reduce (M,C) values by groups into (ng,C)."""
    v = v.astype(np.float64)
    C = v.shape[1]
    cnt = np.bincount(groups, minlength=ng).astype(np.float64)
    nz = np.maximum(cnt, 1.0)[:, None]

    def colsum(x):
        out = np.zeros((ng, C))
        for c in range(C):
            out[:, c] = np.bincount(groups, weights=x[:, c], minlength=ng)
        return out

    if method == "sum":
        return colsum(v)
    if method == "average":
        return colsum(v) / nz
    if method == "sum_of_squares":
        return colsum(v * v)
    if method == "root_mean_square":
        return np.sqrt(colsum(v * v) / nz)
    if method in ("maximum", "minimum"):
        out = np.full((ng, C), -np.inf if method == "maximum" else np.inf)
        (np.maximum if method == "maximum" else np.minimum).at(out, groups, v)
        return np.where(np.isfinite(out), out, 0.0)
    if method in ("first_match", "last_match"):
        pick = np.full(ng, -1, np.int64)
        seq = np.arange(len(groups), dtype=np.int64)
        if method == "first_match":              # written in reverse so the smallest index is written last
            pick[groups[::-1]] = seq[::-1]
        else:
            pick[groups] = seq
        out = np.zeros((ng, C))
        ok = pick >= 0
        out[ok] = v[pick[ok]]
        return out
    if method == "median":
        out = np.zeros((ng, C))
        off = np.concatenate([[0], np.cumsum(cnt)]).astype(np.int64)
        k = cnt.astype(np.int64)
        m = k > 0
        for c in range(C):
            sv = v[np.lexsort((v[:, c], groups)), c]
            lo = off[:-1] + (k - 1) // 2         # an even count takes the mean of the middle two
            hi = off[:-1] + k // 2
            out[m, c] = 0.5 * (sv[lo[m]] + sv[hi[m]])
        return out
    if method == "mode":
        out = np.zeros((ng, C))
        for c in range(C):
            out[:, c] = _mode_1d(v[:, c], groups, ng)
        return out
    raise ValueError(f"Unknown reduction method: {method}")


def _mode_1d(vals, groups, ng):
    """
    The most frequent value in each group. Ties take the smaller one -- there has to be a deterministic rule,
    otherwise the same data could give different answers under different numpy versions.
    """
    if not len(vals):
        return np.zeros(ng)
    order = np.lexsort((vals, groups))
    gs, sv = groups[order], vals[order]
    newrun = np.empty(len(sv), bool)
    newrun[0] = True
    newrun[1:] = (gs[1:] != gs[:-1]) | (sv[1:] != sv[:-1])
    run_id = np.cumsum(newrun) - 1
    runlen = np.bincount(run_id)
    start = np.nonzero(newrun)[0]
    rg, rv = gs[start], sv[start]
    o = np.lexsort((-runlen, rg))                # by group, within a group by run length descending
    first = np.ones(len(o), bool)
    first[1:] = rg[o][1:] != rg[o][:-1]
    sel = o[first]
    out = np.zeros(ng)
    out[rg[sel]] = rv[sel]
    return out


def _agg_string(a, src_idx, groups, ng, method, name):
    """String attributes: only mode / first / last make sense."""
    cnt = np.bincount(groups, minlength=ng)
    pure = int(cnt.max()) <= 1 if len(cnt) else True
    if method not in STRING_METHODS and not pure:
        raise ValueError(
            f"Attribute '{name}' is a string; an arithmetic reduction like '{method}' makes no sense for it. "
            f"Use mode / first_match / last_match, or convert it to a numeric attribute first.")
    vals = a[src_idx, 0]
    out = np.full(ng, "", dtype=a.dtype)
    if method == "mode" and not pure:
        uq, inv = np.unique(vals, return_inverse=True)
        idx = _mode_1d(inv.reshape(-1).astype(np.float64), groups, ng)
        has = cnt > 0
        out[has] = uq[idx[has].astype(np.int64)]
        return out[:, None]
    pick = np.full(ng, -1, np.int64)
    seq = np.arange(len(groups), dtype=np.int64)
    if method == "last_match":
        pick[groups] = seq
    else:                                        # first / pure expansion take the first one
        pick[groups[::-1]] = seq[::-1]
    ok = pick >= 0
    out[ok] = vals[pick[ok]]
    return out[:, None]


# ═══════════════════════════════════════════════════════════════ main entry
def promote(geo, name="", src_cls=PRIM, dst_cls=DETAIL, method="average",
            piece_attrib="", new_name="", delete_original=True):
    """
    name can be a **pattern**: forms like `uv*` or `* ^P` move a batch at once (same rules as Attribute Delete's
    name field).

    When new_name contains `*`, the `*` is replaced by the original attribute name -- this is how a batch is renamed when moving several at once
    (`prom_*`); without `*` it is used as a literal name, which only makes sense when exactly one attribute is moved.

    Following Houdini's rule, piece_attrib is read from **New Class** and must be an integer or string;
    when given, reduction is by "piece" rather than by the target element itself. When the target is detail, pieces make no sense
    (detail has only one element) and it is ignored automatically.
    """
    if src_cls not in CLASSES or dst_cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    names = match_names(list(geo.attribs[src_cls].keys()), name)
    if not names:
        have = sorted(geo.attribs[src_cls].keys())
        raise KeyError(f"No attribute matching '{name}' on {src_cls}. Existing: "
                       f"{have or '(none)'}")

    src_idx, dst_idx = _pairs(geo, src_cls, dst_cls)
    ndst = geo.count(dst_cls)
    if piece_attrib.strip() and dst_cls != DETAIL:
        lab, ng = _piece_labels(geo, dst_cls, piece_attrib.strip())
        groups = lab[dst_idx]
        scatter = lab
    else:
        ng = ndst
        groups = dst_idx
        scatter = np.arange(ndst, dtype=np.int64)

    g = geo.copy()
    for nm in names:
        a = geo.attribs[src_cls][nm]
        out = str(new_name).strip()
        out = (out.replace("*", nm) if out else nm)
        if is_string(a):
            r = _agg_string(a, src_idx, groups, ng, method, nm)
        else:
            r = _agg_numeric(a[src_idx], groups, ng, method)
            if a.dtype.kind in "iub":
                # Integer attributes stay integers after reduction (preserving type, as Houdini does).
                # But **round** rather than truncate: when averaging an int attribute gives 2.9,
                # truncating to 2 is more likely than rounding to 3 to make people think the computation is wrong.
                r = np.rint(r)
            r = r.astype(np.float32 if a.dtype.kind == "f" else a.dtype)
        g.set(dst_cls, out, r[scatter], owned=True)
        if delete_original and not (src_cls == dst_cls and out == nm):
            g.remove(src_cls, nm)
    return g
