"""
Packed primitives (pcg121): Pack / Unpack, Copy to Points' Pack and Instance, viewport instancing.

A packed primitive stands for a whole piece of geometry placed somewhere -- Houdini's packed geometry. Here it is a
primitive of type PRIM_PACKED with one vertex (its point is where the piece sits), and

  prim_data[i]["geo"]   the piece (shared: a thousand copies of a tree hold the same Geometry object)
  prim_data[i]["xfer"]  how Unpack hands the point's attributes to the piece (Copy to Points' attribute settings)
  prim "packedxform"    the 3x3 linear part M (row-major) and
  prim "packedpivot"    the pivot: a piece point p ends up at  M @ (p - pivot) + P(point)
                        -- the same convention as Copy to Points (geo/xform.py), so packing is exact

Why: 10 000 copies of a 5 000-triangle rock are 50 M triangles as real geometry -- gigabytes of attributes and a
viewport that cannot draw them. Packed, it is 10 000 points; the viewport draws them as GPU instances
(three.js InstancedMesh, one draw call per distinct piece).

What understands packed primitives: Pack, Unpack, Transform (moves and rotates the pieces: M and P update), Merge,
Blast / Delete, Sort, Switch, the attribute / group nodes that only read points (Wrangle on points, Attribute Create /
Randomize, Color, Group Create), Copy to Points (packed targets are just their points) and the viewport.
Every other node gets the geometry **unpacked automatically** before it runs (attach_auto_unpack in __init__), so a
packed input never gives a wrong result -- only the speed-up is lost from that node on, like in Houdini when you
unpack before modelling.

Unpack reuses copyto.expand -- the very code Copy to Points runs -- so "Copy to Points (packed) -> Unpack" is
identical to "Copy to Points", attribute for attribute.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_PACKED, is_string
from .groups import resolve

XFORM, PIVOT = "packedxform", "packedpivot"
PACK_BY = ("piece_attribute", "connectivity", "all")
PIVOTS = ("centroid", "bbox_center", "origin", "bbox_min_y")

# Nodes that handle packed primitives themselves; every other node sees unpacked geometry (see attach_auto_unpack)
PACK_AWARE = {
    "PCG_Pack", "PCG_Unpack", "PCG_Transform", "PCG_Merge", "PCG_Blast", "PCG_Delete", "PCG_Sort", "PCG_Switch",
    "PCG_SwitchIf", "PCG_Wrangle", "PCG_AttribCreate", "PCG_AttribRandomize", "PCG_Color", "PCG_GroupCreate",
    "PCG_CopyToPoints", "PCG_Viewport", "PCG_Display", "PCG_GeoSpreadsheet", "PCG_AttribDelete", "PCG_AttribRename",
    "PCG_ExportMesh", "PCG_ExportInstances",
}


def is_packed(geo) -> bool:
    return isinstance(geo, Geometry) and geo.nprims > 0 and bool(np.any(geo.prim_type == PRIM_PACKED))


def make_packed(src, sub, M, T, piv, copynum, xfer):
    """
    One packed primitive per point of `sub` (the target points of Copy to Points), all referencing `src`.
    copynum None: no copynum attribute on unpack (Pack); else it is written like Copy to Points does.
    """
    n = sub.npoints
    out = Geometry()
    out._resize_points(n)
    for k, v in sub.attribs[POINT].items():
        if k != "P":
            out.set(POINT, k, v, owned=True)
    out.set(POINT, "P", np.asarray(T, np.float32), owned=True)
    out.set_topology(np.arange(n, dtype=np.int32), np.arange(n + 1, dtype=np.int32),
                     np.zeros(n, bool), np.full(n, PRIM_PACKED, np.uint8))
    out.set(PRIM, XFORM, np.asarray(M, np.float64).reshape(n, 9), owned=True)
    out.set(PRIM, PIVOT, np.asarray(piv, np.float64).reshape(n, 3), owned=True)
    if copynum is not None:
        out.set(POINT, "copynum", np.asarray(copynum, np.int32)[:, None], owned=True)
    info = {"geo": src, "xfer": tuple(xfer), "copynum": copynum is not None}
    out.prim_data = {i: dict(info) for i in range(n)}
    return out


def _piece_ids(geo, by, attr):
    """Primitive -> piece number (points without primitives: one piece per point cloud)."""
    if by == "all":
        return np.zeros(geo.nprims, np.int64), None
    if by == "connectivity":
        from .topology import connectivity
        c = connectivity(geo, PRIM, "__pk_class__")
        return np.asarray(c.get(PRIM, "__pk_class__"))[:, 0].astype(np.int64), None
    a = geo.get(PRIM, attr)
    if a is None:
        ap = geo.get(POINT, attr)
        if ap is None:
            raise ValueError(f"Pack by Piece Attribute: no primitive or point attribute '{attr}'")
        a = ap[geo.vertex_point[geo.prim_offset[:-1].astype(np.int64)]]
    key = a[:, 0] if (is_string(a) or a.shape[1] == 1) else np.array([str(r.tolist()) for r in a])
    uniq, inv = np.unique(key, return_inverse=True)
    return inv.reshape(-1).astype(np.int64), uniq


def pack(geo, group="", pack_by="piece_attribute", piece_attribute="name", pivot="centroid"):
    """Returns (geometry, report)."""
    from .ops import delete_prims
    if pack_by not in PACK_BY:
        raise ValueError(f"Pack By must be one of {PACK_BY}")
    if pivot not in PIVOTS:
        raise ValueError(f"Pivot must be one of {PIVOTS}")
    src = delete_prims(geo, resolve(geo, PRIM, group)) if str(group).strip() else geo
    if is_packed(src):
        src = unpack(src)[0]
    if not src.nprims:
        raise ValueError("Pack needs primitives")
    pid, keys = _piece_ids(src, pack_by, str(piece_attribute).strip())
    pieces, T = [], []
    for p in np.unique(pid):
        piece = delete_prims(src, pid == p)
        P = np.asarray(piece.get(POINT, "P"), np.float64)
        lo, hi = P.min(0), P.max(0)
        c = {"centroid": P.mean(0), "bbox_center": (lo + hi) / 2, "origin": np.zeros(3),
             "bbox_min_y": np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])}[pivot]
        piece = piece.copy()
        piece.set(POINT, "P", (P - c).astype(np.float32), owned=True)
        pieces.append(piece)
        T.append(c)
    n = len(pieces)
    out_parts = []
    for i, piece in enumerate(pieces):
        one = Geometry()
        one._resize_points(1)
        out_parts.append(make_packed(piece, one, np.eye(3)[None], np.asarray(T[i])[None], np.zeros((1, 3)), None,
                                     ("", "", "", "N v up")))
    from .ops import merge
    out = merge(*out_parts)
    if keys is not None and pack_by == "piece_attribute":
        nm = str(piece_attribute).strip()
        vals = keys[np.unique(pid)]
        if vals.dtype == object or vals.dtype.kind in "US":
            out.set_string(PRIM, nm, np.asarray([str(v) for v in vals], dtype=object))
        else:
            out.set(PRIM, nm, np.asarray(vals)[:, None], owned=True)
    return out, {"packed": n, "pack_by": pack_by}


def assemble(geo, group="", name_attribute="name", name_prefix="piece", create_packed=False, pivot="centroid"):
    """
    Houdini's Assemble: number the connected pieces of the group's primitives and name them prefix0, prefix1 ...
    (string prim attribute), optionally packing each piece. Primitives outside the group pass through untouched
    (a missing name stays empty). Returns (geometry, report).
    """
    from .topology import connectivity
    from .ops import delete_prims, merge
    if pivot not in PIVOTS:
        raise ValueError(f"Pivot must be one of {PIVOTS}")
    nm = str(name_attribute).strip() or "name"
    if is_packed(geo):
        geo = unpack(geo)[0]
    if not geo.nprims:
        raise ValueError("Assemble needs primitives")
    sel = resolve(geo, PRIM, group)
    c = connectivity(geo, PRIM, "__asm__")
    lab = np.asarray(c.get(PRIM, "__asm__"))[:, 0].astype(np.int64)
    # renumber the selected pieces 0..k-1 in order of first primitive
    _, first, inv = np.unique(lab[sel], return_index=True, return_inverse=True)
    rank = np.empty(len(first), np.int64)
    rank[np.argsort(first, kind="stable")] = np.arange(len(first))
    piece = np.full(geo.nprims, -1, np.int64)
    piece[sel] = rank[inv.reshape(-1)]
    out = geo.copy()
    old = out.get(PRIM, nm)
    names = (np.asarray(old, dtype=object)[:, 0].astype(str) if old is not None and is_string(old)
             else np.full(geo.nprims, "", dtype=object))
    names = np.array([str(x) for x in names], dtype=object)
    for i in np.nonzero(sel)[0]:
        names[i] = f"{name_prefix}{piece[i]}"
    if old is not None and not is_string(old):
        del out.attribs[PRIM][nm]
    out.set_string(PRIM, nm, names)
    k = int(len(first))
    if not create_packed or not k:
        return out, {"pieces": k, "packed": 0}
    rest = delete_prims(out, ~sel) if (~sel).any() else None
    sub = delete_prims(out, sel)
    pid = piece[sel]
    pieces, T = [], []
    for p in range(k):
        g = delete_prims(sub, pid == p)
        P = np.asarray(g.get(POINT, "P"), np.float64)
        lo, hi = P.min(0), P.max(0)
        cc = {"centroid": P.mean(0), "bbox_center": (lo + hi) / 2, "origin": np.zeros(3),
              "bbox_min_y": np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])}[pivot]
        g = g.copy()
        g.set(POINT, "P", (P - cc).astype(np.float32), owned=True)
        one = Geometry()
        one._resize_points(1)
        pieces.append(make_packed(g, one, np.eye(3)[None], cc[None], np.zeros((1, 3)), None,
                                  ("", "", "", "N v up")))
        T.append(cc)
    pk = merge(*pieces)
    pk.set_string(PRIM, nm, np.array([f"{name_prefix}{p}" for p in range(k)], dtype=object))
    res = merge(rest, pk) if rest is not None else pk
    return res, {"pieces": k, "packed": k}


def unpack(geo, group="", transfer_attributes=""):
    """Returns (geometry, report). Non-packed primitives pass through."""
    from .copyto import expand
    from .ops import delete_points, merge, match_names
    if not is_packed(geo):
        return geo.copy(), {"unpacked": 0}
    sel = resolve(geo, PRIM, group) & (geo.prim_type == PRIM_PACKED)
    pk = np.nonzero(sel)[0]
    used_by_packed = np.zeros(geo.npoints, bool)
    vpt = geo.vertex_point[geo.prim_offset[pk].astype(np.int64)]
    used_by_packed[vpt] = True
    rest = delete_points(geo, ~used_by_packed)
    for nm in (XFORM, PIVOT):
        if nm in rest.attribs[PRIM] and not (rest.prim_type == PRIM_PACKED).any():
            del rest.attribs[PRIM][nm]
    Mx = np.asarray(geo.get(PRIM, XFORM), np.float64).reshape(-1, 3, 3)
    Pv = np.asarray(geo.get(PRIM, PIVOT), np.float64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    order, groups = [], {}
    for i, v in zip(pk, vpt):
        d = geo.prim_data.get(int(i), {})
        key = (id(d.get("geo")), d.get("xfer"), d.get("copynum"))
        if key not in groups:
            groups[key] = (d, [])
            order.append(key)
        groups[key][1].append((int(i), int(v)))
    extra = str(transfer_attributes).strip()
    prim_names = [k for k in geo.attribs[PRIM] if k not in (XFORM, PIVOT)]
    prim_xfer = match_names(prim_names, extra) if extra else []
    parts = [rest] if rest.npoints or rest.nprims else []
    for key in order:
        d, items = groups[key]
        src = d.get("geo")
        if src is None:
            continue
        prims = np.array([a for a, _ in items])
        pts = np.array([b for _, b in items])
        sub = Geometry()
        sub._resize_points(len(pts))
        for k, v in geo.attribs[POINT].items():
            sub.set(POINT, k, v[pts], owned=True)
        ta, tpa, mult, rot = d.get("xfer") or ("", "", "", "N v up")
        if extra:
            ta = (ta + " " + extra).strip()
        cn = sub.get(POINT, "copynum")
        copynum = (np.asarray(cn)[:, 0] if cn is not None else prims) if d.get("copynum") else None
        part = expand(src, sub, Mx[prims], P[pts], Pv[prims], copynum if copynum is not None else prims,
                      ta, tpa, mult, rot)
        if not d.get("copynum"):
            for cls in (POINT, PRIM):
                part.attribs[cls].pop("copynum", None)
        if src.nprims:
            for k in prim_xfer:
                part.set(PRIM, k, np.repeat(geo.get(PRIM, k)[prims], src.nprims, axis=0), owned=True)
        parts.append(part)
    out = merge(*parts) if parts else Geometry()
    return out, {"unpacked": len(pk), "pieces": len(order), "points": out.npoints}


def instances(geo):
    """
    For the viewport: [(piece geometry, (n,4,4) column-major-ready matrices, point indices)] per distinct piece.
    Matrix rows/cols follow the column-vector convention: X = [[M, T - M piv], [0, 0, 0, 1]].
    """
    if not is_packed(geo):
        return []
    pk = np.nonzero(geo.prim_type == PRIM_PACKED)[0]
    vpt = geo.vertex_point[geo.prim_offset[pk].astype(np.int64)]
    Mx = np.asarray(geo.get(PRIM, XFORM), np.float64).reshape(-1, 3, 3)
    Pv = np.asarray(geo.get(PRIM, PIVOT), np.float64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    groups, order = {}, []
    for i, v in zip(pk, vpt):
        g = geo.prim_data.get(int(i), {}).get("geo")
        if g is None:
            continue
        if id(g) not in groups:
            groups[id(g)] = (g, [], [])
            order.append(id(g))
        groups[id(g)][1].append(int(i))
        groups[id(g)][2].append(int(v))
    out = []
    for k in order:
        g, prims, pts = groups[k]
        prims, pts = np.array(prims), np.array(pts)
        M = Mx[prims]
        X = np.zeros((len(prims), 4, 4))
        X[:, :3, :3] = M
        X[:, :3, 3] = P[pts] - np.einsum("nij,nj->ni", M, Pv[prims])
        X[:, 3, 3] = 1.0
        out.append((g, X, pts))
    return out


def transforms(geo):
    """
    Every packed primitive's placement: (prims, points, M (n,3,3), O (n,3), piece ids (n,)).
    O = P - M @ pivot is where the piece's own origin lands (the instance translation); piece ids number the
    distinct pieces in order of first appearance.
    """
    pk = np.nonzero(geo.prim_type == PRIM_PACKED)[0]
    vpt = geo.vertex_point[geo.prim_offset[pk].astype(np.int64)].astype(np.int64)
    Mx = np.asarray(geo.get(PRIM, XFORM), np.float64).reshape(-1, 3, 3)[pk]
    Pv = np.asarray(geo.get(PRIM, PIVOT), np.float64)[pk]
    P = np.asarray(geo.get(POINT, "P"), np.float64)[vpt]
    ids, seen = np.zeros(len(pk), np.int64), {}
    for j, i in enumerate(pk):
        g = id(geo.prim_data.get(int(i), {}).get("geo"))
        ids[j] = seen.setdefault(g, len(seen))
    return pk, vpt, Mx, P - np.einsum("nij,nj->ni", Mx, Pv), ids


def attach_auto_unpack(mappings):
    """
    Wrap every node that does not handle packed primitives so its geometry inputs arrive unpacked. Idempotent.
    """
    mark = "_pcg_auto_unpack"
    for nid, cls in mappings.items():
        if nid in PACK_AWARE:
            continue
        fn_name = getattr(cls, "FUNCTION", None)
        fn = getattr(cls, fn_name, None) if fn_name else None
        if fn is None or getattr(fn, mark, False):
            continue

        def make(orig):
            def wrapped(self, *args, **kwargs):
                if any(is_packed(a) for a in args) or any(is_packed(v) for v in kwargs.values()):
                    args = tuple(unpack(a)[0] if is_packed(a) else a for a in args)
                    kwargs = {k: (unpack(v)[0] if is_packed(v) else v) for k, v in kwargs.items()}
                return orig(self, *args, **kwargs)
            wrapped.__dict__.update(getattr(orig, "__dict__", {}))
            setattr(wrapped, mark, True)
            wrapped.__wrapped__ = orig
            wrapped.__name__ = getattr(orig, "__name__", "run")
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            return wrapped
        setattr(cls, fn_name, make(fn))
