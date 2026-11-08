"""
VDB nodes, part 1: creation, active topology, structure (pcg106).

The storage model is in vdb.py (dense grid + active mask + background). Index coordinates here are the grid's own:
voxel (0, 0, 0) is the sample at the bounding-box minimum, not OpenVDB's world-origin-centred index space.

  VDB                    create VDB prims: from a reference bounding box (input 2) or Size / Center, at a voxel size;
                         Class SDF / Fog / None, scalar or vector; empty (no active voxels, everything = background)
                         or filled (all active)
  VDB Activate           Union / Intersect / A − B / Copy of the active region with a region: Position (world box),
                         Voxel (index box, inclusive), Expand (dilate by voxels / distance with the face / edge /
                         vertex neighbour pattern), Reference (bounding box, active voxels of reference VDBs, convex hull
                         of points, or inside an implicit surface = SDF < offset), Deactivate (values within tolerance of
                         the background) and Fill SDF (activate the interior). Union / Copy can write Value
  VDB Activate SDF       activate the narrow band |φ| ≤ half width (voxels) around the surface and give it true
                         distances (redistanced from the zero crossing); outside the band = ±background
  VDB Densify            activate everything
  VDB Prune              Value (collapse 8³ leaves whose values are within tolerance of each other: they become one
                         constant, stored at every voxel of the leaf), Inactive (deactivate leaves that are all within
                         tolerance of the background), Level Set (deactivate |φ| ≥ background, outside keeps +bg, inside −bg)
  VDB Clip               keep voxels inside (or outside) a bounding box of geometry / the active voxels of a mask VDB,
                         with padding; the rest become inactive background
  VDB Fill               set a box (index or world, or reference geometry bounds) to a value, active or inactive
  VDB Topology to SDF    the active region as a solid -> SDF with the given half band (+ dilation / closing / smoothing)
  VDB Diagnostics        checks with a report (and optional repair): finite values, background is uniform,
                         inactive voxels hold the background, SDF |∇φ| within tolerance of 1, values in a range
  VDB Visualize Tree     the leaf layout (8³ blocks holding active voxels) as wireframe boxes, active voxels as points
                         or boxes, optionally the internal-node level (128³ blocks)
  VDB Metadata           set name / class / background, transfer to attributes
  VDB Vector Merge/Split three scalar grids <-> one vector grid (Volume Vector Join / Split are the same nodes)
  VDB Transform          translate / scale exactly (moves the grid); rotation resamples into the rotated bounds
  VDB LOD                level L = every 2^L-th sample of the grid (box-filtered first), single / range / pyramid
  VDB Merge              collate by name / primitive number / all; fog: add, SDF: union / intersect, other: add
  VDB Segment            split into connected components (SDF: interior pieces, fog / other: active non-background)
  VDB Remap              input range -> output range through a ramp, with clamp / preserve / extrapolate at the ends
  Convert VDB            VDB <-> Houdini volume, fog <-> SDF, to polygons (closed iso-surface)
"""
from __future__ import annotations

import fnmatch

import numpy as np

from .core import DETAIL, POINT, PRIM, Geometry
from . import vdb as _v

ACTIVATE_OPS = ("union", "intersect", "subtract", "copy")
ACTIVATE_REGIONS = ("position", "voxel", "expand", "reference", "deactivate", "fillsdf")
EXPAND_PATTERNS = ("face", "faceedge", "faceedgevertex")
PRUNE_MODES = ("value", "inactive", "levelset")
CLIP_MODES = ("geometry", "mask", "camera")
FILL_MODES = ("index", "world", "geom")
LOD_MODES = ("single", "range", "mipmaps")
MERGE_COLLATION = ("name", "primitive_number", "all")
REMAP_ENDS = ("clamp", "preserve", "extrapolate")
CONVERT_TO = ("volume", "vdb", "polygons", "sdf", "fog")
CLASS_MENU = ("sdf", "fog", "none")


def _scipy_ndimage():
    try:
        from scipy import ndimage
    except ImportError as e:                       # ComfyUI ships scipy; this is only for odd installs
        raise RuntimeError("This VDB node needs scipy (pip install scipy)") from e
    return ndimage


def _report_names(g, ids):
    return [_v.name_of(g, i) or f"#{i}" for i in ids]


# ═══════════════════════════════════════════════════════════ VDB (create)
def create(name="density", cls="fog", vector=False, voxel_size=0.1, background=None,
           size=(1.0, 1.0, 1.0), center=(0.0, 0.0, 0.0), reference=None, padding=0.0,
           fill=False, value=0.0):
    """
    New VDB prim. The grid covers the reference geometry's bounding box (+ padding) or Size / Center, at Voxel Size
    (voxels are cubes; the extent is rounded up to whole voxels). background None: 0 for fog / none,
    3 voxels for SDF (OpenVDB's default half band). fill: every voxel active with Value; otherwise the VDB is empty
    (no active voxels) and every voxel holds the background, like Houdini's VDB node.
    """
    if cls not in CLASS_MENU:
        raise ValueError(f"Class must be one of {CLASS_MENU}")
    vs = float(voxel_size)
    if vs <= 0:
        raise ValueError("Voxel Size must be greater than 0")
    if reference is not None and reference.npoints:
        lo, hi = _v.bounds(reference)
        lo, hi = lo - float(padding), hi + float(padding)
    else:
        c = np.asarray(center, np.float64)
        s = np.maximum(np.asarray(size, np.float64), vs)
        lo, hi = c - s / 2 - float(padding), c + s / 2 + float(padding)
    n = np.maximum(np.ceil((hi - lo) / vs - 1e-9).astype(int) + 1, 2)
    ext = (n - 1) * vs
    ctr = (lo + hi) / 2
    k = _v.CLASS_NAMES[cls]
    bg = (3.0 * vs if k == _v.CLASS_SDF else 0.0) if background is None else float(background)
    if fill:
        v = value
        mask = None
    else:
        v = bg
        mask = np.zeros((n[2], n[1], n[0]), bool)
    g = _v.make(n, ext, ctr, v, k, name, True, bg, bool(vector))
    if mask is not None:
        _v.set_active(g, 0, mask)
    return g


# ═══════════════════════════════════════════════════════════ morphology on masks
def _structure(pattern):
    nd = _scipy_ndimage()
    conn = {"face": 1, "faceedge": 2, "faceedgevertex": 3}[pattern]
    return nd.generate_binary_structure(3, conn)


def dilate_mask(mask, n, pattern="face"):
    if n <= 0:
        return mask
    nd = _scipy_ndimage()
    return nd.binary_dilation(mask, _structure(pattern), iterations=int(n))


def erode_mask(mask, n, pattern="face"):
    if n <= 0:
        return mask
    nd = _scipy_ndimage()
    return nd.binary_erosion(mask, _structure(pattern), iterations=int(n), border_value=0)


