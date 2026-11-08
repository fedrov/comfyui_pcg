# c2_color_key (pcg100): COP keying / color-correction batch

When I took over, the workspace had the previous agent's uncommitted changes (a new colorkey.py module, 6 new nodes, modes added to 4 old nodes, panel /
icons / mapping table), with no tests and no notes. After reading it section by section and checking it against the docs I **kept** its structure and fixed the following:

- Three syntax errors in the panel spec (an extra `},` after g7 Illegal Pixel, bare ASCII quotes in g7 Histogram's help,
  an extra `},` after g8 Random) -- the whole package couldn't be imported at the time.
- Compare's tolerance semantics were inverted (see the Compare section below); rewritten.
- Redundant code exposed by mutation testing was removed / simplified (see "mutation" in each section); Mono to HeightField's docstring was changed from "docs: multiply first, then add"
  to "the docs don't say which comes first" (the docs only say scaling and shifting).
- In test_panel.py, "367 nodes take over the panel" changed to 373 (6 new nodes). **If other packages also add nodes this number will conflict;
  set it to the final node count when merging.**

All 10 doc pages were re-checked with WebFetch (chromakey / despill / illpixel / randomrgb / equalize /
histogram / compare / monotorgb / monotoid / monotoheightfield). These SideFX pages **only say what the parameters do; they give no
formulas and no defaults**, which is why everything below marked "decided here" exists.

Tests: `test_audit_c2_color_key.py`, 289 checks. "Bit-for-bit identical to before the change at default values" is checked by loading the baseline's old pixel.py / solve.py via `git show a9e114d:…`
as modules and comparing bit-for-bit with the new code (old modes of chroma_key, illegal_pixel, random_layer,
segment_by_value).

---

## Chroma Key → PCG_COPChromaKey (modes added)

