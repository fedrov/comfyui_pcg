"""
Volume / VDB node file (pcg106): Houdini's VDB SOPs and the rest of its Volume SOPs.

Storage and VDB semantics: geo/vdb.py (dense grid + active mask + background); implementations in
geo/vdbcore.py (topology / structure), geo/vdbsdf.py (level sets), geo/vdbfield.py (fields),
geo/volmore.py (the Volume SOPs), geo/volvis.py (viewport display + Volume Visualization).
Mapping rows are in tests/sop_map.py. All nodes are under PCG/volume.
"""
from __future__ import annotations

import json

from .nodes_common import GEO, CAT, CAM, _f, _i
from .geo import vdb as _v, vdbcore as _vc, vdbsdf as _vs, vdbfield as _vf
from .geo import volmore as _vm, volvis as _vv


def _s(default=""):
    return ("STRING", {"default": default})


def _b(default=False):
    return ("BOOLEAN", {"default": default})


def _rep(r):
    return json.dumps(r, ensure_ascii=False, default=float)


def _vg():
    return ("STRING", {"default": "", "tooltip":
                       "Empty = all volumes; numbers = the n-th volume; names (wildcards, ^ to exclude) = the prim attribute name"})


def _node(returns=None):
    def deco(cls):
        cls.FUNCTION = "run"
        cls.CATEGORY = CAT + "/volume"
        if returns is None:
            cls.RETURN_TYPES = (GEO,)
            cls.RETURN_NAMES = ("geo",)
        else:
            cls.RETURN_TYPES = tuple(t for t, _ in returns)
            cls.RETURN_NAMES = tuple(n for _, n in returns)
        return cls
    return deco


_REP = ((GEO, "geo"), ("STRING", "report"))


def _v3(prefix, d=(0.0, 0.0, 0.0), mn=-1e6, mx=1e6):
    return {f"{prefix}_x": _f(d[0], mn, mx), f"{prefix}_y": _f(d[1], mn, mx),
            f"{prefix}_z": _f(d[2], mn, mx)}


def _i3(prefix, d=(0, 0, 0), mn=-(1 << 24), mx=1 << 24):
    return {f"{prefix}_x": _i(d[0], mn, mx), f"{prefix}_y": _i(d[1], mn, mx),
            f"{prefix}_z": _i(d[2], mn, mx)}


def _menu(items):
    return (list(items),)


# ═══════════════════════════════════════════════════════════════ VDB: create / topology
@_node()
class PCG_VDB:
    """
    Maps to: VDB. Creates a VDB prim covering the reference geometry's bounds (+ Padding) or Size / Center at Voxel
    Size. Class SDF / Fog / None, scalar or vector. Empty (no active voxels, every voxel = Background) unless Fill
    Active is on (every voxel active with Value). Background defaults to 0 (fog / none) or 3 voxels (SDF).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "name": _s("density"), "vdb_class": _menu(("fog", "sdf", "none")),
            "vector": _b(False), "voxel_size": _f(0.1, 1e-6, 1e6, 0.001),
            **_v3("size", (1.0, 1.0, 1.0), 0.0), **_v3("center"),
            "padding": _f(0.0, 0.0), "auto_background": _b(True), "background": _f(0.0),
            "fill_active": _b(False), "value": _f(0.0),
        }, "optional": {"reference": (GEO,)}}

    def run(self, name, vdb_class, vector, voxel_size, size_x, size_y, size_z, center_x, center_y,
            center_z, padding, auto_background, background, fill_active, value, reference=None):
        return (_vc.create(name, vdb_class, vector, voxel_size,
                           None if auto_background else background, (size_x, size_y, size_z),
                           (center_x, center_y, center_z), reference, padding, fill_active, value),)


@_node(_REP)
class PCG_VDBActivate:
    """
    Maps to: VDB Activate. Combines the active region with a region (Union / Intersect / A − B / Copy). Region Type:
    Position (world box), Voxel (inclusive index box, voxel 0 = the bounding-box minimum), Expand (dilate by voxels or
    distance; face / face+edge / face+edge+vertex pattern), Reference (second input: bounding box, its VDBs' active
    voxels, the convex hull of its points, or inside its implicit surface, offset in voxels / world), Deactivate
    (voxels within Tolerance of the background) and Fill SDF (the inside of an SDF). Union / Copy can write Value.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _vg(), "operation": _menu(_vc.ACTIVATE_OPS),
            "region": _menu(_vc.ACTIVATE_REGIONS), "set_value": _b(True), "value": _f(1.0),
            **_v3("center"), **_v3("size", (0.0, 0.0, 0.0), 0.0),
            **_i3("min"), **_i3("max"),
            "expand": _i(1, 0, 1000), "expand_dist": _f(0.0, 0.0),
            "pattern": _menu(_vc.EXPAND_PATTERNS), "bound_group": _s(""),
            "use_vdb": _b(False), "use_hull": _b(False), "use_implicit": _b(False),
            "voxel_offset": _f(0.0), "world_offset": _f(0.0), "bg_tolerance": _f(0.0, 0.0),
            "prune": _b(False), "prune_tolerance": _f(0.0, 0.0),
        }, "optional": {"reference": (GEO,)}}

    def run(self, geo, group, operation, region, set_value, value, center_x, center_y, center_z,
            size_x, size_y, size_z, min_x, min_y, min_z, max_x, max_y, max_z, expand, expand_dist,
            pattern, bound_group, use_vdb, use_hull, use_implicit, voxel_offset, world_offset,
            bg_tolerance, prune, prune_tolerance, reference=None):
        g, r = _vc.activate(geo, group, operation, region, set_value, value,
                            (center_x, center_y, center_z), (size_x, size_y, size_z),
                            (min_x, min_y, min_z), (max_x, max_y, max_z), expand, expand_dist,
                            pattern, reference, bound_group, use_vdb, use_hull, use_implicit,
                            voxel_offset, world_offset, bg_tolerance, prune, prune_tolerance)
        return (g, _rep(r))


@_node(_REP)
class PCG_VDBActivateSDF:
    """
    Maps to: VDB Activate SDF. The narrow band |φ| ≤ Half-Width voxels around the surface becomes active and gets true
    distances (redistanced from the zero crossing); everything else is inactive ±background (the background becomes
    the band width). The input SDF is assumed to be right near its surface.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "half_width": _f(3.0, 0.1, 1000.0)}}

    def run(self, geo, group, half_width):
        g, r = _vc.activate_sdf(geo, group, half_width)
        return (g, _rep(r))


@_node()
class PCG_VDBDensify:
    """Maps to: VDB Densify. Every voxel becomes active (the VDB keeps its values; inactive ones held the background)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg()}}

    def run(self, geo, group):
        return (_vc.densify(geo, group),)


@_node(_REP)
class PCG_VDBPrune:
    """
    Maps to: VDB Prune. Value: 8³ leaves whose values differ by at most Tolerance collapse to one constant (their
    mean). Inactive: leaves within Tolerance of the background are deactivated. Level Set: voxels with |φ| ≥ background
    are deactivated (outside +background, inside −background).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "mode": _menu(_vc.PRUNE_MODES),
                             "tolerance": _f(0.0, 0.0)}}

    def run(self, geo, group, mode, tolerance):
        g, r = _vc.prune_vdb(geo, group, mode, tolerance)
        return (g, _rep(r))


@_node(_REP)
class PCG_VDBClip:
    """
    Maps to: VDB Clip. Keeps the active voxels inside (or outside, Keep Inside off) the clipping region -- the
    bounding box of the second input, the active voxels of a mask VDB there, or (pcg122) the view frustum of the
    camera input (frame edges, near and far planes) -- expanded by Padding; the rest become inactive background.
    The grid itself is not resampled into a frustum grid; voxels keep their places.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "inside": _b(True),
                             "clipper": _menu(_vc.CLIP_MODES), "mask": _s(""), "padding": _f(0.0)},
                "optional": {"clip": (GEO,), "camera": (CAM,)}}

    def run(self, geo, group, inside, clipper, mask, padding, clip=None, camera=None):
        g, r = _vc.clip(geo, group, inside, clipper, clip, mask, padding, camera)
        return (g, _rep(r))


@_node()
class PCG_VDBFill:
    """
    Maps to: VDB Fill. Sets a box -- inclusive index range, world range, or the reference geometry's bounds -- to
    Value (x only for scalar grids) and makes it active (or inactive: then it takes the background).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "mode": _menu(_vc.FILL_MODES),
                             **_i3("min"), **_i3("max"), **_v3("wmin"), **_v3("wmax"),
                             **_v3("value"), "active": _b(True)},
                "optional": {"reference": (GEO,)}}

    def run(self, geo, group, mode, min_x, min_y, min_z, max_x, max_y, max_z, wmin_x, wmin_y,
            wmin_z, wmax_x, wmax_y, wmax_z, value_x, value_y, value_z, active, reference=None):
        import numpy as np
        return (_vc.fill(geo, group, mode, np.array([min_x, min_y, min_z]),
                         np.array([max_x, max_y, max_z]), (wmin_x, wmin_y, wmin_z),
                         (wmax_x, wmax_y, wmax_z), (value_x, value_y, value_z), active, reference),)


@_node()
class PCG_VDBTopologyToSDF:
    """
    Maps to: VDB Topology to SDF. The active voxels as a solid: an SDF with the surface half a voxel outside the
    outermost active samples (exact Euclidean distance transforms), after Voxel Dilation and Closing Width
    (dilate then erode); Smoothing Steps of mean filtering + redistancing. Narrow band of Half-Band voxels
    (or world units).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(),
                             "output_name": _menu(("keep", "append", "replace")), "custom_name": _s(""),
                             "world_space": _b(False), "half_band": _i(3, 1, 100),
                             "half_band_world": _f(1.0, 1e-6), "dilation": _i(0, 0, 100),
                             "closing": _i(1, 0, 100), "smoothing": _i(0, 0, 100)}}

    def run(self, geo, group, output_name, custom_name, world_space, half_band, half_band_world,
            dilation, closing, smoothing):
        return (_vc.topology_to_sdf(geo, group, half_band, half_band_world if world_space else None,
                                    dilation, closing, smoothing, output_name, custom_name),)