# ═══════════════════════════════════════════════════════════ VDB Activate
def _region_box_world(origin, cell, shape, lo, hi):
    """Voxels whose cell (sample ± half voxel) touches the world box [lo, hi]."""
    P = _v.world_points(origin, cell, shape)
    h = np.asarray(cell) * 0.5
    return ((P + h >= lo) & (P - h <= hi)).all(-1)


def _convex_hull_inside(P, Q, offset):
    """Points Q inside the convex hull of P (expanded by offset)."""
    try:
        from scipy.spatial import ConvexHull
    except ImportError as e:
        raise RuntimeError("Activate Using Convex Hull needs scipy") from e
    hull = ConvexHull(np.asarray(P, np.float64))
    eq = hull.equations                                   # n·x + d <= 0 inside, |n| = 1
    return (Q @ eq[:, :3].T + eq[:, 3] <= float(offset) + 1e-12).all(1)


def activate(geo, group="", operation="union", region="position", set_value=True,
             value=1.0, center=(0, 0, 0), size=(0, 0, 0), vmin=(0, 0, 0), vmax=(0, 0, 0),
             expand=1, expand_dist=0.0, pattern="face", reference=None, bound_group="",
             use_vdb=False, use_hull=False, use_implicit=False, voxel_offset=0.0,
             world_offset=0.0, bg_tolerance=0.0, prune=False, prune_tolerance=0.0):
    if operation not in ACTIVATE_OPS:
        raise ValueError(f"Operation must be one of {ACTIVATE_OPS}")
    if region not in ACTIVATE_REGIONS:
        raise ValueError(f"Region Type must be one of {ACTIVATE_REGIONS}")
    g = geo.copy()
    sel = _v.select(geo, group)
    counts = []
    for i in sel:
        vox, origin, cell = _v.grid(geo, i)
        shp = vox.shape[:3]
        act = _v.active(geo, i).copy()
        vals = np.array(vox, np.float32, copy=True)
        if region in ("expand", "deactivate", "fillsdf"):
            if region == "expand":
                nvox = int(expand)
                if float(expand_dist) > 0:
                    nvox = max(nvox, int(np.ceil(float(expand_dist) / float(np.min(cell)) - 1e-9)))
                new = dilate_mask(act, nvox, pattern)
                # newly active voxels keep their (background) values
                act = new
            elif region == "deactivate":
                bg = _v.background(geo, i)
                if _v.is_vector(vals):
                    near = (np.abs(vals - bg) <= float(bg_tolerance)).all(-1)
                else:
                    near = np.abs(vals - (_v.inactive_value(geo, i, vals) if _v.grid_class(geo, i) == _v.CLASS_SDF
                                          else bg)) <= float(bg_tolerance)
                act = act & ~near
            else:                                          # fill SDF: interior becomes active, −background
                if _v.grid_class(geo, i) != _v.CLASS_SDF or _v.is_vector(vals):
                    raise ValueError("Fill SDF needs a scalar SDF VDB")
                inside = vals < 0
                newly = inside & ~act
                vals[newly] = -abs(_v.background(geo, i))
                act = act | inside
            _v.set_voxels(g, i, vals, mask=None)
            if not _v.is_vdb(g, i):
                _v.set_vdb(g, i, True)
            _v.set_active(g, i, act)
            counts.append(int(act.sum()))
            continue

        if region == "position":
            c = np.asarray(center, np.float64)
            s = np.abs(np.asarray(size, np.float64))
            reg = _region_box_world(origin, cell, shp, c - s / 2, c + s / 2)
        elif region == "voxel":
            lo = np.minimum(np.asarray(vmin, int), np.asarray(vmax, int))
            hi = np.maximum(np.asarray(vmin, int), np.asarray(vmax, int))
            reg = np.zeros(shp, bool)
            z0, z1 = max(lo[2], 0), min(hi[2], shp[0] - 1)
            y0, y1 = max(lo[1], 0), min(hi[1], shp[1] - 1)
            x0, x1 = max(lo[0], 0), min(hi[0], shp[2] - 1)
            if z0 <= z1 and y0 <= y1 and x0 <= x1:
                reg[z0:z1 + 1, y0:y1 + 1, x0:x1 + 1] = True
        else:                                              # reference
            if reference is None:
                raise ValueError("Region Type Reference needs geometry in the second input")
            reg = _reference_region(reference, bound_group, origin, cell, shp, use_vdb,
                                    use_hull, use_implicit, voxel_offset, world_offset)
        if operation == "union":
            if set_value:
                if _v.is_vector(vals):
                    vals[reg] = float(value)
                else:
                    vals[reg] = float(value)
            act = act | reg
        elif operation == "intersect":
            act = act & reg
        elif operation == "subtract":
            act = act & ~reg
        else:
            if set_value:
                vals[reg] = float(value)
            act = reg.copy()
        _v.set_voxels(g, i, vals, mask=None)
        if not _v.is_vdb(g, i):
            _v.set_vdb(g, i, True)
        _v.set_active(g, i, act)
        counts.append(int(act.sum()))
    if prune:
        g, _ = prune_vdb(g, group, "value", prune_tolerance)
    return g, {"volumes": _report_names(g, sel), "active_voxels": counts}


def _reference_region(ref, bound_group, origin, cell, shp, use_vdb, use_hull, use_implicit,
                      voxel_offset, world_offset):
    P = _v.world_points(origin, cell, shp).reshape(-1, 3)
    off = float(world_offset) + float(voxel_offset) * float(np.min(cell))
    reg = np.zeros(int(np.prod(shp)), bool)
    any_mode = False
    rv = _v.volume_prims(ref)
    if bound_group.strip() and rv:
        rv = _v.select(ref, bound_group)
    if use_vdb:
        any_mode = True
        for j in rv:
            vb, ob, cb = _v.grid(ref, j)
            a = _v.active(ref, j).astype(np.float32)
            s = _v.sample(a, ob, cb, P, "nearest", outside=0.0)
            reg |= s > 0.5
    if use_implicit:
        any_mode = True
        for j in rv:
            vb, ob, cb = _v.grid(ref, j)
            if _v.is_vector(vb):
                continue
            s = _v.sample(vb, ob, cb, P, outside=None)
            if _v.grid_class(ref, j) == _v.CLASS_FOG:
                reg |= s > 0.5 - off
            else:
                reg |= s <= off
    if use_hull:
        any_mode = True
        Pr = np.asarray(ref.get(POINT, "P"), np.float64)
        if len(Pr) >= 4:
            reg |= _convex_hull_inside(Pr, P, off)
    if not any_mode:
        lo, hi = _v.bounds(ref)
        reg |= ((P >= lo - off - 1e-9) & (P <= hi + off + 1e-9)).all(1)
    return reg.reshape(shp)


