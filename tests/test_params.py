"""
Declaration parsing of the parameter panel (Python side).

━━ The most important rule here: **check against the same golden table as the JS implementation**
The panel "grows controls from the declaration" in the frontend, so `parse()` must have two implementations (one in Python,
one in `web/pcg_params.js`). Two implementations drift, and drift is extremely hard to recognize: the declaration looks fine,
yet the panel has one extra parameter or a slightly different default, with no error at all.

So the corpus and the expected results live in **one file** (`params_golden.json`), and each side compares against it:
  · change the Python parsing -> this suite goes red
  · change the JS parsing     -> test_params.mjs goes red
  · to change behaviour you must change both sides **and** the table; missing any one of them goes red

This beats "each test writes its own expected values": with that, you change one side, casually update that side's
expected values, and the two sides silently part ways while every test stays green.

━━ The other rules
  · duplicate parameter names are **an error**, not later-overrides-earlier -- the panel would show two same-named controls,
    only one of which takes effect; this kind of "I changed it and nothing happened" is the hardest to track down
  · after a type change, the stored old value **falls back to the default** instead of being forced -- cramming a scalar into a three-component
    control would only produce a confusing state
  · errors must carry the **line number**: the declaration is multi-line text, and without a line number people have to count from the top
"""
import json
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg import params as PM                     # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

OK = []
GOLDEN = os.path.join(_R, "params_golden.json")


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "no error raised")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:100]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


# ═══════════════════════════════════════════════ 1. Golden reference (cross-language)
sec("Golden table (the JS implementation checks against the same table)")
check("golden table exists", os.path.isfile(GOLDEN), GOLDEN)
gold = json.load(open(GOLDEN, encoding="utf-8"))
check("  table has two groups: valid corpus and corpus that must raise",
      len(gold["ok"]) >= 12 and len(gold["bad"]) >= 8,
      f"{len(gold['ok'])} / {len(gold['bad'])}")

bad_ones = []
for case in gold["ok"]:
    got = PM.parse(case["src"])
    if got != case["specs"]:
        bad_ones.append((case["src"], got, case["specs"]))
check(f"{len(gold['ok'])} valid declarations parse **exactly** like the golden reference",
      not bad_ones, bad_ones[:1])

still_ok = []
for src in gold["bad"]:
    try:
        PM.parse(src)
        still_ok.append(src)
    except ValueError:
        pass
check(f"{len(gold['bad'])} invalid declarations **all** raise ValueError",
      not still_ok, still_ok)

# The golden table itself needs coverage -- an all-green table that only tests float proves nothing
kinds = {s["type"] for c in gold["ok"] for s in c["specs"]}
check("  table covers all six types", kinds == set(PM.TYPES), sorted(kinds))
check("  also covers ranges, labels, comment lines, multi-line, short forms",
      any(s["min"] is not None for c in gold["ok"] for s in c["specs"])
      and any(s["label"] for c in gold["ok"] for s in c["specs"])
      and any(len(c["specs"]) > 3 for c in gold["ok"]))


# ══════════════════════════════════════════════════ 2. Parsing details
sec("Parsing")
one = PM.parse("float radius = 1.0 : 0 10 # radius")[0]
check("type / name / default / range / label are all parsed",
      (one["type"], one["name"], one["default"], one["min"], one["max"],
       one["label"]) == ("float", "radius", 1.0, 0.0, 10.0, "radius"))
check("default can be omitted (gives the type's zero value)",
      PM.parse("float a")[0]["default"] == 0.0
      and PM.parse("string s")[0]["default"] == ""
      and PM.parse("bool b")[0]["default"] is False
      and PM.parse("vector v")[0]["default"] == [0.0, 0.0, 0.0])
check("range can be omitted", PM.parse("float a = 1")[0]["min"] is None)
check("int default and range are both rounded",
      PM.parse("int a = 2.7 : 0.2 9.8")[0]["default"] == 3
      and PM.parse("int a = 2.7 : 0.2 9.8")[0]["min"] == 0)
check("string default may contain spaces",
      PM.parse("string s = a b  c")[0]["default"] == "a b  c")
check("  quotes are optional, and stripped when present",
      PM.parse('string s = "a b"')[0]["default"] == "a b")
check("vector with a single number fills every component",
      PM.parse("vector v = 2")[0]["default"] == [2.0, 2.0, 2.0]
      and PM.parse("vector4 v = 2")[0]["default"] == [2.0] * 4)
