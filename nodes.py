"""
ComfyUI node definitions.

Uses the V1 schema (INPUT_TYPES / RETURN_TYPES / FUNCTION). Reasons:
  * V1 loads on every version; V3 needs a fairly recent comfy_api;
  * V1 supports WEB_DIRECTORY, needed later for custom widgets (code editor, viewport).
Migrating to V3 is mechanical work; the README shows the V3 version of the same node for comparison.

A custom socket type is just a string, "GEOMETRY" -- ComfyUI's type system only compares strings,
so any Python object can be passed between nodes.
"""
from __future__ import annotations

# The shared layer (types, widget helpers, geo module aliases) is in nodes_common.py; re-exported here unchanged,
# so old code `from .nodes import GEO, _group` needs no change
from .nodes_common import *  # noqa: F401,F403
from .nodes_common import (  # noqa: F401
    _aa, _ablr, _an, _ao, _arn, _bnd, _bool, _bpj, _can, _cbk, _cbrg, _ccmp,
    _cctl, _cdc, _cero, _compute, _cflt, _cflw, _cgen, _chm, _chn, _chyd,
    _clev, _clift, _clip, _clu, _cmrp, _cop, _cpj, _cpt, _creg, _csdf, _cspl,
    _ctr, _ctrn, _cvl, _del, _dev, _dfm, _dsv, _edv, _end, _ex, _exp, _f, _fdt,
    _fmp, _gcache, _gex, _group, _hul, _i, _ins, _jn, _mio, _mir, _ms, _mtr,
    _names, _pex, _pfl, _pj, _pk, _prd, _prom, _ray, _ref, _rmp, _rnd, _scat,
    _sec, _sec_defaults, _seq, _stx, _sub, _t2d, _tmo, _trc, _uvf, _uvl, _uvp, _uvs, _v2d,
    _vor, _vsc, _xfr,
)

# COP nodes from before pcg57 are in nodes_cop.py (moved over unchanged in the split) and imported back here:
# the master registry below references them by name, and `nodes.PCG_COPNoise` still works
from .nodes_cop import (  # noqa: F401
    PCG_COPNoise, PCG_COPShape, PCG_COPGradient, PCG_COPConstant,
    PCG_COPComposite, PCG_COPBlur, PCG_COPResize, PCG_COPImport,
    PCG_COPExport, PCG_COPToDevice, PCG_COPInfo, PCG_COPTransform,
    PCG_COPFlip, PCG_COPCrop, PCG_COPTile, PCG_COPDistort, PCG_COPLevels,
    PCG_COPRemap, PCG_COPQuantize, PCG_COPFit, PCG_COPLuminance, PCG_COPMorph,
    PCG_COPEdge, PCG_COPSharpen, PCG_COPMedian, PCG_COPSDFFromMask,
    PCG_RenderPass, _hscale, PCG_COPHeightToNormal, PCG_COPNormalToHeight,
    PCG_COPHeightToAO, PCG_COPHeightToShadow, PCG_COPRefractFromHeight,
    PCG_COPHeightToCaustics, PCG_COPCombineNormals, PCG_COPConvertNormal,
    PCG_COPErosion, PCG_COPSlope, PCG_COPCurvature, PCG_COPStatistics,
    PCG_COPHistogram, PCG_COPSegment, PCG_COPCompare, PCG_COPMaskByFeature,
    PCG_COPTerrace, PCG_COPThermalErosion, PCG_COPHeightfieldToMesh,
    PCG_COPFlowAccumulation, PCG_COPStreamPower, PCG_COPHydraulicErosion,
    PCG_COPSplatMap, _encode_text, _cond_with_mask, PCG_RegionalPrompt,
    PCG_COPHeightfieldFromDepth, PCG_ControlImage, PCG_IDMasks, PCG_COPWarp,
    PCG_SequenceExport, PCG_SequenceImport, PCG_SequencePick,
)


# ============================================================ generators
class PCG_Grid:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "size_x": _f(10.0, 0.001), "size_z": _f(10.0, 0.001),
            "cols": _i(21, 2, 4096), "rows": _i(21, 2, 4096),
            "plane": (["zx", "xy", "yz"],),
            # pcg98 addition (appended last so old workflows' indices are unchanged; default = previous behaviour)
            "center_x": _f(), "center_y": _f(), "center_z": _f(),
            "rx": _f(0, -3600, 3600, 1.0), "ry": _f(0, -3600, 3600, 1.0),
            "rz": _f(0, -3600, 3600, 1.0),
            "connectivity": (list(build.CONNECTIVITY),),
        }}
    RETURN_TYPES = (GEO,)
    RETURN_NAMES = ("geo",)
    FUNCTION = "run"
    CATEGORY = CAT + "/generate"

    def run(self, size_x, size_z, cols, rows, plane, center_x=0.0, center_y=0.0,
            center_z=0.0, rx=0.0, ry=0.0, rz=0.0, connectivity="quadrilaterals"):
        return (build.grid(size_x, size_z, cols, rows, (center_x, center_y, center_z),
                           plane, (rx, ry, rz), connectivity),)


class PCG_Box:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "size_x": _f(1.0, 0.0), "size_y": _f(1.0, 0.0), "size_z": _f(1.0, 0.0),
            "uniform_scale": _f(1.0, 0.0),
            "cx": _f(), "cy": _f(), "cz": _f(),
            "div_x": _i(2, 2, 512), "div_y": _i(2, 2, 512), "div_z": _i(2, 2, 512),
            # pcg98 addition
            "rx": _f(0, -3600, 3600, 1.0), "ry": _f(0, -3600, 3600, 1.0),
            "rz": _f(0, -3600, 3600, 1.0),
            "prim_type": (["polygon", "points"],),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, size_x, size_y, size_z, uniform_scale, cx, cy, cz,
            div_x, div_y, div_z, rx=0.0, ry=0.0, rz=0.0, prim_type="polygon"):
        return (build.box((size_x, size_y, size_z), (cx, cy, cz),
                          (div_x, div_y, div_z), uniform_scale, (rx, ry, rz),
                          prim_type == "points"),)


class PCG_Sphere:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"radius": _f(1.0, 0.0),
                             "cols": _i(24, 3, 1024), "rows": _i(16, 3, 1024),
                             # pcg98 addition. radius has always been a uniform scale (Houdini's Uniform Scale);
                             # the new radius_x/y/z are Houdini's Radius (a radius per axis)
                             "prim_type": (list(build.SPHERE_TYPES),),
                             "frequency": _i(2, 1, 64),
                             "radius_x": _f(1.0, 0.0), "radius_y": _f(1.0, 0.0),
                             "radius_z": _f(1.0, 0.0),
                             "center_x": _f(), "center_y": _f(), "center_z": _f(),
                             "rx": _f(0, -3600, 3600, 1.0), "ry": _f(0, -3600, 3600, 1.0),
                             "rz": _f(0, -3600, 3600, 1.0),
                             "orientation": (list(build.AXES),)}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, radius, cols, rows, prim_type="polygon_mesh", frequency=2,
            radius_x=1.0, radius_y=1.0, radius_z=1.0, center_x=0.0, center_y=0.0,
            center_z=0.0, rx=0.0, ry=0.0, rz=0.0, orientation="y"):
        return (build.sphere(radius, cols, rows, (center_x, center_y, center_z), prim_type,
                             frequency, (radius_x, radius_y, radius_z), (rx, ry, rz),
                             orientation),)


class PCG_Tube:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "radius1": _f(1.0, 0.0), "radius2": _f(1.0, 0.0),
            "height": _f(2.0, 0.0), "cols": _i(16, 3, 1024), "rows": _i(2, 2, 1024),
            "caps": ("BOOLEAN", {"default": True}),
            # pcg98 addition
            "orientation": (list(build.AXES),),
            "center_x": _f(), "center_y": _f(), "center_z": _f(),
            "rx": _f(0, -3600, 3600, 1.0), "ry": _f(0, -3600, 3600, 1.0),
            "rz": _f(0, -3600, 3600, 1.0),
            "radius_scale": _f(1.0, 0.0),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, radius1, radius2, height, cols, rows, caps, orientation="y",
            center_x=0.0, center_y=0.0, center_z=0.0, rx=0.0, ry=0.0, rz=0.0,
            radius_scale=1.0):
        return (build.tube(radius1, radius2, height, cols, rows,
                           (center_x, center_y, center_z), caps, (rx, ry, rz),
                           orientation, radius_scale),)


class PCG_Line:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"dx": _f(0.0), "dy": _f(1.0), "dz": _f(0.0),
                             "length": _f(1.0, 0.0), "points": _i(2, 2, 100000),
                             # pcg98 addition
                             "origin_x": _f(), "origin_y": _f(), "origin_z": _f()}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, dx, dy, dz, length, points, origin_x=0.0, origin_y=0.0, origin_z=0.0):
        return (build.line((origin_x, origin_y, origin_z), (dx, dy, dz), length, points),)


from .geo import curvedraw as _cd                          # noqa: E402


class PCG_Curve:
    """
    Corresponds to: Curve. A curve clicked out in the viewport (pcg103). With this node selected, the viewport enters draw mode:
    left-click on empty space adds a point (hitting geometry puts it on the surface, otherwise on the construction plane), drag a point to move it,
    Ctrl + click a segment inserts a point, Delete while hovering a point removes it, clicking the first point closes the curve; Alt + left button orbits as usual.
    Points are stored in the Points text box, one x, y, z per line, and can be edited by hand (see geo/curvedraw.py).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "points": ("STRING", {"default": "", "multiline": True,
                                  "tooltip": "One point x, y, z per line; written automatically when drawing in the viewport"}),
            "prim_type": (list(_cd.PRIM_TYPES),),
            "closed": ("BOOLEAN", {"default": False}),
            "order": _i(4, 2, 11),
            "reverse": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, points, prim_type="polygon", closed=False, order=4, reverse=False):
        return (_cd.curve(points, prim_type, closed, order, reverse),)


class PCG_Torus:
    """
    Torus. Rows = segments around the **cross-section**, Cols = segments around the **main circle**.

    Both directions are periodic, so neither side gets duplicate end points -- an extra ring of coincident points would create
    zero-area quads on the seam, with nan normals there, visible only with the seam facing the camera. This is also
    where its Rows/Cols differ from Grid / Tube: those two are **end-point counts**, here they are segment counts.

    Has periodic uv. Measured convergence to the analytic values: at cols=512, surface area 11.84304 (analytic 4π²Rr =
    11.84353), volume 1.77631 (analytic 2π²Rr² = 1.77653).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "radius": _f(1.0, 0.0), "section_radius": _f(0.3, 0.0),
            "rows": _i(12, 3, 1024), "cols": _i(24, 3, 1024),
            "plane": (["zx", "xy", "yz"],),
            "center_x": _sec("Center", _f(0.0)),
            "center_y": _sec("Center", _f(0.0)),
            "center_z": _sec("Center", _f(0.0)),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, radius, section_radius, rows, cols, plane,
            center_x, center_y, center_z):
        return (build.torus(radius, section_radius, rows, cols,
                            (center_x, center_y, center_z), plane),)


# ============================================================ modifiers
class PCG_Transform:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "tx": _f(), "ty": _f(), "tz": _f(),
            "rx": _f(0, -3600, 3600, 1.0), "ry": _f(0, -3600, 3600, 1.0),
            "rz": _f(0, -3600, 3600, 1.0),
            "sx": _f(1.0), "sy": _f(1.0), "sz": _f(1.0),
            "group": _group(),
            # pcg85 addition (appended last so old workflows' indices are unchanged). Default xyz = Houdini's Rx Ry Rz;
            # choose zyx to reproduce pre-pcg85 results
            "rotate_order": (list(ops.ROTATE_ORDERS), {
                "tooltip": "Rotation order: xyz = X first, then Y, then Z (Houdini default)"}),
            # pcg98 addition (default = previous behaviour: SRT, no shear, pivot at origin)
            "xform_order": (list(ops.XFORM_ORDERS),),
            "shear_xy": _f(), "shear_xz": _f(), "shear_yz": _f(),
            "uniform_scale": _f(1.0),
            "px": _f(), "py": _f(), "pz": _f(),
            "prx": _f(0, -3600, 3600, 1.0), "pry": _f(0, -3600, 3600, 1.0),
            "prz": _f(0, -3600, 3600, 1.0),
            "invert": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, tx, ty, tz, rx, ry, rz, sx, sy, sz, group="",
            rotate_order="xyz", xform_order="srt", shear_xy=0.0, shear_xz=0.0,
            shear_yz=0.0, uniform_scale=1.0, px=0.0, py=0.0, pz=0.0,
            prx=0.0, pry=0.0, prz=0.0, invert=False):
        return (ops.transform(geo, (tx, ty, tz), (rx, ry, rz), (sx, sy, sz),
                              pivot=(px, py, pz), group=group, rotate_order=rotate_order,
                              xform_order=xform_order, shear=(shear_xy, shear_xz, shear_yz),
                              uniform_scale=uniform_scale, pivot_rotate=(prx, pry, prz),
                              invert=invert),)


class PCG_Merge:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geo1": (GEO,)},
                "optional": {f"geo{i}": (GEO,) for i in range(2, 7)}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo1, **kw):
        return (ops.merge(geo1, *[kw.get(f"geo{i}") for i in range(2, 7)]),)


class PCG_Normal:
    """
    Mirrors Houdini's Normal SOP.

    point  smooth point normals, one normal per point -- hard edges are impossible
    vertex one normal per corner, grouped by cusp_angle -- the only way to get hard edges
    prim   one normal per face, for computations like copy/align, not for shading
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "add_to": (["point", "vertex", "prim", "detail"],),
            "cusp_angle": _f(60.0, 0.0, 180.0, 1.0),
        }, "optional": {"group": _group(),
                        # pcg98 addition; the first = the area weighting used all along
                        "weighting": (list(ops.NORMAL_WEIGHTS),),
                        # pcg100 addition, default = previous behaviour (see ops.normal_sop)
                        "group_type": (list(ops.NORMAL_GROUP_TYPES),),
                        "normal_name": ("STRING", {"default": "N"}),
                        "compute_normals": ("BOOLEAN", {"default": True}),
                        "keep_zero": ("BOOLEAN", {"default": False}),
                        "make_unit": ("BOOLEAN", {"default": False}),
                        "reverse": ("BOOLEAN", {"default": False})}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, add_to, cusp_angle, group="", weighting="by_face_area",
            group_type="guess", normal_name="N", compute_normals=True,
            keep_zero=False, make_unit=False, reverse=False):
        return (ops.normal_sop(geo, add_to, cusp_angle, group, weighting,
                               group_type, normal_name, compute_normals,
                               keep_zero, make_unit, reverse),)


class PCG_PolyBevel:
    """
    Mirrors Houdini's PolyBevel (edge bevel).

    The construction is "inset each face along its bevelled edges, then bridge the gaps": face -> inset polygon,
    edge -> bridge strip, vertex -> n-gon around the point. New points must leave the original edge and fall inside their own faces;
    placing them on the original edge would cut the vertex instead of the edge.

    Bevelled edges = interior manifold edges with selected faces on both sides. So group selects faces, not edges --
    this data model has no edge group.
    (The sentence above is the early description: now Group Type = edges can take an edge group directly.)
    Added in pcg100 against Houdini: Shape gains None (only insets faces, grows no bevel faces); Ignore Flat Edges +
    Maximum Normal Angle; Distance Scaling = Scale by Attribute (point attribute, default pscale);
    Convexity (how much Round bulges, 1 = the previous arc); Offset Group (output edge group).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Edge group name / primitive group / @expression; empty = all"),
            "group_type": (["guess", "edges", "prims", "points"],),
            "distance": _f(0.1, 0.0),
            "limit_distance": ("BOOLEAN", {"default": True}),

            **{k: _sec("Fillet", v, gate=(k == "use_fillet")) for k, v in {
                "use_fillet": ("BOOLEAN", {"default": True}),
                "shape": (list(ops.BEVEL_SHAPES),),
                "divisions": _i(1, 1, 64),
            }.items()},

            **{k: _sec("Output Groups", v, gate=(k == "use_out_groups"))
               for k, v in {
                   "use_out_groups": ("BOOLEAN", {"default": True}),
                   "edge_fillet_group": ("STRING", {"default": "edgefilletpolys"}),
                   "point_fillet_group": ("STRING", {"default": "pointfilletpolys"}),
               }.items()},
            # pcg100 addition (default = previous behaviour)
            "ignore_flat": ("BOOLEAN", {"default": False}),
            "max_normal_angle": _f(2.0, 0.0, 180.0, 0.5),
            "distance_scaling": (list(ops.BEVEL_SCALING),),
            "scale_attribute": _names("attrib", "point", "pscale"),
            "convexity": _f(1.0, -1.0, 1.0, 0.05),
            "offset_group": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, group_type, distance, limit_distance,
            use_fillet, shape, divisions, use_out_groups,
            edge_fillet_group, point_fillet_group, ignore_flat=False,
            max_normal_angle=2.0, distance_scaling="none",
            scale_attribute="pscale", convexity=1.0, offset_group=""):
        return (ops.polybevel(
            geo, group, distance,
            divisions if use_fillet else 1,
            shape if use_fillet else "chamfer",
            edge_fillet_group if use_out_groups else "",
            point_fillet_group if use_out_groups else "",
            group_type, limit_distance, ignore_flat, max_normal_angle,
            distance_scaling, scale_attribute,
            convexity if use_fillet else 1.0,
            offset_group if use_out_groups else ""),)


class PCG_PolyExtrude:
    """
    Mirrors Houdini's PolyExtrude SOP.

    The two Divide Into modes are unified through "region ids": side walls grow only where the two sides of an edge have different region ids.
    inset uses an angle-bisector miter scaled by 1/sin(half angle), so every edge moves in by the same perpendicular distance.
    limit_inset clamps inset before edges flip.
    spine follows a rotation-minimizing frame and is initialized **per region** with the face's own axis -- starting from an arbitrary up
    would add a spurious twist between the face orientation and the spine's normal plane.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "divide_into": (["connected", "individual"],),
            "distance": _f(1.0, -1e5),
            "inset": _f(0.0, -1e5),
            "twist": _f(0.0, -3600, 3600, 1.0),
            "divisions": _i(1, 1, 512),

            **{k: _sec("Direction", v, gate=(k == "use_direction")) for k, v in {
                "use_direction": ("BOOLEAN", {"default": False}),
                "dir_x": _f(0.0), "dir_y": _f(1.0), "dir_z": _f(0.0),
            }.items()},

            **{k: _sec("Spine", v, gate=(k == "use_spine")) for k, v in {
                "use_spine": ("BOOLEAN", {"default": False}),
                "up_x": _f(0.0), "up_y": _f(1.0), "up_z": _f(0.0),
            }.items()},

            **{k: _sec("Local Control", v, gate=(k == "use_local")) for k, v in {
                "use_local": ("BOOLEAN", {"default": False}),
                "distance_attrib": ("STRING", {"default": ""}),
                "inset_attrib": ("STRING", {"default": ""}),
            }.items()},

            **{k: _sec("Insetting", v, gate=(k == "limit_insetting")) for k, v in {
                "limit_insetting": ("BOOLEAN", {"default": False}),
                "use_common_limit": ("BOOLEAN", {"default": True}),
            }.items()},

            **{k: _sec("Front Transform", v, gate=(k == "transform_front"))
               for k, v in {
                   "transform_front": ("BOOLEAN", {"default": False}),
                   "front_tx": _f(0.0), "front_ty": _f(0.0), "front_tz": _f(0.0),
                   "front_rotate": _f(0.0, -3600, 3600, 1.0),
                   "front_scale": _f(1.0, 0.0),
               }.items()},

            **{k: _sec("Output", v, gate=(k == "use_output")) for k, v in {
                "use_output": ("BOOLEAN", {"default": True}),
                "output_front": ("BOOLEAN", {"default": True}),
                "output_back": ("BOOLEAN", {"default": False}),
                "output_side": ("BOOLEAN", {"default": True}),
                "front_group": ("STRING", {"default": "extrudeFront"}),
                "back_group": ("STRING", {"default": "extrudeBack"}),
                "side_group": ("STRING", {"default": "extrudeSide"}),
                "front_seam_group": ("STRING", {"default": ""}),
                "back_seam_group": ("STRING", {"default": ""}),
                "preserve_groups": ("BOOLEAN", {"default": True}),
            }.items()},

            **{k: _sec("Normals", v, gate=(k == "add_vertex_normals"))
               for k, v in {
                   "add_vertex_normals": ("BOOLEAN", {"default": False}),
                   "cusp_angle": _f(60.0, 0.0, 180.0, 1.0),
               }.items()},

            **{k: _sec("Texture", v, gate=(k == "side_uv")) for k, v in {
                "side_uv": ("BOOLEAN", {"default": False}),
                "uv_style": (["proportional", "uniform"],),
            }.items()},
            # pcg98 addition
            "extrusion_mode": (list(ops.EXTRUSION_MODES),),
        }, "optional": {"spine": (GEO,)}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, divide_into, distance, inset, twist, divisions,
            use_direction, dir_x, dir_y, dir_z,
            use_spine, up_x, up_y, up_z,
            use_local, distance_attrib, inset_attrib,
            limit_insetting, use_common_limit,
            transform_front, front_tx, front_ty, front_tz,
            front_rotate, front_scale,
            use_output, output_front, output_back, output_side,
            front_group, back_group, side_group,
            front_seam_group, back_seam_group, preserve_groups,
            add_vertex_normals, cusp_angle,
            side_uv, uv_style, extrusion_mode="prim_edge_normal", spine=None):
        if not use_output:
            d = _sec_defaults(PCG_PolyExtrude, "use_output")
            (output_front, output_back, output_side, front_group, back_group,
             side_group, front_seam_group, back_seam_group, preserve_groups) = (
                d[k] for k in ("output_front", "output_back", "output_side",
                               "front_group", "back_group", "side_group",
                               "front_seam_group", "back_seam_group",
                               "preserve_groups"))
        sp = None
        if use_spine and spine is not None and spine.nprims:
            sp = spine.get("point", "P")[spine.prim_points(0)]
        return (ops.polyextrude(
            geo, group, distance, inset, twist, divisions, divide_into,
            (dir_x, dir_y, dir_z) if use_direction else None,
            output_front, output_back, output_side,
            front_group, back_group, side_group,
            sp, (up_x, up_y, up_z),
            distance_attrib if use_local else "",
            inset_attrib if use_local else "",
            limit_insetting, use_common_limit,
            (front_tx, front_ty, front_tz), front_rotate, front_scale,
            transform_front, side_uv, uv_style,
            add_vertex_normals, cusp_angle,
            front_seam_group, back_seam_group, preserve_groups,
            extrusion_mode),)


class PCG_Carve:
    """
    Mirrors Houdini's Carve SOP: cuts or extracts curves at parametric positions.

    NURBS / Bezier are cut by **knot insertion**, and stay curves of the same type afterwards -- subdividing into a polyline would also
    cut, but the type would be lost, and downstream could no longer change the order or carve again.
    Polygons and polylines interpolate linearly by vertex parameter; end points land exactly at the parametric positions.

    U/V carving of surfaces is not done yet: it needs knot insertion row by row and column by column on the (nu,nv) control grid,
    a separate piece of work, to be added once surface workflows are really in use.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "mode": (["cut", "extract"],),
            "relative_arc_length": ("BOOLEAN", {"default": False}),

            **{k: _sec("U", v, gate=(k == "use_first_u")) for k, v in {
                "use_first_u": ("BOOLEAN", {"default": True}),
                "first_u": _f(0.25, 0.0, 1.0, 0.001),
            }.items()},
            **{k: _sec("Second U", v, gate=(k == "use_second_u")) for k, v in {
                "use_second_u": ("BOOLEAN", {"default": False}),
                "second_u": _f(0.75, 0.0, 1.0, 0.001),
            }.items()},

            **{k: _sec("Keep", v, gate=(k == "use_keep")) for k, v in {
                "use_keep": ("BOOLEAN", {"default": True}),
                "keep_inside": ("BOOLEAN", {"default": True}),
                "keep_outside": ("BOOLEAN", {"default": False}),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, mode, relative_arc_length,
            use_first_u, first_u, use_second_u, second_u,
            use_keep, keep_inside, keep_outside):
        if not use_keep:
            d = _sec_defaults(PCG_Carve, "use_keep")
            keep_inside, keep_outside = d["keep_inside"], d["keep_outside"]
        return (ops.carve(geo, group, first_u, second_u,
                          use_first_u, use_second_u,
                          relative_arc=relative_arc_length, mode=mode,
                          keep_inside=keep_inside, keep_outside=keep_outside),)


class PCG_Boolean:
    """
    Mirrors Houdini's Boolean. The backend is manifold3d, not a home-grown implementation -- robust mesh booleans
    need exact predicates, coplanar handling, retriangulation along intersection lines and winding-number classification; a few hundred lines of our own might still not be stable,
    and crashes would happen on the user's models, which are hard to debug.

    Inputs must be **closed manifold meshes**. If not closed, a clear reason and troubleshooting direction is given.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "a": (GEO,), "b": (GEO,),
            "operation": (["subtract", "union", "intersect", "shatter",
                           "seam"],),
            "direction": (["a-b", "b-a", "both"],),
            "treat_a": (["solid", "surface"],),
            "treat_b": (["solid", "surface"],),

            **{k: _sec("Surface", v, gate=(k == "use_surface_opts"))
               for k, v in {
                   "use_surface_opts": ("BOOLEAN", {"default": False}),
                   "shell_thickness": _f(0.01, 1e-5),
               }.items()},

            **{k: _sec("Detriangulate", v, gate=(k == "detriangulate"))
               for k, v in {
                   "detriangulate": ("BOOLEAN", {"default": True}),
                   "coplanar_tolerance": _f(0.5, 0.0, 90.0, 0.1),
               }.items()},

            **{k: _sec("Output Groups", v, gate=(k == "use_out_groups"))
               for k, v in {
                   "use_out_groups": ("BOOLEAN", {"default": False}),
                   "a_inside_b": ("STRING", {"default": "ainsideb"}),
                   "a_outside_b": ("STRING", {"default": "aoutsideb"}),
                   "b_polys": ("STRING", {"default": "bpolys"}),
                   "seam_group": ("STRING", {"default": "abseams"}),
                   # pcg85 addition (appended last so old workflows' indices are unchanged)
                   "b_inside_a": ("STRING", {"default": "binsidea"}),
                   "b_outside_a": ("STRING", {"default": "boutsidea"}),
               }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, a, b, operation, direction, treat_a, treat_b,
            use_surface_opts, shell_thickness, detriangulate,
            coplanar_tolerance, use_out_groups, a_inside_b, a_outside_b,
            b_polys, seam_group, b_inside_a="binsidea", b_outside_a="boutsidea"):
        # Primitive groups are assigned per face following Houdini's definition (see geo/boolean.py). Before pcg85 Shatter
        # wrote the groups regardless of the toggles and split by whole blocks -- blocks are now told apart by connectivity like in Houdini
        on = use_out_groups
        return (_bool.boolean(
            a, b, operation, direction,
            "quads" if detriangulate else "none", coplanar_tolerance,
            a_inside_b if on else "", a_outside_b if on else "",
            b_polys if on else "",
            treat_a, treat_b,
            shell_thickness if use_surface_opts else 0.01,
            seam_group if on else "",
            b_inside_a if on else "", b_outside_a if on else ""),)


class PCG_Sweep:
    """
    Mirrors Houdini's Sweep: sweeps a cross-section along a backbone curve.

    The frame is a rotation-minimizing frame, so it does not twist at bends. The cross-section's plane is determined by its own principal axes,
    without assuming which plane it was drawn in -- cross-sections coming from circle / carve and other nodes have all kinds of orientations,
    and a hardcoded plane would flatten them.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "backbone": (GEO,),
            "shape": (["round_tube", "square_tube", "ribbon",
                       "second_input"],),
            "surface_type": (list(ops.SWEEP_SURFACES),),
            "cols": _i(8, 3, 512),
            "radius": _f(0.1, 0.0),
            "group": _group("Backbone curves; empty = all"),

            **{k: _sec("Cross Section", v, gate=(k == "use_cross_opts"))
               for k, v in {
                   "use_cross_opts": ("BOOLEAN", {"default": False}),
                   "cross_group": _group("Which cross-section in the second input to use"),
                   "reverse_cross": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Rotation", v, gate=(k == "use_rotation")) for k, v in {
                "use_rotation": ("BOOLEAN", {"default": False}),
                "roll": _f(0.0, -3600, 3600, 1.0),
                "full_twists": _f(0.0, -100, 100, 1.0),
                "partial_twist": _f(0.0, -3600, 3600, 1.0),
                "up_x": _f(0.0), "up_y": _f(1.0), "up_z": _f(0.0),
            }.items()},

            **{k: _sec("Scale", v, gate=(k == "use_scale")) for k, v in {
                "use_scale": ("BOOLEAN", {"default": False}),
                "scale_start": _f(1.0, 0.0),
                "scale_end": _f(1.0, 0.0),
                "use_pscale": ("BOOLEAN", {"default": True}),
            }.items()},

            **{k: _sec("Turns", v, gate=(k == "stretch_around_turns"))
               for k, v in {
                   "stretch_around_turns": ("BOOLEAN", {"default": True}),
                   "max_stretch": _f(10.0, 1.0),
               }.items()},

            **{k: _sec("End Caps", v, gate=(k == "end_caps")) for k, v in {
                "end_caps": ("BOOLEAN", {"default": False}),
                "cap_group": ("STRING", {"default": "endcaps"}),
            }.items()},

            **{k: _sec("UV", v, gate=(k == "use_uv")) for k, v in {
                "use_uv": ("BOOLEAN", {"default": False}),
                "uv_attrib": ("STRING", {"default": "uv"}),
            }.items()},
            # pcg98 addition
            "end_cap_type": _sec("End Caps", (list(ops.SWEEP_CAPS),)),
        }, "optional": {"cross": (GEO,)}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, backbone, shape, surface_type, cols, radius, group,
            use_cross_opts, cross_group, reverse_cross,
            use_rotation, roll, full_twists, partial_twist, up_x, up_y, up_z,
            use_scale, scale_start, scale_end, use_pscale,
            stretch_around_turns, max_stretch, end_caps, cap_group,
            use_uv, uv_attrib, end_cap_type="single_polygon", cross=None):
        rot = use_rotation
        return (ops.sweep(
            backbone, cross, shape, cols, radius, surface_type, group,
            cross_group if use_cross_opts else "",
            reverse_cross if use_cross_opts else False,
            (up_x, up_y, up_z) if rot else (0, 1, 0),
            roll if rot else 0.0, full_twists if rot else 0.0,
            partial_twist if rot else 0.0,
            scale_start if use_scale else 1.0,
            scale_end if use_scale else 1.0,
            use_pscale if use_scale else True,
            stretch_around_turns, max_stretch,
            end_caps, cap_group if end_caps else "",
            uv_attrib if use_uv else "", end_cap_type),)


class PCG_Skin:
    """
    Mirrors Houdini's Skin: skins between a set of cross-section curves.

    Cross-sections are ordered by prim number, and a layer of faces is laid between each adjacent pair; if the cross-sections themselves are closed, U wraps around too.

    auto_resample is a deviation from Houdini: Houdini requires every cross-section to have the same point count and errors out
    otherwise. Here it auto-aligns by default -- in practice cross-sections often come from different sources, their point counts naturally
    differ, and adding a Resample by hand every time is tedious. Turn it off for the strict behaviour.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Cross-sections to skin; empty = all"),
            "connectivity": (["quads", "triangles"],),
            "output": (["polygons", "nurbs"],),
            "v_wrap": ("BOOLEAN", {"default": False}),
            "keep_primitives": ("BOOLEAN", {"default": False}),

            **{k: _sec("Alignment", v, gate=(k == "auto_resample")) for k, v in {
                "auto_resample": ("BOOLEAN", {"default": True}),
                "resample_to": _i(0, 0, 100000),
            }.items()},

            **{k: _sec("NURBS", v, gate=(k == "use_nurbs_opts")) for k, v in {
                "use_nurbs_opts": ("BOOLEAN", {"default": False}),
                "v_order": _i(4, 2, 11),
            }.items()},

            **{k: _sec("Grouping", v, gate=(k == "use_every_n")) for k, v in {
                "use_every_n": ("BOOLEAN", {"default": False}),
                "every_n": _i(2, 2, 4096),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, geo, group, connectivity, output, v_wrap, keep_primitives,
            auto_resample, resample_to, use_nurbs_opts, v_order,
            use_every_n, every_n):
        return (ops.skin(
            geo, group, connectivity, v_wrap, output,
            v_order if use_nurbs_opts else 4, keep_primitives,
            every_n if use_every_n else 0,
            auto_resample, resample_to if auto_resample else 0),)


class PCG_Resample:
    """
    Mirrors Houdini's Resample: resamples curves by equal length or equal count.

    NURBS / Bezier curves are first evaluated on the **curve itself** and then sampled, rather than measuring the control polygon.
    The control polygon is far from the curve; dividing it equally gives points that are not on the curve at all.

    Closed polygons are sampled around the whole loop (including the closing edge), and the output stays closed.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "method": (["max_segment_length", "segment_count"],),
            "length": _f(0.1, 1e-6),
            "segments": _i(10, 1, 100000),
            "even_last_segment": ("BOOLEAN", {"default": True}),
            "create_only_points": ("BOOLEAN", {"default": False}),

            **{k: _sec("Spline", v, gate=(k == "use_spline_opts")) for k, v in {
                "use_spline_opts": ("BOOLEAN", {"default": False}),
                "spline_samples": _i(16, 2, 512),
            }.items()},

            **{k: _sec("Output Attributes", v, gate=(k == "use_out_attribs"))
               for k, v in {
                   "use_out_attribs": ("BOOLEAN", {"default": False}),
                   "distance_attrib": ("STRING", {"default": "ptdist"}),
                   "tangent_attrib": ("STRING", {"default": "tangentu"}),
                   "curveu_attrib": ("STRING", {"default": "curveu"}),
                   "curvenum_attrib": ("STRING", {"default": "curvenum"}),
               }.items()},
            # pcg98 addition
            "treat_polygons_as": (list(ops.RESAMPLE_TREAT),),
            "use_max_segments": ("BOOLEAN", {"default": False}),
            "max_segments": _i(10, 1, 100000),
            # pcg100 addition (against Houdini Resample; default = previous behaviour)
            # measure_method is Houdini's "Method" (which length to measure); our old method is really
            # the combination of the two toggles Maximum Segment Length / Maximum Segments, and the name was already taken
            "measure_method": (list(ops.RESAMPLE_METHODS),),
            "measure": (list(ops.RESAMPLE_MEASURES),),
            "maintain_prim_order": ("BOOLEAN", {"default": False}),
            "resample_by_edge": ("BOOLEAN", {"default": False}),
            "attrib_override": ("BOOLEAN", {"default": False}),
            "maintain_last_vertex": ("BOOLEAN", {"default": True}),
            "randomize_first": ("BOOLEAN", {"default": False}),
            "subdivide_later": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, method, length, segments, even_last_segment,
            create_only_points, use_spline_opts, spline_samples,
            use_out_attribs, distance_attrib, tangent_attrib,
            curveu_attrib, curvenum_attrib, treat_polygons_as="straight_edges",
            use_max_segments=False, max_segments=10,
            measure_method="even_length", measure="along_arc",
            maintain_prim_order=False, resample_by_edge=False,
            attrib_override=False, maintain_last_vertex=True,
            randomize_first=False, subdivide_later=False):
        on = use_out_attribs
        return (ops.resample(
            geo, group, method == "max_segment_length", length, segments,
            even_last_segment, create_only_points,
            spline_samples if use_spline_opts else 16,
            distance_attrib if on else "", tangent_attrib if on else "",
            curveu_attrib if on else "", curvenum_attrib if on else "",
            treat_as=treat_polygons_as,
            max_segments=max_segments if use_max_segments else 0,
            measure_method=measure_method, measure=measure,
            maintain_prim_order=maintain_prim_order, by_edge=resample_by_edge,
            attrib_override=attrib_override, maintain_last=maintain_last_vertex,
            randomize_first=randomize_first, subdivide_later=subdivide_later),)


class PCG_Sort:
    """
    Mirrors Houdini's Sort. It changes **numbering**; the geometry shape stays the same.

    circular is an angular sort around an axis -- it is what lets a scattered ring of points be connected into a correct polygon loop;
    sorting by X/Y/Z only gives a zigzag. Angles are measured around the axis by the right-hand rule.

    Sorting changes point and primitive numbers, so everything that references numbers must follow: vertex table, all kinds of groups,
    edge groups (stored as point pairs), per-prim side channels. Missing one is silent corruption.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "point_sort": (["none", "x", "y", "z", "reverse", "random", "shift",
                     "proximity", "along_vector", "attribute",
                     "expression", "spatial_locality", "circular"],),
            "prim_sort": (["none", "x", "y", "z", "reverse", "random", "shift",
                     "proximity", "along_vector", "attribute",
                     "expression", "spatial_locality", "circular"],),
            "reverse_point_sort": ("BOOLEAN", {"default": False}),
            "reverse_prim_sort": ("BOOLEAN", {"default": False}),
            "points_by_vertex_order": ("BOOLEAN", {"default": False}),

            **{k: _sec("Axis / Center", v, gate=(k == "use_axis")) for k, v in {
                "use_axis": ("BOOLEAN", {"default": True}),
                "axis_x": _f(0.0), "axis_y": _f(1.0), "axis_z": _f(0.0),
                "use_center": ("BOOLEAN", {"default": False}),
                "center_x": _f(0.0), "center_y": _f(0.0), "center_z": _f(0.0),
            }.items()},

            **{k: _sec("Proximity", v, gate=(k == "use_target")) for k, v in {
                "use_target": ("BOOLEAN", {"default": True}),
                "target_x": _f(0.0), "target_y": _f(0.0), "target_z": _f(0.0),
            }.items()},

            **{k: _sec("Attribute / Expression", v, gate=(k == "use_key"))
               for k, v in {
                   "use_key": ("BOOLEAN", {"default": True}),
                   "point_attrib": _names("attrib", "point"),
                   "prim_attrib": _names("attrib", "prim"),
                   "component": _i(0, 0, 15),
                   "point_expr": ("STRING", {"default": "", "code_hl": True}),
                   "prim_expr": ("STRING", {"default": "", "code_hl": True}),
               }.items()},

            **{k: _sec("Random / Shift", v, gate=(k == "use_rs")) for k, v in {
                "use_rs": ("BOOLEAN", {"default": True}),
                "rand_seed": _i(0, 0, 1 << 31),
                "offset": _i(0, -1 << 20, 1 << 20),
            }.items()},

            # ── pcg90: primitive sort has its own set (Houdini's Primitive Sort has its own Seed / Offset /
            # Vector / Point / Component). Appended last, so old workflows' widget indices are unchanged.
            # Put in sections with the same names as the point set, so the section toggles (off in old workflows) govern them too
            **{k: _sec("Random / Shift", v) for k, v in {
                "prim_rand_seed": _i(0, 0, 1 << 31),
                "prim_offset": _i(0, -1 << 20, 1 << 20),
            }.items()},
            **{k: _sec("Axis / Center", v) for k, v in {
                "prim_axis_x": _f(0.0), "prim_axis_y": _f(1.0), "prim_axis_z": _f(0.0),
                "prim_use_center": ("BOOLEAN", {"default": False}),
                "prim_center_x": _f(0.0), "prim_center_y": _f(0.0),
                "prim_center_z": _f(0.0),
            }.items()},
            **{k: _sec("Proximity", v) for k, v in {
                "prim_target_x": _f(0.0), "prim_target_y": _f(0.0),
                "prim_target_z": _f(0.0),
            }.items()},
            "prim_component": _sec("Attribute / Expression", _i(0, 0, 15)),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    # Houdini has none of the four section toggles (whether a parameter is used depends only on the sort method). From pcg90 they default to on and are hidden in the panel;
    # old workflows that have them off still follow "section toggle off = this section uses defaults", and the toggle is shown so it can be turned on
    def run(self, geo, point_sort, prim_sort, reverse_point_sort,
            reverse_prim_sort, points_by_vertex_order,
            use_axis, axis_x, axis_y, axis_z,
            use_center, center_x, center_y, center_z,
            use_target, target_x, target_y, target_z,
            use_key, point_attrib, prim_attrib, component,
            point_expr, prim_expr, use_rs, rand_seed, offset,
            prim_rand_seed=0, prim_offset=0,
            prim_axis_x=0.0, prim_axis_y=1.0, prim_axis_z=0.0,
            prim_use_center=False,
            prim_center_x=0.0, prim_center_y=0.0, prim_center_z=0.0,
            prim_target_x=0.0, prim_target_y=0.0, prim_target_z=0.0,
            prim_component=0):
        off = {}                                  # sections that are off: use defaults
        for gate, on in (("use_axis", use_axis), ("use_target", use_target),
                         ("use_key", use_key), ("use_rs", use_rs)):
            if not on:
                off.update(_sec_defaults(PCG_Sort, gate))
        v = lambda name, val: off.get(name, val)  # noqa: E731
        prim = {"seed": v("prim_rand_seed", prim_rand_seed),
                "offset": v("prim_offset", prim_offset),
                "axis": (v("prim_axis_x", prim_axis_x), v("prim_axis_y", prim_axis_y),
                         v("prim_axis_z", prim_axis_z)),
                "use_center": v("prim_use_center", prim_use_center),
                "center": (v("prim_center_x", prim_center_x),
                           v("prim_center_y", prim_center_y),
                           v("prim_center_z", prim_center_z)),
                "target": (v("prim_target_x", prim_target_x),
                           v("prim_target_y", prim_target_y),
                           v("prim_target_z", prim_target_z)),
                "component": v("prim_component", prim_component)}
        return (ops.sort_geo(
            geo, point_sort, prim_sort, reverse_point_sort, reverse_prim_sort,
            v("rand_seed", rand_seed), v("offset", offset),
            (v("axis_x", axis_x), v("axis_y", axis_y), v("axis_z", axis_z)),
            v("use_center", use_center),
            (v("center_x", center_x), v("center_y", center_y), v("center_z", center_z)),
            (v("target_x", target_x), v("target_y", target_y), v("target_z", target_z)),
            v("point_attrib", point_attrib), v("prim_attrib", prim_attrib),
            v("component", component), v("point_expr", point_expr),
            v("prim_expr", prim_expr), points_by_vertex_order, prim=prim),)


class PCG_Reverse:
    """
    Mirrors Houdini's Reverse: reorders the vertices of prims.

    The whole operator comes down to computing a corner permutation per prim, then reordering vertex_point, all
    vertex attributes and vertex groups together -- plain reversal and the U/V transforms of surfaces share the same path,
    so no kind of data gets missed.

    reverse_v / swap_uv only make sense for NURBS/Bezier surfaces; polygons have no V direction.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "mode": (["reverse", "none", "reverse_u", "reverse_v",
                      "swap_uv", "shift"],),

            **{k: _sec("Shift", v, gate=(k == "use_shift")) for k, v in {
                # Houdini has no such toggle (choosing Shift moves by Offset). From pcg90 it defaults to on and is hidden in the panel;
                # old workflows that have it off still = Offset uses the default 0, and the toggle is shown
                "use_shift": ("BOOLEAN", {"default": True}),
                "u_offset": _i(0, -4096, 4096),
                "v_offset": _i(0, -4096, 4096),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, mode, use_shift, u_offset, v_offset):
        return (ops.reverse_prims(geo, group, mode,
                                  u_offset if use_shift else 0,
                                  v_offset if use_shift else 0),)


class PCG_Convert:
    """
    Prim type conversion, mirrors Houdini's Convert SOP.

    The scope of the NURBS implementation needs stating: the knot vector is always **uniform clamped**; arbitrary non-uniform
    knots are not supported. The reason is that attributes in this model are fixed-size (N,C) arrays and a variable-length knot vector does not fit --
    supporting it would first need a per-prim variable-length side channel on Geometry. Uniform clamped covers
    every case Convert SOP actually produces.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "convert_to": (["triangles", "polygons", "polylines", "points",
                            "nurbs_curve", "nurbs_surface",
                            "bezier_curve", "bezier_surface",
                            "volume_sdf", "volume_fog"],),
            "group": _group("Prims to convert; empty = all"),

            **{k: _sec("NURBS", v, gate=(k == "use_nurbs_opts")) for k, v in {
                "use_nurbs_opts": ("BOOLEAN", {"default": True}),
                "u_order": _i(4, 2, 11),
                "v_order": _i(4, 2, 11),
                "interpolate_through_hulls": ("BOOLEAN", {"default": False}),
            }.items()},

            **{k: _sec("Tessellation", v, gate=(k == "use_tessellation"))
               for k, v in {
                   "use_tessellation": ("BOOLEAN", {"default": True}),
                   "u_divs": _i(16, 2, 512),
                   "v_divs": _i(16, 2, 512),
               }.items()},

            **{k: _sec("Volume", v, gate=(k == "use_volume")) for k, v in {
                "use_volume": ("BOOLEAN", {"default": True}),
                "vol_res_x": _i(48, 2, 512),
                "vol_res_y": _i(48, 2, 512),
                "vol_res_z": _i(48, 2, 512),
                "vol_radius": _f(0.0, 0.0, 1e4, 0.01),
                "vol_pad": _f(0.15, 0.0, 2.0, 0.01),
                "iso": _f(0.0, -1e6, 1e6, 0.01),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, convert_to, group, use_nurbs_opts, u_order, v_order,
            interpolate_through_hulls, use_tessellation, u_divs, v_divs,
            use_volume, vol_res_x, vol_res_y, vol_res_z, vol_radius, vol_pad, iso):
        if not use_nurbs_opts:
            d = _sec_defaults(PCG_Convert, "use_nurbs_opts")
            u_order, v_order = d["u_order"], d["v_order"]
            interpolate_through_hulls = d["interpolate_through_hulls"]
        if not use_tessellation:
            d = _sec_defaults(PCG_Convert, "use_tessellation")
            u_divs, v_divs = d["u_divs"], d["v_divs"]
        if not use_volume:
            d = _sec_defaults(PCG_Convert, "use_volume")
            vol_res_x, vol_res_y, vol_res_z = (d["vol_res_x"], d["vol_res_y"],
                                               d["vol_res_z"])
            vol_radius, vol_pad, iso = d["vol_radius"], d["vol_pad"], d["iso"]
        res = (vol_res_x, vol_res_y, vol_res_z)
        if convert_to == "volume_fog":
            return (volume.points_to_volume(geo, res, vol_radius, vol_pad,
                                            group=group),)
        if convert_to == "volume_sdf":
            return (volume.mesh_to_volume(geo, res, vol_pad, group),)
        # Volume to polygons goes through isosurface extraction, not an ordinary prim type conversion
        geo = volume.volume_to_polygons(geo, iso, group)
        if convert_to in ("nurbs_curve", "nurbs_surface",
                          "bezier_curve", "bezier_surface"):
            basis, _, shape = convert_to.partition("_")
            return (ops.to_spline(geo, shape, basis, group,
                                  u_order, v_order, interpolate_through_hulls),)
        # When converting to polygons, subdivide the splines first, then do the ordinary polygon conversion
        had_spline = bool(geo.nprims) and bool(np.isin(geo.prim_type,
                                                       (4, 5, 6, 7)).any())
        g = ops.spline_to_polygons(geo, group, u_divs, v_divs)
        if convert_to == "polygons" and had_spline:
            return (g,)
        return (ops.convert_prims(g, convert_to, group),)


class PCG_GroupCreate:
    """
    Mirrors Houdini's Group Create SOP: several filter sections stacked in one node, each with its own toggle.

    base is the starting set (empty = select all); accepts group names / indices / ranges / @expressions.
    The bbox / normal / edges / random sections are each intersected (edges can be switched to union),
    and the result is finally merged with an existing group of the same name according to the merge mode.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "name": ("STRING", {"default": "group1"}),
            "cls": (["point", "prim", "vertex"],),
            "merge": (["replace", "union", "intersect", "subtract"],),
            "base": _group("Starting set; empty = select all"),

            **{k: _sec("Bounding Region", v, gate=(k == "use_bbox"))
               for k, v in {
                   "use_bbox": ("BOOLEAN", {"default": False}),
                   "cx": _f(), "cy": _f(), "cz": _f(),
                   "sx": _f(1.0, 0.0), "sy": _f(1.0, 0.0), "sz": _f(1.0, 0.0),
                   "bbox_partial": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Normals", v, gate=(k == "use_normal"))
               for k, v in {
                   "use_normal": ("BOOLEAN", {"default": False}),
                   "dir_x": _f(0.0), "dir_y": _f(0.0), "dir_z": _f(1.0),
                   "spread": _f(180.0, 0.0, 180.0, 1.0),
                   "both_dirs": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Edges", v, gate=(k == "use_edges"))
               for k, v in {
                   "use_edges": ("BOOLEAN", {"default": False}),
                   # include first = default (this page in Houdini is Include); old workflows
                   # store strings, so reordering does not affect them
                   "edge_combine": (["include", "keep"],),
                   "unshared": ("BOOLEAN", {"default": False}),
                   "min_angle": _f(20.0, 0.0, 180.0, 1.0),
                   "max_angle": _f(180.0, 0.0, 180.0, 1.0),
               }.items()},

            **{k: _sec("Random", v, gate=(k == "use_random"))
               for k, v in {
                   "use_random": ("BOOLEAN", {"default": False}),
                   "rand_seed": _i(0, 0, 1 << 31),
                   "percent": _f(50.0, 0.0, 100.0, 1.0),
               }.items()},
            # pcg85 addition (appended last so old workflows' indices are unchanged): the angle rule's own toggle,
            # selected independently from Unshared and unioned
            "use_angle": _sec("Edges", ("BOOLEAN", {"default": True})),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, name, cls, merge, base,
            use_bbox, cx, cy, cz, sx, sy, sz, bbox_partial,
            use_normal, dir_x, dir_y, dir_z, spread, both_dirs,
            use_edges, edge_combine, unshared, min_angle, max_angle,
            use_random, rand_seed, percent, use_angle=True):
        return (groups.create(
            geo, cls, name.strip() or "group1", base,
            use_bbox, (cx, cy, cz), (sx, sy, sz), bbox_partial,
            use_normal, (dir_x, dir_y, dir_z), spread, both_dirs,
            use_edges, min_angle, max_angle, unshared, edge_combine,
            use_random, rand_seed, percent, merge, use_angle),)


class PCG_GroupEdges:
    """
    Builds edge groups. Mirrors the Edges section of Houdini's Group Create, but outputs a real edge group.

    Edge groups store **point pairs**, not edge indices -- edge indices are derived from topology, and after delete / merge / fuse
    the whole numbering changes, so a group storing indices would silently point at other edges.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "name": ("STRING", {"default": "edges1"}),
            "merge": (["replace", "union", "intersect", "subtract"],),
            "base": _group("Starting edge group; empty = all edges"),

            **{k: _sec("Angle", v, gate=(k == "use_angle")) for k, v in {
                "use_angle": ("BOOLEAN", {"default": True}),
                "min_angle": _f(20.0, 0.0, 180.0, 1.0),
                "max_angle": _f(180.0, 0.0, 180.0, 1.0),
            }.items()},
            **{k: _sec("Length", v, gate=(k == "use_length")) for k, v in {
                "use_length": ("BOOLEAN", {"default": False}),
                "min_length": _f(0.0, 0.0),
                "max_length": _f(1e6, 0.0),
            }.items()},
            **{k: _sec("Boundary", v, gate=(k == "unshared")) for k, v in {
                "unshared": ("BOOLEAN", {"default": False}),
            }.items()},
            **{k: _sec("Random", v, gate=(k == "use_random")) for k, v in {
                "use_random": ("BOOLEAN", {"default": False}),
                "rand_seed": _i(0, 0, 1 << 31),
                "percent": _f(50.0, 0.0, 100.0, 1.0),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, name, merge, base, use_angle, min_angle, max_angle,
            use_length, min_length, max_length, unshared,
            use_random, rand_seed, percent):
        return (groups.create_edges(
            geo, name.strip() or "edges1", base,
            use_angle, min_angle, max_angle, unshared,
            use_length, min_length, max_length,
            use_random, rand_seed, percent, merge),)


class PCG_EdgeGroupPromote:
    """Convert edge groups <-> point groups / primitive groups."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "source": ("STRING", {"default": ""}),
            "target": ("STRING", {"default": ""}),
            "direction": (["edge->point", "edge->prim",
                           "point->edge", "prim->edge"],),
            "interior_only": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, source, target, direction, interior_only):
        g = geo.copy()
        tgt = target.strip() or source.strip() or "promoted"
        if direction == "edge->point":
            g.set_group(POINT, tgt, groups.edges_to_points(
                geo, groups.resolve_edges(geo, source)))
        elif direction == "edge->prim":
            g.set_group(PRIM, tgt, groups.edges_to_prims(
                geo, groups.resolve_edges(geo, source)))
        elif direction == "point->edge":
            g.set_edge_group(tgt, groups.points_to_edges(
                geo, groups.resolve(geo, POINT, source)))
        else:
            g.set_edge_group(tgt, groups.prims_to_edges(
                geo, groups.resolve(geo, PRIM, source), interior_only))
        return (g,)


from .geo import grouppromote as _gpr                      # noqa: E402


class PCG_GroupPromote:
    """
    Mirrors Houdini's Group Promote: converts groups between point / prim / edge / vertex.

    Houdini has two combos, Convert From / To; here there is **one** Conversion combo (before pcg100
    only the first two entries existed; workflows store values by token, and splitting into two combos would break old graphs). The rules for each direction are in
    geo/grouppromote.py.

    Two defaults are the opposite of Houdini, to keep old graphs unchanged: Keep Original Group defaults to on (this node
    never deleted the original group before); Include Only Elements Entirely Contained defaults to on (point -> primitive used to
    always be "only when all points are in").
    """
    DIRECTIONS = ("point_to_prim", "prim_to_point",
                  # pcg100 addition; token = <from>_to_<to>
                  "point_to_edge", "point_to_vertex", "prim_to_edge", "prim_to_vertex",
                  "edge_to_point", "edge_to_prim", "edge_to_vertex",
                  "vertex_to_point", "vertex_to_prim", "vertex_to_edge",
                  # Same class to same class only makes sense with Boundary: primitive group -> the ring of faces in the group next to its outline
                  "prim_to_prim")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "name": ("STRING", {"default": "group1"}),
            "direction": (list(cls.DIRECTIONS),),
            "new_name": ("STRING", {"default": ""}),
        }, "optional": {
            # pcg100 addition, default = previous behaviour
            "keep_original": ("BOOLEAN", {"default": True}),
            "only_full": ("BOOLEAN", {"default": True}),
            "share_edge": ("BOOLEAN", {"default": False}),
            "only_boundary": ("BOOLEAN", {"default": False}),
            "include_unshared": ("BOOLEAN", {"default": True}),
            "include_curve_unshared": ("BOOLEAN", {"default": False}),
            "as_attribute": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, name, direction, new_name, keep_original=True,
            only_full=True, share_edge=False, only_boundary=False,
            include_unshared=True, include_curve_unshared=False,
            as_attribute=False):
        if direction not in self.DIRECTIONS:
            raise ValueError(f"Conversion must be one of {self.DIRECTIONS}")
        src, dst = direction.split("_to_")
        return (_gpr.promote(geo, name, src, dst, new_name, keep_original,
                             only_full, share_edge, only_boundary,
                             include_unshared, include_curve_unshared,
                             as_attribute),)


class PCG_Connectivity:
    """Connected component numbering. Mirrors Houdini's Connectivity SOP."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "cls": (["point", "prim"],),
            "attribute": ("STRING", {"default": "class"}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/topology"

    def run(self, geo, cls, attribute):
        return (topology.connectivity(geo, cls, attribute.strip() or "class"),)


class PCG_Smooth:
    """Laplacian smoothing. Boundaries are pinned by default, otherwise open meshes shrink inward every iteration."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "strength": _f(0.5, 0.0, 1.0, 0.01),
            "iterations": _i(5, 0, 500),
            "pin_boundary": ("BOOLEAN", {"default": True}),
            "group": _group(),
            # pcg100: added against Smooth 2.0 (default = old behaviour)
            "method": (["uniform", "scale_dominant", "curvature_dominant"],),
            "pin_group_boundary": ("BOOLEAN", {"default": False}),
            "constrained_points": _names("group", "point", hint="Extra points to pin; group name / indices / @expression"),
            "attributes": _names("attrib", "point", default="P",
                                 hint="Float point / vertex attributes to smooth, space-separated, wildcards allowed (e.g. P uv)"),
            "use_weight_attribute": ("BOOLEAN", {"default": False}),
            "weight_attribute": _names("attrib", "point", default="weight"),
            "recompute_normals": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, strength, iterations, pin_boundary, group, method="uniform",
            pin_group_boundary=False, constrained_points="", attributes="P",
            use_weight_attribute=False, weight_attribute="weight", recompute_normals=False):
        return (topology.smooth(geo, strength, iterations, group, pin_boundary,
                                method=method, pin_group_boundary=pin_group_boundary,
                                constrained_points=constrained_points, attributes=attributes,
                                weight_attribute=weight_attribute if use_weight_attribute else "",
                                recompute_normals=recompute_normals),)


class PCG_Blast:
    """Delete the given group. With keep=True it does the opposite and keeps only that group (equivalent to Houdini's Delete Non-Selected)."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Elements to delete; group name / indices / @expression"),
            "cls": (["point", "prim"],),
            "keep_selected": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, cls, keep_selected):
        if not group.strip():
            return (geo.copy(),)                   # empty = delete nothing
        m = groups.resolve(geo, cls, group)
        keep = m if keep_selected else ~m
        return (ops.delete_prims(geo, keep) if cls == "prim"
                else ops.delete_points(geo, keep),)


class PCG_AttribDelete:
    """
    Mirrors Houdini's Attribute Delete.

    Names accept wildcards: `uv*` matches those starting with uv, `* ^P ^N` means everything except P and N.
    Leaving a field empty = that class is untouched (watch out with invert: empty does not mean "select all").
    Point P is always kept -- without positions it is not geometry.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "point": _names("attrib", "point", hint="e.g. N Cd uv*"),
            "vertex": _names("attrib", "vertex"),
            "prim": _names("attrib", "prim"),
            "detail": _names("attrib", "detail"),
            "delete_non_selected": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, point, vertex, prim, detail, delete_non_selected):
        return (ops.delete_attribs(geo, point, vertex, prim, detail,
                                   delete_non_selected),)


class PCG_GroupDelete:
    """
    Mirrors Houdini's Group Delete.

    Names accept wildcards: `extrude*` matches those starting with extrude, `* ^keep` means everything except keep.
    Leaving a field empty = that class is untouched (with invert, empty does not mean "select all").
    Edge groups are handled as well.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "point": _names("group", "point", hint="e.g. top extrude*"),
            "vertex": _names("group", "vertex"),
            "prim": _names("group", "prim"),
            "edge": _names("group", "edge"),
            "delete_non_selected": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, point, vertex, prim, edge, delete_non_selected):
        return (ops.delete_groups(geo, point, vertex, prim, edge,
                                  delete_non_selected),)


class PCG_AttribPromote:
    """
    Mirrors Houdini's Attribute Promote SOP: moves attributes between point / vertex / prim /
    detail.

    The four classes combine pairwise into 16 directions; internally this is not one branch per direction, but first building a
    **(source element, target element) correspondence table** and then doing a grouped reduction -- in the expanding direction each target maps to exactly one
    source, and a reduction method applied to one element is that element itself, so expansion and reduction share one path.
    Piece Attribute then just means "switch the grouping key from the target element to the piece it belongs to".

    original_name accepts patterns (`uv*` / `* ^P`) to move a batch at once; a `*` in new_name is
    replaced by the original attribute name, which helps with batch renaming.

    Houdini also has Array of All / Unique Values, not done here: they produce **variable-length array attributes**,
    while attributes in this model are always fixed-size (N,C) arrays (see the design notes in geo/core.py).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "original_name": _names("attrib", "prim", "Cd",
                                    "accepts patterns: uv* / * ^P"),
            "original_class": (["point", "vertex", "prim", "detail"],),
            "new_class": (["prim", "point", "vertex", "detail"],),
            "method": (["average", "maximum", "minimum", "sum", "mode",
                        "median", "sum_of_squares", "root_mean_square",
                        "first_match", "last_match"],),
            "delete_original": ("BOOLEAN", {"default": True}),

            **{k: _sec("Piece Attribute", v, gate=(k == "use_piece"))
               for k, v in {
                   "use_piece": ("BOOLEAN", {"default": False}),
                   "piece_attribute": _names(
                       "attrib", "prim", "name",
                       "read from New Class, must be integer or string; reduces per piece instead of per element"),
               }.items()},

            **{k: _sec("Change New Name", v, gate=(k == "change_new_name"))
               for k, v in {
                   "change_new_name": ("BOOLEAN", {"default": False}),
                   "new_name": ("STRING", {"default": "",
                                           "tooltip": "If it contains *, * is replaced by the original attribute name"}),
               }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, original_name, original_class, new_class, method,
            delete_original, use_piece, piece_attribute,
            change_new_name, new_name):
        return (_prom.promote(
            geo, original_name, original_class, new_class, method,
            piece_attribute if use_piece else "",
            new_name if change_new_name else "",
            delete_original),)


class PCG_Switch:
    """
    Mirrors Houdini's Switch SOP: picks one input by index and passes it on.

    **The inputs not selected are not executed.** The branch inputs are declared lazy, and check_lazy_status
    only requests the selected one -- so ComfyUI never runs the other branches, the same as unselected branches
    not cooking in Houdini. That is the real value of this node: otherwise it would just be a prop that
    "computes a pile and throws most of it away".

    **select_input accepts expressions**, like in Houdini:

        2                                    an index directly
        detail(-1, "type", 0)                read a detail attribute on ctrl
        1 if detail("kind") == "drawer" else 0
        nprims() > 100                       take different branches by condition
        ninputs() - 1                        always pick the last one

    The `ctrl` input is Houdini's **Spare Input**, and `-1` refers to it.
    Expressions **can only read from ctrl**, not from branch inputs -- the branches are lazy, and reading one would
    run the unselected ones too, defeating the node. So the data used for the decision needs its own wire;
    Houdini does it the same way (the Spare Input in the screenshot points at attribpromote1).

    Numbering only counts **wired** branches (like Houdini), so with input0/input2 wired and
    input1 empty, index 1 refers to input2. Out-of-range values are clamped to the ends by default; turn on wrap to wrap around
    (negative values count from the end).
    """
    MAX_INPUTS = 8

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "select_input": ("STRING", {
                    "default": "0", "code_hl": True,
                    "tooltip": 'Index or expression, e.g. detail(-1, "type", 0)'}),
                "wrap": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                # ctrl is not lazy: the expression reads it, so it must be computed first
                "ctrl": (GEO,),
                **{f"input{i}": (GEO, {"lazy": True})
                   for i in range(cls.MAX_INPUTS)},
            },
        }
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    @staticmethod
    def _pick(select_input, wrap, kw):
        # kw only holds **wired** inputs (unwired ones do not even appear as keys), which is exactly the table of valid indices
        names = sorted((k for k in kw if k.startswith("input")),
                       key=lambda s: int(s[5:]))
        if not names:
            return None, names
        i = _ex.eval_select(select_input, kw.get("ctrl"), len(names))
        i = i % len(names) if wrap else max(0, min(i, len(names) - 1))
        return names[i], names

    def check_lazy_status(self, select_input, wrap, **kw):
        pick, _ = self._pick(select_input, wrap, kw)
        return [pick] if pick else []

    def run(self, select_input, wrap, **kw):
        pick, names = self._pick(select_input, wrap, kw)
        if pick is None:
            raise ValueError("Switch has no branch input wired at all.")
        g = kw.get(pick)
        if g is None:
            raise ValueError(
                f"The input {pick} selected by Switch produced no geometry -- its upstream may be bypassed.")
        return (g.copy(),)


# ============================================================ scatter / copy
class PCG_Scatter:
    """
    Mirrors Houdini's Scatter SOP.

    Triangulation uses Divide's ear clipping, not a fan -- a fan on a concave ngon grows triangles that stick outside
    the shape, so points get scattered outside the face, and this kind of error takes a long stare at the preview to spot.

    Relax really does project back onto the surface: after each push-apart iteration the points are reprojected onto the nearest triangle
    (grid hash for candidates + exact point-triangle closest point), so points can migrate across triangles,
    dense areas can be pushed out, and they do not drift off the surface. The relax radius is estimated from the target density:
    r = sqrt(total area / (N*pi)), i.e. the radius of N non-overlapping disks filling that area.

    Per-Prim Seed gives every face its own random stream -- changing one face does not reshuffle the points on all the others.
    The cost is per-face sampling (a Python loop), but in a procedural flow "change one spot, the rest stays put" is worth it.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only scatter on these faces; empty = all"),
            "force_total_count": ("BOOLEAN", {"default": True}),
            "count": _i(1000, 0, 1 << 22),
            "density_scale": _f(10.0, 0.0, 1e6, 0.1),
            "rand_seed": _i(0, 0, 1 << 31),
            "randomize_order": ("BOOLEAN", {"default": True}),

            **{k: _sec("Density Attributes", v, gate=(k == "use_density"))
               for k, v in {
                   "use_density": ("BOOLEAN", {"default": False}),
                   "density_attribute": _names("attrib", "point", "density"),
                   "area_attribute": _names("attrib", "prim", "",
                                            "used in place of the prim's geometric area"),
               }.items()},

            **{k: _sec("Max Point Limit", v, gate=(k == "use_max_points"))
               for k, v in {
                   "use_max_points": ("BOOLEAN", {"default": True}),
                   "max_points": _i(1000000, 0, 1 << 24),
               }.items()},

            **{k: _sec("Per-Prim Seed", v, gate=(k == "use_prim_seed"))
               for k, v in {
                   "use_prim_seed": ("BOOLEAN", {"default": False}),
                   "prim_seed_attribute": _names("attrib", "prim", "name"),
               }.items()},

            **{k: _sec("Relax", v, gate=(k == "use_relax")) for k, v in {
                "use_relax": ("BOOLEAN", {"default": False}),
                "relax_iterations": _i(10, 0, 200),
                "scale_radii_by": _f(1.0, 0.0, 100.0, 0.01),
                "use_max_relax_radius": ("BOOLEAN", {"default": True}),
                "max_relax_radius": _f(10.0, 0.0),
                "use_geometric_normals": ("BOOLEAN", {"default": False}),
            }.items()},

            **{k: _sec("Output Attributes", v, gate=(k == "use_out_attribs"))
               for k, v in {
                   "use_out_attribs": ("BOOLEAN", {"default": True}),
                   "normal_attribute": ("STRING", {"default": "N"}),
                   "sourceprim_attribute": ("STRING", {"default": "sourceprim"}),
                   "uv_attribute": ("STRING", {"default": "sourceprimuv"}),
                   "interpolate_attributes": ("BOOLEAN", {"default": True}),
               }.items()},

            # ── pcg100 addition (Houdini Scatter 2.0's Generate / output attributes / Attributes page)
            "generate": (list(_scat.GENERATES),),
            "count_per_prim_attribute": ("STRING", {
                "default": "1", "tooltip": "An integer, or the name of an integer prim attribute (Count per Primitive)"}),
            "texture_uv_attribute": _names("attrib", "vertex", "uv",
                                           "uv used by Density Texture / In Texture Space"),
            "use_out_density": ("BOOLEAN", {"default": False}),
            "out_density_name": ("STRING", {"default": "density"}),
            "use_out_radius": ("BOOLEAN", {"default": False}),
            "out_radius_name": ("STRING", {"default": "pscale"}),
            "use_out_id": ("BOOLEAN", {"default": False}),
            "out_id_name": ("STRING", {"default": "id"}),
            "out_texture_space": ("BOOLEAN", {"default": False}),
            "point_attributes": _names("attrib", "point", "*"),
            "vertex_attributes": _names("attrib", "vertex", "*"),
            "primitive_attributes": _names("attrib", "prim", ""),
            "detail_attributes": _names("attrib", "detail", ""),
            "detail_as_detail": _names("attrib", "detail", ""),
        }, "optional": {
            "density_texture": (COP,),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("points",)
    FUNCTION = "run"; CATEGORY = CAT + "/scatter"

    def run(self, geo, group, force_total_count, count, density_scale,
            rand_seed, randomize_order,
            use_density, density_attribute, area_attribute,
            use_max_points, max_points,
            use_prim_seed, prim_seed_attribute,
            use_relax, relax_iterations, scale_radii_by,
            use_max_relax_radius, max_relax_radius, use_geometric_normals,
            use_out_attribs, normal_attribute, sourceprim_attribute,
            uv_attribute, interpolate_attributes,
            generate="by_density", count_per_prim_attribute="1",
            texture_uv_attribute="uv",
            use_out_density=False, out_density_name="density",
            use_out_radius=False, out_radius_name="pscale",
            use_out_id=False, out_id_name="id", out_texture_space=False,
            point_attributes="*", vertex_attributes="*",
            primitive_attributes="", detail_attributes="",
            detail_as_detail="", density_texture=None):
        on = use_out_attribs
        return (_scat.scatter(
            geo, group, force_total_count, count, density_scale,
            density_attribute if use_density else "",
            area_attribute if use_density else "",
            use_max_points, max_points,
            rand_seed, prim_seed_attribute if use_prim_seed else "",
            randomize_order,
            relax_iterations if use_relax else 0,
            use_geometric_normals,
            scale_radii_by, use_max_relax_radius, max_relax_radius,
            normal_attribute if on else "",
            sourceprim_attribute if on else "",
            uv_attribute if on else "",
            interpolate_attributes and on,
            # Interpolation of vertex attributes has never been controlled by the Interpolate toggle (old behaviour, kept);
            # to turn it off you can now clear Vertex Attributes
            generate=generate, count_per_prim=count_per_prim_attribute,
            density_texture=density_texture,
            texture_uv_attrib=texture_uv_attribute,
            out_density=out_density_name if use_out_density else "",
            out_radius=out_radius_name if use_out_radius else "",
            out_id=out_id_name if use_out_id else "",
            out_texture_space=out_texture_space,
            point_attribs=point_attributes, vertex_attribs=vertex_attributes,
            prim_attribs=primitive_attributes,
            detail_attribs=detail_attributes,
            detail_as_detail=detail_as_detail),)


class PCG_CopyToPoints:
    """
    Mirrors Houdini's Copy to Points.

    Transforms follow Houdini's instance attributes convention exactly: on target points
    orient / N+up / rot / scale / pscale / pivot / trans / transform are all recognised,
    composed in the order P + trans + orient·(rot·(scale·(p - pivot))). The N output by scatter nodes
    and randomized pscale work as soon as they are wired in.

    With name (or variant) in Piece Attribute, the source is split into pieces by this attribute, and target points pick pieces by the attribute
    of the same name -- five kinds of trees scattered in one go, without five branches each with its own Copy.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source": (GEO,), "points": (GEO,),
            "source_group": _group("Primitive group on the source (point group for a point cloud)"),
            "target_group": _group("**Point** group on the target"),
            "transform_using_orientations": ("BOOLEAN", {"default": True}),
            "up_x": _f(0.0), "up_y": _f(1.0), "up_z": _f(0.0),
            "piece_attribute": _names(
                "attrib", "prim", "", "Distribute by piece. Both the source and the target points need this attribute"),

            **{k: _sec("Attributes", v) for k, v in {
                "target_point_attributes": _names(
                    "attrib", "point", "*", "Which target point attributes are passed to the copies' points"),
                "target_prim_attributes": _names(
                    "attrib", "point", "", "Which target point attributes are passed to the copies' primitives"),
                "multiply_attributes": _names(
                    "attrib", "point", "", "These names are multiplied instead of overwritten"),
                "rotate_attributes": _names(
                    "attrib", "point", "N v up", "Direction-like attributes that rotate along"),
            }.items()},
            # pcg121: one packed primitive per copy (drawn as GPU instances; Unpack gives the same geometry as off)
            "pack_and_instance": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/scatter"

    def run(self, source, points, source_group, target_group,
            transform_using_orientations, up_x, up_y, up_z, piece_attribute,
            target_point_attributes, target_prim_attributes,
            multiply_attributes, rotate_attributes, pack_and_instance=False):
        from .geo import packed as _pk
        if _pk.is_packed(source):
            source = _pk.unpack(source)[0]
        if _pk.is_packed(points):          # packed targets: their points are the targets (Houdini does the same)
            points = ops.delete_prims(points, np.zeros(points.nprims, bool), keep_points=True)
        return (_cpt.copy_to_points(
            source, points, source_group, target_group,
            transform_using_orientations, (up_x, up_y, up_z),
            piece_attribute, target_point_attributes, target_prim_attributes,
            multiply_attributes, rotate_attributes, pack=bool(pack_and_instance)),)


class PCG_AttribTransfer:
    """
    Mirrors Houdini's Attribute Transfer.

    "What to blend" and "how much to blend" are two independent quantities: the sample count + kernel decide the blended target value,
    Blend Width decides how it transitions between that value and the original. Blend Width = 0 is a hard switch --
    fully replaced within the threshold, untouched beyond it.

    String attributes and groups cannot be weighted-averaged; they always take the nearest source element.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "dest": (GEO,), "source": (GEO,),
            "dest_group": _group("Points on the target to be painted"),
            "source_group": _group("Points on the source that take part in sampling"),

            **{k: _sec("Attributes", v) for k, v in {
                "point_attributes": _names("attrib", "point", "Cd"),
                "prim_attributes": _names("attrib", "prim", ""),
                "detail_attributes": _names("attrib", "detail", ""),
                "point_groups": ("STRING", {"default": "", "is_group": True}),
                "prim_groups": ("STRING", {"default": "", "is_group": True}),
            }.items()},

            **{k: _sec("Conditions", v) for k, v in {
                "distance_threshold": _f(1.0, 0.0, 1e6, 0.01),
                "blend_width": _f(0.0, 0.0, 1e6, 0.01),
                "max_sample_count": _i(1, 1, 4096),
                "kernel": (list(_xfr.KERNELS),),
                "match_attribute": _names(
                    "attrib", "point", "", "Pair only where this attribute is equal on both sides"),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, dest, source, dest_group, source_group,
            point_attributes, prim_attributes, detail_attributes,
            point_groups, prim_groups, distance_threshold, blend_width,
            max_sample_count, kernel, match_attribute):
        return (_xfr.attribute_transfer(
            dest, source, dest_group, source_group,
            point_attributes, prim_attributes, detail_attributes,
            point_groups, prim_groups, distance_threshold, blend_width,
            max_sample_count, kernel, match_attribute),)


class PCG_Ray:
    """
    Mirrors Houdini's Ray SOP. Drop scattered points onto terrain, or shrink-wrap a shell onto a model.

    Project Rays finds intersections along a direction (or the point normal); Minimum Distance finds the closest surface point.
    Points that miss **stay where they were** -- combined with Hit Group, downstream decides whether to delete or keep them.

    Max Distance is not only a filter: it also pins the search range, which greatly cuts the cost of closest-point queries.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "collision": (GEO,),
            "group": _group("Only process these points"),
            "method": (list(_ray.METHODS),),
            "direction_x": _f(0.0), "direction_y": _f(-1.0),
            "direction_z": _f(0.0),
            "use_point_normals": ("BOOLEAN", {"default": False}),
            "reverse": ("BOOLEAN", {"default": False}),
            "both_directions": ("BOOLEAN", {"default": False}),
            "intersect_farthest": ("BOOLEAN", {"default": False}),
            "max_distance": _f(0.0, 0.0, 1e9, 0.1),

            **{k: _sec("Transform", v, gate=(k == "transform_points"))
               for k, v in {
                   "transform_points": ("BOOLEAN", {"default": True}),
                   "scale": _f(1.0, -1e6, 1e6, 0.01),
                   "lift": _f(0.0, -1e6, 1e6, 0.01),
               }.items()},

            **{k: _sec("Output", v) for k, v in {
                "hit_group": ("STRING", {"default": ""}),
                "distance_attribute": ("STRING", {"default": ""}),
                "hitprim_attribute": ("STRING", {"default": ""}),
                "hituv_attribute": ("STRING", {"default": ""}),
                "hitpos_attribute": ("STRING", {"default": ""}),
                "normal_attribute": ("STRING", {"default": ""}),
                "transfer_attributes": _names(
                    "attrib", "point", "", "Taken from the collision surface by barycentric interpolation"),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, collision, group, method, direction_x, direction_y,
            direction_z, use_point_normals, reverse, both_directions,
            intersect_farthest, max_distance, transform_points, scale, lift,
            hit_group, distance_attribute, hitprim_attribute,
            hituv_attribute, hitpos_attribute, normal_attribute,
            transfer_attributes):
        return (_ray.ray(
            geo, collision, group, method,
            (direction_x, direction_y, direction_z), use_point_normals,
            reverse, both_directions, intersect_farthest, max_distance,
            transform_points, scale, lift, hit_group, distance_attribute,
            hitprim_attribute, hituv_attribute, hitpos_attribute,
            normal_attribute, transfer_attributes),)


# ============================================================ Wrangle
class PCG_Wrangle:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "run_over": (["point", "prim", "vertex", "detail"],),
            "code": ("STRING", {"multiline": True, "code_hl": True, "default":
                                "@P.y = sin(length(@P) * 0.5) * 2.0"}),
            "group": _group(),
            "rand_seed": _i(0, 0, 1 << 31),
            # Parameter values for ch("x") in the code, maintained automatically by the frontend after scanning the code.
            # Uses a fixed JSON string instead of adding input sockets to the node dynamically --
            # dynamically added sockets change widget indices, and parameters shift wholesale when the workflow is restored.
            "ch_params": ("STRING", {"default": "{}", "ch_store": True}),
        }, "optional": {
            # Mirrors the four inputs of a Houdini Wrangle. Code accesses them by index, e.g. point(1, "P", i),
            # npoints(2), getbbox_size(3); without an index it is input 0.
            "geo1": (GEO,), "geo2": (GEO,), "geo3": (GEO,),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, run_over, code, group, rand_seed, ch_params="{}",
            geo1=None, geo2=None, geo3=None):
        import json
        try:
            chd = json.loads(ch_params) if ch_params.strip() else {}
        except (ValueError, AttributeError):
            chd = {}
        return (wrangle.run_wrangle(geo, code, run_over, rand_seed,
                                    group=group, ch_params=chd,
                                    inputs=[geo, geo1, geo2, geo3]),)


# ============================================================ image interop
class PCG_HeightfieldFromImage:
    """
    IMAGE -> displaced grid. This is the key node connecting the diffusion side and the geometry side:
    the heightmap can come from the output of any ComfyUI sampler.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "size_x": _f(100.0, 0.001), "size_z": _f(100.0, 0.001),
            "height": _f(20.0, -1e5),
            "resolution": _i(129, 2, 2049),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/image"

    def run(self, image, size_x, size_z, height, resolution):
        img = image[0].cpu().numpy() if hasattr(image, "cpu") else np.asarray(image)[0]
        lum = img[..., :3].mean(-1).astype(np.float32)

        H, W = lum.shape
        yi = np.linspace(0, H - 1, resolution)
        xi = np.linspace(0, W - 1, resolution)
        y0 = np.clip(np.floor(yi).astype(int), 0, H - 1)
        x0 = np.clip(np.floor(xi).astype(int), 0, W - 1)
        y1 = np.clip(y0 + 1, 0, H - 1); x1 = np.clip(x0 + 1, 0, W - 1)
        fy = (yi - y0)[:, None]; fx = (xi - x0)[None, :]
        h = (lum[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) +
             lum[np.ix_(y0, x1)] * (1 - fy) * fx +
             lum[np.ix_(y1, x0)] * fy * (1 - fx) +
             lum[np.ix_(y1, x1)] * fy * fx)

        g = build.grid(size_x, size_z, resolution, resolution)
        P = g.get_w(POINT, "P")
        P[:, 1] = h.reshape(-1) * height
        g.set(POINT, "P", P, owned=True)
        g.set(POINT, "height", h.reshape(-1), owned=True)
        return (ops.compute_normals(g),)


class PCG_PreviewImage:
    """
    Software-rasterized preview, outputs a standard IMAGE that can go straight into PreviewImage / SaveImage.

    Shading: normal (normal colours) / lambert (grey model) / color (**Cd × lighting**, Cd is recognised on
    point / vertex / prim / detail). Since pcg56 it uses Render Pass's vectorized
    rasterizer, so even terrain meshes with hundreds of thousands of triangles take seconds.

    pcg123 Outdoor look: a perspective environment shot -- the Camera node's view (or an automatic 35 mm camera at
    Elevation / Azimuth), a sky with a sun, sun light with shadows plus sky fill and ground bounce, aerial perspective
    (Haze) and an optional ground plane to the horizon. Textures work as in the studio look; PBR surfaces reflect the sky.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "width": _i(512, 64, 4096), "height": _i(512, 64, 4096),
            "elevation": _f(25.0, -89, 89, 1.0), "azimuth": _f(35.0, -360, 360, 1.0),
            "shading": (list(convert.SHADINGS),),
        }, "optional": {
            "color_attrib": ("STRING", {"default": "Cd"}),
            # pcg110, appended (defaults = old behaviour): the "studio" look -- smooth shading, shadows, AO, a ground that
            # catches shadows, gradient background, BaseColor textures by material
            "look": (["basic", "studio", "outdoor"],),
            "supersampling": _i(2, 1, 4),
            "textures": ("STRING", {"default": "", "multiline": True,
                                    "tooltip": "Studio look: 'basecolor = path', 'normal = path' (OpenGL +Y), "
                                               "'orm = path' (R AO, G roughness, B metallic; switches to PBR "
                                               "shading) or ao / roughness / metallic alone, relative to ComfyUI's "
                                               "output folder; {material} is replaced by each face's material name; "
                                               "'@layer' reads textures_cop. Missing files leave Cd"}),
            "material_attrib": ("STRING", {"default": "material"}),
            "uv_attrib": ("STRING", {"default": "uv"}),
            "textures_cop": ("COPIMAGE",),
            # pcg123, appended: the outdoor look (perspective, sky, sun, haze); camera optional for it
            "camera": (CAM,),
            "sun_elevation": _f(35.0, 1.0, 90.0, 1.0),
            "sun_azimuth": _f(135.0, -360.0, 360.0, 1.0),
            "haze": _f(1.0, 0.0, 20.0, 0.05),
            "ground_plane": ("BOOLEAN", {"default": True}),
            "ground_color": ("STRING", {"default": "0.32 0.31 0.27"}),
            "exposure": _f(1.0, 0.05, 8.0, 0.05),
        }}
    RETURN_TYPES = ("IMAGE",); RETURN_NAMES = ("image",)
    FUNCTION = "run"; CATEGORY = CAT + "/output"

    def run(self, geo, width, height, elevation, azimuth, shading,
            color_attrib="Cd", look="basic", supersampling=2, textures="",
            material_attrib="material", uv_attrib="uv", textures_cop=None, camera=None,
            sun_elevation=35.0, sun_azimuth=135.0, haze=1.0, ground_plane=True,
            ground_color="0.32 0.31 0.27", exposure=1.0):
        # A bare `import torch` leaves only "No module named 'torch'" in the log,
        # which says neither which node needs it nor which python to install it into. Same treatment as other optional dependencies
        torch = convert.need("torch", "Preview Image (to hand the result to ComfyUI)")
        if look == "outdoor":
            from .geo import outdoor as _od
            try:
                gc = [float(x) for x in str(ground_color).replace(",", " ").split()]
            except ValueError:
                gc = []
            if len(gc) != 3:
                raise ValueError(f"Ground Color: three numbers 0..1 (r g b), got {ground_color!r}")
            img = _od.render_outdoor(geo, width, height, camera, elevation, azimuth, color_attrib,
                                     supersampling, textures, output_dir(), material_attrib, uv_attrib,
                                     sun_elevation, sun_azimuth, haze, ground_plane, gc, exposure,
                                     tex_cop=textures_cop)
        elif look == "studio":
            from .geo import studio as _st
            img = _st.render_studio(geo, width, height, elevation, azimuth, color_attrib,
                                    supersampling, textures, output_dir(), material_attrib, uv_attrib,
                                    tex_cop=textures_cop)
        else:
            img = convert.render_preview(geo, width, height, elevation, azimuth,
                                         shading, color_attrib)
        return (torch.from_numpy(img)[None, ...],)


def output_dir():
    """ComfyUI's output directory; outside ComfyUI (tests) it is output/ under the current directory."""
    try:
        import folder_paths
        return folder_paths.get_output_directory()
    except Exception:
        return os.path.abspath("output")


class PCG_ExportMesh:
    """
    Writes to ComfyUI/output/ and returns the relative path.
    A .glb path can be fed straight to the built-in Preview3D node for interactive viewing.

    Since pcg84 glTF / OBJ are written by our own code (no longer via trimesh): with UVs, normals (vertex N first, for hard edges),
    tangents (same set as COP Bake Textures, so baked normal maps line up) and vertex colours.
    Split Attribute splits into several meshes / nodes by a prim attribute (name = attribute value: LOD and collision
    naming conventions rely on it); File Attribute splits into files by another prim attribute, filename_value.glb
    (writing {name} in the file name substitutes that value).
    glTF follows the spec: Y up, metres, UV origin at the top left (written as v -> 1 − v); Scale multiplies positions
    (give 100 for centimetres).

    pcg84 Textures: one `slot = path` per line (basecolor / normal / orm / emissive; paths are relative to the exported
    file, {material} is replaced by the material slot name), written into the glb as external images, so textures attach directly on import into Blender / engines;
    orm serves as both occlusion and metallicRoughness (glTF's channel convention is R AO, G roughness, B metal);
    for normal use the OpenGL (+Y) one. Texture Materials restricts which material slots they attach to. OBJ also writes a .mtl.

    pcg122 GPU Instancing (glb): packed primitives (Pack / Copy to Points with Pack and Instance) are written as one
    mesh per distinct piece plus one node with EXT_mesh_gpu_instancing holding each instance's translation / rotation /
    scale. Pieces with sheared transforms, OBJ output, or the option off: unpacked into ordinary geometry.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "filename": ("STRING", {"default": "pcg/mesh"}),
            "format": (["glb", "obj"],),
            # pcg84 addition at the end (old workflows' widget indices unchanged)
            "split_attribute": ("STRING", {"default": ""}),
            "file_attribute": ("STRING", {"default": ""}),
            "scale": _f(1.0, 1e-6, 1e6, 0.01),
            # pcg84
            "textures": ("STRING", {"default": "", "multiline": True, "section": "Textures",
                                    "tooltip": "One slot = path per line (relative to the exported file): basecolor / "
                                               "normal / orm / emissive; {material} is replaced by the material slot name"}),
            "texture_materials": ("STRING", {"default": "*", "section": "Textures",
                                             "tooltip": "Only attach textures to material slots whose names match (space-separated wildcards)"}),
            # pcg122: packed primitives -> EXT_mesh_gpu_instancing (glb only; OBJ always unpacks)
            "gpu_instancing": ("BOOLEAN", {"default": True,
                                           "tooltip": "glb: packed primitives become one mesh per piece + per-instance "
                                                      "transforms (EXT_mesh_gpu_instancing); off = unpack everything"}),
        }}
    RETURN_TYPES = ("STRING",); RETURN_NAMES = ("path",)
    FUNCTION = "run"; CATEGORY = CAT + "/output"
    OUTPUT_NODE = True

    def run(self, geo, filename, format, split_attribute="", file_attribute="",
            scale=1.0, textures="", texture_materials="*", gpu_instancing=True):
        from .geo import meshexport as _mx
        outdir = output_dir()
        paths = _mx.export(geo, os.path.join(outdir, filename), format,
                           split_attribute, file_attribute, scale,
                           textures=textures, texture_materials=texture_materials,
                           gpu_instancing=gpu_instancing)
        rels = [os.path.relpath(p, outdir).replace("\\", "/") for p in paths]
        rel = rels[0] if len(rels) == 1 else "\n".join(rels)
        # Note: the ui structure Preview3D expects changes between ComfyUI versions;
        # the implementation in your local comfy_extras/nodes_load_3d.py is authoritative.
        return {"ui": {"text": rels}, "result": (rel,)}


class PCG_ImportMesh:
    """
    Reads a mesh / point cloud file. OBJ / PLY / STL / GLB (gltf), **pure python,
    zero dependencies**.

    This is the biggest piece in the AI -> procedural direction: the image-to-3D generation of models
    (Hunyuan3D / Trellis / TripoSR and the like) spits out "**right shape, rotten topology**" --
    triangle soup, duplicate points, no UVs, runaway face counts. And this plugin is itself the toolset for fixing topology:

        Import Mesh -> Fuse -> Facet (recompute normals) -> PolyReduce -> UV AutoSeams
        → UV Flatten → UV Layout → Export Mesh

    **No triangulation** on the way in: OBJ ngons are kept as is (PolyReduce's quad preservation and
    Dissolve's coplanar merging both need the original face structure).

    ━━ Some parameters are not decoration; getting them wrong fails **silently**
    · **weld=auto welds points for STL.** STL is triangle soup: every triangle carries its own three points,
      shared with nothing. Without welding there are three times the points and zero connectivity, so Subdivide /
      PolyReduce / Connectivity / Normal's cusp all quietly stop working --
      no error, just "why are there still cracks after subdividing". The tolerance is **relative to the bounding box**.
    · **up_axis is not guessed.** The glTF spec is Y-up (same as the viewport); OBJ / PLY / STL
      have no convention, and Blender exports are often Z-up. It is an explicit parameter rather than a heuristic:
      guessing right nine times and wrong the tenth is worse than choosing yourself every time.
    · **format=auto looks at magic numbers, not extensions** (renamed extensions are common in AI pipelines).
      Binary STL is detected by the length criterion `84 + 50×triangle count` -- its header often
      literally says "solid", and judging by the start would read it as ascii and produce an empty mesh.

    ━━ uv lands on vertex
    OBJ's `vt` is a **per-corner** index (the same point can have different uvs on different faces; that is the definition
    of a seam); writing it to point would silently erase seams. glTF's per-point uv is also expanded to vertex --
    the default class of every UV node in this package is VERTEX, and mixing them would make it "invisible" downstream.

    ━━ 3DGS .ply files can be read directly
    A PLY without faces is a point cloud; every property goes into point attributes as is (`opacity` /
    `scale_*` / `rot_*` / `f_dc_*` are all there). With `splat_color` on, the spherical-harmonics degree-0
    coefficients are converted to `Cd` (`C = 0.282095 × f_dc + 0.5`), so dragging it into the viewport gives
    a coloured point cloud.

    ━━ mesh port
    In-memory meshes (`MESH` type) from other 3D plugins plug in here, **duck-typed**:
    it recognises `.vertices/.faces`, `{"vertices":..,"faces":..}`, and lists of those;
    torch tensors are converted to numpy automatically. When it is wired, filename is ignored.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "filename": ("STRING", {"default": "mesh.glb"}),
            "format": (list(_mio.FORMATS),),
            "weld": (list(_mio.WELD_MODES),),
            "weld_rel": _f(_mio.WELD_REL, 0.0, 0.1, 1e-6),
            "up_axis": (list(_mio.UP_AXES),),
            "scale": _f(1.0, -1e6, 1e6, 0.01),
            "flip_winding": ("BOOLEAN", {"default": False}),
            "merge_parts": ("BOOLEAN", {"default": True}),
            "splat_color": ("BOOLEAN", {"default": True}),
            "keep_extra_attribs": ("BOOLEAN", {"default": True}),
        }, "optional": {"mesh": ("MESH",)}}
    RETURN_TYPES = (GEO, "INT", "INT", "STRING")
    RETURN_NAMES = ("geo", "points", "prims", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/convert"

    @classmethod
    def IS_CHANGED(cls, filename="", **kw):
        """
        **When the file contents change it must recompute.** ComfyUI's cache is keyed by input hashes, and the file name
        does not change -- so after "the AI regenerated mesh.glb" this node would serve the previous geometry
        without any error. mtime + size serve as the fingerprint (far cheaper than hashing the whole file, and
        sufficient: the generation flow rewrites the file every time).

        When the file cannot be read, return the file name itself, **do not raise** -- IS_CHANGED is called before
        execution, and raising here would keep the whole graph from even being queued, with an odd error location.
        """
        try:
            st = os.stat(_mio.resolve(filename))
            return f"{st.st_mtime_ns}:{st.st_size}"
        except Exception:
            return str(filename)

    def run(self, filename, format, weld, weld_rel, up_axis, scale,
            flip_winding, merge_parts, splat_color, keep_extra_attribs,
            mesh=None):
        if mesh is not None:
            g = _mio.from_object(mesh, weld=("on" if weld == "on" else "off"),
                                 weld_rel=weld_rel, up_axis=up_axis,
                                 scale=scale, flip_winding=flip_winding)
            info = f"MESH port  points {g.npoints}  prims {g.nprims}"
        else:
            g, info = _mio.load(
                _mio.resolve(filename), fmt=format, weld=weld,
                weld_rel=weld_rel, up_axis=up_axis, scale=scale,
                flip_winding=flip_winding, merge=merge_parts,
                splat_color=splat_color, keep_extra=keep_extra_attribs)
        return (g, g.npoints, g.nprims, info)


class PCG_Add:
    """
    Mirrors Houdini's Add SOP. Three things: create points, connect points into polygons, keep only points and drop the faces.

    The parameter panel differs from Houdini in two places, both forced by ComfyUI:

    * In Houdini, coordinates and polygons are multiparms (parameter blocks you can add and remove). ComfyUI has no
      multiparm, and dynamically adding/removing widgets makes parameters shift wholesale when the workflow is restored
      (the same pit as noted in pcg_sections.js). So they are multi-line text boxes, one entry per line,
      which can be pasted straight from a spreadsheet.
    * Point number strings keep order and repeats (`3 1 2` and `1 2 3` are two faces with different winding), so
      the group field's parsing, which returns a boolean mask, cannot be reused.

    Execution order = Houdini's order: keep only points -> append new points -> connect polygons -> clean up.
    New points come after the existing ones, and all three connection methods can refer to both old and new points.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "points": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "One new point per line: x y z (commas work too); lines starting with # are comments"}),

                **{k: _sec("Delete Geometry", v, gate=(k == "keep_points"))
                   for k, v in {
                       "keep_points": ("BOOLEAN", {"default": False}),
                   }.items()},

                **{k: _sec("Polygons by Pattern", v, gate=(k == "use_pattern"))
                   for k, v in {
                       "use_pattern": ("BOOLEAN", {"default": False}),
                       "pattern": ("STRING", {
                           "multiline": True, "default": "0-3",
                           "tooltip": "One polygon per line: 0-3 / 5 2 7 / 0-20:3; "
                                      "negative numbers count from the end"}),
                       "pattern_closed": ("BOOLEAN", {"default": True}),
                   }.items()},

                **{k: _sec("Polygons by Group", v, gate=(k == "use_group"))
                   for k, v in {
                       "use_group": ("BOOLEAN", {"default": False}),
                       "group": _group("Points to connect; empty = all"),
                       "group_mode": (["all_points", "groups_of_n",
                                       "every_nth", "each_point"],),
                       "group_n": _i(2, 1, 1 << 20),
                       "group_closed": ("BOOLEAN", {"default": False}),
                   }.items()},

                **{k: _sec("Polygons by Attribute", v,
                           gate=(k == "use_attribute")) for k, v in {
                       "use_attribute": ("BOOLEAN", {"default": False}),
                       "attribute": _names("attrib", "point", "class",
                                           "points with the same value are connected into one"),
                       "attribute_closed": ("BOOLEAN", {"default": False}),
                   }.items()},

                **{k: _sec("Remove", v, gate=(k == "use_remove")) for k, v in {
                    "use_remove": ("BOOLEAN", {"default": False}),
                    "remove_repeated": ("BOOLEAN", {"default": True}),
                    "remove_unused": ("BOOLEAN", {"default": False}),
                }.items()},
            },
            # With no input it is a pure generator -- Houdini's Add can also be used unwired
            "optional": {"geo": (GEO,)},
        }
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, points, keep_points, use_pattern, pattern, pattern_closed,
            use_group, group, group_mode, group_n, group_closed,
            use_attribute, attribute, attribute_closed,
            use_remove, remove_repeated, remove_unused, geo=None):
        return (addsop.add(
            geo, points, keep_points,
            use_pattern, pattern, pattern_closed,
            use_group, group, group_mode, group_n, group_closed,
            use_attribute, attribute, attribute_closed,
            use_remove and remove_repeated,
            use_remove and remove_unused),)


class PCG_Facet:
    """
    Mirrors Houdini's Facet SOP: a series of topology-cleanup toggles in a fixed order

        unique -> consolidate -> orient -> cusp -> inline -> degenerate -> normals

    The order is Houdini's, and each step takes the previous step's result. The easiest pit to fall into:
    **orient must come before cusp**. With inconsistent winding, adjacent face normals point opposite ways, the angle is always 180°,
    and the whole geometry gets treated as all hard edges and split apart.

    cusp and the vertex mode of Normal (PCG) are two different things: Normal just stores one normal per corner,
    and the geometry itself is unchanged; Facet's cusp **really splits the points**, and after that any point normal you compute
    is hard. For exporting to an engine, making UV seams, or letting downstream operators see hard edges, use this.

    group is a prim group: faces outside it are always kept as is -- no rewinding, no point splitting, no corner deletion.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Prim group; empty = all; faces outside the group are untouched"),

            **{k: _sec("Unique Points", v, gate=(k == "unique_points"))
               for k, v in {
                   "unique_points": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Consolidate Points", v,
                       gate=(k == "consolidate_points")) for k, v in {
                   "consolidate_points": ("BOOLEAN", {"default": False}),
                   "consolidate_distance": _f(0.001, 0.0, 1e5, 0.0001),
               }.items()},

            **{k: _sec("Orient Polygons", v, gate=(k == "orient_polygons"))
               for k, v in {
                   "orient_polygons": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Cusp Polygons", v, gate=(k == "cusp_polygons"))
               for k, v in {
                   "cusp_polygons": ("BOOLEAN", {"default": False}),
                   "cusp_angle": _f(60.0, 0.0, 180.0, 1.0),
               }.items()},

            **{k: _sec("Remove Inline Points", v, gate=(k == "remove_inline"))
               for k, v in {
                   "remove_inline": ("BOOLEAN", {"default": False}),
                   "inline_distance": _f(0.001, 0.0, 1e5, 0.0001),
               }.items()},

            **{k: _sec("Remove Degenerate", v,
                       gate=(k == "remove_degenerate")) for k, v in {
                   "remove_degenerate": ("BOOLEAN", {"default": False}),
                   "degenerate_distance": _f(0.0001, 0.0, 1e5, 0.0001),
                   "remove_bad_prims": ("BOOLEAN", {"default": True}),
               }.items()},

            **{k: _sec("Normals", v, gate=(k == "post_normals")) for k, v in {
                "post_normals": ("BOOLEAN", {"default": False}),
                "unit_normals": ("BOOLEAN", {"default": False}),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, unique_points, consolidate_points,
            consolidate_distance, orient_polygons, cusp_polygons, cusp_angle,
            remove_inline, inline_distance, remove_degenerate,
            degenerate_distance, remove_bad_prims, post_normals, unit_normals):
        return (facet.facet(
            geo, group, unique_points, consolidate_points, consolidate_distance,
            orient_polygons, cusp_polygons, cusp_angle,
            remove_inline, inline_distance,
            remove_degenerate, degenerate_distance, remove_bad_prims,
            post_normals, unit_normals),)


class PCG_Divide:
    """
    Mirrors Houdini's Divide SOP: cuts faces smaller, or conversely merges them / takes the dual.

    Triangulation is **done properly** here: convex faces use a fan (O(n); the vast majority of faces are convex),
    concave ones use ear clipping. Convert (PCG)'s triangles is a pure fan, and concave ngons grow triangles that stick outside
    the shape -- and concave ngons are everywhere in the output of Boolean / PolyBevel / Carve.
    For correct triangles, use this node.

    With Maximum Edges > 3 it ear-clips first and then greedily merges back into convex N-gons, merging only across diagonals, and the result
    must still be convex, so the covered area matches the original face.

    Bricker Polygons cuts faces into bricks with three sets of parallel planes by Brick Size (commonly used to cut floors / window panes
    on buildings). Smooth Polygons is not done -- that is subdivision; use the Subdivide node.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Faces to process; empty = all"),

            **{k: _sec("Convex Polygons", v, gate=(k == "convex_polygons"))
               for k, v in {
                   "convex_polygons": ("BOOLEAN", {"default": True}),
                   "max_edges": _i(3, 3, 4096),
                   "avoid_slivers": ("BOOLEAN", {"default": False}),
                   "avoid_small_angles": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Triangulate Non-Planar", v,
                       gate=(k == "triangulate_nonplanar")) for k, v in {
                   "triangulate_nonplanar": ("BOOLEAN", {"default": True}),
                   "planar_tolerance": _f(0.0001, 0.0, 1e5, 0.0001),
               }.items()},

            **{k: _sec("Bricker Polygons", v, gate=(k == "brick_polygons"))
               for k, v in {
                   "brick_polygons": ("BOOLEAN", {"default": False}),
                   "brick_size_x": _f(1.0, 0.0), "brick_size_y": _f(1.0, 0.0),
                   "brick_size_z": _f(1.0, 0.0),
                   "brick_offset_x": _f(0.0), "brick_offset_y": _f(0.0),
                   "brick_offset_z": _f(0.0),
                   "brick_angle_x": _f(0.0, -3600, 3600, 1.0),
                   "brick_angle_y": _f(0.0, -3600, 3600, 1.0),
                   "brick_angle_z": _f(0.0, -3600, 3600, 1.0),
                   "brick_shared_edges": ("BOOLEAN", {"default": True}),
               }.items()},

            **{k: _sec("Remove Shared Edges", v,
                       gate=(k == "remove_shared_edges")) for k, v in {
                   "remove_shared_edges": ("BOOLEAN", {"default": False}),
               }.items()},

            **{k: _sec("Compute Dual", v, gate=(k == "compute_dual"))
               for k, v in {
                   "compute_dual": ("BOOLEAN", {"default": False}),
                   "attributes_to_swap": _names(
                       "attrib", "point", "* ^P",
                       "matched prim attributes become new point attributes, point attributes become new primitive attributes"),
               }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, convex_polygons, max_edges, avoid_slivers,
            avoid_small_angles, triangulate_nonplanar, planar_tolerance,
            brick_polygons, brick_size_x, brick_size_y, brick_size_z,
            brick_offset_x, brick_offset_y, brick_offset_z,
            brick_angle_x, brick_angle_y, brick_angle_z, brick_shared_edges,
            remove_shared_edges, compute_dual, attributes_to_swap):
        return (divide.divide(
            geo, group, convex_polygons, max_edges,
            triangulate_nonplanar, planar_tolerance,
            avoid_slivers, avoid_small_angles,
            brick_polygons,
            (brick_size_x, brick_size_y, brick_size_z),
            (brick_offset_x, brick_offset_y, brick_offset_z),
            (brick_angle_x, brick_angle_y, brick_angle_z),
            brick_shared_edges,
            remove_shared_edges, compute_dual, attributes_to_swap),)


class PCG_Fuse:
    """
    Mirrors Houdini's Fuse SOP. Three sections: Snap decides which points count as the same point and where they snap to,
    Fuse decides whether to really weld the topology, Output handles groups and normals.

    Difference from the old Fuse (PCG) node: the old one quantized to a grid, so points 0.6d apart but on either side of a cell boundary
    could not merge, while points 1.7d apart in the same cell were merged. This one does a real within-radius neighbour search
    (uniform grid hash, no scipy), then takes the transitive closure of the pairs.

    With the second input target wired, points in the group snap to points on target -- the two geometries are not merged
    into one; the second input only supplies "where to snap to". modify_target is the reverse and outputs the modified target.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "geo": (GEO,),
                "group": _group("Points that take part in snapping; empty = all"),
                "position_attribute": _names(
                    "attrib", "point", "P",
                    "which coordinates to judge distance by. Storing a rest copy and fusing by rest is a common usage"),
                "snap_to": (["near_points", "grid", "none"],),
                "using": (["least_point_number", "closest",
                           "greatest_point_number"],),
                "output_positions": (["average", "target", "keep"],),

                **{k: _sec("Snap Distance", v,
                           gate=(k == "use_snap_distance")) for k, v in {
                       "use_snap_distance": ("BOOLEAN", {"default": True}),
                       "snap_distance": _f(0.001, 0.0, 1e5, 0.0001),
                   }.items()},

                **{k: _sec("Grid", v, gate=(k == "use_grid")) for k, v in {
                    "use_grid": ("BOOLEAN", {"default": False}),
                    "grid_x": _f(0.1, 0.0), "grid_y": _f(0.1, 0.0),
                    "grid_z": _f(0.1, 0.0),
                    "grid_off_x": _f(0.0), "grid_off_y": _f(0.0),
                    "grid_off_z": _f(0.0),
                }.items()},

                **{k: _sec("Radius", v, gate=(k == "use_radius")) for k, v in {
                    "use_radius": ("BOOLEAN", {"default": False}),
                    "radius_attribute": _names("attrib", "point", "pscale"),
                }.items()},

                **{k: _sec("Match Attribute", v, gate=(k == "use_match"))
                   for k, v in {
                       "use_match": ("BOOLEAN", {"default": False}),
                       "match_attribute": _names("attrib", "point", "name"),
                       "match_condition": (["equal", "unequal"],),
                       "match_tolerance": _f(0.0, 0.0, 1e5, 0.0001),
                   }.items()},

                **{k: _sec("Target", v, gate=(k == "use_target")) for k, v in {
                    "use_target": ("BOOLEAN", {"default": False}),
                    "target_group": _group("Target points in the second input; empty = all"),
                    "modify_target": ("BOOLEAN", {"default": False}),
                }.items()},

                **{k: _sec("Fuse", v, gate=(k == "fuse_snapped_points"))
                   for k, v in {
                       "fuse_snapped_points": ("BOOLEAN", {"default": True}),
                       "keep_fused_points": ("BOOLEAN", {"default": False}),
                       "remove_repeated": ("BOOLEAN", {"default": True}),
                       "remove_degenerate_unused": ("BOOLEAN", {"default": True}),
                       "remove_all_unused": ("BOOLEAN", {"default": False}),
                   }.items()},

                **{k: _sec("Output", v, gate=(k == "use_output")) for k, v in {
                    "use_output": ("BOOLEAN", {"default": True}),
                    "recompute_normals": ("BOOLEAN", {"default": True}),
                    "snapped_points_group": ("STRING", {"default": ""}),
                    "snapped_to_group": ("STRING", {"default": ""}),
                    "attributes_to_snap": _names(
                        "attrib", "point", "",
                        "these point attributes are averaged along too, e.g. N uv"),
                }.items()},
            },
            "optional": {"target": (GEO,)},
        }
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, position_attribute, snap_to, using,
            output_positions, use_snap_distance, snap_distance,
            use_grid, grid_x, grid_y, grid_z, grid_off_x, grid_off_y,
            grid_off_z, use_radius, radius_attribute,
            use_match, match_attribute, match_condition, match_tolerance,
            use_target, target_group, modify_target,
            fuse_snapped_points, keep_fused_points, remove_repeated,
            remove_degenerate_unused, remove_all_unused,
            use_output, recompute_normals, snapped_points_group,
            snapped_to_group, attributes_to_snap, target=None):
        on = use_output
        return (fusesop.fuse(
            geo, target if use_target else None,
            group, target_group if use_target else "",
            modify_target if use_target else False,
            snap_to, using, use_snap_distance, snap_distance,
            output_positions,
            radius_attribute if use_radius else "",
            match_attribute if use_match else "",
            match_condition, match_tolerance,
            (grid_x, grid_y, grid_z) if use_grid else (0.1, 0.1, 0.1),
            (grid_off_x, grid_off_y, grid_off_z) if use_grid else (0, 0, 0),
            fuse_snapped_points,
            keep_fused_points and fuse_snapped_points,
            remove_repeated and fuse_snapped_points,
            remove_degenerate_unused and fuse_snapped_points,
            remove_all_unused and fuse_snapped_points,
            recompute_normals and on,
            snapped_points_group if on else "",
            snapped_to_group if on else "",
            attributes_to_snap if on else "",
            position_attribute),)


class PCG_Clip:
    """
    Mirrors Houdini's Clip SOP: cuts geometry with a plane.

    Plane = the one through origin + distance*direction with normal direction.
    With keep=both both halves are kept, just split along the plane -- follow with Connectivity or a For-Each
    looping over connected pieces, and that is the most direct "cut, then process each separately".

    Cut points create new points, and **every attribute on a new point is interpolated from both ends** -- position, normal,
    UV, point groups, edge groups, nothing is missed. This interpolation mechanism is a separate layer in geo/clip.py;
    Bricker sits directly on top of it, and Boolean's retriangulation can hook into it later.

    Concave faces are ear-clipped into triangles before cutting (Sutherland-Hodgman produces self-intersecting results on concave polygons),
    so a cut concave face becomes a pile of triangles. To get large faces back, add Divide's Remove Shared Edges downstream.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only cut these faces; empty = all; faces outside the group are kept as is"),
            "keep": (["below", "above", "both"],),
            "dir_x": _f(0.0), "dir_y": _f(1.0), "dir_z": _f(0.0),
            "distance": _f(0.0),

            **{k: _sec("Origin", v, gate=(k == "use_origin")) for k, v in {
                "use_origin": ("BOOLEAN", {"default": False}),
                "origin_x": _f(0.0), "origin_y": _f(0.0), "origin_z": _f(0.0),
            }.items()},

            **{k: _sec("Output Groups", v, gate=(k == "use_out_groups"))
               for k, v in {
                   "use_out_groups": ("BOOLEAN", {"default": False}),
                   "above_group": ("STRING", {"default": "above"}),
                   "below_group": ("STRING", {"default": "below"}),
                   "seam_group": ("STRING", {"default": "clipseam"}),
               }.items()},
        }, "optional": {
            # ── pcg100 addition (default = previous behaviour; see clip in geo/clip.py) ──
            "orient": (list(_clip.ORIENTS),),
            "translate_x": _f(0.0), "translate_y": _f(0.0), "translate_z": _f(0.0),
            "rotate_x": _f(0.0), "rotate_y": _f(0.0), "rotate_z": _f(0.0),
            "snap_tolerance": _f(0.0, 0.0, 1e6, 0.0001),
            "fill": ("BOOLEAN", {"default": False}),
            "split_connectivity": ("BOOLEAN", {"default": False}),
            "clip_attribute": _names("attrib", "point", "P"),
            # These two groups, like the three above, are governed by the Create Groups toggle; empty by default = not created
            "clipped_group": ("STRING", {"default": ""}),
            "fill_group": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, keep, dir_x, dir_y, dir_z, distance,
            use_origin, origin_x, origin_y, origin_z,
            use_out_groups, above_group, below_group, seam_group,
            orient="direction", translate_x=0.0, translate_y=0.0, translate_z=0.0,
            rotate_x=0.0, rotate_y=0.0, rotate_z=0.0, snap_tolerance=0.0,
            fill=False, split_connectivity=False, clip_attribute="P",
            clipped_group="", fill_group=""):
        on = use_out_groups
        return (_clip.clip(
            geo, group, (dir_x, dir_y, dir_z), distance,
            (origin_x, origin_y, origin_z) if use_origin else (0.0, 0.0, 0.0),
            keep,
            above_group if on else "", below_group if on else "",
            seam_group if on else "",
            orient, (translate_x, translate_y, translate_z),
            (rotate_x, rotate_y, rotate_z), snap_tolerance, fill,
            split_connectivity, clip_attribute,
            clipped_group if on else "", fill_group if on else ""),)


class PCG_Split:
    """
    Mirrors Houdini's Split SOP: splits geometry into two outputs by group.

    The only difference from Blast is that Blast throws away one half while Split gives you both -- in a loop body,
    structures like "do A on the selected, B on the rest, then merge back" save a Blast with it.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Elements that go to inside; empty = everything goes to inside"),
            "cls": (["prim", "point"],),
        }}
    RETURN_TYPES = (GEO, GEO); RETURN_NAMES = ("inside", "outside")
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, cls):
        m = groups.resolve(geo, cls, group)
        cut = ops.delete_prims if cls == "prim" else ops.delete_points
        return (cut(geo, m), cut(geo, ~m))


class PCG_ConvexHull:
    """
    3D convex hull. Mirrors Houdini's Convex Hull SOP.

    More useful than it looks: collision proxies, turning a cloud of scattered points into one solid, the exact answer to "how much room
    does this pile of points take up", and the oriented mode of Bound (PCG).

    The algorithm is quickhull: each round picks the **farthest** outside point as the new vertex (the farthest point is always on the final hull,
    and it removes a big patch of faces at once), deletes the faces visible from it, and connects the horizon to it with a ring of new faces.

    **The visible faces are found by flood fill along adjacency from the current face, not by scanning the whole table.** A visible set from a full scan is not guaranteed
    connected -- floating-point noise makes some nearly coplanar face far away also report "visible", the horizon becomes two loops,
    and the resulting shell is broken. Measured: a 32×24 sphere got cut into 9940 faces with 2442 boundary edges.
    After flood fill: 1408 faces (= 2V−4), 0 boundary edges, and 25 times faster.

    **Tolerance defaults to 1e-6, not 1e-9.** Geometry P is float32; coordinates at unit scale already have an error
    of 6e-8; using 1e-9 as the "outside the face" threshold treats quantization noise as real protrusion,
    and a ring of points that should be coplanar grows a pile of zero-area slivers.

    Merge Coplanar Faces merges coplanar triangles into polygons -- the hull of a cube is 6 quads
    rather than 12 triangles. Collision proxies usually want pure triangles; turn it off then.

    Degenerate input does not raise an error; it **outputs one dimension lower**: coplanar points give a polygon, collinear ones a segment, coincident ones
    a point. Houdini simply gives empty geometry here; one dimension lower is more useful -- collapsing a set of coplanar scattered points into one
    polygon is exactly what you want when drawing plot outlines.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "merge_coplanar_faces": ("BOOLEAN", {"default": True}),
            "tolerance": _f(1e-6, 1e-12, 1.0, 1e-7),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, merge_coplanar_faces, tolerance):
        return (_hul.convex_hull(geo, group, tolerance,
                                 merge_coplanar_faces),)


class PCG_Bound:
    """
    Bounding box / bounding sphere / minimum-volume oriented bounding box. Mirrors Houdini's Bound SOP.

        box       axis-aligned bounding box. Fastest and most common, but absurdly bloated as soon as the object is tilted
        sphere    bounding sphere. Rotation-invariant, the easiest for coarse culling
        oriented  minimum-volume oriented bounding box (OBB). Tight, at the cost of computing a convex hull first

    For a thin rod tilted at 45°, the measured volume of the axis-aligned box is 11 times the OBB -- using it as a collision proxy
    counts a big chunk of surrounding air as solid.

    The OBB does not need to sweep all orientations: O'Rourke's result is that the optimal box **always has a face flush with some face of the hull**
    (the 2D version is more familiar -- "the minimum-area rectangle always has an edge flush with some edge of the hull", which is what
    the rotating calipers in UV Layout use). So only the hull face normals are enumerated, with one more 2D rotating-calipers pass in the plane.
    Only hull vertices take part: the hull of a 50k-point cloud may have just a few dozen vertices.

    The bounding sphere starts with Ritter + tightens by "move 1/k toward the farthest point", and finally a safety pass grows the radius to cover
    all points -- the iteration converges asymptotically, and without the safety pass one point might be missed by floating-point error.

    Outputs detail attributes `bound_center` / `bound_size` / `bound_rot` (3×3 row-major)
    / `bound_volume`. With bound_rot you can straighten the object, or align other things to it.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "mode": (list(_bnd.MODES),),
            "group": _group(),
            "uniform_padding": _f(0.0, -1e6, 1e6, 0.01),
            "padding_x": _sec("Padding", _f(0.0, -1e6, 1e6, 0.01)),
            "padding_y": _sec("Padding", _f(0.0, -1e6, 1e6, 0.01)),
            "padding_z": _sec("Padding", _f(0.0, -1e6, 1e6, 0.01)),
            "divisions_x": _sec("Divisions", _i(2, 2, 1 << 12)),
            "divisions_y": _sec("Divisions", _i(2, 2, 1 << 12)),
            "divisions_z": _sec("Divisions", _i(2, 2, 1 << 12)),
            "sphere_cols": _sec("Sphere", _i(24, 3, 1 << 12)),
            "sphere_rows": _sec("Sphere", _i(16, 2, 1 << 12)),
            "max_normals": _sec("Oriented", _i(256, 1, 1 << 16)),
            "tolerance": _sec("Oriented", _f(1e-6, 1e-12, 1.0, 1e-7)),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, mode, group, uniform_padding, padding_x, padding_y,
            padding_z, divisions_x, divisions_y, divisions_z, sphere_cols,
            sphere_rows, max_normals, tolerance):
        return (_bnd.bound(geo, mode, group,
                           (padding_x, padding_y, padding_z), uniform_padding,
                           (divisions_x, divisions_y, divisions_z),
                           sphere_cols, sphere_rows, tolerance, max_normals),)


class PCG_ConvexDecompose:
    """
    Splits a concave solid into several convex pieces (approximate convex decomposition). Mirrors V-HACD / Houdini's
    Convex Decomposition.

    A convex hull gives "the outermost skin", and for an L shape, a bowl or a chair, what the hull smears over is exactly what
    makes them that shape. Convex collision in physics engines is fast, concave is slow or unsupported, so the industry
    practice is splitting into a pile of convex pieces.

    **Concavity is measured by volume**: `1 − solid volume / hull volume`; it is exactly 0 when convex, and it is
    the relative amount of "how much air gets included by using the hull for this piece". Another common definition is "distance from the most concave point to the hull",
    but a thin spike of negligible volume could then make the whole object count as highly concave, and the algorithm would hack away at that spike.

    **Where to cut: directly minimize the sum of the two sub-pieces' hull volumes.** The scoring function is the very quantity
    we ultimately optimize, with no need to design proxy metrics for symmetry / balance. Candidates are three axes × Resolution−1
    positions; each candidate really cuts and really computes two hulls.

    **The three axes are the OBB's axes, not the world axes.** World axes give almost no good cut for a tilted L shape --
    every cut goes through both legs. Measured on the same U shape rotated at random: OBB axes 3 pieces, world axes 6 pieces.
    It also makes the whole algorithm rotation-covariant (rotate, then decompose: same piece count, total hull volume within 1%).

    **Max Pieces is a global budget, not a depth limit.** Internally a heap ordered by "absolute concave volume" is kept,
    and each time the worst piece is cut -- however many pieces you allow are spent where they matter most, not on "hacking the first leg all the way down".

    After each cut, split by connectivity: a cut across the opening of a U produces a "piece" that is really two separate
    lumps; without splitting, its hull would include the whole air gap in the middle.

    Mode:
        hull    each piece replaced by its own convex hull -- this is what collision proxies want. Total volume ≥ original volume
        exact   keeps the cut solids. Total volume **exactly equals** the original volume

    exact's volume conservation is a handy self-check: if the union is contained in the original and the volumes add up to the original,
    it can only be **no overlaps and no gaps**.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "mode": (list(_cdc.MODES),),
            "max_concavity": _f(0.05, 0.0, 1.0, 0.005),
            "max_pieces": _i(32, 1, 4096),
            "resolution": _sec("Search", _i(8, 2, 64)),
            "split_axes": _sec("Search", (list(_cdc.AXES),)),
            "min_fraction": _sec("Search", _f(0.02, 0.0, 0.5, 0.005)),
            "cap_mode": _sec("Search", (["ngon", "fan", "triangles"],)),
            "tolerance": _sec("Search", _f(1e-5, 1e-9, 1.0, 1e-6)),
            "piece_attribute": _names("attrib", "prim", "piece"),
            "name_attribute": _names("attrib", "prim", "name"),
            "name_prefix": ("STRING", {"default": "convex"}),
            # pcg111, appended (0 = no limit, the old behaviour): vertex budget per hull for engine collision
            "max_hull_points": _i(0, 0, 4096),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, mode, max_concavity, max_pieces, resolution,
            split_axes, min_fraction, cap_mode, tolerance, piece_attribute,
            name_attribute, name_prefix, max_hull_points=0):
        return (_cdc.decompose(geo, mode, max_concavity, max_pieces,
                               resolution, split_axes, min_fraction, cap_mode,
                               tolerance, name_attribute, piece_attribute,
                               name_prefix, max_hull_points),)


class PCG_FractureDetail:
    """
    Adds noise to the **cut faces** of fractured pieces. Fills the gap Voronoi Fracture leaves: the cut faces it produces are perfectly flat,
    obviously fake at a glance.

    The hard part is not the noise, but that the pieces must still fit back together seamlessly and the outer shell's silhouette must not change at all.

    **The displacement must be a pure function of world coordinates, not a push along the normal.** The first instinct is "push a scalar
    noise along the normal", as displacement maps do -- here that is wrong. Pieces A and B share a wall, and at the same position on the wall
    each piece stores its own point, with the same coordinates but **opposite normals**. Pushing the same scalar along the normal sends the two points in opposite
    world directions: either a crack opens or they interpenetrate. Using **vector noise** instead, the displacement depends only on world
    coordinates, the two points get bit-identical displacement, and the wall is still that wall, just bent.

    The corollary is strong: **the sum of all piece volumes is exactly unchanged** (measured: 60 pieces pushed at amplitude 0.1, off by 2e-8).
    The shell does not move, inner walls deform in sync in pairs, and the pieces still tile the original solid with no overlaps or gaps.

    **The falloff must be a pure function too.** The rim (the ring where cut faces meet the original surface) must be pinned, otherwise the silhouette changes.
    The first version wanted graph distance along the surface, which "hugs the geometry" more -- but the graph distance from a point in A to A's rim
    and from its twin in B to B's rim are not necessarily equal (the two pieces' other inner walls are laid out differently, so shortest paths
    route differently), and shared walls still got torn apart. Changed to Euclidean distance to the **global rim point cloud**.

    **Divisions does a linear subdivision first.** A cut face is usually one big n-gon; pushing points directly just
    bends the plane askew and shows no roughness. Linear subdivision does not change the shape, it only cuts the face up. The whole piece is subdivided --
    subdividing only the cut faces would leave T-junction vertices at the border, and the topology would not be closed.

    **Triangulate Interior is on by default.** Once a wall is pushed non-planar, "fan out from corner 0" picks
    different diagonals on the two sides, the surfaces the two faces represent no longer coincide, and a very thin crack opens
    (measured volume-sum difference 5.1e-3). Picking the fan centre by **lexicographic order of vertex coordinates** guarantees both sides pick the same
    vertex. A pure-function displacement is not enough; even the triangulation has to be one.

    Bevelling is not in this node: the cut faces are already a prim group, so plug in PolyBevel (PCG) directly.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _names("group", "prim", "interior"),
            "divisions": _i(2, 0, 6),
            "amount": _f(0.02, 0.0, 1e6, 0.002),
            "frequency": _f(8.0, 0.0, 1e6, 0.1),
            "relative_to_size": ("BOOLEAN", {"default": True}),
            "falloff": _f(0.1, 0.0, 1e6, 0.01),
            "falloff_mode": (list(_fdt.FALLOFFS),),
            "triangulate_interior": ("BOOLEAN", {"default": True}),
            "noise_type": _sec("Noise", (list(_fdt.NOISE_TYPES),)),
            "fractal": _sec("Noise", (list(_fdt.FRACTALS),)),
            "octaves": _sec("Noise", _i(3, 1, 16)),
            "lacunarity": _sec("Noise", _f(2.0, 0.0, 16.0, 0.05)),
            "roughness": _sec("Noise", _f(0.5, 0.0, 1.0, 0.01)),
            "rand_seed": _i(0, 0, 1 << 31),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, divisions, amount, frequency, relative_to_size,
            falloff, falloff_mode, triangulate_interior, noise_type, fractal,
            octaves, lacunarity, roughness, rand_seed):
        return (_fdt.detail(geo, group, divisions, amount, frequency,
                            noise_type, fractal, octaves, lacunarity,
                            roughness, rand_seed, falloff, falloff_mode,
                            relative_to_size, triangulate_interior),)


class PCG_Deform:
    """
    Twist / Bend / Taper / Squash / Shear. Mirrors Houdini's Twist SOP.

    A pure per-point position function that touches neither topology nor attributes, so it can be chained freely.

    **Outside the capture range it extends rigidly rather than clamping t.** Each point first gets a normalized parameter t
    along the main axis, and the deformation amount follows t. Outside the range (t<0 or t>1) is the easiest place to get wrong: a plain `clip(t,0,1)` is right for
    twist / taper / shear (those deformations only rotate or scale each slice around the axis; the axial
    coordinate is not involved), but **wrong for bend** -- the axial coordinate gets clamped too, and the part outside the range
    collapses onto the end face, looking like a squashed layer. Here the excess length is **carried out rigidly**
    along the end tangent, so that part stays straight and keeps its length.

    **Bend is stable at tiny angles too.** Radius R = L/θ; as θ->0, R becomes astronomical, and the textbook
    form `R − R·cos φ` subtracts two huge numbers -- catastrophic cancellation. At θ=1e-6° its relative
    error is **15%** (symptom: the model starts to jitter when the angle is set very small). Here it is rewritten in sinc form;
    from θ = 180° down to 1e-6° the precision stays at float32 storage precision throughout, and **θ=0 is a bit-exact
    identity**, with no special case needed.

    **Squash conserves volume**: within the range, axial is multiplied by Amount and lateral always by 1/√Amount (lateral deliberately
    does not ramp with t -- a ramped version measured 26%~47% volume difference). Measured relative volume change ≤ 3.7e-08.

    **Normals are fixed with a finite-difference Jacobian** (`J⁻ᵀ n`), not recomputed: curves and point clouds can be fixed too,
    hard edges are not smoothed away, and it is the only correct way under anisotropic deformation -- for the same taper, `J·n`
    is off by 9.9°, a "looks right" kind of wrong. Measured difference from recomputed normals: twist 0.0022°,
    taper 0.0000°, bend 0.1489°.

    Up decides the **secondary direction** (which way bend curls, which way shear pushes); when parallel to Axis another one is picked automatically,
    so it never gives nan. Identity parameters (Angle=0 / Amount=1 / Shear=0) are **bit-exact** identities.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "op": (list(_dfm.OPS),),
            "group": _group("Only deform these points"),
            "axis": (list(_dfm.AXES),),
            "angle": _f(45.0, -36000.0, 36000.0, 1.0),
            "amount": _f(0.5, 0.0001, 1e4, 0.01),
            "shear_b": _f(0.0, -1e4, 1e4, 0.05),
            "shear_c": _f(0.0, -1e4, 1e4, 0.05),
            "normals": (list(_dfm.NORMAL_MODES),),
            "up_x": _sec("Up", _f(0.0)),
            "up_y": _sec("Up", _f(1.0)),
            "up_z": _sec("Up", _f(0.0)),
            "use_range": _sec("Capture", ("BOOLEAN", {"default": False}),
                              gate=True),
            "range_start": _sec("Capture", _f(0.0, -1e6, 1e6, 0.1)),
            "range_end": _sec("Capture", _f(1.0, -1e6, 1e6, 0.1)),
            # pcg100: Houdini's Pivot (default origin = old behaviour)
            "pivot_x": _f(0.0), "pivot_y": _f(0.0), "pivot_z": _f(0.0),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/deform"

    def run(self, geo, op, group, axis, angle, amount, shear_b, shear_c,
            normals, up_x, up_y, up_z, use_range, range_start, range_end,
            pivot_x=0.0, pivot_y=0.0, pivot_z=0.0):
        return (_dfm.deform(geo, op, group, axis, angle, amount,
                            shear_b, shear_c, (up_x, up_y, up_z),
                            use_range, range_start, range_end, normals,
                            (pivot_x, pivot_y, pivot_z)),)


class PCG_SoftTransform:
    """
    A transform with falloff -- Houdini's soft-selection drag, turned into a reproducible node.

    Group is the "handle": weight 1 inside the group, falling off with distance to 0 at Radius.

    **It interpolates the parameters, not the result.** The easiest form `P' = lerp(P, M·P, w)` is wrong for rotation:
    linearly interpolating the positions before and after rotation puts the point on the **chord**, closer to the rotation centre --
    the radius gets eaten, worst on the ring at weight 0.5. Here every point computes its own matrix on the spot from `angle × w`, `translate × w`,
    `scale lerp(1, s, w)`, so the rotation radius is preserved exactly (measured max relative change
    4.8e-08; in the same example the lerp form **shrank the radius by 29.3%** around w≈0.5).

    **Metric**: `euclidean` is straight-line distance and also works on point clouds, but it **leaks across gaps** (the piece on the other
    side of a gap gets dragged too); `distance` / `steps` walk along edges and only spread over the connected part,
    which is more correct geometrically but needs topology.

    Pivot defaults to the centroid of the handle group (the intuition of dragging by hand). With a name in Falloff Attribute the
    weight is also written as a point attribute, so downstream can keep using it.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Handle: these points have weight 1; empty = all points"),
            "tx": _f(), "ty": _f(), "tz": _f(),
            "rx": _f(0, -3600, 3600, 1.0), "ry": _f(0, -3600, 3600, 1.0),
            "rz": _f(0, -3600, 3600, 1.0),
            "sx": _f(1.0), "sy": _f(1.0), "sz": _f(1.0),
            "radius": _f(1.0, 0.0, 1e6, 0.05),
            "metric": (list(_dfm.METRICS),),
            "falloff_ramp": ("STRING", {"default": "0:0  1:1"}),
            "ramp_mode": (list(_rmp.MODES),),
            "normals": (list(_dfm.SOFT_NORMAL_MODES),),
            "use_group_center": _sec("Pivot",
                                     ("BOOLEAN", {"default": True}),
                                     gate=True),
            "pivot_x": _sec("Pivot", _f(0.0)),
            "pivot_y": _sec("Pivot", _f(0.0)),
            "pivot_z": _sec("Pivot", _f(0.0)),
            "falloff_attribute": ("STRING", {"default": ""}),
            # pcg100: added against the Soft Transform docs (default = old behaviour: SRT, Rx Ry Rz, no shear)
            "xform_order": (list(ops.XFORM_ORDERS),),
            "rotate_order": (list(ops.ROTATE_ORDERS),),
            "shear_xy": _f(), "shear_xz": _f(), "shear_yz": _f(),
            "prx": _f(0, -3600, 3600, 1.0), "pry": _f(0, -3600, 3600, 1.0),
            "prz": _f(0, -3600, 3600, 1.0),
            "soft_type": (list(_dfm.SOFT_TYPES),),
            "tangent_far": _f(0.0, -89.0, 89.0, 1.0),
            "tangent_near": _f(0.0, -89.0, 89.0, 1.0),
            "kernel": (list(_dfm.KERNELS),),
            "distance_attribute": ("STRING", {"default": "dist"}),
            "apply_rolloff": ("BOOLEAN", {"default": True}),
            "preserve_normal_length": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/deform"

    def run(self, geo, group, tx, ty, tz, rx, ry, rz, sx, sy, sz,
            radius, metric, falloff_ramp, ramp_mode, normals,
            use_group_center, pivot_x, pivot_y, pivot_z, falloff_attribute,
            xform_order="srt", rotate_order="xyz", shear_xy=0.0, shear_xz=0.0, shear_yz=0.0,
            prx=0.0, pry=0.0, prz=0.0, soft_type="ramp", tangent_far=0.0, tangent_near=0.0,
            kernel="links", distance_attribute="dist", apply_rolloff=True,
            preserve_normal_length=False):
        return (_dfm.soft_transform(
            geo, group, (tx, ty, tz), (rx, ry, rz), (sx, sy, sz),
            (pivot_x, pivot_y, pivot_z), use_group_center, radius, metric,
            falloff_ramp, ramp_mode, normals, falloff_attribute,
            xform_order, rotate_order, (shear_xy, shear_xz, shear_yz), (prx, pry, prz),
            soft_type, (tangent_far, tangent_near), kernel, distance_attribute,
            apply_rolloff, preserve_normal_length),)


class PCG_Spherify:
    """
    Pushes the selected points onto a sphere: `P' = lerp(P, C + normalize(P−C)·R, Amount)`.

    Radius left at 0 = the **mean** distance from the selected points to the centre. Spherifying should not scale as a side effect,
    and the mean radius changes volume the least. The centre defaults to the centroid of the selected points.

    Amount=0 is a **bit-exact** identity; at Amount=1 all points land exactly on the sphere (measured radius
    standard deviation 3.0e-08). Its real use is together with Group: spherify just one patch, and with a soft-selection
    weight it becomes a "local bulge".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "amount": _f(1.0, -10.0, 10.0, 0.01),
            "radius": _f(0.0, 0.0, 1e6, 0.05),
            "normals": (list(_dfm.NORMAL_MODES),),
            "use_center": _sec("Center", ("BOOLEAN", {"default": False}),
                               gate=True),
            "center_x": _sec("Center", _f(0.0)),
            "center_y": _sec("Center", _f(0.0)),
            "center_z": _sec("Center", _f(0.0)),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/deform"

    def run(self, geo, group, amount, radius, normals, use_center,
            center_x, center_y, center_z):
        return (_dfm.spherify(geo, group, amount, radius,
                              (center_x, center_y, center_z), use_center,
                              normals),)


class PCG_Ends:
    """
    Open / close / unroll / roll curves. Mirrors Houdini's Ends SOP.

    `prim_closed` is a boolean flag deciding whether there is a closing edge between the last point and the first.
    A bunch of downstream nodes (Resample / Carve / Sweep / PolyExpand2D) treat open and closed curves
    completely differently, and the flag coming from upstream is often not the one you want.

    Four ops; the difference is **whether the geometry changes**:

        close    only flips the flag, **one more** closing edge, the shape changes
        open     only flips the flag, **one fewer** edge, the shape changes
        unroll   closed -> open, and the first point is attached again at the end. Same edge count,
                 **the shape does not change at all** -- the only one of the four that "only changes representation"
        roll     the inverse of unroll: open curve with coincident ends -> remove the duplicate point, then close

    `unroll` is the most used: feeding a closed loop straight into Resample, the resampler does not know where to start (a closed curve
    has no start point); after unroll it is an ordinary open curve that looks exactly the same, and you roll it back afterwards.
    `unroll -> roll` is a **bit-exact** topological identity.

    Two-point prims are not closed -- that would give two coincident edges (a zero-area degenerate face) with nan normals,
    zero area, and it **looks the same as before**, so it would get mixed in far downstream before blowing up. Skipped directly, no error.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only process these prims"),
            "op": (list(_end.OPS),),
            "tolerance": _f(0.0, 0.0, 1e6, 0.001),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, op, tolerance):
        return (_end.ends(geo, group, op, tolerance),)


class PCG_Peak:
    """
    Pushes points along point normals. Mirrors Houdini's Peak SOP.

    **"Push d along point normals" is not "offset the surface by d".** A cube's corner normal is (1,1,1)/√3; pushing d along it
    moves that corner only 0.577d along each face's normal. As a result the faces are no longer flat, the offset
    does not match the number you typed, and the cube is no longer a cube. Houdini's Peak behaves the same way.

    **Miter Corners** multiplies the displacement by `1 / (n_point · n_face)` (taking the smallest dot product among adjacent
    faces) -- that is exactly a "miter": the corner is pushed to the **intersection** of its offset adjacent faces. A cube corner
    gets √3, it is still a cube after pushing, and the edge length grows by exactly 2d (measured: edge 2 pushed by 0.5 -> volume exactly 27).

    At nearly tangent folds this factor explodes, so Max Miter caps it -- every place that does mitering
    (bevel, outlining, extrusion) needs this parameter.

    If N exists it is used as is (upstream may already have tuned the cusp angle or perturbed it); otherwise one is computed on the fly
    **but not written back**. Distance Attribute gives each point its own factor, for use with Attribute Fade /
    Attribute Noise.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "distance": _f(0.1, -1e6, 1e6, 0.01),
            "group": _group(),
            "miter_corners": ("BOOLEAN", {"default": False}),
            "max_miter": _f(8.0, 1.0, 1e4, 0.1),
            "distance_attribute": _names("attrib", "point", ""),
            "normal_attribute": _names("attrib", "point", "N"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, distance, group, miter_corners, max_miter,
            distance_attribute, normal_attribute):
        return (_pk.peak(geo, distance, group, miter_corners, max_miter,
                         distance_attribute, normal_attribute),)


class PCG_Mirror:
    """
    Mirrors about a plane. Mirrors Houdini's Mirror SOP. Three things are wrong if not done, and wrong in
    a very inconspicuous way.

    **1. Mirroring flips orientation, so face winding must be reversed.** The reflection matrix has determinant −1. Reflecting only positions
    and copying the winding makes every face normal in the mirrored half point inward -- it renders black, vanishes with backface culling,
    and volume comes out **negative** (measured +4 becomes −4). In a solid preview it is only visible from some angles.

    **2. Vector attributes must be reflected, not copied.** **Direction** quantities like N / v / up / tangent must be
    reflected after mirroring, while Cd / uv are correctly copied. No type system can tell them apart automatically, so a default list is given,
    and it can be extended.

    **3. append mode must fuse on the plane.** Without fusing, the row of points sitting on the plane is duplicated,
    and the seam is a ring of doubled boundary edges (measured 8), the topology is not closed, and every later node that requires closure
    (Scatter in Volume, Convex Decompose, volumes) errors out or computes wrong.

    Before fusing, points **lying on the plane** are projected exactly onto it: floating-point error puts points that should be at x=0
    at ±1e-8, slightly off on both sides; without projection the tolerance would have to be raised enough to drown real features. Snap Tolerance is
    normalized by the longest side of the bounding box.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "mode": (list(_mir.MODES),),
            "origin_x": _f(0.0, -1e6, 1e6, 0.01),
            "origin_y": _f(0.0, -1e6, 1e6, 0.01),
            "origin_z": _f(0.0, -1e6, 1e6, 0.01),
            "normal_x": _f(1.0, -1e6, 1e6, 0.01),
            "normal_y": _f(0.0, -1e6, 1e6, 0.01),
            "normal_z": _f(0.0, -1e6, 1e6, 0.01),
            "snap_tolerance": _f(1e-4, 0.0, 1.0, 1e-5),
            "fuse_result": ("BOOLEAN", {"default": True}),
            "original_group": _names("group", "prim", ""),
            "mirror_group": _names("group", "prim", ""),
            "vector_attributes": ("STRING", {
                "default": " ".join(_mir.VECTOR_ATTRIBS),
                "tooltip": "Three-component direction attributes to reflect when mirroring, space-separated"}),
        }, "optional": {
            # ── pcg100 addition (default = previous behaviour; see mirror in geo/mirror.py) ──
            "group": _group("Only mirror these faces; empty = all"),
            "operation": (list(_mir.OPERATIONS),),
            "orient": (list(_mir.ORIENTS),),
            "translate_x": _f(0.0), "translate_y": _f(0.0), "translate_z": _f(0.0),
            "rotate_x": _f(0.0), "rotate_y": _f(0.0), "rotate_z": _f(0.0),
            "distance": _f(0.0),
            "reverse_normals": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, mode, origin_x, origin_y, origin_z, normal_x,
            normal_y, normal_z, snap_tolerance, fuse_result, original_group,
            mirror_group, vector_attributes, group="", operation="mirror_all",
            orient="direction", translate_x=0.0, translate_y=0.0, translate_z=0.0,
            rotate_x=0.0, rotate_y=0.0, rotate_z=0.0, distance=0.0,
            reverse_normals=True):
        return (_mir.mirror(geo, mode, (origin_x, origin_y, origin_z),
                            (normal_x, normal_y, normal_z), snap_tolerance,
                            fuse_result, original_group, mirror_group,
                            tuple(str(vector_attributes).split()),
                            group, operation, orient,
                            (translate_x, translate_y, translate_z),
                            (rotate_x, rotate_y, rotate_z), distance,
                            reverse_normals),)


class PCG_ExplodedView:
    """
    Pushes fractured pieces apart for viewing. Mirrors Houdini's Exploded View SOP.

    The outputs of Voronoi Fracture / Voronoi Cluster / Convex Decompose are pieces that fit together
    seamlessly -- in other words they **look as if nothing was cut**. To confirm the cut is right, they have to be pushed apart.

    **Every piece must move rigidly.** The laziest implementation scales the whole geometry by k about the centre; the pieces do
    separate, but each piece is also scaled by k and its volume becomes k³ times -- impressive in a picture, wrong for any measurement.
    Here it is **per-piece translation**, which gives a very clean criterion: every piece's volume is unchanged **piece by piece**.

    **The centroid is area-weighted, not a point average.** A point average is biased by mesh density -- a Voronoi piece's
    cut face is one whole n-gon (few points), while the shell side inherits the original model's subdivision (many points), so the averaged
    "centroid" leans noticeably toward the shell. Face centroids × area weighting does not have this problem, and comes for free.

    Mode: uniform moves every piece the same distance (for inspecting thin-shell layering), proportional moves each in proportion to its distance from the centre
    (for an explosion feel). Shrink also shrinks each piece slightly about **its own centroid**, leaving gaps between cut faces --
    this is an obvious deformation with its own toggle; the default 1.0 leaves it alone.

    Pieces come from a prim attribute (name / piece / cluster, which the upstream nodes all write) or from connected components.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "mode": (list(_exp.MODES),),
            "distance": _f(0.25, -1e6, 1e6, 0.01),
            "shrink": _f(1.0, 0.0, 1.0, 0.01),
            "relative_to_size": ("BOOLEAN", {"default": True}),
            "piece_from": (list(_exp.PIECE_FROM),),
            "piece_attribute": _names("attrib", "prim", "name"),
            "center": (list(_exp.CENTERS),),
            "center_x": _sec("Center Point", _f(0.0, -1e6, 1e6, 0.01)),
            "center_y": _sec("Center Point", _f(0.0, -1e6, 1e6, 0.01)),
            "center_z": _sec("Center Point", _f(0.0, -1e6, 1e6, 0.01)),
            "up_bias": _f(0.0, -1e6, 1e6, 0.01),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, mode, distance, shrink, relative_to_size, piece_from,
            piece_attribute, center, center_x, center_y, center_z, up_bias):
        return (_exp.explode(geo, mode, distance, shrink, piece_from,
                             piece_attribute, center,
                             (center_x, center_y, center_z),
                             relative_to_size, up_bias),)


# ============================================================ image -> geometry
class PCG_AttribFromMap:
    """
    Mirrors Houdini's Attribute from Map. Samples an image by uv and writes it as an attribute.

    **This is the main entry of the "AI -> PCG" half.** Up to the previous batch the chain only went one way: geometry ->
    Render Pass -> Control Image -> diffusion model. For the image a sampler produces to get back onto geometry,
    there used to be only Heightfield from Image, and it could only make heightfields.

    ━━ uv lives on vertices; writing it to points is **ambiguous**
    At a uv seam one point is shared by two uv islands, so it has two uvs. Hence:

        class = vertex   uses that vertex's uv directly, zero ambiguity. **Recommended**
        class = point    takes the uv of the point's first incident vertex
        class = prim     takes the average uv of all the face's vertices

    point takes "the first" rather than the average because averaging u=0 and u=1 on a seam gives 0.5 --
    sampling the middle of the texture, wrong and without an error. The node counts how many points lie on seams and puts it in
    the info output, so the "dirty ring along the seam" symptom at least has a number to check.

    ━━ Remember to turn on srgb_to_linear when using an image as **numeric values**
    A diffusion model's output is meant for the screen; an encoded 0.5 is physically only 0.214. Passing it on as colour
    is fine, but used as displacement height / density / pscale it is off by more than 2x.

    ━━ Bilinear is **exact** inside the image
    Bilinear interpolation reconstructs a+bu+cv+d·uv without error; measured interior error 5e-8 (the precision of the float32 uv attribute
    itself). Half a pixel at the border is the clamp zone and gets flattened there -- that is a boundary condition, not
    an interpolation error.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "class": (list(_fmp.CLASSES),),
            "name": _names("attrib", "point", "Cd"),
            "channels": ("STRING", {"default": "", "tooltip":
                                    "empty = all channels; \"0\" / \"0,2\" picks the given channels"}),
            "decode": (list(_fmp.DECODES), {"tooltip":
                       "choose srgb_to_linear when using the image as numeric values (displacement/density)"}),
            "filter": (list(_fmp.FILTERS),),
            "border": (list(_fmp.BORDERS),),
            "scale": _f(1.0, -1e6, 1e6, 0.01),
            "offset": _f(0.0, -1e6, 1e6, 0.01),
            "blend": _f(1.0, 0.0, 1.0, 0.01),
            "uv_attrib": _sec("UV", _names("attrib", "vertex", "uv")),
            "uv_from": _sec("UV", (list(_fmp.UV_SOURCES),)),
            "uv_scale_u": _sec("UV", _f(1.0, -1e4, 1e4, 0.1)),
            "uv_scale_v": _sec("UV", _f(1.0, -1e4, 1e4, 0.1)),
            "uv_offset_u": _sec("UV", _f(0.0, -1e4, 1e4, 0.01)),
            "uv_offset_v": _sec("UV", _f(0.0, -1e4, 1e4, 0.01)),
            "group": _group(),
        }}
    RETURN_TYPES = (GEO, "STRING"); RETURN_NAMES = ("geo", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, cop, layer, **kw):
        cls = kw.pop("class")
        g, info = _fmp.attribute_from_map(geo, cop, layer=layer, cls=cls, **kw)
        txt = (f"{info.get('count', 0)} elements, {info.get('components', 0)} components"
               + (f", {info['seam_points']} points on uv seams"
                  if info.get("seam_points") else ""))
        return (g, txt)


class PCG_AttribFromCamera:
    """
    Projects an image onto geometry **through a camera** -- an attribute + two groups.

    **The control-flow hub of the AI -> procedural direction.** The Attribute from Map family is all in UV space,
    so turning an AI-made mask into a point group used to take
    `UV Backproject -> Attribute from Map -> threshold grouping`, three nodes, and it required the geometry
    to **already have UVs**. This node needs a single wire and does not go through UV space -- freshly imported AI
    meshes usually have no UVs.

        Render Pass -> diffusion model -> Attrib from Camera -> mask_group
        → Blast / Voronoi Fracture / PolyExtrude / Scatter

    The AI only decides "where"; everything after it is deterministic procedural operators.

    ━━ Difference from "using the camera as a UV projection": **visibility**
    Planar/camera projection knows nothing about occlusion; paint the front of a sphere red and the back gets painted red too, discovered only after turning around.
    Here it is a four-level ladder:

        all       no test (for when you want it to go through)
        frustum   inside the frame + in front of the camera
        front     plus facing
        full      plus occlusion (default)

    The occlusion criterion is **element id or depth**: rasterization gives the visible triangle id per pixel for free;
    if the triangle at the pixel is exactly the one containing the point, it is on the visible surface, no bias needed; only on a mismatch
    does it fall back to depth comparison. Measured (convex sphere, 256² frame, guard=0): depth-only at facing_min=0.1
    still misjudges 4 front-facing points, element+depth 0.

    ━━ facing_min defaults to 0.1, not 0
    Lowering it further, the remaining misjudgements come from "the point's pixel was never covered" -- a polygonal sphere's silhouette is an inscribed
    polygon, smaller than the true sphere, so the outermost ring of points falls outside the rasterized area anyway. And samples at grazing angles
    should not be trusted anyway.

    ━━ depth_bias is a fraction **relative to the bounding-sphere radius**
    Unlike UV Backproject's world units (that one defaults to 0.02, tuned for objects normalized to 1).
    Imported AI meshes have no predictable scale at all; the same absolute value on models of radius 0.001 and 1000
    would judge everything visible on one and nothing visible on the other.

    ━━ The two groups are the point
    `visible_group` = the part this camera can see (multi-camera coverage check).
    `mask_group` = the part whose sampled value passes the threshold; **wherever the AI paints, this moves**. The threshold tests the value written to the
    attribute (after scale / offset), so the number you see in the panel is the one being tested.

    ━━ missing: what to do with elements that cannot be seen
    `keep` keeps the original value (what multi-camera accumulation needs: the second camera should not erase what the first painted),
    `zero` writes 0, `value` writes the given value.

    ━━ Occlusion is always computed with **the whole geometry**, not limited by group
    group limits "what gets written", not "who blocks whom". Something physically blocking you does not vanish because you did not
    select it.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cam": (CAM,),
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "class": (list(_cpj.CLASSES),),
            "name": _names("attrib", "point", "Cd"),
            "channels": ("STRING", {"default": "", "tooltip":
                                    "empty = all channels; \"0\" / \"0,2\" picks the given channels"}),
            "decode": (list(_fmp.DECODES), {"tooltip":
                       "choose srgb_to_linear when using the image as numeric values (displacement/density)"}),
            "filter": (list(_fmp.FILTERS),),
            "border": (list(_fmp.BORDERS),),
            "scale": _f(1.0, -1e6, 1e6, 0.01),
            "offset": _f(0.0, -1e6, 1e6, 0.01),
            "blend": _f(1.0, 0.0, 1.0, 0.01),

            "visibility": _sec("Visibility", (list(_cpj.VISIBILITY),)),
            "occlusion": _sec("Visibility", (list(_cpj.OCCLUSION),)),
            "facing_min": _sec("Visibility",
                               _f(_cpj.FACING_MIN, -1.0, 1.0, 0.01)),
            "depth_bias": _sec("Visibility",
                               _f(_cpj.DEPTH_BIAS, 0.0, 10.0, 0.001)),
            "silhouette_guard": _sec("Visibility", _i(1, 0, 64)),
            "border_margin": _sec("Visibility", _f(0.0, 0.0, 0.49, 0.01)),
            "normal_attrib": _sec("Visibility",
                                  _names("attrib", "point", "N")),

            "missing": _sec("Missing", (list(_cpj.MISSING),)),
            "missing_value": _sec("Missing", _f(0.0, -1e6, 1e6, 0.01)),

            "visible_group": _sec("Groups", ("STRING", {"default": ""})),
            "mask_group": _sec("Groups", ("STRING", {"default": ""})),
            "threshold": _sec("Groups", _f(0.5, -1e6, 1e6, 0.01)),
            "threshold_channel": _sec("Groups", _i(0, 0, 63)),
            "uv_name": _sec("Groups", ("STRING", {"default": "", "tooltip":
                            "if non-empty, the projected screen uv is also written as an attribute"})),
            "group": _group(),
        }}
    RETURN_TYPES = (GEO, "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("geo", "visible", "coverage", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, cam, cop, layer, **kw):
        cls = kw.pop("class")
        g, info = _cpj.project_attribute(geo, cam, cop, layer=layer, cls=cls,
                                         **kw)
        txt = (f"{info['visible']}/{info['total']} visible "
               f"({info.get('coverage', 0.0) * 100:.1f}%)  "
               f"out of frame {info.get('out_frame', 0)}  "
               f"back-facing {info.get('back_facing', 0)}  "
               f"occluded {info.get('occluded', 0)}")
        return (g, int(info["visible"]), float(info.get("coverage", 0.0)), txt)


class PCG_DisplaceFromMap:
    """
    Samples a scalar by uv and pushes points along normals. The standard use of heightmaps / displacement maps.

    midpoint is the value that "does not move": displacement = (sampled value − midpoint) × amount. For a heightmap whose lowest point is 0,
    use 0; for a displacement map where "0.5 is flat", use 0.5.

    **The normals are stale after pushing** -- this node does not recompute N (that needs the new adjacency, which is
    Facet's job). For correct shading / further displacement, add a Facet downstream to recompute normals.

    Same as Attribute from Map: values are used here, so remember to turn on srgb_to_linear.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "channel": _i(0, 0, 63),
            "amount": _f(0.1, -1e6, 1e6, 0.01),
            "midpoint": _f(0.0, -1e6, 1e6, 0.01),
            "decode": (list(_fmp.DECODES),),
            "direction": (["normal", "vector"],),
            "dir_x": _sec("Direction", _f(0.0, -1e6, 1e6, 0.1)),
            "dir_y": _sec("Direction", _f(1.0, -1e6, 1e6, 0.1)),
            "dir_z": _sec("Direction", _f(0.0, -1e6, 1e6, 0.1)),
            "normal_attrib": _sec("Direction",
                                  _names("attrib", "point", "N")),
            "filter": (list(_fmp.FILTERS),),
            "border": (list(_fmp.BORDERS),),
            "uv_attrib": _sec("UV", _names("attrib", "vertex", "uv")),
            "uv_from": _sec("UV", (list(_fmp.UV_SOURCES),)),
            "uv_scale_u": _sec("UV", _f(1.0, -1e4, 1e4, 0.1)),
            "uv_scale_v": _sec("UV", _f(1.0, -1e4, 1e4, 0.1)),
            "uv_offset_u": _sec("UV", _f(0.0, -1e4, 1e4, 0.01)),
            "uv_offset_v": _sec("UV", _f(0.0, -1e4, 1e4, 0.01)),
            "group": _group(),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/deform"

    def run(self, geo, cop, layer, **kw):
        return (_fmp.displace_from_map(geo, cop, layer=layer, **kw),)


class PCG_ScatterFromMap:
    """
    Scatters points using an image as a density field. "Plant grass / place rocks by an AI-made mask" is this node.

    ━━ Why not Attribute from Map -> Scatter's Density Attribute
    Both nodes for that route exist and it can be built in one line, but the density precision is capped by the **mesh resolution**:
    Scatter's density attribute averages the three vertices of a triangle, so a 2×2 grid facing a 1024²
    mask leaves only 4 numbers for the whole image.

    This uses **rejection sampling**: first scatter oversample times the points uniformly, each point looks up the image at **its own uv**,
    and is kept with probability density/max. Density precision is limited only by the image resolution, regardless of how fine
    the mesh is. The cost is an inexact point count -- hence several rounds, scattering more at the previous round's acceptance rate when short.

    ━━ The probability upper bound is **the maximum of the whole image**
    If the image has an isolated bright spot, the acceptance rate everywhere else is pushed down by it, showing up as needing several rounds.
    This is the inherent cost of rejection sampling: put a COP Blur first or compress the highlights.

    density_floor gives a minimum, so fully black areas do not end up with no points at all.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "channel": _i(0, 0, 63),
            "count": _i(1000, 0, 1 << 22),
            "density_scale": _f(1.0, 0.0, 1e4, 0.01),
            "density_floor": _f(0.0, 0.0, 1.0, 0.01),
            "invert": ("BOOLEAN", {"default": False}),
            "decode": (list(_fmp.DECODES),),
            "rand_seed": _i(0, 0, 1 << 30),
            "oversample": _sec("Sampling", _f(4.0, 1.0, 64.0, 0.5)),
            "max_rounds": _sec("Sampling", _i(6, 1, 32)),
            "filter": _sec("Sampling", (list(_fmp.FILTERS),)),
            "border": _sec("Sampling", (list(_fmp.BORDERS),)),
            "out_density": _sec("Sampling",
                                _names("attrib", "point", "density")),
            "uv_attrib": _sec("UV", _names("attrib", "vertex", "uv")),
            "uv_scale_u": _sec("UV", _f(1.0, -1e4, 1e4, 0.1)),
            "uv_scale_v": _sec("UV", _f(1.0, -1e4, 1e4, 0.1)),
            "uv_offset_u": _sec("UV", _f(0.0, -1e4, 1e4, 0.01)),
            "uv_offset_v": _sec("UV", _f(0.0, -1e4, 1e4, 0.01)),
            "group": _group(),
            # ── pcg100 addition (Houdini HeightField Scatter's Scatter Method / Variability /
            #    orientation / Max Points / Quantization / Tag Name), default = old behaviour
            "scatter_method": (list(_fmp.SFM_METHODS),),
            "density": _f(1.0, 0.0, 1e9, 0.1),
            "coverage": _f(0.5, 0.0, 100.0, 0.01),
            "outer_radius": _f(1.0, 0.0, 1e6, 0.01),
            "variability": (list(_fmp.SFM_VARIABILITY),),
            "range_min": _f(0.5, 0.0, 1e6, 0.01),
            "range_max": _f(1.5, 0.0, 1e6, 0.01),
            "spread": _f(0.25, 0.0, 1e6, 0.01),
            "exact_scale": _f(1.0, 0.0, 1e6, 0.01),
            "randomize_orients": ("BOOLEAN", {"default": False}),
            "match_normals": ("BOOLEAN", {"default": True}),
            "randomize_up": _f(0.0, 0.0, 180.0, 1.0),
            "randomize_yaw": _f(180.0, 0.0, 180.0, 1.0),
            "max_points": _i(0, 0, 1 << 26),
            "quantization": _f(0.0, 0.0, 1e6, 0.01),
            "tag_name": ("STRING", {"default": ""}),
        }}
    RETURN_TYPES = (GEO, "INT"); RETURN_NAMES = ("points", "count")
    FUNCTION = "run"; CATEGORY = CAT + "/scatter"

    def run(self, geo, cop, layer, rand_seed, **kw):
        g = _fmp.scatter_from_map(geo, cop, layer=layer, seed=rand_seed, **kw)
        return (g, int(g.npoints))


class PCG_FromJSON:
    """
    Turns a piece of **JSON text** into geometry -- points / boxes / curves, with attributes and groups.

    **AI plans, procedural executes.** Up to the previous batch all AI could give this plugin was pixels
    (control images, textures) and shapes (Import Mesh); but what LLMs / VLMs are best at outputting
    is really **structure** -- layouts, bboxes, labels, classes. This node is the entry to that road:

        LLM / VLM (outputs JSON) -> From JSON -> points / faces / lines + attributes + groups
        -> Copy to Points / PolyExtrude / group by name / Switch routing

    ━━ Parsing is tolerant, but what was repaired is written to info
    What models spit out is almost never clean JSON: wrapped in a ```json fence, a "Here is..." sentence in front,
    a trailing comma at the end. Four steps: parse directly -> strip the fence -> extract the first balanced
    `[...]`/`{...}` -> strip trailing commas. **Which step did the repair is written to info** -- silent repairs are
    the hardest kind to debug: it runs today, and tomorrow the model changes format and you think your own graph broke.

    ━━ Three forms
        points  one point per record (`pos` / `P` / `position` are all recognised)
        boxes   one rectangle (bbox, 4 numbers) or box (6 numbers) per record.
                VLM detection boxes, LLM room layouts: box -> face -> PolyExtrude gives walls
        curves  one polyline per record (`points` / `path`): paths / roads / outlines

    ━━ Key names are **aligned automatically**
    `pos` / `position` / `translate` all land on `P`, `color` / `Cd` land on `Cd`
    (`"#ff8800"` is recognised), `label` / `type` / `tag` land on `name`. This is not a nicety, it is
    **necessary**: models use different key names every time, and without alignment the graph would need changing with every prompt change.
    Keys that do not match come in as is: number -> float attribute, fixed-length array -> vector, string -> string.

    ━━ group_by is the key
    Give an attribute name (usually `name`) and one group is created per value -- **the classes the AI assigned directly become
    usable groups**, ready for Blast / Switch / Copy to Points. It pairs with the previous batch's Attrib from
    Camera mask_group: that one handles "where", this one handles "what, how many, what it is called".

    ━━ Coordinates (same rules for all three forms, see structured._to_world)
    2D coordinates: with `normalized` on, 0..1 maps onto a patch of size `size` (`plane` decides which
    plane it lands on, default the xz ground); off, they are world units on that plane; both are offset by `center`.
    `flip_v` is for image space (where y points down). 3D coordinates are always world coordinates + `center`.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "json_text": ("STRING", {"multiline": True, "default":
                          '[{"name": "a", "pos": [0.25, 0.25]},\n'
                          ' {"name": "b", "pos": [0.75, 0.6]}]'}),
            "mode": (list(_stx.MODES),),
            "path": ("STRING", {"default": "auto", "tooltip":
                     "when the top level is an object, points at the record list, e.g. items; auto finds it automatically"}),
            "plane": (list(_stx.PLANES),),
            "size_u": _f(10.0, -1e6, 1e6, 0.1),
            "size_v": _f(10.0, -1e6, 1e6, 0.1),
            "center_x": _f(), "center_y": _f(), "center_z": _f(),
            "normalized": ("BOOLEAN", {"default": True}),
            "flip_v": ("BOOLEAN", {"default": False}),
            "height": _f(0.0, -1e6, 1e6, 0.1),
            "group_by": ("STRING", {"default": "name"}),
            "color_hex": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (GEO, "INT", "STRING")
    RETURN_NAMES = ("geo", "records", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/convert"

    def run(self, json_text, mode, path, plane, size_u, size_v, center_x,
            center_y, center_z, normalized, flip_v, height, group_by,
            color_hex):
        g, info = _stx.from_json(
            json_text, mode=mode, path=path, plane=plane,
            size=(size_u, size_v), center=(center_x, center_y, center_z),
            flip_v=flip_v, normalized=normalized, height=height,
            group_by=group_by, color_hex=color_hex)
        txt = (f"{info['records']} records -> {info['points']} points / "
               f"{info['prims']} prims  parse: {info['parse']}"
               + (f"  attributes {','.join(info['attribs'])}"
                  if info["attribs"] else "")
               + (f"  groups {info['groups']}" if info["groups"] else "")
               + (f"  filled {info['filled']} missing values" if info["filled"] else ""))
        return (g, int(info["records"]), txt)


class PCG_GeoToJSON:
    """
    Geometry -> JSON. **For showing the model the current layout.**

    The premise of "letting the AI plan" is that it can see the current state: export the attributes of scattered points / pieces / rooms as JSON
    and feed it into the prompt, and only then can the model give a next step that matches up. It pairs with From JSON; both sides use
    the same key-name convention, so `geometry -> JSON -> model edits it -> From JSON` is a closed loop.

    **Only attributes are exported, not topology.** This is for the model to read; ten thousand vertex indices do not help it
    at all and would only eat up the context. For complete geometry use Export Mesh / File Cache.

    `limit` truncates to the first N records and states `truncated` and the total in the output -- truncation has to be said
    out loud, otherwise the model thinks that is everything and then gives a layout that does not match up.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "class": (["point", "prim", "detail"],),
            "attribs": ("STRING", {"default": "", "tooltip":
                        "empty = all; separated by spaces or commas"}),
            "limit": _i(0, 0, 1 << 20),
            "precision": _i(6, 0, 15),
            "indent": _i(0, 0, 8),
        }}
    RETURN_TYPES = ("STRING", "INT"); RETURN_NAMES = ("json", "count")
    FUNCTION = "run"; CATEGORY = CAT + "/convert"

    def run(self, geo, attribs, limit, precision, indent, **kw):
        cls = kw.pop("class")
        txt = _stx.dumps(geo, cls=cls, attribs=attribs, limit=limit,
                         precision=precision, indent=indent)
        return (txt, int(geo.count(cls)))


class PCG_Trace:
    """
    Mirrors Houdini's Trace. Image contours -> **curve geometry**.

    This is the only step on the "image -> geometry" road that brings **topology** back: Attribute from Map
    can only give values, while Trace produces polylines that can be extruded, swept and used as cutting curves. AI-made line art,
    silhouettes and masks only really become editable assets at this step.

    The algorithm is Marching Squares. Both places everyone gets wrong are handled here:

    ━━ **Saddle points are ambiguous**. When two diagonal corners are above the threshold, the two segments can connect or stay apart --
       picking wrong is not "slightly off", it is a topology error (things that should be apart stick together, or one loop splits in two).
       Decided by the cell centre value (average of the four corners), which is exact for a bilinear field.

    ━━ **Orientation must be consistent**. The convention is "the side above the threshold is on the left", so outer contours run counter-clockwise
       (positive signed area) and holes clockwise (negative). Downstream PolyFill / PolyExtrude depend entirely on
       this; with random orientation extrusions come out inside-out. Measured: the two loops of an annulus are +πR² / −πr²,
       1e-5 off the analytic values.

    simplify is in **pixels**, not world units -- it means "how far it may deviate from the original image",
    and that intent should not change with the output size. RDP on a closed loop first takes the farthest pair of points as anchors, otherwise
    the area near the start point could never be simplified, and a perfect circle would keep a spike.

    Outputs prim attributes perimeter / area (signed) and the point attribute uv (traced points still know
    where on the image they came from, so Attribute from Map can be added to pick up colours).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "channel": _i(0, 0, 63),
            "threshold": _f(0.5, -1e6, 1e6, 0.01),
            "invert": ("BOOLEAN", {"default": False}),
            "simplify": _f(0.5, 0.0, 256.0, 0.05),
            "min_points": _i(3, 2, 1 << 20),
            "min_length": _f(0.0, 0.0, 1e6, 0.01),
            "close_open": ("BOOLEAN", {"default": False}),
            "plane": (list(_trc.PLANES),),
            "size": _f(2.0, 1e-4, 1e6, 0.1),
            "keep_aspect": ("BOOLEAN", {"default": True}),
            "height": _sec("Placement", _f(0.0, -1e6, 1e6, 0.1)),
            "center_x": _sec("Placement", _f(0.0, -1e6, 1e6, 0.1)),
            "center_y": _sec("Placement", _f(0.0, -1e6, 1e6, 0.1)),
            "center_z": _sec("Placement", _f(0.0, -1e6, 1e6, 0.1)),
            "add_uv": _sec("Placement", ("BOOLEAN", {"default": True})),
            "uv_attrib": _sec("Placement", _names("attrib", "point", "uv")),
            # ── pcg100 s7 addition (default = old behaviour)
            "channel_mode": (list(_trc.CHANNEL_MODES),),
            "boundary": (list(_trc.BOUNDARIES),),
            "boundary_value": _f(0.0, -1e6, 1e6, 0.01),
            "resample": ("BOOLEAN", {"default": False}),
            "step_size": _f(0.1, 1e-6, 1e6, 0.01),
            "rotate_x": _f(0.0, -360.0, 360.0, 1.0),
            "rotate_y": _f(0.0, -360.0, 360.0, 1.0),
            "rotate_z": _f(0.0, -360.0, 360.0, 1.0),
            "scale_x": _f(1.0, -1e6, 1e6, 0.01),
            "scale_y": _f(1.0, -1e6, 1e6, 0.01),
            "scale_z": _f(1.0, -1e6, 1e6, 0.01),
        }}
    RETURN_TYPES = (GEO, "INT"); RETURN_NAMES = ("curves", "count")
    FUNCTION = "run"; CATEGORY = CAT + "/convert"

    def run(self, cop, rotate_x=0.0, rotate_y=0.0, rotate_z=0.0, scale_x=1.0,
            scale_y=1.0, scale_z=1.0, **kw):
        g = _trc.trace(cop, rotate=(rotate_x, rotate_y, rotate_z),
                       scale=(scale_x, scale_y, scale_z), **kw)
        return (g, int(g.nprims))


# ============================================================ camera / back-projection
class PCG_Camera:
    """
    A camera shared by Render Pass and UV Backproject.

    **Why it is its own node.** Back-projection requires the camera it projects back through to be **exactly the same** as the camera
    that rendered the image. If the two nodes each had their own parameters, changing one and forgetting the other gives
    a texture that is offset as a whole -- and the offset is smooth, looking like "the AI drew it crooked", so it is very hard
    to suspect the camera. As a single wire it cannot get out of sync.

    Multiple views are multiple Camera nodes (or one Camera + different azim), each with a
    Render -> diffusion -> Backproject branch, chained through the accumulator.

    With mode=frame the distance / orthographic size is set automatically from the input geometry's **bounding sphere**. This mode needs geo wired.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "projection": (list(_rnd.PROJECTIONS),),
            "mode": (["frame", "orbit", "look_at"],),
            "resolution_x": _i(512, 8, _cop.MAX_RES),
            "resolution_y": _i(512, 8, _cop.MAX_RES),
            "fov": _f(45.0, 1.0, 179.0, 1.0),
            "ortho_size": _f(2.0, 1e-4, 1e6, 0.1),
            "elev": _f(25.0, -89.9, 89.9, 1.0),
            "azim": _f(35.0, -3600.0, 3600.0, 1.0),
            "distance": _f(5.0, 1e-4, 1e6, 0.1),
            "margin": _f(1.15, 0.5, 10.0, 0.01),
            "target_x": _sec("Look At", _f(0.0, -1e6, 1e6, 0.1)),
            "target_y": _sec("Look At", _f(0.0, -1e6, 1e6, 0.1)),
            "target_z": _sec("Look At", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_x": _sec("Look At", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_y": _sec("Look At", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_z": _sec("Look At", _f(5.0, -1e6, 1e6, 0.1)),
            "up_x": _sec("Look At", _f(0.0, -1.0, 1.0, 0.1)),
            "up_y": _sec("Look At", _f(1.0, -1.0, 1.0, 0.1)),
            "up_z": _sec("Look At", _f(0.0, -1.0, 1.0, 0.1)),
            "near": _sec("Clipping", _f(0.01, 1e-6, 1e6, 0.01)),
            "far": _sec("Clipping", _f(0.0, 0.0, 1e6, 0.1)),
        }, "optional": {"geo": (GEO,)}}
    RETURN_TYPES = (CAM, "STRING"); RETURN_NAMES = ("cam", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, projection, mode, resolution_x, resolution_y, fov,
            ortho_size, elev, azim, distance, margin, target_x, target_y,
            target_z, eye_x, eye_y, eye_z, up_x, up_y, up_z, near, far,
            geo=None):
        cam = _rnd.camera(
            geo, projection=projection, eye=(eye_x, eye_y, eye_z),
            target=(target_x, target_y, target_z), up=(up_x, up_y, up_z),
            fov=fov, ortho_size=ortho_size, xres=resolution_x,
            yres=resolution_y, near=near, far=far, orbit=(mode == "orbit"),
            elev=elev, azim=azim, distance=distance,
            frame_geometry=(mode == "frame"), margin=margin)
        e, t = cam["eye"], cam["target"]
        info = (f"{cam['projection']} {cam['xres']}x{cam['yres']} "
                f"eye=({e[0]:.3f},{e[1]:.3f},{e[2]:.3f}) "
                f"target=({t[0]:.3f},{t[1]:.3f},{t[2]:.3f}) "
                f"dist={cam['distance']:.3f} r={cam['radius']:.3f}")
        return (cam, info)


class PCG_TextureRender:
    """
    Renders a uv texture to the screen. The **forward** half of the loop.

    It has two uses: one is checking right away whether a back-projected texture renders correctly (without exporting
    to an engine to look); two, it is the only honest criterion for back-projection -- known texture -> render -> back-project ->
    should recover the original texture. The two sides take completely different code paths (this side screen rasterization + sampling by uv,
    that side uv rasterization + sampling by screen), so the round trip tests something real, not the same
    bug cancelling itself out at both ends.

    Measured round-trip error (6 views, 2-pixel guard): cube max **0**, planar grid 5e-7.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cam": (CAM,),
            "texture": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "filter": (list(_fmp.FILTERS),),
            "border": (list(_fmp.BORDERS),),
            "background": _f(0.0, -1e6, 1e6, 0.01),
            "uv_attrib": _names("attrib", "vertex", "uv"),
            "group": _group(),
            "device": _dev("numpy"),
        }}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, geo, cam, texture, layer, filter, border, background,
            uv_attrib, group, device):
        return (_bpj.project_texture(
            geo, cam, texture, group=group, uv_attrib=uv_attrib, layer=layer,
            border=border, filter=filter, background=background,
            device=device),)


class PCG_UVBackproject:
    """
    **Projects a screen image back into uv space**, weighted by visibility + facing. The step that closes the loop.

    Before this the whole chain was one-way: geometry -> Render Pass -> Control Image -> diffusion model,
    and then the image just stayed there -- it is laid out by **screen pixels**, while an asset needs a texture laid out
    by **uv**. This node does that conversion.

    ━━ Multiple views are chained through an **accumulator**
    The output is an accumulator (`Csum` / `Wsum` / `views`), not a texture. The second view takes the first one's
    accumulator and adds its own contribution; finally a `UV Resolve` produces the texture. If merged into one
    "output the texture directly" node, the second view could not know how much weight the first used on each texel,
    and overlaps could only be hard-overwritten -- which is a visible seam.

    ━━ Visibility: **triangle id or depth**
    The bias of a pure depth criterion fails both ways: too small gives self-occlusion (patches of black spots on the texture, the same
    disease as shadow acne), too large lets occluded areas leak in. uv rasterization already knows which triangle each texel belongs to,
    and screen rasterization knows which one is visible at each pixel; if they match it counts as visible directly, without looking at depth.

    Measured (sphere + blocker, ground-truth occlusion computed analytically): at bias 0.001 pure depth misjudges 39.5% of visible
    texels, with the triangle criterion added it drops to 5.5%; at bias 0.02 both are 0. Triangles alone do not work either
    -- 15.2% misjudged, because one pixel can hold several texels.

    `depth_bias` is in **fractions of the bounding-sphere radius**, not world units, so changing scale needs no retuning.

    ━━ Silhouette guard
    The ring of pixels on the silhouette is partially covered, with background mixed into the colour; AI-made images are also least
    trustworthy at object edges. Shrinking inward by 1-2 pixels: the cube's round-trip bad points drop from 5.01% to 0.08% / **0**,
    at the cost of single-view coverage 1.000 -> 0.969 -> 0.954. With multiple views this cost is basically not paid.

    ━━ Blending in **linear** space
    Encoded values 0.2 and 0.8, half each: averaging then decoding gives 0.2140, decoding then averaging gives 0.3185
    -- 1.49x apart, and only biased in the overlap band, which looks exactly like a seam. So decoding is the default.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cam": (CAM,),
            "cop": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "resolution_x": _i(1024, 8, _cop.MAX_RES),
            "resolution_y": _i(1024, 8, _cop.MAX_RES),
            "decode": (list(_fmp.DECODES), {"tooltip":
                       "AI-made images are sRGB-encoded and must be decoded before blending"}),
            "facing_power": _f(2.0, 0.0, 16.0, 0.1),
            "facing_min": _f(0.2, 0.0, 1.0, 0.01),
            "border_fade": _f(0.05, 0.0, 0.5, 0.01),
            "visibility": (list(_bpj.VISIBILITY),),
            "depth_bias": _f(0.02, 0.0, 10.0, 0.001),
            "silhouette_guard": _i(1, 0, 64),
            "weight_scale": _sec("Advanced", _f(1.0, 0.0, 1e4, 0.01)),
            "conservative": _sec("Advanced", _f(0.5, 0.0, 4.0, 0.1)),
            "filter": _sec("Advanced", (list(_fmp.FILTERS),)),
            "uv_attrib": _sec("Advanced",
                              _names("attrib", "vertex", "uv")),
            "normal_attrib": _sec("Advanced",
                                  _names("attrib", "point", "N")),
            "group": _group(),
        }, "optional": {"accum": (COP,)}}
    RETURN_TYPES = (COP, "FLOAT", "STRING")
    RETURN_NAMES = ("accum", "coverage", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, geo, cam, cop, layer, resolution_x, resolution_y,
            accum=None, **kw):
        a = _bpj.backproject(geo, cam, cop, accum=accum, xres=resolution_x,
                             yres=resolution_y, layer=layer, **kw)
        cv = _bpj.coverage(a)
        v = np.asarray(a.get(_bpj.COUNT_LAYER))
        info = (f"coverage {cv*100:.2f}%  seen by at most {int(v.max())} views"
                f"  texture {resolution_x}x{resolution_y}")
        return (a, float(cv), info)


class PCG_UVResolve:
    """
    Accumulator -> texture. Divide by weight -> dilate (gutter) -> fill holes.

    ━━ Dilation and hole filling are two different things
    Dilation writes a few extra rings **outside** the uv islands: without it bilinear sampling picks up the background colour at island edges,
    more visibly at low mips. 4 texels by default.

    Hole filling handles places **no view saw** (back faces, fully occluded areas, large empty areas between islands).
    It uses push-pull: the "weighted image" is downsampled level by level into a pyramid and upsampled back level by level; places with weight
    keep their original values, places without are filled from the level above -- O(n), fills holes of any size in one go, and smoothly.
    Iterative dilation needs as many rounds as the hole radius, and on large holes it is slow and leaves concentric rings.

    The output `mask` layer marks texels that were **really seen**; those from dilation and hole filling do not count --
    look at it to know "where another view is still needed". The `views` layer is how many views saw each texel,
    for diagnosing "is only one view holding this patch up".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "accum": (COP,),
            "layer": ("STRING", {"default": "C"}),
            "encode": (["none", "srgb", "linear"], {"tooltip":
                       "accumulation is done in linear space; choose srgb to send it back to ComfyUI for viewing as an image"}),
            "dilate": _i(4, 0, 256),
            "fill_holes": ("BOOLEAN", {"default": True}),
            "background": _f(0.5, -1e6, 1e6, 0.01),
            "device": _dev("numpy"),
        }}
    RETURN_TYPES = (COP, "FLOAT"); RETURN_NAMES = ("texture", "coverage")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, accum, layer, encode, dilate, fill_holes, background,
            device):
        t = _bpj.resolve(accum, layer=layer, encode=encode, dilate=dilate,
                         fill_holes=fill_holes, background=background,
                         device=device)
        return (t, float(_bpj.coverage(accum)))


# ============================================================ timeline
class PCG_CameraPath:
    """
    A camera path -> a list of cameras. The entry on the video side.

    **With loop=True the last frame does not repeat the first**: azim sweeping 0 to 360 over 24 frames, frame 23
    stops at 345° rather than 360°. Otherwise one frame in the loop is a duplicate, and playback "hitches"
    -- a one-frame hitch is visible to the eye, but almost nobody would suspect the sampling interval.
    One-off dolly moves need a closed interval; turn loop off.

    The output is a list, wired into Render Sequence. To use a single frame, wire in Sequence
    Pick.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "frames": _i(24, 1, 1 << 14),
            "mode": (list(_seq.PATHS),),
            "projection": (list(_rnd.PROJECTIONS),),
            "resolution_x": _i(512, 8, _cop.MAX_RES),
            "resolution_y": _i(512, 8, _cop.MAX_RES),
            "fov": _f(45.0, 1.0, 179.0, 1.0),
            "ortho_size": _f(2.0, 1e-4, 1e6, 0.1),
            "frame_geometry": ("BOOLEAN", {"default": True}),
            "loop": ("BOOLEAN", {"default": True}),
            "elev": _sec("Orbit", _f(25.0, -89.9, 89.9, 1.0)),
            "elev_end": _sec("Orbit", _f(25.0, -89.9, 89.9, 1.0)),
            "azim": _sec("Orbit", _f(0.0, -3600.0, 3600.0, 1.0)),
            "azim_end": _sec("Orbit", _f(360.0, -3600.0, 3600.0, 1.0)),
            "distance": _sec("Orbit", _f(5.0, 1e-4, 1e6, 0.1)),
            "distance_end": _sec("Orbit", _f(5.0, 1e-4, 1e6, 0.1)),
            "margin": _sec("Orbit", _f(1.15, 0.5, 10.0, 0.01)),
            "target_x": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "target_y": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "target_z": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_x": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_y": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_z": _sec("Interpolate", _f(5.0, -1e6, 1e6, 0.1)),
            "eye_end_x": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_end_y": _sec("Interpolate", _f(0.0, -1e6, 1e6, 0.1)),
            "eye_end_z": _sec("Interpolate", _f(5.0, -1e6, 1e6, 0.1)),
            "near": _sec("Clipping", _f(0.01, 1e-6, 1e6, 0.01)),
            "far": _sec("Clipping", _f(0.0, 0.0, 1e6, 0.1)),
        }, "optional": {"geo": (GEO,)}}
    RETURN_TYPES = (CAMSEQ, "INT", "STRING")
    RETURN_NAMES = ("cams", "frames", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, frames, mode, projection, resolution_x, resolution_y, fov,
            ortho_size, frame_geometry, loop, elev, elev_end, azim, azim_end,
            distance, distance_end, margin, target_x, target_y, target_z,
            eye_x, eye_y, eye_z, eye_end_x, eye_end_y, eye_end_z, near, far,
            geo=None):
        cams = _seq.camera_path(
            geo, frames=frames, mode=mode, projection=projection,
            xres=resolution_x, yres=resolution_y, fov=fov,
            ortho_size=ortho_size, elev=elev, elev_end=elev_end, azim=azim,
            azim_end=azim_end, distance=distance, distance_end=distance_end,
            margin=margin, target=(target_x, target_y, target_z),
            eye=(eye_x, eye_y, eye_z),
            eye_end=(eye_end_x, eye_end_y, eye_end_z),
            frame_geometry=frame_geometry, near=near, far=far, loop=loop)
        info = (f"{len(cams)} frames {mode} {resolution_x}x{resolution_y}"
                f"  {'loop (last frame does not repeat the first)' if loop else 'one-off (closed interval)'}")
        return (cams, len(cams), info)


class PCG_RenderSequence:
    """
    A list of cameras -> a list of COPs. **The B dimension of IMAGE is video**, and this fills it.

    With motion=True each frame gets three extra layers, motion / motion_bwd / disocclusion, computed from
    this frame to the next. The last frame has no next frame: with loop=True it wraps to frame 0, otherwise it gives all zeros +
    an all-1 disocclusion -- zeros rather than copying the previous frame, because "the last frame's motion is
    undefined" should be visible downstream; quietly copying would add a stretch of fake motion at the end of the exported video.

    This node runs all frames **serially**, unrelated to ComfyUI batching: geometry is a Python
    object and cannot go into a tensor batch. Measured 3.9 s for 24 frames of a 512² sphere (9.6 s with motion vectors).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cams": (CAMSEQ,),
            "pass_depth": ("BOOLEAN", {"default": True}),
            "pass_mask": ("BOOLEAN", {"default": True}),
            "pass_normal": ("BOOLEAN", {"default": True}),
            "pass_shade": ("BOOLEAN", {"default": False}),
            "pass_position": _sec("More Passes",
                                  ("BOOLEAN", {"default": False})),
            "pass_uv": _sec("More Passes", ("BOOLEAN", {"default": False})),
            "pass_id": _sec("More Passes", ("BOOLEAN", {"default": False})),
            "pass_facing": _sec("More Passes",
                                ("BOOLEAN", {"default": False})),
            "motion": ("BOOLEAN", {"default": False}),
            "motion_units": (list(_seq.UNITS),),
            "loop": ("BOOLEAN", {"default": True}),
            "normal_space": _sec("Attributes",
                                 (list(_rnd.NORMAL_SPACES),)),
            "normal_source": _sec("Attributes",
                                  (list(_rnd.NORMAL_SOURCES),)),
            "id_attribute": _sec("Attributes",
                                 _names("attrib", "prim", "name")),
            "uv_attribute": _sec("Attributes",
                                 _names("attrib", "vertex", "uv")),
            "cull": _sec("Attributes", (["none", "back", "front"],)),
            "group": _group(),
            "device": _dev("numpy"),
        }}
    RETURN_TYPES = (COPSEQ, "INT"); RETURN_NAMES = ("seq", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, geo, cams, pass_depth, pass_mask, pass_normal, pass_shade,
            pass_position, pass_uv, pass_id, pass_facing, motion,
            motion_units, loop, normal_space, normal_source, id_attribute,
            uv_attribute, cull, group, device):
        want = [n for n, on in (("depth", pass_depth), ("mask", pass_mask),
                                ("normal", pass_normal),
                                ("position", pass_position),
                                ("uv", pass_uv), ("id", pass_id),
                                ("facing", pass_facing),
                                ("shade", pass_shade)) if on] or ["mask"]
        seq = _seq.render_sequence(
            geo, cams, group, tuple(want), normal_space, normal_source,
            id_attribute, uv_attribute, cull, motion, motion_units, loop,
            device)
        return (seq, len(seq))


class PCG_MotionVectors:
    """
    **Exact** screen-space displacement between two frames. The most valuable node on the video side of the whole plugin.

    ━━ Why not optical flow
    Temporal-consistency schemes (optical flow warp, token merge, FreeNoise) all need to know "where this pixel was in the
    previous frame". The image side can only **estimate** -- RAFT / neural optical flow fails on weak texture, large displacement, mirrors and
    transparency, and fails without an error. Procedural generation **knows** where every vertex was in the previous frame, so
    the displacement here is analytic: same triangle, same barycentric weights, project the vertex positions of both frames once each,
    and subtract. No search, no smoothness term. Measured error under pure translation 1e-13.

    ━━ Forward and backward are images on two different grids, not one with a sign flip
        motion       on frame t's grid, "where I go in the next frame"
        motion_bwd   on frame t+1's grid, "where I came from in the previous frame"
    warp needs the backward one. Negating forward to get backward is only right when displacement is zero; once objects move, even the sets
    of covered pixels differ between the two images. So each is rasterized separately.

    ━━ disocclusion is the area that must be redrawn
    Anything warped from a place the previous frame could not see at all is bound to be wrong. The criterion uses triangle ids (the same trick as UV back-projection)
    plus a silhouette guard. Measured (sphere rotating 10°/frame, 256², warp reconstruction criterion):
    without the guard the p99 of valid-pixel error is 0.0714; a 1-pixel guard brings it down to **0.0024**.

    If the geometry does not move, wire only cam_next (camera motion); if the camera does not move, wire only geo_next (object motion).
    The **topology of the two frames must match** -- barycentric weights need correspondence.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cam": (CAM,),
            "units": (list(_seq.UNITS),),
            "depth_bias": _f(0.02, 0.0, 10.0, 0.001),
            "silhouette_guard": _i(1, 0, 64),
            "group": _group(),
            "device": _dev("numpy"),
        }, "optional": {"geo_next": (GEO,), "cam_next": (CAM,)}}
    RETURN_TYPES = (COP,); RETURN_NAMES = ("cop",)
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, geo, cam, units, depth_bias, silhouette_guard, group,
            device, geo_next=None, cam_next=None):
        return (_seq.motion_vectors(geo, cam, geo_next, cam_next, group,
                                    units, depth_bias, silhouette_guard,
                                    device),)


class PCG_CameraPick:
    """Pick one camera from a camera sequence. The index wraps, for the same reason as Sequence Pick."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "cams": (CAMSEQ,),
            "index": _i(0, 0, 1 << 20),
        }}
    RETURN_TYPES = (CAM, "INT"); RETURN_NAMES = ("cam", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, cams, index):
        if not cams:
            raise ValueError("The camera sequence is empty")
        return (cams[int(index) % len(cams)], len(cams))


class PCG_GeoSequencePick:
    """
    Picks one frame from a geometry sequence. The index **wraps** instead of raising -- going out of range while scrubbing index to look at the preview is normal,
    and raising would break the whole chain.

    The most common use is checking: take the sequence from For-Each Frame End, pick frame 0 and frame 5, wire each into
    a Viewport, and see at a glance whether the animation is right.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"geoseq": (GEOSEQ,), "index": _i(0, 0, 1 << 20)}}
    RETURN_TYPES = (GEO, "INT"); RETURN_NAMES = ("geo", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/loop"

    def run(self, geoseq, index):
        if not geoseq:
            raise ValueError("The geometry sequence is empty")
        return (geoseq[int(index) % len(geoseq)], len(geoseq))


class PCG_GeoMetrics:
    """
    Measures how **good** this geometry is -- hard criteria for automatic selection, also usable as QA.

    Face count / closedness / non-manifold edges / normal orientation consistency / degenerate faces / duplicate points / connected pieces /
    triangle quality / UV utilization and overlap / Euler characteristic and genus. These all **have definite answers**:
    a box's Euler characteristic is 2, not "about 2".

    ━━ The three most worth looking at
    · `closed` / `boundary_edges`: open meshes are no good for booleans or volumes
    · `flipped_edges`: adjacent faces with opposite winding = one normal in, one out. In shading it is a patch of
      black faces, in booleans the result is completely wrong, while the geometry itself "looks fine"
    · `genus`: (2−χ)/2 on a closed manifold. Sphere 0, torus 1. Whether a generated thing gained or lost
      a hole is obvious at a glance from this number

    `volume` is **signed**: on a closed mesh it is the true volume, and negative if the whole orientation is flipped --
    `flipped_edges` cannot catch that (all flipped is as "consistent" as none flipped), so the two criteria must be read together.

    ━━ Written to detail
    With `write_detail` on, all metrics are written as detail attributes, readable downstream by Wrangle / expressions with
    `detail("prims")`; Select Best reads them that way too. On name clashes, fill in `prefix`.

    ━━ Self-intersection is not done
    The correct approach is pairwise triangle intersection (with a BVH). An approximation like "shoot a few rays and see" would
    **quietly give a high score when it misses** -- in automatic selection a criterion that can miss is worse than none:
    without one people know to look for themselves; with one, they stop looking.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "pick": ("STRING", {"default": "prims", "tooltip":
                     "which metric goes to the value output"}),
            "compute_uv": ("BOOLEAN", {"default": True}),
            "compute_quality": ("BOOLEAN", {"default": True}),
            "uv_attrib": _names("attrib", "vertex", "uv"),
            "uv_res": _i(_mtr.DEFAULT_UV_RES, 8, 2048),
            "write_detail": ("BOOLEAN", {"default": True}),
            "prefix": ("STRING", {"default": ""}),
            "indent": _i(1, 0, 8),
        }}
    RETURN_TYPES = (GEO, "STRING", "FLOAT", "INT")
    RETURN_NAMES = ("geo", "json", "value", "int")
    FUNCTION = "run"; CATEGORY = CAT + "/output"

    def run(self, geo, pick, compute_uv, compute_quality, uv_attrib, uv_res,
            write_detail, prefix, indent):
        m = _mtr.metrics(geo, uv=compute_uv, quality=compute_quality,
                         uv_attrib=uv_attrib, res=uv_res)
        out = _mtr.write_detail(geo, m, prefix) if write_detail else geo
        key = str(pick).strip()
        if key and key not in m:
            raise KeyError(f"No metric '{key}'. Available: {sorted(m)}")
        v = float(m[key]) if key else 0.0
        return (out, json.dumps(m, ensure_ascii=False, sort_keys=True,
                                indent=(int(indent) or None)),
                v, int(round(v)))


class PCG_SelectBest:
    """
    **Picks the best by expression** from a list of variants. The missing half of the loop.

    Up to the previous batch the whole chain was one-way: procedural -> control image -> diffusion -> back to geometry. Run ten
    variants, and picking one was still done by eye -- and picking by eye is the ceiling of "automation": ten per round
    is fine, two hundred per round is impossible.

        For-Each (N seeds) -> ... -> For-Each End (geometry sequence)
        -> Select Best -> the best one + the sorted top K + a report

    ━━ What can be used in the expression
    · all metrics: `prims` / `closed` / `flipped_edges` / `uv_overlap` / `genus`...
    · `i` / `n`: which one, and how many in total
    · functions that read geometry: `detail("score")` / `npoints()` / `prim("area", 0, 0)`
      -- the same function library as Wrangle / Switch, so expressions can be copied over as is

    **Aesthetic scores come in through detail attributes.** CLIP / aesthetic / human preference belong to the image side;
    this node does not and should not do them; write that score as a detail attribute of the geometry inside the loop
    (the detail mode of Attribute Create), and here it can be weighted together with structural criteria in one expression:

        detail("score") * 2 - nonmanifold_edges * 0.1 - degenerate_prims

    Going through detail rather than a separate "score sequence" wire is because the score **travels with the geometry**:
    two parallel lists drift apart sooner or later, and once they do, the one picked is some other variant, which still looks reasonable.

    ━━ Ties go to the smaller index
    Otherwise two runs of the same input might pick different variants, and "the random numbers did not change but the result did"
    is the hardest kind to debug.

    `report` is every variant's score + key metrics, sorted -- to show people, or to put back into
    the prompt and have the model explain "why number 3 won".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geoseq": (GEOSEQ,),
            "score": ("STRING", {"multiline": True,
                      "default": "closed * 10 - nonmanifold_edges"
                                 " - degenerate_prims"}),
            "mode": (list(_mtr.MODES),),
            "top_k": _i(1, 1, 4096),
            "compute_uv": ("BOOLEAN", {"default": False}),
            "compute_quality": ("BOOLEAN", {"default": True}),
            "uv_attrib": _names("attrib", "vertex", "uv"),
            "uv_res": _i(_mtr.DEFAULT_UV_RES, 8, 2048),
            "report_metrics": ("STRING", {"default":
                               "prims points closed flipped_edges"}),
        }}
    RETURN_TYPES = (GEO, GEOSEQ, "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("best", "top_k", "index", "score", "report")
    FUNCTION = "run"; CATEGORY = CAT + "/loop"

    def run(self, geoseq, score, mode, top_k, compute_uv, compute_quality,
            uv_attrib, uv_res, report_metrics):
        best, top, idx, sc, rows, order = _mtr.select(
            geoseq, score, mode, top_k, uv=compute_uv,
            quality=compute_quality, uv_attrib=uv_attrib, res=uv_res)
        want = [w for w in str(report_metrics).replace(",", " ").split() if w]
        rep = []
        for rank, i in enumerate(order):
            r = {"rank": rank, "index": rows[i]["index"],
                 "score": round(rows[i]["score"], 6)}
            for w in want:
                if w in rows[i]["metrics"]:
                    v = rows[i]["metrics"][w]
                    r[w] = round(v, 6) if isinstance(v, float) else v
            rep.append(r)
        return (best, top, int(idx), float(sc),
                json.dumps(rep, ensure_ascii=False))


class PCG_TimeBlend:
    """
    Mirrors Houdini's Time Blend SOP: interpolates **between two frames** and returns one frame of geometry.

    The two most common uses: rendering a 24 fps sequence at 48 fps; and slow motion -- wire a
    Channel into frame whose curve advances slower than 1 frame per frame, and you get variable-speed slow motion.

    `interp=blend` requires the whole sequence to have **the same topology** (point i of every frame is the same point);
    otherwise it raises an error, naming which frame is wrong. Sequences whose topology changes, like fracturing / growth, can only
    use `hold` (takes the nearest integer frame, no interpolation).

    Integer / string attributes (id, class, name) are not interpolated; they take the nearer frame -- 0.5 of a
    class is not anything. For the reasons and the cost see the module docs of geo/timeops.py.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geoseq": (GEOSEQ,),
            "frame": _f(0.0, -1e6, 1e6, 0.1),
            "interp": (list(_tmo.RETIME_INTERP),),
            "loop": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO, "INT"); RETURN_NAMES = ("geo", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/loop"

    def run(self, geoseq, frame, interp, loop):
        return (_tmo.timeblend(geoseq, frame, loop, interp), len(geoseq))


class PCG_Trail:
    """
    Mirrors Houdini's Trail SOP: stacks up the previous few frames.

    mode:
        preserve   every frame of the trail is merged as is -- for onion skinning, a reference for motion blur. Also writes a
                   point attribute `trailframe` (0 is the current frame, −1 the previous ...),
                   for downstream fading
        connect    each point's trajectory becomes one **open polyline**, with `trailu` (0 earliest,
                   1 current). Houdini calls this mode Connect as Mesh; on geometry with faces
                   it stitches surface strips; here it only makes polylines, because stitching faces first needs deciding which edge is the outline,
                   and the "look at trajectories" use case does not need that step
        velocity   current-frame geometry + a `v` attribute (unit: **value/frame**). With a previous frame
                   it uses a backward difference; the first frame of the sequence degrades to a forward difference

    length is how many frames to look back, increment is the stride between sampled frames (a strided trail is "sparser",
    and clearer for fast motion). Frame numbers beyond the sequence ends are clamped rather than dropped -- otherwise the trail length
    of the first few frames would change frame by frame, looking like it is "growing out".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geoseq": (GEOSEQ,),
            "index": _i(0, -(1 << 20), 1 << 20),
            "mode": (list(_tmo.TRAIL_MODES),),
            "length": _i(4, 0, 4096),
            "increment": _i(1, 1, 4096),
            "loop": ("BOOLEAN", {"default": False}),
            "velocity_attrib": ("STRING", {"default": "v"}),
        }}
    RETURN_TYPES = (GEO, "INT"); RETURN_NAMES = ("geo", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/loop"

    def run(self, geoseq, index, mode, length, increment, loop,
            velocity_attrib):
        g = _tmo.trail(geoseq, index, length, increment, mode, loop,
                       velocity_attrib)
        return (g, len(geoseq))


class PCG_Retime:
    """
    Mirrors Houdini's Retime SOP: sequence -> a new sequence with time remapped.

    Three mappings:
        speed    source frame = start + i × speed. speed=0.5 is half speed, negative plays backwards
        length   spreads the output's frames evenly over the source sequence (changes duration only, not content)
        channel  source frame = the value of a **keyframe channel** at i -- time warping.
                 This is how retiming with a curve is done in Houdini, and the only one of the three that can
                 express "rush in, pause, ease out": `0:0  6:12  14:12  24:23`

    interp=blend interpolates between source frames (requires the same topology); hold only takes the nearest integer frame.

    **The identity mapping is an identity**: with `0:0 n-1:n-1` in channel mode (or speed=1,
    start=0) every output frame is bit-identical to the input, without a single multiply-add -- the tests use this
    as the criterion, because "looks unchanged" and "really unchanged" are two different things.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geoseq": (GEOSEQ,),
            "mode": (list(_tmo.RETIME_MODES),),
            "frames": _i(0, 0, 1 << 16),
            "speed": _f(1.0, -100.0, 100.0, 0.01),
            "start": _f(0.0, -1e6, 1e6, 0.1),
            "keys": ("STRING", {"default": "0:0  23:23"}),
            "interp": (list(_tmo.RETIME_INTERP),),
            "channel_interp": (list(_chn.INTERPS), {"default": "linear"}),
            "extrapolate": (list(_chn.EXTRAPS),),
            "loop": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEOSEQ, "INT", "STRING")
    RETURN_NAMES = ("geoseq", "frames", "info")
    FUNCTION = "run"; CATEGORY = CAT + "/loop"

    def run(self, geoseq, mode, frames, speed, start, keys, interp,
            channel_interp, extrapolate, loop):
        src = _tmo.retime_map(len(geoseq), frames, mode, speed, start, keys,
                              channel_interp, extrapolate)
        out = _tmo.retime(geoseq, frames, mode, speed, start, keys,
                          channel_interp, extrapolate, interp, loop)
        info = (f"{len(geoseq)} -> {len(out)} frames  "
                f"src {src.min():.3g}..{src.max():.3g}  {mode}/{interp}")
        return (out, len(out), info)


class PCG_SequenceMotion:
    """
    Geometry sequence + camera sequence -> **motion vector sequence**. The moving-geometry case.

    `Render Sequence`'s motion vectors can only capture camera motion (the geometry is one static copy). This node
    takes the geometry sequence from `For-Each Frame End`, so motion vectors of deformation, growth and fracturing can all
    be computed -- and that is exactly the one thing on the video side nobody else can compute: optical flow can only estimate; here it is analytic.

    Geometry and cameras must be equal in number, or only 1 camera is given (fixed camera). The symptom of being one frame off is motion
    vectors shifted by one step as a whole, and warping gives double images, so a mismatch raises an error directly.

    The last frame has no next frame: with loop=True it wraps to frame 0, otherwise it gives all zeros + an all-1
    disocclusion.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geoseq": (GEOSEQ,),
            "cams": (CAMSEQ,),
            "units": (list(_seq.UNITS),),
            "depth_bias": _f(0.02, 0.0, 10.0, 0.001),
            "silhouette_guard": _i(1, 0, 64),
            "loop": ("BOOLEAN", {"default": True}),
            "group": _group(),
            "device": _dev("numpy"),
        }}
    RETURN_TYPES = (COPSEQ, "INT"); RETURN_NAMES = ("seq", "frames")
    FUNCTION = "run"; CATEGORY = CAT + "/render"

    def run(self, geoseq, cams, units, depth_bias, silhouette_guard, loop,
            group, device):
        seq = _seq.motion_sequence(geoseq, cams, group, units, depth_bias,
                                   silhouette_guard, loop, device)
        return (seq, len(seq))


class PCG_Circle:
    """
    Mirrors Houdini's Circle SOP.

    radius is two numbers -- a circle is a special case of an ellipse, and giving them separately allows ellipses. orientation decides which
    plane it lies in; rotate is a Euler rotation stacked on afterwards.

    reverse flips the winding. Circles are often used as Sweep cross-sections or PolyExtrude input, and with the wrong orientation
    all normals point inward, so this toggle is needed.

    arc_type: closed full circle / open_arc an open arc / closed_arc an arc closed with a chord /
    sliced_arc an arc with two radii back to the centre (a pie slice).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prim_type": (["polygon", "nurbs_curve", "bezier_curve"],),
            "orientation": (["xy", "yz", "zx"],),
            "reverse": ("BOOLEAN", {"default": False}),
            "radius_x": _f(1.0, 0.0), "radius_y": _f(1.0, 0.0),
            "divisions": _i(12, 3, 4096),
            "cx": _f(), "cy": _f(), "cz": _f(),
            "uniform_scale": _f(1.0, 0.0),

            **{k: _sec("Rotate", v, gate=(k == "use_rotate")) for k, v in {
                "use_rotate": ("BOOLEAN", {"default": False}),
                "rx": _f(0.0, -3600, 3600, 1.0), "ry": _f(0.0, -3600, 3600, 1.0),
                "rz": _f(0.0, -3600, 3600, 1.0),
            }.items()},

            **{k: _sec("Arc", v, gate=(k == "use_arc")) for k, v in {
                "use_arc": ("BOOLEAN", {"default": False}),
                "arc_type": (["open_arc", "closed_arc", "sliced_arc"],),
                "arc_start": _f(0.0, -3600, 3600, 1.0),
                "arc_end": _f(360.0, -3600, 3600, 1.0),
            }.items()},

            **{k: _sec("Spline", v, gate=(k == "use_spline")) for k, v in {
                "use_spline": ("BOOLEAN", {"default": False}),
                "order": _i(4, 2, 11),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/generate"

    def run(self, prim_type, orientation, reverse, radius_x, radius_y,
            divisions, cx, cy, cz, uniform_scale,
            use_rotate, rx, ry, rz, use_arc, arc_type, arc_start, arc_end,
            use_spline, order):
        g = build.circle(
            (radius_x, radius_y), (cx, cy, cz),
            (rx, ry, rz) if use_rotate else (0, 0, 0),
            uniform_scale, orientation, reverse, divisions,
            arc_type if use_arc else "closed", (arc_start, arc_end))
        if prim_type != "polygon":
            basis = "nurbs" if prim_type == "nurbs_curve" else "bezier"
            g = ops.to_spline(g, "curve", basis, "",
                              order if use_spline else 4)
        return (g,)


class PCG_MatchSize:
    """
    Mirrors Houdini's Match Size SOP.

    Its real use is not "changing size" but **establishing a restorable canonical space**: match a model from any source
    to the unit box -> work in canonical space (cut, scatter, compute UVs) -> then send it back with the stashed
    transform. So the Stash / Restore fields matter as much as alignment.

    With the second input wired it aligns to its bounding box; unwired (or justify_with set to target_values)
    it uses Target Position / Size below.

    When restore_attribute has a name and the geometry really has that detail attribute, it **only restores** --
    it reads the stored 4x4, applies its inverse, and ignores all other parameters. Same as Houdini:
    Restore and alignment are two mutually exclusive things.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "geo": (GEO,),
                "justify_with": (["input_if_wired", "target_values"],),
                "target_px": _f(), "target_py": _f(), "target_pz": _f(),
                "target_sx": _f(1.0, 0.0), "target_sy": _f(1.0, 0.0),
                "target_sz": _f(1.0, 0.0),
                "translate": ("BOOLEAN", {"default": True}),
                "justify_x": (["center", "min", "max", "none"],),
                "justify_y": (["center", "min", "max", "none"],),
                "justify_z": (["center", "min", "max", "none"],),

                **{k: _sec("Justify To", v, gate=(k == "use_justify_to"))
                   for k, v in {
                       "use_justify_to": ("BOOLEAN", {"default": False}),
                       "to_x": (["same", "min", "center", "max"],),
                       "to_y": (["same", "min", "center", "max"],),
                       "to_z": (["same", "min", "center", "max"],),
                       "offset_x": _f(), "offset_y": _f(), "offset_z": _f(),
                   }.items()},

                **{k: _sec("Scale to Fit", v, gate=(k == "scale_to_fit"))
                   for k, v in {
                       "scale_to_fit": ("BOOLEAN", {"default": False}),
                       "uniform_scale": ("BOOLEAN", {"default": True}),
                   }.items()},

                **{k: _sec("Bounds Group", v, gate=(k == "use_group_bounds"))
                   for k, v in {
                       "use_group_bounds": ("BOOLEAN", {"default": False}),
                       "group": _group("Only use these elements to compute the bounding box"),
                       "group_type": (["prim", "point"],),
                   }.items()},

                **{k: _sec("Transform Attribute", v, gate=(k == "use_xform"))
                   for k, v in {
                       "use_xform": ("BOOLEAN", {"default": False}),
                       "stash_attribute": ("STRING", {"default": "xform"}),
                       "restore_attribute": ("STRING", {"default": ""}),
                   }.items()},
            },
            "optional": {"target": (GEO,)},
        }
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, justify_with, target_px, target_py, target_pz,
            target_sx, target_sy, target_sz, translate,
            justify_x, justify_y, justify_z,
            use_justify_to, to_x, to_y, to_z, offset_x, offset_y, offset_z,
            scale_to_fit, uniform_scale,
            use_group_bounds, group, group_type,
            use_xform, stash_attribute, restore_attribute, target=None):
        return (matchsize.match_size(
            geo, target,
            group if use_group_bounds else "", group_type, justify_with,
            (target_px, target_py, target_pz),
            (target_sx, target_sy, target_sz),
            use_group_bounds, translate,
            (justify_x, justify_y, justify_z),
            (to_x, to_y, to_z) if use_justify_to else ("same",) * 3,
            (offset_x, offset_y, offset_z) if use_justify_to else (0, 0, 0),
            scale_to_fit, uniform_scale,
            stash_attribute if use_xform else "",
            restore_attribute if use_xform else ""),)


class PCG_ExtractCentroid:
    """
    Mirrors Houdini's Extract Centroid SOP: condenses each piece of geometry into one point.

    Pieces use the same implementation as For-Each Begin (geo/pieces.py), so the two nodes always agree
    on "how many pieces there are".

    Center of Mass is **area-weighted**: a point average is biased by mesh density -- for the same box,
    with one face subdivided into 100 segments and the other five a single quad each, the point average leans noticeably toward the subdivided face.
    (Houdini computes the volume centroid for closed pieces; here it is always the surface area centroid; on symmetric parts the two
    coincide; asymmetric solid pieces will differ.)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "run_over": (["pieces", "primitives", "points", "connectivity",
                          "detail"],),
            "piece_attribute": _names("attrib", "prim", "name"),
            "piece_elements": (["primitives", "points"],),
            "method": (["center_of_mass", "bounding_box", "average_position"],),
            "output": (["points", "attribute"],),
            "group": _group("Only split within these elements; empty = all"),

            **{k: _sec("Attribute Output", v, gate=(k == "use_attrib_out"))
               for k, v in {
                   "use_attrib_out": ("BOOLEAN", {"default": True}),
                   "attribute_name": ("STRING", {"default": "centroid"}),
               }.items()},

            **{k: _sec("Transfer", v, gate=(k == "use_transfer")) for k, v in {
                "use_transfer": ("BOOLEAN", {"default": False}),
                "transfer_attributes": _names("attrib", "prim", "",
                                              "carry these attributes onto the output points"),
                "transfer_groups": _names("group", "prim", ""),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, run_over, piece_attribute, piece_elements, method,
            output, group, use_attrib_out, attribute_name,
            use_transfer, transfer_attributes, transfer_groups):
        return (centroid.extract_centroid(
            geo, run_over, piece_attribute, piece_elements, method, output,
            attribute_name if use_attrib_out else None,
            transfer_attributes if use_transfer else "",
            transfer_groups if use_transfer else "", group),)



# ============================================================ curves / planar
class PCG_PolyExpand2D:
    """
    Mirrors Houdini's PolyExpand2D: equidistant offsetting of a planar curve network.

    The approach is not "push every edge and be done" -- that makes concave corners cross into small loops and narrow parts flip over whole.
    Here a self-intersecting mitered offset is generated first, then everything that overshot is trimmed off by **distance from midpoint to input ≥ offset**,
    and what remains is exactly the straight-skeleton offset. The criterion only depends on point-to-segment distances;
    there is no event queue, so none of the degenerate event ordering problems that are the nastiest part of straight-skeleton implementations.

    Inside / outside come from the input's own faces: the input is treated as a planar graph (points fused, split at intersections, traversed in angular order);
    bounded faces offset inward give inside, and offsetting the unbounded face inward means expanding outward, giving outside.
    A tree-shaped road network has no bounded face, so there is only outside -- one ring enclosing the whole network.

    The ends of open curves get **square caps** (going another offset along the tangent), not flat caps connecting the two sides directly:
    a flat cap's midpoint sits right on the curve end point at distance 0 and would be trimmed off, breaking the loop. With Omit End Caps on,
    the three segments of the square cap are removed together, and the two remaining lines exactly cover the edges of the original curve.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only offset these faces/curves"),
            "positions_2d": (list(_pex.PLANE_MODES),),
            "plane_origin_x": _f(0.0), "plane_origin_y": _f(0.0),
            "plane_origin_z": _f(0.0),
            "plane_distance": _f(0.0),
            "plane_normal_x": _f(0.0), "plane_normal_y": _f(1.0),
            "plane_normal_z": _f(0.0),
            "output": (list(_pex.OUTPUTS),),
            "offset": _f(0.1, -1e6, 1e6, 0.01),
            "divisions": _i(1, 1, 256),
            "side_determination": (list(_pex.SIDE_MODES),),
            "output_inside": ("BOOLEAN", {"default": True}),
            "output_outside": ("BOOLEAN", {"default": True}),
            "keep_input_geometry": ("BOOLEAN", {"default": False}),
            "split_offset_curves_to_omit_end_caps": ("BOOLEAN",
                                                     {"default": False}),

            **{k: _sec("Local Attributes", v,
                       gate=(k == "create_output_groups")) for k, v in {
                "create_output_groups": ("BOOLEAN", {"default": False}),
                "inside_group": ("STRING", {"default": "inside"}),
                "outside_group": ("STRING", {"default": "outside"}),
            }.items()},
            **{k: _sec("Local Attributes", v) for k, v in {
                "edge_distance_attribute": _names(
                    "attrib", "point", "", "write this ring's offset distance on the output points"),
                "edge_speed_attribute": _names(
                    "attrib", "prim", "", "per-edge offset multiplier (prim or point attribute)"),
                "coincidence_tolerance": _f(0.003, 0.0, 1e3, 0.001),
                "parallelism_tolerance": _f(0.01, 0.0, 1.0, 0.001),
                "on_failure": (list(_pex.FAILURE),),
                "recompute_point_normals": ("BOOLEAN", {"default": True}),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, positions_2d, plane_origin_x, plane_origin_y,
            plane_origin_z, plane_distance, plane_normal_x, plane_normal_y,
            plane_normal_z, output, offset, divisions, side_determination,
            output_inside, output_outside, keep_input_geometry,
            split_offset_curves_to_omit_end_caps, create_output_groups,
            inside_group, outside_group, edge_distance_attribute,
            edge_speed_attribute, coincidence_tolerance,
            parallelism_tolerance, on_failure, recompute_point_normals):
        g = _pex.polyexpand2d(
            geo, group, positions_2d,
            (plane_origin_x, plane_origin_y, plane_origin_z), plane_distance,
            (plane_normal_x, plane_normal_y, plane_normal_z), output,
            offset, divisions, side_determination, output_inside,
            output_outside, keep_input_geometry,
            split_offset_curves_to_omit_end_caps, create_output_groups,
            inside_group, outside_group, edge_distance_attribute,
            edge_speed_attribute, coincidence_tolerance,
            parallelism_tolerance, on_failure)
        # Offset Curves produces curves, which have no normals themselves; only with Offset Surfaces' faces, or
        # when Keep Input Geometry merges back an input with faces, does this option have anything to do (only if the input has N)
        if recompute_point_normals and g.nprims and g.prim_closed.any() \
                and g.has(POINT, "N"):
            g = ops.compute_normals(g, add_to="point")
        return (g,)


class PCG_Refine:
    """
    Mirrors Houdini's Refine: adds / removes points or subdivides at parametric positions on curves.

    Division of labour with Resample: Resample resamples the whole curve and drops all original points; Refine only
    **inserts**, leaving the original points, attributes and numbering untouched -- new points are always appended at the end, so the vertex lists
    of unselected faces need no change at all, and points shared on a mesh are not split apart.

    Spacing decides how u is measured: uniform_domain divides evenly by vertex index, uniform_arc by arc length.
    On curves with uneven point density the two differ a lot.

    The V direction is not done: that field corresponds to the second parametric direction of a parametric surface, and polygon meshes have no global
    (u,v) parameterization. Knot insertion on spline prims is not done either; it raises an error asking you to Convert first.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only process these curves"),
            "mode": (list(_ref.MODES),),
            "use_first_u": ("BOOLEAN", {"default": True}),
            "first_u": _f(0.25, 0.0, 1.0, 0.01),
            "use_second_u": ("BOOLEAN", {"default": False}),
            "second_u": _f(0.75, 0.0, 1.0, 0.01),
            "u_divisions": _i(2, 1, 4096),
            "nurb_count_u": _i(1, 1, 64),
            "spacing": (list(_ref.SPACING),),
            "tolerance": _f(0.01, 0.0, 1e6, 0.001),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, mode, use_first_u, first_u, use_second_u,
            second_u, u_divisions, nurb_count_u, spacing, tolerance):
        return (_ref.refine(geo, group, mode, use_first_u, first_u,
                            use_second_u, second_u, u_divisions, nurb_count_u,
                            spacing, tolerance),)


class PCG_PointJitter:
    """
    Mirrors Houdini's Point Jitter: adds random perturbation to points.

    The random stream is taken by **id attribute** (if a name is given), not by point number -- delete a point upstream, Sort,
    or Fuse two points, and point numbers shift wholesale, so jitter taken by point number would all change.

    The displacement is **uniform within a sphere**, not within a cube: taking [-1,1] on each of the three axes makes the diagonal direction
    1.73 times longer than the axes, and on grid-like input the directionality is visible at a glance. For directionality use Axis Scales.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only jitter these points"),
            "mask": _f(1.0, 0.0, 1.0, 0.01),
            "mask_mode": (list(_pj.MASK_MODES),),
            "mask_attribute": _names("attrib", "point", "", "multiplied onto Mask"),
            "id_attribute": _names(
                "attrib", "point", "", "take the random stream by it; empty = by point number"),
            "scale": _f(1.0, 0.0, 1e6, 0.01),
            "axis_scale_x": _f(1.0), "axis_scale_y": _f(1.0),
            "axis_scale_z": _f(1.0),
            "rand_seed": _i(1, 0, 1 << 31),
            "use_point_scale": ("BOOLEAN", {"default": False}),
            "update_normals": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, mask, mask_mode, mask_attribute, id_attribute,
            scale, axis_scale_x, axis_scale_y, axis_scale_z, rand_seed,
            use_point_scale, update_normals):
        return (_pj.point_jitter(
            geo, group, mask, mask_mode, mask_attribute, id_attribute, scale,
            (axis_scale_x, axis_scale_y, axis_scale_z), rand_seed,
            use_point_scale, update_normals),)



class PCG_ConvertLine:
    """
    Mirrors Houdini's Convert Line: breaks faces into lines.

    Shared edges produce only one line -- emitting segments face by face, corner by corner would produce every interior edge twice; the wireframe looks the same,
    but fed to a solver it is two overlapping springs, doubling the stiffness for nothing.

    With Connect Path on, instead of a pile of two-point segments, edges are chained into polylines as long as possible (continuing through points of degree 2,
    breaking at points whose degree is not 2). Only when chained does downstream Resample / Carve / Sweep treat them as curves.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only break these faces"),
            "keep_group_order": ("BOOLEAN", {"default": True}),
            "connect_path": ("BOOLEAN", {"default": False}),
            "make_isolated_loops_closed": ("BOOLEAN", {"default": False}),
            "remove_unused_points": ("BOOLEAN", {"default": False}),
            "compute_length": ("BOOLEAN", {"default": True}),
            "length_attribute": ("STRING", {"default": "restlength"}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/convert"

    def run(self, geo, group, keep_group_order, connect_path,
            make_isolated_loops_closed, remove_unused_points, compute_length,
            length_attribute):
        return (_cvl.convert_line(
            geo, group, keep_group_order, connect_path,
            make_isolated_loops_closed and connect_path, remove_unused_points,
            length_attribute if compute_length else ""),)


class PCG_PolyPath:
    """
    Chains polylines whose end points touch into curves as long as possible. **Never creates an edge out of nothing.**

    Why it is needed: Resample / Carve / Sweep / PolyExpand2D all work **per prim**;
    a curve has to be one prim for them to know what "walking along the curve" means. What upstream gives is often
    a pile -- Clip cuts a line into several segments, Convert Line emits a pile of two-point segments by default (a 5x5
    grid gives 40), several Merged branches have coincident end points that are not the same point. Then
    `Resample segments=10` does not give you 10 segments, it gives **every fragment** 10 segments; Sweep is worse,
    sweeping a tube along every fragment, with interpenetration at all the joints.

    **The boundary with Join is "does it create edges out of nothing".** PolyPath only connects end points that already touch;
    the geometric shape does not change at all, only "which points belong to which prim"; Join **forcibly** connects in order, and when end points
    do not coincide it adds a straight segment across. Both needs are real and mutually exclusive, so they are two nodes --
    if mixed into one and switched by a toggle, the user could never be sure whether their graph had edges quietly added.

    **It connects whole prims rather than breaking them into edges and re-walking.** Houdini's PolyPath breaks the input into edges and
    re-chains them, with the consequence that a long polyline that was perfectly fine gets split in two wherever one of its points
    **happens** to be crossed by another line -- the user asked for nothing, and the input comes out more fragmented. Here every input polyline
    is an atomic unit, and only its **two end points** take part in connection, so a long line passing through the middle of others is kept as is.
    The price is that it will not split a badly written polyline for you; that is Dissolve / Blast's job.

    **Junction -- what to do when three or more meet at one end point.** A 5x5 grid wireframe (40 edges),
    measured:

        split        36 (most still two-point). Houdini PolyPath's behaviour, the most conservative
        straightest  7: 6 interior rows/columns + 1 closed outer loop of 16 edges
        any          6, of varying length (3/5/7/9/11/11)

    Road networks want straightest. **Max Angle only applies at junctions** -- where the degree is 2 there is
    no second choice at all, so it always connects, otherwise PolyPath would not be PolyPath (that is how the grid's four corners
    get connected into the outer loop: 90° turns, but there is no other road there).

    **Match Attribute**: two lines whose values of this prim attribute differ may not be connected. Split a road network by road class,
    and main roads will not turn into alleys at junctions.

    **Tolerance does not average.** When two end points are within tolerance but not the same point, the **one that came first**
    is kept. Taking the midpoint would move the end points of both lines, and "PolyPath does not change the geometric shape" would no longer hold --
    and that is exactly its boundary with Join. Deviations within tolerance are numerical noise anyway. If you really want both sides to
    give a little, put a Fuse first; that node is made for this.

    Faces and already closed prims do not take part and **pass through as is** (they are not dropped).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only process these prims"),
            "tolerance": _f(0.0, 0.0, 1e6, 0.001),
            "junction": (list(_jn.JUNCTIONS),),
            "max_angle": _f(60.0, 0.0, 180.0, 1.0),
            "close_loops": ("BOOLEAN", {"default": True}),
            "match_attribute": _names(
                "attrib", "prim", "", "empty = no restriction; if set, only connect where this attribute is equal"),
            "prim_attribs": (list(_jn.PRIM_ATTRIBS),),
            "remove_unused_points": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, tolerance, junction, max_angle, close_loops,
            match_attribute, prim_attribs, remove_unused_points):
        return (_jn.polypath(geo, group, tolerance, junction, max_angle,
                             match_attribute, close_loops, prim_attribs,
                             remove_unused_points),)


class PCG_Join:
    """
    Joins the selected polylines into one, **in order**. When end points do not coincide it adds a straight segment across -- that is its
    only difference from PolyPath, and the reason it exists.

    The order is prim number. The use is "joining several separately made trajectories into one complete path": the end points
    are not supposed to coincide, and those connecting segments are exactly what is wanted.

    **Reverse To Fit (on by default).** Before attaching each line it checks which end is closer to the current tail, and puts that end
    first. Houdini's Join does not do this, and without it, if the upstream prim orientations are slightly messy,
    the result is a zigzag folding back and forth -- this is almost bound to happen on Clip / Boolean output,
    because those operators do not guarantee consistent segment orientation. Turning it off gives a strict "tail of the previous to head of the next".

    **Tolerance here is not a "weld radius" but "how close counts as already connected".** Gaps smaller than it count as
    the same point (no segment added and no zero-length edge left); only larger ones really get a connecting segment.

    **Loop**: connects the last segment back to the start of the first, outputting a closed prim.

    **Partition Attribute**: groups by a prim attribute and joins each group separately. "One trajectory per name" in
    fracture animation is this.

    Prim attributes are taken from the **first** line in the chain (Houdini's Join follows the same rule). Vertex attributes follow
    their corners; when a line is reversed, its uv / width are reversed too -- otherwise the texture flow would flip at
    the joint, and it would be the "shape looks fine" kind of error.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only join these prims"),
            "loop": ("BOOLEAN", {"default": False}),
            "tolerance": _f(0.0, 0.0, 1e6, 0.001),
            "reverse_to_fit": ("BOOLEAN", {"default": True}),
            "partition_attribute": _names(
                "attrib", "prim", "", "empty = join everything into one; if set, group by it"),
            "prim_attribs": (list(_jn.PRIM_ATTRIBS),),
            "remove_unused_points": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, loop, tolerance, reverse_to_fit,
            partition_attribute, prim_attribs, remove_unused_points):
        return (_jn.join(geo, group, loop, tolerance, reverse_to_fit,
                         partition_attribute, prim_attribs,
                         remove_unused_points),)


class PCG_AttribNoise:
    """
    Mirrors Houdini's Attribute Noise. Comes with a vectorized noise library.

    The noise is **a function of position**: the random values at lattice points come from a hash of integer lattice coordinates, with no state and no
    pre-generated permutation table. So the same world coordinate always samples the same value, and two pieces of geometry match at the seam.

    Noise Along Vector on + push along N, and a Grid becomes terrain -- that is how "mountains" are made.
    The three Fractal modes differ in "where detail is added": standard (fBm) is equally rough everywhere; terrain and
    hybrid_terrain **multiply** the octaves, so high places get ever more rugged and valley floors get flattened, more like eroded terrain.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "attribute_class": (list(_an.CLASSES),),
            "attribute_names": _names("attrib", "point", "P"),
            "use_x": ("BOOLEAN", {"default": True}),
            "use_y": ("BOOLEAN", {"default": True}),
            "use_z": ("BOOLEAN", {"default": True}),
            "noise_along_vector": ("BOOLEAN", {"default": False}),
            "vector_attribute": _names("attrib", "point", "N"),
            "blend": _f(1.0, 0.0, 1.0, 0.01),

            **{k: _sec("Noise Value", v) for k, v in {
                "operation": (list(_an.OPERATIONS),),
                "range_values": (list(_an.RANGES),),
                "amplitude": _f(0.25, -1e6, 1e6, 0.01),
            }.items()},

            **{k: _sec("Value Correction", v,
                       gate=(k == "use_value_correction")) for k, v in {
                "use_value_correction": ("BOOLEAN", {"default": False}),
                "bias": _f(0.5, 0.001, 0.999, 0.01),
                "gain": _f(0.5, 0.001, 0.999, 0.01),
            }.items()},
            **{k: _sec("Value Correction", v,
                       gate=(k == "use_remap_ramp")) for k, v in {
                "use_remap_ramp": ("BOOLEAN", {"default": False}),
                "remap_ramp": ("STRING", {"default": "0:0  0.5:0.25  1:1"}),
                "ramp_mode": (list(_an.RAMP_MODES),),
            }.items()},
            **{k: _sec("Value Correction", v) for k, v in {
                "use_clamp_min": ("BOOLEAN", {"default": False}),
                "clamp_min": _f(0.0),
                "use_clamp_max": ("BOOLEAN", {"default": False}),
                "clamp_max": _f(1.0),
            }.items()},

            **{k: _sec("Noise Pattern", v) for k, v in {
                # pcg100 s6: Manhattan / Chebyshev Cellular appended at the end of the menu (NOISE_TYPES_X)
                "noise_type": (list(_an.NOISE_TYPES_X),),
                "location_attribute": _names("attrib", "point", "P"),
                "element_size_x": _f(1.0, 1e-6, 1e6, 0.01),
                "element_size_y": _f(1.0, 1e-6, 1e6, 0.01),
                "element_size_z": _f(1.0, 1e-6, 1e6, 0.01),
                "offset_x": _f(0.0), "offset_y": _f(0.0), "offset_z": _f(0.0),
                "rand_seed": _i(0, 0, 1 << 31),
            }.items()},
            **{k: _sec("Noise Pattern", v, gate=(k == "use_vexpression"))
               for k, v in {
                "use_vexpression": ("BOOLEAN", {"default": False}),
                "vexpression": ("STRING", {
                    "default": "set(0, @P.y * 0.1, 0)", "code_hl": True,
                    "tooltip": "Compute one vector per element and add it to Offset"}),
            }.items()},

            **{k: _sec("Animation", v, gate=(k == "use_animation"))
               for k, v in {
                "use_animation": ("BOOLEAN", {"default": False}),
                "noise_time": _f(0.0, -1e6, 1e6, 0.01),
                "time_element_size": _f(1.0, 1e-6, 1e6, 0.01),
            }.items()},

            **{k: _sec("Fractal", v) for k, v in {
                "fractal": (list(_an.FRACTALS),),
                "octaves": _i(3, 1, 16),
                "lacunarity": _f(2.0, 1.0, 16.0, 0.01),
                "roughness": _f(0.5, 0.0, 1.0, 0.01),
                "fractal_offset": _f(0.7, -4.0, 4.0, 0.01),
            }.items()},

            **{k: _sec("Warping", v) for k, v in {
                "warp": _f(0.0, -1e6, 1e6, 0.01),
                "warp_element_size": _f(1.0, 1e-6, 1e6, 0.01),
                "warp_octaves": _i(1, 1, 8),
            }.items()},

            **{k: _sec("Post-Process", v) for k, v in {
                "post_absolute": ("BOOLEAN", {"default": False}),
                "post_invert": ("BOOLEAN", {"default": False}),
                "use_normalize": ("BOOLEAN", {"default": False}),
                "normalize_min": _f(0.0),
                "normalize_max": _f(1.0),
            }.items()},
        }, "optional": {
            # ── pcg100 s6 addition (Houdini Attribute Noise), default = previous behaviour
            "blend_attribute": _names("attrib", "point", ""),
            "attribute_type": (list(_an.ATTRIB_TYPES),),
            "min_value": _f(0.0), "max_value": _f(1.0),
            "middle_value": _f(0.0), "range_length": _f(1.0),
            "gamma": _f(1.0, 0.001, 100.0, 0.01),
            "contrast": _f(1.0, 0.0, 100.0, 0.01),
            "make_unit_length": ("BOOLEAN", {"default": False}),
            "recompute_normals": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, group, attribute_class, attribute_names, use_x, use_y,
            use_z, noise_along_vector, vector_attribute, blend, operation,
            range_values, amplitude, use_value_correction, bias, gain,
            use_remap_ramp, remap_ramp, ramp_mode, use_clamp_min, clamp_min,
            use_clamp_max, clamp_max, noise_type, location_attribute,
            element_size_x, element_size_y, element_size_z, offset_x,
            offset_y, offset_z, rand_seed, use_vexpression, vexpression,
            use_animation, noise_time, time_element_size, fractal, octaves,
            lacunarity, roughness, fractal_offset, warp, warp_element_size,
            warp_octaves, post_absolute, post_invert, use_normalize,
            normalize_min, normalize_max,
            blend_attribute="", attribute_type="auto", min_value=0.0,
            max_value=1.0, middle_value=0.0, range_length=1.0, gamma=1.0,
            contrast=1.0, make_unit_length=False, recompute_normals=False):
        return (_an.attribute_noise(
            geo, group, attribute_class, attribute_names, use_x, use_y, use_z,
            noise_along_vector, vector_attribute, operation, range_values,
            amplitude, noise_type, location_attribute,
            (element_size_x, element_size_y, element_size_z),
            (offset_x, offset_y, offset_z),
            vexpression if use_vexpression else "",
            use_animation, noise_time, time_element_size,
            fractal, octaves, lacunarity, roughness, fractal_offset,
            warp, warp_element_size, warp_octaves,
            rand_seed, blend, use_value_correction, bias, gain,
            use_remap_ramp, remap_ramp, ramp_mode,
            post_absolute, post_invert, use_normalize, normalize_min,
            normalize_max, use_clamp_min, clamp_min, use_clamp_max,
            clamp_max, blend_attribute, min_value, max_value, middle_value,
            range_length, gamma, contrast, attribute_type, make_unit_length,
            recompute_normals),)


class PCG_Measure:
    """
    Mirrors Houdini's Measure: measures area / perimeter / volume / curvature.

    Area uses the Newell area vector, not a fan triangulation summing absolute values -- the latter double-counts the folded
    parts of concave polygons and comes out too large. Volume uses the same formula: a cone from any point,
    V = (1/3)(area vector · v0); summed over a closed mesh it is exactly the enclosed volume, independent of the reference point.

    Visualized Range defaults to **median ± MAD**, not min/max: one distorted face can squash the
    min/max colour scale into a single flat colour, while MAD is insensitive to outliers; most elements fall into distinguishable
    colour bands and the outliers hit the two ends -- exactly the picture you want when hunting for them.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "element_type": (list(_ms.ELEMENTS),),
            "measurement": (list(_ms.MEASURES),),
            "accumulate": (list(_ms.ACCUMULATE),),
            "position_attribute": _names("attrib", "point", "P"),

            **{k: _sec("Visualized Range", v) for k, v in {
                "use_min": ("BOOLEAN", {"default": False}),
                "min_value": _f(-1.0),
                "use_max": ("BOOLEAN", {"default": False}),
                "max_value": _f(1.0),
                "use_width": ("BOOLEAN", {"default": True}),
                "width": _f(6.0, 0.0, 1e6, 0.1),
                "width_mode": (list(_ms.WIDTH_MODES),),
                "center": (list(_ms.CENTERS),),
                "color_ramp": (list(_ms.RAMPS),),
                "custom_ramp": ("STRING", {
                    "default": "0:0,0,0.5  0.5:0.9,0.9,0.9  1:0.8,0,0",
                    "tooltip": "Used when color_ramp is custom. position:r,g,b"}),
                "ramp_mode": (list(_ms.RAMP_MODES),),
                "color_attribute": ("STRING", {"default": ""}),
            }.items()},

            **{k: _sec("Output", v) for k, v in {
                "attribute_name": ("STRING", {"default": "area"}),
                "total_attribute": ("STRING", {"default": ""}),
                "range_group": ("STRING", {"default": ""}),
                "bake_range": ("BOOLEAN", {"default": False}),
                "remap_min": _f(0.0),
                "remap_max": _f(1.0),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, group, element_type, measurement, accumulate,
            position_attribute, use_min, min_value, use_max, max_value,
            use_width, width, width_mode, center, color_ramp, custom_ramp,
            ramp_mode, color_attribute, attribute_name, total_attribute,
            range_group, bake_range, remap_min, remap_max):
        return (_ms.measure(
            geo, group, element_type, measurement, accumulate,
            position_attribute, attribute_name, total_attribute, range_group,
            use_min, min_value, use_max, max_value, use_width, width,
            width_mode, center, color_ramp, custom_ramp, ramp_mode,
            color_attribute, bake_range, remap_min, remap_max),)



# ============================================================ attribute basics
class PCG_AttribCreate:
    """
    Mirrors Houdini's Attribute Create: creates an attribute and writes a value.

    With a non-empty group it **only writes the selected elements** and the rest keep their values -- the most common way of "tagging part
    of the elements". With Use Expression on, the value comes from a one-line wrangle expression (`@P.y`, `@ptnum % 3`),
    evaluated per element.

    The point of this node is that **the graph shows what was done**: with five Wrangles mixed into a chain of nodes,
    coming back two weeks later you have to open each one and read the code; a named node is documentation.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only write these elements"),
            "attribute_class": (list(_ao.CLASSES),),
            "name": _names("attrib", "point", "attrib", "several can be given, space-separated"),
            "attribute_type": (list(_ao.TYPES),),
            "size": _i(1, 1, 4),
            "value_x": _f(0.0), "value_y": _f(0.0),
            "value_z": _f(0.0), "value_w": _f(0.0),
            "string_value": ("STRING", {"default": ""}),
            "use_expression": ("BOOLEAN", {"default": False}),
            "expression": ("STRING", {"default": "@P.y", "code_hl": True}),
            "only_if_missing": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, group, attribute_class, name, attribute_type, size,
            value_x, value_y, value_z, value_w, string_value, use_expression,
            expression, only_if_missing):
        return (_ao.create(geo, name, attribute_class, attribute_type, size,
                           (value_x, value_y, value_z, value_w), string_value,
                           expression if use_expression else "", group,
                           only_if_missing),)


class PCG_AttribCopy:
    """
    Mirrors Houdini's Attribute Copy: copies attributes from another geometry by **element index**.

    Division of labour with Attribute Transfer: Copy requires the elements on both sides to **already correspond** (the same geometry
    split into two branches, each computing something, then merged back), one to one by index; once the topology has changed the indices no longer match,
    and then either attach an id and match by id, or use Transfer to match by distance.

    Elements whose index is beyond the source range **keep their values** rather than getting 0 -- filling 0 would make an error like "the two sides have different element counts"
    look like the data itself has a patch of zeros, which is very hard to track down.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "dest": (GEO,), "source": (GEO,),
            "group": _group("Only write these elements of the target"),
            "attribute_class": (list(_ao.CLASSES),),
            "attributes": _names("attrib", "point", "Cd"),
            "groups": ("STRING", {"default": "", "is_group": True}),
            "use_match_attribute": ("BOOLEAN", {"default": False}),
            "match_attribute": _names("attrib", "point", "id"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, dest, source, group, attribute_class, attributes, groups,
            use_match_attribute, match_attribute):
        return (_ao.copy(dest, source, attributes, attribute_class,
                         match_attribute if use_match_attribute else "",
                         group, groups),)


class PCG_AttribRename:
    """
    Mirrors Houdini's Attribute Rename. Write `old:new`, several pairs separated by spaces.

    Wildcards are supported: `uv*:tex*` turns uv1 -> tex1 and uvSet -> texSet; the part matched by `*`
    is carried as is onto the `*` of the new name. With Rename Groups on it renames groups instead of attributes --
    the operation is identical, and splitting it into two nodes would only mean remembering two places.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "attribute_class": (list(_ao.CLASSES),),
            "rename": ("STRING", {"default": "old:new",
                                  "tooltip": "old:new, several pairs separated by spaces"}),
            "rename_groups": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, attribute_class, rename, rename_groups):
        return (_ao.rename(geo, rename, attribute_class, rename_groups),)


class PCG_AttribCast:
    """
    Mirrors Houdini's Attribute Cast: changes an attribute's storage type.

    float64 is more precise but doubles memory, int32 halves it, string is handy for tagging. Float to integer
    **rounds** rather than truncates: 2.9 becomes 3, not 2 -- truncation makes it easier to think upstream computed it wrong.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "attribute_class": (list(_ao.CLASSES),),
            "attributes": _names("attrib", "point", "*"),
            "to_type": (list(_ao.CAST_TYPES),),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, attribute_class, attributes, to_type):
        return (_ao.cast(geo, attributes, attribute_class, to_type),)


class PCG_AttribRandomize:
    """
    Mirrors Houdini's Attribute Randomize. Add variation to pscale / orient after scattering,
    otherwise a field of copies looks like a military parade.

    **direction is not "randomize each of the three components, then normalize"**: that gives directions denser at the corners
    of the cube, and a field of orientations shows a diagonal bias. Uniform on the sphere has to be uniform in cos (Archimedes' projection),
    and the same inside a cone. Fully random orient uses Shoemake's method of building a quaternion directly from three uniform numbers, strictly uniform
    on SO(3); three random Euler angles are not uniform and pile up near the poles.

    The random stream is taken by id attribute (if a name is given), so upstream additions, deletions and sorting do not affect it.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "attribute_class": (list(_ao.CLASSES),),
            "name": _names("attrib", "point", "pscale"),
            "mode": (list(_arn.MODES),),
            "combine": (list(_arn.COMBINE),),
            "rand_seed": _i(0, 0, 1 << 31),
            "id_attribute": _names("attrib", "point", "",
                                   "take the random stream by it; empty = by element number"),

            **{k: _sec("Value", v) for k, v in {
                "distribution": (list(_arn.DISTRIBUTIONS),),
                "dimensions": _i(1, 1, 4),
                "min_x": _f(0.0), "min_y": _f(0.0),
                "min_z": _f(0.0), "min_w": _f(0.0),
                "max_x": _f(1.0), "max_y": _f(1.0),
                "max_z": _f(1.0), "max_w": _f(1.0),
                "mean": _f(0.5), "stddev": _f(0.25, 0.0),
                "exponent": _f(2.0, 0.01, 100.0, 0.01),
            }.items()},

            **{k: _sec("Direction / Orient", v) for k, v in {
                "shape": (list(_arn.SHAPES),),
                "axis_x": _f(0.0), "axis_y": _f(1.0), "axis_z": _f(0.0),
                "cone_angle": _f(45.0, 0.0, 180.0, 1.0),
                "angle_min": _f(0.0, -3600.0, 3600.0, 1.0),
                "angle_max": _f(360.0, -3600.0, 3600.0, 1.0),
                "length_min": _f(1.0), "length_max": _f(1.0),
            }.items()},
        }, "optional": {
            # ── pcg100 s6 addition (Houdini's Two Values / Uniform (Discrete) /
            #    Custom Discrete / Global Scale), default = previous behaviour
            "prob_b": _sec("Value", _f(0.5, 0.0, 1.0, 0.01)),
            "step_size": _sec("Value", _f(1.0, 0.0, 1e6, 0.01)),
            "value_list": _sec("Value", ("STRING", {
                "default": "0\n1", "multiline": True,
                "tooltip": "Custom Discrete: one set of values per line (min-max:step expands), w=weight at the end of the line"})),
            "global_scale": _f(1.0),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, group, attribute_class, name, mode, combine, rand_seed,
            id_attribute, distribution, dimensions, min_x, min_y, min_z,
            min_w, max_x, max_y, max_z, max_w, mean, stddev, exponent, shape,
            axis_x, axis_y, axis_z, cone_angle, angle_min, angle_max,
            length_min, length_max, prob_b=0.5, step_size=1.0,
            value_list="0\n1", global_scale=1.0):
        return (_arn.randomize(
            geo, name, attribute_class, mode, distribution, dimensions,
            (min_x, min_y, min_z, min_w), (max_x, max_y, max_z, max_w),
            mean, stddev, exponent, shape, (axis_x, axis_y, axis_z),
            cone_angle, angle_min, angle_max, length_min, length_max,
            combine, rand_seed, id_attribute, group,
            prob_b, step_size, global_scale, value_list),)


class PCG_AttribBlur:
    """
    Mirrors Houdini's Attribute Blur: spreads attributes along the topology.

    **Not a spatial blur, it propagates along edges** -- however close two pieces of geometry are, if they are not connected they do not affect each other
    (the masks on the two sides of a wall should not bleed into each other).

    Each iteration does `v += step · mask · (neighbour average - v)`, an explicit heat diffusion. step above 1 diverges,
    so it is clamped to [0,1]; to blur further, add iterations rather than step size. There is no "radius" parameter because
    on a mesh with uneven edge lengths the same radius is one step in sparse areas and ten steps in dense ones; that number would lie.

    Elements outside group are **frozen but still take part in averaging**, otherwise the boundary would be held up by its own values and blur into a bright rim.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only blur these elements (those outside still take part in averaging)"),
            "attribute_class": (["point", "prim"],),
            "attributes": _names("attrib", "point", "Cd"),
            "iterations": _i(5, 0, 1000),
            "step": _f(0.5, 0.0, 1.0, 0.01),
            "mode": (list(_ablr.MODES),),
            "mask_attribute": _names("attrib", "point", ""),
            "invert_mask": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, group, attribute_class, attributes, iterations, step,
            mode, mask_attribute, invert_mask):
        return (_ablr.blur(geo, attributes, attribute_class, iterations, step,
                           mode, mask_attribute, invert_mask, group),)


class PCG_AttribInterpolate:
    """
    Mirrors Houdini's Attribute Interpolate: interpolates source geometry attributes onto points by sourceprim.

    By default it **derives barycentric coordinates back from the point's own position** instead of trusting uv. Because (u,v) is ambiguous for polygons:
    cut a quad into two triangles, and the same (u,v) is valid in both triangles -- and scattering on a
    quad mesh is exactly the most common use. Measured: a linear attribute on a quad mesh via uv has errors up to 0.97,
    derived from position it is 1e-6; with the source triangulated first, both routes are exact.

    To use Houdini's approach, turn on Use UV Attribute.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "source": (GEO,),
            "group": _group(),
            "attribute_class": (["point", "vertex"],),
            "attributes": _names("attrib", "point", "*"),
            "prim_attribute": _names("attrib", "point", "sourceprim"),
            "use_uv_attribute": ("BOOLEAN", {"default": False}),
            "uv_attribute": _names("attrib", "point", "sourceprimuv"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, source, group, attribute_class, attributes,
            prim_attribute, use_uv_attribute, uv_attribute):
        return (_ao.interpolate(geo, source, attributes, attribute_class,
                                prim_attribute, uv_attribute,
                                use_uv_attribute, group),)


class PCG_AttribAdjust:
    """
    Mirrors Houdini's Attribute Adjust Float / Integer / Vector -- merged into one node.

    Those three are separate because Houdini's parameter controls are typed (a float slider cannot hold
    three components); here values are always (N, C) float arrays and the component count comes from the attribute itself, so three nodes would only
    mean two more names to remember.

    Four stages in a fixed order: **initialize -> adjustment stack -> remap -> post-process**. The order matters:
    remap needs to see the final distribution to set its range automatically, and rounding must come last (round first, then multiply by 2 to get even numbers).
    Hardcoding it in the node is harder to get wrong than having people chain four nodes themselves.

    Adjustments is a text stack, one step per line (ComfyUI widgets are declared statically; there is no Houdini-style
    multiparm)::

        mul   2.0
        add   @curvature
        mul   rand(0.8, 1.2)
        add   noise(perlin, 2.0, 0.3)
        mix   1.0 mask=@occlusion
        set   (@P.y * 0.1)

    Operations set/add/sub/mul/div/min/max/pow/mix; the source can be a number, a comma-separated vector,
    `@attribute`, `rand(a,b)`, `noise(type,size,amplitude)` or a wrangle expression in parentheses.
    Each line can carry its own `mask=`, controlling how much the step applies.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "attribute_class": (list(_aa.CLASSES),),
            "attribute_name": _names("attrib", "point", "pscale"),
            "create_if_missing": ("BOOLEAN", {"default": True}),
            "size": _i(1, 1, 4),
            "to_int": ("BOOLEAN", {"default": False}),

            **{k: _sec("Initialize", v) for k, v in {
                "initialize": (list(_aa.INIT),),
                "constant_x": _f(1.0), "constant_y": _f(0.0),
                "constant_z": _f(0.0), "constant_w": _f(0.0),
                "source_attribute": _names("attrib", "point", ""),
                "distribution": (list(_aa.DISTRIBUTIONS),),
                "rand_min": _f(0.0), "rand_max": _f(1.0),
                "gaussian_mean": _f(0.5), "gaussian_stddev": _f(0.25),
                "power_exponent": _f(2.0, 0.001, 64.0, 0.01),
                "noise_type": (list(_aa.NOISE_TYPES),),
                "noise_size": _f(1.0, 1e-6, 1e6, 0.01),
                "noise_amplitude": _f(1.0),
                "expression": ("STRING", {"default": "@P.y", "code_hl": True}),
                "rand_seed": _i(0, 0, 1 << 31),
                "id_attribute": _names("attrib", "point", ""),
            }.items()},

            **{k: _sec("Adjustments", v) for k, v in {
                "adjustments": ("STRING", {
                    "default": "", "multiline": True, "code_hl": True,
                    "tooltip": "One step per line: <op> <source> [mask=<source>]"}),
            }.items()},

            **{k: _sec("Remap", v, gate=(k == "use_remap")) for k, v in {
                "use_remap": ("BOOLEAN", {"default": False}),
                "remap_ramp": ("STRING", {"default": "0:0  0.5:0.25  1:1"}),
                "ramp_mode": (list(_aa.RAMP_MODES),),
                "input_range": (list(_aa.RANGE_MODES),),
                "in_min": _f(0.0), "in_max": _f(1.0),
                "out_min": _f(0.0), "out_max": _f(1.0),
                "range_per_component": ("BOOLEAN", {"default": False}),
            }.items()},

            **{k: _sec("Post-Process", v) for k, v in {
                "use_clamp_min": ("BOOLEAN", {"default": False}),
                "clamp_min": _f(0.0),
                "use_clamp_max": ("BOOLEAN", {"default": False}),
                "clamp_max": _f(1.0),
                "normalize": (list(_aa.NORMALIZE),),
                "round_mode": (list(_aa.ROUND),),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, group, attribute_class, attribute_name,
            create_if_missing, size, to_int, initialize, constant_x,
            constant_y, constant_z, constant_w, source_attribute,
            distribution, rand_min, rand_max, gaussian_mean, gaussian_stddev,
            power_exponent, noise_type, noise_size, noise_amplitude,
            expression, rand_seed, id_attribute, adjustments, use_remap,
            remap_ramp, ramp_mode, input_range, in_min, in_max, out_min,
            out_max, range_per_component, use_clamp_min, clamp_min,
            use_clamp_max, clamp_max, normalize, round_mode):
        return (_aa.adjust(
            geo, attribute_name, attribute_class, group, initialize, size,
            create_if_missing,
            (constant_x, constant_y, constant_z, constant_w),
            distribution, rand_min, rand_max, gaussian_mean, gaussian_stddev,
            power_exponent, source_attribute, noise_type, noise_size,
            noise_amplitude, expression, adjustments, use_remap, remap_ramp,
            ramp_mode, input_range, in_min, in_max, out_min, out_max,
            range_per_component, use_clamp_min, clamp_min, use_clamp_max,
            clamp_max, round_mode, normalize, to_int, rand_seed,
            id_attribute),)


class PCG_Delete:
    """
    Mirrors Houdini's Delete SOP. Blast deletes by group; this one adds **conditions group specifiers cannot
    express**: delete every Nth, delete what is outside a bounding box, delete faces facing away from a direction.

    The four filters are **intersected**: `group ∩ number ∩ bounding volume ∩ normal ∩ expression`; a filter that is off
    selects everything. Intersection reads naturally -- first circle a patch with group, then delete every 3rd within it;
    union would make "turning on a filter" delete more, so adding a condition would loosen it.

    When no filter is on and group is empty too, it **does nothing**: treating an empty group as "select all" here
    would delete the whole geometry, which hardly seems like what anyone wants.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "entity": (list(_del.ENTITIES),),
            "operation": (list(_del.OPERATIONS),),
            "group": _group(),
            "keep_points": ("BOOLEAN", {
                "default": False,
                "tooltip": "When deleting faces, do not delete their points along with them (for keeping a point cloud to scatter trees on)"}),

            **{k: _sec("Number", v, gate=(k == "use_number")) for k, v in {
                "use_number": ("BOOLEAN", {"default": False}),
                "number_mode": (list(_del.NUMBER_MODES),),
                "number_start": _i(0, 0, 1 << 24),
                "number_end": ("INT", {"default": -1, "min": -1,
                                       "max": 1 << 24,
                                       "tooltip": "-1 = to the end"}),
                "number_step": _i(2, 1, 1 << 16),
            }.items()},

            **{k: _sec("Bounding Volume", v, gate=(k == "use_volume"))
               for k, v in {
                "use_volume": ("BOOLEAN", {"default": False}),
                "volume_type": (list(_del.VOLUME_TYPES),),
                "center_x": _f(0.0), "center_y": _f(0.0), "center_z": _f(0.0),
                "size_x": _f(1.0), "size_y": _f(1.0), "size_z": _f(1.0),
                "radius": _f(1.0, 0.0, 1e6, 0.01),
                "volume_invert": ("BOOLEAN", {"default": False}),
            }.items()},

            **{k: _sec("Normal", v, gate=(k == "use_normal")) for k, v in {
                "use_normal": ("BOOLEAN", {"default": False}),
                "direction_x": _f(0.0), "direction_y": _f(1.0),
                "direction_z": _f(0.0),
                "spread_angle": _f(45.0, 0.0, 180.0, 0.5),
                "normal_attribute": _names("attrib", "prim", ""),
                "normal_invert": ("BOOLEAN", {"default": False}),
            }.items()},

            **{k: _sec("Expression", v, gate=(k == "use_expression"))
               for k, v in {
                "use_expression": ("BOOLEAN", {"default": False}),
                "expression": ("STRING", {
                    "default": "@P.y > 0", "code_hl": True,
                    "tooltip": "Boolean expression, same syntax as group expressions"}),
            }.items()},
        }, "optional": {
            # ── pcg100 addition (default = previous behaviour) ──
            # Number page: Pattern, plus Delete by Range's "Select _ of _"
            "number_pattern": _sec("Number", ("STRING", {
                "default": "!*",
                "tooltip": "Number pattern: 0 5 12 / 0-20 / 0-20:3 / !3-5 / *"})),
            "select_num": _sec("Number", _i(1, 1, 1 << 16)),
            "select_of": _sec("Number", _i(1, 1, 1 << 16)),
            **{k: _sec("Degenerate", v, gate=(k == "use_degenerate"))
               for k, v in {
                "use_degenerate": ("BOOLEAN", {"default": False}),
                "degenerate": ("BOOLEAN", {"default": True}),
                "zero_area": ("BOOLEAN", {"default": False}),
                "open_faces": ("BOOLEAN", {"default": False}),
                "degenerate_tolerance": _f(0.001, 0.0, 1e6, 0.0001),
            }.items()},
            **{k: _sec("Random", v, gate=(k == "use_random")) for k, v in {
                "use_random": ("BOOLEAN", {"default": False}),
                "rand_seed": _i(0, 0, 1 << 30),
                "use_seed_attribute": ("BOOLEAN", {"default": False}),
                "seed_attribute": _names("attrib", "point", "id"),
                "percent": _f(50.0, 0.0, 100.0, 0.1),
            }.items()},
            "delete_unused_groups": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, entity, operation, group, keep_points, use_number,
            number_mode, number_start, number_end, number_step, use_volume,
            volume_type, center_x, center_y, center_z, size_x, size_y, size_z,
            radius, volume_invert, use_normal, direction_x, direction_y,
            direction_z, spread_angle, normal_attribute, normal_invert,
            use_expression, expression,
            number_pattern="!*", select_num=1, select_of=1,
            use_degenerate=False, degenerate=True, zero_area=False,
            open_faces=False, degenerate_tolerance=0.001,
            use_random=False, rand_seed=0, use_seed_attribute=False,
            seed_attribute="id", percent=50.0, delete_unused_groups=False):
        return (_del.delete(
            geo, entity, operation, group,
            use_number, number_mode, number_start, number_end, number_step,
            use_volume, volume_type, (center_x, center_y, center_z),
            (size_x, size_y, size_z), radius, volume_invert,
            use_normal, (direction_x, direction_y, direction_z),
            spread_angle, normal_attribute, normal_invert,
            use_expression, expression, keep_points,
            number_pattern, select_num, select_of,
            use_degenerate, degenerate, zero_area, open_faces,
            degenerate_tolerance,
            use_random, rand_seed, percent,
            seed_attribute if use_seed_attribute else "",
            delete_unused_groups),)


class PCG_GroupExpand:
    """
    Mirrors Houdini's Group Expand. Grows or shrinks a group along the topology.

    Two metrics: `steps` counts edges hopped (tied to mesh density -- on a subdivided mesh "grow 3 steps" actually
    covers only half the range); `distance` is the **geodesic distance** summing edge lengths, independent of density.
    **Not Euclidean distance** -- two pieces of geometry touching but not connected are infinitely far apart, so selections on the two sides
    of a wall do not bleed into each other.

    Shrinking = growing the complement, then inverting (erosion in morphology). Note that **the outer boundary of the geometry is not eroded**:
    the complement only contains elements really not in the group, and there is nothing outside the geometry. Same as Houdini, but different from
    erosion in image processing.

    Output Falloff also writes a 0..1 distance falloff attribute, saving an extra Attribute Fade.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "cls": (list(_gex.CLASSES),),
            "group": _group("The group to grow/shrink"),
            "output_group": _names("group", "point", "",
                                   "empty = overwrite the group Group refers to in place"),
            "mode": (list(_gex.MODES),),
            "metric": (list(_gex.METRICS),),
            "radius": _f(1.0, 0.0, 1e6, 0.1),
            **{k: _sec("Falloff", v, gate=(k == "output_falloff"))
               for k, v in {
                "output_falloff": ("BOOLEAN", {"default": False}),
                "falloff_attribute": _names("attrib", "point", "falloff"),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, cls, group, output_group, mode, metric, radius,
            output_falloff, falloff_attribute):
        return (_gex.group_expand(geo, cls, group, output_group, mode,
                                  metric, radius, output_falloff,
                                  falloff_attribute),)


class PCG_AttribFade:
    """
    Mirrors Houdini's Attribute Fade. Writes a fade attribute starting from a group.

        inside the group            inside_value (default 1)
        d steps/metres outside      ramp(1 - d/radius)
        beyond the radius           outside_value (default 0)

    The most common use of this attribute is as a mask for Transform / Attribute Adjust / Noise --
    "only lift this patch, with smooth transitions at the edges". So the default ramp is **smooth** rather than linear:
    linear has a first-derivative crease at the group boundary, and pushing with it shows a visible ridge.

    With From Boundary on, it falls off from the group's **boundary** both inward and outward, for a soft selection where "only the centre is 1".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "attribute_name": _names("attrib", "point", "fade"),
            "cls": (list(_gex.CLASSES),),
            "group": _group("Start from this group"),
            "metric": (list(_gex.METRICS),),
            "radius": _f(3.0, 0.0, 1e6, 0.1),
            "from_boundary": ("BOOLEAN", {"default": False}),
            **{k: _sec("Falloff", v) for k, v in {
                "falloff_ramp": ("STRING", {"default": "0:0  1:1"}),
                "ramp_mode": (list(_gex.RAMP_MODES), {"default": "smooth"}),
                "inside_value": _f(1.0),
                "outside_value": _f(0.0),
                "invert": ("BOOLEAN", {"default": False}),
                "combine": (list(_gex.COMBINE),),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/attribute"

    def run(self, geo, attribute_name, cls, group, metric, radius,
            from_boundary, falloff_ramp, ramp_mode, inside_value,
            outside_value, invert, combine):
        return (_gex.fade(geo, attribute_name, cls, group, metric, radius,
                          falloff_ramp, ramp_mode, inside_value,
                          outside_value, invert, combine, from_boundary),)


class PCG_Subdivide:
    """
    Mirrors Houdini's Subdivide. Three algorithms:

      * `catmull_clark` -- any number of sides -> one quad per corner; the limit surface is a B-spline.
        The default choice for hard-surface fillets and building high-poly from low-poly
      * `loop` -- triangles only, one into four. Better than CC on triangle meshes (CC cuts a triangle into
        three skewed quads)
      * `linear` -- cuts only, no smoothing. Adds density but **does not change the shape**, for cases that displace by themselves, like
        "subdivide, then add noise to make terrain"

    Boundary matches OpenSubdiv's three modes: `edge_corner` (default, the boundary is a crease curve and
    the four corners stay put), `edge_only` (corners follow the curve and get worn away), `smooth`
    (the boundary is not a crease, and the whole surface shrinks inward).

    Creases: edge groups and auto angle are infinitely sharp; since pcg79 the **fractional** weights of the vertex attribute creaseweight
    are also recognised (written by the Crease node; OpenSubdiv's semi-sharp creases: s ≥ 1 is sharp this round, 0..1 blends, and each round
    subtracts 1). Crease Attribute empty = not read.

    Attributes: point attributes use the same stencil as P (Cd gets smoothed along, which is correct); vertex attributes
    are interpolated linearly (just right for uv); prim attributes are inherited by new faces from their source faces.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only subdivide these faces; empty = all"),
            "algorithm": (list(_sub.ALGORITHMS),),
            "depth": _i(1, 0, 6),
            "boundary": (list(_sub.BOUNDARY),),
            **{k: _sec("Creases", v) for k, v in {
                "crease_group": _names("group", "edge", "",
                                       "edge group: these edges stay sharp"),
                "auto_crease_angle": ("FLOAT", {
                    "default": -1.0, "min": -1.0, "max": 180.0, "step": 1.0,
                    "tooltip": "Edges with a dihedral angle above this many degrees become creases automatically; -1 = off"}),
                "output_crease_group": _names("group", "edge", "",
                                              "write the final crease edges as an edge group"),
                "crease_attribute": _names("attrib", "vertex", "creaseweight",
                                           "fractional crease weights (written by the Crease node); empty = not read"),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, algorithm, depth, boundary, crease_group,
            auto_crease_angle, output_crease_group,
            crease_attribute="creaseweight"):
        return (_sub.subdivide(geo, depth, algorithm, group, crease_group,
                               auto_crease_angle, boundary,
                               output_crease_group, crease_attribute),)


class PCG_Dissolve:
    """
    Mirrors Houdini's Dissolve. Deletes the selected edges and merges the faces on both sides into one.

    It is the same machinery as Divide's Remove Shared Edges, at a **different granularity**: that one works by primitive group
    (all interior edges between the selected faces are merged away), this one by edge group (only the edges you pick get merged).

    When the selected edges form a connected patch, it is merged into one whole piece at once rather than edge by edge -- merging one by one would
    rebuild topology at every step, and the intermediate states might not be valid polygons. Patches that do not form a **single** boundary loop (with holes)
    are left as is rather than forced together: a prim has only one vertex loop and cannot store a face with a hole.

    **Remove Inline Points is on by default**; this is the most overlooked half of Dissolve: after merging,
    the end points of the removed edge usually have only two edges passing through, with three points collinear; keeping them, the face count drops but the vertex count
    does not, and later subdivision / UVs carry these redundant points along. The criterion is an angle rather than "exactly collinear" --
    edges computed in floating point are rarely exactly collinear.

    **Boundary edges** with only one face are skipped (there are no "faces on both sides" to merge); the number skipped is written to the detail
    attribute `dissolve_skipped`.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "edge_group": _names("group", "edge", "",
                                 "edges to delete; empty = do nothing"),
            "remove_inline_points": ("BOOLEAN", {"default": True}),
            "inline_tolerance": _f(0.1, 0.0, 90.0, 0.01),
            "delete_lone_points": ("BOOLEAN", {"default": False}),
            "output_boundary_group": _names("group", "edge", "",
                                            "write the outer rim of the merged large faces as an edge group"),
        }, "optional": {
            # pcg100 addition; first item / default = previous behaviour (see BRIDGE in geo/dissolve.py)
            "operation": (list(_dsv.OPERATIONS),),
            "bridge": (list(_dsv.BRIDGE),),
            "recompute_normals": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, edge_group, remove_inline_points, inline_tolerance,
            delete_lone_points, output_boundary_group, operation="selected",
            bridge="leave", recompute_normals=False):
        return (_dsv.dissolve(geo, edge_group, remove_inline_points,
                              inline_tolerance, delete_lone_points,
                              output_boundary_group, operation, bridge,
                              recompute_normals),)


class PCG_EdgeDivide:
    """
    Mirrors Houdini's Edge Divide. Inserts points on the selected edges and connects the new points to cut the faces.

    **"Inserting points" and "connecting" are two different things.** Inserting points is safe on any face; connecting only has a unique answer when
    "exactly two edges of this face are cut" -- with points on one edge, where should they connect to? With three edges there is no non-arbitrary answer.
    So:

        0 edges cut on the face          left as is
        2 edges cut on the face + Connect   cut into cuts+1 pieces
        otherwise                    only insert points; the face becomes an ngon with more sides

    With three or more Houdini connects in a fan toward the face centre; that is one choice, not the unique answer, and it introduces a new point
    that is on no edge. Not done here; better to let people add a Divide and decide how to cut.

    Cut Positions can take custom parametric positions (`0.2 0.5 0.9`); empty divides evenly by Cuts.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "edge_group": _names("group", "edge", "", "Edges to cut"),
            "cuts": _i(1, 1, 64),
            "cut_positions": ("STRING", {
                "default": "",
                "tooltip": "Custom parametric positions, e.g. 0.25 0.5 0.75; empty = divide evenly by Cuts"}),
            "connect": ("BOOLEAN", {"default": True}),
            "output_edge_group": _names("group", "edge", "",
                                        "newly inserted cut edges"),
            "output_point_group": _names("group", "point", "", "Newly inserted points"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, edge_group, cuts, cut_positions, connect,
            output_edge_group, output_point_group):
        return (_edv.edge_divide(geo, edge_group, cuts, cut_positions,
                                 connect, output_edge_group,
                                 output_point_group),)


class PCG_LoopCut:
    """
    Adds a whole edge loop -- mirrors the loop mode of Houdini's PolySplit (called Loop Cut /
    Insert Edge Loop in other software).

    Starting from the seed edge, it steps into the adjacent **quad**, takes "the opposite edge" (two steps away on the vertex loop),
    and crosses into the next quad -- until it gets back to the start or hits a boundary / non-quad. The collected edges
    are handed to Edge Divide's connect, giving a whole loop.

    **A non-quad ends the loop**, and this is not laziness: a triangle has no "opposite edge", a pentagon has two,
    so the loop is naturally broken there. Blender / Maya behave the same way.

    One seed edge is enough; giving several on the same loop does not cut it twice.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "edge_group": _names("group", "edge", "", "Seed edges: the loop starts walking here"),
            "cuts": _i(1, 1, 64),
            "cut_positions": ("STRING", {
                "default": "",
                "tooltip": "Custom parametric positions; empty = divide evenly by Cuts"}),
            "output_edge_group": _names("group", "edge", "", "Newly inserted edge loop"),
            "output_point_group": _names("group", "point", "", "Newly inserted points"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, edge_group, cuts, cut_positions, output_edge_group,
            output_point_group):
        return (_edv.loop_cut(geo, edge_group, cuts, cut_positions,
                              output_edge_group, output_point_group),)


class PCG_PolyReduce:
    """
    Mirrors Houdini's PolyReduce. Quadric error metric (QEM) edge-collapse reduction -- the Garland-Heckbert
    1997 method, still the foundation of every commercial reducer today.

    Every point carries a 4x4 **quadric** `Q = Σ area·ppᵀ` recording "how far from the original surface". When collapsing an
    edge the Q of both ends are simply added, and the new point's error is `vᵀQv` -- the error accumulates along the way, so the 100th
    collapse knows how far it has already drifted and does not keep gnawing at the same spot. That is exactly why it is so much better
    than "pick the shortest edge every time".

    **Boundary Weight is usually the most important parameter.** Looking only at faces, the area near the mesh rim is flat,
    and QEM gnaws the boundary away without hesitation -- measured: a flat Grid reduced to 5%, with weight 0 the area collapses from
    16 to 0.9 (the whole sheet degenerates into a strip along the edge); with 4 it keeps exactly 16. Crease Weight is another entry to the same
    mechanism: it adds a "virtual wall" to crease edges, so dragging them away costs a huge price.

    The input is triangulated first, and **the output is triangles** (Houdini's Preserve Quads is not done).
    pcg100: Target gains two modes counted by points (Percentage of point count / Output point count);
    Hard Edges (edge group, both end points locked), Soft Points + Weight (adds a "how far from the original position" cost for these points).
    Preserve UVs: for LODs -- only half-edge collapses, points on UV seams and hard edges locked, vertex attributes
    rewritten along with the collapses, so the reduced LOD shares the same textures as the original model.
    This node is the only greedy serial one in the whole set -- reduction fundamentally cannot be computed in one batch; for why and measured speeds
    see the README.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only reduce these faces; empty = all"),
            "target": (list(_prd.TARGETS),),
            "keep_percent": _f(50.0, 0.01, 100.0, 0.5),
            "target_count": _i(1000, 1, 1 << 24),
            "position": (list(_prd.POSITIONS),),

            **{k: _sec("Preserve", v) for k, v in {
                "boundary_weight": _f(4.0, 0.0, 1e6, 0.1),
                "crease_group": _names("group", "edge", "",
                                       "keep these edges as much as possible"),
                "crease_weight": _f(4.0, 0.0, 1e6, 0.1),
                "lock_boundary": ("BOOLEAN", {"default": False}),
                "lock_group": _group("Not a single one of these points may move"),
                "max_normal_flip": _f(90.0, 0.0, 180.0, 1.0),
            }.items()},
            # pcg84 addition at the end: LODs share textures -- UVs / hard-edge normals follow as is (half-edge collapse, locked seams)
            "preserve_uvs": ("BOOLEAN", {"default": False}),
            # pcg100 addition: Houdini's Hard Edges, Soft Points + Weight
            "hard_edges": _names("group", "edge", "", "These edges may not move (both end points locked)"),
            "soft_points": _group("These points stay in place as much as possible, but may move"),
            "soft_weight": _f(1.0, 0.0, 1e9, 0.1),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, target, keep_percent, target_count, position,
            boundary_weight, crease_group, crease_weight, lock_boundary,
            lock_group, max_normal_flip, preserve_uvs=False, hard_edges="",
            soft_points="", soft_weight=1.0):
        return (_prd.reduce_mesh(geo, target, keep_percent, target_count,
                                 position, boundary_weight, crease_group,
                                 crease_weight, lock_boundary, lock_group,
                                 max_normal_flip, group, preserve_uvs,
                                 hard_edges, soft_points, soft_weight),)


class PCG_UVProject:
    """
    Mirrors Houdini's UV Texture. Generates UVs by projection -- until now the whole set had no UV node at all.

    **UVs are written as a vertex attribute by default, not point.** One point can map to several
    places in UV space (both sides of a seam, UV island borders); a point attribute stores one value per point and cannot hold that discontinuity.
    Cylindrical / spherical projection **always** produces a seam; written as point, the u of the column of faces on the seam would
    interpolate from 0.98 all the way back to 0.02, smearing the whole texture sideways.

    Fix Seams checks the u span per face; past half a period it adds 1 to the smaller half -- the seam face's u becomes
    (0.98, 0.99, 1.01, 1.02), continuous. Going outside [0,1] is fine, texture addressing is repeat.
    **Only a vertex attribute can do this.**

    Modes:
      * `planar` / `cylindrical` / `spherical` -- project along the given axis
      * `box` -- six-sided projection, picks the axis by **face normal** (point normals would tear faces apart in UV space),
        naturally splits into 6 islands; follow with UV Layout to pack
      * `face` -- each face gets its own 0..1, for one-image-per-piece uses like bricks/cards
      * `rows_columns` -- rows/columns uv on a structured quad grid, recovered by BFS on the dual graph,
        independent of prim order

    Projector section (pcg100, matches the Transformation tab of Houdini's UV Project): when on, it no longer centres on the
    bounding box + Fit; instead a unit-size projector (plane / cylinder / sphere / torus) is placed in the scene by this TRS, uv is taken from the projector's
    parameterisation, then mapped by U / V Range. box / face / rows_columns are unaffected.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "mode": (list(_uvp.MODES),),
            "axis": (list(_uvp.AXES), {"default": "y"}),
            "attribute_class": (list(_uvp.CLASSES),),
            "attribute_name": _names("attrib", "vertex", "uv"),
            **{k: _sec("Transform", v) for k, v in {
                "fit_to_01": ("BOOLEAN", {"default": True}),
                "keep_aspect": ("BOOLEAN", {"default": True}),
                "fix_seams": ("BOOLEAN", {"default": True}),
                "translate_u": _f(0.0), "translate_v": _f(0.0),
                "rotate": _f(0.0, -360.0, 360.0, 1.0),
                "scale_u": _f(1.0), "scale_v": _f(1.0),
            }.items()},
            # pcg100 addition: Houdini UV Project's projector transform (Transformation tab) + U / V Range
            # + Toroidal Inner Radius. Off (default) = the original "centre on bounding box + Fit"
            **{k: _sec("Projector", v, gate=(k == "use_projector")) for k, v in {
                "use_projector": ("BOOLEAN", {"default": False}),
                "xform_order": (list(ops.XFORM_ORDERS),),
                "rotate_order": (list(ops.ROTATE_ORDERS),),
                "proj_translate_x": _f(0.0), "proj_translate_y": _f(0.0), "proj_translate_z": _f(0.0),
                "proj_rotate_x": _f(0.0, -360.0, 360.0, 1.0),
                "proj_rotate_y": _f(0.0, -360.0, 360.0, 1.0),
                "proj_rotate_z": _f(0.0, -360.0, 360.0, 1.0),
                "proj_scale_x": _f(1.0), "proj_scale_y": _f(1.0), "proj_scale_z": _f(1.0),
                "proj_pivot_x": _f(0.0), "proj_pivot_y": _f(0.0), "proj_pivot_z": _f(0.0),
                "u_range_min": _f(0.0), "u_range_max": _f(1.0),
                "v_range_min": _f(0.0), "v_range_max": _f(1.0),
                "inner_radius": _f(0.25, 0.0, 0.5, 0.01),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/uv"

    def run(self, geo, group, mode, axis, attribute_class, attribute_name,
            fit_to_01, keep_aspect, fix_seams, translate_u, translate_v,
            rotate, scale_u, scale_v, use_projector=False, xform_order="srt",
            rotate_order="xyz", proj_translate_x=0.0, proj_translate_y=0.0,
            proj_translate_z=0.0, proj_rotate_x=0.0, proj_rotate_y=0.0,
            proj_rotate_z=0.0, proj_scale_x=1.0, proj_scale_y=1.0,
            proj_scale_z=1.0, proj_pivot_x=0.0, proj_pivot_y=0.0,
            proj_pivot_z=0.0, u_range_min=0.0, u_range_max=1.0,
            v_range_min=0.0, v_range_max=1.0, inner_radius=0.25):
        proj = None
        if use_projector:
            proj = dict(translate=(proj_translate_x, proj_translate_y, proj_translate_z),
                        rotate=(proj_rotate_x, proj_rotate_y, proj_rotate_z),
                        scale=(proj_scale_x, proj_scale_y, proj_scale_z),
                        pivot=(proj_pivot_x, proj_pivot_y, proj_pivot_z),
                        xform_order=xform_order, rotate_order=rotate_order)
        return (_uvp.project(geo, mode, axis, attribute_class,
                             attribute_name, (translate_u, translate_v),
                             rotate, (scale_u, scale_v), fit_to_01,
                             keep_aspect, fix_seams, group, proj,
                             (u_range_min, u_range_max),
                             (v_range_min, v_range_max), inner_radius),)


class PCG_UVLayout:
    """
    Mirrors Houdini's UV Layout. Finds UV islands and arranges them in [0,1]².

    **"UV islands" are split by UV connectivity, not geometric connectivity.** Two faces sharing an edge geometrically does not mean
    they are connected in UV space -- the very definition of a seam is "connected geometrically but split in UV". The criterion is whether
    the corner uvs on both sides of a shared edge match. Splitting islands by geometric connectivity is a common mistake; the symptom is "after box projection
    the pack is still one lump".

    Packing uses **shelves + an outer binary search on scale**: optimal rectangle packing is NP-hard, but "does it fit at a given scale"
    is a cheap test (one O(n) shelf fill); wrapping it in a binary search for the largest feasible scale gives exactly
    the answer that maximises texel density.

    Rotate to Fit uses **rotating calipers** to find the minimum-area orientation -- the minimum-area bounding rectangle always has one side flush with
    some edge of the convex hull, so trying only hull edges is enough. Measured on a 35° diagonal strip, usage drops from 0.76 to 0.47.

    Method = raster: islands are rasterised into masks and nested by shape (all four 90° orientations tried), so triangle / L-shaped
    islands no longer each take a bounding box -- a decimated rock goes from 40% of the sheet to over 60%. Pack Resolution is the side length of the
    occupancy grid: larger is tighter and slower.

    Scale Mode: `uniform` gives all islands the same scale (relative sizes kept, consistent texel density, what baking
    wants); `individual` normalises each by its own long side before packing (sizes evened out, small islands don't blur).

    pcg100: `fixed` (Houdini's Fixed) scales by Fixed Scale as is without searching for the maximum; islands that don't fit are placed
    outside the target and go into the Nonpacked group; Island Rotation Step tries more orientations; with Pack Into = UDIM Tiles
    it packs into several tiles by Starting UDIM / Columns / Count (with Fixed, tiles are opened onward as needed).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only pack the islands these faces belong to"),
            "attribute_class": (list(_uvl.CLASSES),),
            "attribute_name": _names("attrib", "vertex", "uv"),
            "scale_mode": (list(_uvl.SCALE_MODES),),
            "padding": _f(0.01, 0.0, 0.25, 0.001),
            "rotate_to_fit": ("BOOLEAN", {"default": True}),
            # pcg84 additions at the end (widget indices of old workflows unchanged)
            "method": (list(_uvl.PACK_METHODS),),
            "pack_resolution": _i(256, 32, 2048),
            # pcg100 additions (Houdini UV Layout 3.0): Island Rotation Step, the scale value for Scale = Fixed,
            # Scale Islands to Match Their Surface Areas, Pack into UDIM Tiles, output groups / attributes
            "island_rotation": (list(_uvl.ROTATIONS),),
            "rotation_step": _f(90.0, 1.0, 360.0, 1.0),
            "rotation_divisions": _i(4, 1, 360),
            "fixed_scale": _f(1.0, 1e-6, 1e6, 0.01),
            "match_surface_area": ("BOOLEAN", {"default": False}),
            "pack_into": (list(_uvl.PACK_INTO),),
            "udim_start": _i(1001, 1001, 99999),
            "udim_columns": _i(10, 1, 100),
            "udim_count": _i(1, 1, 1000),
            "nonpacked_group": _names("group", "prim", "", "Empty = not written"),
            "island_attribute": _names("attrib", "prim", "", "Empty = not written"),
            "target_attribute": _names("attrib", "prim", "", "Empty = not written"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/uv"

    def run(self, geo, group, attribute_class, attribute_name, scale_mode,
            padding, rotate_to_fit, method="shelf", pack_resolution=256,
            island_rotation="auto", rotation_step=90.0, rotation_divisions=4,
            fixed_scale=1.0, match_surface_area=False, pack_into="unit_square",
            udim_start=1001, udim_columns=10, udim_count=1, nonpacked_group="",
            island_attribute="", target_attribute=""):
        return (_uvl.layout(geo, attribute_name, attribute_class, scale_mode,
                            padding, rotate_to_fit, group, method,
                            pack_resolution, island_rotation, rotation_step,
                            rotation_divisions, fixed_scale, match_surface_area,
                            pack_into, udim_start, udim_columns, udim_count,
                            nonpacked_group, island_attribute,
                            target_attribute),)


class PCG_UVTransform:
    """
    Mirrors Houdini's UV Transform. Translate / rotate / scale in UV space.

    With Per Island on, each island rotates about **its own centre** -- use it when you want to turn scattered islands by 90 degrees each,
    rather than have them orbit the atlas centre.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group(),
            "attribute_class": (list(_uvl.CLASSES),),
            "attribute_name": _names("attrib", "vertex", "uv"),
            "translate_u": _f(0.0), "translate_v": _f(0.0),
            "rotate": _f(0.0, -360.0, 360.0, 1.0),
            "scale_u": _f(1.0), "scale_v": _f(1.0),
            "pivot_u": _f(0.5), "pivot_v": _f(0.5),
            "per_island": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/uv"

    def run(self, geo, group, attribute_class, attribute_name, translate_u,
            translate_v, rotate, scale_u, scale_v, pivot_u, pivot_v,
            per_island):
        return (_uvl.transform(geo, attribute_name, attribute_class,
                               (translate_u, translate_v), rotate,
                               (scale_u, scale_v), (pivot_u, pivot_v),
                               per_island, group),)


class PCG_UVFlatten:
    """
    Mirrors Houdini's UV Flatten. LSCM conformal flattening -- the Lévy 2002 method, still
    the default UV unwrapping algorithm everywhere.

    Projection can only handle things that are "roughly a plane/cylinder/sphere". Arbitrary shapes need an optimisation: find a set of
    (u,v) such that each triangle mapped from 3D to 2D is **as close as possible to just rotation + scale, no shear**. The conformal condition is
    the Cauchy-Riemann equations, and they are **linear** -- so the whole thing is a sparse least-squares problem, not an iterative optimisation.

    **Seams don't require actually cutting the geometry.** The unknowns are not "points" but **wedges** (equivalence classes of corners): two corners
    belong to the same wedge iff they are on the same geometric point and the edge between them is not a seam. The two sides of a seam
    are naturally two wedges, each with its own (u,v). Not a single geometric point moves. This is also exactly why uv must be a vertex
    attribute.

    **Closed pieces can't be flattened** -- a sphere has no isometric planar unfolding (Gauss's Theorema Egregium); it's not an implementation problem.
    In that case the node raises an error telling you to select a loop of edges as a seam with Group Edges, instead of handing back a pile of overlapping uvs.

    The solver is a hand-written CGNR + Jacobi preconditioner (no scipy): M is stored as COO, a matrix product is two
    `bincount`s, and the normal equations MᵀM are **never assembled explicitly**. The initial guess is the projection onto the best-fit plane -- for developable
    surfaces (plane, cone, cylinder) that is already near the exact solution, saving more than ten times the time.

    Flattening Method (pcg100): `lscm` the original two-pin least squares; `scp` spectral conformal (Houdini 3.0's
    default, no pins, so the border isn't pulled crooked by pins); `abf` solves angles first then reconstructs (least area distortion, slowest).
    Houdini 3.0's menu only has SCP / ABF; LSCM is our retained original behaviour (default unchanged).

    Distortion Attribute writes a prim attribute: UV area / 3D area, divided by the global median.
    1 = texel density matches most places. Conformal maps preserve angles, not area, so it is never 1 everywhere anyway --
    it is for finding "which part is stretched absurdly".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "seam_group": _names("group", "edge", "",
                                 "Cut along these edges; empty = only the geometry's own borders"),
            "attribute_name": _names("attrib", "vertex", "uv"),
            "normalize": ("BOOLEAN", {"default": True}),
            **{k: _sec("Pack", v, gate=(k == "pack")) for k, v in {
                "pack": ("BOOLEAN", {"default": False}),
                "padding": _f(0.01, 0.0, 0.25, 0.001),
                "group": _group("When packing, only process the islands these faces belong to"),
            }.items()},
            **{k: _sec("Solver", v) for k, v in {
                "iterations": _i(2000, 1, 1 << 20),
                "tolerance": ("FLOAT", {"default": 1e-8, "min": 1e-14,
                                        "max": 1.0, "step": 1e-9}),
                "distortion_attribute": _names("attrib", "prim", ""),
            }.items()},
            # pcg84 addition at the end: a few ARAP rounds after LSCM (area preserving, even texel density)
            "arap_iterations": _i(0, 0, 200),
            # pcg100 additions (Houdini UV Flatten 3.0): Flattening Method, flatten only the faces in Group,
            # Preserve Seams, Vertex Pins (pinned to existing uv), Output Groups. Default = the original LSCM
            "method": (list(_uvf.METHODS),),
            "flatten_group": _group("Only flatten these faces; other faces keep their uv as is"),
            "preserve_seams": ("BOOLEAN", {"default": False}),
            "pin_group": _names("group", "point", "",
                                "Corners on these points stay pinned to their existing uv"),
            "output_seams": _names("group", "edge", "", "Empty = not written"),
            "output_constrained": _names("group", "prim", "", "Empty = not written"),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/uv"

    def run(self, geo, seam_group, attribute_name, normalize, pack, padding,
            group, iterations, tolerance, distortion_attribute,
            arap_iterations=0, method="lscm", flatten_group="",
            preserve_seams=False, pin_group="", output_seams="",
            output_constrained=""):
        return (_uvf.flatten(geo, seam_group, attribute_name, "vertex",
                             iterations, tolerance, normalize, pack, padding,
                             distortion_attribute, group, arap_iterations,
                             method, flatten_group, preserve_seams, pin_group,
                             output_seams, output_constrained),)


class PCG_UVAutoSeams:
    """
    Finds seams automatically and writes them as an edge group, to feed UV Flatten's Seam Group.

    After LSCM last round, UV unwrapping still lacked this step: seams had to be given as an edge group by hand. In Houdini you can
    click edges in the viewport; ComfyUI has no such interaction -- so automatic seams are not a nice-to-have, they are the piece that makes the whole chain
    usable.

    **Seams have to satisfy two completely different properties at once:**

      1. Look good -- cut along creases, separate high-curvature areas, low distortion after flattening (heuristic)
      2. Be flattenable -- after cutting every piece **must be a disk**, otherwise LSCM has no solution at all (hard constraint)

    So the flow is: pick candidate seams first, then complete them with a topological algorithm. With Make Disks on, every piece is **guaranteed** to be a disk;
    the criterion is the Euler characteristic χ = V − E + F == 1 (V counts wedges, seam edges count twice), not "looks like one".

    Completion uses **tree-cotree**: cutting every edge outside the dual spanning tree always yields a disk (the faces form a tree),
    then repeatedly prune branches "connected by only one edge" to give most of them back. On a sphere it gets pruned to nothing -- that's not
    a bug, the sphere really needs one opening: first find the longest path inside, mark its two ends as unprunable,
    and after pruning exactly that path is left, effectively cutting a meridian automatically.

    Mode: `angle` cuts only creases; `charts` splits into charts by normal cone (the Smart UV Project approach) and cuts chart borders;
    `both` does both. Smaller Cone Angle = more charts, lower distortion -- measured on a sphere, the 90th percentile of distortion
    is 9.6 at 80° and drops to 1.8 at 45°.

    pcg100: `existing_islands` added at the end of Mode (Houdini's Splitting = Existing Islands: edges where existing uv
    is split are the starting point); Include / Exclude edges and Island Attribute match Houdini's Enforce / Avoid cuts.
    Houdini's default Curvature Based (grains + merging) is a different algorithm and is not faked.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only look for seams on these faces"),
            "output_group": _names("group", "edge", "seams"),
            "mode": (list(_uvs.MODES), {"default": "both"}),
            "min_angle": _f(45.0, 0.0, 180.0, 1.0),
            "cone_angle": _f(66.0, 1.0, 180.0, 1.0),
            "make_disks": ("BOOLEAN", {"default": True}),
            "output_chart_attribute": _names("attrib", "prim", ""),
            # pcg100 additions (Houdini UV Autoseam): Enforce / Avoid cuts, Splitting = Existing Islands
            "include_edges": _names("group", "edge", "", "These edges are always seams"),
            "exclude_edges": _names("group", "edge", "", "These edges are never seams"),
            "island_attribute": _names("attrib", "prim", "",
                                       "Integer attribute: cut between adjacent faces with different values"),
            "uv_attribute": _names("attrib", "vertex", "uv"),
            "connectivity_tolerance": ("FLOAT", {"default": 1e-6, "min": 0.0,
                                                 "max": 1.0, "step": 1e-6}),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/uv"

    def run(self, geo, group, output_group, mode, min_angle, cone_angle,
            make_disks, output_chart_attribute, include_edges="",
            exclude_edges="", island_attribute="", uv_attribute="uv",
            connectivity_tolerance=1e-6):
        return (_uvs.auto_seams(geo, output_group, mode, min_angle,
                                cone_angle, make_disks, group,
                                output_chart_attribute, include_edges,
                                exclude_edges, island_attribute, uv_attribute,
                                connectivity_tolerance),)


class PCG_PolyFill:
    """
    Mirrors Houdini's PolyFill. Fills in boundary loops.

    Clip, Blast and Delete all leave openings, and almost every later step wants closed geometry: volume computation
    needs it closed, booleans need it closed, and Voronoi fragments without their openings filled are just a pile of paper sheets.

    **The direction of a boundary loop determines the direction of the fill face, and it is reversed.** Boundary half-edges follow the winding of the existing faces;
    for the fill face to agree with neighbouring normals it has to be strung the other way. Getting this wrong raises no error and the face count is right, only
    the filled patch's normals point inward -- it renders as a black hole and the volume has the opposite sign. So the tests directly check "the volume after filling equals
    the analytic value".

    Three fill methods: `ngon` caps with one polygon (no new points, first choice for planar holes); `fan` adds a point at the hole centre
    and makes a fan (use it for non-planar holes, where ngon would twist); `triangles` ear clipping (no new points, cuts concave holes correctly too).

    With Max Sides > 0, only holes with at most that many edges are filled -- "patch the small holes, don't seal the model's whole opening".
    With Planar Tolerance >= 0, only holes that are flat enough are filled.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "mode": (list(_pfl.MODES),),
            "max_sides": _i(0, 0, 1 << 16),
            "planar_tolerance": ("FLOAT", {"default": -1.0, "min": -1.0,
                                           "max": 1e6, "step": 0.001,
                                           "tooltip": "-1 = ignore flatness"}),
            "output_group": _names("group", "prim", ""),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, mode, max_sides, planar_tolerance, output_group):
        return (_pfl.fill(geo, mode, max_sides, output_group,
                          planar_tolerance),)


class PCG_Triangulate2D:
    """
    Mirrors Houdini's Triangulate 2D: Delaunay / constrained Delaunay triangulation of a planar point set.

    Division of labour with PolyFill: PolyFill "caps the hole", fan or ear clipping, with ugly triangle shapes;
    this one "triangulates **well**" -- Delaunay maximises the minimum angle over all triangulations,
    the kind of mesh finite elements, terrain and cloth initial meshes all want.

    **Delaunay is not hand-written.** It uses parabolic lifting: lift (x,y) to (x,y,x²+y²);
    the lower convex hull's triangles projected back are exactly Delaunay, and "point inside the circumcircle" and "point below the plane"
    after lifting are **the same determinant**. So it directly reuses the already-tested 3D convex hull piece;
    the result is algebraically exact, not approximate -- measured on 400 points with incircle computed against all points,
    the worst value is exactly 0.

    There are two degeneracies on the lifting path that must be blocked; the first version hit both:

    - **Cocircular points**. Coplanar after lifting <=> the original points are cocircular, and squares, rectangles, rhombi, any
      regular polygon and isosceles trapezoids all have four cocircular points; with exactly 3 points it is guaranteed. The hull can't form a tetrahedron,
      so the most basic use, "fill a square with triangles", returned empty geometry outright.
      Now handled separately: any triangulation of a cocircular point set is Delaunay, so just fan it in angular order.
    - **Hull tolerance**. The hull's default tol=1e-6 is a disaster for Delaunay: nearly cocircular points
      are only 1e-8 from that face, get treated as "on the face" and swallowed, **vanishing from the triangulation without an error**.
      Measured: 400 points in two-scale clusters could lose 169. Now pinned to 1e-12.

    Constraint edges (Constrain = Input Polygons) guarantee the input polygons' edges appear in the output;
    concave outlines only fill correctly because of them -- Delaunay triangulates the **convex hull**, it doesn't know your outline.
    Inside/outside uses **region depth parity** (depth +1 across each constraint edge), so holes and multi-level nesting
    are all correct: 4×4 minus 2×2 gives 12, add a 1×1 island inside and it gives 8.

    Max Circumradius / Max Edge Length are alpha pruning, used to get a **concave hull** from a point cloud:
    Delaunay's outer contour is always the convex hull; only deleting "too large" triangles yields a concave shape.
    Both thresholds treat 0 = no pruning -- if 0 meant "delete everything", the default parameters would output empty geometry.

    **Vertex and primitive attributes are not carried over**: the output triangles are newly built and have no correspondence
    with the input vertices/faces; copying by index would only copy wrong values. Point attributes and point groups are kept as is (no point number changes).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only triangulate these points"),
            "plane": (list(_t2d.PLANE_MODES),),
            "constrain": (list(_t2d.CONSTRAIN_MODES),),
            "region": (list(_t2d.REGION_MODES),),
            "max_circumradius": _f(0.0, 0.0, 1e6, 0.01),
            "max_edge_length": _f(0.0, 0.0, 1e6, 0.01),
            "keep_input_geometry": ("BOOLEAN", {"default": False}),

            **{k: _sec("Plane", v) for k, v in {
                "plane_origin_x": _f(0.0), "plane_origin_y": _f(0.0),
                "plane_origin_z": _f(0.0),
                "plane_normal_x": _f(0.0), "plane_normal_y": _f(1.0),
                "plane_normal_z": _f(0.0),
                "plane_distance": _f(0.0),
            }.items()},
            **{k: _sec("Local Attributes", v) for k, v in {
                "constrain_group": _names(
                    "edgegroup", "edge", "",
                    "With Constrain = Edge Group, take constraint edges from this edge group"),
                "border_group": _names(
                    "edgegroup", "edge", "", "Write the output border edges into this edge group"),
                "constrained_group": _names(
                    "edgegroup", "edge", "", "Write the constraint edges into this edge group"),
                "fuse_tolerance": _f(1e-6, 0.0, 1e3, 1e-6),
                "hull_tolerance": _f(1e-12, 0.0, 1e-3, 1e-12),
                "on_failure": (list(_pex.FAILURE),),
            }.items()},
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, group, plane, constrain, region, max_circumradius,
            max_edge_length, keep_input_geometry, plane_origin_x,
            plane_origin_y, plane_origin_z, plane_normal_x, plane_normal_y,
            plane_normal_z, plane_distance, constrain_group, border_group,
            constrained_group, fuse_tolerance, hull_tolerance, on_failure):
        return (_t2d.triangulate2d(
            geo, group, plane,
            (plane_origin_x, plane_origin_y, plane_origin_z),
            (plane_normal_x, plane_normal_y, plane_normal_z), plane_distance,
            constrain, constrain_group, region, max_circumradius,
            max_edge_length, fuse_tolerance, hull_tolerance,
            keep_input_geometry, border_group, constrained_group,
            on_failure),)


class PCG_Voronoi2D:
    """
    Planar Voronoi diagram -- the dual of Delaunay. Scatter points in, get blocks out.

    Division of labour with Voronoi Fracture (PCG): that one is 3D **fracturing** (half-space cuts of a solid,
    producing fragments); this one is 2D **partitioning** (producing cell polygons and their border lines).
    The city-generation chain uses this one: Scatter -> Voronoi 2D (edges) ->
    PolyPath -> PolyExpand2D for road width -> the blocks are what's in between.

    **It does not "connect circumcentres into loops".** The textbook way connects the circumcentres of the triangles around each site in angular order,
    but cells of sites on the convex hull are **unbounded**: you'd need rays to infinity, intersection with the boundary, and handling circumcentres
    outside the boundary -- a pile of degenerate branches. Here half-plane clipping is used instead: the cell of site p = the boundary region
    left after one cut by the perpendicular bisector between p and each of its **Delaunay neighbours**.
    It rests on the theorem that a Voronoi cell is uniquely determined by its Delaunay neighbours, so on average only 6 cuts are needed.
    The benefit is that **unbounded cells never exist**; sites on the hull and inside take the same code path.

    The boundary region **must be convex** -- half-plane clipping only holds for convex polygons. So
    with Boundary = polygon convexity is checked and an error raised, instead of silently giving a self-intersecting result.
    For a concave boundary: compute with bounds first, then clip with Boolean / Clip.

    Output points are Voronoi vertices (new points) with no correspondence to the sites, so point attributes are not carried over;
    each cell gets a `site` prim attribute pointing back to the site's point number. Vertices shared by adjacent cells are fused,
    otherwise the output is a pile of independent polygons that PolyPath / Join can't connect --
    and "connecting into a road network" is exactly its main use.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only use these points as sites"),
            "plane": (list(_t2d.PLANE_MODES),),
            "output": (list(_v2d.OUTPUTS),),
            "boundary": (list(_v2d.BOUNDS),),
            "padding": _f(0.0, 0.0, 1e6, 0.01),
            **{k: _sec("Plane", v) for k, v in {
                "plane_origin_x": _f(0.0), "plane_origin_y": _f(0.0),
                "plane_origin_z": _f(0.0),
                "plane_normal_x": _f(0.0), "plane_normal_y": _f(1.0),
                "plane_normal_z": _f(0.0),
                "plane_distance": _f(0.0),
            }.items()},
            **{k: _sec("Local Attributes", v) for k, v in {
                "site_attribute": _names(
                    "attrib", "prim", "site", "Write the site's point number back onto each cell"),
                "interior_group": _names(
                    "group", "prim", "interior",
                    "With output=edges, the edges shared by two cells"),
                "fuse_tolerance": _f(1e-6, 0.0, 1e3, 1e-6),
                "hull_tolerance": _f(1e-12, 0.0, 1e-3, 1e-12),
                "on_failure": (list(_pex.FAILURE),),
            }.items()},
        }, "optional": {"bounds_geo": (GEO,)}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/scatter"

    def run(self, geo, group, plane, output, boundary, padding,
            plane_origin_x, plane_origin_y, plane_origin_z,
            plane_normal_x, plane_normal_y, plane_normal_z, plane_distance,
            site_attribute, interior_group, fuse_tolerance, hull_tolerance,
            on_failure, bounds_geo=None):
        return (_v2d.voronoi2d(
            geo, group, plane,
            (plane_origin_x, plane_origin_y, plane_origin_z),
            (plane_normal_x, plane_normal_y, plane_normal_z), plane_distance,
            output, boundary, padding, bounds_geo, fuse_tolerance,
            hull_tolerance, site_attribute, interior_group, on_failure),)


class PCG_FileCache:
    """
    Geometry disk cache -- mirrors Houdini's File Cache SOP.

    Geometry is an object living in the Python process and **can't go into the workflow json**.
    So after closing and reopening ComfyUI, the whole chain has to be recomputed from scratch. With a long chain (booleans, decimation,
    UV unwrapping, things that are slow to begin with) every session start means waiting several minutes, though most of it hasn't changed.
    Compute once and write to disk, read from disk afterwards.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    When reading from disk **upstream really is not executed** -- thanks to lazy inputs
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    This is the whole reason the node saves time, and the easiest place to get it wrong. ComfyUI only drives evaluation
    from output nodes; a node "deciding to read from disk" does not stop its upstream from being computed -- in which case
    the cache would be useless, just writing an extra file for nothing.

    So the `geo` input is declared `{"lazy": True}` and `check_lazy_status` is implemented:
    in the read-from-disk case it returns an empty list, and ComfyUI **doesn't touch upstream at all**.
    (`PCG_Switch` skips unselected branches with the same mechanism.)

    Mode:
        auto    read if the file exists, otherwise compute once and write it out -- use this day to day
        write   always recompute and overwrite. Use it to refresh the cache after changing upstream
        read    always read from disk. Errors if the file doesn't exist, and **never** computes upstream

    In the path, `$F` / `$F4` are replaced by the frame number (`$F4` zero-pads to 4 digits, otherwise file names sort wrongly),
    `$V` by the version number. Use with For-Each Frame Block for per-frame caches.

    The format is npz + a JSON manifest, **no pickle** -- cache files travel with the project
    and get copied around, and `allow_pickle` is equivalent to executing arbitrary code from the file; a geometry cache shouldn't
    have that much power. The cost is that prim_data only accepts numpy arrays (measured: the whole repo has only the voxels /
    knots uses, all arrays).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mode": (list(_gcache.MODES),),
            "file": ("STRING", {
                "default": "pcg_cache/geo_$F4.npz",
                "tooltip": "Relative to ComfyUI's output directory; $F/$F4 frame number, $V version"}),
            "frame": _i(0, -1000000, 1000000),
            "version": _i(1, 0, 100000),
            "compress": ("BOOLEAN", {"default": True}),
            "reload": ("INT", {
                "default": 0, "min": 0, "max": 0xffffffff,
                "tooltip": "Change this number to force one re-read / re-write"}),
        }, "optional": {
            # lazy is the core of this node: when reading from disk it **doesn't touch upstream at all**. See the class docstring.
            "geo": (GEO, {"lazy": True}),
        }}
    RETURN_TYPES = (GEO, "STRING"); RETURN_NAMES = ("geo", "path")
    FUNCTION = "run"; CATEGORY = CAT + "/output"

    def check_lazy_status(self, mode, file, frame, version, compress,
                          reload, geo=None):
        # Reading from disk -> request no upstream inputs at all, so ComfyUI never computes them
        return [] if _gcache.will_read(mode, file, frame, version) else ["geo"]

    def run(self, mode, file, frame, version, compress, reload, geo=None):
        return _gcache.run_cache(mode, file, frame, version, compress, geo)


class PCG_VoronoiFracture:
    """
    Mirrors Houdini's Voronoi Fracture. Cuts geometry into fragments by seed points -- the cornerstone of procedural destruction.

    **It doesn't compute a 3D Voronoi diagram.** That (and its dual, the Delaunay tetrahedralisation) has to seriously
    deal with degeneracies, cospherical points and numerical robustness; it's a sizeable project. But the diagram isn't needed here, only the fragments:
    "closer to i than to j" is one half-space -- the side of the perpendicular bisector plane of i, j facing i. So

        cell i = original geometry ∩ (half-spaces for all j)

    and existing Clip can just cut it one slice at a time. **Rephrasing turned a computational geometry problem into
    a chain of existing operations.**

    Pruning is **exact**, not heuristic: cut by j in order of distance, track R, the farthest distance from i on the current fragment;
    once `d_ij / 2 >= R` that plane can't reach it, and later j are only farther, so stop.
    Measured: cutting a sphere with 200 seeds, each cell uses only 13 planes on average (not 199).

    **Openings are filled after every cut**, and only loops lying on that cut's plane are filled -- so closed inputs give
    watertight pieces (volume measured exactly conserved), while open inputs (e.g. a Grid) stay open after cutting and don't get sealed.
    Filled faces go into Interior Group, so the inner surfaces can get their own material directly.

    All fragments are output merged together, distinguished by the name / piece attributes; feed For-Each Begin's
    piece mode to process them piece by piece.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "points": (GEO,),
            **{k: _sec("Interior", v, gate=(k == "cap")) for k, v in {
                "cap": ("BOOLEAN", {"default": True}),
                "cap_mode": (list(_pfl.MODES),),
                "interior_group": _names("group", "prim", "interior"),
                "cap_tolerance": _f(1e-5, 0.0, 1.0, 1e-6),
            }.items()},
            **{k: _sec("Naming", v) for k, v in {
                "name_attribute": _names("attrib", "prim", "name"),
                "piece_attribute": _names("attrib", "prim", "piece"),
                "name_prefix": ("STRING", {"default": "piece"}),
                "max_pieces": _i(4096, 1, 1 << 16),
            }.items()},
            # pcg100 s9 additions (placed last, old workflow indices unchanged; defaults = old behaviour)
            "group": _group("Only cut these faces; faces outside the group are appended as is"),
            "name_mode": (list(_vor.NAME_MODES),),
            "fracture_namespace": ("STRING", {"default": ""}),
            "compute_interior_normals": ("BOOLEAN", {"default": False}),
            "interior_cusp_angle": _f(40.0, 0.0, 180.0, 1.0),
            "exterior_normals": (list(_vor.EXTERIOR_NORMALS),),
            "exterior_cusp_angle": _f(60.0, 0.0, 180.0, 1.0),
            "cell_point_attribute": ("STRING", {"default": ""}),
            "clip_piece_attribute": ("STRING", {"default": ""}),
            "exterior_group": ("STRING", {"default": ""}),
            "merge_groups": ("BOOLEAN", {"default": True}),
            "copy_cell_attributes": ("STRING", {"default": ""}),
            "copy_to_points": ("BOOLEAN", {"default": True}),
            "copy_to_prims": ("BOOLEAN", {"default": False}),
            "cut_plane_offset": _f(0.0, 0.0),
            "connectivity_partition": (list(_vor.PARTITIONS),),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, points, cap, cap_mode, interior_group, cap_tolerance,
            name_attribute, piece_attribute, name_prefix, max_pieces,
            group="", name_mode="overwrite", fracture_namespace="",
            compute_interior_normals=False, interior_cusp_angle=40.0,
            exterior_normals="preserve", exterior_cusp_angle=60.0,
            cell_point_attribute="", clip_piece_attribute="", exterior_group="",
            merge_groups=True, copy_cell_attributes="", copy_to_points=True,
            copy_to_prims=False, cut_plane_offset=0.0, connectivity_partition="none"):
        opts = dict(group=group, name_mode=name_mode, namespace=fracture_namespace,
                    cell_point_attrib=cell_point_attribute,
                    clip_piece_attrib=clip_piece_attribute, exterior_group=exterior_group,
                    merge_groups=merge_groups, partition=connectivity_partition,
                    plane_offset=cut_plane_offset, interior_normals=compute_interior_normals,
                    interior_cusp=interior_cusp_angle, exterior_normals=exterior_normals,
                    exterior_cusp=exterior_cusp_angle, copy_attribs=copy_cell_attributes,
                    copy_to_points=copy_to_points, copy_to_prims=copy_to_prims)
        return (_vor.fracture(geo, points, cap, cap_mode, interior_group,
                              name_attribute, piece_attribute, name_prefix,
                              cap_tolerance, max_pieces, opts),)


class PCG_ScatterVolume:
    """
    Scatters points **inside** closed geometry. Mirrors Houdini's Scatter + Volume.

    Only after finishing Voronoi Fracture last round did we notice the chain was broken: Scatter (PCG) scatters **surface** points,
    and using them as Voronoi seeds puts every cell against the shell, cutting out a pile of shell shards instead of solid chunks.

    `random` scatters in the bounding box and discards points outside the volume (rejection sampling); the distribution is truly random -- some sparse, some dense,
    Voronoi pieces vary widely in size, like natural breakage; `grid` is a jittered regular lattice, pieces are similar in size,
    like man-made cuts.

    Hit rate = volume / bounding box volume, which for a thin slanted rod can be a few percent, so it **estimates while scattering and
    tops up in batches**, rather than scattering count/hit-rate at once -- the hit rate isn't known in advance, and a wrong estimate gives either too few
    or ten times too many.

    With Min Distance > 0, Poisson-disk filtering: grid dart throwing, O(n) not O(n²).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Only use the volume enclosed by these faces"),
            "mode": (list(_vsc.MODES),),
            "count": _i(100, 0, 1 << 22),
            "spacing": _f(0.1, 1e-6, 1e6, 0.01),
            "jitter": _f(1.0, 0.0, 1.0, 0.01),
            "min_distance": _f(0.0, 0.0, 1e6, 0.01),
            "rand_seed": _i(0, 0, 1 << 31),
            "ray_directions": _i(3, 1, 3),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("points",)
    FUNCTION = "run"; CATEGORY = CAT + "/scatter"

    def run(self, geo, group, mode, count, spacing, jitter, min_distance,
            rand_seed, ray_directions):
        return (_vsc.scatter_volume(geo, mode, count, spacing, jitter,
                                    min_distance, rand_seed, group,
                                    ray_directions),)


class PCG_VoronoiCluster:
    """
    Glues Voronoi fragments into larger chunks. Mirrors the Cluster of Houdini's Voronoi Fracture.

    Pure Voronoi cuts are **too regular**: every piece is convex and similar in size, like crystals rather than broken bricks. Real
    breakage is "big chunks + small chunks + debris", and big chunks have concave outlines. The approach isn't a different cutting method but
    **cut finer, then glue neighbours back together** -- cut 200 pieces, cluster them into 12 groups, and the glued chunks come out naturally concave
    with polyline borders.

    "Glue back" = fuse points + delete pairs of faces with **exactly the same point set** (those are the internal walls of a cluster, two back to back).
    Fusing is the prerequisite: without it the two faces use two different sets of point numbers and the keys don't match. Measured: 60 pieces into
    6 clusters, face count 681 → 417, still watertight, volume exactly conserved.

    The points on the walls remain (becoming extra vertices on the chunk surfaces); follow with Dissolve (PCG)'s
    Remove Inline Points to clean them up -- that node already does it right, no reinventing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "mode": (list(_clu.MODES),),
            "cluster_count": _i(8, 1, 1 << 16),
            "piece_attribute": _names("attrib", "prim", "piece"),
            "merge_pieces": ("BOOLEAN", {"default": True}),
            "fuse_tolerance": _f(1e-5, 0.0, 1.0, 1e-6),
            "cluster_attribute": _names("attrib", "prim", "cluster"),
            "name_attribute": _names("attrib", "prim", "name"),
            "name_prefix": ("STRING", {"default": "cluster"}),
            "rand_seed": _i(0, 0, 1 << 31),
        }, "optional": {"points": (GEO,)}}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/modify"

    def run(self, geo, mode, cluster_count, piece_attribute, merge_pieces,
            fuse_tolerance, cluster_attribute, name_attribute, name_prefix,
            rand_seed, points=None):
        return (_clu.cluster(geo, mode, cluster_count, points,
                             piece_attribute, name_attribute, name_prefix,
                             cluster_attribute, merge_pieces, fuse_tolerance,
                             rand_seed),)


class PCG_GroupInside:
    """
    Builds a group by "inside the second geometry input or not". Mirrors the Bounding Object of Houdini's Group SOP.

    The test is ray parity: shoot a ray from the point in one direction, count how many times it crosses the surface; odd means inside. The implementation reuses
    `spatial.ray_cast` -- it only returns the nearest hit, so **after a hit the origin is moved slightly past the hit point
    and the ray is cast again**, until it misses. No need to build a separate "return all hits" intersection routine.

    **Ray Directions defaults to 3.** When a ray grazes exactly an edge or a vertex, that crossing gets counted as
    0 or 2, flipping the parity; on axis-aligned meshes this is not a rare event. Three uncorrelated
    oblique directions vote, and the chance of all hitting the same degenerate spot is negligible.

    (A pitfall worth recording: those three directions must not have small integer ratios. The first version used (1,1,1)/√3,
    which is exactly a cube's body diagonal; shot from the centre it hits a vertex exactly, bouncing at that corner 64 times
    without getting out.)
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "volume": (GEO,),
            "cls": (["point", "prim"],),
            "group_name": _names("group", "point", "inside"),
            "invert": ("BOOLEAN", {"default": False}),
            "ray_directions": _i(3, 1, 3),
        }}
    RETURN_TYPES = (GEO,); RETURN_NAMES = ("geo",)
    FUNCTION = "run"; CATEGORY = CAT + "/group"

    def run(self, geo, volume, cls, group_name, invert, ray_directions):
        nm = str(group_name).strip()
        if not nm:
            raise ValueError("Group Name is empty.")
        if geo is None:
            return (Geometry(),)
        Q = (geo.get(POINT, "P") if cls == "point"
             else ops.prim_centers(geo))
        if Q is None or not len(Q):
            g = geo.copy(); g.set_group(cls, nm, np.zeros(geo.count(cls), bool))
            return (g,)
        m = _ins.inside_mesh(Q, volume, "", ray_directions)
        g = geo.copy()
        g.set_group(cls, nm, ~m if invert else m)
        return (g,)


NODE_CLASS_MAPPINGS = {
    "PCG_Grid": PCG_Grid, "PCG_Box": PCG_Box, "PCG_Sphere": PCG_Sphere,
    "PCG_Tube": PCG_Tube, "PCG_Line": PCG_Line, "PCG_Curve": PCG_Curve,
    "PCG_Torus": PCG_Torus,
    "PCG_Transform": PCG_Transform, "PCG_Merge": PCG_Merge,
    "PCG_Convert": PCG_Convert, "PCG_Carve": PCG_Carve,
    "PCG_ImportMesh": PCG_ImportMesh,
    "PCG_FromJSON": PCG_FromJSON, "PCG_GeoToJSON": PCG_GeoToJSON,
    "PCG_Reverse": PCG_Reverse, "PCG_Resample": PCG_Resample,
    "PCG_Sort": PCG_Sort,
    "PCG_Skin": PCG_Skin, "PCG_Boolean": PCG_Boolean,
    "PCG_Sweep": PCG_Sweep,
    "PCG_PolyExtrude": PCG_PolyExtrude, "PCG_PolyBevel": PCG_PolyBevel,
    "PCG_Normal": PCG_Normal, "PCG_Fuse": PCG_Fuse,
    "PCG_Add": PCG_Add, "PCG_Facet": PCG_Facet,
    "PCG_Divide": PCG_Divide, "PCG_Clip": PCG_Clip,
    "PCG_Split": PCG_Split,
    "PCG_GroupCreate": PCG_GroupCreate, "PCG_GroupPromote": PCG_GroupPromote,
    "PCG_GroupEdges": PCG_GroupEdges, "PCG_EdgeGroupPromote": PCG_EdgeGroupPromote,
    "PCG_Blast": PCG_Blast, "PCG_Connectivity": PCG_Connectivity,
    "PCG_Smooth": PCG_Smooth,
    "PCG_AttribPromote": PCG_AttribPromote, "PCG_AttribDelete": PCG_AttribDelete,
    "PCG_GroupDelete": PCG_GroupDelete, "PCG_Switch": PCG_Switch,
    "PCG_Scatter": PCG_Scatter, "PCG_CopyToPoints": PCG_CopyToPoints,
    "PCG_AttribTransfer": PCG_AttribTransfer, "PCG_Ray": PCG_Ray,
    "PCG_PolyExpand2D": PCG_PolyExpand2D, "PCG_Refine": PCG_Refine,
    "PCG_PointJitter": PCG_PointJitter,
    "PCG_ConvertLine": PCG_ConvertLine,
    "PCG_PolyPath": PCG_PolyPath, "PCG_Join": PCG_Join,
    "PCG_AttribNoise": PCG_AttribNoise,
    "PCG_Measure": PCG_Measure,
    "PCG_AttribCreate": PCG_AttribCreate, "PCG_AttribCopy": PCG_AttribCopy,
    "PCG_AttribRename": PCG_AttribRename, "PCG_AttribCast": PCG_AttribCast,
    "PCG_AttribRandomize": PCG_AttribRandomize,
    "PCG_AttribBlur": PCG_AttribBlur,
    "PCG_AttribInterpolate": PCG_AttribInterpolate,
    "PCG_AttribAdjust": PCG_AttribAdjust, "PCG_Delete": PCG_Delete,
    "PCG_GroupExpand": PCG_GroupExpand, "PCG_AttribFade": PCG_AttribFade,
    "PCG_Subdivide": PCG_Subdivide, "PCG_Dissolve": PCG_Dissolve,
    "PCG_EdgeDivide": PCG_EdgeDivide, "PCG_LoopCut": PCG_LoopCut,
    "PCG_PolyReduce": PCG_PolyReduce,
    "PCG_UVProject": PCG_UVProject, "PCG_UVLayout": PCG_UVLayout,
    "PCG_UVTransform": PCG_UVTransform,
    "PCG_UVFlatten": PCG_UVFlatten,
    "PCG_UVAutoSeams": PCG_UVAutoSeams,
    "PCG_PolyFill": PCG_PolyFill,
    "PCG_Triangulate2D": PCG_Triangulate2D,
    "PCG_Voronoi2D": PCG_Voronoi2D,
    "PCG_FileCache": PCG_FileCache,
    "PCG_VoronoiFracture": PCG_VoronoiFracture,
    "PCG_ScatterVolume": PCG_ScatterVolume,
    "PCG_VoronoiCluster": PCG_VoronoiCluster,
    "PCG_GroupInside": PCG_GroupInside,
    "PCG_ConvexHull": PCG_ConvexHull, "PCG_Bound": PCG_Bound,
    "PCG_ConvexDecompose": PCG_ConvexDecompose,
    "PCG_FractureDetail": PCG_FractureDetail,
    "PCG_Deform": PCG_Deform, "PCG_SoftTransform": PCG_SoftTransform,
    "PCG_Spherify": PCG_Spherify, "PCG_Ends": PCG_Ends,
    "PCG_Peak": PCG_Peak, "PCG_Mirror": PCG_Mirror,
    "PCG_ExplodedView": PCG_ExplodedView,
    "PCG_COPNoise": PCG_COPNoise, "PCG_COPShape": PCG_COPShape,
    "PCG_COPGradient": PCG_COPGradient,
    "PCG_COPConstant": PCG_COPConstant,
    "PCG_COPComposite": PCG_COPComposite,
    "PCG_COPBlur": PCG_COPBlur, "PCG_COPResize": PCG_COPResize,
    "PCG_COPImport": PCG_COPImport, "PCG_COPExport": PCG_COPExport,
    "PCG_COPToDevice": PCG_COPToDevice, "PCG_COPInfo": PCG_COPInfo,
    "PCG_COPTransform": PCG_COPTransform, "PCG_COPFlip": PCG_COPFlip,
    "PCG_COPCrop": PCG_COPCrop, "PCG_COPTile": PCG_COPTile,
    "PCG_COPDistort": PCG_COPDistort,
    "PCG_COPLevels": PCG_COPLevels, "PCG_COPRemap": PCG_COPRemap,
    "PCG_COPQuantize": PCG_COPQuantize, "PCG_COPFit": PCG_COPFit,
    "PCG_COPLuminance": PCG_COPLuminance,
    "PCG_COPMorph": PCG_COPMorph, "PCG_COPEdge": PCG_COPEdge,
    "PCG_COPSharpen": PCG_COPSharpen, "PCG_COPMedian": PCG_COPMedian,
    "PCG_COPSDFFromMask": PCG_COPSDFFromMask,
    "PCG_COPHeightToNormal": PCG_COPHeightToNormal,
    "PCG_COPNormalToHeight": PCG_COPNormalToHeight,
    "PCG_COPHeightToAO": PCG_COPHeightToAO,
    "PCG_COPHeightToShadow": PCG_COPHeightToShadow,
    "PCG_COPRefractFromHeight": PCG_COPRefractFromHeight,
    "PCG_COPHeightToCaustics": PCG_COPHeightToCaustics,
    "PCG_COPCombineNormals": PCG_COPCombineNormals,
    "PCG_COPConvertNormal": PCG_COPConvertNormal,
    "PCG_COPErosion": PCG_COPErosion,
    "PCG_COPSlope": PCG_COPSlope,
    "PCG_COPCurvature": PCG_COPCurvature,
    "PCG_COPStatistics": PCG_COPStatistics,
    "PCG_COPHistogram": PCG_COPHistogram,
    "PCG_COPSegment": PCG_COPSegment,
    "PCG_COPCompare": PCG_COPCompare,
    "PCG_COPMaskByFeature": PCG_COPMaskByFeature,
    "PCG_COPTerrace": PCG_COPTerrace,
    "PCG_COPThermalErosion": PCG_COPThermalErosion,
    "PCG_COPHeightfieldToMesh": PCG_COPHeightfieldToMesh,
    "PCG_COPFlowAccumulation": PCG_COPFlowAccumulation,
    "PCG_COPStreamPower": PCG_COPStreamPower,
    "PCG_COPHydraulicErosion": PCG_COPHydraulicErosion,
    "PCG_COPSplatMap": PCG_COPSplatMap,
    "PCG_RegionalPrompt": PCG_RegionalPrompt,
    "PCG_COPHeightfieldFromDepth": PCG_COPHeightfieldFromDepth,
    "PCG_RenderPass": PCG_RenderPass,
    "PCG_ControlImage": PCG_ControlImage,
    "PCG_IDMasks": PCG_IDMasks,
    "PCG_AttribFromMap": PCG_AttribFromMap,
    "PCG_AttribFromCamera": PCG_AttribFromCamera,
    "PCG_DisplaceFromMap": PCG_DisplaceFromMap,
    "PCG_ScatterFromMap": PCG_ScatterFromMap,
    "PCG_Trace": PCG_Trace,
    "PCG_Camera": PCG_Camera,
    "PCG_TextureRender": PCG_TextureRender,
    "PCG_UVBackproject": PCG_UVBackproject,
    "PCG_UVResolve": PCG_UVResolve,
    "PCG_CameraPath": PCG_CameraPath,
    "PCG_RenderSequence": PCG_RenderSequence,
    "PCG_MotionVectors": PCG_MotionVectors,
    "PCG_COPWarp": PCG_COPWarp,
    "PCG_SequenceExport": PCG_SequenceExport,
    "PCG_SequenceImport": PCG_SequenceImport,
    "PCG_SequencePick": PCG_SequencePick,
    "PCG_CameraPick": PCG_CameraPick,
    "PCG_GeoSequencePick": PCG_GeoSequencePick,
    "PCG_TimeBlend": PCG_TimeBlend, "PCG_Trail": PCG_Trail,
    "PCG_GeoMetrics": PCG_GeoMetrics,
    "PCG_SelectBest": PCG_SelectBest,
    "PCG_Retime": PCG_Retime,
    "PCG_SequenceMotion": PCG_SequenceMotion,
    "PCG_Circle": PCG_Circle, "PCG_MatchSize": PCG_MatchSize,
    "PCG_ExtractCentroid": PCG_ExtractCentroid,
    "PCG_Wrangle": PCG_Wrangle,
    "PCG_HeightfieldFromImage": PCG_HeightfieldFromImage,
    "PCG_PreviewImage": PCG_PreviewImage,
    "PCG_ExportMesh": PCG_ExportMesh,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PCG_Grid": "Grid (PCG)", "PCG_Box": "Box (PCG)", "PCG_Sphere": "Sphere (PCG)",
    "PCG_Tube": "Tube (PCG)", "PCG_Line": "Line (PCG)", "PCG_Curve": "Curve (PCG)",
    "PCG_Torus": "Torus (PCG)",
    "PCG_Transform": "Transform (PCG)", "PCG_Merge": "Merge (PCG)",
    "PCG_Convert": "Convert (PCG)", "PCG_Carve": "Carve (PCG)",
    "PCG_Reverse": "Reverse (PCG)", "PCG_Resample": "Resample (PCG)",
    "PCG_Sort": "Sort (PCG)",
    "PCG_Skin": "Skin (PCG)", "PCG_Boolean": "Boolean (PCG)",
    "PCG_Sweep": "Sweep (PCG)",
    "PCG_PolyExtrude": "PolyExtrude (PCG)", "PCG_PolyBevel": "PolyBevel (PCG)",
    "PCG_Normal": "Normal (PCG)", "PCG_Fuse": "Fuse (PCG)",
    "PCG_Add": "Add (PCG)", "PCG_Facet": "Facet (PCG)",
    "PCG_Divide": "Divide (PCG)", "PCG_Clip": "Clip (PCG)",
    "PCG_Split": "Split (PCG)",
    "PCG_GroupCreate": "Group Create (PCG)",
    "PCG_GroupEdges": "Group Edges (PCG)",
    "PCG_EdgeGroupPromote": "Edge Group Promote (PCG)",
    "PCG_GroupPromote": "Group Promote (PCG)", "PCG_Blast": "Blast (PCG)",
    "PCG_Connectivity": "Connectivity (PCG)", "PCG_Smooth": "Smooth (PCG)",
    "PCG_AttribPromote": "Attribute Promote (PCG)",
    "PCG_AttribDelete": "Attribute Delete (PCG)",
    "PCG_GroupDelete": "Group Delete (PCG)",
    "PCG_Switch": "Switch (PCG)",
    "PCG_Scatter": "Scatter (PCG)", "PCG_CopyToPoints": "Copy to Points (PCG)",
    "PCG_AttribTransfer": "Attribute Transfer (PCG)", "PCG_Ray": "Ray (PCG)",
    "PCG_PolyExpand2D": "PolyExpand2D (PCG)", "PCG_Refine": "Refine (PCG)",
    "PCG_PointJitter": "Point Jitter (PCG)",
    "PCG_ConvertLine": "Convert Line (PCG)",
    "PCG_PolyPath": "PolyPath (PCG)",
    "PCG_Join": "Join (PCG)",
    "PCG_AttribNoise": "Attribute Noise (PCG)",
    "PCG_Measure": "Measure (PCG)",
    "PCG_AttribCreate": "Attribute Create (PCG)",
    "PCG_AttribCopy": "Attribute Copy (PCG)",
    "PCG_AttribRename": "Attribute Rename (PCG)",
    "PCG_AttribCast": "Attribute Cast (PCG)",
    "PCG_AttribRandomize": "Attribute Randomize (PCG)",
    "PCG_AttribBlur": "Attribute Blur (PCG)",
    "PCG_AttribInterpolate": "Attribute Interpolate (PCG)",
    "PCG_AttribAdjust": "Attribute Adjust (PCG)",
    "PCG_Delete": "Delete (PCG)",
    "PCG_GroupExpand": "Group Expand (PCG)",
    "PCG_AttribFade": "Attribute Fade (PCG)",
    "PCG_Subdivide": "Subdivide (PCG)",
    "PCG_Dissolve": "Dissolve (PCG)",
    "PCG_EdgeDivide": "Edge Divide (PCG)",
    "PCG_LoopCut": "Loop Cut (PCG)",
    "PCG_PolyReduce": "PolyReduce (PCG)",
    "PCG_UVProject": "UV Project (PCG)",
    "PCG_UVLayout": "UV Layout (PCG)",
    "PCG_UVTransform": "UV Transform (PCG)",
    "PCG_UVFlatten": "UV Flatten (PCG)",
    "PCG_UVAutoSeams": "UV Auto Seams (PCG)",
    "PCG_PolyFill": "PolyFill (PCG)",
    "PCG_Triangulate2D": "Triangulate 2D (PCG)",
    "PCG_Voronoi2D": "Voronoi 2D (PCG)",
    "PCG_FileCache": "File Cache (PCG)",
    "PCG_VoronoiFracture": "Voronoi Fracture (PCG)",
    "PCG_ScatterVolume": "Scatter in Volume (PCG)",
    "PCG_VoronoiCluster": "Voronoi Cluster (PCG)",
    "PCG_GroupInside": "Group Inside (PCG)",
    "PCG_ConvexHull": "Convex Hull (PCG)",
    "PCG_Bound": "Bound (PCG)",
    "PCG_ConvexDecompose": "Convex Decompose (PCG)",
    "PCG_FractureDetail": "Fracture Detail (PCG)",
    "PCG_Deform": "Twist / Bend / Taper (PCG)",
    "PCG_SoftTransform": "Soft Transform (PCG)",
    "PCG_Spherify": "Spherify (PCG)",
    "PCG_Ends": "Ends (PCG)",
    "PCG_Peak": "Peak (PCG)",
    "PCG_Mirror": "Mirror (PCG)",
    "PCG_ExplodedView": "Exploded View (PCG)",
    "PCG_COPNoise": "COP Noise (PCG)",
    "PCG_COPShape": "COP Shape (PCG)",
    "PCG_COPGradient": "COP Gradient (PCG)",
    "PCG_COPConstant": "COP Constant (PCG)",
    "PCG_COPComposite": "COP Composite (PCG)",
    "PCG_COPBlur": "COP Blur (PCG)",
    "PCG_COPResize": "COP Resize (PCG)",
    "PCG_COPImport": "COP Import (PCG)",
    "PCG_COPExport": "COP Export (PCG)",
    "PCG_COPToDevice": "COP To Device (PCG)",
    "PCG_COPInfo": "COP Info (PCG)",
    "PCG_COPTransform": "COP Transform (PCG)",
    "PCG_COPFlip": "COP Flip (PCG)",
    "PCG_COPCrop": "COP Crop / Pad (PCG)",
    "PCG_COPTile": "COP Tile (PCG)",
    "PCG_COPDistort": "COP Distort (PCG)",
    "PCG_COPLevels": "COP Levels (PCG)",
    "PCG_COPRemap": "COP Remap (PCG)",
    "PCG_COPQuantize": "COP Quantize (PCG)",
    "PCG_COPFit": "COP Fit (PCG)",
    "PCG_COPLuminance": "COP Luminance (PCG)",
    "PCG_COPMorph": "COP Erode / Dilate (PCG)",
    "PCG_COPEdge": "COP Edge Detect (PCG)",
    "PCG_COPSharpen": "COP Sharpen (PCG)",
    "PCG_COPMedian": "COP Median (PCG)",
    "PCG_COPSDFFromMask": "COP SDF from Mask (PCG)",
    "PCG_COPHeightToNormal": "COP Height to Normal (PCG)",
    "PCG_COPNormalToHeight": "COP Normal to Height (PCG)",
    "PCG_COPHeightToAO": "COP Height to AO (PCG)",
    "PCG_COPHeightToShadow": "COP Height to Shadow (PCG)",
    "PCG_COPRefractFromHeight": "COP Refract from Height (PCG)",
    "PCG_COPHeightToCaustics": "COP Height to Caustics (PCG)",
    "PCG_COPCombineNormals": "COP Combine Normals (PCG)",
    "PCG_COPConvertNormal": "COP Convert Normal (PCG)",
    "PCG_COPErosion": "COP Erosion Filter (PCG)",
    "PCG_COPSlope": "COP Slope & Aspect (PCG)",
    "PCG_COPCurvature": "COP Curvature (PCG)",
    "PCG_COPStatistics": "COP Statistics (PCG)",
    "PCG_COPHistogram": "COP Histogram (PCG)",
    "PCG_COPSegment": "COP Segment by Connectivity (PCG)",
    "PCG_COPCompare": "COP Compare (PCG)",
    "PCG_COPMaskByFeature": "COP HeightField Mask by Feature (PCG)",
    "PCG_COPTerrace": "COP HeightField Terrace (PCG)",
    "PCG_COPThermalErosion": "COP HeightField Thermal Erosion (PCG)",
    "PCG_COPHeightfieldToMesh": "COP HeightField to Mesh (PCG)",
    "PCG_COPFlowAccumulation": "COP Flow Accumulation (PCG)",
    "PCG_COPStreamPower": "COP HeightField Stream Power Erosion (PCG)",
    "PCG_COPHydraulicErosion": "COP HeightField Hydraulic Erosion (PCG)",
    "PCG_COPSplatMap": "COP HeightField Splat Map (PCG)",
    "PCG_RegionalPrompt": "Regional Prompt from COP (PCG)",
    "PCG_COPHeightfieldFromDepth": "COP HeightField from Depth (PCG)",
    "PCG_RenderPass": "Render Pass (PCG)",
    "PCG_ControlImage": "Control Image (PCG)",
    "PCG_IDMasks": "ID Masks (PCG)",
    "PCG_AttribFromMap": "Attribute from Map (PCG)",
    "PCG_AttribFromCamera": "Attribute from Camera (PCG)",
    "PCG_DisplaceFromMap": "Displace from Map (PCG)",
    "PCG_ScatterFromMap": "Scatter from Map (PCG)",
    "PCG_Trace": "Trace (PCG)",
    "PCG_Camera": "Camera (PCG)",
    "PCG_TextureRender": "Texture Render (PCG)",
    "PCG_UVBackproject": "UV Backproject (PCG)",
    "PCG_UVResolve": "UV Resolve (PCG)",
    "PCG_CameraPath": "Camera Path (PCG)",
    "PCG_RenderSequence": "Render Sequence (PCG)",
    "PCG_MotionVectors": "Motion Vectors (PCG)",
    "PCG_COPWarp": "COP Warp (PCG)",
    "PCG_SequenceExport": "Sequence Export (PCG)",
    "PCG_SequenceImport": "Sequence Import (PCG)",
    "PCG_SequencePick": "Sequence Pick (PCG)",
    "PCG_CameraPick": "Camera Pick (PCG)",
    "PCG_GeoSequencePick": "Geo Sequence Pick (PCG)",
    "PCG_GeoMetrics": "Geo Metrics (PCG)",
    "PCG_SelectBest": "Select Best (PCG)",
    "PCG_TimeBlend": "Time Blend (PCG)",
    "PCG_Trail": "Trail (PCG)",
    "PCG_Retime": "Retime (PCG)",
    "PCG_SequenceMotion": "Sequence Motion (PCG)",
    "PCG_Circle": "Circle (PCG)", "PCG_MatchSize": "Match Size (PCG)",
    "PCG_ExtractCentroid": "Extract Centroid (PCG)",
    "PCG_Wrangle": "Wrangle (PCG)",
    "PCG_HeightfieldFromImage": "Heightfield from Image (PCG)",
    "PCG_PreviewImage": "Geometry Preview (PCG)",
    "PCG_ImportMesh": "Import Mesh (PCG)",
    "PCG_FromJSON": "From JSON (PCG)",
    "PCG_GeoToJSON": "Geo to JSON (PCG)",
    "PCG_ExportMesh": "Export Mesh (PCG)",
}


# ── The Copernicus completion batch (from pcg58) lives in nodes_cop2.py and is merged into the same table ──
from . import nodes_cop2 as _nc2                           # noqa: E402

NODE_CLASS_MAPPINGS.update(_nc2.NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_nc2.NODE_DISPLAY_NAME_MAPPINGS)


# ── SOP gap fill (from pcg67) lives in nodes_sop2.py, also merged into the main table ──
from . import nodes_sop2 as _ns2                           # noqa: E402

NODE_CLASS_MAPPINGS.update(_ns2.NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_ns2.NODE_DISPLAY_NAME_MAPPINGS)


# ── Volumes / VDB (pcg106) live in nodes_vol.py ──
from . import nodes_vol as _nvol                           # noqa: E402

NODE_CLASS_MAPPINGS.update(_nvol.NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_nvol.NODE_DISPLAY_NAME_MAPPINGS)


# ── Review additions (pcg121): distances, Path Deform, PolyWire, Thicken, Curve Fillet, Pack / Unpack ──
from . import nodes_sop3 as _ns3                           # noqa: E402

NODE_CLASS_MAPPINGS.update(_ns3.NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_ns3.NODE_DISPLAY_NAME_MAPPINGS)
