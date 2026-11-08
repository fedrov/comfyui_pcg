"""
Layout metadata for the parameter panel (pcg84): used by the frontend web/pcg_panel.js to draw a Houdini-style parameter panel.

The native panel puts one widget per row, parameter names are snake_case, vectors are split over three rows, colors are three numbers, a ramp is a string
of text, and parameters irrelevant to the current mode are always shown -- it is "a mess". A few things make Houdini's parameter panel
readable: human-readable labels, tabs / collapsible sections, xyz on one row, color swatches, draggable ramps, hiding irrelevant parameters by mode
(hidewhen), toggles in front of parameters (☑ + value). All of this is **layout information** that does not change the parameters themselves, so:

  · not a single native widget is touched (workflows store values by index, inserting one shifts everything); the frontend hides them,
    and appends an HTML panel at the end of the node; the controls on the panel still read and write those widgets' values
  · the layout is written into each input's options (`pcg_ui`), travelling to the frontend with /object_info, no separate endpoint,
    never out of sync with the node definition

Most of the layout is **derived from names** (derive() below):
  label          snake_case → Title Case, abbreviation table (uv → UV, cls → Class, rand_seed → Seed …)
  vector row     three (or two) consecutive numeric parameters named _x _y _z / tx ty tz / r g b
  color          r g b or xxx_r xxx_g xxx_b → color swatch + color picker + three numbers
  ramp           name contains ramp and the default is a "pos:value …" string → draggable ramp editor;
               the interpolation combo (ramp_mode) is folded into the editor
  toggle + value use_X directly followed by X → one row: ☑ label [value], value grayed out when the toggle is off (Houdini's way)
  string vector  defaults like "0.5 0.5" / "1 1 1" → split into several number fields (names with color get a swatch)
  group / attrib is_group / name_kind → a ▾ next to the field, listing the names actually present upstream
  combo          option token → label (random_by_attribute → Random by Attribute)
  sections       the existing section / section_gate as before → collapsible sections, toggle on the section header

What cannot be derived (parameter order on the Houdini panel, tabs, which parameters only appear in some mode, official menu
names) is hand-written in panel_specs.py following SideFX's official panels, overriding the derived result.
"""
from __future__ import annotations

import re

UI_KEY = "pcg_ui"

# ─────────────────────────────────────────────────────────── Labels
WORDS = {
    "uv": "UV", "uvs": "UVs", "id": "ID", "rgb": "RGB", "rgba": "RGBA", "sdf": "SDF",
    "lod": "LOD", "cd": "Cd", "n": "N", "p": "P", "cop": "COP", "hsv": "HSV",
    "cls": "Class", "num": "Number of", "dir": "Direction", "pos": "Position",
    "min": "Min", "max": "Max", "vdb": "VDB", "ao": "AO",
    "prim": "Primitive", "prims": "Primitives", "attrib": "Attribute",
    "attribs": "Attributes", "pscale": "pscale",
    "orm": "ORM", "exr": "EXR", "png": "PNG", "csv": "CSV", "json": "JSON",
    "glb": "GLB", "obj": "OBJ", "fbx": "FBX", "vex": "VEX", "xform": "Xform",
    "cuda": "CUDA", "cpu": "CPU", "ucx": "UCX", "api": "API", "ai": "AI",
    "arap": "ARAP", "lscm": "LSCM", "nurbs": "NURBS", "bezier": "Bezier",
    "of": "of", "to": "to", "by": "by", "from": "from", "and": "and", "or": "or",
    "the": "the", "in": "in", "on": "on", "per": "Per", "a": "A", "b": "B",
    "x": "X", "y": "Y", "z": "Z", "w": "W", "u": "U", "v": "V", "srgb": "sRGB",
    "gl": "GL", "dx": "DX", "2d": "2D", "3d": "3D", "01": "0-1",
}
WHOLE = {
    "rand_seed": "Seed", "cls": "Class", "attribute_class": "Attribute Class",
    "keep_selected": "Keep Selected", "out_layer": "Output Layer",
    "resolution": "Resolution", "tx": "Translate", "rx": "Rotate", "sx": "Scale",
}
# vector prefix → label (tx ty tz → Translate)
VEC_PREFIX = {
    "t": "Translate", "r": "Rotate", "s": "Scale", "c": "Center", "p": "Pivot",
    "n": "Normal", "d": "Direction", "dir": "Direction", "up": "Up Vector",
    "size": "Size", "div": "Divisions", "offset": "Offset", "axis": "Axis",
    "res": "Resolution", "resolution": "Resolution", "vol_res": "Volume Resolution",
    "bound_min": "Bounds Min", "bound_max": "Bounds Max", "divisions": "Divisions",
    "target_p": "Target Position", "target_s": "Target Size",
    "element_size": "Element Size", "axis_scale": "Axis Scale",
}