check("  commas and spaces both work as separators",
      PM.parse("vector v = 1,2,3")[0]["default"] == [1.0, 2.0, 3.0])
check("bool accepts true/false/1/0/on/off/yes/no",
      [PM.parse(f"bool b = {t}")[0]["default"]
       for t in ("true", "TRUE", "1", "on", "yes", "false", "0", "off")]
      == [True, True, True, True, True, False, False, False])
check("type short forms are all accepted (f/i/b/s/v/vec3/v4)",
      [PM.parse(f"{t} a")[0]["type"] for t in
       ("f", "i", "b", "s", "v", "vec3", "v4")]
      == ["float", "int", "bool", "string", "vector", "vector", "vector4"])
check("types are case-insensitive", PM.parse("FLOAT a")[0]["type"] == "float")
check("blank lines / # comment lines / // comment lines are all skipped",
      PM.parse("\n# x\n// y\n\nfloat a\n") == PM.parse("float a"))
check("one per line, order preserved",
      [s["name"] for s in PM.parse("float a\nint b\nbool c")] == ["a", "b", "c"])
check("empty text parses to an empty list (no error)", PM.parse("") == []
      and PM.parse(None) == [])

err("unparseable line: error has the line number and syntax",
    lambda: PM.parse("float a\nthis is wrong\n"), "line 2")
err("unknown type lists the valid ones",
    lambda: PM.parse("flooat a"), "unknown")
err("invalid name explains the rule",
    lambda: PM.parse("float 1a = 1"), "invalid")
err("**duplicate name is an error**, and says which line it duplicates",
    lambda: PM.parse("float a\nint b\nfloat a"), "duplicates line 1")
err("default is not a number",
    lambda: PM.parse("float a = x"), "is not a number")
err("wrong vector component count",
    lambda: PM.parse("vector v = 1 2"), "expected 3")
err("range with a single number",
    lambda: PM.parse("float a : 1"), "two numbers")
err("reversed range",
    lambda: PM.parse("float a : 5 1"), "range is reversed")
err("bool / string should have no range",
    lambda: PM.parse("bool b : 0 1"), "cannot have a range")
err("bad bool default",
    lambda: PM.parse("bool b = maybe"), "must be")
for bad, frag in (("float a\nfloat 2b = 1", "line 2"),
                  ("float a\n\n\nvector v = 1 2", "line 4")):
    err(f"line numbers are **source line numbers** (blank lines and comments are not renumbered): {frag}",
        lambda b=bad: PM.parse(b), frag)


# ══════════════════════════════════════════════════ 3. Merging values
sec("declaration + saved values -> current values")
specs = PM.parse("float a = 1\nint b = 2\nbool c = true\n"
                 "string d = x\nvector e = 1 2 3")
check("empty saved values: all defaults",
      PM.merge(specs, {}) == {"a": 1.0, "b": 2, "c": True, "d": "x",
                              "e": [1.0, 2.0, 3.0]})
check("saved values are used when present",
      PM.merge(specs, {"a": 7.5, "d": "y"})["a"] == 7.5
      and PM.merge(specs, {"a": 7.5, "d": "y"})["d"] == "y")
check("**type mismatch falls back to the default** (a parameter whose type changed leaves no confusing value)",
      PM.merge(specs, {"a": "not a number", "e": 5})["a"] == 1.0
      and PM.merge(specs, {"e": 5})["e"] == [1.0, 2.0, 3.0])
check("  a changed component count also falls back to the default",
      PM.merge(PM.parse("vector4 e = 1 1 1 1"), {"e": [1, 2, 3]})["e"]
      == [1.0, 1.0, 1.0, 1.0])
check("  bool is not fooled by a string",
      PM.merge(specs, {"c": "true"})["c"] is True)
check("keys not in the declaration are dropped (old values don't linger after a rename)",
      "zzz" not in PM.merge(specs, {"zzz": 1}))
check("saved values that are not a dict don't blow up", PM.merge(specs, None) == PM.defaults(specs)
      and PM.merge(specs, "junk") == PM.defaults(specs))
check("saved int values are rounded and clamped into range",
      PM.merge(PM.parse("int b = 2 : 0 10"), {"b": 99})["b"] == 10
      and PM.merge(PM.parse("int b = 2 : 0 10"), {"b": 3.6})["b"] == 4)


