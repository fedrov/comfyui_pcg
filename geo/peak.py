"""
Peak -- push points along normals. Matches Houdini's Peak SOP.

One of the simplest nodes, but there is one detail worth being picky about.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Push along the point normal by d" is not the same as "offset the surface by d"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A cube's corner normal is (1,1,1)/sqrt(3). Pushing along it by d moves the corner only
d/sqrt(3) ~ 0.577d **along each face's normal**, while points in the middle of the faces (if any) move d. The result:

    . faces are no longer flat (corners sink in)
    . the offset does not match the number you entered
    . a pushed cube is no longer a cube

Houdini's Peak behaves the same way; people are just used to it. A toggle is provided here:

    With Miter Corners on, the displacement is multiplied by **1 / (n_point . n_face)** --
    taking the **smallest** dot product among all faces adjacent to the point.

This is exactly the miter algorithm: corner points are pushed to the **intersection** of the offset adjacent faces.
A cube's corner is multiplied by sqrt(3), the pushed cube is still a cube, and the edge length grows by exactly 2d. This has a closed-form solution, which makes
a much harder test criterion than "looks about right".

Cost: at nearly tangent folds (point normal and face normal at close to 90 deg) the factor blows up, so
there is a Max Miter cap to catch it -- the same parameter every place that does mitering (bevel, stroke, extrude) has to
have.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Where the normals come from
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If N exists it is used as is (upstream may already have tuned the cusp angle with Normal (PCG), or perturbed it with Attribute
Noise); otherwise one is computed **but not written back** -- Peak should not sneak attributes onto your geometry.

Distance Attribute can give each point its own factor (use with Attribute Fade / Attribute
Noise); final displacement = distance x that point's attribute value.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT


def point_normals(geo):
    """The existing N, or if absent an area-weighted one computed on the fly (not written back to the geometry)."""
    N = geo.get(POINT, "N")
    if N is not None and N.shape[1] >= 3:
        return np.asarray(N[:, :3], np.float64)
    from .ops import compute_normals
    return np.asarray(compute_normals(geo, add_to="point").get(POINT, "N")
                      [:, :3], np.float64)


def miter_scale(geo, N, max_scale=8.0):
    """
    Per-point miter factor 1 / min(n_point . n_face).

    Meaning "push the corner point to the intersection of the offset adjacent faces". A cube's corner gets sqrt(3), and the pushed result
    is still a cube. The value blows up at tangent folds, so max_scale is needed as a safeguard.
    """
    from .ops import prim_normals
    if geo.nprims == 0 or geo.nvertices == 0:
        return np.ones(len(N))
    FN = np.asarray(prim_normals(geo), np.float64)
    vp = geo.vertex_point
    vf = geo.vertex_prim()
    d = np.einsum("ij,ij->i", N[vp], FN[vf])
    # Each point takes the **smallest** dot product among its adjacent faces -- the miter must satisfy the tightest face
    mind = np.full(len(N), np.inf)
    np.minimum.at(mind, vp, d)
    mind = np.where(np.isfinite(mind), mind, 1.0)
    return np.clip(1.0 / np.maximum(mind, 1.0 / float(max_scale)),
                   0.0, float(max_scale))


def peak(geo, distance=0.1, group="", miter=False, max_miter=8.0,
         distance_attrib="", normal_attrib="N"):
    """Push points along point normals. With miter=True, scale by the miter factor so planes stay planar."""
    if geo is None:
        return Geometry()
    if geo.npoints == 0:
        return geo.copy()
    from .groups import resolve
    sel = resolve(geo, POINT, group)

    name = str(normal_attrib).strip() or "N"
    N = geo.get(POINT, name)
    if N is None or N.shape[1] < 3:
        if name != "N":
            raise KeyError(
                f"Points have no '{name}' attribute (or it is not three-component). Leave empty to use the default N, "
                f"or add a Normal (PCG) before this.")
        N = point_normals(geo)
    else:
        N = np.asarray(N[:, :3], np.float64)

    d = np.full(geo.npoints, float(distance))
    a = str(distance_attrib).strip()
    if a:
        v = geo.get(POINT, a)
        if v is None:
            raise KeyError(
                f"Points have no '{a}' attribute -- if Distance Attribute should scale displacement per point, "
                f"add an Attribute Fade / Attribute Noise before this to compute it first.")
        d = d * np.asarray(v[:, 0], np.float64)
    if miter:
        d = d * miter_scale(geo, N, max_miter)
    d = np.where(sel, d, 0.0)

    out = geo.copy()
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    out.set(POINT, "P", (P + N * d[:, None]).astype(np.float32), owned=True)
    return out