# ═══════════════════════════════════════════════════════════ Activate SDF / Densify / Prune
def activate_sdf(geo, group="", half_width=3.0):
    """Narrow band of the given half width (voxels) around φ = 0 becomes active with true distances."""
    from .volops import redistance
    g = geo.copy()
    hw = float(half_width)
    if hw <= 0:
        raise ValueError("Half-Width must be greater than 0")
    rep = []
    for i in _v.select_class(geo, group, _v.CLASS_SDF, "VDB Activate SDF"):
        vox, origin, cell = _v.grid(geo, i)
        d = redistance(np.asarray(vox, np.float64), origin, cell)
        band = hw * float(np.min(cell))
        act = np.abs(d) <= band
        d = np.clip(d, -band, band)
        _v.set_vdb(g, i, True, bg=band)
        _v.set_voxels(g, i, d, mask=None)
        _v.set_active(g, i, act)
        rep.append(int(act.sum()))
    return g, {"active_voxels": rep}


def densify(geo, group=""):
    g = geo.copy()
    for i in _v.select(geo, group):
        _v.set_voxels(g, i, g.pdata(i, "voxels"), mask=None)
    return g


def prune_vdb(geo, group="", mode="value", tolerance=0.0):
    if mode not in PRUNE_MODES:
        raise ValueError(f"Mode must be one of {PRUNE_MODES}")
    tol = float(tolerance)
    g = geo.copy()
    rep = []
    for i in _v.select(geo, group):
        vox = np.array(g.pdata(i, "voxels"), np.float32, copy=True)
        act = _v.active(g, i).copy()
        bg = _v.background(g, i)
        if mode == "levelset":
            if _v.grid_class(g, i) != _v.CLASS_SDF or _v.is_vector(vox):
                raise ValueError("Level Set pruning needs a scalar SDF")
            out = np.abs(vox) >= abs(bg) - tol
            act &= ~out
            vox[out] = np.where(vox[out] < 0, -abs(bg), abs(bg))
        else:
            L = _v.LEAF
            rz, ry, rx = vox.shape[:3]
            n = 0
            for z in range(0, rz, L):
                for y in range(0, ry, L):
                    for x in range(0, rx, L):
                        blk = vox[z:z + L, y:y + L, x:x + L]
                        if mode == "value":
                            if np.ptp(blk, axis=(0, 1, 2)).max() <= tol:
                                m = blk.reshape(-1, *blk.shape[3:]).mean(0)
                                vox[z:z + L, y:y + L, x:x + L] = m
                                n += 1
                        else:
                            if (np.abs(blk - bg) <= tol).all():
                                act[z:z + L, y:y + L, x:x + L] = False
                                n += 1
            rep.append(n)
        _v.set_voxels(g, i, vox, mask=None)
        if _v.is_vdb(g, i):
            _v.set_active(g, i, act)
    return g, {"mode": mode, "collapsed_leaves": rep}


# ═══════════════════════════════════════════════════════════ Clip / Fill
def in_frustum(cam, P, pad=0.0):
    """(n,) bool: points inside the camera's view frustum (near / far planes, frame edges), grown by pad (world)."""
    d = np.asarray(P, np.float64) - np.asarray(cam["eye"], np.float64)
    x, y, z = d @ np.asarray(cam["right"]), d @ np.asarray(cam["up"]), d @ np.asarray(cam["forward"])
    aspect = float(cam["xres"]) / float(cam["yres"])
    if cam.get("projection") == "orthographic":
        hy = np.full(len(z), float(cam["ortho_size"]) * 0.5)
    else:
        hy = np.maximum(z, 0.0) * np.tan(np.radians(float(cam["fov"]) * 0.5))
    ok = (np.abs(x) <= hy * aspect + pad) & (np.abs(y) <= hy + pad)
    ok &= z >= float(cam.get("near", 0.0)) - pad
    if float(cam.get("far", 0.0) or 0.0) > 0:
        ok &= z <= float(cam["far"]) + pad
    return ok


def clip(geo, group="", inside=True, clipper="geometry", reference=None, mask="",
         padding=0.0, camera=None):
    if clipper not in CLIP_MODES:
        raise ValueError(f"Clip To must be one of {CLIP_MODES}")
    if clipper == "camera" and camera is None:
        raise ValueError("VDB Clip with Clip To = camera needs a camera in the camera input")
    if clipper != "camera" and reference is None:
        raise ValueError("VDB Clip needs the clipping geometry / mask VDB in the second input")
    g = geo.copy()
    rep = []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        P = _v.world_points(origin, cell, vox.shape[:3]).reshape(-1, 3)
        pad = float(padding)
        if clipper == "camera":
            reg = in_frustum(camera, P, pad)
        elif clipper == "geometry":
            lo, hi = _v.bounds(reference)
            reg = ((P >= lo - pad - 1e-9) & (P <= hi + pad + 1e-9)).all(1)
        else:
            mv = _v.volume_prims(reference)
            if mask.strip():
                mv = _v.select(reference, mask)
            if not mv:
                raise ValueError("Mask VDB: the second input has no volume")
            vb, ob, cb = _v.grid(reference, mv[0])
            a = _v.active(reference, mv[0]).astype(np.float32)
            if pad > 0:
                a = dilate_mask(a > 0.5, int(np.ceil(pad / float(np.min(cb))))).astype(np.float32)
            reg = _v.sample(a, ob, cb, P, "nearest", outside=0.0) > 0.5
        reg = reg.reshape(vox.shape[:3])
        keep = reg if inside else ~reg
        act = _v.active(geo, i) & keep
        if not _v.is_vdb(g, i):
            _v.set_vdb(g, i, True)
        if _v.grid_class(g, i) == _v.CLASS_SDF and not _v.is_vector(vox):
            # pcg108: what the clip removes becomes background, i.e. *outside* for a level set (as OpenVDB's clip
            # does). Keeping the sign there left the cut-away interior "inside", so nothing was cut off.
            v = np.array(vox, np.float32, copy=True)
            v[~keep] = abs(_v.background(g, i))
            g.set_pdata(i, "voxels", v)
        _v.set_active(g, i, act)
        rep.append(int(act.sum()))
    return g, {"active_voxels": rep}


