"""
The second SOP node file: gaps found in the pcg66 inventory are filled starting here (from pcg67).

How node files are split is described in the header of nodes_common.py. The end of nodes.py merges the mappings here into the main table.
Which Houdini node each node maps to is written in the first line of its docstring, "Maps to:"; the full mapping table is in
tests/sop_map.py (when one is added, change its row from todo to new; test_sop_map.py
checks this).

  Batch A frames, copy  Orient Along Curve, PolyFrame, Copy and Transform,
                        Revolve, Copy to Curves, Chain
  Batch B paths, nets   Find Shortest Path, Group Find Path, Curve Intersect,
                        Connect Adjacent Pieces
  Batch C variants/attr Attribute from Pieces, Enumerate, Color, Attribute Fill,
                        Attribute String Edit, Cluster Points (pcg68)
  Batch D mesh repair   Remesh, Clean, Edge Collapse, Point Split, UV Fuse (pcg68)
  Batch E modelling     Platonic Solids, L-System, Font, Lattice (+ Lattice From
                        Bound), Point Deform, Blend Shapes, Transform Pieces,
                        Poly Bridge(pcg70)
  P2 wrap-up           Attribute from Volume, Attribute Transfer by UV (pcg71)
  Volume batch         Volume, Volume Blur / Mix / Resample / Wrangle, Reshape SDF
                        (pcg72; Convert's SDF was switched to an exact one at the same time)
  Xform/correspondence Extract Transform, Attribute Transform Extract, Match Axis,
                        Primitive, Attribute Reorient, Match Topology, Topo Transfer,
                        DeltaMush(pcg73)
  Mesh editing         Edge Equalize, Edge Straighten, Circle from Edges, Edge Flip,
                        Tri Divide, Unsubdivide, Rewire Vertices, PolyCut, PolyStitch,
                        Voronoi Split(pcg74)
  Curves & surfaces    Circle Spline, PolySpline, Ballistic Path, PolyLoft,
                        Cross Section Surface(pcg75)
  Attribs/groups/points Attribute Composite, Attribute Mirror, Group from Attribute
                        Boundary, Partition, Tangent Field, Adaptive Prune,
                        Point Replicate, Point Velocity (pcg76)
  Volume / UV / outline IsoSurface, Remesh to Grid, UV Smooth, Extract Silhouette
                        (pcg77; HeightField Tile Split / Splice live in nodes_cop2.py)
"""
from __future__ import annotations

import json
import os

from .nodes_common import GEO, CAT, _f, _i, _group, _names, _sec  # noqa: F401
from .nodes_common import CAM, CAMSEQ
from .geo import curveframe as _cf, copyxform as _cx, paths as _pt
from .geo import variants as _va, meshfix as _mf, remesh as _rm
from .geo import platonic as _pl, lsystem as _ls, font as _ft
from .geo import deformers as _dfm, polybridge as _pb
from .geo import attribsample as _as
from .geo import volops as _vo
from .geo import registration as _rg, deform2 as _d2
from .geo import meshedit as _me, unsubdivide as _us, voronoisplit as _vs
from .geo import curves2 as _c2
from .geo import crosssection as _xs
from .geo import chainsop as _ch
from .geo import ops as _ops
from .geo import attribgroup as _ag, tangentfield as _tf, pointops2 as _po
from .geo import isosurface as _iso, uvsmooth as _uvs, silhouette as _sil
from .geo import campoints as _cpt, render as _rnd
from .geo import groupcombine as _gc, cutsplit as _cs, pointrelax as _prl
from .geo import xformattr as _xa, subdivide as _sub
from .geo import shrinkwrap as _sw
from .geo import deform3 as _d3, scatteralign as _sa, edgetransport as _et
from .geo import volraster as _vr
from .geo import attribfadetime as _aft
from .geo import xformextract as _xe
from .geo import namesop as _nm
from .geo import polydoctor as _pd
from .geo import uvpelt as _upe, uvunwrap as _uuw
from . import expr as _ex
from .geo.attribnoise import NOISE_TYPES as _AN_NOISE_TYPES


def _s(default=""):
    return ("STRING", {"default": default})


def _b(default=False):
    return ("BOOLEAN", {"default": default})


def _rep(r):
    return json.dumps(r, ensure_ascii=False)


def _node(cat, returns=None):
    def deco(cls):
        cls.FUNCTION = "run"
        cls.CATEGORY = CAT + "/" + cat
        if returns is None:
            cls.RETURN_TYPES = (GEO,)
            cls.RETURN_NAMES = ("geo",)
        else:
            cls.RETURN_TYPES = tuple(t for t, _ in returns)
            cls.RETURN_NAMES = tuple(n for _, n in returns)
        return cls
    return deco


_WITH_REPORT = ((GEO, "geo"), ("STRING", "report"))


# ═══════════════════════════════════════════════════════ Batch A
@_node("attribute")
class PCG_OrientAlongCurve:
    """
    Maps to: Orient Along Curve. Writes rotation-minimising frames (RMF, double reflection) onto curve points:
    N = tangent (+Z for Copy to Points), up (+Y), orient (the same frame as a quaternion).
    Frames don't flip at bends; on closed curves the extra twist accumulated over one loop is spread evenly by arc length, so start and end join up.
    Up Mode: minimal_rotation (the start uses the Up parameter, then RMF carries it forward) / constant
    (every point faces the Up parameter) / attribute (uses the up attribute on the points). Roll and Twists rotate up
    further about the tangent. Empty name = that item is not written.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only process these curves (prim group)"),
            "tangent_type": (list(_cf.TANGENT_TYPES),),
            "up_mode": (list(_cf.UP_MODES),),
            "up_x": _f(0.0, -1, 1), "up_y": _f(1.0, -1, 1), "up_z": _f(0.0, -1, 1),
            "up_attribute": _names("attrib", "point", "up"),
            "roll": _f(0.0, -3600, 3600, 1.0),
            "full_twists": _i(0, -100, 100),
            "partial_twist": _f(0.0, -3600, 3600, 1.0),
            "reverse": _b(False),
            "tangent_name": _s("N"), "up_name": _s("up"),
            "orient_name": _s("orient"), "side_name": _s(""),
            "curveu_name": _s(""),
        }}

    def run(self, geo, group, tangent_type, up_mode, up_x, up_y, up_z,
            up_attribute, roll, full_twists, partial_twist, reverse,
            tangent_name, up_name, orient_name, side_name, curveu_name):
        return (_cf.orient_along_curve(
            geo, group, tangent_type, up_mode, (up_x, up_y, up_z),
            up_attribute, roll, full_twists, partial_twist, reverse,
            tangent_name, up_name, orient_name, side_name, curveu_name),)


@_node("attribute")
class PCG_PolyFrame:
    """
    Maps to: PolyFrame. Writes **local** frames N / tangentu / tangentv onto points or faces.
    Style: two_edges, first_edge, centroid, uv (along increasing u, the same definition as the normal-map tangent
    space), attribute_gradient (the direction in which some scalar attribute increases fastest). On curves the
    point N is the Frenet principal normal (pointing to the inside of the bend, undefined on straight lines) -- for a non-flipping frame to place things,
    use Orient Along Curve. Orthogonal orthogonalises tangentu against N.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only process these prims"),
            "entity": (list(_cf.PF_ENTITIES),),
            "style": (list(_cf.PF_STYLES),),
            "uv_attribute": _names("attrib", "vertex", "uv"),
            "gradient_attribute": _names("attrib", "point", ""),
            "orthogonal": _b(True),
            "n_name": _s("N"), "tangentu_name": _s("tangentu"),
            "tangentv_name": _s("tangentv"),
        }}

    def run(self, geo, group, entity, style, uv_attribute, gradient_attribute,
            orthogonal, n_name, tangentu_name, tangentv_name):
        return (_cf.polyframe(geo, group, entity, style, uv_attribute,
                              gradient_attribute, orthogonal, n_name,
                              tangentu_name, tangentv_name),)


@_node("scatter")
class PCG_CopyAndTransform:
    """
    Maps to: Copy and Transform. Copies copies in total (including the original); copy k gets the same transform applied k times
    (scale and rotate at the pivot, then translate) -- rotating each copy 30° and moving it up 1 gives a spiral staircase, scaling each by 0.9
    gives nesting dolls. Affine matrices are multiplied, not approximated separately as t·k, R^k. Normals follow via the inverse transpose.
    Each copy's index is written into Copy Attribute (one each on point and prim).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "copies": _i(2, 0, 100000),
            "tx": _f(0.0), "ty": _f(0.0), "tz": _f(0.0),
            "rx": _f(0.0, -3600, 3600, 1.0), "ry": _f(0.0, -3600, 3600, 1.0),
            "rz": _f(0.0, -3600, 3600, 1.0),
            "sx": _f(1.0), "sy": _f(1.0), "sz": _f(1.0),
            "uniform_scale": _f(1.0, 0.0, 1e6, 0.01),
            "pivot_x": _f(0.0), "pivot_y": _f(0.0), "pivot_z": _f(0.0),
            "copy_attribute": _s("copynum"),
        }}

    def run(self, geo, copies, tx, ty, tz, rx, ry, rz, sx, sy, sz,
            uniform_scale, pivot_x, pivot_y, pivot_z, copy_attribute):
        return (_cx.copy_and_transform(geo, copies, (tx, ty, tz), (rx, ry, rz),
                                       (sx, sy, sz), uniform_scale,
                                       (pivot_x, pivot_y, pivot_z),
                                       copy_attribute),)


@_node("generate")
class PCG_Revolve:
    """
    Maps to: Revolve. Revolves a profile curve about an axis into a surface (lathe). A full 360° doesn't duplicate points at the seam; profile
    points lying on the axis are placed only once (a sphere revolved from a semicircle has one point at each pole, triangles automatically at the poles,
    no zero-area faces); a closed profile gives a torus. When not a full turn, End Caps close off the profile. With the profile drawn bottom to
    top on the positive side of the axis normals point outward; if reversed, turn on Reverse. If UV Attribute is given, uv is written:
    u = fraction of the angle swept, v = fraction of the profile arc length.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only revolve these curves"),
            "origin_x": _f(0.0), "origin_y": _f(0.0), "origin_z": _f(0.0),
            "axis_x": _f(0.0, -1, 1), "axis_y": _f(1.0, -1, 1),
            "axis_z": _f(0.0, -1, 1),
            "start_angle": _f(0.0, -3600, 3600, 1.0),
            "end_angle": _f(360.0, -3600, 3600, 1.0),
            "divisions": _i(16, 1, 4096),
            "surface": (list(_cx.REVOLVE_SURFACES),),
            "end_caps": _b(False), "reverse": _b(False),
            "uv_attribute": _s("uv"),
        }}

    def run(self, geo, group, origin_x, origin_y, origin_z, axis_x, axis_y,
            axis_z, start_angle, end_angle, divisions, surface, end_caps,
            reverse, uv_attribute):
        return (_cx.revolve(geo, group, (origin_x, origin_y, origin_z),
                            (axis_x, axis_y, axis_z), start_angle, end_angle,
                            divisions, end_caps, surface, reverse,
                            uv_attribute=uv_attribute),)


@_node("scatter")
class PCG_CopyToCurves:
    """
    Maps to: Copy to Curves. Takes points along curves by count (placing at both ends) or spacing, oriented by Orient Along
    Curve's RMF frame (+Z along the curve, +Y = Up), then Copy to Points. Start / End Offset
    leave a stretch free at each end. Roll Step rotates copy k by k times more (staggered railings, spirals). If Piece Attribute
    is given, pieces rotate in turn. k counts from 0 on each curve (same as Chain). The output carries curvenum (which
    curve it came from) and copynum.
    pcg100: Mode gains curve_points = Houdini's semantics (copy onto the curve's **existing points**, no resampling),
    with Houdini's Frame / Additional Rotations / Scales tabs (tangent type, target up, start/end up,
    Roll·Twist / Yaw / Pitch with per-edge / per-distance / per-attribute / full-curve distribution, rotation order, scale, stretch at bends,
    copying attributes from the target). Source Group is read in all modes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source": (GEO,), "curves": (GEO,),
            "group": _group("Only along these curves"),
            "mode": (list(_cx.CURVE_COPY_MODES),),
            "count": _i(10, 0, 1000000), "spacing": _f(1.0, 1e-6, 1e6, 0.01),
            "start_offset": _f(0.0, 0.0, 1e6, 0.01),
            "end_offset": _f(0.0, 0.0, 1e6, 0.01),
            "up_x": _f(0.0, -1, 1), "up_y": _f(1.0, -1, 1), "up_z": _f(0.0, -1, 1),
            "roll": _f(0.0, -3600, 3600, 1.0),
            "roll_step": _f(0.0, -3600, 3600, 1.0),
            "piece_attribute": _names("attrib", "prim", ""),
            "copy_attribute": _s("copynum"),
            # pcg100 additions. Source Group is read in all modes; the rest are only read with Mode = curve_points (Houdini's semantics: copy onto
            # the curve's existing points). In that mode the old Up X/Y/Z = Start Up Vector, Roll = Roll
            "source_group": _group("Only copy these from the source"),
            "source_group_type": (list(_cx.CTC_SOURCE_GROUP_TYPES),),
            "tangent_type": (list(_cx.CTC_TANGENTS),),
            "closed_continuous": ("BOOLEAN", {"default": True}),
            "extrapolate_ends": ("BOOLEAN", {"default": False}),
            "use_point_attribs": ("BOOLEAN", {"default": False}),
            "target_up": (list(_cx.CTC_UP),),
            "up_at_start": ("BOOLEAN", {"default": True}),
            "use_end_up": ("BOOLEAN", {"default": False}),
            "start_up_attrib": _s("start_up"), "end_up_attrib": _s("end_up"),
            "end_up_x": _f(0.0, -1, 1), "end_up_y": _f(1.0, -1, 1), "end_up_z": _f(0.0, -1, 1),
            "rotate_order": (list(_cx.CTC_ROT_ORDERS),),
            "apply_roll": ("BOOLEAN", {"default": False}),
            "twist_per": (list(_cx.CTC_PER),),
            "full_twists": _i(0, -1000, 1000),
            "partial_twist": _f(0.0, -1e6, 1e6, 1.0),
            "twist_ramp_attrib": _s(""),
            "apply_yaw": ("BOOLEAN", {"default": False}),
            "yaw": _f(0.0, -3600, 3600, 1.0),
            "yaw_per": (list(_cx.CTC_PER),),
            "incremental_yaw": _f(0.0, -1e6, 1e6, 1.0),
            "yaw_ramp_attrib": _s(""),
            "apply_pitch": ("BOOLEAN", {"default": False}),
            "pitch": _f(0.0, -3600, 3600, 1.0),
            "pitch_per": (list(_cx.CTC_PER),),
            "incremental_pitch": _f(0.0, -1e6, 1e6, 1.0),
            "pitch_ramp_attrib": _s(""),
            "normalize_scales": ("BOOLEAN", {"default": False}),
            "uniform_scale": _f(1.0, -1e6, 1e6, 0.01),
            "stretch_around_turns": ("BOOLEAN", {"default": False}),
            "max_stretch": _f(10.0, 1.0, 1e6, 0.1),
            "target_attributes": _s(""),
        }}

    def run(self, source, curves, group, mode, count, spacing, start_offset,
            end_offset, up_x, up_y, up_z, roll, roll_step, piece_attribute,
            copy_attribute, source_group="", source_group_type="guess",
            tangent_type="average", closed_continuous=True, extrapolate_ends=False,
            use_point_attribs=False, target_up="curve_normal", up_at_start=True,
            use_end_up=False, start_up_attrib="start_up", end_up_attrib="end_up",
            end_up_x=0.0, end_up_y=1.0, end_up_z=0.0, rotate_order="pyr",
            apply_roll=False, twist_per="per_edge", full_twists=0, partial_twist=0.0,
            twist_ramp_attrib="", apply_yaw=False, yaw=0.0, yaw_per="per_edge",
            incremental_yaw=0.0, yaw_ramp_attrib="", apply_pitch=False, pitch=0.0,
            pitch_per="per_edge", incremental_pitch=0.0, pitch_ramp_attrib="",
            normalize_scales=False, uniform_scale=1.0, stretch_around_turns=False,
            max_stretch=10.0, target_attributes=""):
        if mode == "curve_points":
            return (_cx.copy_to_curve_points(
                source, curves, group, source_group, source_group_type, piece_attribute,
                copy_attribute, tangent_type, closed_continuous, extrapolate_ends,
                use_point_attribs, target_up, up_at_start, use_end_up, start_up_attrib,
                end_up_attrib, (up_x, up_y, up_z), (end_up_x, end_up_y, end_up_z), rotate_order,
                apply_roll, roll, twist_per, full_twists, partial_twist, twist_ramp_attrib,
                apply_yaw, yaw, yaw_per, incremental_yaw, yaw_ramp_attrib, apply_pitch, pitch,
                pitch_per, incremental_pitch, pitch_ramp_attrib, normalize_scales, uniform_scale,
                stretch_around_turns, max_stretch, target_attributes),)
        src = _cx._ctc_source(source, source_group, source_group_type) if source is not None else None
        return (_cx.copy_to_curves(src, curves, group, mode, count, spacing,
                                   start_offset, end_offset, (up_x, up_y, up_z),
                                   roll, roll_step, piece_attribute,
                                   copy_attribute),)


@_node("scatter")
class PCG_Chain:
    """
    Maps to: Chain. Lays links one after another along a curve; each link takes up its own bounding box length in local Z
    + Spacing (negative = interlocking, which is how chain links work). Link centres sit at chord midpoints, +Z along the chord,
    so on bends both ends land on the curve. Adjacent links rotate an extra Roll Step (chain links stagger by 90° by default). Fit adjusts
    the spacing uniformly so the last link ends exactly at the endpoint (exactly one loop on closed curves). If Piece Attribute
    is given, several kinds of links rotate in turn.
    pcg100: Chain Mode gains deform_along_curve = Houdini's Chain (Deform Along Curve): the source is split into pieces by connectivity / piece attribute,
    arranged into a chain by a pattern (cycle / specified / random / weighted random), the chain mapped onto the curve by Map Length / Offset with each link
    bending along the curve; Extend / Clamp / Clip at both ends, end pieces, scale / rotation, Forward / Up axes, output position / index / curve number.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source": (GEO,), "curves": (GEO,),
            "group": _group("Only along these curves"),
            "spacing": _f(0.0, -1e6, 1e6, 0.01), "fit": _b(True),
            "roll": _f(0.0, -3600, 3600, 1.0),
            "roll_step": _f(90.0, -3600, 3600, 1.0),
            "up_x": _f(0.0, -1, 1), "up_y": _f(1.0, -1, 1), "up_z": _f(0.0, -1, 1),
            "piece_attribute": _names("attrib", "prim", ""),
            "copy_attribute": _s("copynum"),
            # pcg100 additions: Chain Mode = deform_along_curve takes Houdini's semantics (chainsop.chain_deform,
            # each link bends along the curve); the ones below are only read in that mode. In that mode the old Spacing = Piece Spacing,
            # Up X/Y/Z = Curve Up Vector (with Custom), Piece Attribute = the attribute name for splitting pieces by attribute;
            # Fit / Roll / Roll per Link are not read
            "chain_mode": (list(_ch.CHAIN_MODES),),
            "geometry_group": _group("Prims of the source that take part"),
            "enable_deformation": ("BOOLEAN", {"default": True}),
            "find_pieces": (list(_ch.FIND_PIECES),),
            "number_of_pieces": (list(_ch.NUM_PIECES),),
            "fraction_of_curve": _f(1.0, 0.0, 1e6, 0.01),
            "only_full_pattern": ("BOOLEAN", {"default": False}),
            "num_pieces": _i(10, 0, 100000),
            "uniform_piece_scale": _f(1.0, 1e-6, 1e6, 0.01),
            "map_length_using": (list(_ch.MAP_LENGTH),),
            "map_length": _f(1.0, -1e6, 1e6, 0.01),
            "map_length_attrib": _s(""),
            "offset_using": (list(_ch.OFFSET_USING),),
            "position_offset": _f(0.0, -1e6, 1e6, 0.01),
            "offset_attrib": _s(""),
            "start_behavior": (list(_ch.END_BEHAVIOR),),
            "end_behavior": (list(_ch.END_BEHAVIOR),),
            "repeat_pattern": (list(_ch.REPEAT_PATTERN),),
            "class_pattern": _s(""),
            "pattern_offset": _i(0, -100000, 100000),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "repeat_length": _i(0, 0, 100000),
            "piece_weights": _s(""),
            "weight_attrib": _s("weight"),
            "use_start_cap": ("BOOLEAN", {"default": False}),
            "start_cap_piece": _i(0, 0, 100000),
            "use_end_cap": ("BOOLEAN", {"default": False}),
            "end_cap_piece": _i(0, 0, 100000),
            "exclude_end_pieces": ("BOOLEAN", {"default": True}),
            "rigid_end_pieces": ("BOOLEAN", {"default": False}),
            "enable_scale": ("BOOLEAN", {"default": False}),
            "base_scale": _f(1.0, -1e6, 1e6, 0.01),
            "scale_attrib": _s(""),
            "enable_rotation": ("BOOLEAN", {"default": False}),
            "base_rotation": _f(0.0, -1e6, 1e6, 1.0),
            "rotation_attrib": _s(""),
            "forward_dir": (list(_ch.AXIS_DIRS), {"default": "z"}),
            "forward_x": _f(0.0), "forward_y": _f(0.0), "forward_z": _f(1.0),
            "up_dir": (list(_ch.AXIS_DIRS), {"default": "y"}),
            "upaxis_x": _f(0.0), "upaxis_y": _f(1.0), "upaxis_z": _f(0.0),
            "center_on_curve": ("BOOLEAN", {"default": False}),
            "piece_rotation": _f(0.0, -3600, 3600, 1.0),
            "curve_up_control": (list(_ch.CURVE_UP),),
            "attribs_to_transform": _s("N"),
            "position_attrib": _s(""),
            "index_attrib": _s(""),
            "curvenum_attrib": _s(""),
        }}

    def run(self, source, curves, group, spacing, fit, roll, roll_step, up_x,
            up_y, up_z, piece_attribute, copy_attribute, chain_mode="rigid_links",
            geometry_group="", enable_deformation=True, find_pieces="connectivity",
            number_of_pieces="fit", fraction_of_curve=1.0, only_full_pattern=False, num_pieces=10,
            uniform_piece_scale=1.0, map_length_using="fraction_curve", map_length=1.0,
            map_length_attrib="", offset_using="curve_u", position_offset=0.0, offset_attrib="",
            start_behavior="extend", end_behavior="extend", repeat_pattern="cycle",
            class_pattern="", pattern_offset=0, rand_seed=0, repeat_length=0, piece_weights="",
            weight_attrib="weight", use_start_cap=False, start_cap_piece=0, use_end_cap=False,
            end_cap_piece=0, exclude_end_pieces=True, rigid_end_pieces=False, enable_scale=False,
            base_scale=1.0, scale_attrib="", enable_rotation=False, base_rotation=0.0,
            rotation_attrib="", forward_dir="z", forward_x=0.0, forward_y=0.0, forward_z=1.0,
            up_dir="y", upaxis_x=0.0, upaxis_y=1.0, upaxis_z=0.0, center_on_curve=False,
            piece_rotation=0.0, curve_up_control="curve_normal", attribs_to_transform="N",
            position_attrib="", index_attrib="", curvenum_attrib=""):
        if chain_mode == "deform_along_curve":
            return (_ch.chain_deform(
                source, curves, group, geometry_group, find_pieces, piece_attribute,
                enable_deformation, number_of_pieces, fraction_of_curve, only_full_pattern,
                num_pieces, uniform_piece_scale, map_length_using, map_length, map_length_attrib,
                offset_using, position_offset, offset_attrib, start_behavior, end_behavior,
                repeat_pattern, class_pattern, pattern_offset, rand_seed, repeat_length,
                piece_weights, weight_attrib, use_start_cap, start_cap_piece, use_end_cap,
                end_cap_piece, exclude_end_pieces, rigid_end_pieces, enable_scale, base_scale,
                scale_attrib, enable_rotation, base_rotation, rotation_attrib, forward_dir,
                (forward_x, forward_y, forward_z), up_dir, (upaxis_x, upaxis_y, upaxis_z),
                center_on_curve, spacing, piece_rotation, curve_up_control, (up_x, up_y, up_z),
                attribs_to_transform, position_attrib, index_attrib, curvenum_attrib,
                copy_attribute)[0],)
        return (_cx.chain(source, curves, group, spacing, fit, roll,
                          roll_step, (up_x, up_y, up_z), piece_attribute,
                          copy_attribute),)


