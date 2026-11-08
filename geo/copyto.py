"""
Copy to Points SOP -- copies source geometry onto target points.

All transform conventions are delegated to xform.py (Houdini's instance attributes); this file only handles
"what gets copied, onto which points, and how attributes combine".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Piece Attribute: laying out a whole forest at once
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
With piece_attrib (usually name or variant) the source is split into **pieces** by that attribute, and
target points pick pieces by the point attribute of the same name -- so "five kinds of trees scattered over a hillside" is one node, rather than
five branches each with its own Copy to Points and a Merge.

Implementation: group by piece, do one uniform copy per group, then merge. The output is therefore **clustered by piece**,
not strictly in target point order; the prim attribute copynum records which target point it came from; sort by it to restore the order.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Attribute merge rules
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source point / vertex / prim attributes are tiled onto every copy as a whole; direction attributes
(rotate_attribs, default N v up) go through the inverse transpose of the rotation matrix.

Target point attributes are picked by target_attribs and repeated onto the copy's points. **On a name clash the target wins over the source**
-- consistent with Houdini and intuitive: the Cd on a target point is there to colour that copy.
Names listed in mult_attribs are multiplied instead, for tinting with Cd.

Attributes used for the transform (orient / pscale / N / ...) are **not** copied onto the copies.
If they were, a downstream Copy to Points would apply the same orientation again.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import merge, delete_prims, delete_points, match_names
from . import xform as _xf


def _sub_source(src, group):
    """Source prim group -> sub-geometry. A point cloud without primitives is returned unchanged."""
    if not str(group).strip():
        return src
    if src.nprims:
        return delete_prims(src, resolve(src, PRIM, group))
    return delete_points(src, resolve(src, POINT, group))


def _piece_key(geo, cls, name):
    """Turns the piece attribute into a 1-D comparable key (vector attributes joined into strings)."""
    a = geo.get(cls, name)
    if a is None:
        return None
    if is_string(a) or a.shape[1] == 1:
        return a[:, 0]
    return np.array([str(r.tolist()) for r in a])


def _source_piece_keys(src, name):
    """
    Which piece each source prim (each point when there are no primitives) belongs to.

    The piece attribute most often lives on prims (output of Assemble / Connectivity); one on points
    is accepted too: the value of each primitive's first point is used -- a primitive whose points belong to different pieces makes no sense anyway.
    """
    if src.nprims:
        k = _piece_key(src, PRIM, name)
        if k is not None:
            return PRIM, k
        kp = _piece_key(src, POINT, name)
        if kp is not None:
            first = src.vertex_point[src.prim_offset[:-1].astype(np.int64)]
            return PRIM, kp[first]
        return None, None
    k = _piece_key(src, POINT, name)
    return (POINT, k) if k is not None else (None, None)


def _tile_attribs(out, src, n, M):
    """Tiles the source attributes n times; direction attributes are rotated along."""
    NM = _xf.normal_matrices(M)
    for k, v in src.attribs[POINT].items():
        if k == "P":
            continue
        out.set(POINT, k, np.tile(v, (n, 1)), owned=True)
    for k, v in src.attribs[VERTEX].items():
        out.set(VERTEX, k, np.tile(v, (n, 1)), owned=True)
    for k, v in src.attribs[PRIM].items():
        out.set(PRIM, k, np.tile(v, (n, 1)), owned=True)
    for cls in (POINT, VERTEX, PRIM):
        for k, v in src.groups[cls].items():
            out.set_group(cls, k, np.tile(v, n))
    for k, v in src.attribs[DETAIL].items():
        out.attribs[DETAIL][k] = v
    return NM


def _copies(src, tgt, sel_idx, up, use_orientations, target_attribs,
            target_prim_attribs, mult_attribs, rotate_attribs, pack=False):
    """Copies the whole src onto the sel_idx points of tgt (pack=True: one packed primitive per copy instead)."""
    n, m = len(sel_idx), src.npoints
    if n == 0 or m == 0:
        return Geometry()
    sub = Geometry(0)                            # a "target point cloud" with only the selected points
    sub._resize_points(n)
    for k, v in tgt.attribs[POINT].items():
        sub.set(POINT, k, v[sel_idx], owned=True)
    M, T, piv = _xf.point_matrices(sub, up, use_orientations)
    xfer = (target_attribs, target_prim_attribs, mult_attribs, rotate_attribs)
    if pack:
        from .packed import make_packed
        return make_packed(src, sub, M, T, piv, np.asarray(sel_idx, np.int32), xfer)
    return expand(src, sub, M, T, piv, np.asarray(sel_idx, np.int32), *xfer)


def expand(src, sub, M, T, piv, copynum, target_attribs="*", target_prim_attribs="", mult_attribs="",
           rotate_attribs="N v up"):
    """
    The copies themselves: src transformed by every (M, T, piv), with the attributes of the point cloud `sub`
    (one point per copy) handed down. Shared by Copy to Points and Unpack, so unpacking a packed copy gives
    exactly what the unpacked Copy to Points gives.
    """
    n, m = sub.npoints, src.npoints
    if n == 0 or m == 0:
        return Geometry()
    tgt, sel_idx = sub, np.arange(n)
    out = Geometry()
    out._resize_points(n * m)
    sp = src.get(POINT, "P")
    sp = np.zeros((m, 3)) if sp is None else np.asarray(sp, np.float64)
    out.set(POINT, "P",
            _xf.apply_matrices(sp, M, T, piv).reshape(-1, 3).astype(np.float32),
            owned=True)

    if src.nprims:
        vp = (src.vertex_point[None, :] +
              (np.arange(n, dtype=np.int32) * m)[:, None]).reshape(-1)
        step = int(src.prim_offset[-1])
        off = (src.prim_offset[1:][None, :] +
               (np.arange(n, dtype=np.int32) * step)[:, None]).reshape(-1)
        out.set_topology(vp, np.concatenate([[0], off]).astype(np.int32),
                         np.tile(src.prim_closed, n), np.tile(src.prim_type, n))

    NM = _tile_attribs(out, src, n, M)
    for k in match_names(list(src.attribs[POINT].keys()), rotate_attribs):
        v = src.get(POINT, k)
        if v is None or v.shape[1] != 3:
            continue
        w = np.einsum("nij,mj->nmi", NM, v.astype(np.float64))
        ln = np.linalg.norm(w, axis=2, keepdims=True)
        out.set(POINT, k, (w / np.where(ln < 1e-12, 1.0, ln)
                           ).reshape(-1, 3).astype(v.dtype), owned=True)

    # ---- hand target point attributes down to the copies
    avail = [k for k in tgt.attribs[POINT]
             if k not in _xf.INSTANCE_ATTRIBS]
    mult = set(match_names(avail, mult_attribs))
    for k in match_names(avail, target_attribs):
        tv = tgt.get(POINT, k)[sel_idx]
        rep = np.repeat(tv, m, axis=0)
        cur = out.get(POINT, k)
        if k in mult and cur is not None and not is_string(cur) \
                and not is_string(rep):
            out.set(POINT, k, (cur.astype(np.float64) * rep).astype(cur.dtype),
                    owned=True)
        else:
            out.set(POINT, k, rep, owned=True)
    if src.nprims:
        for k in match_names(avail, target_prim_attribs):
            out.set(PRIM, k,
                    np.repeat(tgt.get(POINT, k)[sel_idx], src.nprims, axis=0),
                    owned=True)
        out.set(PRIM, "copynum",
                np.repeat(np.asarray(copynum, np.int32), src.nprims), owned=True)
    out.set(POINT, "copynum",
            np.repeat(np.asarray(copynum, np.int32), m), owned=True)
    return out


def copy_to_points(source, target, source_group="", target_group="",
                   use_orientations=True, up=(0.0, 1.0, 0.0),
                   piece_attrib="",
                   target_attribs="*", target_prim_attribs="",
                   mult_attribs="", rotate_attribs="N v up", pack=False):
    """
    Copies source onto every point of target.

    target_group  : **point** group on the target; copy only onto these points
    source_group  : prim group on the source (point group for point clouds)
    piece_attrib  : distribute by piece, see the module notes
    target_attribs: which target point attributes are handed down to the copies (Houdini's Attributes tab)
    """
    if source is None or target is None:
        return Geometry()
    src = _sub_source(source, source_group)
    if src.npoints == 0 or target.npoints == 0:
        return Geometry()

    sel = np.nonzero(resolve(target, POINT, target_group))[0].astype(np.int64)
    if not len(sel):
        return Geometry()
    up = np.asarray(up, np.float64).reshape(3)
    args = (up, use_orientations, target_attribs, target_prim_attribs,
            mult_attribs, rotate_attribs, pack)

    name = str(piece_attrib).strip()
    if not name:
        return _copies(src, target, sel, *args)

    cls, skey = _source_piece_keys(src, name)
    if skey is None:
        have = sorted(set(src.attribs[PRIM]) | set(src.attribs[POINT]))
        raise KeyError(f"Source geometry has no piece attribute '{name}'. Existing: {have or '(none)'}")
    tkey = _piece_key(target, POINT, name)
    if tkey is None:
        have = sorted(target.attribs[POINT])
        raise KeyError(f"Target points have no piece attribute '{name}'. Existing: {have or '(none)'}")
    tkey = tkey[sel]

    parts, matched = [], 0
    for val in np.unique(tkey):
        pts = sel[tkey == val]
        pick = skey == val
        if not pick.any():
            continue                      # target points without a matching piece: skip, no error
        matched += len(pts)
        piece = (delete_prims(src, pick) if cls == PRIM
                 else delete_points(src, pick))
        parts.append(_copies(piece, target, pts, *args))
    if not matched:
        su = sorted(np.unique(skey).tolist())[:8]
        tu = sorted(np.unique(tkey).tolist())[:8]
        raise ValueError(
            f"Piece attribute '{name}' doesn't match between the two sides; not a single target point matched.\n"
            f"  source values: {su}\n  target point values: {tu}")
    return merge(*parts) if parts else Geometry()
