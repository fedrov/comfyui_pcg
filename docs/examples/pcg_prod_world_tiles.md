# World tiles

A 4 km x 4 km open-world terrain delivered as 4 x 4 tiles, engine-agnostic: tiled 16-bit height maps with shared edges, six material weight maps per tile, and per-tile instance tables for trees, bushes and rocks, plus a minimap and a preview.

## Load it

Drag `example_workflows/pcg_prod_world_tiles.json` onto the ComfyUI canvas and press **Queue**. Only comfyui_pcg nodes plus ComfyUI's Preview Image are used. The terrain takes about two minutes on numpy (the two HeightField Erode passes are most of it), much less with CUDA; the preview render takes another minute and a half.

## Deliverables

All files go to `output/pcg/world/`.

| Files | Content |
|---|---|
| `height/Height_x{tx}_y{ty}.png` | 1025 x 1025 samples, 4 m per cell, cut into 16 tiles of 257 x 257 as 16-bit PNG. **Adjacent tiles share the row of pixels on their common edge**, so heights at the seams are identical bit for bit. Metres = minimum + value x range; the range is `range_scaled` in `Height.json`, one range for the whole map. |
| `height/Height_full.r16` | The whole height map as raw 16-bit. |
| `weight/<Layer>_x{tx}_y{ty}.png` | Six layers (Grass, ForestFloor, Sediment, Rock, Snow, Water), one 8-bit greyscale PNG per tile and layer. **They sum to 1 at every pixel**, ready for an engine's terrain layers. |
| `instances/Instances_x{tx}_y{ty}.csv` | Trees (three pines and two broadleaf types, chosen by altitude), bushes and rocks, one CSV per 1024 m tile, plus `Instances_index.json` listing the tiles. Rock names match the `SM_Rock_0N` assets of the [rock assets pipeline](pcg_prod_rock_assets.md). |
| `Overview.png` | A lit minimap with the tile borders drawn in yellow. |

**Coordinate convention** (written into every `.json`): the origin is the north-west corner, which is the top-left of the height map; x points east, z points south (same as the image row order), y points up; units are metres. Instance transforms read the same way as in Copy to Points, so what the preview places is exactly what the tables say.

## Step by step

**1. Terrain: erode, upres, erode**