Done:
- `method` (appended at the end, default `distance` = our original YCbCr chroma distance, which Houdini doesn't have): `chromakey`
  (Houdini's legacy Chromakey: hue / saturation / luminance ranges, each multiplied by a weight, matte = 1 − product),
  `channel_separation` (Screen Color's dominant channel minus the max of the other two, then through Threshold / Width).
- `invert`, `hue_min/max`, `sat_min/max`, `lum_min/max`, `threshold`, `width`,
  `hue_rolloff / sat_rolloff / lum_rolloff`, `interpolation` (linear / ease_in / ease_out / smooth /
  gaussian), `preview`, `preview_color`. All appended at the end.
- Panel: Tolerance/Softness, the HSV ranges + Rolloff, and Threshold/Width are hidden by Method; key_color's label changed to
  Screen Color (all three modes read it: distance as the key color, channel_separation as the screen color, despill to find the dominant channel, so it isn't hidden).

Decided here (not specified by the docs):
- Formulas for the five Interpolations (x = distance outside the range / Rolloff): linear 1−x, ease_in 1−x², ease_out (1−x)²,
  smooth smoothstep(1−x), gaussian exp(−4.5x²) cut to 0 at x ≥ 1 (**a 0.011 step at the Rolloff edge**).
- Luminance uses Rec.709; a hue range with Min > Max wraps around 360°; width ≥ 360 is the full circle.
- Channel Separation formula: s = (c[k] − max(others)) / (the same difference for the screen color itself), matte = 1 − s,
  then fit to [Threshold − Width/2, Threshold + Width/2]; with Width = 0 only matte > Threshold (strict) is kept.
- Preview: color · matte + Preview Color · (1 − matte). The docs say "colors the key result with Preview Color
  instead of keying the pixels out"; the blend is our choice.

Still different from Houdini:
- No Signature (our layers have no type signature), no eyedropper.
- Houdini has a separate matte output; we still write to `alpha_layer` (panel label changed to Matte Layer).
- Despill Amount is our extension and is kept; in Houdini despill is a separate Despill node (see below).

## [C] Despill → new node PCG_COPDespill

Chroma Key's despill is not the same thing as Houdini's Despill (the latter outputs no alpha and has Bias / Luminance), so per the [C] rule
Chroma Key is left alone and a new node was added; copernicus_map's Despill now points to it.

- Parameters: mask, spill_color, bias, luminance, bias_layer / mask_layer (instead of Houdini's bias / mask
  inputs, multiplied per pixel), out_layer, spill_layer (Houdini's spill output).
- Formula (not given by the docs; the standard approach that matches the parameter descriptions): k = Spill Color's largest channel, the other two channels a, b (in RGB order),
  limit = a·(1−Bias) + b·Bias, c[k] = min(c[k], limit). For green despill Bias 0 leans red and 1 leans blue, matching the docs; for a pure color
  (a = b) Bias has no effect, also matching the docs' "no visible change for pure colors".
- Luminance: each of the three channels gets back Luminance × w[k] × the removed amount (Rec.709 weights); at 1 the luminance returns exactly to the original.
- Decided here: Bias / Luminance default to 0.5 / 0; Bias × Bias Layer and Mask × Mask Layer are clamped to 0..1;
  the spill layer does not include the luminance added back; single- / two-channel layers raise an error.

## Illegal Pixel → PCG_COPIllegalPixel (modes added)

Done: `mode` (default `replace` = the original three replacement values + Clamp Negative, which Houdini doesn't have) + Houdini's
blend / zero / highlight / isolate; `highlight_color`, `detect` (nan / inf / nan_inf / custom),
`rule` (less / less_equal / greater / greater_equal / equal), `value`. The panel hides by mode.

Decided here:
- Bad pixels are judged per **pixel** (any channel hit); the four Houdini modes process whole pixels; the report gives the `flagged` pixel count.
- blend: equal-weight average of good pixels in the 8-neighbourhood, filled inward ring by ring; an all-bad image is filled with 0. The docs only say "blends the surrounding pixels".
- highlight / isolate set alpha to 1 on RGBA layers; isolate also uses Highlight Color (the docs mention it only under highlight).
- Custom's comparison value: the docs **don't list this parameter** (only Rule); we added `value` (default 0).

Known limitation: with Detect = custom, unflagged NaNs remain, and blend will treat them as good pixels in the average (the result is NaN).
To handle both, chain two nodes.

## Random RGB → PCG_COPRandom (partial)

Done: `range_values` (default `shared` = the original single Min/Max pair shared by all channels) + Houdini's `min_max`
(per-component Min/Max, `color_model` RGB / HSV, hue in degrees for HSV), `color_ramp` (one uniform number through a ramp),
`specific_values` (`colors`: `r g b [weight]; …`, drawn by weight); `zero_negative_ids` (id mode only).
The last three modes always output RGB, with an extra constant-1 alpha when Channels = 4. The random numbers use the same hash as the shared mode (the min_max mode
is just min + u·(max − min); the test checks u directly).

**Not done**:
- The Color # scheme menu (Constant / Complementary / 2 Analogous / 4 Analogous / Triadic / Tetradic /
  5 Shades / 5 Tints), Angle, Distance, Color Palette, Number of Colors -- the docs don't say how these schemes are derived from the
  base color (the Triadic description is even the same as 2 Analogous), and Houdini has one menu per color, which our single string parameter
  can't express; forcing it would be "looks right but isn't".
- Relative to Color (the docs only say "the range is relative to this color", not how in RGB / HSV).
- Time (the docs only say "also controls the randomness", not how it is folded into the seed; our rand_seed is enough).
- The min / max / ramp / seed inputs (not added as layer-name parameters; the seed input corresponds to our existing id mode).

## [C] Equalize → new node PCG_COPEqualize

Our COP Histogram's equalize is histogram equalization; Houdini's Equalize is a min / max / average range remap,
so a new node was added and copernicus_map points to it.

- Equalize By (five modes), Fit Method (two), Luminance Type (14; the three weight sets are verbatim from the docs), Black / White /
  Target Average, Red/Green/Blue/Alpha toggles, Mask + Mask Layer, Active Layer (> 0.5, verbatim from the docs).
- Decided here: the statistic is measured as **one number** per Luminance Type, and all selected channels use the same coefficients (per-channel stretching would shift hue
  and make Luminance Type meaningless); when the denominator is 0 (stretch on a constant image, scale on an all-black image) that step doesn't scale; single-channel layers are treated as gray,
  2 channels padded with 0; the Alpha mode on a layer without a 4th channel raises an error; for layers with 5+ channels, channels from the 5th on have no toggle and always follow; Luminance Type
  defaults to HDTV, Target to 0.5.
- Not done: Toggle RGB (one button toggling all three, pure UI; the three toggles are all there).

## [C] Histogram → new node PCG_COPHistogramPlot

Our COP Histogram does equalization / matching; Houdini's draws the histogram as an image, so a new node was added and copernicus_map points to it.

- Mode (colored_bars / separate_bars / graph), Buckets, Minimum / Maximum, Outside Values
  (discard / clamp), Scale, four channel toggles, Active Layer (≥ 0.5, verbatim from the docs; differs from Equalize's >).
- The second output counts follows the docs: width = Buckets, height 5, R/G/B/A counts bottom to top, top row column 0 is the number of pixels counted.
- Decided here: a value exactly equal to Maximum goes into the last bucket; NaN is not counted; the "total" is the number of pixels considered (including those Discarded);
  per-bucket value = pixels in bucket / total × Scale; column x maps to bucket floor((x + 0.5)/W · Buckets); separate_bars'
  output layer alpha is 1; Buckets / Scale default to 256 / 10; for 5+ channels only the first 4 are counted.

## [C] Compare → new node PCG_COPCompareMask

Our COP Compare is SSIM / PSNR image difference; Houdini's is a boolean mask, so a new node was added and copernicus_map points to it
(the Error row still points to the old PCG_COPCompare, which is not this package's).

- True If (six modes), Components (all / any), Falloff (none / linear / elendt), Comparison Value (used when Layer B
  is empty), Tolerance, Tolerance Layer.
- **The semantics of the implementation I took over were wrong**: `>` under Linear was d/tol (passing pixels were also below 1), and `>=` / `<=` used the complement, so the tolerance
  ran the wrong way. The docs say Falloff handles values that "**fail** the comparison but fall within the tolerance", so it now works as: passing pixels are always 1, and the tolerance only adds a ramp on the
  failing side -- `==` two-sided (1 − |d|/tol), `>` / `>=` one-sided (1 + d/tol), `<` / `<=` with the sign flipped, `!=` is the complement of `==`.
- Decided here: the tolerance also applies in the None mode (a hard cut at the tolerance edge; `|d| ≤ tol` and `d ≥ −tol` are included); `>=`'s tolerance is the same as `>`
  (the two only differ when tol = 0); `!=`'s tolerance = the complement of `==`'s; Tolerance Layer **replaces** Tolerance, and for multiple channels
  only channel 0 is used; All / Any take the min / max over soft masks.
- Different from Houdini: for Elendt the docs only say "an S-curve smooth at both ends"; smoothstep is used instead, so mid-range values will differ slightly from Houdini.

## [C] Mono to RGB → new node PCG_COPMonoToRGB

Channel Convert's mono_to_rgb copies channels; Houdini's goes through a ramp, so a new node was added and copernicus_map points to it.

- Compute Range, Input Min/Max, Output Min/Max, Scale by Value, Outside Range (clamp / repeat),
  Ramp (+ ramp_mode interpolation), Ramp Layer (instead of the ramp input).
- Decided here: Output Min/Max applies after the ramp (color = OutMin + ramp(t)·(OutMax − OutMin)); the docs say
  "before the ramp is applied", i.e. translate and scale the ramp itself, which is the same thing for the result; Scale by Value multiplies the **unclamped** t;
  Repeat keeps only exactly t = 1 at the end and takes the fractional part otherwise (t = 2 → 0); Ramp Layer takes row H//2, with the endpoints at the leftmost /
  rightmost pixels, linear interpolation; 1- / 2-channel layers are treated as grayscale (channel 0), 4 channels use only RGB; with Input Max = Min, t = 0.
- Not done: VDB / attribute inputs (the plugin has none).

## [C] Mono to ID → `cast` added to PCG_COPSegmentByValue (partial)

Segment by Value's three modes are binning + connectivity, not type conversion. Of Houdini's three modes only Cast means anything on our float32 layers,
so it was added as Segment by Value's 4th mode (end of the menu): truncate toward 0, no renumbering, no connectivity, count = number of distinct
ids. The panel hides bins / step / connected / connectivity in the cast mode.

**Not done**: Safe Unpack (corresponds to VEX `unpack_intfromsafefloat`; the docs give no bit layout, so guessing would be just for show), Bitwise
(reinterpret the float's bits as an int -- our layers store float32, so storing the resulting int back as float32 loses precision and the result is irreversible, which defeats
the point of this mode). copernicus_map's Mono to ID still points to PCG_COPSegmentByValue.

## [C] Mono to HeightField → new node PCG_COPMonoToHeightField

PCG_COPLuminance is a luminance conversion, so a new node was added and copernicus_map points to it (HeightField to Mono is not this package's, untouched).
height = value × Height Scale + Height Offset, written to the height layer (default). The docs don't say whether multiply or add comes first; we multiply first, then add.
Houdini sets the layer's Type Info to height; our layers have no type metadata, so we rely on the layer-name convention.

---

## Mutation testing

The script works at token level (comparison operators, arithmetic operators, min/max, any/all, numeric constants, if conditions replaced by False); scope = all of colorkey.py
+ the lines in pixel.py / solve.py changed relative to the baseline, 836 mutants in total; plus 23 hand-made mutations of the run wiring in nodes_cop2.py
(swapped argument order, replaced with constants). The first round was interrupted once by another agent's `pkill`; after fixing the code the whole round was re-run.

Survived the first round and got tests: the hard edge at Rolloff = 0, the width of hue wrap-around, matte exactly equal to Threshold at Width = 0,
Despill's channel-count check and Bias/Mask clamping, Histogram's Buckets = 1 / error message / binning with Min ≠ 0 /
no pixels in Active / column-to-bucket mapping, 5-channel layers (Histogram / Equalize), Compare's channel-count check (width ≠ channel count),
multi-channel Tolerance Layer, tolerance boundaries, Mono to RGB's Repeat (1.25 / 2), which row Ramp Layer takes / 2 channels /
RGBA / interpolation in the last segment, Specific Values with weights on some entries and not others plus a trailing extra semicolon, several errors distinguished by their message
(otherwise a ValueError numpy happens to throw later could make a "should raise" test pass), node wiring (sat_max, lum_max,
preview_color, Equalize's active_layer, Histogram's scale).

Code proven redundant and removed:
- The `continue` skipping the center cell in blend_fill (the center is a bad pixel with value 0 and count 0, so adding it changes nothing).
- Magnitude's `abs` special case for a single channel (sqrt(v²) is |v|).
- `np.minimum(…, n − 1)` for column → bucket and row → channel band in Histogram ((x + 0.5)/W·n is always below n).
- `np.clip` on the Ramp Layer index in Mono to RGB (with tc ∈ [0,1] floor never goes out of bounds); the Repeat condition simplified to
  a `t == 1` exception.

Survived and judged equivalent (56 in the second round, each one inspected):
- Default values of function parameters (nodes never use the geo functions' defaults; nodes always pass every argument): defaults of illegal_pixel / chroma_key /
  random_layer / equalize / histogram_plot / illegal_fix.
- `reshape(-1)` → `reshape(-2)`, `np.stack(…, -1)` → `axis=1` (identical on 1-D arrays), `np.pad` padding an extra ring at the end.
- `_vec(x, 3)` → `_vec(x, 4)`, `range(3)` → `range(4)` (the extra component isn't used), `[:min(C,3)]` → `[:min(C,4)]`
  / `[:max(C,3)]` (the next line resets alpha to 1, or the out-of-range slice truncates automatically).
- The specific negative number in `np.full(…, −1.0)`, hue difference `+180` ↔ `−180` (differ by 360, same after modulo), the fallback value in `np.where(pos, tol, 1.0)`
  (unused when pos is false), Ramp Layer's `row[:, :2]` / `repeat(…, 4)` / the upper bound −2 of `j` (interpolation weight 0).
- specific_values' `np.minimum(…, len(pal) − 1)`: only guards against rounding error in the cumulative weights, unreachable for normal input; kept as insurance.
- Things like `if total else ones_like` from the first round were already killed by the later tests (all red in the second round).

## Side findings (not this package's, not changed)

- copernicus_map's Error still points to PCG_COPCompare (SSIM / PSNR); whether that row matches the semantics of Houdini's Error COP
  is outside this package's audit scope.
- test_panel.py's total node count is hard-coded and will inevitably conflict when several packages add nodes in parallel; suggest not hard-coding it, or having the coordinator fix it once when merging.
- In the shared scratchpad directory other agents used files with the same names (mut.py / w0 / w1) and deleted them; this package's mutation scripts live under
  `scratchpad/c2_color_key_mut/`; suggest each package use a subdirectory named after the package.
