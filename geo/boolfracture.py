"""
Boolean Fracture -- cuts a solid into fragments with cutting geometry. Matches Houdini's Boolean Fracture SOP
(added in pcg100 s9; this entry used to point at Boolean's shatter mode, but shatter outputs the three pieces A∩B / A−B / B−A
without the piece naming, inside/outside groups, normals and so on of Boolean Fracture).

━━ How it cuts
The backend is manifold3d, same as Boolean (requires closed manifolds).
  - Treat Cutting Geometry As = Solid: the cutting geometry is a closed solid. Fragments = A∩B and A−B.
  - Treat Cutting Geometry As = Surface: the cutting geometry is an open surface (typically a Grid with noise).
    manifold doesn't accept open surfaces, so **each connected cutting surface** is extruded far along the opposite of its average normal
    (2x the overall bounding box diagonal), forming a "half-space solid topped by this surface" S; fragments = A∩S and A−S.
    The cut lies exactly on the original cutting surface, without the offset a thin shell would have. Costs (differing from Houdini):
      - the cutting surface must **pass through the whole object** and be a height field along its average normal (no folding back); a surface that only cuts
        halfway in just makes a slit in Houdini, whereas here the side walls of the extruded solid cut the object apart
    Several cutting surfaces cut one at a time, each cutting every current fragment once.
Finally every result is split by connectivity; each connected piece is one fragment.

━━ Source tracking
The triangles' face_id encodes the source: faces of A = original prim number, faces of the cutting geometry = _CUT + original prim number
(manifold carries face_id through booleans unchanged; as_original() must not be called, it resets face_id to coplanar groupings).
With sources known: exterior faces = from A, interior faces = from the cutting geometry; A's prim attributes and prim groups are copied back by source,
and the cutting geometry's prim attributes are copied onto interior faces per Copy Cutting Surface Attributes.
**Point / vertex attributes are not carried** (manifold only provides positions), same as the Boolean node.

━━ Detriangulate
  all        source prims that weren't cut (same triangle count, all original corners present) are restored to the original polygons; cut ones
             are merged pairwise by source into quads (like Boolean's detriangulate, a single pairing pass)
  unchanged  only uncut ones are restored; cut ones stay triangles (the docs' wording)
  none       all triangles
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_POLY, is_string
from . import ops as _ops

TREAT = ("surface", "solid")
DETRI = ("all", "unchanged", "none")
_CUT = 1 << 30


def _tris_with_prim(geo):
    """Fan triangulation, also giving which prim each triangle comes from (same subdivision as Geometry.triangles)."""
    sizes = geo.prim_sizes()
    keep = geo.prim_closed & (sizes >= 3) & (geo.prim_type == PRIM_POLY)
    tri, src = [], []
    for k in np.unique(sizes[keep]):
        sel = np.nonzero(keep & (sizes == k))[0]
        corner = geo.prim_offset[sel][:, None] + np.arange(k)[None, :]
        idx = geo.vertex_point[corner]
        for t in range(1, k - 1):
            tri.append(np.stack([idx[:, 0], idx[:, t], idx[:, t + 1]], 1))
            src.append(sel)
    if not tri:
        return np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    return np.concatenate(tri).astype(np.int64), np.concatenate(src).astype(np.int64)


def _manifold(P, T, fid, name):
    from .boolean import _m3
    m3 = _m3()
    man = m3.Manifold(m3.Mesh(np.array(P, np.float32, order="C"),
                              np.array(T, np.uint32, order="C"),
                              face_id=np.array(fid, np.uint32, order="C")))
    st = str(man.status())
    if "NoError" not in st:
        raise RuntimeError(f"{name} is not a closed manifold mesh ({st}); booleans need closed solids. "
                           "Put a Fuse first to weld coincident points, and check for holes / inconsistent normal orientation.")
    return man


def _halfspace(cut, ids, D):
    """
    An open cutting surface (prim numbers ids) -> a closed solid topped by it, extruded a distance D opposite its average normal.
    Top = the original surface (facing +n̄), bottom = translated by −D·n̄ and flipped, plus one side quad per boundary edge.
    face_id: top = _CUT + original prim number; bottom and sides = _CUT − 1 (they only occur far away, never at the cut).
    """
    sub = _ops.delete_prims(cut, np.isin(np.arange(cut.nprims), ids))
    T, src = _tris_with_prim(sub)
    P = sub.get(POINT, "P").astype(np.float64)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    fn = np.cross(b - a, c - a)
    nbar = fn.sum(0)
    ln = np.linalg.norm(nbar)
    if ln < 1e-12:
        raise ValueError("The average normal of the cutting surface is zero (a closed surface, or opposing faces cancelling out) -- use Solid for closed solids")
    nbar /= ln
    n = len(P)
    P2 = np.concatenate([P, P - D * nbar])
    # Boundary edges: used by only one triangle, in that triangle's direction
    E = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    key = np.sort(E, 1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    bnd = E[cnt[inv.reshape(-1)] == 1]
    side = np.concatenate([np.stack([bnd[:, 1], bnd[:, 0], bnd[:, 0] + n], 1),
                           np.stack([bnd[:, 1], bnd[:, 0] + n, bnd[:, 1] + n], 1)])
    TT = np.concatenate([T, T[:, ::-1] + n, side])
    orig_ids = np.asarray(ids)[src]                   # sub's prim number -> cut's prim number
    fid = np.concatenate([_CUT + orig_ids, np.full(len(T) + len(side), _CUT - 1)])
    return _manifold(P2, TT, fid, "Extruded cutting surface")


def _to_geo(man):
    mesh = man.to_mesh()
    v = np.asarray(mesh.vert_properties, np.float32)
    t = np.asarray(mesh.tri_verts, np.int64)
    if not len(t):
        return None, None
    return Geometry.from_mesh(v[:, :3], t), np.asarray(mesh.face_id, np.int64)


def _weld_exact(g):
    """Merges points at **exactly the same** position (all from the same manifold mesh, so coordinates are bit-identical)."""
    P = g.get(POINT, "P")
    _, first, inv = np.unique(P, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(first)
    remap = np.empty(len(first), np.int64)
    remap[order] = np.arange(len(first))
    vp = remap[inv][np.asarray(g.vertex_point)]
    sizes = g.prim_sizes()
    polys = np.split(vp, np.cumsum(sizes)[:-1])
    return Geometry.from_mesh(P[first[order]], [list(x) for x in polys])


def _restore(g, fid, geo_a, mode):
    """Detriangulate (see the module notes). g is one fragment's triangle mesh, fid the source of each triangle."""
    if mode == "none" or g.nprims == 0:
        return g, fid
    PA = geo_a.get(POINT, "P").astype(np.float32)
    P = g.get(POINT, "P").astype(np.float32)
    lut = {tuple(p): i for i, p in enumerate(P)}
    ext = fid < _CUT - 1
    T = np.asarray(g.vertex_point).reshape(-1, 3)
    sizes = geo_a.prim_sizes()
    polys, pf, used = [], [], np.zeros(g.nprims, bool)
    for s in np.unique(fid[ext]):
        m = np.nonzero(fid == s)[0]
        ring = PA[geo_a.prim_points(int(s))]
        # "Not cut" = as many triangles as the original fan triangulation, with all corners of the original polygon present. Cut faces gain
        # intersection points (missing corners or more triangles); a single extra T-junction (neighbouring face cut, this one not) also changes the
        # triangle count, and restoring the original polygon would then lose that point and leave a crack, so the count must be checked
        if len(m) != sizes[s] - 2:
            continue
        ids = [lut.get(tuple(p)) for p in ring]
        if any(i is None for i in ids):
            continue
        polys.append(ids)
        pf.append(s)
        used[m] = True
    rest = np.nonzero(~used)[0]
    out_polys = polys + [list(T[i]) for i in rest]
    out_fid = np.concatenate([np.asarray(pf, np.int64), fid[rest]])
    h = Geometry.from_mesh(P, out_polys)
    if mode == "all" and len(rest):
        # Cut triangles: each source prim's own triangles are paired and merged separately (never across sources).
        # detriangulate doesn't carry prim attributes, so it is done in batches by source, tracking the source numbers ourselves
        from .boolean import detriangulate
        k = len(polys)
        parts = [_ops.delete_prims(h, np.arange(h.nprims) < k)] if k else []
        fids = [out_fid[:k]]
        for lab in np.unique(out_fid[k:]):
            sel = np.zeros(h.nprims, bool)
            sel[k:] = out_fid[k:] == lab
            dt = detriangulate(_ops.delete_prims(h, sel), 0.5)
            parts.append(dt)
            fids.append(np.full(dt.nprims, lab, np.int64))
        h = _ops.merge(*parts)
        out_fid = np.concatenate(fids)
        h = _weld_exact(h)                            # after batch merging, points on shared edges are duplicated; weld them back
    return h, out_fid