@_node(_REP)
class PCG_VDBDiagnostics:
    """
    Maps to: VDB Diagnostics. Tests: finite values, a valid background, inactive voxels holding the background,
    SDF gradient magnitude within Tolerance of 1 (in the band), active values within [Min, Max]. Repair: non-finite
    -> background, inactive -> background, values clamped into the range. Mark: adds "<name>_bad" fog VDBs = 1 at
    failing voxels. The report lists the counts per volume.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "test_finite": _b(True),
                             "test_background": _b(True), "test_inactive": _b(True),
                             "test_gradient": _b(True), "gradient_tolerance": _f(0.2, 0.0),
                             "test_range": _b(False), "range_min": _f(0.0), "range_max": _f(1.0),
                             "repair": _b(False), "mark": _b(False)}}

    def run(self, geo, group, test_finite, test_background, test_inactive, test_gradient,
            gradient_tolerance, test_range, range_min, range_max, repair, mark):
        tests = [t for t, on in (("finite", test_finite), ("background", test_background),
                                 ("inactive", test_inactive), ("gradient", test_gradient),
                                 ("range", test_range)) if on]
        g, r = _vc.diagnostics(geo, group, tests, gradient_tolerance, range_min, range_max,
                               repair, mark)
        return (g, _rep(r))


@_node()
class PCG_VDBVisualizeTree:
    """
    Maps to: VDB Visualize Tree. Leaf nodes (8³ blocks holding active voxels) and internal nodes (128³ blocks) as
    wireframe boxes or points, active voxels as boxes or points, the grid bounding box; groups leaves / internal /
    voxels / bbox and Cd. Keep Original Geometry keeps the volumes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "leaves": _menu(("boxes", "points", "none")),
                             "internal": _menu(("none", "boxes", "points")),
                             "voxels": _menu(("none", "points", "boxes")), "bbox": _b(True),
                             "keep": _b(False)}}

    def run(self, geo, group, leaves, internal, voxels, bbox, keep):
        return (_vc.visualize_tree(geo, group, leaves, internal, voxels, bbox, keep),)


@_node()
class PCG_VDBMetadata:
    """Maps to: VDB Metadata. Sets the name, class, background and VDB flag of the selected volumes (each with a toggle)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "set_name": _b(False), "name": _s(""),
                             "set_class": _b(False), "vdb_class": _menu(_vc.CLASS_MENU),
                             "set_background": _b(False), "background": _f(0.0),
                             "set_vdb": _b(False), "vdb": _b(True)}}

    def run(self, geo, group, set_name, name, set_class, vdb_class, set_background, background,
            set_vdb, vdb):
        return (_vc.metadata(geo, group, set_name, name, set_class, vdb_class, set_background,
                             background, set_vdb, vdb),)


@_node()
class PCG_VDBVectorMerge:
    """
    Maps to: VDB Vector Merge (also Volume Vector Join). Pairs the X / Y / Z scalar grids (by base name for patterns
    like *.x, else in order) into vector grids on the X grid's samples; missing components are 0. Named after the
    X grid's base name, or Merged VDB Name (# = number). Remove Source VDBs deletes the scalars.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "xgroup": _s("*.x"), "ygroup": _s("*.y"),
                             "zgroup": _s("*.z"), "use_basename": _b(True),
                             "merge_name": _s("merged#"), "remove_sources": _b(True)}}

    def run(self, geo, xgroup, ygroup, zgroup, use_basename, merge_name, remove_sources):
        return (_vc.vector_merge(geo, xgroup, ygroup, zgroup, use_basename, merge_name,
                                 remove_sources),)


@_node()
class PCG_VDBVectorSplit:
    """
    Maps to: VDB Vector Split (also Volume Vector Split). Each vector grid becomes scalar grids <name>.x / .y / .z;
    scalar grids pass through. Keep Source Volumes keeps the vector grids too.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "keep_source": _b(False)}}

    def run(self, geo, group, keep_source):
        return (_vc.vector_split(geo, group, keep_source),)


@_node()
class PCG_VDBTransform:
    """
    Maps to: VDB Transform. Translate and (non-uniform) scale move the grid exactly; with a rotation the grid is
    resampled into the axis-aligned bounds of the rotated one at the same voxel size (grids here are axis
    aligned). Order: scale, rotate, translate about the pivot. Transform Vectors rotates / scales vector values.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), **_v3("t"), **_v3("r"),
                             **_v3("s", (1.0, 1.0, 1.0)), **_v3("p"), "uniform_scale": _f(1.0),
                             "invert": _b(False), "xform_vectors": _b(False)}}

    def run(self, geo, group, t_x, t_y, t_z, r_x, r_y, r_z, s_x, s_y, s_z, p_x, p_y, p_z,
            uniform_scale, invert, xform_vectors):
        return (_vc.transform(geo, group, (t_x, t_y, t_z), (r_x, r_y, r_z), (s_x, s_y, s_z),
                              uniform_scale, (p_x, p_y, p_z), invert, xform_vectors),)


@_node()
class PCG_VDBLOD:
    """
    Maps to: VDB LOD. Level L keeps every 2^L-th sample after a 2^L box filter (level 0 = the input). Single Level,
    Level Range (start, end, step) or an LOD Pyramid of Count levels; outputs are named <name>_level<L> unless
    Preserve Grid Names (single level).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "lod": _menu(_vc.LOD_MODES),
                             "level": _f(1.0, 0.0, 10.0), "range_start": _i(0, 0, 10),
                             "range_end": _i(2, 0, 10), "range_step": _i(1, 1, 10),
                             "count": _i(2, 1, 10), "reuse": _b(False)}}

    def run(self, geo, group, lod, level, range_start, range_end, range_step, count, reuse):
        return (_vc.lod(geo, group, lod, level, (range_start, range_end, range_step), count, reuse),)


@_node(_REP)
class PCG_VDBMerge:
    """
    Maps to: VDB Merge. VDBs of the same class collated by name / primitive number / all are merged into one whose
    grid covers all of them (first one's voxel size): fog add (or none), SDF union / intersect, other add.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "collation": _menu(_vc.MERGE_COLLATION),
                             "interp": _menu(("linear", "point")), "op_fog": _menu(("add", "none")),
                             "op_sdf": _menu(("sdfunion", "sdfintersect", "none"))}}

    def run(self, geo, group, collation, interp, op_fog, op_sdf):
        g, r = _vc.merge_vdbs(geo, group, collation, interp, op_fog, op_sdf)
        return (g, _rep(r))


@_node(_REP)
class PCG_VDBSegment:
    """
    Maps to: VDB Segment by Connectivity. Splits each volume into connected pieces: SDF interiors, or active
    non-background voxels of fog / other grids (face connectivity). Pieces are named <name>_<n> (Append Segment
    Number) and get a random Cd (Color Segments).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "color": _b(True),
                             "append_number": _b(True)}}

    def run(self, geo, group, color, append_number):
        g, r = _vc.segment(geo, group, color, append_number)
        return (g, _rep(r))


@_node()
class PCG_VDBRemap:
    """
    Maps to: VDB Remap. Input Range -> Output Range through the Transfer Function ramp (empty = linear). Below /
    Above the input range: Clamp, Preserve (keep the value) or Extrapolate (continue the end slope). The background
    is remapped too; Deactivate turns voxels equal to the new background inactive.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "below": _menu(_vc.REMAP_ENDS),
                             "above": _menu(_vc.REMAP_ENDS), "in_min": _f(0.0), "in_max": _f(1.0),
                             "out_min": _f(0.0), "out_max": _f(1.0), "ramp": _s(""),
                             "deactivate": _b(False)}}

    def run(self, geo, group, below, above, in_min, in_max, out_min, out_max, ramp, deactivate):
        return (_vc.remap(geo, group, below, above, (in_min, in_max), (out_min, out_max), ramp,
                          deactivate),)


@_node()
class PCG_ConvertVDB:
    """
    Maps to: Convert VDB. To VDB (from a Houdini volume; Deactivate Tolerance drops background voxels), to Volume
    (densify, no mask), to Polygons (closed iso-surface at Isovalue; Adaptivity reduces the face count), or between
    classes: fog -> SDF (Fog Isovalue, ±Half Band voxels) and SDF -> fog (OpenVDB's ramp across the interior band).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "convert_to": _menu(("vdb", "volume", "polygons", "sdf", "fog")),
                             "isovalue": _f(0.0), "fog_isovalue": _f(0.5), "half_band": _f(3.0, 0.5),
                             "adaptivity": _f(0.0, 0.0, 0.99), "keep_original": _b(False),
                             "deactivate_tolerance": _f(0.0, 0.0)}}

    def run(self, geo, group, convert_to, isovalue, fog_isovalue, half_band, adaptivity,
            keep_original, deactivate_tolerance):
        return (_vc.convert(geo, group, convert_to, isovalue, fog_isovalue, half_band, adaptivity,
                            keep_original, deactivate_tolerance),)


# ═══════════════════════════════════════════════════════════════ VDB: level sets
@_node()
class PCG_VDBFromPolygons:
    """
    Maps to: VDB from Polygons. Exact SDF of the mesh at Voxel Size (or the reference VDB's), narrow band of Exterior /
    Interior Band voxels (or world units; Fill Interior keeps the whole inside), or an unsigned distance field. Optional
    fog VDB (0 outside, 0 -> 1 across the interior band) and surface attribute VDBs: for each listed point / vertex /
    prim attribute, the value at the closest surface point.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "voxel_size": _f(0.1, 1e-6, 1e6, 0.001),
                             "world_units": _b(False), "ext_band": _f(3.0, 0.0), "int_band": _f(3.0, 0.0),
                             "fill_interior": _b(False), "unsigned": _b(False),
                             "build_distance": _b(True), "distance_name": _s("surface"),
                             "build_fog": _b(False), "fog_name": _s("density"), "attributes": _s("")},
                "optional": {"reference": (GEO,)}}

    def run(self, geo, voxel_size, world_units, ext_band, int_band, fill_interior, unsigned,
            build_distance, distance_name, build_fog, fog_name, attributes, reference=None):
        return (_vs.from_polygons(geo, voxel_size, ext_band, int_band, world_units, fill_interior,
                                  unsigned, build_distance, distance_name, build_fog, fog_name,
                                  attributes, reference),)


