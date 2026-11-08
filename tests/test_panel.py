"""
The Python side of the parameter panel (pcg84): panel.py's derivation, self-checks of the hand-written specs (panel_specs*.py), hidewhen parsing,
height estimates; then generates panel_fixture.json for the frontend unit test (test_panel.mjs) to compare against -- both sides' hidewhen parsing,
ramp sampling and panel structure are compared against the same golden reference; change either side and that side's test goes red.

Layout / interaction in the real frontend is in test_panel_e2e.py (needs a running ComfyUI).
"""
import json
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg import panel as P                      # noqa: E402
from comfyui_pcg.panel_specs import SPECS               # noqa: E402
from comfyui_pcg.geo import ramp as RAMP                # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def err(name, fn, frag):
    try:
        fn()
    except Exception as e:                              # noqa: BLE001
        check(name, frag in str(e), str(e)[:90])
        return
    check(name, False, "no error raised")


# ═══════════════════════════════════════════════════ 1. derivation
sec("derivation: labels / vectors / colors / ramps / toggles")
check("labels: snake_case -> Title Case, abbreviation table", [P.auto_label(x) for x in
      ("attribute_class", "uv_style", "rand_seed", "cls", "normal_y", "id_attribute", "fit_to_01")]
      == ["Attribute Class", "UV Style", "Seed", "Class", "Normal Y", "ID Attribute", "Fit to 0-1"])
check("  dropdown items: random_by_attribute -> Random by Attribute; +y / 8 / a-b unchanged",
      [P.menu_label(x) for x in ("random_by_attribute", "+y", "8", "prim", "a-b")]
      == ["Random by Attribute", "+y", "8", "Primitive", "a-b"])


def names_kinds(pairs):
    return [n for n, _ in pairs], [k for _, k in pairs]


g = P._vec_groups(*names_kinds([("tx", "float"), ("ty", "float"), ("tz", "float"),
                                ("size_x", "float"), ("size_y", "float"),
                                ("r", "float"), ("g", "float"), ("b", "float"),
                                ("c_r", "float"), ("c_g", "float"), ("c_b", "float"), ("c_a", "float"),
                                ("front_tx", "float"), ("front_ty", "float"), ("front_tz", "float"),
                                ("scale_u", "float"), ("scale_v", "float"),
                                ("up_x", "float"), ("up_y", "string"), ("up_z", "float"),
                                ("mx", "float"), ("my", "float"), ("zz", "float")]))
check("vector / color on one row: tx ty tz, xxx_x xxx_y, r g b, xxx_r…_a, front_tx…, xxx_u xxx_v",
      g == [(["tx", "ty", "tz"], "vector", "Translate"), (["size_x", "size_y"], "vector", "Size"),
            (["r", "g", "b"], "color", "Color"), (["c_r", "c_g", "c_b", "c_a"], "color", "C"),
            (["front_tx", "front_ty", "front_tz"], "vector", "Front Translate"),
            (["scale_u", "scale_v"], "vector", "Scale")], g)
check("  not merged if a non-numeric one sits in between (up_y is a string); not merged for two letters + x y without z", all(
    "up_x" not in m and "mx" not in m for m, _, _ in g))

it = {"required": {"geo": ("GEOMETRY",), "mode": (["a", "b"],),
                   "use_clamp": ("BOOLEAN", {"default": False}),
                   "clamp": ("FLOAT", {"default": 1.0}),
                   "ramp": ("STRING", {"default": "0:0,0,0  1:1,1,1"}),
                   "ramp_mode": (["linear", "smooth"],),
                   "remap_ramp": ("STRING", {"default": "0:0  1:1"}),
                   "keys": ("STRING", {"default": "0:0  24:1"}),
                   "color": ("STRING", {"default": "1 1 1"}),
                   "pos": ("STRING", {"default": "0.5 0.5"}),
                   "g1": ("STRING", {"default": "", "is_group": True}),
                   "at": ("STRING", {"default": "", "name_kind": "attrib", "name_cls": "prim"}),
                   "code": ("STRING", {"default": "", "multiline": True, "code_hl": True}),
                   "txt": ("STRING", {"default": "", "multiline": True}),
                   "a_in": ("FLOAT", {"default": 0.0, "forceInput": True}),
                   "use_foo": ("BOOLEAN", {"default": False, "section": "Foo",
                                           "section_gate": True}),
                   "foo": ("FLOAT", {"default": 1.0, "section": "Foo"})}}
