# Brick wall PBR

A complete tileable brick-wall texture set made only with COP (image) nodes: 2048 x 2048, seamless on all four sides. It outputs albedo, normal, roughness, height and AO maps, plus a lit 2 x 2 preview to check the seams.

## Load it

Drag `example_workflows/pcg_cop_brick_material.json` onto the ComfyUI canvas and press **Queue**. Only comfyui_pcg nodes plus ComfyUI's Preview Image and Save Image are used. The maps are saved as `pcg/brick_albedo`, `pcg/brick_normal`, `pcg/brick_roughness`, `pcg/brick_height` and `pcg/brick_ao` in ComfyUI's output folder.

## Step by step

**1. Noise**

1. **[COP Noise (PCG)](../reference/cop-generate.md#pcg-copnoise)** (2048 x 2048, Perlin, standard fractal, frequency 8, 6 octaves) writes the layer `detail`: brick-face relief and stains.
2. **[COP Noise Extra (PCG)](../reference/cop-generate.md#pcg-copnoiseextra)** (kind `crystal`, frequency 48) adds the layer `pits`, used for cracks.
3. Both noises repeat in u only; **[COP Retile (PCG)](../reference/cop-transform.md#pcg-copretile)** in `seamless` mode cross-fades `detail` and `pits` so they become seamless in both directions.

**2. Bricks and height**

4. **[COP Pattern (PCG)](../reference/cop-generate.md#pcg-coppattern)** (Tile Pattern, 4 x 10 bricks, offset 0.5, gap 0.018, bevel 0.12) adds the bricks and its helper layers: `pattern_rand` (a random value per brick), `pattern_edge` (pixel distance to the brick edge) and `pattern_height` (the bevel).
5. A **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** combines them into `height`. The edge distance is perturbed by the noise and thresholded, so brick edges and corners look chipped (`@brick`). The crystal noise boundaries (`pits` near 0) become cracks, and the mortar sits low.

**3. Derived maps**

6. **[COP Height to Normal (PCG)](../reference/cop-terrain.md#pcg-copheighttonormal)** (`N`), **[COP Height to AO (PCG)](../reference/cop-terrain.md#pcg-copheighttoao)** (`ao`) and **[COP Curvature (PCG)](../reference/cop-terrain.md#pcg-copcurvature)** (`curvature`) are computed from `height`, all with *Tile* on: the borders are sampled periodically, so there is no seam.
7. A second **[COP Wrangle (PCG)](../reference/cop-utility.md#pcg-copwrangle)** picks a brick colour from `pattern_rand` (about one brick in ten is a dark, over-fired one), brightens convex edges using `curvature`, multiplies by AO into `albedo`, and writes `roughness` (mortar rougher than brick).

**4. Check and save**

8. **[COP Light (PCG)](../reference/cop-utility.md#pcg-coplight)** lights the albedo with the normal map and the height (with shadows) into `lit`; **[COP Tile (PCG)](../reference/cop-transform.md#pcg-coptile)** repeats it 2 x 2 to check for seams, shown by Preview Image.
9. Each map on the right goes through its own **[COP Export (PCG)](../reference/cop-utility.md#pcg-copexport)** into a Save Image. The normal is exported with mode `signed` (-1..1 to 0..1).

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| COP Pattern | `counts`, `offset`, `gap`, `bevel`, `rand_seed` | Brick layout, mortar width and bevel. |
| Height Wrangle | `code` | How chipped the edges are (the `smoothstep(1.5, 6.0, ...)` and the `* 18`), crack depth, mortar depth. |
| Albedo Wrangle | `code` | Brick and mortar colours, the share of dark bricks (`r > 0.88`). |
| Height to Normal / AO / Curvature | `strength` | Bump strength of the derived maps. |
| COP Noise | `frequency`, `rand_seed` | Scale and layout of stains and relief. |

## See also

- [Tutorial 5: COP texture](tutorial_05_cop_texture.md): the same steps in a small graph.
- [Material library](pcg_prod_material_library.md): eight materials with engine-ready file output.
- [Images (COP)](../concepts/images.md): layers, channel counts and export modes.
- [Example index](README.md).