def fill(geo, group="", mode="index", vmin=(0, 0, 0), vmax=(0, 0, 0), wmin=(0, 0, 0),
         wmax=(0, 0, 0), value=(0, 0, 0), active=True, reference=None):
    if mode not in FILL_MODES:
        raise ValueError(f"Bounds must be one of {FILL_MODES}")
    g = geo.copy()
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        shp = vox.shape[:3]
        if mode == "index":
            lo = np.minimum(vmin, vmax).astype(int)
            hi = np.maximum(vmin, vmax).astype(int)
            reg = np.zeros(shp, bool)
            sl = tuple(slice(max(int(lo[a]), 0), max(min(int(hi[a]), shp[2 - a] - 1) + 1, 0))
                       for a in (2, 1, 0))
            reg[sl] = True
        else:
            if mode == "geom":
                if reference is None:
                    raise ValueError("Bounds = Reference Geometry needs the second input")
                lo, hi = _v.bounds(reference)
            else:
                lo = np.minimum(wmin, wmax)
                hi = np.maximum(wmin, wmax)
            P = _v.world_points(origin, cell, shp)
            reg = ((P >= np.asarray(lo) - 1e-9) & (P <= np.asarray(hi) + 1e-9)).all(-1)
        vals = np.array(vox, np.float32, copy=True)
        val = np.asarray(value, np.float32)
        vals[reg] = val if _v.is_vector(vals) else val.reshape(-1)[0]
        act = _v.active(geo, i).copy()
        if active:
            act |= reg
        else:
            act &= ~reg
        _v.set_voxels(g, i, vals, mask=None)
        if not _v.is_vdb(g, i):
            _v.set_vdb(g, i, True)
        _v.set_active(g, i, act)
        if not active:
            # deactivated voxels take the background (that is what inactive means)
            _v.apply_background(g, i)
    return g


# ═══════════════════════════════════════════════════════════ Topology to SDF
def topology_to_sdf(geo, group="", half_band=3.0, world_band=None, dilation=0, closing=1,
                    smoothing=0, output_name="keep", custom_name=""):
    """
    The active region is treated as a solid: an SDF whose zero crossing lies half a voxel outside the outermost
    active samples (the solid's faces between active and inactive samples), via exact Euclidean distance transforms
    of the solid and its complement. Dilation / closing (dilate then erode) in voxels first; smoothing = mean
    curvature-ish smoothing passes (Laplacian of the SDF, followed by redistancing).
    """
    nd = _scipy_ndimage()
    from .volops import redistance
    out = Geometry()
    parts = []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        m = _v.active(geo, i).copy()
        m = dilate_mask(m, int(dilation))
        if int(closing) > 0:
            m = erode_mask(dilate_mask(m, int(closing)), int(closing))
        pad = 2
        mp = np.pad(m, pad)
        samp = np.asarray(cell)[::-1]
        d_out = nd.distance_transform_edt(~mp, sampling=samp)
        d_in = nd.distance_transform_edt(mp, sampling=samp)
        h = 0.5 * float(np.min(cell))
        f = np.where(mp, -(d_in - h), d_out - h)[pad:-pad, pad:-pad, pad:-pad]
        for _ in range(int(smoothing)):
            f = nd.uniform_filter(f, 3, mode="nearest")
            f = redistance(f, origin, cell)
        band = (float(world_band) if world_band is not None else float(half_band) * float(np.min(cell)))
        act = np.abs(f) <= band
        f = np.clip(f, -band, band)
        nm = _v.name_of(geo, i)
        if output_name == "append":
            nm = nm + str(custom_name)
        elif output_name == "replace":
            nm = str(custom_name)
        parts.append(_v.from_grid(f, origin, cell, _v.CLASS_SDF, nm, True, band, act))
    if not parts:
        return out
    from .ops import merge
    return merge(*parts) if len(parts) > 1 else parts[0]


# ═══════════════════════════════════════════════════════════ Diagnostics
DIAG_TESTS = ("finite", "background", "inactive", "gradient", "range")


def diagnostics(geo, group="", tests=("finite", "background", "inactive", "gradient"),
                grad_tol=0.2, vmin=0.0, vmax=1.0,
                repair=False, mark=False):
    """
    Runs the selected tests on each VDB; returns (geometry, report). repair: non-finite -> background,
    inactive voxels -> background, values clamped into the range. mark: adds a fog VDB "<name>_bad" that is 1 at failing voxels.
    """
    g = geo.copy()
    rows = []
    marks = []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        act = _v.active(geo, i)
        bg = _v.background(geo, i)
        bad = np.zeros(vox.shape[:3], bool)
        res = {"volume": _v.name_of(geo, i) or f"#{i}"}
        vals = np.array(vox, np.float32, copy=True)
        sc = vals if not _v.is_vector(vals) else np.linalg.norm(vals, axis=-1)
        if "finite" in tests:
            nf = ~np.isfinite(vals) if not _v.is_vector(vals) else ~np.isfinite(vals).all(-1)
            res["non_finite"] = int(nf.sum())
            bad |= nf
            if repair:
                vals[nf] = bg
        if "background" in tests:
            res["background"] = bg
            res["background_ok"] = bool(np.isfinite(bg))
        if "inactive" in tests:
            iv = _v.inactive_value(geo, i, vals)
            if _v.is_vector(vals):
                wrong = (~act) & (np.abs(vals - bg) > 1e-6).any(-1)
            else:
                wrong = (~act) & (np.abs(vals - iv) > 1e-6)
            res["inactive_not_background"] = int(wrong.sum())
            bad |= wrong
        if "gradient" in tests and _v.grid_class(geo, i) == _v.CLASS_SDF and not _v.is_vector(vals):
            gr = np.linalg.norm(_v.grad(sc, cell), axis=-1)
            band = act & (np.abs(sc) < abs(bg) - float(np.min(cell)))
            off = band & (np.abs(gr - 1.0) > float(grad_tol))
            res["gradient_off"] = int(off.sum())
            res["gradient_checked"] = int(band.sum())
            bad |= off
        if "range" in tests:
            oor = act & ((sc < float(vmin)) | (sc > float(vmax)))
            res["out_of_range"] = int(oor.sum())
            bad |= oor
            if repair and not _v.is_vector(vals):
                vals = np.where(act, np.clip(vals, float(vmin), float(vmax)), vals)
        res["failed_voxels"] = int(bad.sum())
        res["passed"] = res["failed_voxels"] == 0
        rows.append(res)
        if repair:
            _v.set_voxels(g, i, vals, mask="keep")
        if mark:
            marks.append(_v.from_grid(bad.astype(np.float32), origin, cell, _v.CLASS_FOG,
                                      (res["volume"] + "_bad"), True, 0.0))
    if marks:
        from .ops import merge
        g = merge(g, *marks)
    return g, {"volumes": rows, "all_passed": all(r["passed"] for r in rows)}


# ═══════════════════════════════════════════════════════════ Visualize Tree
TREE_DRAW = ("none", "boxes", "points")


