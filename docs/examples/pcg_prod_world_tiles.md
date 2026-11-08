# World tiles

A 2 km x 2 km open-world terrain delivered as 4 x 4 tiles, engine-agnostic: tiled 16-bit height maps with shared edges, six material weight maps per tile, and per-tile instance tables for trees, bushes and rocks, plus a minimap and a preview.

## Load it

Drag `example_workflows/pcg_prod_world_tiles.json` onto the ComfyUI canvas and press **Queue**. Only comfyui_pcg nodes plus ComfyUI's Preview Image are used. Hydraulic erosion takes about a minute on numpy, ten-odd seconds with CUDA.

## Deliverables

All files go to `output/pcg/world/`.

| Files | Content |
|---|---|
| `height/Height_x{tx}_y{ty}.png` | 1025 x 1025 samples, 2 m per cell, cut into 16 tiles of 257 x 257 as 16-bit PNG. **Adjacent tiles share the row of pixels on their common edge**, so heights at the seams are identical bit for bit. Metres = minimum + value x range; the range is `range_scaled` in `Height.json`, one range for the whole map. |
| `height/Height_full.r16` | The whole height map as raw 16-bit. |
| `weight/<Layer>_x{tx}_y{ty}.png` | Six layers (Grass, ForestFloor, Sediment, Rock, Snow, Water), one 8-bit greyscale PNG per tile and layer. **They sum to 1 at every pixel**, ready for an engine's terrain layers. |
| `instances/Instances_x{tx}_y{ty}.csv` | Trees (three pines and two broadleaf types, chosen by altitude), bushes and rocks, one CSV per 512 m tile, plus `Instances_index.json` listing the tiles. Rock names match the `SM_Rock_0N` assets of the [rock assets pipeline](pcg_prod_rock_assets.md). |
| `Overview.png` | A lit minimap with the tile borders drawn in yellow. |

**Coordinate convention** (written into every `.json`): the origin is the north-west corner, which is the top-left of the height map; x points east, z points south (same as the image row order), y points up; units are metres. Instance transforms read the same way as in Copy to Points, so what the preview places is exactly what the tables say.

## Step by step

**1. Terrain**

1. **[COP Noise (PCG)](../reference/cop-generate.md#pcg-copnoise)** (1025 x 1025, simplex, `hybrid_terrain`, 8 octaves) plus a **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** that adds a large mountain band. Inside the band the relief is a ridged multifractal on domain-warped coordinates (crest lines where a noise crosses its middle value, each octave weighted by the one before), so the mountains have sharp crests and branching spurs instead of round cones.
2. **[COP HeightField Stream Power Erosion (PCG)](../reference/cop-terrain.md#pcg-copstreampower)** cuts valleys, **[COP HeightField Thermal Erosion (PCG)](../reference/cop-terrain.md#pcg-copthermalerosion)** makes talus, **[COP HeightField Hydraulic Erosion (PCG)](../reference/cop-terrain.md#pcg-cophydraulicerosion)** adds gullies and alluvium, **[COP Flow Accumulation (PCG)](../reference/cop-terrain.md#pcg-copflowaccumulation)** finds rivers and lakes, **[COP HeightField Splat Map (PCG)](../reference/cop-terrain.md#pcg-copsplatmap)** splits five materials.
3. **[COP Height to Normal (PCG)](../reference/cop-terrain.md#pcg-copheighttonormal)** (strength 2048, world size 2050) gives the terrain normal used to tilt rocks.

**2. Ecology**

4. A **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** derives the forest: grassland below the tree line (normalized height 0.62), in noise patches. It splits the splat layers into the six weight layers, computes the three scatter densities (`d_tree`, `d_bush`, `d_rock`), converts the terrain normal to world axes (`tn`) and paints a preview colour (lush and dry grass in patches, darker rock lower down). The colour is written linear, like any albedo; the mesh preview converts it back to a display colour for `Cd`.

**3. Scatter**

5. Three **[COP Layer To Points (PCG)](../reference/cop-geometry.md#pcg-coplayertopoints)** nodes (mode `scatter`) scatter 15,000 trees, 8,000 bushes and 2,500 rocks by their density layers, sampling the height (`height_scale` 2048) and the attributes `hn` and `tn`.
6. One **[Wrangle (PCG)](../reference/attribute.md#pcg-wrangle)** per type picks the asset name and the orientation: trees stand upright with a random rotation (pines higher up, broadleaf lower, mixed in between); bushes lean a little with the slope; rocks lean 70% towards the slope normal and are sunk by `0.25 * pscale`.
7. **[Merge (PCG)](../reference/modify.md#pcg-merge)**, **[Transform (PCG)](../reference/modify.md#pcg-transform)** (moves the origin to the north-west corner), and **[Blast (PCG)](../reference/modify.md#pcg-blast)** removes points that fell half a cell outside the terrain (they would create empty extra tiles). **[Export Instances (PCG)](../reference/output.md#pcg-exportinstances)** writes the CSVs in 512 m tiles.

**4. Files and preview**

8. **[COP Write File (PCG)](../reference/cop-utility.md#pcg-copwritefile)** nodes write the tiled height (16-bit, `shared_edge` on, `value_scale` 2048), the full `.r16`, and the six weight layers.
9. **[COP Light (PCG)](../reference/cop-utility.md#pcg-coplight)** plus a Wrangle that draws the tile borders produce the minimap, written as `Overview.png` and previewed.
10. **[COP HeightField to Mesh (PCG)](../reference/cop-geometry.md#pcg-copheightfieldtomesh)** (every 2nd sample, about half a million triangles) builds the terrain mesh; cones (**[Tube (PCG)](../reference/generate.md#pcg-tube)**) and spheres (**[Sphere (PCG)](../reference/generate.md#pcg-sphere)**) are copied with **[Copy to Points (PCG)](../reference/scatter.md#pcg-copytopoints)** onto the tree and rock points as proxies; **[Geometry Preview (PCG)](../reference/output.md#pcg-previewimage)** renders the whole world in the *Studio* look at 1600 x 1066.

![The whole world with tree, bush and rock proxies](images/pcg_prod_world_tiles.png)

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| COP Noise / mountain Wrangle | `rand_seed`, `code` | A different world. |
| Ecology Wrangle | `code` | Tree line (0.62), forest patch size, density formulas. |
| COP Layer to Points (x3) | `count`, `rand_seed` | Number of trees, bushes and rocks. |
| Tree / bush / rock Wrangles | `code` | Asset names (match your engine's assets), altitude split, tilt, scale range. |
| Write File / Export Instances | `tiles_x`, `tiles_y`, `tile_size` | Tile layout of the deliverables. |

## See also

- [Terrain maps](pcg_cop_terrain_maps.md): the same terrain chain at a smaller scale.
- [Rock assets pipeline](pcg_prod_rock_assets.md): the rocks these tables reference.
- [Viewing and export](../concepts/viewing-and-export.md): writing images and instance tables.
- [Example index](README.md).
