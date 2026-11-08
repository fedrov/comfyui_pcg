"""
Parameter panel specs for group g11 (format: see the docstring at the top of panel_specs.py).

Geometry sequences (Select Best / Time Blend / Trail) + a batch of modeling / repair SOPs, matched against SideFX's official panels.
hide / disable conditions follow whether the node code (nodes.py / nodes_sop2.py + geo/) actually reads the parameter.
"""

_EDGES_HELP = "Edge group, empty = all edges"

SPECS = {
    # ══════════════════════════════════════════════════ Geometry sequences
    # ── Select Best: this plugin's own node. Expression / direction / count on top, metric toggles, UV metric parameters, report
    "PCG_SelectBest": {
        "order": ["score", "mode", "top_k", "compute_quality", "compute_uv",
                  "uv_attrib", "uv_res", "report_metrics"],
        "inputs": {
            "score": {"label": "Score Expression",
                      "help": "Score of each geometry; can use all metrics, i / n, detail() and other functions that read geometry"},
            "mode": {"label": "Select", "menu": {"max": "Highest Score",
                                                 "min": "Lowest Score"}},
            "top_k": {"label": "Keep Top", "help": "How many top entries the top_k output keeps (ties go to the lower index)"},
            "compute_quality": {"label": "Compute Quality Metrics", "sep": True,
                                "help": "Triangle quality tri_quality_min / tri_quality_mean"},
            "compute_uv": {"label": "Compute UV Metrics",
                           "help": "uv_area / uv_coverage / uv_overlap (texels counted on a raster)"},
            # metrics(): with uv=False uv_metrics does not run at all, so these two are not read
            "uv_attrib": {"label": "UV Attribute", "hide": "{ compute_uv == 0 }"},
            "uv_res": {"label": "UV Raster Resolution", "hide": "{ compute_uv == 0 }",
                       "help": "Precision of coverage / overlap = 1 / resolution"},
            "report_metrics": {"label": "Report Metrics", "sep": True,
                               "help": "Which metrics to list for each entry in the report besides rank / score (space-separated)"},
        },
    },

    # ── Time Blend SOP: Frame / interpolation / loop
    "PCG_TimeBlend": {
        "order": ["frame", "interp", "loop"],
        "inputs": {
            "frame": {"label": "Frame", "help": "Frame number in the sequence (from 0), may be fractional"},
            "interp": {"label": "Interpolation",
                       "menu": {"hold": "Integer Frames (Hold)",
                                "blend": "Blend Subframes"},
                       "help": "Blend requires the same topology on all frames; integer / string attributes take the nearer frame"},
            "loop": {"label": "Cycle Source", "help": "Frame numbers wrap around when out of range instead of clamping to the ends"},
        },
    },

    # ── Trail SOP:Result Type / Trail Length / Trail Increment / Velocity Attribute
    "PCG_Trail": {
        "order": ["index", "mode", "length", "increment", "loop", "velocity_attrib"],
        "inputs": {
            "index": {"label": "Current Frame", "help": "Which frame of the sequence is the current frame"},
            "mode": {"label": "Result Type", "sep": True,
                     "menu": {"preserve": "Preserve Original",
                              "connect": "Connect as Polygons",
                              "connect_mesh": "Connect as Mesh",
                              "velocity": "Compute Velocity"}},
            "length": {"label": "Trail Length",
                       "help": "How many frames to look back; under Compute Velocity, 0 = only the current frame (velocity 0). "
                               "Connect as Polygons: one polyline per point trajectory; "
                               "Connect as Mesh: each edge sweeps a quad between adjacent frames"},
            "increment": {"label": "Trail Increment",
                          "help": "Take one frame every this many; under Compute Velocity also the frame distance for differencing"},
            "loop": {"label": "Cycle Source", "help": "Frame numbers wrap around when out of range instead of clamping to frame 0"},
            # trail(): velocity_attrib is only written in the velocity mode
            "velocity_attrib": {"label": "Velocity Attribute", "sep": True,
                                "hide": "{ mode != velocity }"},
        },
    },

    # ══════════════════════════════════════════════════ Modeling / repair
    # ── Bound SOP: Group / Bounding Type, then Padding / Divisions / type-specific parameters
    "PCG_Bound": {
        "order": ["group", "mode", "uniform_padding", "padding_x", "padding_y",
                  "padding_z", "divisions_x", "divisions_y", "divisions_z",
                  "sphere_cols", "sphere_rows", "max_normals", "tolerance"],
        "inputs": {
            "mode": {"label": "Bounding Type",
                     "menu": {"box": "Bounding Box", "sphere": "Bounding Sphere",
                              "oriented": "Oriented Bounding Box"}},
            "uniform_padding": {"label": "Uniform Padding", "sep": True,
                                "help": "Pushes out in all three directions (per side); added to Padding below"},
            # Houdini's Bound panel is flat, so these one-row collapsible sections are flattened
            "padding_x": {"section": None, "row": {"label": "Padding"},
                          "help": "Amount pushed out per side; Bounding Sphere takes the largest of the three components (negative values do not shrink)"},
            "padding_y": {"section": None},
            "padding_z": {"section": None},
            # bound(): the sphere mode does not read divisions; only box / oriented read it when building the box
            "divisions_x": {"section": None, "row": {"label": "Divisions"}, "sep": True,
                            "hide": "{ mode == sphere }"},
            "divisions_y": {"section": None},
            "divisions_z": {"section": None},
            "sphere_cols": {"section": None, "label": "Columns", "sep": True,
                            "hide": "{ mode != sphere }"},
            "sphere_rows": {"section": None, "label": "Rows", "hide": "{ mode != sphere }"},
            "max_normals": {"section": None, "label": "Max Hull Normals", "sep": True,
                            "hide": "{ mode != oriented }",
                            "help": "When the convex hull has more faces than this, only the normals of the largest faces are enumerated (approximately optimal)"},
            "tolerance": {"section": None, "label": "Hull Tolerance",
                          "hide": "{ mode != oriented }"},
        },
    },

    # ── Carve SOP: Group / ☑ First U / ☑ Second U / Arc Length, then Keep Inside / Outside / Extract
    "PCG_Carve": {
        "order": ["group", "use_first_u", "first_u", "use_second_u", "second_u",
                  "relative_arc_length", "mode", "use_keep", "keep_inside",
                  "keep_outside"],
        "inputs": {
            # Houdini has a single row "☑ First U [0.25]", not a collapsible section
            "use_first_u": {"section": None, "gate": None, "in_toggle": "first_u"},
            "first_u": {"section": None, "toggle": "use_first_u", "label": "First U",
                        "sep": True},
            "use_second_u": {"section": None, "gate": None, "in_toggle": "second_u"},
            "second_u": {"section": None, "toggle": "use_second_u", "label": "Second U",
                         "help": "An end that is not on is the curve endpoint: only Second U on = keep 0 ~ Second U"},
            "relative_arc_length": {"label": "Use Arc Length",
                                    "help": "U is computed as a fraction of arc length, not by vertex / knot parameter"},
            "mode": {"label": "Operation", "sep": True,
                     "menu": {"cut": "Cut", "extract": "Extract"},
                     "help": "Extract takes one point at each enabled U (iso-parametric point of the curve)"},
            # carve(): the extract mode continues directly, keep_inside / keep_outside are not read
            "use_keep": {"label": "Keep", "hide": "{ mode == extract }"},
            "keep_inside": {"label": "Keep Inside", "hide": "{ mode == extract }"},
            "keep_outside": {"label": "Keep Outside", "hide": "{ mode == extract }"},
        },
    },

    # ── Circle from Edges SOP: Group / Radius method / radius / Even Spacing / Rotate
    "PCG_CircleFromEdges": {
        "order": ["edges", "radius_mode", "radius", "even_spacing", "rotate"],
        "inputs": {
            "edges": {"label": "Group", "help": "Each closed loop in the edge group is laid out as a perfect circle; open chains are skipped"},
            "radius_mode": {"label": "Radius Type",
                            "menu": {"average": "Average", "min": "Minimum",
                                     "max": "Maximum", "custom": "Custom"}},
            # circle_from_edges(): radius is only used in the custom mode
            "radius": {"label": "Radius", "hide": "{ radius_mode != custom }"},
            "even_spacing": {"label": "Even Spacing", "sep": True},
            "rotate": {"label": "Rotate", "help": "Rotates the whole thing around the circle normal (degrees)"},
        },
    },

    # ── Circle Spline SOP:Group / Divisions
    "PCG_CircleSpline": {
        "order": ["group", "spline_type", "override_with_attrib", "helix_type", "adjust_arclength",
                  "arclength_samples", "divisions", "use_curveu", "curveu_name", "use_tangent",
                  "tangent_name"],
        "inputs": {
            "spline_type": {"label": "Spline Type", "menu": {"circle": "Circle", "helix": "Helix"},
                            "help": "Houdini's docs give no definition for Hybrid / Ellipse; not implemented"},
            "override_with_attrib": {"label": "Override Spline Type with Attribute",
                                     "help": "The string point attribute splinetype (circle / helix) decides the span centered on that point"},
            # helix_type is only read on the helix points; with a splinetype attribute it can also be used under Circle, so not hidden
            "helix_type": {"label": "Helix Type",
                           "menu": {"directional": "Directional", "balanced": "Balanced", "blended": "Blended"},
                           "disable": "{ spline_type != helix override_with_attrib == 0 }"},
            "adjust_arclength": {"label": "Adjust by Pseudo-Arclength", "sep": True},
            "arclength_samples": {"label": "Arclength Samples", "disable": "{ adjust_arclength == 0 }"},
            "divisions": {"label": "Segment Divisions", "help": "Samples per span (between two adjacent points)"},
            "use_curveu": {"section": None, "gate": None, "in_toggle": "curveu_name", "sep": True},
            "curveu_name": {"section": None, "toggle": "use_curveu", "label": "Output Curveu"},
            "use_tangent": {"section": None, "gate": None, "in_toggle": "tangent_name"},
            "tangent_name": {"section": None, "toggle": "use_tangent", "label": "Output Tangent"},
        },
    },

    # ── Clean SOP: in processing order Fuse → Degenerate → Duplicate → Manifold → Orient → small pieces → Unused
    "PCG_Clean": {
        "order": ["fuse_distance", "remove_degenerate", "remove_duplicates",
                  "make_manifold", "orient", "min_piece_prims", "remove_unused"],
        "inputs": {
            "fuse_distance": {"label": "Fuse Distance", "help": "0 = do not merge points"},
            "remove_degenerate": {"label": "Remove Degenerate Primitives", "sep": True},
            "remove_duplicates": {"label": "Delete Overlap Polygons",
                                  "help": "Only one of the primitives with the same point set is kept (regardless of start point and winding)"},
            "make_manifold": {"label": "Make Manifold",
                              "help": "Edges shared by more than two primitives keep the two largest by area; bowtie points are split"},
            "orient": {"label": "Orient Polygons"},
            "min_piece_prims": {"label": "Delete Small Pieces", "sep": True,
                                "help": "Connected pieces with fewer primitives than this are deleted whole; 0 = none deleted"},
            "remove_unused": {"label": "Remove Unused Points"},
        },
    },

    # ── PolyDoctor SOP: Max Passes; four tabs Primitives / Edges & Points / Topology / Attributes
    "PCG_PolyDoctor": {
        "order": ["max_passes", "ill_formed", "five_plus", "non_convex", "overlapping",
                  "pair_overlaps", "local_area", "local_area_threshold", "non_uniform",
                  "uniformity_threshold", "global_edges", "global_edge_threshold",
                  "local_edges", "local_edge_threshold", "disconnected", "nonmanifold",
                  "self_intersecting",
                  "valid_poly", "repaired_poly", "valid_pt", "repaired_pt", "create_groups"],
        "inputs": {
            "max_passes": {"label": "Max Passes"},
            "ill_formed": {"folder": "Primitives", "label": "Ill-Formed", "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "five_plus": {"folder": "Primitives", "label": "5+ Edges", "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "non_convex": {"folder": "Primitives", "label": "Non-Convex", "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "overlapping": {"folder": "Primitives", "label": "Overlapping", "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            # polydoctor.overlapping: pair is only read when checking for overlaps
            "pair_overlaps": {"folder": "Primitives", "label": "Pair Overlaps",
                              "disable": "{ overlapping == ignore }"},
            "local_area": {"folder": "Primitives", "label": "Locally Small Areas",
                           "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "local_area_threshold": {"folder": "Primitives", "label": "Local Area Threshold",
                                     "disable": "{ local_area == ignore }"},
            "non_uniform": {"folder": "Primitives", "label": "Non-Uniform Polygons",
                            "menu": {"ignore": "Ignore", "mark": "Mark"}, "help": "The docs do not say how to repair it, so it can only be marked"},
            "uniformity_threshold": {"folder": "Primitives", "label": "Uniformity Threshold",
                                     "disable": "{ non_uniform == ignore }",
                                     "help": "Isoperimetric quotient 4πA / perimeter² (circle = 1)"},
            "global_edges": {"folder": "Edges & Points", "label": "Globally Small Edges",
                             "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "global_edge_threshold": {"folder": "Edges & Points", "label": "Global Edge Threshold",
                                      "disable": "{ global_edges == ignore }",
                                      "help": "× bounding box diagonal"},
            "local_edges": {"folder": "Edges & Points", "label": "Locally Small Edges",
                            "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "local_edge_threshold": {"folder": "Edges & Points", "label": "Local Edge Threshold",
                                     "disable": "{ local_edges == ignore }"},
            "disconnected": {"folder": "Edges & Points", "label": "Disconnected Points",
                             "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "nonmanifold": {"folder": "Topology", "label": "Non-Manifold Points", "menu": {"ignore": "Ignore", "mark": "Mark", "repair": "Repair"}},
            "self_intersecting": {"folder": "Topology", "label": "Self-Intersecting Polygons",
                                  "menu": {"ignore": "Ignore", "mark": "Mark"},
                                  "help": "Polygons passing through other polygons of the mesh (mark only)"},
            "valid_poly": {"folder": "Attributes", "label": "Valid Polygons"},
            "repaired_poly": {"folder": "Attributes", "label": "Repaired Polygons"},
            "valid_pt": {"folder": "Attributes", "label": "Valid Points"},
            "repaired_pt": {"folder": "Attributes", "label": "Modified Points"},
            "create_groups": {"folder": "Attributes", "label": "Create a group for each attribute"},
        },
    },

    # ── Clip SOP:Group / Clip Attribute / Keep / Orient Plane with → Origin + Direction
    #    or Translate + Rotate / Distance / Snapping Tolerance / Fill / Split, Create Groups last
    "PCG_Clip": {
        "order": ["group", "clip_attribute", "keep", "orient",
                  "dir_x", "dir_y", "dir_z",
                  "translate_x", "translate_y", "translate_z",
                  "rotate_x", "rotate_y", "rotate_z", "distance", "snap_tolerance",
                  "fill", "split_connectivity",
                  "use_origin", "origin_x", "origin_y", "origin_z",
                  "use_out_groups", "above_group", "below_group", "seam_group",
                  "clipped_group", "fill_group"],
        "inputs": {
            "group": {"label": "Group"},
            "clip_attribute": {"label": "Clip Attribute",
                               "help": "Cuts by the first three components of this point attribute; default P"},
            "keep": {"label": "Keep",
                     "menu": {"below": "Primitives Below the Plane",
                              "above": "Primitives Above the Plane",
                              "both": "All Primitives"}},
            "orient": {"label": "Orient Plane with", "sep": True,
                       "menu": {"direction": "Direction", "transform": "Transform"}},
            # clip(): the transform mode does not read direction / origin, the direction mode does not read translate / rotate
            "dir_x": {"row": {"label": "Direction"}, "hide": "{ orient == transform }"},
            "dir_y": {"hide": "{ orient == transform }"},
            "dir_z": {"hide": "{ orient == transform }"},
            "translate_x": {"row": {"label": "Translate"}, "hide": "{ orient == direction }"},
            "translate_y": {"hide": "{ orient == direction }"},
            "translate_z": {"hide": "{ orient == direction }"},
            "rotate_x": {"row": {"label": "Rotate"}, "hide": "{ orient == direction }",
                         "help": "Rotates (0,1,0) into the plane normal; X first, then Y, then Z"},
            "rotate_y": {"hide": "{ orient == direction }"},
            "rotate_z": {"hide": "{ orient == direction }"},
            "distance": {"label": "Distance", "help": "Distance the plane is moved along its normal"},
            "snap_tolerance": {"label": "Snapping Tolerance",
                               "help": "Points within this distance of the plane are snapped onto it before cutting; 0 = no snapping"},
            "fill": {"label": "Fill Polygons along Clipping Plane", "sep": True},
            # clip(): only read when keep == both
            "split_connectivity": {"label": "Split Connectivity",
                                   "hide": "{ keep != both }"},
            "use_origin": {"label": "Origin", "hide": "{ orient == transform }"},
            "origin_x": {"row": {"label": "Origin"}, "hide": "{ orient == transform }"},
            "origin_y": {"hide": "{ orient == transform }"},
            "origin_z": {"hide": "{ orient == transform }"},
            "use_out_groups": {"label": "Create Groups"},
            "above_group": {"label": "Above Primitives"},
            "below_group": {"label": "Below Primitives"},
            "seam_group": {"label": "Clipped Edges"},
            "clipped_group": {"label": "Clipped Primitives", "section": "Output Groups",
                              "help": "Primitives cut by this plane and kept; empty = not created"},
            "fill_group": {"label": "Filled Polygons", "section": "Output Groups",
                           "disable": "{ fill == 0 }", "help": "The filled primitives; empty = not created"},
        },
    },

    # ── Convex Decomposition SOP: output method / concavity / piece count, Search section, output attributes last
    "PCG_ConvexDecompose": {
        "order": ["mode", "max_concavity", "max_pieces", "max_hull_points", "resolution", "split_axes",
                  "min_fraction", "cap_mode", "tolerance", "piece_attribute",
                  "name_attribute", "name_prefix"],
        "inputs": {
            "mode": {"label": "Output",
                     "menu": {"hull": "Convex Hulls", "exact": "Exact Pieces"},
                     "help": "Convex Hulls: each piece is replaced by its convex hull; Exact: keeps the cut solids (volume preserving)"},
            "max_concavity": {"label": "Max Concavity",
                              "help": "Residual concavity allowed per piece (1 − volume / hull volume)"},
            "max_pieces": {"label": "Max Pieces", "help": "Global piece budget"},
            "max_hull_points": {"label": "Max Hull Points", "disable": "{ mode == exact }",
                                "help": "Vertex budget per hull (0 = no limit); the reduced hull is a subset of the "
                                        "full one's vertices, so it never grows"},
            "resolution": {"label": "Split Candidates"},
            "split_axes": {"label": "Split Axes",
                           "menu": {"oriented": "Oriented (OBB)", "world": "World Axes"}},
            "min_fraction": {"label": "Min Piece Fraction"},
            # The hull mode takes the convex hull of each piece at the end, so how cuts are capped does not affect the result (still read by the code, only greyed out)
            "cap_mode": {"label": "Cap Type",
                         "menu": {"ngon": "N-gon", "fan": "Fan", "triangles": "Triangles"},
                         "disable": "{ mode == hull }"},
            "tolerance": {"label": "Tolerance"},
            "piece_attribute": {"label": "Piece Attribute", "sep": True},
            "name_attribute": {"label": "Name Attribute"},
            "name_prefix": {"label": "Name Prefix"},
        },
    },

    # ── Convex Hull SOP:Group / Merge Coplanar Faces / Tolerance
    "PCG_ConvexHull": {
        "order": ["group", "merge_coplanar_faces", "tolerance"],
        "inputs": {
            "merge_coplanar_faces": {"label": "Merge Coplanar Faces",
                                     "help": "Merges coplanar triangles into polygons; turn off for pure triangles when making collision proxies"},
            "tolerance": {"label": "Tolerance"},
        },
    },

    # ── Crease SOP: Group / Crease Weight / mode / attribute name
    "PCG_Crease": {
        "order": ["edges", "mode", "weight", "attribute"],
        "inputs": {
            "edges": {"label": "Group", "help": _EDGES_HELP},
            "mode": {"label": "Operation",
                     "menu": {"set": "Set", "add": "Add", "multiply": "Multiply",
                              "max": "Maximum"}},
            "weight": {"label": "Crease Weight"},
            "attribute": {"label": "Crease Attribute", "sep": True,
                          "help": "Vertex attribute; Subdivide reads it for semi-sharp creases"},
        },
    },

    # ── Curve Intersect: Group / projection plane / Tolerance / Self / Output / point groups
    "PCG_CurveIntersect": {
        "order": ["group", "cutter_group", "plane", "tolerance", "find_all", "self_intersect", "output",
                  "point_group", "left_pieces", "right_pieces", "affect", "keep_original"],
        "inputs": {
            "group": {"label": "Face Group"},
            # The old points / split modes do not read it (all curves are intersected pairwise)
            "cutter_group": {"label": "Cutter Group", "hide": "{ output == points } { output == split }"},
            "find_all": {"label": "Find All Intersections", "hide": "{ output == points } { output == split }",
                         "help": "Off: each pair of curves only takes the single closest spot (not required to be within Tolerance)"},
            "left_pieces": {"label": "Left-face Pieces", "hide": "{ output != cut }",
                            "menu": {"keep_all": "Keep All", "keep_odd": "Keep Odd-numbered Ones",
                                     "keep_even": "Keep Even-numbered Ones", "keep_none": "Keep None"}},
            "right_pieces": {"label": "Right-face Pieces", "hide": "{ output != cut }",
                             "menu": {"keep_all": "Keep All", "keep_odd": "Keep Odd-numbered Ones",
                                      "keep_even": "Keep Even-numbered Ones", "keep_none": "Keep None"}},
            "affect": {"label": "Affect", "hide": "{ output != extract }",
                       "menu": {"left": "Left Input", "right": "Right Input", "both": "Both Inputs"}},
            "keep_original": {"label": "Keep Original", "hide": "{ output != extract }"},
            "plane": {"label": "Intersect In",
                      "menu": {"3d": "3D", "xz": "XZ Plane (Top)", "xy": "XY Plane",
                               "yz": "YZ Plane"}},
            "tolerance": {"label": "Tolerance"},
            "self_intersect": {"label": "Self Intersections", "hide": "{ output == cut } { output == extract }"},
            "output": {"label": "Output", "sep": True,
                       "menu": {"points": "Intersection Points",
                                "split": "Split Curves",
                                "cut": "Cut (Houdini Method)",
                                "extract": "Extract (Houdini Method)"},
                       "help": "Cut / Extract use Houdini semantics: Face Group (left) × Cutter Group (right, second input)"},
            # curve_intersect(): the points mode returns the intersection points directly, no point groups created
            "point_group": {"label": "Intersection Group", "hide": "{ output != split }"},
        },
    },


    # ── Delete SOP: Entity / Operation / Group on top, tabs Number / Bounding Volume / Normal /
    #    Degenerate / Random (Houdini has exactly these tabs, each with an Enable);
    #    the Expression tab is an extra of this plugin (Houdini puts it in the Operation of the Number tab)
    "PCG_Delete": {
        "order": ["group", "entity", "operation", "keep_points", "delete_unused_groups",
                  "use_number", "number_mode", "number_pattern", "number_start",
                  "number_end", "select_num", "select_of", "number_step",
                  "use_volume", "volume_type", "center_x", "center_y", "center_z",
                  "size_x", "size_y", "size_z", "radius", "volume_invert",
                  "use_normal", "direction_x", "direction_y", "direction_z",
                  "spread_angle", "normal_attribute", "normal_invert",
                  "use_degenerate", "degenerate", "zero_area", "open_faces",
                  "degenerate_tolerance",
                  "use_random", "rand_seed", "use_seed_attribute", "seed_attribute",
                  "percent",
                  "use_expression", "expression"],
        "inputs": {
            "group": {"label": "Group",
                      "help": "Intersected with the filters on the tabs below; all empty / all off deletes nothing. "
                              "With Entity = Edges, enter an edge group here"},
            "entity": {"label": "Entity", "menu": {"point": "Points", "prim": "Primitives",
                                                   "edge": "Edges"},
                       "help": "Edges: deletes the endpoints of the selected edges (only Group is honoured; the tabs below are not supported)"},
            "operation": {"label": "Operation",
                          "menu": {"delete_selected": "Delete Selected",
                                   "keep_selected": "Delete Non-Selected"}},
            # delete(): keep_points is only passed to delete_prims; not read when deleting points / edges (which also deletes points)
            "keep_points": {"label": "Keep Points",
                            "hide": "{ entity == point } { entity == edge }"},
            "delete_unused_groups": {"label": "Delete Unused Groups",
                                     "help": "Removes groups that have no members left after deleting"},
            # Number tab
            "use_number": {"label": "Enable", "folder": "Number"},
            "number_mode": {"folder": "Number", "label": "Operation",
                            "menu": {"every_nth": "Delete by Pattern (Every Nth)",
                                     "range": "Delete by Range",
                                     "pattern": "Delete by Pattern"}},
            # number_mask(): the pattern mode only reads pattern; the range mode does not read step; every_nth does not read select
            "number_pattern": {"folder": "Number", "label": "Pattern",
                               "hide": "{ number_mode != pattern }",
                               "help": "Index pattern: 0 5 12 / 0-20 / 0-20:3 / !3-5 / *"},
            "number_start": {"folder": "Number", "label": "Start",
                             "hide": "{ number_mode == pattern }"},
            "number_end": {"folder": "Number", "label": "End", "help": "-1 = to the end",
                           "hide": "{ number_mode == pattern }"},
            "select_num": {"folder": "Number",
                           "row": {"kind": "vector", "members": ["select_num", "select_of"],
                                   "label": "Select _ of _"},
                           "hide": "{ number_mode != range }",
                           "help": "Takes the first N of every M in the range (left N, right M)"},
            "select_of": {"folder": "Number", "hide": "{ number_mode != range }"},
            "number_step": {"folder": "Number", "label": "Every",
                            "hide": "{ number_mode != every_nth }",
                            "help": "Starting at Start, hits one every this many"},
            # Bounding Volume tab
            "use_volume": {"label": "Enable", "folder": "Bounding Volume"},
            "volume_type": {"folder": "Bounding Volume", "label": "Bounding Type",
                            "menu": {"box": "Bounding Box", "sphere": "Bounding Sphere"}},
            "center_x": {"folder": "Bounding Volume", "row": {"label": "Center"}},
            "center_y": {"folder": "Bounding Volume"},
            "center_z": {"folder": "Bounding Volume"},
            # volume_mask(): box only reads size, sphere only reads radius
            "size_x": {"folder": "Bounding Volume", "row": {"label": "Size"},
                       "hide": "{ volume_type != box }"},
            "size_y": {"folder": "Bounding Volume", "hide": "{ volume_type != box }"},
            "size_z": {"folder": "Bounding Volume", "hide": "{ volume_type != box }"},
            "radius": {"folder": "Bounding Volume", "label": "Radius",
                       "hide": "{ volume_type != sphere }"},
            "volume_invert": {"folder": "Bounding Volume", "label": "Invert",
                              "help": "Selects what is outside the bounding volume"},
            # Normal tab
            "use_normal": {"label": "Enable", "folder": "Normal"},
            "direction_x": {"folder": "Normal", "row": {"label": "Direction"}},
            "direction_y": {"folder": "Normal"},
            "direction_z": {"folder": "Normal"},
            "spread_angle": {"folder": "Normal", "label": "Spread Angle"},
            "normal_attribute": {"folder": "Normal", "label": "Normal Attribute",
                                 "help": "Empty: primitives use freshly computed primitive normals, points use N"},
            "normal_invert": {"folder": "Normal", "label": "Invert"},
            # Degenerate tab (Primitives only)
            "use_degenerate": {"label": "Enable", "folder": "Degenerate"},
            "degenerate": {"folder": "Degenerate", "label": "Delete Degenerate Primitives"},
            "zero_area": {"folder": "Degenerate", "label": "Delete Zero-Area Faces"},
            "open_faces": {"folder": "Degenerate", "label": "Treat Open Faces as Closed",
                           "help": "Also deletes open polylines with perimeter below Tolerance"},
            # degenerate_mask(): tolerance is only read for these two
            "degenerate_tolerance": {"folder": "Degenerate", "label": "Tolerance",
                                     "disable": "{ zero_area == 0 open_faces == 0 }",
                                     "help": "Area is compared against its square, perimeter directly"},
            # Random tab
            "use_random": {"label": "Enable", "folder": "Random"},
            "rand_seed": {"folder": "Random", "label": "Global Seed"},
            "use_seed_attribute": {"folder": "Random", "label": "Use Seed Attribute"},
            "seed_attribute": {"folder": "Random", "label": "Seed Attribute",
                               "disable": "{ use_seed_attribute == 0 }",
                               "help": "Integer attribute used instead of the element index as the random input"},
            "percent": {"folder": "Random", "label": "Percent"},
            # Expression tab
            "use_expression": {"label": "Enable", "folder": "Expression"},
            "expression": {"folder": "Expression", "label": "Filter Expression",
                           "help": "Boolean expression, same syntax as group expressions, e.g. @P.y > 0"},
        },
    },

    # ── Blast by Attribute SOP:Group / Run Over / Attribute Name / Output / Mode / Invert,
    #    Threshold, Min + Max or Center + Width appear per Mode, Output Group / Remove Unused Points last
    "PCG_BlastByAttribute": {
        "order": ["group", "cls", "attribute", "output", "mode", "invert", "threshold",
                  "min", "max", "center", "width", "output_group",
                  "remove_unused_points"],
        "inputs": {
            "group": {"label": "Group", "help": "Only tests these elements; empty = all"},
            "cls": {"label": "Run Over", "menu": {"point": "Points", "prim": "Primitives"}},
            "attribute": {"label": "Attribute Name", "help": "Single-value numeric attribute"},
            "output": {"label": "Output", "menu": {"blast": "Blast", "group": "Group"}},
            "mode": {"label": "Mode", "sep": True,
                     "menu": {"threshold": "Threshold", "range": "Range", "width": "Width"}},
            "invert": {"label": "Invert"},
            # condition_mask(): each mode only reads its own one or two numbers
            "threshold": {"label": "Threshold", "hide": "{ mode != threshold }",
                          "help": "Values below it are hits (equal values are kept)"},
            "min": {"label": "Min", "hide": "{ mode != range }"},
            "max": {"label": "Max", "hide": "{ mode != range }"},
            "center": {"label": "Center", "hide": "{ mode != width }"},
            "width": {"label": "Width", "hide": "{ mode != width }",
                      "help": "Hits [Center − Width/2, Center + Width/2]"},
            # blast_by_attribute(): the group mode only reads output_group; remove_unused_points is not read when deleting points
            "output_group": {"label": "Output Group", "sep": True,
                             "hide": "{ output != group }"},
            "remove_unused_points": {"label": "Remove Unused Points", "sep": True,
                                     "hide": "{ output == group } { cls == point }"},
        },
    },

    # ── Dissolve SOP:Group / Operation / Recompute Normals / Remove Inline Points + Tolerance
    #    / Remove Unused Points / Bridge, output boundary group last (an extra of this plugin)
    "PCG_Dissolve": {
        "order": ["edge_group", "operation", "recompute_normals", "remove_inline_points",
                  "inline_tolerance", "delete_lone_points", "bridge",
                  "output_boundary_group"],
        "inputs": {
            "edge_group": {"label": "Group",
                           "help": "Edges to delete; empty = none selected (with Dissolve Non-Selected "
                                   "that dissolves all edges)"},
            "operation": {"label": "Operation",
                          "menu": {"selected": "Dissolve Selected",
                                   "non_selected": "Dissolve Non-Selected"}},
            "recompute_normals": {"label": "Recompute Normals",
                                  "help": "Recomputes N on the class that had it; does not create N where there was none"},
            "remove_inline_points": {"label": "Remove Inline Points", "sep": True},
            # dissolve(): only read with remove_inline_points
            "inline_tolerance": {"label": "Collinearity Tolerance",
                                 "disable": "{ remove_inline_points == 0 }",
                                 "help": "Angle (degrees): below this counts as collinear"},
            "delete_lone_points": {"label": "Remove Unused Points"},
            "bridge": {"label": "Bridge", "sep": True,
                       "menu": {"leave": "Leave Polygons Unmerged",
                                "bridged": "Create Bridged Polygons",
                                "delete": "Delete Polygons"},
                       "help": "What to do when the merged piece has holes. Leave is what this plugin has always done; "
                               "Create Disjoint Polygons is not implemented"},
            "output_boundary_group": {"label": "Boundary Edge Group", "sep": True,
                                      "help": "Writes the outer border of the merged large primitives as an edge group"},
        },
    },

    # ── Edge Collapse SOP:Group / Remove Degenerate
    "PCG_EdgeCollapse": {
        "order": ["edges", "remove_degenerate"],
        "inputs": {
            "edges": {"label": "Group", "help": _EDGES_HELP},
            "remove_degenerate": {"label": "Remove Degenerate Primitives"},
        },
    },

    # ── Edge Divide SOP: Group / Divisions (or custom positions) / Connect / output group
    "PCG_EdgeDivide": {
        "order": ["edge_group", "cuts", "cut_positions", "connect",
                  "output_edge_group", "output_point_group"],
        "inputs": {
            "edge_group": {"label": "Group", "help": "Edges to divide"},
            # _positions(): Cuts is ignored entirely when Cut Positions is non-empty
            "cuts": {"label": "Divisions", "disable": "{ cut_positions != \"\" }"},
            "cut_positions": {"label": "Cut Positions",
                              "help": "Custom parameter positions, e.g. 0.25 0.5 0.75; empty = evenly by Divisions"},
            "connect": {"label": "Connect Cuts",
                        "help": "When exactly two edges of a primitive are divided, connects them with a new edge, splitting the primitive"},
            "output_edge_group": {"label": "Output Edge Group", "sep": True},
            "output_point_group": {"label": "Output Point Group"},
        },
    },

    # ── Edge Equalize SOP:Group / Measure
    "PCG_EdgeEqualize": {
        "order": ["edges", "group_type", "method", "measure", "output_edge_group"],
        "inputs": {
            "edges": {"label": "Group", "help": _EDGES_HELP},
            # group_type is only read by the three Houdini modes (redistribute only accepts edge groups)
            "group_type": {"label": "Group Type", "disable": "{ method == redistribute }",
                           "menu": {"guess": "Guess from Group", "edges": "Edges", "points": "Points",
                                    "prims": "Primitives"}},
            "method": {"label": "Method",
                       "menu": {"redistribute": "Redistribute Along Curve (PCG)",
                                "average": "Average Edge Length", "longest": "Longest Edge Length",
                                "shortest": "Shortest Edge Length"},
                       "help": "Redistribute is this plugin's approach (redistributes along the original polyline, shape and total length unchanged); "
                               "the last three are Houdini's: all selected edges become the same length"},
            "measure": {"label": "Equalize", "hide": "{ method != redistribute }",
                        "menu": {"arc_length": "Arc Length", "chord": "Chord Length"}},
            "output_edge_group": {"label": "Output Edge Group", "sep": True, "help": "Empty = not written"},
        },
    },

    # ── Edge Straighten SOP:Group / Spacing
    "PCG_EdgeStraighten": {
        "order": ["edges", "spacing"],
        "inputs": {
            "edges": {"label": "Group", "help": _EDGES_HELP + "; closed loops are skipped"},
            "spacing": {"label": "Spacing",
                        "menu": {"preserve": "Preserve Relative Spacing",
                                 "uniform": "Equalize Edge Lengths",
                                 "project": "Project onto Line"}},
        },
    },

    # ── Ends SOP: Group / Close U (Roll is the inverse of Unroll, an extra of this plugin) / Tolerance
    "PCG_Ends": {
        "order": ["group", "op", "tolerance"],
        "inputs": {
            "op": {"label": "Close U",
                   "menu": {"close": "Close Straight", "open": "Open",
                            "unroll": "Unroll with Shared Points",
                            "roll": "Roll (Undo Unroll)"}},
            # ends(): tolerance is only used by roll to decide whether first and last coincide
            "tolerance": {"label": "Tolerance", "hide": "{ op != roll }",
                          "help": "When first and last are not the same point number, they still count as coincident within this distance"},
        },
    },

    # ── Exploded View SOP: piece method / center / distance / scale
    "PCG_ExplodedView": {
        "order": ["piece_from", "piece_attribute", "center", "center_x", "center_y",
                  "center_z", "mode", "distance", "relative_to_size", "up_bias",
                  "shrink"],
        "inputs": {
            "piece_from": {"label": "Pieces From",
                           "menu": {"attribute": "Piece Attribute",
                                    "connectivity": "Connectivity"}},
            # piece_ids(): the connectivity mode does not read the attribute name
            "piece_attribute": {"label": "Piece Attribute",
                                "hide": "{ piece_from != attribute }"},
            "center": {"label": "Explode From", "sep": True,
                       "menu": {"centroid": "Pieces Centroid", "origin": "Specified Point",
                                "bbox": "Bounding Box Center"}},
            # explode(): center_point is only read when center == origin
            "center_x": {"section": None, "row": {"label": "Center"},
                         "hide": "{ center != origin }"},
            "center_y": {"section": None},
            "center_z": {"section": None},
            "mode": {"label": "Explode Type", "sep": True,
                     "menu": {"uniform": "Uniform Distance",
                              "proportional": "Proportional to Distance"}},
            "distance": {"label": "Explode Distance",
                         "help": "A multiplier in the Proportional mode (the farther from the center, the farther it moves)"},
            "relative_to_size": {"label": "Relative to Bounding Box",
                                 "help": "Distance is relative to the longest bounding box side; in the Proportional mode only affects Up Bias"},
            "up_bias": {"label": "Up Bias", "help": "Extra push along +Y"},
            "shrink": {"label": "Piece Scale", "sep": True,
                       "help": "Each piece is scaled about its own centroid, 1 = unchanged"},
        },
    },

    # ── Extract Transform SOP: transform type / weight attribute
    "PCG_ExtractTransform": {
        "order": ["use_piece_attribute", "piece_attribute", "attribute_class", "mode",
                  "output_attributes", "weight_attribute", "compute_distortion",
                  "distortion_attribute"],
        "inputs": {
            "use_piece_attribute": {"in_toggle": "piece_attribute"},
            "piece_attribute": {"label": "Piece Attribute", "toggle": "use_piece_attribute"},
            "attribute_class": {"label": "Attribute Class",
                                "menu": {"prim": "Primitive", "point": "Point"},
                                "disable": "{ use_piece_attribute == 0 }"},
            "mode": {"label": "Extraction Method", "sep": True,
                     "menu": {"rigid": "Translation and Rotation",
                              "similarity": "Translation, Rotation, and Uniform Scale",
                              "affine": "Full Transform",
                              "nonuniform": "Translation, Rotation, and Non-Uniform Scale"}},
            "output_attributes": {"label": "Output Attributes",
                                  "menu": {"standard": "Standard Instance Attributes",
                                           "matrix3": "Transform Matrix (3×3) and Translation",
                                           "matrix4": "Transform Matrix (4×4)"},
                                  "help": "Under Standard, Full Transform still writes a 3×3 transform (shear not separated)"},
            "weight_attribute": {"label": "Weight Attribute",
                                 "help": "Point weights on reference; empty = equal weights (Houdini has no such parameter)"},
            "compute_distortion": {"in_toggle": "distortion_attribute", "sep": True},
            "distortion_attribute": {"label": "Compute Distortion",
                                     "toggle": "compute_distortion",
                                     "help": "Residual RMS per piece (distance from the transformed reference to target)"},
        },
    },

    # ── Facet SOP: Houdini has a flat column of toggles + their own distances / angles; the collapsible sections are flattened here
    "PCG_Facet": {
        "order": ["group", "unique_points", "consolidate_points", "consolidate_distance",
                  "orient_polygons", "cusp_polygons", "cusp_angle", "remove_inline",
                  "inline_distance", "remove_degenerate", "degenerate_distance",
                  "remove_bad_prims", "post_normals", "unit_normals"],
        "inputs": {
            "group": {"label": "Group"},
            "unique_points": {"section": None, "gate": None, "label": "Unique Points",
                              "sep": True},
            "consolidate_points": {"section": None, "gate": None,
                                   "label": "Consolidate Points"},
            "consolidate_distance": {"section": None, "label": "Distance",
                                     "disable": "{ consolidate_points == 0 }"},
            "orient_polygons": {"section": None, "gate": None, "label": "Orient Polygons"},
            "cusp_polygons": {"section": None, "gate": None, "label": "Cusp Polygons"},
            "cusp_angle": {"section": None, "label": "Cusp Angle",
                           "disable": "{ cusp_polygons == 0 }"},
            "remove_inline": {"section": None, "gate": None,
                              "label": "Remove Inline Points"},
            "inline_distance": {"section": None, "label": "Inline Distance",
                                "disable": "{ remove_inline == 0 }"},
            "remove_degenerate": {"section": None, "gate": None,
                                  "label": "Remove Degenerate"},
            "degenerate_distance": {"section": None, "label": "Degenerate Distance",
                                    "disable": "{ remove_degenerate == 0 }"},
            "remove_bad_prims": {"section": None, "label": "Remove Bad Primitives",
                                 "disable": "{ remove_degenerate == 0 }"},
            "post_normals": {"section": None, "gate": None,
                             "label": "Post-Compute Normals", "sep": True},
            # facet(): unit_normals is in the elif of post_normals -- only takes effect when post_normals is off
            "unit_normals": {"section": None, "label": "Make Normals Unit Length",
                             "disable": "{ post_normals == 1 }"},
        },
    },

    # ── Fracture Detail (adds detail to Voronoi fracture faces): group / subdivision / amplitude / frequency / falloff, Noise section
    "PCG_FractureDetail": {
        "order": ["group", "divisions", "triangulate_interior", "amount", "frequency",
                  "relative_to_size", "falloff", "falloff_mode", "noise_type",
                  "fractal", "octaves", "lacunarity", "roughness", "rand_seed"],
        "inputs": {
            "group": {"label": "Interior Group", "help": "Primitive group of the fracture faces (inner surfaces); only these primitives are pushed"},
            "divisions": {"label": "Subdivisions", "sep": True,
                          "help": "Linear subdivision rounds first, to give the noise sample points"},
            "triangulate_interior": {"label": "Triangulate Interior",
                                     "help": "Triangulates fracture faces in lexicographic order so both sides of a shared wall do not crack"},
            "amount": {"label": "Amplitude", "sep": True},
            "frequency": {"label": "Frequency"},
            "relative_to_size": {"label": "Relative to Bounding Box",
                                 "help": "Amplitude / frequency / falloff are normalized by the longest bounding box side"},
            "falloff": {"label": "Edge Falloff", "help": "Fades out within this distance of the fracture face border; 0 = no falloff"},
            # rim_weight(): falloff <= 0 gives all 1 directly, the mode is not read
            "falloff_mode": {"label": "Falloff Shape",
                             "menu": {"smooth": "Smooth", "linear": "Linear"},
                             "disable": "{ falloff == 0 }"},
            "noise_type": {"label": "Noise Type",
                           "menu": {"value": "Value", "perlin": "Perlin",
                                    "simplex": "Simplex",
                                    "worley": "Worley Cellular F1",
                                    "worley_f2f1": "Worley Cellular F2-F1"}},
            "fractal": {"label": "Fractal Type",
                        "menu": {"none": "None", "standard": "Standard",
                                 "terrain": "Terrain", "hybrid_terrain": "Hybrid Terrain"}},
            # fractal_noise(): none returns a single noise layer directly
            "octaves": {"label": "Max Octaves", "hide": "{ fractal == none }"},
            "lacunarity": {"label": "Lacunarity", "hide": "{ fractal == none }"},
            "roughness": {"label": "Roughness", "hide": "{ fractal == none }"},
            "rand_seed": {"label": "Seed", "section": "Noise"},
        },
    },

    # ── Fuse SOP (2.0): three tabs Snap / Fuse / Output Attributes and Groups
    "PCG_Fuse": {
        "order": ["group", "use_target", "target_group", "modify_target",
                  "position_attribute", "snap_to", "using", "output_positions",
                  "use_snap_distance", "snap_distance", "use_radius", "radius_attribute",
                  "use_match", "match_attribute", "match_condition", "match_tolerance",
                  "use_grid", "grid_x", "grid_y", "grid_z", "grid_off_x", "grid_off_y",
                  "grid_off_z",
                  "fuse_snapped_points", "keep_fused_points", "remove_repeated",
                  "remove_degenerate_unused", "remove_all_unused",
                  "use_output", "recompute_normals", "snapped_points_group",
                  "snapped_to_group", "attributes_to_snap"],
        "inputs": {
            "group": {"folder": "Snap", "label": "Group"},
            "use_target": {"folder": "Snap", "label": "Target Points (2nd Input)"},
            "target_group": {"folder": "Snap", "label": "Target Group"},
            "modify_target": {"folder": "Snap", "label": "Modify Target"},
            "position_attribute": {"folder": "Snap", "label": "Position Attribute",
                                   "sep": True},
            "snap_to": {"folder": "Snap", "label": "Snap To",
                        "menu": {"near_points": "Near Points", "grid": "Grid",
                                 "none": "None"}},
            # In the none mode each point is its own cluster; Using / Output Positions are read but have no effect
            "using": {"folder": "Snap", "label": "Using",
                      "menu": {"least_point_number": "Least Point Number",
                               "closest": "Closest Point",
                               "greatest_point_number": "Greatest Point Number"},
                      "disable": "{ snap_to == none }"},
            "output_positions": {"folder": "Snap", "label": "Output Positions",
                                 "menu": {"average": "Average Value",
                                          "target": "Chosen Point (Using)",
                                          "keep": "Keep Original"},
                                 "disable": "{ snap_to == none }"},
            # fuse(): snap_distance / radius / match are only read in the near_points mode
            "use_snap_distance": {"folder": "Snap", "hide": "{ snap_to != near_points }"},
            "snap_distance": {"folder": "Snap", "label": "Snap Distance",
                              "hide": "{ snap_to != near_points }"},
            "use_radius": {"folder": "Snap", "label": "Radius Attribute",
                           "hide": "{ snap_to != near_points }"},
            "radius_attribute": {"folder": "Snap", "label": "Radius Attribute",
                                 "hide": "{ snap_to != near_points }",
                                 "help": "Not read when Target is wired (snaps to target points)"},
            "use_match": {"folder": "Snap", "label": "Match Attribute",
                          "hide": "{ snap_to != near_points }"},
            "match_attribute": {"folder": "Snap", "label": "Match Attribute",
                                "hide": "{ snap_to != near_points }",
                                "help": "Not read when Target is wired"},
            "match_condition": {"folder": "Snap", "label": "Match Condition",
                                "menu": {"equal": "Equal", "unequal": "Unequal"},
                                "hide": "{ snap_to != near_points }"},
            "match_tolerance": {"folder": "Snap", "label": "Match Tolerance",
                                "hide": "{ snap_to != near_points }"},
            # Only read in the grid mode
            "use_grid": {"folder": "Snap", "label": "Grid", "hide": "{ snap_to != grid }"},
            "grid_x": {"folder": "Snap", "row": {"label": "Grid Spacing"},
                       "hide": "{ snap_to != grid }"},
            "grid_off_x": {"folder": "Snap", "row": {"label": "Grid Offset"},
                           "hide": "{ snap_to != grid }"},
            "grid_y": {"folder": "Snap"}, "grid_z": {"folder": "Snap"},
            "grid_off_y": {"folder": "Snap"}, "grid_off_z": {"folder": "Snap"},
            # Fuse tab
            "fuse_snapped_points": {"folder": "Fuse", "label": "Fuse Snapped Points"},
            "keep_fused_points": {"folder": "Fuse", "label": "Keep Fused Points"},
            "remove_repeated": {"folder": "Fuse",
                                "label": "Remove Repeated Vertices and Degenerate Primitives"},
            "remove_degenerate_unused": {"folder": "Fuse",
                                         "label": "Remove Unused Points from Degenerate Primitives"},
            "remove_all_unused": {"folder": "Fuse", "label": "Remove All Unused Points"},
            # Output Attributes and Groups tab
            "use_output": {"folder": "Output Attributes and Groups", "label": "Output"},
            "recompute_normals": {"folder": "Output Attributes and Groups",
                                  "label": "Recompute Affected Normals"},
            "snapped_points_group": {"folder": "Output Attributes and Groups",
                                     "label": "Snapped Points Group"},
            "snapped_to_group": {"folder": "Output Attributes and Groups",
                                 "label": "Snapped Destination Group"},
            "attributes_to_snap": {"folder": "Output Attributes and Groups",
                                   "label": "Attributes to Snap",
                                   "help": "Point attributes merged together with P according to Output Positions (wildcards allowed)"},
        },
    },

    # ── Join SOP: Group / Loop / Tolerance / Reverse, grouping, attributes
    "PCG_Join": {
        "order": ["group", "loop", "tolerance", "reverse_to_fit", "partition_attribute",
                  "prim_attribs", "remove_unused_points"],
        "inputs": {
            "loop": {"label": "Loop", "help": "Closes first and last after joining"},
            "tolerance": {"label": "Tolerance",
                          "help": "Gaps smaller than this count as already joined (no connecting segment added)"},
            "reverse_to_fit": {"label": "Reverse Primitives to Fit",
                               "help": "Before joining each curve, checks which end is closer and reverses if needed"},
            "partition_attribute": {"label": "Partition Attribute", "sep": True,
                                    "help": "Groups by a prim attribute, each group joined separately; empty = join everything into one"},
            "prim_attribs": {"label": "Primitive Attributes",
                             "menu": {"first": "Keep First", "drop": "Drop"}},
            "remove_unused_points": {"label": "Remove Unused Points"},
        },
    },

    # ── Edge Loop mode of PolySplit: seed edges / cut count / positions / output group
    "PCG_LoopCut": {
        "order": ["edge_group", "cuts", "cut_positions", "output_edge_group",
                  "output_point_group"],
        "inputs": {
            "edge_group": {"label": "Seed Edges", "help": "Loops start at these edges and walk across quads"},
            "cuts": {"label": "Number of Loops", "disable": "{ cut_positions != \"\" }"},
            "cut_positions": {"label": "Cut Positions",
                              "help": "Custom parameter positions; when non-empty, Number of Loops is ignored"},
            "output_edge_group": {"label": "Output Edge Group", "sep": True},
            "output_point_group": {"label": "Output Point Group"},
        },
    },

    # ── Match Axis SOP:Group / From / To / Pivot / Up
    "PCG_MatchAxis": {
        "order": ["group", "from_x", "from_y", "from_z", "to_x", "to_y", "to_z",
                  "pivot", "up_from_x", "up_from_y", "up_from_z", "up_to_x",
                  "up_to_y", "up_to_z"],
        "inputs": {
            "from_x": {"row": {"label": "From Axis"}, "sep": True},
            "to_x": {"row": {"label": "To Axis"}},
            "pivot": {"label": "Pivot",
                      "menu": {"origin": "Origin", "centroid": "Centroid",
                               "bbox_center": "Bounding Box Center"}},
            "up_from_x": {"row": {"label": "Up From"}, "sep": True,
                          "help": "When both Up From / Up To are non-zero, also rotates around the main axis so up matches too"},
            "up_to_x": {"row": {"label": "Up To"}},
        },
    },

    # ── Mirror SOP:Group / Operation / Keep Original / Orient Plane with → Origin + Direction
    #    or Translate + Rotate / Distance / Reverse Normals, Consolidate Seam, output groups, reflected attributes
    "PCG_Mirror": {
        "order": ["group", "operation", "mode", "orient",
                  "origin_x", "origin_y", "origin_z", "normal_x", "normal_y", "normal_z",
                  "translate_x", "translate_y", "translate_z",
                  "rotate_x", "rotate_y", "rotate_z", "distance", "reverse_normals",
                  "fuse_result", "snap_tolerance", "original_group",
                  "mirror_group", "vector_attributes"],
        "inputs": {
            "group": {"label": "Group", "help": "Only mirrors these primitives; empty = all"},
            "operation": {"label": "Operation",
                          "menu": {"mirror_all": "Mirror All Primitives",
                                   "clip_and_mirror": "Clip Primitives and Mirror"}},
            # Houdini has a Keep Original toggle here; this dropdown predates it, so its tokens cannot change
            "mode": {"label": "Keep Original",
                     "menu": {"mirror": "Off (Mirrored Only)",
                              "append": "On (Original + Mirrored)"}},
            "orient": {"label": "Orient Plane with", "sep": True,
                       "menu": {"direction": "Direction", "transform": "Transform"}},
            # mirror(): the transform mode does not read origin / normal, the direction mode does not read translate / rotate
            "origin_x": {"row": {"label": "Origin"}, "hide": "{ orient == transform }"},
            "origin_y": {"hide": "{ orient == transform }"},
            "origin_z": {"hide": "{ orient == transform }"},
            "normal_x": {"row": {"label": "Direction"}, "hide": "{ orient == transform }"},
            "normal_y": {"hide": "{ orient == transform }"},
            "normal_z": {"hide": "{ orient == transform }"},
            "translate_x": {"row": {"label": "Translate"}, "hide": "{ orient == direction }"},
            "translate_y": {"hide": "{ orient == direction }"},
            "translate_z": {"hide": "{ orient == direction }"},
            "rotate_x": {"row": {"label": "Rotate"}, "hide": "{ orient == direction }",
                         "help": "Rotates (1,0,0) into the plane normal; X first, then Y, then Z"},
            "rotate_y": {"hide": "{ orient == direction }"},
            "rotate_z": {"hide": "{ orient == direction }"},
            "distance": {"label": "Distance", "help": "Distance the plane is moved along its normal"},
            "reverse_normals": {"label": "Reverse Normals",
                                "help": "Off = the mirrored copy keeps its winding (faces point inward)"},
            # mirror(): the mirror mode returns before seam consolidation / the original-copy group
            "fuse_result": {"label": "Consolidate Seam", "sep": True,
                            "hide": "{ mode == mirror }"},
            "snap_tolerance": {"label": "Seam Distance", "hide": "{ mode == mirror }",
                               "help": "Normalized by the longest bounding box side; points touching the plane are projected exactly before welding"},
            "original_group": {"label": "Original Group", "sep": True,
                               "hide": "{ mode == mirror }"},
            "mirror_group": {"label": "Output Group", "help": "The mirrored primitives; empty = not created"},
            "vector_attributes": {"label": "Reflect Vector Attributes", "sep": True,
                                  "help": "Three-component direction attributes reflected along, space-separated"},
        },
    },

    # ── Peak SOP: Group / Distance / mitering / attributes
    "PCG_Peak": {
        "order": ["group", "distance", "miter_corners", "max_miter", "distance_attribute",
                  "normal_attribute"],
        "inputs": {
            "distance": {"label": "Distance"},
            "miter_corners": {"label": "Miter Corners", "sep": True,
                              "help": "Scaled up by the miter factor, so a plane stays a plane after pushing"},
            "max_miter": {"label": "Max Miter Scale", "disable": "{ miter_corners == 0 }"},
            "distance_attribute": {"label": "Distance Scale Attribute", "sep": True,
                                   "help": "Point attribute multiplied onto Distance; empty = not used"},
            "normal_attribute": {"label": "Normal Attribute"},
        },
    },

    # ── Point Split SOP:Group / Attribute / Tolerance / Promote
    "PCG_PointSplit": {
        "order": ["group", "attribute", "tolerance", "promote"],
        "inputs": {
            "attribute": {"label": "Split by Attribute",
                          "help": "Vertex attribute; empty = every vertex is split into its own point"},
            "tolerance": {"label": "Tolerance"},
            "promote": {"label": "Promote to Point Attribute"},
        },
    },

    # ── PolyBridge SOP: Source / Destination, Divisions / Twist / interpolation, direction, output groups
    "PCG_PolyBridge": {
        "order": ["source_group", "dest_group", "divisions", "twist", "flip_direction",
                  "interpolation", "magnitude", "remove_caps", "reverse_normals",
                  "output_group"],
        "inputs": {
            "source_group": {"label": "Source Group"},
            "dest_group": {"label": "Destination Group"},
            "divisions": {"label": "Divisions", "sep": True},
            "twist": {"label": "Twist", "help": "Shifts the starting point of closed-loop pairing by this many more points (no effect on open curves)"},
            "flip_direction": {"label": "Reverse Destination"},
            "interpolation": {"label": "Interpolation", "sep": True,
                              "menu": {"linear": "Linear", "hermite": "Hermite"}},
            # poly_bridge(): mag only goes into the hermite branch
            "magnitude": {"label": "Magnitude", "hide": "{ interpolation != hermite }"},
            "remove_caps": {"label": "Remove Source and Destination Faces", "sep": True},
            "reverse_normals": {"label": "Reverse Normals"},
            "output_group": {"label": "Bridge Polygons Group", "sep": True},
        },
    },

    # ── Poly Expand 2D SOP: main parameters flat, two sections Local Attributes / Advanced
    #    (previously a Create Output Groups section toggle turned off the whole section, while in the code it only governs two group names)
    "PCG_PolyExpand2D": {
        "order": ["group", "positions_2d", "plane_origin_x", "plane_origin_y",
                  "plane_origin_z", "plane_distance", "plane_normal_x", "plane_normal_y",
                  "plane_normal_z", "output", "offset", "divisions", "side_determination",
                  "output_inside", "output_outside", "keep_input_geometry",
                  "split_offset_curves_to_omit_end_caps",
                  "create_output_groups", "inside_group", "outside_group",
                  "edge_distance_attribute", "edge_speed_attribute",
                  "coincidence_tolerance", "parallelism_tolerance", "on_failure",
                  "recompute_point_normals"],
        "inputs": {
            "positions_2d": {"label": "2D Positions",
                             "menu": {"fit_plane": "Fit Plane",
                                      "specify_plane": "Select Projection Plane"}},
            # plane_basis(): origin / normal are only read in the specify_plane mode
            "plane_origin_x": {"row": {"label": "Plane Origin"},
                               "hide": "{ positions_2d != specify_plane }"},
            "plane_distance": {"label": "Plane Distance",
                               "help": "Moves the plane along its normal; the code also reads it in the Fit Plane mode"},
            "plane_normal_x": {"row": {"label": "Plane Normal"},
                               "hide": "{ positions_2d != specify_plane }"},
            "output": {"label": "Output", "sep": True,
                       "menu": {"offset_curves": "Offset Curves",
                                "offset_surfaces": "Offset Surfaces"},
                       "help": "Offset Surfaces: fills the band between the input and the offset lines with triangles (road network → road surface)"},
            "offset": {"label": "Offset"},
            "divisions": {"label": "Divisions", "help": "When > 1, outputs rings 1 ... Divisions"},
            "side_determination": {"label": "Side Determination",
                                   "menu": {"simple_reachability": "Simple Reachability",
                                            "winding_number": "Winding Number"}},
            "output_inside": {"label": "Output Inside"},
            "output_outside": {"label": "Output Outside"},
            "keep_input_geometry": {"label": "Keep Input Geometry"},
            "split_offset_curves_to_omit_end_caps": {
                "label": "Split Offset Curves to Omit End Caps",
                "hide": "{ output != offset_curves }"},
            "create_output_groups": {"gate": None, "label": "Create Output Groups"},
            "inside_group": {"label": "Inside Group",
                             "disable": "{ create_output_groups == 0 }"},
            "outside_group": {"label": "Outside Group",
                              "disable": "{ create_output_groups == 0 }"},
            "edge_distance_attribute": {"label": "Edge Distance Attribute"},
            "edge_speed_attribute": {"label": "Edge Speed Attribute"},
            "coincidence_tolerance": {"section": "Advanced",
                                      "label": "Coincidence Tolerance"},
            "parallelism_tolerance": {"section": "Advanced",
                                      "label": "Parallelism Tolerance"},
            "on_failure": {"section": "Advanced", "label": "Skeleton Failure",
                           "menu": {"fail_with_error": "Fail with Error",
                                    "warn_and_keep_input": "Warn and Keep Input",
                                    "output_nothing": "Output Empty Geometry"}},
            "recompute_point_normals": {"section": "Advanced",
                                        "label": "Recompute Point Normals",
                                        "help": "Only has something to do when Keep Input Geometry merges an input with primitives back in"},
        },
    },
}