@_node(_REP)
class PCG_VDBFromParticles:
    """
    Maps to: VDB from Particles. SDF union of spheres of radius pscale × Particle Scale; particles smaller than Minimum
    Radius (voxels) are ignored; Velocity Trails add tapering spheres back along v × Velocity Scale every Trail
    Resolution × radius. Optional fog VDB.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": ("STRING", {"default": ""}),
                             "voxel_size": _f(0.1, 1e-6, 1e6, 0.001), "world_units": _b(False),
                             "half_band": _f(3.0, 0.5), "particle_scale": _f(1.0, 0.0),
                             "min_radius": _f(1.5, 0.0), "velocity_trails": _b(False),
                             "velocity_scale": _f(1.0), "trail_resolution": _f(1.0, 0.01),
                             "build_distance": _b(True), "distance_name": _s("surface"),
                             "build_fog": _b(False), "fog_name": _s("density")}}

    def run(self, geo, group, voxel_size, world_units, half_band, particle_scale, min_radius,
            velocity_trails, velocity_scale, trail_resolution, build_distance, distance_name,
            build_fog, fog_name):
        g, r = _vs.from_particles(geo, voxel_size, half_band, world_units, particle_scale,
                                  min_radius, velocity_trails, velocity_scale, trail_resolution,
                                  build_distance, distance_name, build_fog, fog_name, group or None)
        return (g, _rep(r))


@_node()
class PCG_VDBFromParticleFluid:
    """
    Maps to: VDB from Particle Fluid. A smooth fluid surface from particles: spheres of Influence Scale × separation / 2
    (isolated droplets: Droplet Scale), voxel size = Particle Separation × Voxel Scale, then Dilate, Smooth passes and
    Erode (in units of half a separation).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": ("STRING", {"default": ""}),
                             "separation": _f(0.1, 1e-6), "voxel_scale": _f(0.5, 0.05, 4.0),
                             "influence_scale": _f(3.0, 0.5), "droplet_scale": _f(1.0, 0.0),
                             "dilate": _f(1.0, 0.0), "smooth": _i(1, 0, 20), "erode": _f(1.0, 0.0),
                             "name": _s("surface")}}

    def run(self, geo, group, separation, voxel_scale, influence_scale, droplet_scale, dilate,
            smooth, erode, name):
        return (_vs.from_particle_fluid(geo, separation, voxel_scale, influence_scale,
                                        droplet_scale, dilate, smooth, erode, name, group or None),)


@_node()
class PCG_VDBRenormalizeSDF:
    """Maps to: VDB Renormalize SDF. Restores |∇φ| = 1 (exact distance to the zero crossing), keeping the band."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "iterations": _i(1, 1, 10)}}

    def run(self, geo, group, iterations):
        return (_vs.renormalize(geo, group, iterations),)


@_node()
class PCG_VDBRebuildSDF:
    """
    Maps to: VDB Rebuild SDF. An SDF from the Isovalue contour of any scalar grid (fog: dense = inside), with new
    exterior / interior bands (voxels or world units); Fill Interior keeps the whole inside active.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "isovalue": _f(0.0), "world_units": _b(False),
                             "ext_band": _f(3.0, 0.0), "int_band": _f(3.0, 0.0), "fill_interior": _b(False)}}

    def run(self, geo, group, isovalue, world_units, ext_band, int_band, fill_interior):
        return (_vs.rebuild(geo, group, isovalue, ext_band, int_band, world_units, fill_interior),)


@_node(_REP)
class PCG_VDBMorphSDF:
    """
    Maps to: VDB Morph SDF. Moves the source surface toward the target (second input): ∂φ/∂t = φ_target |∇φ|
    (Godunov upwind, CFL-limited substeps) for Timestep, renormalising every Renorm Steps substeps. A large timestep
    ends at the target. Optional alpha mask (third input) blends.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": (GEO,), "target": (GEO,), "source_group": _vg(),
                             "target_group": _vg(), "timestep": _f(1.0 / 24, 0.0, 1e4, 0.001),
                             "renorm_steps": _i(3, 0, 100), "mask_name": _s(""), "invert_mask": _b(False),
                             "min_mask": _f(0.0), "max_mask": _f(1.0)},
                "optional": {"mask": (GEO,)}}

    def run(self, source, target, source_group, target_group, timestep, renorm_steps, mask_name,
            invert_mask, min_mask, max_mask, mask=None):
        g, r = _vs.morph(source, target, source_group, target_group, timestep, renorm_steps, mask,
                         mask_name, invert_mask, min_mask, max_mask)
        return (g, _rep(r))


@_node(_REP)
class PCG_VDBFracture:
    """
    Maps to: VDB Fracture. Cuts each SDF with the cutters of the second input (polygons -> exact SDF on the same grid,
    or SDF VDBs), optionally instanced on the points of the third input (centred, random rotation): inside piece
    max(φ, φc), residual max(φ, −φc). Allow Cutter Overlap cuts the earlier fragments too; Separate Cutters by
    Connectivity uses each connected piece of the cutter separately.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "cutters": (GEO,), "group": _vg(),
                             "separate_cutters": _b(False), "cutter_overlap": _b(False),
                             "center_cutter": _b(True), "random_rotation": _b(False),
                             "rand_seed": _i(1, 0, 1 << 31), "segment_fragments": _b(False),
                             "fragment_group": _s(""), "visualize": _b(True)},
                "optional": {"points": (GEO,)}}

    def run(self, geo, cutters, group, separate_cutters, cutter_overlap, center_cutter,
            random_rotation, rand_seed, segment_fragments, fragment_group, visualize, points=None):
        g, r = _vs.fracture(geo, cutters, points, group, separate_cutters, cutter_overlap,
                            center_cutter, random_rotation, rand_seed, segment_fragments,
                            fragment_group, visualize)
        return (g, _rep(r))


@_node()
class PCG_VDBToSpheres:
    """
    Maps to: VDB to Spheres. Greedy packing inside the Isovalue contour: Point Count random candidates, repeatedly the
    deepest becomes a sphere; others shrink to stay outside it (or, Overlapping, only those inside it are dropped).
    Radii in voxels or world units, Min / Max Radius and Min / Max Spheres. Output: points with pscale and id
    (copy a sphere onto them; sphere primitives are not a prim type here).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "isovalue": _f(0.0), "world_units": _b(False),
                             "use_radius_min": _b(True), "radius_min": _f(1.0, 0.0),
                             "use_radius_max": _b(False), "radius_max": _f(100.0, 0.0),
                             "use_spheres_min": _b(True), "spheres_min": _i(1, 0, 100000),
                             "use_spheres_max": _b(True), "spheres_max": _i(50, 1, 100000),
                             "scatter": _i(10000, 1, 10 ** 7), "overlapping": _b(False),
                             "add_id": _b(True), "add_pscale": _b(True), "rand_seed": _i(1, 0, 1 << 31)}}

    def run(self, geo, group, isovalue, world_units, use_radius_min, radius_min, use_radius_max,
            radius_max, use_spheres_min, spheres_min, use_spheres_max, spheres_max, scatter,
            overlapping, add_id, add_pscale, rand_seed):
        return (_vs.to_spheres(geo, group, isovalue, world_units, use_radius_min, radius_min,
                               use_radius_max, radius_max, use_spheres_min, spheres_min,
                               use_spheres_max, spheres_max, scatter, overlapping, add_id,
                               add_pscale, rand_seed),)


@_node()
class PCG_VDBPlatonic:
    """
    Maps to: VDB Platonic. SDF (narrow band of Half-Band Width voxels) or fog of a sphere or a Platonic solid of the given
    radius (circumradius for the solids) and centre; exact distances to the solid's faces.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"solid": _menu(_vs.PLATONIC), "radius": _f(1.0, 1e-6), **_v3("center"),
                             "voxel_size": _f(0.1, 1e-6, 1e6, 0.001), "half_width": _f(3.0, 0.5),
                             "fog": _b(False), "name": _s("surface")}}

    def run(self, solid, radius, center_x, center_y, center_z, voxel_size, half_width, fog, name):
        return (_vs.platonic(solid, radius, (center_x, center_y, center_z), voxel_size, half_width,
                             fog, name),)


@_node()
class PCG_VDBNoise:
    """
    Maps to: VDB Noise. φ − Amplitude × fractal Perlin noise (Frequency, Octaves, Lacunarity, Gain, Roughness, Noise
    Offset); Straight / Absolute / Inverse Absolute. Positive noise pushes the surface out. An optional mask volume
    (second input) suppresses or scales the noise.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "amp": _f(1.0), "freq": _f(1.0),
                             "octaves": _i(0, 0, 16), "lacunarity": _f(2.0), "gain": _f(1.0),
                             "roughness": _f(1.0), "surface_offset": _f(0.0), **_v3("noise_offset"),
                             "mode": _menu(_vs.NOISE_MODES), "mask_group": _s(""),
                             "mask_mode": _menu(_vs.NOISE_MASK), "threshold": _f(0.0),
                             "falloff": _f(0.0, 0.0)},
                "optional": {"mask": (GEO,)}}

    def run(self, geo, group, amp, freq, octaves, lacunarity, gain, roughness, surface_offset,
            noise_offset_x, noise_offset_y, noise_offset_z, mode, mask_group, mask_mode, threshold,
            falloff, mask=None):
        return (_vs.noise(geo, group, amp, freq, octaves, lacunarity, gain, roughness,
                          surface_offset, (noise_offset_x, noise_offset_y, noise_offset_z), mode,
                          mask, mask_group, mask_mode, threshold, falloff),)


@_node()
class PCG_VDBExtrapolate:
    """
    Maps to: VDB Extrapolate. Expand SDF Narrowband (by Dilation voxels, true distances), Convert Fog VDB to SDF,
    Renormalize SDF, or Extend Field(s) off the surface of the fog / SDF source: each voxel of the Extension Group
    grids takes the value at its closest voxel on the surface (what fast sweeping converges to).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "mode": _menu(_vs.EXTRAP_MODES),
                             "dilate": _i(3, 0, 1000), "pattern": _menu(_vc.EXPAND_PATTERNS),
                             "fog_isovalue": _f(0.5), "sdf_isovalue": _f(0.0), "ext_group": _s("")}}

    def run(self, geo, group, mode, dilate, pattern, fog_isovalue, sdf_isovalue, ext_group):
        return (_vs.extrapolate(geo, group, mode, dilate, fog_isovalue, sdf_isovalue, ext_group,
                                pattern),)