d = P.derive(it)
check("ramp: name contains ramp, default is position:value; component count from the default; ramp_mode folded into the editor",
      d["ramp"]["kind"] == "ramp" and d["ramp"]["ramp"] == {"comps": 3, "interp": "ramp_mode"}
      and d["ramp_mode"]["in_ramp"] == "ramp" and d["remap_ramp"]["ramp"]["comps"] == 1)
check("  names without ramp (animation keyframes keys) are not ramps", d["keys"].get("kind") != "ramp")
check("  when two ramps share one ramp_mode, only the first gets it", d["remap_ramp"]["ramp"].get("interp") is None)
check("use_X directly followed by X -> ☑ + value on one row", d["clamp"].get("toggle") == "use_clamp"
      and d["use_clamp"].get("in_toggle") == "clamp")
check("  section toggle use_foo followed by foo: still a section toggle, not made into ☑ + value", "toggle" not in d["foo"]
      and d["use_foo"].get("gate") and "in_toggle" not in d["use_foo"])
check("string vectors / colors: '1 1 1' -> colorstr 3; '0.5 0.5' -> vecstr 2",
      (d["color"]["kind"], d["color"]["comps"], d["pos"]["kind"], d["pos"]["comps"])
      == ("colorstr", 3, "vecstr", 2))
check("group / attribute name / code / multi-line text", (d["g1"]["kind"], d["at"]["kind"], d["at"]["names"],
                                d["code"]["kind"], d["txt"]["kind"])
      == ("group", "names", ["attrib", "prim"], "code", "text"))
check("wire-only inputs (forceInput) and socket types are not parameters", "a_in" not in d and "geo" not in d)

# ═══════════════════════════════════════════════════ 2. specs
sec("hand-written specs: checked against Houdini, for every node whose panel is taken over")
# pcg85: the remaining 326 got specs too -- every taken-over node has one entry, no extra names
applies = {n for n, c in M.items() if P.panel_applies(n, c.INPUT_TYPES())}
# pcg100: the node count is no longer hard-coded (every batch adds nodes); coverage just has to match exactly and be no less than pcg99's 367
check(f"specs cover exactly the nodes whose panels are taken over ({len(SPECS)}, no more no less, at least 367)",
      set(SPECS) == applies and len(SPECS) >= 367,
      (len(SPECS), sorted(applies - set(SPECS))[:5], sorted(set(SPECS) - applies)[:5]))
probs = []
for n, c in M.items():
    probs += P.check_layout(n, c.INPUT_TYPES())
check("layout self-checks pass for every node (derived + hand-written): names, dropdown values, toggles, row members, order table", not probs,
      probs[:5])
lost = []
for n, c in M.items():
    it = c.INPUT_TYPES()
    ui, specs, top, tabs = P.panel_model(n, it)
    shown = set()
    for sec_, gate, items in top + [b for _, bl in tabs for b in bl]:
        if gate:
            shown.add(gate)
        for x in items:
            shown.add(x)
            u = ui[x]
            shown.update((u.get("row") or {}).get("members") or [])
            if u.get("toggle"):
                shown.add(u["toggle"])
            if (u.get("ramp") or {}).get("interp"):
                shown.add(u["ramp"]["interp"])
    if set(specs) - shown:
        lost.append((n, sorted(set(specs) - shown)))
check("every parameter of every node has a place on the panel (none lost by derivation / specs)", not lost, lost[:3])
dup = []
for n, c in M.items():
    ui, specs, top, tabs = P.panel_model(n, c.INPUT_TYPES())
    seen = []
    for sec_, gate, items in top + [b for _, bl in tabs for b in bl]:
        seen += ([gate] if gate else []) + items
        for x in items:
            seen += ((ui[x].get("row") or {}).get("members") or [])[1:]
            seen += [ui[x]["toggle"]] if ui[x].get("toggle") else []
    if len(seen) != len(set(seen)):
        dup.append(n)
