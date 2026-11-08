"""
Attribute-level building blocks: Create / Rename / Cast / Copy / Interpolate.

Each of these is plain on its own, but without them every time you want to create an attribute, rename it or move a column of data
from another geometry, you have to write a Wrangle line. A Wrangle can do anything, at the price that **the graph doesn't show what it does** --
with five Wrangles mixed into a chain of nodes, coming back two weeks later means opening each one and reading code. Named nodes are documentation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Copy aligns by **index or id**, Transfer by **distance**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The two nodes have similar names but completely different uses. Copy requires the elements on both sides to **already correspond** (the same geometry
split into two branches that each computed something, merged back), moving values one-to-one by index without misses; once the topology changes
the indices no longer match, and then either attach an id attribute and match by id, or use Attribute Transfer.

Attribute Copy defaults to index because "two branches of the same geometry" is its main use; matching by id
must be turned on explicitly because **silently matching by id hides errors** -- elements whose ids don't match would be skipped silently,
better to let people decide.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Interpolate by default **derives** barycentric coordinates **from positions** instead of trusting uv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Houdini's Attribute Interpolate reads the two attributes sourceprim + sourceprimuv. The problem is that
**(u,v) is ambiguous for polygons**: a quad split into two triangles has the same (u,v) valid in both triangles,
so uv alone can't tell which one -- and Scatter on quad meshes is the most common use.

So by default this takes another route: project the point's **own position** P onto the face sourceprim points at,
and derive the barycentric coordinates from that. Exact for polygons with any number of edges, and it still works if the point moved a little. To use
Houdini's approach turn on Use UV Attribute; that route is exact for triangles.
"""
from __future__ import annotations

import fnmatch

import numpy as np

from .core import (Geometry, POINT, VERTEX, PRIM, DETAIL, CLASSES, is_string,
                   freeze)
from .groups import resolve
from .ops import match_names, _gather_blocks

CLASSES = CLASSES          # re-exported for the node layer's dropdown menus
TYPES = ("float", "int", "vector", "vector4", "string")
CAST_TYPES = ("float32", "float64", "int32", "int64", "string")
_NP = {"float32": np.float32, "float64": np.float64,
       "int32": np.int32, "int64": np.int64}


def _check_cls(cls):
    if cls not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")


