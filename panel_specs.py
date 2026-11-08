"""
Hand-written parameter panel layouts (pcg84), matched against SideFX's official node parameter panels.

The layout panel.py infers from names (labels, vector on one row, colors, ramps, use_X toggles ...) is overridden here.
One entry per node:

    "PCG_Color": {
        "order": [...],            # order on the panel (anything not listed follows in its original order)
        "inputs": {
            "mode": {"label": "Color Type", "menu": {"constant": "Constant", ...}},
            "r": {"hide": "{ mode != constant }"},
            ...
        },
    }

Keys on an input:
    label      label
    menu       dropdown options token -> label (the value stays the token; only the display changes)
    hide       Houdini hidewhen syntax: "{ a == x b != y } { c == 1 }" -- braces are OR'ed,
               terms inside a brace are AND'ed; hidden when it matches. Compares the parameter's current value (token for menus, 0/1 for toggles)
    disable    same syntax; greyed out when it matches (still shown, not editable)
    folder     tab (Houdini folder). The order of first appearance within a node is the tab order
    section    collapsible section; gate: True puts this toggle on the section header
    sep        True: draw a separator line above this row
    toggle     name of another toggle parameter: this row is drawn as ☑ label [value]
    row        {"kind": "vector"|"color", "members": [...], "label": ...}: several parameters on one row
    kind       group / names / ramp / vecstr / colorstr / text / code (usually inferred)
    slider     True / False: whether the number field has a slider after it (default inferred from whether min / max are finite)
    help       hover tooltip
Writing None removes the inferred key.
"""

SPECS = {
    # ── Color SOP: Group / Class / Color Type, then per type Color / Seed / Attribute / Ramp
    "PCG_Color": {
        "order": ["group", "attribute_class", "mode", "r", "rand_seed", "attribute",
                  "auto_range", "in_min", "in_max", "ramp", "hue_shift", "saturation",
                  "value", "random_hue", "random_saturation", "random_value", "name"],
        "inputs": {
            "attribute_class": {"label": "Class",
                                "menu": {"point": "Point", "prim": "Primitive",
                                         "vertex": "Vertex"}},
            "mode": {"label": "Color Type",
                     "menu": {"constant": "Constant", "random": "Random",
                              "random_by_attribute": "Random from Attribute",
                              "ramp_by_attribute": "Ramp from Attribute",
                              "adjust": "Adjust (HSV)"}},
            "r": {"hide": "{ mode != constant }"},
            "rand_seed": {"hide": "{ mode == constant } { mode == ramp_by_attribute }"},
            "attribute": {"hide": "{ mode == constant } { mode == random }",
                          "help": "In Adjust mode, giving an attribute randomizes per piece (same offset within a piece)"},
            "auto_range": {"label": "Compute Range", "sep": True,
                           "hide": "{ mode != ramp_by_attribute }"},
            "in_min": {"row": {"kind": "vector", "members": ["in_min", "in_max"],
                               "label": "Range"},
                       "hide": "{ mode != ramp_by_attribute }",
                       "disable": "{ auto_range == 1 }"},
            "ramp": {"label": "Attribute Ramp", "hide": "{ mode != ramp_by_attribute }"},
            "hue_shift": {"section": "Adjust", "hide": "{ mode != adjust }"},
            "saturation": {"hide": "{ mode != adjust }"},
            "value": {"hide": "{ mode != adjust }"},
            "random_hue": {"hide": "{ mode != adjust }"},
            "random_saturation": {"hide": "{ mode != adjust }"},
            "random_value": {"hide": "{ mode != adjust }"},
            "name": {"label": "Output Attribute", "sep": True},
        },
    },
}


# The remaining nodes are written in separate files and merged here:
#   g1–g4  pcg84's 40 common nodes (geometry basics / modeling / attributes & UV / export & COP)
#   g5–g13 everything else from pcg85 (split by category into nine: attributes, COP ×4, deform / generate, loops / modify, render / topology / UV)
#   g14    the volume / VDB nodes of pcg106
#   g15    the nodes added after the pcg121 code review (nodes_sop3.py)
def _merge():
    import importlib
    parts = [importlib.import_module(f".panel_specs_g{i}", __package__).SPECS
             for i in range(1, 16)]
    for part in parts:
        dup = set(part) & set(SPECS)
        if dup:
            raise KeyError(f"panel_specs defines {sorted(dup)} more than once")
        SPECS.update(part)


_merge()