def auto_label(name):
    n = str(name)
    if n in WHOLE:
        return WHOLE[n]
    parts = [p for p in n.split("_") if p]
    out = []
    for p in parts:
        lo = p.lower()
        out.append(WORDS.get(lo, p[:1].upper() + p[1:]))
    s = " ".join(out) or n
    return s[:1].upper() + s[1:]


def menu_label(tok):
    t = str(tok)
    if t in ("a-b", "b-a"):          # Boolean direction: not turned into A-b
        return t
    return auto_label(t)


# ─────────────────────────────────────────────────────────── Derivation
_NUM = ("INT", "FLOAT")
_VEC_STR = re.compile(r"^\s*-?\d+(\.\d+)?(\s+-?\d+(\.\d+)?){1,3}\s*$")
_RAMP_STR = re.compile(r"^\s*-?[\d.]+\s*:\s*-?[\d.]+")


def _kind(spec):
    t = spec[0]
    if isinstance(t, (list, tuple)):
        return "combo"
    return {"INT": "int", "FLOAT": "float", "BOOLEAN": "toggle",
            "STRING": "string"}.get(t)


def _opts(spec):
    return spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}


def _widget_kind(spec):
    """Input that is a widget → kind; forceInput ones (wire only) are not widgets."""
    return None if _opts(spec).get("forceInput") else _kind(spec)


def _vec_groups(names, kinds):
    """
    Find vector / color groups among the widget names in original order → [(members, row kind, label)].
    Only **consecutive** groups that are all numeric are accepted:
      xxx_x xxx_y [xxx_z [xxx_w]]    vector (two count too, e.g. resolution_x / _y)
      xxx_r xxx_g xxx_b [xxx_a]      color
      xxx_u xxx_v                    2D
      tx ty tz / front_tx …         a one- or two-letter prefix + x y z (Houdini's t r s convention)
      r g b                          color
    """
    num = {n: k in ("int", "float") for n, k in zip(names, kinds)}

    def run(i, pre, sufs, need):
        mem = []
        for s in sufs:
            j = i + len(mem)
            if j < len(names) and names[j] == pre + s and num[names[j]]:
                mem.append(names[j])
            else:
                break
        return mem if len(mem) >= need else None

    out, i = [], 0
    while i < len(names):
        a = names[i]
        hit = None
        if a == "r" and names[i:i + 3] == ["r", "g", "b"] and all(num[m] for m in "rgb"):
            hit = (["r", "g", "b"], "color", "Color")
        elif a.endswith("_x"):
            pre = a[:-2]
            m = run(i, pre, ("_x", "_y", "_z", "_w"), 2)
            if m:
                hit = (m, "vector", VEC_PREFIX.get(pre, auto_label(pre)))
        elif a.endswith("_r"):
            pre = a[:-2]
            m = run(i, pre, ("_r", "_g", "_b", "_a"), 3)
            if m:
                hit = (m, "color", auto_label(pre))
        elif a.endswith("_u"):
            pre = a[:-2]
            m = run(i, pre, ("_u", "_v"), 2)
            if m:
                hit = (m, "vector", auto_label(pre))
        elif a.endswith("x") and re.fullmatch(r"([a-z]+_)?[a-z]{1,2}x", a):
            pre = a[:-1]
            m = run(i, pre, ("x", "y", "z"), 3)
            if m:
                head, _, last = pre.rpartition("_")
                lab = VEC_PREFIX.get(last, auto_label(last))
                hit = (m, "vector", (auto_label(head) + " " + lab) if head else lab)
        if hit:
            out.append(hit)
            i += len(hit[0])
        else:
            i += 1
    return out