# ═══════════════════════════════════════════════════════════════ Create
def create(geo, name="attrib", cls=POINT, attr_type="float", size=1,
           value=(0.0, 0.0, 0.0, 0.0), string_value="", expression="",
           group="", only_if_missing=False):
    """
    Creates attributes and writes values. name can list several (space-separated) to create a batch at once.

    With a non-empty group **only selected elements are written**; the rest keep their values (or the default if the attribute didn't exist) --
    consistent with Houdini, and the most common way of "tagging some elements".
    """
    if geo is None:
        return Geometry()
    _check_cls(cls)
    if attr_type not in TYPES:
        raise ValueError(f"Type must be one of {TYPES}")
    names = [t for t in str(name or "").split() if t]
    if not names:
        raise ValueError("Name is empty.")
    n = geo.count(cls)
    sel = resolve(geo, cls, group)
    g = geo.copy()

    C = {"vector": 3, "vector4": 4}.get(attr_type, max(1, int(size)))
    for nm in names:
        cur = geo.get(cls, nm)
        if cur is not None and only_if_missing:
            continue
        if attr_type == "string":
            base = (np.full(n, "", dtype="<U1") if cur is None
                    or not is_string(cur) else np.array(cur)[:, 0])
            sv = str(string_value)
            # Width follows the actual content (it used to be a fixed <U64, truncating long paths / JSON)
            w = max(base.dtype.itemsize // 4, len(sv), 1)
            base = base.astype(f"<U{w}")
            base[sel] = sv
            g.set(cls, nm, base.reshape(-1, 1), owned=True)
            continue
        dt = np.int32 if attr_type == "int" else np.float32
        base = (np.zeros((n, C)) if cur is None or cur.shape[1] != C
                else cur.astype(np.float64))
        if str(expression).strip():
            from .wrangle import eval_value
            val = eval_value(geo, expression, cls, C)
        else:
            val = np.asarray(value, np.float64).reshape(-1)[:C]
            if len(val) < C:
                val = np.concatenate([val, np.zeros(C - len(val))])
            val = np.tile(val, (n, 1))
        base = np.where(sel[:, None], val, base)
        g.set(cls, nm, (np.rint(base) if dt is np.int32 else base).astype(dt),
              owned=True)
    return g


# ═══════════════════════════════════════════════════════════════ Rename
def _pairs(spec):
    """"old:new old2=new2" -> [(old, new), ...]"""
    out = []
    for tok in str(spec or "").split():
        sep = ":" if ":" in tok else ("=" if "=" in tok else None)
        if sep is None:
            raise ValueError(
                f"Renames are written as old:new; '{tok}' has no colon (an equals sign works too). "
                f"e.g. uv:uv2   Cd:oldCd")
        a, b = tok.split(sep, 1)
        if not a or not b:
            raise ValueError(f"'{tok}' needs a name on both sides.")
        out.append((a, b))
    return out


def rename(geo, spec="", cls=POINT, rename_groups=False):
    """
    Renames attributes. Wildcards are supported: `uv*:tex*` turns uv1 -> tex1, uvSet -> texSet --
    the part matched by `*` is carried over to the `*` of the new name.

    With rename_groups=True **groups** are renamed, not attributes. They live in different namespaces;
    they share one node because the operation is identical, and two nodes would mean remembering two places.
    """
    if geo is None:
        return Geometry()
    _check_cls(cls)
    if not str(spec or "").strip():
        return geo.copy()
    g = geo.copy()
    book = (g.groups[cls] if rename_groups else g.attribs[cls]) \
        if not (rename_groups and cls == DETAIL) else None
    if book is None:
        raise ValueError("detail has no groups.")
    for old, new in _pairs(spec):
        if "*" in old:
            head, _, tail = old.partition("*")
            for k in [k for k in list(book)
                      if fnmatch.fnmatchcase(k, old)]:
                mid = k[len(head):len(k) - len(tail)] if tail else k[len(head):]
                book[new.replace("*", mid)] = book.pop(k)
        elif old in book:
            book[new] = book.pop(old)
        else:
            have = sorted(book)
            raise KeyError(
                f"{cls} has no {'group' if rename_groups else 'attribute'} '{old}'. "
                f"Existing: {have or '(none)'}")
    return g


# ═══════════════════════════════════════════════════════════════ Cast
def cast(geo, names="", cls=POINT, to_type="float32"):
    """
    Changes an attribute's storage type. float64 is more precise but doubles memory, int32 saves half, string is handy for tagging.

    Float to integer **rounds**, it doesn't truncate: 2.9 becomes 3, not 2 -- truncation more easily makes people think
    something upstream computed wrong. String to number raises an error on elements that can't be parsed instead of quietly using 0.
    """
    if geo is None:
        return Geometry()
    _check_cls(cls)
    if to_type not in CAST_TYPES:
        raise ValueError(f"To Type must be one of {CAST_TYPES}")
    picked = match_names(list(geo.attribs[cls].keys()), names)
    if not picked:
        have = sorted(geo.attribs[cls].keys())
        raise KeyError(f"{cls} has no attribute matching '{names}'. Existing: {have or '(none)'}")
    g = geo.copy()
    for nm in picked:
        a = geo.attribs[cls][nm]
        if to_type == "string":
            if is_string(a):
                continue
            txt = np.array([" ".join(f"{x:g}" for x in row) for row in a])
            g.set(cls, nm, txt.astype(str).reshape(-1, 1), owned=True)
            continue
        dt = _NP[to_type]
        if is_string(a):
            try:
                v = np.array([[float(x) for x in str(s).split()] or [0.0]
                              for s in a[:, 0]], np.float64)
            except ValueError as ex:
                bad = [str(s) for s in a[:, 0] if not _isnum(s)][:3]
                raise ValueError(
                    f"Attribute '{nm}' is a string containing values that can't be parsed as numbers: {bad}") from ex
        else:
            v = a.astype(np.float64)
        if np.issubdtype(dt, np.integer):
            v = np.rint(v)
        g.set(cls, nm, v.astype(dt), owned=True)
    return g


def _isnum(s):
    try:
        [float(x) for x in str(s).split()]
        return True
    except ValueError:
        return False


# ═══════════════════════════════════════════════════════════════ Copy
def copy(dest, source, names="", cls=POINT, match_attrib="", group="",
         copy_groups=""):
    """
    Moves attributes from source to dest one-to-one by **element index**; if match_attrib is given, pairs by that
    attribute's value instead (usually id).

    Elements whose index is beyond source's range keep their values -- they aren't zero-filled. Zero-filling would make a
    "different element counts on the two sides" error look like the data itself contains a patch of zeros, which is painful to track down.
    """
    if dest is None:
        return Geometry()
    if source is None:
        return dest.copy()
    _check_cls(cls)
    picked = match_names(list(source.attribs[cls].keys()), names)
    grps = match_names(list(source.groups.get(cls, {}).keys()), copy_groups)
    if not picked and not grps:
        have = sorted(source.attribs[cls].keys())
        raise KeyError(f"source {cls} has no attribute matching '{names}'. "
                       f"Existing: {have or '(none)'}")
    nd, ns = dest.count(cls), source.count(cls)
    sel = resolve(dest, cls, group)

    if str(match_attrib).strip():
        nm = str(match_attrib).strip()
        da, sa = dest.get(cls, nm), source.get(cls, nm)
        if da is None or sa is None:
            raise KeyError(
                f"Match Attribute '{nm}' must exist on {cls} of both sides -- "
                f"dest: {'yes' if da is not None else 'no'}, "
                f"source: {'yes' if sa is not None else 'no'}")
        dk = da[:, 0] if da.shape[1] == 1 else np.array(
            [str(r.tolist()) for r in da])
        sk = sa[:, 0] if sa.shape[1] == 1 else np.array(
            [str(r.tolist()) for r in sa])
        uniq, first = np.unique(sk, return_index=True)
        pos = np.searchsorted(uniq, dk)
        ok = (pos < len(uniq)) & (uniq[np.clip(pos, 0, max(len(uniq) - 1, 0))]
                                  == dk) if len(uniq) else np.zeros(nd, bool)
        idx = np.where(ok, first[np.clip(pos, 0, max(len(uniq) - 1, 0))], 0)
    else:
        idx = np.arange(nd)
        ok = idx < ns
        idx = np.clip(idx, 0, max(ns - 1, 0))
    take = ok & sel

    g = dest.copy()
    for nm in picked:
        a = source.attribs[cls][nm]
        cur = dest.get(cls, nm)
        if is_string(a):
            base = (np.full(nd, "", dtype=a.dtype) if cur is None
                    or not is_string(cur) else np.array(cur, a.dtype)[:, 0])
            base[take] = a[idx[take], 0]
            g.set(cls, nm, base.reshape(-1, 1), owned=True)
            continue
        C = a.shape[1]
        base = (np.zeros((nd, C), a.dtype) if cur is None or cur.shape[1] != C
                else np.array(cur, a.dtype))
        base[take] = a[idx[take]]
        g.set(cls, nm, base, owned=True)
    for nm in grps:
        v = source.groups[cls][nm]
        cur = dest.get_group(cls, nm)
        base = np.zeros(nd, bool) if cur is None else np.array(cur, bool)
        base[take] = v[idx[take]]
        g.set_group(cls, nm, base)
    return g


# ═══════════════════════════════════════════════════════════ Interpolate
def _prim_tris(source, group=""):
    """(triangle point numbers, triangle corner numbers, CSR of prim -> its triangles)."""
    from . import spatial as _sp
    tri, tprim, tcorner = _sp.tri_soup(source, group)
    order = np.argsort(tprim, kind="stable")
    tri, tprim, tcorner = tri[order], tprim[order], tcorner[order]
    cnt = np.bincount(tprim, minlength=source.nprims)
    off = np.concatenate([[0], np.cumsum(cnt)]).astype(np.int64)
    return tri, tcorner, off, cnt


def interpolate(dest, source, names="*", cls=POINT, prim_attrib="sourceprim",
                uv_attrib="sourceprimuv", use_uv=False, group=""):
    """
    Interpolates source attributes onto dest points by sourceprim (+ optional uv).

    By default barycentric coordinates are derived from **position**, exact for polygons with any number of edges; use_uv=True follows Houdini's approach
    (the third component of uv is taken as "which triangle within the prim", 0 if absent).
    """
    if dest is None:
        return Geometry()
    if source is None or source.nprims == 0:
        return dest.copy()
    if cls not in (POINT, VERTEX):
        raise ValueError("Attribute Interpolate only makes sense for point / vertex.")
    pa = dest.get(cls, str(prim_attrib).strip())
    if pa is None:
        have = sorted(dest.attribs[cls].keys())
        raise KeyError(
            f"{cls} has no '{prim_attrib}' attribute -- it records which face of the source geometry each point lies on, "
            f"usually output by Scatter or Ray. Existing: {have or '(none)'}")
    sp = np.rint(pa[:, 0].astype(np.float64)).astype(np.int64)
    sel = resolve(dest, cls, group) & (sp >= 0) & (sp < source.nprims)
    if not sel.any():
        return dest.copy()

    tri, tcorner, off, cnt = _prim_tris(source)
    idx = np.nonzero(sel)[0]
    SP = source.get(POINT, "P").astype(np.float64)

    if use_uv:
        ua = dest.get(cls, str(uv_attrib).strip())
        if ua is None:
            have = sorted(dest.attribs[cls].keys())
            raise KeyError(f"{cls} has no '{uv_attrib}' attribute. Existing: {have or '(none)'}")
        u = ua[idx, 0].astype(np.float64)
        v = ua[idx, 1].astype(np.float64) if ua.shape[1] > 1 else np.zeros(len(idx))
        k = (np.rint(ua[idx, 2]).astype(np.int64) if ua.shape[1] > 2
             else np.zeros(len(idx), np.int64))
        t = off[sp[idx]] + np.clip(k, 0, np.maximum(cnt[sp[idx]] - 1, 0))
    else:
        # For each point find the nearest of its face's triangles and derive barycentric coordinates
        from .spatial import closest_on_tri
        c = cnt[sp[idx]]
        keep = c > 0
        idx, c = idx[keep], c[keep]
        if not len(idx):
            return dest.copy()
        qi = np.repeat(np.arange(len(idx)), c)
        ti = _gather_blocks(off[sp[idx]], c)
        Pd = (dest.get(POINT, "P").astype(np.float64) if cls == POINT
              else dest.get(POINT, "P").astype(np.float64)[dest.vertex_point])
        p = Pd[idx][qi]
        a, b2, c2 = SP[tri[ti, 0]], SP[tri[ti, 1]], SP[tri[ti, 2]]
        ab, ac = b2 - a, c2 - a
        e = lambda x, y: np.einsum("ij,ij->i", x, y)
        vv, ww = closest_on_tri(p, ab, ac, e(ab, p - a), e(ac, p - a),
                                e(ab, p - b2), e(ac, p - b2),
                                e(ab, p - c2), e(ac, p - c2))
        d = np.linalg.norm(a + vv[:, None] * ab + ww[:, None] * ac - p, axis=1)
        order = np.lexsort((d, qi))
        firstm = np.ones(len(order), bool)
        firstm[1:] = qi[order][1:] != qi[order][:-1]
        pick = order[firstm]
        t, u, v = ti[pick], vv[pick], ww[pick]

    w = np.stack([1.0 - u - v, u, v], 1)
    g = dest.copy()
    pts = tri[t]
    cor = tcorner[t]
    skip = {str(prim_attrib).strip(), str(uv_attrib).strip()}
    for src_cls, corner in ((POINT, pts), (VERTEX, cor)):
        if src_cls == VERTEX and not len(corner):
            continue
        for nm in match_names(list(source.attribs[src_cls].keys()), names):
            if nm in skip or nm == "P":
                continue
            a = source.attribs[src_cls][nm]
            if is_string(a):
                continue                         # strings can't be interpolated, skip
            cur = dest.get(cls, nm)
            C = a.shape[1]
            base = (np.zeros((dest.count(cls), C)) if cur is None
                    or cur.shape[1] != C else cur.astype(np.float64))
            base[idx] = np.einsum("ij,ijk->ik", w, a[corner].astype(np.float64))
            dt = a.dtype if cur is None else cur.dtype
            g.set(cls, nm, (np.rint(base) if dt.kind in "iub" else base
                            ).astype(dt), owned=True)
    return g
