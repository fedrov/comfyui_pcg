"""
Voronoi Fracture -- cuts geometry into pieces by points. Counterpart of Houdini's Voronoi Fracture SOP.

The cornerstone of procedural destruction. Given a set of seed points, each point owns the space "nearest to it" (its Voronoi
cell), and the geometry is cut by these cells into a pile of pieces.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No Voronoi diagram is computed; instead **each cell is cut out by successive clips**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A 3D Voronoi diagram (or its dual, the Delaunay tetrahedralization) is a sizeable project: degeneracies,
four co-spherical points, numerical robustness all need serious handling. But **we do not need the diagram** -- only each piece.

Cell i is defined as "closer to i than to any j", and "closer to i than to j" is a half-space:
the side of the **perpendicular bisector plane** of i-j that faces i. So:

    cell i = original geometry ∩ (half-spaces for all j)

Just cut it plane by plane with the existing Clip. clip_plane already exists, so this comes almost for free --
**rephrasing the problem turns a computational-geometry challenge into a chain of existing operations.**

The cost is repeated work: each of the N seeds has to go over the other N-1. The pruning below brings that back down.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The pruning is exact, not a heuristic
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sort j by distance to i and cut in order. At any step, let R be the distance from i to the farthest point of the current piece.
The bisector plane of seed j is at distance d_ij / 2 from i -- as long as

    d_ij / 2 >= R

that plane cannot reach the piece, and **later j are only farther**, so we can stop right away. This is not "close enough to stop",
it is a strict sufficient condition: the piece lies entirely inside the sphere of radius R, and the plane is outside the sphere.

Measured with 200 seeds cutting a sphere: on average each cell stopped after only 13 planes (instead of 199),
and the worst one used only 35.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hole filling: only fill the holes **created by cutting**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Freshly cut pieces are open; without filling they are a pile of paper sheets, with no volume and no use for rigid bodies. But **not every hole may be filled**:
the input may already be open (e.g. a Grid), and those boundaries must not be sealed.

The criterion is exact, but **timing matters more: fill after every single cut**. The first version cut everything and then filled,
and could not fill a single hole -- after 7 cuts the opening is one long winding loop spanning several cut planes,
so "this loop lies entirely in one plane" is never true. Right after a cut it is different: the new opening always
lies entirely in that cut's plane, so the check always hits. Later cuts slice the fill faces again, which is also correct.

So open inputs stay open after cutting, and closed inputs give closed pieces -- the tests verify volume for both.

Fill faces go into Interior Group, ready for a separate interior material.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .clip import clip_plane
from .ops import merge
from .polyfill import boundary_loops, fill


def _cell_planes(P0, seeds, i, order):
    """Bisector planes used by cell i (normals pointing outward, i.e. away from i). Sorted by distance to i."""
    d = seeds[order] - seeds[i]
    ln = np.linalg.norm(d, axis=1)
    ok = ln > 1e-12
    n = d[ok] / ln[ok][:, None]
    mid = seeds[i] + 0.5 * d[ok]
    return n, mid, ln[ok]


# Cuts that would change nothing (the whole piece strictly on the kept side) are skipped: clip_plane would return the
# piece unchanged and _cap_plane would find no loop in the plane, so the output is bit-identical -- but each such cut
# cost a clip and a topology build. With seeds inside a solid about half the cuts were of this kind.
_SKIP_NOOP = True


def cell(geo, seeds, i, cap=False, cap_mode="ngon", cap_group="",
         tol=1e-5, eps=1e-9, offset=0.0):
    """
    Cut out the i-th Voronoi cell. Returns (piece, list of planes used).

    Planes are used from nearest to farthest from the seed -- the near ones trim the most, so later planes are more likely to be pruned.

    **Holes must be filled after every single cut.** The first version cut everything and then filled, and could not fill a single one:
    after 7 cuts the opening is **one long winding loop** spanning several cut planes, so "this loop lies entirely
    in one plane" is never true. Filling after each cut avoids that -- right after a cut,
    the new opening always lies entirely in that cut's plane. Later cuts slice those fill faces again, which is also correct.
    """
    order = np.argsort(np.linalg.norm(seeds - seeds[i], axis=1))
    n, mid, dist = _cell_planes(None, seeds, i, order)
    if offset:
        # Cut Plane Offset (pcg100 s9): each bisector plane moves toward this cell's seed by offset / 2, leaving
        # an offset-wide gap between two pieces. The plane-to-seed distance becomes d/2 − offset/2, and the pruning condition follows
        mid = mid - n * (0.5 * float(offset))
        dist = dist - float(offset)
    piece = geo
    used = []
    for k in range(len(n)):
        if piece.nprims == 0 or piece.npoints == 0:
            break
        Q = piece.get(POINT, "P").astype(np.float64)
        R = float(np.linalg.norm(Q - seeds[i], axis=1).max())
        if 0.5 * dist[k] >= R - eps:
            break            # strictly sufficient: the piece is inside the sphere of radius R, this plane is outside it
        if _SKIP_NOOP and float(((Q - mid[k]) @ n[k]).max()) < -max(tol, eps):
            continue         # the whole piece is strictly on the kept side: the cut would change nothing (and no cap)
        piece, _ = clip_plane(piece, n[k], mid[k], keep="below")
        used.append((n[k], mid[k]))
        if cap and piece.nprims:
            piece = _cap_plane(piece, n[k], mid[k], cap_mode, cap_group, tol)
    return piece, used


def _cap_plane(piece, n, o, mode, group_name, tol):
    """Only fill boundary loops that lie **entirely in this cut's plane**. The input's original openings are left alone."""
    loops = boundary_loops(piece)
    if not loops:
        return piece
    P = piece.get(POINT, "P").astype(np.float64)
    on = [lp for lp in loops
          if np.abs((P[np.asarray(lp, np.int64)] - o) @ n).max() <= tol]
    if not on:
        return piece
    old = piece.nprims
    out = fill(piece, mode, loops=on)
    if group_name:
        prev = piece.get_group(PRIM, group_name)
        m = np.zeros(out.nprims, bool)
        if prev is not None:
            m[:old] = prev
        m[old:] = True
        out.set_group(PRIM, group_name, m)
    return out


NAME_MODES = ("overwrite", "append")
EXTERIOR_NORMALS = ("preserve", "recompute", "none")
PARTITIONS = ("none", "overwrite", "maintain")
_DEFAULT_OPTS = dict(group="", name_mode="overwrite", namespace="", cell_point_attrib="",
                     clip_piece_attrib="", exterior_group="", merge_groups=True,
                     partition="none", plane_offset=0.0, interior_normals=False,
                     interior_cusp=40.0, exterior_normals="preserve", exterior_cusp=60.0,
                     copy_attribs="", copy_to_points=True, copy_to_prims=False)


def fracture(geo, points, cap=True, cap_mode="ngon",
             interior_group="interior", name_attrib="name",
             piece_attrib="piece", name_prefix="piece", cap_tol=1e-5,
             max_pieces=4096, opts=None):
    """
    Cut geometry into Voronoi pieces by points. points supplies the seeds via its P.

    The output is all pieces merged together, distinguished by the name / piece attributes -- connect
    For-Each Begin in piece mode to process them one by one.

    opts (pcg100 s9, keys in _DEFAULT_OPTS; None / defaults = the pre-change behaviour): Group,
    Name Attribute (Overwrite / Append + Fracture Namespace), Primitive Cell Point,
    Primitive Clip Piece, Exterior Group, Merge with Existing Groups, Connectivity
    Partition, Cut Plane Offset, Interior / Exterior Normals, Copy Cell Point Attributes.
    All post-processing is in _post(), applied to the whole merged geometry.
    """
    o = dict(_DEFAULT_OPTS, **(opts or {}))
    for k, allowed in (("name_mode", NAME_MODES), ("exterior_normals", EXTERIOR_NORMALS),
                       ("partition", PARTITIONS)):
        if o[k] not in allowed:
            raise ValueError(f"{k} must be one of {allowed}")
    if geo is None:
        return Geometry()
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    if o != _DEFAULT_OPTS:
        return _fracture_ex(geo, points, cap, cap_mode, interior_group, name_attrib,
                            piece_attrib, name_prefix, cap_tol, max_pieces, o)
    if points is None or points.npoints == 0:
        raise ValueError("Voronoi Fracture needs seed points on the second input -- "
                         "connect a Scatter (PCG) or Point Jitter.")
    seeds = points.get(POINT, "P")
    if seeds is None:
        raise KeyError("The seed geometry has no P attribute.")
    seeds = np.unique(seeds.astype(np.float64), axis=0)
    if len(seeds) > int(max_pieces):
        raise ValueError(
            f"There are {len(seeds)} seeds, exceeding the limit {max_pieces} -- every seed has to cut "
            f"the whole geometry, which takes very long at this scale. Scatter fewer points first.")
    if len(seeds) == 1:
        return _tag(geo.copy(), 0, name_attrib, piece_attrib, name_prefix)

    mn, mx = geo.bbox()
    scale = max(float(np.max(np.asarray(mx, np.float64)
                             - np.asarray(mn, np.float64))), 1.0)
    tol = float(cap_tol) * scale

    pieces = []
    for i in range(len(seeds)):
        p, _ = cell(geo, seeds, i, cap, cap_mode,
                    str(interior_group).strip(), tol)
        if p.nprims == 0 or p.npoints == 0:
            continue                       # seed is outside the geometry, the cell is empty
        pieces.append(_tag(p, len(pieces), name_attrib, piece_attrib,
                           name_prefix))
    if not pieces:
        return Geometry()
    return merge(*pieces)


def _tag(g, i, name_attrib, piece_attrib, prefix):
    """Tag a piece with name / piece."""
    n = g.nprims
    if str(name_attrib).strip() and n:
        g.set_string(PRIM, str(name_attrib).strip(),
                     np.full(n, f"{prefix}{i}"))
    if str(piece_attrib).strip() and n:
        g.set(PRIM, str(piece_attrib).strip(),
              np.full((n, 1), i, np.int32), owned=True)
    return g


# ═══════════════════════════════════════════════════════════ pcg100 s9 options
def _fracture_ex(geo, points, cap, cap_mode, interior_group, name_attrib, piece_attrib,
                 name_prefix, cap_tol, max_pieces, o):
    """
    The code path with the Houdini options. It is written separately from the default path so that output with default values does not change by a single bit
    (the default path adds no temporary attributes).

    Approach: before cutting, tag every input face with two temporary prim attributes -- __vf_orig = 1 (original faces;
    faces created by hole filling get 0) and __vf_src (original face number); every piece gets __vf_cell = seed number. After merging
    everything is computed from these columns: interior faces = __vf_orig == 0, exterior faces = 1; piece numbers, names,
    Clip Piece and Partition all come from __vf_cell.
    """
    from .groups import resolve
    from .ops import delete_prims
    if points is None or points.npoints == 0:
        raise ValueError("Voronoi Fracture needs seed points on the second input -- "
                         "connect a Scatter (PCG) or Point Jitter.")
    raw = points.get(POINT, "P")
    if raw is None:
        raise KeyError("The seed geometry has no P attribute.")
    # Dedup and sort as in the default path (piece numbering rules unchanged); sidx records each seed's point number in the input
    seeds, sidx = np.unique(raw.astype(np.float64), axis=0, return_index=True)
    if len(seeds) > int(max_pieces):
        raise ValueError(f"There are {len(seeds)} seeds, exceeding the limit {max_pieces}.")

    src = geo.copy()
    ig = str(interior_group).strip()
    gmask = resolve(src, PRIM, o["group"])
    src.set(PRIM, "__vf_orig", np.ones((src.nprims, 1), np.int32), owned=True)
    src.set(PRIM, "__vf_src", np.arange(src.nprims, dtype=np.int32)[:, None], owned=True)
    rest = None
    if not gmask.all():
        # Group: only cut faces in the group; faces outside the group are appended as they are (tagged with nothing beyond name / piece)
        rest = delete_prims(src, ~gmask)
        src = delete_prims(src, gmask)

    mn, mx = src.bbox()
    scale = max(float(np.max(np.asarray(mx, np.float64) - np.asarray(mn, np.float64))), 1.0)
    tol = float(cap_tol) * scale
    pieces = []
    for i in range(len(seeds)):
        if src.nprims == 0:
            break
        # With a single seed cell() makes no cut and returns the input unchanged (no special case needed as in the default path)
        p, _ = cell(src, seeds, i, cap, cap_mode, ig, tol, offset=float(o["plane_offset"]))
        if p.nprims == 0 or p.npoints == 0:
            continue
        p.set(PRIM, "__vf_cell", np.full((p.nprims, 1), i, np.int32), owned=True)
        pieces.append(p)
    out = merge(*pieces) if pieces else Geometry()
    return _post(out, rest, seeds, sidx, points, ig, name_attrib, piece_attrib,
                 name_prefix, o)


def _post(g, rest, seeds, sidx, points, ig, name_attrib, piece_attrib, prefix, o):
    n = g.nprims
    cellid = (g.get(PRIM, "__vf_cell")[:, 0].astype(np.int64) if n else np.zeros(0, np.int64))
    orig = (g.get(PRIM, "__vf_orig")[:, 0] == 1) if n else np.zeros(0, bool)
    interior = ~orig                                  # faces created by this round's hole filling

    # -- piece number: default = non-empty cells in seed order 0, 1, 2 ... (same as the default path)
    used = np.unique(cellid)
    cell2piece = -np.ones(len(seeds), np.int64)
    cell2piece[used] = np.arange(len(used))
    piece = cell2piece[cellid]
    if o["partition"] != "none" and n:
        piece = _partition(g, piece, o["partition"])

    # -- Clip Piece: an interior face's centroid lies on the bisector plane between its piece and a neighbour, and the other seed nearest to it is
    #    the neighbour that cut this face. The neighbour's piece number: after Partition, use the face nearest to the centroid in the neighbour cell
    clip = None
    if str(o["clip_piece_attrib"]).strip() and n:
        clip = -np.ones(n, np.int64)
        ii = np.nonzero(interior)[0]
        if len(ii):
            C = _prim_centroids(g, ii)
            d = np.linalg.norm(C[:, None, :] - seeds[None, :, :], axis=2)
            d[np.arange(len(ii)), cellid[ii]] = np.inf
            nb = np.argmin(d, axis=1)
            for k, (pi, cj) in enumerate(zip(ii, nb)):
                # the neighbour side was also filled (both sides of a cut get filled); find the nearest-to-centroid face among its fill faces
                cand = np.nonzero((cellid == cj) & interior)[0]
                if len(cand):
                    Cc = _prim_centroids(g, cand)
                    clip[pi] = piece[cand[np.argmin(np.linalg.norm(Cc - C[k], axis=1))]]

    # -- write attributes
    if str(name_attrib).strip() and n:
        nm = str(name_attrib).strip()
        new = [f"{prefix}{int(k)}" for k in piece]
        old = g.get(PRIM, nm)
        if o["name_mode"] == "append":
            # Append: original name + "-" + Fracture Namespace + Piece Prefix + number
            # (the docs do not give the separator, "-" was chosen; faces without a name attribute / with an empty name = Namespace + prefix + number)
            ov = ([str(v) for v in old.reshape(-1)] if old is not None and is_string(old)
                  else [""] * n)
            # Fill faces are new and have an empty name -- they borrow the name of the original piece they belong to (the first named
            # face in the same cell; in multi-level fracturing a cell only falls in one original piece, unless the originals touch each other)
            for c in np.unique(cellid):
                ids = np.nonzero(cellid == c)[0]
                named = [ov[i] for i in ids if ov[i]]
                if named:
                    for i in ids:
                        if not ov[i]:
                            ov[i] = named[0]
            new = [f"{a}-{o['namespace']}{b}" if a else f"{o['namespace']}{b}"
                   for a, b in zip(ov, new)]
        new = np.array(new)                            # fixed-length unicode, same dtype as the default path
        g.set_string(PRIM, nm, new)
    if str(piece_attrib).strip() and n:
        g.set(PRIM, str(piece_attrib).strip(), piece.astype(np.int32)[:, None], owned=True)
    if str(o["cell_point_attrib"]).strip() and n:
        g.set(PRIM, str(o["cell_point_attrib"]).strip(),
              np.asarray(sidx)[cellid].astype(np.int32)[:, None], owned=True)
    if clip is not None:
        g.set(PRIM, str(o["clip_piece_attrib"]).strip(), clip.astype(np.int32)[:, None], owned=True)
    if ig and n and not o["merge_groups"]:
        g.set_group(PRIM, ig, interior)               # Merge off: drop the old interior group, keep only this round's fill faces
    eg = str(o["exterior_group"]).strip()
    if eg and n:
        prev = g.get_group(PRIM, eg)
        if o["merge_groups"] and prev is not None:
            g.set_group(PRIM, eg, np.asarray(prev, bool))     # existing exterior group kept as is
        else:
            g.set_group(PRIM, eg, orig)
    if str(o["copy_attribs"]).strip() and n:
        _copy_cell_attribs(g, points, np.asarray(sidx)[cellid], o)
    if n and (o["interior_normals"] or o["exterior_normals"] != "preserve"):
        g = _normals(g, interior, o)

    for k in ("__vf_cell", "__vf_orig", "__vf_src"):
        if g.get(PRIM, k) is not None:
            g.remove(PRIM, k)
    if rest is not None and rest.nprims:
        for k in ("__vf_orig", "__vf_src"):
            rest.remove(PRIM, k)
        if str(piece_attrib).strip():
            rest.set(PRIM, str(piece_attrib).strip(), np.full((rest.nprims, 1), -1, np.int32),
                     owned=True)
        g = merge(g, rest) if n else rest
    return g


def _prim_centroids(g, ids):
    P = g.get(POINT, "P").astype(np.float64)
    return np.array([P[g.prim_points(int(i))].mean(0) for i in ids])


def _partition(g, piece, mode):
    """
    Connectivity Partition. Disconnected parts of a piece (common when cutting concave objects) become separate pieces:
      overwrite  renumber everything 0, 1, 2 ... in (original piece, connected piece) order (fast, but numbers no longer match seeds)
      maintain   the largest connected part of each piece keeps the original number, the rest are numbered after the highest number
    The docs only say maintain "keeps numbering consistent with the input points", not which part keeps the number; the one with most faces keeps it.
    """
    from .topology import connectivity
    c = connectivity(g, cls="prim", name="__vf_cc")
    cc = c.get(PRIM, "__vf_cc")[:, 0].astype(np.int64)
    out = piece.copy()
    if mode == "overwrite":
        keys = sorted({(int(p), int(k)) for p, k in zip(piece, cc)},
                      key=lambda t: (t[0], int(np.nonzero(cc == t[1])[0].min())))
        lut = {kk: j for j, kk in enumerate(keys)}
        return np.array([lut[(int(p), int(k))] for p, k in zip(piece, cc)], np.int64)
    nxt = int(piece.max()) + 1
    for p in np.unique(piece):
        m = piece == p
        comps, cnt = np.unique(cc[m], return_counts=True)
        if len(comps) <= 1:
            continue
        keep = comps[np.argmax(cnt)]
        for k in comps:
            if k == keep:
                continue
            out[m & (cc == k)] = nxt
            nxt += 1
    return out


def _copy_cell_attribs(g, points, src_pt, o):
    """Copy Cell Point Attributes: copy attributes from seed points (by name, wildcards allowed) onto the pieces' faces / points."""
    from .ops import match_names
    avail = [k for k in points.attribs[POINT] if k != "P"]
    names = match_names(avail, str(o["copy_attribs"]))
    if not names:
        return
    vp = g.vertex_prim()
    VP_ = np.asarray(g.vertex_point)
    pt_prim = np.zeros(g.npoints, np.int64)
    pt_prim[VP_] = vp                                  # pieces share no points, any one face will do
    for k in names:
        v = points.attribs[POINT][k]
        if o["copy_to_prims"]:
            if v.dtype.kind == "O":
                g.set_string(PRIM, k, v.reshape(-1)[src_pt])
            else:
                g.set(PRIM, k, np.asarray(v)[src_pt], owned=True)
        if o["copy_to_points"]:
            idx = src_pt[pt_prim]
            if v.dtype.kind == "O":
                g.set_string(POINT, k, v.reshape(-1)[idx])
            else:
                g.set(POINT, k, np.asarray(v)[idx], owned=True)


