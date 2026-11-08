"""
Panel specs for group g5: attributes (Blur / Cast / Composite / Copy / Create / Delete / Fade /
Fill / from Camera / from Map / from Pieces / from Volume / Interpolate / Mirror /
Rename / Reorient / String Edit / Transfer / Transfer by UV / Transform Extract),
point and curve frames (Cluster Points / Edge Transport / Enumerate / Orient Along Curve /
Point Velocity / PolyFrame / Tangent Field), conversion and IO (Convert Line / From JSON /
Geo to JSON / Import Mesh / Trace / Volume Rasterize Attributes) and two COPs
(Align / Bake Textures). Format: see the notes at the top of panel_specs.py.

The hide / disable conditions follow the branches where a parameter really takes effect in the node code (nodes*.py run() + geo/
implementation), not a copy of Houdini. Parameters that depend only on "whether some input is wired" (panel conditions
cannot express that) are not hidden; they get a help text instead.
"""

_CLASS_ALL = {"point": "Point", "vertex": "Vertex", "prim": "Primitive",
              "detail": "Detail"}


def _cm(*toks):
    """Labels for the Class dropdown (only the tokens this dropdown really has)."""
    return {t: _CLASS_ALL[t] for t in toks}


_DECODE = {"none": "None", "srgb_to_linear": "sRGB to Linear",
           "linear_to_srgb": "Linear to sRGB"}
_FILTER = {"bilinear": "Bilinear", "closest": "Closest"}
_BORDER = {"clamp": "Clamp", "wrap": "Wrap", "black": "Black"}

# Attribute from Pieces: which modes do not read weights / do not read Rules (branches in attrib_from_pieces)
_AFP_NO_W = ("{ mode == cycle } { mode == vexpression }"
             " { mode == by_attribute map_from != weighted_unit }")
_AFP_NO_RULES = ("{ mode != by_attribute mode != vexpression }"
                 " { mode == by_attribute map_from == weighted_unit }"
                 " { mode == by_attribute map_from == automatic }")

# Attribute from Camera: four-step visibility ladder, each step reads a few more parameters (camproject.visible_mask)
_VIS_NO_FRAME = "{ visibility == all }"                          # all returns immediately
_VIS_NO_FACING = "{ visibility == all } { visibility == frustum }"
_VIS_NO_OCCL = "{ visibility != full }"


