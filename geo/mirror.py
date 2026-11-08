"""
Mirror -- mirror about a plane. Matches Houdini's Mirror SOP.

It is one of the simplest nodes, but there are three things that are wrong if skipped, and wrong in a very unobtrusive way.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Mirroring **flips orientation**, so the primitive winding must be reversed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The determinant of a reflection matrix is **-1**. If you only reflect the point positions and copy the winding, every face normal
of the mirrored half points inward -- black when rendered, gone after backface culling, negative volume. And in a solid-shaded
preview it only shows from certain angles, so it is easy to miss.

The check uses exactly this: the mirrored half must have volume of the **same sign** as the original.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. Vector attributes must be reflected too, not copied
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Three-component **direction** quantities like N, v, up, tangent must be reflected along with the mirror; three-component attributes
that are not directions, like Cd and uv, are correctly copied as-is. No type system can tell them apart automatically, so there is a default list
(`N v up N0 tangentu tangentv force targetv`), which can be extended.

Normals need extra care: the winding is already flipped, so face normals flip along with it; **vertex/point N only needs
reflecting**, do not negate it again -- the reflection itself already takes it where it should go.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. append mode must weld on the plane, and the tolerance is relative
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When "original + mirror" are combined, the row of points sitting on the plane becomes two coincident copies, and the seam is a loop of
doubled boundary edges -- topologically not closed, so every downstream node that requires a closed mesh (Scatter in Volume,
Convex Decompose, volume) errors out or computes wrong results.

So append mode welds by default. Before welding, points **lying on the plane** are first projected exactly onto the plane: float
error makes points that should be at x=0 land at +/-1e-8, each side off a bit, giving a 2e-8 gap at weld time; without projecting,
the tolerance would have to grow large enough to swallow real features. After projection both sides coincide exactly and the weld is exact.

Snap Tolerance is normalized by the longest bounding box edge -- models at a different scale do not need retuning.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string

MODES = ("mirror", "append")
# pcg100: Houdini's Operation menu. mode (above) is actually Houdini's Keep Original toggle
OPERATIONS = ("mirror_all", "clip_and_mirror")
ORIENTS = ("direction", "transform")
# Three-component **direction** quantities, reflected when mirroring; Cd / uv and the like are copied as-is
VECTOR_ATTRIBS = ("N", "v", "up", "N0", "tangentu", "tangentv",
                  "force", "targetv")


def reflect_matrix(n, o):
    """Reflection about the plane through point o with normal n: x -> x - 2(n.(x-o))n."""
    n = np.asarray(n, np.float64).reshape(3)
    ln = float(np.linalg.norm(n))
    if ln <= 0:
        raise ValueError("Mirror normal cannot be a zero vector.")
    n = n / ln
    return np.eye(3) - 2.0 * np.outer(n, n), np.asarray(o, np.float64), n


def reflect(geo, n, o, vector_attribs=VECTOR_ATTRIBS, reverse=True):
    """Reflect geometry: point positions, direction attributes, and **primitive winding** (with reverse=False the winding is copied,
    matching Houdini's Reverse Normals turned off -- the mirrored copy's faces point inward)."""
    M, o, nn = reflect_matrix(n, o)
    out = geo.copy()
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    out.set(POINT, "P", ((P - o) @ M + o).astype(np.float32), owned=True)
    names = {s.strip() for s in vector_attribs if str(s).strip()}
    for cls in (POINT, VERTEX, PRIM):
        for k, v in list(geo.attribs[cls].items()):
            if k == "P" or k not in names or is_string(v) or v.shape[1] < 3:
                continue
            w = np.asarray(v, np.float64).copy()
            w[:, :3] = w[:, :3] @ M          # direction quantities only rotate, no translation
            out.set(cls, k, w.astype(v.dtype), owned=True)
    # Reflection has determinant -1: without flipping the winding every face points inward
    if not reverse:
        return out
    from .ops import reverse_prims
    return reverse_prims(out)


def mirror(geo, mode="append", origin=(0.0, 0.0, 0.0), normal=(1.0, 0.0, 0.0),
           snap_tolerance=1e-4, fuse_result=True, keep_original_group="",
           mirror_group="", vector_attribs=VECTOR_ATTRIBS,
           group="", operation="mirror_all", orient="direction",
           translate=(0.0, 0.0, 0.0), rotate=(0.0, 0.0, 0.0), distance=0.0,
           reverse_normals=True):
    """
    mode=mirror outputs only the mirrored copy; mode=append outputs "original + mirrored copy" welded on the plane.

    pcg100 additions (defaults = previous behaviour):
        group            mirror only these primitives. With mode=mirror the output contains **only** the mirrored copy of these primitives
                         (the docs say that with Keep Original off "only the selected geometry remains"),
                         with mode=append it is the whole original + the mirrored copy of these primitives
        operation        clip_and_mirror: first cut the primitives (in the group) with the mirror plane, discard the half on the
                         back side of the normal, then mirror what remains. The original is also the clipped version
        orient=transform the plane is given by translate / rotate: through translate, with normal (1,0,0)
                         rotated by rotate (order X->Y->Z). The docs do not state the base normal or rotation order;
                         (1,0,0) is the default of Direction
        distance         how far to move the plane further along the normal
        reverse_normals  off = the mirrored copy keeps its winding (faces point inward)
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if operation not in OPERATIONS:
        raise ValueError(f"Operation must be one of {OPERATIONS}")
    if orient not in ORIENTS:
        raise ValueError(f"Orient Plane with must be one of {ORIENTS}")
    if geo.npoints == 0:
        return geo.copy()

    if orient == "transform":
        from .ops import euler_matrix
        normal = euler_matrix(*np.asarray(rotate, np.float64).reshape(3)) \
            @ np.array([1.0, 0.0, 0.0])
        origin = translate
    _, o, nn = reflect_matrix(normal, origin)
    o = o + nn * float(distance)
    mn, mx = geo.bbox()
    scale = float(np.max(np.asarray(mx, np.float64)
                         - np.asarray(mn, np.float64))) or 1.0
    tol = float(snap_tolerance) * scale

    src = geo
    if mode == "append" and tol > 0:
        # Points lying on the plane are first projected exactly onto it -- otherwise each side is off by a bit of float error and the weld
        # tolerance would have to grow large enough to swallow real features
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        t = (P - o) @ nn
        on = np.abs(t) <= tol
        if on.any():
            src = geo.copy()
            src.set(POINT, "P",
                    (P - np.where(on, t, 0.0)[:, None] * nn).astype(np.float32),
                    owned=True)

    part = src                                     # the part that gets mirrored
    has_group = bool(str(group).strip())
    if has_group or operation == "clip_and_mirror":
        from .groups import resolve
        from .ops import delete_prims
        sel = resolve(src, PRIM, group)
        if operation == "clip_and_mirror" and src.nprims:
            from .clip import clip_plane
            src, side = clip_plane(src, nn, o, sel, "above")
            sel = side != 0                        # primitives outside the group have side = 0 and stay as they are
        part = src if sel.all() else delete_prims(src, sel)

    ref = reflect(part, nn, o, vector_attribs, reverse_normals)
    if mode == "mirror":
        if str(mirror_group).strip():
            ref.set_group(PRIM, str(mirror_group).strip(),
                          np.ones(ref.nprims, bool))
        return ref

    from .ops import merge, fuse
    a, b = src.copy(), ref
    n0 = a.nprims
    out = merge(a, b)
    if str(keep_original_group).strip():
        m = np.zeros(out.nprims, bool)
        m[:n0] = True
        out.set_group(PRIM, str(keep_original_group).strip(), m)
    if str(mirror_group).strip():
        m = np.zeros(out.nprims, bool)
        m[n0:] = True
        out.set_group(PRIM, str(mirror_group).strip(), m)
    if fuse_result and tol > 0:
        out = fuse(out, tol)
    return out
