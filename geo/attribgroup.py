"""
pcg76: attributes and groups -- Attribute Composite, Attribute Mirror, Group from Attribute
Boundary, Partition. (Tangent Field is in tangentfield.py.)

━━ Attribute Composite
The background attribute A (on geo) and foreground attribute B (on the second input; geo itself when not connected) are composited by blend mode:
    result = A + alpha*(blend(A, B) - A)
alpha = Alpha * the foreground's Alpha attribute (if given), clamped to [0,1]. blend per component:
    over B · add A+B · subtract A−B · multiply A·B · divide A/B (A where B=0) ·
    screen 1−(1−A)(1−B) · overlay A<0.5 ? 2AB : 1−2(1−A)(1−B) ·
    min · max · difference |A−B| · average (A+B)/2
Foreground elements are paired with geo's: index (by number; elements missing from the foreground get alpha=0) or attribute (by an
integer / string attribute such as id or name; unmatched get alpha=0; if a value occurs several times in the foreground the first is used). If B has one component and A several, B is broadcast.
A missing background attribute counts as 0 (in over mode that equals "write a new attribute by alpha"). String attributes only support
over (foreground when alpha > 0.5).

━━ Attribute Mirror
Attributes painted on one side of a symmetric mesh are copied to the other: a plane (origin, direction) splits points into two sides,
and the Source Side is the source; every point on the other side mirrors itself across and looks up a value on the source side:
  closest_point  the source point nearest the mirrored position (on a symmetric mesh exactly the mirror point, exact)
  surface        nearest point to the mirrored position on the source-side surface, interpolated by triangle barycentric coordinates (works even when the mesh
                 itself isn't symmetric -- exact for linear attributes, verified in the tests). Only triangles with all three corners on the source side (or on the plane)
                 are used -- the other corner of a triangle crossing the plane still holds the old, unmirrored value. Cost: when the plane
                 cuts through the middle of triangles, the narrow strip along the plane finds no source surface and takes the value on the nearest edge
                 (no issue when the mesh has a column of points on the plane)
Vector attributes (Vectors, default N v up) are reflected by the plane; quaternions (Quaternions, default orient) get
R' = H*R*H (H is the reflection matrix; two reflections give a proper rotation, never a mirror matrix).
Points within Tolerance of the plane don't move; neither do points whose mirrored position is farther than Max Distance (when > 0) from the source; they are counted.
Only point attributes are processed.

━━ Group from Attribute Boundary
Where attribute values change -> group:
  prim    edges whose two adjacent faces have different values (boundaries of regions by name / material)
  vertex  corners on the two sides of an edge with different values (uv seams, hard edges) -- compared once at each endpoint
  point   edges whose two endpoints have different values
Numbers are compared with Tolerance (per component), strings for equality. Include Unshared also counts the mesh's open
boundary. Group Type: edges (edge group) / points (endpoints of boundary edges) / prims (faces adjacent to boundary edges).

━━ Partition
Groups by attribute value: one group for each distinct value, named by replacing $ATTR in Rule with that value.
Integers as is; floats via %g with the decimal point replaced by _ and the minus sign by m; vector components joined with _; characters in strings
that can't appear in group names become _, and a leading digit gets a _ prefix. When two different values map to the same group name they are merged into one group,
counted in the report.
"""
from __future__ import annotations

import re

import numpy as np

from .core import POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import match_names
from .topology import topology

COMPOSITE_MODES = ("over", "add", "subtract", "multiply", "divide", "screen",
                   "overlay", "min", "max", "difference", "average")
COMPOSITE_CLASSES = ("point", "prim", "vertex", "detail")
MATCH_MODES = ("index", "attribute")
MIRROR_SIDES = ("positive", "negative")
MIRROR_LOOKUPS = ("closest_point", "surface")
BOUNDARY_CLASSES = ("prim", "vertex", "point")
BOUNDARY_TYPES = ("edges", "points", "prims")
PARTITION_CLASSES = ("prim", "point", "vertex")


# ═══════════════════════════════════════════════════════════ Attribute Composite
def _blend(mode, A, B):
    if mode == "over":
        return B
    if mode == "add":
        return A + B
    if mode == "subtract":
        return A - B
    if mode == "multiply":
        return A * B
    if mode == "divide":
        return np.where(B != 0, A / np.where(B != 0, B, 1.0), A)
    if mode == "screen":
        return 1 - (1 - A) * (1 - B)
    if mode == "overlay":
        return np.where(A < 0.5, 2 * A * B, 1 - 2 * (1 - A) * (1 - B))
    if mode == "min":
        return np.minimum(A, B)
    if mode == "max":
        return np.maximum(A, B)
    if mode == "difference":
        return np.abs(A - B)
    return 0.5 * (A + B)                               # average


