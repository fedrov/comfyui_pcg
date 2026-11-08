# s6_attrib_adjust audit notes

## Overall trade-off: why new nodes rather than changing PCG_AttribAdjust

PCG_AttribAdjust is this plugin's own four-stage pipeline "initialize → text operation stack → Remap → post-process", merging Houdini's
three Adjust SOPs into one node. Its Initialize menu (off/constant/random/attribute/noise/expression)
is not the same thing as Houdini's Operation × Pattern Type: there is no Set Initial, no four Range Values modes,
no discrete value table, and Distribution is Attribute Randomize's gaussian/power. Filling the gaps on top of it would mean appending at least
Operation, Pattern Type, Range Values, Value Distribution, Outlier ×6, Stepping, a value table, Blend and so on --
twenty-odd parameters -- and two coexisting semantics, "Initialize=random" and "Pattern=Random" -- the panel would get out of hand and it would be unclear
which overrides which. So, following brief [C]: **the original node is left untouched**, and new Houdini-semantics nodes are added (nodes_sop2.py, implemented in
geo/attribadjust2.py); in sop_map.py Float / Integer (/ Vector / Color, see below) now point to the new nodes;
"Attribute Remap" still points to PCG_AttribAdjust (its Remap stage).

The four new nodes share: the Noise Pattern tab (NoiseSpec), the Range Values group (ScalarSpec), Operation combining
(combine), Blend (blend_weights), the discrete value table (parse_value_list / pick_specific).

## Attribute Adjust Float → new node PCG_AttribAdjustFloat

Done:
- Blend (Constant / Use Attribute) + Blend Attribute (clamped to 0..1).
- Adjust Value toggle (off = post-process only).
- Operation: Set Always / Set Initial / Add / Subtract / Multiply / Minimum / Maximum. When the attribute doesn't
  exist yet, the adjustment value is written directly, per the docs' "all operations have the same effect" (Set Initial writes too).
