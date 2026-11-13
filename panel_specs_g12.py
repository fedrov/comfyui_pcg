"""
Panel specs for group g12: PolyFill / PolyPath / PolySpline / Primitive / Primitive Split / Ray /
Refine / Remesh / Remesh to Grid / Resample / Reverse / Shrinkwrap / Smooth / Sort /
Split / Switch / Switch-If / Transform by Attribute / Triangulate 2D / Volume Blur /
Volume Mix / Volume Resample / Reshape SDF / Voronoi Cluster / Voronoi Fracture /
Voronoi Split / File Cache / Geo Metrics / Preview Image / Channel / Channel XYZ /
Expression / Expression XYZ / Frame / Param Pick / Params from JSON / Value /
Camera / Camera from Points. Format: see the notes at the top of panel_specs.py.

The hide / disable conditions follow the branches where a parameter really takes effect in the node code (nodes*.py / expr.py / params.py run() + geo/
implementation), not a copy of Houdini.
"""


def _not_any(parm, toks):
    """{ parm != a parm != b ... }: true when the value is not in toks."""
    return "{ " + " ".join(f"{parm} != {t}" for t in toks) + " }"


def _neither(toks, parms=("point_sort", "prim_sort")):
    """For Sort: true when neither sort dropdown is any of the modes in toks (AND)."""
    return "{ " + " ".join(f"{p} != {t}" for p in parms for t in toks) + " }"



def _sort_side(mode, pre, side):
    """For Sort: parameters of one side (points / primitives), shown only when that side's sort method uses them."""
    hid = lambda *ts: "{ " + " ".join(f"{mode} != {t}" for t in ts) + " }"  # noqa: E731
    att = "point_attrib" if pre == "" else "prim_attrib"
    exp = "point_expr" if pre == "" else "prim_expr"
    return {
        pre + "rand_seed": {"section": None, "label": "Seed", "hide": hid("random"),
                            "disable": "{ use_rs == 0 }"},
        pre + "offset": {"section": None, "label": "Offset", "hide": hid("shift"),
                         "disable": "{ use_rs == 0 }"},
        pre + "axis_x": {"section": None, "row": {"label": "Vector"},
                         "hide": hid("along_vector", "circular"),
                         "disable": "{ use_axis == 0 }"},
        pre + "use_center": {"section": None, "label": "Specify Center",
                             "hide": hid("circular"), "disable": "{ use_axis == 0 }"},
        pre + "center_x": {"section": None, "row": {"label": "Center"}, "hide": hid("circular"),
                           "disable": "{ use_axis == 0 } { " + pre + "use_center == 0 }"},
        pre + "target_x": {"section": None, "row": {"label": "Point"},
                           "hide": hid("proximity"), "disable": "{ use_target == 0 }"},
        att: {"section": None, "label": f"{side} Attribute", "hide": hid("attribute"),
              "disable": "{ use_key == 0 }"},
        pre + "component": {"section": None, "label": "Component", "hide": hid("attribute"),
                            "disable": "{ use_key == 0 }"},
        exp: {"section": None, "label": f"{side} Expression", "hide": hid("expression"),
              "disable": "{ use_key == 0 }"},
    }

_FILL_MENU = {"ngon": "Single Polygon", "fan": "Triangle Fan", "triangles": "Triangles",
              "quad_fan": "Quadrilateral Fan", "quads": "Quadrilaterals",
              "quad_grid": "Quadrilateral Grid"}

_SORT_MENU = {"none": "No Change", "x": "Sort by X", "y": "Sort by Y",
              "z": "Sort by Z", "reverse": "Reverse", "random": "Random",
              "shift": "Shift", "proximity": "Proximity to Point",
              "along_vector": "Along Vector", "attribute": "By Attribute",
              "expression": "By Expression",
              "spatial_locality": "By Spatial Locality",
              "circular": "Circular (Around Axis)"}

_PROJ_MENU = {"perspective": "Perspective", "orthographic": "Orthographic"}

_INTERP_MENU = {"constant": "Constant", "linear": "Linear", "ease": "Ease",
                "easein": "Ease In", "easeout": "Ease Out", "cubic": "Cubic",
                "quintic": "Quintic"}
_EXTRAP_MENU = {"hold": "Hold", "linear": "Linear (Slope)", "cycle": "Cycle",
                "cycleoffset": "Cycle with Offset", "mirror": "Mirror"}

_PLANE_MENU = {"fit_plane": "Fit Plane", "xy": "XY Plane", "zx": "ZX Plane",
               "yz": "YZ Plane", "specify_plane": "Specify Plane"}
_FAILURE_MENU = {"fail_with_error": "Fail with Error",
                 "warn_and_keep_input": "Warn and Keep Input",
                 "output_nothing": "Output Nothing"}


