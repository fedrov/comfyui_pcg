"""
Add SOP -- creates points from nothing, connects points into polygons, and "keeps only the points, dropping primitives".

In Houdini this node has three jobs; it looks like a grab bag, but it is all about one thing: **the membership relation between points and
prims**. Creating points, connecting, removing primitives and cleaning isolated points all change that relation, never coordinates.

Two UI differences from Houdini, both to fit ComfyUI:

1) In Houdini, coordinates and connections are multiparms (parameter blocks like "Number of Points" that can grow and shrink).
   ComfyUI has no multiparm, and dynamically adding/removing widgets misaligns all parameters when a workflow is restored
   (the same pitfall noted in pcg_sections.js). So they are multi-line text instead:
   one point / one polygon per line. Even handier than a multiparm -- you can paste tables directly.

2) The index strings reuse the token syntax of the group field (`0-9`, `0-20:3`, negatives count from the end),
   but **keep order and duplicates**: polygons have a winding order, `3 1 2` and `1 2 3` are different faces,
   and groups.resolve returns a boolean mask that inherently loses order, so parsing is done here.
"""
from __future__ import annotations

import re

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .groups import resolve
from .ops import merge, delete_points

_RANGE = re.compile(r"^(-?\d+)-(-?\d+)(?::(\d+))?$")
_SEP = re.compile(r"[\s,;]+")


# ═══════════════════════════════════════════════════════════════ parsing
def parse_points(text):
    """
    Multi-line coordinates -> (M,3) float32.

    One point per line, x y z separated by spaces / commas / semicolons; lines starting with `#` are comments.
    With only two numbers z=0 is filled in (handy for pasting planar coordinates); with four the fourth (homogeneous w) is dropped.
    """
    out = []
    for lineno, raw in enumerate(str(text).splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p for p in _SEP.split(line) if p]
        try:
            v = [float(p) for p in parts]
        except ValueError:
            raise ValueError(f"Line {lineno} is not a coordinate: {raw!r}")
        if len(v) == 2:
            v = [v[0], v[1], 0.0]
        elif len(v) >= 4:
            v = v[:3]
        elif len(v) != 3:
            raise ValueError(f"Line {lineno} needs 2-4 numbers, got {len(v)}: {raw!r}")
        out.append(v)
    return np.asarray(out, np.float32).reshape(-1, 3)


