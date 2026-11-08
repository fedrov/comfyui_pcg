"""
Parameter panel specs for group g9: third COP batch (Tile ... Wrangle), ControlNet / sequence bridges
(Control Image / ID Masks / Regional Prompt / Render Pass / Sequence *) and a batch of
deform SOPs (Blend Shapes ... Soft Transform). Format: see the docstring at the top of panel_specs.py.

All hide / disable conditions follow the node's run() and the geo/ implementation (each entry's comment gives the basis), not
guesses based on Houdini. Nodes without a same-named Houdini node are organized as "input layer / main parameters on top, mode-specific ones hidden per mode,
output layer / attribute names last (set off with sep)".
"""

# filters.BORDERS / frommap.BORDERS: clamp = repeat the edge, wrap = periodic, black = pad outside the image with 0
_BORDER_MENU = {"clamp": "Clamp (Streak Edges)", "wrap": "Wrap",
                "black": "Constant (Black)"}
_FILTER_MENU = {"bilinear": "Bilinear", "closest": "Closest"}
_DEVICE_MENU = {"auto": "Auto", "cpu": "CPU", "cuda": "CUDA", "numpy": "NumPy",
                "exact": "Exact (float64)"}
_DEVICE = {"label": "Device", "sep": True, "menu": _DEVICE_MENU,
           "help": "Which backend the output image lives on; exact = float64 numpy"}
# transform.UNITS / sequence.UNITS: uv 1 = full frame, normalized 1 = half frame (−1~1 spans the full frame)
_UNITS_MENU = {"uv": "UV (0-1)", "pixels": "Pixels",
               "normalized": "Normalized (NDC)"}
_LAYERS = {"label": "Layers", "help": "Empty = all layers, space-separated"}
_OUT = {"label": "Output Layer", "sep": True}
_W3_FILTER = {"point": "Point", "bilinear": "Bilinear", "box": "Box", "bartlett": "Bartlett",
              "catmull_rom": "Catmull-Rom", "mitchell": "Mitchell", "bspline": "B-Spline"}
_XF_ORDER = {"srt": "Scale Rot Trans", "str": "Scale Trans Rot", "rst": "Rot Scale Trans",
             "rts": "Rot Trans Scale", "tsr": "Trans Scale Rot", "trs": "Trans Rot Scale"}
_ROT_ORDER = {"xyz": "Rx Ry Rz", "xzy": "Rx Rz Ry", "yxz": "Ry Rx Rz", "yzx": "Ry Rz Rx",
              "zxy": "Rz Rx Ry", "zyx": "Rz Ry Rx"}
_UNITS = {"image": "Image", "texture": "Texture", "pixels": "Pixels", "world": "World"}
_JUST = {"none": "None", "min": "Min", "center": "Center", "max": "Max"}
_GOAL = {"same": "Same", "min": "Min", "center": "Center", "max": "Max"}
_SIDE = {"min": "Min", "center": "Center", "max": "Max"}
_CS_BORDER = {"clamp": "Clamp", "mirror": "Mirror", "wrap": "Wrap", "extend": "Extend"}
_DECODE_MENU = {"none": "None", "srgb_to_linear": "sRGB to Linear",
                "linear_to_srgb": "Linear to sRGB"}
# deform.METRICS: euclidean straight line; distance / steps along edges (adjacency.distance_from)
_METRIC_MENU = {"euclidean": "Euclidean", "distance": "Edge Distance",
                "steps": "Edge Steps"}
# Soft Peak / Soft Transform (pcg100): Houdini's Radius = euclidean, Edge = distance;
# Surface (geodesic distance on the surface) is not implemented; steps is ours
_SOFT_METRIC_MENU = {"euclidean": "Radius", "steps": "Edge Steps", "distance": "Edge",
                     "attribute": "Attribute",
                     "radius_with_connectivity": "Radius with Connectivity (deprecated)"}
_SOFT_TYPE_MENU = {"ramp": "Ramp (PCG)", "linear": "Linear", "quadratic": "Quadratic",
                   "cubic": "Cubic", "metaball": "Metaball"}
_KERNEL_MENU = {"links": "Links", "renderman": "RenderMan", "hart": "Hart"}
_MAGNET_TYPE_MENU = {"points": "Points (Spheres)", "surface": "Surface"}
_TILE_COUNT = {"kind": "vector", "members": ["columns", "rows"],
               "label": "Tile Count"}

