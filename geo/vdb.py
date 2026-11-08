"""
VDB semantics on top of the dense volumes (pcg106).

Volumes here are dense numpy grids (see volume.py: grid-point sampled, the end samples on the bounding-box corners,
voxels in prim_data[i]["voxels"] with shape (rz, ry, rx)). OpenVDB grids are sparse. This module adds the parts of the
VDB data model that change results, on top of the same storage, so the VDB nodes can behave like Houdini's:

  vdb         prim attribute, int. 1 = a VDB primitive, 0 / missing = a Houdini (dense) volume.
  background  prim attribute, float. The value of every inactive voxel and of everything outside the grid.
              For a narrow-band SDF it is the exterior band width (positive); for fog it is 0.
  active      prim_data[i]["active"], bool (rz, ry, rx). Missing = every voxel is active (a dense volume).
              Inactive voxels always hold the background value (SDF interior: -background) -- keeping the stored
              value in step with the mask is what lets every dense operator stay correct without knowing about masks.
  fog         prim attribute (already used by Convert / IsoOffset), the grid class:
              0 = level set (SDF, negative inside), 1 = fog volume (density, positive inside), 2 = none / other.
  vector      voxels of shape (rz, ry, rx, 3) are a vector grid (vel, Cd ...). Houdini dense volumes are scalar only;
              VDB Vector Merge / Split convert between the two forms.

What is not modelled: the tree itself (root / internal / leaf nodes, tiles). VDB Visualize Tree and VDB Diagnostics
derive the leaf layout from the mask in 8³ blocks, which is how OpenVDB's default tree (5-4-3) lays out its leaves,
so leaf counts match a real VDB of the same active topology on the same voxel grid.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_VOLUME, is_string

CLASS_SDF, CLASS_FOG, CLASS_NONE = 0, 1, 2
CLASS_NAMES = {"sdf": CLASS_SDF, "fog": CLASS_FOG, "none": CLASS_NONE}
LEAF = 8                                     # OpenVDB leaf node edge (voxels)


# ═══════════════════════════════════════════════════════════ access
def volume_prims(geo):
    return [i for i in range(geo.nprims) if geo.prim_type[i] == PRIM_VOLUME
            and geo.pdata(i, "voxels") is not None]


def _pattr(geo, name, i, default):
    a = geo.get(PRIM, name)
    if a is None or i >= len(a):
        return default
    v = a[i, 0]
    return default if v is None else v


def is_vdb(geo, i):
    return int(_pattr(geo, "vdb", i, 0)) == 1


def grid_class(geo, i):
    return int(_pattr(geo, "fog", i, 0))


def background(geo, i):
    return float(_pattr(geo, "background", i, 0.0))


def name_of(geo, i):
    a = geo.get(PRIM, "name")
    if a is None or i >= len(a) or not is_string(a):
        return ""
    return str(a[i, 0] or "")


def is_vector(vox):
    return vox is not None and np.ndim(vox) == 4


def res_of(vox):
    """(rx, ry, rz) of a voxel array (scalar or vector)."""
    return (int(vox.shape[2]), int(vox.shape[1]), int(vox.shape[0]))


def grid(geo, i):
    """(voxels, origin, cell) -- same as volume.volume_info, but also works for vector grids."""
    vox = geo.pdata(i, "voxels")
    if vox is None:
        return None
    res = geo.get(PRIM, "res")[i].astype(np.int64)
    size = geo.get(PRIM, "vsize")[i].astype(np.float64)
    ctr = geo.get(POINT, "P")[geo.prim_points(i)[0]].astype(np.float64)
    cell = size / np.maximum(res - 1, 1)
    return vox, ctr - size * 0.5, cell


def active(geo, i):
    """The active mask as a bool array; all True when there is none or it no longer fits the voxel grid."""
    vox = geo.pdata(i, "voxels")
    m = geo.pdata(i, "active")
    shp = vox.shape[:3]
    if m is None or tuple(m.shape) != tuple(shp):
        return np.ones(shp, bool)
    return m


def has_mask(geo, i):
    vox = geo.pdata(i, "voxels")
    m = geo.pdata(i, "active")
    return m is not None and tuple(m.shape) == tuple(vox.shape[:3])


def outside_value(geo, i):
    """What a sample beyond the grid reads: a VDB's background; None for a dense volume (streak = clamp to the edge)."""
    return background(geo, i) if is_vdb(geo, i) else None


def inactive_value(geo, i, vox=None):
    """Value an inactive voxel holds: the background, and for an SDF interior -background (the sign is kept)."""
    bg = background(geo, i)
    if grid_class(geo, i) == CLASS_SDF and vox is not None:
        return np.where(np.asarray(vox) < 0, -abs(bg), abs(bg))
    return bg