def boolean_fracture(geo, cutter, group="", treat_cutter="surface", detri="all",
                     name_mode="overwrite", namespace="", name_attrib="name",
                     prefix="piece", attrib_prefix="", piece_attrib="piece",
                     interior_group="inside", exterior_group="outside", merge_groups=True,
                     interior_seams="", exterior_seams="", pieces_inside="",
                     surface_inside="", copy_cut_attribs="",
                     interior_normals=True, interior_cusp=40.0,
                     exterior_normals="preserve", exterior_cusp=60.0):
    """See the module notes. Returns (geometry, report)."""
    if treat_cutter not in TREAT:
        raise ValueError(f"Treat Cutting Geometry As must be one of {TREAT}")
    if detri not in DETRI:
        raise ValueError(f"Detriangulate must be one of {DETRI}")
    from .voronoi import NAME_MODES, EXTERIOR_NORMALS, _normals
    if name_mode not in NAME_MODES:
        raise ValueError(f"Name Attribute must be one of {NAME_MODES}")
    if exterior_normals not in EXTERIOR_NORMALS:
        raise ValueError(f"Exterior Normals must be one of {EXTERIOR_NORMALS}")
    if geo is None or geo.nprims == 0:
        return Geometry(), {"pieces": 0}
    if cutter is None or cutter.nprims == 0:
        raise ValueError("Boolean Fracture needs cutting geometry on the second input")
    from .groups import resolve
    gmask = resolve(geo, PRIM, group)
    a = _ops.delete_prims(geo, gmask) if not gmask.all() else geo
    rest = _ops.delete_prims(geo, ~gmask) if not gmask.all() else None

    TA, sA = _tris_with_prim(a)
    A = _manifold(a.get(POINT, "P"), TA, sA, "Input geometry")
    lo = np.minimum(a.bbox()[0], cutter.bbox()[0])
    hi = np.maximum(a.bbox()[1], cutter.bbox()[1])
    D = 2.0 * float(np.linalg.norm(np.asarray(hi, np.float64) - np.asarray(lo, np.float64))) + 1.0
    from .topology import connectivity
    cut_comp = connectivity(cutter, cls="prim", name="__bf_cc").get(PRIM, "__bf_cc")[:, 0]
    cut_comp = np.unique(cut_comp, return_inverse=True)[1].reshape(-1)
    if treat_cutter == "solid":
        TB, sB = _tris_with_prim(cutter)
        cutters = [_manifold(cutter.get(POINT, "P"), TB, _CUT + sB, "Cutting geometry")]
    else:
        cutters = [_halfspace(cutter, np.nonzero(cut_comp == k)[0], D)
                   for k in np.unique(cut_comp)]

    # (manifold, inside the cutting geometry?) -- only meaningful for Solid (Pieces Inside Cutting Geometry)
    cur = [(A, False)]
    for C in cutters:
        nxt = []
        for M, ins in cur:
            for R, flag in ((M ^ C, True), (M - C, False)):
                if not R.is_empty():
                    nxt.append((R, flag))     # Solid has only one cutter, cut only once
        cur = nxt

    pieces = []
    for M, ins in cur:
        g, fid = _to_geo(M)
        if g is None:
            continue
        lab = connectivity(g, cls="prim", name="__bf_cc").get(PRIM, "__bf_cc")[:, 0]
        for k in np.unique(lab):
            keep = lab == k
            sub = _ops.delete_prims(g, keep)
            pieces.append((sub, fid[keep], ins))
    if not pieces:
        return (rest.copy() if rest is not None else Geometry()), {"pieces": 0}

    an = (lambda s: f"{attrib_prefix}{s}" if str(s).strip() else "")
    out_parts = []
    for num, (sub, fid, ins) in enumerate(pieces):
        sub, fid = _restore(sub, fid, a, detri)
        n = sub.nprims
        ext = fid < _CUT - 1                      # _CUT − 1 = bottom / sides of the extruded solid, also interior
        srcA = np.where(ext, fid, 0)
        srcB = np.where(fid >= _CUT, np.maximum(fid - _CUT, 0), 0)
        # A's prim attributes / prim groups copied back onto exterior faces by source
        for k, v in a.attribs[PRIM].items():
            vv = np.asarray(v)[srcA]
            if is_string(v):
                vv = np.where(ext[:, None] if vv.ndim == 2 else ext, vv, "")
                sub.set_string(PRIM, k, vv.reshape(-1))
            else:
                sub.set(PRIM, k, np.where(ext[:, None], vv, 0).astype(v.dtype), owned=True)
        for k, m in a.groups[PRIM].items():
            sub.set_group(PRIM, k, np.asarray(m, bool)[srcA] & ext)
        if str(copy_cut_attribs).strip():
            from .ops import match_names
            for k in match_names(list(cutter.attribs[PRIM]), str(copy_cut_attribs)):
                v = cutter.attribs[PRIM][k]
                vv = np.asarray(v)[np.minimum(srcB, cutter.nprims - 1)]
                if is_string(v):
                    old = sub.get(PRIM, k)
                    base = old.reshape(-1) if old is not None and is_string(old) else np.full(n, "")
                    sub.set_string(PRIM, k, np.where(~ext, vv.reshape(-1), base))
                else:
                    old = sub.get(PRIM, k)
                    base = np.asarray(old) if old is not None and old.shape[1] == vv.shape[1] \
                        else np.zeros_like(vv)
                    sub.set(PRIM, k, np.where((~ext)[:, None], vv, base).astype(v.dtype), owned=True)
        # Names
        if str(name_attrib).strip():
            nm = str(name_attrib).strip()
            new = f"{prefix}{num}"
            old = sub.get(PRIM, nm)
            if name_mode == "append":
                ov = [str(x) for x in old.reshape(-1)] if old is not None and is_string(old) else [""] * n
                own = next((x for x in ov if x), "")   # names of interior faces were already cleared above
                names = [f"{own}-{namespace}{new}" if own else f"{namespace}{new}"] * n
            else:
                names = [new] * n
            sub.set_string(PRIM, nm, np.array(names))
        if an(piece_attrib):
            sub.set(PRIM, an(piece_attrib), np.full((n, 1), num, np.int32), owned=True)
        ig, eg = an(interior_group), an(exterior_group)
        if ig:
            prev = sub.get_group(PRIM, ig)
            m = ~ext if not (merge_groups and prev is not None) else (np.asarray(prev, bool) | ~ext)
            sub.set_group(PRIM, ig, m)
        if eg:
            prev = sub.get_group(PRIM, eg)
            sub.set_group(PRIM, eg, np.asarray(prev, bool) if (merge_groups and prev is not None)
                          else ext)
        # Docs: these two groups require the cutting geometry treated as Solid; not created for Surface
        if str(pieces_inside).strip() and treat_cutter == "solid":
            sub.set_group(PRIM, str(pieces_inside).strip(), np.full(n, bool(ins)))
        if str(surface_inside).strip() and treat_cutter == "solid":
            sub.set_group(PRIM, str(surface_inside).strip(), ext & bool(ins))
        if str(exterior_seams).strip() or str(interior_seams).strip():
            from .boolean import seam_edges
            if str(exterior_seams).strip():
                sub.set_edge_group(str(exterior_seams).strip(), seam_edges(sub, ext))
            if str(interior_seams).strip():
                # Intersection lines of the cutting geometry with itself: both sides are interior faces, from different cutting surfaces
                # Intersection lines of the cutting geometry with itself: both sides are interior faces, from different cutting surfaces (connected pieces)
                cid = np.where(ext, -1, cut_comp[srcB])
                sub.set_edge_group(str(interior_seams).strip(), _diff_edges(sub, cid, ~ext))
        if interior_normals or exterior_normals != "preserve":
            sub = _normals(sub, ~ext, dict(interior_normals=interior_normals,
                                           interior_cusp=interior_cusp,
                                           exterior_normals=exterior_normals,
                                           exterior_cusp=exterior_cusp))
        out_parts.append(sub)
    out = _ops.merge(*out_parts)
    if rest is not None and rest.nprims:
        r = rest.copy()
        if an(piece_attrib):
            r.set(PRIM, an(piece_attrib), np.full((r.nprims, 1), -1, np.int32), owned=True)
        out = _ops.merge(out, r)
    return out, {"pieces": len(pieces), "cutters": len(cutters),
                 "inside": int(sum(1 for p in pieces if p[2]))}


def _diff_edges(g, lab, mask):
    """Edges (point pairs) whose two side faces are both in mask but have different lab."""
    from . import topology as _tp
    t = _tp.topology(g)
    if t.nedges == 0:
        return np.zeros((0, 2), np.int32)
    vprim = g.vertex_prim()
    keep = np.zeros(t.nedges, bool)
    two = np.nonzero(t.edge_count == 2)[0]
    if len(two):
        f1 = vprim[t.edge_he[t.edge_he_off[two]]]
        f2 = vprim[t.edge_he[t.edge_he_off[two] + 1]]
        keep[two] = mask[f1] & mask[f2] & (lab[f1] != lab[f2])
    return np.asarray(t.edge_points[keep], np.int32)
