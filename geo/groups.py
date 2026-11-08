"""
Group specifier parsing. Modelled on the group field found on Houdini's SOPs.

Three kinds of syntax are supported; the rule is **if there's an @, the whole string is an expression, otherwise it's parsed as tokens**:

    ""  or  "*"          all elements
    "grpA"               named group
    "grpA grpB"          union
    "grpA !grpB"         subtract grpB from grpA (^ is an alias of !)
    "0 5 12"             element numbers
    "0-20"               closed range
    "0-20:3"             with step
    "!0-10"              all except these
    "@P.y > 0.5"         attribute expression (vectorized, same syntax as Wrangle)
    "@Cd.x > 0.5 & @P.y < 0"

No mixed parsing is deliberate: in Houdini `@` expressions and group names can be mixed, but that needs a
real lexer, and spaces are ambiguous inside expressions. Here "the whole string is one or the other" removes
that complexity, at the cost that using a group and an expression together takes two nodes.
"""
from __future__ import annotations

import re

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, EDGE, DETAIL
from . import wrangle as _wr

_RANGE = re.compile(r"^(-?\d+)-(-?\d+)(?::(\d+))?$")


class _ReadBind:
    """Read-only attribute access proxy for expressions. Can't write; group expressions shouldn't write attributes anyway."""

    def __init__(self, geo: Geometry, cls: str):
        self.geo, self.cls = geo, cls
        self.n = geo.count(cls)

    def __getitem__(self, name):
        a = self.geo.get(self.cls, name)
        if a is None:
            raise KeyError(f"{self.cls} attribute '{name}' in group expression does not exist")
        # Same broadcasting as Wrangle (Vec): in @P.y > @floors * 3.5 the left is (N,) and the right (N,1);
        # bare numpy would broadcast to NxN -- the "group" that came out used to have row count that happened to equal N, quietly selecting a big wrong chunk
        return _wr._cols(a)

    def __setitem__(self, name, value):
        raise RuntimeError("Group expressions can't write attributes, only evaluate")


def _fix_logic(expr: str) -> str:
    """
    Add parentheses around both sides of top-level & / |, and treat && || and Python's and / or / not as aliases.

    In Python & has **higher** precedence than comparison operators, so `@P.x > 0 & @P.z < 0`
    parses as `@P.x > (0 & @P.z) < 0`, a straight TypeError. In VEX && has lower precedence
    than comparisons, the exact opposite habit. Rather than making people remember parentheses every time, add them here.

    Passing and / or straight to Python would take the truth value of arrays ("truth value is ambiguous"),
    so they're replaced word-wise with & / |; not X / !X becomes ~(X). Strings inside quotes are left alone.
    """
    # 1) and/or/not and &&/|| outside quotes are normalized into single-character tokens
    toks, i, q = [], 0, None
    e = expr
    while i < len(e):
        ch = e[i]
        if q:
            toks.append(ch)
            if ch == "\\" and i + 1 < len(e):
                toks.append(e[i + 1]); i += 2; continue
            if ch == q:
                q = None
            i += 1
            continue
        if ch in "\"'":
            q = ch; toks.append(ch); i += 1; continue
        if e.startswith("&&", i) or e.startswith("||", i):
            toks.append(ch); i += 2; continue
        m = _WORD_OP.match(e, i)
        if m and (i == 0 or not (e[i - 1].isalnum() or e[i - 1] in "_@.")):
            w = m.group(1)
            toks.append({"and": "&", "or": "|", "not": "\0"}[w])
            i = m.end(1)
            continue
        if ch == "!" and not e.startswith("!=", i):
            toks.append("\0"); i += 1; continue
        toks.append(ch)
        i += 1
    e = "".join(toks)

    # 2) split at top-level & | (those inside parentheses / quotes don't count)
    def split(e):
        parts, buf, depth, q = [], [], 0, None
        for ch in e:
            if q:
                buf.append(ch)
                if ch == q:
                    q = None
                continue
            if ch in "\"'":
                q = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if depth == 0 and q is None and ch in "&|":
                parts.append("".join(buf)); parts.append(ch); buf = []
                continue
            buf.append(ch)
        parts.append("".join(buf))
        return parts

    def term(t):
        t = t.strip()
        if t.startswith("\0"):
            return f"~({term(t[1:])})"
        if t.startswith("(") and t.endswith(")") and _balanced(t[1:-1]):
            inner = t[1:-1]
            if "\0" in inner or len(split(inner)) > 1:
                return f"({fix(inner)})"
        return t.replace("\0", "~")

    def fix(e):
        parts = split(e)
        if len(parts) == 1:
            t = term(parts[0])
            return t
        out = []
        for tok in parts:
            if tok in ("&", "|"):
                out.append(f" {tok} ")
            else:
                t = term(tok)
                out.append(f"({t})" if t else "")
        return "".join(out)

    return fix(e)