def visualize_tree(geo, group="", leaves="boxes", internal="none", voxels="none",
                   bbox=True, keep=False):
    """
    Leaf nodes (8³ blocks that hold an active voxel) and internal nodes (128³ blocks, OpenVDB's level-1 node) as
    wireframe boxes or points at their centres; active voxels as boxes or points. Each part gets a prim / point
    group (leaves, internal, voxels, bbox) and a Cd colour like Houdini (leaves light blue, internal green, voxels yellow).
    """
    from .build import box as _box
    from .ops import merge
    parts = [geo] if keep else []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        act = _v.active(geo, i)
        cell = np.asarray(cell)

        def blocks(edge, kind, col, name):
            if kind == "none":
                return
            L = edge
            rz, ry, rx = act.shape
            pz, py, px = (-rz) % L, (-ry) % L, (-rx) % L
            m = np.pad(act, ((0, pz), (0, py), (0, px)))
            bz, by, bx = m.shape[0] // L, m.shape[1] // L, m.shape[2] // L
            occ = m.reshape(bz, L, by, L, bx, L).any(axis=(1, 3, 5))
            kz, ky, kx = np.nonzero(occ)
            if not len(kz):
                return
            lo = origin + (np.stack([kx, ky, kz], 1) * L - 0.5) * cell
            hi = lo + L * cell
            parts.append(_boxes(lo, hi, kind, col, name))

        blocks(8, leaves, (0.45, 0.7, 1.0), "leaves")
        blocks(128, internal, (0.4, 0.85, 0.45), "internal")
        if voxels != "none":
            kz, ky, kx = np.nonzero(act)
            P = origin + np.stack([kx, ky, kz], 1) * cell
            parts.append(_boxes(P - cell / 2, P + cell / 2, voxels, (1.0, 0.85, 0.3), "voxels"))
        if bbox:
            rx, ry, rz = _v.res_of(vox)
            lo = origin - cell / 2
            hi = origin + (np.array([rx, ry, rz]) - 0.5) * cell
            parts.append(_boxes(lo[None], hi[None], "boxes", (0.75, 0.75, 0.78), "bbox"))
    parts = [p for p in parts if p is not None and (p.npoints or p.nprims)]
    if not parts:
        return Geometry()
    return merge(*parts) if len(parts) > 1 else parts[0]


def _boxes(lo, hi, kind, col, name):
    lo = np.asarray(lo, np.float64)
    hi = np.asarray(hi, np.float64)
    n = len(lo)
    if kind == "points":
        g = Geometry.from_points(((lo + hi) / 2).astype(np.float32))
        g.set(POINT, "Cd", np.tile(np.asarray(col, np.float32), (n, 1)), owned=True)
        g.set_group(POINT, name, np.ones(n, bool))
        return g
    # 12 edges per box as open 2-point polylines (wireframe, like Houdini's tree display)
    corners = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], np.float64)
    E = np.array([[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4],
                  [0, 4], [1, 5], [2, 6], [3, 7]], np.int32)
    P = lo[:, None, :] + corners[None] * (hi - lo)[:, None, :]
    P = P.reshape(-1, 3)
    vp = (E[None] + (np.arange(n) * 8)[:, None, None]).reshape(-1)
    nprim = n * 12
    g = Geometry.from_points(P.astype(np.float32))
    g.set_topology(vp.astype(np.int32), np.arange(0, nprim * 2 + 1, 2, dtype=np.int32),
                   np.zeros(nprim, bool), np.zeros(nprim, np.uint8))
    g.set(POINT, "Cd", np.tile(np.asarray(col, np.float32), (len(P), 1)), owned=True)
    g.set_group(PRIM, name, np.ones(nprim, bool))
    return g


# ═══════════════════════════════════════════════════════════ Metadata
def metadata(geo, group="", set_name=False, name="", set_class=False, cls="fog",
             set_background=False, background=0.0, set_vdb=False, vdb=True):
    g = geo.copy()
    for i in _v.select(geo, group):
        if set_name:
            _v.set_name(g, i, name)
        if set_class:
            if cls not in CLASS_MENU:
                raise ValueError(f"Class must be one of {CLASS_MENU}")
            _v.set_class(g, i, _v.CLASS_NAMES[cls])
        if set_vdb:
            _v.set_vdb(g, i, bool(vdb))
        if set_background:
            _v.set_background(g, i, float(background))
            _v.apply_background(g, i)
    return g


# ═══════════════════════════════════════════════════════════ Vector merge / split
def _match_pattern(names, pat):
    pat = str(pat).strip()
    if pat.startswith("@name="):
        pat = pat[len("@name="):]
    out = []
    for k, n in enumerate(names):
        if any(fnmatch.fnmatchcase(n, p) for p in pat.split()):
            out.append(k)
    return out


def vector_merge(geo, xgroup="*.x", ygroup="*.y", zgroup="*.z", use_basename=True,
                 merge_name="merged#", remove_sources=True):
    """
    Pairs the x / y / z scalar grids (by base name when the patterns are of the form *.x, else in order) into
    vector grids on the x grid's sample grid; y / z are resampled if their grids differ. Missing components are 0.
    """
    vp = _v.volume_prims(geo)
    names = [_v.name_of(geo, i) for i in vp]
    xs = [vp[k] for k in _match_pattern(names, xgroup)]
    ys = [vp[k] for k in _match_pattern(names, ygroup)]
    zs = [vp[k] for k in _match_pattern(names, zgroup)]
    if not xs:
        raise ValueError(f"No scalar volume matches X Group '{xgroup}'")

    def base(i):
        n = _v.name_of(geo, i)
        return n.rsplit(".", 1)[0] if "." in n else n

    used = set()
    parts = []
    for k, ix in enumerate(xs):
        b = base(ix)
        iy = next((j for j in ys if base(j) == b), ys[k] if k < len(ys) else None)
        iz = next((j for j in zs if base(j) == b), zs[k] if k < len(zs) else None)
        vx, ox, cx = _v.grid(geo, ix)
        P = _v.world_points(ox, cx, vx.shape).reshape(-1, 3)
        comps = [np.asarray(vx, np.float32)]
        for j in (iy, iz):
            if j is None:
                comps.append(np.zeros_like(vx, np.float32))
                continue
            vj, oj, cj = _v.grid(geo, j)
            if vj.shape == vx.shape and np.allclose(oj, ox) and np.allclose(cj, cx):
                comps.append(np.asarray(vj, np.float32))
            else:
                comps.append(_v.sample(vj, oj, cj, P).reshape(vx.shape).astype(np.float32))
        vec = np.stack(comps, -1)
        nm = b if (use_basename and b) else str(merge_name).replace("#", str(k + 1))
        act = _v.active(geo, ix)
        for j in (iy, iz):
            if j is not None and _v.has_mask(geo, j) and _v.grid(geo, j)[0].shape == vx.shape:
                act = act | _v.active(geo, j)
        parts.append(_v.from_grid(vec, ox, cx, _v.CLASS_NONE, nm, _v.is_vdb(geo, ix),
                                  _v.background(geo, ix), act if _v.has_mask(geo, ix) else None))
        used.update(j for j in (ix, iy, iz) if j is not None)
    from .ops import merge, delete_prims
    keep = np.ones(geo.nprims, bool)
    if remove_sources:
        keep[list(used)] = False
    base_geo = delete_prims(geo, keep) if not keep.all() else geo
    return merge(base_geo, *parts) if (base_geo.npoints or base_geo.nprims) else (
        merge(*parts) if len(parts) > 1 else parts[0])


