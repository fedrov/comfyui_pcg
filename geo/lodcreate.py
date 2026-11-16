"""
LOD Create (after SideFX Labs LOD Create 2.0): a chain of levels of detail from one mesh.

    LODs        Percent Triangles per level (`100 50 25 10`: LOD0 is the mesh as it is, the others are reduced
                from LOD0 to that share of its triangles) and Threshold Distance per level (the distance at which
                the level starts; empty = 0, then doubling from First Distance)
    Reduction   quadric edge collapse (Poly Reduce). Preserve UVs keeps seams in place so every level uses LOD0's
                textures; Boundary Weight keeps open borders
    Normals     Recalculate Normals writes vertex normals split at Cusp Angle (on the reduced levels, and on an
                unreduced level that has none)
    Impostor    Last LOD is Impostor replaces the last level by two crossed upright cards (uv 0..1 each) the size
                of the bounding box, for an impostor atlas
    Assets      if the mesh has a string prim attribute `name` (one name per asset), every asset gets its own
                chain
    Custom      a second input whose faces carry an integer prim attribute `lod` replaces those levels (Labs'
                Custom Mesh): a simplified model made another way -- a building's massing without its openings, say,
                where reducing the detailed one would tear the facade. The level's percent then applies to the custom
                mesh (100 = as it is). With asset names, a custom face goes to the asset of the same `name` (no name:
                to every asset)

Output: all levels in one geometry. Prim attributes `lod` (level), `part` (`LOD0`...), `name`
(`<asset>_<prefix><n>`, or `<prefix><n>`), `lod_distance`, `impostor` (1 on impostor cards); prim groups `LOD0`...
View: all (in place, pick one downstream by group), single (only Level), debug (side by side along +X).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM

VIEWS = ("all", "single", "debug")


def _floats(spec):
    return [float(x) for x in str(spec).replace(",", " ").split()]


def _tris(g):
    return int(np.maximum(g.prim_sizes() - 2, 0)[np.asarray(g.prim_closed)].sum()) if g.nprims else 0


def _cards(g):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    lo, hi = P.min(0), P.max(0)
    c = (lo + hi) * 0.5
    r = max(hi[0] - lo[0], hi[2] - lo[2]) * 0.5
    pts, faces = [], []
    for ax in ((1.0, 0.0), (0.0, 1.0)):
        k = len(pts)
        for sx, y in ((-1, lo[1]), (1, lo[1]), (1, hi[1]), (-1, hi[1])):
            pts.append([c[0] + sx * r * ax[0], y, c[2] + sx * r * ax[1]])
        faces.append([k, k + 1, k + 2, k + 3])
    out = Geometry.from_mesh(np.asarray(pts), faces)
    out.set(VERTEX, "uv", np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]] * 2, np.float32))
    return out


def lod_create(geo, percents="100 50 25 10", distances="", first_distance=20.0, preserve_uvs=True,
               boundary_weight=4.0, recalculate_normals=True, cusp_angle=60.0, last_lod_impostor=False,
               name_prefix="LOD", view="all", level=0, spacing=1.2, custom=None):
    """Build the LOD chain of geo; see the module docstring. -> Geometry, report dict."""
    from .ops import merge, delete_prims, compute_normals
    from .polyreduce import reduce_mesh
    if view not in VIEWS:
        raise ValueError(f"View must be one of {VIEWS}")
    pc = _floats(percents)
    if not pc:
        raise ValueError("LODs: give at least one Percent Triangles value, e.g. '100 50 25 10'")
    if any(p <= 0 or p > 100 for p in pc):
        raise ValueError("Percent Triangles must be above 0 and at most 100")
    ds = _floats(distances)
    if ds and len(ds) != len(pc):
        raise ValueError(f"Threshold Distance: {len(ds)} values for {len(pc)} LODs")
    if not ds:
        ds = [0.0] + [float(first_distance) * 2 ** k for k in range(len(pc) - 1)]
    if any(b < a for a, b in zip(ds, ds[1:])):
        raise ValueError("Threshold Distance must not decrease from one LOD to the next")
    if geo is None or geo.nprims == 0:
        return Geometry(), {"lods": []}
    nm = geo.get(PRIM, "name")
    if nm is not None and np.asarray(nm).dtype.kind == "U":
        nm = np.asarray(nm).reshape(-1)
        assets = [(str(a), delete_prims(geo, nm == a)) for a in np.unique(nm)]
    else:
        assets = [("", geo)]
    cust = {}                                                       # (asset, level) -> custom mesh of that level
    if custom is not None and custom.nprims:
        cl = custom.get(PRIM, "lod")
        if cl is None or np.asarray(cl).dtype.kind == "U":
            raise ValueError("Custom Mesh needs an integer prim attribute 'lod' (the level each face replaces)")
        cl = np.rint(np.asarray(cl, np.float64).reshape(-1)).astype(int)
        cn = custom.get(PRIM, "name")
        cn = (np.asarray(cn).reshape(-1).astype(str) if cn is not None and np.asarray(cn).dtype.kind == "U"
              else np.full(custom.nprims, ""))
        for a_, _ in assets:
            for n_ in np.unique(cl):
                if n_ < 0 or n_ >= len(pc):
                    raise ValueError(f"Custom Mesh: lod {n_} does not exist (there are {len(pc)} LODs)")
                sel = (cl == n_) & ((cn == a_) | (cn == "") if a_ else np.ones(len(cl), bool))
                if sel.any():
                    cust[(a_, int(n_))] = delete_prims(custom, sel)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    width = float(np.ptp(P[:, 0])) if len(P) else 1.0
    parts, rep = [], []
    prefix = str(name_prefix).strip() or "LOD"
    for aname, g0 in assets:
        t0 = _tris(g0)
        for n, pct in enumerate(pc):
            imp = bool(last_lod_impostor) and n == len(pc) - 1 and n > 0
            if imp:
                g = _cards(g0)
            elif (aname, n) in cust:                                # a custom mesh, reduced by its own percent
                gc = cust[(aname, n)]
                g = gc.copy() if pct >= 100.0 else reduce_mesh(
                    gc, "percentage", pct, boundary_weight=float(boundary_weight), preserve_uvs=bool(preserve_uvs))
                if recalculate_normals and g.nprims:
                    g = compute_normals(g, add_to="vertex", cusp_angle=float(cusp_angle))
            else:
                g = g0.copy() if pct >= 100.0 else reduce_mesh(
                    g0, "percentage", pct, boundary_weight=float(boundary_weight), preserve_uvs=bool(preserve_uvs))
                # the unreduced level gets them too (its shape is untouched): merged levels need the same
                # attributes, or the level without N would come out with zero normals
                if recalculate_normals and g.nprims and (pct < 100.0 or not g.has(VERTEX, "N")):
                    g = compute_normals(g, add_to="vertex", cusp_angle=float(cusp_angle))
            k = g.nprims
            g.set(PRIM, "lod", np.full(k, n, np.int32))
            g.set_string(PRIM, "part", np.full(k, f"LOD{n}"))
            g.set_string(PRIM, "name", np.full(k, f"{aname}_{prefix}{n}" if aname else f"{prefix}{n}"))
            g.set(PRIM, "lod_distance", np.full(k, ds[n], np.float32))
            g.set(PRIM, "impostor", np.full(k, int(imp), np.int32))
            rep.append({"asset": aname, "lod": n, "triangles": _tris(g), "of": t0, "distance": ds[n],
                        "impostor": imp, "custom": (aname, n) in cust})
            if view == "single" and n != int(level):
                continue
            if view == "debug" and n:
                Q = g.get_w(POINT, "P")
                Q[:, 0] += n * width * float(spacing)
                g.set(POINT, "P", Q)
            parts.append(g)
    if not parts:
        raise ValueError(f"Level {level} does not exist: there are {len(pc)} LODs (0..{len(pc) - 1})")
    out = merge(*parts)
    lod = np.asarray(out.get(PRIM, "lod")).reshape(-1)
    for n in np.unique(lod):
        out.set_group(PRIM, f"LOD{int(n)}", lod == n)
    return out, {"lods": rep}