check("  and no parameter appears twice", not dup, dup[:3])
ui, _ = P.layout_for("PCG_Color", M["PCG_Color"].INPUT_TYPES())
check("hand-written rows override derived ones: in_min / in_max on one row, in_max marked in_row; old derived marks recomputed",
      ui["in_min"]["row"]["members"] == ["in_min", "in_max"] and ui["in_max"]["in_row"] == "in_min"
      and "in_row" not in ui["in_min"])
ui_p, _ = P.layout_for("PCG_COPPattern", M["PCG_COPPattern"].INPUT_TYPES())
check("  None in a spec = remove the derived key (COPPattern's gap moved out of the Tile section)", "section" not in ui_p["gap"])
ui0, specs0, top0, _ = P.panel_model("PCG_Color", M["PCG_Color"].INPUT_TYPES())
check("  panel order follows the spec's order (Group at the top; in the native order it is second)",
      top0[0][2][:3] == ["group", "attribute_class", "mode"], top0[0][2][:3])
SPECS["PCG_Transform"], _old_t = {"inputs": {"tx": {"row": None}}}, SPECS.get("PCG_Transform")
uit, _ = P.layout_for("PCG_Transform", M["PCG_Transform"].INPUT_TYPES())
SPECS["PCG_Transform"] = _old_t
check("  the spec removed the derived row: ty / tz no longer hang under that row (otherwise they'd vanish from the panel)",
      "row" not in uit["tx"] and "in_row" not in uit["ty"] and "in_row" not in uit["tz"])
bad_spec = {"PCG_Color": {"inputs": {"nope": {"label": "x"}}}}
old = dict(SPECS)
SPECS.update(bad_spec)
err("a spec naming a nonexistent parameter -> error", lambda: P.layout_for("PCG_Color", M["PCG_Color"].INPUT_TYPES()),
    "nope")
SPECS.clear()
SPECS.update(old)
SPECS["PCG_Color"] = dict(old["PCG_Color"], inputs=dict(old["PCG_Color"]["inputs"],
                                                          r={"hide": "{ mode != nothing }"}))
pr = P.check_layout("PCG_Color", M["PCG_Color"].INPUT_TYPES())
SPECS.clear()
SPECS.update(old)
check("  hidewhen naming an option the dropdown doesn't have -> reported by the self-check", any("nothing" in x for x in pr), pr)

# ═══════════════════════════════════════════════════ 3. hidewhen
sec("parsing hidewhen / disablewhen")
COND_OK = ["{ mode != constant }", '{ a == x b != "y z" } { c >= 1 }', "{a==1}{b<2}",
           "{ t == 1 }", "{ x <= -0.5 }", "{ s == '' }"]
COND_BAD = ["{ a == }", "a == 1", "{ a == 1", "{ a ~ 1 }", "{}", "{ a == 1 { b == 2 } }"]
try:
    P.parse_cond("{ a == 1 { b == 2 } }")
    _nest = ""
except ValueError as e:
    _nest = str(e)
parsed = {t: P.parse_cond(t) for t in COND_OK}
check("syntax: OR between braces, AND inside; spaces inside quotes kept; works without spaces too",
      parsed["{ mode != constant }"] == [[("mode", "!=", "constant")]]
      and parsed['{ a == x b != "y z" } { c >= 1 }'] == [[("a", "==", "x"), ("b", "!=", "y z")],
                                                         [("c", ">=", "1")]]
      and parsed["{a==1}{b<2}"] == [[("a", "==", "1")], [("b", "<", "2")]]
      and parsed["{ s == '' }"] == [[("s", "==", "")]])
bad_ok = []
for t in COND_BAD:
    try:
        P.parse_cond(t)
        bad_ok.append(t)
    except ValueError:
        pass
