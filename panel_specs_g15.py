"""
Panel specs for group g15 (format: see the docstring at the top of panel_specs.py): the nodes added after the code
review (pcg121, nodes_sop3.py) and Copy to Points' Pack and Instance. Labels follow Houdini's Distance from
Geometry / Distance along Geometry / Path Deform / PolyWire / Pack / Unpack panels.
"""


def _m(*pairs):
    return dict(zip(pairs[0::2], pairs[1::2]))


RAMP_MODES = _m("linear", "Linear", "smooth", "Smooth", "constant", "Constant")


def _mask():
    return {
        "output_mask": {"label": "Output Mask", "section": "Mask"},
        "mask_attribute": {"label": "Mask Attribute", "section": "Mask", "disable": "{ output_mask == 0 }"},
        "mask_radius": {"label": "Mask Radius", "section": "Mask", "disable": "{ output_mask == 0 }",
                        "help": "Distance where the ramp reaches its right end"},
        "mask_ramp": {"label": "Mask Ramp", "section": "Mask", "disable": "{ output_mask == 0 }",
                      "help": "position:value pairs over distance / Mask Radius (0..1); default 1 at the start fading to 0"},
        "ramp_mode": {"label": "Interpolation", "section": "Mask", "menu": RAMP_MODES,
                      "disable": "{ output_mask == 0 }"},
    }


