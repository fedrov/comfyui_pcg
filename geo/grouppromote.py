"""
Group Promote SOP in all directions: point / prim / edge / vertex converted pairwise (pcg100).

Groups are stored two ways in this data model: point / prim / vertex are (n,) boolean masks, edge groups are
(E,2) **point pairs** (see the notes on core.Geometry.edge_groups). So a "selection" here is point pairs for edges
and masks otherwise; convert() sends and receives both ends by this convention.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Rules per direction (the SideFX docs only name the toggles without covering each direction; those marked * are our own choice)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    point  -> prim    any point in the group; only_full = all points in; share_edge = both endpoints of at least
                      one edge in
    point  -> edge    edges with any endpoint in the group; only_full = both endpoints in (docs: Entirely
                      Contained applies to To = Primitives / Edges / Vertices)
    point  -> vertex  vertices referencing these points
    prim   -> point   points used by these primitives
    prim   -> edge    all edges of these primitives
    prim   -> vertex  all vertices of these primitives
    edge   -> point   endpoints
    edge   -> prim    any of its edges in the group; only_full = all of its own edges in
    edge   -> vertex  vertices in their own primitive adjacent to a selected edge (its start or end) *
    vertex -> point   points referenced by these vertices
    vertex -> prim    any vertex in the group (the docs' only_full only mentions point / edge
                      sources, so it doesn't apply here) *
    vertex -> edge    edges whose two adjacent vertices in the same primitive are both in the group *
    prim   -> prim    unchanged (just renamed); only useful with Boundary, see below

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Include Only Elements on the Boundary: implemented only **starting from primitive groups**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The docs say "convert to the output type first, then keep only boundary elements", but what the "boundary" of a point / edge / vertex group
is isn't defined. The boundary of a primitive group is unambiguous -- edges with the group on one side and not the other -- and that is also
the most common use of this toggle in Houdini (primitive group -> outline edges / outline points). Other sources raise an error
instead of guessing.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, EDGE
from .groups import edge_mask, points_to_edges
from .topology import topology

TYPES = (POINT, PRIM, EDGE, VERTEX)


def _prim_any(geo, vmask):
    """(nprims,) number of selected corners in each primitive."""
    return np.bincount(geo.vertex_prim()[vmask], minlength=geo.nprims)


def _pairs(t, emask):
    return np.asarray(t.edge_points[emask], np.int32).reshape(-1, 2)


def _he_selected(geo, t, pairs):
    """(NV,) whether the edge of each half-edge (from this corner to the next corner of the same primitive) is among the point pairs."""
    es = edge_mask(geo, pairs)
    he = np.zeros(geo.nvertices, bool)
    ok = t.he_edge >= 0
    he[ok] = es[t.he_edge[ok]]
    return he


def convert(geo, src, dst, sel, only_full=False, share_edge=False):
    """
    Converts a selection from class src to class dst. sel / return value: (E,2) point pairs for edges, masks otherwise.

    only_full affects point -> prim / point -> edge / edge -> prim; share_edge only affects
    point -> prim (see the module notes); with both on their intersection is taken. In the other directions each target element corresponds to just one
    source element (or the rule itself is "all in"), so the toggle makes no difference.
    """
    if src not in TYPES or dst not in TYPES:
        raise ValueError(f"Group type must be one of {TYPES}")
    if src == dst:
        return sel
    t = topology(geo)
    vp = geo.vertex_point
    nv = geo.nvertices
    vprim = geo.vertex_prim()
    nxt = geo.next_corner() if nv else np.zeros(0, np.int64)
    valid = np.asarray(t.he_valid, bool)

    if src == POINT:
        pm = np.asarray(sel, bool)
        vm = pm[vp]
        if dst == VERTEX:
            return vm
        if dst == EDGE:
            if only_full:
                return points_to_edges(geo, pm)
            # Docs: Entirely Contained also applies to To = Edges; off means "touching one endpoint is enough"
            ep = t.edge_points
            return _pairs(t, pm[ep[:, 0]] | pm[ep[:, 1]]) if t.nedges else \
                np.zeros((0, 2), np.int32)
        cnt = _prim_any(geo, vm)
        out = cnt > 0
        if only_full:
            # An empty prim (0 corners) isn't "all in": it has no points at all
            out &= cnt == geo.prim_sizes()
        if share_edge:
            out &= _prim_any(geo, valid & vm & vm[nxt]) > 0
        return out

    if src == PRIM:
        fm = np.asarray(sel, bool)
        vm = fm[vprim]
        if dst == VERTEX:
            return vm
        if dst == POINT:
            out = np.zeros(geo.npoints, bool)
            out[vp[vm]] = True
            return out
        em = np.zeros(t.nedges, bool)
        em[t.he_edge[valid & vm]] = True
        return _pairs(t, em)

    if src == EDGE:
        pairs = np.asarray(sel, np.int64).reshape(-1, 2)
        if dst == POINT:
            out = np.zeros(geo.npoints, bool)
            out[pairs.reshape(-1)] = True
            return out
        he = _he_selected(geo, t, pairs)
        if dst == VERTEX:
            # The two half-edges adjacent to a vertex: the one starting from it, and the one from the previous corner to it
            out = he.copy()
            out[nxt[he]] = True
            return out
        cnt = _prim_any(geo, he)
        out = cnt > 0
        if only_full:
            out &= cnt == _prim_any(geo, valid)
        return out

    vm = np.asarray(sel, bool)                     # src == VERTEX
    if dst == POINT:
        out = np.zeros(geo.npoints, bool)
        out[vp[vm]] = True
        return out
    if dst == PRIM:
        return _prim_any(geo, vm) > 0
    em = np.zeros(t.nedges, bool)
    em[t.he_edge[valid & vm & vm[nxt]]] = True
    return _pairs(t, em)


def boundary_edges(geo, prim_mask, include_unshared=True,
                   include_curve_unshared=False):
    """
    Outline edges of a primitive group, (nedges,) mask:

        shared edges     a face on one side is in the group, (any) one on the other side isn't
        unshared edges   referenced by only one face, which is in the group -- polygons follow include_unshared,
                         open curves follow include_curve_unshared (two toggles in Houdini)
    """
    t = topology(geo)
    fm = np.asarray(prim_mask, bool)
    if t.nedges == 0:
        return np.zeros(0, bool)
    valid = np.asarray(t.he_valid, bool)
    vprim = geo.vertex_prim()
    n_in = np.bincount(t.he_edge[valid & fm[vprim]], minlength=t.nedges)
    out = (n_in > 0) & (n_in < t.edge_count)
    lone = (t.edge_count == 1) & (n_in == 1)
    if lone.any():
        # Whether the sole owner of this edge is a closed face or an open curve
        closed = np.zeros(t.nedges, bool)
        he = np.nonzero(valid)[0]
        closed[t.he_edge[he]] = geo.prim_closed[vprim[he]]
        if include_unshared:
            out |= lone & closed
        if include_curve_unshared:
            out |= lone & ~closed
    return out


def boundary(geo, dst, prim_mask, include_unshared=True,
             include_curve_unshared=False):
    """Boundary of a primitive group, given in dst class: edges = outline edges, points = endpoints of outline edges, prims = faces in the group
    adjacent to outline edges, vertex = corners of the group's faces at outline points."""
    t = topology(geo)
    fm = np.asarray(prim_mask, bool)
    be = boundary_edges(geo, fm, include_unshared, include_curve_unshared)
    if dst == EDGE:
        return _pairs(t, be)
    bp = np.zeros(geo.npoints, bool)
    if be.any():
        bp[t.edge_points[be].reshape(-1)] = True
    if dst == POINT:
        return bp
    vprim = geo.vertex_prim()
    if dst == VERTEX:
        return fm[vprim] & bp[geo.vertex_point]
    he = np.zeros(geo.nvertices, bool)
    ok = t.he_edge >= 0
    he[ok] = be[t.he_edge[ok]]
    return fm & (_prim_any(geo, he) > 0)


