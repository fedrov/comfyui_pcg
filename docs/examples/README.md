# Example workflows

Ready-made ComfyUI workflows that ship with comfyui_pcg, in `comfyui_pcg/example_workflows/`. To open one, drag its `.json` file onto the ComfyUI canvas (or use the workflow menu's Open), then press **Queue**. Each page below explains what the workflow builds, walks through the node chain with links to the [node reference](../reference/README.md), and lists the parameters worth changing.

Start with the tutorials: they are small (10 to 14 nodes), need no model files, and each one has an English note on the canvas. The showcase and production workflows are larger; their on-canvas notes and node titles are in Chinese, and the pages here are their English walkthroughs.

## Tutorials

| Workflow | What it shows |
|---|---|
| [Tutorial 1: first geometry](tutorial_01_first_geometry.md) | Box, transform, group by normal, extrude twice, bevel, colour, preview image and 3D viewport. |
| [Tutorial 2: scatter and copy](tutorial_02_scatter_copy.md) | Noise terrain, scatter, random `pscale` / `orient`, Copy to Points. |
| [Tutorial 3: attributes and wrangle](tutorial_03_attributes_wrangle.md) | Attribute Create / Noise, a Wrangle expression, promote, group by `@height`, colour by attribute. |
| [Tutorial 4: for-each variations](tutorial_04_foreach_variations.md) | A For-Each count loop whose iteration drives the seeds: six different stones. |
| [Tutorial 5: COP texture](tutorial_05_cop_texture.md) | Noise and tile pattern, levels, composite, colour remap, normal from height, light, save. |
| [Tutorial 6: controller panel](tutorial_06_controller.md) | A Parameters (PCG) panel driving several nodes through bindings. |

## Showcase: geometry and images

| Workflow | What it shows |
|---|---|
| [Rock garden](pcg_sop_rock_garden.md) | A rock library from a For-Each loop, a terrain with a stream, weighted scattering and per-variant copying. |
| [City block](pcg_sop_city_block.md) | 25 buildings from face operations and groups only: setbacks, window grids, shopfronts, trees. |
| [Brick wall PBR](pcg_cop_brick_material.md) | A seamless brick texture set (albedo, normal, roughness, height, AO) with COP nodes. |
| [Terrain maps](pcg_cop_terrain_maps.md) | Noise to eroded terrain to splat, albedo, lit and contour maps, all in COP. |

## Production pipelines

| Workflow | What it shows |
|---|---|
| [Rock assets pipeline](pcg_prod_rock_assets.md) | Four game-ready rocks: high poly, LOD0-2 with shared UVs, UCX collision, baked textures, one glb each. |
| [World tiles](pcg_prod_world_tiles.md) | A 2 km terrain as 4 x 4 tiles: shared-edge 16-bit heights, six weight maps, per-tile instance CSVs. |
| [Modular city](pcg_prod_modular_city.md) | A facade kit exported as glb pieces plus rule-based assembly into an instance table. |
| [Material library](pcg_prod_material_library.md) | Fourteen PBR materials (three facades, cobble, asphalt, wood, two roofs, trim, glass, steel, sign, facade bays for distant buildings) with real-size relief, GL/DX normals, ORM and height. |

## With AI models

| Workflow | What it shows |
|---|---|
| [Terrain to AI texture](pcg_terrain_to_ai_texture.md) | Eroded terrain -> regional prompts + depth ControlNet -> SDXL texture -> textured mesh. Needs an SDXL checkpoint and an SDXL ControlNet. |
| [Image to terrain](pcg_image_to_terrain.md) | A landscape picture -> depth (Depth Anything V2, or MoGe) -> height field -> eroded, coloured mesh. Needs comfyui_controlnet_aux (or the MoGe model). |

## See also

- [Getting started](../getting-started.md)
- [Node reference](../reference/README.md)
- Concepts: [geometry](../concepts/geometry.md), [groups](../concepts/groups.md), [expressions](../concepts/expressions.md), [parameters](../concepts/parameters.md), [loops and time](../concepts/loops-and-time.md), [images](../concepts/images.md), [viewing and export](../concepts/viewing-and-export.md)
