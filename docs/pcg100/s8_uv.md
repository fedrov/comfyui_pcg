# s8_uv audit notes

All docs were re-fetched (uvflatten / uvlayout / uvproject / uvautoseam / uvpelt / uvunwrap). Below, "docs"
means SideFX's current pages; options, defaults and formulas the pages don't give are marked "not specified by the docs, implemented as X".

## UV Flatten → PCG_UVFlatten

Done (all appended at the end of INPUT_TYPES, default = the original LSCM behaviour, GOLDEN digests bit-identical):
- **Flattening Method**: `method` menu `lscm | scp | abf`. Houdini 3.0 only has Spectral (SCP) (default)
  and Angle Based (ABF); `lscm` is our original algorithm, placed first as the default (old workflows unchanged).
  - SCP (Mullen 2008): the smallest non-trivial eigenvector of the generalized eigenproblem A x = λ B x, A = LSCM's MᵀM,
    B = the mass of boundary wedges (half the lengths of the two adjacent boundary edges; the docs don't specify how Houdini takes B, implemented as length-weighted).
    Inverse iteration with shift σ + B-orthogonal projection of the constant at each step. Tests check: developable cylinder patch / plane is isometric; on a saddle the eigen-residual < 1e-4,
    B-orthogonal to the constant, and no smaller Rayleigh quotient in 20 perturbed directions.
  - ABF: the unknowns are angles, min Σ((α−β)/β)², constraints = triangle angle sum π, interior point angle sum 2π, the sine wheel; solved by SQP
    (linearized at each step, the linearized-ABF step from Zayer 2007), repeated until the constraint residual < 1e-10, so it converges to the solution of ABF
    itself; then coordinates are reconstructed via the same LSCM least squares on "virtual triangles determined by the angles". Tests check: the KKT conditions
    (objective gradient lies in the span of the constraint gradients, β computed independently in the test), reconstructed uv angles = the solved angles, ABF energy lowest of the three modes.
- **Group** (`flatten_group`): only these faces are flattened; unselected faces keep their uv (vertex uv first, otherwise
  point uv, otherwise 0). Edges between selected and unselected become seams automatically. The original `group` only controls packing (Pack Group),
  and the name is taken, so the new parameter is called flatten_group, with panel label "Group", placed at the top (as in Houdini).
- **Preserve Seams**: edges that are split in the existing vertex uv (interior edges whose two sides' uv don't match) are added to the seams. The criterion is the same function as
  UV Layout's island split (uvlayout._uv_same, extracted from islands(); islands' result unchanged).
- **Vertex Pins** (`pin_group`, point group): the corners on the group's points are pinned to their **existing** uv. An island with >= 2 pins: solved directly as
  pinned conformal least squares (ABF also reconstructs with the pins); the island is no longer scaled by world area, doesn't take part in Normalize, no ARAP;
  1 pin: flattened at world scale, then the whole island is translated to the pin position (Houdini uses Reference UV to set orientation; not done here).
- **Output Groups**: `output_seams` (edge group: interior edges in Seams + Preserve Seams that touch faces in Group;
  the geometry's own boundary doesn't count), `output_constrained` (primitive group: islands with pins). Houdini has toggles + fixed group names; here you fill in names,
  empty = not written.

Still different from Houdini:
- Houdini 3.0 is interactive, and Pins are a multiparm of individual prim/vertex + UV; here they can only be "pinned to existing uv"; to move a pin,
  shift it first with UV Transform. The docs don't say how SCP solves with >= 2 pins; here it's solved as pinned LSCM.
- Houdini says SCP is faster; here each SCP inverse-iteration step is a full CG, about 5× slower than LSCM (64×40 sphere 0.1s → 0.55s),
  and ABF about the same.
- Houdini 3.0 Flatten has its own layout (Packing area Center / Size, interactive Repack); our Normalize / Pack
  are existing extensions, kept. Newly flattened islands don't avoid existing islands outside Group (Houdini's Preserve Layout does).

