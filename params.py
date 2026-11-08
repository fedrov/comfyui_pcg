"""
Parameter panel -- the equivalent of adding a bunch of spare parameters to a Houdini null and referencing them with `ch()`.

Once a graph gets big, the real pain is not "some parameter is hard to tweak", it is **the same quantity scattered across a dozen nodes**:
radius, density, seed, piece count... every change means hunting them down one by one. Houdini's approach is to build
a set of parameters on a null and reference them elsewhere with `ch("../ctrl/radius")`, so that null becomes the
control panel of the whole graph.

This module does the same thing, but has to work around two hard constraints of ComfyUI.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Constraint 1: widgets can only be appended, never inserted -- so parameters are a **text declaration**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When litegraph restores a workflow it maps widgets_values back onto the widget array **by index**. Adding or removing
widgets dynamically shifts every parameter after it, without any error -- values silently get mixed up. That is why
`PCG_Add`'s polygon list, `ramp.py`'s ramp curve and `channel.py`'s keyframes are all text.

So the parameters are a piece of **declaration text**:

    float  radius = 1.0 : 0 10   # radius
    int    count  = 5   : 1 100
    bool   cap    = true
    string prefix = piece
    vector pos    = 0 0 0
    vector4 col   = 1 1 1 1

The frontend **appends** real ComfyUI widgets (number / text / toggle) according to this text,
and all values are serialized into one fixed JSON-string widget -- the same mechanism as Wrangle's `ch()` parameters
(`pcg_wrangle.js` has already shipped it in two batches), so existing values are not lost when parameters are added or removed.

The side benefit is the same as elsewhere: the text can be copy-pasted, put under version control, and diffs are readable.
In Houdini, moving a set of spare parameters from one HDA to another is actually quite a hassle.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Constraint 2: ComfyUI's cache is keyed on an input hash -- so references are **materialized in the frontend**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Houdini's `ch()` works because its dependency graph explicitly tracks parameter references. ComfyUI has no such
mechanism: if a node reads a value from elsewhere without an edge in the graph, the cache cannot see the dependency -- either the whole graph
recooks, or what should recook does not.

So a binding is not "read at runtime"; instead **the frontend writes the value straight into the target widget** (see
`web/pcg_params.js`). Once written, the hash of the submitted prompt is naturally correct, and invalidation is
**fine-grained**: changing `radius` recooks only the few nodes that reference radius, everything else keeps reusing
the cache. Wires cannot do this -- with wires every consuming node hangs off the same upstream,
so touching one parameter invalidates all of them.

Writing values into other nodes' widgets has already shipped in two batches in this plugin: the playbar writes `PCG_Frame`,
and the 3D panel's camera lock writes `PCG_Camera`.

The cost, stated plainly: **bindings are a frontend thing**. Running the same workflow via API / headless does not
re-evaluate them; it uses the values last materialized into widgets_values. For "tune the parameters, then batch-render"
this makes no difference (the values are fixed anyway), but if you expect parameter linkage to react to changes on the server, this route does not work.
"""
from __future__ import annotations

import json
import math

TYPES = ("float", "int", "bool", "string", "vector", "vector4")
NCOMP = {"float": 1, "int": 1, "bool": 1, "string": 1,
         "vector": 3, "vector4": 4}
_ALIAS = {
    "f": "float", "float": "float",
    "i": "int", "int": "int",
    "b": "bool", "bool": "bool", "toggle": "bool",
    "s": "string", "str": "string", "string": "string",
    "v": "vector", "vec": "vector", "vector": "vector", "vector3": "vector",
    "v3": "vector", "vec3": "vector",
    "v4": "vector4", "vec4": "vector4", "vector4": "vector4",
}
_TRUE = {"1", "true", "yes", "on", "t"}
_FALSE = {"0", "false", "no", "off", "f"}
COMPONENTS = {"x": 0, "y": 1, "z": 2, "w": 3,
              "r": 0, "g": 1, "b": 2, "a": 3,
              "0": 0, "1": 1, "2": 2, "3": 3}

EXAMPLE = "float radius = 1.0 : 0 10   # radius"


def _num(tok, line_no, what):
    try:
        return float(tok)
    except ValueError:
        raise ValueError(f"line {line_no}: {what} '{tok}' is not a number. "
                         f"Syntax: {EXAMPLE}")