SPECS = {
    # ── Attribute Blur SOP:Group / Attributes / Method / Iterations / Step Size
    "PCG_AttribBlur": {
        "order": ["group", "attribute_class", "attributes", "mode", "iterations",
                  "step", "mask_attribute", "invert_mask"],
        "inputs": {
            "attribute_class": {"label": "Attribute Class", "menu": _cm("point", "prim")},
            "attributes": {"label": "Attributes"},
            # attribblur.blur: prim goes through _prim_csr (all weights 1), mode is only read in the point mode
            "mode": {"label": "Weighting Method",
                     "menu": {"uniform": "Uniform", "edge_length": "Edge Length"},
                     "hide": "{ attribute_class == prim }"},
            "iterations": {"label": "Blurring Iterations"},
            "step": {"label": "Step Size"},
            "mask_attribute": {"label": "Mask Attribute", "sep": True},
            "invert_mask": {"label": "Invert Mask",
                            "disable": '{ mask_attribute == "" }'},
        },
    },

    # ── Attribute Cast SOP:Class / Attributes / Precision
    "PCG_AttribCast": {
        "order": ["attribute_class", "attributes", "to_type"],
        "inputs": {
            "attribute_class": {"label": "Class",
                                "menu": _cm("point", "vertex", "prim", "detail")},
            "attributes": {"label": "Attributes"},
            "to_type": {"label": "Precision",
                        "menu": {"float32": "32-bit Float", "float64": "64-bit Float",
                                 "int32": "32-bit Integer", "int64": "64-bit Integer",
                                 "string": "String"},
                        "help": "Float to integer rounds to nearest"},
        },
    },

    # ── Attribute Composite SOP (this plugin's version has two layers, background / foreground): Class → two attributes →
    #    Compositing Operation / Alpha → matching method → output name
    "PCG_AttribComposite": {
        "order": ["attribute_class", "bg_attribute", "fg_attribute", "mode",
                  "alpha", "alpha_attribute", "match", "match_attribute", "output"],
        "inputs": {
            "attribute_class": {"label": "Class",
                                "menu": _cm("point", "prim", "vertex", "detail")},
            "bg_attribute": {"label": "Background Attribute"},
            "fg_attribute": {"label": "Foreground Attribute",
                             "help": "Read from the fg input; without fg, read from geo itself"},
            "mode": {"label": "Compositing Operation", "sep": True,
                     "menu": {"over": "Over", "add": "Add", "subtract": "Subtract",
                              "multiply": "Multiply", "divide": "Divide",
                              "screen": "Screen", "overlay": "Overlay",
                              "min": "Minimum", "max": "Maximum",
                              "difference": "Difference", "average": "Mean"}},
            "alpha": {"label": "Alpha"},
            "alpha_attribute": {"label": "Alpha Attribute"},
            # attribute_composite: the detail mode sets mi = 0 directly and skips _match
            "match": {"label": "Match By", "sep": True,
                      "menu": {"index": "Element Number", "attribute": "Attribute"},
                      "hide": "{ attribute_class == detail }"},
            "match_attribute": {"label": "Match Attribute",
                                "hide": "{ match != attribute } { attribute_class == detail }"},
            "output": {"label": "Output Attribute", "sep": True,
                       "help": "Empty = write back to the background attribute"},
        },
    },

    # ── Attribute Copy SOP:Destination Group / Attribute Class / Attribute Name /
    #    ☑ Match by Attribute [id]
    "PCG_AttribCopy": {
        "order": ["group", "attribute_class", "attributes", "groups",
                  "use_match_attribute", "match_attribute"],
        "inputs": {
            "group": {"label": "Destination Group"},
            "attribute_class": {"label": "Attribute Class",
                                "menu": _cm("point", "vertex", "prim", "detail")},
            "attributes": {"label": "Attribute Name"},
            "groups": {"label": "Copy Groups", "help": "These groups on the source are carried over with the same matching"},
            "match_attribute": {"label": "Match by Attribute", "sep": True},
        },
    },

    # ── Attribute Create SOP:Group / Name / Class / Type / Size / Value / String
    "PCG_AttribCreate": {
        "order": ["group", "name", "attribute_class", "attribute_type", "size",
                  "value_x", "string_value", "use_expression", "expression",
                  "only_if_missing"],
        "inputs": {
            "name": {"label": "Name"},
            "attribute_class": {"label": "Class",
                                "menu": _cm("point", "vertex", "prim", "detail")},
            "attribute_type": {"label": "Type",
                               "menu": {"float": "Float", "int": "Integer",
                                        "vector": "Vector", "vector4": "Vector4",
                                        "string": "String"}},
            # attribops.create: vector / vector4 component counts are hard-coded to 3 / 4, string ignores size
            "size": {"label": "Size",
                     "hide": "{ attribute_type == vector } { attribute_type == vector4 } "
                             "{ attribute_type == string }"},
            # The string branch continues before reading value / expression
            "value_x": {"row": {"label": "Value"},
                        "hide": "{ attribute_type == string }",
                        "disable": "{ use_expression == 1 }",
                        "help": "Only the first Size components are used"},
            "string_value": {"label": "String", "hide": "{ attribute_type != string }"},
            "expression": {"label": "Expression",
                           "hide": "{ attribute_type == string }"},
            "only_if_missing": {"label": "Only If Missing", "sep": True},
        },
    },

    # ── Attribute Delete SOP:Point / Vertex / Primitive / Detail Attributes,Delete Non Selected
    "PCG_AttribDelete": {
        "order": ["point", "vertex", "prim", "detail", "delete_non_selected"],
        "inputs": {
            "point": {"label": "Point Attributes"},
            "vertex": {"label": "Vertex Attributes"},
            "prim": {"label": "Primitive Attributes"},
            "detail": {"label": "Detail Attributes"},
            "delete_non_selected": {"label": "Delete Non Selected", "sep": True,
                                    "help": "Leaving a field empty = that class is untouched (empty does not mean select all)"},
        },
    },

    # ── Attribute Fade: Group / Class / Attribute → distance → Falloff section
    "PCG_AttribFade": {
        "order": ["group", "cls", "attribute_name", "metric", "radius",
                  "from_boundary", "falloff_ramp", "ramp_mode", "inside_value",
                  "outside_value", "invert", "combine"],
        "inputs": {
            "cls": {"label": "Class", "menu": _cm("point", "prim")},
            "attribute_name": {"label": "Attribute Name"},
            "metric": {"label": "Distance Metric", "sep": True,
                       "menu": {"steps": "Edge Steps", "distance": "Distance"}},
            "radius": {"label": "Radius"},
            "from_boundary": {"label": "From Group Boundary"},
            "falloff_ramp": {"label": "Falloff Ramp"},
            "inside_value": {"label": "Inside Value"},
            "outside_value": {"label": "Outside Value"},
            "invert": {"label": "Invert Ramp"},
            "combine": {"label": "Combine",
                        "menu": {"set": "Set", "add": "Add", "multiply": "Multiply",
                                 "max": "Maximum", "min": "Minimum"}},
        },
    },

    # ── Attribute Fade SOP (Houdini semantics, over time): Visualize / Group, two sections Attributes and Timings
    "PCG_AttribFadeTime": {
        "order": ["visualize", "group", "fade_attribute", "start_attribute", "start_retime",
                  "hold_scale_attribute", "frame", "frame_offset", "fade_in", "fade_hold",
                  "fade_out", "fade_in_ramp", "fade_in_ramp_mode", "fade_out_ramp",
                  "fade_out_ramp_mode"],
        "inputs": {
            "visualize": {"label": "Visualize Fade"},
            "group": {"label": "Point Group"},
            "fade_attribute": {"label": "Fade", "section": "Attributes"},
            "start_attribute": {"label": "Fade Start Frame", "section": "Attributes",
                                "help": "Read from the second input when wired (by point number)"},
            "start_retime": {"label": "Start Frame Retime", "section": "Attributes",
                             "help": "Attribute value × this number = frames; use the FPS if the attribute is in seconds"},
            "hold_scale_attribute": {"label": "Hold Frame Scale", "section": "Attributes",
                                     "help": "Read from the third input when wired (by point number)"},
            "frame": {"label": "Frame", "section": "Timings",
                      "help": "Current frame (ComfyUI has no $F; wire in a playbar / value node)"},
            "frame_offset": {"label": "Frame Offset", "section": "Timings"},
            "fade_in": {"label": "Fade In Frames", "section": "Timings"},
            "fade_hold": {"label": "Fade Hold Frames", "section": "Timings"},
            "fade_out": {"label": "Fade out Frames", "section": "Timings"},
            "fade_in_ramp": {"label": "Fade In Ramp", "section": "Timings"},
            "fade_in_ramp_mode": {"section": "Timings",
                                  "menu": {"linear": "Linear", "smooth": "Smooth",
                                           "constant": "Constant"}},
            "fade_out_ramp": {"label": "Fade Out Ramp", "section": "Timings"},
            "fade_out_ramp_mode": {"section": "Timings",
                                   "menu": {"linear": "Linear", "smooth": "Smooth",
                                            "constant": "Constant"}},
        },
    },

    # ── Attribute Fill SOP: Group (known points) / Attribute / Method, method-specific parameters appear per method
    "PCG_AttribFill": {
        "order": ["method", "attribute", "speed_attribute", "match_attribute",
                  "weight_attribute", "known_group", "weights", "iterations",
                  "min_edge_length", "min_speed", "diffusion_time", "unreachable_time",
                  "extrapolation", "tangential_only", "global_rotation"],
        "inputs": {
            "known_group": {"label": "Boundary Group",
                            "help": "Called Known Group in the three old modes; for Diffusion, empty = no fixed sources"},
            "attribute": {"label": "Attribute"},
            "method": {"label": "Mode",
                       "menu": {"harmonic": "Harmonic (Laplace)",
                                "nearest": "Nearest Known Point",
                                "diffuse": "Diffuse",
                                "eikonal": "Eikonal", "poisson": "Poisson",
                                "diffusion": "Diffusion", "extrapolate": "Extrapolate"}},
            "speed_attribute": {"label": "Speed Attribute",
                                "hide": "{ method != eikonal method != diffusion }"},
            "match_attribute": {"label": "Attribute to Match", "hide": "{ method != poisson }"},
            "weight_attribute": {"label": "Weight Attribute", "hide": "{ method != poisson }",
                                 "disable": '{ match_attribute == "" }'},
            # attrib_fill: nearest uses Dijkstra (edge length as distance) and does not read the _edge_graph weights;
            # the four new modes compute their own edge weights
            "weights": {"label": "Edge Weights", "sep": True,
                        "menu": {"uniform": "Uniform",
                                 "inverse_length": "Inverse Edge Length"},
                        "hide": "{ method != harmonic method != diffuse }"},
            "iterations": {"label": "Iterations", "hide": "{ method != diffuse }"},
            "min_edge_length": {"label": "Minimum Edge Length",
                                "hide": "{ method != poisson method != diffusion }"},
            "min_speed": {"label": "Minimum Speed",
                          "hide": "{ method != eikonal method != diffusion }"},
            "diffusion_time": {"label": "Diffusion Time", "hide": "{ method != diffusion }"},
            "unreachable_time": {"label": "Unreachable Time", "hide": "{ method != eikonal }"},
            "extrapolation": {"label": "Extrapolation Type", "hide": "{ method != extrapolate }",
                              "menu": {"scalar": "Scalar",
                                       "parallel_transport": "Parallel Transport"}},
            "tangential_only": {"label": "Tangential Component Only",
                                "hide": "{ method != extrapolate }",
                                "disable": "{ extrapolation == scalar }"},
            "global_rotation": {"label": "Global Rotation",
                                "hide": "{ method != extrapolate }",
                                "disable": "{ extrapolation == scalar }"},
        },
    },

    # ── Attribute from Camera (this plugin's own node): Group / Class / Attribute on top,
    #    three tabs Sampling / Visibility / Output; visibility parameters appear step by step along the four-step ladder
    "PCG_AttribFromCamera": {
        "order": ["group", "class", "name",
                  # Sampling
                  "layer", "channels", "decode", "filter", "border", "scale",
                  "offset", "blend",
                  # Visibility
                  "visibility", "border_margin", "facing_min", "normal_attrib",
                  "occlusion", "depth_bias", "silhouette_guard",
                  "missing", "missing_value",
                  # Output
                  "visible_group", "mask_group", "threshold", "threshold_channel",
                  "uv_name"],
        "inputs": {
            "class": {"label": "Class", "menu": _cm("point", "vertex", "prim")},
            "name": {"label": "Export Attribute"},

            "layer": {"folder": "Sampling", "label": "Layer"},
            "channels": {"folder": "Sampling", "label": "Channels",
                         "help": "Empty = all channels; \"0\" / \"0,2\" picks specific channels"},
            "decode": {"folder": "Sampling", "label": "Decode", "menu": _DECODE},
            "filter": {"folder": "Sampling", "label": "Filter", "menu": _FILTER},
            "border": {"folder": "Sampling", "label": "Border", "menu": _BORDER},
            "scale": {"folder": "Sampling", "label": "Scale", "sep": True},
            "offset": {"folder": "Sampling", "label": "Offset"},
            "blend": {"folder": "Sampling", "label": "Blend"},

            "visibility": {"folder": "Visibility", "section": None,
                           "label": "Visibility Test",
                           "menu": {"all": "All (No Test)", "frustum": "In Frustum",
                                    "front": "Frustum + Facing",
                                    "full": "Frustum + Facing + Occlusion"}},
            "border_margin": {"folder": "Visibility", "section": None,
                              "label": "Border Margin", "hide": _VIS_NO_FRAME},
            "facing_min": {"folder": "Visibility", "section": None,
                           "label": "Min Facing", "hide": _VIS_NO_FACING},
            "normal_attrib": {"folder": "Visibility", "section": None,
                              "label": "Normal Attribute", "hide": _VIS_NO_FACING},
            "occlusion": {"folder": "Visibility", "section": None,
                          "label": "Occlusion Test",
                          "menu": {"element+depth": "Element ID + Depth",
                                   "element": "Element ID", "depth": "Depth"},
                          "hide": _VIS_NO_OCCL},
            # The element mode only compares triangle indices and does not read depth_bias
            "depth_bias": {"folder": "Visibility", "section": None,
                           "label": "Depth Bias",
                           "hide": "{ visibility != full } { occlusion == element }",
                           "help": "Fraction of the bounding sphere radius"},
            "silhouette_guard": {"folder": "Visibility", "section": None,
                                 "label": "Silhouette Guard", "hide": _VIS_NO_OCCL},
            # In the all mode every element is visible, so the missing branch is never taken
            "missing": {"folder": "Visibility", "section": "Not Visible",
                        "label": "Not Visible",
                        "menu": {"keep": "Keep Original", "zero": "Zero",
                                 "value": "Value"},
                        "hide": _VIS_NO_FRAME},
            "missing_value": {"folder": "Visibility", "section": "Not Visible",
                              "label": "Value",
                              "hide": "{ visibility == all } { missing != value }"},

            "visible_group": {"folder": "Output", "section": None,
                              "label": "Visible Group", "help": "Empty = no group created"},
            "mask_group": {"folder": "Output", "section": None,
                           "label": "Mask Group", "help": "Empty = no group created"},
            "threshold": {"folder": "Output", "section": None, "label": "Threshold",
                          "disable": '{ mask_group == "" }'},
            "threshold_channel": {"folder": "Output", "section": None,
                                  "label": "Threshold Channel",
                                  "disable": '{ mask_group == "" }'},
            "uv_name": {"folder": "Output", "section": None, "sep": True,
                        "label": "Screen UV Attribute"},
        },
    },

    # ── Attribute from Map SOP:Group / Texture Channel / UV Attribute / Export Attribute,
    #    followed by three sections Color / Filter / Image (UV transform)
    "PCG_AttribFromMap": {
        "order": ["group", "class", "layer", "name",
                  "channels", "decode", "scale", "offset", "blend",
                  "filter", "border",
                  "uv_attrib", "uv_from", "uv_scale_u", "uv_offset_u"],
        "inputs": {
            "class": {"label": "Class", "menu": _cm("point", "vertex", "prim")},
            "layer": {"label": "Texture Layer"},
            "name": {"label": "Export Attribute"},
            "channels": {"section": "Color", "label": "Color Channels",
                         "help": "Empty = all channels; \"0\" / \"0,2\" picks specific channels"},
            "decode": {"section": "Color", "label": "Decode", "menu": _DECODE},
            "scale": {"section": "Color", "label": "Scale"},
            "offset": {"section": "Color", "label": "Offset"},
            "blend": {"section": "Color", "label": "Blend"},
            "filter": {"section": "Filter", "label": "Filter Type", "menu": _FILTER},
            "border": {"section": "Filter", "label": "Wrap", "menu": _BORDER},
            "uv_attrib": {"label": "UV Attribute"},
            "uv_from": {"label": "UV Source",
                        "menu": {"auto": "Automatic", "vertex": "Vertex",
                                 "point": "Point"}},
            "uv_scale_u": {"row": {"label": "UV Scale"}},
            "uv_offset_u": {"row": {"label": "UV Translate"}},
        },
    },

    # ── Attribute from Pieces SOP:Mode(Cycle / Patches / Noise / Random / Map Attribute /
    # VEXpression) decides which parameters appear. Houdini has one page + several sections with many parameters; split into tabs here
    "PCG_AttribFromPieces": {
        "order": ["group", "attribute_class", "piece_attribute", "mode", "count",
                  "library_attribute", "piece_filter", "copy_attributes", "allow_p",
                  "promotion",
                  "shuffle", "rand_seed", "offset",
                  "use_id_attribute", "id_attribute", "location_attribute",
                  "element_size", "element_scale_x", "element_scale_y", "element_scale_z",
                  "noise_offset_x", "noise_offset_y", "noise_offset_z",
                  "noise_type", "max_octaves", "roughness",
                  "weight_method", "weights", "weight_attribute",
                  "input_attribute", "map_from", "rules", "unmatched_piece",
                  "unmatched_group",
                  "output", "index_output"],
        "inputs": {
            "attribute_class": {"label": "Attribute Class",
                                "menu": _cm("point", "prim", "vertex")},
            "piece_attribute": {"label": "Piece Attribute",
                                "help": "When given, the whole piece gets the same variant"},
            "mode": {"label": "Mode", "sep": True,
                     "menu": {"random": "Random", "cycle": "Cycle",
                              "by_attribute": "Map Attribute", "patches": "Patches",
                              "noise": "Noise", "vexpression": "VEXpression"}},
            "count": {"label": "Number of Pieces", "help": "Only used when no library is wired"},
            "library_attribute": {"label": "Library Attribute",
                                  "help": "Only used when a library is wired"},
            "piece_filter": {"label": "Piece Filter", "help": "Space-separated piece names; empty = all"},
            "copy_attributes": {"label": "Copy Attributes", "help": "Only used when a library is wired"},
            "allow_p": {"label": "Allow P Attribute", "disable": '{ copy_attributes == "" }'},
            "promotion": {"label": "Promotion Method", "disable": '{ copy_attributes == "" }',
                          "menu": {"max": "Maximum", "min": "Minimum", "mean": "Average",
                                   "mode": "Mode", "median": "Median", "sum": "Sum",
                                   "sum_squares": "Sum of Squares",
                                   "rms": "Root Mean Square", "first": "First Match",
                                   "last": "Last Match"}},
            "shuffle": {"folder": "Pieces", "label": "Shuffle"},
            # Seed drives Shuffle, Random, the Patches / Noise seed, and picking one of several in Rules -- not hidden
            "rand_seed": {"folder": "Pieces", "label": "Seed"},
            "offset": {"folder": "Pieces", "label": "Offset"},
            "use_id_attribute": {"folder": "Source Points", "section": None, "gate": None,
                                 "in_toggle": "id_attribute", "label": "Override Ptnum"},
            "id_attribute": {"folder": "Source Points", "section": None,
                             "toggle": "use_id_attribute", "label": "ID Attribute"},
            "location_attribute": {"folder": "Source Points", "label": "Location Attribute",
                                   "hide": "{ mode != patches mode != noise }"},
            "element_size": {"folder": "Patches / Noise", "label": "Element Size",
                             "hide": "{ mode != patches mode != noise }"},
            "element_scale_x": {"folder": "Patches / Noise",
                                "row": {"kind": "vector", "label": "Element Scale",
                                        "members": ["element_scale_x", "element_scale_y",
                                                    "element_scale_z"]},
                                "hide": "{ mode != patches mode != noise }"},
            "noise_offset_x": {"folder": "Patches / Noise",
                               "row": {"kind": "vector", "label": "Offset",
                                       "members": ["noise_offset_x", "noise_offset_y",
                                                   "noise_offset_z"]},
                               "hide": "{ mode != patches mode != noise }"},
            "noise_type": {"folder": "Patches / Noise", "label": "Noise Type",
                           "hide": "{ mode != noise }",
                           "menu": {"value": "Value", "perlin": "Perlin",
                                    "simplex": "Simplex", "worley": "Worley Cellular F1",
                                    "worley_f2f1": "Worley Cellular F2-F1"}},
            "max_octaves": {"folder": "Patches / Noise", "label": "Max Octaves",
                            "hide": "{ mode != noise }"},
            "roughness": {"folder": "Patches / Noise", "label": "Roughness",
                          "hide": "{ mode != noise }"},
            # Weights: not read by cycle, Map Attribute's Automatic / Explicit / String, or VEXpression
            "weight_method": {"folder": "Random", "label": "Weight Method",
                              "hide": _AFP_NO_W,
                              "menu": {"auto": "Automatic (legacy)",
                                       "uniform": "Uniform Distribution",
                                       "piece_weights": "Piece Weights",
                                       "weight_attribute": "Weight Attribute"}},
            "weights": {"folder": "Random", "label": "Piece Weights",
                        "hide": _AFP_NO_W + " { weight_method == uniform }"
                                            " { weight_method == weight_attribute }",
                        "help": "Numbers in order, or piece_name:weight; the auto mode only reads it when no library is wired"},
            "weight_attribute": {"folder": "Random", "label": "Weight Attribute",
                                 "hide": _AFP_NO_W + " { weight_method == uniform }"
                                                     " { weight_method == piece_weights }",
                                 "help": "Only used when a library is wired"},
            "input_attribute": {"folder": "Map Attribute", "label": "Attribute",
                                "hide": "{ mode != by_attribute }"},
            "map_from": {"folder": "Map Attribute", "label": "Map Pieces From",
                         "hide": "{ mode != by_attribute }",
                         "menu": {"weighted_unit": "Weighted 0-1 (legacy)",
                                  "automatic": "Automatic Ranges",
                                  "explicit": "Explicit Ranges",
                                  "string": "String Values"}},
            "rules": {"folder": "Map Attribute", "label": "Rules", "hide": _AFP_NO_RULES,
                      "help": "One per line 'piece[ piece...] : condition'; Explicit takes min max, String a pattern, "
                              "VEXpression an expression"},
            "unmatched_piece": {"folder": "Map Attribute", "label": "Unmatched Piece",
                                "hide": _AFP_NO_RULES},
            "unmatched_group": {"folder": "Map Attribute", "label": "Unmatched Group",
                                "hide": _AFP_NO_RULES},
            "output": {"label": "Output Attribute", "sep": True},
            "index_output": {"label": "Index Attribute", "help": "Empty = not written"},
        },
    },

    # ── Attribute from Volume SOP:Group / Class / Volume / Attribute / Sampling / Outside
    "PCG_AttribFromVolume": {
        "order": ["group", "attribute_class", "volume_select", "attribute", "mode",
                  "outside", "outside_value"],
        "inputs": {
            "attribute_class": {"label": "Class", "menu": _cm("point", "prim")},
            "volume_select": {"label": "Volume Primitive",
                              "help": "Empty = first volume; a number = the n-th one; a name = the prim's name"},
            "attribute": {"label": "Attribute"},
            "mode": {"label": "Sampling",
                     "menu": {"trilinear": "Trilinear", "nearest": "Nearest",
                              "gradient": "Gradient"}},
            "outside": {"label": "Outside Volume", "sep": True,
                        "menu": {"clamp": "Clamp to Border",
                                 "constant": "Constant Value",
                                 "keep": "Keep Original"}},
            # sample_volume: only constant replaces values outside the volume with outside_value
            "outside_value": {"label": "Outside Value",
                              "hide": "{ outside != constant }"},
        },
    },

    # ── Attribute Interpolate SOP:Group / Attributes / Primitive Number / ☑ Primitive UV
    "PCG_AttribInterpolate": {
        "order": ["group", "attribute_class", "attributes", "prim_attribute",
                  "use_uv_attribute", "uv_attribute"],
        "inputs": {
            "attribute_class": {"label": "Attribute Class", "menu": _cm("point", "vertex")},
            "attributes": {"label": "Attributes"},
            "prim_attribute": {"label": "Primitive Number Attribute", "sep": True},
            "uv_attribute": {"label": "Primitive UV Attribute",
                             "help": "Off = barycentric coordinates are recovered from the point position (more accurate on quads)"},
        },
    },

    # ── Attribute Mirror SOP: Group / Attributes / Origin / Direction / lookup method / vector type
    "PCG_AttribMirror": {
        "order": ["group", "attributes", "origin_x", "direction_x", "source_side",
                  "lookup", "tolerance", "max_distance", "vectors", "quaternions"],
        "inputs": {
            "group": {"help": "Only writes these points (on the other side)"},
            "attributes": {"label": "Attributes"},
            "origin_x": {"sep": True},
            "source_side": {"label": "Source Side",
                            "menu": {"positive": "Positive", "negative": "Negative"}},
            "lookup": {"label": "Lookup Method", "sep": True,
                       "menu": {"closest_point": "Closest Point",
                                "surface": "Closest Surface"}},
            "tolerance": {"label": "Plane Tolerance"},
            "max_distance": {"label": "Max Distance", "help": "0 = unlimited"},
            "vectors": {"label": "Vector Attributes", "sep": True},
            "quaternions": {"label": "Quaternion Attributes"},
        },
    },

    # ── Attribute Rename SOP: Class / rename table
    "PCG_AttribRename": {
        "order": ["attribute_class", "rename", "rename_groups"],
        "inputs": {
            "attribute_class": {"label": "Class",
                                "menu": _cm("point", "vertex", "prim", "detail")},
            "rename": {"label": "Rename", "help": "old:new, space-separated for several; * supported"},
            "rename_groups": {"label": "Rename Groups"},
        },
    },

    # ── Attribute Reorient SOP
    "PCG_AttribReorient": {
        "order": ["attributes"],
        "inputs": {
            "attributes": {"label": "Attributes",
                           "help": "Vectors are rotated by the local rotation, quaternions are left-multiplied"},
        },
    },

    # ── Attribute String Edit SOP: Group / Class / Attributes / match method / Find → Replace
    "PCG_AttribStringEdit": {
        "order": ["group", "attribute_class", "attributes", "mode",
                  "case_sensitive", "find", "replace"],
        "inputs": {
            # string_edit: in the detail mode sel = None, group is not read
            "group": {"hide": "{ attribute_class == detail }"},
            "attribute_class": {"label": "Class",
                                "menu": _cm("prim", "point", "vertex", "detail")},
            "attributes": {"label": "Attributes"},
            "mode": {"label": "Match Mode",
                     "menu": {"substring": "Substring", "wildcard": "Wildcard",
                              "regex": "Regular Expression"}},
            "case_sensitive": {"label": "Case Sensitive"},
            "find": {"label": "Find", "sep": True},
            "replace": {"label": "Replace"},
        },
    },

    # ── Attribute Transfer SOP: two tabs, Attributes / Conditions
    "PCG_AttribTransfer": {
        "order": ["source_group", "dest_group", "prim_attributes",
                  "point_attributes", "detail_attributes", "point_groups",
                  "prim_groups", "distance_threshold", "blend_width",
                  "max_sample_count", "kernel", "match_attribute"],
        "inputs": {
            "source_group": {"folder": "Attributes", "label": "Source Group"},
            "dest_group": {"folder": "Attributes", "label": "Destination Group"},
            "prim_attributes": {"folder": "Attributes", "section": None,
                                "label": "Primitives", "sep": True},
            "point_attributes": {"folder": "Attributes", "section": None,
                                 "label": "Points"},
            "detail_attributes": {"folder": "Attributes", "section": None,
                                  "label": "Detail"},
            "point_groups": {"folder": "Attributes", "section": None,
                             "label": "Point Groups", "sep": True},
            "prim_groups": {"folder": "Attributes", "section": None,
                            "label": "Primitive Groups"},
            "distance_threshold": {"folder": "Conditions", "section": None,
                                   "label": "Distance Threshold"},
            "blend_width": {"folder": "Conditions", "section": None,
                            "label": "Blend Width"},
            "max_sample_count": {"folder": "Conditions", "section": None,
                                 "label": "Max Sample Count"},
            # With only 1 sample the normalized weight is always 1, so the kernel has no effect
            "kernel": {"folder": "Conditions", "section": None,
                       "label": "Kernel Function",
                       "menu": {"uniform": "Uniform",
                                "inverse_distance": "Inverse Distance",
                                "tent": "Tent", "gaussian": "Gaussian",
                                "smooth": "Wyvill"},
                       "disable": "{ max_sample_count <= 1 }"},
            "match_attribute": {"folder": "Conditions", "section": None,
                                "label": "Match Attribute", "sep": True},
        },
    },

    # ── Attribute Transfer by UV
    "PCG_AttribTransferByUV": {
        "order": ["group", "attribute_class", "attributes", "uv_attribute",
                  "source_uv", "outside", "max_distance"],
        "inputs": {
            "group": {"help": "Only applies in the point mode"},
            "attribute_class": {"label": "Class", "menu": _cm("point", "vertex")},
            "attributes": {"label": "Attributes"},
            "uv_attribute": {"label": "UV Attribute", "sep": True},
            "source_uv": {"label": "Source UV Attribute",
                          "help": "Empty = same as UV Attribute"},
            "outside": {"label": "Outside UV Islands", "sep": True,
                        "menu": {"nearest": "Nearest Triangle",
                                 "keep": "Keep Original"}},
            # max_distance only goes into closest_surface for outside == nearest
            "max_distance": {"label": "Max Distance", "hide": "{ outside == keep }",
                             "help": "Distance in UV space; 0 = unlimited"},
        },
    },

    # ── Attribute Transform Extract
    "PCG_AttribTransformExtract": {
        "order": ["piece_attribute"],
        "inputs": {"piece_attribute": {"label": "Piece Attribute"}},
    },

    # ── Attribute Transform Extract SOP (KineFX, Houdini semantics): Group, Euler Filter section, Transform section
    "PCG_AttribTransformExtractHou": {
        "order": ["group", "hierarchy", "piece_attribute", "hint_x", "hint_y", "hint_z",
                  "decomposition", "xform_order", "rotate_order", "attributes",
                  "t_prefix", "t_suffix", "r_prefix", "r_suffix", "stretch_prefix",
                  "stretch_suffix", "s_prefix", "s_suffix", "sh_prefix", "sh_suffix"],
        "inputs": {
            "hierarchy": {"label": "Hierarchy Source", "section": "Euler Filter",
                          "menu": {"none": "None", "topology": "Topology",
                                   "pieces_points": "Pieces or Points"}},
            "piece_attribute": {"label": "Piece Attribute", "section": "Euler Filter",
                                "hide": "{ hierarchy != pieces_points }"},
            "hint_x": {"section": "Euler Filter",
                       "row": {"kind": "vector", "label": "Hint",
                               "members": ["hint_x", "hint_y", "hint_z"]}},
            "decomposition": {"label": "Decomposition", "section": "Transform",
                              "menu": {"polar": "Polar Decomposition",
                                       "crack": "Crack Transform"}},
            # polar takes the translation straight from row 4 and ignores Transform Order (xformextract.attrib_transform_extract)
            "xform_order": {"label": "Transform Order", "section": "Transform",
                            "disable": "{ decomposition == polar }",
                            "menu": {"srt": "Scale Rot Trans", "str": "Scale Trans Rot", "rst": "Rot Scale Trans", "rts": "Rot Trans Scale", "tsr": "Trans Scale Rot", "trs": "Trans Rot Scale"}},
            "rotate_order": {"label": "Rotation Order", "section": "Transform",
                             "menu": {"xyz": "Rx Ry Rz", "xzy": "Rx Rz Ry", "yxz": "Ry Rx Rz", "yzx": "Ry Rz Rx", "zxy": "Rz Rx Ry", "zyx": "Rz Ry Rx"}},
            "attributes": {"label": "Attributes", "section": "Transform"},
            # A row can only hold number fields; prefix / suffix each take their own row
            "t_prefix": {"label": "Translation Prefix", "section": "Transform",
                         "help": "Translation is only computed for 16-component matrices"},
            "t_suffix": {"label": "Translation Suffix", "section": "Transform"},
            "r_prefix": {"label": "Rotation Prefix", "section": "Transform"},
            "r_suffix": {"label": "Rotation Suffix", "section": "Transform"},
            "stretch_prefix": {"label": "Stretch Prefix", "section": "Transform",
                               "hide": "{ decomposition != polar }"},
            "stretch_suffix": {"label": "Stretch Suffix", "section": "Transform",
                               "hide": "{ decomposition != polar }"},
            "s_prefix": {"label": "Scale Prefix", "section": "Transform",
                         "hide": "{ decomposition != crack }"},
            "s_suffix": {"label": "Scale Suffix", "section": "Transform",
                         "hide": "{ decomposition != crack }"},
            "sh_prefix": {"label": "Shear Prefix", "section": "Transform",
                          "hide": "{ decomposition != crack }"},
            "sh_suffix": {"label": "Shear Suffix", "section": "Transform",
                          "hide": "{ decomposition != crack }"},
        },
    },

    # ── Name SOP: Attribute / Class / Name from Group (+ Group Mask) / Namings, String Editing last
    "PCG_Name": {
        "order": ["attribute", "cls", "name_from_group", "group_mask", "namings",
                  "global_replace", "from_", "to"],
        "inputs": {
            "attribute": {"label": "Attribute"},
            "cls": {"label": "Class", "menu": {"prim": "Primitives", "point": "Points",
                                               "vertex": "Vertices"}},
            "name_from_group": {"label": "Name from Group", "sep": True},
            "group_mask": {"label": "Group Mask", "disable": "{ name_from_group == 0 }"},
            # name_sop: namings is not read when Name from Group is on
            "namings": {"label": "Namings", "hide": "{ name_from_group == 1 }",
                        "help": "One 'group : name' per line; leading # = Enable off; later lines override earlier ones"},
            "global_replace": {"label": "Global", "section": "String Editing"},
            "from_": {"label": "From", "section": "String Editing"},
            "to": {"label": "To", "section": "String Editing"},
        },
    },

    # ── Cluster Points SOP: Group / attribute to cluster by / Clusters / Iterations / Seed / output name
    "PCG_ClusterPoints": {
        "order": ["group", "name", "output", "color_output", "cluster_filter",
                  "attribute", "weight", "control_attribute2", "weight2",
                  "control_attribute3", "weight3",
                  "build_clusters", "clusters", "rand_seed", "iterations",
                  "copy_point_attributes", "max_sample_count", "size_attribute",
                  "padding_min_x", "padding_min_y", "padding_min_z",
                  "padding_max_x", "padding_max_y", "padding_max_z"],
        "inputs": {
            "name": {"label": "Output Attribute"},
            "output": {"label": "Output",
                       "menu": {"cluster_points": "Cluster points", "average_points": "Average points",
                                "both": "Both", "boxes": "Boxes"}},
            "color_output": {"label": "Color Output",
                             "menu": {"points": "Points", "colored_points": "Colored Points",
                                      "colored_particles": "Colored Particles"},
                             "help": "Colored Particles is the same as Colored Points (this plugin has no particle system)"},
            "cluster_filter": {"label": "Cluster Filter", "help": "Cluster numbers, same syntax as point numbers: 3 4, 3-6"},
            "attribute": {"label": "Control Attribute", "sep": True,
                          "disable": "{ build_clusters == 0 }"},
            "weight": {"label": "Weight", "disable": "{ build_clusters == 0 }"},
            "control_attribute2": {"label": "Control Attribute 2",
                                   "disable": "{ build_clusters == 0 }"},
            "weight2": {"label": "Weight 2", "disable": "{ build_clusters == 0 }"},
            "control_attribute3": {"label": "Control Attribute 3",
                                   "disable": "{ build_clusters == 0 }"},
            "weight3": {"label": "Weight 3", "disable": "{ build_clusters == 0 }"},
            "build_clusters": {"label": "Build Clusters", "section": "Cluster Settings",
                               "help": "Off: uses the existing Output Attribute on the points directly, no k-means"},
            "clusters": {"label": "Clusters", "section": "Cluster Settings",
                         "disable": "{ build_clusters == 0 }"},
            "rand_seed": {"label": "Seed", "section": "Cluster Settings",
                          "disable": "{ build_clusters == 0 }"},
            "iterations": {"label": "Refinement Iterations", "section": "Cluster Settings",
                           "disable": "{ build_clusters == 0 }"},
            "copy_point_attributes": {"label": "Copy Point Attributes from Cluster",
                                      "section": "Averaging Settings",
                                      "hide": "{ output == cluster_points } { output == boxes }"},
            "max_sample_count": {"label": "Max Sample Count", "section": "Averaging Settings",
                                 "hide": "{ output == cluster_points } { output == boxes }",
                                 "disable": "{ copy_point_attributes == 0 }"},
            "size_attribute": {"label": "Size Attribute Name", "section": "Averaging Settings",
                               "hide": "{ output == cluster_points } { output == boxes }"},
            "padding_min_x": {"row": {"label": "Padding Min"}, "section": "Averaging Settings",
                              "hide": "{ output == cluster_points }"},
            "padding_max_x": {"row": {"label": "Padding Max"}, "section": "Averaging Settings",
                              "hide": "{ output == cluster_points }"},
        },
    },

    # ── Edge Transport SOP: Root Group / Method / Operation / Attribute / output
    "PCG_EdgeTransport": {
        "order": ["method", "curve_group", "point_group", "attribute", "direction",
                  "parent_attribute", "root_choice", "root_group", "operation",
                  "use_normalization", "normalization", "new_root_value", "integrate_constant",
                  "scale_by_edge_length", "split_method", "merge_method",
                  "output", "unreached_group"],
        "inputs": {
            "method": {"label": "Method",
                       "menu": {"network": "Edge Network", "curves": "Each Curve",
                                "parent_attribute": "Parent Attribute"}},
            "curve_group": {"label": "Curve Group", "hide": "{ method != curves }"},
            "point_group": {"label": "Point Group", "hide": "{ method == curves }"},
            # In the distance mode A = None, and the output name does not fall back to it either
            "attribute": {"label": "Attribute", "hide": "{ operation == distance }"},
            "direction": {"label": "Direction", "menu": {"forward": "Forward", "backward": "Backward"},
                          "hide": "{ operation == distance } { operation == copy } { operation == sum } { operation == average }"},
            "parent_attribute": {"label": "Parent Attribute", "hide": "{ method != parent_attribute }"},
            "root_choice": {"label": "Root Choice", "hide": "{ method != network }",
                            "menu": {"group": "Group", "first_point": "First Point",
                                     "last_point": "Last Point"}},
            "root_group": {"label": "Root Group",
                           "hide": "{ method == parent_attribute } { method == network root_choice != group }"},
            "operation": {"label": "Operation", "sep": True,
                          "menu": {"distance": "Distance (PCG)", "copy": "Copy (PCG)",
                                   "sum": "Sum (PCG)", "average": "Average (PCG)",
                                   "transport": "Transport",
                                   "transport_from_root": "Transport from Root",
                                   "total": "Total", "maximum": "Maximum", "minimum": "Minimum"}},
            "use_normalization": {"section": None, "gate": None, "in_toggle": "normalization"},
            "normalization": {"label": "Normalization", "section": None, "toggle": "use_normalization",
                              "menu": {"per_component": "Per-Component", "global": "Global"}},
            "new_root_value": {"label": "New Root Value", "menu": {"zero": "Zero", "hold": "Hold"},
                               "hide": "{ operation != transport operation != transport_from_root }"},
            "integrate_constant": {"label": "Integrate a Constant Value",
                                   "hide": "{ operation != total }"},
            "scale_by_edge_length": {"label": "Scale by Edge Length",
                                     "hide": "{ operation != total }"},
            "split_method": {"label": "Edge Split Method", "menu": {"copy": "Copy", "split": "Split"},
                             "hide": "{ operation == distance } { operation == copy } { operation == sum } { operation == average } { direction != forward } { operation == maximum } { operation == minimum }"},
            "merge_method": {"label": "Edge Merge Method",
                             "menu": {"add": "Add", "maximum": "Maximum", "minimum": "Minimum"},
                             "hide": "{ operation == distance } { operation == copy } { operation == sum } { operation == average } { direction != backward } { operation == maximum } { operation == minimum }"},
            "output": {"label": "Output Attribute", "sep": True,
                       "help": "Empty = distance writes transport, the others write back to Attribute"},
            "unreached_group": {"label": "Unreached Group", "help": "Empty = no group created"},
        },
    },

    # ── Enumerate SOP:Group / Group Type / Piece Attribute / Piece Mode / Attribute /
    #    Format / Start / Increment
    "PCG_Enumerate": {
        "order": ["group", "attribute_class", "mode", "piece_attribute", "order",
                  "name", "format", "start", "step"],
        "inputs": {
            "attribute_class": {"label": "Group Type",
                                "menu": _cm("point", "prim", "vertex")},
            "mode": {"label": "Piece Mode",
                     "menu": {"elements": "Elements", "pieces": "Pieces"}},
            "piece_attribute": {"label": "Piece Attribute"},
            # enumerate_: only the pieces mode, or a given piece_attribute, splits into pieces and looks at the order
            "order": {"label": "Piece Order",
                      "menu": {"first_appearance": "First Appearance",
                               "sorted": "Sorted by Value"},
                      "hide": '{ mode == elements piece_attribute == "" }'},
            "name": {"label": "Attribute", "sep": True},
            "format": {"label": "Format",
                       "help": "Empty = integer; piece_%d / %03d writes a string (as in the Name SOP)"},
            "start": {"label": "Start Value"},
            "step": {"label": "Increment"},
        },
    },

    # ── Orient Along Curve SOP: Group on top, two tabs Frame / Output
    "PCG_OrientAlongCurve": {
        "order": ["group", "tangent_type", "reverse", "up_mode", "up_x",
                  "up_attribute", "roll", "full_twists", "partial_twist",
                  "tangent_name", "up_name", "orient_name", "side_name",
                  "curveu_name"],
        "inputs": {
            "tangent_type": {"folder": "Frame", "label": "Tangent Type",
                             "menu": {"average": "Average of Edges",
                                      "previous": "Previous Edge",
                                      "next": "Next Edge"}},
            "reverse": {"folder": "Frame", "label": "Reverse Direction"},
            "up_mode": {"folder": "Frame", "label": "Up Vector Type", "sep": True,
                        "menu": {"minimal_rotation": "Minimal Rotation",
                                 "constant": "Constant",
                                 "attribute": "Attribute"}},
            # curve_frames: in the attribute mode up comes from a point attribute, the up parameter is not read
            "up_x": {"folder": "Frame", "row": {"label": "Up Vector"},
                     "hide": "{ up_mode == attribute }"},
            "up_y": {"folder": "Frame"}, "up_z": {"folder": "Frame"},
            "up_attribute": {"folder": "Frame", "label": "Up Vector Attribute",
                             "hide": "{ up_mode != attribute }"},
            "roll": {"folder": "Frame", "label": "Roll", "sep": True},
            "full_twists": {"folder": "Frame", "label": "Full Twists"},
            "partial_twist": {"folder": "Frame", "label": "Partial Twist"},
            "tangent_name": {"folder": "Output", "label": "Tangent Attribute",
                             "help": "Empty name = this item is not written"},
            "up_name": {"folder": "Output", "label": "Up Attribute"},
            "orient_name": {"folder": "Output", "label": "Orientation Attribute"},
            "side_name": {"folder": "Output", "label": "Side Attribute"},
            "curveu_name": {"folder": "Output", "label": "Curve U Attribute"},
        },
    },

    # ── Point Velocity SOP: Method / FPS / matching / output
    "PCG_PointVelocity": {
        "order": ["method", "fps", "match", "id_attribute", "compute_accel",
                  "v_attribute"],
        "inputs": {
            "method": {"label": "Method",
                       "menu": {"auto": "Automatic",
                                "central": "Central Difference",
                                "backward": "Backward Difference",
                                "forward": "Forward Difference"},
                       "help": "backward needs prev wired, forward needs next, central needs both"},
            "fps": {"label": "Frames per Second"},
            "match": {"label": "Match Points By", "sep": True,
                      "menu": {"index": "Point Number", "attribute": "Attribute"}},
            "id_attribute": {"label": "ID Attribute", "hide": "{ match != attribute }"},
            "compute_accel": {"label": "Compute Acceleration", "sep": True,
                              "help": "Needs both the previous and next frames wired"},
            "v_attribute": {"label": "Velocity Attribute"},
        },
    },

    # ── PolyFrame SOP: Group / Entity / Style / attribute / Orthogonal / three output names
    "PCG_PolyFrame": {
        "order": ["group", "entity", "style", "uv_attribute", "gradient_attribute",
                  "orthogonal", "n_name", "tangentu_name", "tangentv_name"],
        "inputs": {
            "entity": {"label": "Entity",
                       "menu": {"point": "Points", "prim": "Primitives"}},
            "style": {"label": "Style",
                      "menu": {"two_edges": "Two Edges", "first_edge": "First Edge",
                               "centroid": "Primitive Centroid",
                               "uv": "Texture UV",
                               "attribute_gradient": "Attribute Gradient"}},
            "uv_attribute": {"label": "UV Attribute", "hide": "{ style != uv }"},
            "gradient_attribute": {"label": "Attribute Name",
                                   "hide": "{ style != attribute_gradient }"},
            "orthogonal": {"label": "Make Frame Orthogonal"},
            "n_name": {"label": "Normal Name", "sep": True,
                       "help": "Empty name = this item is not written"},
            "tangentu_name": {"label": "Tangent Name"},
            "tangentv_name": {"label": "Bitangent Name"},
        },
    },

    # ── Tangent Field SOP: Symmetry / guides / align to curvature / Seed / output
    "PCG_TangentField": {
        "order": ["symmetry", "guide_attribute", "guide_weight", "align",
                  "rand_seed", "output"],
        "inputs": {
            "symmetry": {"label": "Symmetry",
                         "menu": {"1": "1 (Vector)", "2": "2 (Line)",
                                  "4": "4 (Cross)", "6": "6 (Snowflake)"}},
            "guide_attribute": {"label": "Guide Attribute", "sep": True},
            # guide_weight only multiplies the attribute guide and the curvature guide; not read when neither is present
            "guide_weight": {"label": "Guide Weight",
                             "disable": '{ guide_attribute == "" align == none }'},
            # With symmetry = 1, choosing curvature alignment raises an error
            "align": {"label": "Align to Curvature",
                      "menu": {"none": "None", "max_curvature": "Max Curvature",
                               "min_curvature": "Min Curvature"},
                      "disable": "{ symmetry == 1 }"},
            # Random initialization is only used when there are no constraints at all (solving for the smallest eigenvector)
            "rand_seed": {"label": "Seed",
                          "disable": '{ guide_attribute != "" } { align != none }'},
            "output": {"label": "Output Attribute", "sep": True},
        },
    },

    # ── Convert Line SOP:Group / Keep Group Order / Connect Path / … / ☑ Compute Length [restlength]
    "PCG_ConvertLine": {
        "order": ["group", "keep_group_order", "connect_path",
                  "make_isolated_loops_closed", "remove_unused_points",
                  "compute_length", "length_attribute"],
        "inputs": {
            "keep_group_order": {"label": "Keep Group Order"},
            "connect_path": {"label": "Connect Path"},
            # in run(): make_isolated_loops_closed and connect_path
            "make_isolated_loops_closed": {"label": "Make Isolated Loops Closed",
                                           "disable": "{ connect_path == 0 }"},
            "remove_unused_points": {"label": "Remove Unused Points"},
            "length_attribute": {"label": "Compute Length", "toggle": "compute_length",
                                 "sep": True},
        },
    },

    # ── From JSON (this plugin's own node): input text / parsing → form → placement
    "PCG_FromJSON": {
        "order": ["json_text", "path", "mode", "group_by", "color_hex", "plane",
                  "normalized", "size_u", "center_x", "flip_v", "height"],
        "inputs": {
            "json_text": {"label": "JSON"},
            "path": {"label": "Record Path",
                     "help": "When the top level is an object, points at the record list, e.g. items; auto finds it"},
            "mode": {"label": "Output", "sep": True,
                     "menu": {"points": "Points", "boxes": "Boxes",
                              "curves": "Curves"}},
            "group_by": {"label": "Group By Attribute",
                         "help": "One group per distinct value; empty = none created"},
            "color_hex": {"label": "Parse Hex Colors"},
            "plane": {"label": "Plane", "sep": True,
                      "menu": {"xz": "XZ (Ground)", "xy": "XY", "yz": "YZ"}},
            "normalized": {"label": "Normalized Coordinates",
                           "help": "On: 2D 0..1 is mapped onto a patch of size Size; 3D coordinates are always treated as world coordinates"},
            # Rules in structured._to_world: Size only applies when normalizing; Center translates in all three forms and both modes;
            # Flip V: v → 1 − v when normalizing, v → −v when not
            "size_u": {"row": {"label": "Size"}, "disable": "{ normalized == 0 }"},
            "center_x": {"row": {"label": "Center"}},
            "flip_v": {"label": "Flip V", "help": "Turn on when image-space y points down"},
            # Only build_boxes reads height
            "height": {"label": "Height", "hide": "{ mode != boxes }"},
        },
    },

    # ── Geo to JSON (this plugin's own node)
    "PCG_GeoToJSON": {
        "order": ["class", "attribs", "limit", "precision", "indent"],
        "inputs": {
            "class": {"label": "Class", "menu": _cm("point", "prim", "detail")},
            "attribs": {"label": "Attributes", "help": "Empty = all; separated by spaces or commas"},
            "limit": {"label": "Max Records", "sep": True, "help": "0 = no truncation"},
            "precision": {"label": "Precision"},
            "indent": {"label": "Indent"},
        },
    },

    # ── Import Mesh (the mesh-reading part of the File SOP): file / format / coordinates / point fusing / options
    "PCG_ImportMesh": {
        "order": ["filename", "format", "up_axis", "scale", "flip_winding",
                  "weld", "weld_rel", "merge_parts", "splat_color",
                  "keep_extra_attribs"],
        "inputs": {
            "filename": {"label": "Geometry File", "help": "Ignored when the mesh port is wired"},
            "format": {"label": "File Format",
                       "menu": {"auto": "Automatic", "obj": "OBJ", "ply": "PLY",
                                "stl": "STL", "glb": "glTF (GLB)", "las": "LAS / LAZ (LiDAR)"}},
            "up_axis": {"label": "Up Axis", "sep": True,
                        "menu": {"as_is": "As Is", "z_up_to_y_up": "Z-Up to Y-Up",
                                 "y_up_to_z_up": "Y-Up to Z-Up"}},
            "scale": {"label": "Scale"},
            "flip_winding": {"label": "Reverse Winding"},
            "weld": {"label": "Weld Points", "sep": True,
                     "menu": {"auto": "Automatic (STL)", "on": "On", "off": "Off"}},
            "weld_rel": {"label": "Weld Tolerance", "hide": "{ weld == off }",
                         "help": "Relative to the bounding box"},
            "merge_parts": {"label": "Merge Parts", "sep": True},
            "splat_color": {"label": "Splat Color",
                            "help": "Converts 3DGS f_dc to Cd"},
            "keep_extra_attribs": {"label": "Keep Extra Attributes"},
        },
    },

    # ── Trace SOP: layer / threshold → curve cleanup → placement → ☑ Add Point Texture [uv]
    "PCG_Trace": {
        "order": ["layer", "channel_mode", "channel", "threshold", "invert", "boundary",
                  "boundary_value", "simplify", "min_points", "min_length", "close_open",
                  "resample", "step_size",
                  "plane", "size", "keep_aspect", "height", "center_x", "center_y", "center_z",
                  "rotate_x", "rotate_y", "rotate_z", "scale_x", "scale_y", "scale_z",
                  "add_uv", "uv_attrib"],
        "inputs": {
            "layer": {"label": "Layer"},
            "channel_mode": {"label": "Channel",
                             "menu": {"index": "By Index (legacy)", "mono": "Mono",
                                      "red": "Red", "green": "Green", "blue": "Blue",
                                      "alpha": "Alpha"}},
            # trace._channel_field: only the index mode reads the channel number
            "channel": {"label": "Channel Index", "hide": "{ channel_mode != index }"},
            "threshold": {"label": "Threshold"},
            "invert": {"label": "Invert"},
            "boundary": {"label": "Boundary Color",
                         "menu": {"none": "None (open curves at border)", "black": "Black",
                                  "white": "White", "same_as_00": "Same as (0,0)",
                                  "custom": "Custom"}},
            "boundary_value": {"label": "Boundary Value", "hide": "{ boundary != custom }"},
            "simplify": {"label": "Simplify", "sep": True, "help": "In pixels"},
            "min_points": {"label": "Min Points"},
            "min_length": {"label": "Min Length"},
            "close_open": {"label": "Close Open Curves"},
            "resample": {"label": "Resample Shapes", "section": None, "gate": None,
                         "in_toggle": "step_size"},
            "step_size": {"label": "Step Size", "section": None, "toggle": "resample"},
            "plane": {"label": "Plane", "sep": True,
                      "menu": {"xy": "XY", "xz": "XZ", "zx": "ZX"}},
            "size": {"label": "Size"},
            "keep_aspect": {"label": "Keep Aspect Ratio"},
            "height": {"label": "Height"},
            "center_x": {"row": {"kind": "vector", "label": "Translate",
                                 "members": ["center_x", "center_y", "center_z"]}},
            "rotate_x": {"section": "Placement",
                         "row": {"kind": "vector", "label": "Rotate",
                                 "members": ["rotate_x", "rotate_y", "rotate_z"]}},
            "scale_x": {"section": "Placement",
                        "row": {"kind": "vector", "label": "Scale",
                                "members": ["scale_x", "scale_y", "scale_z"]}},
            "add_uv": {"section": "Placement"},
            "uv_attrib": {"label": "Add Point Texture", "toggle": "add_uv",
                          "section": "Placement"},
        },
    },

    # ── Volume Rasterize Attributes SOP: Group / Attributes / Voxel Size / radius / density name
    "PCG_VolumeRasterizeAttribs": {
        "order": ["group", "attributes", "voxel_size", "use_pscale", "radius",
                  "radius_scale", "density_attribute"],
        "inputs": {
            "attributes": {"label": "Attributes"},
            "voxel_size": {"label": "Voxel Size"},
            "use_pscale": {"label": "Use pscale", "sep": True},
            # radius is only used when Use pscale is off or the points have no pscale -- the panel cannot tell the latter, so not greyed out
            "radius": {"label": "Radius",
                       "help": "Used when Use pscale is off or the points have no pscale"},
            "radius_scale": {"label": "Radius Scale"},
            "density_attribute": {"label": "Density Name", "sep": True},
        },
    },

    # ── Align(Copernicus)
    "PCG_COPAlign": {
        "order": ["fit", "border"],
        "inputs": {
            "fit": {"label": "Fit",
                    "menu": {"stretch": "Stretch", "fit": "Fit", "fill": "Fill",
                             "none": "None"}},
            "border": {"label": "Border", "menu": _BORDER},
        },
    },

    # ── Bake Geometry Textures (Copernicus): Resolution / UV / low-poly attributes, high-poly section
    "PCG_COPBakeTextures": {
        # geoimg.bake_textures: primary ray parameters are only read when high is wired and not single_mesh; both_sides /
        # ray_bias are only read by surface_normal; the cage mode reads the cage input
        "order": ["tracing_mode", "resolution_x", "uv_attrib", "face_culling",
                  "visibility_culling", "max_distance", "both_sides", "ray_bias",
                  "sample_multiplier", "dilate",
                  "normal_space", "world_normal", "world_normal_space", "position",
                  "position_space", "bounding_box", "occlusion", "occlusion_samples",
                  "occlusion_max_distance", "height", "height_space", "inner_distance",
                  "outer_distance", "alpha", "alpha_mask_high", "attribs", "high_attribs"],
        "inputs": {
            "tracing_mode": {"folder": "Tracer", "label": "Tracing Mode",
                             "menu": {"surface_normal": "Surface Normal",
                                      "cage_mesh": "Cage Mesh",
                                      "single_mesh": "Single Mesh (low)"}},
            "resolution_x": {"folder": "Tracer"},
            "uv_attrib": {"folder": "Tracer", "label": "UV Attribute"},
            "face_culling": {"folder": "Tracer", "label": "Face Culling", "sep": True,
                             "menu": {"none": "No Culling", "back": "Back Faces",
                                      "front": "Front Faces"},
                             "disable": "{ tracing_mode == single_mesh }"},
            "visibility_culling": {"folder": "Tracer", "label": "Visibility Culling",
                                   "menu": {"none": "No Culling", "back": "Back Faces",
                                            "front": "Front Faces"},
                                   "disable": "{ occlusion == 0 }",
                                   "help": "Applies to AO's secondary rays"},
            "max_distance": {"folder": "Tracer", "label": "Max Ray Distance",
                             "disable": "{ tracing_mode == single_mesh }",
                             "help": "Only used when high is wired; 0 = unlimited"},
            "both_sides": {"folder": "Tracer", "label": "Trace Both Sides",
                           "disable": "{ tracing_mode != surface_normal }",
                           "help": "Only used when high is wired"},
            "ray_bias": {"folder": "Tracer", "label": "Ray Bias",
                         "disable": "{ tracing_mode != surface_normal }"},
            "sample_multiplier": {"folder": "Tracer", "label": "Sample Multiplier",
                                  "disable": "{ occlusion == 0 }"},
            "dilate": {"folder": "Tracer", "label": "Edge Padding", "sep": True,
                       "help": "Number of texel rings to dilate UV islands outward"},
            "normal_space": {"folder": "Texture Maps", "label": "Normal Space",
                             "menu": {"signed": "Signed (-1 to 1)", "offset": "Offset (0 to 1)"},
                             "help": "normal_ts layer (only present when high is wired)"},
            "world_normal": {"folder": "Texture Maps", "label": "World Normal", "sep": True},
            "world_normal_space": {"folder": "Texture Maps", "label": "World Normal Space",
                                   "menu": {"signed": "Signed (-1 to 1)",
                                            "offset": "Offset (0 to 1)"},
                                   "hide": "{ world_normal == 0 }"},
            "position": {"folder": "Texture Maps", "label": "Position", "sep": True},
            "position_space": {"folder": "Texture Maps", "label": "Position Space",
                               "menu": {"absolute": "Absolute", "relative": "Relative"},
                               "hide": "{ position == 0 }"},
            "bounding_box": {"folder": "Texture Maps", "label": "Bounding Box",
                             "menu": {"fit": "Fit to Bounding Box",
                                      "uniform": "Fit to Uniform Box (No Stretching)"},
                             "hide": "{ position == 0 } { position_space != relative }"},
            "occlusion": {"folder": "Texture Maps", "label": "Ambient Occlusion", "sep": True},
            "occlusion_samples": {"folder": "Texture Maps", "label": "Occlusion Samples",
                                  "hide": "{ occlusion == 0 }"},
            "occlusion_max_distance": {"folder": "Texture Maps", "label": "Max Distance",
                                       "hide": "{ occlusion == 0 }", "help": "0 = unlimited"},
            "height": {"folder": "Texture Maps", "label": "Height", "sep": True},
            "height_space": {"folder": "Texture Maps", "label": "Height Space",
                             "menu": {"true_displacement": "True Displacement",
                                      "custom": "Custom"},
                             "hide": "{ height == 0 }"},
            "inner_distance": {"folder": "Texture Maps", "label": "Inner Distance",
                               "hide": "{ height == 0 } { height_space != custom }"},
            "outer_distance": {"folder": "Texture Maps", "label": "Outer Distance",
                               "hide": "{ height == 0 } { height_space != custom }"},
            "alpha": {"folder": "Texture Maps", "label": "Alpha", "sep": True},
            "alpha_mask_high": {"folder": "Texture Maps",
                                "label": "Mask Out High Resolution Mesh",
                                "hide": "{ alpha == 0 }"},
            "attribs": {"folder": "Texture Maps", "label": "Attributes", "sep": True,
                        "help": "Point attributes on the low-poly mesh to bake"},
            "high_attribs": {"folder": "Texture Maps", "label": "High Attributes",
                             "help": "Only used when high is wired"},
        },
    },
}