@_node()
class PCG_VDBOcclusionMask:
    """
    Maps to: VDB Occlusion Mask. A fog VDB "<name>_occlusion" on each SDF's grid: 1 where the voxel is hidden from the
    camera because the line of sight to the eye passes through the inside first; Erode shrinks it. (Houdini builds
    the mask in a camera frustum grid; here it lives on the input grid.)
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "camera": (CAM,), "group": _vg(), "erode": _i(0, 0, 100),
                             "steps": _i(64, 4, 1024)}}

    def run(self, geo, camera, group, erode, steps):
        return (_vs.occlusion_mask(geo, camera, group, erode, steps),)


@_node(_REP)
class PCG_VDBRay:
    """
    Maps to: VDB Ray. Moves points onto the surface of the VDB in the second input: Ray Intersection along N (or
    reversed, from Bias; nearest or farthest hit; sphere tracing + bisection) or Closest Surface Point (P − φ∇φ).
    Scale moves only part of the way; Store Distances writes dist; Ray Hit Group collects hits.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "vdb": (GEO,), "group": ("STRING", {"default": ""}),
                             "method": _menu(_vs.RAY_METHODS), "isovalue": _f(0.0), "transform": _b(True),
                             "scale": _f(1.0), "store_dist": _b(False), "farthest": _b(False),
                             "reverse": _b(False), "bias": _f(0.0), "create_group": _b(False),
                             "hit_group": _s("rayHitGroup")}}

    def run(self, geo, vdb, group, method, isovalue, transform, scale, store_dist, farthest, reverse,
            bias, create_group, hit_group):
        g, r = _vs.ray(geo, vdb, group, method, isovalue, transform, scale, store_dist, farthest,
                       reverse, bias, create_group, hit_group)
        return (g, _rep(r))


@_node()
class PCG_VolumeSDF:
    """
    Maps to: Volume SDF. Any volume -> SDF of its Iso Surface contour (same resolution). Invert flips the sign (use it
    for fog so dense = inside). Use Maximum Distance clamps to ±Maximum Distance. Distances are exact to the extracted
    contour (Houdini uses fast marching).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "iso": _f(0.0), "invert": _b(False),
                             "use_max": _b(False), "max_dist": _f(1.0, 0.0)}}

    def run(self, geo, group, iso, invert, use_max, max_dist):
        return (_vs.volume_sdf(geo, group, iso, invert, use_max, max_dist),)


# ═══════════════════════════════════════════════════════════════ VDB: fields
@_node(_REP)
class PCG_VDBAnalysis:
    """
    Maps to: VDB Analysis (and Volume Analysis). Gradient, Curvature (mean curvature ∇·(∇φ/|∇φ|)), Laplacian,
    Closest Point (P − φ∇φ) on scalar grids; Divergence, Curl, Length, Normalize on vector grids. Central
    differences in world units. An optional mask VDB (second input) zeroes the result outside its active voxels.
    Vector results are vector grids (VDB Vector Split for .x / .y / .z).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "operator": _menu(_vf.ANALYSIS_OPS),
                             "mask_name": _s(""), "output_name": _menu(("keep", "append", "custom")),
                             "custom_name": _s("")},
                "optional": {"mask": (GEO,)}}

    def run(self, geo, group, operator, mask_name, output_name, custom_name, mask=None):
        g, r = _vf.analysis(geo, group, operator, mask, mask_name, output_name, custom_name)
        return (g, _rep(r))


@_node()
class PCG_VDBSmooth:
    """
    Maps to: VDB Smooth. Mean / Gaussian / Median over a cube of ± Filter Voxel Radius (or world radius), or Offset,
    Iterations times; only active voxels change; an optional alpha mask (second input, Min / Max cutoff, invert) blends.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "operation": _menu(_vf.SMOOTH_OPS),
                             "world_units": _b(False), "radius": _i(1, 0, 100),
                             "world_radius": _f(0.1, 0.0), "iterations": _i(4, 0, 1000), "offset": _f(1.0),
                             "mask_name": _s(""), "invert_mask": _b(False), "min_mask": _f(0.0),
                             "max_mask": _f(1.0)},
                "optional": {"mask": (GEO,)}}

    def run(self, geo, group, operation, world_units, radius, world_radius, iterations, offset,
            mask_name, invert_mask, min_mask, max_mask, mask=None):
        return (_vf.smooth(geo, group, operation, world_units, radius, world_radius, iterations,
                           offset, mask, mask_name, invert_mask, min_mask, max_mask),)


@_node()
class PCG_VDBAdvect:
    """
    Maps to: VDB Advect. Moves the selected grids through a velocity (a vector VDB, or vel.x/.y/.z volumes) in the second
    input for Timestep: Semi-Lagrangian / Mid-Point / RK3 / RK4 back-tracing, Substeps, limiter (none / clamp to the
    source neighbourhood extrema / revert to first order). VDB grids grow so the content does not leave them;
    SDFs (Respect Grid Class) are renormalised.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "velocity": (GEO,), "group": _vg(), "vel_name": _s(""),
                             "respect_class": _b(True), "timestep": _f(1.0 / 24, -1e4, 1e4, 0.001),
                             "substeps": _i(1, 1, 1000), "advection": _menu(_vf.ADVECT_SCHEMES),
                             "limiter": _menu(_vf.LIMITERS)}}

    def run(self, geo, velocity, group, vel_name, respect_class, timestep, substeps, advection,
            limiter):
        return (_vf.advect(geo, velocity, group, vel_name, respect_class, timestep, substeps,
                           advection, limiter),)


@_node()
class PCG_VDBAdvectPoints:
    """
    Maps to: VDB Advect Points. Advection (RK1–RK4 through the velocity for Timestep in Substeps), Projection (to a
    closest-point vector field, VDB Analysis → Closest Point) or Constrained Advection (both); Output Streamlines adds
    the paths as polylines.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "velocity": (GEO,), "group": ("STRING", {"default": ""}),
                             "vel_name": _s(""), "operation": _menu(("advection", "projection", "constrained")),
                             "integration": _menu(("rk4", "rk1", "rk2", "rk3")),
                             "timestep": _f(1.0 / 24, -1e4, 1e4, 0.001), "substeps": _i(1, 1, 1000),
                             "cpt_name": _s(""), "iterations": _i(0, 0, 100), "streamlines": _b(False)}}

    def run(self, geo, velocity, group, vel_name, operation, integration, timestep, substeps, cpt_name,
            iterations, streamlines):
        return (_vf.advect_points(geo, velocity, group, vel_name, operation, integration, timestep,
                                  substeps, velocity, cpt_name, iterations, streamlines),)


@_node(_REP)
class PCG_VDBProjectNonDivergent:
    """
    Maps to: VDB Project Non-Divergent. Removes the divergence of vector grids: ∇²p = ∇·u (conjugate gradient,
    Iterations / Tolerance), u − ∇p. Without a collider p = 0 beyond the grid; Bounding Box collider = no flow through
    the grid border; a VDB collider (second input) = no flow into its inside / active voxels. Output Pressure adds p.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "iterations": _i(1000, 1, 100000),
                             "tolerance": _f(1e-4, 0.0, 1.0, 1e-5), "use_collider": _b(False),
                             "collider_type": _menu(("bbox", "static")), "collider_name": _s(""),
                             "invert_collider": _b(False), "output_pressure": _b(False)},
                "optional": {"collider": (GEO,)}}

    def run(self, geo, group, iterations, tolerance, use_collider, collider_type, collider_name,
            invert_collider, output_pressure, collider=None):
        g, r = _vf.project_non_divergent(geo, group, iterations, tolerance, use_collider,
                                         collider_type, collider, collider_name, invert_collider,
                                         output_pressure)
        return (g, _rep(r))


@_node()
class PCG_VDBPotentialFlow:
    """
    Maps to: VDB Potential Flow. Flow around the solid of an SDF in a domain dilated by Dilation Voxels: ∇²φ = 0 with no
    flow through the solid (Neumann, driven by the Background Velocity) and φ = 0 at the domain border; outputs the
    velocity ∇φ (+ background when Apply Background Velocity) as a vector VDB, and optionally the potential.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "dilation_voxels": _i(10, 1, 1000),
                             "iterations": _i(1000, 1, 100000), "tolerance": _f(1e-4, 0.0, 1.0, 1e-5),
                             "use_background": _b(True), **_v3("background", (1.0, 0.0, 0.0)),
                             "apply_background": _b(True), "output_potential": _b(False),
                             "name": _s("vel")}}

    def run(self, geo, group, dilation_voxels, iterations, tolerance, use_background, background_x,
            background_y, background_z, apply_background, output_potential, name):
        return (_vf.potential_flow(geo, group, dilation_voxels, iterations, tolerance,
                                   (background_x, background_y, background_z), use_background,
                                   apply_background, output_potential, name),)


@_node()
class PCG_VDBCombine:
    """
    Maps to: VDB Combine. A × A Multiplier with B × B Multiplier (B resampled to A's grid; A grows to cover B for VDBs):
    Copy A / B, Invert A, Add, Subtract, Multiply, Divide, Maximum, Minimum, (1 − A) × B, A + (1 − A) × B, SDF Union /
    Intersection / Difference, Replace A with Active B, and Activity Union / Intersection / Difference (masks only).
    Collation: A/B pairs, each A with the first B, or flatten all A into the first A. Deactivate Background Voxels,
    Prune.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"a": (GEO,), "agroup": _vg(), "bgroup": _vg(),
                             "collation": _menu(_vf.COMBINE_COLLATION), "operation": _menu(("add",) + tuple(o for o in _vf.COMBINE_OPS if o != "add")),
                             "amult": _f(1.0), "bmult": _f(1.0), "interp": _menu(("linear", "point")),
                             "deactivate": _b(False), "bg_tolerance": _f(0.0, 0.0), "prune": _b(False),
                             "prune_tolerance": _f(0.0, 0.0)},
                "optional": {"b": (GEO,)}}

    def run(self, a, agroup, bgroup, collation, operation, amult, bmult, interp, deactivate,
            bg_tolerance, prune, prune_tolerance, b=None):
        return (_vf.combine(a, b, agroup, bgroup, collation, operation, amult, bmult, interp,
                            deactivate, bg_tolerance, prune, prune_tolerance),)


