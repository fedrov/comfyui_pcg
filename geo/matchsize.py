"""
Match Size SOP -- aligns / scales geometry to a target bounding box.

In Houdini the real purpose of this node is not "resizing" but **establishing a reversible canonical space**:
match a model from any source into the unit box -> work in canonical space (cut, scatter, UV) ->
send it back into place with the stashed transform. So the Stash / Restore pair matters as much as alignment,
and both are done here.

The transform is stored as a 4x4 matrix in a detail attribute (16 floats in a row). Restore reads it,
inverts it and applies it -- the inverse matrix rather than "reverse translate and scale", so that if rotation is added later
the restore path doesn't need a single line changed.

Alignment rules match Houdini, independently per axis:

    justify      which position of the source is the anchor (min / center / max / none)
    justify_to   which position of the target it aligns to (same = the same kind as the source)
    offset       an extra shift after alignment

none means this axis doesn't move -- scaling still happens, but around the source's own anchor, so the position stays.

Without a second input the reference box comes from Target Position / Size, and **Target Position is the anchor
placed according to this axis's justify**, not a fixed centre (per the Houdini docs).
So with default parameters justify_y=min means "put the model on the ground", not sunk by half a box.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, DETAIL
from .groups import resolve

_ANCHOR = {"min": 0.0, "center": 0.5, "max": 1.0}


def bounds(geo, group="", group_type="prim", use_group=False):
    """(min, max); with use_group=True only the points used by the group's elements count."""
    P = geo.get(POINT, "P")
    if P is None or len(P) == 0:
        z = np.zeros(3)
        return z, z.copy()
    if use_group and str(group).strip():
        if group_type == "point":
            m = resolve(geo, POINT, group)
        else:
            pm = resolve(geo, PRIM, group)
            m = np.zeros(geo.npoints, bool)
            if geo.nvertices:
                m[geo.vertex_point[pm[geo.vertex_prim()]]] = True
        if m.any():
            P = P[m]
    P = P.astype(np.float64)
    return P.min(0), P.max(0)


def _anchor(mn, mx, kind):
    f = _ANCHOR.get(kind, 0.5)
    return mn + (mx - mn) * f


def _mat(scale, translate):
    """Row-vector convention: P' = P @ M[:3,:3] + M[3,:3], same as ops.transform."""
    M = np.eye(4)
    M[0, 0], M[1, 1], M[2, 2] = scale
    M[3, :3] = translate
    return M


def _apply(geo, M, also_vectors=True):
    """Applies a 4x4. Direction attributes (N) go through the inverse transpose so normals don't skew under non-uniform scale."""
    g = geo.copy()
    P = geo.get(POINT, "P")
    if P is None or len(P) == 0:
        return g
    R = M[:3, :3]
    g.set(POINT, "P", (P.astype(np.float64) @ R + M[3, :3]).astype(P.dtype),
          owned=True)
    if also_vectors:
        try:
            NM = np.linalg.inv(R).T
        except np.linalg.LinAlgError:
            NM = R
        for cls in (POINT, "vertex", PRIM):
            N = g.get(cls, "N")
            if N is None or N.shape[1] != 3:
                continue
            v = N.astype(np.float64) @ NM
            l = np.linalg.norm(v, axis=1, keepdims=True)
            g.set(cls, "N", (v / np.where(l == 0, 1, l)).astype(N.dtype),
                  owned=True)
    return g


def match_size(geo, target=None, group="", group_type="prim",
               justify_with="input_if_wired",
               target_position=(0.0, 0.0, 0.0), target_size=(1.0, 1.0, 1.0),
               use_groups_for_bounds=False,
               translate=True,
               justify=("center", "center", "center"),
               justify_to=("same", "same", "same"),
               offset=(0.0, 0.0, 0.0),
               scale_to_fit=False, uniform_scale=True,
               stash_attrib="", restore_attrib=""):
    """
    When restore_attrib is named and the geometry really has that detail attribute, **only restore is done**:
    read that 4x4, invert and apply it to send the geometry back to where it was before the stash; all other parameters are ignored.
    This is how Restore Transform is used in Houdini -- it and alignment are mutually exclusive.
    """
    if geo is None:
        return Geometry()
    name = str(restore_attrib).strip()
    if name and geo.has(DETAIL, name):
        M = np.asarray(geo.get(DETAIL, name), np.float64).reshape(4, 4)
        try:
            inv = np.linalg.inv(M)
        except np.linalg.LinAlgError:
            raise ValueError(f"The transform in detail attribute '{name}' is not invertible; cannot restore.")
        g = _apply(geo, inv)
        g.remove(DETAIL, name)
        return g

    smn, smx = bounds(geo, group, group_type, use_groups_for_bounds)
    if target is not None and justify_with == "input_if_wired":
        tmn, tmx = bounds(target, group, group_type, use_groups_for_bounds)
    else:
        c = np.asarray(target_position, np.float64).reshape(3)
        sz = np.asarray(target_size, np.float64).reshape(3)
        # Target Position is an **anchor**, not a fixed centre. The Houdini docs say:
        # "It represents the center of the box unless the relevant axis'
        #  justification is Min or Max, in which case it represents the edge."
        # So the reference box hangs off Target Position according to this axis's justify:
        # min -> [pos, pos+size] / center -> [pos-size/2, pos+size/2] /
        # max -> [pos-size, pos].
        # Without this, justify_y=min + default parameters would not put the model on the ground but
        # sink it by half a target_size -- and "put it on the ground" is exactly this node's most common use.
        f = np.array([{"min": 0.0, "max": 1.0}.get(justify[i], 0.5)
                      for i in range(3)], np.float64)
        tmn = c - sz * f
        tmx = tmn + sz

    ssz = smx - smn
    tsz = tmx - tmn
    if scale_to_fit:
        s = np.where(ssz > 1e-12, tsz / np.where(ssz > 1e-12, ssz, 1.0), 1.0)
        if uniform_scale:
            live = ssz > 1e-12
            # Take the smallest ratio so the whole thing fits in the target box, same as Houdini's Uniform Scale
            s = np.full(3, float(s[live].min()) if live.any() else 1.0)
    else:
        s = np.ones(3)

    off = np.asarray(offset, np.float64).reshape(3)
    t = np.zeros(3)
    for i in range(3):
        j = justify[i]
        if j == "none" or not translate:
            a = _anchor(smn, smx, "center" if j == "none" else j)[i]
            t[i] = a - a * s[i]                    # scale around its own anchor, position unchanged
            continue
        jt = justify_to[i]
        sa = _anchor(smn, smx, j)[i]
        ta = _anchor(tmn, tmx, j if jt == "same" else jt)[i]
        t[i] = ta - sa * s[i] + off[i]

    M = _mat(s, t)
    g = _apply(geo, M)
    if str(stash_attrib).strip():
        g.set(DETAIL, str(stash_attrib).strip(), M.reshape(1, 16))
    return g