check("  every malformed form errors (missing value, no braces, unclosed, unknown comparison, empty braces, nested)", not bad_ok, bad_ok)
check("  nested braces are reported as nesting", "cannot be nested" in _nest, _nest)
EVALS = [["{ mode != constant }", {"mode": "constant"}, False],
         ["{ mode != constant }", {"mode": "ramp"}, True],
         ["{ a == 1 b == 0 }", {"a": True, "b": False}, True],
         ["{ a == 1 b == 0 }", {"a": True, "b": True}, False],
         ["{ a == 1 } { b == 1 }", {"a": False, "b": True}, True],
         ["{ x == 0 }", {"x": 0.0}, True],
         ["{ x > 2 }", {"x": 10}, True],
         ["{ x < 2 }", {"x": 10}, False],
         ["{ s == '' }", {"s": ""}, True],
         ["{ s == '' }", {"s": "grp"}, False],
         ["{ k == 8 }", {"k": "8"}, True],
         ["{ s == '' }", {"s": "0"}, False]]
res = [P._cond_true(P.parse_cond(t), v) == e for t, v, e in EVALS]
check("evaluation: toggles compare as 1 / 0, numbers numerically (0 == 0.0, 10 > 2 not lexicographic), empty strings, dropdown tokens",
      all(res), [EVALS[i][0] for i, r in enumerate(res) if not r])

# ═══════════════════════════════════════════════════ 4. height estimates
sec("height estimates (used by make_workflows for layout)")
itc = M["PCG_Color"].INPUT_TYPES()
h0 = P.estimate_panel_height("PCG_Color", itc)
h1 = P.estimate_panel_height("PCG_Color", itc, {"mode": "ramp_by_attribute"})
check("Color: 5 rows + separator by default; switching to ramp adds separator + two rows + ramp",
      h0 == P.H["root"] + 5 * P.H["row"] + P.H["sep"] + P.H["extra"]
      and h1 - h0 == P.H["sep"] + 2 * P.H["row"] + P.H["ramp"], (h0, h1))
h2 = P.estimate_panel_height("PCG_Color", itc, linked=["r", "g", "b"])
itt = M["PCG_Transform"].INPUT_TYPES()
check("  wired rows still count (pcg85: the field shows the source, the socket aligns to this row), and wiring doesn't make the node taller",
      h2 == h0 and P.estimate_node_height("PCG_Transform", itt, linked=["tx", "ty", "tz"])
      == P.estimate_node_height("PCG_Transform", itt), (h0, h2))
its = M["PCG_Scatter"].INPUT_TYPES()
hs0 = P.estimate_panel_height("PCG_Scatter", its)
hs1 = P.estimate_panel_height("PCG_Scatter", its, {"use_density": True})
check("a closed section toggle counts only the header; open adds the rows inside (Scatter's Density Attributes: two rows)",
      hs1 - hs0 == P.H["sec_body"] + 2 * P.H["row"], (hs0, hs1))
itg = M["PCG_GroupCreate"].INPUT_TYPES()
check("  tabs: only the current (first) tab counts: GroupCreate's bounding-box section is on the second tab, opening it changes nothing",
      P.estimate_panel_height("PCG_GroupCreate", itg, {"use_bbox": True})
      == P.estimate_panel_height("PCG_GroupCreate", itg))
check("nodes whose panels are taken over = those with parameters, no multi-line code box, not one of the frontend's built-in widgets",
      P.panel_applies("PCG_Color", itc) and not P.panel_applies("PCG_Wrangle", M["PCG_Wrangle"].INPUT_TYPES())
      and not P.panel_applies("PCG_Viewport", M["PCG_Viewport"].INPUT_TYPES())
      and not P.panel_applies("PCG_Merge", M["PCG_Merge"].INPUT_TYPES())
      # pcg104: COP Wrangle has ch_params (custom parameters) and, like the geometry / volume Wrangles, uses native widgets
      and not P.panel_applies("PCG_COPWrangle", M["PCG_COPWrangle"].INPUT_TYPES())
      and not P.panel_applies("PCG_AttribAdjust", M["PCG_AttribAdjust"].INPUT_TYPES())
      and not P.panel_applies("PCG_GeoSpreadsheet", M["PCG_GeoSpreadsheet"].INPUT_TYPES())
      and not P.panel_applies("PCG_Parameters", M["PCG_Parameters"].INPUT_TYPES()))