SPECS = {
    "PCG_DistanceFromGeometry": {
        "order": ["group", "reference_group", "metric", "distance_attribute", "use_max_distance", "max_distance",
                  "output_mask", "mask_attribute", "mask_radius", "mask_ramp", "ramp_mode"],
        "inputs": {
            "group": {"label": "Group"},
            "reference_group": {"label": "Reference Group"},
            "metric": {"label": "Distance Metric",
                       "menu": _m("surface", "Surface", "edges", "Edges", "points", "Points")},
            "distance_attribute": {"label": "Distance Attribute", "sep": True},
            "use_max_distance": {"label": "Max Distance"},
            "max_distance": {"label": "Max Distance", "disable": "{ use_max_distance == 0 }",
                             "help": "Farther points get this value; also bounds the search"},
            **_mask(),
        },
    },

    "PCG_DistanceAlongGeometry": {
        "order": ["start_points", "method", "heat_time", "distance_attribute", "use_max_distance", "max_distance",
                  "output_mask", "mask_attribute", "mask_radius", "mask_ramp", "ramp_mode"],
        "inputs": {
            "start_points": {"label": "Start Points"},
            "method": {"label": "Method", "menu": _m("geodesic", "Geodesic (Heat Method)", "edges", "Edges")},
            "heat_time": {"label": "Heat Time", "hide": "{ method != geodesic }",
                          "help": "Diffusion step in mean edge lengths squared; larger = smoother, less exact"},
            "distance_attribute": {"label": "Distance Attribute", "sep": True},
            "use_max_distance": {"label": "Max Distance"},
            "max_distance": {"label": "Max Distance", "disable": "{ use_max_distance == 0 }"},
            **_mask(),
        },
    },

    "PCG_PathDeform": {
        "order": ["group", "curve_group", "deform_axis", "stretch_to_curve", "scale", "offset", "offset_as_fraction",
                  "cross_scale", "roll", "twist", "up_mode", "up_x", "up_y", "up_z"],
        "inputs": {
            "group": {"label": "Group"},
            "curve_group": {"label": "Curve Group"},
            "deform_axis": {"label": "Deform Axis",
                            "menu": _m("+z", "+Z", "-z", "-Z", "+x", "+X", "-x", "-X", "+y", "+Y", "-y", "-Y")},
            "stretch_to_curve": {"label": "Stretch to Curve", "sep": True},
            "scale": {"label": "Scale Along Curve"},
            "offset": {"label": "Offset"},
            "offset_as_fraction": {"label": "Offset as Fraction of Length"},
            "cross_scale": {"label": "Cross Scale", "sep": True},
            "roll": {"label": "Roll"},
            "twist": {"label": "Twist"},
            "up_mode": {"label": "Up Vector", "sep": True,
                        "menu": _m("minimal_rotation", "Minimal Rotation", "constant", "Constant")},
            "up_x": {"row": {"kind": "vector", "members": ["up_x", "up_y", "up_z"], "label": "Up"}},
        },
    },

    "PCG_PolyWire": {
        "order": ["group", "radius", "radius_from", "divisions", "end_caps", "joints", "joint_angle",
                  "carry_attributes"],
        "inputs": {
            "group": {"label": "Group"},
            "radius": {"label": "Wire Radius", "disable": "{ radius_from != constant }"},
            "radius_from": {"label": "Radius From",
                            "menu": _m("constant", "Wire Radius", "width", "Point width (diameter)",
                                       "pscale", "Point pscale (radius)")},
            "divisions": {"label": "Divisions", "sep": True},
            "end_caps": {"label": "End Caps", "menu": _m("round", "Round", "flat", "Flat", "none", "None")},
            "joints": {"label": "Joint Spheres"},
            "joint_angle": {"label": "Joint Angle", "disable": "{ joints == 0 }",
                            "help": "Bends sharper than this inside a chain get a sphere too"},
            "carry_attributes": {"label": "Carry Point Attributes", "sep": True},
        },
    },

    "PCG_Thicken": {
        "order": ["group", "thickness", "side", "divisions", "front_group", "back_group", "side_group"],
        "inputs": {
            "group": {"label": "Group"},
            "thickness": {"label": "Thickness"},
            "side": {"label": "Side", "menu": _m("both", "Both (Centered)", "outward", "Outward", "inward", "Inward")},
            "divisions": {"label": "Divisions"},
            "front_group": {"label": "Front Group", "section": "Output Groups"},
            "back_group": {"label": "Back Group", "section": "Output Groups"},
            "side_group": {"label": "Side Group", "section": "Output Groups"},
        },
    },

    "PCG_CurveFillet": {
        "order": ["group", "points", "radius", "divisions", "limit_radius", "include_closed"],
        "inputs": {
            "group": {"label": "Group"},
            "points": {"label": "Corner Points"},
            "radius": {"label": "Radius", "sep": True},
            "divisions": {"label": "Divisions"},
            "limit_radius": {"label": "Limit Radius",
                             "help": "Shrink the arc where the neighbouring segments are too short for it"},
            "include_closed": {"label": "Include Closed Curves"},
        },
    },

    "PCG_Pack": {
        "order": ["group", "pack_by", "piece_attribute", "pivot"],
        "inputs": {
            "group": {"label": "Group"},
            "pack_by": {"label": "Pack By",
                        "menu": _m("piece_attribute", "Piece Attribute", "connectivity", "Connectivity",
                                   "all", "Everything (One Packed Primitive)")},
            "piece_attribute": {"label": "Piece Attribute", "hide": "{ pack_by != piece_attribute }"},
            "pivot": {"label": "Pivot",
                      "menu": _m("centroid", "Centroid", "bbox_center", "Bounding Box Center", "origin", "Origin",
                                 "bbox_min_y", "Bottom Center")},
        },
    },

    "PCG_Assemble": {
        "order": ["group", "name_attribute", "name_prefix", "create_packed", "pivot"],
        "inputs": {
            "group": {"label": "Group"},
            "name_attribute": {"label": "Name Attribute"},
            "name_prefix": {"label": "Output Prefix"},
            "create_packed": {"label": "Create Packed Geometry", "sep": True},
            "pivot": {"label": "Pivot", "disable": "{ create_packed == 0 }",
                      "menu": _m("centroid", "Centroid", "bbox_center", "Bounding Box Center", "origin", "Origin",
                                 "bbox_min_y", "Bottom Center")},
        },
    },

    "PCG_Unpack": {
        "order": ["group", "transfer_attributes"],
        "inputs": {
            "group": {"label": "Group"},
            "transfer_attributes": {"label": "Transfer Attributes"},
        },
    },
}