def vector_split(geo, group="", keep_source=False):
    vp = _v.select(geo, group)
    from .ops import merge, delete_prims
    parts = []
    used = []
    for i in vp:
        vox, origin, cell = _v.grid(geo, i)
        if not _v.is_vector(vox):
            continue
        n = _v.name_of(geo, i) or "vector"
        for k, s in enumerate(("x", "y", "z", "w")[:vox.shape[3]]):
            parts.append(_v.from_grid(vox[..., k], origin, cell, _v.CLASS_NONE, f"{n}.{s}",
                                      _v.is_vdb(geo, i), _v.background(geo, i),
                                      _v.active(geo, i) if _v.has_mask(geo, i) else None))
        used.append(i)
    if not used:
        return geo.copy()
    keep = np.ones(geo.nprims, bool)
    if not keep_source:
        keep[used] = False
    base = delete_prims(geo, keep) if not keep.all() else geo
    if base.nprims or base.npoints:
        return merge(base, *parts)
    return merge(*parts) if len(parts) > 1 else parts[0]


# ═══════════════════════════════════════════════════════════ Transform
def transform(geo, group="", translate=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1),
              uniform_scale=1.0, pivot=(0, 0, 0), invert=False, xform_vectors=False):
    """
    Grids here are axis-aligned. Translation and scale (also non-uniform) move / stretch the grid exactly
    (no resampling). With a rotation the grid is resampled into the axis-aligned bounds of the rotated grid at the
    same voxel size (trilinear); vector values are rotated too when Transform Vectors is on.
    Order: scale, rotate (XYZ), translate, about the pivot.
    """
    from .ops import euler_matrix
    S = np.asarray(scale, np.float64) * float(uniform_scale)
    if np.any(np.abs(S) < 1e-12):
        raise ValueError("Scale cannot be 0")
    R = (np.asarray(euler_matrix(*[float(a) for a in rotate], "xyz"), np.float64).T
         if np.any(rotate) else np.eye(3))
    t = np.asarray(translate, np.float64)
    pv = np.asarray(pivot, np.float64)
    # row-vector convention p' = ((p - pv) * S) @ R + pv + t
    M = np.diag(S) @ R

    def fwd(p):
        return (p - pv) @ M + pv + t

    def inv(p):
        return (p - pv - t) @ np.linalg.inv(M) + pv
    if invert:
        fwd, inv = inv, fwd
    g = geo.copy()
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        rx, ry, rz = _v.res_of(vox)
        hi = origin + cell * (np.array([rx, ry, rz]) - 1)
        if not np.any(rotate):
            a, b = fwd(origin[None])[0], fwd(hi[None])[0]
            lo, up = np.minimum(a, b), np.maximum(a, b)
            flip = [bool(a[k] > b[k]) for k in range(3)]
            v2 = np.asarray(vox)
            for k, f in enumerate(flip):
                if f:
                    v2 = np.flip(v2, axis=2 - k)
            if xform_vectors and _v.is_vector(v2):
                v2 = v2 @ (np.diag(S) if not invert else np.linalg.inv(np.diag(S)))
            _v.set_voxels(g, i, v2, mask=None)
            if _v.has_mask(geo, i):
                m = _v.active(geo, i)
                for k, f in enumerate(flip):
                    if f:
                        m = np.flip(m, axis=2 - k)
                _v.set_active(g, i, m)
            _v.set_center_size(g, i, (lo + up) / 2, up - lo)
            continue
        corners = np.array([[x, y, z] for x in (origin[0], hi[0]) for y in (origin[1], hi[1])
                            for z in (origin[2], hi[2])])
        wc = fwd(corners)
        lo, up = wc.min(0), wc.max(0)
        vs = float(np.min(cell)) * float(np.min(np.abs(S)))
        n = np.maximum(np.ceil((up - lo) / vs - 1e-9).astype(int) + 1, 2)
        nc = (up - lo) / np.maximum(n - 1, 1)
        Q = _v.world_points(lo, nc, (n[2], n[1], n[0])).reshape(-1, 3)
        src = inv(Q)
        out = _v.sample(vox, origin, cell, src, outside=_v.outside_value(geo, i))
        if xform_vectors and _v.is_vector(vox):
            out = out @ (M if not invert else np.linalg.inv(M))
        out = out.reshape((n[2], n[1], n[0]) + vox.shape[3:])
        act = None
        if _v.has_mask(geo, i):
            act = _v.sample(_v.active(geo, i).astype(np.float32), origin, cell, src, "nearest",
                            outside=0.0).reshape(n[2], n[1], n[0]) > 0.5
        else:
            u = _v.to_index(origin, cell, src)
            act = ((u >= -1e-6) & (u <= np.array([rx, ry, rz]) - 1 + 1e-6)).all(1).reshape(
                n[2], n[1], n[0])
            if act.all():
                act = None
        _v.set_voxels(g, i, out, mask=None)
        _v.set_center_size(g, i, (lo + up) / 2, up - lo)
        if act is not None:
            if not _v.is_vdb(g, i):
                _v.set_vdb(g, i, True)
            _v.set_active(g, i, act)
    return g