# ═══════════════════════════════════════════════════ 5. attaching to node classes
sec("annotate / attach_panels")
raw = {"required": {"mode": (["a", "b"], {"default": "a"}), "geo": ("GEOMETRY",)}}
out = P.annotate("PCG_X", raw)
check("options gain a pcg_ui; the original dict is not modified; socket inputs get none",
      out["required"]["mode"][1]["pcg_ui"]["menu"] == {"a": "A", "b": "B"}
      and "pcg_ui" not in raw["required"]["mode"][1] and out["required"]["geo"] == ("GEOMETRY",))
check("  the first parameter carries node-level info _node", "_node" in out["required"]["mode"][1]["pcg_ui"])


class _N:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"x": ("FLOAT", {"default": 1.0})}}


P.attach_panels({"PCG_T": _N})
_f1 = _N.__dict__["INPUT_TYPES"]
P.attach_panels({"PCG_T": _N})
check("attach_panels wraps only once (calling it twice doesn't wrap twice)", "pcg_ui" in _N.INPUT_TYPES()["required"]["x"][1]
      and _N.__dict__["INPUT_TYPES"] is _f1)
check("every node registered by the plugin carries pcg_ui", all(
    any("pcg_ui" in (v[1] if len(v) > 1 and isinstance(v[1], dict) else {})
        for g_ in ("required", "optional") for v in (c.INPUT_TYPES().get(g_) or {}).values())
    for n, c in M.items() if n.startswith("PCG_")
    and any(P._widget_kind(v) for g_ in ("required", "optional")
            for v in (c.INPUT_TYPES().get(g_) or {}).values())))

# ═══════════════════════════════════════════════════ 6. golden reference for the frontend
sec("text widths / tab wrapping (pcg85)")
check("width table has 95 entries (ASCII 32–126), Projectile Properties = 116 px (tab width measured in the real frontend 136 − 20)",
      len(P._GLYPH_W) == 95 and P.text_width("Projectile Properties") == 116)
check("  characters outside the table (Chinese) count as 2 × the average width", P.text_width("中文") == 4 * P.CHAR_W)
# the whole ASCII 32–126 string adds up to 639 px from the table; the real frontend measures the whole string at 631 (kerning makes the whole string slightly narrower;
# the estimate is 1.3% too wide, which only wraps tabs a bit early, never underestimates). The real frontend measures "a~b" at 22; ~ is the last character in the table
all_ascii = P.text_width("".join(map(chr, range(32, 127))))
check("  whole ASCII 32–126 string: table 639 px, real frontend 631 (difference < 1.5%), a~b = 22",
      all_ascii == 639 and abs(all_ascii - 631) / 631 < 0.015 and P.text_width("a~b") == 22)
itb = M["PCG_BallisticPath"].INPUT_TYPES()
hb = P.estimate_panel_height("PCG_BallisticPath", itb)
check("Ballistic Path's three tabs fit on one row (real frontend 149 px; estimating with the average width gives two rows at 174)",
      abs(hb - 149) <= 3, hb)
check("  narrowed to 300 it wraps to two rows (24 px more)",
      P.estimate_panel_height("PCG_BallisticPath", itb, width=300) - hb == 24)

sec("panel_fixture.json (for test_panel.mjs)")
RAMPS = [["0:0,0,1 0.5:0,1,0 1:1,0,0", 3], ["0:0  0.5:0.25  1:1", 1], ["1:1 0:0", 1],
         ["0:0.3", 3], ["0:0 0:1 1:2", 1], ["0.3:0 0.8:1", 1]]