def _resolve(geo, cls, spec):
    from .groups import resolve, resolve_edges
    return resolve_edges(geo, spec) if cls == EDGE else resolve(geo, cls, spec)


def promote(geo, name, src, dst, new_name="", keep_original=True,
            only_full=True, share_edge=False, only_boundary=False,
            include_unshared=True, include_curve_unshared=False,
            as_attribute=False):
    """
    Matches Houdini's Group Promote (one rule).

    The defaults of keep_original / only_full are **this node's long-standing behaviour** (original group kept,
    point -> prim requires all points in); Houdini defaults both to off.
    """
    if geo is None:
        return Geometry()
    name = str(name).strip()
    tgt = str(new_name).strip() or name
    sel = _resolve(geo, src, name)
    if only_boundary:
        if src != PRIM:
            raise ValueError(
                "Include Only Elements on the Boundary currently only supports starting from Primitives "
                "(the SideFX docs don't define the \"boundary\" of point / edge / vertex groups).")
        res = boundary(geo, dst, sel, include_unshared, include_curve_unshared)
    else:
        res = convert(geo, src, dst, sel, only_full, share_edge)

    g = geo.copy()
    if not keep_original:
        # Only **named** groups can be deleted: when Group holds numbers / expressions there is no "original group" to delete
        if src == EDGE:
            g.edge_groups.pop(name, None)
        else:
            g.groups[src].pop(name, None)
    if as_attribute:
        if dst == EDGE:
            raise ValueError("Output as Integer Attribute: this data model has no edge attributes, "
                             "so it can't be written when the target is Edges.")
        g.groups[dst].pop(tgt, None)
        g.set(dst, tgt, np.asarray(res, bool).astype(np.int32)[:, None], owned=True)
    elif dst == EDGE:
        g.set_edge_group(tgt, res)
    else:
        g.set_group(dst, tgt, res)
    return g