def parse_indices(spec, n):
    """
    Point number string -> ordered list of point numbers.

    `5` single / `0-9` closed range / `0-20:3` with step / `-1` counted from the end.
    Order and duplicates are kept -- the polygon's winding lives in them. Out-of-range numbers raise an error;
    silently skipping them would give a face "missing a corner", which is harder to track down.
    """
    out = []
    for tok in (t for t in _SEP.split(str(spec).strip()) if t):
        m = _RANGE.match(tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            st = max(1, int(m.group(3) or 1))
            a = a + n if a < 0 else a
            b = b + n if b < 0 else b
            rng = range(a, b + 1, st) if a <= b else range(a, b - 1, -st)
            out.extend(rng)
            continue
        if re.fullmatch(r"-?\d+", tok):
            i = int(tok)
            out.append(i + n if i < 0 else i)
            continue
        raise ValueError(f"Unrecognized syntax in point number string: {tok!r}")
    bad = [i for i in out if not 0 <= i < n]
    if bad:
        raise ValueError(f"Point numbers {bad[:5]} out of range ({n} points)")
    return out


# ═══════════════════════════════════════════════════════════════ topology changes
def _pad(v, n):
    """Pads an attribute array to n rows; the padding is 0 / empty string."""
    if len(v) >= n:
        return v
    fill = np.zeros((n - len(v), v.shape[1]), v.dtype)
    return np.concatenate([v, fill])


def strip_prims(geo):
    """
    Drops all prims, keeping every point -- Houdini's "Delete Geometry But Keep the Points".

    This is the most used mode of the Add SOP: any mesh plugged in becomes a point cloud, with point attributes and point groups
    all carried along. Vertex attributes only exist with prims; once prims are gone, so are they.
    """
    out = Geometry()
    out._resize_points(geo.npoints)
    out.set_topology(np.zeros(0, np.int32), np.zeros(1, np.int32),
                     np.zeros(0, bool))
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.edge_groups = dict(geo.edge_groups)   # edge groups store point pairs; they stay valid as long as the points remain
    return out


def append_prims(geo, faces, closed=True):
    """
    Appends a batch of prims after the existing geometry. closed can be one boolean or given per prim.

    New prims get vertex / prim attributes padded with 0 and groups padded with False -- consistent with how ops.merge handles
    missing attributes; otherwise the same geometry taking two paths would end up with different attribute tables.
    """
    faces = [np.asarray(f, np.int32).reshape(-1) for f in faces]
    faces = [f for f in faces if len(f)]
    if not faces:
        return geo.copy()
    sizes = np.array([len(f) for f in faces], np.int64)
    add_vp = np.concatenate(faces).astype(np.int32)

    nv, npr = geo.nvertices, geo.nprims
    new_vp = np.concatenate([geo.vertex_point, add_vp]).astype(np.int32)
    new_off = np.concatenate([geo.prim_offset,
                              geo.prim_offset[-1] + np.cumsum(sizes)]).astype(np.int32)
    # Anything with fewer than 3 corners can't be a face; force it to a polyline, or downstream triangulation produces zero-area triangles
    cl = np.broadcast_to(np.asarray(closed, bool).reshape(-1),
                         (len(faces),)).copy()
    cl &= sizes >= 3
    new_closed = np.concatenate([geo.prim_closed, cl])
    new_type = np.concatenate([geo.prim_type,
                               np.full(len(faces), PRIM_POLY, np.uint8)])

    out = Geometry()
    out._resize_points(geo.npoints)
    out.set_topology(new_vp, new_off, new_closed, new_type)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, _pad(v, out.nvertices), owned=True)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, _pad(v, out.nprims), owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, np.concatenate(
            [v, np.zeros(out.nvertices - nv, bool)]))
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, np.concatenate(
            [v, np.zeros(out.nprims - npr, bool)]))
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    out.edge_groups = dict(geo.edge_groups)
    return out


def remove_repeated(geo):
    """Removes corners in a prim that **consecutively** reference the same point (closed prims including the wrap-around)."""
    nv = geo.nvertices
    if nv == 0:
        return geo.copy()
    sizes = geo.prim_sizes()
    starts = np.repeat(geo.prim_offset[:-1], sizes)
    local = np.arange(nv, dtype=np.int64) - starts
    sz = np.repeat(sizes, sizes)
    prv = starts + (local - 1) % np.maximum(sz, 1)
    closed = np.repeat(geo.prim_closed, sizes)
    vp = geo.vertex_point
    kill = (vp == vp[prv]) & (closed | (local > 0)) & (sz > 1)
    if not kill.any():
        return geo.copy()

    keep = ~kill
    new_sizes = np.bincount(geo.vertex_prim()[keep], minlength=geo.nprims)
    out = Geometry()
    out._resize_points(geo.npoints)
    out.set_topology(vp[keep],
                     np.concatenate([[0], np.cumsum(new_sizes)]).astype(np.int32),
                     geo.prim_closed, geo.prim_type)
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        out.set_group(POINT, k, v)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[keep], owned=True)
    for k, v in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, v[keep])
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v)
    for k, v in geo.groups[PRIM].items():
        out.set_group(PRIM, k, v)
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    out.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    out.edge_groups = dict(geo.edge_groups)
    return out


def remove_unused(geo):
    """Deletes isolated points not referenced by any prim."""
    if geo.npoints == 0:
        return geo.copy()
    used = np.zeros(geo.npoints, bool)
    if geo.nvertices:
        used[geo.vertex_point] = True
    return geo.copy() if used.all() else delete_points(geo, used)