def _ident(name, line_no):
    if not name or not (name[0].isalpha() or name[0] == "_") \
            or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(
            f"line {line_no}: parameter name '{name}' is invalid -- only letters, digits and "
            f"underscores are allowed, and it cannot start with a digit. Syntax: {EXAMPLE}")
    return name


def _quoted_span(line):
    """
    Position [start, end) of the quoted default value in this line -- # and : inside it are not separators
    (`string dir = "C:/out#1"`). Only counts when "the first = is directly followed by a quote, and the quote has a match";
    other spellings (no quotes, unmatched quotes) behave exactly as before; when # or : comes before =, the first # / : is
    outside this span anyway and is still found first.
    **Matches quotedSpan in web/pcg_params.js.**
    """
    e = line.find("=")
    if e < 0:
        return None
    i = e + 1
    while i < len(line) and line[i].isspace():
        i += 1
    if i >= len(line) or line[i] not in "\"'":
        return None
    j = line.find(line[i], i + 1)
    return None if j < 0 else (i, j + 1)


def _find_outside(line, ch, span):
    i = line.find(ch)
    if span and span[0] <= i < span[1]:
        i = line.find(ch, span[1])
    return i


def parse(text):
    """
    declaration text -> [{type, name, default, min, max, label, n}, ...]

    One parameter per line:

        <type> <name> [= default] [: min max] [# label]

    Both the `=` and `:` parts are optional. A string default may contain spaces (up to the #),
    a vector default is space- or comma-separated components.

    Duplicate names are **an error** rather than the later one overriding the earlier one: duplicated parameters look like two
    independent controls on the panel, but only one of them takes effect -- this kind of "I changed it and nothing happened" is the hardest to track down.
    """
    out, seen = [], {}
    for i, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        label = ""
        span = _quoted_span(line)
        h = _find_outside(line, "#", span)
        if h >= 0:
            line, label = line[:h], line[h + 1:].strip()
        rng = ""
        c = _find_outside(line, ":", span)
        if c >= 0:
            line, rng = line[:c], line[c + 1:]
        dflt = None
        if "=" in line:
            line, _, dflt = line.partition("=")
            dflt = dflt.strip()
        head = line.split()
        if len(head) != 2:
            raise ValueError(
                f"line {i}: cannot understand '{raw.strip()}'. "
                f"Write each line as <type> <name> [= default] [: min max] [# label]. "
                f"Example: {EXAMPLE}")
        kind = _ALIAS.get(head[0].lower())
        if kind is None:
            raise ValueError(
                f"line {i}: unknown type '{head[0]}'. Valid: {TYPES}"
                f" (the short forms f/i/b/s/vec/vec4 are accepted too)")
        name = _ident(head[1], i)
        if name in seen:
            raise ValueError(
                f"line {i}: parameter name '{name}' duplicates line {seen[name]}. "
                f"Only one of two same-named controls would take effect, so it is rejected here.")
        seen[name] = i

        n = NCOMP[kind]
        if kind == "string":
            v = "" if dflt is None else dflt
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]                      # quotes are optional
        elif kind == "bool":
            s = (dflt or "false").strip().lower()
            if s not in _TRUE and s not in _FALSE:
                raise ValueError(
                    f"line {i}: bool default '{dflt}' must be "
                    f"true/false (1/0, on/off accepted too)")
            v = s in _TRUE
        elif n > 1:
            toks = (dflt or "").replace(",", " ").split()
            if not toks:
                v = [0.0] * n
            else:
                if len(toks) == 1:
                    toks = toks * n              # a single number fills every component
                if len(toks) != n:
                    raise ValueError(
                        f"line {i}: {kind} default has {len(toks)} components, "
                        f"expected {n}")
                v = [_num(t, i, "default value") for t in toks]
        else:
            v = 0.0 if dflt is None or dflt == "" else _num(dflt, i, "default value")
            if kind == "int":
                v = int(round(v))

        lo = hi = None
        if rng.strip():
            parts = rng.replace(",", " ").split()
            if len(parts) != 2:
                raise ValueError(
                    f"line {i}: range must be written as ': min max' (two numbers), "
                    f"got '{rng.strip()}'")
            lo, hi = (_num(parts[0], i, "range min"),
                      _num(parts[1], i, "range max"))
            if lo > hi:
                raise ValueError(f"line {i}: range is reversed: {lo} > {hi}")
            if kind in ("bool", "string"):
                raise ValueError(f"line {i}: a {kind} parameter cannot have a range")
            if kind == "int":
                lo, hi = int(round(lo)), int(round(hi))
        out.append({"type": kind, "name": name, "default": v,
                    "min": lo, "max": hi, "label": label, "n": n})
    return out


