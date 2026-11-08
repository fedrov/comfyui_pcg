# Terrain maps

From noise to a full set of terrain maps, entirely in COP: no AI and no mesh. It shapes and erodes a massif at 512 x 512 (the erosion solvers are tuned per pixel), upsamples it to 1024 x 1024 with a fine relief on top, then finds rivers and lakes, splits it into five material layers, shades it, and saves height, normal, splat, albedo, a lit image and a contour map.

## Load it

Drag `example_workflows/pcg_cop_terrain_maps.json` onto the ComfyUI canvas and press **Queue**. Only comfyui_pcg nodes plus ComfyUI's Save Image are used. Images are saved as `pcg/terrain_lit`, `pcg/terrain_topo`, `pcg/terrain_albedo`, `pcg/terrain_height`, `pcg/terrain_normal` and `pcg/terrain_splat`.

## Step by step

**1. Shape**

1. **[COP Noise (PCG)](../reference/cop-generate.md#pcg-copnoise)** (simplex, `hybrid_terrain` fractal, frequency 2.5, 7 octaves, amplitude 0.08) is the base relief; a **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** raises the middle into a massif (`@C` plus a radial falloff).
2. **[COP HeightField Stream Power Erosion (PCG)](../reference/cop-terrain.md#pcg-copstreampower)** cuts branching river valleys; **[COP Strata (PCG)](../reference/cop-terrain.md#pcg-copstrata)** adds rock-layer terraces; **[COP HeightField Thermal Erosion (PCG)](../reference/cop-terrain.md#pcg-copthermalerosion)** collapses steep slopes into talus (the `debris` layer).
3. **[COP HeightField Hydraulic Erosion (PCG)](../reference/cop-terrain.md#pcg-cophydraulicerosion)** carves gullies and adds the alluvium to `debris`. This is the slowest step: about ten-odd seconds on numpy, and it uses the GPU automatically when CUDA is available.

**2. Water**

4. **[COP Flow Accumulation (PCG)](../reference/cop-terrain.md#pcg-copflowaccumulation)** computes the catchment area and derives the river network (`river`) and filled depressions (`lake`).

**3. Materials**

5. **[COP HeightField Splat Map (PCG)](../reference/cop-terrain.md#pcg-copsplatmap)** splits the terrain into grass / sediment / rock / snow / water; the five layers sum to 1 everywhere. It also writes `splat_rgba`, a packed weight map for an engine's terrain layers.

**4. Shading**

6. **[COP Height to Normal (PCG)](../reference/cop-terrain.md#pcg-copheighttonormal)** and **[COP Height to AO (PCG)](../reference/cop-terrain.md#pcg-copheighttoao)** add `N` and `ao`.
7. A **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** mixes a colour per material layer into `albedo`: rock is banded by height (like sedimentary layers), wet grass is darker, and AO darkens the result.
8. **[COP Light (PCG)](../reference/cop-utility.md#pcg-coplight)** shades it with shadows into `lit`; **[COP Visualize (PCG)](../reference/cop-utility.md#pcg-copvisualize)** (`height_ramp`, `terrain` ramp, contour interval 0.005, hillshade) draws a contour map into `vis`.
9. The right-hand columns are **[COP Export (PCG)](../reference/cop-utility.md#pcg-copexport)** + Save Image pairs: the lit image, the contour map, albedo, height (`normalize`), normal (`signed`) and the splat map.

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| COP Noise | `rand_seed`, `frequency`, `octaves` | A different landscape. |
| Massif Wrangle | `code` | Size and height of the central rise. |
| Stream Power | `iterations`, `erodibility` | Depth of the valleys. |
| Strata | `spacing`, `strength` | Terrace spacing and how pronounced the steps are. |
| Splat Map | `rock_angle`, `snow_line` | Where rock and snow appear. |
| Colour Wrangle | `code` | The palette of each material. |

## See also

- [Terrain to AI texture](pcg_terrain_to_ai_texture.md): the same kind of terrain feeding a diffusion model.
- [World tiles](pcg_prod_world_tiles.md): a 2 km terrain delivered as engine tiles.
- [Images (COP)](../concepts/images.md).
- [Example index](README.md).