# ═══════════════════════════════════════════════════════════ writing
def _ensure_attr(g, name, n, default, dtype):
    a = g.get(PRIM, name)
    if a is None:
        a = np.full((n, 1), default, dtype)
    else:
        a = np.array(a, copy=True)
    return a


def set_prim_value(g, name, i, value, dtype=np.float32, default=0):
    a = _ensure_attr(g, name, g.nprims, default, dtype)
    a[i, 0] = value
    g.set(PRIM, name, a, owned=True)


def set_name(g, i, name):
    a = g.get(PRIM, "name")
    if a is None or not is_string(a):
        a = np.array([""] * g.nprims, dtype=object).reshape(-1, 1)
    else:
        a = np.array(a, dtype=object, copy=True)
    a[i, 0] = str(name)
    g.set_string(PRIM, "name", a[:, 0])


def set_class(g, i, cls):
    set_prim_value(g, "fog", i, int(cls), np.int32, 0)


def set_vdb(g, i, flag=True, bg=None):
    set_prim_value(g, "vdb", i, 1 if flag else 0, np.int32, 0)
    if bg is not None:
        set_prim_value(g, "background", i, float(bg), np.float32, 0.0)


def set_background(g, i, bg):
    set_prim_value(g, "background", i, float(bg), np.float32, 0.0)


def set_voxels(g, i, vox, mask="keep"):
    """
    Write voxels. mask: "keep" keeps the current active mask (it is dropped if the grid shape changed),
    None removes it (all active), or a bool array. When the prim is a VDB with a mask, inactive voxels are reset to
    the background so the stored values stay consistent with the mask.
    """
    vox = np.ascontiguousarray(vox, np.float32)
    g.set_pdata(i, "voxels", vox)
    rx, ry, rz = res_of(vox)
    res = g.get(PRIM, "res")
    if res is not None and tuple(int(v) for v in res[i]) != (rx, ry, rz):
        r = np.array(res, copy=True)
        r[i] = (rx, ry, rz)
        g.set(PRIM, "res", r, owned=True)
    if isinstance(mask, str) and mask == "keep":
        m = g.pdata(i, "active")
        if m is not None and tuple(m.shape) != tuple(vox.shape[:3]):
            g.prim_data[int(i)].pop("active", None)
    elif mask is None:
        g.prim_data.get(int(i), {}).pop("active", None)
    else:
        set_active(g, i, mask)
    apply_background(g, i)


def store_sdf(g, i, d, bg=None):
    """
    Write a signed-distance result into prim i (pcg108). A dense volume takes the values as they are. A VDB keeps a
    narrow band: background = bg (default: its own positive background, else 3 voxels), voxels with |d| < bg active,
    the rest inactive at ±background -- so an SDF never ends up with a background that has the wrong sign or zero.
    """
    d = np.asarray(d, np.float64)
    if not is_vdb(g, i):
        set_voxels(g, i, d, mask="keep")
        return
    if bg is None or bg <= 0:
        bg = background(g, i) if grid_class(g, i) == CLASS_SDF else 0.0
    if bg <= 0:
        _, _, cell = grid(g, i)
        bg = 3.0 * float(np.max(cell))
    set_class(g, i, CLASS_SDF)
    set_background(g, i, bg)
    set_voxels(g, i, np.clip(d, -bg, bg), mask=np.abs(d) < bg)


def set_active(g, i, mask):
    vox = g.pdata(i, "voxels")
    m = np.ascontiguousarray(np.broadcast_to(np.asarray(mask, bool), vox.shape[:3]))
    if m.all():
        g.prim_data.get(int(i), {}).pop("active", None)
    else:
        g.set_pdata(i, "active", m)
    apply_background(g, i)


def apply_background(g, i):
    """Inactive voxels := background (SDF: keeps the inside/outside sign). Only for VDB prims with a mask."""
    if not is_vdb(g, i) or not has_mask(g, i):
        return
    vox = g.pdata(i, "voxels")
    m = g.pdata(i, "active")
    if m.all():
        return
    out = np.array(vox, copy=True)
    iv = inactive_value(g, i, vox)
    if is_vector(out):
        out[~m] = float(background(g, i))
    elif np.ndim(iv):
        out[~m] = iv[~m]
    else:
        out[~m] = iv
    g.set_pdata(i, "voxels", np.ascontiguousarray(out, np.float32))