SPECS = {
    # ════════════════════════════════════════════════════ Polygons / curves
    # ── PolyFill SOP: Fill Mode → filter conditions → output group. fill(): all three parameters are always read
    "PCG_PolyFill": {
        "order": ["mode", "max_sides", "planar_tolerance", "output_group"],
        "inputs": {
            "mode": {"label": "Fill Mode", "menu": _FILL_MENU},
            "max_sides": {"label": "Max Hole Sides",
                          "help": "0 = unlimited; > 0 only fills holes with at most this many edges"},
            "planar_tolerance": {"label": "Planar Tolerance",
                                 "help": "-1 = flatness ignored; >= 0 only fills holes that are flat enough"},
            "output_group": {"label": "Fill Polygons Group", "sep": True},
        },
    },

    # ── PolyPath SOP:Group → Tolerance → Junction / Max Angle → Match Attribute →
    #    Close Loops → attributes / cleanup. polypath(): max_angle is only read in straightest's pick
    "PCG_PolyPath": {
        "order": ["group", "tolerance", "junction", "max_angle", "match_attribute",
                  "close_loops", "prim_attribs", "remove_unused_points"],
        "inputs": {
            "tolerance": {"label": "Point Tolerance",
                          "help": "0 = only the same point counts; > 0 endpoints within this distance also connect (the point reached first is kept)"},
            "junction": {"label": "Junctions",
                         "menu": {"split": "Split at Junctions",
                                  "straightest": "Continue Straightest",
                                  "any": "Continue Any"}},
            "max_angle": {"label": "Max Turn Angle",
                          "hide": "{ junction != straightest }"},
            "match_attribute": {"label": "Match Attribute",
                                "help": "Empty = unrestricted; when set, only joins curves whose value of this prim attribute is equal"},
            "close_loops": {"label": "Close Loops"},
            "prim_attribs": {"label": "Primitive Attributes", "sep": True,
                             "menu": {"first": "Keep First", "drop": "Drop"}},
            "remove_unused_points": {"label": "Remove Unused Points"},
        },
    },

    # ── PolySpline SOP: Group / Spline Type / Alpha / Segment Divisions.
    #    poly_spline(): alpha only goes into catmull_rom's _cr_eval
    "PCG_PolySpline": {
        "order": ["group", "basis", "close", "division_method", "segment_length",
                  "output_divisions", "divisions", "first_cv_count", "last_cv_count",
                  "tension", "alpha"],
        "inputs": {
            # The first three are this plugin's originals (Houdini has no such names); the last four map to Houdini's Spline Type
            "basis": {"label": "Spline Type",
                      "menu": {"catmull_rom": "Catmull-Rom",
                               "bspline": "BSpline",
                               "interpolate": "Interpolating (C2)",
                               "bezier": "Bezier",
                               "degree2_bezier": "Degree 2 Bezier",
                               "cardinal": "Cardinal", "linear": "Linear"}},
            "close": {"label": "Close",
                      "menu": {"off": "Off", "on": "On",
                               "if_polygon_does": "If polygon does"}},
            "division_method": {"label": "Division Method",
                                "menu": {"standard": "Standard",
                                         "even_length": "Even Length Segments",
                                         "even_x": "Even X Segments",
                                         "even_y": "Even Y Segments",
                                         "even_z": "Even Z Segments"}},
            "segment_length": {"label": "Segment Length",
                               "disable": "{ division_method == standard }",
                               "help": "0 = computed from Output Divisions"},
            "output_divisions": {"label": "Output Divisions",
                                 "disable": "{ division_method == standard } "
                                            "{ segment_length > 0 }",
                                 "help": "Used when Segment Length is 0; both 0 = no resampling"},
            "divisions": {"label": "Sample Divisions"},
            "first_cv_count": {"label": "First CV Count"},
            "last_cv_count": {"label": "Last CV Count"},
            "tension": {"label": "CV Tension", "hide": "{ basis != cardinal }",
                        "help": "0 = uniform Catmull-Rom, 1 = zero tangents"},
            "alpha": {"label": "Alpha", "hide": "{ basis != catmull_rom }",
                      "help": "0 uniform / 0.5 centripetal / 1 chordal (this plugin's extension, not in Houdini)"},
        },
    },

    # ── Primitive SOP: Transform tab (Transform Order / Rotate Order / Translate / Rotate / Scale /
    #    Shear / Pivot), Attributes tab (Color / Alpha), Face/Hull tab (Close U / Vertex / Offset).
    #    primitive(): the transform set is always read; color is only read when color_mode == add, alpha likewise;
    #    reverse_prims(): u_offset / v_offset are only read for shift
    "PCG_Primitive": {
        "order": ["group", "xform_order", "rotate_order", "translate_x", "rotate_x", "scale_x",
                  "shear_xy", "pivot_x", "uniform_scale", "scale_attribute", "normal_offset",
                  "unshare_points",
                  "color_mode", "color_r", "alpha_mode", "alpha",
                  "close_u", "vertex_op", "u_offset", "v_offset"],
        "inputs": {
            "xform_order": {"label": "Transform Order",
                            "menu": {"srt": "Scale Rot Trans", "str": "Scale Trans Rot",
                                     "rst": "Rot Scale Trans", "rts": "Rot Trans Scale",
                                     "tsr": "Trans Scale Rot", "trs": "Trans Rot Scale"},
                            "help": "Applied left to right"},
            "rotate_order": {"label": "Rotate Order",
                             "menu": {"xyz": "Rx Ry Rz", "xzy": "Rx Rz Ry",
                                      "yxz": "Ry Rx Rz", "yzx": "Ry Rz Rx",
                                      "zxy": "Rz Rx Ry", "zyx": "Rz Ry Rx"}},
            "shear_xy": {"row": {"kind": "vector", "label": "Shear",
                                 "members": ["shear_xy", "shear_xz", "shear_yz"]},
                         "help": "XY / XZ / YZ: x += xy·y + xz·z, y += yz·z (applied right after scale)"},
            "pivot_x": {"help": "Relative to each prim's own center (0 = around the center)"},
            "uniform_scale": {"label": "Uniform Scale"},
            "scale_attribute": {"label": "Scale Attribute",
                                "help": "When given, also multiplies by this prim attribute (empty = not used)"},
            "normal_offset": {"label": "Normal Offset", "sep": True},
            "unshare_points": {"label": "Unshare Points", "sep": True},
            "color_mode": {"section": "Attributes", "label": "Color",
                           "menu": {"keep": "Keep Color", "add": "Add Color",
                                    "remove": "Remove Color"},
                           "help": "Add: writes the prim attribute Cd on the selected prims"},
            "color_r": {"row": {"kind": "color", "label": "Color",
                                "members": ["color_r", "color_g", "color_b"]},
                        "hide": "{ color_mode != add }"},
            "alpha_mode": {"label": "Alpha",
                           "menu": {"keep": "Keep Alpha", "add": "Add Alpha",
                                    "remove": "Remove Alpha"}},
            "alpha": {"label": "Alpha", "hide": "{ alpha_mode != add }"},
            "close_u": {"section": "Face/Hull", "label": "Close U",
                        "menu": {"no_change": "No Change", "open": "Open",
                                 "close": "Close"},
                        "help": "Polygons / polylines only; Houdini's two Unroll modes are not implemented"},
            "vertex_op": {"label": "Vertex",
                          "menu": {"none": "No Change", "reverse": "Reverse",
                                   "reverse_u": "Reverse U", "reverse_v": "Reverse V",
                                   "swap_uv": "Swap UV", "shift": "Shift"}},
            "u_offset": {"label": "U Offset", "hide": "{ vertex_op != shift }"},
            "v_offset": {"label": "V Offset", "hide": "{ vertex_op != shift }",
                         "help": "Only meaningful for NURBS / Bezier surfaces (meshes)"},
        },
    },

    # ── Primitive Split SOP:Group / Attribute / Tolerance
    "PCG_PrimitiveSplit": {
        "order": ["group", "attribute", "tolerance"],
        "inputs": {
            "attribute": {"label": "Split by Attribute"},
            "tolerance": {"label": "Tolerance",
                          "help": "Numeric attributes split only when they differ by more than this; strings split on inequality"},
        },
    },

    # ── Ray SOP: Group / Method / Direction ... / Max Distance, then the Transform section and the Output section.
    #    ray(): the minimum_distance branch reads none of the direction set (direction / N / reverse /
    #    both / farthest); direction is not read when use_point_normals is on
    "PCG_Ray": {
        "order": ["group", "method", "use_point_normals", "direction_x", "reverse",
                  "both_directions", "intersect_farthest", "max_distance",
                  "transform_points", "scale", "lift",
                  "hit_group", "distance_attribute", "hitprim_attribute",
                  "hituv_attribute", "hitpos_attribute", "normal_attribute",
                  "transfer_attributes"],
        "inputs": {
            "method": {"label": "Method",
                       "menu": {"minimum_distance": "Minimum Distance",
                                "project_rays": "Project Rays"}},
            "use_point_normals": {"label": "Use Point Normals as Direction",
                                  "hide": "{ method == minimum_distance }"},
            "direction_x": {"hide": "{ method == minimum_distance }",
                            "disable": "{ use_point_normals == 1 }"},
            "reverse": {"label": "Reverse Rays",
                        "hide": "{ method == minimum_distance }"},
            "both_directions": {"label": "Both Directions",
                                "hide": "{ method == minimum_distance }"},
            "intersect_farthest": {"label": "Intersect Farthest Surface",
                                   "hide": "{ method == minimum_distance }"},
            "max_distance": {"label": "Max Distance", "sep": True,
                             "help": "0 = unlimited; also limits the search range"},
            "scale": {"label": "Scale", "help": "1 = move all the way to the hit, 0.5 = halfway"},
            "lift": {"label": "Lift", "help": "Lifts a little further along the hit normal"},
            "hit_group": {"label": "Hit Group"},
            "distance_attribute": {"label": "Distance Attribute"},
            "hitprim_attribute": {"label": "Hit Primitive Attribute"},
            "hituv_attribute": {"label": "Hit UV Attribute"},
            "hitpos_attribute": {"label": "Hit Position Attribute"},
            "normal_attribute": {"label": "Hit Normal Attribute"},
            "transfer_attributes": {"label": "Transfer Attributes"},
        },
    },

    # ── Refine SOP: Group / First U / Second U, then the parameters of the three modes Refine / Unrefine / Subdivide.
    #    refine(): u_divisions is only read for subdivide, count only for refine (rep),
    #    tolerance only in unrefine's _dp_keep; First / Second U and spacing are read by all three
    "PCG_Refine": {
        "order": ["group", "mode", "use_first_u", "first_u", "use_second_u",
                  "second_u", "spacing", "u_divisions", "nurb_count_u", "tolerance"],
        "inputs": {
            "mode": {"label": "Operation",
                     "menu": {"refine": "Refine", "unrefine": "Unrefine",
                              "subdivide": "Subdivide"}},
            "first_u": {"label": "First U"},
            "second_u": {"label": "Second U"},
            "spacing": {"label": "Parameter Space",
                        "menu": {"uniform_domain": "Uniform Domain",
                                 "uniform_arc": "Uniform Arc Length"}},
            "u_divisions": {"label": "U Divisions", "sep": True,
                            "hide": "{ mode != subdivide }"},
            "nurb_count_u": {"label": "NURB Count U", "sep": True,
                             "hide": "{ mode != refine }",
                             "help": "How many coincident points to insert at each position (knot multiplicity of the spline)"},
            "tolerance": {"label": "Tolerance U", "sep": True,
                          "hide": "{ mode != unrefine }"},
        },
    },

    # ════════════════════════════════════════════════════ Remeshing
    # ── Remesh SOP:Target Size → Iterations → Hard Edges(Feature Angle / Boundary)
    #    → Smoothing → Attributes. remesh(): all always read
    "PCG_Remesh": {
        # remesh(): uv_attribute is only read when uv_seams == harden; detach only takes effect when group does not select
        # all primitives (empty group = all)
        "order": ["group", "hard_edges", "hard_points", "uv_seams", "uv_attribute",
                  "iterations", "relax", "detach",
                  "target_length", "feature_angle", "keep_boundary",
                  "smooth_features", "transfer_attributes", "out_hard_edges"],
        "inputs": {
            "group": {"label": "Group", "help": "Only remeshes these primitives; empty = all"},
            "hard_edges": {"label": "Hard Edges Group",
                           "help": "May be split, but always kept in the output"},
            "hard_points": {"label": "Hard Points Group",
                            "help": "These points are always kept in the output (not moved, not collapsed)"},
            "uv_seams": {"label": "UV Seams",
                         "menu": {"ignore": "Ignore", "harden": "Harden"},
                         "help": "Harden: UV island borders are treated as hard edges. Not implemented in Houdini's Resample"},
            "uv_attribute": {"label": "UV Attribute", "hide": "{ uv_seams == ignore }"},
            "iterations": {"label": "Iterations", "sep": True},
            "relax": {"label": "Smoothing"},
            "detach": {"label": "Detach From Nongroup Geometry",
                       "disable": '{ group == "" }',
                       "help": "Off: new points split on the border are also inserted into the neighbouring unselected primitives, so both sides share points"},
            "target_length": {"label": "Target Size", "sep": True,
                              "help": "Target edge length; 0 = use the mean edge length of the original mesh"},
            "feature_angle": {"label": "Hard Edge Angle", "sep": True,
                              "help": ">= 180 detects no hard edges (this plugin's extension, not in Houdini)"},
            "keep_boundary": {"label": "Keep Boundary",
                              "help": "This plugin's extension; Houdini always preserves boundaries"},
            "smooth_features": {"label": "Smooth Feature Lines",
                                "help": "This plugin's extension: when hard edges / boundaries are split, new points land on an interpolating curve, "
                                        "so curved ridges are no longer a few straight segments. Off = Houdini's behaviour"},
            "transfer_attributes": {"label": "Transfer Attributes", "sep": True},
            "out_hard_edges": {"label": "Hard Edges", "sep": True,
                               "help": "Name of the output edge group (including boundaries and seams); empty = not written"},
        },
    },

    # ── Remesh to Grid SOP: Group / Voxel Size / Project / Smooth.
    #    remesh_to_grid(): the Smooth loop sits inside `if project:`, so without projection neither Smooth item is read
    "PCG_RemeshToGrid": {
        "order": ["group", "voxel_size", "project", "smooth", "smooth_strength",
                  "transfer_attributes"],
        "inputs": {
            "voxel_size": {"label": "Voxel Size"},
            "project": {"label": "Project to Surface", "sep": True},
            "smooth": {"label": "Smooth Iterations",
                       "help": "Tangential relaxation; without Project it is not projected back and drifts slightly off the original surface"},
            "smooth_strength": {"label": "Smooth Strength",
                                "disable": "{ smooth == 0 }"},
            "transfer_attributes": {"label": "Transfer Attributes", "sep": True},
        },
    },

    # ── Shrinkwrap: Group / Voxel Size / Radius / Offset / Project / Smooth.
    #    shrinkwrap(): Smooth does not depend on Project (Project only decides whether to snap again after each round)
    "PCG_Shrinkwrap": {
        "order": ["group", "voxel_size", "radius", "offset", "project", "smooth",
                  "smooth_strength"],
        "inputs": {
            "voxel_size": {"label": "Voxel Size"},
            "radius": {"label": "Wrap Radius",
                       "help": "Gaps narrower than 2 × Radius are bridged; larger = closer to the convex hull"},
            "offset": {"label": "Offset", "help": "Pushes everything outward; must not exceed Radius"},
            "project": {"label": "Project to Surface", "sep": True},
            "smooth": {"label": "Smooth Iterations"},
            "smooth_strength": {"label": "Smooth Strength",
                                "disable": "{ smooth == 0 }"},
        },
    },

    # ── Smooth SOP(2.0):Group / Constrained Boundary / Constrained Points / Attributes /
    #    Weight / Method / Strength. Constrained Boundary is two toggles here:
    #    Pin Border Points (= Unshared Edges) + Pin Group Boundary (both on = Group Boundary)
    "PCG_Smooth": {
        "order": ["group", "pin_boundary", "pin_group_boundary", "constrained_points",
                  "attributes", "use_weight_attribute", "weight_attribute", "method",
                  "strength", "iterations", "recompute_normals"],
        "inputs": {
            "pin_boundary": {"label": "Pin Border Points (Unshared Edges)"},
            "pin_group_boundary": {"label": "Pin Group Boundary",
                                   "help": "Also pins the points on the selection's outer border; together with Pin Border Points = Houdini's Group Boundary"},
            "constrained_points": {"label": "Constrained Points"},
            "attributes": {"label": "Attributes"},
            "use_weight_attribute": {"section": None, "gate": None, "in_toggle": "weight_attribute"},
            "weight_attribute": {"label": "Weight Attribute", "section": None,
                                 "toggle": "use_weight_attribute"},
            "method": {"label": "Method", "sep": True,
                       "menu": {"uniform": "Uniform", "scale_dominant": "Scale-Dominant",
                                "curvature_dominant": "Curvature-Dominant"}},
            "strength": {"label": "Strength"},
            "iterations": {"label": "Iterations"},
            "recompute_normals": {"label": "Recompute Affected Normals", "sep": True},
        },
    },

    # ── Resample SOP: Group / Method → Max Segment Length or Segments / Even Last Segment
    #    → Create Only Points → Spline section → Attributes section.
    #    ops.resample(): length / even_last are only read in the by_length branch, segments only in the other
    "PCG_Resample": {
        "order": ["group", "maintain_prim_order", "resample_by_edge",
                  "measure_method", "measure", "treat_polygons_as", "method", "length",
                  "max_segments", "segments", "attrib_override", "even_last_segment",
                  "maintain_last_vertex", "randomize_first",
                  "create_only_points", "subdivide_later", "use_spline_opts", "spline_samples",
                  "use_out_attribs", "curveu_attrib", "distance_attrib",
                  "tangent_attrib", "curvenum_attrib"],
        "inputs": {
            "method": {"label": "Limit By",
                       "menu": {"max_segment_length": "Maximum Segment Length",
                                "segment_count": "Segment Count"},
                       "help": "Houdini has two toggles, Maximum Segment Length / Maximum Segments: "
                               "Maximum Segment Length = by length (Maximum Segments can additionally cap it); "
                               "Segment Count = only Maximum Segments checked, exactly that many segments"},
            "maintain_prim_order": {"label": "Maintain Primitive Order",
                                    "help": "When off, the resampled curves are placed after the unselected prims"},
            "resample_by_edge": {"label": "Resample by Polygon Edge",
                                 "disable": "{ treat_polygons_as != straight_edges }",
                                 "help": "Each edge is resampled separately, keeping all corners (straight-edged polygons only)"},
            "measure_method": {"label": "Method",
                               "menu": {"even_length": "Even Length Segments",
                                        "even_x": "Even X Segments",
                                        "even_y": "Even Y Segments",
                                        "even_z": "Even Z Segments"}},
            "measure": {"label": "Measure",
                        "menu": {"along_arc": "Along Arc", "along_chord": "Along Chord"},
                        "disable": "{ resample_by_edge == 1 }"},
            "attrib_override": {"label": "Allow Primitive Attributes to Override Parameters",
                                "help": "The prim attributes segment_length / num_segments override Length / Segments; "
                                        "≤ 0 turns the corresponding toggle off"},
            "maintain_last_vertex": {"label": "Maintain Last Vertex",
                                     "disable": "{ method != max_segment_length attrib_override == 0 } { even_last_segment == 1 }"},
            "randomize_first": {"label": "Randomize First Segment Length",
                                "disable": "{ method != max_segment_length attrib_override == 0 } { resample_by_edge == 1 }"},
            "subdivide_later": {"label": "Output as Polygon Curves to be Subdivided Later",
                                "disable": "{ create_only_points == 1 }"},
            "treat_polygons_as": {"label": "Treat Polygons As",
                                  "menu": {"straight_edges": "Straight Edges",
                                           "subdivision_curves": "Subdivision Curves",
                                           "interpolating_curves": "Interpolating Curves"},
                                  "help": "Subdivision: points act as control points, the curve is pulled inward; "
                                          "Interpolating: the curve passes through every point. The densification uses Samples per Span"},
            "length": {"label": "Length",
                       "hide": "{ method != max_segment_length }"},
            "max_segments": {"toggle": "use_max_segments", "label": "Maximum Segments",
                             "hide": "{ method != max_segment_length }",
                             "help": "When the segment count computed from the length exceeds this, uses exactly this many segments instead"},
            "segments": {"label": "Segments",
                         "hide": "{ method != segment_count }"},
            "even_last_segment": {"label": "Even Last Segment",
                                  "hide": "{ method != max_segment_length }"},
            "create_only_points": {"label": "Create Only Points", "sep": True},
            "use_spline_opts": {"label": "Spline Evaluation"},
            "spline_samples": {"label": "Samples per Span",
                               "help": "Density at which NURBS / Bezier are first evaluated on the curve itself; also used when Treat Polygons As densifies"},
            "use_out_attribs": {"label": "Output Attributes"},
            "curveu_attrib": {"label": "Curve U Attribute"},
            "distance_attrib": {"label": "Distance Attribute"},
            "tangent_attrib": {"label": "Tangent Attribute"},
            "curvenum_attrib": {"label": "Curve Number Attribute"},
        },
    },

    # ── Reverse SOP: Group / Vertex (operation) / U Offset / V Offset.
    #    reverse_prims(): offset is only read in the shift branch; v_offset only matters for surface meshes
    "PCG_Reverse": {
        "order": ["group", "mode", "use_shift", "u_offset", "v_offset"],
        "inputs": {
            "mode": {"label": "Vertex",
                     "menu": {"reverse": "Reverse", "none": "No Change",
                              "reverse_u": "Reverse U", "reverse_v": "Reverse V",
                              "swap_uv": "Swap UV", "shift": "Shift"}},
            # Houdini has no section toggle: since pcg90 it is on by default and hidden, only revealed when left off in an old workflow
            "use_shift": {"section": None, "gate": None, "label": "Enable Shift",
                          "hide": "{ mode != shift } { use_shift == 1 }",
                          "help": "Houdini has no such toggle; off = Offset uses the default 0 (old workflows)"},
            "u_offset": {"section": None, "label": "U Offset", "hide": "{ mode != shift }",
                         "disable": "{ use_shift == 0 }"},
            "v_offset": {"section": None, "label": "V Offset", "hide": "{ mode != shift }",
                         "disable": "{ use_shift == 0 }",
                         "help": "Only meaningful for NURBS / Bezier surfaces (meshes)"},
        },
    },

    # ── Sort SOP: two dropdowns Point Sort / Primitive Sort + their own Reverse, then parameter sections
    #    depending on the sort method. _sort_order(): axis only read for along_vector / circular, center only for
    #    circular, target only for proximity, attrib / component only for attribute,
    #    expr only for expression, seed only for random, offset only for shift;
    #    reverse_* skips the whole section when the corresponding sort is none
    "PCG_Sort": {
        # Houdini's layout: Point Sort is followed by its own Seed / Offset / Vector / Point / Attribute,
        # Primitive Sort by another copy (two separate copies since pcg90). Houdini has none of the four section toggles;
        # since pcg90 they are on by default and hidden; only revealed when left off in an old workflow (off = that section uses defaults)
        "order": ["point_sort", "rand_seed", "offset", "axis_x", "use_center",
                  "center_x", "target_x", "point_attrib", "component", "point_expr",
                  "reverse_point_sort",
                  "prim_sort", "prim_rand_seed", "prim_offset", "prim_axis_x",
                  "prim_use_center", "prim_center_x", "prim_target_x", "prim_attrib",
                  "prim_component", "prim_expr", "reverse_prim_sort",
                  "points_by_vertex_order",
                  "use_axis", "use_target", "use_key", "use_rs"],
        "inputs": {
            "point_sort": {"label": "Point Sort", "menu": _SORT_MENU},
            **_sort_side("point_sort", "", "Point"),
            "reverse_point_sort": {"section": None, "label": "Reverse Point Sort",
                                   "disable": "{ point_sort == none }"},
            "prim_sort": {"label": "Primitive Sort", "menu": _SORT_MENU, "sep": True},
            **_sort_side("prim_sort", "prim_", "Primitive"),
            "reverse_prim_sort": {"section": None, "label": "Reverse Primitive Sort",
                                  "disable": "{ prim_sort == none }"},
            "points_by_vertex_order": {"section": None,
                                       "label": "Sort Points by Vertex Order",
                                       "sep": True,
                                       "help": "First reorders points by the order their vertices appear in primitives, then does Point Sort"},
            # Only revealed when off and a sort method on either side uses this section
            **{g: {"section": None, "gate": None, "label": lab,
                   "hide": "{ " + g + " == 1 } " + _neither(toks),
                   "help": "Houdini has no such toggle; off = this section's parameters use defaults (old workflows)"}
               for g, lab, toks in (
                   ("use_axis", "Enable Vector / Center", ("along_vector", "circular")),
                   ("use_target", "Enable Proximity Point", ("proximity",)),
                   ("use_key", "Enable Attribute / Expression", ("attribute", "expression")),
                   ("use_rs", "Enable Seed / Offset", ("random", "shift")))},
        },
    },

    # ── Split SOP:Group / Group Type
    "PCG_Split": {
        "order": ["group", "cls"],
        "inputs": {
            "cls": {"label": "Group Type",
                    "menu": {"prim": "Primitives", "point": "Points"}},
        },
    },

    # ── Switch SOP: Select Input (expressions allowed). wrap is out-of-range handling added by this plugin
    "PCG_Switch": {
        "order": ["select_input", "wrap"],
        "inputs": {
            "select_input": {"label": "Select Input"},
            "wrap": {"label": "Wrap Out-of-Range Index",
                     "help": "Off: clamp to the ends; on: wrap around (negative numbers count from the back)"},
        },
    },

    # ── Switch-If SOP: Merge Condition on top, Tests (one expression per line) below
    "PCG_SwitchIf": {
        "order": ["merge", "invert", "tests"],
        "inputs": {
            "merge": {"label": "Merge Condition",
                      "menu": {"all": "All Tests Pass", "any": "Any Test Passes"}},
            "invert": {"label": "Invert Result"},
            "tests": {"label": "Tests", "sep": True},
        },
    },

    # ── Transform by Attribute SOP: Group / Attribute / Class / Invert, then the attributes transformed along with it
    "PCG_TransformByAttrib": {
        "order": ["group", "attribute", "attribute_class", "invert", "normals",
                  "vectors", "orient"],
        "inputs": {
            "attribute": {"label": "Transform Attribute"},
            "attribute_class": {"label": "Attribute Class",
                                "menu": {"detail": "Detail", "point": "Point",
                                         "prim": "Primitive"}},
            "invert": {"label": "Invert Transform"},
            "normals": {"label": "Normals to Transform", "sep": True},
            "vectors": {"label": "Vectors to Transform"},
            "orient": {"label": "Transform orient"},
        },
    },

    # ── Triangulate 2D SOP: Group / Plane (+ plane parameters) → Constraints → pruning →
    #    Output groups → Advanced. _basis(): fit_plane does not read origin / normal (reads distance),
    #    the three axis modes read origin but not normal; region skips the whole section when there are no constraint edges (m.cons empty)
    "PCG_Triangulate2D": {
        "order": ["group", "plane", "plane_origin_x", "plane_normal_x",
                  "plane_distance",
                  "constrain", "constrain_group", "region",
                  "max_circumradius", "max_edge_length",
                  "keep_input_geometry", "border_group", "constrained_group",
                  "fuse_tolerance", "hull_tolerance", "on_failure"],
        "inputs": {
            "group": {"label": "Points to Triangulate"},
            "plane": {"label": "Plane", "menu": _PLANE_MENU},
            "plane_origin_x": {"section": None, "label": "Plane Origin",
                               "hide": "{ plane == fit_plane }"},
            "plane_normal_x": {"section": None,
                               "hide": "{ plane != specify_plane }"},
            "plane_distance": {"section": None, "label": "Plane Offset",
                               "help": "Additional offset along the plane normal"},
            "constrain": {"label": "Constrain", "sep": True,
                          "menu": {"none": "None",
                                   "input_polygons": "Input Polygons",
                                   "edge_group": "Edge Group"}},
            "constrain_group": {"section": None, "label": "Constrained Edges",
                                "hide": "{ constrain != edge_group }"},
            "region": {"label": "Region",
                       "menu": {"keep_all": "Keep All",
                                "remove_outside": "Remove Outside",
                                "remove_inside": "Remove Inside",
                                "remove_outside_and_inside": "Remove Outside and Inside"},
                       "hide": "{ constrain == none }"},
            "max_circumradius": {"label": "Max Circumradius", "sep": True,
                                 "help": "0 = no pruning; deletes triangles with a larger circumradius (concave hull)"},
            "max_edge_length": {"label": "Max Edge Length",
                                "help": "0 = no pruning; deletes triangles with a longer longest edge"},
            "keep_input_geometry": {"label": "Keep Input Geometry",
                                    "section": "Output"},
            "border_group": {"section": "Output", "label": "Boundary Edge Group"},
            "constrained_group": {"section": "Output",
                                  "label": "Constrained Edge Group"},
            "fuse_tolerance": {"section": "Advanced", "label": "Fuse Tolerance"},
            "hull_tolerance": {"section": "Advanced", "label": "Hull Tolerance"},
            "on_failure": {"section": "Advanced", "label": "On Failure",
                           "menu": _FAILURE_MENU},
        },
    },

    # ════════════════════════════════════════════════════ Volumes
    # ── Volume Blur SOP: Group / Reduction (filter = this plugin's original Gaussian / Box) /
    #    Use Voxel Radius / Radius / Voxel Radius / Passes / Override Border / Blending.
    #    blur(): mode is only read in the filter mode; use_voxel_radius / voxel_radius only in non-filter modes;
    #    border_value only for constant; the two blend amounts only with enable_blending on
    "PCG_VolumeBlur": {
        "order": ["volumes", "reduction", "mode", "use_voxel_radius", "radius",
                  "voxel_radius_x", "iterations", "override_border", "border_value",
                  "enable_blending", "original_blend", "blurred_blend"],
        "inputs": {
            "volumes": {"label": "Group", "help": "Volume names or indices; empty = all"},
            "reduction": {"label": "Reduction",
                          "menu": {"filter": "Filter (Gaussian / Box)",
                                   "maximum": "Maximum", "minimum": "Minimum",
                                   "max_abs": "Maximum of Absolute",
                                   "min_abs": "Minimum of Absolute",
                                   "average": "Average", "median": "Median",
                                   "sum": "Sum", "sum_abs": "Sum of Absolute",
                                   "sum_squares": "Sum of Squares",
                                   "rms": "Root Mean Square"},
                          "help": "Filter holds this plugin's two original modes; the rest are Houdini's Reduction"},
            "mode": {"label": "Filter",
                     "menu": {"gaussian": "Gaussian", "box": "Box (Mean Value)"},
                     "hide": "{ reduction != filter }"},
            "use_voxel_radius": {"label": "Use Voxel Radius",
                                 "hide": "{ reduction == filter }"},
            "radius": {"label": "Blur Radius",
                       "disable": "{ reduction != filter use_voxel_radius == 1 }",
                       "help": "World units; for Gaussian σ = Radius / 2, other modes round to voxel size"},
            "voxel_radius_x": {"row": {"kind": "vector",
                                       "members": ["voxel_radius_x", "voxel_radius_y",
                                                   "voxel_radius_z"],
                                       "label": "Voxel Radius"},
                               "hide": "{ reduction == filter }",
                               "disable": "{ use_voxel_radius == 0 }"},
            "iterations": {"label": "Passes"},
            "override_border": {"label": "Override Border", "sep": True,
                                "menu": {"use_volume": "Use Volume", "constant": "Constant",
                                         "repeat": "Repeat", "streak": "Streak"}},
            "border_value": {"label": "Border Value",
                             "hide": "{ override_border != constant }"},
            "enable_blending": {"label": "Enable Blending", "sep": True},
            "original_blend": {"label": "Original Blend Amount",
                               "disable": "{ enable_blending == 0 }"},
            "blurred_blend": {"label": "Blurred Blend Amount",
                              "disable": "{ enable_blending == 0 }"},
        },
    },

    # ── Volume Mix SOP (+ the SDF operations of VDB Combine): volumes on both sides / Mix Method / per-mode parameters /
    #    Pre·Post adjustment / Clamp. mix(): factor only goes into blend, k only into the three smooth_*, range only into
    #    clamp, value only into user; Pre / Post / Clamp Min·Max are used in every mode
    "PCG_VolumeMix": {
        "order": ["volume_a", "volume_b", "operation", "range_min", "factor", "value", "k",
                  "dest_pre_add", "dest_pre_mul", "src_pre_add", "src_pre_mul",
                  "post_add", "post_mul", "use_clamp_min", "clamp_min",
                  "use_clamp_max", "clamp_max"],
        "inputs": {
            "volume_a": {"label": "Source Group",
                         "help": "Volume names or indices in the first input; every matched volume is mixed"},
            "volume_b": {"label": "Mix Group",
                         "help": "Same-named volumes in B pair up; if B has only one, everything pairs with it; otherwise paired one-to-one in order"},
            "operation": {"label": "Mix Method", "sep": True,
                          "menu": {"add": "Add", "subtract": "Subtract",
                                   "multiply": "Multiply", "maximum": "Maximum",
                                   "minimum": "Minimum", "blend": "Blend",
                                   "copy_b": "Copy",
                                   "union": "SDF Union",
                                   "intersect": "SDF Intersection",
                                   "difference": "SDF Difference (A − B)",
                                   "smooth_union": "Smooth SDF Union",
                                   "smooth_intersect": "Smooth SDF Intersection",
                                   "smooth_difference": "Smooth SDF Difference",
                                   "diff": "Diff", "divide": "Divide", "invert": "Invert",
                                   "clamp": "Clamp", "user": "User"}},
            "range_min": {"row": {"kind": "vector", "members": ["range_min", "range_max"],
                                  "label": "Range"},
                          "hide": "{ operation != clamp }"},
            "factor": {"label": "Blend", "hide": "{ operation != blend }"},
            "value": {"label": "Value", "hide": "{ operation != user }",
                      "help": "Wrangle syntax: @value = A′, @value2 = B′, @P, @ix @iy @iz, "
                              "@bb / @bb2 (0–1 position within the A / B bounding box)"},
            "k": {"label": "Smooth Width",
                  "hide": _not_any("operation", ("smooth_union", "smooth_intersect",
                                                 "smooth_difference")),
                  "help": "Transition width in world units"},
            "dest_pre_add": {"label": "Dest Pre-Add", "sep": True},
            "dest_pre_mul": {"label": "Dest Pre-Mul"},
            "src_pre_add": {"label": "Source Pre-Add"},
            "src_pre_mul": {"label": "Source Pre-Mul"},
            "post_add": {"label": "Post-Add"},
            "post_mul": {"label": "Post-Mul"},
            "use_clamp_min": {"section": None, "gate": None, "in_toggle": "clamp_min",
                              "sep": True},
            "clamp_min": {"label": "Clamp Minimum", "toggle": "use_clamp_min"},
            "use_clamp_max": {"section": None, "gate": None, "in_toggle": "clamp_max"},
            "clamp_max": {"label": "Clamp Maximum", "toggle": "use_clamp_max"},
        },
    },

    # ── Volume Resample SOP: Group / Mode → Resolution / Voxel Size / Scale per mode →
    #    Interpolation. resample(): each of the three modes reads its own
    "PCG_VolumeResample": {
        "order": ["volumes", "mode", "res_x", "voxel_size", "scale", "interpolation"],
        "inputs": {
            "volumes": {"label": "Group", "help": "Volume names or indices; empty = all"},
            "mode": {"label": "Resample By",
                     "menu": {"resolution": "Resolution",
                              "voxel_size": "Voxel Size",
                              "scale": "Scale Voxel Count"}},
            "res_x": {"hide": "{ mode != resolution }"},
            "voxel_size": {"label": "Voxel Size", "hide": "{ mode != voxel_size }"},
            "scale": {"label": "Scale", "hide": "{ mode != scale }"},
            "interpolation": {"label": "Interpolation", "sep": True,
                              "menu": {"trilinear": "Trilinear",
                                       "nearest": "Nearest"}},
        },
    },

    # ── VDB Reshape SDF SOP: Group / Operation / Offset. reshape_sdf(): redistance does not read d
    "PCG_VolumeReshapeSDF": {
        "order": ["volumes", "operation", "distance"],
        "inputs": {
            "volumes": {"label": "Group", "help": "Volume names or indices; empty = all"},
            "operation": {"label": "Operation",
                          "menu": {"dilate": "Dilate", "erode": "Erode",
                                   "open": "Open", "close": "Close",
                                   "redistance": "Redistance (Renormalize)"}},
            "distance": {"label": "Offset", "hide": "{ operation == redistance }"},
        },
    },

    # ── IsoOffset SOP: Output / Mode / Name / sampling / bounding box / Offset. iso_offset():
    #    uniform_divs is only read in the four "per axis" modes, divs_* only in non_uniform, div_size only in by_size;
    #    min / max only with override_bounds on and no second input wired; name is not read by iso_surface
    "PCG_IsoOffset": {
        "order": ["output", "mode", "name", "uniform_sampling", "uniform_divs", "divs_x",
                  "div_size", "override_bounds", "min_x", "max_x", "pad_bounds",
                  "offset", "invert_sign"],
        "inputs": {
            "output": {"label": "Output",
                       "menu": {"iso_surface": "Iso Surface", "fog": "Fog Volume",
                                "sdf": "SDF Volume"}},
            "mode": {"label": "Mode",
                     "menu": {"ray_intersect": "Ray Intersect", "minimum": "Minimum",
                              "point_cloud": "Point Cloud", "implicit_box": "Implicit Box",
                              "implicit_sphere": "Implicit Sphere"}},
            "name": {"label": "Name", "hide": "{ output == iso_surface }"},
            "uniform_sampling": {"label": "Uniform Sampling", "sep": True,
                                 "menu": {"max_axis": "Max Axis+Divs", "x_axis": "X Axis+Divs",
                                          "y_axis": "Y Axis+Divs", "z_axis": "Z Axis+Divs",
                                          "by_size": "By Size",
                                          "non_uniform": "Non Uniform"}},
            "uniform_divs": {"label": "Uniform Sampling Divs",
                             "hide": "{ uniform_sampling == by_size } "
                                     "{ uniform_sampling == non_uniform }",
                             "help": "Number of grid points (Houdini counts voxels)"},
            "divs_x": {"row": {"kind": "vector", "members": ["divs_x", "divs_y", "divs_z"],
                               "label": "Sampling Divs"},
                       "hide": "{ uniform_sampling != non_uniform }"},
            "div_size": {"label": "Div Size", "hide": "{ uniform_sampling != by_size }"},
            "override_bounds": {"label": "Override Bounds", "sep": True,
                                "help": "Uses the second input's bounding box when wired"},
            "min_x": {"row": {"kind": "vector", "members": ["min_x", "min_y", "min_z"],
                              "label": "Minimum Bound"},
                      "disable": "{ override_bounds == 0 }"},
            "max_x": {"row": {"kind": "vector", "members": ["max_x", "max_y", "max_z"],
                              "label": "Maximum Bound"},
                      "disable": "{ override_bounds == 0 }"},
            "pad_bounds": {"label": "Pad Bounds"},
            "offset": {"label": "Offset", "sep": True, "help": "Positive grows outward"},
            "invert_sign": {"label": "Invert Sign"},
        },
    },

    # ── VDB Smooth SDF SOP:Group / Alpha Mask / Operation / Filter Voxel Radius /
    #    Iterations / Invert / Min-Max Cutoff. smooth_sdf(): radius is only read for mean / median;
    #    the three mask parameters are only read with use_mask on
    "PCG_VolumeSmoothSDF": {
        "order": ["volumes", "use_mask", "operation", "filter_voxel_radius", "iterations",
                  "invert_mask", "min_mask_cutoff", "max_mask_cutoff"],
        "inputs": {
            "volumes": {"label": "Group", "help": "Volume names or indices; empty = all"},
            "use_mask": {"label": "Alpha Mask",
                         "help": "Uses the first volume of the second input as a 0–1 blend weight"},
            "operation": {"label": "Operation", "sep": True,
                          "menu": {"mean_value": "Mean Value",
                                   "median_value": "Median Value",
                                   "mean_curvature_flow": "Mean Curvature Flow",
                                   "laplacian_flow": "Laplacian Flow"}},
            "filter_voxel_radius": {"label": "Filter Voxel Radius",
                                    "hide": "{ operation == mean_curvature_flow } "
                                            "{ operation == laplacian_flow }"},
            "iterations": {"label": "Iterations"},
            "invert_mask": {"label": "Invert Alpha Mask", "sep": True,
                            "disable": "{ use_mask == 0 }"},
            "min_mask_cutoff": {"label": "Min Mask Cutoff", "disable": "{ use_mask == 0 }"},
            "max_mask_cutoff": {"label": "Max Mask Cutoff", "disable": "{ use_mask == 0 }"},
        },
    },

    # ════════════════════════════════════════════════════ Voronoi
    # ── Cluster of Voronoi Fracture: Mode → Cluster Count / Seed → Piece Attribute →
    #    Merge (Fuse / Name) → output attributes. cluster(): count / seed are only read in the count mode;
    #    with merge_pieces off it writes the cluster attribute and returns, fuse / name not read
    "PCG_VoronoiCluster": {
        "order": ["mode", "cluster_count", "rand_seed", "piece_attribute",
                  "merge_pieces", "fuse_tolerance", "cluster_attribute",
                  "name_attribute", "name_prefix"],
        "inputs": {
            "mode": {"label": "Cluster Seeds",
                     "menu": {"count": "Random Piece Centroids",
                              "points": "Second Input Points"}},
            "cluster_count": {"label": "Cluster Count", "hide": "{ mode != count }"},
            "rand_seed": {"label": "Seed", "hide": "{ mode != count }"},
            "piece_attribute": {"label": "Piece Attribute", "sep": True},
            "merge_pieces": {"label": "Merge Pieces",
                             "help": "Off: only writes the cluster attribute, no fusing and no interior walls removed"},
            "fuse_tolerance": {"label": "Fuse Tolerance",
                               "disable": "{ merge_pieces == 0 }"},
            "cluster_attribute": {"label": "Cluster Attribute", "sep": True},
            "name_attribute": {"label": "Name Attribute",
                               "disable": "{ merge_pieces == 0 }"},
            "name_prefix": {"label": "Name Prefix",
                            "disable": "{ merge_pieces == 0 }"},
        },
    },

    # ── Voronoi Fracture SOP 3.0: Group / Pieces (Interior Surface, Name, Normals) /
    #    Output Attributes / Cut. fracture(): Namespace is only read for append; Interior Cusp only
    #    when interior normals are on; Exterior Cusp not read in the none mode; the two Copy toggles only when an attribute name is given
    "PCG_VoronoiFracture": {
        "order": ["group", "cap", "cap_mode", "interior_group", "cap_tolerance",
                  "name_attribute", "name_mode", "fracture_namespace", "name_prefix",
                  "compute_interior_normals", "interior_cusp_angle", "exterior_normals",
                  "exterior_cusp_angle",
                  "piece_attribute", "cell_point_attribute", "clip_piece_attribute",
                  "exterior_group", "merge_groups", "copy_cell_attributes", "copy_to_points",
                  "copy_to_prims",
                  "cut_plane_offset", "connectivity_partition", "max_pieces"],
        "inputs": {
            "group": {"label": "Group"},
            "cap": {"label": "Create Interior Surface"},
            "cap_mode": {"label": "Cap Type", "menu": _FILL_MENU},
            "interior_group": {"label": "Interior Group"},
            "cap_tolerance": {"label": "Cap Tolerance",
                              "help": "Relative to the bounding box scale; only fills loops lying on the cut plane"},
            "name_attribute": {"label": "Name Attribute"},
            "name_mode": {"label": "Name Mode", "section": "Naming",
                          "menu": {"overwrite": "Overwrite", "append": "Append"}},
            "fracture_namespace": {"label": "Fracture Namespace", "section": "Naming",
                                   "hide": "{ name_mode != append }",
                                   "help": "Append: original name + '-' + Namespace + prefix + number"},
            "name_prefix": {"label": "Piece Prefix"},
            "compute_interior_normals": {"label": "Compute Interior Normals",
                                         "section": "Normals"},
            "interior_cusp_angle": {"label": "Interior Cusp Angle", "section": "Normals",
                                    "disable": "{ compute_interior_normals == 0 }"},
            "exterior_normals": {"label": "Exterior Normals", "section": "Normals",
                                 "menu": {"preserve": "Preserve Existing Normals",
                                          "recompute": "Recompute Normals",
                                          "none": "Do Not Compute Normals"}},
            "exterior_cusp_angle": {"label": "Exterior Cusp Angle", "section": "Normals",
                                    "disable": "{ exterior_normals == none }"},
            "piece_attribute": {"label": "Primitive Piece", "section": "Output Attributes"},
            "cell_point_attribute": {"label": "Primitive Cell Point",
                                     "section": "Output Attributes",
                                     "help": "Empty = not written; the value is the seed's point number in the second input"},
            "clip_piece_attribute": {"label": "Primitive Clip Piece",
                                     "section": "Output Attributes",
                                     "help": "Empty = not written; the patch faces record the number of the piece on the other side, exterior faces −1"},
            "exterior_group": {"label": "Exterior Group", "section": "Output Attributes",
                               "help": "Empty = not created"},
            "merge_groups": {"label": "Merge with Existing Groups",
                             "section": "Output Attributes"},
            "copy_cell_attributes": {"label": "Copy Cell Point Attributes",
                                     "section": "Output Attributes", "sep": True},
            "copy_to_points": {"label": "To Piece Points", "section": "Output Attributes",
                               "disable": '{ copy_cell_attributes == "" }'},
            "copy_to_prims": {"label": "To Piece Primitives", "section": "Output Attributes",
                              "disable": '{ copy_cell_attributes == "" }'},
            "cut_plane_offset": {"label": "Cut Plane Offset", "section": "Cut",
                                 "help": "Leaves a gap this wide between two pieces (each side gives up half)"},
            "connectivity_partition": {"label": "Connectivity Partition", "section": "Cut",
                                       "menu": {"none": "None",
                                                "overwrite": "Overwrite Piece Numbering",
                                                "maintain": "Maintain Piece Numbering"}},
            "max_pieces": {"label": "Max Pieces", "sep": True},
        },
    },

    # ── Boolean Fracture SOP: Group / Pieces (Name, Normals) / Output Attributes /
    #    Output Groups / Boolean Settings. boolean_fracture(): Namespace is only read for append;
    #    Interior Cusp only when interior normals are on; Exterior Cusp not read in the none mode;
    #    Pieces / Surface Inside are only created when the cutting geometry is treated as Solid
    "PCG_BooleanFracture": {
        "order": ["group", "name_mode", "fracture_namespace", "piece_prefix",
                  "compute_interior_normals", "interior_cusp_angle", "exterior_normals",
                  "exterior_cusp_angle",
                  "attribute_prefix", "piece_attribute", "copy_cutter_attributes",
                  "interior_group", "exterior_group", "merge_groups", "interior_seams",
                  "exterior_seams", "pieces_inside", "surface_inside",
                  "treat_cutter", "detriangulate"],
        "inputs": {
            "group": {"label": "Group"},
            "name_mode": {"label": "Name Attribute", "section": "Pieces",
                          "menu": {"overwrite": "Overwrite", "append": "Append"}},
            "fracture_namespace": {"label": "Fracture Namespace", "section": "Pieces",
                                   "hide": "{ name_mode != append }"},
            "piece_prefix": {"label": "Piece Prefix", "section": "Pieces"},
            "compute_interior_normals": {"label": "Compute Interior Normals",
                                         "section": "Pieces"},
            "interior_cusp_angle": {"label": "Interior Cusp Angle", "section": "Pieces",
                                    "disable": "{ compute_interior_normals == 0 }"},
            "exterior_normals": {"label": "Exterior Normals", "section": "Pieces",
                                 "menu": {"preserve": "Preserve Existing Normals",
                                          "recompute": "Recompute Normals",
                                          "none": "Do Not Compute Normals"}},
            "exterior_cusp_angle": {"label": "Exterior Cusp Angle", "section": "Pieces",
                                    "disable": "{ exterior_normals == none }"},
            "attribute_prefix": {"label": "Attribute Name Prefix",
                                 "section": "Output Attributes"},
            "piece_attribute": {"label": "Primitive Piece", "section": "Output Attributes"},
            "copy_cutter_attributes": {"label": "Copy Cutting Surface Attributes",
                                       "section": "Output Attributes",
                                       "help": "Prim attributes of the cutting geometry (wildcards allowed) copied onto the interior faces"},
            "interior_group": {"label": "Interior Group", "section": "Output Groups"},
            "exterior_group": {"label": "Exterior Group", "section": "Output Groups"},
            "merge_groups": {"label": "Merge with Existing Groups", "section": "Output Groups"},
            "interior_seams": {"label": "Interior Seams", "section": "Output Groups",
                               "help": "Empty = not created"},
            "exterior_seams": {"label": "Exterior Seams", "section": "Output Groups",
                               "help": "Empty = not created"},
            "pieces_inside": {"label": "Pieces Inside Cutting Geometry",
                              "section": "Output Groups", "hide": "{ treat_cutter != solid }"},
            "surface_inside": {"label": "Surface Inside Cutting Geometry",
                               "section": "Output Groups", "hide": "{ treat_cutter != solid }"},
            "treat_cutter": {"label": "Treat Cutting Geometry As", "section": "Boolean Settings",
                             "menu": {"surface": "Surface", "solid": "Solid"}},
            "detriangulate": {"label": "Detriangulate", "section": "Boolean Settings",
                              "menu": {"all": "All Polygons",
                                       "unchanged": "Only Unchanged Polygons",
                                       "none": "No Polygons"}},
        },
    },

    # ── Intersection Analysis SOP: Group A / Group B / output attributes (empty name = not written).
    #    group_b is only read when the second input is wired
    "PCG_IntersectionAnalysis": {
        "order": ["group_a", "group_b", "input_attribute", "prim_attribute", "uvw_attribute"],
        "inputs": {
            "group_a": {"label": "Group A"},
            "group_b": {"label": "Group B", "help": "Only used when the second input is wired"},
            "input_attribute": {"label": "Input Number", "section": "Output Attributes",
                                "help": "int ×2; empty = not written"},
            "prim_attribute": {"label": "Primitive Number", "section": "Output Attributes",
                               "help": "int ×2; empty = not written"},
            "uvw_attribute": {"label": "Primitive UVW", "section": "Output Attributes",
                              "help": "float ×6 (uvw of the two prims one after the other); empty = not written"},
        },
    },

    # ── Voronoi Split SOP: Group / Cut (Offset, Weight Attribute + Method) / output.
    #    voronoi_split(): method and weight_attribute are only read with use_weight on
    "PCG_VoronoiSplit": {
        "order": ["group", "split_points", "offset", "use_weight", "weight_attribute",
                  "method", "piece_attribute", "cut_group"],
        "inputs": {
            "split_points": {"label": "Split Points",
                             "help": "Off: both sides of the cut share points"},
            "offset": {"label": "Offset", "section": "Cut",
                       "help": "Moves the cut plane this far along the line between the two points (lower point number → higher)"},
            "use_weight": {"section": "Cut", "gate": None, "in_toggle": "weight_attribute"},
            "weight_attribute": {"label": "Weight Attribute", "section": "Cut",
                                 "toggle": "use_weight"},
            "method": {"label": "Method", "section": "Cut",
                       "menu": {"power": "Power Distance", "ratio": "Ratio"},
                       "disable": "{ use_weight == 0 }"},
            "piece_attribute": {"label": "Piece Attribute", "sep": True},
            "cut_group": {"label": "Cut Edge Group", "help": "Empty = not written"},
        },
    },

    # ════════════════════════════════════════════════════ Output / caching
    # ── File Cache SOP: Mode (the three Load from Disk modes) / path / Version / Frame.
    #    run_cache(): compress is only read when writing to disk, not in the read mode
    "PCG_FileCache": {
        "order": ["mode", "file", "version", "frame", "compress", "reload"],
        "inputs": {
            "mode": {"label": "Mode",
                     "menu": {"auto": "Automatic (Read if Exists)",
                              "write": "Always Write", "read": "Load from Disk"}},
            "file": {"label": "Geometry File",
                     "help": "Relative to ComfyUI's output directory; $F / $F4 frame number, $V version"},
            "version": {"label": "Version"},
            "frame": {"label": "Frame"},
            "compress": {"label": "Compress", "sep": True,
                         "hide": "{ mode == read }"},
            "reload": {"label": "Reload",
                       "help": "Change this number to force one re-read / re-write"},
        },
    },

    # ── File Merge SOP: Geometry File / Merge Range / Merge Variable / Delete Points / Missing File.
    #    file_merge(): all five parameters are read, nothing is hidden per mode
    "PCG_FileMerge": {
        "order": ["file", "reload", "merge_start", "merge_variable", "delete_other",
                  "missing_file"],
        "inputs": {
            "file": {"label": "Geometry File",
                     "help": "Must contain $SLICE (or the name given in Merge Variable); .npz = geometry cache"},
            "reload": {"label": "Reload Geometry", "help": "Change this number to force a re-read"},
            "merge_start": {"row": {"kind": "vector",
                                    "members": ["merge_start", "merge_end", "merge_inc"],
                                    "label": "Merge Range"}},
            "merge_variable": {"label": "Merge Variable"},
            "delete_other": {"label": "Delete Points from Other Files",
                             "help": "Deletes points whose slice point attribute ≠ the current number"},
            "missing_file": {"label": "Missing File",
                             "menu": {"error": "Report Error", "no_geometry": "No Geometry"}},
        },
    },

    # ── Geo Metrics (this plugin's own node): metrics to compute → detail output → which one the value output picks / JSON indent
    "PCG_GeoMetrics": {
        "order": ["compute_quality", "compute_uv", "uv_attrib", "uv_res",
                  "write_detail", "prefix", "pick", "indent"],
        "inputs": {
            "compute_quality": {"label": "Compute Triangle Quality"},
            "compute_uv": {"label": "Compute UV Metrics"},
            "uv_attrib": {"label": "UV Attribute", "disable": "{ compute_uv == 0 }"},
            "uv_res": {"label": "UV Raster Resolution",
                       "disable": "{ compute_uv == 0 }"},
            "write_detail": {"label": "Write Detail Attributes", "sep": True},
            "prefix": {"label": "Attribute Prefix",
                       "disable": "{ write_detail == 0 }"},
            "pick": {"label": "Value Output", "sep": True,
                     "help": "Which metric goes to the value / int outputs"},
            "indent": {"label": "JSON Indent"},
        },
    },

    # ── Preview Image (our own node): resolution / view / shading. color_attrib is only read in the color mode
    "PCG_PreviewImage": {
        "order": ["width", "height", "elevation", "azimuth", "look", "shading",
                  "color_attrib", "supersampling", "textures", "material_attrib", "uv_attrib",
                  "sun_elevation", "sun_azimuth", "haze", "clouds", "cloud_seed", "sky_samples",
                  "ground_plane", "ground_color", "exposure", "compute"],
        "inputs": {
            "width": {"row": {"kind": "vector", "members": ["width", "height"],
                              "label": "Resolution"}},
            "elevation": {"label": "Elevation", "sep": True},
            "azimuth": {"label": "Azimuth"},
            "shading": {"label": "Shading", "hide": "{ look != basic }",
                        "menu": {"normal": "Normal", "lambert": "Lambert (Gray)",
                                 "color": "Color (Cd)"}},
            "color_attrib": {"label": "Color Attribute",
                             "hide": "{ shading != color look == basic }"},
            # pcg110 studio look, pcg123 outdoor look
            "look": {"label": "Look", "sep": True,
                     "menu": {"basic": "Basic", "studio": "Studio (shadows, AO, ground, textures)",
                              "outdoor": "Outdoor (perspective, sky, sun, haze)"}},
            "supersampling": {"label": "Supersampling", "hide": "{ look == basic }"},
            "textures": {"label": "Textures", "hide": "{ look == basic }",
                         "help": "basecolor / normal / orm (or ao, roughness, metallic) = path, relative to the output folder; "
                                 "{material} = the face's material; @layer reads textures_cop. orm / roughness / "
                                 "metallic switch to PBR shading"},
            "material_attrib": {"label": "Material Attribute", "hide": "{ look == basic }"},
            "uv_attrib": {"label": "UV Attribute", "hide": "{ look == basic }"},
            "sun_elevation": {"label": "Sun Elevation", "section": "Outdoor", "hide": "{ look != outdoor }"},
            "sun_azimuth": {"label": "Sun Azimuth", "section": "Outdoor", "hide": "{ look != outdoor }",
                            "help": "World space: 0 = the sun in +Z, 90 = in +X"},
            "haze": {"label": "Haze", "section": "Outdoor", "hide": "{ look != outdoor }",
                     "help": "Aerial perspective in metres: at 1, light falls to 1/e over 12 km, glowing toward the sun (0 = none)"},
            "ground_plane": {"label": "Ground Plane", "section": "Outdoor", "hide": "{ look != outdoor }",
                             "help": "A ground to the horizon at the bottom of the geometry"},
            "ground_color": {"label": "Ground Color", "section": "Outdoor",
                             "hide": "{ look != outdoor } { ground_plane == 0 }"},
            "exposure": {"label": "Exposure", "section": "Outdoor", "hide": "{ look != outdoor }"},
            "clouds": {"label": "Clouds", "section": "Outdoor", "hide": "{ look != outdoor }",
                       "help": "Cumulus cover 0..1; the clouds also throw soft shadows on the ground"},
            "cloud_seed": {"label": "Cloud Seed", "section": "Outdoor",
                           "hide": "{ look != outdoor } { clouds == 0 }"},
            "sky_samples": {"label": "Sky Samples", "section": "Outdoor", "hide": "{ look != outdoor }",
                            "help": "Directions the sky light is shadowed from (one depth map each); 0 = plain "
                                    "hemisphere fill, fast"},
            "compute": {"label": "Compute", "section": "Outdoor", "hide": "{ look != outdoor }",
                        "menu": {"auto": "Auto (CUDA if available)", "cpu": "CPU (numpy)", "cuda": "CUDA"},
                        "help": "Where the shadow maps and the sky light are computed"},
        },
    },

    # ════════════════════════════════════════════════════ Parameters / time (our own nodes)
    # ── Channel: Frame / Keyframes / default interpolation / out of range / Scale + Offset on the output
    "PCG_Channel": {
        "order": ["frame", "keys", "interp", "extrapolate", "scale", "offset"],
        "inputs": {
            "frame": {"label": "Frame"},
            "keys": {"label": "Keyframes",
                     "help": "frame:value[:interp][@slope], space-separated; the interpolation governs the span to its right"},
            "interp": {"label": "Default Interpolation", "menu": _INTERP_MENU},
            "extrapolate": {"label": "Extrapolation", "menu": _EXTRAP_MENU},
            "scale": {"label": "Scale", "sep": True},
            "offset": {"label": "Offset"},
        },
    },

    "PCG_Channel3": {
        "order": ["frame", "keys_x", "keys_y", "keys_z", "interp", "extrapolate",
                  "scale", "offset"],
        "inputs": {
            "frame": {"label": "Frame"},
            "keys_x": {"label": "Keyframes X", "help": "Empty = 0:0 (always 0, still × Scale + Offset)"},
            "keys_y": {"label": "Keyframes Y", "help": "Empty = 0:0 (always 0, still × Scale + Offset)"},
            "keys_z": {"label": "Keyframes Z", "help": "Empty = 0:0 (always 0, still × Scale + Offset)"},
            "interp": {"label": "Default Interpolation", "menu": _INTERP_MENU,
                       "sep": True},
            "extrapolate": {"label": "Extrapolation", "menu": _EXTRAP_MENU},
            "scale": {"label": "Scale", "sep": True},
            "offset": {"label": "Offset"},
        },
    },

    "PCG_Expr": {
        "order": ["expr"],
        "inputs": {
            "expr": {"label": "Expression",
                     "help": "a ~ f are the wired inputs; unwired ones count as 0"},
        },
    },

    "PCG_Expr3": {
        "order": ["expr_x", "expr_y", "expr_z"],
        "inputs": {
            "expr_x": {"label": "Expression X"},
            "expr_y": {"label": "Expression Y"},
            "expr_z": {"label": "Expression Z"},
        },
    },

    # ── Frame: current frame / frame range / FPS
    "PCG_Frame": {
        "order": ["frame", "start", "end", "fps"],
        "inputs": {
            "frame": {"label": "Frame"},
            "start": {"sep": True,
                      "row": {"kind": "vector", "members": ["start", "end"],
                              "label": "Start / End"}},
            "fps": {"label": "FPS"},
        },
    },

    # ── Param Pick: Key → ☑ Fallback [value] → JSON. default_value is only read with fallback on
    "PCG_ParamPick": {
        "order": ["name", "fallback", "default_value", "json_text"],
        "inputs": {
            "name": {"label": "Key", "help": "Supports a.b for nested keys, pos.y for vector components"},
            "default_value": {"toggle": "fallback", "label": "Fallback Value",
                              "help": "When off, a missing key raises an error"},
            "json_text": {"label": "JSON", "sep": True},
        },
    },

    # ── Params from JSON: with Enabled off, run() returns immediately without parsing the JSON
    "PCG_ParamsFromJSON": {
        "order": ["enabled", "json_text"],
        "inputs": {
            "enabled": {"label": "Enable"},
            "json_text": {"label": "JSON", "disable": "{ enabled == 0 }"},
        },
    },

    "PCG_Value": {
        "order": ["value"],
        "inputs": {"value": {"label": "Value"}},
    },

    # ════════════════════════════════════════════════════ Camera
    # ── Camera OBJ: View tab (projection / resolution / FOV / Ortho Width / clipping planes) + Transform tab
    #    (placement mode / Target / orbit parameters / Eye / Up). render.camera():
    #    fov only used for perspective; ortho_size only for orthographic, and the frame mode recomputes it from the bounding sphere;
    #    elev / azim read in orbit and frame; distance only in orbit (frame computes its own, look_at uses eye);
    #    margin only read in frame; eye only in look_at; target is overridden by the center in the frame mode when geo is wired
    #    (still read without geo, so not hidden); up is read by all three modes
    "PCG_Camera": {
        "order": ["projection", "resolution_x", "fov", "ortho_size", "near", "far",
                  "mode", "target_x", "elev", "azim", "distance", "margin",
                  "eye_x", "up_x"],
        "inputs": {
            "projection": {"folder": "View", "label": "Projection",
                           "menu": _PROJ_MENU},
            "resolution_x": {"folder": "View"},
            "fov": {"folder": "View", "label": "Field of View",
                    "hide": "{ projection != perspective }"},
            "ortho_size": {"folder": "View", "label": "Ortho Width",
                           "hide": "{ projection != orthographic } { mode == frame }"},
            "near": {"folder": "View", "section": None, "label": "Near Clipping",
                     "sep": True},
            "far": {"folder": "View", "section": None, "label": "Far Clipping",
                    "help": "0 = no far clipping"},
            "mode": {"folder": "Transform", "label": "Placement",
                     "menu": {"frame": "Frame Geometry", "orbit": "Orbit",
                              "look_at": "Look At"},
                     "help": "Frame Geometry needs geo wired; the distance is set automatically from the bounding sphere"},
            "target_x": {"folder": "Transform", "section": None,
                         "help": "In the Frame Geometry mode with geo wired, replaced by the bounding sphere center"},
            "elev": {"folder": "Transform", "label": "Elevation",
                     "hide": "{ mode == look_at }"},
            "azim": {"folder": "Transform", "label": "Azimuth",
                     "hide": "{ mode == look_at }"},
            "distance": {"folder": "Transform", "label": "Distance",
                         "hide": "{ mode != orbit }"},
            "margin": {"folder": "Transform", "label": "Frame Margin",
                       "hide": "{ mode != frame }"},
            "eye_x": {"folder": "Transform", "section": None,
                      "hide": "{ mode != look_at }"},
            "up_x": {"folder": "Transform", "section": None, "sep": True},
        },
    },

    # ── Camera from Points (our own node, the point version of Camera Path): sampling → orientation → lens.
    #    cameras_from_points(): look_ahead is only read for path (auto may resolve to path);
    #    the target parameter only in the target mode when the points have no target attribute; up is not read in the orient mode;
    #    focus_distance is not read in the target mode; fov / ortho_size are used per projection, but the points'
    #    projection attribute (Use Point Attributes) can change the projection per camera, so both are kept then
    "PCG_CameraFromPoints": {
        "order": ["group", "frames", "loop", "orientation", "look_ahead",
                  "target_x", "up_x", "focus_distance",
                  "projection", "resolution_x", "fov", "ortho_size", "near", "far",
                  "use_point_attributes"],
        "inputs": {
            "group": {"label": "Point Group"},
            "frames": {"label": "Frames",
                       "help": "0 = one camera per point; > 0 = this many cameras evenly by arc length along the path"},
            "loop": {"label": "Closed Path",
                     "help": "Joins end to start; the last frame does not repeat the first"},
            "orientation": {"label": "Orientation", "sep": True,
                            "menu": {"auto": "Automatic",
                                     "orient": "orient Attribute",
                                     "normal": "N + up",
                                     "target": "Look at Target",
                                     "path": "Along Path"}},
            "look_ahead": {"label": "Look Ahead",
                           "hide": _not_any("orientation", ("path", "auto"))},
            "target_x": {"hide": _not_any("orientation", ("target", "auto")),
                         "help": "Uses the attribute when the points have a target attribute"},
            "up_x": {"hide": "{ orientation == orient }"},
            "focus_distance": {"label": "Focus Distance",
                               "hide": "{ orientation == target }"},
            "projection": {"label": "Projection", "menu": _PROJ_MENU, "sep": True},
            "fov": {"label": "Field of View",
                    "hide": "{ projection != perspective use_point_attributes == 0 }"},
            "ortho_size": {"label": "Ortho Width",
                           "hide": "{ projection != orthographic use_point_attributes == 0 }"},
            "near": {"section": None, "label": "Near Clipping"},
            "far": {"section": None, "label": "Far Clipping",
                    "help": "0 = no far clipping"},
            "use_point_attributes": {"label": "Use Point Attributes", "sep": True,
                                     "help": "fov / ortho_size / near / far / resx / "
                                             "resy / projection / distance on the points override the parameters"},
        },
    },
}
