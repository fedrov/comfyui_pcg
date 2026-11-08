"""
Delete SOP -- deletes elements by condition.

Blast can already delete by group; this node adds **the conditions group specifiers can't express**: delete one in every N,
delete what is outside a bounding box, delete faces facing away from some direction. In Houdini these three are on the Number / Bounding Volume / Normal
tabs of the Delete SOP, copied here as is.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The four filters are an **intersection**, not a union
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    group & number range & bounding volume & normal & expression  =  selection
    operation decides whether the selection is deleted or kept

Intersection means "a filter turned off = select all", which reads naturally when chained: first circle an area with group, then within it
delete one in every 3. A union would make "turning on a filter" mean "deleting more", so adding a condition loosens it --
you'd have to think it backwards every time.

Houdini's Delete actually evaluates each tab independently and then combines them per Operation, which is more convoluted (and has
changed between versions); here the kind that can be explained in one sentence was chosen.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Keep Points: deleting faces **doesn't take the points down with them**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`ops.delete_prims` cleans up points that become isolated by default -- most of the time that is wanted. But "delete all faces
and keep only the point cloud to scatter trees on" is a legitimate use, hence the toggle. Corresponds to Houdini Delete's Keep Points.
"""
from __future__ import annotations

import re

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .groups import resolve, resolve_edges
from .ops import delete_points, delete_prims, prim_normals, prim_centers

# pcg100: edge appended at the end (Houdini's Entity: Edges = delete the endpoints of the selected edges)
ENTITIES = (POINT, PRIM, "edge")
OPERATIONS = ("delete_selected", "keep_selected")
# pcg100: pattern appended at the end (Houdini's Delete by Pattern)
NUMBER_MODES = ("every_nth", "range", "pattern")
VOLUME_TYPES = ("box", "sphere")


def _positions(geo, cls):
    """Points use P, faces use face centres."""
    if cls == POINT:
        P = geo.get(POINT, "P")
        if P is None:
            raise KeyError("The geometry has no P attribute; can't filter by position.")
        return P.astype(np.float64)
    return prim_centers(geo).astype(np.float64)


_PATTERN_TOK = re.compile(r"^[!^]?(\*|\d+(-\d+(:\d+)?)?)$")


def pattern_mask(n, pattern):
    """
    Delete by Pattern: number pattern string; the syntax is the purely numeric half of group specifiers --
    `0 5 12`, `0-20`, `0-20:3` (step), `!3-5`, `*`. **Empty string = select none**
    (Houdini's default for this field is `!*`, which also selects none).

    Group names and @ expressions are not accepted: in Houdini this field is only a number pattern; groups go through Group above.
    Houdini's `a-b:n,m` (take n of every m) is not done; it raises an error rather than silently being parsed as something else.
    """
    toks = str(pattern).split()
    bad = [t for t in toks if not _PATTERN_TOK.match(t)]
    if bad:
        raise ValueError(f"Unrecognized syntax in Pattern {bad}: only numbers, a-b, a-b:step, "
                         f"! exclusion and * are supported.")
    if not toks:
        return np.zeros(n, bool)
    return resolve(Geometry(n), POINT, " ".join(toks))


def number_mask(n, mode="every_nth", start=0, end=-1, step=2, pattern="",
                select_num=1, select_of=1):
    """
    Number filter. end < 0 means to the end.

    In range mode select_num / select_of are Houdini's "Select _ of _": within the range, take the first select_num of every
    select_of (1 of 1 = the whole range, i.e. the previous behaviour).
    """
    if n == 0:
        return np.zeros(0, bool)
    if mode not in NUMBER_MODES:
        raise ValueError(f"Number Mode must be one of {NUMBER_MODES}")
    if mode == "pattern":
        return pattern_mask(n, pattern)
    s = int(start)
    e = n - 1 if int(end) < 0 else min(int(end), n - 1)
    m = np.zeros(n, bool)
    if s > e:
        return m
    if mode == "range":
        k = np.arange(e + 1 - s)
        m[s:e + 1] = (k % max(1, int(select_of))) < max(1, int(select_num))
        return m
    st = max(1, int(step))
    # every_nth: starting at start, one hit every step. step=1 is equivalent to selecting the whole range
    m[s:e + 1:st] = True
    return m


def volume_mask(pos, kind="box", center=(0, 0, 0), size=(1, 1, 1),
                radius=1.0):
    """Bounding volume filter: returns an "inside the volume" mask."""
    c = np.asarray(center, np.float64).reshape(3)
    if kind == "box":
        h = 0.5 * np.abs(np.asarray(size, np.float64).reshape(3))
        d = np.abs(pos - c)
        return np.all(d <= h + 1e-12, axis=1)
    if kind == "sphere":
        return (np.linalg.norm(pos - c, axis=1) <= abs(float(radius)) + 1e-12)
    raise ValueError(f"Volume Type must be one of {VOLUME_TYPES}")