1. **[COP Noise (PCG)](../reference/cop-generate.md#pcg-copnoise)** (257 x 257, 16 m cells) and a **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** that makes a gently rolling lowland tilted so it drains, and a massif mask `m`: a belt running north-west to south-east across the north-east half, with saddles and summits along it and a few foothill knolls, fading out before the map edges. Inside the belt the ground starts as noisy high ground; nothing is drawn as mountains yet.
2. **[COP HeightField Stream Power Erosion (PCG)](../reference/cop-terrain.md#pcg-copstreampower)** uplifts the belt while rivers cut it (300 steps, Rho8 routing, `diffusion` 0.2). This is what gives the range its branching ridges, spurs and valleys. The hillslope diffusion matters as much as the uplift: with little of it every slope is a knife-cut V and the range reads as a row of fins; with it the ridges have rounded shoulders and the median slope is about 23 degrees, like real mid-height mountains (about 400 m of relief over 4 km).
3. A Wrangle brings back the rolling lowland outside the massif (Stream Power fills every pit first, which would flatten it) and makes the profiles slightly concave.
4. **[COP Resize (PCG)](../reference/cop-transform.md#pcg-copresize)** to 513 x 513, 100-200 m lumps on the massif (buttresses and hollows for the water to find), then **[COP HeightField Erode (PCG)](../reference/cop-terrain.md#pcg-copheightfielderode)** (250 steps): rain on every cell, water flowing through virtual pipes, sediment picked up and dropped, over-steep slopes slumping.
5. **COP Resize** to 1025 x 1025, a few metres of noise on the massif, and **[COP Erosion Filter (PCG)](../reference/cop-terrain.md#pcg-coperosion)** for the gully pattern, blended back to the unfiltered height outside the massif.
6. **COP HeightField Erode** again at 1025 x 1025 (150 steps). Besides the height it writes the masks the materials are made from: `flow` (where water ran), `sediment` (where water dropped material) and `debris` (scree from slumping).
7. **[COP Flow Accumulation (PCG)](../reference/cop-terrain.md#pcg-copflowaccumulation)** (Rho8) finds rivers and lakes; **[COP HeightField Splat Map (PCG)](../reference/cop-terrain.md#pcg-copsplatmap)** splits five materials (rock above 37 degrees), with debris plus sediment as the loose-material layer.
8. **[COP Height to Normal (PCG)](../reference/cop-terrain.md#pcg-copheighttonormal)** (strength 2048, world size 4100) gives the terrain normal used to tilt rocks.

**2. Ecology and colour**

9. A **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** builds the six weight layers and the scatter densities from the splat layers and the erosion masks. Forest grows where soil holds (not rock, not scree, not water), below a ragged tree line (about 0.62 of the height range), on slopes under about 35 degrees, thicker where water collects, in clumps at two scales so there are edges and clearings; thin alluvium is grassed. Trees (`d_tree`) also stand alone in meadows, bushes (`d_bush`) line forest edges, wet ground and alpine ledges, rocks (`d_rock`) lie on scree. The preview colour uses the masks too: warm and cool rock in patches with faint warped bedding, darkened where water streaks down it, light scree, olive alluvium, lush grass where wet, dry grass on ridges and a paler alpine meadow above the tree line. It is written linear, like any albedo; the mesh preview converts it back for `Cd`. A `terrain_orm` layer (roughness: water is a mirror, wet rock glistens) is made for the preview.

**3. Scatter**

5. Three **[COP Layer To Points (PCG)](../reference/cop-geometry.md#pcg-coplayertopoints)** nodes (mode `scatter`) scatter 40,000 trees, 14,000 bushes and 4,000 rocks by their density layers, sampling the height (`height_scale` 2048) and the attributes `hn`, `tn`, `wet` and the density itself.
6. One **[Wrangle (PCG)](../reference/attribute.md#pcg-wrangle)** per type picks the asset name and the orientation: trees stand upright with a random rotation (pines higher up, broadleaf lower, mixed in between), bigger deep in the forest and where it is wet, smaller at the edges and toward the tree line; bushes lean a little with the slope; rocks lean 70% towards the slope normal and are sunk by `0.25 * pscale`.
7. **[Merge (PCG)](../reference/modify.md#pcg-merge)**, **[Transform (PCG)](../reference/modify.md#pcg-transform)** (moves the origin to the north-west corner), and **[Blast (PCG)](../reference/modify.md#pcg-blast)** removes points that fell half a cell outside the terrain (they would create empty extra tiles). **[Export Instances (PCG)](../reference/output.md#pcg-exportinstances)** writes the CSVs in 1024 m tiles.

**4. Files and preview**

8. **[COP Write File (PCG)](../reference/cop-utility.md#pcg-copwritefile)** nodes write the tiled height (16-bit, `shared_edge` on, `value_scale` 2048), the full `.r16`, and the six weight layers.
9. **[COP Light (PCG)](../reference/cop-utility.md#pcg-coplight)** plus a Wrangle that draws the tile borders produce the minimap, written as `Overview.png` and previewed.
10. **[COP HeightField to Mesh (PCG)](../reference/cop-geometry.md#pcg-copheightfieldtomesh)** (every sample, about two million triangles) builds the terrain mesh, tagged with the material `terrain`. Proxies stand in for the engine's assets: pines of four stacked cones (**[Tube (PCG)](../reference/generate.md#pcg-tube)**), broadleaf trees with a crown of six lumpy clusters, bushes and angular rocks (**[Sphere (PCG)](../reference/generate.md#pcg-sphere)** plus **[Point Jitter (PCG)](../reference/modify.md#pcg-pointjitter)**), darker toward the bottom of the crown, chosen per point by a `kind` attribute and placed with **[Copy to Points (PCG)](../reference/scatter.md#pcg-copytopoints)** (*Piece Attribute*; *Multiply Attributes* = `Cd`, so every instance multiplies the proxy's colour by its own tint and the forest is not one flat green).
11. A **[Camera (PCG)](../reference/render.md#pcg-camera)** over the south-west lowlands looks toward the range, and **[Geometry Preview (PCG)](../reference/output.md#pcg-previewimage)** renders it in the *Outdoor* look at 1600 x 900: a low sun from the side, the sky as an area light with shadows, cumulus clouds that shade the ground, haze, and `orm = @{material}_orm` so the terrain takes its roughness from the image (lakes mirror the sky) while the proxies keep their colour.

![The world from the lowlands toward the range, with tree, bush and rock proxies](images/pcg_prod_world_tiles.png)

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| COP Noise / massif Wrangle | `rand_seed`, `code` | A different world; the belt's position and width. |
| Stream Power | `iterations`, `uplift`, `erodibility`, `diffusion` | Height of the range, density of its valleys, how rounded the ridges are. |
| Geometry Preview | `sun_elevation`, `sun_azimuth`, `clouds`, `haze` | Time of day and weather of the shot. |
| HeightField Erode (x2) | `iterations`, `capacity`, `talus_angle` | How deeply water carves, how much scree. |
| Ecology Wrangle | `code` | Tree line (about 0.62 of the height range), forest clumps, density and colour formulas. |
| COP Layer to Points (x3) | `count`, `rand_seed` | Number of trees, bushes and rocks. |
| Tree / bush / rock Wrangles | `code` | Asset names (match your engine's assets), altitude split, tilt, scale range. |
| Write File / Export Instances | `tiles_x`, `tiles_y`, `tile_size` | Tile layout of the deliverables. |

## See also

- [Terrain maps](pcg_cop_terrain_maps.md): the same terrain chain at a smaller scale.
- [Rock assets pipeline](pcg_prod_rock_assets.md): the rocks these tables reference.
- [Viewing and export](../concepts/viewing-and-export.md): writing images and instance tables.
- [Example index](README.md).