# ═══════════════════════════════════════════════════════════════ connection strategies
def _by_group(geo, spec, mode="all_points", n=2):
    """
    Connects a point group into polygons. Matches the "By Group" mode of Houdini's Add SOP.

        all_points   one for the whole group (in point number order)
        groups_of_n  one per n points, cut in sequence
        every_nth    only points 0, n, 2n... connected into one
        each_point   each point on its own (with closed=off this is the inverse of "keep only points")
    """
    idx = np.nonzero(resolve(geo, POINT, spec))[0].tolist()
    if not idx:
        return []
    n = max(1, int(n))
    if mode == "groups_of_n":
        return [idx[i:i + n] for i in range(0, len(idx), n)]
    if mode == "every_nth":
        return [idx[::n]]
    if mode == "each_point":
        return [[i] for i in idx]
    return [idx]


def _by_attribute(geo, name):
    """
    Points with the same value are connected into one polygon each, output sorted by value.

    Typical use: Scatter -> Connectivity/class, or write your own name attribute,
    then string the scattered points into several curves in one step. Houdini calls this "By Attribute".
    """
    name = str(name).strip()
    a = geo.get(POINT, name)
    if a is None:
        have = sorted(geo.attribs[POINT].keys())
        raise KeyError(f"point has no attribute '{name}'. Existing: {have or '(none)'}")
    if a.shape[1] != 1 and not is_string(a):
        raise ValueError(f"Attribute '{name}' has {a.shape[1]} components; connecting only supports scalars or strings")
    key = a[:, 0]
    uniq, inv = np.unique(key, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(inv, kind="stable")     # keep point number order within each value
    counts = np.bincount(inv, minlength=len(uniq))
    off = np.concatenate([[0], np.cumsum(counts)])
    return [order[off[i]:off[i + 1]].tolist() for i in range(len(uniq))]


# ═══════════════════════════════════════════════════════════════ main entry
def add(geo=None, points_text="", keep_points=False,
        use_pattern=False, pattern="", pattern_closed=True,
        use_group=False, group="", group_mode="all_points", group_n=2,
        group_closed=False,
        use_attribute=False, attribute="class", attribute_closed=False,
        do_remove_repeated=False, do_remove_unused=False):
    """
    Execution order = Houdini's order:

        input -> [keep only points] -> [append new points] -> [connect polygons] -> [cleanup]

    New points are appended after the existing ones, so the point numbers of the three connection modes below can refer to both old and
    new points. Without an input it is a pure generator (Houdini's Add also works without an input).
    """
    g = geo.copy() if geo is not None else Geometry()
    if keep_points:
        g = strip_prims(g)

    pts = parse_points(points_text)
    if len(pts):
        # Use merge instead of hand-written appending: the rules (union of attributes, pad missing with 0) are fixed there;
        # a copy here would drift sooner or later
        g = merge(g, Geometry.from_points(pts)) if (g.npoints or g.nprims) \
            else Geometry.from_points(pts)

    faces, closed_flags = [], []
    if use_pattern:
        for lineno, raw in enumerate(str(pattern).splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                f = parse_indices(line, g.npoints)
            except ValueError as e:
                raise ValueError(f"Polygons line {lineno}: {e}") from None
            if f:
                faces.append(f)
                closed_flags.append(bool(pattern_closed))
    if use_group:
        for f in _by_group(g, group, group_mode, group_n):
            faces.append(f)
            closed_flags.append(bool(group_closed))
    if use_attribute:
        for f in _by_attribute(g, attribute):
            faces.append(f)
            closed_flags.append(bool(attribute_closed))

    if faces:
        g = append_prims(g, faces, np.asarray(closed_flags, bool))

    if do_remove_repeated:
        g = remove_repeated(g)
    if do_remove_unused:
        g = remove_unused(g)
    return g