def defaults(specs):
    """declaration -> {name: default}."""
    return {s["name"]: s["default"] for s in specs}


def merge(specs, stored):
    """
    declaration + stored values -> {name: current value}.

    Stored values are used when present, defaults otherwise; **on a type mismatch fall back to the default** instead of forcing a conversion --
    after changing a parameter from float to vector, cramming the stored scalar into a three-component control would only produce
    a confusing state.
    """
    vals = {}
    try:
        stored = dict(stored or {})
    except Exception:
        stored = {}
    for s in specs:
        v = stored.get(s["name"], None)
        vals[s["name"]] = s["default"] if not _fits(s, v) else _coerce(s, v)
    return vals


def _fits(spec, v):
    if v is None:
        return False
    if spec["type"] == "string":
        return isinstance(v, str)
    if spec["type"] == "bool":
        return isinstance(v, (bool, int, float)) and not isinstance(v, str)
    if spec["n"] > 1:
        return isinstance(v, (list, tuple)) and len(v) == spec["n"] \
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in v)
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _clamp(spec, x):
    if spec["min"] is None:
        return float(x)
    return max(float(spec["min"]), min(float(spec["max"]), float(x)))


def _coerce(spec, v):
    t = spec["type"]
    if t == "string":
        return str(v)
    if t == "bool":
        return bool(v)
    # Vector components are clamped too -- the frontend applies the same min/max to every component widget;
    # without clamping here, "dragging by hand tops out at 1.0, but a model filling in 5.0 really gets 5.0" -- one declaration, two
    # behaviours. This inconsistency was found while writing the apply_values tests
    if spec["n"] > 1:
        return [_clamp(spec, x) for x in v]
    x = _clamp(spec, v)
    return int(round(x)) if t == "int" else x


def _out_of_range(spec, v):
    """Whether the value (before rounding) is outside the declared range. **Rounding is not a clamp.**

    Simply comparing before/after `_coerce` does not work: an int parameter receiving 3.7 gets rounded to 4, before != after,
    and the report gains a bogus clamped entry. Only checking the range itself gives the right answer.
    """
    if spec["min"] is None:
        return False
    lo, hi = float(spec["min"]), float(spec["max"])
    xs = list(v) if isinstance(v, (list, tuple)) else [v]
    try:
        return any(float(x) < lo or float(x) > hi for x in xs)
    except (TypeError, ValueError):
        return False


def split_ref(ref):
    """
    "pos.y" -> ("pos", 1); "radius" -> ("radius", None); "pos[2]" -> ("pos", 2).

    Component names x/y/z/w, r/g/b/a and 0/1/2/3 are all accepted -- the same vector is named differently
    in different contexts (xyz for positions, rgb for colors), and remembering the wrong set would fail to fetch the value.
    """
    s = str(ref or "").strip()
    if not s:
        raise ValueError("reference is empty")
    if s.endswith("]") and "[" in s:
        name, _, idx = s[:-1].partition("[")
        key = idx.strip()
    elif "." in s:
        name, _, key = s.partition(".")
    else:
        return s, None
    name = name.strip()
    key = key.strip().lower()
    if key not in COMPONENTS:
        raise ValueError(
            f"reference '{ref}': unknown component '{key}' -- must be x/y/z/w, "
            f"r/g/b/a or 0/1/2/3")
    return name, COMPONENTS[key]


