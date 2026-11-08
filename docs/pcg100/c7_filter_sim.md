# c7_filter_sim (pcg100): COP filter / simulation batch

All doc pages were re-checked with WebFetch (feather / extrapolateboundaries / edgedetectcontour /
edgedetectdepth / edgedetectnormal / surfacedither / reactiondiffusion_block_end /
turingpatterns / heatdistortbylayer / refractfromheight / oceanspectrum). Like the previous batch, these pages
**have only parameter names and a one-sentence description each**, almost no defaults and no formulas; that is why everything below marked "decided here" exists.

Tests: `test_audit_c7_filter_sim.py`. Only three nodes had their old-behaviour paths changed (Reaction Diffusion / Refract from Height /
Ocean); their "bit-for-bit identical to before the change at default values" uses the hard-coded digests GOLDEN (7 calls on the pre-change commit f210100,
rounded to 5 decimals before sha1; recomputed with `--digests`), independent of git. Everything else is new nodes; not a single line of the old nodes changed.

The new code is concentrated in the new file `geo/cop/filtersim.py`. Shared conventions:
- Distances in "image coordinates": consistent with the plugin's existing image space, origin at the image center, −1 … 1 spanning the **long side**,
  1 pixel = 2 / max(W, H).
- The `mask` input + Mask parameter on Houdini nodes: result = original + (new − original)·Mask·mask layer
  (our inputs are all layer names within the same COP; empty = unused).

---

## [C] Feather → new node PCG_COPFeatherSlope

The old PCG_COPFeather is "smoothstep by the exact distance to the mask edge" (both / inward / outward); Houdini's
Feather is "limit the maximum rate of change between adjacent pixels" -- not the same thing. Per [C] the old node is left alone and a new node was added;
copernicus_map's "Feather" points to it.

Done:
- `high_to_low` (Feather from High to Low, default on): on = out(p) = max_q(v(q) − s·d(p,q)) (bright stays, dark is
  raised); off = min_q(v(q) + s·d(p,q)).
- `direction` (Diamond / Square / Octagon / Custom / Circle) + Custom's 8 `sweep_*` toggles
  (−X +X −Y +Y −X−Y −X+Y +X−Y +X+Y; +Y = up = increasing row index).
- `method` (Distance for Unit Change / Change per Distance) + `distance` / `change` (image units,
  reciprocals of each other, per the docs).
- `include_border` + `border` (Black / Clamp / Wrap / Mirror): our layers have no border metadata, so it's a parameter.
- `mask` + `mask_layer`; `out_layer` (empty = overwrite, our extension). Multiple channels are processed independently per channel.

Not made clear by the docs, decided here:
- **The definition of distance**. The docs only say "horizontal + vertical passes → diamond islands, diagonal → square islands, horizontal/vertical + diagonal → octagonal islands,
  Circle uses a different algorithm → round islands". Ours: one serial propagation pass per sweep direction, with the cost of a step = s × that step's Euclidean
  length. Combining several passes gives the shortest path "allowed to move only along these directions", whose unit ball = the convex hull of the unit vectors of those directions: Diamond
  = L1, Square = √2·max(|Δx|,|Δy|), Octagon = a regular octagon; all three have their vertices on the same circle.
- A diagonal pass is implemented as a "king's move" sweep within a quadrant (horizontal / vertical / diagonal predecessors all charged s·√2 pixels). The first version only took diagonal steps,
  and an isolated single pixel produced a checkerboard (it could only propagate to cells of the same parity); after this change the shape is unchanged and there is no checkerboard. In Custom with only one
  diagonal direction on, the value propagates into the whole quadrant (not just along one diagonal line).
- **Circle is an approximate circle**: 8 directions + 8 knight-move directions, a 16-gon, with a maximum deviation from a true circle of 1 − cos(13.3°) ≈ 2.7%.
  The docs don't say what Houdini's "different algorithm" is.
- The docs give no defaults: High to Low on, Diamond, Custom with only +X ticked by default, Distance 0.1, Change 10,
  Border Black.
- Include Border + Clamp has no mathematical effect (the padded values are all farther away than the in-image pixels with the same value); stated in the panel help.

Still different from Houdini: no Signature; the Mask blend semantics are our choice, based on the uniform description in other Houdini nodes.

