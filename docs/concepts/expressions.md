# Expressions

comfyui_pcg has three expression languages, each in a different place. **Wrangle code** (Wrangle, Volume Wrangle, COP Wrangle, group `@` patterns) is Python with Houdini's `@attribute` shorthand, evaluated on whole arrays at once; it has its own page, [Wrangle syntax](wrangle.md). **Node expressions** (Expression, Switch, Switch-If, Select Best) are small Python-style formulas evaluated on the server. **Parameter expressions** are typed directly into a numeric or string field of a node's panel; they follow HScript conventions and are evaluated in the browser. This page covers all three and the frame variables they share.

| Where | Language | Angles | Evaluated |
|---|---|---|---|
| Wrangle, Volume Wrangle, COP Wrangle, `@` group patterns | Python + numpy with `@attr` | radians | on the server, once per node run |
| Expression, Expression XYZ, Switch, Switch-If, Select Best | Python-style formula | radians | on the server |
| Parameter fields in the panel | HScript-style | **degrees** | in the browser, before the graph is queued |

## The Wrangle language

Wrangle, Volume Wrangle, COP Wrangle and `@` group patterns use Python with numpy and Houdini's `@attribute` shorthand. The code runs once per node run and every `@attribute` is a whole column, so per-element conditions use `where()` instead of `if`. The full syntax (attributes and type prefixes, `@group_`, operators, functions, `ch()`, the Volume and COP variants, a VEX translation table) is on its own page: **[Wrangle syntax](wrangle.md)**.

```python
@P.y = sin(length(@P) * 0.5) * 2.0
@Cd = where(@P.y > 0, set(1, 0, 0), set(0, 0, 1))
s@name = sprintf("rock_%03d", @ptnum)
```

## Node expressions

These nodes evaluate a single formula on the server. The syntax is Python's expression syntax (`a if cond else b`, `and` / `or`, `**` or `pow`), with no `@` attributes.