def derive(it):
    """INPUT_TYPES result → {input name: ui dict} (widget inputs only)."""
    specs = {}
    for grp in ("required", "optional"):
        for k, v in (it.get(grp) or {}).items():
            if _widget_kind(v):
                specs[k] = v
    names = list(specs)
    kinds = [_kind(specs[n]) for n in names]
    ui = {}
    for n in names:
        s = specs[n]
        o = _opts(s)
        u = {"label": auto_label(n)}
        k = _kind(s)
        if k == "combo":
            u["menu"] = {str(t): menu_label(t) for t in s[0]}
        if o.get("is_group"):
            u["kind"] = "group"
        elif o.get("name_kind"):
            u["kind"] = "names"
            u["names"] = [o.get("name_kind"), o.get("name_cls")]
        if k == "string":
            d = str(o.get("default", ""))
            if o.get("multiline") or o.get("code_hl") or o.get("ch_store"):
                u["kind"] = "text" if not (o.get("code_hl") or o.get("ch_store")) \
                    else "code"
            elif "ramp" in n and _RAMP_STR.match(d):
                comps = max(len(t.split(":", 1)[1].split(","))
                            for t in d.split() if ":" in t)
                u["kind"] = "ramp"
                u["ramp"] = {"comps": 3 if comps >= 3 else 1}
            elif _VEC_STR.match(d) and "kind" not in u:
                u["kind"] = "colorstr" if "color" in n else "vecstr"
                u["comps"] = len(d.split())
        if o.get("section"):
            u["section"] = o["section"]
            if o.get("section_gate"):
                u["gate"] = True
        ui[n] = u
    # vector / color row
    for mem, kind, label in _vec_groups(names, kinds):
        ui[mem[0]]["row"] = {"kind": kind, "members": mem, "label": label}
        for m in mem[1:]:
            ui[m]["in_row"] = mem[0]
    # fold the ramp's interpolation into the editor
    for n in names:
        if ui[n].get("kind") == "ramp":
            for cand in (n + "_mode", "ramp_mode", "ramp_interp"):
                if cand in ui and cand != n and _kind(specs[cand]) == "combo" \
                        and "in_ramp" not in ui[cand]:
                    ui[n]["ramp"]["interp"] = cand
                    ui[cand]["in_ramp"] = n
                    break
    # use_X directly followed by X → ☑ + value row (section toggles don't count: they are on the section header)
    for a, b in zip(names, names[1:]):
        if a.startswith("use_") and a[4:] == b and _kind(specs[a]) == "toggle" \
                and not ui[a].get("gate") and "in_row" not in ui[b]:
            ui[b]["toggle"] = a
            ui[a]["in_toggle"] = b
    return ui


def _deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        elif v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def layout_for(node_id, it):
    """derived + hand-written specs → {input name: ui}, plus a node-level "_node"."""
    from .panel_specs import SPECS
    ui = derive(it)
    spec = SPECS.get(node_id, {})
    for n, over in (spec.get("inputs") or {}).items():
        if n not in ui:
            raise KeyError(f"'{n}' in panel_specs[{node_id}] is not a parameter of this node")
        ui[n] = _deep_merge(ui[n], over)
    # Recompute the auxiliary markers from the final row / toggle / ramp: hand-written rows may override derived rows,
    # and a stale in_row would make the frontend hide a parameter inside a row that no longer exists
    for u in ui.values():
        u.pop("in_row", None)
        u.pop("in_toggle", None)
    for n, u in ui.items():
        for m in (u.get("row") or {}).get("members", [])[1:]:
            if m in ui:
                ui[m]["in_row"] = n
        t = u.get("toggle")
        if t in ui:
            ui[t]["in_toggle"] = n
    node = {k: v for k, v in spec.items() if k != "inputs"}
    return ui, node


def annotate(node_id, it):
    """Write ui into the options of every widget input (on a copy, the original dict is not modified)."""
    ui, node = layout_for(node_id, it)
    out = {}
    first = True
    for grp, d in it.items():
        if not isinstance(d, dict):
            out[grp] = d
            continue
        nd = {}
        for k, v in d.items():
            if k in ui and isinstance(v, (list, tuple)):
                o = dict(_opts(v))
                u = dict(ui[k])
                if first:
                    u["_node"] = node
                    first = False
                o[UI_KEY] = u
                v = (v[0], o) + tuple(v[2:])
            nd[k] = v
        out[grp] = nd
    return out


# ─────────────────────────────────────────────────────────── hidewhen
_COND_TOK = re.compile(r'"[^"]*"|\'[^\']*\'|==|!=|<=|>=|<|>|[^\s{}<>=!"\']+|[{}]')


