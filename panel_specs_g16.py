"""
Panel specs for group g16 (format: see the docstring at the top of panel_specs.py): the fourteen Grunge maps and the
five Adjacency nodes of Houdini 22's Copernicus. Sections follow Houdini's Grunge panels: Range, Pattern, the map's
own section, Post Processing.
"""
from .geo.cop import grunge as _gr
from .geo.cop import noisepost as _cpost

_PP = list(_cpost.KEYS)

# the first sentence of each parameter's documentation (docs/_data/nodes/g12_cop_5.json holds the full text)
_HELP = {
    "strips_inflate": "Widens the strips", "primary_edge_breakup": "How much the strip edges wander",
    "cracks_size": "Higher = fewer, wider-spaced cracks", "reflection": "Stretches the pattern sideways",
    "lacunarity": "Frequency ratio between layers (whole number, so the map tiles)",
    "cluster": "0 = spots spread evenly", "coverage": "Share of the surface covered by rust",
    "arc_spread": "Angle each wipe sweeps", "streak_fineness": "Number of streaks in each wipe",
    "primary_trailing": "Trail below the large drops; 0 = heads only",
    "secondary_trailing": "Trail below the small drops", "tertiary_balance": "Width of the highlights",
}


def _label(name):
    return " ".join(w.title() for w in name.split("_"))


def _grunge(kind):
    hname, spec, _, _ = _gr.KINDS[kind]
    own = [n for n, *_ in spec]
    inputs = {
        "amplitude": {"label": "Amplitude", "section": "Range"},
        "center": {"label": "Center"},
        "mask_contrast": {"label": "Mask Contrast", "help": "Pushes the map toward 0 and 1 before Amplitude"},
        "element_size": {"label": "Element Size", "section": "Pattern", "sep": True,
                         "help": "Rounded to a whole number of elements per Tile Size"},
        "offset": {"label": "Offset"},
        "tile_size": {"label": "Tile Size", "help": "One seamless repeat (X Y; image width = 1)"},
    }
    for i, n in enumerate(own):
        e = {"label": _label(n)}
        if n in _HELP:
            e["help"] = _HELP[n]
        if i == 0:
            e.update(section=hname.replace("Grunge ", ""), sep=True)
        inputs[n] = e
    inputs["rand_seed"] = {"label": "Seed"}
    inputs.update(_cpost.panel())
    inputs["out_layer"] = {"label": "Output Layer", "sep": True}
    inputs["resolution_x"] = {"help": "Used when no cop is wired; with a cop wired, follows its resolution"}
    return {"order": ["amplitude", "center", "mask_contrast", "element_size", "offset", "tile_size", *own,
                      "rand_seed", *_PP, "out_layer", "resolution_x", "resolution_y"],
            "inputs": inputs}


_PREFIX = {"label": "Adjacency Prefix", "sep": True, "help": "As set on COP Geometry to Adjacency"}

SPECS = {
    **{"PCG_COPGrunge" + "".join(w.title() for w in k.split("_")): _grunge(k) for k in _gr.KINDS},

    "PCG_COPGeometryToAdjacency": {
        "order": ["uv_attrib", "padding", "prefix", "resolution_x", "resolution_y"],
        "inputs": {
            "uv_attrib": {"label": "UV Attribute"},
            "padding": {"label": "Padding", "help": "Texels around each island that get adjacency; at least the "
                                                    "reach of the filter that follows"},
            "prefix": {"label": "Layer Prefix", "sep": True,
                       "help": "Layers = prefix + mask / uv / valid / jac / near / tri / bary / primid / P / N / "
                               "tanU / tanV / uvscale"},
            "resolution_x": {"help": "Used when no cop is wired; with a cop wired, follows its resolution"},
        },
    },
    "PCG_COPExtrapolateWithAdjacency": {
        "order": ["layers", "transform_vectors", "prefix"],
        "inputs": {
            "layers": {"label": "Layers", "help": "Space separated; empty = every layer but the adjacency's own"},
            "transform_vectors": {"label": "Transform Vectors between Islands",
                                  "help": "For texture-space directions (flow, velocity): turn them into this "
                                          "island's orientation"},
            "prefix": _PREFIX,
        },
    },
    "PCG_COPDistortWithAdjacency": {
        "order": ["layer", "direction", "dir_layer", "scale", "transform_vectors", "out_layer", "prefix"],
        "inputs": {
            "layer": {"label": "Source Layer"},
            "direction": {"label": "Direction", "help": "U V offset in uv units",
                          "disable": "{ dir_layer != \"\" }"},
            "dir_layer": {"label": "Direction Layer", "help": "First two channels = offset per texel; empty = "
                                                              "the constant Direction"},
            "scale": {"label": "Scale"},
            "transform_vectors": {"label": "Transform Vectors between Islands"},
            "out_layer": {"label": "Output Layer", "sep": True, "help": "Empty = overwrite the input layer"},
            "prefix": _PREFIX,
        },
    },
    "PCG_COPAttributeSampleWithAdjacency": {
        "order": ["attrib", "out_layer", "extrapolate", "prefix"],
        "inputs": {
            "attrib": {"label": "Attribute", "help": "Vertex, point or primitive attribute"},
            "out_layer": {"label": "Output Layer", "help": "Empty = the attribute's name"},
            "extrapolate": {"label": "Extrapolate", "help": "Fill outside the islands from the neighbours"},
            "prefix": _PREFIX,
        },
    },
    "PCG_COPSpaceTransformWithAdjacency": {
        "order": ["layer", "transformation", "signature", "out_layer", "prefix"],
        "inputs": {
            "layer": {"label": "Source Layer"},
            "transformation": {"label": "Transformation",
                               "menu": {"world_to_tangent": "World to Tangent",
                                        "tangent_to_world": "Tangent to World"}},
            "signature": {"label": "Signature", "menu": {"rgb": "RGB", "uv": "UV"}},
            "out_layer": {"label": "Output Layer", "sep": True, "help": "Empty = overwrite the input layer"},
            "prefix": _PREFIX,
        },
    },
}