def _match(geo, src, cls, how, key):
    """Index each geo element is matched to in src (-1 if unmatched)."""
    n, m = geo.count(cls), src.count(cls)
    if how == "index":
        idx = np.arange(n)
        return np.where(idx < m, idx, -1)
    ka, kb = geo.get(cls, key), src.get(cls, key)
    if ka is None or kb is None:
        raise KeyError(f"The {cls} of both sides need the match attribute '{key}'")
    ka = np.asarray(ka)[:, 0]
    kb = np.asarray(kb)[:, 0]
    first = {}
    for j, k in enumerate(kb.tolist()):
        first.setdefault(k, j)
    return np.array([first.get(k, -1) for k in ka.tolist()], np.int64)


def attribute_composite(geo, fg=None, attribute_class="point", bg_attribute="Cd",
                        fg_attribute="Cd", output="Cd", mode="over", alpha=1.0,
                        alpha_attribute="", match="index",
                        match_attribute="id"):
    """See the file header. Returns (geometry, report)."""
    cls = attribute_class
    if cls not in COMPOSITE_CLASSES:
        raise ValueError(f"Attribute Class must be one of {COMPOSITE_CLASSES}")
    if mode not in COMPOSITE_MODES:
        raise ValueError(f"Mode must be one of {COMPOSITE_MODES}")
    if match not in MATCH_MODES:
        raise ValueError(f"Match must be one of {MATCH_MODES}")
    src = geo if fg is None else fg
    b = src.get(cls, str(fg_attribute).strip())
    if b is None:
        raise KeyError(f"Foreground {cls} has no attribute '{fg_attribute}'")
    n = geo.count(cls) if cls != DETAIL else 1
    if cls == DETAIL:
        mi = np.zeros(1, np.int64)
    else:
        mi = _match(geo, src, cls, match, str(match_attribute).strip())
    ok = mi >= 0
    a = geo.get(cls, str(bg_attribute).strip())
    al = np.full(n, float(alpha))
    an = str(alpha_attribute).strip()
    if an:
        aa = src.get(cls, an)
        if aa is None or is_string(aa):
            raise KeyError(f"Foreground {cls} has no numeric attribute '{an}'")
        al = al * np.where(ok, np.asarray(aa, np.float64)[np.maximum(mi, 0), 0],
                           0.0)
    al = np.clip(np.where(ok, al, 0.0), 0.0, 1.0)
    g = geo.copy()
    rep = {"matched": int(ok.sum()), "unmatched": int((~ok).sum())}
    name = str(output).strip() or str(bg_attribute).strip()
    if is_string(b):
        if mode != "over":
            raise ValueError("String attributes only support over mode")
        base = (np.asarray(a)[:, 0] if a is not None and is_string(a)
                else np.full(n, "", "<U64"))
        Bv = np.asarray(b)[np.maximum(mi, 0), 0]
        out = np.where(al > 0.5, Bv, base)
        g.set_string(cls, name, out.astype(np.result_type(out.dtype, "<U1"))
                     .reshape(-1, 1))
        return g, rep
    B = np.asarray(b, np.float64)[np.maximum(mi, 0)]
    if a is None:
        A = np.zeros((n, B.shape[1]))
    else:
        if is_string(a):
            raise ValueError(f"Background attribute '{bg_attribute}' is a string, the foreground is numeric")
        A = np.asarray(a, np.float64)
    if B.shape[1] != A.shape[1]:
        if B.shape[1] == 1:
            B = np.repeat(B, A.shape[1], 1)
        elif A.shape[1] == 1 and a is not None:
            A = np.repeat(A, B.shape[1], 1)
        else:
            raise ValueError(f"Component counts don't match: background {A.shape[1]}, foreground {B.shape[1]}")
    R = A + al[:, None] * (_blend(mode, A, B) - A)
    dt = a.dtype if a is not None and a.dtype.kind == "f" and \
        a.shape[1] == R.shape[1] else np.float32
    g.set(cls, name, R.astype(dt), owned=True)
    return g, rep