# ══════════════════════════════════════════════════ 4. References
sec("References")
check("bare name", PM.split_ref("radius") == ("radius", None))
check("dot components x/y/z/w",
      [PM.split_ref(f"p.{c}")[1] for c in "xyzw"] == [0, 1, 2, 3])
check("  color names r/g/b/a are accepted too",
      [PM.split_ref(f"p.{c}")[1] for c in ("r", "g", "b", "a")] == [0, 1, 2, 3])
check("  numeric indices and square brackets are accepted too",
      PM.split_ref("p.2") == ("p", 2) and PM.split_ref("p[3]") == ("p", 3))
check("  case-insensitive", PM.split_ref("p.Y")[1] == 1)
vals = PM.merge(specs, {})
check("value_of gets a scalar", PM.value_of(vals, specs, "a") == 1.0)
check("value_of gets a component", PM.value_of(vals, specs, "e.z") == 3.0)
err("missing name lists the existing ones",
    lambda: PM.value_of(vals, specs, "nope"), "Existing")
err("unknown component name", lambda: PM.split_ref("p.q"), "unknown")
err("taking a component of a scalar is explained",
    lambda: PM.value_of(vals, specs, "a.x"), "is not a vector")
err("component out of range", lambda: PM.value_of(vals, specs, "e.w"), "component")
err("empty reference", lambda: PM.split_ref("  "), "empty")


# ══════════════════════════════════════════════════ 5. Node
sec("Node")
node = MAP["PCG_Parameters"]()
res = node.run("float a = 1.5\nvector v = 1 2 3", '{"a": 9}')
out = tuple(res.get("result", ())) if isinstance(res, dict) else res
check("outputs two strings: json + schema",
      len(out) == 2 and all(isinstance(x, str) for x in out))
got = json.loads(out[0])
check("  saved values take precedence, defaults otherwise",
      got == {"a": 9.0, "v": [1.0, 2.0, 3.0]}, got)
check("  keys are sorted (same parameters always give the same string, so the cache is stable)",
      out[0].index('"a"') < out[0].index('"v"'))
err("malformed declaration: error has the line number",
    lambda: node.run("float a\nbad line", "{}"), "line 2")
err("values that are not valid JSON are explained",
    lambda: node.run("float a", "{not json"), "not valid JSON")
check("empty values string is treated as empty saved values",
      json.loads((lambda r: tuple(r.get("result", ()))
                  if isinstance(r, dict) else r)(node.run("float a = 2", ""))
                 [0]) == {"a": 2.0})

spec_in = MAP["PCG_Parameters"].INPUT_TYPES()["required"]
check("declare is multi-line text", spec_in["declare"][1].get("multiline") is True)
check("  has the param_decl marker (the frontend recognizes it by this, not by name)",
      spec_in["declare"][1].get("param_decl") is True)
check("values has the param_store marker (the frontend hides it as a carrier)",
      spec_in["values"][1].get("param_store") is True)
check("only two widgets -- parameters themselves are not widgets, so there is no index drift",
      len(spec_in) == 2, list(spec_in))
check("under the PCG/param category",
      MAP["PCG_Parameters"].CATEGORY == "PCG/param")
check("node is registered in the package", "PCG_Parameters" in MAP)


# ══════════════════════════════════════════════════ 6. schema
#
# The schema is **the prerequisite for the model getting key names right**. Without it the model can only guess ("radius" or
# "size"?), and wrongly guessed keys are silently ignored -- the symptom is "the model's answer looks plausible, yet not a single parameter
# in the graph changed". So pin it down here: every declared parameter is present, ranges too.
sec("schema -- the one shown to the model")
SP = PM.parse("float radius = 1.0 : 0 10   # radius\n"
              "int   count  = 5\n"
              "bool  cap    = true\n"
              "string pre   = piece\n"
              "vector pos   = 0 1 2\n")
sch = PM.schema(SP)
check("every declared parameter is in the schema",
      sorted(sch) == ["cap", "count", "pos", "pre", "radius"], sorted(sch))
check("  type names are the declared type names",
      [sch[k]["type"] for k in ("radius", "count", "cap", "pre", "pos")]
      == ["float", "int", "bool", "string", "vector"])
check("  defaults included (the model can change only the ones it wants)",
      sch["pos"]["default"] == [0.0, 1.0, 2.0], sch["pos"])