def value_of(values, specs, ref):
    """Look up a value by reference. When it fails, the error must say whether the name or the component was wrong."""
    name, comp = split_ref(ref)
    if name not in values:
        have = ", ".join(sorted(values)) or "(the panel has no parameters at all)"
        raise KeyError(f"no '{name}' on the parameter panel. Existing: {have}")
    v = values[name]
    if comp is None:
        return v
    if not isinstance(v, (list, tuple)):
        raise ValueError(f"parameter '{name}' is not a vector, cannot take .{ref.split('.')[-1]}")
    if comp >= len(v):
        raise IndexError(f"parameter '{name}' has only {len(v)} components, cannot take component "
                         f"{comp}")
    return v[comp]


# ═══════════════════════════════════════════ Letting a model fill it in: schema / apply
def schema(specs):
    """
    declaration -> schema shown to the model. **This is the prerequisite for the model getting key names right.**

    Without a schema the model can only guess names ("radius" or "size"?), and the wrongly guessed keys get
    silently ignored -- the symptom is "the model's answer looks plausible, yet not a single parameter in the graph changed". So the panel
    outputs a schema directly, to paste into the prompt.
    """
    out = {}
    for sp in specs:
        e = {"type": sp["type"], "default": sp["default"]}
        if sp["min"] is not None:
            e["min"], e["max"] = sp["min"], sp["max"]
        if sp["n"] > 1:
            e["components"] = sp["n"]
        if sp["label"]:
            e["label"] = sp["label"]
        out[sp["name"]] = e
    return out


def apply_values(specs, current, incoming):
    """
    Merge a {name: value} set from the model into the current values -> (new values, report).

    **This is the entire boundary through which AI can touch this graph.** It can only fill in values for **already declared** parameters:

      · keys not in the declaration -> recorded in `unknown`, no parameter created
      · type mismatch (a float parameter given "big") -> recorded in `skipped`, original value kept
      · outside the declared range -> **clamped** and recorded in `clamped`
      · parameters not mentioned -> left untouched

    So the model can change values, but not topology, not bindings, and it cannot add parameters -- "parameter-level rather than
    topology-level" holds **structurally**, not through prompt constraints.

    All three cases must be reported. Silently ignoring half the keys is the most common pitfall of this kind of feature: the model's answer
    looks convincing, only half the graph changed, and you think it filled in everything.
    """
    by = {sp["name"]: sp for sp in specs}
    out = dict(merge(specs, current))
    rep = {"applied": [], "clamped": [], "unknown": [], "skipped": []}
    if not isinstance(incoming, dict):
        raise ValueError(
            f"expected a JSON object ({{\"name\": value}}), got "
            f"{type(incoming).__name__}")
    for k, v in incoming.items():
        name = str(k).strip()
        sp = by.get(name)
        if sp is None:
            rep["unknown"].append(name)
            continue
        if isinstance(v, str) and sp["type"] != "string":
            # Models love writing numbers as strings; rescue them where possible, otherwise record skipped.
            # inf/nan also count as unrescuable -- they would travel all the way into the geometry and become a pile of nan vertices,
            # by which point you are far away from "the model filled in an inf"
            try:
                v = float(v)
            except ValueError:
                rep["skipped"].append(name)
                continue
            if not math.isfinite(v):
                rep["skipped"].append(name)
                continue
        if not _fits(sp, v):
            if sp["type"] == "bool" and isinstance(v, (int, float)):
                v = bool(v)
            elif sp["n"] > 1 and isinstance(v, (int, float)):
                v = [float(v)] * sp["n"]       # a single number fills every component
            else:
                rep["skipped"].append(name)
                continue
        if _out_of_range(sp, v):
            rep["clamped"].append(name)
        out[name] = _coerce(sp, v)
        rep["applied"].append(name)
    for key in rep:
        rep[key] = sorted(rep[key])
    return out, rep


