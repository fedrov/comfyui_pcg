"""
Panel specs for group g3: Extract Centroid / Attribute Promote / Attribute Noise /
Attribute Randomize / Point Jitter / UV Project / UV Flatten / UV Layout /
Convert / Measure. Format: see the notes at the top of panel_specs.py.

The hide / disable conditions follow the branches where a parameter really takes effect in the node code (nodes.py run() + geo/
implementation), not a copy of Houdini.
"""

_NURBS_TYPES = ("nurbs_curve", "nurbs_surface", "bezier_curve", "bezier_surface")
_VOLUME_TYPES = ("volume_sdf", "volume_fog")


def _not_any(parm, toks):
    """{ parm != a parm != b ... }: true when the value is not in toks."""
    return "{ " + " ".join(f"{parm} != {t}" for t in toks) + " }"


def _any(parm, toks):
    """{ parm == a } { parm == b } ...: true when the value is in toks."""
    return " ".join(f"{{ {parm} == {t} }}" for t in toks)


# Convert: each of the three parameter sets only takes effect for one kind of target
_HIDE_SPLINE = _not_any("convert_to", _NURBS_TYPES)                 # non-spline targets
_HIDE_TESS = _any("convert_to", _NURBS_TYPES + _VOLUME_TYPES)        # non-polygon targets
_HIDE_VOLUME = _not_any("convert_to", _VOLUME_TYPES)                 # non-volume targets

_AA2_NOISE = {"value": "Value", "perlin": "Perlin", "simplex": "Simplex",
              "worley": "Worley Cellular F1", "worley_f2f1": "Worley Cellular F2-F1",
              "manhattan": "Manhattan Cellular F1",
              "manhattan_f2f1": "Manhattan Cellular F2-F1",
              "chebyshev": "Chebyshev Cellular F1",
              "chebyshev_f2f1": "Chebyshev Cellular F2-F1"}

# Attribute Randomize: these distributions do not read Min / Max
_RAND_NO_MIN = ("gaussian", "exponential", "lognormal", "cauchy", "custom_discrete",
                "inside_sphere")

_CLASS_MENU = {"point": "Point", "vertex": "Vertex", "prim": "Primitive",
               "detail": "Detail"}