def parse_cond(text):
    """
    Houdini's hidewhen / disablewhen: "{ a == x b != y } { c == 1 }"
    → [[(a, "==", "x"), (b, "!=", "y")], [(c, "==", "1")]]  outer level is OR, inner level is AND.
    The frontend pcg_panel.js has an identical parser; the tests check both sides against the same set of expressions.
    """
    toks = _COND_TOK.findall(str(text or ""))
    groups, cur, i = [], None, 0
    while i < len(toks):
        t = toks[i]
        if t == "{":
            if cur is not None:
                raise ValueError(f"condition '{text}': braces cannot be nested")
            cur = []
            i += 1
        elif t == "}":
            if cur is None:
                raise ValueError(f"condition '{text}': one }} too many")
            if not cur:
                raise ValueError(f"condition '{text}': empty {{ }}")
            groups.append(cur)
            cur = None
            i += 1
        else:
            if cur is None:
                raise ValueError(f"condition '{text}': comparisons must be written inside {{ }}")
            if i + 2 >= len(toks) or toks[i + 2] in ("{", "}"):
                raise ValueError(f"condition '{text}': '{t}' is missing a comparison or value")
            name, op, val = toks[i], toks[i + 1], toks[i + 2]
            if op not in ("==", "!=", "<", ">", "<=", ">="):
                raise ValueError(f"condition '{text}': '{op}' is not a comparison operator")
            if val[:1] in "\"'":
                val = val[1:-1]
            cur.append((name, op, val))
            i += 3
    if cur is not None:
        raise ValueError(f"condition '{text}': one }} missing")
    return groups


def check_layout(node_id, it):
    """
    Self-check of the hand-written specs, returns a list of problems (empty = fine): names, combo values, toggle types, row members,
    and the order table must all match. Run it when writing specs; the tests run it too.
    """
    probs = []
    try:
        ui, node = layout_for(node_id, it)
    except Exception as e:                                  # noqa: BLE001
        return [f"{node_id}: {e}"]
    specs = {}
    for grp in ("required", "optional"):
        for k, v in (it.get(grp) or {}).items():
            if _widget_kind(v):
                specs[k] = v
    for n in node.get("order") or []:
        if n not in ui:
            probs.append(f"{node_id}: '{n}' in order is not a parameter")
    if len(set(node.get("order") or [])) != len(node.get("order") or []):
        probs.append(f"{node_id}: duplicates in order")
    seen_row = {}
    for n, u in ui.items():
        for key in ("hide", "disable"):
            if not u.get(key):
                continue
            try:
                g = parse_cond(u[key])
            except ValueError as e:
                probs.append(f"{node_id}.{n}.{key}: {e}")
                continue
            for conj in g:
                for (a, op, val) in conj:
                    if a not in specs:
                        probs.append(f"{node_id}.{n}.{key}: '{a}' is not a parameter")
                        continue
                    k = _kind(specs[a])
                    if k == "combo" and op in ("==", "!=") and \
                            val not in [str(t) for t in specs[a][0]]:
                        probs.append(f"{node_id}.{n}.{key}: '{a}' has no option '{val}'")
                    if k == "toggle" and val not in ("0", "1"):
                        probs.append(f"{node_id}.{n}.{key}: toggle '{a}' can only be compared with 0 / 1")
        t = u.get("toggle")
        if t and (t not in specs or _kind(specs[t]) != "toggle"):
            probs.append(f"{node_id}.{n}: toggle '{t}' is not a toggle parameter")
        r = u.get("row")
        if r:
            mem = r.get("members") or []
            if not mem or mem[0] != n:
                probs.append(f"{node_id}.{n}: the first member of row must be itself")
            for m in mem:
                if m not in specs:
                    probs.append(f"{node_id}.{n}: row member '{m}' is not a parameter")
                elif m in seen_row:
                    probs.append(f"{node_id}: '{m}' is in two rows at once")
                seen_row[m] = n
        for key in ("menu",):
            if u.get(key) and _kind(specs[n]) == "combo":
                bad = set(u[key]) - {str(t) for t in specs[n][0]}
                if bad:
                    probs.append(f"{node_id}.{n}: menu has nonexistent options {sorted(bad)}")
    return probs


def attach_panels(mappings):
    """Wrap annotate around the INPUT_TYPES of every node class. Wraps only once."""
    for node_id, cls in mappings.items():
        if getattr(cls, "_pcg_panel_wrapped", False):
            continue
        orig = cls.INPUT_TYPES

        def make(orig=orig, node_id=node_id):
            def INPUT_TYPES(c=None):
                return annotate(node_id, orig())
            return classmethod(lambda c: INPUT_TYPES(c))
        cls.INPUT_TYPES = make()
        cls._pcg_panel_wrapped = True


