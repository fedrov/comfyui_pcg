"""
LOD manifest: what an engine needs to set up the LOD chains of an exported mesh, as JSON beside it.

The geometry is LOD Create's output (or anything shaped like it): prims carry `name` (`<asset>_LOD<k>`, as Export
Mesh's Split Attribute writes the nodes), optionally `lod` (the level) and `lod_distance` (the switch distance in
metres). Per asset the manifest lists its levels (node name, level, distance, triangle count), its bounds and its
materials (and its collision nodes, UCX_<asset>_NN, which are not levels), and two ready-made sets of thresholds for a camera with the given vertical field of view:

    screen_size     the fraction of the screen height the bounding sphere covers at the level's distance:
                    r / (d tan(fov / 2)), 1 at distance 0 -- Unreal's per-LOD Screen Size (switch to LOD k below it)
    unity           Unity LODGroup's screenRelativeTransitionHeight per level: where that level ends, i.e. the next
                    level's screen size (the last level ends at Cull Screen Size; 0 = never culled)

Distances and bounds are in the exported file's units (positions times Export Mesh's Scale).
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

from .core import POINT, PRIM

_LODRE = re.compile(r"^(.*)_LOD(\d+)$")
_UCXRE = re.compile(r"^UCX_(.*)_\d+$")


def manifest(geo, fov=60.0, scale=1.0, cull_screen_size=0.0):
    """-> dict (see the module docstring)."""
    t = float(np.tan(np.radians(np.clip(float(fov), 1.0, 179.0)) / 2.0))
    n = geo.nprims
    nm = geo.get(PRIM, "name")
    names = (np.asarray(nm).reshape(-1).astype(str) if nm is not None and np.asarray(nm).dtype.kind == "U"
             else np.full(n, ""))
    la = geo.get(PRIM, "lod")
    lod = np.full(n, -1, np.int64) if la is None else np.rint(np.asarray(la, np.float64).reshape(-1)).astype(np.int64)
    asset = np.empty(n, object)
    ucx = {}                                       # collision nodes (UCX_<asset>_NN) by asset: not levels
    for i, s in enumerate(names):
        u = _UCXRE.match(s)
        if u:
            asset[i] = None
            ucx.setdefault(u.group(1), set()).add(s)
            continue
        m = _LODRE.match(s)
        asset[i] = m.group(1) if m else s
        if lod[i] < 0:
            lod[i] = int(m.group(2)) if m else 0
    da = geo.get(PRIM, "lod_distance")
    dist = np.zeros(n) if da is None else np.asarray(da, np.float64).reshape(-1) * float(scale)
    ma = geo.get(PRIM, "material")
    mats = np.asarray(ma).reshape(-1).astype(str) if ma is not None and np.asarray(ma).dtype.kind == "U" else None
    off = np.asarray(geo.prim_offset)
    vp = np.asarray(geo.vertex_point)
    tris = np.maximum(np.diff(off) - 2, 0)
    P = np.asarray(geo.get(POINT, "P"), np.float64) * float(scale)
    out = []
    for a in sorted(set(asset.tolist()) - {None}):
        sel = asset == a
        levels = sorted(set(lod[sel].tolist()))
        l0 = sel & (lod == levels[0])
        pts = np.unique(np.concatenate([vp[off[i]:off[i + 1]] for i in np.nonzero(l0)[0]])) if l0.any() else []
        Q = P[pts] if len(pts) else np.zeros((1, 3))
        lo, hi = Q.min(0), Q.max(0)
        c = 0.5 * (lo + hi)
        r = float(np.linalg.norm(hi - lo) / 2)
        lods = []
        for k in levels:
            s_ = sel & (lod == k)
            d = float(dist[s_][0]) if s_.any() else 0.0
            ss = 1.0 if d <= 0 else min(1.0, r / (d * t))
            node = next((x for x in names[s_] if x), f"{a}_LOD{k}")
            lods.append({"lod": int(k), "node": node, "distance": round(d, 4), "triangles": int(tris[s_].sum()),
                         "screen_size": round(ss, 6)})
        for j, e in enumerate(lods):
            e["unity_transition"] = lods[j + 1]["screen_size"] if j + 1 < len(lods) else round(float(cull_screen_size), 6)
        out.append({"name": a, "bounds": {"min": [round(float(v), 4) for v in lo], "max": [round(float(v), 4) for v in hi],
                                          "center": [round(float(v), 4) for v in c], "radius": round(r, 4)},
                    "materials": sorted(set(mats[sel].tolist()) - {""}) if mats is not None else [],
                    "lods": lods, **({"collision": sorted(ucx[a])} if a in ucx else {})})
    return {"fov_degrees": float(fov), "units": "metres x scale", "up": "+Y", "assets": out}


def write(geo, path, fov=60.0, scale=1.0, cull_screen_size=0.0):
    """Writes the manifest as JSON to path (folders created). -> the dict."""
    m = manifest(geo, fov, scale, cull_screen_size)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)
    return m