SPECS = {
    # ── Extract Centroid SOP:Run Over → Piece Attribute / Piece Elements → Method
    #    → Output → Centroid Attribute / Transfer Attributes / Transfer Groups
    "PCG_ExtractCentroid": {
        "order": ["group", "run_over", "piece_attribute", "piece_elements",
                  "method", "output", "use_attrib_out", "attribute_name",
                  "use_transfer", "transfer_attributes", "transfer_groups"],
        "inputs": {
            "group": {},
            "run_over": {"label": "Run Over",
                         "menu": {"pieces": "Pieces", "primitives": "Primitives",
                                  "points": "Points",
                                  "connectivity": "Connectivity",
                                  "detail": "Detail"}},
            "piece_attribute": {"label": "Piece Attribute",
                                "hide": "{ run_over != pieces }"},
            # pieces.plan: the primitives / points modes force the element class; detail skips plan
            "piece_elements": {"label": "Piece Elements",
                               "menu": {"primitives": "Primitives",
                                        "points": "Points"},
                               "hide": "{ run_over != pieces run_over != connectivity }"},
            # With single-point pieces all three methods agree; with per-point pieces / connectivity, Bounding Box differs
            "method": {"label": "Method",
                       "menu": {"center_of_mass": "Center of Mass",
                                "bounding_box": "Bounding Box Center",
                                "average_position": "Average Position"},
                       "hide": "{ run_over == points }"},
            "output": {"label": "Output",
                       "menu": {"points": "Points", "attribute": "Attribute"},
                       "sep": True},
            # The attribute is only written with output=attribute; transfer only happens with output=points.
            # Houdini has a single row ☑ Centroid Attribute [centroid]; off = not written
            "use_attrib_out": {"section": None, "gate": None,
                               "in_toggle": "attribute_name",
                               "hide": "{ output != attribute }"},
            "attribute_name": {"section": None, "toggle": "use_attrib_out",
                               "label": "Centroid Attribute",
                               "hide": "{ output != attribute }"},
            "use_transfer": {"hide": "{ output != points }"},
            "transfer_attributes": {"label": "Transfer Attributes",
                                    "hide": "{ output != points }"},
            "transfer_groups": {"label": "Transfer Groups",
                                "hide": "{ output != points }"},
        },
    },

    # ── Attribute Promote SOP:Original Name / Original Class / New Class /
    #    ☑ Piece Attribute / Promotion Method / ☑ Change New Name / Delete Original
    "PCG_AttribPromote": {
        "order": ["original_name", "original_class", "new_class", "use_piece",
                  "piece_attribute", "method", "change_new_name", "new_name",
                  "delete_original"],
        "inputs": {
            "original_name": {"label": "Original Name"},
            "original_class": {"label": "Original Class", "menu": _CLASS_MENU},
            "new_class": {"label": "New Class", "menu": _CLASS_MENU},
            # Houdini has a single row "☑ Piece Attribute [name]"; promote() ignores pieces when the target is detail
            "use_piece": {"section": None, "gate": None,
                          "in_toggle": "piece_attribute",
                          "hide": "{ new_class == detail }"},
            "piece_attribute": {"section": None, "toggle": "use_piece",
                                "label": "Piece Attribute",
                                "hide": "{ new_class == detail }"},
            "method": {"label": "Promotion Method",
                       "menu": {"average": "Average", "maximum": "Maximum",
                                "minimum": "Minimum", "sum": "Sum",
                                "mode": "Mode", "median": "Median",
                                "sum_of_squares": "Sum of Squares",
                                "root_mean_square": "Root Mean Square",
                                "first_match": "First Match",
                                "last_match": "Last Match"}},
            "change_new_name": {"section": None, "gate": None,
                                "in_toggle": "new_name", "sep": True},
            "new_name": {"section": None, "toggle": "change_new_name",
                         "label": "New Name"},
            "delete_original": {"label": "Delete Original"},
        },
    },

    # ── Attribute Noise SOP: target attribute on top, then three tabs Noise Value / Noise Pattern /
    #    Animation; Remap Ramp and Bias / Gain live in Value Correction on the Noise Value tab
    "PCG_AttribNoise": {
        "order": [
            "group", "blend", "blend_attribute", "attribute_type", "attribute_names",
            "use_x", "use_y", "use_z",
            "attribute_class", "noise_along_vector", "vector_attribute",
            # Noise Value
            "range_values", "operation", "amplitude", "min_value", "max_value",
            "middle_value", "range_length",
            "use_remap_ramp", "remap_ramp", "ramp_mode",
            "use_value_correction", "bias", "gain", "gamma", "contrast",
            "use_clamp_min", "clamp_min", "use_clamp_max", "clamp_max",
            "make_unit_length", "recompute_normals",
            "post_absolute", "post_invert", "use_normalize", "normalize_min",
            "normalize_max",
            # Noise Pattern
            "noise_type", "location_attribute", "element_size_x",
            "element_size_y", "element_size_z", "offset_x", "offset_y",
            "offset_z", "rand_seed", "use_vexpression", "vexpression",
            "fractal", "octaves", "lacunarity", "roughness", "fractal_offset",
            "warp", "warp_element_size", "warp_octaves",
            # Animation
            "use_animation", "noise_time", "time_element_size",
        ],
        "inputs": {
            "blend": {"label": "Blend"},
            "attribute_names": {"label": "Attribute Names"},
            "use_x": {"label": "Component Scope X"},
            "use_y": {"label": "Component Scope Y"},
            "use_z": {"label": "Component Scope Z"},
            "attribute_class": {"label": "Attribute Class", "menu": _CLASS_MENU},
            "noise_along_vector": {"label": "Noise Along Vector", "sep": True},
            "vector_attribute": {"label": "Vector Attribute",
                                 "disable": "{ noise_along_vector == 0 }"},

            # Noise Value
            "range_values": {"folder": "Noise Value", "section": None, "label": "Range Values",
                             "menu": {"zero_centered": "Zero Centered",
                                      "zero_to_one": "Positive",
                                      "one_centered": "One Centered",
                                      "negative": "Negative", "min_max": "Min/Max",
                                      "min_range": "Min + Range Length",
                                      "middle_range": "Middle \u00b1 Range Length"}},
            "operation": {"folder": "Noise Value", "section": None, "label": "Operation",
                          "menu": {"add": "Add", "subtract": "Subtract",
                                   "multiply": "Multiply", "set": "Set Always",
                                   "set_initial": "Set Initial", "minimum": "Minimum",
                                   "maximum": "Maximum"}},
            "amplitude": {"folder": "Noise Value", "section": None, "label": "Amplitude",
                          "hide": "{ range_values == min_max } { range_values == min_range } "
                                  "{ range_values == middle_range }"},
            "min_value": {"folder": "Noise Value", "section": None, "label": "Min Value",
                          "hide": "{ range_values != min_max range_values != min_range }"},
            "max_value": {"folder": "Noise Value", "section": None, "label": "Max Value",
                          "hide": "{ range_values != min_max }"},
            "middle_value": {"folder": "Noise Value", "section": None, "label": "Middle Value",
                             "hide": "{ range_values != middle_range }"},
            "range_length": {"folder": "Noise Value", "section": None, "label": "Range Length",
                             "hide": "{ range_values != min_range range_values != middle_range }",
                             "help": "Middle ± Range Length is the full width (unlike Attribute Adjust's half width)"},
            "gamma": {"folder": "Noise Value", "section": "Value Correction", "label": "Gamma"},
            "contrast": {"folder": "Noise Value", "section": "Value Correction",
                         "label": "Contrast"},
            "make_unit_length": {"folder": "Noise Value", "label": "Make Vectors Unit Length",
                                 "sep": True},
            "recompute_normals": {"folder": "Noise Value", "label": "Recompute Normals"},
            "blend_attribute": {"label": "Blend Attribute",
                                "help": "When non-empty, used per element as Blend (the constant above no longer applies)"},
            "attribute_type": {"label": "Attribute Type",
                               "menu": {"auto": "Auto (from Attribute)", "float": "Float",
                                        "vector": "Vector"}},
            # Previously two "Value Correction" sections with the same name, each with a header toggle; merged into one section,
            # the two toggles became plain toggles, each greying out the parameters after it
            "use_remap_ramp": {"folder": "Noise Value", "section": "Value Correction",
                               "gate": None, "label": "Enable Remap Ramp"},
            "remap_ramp": {"folder": "Noise Value", "section": "Value Correction",
                           "label": "Remap Ramp",
                           "disable": "{ use_remap_ramp == 0 }"},
            "ramp_mode": {"folder": "Noise Value", "section": "Value Correction"},
            "use_value_correction": {"folder": "Noise Value",
                                     "section": "Value Correction", "gate": None,
                                     "label": "Enable Bias / Gain", "sep": True},
            "bias": {"folder": "Noise Value", "section": "Value Correction",
                     "label": "Bias", "disable": "{ use_value_correction == 0 }"},
            "gain": {"folder": "Noise Value", "section": "Value Correction",
                     "label": "Gain", "disable": "{ use_value_correction == 0 }"},
            # Clamp is applied after Operation -- placed in Post-Process as in Houdini
            "use_clamp_min": {"folder": "Noise Value", "section": "Post-Process"},
            "clamp_min": {"folder": "Noise Value", "section": "Post-Process",
                          "label": "Minimum"},
            "use_clamp_max": {"folder": "Noise Value", "section": "Post-Process"},
            "clamp_max": {"folder": "Noise Value", "section": "Post-Process",
                          "label": "Maximum"},
            "post_absolute": {"folder": "Noise Value", "label": "Absolute Value",
                              "sep": True},
            "post_invert": {"folder": "Noise Value", "label": "Invert"},
            "use_normalize": {"folder": "Noise Value", "label": "Normalize",
                              "sep": True},
            "normalize_min": {"folder": "Noise Value",
                              "row": {"kind": "vector",
                                      "members": ["normalize_min", "normalize_max"],
                                      "label": "Normalize Range"},
                              "disable": "{ use_normalize == 0 }"},
            "normalize_max": {"folder": "Noise Value", "in_row": "normalize_min"},

            # Noise Pattern
            "noise_type": {"folder": "Noise Pattern", "section": None, "label": "Noise Type",
                           "menu": _AA2_NOISE},
            "location_attribute": {"folder": "Noise Pattern", "section": None,
                                   "label": "Location Attribute"},
            "element_size_x": {"folder": "Noise Pattern", "section": None,
                               "row": {"label": "Element Size"}},
            "element_size_y": {"folder": "Noise Pattern", "section": None},
            "element_size_z": {"folder": "Noise Pattern", "section": None},
            "offset_x": {"folder": "Noise Pattern", "section": None, "row": {"label": "Offset"}},
            "offset_y": {"folder": "Noise Pattern", "section": None},
            "offset_z": {"folder": "Noise Pattern", "section": None},
            "rand_seed": {"folder": "Noise Pattern", "section": None},
            "use_vexpression": {"folder": "Noise Pattern", "section": "Use VEXpression"},
            "vexpression": {"folder": "Noise Pattern", "section": "Use VEXpression",
                            "label": "VEXpression"},
            "fractal": {"folder": "Noise Pattern", "label": "Fractal Type",
                        "menu": {"none": "None", "standard": "Standard",
                                 "terrain": "Terrain",
                                 "hybrid_terrain": "Hybrid Terrain"}},
            # fractal_noise(): none returns a single noise layer directly; offset only goes into terrain / hybrid
            "octaves": {"folder": "Noise Pattern", "label": "Max Octaves",
                        "hide": "{ fractal == none }"},
            "lacunarity": {"folder": "Noise Pattern", "label": "Lacunarity",
                           "hide": "{ fractal == none }"},
            "roughness": {"folder": "Noise Pattern", "label": "Roughness",
                          "hide": "{ fractal == none }"},
            "fractal_offset": {"folder": "Noise Pattern", "label": "Terrain Offset",
                               "hide": "{ fractal == none } { fractal == standard }"},
            "warp": {"folder": "Noise Pattern", "label": "Warp Distance",
                     "help": "0 = no distortion; the two parameters below only take effect when it is non-zero"},
            "warp_element_size": {"folder": "Noise Pattern",
                                  "label": "Warp Element Size"},
            "warp_octaves": {"folder": "Noise Pattern", "label": "Warp Octaves"},

            # Animation
            "use_animation": {"folder": "Animation", "label": "Animate Noise"},
            "noise_time": {"folder": "Animation", "label": "Time"},
            "time_element_size": {"folder": "Animation", "label": "Pulse Duration"},
        },
    },

    # ── Attribute Randomize SOP: Attribute Class / Name / Operation on top,
    #    the Distribution tab shows Min/Max or Mean/Std Dev depending on the distribution, the Options tab holds the seed
    "PCG_AttribRandomize": {
        "order": ["group", "attribute_class", "name", "combine", "global_scale",
                  "mode", "distribution", "dimensions",
                  "min_x", "min_y", "min_z", "min_w",
                  "max_x", "max_y", "max_z", "max_w",
                  "mean", "stddev", "exponent", "prob_b", "step_size", "value_list",
                  "shape", "axis_x", "axis_y", "axis_z", "cone_angle",
                  "angle_min", "angle_max", "length_min", "length_max",
                  "rand_seed", "id_attribute"],
        "inputs": {
            "attribute_class": {"label": "Attribute Class", "menu": _CLASS_MENU},
            "name": {"label": "Attribute Name"},
            "combine": {"label": "Operation",
                        "menu": {"set": "Set Value", "add": "Add Value",
                                 "multiply": "Multiply", "minimum": "Minimum",
                                 "maximum": "Maximum"}},

            "mode": {"folder": "Distribution", "label": "Value Type",
                     "menu": {"value": "Value", "direction": "Direction",
                              "orient": "Orientation"}},
            # mode=value
            "distribution": {"folder": "Distribution", "label": "Distribution",
                             "menu": {"uniform": "Uniform (Continuous)",
                                      "gaussian": "Normal (Gaussian)",
                                      "power": "Power",
                                      "constant": "Constant Value",
                                      "two_values": "Two Values",
                                      "uniform_discrete": "Uniform (Discrete)",
                                      "exponential": "Exponential",
                                      "lognormal": "Log-Normal",
                                      "cauchy": "Cauchy-Lorentz",
                                      "custom_discrete": "Custom Discrete",
                                      "inside_sphere": "Inside Sphere"},
                             "hide": "{ mode != value }"},
            "dimensions": {"folder": "Distribution", "label": "Dimensions",
                           "hide": "{ mode != value }"},
            # Constant Value / Two Values reuse Min (= Value / Value A) and Max (= Value B)
            "min_x": {"folder": "Distribution", "row": {"label": "Min Value"},
                      "hide": "{ mode != value } " + _any("distribution", _RAND_NO_MIN),
                      "help": "Value for Constant Value; Value A for Two Values"},
            "max_x": {"folder": "Distribution", "row": {"label": "Max Value"},
                      "hide": "{ mode != value } { distribution == constant } "
                              + _any("distribution", _RAND_NO_MIN),
                      "help": "Value B for Two Values"},
            "min_y": {"folder": "Distribution"}, "min_z": {"folder": "Distribution"},
            "min_w": {"folder": "Distribution"}, "max_y": {"folder": "Distribution"},
            "max_z": {"folder": "Distribution"}, "max_w": {"folder": "Distribution"},
            "mean": {"folder": "Distribution", "label": "Middle Value",
                     "hide": "{ mode != value } " + _not_any(
                         "distribution", ("gaussian", "exponential", "lognormal", "cauchy")),
                     "help": "Normal = mean; Exponential / Log-Normal / Cauchy = median"},
            "stddev": {"folder": "Distribution", "label": "Scale Around Middle",
                       "hide": "{ mode != value } " + _not_any(
                           "distribution", ("gaussian", "lognormal", "cauchy")),
                       "help": "Normal = standard deviation; Log-Normal = standard deviation in log space; Cauchy = γ"},
            "exponent": {"folder": "Distribution", "label": "Exponent",
                         "hide": "{ mode != value } { distribution != power }"},
            "prob_b": {"folder": "Distribution", "label": "Probability of Value B",
                       "hide": "{ mode != value } { distribution != two_values }"},
            "step_size": {"folder": "Distribution", "label": "Step Size",
                          "hide": "{ mode != value } { distribution != uniform_discrete }"},
            "value_list": {"folder": "Distribution", "label": "Values",
                           "hide": "{ mode != value } { distribution != custom_discrete }",
                           "help": "One set per line (min-max:step expands), w=weight at the end of the line"},
            "global_scale": {"label": "Global Scale",
                             "help": "Multiplied onto the generated value before Operation (not for Orientation)"},
            # mode=direction / orient
            "shape": {"folder": "Distribution", "label": "Shape",
                      "menu": {"sphere": "Sphere", "cone": "Cone",
                               "disc": "Disc", "line": "Line"},
                      "hide": "{ mode == value }",
                      "help": "For Orientation, Sphere = fully random, the other three = random rotation around Direction"},
            # orient + sphere uses Shoemake and ignores the axis; direction + sphere still builds a basis from the axis (rotates the result)
            "axis_x": {"folder": "Distribution", "row": {"label": "Direction"},
                       "hide": "{ mode == value } { mode == orient shape == sphere }"},
            "axis_y": {"folder": "Distribution"}, "axis_z": {"folder": "Distribution"},
            "cone_angle": {"folder": "Distribution", "label": "Cone Angle",
                           "hide": "{ mode != direction } { shape != cone }"},
            "angle_min": {"folder": "Distribution",
                          "row": {"kind": "vector",
                                  "members": ["angle_min", "angle_max"],
                                  "label": "Angle Range"},
                          "hide": "{ mode != orient } { shape == sphere }"},
            "angle_max": {"folder": "Distribution", "in_row": "angle_min"},
            "length_min": {"folder": "Distribution",
                           "row": {"kind": "vector",
                                   "members": ["length_min", "length_max"],
                                   "label": "Length Range"},
                           "hide": "{ mode != direction }"},
            "length_max": {"folder": "Distribution", "in_row": "length_min"},

            "rand_seed": {"folder": "Options", "label": "Global Seed"},
            "id_attribute": {"folder": "Options", "label": "Seed Attribute"},
        },
    },

    # ── Point Jitter SOP: Group / Mask (+ mode) / Id Attribute / Scale / Axis Scales /
    #    Seed / Use Point Scale
    "PCG_PointJitter": {
        "order": ["group", "mask", "mask_mode", "mask_attribute", "id_attribute",
                  "scale", "axis_scale_x", "axis_scale_y", "axis_scale_z",
                  "rand_seed", "use_point_scale", "update_normals"],
        "inputs": {
            "mask": {"label": "Mask"},
            "mask_mode": {"label": "Mask Mode",
                          "menu": {"no_scaling": "No Scaling",
                                   "scale_by_attribute": "Scale by Attribute"}},
            "mask_attribute": {"label": "Mask Attribute",
                               "hide": "{ mask_mode != scale_by_attribute }"},
            "id_attribute": {"label": "Id Attribute"},
            "scale": {"label": "Scale", "sep": True},
            "axis_scale_x": {"row": {"label": "Axis Scales"}},
            "rand_seed": {"label": "Seed"},
            "use_point_scale": {"label": "Use Point Scale"},
            "update_normals": {"label": "Update Normals"},
        },
    },

    # ── UV Project (counterpart of UV Texture / UV Project): UV Attribute / Group / Class /
    #    Projection, with Axis and Fix Boundary Seams depending on the projection
    "PCG_UVProject": {
        "order": ["attribute_name", "group", "attribute_class", "mode", "axis",
                  "fit_to_01", "keep_aspect", "translate_u", "translate_v",
                  "rotate", "scale_u", "scale_v", "fix_seams",
                  "use_projector", "xform_order", "rotate_order", "proj_translate_x",
                  "proj_rotate_x", "proj_scale_x", "proj_pivot_x",
                  "u_range_min", "v_range_min", "inner_radius"],
        "inputs": {
            "attribute_name": {"label": "UV Attribute"},
            "attribute_class": {"label": "Attribute Class",
                                "menu": {"vertex": "Vertex", "point": "Point"},
                                "help": "Box / Face can only write Vertex"},
            "mode": {"label": "Projection",
                     "menu": {"planar": "Orthographic",
                              "cylindrical": "Cylindrical",
                              "spherical": "Polar",
                              "box": "Box (Six Sides)", "face": "Face",
                              "rows_columns": "Rows & Columns",
                              "toroidal": "Toroidal", "plastic_wrap": "Plastic Wrap"},
                     "help": "Toroidal: u around the main axis, v around the tube (for tori); "
                             "Plastic Wrap: wraps down from the positive axis, pinched to a point only at the back, no seam"},
            # Only planar / cylindrical / spherical use _frame(axis)
            "axis": {"label": "Projection Axis",
                     "menu": {"x": "X Axis", "y": "Y Axis", "z": "Z Axis"},
                     "hide": _not_any("mode", ("planar", "cylindrical", "spherical",
                                               "toroidal", "plastic_wrap"))},
            # With the projector on, planar / cylinder / sphere / torus / wrap skip Fit (box / face / rows_columns unchanged)
            "fit_to_01": {"label": "Fit to 0-1",
                          "help": "With Projector Transform on, only affects Box / Face / Rows & Columns"},
            "keep_aspect": {"label": "Keep Aspect Ratio",
                            "disable": "{ fit_to_01 == 0 }"},
            "translate_u": {"row": {"label": "Offset"}},
            "rotate": {"label": "Angle"},
            "scale_u": {"row": {"label": "Scale"}},
            # _seam_fix only runs for cylindrical / spherical and when writing vertex
            "fix_seams": {"label": "Fix Boundary Seams", "sep": True,
                          "hide": _not_any("mode", ("cylindrical", "spherical", "toroidal")),
                          "disable": "{ attribute_class == point }"},
            # Only read for toroidal with the projector on (when off, the major radius comes from the data)
            "inner_radius": {"label": "Inner Radius",
                             "hide": "{ mode != toroidal }",
                             "disable": "{ use_projector == 0 }",
                             "help": "The projector's outer radius is fixed at 0.5; only used with Projector on"},
            "use_projector": {"label": "Projector Transform",
                              "help": "On = Houdini semantics: a unit-sized projector placed by the transform below, "
                                      "no more centering / Fit; box / face / rows_columns are unaffected"},
            "xform_order": {"label": "Transform Order",
                            "menu": {"srt": "Scale Rot Trans", "str": "Scale Trans Rot",
                                     "rst": "Rot Scale Trans", "rts": "Rot Trans Scale",
                                     "tsr": "Trans Scale Rot", "trs": "Trans Rot Scale"},
                            "help": "Applied left to right"},
            "rotate_order": {"label": "Rotate Order",
                             "menu": {"xyz": "Rx Ry Rz", "xzy": "Rx Rz Ry",
                                      "yxz": "Ry Rx Rz", "yzx": "Ry Rz Rx",
                                      "zxy": "Rz Rx Ry", "zyx": "Rz Ry Rx"}},
            "proj_translate_x": {"row": {"kind": "vector", "label": "Translate",
                                         "members": ["proj_translate_x", "proj_translate_y",
                                                     "proj_translate_z"]}},
            "proj_rotate_x": {"row": {"kind": "vector", "label": "Rotate",
                                      "members": ["proj_rotate_x", "proj_rotate_y", "proj_rotate_z"]}},
            "proj_scale_x": {"row": {"kind": "vector", "label": "Scale",
                                     "members": ["proj_scale_x", "proj_scale_y", "proj_scale_z"]}},
            "proj_pivot_x": {"row": {"kind": "vector", "label": "Pivot",
                                     "members": ["proj_pivot_x", "proj_pivot_y", "proj_pivot_z"]}},
            "u_range_min": {"row": {"kind": "vector", "label": "U Range",
                                    "members": ["u_range_min", "u_range_max"]}},
            "v_range_min": {"row": {"kind": "vector", "label": "V Range",
                                    "members": ["v_range_min", "v_range_max"]}},
        },
    },

    # ── UV Flatten SOP: UV Attribute / Seams, solver, packing sections
    "PCG_UVFlatten": {
        "order": ["flatten_group", "attribute_name", "method", "preserve_seams",
                  "seam_group", "pin_group", "normalize",
                  "iterations", "tolerance", "arap_iterations",
                  "pack", "padding", "group", "distortion_attribute",
                  "output_seams", "output_constrained"],
        "inputs": {
            "flatten_group": {"label": "Group",
                              "help": "Only flattens these primitives; the selection border becomes a seam automatically, other primitives' uv is left alone"},
            "attribute_name": {"label": "UV Attribute"},
            "method": {"label": "Flattening Method",
                       "menu": {"lscm": "Least Squares Conformal (LSCM)",
                                "scp": "Spectral (SCP)",
                                "abf": "Angle Based (ABF)"},
                       "help": "LSCM is this plugin's original algorithm (Houdini 3.0 has no such mode); "
                               "SCP pins nothing; ABF solves angles first, least area distortion, slowest"},
            "preserve_seams": {"label": "Preserve Seams",
                               "help": "Edges already split in the existing uv also count as seams"},
            "seam_group": {"label": "Seams"},
            "pin_group": {"label": "Vertex Pins",
                          "help": "Corners on these points are pinned to the existing uv; with >= 2 pins in an island "
                                  "no more scaling / normalizing"},
            "output_seams": {"section": "Output", "label": "Seams Group",
                             "help": "Seams used (Seams + Preserve Seams) written as an edge group; empty = not written"},
            "output_constrained": {"section": "Output", "label": "Constrained Islands Group",
                                   "help": "Primitives of islands with pins; empty = not written"},
            # Packing rescales the whole UV, overriding the global scale done by Normalize
            "normalize": {"label": "Normalize to 0-1",
                          "disable": "{ pack == 1 }"},
            "iterations": {"label": "Max Iterations"},
            "tolerance": {"label": "Tolerance"},
            "arap_iterations": {"section": "Solver", "label": "ARAP Iterations",
                                "help": "Extra ARAP rounds after flattening, 0 = none; skipped when an island has >= 2 pins"},
            "pack": {"label": "Pack Islands"},
            "padding": {"label": "Island Padding"},
            "group": {"label": "Pack Group",
                      "help": "Only affects packing; which primitives get flattened is set by Group at the top"},
            "distortion_attribute": {"section": "Output",
                                     "label": "Distortion Attribute"},
        },
    },

    # ── UV Layout SOP: two tabs, Islands to Pack / Packing
    "PCG_UVLayout": {
        "order": ["attribute_name", "group", "attribute_class",
                  "match_surface_area", "rotate_to_fit",
                  "method", "scale_mode", "fixed_scale", "island_rotation",
                  "rotation_step", "rotation_divisions", "padding",
                  "pack_resolution",
                  "pack_into", "udim_start", "udim_columns", "udim_count",
                  "nonpacked_group", "island_attribute", "target_attribute"],
        "inputs": {
            "attribute_name": {"folder": "Islands to Pack", "label": "UV Attribute"},
            "group": {"folder": "Islands to Pack"},
            "attribute_class": {"folder": "Islands to Pack",
                                "label": "Attribute Class",
                                "menu": {"vertex": "Vertex", "point": "Point"}},
            "match_surface_area": {"folder": "Islands to Pack",
                                   "label": "Scale Islands to Match Their Surface Areas",
                                   "help": "Before packing, scale each island's uv area to be proportional to its 3D area"},
            # Our "minimum area orientation" pre-rotation; its position corresponds to Houdini's Axis Alignment
            "rotate_to_fit": {"folder": "Islands to Pack", "label": "Rotate to Fit",
                              "help": "First rotates to the orientation of the minimum-area bounding box (in Houdini's Axis Alignment "
                                      "slot; different algorithm)"},
            "method": {"folder": "Packing", "label": "Packing Method",
                       "menu": {"shelf": "Bounding Box (Shelf)",
                                "raster": "Island Shape (Raster)"}},
            "scale_mode": {"folder": "Packing", "label": "Scale",
                           "menu": {"uniform": "Largest Packable (Uniform)",
                                    "individual": "Individual (Equal Area)",
                                    "fixed": "Fixed"}},
            "fixed_scale": {"folder": "Packing", "label": "Fixed Scale",
                            "hide": "{ scale_mode != fixed }"},
            "island_rotation": {"folder": "Packing", "label": "Island Rotation Step",
                                "menu": {"auto": "Default (Raster: 90°)",
                                         "none": "No Rotation",
                                         "step": "Rotation Step",
                                         "custom": "Custom"}},
            "rotation_step": {"folder": "Packing", "label": "Step",
                              "hide": "{ island_rotation != step }"},
            "rotation_divisions": {"folder": "Packing", "label": "Divisions of 360°",
                                   "hide": "{ island_rotation != custom }"},
            "padding": {"folder": "Packing", "label": "Island Padding"},
            # Only raster uses the occupancy grid
            "pack_resolution": {"folder": "Packing", "label": "Search Resolution",
                                "hide": "{ method != raster }"},
            "pack_into": {"folder": "Targets", "label": "Pack Into",
                          "menu": {"unit_square": "Unit Square (0-1)",
                                   "udim_tiles": "UDIM Tiles"}},
            "udim_start": {"folder": "Targets", "label": "Starting UDIM",
                           "hide": "{ pack_into != udim_tiles }"},
            "udim_columns": {"folder": "Targets", "label": "Columns",
                             "hide": "{ pack_into != udim_tiles }"},
            # With Fixed, tiles are opened onward as needed; Count is not read
            "udim_count": {"folder": "Targets", "label": "Tile Count",
                           "hide": "{ pack_into != udim_tiles }",
                           "disable": "{ scale_mode == fixed }"},
            "nonpacked_group": {"folder": "Output", "label": "Nonpacked Polygons",
                                "disable": "{ scale_mode != fixed }"},
            "island_attribute": {"folder": "Output", "label": "Island Number"},
            "target_attribute": {"folder": "Output", "label": "Assigned Target"},
        },
    },

    # ── Convert SOP: Group / Convert To, then Divisions, Order, volume parameters depending on the target type,
    #    Volume Offset
    "PCG_Convert": {
        "order": ["group", "convert_to",
                  "use_tessellation", "u_divs", "v_divs",
                  "use_nurbs_opts", "u_order", "v_order",
                  "interpolate_through_hulls",
                  "use_volume", "vol_res_x", "vol_res_y", "vol_res_z",
                  "vol_radius", "vol_pad", "iso"],
        "inputs": {
            "convert_to": {"label": "Convert To",
                           "menu": {"triangles": "Triangles",
                                    "polygons": "Polygon",
                                    "polylines": "Polyline",
                                    "points": "Points",
                                    "nurbs_curve": "NURBS Curve",
                                    "nurbs_surface": "NURBS Surface",
                                    "bezier_curve": "Bezier Curve",
                                    "bezier_surface": "Bezier Surface",
                                    "volume_sdf": "Volume (SDF)",
                                    "volume_fog": "Volume (Fog)"}},
            # Houdini has none of the three section header toggles (sections always apply), so they are hidden by default; sections
            # are shown / hidden whole by target type. Off = this section uses defaults (run() really reads them since pcg85);
            # only revealed when switched off, otherwise a toggle left off in an old workflow would be invisible on the panel and impossible to turn on
            "use_tessellation": {"section": "Divisions", "gate": None,
                                 "hide": "{ use_tessellation == 1 }"},
            "u_divs": {"section": "Divisions",
                       "row": {"kind": "vector", "members": ["u_divs", "v_divs"],
                               "label": "Divisions"},
                       "hide": _HIDE_TESS,
                       "help": "Subdivisions per span when converting splines to polygons (V only affects surfaces)"},
            "v_divs": {"section": "Divisions", "in_row": "u_divs"},
            "use_nurbs_opts": {"gate": None,
                               "hide": "{ use_nurbs_opts == 1 }"},
            "u_order": {"label": "U Order", "hide": _HIDE_SPLINE},
            # Curves only have the U direction
            "v_order": {"label": "V Order",
                        "hide": _not_any("convert_to",
                                         ("nurbs_surface", "bezier_surface"))},
            "interpolate_through_hulls": {"label": "Interpolate Through Hulls",
                                          "hide": _HIDE_SPLINE},
            "use_volume": {"gate": None,
                           "hide": "{ use_volume == 1 }"},
            "vol_res_x": {"hide": _HIDE_VOLUME},
            # Only points_to_volume uses the radius; mesh_to_volume does not
            "vol_radius": {"label": "Point Radius",
                           "hide": "{ convert_to != volume_fog }",
                           "help": "0 = derived automatically from point spacing"},
            "vol_pad": {"label": "Padding", "hide": _HIDE_VOLUME},
            # Iso value for volume to polygons; volume targets do not go through volume_to_polygons
            "iso": {"section": None, "label": "Volume Offset", "sep": True,
                    "hide": _any("convert_to", _VOLUME_TYPES)},
        },
    },

    # ── Measure SOP: Group / Element Type, three tabs Measurement / Visualized Range / Output
    "PCG_Measure": {
        "order": ["group", "element_type",
                  "measurement", "accumulate", "position_attribute",
                  "color_attribute", "use_min", "min_value", "use_max",
                  "max_value", "use_width", "width", "width_mode", "center",
                  "color_ramp", "custom_ramp", "ramp_mode",
                  "attribute_name", "total_attribute", "range_group",
                  "bake_range", "remap_min", "remap_max"],
        "inputs": {
            "element_type": {"label": "Element Type",
                             "menu": {"primitives": "Primitives",
                                      "points": "Points"}},
            "measurement": {"folder": "Measurement", "label": "Measure",
                            "menu": {"area": "Area",
                                     "perimeter": "Perimeter / Length",
                                     "volume": "Volume",
                                     "curvature": "Curvature (Mean)",
                                     "gaussian_curvature": "Curvature (Gaussian)"},
                            "help": "Perimeter / Volume only work with Primitives"},
            "accumulate": {"folder": "Measurement", "label": "Accumulate",
                           "menu": {"per_element": "Per Element",
                                    "total": "Throughout"}},
            "position_attribute": {"folder": "Measurement",
                                   "label": "Position Attribute"},

            "color_attribute": {"folder": "Visualized Range", "section": None,
                                "label": "Color Attribute",
                                "help": "Colors by the range and color ramp below only when a name is given"},
            "use_min": {"folder": "Visualized Range", "section": None,
                        "in_toggle": "min_value", "sep": True},
            "min_value": {"folder": "Visualized Range", "section": None,
                          "toggle": "use_min", "label": "Minimum"},
            "use_max": {"folder": "Visualized Range", "section": None,
                        "in_toggle": "max_value"},
            "max_value": {"folder": "Visualized Range", "section": None,
                          "toggle": "use_max", "label": "Maximum"},
            "use_width": {"folder": "Visualized Range", "section": None},
            # visual_range(): without Width the range is min / max, and Width / multiplier / center are ignored;
            # likewise ignored when both Min and Max are locked
            "width": {"folder": "Visualized Range", "section": None,
                      "label": "Width",
                      "disable": "{ use_min == 1 use_max == 1 }"},
            "width_mode": {"folder": "Visualized Range", "section": None,
                           "label": "Width Multiplier",
                           "menu": {"mad": "x MAD", "stddev": "x SD",
                                    "absolute": "x 1.0"},
                           "disable": "{ use_width == 0 } { use_min == 1 use_max == 1 }"},
            "center": {"folder": "Visualized Range", "section": None,
                       "label": "Center",
                       "menu": {"median": "Median", "mean": "Mean",
                                "zero": "Fixed (0)"},
                       "disable": "{ use_width == 0 } { use_min == 1 use_max == 1 }"},
            "color_ramp": {"folder": "Visualized Range", "section": None,
                           "label": "Color Ramp", "sep": True,
                           "menu": {"blue_white_red": "Blue-White-Red",
                                    "grayscale": "Grayscale", "heat": "Heat",
                                    "custom": "Custom"}},
            # The interpolation also applies to the built-in color ramps -- pulled out of the ramp editor onto its own row,
            # so it stays visible when Custom Ramp is hidden
            "custom_ramp": {"folder": "Visualized Range", "section": None,
                            "label": "Custom Ramp", "ramp": {"interp": None},
                            "hide": "{ color_ramp != custom }"},
            "ramp_mode": {"folder": "Visualized Range", "section": None,
                          "in_ramp": None, "label": "Ramp Interpolation",
                          "menu": {"linear": "Linear", "smooth": "Smooth",
                                   "constant": "Constant"}},

            "attribute_name": {"folder": "Output", "section": None,
                               "label": "Attribute Name",
                               "help": "Empty = default name based on Measure"},
            "total_attribute": {"folder": "Output", "section": None,
                                "label": "Total Attribute Name"},
            "range_group": {"folder": "Output", "section": None,
                            "label": "Range Group"},
            "bake_range": {"folder": "Output", "section": None,
                           "label": "Bake Visualized Range Into Output",
                           "sep": True},
            "remap_min": {"folder": "Output", "section": None,
                          "row": {"kind": "vector",
                                  "members": ["remap_min", "remap_max"],
                                  "label": "Remap Range"},
                          "disable": "{ bake_range == 0 }"},
            "remap_max": {"folder": "Output", "section": None, "in_row": "remap_min"},
        },
    },
}