RAMP_BAD = [["", 1], ["0-1", 1], ["0:a", 1], ["0:1,2", 3], ["x:1", 1]]
samples = []
for text, comps in RAMPS:
    pos, val = RAMP.parse(text, comps)
    for mode in ("linear", "smooth", "constant"):
        ts = np.array([-0.2, 0.0, 0.1, 0.25, 0.5, 0.7, 1.0, 1.3])
        v = RAMP.apply(ts, pos, val, mode)
        samples.append([text, comps, mode, ts.tolist(), v.tolist()])
NODES = ["PCG_Color", "PCG_Scatter", "PCG_COPPattern", "PCG_AttribNoise", "PCG_GroupCreate",
         "PCG_COPNoise", "PCG_Transform", "PCG_PolyExtrude", "PCG_COPLight", "PCG_Add",
         "PCG_Measure", "PCG_Wrangle"]


def node_data(n):
    it = M[n].INPUT_TYPES()
    conv = {}
    for g_, dd in it.items():
        conv[g_] = {k: [list(v[0]) if isinstance(v[0], (list, tuple)) else v[0]]
                    + ([v[1]] if len(v) > 1 else []) for k, v in dd.items()}
    return {"name": n, "input": conv}


def model(n):
    ui, specs, top, tabs = P.panel_model(n, M[n].INPUT_TYPES())
    fix = lambda bl: [{"section": s, "gate": g_, "items": i} for s, g_, i in bl]  # noqa: E731
    return {"top": fix(top), "tabs": [{"name": t, "blocks": fix(b)} for t, b in tabs]}


fixture = {
    "conds": [[t, [[list(c) for c in conj] for conj in P.parse_cond(t)]] for t in COND_OK],
    "cond_bad": COND_BAD,
    "evals": EVALS,
    "ramps": [[t, c, [{"p": float(p_), "v": [float(x) for x in v]}
                      for p_, v in zip(*RAMP.parse(t, c))]] for t, c in RAMPS],
    "ramp_bad": RAMP_BAD,
    "samples": samples,
    "nodes": {n: node_data(n) for n in NODES},
    "models": {n: model(n) for n in NODES if P.panel_applies(n, M[n].INPUT_TYPES())},
    "applies": {n: P.panel_applies(n, M[n].INPUT_TYPES()) for n in NODES},
    # width table: the frontend's check for "toggle text doesn't fit in the value column" and the tab-wrap estimate here use the same table
    "glyphs": P._GLYPH_W,
    "widths": {t: P.text_width(t) for t in (
        "Projectile Properties", "Delete Geometry But Keep the Points",
        "Randomize Point Order", "中文", "a~b")},
}
bad_r = []
for t, c in RAMP_BAD:
    try:
        RAMP.parse(t, c)
        bad_r.append(t)
    except ValueError:
        pass
check("every malformed ramp errors on the Python side (the frontend compares the same batch)", not bad_r, bad_r)
path = os.path.join(_R, "panel_fixture.json")
text = json.dumps(fixture, ensure_ascii=False, indent=0)   # not sorted: parameter order matters
prev = open(path, encoding="utf-8").read() if os.path.exists(path) else None
if prev != text:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
check("golden reference written (file left untouched if unchanged)", os.path.exists(path),
      "updated" if prev != text else "unchanged")

sec("reserved widget names (pcg100)")
# a COP node's thumbnail widget is called preview (pcg_cop_preview.js, serialize=false); a parameter also called preview would clash with it:
# the frontend's eligible() looks up pcg_ui by name, takes the thumbnail for that parameter, the types don't match, and the whole node falls back to native widgets.
# pcg100's Chroma Key hit this (found by the e2e test) -- caught early on the Python side here
def _preview_clash(mapping):
    return [n for n, c in mapping.items()
            if any("preview" in (c.INPUT_TYPES().get(g) or {}) for g in ("required", "optional"))]


class _FakeClash:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"preview": ("BOOLEAN", {"default": False})}}


check("no node has a parameter called preview (reserved name of the COP thumbnail widget)", not _preview_clash(M), _preview_clash(M))
check("  negative control: insert a parameter called preview -> detected",
      _preview_clash(dict(M, PCG_FakeClash=_FakeClash)) == ["PCG_FakeClash"])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
