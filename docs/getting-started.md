# Getting started

comfyui_pcg is a ComfyUI custom-node package that brings Houdini-style procedural modelling into ComfyUI: over 400 nodes, most of them modelled on Houdini geometry nodes (SOPs) or Copernicus image nodes (COPs), implemented in numpy, with Houdini-style parameter panels, display flags, a 3D viewport and a timeline. This page covers installation, building and viewing a first graph, where the nodes are in the menu, how the parameter panel works at a glance, and where output files go.

## Installation

1. Copy (or `git clone`) the `comfyui_pcg` folder into ComfyUI's `custom_nodes` folder, so that you have `ComfyUI/custom_nodes/comfyui_pcg/__init__.py`.
2. Install the Python requirements **into the Python that runs ComfyUI**:

   ```bash
   # regular installation (activate ComfyUI's virtual environment first)
   python -m pip install -r ComfyUI/custom_nodes/comfyui_pcg/requirements.txt

   # Windows portable build: it has its own Python
   python_embeded\python.exe -m pip install -r ComfyUI\custom_nodes\comfyui_pcg\requirements.txt
   ```

   `requirements.txt` lists `numpy`, `trimesh` and `scipy` (scipy already comes with ComfyUI; the volume / VDB nodes use it). Installing packages into the system Python does nothing for the portable build.
3. Restart ComfyUI, then reload the browser page.

### Optional packages

The core nodes need only numpy. A few nodes need an extra package and raise an error with the exact `pip install` command when it is missing:

| Package | Needed by |
|---|---|
| `manifold3d` | [Boolean (PCG)](reference/modify.md#pcg-boolean), [Boolean Fracture (PCG)](reference/modify.md#pcg-booleanfracture) |
| `fonttools` | [Font (PCG)](reference/generate.md#pcg-font) |
| `torch` | Already part of ComfyUI. Used by [Geometry Preview (PCG)](reference/output.md#pcg-previewimage), [Regional Prompt from COP (PCG)](reference/cop-layers.md#pcg-regionalprompt) and the CPU / CUDA backends of the image nodes. |

### GPU

Geometry nodes run on the CPU. Image (COP) nodes can run on the GPU through torch, which ComfyUI already uses; with the default *Auto* device they switch to CUDA by themselves for images of 256 x 256 pixels or more when a CUDA device is available. See [Images: devices and backends](concepts/images.md#devices-and-backends). [COP Info (PCG)](reference/cop-utility.md#pcg-copinfo) tells you whether CUDA is available.

### Updating

After updating the plugin, restart ComfyUI (Python changes) and reload the page (front-end changes). Some front-end settings, such as switching the parameter panel style, also take effect only after a page reload.

### Offline use

The 3D viewport uses three.js. It loads `web/vendor/three.module.js` from the plugin folder if present and otherwise fetches three.js 0.160.0 from a CDN. On a machine without internet access, place that file in `web/vendor/`.

## Finding nodes

Every node's display name ends in **(PCG)**: *Box (PCG)*, *Copy to Points (PCG)*, *COP Noise (PCG)*. Image nodes additionally start with **COP**. Double-click the canvas and type a name, or browse the **Add Node** menu under **PCG**:

| Menu category | Contents |
|---|---|
| `PCG/generate` | Primitives, curves, text, L-systems, volumes |
| `PCG/modify` | Modelling: extrude, bevel, boolean, clip, fuse, merge, transform, subdivide, switches, volume operations ... |
| `PCG/deform` | Point deformers |
| `PCG/topology` | Connectivity, paths, edges |
| `PCG/attribute` | Attribute nodes, Wrangle |
| `PCG/group` | Group nodes |
| `PCG/scatter` | Scatter, copy and instancing |
| `PCG/uv` | UV projection, unwrapping, layout |
| `PCG/convert` | Import, JSON, conversions |
| `PCG/render` | Cameras, render sequences, back-projection |
| `PCG/output` | Viewport, Display, spreadsheet, preview, export, file cache |
| `PCG/loop` | For-Each and frame loops, sequence tools |
| `PCG/param` | Value, Expression, Frame, Channel, Parameters |
| `PCG/image` | Heightfield from Image |
| `PCG/cop` | All image (COP) nodes |

The [node reference](reference/README.md) groups the same nodes by topic and shows each node's menu category. If you know the Houdini node you want, look it up in the [Houdini node index](reference/houdini-index.md).

## A first graph

1. Add **Box (PCG)**. Leave the defaults (a 1 x 1 x 1 box).
2. Add **Transform (PCG)** and connect Box's `geo` output to its `geo` input. Set *Translate* y to `0.5` and *Rotate* y to `30`.
3. Look at the result in one of these ways:
   - **Display flag:** click the small **blue square** above the Transform node's title bar. A Display (PCG) node is created and connected for you, the graph is queued, and the result appears in the floating 3D panel. Click the blue square on Box to look at Box instead.
   - **Viewport node:** add **Viewport (PCG)** after Transform and press **Run**. The 3D view is drawn inside the node.
   - **Image:** add **Geometry Preview (PCG)** after Transform and connect its `image` output to ComfyUI's **Preview Image** (or Save Image). Press Run.
4. Drag in the viewer to look around: left button tumbles, middle button pans, right button or the wheel zooms, double-click frames the geometry.

From here, a typical next step is Grid, Scatter and Copy to Points; see [Geometry](concepts/geometry.md) for the data model and [Loops and time](concepts/loops-and-time.md) for variations per piece.

Only nodes that lead to an output node (Viewport, Display, Preview Image, an export node ...) are executed when you press Run. A chain that ends in nothing does not run, which is why the display flag works by connecting a Display node.

## The parameter panel at a glance

PCG nodes show a Houdini-style panel instead of ComfyUI's plain widget list:

- Labels and menu entries use Houdini's names; vectors such as Translate are on one row; colours have a swatch; ramps have an editor.
- Parameters that the current mode does not use are hidden or greyed out, and the node resizes.
- Click a number to type a value or a formula (`2*pi`, `ch("../box1/size_x") * 2`, `$F * 10`); drag sideways to scrub (Shift faster, Ctrl slower); Up / Down step.
- Right-click a parameter for **Copy Parameter**, **Paste Relative References**, keyframes and **Revert to Defaults**. Alt+click sets a keyframe.
- Group and attribute fields have a `▾` that lists the names found upstream after a run.
- Wires from other nodes can be dropped directly onto a parameter cell.

The underlying ComfyUI widgets are unchanged, so workflows saved with the panel load anywhere. Plugin-specific menu entries and settings use Houdini's English terms. See [Parameters](concepts/parameters.md) for the details and for switching back to native widgets, and [Keyboard and mouse](concepts/shortcuts.md) for all shortcuts (Tab opens the PCG node menu, Y + drag cuts wires).

## Where outputs go

- **Files** written by export nodes ([Export Mesh](reference/output.md#pcg-exportmesh), [Export Instances](reference/output.md#pcg-exportinstances), [COP Write File](reference/cop-utility.md#pcg-copwritefile), [File Cache](reference/output.md#pcg-filecache)) go into ComfyUI's **output** folder; file names are relative to it (for example `pcg/mesh.glb`). Export nodes return the path they wrote.
- **Images** become ComfyUI `IMAGE`s through [Geometry Preview](reference/output.md#pcg-previewimage) or [COP Export](reference/cop-utility.md#pcg-copexport), and are previewed or saved with ComfyUI's own nodes.
- **Geometry** stays in memory and is not stored in the workflow file. After restarting ComfyUI it is recomputed on the next run unless you cache it with File Cache.

## Example workflows

The plugin ships example workflows in its `example_workflows` folder, including a numbered series of tutorials (`tutorial_01_first_geometry.json` and onward) and larger production examples. Open them through ComfyUI's workflow browser or by dragging the JSON file onto the canvas.

## See also

- [Geometry](concepts/geometry.md), [Group patterns](concepts/groups.md), [Expressions](concepts/expressions.md), [Wrangle syntax](concepts/wrangle.md), [Parameters](concepts/parameters.md), [Loops and time](concepts/loops-and-time.md), [Images](concepts/images.md), [Viewing and export](concepts/viewing-and-export.md), [Wires](concepts/wires.md), [Keyboard and mouse](concepts/shortcuts.md)
- [Guide for Houdini users](houdini-users.md)
- [Node reference](reference/README.md)
