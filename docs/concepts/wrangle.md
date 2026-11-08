# Wrangle syntax

The code in [Wrangle (PCG)](../reference/attribute.md#pcg-wrangle), [Volume Wrangle (PCG)](../reference/modify.md#pcg-volumewrangle) and [COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle) is **Python with numpy**, plus Houdini's `@attribute` shorthand and a VEX-like function library. The same language is used by `@` group patterns and by the sort and filter fields of some nodes. This page is the complete reference. The other two expression languages (node expressions and parameter-field expressions) are on [Expressions](expressions.md).

## How the code runs

The code is **not** VEX and does **not** run once per element. It runs **once per node run**, and every `@attribute` is a whole column: `@P` is an array with one row per point and three columns, `@P.y` is one number per point. Each line works on all elements at the same time.

```python
# runs once; every line works on all points at the same time
@P.y = sin(length(@P) * 0.5) * 2.0
@Cd = set(1, 0, 0)
@pscale = fit(@P.y, -2, 2, 0.1, 1.0)
```

That has three consequences:

| In VEX | Here |
|---|---|
| `if (@P.y > 0) @Cd = {1, 0, 0};` | `@Cd = where(@P.y > 0, set(1, 0, 0), @Cd)`. An `if` needs a single True / False, and `@P.y > 0` is one value per point, so `if` on it is an error ("The truth value of an array ... is ambiguous"). |
| `a && b`, `a \|\| b`, `!a` per element | `(a) & (b)`, `(a) \| (b)`, `~(a)`, **with parentheses**: `&` binds tighter than `>`, so `@P.x > 0 & @P.z > 0` is read as `@P.x > (0 & @P.z) > 0` and fails. `and` / `or` / `not` work only on single values. |
| `x > 0 ? a : b` | `where(x > 0, a, b)`. Python's `a if x > 0 else b` is fine when `x` is a single number. |

Ordinary Python is fine wherever the value is a single number: local variables, `for i in range(n):`, `while`, `if` on a count (`if npoints() > 100:`), your own functions (`def`), `del`. Loops run in Python, so loop over a few octaves or layers, not over the points.

## Statements and comments

| Syntax | Note |
|---|---|
| `# comment` | Python comments. `//` is **not** a comment (it is integer division). |
| One statement per line, or several separated by `;` | Indentation (4 spaces) for `def`, `for`, `while`, `if`. In the code box, Tab inserts 4 spaces. |
| `x = @P.y * 2` | A local variable: a whole column, or a single number. Locals are not written to the geometry. |
| `def f(x): return x * 2` | Functions of your own. They can use `@` attributes. |
| `print(...)` | Prints to the ComfyUI server console, not the browser. |
| `np.` and `math.` | numpy and Python's `math` are available; `import` is not (it raises `ImportError: __import__ not found`). |

Available Python built-ins: `abs`, `min`, `max`, `round` (these four work element by element), `range`, `len`, `float`, `int`, `bool`, `str`, `sum`, `enumerate`, `zip`, `print`, `True`, `False`, `None`. `str()` does not work on a column; use `sprintf`.

When the code fails, the error shows the message and the **translated Python** (every `@P` replaced by its array access), so the line can be found.

## Attributes

| Syntax | Meaning |
|---|---|
| `@P`, `@Cd`, `@foo` | Read or write an attribute of the *Run Over* class. |
| `@P.x` `@P.y` `@P.z` `@P.w` | One component, readable and writable (`@P.y += 1`). Swizzles such as `@P.xy` are not supported; use `set(@P.x, @P.y)`. |
| `@P[:, 1]`, `@P[mask, 1] = 0` | numpy indexing also works: a whole column, or only the rows where a boolean `mask` is true. |
| `@ptnum` `@primnum` `@vtxnum` `@elemnum` | Element number, 0 to n-1 (all four are the same thing). |
| `@numpt` `@numprim` `@numvtx` `@numelem` | Element count (all four are the same thing). |
| `@group_name` | The group `name` of the *Run Over* class: reads as 0 / 1 per element, and assigning to it sets the group (non-zero = member): `@group_top = @P.y > 0`. No attribute called `group_name` is created. A group that does not exist reads as 0. |

**Type prefixes** declare the attribute's type. A typed assignment converts the value to that type, as in VEX:

| Prefix | Type | Example |
|---|---|---|
| `f@` | float, 1 component | `f@height = @P.y` |
| `i@` | 32-bit integer (values are truncated) | `i@id = @ptnum // 4` |
| `v@` | float, 3 components; a single number fills all three | `v@up = set(0, 1, 0)`, `v@c = 0.5` |
| `2@` `3@` `4@` | float with 2, 3 or 4 components | `2@uv2 = set(@P.x, @P.z)` |
| `p@` | float, 4 components (a quaternion, as VEX's `p@orient`) | `p@orient = set(0, 0, 0, 1)` |
| `s@` | string; numbers are turned into text | `s@name = sprintf("rock_%02d", @ptnum)` |

A typed assignment with the wrong number of components (`f@a = @P`) or text into a number (`f@a = "x"`) is an error that names the attribute.

**Without a prefix** the value decides: writing to an attribute that does not exist creates it, with as many components as the value has (a single number gives 1, `set(x, y, z)` gives 3) and the value's number type. Reading an attribute that does not exist yet gives zeros with **3** components, so `@foo = @foo + 1` on a new attribute makes a vector; write `f@foo = f@foo + 1` for a scalar.

A constant vector such as `set(1, 0, 0)` is spread over every row. One-number-per-element values (`@P.y`, `@pscale`, `rand(@ptnum)`) combine with vectors row by row, so `@Cd = set(1, 0, 0) * @P.y` and `@P = @P * @pscale` do what you expect.

### Run Over

| Run Over | `@name` means | Notes |
|---|---|---|
| `point` | point attributes | The default. |
| `prim` | primitive attributes | `@P` is the primitive's centre, read-only, as in VEX. |
| `vertex` | vertex attributes | `@P` is the position of the vertex's point, read-only. |
| `detail` | detail attributes | One row. |

**Group** limits the change to a selection (see [Group patterns](groups.md)). The code still runs on all elements; afterwards rows outside the group are put back to their old value, or to 0 / empty (and out of the group, for `@group_`) when the code just created it. A division by zero in unselected rows can therefore still raise an error.

## Values and operators

| Kind | Notes |
|---|---|
| Numbers | `+ - * / ** %`, `//` (integer division). Integer columns stay integer until mixed with floats. |
| Comparisons | `== != < > <= >=` give one True / False per element. In arithmetic True is 1: `@Cd = set(@P.y > 0, 0, 0)`. |
| Logic | `&` `\|` `~` with parentheses (see above); `np.logical_and` etc. also work. |
| Vectors | `set(x, y, z)` (also `vector`, `vector2`, `vector4`); `+ - *` are per component; `dot`, `cross`, `length`, `normalize` are functions. Functions that return vectors support `.x` `.y` `.z` `.w`: `getbbox_size().y`, `point("P", 0).z`. |
| Strings | `"..."` or `'...'`. A string column can be built with `where(@P.x > 0, "left", "right")`, by indexing an array of names (`np.array(["a", "b"])[@ptnum % 2]`) or with `sprintf`. Compare with `==`: `where(@name == "roof", 1, 0)`. |
| Whole-column reductions | `@P.y.max()`, `np.mean(@P[:, 0])`, `len(@P)` give one number for the whole geometry. |

## Functions

All of numpy is available as `np`, and Python's `math` as `math`. On top of that:

| Category | Functions |
|---|---|
| Trigonometry (radians) | `sin cos tan asin acos atan atan2 sinh cosh tanh radians degrees`, constant `PI` |
| Powers and logs | `sqrt cbrt pow exp log log10` |
| Rounding | `floor ceil rint trunc frac sign abs round` (`round(x)` and `rint` round halves away from zero) |
| Ranges | `clamp(x, lo, hi)`, `fit(x, a, b, c, d)`, `fit01(x, c, d)`, `fit10(x, c, d)`, `efit(x, a, b, c, d)` (no clamping), `lerp(a, b, t)`, `smooth(a, b, x)` / `smoothstep(a, b, x)` |
| Element-wise min / max | `min(a, b)`, `max(a, b)` (these replace Python's built-ins, which would compare whole arrays) |
| Vectors | `set(...)` / `vector(...)` / `vector2(...)` / `vector4(...)`, `length length2 distance distance2 normalize cross dot` |
| Selection | `where(cond, a, b)` |
| Noise and random | `noise(p)` (Perlin, 0..1, like VEX), `vnoise(p)` (3 components), `pnoise(p, period)` (periodic Perlin, see below), `rand(seed)` |
| Strings | `sprintf(fmt, ...)` (one string per element when an argument is per-element; `%d %02d %s %.3f`), `itoa(x)` |
| Geometry queries | `point([input,] name, index)`, `prim(...)`, `vertex(...)`, `detail([input,] name)`, `npoints([input])`, `nprims([input])`, `nvertices([input])`, `ninputs()`, `getbbox_min([input])`, `getbbox_max`, `getbbox_size`, `getbbox_center` |
| Panel parameters | `ch(name, default)`, `chf`, `chi`, `chs`, `chv` |

**`rand(x)`** follows VEX: the argument is a seed, not a count, and the same seed gives the same number. The node's **Rand Seed** parameter is mixed in, so changing it re-rolls every `rand()` call; the seed itself is available as the variable `seed`. `rand(0)` with Rand Seed 0 returns exactly 0; use `rand(@ptnum + 1)` or a non-zero Rand Seed if that matters. Different calls with the same argument return the same number, so offset the argument: `rand(@ptnum + 0.37)`.

**`noise(p)`** is Perlin noise in 0..1 (mostly 0.3 to 0.7). **`pnoise(p, period)`** is the same noise repeating every `period` units (a number, or a 3-vector of whole numbers; 0 = not periodic on that axis). In a COP Wrangle `pnoise(set(@u * 8, @v * 8, 0), set(8, 8, 0))` tiles on all four sides of the image, which `noise()` does not.

**Reading other elements and inputs.** `point(name, index)` reads one element (`point("P", 0)`) or, with a column of indices, one per element (`point(0, "P", @ptnum + 1)`). Wrangle has three optional inputs `geo1`, `geo2`, `geo3` besides `geo`; the query functions take the input number as an optional first argument: `point(1, "P", 0)`, `npoints(2)`, `getbbox_size(3)`. Without a number they read input 0. A missing attribute reads as 0.

```python
# move every point up by the height of the geometry on input 1
@P.y += getbbox_size(1).y

# random size per point, deterministic
@pscale = fit01(rand(@ptnum + 1), 0.2, 1.0)

# a name per point
s@name = sprintf("rock_%03d", @ptnum)

# points above the middle go into the group "top"
@group_top = @P.y > getbbox_center().y

# a few octaves of noise: a Python loop over octaves, not over points
h = 0
for k in range(4):
    h += 0.5 ** k * (noise(@P * 2 ** k) - 0.5)
@P.y += h
```

## `ch()` parameters

Writing `ch("amount")` in the code adds a [custom parameter](parameters.md#custom-parameters-on-any-node) named `amount` to the node, like the "create spare parameters" button on a Houdini Wrangle. The type follows the function: `ch` / `chf` make a float, `chi` an integer, `chv` a vector and `chs` a string; `ch("amount", 0.5)` sets the default. The value is stored with the node, so `ch("amount")` reads whatever you set there, and the parameter can carry an expression, keyframes or a reference like any other.

Parameters created this way are removed again when the call disappears from the code, as long as their value is still the default and nothing is bound to them, so typing `ch("a")`, `ch("am")`, `ch("amp")` leaves only `amp`. Once you change the value, or edit the parameters in the Edit Parameter Interface dialog, they stay until you delete them; the right-click entry *delete the ch() parameters not used in the code* lists and removes the unused ones.

Inside the code, `ch` and `chf` return a float, `chi` a rounded integer, `chs` a string and `chv` a vector (`chv("dir").y` works). A vector parameter `dir` can also be read per component as `ch("dirx")`, as in Houdini. Older workflows that stored values for `ch()` fields keep them.

## Volume Wrangle and COP Wrangle

[Volume Wrangle (PCG)](../reference/modify.md#pcg-volumewrangle) runs the same language once per volume, treating each voxel as a point:

| Name | Meaning |
|---|---|
| `@value` | The voxel value (read and write). A flat column, so `@value * sin(@P.x)` works directly; to scale a vector by it write `@P * @value[:, None]`. |
| `@P` | World position of the voxel. |
| `@ix` `@iy` `@iz` | Voxel indices. |
| `volsample(name_or_index, pos)` | Sample another volume of the same geometry (trilinear, world space). |

[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle) works on an image, one row per pixel:

| Name | Meaning |
|---|---|
| `@C`, `@mask`, `@N`, ... | Image layers, read and write. New layers are created from the assigned shape (at most 4 channels). `@C.x` or `@C.r` read one channel (`.r .g .b .a` work here only). |
| `@u` `@v` | Pixel-centre coordinates 0..1 (v points up). |
| `@x` `@y` | Pixel coordinates. |
| `@res` | (width, height). |
| `@ix` | Pixel index. |

The function library is the same. With *Rows per Pass* above 0 the code runs on bands of rows to save memory; per-pixel code gives the same image, but whole-image reductions such as `@C.max()` then see one band at a time.

## Group patterns

A Group field that contains `@` is a single Wrangle-language expression returning one true/false value per element, for example `@P.y > 0 & @Cd.x < 0.5`. Unlike in Wrangle code, comparisons joined by `&` and `|` are put in parentheses for you there, so no extra brackets are needed. `rand()` and `ch()` are not available. See [Group patterns](groups.md#expression-mode).

## From VEX

| VEX | Wrangle |
|---|---|
| `@P.y += 1;` | `@P.y += 1` |
| `v@up = {0, 1, 0};` | `v@up = set(0, 1, 0)` |
| `if (@P.y < 0) @P.y = 0;` | `@P.y = max(@P.y, 0)` or `@P.y = where(@P.y < 0, 0, @P.y)` |
| `@Cd = @P.y > 0 ? {1,0,0} : {0,0,1};` | `@Cd = where(@P.y > 0, set(1, 0, 0), set(0, 0, 1))` |
| `if (@P.y > 0 && @P.x > 0) ...` | `m = (@P.y > 0) & (@P.x > 0)`, then `where(m, ..., ...)` |
| `i@group_top = @P.y > 0;` | `@group_top = @P.y > 0` |
| `s@name = sprintf("p%d", @ptnum);` | `s@name = sprintf("p%d", @ptnum)` |
| `float r = rand(@ptnum);` | `r = rand(@ptnum)` |
| `vector p = point(1, "P", @ptnum);` | `p = point(1, "P", @ptnum)` |
| `for (int i = 0; i < 4; i++) ...` | `for i in range(4):` (indented block) |
| `removepoint(0, @ptnum);` | Not available: mark the points (`@group_kill = ...`) and delete them with [Blast (PCG)](../reference/modify.md#pcg-blast). |
| `addpoint(0, pos);` | Not available: make points with [Add (PCG)](../reference/generate.md#pcg-add) or scatter them, then wrangle. |
| `// comment` | `# comment` |

## Security

Wrangle code, group expressions and the formulas of the Expression and Switch nodes are stored in the workflow and run as **Python on the ComfyUI server**, the computer that runs ComfyUI. Opening a workflow does nothing, but running one runs its code. Before anything runs, the plugin rejects the obvious ways to reach files, programs and Python internals:

- `import` and `from ... import` (`np` and `math` are already there);
- names and attributes that start with an underscore (`__class__`, `__globals__`, ...);
- numpy's file functions (`np.save`, `np.load`, `np.loadtxt`, `np.fromfile`, `tofile`, `np.memmap`, `np.lib`, ...);
- `getattr`, `eval`, `exec`, `open`, `type`, `str.format`, `global`, and the frame and code objects of generators and tracebacks.

Such code fails with an error saying what was blocked. This is a **guard, not a sandbox**: it stops the well-known tricks, not a determined attacker. As with any ComfyUI custom node that runs code, run workflows only from people you trust, and read the Wrangle nodes of a workflow from an unknown source before queueing it.

If you need something the guard blocks in your own workflows, set the environment variable `PCG_ALLOW_UNSAFE_CODE=1` before starting ComfyUI. Do not run untrusted workflows with it set.

Parameter-field expressions (the cyan fields in the panel) are not Python: they are parsed by the plugin's own small evaluator in the browser and can only call the functions listed on [Expressions](expressions.md#parameter-expressions).

## See also

- [Expressions](expressions.md): node expressions, parameter-field expressions, keyframe channels
- [Group patterns](groups.md)
- [Geometry](geometry.md): attribute classes and types
- [Keyboard and mouse](shortcuts.md): the code box and the other editors
