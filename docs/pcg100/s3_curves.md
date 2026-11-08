# s3_curves audit notes (pcg100)

Tests: `test_audit_s3_curves.py`, 373 checks (each section readable on its own; shared helpers at the top of the file). Also run in the installed layout
(`comfyui_pcg/tests/`, no git, no sop_map.py at the repo root): all 372 pass -- the missing one is
"sop_map points to the new node", which prints a skip and isn't counted when sop_map can't be loaded.
"Bit-for-bit identical to before the change at default values": digests computed before the change (commit c87c5d9) from a set of calls **passing only old parameters** (all 7 nodes)
are hard-coded in `GOLDEN`, independent of git (also runs in the installed `comfyui_pcg/tests/` layout);
`python3 test_audit_s3_curves.py --digests` prints the current digests.

The mutation-testing script is in the scratchpad (`s3_curves/mut.py` + one mutation table per node); each mutant runs the whole test file.

## Resample → PCG_Resample (done)

Done (new widgets all at the end of INPUT_TYPES, default = old behaviour):
- `measure_method` (panel label **Method**): Even Length / Even X / Even Y / Even Z Segments.
  The old name `method` was already taken (it is really a combination of Houdini's two toggles Maximum Segment Length / Maximum Segments),
  so its panel label changed from "Method" to "Limit By", with the help describing the mapping to Houdini's two toggles:
  Maximum Segment Length = only length ticked (with Maximum Segments ticked too as a cap); Segment Count = only segments ticked.
- `measure` (Measure): Along Arc (= old behaviour) / Along Chord (equal straight-line distance between adjacent samples, using PolySpline's
  `_march` / `_even_params`).
- `maintain_prim_order`, `resample_by_edge`, `attrib_override` (prim attributes `segment_length` /
  `num_segments`), `maintain_last_vertex` (default on), `randomize_first`, `subdivide_later`.
- The check "Resample's new widgets come last" in `test_options98.py` hard-codes the trailing parameter names; these eight were appended to it.

Still different from Houdini / not done:
- **Level of Detail not done**: our existing Spline Evaluation / Samples per Span (how many evaluations per CV) does the same job,
  in different units.
- Rounding of the segment count: with length + even subdivision we have always used `round(total length / Length)` (old behaviour, not changed); Houdini calls it *Maximum* Segment
  Length, so it may round up (segments no longer than Length). The docs don't say, not changed; **the coordinator / author needs to check it against Houdini**.
- The semantics of the output attributes differ from the docs (old behaviour, not changed; these attributes aren't output by default):
  - The docs' Distance Attribute = half the sum of the lengths of the edges connected to this point; we write the arc length from the start.
  - The docs' Curve U = the input curve's **parameter** u (depends on input point spacing); we write the arc-length fraction.
- Maintain Primitive Order only orders prims; point numbering is still "untouched ones first".

Not made clear by the docs, decided here:
- Even X/Y/Z + Along Arc: measures the cumulative |Δx| (|Δy|, |Δz|) along the curve. On a stretch where that axis doesn't change (a plateau of the measure),
  the first position reaching this measure is used -- no points are placed on plateaus (an L-shaped line with Even Y doesn't get the corner); but the position where the measure is used up
  is always placed at the curve's end point, otherwise a trailing plateau would be dropped entirely. When the curve has no extent along that axis, only the start and end points are output.
- Even X/Y/Z + Along Chord: zero the other two components and measure the chord (same as PolySpline) = equal differences along that one axis between adjacent points.
- Segment count for Along Chord + even subdivision: whole steps + tail / Length, rounded (matching Along Arc's round), then bisection finds the chord length that gives
  exactly n steps.
- Resample by Polygon Edge: each edge is sampled separately by the same rules (length / segments / cap are all **per edge**), keeping all corners;
  edges are straight, so Measure has no effect (grayed out on the panel); the random first segment isn't used. Only for straight-edged polygons: when Treat Polygons As isn't straight edges
  (they've been densified into fine polylines, so there are no "edges") and on NURBS / Bezier it has no effect.
- Prim attribute override: `segment_length > 0` turns the length toggle on and uses it, ≤ 0 turns it off; `num_segments` likewise drives the segments toggle
  (Segments in Segment Count mode, the cap in length mode). Prims with both toggles turned off aren't resampled and are output as is
  (placed with the unselected prims; when Treat Polygons As isn't straight edges, the output is the densified polyline).
- Maintain Last Vertex only matters for "by length, not even": when off, a tail shorter than a step drops the end point; when the tail is exactly one full step
  (the end point is a sample anyway) the end point stays. Closed curves are unaffected.
- Randomize First Segment Length: first segment length = Length × (1 − U), with U from `np.random.default_rng(the input prim number)`,
  in (0, Length]; after that as usual (with even subdivision the rest is divided evenly; with Along Chord it walks normally from the first sample).
  Only takes effect with the length toggle on. Of course differs from Houdini's random sequence. A curve shorter than the first segment → only start and end remain.
  Under Along Chord, when the first sample is exactly the end point (measure zero), an extra coincident end point appears.
- Output as Polygon Curves to be Subdivided Later: solves (c₋ + 4c + c₊)/6 = sample point (open curves keep both endpoints fixed,
  closed curves use cyclic equations) -- consistent with the uniform cubic B-spline used by Treat Polygons As = Subdivision Curves;
  the test subdivides back with PolySpline (BSpline) to verify it passes exactly through the samples. Only P is adjusted; other attributes and tangent remain those at the samples.
  Not adjusted with Create Only Points.

Mutation testing: 38 + 6 + 1 mutants. Survivors handled as follows:
- The `a <= 1e-300` branch in `_rs_first_chord`: proven unreachable (the first vertex ≥ r from the start is j+1, Q[j] is inside the sphere,
  so this segment's length must be > 0), removed; likewise the [0,1] clamp on `u` (the start is inside the sphere, so the larger root is in (0,1]), removed.
- The "remaining polyline length is 0" guard branch for the random first segment under Along Chord: only reachable when the sample is exactly the end point (measure zero), removed;
  the consequence is described above.
- The original `untouched.any()` condition in Maintain Primitive Order was a real bug (with everything selected + Treat As densifying, NURBS were moved to
  the front, not ordered); fixed and a test added. The `len(kk) == nprims` guard changed to an explicit `not only_points`, test added.
- `dist >= r` changed to `dist > r`: only differs when a vertex is exactly r from the start; equivalent (boundary of measure zero), kept.
- The seed uses `orig[i]` (the prim number in the input) rather than the internal prim number after densification: test added.


## Cross Section Surface → new node PCG_CrossSectionSurfaceHou (done, handled as [C])

Our existing `PCG_CrossSectionSurface` is a **Gordon surface** (cross sections + guide curves weaving a net of two curve families, resampling, cubic /
linear interpolation), not the same thing as Houdini's Cross Section Surface (= Sweep with only cross sections: connects the cross sections' points directly into rows and columns by point number,
no resampling, no guide curves). The old node is untouched (digest regression); a new
`PCG_CrossSectionSurfaceHou` ("Cross Section Surface · Houdini (PCG)", `geo/crosssection.py`,
icon `cross_section_grid`, panel spec in g10) was added. The `sop_map.py` row points to the new node; the old node was added to `EXTRA`
(test_sop_map requires every geometry node to be either referenced by the table or listed in EXTRA).

Done (parameters following Houdini's four pages Cross Section / Surface / UV Coordinates / Attributes):
- Cross Section Group, Reverse Cross Sections.
- End Cap Type with four modes None / Single Polygon / Grid / Side Single Polygon; Cap Divisions, Triangular Poles,
  End Cap Scale, End Cap Roundness, End Caps Group (empty = no group).
- Surface Type with eight modes (Houdini's order, default Quadrilaterals); Ensure Unique Seam Vertices,
  Swap Rows and Columns, Close Implicit Backbone Curve.
- The whole UV group: Compute UVs, Override, Length-Weighted, Normalize U / V, Wrap U / V, Use Max Cross Section
  Length, Flip U, UV Scale. Polygon output writes vertex uv (2 components, like other uv in the plugin); Points output writes a point attribute.
- From Cross Sections (name pattern, default `*`), Point Row / Col, Prim Row / Col, the Cross Section Num attribute
  (Houdini has toggle + name; here an empty name = not written).

Not done / still different from Houdini:
- **Primitive Type (Automatic / Polygon / NURBS / Bezier) not done**: only polygons are output. Only polygon cross sections are recognized (NURBS /
  Bezier cross sections are skipped).
- **Cross sections with different point counts raise an error** (not in the docs; Houdini's Sweep adds points itself, how isn't documented). The message suggests connecting Resample first.
- The docs give no defaults for the toggles; filled with Houdini Sweep's usual defaults (Length-Weighted on, Normalize U on,
  Normalize V off, both Wraps on, Flip U on, Compute UVs off); **need checking against Houdini**.
- Normal direction uses this plugin's right-hand rule (U × V, U along the cross section, V toward the next cross section); Houdini's own winding convention wasn't checked.

Not made clear by the docs, decided here:
- Cross sections are ordered into rows by prim number; the point order on a cross section is the columns; it wraps around only if **all** cross sections are closed with ≥ 3 points (one open one means no wrap);
  Close Implicit Backbone needs ≥ 3 cross sections to wrap (wrapping two would only stack duplicate faces).
- Reverse Cross Sections = reverse the whole point order of each cross section.
- Single Polygon: with closed cross sections and an open backbone, one polygon at each end, wound opposite to the sides along the shared edges (a closed manifold);
  Side Single Polygon: with a closed backbone and open cross sections, one polygon each for the first and last columns.
- **The docs give no formula for the Grid end cap**; our choice: ring k (t = k/D, θ = tπ/2) shrinks toward the center within the cross section to
  s = (1−r)(1−t) + r·cos θ, and is raised along the cross section's normal (Newell, toward the side facing away from the adjacent cross section; when the cross section degenerates to a line, the away direction is used;
  with only one cross section the two ends face opposite directions) by h = Scale·R·((1−r)t + r·sin θ), R = the maximum distance from the cross section to its centroid
  (the docs' bounding circle radius), r = Roundness. Roundness 1 = a quarter circle, 0 = a cone, negative is concave;
  Scale 0 = a flat cap, negative caves inward. The last ring is a pole: with Triangular Poles off the pole is surrounded by "quads with two repeated
  vertices" (the docs' wording), with it on by triangles. Grid only takes effect with closed cross sections, an open backbone and a polygonal Surface Type.
  With a Triangles-type Surface Type, degenerate triangles with two vertices at the pole are discarded.
- Swap Rows and Columns (docs: points and primitives change from row-major to column-major, normals flip): points are reordered column-major, side primitives ordered by (column, row),
  and every primitive's vertex order reversed. The Rows output is still "one curve per cross section" (just reversed), and the row / column number attributes keep their original
  meaning -- the docs only say "reorder", not that the meaning of rows and columns is swapped.
- Ensure Unique Seam Vertices only matters for Rows / Columns curves (a polygon's vertex uv is already split on both sides of the seam):
  curves in the closed direction become open with an extra trailing vertex referencing the first point, so u = 0 and 1 are separate.
- UV: U = arc length along the cross section (column number when unweighted); V = the mean over columns of the distance between adjacent cross sections (row number when unweighted).
  With Normalize U but not Normalize V, each V step is divided by the mean perimeter of the two adjacent cross sections (by the longest with Use Max);
  with Normalize V but not Normalize U, U is divided by the total length of V. Wrap rounds the range to a positive integer (a normalized range is 1,
  unchanged by rounding). Flip U = (this row's U range) − U. End-cap rings use the same algorithm (rows of the extended grid); the pole ring has length 0,
  so U falls back to the column-number fraction. Single / Side Single Polygon end caps get uv 0 (not in the docs).
- Without Override, "copy the input's U": only the **point** attribute uv is recognized, and only for **open** cross sections (on closed cross sections the U of the seam ring can't be determined from
  points); the copied U is not normalized / rounded / flipped, only multiplied by UV Scale. V is computed as usual.
- From Cross Sections: point attributes (including strings) come from the source point (end-cap rings and the pole take the corresponding point / point 0 on the end cross section);
  prim attributes come from this row's cross section (end caps from the end cross section, column curves from the 0th). Vertex attributes aren't carried.
- Row / column numbers are in the extended grid (Grid end-cap rings count as rows); end-cap polygons get prim row and column −1.

Mutation testing: 47 mutants, 19 survived the first round:
- Killed by added tests: degenerate cross-section normal fallback, opposite poles with a single cross section, bounding-circle radius taking the maximum, "wrap only if all closed",
  "wrap the backbone only with ≥ 3", Grid only for closed cross sections, ring order at the start end, discarding degenerate triangles, Side Single Polygon requiring a closed backbone,
  string attributes, unweighted V, Wrap rounding to nearest, Flip without normalization, end-cap uv 0, the U fallback on the pole ring
  (with Wrap U on this is rescued by rounding, so a Wrap U off case was added).
- Proven equivalent and removed: the end-cap `len(f) < 3` guard (the wrapped direction has at least 3 points), clearing primitives when `surface == points`
  (that branch never outputs primitives), "round only if not normalized" in Wrap U / V (after normalization the range is exactly 1, unchanged by rounding).

## Curve Intersect → PCG_CurveIntersect (done, [C] class: the old two modes untouched, two modes added)

The old `output = points / split` is "intersect all curves pairwise / split at the intersections with shared intersection points (a connected network)", not the same thing as
Houdini's "left (Face Group) × right (Cutter Group), Method = Cut / Extract"; behaviour is entirely unchanged
(digest regression on 7 old calls; also verified that the old two modes don't read the new parameters when given them).

Done (new widgets at the end, the new optional input `cutter` also at the end):
- **cut / extract** appended to the end of the `output` menu (panel labels "Cut (Houdini Method)" / "Extract (Houdini Method)"),
  running the new function `paths.curve_intersect_hou`.
- `cutter_group` (Cutter Group) + an optional second input `cutter` (if unconnected, selected from geo); `group`'s panel label changed to Face Group.
- `find_all` (Find All Intersections), `left_pieces` / `right_pieces` (Keep All / Odd / Even / None),
  `affect` (Left / Right / Both Inputs), `keep_original`.
- Panel: new parameters hidden according to the code (Cutter Group / Find All only in cut / extract; Pieces only in cut; Affect / Keep Original
  only in extract); Self Intersections hidden in both Houdini modes (not read).

Still different from Houdini / not done:
- **Extract Point (point / isoparm) not done**: only meaningful when "the right side is a surface"; we don't support surfaces as cutters
  (neither NURBS / Bezier surfaces nor polygon surfaces; only curves -- a closed polygon counts as the curve of its edge loop, as in the old two modes).
- Intersect In (3d / xz / xy / yz) is this plugin's extension and is also read by the two Houdini modes; Houdini's semantics is 3d.
  **Note the node defaults to xz** (the old default, can't change); for strict Houdini behaviour choose 3D manually.
- Cut pieces each have their own points (pieces don't share cut points with each other, nor left with right) -- not in the docs, interpreted as "cut apart"; for a connected network use the old split.
- Output order: untouched prims first, then the left pieces, then the right pieces (Houdini's order not checked).
- Cut pieces carry no vertex attributes (float point attributes interpolated, others from the nearest source point; prim attributes and groups copied).
- Points produced by Extract carry no attributes (not in the docs; the old points mode has prim_a / u_a and so on).
- The docs give no default for Keep Original; set to off.

Not made clear by the docs, decided here:
- Pieces are numbered from 0 (docs: Odd = 1st, 3rd, 5th…, Even = 0th, 2nd, 4th…); closed curves count from the first cut point (smallest arc length).
- Curves that aren't cut are kept as is regardless of parity; with Keep None the whole curve is deleted (including uncut ones -- the docs say "Deletes the entire face").
- Right side Keep None = the right curves aren't output; when cutter is a separate input, its parts not selected by Cutter Group aren't output either
  (the docs say "Which pieces of the right face to create"). Without a cutter connected, unselected right prims stay in geo as is.
- A prim in both Face Group and Cutter Group (without a cutter connected): counted as left, not as a cutter.
- Find All off: each (left curve, right curve) pair takes only the **closest** location, without requiring it to be within Tolerance (the docs say
  "finds only the point of minimum distance"); ties take the smaller left arc length. It needs all segment pairs; more than
  20 million pairs raises an error (`_HIT_PAIR_LIMIT`).
- Cut points on an open curve's endpoints (within Tolerance) don't count; cut points whose arc lengths differ by less than Tolerance are merged into one cut
  (when the cutting line passes exactly through a vertex, the two adjacent segments each report one, within Tolerance of each other -- in the test the triangle's differ by 1.9e-8,
  and merging at 1e-9 used to cut out a zero-length piece; found incidentally by mutation testing and fixed).
- Extract: Left = the intersection's position on the left curve, Right = on the right one (with 3d and a Tolerance the two don't coincide), Both = output both.

Mutation testing: 30 mutants, 13 survived the first round, all killed by added tests (planar projection, bounding boxes enlarged by Tolerance, the segment-pair limit,
`<=` with Tolerance 0, deduplication at vertices, two cutting lines making the same cut, merging 0 / T on closed curves, uncut closed curves staying closed,
integer attributes / point groups taking the nearest point, prim groups); the [0,1] clamp on `w` was proven redundant (searchsorted guarantees it falls within the segment) and removed.

## Circle Spline → PCG_CircleSpline (partial)

Our original algorithm is Houdini's **Circle** type (one circle per three adjacent points, two arcs blended with w = sin²(πt/2)),
kept as the default.

Done (new widgets at the end, default = old behaviour):
- `spline_type`: Circle (default) / **Helix**.
- `helix_type`: Directional / Balanced / Blended (only read for the helix).
- `override_with_attrib`: the string point attribute `splinetype` (case-insensitive) decides which type the three points centered on that point use;
  values not implemented (hybrid / ellipse), empty strings and non-string attributes fall back to the node's Spline Type.
- `adjust_arclength` + `arclength_samples` (Adjust by Pseudo-Arclength).
- `use_curveu` / `curveu_name`, `use_tangent` / `tangent_name` (Houdini's Use Curveu Output / Output
  Curveu, Use Tangent Attrib / Output Tangent; default names curveu / tangentu).
- The panel label Divisions changed to Houdini's "Segment Divisions" (the parameter itself unchanged).

**Not done** (the docs have only a sentence or two, no definition to follow; not invented):
- **Hybrid** (Houdini's default type), **Ellipse**: I worked through Ellipse's sentence "the middle point sets the first axis, the far point sets the second axis,
  fitted through the remaining point": an equation in one parameter (the axis orientation) that diverges to +∞ at both ends, may have no root or two roots,
  and the docs don't say how the "bisection" starts -- anything built would be a guess, so not done.
- Re-parametrization Strength: our blend is done per segment parameter t; the docs don't say how the "parameterization" it affects is passed to neighbouring segments.
- Fitting Iteration Limit / Error Tolerance: only serve the Ellipse fit (and the circle / line decision); Ellipse isn't done,
  and the circle's collinearity test keeps the old fixed threshold (changing it would alter the default output).

Not made clear by the docs, decided here (Helix):
- The three points (a, b, c) are at −180°, 0°, 180° on the helix. Each half (a→b, b→c) is a half-turn about the axis d: in the plane perpendicular to d,
  the two points' projections are the ends of a diameter, the angle turns π uniformly in t, and the axial coordinate is linear in t. **Handedness is right-handed about d** (not in the docs).
- Directional: d = a→c; the two half-turns share one circle (equal radii), and their axial lengths may differ -- consistent with the docs' description.
- Balanced: d satisfies d·(b − a) = d·(c − b) (both halves equally long along the axis), taking the direction satisfying it that is closest to a→c
  (the projection of a→c onto the plane perpendicular to a − 2b + c); the two halves are equally long along the axis with different radii (each centered at the midpoint of its projection --
  "share an axis" interpreted as sharing the axis direction).
- Blended: blends the two axes by ∠abc, w = ∠/180°: 180° is Directional, 0° is Balanced.
- Degenerate: a and c coincide (no axis) falls back to the circle algorithm; when the two points' projections coincide, that half is a line segment.
- Segments are still blended with sin² (tangent-continuous at endpoints), so Helix is only an exact helix on each three-point segment itself.
- Pseudo-Arclength: point count unchanged; each segment is densely sampled at Segment Divisions × (Arclength Samples + 1) to measure arc length,
  and parameters are found by inverse lookup for equal arc lengths (open curves keep both ends fixed, closed curves divide the full loop evenly); P is re-evaluated on the curve, other float point attributes are
  interpolated linearly by parameter, integer / string / vertex attributes take the source point / source corner nearest in parameter.
- curveu = (segment number + in-segment parameter) / segment count (0~1 over the whole curve; after adjustment it's the looked-up parameter). The tangent is the central difference
  of the curve with respect to the parameter (h = 1e-5, evaluating slightly beyond the segment at endpoints), normalized.

Mutation testing: 27 + 8 + 1 mutants. Killed by added tests: degenerate-axis fallback (balanced / blended no longer raise), collinear unequal spacing,
the angle when a and b coincide, float / integer / vertex attributes after even redistribution. Proven equivalent and removed: the scale of r in the half-turn (u divided by r and multiplied back)
and the line-segment branch for r ≈ 0 (when the projections coincide u = 0, and the formula degenerates to a segment by itself), the zero-vector fallback for the blended axis (db·dd > 0, never zero),
the early check for a non-string splinetype (an unrecognized value falls back naturally), the clip on tangent endpoints (arcs / helices are defined beyond the segment too).

## Copy to Curves → PCG_CopyToCurves (partial, [C] class: the old two modes untouched, one mode added)

Houdini copies the source onto **every existing point** of the curve (frame from tangent / up); our old Sample By = count / spacing is
"resample along the curve, then Copy to Points", different semantics, entirely unchanged (digest regression on 3 old calls).

Done (new widgets all at the end):
- **curve_points** appended to the end of `mode` (panel "Curve Points (Houdini)"), running the new function
  `copyxform.copy_to_curve_points`; everything below is only read in this mode (hidden / grayed on the panel per the code). In this mode the old
  Up X/Y/Z = Start Up Vector (with Custom), and the old Roll = Roll (with Apply Roll ticked); Roll per Copy and
  Count / Spacing / Offset aren't read.
- Source Group + Source Group Type (Guess / Primitive / Point) -- **read in all three modes** (default empty = old behaviour).
- Frame page: five Tangent Types, Make Closed Curve Orientations Continuous, Extrapolate End Tangents,
  Transform Using Curve Point Attributes, Target Up Vector (Curve Normal / Y Axis / Attribute / Custom),
  Target Up Vector at Start (else Average), Use Target End Up Vector, Start / End Up Attribute, End Up Vector.
- Additional Rotations page: Rotate Order, Apply Roll or Twist + Twist Per (five kinds) + Full Twists / Partial Twist /
  Twist Ramp Attribute, Apply Yaw + Yaw / Yaw Per / Incremental Yaw / Yaw Ramp Attribute, Pitch likewise.
- Scales page: Normalize Scales, Uniform Scale, Stretch Around Turns, Max Stretch.
- Attributes from Target: simplified to one name pattern (`target_attributes`); curve point attributes are copied by copy onto the copies' **points**.
- Piece Attribute: in this mode, if the curve points have this attribute, pieces are picked by its value on the point (docs: attributes on the target points are matched with the source);
  otherwise they rotate the old way.

Not done / still different from Houdini:
- **Adjust Up Vectors by Curvature, Curvature Scale, Curvature Scale Attrib, Curvature Attrib not done**
  (the docs only say "tilt toward the center of curvature, scaled by Curvature Scale", with no formula for the tilt).
- Pack and Instance, Pivot Location, Display As not done (the plugin has no packed prims).
- Attributes from Target only does the one row "Apply to Point, by Copy"; no vertex / primitive, multiply / add /
  subtract, or multiple rows.
- The docs don't fully give Rotate Order's menu items and default; implemented as "the six permutations of Pitch / Yaw / Roll, listed first rotates first",
  default Pitch, Yaw, Roll -- **needs checking against Houdini**. Target Up Vector defaults to the first menu item, Curve Normal (unchecked).
- Transform Using Curve Point Attributes: N (tangent), up, orient (the whole frame), rot (an extra inner rotation in the frame),
  pscale / scale, trans, pivot, transform (3×3, overrides) are all recognized; a 4×4 transform isn't.
- Output point order follows copy_to_points (one copy after another); Houdini's output attributes aren't written.

Not made clear by the docs, decided here:
- Central Difference = the previous and next edges added **unnormalized**, then normalized (the docs say "unnormalized"); when they sum to 0
  (a 180° reversal) the next edge is used. Z Axis = tangent (0,0,1) at every point.
- Extrapolate End Tangents: the endpoint tangent = the second point's tangent mirrored about the first edge (likewise at the end) -- exact for circular arcs
  (verified in the tests), only done under Average / Central Difference; not done when the first segment has length 0.
- Curve Normal: the curve's Newell normal (open curves are computed as if joined end to end); if it comes out ≈ 0 (a straight line) it falls back to the Y axis. The threshold widens with coordinate magnitude
  (points are stored in float32; at 1000 from the origin even collinear points have 1e-4 error). With Attribute and the attribute missing, the Y axis is used.
- up is transported along the curve by RMF (double reflection); with Continuous, the extra twist accumulated around a closed curve is spread out by arc length (the closing edge gets only its share).
- Average (At Start unticked): the whole curve is rotated by one angle about the tangent so that the circular mean of the angle between each point's up and the target (projected onto its normal plane) is 0.
- End Up: the angle difference at the last point is spread linearly along the whole curve by arc-length fraction (the start is unchanged); not adjusted when End Up is parallel to the last tangent. Only Attribute /
  Custom have a separate "end target"; for the other two the end target = the start target.
- The five Per modes of Twist / Yaw / Pitch: Per Edge = value × point number; Per Unit Distance = value × arc length to this point;
  Scale by Attribute = value × attribute (point / prim / detail all recognized, not accumulated, missing attribute counts as 0); Per Full Curve by Edges =
  value × point number / edge count (closed curve edge count = point count); by Distance = value × arc length / total length. Roll / Yaw / Pitch are constants added on top.
- With Continuous, twist on closed curves (except Scale by Attribute) is scaled proportionally to whole turns (docs: "Non-full-turn twists
  are rounded to full turns"): the total over the loop is rounded to an integer multiple of 360°. Only for Twist, not Yaw / Pitch.
- All rotations are in the curve frame: Roll about local Z (tangent), Yaw about local Y (up), Pitch about local X (outward = up × tangent);
  final M = frame × R(last rotation … first rotation) × rot × scale.
- Stretch Around Turns: at corners, stretches along the miter direction (outgoing unit vector − incoming unit vector) by 1/cos(θ/2) (θ is the corner angle),
  capped by Max Stretch; open curves aren't stretched at the ends. Always computed from edge directions regardless of Tangent Type (the docs say it "always uses Average").
- Source Group Guess: if the source has only a point group of that name (no prim group of that name) it's points, otherwise prims (docs: without a type, primitive).

Mutation testing: 36 + 16 + 3 mutants. All survivors killed by added tests (Central Difference on closed curves, 180° reversal,
no extrapolation with a zero-length first segment, closed Full Curve by Edges, missing attribute / ramp from a prim attribute, Newell threshold on oblique lines, tangent parallel to up,
spreading twist continuously on closed curves, end up from Attribute, End Up parallel to the tangent, rounding per-distance to whole turns on a closed rectangle, rot as the inner rotation, stretching on closed curves,
piece attribute order). Proven equivalent and removed: the "don't stretch on straight runs" mask (with m = 0, k = 1, S is the identity anyway), subtracting the centroid before Newell
(in float64 the summed cross products are insensitive to translation; the error comes mainly from float32 input, which the threshold already covers).

## Chain → PCG_Chain (partial, [C] class: the old mode untouched, one mode added)

The old Chain is "rigid whole links laid on chords, Fit fine-tunes the spacing, Roll per Link" (this plugin's own approximation), not the same thing as Houdini's
Chain (a Path Deform repeated by pattern: each link bends along the curve); entirely unchanged (digest regression on 2 old calls).

Done (new widgets at the end; the new algorithm is in the new module `geo/chainsop.py`):
- `chain_mode`: Rigid Links on Chords (default = old behaviour) / **Deform Along Curve (Houdini)**. Everything below is only read in
  the latter mode (hidden on the panel per the code). In that mode the old Spacing = Piece Spacing, Up X/Y/Z = Curve Up Vector (with Custom),
  Piece Attribute = the attribute name for By Piece Attribute, and Copy Number Attribute writes the link number; Fit / Roll / Roll per Link aren't read.
- Chain Pattern: Geometry Group, Enable Deformation, Find Pieces (By Connectivity / By Piece Attribute),
  Number of Pieces (Fit / Explicit) + Fraction of Curve / Only Repeat Full Pattern / Num Pieces, Uniform Piece
  Scale, Map Length Using (three kinds) + Map Length + Pos End Attrib, Offset Position Using (three kinds) + Position Offset +
  Pos Offset Attrib, Start / End Behavior (Extend / Clamp / Clip).
- Pattern: five Repeat Patterns, Class Pattern, Offset, Seed (`rand_seed`), Repeat Length, Weights,
  Weight Attribute; Use Start / End Cap + piece number, Exclude End Pieces from Pattern, Do Not Deform End Pieces.
- Deformation: Enable Scale + Base Scale Factor + curve point attribute; Enable Rotation + Base Rotation + curve point attribute.
- Alignment: Forward Direction / Up Direction (X / Y / Z / Custom + vector), Center Geometry on Curve,
  Piece Rotation (new, default 0 -- the old Roll per Link defaults to 90 for chain links and wasn't reused), Curve Up Control
  (Curve Normal / X / Y / Z / Custom).
- Attributes: Attributes to Transform (default N), Output Position Along Curve / Index / Curve Number
  (Houdini has toggle + name; here an empty name = not written).

**Not done**:
- Mode = Deform Between Pivots (the docs have only one sentence).
- **The whole Fusing page** (Fuse Repeat Geometry, Snap Distance, three Fuse Methods), **the whole Rigidity page** (Rigid Prims,
  by piece attribute, Stretch Softening's Edge / Surface distance, Soften Radius, Falloff Ramp, Allow Rigid Geometry to
  Stretch, Rigidity Mask) -- a lot of work, and the docs don't describe the softening / mask algorithms; not done.
- Scale Ramp / Rotation Scale Ramp (only Base × curve point attribute is done).
- Bounds Group, Orient Using Point Attributes, Recompute Affected Normals, Preserve Normal Length.
- Output Repeated Geometry To Be Deformed After: same effect as turning off Enable Deformation (laid out straight along Z); not done separately.
- Houdini's exact mapping of "how much arc length" each curve segment's points use, and how frames are interpolated at corners, couldn't be checked; the defaults (Curve Up Control
  = Curve Normal, Exclude End Pieces = on, Attributes to Transform = N) follow the first menu item / common sense, **unchecked**.

Not made clear by the docs, decided here:
- Chain coordinate: each link's length = its bounding-box length along Forward × Uniform Piece Scale (side / up scaled likewise), plus
  Piece Spacing between links; link k starts at t_k. Fit: links are placed one by one until the next one no longer fits in Fraction of Curve × curve length
  (end pieces reserve their space first; piece lengths come from float32 points, so the check has a 1e-6 margin); if even the end pieces don't fit, nothing is output.
  Explicit: exactly Num Pieces links (including end pieces). Only Repeat Full Pattern: the middle stretch is truncated to an integer multiple of the pattern length
  (Cycle = the number of pieces in the pattern, Explicit = pattern length, random = Repeat Length; 0 = no truncation). Capped at 100k links.
- Mapping: chain coordinate t ∈ [0, G] → curve arc length s = Offset + t·(Map Length / G); Map Length: Fraction of Curve
  Length = value × curve length, Fraction of Geo Length = value × G, Distance = value; Offset likewise (Curve U = value × curve length).
  So the default (Fit, Fraction 1, Map Length curve length × 1) **stretches the whole links that fit over the entire curve**. The Pos End / Pos Offset
  attributes are prim attributes on the curve that override the Map Length / Position Offset values per curve (in the units of their respective Using).
- Deformation: point (side, up, forward) → the curve's position at s + side·X + up·Y (X = up × tangent); the frame's tangent / up within a segment
  are interpolated from the two end vertices' values and normalized (continuous at corners; the test verifies a bar offset to one side doesn't break across a right-angle corner).
- Extend extends along the end tangent; Clamp clamps s to [0, L]; Clip cuts the link in chain coordinates with clip.clip_plane at the planes corresponding to s = 0 / L
  and then deforms, discarding links entirely out of range (it only cuts when actually out of range -- same result, just saves a clip_plane call; this mutant
  is "equivalent but kept"). Closed curves have no ends: s is taken modulo the perimeter.
- Random patterns: `np.random.default_rng([seed, curve prim number])` (different per curve, and of course different from Houdini's random sequence);
  with Repeat Length > 0, the sequence cycles after that many random links. Weighted Random's weights are space-separated numbers in piece-number order (Houdini has
  multi-row Piece / Weight); all 0 means uniform. Weighted Random from Attribute: each piece takes the mean of its prim attribute.
  Explicit Pattern's piece numbers are taken modulo the piece count.
- Exclude End Pieces from Pattern: end pieces don't take part in pattern selection (if everything is excluded, falls back to all). Do Not Deform End Pieces:
  end pieces are placed rigidly by the frame at their midpoint (still scaled along the tangent by the chain's stretch ratio).
- Enable Scale / Rotation's curve point attributes are interpolated linearly by arc length (the closing edge of a closed curve interpolates back to the first point; missing / string attributes count as 1);
  Rotation is about the tangent, counterclockwise in the (side, up) plane. Attributes to Transform only rotates 3-component float point attributes, together with the frame and the two
  rotations (not with scaling).
- Without deformation (Enable Deformation off), links are laid along world Z: (side, up, s) -- z uses the curve arc-length coordinate (including Offset and stretch),
  so a downstream Path Deform-style node lines up.
- Find Pieces By Connectivity: by the prims' connected components (for a point-cloud source, one piece per point); By Piece Attribute with an empty name →
  falls back to connectivity.

Mutation testing: 41 + 19 + 4 mutants. Killed by added tests: empty attribute name / point-cloud source, tangent interpolation at corners, re-orthogonalizing up after interpolation,
Curve Normal on a float32 oblique line, Explicit piece number modulo, all-zero weights, Up ∥ Forward, centering by bounding box, the budget for end pieces + spacing,
end pieces not fitting, Piece Rotation's direction, Rotation's direction, Clip's position after stretching (including "discard the whole link rather than squash it at the end"),
non-3-component attributes, string scale attributes, attribute interpolation on closed curves, z including Offset without deformation. Proven equivalent and removed: "skip links cut to nothing"
after Clip (empty geometry going through the rest is still empty). Equivalent but kept: "only cut when actually out of range" before Clip (only to save clip_plane).

## Edge Equalize → PCG_EdgeEqualize (done, [C] class: the old mode kept as default, three modes added)

Ours was "redistribute points along the original polyline so edges are equal length (arc length / chord), shape and total length unchanged", not the same thing as Houdini's
"selected edges become the same length (Method sets the target)". The old approach is kept (`method`'s default Redistribute Along
Curve (PCG); the old `measure` is only read in this mode and hidden in the others); digest regression on 2 old calls.

Done (new widgets at the end):
- `method`: redistribute (default = old behaviour) / **Average / Longest / Shortest Edge Length** (Houdini's three modes,
  running the new function `meshedit.edge_equalize_hou`).
- `group_type`: Guess from Group / Edges / Points / Primitives (only read in the three Houdini modes; the old mode only recognizes edge groups).
- `output_edge_group`: written in every mode (the old mode writes the edges in Edges); empty = not written.

Not made clear by the docs, decided here:
- **The docs don't say which points move or how the change is distributed**: each selected edge stretches or shrinks about its own midpoint to the target length; when a point is pulled by several selected edges it takes
  the average correction, iterated (Jacobi on position constraints) until every selected edge's length error is < 1e-9 × target (at most 1000 rounds; the report has the
  iteration count and the maximum error). Disconnected edges get there in one step; connected edges pull on each other and all end up at the target length, but the overall shape changes.
  Only the endpoints of selected edges move.
- The target length is the mean / longest / shortest over selected edges with length > 0 only (zero-length edges have no direction and are excluded); if all are 0 it returns unchanged.
- The docs don't list Group Type's menu items; implemented as Houdini's usual Guess / Edges / Points / Primitives: Points = edges with both ends in
  the group, Primitives = all edges of the selected primitives; Guess: if the name matches an edge group, edges; if there is a prim group of that name and no point group of that name, prims;
  otherwise points (point number / range syntax also goes to points). Point pairs in an edge group that aren't edges are ignored. Empty Group = all edges.

Mutation testing: 12 + 4 mutants. Killed by added tests: Guess with same-named point group / prim group, non-edges in an edge group, all zero lengths,
averaging at shared points (a star: without averaging it doesn't converge). Proven equivalent and removed: the early return for an empty Group (parsing an empty string gives all edges for every type).

## Changed other tests

- `test_options98.py`: the check "Normal / Resample / Sweep / PolyExtrude new widgets come last" hard-codes Resample's trailing
  parameter names; this package's eight were appended (with a comment saying so).
- `sop_map.py`: the Cross Section Surface row now points to the new node; the old `PCG_CrossSectionSurface` was added to `EXTRA`
  (test_sop_map requires every geometry node to be either referenced by the table or listed in EXTRA).

## Side findings (not changed; for the coordinator / author to decide)

- Resample's old "by length, even" segment count is `round(total length / Length)`; Houdini calls it *Maximum* Segment Length, so it may
  round up (segments no longer than Length); the semantics of the two output attributes Distance / Curve U also differ from the docs (see the Resample section).
  All of these would change default output, so they weren't touched.
- The Curve Intersect node's Intersect In defaults to xz (old default), while Houdini's semantics is 3D; the Cut / Extract modes read it too.
- Several defaults in Copy to Curves / Chain / Cross Section Surface (Target Up Vector, Rotate Order,
  Curve Up Control, the UV toggle group) aren't given in the docs and were filled with the first menu item / Sweep's usual defaults; worth checking against Houdini.
- Chain's old mode (Rigid Links) defaults to Roll per Link = 90°, meant for chain links; Houdini's Piece Rotation default is presumably 0 --
  so the Houdini mode uses a new parameter, Piece Rotation, instead of reusing it.
