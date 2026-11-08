# c6_uv_xform (pcg100): COP UV / coordinate space / transform batch

All doc pages were re-checked with WebFetch (uvmap / uvmapbyid / polartouv / uvtopolar / spacetransform /
spheresample / xform / align / alignpixels / bend / posmap). As with the previous batch, these SideFX pages **have only parameter names
and a one-sentence description each**, no formulas and no defaults; that is why everything below marked "decided here" exists.

Tests: `test_audit_c6_uv_xform.py`. The only node whose old-behaviour path changed is PCG_COPUVMap; its "bit-for-bit identical to before the change at default
values" uses the hard-coded digests GOLDEN (4 calls on the pre-change commit 9e3fb92: identity default / identity with Scale·Rotate·Offset /
by_id fit / by_id stretch, rounded to 5 decimals before sha1; recomputed with `--digests`), independent of git. During development I also temporarily put the old uvx.py
back into the package and compared bit-for-bit once (4 calls, every layer `np.array_equal`). Everything else is new nodes; old nodes are untouched.

**Unified coordinate-space convention** (new file `geo/cop/coordspace.py`): our CopImage has only a resolution -- no distinction between data window /
display window, no pixel scale, no layer camera. So Data Window = Display Window = the whole image;
Buffer = Pixel; World = Image (equivalent to a default orthographic camera looking at the z = 0 plane). Image space follows the convention already in the plugin
(transform.crop_window / fx mirror): origin at the image center, −1…1 spanning the **long side**. Pixel: the center of the first pixel is 0.5
(the UV Map docs' wording).

Border / Shift / Cycles (shared by UV Map, UV Map by ID and Position Map via `shift_cycles_border`):
the docs only say both come before Border, not whether Shift or Cycles is first -- defined as **(x + Shift) × Cycles**, then Border.
Mirror's period is 2·(hi − lo), Wrap's is hi − lo. The docs don't give the "canonical range" of Pixel space; [0, W] / [0, H] is used.

---

## [C] UV Map + UV Map by ID → PCG_COPUVMap (parameters appended, default = old behaviour)

Both audit items point at the same node. The UV Map item is marked [C] (the old node's Scale / Rotate / Offset / Fit are our own
parameter set), but all of Houdini's parameters can be added "appended, defaulting to the old behaviour", with no semantics conflicting with the old parameters, so
I chose "give the original node Houdini semantics" over a new node. All appended to the end of INPUT_TYPES:

- `uv_space` (Texture / Image / Pixel): under identity the old Scale / Rotate / Offset are still done in texture space, and the result is then
  converted to the chosen space. by_id + Image: the island's bounding box is **uniformly** fitted into [−1,1]² (docs: "framed to fit the bounding box, so
  keep pixels square"); Fit isn't read under Image. by_id + Pixel: raises an error (Houdini's by ID menu only has Texture / Image).
- `u_border` `u_shift` `u_cycles` `v_border` `v_shift` `v_cycles`. **Border defaults to Extend**: the docs don't give Houdini's default,
  and only Extend = no folding matches the old behaviour.
- `uvscale_layer` (empty = not output, = old behaviour): 1 channel, "how many times larger than the identity UV Map of this space" = the largest singular value
  of the Jacobian (multiplied by the inverse of the identity mapping's Jacobian). identity is the analytic diag(Cycles)·D·Lin·D⁻¹; by_id is the island's scale
  (Texture/stretch: max(|cu|·W/bw, |cv|·H/bh); Image: long side / island long side). The docs only have the one sentence "effective scale factor
  caused by resizing"; the exact quantity is our choice; our UV Sample doesn't currently consume uvscale.
- `id_mode` (Houdini by ID's Mode: UV Map / Center / Minimum / Maximum / Size): the bounding box uses pixel edges, measured in
  uv_space. These four modes **don't apply** Shift / Cycles / Border (the docs don't say they act on the statistics); uvscale = 1.
- `auto_scale` (default on = old behaviour): when off, under Texture the origin is at the lower left of the island's bounding box in whole-image texture units; under Image
  the origin is at the bounding-box center in whole-image image units. The docs don't give the origin; our choice.
- `zero_negative_ids` (default on = old behaviour: negative ids were already skipped): when off, negative ids form their own islands.
- `connected` (default off = old behaviour): when on, disconnected pieces within one id each count as an island (**4-connected**; the docs don't say 4 or 8).
  Houdini says "each connected ID island", so turn it on for Houdini semantics.

Still different from Houdini / decided here:
- id 0 is background (uv = 0, uvscale = 0). The docs' "negative ids are set to zero" implies 0 is "invalid", but doesn't say outright whether 0 is an island.
- Houdini's Texture is "stretched to the bounding box"; under Texture ours is still governed by the old Fit (default Fit preserves aspect); for
  Houdini's behaviour choose Stretch (stated in the panel help).
- No size_ref input: the old node uses the optional `cop` input to set the resolution, which does the same job.

Panel (g9): everything by_id-related is `hide mode != by_id`; Fit is disabled under Image / Auto Scale off / the statistics modes;
Border / Shift / Cycles are disabled in by_id's statistics modes; Translate / Rotate / Scale are only shown under identity.

Mutation: 37, 8 survived the first round, all killed after targeted tests -- uvscale in Pixel space (non-square image + non-uniform scale +
rotation, checked against a numeric Jacobian in all three spaces), the u lower bound of Clamp under Image, Lin with rows/columns swapped (only distinguishable with a non-square image + non-uniform
scale), uvscale = 1 in the statistics modes, by_id's uvscale dominated by the v axis / Cycles taken as absolute value, 4- vs 8-connectivity (two pixels adjacent only
diagonally).

---

## [C] UV to Polar / Polar to UV → new node PCG_COPPolarCoords

In Houdini these two are **pure coordinate conversions** (uv stored in pixels ↔ angle / length, no pixels moved); the old COP Polar resamples the whole image in
polar coordinates (equivalent to the combined effect of UV Map → UV to Polar → UV Sample), so per [C] it is left alone and a new node was added,
with a `direction` dropdown choosing the direction (two Houdini nodes in one, per plugin convention). Two rows of copernicus_map now point to it.

- Angle Units: Radians / Degrees / Circles(2pi), default Circles (the UV to Polar docs say the default is "rotations").
- UV to Polar: reads `uv_layer`, writes single-channel `angle_layer` / `length_layer`.
- Polar to UV: reads `angle_layer` / `length_layer`; when a layer name is **empty** the `angle` / `length` constants are used (corresponding to "parameters are used when no input is connected");
  writes `uv_layer`.
- Decided here: angle 0 = +u, counterclockwise positive (v up); output angles fall in [0, one full turn) (the docs only give Circles 0~1);
  `origin` is our extension (Houdini's origin is fixed at uv = 0), default 0 0. The Length constant defaults to 1, Angle to 0.
- Not done: Signature (layer type signature; the plugin has no such concept).

Mutation: 9, all killed.

## [C] Space Transform → new node PCG_COPSpaceTransform

The old target, COP Vector Transform, does rotation / matrix / tangent-space transforms, not the same thing, so a new node; copernicus_map points to it.
- Vector Type: Position (affine) / Vector (linear part only). Source / Destination Space: Buffer / Pixel /
  Texture / Image / World. The source space is interpreted at `src_ref`'s resolution, the destination at `dst_ref`'s (unconnected = coord's own).
- Different from Houdini: Buffer = Pixel, World = Image (see the beginning); only the first two channels are converted, the 3rd is kept as is (there is no camera,
  so nothing to convert in depth). Empty `out_layer` = overwrite the original layer (extension).

Mutation: 10, all killed (including ref being ignored, Vector still adding the translation, the two axes' coefficients mixed up).

## [C] Position Map → new node PCG_COPPositionMap

The old target, Render Pass, is a geometry render-pass generator, not the same thing, so a new node; copernicus_map points to it (status done → new).
- Source Position: Position = (image x, image y, 0); View Direction = (0, 0, −1) (the default orthographic camera looks along −Z).
- X/Y/Z Border (default Extend; the docs don't give Houdini's default) / Shift / Cycles, canonical cube [−1, 1]³.
- The optional `size_ref` input sets the resolution; unconnected uses resolution_x/y.
- **Camera Origin not done**: an orthographic camera's origin varies per pixel, but the z value depends on the camera, and we have no camera metadata, so not invented.

Mutation: 5, 1 survived (Y used X's Cycles -- in the test both x and y Cycles were the default 1); killed after adding "Y Cycles 2, X Cycles 3".

---

## Shared: new file `geo/cop/warp3d.py` (Sphere Sample / Transform 3D / Align / Align Pixels / Bend)

Many of these Copernicus nodes **change layer metadata** (where the layer sits in the world, the camera), and pixels only come out at Rasterize.
Our CopImage has no metadata, so all of them **output pixels directly** (equivalent to always being followed by a Rasterize Layer), on the raster of
size_ref (unconnected = source itself). The default camera looks along −Z: orthographic = one parallel ray per pixel; perspective = camera at
(0, 0, Camera Distance), seeing exactly the image-space area on the z = 0 plane. **Camera Distance is a parameter we added**
(Houdini's camera comes from layer metadata), default 2.

Filter (Point / Bilinear / Box / Bartlett / Catmull-Rom / Mitchell / B-spline) is implemented as a reconstruction kernel (`fsample`,
BC cubic kernel). We don't do footprint filtering for minification, so **at unit footprint Box = Point and Bartlett = Bilinear** (stated in the panel help);
they only differ in Houdini when it enlarges the footprint by uvscale.

## [C] Sphere Sample → new node PCG_COPSphereSample

The old target, COP UV Sample (its latlong mode is "look up by a direction layer"), is not the same thing, so a new node; copernicus_map points to it.
- Done: Filter, Transform Order, Rotate Order, Celestial Sphere (reads only Rotate, mask all 1), Projection
  (Perspective / Orthographic), Translate / Rotate / Scale / Uniform Scale, size_ref, source,
  the transform and mask outputs (layer names configurable).
- Decided here: the lat-long convention follows the plugin's UV Sample latlong (Y up, +X at u = 0.5, front center at u = 0.25); with the camera
  inside the sphere, the far intersection is used. Celestial sphere + orthographic = all rays in the same direction, so the whole image is one color (a direct consequence of the definition).
- Different: Signature not done; the camera is our own default camera.

## [C] Transform 3D → new node PCG_COPTransform3D

The old target, COP Corner Pin, is a four-corner mapping, not the same thing, so a new node; copernicus_map points to it.
- Done: Transform Order, Rotate Order, Translate, Rotate, Scale, Shear (XY / XZ / YZ), Uniform Scale,
  Pivot Translate, Pivot Rotate, Invert Transformation, Perspective Camera, Border (Auto / Constant /
  Clamp / Mirror / Wrap / Clip), Filter (default Box, per the docs). The matrix comes straight from SOP Transform's `ops.xform_matrix`.
- **Only the Rasterize mode is done**: Houdini's default is "only change the layer's 3D placement, no pixels", and we have no metadata, so there is no
  Rasterize toggle (always on). **Crop to Content not done** (we have no data window; the output is always the original raster).
- Border Auto: our layers have no border metadata (equivalent to Constant), and per the docs Constant uses Clip, so Auto = Clip.
  Clip = sample normally inside the image (clamped at the edge), 0 outside; Constant = pad with 0 outside, the edge fades to black by the filter kernel.
  Pixels edge-on to the camera / behind the camera are 0 regardless of Border (the first version sampled edge values under Clamp / Wrap; found during
  mutation testing, fixed).

## [C] Align → new node PCG_COPAlignWindow

The old COP Align is "stretch / fit / fill the whole image into the reference resolution", not Houdini's justify / goal alignment; per [C]
it is kept, a new node was added, and copernicus_map's Align points to it.
- Done: Justify with (Reference Window / Target Point), Units (Image / Texture / Pixels / World), Target
  Point, Target Size, Justify X/Y (None / Min / Center / Max), Goal X/Y (Same / Min / Center / Max),
  Offset by (image space), Scale to Fit, Uniform Scale, Scale Axis (Scale X / Scale Y), Filter.
- Different from Houdini: there is no data window ≠ display window, so Source (Data / Display Window) isn't done,
  and Reference Data / Display Window are merged into a single Reference Window. World = Image.
- Decided here (not in the docs): Target Point is the **center** of the target rectangle; Scale to Fit is done first (about the source rectangle's center), and Justify uses the scaled
  rectangle; with Uniform both axes use the ratio of the Scale Axis axis, without Uniform each axis is stretched to the target width / height; Justify
  defaults to Center, Goal to Same (the docs don't give Houdini's defaults). Outside the image is padded with 0.

## [C] Align Pixels → new node PCG_COPAlignPixels

- Done: Side (X) / Side (Y) (the docs **don't list the options**; Justify's Min / Center / Max are used, default Min), Justify with
  (Reference Window / Original Window / Target Point), Units, Target Point, Justify X/Y, Goal X/Y,
  Offset by (pixels).
- Semantics: ① snapping -- the Side point of the source window in the world is converted to the reference image's pixel coordinates and rounded to a pixel corner, and the source is laid out 1:1
  pixel from there (no interpolation, pixels preserved bit-for-bit, the test uses array_equal); ② the per-axis translation is rounded. Offset is rounded too (the docs say
  whole pixels, no interpolation). When partly out of bounds only the overlap is copied.
- Different from Houdini: Snapping's Data / Display Window choice isn't done (merged, as in Align).

## [C] Bend → new node PCG_COPBend

The old COP Swirl's bend mode is a bend distortion about the center that matches none of Houdini's three Modes; kept. A new node was added and copernicus_map's
Bend points to it.
- Done: Mode (Corners / Sides / Angle), Filter, four corners, eight tangent handles, four edge midpoints, Bend Angle, Capture
  Origin / Direction / Length, Deform in Both Directions, size_ref; plus an optional mask output (extension).
- Corners: each edge is a cubic Bézier (corner → corner + handle → other corner + handle → other corner), with a Coons patch inside (bilinear blend).
  Sides: each edge is a quadratic curve through the midpoint, Coons inside likewise. Angle: the segment [0, Length] along the capture direction is bent into a circular arc (total turn
  Bend Angle, bending to the left of the direction), with the part after it following rigidly and the part before it unchanged; with Both Directions the opposite direction bends the same way (the same idea as SOP Bend).
  Each output pixel's source coordinate is solved by Newton iteration (numeric Jacobian, step limiting); unsolved / outside the patch = 0.
- Decided here (the docs only have parameter names): **tangent handles are offsets relative to the corner** (not absolute positions); default handles = 1/3 of the edge length (straight edges, identity);
  default corners ±1 -- **for identity on a non-square image the corners must be (±W/L, ±H/L)** (stated in the panel help, verified at 32×16 in the tests); Angle
  mode defaults to 45°, origin (0, 0), direction (0, 1), length 1. When the patch folds over itself only one solution is found.
- Not done: the viewport Handles tool (interactive; the plugin has none).

Mutation (67 in total for warp3d): 14 survived the first round --
- 2 equivalent: the BC kernel's `x < 1` changed to `x <= 1` (the kernel is continuous at 1, both pieces = B/6); one "identity mutant" generated by a typo.
- 11 killed with added tests: B-spline at a half cell (C has no effect at integer points), sphere / plane behind the perspective camera, Target Size in Texture units,
  Pixels units on a non-square reference, scaling before Justify, Side X / Side Y separately, Sides rotated 90° (initial guess far from the solution, so step limiting matters),
  the mask to the upper right of the patch, a non-square source image, pixels where the inverse solve fails output 0 (Angle 300° folds over itself).
- 1 bug found and fixed: in Transform 3D, pixels that miss the plane weren't 0 under Clamp / Wrap / Mirror (see above). After the fix, the two lines
  "set px of missed pixels to 0" were proven redundant (t = −1, coordinates finite, masked out by keep later) and removed.

---

## Side findings / not touched (other packages or old nodes)

- The old COP Polar (to_polar / from_polar resampling), COP Vector Transform, COP Corner Pin, COP Swirl's bend mode,
  COP Align (stretch / fit / fill) and COP UV Sample's latlong mode are all kept untouched per [C]; the corresponding
  Houdini rows in copernicus_map now point to the new nodes. COP UV Sample is still the mapping for "UV Sample".
- Our COP UV Sample doesn't consume uvscale (Houdini uses it to adjust filter width); the uvscale that UV Map / UV Shape output is currently informational only.
- `test_audit_c4_pattern_shape.py`'s `defaults()` takes the first dropdown item and doesn't recognize `{"default": …}`; this package's tests have their own version that
  recognizes default.

## Test counts

`test_audit_c6_uv_xform.py` 214 checks, all pass. Regressions: test_nodes 42, test_panel 42, test_panel.mjs 230, test_cop_uv 62,
test_cop2 197, test_sop_xform 49, test_sop_map 11, test_icons.mjs 23 (after regenerating tools/nodes.json), all pass.
No hard-coded numbers in existing tests needed changing because of appended widgets.
