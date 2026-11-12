"""
Parameter panel specs for group g7: a batch of COPs (Gradient ... Polar, line 7 of groups85.txt).
Format: see the docstring at the top of panel_specs.py.

All hide / disable conditions follow the node's run() and the geo/cop/ implementation (see each entry's comment), not guesses based on Houdini.
Parameters that depend only on "whether some input is wired" (e.g. HF Project's geo, Heightfield from Depth's
moge_geometry) cannot be expressed as panel conditions; they only get a help text and are not hidden.
"""

_DEVICE_MENU = {"auto": "Auto", "cpu": "CPU", "cuda": "CUDA", "numpy": "NumPy",
                "exact": "Exact (float64)"}
_COMPUTE_MENU = {"auto": "Auto", "cpu": "CPU", "cuda": "CUDA"}
# filters.BORDERS = clamp / wrap / black (Copernicus Border: Clamp / Wrap / Constant)
_BORDER_MENU = {"clamp": "Clamp", "wrap": "Wrap", "black": "Constant (Black)"}
_PLANE_MENU = {"xz": "XZ Plane", "xy": "XY Plane", "zy": "ZY Plane"}
_SHAPE_MENU = {"box": "Square", "disc": "Circle"}
_LAYERS = {"label": "Layers", "help": "Empty = all layers, space-separated"}
_OUT = {"label": "Output Layer", "sep": True}
_KEEP = {"label": "Keep Input Layers"}

from .geo.cop import noisepost as _cpost                       # noqa: E402
_PP = list(_cpost.KEYS)
_METRIC_MENU = {"euclidean": "Euclidean", "manhattan": "Manhattan",
                "chebyshev": "Chebyshev"}
# Pattern section shared by Worley / Cellular (parameters of cellnoise.cell_fields)
_CELL_PATTERN = {
    "element_size": {"label": "Element Size", "section": "Pattern",
                     "help": "Image coordinates (image width = 1)"},
    "element_scale": {"label": "Element Scale", "help": "Per-axis scale (anisotropic)"},
    "jitter": {"label": "Jitter", "help": "0 = regular grid; > 1 runs outside the search range"},
    "jitter_scale": {"label": "Jitter Scale"},
    "metric": {"label": "Metric", "menu": _METRIC_MENU},
    "offset": {"label": "Offset"},
    "tile": {"label": "Tile", "sep": True,
             "help": "Cell count = round(Tile Size / Element Size), Element Size is adjusted slightly to match"},
    "tile_size": {"label": "Tile Size", "disable": "{ tile == 0 }",
                  "help": "For non-square images, give it according to the aspect ratio (image width = 1)"},
    "pos_layer": {"label": "Pos Layer", "sep": True,
                  "help": "Optional when a cop is wired: 2 channels = 2D coordinates, 3 channels = 3D version (world coordinates)"},
    "rand_seed": {"label": "Seed"},
    "prefix": {"label": "Layer Prefix", "help": "Prefix for output layer names"},
}