# ── pcg100 s6:Attribute Adjust Float / Integer / Vector / Color(attribadjust2.py)
_AA2_OPS = {"set_always": "Set Always", "set_initial": "Set Initial", "add": "Add",
            "subtract": "Subtract", "multiply": "Multiply", "minimum": "Minimum",
            "maximum": "Maximum"}



def _aa2_noise_spec(hide):
    """Noise Pattern tab. hide = the condition that holds when it is not Noise."""
    f = "Noise Pattern"
    frac = hide + " { fractal_type == none }"
    return {
        "noise_type": {"folder": f, "label": "Noise Type", "menu": _AA2_NOISE,
                       "hide": hide},
        "location_attribute": {"folder": f, "label": "Location Attribute", "hide": hide},
        "element_size": {"folder": f, "label": "Element Size", "hide": hide},
        "element_scale_x": {"folder": f, "row": {"label": "Element Scale"}, "hide": hide},
        "element_scale_y": {"folder": f}, "element_scale_z": {"folder": f},
        "noise_offset_x": {"folder": f, "row": {"label": "Offset"}, "hide": hide},
        "noise_offset_y": {"folder": f}, "noise_offset_z": {"folder": f},
        "fractal_type": {"folder": f, "label": "Fractal Type", "sep": True, "hide": hide,
                         "menu": {"none": "None", "standard": "Standard",
                                  "terrain": "Terrain", "hybrid": "Hybrid"}},
        "max_octaves": {"folder": f, "label": "Max Octaves", "hide": frac},
        "lacunarity": {"folder": f, "label": "Lacunarity", "hide": frac},
        "roughness": {"folder": f, "label": "Roughness", "hide": frac},
    }