# ─────────────────────────────────────────────────────────── Panel height estimate
# make_workflows layout needs to know how tall nodes are (otherwise nodes overlap in the generated workflows). This follows
# pcg_panel.js's buildModel + visibility rules; the height of each row kind was measured in the real frontend (1.47),
# and the e2e test (test_panel_e2e.py) compares against heights measured in the real frontend
H = {"row": 25, "sep": 9, "sec_head": 29, "sec_body": 6, "tabs": 31, "tab_body": 4,
     "root": 10, "ramp": 95, "ramp_float": 152, "text_head": 19, "text_line": 15, "text_pad": 10,
     "extra": 5}
# Width (pixels) of each character in ASCII 32–126 for 12px Inter (the frontend's built-in UI font), measured in the real frontend
# (one character repeated 100 times, total width measured). Before pcg85 an average char width of 6.7 was used, so long tab text made one row
# be estimated as two (Ballistic Path's three tabs actually fit on one row, overestimated by 24 px)
_GLYPH_W = [int(x) for x in (
    "3 3 6 8 8 12 8 4 4 4 6 8 3 6 3 4 8 5 7 7 8 7 7 7 7 7 3 4 8 8 8 6 12 8 8 9 9 7 "
    "7 9 9 3 7 8 7 11 9 9 8 9 8 8 8 9 8 12 8 8 8 4 3 4 6 5 4 7 7 7 7 7 4 7 7 3 3 7 "
    "3 11 7 7 7 7 5 6 4 7 7 10 7 7 7 5 4 5 8").split()]
CHAR_W = 6.7          # characters outside the table (CJK etc.) are estimated as this × 2


def text_width(s):
    """Width (pixels) of a piece of text in the 12px UI font."""
    return sum(_GLYPH_W[ord(c) - 32] if 32 <= ord(c) < 127 else CHAR_W * 2
               for c in str(s))


def _cond_true(groups, values):
    def cmp(a, op, b):
        try:
            x, y = float(a), float(b)
            if a == "" or b == "":
                raise ValueError
        except ValueError:
            x, y = a, b
        return {"==": x == y, "!=": x != y, "<": x < y, ">": x > y,
                "<=": x <= y, ">=": x >= y}[op]

    def val(n):
        v = values.get(n)
        return "1" if v is True else "0" if v is False else "" if v is None else str(v)
    return any(all(cmp(val(a), op, b) for a, op, b in conj) for conj in groups)


def panel_model(node_id, it):
    """Same structure as JS buildModel: (top blocks, [(tab name, blocks)]). block = (section, section toggle, [parameters])."""
    ui, node = layout_for(node_id, it)
    specs = {}
    for grp in ("required", "optional"):
        for k, v in (it.get(grp) or {}).items():
            if _widget_kind(v):
                specs[k] = v
    names = list(specs)
    order = [n for n in (node.get("order") or []) if n in names]
    order += [n for n in names if n not in order]
    lead = [n for n in order if not (ui[n].get("in_row") or ui[n].get("in_toggle")
                                     or ui[n].get("in_ramp"))]
    top, tabs, tab_of = [], [], {}
    for n in lead:
        u = ui[n]
        blocks = top
        if u.get("folder"):
            if u["folder"] not in tab_of:
                tab_of[u["folder"]] = (u["folder"], [])
                tabs.append(tab_of[u["folder"]])
            blocks = tab_of[u["folder"]][1]
        sec = u.get("section")
        if u.get("gate") and sec and _kind(specs[n]) == "toggle":
            blocks.append([sec, n, []])
            continue
        if blocks and blocks[-1][0] == sec:
            blocks[-1][2].append(n)
        else:
            blocks.append([sec, None, [n]])
    return ui, specs, top, tabs


