# Guide for Houdini users

If you know Houdini, most of comfyui_pcg will feel familiar: the same geometry model (points, vertices, primitives, detail), the same attribute names, Houdini's node names and parameter labels, display flags, a Copy Parameter / Paste Relative References workflow and a Copernicus-style image context. The differences come from two places: the plugin is written in Python and numpy rather than being Houdini, and it runs inside ComfyUI, whose graph is evaluated very differently from a Houdini network. This page lists what carries over directly, the systematic differences, and how to find the node you are looking for.

## Naming

- Every node's display name is the Houdini name followed by **(PCG)**: *PolyExtrude (PCG)*, *Copy to Points (PCG)*, *Attribute Promote (PCG)*. Image nodes are prefixed **COP**: *COP Blur (PCG)*, *COP HeightField Terrace (PCG)*.
- Several Houdini nodes are sometimes combined into one node with a mode menu; for example Twist, Bend and Taper are modes of [Twist / Bend / Taper (PCG)](reference/deform.md#pcg-deform), and Attribute Remap is covered by [Attribute Adjust (PCG)](reference/attribute.md#pcg-attribadjust).
- Where the plugin's node of the same name does something different from Houdini's, a second node with the suffix **· Houdini** follows Houdini's behaviour, for example [Cross Section Surface · Houdini (PCG)](reference/generate.md#pcg-crosssectionsurfacehou).
- Parameter labels and menu entries in the panel use Houdini's wording. The internal parameter names (`tx`, `size_x`, `rand_seed`) are what `ch()` and saved workflows use; the [reference](reference/README.md) lists both.
- The internal node type is `PCG_<Name>`, shown on renamed nodes and in saved workflows.

**To find the equivalent of a Houdini node**, use the [Houdini node index](reference/houdini-index.md): it lists Houdini SOPs and Copernicus COPs with the comfyui_pcg node to use and whether it is a full or partial equivalent. Each node's reference entry has a *Compared with Houdini* section for known differences.

## What carries over

| Houdini | comfyui_pcg |
|---|---|
| Points, vertices, primitives, detail; attribute classes | Same model. See [Geometry](concepts/geometry.md). |
| `P`, `N`, `Cd`, `uv`, `pscale`, `orient`, `up`, `v`, `scale`, `rot`, `pivot`, `trans`, `transform`, `name` | Same names and meanings; quaternions are (x, y, z, w). Copy to Points combines them in Houdini's order. |
| Group field: names, numbers, ranges `0-20:3`, `!` / `^` exclusion, `@P.y > 0` | Same idea; see the differences below and [Group patterns](concepts/groups.md). |
| Group types: point, primitive, vertex, edge | Same; edge groups survive topology edits as long as their points do. |
| Y-up, grid in the XZ plane | Same. Transform's default rotate order is Rx Ry Rz, as in Houdini. |
| Attribute Wrangle | [Wrangle (PCG)](reference/attribute.md#pcg-wrangle) with `@attr` syntax and many VEX function names, but Python, not VEX (below). |
| Block Begin / Block End | [For-Each Begin / End (PCG)](reference/loop.md#pcg-foreachbegin), with pieces, points, primitives, connectivity or count, Fetch Feedback, Single Pass. |
| SOP Solver | [For-Each Frame Begin / End (PCG)](reference/loop.md#pcg-foreachframebegin) with method *Fetch Feedback (Solver)*. |
| Display and template flags | Blue and grey squares above each node; see [Viewing and export](concepts/viewing-and-export.md). |
| Geometry Spreadsheet | [Geometry Spreadsheet (PCG)](reference/output.md#pcg-geospreadsheet), in the node body. |
| Null with spare parameters, Edit Parameter Interface | [Parameters (PCG)](reference/param.md#pcg-parameters) with an Edit Parameter Interface dialog; see [Parameters](concepts/parameters.md). |
| Spare parameters on any node, Wrangle's "create spare parameters" button | Right-click any node, **PCG: Edit Parameter Interface...**; Wrangle `ch()` calls create them automatically. See [Custom parameters on any node](concepts/parameters.md#custom-parameters-on-any-node). |
| Copy Parameter / Paste Relative References, `ch()`, HScript expressions, `$F`, keyframes | In the panel, with the same menu, `ch("../node/parm")` paths, degree-based trig and Alt+click keys; see [Expressions](concepts/expressions.md#parameter-expressions). |
| Switch with lazy branches, Switch-If | [Switch (PCG)](reference/modify.md#pcg-switch) (only the chosen branch runs; `detail(-1, ...)` reads the control input), [Switch-If (PCG)](reference/modify.md#pcg-switchif). |
| File Cache | [File Cache (PCG)](reference/output.md#pcg-filecache), `.npz` files; when reading, the upstream does not run. |
| Copernicus layers (`C`, `mask`, ...), v up, unclamped float | Same conventions in `COPIMAGE`; see [Images](concepts/images.md). |

## Systematic differences

### No VEX: Wrangle is vectorised Python

Wrangle code is Python with numpy, run **once over all elements**, not once per element. `@P` is the whole column of positions.

- No per-element `if`; use `where(cond, a, b)` or masks. Python's `and` / `or` do not work on columns; use `&`, `|`, `~`.
- Trigonometry is in radians, as in VEX.
- `rand(seed)` behaves like VEX (same seed, same number) and is combined with the node's *Rand Seed*.
- `point()`, `prim()`, `detail()`, `npoints()` and friends read the node's inputs by number, as in VEX; there are four inputs.
- `ch("name")` in Wrangle code reads a parameter **of that Wrangle node** (created automatically), not another node's parameter. Wire values in, or reference them from a panel field, to bring outside values into the code.
- There is no `@group_name` syntax for writing groups and no `setpointgroup()`; create groups with Group Create and an `@` expression.

See [Wrangle syntax](concepts/wrangle.md).

### Data model limits

- **Packed primitives, simplified.** Pack / Unpack, Assemble and Copy to Points' *Pack and Instance* exist, the viewport instances them and Export Mesh writes them as glTF GPU instances, but only Transform, Merge, Blast / Delete, Sort and the point attribute / group nodes keep them packed; every other node unpacks its input automatically. There are no packed disk primitives, Assemble's packed pieces carry no `path` attribute, and there are no intrinsics beyond the transform.
- **VDBs are dense grids with VDB semantics.** The VDB and Volume SOPs are on the [Volumes & VDB](reference/volume.md) page; a VDB here has an active mask and a background like OpenVDB, but stores every voxel, so very large sparse grids cost memory. Grids are axis aligned (VDB Transform resamples a rotation) and there are no frustum grids or VDB Points (points are points).
- **NURBS / Bezier** curves and surfaces exist with uniform clamped knots only; Convert, Carve, Resample and a few generators support them. NURBS surface modelling (projection, surface intersections) is not available.
- **Height fields are images.** Houdini's HeightField SOPs correspond to COP HeightField nodes working on an image layer (default `C`), not to volumes.
- **No array or dictionary attributes**, and strings created by Attribute Create or Wrangle are limited to 64 characters.
- No metaballs, tetrahedra, agents, KineFX, Vellum, Pyro or RBD solvers.

### The group field

- A pattern is **either** tokens (names, numbers, ranges, exclusions) **or**, if it contains `@`, a single expression. `@P.y > 0 top` does not mix them as Houdini can.
- Group names do not take wildcards in Group fields (`piece*` is an error); Group Combine does accept them.
- Edge fields accept only edge-group names (no point-pair or number syntax), and unknown edge-group names are silently ignored.
- In Group Combine, `^` means symmetric difference, while in a Group field `^` means exclude.

### ComfyUI evaluates graphs differently

| Houdini | ComfyUI / comfyui_pcg |
|---|---|
| A node cooks when something looks at it (display flag, downstream request). | Pressing **Run** executes only nodes that lead to an **output node** (Viewport, Display, Preview Image, an export node ...). The display flag works by rewiring a Display (PCG) node to the flagged node. |
| Changing a parameter re-cooks interactively. | Nothing runs until the graph is queued. Results are cached by input values, so a new run recomputes only what changed. The display flag and the playbar can queue automatically. |
| `$F` is global; every node can depend on time. | Time comes from a [Frame (PCG)](reference/param.md#pcg-frame) node and travels along wires, so ComfyUI can see which nodes depend on it. The playbar writes the frame into Frame nodes and re-runs. `$F` in panel fields works because the value is computed in the browser and written into the parameter. |
| A network cooks per frame during playback. | One run computes one frame. To compute many frames at once (sequences, motion vectors, solvers), use For-Each Frame. |
| `ch()` references are tracked by the network. | References, expressions and keyframes in panel fields are evaluated in the browser and written into the parameters before the run. Running the workflow through the API does **not** re-evaluate them; it uses the last written values. Wires are evaluated on the server. |
| Expressions can read any node's geometry on demand. | Geometry-reading functions in fields (`npoints("../box1")`, `bbox()`, `point()`) read the referenced node's **last run**, so a change upstream needs a second run to show up. |
| Block settings live on Block End; zero iterations skip the body. | Iteration settings live on For-Each Begin; with zero iterations the body still runs once on empty geometry, because a ComfyUI graph always executes. |
| Subnetworks and digital assets. | No plugin-specific subnetworks. Use ComfyUI's own subgraphs to package nodes, and Parameters (PCG) for a shared control panel. |
| Null, Output and Object Merge nodes. | Not needed: a wire can go anywhere, and one output can feed any number of inputs. |
| Geometry is saved in the `.hip`. | Geometry is not stored in the workflow; it is recomputed after a restart unless written with File Cache. |
| Randomness can come from anything. | Random nodes take an explicit seed (`rand_seed`); results are reproducible and never change between runs on their own. |

### Viewport and interaction

Selecting a Transform, a generator such as Box or Grid, or a few other nodes shows a translate / rotate / scale handle in the viewport, and selecting a Curve (PCG) node turns the viewport into a curve drawing tool (see [Handles](concepts/viewing-and-export.md#handles)). Handles edit the node's parameters. **S** gives a select mode: click / box selection of points or primitives becomes a group expression you can copy or turn into a Group Create node (see [Selecting](concepts/viewing-and-export.md#selecting)); there is no brush tool, and a selection does not feed nodes by itself the way Houdini's viewport state does. The viewer uses Houdini's mouse layout (left tumble, middle track, right dolly; Alt + left tumbles while a handle is active) and the camera bar can lock a camera to the view.

## Mapping cheat sheet

| You want | Use |
|---|---|
| Find any Houdini node | [Houdini node index](reference/houdini-index.md) |
| A quick per-element formula | [Wrangle (PCG)](reference/attribute.md#pcg-wrangle) or [Attribute Create (PCG)](reference/attribute.md#pcg-attribcreate) with an expression |
| One slider that drives many nodes | [Parameters (PCG)](reference/param.md#pcg-parameters) + Paste Relative References |
| A value computed on the server and wired into parameters | [Value (PCG)](reference/param.md#pcg-value), [Expression (PCG)](reference/param.md#pcg-expr), [Channel (PCG)](reference/param.md#pcg-channel) |
| Animation | [Frame (PCG)](reference/param.md#pcg-frame) + playbar, keyframes in fields, or For-Each Frame for sequences |
| Instancing for a game engine | [Export Instances (PCG)](reference/output.md#pcg-exportinstances) |
| Getting meshes out | [Export Mesh (PCG)](reference/output.md#pcg-exportmesh) (`.glb` / `.obj`) |
| Getting meshes in | [Import Mesh (PCG)](reference/convert.md#pcg-importmesh) (OBJ, PLY, STL, glTF) |

## See also

- [Getting started](getting-started.md)
- Concepts: [Geometry](concepts/geometry.md), [Group patterns](concepts/groups.md), [Expressions](concepts/expressions.md), [Parameters](concepts/parameters.md), [Loops and time](concepts/loops-and-time.md), [Images](concepts/images.md), [Viewing and export](concepts/viewing-and-export.md)
- [Houdini node index](reference/houdini-index.md) and [Node reference](reference/README.md)
