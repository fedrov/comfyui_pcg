# c8_geo_layer_seq (pcg100): geometry ↔ layer, sequence batch

Tests: `test_audit_c8_geo_layer_seq.py`. "Bit-for-bit identical to before the change at default values" uses the hard-coded digests GOLDEN (the same set of calls on the pre-change commit
f210100, rounded to 5 decimals before sha1; recomputed with `--digests`), independent of git.

---

## Layer to Points → PCG_COPLayerToPoints (parameters appended, default = old behaviour)

Docs re-checked (WebFetch layertopoints). The docs only have parameter names and a one-sentence description each, no defaults and nothing about where the points are placed.

Done:
- Houdini's five Method modes appended to the end of the `mode` dropdown: `nonzero` (Non-Zero Pixels), `count_per_pixel`,
  `unique_values`, `count_first`, `count_last`. **All Pixel doesn't get its own mode**: it is just the old `pixels`
  mode with no mask connected and Stride 1 (the panel label is still "One Point per Pixel"). The panel label was changed to Houdini's "Method".
- These five modes use `mask_layer` as the source layer (Houdini has only one layer input; our images are multi-layer); empty = C (`getn`'s
  default layer). No separate layer parameter was added, to avoid having to fill in both that and Mask Layer.
- Appended `layer_attrib` / `index_attrib` (empty = not written; integer point attributes), `set_positions` (default on),
  `ignore_minus_one` (default on, only read by unique_values). Layer Attrib / Index Attrib / Set Positions
  also apply to the old pixels / scatter modes.

Not made clear by the docs, decided here:
- Multi-channel layers: the "value" is channel 0; only Non-Zero looks at all channels (any non-zero channel counts as non-zero).
- Count per Pixel / Count from: point count = floor(value); negatives / NaN count as 0.
- Unique Values: values are compared exactly as floats; the point is placed on the pixel where the value **first appears**, and points are ordered by ascending buffer offset.
- Point order is always ascending buffer offset x + y·xres; our row 0 is the bottom, the same direction as Houdini's buffer.
- Count from First / Last Pixel: these points have no corresponding pixel position, so P is always the origin (unaffected by Set Positions /
  Jitter), and uv / Index Attrib / sampled attributes all come from that source pixel.
- Layer Attrib writes rint(channel 0).
- Positions use the old node's plane + world mapping (pixel centers); Jitter also applies to the Houdini modes except Count from;
  multiple points from the same pixel in Count per Pixel take their random numbers by point number, otherwise they would all stack up.
- Set Positions off: P is all 0 and Height Layer isn't read either; uv is still written.

Still different from Houdini / not done:
- **The Point Attributes multiparm table not done** (Name / Class / Type / Tuple Size): Houdini uses it to pre-create empty attributes for downstream
  OpenCL nodes; we have no OpenCL nodes, so the table means little; if done, it would be "create a few all-zero attributes".
- The old extension parameters (plane, world_size, jitter, seed, height, density, stride, the scatter mode) are kept.

Side finding: `attribs` defaults to "C", and it raises an error right away when the source image has no C layer (old behaviour, not changed). When using the Houdini modes on
ID layers (usually only one layer) you have to clear Layers to Attributes by hand. Suggest the coordinator consider "skip missing layers", but that would change the old
error behaviour, so I didn't touch it.

Mutation: 18, 3 survived the first round, all killed after targeted tests -- uv being jittered in the Count from modes (only P had been tested), u/v using
the same random number, multi-channel layers taking the last channel as the value.

---

## [C] Point Generate → new node PCG_COPPointGenerate

Docs re-checked (WebFetch pointgenerate). Houdini's is "add points to a point cloud" (geometry in, geometry out), not the same thing as Layer to Points'
"points from a layer", so per [C] a new node was added (nodes_cop2.py, implemented in the new file `geo/cop/geolayer.py`);
that copernicus_map row points to it. Icon `gl_ptgen`, panel spec in g7.

Done: Method (Parameters / Point Attribute / Detail Attribute), Number of Points, Points per Second,
Seed (`rand_seed`), Count Attribute, Copy Attributes (Houdini name patterns, supporting `*` and `^exclude`),
Append Points; inputs points (optional) and ref (optional); id / nextid / idstep continue the numbering.