_AA2_NOISE_ORDER = ["noise_type", "location_attribute", "element_size",
                    "element_scale_x", "element_scale_y", "element_scale_z",
                    "noise_offset_x", "noise_offset_y", "noise_offset_z",
                    "fractal_type", "max_octaves", "lacunarity", "roughness"]


def _aa2_scalar_spec(p, hide, folder="Adjustment Value", value_label="Value"):
    """
    The Range Values set. p = parameter name prefix (used by the Vector node), hide = condition under which this whole set
    has no effect (not Random / Noise). Conditions checked against ScalarSpec.values(): Specific Values
    is a direct table lookup and ignores Distribution / Stepping.
    """
    rv = p + "range_values"
    dist = p + "value_distribution"
    spec = hide + f" {{ {rv} == specific }}"
    outl = spec + f" {{ {dist} != uniform_outliers }}"
    return {
        rv: {"folder": folder, "label": "Range Values", "hide": hide, "sep": True,
             "menu": {"min_max": "Min/Max", "min_range": "Min + Range Length",
                      "middle_range": "Middle ± Range Length",
                      "specific": "Specific Values"}},
        p + "min_value": {"folder": folder, "label": "Min " + value_label,
                          "hide": hide + f" {{ {rv} == middle_range }} {{ {rv} == specific }}"},
        p + "max_value": {"folder": folder, "label": "Max " + value_label,
                          "hide": hide + f" {{ {rv} != min_max }}"},
        p + "middle_value": {"folder": folder, "label": "Middle " + value_label,
                             "hide": hide + f" {{ {rv} != middle_range }}"},
        p + "range_length": {"folder": folder, "label": "Range Length",
                             "hide": hide + f" {{ {rv} == min_max }} {{ {rv} == specific }}",
                             "help": "Middle ± Range Length: half width = half the length"},
        p + "value_list": {"folder": folder, "label": "Values",
                           "hide": hide + f" {{ {rv} != specific }}",
                           "help": "Number of Values multiparm written as one set per line: "
                                   "a value or Value List (min-max:step), w=Weight at the end of the line"},
        dist: {"folder": folder, "label": "Value Distribution", "hide": spec,
               "menu": {"uniform": "Uniform", "uniform_remap": "Uniform with Remapping",
                        "uniform_outliers": "Uniform with Outliers"}},
        p + "remap_ramp": {"folder": folder, "label": "Remap Ramp",
                           "hide": spec + f" {{ {dist} != uniform_remap }}"},
        p + "outlier_percent": {"folder": folder, "label": "Outlier Percent", "hide": outl},
        p + "outlier_range": {"folder": folder, "label": "Outlier Range", "hide": outl},
        p + "outlier_range_mode": {"folder": folder, "label": "Outlier Range Mode",
                                   "hide": outl,
                                   "menu": {"additive": "Additive",
                                            "multiplicative": "Multiplicative"}},
        p + "outlier_extent": {"folder": folder, "label": "Outlier Extent", "hide": outl,
                               "menu": {"above_max": "Above Max Value",
                                        "below_min": "Below Min Value", "both": "Both"}},
        p + "outlier_seed": {"folder": folder, "label": "Outlier Seed", "hide": outl},
        # The code writes it whenever the name is non-empty (all 0 outside outlier modes), so it is not hidden
        p + "outlier_attribute": {"folder": folder, "label": "Outlier Attribute",
                                  "help": "Empty = not written; 1 = outlier, 0 = not"},
        p + "use_stepping": {"folder": folder, "label": "Enable Stepping", "hide": spec},
        p + "step_size": {"folder": folder, "label": "Step Size", "hide": spec,
                          "disable": f"{{ {p}use_stepping == 0 }}"},
    }