check("  ranges written out where present", (sch["radius"]["min"], sch["radius"]["max"])
      == (0.0, 10.0))
check("  no min/max without a range (don't let the model think there is a constraint)",
      "min" not in sch["count"] and "max" not in sch["count"])
check("  vectors state their component count", sch["pos"].get("components") == 3)
check("  scalars have no components", "components" not in sch["radius"])
check("  label written out (it is for humans, and also semantics for the model)",
      sch["radius"].get("label") == "radius")
check("  no empty label when there is none", "label" not in sch["count"])
check("schema passes json.dumps (it gets pasted into the prompt)",
      isinstance(json.dumps(sch, ensure_ascii=False), str))
check("empty declaration -> empty schema", PM.schema([]) == {})
# Negative control: the schema must **not** contain anything outside the declaration, otherwise the model would fill in a nonexistent key
check("negative control: schema keys are exactly the names from parse",
      set(sch) == {s["name"] for s in SP})

node2 = MAP["PCG_Parameters"]()
r2 = node2.run("float radius = 1 : 0 10", "{}")
sch2 = json.loads(tuple(r2.get("result", ()))[1]
                  if isinstance(r2, dict) else r2[1])
check("the panel node's second output is this schema",
      sch2 == {"radius": {"type": "float", "default": 1.0,
                          "min": 0.0, "max": 10.0}}, sch2)
check("  RETURN_NAMES is (json, schema)",
      MAP["PCG_Parameters"].RETURN_NAMES == ("json", "schema"))


# ══════════════════════════════════════════════════ 7. apply_values
#
# **This is the entire boundary through which AI can touch this graph.** It is structural, not enforced through the prompt,
# so every boundary needs a test, and every one needs a **negative control** -- proving "what should not happen"
# really did not happen: keys outside the declaration did not become new parameters, wrong types did not wipe the original value.
#
# Equally important: **all three lists must be reported**. Silently ignoring half the keys is the most common pitfall of this kind of
# feature -- the model's answer looks convincing, only half the graph changed, and you think it filled in everything.
sec("apply_values -- the model can only fill in declared parameters")
CUR = PM.defaults(SP)
nv, rep = PM.apply_values(SP, CUR, {"radius": 3.5, "count": 9})
check("values filled in", (nv["radius"], nv["count"]) == (3.5, 9), (nv["radius"],
                                                            nv["count"]))
check("  applied is listed", rep["applied"] == ["count", "radius"],
      rep["applied"])
check("parameters not mentioned are left untouched",
      nv["pre"] == "piece" and nv["pos"] == [0.0, 1.0, 2.0])

nv, rep = PM.apply_values(SP, CUR, {"nope": 1, "radius": 2})
check("keys not in the declaration -> unknown", rep["unknown"] == ["nope"], rep)
check("  negative control: **no** extra parameter appeared because of it",
      "nope" not in nv and sorted(nv) == sorted(CUR), sorted(nv))
check("  valid keys in the same call are still filled in", nv["radius"] == 2.0)

nv, rep = PM.apply_values(SP, CUR, {"radius": "a bit bigger"})
check("unrescuable type -> skipped", rep["skipped"] == ["radius"], rep)
check("  negative control: original value **not wiped**", nv["radius"] == 1.0, nv["radius"])
check("  not in applied", rep["applied"] == [])

nv, rep = PM.apply_values(SP, CUR, {"radius": "3.5"})
check("numbers written as strings can be rescued (models love doing this)", nv["radius"] == 3.5)
check("  rescued ones count as applied, not skipped",
      rep["applied"] == ["radius"] and rep["skipped"] == [])
for bad in ("inf", "-inf", "nan", "NaN", "Infinity", ""):
    nv, rep = PM.apply_values(SP, CUR, {"radius": bad})
    check(f"  but '{bad}' counts as unrescuable (it would end up as nan vertices)",
          rep["skipped"] == ["radius"] and nv["radius"] == 1.0, rep)

nv, rep = PM.apply_values(SP, CUR, {"radius": 999})
check("out of range -> clamped", nv["radius"] == 10.0, nv["radius"])
check("  and recorded in clamped (otherwise it is silent truncation)",
      rep["clamped"] == ["radius"] and rep["applied"] == ["radius"], rep)