- Pattern Type: Constant / Random / Noise / Attribute. Attribute mode has Scale / Offset / Apply Both
  (in the Float docs; the Integer docs say it doesn't have them, but we kept them for Integer too, as an extension). The adjustment attribute can name a component (v.z).
- Range Values: Min/Max, Min + Range Length, Middle ± Range Length (half-width = half the length, unlike Attribute
  Noise's full width, which the docs point out specifically), Specific Values.
- Value Distribution: Uniform / Uniform with Remapping (Remap Ramp as text) / Uniform with Outliers
  (Outlier Percent, Outlier Range, Additive / Multiplicative, Above Max / Below Min / Both,
  Outlier Seed, Outlier Attribute).
- Enable Stepping + Step Size.
- Specific Values table: Houdini's Number of Values multiparm (Value Type Constant / List of
  Values, Value, Weight, the `min-max:step` syntax of Value List) is written as multi-line text, one group per line, `w=weight` at the end of the line.
- Randomization By: Element Number / Custom Attribute (error if the attribute isn't found) + Seed.
- Noise Pattern: Noise Type, Location Attribute, Element Size, Element Scale (xyz), Offset (xyz),
  Fractal Type None/Standard/Terrain/Hybrid, Max Octaves, Lacunarity, Roughness.
  Noise Type gains Manhattan Cellular F1/F2-F1, Chebyshev Cellular F1/F2-F1 (attribnoise.worley
  gained a metric parameter; the old NOISE_TYPES tuple is unchanged and a separate NOISE_TYPES_X was added, so that the menus and panel specs of Fracture Detail / the old
  Attribute Adjust don't get out of sync).
- Post-Process Minimum / Maximum (one "☑ Label [value]" row).
- An attribute name with a component suffix (v.x / v[1] / Cd.g) changes only that component; pointing at a vector attribute without a component adjusts the **length**
  (docs: "for vector attributes the length can be adjusted"); zero vectors stay zero.

Still different from Houdini / not made clear by the docs, so decided here:
- Noise's u = (noise + 1)/2, not flattened to a uniform distribution, so Noise + Min/Max values cluster in the middle of the range;
  the docs don't say whether Houdini equalizes it.
- Uniform with Remapping: the docs say "first generate uniform values in −1..1, then map them to the range through the Remap Ramp", but don't give the ramp's exact
  coordinate convention. Here the horizontal axis = u (0..1, left = Min), the vertical axis 0..1 is then stretched to [Min, Max].
- Outlier: outliers are taken uniformly within the extension band; Both puts half on each side (the docs give no ratio). Multiplicative is interpreted as "extension bandwidth =
  (Outlier Range − 1) × range length" -- the docs only say "multiplied onto the endpoints"; multiplying the endpoint values directly would never extend the lower end of [0,1],
  which doesn't seem intended; with Range < 1 the bandwidth is clamped to 0. The Outlier Extent menu text only lists Below Min Value / Both,
  but an image file name contains "above", so Above Max Value was added and made the default -- this item is inferred.
- Stepping: the grid starts from Min (Integer docs example: 1..9 step 2 → 1 3 5 7 9), using "split evenly into m+1 bins and take bin k"
  instead of round, so the endpoints and inner steps are equally likely; the Float docs only say "quantized to integer multiples of Step Size", without an anchor,
  so it is unified with the Integer example. With Stepping on, outliers are quantized by round.
- Value-table weights: interpreted as "probability of a group being picked ∝ Weight, uniform within the group" (the docs' "expanded values share the same Weight" can be read two ways).
  Noise mode uses a single u to pick a value, so discrete values appear in patches.
- Operation menu order: Set Always is first as the default (in ComfyUI, dropdowns default to the first item, which is better for workflow compatibility);
  in Houdini Set Initial comes first; the default Noise Type = Perlin and default attribute name pscale were our own choices.
- Attribute Class menu point / prim / vertex / detail (Houdini's order differs; no effect).

Not done (with reasons):
- Unit Settings (unit conversion presets) -- the plugin has no unit system.
- Use VEXpression -- a wrangle expression could be hooked up, but Houdini's VEXpression "overrides any parameter", too large a semantic surface;
  not done this round.
- Animate Noise / Pulse Duration, Warping (Lattice / Gradient Warp, Accumulate) -- our noise library has neither
  lattice nor gradient warp, and we don't fake it.
- Noise Types Fast, Sparse Convolution, Alligator, Perlin Flow -- the noise library doesn't have these algorithms.
- Default Value -- Geometry has no concept of attribute default values.
- The Enable Post-Process master toggle -- replaced by the separate toggles on Minimum / Maximum.

## Attribute Adjust Integer → new node PCG_AttribAdjustInteger

Same code as Float (integer=True). Differences:
- No Blend (not in the Integer docs).
- Random integers are uniform over [Min, Max] inclusive; without Stepping it is equivalent to step 1; when the Middle ± Range Length half-width is fractional
  it is shrunk inwards (0 ± 1.5 → -1..1; the docs example 0 / 2 → -1..1 holds under this).
- Outliers are at least 1 outside the range (otherwise rounding would put them back on the endpoint and they wouldn't be outliers).
- Rounded at the end; new attributes are int32, existing float attributes stay float32 but with integer values.
- Min / Max / Value / Range Length / Step Size are INT controls.

## Mutation testing (Float / Integer)

46 mutants, 14 survived the first round; handled as follows:
- Killed by new tests: negative weights raise an error, Element Size not used, Offset added before dividing, integer shrinking for Middle ± (together with the next item),
  step floating-point error (0.3/0.1), extension bandwidth clamped to 0, integer Below Min outliers, Stepping quantization of outliers, Blend attribute clamping,
  the Integer node rounding on a float attribute, menu routing of manhattan_f2f1.
- Proven equivalent, code removed: a second ceil/floor on integers in `_fit` (range_bounds already shrinks them, and Min/Max are INT anyway),
  the `outlier_percent > 0` guard (with percent 0 the mask is all false anyway), np.where for adjusting the length of zero vectors (when full is 0 the product
  is 0 anyway).
- To be covered by the Vector node: NoiseSpec.sample's salt (Float/Integer only use salt 0).

## Attribute Adjust Vector → new node PCG_AttribAdjustVector

Done:
- Adjustment for: Direction & Length / Direction Only / Length Only.
- All 11 Operations: Set Always / Set Initial / Set / Add / Subtract / Multiply / Minimum / Maximum /
  Rotate / Spread / Interpolate. Validated against the combinations the docs allow (Set* / Multiply / Min / Max only for Direction &
  Length, Rotate / Spread / Interpolate only for Direction Only, Length Only only Add/Sub/Mul/Min/Max);
  choosing a disallowed combination **raises an error** rather than silently switching the operation; not validated when Adjust Value is off.
- Adjust With: Constant / Random / Noise / Attribute.
- Range Values for vector adjustment values: Positive (0..Amplitude) / Zero Centered ((u−0.5)×Amplitude, per the docs' wording;
  ±0.5 at amplitude 1) / Min/Max (per component) / Specific Values (one x y z per line, w= at the end). Amplitude Scale
  per axis. Random / Noise use independent random streams / noise slices for the three components (different salt).
- Scalar adjustment values (the length for Length Only, the angle for Rotate / Spread, the Bias for Interpolate): Constant uses one
  "Value / Angle / Bias" parameter; Random / Noise use the Float node's whole Range Values group (including Distribution,
  Outliers, Stepping, value table).
- Axis of Rotation, Goal Direction: Constant Value / From Attribute (in Houdini both are called Axis Attribute;
  here split into two parameters, axis_attribute / goal_attribute).
- Pre-Process: Enable, Overwrite Initial Value (Constant / Normal Attribute (computed on the fly by Attribute Class with
  the Normal SOP's algorithm) / Vector Attribute), Reverse Direction, Make Vectors Unit Length, Length Scale.
  Once an initial value has been written, Set Initial no longer overwrites it.
- Post-Process: Blend (Constant / Use Attribute) + Blend Type (Linear / Spherical: spherical interpolation of direction,
  linear interpolation of length), Length Scale, Minimum / Maximum Length, Make Vectors Unit Length, Length output attribute.
- Random (Randomization By / Custom Attribute / Seed) and the Noise Pattern tab as in Float.

Still different from Houdini / decided here:
- Set and Set Always: the docs' two descriptions are almost identical and no difference can be seen, so they are treated as the same operation.
- Rotate / Spread / Bias Min / Max / List are three independent parameter sets in Houdini (Rotate Angle Min…); here they share
  the scalar Range Values group, labelled "Min Value". Also, Houdini's Min + Range Length / Middle ± /
  Distribution are only for Length Only; ours can be used for angle and Bias too (a superset).
- Spread's azimuth: the docs only say "lands on the cone surface", not how the azimuth is chosen. Here a random azimuth is taken by Randomization By + Seed.
- Interpolate's Bias is clamped to [0,1]; for opposite directions (180°) there is no unique great circle, so it degrades to linear interpolation and then normalizes.
- The docs say Attribute mode is only for Length Only; our Direction & Length / Direction Only Add/Sub can also use
  a vector attribute as the adjustment value (extension). Single-component attributes are spread to three components.
- Zero vectors: stay zero under Direction Only / Length Only / Min Length (the docs' wording).

Not done: Component Scope, Type Qualifier, Default Value (no corresponding concept), Use VEXpression, Animate Noise,
Warping, Fast / Sparse Convolution / Alligator / Perlin Flow noise (as for Float). Min/Max Value Scale
(per-axis scaling of the bounds) not done -- our Min / Max are already per-axis vectors.

Mutation testing: 26, 9 survived the first round. Killed by new tests: spreading single-component attributes, slerp degenerating on opposite directions (the value, not just finiteness),
the along-axis term of Rodrigues, Set Initial not overwriting after an initial value was written (the old test's expected value happened to equal the default constant; the constant was changed),
Spread's azimuth honouring Randomization By. Proven equivalent, code removed: the zero-vector np.where in Direction Only (L = 0 multiplies out to 0 anyway),
the branch in Spherical Blend falling back to linear when one end is zero (_unit gives a zero direction and slerp degrades to linear exactly), the zero-vector branch of Min Length.
Equivalent, not removed: replacing combine(..., existed=True) in Length Only with existed -- when the attribute doesn't exist the length is 0 and d is 0 too,
same result; True is kept so it reads clearly as "the length always exists". NoiseSpec's salt is killed by Vector's three-component noise test.

## Attribute Adjust Color → new node PCG_AttribAdjustColor

PCG_Color is the Color SOP (plus an "adjust" HSV mode), with a single Color Type menu, not the same thing as Operation × Pattern Type;
it stays as the counterpart of "Color", and sop_map's Attribute Adjust Color now points to the new node.

Done:
- Blend (Constant / Use Attribute). **Blend comes last** (after correction and post-process); Blend 0 = input unchanged
  (even Overwrite Initial is blended away) -- docs: "0 means no adjustment, output the original value".
- Pre-Process: Delete All Existing Color Attributes (deletes attributes with the same name on other classes), Overwrite Initial Color,
  Initial Color From: Constant / Color Attribute / Float Attribute (first component spread to grey).
- All 11 Operations: Set Always / Set Initial / Add / Subtract / Multiply / Overlay / Screen / Hard Mix /
  Difference / Minimum / Maximum.
- Pattern Type: Constant / Random / Noise / Color Attribute / Remap Attribute (Source Attribute + Compute
  Range or a manual Source Range + Color Ramp) / Bounding Box (projected along Direction, normalized by the min/max of all elements' projections,
  then through the Color Ramp).
- Random / Noise Range Values: Min/Max (Color Space RGB / HSV, each channel random independently) / Color Ramp (one u
  looks up the ramp) / Specific Colors (Color Scheme: Constant / Complementary / 2 Analogous / 4 Analogous /
  Triadic / Tetradic / 5 Shades / 5 Tints, derived from the base colour with equal weights; or Custom: one r g b + w= per line).
- Color Correction: Hue Shift, Saturation, Value, Brightness, Contrast, Gain, Gamma.
- Post-Process: Minimum / Maximum, Complement Color.
- Randomization By / Seed and the Noise Pattern tab as in Float.

Not made clear by the docs, so decided here:
- The docs give no Overlay / Screen formulas: the usual layer blend formulas are used, Overlay splitting light/dark by the **original colour**. Hard Mix follows the docs
  (a + b ≥ 1 → 1). Difference follows the docs' wording "adjustment value minus original value" = b − a, **no absolute value** (common software's
  Difference is |a − b|; if Houdini measures as absolute, this line needs changing).
- The docs give neither the order nor the formulas of Color Correction: HSV (hue + Shift, saturation × and clamped to 0..1, value × Value then +
  Brightness) → RGB × Gain → (c − 0.5)·Contrast + 0.5 → c^(1/Gamma) (Gamma > 1 brightens, matching the docs' description).
  When everything is at default it is skipped entirely, with no HSV round trip, guaranteeing bit-identical output.
- Min / Max in HSV space: the three components are interpolated as (hue 0..1 around the circle, saturation, value). Houdini has a Min/Max parameter pair for each of
  Red/Green/Blue or Hue/Saturation/Value; here they share the two colour rows min_color / max_color.
- Color Scheme in Houdini is "a preset menu that fills the multiparm"; here it is a menu that stays in effect + a Custom mode. Triadic is set to
  ±120° (the docs summary's "same as 2 Analogous" doesn't make sense); the docs don't give the step for 5 Shades / 5 Tints, so value /
  saturation are multiplied by 1 .8 .6 .4 .2 in turn; Distance only applies to the hue schemes; Tetradic = 0, +d, 180°, 180°+d.
- Remap Attribute's Compute Range only looks at elements in the group (consistent with PCG_AttribAdjust's auto range);
  Bounding Box uses all elements (it is a "bounding box"). A zero range takes the left end of the ramp.

Not done:
- Color Map (texture sampling: Image Path, UV, Wrap Repeat/Streak/Decal …) -- on the geometry side Attribute from Map
  (PCG_AttribFromMap) does this, not duplicated here; doing it would mean bringing over Translate/Rotate/Scale/Pivot/Border Color/
  Source Color Space too; not done this round.
- Line / Radial: the docs say these are gradients drawn by dragging handles in the viewport, with no numeric parameters; we don't fake it.
- "By attribute" versions of the Color Correction items (Hue Attribute etc.), Delete All Randomization Attribute,
  Component Scope RGB/HSV, Relative to Color, the Color Palette button, Default Value, Type Qualifier.
- Noise's Color Ramp / Noise Pattern dropdown (mentioned in the docs) -- our Noise goes through the Range Values set
  (Min/Max / Color Ramp / Specific), which covers the functionality.
- The docs' Attribute Class includes detail -- we support it too (point / prim / vertex / detail).

Mutation testing: 23, 5 survived the first round. Killed by new tests: clamping after boosting saturation, the order of Value and Brightness,
the zero-range guard, Float Attribute taking the first component when given a vector attribute, Blend mixing back to the input rather than the initial colour after Overwrite.
Proven equivalent, code removed: the 0..1 clamp in _fit01 (ramp.apply after it clamps anyway).

## Attribute Randomize → appended to the existing node PCG_AttribRandomize

Done (new widgets all optional, default = old behaviour; menus only appended to at the end):
- Operation (combine) gains Minimum / Maximum. When the attribute doesn't exist the generated value is taken directly (comparing with 0 is meaningless;
  the docs say Set Value should be used when the attribute doesn't exist).
- Distribution gains: Constant Value, Two Values, Uniform (Discrete), Exponential, Log-Normal,
  Cauchy-Lorentz, Custom Discrete, Inside Sphere. Parameters reused: Constant / Value A = Min, Value B = Max,
  Middle Value = mean (panel label changed to Middle Value), Scale / Spread Around Middle = stddev (label changed to
  Scale Around Middle); new prob_b (Probability of Value B), step_size, value_list (the value table for Custom Discrete,
  same syntax as Attribute Adjust's).
- Global Scale (multiplied onto the generated value before Operation; orient quaternions are not multiplied).
- Panel: the hide conditions of Min / Max / Middle / Scale updated for the new distributions (layout only).

Not made clear by the docs, so decided here:
- Log-Normal's Spread Around Middle is taken as the standard deviation in log space: median × exp(σ·z).
- Cauchy: the docs say "can be limited with Min Value / Max Value" without saying whether it clamps automatically or has a separate toggle; here it is **not clamped**
  (Min / Max are hidden under Cauchy); to limit it, connect a Clamp.
- Uniform (Discrete): inclusive, grid starting from Min, all steps equally likely (same scheme as Adjust's Stepping).
- Custom Discrete with multiple dimensions draws each component independently (the docs don't say how multiple dimensions are handled).
- Inside Sphere is placed in Distribution (value mode), dimension taken from Dimensions: uniform direction × radius u^(1/dimensions).
  In Houdini Inside Sphere shares the Cone Angle / Direction / Bias parameters with Direction or Orientation; here
  only "the whole unit sphere" is done.

Not done:
- Custom Ramp (inverse-CDF sampling using the ramp as a probability density) -- not done this round.
- Fraction Attribute -- distributions like Gaussian need an inverse CDF (erfinv), which numpy doesn't have, and scipy isn't pulled in; doing it only for some distributions
  would make the toggle's semantics inconsistent, so none of it is done.
- Group Type, Visualize as Points, Type = String (sampling from a string list).
- Direction or Orientation's Bias Toward Direction.

Differences from Houdini (not changed, listed here):
- When the Seed Attribute isn't found we **raise an error**; the Houdini docs say "if not found, the element number is used".
- Our power distribution and Value Type (value/direction/orient) + Shape menu are our own extensions, kept.

Mutation testing: 14, 1 survived (the guard for Step Size 0: without it int(inf) raises OverflowError, and the old test only checked "raises an exception").
The test now requires ValueError, which kills it. Also, the old `else: raise` (bad distribution name) in value mode was moved to a single validation at the start of the function,
removing an unreachable branch.

## Attribute Noise → appended to the existing node PCG_AttribNoise

Done (new widgets all optional, default = old behaviour; menus only appended to at the end):
- Operation gains Set Initial (leave the attribute alone if it already exists), Minimum, Maximum (all respect Component Scope; when the attribute doesn't exist
  the noise is written directly). The existing "set" is Set Always.
- Range Values gains Negative, Min/Max, Min + Range Length, Middle ± Range Length (**full width**: Middle ± Length;
  the docs point out specifically that it differs from Attribute Adjust's half-width) + Min Value / Max Value / Middle Value / Range Length.
  Positive already existed (token zero_to_one).
- Manhattan Cellular F1/F2-F1, Chebyshev Cellular F1/F2-F1 appended to the end of the Noise Type menu (attribnoise.NOISE_TYPES_X).
- Blend Attribute (when non-empty, used per element as Blend, clamped to 0..1; Houdini has a Blend menu Constant / Use Attribute;
  here "name non-empty" replaces the menu, to avoid adding another dropdown to the existing node).
- Attribute Type: Auto (old behaviour: guess the component count from the existing attribute / name) / Float (one noise spread over all components) / Vector
  (new attributes get 3 components). Auto is not a Houdini option; it exists so that default = old behaviour.
- Value Correction gains Gamma and Contrast (in 0..1 space, after Bias/Gain: first clamp to 0..1, t^(1/Gamma), then
  (t − 0.5)·Contrast + 0.5; skipped when both equal 1, bit-identical). The docs give no formula; Gamma > 1 brightening matches the docs' description.
- Post-Process gains Make Vectors Unit Length and Recompute Normals (after the change, if N already exists on point / vertex / prim / detail,
  it is recomputed on that class with the Normal SOP's algorithm).

Not done:
- Output Raw Value: the docs say that with it off "the distribution is more uniform" -- Houdini flattens the noise distribution by default; ours has always been raw. Doing it would need
  a CDF table for each noise × fractal; not done this round. So **our Attribute Noise equals Houdini's result with Output Raw
  Value on** (distribution concentrated in the middle).
- Per Component Amplitude Scale / Min/Max/Middle/Range Length Scale, Element Scale (we have per-axis
  Element Size).
- Lattice Warp / Gradient Warp / Accumulate, Flow Rotation, Distortion, Stretch, Droop, Worley Details,
  Perlin Cloud / Simplex Cloud / Fast Simplex Cloud, Fast / Sparse Convolution / Alligator / Perlin Flow --
  the noise library doesn't have these algorithms; we don't fake them. Our Warp (domain warp distance) is our own extension, kept.

Mutation testing: 16, 2 survived, both killed by new tests: the 0..1 clamp before Gamma (the Terrain fractal goes outside [-1,1], and a root of a negative base gives
nan), Component Scope of Min / Max (the old test compared Maximum against 0.1, and the turned-off component's delta=0 happened to be swallowed by max;
changed to Minimum).

## Regression / test counts

- test_audit_s6_attrib_adjust.py: 261 checks. "Bit-for-bit identical to before the change at default values" uses 20 digests from before the change (9e3fb92)
  (PCG_AttribAdjust 3, PCG_AttribNoise 7, PCG_AttribRandomize 5, PCG_Color 5) hard-coded in GOLDEN, independent of git.
- Related existing tests: test_audit_c3_noise 193, test_geoattrs 166, test_sequence 121, test_workflows 100,
  test_params 148, test_nodes 42, test_panel 42, test_sop_map 11, test_panel.mjs 230, test_icons.mjs 23, all green.
  No hard-coded numbers in existing tests needed changing because of the appended widgets.

## Issues found in passing / things the coordinator should know

- The four new nodes' run() uses `**kw` (there is precedent in nodes_sop2.py), so test_nodes' "run() accepts all inputs" check
  is a no-op for them; the new nodes' parameters are each covered by run() calls in test_audit.
- PCG_AttribRandomize: raises an error when the Seed Attribute (id_attribute) isn't found; the Houdini docs fall back to the element number. Not changed.
- In PCG_AttribAdjust (the merged version), Distribution's gaussian / power, Normalize and Round Mode are not Houdini parameters of the Adjust
  family -- now that there are Houdini-semantics new nodes, it is kept as our own "four-stage pipeline + operation stack" node;
  in sop_map only Attribute Remap still points to it.
- PCG_Color's Attribute Class menu has no detail (Houdini does); the new Attribute Adjust Color does.
- In the PCG_AttribNoise panel, ramp_mode has no menu label (it was like that before this package); this package's panel checks only cover the dropdowns it touched.
