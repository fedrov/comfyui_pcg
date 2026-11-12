# Output & Export

Writing files and exporting to other applications.

8 nodes.

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

The **Outdoor** look renders an environment shot instead of an object on a studio floor: a perspective camera (the connected Camera node, or an automatic 35 mm camera at Elevation / Azimuth), a sky with a sun, warm sun light with shadows plus blue sky fill and ground bounce, aerial perspective that fades distant surfaces toward the horizon, and an optional ground plane to the horizon. Textures and PBR work as in the studio look; glossy surfaces reflect the sky. Use it for streets, towns and terrain where scale and depth matter; keep Studio for asset turnarounds.

The outdoor look lights the scene like a photograph: the sky is an area light with shadows and one bounce of light off the scene, so narrow streets are darker than open squares and shadowed walls pick up warm light from sunlit ground; sun shadows are crisp at contact and soften with distance; the sky's colours follow the sun's elevation; the frame is finished with bloom, a slight vignette and the AgX tone curve.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to render. |
| `textures_cop` *(optional)* | COPIMAGE | Optional COP image whose layers Textures can name with `@layer` (Studio look). |
| `camera` *(optional)* | PCGCAM | Optional camera for the Outdoor look (any Camera node; its view is rendered in perspective). Without it an automatic 35 mm camera at Elevation / Azimuth frames the geometry. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `image` | IMAGE | The rendered preview as an IMAGE. |

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
| Textures `textures` | string | *(empty)* | Studio: one `slot = path` per line. Slots: `basecolor`, `normal` (tangent space, OpenGL +Y), `orm` (R = AO, G = roughness, B = metallic, as Export Mesh packs it), or `ao` / `roughness` / `metallic` on their own. `orm`, `roughness` or `metallic` switch the surface to PBR shading. `{material}` in a path is replaced by the face's material name; `@layer` (or `@ao roughness metallic`) reads the COP image on textures_cop. *Hidden when look = basic.* |
| Material Attribute `material_attrib` | string | `material` | Studio: string prim attribute holding each face's material name (used for `{material}` in Textures). *Hidden when look = basic.* |
| UV Attribute `uv_attrib` | string | `uv` | Studio: uv attribute (vertex or point) used to look up the textures; uv repeats outside 0..1. *Hidden when look = basic.* |

*Outdoor*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Sun Elevation `sun_elevation` | float [1.0..90.0] | 35 | Outdoor: the sun's height above the horizon in degrees; low sun gives long shadows and warmer light. *Hidden when look ≠ outdoor.* |
| Sun Azimuth `sun_azimuth` | float [-360.0..360.0] | 135 | Outdoor: the sun's direction in world space (0 = toward +Z, 90 = toward +X), so the light stays put when the camera moves. *Hidden when look ≠ outdoor.* |
| Haze `haze` | float [0.0..20.0] | 1 | Outdoor: aerial perspective, how fast distant surfaces fade toward the horizon colour; 0 turns it off. *Hidden when look ≠ outdoor.* |
| Clouds `clouds` | float [0.0..1.0] | 0 | Outdoor: cumulus cover from 0 (clear) to 1 (overcast). The clouds are drawn in the sky and throw soft shadows on the scene. *Hidden when look ≠ outdoor.* |
| Cloud Seed `cloud_seed` | int [0..] | 0 | Outdoor: seed of the cloud pattern. *Hidden when look ≠ outdoor } { clouds = 0.* |
| Sky Samples `sky_samples` | int [0..128] | 32 | Outdoor: number of directions the sky light is sampled and shadowed from, one depth map each. More is smoother and slower; 0 uses a plain hemisphere fill without sky shadows. *Hidden when look ≠ outdoor.* |
| Ground Plane `ground_plane` | toggle | on | Outdoor: add a ground plane to the horizon at the bottom of the geometry, so a block of buildings sits in a landscape. *Hidden when look ≠ outdoor.* |
| Ground Color `ground_color` | string | `0.32 0.31 0.27` | Outdoor: colour of the ground plane, three numbers 0..1. *Hidden when look ≠ outdoor } { ground_plane is off.* |
| Exposure `exposure` | float [0.05..8.0] | 1 | Outdoor: brightness multiplier before the tone curve. *Hidden when look ≠ outdoor.* |
| Compute `compute` | menu | Auto (CUDA if available) | Outdoor: where the shadow maps and the sky light are computed. Auto uses CUDA when available, otherwise numpy; the result differs only at float32 rounding level. Options: Auto (CUDA if available) (`auto`), CPU (numpy) (`cpu`), CUDA (`cuda`). *Hidden when look ≠ outdoor.* |

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
