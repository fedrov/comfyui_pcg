"""
Parameter panel specs for group g10 (format: see the docstring at the top of panel_specs.py).

Deform / generate (Spherify, Topo Transfer, Transform Pieces, Add, Ballistic Path,
Circle, Cross Section Surface, Extract Silhouette, Font, IsoSurface, L-System,
Line, Platonic Solids, PolyLoft, Revolve, Skin, Sweep, Torus, Volume),
groups (Edge Group Promote, Group Delete, Group Edges, Group Expand, Group Find Path,
Group from Attribute Boundary, Group Inside, Group Promote, Partition),
Heightfield from Image, and loops / sequences (For-Each Begin / End, For-Each Frame
Begin / End, Geo Sequence Pick, Retime).

The hide / disable conditions follow the branches where a parameter really takes effect in the node code (nodes*.py run() + geo/
implementation), not a copy of Houdini.
"""

_MERGE = {"replace": "Replace Existing", "union": "Union with Existing",
          "intersect": "Intersect with Existing",
          "subtract": "Subtract from Existing"}
_PLANE = {"xy": "XY Plane", "yz": "YZ Plane", "zx": "ZX Plane"}
_ANY_TARGET = "{ mode == velocity }"


SPECS = {
    # ── Spherify (Houdini has no SOP of this name; follows deformer conventions: Group / strength / radius / center,
    #    normal update last)
    "PCG_Spherify": {
        "order": ["group", "amount", "radius", "use_center", "center_x", "normals"],
        "inputs": {
            "amount": {"label": "Amount",
                       "help": "0 = no change, 1 = exactly on the sphere; may extrapolate beyond 0~1"},
            "radius": {"label": "Radius",
                       "help": "0 = mean distance from the selected points to the center (least volume change)"},
            "use_center": {"label": "Specify Center",
                           "help": "Off = use the centroid of the selected points as the center"},
            "center_x": {"row": {"label": "Center"}},
            "normals": {"label": "Update Normals", "sep": True,
                        "menu": {"jacobian": "Transform by Jacobian",
                                 "none": "Don't Update"}},
        },
    },

    # ── Topo Transfer: Landmarks / rigid pre-alignment on top, solver iterations below
    "PCG_TopoTransfer": {
        "order": ["landmark_attribute", "prealign", "iterations", "smoothing",
                  "stiffness"],
        "inputs": {
            "landmark_attribute": {"label": "Landmark Attribute",
                                   "help": "Integer point attribute present on both sides; points with the same value (≥ 0) are paired and pinned every iteration"},
            "prealign": {"label": "Rigid Pre-Alignment",
                         "help": "With ≥ 3 landmark pairs, aligns with a similarity transform, otherwise by bounding box"},
            "iterations": {"label": "Iterations", "sep": True},
            "smoothing": {"label": "Smoothing Steps",
                          "help": "Smoothing passes on the displacement field per iteration, decreasing linearly from this value to 0 (the last iteration is pure projection)"},
            # stiffness is only used in the smoothing loop; with smoothing = 0 the loop never runs
            "stiffness": {"label": "Smoothing Strength",
                          "disable": "{ smoothing == 0 }"},
        },
    },

    # ── Transform Pieces: only Piece Attribute (rest is the third input)
    "PCG_TransformPieces": {
        "order": ["attribute_mode", "piece_attribute", "invert_transformation",
                  "center_pieces", "attributes_to_transform",
                  "copy_template_attributes", "attributes_to_copy", "groups_to_copy"],
        "inputs": {
            "attribute_mode": {"label": "Attribute Mode",
                               "menu": {"match": "Match by Attribute",
                                        "index": "Index by Attribute"}},
            "piece_attribute": {"label": "Attribute",
                                "help": "Prim attribute preferred, falls back to point; Match: pairs with the same-named attribute on template points; "
                                        "Index: the integer value is the template point number"},
            "invert_transformation": {"label": "Invert Transformation"},
            "center_pieces": {"label": "Center Pieces (No Rest)",
                              "disable": "{ invert_transformation == 1 }",
                              "help": "This plugin's extension: without rest wired, first moves the piece's center to the origin, then transforms. "
                                      "Off = Houdini's behaviour"},
            "attributes_to_transform": {"label": "Attributes to Transform",
                                        "help": "Attributes named N are transformed as normals, other three-component attributes as vectors; P is always transformed"},
            "copy_template_attributes": {"label": "Copy Template Attributes", "sep": True},
            "attributes_to_copy": {"label": "Attributes to Copy",
                                   "disable": "{ copy_template_attributes == 0 }"},
            "groups_to_copy": {"label": "Groups to Copy",
                               "disable": "{ copy_template_attributes == 0 }"},
        },
    },

    # ── Add SOP: two tabs, Points / Polygons; on the Polygons tab By Pattern / By Group /
    #    By Attribute (single-choice tabs in Houdini; here the three sections can be on at the same time)
    "PCG_Add": {
        "order": ["keep_points", "points",
                  "use_pattern", "pattern", "pattern_closed",
                  "use_group", "group", "group_mode", "group_n", "group_closed",
                  "use_attribute", "attribute", "attribute_closed",
                  "use_remove", "remove_repeated", "remove_unused"],
        "inputs": {
            # A section with only one toggle → turned into a plain toggle row
            "keep_points": {"folder": "Points", "section": None, "gate": None,
                            "label": "Delete Geometry But Keep the Points"},
            "points": {"folder": "Points", "label": "Points",
                       "help": "One new point per line: x y z; appended after the existing points"},
            "use_pattern": {"folder": "Polygons"},
            "pattern": {"folder": "Polygons", "label": "Pattern"},
            "pattern_closed": {"folder": "Polygons", "label": "Closed"},
            "use_group": {"folder": "Polygons"},
            "group": {"folder": "Polygons", "label": "Group"},
            "group_mode": {"folder": "Polygons", "label": "Add",
                           "menu": {"all_points": "All Points",
                                    "groups_of_n": "Groups of N Points",
                                    "every_nth": "Skip Every Nth Point",
                                    "each_point": "Each Point Separately"}},
            # _by_group only reads n for groups_of_n / every_nth
            "group_n": {"folder": "Polygons", "label": "N",
                        "hide": "{ group_mode == all_points } { group_mode == each_point }"},
            "group_closed": {"folder": "Polygons", "label": "Closed"},
            "use_attribute": {"folder": "Polygons"},
            "attribute": {"folder": "Polygons", "label": "Attribute Name"},
            "attribute_closed": {"folder": "Polygons", "label": "Closed"},
            "use_remove": {"folder": "Polygons"},
            "remove_repeated": {"folder": "Polygons", "label": "Remove Repeated Points"},
            "remove_unused": {"folder": "Polygons", "label": "Remove Unused Points"},
        },
    },

    # ── Ballistic Path SOP: three tabs General / Projectile Properties / Basic Collision
    "PCG_BallisticPath": {
        "order": ["group", "mode", "v_attribute", "duration", "flight_time",
                  "launch_angle", "drag", "gravity_x", "samples",
                  "ground", "ground_height"],
        "inputs": {
            "group": {"folder": "General"},
            "mode": {"folder": "General", "label": "Launch Method",
                     "menu": {"velocity": "Free (Velocity Attribute)",
                              "target_time": "Targeted: Life",
                              "target_angle": "Targeted: Initial Angle"},
                     "help": "The two Targeted modes use the second input's points as targets, paired with launch points by point number"},
            "v_attribute": {"folder": "General", "label": "Velocity Attribute",
                            "hide": "{ mode != velocity }"},
            "duration": {"folder": "General", "label": "Life",
                         "hide": "{ mode != velocity }"},
            "flight_time": {"folder": "General", "label": "Life",
                            "hide": "{ mode != target_time }",
                            "help": "Time to reach the target (seconds)"},
            "launch_angle": {"folder": "General", "label": "Initial Angle",
                             "hide": "{ mode != target_angle }"},
            "drag": {"folder": "Projectile Properties", "label": "Drag"},
            "gravity_x": {"folder": "Projectile Properties",
                          "row": {"label": "Gravity"}},
            "samples": {"folder": "Projectile Properties",
                        "label": "Points per Path",
                        "help": "Houdini uses FPS × duration; here the number of points per trajectory is given directly"},
            # Houdini: ☑ Clip Below Height [value]
            "ground": {"folder": "Basic Collision", "in_toggle": "ground_height"},
            "ground_height": {"folder": "Basic Collision", "toggle": "ground",
                              "label": "Clip Below Height",
                              "help": "Height along the gravity direction; with the collision input wired, also clipped at the first collision point"},
        },
    },

    # ── Circle SOP:Primitive Type / Orientation / Reverse / Radius / Center /
    #    Rotate / Uniform Scale / Order / Divisions / Arc Type / Arc Angles
    "PCG_Circle": {
        "order": ["prim_type", "orientation", "reverse", "radius_x", "cx",
                  "use_rotate", "rx", "uniform_scale", "divisions",
                  "use_spline", "order", "use_arc", "arc_type", "arc_start"],
        "inputs": {
            "prim_type": {"label": "Primitive Type",
                          "menu": {"polygon": "Polygon", "nurbs_curve": "NURBS Curve",
                                   "bezier_curve": "Bezier Curve"}},
            "orientation": {"label": "Orientation", "menu": dict(_PLANE)},
            "reverse": {"label": "Reverse Output"},
            "radius_x": {"sep": True},
            "uniform_scale": {"label": "Uniform Scale"},
            "divisions": {"label": "Divisions"},
            # order is only read when converting to splines (prim_type != polygon)
            "use_spline": {"hide": "{ prim_type == polygon }"},
            "order": {"label": "Order", "hide": "{ prim_type == polygon }"},
            "arc_type": {"label": "Arc Type",
                         "menu": {"open_arc": "Open Arc", "closed_arc": "Closed Arc",
                                  "sliced_arc": "Sliced Arc"}},
            "arc_start": {"row": {"kind": "vector", "members": ["arc_start", "arc_end"],
                                  "label": "Arc Angles"}},
        },
    },

    # ── Cross Section Surface: cross-section groups / interpolation / divisions in both directions
    "PCG_CrossSectionSurface": {
        "order": ["group", "interpolation", "divisions_s"],
        "inputs": {
            "group": {"label": "Cross Section Group"},
            "interpolation": {"label": "Interpolation",
                              "menu": {"cubic": "Cubic (Catmull-Rom)",
                                       "linear": "Linear"}},
            "divisions_s": {"row": {"kind": "vector",
                                    "members": ["divisions_s", "divisions_t"],
                                    "label": "Divisions"},
                            "sep": True,
                            "help": "First: subdivisions per span along the cross sections; second: subdivisions per span between cross sections"},
        },
    },

    # ── Cross Section Surface (Houdini semantics, pcg100 s3_curves): follows Houdini's four tabs
    #    cross_section_grid(): Cap Divisions / Triangular Poles / Scale / Roundness are only read for grid;
    #    Wrap U is only read when U is not normalized, Wrap V likewise; Max Length only when U is normalized and V is not
    "PCG_CrossSectionSurfaceHou": {
        "order": ["group", "reverse_cross_sections", "end_cap_type", "cap_divisions",
                  "triangular_poles", "end_cap_scale", "end_cap_roundness", "end_caps_group",
                  "surface_type", "unique_seam_vertices", "swap_rows_cols", "close_backbone",
                  "compute_uvs", "override_uvs", "length_weighted_uvs", "normalize_u", "normalize_v",
                  "wrap_u", "wrap_v", "use_max_length", "flip_u", "uv_scale_u",
                  "from_cross_sections", "point_row_attrib", "point_col_attrib", "prim_row_attrib",
                  "prim_col_attrib", "cross_section_num_attrib"],
        "inputs": {
            "group": {"label": "Cross Section Group", "folder": "Cross Section"},
            "reverse_cross_sections": {"label": "Reverse Cross Sections"},
            "end_cap_type": {"label": "End Cap Type", "sep": True,
                             "menu": {"none": "None", "single_polygon": "Single Polygon",
                                      "grid": "Grid", "side_single_polygon": "Side Single Polygon"},
                             "help": "Single Polygon / Grid need closed cross sections and an open backbone; Side Single Polygon needs a closed backbone and open cross sections"},
            "cap_divisions": {"label": "Cap Divisions", "hide": "{ end_cap_type != grid }"},
            "triangular_poles": {"label": "Triangular Poles", "hide": "{ end_cap_type != grid }"},
            "end_cap_scale": {"label": "End Cap Scale", "hide": "{ end_cap_type != grid }",
                              "help": "Pole lift distance = this × bounding circle radius of the end cross section; negative = concave"},
            "end_cap_roundness": {"label": "End Cap Roundness", "hide": "{ end_cap_type != grid }",
                                  "help": "0 pointed (cone), 1 round (quarter circle); negative reverses the curvature"},
            "end_caps_group": {"label": "End Caps Group", "hide": "{ end_cap_type == none }",
                               "help": "Empty = no group created"},
            "surface_type": {"label": "Surface Type", "folder": "Surface",
                             "menu": {"points": "Points", "rows": "Rows", "columns": "Columns",
                                      "rows_and_columns": "Rows and Columns", "triangles": "Triangles",
                                      "quads": "Quadrilaterals", "alt_triangles": "Alternating Triangles",
                                      "reverse_triangles": "Reverse Triangles"}},
            "unique_seam_vertices": {"label": "Ensure Unique Seam Vertices",
                                     "disable": "{ surface_type != rows surface_type != columns "
                                                "surface_type != rows_and_columns }",
                                     "help": "Closed row / column curves get one extra vertex at the seam (u = 0 and 1 kept apart)"},
            "swap_rows_cols": {"label": "Swap Rows and Columns"},
            "close_backbone": {"label": "Close Implicit Backbone Curve"},
            "compute_uvs": {"label": "Compute UVs", "folder": "UV Coordinates"},
            "override_uvs": {"label": "Override Any Existing UVs", "disable": "{ compute_uvs == 0 }",
                             "help": "When off, the U of existing uv point attributes on open cross sections is copied as-is"},
            "length_weighted_uvs": {"label": "Length-Weighted UVs", "disable": "{ compute_uvs == 0 }"},
            "normalize_u": {"label": "Normalize Computed Us", "disable": "{ compute_uvs == 0 }"},
            "normalize_v": {"label": "Normalize Computed Vs", "disable": "{ compute_uvs == 0 }"},
            "wrap_u": {"label": "Make Computed Us Wrap Seamlessly",
                       "disable": "{ compute_uvs == 0 } { normalize_u == 1 }"},
            "wrap_v": {"label": "Make Computed Vs Wrap Seamlessly",
                       "disable": "{ compute_uvs == 0 } { normalize_v == 1 }"},
            "use_max_length": {"label": "Use Max Cross Section Length for Proportional Scale",
                               "disable": "{ compute_uvs == 0 } { normalize_u == 0 } { normalize_v == 1 }"},
            "flip_u": {"label": "Flip Computed Us", "disable": "{ compute_uvs == 0 }"},
            "uv_scale_u": {"row": {"kind": "vector", "members": ["uv_scale_u", "uv_scale_v"],
                                   "label": "UV Scale"},
                           "disable": "{ compute_uvs == 0 }"},
            "from_cross_sections": {"label": "From Cross Sections", "folder": "Attributes",
                                    "help": "Point attributes come from the source points, prim attributes from that row's cross section"},
            "point_row_attrib": {"label": "Point Row Attribute", "sep": True, "help": "Empty = not written"},
            "point_col_attrib": {"label": "Point Col Attribute", "help": "Empty = not written"},
            "prim_row_attrib": {"label": "Prim Row Attribute", "help": "Empty = not written"},
            "prim_col_attrib": {"label": "Prim Col Attribute", "help": "Empty = not written"},
            "cross_section_num_attrib": {"label": "Cross Section Num Attribute", "help": "Empty = not written"},
        },
    },

    # ── Extract Silhouette: Group / mode / direction / origin; outline and contour each have their own options
    "PCG_ExtractSilhouette": {
        "order": ["group", "mode", "direction_x", "origin_x", "simplify",
                  "include_boundary"],
        "inputs": {
            "mode": {"label": "Mode",
                     "menu": {"outline": "Projected Outline",
                              "contour": "Contour on Mesh"}},
            "direction_x": {"row": {"label": "Direction"}, "sep": True},
            # contour only looks at the sign of the projected area (independent of translation), output stays in place on the mesh, origin not read
            "origin_x": {"row": {"label": "Origin"},
                         "hide": "{ mode == contour }",
                         "help": "The projection plane passes through this point"},
            "simplify": {"label": "Remove Inline Points", "sep": True,
                         "hide": "{ mode == contour }"},
            "include_boundary": {"label": "Include Unshared Edges",
                                 "hide": "{ mode == outline }"},
        },
    },

    # ── Font SOP: Type / Font File / Text / alignment, then font size, spacing, precision
    "PCG_Font": {
        "order": ["mode", "font", "text", "halign", "valign", "size", "tracking",
                  "line_spacing", "curve_segments", "depth", "fallback"],
        "inputs": {
            "mode": {"label": "Type",
                     "menu": {"outline": "Outline", "faces": "Faces",
                              "extrude": "Extruded"}},
            "font": {"label": "Font File",
                     "help": "Path, file name (arial, msyh) or family name; empty = arial / DejaVuSans"},
            "text": {"label": "Text"},
            "halign": {"label": "Horizontal Alignment",
                       "menu": {"left": "Left", "center": "Center", "right": "Right"}},
            "valign": {"label": "Vertical Alignment",
                       "menu": {"baseline": "Baseline", "top": "Top",
                                "center": "Center", "bottom": "Bottom"}},
            "size": {"label": "Font Size", "sep": True},
            "tracking": {"label": "Tracking"},
            "line_spacing": {"label": "Line Spacing"},
            "curve_segments": {"label": "Curve Segments",
                               "help": "Number of polyline segments each quadratic / cubic Bézier is split into (Houdini's Level of Detail)"},
            "depth": {"label": "Extrude Depth", "hide": "{ mode != extrude }"},
            "fallback": {"label": "Fallback Fonts", "sep": True,
                         "help": "Fonts searched in order when the main font lacks a glyph"},
        },
    },

    # ── IsoSurface SOP:Implicit Function / Min Bound / Max Bound / Divisions
    "PCG_IsoSurface": {
        "order": ["expression", "iso", "bound_min_x", "bound_max_x", "divisions_x",
                  "output", "project", "normals"],
        "inputs": {
            "expression": {"label": "Implicit Function"},
            "iso": {"label": "Iso Value"},
            "bound_min_x": {"row": {"label": "Min Bound"}, "sep": True},
            "bound_max_x": {"row": {"label": "Max Bound"}},
            "divisions_x": {"row": {"label": "Divisions"}},
            "output": {"label": "Output Type", "sep": True,
                       "menu": {"polygons": "Polygons", "volume": "Volume"}},
            # The volume mode returns before surface extraction
            "project": {"label": "Project to Isosurface", "hide": "{ output == volume }"},
            "normals": {"label": "Compute Normals", "hide": "{ output == volume }"},
        },
    },

    # ── L-System SOP: Geometry tab (generations, step size, thickness, angle, gravity, seed) + Rules tab
    "PCG_LSystem": {
        "order": ["generations", "step", "step_scale", "width", "width_scale",
                  "angle", "angle_variance", "gravity", "rand_seed", "max_symbols",
                  "premise", "rules"],
        "inputs": {
            "generations": {"folder": "Geometry", "label": "Generations"},
            "step": {"folder": "Geometry", "label": "Step Size", "sep": True},
            "step_scale": {"folder": "Geometry", "label": "Step Size Scale"},
            "width": {"folder": "Geometry", "label": "Thickness"},
            "width_scale": {"folder": "Geometry", "label": "Thickness Scale"},
            "angle": {"folder": "Geometry", "label": "Angle", "sep": True},
            "angle_variance": {"folder": "Geometry", "label": "Variance",
                               "help": "Maximum random offset angle for each turn"},
            "gravity": {"folder": "Geometry", "label": "Gravity"},
            "rand_seed": {"folder": "Geometry", "label": "Random Seed"},
            "max_symbols": {"folder": "Geometry", "label": "Max Symbols", "sep": True,
                            "help": "Raises an error once the rewritten string exceeds this length"},
            "premise": {"folder": "Rules", "label": "Premise"},
            "rules": {"folder": "Rules", "label": "Rules",
                      "help": "One F=... per line; several rules for the same character, prefixed with (weight), are stochastic rules"},
        },
    },

    # ── Line SOP:Origin / Direction / Length / Points
    "PCG_Line": {
        "order": ["origin_x", "dx", "length", "points"],
        "inputs": {
            "dx": {"row": {"kind": "vector", "label": "Direction", "members": ["dx", "dy", "dz"]}},
            "length": {"label": "Length"},
            "points": {"label": "Points"},
        },
    },

    # ── Curve SOP: Primitive Type / Close Curve / Reverse / Order, point list last (written by drawing in the viewport)
    "PCG_Curve": {
        "order": ["prim_type", "closed", "reverse", "order", "points"],
        "inputs": {
            "prim_type": {"label": "Primitive Type",
                          "menu": {"polygon": "Polygon", "nurbs": "NURBS", "bezier": "Bezier"}},
            "closed": {"label": "Close Curve"},
            "reverse": {"label": "Reverse"},
            "order": {"label": "Order", "hide": "{ prim_type == polygon }"},
            "points": {"label": "Points", "sep": True,
                       "help": "One point x, y, z per line. With the node selected, click / drag in the viewport, Ctrl+click inserts a point, Delete removes points"},
        },
    },

    # ── Platonic Solids SOP:Solid Type / Center / Radius
    "PCG_PlatonicSolids": {
        "order": ["solid", "center_x", "radius"],
        "inputs": {
            "solid": {"label": "Solid Type",
                      "menu": {"tetrahedron": "Tetrahedron", "cube": "Cube",
                               "octahedron": "Octahedron",
                               "dodecahedron": "Dodecahedron",
                               "icosahedron": "Icosahedron",
                               "soccer_ball": "Soccer Ball"}},
            "radius": {"label": "Radius", "help": "Circumscribed sphere radius"},
        },
    },

    # ── PolyLoft SOP:Group / Form / Wrap / Keep Original
    "PCG_PolyLoft": {
        "order": ["group", "form", "wrap", "keep_original"],
        "inputs": {
            "form": {"label": "Form",
                     "menu": {"faces": "Faces", "cross_lines": "Cross Lines",
                              "grid_lines": "Grid Lines"}},
            "wrap": {"label": "Wrap Last to First"},
            # grid_lines always keeps the original curves; the toggle is not read
            "keep_original": {"label": "Keep Original Primitives",
                              "hide": "{ form == grid_lines }"},
        },
    },

    # ── Revolve SOP: Group / Surface Type / Origin / Direction / angles / Divisions /
    #    End Caps
    "PCG_Revolve": {
        "order": ["group", "surface", "origin_x", "axis_x", "start_angle",
                  "divisions", "end_caps", "reverse", "uv_attribute"],
        "inputs": {
            "surface": {"label": "Surface Type",
                        "menu": {"quads": "Quadrilaterals", "triangles": "Triangles"}},
            "origin_x": {"row": {"label": "Origin"}, "sep": True},
            "axis_x": {"row": {"label": "Direction"}},
            "start_angle": {"row": {"kind": "vector",
                                    "members": ["start_angle", "end_angle"],
                                    "label": "Start / End Angle"}},
            "divisions": {"label": "Divisions"},
            "end_caps": {"label": "End Caps", "sep": True,
                         "help": "Only capped when not revolved a full 360° and the cross section is closed"},
            "reverse": {"label": "Reverse Normals"},
            "uv_attribute": {"label": "UV Attribute", "sep": True,
                             "help": "Empty = no uv written"},
        },
    },

    # ── Skin SOP:Group / Connectivity / Output /(V Wrap)/ Keep Primitives,
    #    then NURBS V Order and grouping by N curves
    "PCG_Skin": {
        "order": ["group", "output", "connectivity", "v_wrap", "keep_primitives",
                  "auto_resample", "resample_to", "use_nurbs_opts", "v_order",
                  "use_every_n", "every_n"],
        "inputs": {
            "output": {"label": "Output Type",
                       "menu": {"polygons": "Polygons", "nurbs": "NURBS Surface"}},
            # skin(): the nurbs mode emits one surface prim and continues, connectivity / v_wrap not read
            "connectivity": {"label": "Connectivity",
                             "menu": {"quads": "Quadrilaterals", "triangles": "Triangles"},
                             "hide": "{ output == nurbs }"},
            "v_wrap": {"label": "V Wrap", "hide": "{ output == nurbs }",
                       "help": "Connects the last cross section back to the first"},
            "keep_primitives": {"label": "Keep Primitives"},
            "auto_resample": {"help": "Resamples automatically to match when cross sections have different point counts (Houdini raises an error)"},
            "resample_to": {"label": "Resample To",
                            "help": "0 = point count of the cross section with the most points"},
            "use_nurbs_opts": {"hide": "{ output == polygons }"},
            "v_order": {"label": "V Order", "hide": "{ output == polygons }"},
            "every_n": {"label": "Skin Every N Sections"},
        },
    },

    # ── Sweep 2.0: tabs Surface / Scale / Rotation / Cross Sections / UVs and Attributes
    "PCG_Sweep": {
        "order": ["group", "shape", "surface_type", "cols", "radius",
                  "end_caps", "end_cap_type", "cap_group",
                  "use_scale", "scale_start", "scale_end", "use_pscale",
                  "use_rotation", "up_x", "roll", "full_twists", "partial_twist",
                  "use_cross_opts", "cross_group", "reverse_cross",
                  "stretch_around_turns", "max_stretch",
                  "use_uv", "uv_attrib"],
        "inputs": {
            "group": {"label": "Curve Group", "folder": "Surface"},
            "shape": {"folder": "Surface", "label": "Surface Shape",
                      "menu": {"round_tube": "Round Tube", "square_tube": "Square Tube",
                               "ribbon": "Ribbon",
                               "second_input": "Second Input Cross Sections"}},
            "surface_type": {"folder": "Surface", "label": "Surface Type",
                             "menu": {"quads": "Quadrilaterals", "triangles": "Triangles",
                                      "alternating_triangles": "Alternating Triangles",
                                      "rows": "Rows", "columns": "Columns",
                                      "rows_and_columns": "Rows and Columns",
                                      "points": "Points"},
                             "help": "Rows: one polyline ring per cross section; Columns: polylines running along the backbone"},
            # _builtin_section: only the round tube reads cols (also read when second_input falls back to a tube without a cross section wired)
            "cols": {"folder": "Surface", "label": "Columns",
                     "hide": "{ shape == square_tube } { shape == ribbon }"},
            "radius": {"folder": "Surface", "label": "Radius",
                       "help": "Only used when the Second Input mode falls back to a round tube because no cross section is wired"},
            "end_caps": {"folder": "Surface"},
            "end_cap_type": {"folder": "Surface", "label": "End Cap Type",
                             "menu": {"single_polygon": "Single Polygon", "grid": "Grid"},
                             "disable": "{ end_caps == 0 }",
                             "help": "Grid: fills the cross section ring with a quad grid (cross section point count must be even, otherwise falls back to Single Polygon)"},
            "cap_group": {"folder": "Surface", "label": "End Cap Group"},
            "use_scale": {"folder": "Scale"},
            "scale_start": {"folder": "Scale",
                            "row": {"kind": "vector", "members": ["scale_start", "scale_end"],
                                    "label": "Scale Start / End"}},
            "use_pscale": {"folder": "Scale", "label": "Apply pscale Along Curve"},
            "use_rotation": {"folder": "Rotation"},
            "up_x": {"folder": "Rotation", "row": {"label": "Up Vector"}},
            "roll": {"folder": "Rotation", "label": "Roll"},
            "full_twists": {"folder": "Rotation", "label": "Full Twists"},
            "partial_twist": {"folder": "Rotation", "label": "Partial Twist"},
            "use_cross_opts": {"folder": "Cross Sections"},
            # cross_group only selects cross sections from the second input in the second_input mode
            "cross_group": {"folder": "Cross Sections", "label": "Cross Section Group",
                            "hide": "{ shape != second_input }"},
            "reverse_cross": {"folder": "Cross Sections",
                              "label": "Reverse Cross Sections"},
            "stretch_around_turns": {"folder": "Cross Sections",
                                     "label": "Stretch Around Turns"},
            "max_stretch": {"folder": "Cross Sections", "label": "Max Stretch"},
            "use_uv": {"folder": "UVs and Attributes", "label": "Compute UVs"},
            "uv_attrib": {"folder": "UVs and Attributes", "label": "UV Attribute"},
        },
    },

    # ── Torus SOP: Orientation / Radius (two) / Center / Rows / Columns
    "PCG_Torus": {
        "order": ["plane", "radius", "rows", "cols", "center_x"],
        "inputs": {
            "plane": {"label": "Orientation", "menu": dict(_PLANE)},
            "radius": {"row": {"kind": "vector", "members": ["radius", "section_radius"],
                               "label": "Radius"},
                       "help": "First is the major radius, second the cross-section radius"},
            "rows": {"label": "Rows", "sep": True,
                     "help": "Segments around the cross section (segments, not points, unlike Grid / Tube)"},
            "cols": {"label": "Columns", "help": "Segments around the major circle"},
        },
    },

    # ── Volume SOP: Name / Initial Value / type, then Center / Size / resolution
    "PCG_Volume": {
        "order": ["name", "value", "fog", "center_x", "size_x", "voxel_size",
                  "res_x", "padding"],
        "inputs": {
            "name": {"label": "Name"},
            "value": {"label": "Initial Value"},
            "fog": {"label": "Fog Volume", "help": "Off = SDF"},
            "center_x": {"row": {"label": "Center"}, "sep": True,
                         "help": "With the bound input wired, Center / Size are not used; its bounding box is used instead"},
            "size_x": {"row": {"label": "Size"}},
            "voxel_size": {"label": "Voxel Size", "sep": True,
                           "help": "When > 0, resolution is derived from extent / voxel size and Resolution is not used"},
            "res_x": {"row": {"label": "Resolution"}, "disable": "{ voxel_size > 0 }"},
            "padding": {"label": "Bounds Padding",
                        "help": "Only expands the bounding box when the bound input is wired"},
        },
    },

    # ── Group Promote SOP (the edge group part): Group / Conversion / New Name
    "PCG_EdgeGroupPromote": {
        "order": ["source", "direction", "target", "interior_only"],
        "inputs": {
            "source": {"label": "Group"},
            "direction": {"label": "Conversion",
                          "menu": {"edge->point": "Edges to Points",
                                   "edge->prim": "Edges to Primitives",
                                   "point->edge": "Points to Edges",
                                   "prim->edge": "Primitives to Edges"}},
            "target": {"label": "New Name", "sep": True,
                       "help": "Empty = use the original group name"},
            # run(): only the prim->edge mode passes it down
            "interior_only": {"label": "Interior Edges Only",
                              "hide": '{ direction != "prim->edge" }'},
        },
    },

    # ── Group Delete: one field per group class + Delete Unselected
    "PCG_GroupDelete": {
        "order": ["point", "vertex", "prim", "edge", "delete_non_selected"],
        "inputs": {
            "point": {"label": "Point Groups"},
            "vertex": {"label": "Vertex Groups"},
            "prim": {"label": "Primitive Groups"},
            "edge": {"label": "Edge Groups"},
            "delete_non_selected": {"label": "Delete Unselected", "sep": True,
                                    "help": "Leaving a field empty = that class is untouched (does not mean select all even when inverted)"},
        },
    },

    # ── The edge part of Group Create: Group Name / Initial Merge / Base Group, rule sections below
    "PCG_GroupEdges": {
        "order": ["name", "merge", "base", "use_angle", "min_angle", "max_angle",
                  "use_length", "min_length", "max_length", "unshared",
                  "use_random", "rand_seed", "percent"],
        "inputs": {
            "name": {"label": "Group Name"},
            "merge": {"label": "Initial Merge", "menu": dict(_MERGE)},
            "base": {"label": "Base Group"},
            "use_angle": {"label": "Edge Angle"},
            "min_angle": {"label": "Min Edge Angle"},
            "max_angle": {"label": "Max Edge Angle"},
            "use_length": {"label": "Edge Length"},
            "min_length": {"row": {"kind": "vector",
                                   "members": ["min_length", "max_length"],
                                   "label": "Length Range"}},
            # The section only holds itself: turned into a plain toggle row
            "unshared": {"section": None, "gate": None, "label": "Unshared Edges",
                         "sep": True},
            "rand_seed": {"label": "Global Seed"},
            "percent": {"label": "Percent"},
        },
    },

    # ── Group Expand SOP: Group Type / Base Group / Output Group / steps, Falloff section
    "PCG_GroupExpand": {
        "order": ["cls", "group", "output_group", "mode", "metric", "radius",
                  "output_falloff", "falloff_attribute"],
        "inputs": {
            "cls": {"label": "Group Type",
                    "menu": {"point": "Points", "prim": "Primitives"}},
            "group": {"label": "Base Group"},
            "output_group": {"label": "Output Group"},
            "mode": {"label": "Operation", "sep": True,
                     "menu": {"expand": "Expand", "shrink": "Shrink"}},
            "metric": {"label": "Measure",
                       "menu": {"steps": "Topology Steps",
                                "distance": "Edge Distance (Geodesic)"}},
            "radius": {"label": "Steps / Distance",
                       "help": "For Topology Steps, the number of edges to hop; for Edge Distance, the accumulated length along edges"},
            "output_falloff": {"label": "Output Falloff"},
            "falloff_attribute": {"label": "Falloff Attribute"},
        },
    },

    # ── Group Find Path SOP: Points / Mode, shortest path options, output group name last
    "PCG_GroupFindPath": {
        "order": ["points", "mode", "close", "avoid_self_intersection", "use_length",
                  "cost_attribute", "cost_weight", "collision_group", "contain_within_collision",
                  "group_name"],
        "inputs": {
            "points": {"label": "Base Group",
                       "help": "Point numbers (in order) or a point group"},
            "mode": {"label": "Path Type",
                     "menu": {"shortest_path": "Paths through Each Base Group Element in Order",
                              "boundary_loop": "Boundary Loop (PCG)",
                              "start_end_pairs": "Paths between Start/End Pairs in Base Group"}},
            # group_find_path: the boundary_loop branch does not read the ones below
            "close": {"label": "Close Path", "hide": "{ mode == boundary_loop }"},
            "avoid_self_intersection": {"label": "Avoid Self Intersection",
                                        "hide": "{ mode == boundary_loop }"},
            "use_length": {"label": "Use Edge Length as Cost",
                           "hide": "{ mode == boundary_loop }"},
            "cost_attribute": {"label": "Point Cost Attribute",
                               "hide": "{ mode == boundary_loop }"},
            "cost_weight": {"label": "Cost Weight",
                            "hide": "{ mode == boundary_loop }",
                            "disable": '{ cost_attribute == "" }'},
            "collision_group": {"label": "Collision Group", "sep": True,
                                "hide": "{ mode == boundary_loop }"},
            "contain_within_collision": {"label": "Contain within Collision Group",
                                         "hide": "{ mode == boundary_loop }",
                                         "disable": '{ collision_group == "" }'},
            "group_name": {"label": "Group Name", "sep": True,
                           "help": "Written as an edge group, plus a point group of the same name"},
        },
    },

    # ── Group from Attribute Boundary SOP: attribute class / attribute / tolerance, output group type and name last
    "PCG_GroupFromAttribBoundary": {
        "order": ["attribute_class", "attribute", "tolerance", "include_unshared",
                  "group_type", "group_name"],
        "inputs": {
            "attribute_class": {"label": "Attribute Class",
                                "menu": {"prim": "Primitive", "vertex": "Vertex",
                                         "point": "Point"}},
            "attribute": {"label": "Attribute"},
            "tolerance": {"label": "Tolerance", "help": "How different numeric attributes must be to count as different"},
            "include_unshared": {"label": "Include Unshared Edges"},
            "group_type": {"label": "Group Type", "sep": True,
                           "menu": {"edges": "Edges", "points": "Points",
                                    "prims": "Primitives"}},
            "group_name": {"label": "Group Name"},
        },
    },

    # ── Bounding Object of the Group SOP: Group Name / Entity / Invert
    "PCG_GroupInside": {
        "order": ["group_name", "cls", "invert", "ray_directions"],
        "inputs": {
            "group_name": {"label": "Group Name"},
            "cls": {"label": "Entity", "menu": {"point": "Points", "prim": "Primitives"}},
            "invert": {"label": "Invert"},
            "ray_directions": {"label": "Ray Directions", "sep": True,
                               "help": "Several oblique rays vote on inside / outside; 1 is fastest, 3 is most robust (no misclassification on grazing hits)"},
        },
    },

    # ── Group Promote SOP: Group / Convert From→To (one dropdown here) / New Name / Keep Original,
    #    then the boundary toggles and Entirely Contained / Sharing an Edge, Output as Attribute last
    "PCG_GroupPromote": {
        "order": ["name", "direction", "new_name", "keep_original",
                  "only_boundary", "include_unshared", "include_curve_unshared",
                  "only_full", "share_edge", "as_attribute"],
        "inputs": {
            "name": {"label": "Group"},
            "direction": {"label": "Convert From / To",
                          "menu": {"point_to_prim": "Points to Primitives",
                                   "prim_to_point": "Primitives to Points",
                                   "point_to_edge": "Points to Edges",
                                   "point_to_vertex": "Points to Vertices",
                                   "prim_to_edge": "Primitives to Edges",
                                   "prim_to_vertex": "Primitives to Vertices",
                                   "edge_to_point": "Edges to Points",
                                   "edge_to_prim": "Edges to Primitives",
                                   "edge_to_vertex": "Edges to Vertices",
                                   "vertex_to_point": "Vertices to Points",
                                   "vertex_to_prim": "Vertices to Primitives",
                                   "vertex_to_edge": "Vertices to Edges",
                                   "prim_to_prim": "Primitives to Primitives"}},
            "new_name": {"label": "New Name", "help": "Empty = use the original group name"},
            "keep_original": {"label": "Keep Original Group",
                              "help": "Off by default in Houdini; on by default here (this node never deleted the original group before)"},
            # promote(): with only_boundary on it goes through boundary() and does not read only_full / share_edge;
            # with it off it goes through convert() and does not read the two unshared toggles
            "only_boundary": {"label": "Include Only Elements on the Boundary", "sep": True,
                              "help": "Only supports starting from primitive groups (Primitives to ...)"},
            "include_unshared": {"label": "Include Unshared Edges",
                                 "disable": "{ only_boundary == 0 }"},
            "include_curve_unshared": {"label": "Include All Unshared Curve Edges",
                                       "disable": "{ only_boundary == 0 }"},
            # convert(): only_full is only read for these three directions, share_edge only for point → prim
            "only_full": {"label": "Include Only Elements Entirely Contained in Original Group",
                          "sep": True,
                          "hide": "{ direction != point_to_prim direction != point_to_edge "
                                  "direction != edge_to_prim }",
                          "disable": "{ only_boundary == 1 }",
                          "help": "Off by default in Houdini; on by default here (previously point → primitive always required all points)"},
            "share_edge": {"label": "Include Only Primitives Sharing an Edge with Original Group",
                           "hide": "{ direction != point_to_prim }",
                           "disable": "{ only_boundary == 1 }"},
            "as_attribute": {"label": "Output as Integer Attribute", "sep": True,
                             "help": "Written as a 0/1 integer attribute, no group created; not supported when the target is Edges"},
        },
    },

    # ── Partition SOP: Entity / attribute / Rule
    "PCG_Partition": {
        "order": ["attribute_class", "attribute", "rule"],
        "inputs": {
            "attribute_class": {"label": "Entity",
                                "menu": {"prim": "Primitives", "point": "Points",
                                         "vertex": "Vertices"}},
            "attribute": {"label": "Attribute"},
            "rule": {"label": "Rule", "help": "$ATTR is replaced by the attribute value; one group per distinct value"},
        },
    },

    # ── Heightfield from Image (this plugin's own node): Size / Height / Resolution
    "PCG_HeightfieldFromImage": {
        "order": ["size_x", "height", "resolution"],
        "inputs": {
            "size_x": {"row": {"kind": "vector", "members": ["size_x", "size_z"],
                               "label": "Size"},
                       "help": "Side lengths along X / Z; the mesh lies in the ZX plane"},
            "height": {"label": "Height Scale", "help": "Brightness (RGB mean) × this value = height"},
            "resolution": {"label": "Grid Resolution", "sep": True,
                           "help": "Points per side"},
        },
    },

    # ── Iteration settings of Block Begin + Block End: Method / Iteration Method / Piece Elements /
    #    Piece Attribute / Iterations, Max Iterations and ☑ Single Pass last
    "PCG_ForEachBegin": {
        "order": ["method", "iterate_over", "piece_elements", "piece_attribute",
                  "iterations", "group", "max_iterations", "use_single_pass",
                  "single_pass"],
        "inputs": {
            "method": {"label": "Method",
                       "menu": {"fetch_piece": "Extract Piece or Point",
                                "fetch_feedback": "Fetch Feedback",
                                "fetch_input": "Fetch Input"}},
            "iterate_over": {"label": "Iteration Method",
                             "menu": {"pieces": "By Pieces (Attribute)",
                                      "primitives": "By Primitives",
                                      "points": "By Points",
                                      "connectivity": "By Connectivity",
                                      "count": "By Count"}},
            # pieces.plan: the primitives / points modes force the element class, count returns directly
            "piece_elements": {"label": "Piece Elements",
                               "menu": {"primitives": "Primitives", "points": "Points"},
                               "hide": "{ iterate_over != pieces iterate_over != connectivity }"},
            "piece_attribute": {"label": "Piece Attribute",
                                "hide": "{ iterate_over != pieces }"},
            "iterations": {"label": "Iterations", "hide": "{ iterate_over != count }"},
            "group": {"label": "Group", "hide": "{ iterate_over == count }"},
            "max_iterations": {"label": "Max Iterations", "sep": True},
            # Houdini: ☑ Single Pass [0], not a collapsible section
            "use_single_pass": {"section": None, "gate": None,
                                "in_toggle": "single_pass"},
            "single_pass": {"section": None, "toggle": "use_single_pass",
                            "label": "Single Pass"},
        },
    },

    # ── Block End:Gather Method
    "PCG_ForEachEnd": {
        "order": ["gather"],
        "inputs": {
            "gather": {"label": "Gather Method",
                       "menu": {"merge": "Merge Each Iteration",
                                "feedback": "Feedback Each Iteration"}},
        },
    },

    # ── Per-frame loop begin (this plugin's own node, approximates SOP Solver + frame range): Method / frame range / FPS
    "PCG_ForEachFrameBegin": {
        "order": ["method", "start", "frames", "fps", "max_iterations",
                  "use_single_pass", "single_pass"],
        "inputs": {
            "method": {"label": "Method",
                       "menu": {"input": "Fetch Input (Each Frame)",
                                "feedback": "Fetch Feedback (Solver)"}},
            "start": {"label": "Start Frame", "sep": True},
            "frames": {"label": "Frames"},
            "fps": {"label": "FPS"},
            "max_iterations": {"label": "Max Iterations", "sep": True},
            "single_pass": {"label": "Single Pass"},
        },
    },

    # ── Per-frame loop end
    "PCG_ForEachFrameEnd": {
        "order": ["merge_output"],
        "inputs": {
            "merge_output": {"label": "Output Merged Geometry",
                             "help": "Merges all frames into one output on the merged port (off by default)"},
        },
    },

    # ── Geo Sequence Pick
    "PCG_GeoSequencePick": {
        "order": ["index"],
        "inputs": {
            "index": {"label": "Index", "help": "Wraps around beyond the length"},
        },
    },

    # ── Retime SOP: Method / frame count, then Speed + Start or a keyframe channel depending on the mode, interpolation last
    "PCG_Retime": {
        "order": ["mode", "frames", "speed", "start", "keys", "channel_interp",
                  "extrapolate", "interp", "loop"],
        "inputs": {
            "mode": {"label": "Retime Method",
                     "menu": {"speed": "Speed", "length": "Output Length",
                              "channel": "Time Warp Channel"}},
            "frames": {"label": "Output Frames", "help": "0 = automatic (from speed / source length)"},
            "speed": {"label": "Speed", "hide": "{ mode != speed }", "sep": True},
            # The length mode only reads start when frames == 1; the channel mode reads none of them
            "start": {"label": "Start Frame", "hide": "{ mode == channel }"},
            "keys": {"label": "Time Warp Keys", "hide": "{ mode != channel }", "sep": True,
                     "help": "output_frame:source_frame ..., e.g. 0:0  6:12  14:12  24:23"},
            "channel_interp": {"label": "Key Interpolation", "hide": "{ mode != channel }",
                               "menu": {"constant": "Constant", "linear": "Linear",
                                        "ease": "Ease", "easein": "Ease In",
                                        "easeout": "Ease Out", "cubic": "Cubic",
                                        "quintic": "Quintic"}},
            "extrapolate": {"label": "Extrapolation", "hide": "{ mode != channel }",
                            "menu": {"hold": "Hold", "linear": "Linear",
                                     "cycle": "Cycle", "cycleoffset": "Cycle with Offset",
                                     "mirror": "Mirror"}},
            "interp": {"label": "Interpolation", "sep": True,
                       "menu": {"hold": "Integer Frames (Hold)",
                                "blend": "Blend Subframes"},
                       "help": "Blend requires the same topology on all frames"},
            "loop": {"label": "Cycle Source", "help": "Source frame numbers wrap around when out of range instead of clamping to the ends"},
        },
    },
}