@_node()
class PCG_VDBResample:
    """
    Maps to: VDB Resample. Same world content on a new grid: Explicitly (scale the voxel size, translate in voxels,
    rotate about the pivot -- the grid stays axis aligned), To Match Reference VDB (second input), Using Voxel Size
    Only, or Using Voxel Scale Only. Nearest / linear interpolation; SDFs are redistanced (Rebuild SDF).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "mode": _menu(("voxelsizeonly", "explicit", "refvdb", "voxelscaleonly")),
                             "ref_name": _s(""), "interp": _menu(("linear", "point")), **_v3("t"),
                             **_v3("r"), **_v3("s", (1.0, 1.0, 1.0)), **_v3("p"),
                             "voxel_size": _f(0.1, 1e-6, 1e6, 0.001), "voxel_scale": _f(1.0, 1e-6),
                             "rebuild_sdf": _b(True), "xform_vectors": _b(False)},
                "optional": {"reference": (GEO,)}}

    def run(self, geo, group, mode, ref_name, interp, t_x, t_y, t_z, r_x, r_y, r_z, s_x, s_y, s_z,
            p_x, p_y, p_z, voxel_size, voxel_scale, rebuild_sdf, xform_vectors, reference=None):
        return (_vf.resample(geo, group, mode, reference, ref_name, interp, (t_x, t_y, t_z),
                             (r_x, r_y, r_z), (s_x, s_y, s_z), (p_x, p_y, p_z), voxel_size,
                             voxel_scale, rebuild_sdf, xform_vectors),)


@_node(_REP)
class PCG_VDBPointsGroup:
    """
    Maps to: VDB Points Group (VDB Points are ordinary points here). A point group from: a percentage or a count
    (random, or seeded by an attribute), a bounding box or the bounds of the second input, and an SDF range (the
    second input's SDF, Min ≤ φ ≤ Max, invertible). Filters combine with AND.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group_name": _s("group1"), "enable_number": _b(False),
                             "number_mode": _menu(("percentage", "total")), "percent": _f(10.0, 0.0, 100.0),
                             "count": _i(5000, 0, 1 << 30), "seed_attribute": _s(""),
                             "enable_box": _b(False), "bound_mode": _menu(("boundingbox", "boundingobject")),
                             **_v3("size", (1.0, 1.0, 1.0), 0.0), **_v3("center"),
                             "enable_sdf": _b(False), "sdf_name": _s(""), "use_min": _b(True),
                             "sdf_min": _f(-0.1), "use_max": _b(True), "sdf_max": _f(0.1),
                             "invert": _b(False), "rand_seed": _i(0, 0, 1 << 31)},
                "optional": {"reference": (GEO,)}}

    def run(self, geo, group_name, enable_number, number_mode, percent, count, seed_attribute,
            enable_box, bound_mode, size_x, size_y, size_z, center_x, center_y, center_z,
            enable_sdf, sdf_name, use_min, sdf_min, use_max, sdf_max, invert, rand_seed,
            reference=None):
        g, r = _vf.points_group(geo, group_name, enable_number, number_mode, percent, count,
                                seed_attribute, enable_box, bound_mode, reference,
                                (size_x, size_y, size_z), (center_x, center_y, center_z),
                                enable_sdf, reference, sdf_name, use_min, sdf_min, use_max, sdf_max,
                                invert, rand_seed)
        return (g, _rep(r))


@_node()
class PCG_VDBScatter:
    """
    Maps to: VDB Scatter. Points in the active voxels: Point Total, Point Density (per unit volume) or Points Per
    Voxel; Spread jitters within the voxel; Scale Density by Voxel Values (fog / other); SDFs scatter in the Interior,
    on the Isosurface (projected onto it) or in the Narrow Band. Keep Original Geometry, Scatter Group.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "keep": _b(False),
                             "mode": _menu(_vf.SCATTER_MODES), "count": _i(5000, 0, 1 << 30),
                             "points_per_voxel": _f(8.0, 0.0), "density": _f(1.0, 0.0),
                             "multiply": _b(False), "spread": _f(1.0, 0.0, 1.0),
                             "sdf_domain": _menu(("band", "interior", "surface")), "isovalue": _f(0.0),
                             "rand_seed": _i(0, 0, 1 << 31), "scatter_group": _s("")}}

    def run(self, geo, group, keep, mode, count, points_per_voxel, density, multiply, spread,
            sdf_domain, isovalue, rand_seed, scatter_group):
        return (_vf.scatter(geo, group, keep, mode, count, points_per_voxel, density, multiply,
                            spread, sdf_domain, isovalue, rand_seed, scatter_group),)


# ═══════════════════════════════════════════════════════════════ Volume SOPs
@_node()
class PCG_VolumeAdjustFog:
    """
    Maps to: Volume Adjust Fog. Pre-process (overwrite with Initial Value, complement), an adjustment of Adjust Value ×
    pattern (constant / random / noise / line / radial / bounding box, through the Remap Ramp, scaled to Range) combined
    by Operation, post-process (scale, add, clamp, complement), blended by Blend Amount or a blend volume.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "operation": _menu(("add", "set", "subtract", "multiply", "minimum", "maximum")),
                             "value": _f(1.0), "pattern": _menu(_vm.ADJUST_PATTERNS),
                             "range_min": _f(0.0), "range_max": _f(1.0), "ramp": _s(""),
                             "element_size": _f(1.0, 1e-6), **_v3("offset"), "rand_seed": _i(0, 0, 1 << 31),
                             **_v3("line_origin"), **_v3("line_dir", (0.0, 1.0, 0.0)),
                             **_v3("radial_center"), "radial_radius": _f(1.0, 1e-6),
                             "pre_overwrite": _b(False), "initial_value": _f(0.0),
                             "pre_complement": _b(False), "post": _b(False), "post_scale": _f(1.0),
                             "post_add": _f(0.0), "post_clamp_min": _b(False), "clamp_min": _f(0.0),
                             "post_clamp_max": _b(False), "clamp_max": _f(1.0),
                             "post_complement": _b(False), "blend": _menu(("constant", "volume")),
                             "blend_amount": _f(1.0, 0.0, 1.0), "blend_name": _s("")},
                "optional": {"blend_volume": (GEO,)}}

    def run(self, geo, group, operation, value, pattern, range_min, range_max, ramp, element_size,
            offset_x, offset_y, offset_z, rand_seed, line_origin_x, line_origin_y, line_origin_z,
            line_dir_x, line_dir_y, line_dir_z, radial_center_x, radial_center_y, radial_center_z,
            radial_radius, pre_overwrite, initial_value, pre_complement, post, post_scale, post_add,
            post_clamp_min, clamp_min, post_clamp_max, clamp_max, post_complement, blend,
            blend_amount, blend_name, blend_volume=None):
        return (_vm.adjust_fog(geo, group, operation, value, pattern, range_min, range_max, ramp,
                               element_size, (offset_x, offset_y, offset_z), rand_seed,
                               (line_origin_x, line_origin_y, line_origin_z),
                               (line_dir_x, line_dir_y, line_dir_z),
                               (radial_center_x, radial_center_y, radial_center_z), radial_radius,
                               pre_overwrite, initial_value, pre_complement, post, post_scale,
                               post_add, post_clamp_min, clamp_min, post_clamp_max, clamp_max,
                               post_complement, blend, blend_amount, blend_volume, blend_name),)


@_node(_REP)
class PCG_VolumeBound:
    """
    Maps to: Volume Bound. A box around the voxels meeting the condition (≥ / > / ≤ / < / = Bounding Value), on the voxel
    edges (±½ voxel) and expanded by Voxel Padding (−0.5 = bound on voxel centres). No matching voxel: no box.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "region": _menu(_vm.BOUND_REGIONS),
                             "value": _f(0.0), **_v3("padding", (0.0, 0.0, 0.0))}}

    def run(self, geo, group, region, value, padding_x, padding_y, padding_z):
        g, r = _vm.bound(geo, group, region, value, (padding_x, padding_y, padding_z))
        return (g, _rep(r))


@_node()
class PCG_VolumeBreak:
    """
    Maps to: Volume Break. Cuts polygons with the zero surface of the SDF in the second input (fog: its 0.5 contour),
    linear along edges; keeps inside, outside or both, with inside / outside primitive groups. Snapping Tolerance
    snaps near-zero point distances to the surface. Holes are not closed.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "volume": (GEO,), "volume_group": _vg(),
                             "keep": _menu(("both", "inside", "outside")), "snap": _f(0.0, 0.0),
                             "create_groups": _b(True), "inside_group": _s("inside"),
                             "outside_group": _s("outside")}}

    def run(self, geo, volume, volume_group, keep, snap, create_groups, inside_group, outside_group):
        return (_vm.volume_break(geo, volume, volume_group, keep, create_groups, inside_group,
                                 outside_group, snap),)


