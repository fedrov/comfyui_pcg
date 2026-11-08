# s7_attrib_misc audit notes

Tests: `test_audit_s7_attrib_misc.py`. "Bit-for-bit identical to before the change at default values" uses digests of the same set of calls from before the change (f210100)
(GOLDEN; `--digests` prints the current values), compared both ways of passing parameters: old parameters only / new widgets at their panel defaults.

## Attribute from Pieces → PCG_AttribFromPieces (appended to the existing node)

Docs re-checked (WebFetch, asked in three parts). Our node already does the same thing, "pick a piece for each point": the second input
library = Houdini's Geometry Library, library_attribute = the Piece Attribute on the library, output = the attribute name written to the points
(the same name in Houdini; we separate them, an extension). So no new node; appended to the end of the existing node:

Done:
- Mode gains `patches` (Worley cells: points whose nearest feature point is in the same cell get the same piece, picked randomly by weight), `noise` (the noise value
  (n+1)/2 quantized by the cumulative distribution of the weights), `vexpression` (Rules, one `piece name : expression` per line, wrangle syntax).
- Weight Method: `auto` (old rule, default) / Uniform Distribution / Piece Weights / Weight Attribute.
  Weight Attribute takes "the mean over all prims of the piece" per the docs (the old auto only reads the first prim, unchanged).
  The Piece Weights multiparm is written as one line of text: all numbers = in order; `piece name:weight` = only the listed pieces take part.
- Piece Filter (space-separated piece names; numeric piece names compared numerically, '7' matches 7.0).
- Shuffle (uses rand_seed), Offset (moves the last ones to the front, np.roll). The order affects Cycle, Automatic Ranges and the index output.
- Override Ptnum (use_id_attribute + id_attribute): Cycle uses id mod N, Random uses id as the random key.
- Map Attribute: a new dropdown `map_from` = weighted_unit (old behaviour, default) / Automatic Ranges (the selected elements'
  [min, max] split evenly into N bins) / Explicit Ranges (Rules `piece name : min max`) / String (Rules `piece name : pattern…`).
  Houdini has two dropdowns, Attribute Type + Map Pieces From; we merged them into one (String only has one mapping anyway).