SPECS = {
    # ── Copernicus Ramp family: Ramp Type → each type's own parameters → Ramp; output layer name last
    "PCG_COPGradient": {
        "order": ["resolution_x", "resolution_y", "direction", "angle",
                  "center_x", "center_y", "ramp", "ramp_mode", "layer", "device"],
        "inputs": {
            "direction": {"label": "Ramp Type",
                          "menu": {"v": "Linear V (Vertical)",
                                   "u": "Linear U (Horizontal)",
                                   "diagonal": "Linear (Angle)",
                                   "radial": "Radial", "angular": "Angular"}},
            # generate.gradient: angle is only read in the diagonal branch
            "angle": {"label": "Angle", "hide": "{ direction != diagonal }"},
            # center is only read in the radial / angular branches
            "center_x": {"hide": "{ direction != radial direction != angular }"},
            "center_y": {"hide": "{ direction != radial direction != angular }"},
            "ramp": {"label": "Ramp", "sep": True,
                     "help": "position:value, space-separated; values may be written as r,g,b for multiple channels"},
            "ramp_mode": {"label": "Interpolation",
                          "menu": {"linear": "Linear", "smooth": "Smooth",
                                   "constant": "Constant"}},
            "layer": {"label": "Output Layer", "sep": True},
            "device": {"label": "Device", "menu": _DEVICE_MENU},
        },
    },

    # ── HeightField Clip: Layer / Mask Layer → Clip mode → Min / Max → Softness
    "PCG_COPHFClip": {
        "order": ["layer", "mask_layer", "mode", "min", "max", "softness",
                  "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mask_layer": {"label": "Mask Layer", "help": "Empty = whole image; 0~1 blends back to the original height by the mask"},
            "mode": {"label": "Clip", "sep": True,
                     "menu": {"both": "Clip Below and Above", "above": "Clip Above",
                              "below": "Clip Below"}},
            # hfvis.hf_clip: below only reads min, above only reads max
            "min": {"label": "Minimum Height", "hide": "{ mode == above }"},
            "max": {"label": "Maximum Height", "hide": "{ mode == below }"},
            "softness": {"label": "Softness",
                         "help": "Soft knee width (height value); 0 = hard clamp"},
            "out_layer": {"label": "Output Layer", "sep": True,
                          "help": "Empty = overwrite Layer; also writes <name>_clipped (the change)"},
        },
    },

    # ── HeightField Cutout by Object
    "PCG_COPHFCutoutByObject": {
        "order": ["layer", "strength", "world_size", "mode", "out_layer"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale", "help": "Height value × Height Scale = world height"},
            "world_size": {"label": "World Size", "help": "Width of the height field in xz (centered)"},
            "mode": {"label": "Operation", "sep": True,
                     "menu": {"carve": "Carve (Cut Down)", "fill": "Fill (Raise Up)",
                              "both": "Carve and Fill"}},
            "out_layer": {"label": "Output Layer", "sep": True,
                          "help": "Empty = overwrite Height Layer; also writes <name>_cut"},
        },
    },

    # ── HeightField Mask by Object
    "PCG_COPHFMaskByObject": {
        "order": ["mode", "layer", "strength", "world_size", "feather", "invert",
                  "out_layer"],
        "inputs": {
            "mode": {"label": "Mask Type",
                     "menu": {"footprint": "Footprint", "intersect": "Intersecting Ground",
                              "above": "Above Ground", "below": "Below Ground"}},
            # hfobject.mask_by_object: footprint does not read the height layer, neither layer nor strength is used
            "layer": {"label": "Height Layer", "hide": "{ mode == footprint }"},
            "strength": {"label": "Height Scale", "hide": "{ mode == footprint }"},
            "world_size": {"label": "World Size"},
            "feather": {"label": "Feather", "sep": True, "help": "Outward feather width (world units)"},
            "invert": {"label": "Invert Mask"},
            "out_layer": {"label": "Output Layer", "sep": True},
        },
    },

    # ── HeightField Project / Transform 3D: geo wired = Project, not wired = Transform 3D
    #    hfvis.hf_project: mode / mask / mask_layer are not read when projection_only is on
    "PCG_COPHFProject": {
        "order": ["layer", "project", "max_height", "mask", "mask_layer",
                  "mode", "projection_only", "fill_value", "strength", "world_size",
                  "translate", "rotate", "scale", "out_layer", "hitmask_layer"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "project": {"label": "Project",
                        "menu": {"maximum": "Maximum Height", "minimum": "Minimum Height"}},
            "max_height": {"label": "Max Projection Height",
                           "help": "> 0: only projects geometry with |height value| ≤ it; 0 = unlimited"},
            "mask": {"label": "Mask", "disable": "{ projection_only == 1 }",
                     "help": "Blend amount; multiplied onto Mask Layer when that is given"},
            "mask_layer": {"label": "Mask Layer", "disable": "{ projection_only == 1 }"},
            "mode": {"label": "Blend Mode", "sep": True,
                     "disable": "{ projection_only == 1 }",
                     "menu": {"max": "Maximum", "min": "Minimum", "add": "Add",
                              "replace": "Replace", "blend": "Blend",
                              "multiply": "Multiply"},
                     "help": "Only takes effect when geo is wired; without geo (Transform 3D) it is fixed to Replace. "
                             "Blend = hits replaced by the projection, misses unchanged; Replace fills misses with Fill Value"},
            "projection_only": {"label": "Output Projection Only"},
            # fill_value: with geo wired it is read by replace / projection-only, without geo it is always read -- the panel cannot tell wiring, so not hidden
            "fill_value": {"label": "Fill Value",
                           "help": "Value for texels that were not hit (with geo wired, only used under Replace / Output Projection Only)"},
            "strength": {"label": "Height Scale", "sep": True},
            "world_size": {"label": "World Size"},
            "translate": {"label": "Translate", "section": "Transform 3D",
                          "help": "Only takes effect without geo: transforms the height field as a mesh in 3D and projects it back"},
            "rotate": {"label": "Rotate", "section": "Transform 3D"},
            "scale": {"label": "Scale", "section": "Transform 3D"},
            "out_layer": {"label": "Output Layer", "sep": True,
                          "help": "Empty = overwrite Height Layer"},
            "hitmask_layer": {"label": "Hitmask Layer", "help": "Hit 1, miss 0; empty = not output"},
        },
    },

    # ── Heat Distort / Heat Distort by Layer
    "PCG_COPHeatDistort": {
        "order": ["layers", "amount", "scale", "direction", "speed", "time",
                  "rand_seed", "field_layer", "border"],
        "inputs": {
            "layers": _LAYERS,
            "amount": {"label": "Amount", "sep": True, "help": "Pixels"},
            "scale": {"label": "Element Size", "help": "Noise feature scale (uv units)"},
            "direction": {"label": "Direction", "help": "Direction the heat haze drifts (degrees)"},
            "speed": {"label": "Speed"},
            "time": {"label": "Time", "help": "Wire in the frame number to animate; actual offset = Time × Speed"},
            "rand_seed": {"label": "Seed"},
            "field_layer": {"label": "Field Layer", "sep": True,
                            "help": "When given, scales the distortion strength by its value (above the heat source)"},
            "border": {"label": "Border", "menu": _BORDER_MENU},
        },
    },

    # ── Heat Distort by Layer(pcg100 c7,filtersim.heat_distort_by_layer):
    #    Step Pixels is only read with Accurate on; Timestep / each Blur Size / the chromatic aberration multiplier only when their toggles are on
    "PCG_COPHeatDistortByLayer": {
        "order": ["layers", "noise_layer", "effect_layer", "dir_layer", "mask", "mask_layer",
                  "scale", "angle", "accurate", "step_pixels", "streak_blur",
                  "scale_by_timestep", "timestep", "blur_source", "blur_source_size",
                  "blur_noise", "blur_noise_size", "chromatic", "ca_scale", "ca_red",
                  "ca_green", "ca_blue", "border"],
        "inputs": {
            "layers": {"label": "Source Layers", "help": "Empty = all layers except noise / effect / dir / mask"},
            "noise_layer": {"label": "Noise Layer"},
            "effect_layer": {"label": "Effect Layer", "help": "Empty = 1; scales the distortion strength per pixel"},
            "dir_layer": {"label": "Direction Layer", "help": "Empty = use the gradient of noise as the direction"},
            "mask": {"label": "Mask"},
            "mask_layer": {"label": "Mask Layer", "help": "Empty = no mask layer"},
            "scale": {"label": "Scale", "section": "Distortion", "help": "Displacement = Scale · effect · ∇noise (image units)"},
            "angle": {"label": "Angle", "section": "Distortion"},
            "accurate": {"label": "Accurate Distortion", "section": "Distortion"},
            "step_pixels": {"label": "Pixels per Step", "section": "Distortion",
                            "disable": "{ accurate == 0 streak_blur == 0 }"},
            "streak_blur": {"label": "Streak Blur", "section": "Distortion"},
            "scale_by_timestep": {"label": "Scale by Timestep", "section": "Distortion"},
            "timestep": {"label": "Timestep", "section": "Distortion",
                         "disable": "{ scale_by_timestep == 0 }", "help": "We have no $FPS, so it is given here (default 1/24)"},
            "blur_source": {"label": "Blur Source", "section": "Blur Source"},
            "blur_source_size": {"label": "Blur Size", "section": "Blur Source",
                                 "disable": "{ blur_source == 0 }"},
            "blur_noise": {"label": "Blur Noise", "section": "Blur Noise"},
            "blur_noise_size": {"label": "Blur Size", "section": "Blur Noise",
                                "disable": '{ blur_noise == 0 } { dir_layer != "" }'},
            "chromatic": {"label": "Chromatic Aberration", "section": "Chromatic Aberration"},
            "ca_scale": {"label": "Scale", "section": "Chromatic Aberration",
                         "disable": "{ chromatic == 0 }"},
            "ca_red": {"label": "Red", "section": "Chromatic Aberration",
                       "disable": "{ chromatic == 0 }"},
            "ca_green": {"label": "Green", "section": "Chromatic Aberration",
                         "disable": "{ chromatic == 0 }"},
            "ca_blue": {"label": "Blue", "section": "Chromatic Aberration",
                        "disable": "{ chromatic == 0 }"},
            "border": {"label": "Border", "sep": True, "menu": _BORDER_MENU},
        },
    },

    # ── Height to Caustics (no Copernicus equivalent, organized like the height map family): Height → Water → Light → Quality
    "PCG_COPHeightToCaustics": {
        "order": ["layer", "strength", "world_size", "depth", "ior", "azimuth",
                  "elevation", "supersample", "tile", "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale", "section": "Height"},
            "world_size": {"label": "World Size", "section": "Height"},
            "depth": {"label": "Water Depth", "section": "Water"},
            "ior": {"label": "IOR", "section": "Water"},
            # heightmap.height_to_caustics: with elevation ≥ 90, ce = 0, azimuth is multiplied by 0 and has no effect
            "azimuth": {"label": "Azimuth", "section": "Light",
                        "disable": "{ elevation >= 90 }"},
            "elevation": {"label": "Elevation", "section": "Light"},
            "supersample": {"label": "Supersample", "section": "Quality",
                            "help": "Supersample² photons per pixel"},
            "tile": {"label": "Tileable (Wrap Edges)", "section": "Quality"},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    # ── Height to Shadow:Height → Light → Quality
    "PCG_COPHeightToShadow": {
        "order": ["layer", "strength", "world_size", "azimuth", "elevation",
                  "softness", "max_distance", "step", "tile", "invert",
                  "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale", "section": "Height"},
            "world_size": {"label": "World Size", "section": "Height"},
            "azimuth": {"label": "Azimuth", "section": "Light",
                        "help": "Direction the light comes from: 0° = +u, 90° = +v"},
            "elevation": {"label": "Elevation", "section": "Light"},
            "softness": {"label": "Softness", "section": "Light",
                         "help": "Angular radius of the sun (degrees), 0 = hard shadows"},
            "max_distance": {"label": "Max Distance", "section": "Quality",
                             "help": "Pixels"},
            "step": {"label": "Step Size", "section": "Quality", "help": "Pixels"},
            "tile": {"label": "Tileable (Wrap Edges)", "section": "Quality"},
            "invert": {"label": "Invert (1 = Lit)", "sep": True},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    # ── Heightfield from Depth (our own node): Mode selects one of two parameter sets
    "PCG_COPHeightfieldFromDepth": {
        "order": ["mode", "depth_kind", "batch_index", "resolution", "fov_x",
                  "up", "far_quantile", "fill_holes", "shift", "sky",
                  "relief", "world_size", "dequantize"],
        "inputs": {
            "mode": {"label": "Projection",
                     "menu": {"perspective": "Perspective (Photo)",
                              "top_down": "Top Down (Orthographic)"}},
            "depth_kind": {"label": "Depth Type",
                           "menu": {"disparity": "Disparity (Inverse Depth)",
                                    "depth": "Depth"},
                           "help": "Not used when moge_geometry is wired"},
            "batch_index": {"label": "Batch Index"},
            # lift.lift: top_down only reads depth_kind / relief / world_size / batch_index,
            # resolution follows the depth image; resolution / fov / up / far_quantile / fill_holes are only read in perspective
            "resolution": {"label": "Resolution", "sep": True,
                           "hide": "{ mode == top_down }"},
            "fov_x": {"label": "Horizontal FOV", "hide": "{ mode == top_down }",
                      "help": "Only used when depth is wired (and moge_geometry is not)"},
            # points_from_depth: shift / sky are only read in the disparity branch
            "shift": {"label": "Disparity Shift",
                      "hide": "{ mode == top_down } { depth_kind == depth }",
                      "help": "z = 1 / (d + Shift); only used when depth is wired"},
            "sky": {"label": "Sky Threshold",
                    "hide": "{ mode == top_down } { depth_kind == depth }",
                    "help": "Pixels with disparity ≤ Sky are treated as sky and dropped"},
            "up": {"label": "Up Vector", "hide": "{ mode == top_down }",
                   "menu": {"fit_plane": "Fit Ground Plane",
                            "camera_level": "Camera Level"}},
            "far_quantile": {"label": "Far Quantile", "hide": "{ mode == top_down }"},
            "fill_holes": {"label": "Fill Holes", "hide": "{ mode == top_down }"},
            "relief": {"label": "Relief", "hide": "{ mode == perspective }",
                       "help": "Height range = Relief × World Size"},
            "world_size": {"label": "World Size", "hide": "{ mode == perspective }"},
            # lift.dequantize: depth input only, and only acts on values on the 1/255 lattice
            "dequantize": {"label": "Dequantize 8-bit Depth", "sep": True,
                           "help": "Smooths an 8-bit depth map back to continuous values within its 256 levels; "
                                   "removes the far-field streaks / terraces. No effect on float depth or MoGe"},
        },
    },

    # ── HeightField Convert to mesh family: height → decimation → options → carried-over layers
    "PCG_COPHeightfieldToMesh": {
        "order": ["layer", "strength", "world_size", "step", "center", "normals",
                  "attribs"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "step": {"label": "Step", "sep": True, "help": "Takes one point every Step pixels (no resampling)"},
            "center": {"label": "Center at Origin"},
            "normals": {"label": "Compute Normals"},
            "attribs": {"label": "Layers to Attributes", "sep": True},
        },
    },

    # ── Hex Tile
    "PCG_COPHexTile": {
        "order": ["layer", "tiles", "rotation", "contrast", "rand_seed",
                  "xres", "yres", "out_layer"],
        "inputs": {
            "layer": {"label": "Source Layer",
                      "help": "Taken from source when wired, otherwise from cop"},
            "tiles": {"label": "Tile Count", "help": "How many texture periods across the image width"},
            "rotation": {"label": "Max Rotation", "help": "Each cell is rotated randomly by ±Rotation degrees"},
            "contrast": {"label": "Blend Contrast", "help": "Larger = narrower seams"},
            "rand_seed": {"label": "Seed"},
            "xres": {"row": {"kind": "vector", "members": ["xres", "yres"],
                             "label": "Resolution"},
                     "sep": True, "help": "0 = follow the input"},
            "out_layer": _OUT,
        },
    },

    # ── Histogram:Equalize / Match
    "PCG_COPHistogram": {
        "order": ["mode", "layers", "ref_layer", "mask_layer", "amount"],
        "inputs": {
            "mode": {"label": "Mode",
                     "menu": {"equalize": "Equalize", "match": "Match Reference"}},
            "layers": {"label": "Layers", "help": "Empty = all layers"},
            # analysis.histogram: ref_layer is only read in the match branch
            "ref_layer": {"label": "Reference Layer", "hide": "{ mode != match }"},
            "mask_layer": {"label": "Mask Layer", "sep": True,
                           "help": "When given, only pixels inside the mask are changed"},
            "amount": {"label": "Amount"},
        },
    },

    # ── HeightField Erode (hydraulic, droplet model): main parameters on top; three tabs Erosion / Output / Advanced
    "PCG_COPHydraulicErosion": {
        "order": ["layer", "strength", "world_size", "tile", "hardness_layer",
                  "rand_seed",
                  "droplets_per_pixel", "lifetime", "erode_rate", "deposit_rate",
                  "capacity", "inertia", "min_slope", "evaporate", "gravity",
                  "radius", "deposit_radius", "end_mode",
                  "out_layer", "deposit_layer", "accumulate_deposit",
                  "erosion_layer", "wet_layer", "keep_layers",
                  "batch", "compute"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "tile": {"label": "Tileable (Wrap Edges)"},
            "hardness_layer": {"label": "Hardness Layer", "help": "0~1, 1 = bedrock that does not erode"},
            "rand_seed": {"label": "Seed"},
            "droplets_per_pixel": {"label": "Droplets per Pixel", "folder": "Erosion"},
            "lifetime": {"label": "Max Lifetime", "folder": "Erosion",
                         "help": "Maximum steps per droplet"},
            "erode_rate": {"label": "Erosion Rate", "folder": "Erosion"},
            "deposit_rate": {"label": "Deposition Rate", "folder": "Erosion"},
            "capacity": {"label": "Sediment Capacity", "folder": "Erosion"},
            "inertia": {"label": "Inertia", "folder": "Erosion"},
            "min_slope": {"label": "Min Slope", "folder": "Erosion"},
            "evaporate": {"label": "Evaporation Rate", "folder": "Erosion"},
            "gravity": {"label": "Gravity", "folder": "Erosion"},
            "radius": {"label": "Erosion Radius", "folder": "Erosion"},
            "deposit_radius": {"label": "Deposition Radius", "folder": "Erosion",
                               "help": "≤ 1 = bilinear deposit into four cells"},
            "end_mode": {"label": "At End of Lifetime", "folder": "Erosion",
                         "menu": {"spread": "Spread Sediment", "lose": "Discard Sediment"}},
            "out_layer": {"label": "Output Layer", "folder": "Output"},
            "deposit_layer": {"label": "Deposit Layer", "folder": "Output",
                              "help": "Empty = not output"},
            # hydro: when dl is empty the whole section is not written, accumulate is not read
            "accumulate_deposit": {"label": "Accumulate onto Existing", "folder": "Output",
                                   "disable": '{ deposit_layer == "" }'},
            "erosion_layer": {"label": "Erosion Layer", "folder": "Output",
                              "help": "Empty = not output"},
            "wet_layer": {"label": "Wetness Layer", "folder": "Output",
                          "help": "Empty = not output"},
            "keep_layers": {"label": "Keep Input Layers", "folder": "Output"},
            "batch": {"label": "Batch Size", "folder": "Advanced", "section": None,
                      "help": "Droplets simulated at once; larger = faster but deviates more from the one-droplet-at-a-time algorithm"},
            "compute": {"label": "Compute", "folder": "Advanced", "menu": _COMPUTE_MENU},
        },
    },

    # ── HeightField Erode (grid: virtual pipes + thermal): main parameters on top; tabs Erosion / Thermal / Output / Advanced
    "PCG_COPHeightfieldErode": {
        "order": ["layer", "strength", "world_size", "iterations", "rain", "evaporation", "tile",
                  "hardness_layer", "rain_layer",
                  "capacity", "erode_rate", "deposit_rate", "min_slope", "max_depth", "damping",
                  "bed_change_limit",
                  "talus_angle", "thermal_rate",
                  "out_layer", "flow_layer", "water_layer", "sediment_layer", "debris_layer",
                  "accumulate_debris", "erosion_layer", "keep_layers", "compute"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "iterations": {"label": "Iterations"},
            "rain": {"label": "Rain", "help": "Water added to every cell per step, in cells (pixel size)"},
            "evaporation": {"label": "Evaporation", "help": "Fraction of the water that evaporates per step"},
            "tile": {"label": "Tileable (Wrap Edges)", "help": "Off: water and sediment drain off the image edges"},
            "hardness_layer": {"label": "Hardness Layer", "help": "0~1, 1 = bedrock that does not erode or slump"},
            "rain_layer": {"label": "Rain Layer", "help": "Multiplies Rain per cell; empty = uniform"},
            "capacity": {"label": "Sediment Capacity", "folder": "Erosion", "section": None,
                         "help": "Capacity × slope × speed × depth: how much material the water can carry"},
            "erode_rate": {"label": "Erosion Rate", "folder": "Erosion", "section": None},
            "deposit_rate": {"label": "Deposition Rate", "folder": "Erosion", "section": None},
            "min_slope": {"label": "Min Slope", "folder": "Erosion", "section": None,
                          "help": "Flat ground still carries this much (sine of the tilt)"},
            "max_depth": {"label": "Max Erosion Depth", "folder": "Erosion", "section": None,
                          "help": "Water deeper than this (cells) erodes no faster: lakes don't dig"},
            "damping": {"label": "Flow Damping", "folder": "Erosion", "section": None,
                        "help": "How much of last step's flux is kept (momentum)"},
            "bed_change_limit": {"label": "Bed Change Limit", "folder": "Erosion", "section": None,
                                 "help": "0 = off. Caps how far the bed moves per step, as a fraction of the water "
                                         "depth; 0.03 stops the ripples a Capacity above ~3 makes"},
            "talus_angle": {"label": "Talus Angle", "folder": "Thermal", "section": None},
            "thermal_rate": {"label": "Thermal Rate", "folder": "Thermal", "section": None,
                             "help": "0 = no slumping"},
            "out_layer": {"label": "Output Layer", "folder": "Output"},
            "flow_layer": {"label": "Flow Layer", "folder": "Output", "help": "0..1 mask; empty = not output"},
            "water_layer": {"label": "Water Layer", "folder": "Output", "help": "Empty = not output"},
            "sediment_layer": {"label": "Sediment Layer", "folder": "Output", "help": "Empty = not output"},
            "debris_layer": {"label": "Debris Layer", "folder": "Output", "help": "Empty = not output"},
            "accumulate_debris": {"label": "Accumulate onto Existing", "folder": "Output",
                                  "disable": '{ debris_layer == "" }'},
            "erosion_layer": {"label": "Erosion Layer", "folder": "Output", "help": "Empty = not output"},
            "keep_layers": {"label": "Keep Input Layers", "folder": "Output"},
            "compute": {"label": "Compute", "folder": "Advanced", "menu": _COMPUTE_MENU},
        },
    },

    # ── ID to Mask / ID to Mono / ID to SDF
    "PCG_COPIDConvert": {
        "order": ["layer", "mode", "ids", "invert", "normalize", "out_layer"],
        "inputs": {
            "layer": {"label": "ID Layer"},
            "mode": {"label": "Convert To",
                     "menu": {"mask": "Mask", "mono": "Mono", "sdf": "SDF"}},
            # uvx.id_convert: the mono branch does not read ids / invert, only mono reads normalize
            "ids": {"label": "IDs", "hide": "{ mode == mono }",
                    "help": "E.g. 1 3 5-8; in the SDF mode empty = distance from each piece to the other ids"},
            "invert": {"label": "Invert", "hide": "{ mode == mono }"},
            "normalize": {"label": "Normalize", "hide": "{ mode != mono }"},
            "out_layer": {"label": "Output Layer", "sep": True,
                          "help": "Empty = <layer>_<mode>"},
        },
    },

    # ── Histogram (Houdini semantics, drawn as an image): all parameters are always read
    "PCG_COPHistogramPlot": {
        "order": ["layer", "mode", "buckets", "min", "max", "outside", "scale",
                  "red", "green", "blue", "alpha", "active_layer", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "mode": {"label": "Mode",
                     "menu": {"colored_bars": "Colored Bars",
                              "separate_bars": "Separate Bars", "graph": "Graph"}},
            "buckets": {"label": "Buckets"},
            "min": {"label": "Minimum"},
            "max": {"label": "Maximum"},
            "outside": {"label": "Outside Values",
                        "menu": {"discard": "Discard", "clamp": "Clamp"}},
            "scale": {"label": "Scale", "help": "Multiplies \"pixels in bucket / total pixels\""},
            "red": {"label": "Red", "sep": True, "help": "Single-channel layers only look at this toggle"},
            "green": {"label": "Green"},
            "blue": {"label": "Blue"},
            "alpha": {"label": "Alpha"},
            "active_layer": {"label": "Active Layer", "sep": True,
                             "help": "Only pixels where this layer ≥ 0.5 are counted; empty = whole image"},
            "out_layer": {"label": "Output Layer"},
        },
    },

    # ── Illegal Pixel: pixel.illegal_pixel -- the three replacement values and Clamp Negative are only read by replace;
    #    highlight_color is only read by highlight / isolate; detect is not read in the replace mode
    #    (there nan / ±inf each have their own replacement value), rule / value are only read when detect = custom
    "PCG_COPIllegalPixel": {
        "order": ["layers", "mode", "highlight_color", "detect", "rule", "value",
                  "nan", "pos_inf", "neg_inf", "clamp_negative"],
        "inputs": {
            "layers": _LAYERS,
            "mode": {"label": "Illegal Pixels",
                     "menu": {"replace": "Fix by Replacing Values (PCG)",
                              "blend": "Fix by Blending Surrounding Pixels",
                              "zero": "Fix by Zeroing",
                              "highlight": "Show with Highlight",
                              "isolate": "Show by Isolating"}},
            "highlight_color": {"label": "Highlight Color",
                                "hide": "{ mode != highlight mode != isolate }"},
            "detect": {"label": "Detect", "hide": "{ mode == replace }",
                       "menu": {"nan": "NaN Values", "inf": "Infinite Values",
                                "nan_inf": "NaN and Infinite Values",
                                "custom": "Custom"}},
            "rule": {"label": "Rule",
                     "hide": "{ mode == replace } { detect != custom }",
                     "menu": {"less": "Less Than", "less_equal": "Less Than or Equal",
                              "greater": "Greater Than",
                              "greater_equal": "Greater Than or Equal",
                              "equal": "Equal"}},
            "value": {"label": "Value",
                      "hide": "{ mode == replace } { detect != custom }"},
            "nan": {"label": "Replace NaN With", "sep": True,
                    "hide": "{ mode != replace }"},
            "pos_inf": {"label": "Replace +Inf With", "hide": "{ mode != replace }"},
            "neg_inf": {"label": "Replace −Inf With", "hide": "{ mode != replace }"},
            "clamp_negative": {"label": "Clamp Negative Values",
                               "hide": "{ mode != replace }"},
        },
    },

    # ── Import(IMAGE → COP)
    "PCG_COPImport": {
        "order": ["layer", "batch_index", "device"],
        "inputs": {
            "layer": {"label": "Output Layer"},
            "batch_index": {"label": "Batch Index"},
            "device": {"label": "Device", "sep": True, "menu": _DEVICE_MENU},
        },
    },

    # ── Invert
    "PCG_COPInvert": {
        "order": ["layers", "pivot", "invert_alpha"],
        "inputs": {
            "layers": _LAYERS,
            "pivot": {"label": "Pivot", "help": "x → Pivot − x"},
            "invert_alpha": {"label": "Invert Alpha"},
        },
    },

    # ── Kuwahara Filter
    "PCG_COPKuwahara": {
        "order": ["layers", "radius"],
        "inputs": {
            "layers": _LAYERS,
            "radius": {"label": "Radius", "help": "Pixels"},
        },
    },

    # ── Lattice Deform
    "PCG_COPLatticeDeform": {
        "order": ["layers", "divisions", "offsets", "jitter", "rand_seed", "border"],
        "inputs": {
            "layers": _LAYERS,
            "divisions": {"label": "Divisions", "sep": True},
            "offsets": {"label": "Point Offsets",
                        "help": "Two numbers per control point (uv offset), row by row from bottom to top; padded with 0 if short"},
            "jitter": {"label": "Jitter"},
            # fx.lattice_deform: with jitter ≤ 0 no random numbers are generated and seed is not read
            "rand_seed": {"label": "Seed", "disable": "{ jitter == 0 }"},
            "border": {"label": "Border", "sep": True, "menu": _BORDER_MENU},
        },
    },

    # ── Rename / layer management
    "PCG_COPLayerEdit": {
        "order": ["op", "spec"],
        "inputs": {
            "op": {"label": "Operation",
                   "menu": {"rename": "Rename", "copy": "Copy", "delete": "Delete",
                            "keep": "Keep Only"}},
            "spec": {"label": "Layers",
                     "help": "Rename / Copy: old=new old2=new2; Delete / Keep: layer names"},
        },
    },

    # ── Layer to Points / Point Generate: Mode selects one of two parameter sets
    "PCG_COPLayerToPoints": {
        "order": ["mode", "mask_layer", "threshold", "stride", "jitter",
                  "count", "density_layer", "ignore_minus_one", "rand_seed",
                  "set_positions", "plane", "world_size", "height_layer", "height_scale",
                  "attribs", "layer_attrib", "index_attrib"],
        "inputs": {
            "mode": {"label": "Method",
                     "menu": {"pixels": "One Point per Pixel",
                              "scatter": "Scatter by Density",
                              "nonzero": "Non-Zero Pixels",
                              "count_per_pixel": "Count per Pixel",
                              "unique_values": "Unique Values",
                              "count_first": "Count from First Pixel",
                              "count_last": "Count from Last Pixel"}},
            # geoimg.layer_to_points: pixels reads mask / threshold / stride / jitter,
            # scatter reads count / density_layer; Houdini's five modes read mask_layer (as the source layer)
            "mask_layer": {"label": "Mask Layer", "hide": "{ mode == scatter }",
                           "help": "pixels: mask (empty = all); Houdini modes: source layer (empty = C)"},
            "threshold": {"label": "Threshold", "hide": "{ mode != pixels }",
                          "disable": '{ mask_layer == "" }'},
            "stride": {"label": "Stride", "hide": "{ mode != pixels }"},
            "jitter": {"label": "Jitter",
                       "hide": "{ mode == scatter } { mode == count_first } { mode == count_last }"},
            "count": {"label": "Point Count", "hide": "{ mode != scatter }"},
            "density_layer": {"label": "Density Layer", "hide": "{ mode != scatter }",
                              "help": "Empty = uniform"},
            "ignore_minus_one": {"label": "Ignore Minus One", "hide": "{ mode != unique_values }"},
            # scatter always reads seed; the other modes with positions do not read it when jitter = 0
            "rand_seed": {"label": "Seed",
                          "disable": "{ mode != scatter jitter == 0 } { mode == count_first } "
                                     "{ mode == count_last }"},
            "set_positions": {"label": "Set Positions", "sep": True,
                              "disable": "{ mode == count_first } { mode == count_last }",
                              "help": "Off: P is all 0"},
            "plane": {"label": "Plane", "menu": _PLANE_MENU,
                      "disable": "{ set_positions == 0 } { mode == count_first } "
                                 "{ mode == count_last }"},
            "world_size": {"label": "World Size",
                           "disable": "{ set_positions == 0 } { mode == count_first } "
                                      "{ mode == count_last }"},
            "height_layer": {"label": "Height Layer", "help": "Feeds the axis out of the plane",
                             "disable": "{ set_positions == 0 } { mode == count_first } "
                                        "{ mode == count_last }"},
            "height_scale": {"label": "Height Scale",
                             "disable": '{ height_layer == "" } { set_positions == 0 } '
                                        "{ mode == count_first } { mode == count_last }"},
            "attribs": {"label": "Layers to Attributes", "sep": True,
                        "help": "Space-separated; C → Cd"},
            "layer_attrib": {"label": "Layer Attrib", "help": "Value of the source pixel (integer); empty = not written"},
            "index_attrib": {"label": "Index Attrib", "help": "Source pixel offset x + y·xres; empty = not written"},
        },
    },

    # ── Point Generate (pcg100 c8): geolayer.point_generate. parameters reads Number /
    #    Points per Second / Time Step / Seed; the two attribute modes read Count Attribute;
    #    Copy Attributes is only read by point_attribute
    "PCG_COPPointGenerate": {
        "order": ["method", "number_of_points", "points_per_second", "time_step",
                  "rand_seed", "count_attrib", "copy_attribs", "append_points"],
        "inputs": {
            "method": {"label": "Method",
                       "menu": {"parameters": "Parameters",
                                "point_attribute": "Point Attribute",
                                "detail_attribute": "Detail Attribute"}},
            "number_of_points": {"label": "Number of Points", "hide": "{ method != parameters }"},
            "points_per_second": {"label": "Points per Second",
                                  "hide": "{ method != parameters }"},
            "time_step": {"label": "Time Step", "hide": "{ method != parameters }",
                          "disable": "{ points_per_second == 0 }",
                          "help": "Houdini uses the simulation time step; we have no simulation, so it is given here"},
            "rand_seed": {"label": "Seed", "hide": "{ method != parameters }",
                          "help": "Decides whether the point for the fractional part is kept"},
            "count_attrib": {"label": "Count Attribute", "hide": "{ method == parameters }"},
            "copy_attribs": {"label": "Copy Attributes", "hide": "{ method != point_attribute }"},
            "append_points": {"label": "Append Points", "sep": True},
        },
    },

    # ── Layer from Attribute (pcg100 c8): geolayer.layer_from_attrib. With Resize Layer on,
    #    size_ref / resolution are not read; with index wired Data Ordering is not read (index is an input the panel cannot see,
    #    so only a help text)
    "PCG_COPLayerFromAttrib": {
        "order": ["attrib_class", "attrib", "data_ordering", "index_layer", "resize_layer",
                  "resize_shape", "resolution_x", "resolution_y", "out_layer"],
        "inputs": {
            "attrib_class": {"label": "Class",
                             "menu": {"point": "Point", "prim": "Primitive",
                                      "vertex": "Vertex", "detail": "Detail"}},
            "attrib": {"label": "Attribute"},
            "data_ordering": {"label": "Data Ordering",
                              "menu": {"bottom_left": "Bottom Left", "top_left": "Top Left"},
                              "help": "Not read when the index input is wired"},
            "index_layer": {"label": "Index Layer", "help": "Which layer to read from the index input (empty = C)"},
            "resize_layer": {"label": "Resize Layer", "sep": True},
            "resize_shape": {"label": "Resize Shape", "disable": "{ resize_layer == 0 }",
                             "menu": {"pow2_square": "Power of 2 Square", "square": "Square",
                                      "single_row": "Single Row",
                                      "single_column": "Single Column"}},
            "resolution_x": {"disable": "{ resize_layer == 1 }",
                             "help": "Used when size_ref is not wired"},
            "resolution_y": {"disable": "{ resize_layer == 1 }"},
            "out_layer": {"label": "Output Layer", "sep": True},
        },
    },

    # ── Geometry to Layer (pcg100 c8): geolayer.geo_to_layer. Default Value is only read with Optional
    #    on
    "PCG_COPGeoToLayer": {
        "order": ["slice", "slice_offset", "outputs", "out_type", "optional", "default_value"],
        "inputs": {
            "slice": {"label": "Slice",
                      "menu": {"xy": "XY Plane", "yz": "YZ Plane", "zx": "ZX Plane"}},
            "slice_offset": {"label": "Slice Offset", "help": "World coordinate of the plane along its normal (extension)"},
            "outputs": {"label": "Primitive Names", "sep": True,
                        "help": "Space-separated: names / indices / vel.* (combined into multiple channels); empty = all volumes"},
            "out_type": {"label": "Type",
                         "menu": {"auto": "Auto", "id": "ID", "mono": "Mono", "uv": "UV",
                                  "rgb": "RGB", "rgba": "RGBA"}},
            "optional": {"label": "Optional"},
            "default_value": {"label": "Default Value", "disable": "{ optional == 0 }"},
        },
    },

    # ── Sequence (pcg100 c8): geolayer.sequence_clips; Clips is a text version of the multiparm table
    "PCG_COPSequenceClips": {
        "order": ["clips", "output_start_frame"],
        "inputs": {
            "clips": {"label": "Clips",
                      "help": "Each clip 'start_frame frame_count', semicolon-separated; clip k takes input k, extra clips take the last one; "
                              "empty = all of the first input"},
            "output_start_frame": {"label": "Output Start Frame"},
        },
    },

    # ── Time Pack (pcg100 c8): geolayer.time_pack. Frame is only read by relative, FPS only by seconds
    "PCG_COPTimePack": {
        "order": ["mode", "frame", "units", "fps", "range_start", "range_end", "step",
                  "add_time_as", "layers"],
        "inputs": {
            "mode": {"label": "Mode", "menu": {"relative": "Relative", "absolute": "Absolute"}},
            "frame": {"label": "Frame", "hide": "{ mode != relative }",
                      "help": "Current frame (Houdini uses the scene's current frame)"},
            "units": {"label": "Units", "menu": {"frames": "Frames", "seconds": "Seconds"}},
            "fps": {"label": "FPS", "hide": "{ units != seconds }"},
            "range_start": {"row": {"kind": "vector", "members": ["range_start", "range_end"],
                                    "label": "Range"}},
            "step": {"label": "Step"},
            "add_time_as": {"label": "Add Time As", "sep": True,
                            "menu": {"prefix": "Prefix", "suffix": "Suffix"}},
            "layers": {"label": "Layers", "help": "Empty = all layers"},
        },
    },

    # ── Integrate Volume (pcg100 c8): geolayer.integrate_volume. The Density section is only read by integral /
    #    transmittance; Cutoff likewise; Seed is only read when there is jitter
    "PCG_COPIntegrateVolume": {
        "order": ["density", "operation", "density_scale", "density_min", "density_max",
                  "ramp_mode", "sample_jitter", "stratification_jitter", "rand_seed",
                  "step_size", "max_steps", "transmittance_cutoff", "origin_layer",
                  "direction_layer", "mindepth_layer", "maxdepth_layer", "resolution_x",
                  "out_layer"],
        "inputs": {
            "density": {"label": "Volume", "help": "Volume name / index / vel.* (multiple channels); empty = the first one"},
            "operation": {"label": "Operation",
                          "menu": {"integral": "Integral", "transmittance": "Transmittance",
                                   "minimum": "Minimum", "maximum": "Maximum"}},
            "density_scale": {"section": "Density", "label": "Density Scale",
                              "disable": "{ operation == minimum } { operation == maximum }"},
            "density_min": {"section": "Density", "label": "Min",
                            "disable": "{ operation == minimum } { operation == maximum }"},
            "density_max": {"section": "Density", "label": "Max",
                            "disable": "{ operation == minimum } { operation == maximum }"},
            "ramp_mode": {"section": "Density", "label": "Ramp Mode",
                          "menu": {"none": "No Ramp", "clamped": "Clamped Ramp",
                                   "periodic": "Periodic Ramp"},
                          "disable": "{ operation == minimum } { operation == maximum }",
                          "help": "Only clamp / modulo are implemented, no Density Ramp curve"},
            "sample_jitter": {"section": "Quality", "label": "Sample Jitter Scale"},
            "stratification_jitter": {"section": "Quality",
                                      "label": "Stratification Jitter Scale"},
            "rand_seed": {"section": "Quality", "label": "Seed",
                          "disable": "{ sample_jitter == 0 stratification_jitter == 0 }"},
            "step_size": {"section": "Quality", "label": "Integration Step Size"},
            "max_steps": {"section": "Quality", "label": "Max Step Count"},
            "transmittance_cutoff": {"section": "Quality", "label": "Transmittance Cutoff",
                                     "disable": "{ operation == minimum } { operation == maximum }",
                                     "help": "−1 = no early termination"},
            "origin_layer": {"section": "Rays", "label": "View Origin Layer",
                             "help": "A layer in the layers input; empty = default orthographic"},
            "direction_layer": {"section": "Rays", "label": "View Direction Layer"},
            "mindepth_layer": {"section": "Rays", "label": "Min Depth Layer"},
            "maxdepth_layer": {"section": "Rays", "label": "Max Depth Layer"},
            "resolution_x": {"help": "Used when layers is not wired"},
            "out_layer": {"label": "Output Layer", "sep": True},
        },
    },

    # ── Configure Stamps (pcg100 c8): geolayer.configure_stamps. Each Variance / Min / Max is only read in
    #    its corresponding mode; Mask only when the layer name is non-empty; Select Layer only in layer_select
    "PCG_COPConfigureStamps": {
        "order": ["rand_seed", "plane", "world_size",
                  "jitter", "jitter_scale", "jitter_layer", "jitter_mask",
                  "scale", "scale_mode", "scale_variance", "scale_min", "scale_max",
                  "scale_layer", "scale_mask",
                  "stretch", "stretch_mode", "stretch_variance", "stretch_min", "stretch_max",
                  "stretch_layer", "stretch_mask",
                  "angle", "angle_mode", "angle_variance", "angle_min", "angle_max", "round_to",
                  "angle_layer", "angle_mask", "direction_layer", "direction_mask",
                  "use_sort_layer", "sort_layer", "color", "color_mode", "color_seed",
                  "hue_variance", "saturation_variance", "value_variance", "color_layer",
                  "color_mask", "alpha", "alpha_mode", "alpha_variance", "alpha_layer",
                  "alpha_mask", "stamp_count", "select_mode", "select_seed", "select_layer"],
        "inputs": {
            "rand_seed": {"label": "Seed"},
            "plane": {"label": "Plane", "menu": _PLANE_MENU, "help": "Point → layer uv (for the sampled layer input)"},
            "world_size": {"label": "World Size"},
            "jitter": {"section": "Jitter", "label": "Jitter"},
            "jitter_scale": {"section": "Jitter", "label": "Jitter Scale"},
            "jitter_layer": {"section": "Jitter", "label": "Jitter Layer"},
            "jitter_mask": {"section": "Jitter", "label": "Jitter Layer Mask",
                            "disable": '{ jitter_layer == "" }'},
            "scale": {"section": "Scale", "label": "Scale"},
            "scale_mode": {"section": "Scale", "label": "Scale Mode",
                           "menu": {"uniform": "Uniform", "percent_variance": "Percent Variance",
                                    "min_max": "Min/Max"}},
            "scale_variance": {"section": "Scale", "label": "Scale Variance",
                               "hide": "{ scale_mode != percent_variance }"},
            "scale_min": {"section": "Scale", "label": "Min Value",
                          "hide": "{ scale_mode != min_max }"},
            "scale_max": {"section": "Scale", "label": "Max Value",
                          "hide": "{ scale_mode != min_max }"},
            "scale_layer": {"section": "Scale", "label": "Scale Layer"},
            "scale_mask": {"section": "Scale", "label": "Scale Layer Mask",
                           "disable": '{ scale_layer == "" }'},
            "stretch": {"section": "Stretch", "label": "Stretch"},
            "stretch_mode": {"section": "Stretch", "label": "Stretch Mode", "menu": {"uniform": "Uniform", "variance": "Variance", "min_max": "Min/Max"}},
            "stretch_variance": {"section": "Stretch", "label": "Stretch Variance",
                                 "hide": "{ stretch_mode != variance }"},
            "stretch_min": {"section": "Stretch", "label": "Min Value",
                            "hide": "{ stretch_mode != min_max }"},
            "stretch_max": {"section": "Stretch", "label": "Max Value",
                            "hide": "{ stretch_mode != min_max }"},
            "stretch_layer": {"section": "Stretch", "label": "Stretch Layer"},
            "stretch_mask": {"section": "Stretch", "label": "Stretch Layer Mask",
                             "disable": '{ stretch_layer == "" }'},
            "angle": {"section": "Angle", "label": "Angle"},
            "angle_mode": {"section": "Angle", "label": "Angle Mode", "menu": {"uniform": "Uniform", "variance": "Variance", "min_max": "Min/Max"}},
            "angle_variance": {"section": "Angle", "label": "Angle Variance",
                               "hide": "{ angle_mode != variance }"},
            "angle_min": {"section": "Angle", "label": "Min Value",
                          "hide": "{ angle_mode != min_max }"},
            "angle_max": {"section": "Angle", "label": "Max Value",
                          "hide": "{ angle_mode != min_max }"},
            "round_to": {"section": "Angle", "label": "Round To", "help": "0 = no rounding"},
            "angle_layer": {"section": "Angle", "label": "Angle Layer", "help": "0 → 0°,1 → 360°"},
            "angle_mask": {"section": "Angle", "label": "Angle Layer Mask",
                           "disable": '{ angle_layer == "" }'},
            "direction_layer": {"section": "Angle", "label": "Direction Layer"},
            "direction_mask": {"section": "Angle", "label": "Direction Layer Mask",
                               "disable": '{ direction_layer == "" }'},
            "use_sort_layer": {"section": "Color and Blending", "label": "Use Sort Layer"},
            "sort_layer": {"section": "Color and Blending", "label": "Sort Layer",
                           "disable": "{ use_sort_layer == 0 }"},
            "color": {"section": "Color and Blending", "label": "Color", "kind": "colorstr"},
            "color_mode": {"section": "Color and Blending", "label": "Stamp Color",
                           "menu": {"uniform": "Uniform", "variance": "Variance"}},
            "color_seed": {"section": "Color and Blending", "label": "Color Seed",
                           "disable": "{ color_mode == uniform alpha_mode == uniform }"},
            "hue_variance": {"section": "Color and Blending", "label": "Hue",
                             "hide": "{ color_mode != variance }"},
            "saturation_variance": {"section": "Color and Blending", "label": "Saturation",
                                    "hide": "{ color_mode != variance }"},
            "value_variance": {"section": "Color and Blending", "label": "Value",
                               "hide": "{ color_mode != variance }"},
            "color_layer": {"section": "Color and Blending", "label": "Color Layer"},
            "color_mask": {"section": "Color and Blending", "label": "Color Layer Mask",
                           "disable": '{ color_layer == "" }'},
            "alpha": {"section": "Alpha", "label": "Alpha"},
            "alpha_mode": {"section": "Alpha", "label": "Stamp Alpha",
                           "menu": {"uniform": "Uniform", "variance": "Variance"}},
            "alpha_variance": {"section": "Alpha", "label": "Alpha Variance",
                               "hide": "{ alpha_mode != variance }"},
            "alpha_layer": {"section": "Alpha", "label": "Alpha Layer"},
            "alpha_mask": {"section": "Alpha", "label": "Alpha Layer Mask",
                           "disable": '{ alpha_layer == "" }'},
            "stamp_count": {"section": "Stamp Selection", "label": "Stamp Count"},
            "select_mode": {"section": "Stamp Selection", "label": "Mode",
                            "menu": {"cycle": "Cycle", "random": "Random",
                                     "layer_select": "Layer Select"}},
            "select_seed": {"section": "Stamp Selection", "label": "Select Seed",
                            "hide": "{ select_mode != random }"},
            "select_layer": {"section": "Stamp Selection", "label": "Select Layer",
                             "hide": "{ select_mode != layer_select }"},
        },
    },

    # ── Lens Distort
    "PCG_COPLensDistort": {
        "order": ["layers", "mode", "k1", "k2", "center", "border"],
        "inputs": {
            "layers": _LAYERS,
            "mode": {"label": "Mode", "sep": True,
                     "menu": {"distort": "Distort", "undistort": "Undistort"}},
            "k1": {"label": "Radial K1", "help": "< 0 barrel, > 0 pincushion"},
            "k2": {"label": "Radial K2"},
            "center": {"label": "Center", "help": "uv"},
            "border": {"label": "Border", "sep": True,
                       "menu": {"black": "Constant (Black)", "clamp": "Clamp",
                                "wrap": "Wrap"}},
        },
    },

    # ── Levels:Input Range → Gamma → Output Range
    "PCG_COPLevels": {
        "order": ["layers", "in_black", "in_white", "clamp_input", "gamma",
                  "out_black", "out_white", "clamp_output"],
        "inputs": {
            "layers": _LAYERS,
            "in_black": {"row": {"kind": "vector", "members": ["in_black", "in_white"],
                                 "label": "Input Range"}, "sep": True},
            "clamp_input": {"label": "Clamp Input",
                            "help": "Turn off when processing SDFs / normals / HDR"},
            "gamma": {"label": "Gamma", "help": "> 1 brightens (exponent is 1/Gamma)"},
            "out_black": {"row": {"kind": "vector", "members": ["out_black", "out_white"],
                                  "label": "Output Range"}, "sep": True},
            "clamp_output": {"label": "Clamp Output",
                             "help": "Clamps to [Output Black, Output White]"},
        },
    },

    # ── Logic
    "PCG_COPLogic": {
        "order": ["a", "op", "b", "tolerance", "out_layer"],
        "inputs": {
            "a": {"label": "Input A", "help": "Layer name"},
            "op": {"label": "Operation",
                   "menu": {"greater": "A > B", "greater_equal": "A ≥ B",
                            "less": "A < B", "less_equal": "A ≤ B",
                            "equal": "A = B", "not_equal": "A ≠ B",
                            "and": "A AND B", "or": "A OR B", "xor": "A XOR B",
                            "not": "NOT A"}},
            # pixel.logic: not ignores B's value, but B is still parsed (a typo still raises an error) → greyed out, not hidden
            "b": {"label": "Input B", "help": "Layer name or constant",
                  "disable": "{ op == not }"},
            # Only the four ≥ ≤ = ≠ read tolerance
            "tolerance": {"label": "Tolerance",
                          "hide": "{ op == greater } { op == less } { op == and } "
                                  "{ op == or } { op == xor } { op == not }"},
            "out_layer": _OUT,
        },
    },

    # ── Mono to HeightField / Mono to RGB (Houdini semantics). colorkey.mono_to_rgb:
    #    in_min / in_max are not read while Compute Range is on; ramp / ramp_mode are not read when a Ramp
    #    Layer is given
    "PCG_COPMonoToHeightField": {
        "order": ["layer", "height_scale", "height_offset", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer", "help": "Multi-channel layers use channel 0"},
            "height_scale": {"label": "Height Scale"},
            "height_offset": {"label": "Height Offset"},
            "out_layer": {"label": "Output Layer", "sep": True},
        },
    },

    "PCG_COPMonoToRGB": {
        "order": ["layer", "compute_range", "in_min", "in_max", "out_min", "out_max",
                  "scale_by_value", "outside", "ramp", "ramp_mode", "ramp_layer",
                  "out_layer"],
        "inputs": {
            "layer": {"label": "Layer", "help": "Multi-channel layers use channel 0"},
            "compute_range": {"label": "Compute Range"},
            "in_min": {"label": "Input Min", "disable": "{ compute_range == 1 }"},
            "in_max": {"label": "Input Max", "disable": "{ compute_range == 1 }"},
            "out_min": {"label": "Output Min"},
            "out_max": {"label": "Output Max"},
            "scale_by_value": {"label": "Scale by Value"},
            "outside": {"label": "Outside Range",
                        "menu": {"clamp": "Clamp at End", "repeat": "Repeat"}},
            "ramp": {"label": "Ramp", "disable": "{ ramp_layer != \"\" }"},
            "ramp_layer": {"label": "Ramp Layer", "sep": True,
                           "help": "When given, colors are taken horizontally from the middle row of this layer instead of the Ramp above"},
            "out_layer": {"label": "Output Layer", "help": "Empty = overwrite the input layer"},
        },
    },

    # ── Luminance
    "PCG_COPLuminance": {
        "order": ["layer", "operation", "weights", "normalize_weights", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer"},
            "operation": {"label": "Operation",
                          "menu": {"sgi": "SGI Luminance", "ntsc": "NTSC Luminance",
                                   "hdtv": "HDTV Luminance", "average": "Average",
                                   "max": "Maximum Channel", "min": "Minimum Channel",
                                   "length": "Magnitude / Length", "hue": "Hue",
                                   "saturation": "Saturation", "value": "Value",
                                   "red": "Red", "green": "Green", "blue": "Blue",
                                   "alpha": "Alpha", "custom": "Custom"}},
            # pixel.mono only reads these two in the custom mode
            "weights": {"label": "Weights", "hide": "{ operation != custom }"},
            "normalize_weights": {"label": "Normalize Weights",
                                  "hide": "{ operation != custom }"},
            "out_layer": _OUT,
        },
    },

    # ── Layer Merge (Houdini's one: N inputs composited per pixel)
    "PCG_COPLayerCombine": {
        "order": ["layer", "operation", "out_layer"],
        "inputs": {
            "layer": {"label": "Layer", "help": "This layer is taken from every input"},
            "operation": {"label": "Operation",
                          "menu": {"add": "Add", "average": "Average",
                                   "multiply": "Multiply", "min": "Min", "max": "Max",
                                   "over": "Over"}},
            "out_layer": {"label": "Output Layer", "sep": True, "help": "Empty = overwrite Layer"},
        },
    },

    # ── HeightField Mask by Feature: one section per criterion, toggle on the section header (Mask by ...)
    "PCG_COPMaskByFeature": {
        "order": ["layer", "strength", "world_size", "tile", "smooth_radius",
                  "blend_mode",
                  "use_slope", "slope_min", "slope_max", "slope_falloff",
                  "use_aspect", "aspect_dir", "aspect_spread", "aspect_falloff",
                  "use_height", "height_min", "height_max", "height_falloff",
                  "curvature", "curv_threshold", "curv_falloff", "curv_blur",
                  "curv_reference",
                  "use_occlusion", "occ_min", "occ_max", "occ_falloff",
                  "occ_height_scale", "occ_radius", "occ_step_scale", "occ_samples",
                  "invert", "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Height Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "tile": {"label": "Tileable (Wrap Edges)"},
            # terrain.mask_by_feature: with use_x off the whole section is not read → section header toggle
            "use_slope": {"label": "Mask by Slope", "gate": True},
            "slope_min": {"row": {"kind": "vector", "members": ["slope_min", "slope_max"],
                                  "label": "Slope Range"}},
            "slope_falloff": {"label": "Slope Falloff"},
            "use_aspect": {"label": "Mask by Direction", "section": "Direction",
                           "gate": True},
            "aspect_dir": {"label": "Goal Angle", "section": "Direction",
                           "help": "Downhill facing: 0° = +u, 90° = +v"},
            "aspect_spread": {"label": "Angle Spread", "section": "Direction"},
            "aspect_falloff": {"label": "Direction Falloff", "section": "Direction"},
            "use_height": {"label": "Mask by Height", "gate": True},
            "height_min": {"row": {"kind": "vector",
                                   "members": ["height_min", "height_max"],
                                   "label": "Height Range"},
                           "help": "Height value (not multiplied by Height Scale)"},
            "height_falloff": {"label": "Height Falloff"},
            "curvature": {"label": "Mask by Curvature",
                          "menu": {"off": "Off", "ridges": "Ridges",
                                   "gullies": "Gullies"}},
            # With curvature == off the whole section is not read
            "curv_threshold": {"label": "Threshold", "hide": "{ curvature == off }"},
            "curv_falloff": {"label": "Falloff", "hide": "{ curvature == off }"},
            "curv_blur": {"label": "Blur Radius", "hide": "{ curvature == off }",
                          "help": "Pixels; blurred first, then curvature is computed"},
            "curv_reference": {"label": "Reference Curvature",
                               "hide": "{ curvature == off }",
                               "help": "> 0 normalizes by it (required for tiled generation); 0 = use this image's 90th percentile"},
            # terrain.mask_by_feature: with use_occlusion off the whole section is not read → section header toggle
            "use_occlusion": {"label": "Mask by Occlusion", "gate": True},
            "occ_min": {"row": {"kind": "vector", "members": ["occ_min", "occ_max"],
                                "label": "Occlusion Range"},
                        "help": "Occlusion 0 = open, 1 = fully blocked (= 1 − Height to AO)"},
            "occ_falloff": {"label": "Occlusion Falloff"},
            "occ_height_scale": {"label": "Height Scale", "help": "Multiplies the height before computing occlusion"},
            "occ_radius": {"label": "View Radius", "help": "World units"},
            "occ_step_scale": {"label": "Step Scale", "help": "Pixels per step (at most 64 steps)"},
            "occ_samples": {"label": "Sample Count", "help": "Number of directions"},
            "smooth_radius": {"label": "Smooth Radius", "sep": True,
                              "help": "World units; the height is blurred before measuring any feature"},
            "blend_mode": {"label": "Blend Mode",
                           "menu": {"multiply": "Multiply", "add": "Add",
                                    "average": "Average", "minimum": "Minimum",
                                    "maximum": "Maximum"},
                           "help": "How to combine when several criteria are enabled"},
            "invert": {"label": "Invert Mask", "sep": True},
            "out_layer": {"label": "Output Layer", "sep": True},
            "keep_layers": _KEEP,
        },
    },

    # ── Mask Combine: pixel.mask_combine's layer_stack mode reads stack / starting_value
    #    and not layers; the other modes the other way round. Post-processing is done in every mode
    "PCG_COPMaskCombine": {
        "order": ["op", "layers", "starting_value", "stack", "fold", "complement",
                  "use_clamp_min", "clamp_min", "use_clamp_max", "clamp_max",
                  "clamp", "out_layer"],
        "inputs": {
            "op": {"label": "Operation",
                   "menu": {"union": "Union (Max)", "intersect": "Intersect (Min)",
                            "add": "Add", "multiply": "Multiply",
                            "subtract": "Subtract", "difference": "Difference",
                            "screen": "Screen", "average": "Average",
                            "layer_stack": "Per-Layer Blend Modes (Houdini)"}},
            "layers": {"label": "Mask Layers", "hide": "{ op == layer_stack }",
                       "help": "Space-separated, only channel 0 is used"},
            "starting_value": {"label": "Starting Value", "hide": "{ op != layer_stack }"},
            "stack": {"label": "Mask Layers", "hide": "{ op != layer_stack }",
                      "help": "One layer per line, stacked top to bottom: layer[.channel] mode amount. Modes: blend add subtract "
                              "multiply divide screen hypot difference exclusion maximum "
                              "minimum overlay softlight hardlight dodge burn; leading # = layer disabled"},
            "fold": {"label": "Fold", "section": "Post Processing",
                     "help": "Takes the absolute value"},
            "complement": {"label": "Complement", "section": "Post Processing",
                           "help": "x → 1 − x"},
            "use_clamp_min": {"section": "Post Processing"},
            "clamp_min": {"label": "Clamp Minimum", "section": "Post Processing"},
            "use_clamp_max": {"section": "Post Processing"},
            "clamp_max": {"label": "Clamp Maximum", "section": "Post Processing"},
            "clamp": {"label": "Clamp 0-1", "section": "Post Processing"},
            "out_layer": _OUT,
        },
    },

    # ── Median
    "PCG_COPMedian": {
        "order": ["layers", "radius", "shape", "border"],
        "inputs": {
            "layers": _LAYERS,
            "radius": {"label": "Radius", "sep": True, "help": "Pixels, at most 8"},
            "shape": {"label": "Shape", "menu": _SHAPE_MENU},
            "border": {"label": "Border", "menu": _BORDER_MENU},
        },
    },

    # ── Mirror: fx.mirror's number_and_offset mode reads planes / angle / offset / reverse,
    #    custom_planes reads plane_list, the other five modes read position
    "PCG_COPMirror": {
        "order": ["layers", "mode", "position", "planes", "angle", "offset",
                  "reverse", "plane_list"],
        "inputs": {
            "layers": _LAYERS,
            "mode": {"label": "Mode", "sep": True,
                     "menu": {"left_to_right": "Left to Right",
                              "right_to_left": "Right to Left",
                              "bottom_to_top": "Bottom to Top",
                              "top_to_bottom": "Top to Bottom",
                              "quad": "Quad (Four-Way)",
                              "number_and_offset": "Number and Offset",
                              "custom_planes": "Custom Mirror Planes"}},
            "position": {"label": "Mirror Position", "help": "Mirror plane position (uv)",
                         "hide": "{ mode == number_and_offset } { mode == custom_planes }"},
            "planes": {"label": "Number of Planes", "hide": "{ mode != number_and_offset }"},
            "angle": {"label": "Angle", "hide": "{ mode != number_and_offset }",
                      "help": "Angle between adjacent mirrors (degrees); mirror k is at k × Angle. 0 = vertical center line, left half mirrored onto the right"},
            "offset": {"label": "Offset", "hide": "{ mode != number_and_offset }",
                       "help": "Image space (−1...1 across the long side); positive = mirror moves right"},
            "reverse": {"label": "Reverse Mirror Plane Direction",
                        "hide": "{ mode != number_and_offset }"},
            "plane_list": {"label": "Mirrors", "hide": "{ mode != custom_planes }",
                           "help": "One mirror per line, applied in order: angle offset [reverse 0/1]"},
        },
    },

    # ── Morph(Erode / Dilate / Open / Close / Gradient)
    "PCG_COPMorph": {
        "order": ["layers", "op", "radius", "shape", "border"],
        "inputs": {
            "layers": _LAYERS,
            "op": {"label": "Operation", "sep": True,
                   "menu": {"erode": "Erode", "dilate": "Dilate", "open": "Open",
                            "close": "Close", "gradient": "Gradient (Outline)"}},
            "radius": {"label": "Radius", "help": "Pixels; large radii use an SDF"},
            "shape": {"label": "Shape", "menu": _SHAPE_MENU},
            "border": {"label": "Border", "menu": _BORDER_MENU},
        },
    },

    # ── Bubble / Crystal / Phasor / Curl / Cloud Noise collection: Noise Type decides which section takes effect
    "PCG_COPNoiseExtra": {
        "order": ["kind", "amplitude", "center",
                  "frequency", "offset", "octaves", "rand_seed",
                  "radius", "density", "sharpness", "metric", "jitter",
                  "phasor_type", "periodic_function",
                  "stripe_freq", "angle", "spread", "kernels", "direction_layer",
                  "coverage", "softness", "billow", *_PP,
                  "out_layer", "resolution_x", "resolution_y", "compute"],
        "inputs": {
            "kind": {"label": "Noise Type",
                     "menu": {"bubble": "Bubble", "crystal": "Crystal",
                              "phasor": "Phasor", "curl": "Curl",
                              "curl_3d": "Curl 3D", "cloud": "Cloud 3D"}},
            "frequency": {"label": "Frequency", "help": "Reciprocal of Element Size"},
            "offset": {"label": "Offset", "help": "The third number is the z of the 3D slice"},
            # noisex.noise_extra: only curl / curl_3d / cloud read octaves
            "octaves": {"label": "Octaves",
                        "hide": "{ kind == bubble } { kind == crystal } { kind == phasor }"},
            "rand_seed": {"label": "Seed"},
            "radius": {"label": "Radius", "hide": "{ kind != bubble }"},
            "density": {"label": "Density", "hide": "{ kind != bubble }"},
            "sharpness": {"label": "Sharpness", "hide": "{ kind != crystal }"},
            # pcg100: only noisex.crystal reads metric / jitter; only phasor_main reads the last two
            "metric": {"label": "Primary Metric", "menu": _METRIC_MENU,
                       "hide": "{ kind != crystal }"},
            "jitter": {"label": "Jitter", "hide": "{ kind != crystal }"},
            "phasor_type": {"label": "Type", "hide": "{ kind != phasor }",
                            "menu": {"phasor_wave": "Phasor Wave",
                                     "gabor_noise": "Gabor Noise",
                                     "intensity_field": "Intensity Field"}},
            "periodic_function": {"label": "Periodic Function",
                                  "hide": "{ kind != phasor } { phasor_type != phasor_wave }",
                                  "menu": {"sine": "Sine", "rectangle": "Rectangle",
                                           "saw": "Saw"}},
            "amplitude": {"label": "Amplitude", "section": "Range",
                          "help": "Only applies to the main layer (helper layers _id / _edge ... are untouched)"},
            "center": {"label": "Center", "section": "Range"},
            **_cpost.panel(),
            "stripe_freq": {"label": "Stripe Frequency", "hide": "{ kind != phasor }"},
            "angle": {"label": "Angle", "hide": "{ kind != phasor }"},
            "spread": {"label": "Angle Spread", "hide": "{ kind != phasor }"},
            "kernels": {"label": "Kernels per Cell", "hide": "{ kind != phasor }"},
            "direction_layer": {"label": "Direction Layer", "hide": "{ kind != phasor }",
                                "help": "2-channel vector field; the stripes follow it"},
            "coverage": {"label": "Coverage", "hide": "{ kind != cloud }"},
            "softness": {"label": "Softness", "hide": "{ kind != cloud }"},
            "billow": {"label": "Billow", "hide": "{ kind != cloud }"},
            "out_layer": _OUT,
            "resolution_x": {"help": "Used when no cop is wired; with a cop wired, follows its resolution"},
            "compute": {"label": "Compute", "menu": _COMPUTE_MENU},
        },
    },

    # ── Worley Noise (3D): Pattern → Post Processing → output
    "PCG_COPWorleyNoise": {
        "order": ["element_size", "element_scale", "jitter", "jitter_scale",
                  "lattice", "metric", "round_border", "offset", "tile", "tile_size",
                  "pos_layer", "rand_seed", *_PP, "prefix",
                  "resolution_x", "resolution_y"],
        "inputs": {
            **_CELL_PATTERN,
            "lattice": {"label": "Lattice Type",
                        "menu": {"rectangular": "Rectangular",
                                 "hexagonal": "Simplical (Hexagonal)"}},
            # cell_fields: only euclidean goes through smooth-min
            "round_border": {"label": "Round Border", "hide": "{ metric != euclidean }"},
            **_cpost.panel(),
            "prefix": {"label": "Layer Prefix", "sep": True,
                       "help": "Layer names = prefix + dist1 / dist2 / border / center / id"},
            "resolution_x": {"help": "Used when no cop is wired; with a cop wired, follows its resolution"},
        },
    },

    # ── Cellular Noise(3D):Range → Pattern → Shape → Post Processing
    "PCG_COPCellularNoise": {
        "order": ["amplitude", "shift",
                  "element_size", "element_scale", "jitter", "jitter_scale",
                  "lattice", "metric", "smooth_edge", "offset", "tile", "tile_size",
                  "shape_mode", "gap", "bevel",
                  "pos_layer", "rand_seed", *_PP, "prefix",
                  "resolution_x", "resolution_y"],
        "inputs": {
            "amplitude": {"label": "Amplitude", "section": "Range"},
            "shift": {"label": "Shift", "section": "Range"},
            **_CELL_PATTERN,
            "lattice": {"label": "Lattice Type",
                        "menu": {"rectangular": "Grid", "hexagonal": "Hexagonal"}},
            "smooth_edge": {"label": "Smooth Edge", "hide": "{ metric != euclidean }"},
            "shape_mode": {"label": "Mode", "section": "Shape",
                           "menu": {"absolute": "Absolute", "relative": "Relative"}},
            "gap": {"label": "Gap"},
            "bevel": {"label": "Bevel", "help": "0 = hard-edged flat top; larger = pointier top"},
            **_cpost.panel(),
            "prefix": {"label": "Layer Prefix", "sep": True,
                       "help": "Layer names = prefix + noise / border / center / id"},
            "resolution_x": {"help": "Used when no cop is wired; with a cop wired, follows its resolution"},
        },
    },

    # ── Fractal Sample: source → Fractal (octaves / combine method) → Border / Filter → random → Post
    "PCG_COPFractalSample": {
        "order": ["source_layer", "maintain_tileable", "max_octaves", "lacunarity",
                  "roughness", "bias", "offset_with_bias", "blend_mode",
                  "border", "filter", "rand_seed", "jitter", "angle_mode", "angle",
                  "random_flip_x", "random_flip_y", *_PP, "out_layer"],
        "inputs": {
            "source_layer": {"label": "Source Layer"},
            "maintain_tileable": {"label": "Maintain Tileable",
                                  "help": "Lacunarity is rounded, angles are multiples of 90°; the source image itself must tile"},
            "max_octaves": {"label": "Max Octaves", "section": "Fractal"},
            "lacunarity": {"label": "Lacunarity"},
            "roughness": {"label": "Roughness"},
            # fractalsample: over does not subtract Bias and does not add it back
            "bias": {"label": "Bias", "disable": "{ blend_mode == over }",
                     "help": "Midpoint subtracted from each sample first"},
            "offset_with_bias": {"label": "Offset with Bias",
                                 "disable": "{ blend_mode == over }"},
            "blend_mode": {"label": "Blend Mode",
                           "menu": {"add": "Add", "subtract": "Subtract",
                                    "maximum": "Maximum", "over": "Over"},
                           "help": "Over only applies to RGBA"},
            "border": {"label": "Border", "menu": {"wrap": "Wrap", "clamp": "Clamp",
                                                   "black": "Constant (Black)"},
                       "sep": True},
            "filter": {"label": "Filter", "menu": {"bilinear": "Bilinear",
                                                   "point": "Point"}},
            "rand_seed": {"label": "Seed", "section": "Randomization"},
            "jitter": {"label": "Jitter", "help": "One ±Jitter uv offset per octave"},
            "angle_mode": {"label": "Angle Mode",
                           "menu": {"per_octave": "Per Octave", "random": "Random"}},
            "angle": {"label": "Angle"},
            "random_flip_x": {"label": "Random Flip X"},
            "random_flip_y": {"label": "Random Flip Y"},
            **_cpost.panel(),
            "out_layer": _OUT,
        },
    },

    # ── Normal to Height
    "PCG_COPNormalToHeight": {
        "order": ["layer", "strength", "world_size", "method", "tile",
                  "out_layer", "keep_layers"],
        "inputs": {
            "layer": {"label": "Normal Layer"},
            "strength": {"label": "Height Scale"},
            "world_size": {"label": "World Size"},
            "method": {"label": "Method", "section": "Integration",
                       "menu": {"spectral": "Spectral (Frankot-Chellappa)",
                                "exact": "Exact (Inverse of Height to Normal)"},
                       "help": "Tile on uses Exact, off uses Spectral"},
            "tile": {"label": "Tileable (Wrap Edges)", "section": "Integration"},
            "out_layer": _OUT,
            "keep_layers": _KEEP,
        },
    },

    # ── Ocean Spectrum + Evaluate:Grid → Wind → Waves
    "PCG_COPOcean": {
        "order": ["size", "depth", "gravity", "resolution_x", "resolution_y", "time",
                  "loop_period", "rand_seed",
                  "spectrum_type", "wind_speed", "wind_direction", "swell", "fetch_km",
                  "align", "directional_movement",
                  "distribution", "amplitude", "small_cut", "choppiness", "foam_threshold",
                  "out_layer"],
        "inputs": {
            "size": {"label": "Grid Size", "help": "How many meters the image width spans"},
            "depth": {"label": "Depth", "help": "Water depth (meters); 0 = deep water"},
            "gravity": {"label": "Gravity"},
            "resolution_x": {"help": "Used when no cop is wired; with a cop wired, follows its resolution"},
            "time": {"label": "Time", "help": "Seconds"},
            "loop_period": {"label": "Loop Period", "help": "Seconds; 0 = no loop"},
            "rand_seed": {"label": "Seed"},
            # Phillips reads align / directional_movement / amplitude; TMA reads swell / fetch (sim.ocean_spectrum)
            "spectrum_type": {"label": "Spectrum Type", "section": "Wind",
                              "menu": {"phillips": "Phillips", "tma": "TMA"}},
            "wind_speed": {"label": "Wind Speed", "section": "Wind", "help": "Meters/second"},
            "wind_direction": {"label": "Wind Direction", "section": "Wind"},
            "swell": {"label": "Swell", "section": "Wind", "hide": "{ spectrum_type != tma }"},
            "fetch_km": {"label": "Fetch (km)", "section": "Wind",
                         "hide": "{ spectrum_type != tma }"},
            "align": {"label": "Wind Direction Bias", "section": "Wind",
                      "hide": "{ spectrum_type != phillips }", "help": "Larger = waves more aligned with the wind"},
            "directional_movement": {"label": "Directional Movement", "section": "Wind",
                                     "hide": "{ spectrum_type != phillips }",
                                     "help": "Waves travelling against the wind × (1 − this)"},
            "distribution": {"label": "Distribution", "section": "Waves",
                             "menu": {"none": "None", "uniform": "Uniform",
                                      "gaussian": "Gaussian", "log_normal": "Log Normal"}},
            "amplitude": {"label": "Amplitude", "section": "Waves",
                          "hide": "{ spectrum_type != phillips }"},
            "small_cut": {"label": "Min Wavelength", "section": "Waves",
                          "help": "Meters"},
            "choppiness": {"label": "Chop", "section": "Waves"},
            "foam_threshold": {"label": "Foam Threshold", "section": "Waves"},
            "out_layer": _OUT,
        },
    },

    # ── Pixelate
    "PCG_COPPixelate": {
        "order": ["layers", "size", "mode"],
        "inputs": {
            "layers": _LAYERS,
            "size": {"label": "Pixel Size", "sep": True},
            "mode": {"label": "Mode",
                     "menu": {"average": "Average", "sample": "Sample Center"}},
        },
    },

    # ── Planar Inflate
    "PCG_COPPlanarInflate": {
        "order": ["layer", "mode", "height", "iterations", "out_layer"],
        "inputs": {
            "layer": {"label": "Mask Layer"},
            "mode": {"label": "Profile",
                     "menu": {"round": "Round", "poisson": "Poisson (Soap Bubble)"}},
            "height": {"label": "Height"},
            # fx.planar_inflate: round uses an EDT, no iterations
            "iterations": {"label": "Iterations", "hide": "{ mode == round }"},
            "out_layer": _OUT,
        },
    },

    # ── Points from Blobs
    "PCG_COPPointsFromBlobs": {
        "order": ["layer", "threshold", "connectivity", "min_area", "value_layer",
                  "plane", "world_size", "height_layer", "height_scale"],
        "inputs": {
            "layer": {"label": "Mask Layer"},
            "threshold": {"label": "Threshold"},
            "connectivity": {"label": "Connectivity",
                             "menu": {"8": "8 (Include Diagonals)",
                                      "4": "4 (Edges Only)"}},
            "min_area": {"label": "Min Area", "help": "Pixel count"},
            "value_layer": {"label": "Value Layer", "help": "Mean value inside each blob written as a point attribute"},
            "plane": {"label": "Plane", "sep": True, "menu": _PLANE_MENU},
            "world_size": {"label": "World Size"},
            "height_layer": {"label": "Height Layer"},
            # geoimg.points_from_blobs: height_scale is not read when height_layer is empty
            "height_scale": {"label": "Height Scale",
                             "disable": '{ height_layer == "" }'},
        },
    },

    # ── UV to Polar / Polar to UV
    "PCG_COPPolar": {
        "order": ["layers", "direction", "center", "radius", "angle", "border"],
        "inputs": {
            "layers": _LAYERS,
            "direction": {"label": "Conversion", "sep": True,
                          "menu": {"to_polar": "Cartesian to Polar",
                                   "from_polar": "Polar to Cartesian"}},
            "center": {"label": "Center", "help": "uv"},
            "radius": {"label": "Radius"},
            "angle": {"label": "Start Angle"},
            "border": {"label": "Border", "menu": _BORDER_MENU,
                       "help": "Polar to Cartesian only distinguishes Constant from the rest"},
        },
    },
}
