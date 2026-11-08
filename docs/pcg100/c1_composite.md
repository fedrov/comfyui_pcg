# c1_composite audit notes (pcg100)

Handover note: the previous agent was interrupted and left uncommitted changes in 8 files (no tests, no notes, no mutation testing).
I read them section by section and checked them against a fresh copy of the SideFX docs. **I kept its implementation** and changed the following:

- `fx.copy_transform`'s over_last / under had a block that was effectively a no-op on "layers without alpha"
  (copy 0 is untransformed and covers the whole frame, so under always equals the original; `acov` was only used on this unreachable path). Removed it,
  and changed the docstring's "use coverage as alpha" wording to the actual semantics: a layer without alpha = the whole frame is opaque.
- `fx.mirror`'s docstring said "the docs don't say where Angle starts from" -- the docs do say it (20° × 3 planes = 20/40/60). Fixed.
- `fx.kernel_from_image`'s docstring said "the docs don't say where the origin is when Centered is off" -- the docs say "corner", they just don't say which corner. Fixed.
- `and not inside.all()` in `transform.crop` is a pure optimization (an equivalent mutant). Removed.
- Wrap-up it hadn't done: the new node's icon, the copernicus_map pointer, the hard-coded node count in test_panel.py (367 → 368),
  and test_nodes.py's canned inputs (see "Convolve" below).

Tests: `test_audit_c1_composite.py`, 310 checks. The last section takes the baseline code with `git archive a9e114d`,
runs 72 sets of **old parameters** (all old modes of the 8 nodes) on the same inputs in a subprocess, and compares bit-for-bit with the current output.

## Blend → PCG_COPComposite (partial)