def normal_mask(geo, cls, direction=(0, 1, 0), spread=45.0, normal_attrib=""):
    """
    Normal filter: hits where the angle between the normal and the given direction is within spread.

    By default freshly computed face normals are used instead of the N attribute -- N may have been changed upstream (Facet's cusp,
    a hand-written Wrangle), while the question here is "which way does this face point", which should be answered by topology, not by attributes.
    To filter by attribute, fill in Normal Attribute.
    """
    d = np.asarray(direction, np.float64).reshape(3)
    ln = np.linalg.norm(d)
    if ln < 1e-12:
        raise ValueError("Normal Direction is a zero vector.")
    d = d / ln
    nm = str(normal_attrib).strip()
    if nm:
        N = geo.get(cls, nm)
        if N is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"No normal attribute '{nm}' on {cls}. Existing: {have or '(none)'}")
        if N.shape[1] < 3:
            raise ValueError(f"'{nm}' has only {N.shape[1]} components; it is not a normal.")
        N = N[:, :3].astype(np.float64)
    elif cls == PRIM:
        N = prim_normals(geo, normalize=True).astype(np.float64)
    else:
        N = geo.get(POINT, "N")
        if N is None:
            raise KeyError(
                "Filtering points by normal needs an N attribute on point -- connect a Normal (PCG) first.")
        N = N[:, :3].astype(np.float64)
    L = np.linalg.norm(N, axis=1, keepdims=True)
    N = N / np.where(L < 1e-12, 1.0, L)
    return (N @ d) >= np.cos(np.radians(float(np.clip(spread, 0.0, 180.0))))


def expression_mask(geo, cls, expr):
    """Expression filter. Same syntax as group expressions / Wrangle: `@P.y > 0 & @Cd.r < 0.5`."""
    return resolve(geo, cls, str(expr), empty_is_all=True)


def degenerate_mask(geo, degenerate=True, zero_area=False, open_faces=False,
                    tolerance=0.001):
    """
    Degenerate tab (faces only): three toggles each select one category; the union is taken.

      degenerate  after removing adjacent duplicate point references, closed faces with fewer than 3 points / open lines with fewer than 2
                  (Houdini actually removes duplicate references first and then deletes; here we only **select**, and the remaining faces
                  are untouched -- use Clean to remove duplicate references)
      zero_area   closed faces with area < tolerance^2. Docs: area has squared units, so Tolerance is
                  "the side length of the smallest square not counted as zero area"
      open_faces  open faces (polylines) with perimeter < tolerance. The docs' wording for Treat Open Faces as Closed
                  is exactly "Delete open faces with perimeter less than the tolerance"
    """
    n = geo.nprims
    out = np.zeros(n, bool)
    if n == 0:
        return out
    sizes = geo.prim_sizes()
    closed = np.asarray(geo.prim_closed, bool)
    vprim = geo.vertex_prim()
    vp = geo.vertex_point
    nxt = geo.next_corner() if geo.nvertices else np.zeros(0, np.int64)
    last = np.zeros(geo.nvertices, bool)
    last[geo.prim_offset[1:][sizes > 0] - 1] = True
    seg = ~(last & ~closed[vprim])                # there really is an edge between this corner and the next
    if degenerate:
        # A corner counts as "non-duplicate" only if it points to a different point than the next corner. The last corner of an open line has no next one,
        # so it is compared with the **first** corner -- this doesn't affect the conclusion: when start and end are the same point, either the whole line is
        # that one point (0 or 1, both < 2), or it left and came back in between (at least 2), so the comparison with the threshold
        # 2 is unchanged
        distinct = vp != vp[nxt]
        cnt = np.bincount(vprim[distinct], minlength=n)
        # By the counting above open lines can only be 0 or >= 2, so a threshold of 1 or 2 is the same; 2 follows
        # the literal meaning of "fewer than two distinct points"
        out |= cnt < np.where(closed, 3, 2)
    tol = float(tolerance)
    if zero_area:
        area = np.linalg.norm(prim_normals(geo, normalize=False).astype(np.float64), axis=1)
        out |= closed & (area < tol * tol)
    if open_faces:
        P = geo.get(POINT, "P").astype(np.float64)
        ln = np.linalg.norm(P[vp[nxt]] - P[vp], axis=1) * seg
        out |= ~closed & (np.bincount(vprim, weights=ln, minlength=n) < tol)
    return out


def random_mask(geo, cls, seed=0, percent=50.0, seed_attrib=""):
    """
    Random tab: each element gets a random number in [0,1); those below percent/100 are hits -- so it is
    "**about** percent%", consistent with Houdini's description (but the random numbers are not Houdini's, so the selected
    elements won't be the same set).

    If seed_attrib is given (an integer attribute), it replaces the element number as the random input: elements with the same id
    share the same fate, unaffected by adding / deleting other elements.
    """
    from .wrangle import _hash01
    n = geo.count(cls)
    nm = str(seed_attrib).strip()
    if nm:
        a = geo.get(cls, nm)
        if a is None:
            have = sorted(geo.attribs[cls].keys())
            raise KeyError(f"No seed attribute '{nm}' on {cls}. Existing: {have or '(none)'}")
        if a.dtype.kind not in "iub":
            raise ValueError(f"Seed Attribute '{nm}' must be an integer attribute.")
        ids = np.asarray(a[:, 0], np.float64)
    else:
        ids = np.arange(n, dtype=np.float64)
    return np.asarray(_hash01(ids, int(seed))).reshape(-1) < float(percent) / 100.0