Operators, highest precedence first (Python's rules):

| Operators | Meaning |
|---|---|
| `( )`, `f(...)` | Grouping, function calls. |
| `**` | Power, right-associative; binds tighter than a unary minus on its left (`-2**2 = -4`). |
| `-x`, `+x` | Sign. |
| `*` `/` `//` `%` | Multiply, divide, integer divide, remainder. |
| `+` `-` | Add, subtract. |
| `<` `<=` `>` `>=` `==` `!=` | Comparisons give 1 or 0 (they chain: `0 < a < 1`). |
| `not`, `and`, `or` | Logic. |
| `a if cond else b` | Choice. |

Like Wrangle code, these formulas are Python run on the server, behind the same code guard; see [Security](wrangle.md#security).

**[Expression (PCG)](../reference/param.md#pcg-expr)** and **[Expression XYZ (PCG)](../reference/param.md#pcg-expr3)** compute numbers from up to six float inputs `a` to `f` (unconnected inputs are 0). Expression outputs a float and the same value rounded to an int; Expression XYZ evaluates three formulas with the same inputs.

Functions: `sin cos tan asin acos atan atan2 sqrt exp log pow abs floor ceil round min max sign mod frac radians degrees clamp fit fit01 lerp rand`; constants `PI`, `TAU`, `E`. Angles are in radians. `rand(seed)` returns the same number for the same seed.

```text
fit(a, 0, 1, 0, 360)        one turn as a goes from 0 to 1
sin(a * TAU) * 0.5 + 0.5    there and back
a if a > 1 else -1
```

**[Switch (PCG)](../reference/modify.md#pcg-switch)** Select Input and **[Switch-If (PCG)](../reference/modify.md#pcg-switchif)** Tests use the same functions plus geometry queries that read the control geometry (`ctrl` on Switch, `test` on Switch-If):

| Function | Returns |
|---|---|
| `detail("name" [, component])`, `point("name", i [, component])`, `prim(...)`, `vertex(...)` | An attribute value (string attributes return text). |
| `npoints()`, `nprims()`, `nvertices()`, `ninputs()` | Counts. |
| `hasattrib("point", "Cd")`, `hasdetail("name")` | 1 or 0. |
| `hasgroup("prim", "top")`, `ngroup("edge", "crease")` | Whether a group exists / its member count (-1 if missing). |
| `attribmin("point", "P", 1)`, `attribmax(...)`, `attribmean(...)` | Aggregates over all elements. |

As in Houdini, a leading input number of `-1` is accepted and refers to the control input: `detail(-1, "type", 0)`. Other input numbers are an error, because reading a branch would execute it. Switch-If takes one test per line; lines starting with `#` are comments.

**[Select Best (PCG)](../reference/loop.md#pcg-selectbest)** scores each geometry of a sequence with an expression that can use every Geo Metrics name (`prims`, `closed`, `genus`, ...), `i`, `n` and the same geometry-reading functions.

## Parameter expressions

Any numeric field in a node's Houdini-style panel can hold an expression instead of a number, like a Houdini parameter with an HScript expression. Type it and press Enter:

| You type | Result |
|---|---|
| A plain number, `4.5` | Sets the value; replaces any expression or reference. |
| Anything else: `ch("../grid1/rows") * 2 + 1`, `sin($F * 10)`, `2*pi`, `1/3` | Stored as an expression. The field turns cyan and shows the expression. |
| An invalid expression, `fit(1, 0, 2` | Stored, but the field turns red; hover for the reason. The value is not changed. |
| Enter without changes, an empty field, or Esc | Nothing changes. |

The expression is evaluated **in the browser**, and the result is written into the node's real parameter before the graph is queued. The server only ever sees a plain number, so ComfyUI's caching works normally and only nodes whose values changed are recomputed. The flip side: when a workflow is run through the API or headless, expressions are not re-evaluated and the last value written into the workflow is used.

To see the current value of an expression field, hold the **middle mouse button** on it, or click the parameter's label to toggle between expression and value for that row.

### Syntax

- Operators, highest precedence first:

  | Operators | Meaning |
  |---|---|
  | `( )`, `f(...)` | Grouping, function calls. |
  | `^` or `**` | Power, right-associative (`2^3^2 = 512`); binds tighter than a unary minus (`-2^2 = -4`). |
  | `-x` `+x` `!x` | Sign, logical not. |
  | `*` `/` `%` | Multiply, divide, remainder. |
  | `+` `-` | Add, subtract; `+` with a string concatenates. |
  | `<` `>` `<=` `>=` | Comparisons (1 or 0). |
  | `==` `!=` | Equality (1 or 0). |
  | `&&` | And (short-circuit). |
  | `\|\|` | Or (short-circuit). |
- Strings in `"..."` or `'...'`; `+` with a string concatenates.
- `if(cond, a, b)` evaluates only the chosen branch.
- Functions (numbers in, numbers out unless noted):

  | Function | Result |
  |---|---|
  | `abs(x)` `ceil(x)` `floor(x)` `frac(x)` `sign(x)` | As usual; `frac(-0.25) = 0.75`. |
  | `rint(x)` `round(x)` | Nearest integer, halves away from zero. |
  | `int(x)` `trunc(x)` | Drop the fraction. |
  | `min(a, b, ...)` `max(a, b, ...)` | Any number of arguments. |
  | `clamp(x, lo, hi)` | `x` limited to the range. |
  | `fit(x, a, b, c, d)` | `x` mapped from `a..b` to `c..d`, clamped. |
  | `fit01(x, c, d)` `fit10(x, c, d)` `fit11(x, c, d)` | `fit` from 0..1, 1..0, -1..1. |
  | `lerp(a, b, t)` | `a + (b - a) * t`. |
  | `pow(x, y)` `sqrt(x)` `exp(x)` `log(x)` `log10(x)` `hypot(a, b, ...)` | Powers and logs (`log` of 0 or less is an error). |
  | `sin cos tan(deg)` `asin acos atan(x)` `atan2(y, x)` | **Degrees** in and out. |
  | `sinh cosh tanh(x)` | Hyperbolic. |
  | `rad(deg)` `deg(rad)` | Unit conversion. |
  | `rand(seed)` | 0..1, the same number for the same seed. |
  | `strlen(s)` | Length of a string. |
  | `padzero(width, n)` | `n` as text padded with zeros: `padzero(4, 7) = "0007"`. |
  | `if(cond, a, b)` | Only the chosen branch is evaluated. |
  | `ch` `chf` `chs`, `npoints` ... `opinputpath` | Parameters and geometry, below. |
- **Trigonometry is in degrees** here, as in HScript: `sin(90) = 1`. This differs from Wrangle and the Expression node, which use radians.
- `rand(seed)` returns the same number as `rand(seed)` in the Expression node.
- Constants: `$PI`, `$E` (also `PI`, `E`, `pi`); `D_XMIN`, `D_XMAX`, `D_YMIN`, `D_YMAX`, `D_ZMIN`, `D_ZMAX`, `D_XSIZE`, `D_YSIZE`, `D_ZSIZE`, `D_X`, `D_Y`, `D_Z` for `bbox()` and `centroid()`.

### Variables

| Variable | Value |
|---|---|
| `$F`, `$FF` | Current frame. |
| `$T` | Time in seconds: (frame - start) / fps. |
| `$FPS`, `$FSTART`, `$FEND`, `$NFRAMES` | Timeline settings. |
| `$OS` | This node's title (a string). |

The frame variables come from the [Frame (PCG)](../reference/param.md#pcg-frame) node in the graph (the one the playbar drives). Without a Frame node they use its defaults: frame 0, start 0, end 23, 24 fps. See [Loops and time](loops-and-time.md).

### Referencing other parameters: `ch()`

| Path | Refers to |
|---|---|
| `ch("tx")`, `ch("./tx")` | Parameter `tx` of this node. |
| `ch("../box1/tx")` | Parameter `tx` of the node titled `box1`. |
| `ch("../CTRL/radius")`, `ch("../CTRL/pos.y")` | Parameter `radius` / component `y` of `pos` on the Parameters (PCG) node titled `CTRL`. |
| `chs(...)` | Same, for string and menu parameters. |
| `chf(path, frame)` | The parameter's value at another frame (differs only for keyframed or `$F`-based values). |

Parameter names are the internal names shown in the reference (for example `tx`, `rows`). When stored, `../title/` is replaced by the node's id, and shown again with the current title, so **renaming the source node does not break the reference**. Copying a node keeps references to its own parameters (`ch("tx")`) pointing at itself.

An expression turns red when the referenced title is ambiguous (several nodes with that title; rename one), when the node or parameter does not exist, when the reference forms a cycle, when the source parameter is connected to a wire (its value only exists at run time), or when `ch` is used on a string parameter (use `chs`).

### Reading geometry in a field

| Function | Returns |
|---|---|
| `npoints(path)`, `nprims(path)`, `nvertices(path)` | Counts. |
| `bbox(path, D_XMIN ... D_ZSIZE)` | Bounding-box bound or size. |
| `centroid(path, D_X / D_Y / D_Z)` | Bounding-box centre. |
| `point(path, index, attrib, component)`, `prim(...)` | A numeric attribute value. |
| `points(...)`, `prims(...)` | The same for string attributes. |
| `detail(path, attrib, component)`, `details(path, attrib)` | Detail attribute, numeric / string. |
| `opname(path)` | The node's title. |
| `opinputpath(path, n)` | The node connected to geometry input `n`. |

The node path is `"."` for this node or `"../title"` for another one. A missing attribute or index out of range gives 0 (or an empty string).

These functions read the **result of the last run** of that node. ComfyUI computes the whole graph on the server, so the browser only knows a node's geometry after it has run. If you change something upstream, the first run uses the previous geometry; run again to pick up the new one. Before the referenced node has run, the field is shown grey and italic (waiting), not red.

### String fields and templates

In single-line string fields (group, file name, attribute name; not Wrangle code), text containing a backtick or a `$variable` is stored as a **template** and expanded when values are written:

```text
out/${OS}_$F4.png              node title, frame padded to 4 digits
piece_`$F*2`                   backticks contain an expression
`chs("../a/name")`_v2          reference to another string parameter
```

- `$F4` is the frame padded to four digits. Use `${F}` to separate a variable from following text; `$F4_x` is read as a variable named `F4_x`, as in Houdini.
- Unknown variables (for example `$HIP`) are left as they are.
- Escape with `` \` ``, `\$` and `\\`.
- Plain text without backticks or `$` is an ordinary value.

### Keyframes

Any numeric field can be keyframed:

- **Alt+click** a field sets a key at the current frame with the current value; Alt+click the label keys the whole row.
- **Alt+Shift+click** deletes the key at the current frame.
- The right-click menu has Set Keyframe, Delete Keyframe and Delete Channels.

Keyed fields are green (brighter when the current frame is on a key). Typing a number, using the arrow keys or dragging in a keyed field sets a key at the current frame. Typing an expression replaces the keys with the expression. Keys use the same format and interpolation as the [Channel (PCG)](../reference/param.md#pcg-channel) node; new keys are `cubic`.

### How fields store this

In a saved workflow these bindings live in the node's properties (`pcg_bind`), not in `widgets_values`. A stored entry is one of: `@<id>/<param>` (a pasted relative reference), a Parameters-panel name, `=<expression>`, `~<template>` or `k:<keys>`. You never type the prefixes yourself; they are useful to know when reading a workflow JSON.

## Keyframe channels

[Channel (PCG)](../reference/param.md#pcg-channel) and [Channel XYZ (PCG)](../reference/param.md#pcg-channel3) evaluate a keyframe curve written as text, at the frame given by their `frame` input:

```text
frame:value[:interpolation][@slope]

0:0  24:360                    constant speed, one turn
0:0  12:1:ease  24:0           there and back with easing
0:0  10:1:constant  20:1       step to 1 at frame 10
0:0@0  12:1  24:0@0            force flat tangents at the ends
```

- Keys are separated by spaces and sorted by frame.
- **The interpolation written on a key applies to the segment to its right.** Keys without one use the node's Interpolation setting.
- Interpolations: `constant`, `linear`, `ease` (flat at both ends), `easein` (slow start), `easeout` (slow end), `cubic` (Hermite, automatic or `@slope` tangents; default), `quintic`.
- `@slope` sets the tangent in value per frame; it is used by `cubic` and `quintic`. Automatic tangents are exact for quadratic curves at any key spacing, so `cubic` can overshoot; flatten with `@0` or use `ease`.
- Outside the keys (Extrapolation): `hold`, `linear`, `cycle`, `cycleoffset`, `mirror`.
- The output is `value * Scale + Offset`, so one curve can drive parameters with different units.

## See also

- [Wrangle syntax](wrangle.md)
- [Group patterns](groups.md)
- [Parameters](parameters.md): the panel, references and the Parameters (PCG) controller
- [Loops and time](loops-and-time.md): Frame, playbar, frame loops
- [Geometry](geometry.md): attribute classes and types
- Reference: [Parameters & Expressions](../reference/param.md), [Wrangle](../reference/attribute.md#pcg-wrangle)