# ═══════════════════════════════════════════════════════ Batch B
@_node("topology", _WITH_REPORT)
class PCG_FindShortestPath:
    """
    Maps to: Find Shortest Path. Finds shortest paths (Dijkstra) along the edges of a mesh / curve network. Cost = edge length
    (or step count) × (1 + Cost Weight·cost attribute) × (1 + Slope Weight·|slope|) -- when pathfinding on terrain,
    slope makes paths follow contour lines, and a cost attribute steers around water and forests.
    Mode: nearest_end (each start to its nearest end) / each_pair / sequence (start group chained in the written
    order: "12 40 7"). Output: paths (paths only, with cost / length / startpt /
    endpt / srcpt) / merge (source geometry + paths) / group (writes edge and point groups on the source geometry).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "start_group": _group("Starts (point group, or point numbers in order)"),
            "end_group": _group("Ends (point group); not used in sequence mode"),
            "mode": (list(_pt.PATH_MODES),),
            "use_length": _b(True),
            "cost_attribute": _names("attrib", "point", ""),
            "cost_weight": _f(1.0, -1e6, 1e6, 0.1),
            "slope_weight": _f(0.0, 0.0, 1e6, 0.1),
            "up_x": _f(0.0, -1, 1), "up_y": _f(1.0, -1, 1), "up_z": _f(0.0, -1, 1),
            "output": (list(_pt.PATH_OUTPUTS),),
            "group_name": _s("path"), "close_sequence": _b(False),
            # pcg100: additions per the Find Shortest Path docs (defaults = old behaviour)
            "use_max_cost": _b(False), "max_cost": _f(100.0, 0.0, 1e12, 1.0),
            "point_cost_attribute": _names("attrib", "point", ""),
            "prim_cost_attribute": _names("attrib", "prim", ""),
            "omit_distance": _b(False),
            "surface_prims": _group("Only travel along the edges of these prims; empty = all"),
            "directed_prims": _group("Edges of these prims can only be travelled in prim direction; empty = none"),
            "edges_to_avoid": _names("group", "edge", hint="Edge group name; empty = none"),
        }}

    def run(self, geo, start_group, end_group, mode, use_length,
            cost_attribute, cost_weight, slope_weight, up_x, up_y, up_z,
            output, group_name, close_sequence, use_max_cost=False, max_cost=100.0,
            point_cost_attribute="", prim_cost_attribute="", omit_distance=False,
            surface_prims="", directed_prims="", edges_to_avoid=""):
        g, r = _pt.find_shortest_path(geo, start_group, end_group, mode,
                                      use_length, cost_attribute, cost_weight,
                                      slope_weight, (up_x, up_y, up_z), output,
                                      group_name, close_sequence,
                                      max_cost if use_max_cost else None,
                                      prim_cost_attribute, point_cost_attribute, omit_distance,
                                      surface_prims, directed_prims, edges_to_avoid)
        return (g, _rep(r))


@_node("group", _WITH_REPORT)
class PCG_GroupFindPath:
    """
    Maps to: Group Find Path. Writes an **edge group** (and a point group of the same name) on the source geometry; no new geometry.
    shortest_path: the points in Points are connected pairwise by shortest paths in the written order ("12 40 7"; Close connects back to
    the first); boundary_loop: the boundary loop (open edge, ring around a hole) each point in Points lies on.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "points": _group("Point numbers (in order) or a point group"),
            "mode": (list(_pt.GFP_MODES),),
            "close": _b(False), "use_length": _b(True),
            "cost_attribute": _names("attrib", "point", ""),
            "cost_weight": _f(1.0, -1e6, 1e6, 0.1),
            "group_name": _s("path"),
            # pcg100: additions per the Group Find Path docs (defaults = old behaviour)
            "avoid_self_intersection": _b(False),
            "collision_group": _group("Paths don't pass through these points; empty = none"),
            "contain_within_collision": _b(False),
        }}

    def run(self, geo, points, mode, close, use_length, cost_attribute,
            cost_weight, group_name, avoid_self_intersection=False, collision_group="",
            contain_within_collision=False):
        g, r = _pt.group_find_path(geo, points, mode, close, use_length,
                                   cost_attribute, cost_weight, group_name,
                                   avoid_self_intersection, collision_group,
                                   contain_within_collision)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_CurveIntersect:
    """
    Maps to: Curve Intersect. Intersects curves pairwise. With Plane = xz / xy / yz intersections are computed in projection (road networks
    computed from the top view); 3d requires two segments to actually come within Tolerance. Output: points (intersection points only,
    with prim_a / prim_b / u_a / u_b) / split (cut at intersections, which are shared, giving a connected
    network Find Shortest Path can travel directly; intersection points go into Point Group).
    pcg100: Output gains cut / extract = Houdini's Method: intersect between left (Face Group) and right (Cutter Group,
    curves from the second input cutter, picked from geo when not connected); cut splits both sides into segments and picks odd/even segments per Left / Right-face
    Pieces, extract outputs intersection points (Affect left / right / both, Keep Original). With Find All off, each pair of
    curves only takes the nearest intersection.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only compute these curves"),
            "plane": (list(_pt.INTERSECT_PLANES), {"default": "xz"}),
            "tolerance": _f(1e-4, 0.0, 1e6, 1e-4),
            "self_intersect": _b(True),
            "output": (list(_pt.INTERSECT_OUTPUTS), {"default": "split"}),
            "point_group": _s("intersections"),
            # pcg100 additions: Output gains Houdini's two Methods (cut / extract) at the end; the ones below are only read in those two modes.
            # Houdini is "left (Face Group) × right (Cutter Group / second input)", unlike the two old modes' "all curves pairwise"
            "cutter_group": _group("Curves on the right (cutter); picked from geo when the second input isn't connected"),
            "find_all": ("BOOLEAN", {"default": True}),
            "left_pieces": (list(_pt.INTERSECT_KEEP),),
            "right_pieces": (list(_pt.INTERSECT_KEEP),),
            "affect": (list(_pt.INTERSECT_AFFECT),),
            "keep_original": ("BOOLEAN", {"default": False}),
        }, "optional": {"cutter": (GEO,)}}

    def run(self, geo, group, plane, tolerance, self_intersect, output,
            point_group, cutter_group="", find_all=True, left_pieces="keep_all",
            right_pieces="keep_all", affect="left", keep_original=False, cutter=None):
        if output in ("cut", "extract"):
            g, r = _pt.curve_intersect_hou(geo, cutter, group, cutter_group, plane, tolerance,
                                           output, find_all, left_pieces, right_pieces, affect,
                                           keep_original)
        else:
            g, r = _pt.curve_intersect(geo, group, plane, tolerance,
                                       self_intersect, output, point_group)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_ConnectAdjacentPieces:
    """
    Maps to: Connect Adjacent Pieces. Connects neighbouring things with two-point polylines (constraint skeletons, road-network
    skeletons). points: the nearest Max Connections points within the radius; piece_centroids: two pieces with points within
    ≤ Radius are connected between their centres; piece_points: connected at the nearest pair of points of the two pieces. Lines carry
    restlength and the piece / point numbers of both ends. When Piece Attribute isn't found, pieces are split by connectivity.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "mode": (list(_pt.CONNECT_MODES),),
            "radius": _f(0.1, 1e-9, 1e6, 0.01),
            "max_connections": _i(4, 1, 1000),
            "piece_attribute": _names("attrib", "prim", "name"),
            "keep_input": _b(False),
            "group": _group("Only use these points"),
        }}

    def run(self, geo, mode, radius, max_connections, piece_attribute,
            keep_input, group):
        g, r = _pt.connect_adjacent_pieces(geo, mode, radius, max_connections,
                                           piece_attribute, keep_input, group)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Batch C
_CLS = (list(_va.CLASSES),)


@_node("attribute", _WITH_REPORT)
class PCG_AttribFromPieces:
    """
    Maps to: Attribute from Pieces. Picks a **variant** for each element (or each piece) and writes it as an attribute --
    feed Copy to Points' Piece Attribute for "several kinds of rocks scattered over a slope by weight".
    Variants come from the values of Library Attribute on the second input library (weights read from Weight
    Attribute); without library they are 0..Count−1 (weights written in Weights).
    Mode: random (random by weight) / cycle (rotating) / by_attribute (looks up the cumulative weights with Input Attribute's
    0~1 value -- feed a noise attribute and variants are distributed in clumps). If Piece Attribute is given,
    a whole piece gets the same variant. The report says how many times each variant was used.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute_class": _CLS, "group": _group(),
            "mode": (list(_va.AFP_MODES),),
            "count": _i(4, 1, 100000), "weights": _s(""),
            "library_attribute": _s("name"), "weight_attribute": _s("weight"),
            "piece_attribute": _names("attrib", "point", ""),
            "input_attribute": _names("attrib", "point", ""),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "output": _s("variant"), "index_output": _s(""),
            # ── pcg100 s7 additions (defaults = old behaviour)
            "weight_method": (list(_va.AFP_WEIGHT_METHODS),),
            "piece_filter": _s(""),
            "shuffle": _b(False), "offset": _i(0, -100000, 100000),
            "use_id_attribute": _b(False), "id_attribute": _names("attrib", "point", "id"),
            "copy_attributes": _s(""), "allow_p": _b(False),
            "promotion": (list(_va.AFP_PROMOTIONS), {"default": "first"}),
            "location_attribute": _names("attrib", "point", "P"),
            "element_size": _f(1.0, 1e-6, 1e6),
            "element_scale_x": _f(1.0, 1e-6, 1e6), "element_scale_y": _f(1.0, 1e-6, 1e6),
            "element_scale_z": _f(1.0, 1e-6, 1e6),
            "noise_offset_x": _f(0.0), "noise_offset_y": _f(0.0), "noise_offset_z": _f(0.0),
            "noise_type": (list(_AN_NOISE_TYPES), {"default": "perlin"}),
            "max_octaves": _i(1, 1, 16), "roughness": _f(0.5, 0.0, 1.0),
            "map_from": (list(_va.AFP_MAP_FROM),),
            "rules": ("STRING", {"multiline": True, "default": ""}),
            "unmatched_piece": _s(""), "unmatched_group": _s(""),
        }, "optional": {"library": (GEO,)}}

    def run(self, geo, attribute_class, group, mode, count, weights,
            library_attribute, weight_attribute, piece_attribute,
            input_attribute, rand_seed, output, index_output, library=None,
            weight_method="auto", piece_filter="", shuffle=False, offset=0,
            use_id_attribute=False, id_attribute="id", copy_attributes="",
            allow_p=False, promotion="first", location_attribute="P",
            element_size=1.0, element_scale_x=1.0, element_scale_y=1.0,
            element_scale_z=1.0, noise_offset_x=0.0, noise_offset_y=0.0,
            noise_offset_z=0.0, noise_type="perlin", max_octaves=1,
            roughness=0.5, map_from="weighted_unit", rules="",
            unmatched_piece="", unmatched_group=""):
        g, r = _va.attrib_from_pieces(
            geo, library, attribute_class, group, piece_attribute,
            library_attribute, weight_attribute, count, weights, mode,
            input_attribute, rand_seed, output, index_output,
            weight_method=weight_method, piece_filter=piece_filter,
            shuffle=shuffle, offset=offset, use_id_attribute=use_id_attribute,
            id_attribute=id_attribute, copy_attributes=copy_attributes,
            allow_p=allow_p, promotion=promotion,
            location_attribute=location_attribute, element_size=element_size,
            element_scale=(element_scale_x, element_scale_y, element_scale_z),
            noise_offset=(noise_offset_x, noise_offset_y, noise_offset_z),
            noise_type=noise_type, max_octaves=max_octaves, roughness=roughness,
            map_from=map_from, rules=rules, unmatched_piece=unmatched_piece,
            unmatched_group=unmatched_group)
        return (g, _rep(r))


@_node("attribute")
class PCG_Enumerate:
    """
    Maps to: Enumerate (and Name). elements: writes an index for each selected element; with Piece
    Attribute each piece counts from the start on its own; pieces: each element gets the index of its piece. Value = Start +
    Step × index. If Format is given (piece_%d, %03d) it is written as a string -- the Name SOP usage.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute_class": _CLS, "group": _group(),
            "mode": (list(_va.ENUM_MODES),),
            "piece_attribute": _names("attrib", "prim", ""),
            "name": _s("index"), "start": _i(0, -(1 << 30), 1 << 30),
            "step": _i(1, -(1 << 30), 1 << 30), "format": _s(""),
            "order": (list(_va.ENUM_ORDERS),),
        }}

    def run(self, geo, attribute_class, group, mode, piece_attribute, name,
            start, step, format, order):
        return (_va.enumerate_(geo, attribute_class, group, mode,
                               piece_attribute, name, start, step, format,
                               order),)


@_node("attribute")
class PCG_Color:
    """
    Maps to: Color, and Attribute Adjust Color (adjust mode). constant / random /
    random_by_attribute (same colour for the same attribute value, colouring fragments by name) /
    ramp_by_attribute (scalar attribute → colour ramp, ramp as one line of text) / adjust (adjusts HSV on the existing colour,
    each with its own random amount; with Attribute given, random per piece). Only changes the selected elements.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute_class": _CLS, "group": _group(),
            "mode": (list(_va.COLOR_MODES),),
            "r": _f(1.0, 0, 100), "g": _f(1.0, 0, 100), "b": _f(1.0, 0, 100),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "attribute": _names("attrib", "point", ""),
            "ramp": _s("0:0,0,1 0.5:0,1,0 1:1,0,0"),
            "ramp_mode": (["linear", "smooth", "constant"],),
            "auto_range": _b(True), "in_min": _f(0.0), "in_max": _f(1.0),
            "hue_shift": _sec("Adjust", _f(0.0, -360, 360, 1.0)),
            "saturation": _sec("Adjust", _f(1.0, 0, 10, 0.01)),
            "value": _sec("Adjust", _f(1.0, 0, 10, 0.01)),
            "random_hue": _sec("Adjust", _f(0.0, 0, 360, 1.0)),
            "random_saturation": _sec("Adjust", _f(0.0, 0, 1, 0.01)),
            "random_value": _sec("Adjust", _f(0.0, 0, 1, 0.01)),
            "name": _s("Cd"),
        }}

    def run(self, geo, attribute_class, group, mode, r, g, b, rand_seed,
            attribute, ramp, ramp_mode, auto_range, in_min, in_max, hue_shift,
            saturation, value, random_hue, random_saturation, random_value,
            name):
        return (_va.color(geo, attribute_class, group, mode,
                          (r, g, b), rand_seed, attribute, ramp, ramp_mode,
                          auto_range, in_min, in_max, hue_shift, saturation,
                          value, random_hue, random_saturation, random_value,
                          name),)


@_node("attribute", _WITH_REPORT)
class PCG_AttribFill:
    """
    Maps to: Attribute Fill. A point attribute is only meaningful on the points of Known Group, and is filled along the topology to the remaining
    points: harmonic (harmonic interpolation, conjugate-gradient solve; smooth, extrema only at known points) / nearest
    (the nearest known point along edges) / diffuse (Iterations rounds of weighted averaging; few iterations give a soft transition).
    Empty Known Group = points where the attribute is not all 0. Points not connected to any known point are untouched.
    The last four are Houdini's Modes: eikonal (arrival time) / poisson (harmonic fill with Attribute to Match)
    / diffusion (one implicit diffusion step) / extrapolate (Scalar / Parallel
    Transport). Known Group is Houdini's Boundary Group.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "point", "Cd"),
            "known_group": _group("Known points (point group); empty = points where the attribute is not all 0"),
            "method": (list(_va.FILL_METHODS),),
            "weights": (list(_va.FILL_WEIGHTS),),
            "iterations": _i(50, 1, 100000),
            # ── pcg100 s7 additions: parameters used by Houdini's four Modes (the three old modes don't read them)
            "speed_attribute": _names("attrib", "point", ""),
            "match_attribute": _names("attrib", "point", ""),
            "weight_attribute": _names("attrib", "point", ""),
            "min_edge_length": _f(1e-6, 0.0, 1e6, 1e-6),
            "min_speed": _f(1e-3, 0.0, 1e6, 1e-4),
            "diffusion_time": _f(1.0, 0.0, 1e6),
            "unreachable_time": _f(-1.0, -1e9, 1e9),
            "extrapolation": (list(_va.FILL_EXTRAP),),
            "tangential_only": _b(True),
            "global_rotation": _f(0.0, -360.0, 360.0, 1.0),
        }}

    def run(self, geo, attribute, known_group, method, weights, iterations,
            speed_attribute="", match_attribute="", weight_attribute="",
            min_edge_length=1e-6, min_speed=1e-3, diffusion_time=1.0,
            unreachable_time=-1.0, extrapolation="scalar", tangential_only=True,
            global_rotation=0.0):
        g, r = _va.attrib_fill(geo, attribute, known_group, method, weights,
                               iterations, speed_attribute=speed_attribute,
                               match_attribute=match_attribute,
                               weight_attribute=weight_attribute,
                               min_edge_length=min_edge_length, min_speed=min_speed,
                               diffusion_time=diffusion_time,
                               unreachable_time=unreachable_time,
                               extrapolation=extrapolation,
                               tangential_only=tangential_only,
                               global_rotation=global_rotation)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_AttribStringEdit:
    """
    Maps to: Attribute String Edit. Find and replace on string attributes: substring (replaces every occurrence)
    / wildcard (whole-string match against a pattern with *; what * captures fills the *s in Replace in order:
    piece*_old → chunk*) / regex (re.sub, \1 references a group). Attributes can list several and
    supports wildcards.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute_class": (["prim", "point", "vertex", "detail"],),
            "attributes": _s("name"), "group": _group(),
            "find": _s(""), "replace": _s(""),
            "mode": (list(_va.STREDIT_MODES),),
            "case_sensitive": _b(True),
        }}

    def run(self, geo, attribute_class, attributes, group, find, replace, mode,
            case_sensitive):
        g, r = _va.string_edit(geo, attribute_class, attributes, group,
                               find, replace, mode, case_sensitive)
        return (g, _rep(r))


@_node("attribute", ((GEO, "geo"), (GEO, "centroids"), ("STRING", "report")))
class PCG_ClusterPoints:
    """
    Maps to: Cluster Points (and the old Cluster). k-means splits points into Clusters clusters, writing an integer
    attribute (default cluster). Clusters by the value of Attribute (default P; can also split colour patches by Cd).
    k-means++ initialisation, reproducible with a fixed Rand Seed. The second output is each cluster's centre point (with
    cluster, count).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "clusters": _i(8, 1, 100000),
            "attribute": _names("attrib", "point", "P"), "group": _group(),
            "iterations": _i(30, 1, 10000),
            "rand_seed": _i(0, 0, 2 ** 31 - 1), "name": _s("cluster"),
            # ── pcg100 additions (Houdini Cluster Points), defaults = old behaviour
            "output": (list(_va.CLUSTER_OUTPUTS),),
            "color_output": (list(_va.CLUSTER_COLORS),),
            "cluster_filter": _s(""),
            "weight": _f(1.0, 0.0, 1e6, 0.01),
            "control_attribute2": _names("attrib", "point", ""),
            "weight2": _f(1.0, 0.0, 1e6, 0.01),
            "control_attribute3": _names("attrib", "point", ""),
            "weight3": _f(1.0, 0.0, 1e6, 0.01),
            "build_clusters": _b(True),
            "copy_point_attributes": _b(False),
            "max_sample_count": _i(10, 1, 100000),
            "size_attribute": _s("scale"),
            **_v3("padding_min", (0.0, 0.0, 0.0)),
            **_v3("padding_max", (0.0, 0.0, 0.0)),
        }}

    def run(self, geo, clusters, attribute, group, iterations, rand_seed,
            name, output="cluster_points", color_output="points", cluster_filter="",
            weight=1.0, control_attribute2="", weight2=1.0, control_attribute3="",
            weight3=1.0, build_clusters=True, copy_point_attributes=False,
            max_sample_count=10, size_attribute="scale", padding_min_x=0.0,
            padding_min_y=0.0, padding_min_z=0.0, padding_max_x=0.0, padding_max_y=0.0,
            padding_max_z=0.0):
        g, c, r = _va.cluster_points(
            geo, clusters, attribute, group, iterations, rand_seed, name,
            output=output, color_output=color_output, cluster_filter=cluster_filter,
            weight=weight, controls=((control_attribute2, weight2),
                                     (control_attribute3, weight3)),
            build_clusters=build_clusters, copy_attribs=copy_point_attributes,
            max_samples=max_sample_count, size_attrib=size_attribute,
            pad_min=(padding_min_x, padding_min_y, padding_min_z),
            pad_max=(padding_max_x, padding_max_y, padding_max_z))
        return (g, c, _rep(r))


# ═══════════════════════════════════════════════════════ Batch D
@_node("modify", _WITH_REPORT)
class PCG_Remesh:
    """
    Maps to: Remesh. Isotropic remeshing (Botsch & Kobbelt 2004): split long edges, collapse short edges, flip edges
    to even out valence, tangential smoothing, project back onto the original surface; five steps per round. With Target Length ≤ 0 the original mesh's average
    edge length is used. Hard edges with a dihedral angle above Feature Angle and borders (Keep Boundary) are preserved: a cube's
    corners and edges stay as they are. Point / prim / vertex attributes are interpolated from the nearest original triangle (uv seams aren't preserved;
    if you need uv, unwrap again afterwards). The report has split / collapse / flip counts and the share of edge lengths within the target range.
    pcg100 additions to match Houdini: Group (local remeshing, the other prims left as is; with Detach From Nongroup
    Geometry off, new points split on the boundary are also inserted into the neighbouring faces), Hard Edges Group, Hard Points
    Group, UV Seams = Harden, the output Hard Edges edge group. Edge Lengths = Adaptive is not done.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "target_length": _f(0.0, 0.0, 1e6, 0.01),
            "iterations": _i(6, 0, 100),
            "feature_angle": _f(45.0, 0.0, 180.0, 1.0),
            "keep_boundary": _b(True), "relax": _f(0.5, 0.0, 1.0, 0.05),
            "transfer_attributes": _b(True),
            # pcg100 additions (defaults = the previous behaviour)
            "group": _group(),
            "hard_edges": _names("group", "edge", ""),
            "hard_points": _names("group", "point", ""),
            "uv_seams": (list(_rm.UV_SEAMS),),
            "uv_attribute": _names("attrib", "vertex", "uv"),
            "detach": _b(False),
            "out_hard_edges": _s(""),
            # pcg102 additions
            "smooth_features": _b(False),
        }}

    def run(self, geo, target_length, iterations, feature_angle,
            keep_boundary, relax, transfer_attributes, group="", hard_edges="",
            hard_points="", uv_seams="ignore", uv_attribute="uv", detach=False,
            out_hard_edges="", smooth_features=False):
        g, r = _rm.remesh(geo, target_length, iterations, feature_angle,
                          keep_boundary, relax, transfer_attributes, group,
                          hard_edges, hard_points, uv_seams, uv_attribute, detach,
                          out_hard_edges, smooth_features)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_Clean:
    """
    Maps to: Clean (and PolyDoctor's repairs). In order: fuse points within distance, remove degenerates, remove duplicate
    faces (regardless of start point and winding), Make Manifold (edges shared by more than two faces keep the two largest,
    bowtie points are split), consistent orientation, delete small fragments, delete unused points. The report says how much each step changed.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "fuse_distance": _f(0.0, 0.0, 1e6, 0.0001),
            "remove_degenerate": _b(True), "remove_duplicates": _b(True),
            "make_manifold": _b(False), "orient": _b(False),
            "min_piece_prims": _i(0, 0, 1 << 30), "remove_unused": _b(True),
        }}

    def run(self, geo, fuse_distance, remove_degenerate, remove_duplicates,
            make_manifold, orient, min_piece_prims, remove_unused):
        g, r = _mf.clean(geo, "", fuse_distance, remove_degenerate,
                         remove_duplicates, make_manifold, orient,
                         remove_unused, min_piece_prims)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_EdgeCollapse:
    """
    Maps to: Edge Collapse. Chains of connected edges in the edge group are collapsed into one point (placed at the centre of the chain's points);
    afterwards duplicate corners and faces that can no longer stand are removed.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _names("group", "edge", ""),
            "remove_degenerate": _b(True),
        }}

    def run(self, geo, edges, remove_degenerate):
        g, r = _mf.edge_collapse(geo, edges, remove_degenerate)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_PointSplit:
    """
    Maps to: Point Split. A point whose several vertices have different vertex attribute values (uv seams, hard-edge N)
    is split into several points. Empty Attribute = split by all. Values are compared with a chained tolerance (no bucketing).
    Promote also writes this vertex attribute as a point attribute of the same name.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "vertex", "uv"),
            "tolerance": _f(1e-5, 0.0, 1e6, 1e-5), "group": _group(),
            "promote": _b(True),
        }}

    def run(self, geo, attribute, tolerance, group, promote):
        g, r = _mf.point_split(geo, attribute, tolerance, group, promote)
        return (g, _rep(r))


