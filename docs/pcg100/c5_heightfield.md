# c5_heightfield (pcg100): the HeightField COP family

All doc pages were re-checked with WebFetch (heightfield_terrace / slump / strata / maskbyfeature / project /
xform / erode / visualize). These pages **have only parameter names and a one-sentence description each**, no formulas and no defaults; that is why
everything below marked "decided here" exists.

Tests: `test_audit_c5_heightfield.py`. "Bit-for-bit identical to before the change at default values" uses the hard-coded digests GOLDEN (the same 20 calls on the pre-change commit
9e3fb92 -- Terrace ×3, Thermal ×3, Strata ×2, Mask by Feature ×3, HF Project
×5, Visualize ×4 -- arrays rounded to 5 decimals before sha1; recomputed with `--digests`), independent of git. During development I also compared bit-for-bit against
the full arrays saved with `--dump` (an npz in the scratchpad): once after each node, 72 arrays bit-for-bit identical.

---

## HeightField Terrace → PCG_COPTerrace (parameters added)

Done (all appended to the end of INPUT_TYPES, defaults = old behaviour):
- `method`: `step_size` (old) / `num_terraces` (Number of Terraces: step = (Max − Min) / `terraces`).
- `terraces`, `min_height`, `max_height`.
- `limit_range` (a toggle we added): Step Size also only works within [Min, Max]. Houdini's Min / Max exist under both
  Methods, but our old Step Size wasn't range-limited, so to keep defaults = old behaviour a toggle had to be added. Number of
  Terraces is always range-limited (doesn't read this toggle).
- `random_step` (0~1) + `rand_seed` (Houdini's Step Seed).
- `mask`: Houdini's Mask parameter (blend amount), multiplied onto the existing `mask_layer`; without a mask_layer it is a constant blend amount.
- Panel (g8): Step / Terraces hidden by Method; Limit Range hidden under Number of Terraces; Min / Max disabled when
  "Step Size and Limit Range off"; Step Seed disabled when Random Step = 0.

Decided here (not specified by the docs):
- When range-limited, the first boundary is at **Min + Offset** (docs: "generate terraces starting from Min Height"). Values outside the range are untouched,
  and the endpoints are included in the range. With Number of Terraces + Offset 0 both ends land exactly on the boundaries and join up; with an Offset, or when
  Step Size doesn't divide the range evenly, there are jumps at both ends -- the docs don't say how Houdini handles the range endpoints, so no extra transition was added.
- Random Step: the docs only say "scales the random height added to each step, 0 = every step the same". Here it is implemented as **moving the boundaries**:
  b_k = base + step·(k + rs·(r_k − ½)), r_k = hash random(k, seed). rs ≤ 1 keeps the boundaries ordered → still
  monotonic, only cuts and never fills; the average step is unchanged, so Number of Terraces keeps its step count. Under Number of Terraces
  the boundaries k = 0 and k = N are pinned and don't move (with Offset 0 the two ends still join up).
- The terrace face shape is still our f^p (Sharpness); Houdini doesn't have this parameter -- kept (intentional extension).

Still different from Houdini / not done:
- **Add Layers / Layers / Seed / Global Seed not done**: the docs only say "adds several layers of randomly offset terraces", not how the layers combine
  (average? max? sum?). Global Seed only affects that and Step Seed, and Step Seed already uses rand_seed.
- **The mesa / cliffs output layers not done**: the docs don't define how a mesa / cliff is determined (our terrace faces aren't strictly flat,
  and at Sharpness 1 the cliff is a discontinuous jump with no "pixels on the cliff").
- The Compute Range button (we have no button widgets).

Mutation: 27 + 7. 10 survived the first round, handled as follows:
- The margin of the boundary search range (originally −2 / +3): proven that −1 / +2 is exactly enough (jitter ≤ ½ step); after tightening I added a test "single-pixel image
  × 40 seeds × Random Step 1 agrees with a brute-force reference", which kills the mutations in both directions.
- The division-by-zero guard `np.where(w > 0, …)`: proven redundant (differences of r ∈ [0,1) are > −1, rs ≤ 1 → w > 0), removed.
- Number of Terraces originally only pinned the boundaries at Offset 0: changed to always pin (at Min/Max + Offset when Offset ≠ 0),
  condition removed.
- `rs > 0 and p != 1`: added "Sharpness 0 + Random Step is still bit-for-bit identity". Random Step upper-bound check: added a direct
  function call with 1.5 that must raise. Min + Offset and the range endpoints ≥ / ≤: the original test happened to have 0.5 land on an equivalence point; changed to 0.52 and added a hand-computed case with endpoints including
  Offset; all killed.
- `searchsorted(side="right")` → `"left"`: **equivalent** (when h is exactly on a boundary, left falls to the next step with f = 1,
  b_{k−1} + w·1 = b_k, the same value), kept.

---

## HeightField Slump → PCG_COPThermalErosion (modes / parameters added)

The audit said we only cover the "thermal" kind. Re-checking the docs showed **the semantics differ by one layer**: in Houdini Slump the height is fixed
bedrock and what slides is the **debris layer** (without a debris input, a constant thickness Debris Scale); our old one lets the whole height collapse.
So what was added is "optional Houdini semantics", with the old one kept as the default mode.

Done (appended after `compute`, default = old behaviour, bit-for-bit unchanged):
- `debris_source`: `height` (old, panel label Whole Height (Thermal)) / `layer` (Debris Layer) /
  `constant` (Constant Depth). In the latter two: the bedrock doesn't move, debris = the `debris_input` layer × `debris_scale` (layer)
  or `debris_scale` thick everywhere (constant); slope is computed from bedrock + debris, and the amount moved per cell per step ≤ the debris currently in that cell
  (once it has slid away the bedrock is exposed and no longer cut); total debris is conserved.
- `debris_input` (layer name, default "debris"), `debris_scale`.
- `remove_debris` (Remove Debris from Input Height), `add_debris` (Add Debris to Output Height,
  default on). In these two modes the `debris_layer` output is **the debris thickness after sliding** (Houdini's debris output); the height mode still outputs the
  old "net deposition".
- `slump_mode`: `smooth` (old algorithm) / `granular`; `rand_seed` (Random Seed).
- Panel (g8): labels changed to Houdini's Repose Angle / Spread Iterations / Spread Rate (labels only);
  Seed disabled under smooth; the debris controls hidden in the height mode, Debris Input Layer only shown in the layer mode.

Decided here (not specified by the docs):
- Granular: the docs only say "collapses in chunks, with randomness". Implemented as multiplying each cell's per-step transport by a [0,1) hash random number
  (pixel index + step·pixel count, seed, salt 2). It only ever moves less, so conservation and "no overshooting" are unaffected.
  This is only "with randomness", **not chunks**; the docs don't say how Houdini's granular forms chunks.
- Smooth = our old deterministic algorithm (each cell moves rate·max excess/2, split among neighbours by their excess). Houdini says Smooth
  "spreads like a liquid"; unknown whether it's this scheme.
- Debris layer values are converted like height, "height value × Strength". Negative debris counts as 0.
- Add Debris defaults to on (the docs don't give Houdini's default).

Still different from Houdini / not done:
- **The Rainfall mode not done** (along with Flow Force / Rainfall Coverage / Slope Influence / Erosion / Deposition /
  Removal / Evaporation Rate): that is a hydraulic model with water-flow scouring, and the docs give no algorithm; our droplet erosion
  (PCG_COPHydraulicErosion) is a different system, and bolting it on would only "look like" it.
- **The flow output layer not done** (UV flow direction; the docs don't say how it is normalized).
- Neighbours 8 / 4 is our extension, kept.

Changed someone else's existing test: `test_cop_accel.py` "Compute is the last widget" -- for Thermal Erosion changed to
"compute still directly follows keep_layers" (caused by appending at the end per the rules; its position didn't move).

Mutation: 20 + 4. 2 survived (×Strength in the Constant mode, the error for an unknown Debris Source); after adding a hand-computed case with Strength 2
and an error test, all killed. **Note**: the first round's mutation script was cut off by a 2-minute timeout, and the last mutant (Add Debris hard-coded to
True) was left in the source file -- found with git diff and reverted; after that, mutations were run with a long timeout.
---

## HeightField Project → PCG_COPHFProject (parameters / menu items added)

Done (appended at the end, default = old behaviour, bit-for-bit unchanged):
- `project`: `maximum` (old: the first hit from the top down) / `minimum` (the farthest hit on the same ray = the lowest surface).
  Labels Maximum Height / Minimum Height.
- `max_height` (Max Projection Height): when > 0 the ray starts at +limit and travels at most 2·limit; geometry outside the limit
  (above or below) isn't projected.
- `blend` (Houdini Blend: hits are replaced by the projection, misses keep the original height) and `multiply`
  (at hits original × projection) appended to the `mode` menu. The menu that used to be built as `PROJECT_MODES[1:] + ["replace"]` is now a hard-coded list,
  with the old four items in the same order.
- `mask` + `mask_layer` (Houdini's Mask parameter and mask input): blends between the original height and the result.
- `projection_only` (Output Projection Only): outputs only the projected height, misses filled with Fill Value, without Blend Mode / Mask.
- `hitmask_layer`: given a name, also outputs a hitmask (hit 1, miss 0). Default empty = not output (Houdini always outputs it,
  but doing so by default would add a layer to old workflows and break "default = old behaviour").
- Panel (g7): with Projection Only on, Mode / Mask / Mask Layer are disabled; Mode's label changed to Blend Mode.

Decided here (not specified by the docs):
- **Max Projection Height is in height values** (same units as the output, world = value × Strength); 0 = unlimited (Houdini's default
  unknown). The docs say "largest absolute height"; here it is the band [−limit, +limit].
- Blend differs from our old Replace only where nothing was hit (Blend keeps the original value, Replace fills Fill Value).
- Mask is first multiplied onto Mask Layer (clamped to 0~1); without a geo connected (the Transform 3D path), Project / limit / Mask /
  projection only / hitmask still all take effect.

Still different from Houdini:
- Houdini requires polygon geometry; we go through tri_soup, and also accept other primitives that can be triangulated.
- translate / rotate / scale / fill_value are our old ones (the Transform 3D approximation when no geo is connected), kept.

Mutation: 18 + 3. 3 survived (Strength conversion of the limit -- the original test's values happened to hit the box bottom either way; the error for an unknown Project;
the Mask 1 + Mask Layer branch); after targeted tests were added, all killed.

## [C] HeightField Transform 3D → skipped (still points to PCG_COPHFProject)

**Not done, because**: Houdini's Transform 3D changes **where the layer is placed in 3D** (a Copernicus layer carries a
3D transform: Transform / Rotate Order, Shear, Pivot, Invert; Grid Scale changes the cell spacing, Height Scale /
Offset change the height values) -- the result is still the same image, just placed elsewhere in the viewport. Our CopImage has no concept of a "layer's world transform"
(only xres / yres / layers), so these parameters have nowhere to land in the plugin; forcing it would turn it into resampling, which would be
"looks right but isn't". The path in our PCG_COPHFProject without a geo, "transform the height field as a 3D mesh and project it back",
has resampling semantics and is not the same thing as Houdini -- per the [C] rule its behaviour wasn't changed.
The only parts meaningful for an image are Height Scale / Height Offset (= a Levels node) and Grid Scale
(= resampling), neither worth its own node.
**The coordinator needs to decide**: whether the row "HeightField Transform 3D": ("new", "PCG_COPHFProject") in copernicus_map.py
should change to a "not done / different semantics" state (I didn't change it, since there is no new node to point to).
---

## HeightField Mask by Feature → PCG_COPMaskByFeature (parameters / a section added)

Done (appended at the end, default = old behaviour, bit-for-bit unchanged):
- `blend_mode`: `multiply` (old) / `add` / `average` / `minimum` / `maximum`. Each criterion's mask is collected in the old code's
  order; multiply multiplies them in turn (bit-for-bit the same as the old `m = m * …`). With no criterion enabled every mode gives all 1.
- `smooth_radius` (Smooth Radius): blurs the height before measuring **all** features. Curvature's own Curv Blur is still applied on top as before.
- **The Mask by Occlusion section**: `use_occlusion` (section header toggle), `occ_min` / `occ_max` (Minimum / Maximum
  Occlusion), `occ_falloff`, `occ_height_scale` (Height Scale), `occ_radius` (View Radius),
  `occ_step_scale` (Step Scale), `occ_samples` (Sample Count). Reuses COP Height to AO (horizon-based).
- Panel (g7): Smooth Radius / Blend Mode placed before the criteria; the Occlusion section after curvature, with a header toggle.

Decided here (not specified by the docs):
- Add is not clamped (the docs don't say; the mask can be > 1, and < 0 after Invert).
- Smooth Radius is in **world units** (the docs say local space); Gaussian σ = radius / 3, kernel cut at 3σ = radius.
- Occlusion = 1 − AO (0 = open, 1 = fully blocked). The docs don't say how Houdini computes occlusion ("Sample from Hemisphere
  divides the angle by 90° instead of 180°" hints that it is normalized by horizon angle); our AO is an average of "the sine of the maximum elevation angle relative to the tangent plane,
  attenuated by distance", a different numeric scale -- the same Min / Max Occlusion will not frame the same region in the two.
- View Radius world units → pixels; Sample Count = number of directions; steps = ceil(View Radius in pixels / Step Scale),
  1~64 (height_to_ao's limit). The default Occlusion range is [0.2, 1] (only used when enabled).

Still different from Houdini / not done:
- **Slope / Height / Curvature / Direction / Occlusion Ramp not done**: we use the *_falloff smoothstep soft edges
  instead (ramp widgets exist, but adding five ramps would make the panel heavy, and "default ramp = the old smoothstep" can't be bit-for-bit;
  left for later).
- **Sample from Hemisphere not done** (our AO isn't normalized by horizon angle, so this toggle has no counterpart).
- Curvature: Houdini has a toggle + Max Curvature, the range [−Max, +Max] through a ramp; ours is off / ridges / gullies +
  threshold + normalization, kept (a superset). Direction's Angle Spread has the same semantics.
- The Compute Range button.

Mutation: 22 + 3. 4 survived: the radius not divided by texel size (the test image happened to have texel = 1), the blur's wrap / clamp, the tile in the occlusion computation --
killed after adding tests; the View Radius ≤ 0 error was proven **redundant** (height_to_ao raises on its own), removed.
---

## HeightField Visualize → PCG_COPVisualize (parameters added)

**To be clear up front**: Houdini's HeightField Visualize outputs **geometry with a color attribute** (for viewing the height field in the viewport);
ours outputs an image (ramp + hillshade + contours; plus three velocity modes). They are really two different nodes. Here only the two items that have a counterpart
on "an image" were added.

Done (appended at the end, only for the height_ramp mode, default = old behaviour, bit-for-bit unchanged):
- `range_mode` (Houdini's Mode): `clamped` (old = Clamped Ramp) / `periodic` (t modulo 1) /
  `no_ramp` (no ramp, all three channels are t, **not clamped**, extrapolated).
- `tint_by`: `height` (old) / `mask` (the ramp is driven by channel 0 of `tint_layer`) / `color` (`tint_layer` used directly as the color,
  a single channel spread to three, ignoring Range / Mode / Ramp). `tint_layer` is the layer name for Houdini's color / mask input.
- Panel (g9): Range's label changed to Input Range; Tint Layer hidden when Tint by = Height; under Color, Mode / Ramp /
  Range are disabled; under No Ramp, Ramp is disabled.

Decided here (not specified by the docs):
- When Lo / Hi are both 0 the automatic range takes the min and max of **the tint layer** (Houdini's Compute Range also uses the Tint layer).
- Hillshade and contours always come from the height layer; when Tint uses another layer, the hillshade gradient is normalized by the height's own min and max (under Height tint it is still the old
  normalization by Lo / Hi).
- No Ramp outputs grayscale (in Houdini this mode is a linear mapping "without the ramp" on geometry; on an image it can only be grayscale).

Not done:
- **Height Scale / Height Offset**: Houdini uses them to turn values into the geometry's world coordinates; we output an image and the hillshade is normalized by range,
  so these two parameters have nothing to act on in the image.
- **Split Channels, the layers input** (turning a series of layers into volumes on the geometry) -- only meaningful with geometry output.
- **Diffuse Ramp (an editable ramp)**: we have four preset ramps (terrain / gray / viridis / heat), not replaced with a ramp widget
  (if replaced, the defaults couldn't match the old presets bit-for-bit, and old workflows use the four presets).
- What we have and Houdini doesn't (three velocity modes, LIC, arrows, hillshade, contours, Seed) are intentional extensions, kept.

Mutation: 13 + 3. 3 survived (the unknown Tint by error masked by the "no layer given" error, the single-channel color expansion masked by allclose
broadcasting, the clamping for Color + No Ramp); after tests were added, all killed.
---

## HeightField Strata → PCG_COPStrata (partial)

**The model is different**: Houdini's Strata is "a noise (Simplex / Perlin / Worley / … + fractal + post-processing) laid out along tilted strata
planes, producing a strata layer, which is then combined into the height by Blend Mode (Add / Subtract / Multiply / Difference / Max / Min)";
ours is "tilted terraces" -- strata coordinate = height + Tilt·uv + noise, random hardness per stratum, blended back by Strength.
The Houdini docs don't say how the strata noise is sampled on the strata planes (Element Size is "image coordinates", Strata Size is "thickness", and how the two
combine, or how Tilt's angle converts onto our images with no world height unit, isn't said), so following it would be guesswork -- hence **only the three items
that fit our model were added**; the rest are listed below. It was not turned into a new node: the audit didn't mark it [C], and our node with "Tilt 0,
noise 0" is just Terrace, and has been used as the Strata approximation all along. **The coordinator needs to decide** whether to create a separate
Strata node with Houdini semantics (most of the work is the noise / fractal / post-processing c3 already has, but the definition of the strata coordinate has to be settled first).

Done (appended at the end, default = old behaviour, bit-for-bit unchanged):
- `strata_offset` (Strata Offset): the strata boundaries move as a whole to Offset + k·Spacing (height values); the stratum index _id moves with them.
- `mask_layer` (Houdini's mask input): blend-back amount = Strength × mask (clamped to 0~1). Houdini's Mask parameter =
  our Strength (panel label changed to Mask).
- `strata_only` (Output Strata Only): outputs only the strata displacement strata = target − strata coordinate (not multiplied by Strength, no mask;
  height + strata = the Strength 1 result).
- Panel (g8): Spacing's label changed to Strata Size; with Output Strata Only on, Mask / Mask Layer are disabled.

**Not done**: Blend Mode (our strata is "the displacement to the terrace target"; the five modes besides Add are legal but don't carry Houdini's meaning),
the Range section (Amplitude / Center / Noise Contrast), the Pattern section's Noise Type / Metric / Worley Jitter / Units /
Element Size / Scale / Offset / Rotate / Origin, Tilt as an angle (ours is a uv gradient "tx ty"), the Add Layers group,
Base Height Influence (the baseheight input), the Fractal section, the Post Processing section.
Our sharpness / hardness_random / noise_amount / noise_frequency are extensions, kept.

Mutation: 8 + 1, 1 survived (Mask Layer clamping), killed after adding a test.

---

## [C] HeightField Erode → skipped (still points to PCG_COPHydraulicErosion)

**Not done, because**: Houdini's Erode is **a combined hydro + thermal model on a grid** (Feature Size, Spread Iterations,
Erodability; Hydro's Flow Force / Bank Angle / Rainfall Coverage / Slope Influence / Erosion·Deposition·
Removal·Evaporation Rate; Thermal's Weathering Force / Cut Angle / Repose Angle; sediment / debris / flow
outputs, with a simulation cache). The docs have one sentence per parameter and **no algorithm** (how Bank Angle, Cut Angle, Removal Rate, and
Evaporation as "capacity decay" enter the equations is unknown). Assembling a grid erosion from the parameter names would only "look like" it, violating "better to do less".
Our droplet model (PCG_COPHydraulicErosion) is a different algorithm; per the [C] rule it is left alone. The existing correspondence:
the Thermal half ≈ PCG_COPThermalErosion (Repose Angle, Spread Iterations / Rate); Erosion / Deposition /
Evaporation Rate and Seed have parameters of the same name in the droplet model, but with different meanings.
**The coordinator needs to decide**: whether the "done" in "HeightField Erode": ("done", "PCG_COPHydraulicErosion") in copernicus_map.py
should change to "different semantics" (I didn't change it).
