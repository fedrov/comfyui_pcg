"""
Ends -- open / close / unroll / roll curves. Matches Houdini's Ends SOP.

A small but long-missing piece. `prim_closed` is a **boolean flag** that decides whether the closing edge between the last
and first point exists. A whole set of downstream nodes (Resample / Carve / Sweep /
PolyExpand2D) treat open and closed curves completely differently, and the flag coming from upstream is often not what you
want -- a loop cut by Clip becomes open, a contour from Trace is closed but you want to resample it as an open curve.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Four ops; the difference is "**does the geometry change**"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    close    only flips the flag. **One extra** closing edge; the shape changes (an extra chord)
    open     only flips the flag. **One edge fewer**; the shape changes
    unroll   closed -> open, and the first point is **attached again** at the end. Edge count unchanged,
             **shape completely unchanged** -- the only op that "changes representation, not geometry"
    roll     inverse of unroll: an open curve whose first and last points coincide -> drop the duplicate and close it

`unroll` is the most used of the four: send a closed loop straight into Resample and the resampler doesn't know where
to start (a closed curve has no start point); after unroll it is an ordinary open curve that looks identical.
Afterwards `roll` it back.

`unroll -> roll` is the **identity** (topology bit for bit); this is the module's main acceptance criterion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two-point prims may not be closed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Closing a two-point polyline gives two coincident edges "A->B and B->A" -- a degenerate zero-area primitive.
It is useless downstream: normals come out nan, area 0, triangulation gives zero-area triangles,
and it **looks exactly like the original**, so it travels a long way before blowing up. It is simply skipped here,
without an error (errors are more annoying in batch processing).

The vertex attributes of the new corner created by `unroll` are copied from the **first** corner --
it references the same point anyway, so carrying uv and the like over is correct.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL
from .groups import resolve

OPS = ("close", "open", "unroll", "roll")


def _rebuild(geo, blocks, closed):
    """Rebuilds from new corner blocks. blocks hold **source corner indices**."""
    sizes = [len(b) for b in blocks]
    cor = (np.concatenate(blocks) if blocks
           else np.zeros(0, np.int64)).astype(np.int64)
    g = Geometry()
    g._resize_points(geo.npoints)
    for k, v in geo.attribs[POINT].items():
        g.set(POINT, k, v)
    for k, v in geo.groups[POINT].items():
        g.set_group(POINT, k, v)
    g.set_topology(geo.vertex_point[cor].astype(np.int32),
                   np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                   np.asarray(closed, bool))
    for k, v in geo.attribs[VERTEX].items():
        g.set(VERTEX, k, v[cor], owned=True)
    for k, v in geo.groups[VERTEX].items():
        g.set_group(VERTEX, k, v[cor])
    for k, v in geo.attribs[PRIM].items():
        g.set(PRIM, k, v)
    for k, v in geo.groups[PRIM].items():
        g.set_group(PRIM, k, v)
    g.prim_data = {k: dict(v) for k, v in geo.prim_data.items()}
    g.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    for k, v in geo.edge_groups.items():
        g.edge_groups[k] = v
    return g


def ends(geo, group="", op="unroll", tolerance=0.0):
    """
    Opens / closes / unrolls / rolls the selected prims. The **number and order of prims don't change at all**, so
    prim attributes, prim groups and side-channel data all still line up.

    `tolerance` is only used by roll: first and last points that aren't the same point number but lie within tolerance also count as coincident.
    0 means only the same point number counts.
    """
    if geo is None:
        return Geometry()
    if op not in OPS:
        raise ValueError(f"Op must be one of {OPS}")
    if geo.nprims == 0:
        return geo.copy()
    sel = resolve(geo, PRIM, group)
    if not sel.any():
        return geo.copy()

    off = geo.prim_offset.astype(np.int64)
    vp = geo.vertex_point.astype(np.int64)
    P = geo.get(POINT, "P")
    tol = float(tolerance)
    Pd = (np.asarray(P, np.float64) if (P is not None and tol > 0) else None)

    blocks, closed, changed = [], [], False
    for i in range(geo.nprims):
        cor = np.arange(off[i], off[i + 1], dtype=np.int64)
        cl = bool(geo.prim_closed[i])
        if not sel[i] or len(cor) < 2:
            blocks.append(cor)
            closed.append(cl)
            continue
        if op == "close":
            # A closed two-point prim is a doubled edge (degenerate zero-area primitive); skip
            new_cl = cl or len(cor) >= 3
            changed |= new_cl != cl
            blocks.append(cor)
            closed.append(new_cl)
        elif op == "open":
            changed |= cl
            blocks.append(cor)
            closed.append(False)
        elif op == "unroll":
            if cl:
                blocks.append(np.concatenate([cor, cor[:1]]))
                closed.append(False)
                changed = True
            else:
                blocks.append(cor)
                closed.append(False)
        else:                                   # roll
            same = vp[cor[0]] == vp[cor[-1]]
            if not same and Pd is not None:
                same = bool(np.linalg.norm(
                    Pd[vp[cor[0]]] - Pd[vp[cor[-1]]]) <= tol)
            if (not cl) and same and len(cor) >= 4:
                blocks.append(cor[:-1])
                closed.append(True)
                changed = True
            else:
                blocks.append(cor)
                closed.append(cl)
    if not changed:
        return geo.copy()
    return _rebuild(geo, blocks, closed)