- Several piece names on one Rules line → pick one at random (the docs' wording); Unmatched Piece / Unmatched Group.
- Copy Attributes + Allow P Attribute + Promotion Method (ten kinds, Maximum … Last Match).
- Location Attribute, Element Size, Element Scale, Offset, Noise Type, Max Octaves, Roughness.

Still different from Houdini / not made clear by the docs, so decided here:
- Patches and Noise share one set of Size / Scale / Offset (Houdini has two sets, Patch Size / Element Size).
  Offset is implemented as "translate the noise field by offset": sample position = (P − offset) / (Size × Scale). The docs don't give the direction.
- Patches picks a piece per cell by weight (the docs don't say whether Patches looks at weights).
- Noise doesn't equalize its value range: noise values cluster in the middle, so the first and last pieces get fewer points (Houdini has a Remap Noise ramp to adjust this; we don't).
  When points sit exactly on integer lattice points Perlin = 0 and they all land on the middle piece -- when using it, don't pick a Size that divides 1.
- Explicit Ranges are inclusive at both ends; when lines overlap, the one written first wins (the docs don't say). VEXpression likewise: the first true one wins.
- Unmatched Piece applies in all three modes Explicit / String / VEXpression (the docs only list it in the VEXpression section).
  When empty, strings get "", integer pieces −1, index −1.
- Copy Attributes reads the attributes of the class the library piece lives on (prim; points when the library only has points), plus the point attributes of the points used by this piece's prims
  (deduplicated in vertex order); on a name clash prim wins -- the docs only say "aggregated over each piece". Integer attributes with Average / RMS output
  float; the rest stay int. Strings only allow Max / Min / Mode / Median / First / Last (lexicographic); others raise an error.
  Attributes with the same name as the output attribute are not copied (otherwise they'd overwrite the piece name just written).
- When a Piece Attribute is given (picking per piece): VEXpression / String look at the piece's first element; numeric attributes take the piece mean.
- There is only one Seed (rand_seed), driving Shuffle / Random / Patches / Noise / Rules multi-choice at once (each with a different salt).
  Houdini has one Seed each in the Pieces and Random sections.

Not done:
- Promotion Method's Array of All / Unique Values (Geometry has no array attributes).
- Patches / Noise Distortion (Lattice / Gradient Warp), the Remap Noise ramp.
- The Autofill Pieces button (no button-type UI; write the text yourself).
- The "Enable piece" checkbox of VEXpression in Rules: replaced by commenting the line out with `#`.

Mutation testing: 48 mutants; 6 survived the first round (empty Piece Weights, string Max / Median, skipping the output name,
Random using ID, Unmatched Group collecting only selected elements); after adding targeted tests for each, all were killed.

Found in passing: the check for all-zero Weight used to raise an error in cycle mode too (after filtering, a and c both have auto weight 0); now it is only raised in modes that actually read
weights.

## Attribute Fill → PCG_AttribFill (appended to the existing node)

Docs re-checked. The old three modes (harmonic / nearest / diffuse) are this plugin's own "fill values along topology" and don't match Houdini's
Modes (the audit is right). Per the rules the old modes are untouched, and Houdini's four Modes are added at the **end** of the method dropdown; Known Group
is Houdini's Boundary Group (panel label changed to Boundary Group, parameter name unchanged).

Done:
- `eikonal`: shortest arrival time along edges (multi-source Dijkstra); time to go from i to j = edge length / Speed_i (docs: Speed is
  the speed of "leaving this point", so it's directional). Unreachable points get Unreachable Time; input values aren't read and the attribute need not exist
  (created as float); for an existing multi-component attribute each component gets the same time.
- `poisson`: harmonic fill with edge weights 1 / max(edge length, Minimum Edge Length) (1/l makes the solution on an unevenly spaced chain linear in arc length).
  Attribute to Match: minimizes Σ w (x_i − x_j − ω (g_i − g_j))², with ω given by Weight Attribute (clamped to 0..1);
  all 1 equals not giving Weight (the docs' wording holds); all 0 degrades to the unguided harmonic solution. Points not connected to Boundary Group
  get 0 (docs: "default Attribute value").
- `diffusion`: one implicit step (I + t L) x = x0, edge weight = rate / edge length², rate = mean of the two ends' Speed (clamped to
  Minimum Speed); Boundary Group points are fixed. No group = no fixed sources.
- `extrapolate`: Scalar (= the old nearest, the value of the nearest source along edges) / Parallel Transport (the tangential component at the source point
  is carried step by step along the shortest-path tree with "the minimal rotation between adjacent normals"; with Tangential Component Only off the normal component is copied as for Scalar,
  i.e. the source point's v·N multiplied onto this point's normal; Global Rotation rotates the tangential part about this point's normal). Point normals are computed on the fly when there is no N.

Still different from Houdini / decided here:
- Eikonal is the **combinatorial version**: it walks along edges and can't cut diagonally across triangles (the distance between diagonal points of a grid is 2, not √2). The docs open by saying this node
  solves "combinatorial versions", hence this choice; but the docs don't say which discretization Houdini actually uses.
- Speed is clamped to Minimum Speed in Eikonal too (the docs only mention Minimum Speed under Diffusion; without clamping it would divide by 0).
- Diffusion's edge weight k / l² is the standard finite difference on a uniform 1D grid; what Houdini uses on irregular meshes (whether area-weighted)
  the docs don't say.
- Weight Attribute goes from points to edges as the mean of the two ends (the docs don't say).
- Poisson / Extrapolate without Boundary Group keep this node's old convention: points whose attribute isn't all 0 count as known.
  Eikonal without a group raises an error.
- In Parallel Transport, Boundary Group points keep their original values (including not applying Global Rotation) -- the docs say "rotates
  the final output" without saying whether the sources rotate.
- The new four modes don't read the old Edge Weights / Iterations (hidden on the panel).

Not done:
- Extrapolation Type's Radial Field -- the docs have only one sentence, "produces radial vector fields with sources at
  the boundary points", saying nothing about how length / direction are determined; we don't fake it.
- The docs say the Extrapolate mode needs a polygon mesh; we use point connectivity, so point clouds + lines also run (no restriction).

Mutation testing: 27 mutants, 8 survived the first round:
- Raising the CG convergence threshold by 1e8× went unnoticed -- on a chain CG only converges at the last step; added a residual check on a 15×15 grid with a random boundary.
- Rodrigues missing the k(k·v)(1−c) term, Eikonal multi-component write-back, Weight averaging on edges, shortest-path tree depth, the error text for Eikonal without a group
  -- each got a targeted test (component along the polyline direction, shape check, non-uniform Weight against an independent least-squares solve,
  a folded strip with reversed point numbers, the error text).
- The "project back onto the tangent plane" line after parallel transport: the minimal rotation takes N[p] exactly to N[i], so the tangent vector is still perpendicular to N[i] after rotating
  (with a reversed normal it doesn't rotate and is still perpendicular); the line was redundant and was removed. After removing it, the "remove the normal component at the source first" mutant was killed as well.

## [C] Attribute Fade → new node PCG_AttribFadeTime

Docs re-checked: Houdini's Attribute Fade fades point attributes in / holds / fades out **over time** (for simulation fuel and the like);
our PCG_AttribFade is a spatial falloff starting from a group -- not the same thing. Per rule [C] the existing node is untouched, and a new
PCG_AttribFadeTime is added (nodes_sop2.py, implemented in geo/attribfadetime.py, icon attrib_fade, panel in g5);
"Attribute Fade" in sop_map.py now points to it; PCG_AttribFade moved into EXTRA (noted as a spatial falloff).

Done: Visualize Fade (writes Cd), Point Group, Fade, Fade Start Frame (read from the second input when connected),
Start Frame Retime, Hold Frame Scale (read from the third input when connected), Frame Offset, Fade In / Hold / Out
Frames, Fade In Ramp / Fade Out Ramp (each with an interpolation dropdown). A missing attribute counts as 1 (the docs' wording).

Still different from Houdini / decided here:
- The current frame is the parameter Frame (ComfyUI has no global $F; connect a playbar / value node).
- Both ramps give the fade value directly: fade-in defaults to 0→1, fade-out to 1→0. The docs don't say whether the fade-out ramp is used forwards or reversed.
- Section boundaries: [0, in) fade in, [in, in+hold) hold at 1, [in+hold, in+hold+out) fade out, 0 elsewhere. When t exactly equals the total length
  it's 0 (finished fading).
- Start Frame Retime is a multiplier (attribute × Retime = frame). The docs say "by default 0–1 uses frames; set to 1, $FPS
  to work in seconds", which looks like a (from, to) pair; multiplier = to / from.
- The second / third inputs correspond by point number (point counts must match when the attribute exists); input connected but without the attribute → default value
  (start 0 / scale 1), without falling back to the first input. The docs only say "read from the second input".
- The default attribute names fadestart / holdscale were chosen here (the docs give no default names).
- A negative Hold Frame Scale gives a hold duration of 0.
- Visualize Fade: points in the group get Cd = (f, f, f); points outside keep their original Cd (white if none).

Not done: nothing (all parameters in the docs are done; in Houdini Fade In / Out Ramp are draggable curves, ours are one-line text ramps,
the plugin's usual approach).

Mutation testing: 16, 6 survived the first round. 4 were section boundaries (<= vs <), "negative Hold" and "keep Cd outside the group" -- boundary tests were added using ramps whose
ends aren't 0/1 (0:0.3 1:0.8, 0:0.6 1:0.4), plus tests for negative Hold and Visualize + Group.
The remaining 2 (fade-in t <= in, hold t <= in + hold) are **equivalent mutants**: the next section's assignment comes later in the code,
so boundary points get overwritten by the next section and the result is unchanged.

Regression: test_nodes.py's all-node smoke test connects the same geometry to every optional input; initially "input connected but no attribute
raises an error" broke one check there -- changed to use the default value per the docs' "missing means 0", no longer an error.

## [C] Attribute Transform Extract → new node PCG_AttribTransformExtractHou

Docs (kinefx--attribtransformextract) re-checked: Houdini's node "decomposes a matrix attribute on the points into translation / rotation /
stretch (or scale / shear) + Euler-filters the rotation", single input. Our PCG_AttribTransformExtract solves per-piece rigid transforms between two geometries, rest /
animated -- not the same thing. Per [C]: the existing node is untouched (moved into sop_map's EXTRA, with its purpose noted), and
a new PCG_AttribTransformExtractHou is added (nodes_sop2.py, implemented in geo/xformextract.py, icon extract_xform,
panel g5); sop_map's "Attribute Transform Extract" now points to it.

Done: Group, Hierarchy Source (None / Topology / Pieces or Points) + Piece Attribute, Hint,
Decomposition (Polar Decomposition / Crack Transform), Transform Order, Rotation Order, Attributes
(wildcards, matching 9 / 16-component point attributes), prefix + suffix for Translation / Rotation / Stretch / Scale / Shear.

- Crack and ops.xform_matrix (the Transform SOP's matrix) are mutual inverses: 6 Transform Orders × 6 Rotation Orders with random
  parameters all decompose back to the original values (each run in the tests). With S before R, QR of Lᵀ is used; with R first, QL; for matrices with a reflection the reflection goes into one
  scale component. Translation = row 4 × (product of the matrices after T)⁻¹.
- Polar: H3 = Stretch · R (SVD; with a reflection Stretch absorbs the minus sign and R is still a proper rotation); translation is taken directly from row 4.
- Euler angle output (degrees) is the inverse of ops.euler_matrix; the Euler filter picks, among the two Tait-Bryan solutions (each plus integer multiples of 360°),
  the one closest to the reference angle; reference angle = the parent's already-filtered angle, the root uses Hint.

Still different from Houdini / decided here:
- **The matrix convention follows this plugin** (Transform by Attribute / Copy to Points: 3×3 acts on column vectors, translation in row 4);
  the tests pin down "Transform by Attribute with this matrix = Transform SOP with the same parameters". Houdini natively uses the row-vector convention,
  so the 3×3 is exactly the transpose -- matrices exported from Houdini need their upper-left 3×3 transposed first (see "Found in passing").
- The default suffixes of the output attributes (_t _r _stretch _s _sh, empty prefix) were chosen here; the docs only give an example with prefix `_` and suffix `_t`,
  without saying what the defaults are. Rotation is output as Euler angles (degrees) -- the docs don't give the unit, but given the Euler Filter semantics it can only be angles.
- Polar ignores Transform Order (greyed out on the panel).
- Topology: on each line the previous point is the parent; a point on several lines uses its first occurrence; cycles are broken.
  Pieces or Points: within a piece by point number, the previous **selected** point is the parent; if the piece attribute is missing or is float → everything is one piece (docs).
- Group limits both "which points build the hierarchy" (the docs' wording) and "which points get decomposed"; points outside the group get default values (translation 0, rotation 0,
  scale 1, shear 0, stretch identity).
- When Attributes matches no matrix: returned unchanged + a warning in the report (originally an error, but the all-node smoke test test_nodes.py
  counted it as "an extra active refusal"; Houdini does nothing in this case too, so it no longer errors).

Not done: nothing.

Mutation testing: 24, 4 survived the first round (parent of a shared point takes the first occurrence, Topology + Group, cycle breaking, Polar reflection) --
all killed after adding a test for each.

## [C] Name → new node PCG_Name

Docs re-checked: the Name SOP "writes a string attribute (default name) to the elements in a group / names by the group they belong to (the inverse of Partition) /
renames existing names From → To". sop_map used to point it at PCG_Enumerate's Format mode (numbering), which is
Enumerate's job. Per [C]: PCG_Enumerate is untouched (sop_map's "Enumerate" row still points to it), and a new PCG_Name is added
(nodes_sop2.py, implemented in geo/namesop.py, icon reuses enumerate_, panel g5); the "Name" row now points to it.

Done: Attribute, Class (Primitives / Points / Vertices), Name from Group + Group Mask, Number of
Namings (Group / Name / Enable), Global / From / To.

Still different from Houdini / decided here:
- The Namings multiparm is written as multi-line text, one `group : name` per line (split at the last colon); a leading `#` = Enable off.
- When groups overlap, in multiparm order **later entries overwrite earlier ones** (the docs don't say).
- With Name from Group, an element in several groups (docs: behaviour undefined): by lexicographic group name, later ones overwrite earlier ones.
  With Name from Group on, Namings isn't read (hidden on the panel).
- From / To replace by **plain substring** (the docs don't say whether wildcards are supported; Global off = replace only the first occurrence), applied to the whole column after naming.
- Elements that weren't named keep their original value; if the attribute didn't exist, the empty string.
- An existing **numeric** attribute with the same name: replaced by a string attribute (old values lost) + a warning in the report. Originally an error, but the all-node smoke test
  (test_nodes.py, whose smoke geometry carries a numeric name) counted it as an extra "active refusal"; the docs don't cover this case,
  so it no longer errors.

Not done: nothing.

Mutation testing: 13, 1 survived (the special case "empty group = everything"): resolve("") is everything anyway, so it was equivalent code; removed.

## [C] Camera from Points → PCG_CameraFromPoints (skipped, no code changed)

Docs re-checked: there is only one parameter, Camera Parms Attribute (a **dictionary** attribute on the points, built the way Camera writes it); when it isn't found
it falls back to the individual attributes written by Camera to Points set to "Unpack to Multiple Attributes"; each point becomes a
camera primitive.

Conclusion: the audit's "different algorithm" is only half right. With **default parameters** (Frames = 0, Orientation auto, Use Point
Attributes on) our node is exactly "one camera per point, parameters read from the point attributes unpacked by Camera To Points" -- the same thing as Houdini's fallback path
(test_sop_campoints.py has a round-trip test; this package's tests add another check that "fov / resx are read per point").
The extra Frames / Loop / Look Ahead / Orientation etc. are a "place cameras along a path" extension, kept per the rules.
So no new node, and sop_map is unchanged.

Skipped: Camera Parms Attribute (dictionary attribute) -- this plugin's Geometry has no dictionary-type attributes; faking a dictionary with a JSON string
would mean inventing key names (the docs don't list them either); we don't fake it. The output is a CAMSEQ camera sequence rather than camera
primitives in the geometry; that is the plugin's uniform representation of cameras, not changed.

## Trace → PCG_Trace (appended to the existing node)

Docs re-checked. The core difference: Houdini's Trace outputs **faces** (shapes touching the image edge are closed too, with Boundary Color deciding
what colour counts outside the image), whereas ours used to be "touching the edge means an open line" + Close Open Curves. Appended at the end:

Done:
- A Channel dropdown `channel_mode`: By Index (old behaviour, reads the channel number, default) / Mono / Red / Green / Blue / Alpha.
  The original INT channel can't be turned into a dropdown (rule: don't change existing parameters), so a new dropdown was added; only the By Index mode reads the channel number.
- Boundary Color: None (old behaviour, default) / Black / White / Same as (0,0) / Custom + Boundary Value:
  pad a ring of pixels with this value around the image before tracing, so shapes touching the edge close; after tracing, coordinates are shifted back to the original image.
- Resample Shapes + Step Size (world units, reusing ops.resample's equal-length resampling).
- Rotate / Scale on the Transform tab (xyz, about the image centre; Translate is the existing center_x/y/z).
  Signed area is corrected by the (signed) scales of the two axes in the image plane; perimeter is recomputed from the transformed points.

Still different from Houdini / decided here:
- Mono uses Rec.709 luminance (0.2126 / 0.7152 / 0.0722); the docs only say "brightness"; for a single-channel image Mono = that channel.
  Alpha without a 4th channel counts as all 1 (docs: "used if present").
- Same as (0,0) takes the COP's (0,0) pixel = bottom-left corner (COP row 0 is at the bottom).
- The boundary is padded before Invert (it pads the original value, inverted along with everything else).
- Rotation order Rx Ry Rz, scale before rotate (the docs don't give Trace's Transform Order / Rotate Order).
- After Resample, perimeter / area are still the values of the original contour.
- Default Size = 2 (Houdini fits to a 1×1 square); old behaviour not changed.

Not done (reasons):
- Remove Borders / Border Width -- the docs have only one sentence, "tries to remove the border"; the algorithm (drop shapes touching the edge? treat border pixels as background?)
  isn't given; we don't fake it.
- Smooth Shapes / Corner Delta, Fit to Curves / Fitting Error / Convert to Poly / Level of Detail --
  for the former the algorithm isn't given; the latter need Bezier fitting + re-discretization, not done this round (we have Simplify doing RDP simplification, similar intent).
- Hole Faces (bridging holes into the outer contour) -- the plugin has no ready-made "hole bridging" tool, not done this round; downstream PolyFill can take
  "outer contour + holes" directly.
- File / COP Path / COP Frame / Planes / Missing Frame / Scale to Size -- the input is a COP image port,
  and selecting a layer is Layer; there is no file-reading step.
- A 2D volume on the first input (Layer to Trace) -- not done.

Mutation testing: 15, 1 survived (Mono for single-channel images) -- killed after adding a test.

## PolyDoctor → new node PCG_PolyDoctor (partial)

Docs re-checked. The core of PolyDoctor is "Ignore / Mark / Repair for each kind of problem + valid / repaired attributes";
PCG_Clean is the Clean SOP (repair toggles only; Fuse Distance / Remove Unused Points are Clean parameters too).
Appending a dozen three-way menus to Clean would overlap with its existing boolean toggles and make it unclear which controls what, so a new PCG_PolyDoctor is added
(nodes_sop2.py, implemented in geo/polydoctor.py, icon reuses clean, panel g11); sop_map's "PolyDoctor" now points to
it (still marked partial, noting what isn't done); the "Clean" row is still PCG_Clean.

Done (each item Ignore / Mark / Repair, except where noted):
- Max Passes: if a pass repaired anything, do another pass (every repair changes topology; stop when nothing was repaired).
- Ill-Formed: fewer than 3 corners / adjacent duplicates (same point or coincident positions, including first/last) / the same point appearing twice / zero area.
  Repair: remove adjacent duplicate corners, delete what's left that can't form a face.
- 5+ Edges: repair = convex ones are fan-split from point 0 into quads (an odd count leaves one triangle), concave ones are ear-clipped into triangles.
- Non-Convex (quads, convexity judged in the best-fit plane): repair = ear-clip into two triangles.
- Overlapping (same point set, regardless of start point and winding) + Pair Overlaps. Repair = delete (with Pair, the whole group is deleted).
- Locally Small Areas + Local Area Threshold: area / the largest area among edge-sharing neighbours < threshold. Repair = move the face's points to its centre
  and fuse them into one point (docs: "shrinks to a point"); collapsed faces are cleaned up as Ill-Formed.
- Non-Uniform Polygons + Uniformity Threshold: **Ignore / Mark only** (the docs don't say how to repair).
- Globally / Locally Small Edges + thresholds: repair = collapse to the midpoint (chains collapse together to their mean position); Mark marks the polygons containing the edge
  (the docs' wording).
- Disconnected Points: points not referenced by any prim. Repair = delete; Mark = valid_pt 0.
- Non-Manifold Points: bowties + endpoints of edges shared by 3 or more faces. Repair = duplicate points "one per fan" (reusing
  meshfix._split_bowties; edges shared by 3 or more faces are split apart by this too).
- Attributes: names for Valid Polygons / Repaired Polygons / Valid Points / Modified Points (empty = not written),
  Create a group for each attribute (`<name>_grp`).

Still different from Houdini / not made clear by the docs, so decided here:
- Default modes (the docs give none): Ill-Formed, Overlapping, Disconnected Points = Repair, the rest Ignore; Max Passes 10;
  thresholds: Local Area 0.1 (the docs example), Uniformity 0.1, Global Edge 0.001, Local Edge 0.1.
- Uniformity uses the isoperimetric quotient 4πA / perimeter² (circle = 1; the docs only say "0 = very non-uniform, 1 = circle").
- Global Edge Threshold multiplies the bounding-box diagonal (docs: "bounding sphere diameter"; taken as the bounding box's circumscribed sphere).
- Local Edge: edge length < threshold × the longest edge among the polygons containing this edge (the docs only say "compared with adjacent edges").
- The Non-Manifold repair doesn't do Prefer Larger Angles pairing: when 3 faces share an edge all three are separated (Houdini keeps the two more
  coplanar ones together). Non-Manifold Points has an Ignore mode (Houdini only has Mark / Repair).
- Repaired faces / points always count as valid (docs: repaired is a subset of valid), even if marked by another item in the same pass.
- Polylines and non-polygon prims pass through unchanged, valid = 1; points used by polylines don't count as disconnected.
- Random Seed not done: our repair order is deterministic (by prim number).

Not done (reasons):
- Self-intersecting + Thickness -- needs pairwise triangle intersection (with an acceleration structure), not done this round.
- Globally Small Areas + Global Area Threshold -- the docs say "1 is the circumference of the bounding sphere"; area and perimeter units don't match,
  and it's unclear how to compare them; not invented.
- Ignore Winding / Visualize Maximal Manifold Patches / Create Manifold Number Attribute /
  Correct Winding / Delete Small Manifold Patches -- the manifold-patch set not done this round.
- The Visualize tab (colour display of invalid / repaired points and faces) -- not done this round; the valid_* / repaired_* attributes and groups can feed Color.

Mutation testing: 34, 12 survived the first round. 8 killed by new tests (figure-8 face, adjacent coincident points, same point at start and end, convex pentagon,
taking the max among neighbours, the isoperimetric constant, threshold multiplied by the diagonal, repaired counts as valid). Equivalent / redundant ones handled as follows:
- The line separately marking "endpoints of edges shared by 3 or more faces": such edges don't take part in corner pairing, so their endpoints are necessarily caught by the bowtie test -- redundant, removed.
- The "stop when the topology signature hasn't changed" check: every repair changes topology, so it's equivalent to "this pass repaired something" -- removed.
- 2 equivalent ones remain: neighbour area taking max / min (on manifold edges each edge has only one neighbour, same result); sorting by source prim in _rebuild
  (items are generated in prim-number order anyway).

## Found in passing (not this package's, not changed)

- **Matrix convention**: xform.point_matrices / xformattr._matrices use the upper-left 3×3 of a 16-component matrix with the column-vector convention (M·p),
  but put the translation in row 4 per Houdini's row-vector convention. The plugin is internally consistent (Transform by Attribute's result matches the Transform SOP,
  pinned in this package's tests), but 4×4 / 3×3 matrices exported from Houdini (row-vector convention) brought in will have transposed rotations.
  PCG_AttribTransformExtractHou reads by the plugin's convention; whether to unify on Houdini's convention is for the coordinator to decide.
- meshfix._dup_prims has a line of dead code `k = min(len(p), len(p))`.
- The old PCG_AttribFromPieces: the all-zero weight check also raised an error in cycle mode (cycle doesn't look at weights); this package changed it to raise only in modes that read weights.

## Existing tests changed / hard-coded numbers

None. test_nodes.py's smoke test broke twice because of new nodes' "active refusals" (Transform Extract with no matrix, Name hitting a numeric name);
both were fixed by changing the node (to Houdini's "do nothing / convert to string" behaviour), not the test.