@_node(_REP)
class PCG_VolumeCompress:
    """
    Maps to: Volume Compress. 16³ tiles whose values differ by at most Constant Tolerance become constant; values are
    quantised to Quantization Tolerance (ordered dithering optional); Use 16bit Float rounds to half floats; a mask
    (second input, strictly above Mask Minimum / below Mask Maximum, invertible) zeroes the rest. Values are what a
    compressed Houdini volume would read back.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "constant_tolerance": _f(0.0, 0.0),
                             "quantization_tolerance": _f(0.0, 0.0), "dither": _menu(_vm.COMPRESS_DITHER),
                             "half": _b(False), "mask_group": _s(""), "use_min": _b(False),
                             "mask_min": _f(0.0), "use_max": _b(False), "mask_max": _f(1.0),
                             "invert_mask": _b(False)},
                "optional": {"mask": (GEO,)}}

    def run(self, geo, group, constant_tolerance, quantization_tolerance, dither, half, mask_group,
            use_min, mask_min, use_max, mask_max, invert_mask, mask=None):
        g, r = _vm.compress(geo, group, constant_tolerance, quantization_tolerance, dither, half,
                            mask, mask_group, use_min, mask_min, use_max, mask_max, invert_mask)
        return (g, _rep(r))


@_node()
class PCG_VolumeConvolve:
    """
    Maps to: Volume Convolve 3×3×3. 27 coefficients (three z planes z−1 / z / z+1, each 3 rows y−1..y+1 of x−1..x+1,
    whitespace separated); Normalize Kernel divides by their sum; Add, or Add Absolute (|coefficient × voxel|).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(),
                             "kernel": ("STRING", {"default": "0 0 0 0 1 0 0 0 0\n0 1 0 1 1 1 0 1 0\n0 0 0 0 1 0 0 0 0",
                                                   "multiline": True}),
                             "normalize": _b(True), "operation": _menu(_vm.CONVOLVE_OPS)}}

    def run(self, geo, group, kernel, normalize, operation):
        vals = [float(x) for x in str(kernel).replace(",", " ").split()]
        if len(vals) != 27:
            raise ValueError(f"The kernel needs 27 numbers, got {len(vals)}")
        return (_vm.convolve3(geo, group, vals, normalize, operation),)


@_node()
class PCG_VolumeFeather:
    """
    Maps to: Volume Feather. Caps how fast values may change: High to Low v = max(v, w − rate·d) (fog grows),
    otherwise min(v, w + rate·d) (fog shrinks), over the 26 neighbours until stable. The rate comes from the Feather
    Mode (change per distance / per voxel, distance or voxels for a unit change, slope angle).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "mode": _menu(_vm.FEATHER_MODES),
                             "amount": _f(1.0, 0.0), "high_to_low": _b(True),
                             "border": _menu(("use_volume", "constant", "repeat", "streak")),
                             "border_value": _f(0.0)}}

    def run(self, geo, group, mode, amount, high_to_low, border, border_value):
        return (_vm.feather(geo, group, mode, amount, high_to_low, border, border_value),)


@_node()
class PCG_VolumeFFT:
    """
    Maps to: Volume FFT. Volumes in (real, imaginary) pairs; a lone real volume gets a zero imaginary part (written to
    a new <name>_imag volume). Invert computes the inverse; Normalize makes forward then inverse the identity; Center DC
    shifts zero frequency to the centre; Compute 2D Slices transforms each slice along the axis.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "center_dc": _b(False), "invert": _b(False),
                             "normalize": _b(True), "slices": _b(False), "axis": _menu(("z", "y", "x"))}}

    def run(self, geo, group, center_dc, invert, normalize, slices, axis):
        return (_vm.fft(geo, group, center_dc, invert, normalize, slices, axis),)


@_node()
class PCG_VolumeFromAttrib:
    """
    Maps to: Volume from Attrib. Writes a point attribute (second input) into the volumes: Accumulated (trilinear splat,
    normalised where the total weight exceeds Threshold; Bandwidth widens the splat), or Extrapolated (nearest point within
    Max Extrapolation Distance / cells). Combined with the volume by Calculation with pre / post add and multiply.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "points": (GEO,), "group": _vg(),
                             "point_group": ("STRING", {"default": ""}), "attribute": _s("density"),
                             "use_attribute": _b(True), "accumulated": _b(True), "extrapolated": _b(False),
                             "max_cells": _i(1, 0, 1000), "max_dist": _f(0.0, 0.0), "threshold": _f(1.0, 0.0),
                             "bandwidth": _f(0.0, 0.0), "scale_by_volume": _b(False),
                             "calculation": _menu(_vm.FROM_ATTRIB_OPS), "dest_add": _f(0.0), "dest_mul": _f(1.0),
                             "src_add": _f(0.0), "src_mul": _f(1.0), "post_add": _f(0.0),
                             "post_mul": _f(1.0)}}

    def run(self, geo, points, group, point_group, attribute, use_attribute, accumulated,
            extrapolated, max_cells, max_dist, threshold, bandwidth, scale_by_volume, calculation,
            dest_add, dest_mul, src_add, src_mul, post_add, post_mul):
        return (_vm.from_attrib(geo, points, group, point_group, attribute, use_attribute, accumulated,
                                extrapolated, max_cells, max_dist, threshold, bandwidth,
                                scale_by_volume, calculation, dest_add, dest_mul, src_add, src_mul,
                                post_add, post_mul),)


@_node()
class PCG_VolumeMerge:
    """
    Maps to: Volume Merge. Flattens the Merge Group volumes (second input, or the first input's other volumes) into
    the base volume: Copy (the last), Add, Multiply, Maximum, Minimum, Average; Dest / Source pre add-multiply,
    post add-multiply, clamps. Clamp at Volume Boundary: B contributes 0 outside its own box.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "merge_group": _vg(),
                             "method": _menu(("add", "copy", "multiply", "maximum", "minimum", "average")),
                             "clamp_boundary": _b(True), "dest_add": _f(0.0), "dest_mul": _f(1.0),
                             "src_add": _f(0.0), "src_mul": _f(1.0), "post_add": _f(0.0),
                             "post_mul": _f(1.0), "use_min": _b(False), "clamp_min": _f(0.0),
                             "use_max": _b(False), "clamp_max": _f(1.0)},
                "optional": {"merge": (GEO,)}}

    def run(self, geo, group, merge_group, method, clamp_boundary, dest_add, dest_mul, src_add,
            src_mul, post_add, post_mul, use_min, clamp_min, use_max, clamp_max, merge=None):
        return (_vm.merge_volumes(geo, merge, group, merge_group, method, clamp_boundary, dest_add,
                                  dest_mul, src_add, src_mul, post_add, post_mul, use_min, clamp_min,
                                  use_max, clamp_max),)


@_node()
class PCG_VolumeOpticalFlow:
    """
    Maps to: Volume Optical Flow. The displacement from each source voxel to the matching goal values (Horn–Schunck
    with warping, coarse to fine over Pyramid Levels scaled by Pyramid Scale, Iterations per level, displacement blurred
    by Blurring Window Radius, box or Gaussian; Approximation Window Radius pre-smooths the images). Outputs
    <source>.x / .y / .z in world units.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": (GEO,), "goal": (GEO,), "group": _vg(), "goal_group": _vg(),
                             "tolerance": _f(0.0, 0.0), "blur_radius": _i(1, 0, 20), "gaussian": _b(False),
                             "levels": _i(3, 1, 8), "pyramid_scale": _f(0.5, 0.1, 0.9),
                             "iterations": _i(4, 1, 100), "approx_radius": _i(2, 0, 20)}}

    def run(self, source, goal, group, goal_group, tolerance, blur_radius, gaussian, levels,
            pyramid_scale, iterations, approx_radius):
        return (_vm.optical_flow(source, goal, group, goal_group, tolerance, blur_radius, gaussian,
                                 levels, pyramid_scale, iterations, approx_radius),)


@_node()
class PCG_VolumePatch:
    """
    Maps to: Volume Patch. Fills the masked region (Mask ≥ Cutoff) of the background with the foreground's features while
    matching the background on the region's border (Poisson: ∇²u = ∇²foreground inside, u = background outside). Use
    Foreground as Laplacian: the foreground already is the Laplacian.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "background": _s("background"), "foreground": _s("foreground"),
                             "mask": _s("mask"), "cutoff": _f(0.5), "foreground_is_laplacian": _b(False),
                             "iterations": _i(2000, 1, 100000)}}

    def run(self, geo, background, foreground, mask, cutoff, foreground_is_laplacian, iterations):
        return (_vm.patch(geo, background, foreground, mask, cutoff, foreground_is_laplacian,
                          iterations),)


@_node()
class PCG_VolumeRamp:
    """
    Maps to: Volume Ramp. Remaps the volumes: Source Min / Max -> 0..1 (clamped) -> the scalar ramp -> Dest Min / Max,
    or through a colour ramp into three volumes <name>.x / .y / .z (New Name "Cd" gives Cd.x / .y / .z).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "new_name": _s(""), "src_min": _f(0.0),
                             "src_max": _f(1.0), "dest_min": _f(0.0), "dest_max": _f(1.0),
                             "use_color": _b(False), "ramp": _s("0:0 1:1"),
                             "color_ramp": _s("0:0,0,0 1:1,1,1")}}

    def run(self, geo, group, new_name, src_min, src_max, dest_min, dest_max, use_color, ramp,
            color_ramp):
        return (_vm.volume_ramp(geo, group, new_name, src_min, src_max, dest_min, dest_max, use_color,
                                ramp, color_ramp),)


@_node()
class PCG_VolumeRasterizeCurve:
    """
    Maps to: Volume Rasterize Curve (and Volume Rasterize Hair). Curves as tubes of radius width / 2 × stroke_pressure
    (pscale when width is missing): Mask = density (smooth from 1 on the axis to 0 at the tube surface), Color = density +
    a vector Cd volume, SDF = union of the tubes. Fade lowers the density along the stroke, Flow Rate scales it.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "output": _menu(("mask", "color", "sdf")),
                             "voxel_size": _f(0.05, 1e-6, 1e6, 0.001), "density_scale": _f(1.0),
                             "fade": _f(0.0, 0.0, 1.0), "flow_rate": _f(1.0, 0.0), "name": _s("density")}}

    def run(self, geo, output, voxel_size, density_scale, fade, flow_rate, name):
        return (_vm.rasterize_curve(geo, output, voxel_size, density_scale, fade, flow_rate, name),)