Mutation: 26. 2 survived: ① the shortcut branch returning the new value directly when `mask == 1` (equivalent: src + (new − src)·1),
**removed**; ② in-row propagation on the first row of a diagonal sweep (the sweep start, with no previous row) -- killed after adding a "bright point on the first row" test.

---

## [C] Extrapolate Boundaries → new node PCG_COPExtrapolateBoundaries

The old target, PCG_COPSmoothFill, is "mask > 0.5 is known + three home-grown methods pushpull / laplace / nearest"; Houdini's
is "split the interior out of fillarea by Threshold, pad outward by Edge Padding, then treat the outside per Exterior". Per [C]
the old node is left alone and a new node was added; copernicus_map's "Extrapolate Boundaries" points to it ("Smooth Fill" still points to the old node).

Done: Exterior (Unchanged / Black / Diffuse Fill), Inner Side (Below / Above Threshold), Threshold,
Edge Padding, Edge Offset, Sample Only Present, Diffuse Iterations, Mask + Mask Layer; `fillarea_layer`
corresponds to the fillarea input, `layers` to source (empty = all layers except fillarea).

Decided here (not in the docs):
- Padding = copy the value of the **exact Euclidean nearest** interior pixel. For this, filtersim got a lower-envelope EDT with indices (`nearest_seed`;
  sdf._edt1d_sq only gives distances and was left alone).
- Edge Offset: step back inward by Offset along the "exterior pixel → nearest interior point" direction, sampled bilinearly.
- Sample Only Present on: bilinear uses only interior pixels with renormalized weights, falling back to the nearest point's value when none of the four corners is interior; off:
  ordinary bilinear (mixes in exterior values -- the "smoothly interpolated edge" the docs mention).
- Diffuse Fill: solves ∇²f = 0 with "interior + padding" as known values, nearest known value as the base + Diffuse Iterations Jacobi iterations.
- Pixels exactly equal to Threshold count as exterior. The docs give no defaults: Inner Side defaults to Above Threshold (the common use of alpha as
  fillarea), Threshold 0.5, Edge Padding 0.05, Edge Offset 0, Sample Only Present on,
  Exterior Unchanged, Diffuse Iterations 50.

Still different from Houdini: no Signature; Houdini suggests "split RGBA's alpha out as fillarea first", we just take a layer name.

Mutation: 22. 4 survived: ① the EDT lower envelope's pop condition / ② bilinear x, y weights swapped -- the test scene was too symmetric; added
"nearest seed compared pixel by pixel with a brute-force solution" and "half-pixel step-back in an asymmetric direction", killed; ③ putting r back by the known mask after Diffuse,
④ the final "restore interior pixels to their original values" -- both equivalent (f is identically r at known pixels; interior pixels are never written), **removed**.

Side finding (not this package's, not changed): in `geo/backproject._push_pull`, on **non-square images** the pyramid stops as soon as one side shrinks to 1,
and the remaining weightless cells at the top level count as 0, so large holes are pulled toward 0 (20×10 with the left 11 columns known = 3, the rightmost is filled with 0).
COP Smooth Fill's pushpull / laplace modes and Back Project's hole filling both use it. Found when the first version of Diffuse Fill used it as the base;
now the nearest value is used as the base to avoid it.

---

## [C] Edge Detect by Contour / Depth / Normal → new node PCG_COPEdgeDetectProbe

All three audit items are marked [C]: the old PCG_COPContour is "one isoline every Interval", PCG_ControlImage is the ControlNet
bundle (its lineart mode extracts lines from depth / normal gradients). Houdini's three are "compare the current pixel with its neighbours (id / Z /
normal) within a probe radius, with variable line width". The three parameter sets are fully isomorphic, so they were merged into one new node with a `kind` dropdown (plugin convention); all three
copernicus_map rows point to it (status done → new). The old nodes are all untouched.

Done: Thickness Scale, the thickness layer (`thickness_layer`; when connected, Scale is a multiplier), Edge Spread, Blur,
Contour / Depth / Normal Tolerance (each only shown under its own Kind), Min Probe Radius; output layer `edges`.

**The docs don't describe the algorithm** (they only say "compares neighbours using ray differentials"), so all of this is our choice:
- Per-pixel probe radius R = max(Scale × thickness, Min Probe Radius), in pixels, capped at 64.
- An integer offset o within the radius is an "on-line neighbour" when, for contour: ‖Δv‖ > tolerance (multi-channel Euclidean); depth: |Δz| > tolerance;
  normal: dot product after normalization < tolerance.