nv, rep = PM.apply_values(SP, CUR, {"radius": -5})
check("  lower bound clamped too", nv["radius"] == 0.0 and rep["clamped"] == ["radius"])
nv, rep = PM.apply_values(SP, CUR, {"radius": 10})
check("  negative control: exactly on the boundary is not clamped",
      rep["clamped"] == [] and nv["radius"] == 10.0, rep)
nv, rep = PM.apply_values(SP, CUR, {"count": 9.7})
check("negative control: int rounding is **not** clamped (it is not a range issue)",
      nv["count"] == 10 and rep["clamped"] == [], rep)
SPI = PM.parse("int n = 5 : 0 100")
nv, rep = PM.apply_values(SPI, {"n": 5}, {"n": 9.7})
check("  rounding a ranged int is not clamped either -- this one used to be wrong",
      nv["n"] == 10 and rep["clamped"] == [], rep)
nv, rep = PM.apply_values(SPI, {"n": 5}, {"n": 500})
check("  a ranged int counts only when truly out of range", nv["n"] == 100
      and rep["clamped"] == ["n"], rep)

nv, rep = PM.apply_values(SP, CUR, {"cap": 0})
check("bool receiving a number -> False", nv["cap"] is False and rep["applied"] == ["cap"])
nv, rep = PM.apply_values(SP, CUR, {"cap": "1"})
check("bool receiving '1' -> True", nv["cap"] is True, nv["cap"])
nv, rep = PM.apply_values(SP, CUR, {"cap": "yes"})
check("bool receiving 'yes' -> unrescuable (float('yes') just fails, reporting beats guessing)",
      rep["skipped"] == ["cap"], rep)

nv, rep = PM.apply_values(SP, CUR, {"pos": [4, 5, 6]})
check("vector filled as a whole", nv["pos"] == [4.0, 5.0, 6.0], nv["pos"])
nv, rep = PM.apply_values(SP, CUR, {"pos": 7})
check("vector receiving one number -> fills every component", nv["pos"] == [7.0, 7.0, 7.0], nv["pos"])
nv, rep = PM.apply_values(SP, CUR, {"pos": [1, 2]})
check("wrong vector component count -> skipped (no guessing the third)",
      rep["skipped"] == ["pos"] and nv["pos"] == [0.0, 1.0, 2.0], rep)
SPV = PM.parse("vector v = 0 0 0 : -1 1")
nv, rep = PM.apply_values(SPV, {"v": [0, 0, 0]}, {"v": [5, 0, -5]})
check("vector components are clamped too (the frontend puts the same min/max on every component)",
      nv["v"] == [1.0, 0.0, -1.0], nv["v"])
check("  and recorded in clamped", rep["clamped"] == ["v"], rep)

nv, rep = PM.apply_values(SP, CUR, {"pre": "rock"})
check("string filled in", nv["pre"] == "rock")
nv, rep = PM.apply_values(SP, CUR, {"pre": 5})
check("string parameter receiving a number -> skipped (no silent str())",
      rep["skipped"] == ["pre"] and nv["pre"] == "piece", rep)

nv, rep = PM.apply_values(SP, CUR, {})
check("empty object -> nothing changes",
      nv == CUR and not any(rep[k] for k in rep), rep)
err("non-object input: error says what shape is expected",
    lambda: PM.apply_values(SP, CUR, [1, 2]), "JSON object")
nv, rep = PM.apply_values(SP, CUR, {"  radius  ": 4})
check("whitespace around keys is trimmed (model formatting adds spaces)", nv["radius"] == 4.0)
nv, rep = PM.apply_values(SP, CUR,
                          {"radius": 99, "count": 2, "zzz": 1, "pre": 5})
check("all four lists can appear at once (none may be missed when mixed)",
      (rep["applied"], rep["clamped"], rep["unknown"], rep["skipped"])
      == (["count", "radius"], ["radius"], ["zzz"], ["pre"]), rep)
check("  lists are sorted (stable report text, readable diffs)",
      all(rep[k] == sorted(rep[k]) for k in rep))
check("negative control: apply_values does **not touch** the current passed in (pure function)",
      CUR == PM.defaults(SP), CUR)
check("apply_values' result can be fed straight back into merge as saved values",
      PM.merge(SP, PM.apply_values(SP, CUR, {"radius": 3})[0])["radius"]
      == 3.0)


# ══════════════════════════════════════════════════ 8. Params from JSON
sec("Params from JSON node")
pj = MAP["PCG_ParamsFromJSON"]()
r = pj.run('{"radius": 2.5, "count": 12}', True)
check("returns the {ui, result} pair", isinstance(r, dict)
      and "ui" in r and "result" in r)
