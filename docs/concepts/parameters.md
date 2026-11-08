# Parameters

comfyui_pcg replaces ComfyUI's one-widget-per-line node body with a Houdini-style parameter panel: readable labels, tabs and collapsible folders, vector rows, colour swatches, ramp editors, and parameters that hide or grey out depending on the current mode. On top of the panel it adds Houdini's parameter linking: Copy Parameter / Paste Relative References, expressions and keyframes in fields, and a controller node, Parameters (PCG), with an Edit Parameter Interface dialog. This page explains how all of that works and what it means for saved workflows.

The plugin's menu entries and settings use Houdini's English terms (for example *Paste Relative References*). Every shortcut is listed on [Keyboard and mouse](shortcuts.md).

## The panel

The panel is drawn over the node's original ComfyUI widgets, which stay on the node but hidden. Every control reads and writes those widgets, so a workflow saved with the panel is identical to one saved without it, and undo, API prompts and other extensions see ordinary widget values.

| Element | Behaviour |
|---|---|
| Labels and menus | Houdini's names (*Attribute Class*, *Ramp from Attribute*). The internal parameter name is listed in the [reference](../reference/README.md) next to each label. |
| Tabs | Used where Houdini uses tabs (PolyExtrude: *Extrusion*, *Output Geometry and Groups*, ...). |
| Folders | Collapsible sections. A folder with an enable toggle in its header (Houdini's *Enable*) collapses when switched off, and switching it off means "this section is at its defaults", not "this feature is gone". |
| Vector rows | `x y z` triples (Translate, Rotate, Scale, Size, Center ...) on one row; also string vectors such as `"0.5 0.5"`. |
| Colours | A swatch plus three numbers; click the swatch for the colour picker. |
| Toggle + value | Optional values have their toggle in front (`[x] Force Total Count [1000]`); the value is greyed out when off. |
| Hide / disable rules | Parameters the current mode does not use are hidden (Houdini's *hidewhen*) or greyed out (*disablewhen*). The node grows and shrinks accordingly. The reference lists each rule as *Hidden when* / *Disabled when*. |
| Name fields | Group and attribute fields have a `▾` button that lists the names existing on the upstream geometry (after the upstream has run once). |
| Multi-line text | Grows with its content; Tab indents. |

Number fields:

- type a value, or a formula such as `2*pi` or `1/3` (see [Parameter expressions](expressions.md#parameter-expressions));
- drag left/right on the field to scrub the value (Shift faster, Ctrl slower);
- Up / Down arrow keys step the value;
- fields with a small range also show a slider.

### Ramps

Ramp parameters (colour or float) get a ramp editor instead of a text line.

- **Float ramp:** a curve area with grid lines. Every key is a handle on the curve; drag it left/right to change its position and up/down to change its value.
- **Colour ramp:** a colour bar with coloured key markers underneath; drag markers left/right, **double-click** a marker to pick its colour.
- Click on an empty spot to add a key (it takes the current value there) and keep dragging it.
- Right-click a key, or select it and press Delete / Backspace, to remove it (at least one key remains).
- Left / Right arrows change the selected key. The interpolation menu is inside the editor.

The ramp is still saved as the same line of text (`position:value` entries), so older workflows load unchanged.

### Nodes without the panel

The panel does not take over nodes with a code editor (Wrangle, Volume Wrangle, Attribute Adjust), the Parameters (PCG) declaration node, Geometry Spreadsheet, and nodes without parameters. To go back to native widgets everywhere, change the PCG *parameter panel* setting in ComfyUI's settings to native (reload the page afterwards); for a single node, use its right-click entry that switches the panel to native widgets.

### Connecting wires to parameters

ComfyUI's own way of driving a parameter from another node's output still works with the panel:

- Drop a wire **on the cell** you want; it connects to that parameter (the cell is outlined in yellow while dragging). Dropping on a row label connects to the first compatible parameter of the row.
- The input dot is aligned to the panel row.
- A connected cell shows `⇠ source.output` (purple, read-only). Disconnect to get the value back.

Wires are evaluated on the server at run time and work with the API; panel references and expressions (below) are evaluated in the browser.

## Linking parameters

### Copy Parameter / Paste Relative References

Right-click a row or a single cell of the panel:

| Entry | Effect |
|---|---|
| Copy Parameter | Remembers the node and parameter(s). Right-click on the **label** copies the whole row (all three components of Translate); on a **cell**, just that one. |
| Paste Copied Values | Copies the values once; no link. |
| Paste Relative References | The target now follows the source (Houdini would write `ch("../box1/tx")`). |
| Delete Channels | Removes the reference or keys; the current value stays and the cell becomes editable. |
| Disconnect | Shown when the cell has a wire. |
| Revert to Defaults | |
| Promote | Shown when the graph has a Parameters (PCG) node; see below. |
| Set Keyframe / Delete Keyframe | See [Keyframes](expressions.md#keyframes). |

A whole row pasted onto a whole row pairs components (x to x, y to y, z to z); a single parameter pasted onto a row references it from every component. Paste skips targets that would create a cycle, have an incompatible type (a menu onto a number), or reference themselves.

A referenced cell is **cyan**, cannot be edited directly, and shows the expression (for example `ch("../box1/size_x")`). Hold the middle mouse button on it to see the value; click the row label to toggle expression / value for the row. You can click into a referenced cell and edit the expression, for example to append `* 2`.

References are stored by node id, not title: renaming the source keeps the link, and copying both nodes together keeps the copy pointing at the **original** source, as in Houdini. If the source node is deleted, or its parameter is now driven by a wire, the reference is marked with a question mark and the target keeps its last value.

The same operations are available from the node's right-click menu when native widgets are used (entries starting with `PCG:`).

### Reference lines

When you select a node, a faint dashed line is drawn between it and every node it has a parameter reference with, in both directions, as in Houdini's network view. Pasted references, Parameters-panel bindings, and node paths written in expressions and templates (`ch("../box1/tx")`, `npoints("../box1")`) all count. Keyframes, references to the node itself and paths computed at run time (`opinputpath()`) do not. The lines can be turned off in the PCG settings.

### How references are evaluated

References, expressions, templates and keyframes are all **materialised in the browser**: when a source value changes (or just before the graph is queued), the computed value is written into the target node's real widget. Consequences:

- The prompt sent to the server contains exactly the values you see, and ComfyUI's cache invalidates only nodes whose values actually changed.
- In a saved workflow the links are stored in the node's properties, and the last computed values are stored as normal widget values.
- Running a workflow through the API or headless **does not re-evaluate links**; it uses the last materialised values. Use wires (or Param Pick, below) for anything that must be computed on the server.

## Parameters (PCG): a control node

[Parameters (PCG)](../reference/param.md#pcg-parameters) plays the role of a Houdini null with spare parameters: one place that holds the radius, seed, count and so on of the whole graph, which other nodes reference. It is declared as text, one parameter per line:

```text
<type> <name> [= default] [: min max] [# label]

float  radius = 1.0 : 0 10   # Radius
int    count  = 5   : 1 100
bool   cap    = true
string prefix = piece
vector pos    = 0 0 0
vector4 col   = 1 1 1 1
string dir    = "C:/out#1"    # quotes protect # and : in a default
```

- Types: `float`, `int`, `bool`, `string`, `vector` (3 components), `vector4`. Short forms are accepted: `f i b s v vec v3 vec3 v4 vec4`, and `toggle`, `str`, `vector3`.
- Names must start with a letter or underscore and contain only letters, digits and underscores. Duplicate names are an error.
- Lines starting with `#` or `//` are comments.
- A single number as a vector default fills all components. Vector components may be separated by spaces or commas.
- `: min max` gives a range (number types only); values are clamped to it and the field gets a slider.
- `bool` accepts `true/false`, `1/0`, `yes/no`, `on/off`.

The node grows a control for each line. Its `json` output carries all current values; its `schema` output describes them (type, default, range, label) for use in prompts. The node does not need to be connected to anything; it is a panel.

### Edit Parameter Interface

Instead of writing the text by hand, click **Edit Parameter Interface...** on the node (or the first entry of its right-click menu). The dialog has Houdini's three columns:

- **Create Parameters:** Float, Integer, Toggle, String, Float Vector 3, Float Vector 4. A new parameter is inserted after the selected one, named `newparameter` (then `newparameter2` ...), with the name field focused.
- **Existing Parameters:** select, drag to reorder (or use the arrows), duplicate, delete. Each entry shows its label, name, type and **how many places reference it**.
- **Parameter Description:** Name, Label, Type, Default and an optional Range. Invalid entries (bad or duplicate name, non-numeric default, reversed range) turn red with a message, and Apply / Accept are disabled until fixed.

**Apply** writes the changes and keeps the dialog open, **Accept** writes and closes, **Cancel** or Esc discards. The whole edit is one undo step. The dialog is only an editor for the declaration text: comment lines and blank lines are kept, and a broken line shows up in red so you can fix it.

**Renaming keeps references.** When you rename a parameter in the dialog, every reference to it from this panel (name bindings, `ch()` in expressions and templates) is updated, and the stored value moves to the new name. Deleting a parameter does not fix references for you; the referencing cells get a question mark and keep their value.

### Using the control node

- **Reference a panel parameter** in any field: `ch("../CTRL/radius")`, `ch("../CTRL/pos.y")` (components `x y z w`, `r g b a` or `0 1 2 3`).
- **Promote** a parameter: right-click it and choose Promote. A line with the parameter's name and current value is appended to the (first) Parameters node, and the parameter is bound to it.
- **Bind** with the right-click menu: on the target node, the `PCG:` bind entry lists its parameters and the panel's parameter names; or copy a panel parameter's reference on the Parameters node and paste it on the target.

Bindings by name are looked up across all Parameters nodes; if two panels declare the same name, the one earlier in the graph wins. One panel per graph, with name prefixes (`rock_radius`) for grouping, is the simplest setup.

## Custom parameters on any node

Any node can get extra parameters of its own, like spare parameters on a Houdini node: right-click the node and choose **PCG: Edit Parameter Interface...**. It is the same dialog as for Parameters (PCG), with the same types, ranges, labels, reordering and checks. The parameters appear at the end of the node's panel (in a *Spare* section, or a *Spare* tab when the node has tabs) and, for nodes without the panel, as the last widgets on the node.

They behave like the node's own parameters: drag them, type expressions, set keyframes, copy and paste references. Refer to them from the same node as `ch("amp")` and from other nodes as `ch("../wave1/amp")`. A vector parameter is split into components with Houdini's names: `vector pos` becomes `posx`, `posy`, `posz`, so the references are `ch("posx")` and so on. Names may not repeat the node's own parameter or input names.

Renaming a custom parameter in the dialog updates every reference to it: pasted references, `ch()` paths in other nodes' expressions and templates, the node's own `ch("amp")`, and expressions or keyframes set on the parameter itself. The stored value moves to the new name.

The declaration and the values are kept in the node's properties (`pcg_spare`, `pcg_spare_vals`), by name, so adding or removing custom parameters never shifts the node's normal parameter values in the saved workflow, and copied nodes keep them. The server does not see them as inputs. Their effect comes from references and expressions, which are evaluated in the browser like any other. The exceptions are the three Wrangle nodes (geometry, volume and COP), which receive all custom parameter values and read them with `ch()`; see [`ch()` parameters](wrangle.md#ch-parameters).

## Filling parameters from JSON

Two nodes take parameter values from JSON text, typically written by a language model:

- [Params from JSON (PCG)](../reference/param.md#pcg-paramsfromjson) writes the values into the Parameters panel. Only declared names are applied; unknown keys, wrong types and out-of-range values are reported (out-of-range values are clamped). Because the values are written in the browser, the run that receives the JSON still uses the old values: **run a second time** to use them. It never re-queues automatically.
- [Param Pick (PCG)](../reference/param.md#pcg-parampick) extracts one value (`radius`, `a.b`, `pos.y`) and outputs it as float, int and string, to be wired into a parameter. It takes effect in the same run. A missing key is an error unless *fallback* is on.

Both accept loosely formatted JSON (code fences, a sentence before the object, trailing commas) and report what was repaired.

## Other network-editor behaviour

These are separate from parameters but come with the same front end; see [Wires](wires.md) and [Keyboard and mouse](shortcuts.md):

- **Wire style:** wires are drawn as Houdini-style rounded elbows; you can switch back to ComfyUI's own link style.
- **Re-wiring by dragging a wire end:** press on the first or last third of a wire and drag to move that end to another node (dropped on empty canvas: the input end disconnects, the output end leaves the wire as it was).
- **Snapping:** while dragging a node it snaps so that wires become straight and edges align with nearby nodes (hold Shift to disable).
- **Original type of renamed nodes:** a renamed node shows its original type after the title.

## See also

- [Expressions](expressions.md): expression syntax in fields, templates, keyframes and channels
- [Wires](wires.md) and [Keyboard and mouse](shortcuts.md)
- [Getting started](../getting-started.md)
- [Houdini users](../houdini-users.md)
- Reference: [Parameters & Expressions](../reference/param.md)