# ═══════════════════════════════════════════════════════════ LOD
def _lod_level(vox, origin, cell, act, level):
    """Level L: box-filter by 2^L (average over the block) then keep every 2^L-th sample."""
    f = 2 ** int(level)
    if f == 1:
        return vox, origin, cell, act
    nd = _scipy_ndimage()
    if _v.is_vector(vox):
        sm = np.stack([nd.uniform_filter(vox[..., k], f, mode="nearest") for k in range(vox.shape[3])], -1)
    else:
        sm = nd.uniform_filter(np.asarray(vox, np.float64), f, mode="nearest")
    out = sm[::f, ::f, ::f]
    a = None if act is None else dilate_mask(act, f // 2)[::f, ::f, ::f]
    if min(out.shape[:3]) < 2:
        raise ValueError(f"Level {level} would leave fewer than 2 samples along an axis")
    return out, origin, np.asarray(cell) * f, a


def lod(geo, group="", mode="single", level=1.0, lrange=(0, 2, 1), count=2, reuse_name=False):
    if mode not in LOD_MODES:
        raise ValueError(f"LOD Mode must be one of {LOD_MODES}")
    if mode == "single":
        levels = [int(round(float(level)))]
    elif mode == "range":
        a, b, s = int(lrange[0]), int(lrange[1]), max(1, int(lrange[2]))
        levels = list(range(a, b + 1, s))
    else:
        levels = list(range(0, max(1, int(count))))
    parts = []
    for i in _v.select(geo, group):
        vox, origin, cell = _v.grid(geo, i)
        act = _v.active(geo, i) if _v.has_mask(geo, i) else None
        nm = _v.name_of(geo, i)
        for L in levels:
            o, oo, oc, oa = _lod_level(vox, origin, cell, act, L)
            name = nm if (mode == "single" and reuse_name) else f"{nm}_level{L}"
            parts.append(_v.from_grid(o, oo, oc, _v.grid_class(geo, i), name, True,
                                      _v.background(geo, i), oa))
    from .ops import merge
    if not parts:
        return Geometry()
    return merge(*parts) if len(parts) > 1 else parts[0]


# ═══════════════════════════════════════════════════════════ Merge
def merge_vdbs(geo, group="", collation="name", interp="linear", op_fog="add", op_sdf="sdfunion"):
    """
    VDBs in the same collation group are merged onto the first one's grid (others resampled by world position;
    outside their grid they contribute their background). Fog: add (or none = keep the first);
    SDF: union (min) / intersect (max); other / vector: add.
    """
    from .ops import merge, delete_prims
    if collation not in MERGE_COLLATION:
        raise ValueError(f"Collation must be one of {MERGE_COLLATION}")
    sel = _v.select(geo, group)
    groups = {}
    for i in sel:
        key = (_v.name_of(geo, i) if collation == "name" else
               (i if collation == "primitive_number" else 0))
        cls = (_v.grid_class(geo, i), _v.is_vector(geo.pdata(i, "voxels")))
        groups.setdefault((key, cls), []).append(i)
    keep = np.ones(geo.nprims, bool)
    parts = []
    rep = []
    for (key, (cls, vec)), ids in groups.items():
        if len(ids) < 2:
            continue
        i0 = ids[0]
        v0, o0, cell = _v.grid(geo, i0)
        # the merged grid covers all of them (a VDB grows; a dense grid has to be enlarged), at the first's voxel size
        los, his = [], []
        for j in ids:
            vj, oj, cj = _v.grid(geo, j)
            los.append(oj)
            his.append(oj + cj * (np.array(_v.res_of(vj)) - 1))
        lo, hi = np.min(los, 0), np.max(his, 0)
        k0 = np.floor((lo - o0) / cell + 1e-6)
        k1 = np.ceil((hi - o0) / cell - 1e-6)
        origin = o0 + k0 * cell
        n = (k1 - k0).astype(int) + 1
        shp = (n[2], n[1], n[0])
        P = _v.world_points(origin, cell, shp).reshape(-1, 3)
        acc = _v.sample(v0, o0, cell, P, outside=_v.outside_value(geo, i0)).reshape(
            shp + v0.shape[3:])
        act = _v.sample(_v.active(geo, i0).astype(np.float32), o0, cell, P, "nearest",
                        outside=0.0).reshape(shp) > 0.5
        for j in ids[1:]:
            vj, oj, cj = _v.grid(geo, j)
            sj = _v.sample(vj, oj, cj, P, "nearest" if interp == "point" else "trilinear",
                           outside=_v.outside_value(geo, j)).reshape(acc.shape)
            aj = _v.sample(_v.active(geo, j).astype(np.float32), oj, cj, P, "nearest",
                           outside=0.0).reshape(act.shape) > 0.5
            if cls == _v.CLASS_SDF and not vec:
                if op_sdf == "sdfunion":
                    acc = np.minimum(acc, sj)
                elif op_sdf == "sdfintersect":
                    acc = np.maximum(acc, sj)
            elif cls == _v.CLASS_FOG and not vec:
                if op_fog == "add":
                    acc = acc + sj
            else:
                acc = acc + sj
            act |= aj
        out = _v.from_grid(acc, origin, cell, cls, _v.name_of(geo, i0), True,
                           _v.background(geo, i0), act)
        parts.append(out)
        keep[ids] = False
        rep.append({"name": _v.name_of(geo, i0), "merged": len(ids)})
    base = delete_prims(geo, keep) if not keep.all() else geo
    allp = ([base] if (base.npoints or base.nprims) else []) + parts
    if not allp:
        return Geometry(), {"groups": rep}
    return (merge(*allp) if len(allp) > 1 else allp[0]), {"groups": rep}


# ═══════════════════════════════════════════════════════════ Segment by Connectivity
def segment(geo, group="", color=True, append_number=True):
    """
    SDF: connected components of the interior (φ < 0), each piece becomes an SDF whose other pieces are pushed
    outside (to +background); fog / other: connected components of active non-background voxels (face connectivity).
    """
    nd = _scipy_ndimage()
    from .ops import merge, delete_prims
    parts = []
    keep = np.ones(geo.nprims, bool)
    rep = []
    rng = np.random.default_rng(7)
    for i in _v.select(geo, group, allow_vector=False):
        vox, origin, cell = _v.grid(geo, i)
        cls = _v.grid_class(geo, i)
        bg = _v.background(geo, i)
        act = _v.active(geo, i)
        if cls == _v.CLASS_SDF:
            solid = vox < 0
        else:
            solid = act & (np.abs(vox - bg) > 1e-7)
        lab, n = nd.label(solid)
        rep.append(int(n))
        if n <= 1:
            continue
        keep[i] = False
        nm = _v.name_of(geo, i)
        for k in range(1, n + 1):
            m = lab == k
            if cls == _v.CLASS_SDF:
                from .volops import redistance
                # the piece alone: distance to its own surface (others count as outside)
                f = np.where(m, np.asarray(vox, np.float64), np.abs(np.asarray(vox, np.float64)))
                grow = dilate_mask(m, 3, "faceedgevertex")
                f = np.where(grow & ~m, np.maximum(np.asarray(vox, np.float64), 0), f)
                f = np.where(~grow, abs(bg) if bg else np.abs(f).max(), f)
                f = redistance(f, origin, cell)
                a = dilate_mask(m, 3, "faceedgevertex") & act if _v.has_mask(geo, i) else None
            else:
                f = np.where(m, vox, bg)
                a = (m & act) if _v.has_mask(geo, i) else m
            piece = _v.from_grid(f, origin, cell, cls, f"{nm}_{k - 1}" if append_number else nm,
                                 _v.is_vdb(geo, i) or a is not None, bg, a)
            if color:
                piece.set(PRIM, "Cd", rng.random((1, 3)).astype(np.float32) * 0.7 + 0.3, owned=True)
            parts.append(piece)
    base = delete_prims(geo, keep) if not keep.all() else geo
    allp = ([base] if (base.npoints or base.nprims) else []) + parts
    if not allp:
        return Geometry(), {"pieces": rep}
    return (merge(*allp) if len(allp) > 1 else allp[0]), {"pieces": rep}


# ═══════════════════════════════════════════════════════════ Remap
def remap(geo, group="", below="clamp", above="clamp", in_range=(0.0, 1.0), out_range=(0.0, 1.0),
          ramp="", deactivate=False):
    """
    t = (v − in_min) / (in_max − in_min); out = out_min + ramp(t)·(out_max − out_min). Outside [0, 1]:
    clamp (to the ramp's end value), preserve (the original value is kept) or extrapolate (the end segment's slope
    continues). Empty ramp = linear. deactivate: voxels equal to the remapped background become inactive.
    """
    for e in (below, above):
        if e not in REMAP_ENDS:
            raise ValueError(f"Below / Above must be one of {REMAP_ENDS}")
    from . import ramp as _rmp
    lo, hi = float(in_range[0]), float(in_range[1])
    olo, ohi = float(out_range[0]), float(out_range[1])
    span = hi - lo if abs(hi - lo) > 1e-12 else 1e-12
    pos, val = (_rmp.parse(ramp, 1) if str(ramp).strip() else (np.array([0.0, 1.0]),
                                                                  np.array([[0.0], [1.0]])))

    def f(x):
        x = np.asarray(x, np.float64)
        t = (x - lo) / span
        r = _rmp.apply(t.reshape(-1), pos, val)[:, 0].reshape(x.shape)
        out = olo + r * (ohi - olo)
        for side, mode in (("below", below), ("above", above)):
            sel = t < 0 if side == "below" else t > 1
            if not sel.any():
                continue
            if mode == "preserve":
                out = np.where(sel, x, out)
            elif mode == "extrapolate":
                if side == "below":
                    k = len(pos) > 1 and (val[1, 0] - val[0, 0]) / max(pos[1] - pos[0], 1e-12)
                    e = olo + (val[0, 0] + k * (t - pos[0])) * (ohi - olo)
                else:
                    k = len(pos) > 1 and (val[-1, 0] - val[-2, 0]) / max(pos[-1] - pos[-2], 1e-12)
                    e = olo + (val[-1, 0] + k * (t - pos[-1])) * (ohi - olo)
                out = np.where(sel, e, out)
        return out

    g = geo.copy()
    for i in _v.select(geo, group, allow_vector=False):
        vox = g.pdata(i, "voxels")
        bg = _v.background(geo, i)
        nb = float(f(np.array([bg]))[0])
        out = f(vox)
        _v.set_background(g, i, nb) if _v.is_vdb(geo, i) else None
        _v.set_voxels(g, i, out, mask="keep")
        if deactivate:
            act = _v.active(g, i) & (np.abs(out - nb) > 1e-7)
            if not _v.is_vdb(g, i):
                _v.set_vdb(g, i, True)
            _v.set_active(g, i, act)
    return g


# ═══════════════════════════════════════════════════════════ Convert VDB
def convert(geo, group="", to="vdb", iso=0.0, fog_iso=0.5, half_band=3.0, adaptivity=0.0,
            keep_original=False, deactivate_tol=0.0):
    """
    to = vdb        Houdini volume -> VDB (all voxels active unless Deactivate Tolerance > 0 drops background ones)
         volume     VDB -> Houdini volume (densify; the mask is dropped)
         polygons   closed iso-surface at Isovalue (VDBs are closed by their background; Houdini volumes too here)
         sdf        fog -> SDF: the Fog Isovalue contour becomes φ = 0 (inside negative), narrow band ± Half Band voxels
         fog        SDF -> fog (OpenVDB's sdfToFogVolume): 0 outside, ramping 0 -> 1 across the interior band, 1 deeper
    adaptivity > 0 reduces the polygon count (Poly Reduce by that fraction of the faces).
    """
    if to not in CONVERT_TO:
        raise ValueError(f"Convert To must be one of {CONVERT_TO}")
    from .ops import merge, delete_prims
    sel = _v.select(geo, group)
    if to == "polygons":
        from .volume import volume_to_polygons
        only = np.zeros(geo.nprims, bool)
        only[sel] = True
        surf = volume_to_polygons(delete_prims(geo, only), float(iso), None, close=True)
        if float(adaptivity) > 0 and surf.nprims > 8:
            from . import polyreduce as _pr
            surf = _pr.reduce_mesh(surf, "percentage", max(1.0, 100.0 * (1.0 - float(adaptivity))))
        keep = np.ones(geo.nprims, bool) if keep_original else ~only
        base = delete_prims(geo, keep) if not keep.all() else geo
        if base.npoints or base.nprims:
            return merge(base, surf)
        return surf
    g = geo.copy()
    from .volops import redistance
    for i in sel:
        vox, origin, cell = _v.grid(geo, i)
        if to == "vdb":
            if not _v.is_vdb(g, i):
                bg = _v.background(geo, i)
                _v.set_vdb(g, i, True, bg=bg)
            if float(deactivate_tol) > 0 and not _v.is_vector(vox):
                act = np.abs(np.asarray(vox) - _v.background(g, i)) > float(deactivate_tol)
                _v.set_active(g, i, act & _v.active(geo, i))
        elif to == "volume":
            g.prim_data.get(int(i), {}).pop("active", None)
            _v.set_vdb(g, i, False)
        elif to == "sdf":
            if _v.is_vector(vox):
                raise ValueError("Cannot convert a vector grid to an SDF")
            f = -(np.asarray(vox, np.float64) - float(fog_iso))      # inside (dense) negative
            d = redistance(f, origin, cell)
            band = float(half_band) * float(np.min(cell))
            act = np.abs(d) <= band
            _v.set_class(g, i, _v.CLASS_SDF)
            _v.set_vdb(g, i, True, bg=band)
            _v.set_voxels(g, i, np.clip(d, -band, band), mask=None)
            _v.set_active(g, i, act)
        else:
            if _v.grid_class(geo, i) != _v.CLASS_SDF or _v.is_vector(vox):
                raise ValueError("SDF to fog needs a scalar SDF")
            bg = abs(_v.background(geo, i)) or float(half_band) * float(np.min(cell))
            d = np.asarray(vox, np.float64)
            # OpenVDB sdfToFogVolume: 0 outside, 0 -> 1 across the interior band, 1 deeper inside
            fog = np.clip(-d / bg, 0.0, 1.0)
            _v.set_class(g, i, _v.CLASS_FOG)
            _v.set_vdb(g, i, True, bg=0.0)
            _v.set_voxels(g, i, fog, mask=None)
            _v.set_active(g, i, fog > 0)
    return g