def set_center_size(g, i, center, size):
    P = np.array(g.get(POINT, "P"), np.float32, copy=True)
    P[g.prim_points(i)[0]] = center
    g.set(POINT, "P", P, owned=True)
    s = np.array(g.get(PRIM, "vsize"), np.float32, copy=True)
    s[i] = size
    g.set(PRIM, "vsize", s, owned=True)


def set_grid(g, i, origin, cell, vox):
    """Place voxels with the given origin / cell (cell may differ per axis)."""
    rx, ry, rz = res_of(vox)
    size = np.asarray(cell, np.float64) * (np.array([rx, ry, rz]) - 1)
    center = np.asarray(origin, np.float64) + size * 0.5
    set_voxels(g, i, vox, mask=None)
    set_center_size(g, i, center, size)


def grow(g, i, lo, hi):
    """
    Enlarge prim i's grid (on its own lattice, no resampling) so it covers the world box [lo, hi]. New samples are
    inactive background for a VDB (an SDF outside: +background) and repeat the edge for a dense volume (streak).
    Returns True if the grid changed.
    """
    vox, origin, cell = grid(g, i)
    rx, ry, rz = res_of(vox)
    top = origin + cell * (np.array([rx, ry, rz]) - 1)
    k0 = np.maximum(np.ceil((origin - np.asarray(lo, np.float64)) / cell - 1e-6), 0).astype(int)
    k1 = np.maximum(np.ceil((np.asarray(hi, np.float64) - top) / cell - 1e-6), 0).astype(int)
    if not (k0.any() or k1.any()):
        return False
    pad = [(k0[2], k1[2]), (k0[1], k1[1]), (k0[0], k1[0])]
    padv = pad + ([(0, 0)] if is_vector(vox) else [])
    if is_vdb(g, i):
        bg = abs(background(g, i)) if grid_class(g, i) == CLASS_SDF else background(g, i)
        new = np.pad(np.asarray(vox, np.float32), padv, constant_values=bg)
        m = np.pad(active(g, i), pad, constant_values=False)
    else:
        new = np.pad(np.asarray(vox, np.float32), padv, mode="edge")
        m = None
    norigin = origin - k0 * cell
    had = has_mask(g, i) or is_vdb(g, i)
    set_grid(g, i, norigin, cell, new)
    if had and m is not None:
        set_active(g, i, m)
    return True


def make(res, size, center=(0, 0, 0), fill=0.0, cls=CLASS_FOG, name="",
         vdb=True, background=0.0, vector=False, mask=None) -> Geometry:
    """A single volume prim (VDB by default)."""
    rx, ry, rz = [max(2, int(v)) for v in res]
    g = Geometry.from_points(np.asarray([center], np.float32))
    g.set_topology(np.zeros(1, np.int32), np.array([0, 1], np.int32),
                   np.zeros(1, bool), np.array([PRIM_VOLUME], np.uint8))
    g.set(PRIM, "res", np.array([[rx, ry, rz]], np.int32), owned=True)
    g.set(PRIM, "vsize", np.array([list(size)], np.float32), owned=True)
    g.set(PRIM, "fog", np.array([[int(cls)]], np.int32), owned=True)
    g.set(PRIM, "vdb", np.array([[1 if vdb else 0]], np.int32), owned=True)
    g.set(PRIM, "background", np.array([[float(background)]], np.float32), owned=True)
    shp = (rz, ry, rx, 3) if vector else (rz, ry, rx)
    fv = np.asarray(fill, np.float32)
    g.set_pdata(0, "voxels", np.ascontiguousarray(np.broadcast_to(fv, shp), np.float32))
    if str(name):
        g.set_string(PRIM, "name", np.array([str(name)], dtype=object))
    if mask is not None:
        set_active(g, 0, mask)
    return g


def from_grid(vox, origin, cell, cls=CLASS_FOG, name="", vdb=True, background=0.0,
              mask=None) -> Geometry:
    vox = np.asarray(vox, np.float32)
    rx, ry, rz = res_of(vox)
    cell = np.broadcast_to(np.asarray(cell, np.float64), (3,))
    size = cell * (np.array([rx, ry, rz]) - 1)
    center = np.asarray(origin, np.float64) + size * 0.5
    g = make((rx, ry, rz), size, center, 0.0, cls, name, vdb, background, is_vector(vox))
    g.set_pdata(0, "voxels", np.ascontiguousarray(vox, np.float32))
    if mask is not None:
        set_active(g, 0, mask)
    return g


def copy_prim(geo, i) -> Geometry:
    """A single-prim geometry holding prim i (attributes of that prim kept)."""
    from .ops import delete_prims
    keep = np.zeros(geo.nprims, bool)
    keep[i] = True
    return delete_prims(geo, keep)