def estimate_panel_height(node_id, it, values=None, width=340, linked=()):
    """Panel height (pixels, excluding top/bottom margin) for the given parameter values."""
    ui, specs, top, tabs = panel_model(node_id, it)
    vals = {}
    for n, s in specs.items():
        d = _opts(s).get("default")
        if d is None and _kind(s) == "combo":
            d = s[0][0] if s[0] else None
        vals[n] = d
    vals.update(values or {})

    # linked is kept only for compatibility with old callers: since pcg85 wired parameters still take a row (the field shows the source,
    # the socket dot aligns to this row), no longer hidden, and no extra native widget either
    del linked

    def shown(n):
        g = ui[n].get("hide")
        return not (g and _cond_true(parse_cond(g), vals))

    def item_h(n):
        u = ui[n]
        if not shown(n):
            return 0
        h = H["sep"] if u.get("sep") else 0
        if u.get("kind") == "ramp":
            # a float ramp is a tall curve area (control points drawn on the curve); a color ramp is a color band + a row of markers
            return h + H["ramp" if (u.get("ramp") or {}).get("comps", 1) >= 3 else "ramp_float"]
        if u.get("kind") == "text" or (_opts(specs[n]).get("multiline")
                                       and u.get("kind") != "code"):
            lines = str(vals.get(n) or "").count("\n") + 1
            rows = min(24, max(3, lines + 1))
            return h + H["text_head"] + rows * H["text_line"] + H["text_pad"]
        return h + H["row"]

    def blocks_h(blocks):
        t = 0
        for sec, gate, items in blocks:
            if not sec:
                t += sum(item_h(n) for n in items)
                continue
            if gate and ui[gate].get("hide") and _cond_true(parse_cond(ui[gate]["hide"]), vals):
                continue
            body = sum(item_h(n) for n in items)
            if not gate and body == 0:
                continue
            t += H["sec_head"]
            on = vals.get(gate) is not False if gate else True
            if on and body:
                t += H["sec_body"] + body
        return t

    total = H["root"] + blocks_h(top)
    if tabs:
        # Same as pcg_panel.js: a tab is shown only if one of its rows is visible, or one of its section toggles is not hidden itself
        # (before pcg100 only "has a section toggle" was checked, so tabs whose toggle was hidden counted too, and Chain was estimated one row too tall)
        def gate_shown(g):
            hg = ui[g].get("hide")
            return not (hg and _cond_true(parse_cond(hg), vals))
        vis = [(name, b) for name, b in tabs if blocks_h(b) > 0 or
               any(g and gate_shown(g) for _, g, _ in b)]
        avail = width - 8 - 12
        lines, x = 1, 0
        for name, _ in vis:
            w = text_width(name) + 20          # padding 9 × 2 + border 2
            # +1: the char-width table is summed after per-character rounding, real layout is sub-pixel -- Attribute Adjust Vector's four tabs
            # compute to 381 > 380 by the table and would wrap, but fit on one row in the real frontend (measured by the pcg100 e2e)
            if x and x + w > avail + 1:
                lines += 1
                x = 0
            x += w + 2
        # when no tab is shown the tab bar is empty: only the top margin 6 + bottom border 1 remain
        total += (H["tabs"] + (lines - 1) * 24 if vis else 7) + H["tab_body"]
        if vis:
            total += blocks_h(vis[0][1])
    return int(round(total + H["extra"]))


# Other frontend extensions add their own widgets to these nodes (parameter declaration panel, spreadsheet); the panel does not take them over.
# (the 3D viewport has no parameter widgets, so it is never taken over and need not be listed)
JS_CUSTOM = frozenset({"PCG_Parameters", "PCG_GeoSpreadsheet"})


def panel_applies(node_id, it):
    """Whether this node is replaced by the panel in the frontend (matches eligible in pcg_panel.js, compared by the e2e test)."""
    if not str(node_id).startswith("PCG_") or node_id in JS_CUSTOM:
        return False
    any_w = False
    for grp in ("required", "optional"):
        for k, v in (it.get(grp) or {}).items():
            if not _widget_kind(v):
                continue
            any_w = True
            o = _opts(v)
            if o.get("multiline") and (o.get("code_hl") or o.get("ch_store")):
                return False
            if o.get("ch_store"):
                return False
    return any_w


def estimate_node_height(node_id, it, outs=1, values=None, width=340, linked=(),
                         cop_preview=False):
    """
    Height of the whole node (excluding the title bar) once the panel takes over; coefficients fitted from measuring 367 nodes in the real frontend:
      26 + 20 × max(input slots, output slots) + panel + COP thumbnail (≈ width)
    (before pcg85 wired parameters kept their native widget, adding a 22 row each; now the socket aligns to the panel row)
    """
    socks = 0
    for grp in ("required", "optional"):
        for k, v in (it.get(grp) or {}).items():
            if not _widget_kind(v):
                socks += 1
    return int(26 + 20 * max(socks, outs) + estimate_panel_height(node_id, it, values, width)
               + (width + 14 if cop_preview else 0))