@_node("uv", _WITH_REPORT)
class PCG_UVFuse:
    """
    Maps to: UV Fuse. Vertices within Distance of each other in uv space are welded together (averaged).
    shared_points only welds those on the same geometric point (cleaning up small gaps left by projection); distance doesn't care whether they're
    the same point (sewing up the touching edges of two islands).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "uv_attribute": _names("attrib", "vertex", "uv"),
            "mode": (list(_mf.UVFUSE_MODES),),
            "distance": _f(1e-3, 0.0, 1e6, 1e-4), "group": _group(),
        }}

    def run(self, geo, uv_attribute, mode, distance, group):
        g, r = _mf.uv_fuse(geo, uv_attribute, mode, distance, group)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Batch E
@_node("generate")
class PCG_PlatonicSolids:
    """
    Maps to: Platonic Solids. Tetrahedron / cube / octahedron / dodecahedron / icosahedron and the soccer ball (truncated icosahedron).
    Radius is the circumsphere radius; faces all face outward and points are shared (watertight). The prim attribute sides = the face's
    edge count (on the soccer ball 5 are the black patches, 6 the white ones). The octahedron and dodecahedron are built as duals, the soccer ball is the
    icosahedron truncated at 1/3 of each edge -- no copied coordinate tables.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "solid": (list(_pl.TYPES), {"default": "icosahedron"}),
            "radius": _f(1.0, 0.0), "center_x": _f(0.0), "center_y": _f(0.0),
            "center_z": _f(0.0),
        }}

    def run(self, solid, radius, center_x, center_y, center_z):
        return (_pl.solid(solid, radius, (center_x, center_y, center_z)),)


@_node("generate", _WITH_REPORT)
class PCG_LSystem:
    """
    Maps to: L-System. Premise is rewritten by Rules for Generations generations, then drawn with a 3D turtle.
    One rule per line: F=F[+F]F[-F]F; writing several rules for the same character, prefixed with (weight), makes them stochastic rules.
    F draws, f skips, + - turn left/right, & ^ pitch down/up, \\ / roll, | turn around, [ ] branch, ! thinner,
    " shorter, J K L M place leaf points (point group leaves, with N / up / orient and name).
    Gravity makes branches droop. Point attributes width, generation (which generation it grew in), depth.
    If the string gets too long (more than Max Symbols) it raises an error instead of truncating.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "premise": _s("F"),
            "rules": ("STRING", {"multiline": True,
                                 "default": "F=F[+F]F[-F]F"}),
            "generations": _i(4, 0, 30),
            "angle": _f(25.7, -360.0, 360.0, 0.1), "step": _f(1.0, 0.0),
            "width": _f(0.1, 0.0), "step_scale": _f(0.9, 0.0, 10.0),
            "width_scale": _f(0.7, 0.0, 10.0),
            "gravity": _f(0.0, -10.0, 10.0, 0.01),
            "angle_variance": _f(0.0, 0.0, 180.0, 0.5),
            "rand_seed": _i(0, 0, 1 << 30),
            "max_symbols": _i(2_000_000, 1, 1 << 30),
        }}

    def run(self, premise, rules, generations, angle, step, width, step_scale,
            width_scale, gravity, angle_variance, rand_seed, max_symbols):
        g, r = _ls.lsystem(premise, rules, generations, angle, step, width,
                           step_scale, width_scale, gravity, angle_variance,
                           rand_seed, max_symbols)
        return (g, _rep(r))


@_node("generate", _WITH_REPORT)
class PCG_Font:
    """
    Maps to: Font. Vector outlines of text (fontTools reads ttf / otf / ttc) → outline (closed contours,
    prim attribute hole) / faces (constrained Delaunay fill, holes kept) / extrude (front + back +
    side walls, watertight). Font takes a path, a file name (arial, msyh) or a family name; empty uses arial /
    DejaVuSans; characters missing from the main font are looked up via Fallback (by default including Chinese fonts like Microsoft YaHei). Size is the
    em height; text lies in the XY plane facing +Z. Prim attributes char / char_index / line.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "PCG"}),
            "font": _s(""), "size": _f(1.0, 0.0),
            "mode": (list(_ft.MODES), {"default": "faces"}),
            "depth": _f(0.2, 0.0), "curve_segments": _i(6, 1, 64),
            "tracking": _f(0.0, -1.0, 10.0), "line_spacing": _f(1.0, 0.0, 10.0),
            "halign": (list(_ft.HALIGN),), "valign": (list(_ft.VALIGN),),
            "fallback": _s(_ft.DEFAULT_FALLBACK),
        }}

    def run(self, text, font, size, mode, depth, curve_segments, tracking,
            line_spacing, halign, valign, fallback):
        g, r = _ft.font(text, font, size, mode, depth, curve_segments, tracking,
                        line_spacing, halign, valign, fallback)
        return (g, _rep(r))


@_node("deform", ((GEO, "lattice"),))
class PCG_LatticeFromBound:
    """
    Maps to: the lattice of the Lattice SOP (Bound + Divisions). Lays out
    (nx+1)(ny+1)(nz+1) control points over the input's bounding box (connected with grid lines for easy viewing), each point with a rest attribute.
    Move these points with any node, then connect to the lattice input of Lattice (PCG). Don't delete or merge points.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "divisions_x": _i(2, 1, 64), "divisions_y": _i(2, 1, 64),
            "divisions_z": _i(2, 1, 64), "padding": _f(0.0, 0.0),
        }}

    def run(self, geo, divisions_x, divisions_y, divisions_z, padding):
        return (_dfm.lattice_from_bound(geo, (divisions_x, divisions_y,
                                              divisions_z), padding),)


@_node("deform")
class PCG_Lattice:
    """
    Maps to: Lattice (FFD free-form deformation). Geometry deforms with the control lattice: rest positions are read from the lattice's own
    rest attribute (or connect rest_lattice). trilinear is local (each point only looks at the 8 control points
    of its cell); bezier is Sederberg–Parry's global Bernstein volume, smooth everywhere, suited to large-form adjustments with 2~4
    cells. Both have linear precision: an overall affine lattice makes the geometry exactly affine. With Outside =
    keep, points outside the lattice don't move. Normals are corrected by the inverse transpose of the Jacobian.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "lattice": (GEO,),
            "interpolation": (list(_dfm.LATTICE_INTERP),),
            "outside": (list(_dfm.OUTSIDE),), "group": _group(),
        }, "optional": {"rest_lattice": (GEO,)}}

    def run(self, geo, lattice, interpolation, outside, group,
            rest_lattice=None):
        return (_dfm.lattice(geo, lattice, rest_lattice, interpolation, outside,
                             group),)


@_node("deform", _WITH_REPORT)
class PCG_PointDeform:
    """
    Maps to: Point Deform. A high-res mesh deforms with a low-res point cloud: rest is the low-res original points, deformed is
    the deformed one (same point count and order). Each high-res point is weighted by its nearest Max Points low-res points (kernel radius
    is the (k+1)-th nearest distance, so weights stay continuous when neighbours change). rigid: blends each low-res point's local rigid transform
    (Kabsch), so rotating the whole low-res rotates the high-res exactly, normals rotating along; translate: only blends displacements, cheap
    but deforms as soon as it rotates.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "rest": (GEO,), "deformed": (GEO,),
            "max_points": _i(8, 1, 256), "mode": (list(_dfm.PD_MODES),),
            "group": _group(),
        }}

    def run(self, geo, rest, deformed, max_points, mode, group):
        g, r = _dfm.point_deform(geo, rest, deformed, max_points, mode, group)
        return (g, _rep(r))


@_node("deform", _WITH_REPORT)
class PCG_BlendShapes:
    """
    Maps to: Blend Shapes. Blends point attributes of several geometries with the same topology (Attributes, default P N; N
    normalised after blending). additive: base + Σ wᵢ(targetᵢ − base), weights may go outside 0~1; sequential:
    a single Blend value walks base → target1 → target2 … (1.5 = halfway between 1 and 2; counted by slot number,
    empty slots stop at the previous shape). With Match =
    id, points are matched by the id attribute (works even with shuffled point order).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "base": (GEO,), "target1": (GEO,),
            "mode": (list(_dfm.BLEND_MODES),),
            "weight1": _f(1.0, -10.0, 10.0), "weight2": _f(0.0, -10.0, 10.0),
            "weight3": _f(0.0, -10.0, 10.0), "weight4": _f(0.0, -10.0, 10.0),
            "blend": _f(0.0, 0.0, 4.0), "attributes": _s("P N"),
            "match": (list(_dfm.BLEND_MATCH),),
        }, "optional": {"target2": (GEO,), "target3": (GEO,),
                        "target4": (GEO,)}}

    def run(self, base, target1, mode, weight1, weight2, weight3, weight4,
            blend, attributes, match, target2=None, target3=None, target4=None):
        # Passed by slot as is (unconnected ones are None): sequential's Blend counts by slot number, see blend_shapes
        g, r = _dfm.blend_shapes(base, [target1, target2, target3, target4],
                                 [weight1, weight2, weight3, weight4], mode, blend,
                                 attributes, match)
        return (g, _rep(r))


@_node("deform", _WITH_REPORT)
class PCG_TransformPieces:
    """
    Maps to: Transform Pieces. Splits into pieces by name (on prims first, otherwise on points), and transforms each piece with the
    instance attributes of the template point of the same name (P / orient / N+up / scale / pscale / pivot / transform,
    as in Copy to Points). With rest connected: piece = template ∘ rest⁻¹ (points exported from RBD,
    bones); without: piece centres are placed on the template points. Pieces with no template point don't move and are listed in the report.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "template": (GEO,),
            "piece_attribute": _names("attrib", "prim", "name"),
            # ── pcg100 additions (Houdini Transform Pieces), defaults = old behaviour
            "attribute_mode": (list(_dfm.PIECE_MODES),),
            "invert_transformation": _b(False),
            "center_pieces": _b(True),
            "attributes_to_transform": _s("N up v"),
            "copy_template_attributes": _b(False),
            "attributes_to_copy": _names("attrib", "point", "*"),
            "groups_to_copy": _names("group", "point", ""),
        }, "optional": {"rest": (GEO,)}}

    def run(self, geo, template, piece_attribute, rest=None, attribute_mode="match",
            invert_transformation=False, center_pieces=True,
            attributes_to_transform="N up v", copy_template_attributes=False,
            attributes_to_copy="*", groups_to_copy=""):
        on = copy_template_attributes
        g, r = _dfm.transform_pieces(
            geo, template, rest, piece_attribute, attribute_mode=attribute_mode,
            invert=invert_transformation, center_pieces=center_pieces,
            transform_attribs=attributes_to_transform,
            copy_attribs=attributes_to_copy if on else "",
            copy_groups=groups_to_copy if on else "")
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_PolyBridge:
    """
    Maps to: Poly Bridge. Builds faces between two loops of edges: Source / Destination are prim groups (faces →
    their outer outline, deleted with Remove Caps; open curves → the curves themselves) or point groups
    (hole borders). Equal point counts give quads, unequal counts zip by arc length into triangles; start points are aligned automatically, Twist
    offsets by a few more points. Divisions sections, linear or hermite (leaving along the cap normals, so handles / tunnels
    pick their direction automatically). Orientation matches neighbouring faces, still watertight after tunnelling. New faces go into Output Group.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "source_group": _names("group", "prim", ""),
            "dest_group": _names("group", "prim", ""),
            "divisions": _i(1, 1, 1000), "twist": _i(0, -100000, 100000),
            "interpolation": (list(_pb.INTERP),),
            "magnitude": _f(1.0, -10.0, 10.0), "flip_direction": _b(False),
            "remove_caps": _b(True), "reverse_normals": _b(False),
            "output_group": _s("bridge"),
        }}

    def run(self, geo, source_group, dest_group, divisions, twist,
            interpolation, magnitude, flip_direction, remove_caps,
            reverse_normals, output_group):
        g, r = _pb.poly_bridge(geo, source_group, dest_group, divisions, twist,
                               interpolation, magnitude, flip_direction,
                               remove_caps, reverse_normals, output_group)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ P2 wrap-up
@_node("attribute", _WITH_REPORT)
class PCG_AttribFromVolume:
    """
    Maps to: Attribute from Volume (and Volume Sample). Samples a dense volume at each point's (or prim centre's) position
    and writes an attribute: trilinear / nearest / gradient (vec3; on an SDF that's the
    normal direction). Outside the volume: clamp takes the border value, constant gives Outside Value, keep doesn't write.
    Empty Volume Select = the first volume; a number = the n-th volume; a name = the prim attribute name.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "volume": (GEO,), "attribute": _s("density"),
            "volume_select": _s(""), "mode": (list(_as.VOL_MODES),),
            "outside": (list(_as.OUTSIDE),), "outside_value": _f(0.0),
            "attribute_class": (list(_as.CLASSES),), "group": _group(),
        }}

    def run(self, geo, volume, attribute, volume_select, mode, outside,
            outside_value, attribute_class, group):
        g, r = _as.attribute_from_volume(geo, volume, attribute, volume_select,
                                         mode, outside, outside_value,
                                         attribute_class, group)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_AttribTransferByUV:
    """
    Maps to: Attribute Transfer by UV. Transfers attributes from source by uv (not spatial distance): for each target
    point / vertex, find which uv triangle of source its uv falls in, and interpolate by the barycentric coordinates there. The two sides
    may differ in topology and position as long as the UV layout is the same (moving colours baked on a high-res mesh to a low-res one; transferring P wraps
    one geometry onto another by UV). For those falling outside UV islands: nearest uses the nearest triangle (Max
    Distance limits the distance), keep doesn't write. The report has the count falling in UV overlap regions.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "source": (GEO,), "attributes": _s("Cd"),
            "uv_attribute": _names("attrib", "vertex", "uv"),
            "source_uv": _s(""), "attribute_class": (list(_as.UV_CLASSES),),
            "outside": (list(_as.UV_OUTSIDE),),
            "max_distance": _f(0.0, 0.0), "group": _group(),
        }}

    def run(self, geo, source, attributes, uv_attribute, source_uv,
            attribute_class, outside, max_distance, group):
        g, r = _as.attribute_transfer_by_uv(geo, source, attributes, uv_attribute,
                                            source_uv, attribute_class, outside,
                                            max_distance, group)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Volume batch
def _vsel():
    return ("STRING", {"default": "", "tooltip":
                       "Empty = all volumes; a number = the n-th volume; a name (wildcards allowed) = the prim attribute name"})


@_node("generate")
class PCG_Volume:
    """
    Maps to: Volume. Builds a constant volume (sampled at grid points, the end grid points at the box corners). With bound connected, its
    bounding box (expanded by Padding) is the range; with Voxel Size > 0 the resolution is computed from range / voxel edge length
    (voxels are cubes), otherwise Resolution is used. Fog marks a density field (positive inside); unchecked it's an SDF.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "res_x": _i(32, 2, 1024), "res_y": _i(32, 2, 1024), "res_z": _i(32, 2, 1024),
            "size_x": _f(1.0, 1e-6), "size_y": _f(1.0, 1e-6), "size_z": _f(1.0, 1e-6),
            "center_x": _f(0.0), "center_y": _f(0.0), "center_z": _f(0.0),
            "value": _f(0.0), "fog": _b(False), "name": _s(""),
            "padding": _f(0.0, 0.0), "voxel_size": _f(0.0, 0.0),
        }, "optional": {"bound": (GEO,)}}

    def run(self, res_x, res_y, res_z, size_x, size_y, size_z, center_x,
            center_y, center_z, value, fog, name, padding, voxel_size,
            bound=None):
        return (_vo.create_volume((res_x, res_y, res_z), (size_x, size_y, size_z),
                                  (center_x, center_y, center_z), value, fog, name,
                                  bound, padding, voxel_size),)


@_node("modify")
class PCG_VolumeBlur:
    """
    Maps to: Volume Blur. gaussian (σ = Radius / 2, converted by each axis's voxel edge length, round in world space)
    or box; separable, one pass per direction. A blurred SDF is no longer a distance field; to use it as one, follow with
    Reshape SDF's redistance (or use the Smooth SDF node).
    pcg100 s9 adds Houdini's Reduction (Maximum … Root Mean Square; default filter = the Mode
    above), Use Voxel Radius / Voxel Radius, Override Border + Border Value, Enable Blending
    (Original / Blurred Blend Amount). Iterations corresponds to Houdini's Passes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "radius": _f(0.1, 0.0), "mode": (list(_vo.BLUR_MODES),),
            "iterations": _i(1, 0, 100), "volumes": _vsel(),
            # pcg100 s9 additions (placed last, old workflow indices unchanged)
            "reduction": (list(_vo.BLUR_REDUCTIONS),),
            "use_voxel_radius": _b(False),
            "voxel_radius_x": _i(1, 0, 256), "voxel_radius_y": _i(1, 0, 256),
            "voxel_radius_z": _i(1, 0, 256),
            "override_border": (list(_vo.BLUR_BORDERS),),
            "border_value": _f(0.0),
            "enable_blending": _b(False),
            "original_blend": _f(0.0), "blurred_blend": _f(1.0),
        }}

    def run(self, geo, radius, mode, iterations, volumes, reduction="filter",
            use_voxel_radius=False, voxel_radius_x=1, voxel_radius_y=1, voxel_radius_z=1,
            override_border="use_volume", border_value=0.0, enable_blending=False,
            original_blend=0.0, blurred_blend=1.0):
        return (_vo.blur(geo, radius, mode, iterations, volumes, reduction,
                         use_voxel_radius, (voxel_radius_x, voxel_radius_y, voxel_radius_z),
                         override_border, border_value, enable_blending,
                         original_blend, blurred_blend),)


@_node("modify", _WITH_REPORT)
class PCG_VolumeMix:
    """
    Maps to: Volume Mix (and VDB Combine). B is trilinearly sampled onto A's grid by world position, then combined:
    add, subtract, multiply, max, min, blend, copy_b; SDF union / intersect / difference and their
    smooth versions (Quilez polynomial smooth min, K is the transition width in world units). The result is on A's grid.
    Every selected volume in A is mixed (paired with the same-named one in B; if B has only one, all pair with it; otherwise in order).
    pcg100 s9 adds Houdini's Diff / Divide / Invert / Clamp (Range) / User (Value expression,
    Wrangle syntax) and Dest / Source Pre-Add·Mul, Post-Add·Mul, Clamp Minimum / Maximum.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo_a": (GEO,), "geo_b": (GEO,), "operation": (list(_vo.MIX_OPS),),
            "factor": _f(0.5, -10.0, 10.0), "k": _f(0.1, 0.0),
            "volume_a": _vsel(), "volume_b": _vsel(),
            # pcg100 s9 additions (placed last, old workflow indices unchanged)
            "range_min": _f(0.0), "range_max": _f(1.0),
            "value": _s("@value"),
            "dest_pre_add": _f(0.0), "dest_pre_mul": _f(1.0),
            "src_pre_add": _f(0.0), "src_pre_mul": _f(1.0),
            "post_add": _f(0.0), "post_mul": _f(1.0),
            "use_clamp_min": _b(False), "clamp_min": _f(0.0),
            "use_clamp_max": _b(False), "clamp_max": _f(1.0),
        }}

    def run(self, geo_a, geo_b, operation, factor, k, volume_a, volume_b,
            range_min=0.0, range_max=1.0, value="@value", dest_pre_add=0.0,
            dest_pre_mul=1.0, src_pre_add=0.0, src_pre_mul=1.0, post_add=0.0,
            post_mul=1.0, use_clamp_min=False, clamp_min=0.0, use_clamp_max=False,
            clamp_max=1.0):
        adj = dict(range_min=range_min, range_max=range_max, value=value,
                   dest_add=dest_pre_add, dest_mul=dest_pre_mul,
                   src_add=src_pre_add, src_mul=src_pre_mul,
                   post_add=post_add, post_mul=post_mul,
                   use_min=use_clamp_min, clamp_min=clamp_min,
                   use_max=use_clamp_max, clamp_max=clamp_max)
        g, r = _vo.mix(geo_a, geo_b, operation, factor, k, volume_a, volume_b, adj)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_VolumeResample:
    """
    Maps to: Volume Resample. Changes resolution with the bounding box unchanged: give the resolution directly, compute it from voxel edge length, or an overall
    scale factor. New grid points sample the old field by trilinear / nearest.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "mode": (list(_vo.RESAMPLE_MODES),),
            "res_x": _i(32, 2, 1024), "res_y": _i(32, 2, 1024), "res_z": _i(32, 2, 1024),
            "voxel_size": _f(0.1, 0.0), "scale": _f(1.0, 0.0),
            "interpolation": (list(_vo.INTERP),), "volumes": _vsel(),
        }}

    def run(self, geo, mode, res_x, res_y, res_z, voxel_size, scale,
            interpolation, volumes):
        g, r = _vo.resample(geo, mode, (res_x, res_y, res_z), voxel_size, scale,
                            interpolation, volumes)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_VolumeWrangle:
    """
    Maps to: Volume Wrangle. Same syntax as Wrangle, each voxel treated as a point: @P grid point world position,
    @value voxel value (read/write), @ix @iy @iz indices; volsample(name or index, position) samples other volumes of the same
    geometry. @value reads as 1D and combines directly with @P.x; to multiply with a vector write
    @P * @value[:, None].
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "code": ("STRING", {"multiline": True, "code_hl": True, "default":
                                "@value = @value + 0.05 * noise(@P * 4.0)"}),
            "volumes": _vsel(), "rand_seed": _i(0, 0, 1 << 31),
            "ch_params": ("STRING", {"default": "{}", "ch_store": True}),
        }}

    def run(self, geo, code, volumes, rand_seed, ch_params="{}"):
        try:
            chd = json.loads(ch_params) if str(ch_params).strip() else {}
        except ValueError:
            chd = {}
        g, r = _vo.wrangle(geo, code, volumes, rand_seed, chd)
        return (g, _rep(r))


@_node("modify")
class PCG_VolumeReshapeSDF:
    """
    Maps to: VDB Reshape SDF. dilate (f − d) / erode (f + d) / open (erode then dilate, removing protrusions thinner than
    2d) / close (dilate then erode, filling gaps narrower than 2d) / redistance (only recompute distances,
    restoring |∇f| = 1 after blurring, mixing or wrangling). Redistancing = extract the 0 iso-surface, compute exact distance to it,
    keep the original sign. Only meaningful for SDFs (fog raises an error).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "operation": (list(_vo.RESHAPE_OPS),),
            "distance": _f(0.05, 0.0), "volumes": _vsel(),
        }}

    def run(self, geo, operation, distance, volumes):
        return (_vo.reshape_sdf(geo, operation, distance, volumes),)