# ═══════════════════════════════════════════════════════════ coordinates
def world_points(origin, cell, shape):
    """World positions of every sample, (rz, ry, rx, 3)."""
    rz, ry, rx = shape[:3]
    z, y, x = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx), indexing="ij")
    return np.asarray(origin) + np.stack([x, y, z], -1) * np.asarray(cell)


def to_index(origin, cell, P):
    """World -> continuous index space (x, y, z)."""
    return (np.asarray(P, np.float64) - np.asarray(origin)) / np.asarray(cell)


def sample(vox, origin, cell, Q, interp="trilinear", border="clamp", outside=None):
    """
    Sample a scalar or vector grid at world points Q (N, 3). outside: value for points outside the grid
    (None = clamp to the edge sample, like Houdini's streak border).
    """
    Q = np.asarray(Q, np.float64).reshape(-1, 3)
    if is_vector(vox):
        out = np.stack([sample(vox[..., k], origin, cell, Q, interp, border, outside)
                        for k in range(3)], -1)
        return out
    from .attribsample import sample_volume
    v, _ = sample_volume(vox, origin, cell, Q, interp, "clamp")
    v = np.asarray(v, np.float64).reshape(-1)
    if outside is not None:
        rz, ry, rx = vox.shape
        u = to_index(origin, cell, Q)
        out = ((u < -1e-6) | (u > np.array([rx - 1, ry - 1, rz - 1]) + 1e-6)).any(1)
        v[out] = outside
    return v


def grad(f, cell):
    """Central differences (one-sided at the border), returns (..., 3) in world units."""
    f = np.asarray(f, np.float64)
    return np.stack([np.gradient(f, float(cell[0]), axis=2),
                     np.gradient(f, float(cell[1]), axis=1),
                     np.gradient(f, float(cell[2]), axis=0)], -1)


def leaf_blocks(mask):
    """(bz, by, bx) bool -- which 8³ leaves contain any active voxel (the leaf layout of OpenVDB's 5-4-3 tree)."""
    rz, ry, rx = mask.shape
    pz, py, px = (-rz) % LEAF, (-ry) % LEAF, (-rx) % LEAF
    m = np.pad(mask, ((0, pz), (0, py), (0, px)))
    bz, by, bx = m.shape[0] // LEAF, m.shape[1] // LEAF, m.shape[2] // LEAF
    return m.reshape(bz, LEAF, by, LEAF, bx, LEAF).any(axis=(1, 3, 5))


def bounds(geo):
    """Bounding box (lo, hi) of a geometry, with volume prims counted by their full extent."""
    P = geo.get(POINT, "P")
    los, his = [], []
    vp = set(volume_prims(geo))
    if P is not None and len(P):
        other = np.ones(len(P), bool)
        if vp:
            for i in vp:
                other[geo.prim_points(i)] = False
            # a point shared with a non-volume prim still counts
            for i in range(geo.nprims):
                if i not in vp:
                    other[geo.prim_points(i)] = True
        if other.any():
            Q = np.asarray(P, np.float64)[other]
            los.append(Q.min(0))
            his.append(Q.max(0))
    for i in vp:
        vox, o, c = grid(geo, i)
        los.append(o)
        his.append(o + c * (np.array(res_of(vox)) - 1))
    if not los:
        z = np.zeros(3)
        return z, z
    return np.min(los, 0), np.max(his, 0)


def select(geo, spec="", allow_vector=True, need=None):
    """Volumes parameter -> prim indices (same rules as volops.select_volumes), optionally filtered."""
    from .volops import select_volumes
    out = select_volumes(geo, spec)
    if not allow_vector:
        out = [i for i in out if not is_vector(geo.pdata(i, "voxels"))]
    if need is not None:
        out = [i for i in out if need(geo, i)]
    return out


def select_class(geo, spec="", cls=CLASS_SDF, what="This node"):
    """
    Scalar volumes of one class. With an empty group the others are skipped silently (a geometry with an SDF and a
    fog works as you would expect); a group that names a volume of another class is an error.
    """
    ids = select(geo, spec, allow_vector=False)
    good = [i for i in ids if grid_class(geo, i) == cls]
    kind = {CLASS_SDF: "SDF", CLASS_FOG: "fog", CLASS_NONE: "plain"}[cls]
    if str(spec).strip() and len(good) != len(ids):
        bad = [name_of(geo, i) or f"#{i}" for i in ids if i not in good]
        raise ValueError(f"{what} needs {kind} volumes; {bad} are not")
    if not good:
        raise ValueError(f"{what}: the input has no {kind} volume")
    return good