_WORD_OP = re.compile(r"(and|or|not)(?![\w])")


def _balanced(s):
    d, q = 0, None
    for ch in s:
        if q:
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch in "([{":
            d += 1
        elif ch in ")]}":
            d -= 1
            if d < 0:
                return False
    return d == 0


def _eval_expr(geo, cls, spec):
    py, _ = _wr._transpile(_fix_logic(spec))
    n = geo.count(cls)
    ns = _wr._namespace()
    ns["_A"] = _ReadBind(geo, cls)
    ns["_ELEMNUM"] = np.arange(n, dtype=np.int32)
    ns["_NUMELEM"] = n
    _wr.check_code(py, "Group expression", "eval")
    try:
        r = eval(compile(py, "<group>", "eval"), ns)
    except SyntaxError as e:
        raise RuntimeError(
            f"A group expression must be **an expression**, not a statement: {spec}") from e
    except Exception as e:
        raise RuntimeError(
            f"Group expression evaluation failed: {type(e).__name__}: {e}\n"
            f"  Original: {spec}\n  Translated: {py}") from e

    r = np.asarray(r)
    if r.ndim == 2 and r.shape[1] == 1:
        r = r[:, 0]
    if r.ndim == 0:
        r = np.full(n, bool(r))
    if r.ndim != 1 or r.shape[0] != n:
        raise RuntimeError(
            f"Group expression result shape {r.shape} doesn't match the {cls} element count {n} "
            f"(need one true/false value per element)")
    return r.astype(bool)


