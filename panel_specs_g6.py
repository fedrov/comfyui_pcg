"""
Parameter panel specs for group g6: first COP batch (Blur ... Glow, 44 nodes in alphabetical order). Format: see the docstring
at the top of panel_specs.py.

All hide / disable conditions follow the node's run() and the geo/cop/ implementation (each entry's comment gives the basis), not
guesses based on Houdini. Nodes without a same-named Copernicus node are organized as "input layer / main parameters on top, mode-specific ones
hidden per mode, output layer name last (set off with sep)".
"""

# filters.BORDERS: clamp = repeat the edge, wrap = periodic, black = pad outside the image with 0
_BORDER_MENU = {"clamp": "Clamp (Streak Edges)", "wrap": "Wrap", "black": "Constant (Black)"}
_COMPUTE_MENU = {"auto": "Auto", "cpu": "CPU", "cuda": "CUDA"}
_DEVICE_MENU = {"auto": "Auto", "cpu": "CPU", "cuda": "CUDA", "numpy": "NumPy",
                "exact": "Exact (float64)"}
_LAYERS = {"label": "Layers", "help": "Empty = all layers, space-separated"}
_OUT = {"label": "Output Layer", "sep": True}
_KEEP = {"label": "Keep Input Layers"}

SPECS = {
    # ── Blur:Layers → Size → Border
    "PCG_COPBlur": {
        "order": ["layers", "sigma_pixels", "border"],
        "inputs": {
            "layers": _LAYERS,
            "sigma_pixels": {"label": "Blur Size (Sigma)",
                             "help": "Gaussian σ in pixels; kernel radius ceil(3σ)"},
            "border": {"label": "Border", "menu": _BORDER_MENU},
        },
    },

    # ── Bounding Rectangle: solve.bounding_rect with per_id picks pixels where rint(value) == id,
    #    threshold is not read
    "PCG_COPBoundingRect": {
        "order": ["layer", "per_id", "threshold", "padding", "out_layer"],
        "inputs": {
            "layer": {"label": "Mask Layer"},
            "per_id": {"label": "Per ID", "help": "Treats Layer as an id image, one rectangle per id (> 0)"},
            "threshold": {"label": "Threshold", "hide": "{ per_id == 1 }"},
            "padding": {"label": "Padding (Pixels)"},
            "out_layer": _OUT,
        },
    },

    # ── Channel Convert (Mono to RGB / RGB to RGBA / UV to RGB ... combined):
    #    pixel.channel_convert only reads alpha when adding a 4th channel (dst = rgba), and only reads fill
    #    when adding the b channel for uv→rgb(a)
    "PCG_COPChannelConvert": {
        "order": ["layer", "mode", "alpha", "fill", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Conversion",
                     "menu": {"mono_to_rgb": "Mono to RGB", "mono_to_rgba": "Mono to RGBA",
                              "rgb_to_rgba": "RGB to RGBA", "rgba_to_rgb": "RGBA to RGB",
                              "rgb_to_uv": "RGB to UV", "rgba_to_uv": "RGBA to UV",
                              "uv_to_rgb": "UV to RGB", "uv_to_rgba": "UV to RGBA",
                              "rgb_to_mono_luma": "RGB to Mono (Luminance)",
                              "rgb_to_mono_average": "RGB to Mono (Average)",
                              "rgb_to_mono_max": "RGB to Mono (Maximum)"}},
            "alpha": {"label": "Alpha",
                      "hide": "{ mode != mono_to_rgba mode != rgb_to_rgba mode != uv_to_rgba }"},
            "fill": {"label": "Fill Value", "help": "The B channel added by UV → RGB",
                     "hide": "{ mode != uv_to_rgb mode != uv_to_rgba }"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
        },
    },

    "PCG_COPChannelJoin": {
        "order": ["layers", "out_layer"],
        "inputs": {
            "layers": {"label": "Input Layers",
                       "help": "Space-separated; all channels concatenated in order, at most 4 in total"},
            "out_layer": _OUT,
        },
    },

    "PCG_COPChannelSplit": {
        "order": ["layer", "suffixes", "keep_layers"],
        "inputs": {
            "layer": {"label": "Layer"},
            "suffixes": {"label": "Channel Suffixes",
                         "help": "Output layer name = layer_name.suffix; channel index used when there are not enough"},
            "keep_layers": _KEEP,
        },
    },

    # ── Chroma Key: Method → Invert → Key (a different set per Method) → Rolloff → Despill →
    #    Visualize → output. pixel.chroma_key: tolerance / softness are only read by distance;
    #    hue / sat / lum / rolloff / interpolation only by chromakey; threshold / width
    #    only by channel_separation. key_color is read by all three modes (distance measures distance to it,
    #    channel_separation uses it as the Screen Color, despill finds the dominant channel), so it is not hidden
    "PCG_COPChromaKey": {
        "order": ["layer", "method", "invert", "key_color", "tolerance", "softness",
                  "hue_min", "hue_max", "sat_min", "sat_max", "lum_min", "lum_max",
                  "threshold", "width",
                  "hue_rolloff", "sat_rolloff", "lum_rolloff", "interpolation",
                  "despill", "show_matte", "preview_color", "premultiply",
                  "out_layer", "alpha_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "method": {"label": "Method",
                       "menu": {"distance": "Chroma Distance (PCG)",
                                "chromakey": "Chromakey (Legacy)",
                                "channel_separation": "Channel Separation"}},
            "invert": {"label": "Invert", "help": "Inverts the matte"},
            "key_color": {"label": "Screen Color", "section": "Key",
                          "help": "distance: the key color; channel_separation: the screen color to key out; "
                                  "despill finds the dominant channel from its largest channel"},
            "tolerance": {"label": "Tolerance", "hide": "{ method != distance }"},
            "softness": {"label": "Softness", "hide": "{ method != distance }"},
            "hue_min": {"row": {"kind": "vector", "members": ["hue_min", "hue_max"],
                                "label": "Hue"},
                        "hide": "{ method != chromakey }",
                        "help": "Degrees; Min > Max means wrapping past 360"},
            "sat_min": {"row": {"kind": "vector", "members": ["sat_min", "sat_max"],
                                "label": "Saturation"},
                        "hide": "{ method != chromakey }"},
            "lum_min": {"row": {"kind": "vector", "members": ["lum_min", "lum_max"],
                                "label": "Luminance Range"},
                        "hide": "{ method != chromakey }"},
            "threshold": {"label": "Threshold",
                          "hide": "{ method != channel_separation }"},
            "width": {"label": "Width", "hide": "{ method != channel_separation }",
                      "help": "Total transition width on both sides of the threshold; 0 = hard threshold"},
            "hue_rolloff": {"label": "Hue", "section": "Rolloff",
                            "hide": "{ method != chromakey }"},
            "sat_rolloff": {"label": "Saturation", "hide": "{ method != chromakey }"},
            "lum_rolloff": {"label": "Luminance", "hide": "{ method != chromakey }"},
            "interpolation": {"label": "Interpolation",
                              "hide": "{ method != chromakey }",
                              "menu": {"linear": "Linear", "ease_in": "Ease In",
                                       "ease_out": "Ease Out", "smooth": "Smooth",
                                       "gaussian": "Gaussian"}},
            "despill": {"label": "Despill Amount", "section": "Despill (PCG)",
                        "help": "0 = no despill. Houdini's Chroma Key has no such option"},
            "show_matte": {"label": "Preview", "section": "Visualize"},
            "preview_color": {"label": "Preview Color", "disable": "{ show_matte == 0 }"},
            "premultiply": {"label": "Premultiply"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
            "alpha_layer": {"label": "Matte Layer", "help": "Empty = no matte output"},
        },
    },

    "PCG_COPChromaticAberration": {
        "order": ["layer", "amount", "center", "border"],
        "inputs": {
            "layer": {"label": "Layer"},
            "amount": {"label": "Amount", "help": "R scaled up by 1+Amount, B scaled down by 1−Amount"},
            "center": {"label": "Center"},
            "border": {"label": "Border", "menu": _BORDER_MENU},
        },
    },

    "PCG_COPClamp": {
        "order": ["layers", "min", "max"],
        "inputs": {
            "layers": _LAYERS,
            "min": {"label": "Minimum"},
            "max": {"label": "Maximum"},
        },
    },

    # ── Color Correct: pixel.color_correct skips the whole step when contrast == 1, pivot is not read
    "PCG_COPColorCorrect": {
        "order": ["layers", "exposure", "brightness", "contrast", "pivot", "gamma",
                  "saturation", "hue_shift", "hsv_saturation", "hsv_value", "mask_layer"],
        "inputs": {
            "layers": _LAYERS,
            "exposure": {"label": "Exposure", "help": "× 2^Exposure"},
            "brightness": {"label": "Brightness (Offset)", "help": "Additive"},
            "contrast": {"label": "Contrast"},
            "pivot": {"label": "Contrast Pivot", "disable": "{ contrast == 1 }"},
            "gamma": {"label": "Gamma", "help": "> 1 brightens"},
            "saturation": {"label": "Saturation", "help": "Only for layers with ≥ 3 channels"},
            "hue_shift": {"label": "Hue Shift", "help": "Degrees; the HSV section only applies to layers with ≥ 3 channels"},
            "hsv_saturation": {"label": "Saturation Scale"},
            "hsv_value": {"label": "Value Scale"},
            "mask_layer": {"label": "Mask Layer", "sep": True, "help": "Empty = whole image"},
        },
    },

    "PCG_COPCombineNormals": {
        "order": ["base_layer", "detail_layer", "method", "amount",
                  "out_layer", "keep_layers"],
        "inputs": {
            "base_layer": {"label": "Base Layer"},
            "detail_layer": {"label": "Detail Layer",
                             "help": "Taken from the detail input when wired, otherwise from the same image"},
            "method": {"label": "Method",
                       "menu": {"rnm": "Reoriented Normal Mapping", "whiteout": "Whiteout",
                                "udn": "UDN", "linear": "Linear"}},
            "amount": {"label": "Detail Amount"},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    "PCG_COPCompare": {
        "order": ["layer_a", "layer_b", "data_range", "out_diff", "out_ssim", "keep_layers"],
        "inputs": {
            "layer_a": {"label": "Layer A"},
            "layer_b": {"label": "Layer B", "help": "Empty = same name as Layer A"},
            "data_range": {"label": "Data Range", "help": "Width of the value range; use 1 for 0-1 images"},
            "out_diff": {"label": "Difference Layer", "sep": True},
            "out_ssim": {"label": "SSIM Layer"},
            "keep_layers": _KEEP,
        },
    },

    # ── Compare (Houdini semantics, outputs a mask): colorkey.compare_mask -- value is only read when Layer B
    #    is empty (expressible as a string condition: layer_b != ""); tolerance is not read when a Tolerance Layer
    #    is given (likewise)
    "PCG_COPCompareMask": {
        "order": ["layer_a", "layer_b", "value", "tolerance", "tolerance_layer",
                  "true_if", "components", "falloff", "out_layer"],
        "inputs": {
            "layer_a": {"label": "Layer A"},
            "layer_b": {"label": "Layer B", "help": "Empty = compare against Comparison Value"},
            "value": {"label": "Comparison Value", "disable": "{ layer_b != \"\" }"},
            "tolerance": {"label": "Tolerance", "disable": "{ tolerance_layer != \"\" }"},
            "tolerance_layer": {"label": "Tolerance Layer",
                                "help": "Per-pixel tolerance (single channel); when given, Tolerance is not used"},
            "true_if": {"label": "True If",
                        "menu": {"equal": "Equal to each other (==)",
                                 "not_equal": "Not equal to each other (!=)",
                                 "greater": "A greater than B (>)",
                                 "greater_equal": "A greater than or equal to B (>=)",
                                 "less": "B greater than A (<)",
                                 "less_equal": "B greater than or equal to A (<=)"}},
            "components": {"label": "Components",
                           "menu": {"all": "True if All", "any": "True if Any"}},
            "falloff": {"label": "Falloff",
                        "menu": {"none": "None", "linear": "Linear", "elendt": "Elendt"}},
            "out_layer": _OUT,
        },
    },

    # ── Despill: all parameters are always read; Bias / Mask Layer are Houdini's bias / mask inputs
    "PCG_COPDespill": {
        "order": ["layer", "mask", "spill_color", "bias", "luminance",
                  "bias_layer", "mask_layer", "out_layer", "spill_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mask": {"label": "Mask", "help": "Blend between old and new, 1 = fully new values"},
            "spill_color": {"label": "Spill Color"},
            "bias": {"label": "Bias", "help": "When removing green, 0 leans red, 1 leans blue; no visible change on flat colors"},
            "luminance": {"label": "Luminance", "help": "1 = restore luminance to match the original"},
            "bias_layer": {"label": "Bias Layer", "sep": True,
                           "help": "Multiplied onto Bias per pixel (single channel); empty = not used"},
            "mask_layer": {"label": "Mask Layer", "help": "Multiplied onto Mask per pixel; empty = not used"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
            "spill_layer": {"label": "Spill Layer", "help": "The removed color; empty = not output"},
        },
    },

    # ── Equalize (Houdini semantics): colorkey.equalize -- fit_method is only read by the middle three modes;
    #    black:stretch / min_to_black;white:stretch / max_to_white / max_length;
    #    target_average:average
    "PCG_COPEqualize": {
        "order": ["layer", "mask", "red", "green", "blue", "alpha",
                  "equalize_by", "fit_method", "luminance_type", "black", "white",
                  "target_average", "active_layer", "mask_layer", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mask": {"label": "Mask", "help": "Blend between old and new, 1 = fully new values"},
            "red": {"label": "Red", "help": "Single-channel layers only look at this toggle"},
            "green": {"label": "Green"},
            "blue": {"label": "Blue"},
            "alpha": {"label": "Alpha"},
            "equalize_by": {"label": "Equalize By", "sep": True,
                            "menu": {"stretch": "Stretch to Black and White",
                                     "min_to_black": "Move Minimum to Black",
                                     "max_to_white": "Move Maximum to White",
                                     "average": "Move Average to Value",
                                     "max_length": "Scale to Maximum Length"}},
            "fit_method": {"label": "Fit Method",
                           "hide": "{ equalize_by == stretch } { equalize_by == max_length }",
                           "menu": {"shift": "Shifting Values", "scale": "Scaling Values"}},
            "luminance_type": {"label": "Luminance Type",
                               "menu": {"sgi": "SGI Luminance", "ntsc": "NTSC Luminance",
                                        "hdtv": "HDTV Luminance", "average": "Average",
                                        "max": "Maximum Channel", "min": "Minimum Channel",
                                        "magnitude": "Magnitude / Length", "hue": "Hue",
                                        "saturation": "Saturation", "value": "Value",
                                        "red": "Red", "green": "Green", "blue": "Blue",
                                        "alpha": "Alpha"}},
            "black": {"label": "Black",
                      "hide": "{ equalize_by != stretch equalize_by != min_to_black }"},
            "white": {"label": "White",
                      "hide": "{ equalize_by == min_to_black } { equalize_by == average }"},
            "target_average": {"label": "Target Average",
                               "hide": "{ equalize_by != average }"},
            "active_layer": {"label": "Active Layer", "sep": True,
                             "help": "Only pixels where this layer > 0.5 count toward min / max / mean; empty = whole image"},
            "mask_layer": {"label": "Mask Layer", "help": "Multiplied onto Mask per pixel; empty = not used"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
        },
    },

    # ── Blend / Composite: Mode + Opacity on top, layer names below; mask_layer is only read when the mask
    #    input is wired (wiring state cannot be expressed as hide, only as help)
    "PCG_COPComposite": {
        "order": ["mode", "opacity", "swap", "compare_lengths",
                  "channel_r", "channel_g", "channel_b", "channel_a",
                  "layer", "foreground_layer", "mask_layer",
                  "output_layer", "keep_other_layers"],
        "inputs": {
            # replace is Houdini's Blend (the default mode), darken / lighten are its
            # Minimum / Maximum; atop / xor are our extras
            "mode": {"label": "Mode",
                     "menu": {"over": "Over", "add": "Add", "subtract": "Subtract",
                              "difference": "Difference", "multiply": "Multiply",
                              "divide": "Divide", "screen": "Screen", "overlay": "Overlay",
                              "softlight": "SoftLight", "darken": "Minimum",
                              "lighten": "Maximum", "atop": "Atop", "xor": "Xor",
                              "replace": "Blend", "under": "Under", "hypot": "Hypot",
                              "exclusion": "Exclusion", "hardlight": "HardLight",
                              "dodge": "Dodge", "burn": "Burn"}},
            "opacity": {"label": "Mask", "help": "Amount mixed in; multiplied further by the mask input when wired"},
            "swap": {"label": "Swap FG and BG"},
            # composite() only reads it in the darken / lighten modes
            "compare_lengths": {"label": "Compare Lengths",
                                "disable": "{ mode != darken mode != lighten }",
                                "help": "Minimum / Maximum pick whole pixels by the length of the pixel vector, not per channel"},
            "channel_r": {"label": "Red", "sep": True, "help": "Channels turned off keep the background value"},
            "channel_g": {"label": "Green"},
            "channel_b": {"label": "Blue"},
            "channel_a": {"label": "Alpha"},
            "layer": {"label": "Background Layer", "sep": True},
            "foreground_layer": {"label": "Foreground Layer", "help": "Empty = same name as Background Layer"},
            "mask_layer": {"label": "Mask Layer", "help": "Only read when the mask input is wired"},
            "output_layer": {"label": "Output Layer", "sep": True,
                             "help": "Empty = overwrite Background Layer"},
            "keep_other_layers": {"label": "Keep Other Layers"},
        },
    },

    # ── Constant: Size → Color (+ ☑ Alpha) → layer name → Device
    "PCG_COPConstant": {
        "order": ["resolution_x", "resolution_y", "red", "green", "blue",
                  "use_alpha", "alpha", "layer", "device"],
        "inputs": {
            "resolution_x": {"row": {"kind": "vector",
                                     "members": ["resolution_x", "resolution_y"],
                                     "label": "Resolution"}},
            "red": {"row": {"kind": "color", "members": ["red", "green", "blue"],
                            "label": "Color"}},
            "use_alpha": {"label": "Alpha"},
            "alpha": {"label": "Alpha", "help": "On = output 4 channels"},
            "layer": {"label": "Output Layer", "sep": True},
            "device": {"label": "Device", "menu": _DEVICE_MENU},
        },
    },

    # ── Contact Sheet: hfvis.contact_sheet only reads font / label_size when labels is on
    "PCG_COPContactSheet": {
        "order": ["layer", "columns", "padding", "scale", "background",
                  "labels", "font", "label_size"],
        "inputs": {
            "layer": {"label": "Layer"},
            "columns": {"label": "Columns", "help": "0 = automatic, close to square"},
            "padding": {"label": "Padding (Pixels)"},
            "scale": {"label": "Frame Scale", "help": "Uniform scale by the first frame's size × Scale"},
            "background": {"label": "Background Color", "kind": "colorstr"},
            "labels": {"label": "Frame Labels", "sep": True},
            "font": {"label": "Font", "disable": "{ labels == 0 }"},
            "label_size": {"label": "Label Size", "disable": "{ labels == 0 }",
                           "help": "0 = frame height / 10"},
        },
    },

    "PCG_COPContour": {
        "order": ["layer", "interval", "offset", "width", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "interval": {"label": "Contour Interval"},
            "offset": {"label": "Offset"},
            "width": {"label": "Line Width (Pixels)"},
            "out_layer": _OUT,
        },
    },

    # ── Surface Dither (pcg100 c7, filtersim.surface_dither): Iso Offset / Smooth are only read in the Mask mode
    "PCG_COPSurfaceDither": {
        "order": ["uv_layer", "dotscale_layer", "density_scale", "pattern_scale",
                  "pattern_scale_xy", "pattern_offset", "pattern_rotate", "dot_scale",
                  "output_type", "iso_offset", "smooth", "level_transition", "out_layer",
                  "uv_out_layer", "level_layer", "scale_layer", "resolution_x", "resolution_y"],
        "inputs": {
            "uv_layer": {"label": "UV Layer", "help": "Empty = texture uv at pixel centers"},
            "dotscale_layer": {"label": "Dot Scale Layer", "help": "Empty = 1; scales the dot size per pixel"},
            "density_scale": {"label": "Density Scale", "sep": True,
                              "help": "On-screen dot spacing (pixels); levels are graded between it and half of it"},
            "pattern_scale": {"label": "Pattern Scale"},
            "pattern_scale_xy": {"label": "Pattern Scale XY"},
            "pattern_offset": {"label": "Pattern Offset"},
            "pattern_rotate": {"label": "Pattern Rotate"},
            "dot_scale": {"label": "Dot Scale", "help": "Dot radius = ½ · Dot Scale · layer · Density Scale"},
            "output_type": {"label": "Output Type", "sep": True,
                            "menu": {"mask": "Mask", "sdf": "SDF"}},
            "iso_offset": {"label": "Iso Offset", "hide": "{ output_type != mask }",
                           "help": "Pixels; > 0 enlarges the dots"},
            "smooth": {"label": "Smooth", "hide": "{ output_type != mask }"},
            "level_transition": {"label": "Level Transition",
                                 "help": "Dots that are going away shrink to nothing within this last stretch of each level"},
            "out_layer": dict(_OUT, label="Dither Layer"),
            "uv_out_layer": {"label": "UV Output Layer", "help": "Empty = not output"},
            "level_layer": {"label": "Level Output Layer", "help": "Empty = not output"},
            "scale_layer": {"label": "Scale Output Layer", "help": "Empty = not output; 2^(−f)"},
            "resolution_x": {"help": "Used when no cop is wired; when wired, follows its resolution"},
        },
    },

    # ── Edge Detect by Contour / Depth / Normal(pcg100 c7,filtersim.edge_detect_probe):
    #    each of the three Tolerances is only read under its own Kind
    "PCG_COPEdgeDetectProbe": {
        "order": ["kind", "layer", "thickness_layer", "thickness_scale", "edge_spread", "blur",
                  "contour_tolerance", "depth_tolerance", "normal_tolerance",
                  "min_probe_radius", "out_layer"],
        "inputs": {
            "kind": {"label": "Detect By",
                     "menu": {"contour": "Contour (Edge Detect by Contour)",
                              "depth": "Depth (Edge Detect by Depth)",
                              "normal": "Normal (Edge Detect by Normal)"}},
            "layer": {"label": "Source Layer", "help": "Contour: id; Depth: Z; Normal: 3-channel normals"},
            "thickness_layer": {"label": "Thickness Layer", "help": "Empty = not used; when given, Thickness Scale is a multiplier on it"},
            "thickness_scale": {"label": "Thickness Scale", "sep": True,
                                "help": "Probe radius (pixels)"},
            "edge_spread": {"label": "Edge Spread", "help": "σ of the Gaussian falloff = Edge Spread × radius"},
            "blur": {"label": "Blur", "help": "Gaussian blur before detection (σ, pixels)"},
            "contour_tolerance": {"label": "Contour Tolerance", "hide": "{ kind != contour }"},
            "depth_tolerance": {"label": "Depth Tolerance", "hide": "{ kind != depth }"},
            "normal_tolerance": {"label": "Normal Tolerance", "hide": "{ kind != normal }",
                                 "help": "Counts as a crease when the dot product with a neighbour's normal is below this"},
            "min_probe_radius": {"label": "Min Probe Radius"},
            "out_layer": _OUT,
        },
    },

    # ── Convert Depth: pixel.convert_depth only uses FOV (ray length) when from = distance / to = distance / position,
    #    and only uses near / far when from or to = normalized
    "PCG_COPConvertDepth": {
        "order": ["layer", "from_kind", "to_kind", "fov", "near", "far",
                  "mask_layer", "out_layer"],
        "inputs": {
            "layer": {"label": "Depth Layer"},
            "from_kind": {"label": "From",
                          "menu": {"z_depth": "Z Depth", "distance": "Distance to Camera",
                                   "disparity": "Disparity (1/Z)",
                                   "normalized": "Normalized (Near to Far)"}},
            "to_kind": {"label": "To",
                        "menu": {"z_depth": "Z Depth", "distance": "Distance to Camera",
                                 "disparity": "Disparity (1/Z)",
                                 "normalized": "Normalized (Near to Far)",
                                 "position": "Camera-Space Position"}},
            "fov": {"label": "Vertical FOV",
                    "hide": "{ from_kind != distance to_kind != distance to_kind != position }"},
            "near": {"row": {"kind": "vector", "members": ["near", "far"],
                             "label": "Near / Far"},
                     "hide": "{ from_kind != normalized to_kind != normalized }",
                     "help": "For To Normalized, both 0 = use min / max inside the mask; "
                             "From Normalized requires near < far"},
            "far": {"hide": "{ from_kind != normalized to_kind != normalized }"},
            "mask_layer": {"label": "Mask Layer", "help": "Empty = pixels that are finite and > 0; outputs 0 outside the mask"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
        },
    },

    "PCG_COPConvertNormal": {
        "order": ["layer", "decode", "encode", "reconstruct_z", "flip_red",
                  "flip_green", "normalize", "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Layer"},
            "decode": {"label": "Input Encoding",
                       "menu": {"signed": "Signed (-1 to 1)", "packed": "Packed (0 to 1)"}},
            "encode": {"label": "Output Encoding",
                       "menu": {"signed": "Signed (-1 to 1)", "packed": "Packed (0 to 1)"}},
            "reconstruct_z": {"label": "Reconstruct Z", "sep": True,
                              "help": "Reconstructs z from xy only (two-channel normal maps)"},
            "flip_red": {"label": "Flip Red (X)"},
            "flip_green": {"label": "Flip Green (Y)", "help": "OpenGL ↔ DirectX"},
            "normalize": {"label": "Normalize"},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    # ── Convolve: fx.convolve_layer only parses kernel when preset == custom
    "PCG_COPConvolve": {
        "order": ["layers", "preset", "kernel", "normalize", "kernel_layer",
                  "centered", "border"],
        "inputs": {
            "layers": _LAYERS,
            "preset": {"label": "Kernel Preset",
                       "menu": {"custom": "Custom", "box3": "Box 3×3",
                                "gaussian3": "Gaussian 3×3", "sharpen": "Sharpen",
                                "edge": "Edge Detect", "emboss": "Emboss",
                                "sobel_x": "Sobel X", "sobel_y": "Sobel Y"},
                       "help": "Not read when the kernel_cop input is wired"},
            "kernel": {"label": "Kernel", "hide": "{ preset != custom }",
                       "help": "n² numbers, n odd; the first row written is the top row of the image"},
            "normalize": {"label": "Normalize Kernel", "help": "Scales the kernel to sum to 1 (kernels summing to 0 are left alone)"},
            # The two below are only read when kernel_cop is wired (wiring state cannot be written as hide)
            "kernel_layer": {"label": "Kernel Layer", "sep": True,
                             "help": "Only read when the kernel_cop input is wired: which of its layers to use as the kernel"},
            "centered": {"label": "Centered Kernel",
                         "help": "Only read when the kernel_cop input is wired. On: the center of the kernel image is the origin, no shift in the result"},
            "border": {"label": "Border", "sep": True,
                       "menu": dict(_BORDER_MENU, mirror="Mirror")},
        },
    },

    "PCG_COPCopyTransform": {
        "order": ["layers", "copies", "translate", "rotate", "scale_xy", "scale",
                  "pivot", "op", "fade"],
        "inputs": {
            "layers": _LAYERS,
            "copies": {"label": "Total Number"},
            "translate": {"label": "Translate (UV)", "section": "Transform per Copy"},
            "rotate": {"label": "Rotate", "section": "Transform per Copy"},
            "scale_xy": {"label": "Scale", "section": "Transform per Copy"},
            "scale": {"label": "Uniform Scale", "section": "Transform per Copy"},
            "pivot": {"label": "Pivot", "section": "Transform per Copy"},
            # over is the old behaviour (copy 0 on top, alpha interpolated like a normal channel); Houdini's
            # Over / Under are over_last / under
            "op": {"label": "Blend Method", "sep": True,
                   "menu": {"over": "Over (Legacy, First Copy on Top)", "add": "Add",
                            "max": "Maximum", "over_last": "Over", "under": "Under"}},
            "fade": {"label": "Fade per Copy",
                     "help": "Copy i × (1 − Fade)^i; the Over / Under modes only multiply alpha"},
        },
    },

    "PCG_COPCornerDetect": {
        "order": ["layer", "k", "sigma", "threshold", "radius", "out_layer", "response_layer"],
        "inputs": {
            "layer": {"label": "Layer", "help": "Only channel 0 is used"},
            "k": {"label": "Harris K"},
            "sigma": {"label": "Window Sigma"},
            "threshold": {"label": "Threshold", "help": "Fraction of the maximum response"},
            "radius": {"label": "Suppression Radius", "help": "Pixels; neighbourhood for the local maximum"},
            "out_layer": _OUT,
            "response_layer": {"label": "Response Layer", "help": "Empty = not output"},
        },
    },

    # ── Corner Pin: fx.corner_pin's corners mode only reads corners, the rotate_3d mode only reads
    #    rotate / fov / distance
    "PCG_COPCornerPin": {
        "order": ["layers", "mode", "corners", "rotate", "fov", "distance", "border"],
        "inputs": {
            "layers": _LAYERS,
            "mode": {"label": "Mode",
                     "menu": {"corners": "Corner Pin", "rotate_3d": "Rotate in 3D"}},
            "corners": {"label": "Corners (UV)", "hide": "{ mode != corners }",
                        "help": "Lower left, lower right, upper right, upper left, two numbers each"},
            "rotate": {"label": "Rotate", "hide": "{ mode != rotate_3d }"},
            "fov": {"label": "Field of View", "hide": "{ mode != rotate_3d }"},
            "distance": {"label": "Distance", "hide": "{ mode != rotate_3d }",
                         "help": "0 = the distance that exactly fills the frame"},
            "border": {"label": "Border", "sep": True, "menu": _BORDER_MENU},
        },
    },

    # ── Crop: nodes_cop.PCG_COPCrop.run reads integer x / y / resolution when units == pixels and method ==
    #    lower_left_size, otherwise corner / extent
    "PCG_COPCrop": {
        "order": ["mode", "border", "units", "method", "x", "y",
                  "resolution_x", "resolution_y", "corner", "extent",
                  "pad_left", "pad_right", "pad_top", "pad_bottom"],
        "inputs": {
            "mode": {"label": "Mode",
                     "menu": {"discard_reframe": "Discard and Reframe to Crop",
                              "discard": "Discard Cropped"}},
            "border": {"label": "Border",
                       "menu": dict(_BORDER_MENU, mirror="Mirror"),
                       "help": "How the parts where the window extends past the image / are dropped get filled"},
            "units": {"label": "Units", "sep": True,
                      "menu": {"pixels": "Pixels", "texture": "Texture", "image": "Image"}},
            "method": {"label": "Method",
                       "menu": {"lower_left_size": "Lower Left and Size",
                                "lower_left_upper_right": "Lower Left and Upper Right"}},
            "x": {"row": {"kind": "vector", "members": ["x", "y"],
                          "label": "Lower Left"},
                  "hide": "{ units != pixels } { method != lower_left_size }",
                  "help": "Pixels, origin at the lower left; may be negative (pads outward)"},
            "y": {"hide": "{ units != pixels } { method != lower_left_size }"},
            "resolution_x": {"row": {"kind": "vector",
                                     "members": ["resolution_x", "resolution_y"],
                                     "label": "Size"},
                             "hide": "{ units != pixels } { method != lower_left_size }"},
            "resolution_y": {"hide": "{ units != pixels } { method != lower_left_size }"},
            "corner": {"label": "Lower Left",
                       "hide": "{ units == pixels method == lower_left_size }",
                       "help": "Texture: 0-1; Image: −1...1 across the long side, origin at the image center"},
            "extent": {"label": "Upper Right / Size",
                       "hide": "{ units == pixels method == lower_left_size }",
                       "help": "Size when Method is Lower Left and Size, otherwise the upper right corner"},
            "pad_left": {"label": "Left", "section": "Pixel Padding"},
            "pad_right": {"label": "Right", "section": "Pixel Padding"},
            "pad_top": {"label": "Top", "section": "Pixel Padding"},
            "pad_bottom": {"label": "Bottom", "section": "Pixel Padding"},
        },
    },

    "PCG_COPCurvature": {
        "order": ["layer", "strength", "world_size", "kind", "scale", "tile",
                  "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "kind": {"label": "Curvature Type", "sep": True,
                     "menu": {"mean": "Mean", "gaussian": "Gaussian", "profile": "Profile",
                              "tangential": "Tangential", "plan": "Plan"}},
            "scale": {"label": "Output Scale"},
            "tile": {"label": "Tileable (Wrap Edges)"},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    # ── Defocus: fx.kernel_shape only reads blades / rotation for polygons (hexagon mode);
    #    with depth_layer empty coc = None and the rest of the Depth section is not read; with highlight_gain == 0
    #    threshold is not read
    "PCG_COPDefocus": {
        "order": ["layers", "radius", "shape", "blades", "rotation",
                  "depth_layer", "focus", "focus_range", "falloff", "levels",
                  "highlight_gain", "highlight_threshold", "border"],
        "inputs": {
            "layers": _LAYERS,
            "radius": {"label": "Blur Radius", "help": "Pixels"},
            "shape": {"label": "Aperture Shape",
                      "menu": {"disc": "Disc", "hexagon": "Polygon (Blades)",
                               "square": "Square"}},
            "blades": {"label": "Aperture Blades", "hide": "{ shape != hexagon }"},
            "rotation": {"label": "Blade Rotation", "hide": "{ shape != hexagon }"},
            "depth_layer": {"label": "Depth Layer", "help": "Empty = same radius over the whole image"},
            "focus": {"label": "Focus Distance", "disable": '{ depth_layer == "" }'},
            "focus_range": {"label": "Focus Range", "disable": '{ depth_layer == "" }'},
            "falloff": {"label": "Falloff", "disable": '{ depth_layer == "" }'},
            "levels": {"label": "Blur Levels", "disable": '{ depth_layer == "" }'},
            "highlight_gain": {"label": "Highlight Gain", "section": "Highlights"},
            "highlight_threshold": {"label": "Highlight Threshold", "section": "Highlights",
                                    "disable": "{ highlight_gain == 0 }"},
            "border": {"label": "Border", "sep": True, "menu": _BORDER_MENU},
        },
    },

    # ── Denoise TVD: fx.denoise_tv returns immediately when weight == 0, no iterations
    "PCG_COPDenoiseTV": {
        "order": ["layers", "weight", "iterations", "compute"],
        "inputs": {
            "layers": _LAYERS,
            "weight": {"label": "Weight", "help": "Larger = smoother; 0 = returned unchanged"},
            "iterations": {"label": "Iterations", "disable": "{ weight == 0 }"},
            "compute": {"label": "Compute", "sep": True, "menu": _COMPUTE_MENU},
        },
    },

    "PCG_COPDerivative": {
        "order": ["layer", "mode", "scale", "border", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Mode",
                     "menu": {"dx": "Derivative X", "dy": "Derivative Y",
                              "gradient": "Gradient", "magnitude": "Gradient Magnitude",
                              "laplacian": "Laplacian", "divergence": "Divergence",
                              "curl": "Curl"}},
            "scale": {"label": "Scale"},
            "border": {"label": "Border", "menu": _BORDER_MENU},
            "out_layer": dict(_OUT, help="Empty = layername_mode"),
        },
    },

    "PCG_COPDirectionalBlur": {
        "order": ["layers", "length", "angle", "mode", "samples", "border", "compute"],
        "inputs": {
            "layers": _LAYERS,
            "length": {"label": "Length", "help": "Pixels"},
            "angle": {"label": "Angle", "help": "Degrees, 0 = right, 90 = up"},
            "mode": {"label": "Mode",
                     "menu": {"centered": "Centered", "streak": "Streak (One Side)"}},
            "samples": {"label": "Samples", "help": "0 = one per pixel"},
            "border": {"label": "Border", "menu": _BORDER_MENU},
            "compute": {"label": "Compute", "sep": True, "menu": _COMPUTE_MENU},
        },
    },

    "PCG_COPDistort": {
        "order": ["layers", "field_layer", "amount", "units", "filter", "border"],
        "inputs": {
            "layers": _LAYERS,
            "field_layer": {"label": "Field Layer", "help": "2-channel vector layer on the field input"},
            "amount": {"label": "Amount", "help": "Backward: the output samples at p + Amount·field"},
            "units": {"label": "Units",
                      "menu": {"uv": "UV (1 = Full Size)", "pixels": "Pixels",
                               "normalized": "Normalized (1 = Half Size)"}},
            "filter": {"label": "Filter",
                       "menu": {"bilinear": "Bilinear", "closest": "Closest"}},
            "border": {"label": "Border", "menu": _BORDER_MENU},
        },
    },

    # ── Dither: only fx.dither's white_noise uses the seed
    "PCG_COPDither": {
        "order": ["layers", "method", "levels", "rand_seed"],
        "inputs": {
            "layers": _LAYERS,
            "method": {"label": "Method",
                       "menu": {"bayer4": "Ordered (Bayer 4×4)", "bayer8": "Ordered (Bayer 8×8)",
                                "floyd_steinberg": "Error Diffusion (Floyd-Steinberg)",
                                "white_noise": "White Noise"}},
            "levels": {"label": "Levels"},
            "rand_seed": {"label": "Seed", "hide": "{ method != white_noise }"},
        },
    },

    "PCG_COPDropShadow": {
        "order": ["layer", "alpha_layer", "offset", "blur", "color", "opacity"],
        "inputs": {
            "layer": {"label": "Layer"},
            "alpha_layer": {"label": "Alpha Layer", "help": "Empty = use Layer's 4th channel (error if it has none)"},
            "offset": {"label": "Offset (Pixels)", "sep": True, "help": "+y is up"},
            "blur": {"label": "Blur"},
            "color": {"label": "Shadow Color"},
            "opacity": {"label": "Opacity"},
        },
    },

    # ── Edge Detect: morph.edge's laplacian mode returns directly and does not write components
    "PCG_COPEdge": {
        "order": ["layer", "method", "scale", "border", "components",
                  "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Layer"},
            "method": {"label": "Method",
                       "menu": {"sobel": "Sobel", "prewitt": "Prewitt", "scharr": "Scharr",
                                "laplacian": "Laplacian"}},
            "scale": {"label": "Scale"},
            "border": {"label": "Border", "menu": _BORDER_MENU},
            "components": {"label": "Output Components", "hide": "{ method == laplacian }",
                           "help": "Also outputs three layers _gx / _gy / _dir"},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    "PCG_COPEikonal": {
        "order": ["seed_layer", "speed_layer", "speed", "max_sweeps", "tolerance",
                  "out_layer", "id_layer"],
        "inputs": {
            "seed_layer": {"label": "Seed Layer", "help": "Pixels > 0.5 are start points"},
            "speed_layer": {"label": "Speed Layer", "help": "Empty = Speed everywhere; 0 = wall"},
            "speed": {"label": "Speed"},
            "max_sweeps": {"label": "Max Sweeps", "section": "Solver"},
            "tolerance": {"label": "Tolerance", "section": "Solver"},
            "out_layer": _OUT,
            "id_layer": {"label": "ID Layer", "help": "Empty = do not output the index of the nearest seed"},
        },
    },

    # ── Erosion filter (this plugin's own node, organized as Height / Erosion / Fade / Tiling / Output):
    #    erosion.erode only reads height_min / height_max when fade == altitude
    "PCG_COPErosion": {
        "order": ["layer", "strength", "world_size",
                  "amplitude", "wavelength", "octaves", "lacunarity", "gain",
                  "steepness", "flow_blur", "rand_seed",
                  "fade", "height_min", "height_max",
                  "tile", "origin_x", "origin_y",
                  "out_layer", "mask_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "amplitude": {"label": "Amplitude", "section": "Erosion",
                          "help": "Depth of the coarsest gully level (world units)"},
            "wavelength": {"label": "Wavelength", "section": "Erosion",
                           "help": "Spacing of the coarsest gully level (pixels)"},
            "octaves": {"label": "Octaves", "section": "Erosion"},
            "lacunarity": {"label": "Lacunarity", "section": "Erosion"},
            "gain": {"label": "Gain", "section": "Erosion"},
            "steepness": {"label": "Steepness", "section": "Erosion"},
            "flow_blur": {"label": "Flow Blur", "section": "Erosion"},
            "rand_seed": {"label": "Seed", "section": "Erosion"},
            "fade": {"label": "Fade", "section": "Fade",
                     "menu": {"altitude": "By Altitude", "none": "None"}},
            "height_min": {"section": "Fade",
                           "row": {"kind": "vector", "members": ["height_min", "height_max"],
                                   "label": "Height Range"},
                           "hide": "{ fade != altitude }",
                           "help": "Equal = use the image's own min / max; tiled generation needs explicit values"},
            "height_max": {"section": "Fade", "hide": "{ fade != altitude }"},
            "tile": {"label": "Tileable (Wrap Edges)", "section": "Tiling"},
            "origin_x": {"section": "Tiling", "help": "World coordinates of this image's lower left corner (for tiled generation)"},
            "origin_y": {"section": "Tiling"},
            "out_layer": _OUT,
            "mask_layer": {"label": "Erosion Mask Layer", "help": "[-1,1] ridges > 0, gullies < 0; empty = not output"},
            "keep_layers": _KEEP,
        },
    },

    "PCG_COPExport": {
        "order": ["layer", "mode", "mask_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Range Mode",
                     "menu": {"clamp": "Clamp 0-1", "raw": "Raw",
                              "normalize": "Normalize (Min / Max)",
                              "signed": "Signed (-1 to 1 → 0 to 1)"}},
            "mask_layer": {"label": "Mask Layer", "sep": True,
                           "help": "The MASK output takes its channel 0 (clamped to 0-1, ignores Range Mode); outputs all 1 if the layer does not exist"},
        },
    },

    # ── FFT: solve.fft's magnitude mode always applies fftshift, the filter mode does not read centered;
    #    the Filter section is only read in the filter mode, cutoff_high only for bandpass / bandstop
    "PCG_COPFFT": {
        "order": ["layer", "mode", "centered", "filter", "cutoff", "cutoff_high",
                  "softness", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Mode",
                     "menu": {"forward": "Forward", "inverse": "Inverse",
                              "magnitude": "Magnitude Spectrum",
                              "filter": "Filter Frequencies"}},
            "centered": {"label": "Centered", "hide": "{ mode == filter }",
                         "help": "Moves DC to the image center; inverse must use the same setting as forward"},
            "filter": {"label": "Filter Type", "hide": "{ mode != filter }",
                       "menu": {"lowpass": "Low Pass", "highpass": "High Pass",
                                "bandpass": "Band Pass", "bandstop": "Band Stop"}},
            "cutoff": {"label": "Cutoff", "hide": "{ mode != filter }",
                       "help": "Cycles per image width; the low end for bandpass / bandstop"},
            "cutoff_high": {"label": "High Cutoff",
                            "hide": "{ mode != filter } { filter == lowpass } { filter == highpass }"},
            "softness": {"label": "Softness", "hide": "{ mode != filter }"},
            "out_layer": dict(_OUT, help="Empty = layername_mode; in the Filter mode empty = overwrite the input layer"),
        },
    },

    "PCG_COPFeather": {
        "order": ["layer", "width", "direction", "out_layer"],
        "inputs": {
            "layer": {"label": "Mask Layer"},
            "width": {"label": "Feather Width (Pixels)"},
            "direction": {"label": "Direction",
                          "menu": {"both": "Both", "inward": "Inward", "outward": "Outward"}},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
        },
    },

    # ── Feather (pcg100 c7, Houdini semantics: maximum slope, filtersim.feather_slope)
    "PCG_COPFeatherSlope": {
        "order": ["layer", "mask", "mask_layer", "high_to_low", "include_border", "border",
                  "direction", "sweep_nx", "sweep_px", "sweep_ny", "sweep_py", "sweep_nxny",
                  "sweep_nxpy", "sweep_pxny", "sweep_pxpy", "method", "distance", "change",
                  "out_layer"],
        "inputs": {
            "layer": {"label": "Source Layer"},
            "mask": {"label": "Mask", "help": "Fraction of the new value mixed in (× Mask Layer)"},
            "mask_layer": {"label": "Mask Layer", "help": "Empty = no mask layer"},
            "high_to_low": {"label": "Feather from High to Low", "sep": True,
                            "help": "On: bright pixels stay, dark pixels are raised; off: dark pixels stay, bright pixels are lowered"},
            "include_border": {"label": "Include Border",
                               "help": "Samples outside the image according to Border (use Wrap for seamless textures)"},
            "border": {"label": "Border", "menu": {"clamp": "Clamp", "wrap": "Wrap",
                                                   "black": "Constant (Black)",
                                                   "mirror": "Mirror"},
                       "disable": "{ include_border == 0 }",
                       "help": "Our layers have no border metadata, so it is given here; Clamp means no effect"},
            "direction": {"label": "Feather Direction", "sep": True,
                          "menu": {"diamond": "Diamond", "square": "Square",
                                   "octagon": "Octagon", "custom": "Custom",
                                   "circle": "Circle"},
                          "help": "Circle is a 16-direction approximation of a circle (max deviation about 2.7%)"},
            "sweep_nx": {"label": "-X", "hide": "{ direction != custom }"},
            "sweep_px": {"label": "+X", "hide": "{ direction != custom }"},
            "sweep_ny": {"label": "-Y", "hide": "{ direction != custom }"},
            "sweep_py": {"label": "+Y", "hide": "{ direction != custom }"},
            "sweep_nxny": {"label": "-X-Y", "hide": "{ direction != custom }"},
            "sweep_nxpy": {"label": "-X+Y", "hide": "{ direction != custom }"},
            "sweep_pxny": {"label": "+X-Y", "hide": "{ direction != custom }"},
            "sweep_pxpy": {"label": "+X+Y", "hide": "{ direction != custom }"},
            "method": {"label": "Feather Method", "sep": True,
                       "menu": {"distance_for_unit_change": "Distance for Unit Change",
                                "change_per_distance": "Change per Distance"}},
            "distance": {"label": "Distance for Unit Change",
                         "hide": "{ method != distance_for_unit_change }",
                         "help": "Image units (long side = 2)"},
            "change": {"label": "Change per Distance",
                       "hide": "{ method != change_per_distance }"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
        },
    },

    # ── Fill: pixel.fill does not read invert_mask when mask_layer is empty
    "PCG_COPFill": {
        "order": ["layer", "value", "mask_layer", "invert_mask"],
        "inputs": {
            "layer": {"label": "Layer"},
            "value": {"label": "Fill Value", "help": "Missing values are padded with the last one"},
            "mask_layer": {"label": "Mask Layer", "sep": True, "help": "Empty = fill everything"},
            "invert_mask": {"label": "Invert Mask", "disable": '{ mask_layer == "" }'},
        },
    },

    "PCG_COPFit": {
        "order": ["layers", "out_min", "out_max", "per_channel", "stats_layer"],
        "inputs": {
            "layers": _LAYERS,
            "out_min": {"row": {"kind": "vector", "members": ["out_min", "out_max"],
                                "label": "Output Range"}},
            "per_channel": {"label": "Per Channel", "help": "Stretches each channel separately (changes color relationships)"},
            "stats_layer": {"label": "Stats Layer", "sep": True, "help": "Which layer the statistics report looks at"},
        },
    },

    "PCG_COPFlip": {
        "order": ["layers", "horizontal", "vertical"],
        "inputs": {
            "layers": _LAYERS,
            "horizontal": {"label": "Flip Horizontal"},
            "vertical": {"label": "Flip Vertical"},
        },
    },

    # ── Fill Connected: fx.flood_fill does not read seed_uv when seed_layer is given
    "PCG_COPFloodFill": {
        "order": ["layer", "seed_uv", "seed_layer", "tolerance", "connectivity", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "seed_uv": {"label": "Seed Position (UV)", "disable": '{ seed_layer != "" }'},
            "seed_layer": {"label": "Seed Layer", "help": "Pixels > 0.5 are seeds; when given, Seed UV is not used"},
            "tolerance": {"label": "Tolerance"},
            "connectivity": {"label": "Connectivity",
                             "menu": {"4": "4 Neighbours", "8": "8 Neighbours"}},
            "out_layer": _OUT,
        },
    },

    # ── HeightField Flow Field family: flow.flow_accumulation only reads exponent for mfd,
    #    only reads rand_seed for rho8; river_area / river_softness are not read when river_layer is empty
    "PCG_COPFlowAccumulation": {
        "order": ["layer", "strength", "world_size",
                  "method", "exponent", "rand_seed", "fill_pits", "tile",
                  "base_layer", "rain_layer",
                  "river_layer", "river_area", "river_softness",
                  "flow_layer", "lake_layer", "dir_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "method": {"label": "Flow Method", "section": "Flow",
                       "menu": {"d8": "D8", "rho8": "Rho8 (Randomized D8)",
                                "mfd": "MFD (Multiple Flow Directions)"}},
            "exponent": {"label": "Slope Exponent", "section": "Flow",
                         "hide": "{ method != mfd }"},
            "rand_seed": {"label": "Seed", "section": "Flow", "hide": "{ method != rho8 }"},
            "fill_pits": {"label": "Fill Pits", "section": "Flow",
                          "help": "Fills pits into lakes; when off, water at the bottom of pits does not flow to an outlet"},
            "tile": {"label": "Tileable (Wrap Edges)", "section": "Flow",
                     "help": "Outlet = the lowest point of the whole image (not the four edges)"},
            "base_layer": {"label": "Outlet Layer", "section": "Flow",
                           "help": "Pixels > 0.5 are outlets; empty = the four edges"},
            "rain_layer": {"label": "Rain Layer", "section": "Flow", "help": "Empty = uniform rainfall"},
            "river_layer": {"label": "River Layer", "section": "River", "help": "Empty = not output"},
            "river_area": {"label": "River Area", "section": "River",
                           "disable": '{ river_layer == "" }', "help": "Catchment area (world units²)"},
            "river_softness": {"label": "River Softness", "section": "River",
                               "disable": '{ river_layer == "" }'},
            "flow_layer": {"label": "Flow Layer", "section": "Output", "help": "Empty = not output"},
            "lake_layer": {"label": "Lake Depth Layer", "section": "Output"},
            "dir_layer": {"label": "Flow Direction Layer", "section": "Output"},
            "keep_layers": {"label": "Keep Input Layers", "section": "Output"},
        },
    },

    # ── Flow Block / Project Non-Divergent: sim.flow's project mode only projects the velocity;
    #    density / steps / dt / force / dissipation are not read at all; tolerance is read by neither mode
    "PCG_COPFlowSolve": {
        "order": ["velocity_layer", "mode", "density_layers", "steps", "dt",
                  "force_layer", "force_scale", "dissipation", "edge", "tolerance", "compute"],
        "inputs": {
            "velocity_layer": {"label": "Velocity Layer", "help": "2 channels, pixels / step"},
            "mode": {"label": "Mode",
                     "menu": {"simulate": "Simulate (Stable Fluids)",
                              "project": "Project Non-Divergent"}},
            "density_layers": {"label": "Density Layers", "hide": "{ mode != simulate }",
                               "help": "Space-separated, advected along with the velocity"},
            "steps": {"label": "Steps", "hide": "{ mode != simulate }"},
            "dt": {"label": "Time Step", "hide": "{ mode != simulate }"},
            "force_layer": {"label": "Force Layer", "hide": "{ mode != simulate }",
                            "help": "Empty = no force"},
            "force_scale": {"label": "Force Scale", "hide": "{ mode != simulate }",
                            "disable": '{ force_layer == "" }'},
            "dissipation": {"label": "Dissipation", "hide": "{ mode != simulate }"},
            "edge": {"label": "Boundary", "sep": True,
                     "menu": {"wrap": "Wrap (Periodic)", "clamp": "Closed (Walls)"}},
            "tolerance": {"label": "Tolerance (Unused)",
                          "help": "Both boundary types are solved directly, so it no longer has any effect; kept only so old workflows do not shift"},
            "compute": {"label": "Compute", "sep": True, "menu": _COMPUTE_MENU},
        },
    },

    # ── Function: pixel.function only reads a for pow / step / smoothstep / mod,
    #    only reads b for smoothstep
    "PCG_COPFunction": {
        "order": ["layers", "function", "a", "b"],
        "inputs": {
            "layers": _LAYERS,
            "function": {"label": "Function",
                         "menu": {"abs": "Absolute", "negate": "Negate", "sqrt": "Square Root",
                                  "pow": "Power", "exp": "Exponential", "log": "Natural Log",
                                  "sin": "Sine", "cos": "Cosine", "tan": "Tangent",
                                  "floor": "Floor", "ceil": "Ceiling", "round": "Round",
                                  "frac": "Fractional Part", "sign": "Sign", "step": "Step",
                                  "smoothstep": "Smooth Step", "clamp01": "Clamp 0-1",
                                  "reciprocal": "Reciprocal (1/x)", "mod": "Modulo",
                                  "sigmoid": "Sigmoid"}},
            "a": {"label": "A",
                  "hide": "{ function != pow function != step function != smoothstep "
                          "function != mod }",
                  "help": "pow: exponent; step: threshold; smoothstep: lower edge; mod: modulus"},
            "b": {"label": "B", "hide": "{ function != smoothstep }",
                  "help": "Upper edge of smoothstep"},
        },
    },

    # ── Glow: fx.glow's glow mode only reads radius, the star mode only reads rays / ray_length / angle
    "PCG_COPGlow": {
        "order": ["layers", "mode", "threshold", "intensity", "radius",
                  "rays", "ray_length", "angle", "border"],
        "inputs": {
            "layers": _LAYERS,
            "mode": {"label": "Mode", "menu": {"glow": "Glow", "star": "Star Glow"}},
            "threshold": {"label": "Threshold"},
            "intensity": {"label": "Intensity"},
            "radius": {"label": "Glow Radius", "hide": "{ mode != glow }"},
            "rays": {"label": "Number of Rays", "hide": "{ mode != star }"},
            "ray_length": {"label": "Ray Length", "hide": "{ mode != star }"},
            "angle": {"label": "Ray Angle", "hide": "{ mode != star }"},
            "border": {"label": "Border", "sep": True, "menu": _BORDER_MENU},
        },
    },
}
