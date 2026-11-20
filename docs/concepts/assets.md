# Digital assets

A digital asset is a group of nodes folded into one node, with the parameters you choose on its parameter pane: Houdini's HDA. comfyui_pcg builds assets on ComfyUI's subgraphs and adds the parameter interface, references across the asset's boundary, and updating instances from the library.

## Making one

1. Select the nodes and choose **Convert to Subgraph** from the selection toolbar or the node menu. The nodes become one node; double-click it, or use its enter icon, to go inside.
2. Right-click the new node and choose **PCG: Edit Asset Interface…** (Houdini's Type Properties):
   - **Nodes inside** (left) lists every parameter of every node inside. Pick one and press **→**, or double-click it, to promote it to the asset.
   - **Asset parameters** (middle) is the asset's interface, in order. **↑ ↓** reorder, **Remove** demotes a parameter (the node inside keeps the value it had).
   - **Parameter** (right) edits the selected one: label, folder (a tab), section, minimum, maximum, default (used by Revert to Defaults), *Hide when* and *Disable when* rules written with the asset's parameter names (`{ mode == ramp }`, `{ size_x < 1.5 }`), and a help text.
3. **Apply**. Select the asset: its parameters are in the docked pane.

A promoted parameter takes the look of the parameter it drives inside: its label, slider and range, menu labels, and its kind (vector, colour, ramp). When all three components of a vector are promoted they form one row again. ComfyUI's own **Promote Widget** (right-click a parameter inside) promotes too; the interface picks it up.

On the canvas an asset is as compact as any node: its title, its inputs and outputs, and a row per promoted parameter that is wired from outside.

The interface is stored on the asset's definition, so every instance of that definition in the workflow shows the same parameters; the values are per instance. It is also copied onto each instance, so it travels where ComfyUI copies an instance (copy and paste, Publish Subgraph).

## The library

**Publish Subgraph** (selection toolbar or node menu) saves the asset in your node library (the `subgraphs` folder of your ComfyUI user data); insert it from the node library like any node. As in Houdini, the asset is known by its name.

ComfyUI gives each inserted or pasted instance its own copy of the definition, so instances do not follow the library by themselves. When the library has another version of an asset, a blue **⟳** appears in the parameter pane's title bar while one of its instances is selected; click it, or choose **PCG: Update Asset from Library** from the instance's node menu, to bring every instance of that name in the workflow to the library's version. Each instance keeps its parameter values. To change the library's version, edit the published asset from the node library (ComfyUI's *Edit* entry) and save it.

## Inside an asset

Paths in expressions and references are relative, as in Houdini:

| Path | Means |
|---|---|
| `ch("../box1/tx")` | Parameter `tx` of node `box1` next to this node (in the same network). |
| `ch("../tx")` | Parameter `tx` of the asset this node is inside. |
| `ch("../../ctl/amp")` | Parameter `amp` of node `ctl` next to the asset (one network up). |
| `ch("../rock/box1/sx")` | From outside: parameter `sx` of node `box1` inside the asset `rock`. |

The same paths work for node paths in geometry queries (`npoints("../box1")`, `opname("..")`). They are stored by node id, so renaming a node or the asset does not break them. One parameter of the asset can drive several nodes inside this way, with an expression each, where Promote Widget connects one parameter to one.

The parameter pane's title bar shows where a node inside an asset sits, as `/rock/box1`.

The display flag works inside an asset: clicking it puts a Display node into the asset's network, which runs as part of the asset; the 3D panel shows its result. Cook times, the middle-button info and the performance pane (see [Network feedback](network.md)) cover the nodes inside assets too.
