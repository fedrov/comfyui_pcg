# c3_noise (pcg100): Copernicus noise batch

All docs were re-checked with WebFetch: fractalnoise, worleynoise, cellularnoise, crystalnoise, bubblenoise,
cloudnoise3d, phasornoise, fractalsample (the 3D versions fractalnoise3d / worleynoise3d / cellularnoise3d /
crystalnoise3d weren't fetched separately -- per the audit record they differ from the 2D versions only in "coordinates are world coordinates, plus a pos input";
see each section for how that's handled). **These SideFX pages only say what the parameters do and give almost no formulas, defaults or value ranges**, which is why everything below
marked "decided here" exists.

Tests: `test_audit_c3_noise.py`, 193 checks (all green). "Bit-for-bit identical to before the change at default values" uses **hard-coded digests**
(GOLDEN, 30 old-signature calls: COP Noise 5 noise types × 4 fractal types + tiling / time / loop, Noise Extra 6 kinds +
billow), computed with `--digests` on the pre-change commit c87c5d9; they don't depend on git and also run in the installed layout.

Changed other people's existing tests (both because **appending** widgets per the rules broke hard-coded position assumptions):
- `test_sequence.py`: "COP Noise's three time-axis parameters are the last three" → changed to "the three right after device".
- `test_cop_accel.py`: "the last widget of 8 nodes is compute" → for Noise Extra changed to "compute is still
  after resolution_y (its original position)".

New shared module `geo/cop/noisepost.py`: the **Post Processing** section common to Houdini's noise family, in the docs' order
Fold → Complement → Bias → Gain → Gamma → Contrast → Clamp Min → Clamp Max. COP Noise,
Noise Extra, Worley, Cellular and Fractal Sample all use it (consistent widget names: fold / complement /
pp_bias / gain / gamma / contrast / use_clamp_min / clamp_min / use_clamp_max / clamp_max; Bias is called
`pp_bias` because COP Noise already has a `bias` (= Center)). Formulas decided here:
- Bias / Gain: Perlin's bias (x^(ln b/ln 0.5)) / gain. **The docs contradict themselves**: they say "below 1 pulls toward 0, above 1
  pulls toward 1" and also "0.5 has no effect"; we take the latter (b ∈ (0,1), < 0.5 pulls toward 0). The endpoints 0 / 1 are clamped into the open interval.
- Gamma: x^γ -- the docs say γ > 1 **darkens**, so that's what it does (opposite direction to Color Correct's gamma).
- Contrast: (x − 0.5)·c + 0.5.
- Negative values: bias / gain / gamma use the odd extension sign(x)·|x|^p for negatives (not in the docs; Perlin's formula gives NaN for negatives).
- Each step only runs when its parameter differs from the default; with everything at default the same array is returned unchanged (bit-for-bit).

---

## Fractal Noise / Fractal Noise 3D → PCG_COPNoise (parameters added)

Done (all appended to the end of INPUT_TYPES, default = old behaviour):
- Appended `white` (White (Random): a constant random value per cell, no interpolation) and `torus` (Torus) to Noise Type.
  Both are COP-only (`noise.NOISE_TYPES_COP`); the `NOISE_TYPES` shared with attribnoise is unchanged.
- `metric` (Euclidean / Manhattan / Chebyshev), `jitter`: only for worley / worley_f2f1 (read in both 3D and 4D),
  hidden on the panel for other types. jitter = 1 takes the original line of code (bit-for-bit unchanged); otherwise "cell center + (h−½)·jitter",
  0 = a regular grid.
- `tile_v`: tiling in v. Together with tile_u = seamless in both directions -- the u circle in (x,y), the v circle in (z,w), i.e. the 4D flat torus
  (Clifford torus), both radii F/2π, element size unchanged, isotropic.
- **Torus = simplex + two-way tiling**; no separate basis function (the docs literally say "4D simplex on a flat torus").
  With Torus selected, the Tile U / Tile V toggles are ignored (disabled on the panel).
- The Post Processing section (see above), after Amplitude / Center.
- Panel: two labels added to the Noise Type menu; Metric / Jitter only shown for the two Worley types.

Still different from Houdini / decided here:
- Tiling doesn't require rounding Lacunarity (multiplying the circle coordinates by Lacunarity just enlarges the circle, which still closes). Houdini rounds it.
- Two-way tiling (including Torus) uses up 4D, so **time can't be added** (time_scale > 0 raises an error); Tile V + loop also raises (5D).
  With only one direction tiled, time is allowed.
- Element Size: ours is Frequency (= 1/Element Size, in uv units), unchanged. Per Component = our Channels.
- White's w dimension (time / two-way tiling), like value4, guarantees "the cell with w ∈ [0,1) equals the 3D version".

Skipped:
- The **Alligator and Sparse Convolution** noise types: the docs only have one sentence describing their look ("alligator skin", "a value noise
  smoother than Perlin"), no algorithm -- anything we built would only "look like" it, so not done.
- **Fractal Type Sharp / Dampened**: the docs again give only a single word; can't be pinned down. Our `standard` (fBm),
  `terrain` and `hybrid_terrain` are kept.
- Noise Contrast (docs: "more intense within 0~1", no curve given), Octave Offset (we change seed per octave, seed+101·o,
  not a translation), Pulse Length / Loop Length in seconds (ours is frame-based time / time_scale / loop_frames),
  the four optional input layers pos / time / octaves / roughness -- none done.
- Fractal Noise 3D's "world coordinates + pos input": COP Noise is already a 3D slice at z = Offset Z, with no pos input; not done.

Mutation: 43, 9 survived the first round, handled as follows:
- worley4's w-axis jitter, White's salt (offset from value noise), Metric / Jitter passed to every octave for all three fractal types
  (for hybrid, the first octave got an extra hand-computed check of "1 octave = no fractal"), Offset X with only Tile V on, Bias endpoint clamping,
  the boundary between Gain's two halves -- targeted tests added for all of them; re-run killed everything.
- `is_identity` (a check for all-defaults up front) removed: mutation showed it exactly duplicated each step's own condition in apply.

## Worley Noise / Worley Noise 3D → new node PCG_COPWorleyNoise

This used to point to COP Noise's worley mode -- that is just a scalar 1 − 2·F1 without Houdini's five outputs, so a new node was created
(`geo/cop/cellnoise.py`) and two rows in copernicus_map.py now point to it.

Done: Element Size, Element Scale (per axis), Jitter, Jitter Scale, Lattice Type (rectangular / hexagonal),
Metric, Round Border, Offset, Tile + Tile Size, Post Processing; output layers dist1 / dist2 / border / center / id
(names as in Houdini, with an optional prefix). Connect a cop for Pos Layer: 2 channels = 2D coordinates, 3 channels = **Worley Noise 3D**.

Decided here / different from Houdini:
- Coordinate units: image width = 1 (x = u, y = v·H/W). The docs don't give the range of Houdini's canonical image coordinates.
- border (Euclidean): the minimum distance to the perpendicular bisectors of all Voronoi neighbours of the nearest point (exact; Quílez's two-pass method done in one pass).
  **Under Manhattan / Chebyshev it is estimated as (dist2 − dist1)/2**, not exact as Houdini claims.
- Round Border: polynomial smooth-min, k = this value (in cell units). The docs only say "larger is rounder".
- Distance units = cell-space distance × Element Size; with Element Scale ≠ 1 it is the "pre-stretch" distance.
- id = the low 32 bits of the hash of the nearest cell (after modulo) as a signed integer; **it changes with the seed** (random coloring changes when the seed changes).
- Tiling: cells per axis = round(Tile Size / Element Size), and Element Size becomes Tile Size / cell count. Hexagonal + tiling raises an error
  (a triangular lattice doesn't close in a rectangular period); 3D hexagonal not done (needs a tetrahedral lattice), raises.
- Search range: 5×5 neighbour cells in 2D, 5×5×5 in 3D. Measured at jitter = 1 to be bit-for-bit identical to ±4 / ±3 (the test has the comparison and a ±1 negative control).
  Not guaranteed for jitter > 1 (Houdini warns the same).
- Post Processing only applies to dist1 / dist2.
- No Per-Component Controls toggle: Element Scale / Jitter Scale are always shown, default 1 1 1.

Mutation: 36 (module shared with Cellular), 10 survived; after adding tests for all of them the re-run killed everything (z of the 3D hash, error branches must raise
an error "that explains why", Tile cell count round vs floor, y scaling on non-square images, the Tile wiring on the node, id varying with seed).
The search-radius mutation made me measure it, and I reduced 2D from 7×7 to 5×5 (faster, results bit-for-bit unchanged).

## Worley Noise 3D → same as above (Pos Layer with 3 channels)

## Cellular Noise / Cellular Noise 3D → new node PCG_COPCellularNoise

Same module, plus the Range (Amplitude / Shift) and Shape sections:
- `noise = Amplitude · clamp(s / Bevel, 0, 1) + Shift`, then through Post Processing; Bevel = 0 gives a hard 0/1 edge.
- Absolute: s = border − Gap/2 (image coordinates; Gap is the total gap width between two cells).
- Relative: s = border/(border + dist1) − Gap (1 at the feature point, 0 at the cell boundary). **The docs only give these two endpoints**;
  the normalization in between is our choice; the docs' sentence "with Jitter, 1 corresponds to the most elongated cell" isn't reflected.
- Smooth Edge = Worley's Round Border (only effective under Euclidean; hidden on the panel otherwise).
- Lattice Type labels follow Cellular's docs: Grid / Hexagonal. Also outputs border / center / id.
- Amplitude / Shift: multiply first, then add (the docs don't say the order; follows the Range section convention).

Not done: **Bevel Ramp** (a linear ramp instead).

## Crystal Noise / Crystal Noise 3D → PCG_COPNoiseExtra (partial)

Done: `metric` (panel label Primary Metric), `jitter` -- for the crystal kind only (the distance metric used to pick cells, feature point jitter);
the `amplitude` / `center` / Post Processing shared by all kinds (only applied to the main layer; auxiliary layers like _id / _edge are untouched).

**Not done / still different**: Houdini's Crystal is "two layers of Worley with random offsets combined", and the docs don't give the combination; our crystal is
a different algorithm, "one random sloped plane per cell", kept. So the Secondary group (Secondary Metric / Jitter / Element Size),
Noise Contrast and Flatten Faces aren't done; Tile Size and the 3D Noise time parameters aren't done either.

## Bubble Noise → PCG_COPNoiseExtra (only the common section added)

Done: Amplitude / Center / Post Processing (the common section).

**The core is skipped**: Houdini's Bubble Noise is "a fractal of torus noise with Distortion / Stretch / Droop warping per octave",
and the docs don't give the warp formulas; our bubble is "the height of a 3D sphere cross-section", something entirely different. Doing it Houdini's way
(Noise Type Simplex / Curl, Phase, Distortion, Stretch, Droop, Fold each Octave) would be pure guesswork, so not done.
**Suggest the coordinator decide** whether to mark the Bubble Noise row in copernicus_map as "different semantics" (currently new → NoiseExtra).

## Cloud Noise 3D → PCG_COPNoiseExtra (only the common section added)

Same as Bubble: Houdini's is fractal simplex / curl + Distortion / Stretch / Droop / Fold Each Octave, formulas not given;
our cloud is a density cut out by coverage / softness. Only Amplitude / Center / Post were added.

## Phasor Noise → PCG_COPNoiseExtra (partial)

Done:
- `phasor_type`: `phasor_wave` (default, = the original output) / `gabor_noise` / `intensity_field`.
- `periodic_function` (phasor_wave only): `sine` (the original 0.5 + 0.5·sin φ) / `rectangle` (1 where sin φ ≥ 0) /
  `saw` (φ/2π + ½, i.e. the _phase layer).
- Gabor = 0.5 + 0.5·Re(S)/√K, Intensity = |S|/√K. √K is derived by hand (K kernels per cell; with b = 1.5 the standard deviation of Re(S) is
  √K/3), not fitted; the test checks "|2·Gabor − 1| ≤ Intensity" and standard deviation ≈ 1/3.
- Amplitude / Center / Post (the common section).
- Existing equivalents: Rotate Pattern Uniform / Set Varying = our Angle + Spread (Spread 0 = Uniform);
  Kernels; the Direction input = Direction Layer.

Not done: the **Phasor Noise** item of Type (the docs only say "based on Gabor, with sharper shapes", undefined), Wave Bias (peak position,
no formula given), Saw's orientation is our choice, Blending Radius (our kernel bandwidth b is hard-coded to 1.5), Use Secondary Rotation,
the bias / scale input layers and their Blur / Strength, Rotate Channel, Noise Contrast, Tile Size, the 3D Noise time parameters.

Noise Extra mutation: 18, 3 survived (Crystal's 3D distance missing the z component ×2, changing only Center but not Amplitude);
after hand-computed tests were added, all killed.

## [C] Fractal Sample → new node PCG_COPFractalSample

The mapping table used to point to PCG_AttribNoise (geometry attribute noise) -- not the same semantics; per the rules it is left alone and a new node was created
(`geo/cop/fractalsample.py`); the mapping-table row changed to ("new", "PCG_COPFractalSample").

Done: Source Layer, Maintain Tileable, Max Octaves, Lacunarity, Roughness, Bias, Offset with Bias,
Blend Mode (Add / Subtract / Maximum / Over), Border (Wrap / Clamp / Black), Filter (Bilinear / Point),
Seed, Jitter, Angle (Per Octave / Random), Random Flip X / Y, Post Processing.

Decided here (the docs only describe semantics):
- Each octave is scaled about the image center by Lacunarity^o, rotated by θ, flipped and jittered. Per Octave's θ = Angle·(o+1) (per the docs' "at 30° the third
  octave is 90°", i.e. even the first octave is rotated).
- Add / Subtract **normalize by dividing by Σw** (so with 1 octave and no rotation or jitter the output is bit-for-bit the source image); Maximum doesn't normalize.
  Subtract = the first octave minus the rest. Over: premultiplied RGBA, each layer multiplied by its weight first, Bias not subtracted, only 4 channels accepted (the docs impose the same limit).
- Maintain Tileable: Lacunarity rounded (≥ 1), angles snapped to multiples of 90° (Random angles too); the test verifies that with Wrap +
  a tileable source the seam is smooth, and without it there is a seam.
- The gain in the docs' sentence "after weight and gain" isn't defined; not done.

Not done: Border has only three options (Houdini uses the layer's own border attribute); **Filter has no area filtering at Box and above** (high octaves are
heavy downscaling, so there will be aliasing); the three per-pixel input layers octaves / lacunarity / roughness.

Mutation: 24, 6 survived (X / Y flips sharing one coin, jitter range / direction, no jitter in v, Over's 4-channel check,
Lacunarity round vs floor); after tests were added, the re-run killed everything.

---

## Side findings (not changed; other packages / existing behaviour)

- COP Noise's `bias` has the panel label Center (Center from Houdini's Range section), which is a different thing from Post Processing's Bias --
  hence the new one is called `pp_bias`.
- In Noise Extra's kind menu, bubble / cloud are different algorithms from Houdini's nodes of the same name (described above); the mapping table records them as
  "new → NoiseExtra", which makes it easy to assume they correspond.
- COP Noise's Worley search covers only 27 neighbour cells. Measured (jitter = 1, 100k points, brute-force comparison against 125 neighbour cells, float32 tolerance):
  F1 is correct for all three metrics, F2 for Euclidean / Chebyshev, **worley_f2f1 + Manhattan is wrong for 0.49%**. Written into the docstring, not changed
  (extending to 125 neighbour cells is 4.6× more expensive; the default Euclidean mode is unaffected).
