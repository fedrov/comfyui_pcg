# Output & Export

Writing files and exporting to other applications.

9 nodes.

[Back to the reference index](README.md)

## Contents

- [Display (PCG)](#pcg-display) — Passes geometry through and acts as the target of the display flag shown in the persistent viewer panel.
- [Export Instances (PCG)](#pcg-exportinstances) — Writes points as an instance table (CSV or JSON) with asset name, position, rotation and scale for game engines.
- [Export Mesh (PCG)](#pcg-exportmesh) — Writes geometry to a .glb or .obj file under the ComfyUI output directory and returns its relative path.
- [File Cache (PCG)](#pcg-filecache) — Caches geometry to disk and reloads it later without cooking the upstream chain.
- [Geo Metrics (PCG)](#pcg-geometrics) — Measures a geometry's quality (counts, closedness, manifoldness, normals, degenerate faces, UV usage, genus) and outputs the numbers.
- [Geometry Preview (PCG)](#pcg-previewimage) — Renders a software-rasterised preview of geometry to a standard IMAGE.
- [Geometry Spreadsheet (PCG)](#pcg-geospreadsheet) — Shows geometry attributes in a table inside the node, like Houdini's Geometry Spreadsheet.
- [Viewport (PCG)](#pcg-viewport) — Shows geometry in an interactive 3D viewport embedded in the node body and passes the geometry through.
- [World Manifest (PCG)](#pcg-worldmanifest) — Writes World.json, one file describing an exported world, plus one manifest per streaming tile.

## Nodes

### Display (PCG)

<a id="pcg-display"></a>

`PCG_Display` · category `PCG/output`

Passes geometry through and acts as the target of the display flag shown in the persistent viewer panel.

The anchor for the display / template flag. In Houdini the display flag itself causes the chain to cook; ComfyUI only executes nodes that lead to an output node, so an intermediate node that is not connected to anything never runs. The display flag therefore works by rewiring this node's `geo` input to the flagged node, so the link on the canvas is the real execution dependency. It survives save/load, undo and copy/paste like any other link.

The node has no canvas of its own: the image is shown in the persistent viewer panel. A graph normally needs only one Display, and the flag moves its input to wherever you click. Use Viewport (PCG) instead when you want a viewer embedded in the node body, for example to pin two branches side by side. Both use the same transport and the same viewer, so they draw identically.

The geometry is passed through unchanged, so Display can sit in the middle of a chain.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to display. |
| `template` *(optional)* | GEOMETRY | Optional geometry drawn as a grey wireframe for reference only, like a Houdini template flag. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The input geometry, unchanged. |

**Compared with Houdini**

Houdini's display flag is a node flag that drives cooking. Here it is a sink node whose input is rewired, because ComfyUI only evaluates what leads to an output node.

---

### Export Instances (PCG)

<a id="pcg-exportinstances"></a>

`PCG_ExportInstances` · category `PCG/output`

Writes points as an instance table (CSV or JSON) with asset name, position, rotation and scale for game engines.

Turns scattered points into one row per instance: `asset`, position `px py pz`, quaternion `qx qy qz qw`, Euler angles `rx ry rz` (degrees, XYZ order, `R = Rz*Ry*Rx`) and scale `sx sy sz`, followed by any extra point attributes you list. The transform is read exactly as Copy to Points reads it (`orient` > `N` + `up` > `pscale` and so on), so what you preview with Copy to Points is what the table describes.

Axis Map converts to another coordinate system and rotations are converted along with positions. Unit Scale is applied to positions only. With Tile Size above 0 the points are split by their original x and z into tiles, one file per tile, and an `_index.json` listing every tile is written next to them. Files are written under the ComfyUI output directory. The node is an output node and returns a text report of what was written.

It raises an error if the Asset Attribute or an Extra Attribute does not exist on the points.

Packed primitives are read directly: one row per packed primitive, with its own transform and the position where the piece's origin lands. The asset name comes from the point attribute, then the primitive attribute of that name (Pack and Assemble write `name`), and otherwise `piece0`, `piece1` ... per distinct piece.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `points` | GEOMETRY | Points to export. One table row is written per point. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `report` | STRING | Text report: columns, axis map, unit scale, instance count, the files written (with tile and count) and the asset names found. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Output File `filename` | string | `pcg/instances/instances` | Output path relative to the ComfyUI output directory, without extension (`.csv` or `.json` is appended). `{index}` is replaced by Index, and `{tx}` / `{ty}` by the tile numbers when tiling is on. |
| Format `format` | menu | CSV | CSV writes a header plus one line per instance; JSON writes an object with the column metadata and an `instances` list. Options: CSV (`csv`), JSON (`json`). |
| Asset Attribute `asset_attribute` | string | `name` | Point attribute (string or integer) written to the `asset` column, usually the name of the mesh or prefab to instance. Empty leaves the column blank. |
| Extra Attributes `extra_attributes` | string | *(empty)* | Space-separated point attribute names to append as extra columns. Vector attributes are split into `name_0`, `name_1` and so on. |
| Axis Map `axis_map` | string | `x y z` | Three words saying which original axis each new x, y, z takes, optionally negated. `x y z` keeps the data as is (Y up), `x -z y` gives Z up right-handed, `x z y` gives Z up left-handed. Rotations are converted too. |
| Unit Scale `unit_scale` | float [1e-06..] | 1 | Multiplier applied to positions, for example 100 to convert metres to centimetres. |
| Tile Size `tile_size` | float [0.0..] | 0 | Above 0, points are grouped into square tiles of this size by their original x and z, one file per tile, plus an `_index.json`. Include `{tx}` and `{ty}` in the filename to keep tiles apart. 0 writes a single file. |
| Index `index` | int [0..] | 0 | Number substituted for `{index}` in the filename, for example to write one file per iteration of a loop. |

**Compared with Houdini**

Corresponds to a ROP that outputs instance points and to the Labs instance export; the output here is a plain CSV / JSON table.

---

### Export Mesh (PCG)

<a id="pcg-exportmesh"></a>

`PCG_ExportMesh` · category `PCG/output`

Writes geometry to a .glb or .obj file under the ComfyUI output directory and returns its relative path.

Writes the file directly, without an external mesh library, with UVs, normals (hard edges from vertex `N` are preferred), tangents and vertex colours. The tangents use the same convention as COP Bake Textures, so baked normal maps match. The returned path of a `.glb` can be connected straight to ComfyUI's Preview3D node.

glTF follows the specification: Y up, metres, and the UV origin at the top left (v is written as 1 - v). Scale multiplies positions, so use 100 for centimetres.

Split by Attribute divides the mesh into several meshes / nodes in one file, named after the values of a primitive attribute; this is how LOD or collision naming conventions are produced. File per Attribute writes a separate file per value of another primitive attribute as `filename_value.ext`; `{name}` in the filename is replaced by the value instead.

Textures attaches external image references to the materials: one `slot = path` per line, with slots `basecolor`, `normal`, `orm` and `emissive`. Paths are relative to the exported file and `{material}` is replaced by the material slot name. `orm` serves as both occlusion and metallicRoughness (R = AO, G = roughness, B = metal), and `normal` should be the OpenGL (+Y) map. OBJ output also writes a `.mtl` file.

With **GPU Instancing** on (the default) a `.glb` writes packed primitives (from Pack, Assemble or Copy to Points with Pack and Instance) as one mesh per distinct piece plus one node carrying the `EXT_mesh_gpu_instancing` extension, which stores each instance's translation, rotation and scale. Ten thousand rocks become one rock mesh and ten thousand transforms. Pieces whose transforms contain shear (not expressible as translation x rotation x scale) are unpacked into ordinary geometry instead; OBJ output, or the option off, always unpacks. Per-instance point attributes such as `Cd` are not written to instanced pieces.

**LOD manifest.** With `LOD Manifest` on, a JSON file is written beside the mesh with what an engine needs to set the LOD chains up: per asset the levels (node, distance, triangles), bounds, materials, Unreal Screen Sizes and Unity LODGroup transition heights, in the file's units.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to export. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `path` | STRING | Path of the written file relative to the output directory. With File per Attribute, one path per line. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Output File `filename` | string | `pcg/mesh` | Output path relative to the ComfyUI output directory, without extension. With File per Attribute you may include `{name}`. |
| Format `format` | menu | glTF Binary (.glb) | Binary glTF (`.glb`) or Wavefront OBJ. Options: glTF Binary (.glb) (`glb`), Wavefront (.obj) (`obj`). |
| Scale `scale` | float [1e-06..] | 1 | Multiplier applied to positions (use 100 for centimetres). |
| Split by Attribute `split_attribute` | string | *(empty)* | Primitive attribute whose values split the mesh into separate meshes / nodes inside the file. The attribute value becomes the name. Empty keeps one mesh. |
| File per Attribute `file_attribute` | string | *(empty)* | Primitive attribute whose values split the output into separate files named `filename_value.ext`. Empty writes one file. |

*Textures*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Textures `textures` | string | *(empty)* | One `slot = path` per line (`basecolor`, `normal`, `orm`, `emissive`). Paths are relative to the exported file; `{material}` is replaced with the material slot name. In `.glb` they are written as external image references. |
| Texture Materials `texture_materials` | string | `*` | Space-separated wildcard patterns limiting which material slots receive the textures. `*` matches all. |

| Parameter | Type | Default | Description |
|---|---|---|---|
| GPU Instancing `gpu_instancing` | toggle | on | glb only: write packed primitives as instanced meshes (EXT_mesh_gpu_instancing) instead of unpacking them. *Disabled when format ≠ glb.* |

*LOD Manifest*

| Parameter | Type | Default | Description |
|---|---|---|---|
| LOD Manifest `lod_manifest` | toggle | off | Also write `<filename>.lods.json`: per asset (prims named `<asset>_LOD<k>`, as LOD Create writes them) its LOD node names, switch distances (`lod_distance`), triangle counts, bounds and materials, plus Unreal per-LOD Screen Size (`r / (d tan(fov/2))`, the fraction of the screen height the bounding sphere covers) and Unity LODGroup `screenRelativeTransitionHeight` per level (the next level's screen size). |

| Parameter | Type | Default | Description |
|---|---|---|---|
| Camera FOV `lod_fov` | float [1.0..179.0] | 60 | Vertical field of view, in degrees, of the camera the screen sizes are computed for. *Disabled when lod_manifest is off.* |
| Cull Screen Size `lod_cull_screen_size` | float [0.0..1.0] | 0 | Screen size at which the last level ends in the Unity values (0 = never culled). *Disabled when lod_manifest is off.* |

---

### File Cache (PCG)

<a id="pcg-filecache"></a>

`PCG_FileCache` · category `PCG/output` · Houdini: File Cache (SOP), Stash (SOP)

Caches geometry to disk and reloads it later without cooking the upstream chain.

Geometry lives in the Python process and cannot be stored in the workflow file, so reopening ComfyUI normally recomputes the whole chain. File Cache computes once, writes to disk, and reads from disk afterwards.

When the node reads from disk, the upstream is genuinely not executed: the `geo` input is lazy, and the read modes ask ComfyUI not to evaluate it. This is what makes the cache save time.

In `auto` mode the file is read if it exists and written otherwise. `write` always recomputes and overwrites (use it after changing the upstream), and `read` always loads and raises an error if the file is missing; it never evaluates the upstream. In the file path `$F` and `$F4` are replaced by the Frame value (`$F4` zero-padded to 4 digits) and `$V` by Version. A path without extension gets `.npz`. Relative paths are placed under the ComfyUI output directory.

The format is `.npz` plus a JSON manifest, with no pickle, so cache files are safe to copy around. Primitive data (`prim_data`) must be numpy arrays.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` *(optional)* | GEOMETRY | Geometry to cache. Optional and lazy: it is not evaluated when the node reads from disk. Required when the node has to write. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The geometry, either freshly computed or loaded from disk. |
| `path` | STRING | Absolute path of the cache file used. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Mode `mode` | menu | Automatic (Read if Exists) | `auto` reads the file if it exists, otherwise writes it. `write` always recomputes and overwrites. `read` always reads and errors if the file is missing. Options: Automatic (Read if Exists) (`auto`), Always Write (`write`), Load from Disk (`read`). |
| Geometry File `file` | string | `pcg_cache/geo_$F4.npz` | Cache file path, relative to the ComfyUI output directory. `$F` / `$F4` is replaced by Frame and `$V` by Version. |
| Version `version` | int [0..] | 1 | Number substituted for `$V` in the path. Bump it to keep several caches side by side. |
| Frame `frame` | int | 0 | Frame number substituted for `$F` / `$F4`. Not read from the timeline automatically; connect it from a Frame or For-Each Frame Begin output for per-frame caches. |
| Compress `compress` | toggle | on | Compress the written file. Not shown in Load from Disk mode. *Hidden when mode = read.* |
| Reload `reload` | int [0..] | 0 | Change this number to force a re-read or re-write on the next run. |

**Compared with Houdini**

Corresponds to the File Cache SOP (and covers the Stash use case). Files are `.npz` with a JSON manifest rather than `.bgeo`.

**Tips**

- Use `auto` in daily work and switch to `write` once when the upstream changed.
- For per-frame caches put the path with `$F4` inside a For-Each Frame block and connect `frame` from the loop.

---

### Geo Metrics (PCG)

<a id="pcg-geometrics"></a>

`PCG_GeoMetrics` · category `PCG/output` · Houdini: UV Visualize (SOP)

Measures a geometry's quality (counts, closedness, manifoldness, normals, degenerate faces, UV usage, genus) and outputs the numbers.

Computes objective, deterministic metrics, for automatic selection or as a QA check: element counts, area, signed volume, bounding box, edge lengths, connected components, edge topology, triangle quality, duplicate points, UV statistics, Euler characteristic and genus. Examples of names: `prims`, `points`, `closed`, `boundary_edges`, `nonmanifold_edges`, `flipped_edges`, `degenerate_prims`, `duplicate_points`, `components`, `euler`, `genus`, `tri_quality_min`, `uv_coverage`, `uv_overlap`. The full set is in the `json` output.

Three to watch: `closed` / `boundary_edges` (booleans and volumes need a watertight mesh), `flipped_edges` (neighbouring faces wound in opposite directions, which shows up as black faces or wrong booleans while the mesh looks fine) and `genus` (for a closed manifold, (2 - euler) / 2: 0 for a sphere, 1 for a torus; it is NaN otherwise and is not written to detail). `volume` is signed: on a closed mesh it is the true volume and goes negative if the whole mesh is inside out. `flipped_edges` cannot catch that case because a fully flipped mesh is still consistent, so read both together.

UV coverage and overlap are counted on a `uv_res` x `uv_res` texel grid, so their precision is 1 / `uv_res` and depends on it; overlap counts distinct primitives, not triangles. Self-intersection is deliberately not measured.

With Write Detail on, every metric is also written as a detail attribute on the output geometry (readable with `detail("prims")`; Select Best uses these).

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to measure. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The input geometry, with the metrics added as detail attributes if Write Detail is on. |
| `json` | STRING | All metrics as a JSON object. |
| `value` | FLOAT | The metric named by Pick, as a float. |
| `int` | INT | The same metric rounded to an integer. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Compute Triangle Quality `compute_quality` | toggle | on | Compute triangle quality (`tri_quality_min`, `tri_quality_mean`), degenerate primitives and duplicate points. |
| Compute UV Metrics `compute_uv` | toggle | on | Compute UV statistics (`uv_area`, `uv_flipped`, `uv_out_of_range`, `uv_coverage`, `uv_overlap`). Needs a UV attribute. |
| UV Attribute `uv_attrib` | string | `uv` | Vertex attribute holding the UVs. Only used when Compute UV is on. *Disabled when compute_uv is off.* |
| UV Raster Resolution `uv_res` | int [8..2048] | 128 | Texel grid resolution for UV coverage and overlap. Higher is more precise and slower. Only used when Compute UV is on. *Disabled when compute_uv is off.* |
| Write Detail Attributes `write_detail` | toggle | on | Write all metrics onto the geometry as detail attributes. |
| Attribute Prefix `prefix` | string | *(empty)* | Text put in front of every written detail attribute name, to avoid clashes with existing attributes. Only used when Write Detail is on. *Disabled when write_detail is off.* |
| Value Output `pick` | string | `prims` | Name of the metric sent to the `value` and `int` outputs, for example `prims` or `genus`. An unknown name raises an error listing the valid ones. Empty outputs 0. |
| JSON Indent `indent` | int [0..8] | 1 | Indentation of the `json` output. 0 gives a single compact line. |

**Compared with Houdini**

No single Houdini SOP produces these numbers; the UV statistics are comparable to what UV Visualize shows.

---

### Geometry Preview (PCG)

<a id="pcg-previewimage"></a>

`PCG_PreviewImage` · category `PCG/output`

Renders a software-rasterised preview of geometry to a standard IMAGE.

Renders the geometry with a built-in orthographic rasteriser, with no GPU or OpenGL needed. The output is a normal ComfyUI IMAGE, so it can be connected to PreviewImage or SaveImage. The camera is framed to the bounding sphere. Azimuth 0 and elevation 0 look along the -Z axis from +Z.

Shading: **Normal** colours by world-space face normal, **Lambert** is a grey model with one directional light, **Color** is `Cd` multiplied by lighting (`Cd` is looked up on point, vertex, primitive and detail; without it the result is grey). Rasterisation is vectorised, so meshes with hundreds of thousands of triangles take about a second. Empty geometry gives a black image. Requires `torch`.

**Studio** look: smooth shading from `N`, a key light with shadows, sky fill and a soft highlight, screen-space ambient occlusion, a ground that only catches shadows and fades into a gradient background, and supersampling for clean edges. It also maps textures, with the same `slot = path` lines as Export Mesh: `basecolor`, `normal` (tangent space, OpenGL +Y) and `orm` (R = AO, G = roughness, B = metallic), or `ao`, `roughness` and `metallic` separately. A roughness or metallic map switches the surface to metal-rough PBR shading: a GGX highlight from the key light, the studio (ceiling, floor, a softbox and a strip light beside the camera) reflected with Schlick Fresnel, F0 = 0.04 for dielectrics and BaseColor for metals, and the AO map multiplied into the occlusion. Without one the shading is the plain diffuse look with a soft highlight, so polished glass or bare metal would show only as dark surfaces. Paths are relative to ComfyUI's output folder, so files written earlier in the graph can be used, and `{material}` is replaced by each face's material name (a string prim attribute, Material Attribute). The normal map uses the same tangent frames Export Mesh writes and COP Bake Textures bakes against, so a baked map looks as it will in an engine. A material whose file does not exist keeps its `Cd` and mesh normal. A value `@layer` takes that layer from the COP image connected to **textures_cop** instead of a file, for example `basecolor = @basecolor` and `normal = @normal_ts` straight from COP Bake Textures, or `orm = @ao roughness metallic` to pack three layers like an ORM file, which avoids depending on files being written first. The camera direction is the same as Basic, but the frame fits the object's projected extent, so a row of objects fills a wide image. Shading is ignored in Studio.

The **Outdoor** look renders an environment shot instead of an object on a studio floor: a perspective camera (the connected Camera node, or an automatic 35 mm camera at Elevation / Azimuth), a sky with a sun, warm sun light with shadows plus blue sky fill and ground bounce, aerial perspective that fades distant surfaces toward the horizon, and an optional ground plane to the horizon. Textures and PBR work as in the studio look; glossy surfaces reflect the sky. A face seen from behind turns its normal to the viewer, unless its authored `N` already faces the viewer: grass blades and foliage cards that carry the ground's up as `N` shade like the ground from both sides. Use it for streets, towns and terrain where scale and depth matter; keep Studio for asset turnarounds.

The outdoor look lights the scene like a photograph: the sky is an area light with shadows and one bounce of light off the scene, so narrow streets are darker than open squares and shadowed walls pick up warm light from sunlit ground; sun shadows are crisp at contact and soften with distance; the sky's colours follow the sun's elevation; the frame is finished with bloom, a slight vignette and the AgX tone curve.

**Guide passes**: the outdoor look also returns the same frame's depth and normal passes (outputs `depth` and `normal`), so a render can steer a ControlNet with exactly the geometry it shows.

**Weather and light** (Outdoor, all off by default): Snow lays snow on upward faces above Snow Line; Wetness darkens and glosses the ground with puddles; Emit Attribute adds emitted light (lit windows), and the lights input adds point lights (street lamps), so with the sun just below the horizon a town lights up. **Camera sequences**: with the cameras input every camera is rendered into a batch of frames, for a flyby.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to render. |
| `textures_cop` *(optional)* | COPIMAGE | Optional COP image whose layers Textures can name with `@layer` (Studio look). |
| `camera` *(optional)* | PCGCAM | Optional camera for the Outdoor look (any Camera node; its view is rendered in perspective). Without it an automatic 35 mm camera at Elevation / Azimuth frames the geometry. |
| `detail_cop` *(optional)* | COPIMAGE | Optional COP image holding small tiled maps: the detail maps (detail1..4, detail_normal1..4) and the terrain layers (layer1.., layer1_normal ..) in Textures read `@layer` from here (the textures image is terrain-sized; a tile is a few hundred pixels). |
| `splat_cop` *(optional)* | COPIMAGE | Optional COP image with the terrain layers' masks and macro map (layer_weights, layer_macro), at their own resolution: 2 m splat maps beside a 1 m surface. Without it they are read from textures_cop. |
| `extra_geo` *(optional)* | GEOMETRY | Optional geometry drawn together with `geo`: a per-shot part, such as trees and impostor cards turned to this camera, beside a large shared scene. In the Outdoor look the two are rasterized separately and the nearer surface wins each pixel (shadows and sky light see both), so the scene is not copied; the other looks merge them, with only what the render reads (P, N, Alpha, the colour, uv and material attributes, shadow_only). A geometry lacking the material or uv attribute is treated as having empty / zero values, as a merge would fill them. |
| `lights` *(optional)* | GEOMETRY | Optional points lit as unshadowed point lights (Outdoor): `P` the light's place, `Cd` its colour (default warm), `intensity` its strength (default 10; the irradiance at 1 m is about intensity / 2), falling to nothing at Light Range. Street lamps at dusk. |
| `cameras` *(optional)* | PCGCAMSEQ | Optional camera sequence (Camera Path, Camera from Points; Outdoor): every camera is rendered and the outputs are batches of frames, ready for a video or animated image node. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `image` | IMAGE | The rendered preview as an IMAGE. |
| `depth` | IMAGE | Outdoor look: the frame's inverse depth (near white, far ground and sky black), scaled between the 5th and 99.5th percentile of the distances and square-rooted so that distant ridges keep some grey: the convention depth ControlNets read. Other looks give a black image. |
| `normal` | IMAGE | Outdoor look: the frame's normals in camera space (R = right, G = up, B = toward the camera, mapped to 0..1; the sky is flat, facing the camera), for normal ControlNets. Other looks give a flat (0.5, 0.5, 1) image. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Resolution `width` `height` | int [64..4096] | 512, 512 | Image width and height in pixels (Width, Height). |
| Elevation `elevation` | float [-89..89] | 25 | Camera elevation angle in degrees. 0 looks horizontally, positive looks from above. |
| Azimuth `azimuth` | float [-360..360] | 35 | Rotation of the camera around the vertical axis in degrees. |
| Look `look` | menu | Basic | Basic: fast flat shading. Studio: an object on a studio floor (orthographic, shadows, AO, textures). Outdoor: an environment shot with a perspective camera, sky, sun, haze and an optional ground plane. Options: Basic (`basic`), Studio (shadows, AO, ground, textures) (`studio`), Outdoor (perspective, sky, sun, haze) (`outdoor`). |
| Shading `shading` | menu | Normal | How the surface is coloured. Normal shows face normals as colour, Lambert is a grey model with simple lighting, Color shows the colour attribute times lighting. Options: Normal (`normal`), Lambert (Gray) (`lambert`), Color (Cd) (`color`). *Hidden when look ≠ basic.* |
| Color Attribute `color_attrib` | string | `Cd` | Attribute read for the colour. Only used in Color shading. *Hidden when shading ≠ color look = basic.* |
| Supersampling `supersampling` | int [1..4] | 2 | Studio: renders this many times larger and averages down, for smooth edges (2 is a good default; 3–4 are slower). *Hidden when look = basic.* |
| Textures `textures` | string | *(empty)* | Studio: one `slot = path` per line. Slots: `basecolor`, `normal` (tangent space, OpenGL +Y), `orm` (R = AO, G = roughness, B = metallic, as Export Mesh packs it), or `ao` / `roughness` / `metallic` on their own. `orm`, `roughness` or `metallic` switch the surface to PBR shading. `{material}` in a path is replaced by the face's material name; `@layer` (or `@ao roughness metallic`) reads the COP image on textures_cop. Detail maps: `detail1`..`detail4` (tiled colour, 0.5 = no change, multiplying the base colour by 2 x detail), `detail_normal1`..`detail_normal4`, `detail_weights` (a layer on the mesh uv whose channels say how much of each detail applies) and `detail_tiling` (how many times the detail repeats across the uv range) sharpen close views of a large terrain; far away their mips average out and they fade. `detail_triplanar` = a size in world units projects the detail from the three axes instead (one tile per that size, blended by the normal), so cliffs keep its shape instead of streaking down the slope. Terrain layers, as an engine's landscape material: `layer1`, `layer2` ... are full-colour tiled maps (on detail_cop), each with optional `layerN_normal`, `layerN_rough`, `layerN_height` (0..1) and `layerN_size` (metres per tile), projected in world space from the three axes; `layer_weights = @w0 @w1 ...` names the masks (their channels, in order, weigh layer1, layer2 ...; four per RGBA splat map), `layer_blend` blends by height, `layer_antitile` mixes in a larger, turned second sample so the repeat does not line up, and `layer_macro` multiplies the layered colour. Where the weights sum below 1 the base colour shows. `alpha = path` (or `@layer`) cuts the surface away where the texture's first channel is below `alpha_cutoff` (default 0.5): leaves, fences, impostor cards; cut-out faces cast no shadow, unless `alpha_shadow` names their material (wildcards, several allowed: `alpha_shadow = M_Leaf M_Needle`), when they cast it as whole faces (a tree's leaf cards shading the ground and each other). A `@layer` is looked up in textures_cop, then splat_cop, then detail_cop. `basecolor_tint = 1` multiplies the base colour texture by the colour attribute (or, instead of 1, material wildcards such as `imp_*` limit it to those materials): one atlas, a tint per instance. `uv_blend = uv uv2 uv3 uv4` with `uv_blend_weights = fw` reads the base colour and the alpha at each of those uvs and sums them by the weights (one per uv, a point or vertex attribute): an impostor card blends the atlas frames round its view direction; where the weights are 0, or the geometry has no weights attribute, the plain uv is read. *Hidden when look = basic.* |
| Material Attribute `material_attrib` | string | `material` | Studio: string prim attribute holding each face's material name (used for `{material}` in Textures). *Hidden when look = basic.* |
| UV Attribute `uv_attrib` | string | `uv` | Studio: uv attribute (vertex or point) used to look up the textures; uv repeats outside 0..1. *Hidden when look = basic.* |

*Outdoor*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Sun Elevation `sun_elevation` | float [-10.0..90.0] | 35 | Outdoor: the sun's height above the horizon in degrees; low sun gives long shadows and warmer light. From -10: a sun just below the horizon gives twilight (no direct sun, a dim warm sky), for a dusk shot with lights. *Hidden when look ≠ outdoor.* |
| Sun Azimuth `sun_azimuth` | float [-360.0..360.0] | 135 | Outdoor: the sun's direction in world space (0 = toward +Z, 90 = toward +X), so the light stays put when the camera moves. *Hidden when look ≠ outdoor.* |
| Haze `haze` | float [0.0..20.0] | 1 | Outdoor: aerial perspective in metres. At 1, light from a surface falls to 1/e over 12 km (3 gives 4 km: a hazy day); the haze glows toward the sun. 0 turns it off. *Hidden when look ≠ outdoor.* |
| Clouds `clouds` | float [0.0..1.0] | 0 | Outdoor: cumulus cover from 0 (clear) to 1 (overcast). The clouds are drawn in the sky and throw soft shadows on the scene. *Hidden when look ≠ outdoor.* |
| Cloud Seed `cloud_seed` | int [0..] | 0 | Outdoor: seed of the cloud pattern. *Hidden when look ≠ outdoor } { clouds = 0.* |
| Sky Samples `sky_samples` | int [0..128] | 32 | Outdoor: number of directions the sky light is sampled and shadowed from, one depth map each. More is smoother and slower; 0 uses a plain hemisphere fill without sky shadows. *Hidden when look ≠ outdoor.* |
| Ground Plane `ground_plane` | toggle | on | Outdoor: add a ground plane to the horizon at the bottom of the geometry, so a block of buildings sits in a landscape. *Hidden when look ≠ outdoor.* |
| Ground Color `ground_color` | string | `0.32 0.31 0.27` | Outdoor: colour of the ground plane, three numbers 0..1. *Hidden when look ≠ outdoor } { ground_plane is off.* |
| Exposure `exposure` | float [0.05..8.0] | 1 | Outdoor: brightness multiplier before the tone curve. *Hidden when look ≠ outdoor.* |
| Compute `compute` | menu | Auto (CUDA if available) | Outdoor: where the frame is rasterized and textured (the texture lookups, the bulk of a terrain's render) and the shadow maps and the sky light are computed. Auto uses CUDA when available, otherwise numpy; the result differs only at float32 rounding level. Options: Auto (CUDA if available) (`auto`), CPU (numpy) (`cpu`), CUDA (`cuda`). *Hidden when look ≠ outdoor.* |

*Weather*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Snow Line `snow_line` | float | 150 | Outdoor: height in metres above which upward-facing surfaces take snow (with Snow above 0). The line is ragged (two scales of noise) and fades over 25 m. *Hidden when look ≠ outdoor.* |
| Snow `snow_amount` | float [0.0..1.0] | 0 | Outdoor: how much snow lies above the snow line, 0 (none, the default) to 1. Only faces turned up (the normal's height above about 0.45) take it. The snow and the wetness read the slope at the scale of a mountainside: the mesh normal blurred over about 1/80 of the frame, weighted 3:1 over the normal-mapped one, so gullies and normal-map ripples do not stripe them. *Hidden when look ≠ outdoor.* |
| Wetness `wetness` | float [0.0..1.0] | 0 | Outdoor: wet ground, 0 to 1: upward faces darker and much glossier (they reflect the sky), puddles on the flattest. Switches to PBR shading. *Hidden when look ≠ outdoor.* |

*Lights*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Emit Attribute `emit_attrib` | string | `emit` | Outdoor: a colour attribute added as emitted light (linear, before exposure): lit windows, lamp heads. Empty reads none. *Hidden when look ≠ outdoor.* |
| Light Range `light_range` | float [0.1..] | 40 | Outdoor: how far the point lights on the lights input reach, in metres. *Hidden when look ≠ outdoor.* |

*Weather*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Weather Attribute `weather_attrib` | string | `weather` | Outdoor: a float attribute 0..1 that scales the snow and the wetness per surface, so grass blades (whose normals point up like the ground's) can stay dry: 0 keeps a surface as it is. Where the attribute is absent the weather applies in full. *Hidden when look ≠ outdoor.* |

---

### Geometry Spreadsheet (PCG)

<a id="pcg-geospreadsheet"></a>

`PCG_GeoSpreadsheet` · category `PCG/output`

Shows geometry attributes in a table inside the node, like Houdini's Geometry Spreadsheet.

Displays the point, vertex, primitive and detail attributes of the input in tables in the node body, together with the element counts and bounding box. It also outputs a short text summary of the geometry, which can be connected to other nodes. It is an output node, so it runs without anything downstream.

The tables are limited to Max Rows rows starting at Start Row; string and numeric columns are both shown, and non-finite numbers are shown as empty. Group names of each class are listed too.

When a class has more rows than Max Rows, the footer shows page buttons (first, previous, next, last) and a row field to jump to. Pages are fetched from the server's cache of the last run, so paging never re-runs the graph and does not change the Start Row widget.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to inspect. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `info` | STRING | A short plain-text summary of the geometry. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Max Rows `max_rows` | int [1..2000] | 64 | Maximum number of rows shown per attribute class. |
| Start Row `start_row` | int [0..] | 0 | Index of the first row shown, for paging through large geometry. |

**Compared with Houdini**

Counterpart of the Geometry Spreadsheet pane. It is read-only and lives in the node body rather than a separate pane.

---

### Viewport (PCG)

<a id="pcg-viewport"></a>

`PCG_Viewport` · category `PCG/output`

Shows geometry in an interactive 3D viewport embedded in the node body and passes the geometry through.

Every time the node cooks, the geometry is stored in a cache and the front end fetches it to rebuild the view, using a three.js canvas inside the node. Shading and display options are front-end only widgets, so changing them does not re-cook the chain.

The `geo` output passes the input through unchanged, so Viewport can sit in the middle of a chain like a display flag. Pin several Viewports to compare branches side by side. Use Display (PCG) instead for a single viewer in the persistent panel that follows the display flag.

**Selection**: press **S** with the pointer over the viewport to enter select mode (a toolbar appears at the top; Esc leaves it). Click picks the nearest point or the primitive under the cursor, dragging draws a selection box; Shift adds and Ctrl removes. Visible Only skips what the surface hides. The selection is shown as a group expression such as `0-4 7 12-19`, which any group field accepts: Copy puts it on the clipboard, and → group creates a Group Create node wired to the node feeding the viewport, with the expression as its base pattern. Numbers refer to the geometry the viewport shows.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to show. |
| `template` *(optional)* | GEOMETRY | Optional reference geometry drawn as a grey wireframe, like a Houdini template flag. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The input geometry, unchanged. |

**Compared with Houdini**

The template display is an input link instead of a node flag, so the dependency is visible on the canvas.

---

### World Manifest (PCG)

<a id="pcg-worldmanifest"></a>

`PCG_WorldManifest` · category `PCG/output`

Writes World.json, one file describing an exported world, plus one manifest per streaming tile.

An engine import should not have to know how a world's files are named. This node reads back everything the export nodes wrote under **Folder** and writes `World.json` beside them, with one `tiles/Tile_x{i}_y{j}.json` per tile, so an import script reads a single file.

What it recognises, by content rather than by name:

- **Image sets**: every sidecar JSON of COP Write File (height, colour, normal, splat maps, layer textures ...) with its channels, bit depth, decode rule, size and files. A set tiled on the same grid as the world lists its file in each tile. The height map (the set in the `height` folder) also becomes the `terrain` section: range in metres, samples, metres per sample, shared edges.
- **Instance tables**: Export Instances' index and its CSVs. Every row is counted per asset and per tile.
- **Meshes**: every glb with its nodes, meshes, materials, triangle counts and bounds (POSITION min / max with the node's translation and scale; a GPU-instanced node lists its instance count). A `.lods.json` beside it (Export Mesh's LOD Manifest) adds each asset's LOD nodes and switch distances, and LOD assets are placed in the tile of their bounds' centre. Other meshes with bounds (water, say) are listed in every tile they overlap. The `assets` folder is treated as a library and not placed.
- **Polylines**: OBJ `l` records (roads), with their count, length and bounds; each tile gets the length of each set inside it.
- Everything else is listed under `files`.

The role of a file is its first folder under Folder (height, texture, instances, buildings, roads, water, assets ...). `coordinates` states the convention: metres, +Y up, x east and z south, where (0, 0) lies (**Origin**), the tile grid (**Tile Size**; tile (i, j) covers x from i × tile), the image orientation (row 0 at the tile's smallest z) and how Unreal and Unity map the axes. A tile's `bounds` joins the terrain's decoded height range over its extent with the instances, buildings and roads in it.

The manifest only sees files that exist when it runs: link the exports' outputs (Export Mesh's path, Export Instances' and COP Write File's reports) to the `after` inputs, and they run first. The inputs take any type, so the image of a render that comes last can be linked too: ComfyUI runs an export as soon as its input is ready, so everything that render read has been written by then. **Extra JSON** (an object) adds keys of your own, such as road classes with their widths and materials; it cannot replace format, version, coordinates or tiles.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `after1` *(optional)* | * | Optional, any type: an export's path or report, or a render's image. Only used to make those nodes (and everything they read) run before the manifest; likewise after2 to after8. |
| `after2` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |
| `after3` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |
| `after4` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |
| `after5` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |
| `after6` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |
| `after7` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |
| `after8` *(optional)* | * | Optional, any type: like after1, another output that must run before the manifest. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `path` | STRING | World.json's path, relative to the output folder. |
| `report` | STRING | JSON counts: tiles, image sets, meshes, polylines, instances, other files. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Folder `folder` | string | `pcg/world` | The world's folder under ComfyUI's output folder. |
| World Size `world_size` | float [1.0..] | 4096 | Edge of the square world in metres. |
| Tile Size `tile_size` | float [1.0..] | 1024 | Edge of a streaming tile in metres, the grid of the _x{i}_y{j} files. |
| Origin `origin` | menu | North-West Corner | Where (0, 0) lies: the north-west corner (the world spans 0 to World Size) or the centre (minus half to plus half). Options: North-West Corner (`north_west_corner`), Center (`center`). |
| Extra JSON `extra_json` | string | *(empty)* | A JSON object whose keys are added to World.json (for example road classes). Empty adds nothing. |

**Compared with Houdini**

No Houdini node; in a Houdini pipeline this is the job of a PDG / Python step after the ROPs, collecting their outputs into a level description.

---