def drop_empty_groups(geo):
    """Delete Unused Groups: removes groups (point / vertex / primitive / edge) left with no members after deleting."""
    g = geo.copy()
    for cls in (POINT, VERTEX, PRIM):
        g.groups[cls] = {k: v for k, v in g.groups[cls].items() if v.any()}
    g.edge_groups = {k: v for k, v in g.edge_groups.items() if len(v)}
    return g


def delete(geo, cls=PRIM, operation="delete_selected", group="",
           use_number=False, number_mode="every_nth", number_start=0,
           number_end=-1, number_step=2,
           use_volume=False, volume_type="box", volume_center=(0, 0, 0),
           volume_size=(1, 1, 1), volume_radius=1.0, volume_invert=False,
           use_normal=False, normal_direction=(0, 1, 0), normal_spread=45.0,
           normal_attrib="", normal_invert=False,
           use_expression=False, expression="",
           keep_points=False,
           number_pattern="", select_num=1, select_of=1,
           use_degenerate=False, degenerate=True, zero_area=False,
           open_faces=False, degenerate_tolerance=0.001,
           use_random=False, rand_seed=0, percent=50.0, seed_attrib="",
           delete_unused_groups=False):
    """
    Deletes elements by condition. The four filters are intersected; see the module docstring.

    When none is turned on and group is also empty, **nothing is done** -- treating an empty group as "select all" here
    would delete the entire geometry, which hardly seems like what anyone wants.
    """
    if geo is None:
        return Geometry()
    if cls not in ENTITIES:
        raise ValueError(f"Entity must be one of {ENTITIES}")
    if operation not in OPERATIONS:
        raise ValueError(f"Operation must be one of {OPERATIONS}")
    tidy = drop_empty_groups if delete_unused_groups else (lambda g: g)
    if cls == "edge":
        return tidy(_delete_edges(geo, operation, group, use_number or use_volume
                                  or use_normal or use_expression
                                  or use_degenerate or use_random))
    n = geo.count(cls)
    if n == 0:
        return tidy(geo.copy())

    has_group = bool(str(group).strip())
    if not (has_group or use_number or use_volume or use_normal
            or use_expression or use_degenerate or use_random):
        return tidy(geo.copy())

    sel = resolve(geo, cls, group) if has_group else np.ones(n, bool)
    if use_number:
        sel &= number_mask(n, number_mode, number_start, number_end,
                           number_step, number_pattern, select_num, select_of)
    if use_volume:
        m = volume_mask(_positions(geo, cls), volume_type, volume_center,
                        volume_size, volume_radius)
        sel &= (~m if volume_invert else m)
    if use_normal:
        m = normal_mask(geo, cls, normal_direction, normal_spread,
                        normal_attrib)
        sel &= (~m if normal_invert else m)
    if use_expression:
        if not str(expression).strip():
            raise ValueError("Filter Expression is on but empty.")
        sel &= expression_mask(geo, cls, expression)
    if use_degenerate:
        if cls != PRIM:
            raise ValueError("The Degenerate tab only makes sense for Primitives; Entity is currently Points.")
        sel &= degenerate_mask(geo, degenerate, zero_area, open_faces,
                               degenerate_tolerance)
    if use_random:
        sel &= random_mask(geo, cls, rand_seed, percent, seed_attrib)

    keep = sel if operation == "keep_selected" else ~sel
    if cls == POINT:
        return tidy(delete_points(geo, keep))
    return tidy(delete_prims(geo, keep, keep_points=keep_points))


def _delete_edges(geo, operation, group, any_filter):
    """
    Entity = Edges: Houdini's wording is "Delete the points associated with each selected
    edge" -- what is deleted is the **endpoints** (along with the faces using them), not dissolving the edges (that is Dissolve).
    
    Only Group is accepted (edge group name, `*` = all edges). How the Number / Bounding Volume / Normal / ... tabs
    would apply to edges (edge numbers? midpoints?) is not documented, and edges have no stable numbers here, so turning them on
    raises an error instead of guessing. With an empty Group, nothing is done, as with the other Entities.
    """
    if any_filter:
        raise ValueError("With Entity = Edges only deleting by Group (edge group) is supported; "
                         "Number / Bounding Volume / Normal / Expression / Degenerate / "
                         "tabs are not implemented for edges.")
    if not str(group).strip() or geo.npoints == 0:
        return geo.copy()
    pairs = resolve_edges(geo, group)
    sel = np.zeros(geo.npoints, bool)
    if len(pairs):
        sel[np.asarray(pairs, np.int64).reshape(-1)] = True
    return delete_points(geo, sel if operation == "keep_selected" else ~sel)