def resolve(geo: Geometry, cls: str, spec, empty_is_all=True) -> np.ndarray:
    """Parse a group specifier into an (n,) boolean mask."""
    n = geo.count(cls)
    if spec is None or not str(spec).strip():
        return np.ones(n, bool) if empty_is_all else np.zeros(n, bool)
    spec = str(spec).strip()

    if "@" in spec:
        return _eval_expr(geo, cls, spec)

    pos = np.zeros(n, bool)
    neg = np.zeros(n, bool)
    any_pos = False

    for tok in spec.split():
        target, t = pos, tok
        if t[0] in "!^":
            target, t = neg, t[1:]
        else:
            any_pos = True
        if not t:
            continue

        if t == "*":
            target |= True
            continue

        m = _RANGE.match(t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            st = int(m.group(3) or 1)
            if a > b:
                a, b = b, a
            idx = np.arange(a, b + 1, max(1, st))
            idx = idx[(idx >= 0) & (idx < n)]
            target[idx] = True
            continue

        if re.fullmatch(r"-?\d+", t):
            i = int(t)
            if -n <= i < n:
                target[i] = True
            continue

        g = geo.get_group(cls, t)
        if g is None:
            known = sorted(geo.groups.get(cls, {}).keys())
            raise KeyError(
                f"No group '{t}' on {cls}. Existing groups: {known or '(none)'}")
        target |= g

    if not any_pos:
        pos[:] = True                 # only exclusions were written, so the base is everything
    return pos & ~neg


def to_prim_mask(geo, cls, mask):
    """Promote a point mask to prim level: a prim is in only if all its points are."""
    if cls == PRIM or geo.nprims == 0:
        return mask
    ok = mask[geo.vertex_point].astype(np.int8)
    return np.minimum.reduceat(ok, geo.prim_offset[:-1]).astype(bool)


def to_point_mask(geo, cls, mask):
    """Spread a prim mask to point level: points referenced by any selected prim are in."""
    if cls == POINT or geo.nprims == 0:
        return mask
    out = np.zeros(geo.npoints, bool)
    sel = np.repeat(mask, geo.prim_sizes())
    out[geo.vertex_point[sel]] = True
    return out


# ---------------------------------------------------------------- Group Create
#
# Modelled on Houdini's Group Create SOP: several filter sections stacked in one node, each with its own toggle.
# Semantics follow Houdini's wording:
#   Base Group          starting set; off means "select all"
#   Keep in Bounding..  intersect
#   Keep by Normals     intersect
#   Include by Edges    intersect by default, can be switched to union. Houdini calls it "Include", implying union,
#                       but when the base set is everything, union means no filtering, so nobody actually uses it that way --
#                       hence the default is "keep"; switch to include if you really want to add to it.
#   Keep by Random..    intersect
# Finally merge with an existing group of the same name per the merge mode.

def _bbox_mask(geo, cls, center, size, partial):
    P = geo.get(POINT, "P")
    c = np.asarray(center, np.float32)
    h = np.abs(np.asarray(size, np.float32)) * 0.5
    inside = np.all((P >= c - h) & (P <= c + h), axis=1)
    if cls == POINT:
        return inside
    if geo.nprims == 0:
        return np.zeros(geo.count(cls), bool)
    v = inside[geo.vertex_point].astype(np.int8)
    red = np.maximum if partial else np.minimum
    m = red.reduceat(v, geo.prim_offset[:-1]).astype(bool)
    if cls == PRIM:
        return m
    return np.repeat(m, geo.prim_sizes())


def _normal_mask(geo, cls, direction, spread, both):
    from .ops import prim_normals, compute_normals
    d = np.asarray(direction, np.float32)
    n = np.linalg.norm(d)
    if n == 0:
        return np.ones(geo.count(cls), bool)
    d = d / n

    if cls == PRIM:
        N = geo.get(PRIM, "N")
        if N is None:
            N = prim_normals(geo)
    else:
        N = geo.get(POINT, "N")
        if N is None:
            N = compute_normals(geo, "point").get(POINT, "N")
        if cls == VERTEX:
            N = N[geo.vertex_point]

    ln = np.linalg.norm(N, axis=1, keepdims=True)
    dot = (N / np.where(ln == 0, 1, ln)) @ d
    if both:
        dot = np.abs(dot)

    sp = float(np.clip(spread, 0.0, 180.0))
    if sp >= 180.0:
        return np.ones(len(dot), bool)          # take everything, don't let float error drop back-facing ones

    # Compare using cosines to avoid an arccos per element. But cos(radians(90)) isn't 0, it's
    # 6.12e-17 -- elements whose normal is exactly perpendicular to the direction (sphere equator points, pole points) have dot exactly 0,
    # and a strict comparison would exclude them all. So keep a tolerance so "exactly on the boundary" counts as in the group,
    # which also matches Houdini's behaviour.
    return dot >= float(np.cos(np.radians(sp))) - 1e-6


def _edge_mask(geo, cls, min_angle, max_angle, unshared, use_angle=True):
    """
    Each Include by Edges rule **selects on its own and the results are unioned** (Houdini: each one
    "Groups primitives with ..."). Before pcg85, turning on Unshared stopped looking at the angle;
    the two rules were mutually exclusive. Boundary edges have only one adjacent primitive and no dihedral angle, so the angle rule can't select them.
    """
    from . import topology as _tp
    t = _tp.topology(geo)
    if t.nedges == 0:
        return np.zeros(geo.count(cls), bool)
    sel = np.zeros(t.nedges, bool)
    if unshared:
        sel |= t.boundary
    if use_angle:
        ang = _tp.edge_angles(geo)
        sel |= (t.edge_count == 2) & (ang >= float(min_angle)) \
            & (ang <= float(max_angle))

    if cls == POINT:
        m = np.zeros(geo.npoints, bool)
        m[t.edge_points[sel].reshape(-1)] = True
        return m
    m = np.zeros(geo.nprims, bool)
    if sel.any():
        m[geo.vertex_prim()[t.edge_he[np.repeat(sel, t.edge_count)]]] = True
    return m if cls == PRIM else np.repeat(m, geo.prim_sizes())


def create(geo: Geometry, cls: str, name: str, base="",
           use_bbox=False, center=(0, 0, 0), size=(1, 1, 1), bbox_partial=False,
           use_normal=False, direction=(0, 0, 1), spread=180.0, both_dirs=False,
           use_edges=False, min_angle=20.0, max_angle=180.0, unshared=False,
           edge_combine="include",
           use_random=False, seed=0, percent=50.0,
           merge="replace", use_angle=True):
    """
    As in Houdini's Group Create: Base / Bounding / Normals / Random are Keep
    (intersect), Include by Edges is Include -- elements selected by the edge rules go in "regardless of the other tabs",
    so it is unioned in last, and Random won't filter it out either.

    An empty base is like Houdini without Base Group enabled: with a Keep tab on, start from all elements;
    with only Include by Edges on, start from the empty set (otherwise "all U edges" is still all, and the edges tab
    would be pointless). edge_combine="keep" is this plugin's addition: the edge rules act as Keep.
    Before pcg85 the default was keep and Random came after edges, both the opposite of Houdini.
    """
    n = geo.count(cls)
    include = use_edges and edge_combine == "include"
    keeps = use_bbox or use_normal or use_random or (use_edges and not include)
    if not str(base or "").strip() and include and not keeps:
        m = np.zeros(n, bool)
    else:
        m = resolve(geo, cls, base)                   # empty base = select all

    if use_bbox:
        m &= _bbox_mask(geo, cls, center, size, bbox_partial)
    if use_normal:
        m &= _normal_mask(geo, cls, direction, spread, both_dirs)
    if use_random:
        r = np.random.default_rng(int(seed)).random(n)
        m &= r < np.clip(percent, 0.0, 100.0) / 100.0
    if use_edges:
        e = _edge_mask(geo, cls, min_angle, max_angle, unshared, use_angle)
        m = (m | e) if include else (m & e)

    old = geo.get_group(cls, name)
    if old is not None and merge != "replace":
        m = {"union": lambda: old | m,
             "intersect": lambda: old & m,
             "subtract": lambda: old & ~m}[merge]()

    g = geo.copy()
    g.set_group(cls, name, m)
    return g


# ------------------------------------------------------------------ edge groups
def resolve_points_guess(geo: Geometry, spec) -> np.ndarray:
    """
    Point mask, Group Type = guess (Houdini's default): first parse as a point group / point attribute expression;
    if points don't have that group / attribute but primitives do, take the points those primitives use. So in Transform's group
    you can write a primitive group name, or @part == "LOD1" (a primitive attribute), and both work.
    """
    try:
        return resolve(geo, POINT, spec)
    except (KeyError, RuntimeError) as e_pt:
        try:
            pm = resolve(geo, PRIM, spec)
        except (KeyError, RuntimeError):
            raise e_pt
        m = np.zeros(geo.npoints, bool)
        idx = np.nonzero(pm)[0]
        if len(idx):
            sizes = geo.prim_sizes()
            off = geo.prim_offset
            corners = np.concatenate([np.arange(off[i], off[i] + sizes[i]) for i in idx])
            m[geo.vertex_point[corners]] = True
        return m


_EDGE_PAIR = re.compile(r"^p\d+(?:-\d+)+$")


def resolve_edges(geo: Geometry, spec) -> np.ndarray:
    """
    Edge group spec -> (E,2) point pairs. Supports group names, unions of several group names, wildcards (edge_*),
    point-pair syntax p3-7 / p0-1-2, and "*"/empty for all edges. Nonexistent group names raise (KeyError).

    Edges aren't a standalone element class and have no stable numbering, so selection by number like "0-10:2" isn't supported here --
    numbers change with topology, and an expression written today would point at different edges next time. To select edges by geometric condition,
    use Group Create's Edges section (angle, boundary, length).
    """
    from . import topology as _tp
    if spec is None or not str(spec).strip() or str(spec).strip() == "*":
        t = _tp.topology(geo)
        return np.asarray(t.edge_points, np.int32)
    import fnmatch
    out = []
    for name in str(spec).split():
        m = _EDGE_PAIR.match(name)
        if m:
            # Houdini's point-pair syntax: p3-7 (one edge between two adjacent points), p0-1-2 = two edges 0-1, 1-2
            ids = [int(x) for x in name[1:].split("-")]
            if max(ids) >= geo.npoints:
                raise KeyError(f"Edge '{name}' references a nonexistent point (there are only {geo.npoints} points)")
            out.append(np.asarray(list(zip(ids[:-1], ids[1:])), np.int32).reshape(-1, 2))
            continue
        if any(c in name for c in "*?["):
            hits = [k for k in geo.edge_groups if fnmatch.fnmatchcase(k, name)]
        elif name in geo.edge_groups:
            hits = [name]
        else:
            # used to be silently ignored -- a misspelled group name quietly turned the whole operation into "select nothing"
            have = sorted(geo.edge_groups)
            raise KeyError(f"Edge group '{name}' does not exist. Existing edge groups: {have or '(none)'}")
        for k in hits:
            v = geo.edge_groups[k]
            if v is not None and len(v):
                out.append(np.asarray(v, np.int32).reshape(-1, 2))
    if not out:
        return np.zeros((0, 2), np.int32)
    return np.unique(np.sort(np.concatenate(out), axis=1), axis=0)


def edge_mask(geo: Geometry, pairs) -> np.ndarray:
    """(E,2) point pairs -> edge mask (nedges,) bool for the current topology."""
    from . import topology as _tp
    t = _tp.topology(geo)
    m = np.zeros(t.nedges, bool)
    if not len(pairs) or t.nedges == 0:
        return m
    key = t.edge_points[:, 0].astype(np.int64) * (geo.npoints + 1) \
        + t.edge_points[:, 1]
    q = np.sort(np.asarray(pairs, np.int64), axis=1)
    qk = q[:, 0] * (geo.npoints + 1) + q[:, 1]
    order = np.argsort(key)
    pos = np.searchsorted(key[order], qk)
    pos = np.clip(pos, 0, len(key) - 1)
    hit = key[order][pos] == qk
    m[order[pos[hit]]] = True
    return m


def edges_to_points(geo, pairs) -> np.ndarray:
    m = np.zeros(geo.npoints, bool)
    if len(pairs):
        m[np.asarray(pairs, np.int64).reshape(-1)] = True
    return m


def edges_to_prims(geo, pairs) -> np.ndarray:
    from . import topology as _tp
    t = _tp.topology(geo)
    m = np.zeros(geo.nprims, bool)
    sel = edge_mask(geo, pairs)
    if sel.any():
        he = t.edge_he[np.repeat(sel, t.edge_count)]
        m[geo.vertex_prim()[he]] = True
    return m


def points_to_edges(geo, mask) -> np.ndarray:
    """Edges whose two endpoints are both in the point group."""
    from . import topology as _tp
    t = _tp.topology(geo)
    if t.nedges == 0:
        return np.zeros((0, 2), np.int32)
    m = np.asarray(mask, bool)
    ep = t.edge_points
    return np.asarray(ep[m[ep[:, 0]] & m[ep[:, 1]]], np.int32)


def prims_to_edges(geo, mask, interior_only=False) -> np.ndarray:
    """Edges of selected primitives. With interior_only=True, only interior edges whose both sides are selected."""
    from . import topology as _tp
    t = _tp.topology(geo)
    if t.nedges == 0:
        return np.zeros((0, 2), np.int32)
    m = np.asarray(mask, bool)
    vprim = geo.vertex_prim()
    keep = np.zeros(t.nedges, bool)
    for e in range(t.nedges):
        hs = t.edge_he[t.edge_he_off[e]:t.edge_he_off[e + 1]]
        owners = m[vprim[hs]]
        keep[e] = owners.all() and (len(hs) == 2 or not interior_only) \
            if interior_only else owners.any()
    return np.asarray(t.edge_points[keep], np.int32)


def create_edges(geo: Geometry, name: str, base="",
                 use_angle=False, min_angle=20.0, max_angle=180.0,
                 unshared=False,
                 use_length=False, min_length=0.0, max_length=1e9,
                 use_random=False, seed=0, percent=50.0,
                 merge="replace") -> Geometry:
    """Build edge groups by geometric condition. Modelled on the Edges section of Houdini's Group Create."""
    from . import topology as _tp
    t = _tp.topology(geo)
    pairs = resolve_edges(geo, base)
    sel = edge_mask(geo, pairs)

    if unshared:
        sel &= t.boundary
    if use_angle:
        ang = _tp.edge_angles(geo)
        sel &= (ang >= float(min_angle)) & (ang <= float(max_angle))
    if use_length:
        L = _tp.edge_lengths(geo)
        sel &= (L >= float(min_length)) & (L <= float(max_length))
    if use_random:
        r = np.random.default_rng(int(seed)).random(t.nedges)
        sel &= r < np.clip(percent, 0.0, 100.0) / 100.0

    new = np.asarray(t.edge_points[sel], np.int32)
    old = geo.edge_groups.get(name)
    if old is not None and len(old) and merge != "replace":
        a = {tuple(x) for x in np.sort(old, axis=1).tolist()}
        b = {tuple(x) for x in np.sort(new, axis=1).tolist()}
        r = {"union": a | b, "intersect": a & b, "subtract": a - b}[merge]
        new = np.asarray(sorted(r), np.int32).reshape(-1, 2)

    g = geo.copy()
    g.set_edge_group(name, new)
    return g