def _aa2_scalar_order(p):
    return [p + k for k in (
        "range_values", "min_value", "max_value", "middle_value", "range_length",
        "value_list", "value_distribution", "remap_ramp", "outlier_percent",
        "outlier_range", "outlier_range_mode", "outlier_extent", "outlier_seed",
        "outlier_attribute", "use_stepping", "step_size")]


def _aa2_scalar_node(integer):
    """Specs for the Float / Integer nodes. Conditions checked against attribadjust2.adjust_scalar()."""
    adj = "Adjustment Value"
    not_rn = "{ pattern_type == constant } { pattern_type == attribute }"
    not_attr = "{ pattern_type != attribute }"
    blend = [] if integer else ["blend_mode", "blend", "blend_attribute"]
    order = (["group"] + blend + ["attribute_name", "attribute_class",
              "adjust_value", "operation", "pattern_type", "constant_value"]
             + _aa2_scalar_order("")
             + ["adjustment_attribute", "attribute_adjustment", "attribute_scale",
                "attribute_offset", "randomization_by", "custom_attribute", "rand_seed"]
             + _AA2_NOISE_ORDER
             + ["use_minimum", "minimum", "use_maximum", "maximum"])
    inputs = {
        "attribute_name": {"label": "Attribute Name"},
        "attribute_class": {"label": "Attribute Class", "menu": _CLASS_MENU},
        "adjust_value": {"folder": adj, "label": "Adjust Value"},
        "operation": {"folder": adj, "label": "Operation", "menu": _AA2_OPS,
                      "disable": "{ adjust_value == 0 }"},
        "pattern_type": {"folder": adj, "label": "Pattern Type",
                         "disable": "{ adjust_value == 0 }",
                         "menu": {"constant": "Constant", "random": "Random",
                                  "noise": "Noise", "attribute": "Attribute"}},
        "constant_value": {"folder": adj, "label": "Constant Value",
                           "hide": "{ pattern_type != constant }"},
        **_aa2_scalar_spec("", not_rn, adj),
        "adjustment_attribute": {"folder": adj, "label": "Attribute", "hide": not_attr},
        "attribute_adjustment": {"folder": adj, "label": "Attribute Adjustment",
                                 "hide": not_attr,
                                 "menu": {"scale": "Scale", "offset": "Offset",
                                          "both": "Apply Both"}},
        "attribute_scale": {"folder": adj, "label": "Scale",
                            "hide": not_attr + " { attribute_adjustment == offset }"},
        "attribute_offset": {"folder": adj, "label": "Offset",
                             "hide": not_attr + " { attribute_adjustment == scale }"},
        "randomization_by": {"folder": "Random", "label": "Randomization By",
                             "menu": {"element_number": "Element Number",
                                      "custom_attribute": "Custom Attribute"}},
        "custom_attribute": {"folder": "Random", "label": "Custom Attribute",
                             "disable": "{ randomization_by == element_number }"},
        "rand_seed": {"folder": "Random", "label": "Seed"},
        **_aa2_noise_spec("{ pattern_type != noise }"),
        "use_minimum": {"folder": "Post-Process", "section": None, "gate": None,
                        "in_toggle": "minimum"},
        "minimum": {"folder": "Post-Process", "section": None, "toggle": "use_minimum",
                    "label": "Minimum"},
        "use_maximum": {"folder": "Post-Process", "section": None, "gate": None,
                        "in_toggle": "maximum"},
        "maximum": {"folder": "Post-Process", "section": None, "toggle": "use_maximum",
                    "label": "Maximum"},
    }
    if not integer:
        inputs.update({
            "blend_mode": {"label": "Blend",
                           "menu": {"constant": "Constant", "attribute": "Use Attribute"}},
            "blend": {"label": "Blend", "hide": "{ blend_mode != constant }"},
            "blend_attribute": {"label": "Blend Attribute",
                                "hide": "{ blend_mode != attribute }"},
        })
    return {"order": order, "inputs": inputs}


