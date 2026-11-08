# Terrain to AI texture

A complete procedural terrain -> diffusion model -> back onto the mesh chain. A noise height field is eroded and classified into five material layers; those layers become regional prompts and the height becomes a ControlNet depth image; SDXL paints a top-down texture that lines up pixel for pixel with the height field; the texture is put back into the terrain and turned into a coloured mesh.

## Load it

Drag `example_workflows/pcg_terrain_to_ai_texture.json` onto the ComfyUI canvas.

**Requirements**

| What | Default in the workflow | Notes |
|---|---|---|
| SDXL checkpoint | `SDXL\RealVisXL_V4.0.safetensors` | Pick your own SDXL checkpoint in `CheckpointLoaderSimple`. |
| SDXL ControlNet | `SDXL\controlnet-union-sdxl-1_promax.safetensors` | A union or a depth ControlNet for SDXL both work. **SetUnionControlNetType** is set to `depth`. |
| Custom nodes | none besides comfyui_pcg | The AI part uses ComfyUI core nodes only: `CheckpointLoaderSimple`, `CLIPTextEncode`, `ControlNetLoader`, `SetUnionControlNetType`, `ControlNetApplyAdvanced`, `EmptyLatentImage`, `KSampler`, `VAEDecode`, `SaveImage`, `PreviewImage`. |

The erosion runs at 512 x 512; the terrain is then upsampled to 1024 x 1024 (with a fine relief on top), the size the image is generated at, so masks, control image and texture line up pixel for pixel.

## Step by step

**1. Terrain (left two columns)**

1. **[COP Noise (PCG)](../reference/cop-generate.md#pcg-copnoise)**: 512 x 512 simplex noise, standard fractal, frequency 3, 6 octaves, amplitude 0.06, seed 7.
2. **[COP HeightField Stream Power Erosion (PCG)](../reference/cop-terrain.md#pcg-copstreampower)**: stream-power erosion (60 iterations, `rho8` routing) cuts river valleys.
3. **[COP Erosion Filter (PCG)](../reference/cop-terrain.md#pcg-coperosion)**: the erosion filter (amplitude 0.003, wavelength 40).
4. **[COP HeightField Thermal Erosion (PCG)](../reference/cop-terrain.md#pcg-copthermalerosion)**: thermal erosion (talus angle 38, 12 iterations).
5. **[COP HeightField Hydraulic Erosion (PCG)](../reference/cop-terrain.md#pcg-cophydraulicerosion)**: hydraulic erosion: gullies plus alluvium, accumulated into the `debris` layer.
6. **[COP Flow Accumulation (PCG)](../reference/cop-terrain.md#pcg-copflowaccumulation)**: flow accumulation (`d8`) for rivers and lakes.
7. **[COP HeightField Splat Map (PCG)](../reference/cop-terrain.md#pcg-copsplatmap)**: splits the terrain into grass / sediment / rock / snow / water; the five layers sum to 1 everywhere (rock angle 42, snow line 0.78).

**2. Prompts and control image**

8. **[Regional Prompt from COP (PCG)](../reference/cop-layers.md#pcg-regionalprompt)** turns the splat layers into regional conditioning: a base prompt plus one line per layer (`layer: prompt`); later lines take priority. Its `preview` output shows the regions.
9. **[Control Image (PCG)](../reference/cop-layers.md#pcg-controlimage)** in `height` mode outputs a top-down depth map (high = white) for the ControlNet.

**3. Generation**

10. SDXL with the union ControlNet in depth mode (strength 0.85, ending at 85% of the steps), a negative prompt against perspective, sky, text and similar, and KSampler (seed 7, 28 steps, CFG 5, `dpmpp_2m` / `karras`) produce a top-down texture aligned with the height field. Save Image writes it as `pcg/terrain_albedo`.

**4. Back to the mesh**

11. **[COP Import (PCG)](../reference/cop-utility.md#pcg-copimport)** reads the generated image back into a COPIMAGE (layer `albedo`).
12. **[COP Composite (PCG)](../reference/cop-composite.md#pcg-copcomposite)** (mode `replace`) puts it into the terrain image's `albedo` layer.
13. **[COP HeightField to Mesh (PCG)](../reference/cop-geometry.md#pcg-copheightfieldtomesh)** (step 2, attributes `Cd=albedo`) builds the mesh with the texture as point colour.
14. **[Geometry Preview (PCG)](../reference/output.md#pcg-previewimage)** in the *Studio* look shows the textured terrain, and **[Export Mesh (PCG)](../reference/output.md#pcg-exportmesh)** writes `pcg/terrain_ai` (glb) to the output folder.

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| COP Noise | `rand_seed`, `frequency`, `amplitude` | A different terrain. |
| Splat Map | `rock_angle`, `snow_line` | How much rock and snow the prompts get. |
| Regional Prompt | `base_prompt`, `regions` | The look of each material. |
| `ControlNetApplyAdvanced` | `strength`, `end_percent` | How strictly the image follows the height. |
| KSampler | `seed` | A different texture for the same terrain. |

## See also

- [Image to terrain](pcg_image_to_terrain.md): the opposite direction.
- [Terrain maps](pcg_cop_terrain_maps.md): the same terrain chain without AI.
- [Images (COP)](../concepts/images.md): COPIMAGE, layers, import and export.
- [Example index](README.md).
