"""
Mesh repair (pcg68, the four of SOP gap batch D other than Remesh): Clean, Edge Collapse,
Point Split, UV Fuse.

All four are "topology cleanup": they don't change the shape (except Edge Collapse, whose job is to collapse), only how points and primitives
connect. Splitting / merging points goes through the two existing tools in facet.py -- _split_points (rebuild the point set
by corner classes) and _weld (merge points by key) -- so the rules for carrying attributes, groups and edge groups are exactly those of
Facet.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string
from .groups import resolve, resolve_edges
from .ops import delete_prims, prim_normals
from .topology import topology
from . import facet as _fc

UVFUSE_MODES = ("shared_points", "distance")


def _uf(n, pairs):
    """Union-find -> (class id per element, number of classes). Class ids in order of first occurrence."""
    inv, k = _fc._labels(n, np.asarray(pairs, np.int64).reshape(-1, 2))
    return inv, k


# ═══════════════════════════════════════════════════════════ Clean
def _dup_prims(geo):
    """Prims with identical point sets (closed faces regardless of start point and winding, polylines regardless of direction): only the first is kept."""
    keys = []
    for i in range(geo.nprims):
        p = geo.prim_points(i).tolist()
        if geo.prim_closed[i]:
            k = min(len(p), len(p))
            rots = [tuple(p[j:] + p[:j]) for j in range(len(p))]
            rp = p[::-1]
            rots += [tuple(rp[j:] + rp[:j]) for j in range(len(rp))]
            keys.append(("c", min(rots)))
        else:
            keys.append(("o", min(tuple(p), tuple(p[::-1]))))
    seen = {}
    keep = np.ones(geo.nprims, bool)
    for i, k in enumerate(keys):
        if k in seen:
            keep[i] = False
        else:
            seen[k] = i
    return keep


def _nonmanifold_edges(geo):
    """Edges shared by more than two faces: keep the two largest by area, delete the remaining faces."""
    t = topology(geo)
    if not t.nedges:
        return np.ones(geo.nprims, bool), 0
    vprim = geo.vertex_prim()
    area = np.linalg.norm(prim_normals(geo, normalize=False), axis=1)
    keep = np.ones(geo.nprims, bool)
    bad = np.nonzero(t.edge_count > 2)[0]
    for e in bad:
        fs = np.unique(vprim[t.he_of_edge(e)])
        fs = fs[keep[fs]]
        if len(fs) > 2:
            order = fs[np.argsort(-area[fs], kind="stable")]
            keep[order[2:]] = False
    return keep, int((~keep).sum())


def _split_bowties(geo):
    """
    Splits non-manifold points (bowties: one point with two fans of faces that aren't connected) into one point per fan.

    Two corners of the same point belong to the same fan if their faces share a manifold edge **through this point**.
    For every edge a->b (face 1) / b->a (face 2) with exactly two faces: the two corners at a
    are h1 and next(h2), at b they are next(h1) and h2 -- union them. After the unions, the number of classes of corners at
    each point is its number of fans; points with more than one fan are split.
    """
    t = topology(geo)
    nv = geo.nvertices
    if not nv or not t.nedges:
        return geo.copy(), 0
    nxt = geo.next_corner()
    two = np.nonzero(t.edge_count == 2)[0]
    h1 = t.edge_he[t.edge_he_off[two]]
    h2 = t.edge_he[t.edge_he_off[two] + 1]
    vp = geo.vertex_point
    # h2 must run opposite to h1 (consistent orientation); same-direction ones (inconsistent orientation) are also paired at the same point
    same_start = vp[h1] == vp[h2]
    pa = np.where(same_start, h2, nxt[h2])
    pb = np.where(same_start, nxt[h2], h2)
    pairs = np.concatenate([np.stack([h1, pa], 1), np.stack([nxt[h1], pb], 1)])
    cls, k = _uf(nv, pairs)
    # Number of classes per point
    nclass = np.zeros(geo.npoints, np.int64)
    uniq = np.unique(np.stack([vp, cls], 1), axis=0)
    np.add.at(nclass, uniq[:, 0], 1)
    split = int((nclass > 1).sum())
    if not split:
        return geo.copy(), 0
    return _fc._split_points(geo, cls, k), split


def clean(geo, group="", fuse_distance=0.0, remove_degenerate=True,
          remove_duplicates=True, make_manifold=False, orient=False,
          remove_unused=True, min_piece_prims=0):
    """
    Matches Houdini's Clean (and the repair half of PolyDoctor). In fixed order:

      1 fuse_distance > 0   points within the distance merged into one (Facet's consolidate)
      2 remove_degenerate   adjacent duplicate corners, prims that can't span a face, zero-area faces
      3 remove_duplicates   prims with identical point sets keep only one (regardless of start point and winding)
      4 make_manifold       edges shared by more than two faces: keep the two largest; split bowtie points
      5 orient              consistent orientation (Facet's orient)
      6 min_piece_prims     connected pieces with fewer faces than this are deleted entirely (debris)
      7 remove_unused       points not referenced by any prim are deleted
    Returns (geometry, report: how much each step changed).
    """
    g = geo.copy()
    rep = {}
    n0, p0 = g.npoints, g.nprims
    if float(fuse_distance) > 0:
        g = _fc.consolidate_points(g, float(fuse_distance))
        rep["fused_points"] = n0 - g.npoints
    if remove_degenerate and g.nprims:
        before = g.nprims
        g = _fc.remove_degenerate(g, 1e-12)
        rep["degenerate_prims"] = before - g.nprims
    if remove_duplicates and g.nprims:
        keep = _dup_prims(g)
        rep["duplicate_prims"] = int((~keep).sum())
        if not keep.all():
            g = delete_prims(g, keep, keep_points=True)
    if make_manifold and g.nprims:
        keep, rm = _nonmanifold_edges(g)
        rep["nonmanifold_faces_removed"] = rm
        if rm:
            g = delete_prims(g, keep, keep_points=True)
        g, sp = _split_bowties(g)
        rep["bowtie_points_split"] = sp
    if orient and g.nprims:
        g = _fc.orient_polygons(g)
    if int(min_piece_prims) > 0 and g.nprims:
        from .topology import connectivity
        c = connectivity(g, PRIM, "__piece__")
        pid = np.asarray(c.get(PRIM, "__piece__"))[:, 0].astype(np.int64)
        cnt = np.bincount(pid)
        keep = cnt[pid] >= int(min_piece_prims)
        rep["small_piece_prims"] = int((~keep).sum())
        if not keep.all():
            g = delete_prims(g, keep, keep_points=True)
    if remove_unused and g.nvertices:
        used = np.zeros(g.npoints, bool)
        used[g.vertex_point] = True
        rep["unused_points"] = int((~used).sum())
        if not used.all():
            g = delete_prims(g, np.ones(g.nprims, bool), keep_points=False)
    rep["points"] = [n0, g.npoints]
    rep["prims"] = [p0, g.nprims]
    return g, rep


# ═══════════════════════════════════════════════════════════ Edge Collapse
def edge_collapse(geo, edges="", remove_degenerate=True):
    """
    Matches Houdini's Edge Collapse: each chain formed by the edges of the edge group collapses into one point, placed at
    the centre of that chain's points. Afterwards adjacent duplicate corners are removed and faces that can no longer stand are deleted.
    An empty edge group is an error (collapsing all edges gives a single point, never what is wanted). Returns (geometry, report).
    """
    spec = str(edges).strip()
    if not spec:
        raise ValueError("Edges is empty -- enter an edge group name (Group Edges / Group "
                         "Find Path can create one)")
    pairs = resolve_edges(geo, spec)
    if not len(pairs):
        return geo.copy(), {"collapsed_chains": 0}
    n = geo.npoints
    lab, k = _uf(n, pairs)
    size = np.bincount(lab, minlength=k)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    C = np.stack([np.bincount(lab, weights=P[:, c], minlength=k)
                  for c in range(3)], 1) / size[:, None]
    g = _fc._weld(geo, lab[:, None])
    # Order of _weld's new points = order of each class's representative point (lowest original number)
    _, first = np.unique(lab, return_index=True)
    order = np.argsort(first)
    newP = C[order]
    g.set(POINT, "P", newP.astype(np.float32), owned=True)
    if remove_degenerate:
        g = _fc.remove_degenerate(g, 1e-12)
    return g, {"collapsed_chains": int((size > 1).sum()),
               "points_removed": int(n - k)}


# ═══════════════════════════════════════════════════════════ Point Split
def point_split(geo, attribute="", tolerance=1e-5, group="", promote=True):
    """
    Matches Houdini's Point Split: if the vertices on a point have different vertex attribute
    values (the two sides of a uv seam, N on the two sides of a hard edge), the point is split into several, one per value.

    Empty attribute = split everything (one point per corner, Facet's unique points).
    Corners on the same point are sorted by attribute value, and neighbours differing by no more than tolerance are in the same class
    (chained), rather than bucketed by rounding to tolerance -- bucketing would put 0.49999 and 0.50001 on different sides.
    Points outside group aren't split. promote: after splitting, the vertex attribute is also written as a point attribute of the same name
    (each point now has a single value). Returns (geometry, report).
    """
    nv = geo.nvertices
    if not nv:
        return geo.copy(), {"split_points": 0}
    vp = geo.vertex_point.astype(np.int64)
    sel = resolve(geo, POINT, group)
    name = str(attribute).strip()
    if not name:
        key = np.arange(nv)
        cls = np.where(sel[vp], key, -1 - vp)
        _, cls = np.unique(cls, return_inverse=True)
        cls = cls.reshape(-1)
        k = int(cls.max()) + 1
    else:
        a = geo.get(VERTEX, name)
        if a is None or is_string(a):
            raise KeyError(f"vertex has no numeric attribute '{name}'")
        A = np.asarray(a, np.float64)
        order = np.lexsort(tuple(A[:, c] for c in range(A.shape[1] - 1, -1, -1))
                           + (vp,))
        vs, As = vp[order], A[order]
        new = np.ones(nv, bool)
        if nv > 1:
            same_pt = vs[1:] == vs[:-1]
            close = np.abs(As[1:] - As[:-1]).max(1) <= float(tolerance)
            new[1:] = ~(same_pt & (close | ~sel[vs[1:]]))
        grp = np.cumsum(new) - 1
        cls = np.empty(nv, np.int64)
        cls[order] = grp
        k = int(grp[-1]) + 1
    before = geo.npoints
    g = _fc._split_points(geo, cls, k)
    if name and promote:
        a = np.asarray(geo.get(VERTEX, name))
        pv = np.zeros((g.npoints, a.shape[1]), a.dtype)
        pv[g.vertex_point] = a
        g.set(POINT, name, pv, owned=True)
    return g, {"split_points": int(g.npoints - before)}


# ═══════════════════════════════════════════════════════════ UV Fuse
def uv_fuse(geo, uv="uv", mode="shared_points", distance=1e-3, group=""):
    """
    Matches Houdini's UV Fuse: vertices close together in uv space are welded (averaged).

      shared_points  only welds vertices on **the same geometry point** (tiny seam errors left by projection / unwrapping;
                     the two sides of a real seam are far apart and won't be welded)
      distance       welds everything within distance in uv space (whether or not on the same point) --
                     stitches the touching edges of two uv islands
    group is a prim group: only vertices on these primitives move. Returns (geometry, report: how many groups were welded).
    """
    if mode not in UVFUSE_MODES:
        raise ValueError(f"Mode must be one of {UVFUSE_MODES}")
    name = str(uv).strip() or "uv"
    a = geo.get(VERTEX, name)
    if a is None or is_string(a):
        raise KeyError(f"vertex has no uv attribute '{name}'")
    A = np.asarray(a, np.float64)
    nv = geo.nvertices
    selp = resolve(geo, PRIM, group)
    selv = np.repeat(selp, geo.prim_sizes())
    idx = np.nonzero(selv)[0]
    d = float(distance)
    Q = np.zeros((len(idx), 3))
    Q[:, :2] = A[idx, :2]
    from .spatial import neighbors_within
    qi, pi, _ = neighbors_within(Q, Q, d) if d > 0 else (
        np.zeros(0, np.int64), np.zeros(0, np.int64), None)
    m = qi < pi
    qi, pi = idx[qi[m]], idx[pi[m]]
    if mode == "shared_points":
        vp = geo.vertex_point
        same = vp[qi] == vp[pi]
        qi, pi = qi[same], pi[same]
    lab, k = _uf(nv, np.stack([qi, pi], 1))
    size = np.bincount(lab, minlength=k)
    mean = np.stack([np.bincount(lab, weights=A[:, c], minlength=k)
                     for c in range(A.shape[1])], 1) / size[:, None]
    B = np.where((size[lab] > 1)[:, None], mean[lab], A)
    out = geo.copy()
    out.set(VERTEX, name, B.astype(a.dtype), owned=True)
    return out, {"fused_groups": int((size > 1).sum()),
                 "vertices_moved": int((np.abs(B - A).max(1) > 0).sum())}