@_node("modify")
class PCG_VolumeSmoothSDF:
    """
    Maps to: VDB Smooth SDF (new in pcg100 s9; this row used to point to Volume Blur, but none of Houdini's four
    Operations is our gaussian / box). Mean Value (cube mean) / Median Value
    (true cube median) / Mean Curvature Flow / Laplacian Flow; Filter Voxel Radius is in voxels;
    Alpha Mask uses the first volume of the second input (Min / Max Cutoff remapping, invertible) to blend per voxel.
    Different from Houdini: OpenVDB redistances within the narrow band after each iteration; that isn't done here -- for |∇φ| = 1 follow with
    Reshape SDF's redistance; Trim is meaningless on dense grids, not done. SDF only (fog raises an error).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "volumes": _vsel(),
            "operation": (list(_vo.SMOOTH_SDF_OPS),),
            "filter_voxel_radius": _i(1, 0, 16), "iterations": _i(1, 0, 1000),
            "use_mask": _b(False), "invert_mask": _b(False),
            "min_mask_cutoff": _f(0.0), "max_mask_cutoff": _f(1.0),
        }, "optional": {"mask": (GEO,)}}

    def run(self, geo, volumes, operation, filter_voxel_radius, iterations, use_mask,
            invert_mask, min_mask_cutoff, max_mask_cutoff, mask=None):
        return (_vo.smooth_sdf(geo, operation, filter_voxel_radius, iterations, volumes,
                               mask, use_mask, invert_mask, min_mask_cutoff,
                               max_mask_cutoff),)



@_node("modify", _WITH_REPORT)
class PCG_BooleanFracture:
    """
    Maps to: Boolean Fracture (new in pcg100 s9; used to point to Boolean's shatter mode). The cutting geometry of the second input
    cuts the first input into fragments, one per connected piece: name = prefix + number (or Appended to the original name), piece,
    inside / outside face groups, inside/outside seam edge groups, piece / face groups inside the cutter, inside/outside normals.
    With cutting geometry as Surface, each connected sheet is extruded into a half-space along its average normal before the boolean -- requiring the cutting surface to pass through the whole object
    and not fold back along the average normal (unlike Houdini: a surface cutting only halfway in still cuts the object in two here).
    The backend is manifold3d, requiring closed manifold input; point / vertex attributes aren't carried over (prim attributes and prim groups are carried by origin).
    """
    @classmethod
    def INPUT_TYPES(cls):
        from .geo import boolfracture as _bf, voronoi as _vr
        return {"required": {
            "geo": (GEO,), "cutter": (GEO,), "group": _group("Only cut these faces; faces outside the group are appended as is"),
            "name_mode": (list(_vr.NAME_MODES),), "fracture_namespace": _s(""),
            "piece_prefix": _s("piece"),
            "compute_interior_normals": _b(True), "interior_cusp_angle": _f(40.0, 0.0, 180.0),
            "exterior_normals": (list(_vr.EXTERIOR_NORMALS),),
            "exterior_cusp_angle": _f(60.0, 0.0, 180.0),
            "attribute_prefix": _s(""), "piece_attribute": _s("piece"),
            "copy_cutter_attributes": _s(""),
            "interior_group": _s("inside"), "exterior_group": _s("outside"),
            "merge_groups": _b(True),
            "interior_seams": _s(""), "exterior_seams": _s(""),
            "pieces_inside": _s(""), "surface_inside": _s(""),
            "treat_cutter": (list(_bf.TREAT),), "detriangulate": (list(_bf.DETRI),),
        }}

    def run(self, geo, cutter, group, name_mode, fracture_namespace, piece_prefix,
            compute_interior_normals, interior_cusp_angle, exterior_normals,
            exterior_cusp_angle, attribute_prefix, piece_attribute, copy_cutter_attributes,
            interior_group, exterior_group, merge_groups, interior_seams, exterior_seams,
            pieces_inside, surface_inside, treat_cutter, detriangulate):
        from .geo import boolfracture as _bf
        g, r = _bf.boolean_fracture(
            geo, cutter, group, treat_cutter, detriangulate, name_mode, fracture_namespace,
            "name", piece_prefix, attribute_prefix, piece_attribute, interior_group,
            exterior_group, merge_groups, interior_seams, exterior_seams, pieces_inside,
            surface_inside, copy_cutter_attributes, compute_interior_normals,
            interior_cusp_angle, exterior_normals, exterior_cusp_angle)
        return (g, _rep(r))



@_node("generate")
class PCG_IsoOffset:
    """
    Maps to: IsoOffset (new in pcg100 s9; Convert's volume_sdf / volume_fog modes are unchanged).
    Geometry → SDF / Fog volume / offset iso-surface. Mode: ray_intersect (exact SDF, sign from pseudo-normals and flood
    fill, not rays) / minimum (unsigned) / point_cloud / implicit_box / implicit_sphere;
    Uniform Sampling (grid points along one axis / voxel edge length / given per axis); Offset (positive goes outward), Invert Sign,
    Override Bounds (or the second input's bounding box), Pad Bounds. Divs is the grid point count (Houdini uses voxel count).
    """
    @classmethod
    def INPUT_TYPES(cls):
        from .geo import isooffset as _io
        return {"required": {
            "geo": (GEO,),
            "output": (list(_io.OUTPUTS),), "mode": (list(_io.MODES),),
            "name": _s(""),
            "uniform_sampling": (list(_io.SAMPLING),),
            "uniform_divs": _i(30, 2, 1024),
            "divs_x": _i(30, 2, 1024), "divs_y": _i(30, 2, 1024), "divs_z": _i(30, 2, 1024),
            "div_size": _f(0.1, 1e-6),
            "override_bounds": _b(False),
            "min_x": _f(-1.0), "min_y": _f(-1.0), "min_z": _f(-1.0),
            "max_x": _f(1.0), "max_y": _f(1.0), "max_z": _f(1.0),
            "pad_bounds": _b(False),
            "offset": _f(0.0), "invert_sign": _b(False),
        }, "optional": {"bound": (GEO,)}}

    def run(self, geo, output, mode, name, uniform_sampling, uniform_divs, divs_x, divs_y,
            divs_z, div_size, override_bounds, min_x, min_y, min_z, max_x, max_y, max_z,
            pad_bounds, offset, invert_sign, bound=None):
        from .geo import isooffset as _io
        return (_io.iso_offset(geo, output, mode, uniform_sampling, uniform_divs,
                               (divs_x, divs_y, divs_z), div_size, offset, invert_sign,
                               override_bounds, (min_x, min_y, min_z), (max_x, max_y, max_z),
                               bound, pad_bounds, name),)



@_node("modify", _WITH_REPORT)
class PCG_IntersectionAnalysis:
    """
    Maps to: Intersection Analysis (new in pcg100 s9; Boolean's seam mode is unchanged). Places a point wherever triangles / polylines
    pass through each other (with only the first input connected = finds self-intersections; with two = between the two), recording on the point both sources'
    Input Number / Primitive Number / Primitive UVW (two of each: [the prim the edge belongs to, the prim of the triangle passed
    through]). Empty attribute name = not written (Houdini uses a toggle + name). Doesn't require closed manifolds.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group_a": _group(), "group_b": _group("Faces in the second input"),
            "input_attribute": _s("input"), "prim_attribute": _s("sourceprim"),
            "uvw_attribute": _s("sourceprimuv"),
        }, "optional": {"geo_b": (GEO,)}}

    def run(self, geo, group_a, group_b, input_attribute, prim_attribute, uvw_attribute,
            geo_b=None):
        from .geo import intersectanalysis as _ia
        g, r = _ia.intersection_analysis(geo, geo_b, group_a, group_b, input_attribute,
                                         prim_attribute, uvw_attribute)
        return (g, _rep(r))



@_node("convert", _WITH_REPORT)
class PCG_FileMerge:
    """
    Maps to: File Merge (new in pcg100 s9; Import Mesh reads one file at a time and is unchanged). $SLICE in the file name
    is replaced in turn by each number of Merge Range (start, end, inc, end inclusive), and the files read are combined in order. .npz is read as this plugin's
    geometry cache, the rest sniffed by Import Mesh's formats. Delete Points from Other Files deletes points whose slice point attribute
    differs from the current number; with Missing File = no_geometry, missing files are skipped (noted in the report).
    """
    @classmethod
    def INPUT_TYPES(cls):
        from .geo import filemerge as _fm
        return {"required": {
            "file": _s("geo.$SLICE.npz"),
            "merge_start": _i(0, -1 << 20, 1 << 20), "merge_end": _i(3, -1 << 20, 1 << 20),
            "merge_inc": _i(1, -1 << 20, 1 << 20),
            "merge_variable": _s("SLICE"),
            "delete_other": _b(False),
            "missing_file": (list(_fm.MISSING),),
            "reload": _i(0, 0, 1 << 30),
        }}

    @classmethod
    def IS_CHANGED(cls, file="", merge_start=0, merge_end=3, merge_inc=1,
                   merge_variable="SLICE", reload=0, **kw):
        """
        Each file's mtime + size is the fingerprint (as in Import Mesh: same file name with changed content must recompute too).
        This must not raise -- it's called before execution, and if it raises the whole graph can't be queued.
        """
        from .geo import filemerge as _fm, meshio as _mio
        out = [str(reload)]
        try:
            for k in _fm.slices(merge_start, merge_end, merge_inc):
                try:
                    st = os.stat(_mio.resolve(_fm.expand(file, merge_variable, k)))
                    out.append(f"{st.st_mtime_ns}:{st.st_size}")
                except Exception:
                    out.append("-")
        except Exception:
            out.append(str(file))
        return "|".join(out)

    def run(self, file, merge_start, merge_end, merge_inc, merge_variable, delete_other,
            missing_file, reload):
        from .geo import filemerge as _fm
        g, r = _fm.file_merge(file, merge_start, merge_end, merge_inc, merge_variable,
                              delete_other, missing_file)
        r["reload"] = int(reload)      # reload only serves to change IS_CHANGED and force a re-read; recorded in the report
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Transforms and correspondence
def _v3(prefix, d):
    return {f"{prefix}_x": _f(d[0]), f"{prefix}_y": _f(d[1]), f"{prefix}_z": _f(d[2])}


@_node("modify", ((GEO, "point"), (GEO, "geo"), ("STRING", "report")))
class PCG_ExtractTransform:
    """
    Maps to: Extract Transform. reference and target are the same geometry before and after a transform (point numbers correspond one to one);
    solves the best rigid (Kabsch) / similarity (Umeyama, plus uniform scale) / affine transform. The point output
    is one instance point (P / orient / pscale, or transform when affine); copying reference with Copy to Points
    lands it on target; the geo output is reference transformed directly. The report has the residual RMS.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "reference": (GEO,), "target": (GEO,), "mode": (list(_rg.XF_MODES),),
            "weight_attribute": _names("attrib", "point", ""),
            # ── pcg100 additions (Houdini Extract Transform), defaults = old behaviour
            "use_piece_attribute": _b(False),
            "piece_attribute": _names("attrib", "prim", "name"),
            "attribute_class": (list(_rg.XF_CLASSES),),
            "output_attributes": (list(_rg.XF_OUTPUTS),),
            "compute_distortion": _b(False),
            "distortion_attribute": _s("distortion"),
        }}

    def run(self, reference, target, mode, weight_attribute, use_piece_attribute=False,
            piece_attribute="name", attribute_class="prim", output_attributes="standard",
            compute_distortion=False, distortion_attribute="distortion"):
        pt, g, r = _rg.extract_transform(
            reference, target, mode, weight_attribute,
            piece_attribute=piece_attribute if use_piece_attribute else "",
            piece_class=attribute_class, output=output_attributes,
            distortion_attrib=distortion_attribute if compute_distortion else "")
        return (pt, g, _rep(r))


@_node("attribute", ((GEO, "template"), (GEO, "rest_points"), ("STRING", "report")))
class PCG_AttribTransformExtract:
    """
    Maps to: Attribute Transform Extract (per-piece Extract Transform). rest and animated
    have the same topology; split into pieces by name, one rigid transform solved per piece. Outputs two sets of points: template (centre of the animated piece +
    orient) and rest_points (centre of the rest piece) -- connect them directly to Transform Pieces' template and
    rest, and another geometry (high-res fragments) follows exactly piece by piece.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "rest": (GEO,), "animated": (GEO,),
            "piece_attribute": _names("attrib", "prim", "name"),
        }}

    def run(self, rest, animated, piece_attribute):
        t, rp, r = _rg.attribute_transform_extract(rest, animated, piece_attribute)
        return (t, rp, _rep(r))


@_node("modify")
class PCG_MatchAxis:
    """
    Maps to: Match Axis. Rotates From Axis to To Axis by the minimal rotation (about origin / centroid /
    bbox_center); with Up From / Up To given (non-zero) it then rotates about the main axis so up matches too. N / up / v /
    orient rotate along.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,)}
        req.update(_v3("from", (0, 1, 0)))
        req.update(_v3("to", (0, 0, 1)))
        req["pivot"] = (list(_rg.PIVOTS),)
        req.update(_v3("up_from", (0, 0, 0)))
        req.update(_v3("up_to", (0, 0, 0)))
        req["group"] = _group()
        return {"required": req}

    def run(self, geo, from_x, from_y, from_z, to_x, to_y, to_z, pivot,
            up_from_x, up_from_y, up_from_z, up_to_x, up_to_y, up_to_z, group):
        return (_rg.match_axis(geo, (from_x, from_y, from_z), (to_x, to_y, to_z),
                               pivot, (up_from_x, up_from_y, up_from_z),
                               (up_to_x, up_to_y, up_to_z), group),)


@_node("modify")
class PCG_Primitive:
    """
    Maps to: Primitive. Each selected prim is translated / rotated (ZYX, degrees) / scaled about its own centre, then moved along
    its own normal by Normal Offset; if Scale Attribute is given it is further multiplied by that prim attribute. Unshare
    Points first splits the selected prims' points apart (otherwise shared points get dragged by the last prim).
    pcg100 additions to match Houdini: Transform Order / Rotate Order / Shear / Pivot (relative to the prim centre);
    the Attributes tab's Color / Alpha (Keep / Add / Remove, writing prim attributes Cd / Alpha); the Face/Hull tab's
    Close U (open / closed) and Vertex (Reverse / Shift …, the same implementation as the Reverse node).
    (The "ZYX" written above is wrong: it has actually always been Rx Ry Rz, i.e. Rotate Order = xyz.)
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "group": _group()}
        req.update(_v3("translate", (0, 0, 0)))
        req.update(_v3("rotate", (0, 0, 0)))
        req.update(_v3("scale", (1, 1, 1)))
        req.update({"uniform_scale": _f(1.0), "scale_attribute":
                    _names("attrib", "prim", ""), "normal_offset": _f(0.0),
                    "unshare_points": _b(True)})
        # pcg100 additions (defaults = the previous behaviour)
        req.update({"xform_order": (list(_ops.XFORM_ORDERS),),
                    "rotate_order": (list(_ops.ROTATE_ORDERS),),
                    "shear_xy": _f(0.0), "shear_xz": _f(0.0), "shear_yz": _f(0.0)})
        req.update(_v3("pivot", (0, 0, 0)))
        req.update({"color_mode": (list(_d2.PRIM_ATTR_MODES),),
                    "color_r": _f(1.0, 0.0, 1e6, 0.01), "color_g": _f(1.0, 0.0, 1e6, 0.01),
                    "color_b": _f(1.0, 0.0, 1e6, 0.01),
                    "alpha_mode": (list(_d2.PRIM_ATTR_MODES),),
                    "alpha": _f(1.0, 0.0, 1.0, 0.01),
                    "close_u": (list(_d2.PRIM_CLOSE),),
                    "vertex_op": (list(_d2.PRIM_VERTEX_OPS),),
                    "u_offset": _i(0, -(1 << 20), 1 << 20),
                    "v_offset": _i(0, -(1 << 20), 1 << 20)})
        return {"required": req}

    def run(self, geo, group, translate_x, translate_y, translate_z, rotate_x,
            rotate_y, rotate_z, scale_x, scale_y, scale_z, uniform_scale,
            scale_attribute, normal_offset, unshare_points,
            xform_order="srt", rotate_order="xyz", shear_xy=0.0, shear_xz=0.0,
            shear_yz=0.0, pivot_x=0.0, pivot_y=0.0, pivot_z=0.0,
            color_mode="keep", color_r=1.0, color_g=1.0, color_b=1.0,
            alpha_mode="keep", alpha=1.0, close_u="no_change", vertex_op="none",
            u_offset=0, v_offset=0):
        return (_d2.primitive(geo, group, (translate_x, translate_y, translate_z),
                              (rotate_x, rotate_y, rotate_z),
                              (scale_x, scale_y, scale_z), uniform_scale,
                              scale_attribute, normal_offset, unshare_points,
                              xform_order, rotate_order,
                              (shear_xy, shear_xz, shear_yz),
                              (pivot_x, pivot_y, pivot_z),
                              color_mode, (color_r, color_g, color_b),
                              alpha_mode, alpha, close_u, vertex_op,
                              u_offset, v_offset),)


@_node("attribute", _WITH_REPORT)
class PCG_AttribReorient:
    """
    Maps to: Attribute Reorient. The geometry deformed but N / up / v / orient are still pre-deformation: the vector attributes are rotated by each point's
    one-ring local rotation (Kabsch) from rest → deformed, quaternions left-multiplied. Attributes are read from
    deformed (from rest if absent).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "rest": (GEO,),
            "attributes": _s(_d2.REORIENT_DEFAULT),
        }}

    def run(self, geo, rest, attributes):
        g, r = _d2.attribute_reorient(geo, rest, attributes)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_MatchTopology:
    """
    Maps to: Match Topology. geo and reference are the same mesh but with point / prim numbers / start corners scrambled:
    topology mode walks the whole mesh in sync across opposite edges starting from a pair of seed corners (ignoring positions, so any deformation works; seeds
    left at −1 are found automatically), position mode matches by nearest point. Outputs geo renumbered to match reference.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "reference": (GEO,), "mode": (list(_rg.MT_MODES),),
            "ref_prim": _i(-1, -1, 1 << 30), "ref_point": _i(-1, -1, 1 << 30),
            "geo_prim": _i(-1, -1, 1 << 30), "geo_point": _i(-1, -1, 1 << 30),
            "tolerance": _f(1e-4, 0.0, 1e6, 1e-5),
        }}

    def run(self, geo, reference, mode, ref_prim, ref_point, geo_prim, geo_point,
            tolerance):
        g, r = _rg.match_topology(reference, geo, mode, ref_prim, ref_point,
                                  geo_prim, geo_point, tolerance)
        return (g, _rep(r))


@_node("deform", _WITH_REPORT)
class PCG_TopoTransfer:
    """
    Maps to: Topo Transfer. Fits geo's edge flow onto target's shape: first aligns (a similarity transform if landmark point groups are given,
    otherwise by bounding box), then iterates "project onto target's surface + smooth the displacement field", with smoothing weakening each round
    and the final round a pure projection -- all points end up on target, edge flow density is kept, no flipped faces. landmark is an integer point attribute
    present on both sides; points with equal values (≥ 0) are paired and pinned every round.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "target": (GEO,), "iterations": _i(20, 1, 1000),
            "smoothing": _i(10, 0, 1000), "stiffness": _f(0.5, 0.0, 1.0),
            "landmark_attribute": _names("attrib", "point", "landmark"),
            "prealign": _b(True),
        }}

    def run(self, geo, target, iterations, smoothing, stiffness,
            landmark_attribute, prealign):
        g, r = _rg.topo_transfer(geo, target, iterations, smoothing, stiffness,
                                 landmark_attribute, prealign)
        return (g, _rep(r))


@_node("deform", _WITH_REPORT)
class PCG_DeltaMush:
    """
    Maps to: DeltaMush. geo is deformed, rest is pre-deformation (same topology): both are smoothed, rest's detail
    is recorded in the smoothed frames and reapplied onto the smoothed geo -- local damage from deformation is smoothed out and detail comes back
    as in rest; under overall rigid motion the result exactly equals geo. The Mask point attribute controls how much correction each point gets.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "rest": (GEO,), "iterations": _i(10, 0, 1000),
            "step": _f(0.5, 0.0, 1.0), "pin_boundary": _b(True),
            "mask_attribute": _names("attrib", "point", ""),
        }}

    def run(self, geo, rest, iterations, step, pin_boundary, mask_attribute):
        g, r = _d2.delta_mush(geo, rest, iterations, step, pin_boundary,
                              mask_attribute)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Mesh editing (pcg74)
def _edges_in():
    return _names("group", "edge", "", "Edge group name (Group Create's edge section / Group Find Path can make one)")


@_node("modify", _WITH_REPORT)
class PCG_EdgeEqualize:
    """
    Maps to: Edge Equalize. Edge-group edges are chained, and points are redistributed along **the original polyline** into equal-length segments (polyline shape
    unchanged): arc_length makes arc lengths along the line equal, chord makes straight-line distances equal. Open chain ends stay put; for pure closed loops the phase that
    "moves the least" is chosen; loops through branch points pin the branch points.
    pcg100: Method gains Houdini's three modes (target edge length = mean / longest / shortest of the selected edges, each edge scaled about its midpoint, shared points
    averaged and iterated to convergence -- the shape changes, and the total length with it); Group Type (Guess / Edges / Points / Primitives,
    only read in the three Houdini modes); Output Edge Group (written in all modes).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _edges_in(),
            "measure": (list(_me.EQUALIZE_MEASURES),),
            # pcg100 addition: Houdini's Method (target length = mean / longest / shortest of the selected edges); default redistribute = old behaviour
            "method": (list(_me.EQUALIZE_METHODS),),
            "group_type": (list(_me.EQUALIZE_GROUP_TYPES),),
            "output_edge_group": _s(""),
        }}

    def run(self, geo, edges, measure, method="redistribute", group_type="guess",
            output_edge_group=""):
        if method != "redistribute":
            g, r = _me.edge_equalize_hou(geo, edges, method, group_type, output_edge_group)
            return (g, _rep(r))
        g, r = _me.edge_equalize(geo, edges, measure)
        if str(output_edge_group).strip():
            # The old mode also writes Output Edge Group: the edges on the chains that moved (= the edges in Edges)
            from .geo.groups import resolve_edges as _re
            g.set_edge_group(str(output_edge_group).strip(), _re(geo, edges))
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_EdgeStraighten:
    """
    Maps to: Edge Straighten. Each open chain in the edge group is pulled straight, endpoints fixed. spacing: preserve (by the original
    arc length ratios) / uniform (equal division) / project (perpendicular projection). Closed loops are skipped, counted in the report.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _edges_in(),
            "spacing": (list(_me.STRAIGHTEN_SPACING),),
        }}

    def run(self, geo, edges, spacing):
        g, r = _me.edge_straighten(geo, edges, spacing)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_CircleFromEdges:
    """
    Maps to: Circle from Edges. Each closed loop in the edge group is laid out as a perfect circle: centre = mean of the points, plane = the loop's
    Newell normal (point order kept), radius average / min / max / custom; Even Spacing
    distributes at equal angles (phase chosen to move the least), Rotate turns the whole thing further. Open chains are skipped.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _edges_in(),
            "radius_mode": (list(_me.RADIUS_MODES),),
            "radius": _f(1.0, 0.0, 1e6, 0.01), "even_spacing": _b(True),
            "rotate": _f(0.0, -360.0, 360.0, 1.0),
        }}

    def run(self, geo, edges, radius_mode, radius, even_spacing, rotate):
        g, r = _me.circle_from_edges(geo, edges, radius_mode, radius,
                                     even_spacing, rotate)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_EdgeFlip:
    """
    Maps to: Edge Flip. rotate: the two faces sharing the edge form one ring, and the edge rotates Cycles steps around the ring (two
    triangles = flip the diagonal; two quads = rotate the edge), face side counts unchanged; delaunay: only flips edges of triangle pairs whose opposite angles
    sum > 180°, until nothing is left to flip; edges with a dihedral angle above Max Angle aren't flipped. Empty Edges = all edges.
    Flipped edges are replaced by the new edges in the edge group of the same name.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _names("group", "edge", "",
                                           "Empty = all edges"),
            "mode": (list(_me.FLIP_MODES),), "cycles": _i(1, -64, 64),
            "max_angle": _f(10.0, 0.0, 180.0, 1.0),
        }}

    def run(self, geo, edges, mode, cycles, max_angle):
        g, r = _me.edge_flip(geo, edges, mode, cycles, max_angle)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_TriDivide:
    """
    Maps to: Tri Divide. Triangulates the selected faces, then subdivides by longest-edge bisection (LEPP) until edge length ≤ Max Edge
    Length and area ≤ Max Area (0 = unlimited): both sides are split together, no T-junctions, shape unchanged, and the minimum angle doesn't keep
    degrading. Unselected neighbouring faces only get the midpoints inserted. With Delaunay on, Lawson edge flips are done at the end (only edges with dihedral angle ≤ Flip
    Angle are flipped).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "max_edge_length": _f(0.0, 0.0, 1e6, 0.01),
            "max_area": _f(0.0, 0.0, 1e12, 0.01), "delaunay": _b(True),
            "flip_angle": _f(1.0, 0.0, 180.0, 0.5),
        }}

    def run(self, geo, group, max_edge_length, max_area, delaunay, flip_angle):
        g, r = _me.tri_divide(geo, group, max_edge_length, max_area, delaunay,
                              flip_angle)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_Unsubdivide:
    """
    Maps to: Unsubdivide. Recognises the original vertices / edge points / face points left by Catmull-Clark subdivision and rewinds the topology by one level
    (Levels levels). Positions = fit inverts by least squares on the subdivision stencils -- if it really came from subdivision, the original mesh is exactly
    restored; keep leaves the original vertices at their subdivided positions (Houdini's approach, the shape shrinks a bit). Boundary must match
    the one used when subdividing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "levels": _i(1, 1, 6),
            "positions": (list(_us.POSITIONS),),
            "boundary": (list(_us.BOUNDARY),),
        }}

    def run(self, geo, levels, positions, boundary):
        g, r = _us.unsubdivide(geo, levels, positions, boundary)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_RewireVertices:
    """
    Maps to: Rewire Vertices. An integer attribute (on vertices first, otherwise on points) gives the point number each
    vertex should be rewired to; −1 / out-of-range ones are unchanged. Optionally removes consecutive duplicate corners and faces that can't stand,
    and deletes unused points.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "vertex", "rewire_to"),
            "keep_unused_points": _b(True), "remove_degenerate": _b(False),
        }}

    def run(self, geo, attribute, keep_unused_points, remove_degenerate):
        g, r = _me.rewire_vertices(geo, attribute, keep_unused_points,
                                   remove_degenerate)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_PolyCut:
    """
    Maps to: PolyCut. Cuts faces / polylines into polylines along edges: cut_points breaks at the points of the point group; keep_points keeps only
    edges with both ends in the point group; threshold inserts points where a point attribute crosses the threshold (shared by adjacent faces), Keep chooses all (just
    break) / above / below. Closed faces not cut at all are kept as is.
    pcg100: Strategy gains remove / cut at the end, which are Houdini PolyCut's own semantics (the three modes above are
    this plugin's originals; Houdini doesn't have them): finds "failing edges" by Cut Attribute (Detect Edge Changes: crossing
    Cut Value / change above Cut Threshold; empty attribute = all edges); with Type = points it deletes / breaks at their
    two endpoints, with Type = edges it deletes the edge / breaks it in the middle. In these two modes Points = Houdini's
    Cut Points (empty = all points), Threshold = Cut Value, Keep is not read.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(), "mode": (list(_me.CUT_MODES),),
            "points": _names("group", "point", ""),
            "attribute": _names("attrib", "point", ""),
            "threshold": _f(0.5), "keep": (list(_me.CUT_KEEP),),
            # pcg100 addition: only read by Houdini's Strategy (mode = remove / cut)
            "cut_type": (list(_me.CUT_TYPES),),
            "cut_edges": _names("group", "edge", ""),
            "detect": (list(_me.CUT_DETECT),),
            "cut_threshold": _f(0.1, 0.0, 1e9, 0.01),
            "keep_closed": _b(False),
        }}

    def run(self, geo, group, mode, points, attribute, threshold, keep,
            cut_type="points", cut_edges="", detect="crossing", cut_threshold=0.1,
            keep_closed=False):
        g, r = _me.poly_cut(geo, group, mode, points, attribute, threshold,
                            keep, cut_type, cut_edges, detect, cut_threshold,
                            keep_closed)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_PolyStitch:
    """
    Maps to: PolyStitch. Stitches seams between patches of different resolution: border points within ≤ Tolerance of each other are welded; with Snap on,
    remaining border points snap onto others' border edges; points landing on an edge are inserted into that edge's faces -- T-junctions at the seam vanish and
    both sides share the same chain of points. The report has the number of remaining border edges.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "tolerance": _f(1e-3, 0.0, 1e6, 1e-4), "snap": _b(True),
        }}

    def run(self, geo, group, tolerance, snap):
        g, r = _me.poly_stitch(geo, group, tolerance, snap)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_VoronoiSplit:
    """
    Maps to: Voronoi Split. Cuts the surface by the Voronoi cells of Cell Points (cutting on the bisector planes, shape unchanged;
    faces lying entirely in one cell are untouched). With Split Points on each piece has its own points (truly separated); off,
    both sides of a cut share points. Writes the prim attributes cell and Piece Attribute ("piece<k>"); if Cut Group is given a
    name, the cuts are written as an edge group.
    pcg100 s9 adds Houdini's Weight Attribute + Method (Power Distance / Ratio) and Offset.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "cell_points": (GEO,), "group": _group(),
            "split_points": _b(True),
            "piece_attribute": _s("name"), "cut_group": _s(""),
            # pcg100 s9 additions (placed last, old workflow indices unchanged)
            "use_weight": _b(False), "weight_attribute": _s("weight"),
            "method": (list(_vs.METHODS),), "offset": _f(0.0),
        }}

    def run(self, geo, cell_points, group, split_points, piece_attribute,
            cut_group, use_weight=False, weight_attribute="weight", method="power",
            offset=0.0):
        g, r = _vs.voronoi_split(geo, cell_points, group, split_points,
                                 piece_attribute, cut_group, use_weight,
                                 weight_attribute, method, offset)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Curves and surfaces (pcg75)
