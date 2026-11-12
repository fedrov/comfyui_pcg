# World tiles

A 4 km x 4 km island for an open world, delivered as 4 x 4 tiles, engine-agnostic: tiled 16-bit height maps with shared edges, six material weight maps per tile, and per-tile instance tables for trees, bushes and rocks, plus a minimap and a preview.

## Load it

Drag `example_workflows/pcg_prod_world_tiles.json` onto the ComfyUI canvas and press **Queue**. Only comfyui_pcg nodes plus ComfyUI's Preview Image are used. The terrain takes about two minutes on numpy (the two HeightField Erode passes are most of it), much less with CUDA; the preview render takes another minute and a half.

## Deliverables

All files go to `output/pcg/world/`.

| Files | Content |
|---|---|
| `height/Height_x{tx}_y{ty}.png` | 1025 x 1025 samples, 4 m per cell, cut into 16 tiles of 257 x 257 as 16-bit PNG. **Adjacent tiles share the row of pixels on their common edge**, so heights at the seams are identical bit for bit. Metres = minimum + value x range; the range is `range_scaled` in `Height.json`, one range for the whole map. |
| `height/Height_full.r16` | The whole height map as raw 16-bit. |
| `weight/<Layer>_x{tx}_y{ty}.png` | Six layers (Grass, ForestFloor, Sediment, Rock, Sand, Water), one 8-bit greyscale PNG per tile and layer. **They sum to 1 at every pixel**, ready for an engine's terrain layers. |
| `instances/Instances_x{tx}_y{ty}.csv` | Trees (three pines and two broadleaf types, chosen by altitude), bushes and rocks, one CSV per 1024 m tile, plus `Instances_index.json` listing the tiles. Rock names match the `SM_Rock_0N` assets of the [rock assets pipeline](pcg_prod_rock_assets.md). |
| `Overview.png` | A lit minimap with the tile borders drawn in yellow. |

**Coordinate convention** (written into every `.json`): the origin is the north-west corner, which is the top-left of the height map; x points east, z points south (same as the image row order), y points up; units are metres. Instance transforms read the same way as in Copy to Points, so what the preview places is exactly what the tables say.

## Step by step

**1. Terrain: an island grown by its rivers**