@_node()
class PCG_VolumeRasterizeParticles:
    """
    Maps to: Volume Rasterize Particles. Each point adds kernel(|x − p| / r) × coverage to density (Gaussian / Box /
    Cubic Spline), r = max(pscale × Particle Scale, Minimum Filter Size voxels); listed attributes become
    coverage-weighted averages. Into the first input's volumes when given (same names), else a new grid at Voxel Size.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"points": (GEO,), "point_group": ("STRING", {"default": ""}),
                             "filter": _menu(_vm.PARTICLE_FILTERS), "coverage_attribute": _s(""),
                             "coverage_scale": _f(1.0), "particle_scale": _f(1.0, 0.0),
                             "min_filter": _f(1.0, 0.0), "attributes": _s(""),
                             "voxel_size": _f(0.1, 1e-6, 1e6, 0.001)},
                "optional": {"destination": (GEO,)}}

    def run(self, points, point_group, filter, coverage_attribute, coverage_scale, particle_scale,
            min_filter, attributes, voxel_size, destination=None):
        return (_vm.rasterize_particles(destination, points, point_group, filter, coverage_attribute,
                                        coverage_scale, particle_scale, min_filter, attributes,
                                        voxel_size),)


@_node()
class PCG_VolumeRasterizePoints:
    """
    Maps to: Volume Rasterize Points (and Volume Rasterize). Points as spheres of pscale + Exterior Pad: density 1 inside
    Solid Ratio × r, falling to 0 at r (linear or smooth), × Density Scale × point density; Merge Method maximum / add;
    optional noise; listed attributes into same-named volumes. Into the first input's volumes or a new grid.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"points": (GEO,), "point_group": ("STRING", {"default": ""}),
                             "density_scale": _f(1.0), "solid_ratio": _f(0.0, 0.0, 1.0),
                             "smooth": _b(True), "exterior_pad": _f(0.0), "attributes": _s(""),
                             "voxel_size": _f(0.1, 1e-6, 1e6, 0.001),
                             "merge_method": _menu(("maximum", "add")), "noise_amp": _f(0.0),
                             "noise_size": _f(1.0, 1e-6), "rand_seed": _i(0, 0, 1 << 31)},
                "optional": {"destination": (GEO,)}}

    def run(self, points, point_group, density_scale, solid_ratio, smooth, exterior_pad, attributes,
            voxel_size, merge_method, noise_amp, noise_size, rand_seed, destination=None):
        return (_vm.rasterize_points(destination, points, point_group, density_scale, solid_ratio,
                                     smooth, exterior_pad, attributes, voxel_size, merge_method,
                                     noise_amp, noise_size, rand_seed),)


@_node(_REP)
class PCG_VolumeReduce:
    """
    Maps to: Volume Reduce. One number per volume (maximum, minimum, average, sum, median at Percentile, RMS, sums
    and extremes of absolutes, sum of squares; active voxels only for VDBs), optionally × voxel length / area /
    volume; stored as a detail attribute, a prim attribute, or the volume itself becomes constant.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "reduction": _menu(_vm.REDUCE_OPS),
                             "percentile": _f(50.0, 0.0, 100.0), "scale_by": _menu(_vm.REDUCE_SCALE),
                             "store": _menu(_vm.REDUCE_STORE), "attribute": _s("")}}

    def run(self, geo, group, reduction, percentile, scale_by, store, attribute):
        g, r = _vm.reduce(geo, group, reduction, percentile, scale_by, store, attribute)
        return (g, _rep(r))


@_node()
class PCG_VolumeResize:
    """
    Maps to: Volume Resize. New bounds on the same voxel lattice (no filtering): the second input's bounds or Size /
    Center, Replace / Intersect / Union with the current box, Voxel Padding; new voxels repeat the edge (streak).
    Keep Data off: an empty volume. Limit Resolution caps each axis.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "combine": _menu(_vm.RESIZE_COMBINE),
                             **_v3("size", (1.0, 1.0, 1.0), 0.0), **_v3("center"),
                             **_v3("padding", (0.0, 0.0, 0.0)), "keep_data": _b(True),
                             "limit_res": _b(False), "max_res": _i(512, 2, 1 << 16)},
                "optional": {"reference": (GEO,)}}

    def run(self, geo, group, combine, size_x, size_y, size_z, center_x, center_y, center_z,
            padding_x, padding_y, padding_z, keep_data, limit_res, max_res, reference=None):
        return (_vm.resize(geo, reference, group, combine, (size_x, size_y, size_z),
                           (center_x, center_y, center_z), (padding_x, padding_y, padding_z),
                           keep_data, limit_res, max_res),)


@_node()
class PCG_VolumeSlice:
    """
    Maps to: Volume Slice. A plane through the volumes (XY / YZ / ZX; relative offset −1..1 or a world position +
    offset; snap to voxels) as a mesh or points with the volumes' values in one attribute (one component per volume),
    or as thin volumes. Visualize writes Cd through a ramp over the Visualization Range (several volumes -> RGB).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "method": _menu(_vm.SLICE_METHODS),
                             "plane": _menu(_vm.SLICE_PLANES), "relative": _b(True), **_v3("position"),
                             "offset": _f(0.0), "snap": _b(False), "attribute": _s(""),
                             "visualize": _b(True), "vis_min": _f(0.0), "vis_max": _f(1.0), "ramp": _s(""),
                             "keep": _b(False)}}

    def run(self, geo, group, method, plane, relative, position_x, position_y, position_z, offset,
            snap, attribute, visualize, vis_min, vis_max, ramp, keep):
        return (_vm.slice_volumes(geo, group, method, plane, relative,
                                  (position_x, position_y, position_z), offset, snap, attribute,
                                  visualize, vis_min, vis_max, ramp, keep),)


@_node()
class PCG_VolumeSplice:
    """
    Maps to: Volume Splice. Same-named volumes on the same voxel lattice are joined into one volume covering them all;
    where they overlap the voxel comes from the volume whose centre is nearest. Delete Original Volumes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "delete_original": _b(True)}}

    def run(self, geo, group, delete_original):
        return (_vm.splice(geo, group, delete_original),)


@_node()
class PCG_VolumeStamp:
    """
    Maps to: Volume Stamp. The volumes of the third input (matched to the destination by name) are placed on every
    point of the second input (translated to P, scaled by pscale, rotated by orient) and merged into the destination
    (maximum / add / minimum / copy / average).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "points": (GEO,), "stamps": (GEO,), "group": _vg(),
                             "point_group": ("STRING", {"default": ""}),
                             "merge_method": _menu(_vm.STAMP_MERGE)}}

    def run(self, geo, points, stamps, group, point_group, merge_method):
        return (_vm.stamp(geo, points, stamps, group, point_group, merge_method),)


@_node()
class PCG_VolumeTrail:
    """
    Maps to: Volume Trail. A polyline per point through the velocity of the second input (a vector volume or
    vel.x / .y / .z), RK2: Trail Length in seconds (time) or path length (distance), × traillen; a fixed Number of
    Steps or CFL-limited steps (CFL × voxel size, at most Max Steps). Visualize: Cd from the speed (Detect Range).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "velocity": (GEO,), "point_group": ("STRING", {"default": ""}),
                             "vel_name": _s(""), "method": _menu(("time", "distance")),
                             "length": _f(1.0, 0.0), "use_cfl": _b(False), "cfl": _f(1.0, 0.01),
                             "steps": _i(10, 1, 100000), "max_steps": _i(1000, 1, 1000000),
                             "keep": _b(False), "visualize": _b(True), "detect_range": _b(True),
                             "maximum": _f(1.0, 0.0), "ramp": _s("")}}

    def run(self, geo, velocity, point_group, vel_name, method, length, use_cfl, cfl, steps,
            max_steps, keep, visualize, detect_range, maximum, ramp):
        return (_vm.trail(geo, velocity, point_group, vel_name, method, length, use_cfl, cfl, steps,
                          max_steps, keep, visualize, detect_range, maximum, ramp),)


@_node()
class PCG_VolumeVelocity:
    """
    Maps to: Volume Velocity. Adds to the selected velocity volume (a vector volume, or the first three scalar ones):
    a uniform velocity, a vortex (centre, axis, angular velocity, radius), divergence-free curl noise (scale, swirl
    size, grain, offset, attenuation, turbulence octaves) and velocity extrapolated from the second input's points;
    optionally masked by a third-input volume (expansion, comparison, cutoff).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "group": _vg(), "uniform": _b(False),
                             **_v3("constant"), "vortex": _b(False), **_v3("center"),
                             **_v3("direction", (0.0, 1.0, 0.0)), "angular": _f(1.0),
                             "vortex_radius": _f(0.0, 0.0), "curl": _b(False), "curl_scale": _f(1.0),
                             "swirl_size": _f(1.0, 1e-6), "grain": _f(0.5, 0.0), **_v3("curl_offset"),
                             "attenuation": _f(1.0), "turbulence": _i(3, 1, 10),
                             "rand_seed": _i(0, 0, 1 << 31), "point_velocity": _b(False),
                             "attribute": _s("v"), "point_scale": _f(1.0), "extrap_dist": _f(1.0, 0.0),
                             "apply_mask": _b(False), "mask_group": _s(""), "expansion": _f(0.0, 0.0),
                             "comparison": _menu(("greater", "less", "greaterequal", "lessequal")),
                             "cutoff": _f(0.0)},
                "optional": {"points": (GEO,), "mask": (GEO,)}}

    def run(self, geo, group, uniform, constant_x, constant_y, constant_z, vortex, center_x,
            center_y, center_z, direction_x, direction_y, direction_z, angular, vortex_radius, curl,
            curl_scale, swirl_size, grain, curl_offset_x, curl_offset_y, curl_offset_z, attenuation,
            turbulence, rand_seed, point_velocity, attribute, point_scale, extrap_dist, apply_mask,
            mask_group, expansion, comparison, cutoff, points=None, mask=None):
        return (_vm.velocity(geo, points, mask, group, uniform, (constant_x, constant_y, constant_z),
                             vortex, (center_x, center_y, center_z),
                             (direction_x, direction_y, direction_z), angular, vortex_radius, curl,
                             curl_scale, swirl_size, grain, (curl_offset_x, curl_offset_y, curl_offset_z),
                             attenuation, turbulence, rand_seed, point_velocity, attribute, point_scale,
                             extrap_dist, apply_mask, mask_group, expansion, comparison, cutoff),)


@_node()
class PCG_VolumeVelocityFromCurves:
    """
    Maps to: Volume Velocity from Curves. Each voxel averages the tangents of curve segments within the lookup radius
    (constant, or the distance to the N-th nearest curve × multiplier), weighted by (1 − d / R)² × an optional prim
    weight attribute; optionally smoothed. The grid comes from a reference volume (third input), or the curves' bounds
    (and the surface's, second input) at Voxel Size.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"curves": (GEO,), "voxel_size": _f(0.1, 1e-6, 1e6, 0.001),
                             "radius_mode": _menu(("constant", "minimum")), "radius": _f(0.5, 1e-6),
                             "min_curves": _i(3, 1, 1000), "radius_mult": _f(1.0, 0.0),
                             "smooth": _b(False), "voxel_radius": _i(1, 0, 20), "blur_iters": _i(1, 0, 100),
                             "use_weight": _b(False), "weight_attribute": _s(""), "name": _s("vel")},
                "optional": {"surface": (GEO,), "reference": (GEO,)}}

    def run(self, curves, voxel_size, radius_mode, radius, min_curves, radius_mult, smooth,
            voxel_radius, blur_iters, use_weight, weight_attribute, name, surface=None,
            reference=None):
        return (_vm.velocity_from_curves(curves, surface, reference, voxel_size, radius, radius_mode,
                                         min_curves, radius_mult, smooth, voxel_radius, blur_iters,
                                         use_weight, weight_attribute, name),)