Not done (listed, not faked):
- Preserve Layout, Preserve Island Boundary Shapes (SCP keeping the boundary shape and only relaxing the interior).
- Rectify group, Axis-aligned vertex groups, Straightened Loops (ABF) -- all extra linear / non-linear constraints
  that require changing the solver's constraint structure; not done this round.
- Enable Manual Layout / the distinction between the two Seams sets of Layout constraints (that's interactive-state stuff).
- Packing area Center / Size.
- Iterations / Tolerance / ARAP / Distortion Attribute are our own solver parameters, not in Houdini; kept.

Mutation testing (31 + 3):
- 13 survived the initial run, each handled: initial value for two pins (similarity-transform fit) -- added test "CG converges in 0~1 steps on a flat grid";
  loosening `_pcg`'s convergence criterion -- added a 30-dimensional SPD unit test; ABF's β scaling -- added the KKT test; with Group, not filtering triangles /
  not filtering the closed-surface criterion / ARAP with pins / vertex uv preservation / the two filters of Output Seams / intersecting the Constrained group with Group /
  pinning on point uv -- one targeted test each; all killed.
- `pmask & sel[vprim]` (intersecting pins with Group) proved redundant: the selection boundary is a seam, so corners on unselected faces form their own wedges,
  join no island, and pinning them has no effect -- removed.
- `beta = clip(beta, 1e-4, π−1e-4)` in ABF: θ is already clamped; β above π after scaling only occurs at very sharp vertices of degree 3,
  and SQP still holds for β > π (the constraints pull α back) -- redundant, removed.

Found in passing: nothing.

## UV Layout → PCG_UVLayout

Done (appended at the end; at default values the original code path is taken, GOLDEN digests bit-identical):
- **Scale = Fixed**: `fixed` + `fixed_scale` appended to the Scale menu. All islands are scaled by this factor, no search for the maximum;
  islands that don't fit are placed in a row **below** the target area (v < 0; the docs only say "placed outside the target bounding box", without the exact position; implemented this way),
  and go into `nonpacked_group` (Houdini's Nonpacked polygons). Both shelf / raster are supported.
  The original menu label changed to "Largest Packable (Uniform)", token unchanged.
- **Island Rotation Step**: `island_rotation` menu `auto | none | step | custom` + `rotation_step` (degrees)
  + `rotation_divisions` (360° split into N). `auto` = the original behaviour (tries 4 × 90°; under shelf 90° doesn't change the bounding box,
  so it's the same as not rotating). Raster tries each orientation and finds the position with "lowest top edge, then leftmost"; shelf only looks at the bounding box and picks the orientation with the smallest bounding-box area
  (this is our heuristic; Houdini's search is raster-based). Under Rotation Step the scale upper bound is computed from the longest side in the most favourable orientation
  (a long strip placed diagonally can be bigger than placed horizontally).
- **Scale Islands to Match Their Surface Areas** (`match_surface_area`): before packing each island is multiplied by
  √(3D area / uv area).
- **Pack into = UDIM Tiles**: `pack_into` `unit_square | udim_tiles` + `udim_start` (Starting UDIM),
  `udim_columns` (Columns), `udim_count`. UDIM number → tile bottom-left = ((number−1001) % Columns, (number−1001) // Columns).
  With Largest packable, packs into Count tiles (shelf moves on to the next tile when one is full; raster searches each island from the first tile onwards);
  with Fixed, per the docs "fills as many tiles as needed", tiles are opened onwards as needed, Count not read.
- Output: `island_attribute` (Island number, = island number by uv connectivity), `target_attribute` (Assigned target:
  UDIM number / 0 for the unit square / −1 if not placed or not in Group), `nonpacked_group`.

Still different from Houdini / not made clear by the docs, so decided here:
- Houdini's Target is a multiparm (several rectangles / several UDIM numbers); here there's only "the unit square" or "Count consecutive tiles from Starting UDIM".
  Tile size not done (the docs also recommend keeping 1×1).
- Fixed's scale multiplies the **current uv size** (the docs don't say what Fixed is relative to; with Match Surface Areas it's relative to
  the 3D size).
- Island Padding is still in uv units (Houdini's is pixels at the Search Resolution) -- existing behaviour, not changed.
- Rotate to Fit (pre-rotation to the minimum-area bounding box) takes the place of Axis Alignment, but with a different algorithm; noted in the panel help.

Not done: the Axis Alignment menu (None / By Island Symmetry / By Island Position in 3D), Iterations / Random Seed /
Scale Search Tolerance (our packing is deterministic), Connectivity Tolerance, Separator edges / Island attribute
override, Target / Island scale / Island offset attributes and Overrides, Avoid Packing Over Non-Group Island,
Pack in Cavities (raster naturally fills concavities, shelf doesn't; no toggle), Apply Padding Between Island Target Boundary,
Spread Islands, Rectangles multi-rectangle targets, Islands from second input, the whole Island Stacking tab.

Mutation testing (30 + 9 + 2):
- 11 survived the initial run: Raster + No Rotation must not rotate / _rot_any must move back to the origin after rotating / shelf padding on a new row vs the same row /
  raster recording the tile / raster Fixed scale / area upper bound with multiple tiles / Raster's Default under UDIM also trying 4 × 90° --
  one test each (long-strip orientation, within 0..1, pairwise spacing >= padding, both tiles used without overlap, size with Fixed 0.2,
  8 squares on two tiles with side ≈ 0.5); all killed.
- Whether `auto` under shelf returns [0] or 4 × 90°: equivalent (90° doesn't change the bounding-box area, _best_rot takes 0° on a tie) -- unified to
  4 × 90°, that branch removed, added test "under shelf Default = No Rotation".
- "Check the ntiles cap before opening a new tile" in `_raster_try` was redundant (the later break already handles it) -- removed.
- Removing `_rot_any`'s "multiples of 90° go through _rot90" changes the result only in the last floating-point digits (the digests, quantized to 1e-6, can't catch it); kept so that the original
  Raster stays bit-identical, and added a test "_rot_any(q, 90k) is bit-identical to _rot90".
- With unlimited tiles, replacing "stop when not even an empty tile fits" with another termination condition gives the same output -- it is the loop's termination condition; kept.

## UV Project → PCG_UVProject

The audit record says "our box / face / rows_columns aren't UV Project options" -- right, they belong to UV Texture
(UV Texture in sop_map also points to this node); kept deliberately.

Done (appended at the end, a collapsible Projector section whose header toggle `use_projector` is off by default = original behaviour):
- **Transformation tab**: `xform_order` (Transform Order, 6 modes), `rotate_order` (Rotate Order, 6 modes),
  three components each of Translate / Rotate / Scale / Pivot (`proj_*`). The matrix is the same
  `ops.xform_matrix` as the Transform SOP; points are transformed by its inverse back into the projector's local space and then projected.
- Projectors are unit-sized (the docs don't specify the exact size of each projector; implemented as the unit projectors seen in Houdini's viewport):
  Orthographic = a square of side 1 centred at the origin (parameter = local coordinate + 0.5); Cylindrical = height 1 (v = y + 0.5);
  Polar = sphere (v by latitude, as before); Toroidal = outer radius 0.5, inner radius `inner_radius` (docs: "the outer radius is always 0.5"),
  tube centreline radius = (0.5 + inner)/2; Plastic Wrap uses the original formula, just no longer centred.
  When on, it **no longer** centres by bounding box and doesn't Fit to 0-1 (the projector itself is the placement; Houdini uses the Initialize button to fit the projector
  to the bounding box, and our Fit to 0-1 plays that role when it's off).
- **U Range / V Range**: uv = (projector parameter − start)/(end − start), i.e. the texture's left/right / bottom/top edges land at these two positions of the projector parameter
  (the docs only say "the position of the texture edges"; the exact mapping for each projection type isn't specified; implemented this way). Applied after Fix Seams.
- **Inner Radius**: only read with Toroidal + projector on; when off, the major radius is taken from the data as before (result identical to before the change, tested).
- Angle (our rotate) also rotates about (0.5, 0.5) in projector mode (the docs' wording), and likewise with Fit off.

Still different from Houdini:
- We only have one Axis menu deciding the projection direction; Houdini's projector orientation comes entirely from Rotate. The two stack: first the local basis is taken from Axis,
  then the projector rotates as a whole. Orthographic along y has u along +Z, v along +X (the original _frame convention, not changed).
- Our translate_u/v, scale_u/v are in uv space (existing extension), separate from the projector's 3D transform; both sets exist.
- box / face / rows_columns are unaffected by the projector.

Not done: the Initialize tab's Method menu + Initialize button (ComfyUI has no "press to change parameters" interaction; Fit to 0-1 approximates it),
the Fix Poles / Pole Radius toggle (the original implementation in Fix Seams already sets the u of pole corners to the mean of the face's other corners, with a hard-coded threshold of 1e-6 ×
radius, not made a parameter), Group Type independent of Attribute Class (our group is parsed by attribute_class).

Mutation testing (16 + 2): 2 survived the initial run -- the rotation centre of Angle with Fit off, the Rotate Z component not passed through -- each killed after adding a
test.

## UV Autoseam → PCG_UVAutoSeams

Houdini's algorithm is "curvature grains + merging" (Grain islands: Splitting / Grain tolerance / Merge threshold); ours is
"crease angle / normal-cone partitioning + tree-cotree to make disks". They're not the same thing; we do **not** pass ours off as Curvature Based, and the original three Modes are unchanged.

Done (appended at the end; GOLDEN bit-identical at default values):
- **Splitting = Existing Islands**: `existing_islands` appended to Mode + `uv_attribute` (default uv) +
  `connectivity_tolerance` (default 1e-6, the same tolerance as UV Layout's island split; the docs don't specify Houdini's default).
  Interior edges split in the existing vertex uv are the starting seams (the same function as UV Flatten's Preserve Seams; the tests check both sides agree),
  then Make Disks as usual. Error if there is no vertex uv (point uv can't express seams).
- **Enforce cuts**: `include_edges` (always seams, added after the Group restriction, so they count outside Group too),
  `island_attribute` (integer prim attribute; cuts between adjacent faces with different values).
- **Avoid cuts**: `exclude_edges`. Removed directly from the heuristic candidates; when Make Disks adds seams, the dual spanning tree **takes** excluded edges **first**
  (Kruskal), and when opening the first cut on a closed piece the diameter is taken only among non-excluded edges. When the excluded region covers every possible path (e.g. excluding all edges),
  the topologically forced cuts are still made -- without them it's not a disk and LSCM has no solution; stated in both the notes and the panel help.

Still different from Houdini / not done:
- Curvature Based, Grain tolerance, Merge threshold, Weight -- a different algorithm, not done.
- Avoid attribute + Weight (float point attribute, soft avoidance) not done: our pipeline has no "cost" to weight; the hard Exclude is done.
- In Houdini Existing Islands is the starting point for grains, which are merged afterwards; ours uses them directly as seams (only completing disks, no merging).

Two problems fixed along the way (both tested):
- With Exclude given on a closed piece, the first cut took the diameter of the whole cut tree and could pass through the excluded region -- changed to take it only among non-excluded edges.
- At one point we tried "first take a spanning tree of the original graph that avoids excluded edges, then take the dual tree of the complement": without merging the boundary points into one root, a tube was cut into 31 pieces
  (the complement is disconnected in the dual graph); after merging the root, mutation testing showed it gives the same result as the one-step "dual tree takes excluded edges first" -- the two-step approach was removed,
  leaving only the one-step one.

Mutation testing (12 + 4 + 5): removing path compression in Kruskal gives the same result (only affects speed), kept and counted as equivalent; all others killed
(added an Exclude test on a tube: the default vertical seam lies in the excluded region; after excluding, it moves to the other half, still one disk, same number of seams).

## [C] UV Pelt → new node PCG_UVPelt (nodes_sop2.py, implemented in geo/uvpelt.py)

The audit's conclusion is right: sop_map used to say "UV Pelt → PCG_UVFlatten, covered by LSCM", but Pelt is a "boundary pinned to a frame + springs"
model, not the same thing as conformal flattening. Per [C], UV Flatten is untouched, a new node is added, and that sop_map row now points to it (status new).
Icon uv_pelt (a circular frame + a few springs pulled to it); panel spec in panel_specs_g13.py.

Done:
- Cut along the Edge Cut Group (`seam_group`) (wedges; the geometry isn't cut); the **longest** boundary loop of the piece containing the Hint Primitive
  is laid out on the frame by 3D arc length (the docs' wording: "spacing between adjacent boundary points proportional to the corresponding edge lengths", "the longest boundary is connected to the frame").
- Frame: without a second input it's a circle (docs: circular by default), centre (0.5, 0.5), radius 0.5 (the docs give no size; implemented as the inscribed circle of the 0..1 square);
  a closed face on the second input is used instead (the first face with ≥ 3 points, U = P.x, V = P.y -- the docs don't list the options of the U From / V From menus,
  implemented this way; a frame given clockwise is reversed automatically, keeping the start point).
- Pelting Method: `spring_relaxation` (weight = sum of adjacent triangle areas / edge length² -- the docs only say "depends on edge lengths and the area of the incident
  faces"; the formula is our own), `tutte_barycentric` (unit weights), `discrete_harmonic` (cotangent weights (cot α + cot β)/2,
  negatives not clamped).
- Boundary Springs: strength k of the springs connecting boundary points to their positions on the frame, energy Σ w|u_i − u_j|² + k Σ|u_b − f_b|², solving (L + kD)u = kf
  (PCG). Docs: "increase it to enlarge the pelt" -- exactly so under this model (test: with small k the whole piece shrinks inwards). Default 10 (the docs give no default).
- Stiffness Attribute (point attribute; edge weight multiplied by the mean at both ends), Hint Primitive, Orientation (arc-length parameter on the frame, 0..1, of the boundary point nearest the hint face;
  the docs only say "the position of the first boundary point on the frame", type / units unspecified), Use Range + U / V Range (affinely maps this piece's
  uv bounding box to Range), Output Group (this piece's faces).
- Only the piece containing the hint face is flattened; other faces keep their uv (vertex uv first, then point uv, otherwise 0). Closed pieces raise an error suggesting to cut seams first.

Still different from Houdini:
- Iterations is CG's maximum step count, and the solution is the converged one; Houdini relaxes iteratively, not converged with few steps -- with small Iterations the two differ.
- The frame's Weight Attribute (guiding how boundary points connect to the frame) not done; boundary points are only spread by arc length.
- Extra boundaries (holes) are free, not connected to the frame (the docs don't say how holes are handled).

Tests (analytic references): Tutte interior points = centroid of neighbours; Harmonic / Spring interior points satisfy the equilibrium equations of their respective weights (weights computed independently in the test,
including an obtuse-angled mesh); boundary points satisfy Σ(u_b − u_j) + k(u_b − f_b) = 0; boundary by arc length (4×1 rectangle: long side 2π/10, short side 2π/20);
with stiff springs the boundary lies on the circle / square frame; landing points for Orientation 0 / 0.25; on an annulus the outer loop is pinned and the inner loop free; none of the three methods flips faces on a saddle,
and handedness matches UV Flatten.

Mutation testing (23 + 7 + 1): 6 survived the initial run (longest boundary, start point, arc-length parameter, absolute scale of Tutte weights, cotangent taking abs, interpolation on the frame)
+ 1 (keeping existing vertex uv); all killed after targeted tests.
- Existing test changed: test_nodes.py's EXPECT_REFUSE gained PCG_UVPelt (the default test geometry is closed; same as PCG_UVFlatten,
  refusing with "cut seams first" is correct).

## [C] UV Unwrap → new node PCG_UVUnwrap (nodes_sop2.py, implemented in geo/uvunwrap.py)

The audit's conclusion is right: the old sop_map said "UV Unwrap → PCG_UVFlatten, with UV Autoseam", but Houdini's Unwrap is "partition by plane +
orthographic projection + layout", a different algorithm from LSCM flattening. UV Flatten is untouched, a new node is added, sop_map now points to it (new). Icon uv_unwrap.

Done:
- Plane assignment: each face picks the plane with the largest |face normal · plane normal| (orthographic projected area ratio = |cos|; docs: "the plane causing the least shape distortion").
- Default planes = the coordinate planes of the three axes (the same (u, v) pairing as UV Project's box), rotated as a whole by `rotate_order` + `rotate_x/y/z`;
  polygons on the second input `planes` are used as the planes instead (filtered by `plane_group`; u = the polygon's first edge projected into the plane, v = n × u).
- Regions: faces projected to the same plane that share an edge are joined into one piece; faces outside Group don't take part and keep their uv.
- Layout: `strip` (sorted by each region's lowest face number, laid out in a row along U, bottoms aligned), `square` (by bounding-box area from largest to smallest, a shelf with row width
  max(S, widest region)). Scale: `none` (world size) / `uniform` (proportional, long side = 1) / `stretch` (both sides stretched to 1).
- Spacing: spacing between regions = Spacing% × S, S = √(sum of the regions' bounding-box areas).

Not made clear by the docs, so decided here:
- Faces facing the back of a plane form their own regions with u negated, so all regions have the same handedness as the face winding (no mirroring). The docs don't say whether Houdini splits this way.
- The docs don't list the options of the Planes menu (default plane orientations) -- only "the coordinate planes of the three axes" is done, so there's no such menu.
- Spacing's "layout space" is interpreted as S; Strip's order and Square's filling (shelf) were chosen here.
- Rotate isn't used when the second input is connected (stated in the panel help; specs can't express hide on "is an optional input connected").

Mutation testing (19 + 8 + 1): 8 survived the initial run (u projection on non-planar polygons, plane handedness, Square row width / ordering / row spacing,
vertex uv outside Group, Plane Group, Rotate Order); all killed after targeted tests.

## Summary: existing tests changed / other
- test_nodes.py: EXPECT_REFUSE gained PCG_UVPelt (see above). No other existing tests changed.
- The new test_audit_s8_uv.py runs in both layouts: in-package paths aren't concatenated; when sop_map can't be imported in the device layout that check only verifies the nodes exist;
  "bit-for-bit identical to before the change" uses hard-coded GOLDEN digests (20 old calls, baseline f210100; floats in the digests quantized to 1e-6 to avoid last-digit jitter
  from the number of BLAS threads); `--digests` prints the current digests.

## Found in passing while reading the code (not changed; for other packages / the coordinator to decide)
- The run() helper used by the tests (the test_options99 / s1 set) always takes the **first** option of a menu, ignoring the "default" written in INPUT_TYPES:
  PCG_UVProject's axis defaults to y, but run() passes x; PCG_UVAutoSeams' mode defaults to both, run() passes angle.
  I haven't verified whether ComfyUI itself honours a menu's "default" -- if it does, these tests aren't running the defaults; if it doesn't, the
  default written in the node is decoration (a newly created node actually defaults to the first item). Suggest the coordinator verify this across the board.
- The panel help of PCG_UVFlatten's original `group` (Pack Group) said "flattening itself always processes all faces"; changed after flatten_group was added.