class PCG_Parameters:
    """
    Control panel for the whole graph -- the equivalent of adding a bunch of spare parameters to a Houdini null.

    One parameter declared per line; the frontend **grows real controls** on this node from it:

        float  radius = 1.0 : 0 10   # radius
        int    count  = 5   : 1 100
        bool   cap    = true
        string prefix = piece
        vector pos    = 0 0 0
        vector4 col   = 1 1 1 1

    ━━ How to hook it up to other nodes (= Houdini's copy relative reference)
    Right-click the **target node** → `PCG: Bind Parameter`, pick a widget and a parameter name;
    or right-click this node → `PCG: Copy Parameter Reference`, then on the target node → `Paste Parameter Reference`.
    After binding, that widget's label becomes `name ← radius` and its value follows the panel.

    **Bindings are done in the frontend: when the panel changes, the value is written straight into the target widget.** So:
      · the submitted prompt is exactly the values you see, and the cache hash is naturally correct
      · invalidation is **fine-grained** -- changing radius recooks only the nodes that reference it, everything else keeps reusing the cache.
        Wires cannot do this (every consuming node hangs off the same upstream, touching one invalidates them all)
      · cost: via API / headless nothing is re-evaluated; the last materialized values are used

    ━━ A graph should have only one panel
    Bindings are looked up **by name** (unlike Houdini's relative paths); when several panels have a parameter with the same name
    the one earliest in the graph wins, and the panel title says so. To group parameters, use name prefixes (`rock_radius`).

    The `json` output is the current values of all parameters, useful for reading in a Wrangle or for saving;
    if it is not wired up, this node is never even executed -- it is just a panel.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "declare": ("STRING", {
                "multiline": True, "param_decl": True,
                "default": "float radius = 1.0 : 0 10   # radius\n"
                           "int   count  = 5   : 1 100\n",
                "tooltip": "One per line: <type> <name> [= default] [: min max] "
                           "[# label]"}),
            "values": ("STRING", {"default": "{}", "param_store": True}),
        }}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("json", "schema")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, declare, values="{}"):
        specs = parse(declare)
        try:
            stored = json.loads(values) if str(values).strip() else {}
        except json.JSONDecodeError as e:
            raise ValueError(f"parameter values are not valid JSON: {e}") from e
        return (json.dumps(merge(specs, stored), ensure_ascii=False,
                           sort_keys=True),
                json.dumps(schema(specs), ensure_ascii=False,
                           sort_keys=True, indent=1))


class PCG_ParamsFromJSON:
    """
    **Let a model fill in the parameter panel.** Item 5 on the list, the parameter-level tier.

        Parameters (schema output) → paste into the prompt → LLM → this node
        → the values on the panel all change → existing bindings fan them out across the whole graph

    ━━ Why "parameter-level" rather than "let the model write the graph"
    Having the model emit a subgraph directly is technically possible (the GraphBuilder used by For-Each / File Cache
    does exactly that), but that route is not reproducible and a wrong graph is extremely hard to debug: the error shows up
    on generated nodes, and all you have is a prompt.

    The parameter-level boundary is **structural**, not enforced through the prompt: this node can only fill in values for **already declared**
    parameters -- keys not in the declaration are recorded in `unknown` instead of creating new parameters,
    wrong types are recorded in `skipped`, out-of-range values are **clamped** and recorded in `clamped`. So the model can change
    values, but not topology, not bindings, and it cannot add parameters. The topology is still yours: reproducible and revertible.

    ━━ All three cases **must be reported**
    Silently ignoring half the keys is the most common pitfall of this kind of feature: the model's answer looks convincing, only half the graph changed,
    and you think it filled in everything. `report` contains all four lists.

    ━━ It takes two runs
    The values are written into the panel in the **frontend** (the same mechanism as parameter bindings), so this run still uses
    the old values; **press Run once more** to get results from the new values. This is the inherent cost of frontend materialization,
    already documented in the parameter-binding batch.

    **It does not automatically queue a re-run** -- auto re-run + every run changing parameters = an infinite loop, and the kind
    that looks like it is "working hard".

    ━━ The input can be messy
    It uses the same tolerant parsing as From JSON: ```json fences, a leading "Here you go:",
    trailing commas are all fine; whatever was repaired is written into report.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "json_text": ("STRING", {"multiline": True, "default":
                          '{"radius": 2.5, "count": 12}'}),
            "enabled": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("values", "applied", "report")
    FUNCTION = "run"
    CATEGORY = "PCG/param"
    OUTPUT_NODE = True

    def run(self, json_text, enabled):
        from .geo import structured as _stx
        if not enabled:
            return {"ui": {}, "result": ("{}", 0, "disabled, panel left untouched")}
        data, how = _stx.loads(json_text)
        if isinstance(data, list):
            # Models sometimes wrap it in an array. Take the first object and say so clearly in the report
            data = next((x for x in data if isinstance(x, dict)), None)
            how = (how + "+took the first object from an array") if data is not None else how
        if not isinstance(data, dict):
            raise ValueError(
                "expected a JSON object, like {\"radius\": 2.5}. "
                f"Parsed a {type(data).__name__}")
        txt = json.dumps(data, ensure_ascii=False, sort_keys=True)
        # The panel lives in the frontend; the backend does not know what it declares -- name filtering and clamping happen in the frontend,
        # here we only pass on a **cleanly parsed** set of values
        return {"ui": {"pcg_params_apply": [{"values": data, "parse": how}]},
                "result": (txt, len(data), f"parsed: {how}  {len(data)} keys")}


class PCG_ParamPick:
    """
    Pick one value out of a piece of JSON, **usable in the same run**.

    `Params from JSON` is the other route; each has its cost:

        Params from JSON   writes into the panel -> bindings fan out across the graph. Changing one parameter recooks only the nodes
                           that reference it (fine-grained), but the values are materialized in the frontend, so it **takes two runs**
        Param Pick         one wire into the target widget. **Takes effect in the same run**,
                           but all Picks hang off the same JSON, so when the JSON changes they are all invalidated

    The JSON a model gives is replaced as a whole anyway, so the latter's "coarse granularity" costs nothing in this use case --
    what matters is taking effect in the same run. Using both together works too: the panel for parameters tuned by hand, Pick for what the model gives in this run.

    When the lookup fails it **raises instead of returning 0**: a silent 0 travels all the way to the end, and "the model did not give this key"
    and "the model gave 0" are two completely different things. To tolerate it, turn on `fallback`.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            # Default to a placeholder JSON that runs. With an empty `{}`, a freshly dragged-out node raises KeyError
            # as soon as you press Run -- correctly (see below), but that should not be the first impression
            "json_text": ("STRING", {"multiline": True,
                                     "default": '{"radius": 1.0}'}),
            "name": ("STRING", {"default": "radius", "tooltip":
                     "a.b reads nested keys, pos.y reads a vector component"}),
            "fallback": ("BOOLEAN", {"default": False}),
            "default_value": ("FLOAT", {"default": 0.0, "min": -1e9,
                                        "max": 1e9, "step": 0.01}),
        }}
    RETURN_TYPES = ("FLOAT", "INT", "STRING")
    RETURN_NAMES = ("float", "int", "string")
    FUNCTION = "run"
    CATEGORY = "PCG/param"

    def run(self, json_text, name, fallback, default_value):
        from .geo import structured as _stx
        data, _how = _stx.loads(json_text)
        cur, key = data, str(name).strip()
        try:
            if not key:
                raise KeyError("name is empty")
            for part in key.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                elif isinstance(cur, (list, tuple)) \
                        and part.lower() in COMPONENTS \
                        and COMPONENTS[part.lower()] < len(cur):
                    cur = cur[COMPONENTS[part.lower()]]
                else:
                    have = (sorted(cur.keys()) if isinstance(cur, dict)
                            else type(cur).__name__)
                    raise KeyError(f"cannot get '{part}'. This level has: {have}")
        except KeyError as e:
            if not fallback:
                raise KeyError(
                    f"no '{key}' in the JSON: {e}. "
                    f"Turn on fallback to fall back to the default value instead.") from e
            cur = float(default_value)
        if isinstance(cur, bool):
            cur = 1.0 if cur else 0.0
        if isinstance(cur, (list, tuple)):
            return (float(cur[0]) if cur else 0.0,
                    int(round(float(cur[0]))) if cur else 0,
                    json.dumps(cur, ensure_ascii=False))
        if isinstance(cur, str):
            try:
                f = float(cur)
            except ValueError:
                f = float(default_value)
            return (f, int(round(f)), cur)
        f = float(cur)
        return (f, int(round(f)), json.dumps(cur, ensure_ascii=False))


NODE_CLASS_MAPPINGS = {
    "PCG_Parameters": PCG_Parameters,
    "PCG_ParamsFromJSON": PCG_ParamsFromJSON,
    "PCG_ParamPick": PCG_ParamPick,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PCG_Parameters": "Parameters (PCG)",
    "PCG_ParamsFromJSON": "Params from JSON (PCG)",
    "PCG_ParamPick": "Param Pick (PCG)",
}
