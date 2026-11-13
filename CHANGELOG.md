# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