@_node()
class PCG_VolumeVelocityFromSurface:
    """
    Maps to: Volume Velocity from Surface. Flow inside a closed surface driven by its divergence attribute (point or
    prim): sources near the surface, ∇²p = divergence inside with zero flux through the surface, v = ∇p -- the flow
    leaves high-divergence regions for low ones. Optional collision SDF output.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "voxel_size": _f(0.1, 1e-6, 1e6, 0.001),
                             "ext_band": _f(0.2, 0.0), "iterations": _i(500, 1, 100000),
                             "divergence_attribute": _s("divergence"), "name": _s("vel"),
                             "collision": _b(False), "collision_name": _s("collision")}}

    def run(self, geo, voxel_size, ext_band, iterations, divergence_attribute, name, collision,
            collision_name):
        return (_vm.velocity_from_surface(geo, voxel_size, ext_band, iterations, divergence_attribute,
                                          name, collision, collision_name),)


@_node()
class PCG_VolumeVisualization:
    """
    Maps to: Volume Visualization. How the viewport draws the volumes: Smoke (ray-marched; density = optical thickness
    per unit length × Density Scale, self-shadowing × Shadow Scale, Shadow Color), Rainbow, Iso Surface (at Iso Value,
    closed at the grid boundary) or Invisible. Density / Diffuse / Emission fields by name; a scalar diffuse field goes
    through the ramp (clamped / periodic), a vector one is RGB; Minimum / Maximum remap the fields. Writes volvis_*
    detail attributes; the geometry is unchanged.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo": (GEO,), "mode": _menu(_vv.MODES), "range_min": _f(0.0),
                             "range_max": _f(1.0), "density_scale": _f(1.0, 0.0), "shadow_scale": _f(1.0, 0.0),
                             "density_field": _s(""), "diffuse_field": _s(""), "color_r": _f(1.0, 0.0, 1.0),
                             "color_g": _f(1.0, 0.0, 1.0), "color_b": _f(1.0, 0.0, 1.0),
                             "shadow_color_r": _f(0.0, 0.0, 1.0), "shadow_color_g": _f(0.0, 0.0, 1.0),
                             "shadow_color_b": _f(0.0, 0.0, 1.0), "ramp_mode": _menu(_vv.RAMP_MODES),
                             "ramp": _s(""), "emit_field": _s(""), "emit_scale": _f(0.0, 0.0),
                             "emit_color_r": _f(1.0, 0.0, 1.0), "emit_color_g": _f(1.0, 0.0, 1.0),
                             "emit_color_b": _f(1.0, 0.0, 1.0), "iso": _f(0.0),
                             "max_res": _i(128, 8, 512)}}

    def run(self, geo, mode, range_min, range_max, density_scale, shadow_scale, density_field,
            diffuse_field, color_r, color_g, color_b, shadow_color_r, shadow_color_g, shadow_color_b,
            ramp_mode, ramp, emit_field, emit_scale, emit_color_r, emit_color_g, emit_color_b, iso,
            max_res):
        return (_vv.visualize(geo, mode, density_field, diffuse_field, emit_field, range_min, range_max,
                              density_scale, shadow_scale, (color_r, color_g, color_b),
                              (shadow_color_r, shadow_color_g, shadow_color_b), ramp_mode, ramp,
                              emit_scale, (emit_color_r, emit_color_g, emit_color_b), iso, max_res),)


_NAMES = {
    "PCG_VDB": "VDB (PCG)",
    "PCG_VDBActivate": "VDB Activate (PCG)",
    "PCG_VDBActivateSDF": "VDB Activate SDF (PCG)",
    "PCG_VDBDensify": "VDB Densify (PCG)",
    "PCG_VDBPrune": "VDB Prune (PCG)",
    "PCG_VDBClip": "VDB Clip (PCG)",
    "PCG_VDBFill": "VDB Fill (PCG)",
    "PCG_VDBTopologyToSDF": "VDB Topology to SDF (PCG)",
    "PCG_VDBDiagnostics": "VDB Diagnostics (PCG)",
    "PCG_VDBVisualizeTree": "VDB Visualize Tree (PCG)",
    "PCG_VDBMetadata": "VDB Metadata (PCG)",
    "PCG_VDBVectorMerge": "VDB Vector Merge (PCG)",
    "PCG_VDBVectorSplit": "VDB Vector Split (PCG)",
    "PCG_VDBTransform": "VDB Transform (PCG)",
    "PCG_VDBLOD": "VDB LOD (PCG)",
    "PCG_VDBMerge": "VDB Merge (PCG)",
    "PCG_VDBSegment": "VDB Segment by Connectivity (PCG)",
    "PCG_VDBRemap": "VDB Remap (PCG)",
    "PCG_ConvertVDB": "Convert VDB (PCG)",
    "PCG_VDBFromPolygons": "VDB from Polygons (PCG)",
    "PCG_VDBFromParticles": "VDB from Particles (PCG)",
    "PCG_VDBFromParticleFluid": "VDB from Particle Fluid (PCG)",
    "PCG_VDBRenormalizeSDF": "VDB Renormalize SDF (PCG)",
    "PCG_VDBRebuildSDF": "VDB Rebuild SDF (PCG)",
    "PCG_VDBMorphSDF": "VDB Morph SDF (PCG)",
    "PCG_VDBFracture": "VDB Fracture (PCG)",
    "PCG_VDBToSpheres": "VDB to Spheres (PCG)",
    "PCG_VDBPlatonic": "VDB Platonic (PCG)",
    "PCG_VDBNoise": "VDB Noise (PCG)",
    "PCG_VDBExtrapolate": "VDB Extrapolate (PCG)",
    "PCG_VDBOcclusionMask": "VDB Occlusion Mask (PCG)",
    "PCG_VDBRay": "VDB Ray (PCG)",
    "PCG_VolumeSDF": "Volume SDF (PCG)",
    "PCG_VDBAnalysis": "VDB Analysis (PCG)",
    "PCG_VDBSmooth": "VDB Smooth (PCG)",
    "PCG_VDBAdvect": "VDB Advect (PCG)",
    "PCG_VDBAdvectPoints": "VDB Advect Points (PCG)",
    "PCG_VDBProjectNonDivergent": "VDB Project Non-Divergent (PCG)",
    "PCG_VDBPotentialFlow": "VDB Potential Flow (PCG)",
    "PCG_VDBCombine": "VDB Combine (PCG)",
    "PCG_VDBResample": "VDB Resample (PCG)",
    "PCG_VDBPointsGroup": "VDB Points Group (PCG)",
    "PCG_VDBScatter": "VDB Scatter (PCG)",
    "PCG_VolumeAdjustFog": "Volume Adjust Fog (PCG)",
    "PCG_VolumeBound": "Volume Bound (PCG)",
    "PCG_VolumeBreak": "Volume Break (PCG)",
    "PCG_VolumeCompress": "Volume Compress (PCG)",
    "PCG_VolumeConvolve": "Volume Convolve 3×3×3 (PCG)",
    "PCG_VolumeFeather": "Volume Feather (PCG)",
    "PCG_VolumeFFT": "Volume FFT (PCG)",
    "PCG_VolumeFromAttrib": "Volume from Attrib (PCG)",
    "PCG_VolumeMerge": "Volume Merge (PCG)",
    "PCG_VolumeOpticalFlow": "Volume Optical Flow (PCG)",
    "PCG_VolumePatch": "Volume Patch (PCG)",
    "PCG_VolumeRamp": "Volume Ramp (PCG)",
    "PCG_VolumeRasterizeCurve": "Volume Rasterize Curve (PCG)",
    "PCG_VolumeRasterizeParticles": "Volume Rasterize Particles (PCG)",
    "PCG_VolumeRasterizePoints": "Volume Rasterize Points (PCG)",
    "PCG_VolumeReduce": "Volume Reduce (PCG)",
    "PCG_VolumeResize": "Volume Resize (PCG)",
    "PCG_VolumeSlice": "Volume Slice (PCG)",
    "PCG_VolumeSplice": "Volume Splice (PCG)",
    "PCG_VolumeStamp": "Volume Stamp (PCG)",
    "PCG_VolumeTrail": "Volume Trail (PCG)",
    "PCG_VolumeVelocity": "Volume Velocity (PCG)",
    "PCG_VolumeVelocityFromCurves": "Volume Velocity from Curves (PCG)",
    "PCG_VolumeVelocityFromSurface": "Volume Velocity from Surface (PCG)",
    "PCG_VolumeVisualization": "Volume Visualization (PCG)",
}

NODE_CLASS_MAPPINGS = {k: globals()[k] for k in _NAMES}
NODE_DISPLAY_NAME_MAPPINGS = dict(_NAMES)