SPECS.update({
    "PCG_AttribAdjustFloat": _aa2_scalar_node(False),
    "PCG_AttribAdjustInteger": _aa2_scalar_node(True),
})


def _aa2_toggle_row(use, val, label, folder):
    return {use: {"folder": folder, "section": None, "gate": None, "in_toggle": val},
            val: {"folder": folder, "section": None, "toggle": use, "label": label}}


def _aa2_vector_node():
    """Attribute Adjust Vector. Conditions checked against attribadjust2.adjust_vector():
    scalar adjust value (length / angle / Bias) = Length Only or Rotate / Spread / Interpolate."""
    pre, adj, post = "Pre-Process", "Adjustment Value", "Post-Process"
    scalar = ("{ adjustment_for == length_only } { operation == rotate } "
              "{ operation == spread } { operation == interpolate }")
    vector = ("{ adjustment_for != length_only operation != rotate "
              "operation != spread operation != interpolate }")
    not_rn = "{ adjust_with == constant } { adjust_with == attribute }"
    vr = scalar + " " + not_rn
    off = "{ enable_preprocess == 0 }"
    ini = "{ enable_preprocess == 0 } { overwrite_initial == 0 }"
    order = (["group", "attribute_name", "attribute_class",
              "enable_preprocess", "overwrite_initial", "initial_from",
              "initial_vector_x", "initial_vector_y", "initial_vector_z", "initial_attribute",
              "reverse_direction", "pre_unit_length", "use_pre_length_scale", "pre_length_scale",
              "adjust_value", "adjustment_for", "operation", "adjust_with",
              "constant_vector_x", "constant_vector_y", "constant_vector_z", "scalar_value",
              "vector_range", "amplitude", "amplitude_scale_x", "amplitude_scale_y",
              "amplitude_scale_z", "min_vector_x", "min_vector_y", "min_vector_z",
              "max_vector_x", "max_vector_y", "max_vector_z", "vector_list"]
             + _aa2_scalar_order("")
             + ["axis_from", "axis_x", "axis_y", "axis_z", "axis_attribute",
                "goal_from", "goal_x", "goal_y", "goal_z", "goal_attribute",
                "adjustment_attribute", "randomization_by", "custom_attribute", "rand_seed"]
             + _AA2_NOISE_ORDER
             + ["blend_mode", "blend", "blend_attribute", "blend_type",
                "use_post_length_scale", "post_length_scale", "use_min_length", "min_length",
                "use_max_length", "max_length", "post_unit_length", "length_attribute"])
    src = {"constant": "Constant Value", "attribute": "From Attribute"}
    inputs = {
        "attribute_name": {"label": "Attribute Name"},
        "attribute_class": {"label": "Attribute Class", "menu": _CLASS_MENU},
        "enable_preprocess": {"folder": pre, "label": "Enable Pre-Process"},
        "overwrite_initial": {"folder": pre, "label": "Overwrite Initial Value", "disable": off},
        "initial_from": {"folder": pre, "label": "Initial Value From", "disable": ini,
                         "menu": {"constant": "Constant Value", "normal": "Normal Attribute",
                                  "attribute": "Vector Attribute"}},
        "initial_vector_x": {"folder": pre, "row": {"label": "Initial Vector"}, "disable": ini,
                             "hide": "{ initial_from != constant }"},
        "initial_vector_y": {"folder": pre}, "initial_vector_z": {"folder": pre},
        "initial_attribute": {"folder": pre, "label": "Vector Attribute", "disable": ini,
                              "hide": "{ initial_from != attribute }"},
        "reverse_direction": {"folder": pre, "label": "Reverse Direction", "disable": off},
        "pre_unit_length": {"folder": pre, "label": "Make Vectors Unit Length", "disable": off},
        **_aa2_toggle_row("use_pre_length_scale", "pre_length_scale", "Length Scale", pre),
        "adjust_value": {"folder": adj, "label": "Adjust Value"},
        "adjustment_for": {"folder": adj, "label": "Adjustment for",
                           "disable": "{ adjust_value == 0 }",
                           "menu": {"direction_length": "Direction & Length",
                                    "direction_only": "Direction Only",
                                    "length_only": "Length Only"}},
        "operation": {"folder": adj, "label": "Operation", "disable": "{ adjust_value == 0 }",
                      "menu": dict(_AA2_OPS, set="Set", rotate="Rotate", spread="Spread",
                                   interpolate="Interpolate"),
                      "help": "Set*/Multiply/Min/Max cannot be used with Direction Only; "
                              "Rotate/Spread/Interpolate only with Direction Only; a wrong choice raises an error"},
        "adjust_with": {"folder": adj, "label": "Adjust With",
                        "disable": "{ adjust_value == 0 }",
                        "menu": {"constant": "Constant", "random": "Random",
                                 "noise": "Noise", "attribute": "Attribute"}},
        "constant_vector_x": {"folder": adj, "row": {"label": "Constant Value"},
                              "hide": "{ adjust_with != constant } " + scalar},
        "constant_vector_y": {"folder": adj}, "constant_vector_z": {"folder": adj},
        "scalar_value": {"folder": adj, "label": "Value / Angle / Bias",
                         "hide": "{ adjust_with != constant } " + vector,
                         "help": "Length Only = length; Rotate / Spread = angle (degrees); "
                                 "Interpolate = Bias(0..1)"},
        "vector_range": {"folder": adj, "label": "Range Values", "hide": vr, "sep": True,
                         "menu": {"positive": "Positive", "zero_centered": "Zero Centered",
                                  "min_max": "Min/Max", "specific": "Specific Values"}},
        "amplitude": {"folder": adj, "label": "Amplitude",
                      "hide": vr + " { vector_range == min_max } { vector_range == specific }"},
        "amplitude_scale_x": {"folder": adj, "row": {"label": "Amplitude Scale"},
                              "hide": vr + " { vector_range == min_max } { vector_range == specific }"},
        "amplitude_scale_y": {"folder": adj}, "amplitude_scale_z": {"folder": adj},
        "min_vector_x": {"folder": adj, "row": {"label": "Min Value"},
                         "hide": vr + " { vector_range != min_max }"},
        "min_vector_y": {"folder": adj}, "min_vector_z": {"folder": adj},
        "max_vector_x": {"folder": adj, "row": {"label": "Max Value"},
                         "hide": vr + " { vector_range != min_max }"},
        "max_vector_y": {"folder": adj}, "max_vector_z": {"folder": adj},
        "vector_list": {"folder": adj, "label": "Values",
                        "hide": vr + " { vector_range != specific }"},
        **_aa2_scalar_spec("", vector + " " + not_rn, adj),
        "axis_from": {"folder": adj, "label": "Axis of Rotation", "menu": src,
                      "hide": "{ operation != rotate }", "sep": True},
        "axis_x": {"folder": adj, "row": {"label": "Axis"},
                   "hide": "{ operation != rotate } { axis_from != constant }"},
        "axis_y": {"folder": adj}, "axis_z": {"folder": adj},
        "axis_attribute": {"folder": adj, "label": "Axis Attribute",
                           "hide": "{ operation != rotate } { axis_from != attribute }"},
        "goal_from": {"folder": adj, "label": "Goal Direction", "menu": src,
                      "hide": "{ operation != interpolate }", "sep": True},
        "goal_x": {"folder": adj, "row": {"label": "Goal"},
                   "hide": "{ operation != interpolate } { goal_from != constant }"},
        "goal_y": {"folder": adj}, "goal_z": {"folder": adj},
        "goal_attribute": {"folder": adj, "label": "Goal Attribute",
                           "hide": "{ operation != interpolate } { goal_from != attribute }"},
        "adjustment_attribute": {"folder": adj, "label": "Adjustment Attribute",
                                 "hide": "{ adjust_with != attribute }"},
        "randomization_by": {"folder": "Random", "label": "Randomization By",
                             "menu": {"element_number": "Element Number",
                                      "custom_attribute": "Custom Attribute"}},
        "custom_attribute": {"folder": "Random", "label": "Custom Attribute",
                             "disable": "{ randomization_by == element_number }"},
        "rand_seed": {"folder": "Random", "label": "Seed",
                      "help": "Seed for Random / Noise; also determines the azimuth of Spread"},
        **_aa2_noise_spec("{ adjust_with != noise }"),
        "blend_mode": {"folder": post, "label": "Blend",
                       "menu": {"constant": "Constant", "attribute": "Use Attribute"}},
        "blend": {"folder": post, "label": "Blend", "hide": "{ blend_mode != constant }"},
        "blend_attribute": {"folder": post, "label": "Blend Attribute",
                            "hide": "{ blend_mode != attribute }"},
        "blend_type": {"folder": post, "label": "Blend Type",
                       "menu": {"linear": "Linear", "spherical": "Spherical"}},
        **_aa2_toggle_row("use_post_length_scale", "post_length_scale", "Length Scale", post),
        **_aa2_toggle_row("use_min_length", "min_length", "Minimum Length", post),
        **_aa2_toggle_row("use_max_length", "max_length", "Maximum Length", post),
        "post_unit_length": {"folder": post, "label": "Make Vectors Unit Length"},
        "length_attribute": {"folder": post, "label": "Length Attribute", "sep": True,
                             "help": "Empty = not written; writes the length of the final vector"},
    }
    return {"order": order, "inputs": inputs}


