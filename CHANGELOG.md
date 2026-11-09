# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

[Unreleased]: https://github.com/fedrov/comfyui_pcg/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/fedrov/comfyui_pcg/releases/tag/v0.1.0