Done:
- Appended `under / hypot / exclusion / hardlight / dodge / burn` to the end of Mode. Houdini's Blend = the existing
  `replace`, Maximum / Minimum = the existing `lighten / darken`; no duplicate tokens were added, the panel labels were changed to Houdini's names
  (Blend / Maximum / Minimum / SoftLight; Opacity's label changed to Mask).
- New widgets (appended at the end, default = old behaviour): `swap` (Swap FG and BG), `compare_lengths`,
  `channel_r / channel_g / channel_b / channel_a`.

Still different from Houdini / not done:
- **The five modes Sharpen, Hue, Saturation, Luminosity, Color are not done**: the docs give only a one-sentence description, no formula
  (for Hue and the other three the industry has W3C's non-separable blend formulas, but the docs don't say whether Houdini uses that set, so I didn't invent it).
- Space / Border / Filter / Clip by Data Window / Crop to Content not done: they all depend on data window ≠ display window,
  and our layer = the frame. When the two inputs have different resolutions we still resample to the first input.
- The Alpha Compositing toggle is not done: our over / under / atop / xor always composite by alpha, the other modes are always per-component.
- Toggle RGB (one switch for all three channels) not done, only the four separate toggles.
- Our extra atop / xor are kept.

Not specified by the docs, decided here:
- Dodge = bg / (1 − fg), Burn = 1 − (1 − bg) / fg (the docs only say "brightens / darkens based on the foreground"). No clamping; a zero denominator is padded with 1e-8.
- HardLight at fg = 0.5 goes to the screen branch (the two branches are equal there, so it doesn't matter).
- Compare Lengths tie (equal lengths) keeps the background.
- After Swap, Mask < 1 interpolates toward "the swapped background" (= the original foreground); output resolution and the other layers still come from the first input.
- Channel toggles: a single-channel layer only looks at Red, a two-channel layer at Red / Green; channels from the 5th on are always on.
- Under is implemented as "over with the two inputs swapped".

## Mask Combine → PCG_COPMaskCombine (partial)

Done:
- Appended `layer_stack` to the end of Operation: Houdini's approach -- starting from `starting_value`, one layer per line in `stack`
  (`layer[.channel] [mode] [amount]`, a leading `#` = this layer is off), each with its own Blend Mode and Mask amount, stacked top to bottom.
  16 modes: blend add subtract multiply divide screen hypot difference exclusion maximum minimum
  overlay softlight hardlight dodge burn.
- Post-processing (applies to every Operation): `fold`, `complement`, `use_clamp_min / clamp_min`, `use_clamp_max / clamp_max`,
  in the order Fold → Complement → Clamp Min / Max → the original Clamp 0-1.

Not done:
- Blend Mode **Sharpen** (no formula).
- Per-layer Conversion = Channel Mix / Light Direction (only Channel Extract is done, written as `layer.channel`), Blur, Layer Remap.
- Post-processing Combined Mask Remap, Mask Contrast, Amplitude, Center, Bias, Gain, Gamma, Contrast: the docs give no formulas
  (Bias / Gain / Contrast are defined differently by different vendors). If needed, follow with a COP color-correction node.
- Houdini uses a multiparm, we use a multi-line text field -- the panel does not have one row of controls per layer.

Decided here: mode defaults to blend, amount defaults to 1; no channel given takes channel 0; post-processing runs in the order listed on the panel
(the docs say "executed in the order listed", and the relative order of Fold / Complement / Clamp matches ours).

## Crop → PCG_COPCrop (partial)

Done (all appended at the end):
- `mode`: `discard_reframe` (old behaviour) / `discard` (Discard Cropped: resolution unchanged, everything outside the window is dropped).
- Appended `mirror` to the end of Border (reflect at the edge, the edge pixel repeated once).
- `units` (pixels / texture / image), `method` (lower_left_size / lower_left_upper_right), `corner`, `extent`.
  **With pixels + lower_left_size the integer X / Y / Resolution are read as before** (that is what old workflows saved); every other combination reads the Corner / Extent
  vector strings -- the panel hides one set or the other based on this condition.
- Pixel Padding: `pad_left / pad_right / pad_top / pad_bottom`.

Not done:
- Mode **Reframe to Crop** (data untouched, only the display window changes): we can't represent data outside the frame.
- Border Unchanged / Clip (layers carry no border attribute); Constant = the existing `black`.
- Aspect Ratio, Extract Tile (Tile Counts / Tile Number), Minimum Resolution, Limit / Maximum Resolution,
  Reset Pixel Origin, Geometry Units and the two inputs bounds / size_ref.

Decided here:
- After the Units conversion each of the two corners is rounded to a pixel edge (`floor(x + 0.5)`); the docs only say "rounding happens". An empty window raises an error.
- image units: −1 … 1 spans the **long side**, origin at the image center, square pixels.
- With Discard Cropped, pixels outside the window are read per Border outward from "the part that stays (window ∩ original image)"; a window entirely outside the image = all 0.
- The docs' Pixel Padding is two parameters, Left/Right and Top/Bottom (each a pair); here they are split into four integers.

## Convolve Filter → PCG_COPConvolve (partial)

Done: optional inputs `kernel_cop` + `kernel_layer` + `centered` (Centered Kernel); appended `mirror` to the end of Border.
When a kernel image is connected, the Preset / Kernel string is not read.

Not done: the Padding toggle and value -- we always pad by the kernel radius and crop it back off, so there is no circular-convolution bleed
(equivalent to Padding on and large enough). Border Unchanged is missing (layers carry no border attribute).

Decided here:
- Interpreted as a **true convolution** (convolving a single-pixel impulse = the kernel image itself); the docs don't mention whether the kernel is flipped. Note this is the opposite direction
  from this node's string kernel (correlation, first row at the top); one test lines the two up.
- Centered = origin at (h//2, w//2); off = the lower-left pixel (the docs only say "corner").
- A 1-channel kernel → used for every channel; kernel channel count = layer channel count → per channel; anything else raises an error. Normalize divides each channel by its own sum.

Side note: test_nodes.py's "run once with defaults" feeds a canned image (C is 3 channels) into optional COP inputs,
and Layers left empty = all layers, so the 1- / 2-channel layers don't match the 3-channel kernel and raise. In test_nodes.py's OVERRIDE I
added `layers="C"` for PCG_COPConvolve (that table exists for exactly this), and did not touch the reject list. **The coordinator needs to confirm this is OK**;
the alternative is to fall back to the kernel's channel 0 when the channel counts don't match, but that is a silent guess.

## Copy and Transform → PCG_COPCopyTransform (partial)

Done:
- `scale_xy` (non-uniform Scale, multiplied with Uniform Scale).
- Appended `over_last` (Houdini's Over: later copies on top) and `under` (Houdini's Under) to the end of Op; alpha is computed Porter–Duff,
  Fade only multiplies alpha. **The old `over` is "copy 0 on top", the opposite direction of Houdini's Over, and it interpolates alpha as an ordinary channel**
  -- behaviour unchanged, the panel label reads "Over (Legacy, First Copy on Top)".

Not done: Blend Method Subtract / Multiply / Minimum (the docs' description depends on Background Color, and the Subtract sentence
"subtracts the original pixels from the stamps layered on top" is ambiguous about direction), Order, Filter, Wrap Mode / Tile Size, Center Pivot on Shape,
Pivot Rotate, Stamp Color, the two Change per Copy, Color Ramp / Alpha Ramp, Uniform Alpha, Background Color / Alpha,
the size_ref / pointmask inputs, the id / uv outputs.

Different from Houdini: Translate is still UV (Houdini's is world); Fade is multiplicative (Houdini's Change per Copy is additive).

Decided here: a layer without alpha is treated as fully opaque over the whole frame under over_last / under -- with over_last a later copy's **whole frame**
(including the black areas) covers the earlier ones, and with under the result is the original image. To stack by shape, give the layer an alpha.

## Mono → PCG_COPLuminance (done)

`operation` (15 modes, menu order as in Houdini, default `hdtv` = the previously hard-coded Rec.709, bit-for-bit unchanged), `weights`, `normalize_weights`.

Decided here (the docs only say "the channels" and "standard channel expansion rules"):
- Average / Maximum / Minimum / Magnitude use **all existing channels** of the layer (RGBA includes alpha).
- Hue / Saturation / Value / Red / Green / Blue / Alpha use channel expansion: Mono → all three channels are it, UV → blue padded with 0, alpha padded with 1.
  Hue is 0-1.
- The three luminance sets take channel 0 on layers with fewer than 3 channels (this node's old rule).
- Custom only uses as many weights as there are existing channels; Normalize divides by the sum of the weights **actually used**; a zero sum raises an error.
- The docs give no default for Weights; Rec.709 (+ alpha 0) is used.

Note: this is the first combo in the package with `{"default": ...}` (the first menu item is sgi, the default is hdtv). ComfyUI supports this natively;
test_nodes / test_panel / the frontend test_panel.mjs all pass, but I haven't clicked through it in a real ComfyUI.

## Mirror → PCG_COPMirror (done)

Appended `number_and_offset` (planes / angle / offset / reverse) and `custom_planes`
(`plane_list` multi-line text, one plane per line: `angle offset [reverse 0/1]`) to the end of Mode. The old five modes (axis-aligned + Position) are kept.

Stated in the docs: Angle accumulates (plane k = k × Angle), multiple planes are applied in order, a positive Offset moves the mirror plane right,
180° + Reverse = 0°.
Decided here:
- Angle 0 = a vertical mirror plane, **left half mirrored onto the right** (bit-for-bit the same as the old left_to_right). The docs' wording is
  "Positive values mirror the left side of the image. Negative values mirror the right side",
  which is about the sign of the angle; it doesn't say which side is the source at 0° -- **this is the item most likely to disagree with Houdini; please check it in a real Houdini**.
- Offset units are image space (half the long side = 1).
- Multiple mirrors compose the coordinate mappings and sample only once (not resampled per plane); the result matches plane-by-plane but without extra blur.
- Houdini's Mirrors is a multiparm; here it is multi-line text.

## [C] Layer Merge → new node PCG_COPLayerCombine (done)

The existing PCG_COPLayerMerge (moves B's layers into A) is **untouched**. New node `PCG_COPLayerCombine` (nodes_cop2.py):
six optional inputs `source1..6`, `layer`, `operation` (add / average / multiply / min / max / over), `out_layer`.
copernicus_map.py's "Layer Merge" now points to it; icon `layer_combine`; panel spec in g7.

- Over: earlier inputs cover later ones; when not everything is RGBA, "copy the last input's pixels" per the docs.
- Resolution follows the first connected input, the rest are resampled; 1 channel broadcasts, 3 vs 4 is not guessed (raises).
- Not done: Space / Border / Filter / Clip by Data Window / Crop to Content (data window).
- Different from Houdini: a fixed 6 inputs (Houdini is unlimited); the output keeps the first input's other layers (our COPs are multi-layer).
- The new node's display name / whether it goes into the README node table: I didn't touch the README (the brief forbids it); left to the coordinator.

## Mutation testing

The script made 167 hand-written mutations of the 5 source files + node classes + mapping table (flip comparisons, swap branches, change constants, delete lines, swap arguments),
run in a copy of the workspace (source files untouched; `PCG_AUDIT_NO_BASELINE=1` skips the baseline section that needs .git).
8 survived the first round:

| Mutation | Handling |
|---|---|
| channel-toggle padding `[True]*C` → `[False]*C` | added test: 5-channel layer |
| crop `and not inside.all()` removed | equivalent (pure optimization), **removed the condition** |
| crop zeroing `where` → multiply by 0 | the original inf test was in the wrong place (pixels outside the window are never read); now puts inf on the window corner |
| crop mirror path without `check_res` | added test: exceeding MAX_RES raises |
| `kernel_from_image` radius +1 | equivalent output (an extra ring of 0 around the kernel); added a kernel-size assertion so it can't silently get slower / fall onto the FFT path |
| copy_transform overlay name-collision loop removed | the original test didn't include colliding layers; now Layers is left empty |
| over_last branch `sy` → `sx` | added test: over_last / under + non-uniform Scale |
| node source5 / source6 swapped | added test: over on inputs 4 / 5 / 6 |

The second round added 8 more; 1 survived (layer_combine doesn't read `layer`), test added. All killed in the end.
The hide / disable conditions in the panel spec can't be killed by Python tests; they were written by reading the code.

## Side findings / things to know

- **Behaviour differences between the code and Houdini (not changed)**: PCG_COPCopyTransform's old `over` runs opposite to Houdini's Over (see above);
  PCG_COPConvolve's preset `box3` is an unnormalized all-ones kernel (sum 9), you have to tick Normalize to get a mean blur;
  PCG_COPMirror's old five modes have Position in uv, which Houdini has no parameter for.
- PCG_COPComposite's `mask_layer` and PCG_COPConvolve's `kernel_layer / centered` are only read when the matching input is connected;
  the panel can't hide by connection state, so only the help says so.
- Regressions not run: test_prod_workflows.py (forbidden by the brief), test_terrain / test_erosion / test_aiterrain
  (they only use old composite / crop parameters, which the bit-for-bit baseline comparison already covers).
- Incident: midway through mutation testing I once ran `pkill -f mut.py` / `pkill -f test_audit_c1` in the shared scratchpad
  to clear my own timed-out processes. The command killed my own shell first; but if another agent had a process with `mut.py` in its command line at the time,
  it would have been terminated too. After that I switched to my own subdirectory and stopped killing processes by name.
