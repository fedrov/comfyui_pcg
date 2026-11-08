"""
Thicken (pcg121): give an open surface (a leaf, cloth, a terrain patch, a shell) a real thickness.

PolyExtrude can do it with Output Back on and Point Normal extrusion, but needs four settings right; Thicken is the
one-knob version and adds the choice of which side the thickness goes to:

  outward  the input stays the inner skin, the new skin is Thickness away along the point normals
  inward   the input stays the outer skin
  both     the input becomes the mid-surface (half the thickness to each side) -- what cloth / leaf assets want

Front / back / side faces get the groups thickenFront / thickenBack / thickenSide. Thickness is measured along
the (area-weighted) point normals, so on sharp convex corners the shell gets thinner than Thickness, like any
offset-by-normals; closed meshes become hollow shells.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM
from .groups import resolve

MODES = ("both", "outward", "inward")


def thicken(geo, group="", thickness=0.1, mode="both", divisions=1, front_group="thickenFront",
            back_group="thickenBack", side_group="thickenSide"):
    """Returns (geometry, report)."""
    from .ops import compute_normals, polyextrude
    if mode not in MODES:
        raise ValueError(f"Side must be one of {MODES}")
    t = float(thickness)
    if not geo.nprims:
        raise ValueError("Thicken needs polygons")
    sel = resolve(geo, PRIM, group)
    if not sel.any():
        return geo.copy(), {"prims": 0}
    g = geo
    shift = {"both": -0.5, "outward": 0.0, "inward": -1.0}[mode] * t
    if shift:
        g = geo.copy()
        N = np.asarray(compute_normals(geo, "point", group=group or None).get(POINT, "N"), np.float64)
        pts = np.zeros(geo.npoints, bool)
        sizes = geo.prim_sizes()
        pts[geo.vertex_point[np.repeat(sel, sizes)]] = True
        P = np.asarray(g.get(POINT, "P"), np.float64)
        P[pts] += N[pts] * shift
        g.set(POINT, "P", P.astype(np.float32), owned=True)
    grp = str(group).strip() or None
    out = polyextrude(g, grp, distance=t, divisions=max(1, int(divisions)), output_front=True, output_back=True,
                      output_side=True, front_group=front_group, back_group=back_group, side_group=side_group,
                      extrusion_mode="point_normal")
    return out, {"prims": int(sel.sum()), "thickness": t, "side": mode, "points": out.npoints}
