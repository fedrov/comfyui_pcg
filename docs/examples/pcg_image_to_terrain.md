# Image to terrain

Lifts a single landscape image (a photo or an AI-painted perspective view) into a top-down height field, then continues with the terrain chain: a little stream-power erosion, a coloured mesh, a preview and a glb export.

## Load it

Drag `example_workflows/pcg_image_to_terrain.json` onto the ComfyUI canvas and choose your image in **Load Image**.

The workflow opens on ComfyUI's `example.png`, which is a cartoon figure, not a landscape: lifted, its flat sky becomes a wall at the back and the figure a spike. Pick a picture of ground running into the distance — a camera looking slightly down at a valley, hills or a coast, with a horizon — a photo or an AI-painted one.

**Requirements**

| What | Default in the workflow | Notes |
|---|---|---|
| Depth Anything V2 | `DepthAnythingV2Preprocessor`, `depth_anything_v2_vitl.pth` | From the custom node pack **comfyui_controlnet_aux**; it downloads the weights automatically on the first run. This is the default depth route. |
| MoGe (optional) | `LoadMoGeModel` with `moge_2_vitl_normal.safetensors`, `MoGeInference` | ComfyUI core nodes. Put the model in `models/geometry_estimation/`. Both nodes are muted in the saved workflow. |

## Two depth routes

**Depth Anything V2 (default).** Its output is *relative inverse depth*: it is known only up to a scale and a shift. The *Shift* and *FOV X* values of HeightField from Depth are therefore guesses, and a wrong guess bends the terrain rather than just scaling it.

**MoGe (more accurate).** MoGe provides camera-space points, metric scale and a sky mask directly. To use it, put the model in `models/geometry_estimation/`, select the two greyed-out MoGe nodes and press **Ctrl+M** to unmute them. The wires are already connected: while the MoGe nodes are muted, the front end drops every input that comes from a muted node, so HeightField from Depth uses `depth`; once they are unmuted, `moge_geometry` takes priority.

## Step by step

1. **Load Image** provides the picture; **DepthAnythingV2Preprocessor** (resolution 1024) estimates depth, shown by a Preview Image ("near = white").
2. **[COP HeightField from Depth (PCG)](../reference/cop-terrain.md#pcg-copheightfieldfromdepth)** (mode `perspective`, resolution 640, depth kind `disparity`, FOV X 60) projects the depth into a top-down height field. It also takes the original image (for colour) and, when unmuted, the MoGe geometry. Its `mask` layer marks which cells were actually measured; the hidden areas behind mountains are filled by push-pull and are guesses. The `world_size` output gives the size of the area.
3. **[COP HeightField Stream Power Erosion (PCG)](../reference/cop-terrain.md#pcg-copstreampower)** (30 iterations, erodibility 0.02, diffusion 0.01) erodes it lightly. Its `world_size` input is wired from step 2, so the scale matches automatically.
4. **[COP HeightField to Mesh (PCG)](../reference/cop-geometry.md#pcg-copheightfieldtomesh)** (step 2, attributes `Cd=albedo mask`, `world_size` wired as well) builds the mesh with the image colours.
5. **[Geometry Preview (PCG)](../reference/output.md#pcg-previewimage)** (*Studio* look) renders the lifted terrain and **[Export Mesh (PCG)](../reference/output.md#pcg-exportmesh)** writes `pcg/terrain_from_image`.

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| HeightField from Depth | `fov_x`, `shift` | The two guesses of the Depth Anything route. Adjust them when the terrain looks bent. |
| HeightField from Depth | `resolution` | Height-field size in pixels. |
| HeightField from Depth | `dequantize` | On by default. Depth Anything through comfyui_controlnet_aux arrives as an 8-bit image (256 levels); each level would lift to one arc on the ground, giving horizontal streaks and terraces in the far field. Dequantize smooths the map back to continuous values within its levels; it does nothing to float depth or MoGe. |
| Stream Power | `iterations`, `erodibility` | How much erosion is added on top of the measured shape. |
| DepthAnythingV2Preprocessor | `ckpt_name`, `resolution` | Smaller models (vitb, vits) run faster. |

## See also

- [Terrain to AI texture](pcg_terrain_to_ai_texture.md): the opposite direction.
- [Images (COP)](../concepts/images.md): height fields and the bridge between images and geometry.
- [Example index](README.md).