1. **[COP Noise (PCG)](../reference/cop-generate.md#pcg-copnoise)** (513 x 513, 8 m cells) and a **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** that draws the island outline (distance from the centre, pushed in and out by two scales of noise for bays and headlands), marks the sea (`sea`) and makes an uplift map (`up`): everywhere on the island, more under a few massifs, less toward the coast.
2. **[COP HeightField Stream Power Erosion (PCG)](../reference/cop-terrain.md#pcg-copstreampower)** (300 steps, `base_layer` = `sea`): the whole island rises while rivers cut it down to the sea, until uplift and erosion balance. This is what puts detail everywhere: every slope belongs to a valley, every valley branches and reaches the coast, there are no flat interiors. The relief is about Uplift / Erodibility (here some 250 m); `diffusion` sets how far apart the valleys are (0.04 gives a finely dissected badland, 0.25 a few smooth domes, 0.12 valleys 150-300 m apart).
3. **[COP Blur (PCG)](../reference/cop-filter.md#pcg-copblur)** (0.8 px) softens the one-cell river cuts, **[COP Resize (PCG)](../reference/cop-transform.md#pcg-copresize)** goes to 1025 x 1025 (4 m cells), a Wrangle adds buttresses and hollows (60-150 m) and rock roughness on the land, and **[COP Erosion Filter (PCG)](../reference/cop-terrain.md#pcg-coperosion)** the gully pattern.
4. **[COP HeightField Erode (PCG)](../reference/cop-terrain.md#pcg-copheightfielderode)** (160 steps, `capacity` 4 with `bed_change_limit` 0.03 so the strong carving does not ripple) cuts the gullies and writes the masks the materials are made from: `flow` (where water ran), `sediment` and `debris` (scree).
5. **[COP Flow Accumulation (PCG)](../reference/cop-terrain.md#pcg-copflowaccumulation)** (Rho8, draining to the sea) finds the rivers; a Blur and a Wrangle turn them into beds cut 1.5-5 m into the valley floors, deeper and wider for larger catchments.
6. **[COP Height to Normal (PCG)](../reference/cop-terrain.md#pcg-copheighttonormal)** (strength 2048, world size 4100) gives the slopes and the normal used to tilt rocks.

**2. Ecology and colour**

7. A **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** builds the six weight layers and the scatter densities, each layer taking its share of what the ones above left: water (the sea, and the trunk rivers in their beds), sand (the beach 0-4 m above the sea, and the beds of the smaller streams), rock (above about 45 degrees everywhere, from about 35 degrees in patches: bare outcrops in the grass), scree (the debris below them), woodland (valleys and lower slopes where water collects, in clumps) and grass. The colour comes from the same masks: rock with warm and cool beds, darkened where water streaks down it; grass lush in the valleys, dry on sunny ridges, heath-coloured on the high ground and darker along every gully, so the drainage pattern reads in the colour as well as the shape. A `terrain_orm` layer gives the preview the roughness (water is a mirror) and `sea_orm` the sea's.

**3. Scatter**

5. Three **[COP Layer To Points (PCG)](../reference/cop-geometry.md#pcg-coplayertopoints)** nodes (mode `scatter`) scatter 30,000 trees, 14,000 bushes and 4,000 rocks by their density layers, sampling the height (`height_scale` 2048) and the attributes `hn`, `tn`, `wet` and the density itself.
6. One **[Wrangle (PCG)](../reference/attribute.md#pcg-wrangle)** per type picks the asset name and the orientation: trees stand upright with a random rotation (pines higher up, broadleaf lower, mixed in between), bigger deep in the forest and where it is wet, smaller at the edges and toward the tree line; bushes lean a little with the slope; rocks lean 70% towards the slope normal and are sunk by `0.25 * pscale`.
7. **[Merge (PCG)](../reference/modify.md#pcg-merge)**, **[Transform (PCG)](../reference/modify.md#pcg-transform)** (moves the origin to the north-west corner), and **[Blast (PCG)](../reference/modify.md#pcg-blast)** removes points that fell half a cell outside the terrain (they would create empty extra tiles). **[Export Instances (PCG)](../reference/output.md#pcg-exportinstances)** writes the CSVs in 1024 m tiles.

**4. Files and preview**

8. **[COP Write File (PCG)](../reference/cop-utility.md#pcg-copwritefile)** nodes write the tiled height (16-bit, `shared_edge` on, `value_scale` 2048), the full `.r16`, and the six weight layers.
9. **[COP Light (PCG)](../reference/cop-utility.md#pcg-coplight)** plus a Wrangle that draws the tile borders produce the minimap, written as `Overview.png` and previewed.
10. **[COP HeightField to Mesh (PCG)](../reference/cop-geometry.md#pcg-copheightfieldtomesh)** (every sample, about two million triangles) builds the terrain mesh; below sea level the preview mesh is flattened to the water surface (the height files keep the sea floor), and a single quad continues the sea to the horizon. Proxies stand in for the engine's assets: pines of stacked cones, broadleaf trees with a crown of lumpy clusters, bushes and angular rocks, darker toward the bottom of the crown and tinted per instance (*Multiply Attributes* = `Cd`).
11. Two **[Camera (PCG)](../reference/render.md#pcg-camera)** nodes and **[Geometry Preview (PCG)](../reference/output.md#pcg-previewimage)** in the *Outdoor* look at 1600 x 900: the whole island from the air south-west of it, and a low view from a ridge toward the main peak. Both use `orm = @{material}_orm` with the ecology image on `textures_cop`, so the terrain and the sea take their roughness from it while the proxies keep their colour.

![The island from the air](images/pcg_prod_world_tiles.png)

![From a ridge toward the main peak](images/pcg_prod_world_tiles_valley.png)

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| COP Noise / island Wrangle | `rand_seed`, `code` | A different island: outline, where the massifs are. |
| Stream Power | `uplift`, `erodibility`, `diffusion` | Height of the island (about uplift / erodibility), how far apart the valleys are. |
| Geometry Preview | `sun_elevation`, `sun_azimuth`, `clouds`, `haze` | Time of day and weather of the shot. |
| HeightField Erode | `iterations`, `capacity`, `talus_angle` | How deeply water carves, how much scree. |
| Ecology Wrangle | `code` | Where rock, sand, woodland and grass go; density and colour formulas. |
| COP Layer to Points (x3) | `count`, `rand_seed` | Number of trees, bushes and rocks. |
| Tree / bush / rock Wrangles | `code` | Asset names (match your engine's assets), altitude split, tilt, scale range. |
| Write File / Export Instances | `tiles_x`, `tiles_y`, `tile_size` | Tile layout of the deliverables. |

## See also

- [Terrain maps](pcg_cop_terrain_maps.md): the same terrain chain at a smaller scale.
- [Rock assets pipeline](pcg_prod_rock_assets.md): the rocks these tables reference.
- [Viewing and export](../concepts/viewing-and-export.md): writing images and instance tables.
- [Example index](README.md).
