"""
File Merge -- reads a series of numbered files and merges them into one geometry. Matches Houdini's File Merge SOP
(added in pcg100 s9; it used to point at Import Mesh, which reads only one file at a time).

`$SLICE` in the file name (the variable name comes from Merge Variable; `${SLICE}` is accepted too) is replaced in turn by
start, start + inc, ... of Merge Range (end inclusive; a negative inc walks backwards). For each file:
  - .npz is read as this plugin's geometry cache (written by File Cache); anything else is read with Import Mesh's
    format sniffing (OBJ / PLY / STL / GLB, all parameters at Import Mesh's defaults)
  - Delete Points from Other Files: deletes points whose point attribute slice differs from the current number
    (in distributed particle sims each file contains particles from other slices). The docs only say "slice attribute",
    so the attribute name is slice; if the file has no such attribute nothing is deleted
  - Missing File: error = raise an error (Houdini default); no_geometry = skip the file and note it in the report
Finally everything is merged in order. Houdini's Load (Info / Info Bounding Box) and Cache Length are not provided
(ComfyUI caches by inputs itself).
"""
from __future__ import annotations

import os

import numpy as np

from .core import Geometry, POINT

MISSING = ("error", "no_geometry")


def slices(start, end, inc):
    inc = int(inc)
    if inc == 0:
        raise ValueError("Merge Range increment cannot be 0")
    out, k = [], int(start)
    while (k <= int(end)) if inc > 0 else (k >= int(end)):
        out.append(k)
        k += inc
    return out


def expand(pattern, var, k):
    v = str(var).strip() or "SLICE"
    p = str(pattern)
    if f"${v}" not in p and "${" + v + "}" not in p:
        raise ValueError(f"File name has no ${v} -- File Merge needs it to substitute the number")
    return p.replace("${" + v + "}", str(k)).replace(f"${v}", str(k))


def _read(path):
    from . import meshio, geocache
    full = meshio.resolve(path)
    if full.lower().endswith(".npz"):
        return geocache.load(full)
    return meshio.load(full)[0]


def file_merge(pattern, start=0, end=3, inc=1, var="SLICE", delete_other=False,
               missing="error"):
    """Returns (geometry, report)."""
    if missing not in MISSING:
        raise ValueError(f"Missing File must be one of {MISSING}")
    from .ops import merge, delete_points
    parts, read, skipped = [], [], []
    for k in slices(start, end, inc):
        path = expand(pattern, var, k)
        try:
            g = _read(path)
        except (ValueError, FileNotFoundError) as ex:
            if missing == "error":
                raise ValueError(f"File Merge: file #{k} could not be read: {path}\n{ex}") from ex
            skipped.append(path)
            continue
        if delete_other:
            s = g.get(POINT, "slice")
            if s is not None:
                g = delete_points(g, np.asarray(s).reshape(len(s), -1)[:, 0] == k)
        parts.append(g)
        read.append(path)
    out = merge(*parts) if parts else Geometry()
    return out, {"read": read, "missing": skipped, "points": int(out.npoints),
                 "prims": int(out.nprims)}