- edges = max over on-line neighbours of exp(−½((|o| − 1)/(Edge Spread·R))²): 1 right next to the discontinuity, Gaussian falloff outward,
  cut off at R.
- Depth draws both sides (the docs speak of "the difference", not of drawing only the occluding edge on the near side).
- The docs say Normal Tolerance is "the **minimum** dot product required for a neighbour to count as on the line"; implemented literally, that wouldn't be crease detection, so it is
  implemented as "a dot product **below** it counts as a line"; stated in the panel help.
- The docs give no defaults: Scale 2, Edge Spread 0.5, Blur 0, Contour 0.5, Depth 0.01, Normal 0.9,
  Min Probe Radius 1. Blur is a Gaussian σ (pixels).

Still different from Houdini: no camera, no ray differentials; tolerances are absolute and don't scale with distance / slope; outside the border
the edge pixels are replicated.

Mutation: 19. 4 survived: ① the Depth mode slicing out channel 0 first (the code below only reads channel 0 anyway) -- equivalent, **removed**;
② skipping offsets outside the disk (there is a later |o| ≤ R check) -- an equivalent speed-up; rewritten to compute the disk width per row and never visit those offsets,
so the mutation point is gone (the new code's "width −1" mutation is killed); ③ multi-channel id comparing only channel 0 -- in the original test channel 0 happened to be
where the difference was; changed to "only channel 1 differs", killed; ④ the Normal mode raising on 1 channel -- killed after adding a test.

---

## [C] Surface Dither → new node PCG_COPSurfaceDither

The old PCG_COPDither is screen-space quantization dithering (bayer / Floyd–Steinberg / white noise, Levels); Houdini's is
"halftone dots attached to the uv, leveled by uv to avoid aliasing". Per [C] the old node is left alone and a new node was added; copernicus_map points to it.

Done: the uv layer (empty = texture uv of the pixel center), the dotscale layer, Density Scale, Pattern Scale / Scale XY /
Offset / Rotate, Dot Scale, Output Type (Mask / SDF), Iso Offset, Smooth, Level Transition; three extra output layers
uv / level / scale (empty layer name = not output).

**The docs don't describe the algorithm**; our approach (the docstring of filtersim.surface_dither has the full formulas):
- Pattern coordinate q = Rotate(uv ⊙ Scale) + Offset; ρ = the **largest** singular value of ∂q/∂pixel (central differences);
  λ = log2(Density Scale·ρ), k = ⌊λ⌋, f = λ − k. Dots sit on q's lattice points m·2^k, so the on-screen dot spacing is between
  Density Scale and half of it. We define Density Scale as **the on-screen dot spacing (pixels)** (the docs say "the overall size of the pattern in UV
  space", with no units).
- On moving to the next level, only lattice points with both components even are kept (exactly the full lattice of the next level); the other dots shrink away in the
  final Level Transition stretch of each level: t = 1 − smoothstep(1 − T, 1, f), radius (r0 + Rb)·t − Rb,
  Rb = √2 × cell pixels. Shrinking only to radius 0 isn't enough -- a dot of radius 0 has SDF = 0 at its center, so the SDF jumps at the level change
  (the test caught this in the first version with λ exactly an integer + floating-point error from a 90° rotation), so it is shrunk all the way until it "no longer contributes".
- Dot radius = ½·Dot Scale·dotscale·Density Scale (pixels); kept dots have the same on-screen size before and after a level change.
- SDF units are pixels; Mask = 1 − smoothstep(Iso − Smooth/2, Iso + Smooth/2, SDF).
- scale output = 2^(−f) (this region's dot spacing / Density Scale), level output = k, uv output = local coordinates within the cell.
- All defaults are our choice: Density Scale 8, Dot Scale 0.5, Smooth 1, Level Transition 0.5.

Still different from Houdini / not done: **the shape input and Shape Resolution not done** (custom dot SDF shapes would need a resampled copy of the shape stamped into every
cell; only round dots for now); at uv seams the derivative jump picks a very coarse level, and the docs don't say how Houdini handles it;
Houdini's tone (light/dark) can only be supplied via the dotscale layer, same as ours.

Mutation: 18. 1 survived: v used u's Offset (the two Offsets were equal in the test) -- killed after adding a "move only v" case.
Analytic references in the tests: lattice SDF at f = 0 / 0.5 / 1⁻ / after a level change, on-screen dots unchanged after Pattern Scale ×2
(surface stability), a uv layer = 2× texture uv agreeing with Pattern Scale 2, leveling by the largest singular value.

---

## Reaction-Diffusion Block End → PCG_COPReactionDiffusion (appended, default = old behaviour)

Not [C]: the old node is this solver (the Gray-Scott equations match the docs word for word); what was added is parameters. All appended to the end of
INPUT_TYPES (after compute); at default values the three GOLDEN cases (gray_scott default / custom + clamp / turing)
are bit-for-bit unchanged.

Done:
- **`maginu` (Kenjiro Maginu) added to the Model menu**, equations per the docs: A' = Da∇²A + α(A − A³) − B,
  B' = Db∇²B + β(A − γB). Diffusion A/B use the existing Du / Dv. State layers `_a` / `_b`, connect them back to continue.
  Initial state: A = ±0.05 noise (Rand Seed), B = 0, A = 1 at the Seed Layer / Spots (our choice).
- `maginu_alpha / beta / gamma`. The docs give no defaults; 1.0 / 0.5 / 1.5 are used: stable at dt = 1, separating from noise into
  two phases A ≈ ±0.86 (test: 48² run for 3000 steps, std > 0.3, no divergence). The first try, 0.6 / 1.0 / 1.2, is the textbook Turing
  range, but at dt = 1 B's reaction is too fast and explicit Euler diverges (only stable at dt ≤ 0.5) -- replaced.
- `scale_multiplier`: reaction terms ÷ S (Gray-Scott and Maginu). At S = 1 it is an exact ×1.0 and the addition order is kept as is,
  so it is bit-for-bit unchanged.
- Boundary: `boundary_layer` (SDF; reaction where SDF ≤ Threshold), Invert Boundary, Boundary Threshold,
  Boundary Smoothing (Gaussian-blurs the 0/1 region into a weight w). After each step, state = rest state + w·(state − rest state)
  (Gray-Scott U = 1, V = 0; Maginu A = B = 0). The docs only say "connect an SDF to make the reaction grow into that shape, Smoothing makes the
  reaction recede from the edges"; the method is our choice.
- Output Correction (only changes out_layer, state layers untouched): Normalize Model (each model's natural range → 0~1: Gray-Scott's
  V unchanged, Maginu (A + 1)/2), Invert, Clamp Minimum / Maximum (`use_clamp_*` toggles + values).
  Order Normalize → Invert → Clamp, our choice.
- Panel: Kenjiro Maginu added to the Model menu; Preset / Feed / Kill / Feed·Kill Layer changed to hide only when `mode != gray_scott`
  (maginu doesn't read them in the code); new parameters hidden under turing.

**Not done**:
- Houdini's Gray-Scott presets (Small Waves / Large Waves / Spots / Blinking Blobs / Worms / Labyrinth /
  Negatons / Chaos with Negatons / Spatiotemporal Chaos) and all the Maginu presets (Blobs & Spots …
  Moving Brusselator): **the docs have only names and a one-sentence description, no values**. These names come from Munafo's xmorphia atlas,
  but Houdini uses normalized parameters + Scale Multiplier, so the values don't carry over; inventing values would be "looks right but isn't", skipped.
  The old coral / mitosis / spots / worms / maze presets are kept.
- The Time section (Simulate / Reset / Live Simulation / Iterations per Step / Time Scale / Substeps / Caching):
  ComfyUI has no state between frames; ours is "one node runs Steps steps, state lives in layers, connect it back to continue", a platform difference.
- Switch to Raw Values (the docs don't give Houdini's internal conversion of "normalized parameters"), Signature's Chemical (UV) output
  (our state layers are the raw chemical quantities), Block Begin's alpha / beta / gamma / scale / coefficient input layers
  (Gray-Scott has Feed / Kill Layer; Maginu has no per-pixel version).

Changed an existing test: `test_cop_accel.py`'s "Compute is the last widget" for Reaction Diffusion changed, as for
Noise Extra, to check "compute directly follows resolution_y" (per the rules new widgets are appended after compute).

Mutation: 22. 2 survived: Maginu + Boundary pulling back only A and not B, Du/Dv swapped -- killed after adding "B = 0 outside the region" and "single-point diffusion:
A uses Du, B uses Dv".

---

## [C] Turing Patterns → new node PCG_COPTuringPatterns

The old target, PCG_COPReactionDiffusion's turing mode, is McCabe 2010's multi-scale Turing (comparing activator / inhibitor at multiple
radii) plus the Gray-Scott PDE; Houdini 22's Turing Patterns is a filter that "repeatedly blurs + sharpens a layer". Per [C]
the old node is left alone and a new node was added; copernicus_map's "Turing Patterns" points to it (Reaction-Diffusion Block
Begin / End still point to the old node).

Done: Filter (Box / Gaussian, default Gaussian -- the default given in the docs), Read Pixels outside Image + Border,
Units (Image / Pixels), Iterations, Radius, Power, Gain, Scale (x y), Mask (default 1, given in the docs) +
Mask Layer, Out Layer.

**The docs give no formula**; ours: x₀ = Gain·source; each iteration b = Blur(x, R), x = clip(b + Power·(b − Blur(b, R)),
0, 1). A same-radius unsharp mask = band-pass amplification by difference of Gaussians, and clamping to 0~1 is the nonlinearity that saturates it into two phases. The tests verify
"noise → a two-phase pattern" and "doubling the radius → roughly doubles the mean wavelength". Also our choice: Gaussian kernel half-width = radius, σ = radius/3;
Box is a mean over 2·round(R)+1; with Read Outside off only in-image pixels are used with renormalized weights; Mask blends with the **original image** (not
the post-Gain one); clamped to 0~1 (HDR input gets flattened); defaults Iterations 10, Radius 4, Power 2,
Units Pixels.

Not done: the radius input layer (per-pixel radius needs a variable-radius blur), Toggle RGB / per-channel toggles (we process every channel; select layers with Layer),
VDB input.

Mutation: 15. 3 survived: ① Box radius round changed to ceil -- killed with "radius 1.4 = radius 1"; ② Box's early return for n < 1
(at n = 0 the kernel is [1], identity) -- equivalent, **removed**; ③ Mask blending with the post-Gain value -- killed with "Gain 2 + Mask 0.5".

---

## [C] Heat Distort by Layer → new node PCG_COPHeatDistortByLayer

The old PCG_COPHeatDistort generates its own simplex noise drifting by Speed / Time (corresponding to Houdini's procedural "Heat Distort";
that row is untouched); Houdini's "by Layer" version consumes **input** noise / effect / dir layers. Per [C] a new node was added;
copernicus_map's "Heat Distort by Layer" points to it.

Done: the three layer inputs noise / effect / dir, Scale, Angle, Accurate Distortion (+ Pixels per Step), Streak Blur,
Scale by Timestep (+ Timestep; we have no $FPS, default 1/24), Blur Source (+ Blur Size), Blur Noise
(+ Blur Size), Chromatic Aberration (Scale / Red / Green / Blue), Mask + Mask Layer, Border.

**The docs give no formula**; our definition (the full version is in the docstring of filtersim.heat_distort_by_layer):
- Direction g = the dir layer (a 2D vector in image units); unconnected, the gradient of noise (per image unit) is used. Displacement
  D = Scale · effect · Rot(Angle)·g (· Timestep). Sampling out(p) = src(p − D(p)).
- Accurate: walk backward along the field for n = ceil(|D|max / Step) steps (capped at 256), each step using D at the current position; the test checks it against
  the exact ODE solution X·e^(−t) of a linear field. Streak Blur: average of the n+1 points along the trajectory.
- Blur Source: Gaussian-blur the source first, then interpolate between the original and the blurred image by |D| / max|D| (the normalization for "blur by distortion
  strength" is our choice). Blur Noise only takes effect when dir isn't connected (the docs' wording). Both Blur Sizes are σ in image units.
- Chromatic aberration: on layers with ≥ 3 channels, the R / G / B displacements are each multiplied by Scale × their own multiplier (defaults 1.2 / 1.0 / 0.8, not given in the docs),
  alpha follows G.
- Scale defaults to 0.05 image units. Empty Layers = all layers except noise / effect / dir / mask.

Not done: Blur Source / Blur Noise's Per-Component (per-axis) Scale; Signature.

Mutation: 25. 7 survived the first round, all handled by adding tests or rewriting: ppu using the long side (added a non-square image), the y gradient and Accurate's
y component (added a field along y), the −sin term of the rotation matrix (added "gradient +y rotated 90°"), Blur Source's interpolation weight (added "half the image
with displacement 0"), and "whether the trajectory takes 1 segment or n segments when neither Streak nor Accurate" -- equivalent (same endpoint); that branch was rewritten to
return the endpoint directly, and the new code's mutation is killed.

Changed an existing test: added PCG_COPHeatDistortByLayer to `test_nodes.py`'s EXPECT_REFUSE (the noise layer is a required input;
the default layer name noise doesn't exist in the generic test COP, so refusing and listing the existing layers is correct).

---

## Refract from Height → PCG_COPRefractFromHeight (appended, default = old behaviour)

Not [C]. The old node only outputs a 2-channel uv offset (viewed from directly above, flat water bottom); Houdini outputs the refracted / reflected RGB image.
All new parameters are appended at the end; **with everything at default the original code path runs** (both GOLDEN cases bit-for-bit unchanged); when any of them is not at default
the newly written `heightmap._refract_ext` (numpy) runs. The tests also check that "the full version with equivalent parameters (an all-zero ground connected,
Scale 0) agrees with the old path to 1e-6" (tile on / off).

Done:
- View: Directional (default on) + View Azimuth / View Altitude (Altitude 90 = directly above = old behaviour); off uses
  View Position (a point viewpoint). The docs don't give View Position's coordinate system; defined as the same world coordinates as the water surface (x 0 … World Size
  spanning the image width, z up).
- Height Offset; the normal layer + Normal Type (Signed / Offset); with a normal layer connected the normal comes from it and the height only provides the
  water surface's z (Houdini grays out Height Scale when normal is connected; our z still uses Strength, so the panel doesn't gray it out).
- The ground layer + Ground Offset / Ground Scale / Ray Trace Iterations: z = −Depth + Offset + Scale·ground,
  Newton iteration starting from the flat-bottom solution (gradient by central differences, then sampled bilinearly), t clamped to ≥ 0 (offset 0 where the bottom is above the surface).
  Test: a sloped planar bottom + an oblique view agree with the analytic ray / plane intersection; Iterations 0 stays at the initial guess.
- The source layer (empty = not output) + Refract Output Layer: sampled bilinearly at uv + offset, outputting the refracted image
  (Houdini's refract output). With Tile on, sampling wraps around.
- Refraction uses Snell's law in vector form; the tests check the analytic offsets for a 45° oblique view, IOR 1 passing straight through, Azimuth 90, and a point viewpoint.

**Not done**: Ground's IOR (the refractive index of the medium below the bottom -- we only trace to the bottom, not into the next medium), Material
(Water / Glass / Diamond) / Medium Color / Light Absorbance / Dispersion / Number of Colors (the docs give no
dispersion / absorption values for any material, so they can't be invented), the Reflection section and envmap (needs Fresnel + an environment map and outputs two images, result /
reflect, beyond the scope of this "distortion field" node; could be a separate node later), Space (Local / World; we have no layer
transforms), Compute Derivative outside Image / Kernel Size (the original Tile toggle + central differences are used), Filter
(bilinear only).

Mutation: 20. 4 survived: the default-path check missed Height Offset (viewed from directly above + an undulating surface it does change the result), the normal layer
not normalized, t not clamped to ≥ 0, sampling not wrapping around with Tile -- one test each added, all killed.

---

## Ocean Spectrum → PCG_COPOcean (appended, default = old behaviour)

Not [C]. The old node is Ocean Spectrum + Ocean Evaluate in one (directly outputs height / displacement / normal / foam). All new parameters are
appended at the end; at default values both GOLDEN cases are bit-for-bit unchanged (the order of random draws on the Phillips + Gaussian path is unchanged).

Done:
- `depth` (0 = deep water = old; > 0 uses the finite-depth dispersion ω = √(gk·tanh(kh)), for both spectra), `gravity` (the old version hard-coded 9.81).
- `spectrum_type`: Phillips (old) / **TMA**. TMA = JONSWAP × Kitaigorodskii depth attenuation, with the Hasselmann directional distribution
  cos^{2s}(θ/2); formulas per Horvath 2015 ("Empirical directional wave spectra", which is what Encino
  Waves is). Converted to a wavenumber spectrum P(k) = S(ω)·D(θ)·(dω/dk)/k, θ = the angle between the wave's **propagation direction** and the wind.
  Normalized so the height variance = ∫S dω (test: deep water / 5 m depth, grid sum vs. 1D integral differ by < 10%; with U 10, Fetch 100 km
  the significant wave height is 2.1 m, JONSWAP's order of magnitude). `fetch_km`, `swell`.
- `directional_movement` (Phillips): waves travelling against the wind are multiplied by (1 − dm). I worked out the old code's propagation-direction convention: the h0(q) term
  travels toward **−q**, so "against the wind" is q̂·ŵ > 0; the test uses the correlation of ∂h/∂t and ∂h/∂x to confirm that at dm = 1 the waves run downwind.
- `distribution` (None / Uniform / Gaussian / Log Normal, default Gaussian = old). All four are "random phase × amplitude r",
  E[r²] = 1 (same mean wave height): None r = 1, Uniform U(0, √3), Gaussian = the old complex Gaussian (Rayleigh), Log Normal
  exp(z − 1).
- `loop_period` (0 = no loop): ω is quantized down to integer multiples of 2π/T, so the surface at t and t + T is the same.

Decided here / different from Houdini:
- **Swell**: the docs say "> 0 is more concentrated, negative values spread more and add upwind waves"; Horvath's original is s += 16·tanh(ωp/ω)·ξ² (only ever more concentrated);
  we add it signed as ξ·|ξ|, then clamp to s ≥ 0. At Swell = −1, s is basically clamped to 0 (isotropic).
- TMA doesn't read Amplitude / Wind Direction Bias (those are Phillips constants); Min Wavelength (Small Cut) multiplies both spectra
  by exp(−k²l²). Log Normal's σ = 1 and Uniform's upper bound √3 are derived from "E[r²] = 1"; the docs don't give the distribution parameters.
- **Normalize / Reference Wind not done** (the docs only say "keeps the wave height consistent", without the normalization method), nor Houdini's Scale
  (our Amplitude is the Phillips constant A, not a total gain; the TMA mode has no total gain).
- Houdini's node only outputs the three layers amplitude / frequency / phase for Ocean Evaluate; we evaluate the surface directly
  (as the old node did), so those three layers aren't output separately.

Mutation: 33. 8 survived the first round: both sides of JONSWAP's σ, both pieces of Kitaigorodskii's Φ, the low-frequency exponent of Hasselmann's s,
Phillips' L using the constant G, the finite-depth group velocity -- all killed after tests computing each formula term by hand; folding θ back into [−π, π) and
capping s at 1000 were both equivalent (D only depends on |cos(θ/2)|; lgamma doesn't overflow at large s anyway), **removed**.

---

## Summary

Changed 8 rows in copernicus_map.py: Feather → PCG_COPFeatherSlope; Extrapolate Boundaries →
PCG_COPExtrapolateBoundaries; Edge Detect by Contour / Depth / Normal → PCG_COPEdgeDetectProbe (the latter two
done → new); Surface Dither → PCG_COPSurfaceDither; Turing Patterns → PCG_COPTuringPatterns; Heat Distort by
Layer → PCG_COPHeatDistortByLayer. Not a line of the old nodes (COP Feather / Smooth Fill / Contour / Dither / Heat Distort /
Control Image) changed; they are still referenced by their other Houdini rows or exist on their own.

7 new nodes (nodes_cop2.py, icons in web/pcg_icons.js, panels g6 / g7 / g8); 3 old nodes changed (Reaction Diffusion,
Refract from Height, Ocean; all new widgets appended at the end, GOLDEN bit-for-bit unchanged at default values).

Changed existing tests in 2 places: test_cop_accel.py (Reaction Diffusion's compute is no longer the last widget), test_nodes.py
(Heat Distort by Layer added to the refuse list).

For the coordinator to decide / side findings (not changed):
- `geo/backproject._push_pull` counts empty top-level pyramid cells as 0 on non-square images, so large holes are pulled toward 0 (used by COP Smooth Fill's
  pushpull / laplace and Back Project's hole filling). See the Extrapolate Boundaries section.
- Reaction diffusion's Houdini presets have names but no values (all skipped); Refract from Height's large material / reflection / environment map section
  isn't done; if it is ever done, it would fit better as a separate "render" node.