@_node("modify", _WITH_REPORT)
class PCG_CircleSpline:
    """
    Maps to: Circle Spline. Arcs through each three adjacent points blended pairwise (w = sin²(πt/2)): the curve passes through every point,
    and its tangent and curvature at a point are exactly those of the circle through the previous, current and next points (G2); when all points lie on a circle the result is that circle,
    and where three points are collinear it's a straight line. Divisions samples per segment; other numeric point attributes are interpolated linearly per segment.
    pcg100: Spline Type gains Helix (one helix per three points, axis by Helix Type: Directional / Balanced / Blended);
    the point attribute splinetype can override per point; Adjust by Pseudo-Arclength (same point count, evened out by arc length); outputs curveu /
    tangent. Houdini's Hybrid and Ellipse have no definition in the docs; not done.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(), "divisions": _i(8, 1, 1024),
            # pcg100 addition (default = the previous behaviour: Circle)
            "spline_type": (list(_c2.CIRCLE_TYPES),),
            "override_with_attrib": ("BOOLEAN", {"default": False}),
            "helix_type": (list(_c2.HELIX_TYPES),),
            "adjust_arclength": ("BOOLEAN", {"default": False}),
            "arclength_samples": _i(4, 0, 1000),
            "use_curveu": ("BOOLEAN", {"default": False}),
            "curveu_name": _s("curveu"),
            "use_tangent": ("BOOLEAN", {"default": False}),
            "tangent_name": _s("tangentu"),
        }}

    def run(self, geo, group, divisions, spline_type="circle", override_with_attrib=False,
            helix_type="directional", adjust_arclength=False, arclength_samples=4,
            use_curveu=False, curveu_name="curveu", use_tangent=False, tangent_name="tangentu"):
        g, r = _c2.circle_spline(geo, group, divisions, spline_type, override_with_attrib,
                                 helix_type, adjust_arclength, arclength_samples,
                                 curveu_name.strip() if use_curveu else "",
                                 tangent_name.strip() if use_tangent else "")
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_PolySpline:
    """
    Maps to: PolySpline. Polyline -> smooth spline polyline: catmull_rom passes through the points (Alpha 0 uniform / 0.5 centripetal /
    1 chordal), bspline approximates (C2, not through interior points), interpolate passes through the points with C2 (solving a tridiagonal system for control points).
    Open curves pass through both endpoints; numeric point attributes use the same weights as P.
    pcg100 additions to match Houdini: Spline Type gains bezier / degree2_bezier (points as control points), cardinal
    (CV Tension), linear; Close (Off / On / If polygon does); Division Method (resampling by equal chord length / equal X /
    equal Y / equal Z, Segment Length or Output Divisions); First / Last CV Count.
    Special Bezier / Special Smooth Bezier have no definition in the docs; not done.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "basis": (list(_c2.SPLINE_BASES),),
            "alpha": _f(0.5, 0.0, 1.0, 0.05), "divisions": _i(8, 1, 1024),
            # pcg100 additions (defaults = the previous behaviour)
            "close": (list(_c2.SPLINE_CLOSE), {"default": "if_polygon_does"}),
            "division_method": (list(_c2.SPLINE_DIVISION),),
            "segment_length": _f(0.0, 0.0, 1e6, 0.01),
            "output_divisions": _i(0, 0, 1 << 20),
            "first_cv_count": _i(1, 1, 64), "last_cv_count": _i(1, 1, 64),
            "tension": _f(0.5, -10.0, 10.0, 0.05),
        }}

    def run(self, geo, group, basis, alpha, divisions, close="if_polygon_does",
            division_method="standard", segment_length=0.0, output_divisions=0,
            first_cv_count=1, last_cv_count=1, tension=0.5):
        g, r = _c2.poly_spline(geo, group, basis, alpha, divisions, close,
                               division_method, segment_length, output_divisions,
                               first_cv_count, last_cv_count, tension)
        return (g, _rep(r))


@_node("generate", _WITH_REPORT)
class PCG_BallisticPath:
    """
    Maps to: Ballistic Path. Launches a projectile from each point and outputs the trajectory polyline (time, v on points; srcpoint on prims).
    velocity uses the point attribute v; target_time / target_angle aim at the points of targets (paired by index),
    solving the initial velocity from a given flight time or elevation angle. Linear air drag has an analytic solution; Ground truncates at the ground (exact landing point),
    and with collision connected it truncates at the first collision point.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "group": _group(),
               "mode": (list(_c2.BALLISTIC_MODES),),
               "v_attribute": _names("attrib", "point", "v")}
        req.update(_v3("gravity", (0.0, -9.8, 0.0)))
        req.update({"drag": _f(0.0, 0.0, 100.0, 0.01),
                    "duration": _f(2.0, 0.0, 1e6, 0.1),
                    "flight_time": _f(1.0, 0.0, 1e6, 0.1),
                    "launch_angle": _f(45.0, -89.0, 89.0, 1.0),
                    "samples": _i(32, 2, 100000), "ground": _b(False),
                    "ground_height": _f(0.0)})
        return {"required": req,
                "optional": {"targets": (GEO,), "collision": (GEO,)}}

    def run(self, geo, group, mode, v_attribute, gravity_x, gravity_y,
            gravity_z, drag, duration, flight_time, launch_angle, samples,
            ground, ground_height, targets=None, collision=None):
        g, r = _c2.ballistic_path(geo, group, mode, targets, v_attribute,
                                  (gravity_x, gravity_y, gravity_z), drag,
                                  duration, flight_time, launch_angle, samples,
                                  ground, ground_height, collision)
        return (g, _rep(r))


@_node("generate", _WITH_REPORT)
class PCG_PolyLoft:
    """
    Maps to: PolyLoft. Connects **using existing points**: faces lays faces between adjacent curves (quads with equal point counts,
    zipped triangles by arc length otherwise), cross_lines connects the i-th point of each curve into cross lines, grid_lines is
    a network of cross lines + the original curves. Wrap also connects the last curve to the first. Not a single new point is created.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(), "form": (list(_c2.LOFT_FORMS),),
            "wrap": _b(False), "keep_original": _b(True),
        }}

    def run(self, geo, group, form, wrap, keep_original):
        g, r = _c2.poly_loft(geo, group, form, wrap, keep_original)
        return (g, _rep(r))


@_node("generate", _WITH_REPORT)
class PCG_CrossSectionSurface:
    """
    Maps to: Cross Section Surface. A network woven from two families of curves, sections and guides -> a Gordon surface
    (lofting each family and summing, minus the tensor interpolation of the intersection points): the surface passes exactly through every curve in the network.
    Interpolation chooses cubic (Catmull-Rom) or linear; when curves are closed the surface closes in that direction.
    Without guides it's a loft along sections. Outputs a quad mesh + point attribute uv.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "sections": (GEO,), "group": _group(),
            "interpolation": (list(_c2.CSS_INTERP),),
            "divisions_s": _i(8, 1, 1024), "divisions_t": _i(8, 1, 1024),
        }, "optional": {"guides": (GEO,)}}

    def run(self, sections, group, interpolation, divisions_s, divisions_t,
            guides=None):
        g, r = _c2.cross_section_surface(sections, guides, group, "",
                                         interpolation, divisions_s,
                                         divisions_t)
        return (g, _rep(r))


@_node("generate", _WITH_REPORT)
class PCG_CrossSectionSurfaceHou:
    """
    Maps to: Houdini's Cross Section Surface (new in pcg100). Not the same as PCG_CrossSectionSurface above
    (Gordon surface: two families of curves, resampling, interpolation), which is kept unchanged.
    This follows Houdini: = Sweep with only cross sections. Each section is a row of the mesh and the c-th point on a section is column c,
    connected **using the existing points on the sections** (no resampling, no interpolation), so all sections must have the same point count (error otherwise).
    All sections closed → a tube; Close Implicit Backbone Curve → the last connects back to the first.
    Surface Type chooses among points / rows / columns / quads / triangles variants; end caps Single Polygon / Grid (hemisphere, cone,
    concave, Scale + Roundness) / Side Single Polygon; UV via Houdini's set of toggles (length weighted, normalised,
    rounded for seamless, flipped, scaled), written on vertices for polygon output; empty attribute names for row / column number and section number = not written.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Prims to use as cross sections (ordered into rows by prim number)"),
            "reverse_cross_sections": ("BOOLEAN", {"default": False}),
            "end_cap_type": (list(_xs.CSS_CAPS),),
            "cap_divisions": _i(3, 1, 1000),
            "triangular_poles": ("BOOLEAN", {"default": False}),
            "end_cap_scale": _f(1.0, -1e6, 1e6, 0.05),
            "end_cap_roundness": _f(1.0, -10.0, 10.0, 0.05),
            "end_caps_group": ("STRING", {"default": ""}),
            "surface_type": (list(_xs.CSS_SURFACES), {"default": "quads"}),
            "unique_seam_vertices": ("BOOLEAN", {"default": False}),
            "swap_rows_cols": ("BOOLEAN", {"default": False}),
            "close_backbone": ("BOOLEAN", {"default": False}),
            "compute_uvs": ("BOOLEAN", {"default": False}),
            "override_uvs": ("BOOLEAN", {"default": False}),
            "length_weighted_uvs": ("BOOLEAN", {"default": True}),
            "normalize_u": ("BOOLEAN", {"default": True}),
            "normalize_v": ("BOOLEAN", {"default": False}),
            "wrap_u": ("BOOLEAN", {"default": True}),
            "wrap_v": ("BOOLEAN", {"default": True}),
            "use_max_length": ("BOOLEAN", {"default": False}),
            "flip_u": ("BOOLEAN", {"default": True}),
            "uv_scale_u": _f(1.0, -1e6, 1e6, 0.05), "uv_scale_v": _f(1.0, -1e6, 1e6, 0.05),
            "from_cross_sections": ("STRING", {"default": "*"}),
            "point_row_attrib": ("STRING", {"default": ""}),
            "point_col_attrib": ("STRING", {"default": ""}),
            "prim_row_attrib": ("STRING", {"default": ""}),
            "prim_col_attrib": ("STRING", {"default": ""}),
            "cross_section_num_attrib": ("STRING", {"default": ""}),
        }}

    def run(self, geo, group, reverse_cross_sections, end_cap_type, cap_divisions,
            triangular_poles, end_cap_scale, end_cap_roundness, end_caps_group, surface_type,
            unique_seam_vertices, swap_rows_cols, close_backbone, compute_uvs, override_uvs,
            length_weighted_uvs, normalize_u, normalize_v, wrap_u, wrap_v, use_max_length,
            flip_u, uv_scale_u, uv_scale_v, from_cross_sections, point_row_attrib,
            point_col_attrib, prim_row_attrib, prim_col_attrib, cross_section_num_attrib):
        g, r = _xs.cross_section_grid(
            geo, group, reverse_cross_sections, end_cap_type, cap_divisions, triangular_poles,
            end_cap_scale, end_cap_roundness, end_caps_group, surface_type, unique_seam_vertices,
            swap_rows_cols, close_backbone, compute_uvs, override_uvs, length_weighted_uvs,
            normalize_u, normalize_v, wrap_u, wrap_v, use_max_length, flip_u,
            (uv_scale_u, uv_scale_v), from_cross_sections, point_row_attrib, point_col_attrib,
            prim_row_attrib, prim_col_attrib, cross_section_num_attrib)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Attributes, groups, points (pcg76)
@_node("attribute", _WITH_REPORT)
class PCG_AttribComposite:
    """
    Maps to: Attribute Composite. Composites the background attribute (geo) and foreground attribute (fg; geo itself when not connected) by blend
    mode: result = A + α·(blend(A,B) − A), α = Alpha × the foreground's Alpha attribute. over / add /
    subtract / multiply / divide / screen / overlay / min / max / difference / average.
    Foreground is paired by index or by attribute (id / name); unpaired elements are untouched.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute_class": (list(_ag.COMPOSITE_CLASSES),),
            "bg_attribute": _names("attrib", "point", "Cd"),
            "fg_attribute": _names("attrib", "point", "Cd"),
            "output": _s("Cd"), "mode": (list(_ag.COMPOSITE_MODES),),
            "alpha": _f(1.0, 0.0, 1.0, 0.01),
            "alpha_attribute": _names("attrib", "point", ""),
            "match": (list(_ag.MATCH_MODES),),
            "match_attribute": _names("attrib", "point", "id"),
        }, "optional": {"fg": (GEO,)}}

    def run(self, geo, attribute_class, bg_attribute, fg_attribute, output,
            mode, alpha, alpha_attribute, match, match_attribute, fg=None):
        g, r = _ag.attribute_composite(geo, fg, attribute_class, bg_attribute,
                                       fg_attribute, output, mode, alpha,
                                       alpha_attribute, match, match_attribute)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_AttribMirror:
    """
    Maps to: Attribute Mirror. Copies point attributes from one side of a plane to the other: points on the other side are mirrored across, and values taken from the nearest point
    (closest_point) or by barycentric interpolation on the source-side surface (surface); vector attributes are reflected by the plane, quaternions
    get H·R·H (still a proper rotation). Only point attributes are processed.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "attributes": _s("Cd")}
        req.update(_v3("origin", (0, 0, 0)))
        req.update(_v3("direction", (1, 0, 0)))
        req.update({"source_side": (list(_ag.MIRROR_SIDES),),
                    "lookup": (list(_ag.MIRROR_LOOKUPS),),
                    "vectors": _s("N v up"), "quaternions": _s("orient"),
                    "tolerance": _f(1e-6, 0.0, 1e6, 1e-6),
                    "max_distance": _f(0.0, 0.0, 1e6, 0.01), "group": _group()})
        return {"required": req}

    def run(self, geo, attributes, origin_x, origin_y, origin_z, direction_x,
            direction_y, direction_z, source_side, lookup, vectors,
            quaternions, tolerance, max_distance, group):
        g, r = _ag.attribute_mirror(geo, attributes,
                                    (origin_x, origin_y, origin_z),
                                    (direction_x, direction_y, direction_z),
                                    source_side, lookup, vectors, quaternions,
                                    tolerance, max_distance, group)
        return (g, _rep(r))


@_node("group", _WITH_REPORT)
class PCG_GroupFromAttribBoundary:
    """
    Maps to: Group from Attribute Boundary. Builds groups where attribute values change: prim attribute → edges between adjacent faces with different
    values; vertex attribute → edges whose corners differ on the two sides (uv seams); point attribute → edges whose endpoints differ.
    Group Type chooses edge group / endpoints / adjacent faces; Include Unshared also counts open borders.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "prim", "name"),
            "attribute_class": (list(_ag.BOUNDARY_CLASSES),),
            "group_name": _s("boundary"),
            "group_type": (list(_ag.BOUNDARY_TYPES),),
            "include_unshared": _b(False),
            "tolerance": _f(1e-5, 0.0, 1e6, 1e-5),
        }}

    def run(self, geo, attribute, attribute_class, group_name, group_type,
            include_unshared, tolerance):
        g, r = _ag.group_from_attribute_boundary(geo, attribute,
                                                 attribute_class, group_name,
                                                 group_type, include_unshared,
                                                 tolerance)
        return (g, _rep(r))


@_node("group", _WITH_REPORT)
class PCG_Partition:
    """
    Maps to: Partition. Builds one group per distinct attribute value; group name = $ATTR in Rule replaced by that value
    (characters not allowed in group names, from floats / minus signs / strings, are replaced; a leading digit gets a _ prefix).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "prim", "name"),
            "attribute_class": (list(_ag.PARTITION_CLASSES),),
            "rule": _s("grp_$ATTR"),
        }}

    def run(self, geo, attribute, attribute_class, rule):
        g, r = _ag.partition(geo, attribute, attribute_class, rule)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_TangentField:
    """
    Maps to: Tangent Field. The smoothest n-fold symmetric direction field on a surface (1 arrow / 2 lines / 4 crosses /
    6 snowflakes): adjacent points are compared by discrete transport, and the minimum energy is solved (with guides a constrained linear system, without them the
    smallest eigenvector). Guides come from a point vector attribute, or principal curvature directions (max / min_curvature, needs n ≥ 2).
    Outputs unit tangent vectors; the report has the singularity count and index sum (= n·χ on closed surfaces).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "symmetry": ([str(n) for n in _tf.SYMMETRIES],),
            "guide_attribute": _names("attrib", "point", ""),
            "guide_weight": _f(1.0, 0.0, 1e6, 0.1),
            "align": (list(_tf.ALIGN_MODES),), "output": _s("tangent"),
            "rand_seed": _i(0, 0, 1 << 30),
        }}

    def run(self, geo, symmetry, guide_attribute, guide_weight, align, output,
            rand_seed):
        g, r = _tf.tangent_field(geo, int(symmetry), guide_attribute,
                                 guide_weight, align, output, rand_seed)
        return (g, _rep(r))


@_node("scatter", _WITH_REPORT)
class PCG_AdaptivePrune:
    """
    Maps to: Adaptive Prune. Thins points so pairwise spacing ≥ radius (Radius × radius attribute, the larger of the two
    points): greedily keeps points by priority (random / larger attribute value first / lower point number first). Kept points don't conflict pairwise,
    and every deleted point is next to a kept point of higher priority. With Mode = group it only marks, doesn't delete.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(), "radius": _f(0.1, 0.0, 1e6, 0.01),
            "radius_attribute": _names("attrib", "point", ""),
            "priority": (list(_po.PRUNE_PRIORITY),),
            "priority_attribute": _names("attrib", "point", ""),
            "rand_seed": _i(0, 0, 1 << 30), "mode": (list(_po.PRUNE_MODES),),
            "group_name": _s("pruned"),
        }}

    def run(self, geo, group, radius, radius_attribute, priority,
            priority_attribute, rand_seed, mode, group_name):
        g, r = _po.adaptive_prune(geo, radius, radius_attribute, priority,
                                  priority_attribute, rand_seed, mode,
                                  group_name, group)
        return (g, _rep(r))


@_node("scatter", _WITH_REPORT)
class PCG_PointReplicate:
    """
    Maps to: Point Replicate. Scatters a cluster of points around each point (Count, or by attribute), radius Radius × radius
    attribute (default pscale); sphere / shell / disk (perpendicular to N) / gaussian. Each source point seeds its own random numbers by
    (Rand Seed, id), so adding or deleting points doesn't affect other clusters. New points inherit the source point's attributes and get source written.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(), "count": _i(10, 0, 100000),
            "count_attribute": _names("attrib", "point", ""),
            "radius": _f(0.1, 0.0, 1e6, 0.01),
            "radius_attribute": _names("attrib", "point", "pscale"),
            "shape": (list(_po.REPLICATE_SHAPES),),
            "rand_seed": _i(0, 0, 1 << 30), "keep_original": _b(False),
            # ── pcg100 additions (Houdini Point Replicate's Shape tab / Attributes tab), defaults = old behaviour
            "orientation": (list(_po.REPLICATE_PLANES),),
            **_v3("center", (0.0, 0.0, 0.0)),
            **_v3("size", (1.0, 1.0, 1.0)),
            "uniform_scale": _f(1.0, 0.0, 1e6, 0.01),
            "velocity_stretch": (list(_po.VELOCITY_STRETCH),),
            "velocity_scale": _f(1.0, -1e6, 1e6, 0.01),
            "copy_source_attributes": _b(True),
            "source_attributes": _names("attrib", "point", "*"),
            "inherit_velocity": _f(1.0, -1e6, 1e6, 0.01),
            "radial_velocity": _f(0.0, -1e6, 1e6, 0.01),
            "keep_source_attributes": _b(True),
            "source_point_attribute": _s("source"),
            "source_index_attribute": _s(""),
            "create_output_group": _b(False),
            "output_group": _s("replicated"),
        }}

    def run(self, geo, group, count, count_attribute, radius, radius_attribute,
            shape, rand_seed, keep_original, orientation="xy", center_x=0.0,
            center_y=0.0, center_z=0.0, size_x=1.0, size_y=1.0, size_z=1.0,
            uniform_scale=1.0, velocity_stretch="none", velocity_scale=1.0,
            copy_source_attributes=True, source_attributes="*", inherit_velocity=1.0,
            radial_velocity=0.0, keep_source_attributes=True,
            source_point_attribute="source", source_index_attribute="",
            create_output_group=False, output_group="replicated"):
        ks = keep_source_attributes
        g, r = _po.point_replicate(
            geo, count, count_attribute, radius, radius_attribute, shape, rand_seed,
            keep_original, group, orientation=orientation,
            center=(center_x, center_y, center_z), size=(size_x, size_y, size_z),
            uniform_scale=uniform_scale, velocity_stretch=velocity_stretch,
            velocity_scale=velocity_scale,
            copy_attributes=source_attributes if copy_source_attributes else "",
            inherit_velocity=inherit_velocity, radial_velocity=radial_velocity,
            source_attribute=source_point_attribute if ks else "",
            source_index_attribute=source_index_attribute if ks else "",
            output_group=output_group if create_output_group else "")
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_PointVelocity:
    """
    Maps to: Point Velocity. Computes v by differencing positions of adjacent frames: backward / forward / central (auto =
    central when both sides exist), dt = 1/FPS; paired by point number or id; unpaired ones get v = 0 and go into the no_velocity group;
    with both previous and next frames connected, accel can be computed too.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "method": (list(_po.VELOCITY_METHODS),),
            "fps": _f(24.0, 0.001, 1e6, 1.0),
            "match": (list(_po.VELOCITY_MATCH),),
            "id_attribute": _names("attrib", "point", "id"),
            "compute_accel": _b(False), "v_attribute": _s("v"),
        }, "optional": {"prev": (GEO,), "next": (GEO,)}}

    def run(self, geo, method, fps, match, id_attribute, compute_accel,
            v_attribute, prev=None, next=None):
        g, r = _po.point_velocity(geo, prev, next, method, fps, match,
                                  id_attribute, compute_accel, v_attribute)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ Volume / UV / outline (pcg77)