SPECS["PCG_AttribAdjustVector"] = _aa2_vector_node()


def _crow(p, label, folder, **kw):
    """Draws the three parameters r / g / b as one color row."""
    return {p + "_r": dict({"folder": folder, "row": {"kind": "color", "label": label,
                                                      "members": [p + "_r", p + "_g", p + "_b"]}},
                           **kw),
            p + "_g": {"folder": folder}, p + "_b": {"folder": folder}}


def _aa2_color_node():
    """Attribute Adjust Color. Conditions checked against attribadjust2.adjust_color()."""
    pre, adj, cc, post = "Pre-Process", "Adjustment Value", "Color Correction", "Post-Process"
    not_rn = "{ pattern_type != random pattern_type != noise }"
    rv = not_rn + " { range_values != min_max }"
    spec = not_rn + " { range_values != specific }"
    ramp = ("{ pattern_type == constant } { pattern_type == color_attribute } "
            "{ pattern_type == random range_values != color_ramp } "
            "{ pattern_type == noise range_values != color_ramp }")
    src = "{ pattern_type != remap_attribute pattern_type != bounding_box }"
    ini = "{ overwrite_initial == 0 }"
    rgb = lambda p: [p + "_r", p + "_g", p + "_b"]                  # noqa: E731
    order = (["group", "blend_mode", "blend", "blend_attribute", "attribute_name",
              "attribute_class", "delete_other_colors", "overwrite_initial", "initial_from"]
             + rgb("initial_color")
             + ["initial_attribute", "adjust_value", "operation", "pattern_type"] + rgb("color")
             + ["range_values", "color_space"] + rgb("min_color") + rgb("max_color")
             + ["color_ramp", "color_scheme"] + rgb("scheme_color")
             + ["scheme_distance", "color_list", "adjustment_attribute", "source_attribute",
                "bbox_direction_x", "bbox_direction_y", "bbox_direction_z", "compute_range",
                "source_min", "source_max", "randomization_by", "custom_attribute", "rand_seed"]
             + _AA2_NOISE_ORDER
             + ["hue_shift", "saturation", "value", "brightness", "contrast", "gain", "gamma",
                "use_minimum", "minimum", "use_maximum", "maximum", "complement"])
    inputs = {
        "blend_mode": {"label": "Blend",
                       "menu": {"constant": "Constant", "attribute": "Use Attribute"}},
        "blend": {"label": "Blend", "hide": "{ blend_mode != constant }"},
        "blend_attribute": {"label": "Blend Attribute", "hide": "{ blend_mode != attribute }"},
        "attribute_name": {"label": "Attribute Name"},
        "attribute_class": {"label": "Attribute Class", "menu": _CLASS_MENU},
        "delete_other_colors": {"folder": pre, "label": "Delete All Existing Color Attributes",
                                "help": "Deletes same-named attributes on other classes (point color would override primitive color)"},
        "overwrite_initial": {"folder": pre, "label": "Overwrite Initial Color"},
        "initial_from": {"folder": pre, "label": "Initial Color From", "disable": ini,
                         "menu": {"constant": "Constant", "color_attribute": "Color Attribute",
                                  "float_attribute": "Float Attribute"}},
        **_crow("initial_color", "Initial Color", pre, disable=ini,
                hide="{ initial_from != constant }"),
        "initial_attribute": {"folder": pre, "label": "Initial Attribute", "disable": ini,
                              "hide": "{ initial_from == constant }"},
        "adjust_value": {"folder": adj, "label": "Adjust Value"},
        "operation": {"folder": adj, "label": "Operation", "disable": "{ adjust_value == 0 }",
                      "menu": dict(_AA2_OPS, overlay="Overlay", screen="Screen",
                                   hard_mix="Hard Mix", difference="Difference")},
        "pattern_type": {"folder": adj, "label": "Pattern Type",
                         "disable": "{ adjust_value == 0 }",
                         "menu": {"constant": "Constant", "random": "Random", "noise": "Noise",
                                  "color_attribute": "Color Attribute",
                                  "remap_attribute": "Remap Attribute",
                                  "bounding_box": "Bounding Box"}},
        **_crow("color", "Value", adj, hide="{ pattern_type != constant }"),
        "range_values": {"folder": adj, "label": "Range Values", "hide": not_rn, "sep": True,
                         "menu": {"min_max": "Min/Max", "color_ramp": "Color Ramp",
                                  "specific": "Specific Colors"}},
        "color_space": {"folder": adj, "label": "Color Space", "hide": rv,
                        "menu": {"rgb": "RGB", "hsv": "HSV"},
                        "help": "With HSV, the three components of Min / Max are hue (0..1 = one full turn), saturation, value"},
        **_crow("min_color", "Min", adj, hide=rv),
        **_crow("max_color", "Max", adj, hide=rv),
        "color_ramp": {"folder": adj, "label": "Color Ramp", "hide": ramp},
        "color_scheme": {"folder": adj, "label": "Color Scheme", "hide": spec,
                         "menu": {"custom": "Custom (Color List)", "constant": "Constant",
                                  "complementary": "Complementary",
                                  "analogous2": "2 Analogous", "analogous4": "4 Analogous",
                                  "triadic": "Triadic", "tetradic": "Tetradic",
                                  "shades5": "5 Shades", "tints5": "5 Tints"}},
        **_crow("scheme_color", "Color", adj, hide=spec + " { color_scheme == custom }"),
        "scheme_distance": {"folder": adj, "label": "Distance",
                            "hide": spec + " { color_scheme != analogous2 color_scheme != "
                                           "analogous4 color_scheme != tetradic }"},
        "color_list": {"folder": adj, "label": "Colors",
                       "hide": spec + " { color_scheme != custom }"},
        "adjustment_attribute": {"folder": adj, "label": "Adjustment Attribute",
                                 "hide": "{ pattern_type != color_attribute }"},
        "source_attribute": {"folder": adj, "label": "Source Attribute",
                             "hide": "{ pattern_type != remap_attribute }"},
        "bbox_direction_x": {"folder": adj, "row": {"label": "Direction"},
                             "hide": "{ pattern_type != bounding_box }"},
        "bbox_direction_y": {"folder": adj}, "bbox_direction_z": {"folder": adj},
        "compute_range": {"folder": adj, "label": "Compute Range", "hide": src},
        "source_min": {"folder": adj, "row": {"kind": "vector", "label": "Source Range",
                                              "members": ["source_min", "source_max"]},
                       "hide": src, "disable": "{ compute_range == 1 }"},
        "source_max": {"folder": adj, "in_row": "source_min"},
        "randomization_by": {"folder": "Random", "label": "Randomization By",
                             "menu": {"element_number": "Element Number",
                                      "custom_attribute": "Custom Attribute"}},
        "custom_attribute": {"folder": "Random", "label": "Custom Attribute",
                             "disable": "{ randomization_by == element_number }"},
        "rand_seed": {"folder": "Random", "label": "Seed"},
        **_aa2_noise_spec("{ pattern_type != noise }"),
        "hue_shift": {"folder": cc, "label": "Hue Shift"},
        "saturation": {"folder": cc, "label": "Saturation"},
        "value": {"folder": cc, "label": "Value"},
        "brightness": {"folder": cc, "label": "Brightness"},
        "contrast": {"folder": cc, "label": "Contrast"},
        "gain": {"folder": cc, "label": "Gain"},
        "gamma": {"folder": cc, "label": "Gamma"},
        **_aa2_toggle_row("use_minimum", "minimum", "Minimum", post),
        **_aa2_toggle_row("use_maximum", "maximum", "Maximum", post),
        "complement": {"folder": post, "label": "Complement Color"},
    }
    return {"order": order, "inputs": inputs}


SPECS["PCG_AttribAdjustColor"] = _aa2_color_node()
