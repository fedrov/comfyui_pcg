# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **World tiles, round three**: rocks in the rock assets' four kinds (one picked per rock), with hard edges and each
  its own stone; forests tinted by stands a few hundred metres across and a little darker higher up; the sea and the
  rivers and lakes shaded as water; cut-out edges dithered (alpha to coverage).
- **Tests**: every push and pull request runs the quick suites; the production workflows run on pushes to `main`,
  nightly and by hand, their output kept as an artifact. `tests/run_tests.py --logs <folder>` keeps each suite's
  output; `tools/run_tests.bat` runs the suites with the Windows portable ComfyUI's Python.
- **World tiles, grass and foliage**: the grass tufts are six curved blades in grass greens (fresh to dry, a third
  of the ground's colour), yellow-green at the tips and translucent; they no longer show as dark strokes on slopes
  seen from below; from 35 m out they fade into the ground's colour and get shorter, so they meet the terrain texture
  without a seam. Leaf cards, the impostor cards and the coarse trees' cards are translucent; the coarse trees have
  more, smaller cards. Bushes, hedges and orchard trees are built by Tree Generator (dense leaf cards) instead of lumpy
  spheres and boxes; ferns are nine arching fronds; rocks come from the rock assets' SDF, coloured by curvature.
- **Geometry Preview (Outdoor), memory**: the sun and sky depth maps rasterize their triangles in batches; the
  alpha test (with every vertex's uv sets) is let go right after the rasterizing, the per-geometry depth once the
  two are merged, the frame's view rays once the surfaces are found (the shading makes its chunk's again), and the
  shadow casters are joined into one soup only after the texturing. The same image, bit for bit; about 480 MB less
  at the peak of the world-tiles road view (1600 x 900, supersampled), on top of the tangent frames below.
- **Geometry Preview (Outdoor and Studio), memory**: a normal-mapped material's tangent frames are built from the
  triangles around the visible ones only (the same frames at every visible pixel): a few hundred MB less at the
  peak of the world-tiles road view, whose terrain is mostly off screen.
- **World tiles, the Snow view**: the snow line is 60 m (was 140 m), so the snow covers the valley sides
  and not only the summits.
- **COP Wrangle**: its code box is highlighted like the other Wrangles'.
- **Big example workflows open collapsed** (world tiles, its quick variant, the modular city: more than 300 nodes):
  only previews, viewports and notes stay open, so the canvas does not carry hundreds of code boxes while panning.
- **Tutorial 4 (for-each variations)**: the stones start from an icosphere (a jittered UV sphere pinched into
  spikes at its poles), jitter less than the point spacing (no folded slits), sit on the ground (Match Size: they
  floated at whatever height their shape reached) and get mottled grey-to-buff colours.
- **Rock assets**: four kinds of rock in turn (`seed % 4`) -- a chunky boulder, a bedded slab with stepped ledges, a
  tall split shard, a weathered block with rounded arrises -- each with its own stone colour (grey-brown, buff
  sandstone, dark speckled, weathered grey); strata faint and broken, cracks that widen and break into runs, fewer
  pits, darker and less uniform overall.
- **Rock garden**: the rocks come from the rock assets' signed distance field (8 broken stones, two of each kind);
  the ground is a height field washed by HeightField Erode and the erosion filter, coloured by its masks (scree, silt,
  rills, bare steep ground), which also place the boulders (on the scree) and the pebbles (on the banks and the silt).
- **Faster previews**: the studio look reuses its soft shadow when only the textures change (the material library's
  fourteen previews of one swatch: 282 to 233 s), shadow and sky depth maps of small scenes are remembered, and the
  numpy rasterizer draws front to back, skipping triangles wholly behind what is already drawn (exact; 15-20% off a
  big frame's raster time).
- **World tiles: terrain v2** -- the Gaea / Houdini erosion workflow: a large-scale HeightField Erode pass at 8 m after
  the river network (branching valleys, sediment on their floors), the 4 m passes as before, and a fine pass at 2 m
  on the finished terrain (rills, small gullies, fans; roads, lots, beds, lakes and the sea kept). The exported
  height is 2 m now (2049², 513² tiles); the meshes and instances get the fine pass's change; the 1 m surface is
  coloured by its masks -- rock bared where it wore slopes down, scree on its debris, gravel and silt on its
  deposits, damper grass along its flow -- and the splat weights follow the same masks; the normal map carries
  the relief the 2 m pass adds between the 4 m mesh vertices. The road camera moved with its road.
- **Faster renders and COP Wrangles, on every machine**: the Studio / Outdoor looks read their textures once per output
  pixel where one surface covers it (as MSAA shades once per pixel) instead of once per supersample; texture
  lookups and banded COP Wrangles (`rows_per_pass`) run on several threads (`PCG_THREADS`, up to 4 by default);
  `noise()` reads Perlin's gradients from a table (the same numbers, faster). The world tiles run went from 23 to
  18 minutes on two CPU cores, its 4096² surface Wrangle from 170 to 62 seconds.

### Added
- **Network boxes**: right-click a group, *PCG: Collapse Box* -- its nodes collapse and stack at its top left, the box
  shrinks round them (wires stay connected); *PCG: Expand Box* puts every node back as it was. Kept in the group, so it
  survives saving and loading.
- **Colour palette**: C with nodes or boxes selected (or a node's menu) opens Houdini's palette of node colours, the
  default and the node shapes.
- **Which parameters use this one**: hovering a parameter in the panel outlines the nodes that read it (orange) and
  the ones it reads (cyan) on the canvas, with their fields; the label's tooltip lists them.
- **Keyframes on the playbar**: a diamond over the slider per keyframe of the selected nodes (all nodes when none is
  selected), click to go there; Ctrl+← / Ctrl+→ and ◆◀ / ▶◆ go to the previous / next keyframe.
- **Textures: `water`** (Outdoor look): material names (wildcards) shaded as a water surface -- the sky and its
  clouds mirrored by Fresnel's law over two scales of ripples that fade out where they would be under a pixel, and the
  sun's glint where it is not shadowed. Materials not named render as before.
- **Textures: `alpha_coverage`**: a width (0..1, default 0 = the hard cut as before) that dithers the alpha cutoff in a
  fixed 4 x 4 screen pattern (alpha to coverage): with supersampling, cut-out edges come out soft and steady from frame
  to frame.
- **Node info: notes.** `cookstats.note()` adds plain lines to a node's middle-button info; Geometry Preview's Outdoor
  look reports the frame size, CPU or GPU, and the seconds of each stage (rasterize, surfaces and textures, sun and
  cloud shadows, sky light, shading, tone).
- **Geometry Preview (Outdoor): Translucency Attribute** (`translucency_attrib`, appended, default `translucency`): a
  float 0..1 for thin surfaces such as grass blades and leaf cards. They are lit from either side, keep their authored
  normal when seen from behind (grass with the ground's up normal no longer turns dark when seen from below, up a
  slope), let that share of the sunlight through, tinted by their colour, when the sun is behind them, and get a
  faint sheen toward the sun. Geometry without the attribute renders as before.
- **Camera: Eye Above Ground** (appended; 0 = off, as before) with an optional `ground` input: in the Look At mode
  the eye is placed that high over the ground under it; the info output reports the ground height.
- **Digital assets on subgraphs** (Houdini's HDA): **PCG: Edit Asset Interface…** on a subgraph node is Type
  Properties -- promote parameters of the nodes inside, order them, label, folder, section, range, default, hide /
  disable rules, help; the instance's parameters are in the docked pane with the look of what they drive (a full
  vector promoted is one row again). The interface lives on the definition and is copied onto its instances, so it
  travels with Publish Subgraph and copy / paste. **Update from the library**: when the library has another version
  of an asset (by name), ⟳ in the pane (or the node menu) brings every instance in the workflow to it, values kept.
- **Paths across networks**: `ch("../tx")` is the parameter of the asset a node is inside, `ch("../../ctl/amp")` a
  node next to the asset, `ch("../rock/box1/sx")` a node inside an asset from outside -- in expressions, references
  and geometry queries, stored by id; materializing reaches every network. The display flag, the Tab menu, Y-cut,
  shake, the ▾ name pickers and the COP thumbnails work inside subgraphs; the pane shows a node's path (`/rock/box1`).
- **Network feedback**: every node that ran shows its cook time right of its title bar, a red / yellow badge when it
  failed / warned, an amber dot when it is out of date (its parameters, wires or bypass, or something upstream,
  changed since it cooked). The **middle button** on a node shows its info: time, counts, memory, bounding box,
  attributes by class with type and size, groups, COP layers, warnings, the error. The **Performance** pane (tab on
  the right edge) lists the last run slowest first. The server reports through `cookstats.py` ("pcg.cook" messages;
  a node from the cache shows what it reported last, also after a page reload).
- **Multiparm blocks** in declarations (`multi pts = 2 … end`, `#` = instance number), with + / − / ✕ in the panel;
  the same expansion in Python and in the frontend (tested on the same cases).
- **Presets**: ☰ in the pane or **PCG: Presets…** in a node's menu -- save, load, delete, Revert to Defaults; per node
  type (per asset name), in the user's ComfyUI data.
- **Quick edit**: Ctrl+click a node to open its panel next to it without selecting it.
- **Docked parameter pane** (the new default of Settings -> PCG -> *Parameters of PCG nodes*: Docked pane / On node /
  Native), as in Houdini: nodes on the canvas are their title and connectors, and one persistent pane shows the
  selected node's panel (movable, resizable, a pin to keep it on one node, hidden and brought back from a tab on the
  window's edge). No parameter elements on the canvas: the world tiles graph opens in about 2 s with all 833 nodes
  open (13 s with a panel on every node) and pans at the same frame time as an empty canvas would allow. The
  Wrangles' code is a tall highlighted editor in the pane. A connected parameter is an input row of the node with
  the parameter's name; while a wire is dragged to a node, its free parameters of the wire's type are listed under it
  to drop on. Values are stored as before: a workflow opens the same in all three modes. "On node" is the earlier
  layout; a saved "Houdini panel" setting reads as On node.
- **COP Wrangle on the GPU**: `compute` (appended; default cpu = numpy as before; auto / cuda = on a CUDA GPU). The same
  code runs on float32 tensors in bands of about half a million pixels: maths, set / components, clamp / fit / lerp /
  smoothstep, vectors, where, noise / pnoise, worley / pworley and their _dir, rand (the same 64-bit mixing as numpy).
  Code it does not cover (sprintf, astype, numpy calls on a layer, `if` on a per-pixel value) runs on numpy. All 66
  COP Wrangles of the example workflows match numpy in float64 on torch's CPU (65 run on torch); the example workflows
  set it to auto.
- **Resize**: `align` -- centres (as before) or corners, for grids of samples such as heightfields (1025 at 4 m to
  2049 at 2 m keeps every old sample on an even new one, and back).
- **Preview Image / Outdoor on the GPU**: with Compute auto (CUDA available) or cuda, the frame is also rasterized and
  textured with torch -- the texture lookups were most of a terrain render's time on numpy -- besides the shadow maps
  and the sky light; same result as numpy to float32 rounding.
- **Leaf Card Texture** (new node): the colour and cutout of a foliage card -- a broadleaf twig or a conifer needle
  spray -- rooted where Tree Generator's cards stand on their branch, as `<Prefix>_C` / `<Prefix>_alpha` layers.
- **Tree Generator**: `leaf_material` (each kind its own leaf texture); conifer sprays smaller on the short top
  branches.
- **Impostor Textures**: `textures` and a `textures_cop` input -- the frames rendered with base colour, cutout and
  tint, so leaf cards bake as leaves.
- **Textures**: `alpha_shadow = <materials>` -- cut-out faces of those materials cast shadows (whole), for leaf
  cards.
- **World tiles, quick version** (`pcg_prod_world_tiles_quick`): the same world for a first look -- 2 m surface
  textures, 800 x 450 previews without supersampling, the variants muted.
- **Tree Generator** (new node): a procedural tree as a game asset -- broadleaf (a branching crown) or conifer
  (whorls along a trunk to the top) -- bark tubes with uv in metres, leaf cards with normals bent out of the crown,
  part / material / level attributes, seed variants.
- **Preview Image / Outdoor**: weather and light -- `snow_line` / `snow_amount`, `wetness` (puddles), `emit_attrib`
  (emitted light), a `lights` input (unshadowed point lights, `light_range`), `sun_elevation` down to -10 (twilight);
  a `cameras` input renders a camera sequence into a batch of frames; `weather_attrib` scales the weather per surface
  (grass blades kept dry).
- **Preview Image / Outdoor**: the snow and the wetness read the slope at the scale of a mountainside (the mesh
  normal blurred over about 1/80 of the frame, 3:1 over the normal-mapped one), so gullies and normal-map ripples no
  longer stripe the snow.
- **Sweep**: `fixed_up` (Keep Square to Up Vector, with Rotation on) keeps every cross section square to the up
  vector, so a ribbon stays level across as the curve climbs and turns (a road).
- **COP Text**: label points -- a `points` input with `label_attribute` and `world_size` puts one text per point.
- **World tiles: procedural trees, road surfaces, an arch bridge, shore, map, dusk / rain / snow, a flyby**. The
  trees are Tree Generator assets (LOD1 a coarse variant, then impostor cards; full trees within 60 m in the
  previews); `roads/Roads_Mesh.glb` has the road surfaces by class with shoulders and pavements; the bridge is a stone
  arch; a wet band and surf along the shore; `Map.png` is a game map with town names, legend and scale bar; three
  more shots at dusk (lamps and windows lit), in the rain and under snow (`variants/`); a muted Flyby group renders
  240 frames to an animated WebP.
- **World tiles: no more stripes on the slopes**. Rock, grass, moss and bare soil are classed mostly by the slope
  of the height blurred over ~20 m, not by each first-order gully on the steady-state flanks; the snow likewise (the
  renderer's broad slope).
- **World Manifest** (new node): reads an exported world back from its folder and writes `World.json` (image sets
  with their decode rules, instance tables, meshes with nodes, bounds and LOD chains, polylines, other files, the
  coordinate convention and how Unreal and Unity map it) and `tiles/Tile_x{i}_y{j}.json` per streaming tile (its
  terrain files, instance counts per asset, towns, water nodes, road length, bounds). Its `after` inputs take any
  type, to order the exports before it; Extra JSON adds keys.
- **Engine import examples** (`engine/`): an Unreal Editor Python script (Landscape settings that reproduce the
  heights, textures, meshes with LOD chains and screen sizes, instances as HISM per tile, road splines) and a Unity
  Editor importer (a Terrain per tile with layers and alphamaps, LODGroups, instances, roads) reading World.json;
  their engine-independent parts are tested (the Unity core compiled and run with Mono).
- **Preview Image**: outputs `depth` and `normal`, the outdoor look's guide passes (inverse depth, camera-space
  normals) for ControlNet.
- **World tiles: road classes, water, layered vegetation, World.json, ControlNet concept art**. Main roads, town
  streets and lanes each get their own polylines (`Roads_Main.obj`, `Streets.obj`, `Lanes.obj`), splat layer (Road,
  the new Setts and Track) and lamp (`SM_RoadLamp` 70 m apart near the towns, `SM_StreetLamp` 28 m, `SM_LaneLamp`
  40 m); the rivers and a dammed lake are a water mesh (`water/Water.glb`, flow in the vertex colour, a node per
  tile) that the previews show reflecting the sky; the forest edge is feathered with a shrub belt, ferns and low
  shrubs grow under the trees, trees are fewer and smaller up high; World Manifest writes `World.json`; the road
  view's render, depth and normal are saved for image models, and a muted Concept group (SDXL + union ControlNet)
  turns them into concept art.
- **World tiles: graded lanes, corner lots, cross gables, bridges by span**. The lanes are graded like the roads
  (a smoothed bed cut in over 10 m) and written to `roads/Lanes.obj`; a lot with a street beside it is a corner
  lot whose building faces both streets; L-shaped buildings get pitched roofs; a bridge spans its river bed
  (measured by probes along the road) with piers on the bed (`SM_BridgePier`).
- **Building Generator**: `side_front_attribute` (a corner lot's second street gets the front's ground floor too);
  an L (`notch_attribute`) under a gable or hip roof gets two gable wings, a cross gable.
- **World tiles: side streets, livelier towns, road furniture, orchards and hedgerows, textured previews**. Each
  town gets lanes square to its roads (painted, with plots along them) and a paved square where its roads meet;
  core buildings get shopfronts and some are L-shaped, upper floors balconies, pitched roofs chimneys, every lot a
  yard wall. Bridges where roads cross rivers, street lamps in the towns and guard rails where the ground drops
  beside a mountain road join the instance tables (proxies in `assets/SM_Props.glb`); orchards in rows ring the
  towns (broadleaf only near them) and hedgerows follow the field margins. `buildings/Towns.lods.json` lists the
  LOD chains for an engine; every building's faces carry its own street point (`street`) and front direction. The previews texture the buildings with the material library's recipes made in the
  same run, tint and frame-blend the impostor cards and tilt them to the camera.
- **Preview Image / Outdoor**: `extra_geo` is drawn beside `geo` without merging (rasterized on its own, the nearer
  surface wins; shadows and sky see both), so a per-shot addition costs no copy of the scene; Textures
  `basecolor_tint` (all, or by material wildcard) and `uv_blend` / `uv_blend_weights` (impostor frame blending);
  the alpha test runs only on the prims that have a cutout.
- **Building Generator**: a `balcony` module, `front_pattern_attribute` (a front pattern per footprint),
  `chimney_chance`, `yard_wall_height` / `yard_wall_thickness` (walls along the lot line, open at the front) and
  `notch_attribute` (L-shaped footprints).
- **Export Mesh**: `lod_manifest` writes `<filename>.lods.json` beside the mesh: per asset its LOD nodes, switch
  distances, triangles, bounds, materials, Unreal screen sizes and Unity LODGroup transitions (`lod_fov`,
  `lod_cull_screen_size`).
- **World tiles: towns along the roads, building LODs, textured buildings, a Crops layer, impostor trees in the
  previews**. The towns are plots along their roads (both sides, facing the road, cut into front and back lots by
  Lot Subdivision) instead of square blocks; each building's door and ground floor face the street, the taller ones
  stand toward the town core, roofs are gable (hip from four floors), and the parts get the material library's
  materials (`M_Stucco` / `M_BrickBuff` / `M_Wall` facades, `M_Trim`, `M_Glass`, `M_Door`, `M_Roof`, `M_RoofFlat`).
  `Towns.glb` holds a node per town and level: the buildings, their massing (the same generator without openings,
  as LOD Create's custom level: reducing the facades would tear them) and the massing reduced. The fields are a
  thirteenth terrain layer, Crops (rows), in a fourth splat map. The previews show the far trees as impostor cards
  (alpha cut out, a blob for the shadow) and the towns at the LOD of each lot's distance.
- **Preview Image**: `extra_geo`, geometry merged in before rendering; Textures `alpha` (and `alpha_cutoff`) cut
  faces out by a texture (impostor cards, foliage); `a | b` alternatives (the first found is used); a `@layer` not
  in its own image is looked for in the others (Textures, Splat, Detail); prims with `shadow_only` = 1 cast shadows
  but are not seen.
- **Building Generator**: Gable and Hip roofs (`roof_pitch`, `roof_overhang`, gable-end walls), `roof_attribute`
  (the roof per footprint), `front_attribute` / `front_pattern` (the ground-floor pattern on the wall facing the
  footprint's front: doors to the street).
- **LOD Create**: a `custom` input whose faces (prim `lod`) replace those levels, reduced by their own percent.

### Changed
- **World tiles**: `roads/Roads.obj` is replaced by `roads/Roads_Main.obj` and `roads/Streets.obj` (the same network, by
  class); the splat maps hold fifteen layers (Splat3: Crops, Setts, Track).
- **Building Generator**: a front wall with fewer bays than its Front Pattern shows the pattern's middle (one bay
  of `window door window` is the door), where it used to show the pattern's start (a window).
- **Impostor Textures**: the C layer is linear (Cd is a display colour), like the base colour everywhere else.
- **Merge**: an attribute with different tuple sizes on its inputs takes the largest, the shorter ones padded
  with 0 (it used to fail), as Houdini does.

- **World tiles: towns, fields and the far view**. Each town's ground is cut into lots (Lot Subdivision); the lots
  in the town disc, off the roads, dry and gentle enough are levelled into pads (HeightField Project into the height
  map, so the mesh, weights and 1 m surface see the terraces) and get a building each (Building Generator: set back
  from the lot lines, 1-5 floors rising toward the centre, a plinth for the pad edges), written to
  `buildings/Towns.glb` with a node per town. Farmland round the towns is a COP WFC patchwork of fields (wheat, green
  crop, pasture, ploughed soil) with grass margins: the woodland is cleared from the crops, the margins keep it as
  hedgerows. The tree proxies are exported as LOD chains ending in impostor cards (LOD Create) with hemi-octahedral
  impostor atlases (Impostor Textures). The scattered house instances and their proxy are gone.
- **Building Generator**: `footprint_inset` (setback from the footprint, so touching lots leave lanes) and
  `foundation_depth` (a plinth below the base for uneven ground); the footprint's prim attributes are carried to its
  building's faces.
- **Scene generation, after SideFX Labs** (five nodes):
  - **Lot Subdivision**: cuts blocks into lots by repeated straight cuts (Alignment: Bounding Box / Longest Edge,
    Minimum Lot Size, Iterations, Irregularity, Cluster Lots); concave blocks, shared points, `lot / block / area`.
  - **Building Generator**: footprints to buildings: floors, bays holding modules named by a Facade Module Pattern
    (built in: wall, window, door, shopfront; or a module library on the second input), corner modules, top and
    bottom ledges, flat or parapet roof, per-floor overrides; `building / floor / part / material / module`, a
    group per part, uv in metres.
  - **COP WFC**: Wave Function Collapse (overlapping model) from a sample image, with constraints, rotations,
    tileable output, and an id layer for instancing by value.
  - **LOD Create**: a chain of levels by quadric reduction (Percent Triangles, Threshold Distance per level),
    optional impostor cards as the last level, per-asset chains, `lod / part / name / lod_distance`.
  - **Impostor Textures**: an atlas of views (octahedron, hemi-octahedron, fixed axis, 3D) with base colour,
    alpha, normal, depth and lit beauty layers, and the card to show it on.
- **COP Grunge: fourteen dirt-and-wear maps** (Houdini 22's Grunge nodes): Aurora, Bark Strips, Birch Bark, Drips,
  Galvanized Steel, Layered Noise, Leaking Streaks, Moisture, Mold Spots, Pine Bark, Rust, Rusty Surface, Sheets,
  Wipe Trails. One mono 0-1 layer each, with Houdini's Range (Amplitude, Center, Mask Contrast), Pattern (Element
  Size, Offset, Tile Size) and Post Processing sections; every map tiles over Tile Size. Drips, Bark Strips, Leaking
  Streaks and Rusty Surface carry Houdini's parameter names. The formulas are our own (SideFX does not publish
  them): alike in kind, not pixel for pixel.
- **COP Adjacency: image filters across uv seams** (Houdini 22). COP Geometry to Adjacency rasterises a mesh's uv
  islands and records, around each island, where the surface continues on the island that shares the edge on the
  mesh (layers `adj_mask / uv / valid / jac / near / tri / bary / primid / P / N / tanU / tanV / uvscale`).
  COP Extrapolate with Adjacency fills the texels outside the islands from the neighbours (with Transform Vectors
  between Islands), COP Distort with Adjacency shifts a texture across seams, COP Attribute Sample with Adjacency
  bakes a vertex / point / primitive attribute, COP Space Transform with Adjacency turns vectors between world and
  tangent space. Seams are paired by position (welded or split points); one hop across a seam.
- **World tiles: wear on the terrain layers**. Six Grunge maps (Leaking Streaks, Rust, Moisture, Mold Spots, Layered
  Noise, Sheets) on the layer canvas: water streaks, iron stains and lichen on cliff and strata, exfoliation sheets
  and damp patches on the slab, damp and dust on soil and road, moss between the gravel. The layer tints were
  rescaled so each layer's mean colour (and so the macro map) is unchanged.
- **Wrangle**: `worley3_periodic` takes a seed (engine side; the wrangle functions are unchanged).
- **Wrangle: cellular noise** `worley(p)` / `pworley(p, period)` -> `set(f1, f2, cell id)` and `worley_dir(p)` /
  `pworley_dir(p, period)` -> the vector to the nearest feature point; the `p...` forms tile like `pnoise`. Stones,
  cracks, cobbles and leaves in a COP Wrangle.
- **Geometry Preview: terrain layers**, as an engine's landscape material: `layer1..N` tiled full-colour maps with
  `layerN_normal / _rough / _height / _size`, projected in world space from the three axes; `layer_weights` names
  the splat maps (four layers per RGBA map), `layer_blend` blends by height, `layer_antitile` mixes in a larger,
  turned second sample against visible repeats, `layer_macro` multiplies the layered colour. A new `splat_cop` input
  holds the masks at their own resolution. Weights are kept as 8-bit mip chains.
- **World tiles: close-range terrain**. Over the road view (1.6 x 1.6 km) the preview terrain is a 2 m mesh displaced
  by the 1 m detail height (crags, ribs, ledges, rills as relief with shadows and real silhouettes), set into a hole
  in the 4 m full-map mesh along its grid, the detail fading out to the border so they meet without a crack; the
  grass stands on it.
- **World tiles: twelve terrain layers**. A layer library (lush and dry grass, moss, forest floor, soil, mud, gravel,
  sand, cliff rock, strata, slab, road; 512² tiles of 2-16 m, colour, normal, height, roughness) built from cells and
  noise, three 2 m RGBA splat maps from the surface's masks, and a macro map that keeps the painted 1 m variation;
  written for the engine and used by the previews in place of the four detail maps. Rock faces: streaks and ribs
  stretched along six fixed directions (a per-pixel frame ringed every cone-shaped peak like the grain of a sawn log),
  bedding on a tilted plane, rock in four sub-layers over angular crags, ledges where the beds crop out.
- **Geometry Preview: triplanar detail** (`detail_triplanar = size`): the detail maps projected from the three axes,
  blended by the normal, so on a cliff they keep their shape instead of streaking down the slope along a top-down uv.
- **World tiles: grass and softer trees in the road view**. Grass tufts (six-bladed, the ground's colour, 40 per m²
  at the camera thinning to 2 per m² and none past 140 m) from the grass weight around the road camera, preview
  only (an engine draws its grass from the weight map); tree and bush proxies get soft crown normals; the terrain's
  detail is triplanar.
- **Geometry Preview: detail maps** (Studio and Outdoor looks): `detail1..4` (tiled colour, 0.5 = no change),
  `detail_normal1..4`, `detail_weights` (a layer on the mesh uv) and `detail_tiling`, blended like an engine's detail
  texturing; a new `detail_cop` input holds the small tiles. Close views of a metre-per-texel terrain get their
  centimetres; far away the detail's mips average out.
- **World tiles: houses, ruts, detail maps and a road-level shot**. About 160 houses in the towns, along the roads and
  facing them (instances `SM_House_A..C`, whitewashed slate-roofed proxies); wheel ruts and a grassy crown on the
  roads; four tileable detail maps (grass, rock, gravel, litter) written for the engine and used by the previews; a
  third camera on a road at eye height.
- COP HeightField Road Network: point attribute `road_t`, the direction along the road (for ruts, verges, kerbs).
- **COP HeightField Road Network**: least-cost roads over a height field that keep to a drivable grade (switchbacks
  appear by themselves on steep ground), avoid and block layers, and a network that grows by Prim's algorithm so
  roads branch off roads. Polylines on the terrain with the road-bed height per point.
- **World tiles: roads**. Town sites on flat low ground joined by a road network at a 10 % grade, cut into the
  terrain (bed, cut and fill), a Road weight layer, verges cleared of trees, roads at 1 m in the surface textures,
  and the centre lines written as OBJ polylines.
- **COP HeightField Stream Power Erosion: Erodibility Layer**. K per pixel: hard rock (below 1) stands as cliffs,
  crags and plateaus, soft rock (above 1) wears into broad valleys.
- **World tiles: 1 m terrain textures**. The ecology is taken to 4096² and detailed there: rock outcrops with crisp,
  ragged edges, couloirs and ribs, joints, colour bands, lichen and dark streaks down the faces; rills from the erosion filter;
  grass mottled at three scales, greener in the rills and drier on the spurs; gravel and wet sand. A detail height
  becomes a tangent-space normal map. Written as 4 × 4 tiles of 1024² (BaseColor sRGB, Normal OpenGL) and used by
  both preview shots (`basecolor = @{material}_albedo`, `normal = @{material}_nrm`, `roughness = @{material}_rough`).

### Changed
- Geometry Preview: textures are filtered across face edges where the uv is continuous (a dense mesh such as a
  terrain, nearly every pixel's neighbour another face, kept a footprint of 0 and was not filtered in the distance),
  and anisotropically (the footprint's short axis, up to 8x the long one), as GPUs do.
- Wrangle: `worley(set(x, y))` and the other cellular functions take a 2-vector for the 2D pattern (9 cells, 3x faster).
- Memory: after a node of more than 3 s, and before an outdoor preview render, the garbage collector runs before the
  heap is trimmed: arrays held only by reference cycles had waited for Python's rare full collection, and 2 GB of
  them were still held when the open-world example's first preview started. Detail maps are applied in blocks of a
  million pixels.
- Geometry Preview (Studio, Outdoor): a face seen from behind keeps an authored normal that already faces the viewer
  (it used to be flipped away): grass blades and foliage cards with the ground's up as `N` shade like the ground from
  both sides. Without an authored `N`, or with one facing away, nothing changes.
- COP Rasterize Curves builds its pixel grids per segment window and stores float32: at 4096² it allocated two
  full-image float64 grids (270 MB) per call to draw a few pixels per segment.
- COP Wrangle in bands hands freed memory back after each band.
- **Outdoor look: Haze is in metres** (1 = light falls to 1/e over 12 km, glowing toward the sun). It scaled with the
  bounding box, so a sea quad to the horizon pushed the haze some 600 km out and near and far ridges looked the same;
  the contact shadows (850 m wide) and the cloud-layer height had the same fault and now follow the visible scene.
- **World tiles: a new island**. A ridged spine and a rock-hardness map under Stream Power (sharp ridges, a main peak,
  crags on hard rock, broad valleys on soft), buttresses and couloirs cut down the steep faces, rock only above
  about 55 degrees, terraces gone from the rock relief; both shots lit from the side.
  Erosion follows Houdini's erode - distort - erode recipe with the rock map as HeightField Erode's hardness, and the
  colour reads the terrain like Project Pegasus's colour map: curvature (ridges light, hollows dark) and sediment fans.
- **Normal maps in the preview cost a fraction of the memory**: tangent frames are computed for the textured
  material's triangles only, not the whole scene (a normal-mapped terrain under 48,000 proxy trees took 5.8 GB and
  28 s for its frames; now about 1 GB), and COP texture layers are read as float32 without a float64 copy.
- **Freed memory goes back to the system after long nodes** (Linux): glibc kept what a 4096² COP Wrangle run in
  bands had freed (1.7 GB for a 384 MB result), and ComfyUI's output cache piled it up node after node.
- COP Wrangle run in bands (*Rows per Pass*) converts only each band's rows to float64: it converted the whole layer
  on every access, a 400 MB copy per layer per band on a 4096² image (the surface textures now take half the time).
  The bands are assembled in float32 on the numpy backend (the layers are stored as float32 anyway).
- COP Write File's *preview* output is at most 2048 px on its longest side (box average); the files are full size.
- COP Write File encodes tile by tile (same bytes as before): an sRGB 4096² BaseColor no longer peaks at 2 GB of
  whole-image float64 temporaries.

### Fixed
- **World tiles: the road camera** (Road, Dusk, Rain) sat at a fixed height 1.8 m over the road as one run made it;
  a terrain made a little differently (another GPU's erosion) buried it, and the frames showed the terrain from
  below. It now stands 1.8 m over the terrain the run made (Eye Above Ground).
- **Inside subgraphs**: the Tab node menu put new nodes into the top-level graph, Y-cut and shake worked on the
  top-level wires, the group / attribute ▾ pickers looked upstream there, and a COP node's thumbnail never showed.
- **Renders on a CUDA GPU (Compute auto / cuda)**: the rasterizer's float32 got the depth of triangles reaching far off
  screen wrong -- a sea plane cut at the near plane has corners at millions of pixels -- so the world tiles' sea came
  out in front of the land in bands of rows (Whole world) or over the whole frame (Dusk, Rain: only the reflection on
  the water showed). Such triangles now get their fragments in float64; the rest stays float32. (The CPU path was
  never affected, which is why the example renders here were right.)
- **Parameters (PCG)** no longer appends its generated controls to `widgets_values` (they were saved after the two
  real values on every save); Tutorial 6 stores its values the way the frontend writes them back.
- **Loading big graphs** (the parameter panel): every panel measured its height on the spot as the graph loaded --
  a forced layout of the whole page, three times per node -- and the code boxes all set themselves up at once: the
  world tiles graph took 36 s to load in the frontend, now 2.3 s (13 s with every node open). Collapsed nodes get
  their panel when first opened; panels off the visible canvas are measured together in one layout before the next
  frame; code boxes are highlighted when they first come into view.
- **Example layouts**: the frontend widens a node with a code box to 400 px and draws image nodes some 35 px taller
  than before; the layouts leave room for both (no overlapping nodes in the real frontend).
- **World Manifest on Windows**: the height's sidecar was looked up by a path spelt with forward slashes
  (`...\output\pcg/world/height/Height.json`) in a table filled from os.walk's back-slashed paths, and the node
  failed with a KeyError at the end of the world tiles run; paths are now compared normalised (the same for the list
  of files it had already accounted for).
- **Code highlighting** (`pcg_codehl.js`): a code box whose DOM was not in the document yet threw (`insertBefore` of
  null; 137 times on the world tiles graph) instead of being attached later; one shared timer now replaces the one
  per box (hundreds on a big graph) and skips hidden boxes.
- **COP Wrangle in bands** (`rows_per_pass`) kept every finished band's input rows (and, on several threads, its
  results) alive until the garbage collector ran: a 2048² splat Wrangle in 128-row bands peaked 1.9 GB over its input,
  now 0.7 GB; the world tiles run peaks some 1.3 GB lower.
- **World tiles**: the 1 m surface Wrangle read the slope layer `upb` without it ever reaching that set (a Wrangle
  reads a missing layer as 0), so its slope-driven materials took every pixel for steep ground; the layer is merged
  in now.

## [0.2.0] - 2026-11-13

### Added
- **Progress and Cancel for long nodes**: the erosion nodes (HeightField Erode, Stream Power, Thermal, Hydraulic),
  the reaction-diffusion / ripple / fluid solvers and the Outdoor render advance ComfyUI's progress bar and stop
  when the queue is cancelled.
- **Outdoor look on the GPU**: *Compute* on Geometry Preview (auto = CUDA when available) runs the shadow maps and
  the sky light in torch; same picture as numpy to float32 rounding.
- **COP HeightField Erode: Bed Change Limit**. Caps how far the bed moves per step relative to the water depth;
  0.03 stops the washboard ripples a Capacity above about 3 used to make, so deep gullies can be carved directly.
- 39 more node pictures in the reference.
- **Outdoor look, lit like a photograph** (Geometry Preview): the sky is an area light with shadows (*Sky Samples*
  directions, each with its own depth map: narrow streets are darker than squares, eaves shade walls) plus one bounce
  of light off the scene; soft sun shadows that are crisp at contact and widen with distance; sky colours that
  follow the sun's elevation; a cumulus layer (*Clouds*, *Cloud Seed*) that also shades the ground; bloom, a slight
  vignette and the AgX tone curve. Per-material COP textures (`orm = @{material}_orm`: faces whose layer does not
  exist keep their own colour).
- **Studio look**: soft key-light shadows with contact hardening, occlusion from the whole studio dome (objects sit
  in a pool of shade instead of floating), a lighter backdrop with a pool of light on the floor.
- **COP HeightField Erode**: grid-based hydraulic erosion like Houdini's HeightField Erode (Hydro) -- rain on every
  cell, water flowing through virtual pipes, sediment carried and deposited, thermal slumping in the same solver --
  writing flow, water, sediment and debris masks. Material is conserved exactly; runs on CUDA when available.
- **Packed primitives**: Pack and Unpack nodes, *Pack and Instance* on Copy to Points (one packed primitive per copy),
  and GPU instancing in the viewport (one InstancedMesh per distinct piece). Transform, Merge, Blast / Delete, Sort and
  the point attribute / group nodes keep geometry packed; every other node unpacks its input automatically.
  Copy to Points (packed) -> Unpack is identical to Copy to Points.
- **Distance from Geometry** (to a surface, edges or points; Max Distance; 0..1 mask through a ramp) and
  **Distance along Geometry** (geodesic distance by the heat method, or shortest path along edges).
- **Path Deform**: bend geometry along a curve (rotation-minimising frames, stretch, offset, roll, twist).
- **PolyWire**: tubes along curve networks with junction spheres and round / flat end caps.
- **Thicken**: give open surfaces a thickness (outward, inward or centered).
- **Curve Fillet**: round polyline corners with tangent arcs.
- **Assemble**: name the connected pieces of a mesh (piece0, piece1 ...) and optionally pack each piece.
- **Export Mesh GPU instancing**: packed primitives are written to glb as one mesh per piece plus per-instance
  transforms (`EXT_mesh_gpu_instancing`); sheared pieces, OBJ and the option off unpack. **Export Instances** reads
  packed primitives directly (one row each, asset from the name attribute or the piece).
- **Viewport selection**: S toggles click / box selection of points or primitives (Shift adds, Ctrl removes, visible
  only); the selection becomes a group expression to copy or to turn into a wired Group Create node.
- **Geometry Spreadsheet paging**: page buttons and a jump-to-row field fetch pages from a server cache, without
  re-running the graph.
- **PolyDoctor Self-Intersecting Polygons** (mark), via Intersection Analysis.
- **Import Mesh reads LAS** (point formats 0-3, 6-8, no dependency) and LAZ (optional `laspy`), with LiDAR attributes,
  RGB colour and recentring of survey coordinates (`las_origin`).
- **VDB Clip to a camera frustum** (Clip To = Camera Frustum, with Padding).
- **Geometry Preview Outdoor look**: perspective environment shots through a Camera node (or an automatic 35 mm
  camera), sky with a sun, sun shadows with sky fill and ground bounce, aerial perspective (Haze), an optional ground
  plane to the horizon; PBR surfaces reflect the sky.
- **Example workflows, less demo, more production**:
  - modular city: facade variants per building (red brick, buff brick, painted render with paired windows) via a
    `facade` column, rooftop plant (condensers, water tanks), asphalt streets with road paint, parked cars, better
    trees, low-detail context blocks with whole-bay facade textures, two hero cameras in the Outdoor look;
  - world tiles: pine / broadleaf / bush / rock proxies and a low camera toward the range with haze;
  - rock assets: crisp, faceted rocks with a split face and irregular layer joints, LOD0 at 9 cm voxels;
  - material library: six new materials (buff brick, painted render, asphalt, bitumen roofing, two facade bays).

### Changed
- World tiles example is now a 4 km island grown by its rivers: Stream Power raises the whole island against
  erosion down to the sea, so every slope belongs to a branching valley and there are no flat interiors; then
  buttresses, gullies (HeightField Erode, Capacity 4 with the bed change limit), river beds cut into the valley
  floors, beaches, rock outcrops, scree, woodland in the valleys, grass darker along every gully, a sea to the
  horizon; a second camera from a ridge toward the main peak. The weight layers are now Grass / ForestFloor /
  Sediment / Rock / Sand / Water (Sand replaces Snow).
- **Production examples reworked for picture quality.** World tiles: now 4 km x 4 km at 4 m cells, a range with
  rounded ridges and natural slopes (hillslope diffusion in the Stream Power pass), forest climbing the slopes to a
  ragged tree line, 40,000 trees with per-instance tints, mirror lakes, a side-lit low sun with clouds and haze.
  Modular city: a green belt with trees around the plot, context blocks on their own ground, fuller street trees,
  new hero cameras and light. Rock assets: weathering lumps, pits and iron staining in the texel detail.
- Rendering 8 million faces takes 3 GB less memory (triangles and convex quads are cut directly, face normals are
  computed once, materials are looked up as codes).
- **Open-world terrain example** rebuilt the Houdini way: Stream Power grows a dendritic range, HeightField Erode
  passes at 513² and 1025² with an erosion-filter gully pattern in between; materials and vegetation now come from
  the erosion masks (water-streaked rock, scree, grassed alluvium, clumped forest with a ragged tree line, tree size
  by wetness); side-lit camera closer to the range.
- Second performance round: PolyBevel ~17x on dense meshes (a per-point scan of every corner was O(points x
  corners); corner candidates vectorized); Intersection Analysis 15-80x (KD-tree candidate pairs instead of testing
  every edge against every triangle, identical output); Voronoi Fracture ~1.8x (cuts that change nothing are skipped;
  bit-identical output); Volume Rasterize
  Particles 4-8x for small particles; the jump-flood pass of the SDF builder ~15% faster.
- Faster closest-point queries (Ray minimum distance, Shrinkwrap, Remesh, Boolean, Scatter Align, Iso Surface, VDB surface attributes,
  Point Relax ...): a KD tree gives each query a tight bound and one ball of candidates. 10k points on a 7.2k-face
  sphere: 31 s / 3.8 GB -> 1 s / 0.2 GB. Results are bit-identical; without scipy the old path is used.
- Triangulate 2D uses Qhull for the Delaunay step and a KD tree for welding: 22.5k points 7 s -> 0.3 s (exact
  Delaunay, every point kept; an explicitly looser Hull Tolerance keeps the previous hull).
- VDB from Polygons: about 2.5x faster (scatter-min instead of a sort, a bounding-sphere prefilter, and no far-field
  pass when Fill Interior is off). Output unchanged.
- The 3D viewport draws on demand instead of 60 times a second: idle viewports no longer use GPU / CPU.

### Fixed
- **Stream Power Erosion**: across the lakes filled at the start, rivers follow the drowned valley instead of the
  straight epsilon slope of pit filling (as Flow Accumulation already did).
- **Outdoor look**: the sun's shadow map now frames the visible ground around the geometry too; shadows cast by the
  lower part of a tall object used to be missing next to it when the camera only saw its top.
- **Outdoor look**: no more staircase of bright triangles along shadow terminators on coarse meshes (grazing faces
  are now faded into shadow instead of treated as lit; the shadow normal offset scales with the face size).
- **COP Flow Accumulation**: water crossing a filled lake no longer runs down the pit-filling epsilon slope,
  which drew ruler-straight 0° / 45° lines and hatching across every lake and long filled valley floor. Lake pixels
  now drain along the drowned valley (a second priority flood over the original terrain, from the lake's exit).
- COP Noise: Tile U is greyed out for the Torus noise type again.
- Removed unreachable leftover code in the geometry preview renderer and unused variables found by a lint pass.

## [0.1.0] - 2026-11-04

First public release.

### Added
- **494 nodes** under `PCG/`, all in numpy: geometry (SOP-style; generate, modify, attribute, group, topology, UV,
  scatter, deform, render, loops), 68 volume and VDB nodes, and 182 image nodes in a Copernicus-style COP context.
- Houdini's geometry data model: points, primitives, vertices and detail; typed attributes; point / primitive / edge
  groups with Houdini's group pattern syntax.
- Volumes and VDB: the VDB SOPs (from Polygons / Particles, Activate, Combine, Smooth, Advect, Analysis, Fracture, to
  Spheres, Segment, Resample, Project Non-Divergent ...) and the other Volume SOPs, on dense grids with VDB semantics
  (active mask, background value, vector grids).
- Houdini-style parameter panels (tabs, folders, ramps, hide-when / disable-when), display and template flags, a
  geometry spreadsheet, a playbar with keyframes, spare parameters on any node.
- Expressions in parameter fields (`ch()`, relative references, `$F` and the other frame variables, geometry queries,
  string templates) and a VEX-like Wrangle for geometry, volumes and COP images, with type prefixes, `@group_`,
  `pnoise()` for seamless textures and automatic `ch()` parameters.
- A 3D viewport (three.js) with transform and shape handles, a curve drawing tool, Cd shown as in Houdini, a UV view
  (key 5) and UV checker shading, fog volumes ray-marched as smoke and SDFs as closed surfaces.
- Geometry Preview with a *Studio* look: shadows, ambient occlusion, a shadow-catching ground, supersampling and
  BaseColor / normal textures from files or straight from a COP image.
- For-Each and frame loops; trails, retiming and time blending.
- Render passes for ControlNet (depth, normal, ID, regional prompts), texture baking (normal, displacement, AO,
  position, tangent frames) and UV back-projection of generated images.
- Convex decomposition with a vertex budget per hull for engine collision.
- Export to glb / obj (split by attribute, textures attached), instance tables, 8 / 16 / 32-bit image files and
  height-map tiles with shared edges.
- Network editor: Houdini-style rounded wires, rewiring by dragging a wire end, cutting wires with Y, shake to
  disconnect, snapping and Alt-drag arranging, a Tab menu of PCG nodes, dashed lines to parameter references.
- 16 example workflows with walkthroughs: six tutorials, showcases, four production pipelines (rock assets with LODs,
  baked textures and collision; 4 × 4 open-world terrain tiles; a modular city kit; an 8-material PBR library) and AI
  round trips.
- Documentation for every node and parameter with the Houdini equivalent and known differences, concept pages
  (geometry, groups, parameters, expressions, Wrangle syntax, loops, images, viewing and export, wires, keyboard and
  mouse), and an HTML version published with GitHub Pages.
- About 100 test suites with analytic checks, negative controls and mutation tests; CI on GitHub Actions.

### Security
- Wrangle code, group expressions and Expression / Switch formulas are Python run on the ComfyUI server. A code guard
  rejects imports, Python internals and numpy's file functions before anything runs; it is a guard, not a sandbox.
  Run workflows only from people you trust. See [Wrangle syntax: Security](docs/concepts/wrangle.md#security).

### Known limitations
- Parameter expressions and geometry queries are evaluated in the browser; headless / API runs use the last values
  written by the UI, and geometry queries lag one run.
- Remesh adaptive edge lengths, curve tangent handles and weights, viewport component selection, font kerning (GPOS)
  and edge groups through Boolean are not implemented yet.

[Unreleased]: https://github.com/fedrov/comfyui_pcg/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/fedrov/comfyui_pcg/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/fedrov/comfyui_pcg/releases/tag/v0.1.0