@_node("generate", _WITH_REPORT)
class PCG_IsoSurface:
    """
    Maps to: IsoSurface. An implicit-function expression (wrangle syntax, @P / @P.x …, also accepts $X $Y $Z) evaluated at grid points
    within the bounding box; surface nets extract the iso-surface f = Iso (quads, positive outside, negative inside); Project moves vertices onto the true iso-surface
    by Newton iteration along the numerical gradient; Normals writes N from the gradient. Output = volume outputs the volume directly.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {}
        req.update(_v3("bound_min", (-1.5, -1.5, -1.5)))
        req.update(_v3("bound_max", (1.5, 1.5, 1.5)))
        req.update({"divisions_x": _i(48, 1, 1024), "divisions_y": _i(48, 1, 1024),
                    "divisions_z": _i(48, 1, 1024),
                    "expression": ("STRING", {"default": "length(@P) - 1",
                                              "multiline": True}),
                    "iso": _f(0.0), "project": _b(True), "normals": _b(True),
                    "output": (list(_iso.ISO_OUTPUTS),)})
        return {"required": req}

    def run(self, bound_min_x, bound_min_y, bound_min_z, bound_max_x,
            bound_max_y, bound_max_z, divisions_x, divisions_y, divisions_z,
            expression, iso, project, normals, output):
        g, r = _iso.isosurface((bound_min_x, bound_min_y, bound_min_z),
                               (bound_max_x, bound_max_y, bound_max_z),
                               (divisions_x, divisions_y, divisions_z),
                               expression, iso, project, normals, output)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_RemeshToGrid:
    """
    Maps to: Remesh to Grid. Exact SDF (cubic voxels, aligned to integer multiples of Voxel Size) → surface nets
    giving an all-quad closed mesh; Project projects points back onto the original surface, Smooth does a few rounds of tangential relaxation (with Project on, re-projected
    every round; without, only relaxation); point attributes
    are carried over by barycentric interpolation at the nearest point. Sharp edges get rounded (to keep edges use Remesh).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "voxel_size": _f(0.1, 1e-6, 1e6, 0.01), "project": _b(True),
            "smooth": _i(2, 0, 100), "smooth_strength": _f(0.5, 0.0, 1.0, 0.05),
            "transfer_attributes": _b(True),
        }}

    def run(self, geo, group, voxel_size, project, smooth, smooth_strength,
            transfer_attributes):
        g, r = _iso.remesh_to_grid(geo, voxel_size, project, smooth,
                                   smooth_strength, transfer_attributes, group)
        return (g, _rep(r))


@_node("uv", _WITH_REPORT)
class PCG_UVSmooth:
    """
    Maps to: UV Smooth. Relaxation in uv space: corners on the same point with the same uv form one wedge (the two sides of a seam move
    independently). Weights cotangent (by 3D triangle, with linear precision: only removes distortion inconsistent with the 3D shape) or
    uniform; relax iterates / harmonic solves directly to convergence. Pin Boundary fixes island borders; points outside group
    are fixed too.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "uv_attribute": _names("attrib", "vertex", "uv"),
            "iterations": _i(20, 0, 100000), "strength": _f(0.5, 0.0, 1.0, 0.05),
            "weights": (list(_uvs.UV_WEIGHTS),), "solve": (list(_uvs.UV_SOLVES),),
            "pin_boundary": _b(True), "group": _group(),
        }}

    def run(self, geo, uv_attribute, iterations, strength, weights, solve,
            pin_boundary, group):
        g, r = _uvs.uv_smooth(geo, uv_attribute, iterations, strength, weights,
                              solve, pin_boundary, group)
        return (g, _rep(r))


@_node("generate", _WITH_REPORT)
class PCG_ExtractSilhouette:
    """
    Maps to: Extract Silhouette. outline: projects along Direction onto the plane through Origin and exactly computes the border of the projected
    region (candidate silhouette edges intersected and cut into segments, decided by coverage on both sides), closed polylines, outer loops counter-clockwise, holes clockwise
    (prim attributes hole, area). contour: the border of front-facing regions on the mesh, left in 3D.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "group": _group()}
        req.update(_v3("direction", (0.0, -1.0, 0.0)))
        req.update(_v3("origin", (0.0, 0.0, 0.0)))
        req.update({"mode": (list(_sil.SIL_MODES),), "simplify": _b(True),
                    "include_boundary": _b(True)})
        return {"required": req}

    def run(self, geo, group, direction_x, direction_y, direction_z, origin_x,
            origin_y, origin_z, mode, simplify, include_boundary):
        g, r = _sil.extract_silhouette(geo, (direction_x, direction_y,
                                             direction_z),
                                       (origin_x, origin_y, origin_z), mode,
                                       simplify, include_boundary, group)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════════ pcg78 cameras ↔ points
@_node("render", ((GEO, "geo"), (GEO, "frustums"), ("STRING", "report")))
class PCG_CameraToPoints:
    """
    Maps to: Camera To Points. A camera sequence (and / or a single camera) → one point per camera, point number = frame number: P,
    orient (+Z line of sight, +Y up, the same convention as N / Orient Along Curve / Copy to Points), N, up,
    target, distance, fov, ortho_size, near, far, radius, resx, resy, projection, frame.
    With Path on, a connecting polyline is added. frustums are frustum wireframes (depth Frustum Depth, 0 = none);
    the four corners of the frustum base are exactly the four corners of the image. Edit the points then connect Camera from Points, and you've "placed camera positions in the viewport".
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"path": _b(True),
                             "frustum_depth": _f(0.5, 0.0, 1e6, 0.1)},
                "optional": {"cams": (CAMSEQ,), "cam": (CAM,)}}

    def run(self, path, frustum_depth, cams=None, cam=None):
        seq = list(cams or []) + ([cam] if cam is not None else [])
        if not seq:
            raise ValueError("connect at least one of cams / cam")
        g, fr, r = _cpt.cameras_to_points(seq, path, frustum_depth)
        return (g, fr, _rep(r))


@_node("render", ((CAMSEQ, "cams"), ("INT", "frames"), ("STRING", "report")))
class PCG_CameraFromPoints:
    """
    Maps to: Camera from Points. Points (in point-number order) → a camera sequence; the curve version of Camera Path.
    Orientation: auto (looks for orient → N → target attribute → path in turn) / orient / normal (N + up) /
    target (looks at the target attribute or the Target parameter) / path (along the path tangent; with Look Ahead > 0 it looks at the point that far
    ahead on the path, for a steadier shot). Frames = 0 gives one camera per point; > 0 samples evenly by arc length along the path (orient uses slerp,
    the rest linear interpolation). Loop joins end to start without repeating the first frame at the end. Use Point Attributes: fov /
    ortho_size / near / far / radius / resx / resy / projection / distance on the points override the parameters;
    round trips with Camera To Points are exact.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "group": _group("Only use these points (point group)"),
               "orientation": (list(_cpt.CAM_ORIENT),),
               "frames": _i(0, 0, 1 << 14), "loop": _b(False),
               "look_ahead": _f(0.0, 0.0, 1e6, 0.1),
               "projection": (list(_rnd.PROJECTIONS),),
               "resolution_x": _i(512, 8, 16384), "resolution_y": _i(512, 8, 16384),
               "fov": _f(45.0, 1.0, 179.0, 1.0),
               "ortho_size": _f(2.0, 1e-4, 1e6, 0.1),
               "focus_distance": _f(5.0, 1e-4, 1e6, 0.1),
               "use_point_attributes": _b(True)}
        req.update(_v3("up", (0.0, 1.0, 0.0)))
        req.update(_v3("target", (0.0, 0.0, 0.0)))
        req.update({"near": _sec("Clipping", _f(0.01, 1e-6, 1e6, 0.01)),
                    "far": _sec("Clipping", _f(0.0, 0.0, 1e6, 0.1))})
        return {"required": req}

    def run(self, geo, group, orientation, frames, loop, look_ahead, projection,
            resolution_x, resolution_y, fov, ortho_size, focus_distance,
            use_point_attributes, up_x, up_y, up_z, target_x, target_y,
            target_z, near, far):
        cams, r = _cpt.cameras_from_points(
            geo, orientation, frames, loop, look_ahead, projection,
            resolution_x, resolution_y, fov, ortho_size, near, far,
            (up_x, up_y, up_z), (target_x, target_y, target_z),
            focus_distance, use_point_attributes, group)
        return (cams, len(cams), _rep(r))


# ═══════════════════════════════════════════════════ pcg79 completing the 8 partials
@_node("group", _WITH_REPORT)
class PCG_GroupCombine:
    """
    Maps to: Group Combine. Combines several groups into one by set operations: | union, & intersection, - difference, ^ symmetric difference, ! complement,
    parentheses nest freely, precedence as Python sets (! > - > & > ^ > |). Group names may contain wildcards, * is the full set.
    Example: (top & selected) - border. Group Type can be point / prim / vertex / edge.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group_type": (list(_gc.COMBINE_CLASSES),),
            "expression": _s("a & b"), "output_group": _s("combined")}}

    def run(self, geo, group_type, expression, output_group):
        g, r = _gc.group_combine(geo, group_type, expression, output_group)
        return (g, _rep(r))


@_node("modify", ((GEO, "geo"), ("BOOLEAN", "result"), ("STRING", "report")))
class PCG_SwitchIf:
    """
    Maps to: Switch-If. If the condition holds, outputs if_true, otherwise if_false (unconnected = empty geometry). Tests holds one
    expression per line (lines starting with # are comments); Merge = all is true only if all are true / any is true if any is, Invert negates.
    Functions: npoints() nprims() detail("x") point("x", i) hasattrib("point", "Cd")
    hasgroup("prim", "top") ngroup("edge", "crease") attribmax("point", "P", 1) attribmin
    attribmean …. Tests read the test input; with test unconnected they read if_true.
    **Unselected branches are not executed** (lazy): with test connected only the selected branch runs; without it if_true must
    be computed first (the tests run on it), and if_false only runs when the condition fails.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
                    "tests": ("STRING", {"default": "npoints() > 0",
                                         "multiline": True}),
                    "merge": (list(_ex.SWITCHIF_MERGE),),
                    "invert": _b(False)},
                "optional": {"test": (GEO,),
                             "if_true": (GEO, {"lazy": True}),
                             "if_false": (GEO, {"lazy": True})}}

    @staticmethod
    def _decide(tests, merge, invert, geo):
        r, vals = _ex.eval_tests(tests, geo, merge)
        return (r != bool(invert)), vals

    def check_lazy_status(self, tests, merge, invert, **kw):
        if "test" in kw and kw["test"] is not None:
            ok, _ = self._decide(tests, merge, invert, kw["test"])
            want = "if_true" if ok else "if_false"
            return [want] if want in kw and kw[want] is None else []
        if "if_true" in kw and kw["if_true"] is None:
            return ["if_true"]
        if "if_true" not in kw:
            return []
        ok, _ = self._decide(tests, merge, invert, kw["if_true"])
        if not ok and "if_false" in kw and kw["if_false"] is None:
            return ["if_false"]
        return []

    def run(self, tests, merge, invert, test=None, if_true=None, if_false=None):
        src = test if test is not None else if_true
        if src is None:
            raise ValueError("Neither test nor if_true is connected: no geometry to test")
        ok, vals = self._decide(tests, merge, invert, src)
        out = if_true if ok else if_false
        from .geo.core import Geometry
        g = out.copy() if out is not None else Geometry()
        return (g, bool(ok), _rep({"result": bool(ok), "tests": vals,
                                   "tested_on": "test" if test is not None
                                   else "if_true"}))


@_node("scatter", _WITH_REPORT)
class PCG_PointRelax:
    """
    Maps to: Point Relax. Pushes any point cloud apart by radius until nothing overlaps (pscale × Radius Scale; without pscale
    Radius is used; Radius = 0 picks it automatically). With surface connected, points are projected back onto it every step. Points outside group don't move but still block.
    Each step moves at most Max Step × radius; stops early when nothing overlaps.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only push these points (point group)"),
            "iterations": _i(20, 0, 10000),
            "radius": _f(0.0, 0.0, 1e6, 0.01),
            "use_pscale": _b(True),
            "radius_scale": _f(1.0, 0.0, 1e6, 0.05),
            "max_step": _f(0.5, 0.0, 10.0, 0.05)},
            "optional": {"surface": (GEO,)}}

    def run(self, geo, group, iterations, radius, use_pscale, radius_scale,
            max_step, surface=None):
        g, r = _prl.point_relax(geo, surface, iterations, radius, use_pscale,
                                radius_scale, max_step, group)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_PrimitiveSplit:
    """
    Maps to: Primitive Split. Faces with different prim attribute values (difference > Tolerance; strings by equality) don't share points:
    a point shared by several kinds of faces is split into that many. Faces outside group count as one kind (still sharing among themselves).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "prim", "name"),
            "tolerance": _f(0.0, 0.0, 1e6, 1e-4), "group": _group()}}

    def run(self, geo, attribute, tolerance, group):
        g, r = _cs.primitive_split(geo, attribute, tolerance, group)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_TransformByAttrib:
    """
    Maps to: Transform by Attribute. Transforms the geometry itself by a matrix attribute (9 = 3×3, 16 = 4×4, read as in Copy to Points).
    Class: detail one matrix / point one per point / prim one per face. Invert uses the inverse matrix.
    Normals use the inverse transpose then renormalise, vectors only multiply by the 3×3, orient multiplies by the rotation part.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _s("transform"),
            "attribute_class": (list(_xa.XFORM_CLASSES), {"default": "point"}),
            "invert": _b(False), "normals": _s("N"), "vectors": _s("v up"),
            "orient": _b(True), "group": _group()}}

    def run(self, geo, attribute, attribute_class, invert, normals, vectors,
            orient, group):
        g, r = _xa.transform_by_attrib(geo, attribute, attribute_class, invert,
                                       normals, vectors, orient, group)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_PolySplit:
    """
    Maps to: PolySplit. Locations are space separated: 12 (or p12) = a point, 3-7@0.25 = t = 0.25 on the edge from point 3→7
    (@ omitted = midpoint). Two consecutive locations must lie on the same face, which is split in two along the connecting line; new points on edges are inserted into
    all faces on both sides (no T-junctions left). Close Path connects back to the first. With a non-empty Edge Group the cut edges are written as an edge group.
    pcg100: locations also accept Houdini's notation (p3-7:0.25, 0v2, 0e1:0.25; in-face 0f:u,v is not done);
    Path Type = edge_loop inserts a loop of edges around the quad ring from each location on an edge (with Number of Loops > 1, several equally spaced loops);
    Edge Percentage locks all locations on edges to the same t. The other Path Type is called Shortest Path to
    match Houdini's name -- we don't actually pathfind; two consecutive locations still have to lie on the same face.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "locations": _s("0-1@0.5 2-3@0.5"),
            "close_path": _b(False), "edge_group": _s(""),
            # pcg100 additions
            "path_type": (list(_cs.SPLIT_PATH),),
            "num_loops": _i(1, 1, 1024),
            "use_edge_percentage": _b(False),
            "edge_percentage": _f(0.5, 0.0, 1.0, 0.01)}}

    def run(self, geo, locations, close_path, edge_group, path_type="shortest_path",
            num_loops=1, use_edge_percentage=False, edge_percentage=0.5):
        g, r = _cs.poly_split(geo, locations, close_path, edge_group, path_type,
                              num_loops, use_edge_percentage, edge_percentage)
        return (g, _rep(r))


@_node("topology", _WITH_REPORT)
class PCG_EdgeCusp:
    """
    Maps to: Edge Cusp. Cuts along the edge group (empty = all edges): faces on the two sides no longer share endpoints; with Min Angle > 0 only edges with
    dihedral angle ≥ it are cut. Points not touching a cut edge don't move. Compute Normals writes area-weighted point normals (hard edges at the cuts).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _edges_in(),
            "min_angle": _f(0.0, 0.0, 180.0, 1.0),
            "compute_normals": _b(True)}}

    def run(self, geo, edges, min_angle, compute_normals):
        g, r = _cs.edge_cusp(geo, edges, min_angle, compute_normals)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_Crease:
    """
    Maps to: Crease. Writes fractional crease weights for the edge group (empty = all edges) (vertex attribute creaseweight, written on the start of
    the half-edges on both sides of an edge). Subdivide reads it for semi-sharp creases: s ≥ 1 is sharp this round, 0..1 blends, minus 1 per round.
    Mode: set / add / multiply / max.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "edges": _edges_in(),
            "weight": _f(2.0, 0.0, 100.0, 0.1),
            "mode": (list(_sub.CREASE_MODES),),
            "attribute": _s("creaseweight")}}

    def run(self, geo, edges, weight, mode, attribute):
        g, r = _sub.crease(geo, edges, weight, mode, attribute)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════════ pcg81
@_node("modify", _WITH_REPORT)
class PCG_Shrinkwrap:
    """
    Maps to: Shrinkwrap (the kind that shrinks into concave areas). A ball of radius Radius rolls from outside; the border of the region it can't reach is the shell:
    gaps / holes / grooves narrower than 2 × Radius are bridged over, wider concave areas are followed closely; open meshes, loose parts and interpenetrating pieces are all
    wrapped into **one closed manifold**. Radius → ∞ gives the convex hull. Offset pushes everything outward. Project snaps the touching points exactly onto
    the surface (point group contact), Smooth relaxes tangentially. Precision is one voxel (Voxel Size, aligned to world coordinates).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only wrap these faces"),
            "voxel_size": _f(0.05, 1e-4, 1e4, 0.01),
            "radius": _f(0.15, 0.0, 1e4, 0.01),
            "offset": _f(0.0, 0.0, 1e4, 0.01),
            "project": _b(True),
            "smooth": _i(2, 0, 100),
            "smooth_strength": _f(0.5, 0.0, 1.0, 0.05)}}

    def run(self, geo, group, voxel_size, radius, offset, project, smooth,
            smooth_strength):
        g, r = _sw.shrinkwrap(geo, voxel_size, radius, offset, project, smooth,
                              smooth_strength, group)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════════ pcg82
_RAMP = ("STRING", {"default": "0:0  1:1"})


def _soft_extra_inputs():
    """Falloff parameters shared by Soft Peak / Soft Transform (pcg100, appended at the end of each)."""
    from .geo.deform import SOFT_TYPES, KERNELS
    return {"soft_type": (list(SOFT_TYPES),),
            "tangent_far": _f(0.0, -89.0, 89.0, 1.0),
            "tangent_near": _f(0.0, -89.0, 89.0, 1.0),
            "kernel": (list(KERNELS),),
            "distance_attribute": _s("dist"),
            "apply_rolloff": _b(True)}


@_node("deform", _WITH_REPORT)
class PCG_SoftPeak:
    """
    Maps to: Soft Peak. Pushes the point group along its own normals by Distance; points within Radius follow with Ramp falloff (soft selection as in
    Soft Transform: euclidean / distance along edges / steps hop count). N is computed on the fly if missing.
    """
    @classmethod
    def INPUT_TYPES(cls):
        from .geo.deform import METRICS
        return {"required": {
            "geo": (GEO,), "group": _group("Points being pushed (point group)"),
            "distance": _f(0.2, -1e6, 1e6, 0.01), "radius": _f(1.0, 0.0, 1e6, 0.05),
            "metric": (list(METRICS),), "ramp": _RAMP,
            "ramp_mode": (["smooth", "linear", "constant"],),
            "update_normals": _b(True), "weight_attribute": _s(""),
            # pcg100: additions per the Soft Peak docs (defaults = old behaviour)
            **_soft_extra_inputs(),
            "translate_along_lead_normal": _b(False),
            "lead_point_attribute": _s("lead"),
            "use_mask": _b(False), "mask_attribute": _s("mask")}}

    def run(self, geo, group, distance, radius, metric, ramp, ramp_mode,
            update_normals, weight_attribute, soft_type="ramp", tangent_far=0.0,
            tangent_near=0.0, kernel="links", distance_attribute="dist", apply_rolloff=True,
            translate_along_lead_normal=False, lead_point_attribute="lead", use_mask=False,
            mask_attribute="mask"):
        g, r = _d3.soft_peak(geo, group, distance, radius, metric, ramp, ramp_mode,
                             update_normals, weight_attribute, soft_type,
                             (tangent_far, tangent_near), kernel, distance_attribute,
                             apply_rolloff, translate_along_lead_normal, lead_point_attribute,
                             mask_attribute if use_mask else "")
        return (g, _rep(r))


def _magnet_inputs():
    return {"magnet_type": (list(_d3.MAGNET_TYPES),),
            "radius": _f(1.0, 0.0, 1e6, 0.05), "use_pscale": _b(True),
            "ramp": _RAMP, "ramp_mode": (["smooth", "linear", "constant"],),
            "group": _group("Only move these points"), "weight_attribute": _s("")}


@_node("deform", _WITH_REPORT)
class PCG_Bulge:
    """
    Maps to: Bulge. The second input is magnets (each point a spherical influence region of radius pscale × Radius; the surface type uses distance to
    the magnet surface); points in the influence region are pushed along their normals (normal) or away from the magnet (radial) by Magnitude × weight.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "magnet": (GEO,),
               "magnitude": _f(0.5, -1e6, 1e6, 0.01),
               "direction": (list(_d3.BULGE_DIRS),)}
        req.update(_magnet_inputs())
        req["update_normals"] = _b(True)
        return {"required": req}

    def run(self, geo, magnet, magnitude, direction, magnet_type, radius,
            use_pscale, ramp, ramp_mode, group, weight_attribute, update_normals):
        g, r = _d3.bulge(geo, magnet, magnitude, direction, magnet_type, radius,
                         use_pscale, ramp, ramp_mode, group, update_normals,
                         weight_attribute)
        return (g, _rep(r))


@_node("deform", _WITH_REPORT)
class PCG_Magnet:
    """
    Maps to: Magnet. Points in the magnet influence region (as in Bulge) are transformed by weight: displacement × w, rotation angle × w, scale
    lerp(1, s, w), about the magnet centroid / origin / a given Pivot. Parameters are interpolated, not results, so rotation doesn't collapse the radius.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "magnet": (GEO,)}
        req.update(_v3("translate", (0.0, 0.5, 0.0)))
        req.update(_v3("rotate", (0.0, 0.0, 0.0)))
        req.update(_v3("scale", (1.0, 1.0, 1.0)))
        req["pivot_mode"] = (list(_d3.PIVOTS),)
        req.update(_v3("pivot", (0.0, 0.0, 0.0)))
        req.update(_magnet_inputs())
        return {"required": req}

    def run(self, geo, magnet, translate_x, translate_y, translate_z, rotate_x,
            rotate_y, rotate_z, scale_x, scale_y, scale_z, pivot_mode, pivot_x,
            pivot_y, pivot_z, magnet_type, radius, use_pscale, ramp, ramp_mode,
            group, weight_attribute):
        g, r = _d3.magnet(geo, magnet, (translate_x, translate_y, translate_z),
                          (rotate_x, rotate_y, rotate_z), (scale_x, scale_y, scale_z),
                          pivot_mode, (pivot_x, pivot_y, pivot_z), magnet_type, radius,
                          use_pscale, ramp, ramp_mode, group, weight_attribute)
        return (g, _rep(r))


@_node("deform", _WITH_REPORT)
class PCG_Fractal:
    """
    Maps to: Fractal. Midpoint displacement: linear subdivision per level, randomly pushing only the points newly created at that level along their normals (or a given direction)
    by ±Scale·Roughness^level. Fixed Boundary: new points on open borders aren't pushed (tiles don't crack).
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "divisions": _i(3, 0, 6),
               "scale": _f(0.2, -1e6, 1e6, 0.01),
               "roughness": _f(0.5, 0.0, 2.0, 0.05),
               "direction": (list(_d3.FRACTAL_DIRS),)}
        req.update(_v3("vector", (0.0, 1.0, 0.0)))
        req.update({"fixed_boundary": _b(True), "rand_seed": _i(0, 0, 2 ** 31 - 1)})
        return {"required": req}

    def run(self, geo, divisions, scale, roughness, direction, vector_x, vector_y,
            vector_z, fixed_boundary, rand_seed):
        g, r = _d3.fractal(geo, divisions, scale, roughness, direction,
                           (vector_x, vector_y, vector_z), fixed_boundary, rand_seed)
        return (g, _rep(r))


