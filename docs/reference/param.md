# Parameters & Expressions

Controller nodes, values, expressions and parameter plumbing.

9 nodes.

[Back to the reference index](README.md)

## Contents

- [Channel (PCG)](#pcg-channel) — Evaluates a keyframed curve, written as one line of text, at a given frame.
- [Channel XYZ (PCG)](#pcg-channel3) — Evaluates three keyframed curves at the same frame and outputs x, y and z.
- [Expression (PCG)](#pcg-expr) — Evaluates a single math expression of up to six float inputs.
- [Expression XYZ (PCG)](#pcg-expr3) — Evaluates three math expressions that share the same six float inputs and outputs x, y and z.
- [Frame (PCG)](#pcg-frame) — Provides the current frame, normalised time and seconds from the timeline.
- [Param Pick (PCG)](#pcg-parampick) — Reads one value out of a JSON text and outputs it as float, int and string, usable in the same run.
- [Parameters (PCG)](#pcg-parameters) — Defines a control panel of named parameters for the whole graph, similar to spare parameters on a Houdini null.
- [Params from JSON (PCG)](#pcg-paramsfromjson) — Lets a model fill the Parameters panel by applying a JSON object of values to already-declared parameters.
- [Value (PCG)](#pcg-value) — Outputs one float that can be connected to many parameters, as a global variable for the graph.

## Nodes

### Channel (PCG)

<a id="pcg-channel"></a>

`PCG_Channel` · category `PCG/param`

Evaluates a keyframed curve, written as one line of text, at a given frame.

A keyframe channel: the curve is a text string of keys, evaluated at `frame`. Wire `frame_f` from Frame (PCG) into `frame`, convert the target parameter to an input and connect `value` to it; dragging the playbar then animates the parameter.

Each key is written `frame:value[:interp][@slope]`. Keys are separated by spaces and may be in any order (they are sorted). The interpolation written on a key controls the segment to its **right**, so one written on the last key has no effect. If two keys share a frame the later one wins. `@slope` sets the tangent at that key in value per frame and is only used by `cubic` and `quintic`; without it the tangent is computed automatically with a spacing-weighted three-point difference that is exact for quadratics at any key spacing (plain Catmull-Rom is only exact for evenly spaced keys). Because of this `cubic` can overshoot on step-like data; pin the tangents with `@0` or use `ease` to prevent it.

Example: `0:0  12:1.5:ease  18:1.5  24:0` pushes in over 12 frames, holds for 6, then pulls out.

The final output is `curve value * scale + offset`. Use Channel for "what should the value be at frame N" and Expression (PCG) for values computed from other values; chain them (Channel into `a`, expression `a * 2`) to combine both.

**Outputs**

| Output | Type | Description |
|---|---|---|
| `value` | FLOAT | The curve value at `frame`, after scale and offset. |
| `int` | INT | The same value rounded to the nearest integer. |
| `info` | STRING | A short text summary of the parsed curve, for display or debugging. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Frame `frame` | float | 0 | Frame at which the curve is evaluated. Fractional frames are allowed. Normally driven by the `frame_f` output of Frame (PCG). |
| Keyframes `keys` | string | `0:0  12:1:ease  24:0` | The keyframes as `frame:value[:interp][@slope]`, separated by spaces. The interpolation on a key applies to the segment to its right; keys without one use Default Interpolation. |
| Default Interpolation `interp` | menu | Cubic | Interpolation used for keys that do not name their own. `constant` is a step (holds the left value), `ease` has zero tangent at both ends (smoothstep), `easein` eases only at the start of the segment and `easeout` only at its end, `cubic` and `quintic` are Hermite curves using automatic or `@` tangents (quintic also has zero second derivative at the ends). Options: Constant (`constant`), Linear (`linear`), Ease (`ease`), Ease In (`easein`), Ease Out (`easeout`), Cubic (`cubic`), Quintic (`quintic`). |
| Extrapolation `extrapolate` | menu | Hold | What the curve does outside the first and last key. `hold` keeps the end value, `linear` continues along the actual end tangent, `cycle` repeats the whole curve, `cycleoffset` repeats it and adds the net change of one period each time (useful for walk cycles that move forward), `mirror` ping-pongs. Options: Hold (`hold`), Linear (Slope) (`linear`), Cycle (`cycle`), Cycle with Offset (`cycleoffset`), Mirror (`mirror`). |
| Scale `scale` | float | 1 | Multiplier applied to the curve value. Lets one 0 to 1 curve drive parameters of different units. |
| Offset `offset` | float | 0 | Value added after scaling. |

**Compared with Houdini**

Houdini keys carry separate in and out functions; here each key has a single interpolation (the outgoing one), which avoids ambiguity when the two disagree. The curve is edited as text rather than in a graph editor.

**Tips**

- To check a curve visually, connect the output to a parameter and scrub the playbar.
- To suppress overshoot at a plateau, give those keys `@0` or use `ease`.

---

### Channel XYZ (PCG)

<a id="pcg-channel3"></a>

`PCG_Channel3` · category `PCG/param`

Evaluates three keyframed curves at the same frame and outputs x, y and z.

Three Channel (PCG) curves sharing one frame number, one interpolation setting, one extrapolation mode and one scale/offset. Use it for translate or rotate triples such as camera moves. Having the three key lists in one node also shows at a glance whether the x, y and z keys fall on the same frames.

Key syntax is `frame:value[:interp][@slope]`, as described on Channel (PCG). An empty key field behaves exactly like `0:0`: a curve that is always 0, which still goes through `* scale + offset`. You therefore only need to write the axis you want to animate.

**Outputs**

| Output | Type | Description |
|---|---|---|
| `x` | FLOAT | Curve X value after scale and offset. |
| `y` | FLOAT | Curve Y value after scale and offset. |
| `z` | FLOAT | Curve Z value after scale and offset. |
| `info` | STRING | Text summary of the frame and the three values. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Frame `frame` | float | 0 | Frame at which all three curves are evaluated. Fractional values are allowed; usually driven by `frame_f` of Frame (PCG). |
| Keyframes X `keys_x` | string | `0:0  24:0` | Keyframes for the X curve as `frame:value[:interp][@slope]`. Empty is the same as `0:0`. |
| Keyframes Y `keys_y` | string | `0:0  12:1:ease  24:0` | Keyframes for the Y curve. Empty is the same as `0:0`. |
| Keyframes Z `keys_z` | string | *(empty)* | Keyframes for the Z curve. Empty is the same as `0:0`. |
| Default Interpolation `interp` | menu | Cubic | Interpolation for keys that do not name their own; applies to all three curves. See Channel (PCG) for the seven options. Options: Constant (`constant`), Linear (`linear`), Ease (`ease`), Ease In (`easein`), Ease Out (`easeout`), Cubic (`cubic`), Quintic (`quintic`). |
| Extrapolation `extrapolate` | menu | Hold | Behaviour of all three curves outside their first and last key: hold the end value, continue along the end slope, repeat, repeat with offset, or mirror. Options: Hold (`hold`), Linear (Slope) (`linear`), Cycle (`cycle`), Cycle with Offset (`cycleoffset`), Mirror (`mirror`). |
| Scale `scale` | float | 1 | Multiplier applied to each curve value. |
| Offset `offset` | float | 0 | Value added to each curve after scaling, including curves left empty. |

**Tips**

- Stagger keys on purpose between axes to get weight; this node makes accidental misalignment easy to spot.

---

### Expression (PCG)

<a id="pcg-expr"></a>

`PCG_Expr` · category `PCG/param`

Evaluates a single math expression of up to six float inputs.

Evaluates `expr` with the connected inputs available as variables `a` to `f`. Unconnected inputs count as 0. The result is output both as a float and rounded to an integer. The function library is the same as in Wrangle (`sin`, `fit`, `clamp`, `lerp`, `rand` ...), with constants `PI`, `TAU` and `E`.

Use it between a Frame (PCG) output and a parameter to shape the value: `fit(a, 0, 1, 0, 360)` turns a camera once around, `sin(a*TAU)*0.5+0.5` makes a there-and-back motion.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `a` *(optional)* | FLOAT | Variable `a` in the expression. 0 when unconnected. |
| `b` *(optional)* | FLOAT | Variable `b`. 0 when unconnected. |
| `c` *(optional)* | FLOAT | Variable `c`. 0 when unconnected. |
| `d` *(optional)* | FLOAT | Variable `d`. 0 when unconnected. |
| `e` *(optional)* | FLOAT | Variable `e`. 0 when unconnected. |
| `f` *(optional)* | FLOAT | Variable `f`. 0 when unconnected. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `float` | FLOAT | The expression result. |
| `int` | INT | The result rounded to the nearest integer. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Expression `expr` | string | `a * 2 + b` | The expression, using `a` to `f`, numbers, constants and functions. Unconnected variables are 0. |

**Tips**

- Use Channel (PCG) for keyframed behaviour and Expression for values derived from other values.

---

### Expression XYZ (PCG)

<a id="pcg-expr3"></a>

`PCG_Expr3` · category `PCG/param`

Evaluates three math expressions that share the same six float inputs and outputs x, y and z.

Three expressions evaluated against the same variables `a` to `f` (unconnected inputs are 0). It is cleaner than three separate Expression (PCG) nodes when driving a triple such as `tx/ty/tz` or `rx/ry/rz`. The function library is the same as in Expression (PCG) and Wrangle.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `a` *(optional)* | FLOAT | Variable `a`. 0 when unconnected. |
| `b` *(optional)* | FLOAT | Variable `b`. 0 when unconnected. |
| `c` *(optional)* | FLOAT | Variable `c`. 0 when unconnected. |
| `d` *(optional)* | FLOAT | Variable `d`. 0 when unconnected. |
| `e` *(optional)* | FLOAT | Variable `e`. 0 when unconnected. |
| `f` *(optional)* | FLOAT | Variable `f`. 0 when unconnected. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `x` | FLOAT | Result of the X expression. |
| `y` | FLOAT | Result of the Y expression. |
| `z` | FLOAT | Result of the Z expression. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Expression X `expr_x` | string | `a` | Expression producing the x output. |
| Expression Y `expr_y` | string | `0` | Expression producing the y output. |
| Expression Z `expr_z` | string | `a` | Expression producing the z output. |

---

### Frame (PCG)

<a id="pcg-frame"></a>

`PCG_Frame` · category `PCG/param`

Provides the current frame, normalised time and seconds from the timeline.

The single source of truth for time. The playbar writes its frame into this node, and every parameter that should animate takes a link from one of its outputs. A graph can contain several Frame nodes: the playbar writes the same frame to all of them, but each has its own Start / End, so their `t` values differ. For example a 0 to 23 main timeline plus a 12 to 18 node for a secondary move.

Outputs: `frame` (int), `frame_f` (the same number as float), `t` = (frame - start) / (end - start), `frames` = |end - start| + 1 and `seconds` = (frame - start) / fps. Both integer and float frame outputs exist because ComfyUI only connects identical types, and most parameters to drive (time, angles, distances) are floats.

There is no `$F` environment variable. A link is how ComfyUI's cache learns about the dependency: when `frame` changes, only nodes downstream of this node are recomputed and the time-independent part of the graph is reused. Connect the outputs to widgets (convert widget to input), and put an Expression between them to shape a curve: `fit(a, 0, 1, 0, 360)` turns the camera once around, `sin(a*TAU)*0.5+0.5` goes there and back.

End may be lower than Start for a reversed range; `t` still runs from 0 at Start to 1 at End and `frames` is still |end - start| + 1. With Start equal to End, `t` is 0.

**Outputs**

| Output | Type | Description |
|---|---|---|
| `frame` | INT | Current frame number as an integer. |
| `frame_f` | FLOAT | Current frame number as a float, for float parameters. |
| `t` | FLOAT | Normalised time: (frame - start) / (end - start). 0 when start equals end. |
| `frames` | INT | Length of the range: \|end - start\| + 1. |
| `seconds` | FLOAT | Time since Start in seconds: (frame - start) / fps. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Frame `frame` | int | 0 | Current frame. Normally set by the playbar; drag it or edit it to scrub. |
| Start / End `start` `end` | int | 0, 23 | First and last frame of the range (Start, End), used for `t` and `frames`. End may be lower than Start for a reversed range. |
| FPS `fps` | float [0.01..1000.0] | 24 | Frames per second, used only for the `seconds` output. |

**Compared with Houdini**

Replaces Houdini's `$F`, `$T` and `$FPS` variables with explicit links so that ComfyUI's input-hash cache can track the dependency.

---

### Param Pick (PCG)

<a id="pcg-parampick"></a>

`PCG_ParamPick` · category `PCG/param`

Reads one value out of a JSON text and outputs it as float, int and string, usable in the same run.

Picks a single value from `json_text` by name and outputs it. Connect the output to a target widget (convert widget to input) and the value takes effect in the current run.

There are two ways to feed JSON values into a graph. Params from JSON writes into the Parameters panel and its bindings fan out to the whole graph: changing one value recomputes only the nodes that reference it, but the values are written by the front end, so you need to run twice. Param Pick uses a normal link and applies immediately, but all Picks hang off the same JSON, so any change to the JSON invalidates all of them. For JSON that a model supplies as a whole, the coarse invalidation costs nothing. You can use both: the panel for hand-tuned parameters, Picks for what the model gave in this run.

If the name cannot be found the node raises an error rather than returning 0, because a silent 0 hides the difference between a key the model omitted and a key it set to 0. Enable Fallback to use the default value instead. The JSON is parsed tolerantly (code fences, leading text, trailing commas).

Boolean values become 1 or 0. A list outputs its first component as float and int, and the whole list as JSON text. A string outputs the number it parses to, or the default value if it is not numeric.

**Outputs**

| Output | Type | Description |
|---|---|---|
| `float` | FLOAT | The picked value as a float. |
| `int` | INT | The picked value rounded to an integer. |
| `string` | STRING | The picked value as text (JSON text for numbers and lists, the raw string for strings). |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Key `name` | string | `radius` | Key to read. Use `a.b` for nested objects and `pos.y` (or `pos.1`) for a component of a vector. |
| Fallback Value `default_value` | float | 0 | Value used when the key is missing and Fallback is on. |
| Fallback `fallback` | toggle | off | When off, a missing key raises an error. When on, Default Value is used instead. |
| JSON `json_text` | string | `{"radius": 1.0}` | The JSON text to read from. Fenced code blocks, text before the JSON and trailing commas are tolerated. |

---

### Parameters (PCG)

<a id="pcg-parameters"></a>

`PCG_Parameters` · category `PCG/param`

Defines a control panel of named parameters for the whole graph, similar to spare parameters on a Houdini null.

Declare one parameter per line and the front end builds real widgets on this node for them:

```
float  radius = 1.0 : 0 10   # label
int    count  = 5   : 1 100
bool   cap    = true
string prefix = piece
vector pos    = 0 0 0
vector4 col   = 1 1 1 1
```

The format is `type name [= default] [: min max] [# label]`. To use a parameter, bind a widget of another node to it from the node's right-click menu (the PCG bind-parameter entry on the target node; or copy the parameter reference on this node and paste it on the target). The widget label then shows `name <- radius` and follows the panel. This is the counterpart of copying a relative reference in Houdini.

Bindings are made by the front end: when the panel changes, the value is written into the target widget. The submitted prompt therefore contains the real value and the cache works at fine grain: changing `radius` only recomputes nodes that reference it. The cost is that when running through the API or headless, bindings are not re-evaluated and the last stored values are used.

Bindings look parameters up by **name**, not path. Keep one panel per graph; if several panels declare the same name, the one earliest in the graph wins and the panel title says so. Use name prefixes (`rock_radius`) for grouping. The `json` output carries all current values, for a Wrangle or for archiving, and `schema` describes the declared parameters, for pasting into a prompt. The node only executes when an output is connected.

**Outputs**

| Output | Type | Description |
|---|---|---|
| `json` | STRING | All current parameter values as a JSON object. |
| `schema` | STRING | The declared parameters (type, default, range, components, label) as JSON, to paste into a model prompt for Params from JSON. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Declare `declare` | string | *(see panel)* | One parameter per line: `type name [= default] [: min max] [# label]`. Types are `float`, `int`, `bool`, `string`, `vector` (3 components) and `vector4`. Changing the text adds or removes widgets; stored values of parameters that remain are kept. |
| Values `values` | string | `{}` | Storage for the current values, written by the generated widgets as JSON. Normally not edited by hand. |

**Compared with Houdini**

Parameters are declared as text rather than built with the parameter interface editor, and references resolve by name instead of by relative path like `ch("../ctrl/radius")`.

---

### Params from JSON (PCG)

<a id="pcg-paramsfromjson"></a>

`PCG_ParamsFromJSON` · category `PCG/param`

Lets a model fill the Parameters panel by applying a JSON object of values to already-declared parameters.

Parameter-level control by a language model: Parameters (schema output) is pasted into a prompt, the model answers with JSON, and this node writes the values into the panel, from where the existing bindings spread them across the graph.

The boundary is structural. Only declared parameters can be set: keys that are not declared are reported as `unknown` and create nothing, values of the wrong type are `skipped` (the old value stays), out-of-range values are **clamped** and reported as `clamped`, and parameters not mentioned are left alone. The model can change numbers, but not topology, bindings or the list of parameters. The `report` output names all of these groups, so a half-applied answer is visible.

The values are written into the panel by the front end, so the run in which they arrive still uses the old values. Press Run **again** to run with the new ones. The node does not re-queue a run on its own, because automatic re-runs combined with parameter changes on every run would loop endlessly.

Parsing is tolerant: a ```json fence, a leading sentence such as "Here you go:" and trailing commas are accepted, and what was repaired appears in the report. A list is accepted if it contains an object (the first object is used).

**Outputs**

| Output | Type | Description |
|---|---|---|
| `values` | STRING | The parsed JSON object as text. |
| `applied` | INT | Number of keys passed on to the panel. |
| `report` | STRING | How the text was parsed and how many keys were found. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Enable `enabled` | toggle | on | When off, nothing is applied and the panel is left untouched. |
| JSON `json_text` | string | `{"radius": 2.5, "count": 12}` | JSON object of parameter names to values, for example the model's answer. Fences and stray text around it are tolerated. *Disabled when enabled is off.* |

**Tips**

- Run twice: once to deliver the values and once to compute with them.

---

### Value (PCG)

<a id="pcg-value"></a>

`PCG_Value` · category `PCG/param`

Outputs one float that can be connected to many parameters, as a global variable for the graph.

A single editable number outputting as float and as rounded integer. Connect it to several converted widgets to drive them together.

**Outputs**

| Output | Type | Description |
|---|---|---|
| `float` | FLOAT | The value. |
| `int` | INT | The value rounded to the nearest integer. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Value `value` | float | 1 | The number to output. |

---
