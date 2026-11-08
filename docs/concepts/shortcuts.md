# Keyboard and mouse

Every shortcut and mouse action the plugin adds, in one place. ComfyUI's own shortcuts (queue, copy and paste, undo, ...) are unchanged. Keys on the canvas act only when no text field has the focus.

## Network editor (canvas)

| Input | Action |
|---|---|
| **Tab** (pointer over the canvas) | Open the PCG node menu at the pointer, like Houdini's Tab menu. It lists only PCG nodes. |
| Type in the menu | Search by subsequence: `pe` finds PolyExtrude, `grcr` Group Create. |
| ↑ / ↓, Ctrl+P / Ctrl+N | Move in the list. |
| Enter | Create the node at the pointer. |
| Esc, Tab | Close the menu. |
| **Y + left-drag** | Cut every wire the drawn line crosses. Esc cancels. |
| **Alt + left-drag** on two or more selected nodes | Arrange them in a column (drag vertically) or a row (drag horizontally). Esc cancels. |
| **Shake** a node while dragging | Disconnect all its wires. |
| Press and drag the **last third** of a wire | Move its input end to another input; dropped on empty canvas it disconnects. |
| Press and drag the **first third** of a wire | Pull a new wire from the same input to choose another output. |
| **Shift** while dragging a node | Do not snap to wires and neighbours. |
| Drop a wire on a **panel cell** | Connect it to that parameter. |
| Click the **blue** square above a node | Show the node in the floating 3D panel (display flag). Again: clear it. |
| Click the **grey** square, or right-click / Ctrl+click the blue one | Use the node as the template (grey wireframe). |
| Click a COP node's **thumbnail** | Next layer (when there are several), otherwise the next display mode. |
| **Shift+click** a COP thumbnail | Next display mode: auto, clamp, signed, normalize. |
| Hover a COP thumbnail | Show the pixel value under the pointer. |

Wire style, snapping and the other canvas behaviour are described on [Wires](wires.md).

## Parameter panel

| Input | Action |
|---|---|
| Type a number, Enter | Set the value (replaces any expression, reference or keys). |
| Type a formula, Enter | Store it as an [expression](expressions.md#parameter-expressions) (the field turns cyan). |
| Esc | Abandon the edit. |
| ↑ / ↓ in a number field | Step the value; **Shift** ×10, **Ctrl** ×0.1. In a keyed field this sets a key; fields driven by an expression or reference do not step. |
| Drag left / right on a number field | Scrub the value; **Shift** faster, **Ctrl** slower. |
| **Alt+click** a field | Set a keyframe at the current frame. Alt+click the label: key the whole row. |
| **Alt+Shift+click** a field | Delete the keyframe at the current frame. |
| Hold the **middle mouse button** on an expression or reference | Show its current value. |
| Click a parameter's **label** | Toggle that row between expression and value. |
| Right-click a row or cell | Copy Parameter, Paste Relative References, keyframes, Disconnect, Revert to Defaults ... |
| `▾` next to a group or attribute field | Pick a name that exists on the upstream geometry. |
| **Tab** in a code or multi-line field | Insert 4 spaces (instead of moving the focus). |

**Ramps**

| Input | Action |
|---|---|
| Click an empty spot | Add a key there and keep dragging it. |
| Drag a key | Move it (left / right = position, up / down = value on a float ramp). |
| Double-click a colour key | Pick its colour. |
| Right-click a key, or Delete / Backspace | Remove the selected key (one always remains). |
| ← / → | Select the previous / next key. |

**Edit Parameter Interface dialog**: Esc closes it; Delete removes the selected parameter (when no field is being edited).

## 3D viewport and floating panel

| Input | Action |
|---|---|
| Left drag | Tumble. |
| Middle drag | Track (pan). |
| Right drag, mouse wheel | Dolly. |
| Double-click, **F** / **G** / **H** / Home | Frame all. |
| **1** / **2** / **3** / **4** | Perspective / top / front / right view (also leave the UV view). |
| **5** | UV view on / off. In the UV view: left or middle drag pans, right drag or the wheel zooms (about the pointer), **F** frames the layout. |
| **Alt** or **Space** + left drag | Tumble, even while a handle or the curve tool is active. |

Keys act while the pointer is over the view, also when a toolbar menu of the panel still has focus; only a text box being typed in keeps its keys.

**Handles** (select a node that has one, see [Handles](viewing-and-export.md#handles)):

| Input | Action |
|---|---|
| **T** / **R** / **E** | Translate / rotate / scale handle. |
| Drag an arrow / square / centre circle | Move along an axis / in a plane / in the screen plane. |
| Drag a ring | Rotate. |
| Drag a scale box / the centre box | Scale along an axis / uniformly. |
| **Ctrl** while dragging | Snap: a tenth of the grid unit, 15 degrees, steps of 0.1. |

**Curve tool** (select a Curve node):

| Input | Action |
|---|---|
| Click empty space | Add a point at the end (on the geometry under the pointer, or on the construction plane). |
| Drag a point | Move it. **Shift**: snap to the surface; **Ctrl**: snap to a tenth of the grid unit. |
| **Ctrl+click** a segment | Insert a point. |
| **Delete** / Backspace over a point | Remove it. |
| Click the first point | Close the curve. |

## Playbar

Shown when the graph has a [Frame (PCG)](../reference/param.md#pcg-frame) node.

| Input | Action |
|---|---|
| **Space** | Play / pause. |
| **←** / **→** | Previous / next frame. |

These act only when no text field has the focus and no modifier key is held; the keyboard button on the playbar turns them off.

## Geometry Spreadsheet

The mouse wheel scrolls the table (not the canvas); the tabs switch between point, vertex, primitive and detail.

## See also

- [Wires](wires.md)
- [Parameters](parameters.md)
- [Viewing and export](viewing-and-export.md)
- [Loops and time](loops-and-time.md)