@_node("scatter", _WITH_REPORT)
class PCG_ScatterAlign:
    """
    Maps to: Scatter and Align. Scatters points (count / density / coverage: infers the point count from the area fraction covered by pscale disks)
    and in one go writes pscale (random Min..Max), N, up (projected onto the tangent plane, randomly rotated about N), orient (+Z = N);
    Tilt randomly tilts normals; Avoid Overlap pushes apart on the surface by pscale so instances don't interpenetrate.
    """
    @classmethod
    def INPUT_TYPES(cls):
        req = {"geo": (GEO,), "group": _group("Only scatter on these faces"),
               "mode": (list(_sa.SA_MODES),), "count": _i(200, 0, 1 << 22),
               "density": _f(10.0, 0.0, 1e9, 0.5), "coverage": _f(0.5, 0.0, 10.0, 0.05),
               "scale_min": _f(0.05, 0.0, 1e6, 0.01), "scale_max": _f(0.1, 0.0, 1e6, 0.01)}
        req.update(_v3("up", (0.0, 1.0, 0.0)))
        req.update({"rotate_random": _f(360.0, 0.0, 360.0, 1.0),
                    "tilt": _f(0.0, 0.0, 90.0, 1.0), "avoid_overlap": _b(False),
                    "overlap_scale": _f(1.0, 0.0, 10.0, 0.05),
                    "relax_iterations": _i(20, 0, 1000),
                    "rand_seed": _i(0, 0, 2 ** 31 - 1)})
        # ── pcg100 additions (Houdini Scatter and Align's Mode / By Point Spacing / orientation axes /
        #    Min-Max rotation / output attributes / Surface Attributes), defaults = old behaviour
        req.update({
            "scatter_mode": (list(_sa.SCATTER_MODES),),
            "point_group": _group("Points in the second input to write attributes on"),
            "tag_name": _s(""),
            "spacing": _f(0.1, 1e-6, 1e6, 0.01),
            "use_density_attribute": _b(False),
            "density_attribute": _names("attrib", "point", "density"),
            "use_emergency_limit": _b(False),
            "emergency_limit": _i(1000000, 1, 1 << 24),
            "normal_direction": (list(_sa.AXES),),
            **_v3("normal_custom", (0.0, 0.0, 1.0)),
            "forward_direction": (list(_sa.FWD_AXES),),
            **_v3("forward_custom", (0.0, 1.0, 0.0)),
            "rotation_range": (list(_sa.ROT_RANGES),),
            "min_angle": _f(0.0, -3600.0, 3600.0, 1.0),
            "max_angle": _f(360.0, -3600.0, 3600.0, 1.0),
            "round_rotation": _b(False),
            "round_to": _f(90.0, 0.0, 360.0, 1.0),
            "offset_angle": _f(0.0, -3600.0, 3600.0, 1.0),
            "use_radius_attribute": _b(True), "radius_attribute": _s("pscale"),
            "use_orient_attribute": _b(True), "orient_attribute": _s("orient"),
            "use_prim_uvw": _b(False), "prim_uvw_attribute": _s("sourceprimuv"),
            "surface_point_attributes": _names("attrib", "point", ""),
            "surface_vertex_attributes": _names("attrib", "vertex", ""),
            "surface_primitive_attributes": _names("attrib", "prim", ""),
            "surface_detail_attributes": _names("attrib", "detail", ""),
        })
        return {"required": req, "optional": {"points": (GEO,)}}

    def run(self, geo, group, mode, count, density, coverage, scale_min, scale_max,
            up_x, up_y, up_z, rotate_random, tilt, avoid_overlap, overlap_scale,
            relax_iterations, rand_seed, scatter_mode="surface", point_group="",
            tag_name="", spacing=0.1, use_density_attribute=False,
            density_attribute="density", use_emergency_limit=False, emergency_limit=1000000,
            normal_direction="z", normal_custom_x=0.0, normal_custom_y=0.0,
            normal_custom_z=1.0, forward_direction="y", forward_custom_x=0.0,
            forward_custom_y=1.0, forward_custom_z=0.0, rotation_range="symmetric",
            min_angle=0.0, max_angle=360.0, round_rotation=False, round_to=90.0,
            offset_angle=0.0, use_radius_attribute=True, radius_attribute="pscale",
            use_orient_attribute=True, orient_attribute="orient", use_prim_uvw=False,
            prim_uvw_attribute="sourceprimuv", surface_point_attributes="",
            surface_vertex_attributes="", surface_primitive_attributes="",
            surface_detail_attributes="", points=None):
        g, r = _sa.scatter_align(
            geo, mode, count, density, coverage, scale_min,
            scale_max, (up_x, up_y, up_z), rotate_random, tilt,
            avoid_overlap, overlap_scale, relax_iterations, group,
            rand_seed, scatter_mode=scatter_mode, points=points, point_group=point_group,
            spacing=spacing,
            density_attrib=density_attribute if use_density_attribute else "",
            emergency_limit=emergency_limit if use_emergency_limit else 0,
            normal_axis=normal_direction,
            normal_custom=(normal_custom_x, normal_custom_y, normal_custom_z),
            forward_axis=forward_direction,
            forward_custom=(forward_custom_x, forward_custom_y, forward_custom_z),
            rotation_range=rotation_range, min_angle=min_angle, max_angle=max_angle,
            round_to=round_to if round_rotation else 0.0, offset_angle=offset_angle,
            radius_attrib=radius_attribute if use_radius_attribute else "",
            orient_attrib=orient_attribute if use_orient_attribute else "",
            prim_uvw_attrib=prim_uvw_attribute if use_prim_uvw else "",
            tag_name=tag_name, point_attribs=surface_point_attributes,
            vertex_attribs=surface_vertex_attributes,
            prim_attribs=surface_primitive_attributes,
            detail_attribs=surface_detail_attributes)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_EdgeTransport:
    """
    Maps to: Edge Transport. Builds trees outward along edges from roots (network: shortest paths by edge length; curves: each line walked from its start); along the tree,
    copy the root's value / sum accumulates along the way / distance path length / average averages along the way. Unreachable points go into the unreached group.
    Writes the point attribute transport_root (which root it belongs to).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attribute": _names("attrib", "point", ""),
            "operation": (list(_et.ET_OPS),),
            "method": (list(_et.ET_METHODS),),
            "root_group": _group("Start from these points"),
            "output": _s(""), "unreached_group": _s("unreached"),
            # pcg100: additions per the Edge Transport docs (defaults = old behaviour)
            "direction": (list(_et.DIRECTIONS),),
            "root_choice": (list(_et.ROOT_CHOICES),),
            "point_group": _group("Only travel over these points (network / parent_attribute)"),
            "curve_group": _group("Only travel along these curves (curves)"),
            "parent_attribute": _names("attrib", "point", "parent"),
            "use_normalization": _b(False),
            "normalization": (list(_et.NORMALIZATIONS),),
            "new_root_value": (list(_et.NEW_ROOT_VALUES),),
            "integrate_constant": _b(False),
            "scale_by_edge_length": _b(False),
            "split_method": (list(_et.SPLIT_METHODS),),
            "merge_method": (list(_et.MERGE_METHODS),)}}

    def run(self, geo, attribute, operation, method, root_group, output,
            unreached_group, direction="forward", root_choice="group", point_group="",
            curve_group="", parent_attribute="parent", use_normalization=False,
            normalization="per_component", new_root_value="zero", integrate_constant=False,
            scale_by_edge_length=False, split_method="copy", merge_method="add"):
        g, r = _et.edge_transport(geo, attribute, operation, method, root_group,
                                  output, unreached_group, direction, root_choice, point_group,
                                  curve_group, parent_attribute,
                                  normalization if use_normalization else "", new_root_value,
                                  integrate_constant, scale_by_edge_length, split_method,
                                  merge_method)
        return (g, _rep(r))


@_node("convert", _WITH_REPORT)
class PCG_VolumeRasterizeAttribs:
    """
    Maps to: Volume Rasterize Attributes. Splats points into a volume by radius (pscale × Radius Scale): density (fog)
    plus a kernel-weighted average of each attribute (vectors split into name.x / .y / .z). The grid is aligned to world coordinates.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "attributes": _s("Cd"),
            "voxel_size": _f(0.05, 1e-5, 1e5, 0.01), "radius": _f(0.1, 0.0, 1e5, 0.01),
            "use_pscale": _b(True), "radius_scale": _f(1.0, 0.0, 1e5, 0.05),
            "density_attribute": _s("density"), "group": _group()}}

    def run(self, geo, attributes, voxel_size, radius, use_pscale, radius_scale,
            density_attribute, group):
        g, r = _vr.rasterize_attributes(geo, attributes, voxel_size, radius, use_pscale,
                                        radius_scale, density_attribute, group)
        return (g, _rep(r))


@_node("output", returns=(("STRING", "report"),))
class PCG_ExportInstances:
    """
    Maps to: ROP output of instance points / Labs Instance export. Points → instance table (CSV / JSON): asset,
    position, quaternion, Euler angles (XYZ, degrees), scale, plus Extra Attributes. Transforms are read exactly as in Copy to
    Points (orient > N + up > pscale …), so what the preview shows is what's written in the table.
    Axis Map's three words say which original axis the new x y z take (sign allowed): x y z as is (Y up),
    x -z y (Z up, right-handed), x z y (Z up, left-handed), with rotations converted along; Unit Scale multiplies positions.
    Tile Size > 0 tiles by x, z, one file per tile ({tx} {ty}), plus a separate _index.json.
    """
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        from .geo import instances as _ins
        return {"required": {
            "points": (GEO,),
            "filename": _s("pcg/instances/instances"),
            "format": (list(_ins.FORMATS),),
            "asset_attribute": _names("attrib", "point", "name"),
            "extra_attributes": _s(""),
            "axis_map": _s("x y z"),
            "unit_scale": _f(1.0, 1e-6, 1e6, 0.01),
            "tile_size": _f(0.0, 0.0, 1e7, 1.0),
            "index": _i(0, 0, 1 << 30),
        }}

    def run(self, points, filename, format, asset_attribute, extra_attributes,
            axis_map, unit_scale, tile_size, index):
        from .geo import instances as _ins
        from .nodes import output_dir
        r = _ins.write(points, output_dir(), filename, format, asset_attribute,
                       extra_attributes, axis_map, unit_scale, tile_size, index)
        return {"ui": {"text": [f["file"] for f in r["files"]][:16]},
                "result": (_rep(r),)}


# ═══════════════════════════════════════════════════════════ Registration
# ═══════════════════════════════════════════════════════ pcg100 audit gap fill
from .geo import blastattr as _bla                                  # noqa: E402


@_node("modify")
class PCG_BlastByAttribute:
    """
    Maps to: Blast by Attribute. Deletes points / faces by a **single-valued** attribute, or (Output = Group) doesn't delete
    and just puts the hits into a group. Mode: threshold hits values below the threshold (strictly less) / range min ≤ value ≤ max
    / width falls within [center − width/2, center + width/2]; Invert negates. Elements outside Group
    don't take part (Invert doesn't touch them either). Remove Unused Points only matters when deleting faces.
    The SideFX docs don't give the defaults of several numbers or how vector attributes are evaluated: the defaults are our own, and vector attributes
    raise an error outright.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group("Only test within these elements; empty = all"),
            "cls": (list(_bla.CLASSES),),
            "attribute": _names("attrib", "point", "pscale"),
            "output": (list(_bla.OUTPUTS),),
            "mode": (list(_bla.MODES),),
            "invert": _b(False),
            "threshold": _f(0.5),
            "min": _f(0.0), "max": _f(1.0),
            "center": _f(0.5), "width": _f(0.2, 0.0),
            "output_group": _s("group1"),
            "remove_unused_points": _b(True)}}

    def run(self, geo, group, cls, attribute, output, mode, invert, threshold,
            min, max, center, width, output_group, remove_unused_points):
        return (_bla.blast_by_attribute(geo, group, cls, attribute, output, mode,
                                        invert, threshold, min, max, center, width,
                                        output_group, remove_unused_points),)


# ═══════════════════════════════════════════════════════ pcg100 s6: the Attribute Adjust series
from .geo import attribadjust2 as _aa2                              # noqa: E402


def _aa2_noise_inputs():
    """The Noise Pattern tab, shared by the four Adjust nodes."""
    return {
        "noise_type": (list(_aa2.NOISE_TYPES), {"default": "perlin"}),
        "location_attribute": _names("attrib", "point", "P"),
        "element_size": _f(1.0, 1e-6, 1e6, 0.01),
        **_v3("element_scale", (1.0, 1.0, 1.0)),
        **_v3("noise_offset", (0.0, 0.0, 0.0)),
        "fractal_type": (list(_aa2.FRACTALS),),
        "max_octaves": _i(3, 1, 16),
        "lacunarity": _f(2.0, -16.0, 16.0, 0.01),
        "roughness": _f(0.5, -4.0, 4.0, 0.01),
    }


def _aa2_noise(kw):
    return _aa2.NoiseSpec(
        kw["noise_type"], kw["location_attribute"], kw["element_size"],
        (kw["element_scale_x"], kw["element_scale_y"], kw["element_scale_z"]),
        (kw["noise_offset_x"], kw["noise_offset_y"], kw["noise_offset_z"]),
        kw["fractal_type"], kw["max_octaves"], kw["lacunarity"], kw["roughness"])


def _aa2_scalar_inputs(integer, prefix=""):
    """Range Values / Distribution / Outliers / Stepping / value table. The Vector node distinguishes by prefix."""
    num = (lambda d: _i(int(d), -(1 << 30), 1 << 30)) if integer else (lambda d: _f(d))
    p = prefix
    return {
        p + "range_values": (list(_aa2.RANGES),),
        p + "min_value": num(0.0), p + "max_value": num(1.0 if not integer else 10),
        p + "middle_value": num(0.5 if not integer else 5),
        p + "range_length": num(1.0 if not integer else 10),
        p + "value_list": ("STRING", {
            "default": "0\n1", "multiline": True,
            "tooltip": "One group per line: a value or list (space/comma/semicolon separated, min-max:step expands)"
                       "; w=weight at the end of the line"}),
        p + "value_distribution": (list(_aa2.DISTRIBUTIONS),),
        p + "remap_ramp": _s("0:0 1:1"),
        p + "outlier_percent": _f(10.0, 0.0, 100.0, 0.1),
        p + "outlier_range": num(1.0),
        p + "outlier_range_mode": (list(_aa2.OUTLIER_MODES),),
        p + "outlier_extent": (list(_aa2.OUTLIER_EXTENTS),),
        p + "outlier_attribute": _s(""),
        p + "outlier_seed": _i(0, 0, 1 << 30),
        p + "use_stepping": _b(False),
        p + "step_size": (_i(1, 1, 1 << 30) if integer else _f(1.0, 0.0, 1e6, 0.01)),
    }


def _aa2_scalar(kw, integer, prefix=""):
    p = prefix
    return _aa2.ScalarSpec(
        kw[p + "range_values"], kw[p + "min_value"], kw[p + "max_value"],
        kw[p + "middle_value"], kw[p + "range_length"],
        kw[p + "value_distribution"], kw[p + "remap_ramp"],
        kw[p + "outlier_percent"], kw[p + "outlier_range"],
        kw[p + "outlier_range_mode"], kw[p + "outlier_extent"],
        kw[p + "outlier_seed"], kw[p + "use_stepping"], kw[p + "step_size"],
        kw[p + "value_list"], integer)


def _aa2_scalar_node_inputs(integer):
    num = (lambda d: _i(int(d), -(1 << 30), 1 << 30)) if integer else (lambda d: _f(d))
    head = {
        "geo": (GEO,), "group": _group(),
        "attribute_name": _names("attrib", "point", "pscale",
                                 "v.x / v[0] changes one component only; a vector attribute without a component = adjust the length"),
        "attribute_class": (list(_aa2.CLASSES),),
    }
    if not integer:                         # Integer's docs have no Blend
        head.update({"blend_mode": (list(_aa2.BLEND_MODES),),
                     "blend": _f(1.0, 0.0, 1.0, 0.01),
                     "blend_attribute": _names("attrib", "point", "mask")})
    return {"required": {
        **head,
        "adjust_value": _b(True),
        "operation": (list(_aa2.OPERATIONS),),
        "pattern_type": (list(_aa2.PATTERNS),),
        "constant_value": num(0.0),
        **_aa2_scalar_inputs(integer),
        "adjustment_attribute": _names("attrib", "point", ""),
        "attribute_adjustment": (list(_aa2.ATTRIB_MODES),),
        "attribute_scale": _f(1.0), "attribute_offset": _f(0.0),
        "randomization_by": (list(_aa2.RAND_BY),),
        "custom_attribute": _names("attrib", "point", "id"),
        "rand_seed": _i(0, 0, 1 << 30),
        **_aa2_noise_inputs(),
        "use_minimum": _b(False), "minimum": num(0.0),
        "use_maximum": _b(False), "maximum": num(1.0),
    }}


def _aa2_scalar_run(kw, integer):
    return (_aa2.adjust_scalar(
        kw["geo"], kw["attribute_name"], kw["attribute_class"], kw["group"],
        integer, kw.get("blend_mode", "constant"), kw.get("blend", 1.0),
        kw.get("blend_attribute", ""), kw["adjust_value"], kw["operation"],
        kw["pattern_type"], kw["constant_value"], _aa2_scalar(kw, integer),
        kw["adjustment_attribute"], kw["attribute_adjustment"],
        kw["attribute_scale"], kw["attribute_offset"], kw["randomization_by"],
        kw["custom_attribute"], kw["rand_seed"], _aa2_noise(kw),
        kw["use_minimum"], kw["minimum"], kw["use_maximum"], kw["maximum"],
        kw["outlier_attribute"]),)


@_node("attribute")
class PCG_AttribAdjustFloat:
    """
    Maps to: Attribute Adjust Float (Houdini semantics; the merged PCG_AttribAdjust is kept).
    Adjustment value = Pattern Type (Constant / Random / Noise / Attribute); Random and Noise
    take values by Range Values (Min/Max, Min + Range Length, Middle ± Range Length half width,
    Specific Values value table), Value Distribution can add a Remap Ramp or outliers;
    then combined with the original value by Operation (Set Always / Set Initial / Add / Subtract / Multiply / Min / Max),
    blended back by Blend, clamped by Minimum / Maximum. Value table: one group per line, w=weight at the end of the line.
    Not done: Unit Settings, VEXpression, Animate Noise, Warping, Default Value.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return _aa2_scalar_node_inputs(False)

    def run(self, **kw):
        return _aa2_scalar_run(kw, False)


@_node("attribute")
class PCG_AttribAdjustInteger:
    """
    Maps to: Attribute Adjust Integer. The same set as the Float version, differences: no Blend;
    random integers are uniform over [Min, Max] **inclusive of both ends** (Step Size counts from Min: 1..9 step 2 →
    1 3 5 7 9); outliers lie at least 1 outside the range; rounded at the end. A missing attribute is created as int32.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return _aa2_scalar_node_inputs(True)

    def run(self, **kw):
        return _aa2_scalar_run(kw, True)



@_node("attribute")
class PCG_AttribAdjustVector:
    """
    Maps to: Attribute Adjust Vector. Adjustment for: Direction & Length (the adjustment value is a vector) /
    Direction Only (Add / Subtract then normalised back to the original length, Rotate about an axis, Spread over a cone, Interpolate
    spherically towards Goal) / Length Only (scalar, changes the length). Vector adjustment values: Positive / Zero Centered
    (Amplitude × Amplitude Scale) / Min/Max / Specific Values (one x y z per line); scalar adjustment values
    (length, angle, Bias) use the Float node's set of Range Values. Pre-Process: Overwrite Initial
    Value (Constant / normal / attribute), Reverse, Unit Length, Length Scale; Post-Process:
    Blend (Linear / Spherical), Length Scale, Min / Max Length, Unit Length, Length attribute.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "attribute_name": _names("attrib", "point", "v"),
            "attribute_class": (list(_aa2.CLASSES),),
            # Pre-Process
            "enable_preprocess": _b(False),
            "overwrite_initial": _b(False),
            "initial_from": (list(_aa2.INITIAL_FROM),),
            **_v3("initial_vector", (0.0, 1.0, 0.0)),
            "initial_attribute": _names("attrib", "point", "N"),
            "reverse_direction": _b(False),
            "pre_unit_length": _b(False),
            "use_pre_length_scale": _b(False),
            "pre_length_scale": _f(1.0),
            # Adjustment Value
            "adjust_value": _b(True),
            "adjustment_for": (list(_aa2.ADJUST_FOR),),
            "operation": (list(_aa2.VEC_OPERATIONS),),
            "adjust_with": (list(_aa2.PATTERNS),),
            **_v3("constant_vector", (0.0, 1.0, 0.0)),
            "vector_range": (list(_aa2.VEC_RANGES), {"default": "zero_centered"}),
            "amplitude": _f(1.0),
            **_v3("amplitude_scale", (1.0, 1.0, 1.0)),
            **_v3("min_vector", (0.0, 0.0, 0.0)),
            **_v3("max_vector", (1.0, 1.0, 1.0)),
            "vector_list": ("STRING", {"default": "0 1 0\n1 0 0", "multiline": True,
                                       "tooltip": "One vector per line: x y z; w=weight at the end of the line"}),
            "scalar_value": _f(1.0),
            **_aa2_scalar_inputs(False),
            "axis_from": (list(_aa2.VEC_SOURCES),),
            **_v3("axis", (0.0, 1.0, 0.0)),
            "axis_attribute": _names("attrib", "point", "up"),
            "goal_from": (list(_aa2.VEC_SOURCES),),
            **_v3("goal", (0.0, 1.0, 0.0)),
            "goal_attribute": _names("attrib", "point", "N"),
            "adjustment_attribute": _names("attrib", "point", ""),
            # Random / Noise
            "randomization_by": (list(_aa2.RAND_BY),),
            "custom_attribute": _names("attrib", "point", "id"),
            "rand_seed": _i(0, 0, 1 << 30),
            **_aa2_noise_inputs(),
            # Post-Process
            "blend_mode": (list(_aa2.BLEND_MODES),),
            "blend": _f(1.0, 0.0, 1.0, 0.01),
            "blend_attribute": _names("attrib", "point", "mask"),
            "blend_type": (list(_aa2.BLEND_TYPES),),
            "use_post_length_scale": _b(False), "post_length_scale": _f(1.0),
            "use_min_length": _b(False), "min_length": _f(0.0, 0.0),
            "use_max_length": _b(False), "max_length": _f(1.0, 0.0),
            "post_unit_length": _b(False),
            "length_attribute": _s(""),
        }}

    def run(self, **kw):
        v3 = lambda p: (kw[p + "_x"], kw[p + "_y"], kw[p + "_z"])   # noqa: E731
        return (_aa2.adjust_vector(
            kw["geo"], kw["attribute_name"], kw["attribute_class"], kw["group"],
            kw["enable_preprocess"], kw["overwrite_initial"], kw["initial_from"],
            v3("initial_vector"), kw["initial_attribute"], kw["reverse_direction"],
            kw["pre_unit_length"], kw["use_pre_length_scale"], kw["pre_length_scale"],
            kw["adjust_value"], kw["adjustment_for"], kw["operation"], kw["adjust_with"],
            v3("constant_vector"), kw["vector_range"], kw["amplitude"],
            v3("amplitude_scale"), v3("min_vector"), v3("max_vector"), kw["vector_list"],
            kw["scalar_value"], _aa2_scalar(kw, False),
            kw["axis_from"], v3("axis"), kw["axis_attribute"],
            kw["goal_from"], v3("goal"), kw["goal_attribute"], kw["adjustment_attribute"],
            kw["randomization_by"], kw["custom_attribute"], kw["rand_seed"], _aa2_noise(kw),
            kw["blend_mode"], kw["blend"], kw["blend_attribute"], kw["blend_type"],
            kw["use_post_length_scale"], kw["post_length_scale"],
            kw["use_min_length"], kw["min_length"], kw["use_max_length"], kw["max_length"],
            kw["post_unit_length"], kw["length_attribute"], kw["outlier_attribute"]),)



def _rgbw(prefix, d):
    return {f"{prefix}_r": _f(d[0], -1e6, 1e6), f"{prefix}_g": _f(d[1], -1e6, 1e6),
            f"{prefix}_b": _f(d[2], -1e6, 1e6)}