Not made clear by the docs, decided here:
- The docs don't say how Number of Points and Points per Second relate (on the page, the hierarchy of the two and Method is unclear); defined as
  **added**: count = Number + PPS × Time Step. Whether the fractional part is kept is decided by a random number from Seed (the docs' wording).
- Houdini uses the simulation's current time step; we have no simulation, so **Time Step is a parameter** (extension, default 1/24).
- The docs give no defaults: Number of Points 10, Count Attribute "count", Copy Attributes "*", Append on.
- The docs don't give the new points' positions: without P copied it is the default value (origin). The Parameters / Detail modes have no source points, so they are always at the origin.
- Point Attribute / Detail Attribute counts take floor, negatives count as 0; in the Detail mode the fractional part is **not** randomly kept.
- Source = ref (if connected), otherwise points. New points carry all of points' point attribute definitions (values 0), and with Append off they also carry points'
  detail attributes. Point groups are kept; the new points are not in the groups.
- id numbering: start = detail nextid (if present), otherwise max(id)+1; step = detail idstep (if present), otherwise 1; when nextid exists it is
  updated to the next available value (the docs don't say to update it).

Not done: the third input `count` (in Houdini a separate geometry can be connected as the source of the count attribute) -- ref achieves the same thing.

Mutation: 14, 4 survived: point group preservation, Detail floor, detail attributes with Append off -- killed after adding tests;
the condition in `merge(base, new) if n else base` was redundant (merge drops empty geometry itself), so the condition was removed.

---

## [C] Layer from Attribute → new node PCG_COPLayerFromAttrib

Docs re-checked (WebFetch layerfromattrib). The old target, Texture Render, is "render a textured mesh through a camera",
not the same thing as "fill pixels element by element from an attribute array". A new node was added; that copernicus_map row points to it (status done → new).
Texture Render is untouched (in sop_map it still corresponds to UV Quick Shade).

Done: Data Ordering (Bottom Left / Top Left), Resize Layer, Resize Shape (Power of 2 Square / Square /
Single Row / Single Column), the size_ref input, the index input (+ `index_layer` to choose the layer).

Different from Houdini / decided here:
- Copernicus' attrib input is a "detached attribute" (a standalone attribute array); we have no such type, so it became **geometry +
  attribute name + Class** (Point / Primitive / Vertex / Detail). A Detail attribute counts as 1 element (components are channels).
- Signature not done: output layer channel count = attribute component count; string attributes raise an error.
- Not in the docs: when there are more pixels than elements, the extra pixels are filled with 0; when there are more elements than pixels, the extras are dropped; index takes rint, out of range (including negative) fills 0;
  index's resolution must match the output (otherwise an error).
- With Resize Layer off and no size_ref connected, resolution_x/y is used (the docs don't give Houdini's size without size_ref).
  With Resize on, the output is a new image with only this layer (its size differs from size_ref, so size_ref's layers can't be carried along).
- With 0 elements, Resize gives 1×1.

Mutation: 13 + 4. 4 survived: the string check (numpy's conversion to float also throws ValueError on its own -- the test was changed to match our
error text), index rint vs floor (added the value 1.6), the two floating-point correction loops in the Square size (equivalent for realistic n --
changed to `math.isqrt(n − 1) + 1`, removing the loops; both mutations of the new code are killed).

---

## [C] Geometry to Layer → new node PCG_COPGeoToLayer

Docs re-checked (WebFetch geotolayer-2.0). The old target, Render Pass, is camera rasterization (depth / normal / shading passes),
not "volume prim → layer". A new node was added; that copernicus_map row points to it (done → new); Render Pass is still referenced by the
"Rasterize Geometry" row.

Done (only for our **dense volume** prims, = Houdini's volume):
- Slice (XY / YZ / ZX Plane): a 3D volume is sliced on the plane where the normal coordinate = `slice_offset`, interpolating linearly along the normal between the two adjacent voxel
  layers; one voxel per pixel.
- Outputs: Houdini has a multiparm table + multiple outputs; we have **one** output (a multi-layer COP); the `outputs` string lists, space-separated,
  prim names / indices (may be negative) / wildcards (the volumes matched by `vel.*` are sorted by name and combined into one multi-channel layer, with `.*` removed from the layer name,
  corresponding to the vel.* + RGB usage in the docs). Empty = one layer per volume (equivalent to the Set Imports from Geometry button).
- Type (Auto / ID / Mono / UV / RGB / RGBA): truncated or padded with 0 to the corresponding channel count, ID takes rint. In Houdini the type is attached to each
  output; we have one Type for all of them (Auto = as many channels as volumes matched).
- Optional + Default Value + the size_ref input: when nothing is found, fill the default value at size_ref's resolution (with Type's channel count).

Not made clear by the docs, decided here:
- Which slice of a 3D volume: the docs only say "like the Volume Slice SOP". Volume Slice has Plane Offset, so `slice_offset` was added here
  (extension, default 0 = through the world origin). When the plane falls outside the volume the whole slice is 0 (Houdini volumes default to a constant 0 border).
- "ZX Plane" taken literally: horizontal axis Z, vertical axis X; YZ: horizontal Y, vertical Z; XY: horizontal X, vertical Y. row 0 = the side with the smallest coordinate.
- Unnamed prims: layer name output + (prim index + 1) (the docs' wording "incremented by 1 when that number is 0" is hard to
  parse; interpreted as "numbered from 1").

Different from Houdini / not done:
- **All layers in one image have the same resolution** (a constraint of our CopImage): if several volume slices have different resolutions it raises an error, telling the user to convert them with two nodes.
- No VDB (Densify VDBs and the vdb_ref input skipped), no camera prims, no Precision / Border (our layers are
  float32 with no border metadata). Prim attributes aren't imported as layer attributes (our layers have no metadata).
- No layer world transform: the slice is only voxel values, with no information about "where this image is in the world".

Mutation: 16 + 2. 2 survived (the errors for "can't combine into one layer" / "different resolutions" were preempted by numpy's own errors) -- killed after changing the tests to match our
error text.

**Changed an existing test**: added PCG_COPGeoToLayer to test_nodes.py's EXPECT_REFUSE (with default parameters the test geometry is a grid
with no volume prims, so refusing is correct; the error text follows the Volume nodes' entries).

---

## [C] Sequence → new node PCG_COPSequenceClips

Docs re-checked (WebFetch sequence). The page has only three parameters (Start Frame / Length in Frames / Output Start
Frame, in the Clips multiparm table), no defaults, and doesn't describe the inputs and outputs. The old target, Sequence Import, is IMAGE → sequence,
not the same thing. A new node was added; that copernicus_map row points to it. Sequence Import is untouched.

Done: Clips (a text version of the multiparm table: `start_frame frame_count`, separated by semicolons or newlines), Output Start Frame, up to 4 sequence inputs
(seq required, seq2–4 optional; unconnected ones in between are skipped). Clip k is taken from input k; when there are more clips than inputs, the extra clips all come from **the last
input** (the docs say "taken from the last clip", read as "the last input" -- the sentence "with only one input all clips are taken from it"
is consistent with this reading). Empty Clips = the first input unchanged.

Decided here:
- Frame number = sequence index (from 0, consistent with Sequence Pick). Our sequences have no "frame number" metadata.
- Out-of-range frames in a clip are extended with the first / last frame (hold); no error.
- Output Start Frame = S: our sequences always start at frame 0 and can't "leave the start empty": for S > 0 the first S frames repeat the first frame,
  for S < 0 the first −S frames are dropped (dropping everything raises an error).
- Overlapping clips / gaps between clips: not in the docs; ours are **concatenated end to end** (each clip's output position is determined by the lengths of the preceding clips), so there are no overlaps or
  gaps. Whether each clip in Houdini has its own output start frame is uncertain; the docs only give one Output Start Frame.

## [C] Time Pack → new node PCG_COPTimePack

Docs re-checked (WebFetch timepack). The old target, Sequence Import, is not the same thing. A new node was added; copernicus_map
points to it.

Done: Mode (Relative / Absolute), Range (start / end), Step, Frames / Seconds (`units`), Add Time As
(Prefix / Suffix). The input is our sequence; the output is a multi-layer image (Houdini outputs a cable; our COPIMAGE is multi-layer itself).

Different from Houdini / decided here:
- Houdini "cooks the upstream at different times"; our images have no time, so the input became a sequence and time = sequence index. Relative's
  "current frame" is the parameter `frame` (Houdini uses the scene's current frame), and Seconds is converted with the `fps` parameter (Houdini uses the scene frame rate).
- Samples = start, start + step, …, ≤ end (tolerance 1e−9); times between two frames are linearly interpolated between them (as Time Blend
  does; not in the docs); out-of-range frames are extended with the first / last frame.
- Layer names: Prefix → `<k>_<layer>`, Suffix → `<layer>_<k>`, where k is the sample number counting from 0 (the docs only say "adds the sample number"; the format is our
  choice). Default Suffix (the docs give no default). `layers` chooses which layers to pack (extension, empty = all).
- Method only has By Frame (the docs list only this one), so it isn't a parameter. Sample count capped at 4096 (guards against typos).

Mutation (both nodes together): 14, all killed.

---

## Bake Geometry Textures / Bake Geometry Textures 2.0 → PCG_COPBakeTextures (parameters appended, default = old behaviour)

Docs re-checked (WebFetch bakegeometrytextures-2.0; 1.0's parameters are a subset of 2.0's, not fetched separately). Both audit items point to the same
node and were done together. The old node is a generic attribute baker, "rasterize by the low-res mesh's uv + search the high-res mesh along ±N"; Houdini's core is a set of built-in maps.
Everything that could be added as "appended parameters, default off" was appended to the end of INPUT_TYPES, and new layers are only output when the corresponding toggle is on. The panel was changed to Houdini's
two pages: Tracer / Texture Maps. New optional input `cage`.

Done:
- **Tracing Mode**: Surface Normal (= old behaviour) / Cage Mesh (cage has the same point numbers and topology as the low-res mesh; for each texel, the point on the cage in the same triangle with
  the same barycentric coordinates shoots a one-way ray **toward that point on the low-res mesh**; displacement is the projection of hit point minus low-res point onto N) / Single Mesh (low)
  (no primary rays, no normal_ts / displacement; AO traces against the low-res mesh itself).
- **Face Culling** (primary rays) / **Visibility Culling** (AO's secondary rays): No Culling / Back Faces / Front Faces.
  For this `spatial.ray_cast` got a `cull` parameter (default 0 = unchanged; culled hits don't block, the ray goes on to find the next one).
  "Back face" = the triangle normal points in the same direction as the ray's **actual direction of travel** (for hits with t < 0 the direction of travel is −D).
- **Ray Bias** (under Surface Normal the origin moves along N; displacement is still measured from the low-res surface).
- **Normal Space** (Signed / Offset) applied to normal_ts.
- **World Normal** (the `worldnormal` layer, the interpolated normal of the high-res mesh at the hit point; on a miss / without a high-res mesh the low-res N is used) + World Normal Space.
- **Position** (the `position` layer, world position of the hit point) + Position Space (Absolute / Relative) + Bounding Box
  (Fit: each axis of the low-res bounding box normalized separately to 0~1; Uniform: by the longest side, bounding-box center at 0.5, no stretching).
- **Ambient Occlusion** (the `occlusion` layer, 1 = unoccluded) + Occlusion Samples + Max Distance (0 = unlimited) + Sample
  Multiplier. Cosine-weighted hemisphere (Malley), random numbers hashed by (texel, sample number), reproducible. Starts from the hit point (high-res) and traces against the high-res mesh;
  with Single Mesh / no high-res mesh connected it starts from and traces against the low-res mesh.
- **Height** (the `height` layer) + Height Space (True Displacement / Custom: Inner → 0, Outer → 1, linear, unclamped).
- **Alpha** (the `alpha` layer = low-res uv coverage) + Mask Out High Resolution Mesh (only texels whose primary ray hit the high-res mesh are 1).

Not made clear by the docs, decided here:
- The AO origin is offset along the normal by 1e−4 × the target geometry's bounding-box diagonal (avoids self-intersection); "bright = 1".
- The docs don't give how the Uniform Box is aligned (center at 0.5).
- Inner / Outer Distance default to −0.1 / 0.1 (the docs give no defaults).
- New layers go through Dilate (= Edge Padding) like the old ones.

**Not done** (listed in the audit):
- Curvature, Edge, Cavity, Thickness, Rounded Edge Normal: the docs only have notes like "more samples reduce noise / radius / threshold",
  without defining how the outputs are normalized (e.g. is Thickness a distance or a transmittance, where Curvature Scale is applied); anything built would "look right" without being right.
- Cage attributes (Ray Start / Ray Direction / Ray Length), If Ray Length Missing / Custom Ray Length: the old
  Max Ray Distance does the same job (0 = infinite). Auto Generate Cage / Cage Offset / Soften Cage (from 1.0).
- Match Pieces by Name, UDIM Override, Remove UV Z, the missing Normals / Tangents policy (we always fill them silently;
  tangents use corner_frames -- consistent with Export Mesh, not guaranteed bit-for-bit identical to MikkT), Normal Y Direction, World Space
  handedness / up axis, Exclude Alpha from UV Fill, Exterior (Unchanged / Black / Diffuse Fill: beyond our padding it
  is 0, equivalent to Black), Edge Offset, the Type of custom attributes (the old attribs / high_attribs output layers with the attribute's own component count),
  Tracer (CPU / OptiX), the skew input.

**Still different from Houdini / problems found (not changed; for the coordinator to decide)**:
- `spatial.ray_cast(both=True)` picks the hit with the **smallest (most negative) t**, not the smallest |t| -- the function's docstring says "the nearest
  surface, on either side". So with Trace Both Sides on and high-res faces **below** the low-res mesh, it always takes the farthest layer below, even if there is
  a layer right above. Houdini's Surface Normal presumably takes the nearest. This function has 10 call sites and changing it would affect other nodes, so I didn't touch it;
  the Ray Bias test therefore uses both_sides off.
- Height's True Displacement uses displacement directly (the signed distance along N).

Mutation: 29 + 4. 4 survived the first round, all killed after targeted tests: ray_cast's chunked path (> 260k rays) didn't pass cull down
(added a direct test with 260k rays), Cage mode wrongly using two-way rays (added a scene "with another layer behind the cage"), custom Height outside the uv
coverage being (0 − inner)/span instead of 0 (added a low-res mesh whose uv covers only a quarter), menu value validation (added an error test).

Regressions: changed `spatial.ray_cast` (added cull; the default 0 doesn't take the new code); ran test_cop_geoimg / test_exporters /
test_render_clip / test_sop_shrinkwrap / test_core / test_geoops / test_sop_sample / test_houdini_fixes, all green.
Bake's "bit-for-bit identical at default values" is in GOLDEN (3 calls: low-res only + attribs, with high-res + high_attribs + dilate,
max_distance + one-way).

---

## [C] Integrate Volume → new node PCG_COPIntegrateVolume

Docs re-checked (WebFetch integratevolume). The old target, Prefix Sum, is a 2D prefix sum, not the same thing. Houdini consumes VDBs;
we have no VDB, but we have **dense volume** prims, and integrating along a view ray is the same thing on a dense volume, so it was done (rather than skipped as OOS_VDB).
A new node was added; copernicus_map points to it. It was added to test_nodes.py's EXPECT_REFUSE (the default test geometry has no volume).

Done: Operation (Integral / Transmittance / Minimum / Maximum), Density Scale / Min / Max, Ramp Mode
(No Ramp / Clamped / Periodic), Integration Step Size, Max Step Count, Transmittance Cutoff, Sample Jitter
Scale, Stratification Jitter Scale, Seed (`rand_seed`, ours), vieworigin / viewdir / mindepth /
maxdepth (separate inputs in Houdini; for us one optional COP input `layers` + four layer names), multiple volumes = multiple channels (Vector VDBs
correspond to name wildcards like vel.*, each channel accumulated separately).

Not made clear by the docs, decided here:
- Default orthographic projection: the pixel center's image coordinates (long side −1~1, consistent with c6's convention) as (x, y), along +Z. The docs don't say where the ray starts,
  so the **whole line** is used (not truncated), t = the z coordinate; in this case Min / Max Depth is the z range. Custom rays start at origin,
  t ≥ 0, direction normalized automatically.
- Integral = Σ mapped density × segment length; the view ray is first clipped to the volume bounding box (union for multiple volumes); a partial last segment is weighted by its actual length (exact for constant fields,
  and the midpoint rule is exact for linear fields too); a segment crossing a volume boundary counts as a whole segment depending on whether its midpoint is inside the volume.
- Stratification Jitter: the slice grid of the whole ray is shifted by (rnd − 0.5) × scale × step; segment 0 always starts at the entry point, so nothing is missed.
- Minimum / Maximum use the raw sampled values (the docs say the Density section only applies to Integral / Transmittance); not touching any volume gives ±inf
  (the docs' wording).
- Transmittance Cutoff defaults to −1 (no early stop; the docs give no default, −1 = exact). With multiple channels it only stops when all channels are below the cutoff.

Not done:
- **The Density Ramp curve**: Clamped / Periodic only do the "clamp to 0~1 / take the fractional part" step, with the curve as identity (stated in the panel help).
- Depth Conversion (Distance / Depth / Height): the latter two need the camera's forward vector / image plane, and we have no layer camera; only Distance.
- camera_ref, Move to Origin, Seed Jitter with Time, Signature (all need layer metadata / time).

Mutation: 18 + 4. 6 survived the first round: defaulting to the first volume, custom rays + negative Min Depth, the `ins` check when multiple volumes have different extents,
all / any for the multi-channel Cutoff -- killed after adding tests; `tf > tn` changed to `>=` (a zero-length ray accumulates nothing) and "take one extra step before stopping"
(the extra step has a negative segment length and isn't counted) are **equivalent mutants**; code kept, noted here.

## [C] Project on Layer → skipped

Docs re-checked (WebFetch projectonlayer). It "uses source as a slide projector, projecting it onto the target
layer with source's **layer camera**". Our CopImage has no layer camera / world position metadata, so there is no computable projection between two images (with default cameras on both sides it is just
an identity resample). The old mapping to UV Backproject (geometry + uv back-projection) is not the same thing, so that copernicus_map row was changed to
`("oos", OOS_META)` and no new node was added. Invert Transformation / Border / Filter all depend on the projection itself and are dropped with it.
**The coordinator needs to confirm**: this row changed from done to oos (marking it done before was wrong).

---

## [C] Configure Stamps → new node PCG_COPConfigureStamps

Docs re-checked (WebFetch configurestamps). Houdini's node only writes sprite / stamp attributes onto points (it draws nothing); the old target,
Scatter Shapes, is rasterized stamping, not the same thing. A new node was added; copernicus_map points to it (Scatter Shapes still corresponds to Scatter
Shapes / Stamp Points / Scatter on Curves).

Done: Seed, Jitter / Jitter Scale / jitter layer + Mask, Scale + Scale Mode (Uniform / Percent Variance /
Min/Max) + Variance / Min / Max + layer + Mask, Stretch (X Y) + Stretch Mode (Uniform / Variance / Min/Max) + …,
Angle + Angle Mode + Variance / Min / Max + Round To + angle layer / direction layer + their own Masks, Use Sort Layer +
sort layer, Stamp Color (Uniform / Variance) + Color Seed + Hue / Saturation / Value + layer + Mask, Stamp Alpha
(Uniform / Variance) + Alpha Variance + layer + Mask, Stamp Count + Mode (Cycle / Random / Layer Select) + Select
Seed + select layer. Attributes written: spritescale (2), spriterot (degrees), Cd, blend, stamp (int); Jitter / Sort change P.

Different from Houdini / decided here (the docs have one sentence per item, so **all the formulas are our choice**, each written out in the node docstring):
- Houdini's 9 layer inputs → one optional COP input `layers` + 9 layer names; point → uv uses plane + world (consistent with Layer to Points),
  bilinear sampling.
- Layer modulation is always `value × lerp(1, layer value, Mask)` (the angle layer is `+ layer value × 360 × Mask`, per the docs 0 → 0°, 1 → 360°; the direction
  layer is `+ atan2(y, x) × Mask`).
- Percent Variance / Stretch Variance: × (1 + Variance · r); Angle / Alpha Variance: + Variance · r (in angle units /
  clamped to 0~1); r ∈ [−1, 1). Min/Max: × a uniform pick in [Min, Max]; Angle's Min/Max also multiplies (the docs say "multiplied against
  Angle"; it looks odd but follows the docs). Round To rounds to nearest, applied last.
- Color Variance: in HSV, h wraps around, s / v clamped to 0~1. Color Seed also drives alpha's randomness (the docs say Color Seed drives "color and
  alpha randomization").
- Jitter is in world units (Houdini's is image space); the Sort layer value is added directly to the out-of-plane axis (the docs only say "a small Z offset").
- Layer Select: round(layer value × (Count − 1)) clamped to range.

Not done: **Random from Ramp** (color / alpha; needs a ramp parameter); the Per-Component Controls toggle (Jitter Scale is always two-axis).

**The coordinator needs to know**: our own Scatter Shapes reads pscale / Cd, not spritescale / spriterot / blend / stamp --
connecting Configure Stamps' output to Scatter Shapes only makes Cd take effect. Whether Scatter Shapes should recognize these attributes is outside this package's scope.

Mutation: 22 + 4. 4 survived the first round: Round To rounding vs floor, Saturation not taking effect, Value not clamped, uv using a fixed plane --
killed after adding tests.