def _normals(g, interior, o):
    """
    Compute Interior Normals / Exterior Normals, writing vertex normals N.
      Interior face vertices: computed with Interior Cusp Angle (over the whole geometry; the angle between interior and exterior faces is usually
                    larger than the cusp, so it is a hard edge)
      Exterior face vertices: preserve  use the input N if present (point N promoted to vertices); if absent and interior normals are on,
                               compute with Exterior Cusp Angle
                    recompute always recompute with Exterior Cusp Angle
                    none      not computed; but with interior normals on, exterior gets smooth normals (cusp 180°, as the docs say)
    With interior normals off and exterior recompute, interior face vertices also use the exterior cusp (N is a vertex attribute,
    it cannot be written for only half; not specified by the docs).
    """
    from .ops import compute_normals
    vp = g.vertex_prim()
    vin = interior[vp]
    had_v = g.get(VERTEX, "N")
    had_p = g.get(POINT, "N")
    ext_mode = o["exterior_normals"]
    if not o["interior_normals"] and ext_mode == "none":
        return g

    def vn(cusp):
        return compute_normals(g, "vertex", float(cusp)).get(VERTEX, "N").astype(np.float32)

    N = np.zeros((g.nvertices, 3), np.float32)
    if ext_mode == "recompute":
        N[:] = vn(o["exterior_cusp"])
    elif ext_mode == "none":
        N[:] = vn(180.0)
    else:
        if had_v is not None:
            N[:] = had_v
        elif had_p is not None:
            N[:] = had_p[np.asarray(g.vertex_point)]
        else:
            N[:] = vn(o["exterior_cusp"])
    if o["interior_normals"]:
        N[vin] = vn(o["interior_cusp"])[vin]
    out = g.copy()
    if had_p is not None:
        out.remove(POINT, "N")                      # with point N and vertex N both present, shading only uses the vertex one
    out.set(VERTEX, "N", N, owned=True)
    return out