SPECS = {
    # ══════════════════════════════════════════════════════════ COP
    # ── Tile: tile counts on one row, two mirror toggles (transform.tile reads all of them)
    "PCG_COPTile": {
        "order": ["tiles_x", "tiles_y", "mirror_u", "mirror_v"],
        "inputs": {
            "tiles_x": {"row": {"kind": "vector", "members": ["tiles_x", "tiles_y"],
                                "label": "Tile Count"},
                        "help": "Output resolution = input × count, copied bit-exactly"},
            "mirror_u": {"label": "Mirror Alternate Columns",
                         "help": "Mirrors odd columns -- turns any image into a seamless tile"},
            "mirror_v": {"label": "Mirror Alternate Rows"},
        },
    },

    # ── HeightField Tile Splice:Tile Count / Overlap / Feather
    #    tiles.tile_splice: b = feather × overlap; with overlap = 0 feather has no effect
    "PCG_COPTileSplice": {
        "order": ["columns", "rows", "overlap", "feather"],
        "inputs": {
            "columns": {"row": dict(_TILE_COUNT),
                        "help": "Must match the split (Tile Split)"},
            "overlap": {"label": "Tile Overlap", "help": "Pixels; must match Tile Split"},
            "feather": {"label": "Blend Width", "disable": "{ overlap == 0 }",
                        "help": "Fraction of Overlap taken by the blend band, 0 = hard join"},
        },
    },

    # ── HeightField Tile Split: Tile Count / Overlap (all read)
    "PCG_COPTileSplit": {
        "order": ["columns", "rows", "overlap"],
        "inputs": {
            "columns": {"row": dict(_TILE_COUNT),
                        "help": "Output sequence: lower left tile first, rows before columns"},
            "overlap": {"label": "Tile Overlap", "help": "Extra pixels each tile carries on all sides (none at the image border)"},
        },
    },

    # ── Only a Device
    "PCG_COPToDevice": {
        "order": ["device"],
        "inputs": {
            "device": {"label": "Device", "menu": _DEVICE_MENU,
                       "help": "Each move is a full-image transfer; do not move back and forth along the chain"},
        },
    },

    # ── Tone Map:Layers → Operator → Exposure → White Point → Encode
    #    pixel.tone_map: white is only read in the reinhard_extended / hable modes
    "PCG_COPToneMap": {
        "order": ["layers", "op", "exposure", "white", "encode_srgb"],
        "inputs": {
            "layers": dict(_LAYERS),
            "op": {"label": "Operator",
                   "menu": {"reinhard": "Reinhard",
                            "reinhard_extended": "Reinhard Extended",
                            "aces": "ACES (Narkowicz Fit)",
                            "hable": "Hable (Uncharted 2)",
                            "exposure_only": "Exposure Only (Clamp)"}},
            "exposure": {"label": "Exposure", "help": "Stops: × 2^Exposure"},
            "white": {"label": "White Point",
                      "hide": "{ op != reinhard_extended op != hable }"},
            "encode_srgb": {"label": "Encode sRGB", "sep": True,
                            "help": "On for images you view directly; off for ones still going into compositing"},
        },
    },

    # ── Copernicus Transform 2D: Translate / Rotate / Scale / Pivot, then Units / Border / Filter
    #    transform.transform: pure translation takes the fast path and does not read pivot, but pivot has no effect then anyway → not hidden
    "PCG_COPTransform": {
        "order": ["layers", "translate_x", "translate_y", "rotate", "scale_x",
                  "scale_y", "pivot_u", "pivot_v", "units", "border", "filter"],
        "inputs": {
            "layers": dict(_LAYERS, help="Empty = all layers; unlisted layers pass through unchanged, not resampled"),
            "translate_x": {"help": "Units set by Translate Units below"},
            "rotate": {"label": "Rotate", "help": "Counter-clockwise degrees (v up)"},
            "scale_x": {"help": "> 1 enlarges the image content; must not be 0"},
            "pivot_u": {"section": None,
                        "row": {"kind": "vector", "members": ["pivot_u", "pivot_v"],
                                "label": "Pivot"},
                        "help": "uv coordinates (not affected by Units)"},
            "pivot_v": {"section": None},
            "units": {"label": "Translate Units", "sep": True, "menu": dict(_UNITS_MENU)},
            "border": {"label": "Border", "menu": dict(_BORDER_MENU)},
            "filter": {"label": "Filter", "menu": dict(_FILTER_MENU)},
        },
    },

    # ── Triplanar: P / N / texture layer → Scale / Sharpness → Hex Tiling section (toggle on the header) → output
    #    uvx.triplanar: with hex off, tiles_rotation / seed are not read
    "PCG_COPTriplanar": {
        "order": ["p_layer", "n_layer", "layer", "scale", "sharpness",
                  "hex", "hex_rotation", "rand_seed", "out_layer", "uv_layer"],
        "inputs": {
            "p_layer": {"label": "Position Layer",
                        "help": "World position P (position channel of Render Pass)"},
            "n_layer": {"label": "Normal Layer", "help": "World-space normals (choose world in Render Pass)"},
            "layer": {"label": "Texture Layer", "sep": True,
                      "help": "Taken from source when wired, otherwise from this layer itself"},
            "scale": {"label": "Scale", "help": "P × Scale as projection coordinates (texture period = 1 / Scale)"},
            "sharpness": {"label": "Blend Sharpness", "help": "Three-axis weights = |N|^Sharpness"},
            "hex": {"label": "Hex Tiling", "section": "Hex Tiling", "gate": True},
            "hex_rotation": {"label": "Max Rotation", "section": "Hex Tiling",
                             "help": "Each cell rotated randomly by ±this angle"},
            "rand_seed": {"label": "Seed", "section": "Hex Tiling"},
            "out_layer": dict(_OUT),
            "uv_layer": {"label": "UV Output Layer",
                         "help": "When non-empty, also outputs the projected uv of the dominant axis (Triplanar UV)"},
        },
    },

    # ── UV Inverse: UV layer → Source Res → Fill → output (all read)
    "PCG_COPUVInverse": {
        "order": ["layer", "source_res", "fill", "out_layer"],
        "inputs": {
            "layer": {"label": "UV Layer", "help": "Mapping from output → source image uv"},
            "source_res": {"label": "Source Resolution", "help": "0 0 = same resolution as the input"},
            "fill": {"label": "Fill Holes (Push-Pull)"},
            "out_layer": dict(_OUT, help="Also outputs a <name>_mask coverage layer"),
        },
    },

    # ── UV Map / UV Map by ID: Mode decides which set is read (uvx.uv_map)
    #    identity only reads scale / offset / rotate; by_id only reads id_layer / fit / id_mode ...
    #    pcg100 c6: UV Space, U/V Border · Shift · Cycles, uvscale, by-ID Mode, etc.
    "PCG_COPUVMap": {
        "order": ["mode", "uv_space", "id_layer", "id_mode", "fit", "auto_scale",
                  "zero_negative_ids", "connected", "offset", "rotate", "scale",
                  "u_border", "u_shift", "u_cycles", "v_border", "v_shift", "v_cycles",
                  "out_layer", "uvscale_layer", "resolution_x", "resolution_y"],
        "inputs": {
            "mode": {"label": "Mode",
                     "menu": {"identity": "UV Map", "by_id": "UV Map by ID"}},
            "uv_space": {"label": "UV Space",
                         "menu": {"texture": "Texture", "image": "Image", "pixel": "Pixel"},
                         "help": "Texture 0...1; Image −1...1 across the long side; Pixel starts at 0.5 at pixel centers. "
                                 "UV Map by ID only supports Texture / Image"},
            "id_layer": {"label": "ID Layer", "hide": "{ mode != by_id }"},
            "id_mode": {"label": "Output", "hide": "{ mode != by_id }",
                        "menu": {"uv_map": "UV Map", "center": "Center",
                                 "minimum": "Minimum", "maximum": "Maximum",
                                 "size": "Size"},
                        "help": "Mode of Houdini's UV Map by ID: uv within the island, or statistics of the island's bounding box"},
            "fit": {"label": "Fit", "hide": "{ mode != by_id }",
                    "disable": "{ uv_space == image } { auto_scale == 0 } { id_mode != uv_map }",
                    "menu": {"fit": "Fit (Keep Aspect)", "stretch": "Stretch"},
                    "help": "Used in Texture space; Houdini's Texture is Stretch, Image is always uniform"},
            "auto_scale": {"label": "Auto Scale", "hide": "{ mode != by_id }",
                           "disable": "{ id_mode != uv_map }"},
            "zero_negative_ids": {"label": "Zero Negative IDs", "hide": "{ mode != by_id }"},
            "connected": {"label": "Split Disconnected Islands", "hide": "{ mode != by_id }",
                          "help": "On: disconnected pieces within one id each count as an island (Houdini's approach); "
                                  "off: one island per id (old behaviour)"},
            "offset": {"label": "Translate", "hide": "{ mode != identity }"},
            "rotate": {"label": "Rotate", "hide": "{ mode != identity }",
                       "help": "Counter-clockwise degrees around (0.5, 0.5)"},
            "scale": {"label": "Scale", "hide": "{ mode != identity }"},
            "u_border": {"label": "U Border", "section": "Border",
                         "disable": "{ mode == by_id id_mode != uv_map }",
                         "menu": {"clamp": "Clamp", "mirror": "Mirror", "wrap": "Wrap",
                                  "extend": "Extend"}},
            "u_shift": {"label": "U Shift", "disable": "{ mode == by_id id_mode != uv_map }"},
            "u_cycles": {"label": "U Cycles", "disable": "{ mode == by_id id_mode != uv_map }",
                         "help": "(uv + Shift) × Cycles, then folded back by Border"},
            "v_border": {"label": "V Border",
                         "disable": "{ mode == by_id id_mode != uv_map }",
                         "menu": {"clamp": "Clamp", "mirror": "Mirror", "wrap": "Wrap",
                                  "extend": "Extend"}},
            "v_shift": {"label": "V Shift", "disable": "{ mode == by_id id_mode != uv_map }"},
            "v_cycles": {"label": "V Cycles", "disable": "{ mode == by_id id_mode != uv_map }"},
            "out_layer": dict(_OUT),
            "uvscale_layer": {"label": "UV Scale Layer", "help": "Empty = not output"},
            "resolution_x": {"help": "Used when no cop is wired; when wired, follows the input's resolution"},
        },
    },

    # ── UV to Polar / Polar to UV (pcg100 c6, coordspace.polar_coords): pure coordinate conversion
    "PCG_COPPolarCoords": {
        "order": ["direction", "angle_units", "uv_layer", "angle_layer", "length_layer",
                  "angle", "length", "origin"],
        "inputs": {
            "direction": {"label": "Direction",
                          "menu": {"uv_to_polar": "UV to Polar", "polar_to_uv": "Polar to UV"}},
            "angle_units": {"label": "Angle Units",
                            "menu": {"radians": "Radians", "degrees": "Degrees",
                                     "circles": "Circles (2pi)"}},
            "uv_layer": {"label": "UV Layer",
                         "help": "Read by UV to Polar; written by Polar to UV"},
            "angle_layer": {"label": "Angle Layer",
                            "help": "Written by UV to Polar; read by Polar to UV (empty = use the Angle constant)"},
            "length_layer": {"label": "Length Layer",
                             "help": "Written by UV to Polar; read by Polar to UV (empty = use the Length constant)"},
            "angle": {"label": "Angle", "hide": "{ direction == uv_to_polar }",
                      "disable": '{ angle_layer != "" }'},
            "length": {"label": "Length", "hide": "{ direction == uv_to_polar }",
                       "disable": '{ length_layer != "" }'},
            "origin": {"label": "Origin", "sep": True,
                       "help": "Our addition; Houdini fixes it at uv = (0, 0)"},
        },
    },

    # ── Space Transform(pcg100 c6,coordspace.space_transform)
    "PCG_COPSpaceTransform": {
        "order": ["layer", "vector_type", "src_space", "dst_space", "out_layer"],
        "inputs": {
            "layer": {"label": "Coord Layer"},
            "vector_type": {"label": "Vector Type",
                            "menu": {"position": "Position",
                                     "vector": "Vector/Displacement/Velocity"}},
            "src_space": {"label": "Source Space", "menu": {"buffer": "Buffer", "pixel": "Pixel", "texture": "Texture", "image": "Image", "world": "World"},
                          "help": "Interpreted at src_ref's resolution (coord when not wired). Buffer = Pixel, World = Image"},
            "dst_space": {"label": "Destination Space", "menu": {"buffer": "Buffer", "pixel": "Pixel", "texture": "Texture", "image": "Image", "world": "World"},
                          "help": "Interpreted at dst_ref's resolution (coord when not wired)"},
            "out_layer": dict(_OUT, help="Empty = overwrite the original layer"),
        },
    },

    # ── Position Map (pcg100 c6, coordspace.position_map): Border / Shift / Cycles per axis
    "PCG_COPPositionMap": {
        "order": ["source_position", "x_border", "x_shift", "x_cycles", "y_border", "y_shift",
                  "y_cycles", "z_border", "z_shift", "z_cycles", "out_layer",
                  "resolution_x", "resolution_y"],
        "inputs": {
            "source_position": {"label": "Source Position",
                                "menu": {"position": "Position",
                                         "view_direction": "View Direction"},
                                "help": "No camera: Position = (image x, image y, 0), "
                                        "View Direction = (0, 0, −1)"},
            "x_border": {"label": "X Border", "section": "X", "menu": _CS_BORDER},
            "x_shift": {"label": "X Shift"},
            "x_cycles": {"label": "X Cycles", "help": "(P + Shift) × Cycles, then folded back into [−1, 1] by Border"},
            "y_border": {"label": "Y Border", "section": "Y", "menu": _CS_BORDER},
            "y_shift": {"label": "Y Shift"},
            "y_cycles": {"label": "Y Cycles", "help": "(P + Shift) × Cycles, then folded back into [−1, 1] by Border"},
            "z_border": {"label": "Z Border", "section": "Z", "menu": _CS_BORDER},
            "z_shift": {"label": "Z Shift"},
            "z_cycles": {"label": "Z Cycles", "help": "(P + Shift) × Cycles, then folded back into [−1, 1] by Border"},
            "out_layer": dict(_OUT),
            "resolution_x": {"help": "Used when size_ref is not wired; when wired, follows its resolution"},
        },
    },

    # ── Sphere Sample(pcg100 c6,warp3d.sphere_sample)
    "PCG_COPSphereSample": {
        "order": ["source_layer", "filter", "xform_order", "rotate_order", "celestial",
                  "projection", "translate", "rotate", "scale", "uniform_scale",
                  "camera_distance", "out_layer", "mask_layer", "resolution_x", "resolution_y"],
        "inputs": {
            "source_layer": {"label": "Source Layer", "help": "Lat-long image"},
            "filter": {"label": "Filter", "menu": _W3_FILTER,
                       "help": "With a unit footprint, Box = Point, Bartlett = Bilinear"},
            "xform_order": {"label": "Transform Order", "menu": _XF_ORDER,
                            "disable": "{ celestial == 1 }"},
            "rotate_order": {"label": "Rotate Order", "menu": _ROT_ORDER},
            "celestial": {"label": "Celestial Sphere",
                          "help": "On: infinitely distant sky sphere, only Rotate is read, mask is all 1"},
            "projection": {"label": "Projection",
                           "menu": {"perspective": "Perspective",
                                    "orthographic": "Orthographic"}},
            "translate": {"label": "Translate", "disable": "{ celestial == 1 }"},
            "rotate": {"label": "Rotate"},
            "scale": {"label": "Scale", "disable": "{ celestial == 1 }"},
            "uniform_scale": {"label": "Uniform Scale", "disable": "{ celestial == 1 }"},
            "camera_distance": {"label": "Camera Distance", "disable": "{ projection != perspective }",
                                "help": "Our addition: there is no camera metadata; the perspective camera sits at (0, 0, d) looking down −Z"},
            "out_layer": dict(_OUT),
            "mask_layer": {"label": "Mask Layer", "help": "Empty = not output"},
            "resolution_x": {"help": "Used when size_ref is not wired; when wired, follows its resolution"},
        },
    },

    # ── Transform 3D (pcg100 c6, warp3d.transform3d): only Rasterize is implemented
    "PCG_COPTransform3D": {
        "order": ["layers", "xform_order", "rotate_order", "translate", "rotate", "scale",
                  "shear", "uniform_scale", "pivot", "pivot_rotate", "invert", "perspective",
                  "camera_distance", "border", "filter"],
        "inputs": {
            "layers": {"label": "Layers", "help": "Empty = all layers"},
            "xform_order": {"label": "Transform Order", "menu": _XF_ORDER},
            "rotate_order": {"label": "Rotate Order", "menu": _ROT_ORDER},
            "translate": {"label": "Translate", "help": "Image space (−1...1 across the long side)"},
            "rotate": {"label": "Rotate"},
            "scale": {"label": "Scale"},
            "shear": {"label": "Shear", "help": "XY, XZ, YZ"},
            "uniform_scale": {"label": "Uniform Scale"},
            "pivot": {"label": "Pivot Translate", "section": "Pivot Transform"},
            "pivot_rotate": {"label": "Pivot Rotate"},
            "invert": {"label": "Invert Transformation", "sep": True},
            "perspective": {"label": "Perspective Camera"},
            "camera_distance": {"label": "Camera Distance", "disable": "{ perspective == 0 }",
                                "help": "Our addition: the perspective camera sits at (0, 0, d)"},
            "border": {"label": "Border",
                       "menu": {"auto": "Auto", "constant": "Constant", "clamp": "Clamp",
                                "mirror": "Mirror", "wrap": "Wrap", "clip": "Clip"},
                       "help": "Our layers have no border metadata, Auto = Clip"},
            "filter": {"label": "Filter", "menu": _W3_FILTER},
        },
    },

    # ── Align(pcg100 c6,warp3d.align_window)
    "PCG_COPAlignWindow": {
        "order": ["layers", "justify_with", "units", "target_point", "target_size",
                  "justify_x", "goal_x", "justify_y", "goal_y", "offset", "scale_to_fit",
                  "uniform_scale", "scale_axis", "filter"],
        "inputs": {
            "layers": {"label": "Layers", "help": "Empty = all layers"},
            "justify_with": {"label": "Justify with",
                             "menu": {"reference": "Reference Window",
                                      "target_point": "Target Point"},
                             "help": "No data window: Data / Display are the same; size_ref not wired = itself"},
            "units": {"label": "Units", "section": "Target", "menu": _UNITS,
                      "disable": "{ justify_with != target_point }"},
            "target_point": {"label": "Target Point", "disable": "{ justify_with != target_point }",
                             "help": "Center of the target rectangle"},
            "target_size": {"label": "Target Size", "disable": "{ justify_with != target_point }"},
            "justify_x": {"label": "Justify X", "section": "Matching", "menu": _JUST},
            "goal_x": {"label": "Goal X", "menu": _GOAL, "disable": "{ justify_x == none }"},
            "justify_y": {"label": "Justify Y", "menu": _JUST},
            "goal_y": {"label": "Goal Y", "menu": _GOAL, "disable": "{ justify_y == none }"},
            "offset": {"label": "Offset by", "help": "Image space"},
            "scale_to_fit": {"label": "Scale to Fit"},
            "uniform_scale": {"label": "Uniform Scale", "disable": "{ scale_to_fit == 0 }"},
            "scale_axis": {"label": "Scale Axis", "menu": {"x": "Scale X", "y": "Scale Y"},
                           "disable": "{ scale_to_fit == 0 } { uniform_scale == 0 }"},
            "filter": {"label": "Filter", "sep": True, "menu": _W3_FILTER},
        },
    },

    # ── Align Pixels(pcg100 c6,warp3d.align_pixels)
    "PCG_COPAlignPixels": {
        "order": ["layers", "side_x", "side_y", "justify_with", "units", "target_point",
                  "justify_x", "goal_x", "justify_y", "goal_y", "offset"],
        "inputs": {
            "layers": {"label": "Layers", "help": "Empty = all layers"},
            "side_x": {"label": "Side (X)", "section": "Snapping", "menu": _SIDE},
            "side_y": {"label": "Side (Y)", "menu": _SIDE},
            "justify_with": {"label": "Justify with",
                             "menu": {"reference": "Reference Window",
                                      "original": "Original Window",
                                      "target_point": "Target Point"}},
            "units": {"label": "Units", "menu": _UNITS,
                      "disable": "{ justify_with != target_point }"},
            "target_point": {"label": "Target Point",
                             "disable": "{ justify_with != target_point }"},
            "justify_x": {"label": "Justify X", "section": "Matching", "menu": _JUST},
            "goal_x": {"label": "Goal X", "menu": _GOAL, "disable": "{ justify_x == none }"},
            "justify_y": {"label": "Justify Y", "menu": _JUST},
            "goal_y": {"label": "Goal Y", "menu": _GOAL, "disable": "{ justify_y == none }"},
            "offset": {"label": "Offset by", "help": "Pixels, rounded"},
        },
    },

    # ── Bend (pcg100 c6, warp3d.bend): Mode decides which set is read
    "PCG_COPBend": {
        "order": ["layers", "mode", "filter", "bottom_left", "bottom_right", "top_left",
                  "top_right", "bl_u", "bl_v", "br_u", "br_v", "tl_u", "tl_v", "tr_u", "tr_v",
                  "side_bottom", "side_top", "side_left", "side_right", "bend_angle",
                  "capture_origin", "capture_direction", "capture_length", "both_directions",
                  "mask_layer"],
        "inputs": {
            "layers": {"label": "Layers", "help": "Empty = all layers"},
            "mode": {"label": "Mode",
                     "menu": {"corners": "Corners", "sides": "Sides", "angle": "Angle"}},
            "filter": {"label": "Filter", "menu": _W3_FILTER},
            "bottom_left": {"label": "Bottom Left", "section": "Corners",
                            "hide": "{ mode == angle }",
                            "help": "Image space; for identity on non-square images use (±W/L, ±H/L)"},
            "bottom_right": {"label": "Bottom Right", "hide": "{ mode == angle }"},
            "top_left": {"label": "Top Left", "hide": "{ mode == angle }"},
            "top_right": {"label": "Top Right", "hide": "{ mode == angle }"},
            "bl_u": {"label": "Bottom Left U", "section": "Corner Handles",
                     "hide": "{ mode != corners }", "help": "Offset relative to the corner"},
            "bl_v": {"label": "Bottom Left V", "hide": "{ mode != corners }"},
            "br_u": {"label": "Bottom Right U", "hide": "{ mode != corners }"},
            "br_v": {"label": "Bottom Right V", "hide": "{ mode != corners }"},
            "tl_u": {"label": "Top Left U", "hide": "{ mode != corners }"},
            "tl_v": {"label": "Top Left V", "hide": "{ mode != corners }"},
            "tr_u": {"label": "Top Right U", "hide": "{ mode != corners }"},
            "tr_v": {"label": "Top Right V", "hide": "{ mode != corners }"},
            "side_bottom": {"label": "Bottom", "section": "Side Handles",
                            "hide": "{ mode != sides }", "help": "Midpoint of the side (the curve passes through it)"},
            "side_top": {"label": "Top", "hide": "{ mode != sides }"},
            "side_left": {"label": "Left", "hide": "{ mode != sides }"},
            "side_right": {"label": "Right", "hide": "{ mode != sides }"},
            "bend_angle": {"label": "Bend Angle", "section": "Capture",
                           "hide": "{ mode != angle }"},
            "capture_origin": {"label": "Capture Origin", "hide": "{ mode != angle }"},
            "capture_direction": {"label": "Capture Direction", "hide": "{ mode != angle }"},
            "capture_length": {"label": "Capture Length", "hide": "{ mode != angle }"},
            "both_directions": {"label": "Deform in Both Directions",
                                "hide": "{ mode != angle }"},
            "mask_layer": {"label": "Mask Layer", "sep": True, "help": "Empty = not output"},
        },
    },

    # ── UV Sample / Sphere Sample: Mode → coordinate layer → source layer → Border → output (all read)
    "PCG_COPUVSample": {
        "order": ["mode", "uv_layer", "source_layer", "border", "out_layer"],
        "inputs": {
            "mode": {"label": "Mode",
                     "menu": {"uv": "UV", "latlong": "Lat-Long (Direction)",
                              "mirror_ball": "Mirror Ball (Direction)"}},
            "uv_layer": {"label": "Coordinate Layer",
                         "help": "UV mode: 2-channel uv; the other two modes: 3-channel direction (N, reflection vector)"},
            "source_layer": {"label": "Source Layer",
                             "help": "Without source, samples itself"},
            "border": {"label": "Border", "menu": dict(_BORDER_MENU)},
            "out_layer": dict(_OUT),
        },
    },

    # ── UV Shape (pcg100 c4, uvshape.uv_shape): Shapes decides which parameter set is read
    "PCG_COPUVShape": {
        "order": ["shape", "disk_mode", "radius", "annulus_mode", "inner_radius",
                  "outer_radius", "offset", "angle", "shear", "uv_filter_bound",
                  "u_border", "v_border", "u_scale", "v_scale", "uv_range",
                  "uv_layer", "uvscale_layer", "mask_layer",
                  "resolution_x", "resolution_y"],
        "inputs": {
            "shape": {"label": "Shapes", "menu": {"disk": "Disk", "annulus": "Annulus"}},
            "disk_mode": {"label": "Mode", "hide": "{ shape != disk }",
                          "menu": {"linear": "Linear", "polar": "Polar",
                                   "equal_area": "Equal Area", "squircle": "Squircle",
                                   "elliptic_arc": "Elliptic Arc"}},
            "radius": {"label": "Radius", "hide": "{ shape != disk }"},
            "annulus_mode": {"label": "Mode", "hide": "{ shape != annulus }",
                             "menu": {"polar": "Polar", "log": "Log"}},
            "inner_radius": {"label": "Inner Radius", "hide": "{ shape != annulus }"},
            "outer_radius": {"label": "Outer Radius", "hide": "{ shape != annulus }"},
            "offset": {"label": "Offset", "section": "Transform"},
            "angle": {"label": "Angle", "section": "Transform"},
            "shear": {"label": "Shear", "section": "Transform", "help": "u += Shear·v"},
            "uv_filter_bound": {"label": "UV Filter Bound", "section": "UV",
                                "disable": '{ uvscale_layer == "" }'},
            "u_border": {"label": "U Border", "section": "UV",
                         "menu": {"clamp": "Clamp", "mirror": "Mirror", "wrap": "Wrap",
                                  "extend": "Extend"}},
            "v_border": {"label": "V Border", "section": "UV",
                         "menu": {"clamp": "Clamp", "mirror": "Mirror", "wrap": "Wrap",
                                  "extend": "Extend"}},
            "u_scale": {"label": "U Scale", "section": "UV"},
            "v_scale": {"label": "V Scale", "section": "UV"},
            "uv_range": {"label": "UV Range", "section": "UV",
                         "menu": {"signed": "−1 to 1 (Houdini)",
                                  "unit": "0 to 1 (for UV Sample)"},
                         "help": "Our UV Sample takes 0~1"},
            "uv_layer": {"label": "UV Layer", "sep": True, "help": "Empty = not output"},
            "uvscale_layer": {"label": "UV Scale Layer", "help": "Empty = not output"},
            "mask_layer": {"label": "Mask Layer", "help": "Empty = not output"},
            "resolution_x": {"help": "Used when no cop is wired; when wired, follows the input's resolution"},
        },
    },

    # ── UV Transform: Translate / Rotate / Scale / Pivot / Wrap (all read)
    "PCG_COPUVTransform": {
        "order": ["layer", "translate", "rotate", "scale", "pivot", "wrap", "out_layer"],
        "inputs": {
            "layer": {"label": "UV Layer"},
            "translate": {"label": "Translate", "sep": True},
            "rotate": {"label": "Rotate", "help": "Counter-clockwise degrees; scale first, then rotate, then translate"},
            "scale": {"label": "Scale"},
            "pivot": {"label": "Pivot"},
            "wrap": {"label": "Wrap (Fractional Part)"},
            "out_layer": dict(_OUT, help="Empty = overwrite the UV layer"),
        },
    },

    # ── Vector Math (Dot / Cross ...): A → Operation → B → T → output
    #    pixel.vector_math: length / normalize do not use B in the result, but B is still parsed,
    #    and a B layer with a different channel count truncates A → only greyed out, not hidden; t is only read for lerp
    "PCG_COPVectorMath": {
        "order": ["a", "op", "b", "t", "out_layer"],
        "inputs": {
            "a": {"label": "Input A Layer"},
            "op": {"label": "Operation",
                   "menu": {"dot": "Dot Product", "cross": "Cross Product",
                            "length": "Length", "normalize": "Normalize",
                            "add": "Add", "subtract": "Subtract",
                            "multiply": "Multiply", "divide": "Divide",
                            "min": "Minimum", "max": "Maximum",
                            "distance": "Distance", "reflect": "Reflect",
                            "lerp": "Lerp"}},
            "b": {"label": "Input B", "disable": "{ op == length } { op == normalize }",
                  "help": "Layer name or constant (\"0 0 1\"); used as the normal for reflect"},
            "t": {"label": "Bias (T)", "hide": "{ op != lerp }"},
            "out_layer": dict(_OUT),
        },
    },

    # ── Vector Transform / 2D / Space Transform: Mode decides which parameter is read
    #    pixel.vector_transform: rotate_2d only reads angle; rotate_3d only rotate; scale only
    #    scale; matrix only matrix; tangent ↔ world only normal_layer / tangent_layer
    "PCG_COPVectorTransform": {
        "order": ["layer", "mode", "angle", "rotate", "scale", "matrix",
                  "normal_layer", "tangent_layer", "out_layer"],
        "inputs": {
            "layer": {"label": "Vector Layer"},
            "mode": {"label": "Transform",
                     "menu": {"rotate_2d": "Rotate 2D", "rotate_3d": "Rotate 3D",
                              "scale": "Scale", "matrix": "Matrix (3×3)",
                              "tangent_to_world": "Tangent to World",
                              "world_to_tangent": "World to Tangent"}},
            "angle": {"label": "Angle", "hide": "{ mode != rotate_2d }",
                      "help": "Rotates the first two components counter-clockwise around z"},
            "rotate": {"label": "Rotate", "hide": "{ mode != rotate_3d }",
                       "help": "Euler angles (degrees), x first, then y, then z"},
            "scale": {"label": "Scale", "hide": "{ mode != scale }"},
            "matrix": {"label": "Matrix", "hide": "{ mode != matrix }",
                       "help": "9 numbers, row-major, v' = M v"},
            "normal_layer": {"label": "Normal Layer",
                             "hide": "{ mode != tangent_to_world mode != world_to_tangent }"},
            "tangent_layer": {"label": "Tangent Layer",
                              "hide": "{ mode != tangent_to_world mode != world_to_tangent }",
                              "help": "Empty = +x projected onto the tangent plane"},
            "out_layer": dict(_OUT, help="Empty = overwrite the input layer"),
        },
    },

    # ── Vignette: Layers → Amount / Radius / Softness / Roundness / Center (all read)
    "PCG_COPVignette": {
        "order": ["layers", "amount", "radius", "softness", "roundness", "center"],
        "inputs": {
            "layers": dict(_LAYERS),
            "amount": {"label": "Amount", "sep": True, "help": "Negative = brighten the edges"},
            "radius": {"label": "Radius"},
            "softness": {"label": "Softness"},
            "roundness": {"label": "Roundness", "help": "1 = circle, 0 = ellipse matching the frame"},
            "center": {"label": "Center", "help": "uv"},
        },
    },

    # ── HeightField Visualize / Visualize Velocity: Mode decides which set is read (hfvis.visualize)
    #    height_ramp reads ramp / lo / hi / hillshade / contour; velocity_hsv reads scale;
    #    velocity_lic reads lic_length / seed; velocity_arrows reads arrow_spacing / scale
    "PCG_COPVisualize": {
        "order": ["layer", "mode", "tint_by", "tint_layer", "range_mode", "ramp", "lo", "hi",
                  "hillshade", "contour_interval",
                  "scale", "lic_length", "rand_seed", "arrow_spacing", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Visualization",
                     "menu": {"height_ramp": "Height Ramp",
                              "velocity_hsv": "Velocity (HSV)",
                              "velocity_lic": "Velocity (LIC)",
                              "velocity_arrows": "Velocity (Arrows)"}},
            # hfvis.visualize: with tint_by == color, range_mode / ramp / lo / hi are not read
            "tint_by": {"label": "Tint by", "hide": "{ mode != height_ramp }",
                        "menu": {"height": "Height", "color": "Color", "mask": "Mask"}},
            "tint_layer": {"label": "Tint Layer",
                           "hide": "{ mode != height_ramp } { tint_by == height }",
                           "help": "Color: used directly as the color; Mask: goes through the color ramp"},
            "range_mode": {"label": "Mode",
                           "hide": "{ mode != height_ramp }",
                           "disable": "{ tint_by == color }",
                           "menu": {"clamped": "Clamped Ramp", "periodic": "Periodic Ramp",
                                    "no_ramp": "No Ramp"}},
            "ramp": {"label": "Color Ramp", "hide": "{ mode != height_ramp }",
                     "disable": "{ tint_by == color } { range_mode == no_ramp }",
                     "menu": {"terrain": "Terrain", "gray": "Grayscale",
                              "viridis": "Viridis", "heat": "Heat"}},
            "lo": {"row": {"kind": "vector", "members": ["lo", "hi"], "label": "Input Range"},
                   "hide": "{ mode != height_ramp }",
                   "disable": "{ tint_by == color }",
                   "help": "Both 0 = use the min / max of the Tint layer"},
            "hi": {"hide": "{ mode != height_ramp }"},
            "hillshade": {"label": "Hillshade", "hide": "{ mode != height_ramp }"},
            "contour_interval": {"label": "Contour Interval",
                                 "hide": "{ mode != height_ramp }", "help": "0 = no contour lines"},
            "scale": {"label": "Velocity Scale",
                      "hide": "{ mode == height_ramp } { mode == velocity_lic }"},
            "lic_length": {"label": "LIC Length", "hide": "{ mode != velocity_lic }",
                           "help": "How many steps to integrate forward and backward along the streamline"},
            "rand_seed": {"label": "Seed", "hide": "{ mode != velocity_lic }"},
            "arrow_spacing": {"label": "Arrow Spacing", "hide": "{ mode != velocity_arrows }",
                              "help": "Pixels"},
            "out_layer": dict(_OUT),
        },
    },

    # ── Warp (backward warp by motion_bwd): layer → motion layer → Units / Edge / Filter → Device (all read)
    "PCG_COPWarp": {
        "order": ["layer", "motion_layer", "units", "edge", "filter", "device"],
        "inputs": {
            "layer": {"label": "Layer"},
            "motion_layer": {"label": "Motion Layer",
                             "help": "Must be backward motion (motion_bwd); forward motion warps the wrong way"},
            "units": {"label": "Motion Units", "sep": True, "menu": dict(_UNITS_MENU)},
            "edge": {"label": "Border",
                     "menu": {"clamp": "Clamp (Streak Edges)", "black": "Constant (Black)",
                              "wrap": "Wrap"}},
            "filter": {"label": "Filter", "menu": dict(_FILTER_MENU)},
            "device": dict(_DEVICE),
        },
    },

    # ── Wipe: Layer → Wipe Type → Transition → type-specific parameters → output
    #    hfvis.wipe: angle only read by linear; center only by radial; softness not read by crossfade;
    #    seed only by dissolve
    "PCG_COPWipe": {
        "order": ["layer", "mode", "t", "angle", "center", "softness", "rand_seed",
                  "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Wipe Type",
                     "menu": {"linear": "Linear", "radial": "Radial",
                              "dissolve": "Dissolve", "crossfade": "Crossfade"}},
            "t": {"label": "Transition", "help": "0 all A, 1 all B (bit-exact at both ends)"},
            "angle": {"label": "Angle", "hide": "{ mode != linear }"},
            "center": {"label": "Center", "hide": "{ mode != radial }", "help": "uv"},
            "softness": {"label": "Softness", "hide": "{ mode == crossfade }"},
            "rand_seed": {"label": "Seed", "hide": "{ mode != dissolve }"},
            "out_layer": dict(_OUT, help="Empty = write back to Layer"),
        },
    },

    # ── Wrangle: since pcg104 it carries ch_params (custom parameters); like the geometry / volume Wrangles it uses native widgets, not taken over

    # ══════════════════════════════════════════ ControlNet / sequence bridges (this plugin's own nodes)
    # ── Control Image: Kind → layer → each kind's own section → sRGB / alignment
    #    control.control_image: near / far / gamma / background only read by depth / height;
    #    flip_* only by normal; the lineart section only by lineart; saturation / value only by id;
    #    invert is not read in the normal / id modes; in the color mode the node forces srgb=True, so the toggle has no effect → greyed out
    "PCG_ControlImage": {
        "order": ["kind", "layer", "mask_layer", "invert",
                  "near", "far", "gamma", "background",
                  "flip_r", "flip_g", "flip_b",
                  "normal_layer", "silhouette", "crease", "threshold", "softness",
                  "thickness", "saturation", "value", "srgb", "color_srgb", "align"],
        "inputs": {
            "kind": {"label": "Control Type",
                     "menu": {"depth": "Depth (Near = White)", "normal": "Normal",
                              "lineart": "Line Art", "mask": "Mask",
                              "id": "Segmentation (ID)", "color": "Color",
                              "raw": "Raw", "height": "Height (High = White)"}},
            "layer": {"label": "Layer",
                      "help": "Empty = default layer for the kind (depth / N / depth / mask / id / C / C / C); "
                              "Line Art takes the depth layer here, the normal layer is filled in separately below"},
            "mask_layer": {"label": "Mask Layer",
                           "help": "Also determines the MASK output; missing layer = all 1"},
            "invert": {"label": "Invert", "hide": "{ kind == normal } { kind == id }"},
            "near": {"label": "Near", "hide": "{ kind != depth kind != height }",
                     "help": "0 = automatic from min inside the mask; in the Height mode, the lower height bound"},
            "far": {"label": "Far", "hide": "{ kind != depth kind != height }",
                    "help": "0 = automatic from max inside the mask; in the Height mode, the upper height bound"},
            "gamma": {"label": "Gamma", "hide": "{ kind != depth kind != height }"},
            "background": {"label": "Background", "hide": "{ kind != depth kind != height }",
                           "help": "Value outside the mask; use 0 for depth (farthest = black)"},
            "flip_r": {"label": "Flip Red (X)", "hide": "{ kind != normal }"},
            "flip_g": {"label": "Flip Green (Y)", "hide": "{ kind != normal }",
                       "help": "OpenGL / DirectX green channel convention"},
            "flip_b": {"label": "Flip Blue (Z)", "hide": "{ kind != normal }"},
            "normal_layer": {"section": "Line Art", "label": "Normal Layer",
                             "hide": "{ kind != lineart }", "help": "Creases are extracted from discontinuities in this layer"},
            "silhouette": {"section": "Line Art", "label": "Silhouette Weight", "hide": "{ kind != lineart }"},
            "crease": {"section": "Line Art", "label": "Crease Weight", "hide": "{ kind != lineart }"},
            "threshold": {"section": "Line Art", "label": "Threshold", "hide": "{ kind != lineart }"},
            "softness": {"section": "Line Art", "label": "Softness", "hide": "{ kind != lineart }"},
            "thickness": {"section": "Line Art", "label": "Line Thickness", "hide": "{ kind != lineart }",
                          "help": "Pixels"},
            "saturation": {"label": "Saturation", "hide": "{ kind != id }"},
            "value": {"label": "Value", "hide": "{ kind != id }"},
            "srgb": {"label": "Encode sRGB", "sep": True, "hide": "{ kind == color }",
                     "help": "Keep off for control images"},
            # The Color mode's own toggle (on by default); both toggles share a label, only one is shown at a time
            "color_srgb": {"label": "Encode sRGB", "sep": True, "hide": "{ kind != color }",
                           "help": "Needed for the Color mode in img2img; off = output linear values unchanged"},
            "align": {"label": "Align Resolution To",
                      "help": "Shrinks to the nearest multiple (latent is /8); 0 = no alignment"},
        },
    },

    # ── ID Masks: ID layer / mask layer / limit (all read)
    "PCG_IDMasks": {
        "order": ["layer", "mask_layer", "max_regions"],
        "inputs": {
            "layer": {"label": "ID Layer"},
            "mask_layer": {"label": "Mask Layer", "help": "Only pixels inside the mask are taken; missing layer = whole image"},
            "max_regions": {"label": "Max Regions", "sep": True,
                            "help": "When exceeded, the largest ones by area are kept"},
        },
    },

    # ── Regional Prompt: two prompt blocks → Mode / Base → Feather / Strength (all read)
    "PCG_RegionalPrompt": {
        "order": ["base_prompt", "regions", "mode", "base", "feather", "strength"],
        "inputs": {
            "base_prompt": {"label": "Base Prompt"},
            "regions": {"label": "Regions", "help": "One `layer_name: prompt` per line"},
            "mode": {"label": "Mask Mode", "sep": True,
                     "menu": {"normalized": "Normalized (Partition)",
                              "layered": "Layered (Later Wins)"}},
            "base": {"label": "Base Coverage",
                     "menu": {"remainder": "Remainder", "global": "Global (Unmasked)"}},
            "feather": {"label": "Feather", "help": "Gaussian blur on the masks first (pixels), 0 = no blur"},
            "strength": {"label": "Strength",
                         "help": "Strength of the regional conditioning; with Base = Global, Base is not multiplied by it"},
        },
    },

    # ── Render Pass: Group / Resolution on top, three tabs Camera / Passes / Attributes
    #    render.camera: fov only read by perspective; ortho_size only by orthographic and not frame;
    #    elev / azim only by orbit / frame; distance only by orbit; margin only by frame;
    #    target is replaced by the bounding sphere center in the frame mode; eye only read by look_at.
    #    render.render: normal_source only read by the normal channel; normal_space affects normal / shade;
    #    id / uv attributes only read by their channels (same as g13's Render Sequence)
    "PCG_RenderPass": {
        "order": ["group", "resolution_x", "resolution_y",
                  "camera", "projection", "fov", "ortho_size", "elev", "azim",
                  "distance", "margin", "target_x", "eye_x", "near", "far",
                  "pass_depth", "pass_mask", "pass_normal", "pass_shade",
                  "pass_position", "pass_uv", "pass_id", "pass_facing",
                  "normal_space", "normal_source", "id_attribute", "uv_attribute",
                  "cull", "device"],
        "inputs": {
            "group": {"label": "Group"},
            "camera": {"folder": "Camera", "label": "Camera Mode",
                       "menu": {"frame": "Frame Geometry", "orbit": "Orbit",
                                "look_at": "Look At"},
                       "help": "Nothing on this tab takes effect when the cam input is wired"},
            "projection": {"folder": "Camera", "label": "Projection",
                           "menu": {"perspective": "Perspective",
                                    "orthographic": "Orthographic"}},
            "fov": {"folder": "Camera", "label": "Field of View",
                    "hide": "{ projection == orthographic }"},
            "ortho_size": {"folder": "Camera", "label": "Ortho Width",
                           "hide": "{ projection == perspective } { camera == frame }"},
            "elev": {"folder": "Camera", "label": "Elevation", "sep": True,
                     "hide": "{ camera == look_at }"},
            "azim": {"folder": "Camera", "label": "Azimuth", "hide": "{ camera == look_at }"},
            "distance": {"folder": "Camera", "label": "Distance",
                         "hide": "{ camera != orbit }"},
            "margin": {"folder": "Camera", "label": "Frame Margin",
                       "hide": "{ camera != frame }", "help": "1 = bounding sphere just touches the frame edges"},
            "target_x": {"folder": "Camera", "section": None, "hide": "{ camera == frame }"},
            "target_y": {"section": None},
            "target_z": {"section": None},
            "eye_x": {"folder": "Camera", "section": None, "hide": "{ camera != look_at }"},
            "eye_y": {"section": None},
            "eye_z": {"section": None},
            "near": {"folder": "Camera", "section": None, "label": "Near Clip", "sep": True},
            "far": {"folder": "Camera", "section": None, "label": "Far Clip",
                    "help": "0 = no far clipping"},
            "pass_depth": {"folder": "Passes", "label": "Depth",
                           "help": "With no channel checked, behaves as if only Mask were checked"},
            "pass_mask": {"folder": "Passes", "label": "Mask"},
            "pass_normal": {"folder": "Passes", "label": "Normal"},
            "pass_shade": {"folder": "Passes", "label": "Shaded Preview"},
            "pass_position": {"folder": "Passes", "label": "Position (P)"},
            "pass_uv": {"folder": "Passes", "label": "UV"},
            "pass_id": {"folder": "Passes", "label": "Piece ID"},
            "pass_facing": {"folder": "Passes", "label": "Facing Ratio"},
            "normal_space": {"folder": "Attributes", "section": None,
                             "label": "Normal Space",
                             "menu": {"camera": "Camera", "world": "World"},
                             "hide": "{ pass_normal == 0 pass_shade == 0 }"},
            "normal_source": {"folder": "Attributes", "section": None,
                              "label": "Normal Source",
                              "menu": {"auto": "Auto (Point N or Face)",
                                       "point": "Point", "face": "Face"},
                              "hide": "{ pass_normal == 0 }"},
            "id_attribute": {"folder": "Attributes", "section": None,
                             "label": "ID Attribute", "hide": "{ pass_id == 0 }"},
            "uv_attribute": {"folder": "Attributes", "section": None,
                             "label": "UV Attribute", "hide": "{ pass_uv == 0 }"},
            "cull": {"folder": "Attributes", "section": None, "label": "Backface Culling",
                     "menu": {"none": "None", "back": "Back Faces",
                              "front": "Front Faces"}},
            "device": dict(_DEVICE),
        },
    },

    # ── Sequence Export (same as COP Export): Layer → Range Mode → Mask Layer (all read)
    "PCG_SequenceExport": {
        "order": ["layer", "mode", "mask_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Range Mode",
                     "menu": {"clamp": "Clamp 0-1", "raw": "Raw",
                              "normalize": "Normalize (Whole Sequence)",
                              "signed": "Signed (-1 to 1 → 0 to 1)"},
                     "help": "Normalize computes min / max over the whole sequence, not per frame"},
            "mask_layer": {"label": "Mask Layer", "sep": True,
                           "help": "Channel 0 per frame (clamped to 0-1); frames missing this layer output all 1"},
        },
    },

    # ── Sequence Import:Layer / Device
    "PCG_SequenceImport": {
        "order": ["layer", "device"],
        "inputs": {
            "layer": {"label": "Layer", "help": "Layer name each frame is written as"},
            "device": dict(_DEVICE),
        },
    },

    # ── Sequence Pick: only Index
    "PCG_SequencePick": {
        "order": ["index"],
        "inputs": {
            "index": {"label": "Frame Index", "help": "Wraps around when out of range (index mod frame count)"},
        },
    },

    # ══════════════════════════════════════════════════════════ Deform SOPs
    # ── Blend Shapes SOP: Mode → per-target weights / Blend for sequential blending → attributes → matching method
    #    deformers.blend_shapes: additive only reads weights; sequential only reads blend
    "PCG_BlendShapes": {
        "order": ["mode", "weight1", "weight2", "weight3", "weight4", "blend",
                  "attributes", "match"],
        "inputs": {
            "mode": {"label": "Blend Mode",
                     "menu": {"additive": "Additive (Differencing)",
                              "sequential": "Sequential Blend"}},
            "weight1": {"label": "Blend 1", "hide": "{ mode != additive }"},
            "weight2": {"label": "Blend 2", "hide": "{ mode != additive }",
                        "help": "No effect when target2 is not wired"},
            "weight3": {"label": "Blend 3", "hide": "{ mode != additive }",
                        "help": "No effect when target3 is not wired"},
            "weight4": {"label": "Blend 4", "hide": "{ mode != additive }",
                        "help": "No effect when target4 is not wired"},
            "blend": {"label": "Blend", "hide": "{ mode != sequential }",
                      "help": "0 = base, 1 = target1, 1.5 = halfway between target1 and 2; counted by slot number, empty slots stop at the previous shape"},
            "attributes": {"label": "Attributes to Blend", "sep": True,
                           "help": "Space-separated point attributes; N is normalized after blending"},
            "match": {"label": "Match By",
                      "menu": {"point_number": "Point Number", "id": "Point Attribute id"}},
        },
    },

    # ── Bulge SOP: Group → Magnitude / Direction → Influence section (magnet) → normals / output attributes
    #    deform3.magnet_field: the surface mode does not read pscale
    "PCG_Bulge": {
        "order": ["group", "magnitude", "direction",
                  "magnet_type", "radius", "use_pscale", "ramp",
                  "update_normals", "weight_attribute"],
        "inputs": {
            "group": {"label": "Group"},
            "magnitude": {"label": "Magnitude", "sep": True},
            "direction": {"label": "Direction",
                          "menu": {"normal": "Along Normal", "radial": "Away from Magnet"}},
            "magnet_type": {"label": "Magnet Type", "section": "Influence",
                            "menu": dict(_MAGNET_TYPE_MENU)},
            "radius": {"label": "Radius", "section": "Influence"},
            "use_pscale": {"label": "Scale Radius by pscale", "section": "Influence",
                           "hide": "{ magnet_type == surface }"},
            "ramp": {"label": "Falloff", "section": "Influence"},
            "update_normals": {"label": "Recompute Normals", "sep": True,
                               "help": "Only recomputed when the input has N"},
            "weight_attribute": {"label": "Output Weight Attribute", "help": "Empty = not written"},
        },
    },

    # ── Twist SOP: Group → Operation / Primary Axis → strength → Secondary Axis (Up) →
    #    Capture section (toggle on the header) → Normals
    #    deform.deform: angle only read by twist / bend; amount only by taper / squash; shear only by shear;
    #    the secondary direction set by up only matters for bend / shear (twist / taper / squash are symmetric around the primary axis)
    "PCG_Deform": {
        "order": ["group", "op", "axis", "up_x", "up_y", "up_z", "pivot_x", "pivot_y", "pivot_z",
                  "angle", "amount", "shear_b", "shear_c",
                  "use_range", "range_start", "range_end", "normals"],
        "inputs": {
            "group": {"label": "Group"},
            "op": {"label": "Operation",
                   "menu": {"twist": "Twist", "bend": "Bend", "taper": "Linear Taper",
                            "squash": "Squash and Stretch", "shear": "Shear"}},
            "axis": {"label": "Primary Axis", "menu": {"x": "X", "y": "Y", "z": "Z"}},
            "amount": {"label": "Scale",
                       "hide": "{ op == twist } { op == bend } { op == shear }",
                       "help": "Taper: scale at the end; Squash: axial scale (lateral 1/√)"},
            "shear_b": {"row": {"kind": "vector", "members": ["shear_b", "shear_c"],
                                "label": "Shear"},
                        "hide": "{ op != shear }",
                        "help": "Pushes along the secondary / third direction (displacement at the end)"},
            "up_x": {"section": None,
                     "row": {"kind": "vector", "members": ["up_x", "up_y", "up_z"],
                             "label": "Secondary Axis (Up)"},
                     "hide": "{ op == twist } { op == taper } { op == squash }",
                     "help": "Which way Bend bends and Shear pushes"},
            "up_y": {"section": None},
            "up_z": {"section": None},
            "pivot_x": {"row": {"kind": "vector", "members": ["pivot_x", "pivot_y", "pivot_z"],
                                "label": "Pivot"},
                        "help": "The deform axis passes through this point (the component along the primary axis has no effect; the range is in absolute coordinates)"},
            "angle": {"label": "Angle", "sep": True,
                      "hide": "{ op == taper } { op == squash } { op == shear }"},
            "use_range": {"label": "Capture Region"},
            "range_start": {"row": {"kind": "vector",
                                    "members": ["range_start", "range_end"],
                                    "label": "Range (Start / End)"},
                            "help": "Absolute coordinates on the primary axis; when off, the actual extent of the selected points is used"},
            "normals": {"label": "Normals", "sep": True,
                        "menu": {"jacobian": "Transform (Jacobian)", "none": "Leave Unchanged"}},
        },
    },

    # ── DeltaMush SOP:Iterations / Step Size / Pin Border / Mask
    "PCG_DeltaMush": {
        "order": ["iterations", "step", "pin_boundary", "mask_attribute"],
        "inputs": {
            "iterations": {"label": "Iterations"},
            "step": {"label": "Step Size"},
            "pin_boundary": {"label": "Pin Border Points"},
            "mask_attribute": {"label": "Mask Attribute", "sep": True,
                               "help": "Point attribute, how much correction each point gets; empty = all 1"},
        },
    },

    # ── Displace from Map (Attribute from Map family): Group / sampling → Amount / Midpoint →
    #    Direction section → UV section
    #    frommap.displace_from_map: dir_xyz only read in the vector mode; normal_attrib only in the normal mode
    "PCG_DisplaceFromMap": {
        "order": ["group", "layer", "channel", "decode", "filter", "border",
                  "amount", "midpoint",
                  "direction", "dir_x", "dir_y", "dir_z", "normal_attrib",
                  "uv_attrib", "uv_from", "uv_scale_u", "uv_scale_v",
                  "uv_offset_u", "uv_offset_v"],
        "inputs": {
            "group": {"label": "Group"},
            "layer": {"label": "Layer", "sep": True},
            "channel": {"label": "Channel"},
            "decode": {"label": "Decode", "menu": dict(_DECODE_MENU),
                       "help": "Data maps (height) usually None; maps stored as sRGB need sRGB to Linear"},
            "filter": {"label": "Filter", "menu": dict(_FILTER_MENU)},
            "border": {"label": "Border", "menu": dict(_BORDER_MENU)},
            "amount": {"label": "Amount", "sep": True},
            "midpoint": {"label": "Midpoint",
                         "help": "The value that does not move: displacement = (value − Midpoint) × Amount"},
            "direction": {"label": "Direction", "section": "Direction",
                          "menu": {"normal": "Along Normal", "vector": "Fixed Vector"}},
            "dir_x": {"hide": "{ direction != vector }"},
            "normal_attrib": {"label": "Normal Attribute", "hide": "{ direction != normal }",
                              "help": "Computed on the fly if missing (not written back)"},
            "uv_attrib": {"label": "UV Attribute"},
            "uv_from": {"label": "UV Source",
                        "menu": {"auto": "Auto", "vertex": "Vertex", "point": "Point"}},
        },
    },

    # ── Fractal SOP:Divisions / Roughness / Scale / Seed / Fixed Boundary / Direction
    #    deform3.fractal: vector only read in the vector mode
    "PCG_Fractal": {
        "order": ["divisions", "roughness", "scale", "rand_seed", "fixed_boundary",
                  "direction", "vector_x", "vector_y", "vector_z"],
        "inputs": {
            "divisions": {"label": "Divisions"},
            "roughness": {"label": "Roughness", "help": "Displacement of each level × Roughness"},
            "scale": {"label": "Scale", "help": "Maximum displacement of the first level"},
            "rand_seed": {"label": "Seed"},
            "fixed_boundary": {"label": "Fixed Boundary"},
            "direction": {"label": "Direction", "sep": True,
                          "menu": {"normal": "Use Normals", "vector": "Fixed Vector"}},
            "vector_x": {"hide": "{ direction != vector }"},
        },
    },

    # ── Lattice SOP (FFD): Group → Interpolation → Outside (all read)
    "PCG_Lattice": {
        "order": ["group", "interpolation", "outside"],
        "inputs": {
            "group": {"label": "Group"},
            "interpolation": {"label": "Interpolation",
                              "menu": {"trilinear": "Trilinear (Local)",
                                       "bezier": "Bezier (Global)"}},
            "outside": {"label": "Points Outside Lattice",
                        "menu": {"deform": "Deform (Extrapolate)",
                                 "keep": "Keep Unchanged"}},
        },
    },

    # ── The lattice part of the Lattice SOP: Divisions / Padding
    "PCG_LatticeFromBound": {
        "order": ["divisions_x", "divisions_y", "divisions_z", "padding"],
        "inputs": {
            "divisions_x": {"help": "Cells per axis; control points = (nx+1)(ny+1)(nz+1)"},
            "padding": {"label": "Padding", "help": "Expands each side of the bounding box"},
        },
    },

    # ── Magnet SOP: Group → Transform (Translate / Rotate / Scale / Pivot) → Influence section
    #    deform3.magnet: pivot only read by custom; magnet_field: the surface mode does not read pscale
    "PCG_Magnet": {
        "order": ["group", "translate_x", "translate_y", "translate_z",
                  "rotate_x", "rotate_y", "rotate_z", "scale_x", "scale_y", "scale_z",
                  "pivot_mode", "pivot_x", "pivot_y", "pivot_z",
                  "magnet_type", "radius", "use_pscale", "ramp", "weight_attribute"],
        "inputs": {
            "group": {"label": "Group"},
            "translate_x": {"help": "Scaled by weight: displacement × w, angle × w, scale lerp(1, s, w)"},
            "pivot_mode": {"label": "Pivot Location", "sep": True,
                           "menu": {"magnet_center": "Magnet Centroid", "origin": "Origin",
                                    "custom": "Custom"}},
            "pivot_x": {"hide": "{ pivot_mode != custom }"},
            "magnet_type": {"label": "Magnet Type", "section": "Influence",
                            "menu": dict(_MAGNET_TYPE_MENU)},
            "radius": {"label": "Radius", "section": "Influence"},
            "use_pscale": {"label": "Scale Radius by pscale", "section": "Influence",
                           "hide": "{ magnet_type == surface }"},
            "ramp": {"label": "Falloff", "section": "Influence"},
            "weight_attribute": {"label": "Output Weight Attribute", "sep": True,
                                 "help": "Empty = not written"},
        },
    },

    # ── Point Deform SOP: Group → Max Points → Mode (all read)
    "PCG_PointDeform": {
        "order": ["group", "max_points", "mode"],
        "inputs": {
            "group": {"label": "Group"},
            "max_points": {"label": "Max Points", "sep": True,
                           "help": "Each point is weighted by this many nearest low-res points"},
            "mode": {"label": "Deformation",
                     "menu": {"rigid": "Rigid (Local Frames)", "translate": "Translate Only"}},
        },
    },

    # ── Soft Peak SOP: Group → Distance → Soft Radius / Metric / Falloff → normals / output attributes
    "PCG_SoftPeak": {
        "order": ["group", "use_mask", "mask_attribute", "distance", "radius", "metric",
                  "distance_attribute", "apply_rolloff", "lead_point_attribute",
                  "translate_along_lead_normal", "soft_type", "tangent_far", "tangent_near",
                  "kernel", "ramp", "update_normals", "weight_attribute"],
        "inputs": {
            "group": {"label": "Group", "help": "Points being pushed (with Metric = Attribute, may be empty = all points)"},
            "use_mask": {"section": None, "gate": None, "in_toggle": "mask_attribute",
                         "help": "Mask: Scale by Attribute -- displacement × attribute value"},
            "mask_attribute": {"label": "Mask Attribute", "section": None, "toggle": "use_mask"},
            "distance": {"label": "Distance", "sep": True, "help": "Distance to push along the point normal"},
            "radius": {"label": "Soft Radius"},
            "metric": {"label": "Distance Metric", "menu": dict(_SOFT_METRIC_MENU)},
            "distance_attribute": {"label": "Distance Attribute", "hide": "{ metric != attribute }"},
            "apply_rolloff": {"label": "Apply Rolloff", "hide": "{ metric != attribute }"},
            "lead_point_attribute": {"label": "Lead Point Attribute",
                                     "hide": "{ metric != attribute }",
                                     "disable": "{ translate_along_lead_normal == 0 }"},
            "translate_along_lead_normal": {"label": "Translate Along Lead Normal"},
            "soft_type": {"label": "Soft Type", "sep": True, "menu": dict(_SOFT_TYPE_MENU)},
            "tangent_far": {"row": {"kind": "vector", "members": ["tangent_far", "tangent_near"],
                                    "label": "Tangent Angles"},
                            "hide": "{ soft_type != cubic }"},
            "kernel": {"label": "Kernel Function", "menu": dict(_KERNEL_MENU),
                       "hide": "{ soft_type != metaball }"},
            "ramp": {"label": "Soft Falloff", "hide": "{ soft_type != ramp }"},
            "update_normals": {"label": "Recompute Normals", "sep": True,
                               "help": "Only recomputed when the input has N"},
            "weight_attribute": {"label": "Output Weight Attribute", "help": "Empty = not written"},
        },
    },

    # ── Soft Transform SOP: Group → Translate / Rotate / Scale → Pivot section →
    #    Soft Radius / Metric / Falloff → Normals → output attributes
    #    deform.soft_transform: with use_group_center on (and a non-empty group), pivot is not read --
    #    it means "when on, the values below are unused", the opposite of section header toggle semantics, so it is a plain toggle inside the section + greying out
    "PCG_SoftTransform": {
        "order": ["group", "xform_order", "rotate_order", "tx", "ty", "tz", "rx", "ry", "rz",
                  "sx", "sy", "sz", "shear_xy", "shear_xz", "shear_yz",
                  "use_group_center", "pivot_x", "pivot_y", "pivot_z", "prx", "pry", "prz",
                  "normals", "preserve_normal_length",
                  "radius", "metric", "distance_attribute", "apply_rolloff",
                  "soft_type", "tangent_far", "tangent_near", "kernel", "falloff_ramp",
                  "falloff_attribute"],
        "inputs": {
            "group": {"label": "Group", "help": "Handle: these points have weight 1; empty = all points (i.e. a plain transform)"},
            "xform_order": {"label": "Transform Order",
                            "menu": {"srt": "Scale Rot Trans", "str": "Scale Trans Rot",
                                     "rst": "Rot Scale Trans", "rts": "Rot Trans Scale",
                                     "tsr": "Trans Scale Rot", "trs": "Trans Rot Scale"}},
            "rotate_order": {"label": "Rotate Order",
                             "menu": {"xyz": "Rx Ry Rz", "xzy": "Rx Rz Ry", "yxz": "Ry Rx Rz",
                                      "yzx": "Ry Rz Rx", "zxy": "Rz Rx Ry", "zyx": "Rz Ry Rx"}},
            "tx": {"help": "Scaled by weight: displacement × w, angle × w, scale lerp(1, s, w), shear × w"},
            "shear_xy": {"row": {"kind": "vector", "members": ["shear_xy", "shear_xz", "shear_yz"],
                                 "label": "Shear"}},
            "use_group_center": {"gate": None, "label": "Pivot at Group Centroid"},
            "pivot_x": {"disable": "{ use_group_center == 1 }"},
            "prx": {"row": {"kind": "vector", "members": ["prx", "pry", "prz"],
                            "label": "Pivot Rotate"}},
            "normals": {"label": "Normals", "sep": True,
                        "menu": {"jacobian": "Transform (Jacobian)", "none": "Leave Unchanged",
                                 "recompute_point": "Recompute Point Normals",
                                 "recompute_affected": "Recompute Affected Normals"}},
            "preserve_normal_length": {"label": "Preserve Normal Length",
                                       "hide": "{ normals != jacobian }"},
            "radius": {"label": "Soft Radius", "sep": True},
            "metric": {"label": "Distance Metric", "menu": dict(_SOFT_METRIC_MENU)},
            "distance_attribute": {"label": "Distance Attribute", "hide": "{ metric != attribute }"},
            "apply_rolloff": {"label": "Apply Rolloff", "hide": "{ metric != attribute }"},
            "soft_type": {"label": "Soft Type", "menu": dict(_SOFT_TYPE_MENU)},
            "tangent_far": {"row": {"kind": "vector", "members": ["tangent_far", "tangent_near"],
                                    "label": "Tangent Angles"},
                            "hide": "{ soft_type != cubic }"},
            "kernel": {"label": "Kernel Function", "menu": dict(_KERNEL_MENU),
                       "hide": "{ soft_type != metaball }"},
            "falloff_ramp": {"label": "Soft Falloff", "hide": "{ soft_type != ramp }"},
            "falloff_attribute": {"label": "Output Falloff Attribute", "sep": True,
                                  "help": "Empty = not written"},
        },
    },
}