# ═══════════════════════════════════════════════════════════ Attribute Mirror
def attribute_mirror(geo, attributes="Cd", origin=(0, 0, 0), direction=(1, 0, 0),
                     source_side="positive", lookup="closest_point",
                     vectors="N v up", quaternions="orient", tolerance=1e-6,
                     max_distance=0.0, group=""):
    from .curveframe import mat_to_quat
    from .xform import quat_to_mat
    from . import spatial as _sp
    if source_side not in MIRROR_SIDES:
        raise ValueError(f"Source Side must be one of {MIRROR_SIDES}")
    if lookup not in MIRROR_LOOKUPS:
        raise ValueError(f"Lookup must be one of {MIRROR_LOOKUPS}")
    nd = np.asarray(direction, np.float64)
    if not np.linalg.norm(nd) > 0:
        raise ValueError("Direction cannot be a zero vector")
    nd = nd / np.linalg.norm(nd)
    o = np.asarray(origin, np.float64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    d = (P - o) @ nd
    sgn = 1.0 if source_side == "positive" else -1.0
    tol = float(tolerance)
    # Source: on the source side or exactly on the plane (points on the plane aren't changed, their values serve both sides; without counting them as
    # source, all triangles in the strip along the plane are excluded and points very close to the plane find no surface)
    src = d * sgn >= -tol
    dst = (d * sgn < -tol) & resolve(geo, POINT, group)
    names = [k for k in match_names(list(geo.attribs[POINT].keys()), attributes)
             if k != "P"]
    rep = {"attributes": names, "mirrored_points": 0, "too_far": 0}
    g = geo.copy()
    if not names or not dst.any() or not src.any():
        return g, rep
    di = np.nonzero(dst)[0]
    Q = P[di] - 2 * d[di, None] * nd                     # mirrored onto the source side
    H = np.eye(3) - 2 * np.outer(nd, nd)
    vec = set(match_names(names, vectors))
    qua = set(match_names(names, quaternions))
    if lookup == "closest_point":
        si = np.nonzero(src)[0]
        S_ = P[si]

        def ev(qi, ti):
            return np.linalg.norm(Q[qi] - S_[ti], axis=1), np.zeros((len(qi), 0))
        k, bd, _ = _sp.nearest(Q, S_, S_, ev)
        best = si[np.maximum(k, 0)]
        W = None
    else:
        from .spatial import tri_soup
        tri, _, _ = tri_soup(geo)
        keep = src[tri].all(1)
        tri = tri[keep]
        if not len(tri):
            raise ValueError("No complete triangles on the source side (surface mode needs faces with all three corners on the source side)")
        ti, _, pos, uv = _sp.closest_surface(Q, P, tri)
        bd = np.linalg.norm(pos - Q, axis=1)
        tri_pts = tri[np.maximum(ti, 0)]
        W = np.stack([1 - uv[:, 0] - uv[:, 1], uv[:, 0], uv[:, 1]], 1)
    far = bd > float(max_distance) if float(max_distance) > 0 else \
        np.zeros(len(Q), bool)
    use = ~far
    rep["too_far"] = int(far.sum())
    rep["mirrored_points"] = int(use.sum())
    for k in names:
        v = geo.get(POINT, k)
        if is_string(v):
            if W is None:
                val = np.asarray(v)[best]
            else:
                val = np.asarray(v)[tri_pts[np.arange(len(Q)), W.argmax(1)]]
            out = np.asarray(v).copy()
            out[di[use]] = val[use]
            g.set(POINT, k, out, owned=True)
            continue
        vv = np.asarray(v, np.float64)
        if W is None:
            val = vv[best]
        else:
            val = (vv[tri_pts] * W[:, :, None]).sum(1)
        if k in vec and vv.shape[1] >= 3:
            val[:, :3] = val[:, :3] @ H.T
        elif k in qua and vv.shape[1] == 4:
            if W is not None:
                val = val / np.maximum(np.linalg.norm(val, axis=1, keepdims=True),
                                       1e-300)
            R = quat_to_mat(val)
            val = mat_to_quat(np.einsum("ij,njk,kl->nil", H, R, H))
        out = vv.copy()
        out[di[use]] = val[use]
        g.set(POINT, k, (np.rint(out) if v.dtype.kind in "iub" else out)
              .astype(v.dtype), owned=True)
    return g, rep


# ═══════════════════════════════════════════════════════════ attribute boundary -> group
def _differs(V, i, j, tol):
    if is_string(V):
        return V[i, 0] != V[j, 0]
    return (np.abs(np.asarray(V[i], np.float64) - np.asarray(V[j], np.float64))
            > tol).any(1)


def group_from_attribute_boundary(geo, attribute, attribute_class="prim",
                                  group_name="boundary", group_type="edges",
                                  include_unshared=False, tolerance=1e-5):
    if attribute_class not in BOUNDARY_CLASSES:
        raise ValueError(f"Attribute Class must be one of {BOUNDARY_CLASSES}")
    if group_type not in BOUNDARY_TYPES:
        raise ValueError(f"Group Type must be one of {BOUNDARY_TYPES}")
    name = str(attribute).strip()
    V = geo.get(attribute_class, name)
    if V is None:
        raise KeyError(f"{attribute_class} has no attribute '{name}'")
    gname = str(group_name).strip()
    if not gname:
        raise ValueError("Group Name cannot be empty")
    t = topology(geo)
    tol = float(tolerance)
    vp = np.asarray(geo.vertex_point, np.int64)
    vpr = geo.vertex_prim().astype(np.int64)
    nxt = geo.next_corner().astype(np.int64)
    ep = t.edge_points.astype(np.int64)
    cnt = t.edge_count
    mark = np.zeros(t.nedges, bool)
    if attribute_class == "point":
        mark = _differs(V, ep[:, 0], ep[:, 1], tol) & (cnt >= 1)
    else:
        # Compare every pair of half-edges of each edge (non-manifold edges too: any two differing counts)
        multi = np.nonzero(cnt >= 2)[0]
        for k in range(1, int(cnt.max()) if len(cnt) else 1):
            e = multi[cnt[multi] > k]
            if not len(e):
                continue
            h0 = t.edge_he[t.edge_he_off[e]].astype(np.int64)
            hk = t.edge_he[t.edge_he_off[e] + k].astype(np.int64)
            if attribute_class == "prim":
                mark[e] |= _differs(V, vpr[h0], vpr[hk], tol)
            else:
                # Corners of the two half-edges at the same endpoint: start with start, end with end
                same = vp[h0] == vp[hk]
                a0, b0 = h0, nxt[h0]
                ak = np.where(same, hk, nxt[hk])
                bk = np.where(same, nxt[hk], hk)
                mark[e] |= _differs(V, a0, ak, tol) | _differs(V, b0, bk, tol)
    if include_unshared:
        mark |= cnt == 1
    g = geo.copy()
    pairs = ep[mark].astype(np.int32)
    if group_type == "edges":
        g.set_edge_group(gname, pairs)
    elif group_type == "points":
        m = np.zeros(geo.npoints, bool)
        m[pairs.reshape(-1)] = True
        g.set_group(POINT, gname, m)
    else:
        m = np.zeros(geo.nprims, bool)
        e = np.nonzero(mark)[0]
        if len(e):
            from .ops import _gather_blocks
            hs = t.edge_he[_gather_blocks(t.edge_he_off[e], cnt[e])]
            m[vpr[hs]] = True
        g.set_group(PRIM, gname, m)
    return g, {"boundary_edges": int(mark.sum())}


# ═══════════════════════════════════════════════════════════ Partition
def _token(v, is_str):
    if is_str:
        return str(v)
    out = []
    for x in np.atleast_1d(v).tolist():
        if float(x).is_integer() and abs(x) < 1e15:
            s = str(int(x))
        else:
            s = "%g" % x
        out.append(s.replace("-", "m").replace(".", "_").replace("+", ""))
    return "_".join(out)


def _sanitize(s):
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    if not s or s[0].isdigit():
        s = "_" + s
    return s


def partition(geo, attribute, attribute_class="prim", rule="grp_$ATTR"):
    if attribute_class not in PARTITION_CLASSES:
        raise ValueError(f"Attribute Class must be one of {PARTITION_CLASSES}")
    name = str(attribute).strip()
    V = geo.get(attribute_class, name)
    if V is None:
        raise KeyError(f"{attribute_class} has no attribute '{name}'")
    if "$ATTR" not in str(rule):
        raise ValueError("Rule needs $ATTR (e.g. grp_$ATTR), otherwise all values go into the same group")
    s = is_string(V)
    vals = np.asarray(V)
    if s:
        uniq, inv = np.unique(vals[:, 0], return_inverse=True)
    else:
        uniq, inv = np.unique(vals, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    g = geo.copy()
    groups = {}
    for k, u in enumerate(uniq):
        gn = _sanitize(str(rule).replace("$ATTR", _token(u, s)))
        groups.setdefault(gn, []).append(k)
    for gn, ks in groups.items():
        g.set_group(attribute_class, gn, np.isin(inv, ks))
    return g, {"groups": sorted(groups), "values": int(len(uniq)),
               "merged": int(len(uniq) - len(groups))}
