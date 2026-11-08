"""
Parameter panel specs for group g1 (format: see the docstring at the top of panel_specs.py).

Transform / Box / Grid / Sphere / Tube / Blast / Group Create / Group Combine /
Normal / Connectivity, matched against SideFX's official panels. hide / disable conditions follow whether the node code
(nodes.py / nodes_sop2.py + geo/) actually reads the parameter.
"""

_GROUP_TYPE = {"point": "Points", "prim": "Primitives",
               "vertex": "Vertices", "edge": "Edges"}

SPECS = {
    # ── Transform SOP:Group / Transform Order / Rotate Order / Translate / Rotate / Scale /
    #    Shear / Uniform Scale / Pivot Translate / Pivot Rotate / Invert Transformation
    "PCG_Transform": {
        "order": ["group", "xform_order", "rotate_order", "tx", "rx", "sx", "shear_xy",
                  "uniform_scale", "px", "prx", "invert"],
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
            "group": {"label": "Group",
                      "help": "Group Type is fixed to Guess: first tried as a point group / point attribute expression; "
                              "if nothing matches on points, as a primitive group (takes those primitives' points)"},
            "tx": {"sep": True},
            "rx": {"help": "In degrees; the three angles are applied in Rotate Order"},
            "shear_xy": {"row": {"kind": "vector", "label": "Shear",
                                 "members": ["shear_xy", "shear_xz", "shear_yz"]},
                         "help": "XY / XZ / YZ: x += xy·y + xz·z, y += yz·z (applied right after scale)"},
            "uniform_scale": {"label": "Uniform Scale"},
            "px": {"row": {"kind": "vector", "label": "Pivot Translate",
                           "members": ["px", "py", "pz"]}, "sep": True,
                   "help": "Scale / rotate happen around this point"},
            "prx": {"row": {"kind": "vector", "label": "Pivot Rotate",
                            "members": ["prx", "pry", "prz"]},
                    "help": "Scale / rotate happen in a frame rotated by these angles"},
            "invert": {"label": "Invert Transformation", "sep": True},
        },
    },

    # ── Box SOP:Primitive Type / Size / Center / Rotate / Uniform Scale / Axis Divisions
    "PCG_Box": {
        "order": ["prim_type", "size_x", "cx", "rx", "uniform_scale", "div_x"],
        "inputs": {
            "prim_type": {"label": "Primitive Type",
                          "menu": {"polygon": "Polygon", "points": "Points"},
                          "help": "Points: only the lattice points on the shell, no primitives"},
            "rx": {"row": {"kind": "vector", "label": "Rotate", "members": ["rx", "ry", "rz"]}},
            "uniform_scale": {"label": "Uniform Scale"},
            "div_x": {"row": {"label": "Axis Divisions"}, "sep": True,
                      "help": "Number of points per axis (2 = one cell per face), same as Houdini"},
        },
    },

    # ── Grid SOP:Connectivity / Orientation / Size / Center / Rotate / Rows / Columns
    "PCG_Grid": {
        "order": ["connectivity", "plane", "size_x", "center_x", "rx", "rows", "cols"],
        "inputs": {
            "connectivity": {"label": "Connectivity",
                             "menu": {"quadrilaterals": "Quadrilaterals", "rows": "Rows",
                                      "columns": "Columns", "rows_and_columns": "Rows and Columns",
                                      "triangles": "Triangles",
                                      "alternating_triangles": "Alternating Triangles",
                                      "points": "Points"},
                             "help": "Rows / Columns: one polyline per row / per column; Points: points only"},
            "plane": {"label": "Orientation",
                      "menu": {"zx": "ZX Plane", "xy": "XY Plane", "yz": "YZ Plane"}},
            "size_x": {"row": {"kind": "vector", "members": ["size_x", "size_z"],
                               "label": "Size"},
                       "help": "First is the column direction, second the row direction; ZX plane = X / Z, XY plane = X / Y, "
                               "YZ plane = Z / Y"},
            "rx": {"row": {"kind": "vector", "label": "Rotate", "members": ["rx", "ry", "rz"]}},
            "rows": {"label": "Rows", "sep": True},
            "cols": {"label": "Columns", "help": "Number of points, not cells (same as Houdini)"},
        },
    },

    # ── Sphere SOP:Primitive Type / Radius / Center / Rotate / Uniform Scale / Orientation /
    #    Frequency(Polygon)/ Rows / Columns(Polygon Mesh)
    "PCG_Sphere": {
        "order": ["prim_type", "radius_x", "center_x", "rx", "radius", "orientation",
                  "frequency", "rows", "cols"],
        "inputs": {
            "prim_type": {"label": "Primitive Type",
                          "menu": {"polygon_mesh": "Polygon Mesh", "polygon": "Polygon"},
                          "help": "Polygon Mesh: UV (lat-long) sphere (Rows × Columns); "
                                  "Polygon: subdivided icosahedron (Frequency), evenly sized triangles, no poles"},
            "radius_x": {"row": {"kind": "vector", "label": "Radius",
                                 "members": ["radius_x", "radius_y", "radius_z"]}},
            "rx": {"row": {"kind": "vector", "label": "Rotate", "members": ["rx", "ry", "rz"]}},
            "radius": {"label": "Uniform Scale"},
            "orientation": {"label": "Orientation",
                            "menu": {"y": "Y Axis", "x": "X Axis", "z": "Z Axis"},
                            "help": "Axis the poles point along"},
            "frequency": {"label": "Frequency", "sep": True,
                          "hide": "{ prim_type != polygon }",
                          "help": "Segments per edge: 20·f² triangles"},
            "rows": {"label": "Rows", "sep": True, "hide": "{ prim_type != polygon_mesh }",
                     "help": "Number of points along latitude (including the poles, one point each)"},
            "cols": {"label": "Columns", "hide": "{ prim_type != polygon_mesh }"},
        },
    },

    # ── Tube SOP:Orientation / End Caps / Center / Rotate / Radius / Radius Scale / Height /
    #    Rows / Columns
    "PCG_Tube": {
        "order": ["orientation", "caps", "center_x", "rx", "radius1", "radius_scale", "height",
                  "rows", "cols"],
        "inputs": {
            "orientation": {"label": "Orientation",
                            "menu": {"y": "Y Axis", "x": "X Axis", "z": "Z Axis"}},
            "caps": {"label": "End Caps"},
            "rx": {"row": {"kind": "vector", "label": "Rotate", "members": ["rx", "ry", "rz"]}},
            "radius1": {"row": {"kind": "vector", "members": ["radius1", "radius2"],
                                "label": "Radius"},
                        "sep": True,
                        "help": "First is the bottom radius, second the top radius"},
            "radius_scale": {"label": "Radius Scale"},
            "height": {"label": "Height"},
            "rows": {"label": "Rows", "sep": True},
            "cols": {"label": "Columns"},
        },
    },

    # ── Blast SOP:Group / Group Type / Delete Non Selected
    "PCG_Blast": {
        "order": ["group", "cls", "keep_selected"],
        "inputs": {
            "group": {"label": "Group", "help": "Empty = delete nothing (even with Delete Non "
                                                "Selected on)"},
            "cls": {"label": "Group Type",
                    "menu": {"point": "Points", "prim": "Primitives"}},
            "keep_selected": {"label": "Delete Non Selected"},
        },
    },

    # ── Group Create SOP: Group Name / Group Type / Initial Merge, then five tabs
    #    Base Group / Keep in Bounding Regions / Keep by Normals / Include by Edges
    #    / Keep by Random Chance; each tab's Enable is the toggle on its section header
    "PCG_GroupCreate": {
        "order": ["name", "cls", "merge", "base",
                  "use_bbox", "sx", "cx", "bbox_partial",
                  "use_normal", "dir_x", "spread", "both_dirs",
                  "use_edges", "edge_combine", "use_angle", "min_angle", "max_angle",
                  "unshared",
                  "use_random", "rand_seed", "percent"],
        "inputs": {
            "name": {"label": "Group Name"},
            "cls": {"label": "Group Type",
                    "menu": {"point": "Points", "prim": "Primitives",
                             "vertex": "Vertices"}},
            "merge": {"label": "Initial Merge",
                      "menu": {"replace": "Replace Existing",
                               "union": "Union with Existing",
                               "intersect": "Intersect with Existing",
                               "subtract": "Subtract from Existing"},
                      "help": "How to merge with an existing group of the same name; with no such group, all behave like Replace"},
            # Base Group tab: Houdini has an Enable toggle; here empty = select all
            "base": {"label": "Base Group", "folder": "Base Group",
                     "help": "Starting set, empty = unrestricted (starts from the empty set when only Include by Edges is on); "
                             "the Keep tabs intersect with it, Include by Edges is unioned in last"},
            # Keep in Bounding Regions (Bounding Box only)
            "use_bbox": {"label": "Enable", "folder": "Keep in Bounding Regions"},
            "sx": {"folder": "Keep in Bounding Regions",
                   "row": {"kind": "vector", "members": ["sx", "sy", "sz"],
                           "label": "Size"}},
            "cx": {"folder": "Keep in Bounding Regions",
                   "row": {"label": "Center"}},
            "sy": {"folder": "Keep in Bounding Regions"},
            "sz": {"folder": "Keep in Bounding Regions"},
            "cy": {"folder": "Keep in Bounding Regions"},
            "cz": {"folder": "Keep in Bounding Regions"},
            "bbox_partial": {"folder": "Keep in Bounding Regions",
                             "label": "Include Partially Contained Entities",
                             "hide": "{ cls == point }",
                             "help": "A primitive / vertex counts if any one of its points is inside the box (off: all points must be inside)"},
            # Keep by Normals
            "use_normal": {"label": "Enable", "folder": "Keep by Normals"},
            "dir_x": {"folder": "Keep by Normals", "row": {"label": "Direction"}},
            "dir_y": {"folder": "Keep by Normals"},
            "dir_z": {"folder": "Keep by Normals"},
            "spread": {"folder": "Keep by Normals", "label": "Spread Angle",
                       "help": "180 = include all"},
            "both_dirs": {"folder": "Keep by Normals",
                          "label": "Include Normals Matching Opposite Direction"},
            # Include by Edges
            "use_edges": {"label": "Enable", "folder": "Include by Edges"},
            "edge_combine": {"folder": "Include by Edges", "label": "Combine",
                             "menu": {"include": "Include (Union)",
                                      "keep": "Keep (Intersect)"},
                             "help": "Include works as in Houdini: edges picked by the edge rules join the group regardless of other tabs; "
                                     "Keep is an extra of this plugin, intersected with the previous result"},
            # Houdini has two toggles, ☑ Min Edge Angle / ☑ Max Edge Angle; merged into one here
            "use_angle": {"folder": "Include by Edges", "label": "Edge Angle",
                          "help": "Edges whose adjacent primitives' normals differ by Min ~ Max degrees; selected independently of Unshared, then unioned"},
            "min_angle": {"folder": "Include by Edges", "label": "Min Edge Angle",
                          "disable": "{ use_angle == 0 }"},
            "max_angle": {"folder": "Include by Edges", "label": "Max Edge Angle",
                          "disable": "{ use_angle == 0 }"},
            "unshared": {"folder": "Include by Edges", "label": "Unshared Edges",
                         "help": "Boundary edges (only one adjacent primitive); unioned with the angle rule"},
            # Keep by Random Chance
            "use_random": {"label": "Enable", "folder": "Keep by Random Chance"},
            "rand_seed": {"folder": "Keep by Random Chance", "label": "Global Seed"},
            "percent": {"folder": "Keep by Random Chance", "label": "Percent"},
        },
    },

    # ── Group Combine SOP: each line is Group Type / Group (output) = expression;
    #    Houdini uses an A op B multiparm; we use a one-line expression
    "PCG_GroupCombine": {
        "order": ["group_type", "output_group", "expression"],
        "inputs": {
            "group_type": {"label": "Group Type", "menu": dict(_GROUP_TYPE)},
            "output_group": {"label": "Group"},
            "expression": {"label": "Expression",
                           "help": "| union  & intersect  - difference  ^ symmetric difference  ! negate, parentheses allowed; "
                                   "group names may use wildcards, * = all"},
        },
    },

    # ── Normal SOP:Group / Group Type / Override Normal / Compute Normals,
    #    Add Normals to / Cusp Angle (only matters for Vertices) / Weighting, then three toggles
    "PCG_Normal": {
        "order": ["group", "group_type", "normal_name", "compute_normals", "add_to",
                  "cusp_angle", "weighting", "keep_zero", "make_unit", "reverse"],
        "inputs": {
            "group": {"label": "Group",
                      "help": "With Group Type = Guess, parsed as the element class chosen in Add Normals to",
                      "hide": "{ add_to == detail }"},
            "group_type": {"label": "Group Type",
                           "menu": {"guess": "Guess from Group", "point": "Points",
                                    "vertex": "Vertices", "prim": "Primitives",
                                    "edge": "Edges"},
                           "hide": "{ add_to == detail }"},
            "normal_name": {"label": "Override Normal", "help": "Attribute to write to; empty = N"},
            "compute_normals": {"label": "Compute Normals", "sep": True},
            "add_to": {"label": "Add Normals to",
                       "menu": {"point": "Points", "vertex": "Vertices",
                                "prim": "Primitives", "detail": "Detail"}},
            # normal_sop(): with compute off, compute_normals is not called, so these two are not read
            "cusp_angle": {"label": "Cusp Angle", "hide": "{ add_to != vertex }",
                           "disable": "{ compute_normals == 0 }"},
            "weighting": {"label": "Weighting Method",
                          "menu": {"by_face_area": "By Face Area",
                                   "each_vertex_equally": "Each Vertex Equally",
                                   "by_vertex_angle": "By Vertex Angle"},
                          "hide": "{ add_to == prim } { add_to == detail }",
                          "disable": "{ compute_normals == 0 }",
                          "help": "How the normals of the primitives around a point are averaged"},
            "keep_zero": {"label": "Keep Original Normal Where Computed Normal Is Zero",
                          "sep": True, "disable": "{ compute_normals == 0 }"},
            "make_unit": {"label": "Make Normals Unit Length",
                          "disable": "{ compute_normals == 1 }"},
            "reverse": {"label": "Reverse Normals"},
        },
    },

    # ── Connectivity SOP:Connectivity Type / Attribute
    "PCG_Connectivity": {
        "order": ["cls", "attribute"],
        "inputs": {
            "cls": {"label": "Connectivity Type",
                    "menu": {"point": "Point", "prim": "Primitive"}},
            "attribute": {"label": "Attribute",
                          "help": "Integer piece number, written to the class chosen in Connectivity Type"},
        },
    },
}