pay = r["ui"]["pcg_params_apply"][0]
check("  ui carries the cleanly parsed values",
      pay["values"] == {"radius": 2.5, "count": 12}, pay["values"])
check("  also carries 'what was repaired' (otherwise messy input is silently fixed)",
      isinstance(pay.get("parse"), str) and pay["parse"])
check("  result's applied is the key count", r["result"][1] == 2)
check("is OUTPUT_NODE -- must run even with nothing downstream, otherwise ui is never sent",
      MAP["PCG_ParamsFromJSON"].OUTPUT_NODE is True)

r = pj.run('Here you go:\n```json\n{"radius": 2.5,}\n```', True)
check("messy input gets through (fence + preamble + trailing comma)",
      r["ui"]["pcg_params_apply"][0]["values"] == {"radius": 2.5})
check("  what was repaired is written into report", "```" in r["result"][2], r["result"][2])
r = pj.run('[{"radius": 1}]', True)
check("model wrapped it in an array -> take the first object",
      r["ui"]["pcg_params_apply"][0]["values"] == {"radius": 1})
check("  and say so clearly in the report", "array" in r["result"][2], r["result"][2])
err("parsed result is not an object: error says what shape is expected",
    lambda: pj.run("42", True), "JSON object")
r = pj.run('{"radius": 2.5}', False)
check("when disabled, no ui is sent (otherwise toggling off and on would still change the panel)",
      not r["ui"] and r["result"][1] == 0, r)
check("  and says it was disabled, not that nothing was parsed",
      "disabled" in r["result"][2], r["result"][2])
check("under the PCG/param category",
      MAP["PCG_ParamsFromJSON"].CATEGORY == "PCG/param")


# ══════════════════════════════════════════════════ 9. Param Pick
sec("Param Pick node")
pk = MAP["PCG_ParamPick"]()
check("gets a scalar", pk.run('{"radius": 2.5}', "radius", False, 0.0)[:2]
      == (2.5, 2))
check("  int is rounded, not truncated",
      pk.run('{"a": 2.6}', "a", False, 0.0)[1] == 3)
check("gets nested a.b", pk.run('{"a": {"b": 7}}', "a.b", False, 0.0)[0] == 7.0)
check("gets vector component pos.y",
      pk.run('{"pos": [1, 2, 3]}', "pos.y", False, 0.0)[0] == 2.0)
check("  the rgb aliases are accepted too",
      pk.run('{"c": [1, 2, 3]}', "c.g", False, 0.0)[0] == 2.0)
check("whole vector -> string output is JSON",
      json.loads(pk.run('{"p": [1, 2]}', "p", False, 0.0)[2]) == [1, 2])
check("bool -> 1/0", pk.run('{"b": true}', "b", False, 0.0)[0] == 1.0)
check("numbers inside strings are accepted too",
      pk.run('{"a": "3.5"}', "a", False, 0.0)[0] == 3.5)
check("  string output kept as is",
      pk.run('{"a": "hi"}', "a", False, 0.0)[2] == "hi")
err("missing key **raises** instead of giving 0", lambda: pk.run('{}', "radius", False, 0.0),
    "radius", KeyError)
try:                     # str() of a KeyError is the repr, quotes get escaped -- look at args
    pk.run('{"a": 1, "b": 2}', "zz", False, 0.0)
    check("  error lists what this level has (otherwise you can only guess key names)", False, "no error raised")
except KeyError as ex:
    msg = ex.args[0]
    check("  error lists what this level has (otherwise you can only guess key names)",
          "'a'" in msg and "'b'" in msg, msg)
check("negative control: fallback only applies when turned on",
      pk.run('{}', "radius", True, 8.0)[0] == 8.0)
check("  fallback also goes through the int/string outputs",
      pk.run('{}', "radius", True, 8.0)[:2] == (8.0, 8))
err("empty name also raises (an empty name returning the whole JSON would only be harder to debug)",
    lambda: pk.run('{"a": 1}', "  ", False, 0.0), "", KeyError)
check("under the PCG/param category",
      MAP["PCG_ParamPick"].CATEGORY == "PCG/param")
check("all three nodes are registered in the package",
      all(k in MAP for k in ("PCG_Parameters", "PCG_ParamsFromJSON",
                             "PCG_ParamPick")))


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