@_node("attribute")
class PCG_AttribAdjustColor:
    """
    Maps to: Attribute Adjust Color (Houdini semantics; PCG_Color is kept as the Color SOP). Pattern Type:
    Constant / Random / Noise / Color Attribute / Remap Attribute / Bounding Box;Random
    and Noise's Range Values: Min/Max (RGB or HSV space) / Color Ramp / Specific Colors
    (Color Scheme derived from a base colour, or one r g b + w= per line). Operation includes Overlay / Screen /
    Hard Mix / Difference. Then Color Correction (Hue / Saturation / Value / Brightness /
    Contrast / Gain / Gamma), Post-Process (Min / Max / Complement), and finally Blend back to the input.
    Not done: Color Map (texture sampling), Line / Radial (ramps drawn with viewport handles), per-attribute versions of the correction parameters.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "blend_mode": (list(_aa2.BLEND_MODES),),
            "blend": _f(1.0, 0.0, 1.0, 0.01),
            "blend_attribute": _names("attrib", "point", "mask"),
            "attribute_name": _names("attrib", "point", "Cd"),
            "attribute_class": (list(_aa2.CLASSES),),
            # Pre-Process
            "delete_other_colors": _b(False),
            "overwrite_initial": _b(False),
            "initial_from": (list(_aa2.COLOR_INITIAL),),
            **_rgbw("initial_color", (1.0, 1.0, 1.0)),
            "initial_attribute": _names("attrib", "point", ""),
            # Adjustment Value
            "adjust_value": _b(True),
            "operation": (list(_aa2.COLOR_OPERATIONS),),
            "pattern_type": (list(_aa2.COLOR_PATTERNS),),
            **_rgbw("color", (1.0, 1.0, 1.0)),
            "range_values": (list(_aa2.COLOR_RANGES),),
            "color_space": (list(_aa2.COLOR_SPACES),),
            **_rgbw("min_color", (0.0, 0.0, 0.0)),
            **_rgbw("max_color", (1.0, 1.0, 1.0)),
            "color_ramp": _s("0:0,0,0 1:1,1,1"),
            "color_scheme": (list(_aa2.COLOR_SCHEMES),),
            **_rgbw("scheme_color", (1.0, 0.0, 0.0)),
            "scheme_distance": _f(30.0, 0.0, 180.0, 1.0),
            "color_list": ("STRING", {"default": "1 0 0\n0 1 0\n0 0 1", "multiline": True,
                                      "tooltip": "One colour per line: r g b; w=weight at the end of the line"}),
            "adjustment_attribute": _names("attrib", "point", ""),
            "source_attribute": _names("attrib", "point", ""),
            **_v3("bbox_direction", (0.0, 1.0, 0.0)),
            "compute_range": _b(True),
            "source_min": _f(0.0), "source_max": _f(1.0),
            # Random / Noise
            "randomization_by": (list(_aa2.RAND_BY),),
            "custom_attribute": _names("attrib", "point", "id"),
            "rand_seed": _i(0, 0, 1 << 30),
            **_aa2_noise_inputs(),
            # Color Correction
            "hue_shift": _f(0.0, -360.0, 360.0, 1.0),
            "saturation": _f(1.0, 0.0, 100.0, 0.01),
            "value": _f(1.0, 0.0, 100.0, 0.01),
            "brightness": _f(0.0),
            "contrast": _f(1.0, 0.0, 100.0, 0.01),
            "gain": _f(1.0, 0.0, 100.0, 0.01),
            "gamma": _f(1.0, 0.001, 100.0, 0.01),
            # Post-Process
            "use_minimum": _b(False), "minimum": _f(0.0),
            "use_maximum": _b(False), "maximum": _f(1.0),
            "complement": _b(False),
        }}

    def run(self, **kw):
        c3 = lambda p: (kw[p + "_r"], kw[p + "_g"], kw[p + "_b"])   # noqa: E731
        return (_aa2.adjust_color(
            kw["geo"], kw["attribute_name"], kw["attribute_class"], kw["group"],
            kw["blend_mode"], kw["blend"], kw["blend_attribute"],
            kw["delete_other_colors"], kw["overwrite_initial"], kw["initial_from"],
            c3("initial_color"), kw["initial_attribute"],
            kw["adjust_value"], kw["operation"], kw["pattern_type"], c3("color"),
            kw["range_values"], kw["color_space"], c3("min_color"), c3("max_color"),
            kw["color_ramp"], kw["color_scheme"], c3("scheme_color"), kw["scheme_distance"],
            kw["color_list"], kw["adjustment_attribute"], kw["source_attribute"],
            (kw["bbox_direction_x"], kw["bbox_direction_y"], kw["bbox_direction_z"]),
            kw["compute_range"], kw["source_min"], kw["source_max"],
            kw["randomization_by"], kw["custom_attribute"], kw["rand_seed"], _aa2_noise(kw),
            kw["hue_shift"], kw["saturation"], kw["value"], kw["brightness"],
            kw["contrast"], kw["gain"], kw["gamma"],
            kw["use_minimum"], kw["minimum"], kw["use_maximum"], kw["maximum"],
            kw["complement"]),)


# ═══════════════════════════════════════════════════════ pcg100 s7: attribute miscellany
@_node("attribute", _WITH_REPORT)
class PCG_AttribFadeTime:
    """
    Maps to: Attribute Fade (Houdini semantics -- fades a point attribute in / holds / fades it out over **time**).
    PCG_AttribFade is spatial falloff, a different thing, kept. Frame is the current frame (connect a playbar / value node);
    each point's start frame = Fade Start Frame attribute × Retime + Frame Offset, read from the second input if connected;
    Hold duration × Hold Frame Scale attribute (read from the third input if connected). Output = original value × fade;
    a missing attribute counts as 1. Visualize Fade writes fade into Cd.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "visualize": _b(False),
            "fade_attribute": _names("attrib", "point", "fade"),
            "start_attribute": _names("attrib", "point", "fadestart"),
            "start_retime": _f(1.0, -1e6, 1e6),
            "hold_scale_attribute": _names("attrib", "point", "holdscale"),
            "frame": _f(1.0, -1e6, 1e6, 1.0),
            "frame_offset": _f(0.0, -1e6, 1e6, 1.0),
            "fade_in": _f(10.0, 0.0, 1e6, 1.0),
            "fade_hold": _f(10.0, 0.0, 1e6, 1.0),
            "fade_out": _f(10.0, 0.0, 1e6, 1.0),
            "fade_in_ramp": _s("0:0 1:1"),
            "fade_in_ramp_mode": (list(_aft.RAMP_MODES),),
            "fade_out_ramp": _s("0:1 1:0"),
            "fade_out_ramp_mode": (list(_aft.RAMP_MODES),),
        }, "optional": {"start_geo": (GEO,), "hold_geo": (GEO,)}}

    def run(self, geo, group, visualize, fade_attribute, start_attribute, start_retime,
            hold_scale_attribute, frame, frame_offset, fade_in, fade_hold, fade_out,
            fade_in_ramp, fade_in_ramp_mode, fade_out_ramp, fade_out_ramp_mode,
            start_geo=None, hold_geo=None):
        g, r = _aft.attrib_fade_time(
            geo, group, fade_attribute, frame, start_attribute, start_retime,
            hold_scale_attribute, frame_offset, fade_in, fade_hold, fade_out,
            fade_in_ramp, fade_in_ramp_mode, fade_out_ramp, fade_out_ramp_mode,
            visualize, start_geo, hold_geo)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_AttribTransformExtractHou:
    """
    Maps to: Attribute Transform Extract (Houdini / KineFX semantics). Breaks 9 / 16-component matrix attributes on points
    into translate / rotate (Euler, degrees) / Stretch (Polar Decomposition) or scale / shear (Crack Transform,
    inverse to the Transform SOP), then Euler-filters rotations by hierarchy (None / Topology / Pieces or Points).
    PCG_AttribTransformExtract (rigid transforms per piece between two geometries rest / animated) is a different thing, kept.
    The matrix convention matches Houdini (row vectors p' = p·M, translation in row 4), and so does Transform by Attribute.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "group": _group(),
            "hierarchy": (list(_xe.HIERARCHY),),
            "piece_attribute": _names("attrib", "point", "name"),
            **_v3("hint", (0.0, 0.0, 0.0)),
            "decomposition": (list(_xe.DECOMPOSITIONS),),
            "xform_order": (list(_xe.XFORM_ORDERS),),
            "rotate_order": (list(_xe.ROTATE_ORDERS),),
            "attributes": _names("attrib", "point", "transform"),
            "t_prefix": _s(""), "t_suffix": _s("_t"),
            "r_prefix": _s(""), "r_suffix": _s("_r"),
            "stretch_prefix": _s(""), "stretch_suffix": _s("_stretch"),
            "s_prefix": _s(""), "s_suffix": _s("_s"),
            "sh_prefix": _s(""), "sh_suffix": _s("_sh"),
        }}

    def run(self, geo, group, hierarchy, piece_attribute, hint_x, hint_y, hint_z,
            decomposition, xform_order, rotate_order, attributes, t_prefix, t_suffix,
            r_prefix, r_suffix, stretch_prefix, stretch_suffix, s_prefix, s_suffix,
            sh_prefix, sh_suffix):
        g, r = _xe.attrib_transform_extract(
            geo, group, hierarchy, piece_attribute, (hint_x, hint_y, hint_z),
            decomposition, xform_order, rotate_order, attributes, t_prefix, t_suffix,
            r_prefix, r_suffix, stretch_prefix, stretch_suffix, s_prefix, s_suffix,
            sh_prefix, sh_suffix)
        return (g, _rep(r))


@_node("attribute", _WITH_REPORT)
class PCG_Name:
    """
    Maps to: Name. Writes a string attribute (default name) on elements in groups: Namings has one "group : name" per line (a leading # =
    Enable off), later lines override earlier ones; with Name from Group on it instead "names by the group it belongs to" (Group Mask filters group names).
    Finally a From → To replacement is done over the whole column of values (Global = replace all, otherwise only the first occurrence).
    The PCG_Enumerate (Format numbering) previously attached to Name is Enumerate, kept.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "attribute": _names("attrib", "prim", "name"),
            "cls": (list(_nm.NAME_CLASSES),),
            "name_from_group": _b(False),
            "group_mask": _s("*"),
            "namings": ("STRING", {"multiline": True, "default": ""}),
            "global_replace": _b(True),
            "from_": _s(""), "to": _s(""),
        }}

    def run(self, geo, attribute, cls, name_from_group, group_mask, namings,
            global_replace, from_, to):
        g, r = _nm.name_sop(geo, attribute, cls, name_from_group, group_mask, namings,
                            global_replace, from_, to)
        return (g, _rep(r))


@_node("modify", _WITH_REPORT)
class PCG_PolyDoctor:
    """
    Maps to: PolyDoctor. Checks polygon problems item by item, each Ignore / Mark / Repair: Ill-Formed, 5+ Edges,
    Non-Convex, Overlapping (+ Pair Overlaps), Locally Small Areas, Non-Uniform (mark only),
    Globally / Locally Small Edges, Disconnected Points, Non-Manifold Points. Marks write
    valid_poly / valid_pt = 0, repairs write repaired_poly / repaired_pt = 1 (optionally a _grp group for each);
    repairs run at most Max Passes rounds. PCG_Clean (Clean SOP) is kept.
    pcg122 Self-Intersecting (mark only): polygons that pass through other polygons of the same mesh, found with
    Intersection Analysis (faces sharing a point are not tested against each other).
    """
    @classmethod
    def INPUT_TYPES(cls):
        m, mo = list(_pd.PD_MODES), list(_pd.PD_MARK_ONLY)
        return {"required": {
            "geo": (GEO,), "max_passes": _i(10, 1, 1000),
            "ill_formed": (m, {"default": "repair"}),
            "five_plus": (m, {"default": "ignore"}),
            "non_convex": (m, {"default": "ignore"}),
            "overlapping": (m, {"default": "repair"}),
            "pair_overlaps": _b(False),
            "local_area": (m, {"default": "ignore"}),
            "local_area_threshold": _f(0.1, 0.0, 1.0, 0.01),
            "non_uniform": (mo, {"default": "ignore"}),
            "uniformity_threshold": _f(0.1, 0.0, 1.0, 0.01),
            "global_edges": (m, {"default": "ignore"}),
            "global_edge_threshold": _f(0.001, 0.0, 1.0, 0.001),
            "local_edges": (m, {"default": "ignore"}),
            "local_edge_threshold": _f(0.1, 0.0, 1.0, 0.01),
            "disconnected": (m, {"default": "repair"}),
            "nonmanifold": (m, {"default": "ignore"}),
            "valid_poly": _s("valid_poly"), "repaired_poly": _s("repaired_poly"),
            "valid_pt": _s("valid_pt"), "repaired_pt": _s("repaired_pt"),
            "create_groups": _b(False),
            # pcg122
            "self_intersecting": (mo, {"default": "ignore"}),
        }}

    def run(self, geo, max_passes, ill_formed, five_plus, non_convex, overlapping,
            pair_overlaps, local_area, local_area_threshold, non_uniform,
            uniformity_threshold, global_edges, global_edge_threshold, local_edges,
            local_edge_threshold, disconnected, nonmanifold, valid_poly, repaired_poly,
            valid_pt, repaired_pt, create_groups, self_intersecting="ignore"):
        g, r = _pd.polydoctor(
            geo, max_passes, ill_formed, five_plus, non_convex, overlapping, pair_overlaps,
            local_area, local_area_threshold, non_uniform, uniformity_threshold,
            global_edges, global_edge_threshold, local_edges, local_edge_threshold,
            disconnected, nonmanifold, valid_poly, repaired_poly, valid_pt, repaired_pt,
            create_groups, self_intersecting)
        return (g, _rep(r))


# ═══════════════════════════════════════════════════════ pcg100 s8_uv
@_node("uv")
class PCG_UVPelt:
    """
    Maps to: UV Pelt (2.0). A different thing from UV Flatten's conformal flattening (audit [C]): cuts into disks along Edge Cut Group,
    pins the **longest boundary loop** of the piece containing Hint Primitive onto a frame by arc length (a circle by default; if the second input gives a
    closed face it is used, U = P.x, V = P.y), and pulls the inside flat with springs. Pelting Method decides spring weights:
    spring_relaxation (adjacent area / edge length²), tutte_barycentric (unit weights, no flips on a convex frame),
    discrete_harmonic (cotangent weights). Boundary Springs is the strength of the springs connecting border points to the frame; larger sticks closer to the frame.
    Only the hint face's piece is unwrapped; other faces keep their uv as is (0 if none).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "attribute_name": _names("attrib", "vertex", "uv"),
            "seam_group": _names("group", "edge", "", "Cut along these edges"),
            "method": (list(_upe.METHODS),),
            "output_group": _names("group", "prim", "", "Empty = not written"),
            "iterations": _i(1000, 1, 1 << 20),
            "boundary_springs": _f(10.0, 1e-6, 1e9, 0.1),
            "stiffness_attribute": _names("attrib", "point", ""),
            "hint_prim": _i(0, 0, 1 << 30),
            "use_range": _b(False),
            "u_range_min": _f(0.0), "u_range_max": _f(1.0),
            "v_range_min": _f(0.0), "v_range_max": _f(1.0),
            "orientation": _f(0.0, -1e6, 1e6, 0.01),
        }, "optional": {"frame": (GEO,)}}

    def run(self, geo, attribute_name, seam_group, method, output_group, iterations,
            boundary_springs, stiffness_attribute, hint_prim, use_range, u_range_min,
            u_range_max, v_range_min, v_range_max, orientation, frame=None):
        return (_upe.pelt(geo, frame, attribute_name, seam_group, method, iterations,
                          boundary_springs, stiffness_attribute, hint_prim, use_range,
                          (u_range_min, u_range_max), (v_range_min, v_range_max),
                          orientation, output_group),)


@_node("uv")
class PCG_UVUnwrap:
    """
    Maps to: UV Unwrap. Not the same as UV Flatten (audit [C]): each face picks the plane with the least projection distortion
    (by default the coordinate planes of the three axes, Rotate turns them as a whole; if the second input gives polygons they are used as planes), connected faces projected onto the same plane
    form one region, regions are laid out by Layout (strip in a row / square packed into a square), then scaled by Scale
    (none world size / uniform fit proportionally into 0..1 / stretch fill 0..1). Spacing is the region gap as a percentage of the layout space.
    Faces facing the back of a plane form separate regions with u negated (not mirrored). Faces outside Group keep their uv.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "attribute_name": _names("attrib", "vertex", "uv"),
            "group": _group(),
            "plane_group": _names("group", "prim", "", "Which polygons of the second input act as planes; empty = all"),
            "layout": (list(_uuw.LAYOUTS),),
            "scale": (list(_uuw.SCALES),),
            "spacing": _f(5.0, 0.0, 100.0, 0.5),
            "rotate_order": (list(_ops.ROTATE_ORDERS),),
            "rotate_x": _f(0.0, -360.0, 360.0, 1.0),
            "rotate_y": _f(0.0, -360.0, 360.0, 1.0),
            "rotate_z": _f(0.0, -360.0, 360.0, 1.0),
        }, "optional": {"planes": (GEO,)}}

    def run(self, geo, attribute_name, group, plane_group, layout, scale, spacing,
            rotate_order, rotate_x, rotate_y, rotate_z, planes=None):
        return (_uuw.unwrap(geo, planes, attribute_name, group, plane_group, layout,
                            scale, spacing, rotate_order, (rotate_x, rotate_y, rotate_z)),)


_NAMES = {
    "PCG_OrientAlongCurve": "Orient Along Curve (PCG)",
    "PCG_PolyFrame": "PolyFrame (PCG)",
    "PCG_CopyAndTransform": "Copy and Transform (PCG)",
    "PCG_Revolve": "Revolve (PCG)",
    "PCG_CopyToCurves": "Copy to Curves (PCG)",
    "PCG_Chain": "Chain (PCG)",
    "PCG_FindShortestPath": "Find Shortest Path (PCG)",
    "PCG_GroupFindPath": "Group Find Path (PCG)",
    "PCG_CurveIntersect": "Curve Intersect (PCG)",
    "PCG_ConnectAdjacentPieces": "Connect Adjacent Pieces (PCG)",
    "PCG_AttribFromPieces": "Attribute from Pieces (PCG)",
    "PCG_Enumerate": "Enumerate (PCG)",
    "PCG_Color": "Color (PCG)",
    "PCG_AttribFill": "Attribute Fill (PCG)",
    "PCG_AttribStringEdit": "Attribute String Edit (PCG)",
    "PCG_ClusterPoints": "Cluster Points (PCG)",
    "PCG_Remesh": "Remesh (PCG)",
    "PCG_Clean": "Clean (PCG)",
    "PCG_EdgeCollapse": "Edge Collapse (PCG)",
    "PCG_PointSplit": "Point Split (PCG)",
    "PCG_UVFuse": "UV Fuse (PCG)",
    "PCG_PlatonicSolids": "Platonic Solids (PCG)",
    "PCG_LSystem": "L-System (PCG)",
    "PCG_Font": "Font (PCG)",
    "PCG_LatticeFromBound": "Lattice From Bound (PCG)",
    "PCG_Lattice": "Lattice (PCG)",
    "PCG_PointDeform": "Point Deform (PCG)",
    "PCG_BlendShapes": "Blend Shapes (PCG)",
    "PCG_TransformPieces": "Transform Pieces (PCG)",
    "PCG_PolyBridge": "Poly Bridge (PCG)",
    "PCG_AttribFromVolume": "Attribute from Volume (PCG)",
    "PCG_AttribTransferByUV": "Attribute Transfer by UV (PCG)",
    "PCG_Volume": "Volume (PCG)",
    "PCG_VolumeBlur": "Volume Blur (PCG)",
    "PCG_VolumeMix": "Volume Mix (PCG)",
    "PCG_VolumeResample": "Volume Resample (PCG)",
    "PCG_VolumeWrangle": "Volume Wrangle (PCG)",
    "PCG_VolumeReshapeSDF": "Volume Reshape SDF (PCG)",
    "PCG_ExtractTransform": "Extract Transform (PCG)",
    "PCG_AttribTransformExtract": "Attribute Transform Extract (PCG)",
    "PCG_MatchAxis": "Match Axis (PCG)",
    "PCG_Primitive": "Primitive (PCG)",
    "PCG_AttribReorient": "Attribute Reorient (PCG)",
    "PCG_MatchTopology": "Match Topology (PCG)",
    "PCG_TopoTransfer": "Topo Transfer (PCG)",
    "PCG_DeltaMush": "DeltaMush (PCG)",
    "PCG_EdgeEqualize": "Edge Equalize (PCG)",
    "PCG_EdgeStraighten": "Edge Straighten (PCG)",
    "PCG_CircleFromEdges": "Circle from Edges (PCG)",
    "PCG_EdgeFlip": "Edge Flip (PCG)",
    "PCG_TriDivide": "Tri Divide (PCG)",
    "PCG_Unsubdivide": "Unsubdivide (PCG)",
    "PCG_RewireVertices": "Rewire Vertices (PCG)",
    "PCG_PolyCut": "PolyCut (PCG)",
    "PCG_PolyStitch": "PolyStitch (PCG)",
    "PCG_VoronoiSplit": "Voronoi Split (PCG)",
    "PCG_CircleSpline": "Circle Spline (PCG)",
    "PCG_PolySpline": "PolySpline (PCG)",
    "PCG_BallisticPath": "Ballistic Path (PCG)",
    "PCG_PolyLoft": "PolyLoft (PCG)",
    "PCG_CrossSectionSurface": "Cross Section Surface (PCG)",
    "PCG_CrossSectionSurfaceHou": "Cross Section Surface · Houdini (PCG)",
    "PCG_AttribComposite": "Attribute Composite (PCG)",
    "PCG_AttribMirror": "Attribute Mirror (PCG)",
    "PCG_GroupFromAttribBoundary": "Group from Attribute Boundary (PCG)",
    "PCG_Partition": "Partition (PCG)",
    "PCG_TangentField": "Tangent Field (PCG)",
    "PCG_AdaptivePrune": "Adaptive Prune (PCG)",
    "PCG_PointReplicate": "Point Replicate (PCG)",
    "PCG_PointVelocity": "Point Velocity (PCG)",
    "PCG_IsoSurface": "IsoSurface (PCG)",
    "PCG_RemeshToGrid": "Remesh to Grid (PCG)",
    "PCG_UVSmooth": "UV Smooth (PCG)",
    "PCG_ExtractSilhouette": "Extract Silhouette (PCG)",
    "PCG_CameraToPoints": "Camera To Points (PCG)",
    "PCG_CameraFromPoints": "Camera from Points (PCG)",
    "PCG_GroupCombine": "Group Combine (PCG)",
    "PCG_SwitchIf": "Switch-If (PCG)",
    "PCG_PointRelax": "Point Relax (PCG)",
    "PCG_PrimitiveSplit": "Primitive Split (PCG)",
    "PCG_TransformByAttrib": "Transform by Attribute (PCG)",
    "PCG_PolySplit": "PolySplit (PCG)",
    "PCG_EdgeCusp": "Edge Cusp (PCG)",
    "PCG_Crease": "Crease (PCG)",
    "PCG_Shrinkwrap": "Shrinkwrap (PCG)",
    "PCG_SoftPeak": "Soft Peak (PCG)",
    "PCG_Bulge": "Bulge (PCG)",
    "PCG_Magnet": "Magnet (PCG)",
    "PCG_Fractal": "Fractal (PCG)",
    "PCG_ScatterAlign": "Scatter and Align (PCG)",
    "PCG_EdgeTransport": "Edge Transport (PCG)",
    "PCG_VolumeRasterizeAttribs": "Volume Rasterize Attributes (PCG)",
    "PCG_ExportInstances": "Export Instances (PCG)",
    "PCG_BlastByAttribute": "Blast by Attribute (PCG)",
    "PCG_AttribAdjustFloat": "Attribute Adjust Float (PCG)",
    "PCG_AttribAdjustInteger": "Attribute Adjust Integer (PCG)",
    "PCG_AttribAdjustVector": "Attribute Adjust Vector (PCG)",
    "PCG_AttribAdjustColor": "Attribute Adjust Color (PCG)",
    "PCG_AttribFadeTime": "Attribute Fade · Time (PCG)",
    "PCG_AttribTransformExtractHou": "Attribute Transform Extract · Houdini (PCG)",
    "PCG_Name": "Name (PCG)",
    "PCG_PolyDoctor": "PolyDoctor (PCG)",
    "PCG_UVPelt": "UV Pelt (PCG)",
    "PCG_UVUnwrap": "UV Unwrap (PCG)",
    "PCG_VolumeSmoothSDF": "Volume Smooth SDF (PCG)",
    "PCG_BooleanFracture": "Boolean Fracture (PCG)",
    "PCG_IsoOffset": "IsoOffset (PCG)",
    "PCG_IntersectionAnalysis": "Intersection Analysis (PCG)",
    "PCG_FileMerge": "File Merge (PCG)",
}

NODE_CLASS_MAPPINGS = {k: globals()[k] for k in _NAMES}
NODE_DISPLAY_NAME_MAPPINGS = dict(_NAMES)
