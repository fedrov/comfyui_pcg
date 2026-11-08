# s9_volume_fracture audit notes

Tests: `test_audit_s9_volume_fracture.py`. "Bit-for-bit identical to before the change at default values" uses digests of the same set of calls from before the change (f210100)
hard-coded in GOLDEN (`--digests` prints the current digests), independent of git.
The mutation scripts are under `s9_volume_fracture/` in the scratchpad; each mutant is applied on its own, the whole test file is run, then it's restored.

## Volume Blur → PCG_VolumeBlur

**Done** (all appended at the end of INPUT_TYPES, default = old behaviour):
- `reduction`: `filter` (default, = the old Mode menu gaussian / box) + Houdini's ten modes
  Maximum / Minimum / Maximum of Absolute / Minimum of Absolute / Average / Median / Sum /
  Sum of Absolute / Sum of Squares / Root Mean Square.
- `use_voxel_radius` + `voxel_radius_x/y/z` (voxels per axis).
- `override_border` (Use Volume / Constant / Repeat / Streak) + `border_value`.
  Override Border also applies to the filter mode.
- `enable_blending` + `original_blend` / `blurred_blend`: out = a × original + b × result.
- Panel: the Iterations label changed to Houdini's "Passes" (label only); mode is only shown in the filter mode,
  Voxel Radius only in the non-filter modes.

**Still different from Houdini / decided here**:
- Window radius: the world Radius is rounded with `np.round` by each axis's voxel size (same as the old box, so 2.5 → 2 is
  banker's rounding); Houdini's Average supports fractional radii with OpenCL off, not supported here. Capped at 5× the resolution
  per the docs.
- Max/Min of Absolute output the absolute value itself (the docs say "the largest absolute value"), without restoring the original sign --
  the docs aren't clear; implemented literally.
- For Sum of Squares / RMS / *Absolute* with a Constant border, the outside Border Value is also squared / made absolute first
  before the reduction (not specified by the docs; implemented as "the outside voxels have this value").
- Use Volume: our volumes have no per-volume border setting (sampling always clamps to the edge), so it equals Streak.
- The docs give no defaults for the two Blend amounts; 0 / 1 are used (turning Blending on doesn't change the result by default).
- Not done: Use OpenCL (meaningless); Houdini's Radius handling for "tapered" volumes (we have none).
- The old gaussian is truncated at ±4σ and isn't subject to the 5× resolution cap.

**Mutations**: 21, 3 survived → handled as follows:
- The early return for `r <= 0` in `_reduce1d`: without it a window of 1 gives the same result, equivalent → that code was removed.
- The `use_volume → streak` mapping: `_pad` already takes edge for unknown values, equivalent → mapping removed, explained in a comment.
- Changing the 5× cap to 1×: max/min can't tell → added a test with Sum + border extension + a huge radius (where the cap is visible),
  after which it was killed.

## VDB Smooth SDF → new node PCG_VolumeSmoothSDF

The audit record maps it to PCG_VolumeBlur, but none of Houdini's four Operations is our gaussian / box,
and VDB Smooth SDF has its own mask input; forcing it into Volume Blur would mix the parameters of two Houdini nodes in one panel.
So **a new node** (nodes_sop2.py, icon volume_blur, panel g12), and sop_map's "VDB Smooth SDF" now points to it.
This one is not [C]; adding a new node was my own judgement -- if the coordinator thinks it should be merged into Volume Blur, it can be revisited.

**Done**: Group / Alpha Mask (the first volume of the second input `mask`) / Operation (Mean Value, Median Value,
Mean Curvature Flow, Laplacian Flow) / Filter Voxel Radius / Iterations / Invert Alpha Mask /
Min, Max Mask Cutoff.
- Mean Value: mean over a (2r+1)³ cube (separable box, border extended).
- Median Value: the **true** median over a (2r+1)³ cube (OpenVDB's approach; different from Volume Blur's per-axis approximation, compared in the tests).
- Mean Curvature Flow: φ += dt·H|∇φ|, H = ½div(∇φ/|∇φ|), dt = h²/3;
  Laplacian Flow: φ += dt·Δφ, dt = h²/6. **The docs give neither the step size nor the ½ in H; taken from the OpenVDB LevelSetFilter source** (from memory).
  For a sphere, R² = R0² − 2t / R0² − 4t matches in the tests (error < 2e-3). On anisotropic grids derivatives use each axis's own spacing, h = smallest spacing.
- Alpha Mask: a = clamp((mask − Min)/(Max − Min), 0, 1), 1 − a when Invert; each iteration φ = lerp(φ, filtered, a)
  (OpenVDB's approach; the docs only say below Min → 0, above Max → 1; linear in between is per OpenVDB).
  The mask is trilinearly sampled onto the SDF's grid in world coordinates.

**Different from Houdini / not done**:
- OpenVDB re-normalizes distances within the narrow band after each iteration (tracker normalize), which the docs don't mention; not done here (recomputing distances on a dense grid is too expensive);
  for |∇φ| = 1, follow it with Reshape SDF's redistance.
- Trim (setting outside the narrow band to the background value): a dense grid has no narrow band / background value; not done.
- Assume Uniform Scaling: our volumes are axis-aligned and derivatives are already computed per-axis spacing, so it isn't needed; the toggle wasn't added.
- Filter Voxel Radius only applies to Mean / Median (hidden on the panel for the two flows).
- Only accepts SDFs (fog raises an error, consistent with Reshape SDF).

**Existing tests changed in passing**: test_nodes.py's EXPECT_REFUSE gained PCG_VolumeSmoothSDF (the default input has no volume,
so it refuses like the other volume nodes).

**Mutations**: 22, 4 survived → handled as follows:
- The early return for `r <= 0` in `_median_cube`: equivalent → removed.
- The `np.where` where `∇φ = 0`: alpha is 0 there too, equivalent → removed, replaced by dividing directly by max(|∇φ|², ε).
- Changing the first derivative's 1/(2h) to 1/h: H|∇φ| is homogeneous of degree zero under uniform scaling of the first derivatives, so **equivalent**; the correct form is kept.
- Changing fy²(fxx+fzz) to fy²(fxx+fxx): the old test only measured zeros on the x axis (fy = 0) → added a test "after the flow, still symmetric under permutation of the three axes", killed.

## Volume Mix → PCG_VolumeMix

**Done** (all appended at the end, default = old behaviour):
- Mix Method gains `diff` (|A − B|), `divide` (A / B), `invert` (−A), `clamp` (clamp(A, Range)),
  `user` (Value expression). On the panel, copy_b's label changed to Houdini's "Copy" (token unchanged).
- `range_min` / `range_max` (Clamp mode), `value` (User mode), Dest / Source Pre-Add·Pre-Mul, Post-Add·Post-Mul,
  `use_clamp_min` + `clamp_min`, `use_clamp_max` + `clamp_max` (Houdini's "☑ Label [value]" row).
- Formulas per the docs' text: A′ = A·m + a, B′ = B·m + a, result′ = result·m + a, then Clamp.
  Pre / Post / Clamp apply to all modes (including this plugin's SDF modes). At default values these steps are **skipped entirely**
  (·1 + 0 would turn −0.0 into +0.0, measured in the tests), bit-identical to before the change.

**Different from Houdini / decided here**:
- User's Value uses this plugin's Wrangle syntax, not HScript: @value = V(A′), @value2 = V2(B′), @P = X Y Z,
  @ix @iy @iz = IX IY IZ, @bb / @bb2 = BBX… / BBX2… (the 0–1 position within A's / B's own bounding box).
  V / V2 take the values after Pre -- the docs say "A in the computation is set to A′", interpreted that way.
- Divide gives 0 where B = 0 (the docs only say A / B, without specifying division by zero).
- With only one input connected, Houdini looks for the Mix Group in the first input; our geo_b is a required input (making it optional would change an existing parameter); not done.
- Expand VDB Active Region: VDB-specific, not done.
- Panel: the Volume A / B labels changed to Houdini's Source Group / Mix Group; the factor label changed to "Blend".

**Mutations**: 16, 2 survived → handled as follows:
- The `max(ext, 1e-30)` guard on the `@bb` divisor: with resolution ≥ 2 and size > 0, ext can't be 0, equivalent → guard removed.
- The identity skip in `_affine`: the old test couldn't tell → added a bit-for-bit −0.0 test, killed.

## Voronoi Fracture → PCG_VoronoiFracture

**Done** (all appended at the end, default = old behaviour; as soon as any new option is not at its default the new path `_fracture_ex` is taken;
at default values not a single line of new code runs -- the tests also check "changing a new parameter that has no effect takes the new path, and the output is bit-identical to the default"):
- `group`: only faces in the group are fractured; faces outside the group are appended unchanged, piece = −1 (the docs don't specify how faces outside the group are handled; decided this way).
- `name_mode` (Overwrite / Append) + `fracture_namespace`. Append = original name + "-" + Namespace + prefix + number;
  cap faces (newly created, with no original name) borrow the name of the original part in the same cell. **The separator "-" isn't in the docs; our own choice**; with no name
  attribute, Append = Namespace + prefix + number.
- `compute_interior_normals` + `interior_cusp_angle`, `exterior_normals` (Preserve / Recompute / Do Not
  Compute) + `exterior_cusp_angle`: write **vertex** N. Preserve: if the input has N (point or vertex) it is reused, with point N promoted to vertices
  and the point N deleted (when both exist, shading only uses the vertex one); with no N and interior normals on, computed with the exterior cusp. Do Not Compute + interior
  normals on: the exterior gets smooth normals (cusp 180°, the docs' wording "compute smooth normals"). With interior normals off + Recompute, the cap faces'
  vertices are also computed with the exterior cusp (N is a vertex attribute and can't be only half written; not specified by the docs).
- `cell_point_attribute` (Primitive Cell Point: the seed's point number in the second input), `clip_piece_attribute`
  (Primitive Clip Piece: cap faces record the number of the piece on the other side, exterior faces −1; found by = the other seed nearest the centroid → the piece containing the cap face
  in that cell nearest the centroid; also correct after Partition).
- `exterior_group`, `merge_groups` (on = old interior groups accumulate and existing exterior groups are kept unchanged; off = the interior group only has this run's
  caps, exterior group = all the original faces). Default on = old behaviour (the old code already accumulated interior groups).
- `copy_cell_attributes` (names, wildcards allowed) + `copy_to_points` / `copy_to_prims`.
- `cut_plane_offset`: each bisecting plane moves offset/2 towards its own cell's seed, leaving a gap of width offset between pieces (**whether the gap is offset or
  2×offset the docs don't say**; decided as offset); the pruning condition changes accordingly (tested).
- `connectivity_partition` (None / Overwrite / Maintain): Overwrite renumbers by (original piece number, connected part);
  Maintain keeps the original number for the part with the most faces in each piece, the rest go after the highest number (**which part keeps the original number the docs don't say**; decided as the most faces).

**Still different from Houdini / not done**:
- Piece numbering: ours has always been "after deduplicating and sorting the seeds, non-empty cells numbered in order"; Houdini goes by cell point number. The default behaviour can't change,
  so Primitive Cell Point was added to let users get the point number.
- The second output Constraint Geometry (one point per piece + lines between neighbours) and Copy to Constraint Points: not done (it would change
  RETURN_TYPES; better as a separate task).
- Triangulation (Auto Detect / Use Existing): we don't do Delaunay, we cut planes cell by cell; this parameter has no counterpart.
- Attribute Name Prefix: not done (minor). Snapping Tolerance ≈ our Cap Tolerance (not exactly the same semantics).
- The docs give no defaults for Interior / Exterior Cusp; 40 / 60 are used. Houdini's Compute Interior Normals probably defaults to on;
  ours defaults to off (= old behaviour).
- Cap Type and Max Pieces are this plugin's extensions, kept.

**Mutations**: 37, 9 survived → handled as follows:
- Pruning distance not reduced after the offset: added a test "seeds 2 apart, offset 1.2, plane moved into the geometry", killed.
- With Merge off, deleting the old interior group first / overwriting the interior group at the end: each makes the other redundant → the former removed, the latter killed by a test.
- The single-seed special case: `cell()` with one seed makes no cuts, equivalent → removed.
- Piece number arange vs cell number: added a test "seed outside the geometry → empty cell → numbers still compact", killed.
- The fallback when Clip Piece can't find a cap face: both sides of a cut always get caps, so it can't happen → removed.
- Clip Piece taking the first vs the nearest: added a test of Clip Piece after Partition, killed.
- Which part Maintain keeps: added a test with two parts of different face counts, killed.
- Interior faces using the interior cusp: added a test "two cap faces in three pieces at 45°, cusp 40 hard / 60 smooth", killed.

## Boolean Fracture → new node PCG_BooleanFracture

PCG_Boolean's shatter mode outputs three pieces A∩B / A−B / B−A, without Boolean Fracture's piece naming, inside/outside groups or normals;
stuffing a dozen parameters that only apply under shatter into Boolean isn't appropriate, so **a new node** (nodes_sop2.py + geo/boolfracture.py,
icon voronoi, panel g12), and sop_map's "Boolean Fracture" now points to it. PCG_Boolean is untouched. (As with Smooth SDF: not [C];
adding a new node was my judgement.)

**Done**: Group / Name Attribute (Overwrite / Append) / Fracture Namespace / Piece Prefix / Compute Interior Normals /
Interior Cusp / Exterior Normals (three modes) / Exterior Cusp / Attribute Name Prefix / Primitive Piece /
Copy Cutting Surface Attributes (prim attributes only) / Interior Group / Exterior Group / Merge with Existing Groups /
Interior Seams / Exterior Seams / Pieces Inside Cutting Geometry / Surface Inside Cutting Geometry /
Treat Cutting Geometry As (Surface / Solid) / Detriangulate (All / Only Unchanged / No Polygons). The report outputs the piece count.

- Each connected piece is one piece, numbered in the order of the boolean result. Origins are tracked with manifold's face_id (A's faces = prim number, cutting faces = 2³⁰ + prim number),
  so A's prim attributes / prim groups can be carried back to exterior faces by origin; interior faces are zeroed / cleared.
- Surface cutting: each **connected** cutting surface is extruded backwards along its average normal by 2× the total bounding-box diagonal into a half-space solid, then booleaned, so the cut lies exactly on the original cutting surface.
- Detriangulate: faces that weren't cut (same triangle count as the original fan triangulation, all original corners present) are restored to the original polygons; in the All mode, cut ones are
  paired and merged into quads in batches by source prim (Boolean's detriangulate, a single pairing pass, not full n-gons).
- Normals reuse Voronoi Fracture's `_normals` (same rules as the previous section). Compute Interior Normals defaults to on (new node, following Houdini's convention).
- Names: with Append, the whole piece uses the original part's name (interior faces borrow the exterior faces') + "-" + Namespace + prefix + number; the separator is the same self-chosen one as Voronoi Fracture's.

**Different from Houdini / not done**:
- **Surface cutting surfaces must pass through the whole object and not fold back along the average normal**: in Houdini a surface that only cuts halfway in just makes a slit; here the side walls of the extruded solid would
  cut the object through. A closed cutting solid treated as Surface raises an error (average normal 0), suggesting Solid instead.
- Treat Geometry As: only Solid is supported (needs a closed manifold, as with Boolean); the parameter wasn't added.
- Point / vertex attributes aren't carried (manifold only gives positions); the Point / Vertex items of Copy Cutting Surface Attributes are not done.
  So with Exterior Normals = Preserve the input N can't be carried over either (equivalent to "no N").
- The second output Constraint Geometry not done (as with Voronoi Fracture).
- Assume seam polygons are flat / Collapse tiny seam-adjacent edges / Edge length threshold: not done (manifold's output has no
  tiny seam edges; Detriangulate's coplanarity tolerance is fixed at 0.5°).
- Faces selected by Group must themselves form a closed solid (e.g. one of several pieces), otherwise manifold refuses. Faces outside the group are appended unchanged, piece = −1.
- Open polylines in the input don't go into the boolean and are absent from the output (as with Boolean).

**Existing tests changed in passing**: test_nodes.py's EXPECT_REFUSE gained PCG_BooleanFracture (the two default inputs are the same closed mesh, and Surface
mode refuses).

**Mutations**: 28, 12 survived → handled as follows:
- Half-space solid boundary-edge check `== 1` changed to `>= 1`: added a test of the half-space solid's triangle count / volume, killed.
- The area check when restoring polygons: with the same triangle count and all original corners present, the area is necessarily the same → removed. The triangle-count check is **kept, but no test can kill it**:
  it guards against "a neighbouring face was cut and this face gained a T-junction" (restoring would leave a crack); I couldn't construct an input that triggers it -- recorded here honestly.
- `ins or flag`: Solid has only one cutting solid and cuts only once, equivalent → simplified to flag.
- Interior faces clearing A's numeric / string attributes: test added, killed.
- Append taking the exterior faces' name: interior face names are already cleared, equivalent → simplified to "the first non-empty name".
- Accumulating the old inside group with Merge on: test added, killed.
- The two Interior Seams mutations (ignoring origin / using prim number instead of the cutting surface's connected piece): added a test with a 0.5-cell cutting surface, killed.
- Triangulating only closed polygons: added a test "mixed with open polylines", killed.

## Voronoi Split → PCG_VoronoiSplit

**Done** (appended at the end, default = old behaviour): `use_weight` + `weight_attribute` (Houdini's "☑ Weight Attribute [name]"),
`method` (Power Distance / Ratio), `offset`.
- Power Distance: weights are sphere radii, the cutting plane is where the powers are equal, |x − a|² − w_a² = |x − b|² − w_b² (power diagram; equal weights = ordinary Voronoi).
- Ratio: the ratio of the cutting plane's distances to the two points = the ratio of the weights (t = w_a / (w_a + w_b)); weights must be > 0.
- Offset: the cutting plane is moved by offset (world distance) along the line between the two points. **The docs only say "along the segment direction"; the direction is set from lower → higher point number** (we have no clip polyline,
  so both sides use the same plane and no gaps leak). The docs give no formula for either Method; the above follows the textual definitions.
- With these on, the two shortcuts "assign a whole face to one cell" and "filter candidate cells by nearest distance" no longer hold, so all selected faces take the cutting path, and each triangle is compared against all cells
  (slow: triangle count × cell count²).

**Still different from Houdini / not done**:
- Houdini 2.0 cuts along **clip polylines from the second input** (only between the two points a polyline connects); ours is the full Voronoi between all pairs of cell points.
  This is a structural difference, not changed; Ratio / Offset give one plane per pair in the full Voronoi, so with three or more points cells may overlap or leave gaps
  (Houdini cutting segment by segment along polylines probably has the same problem; the docs don't say).
- Create Interior Surfaces / Primitive Clip Point: we cut surfaces and don't cap interior faces (for solid fracturing use Voronoi Fracture); not done.
- Primitive Cell Point: the existing prim attribute `cell` is the cell point's point number (can't be renamed).
- Snapping Tolerance: not done (cut points are computed exactly, with a relative tolerance of 1e-12 internally).
- Clip Points Group (selecting a point group on the input): our cell points are a separate second input; not changed.

**Mutations**: 12, 2 survived → handled as follows:
- Offset not divided by the line length: the old test with points 1 apart couldn't tell → added a test with points 2 apart, killed.
- Still filtering candidate cells by nearest distance when weighted: added a test "a distant point with a large radius takes over in front of another point, fine mesh", killed.

## [C] IsoOffset → new node PCG_IsoOffset

Per rule [C], PCG_Convert is untouched (its volume_sdf / volume_fog modes stay as they are); a new PCG_IsoOffset is added (nodes_sop2.py +
geo/isooffset.py, icon volume_new, panel g12), and sop_map's IsoOffset now points to it.

**Done**: Output (Iso Surface / Fog Volume / SDF Volume), Mode (Ray Intersect / Minimum / Point Cloud / Implicit Box /
Implicit Sphere), Name, Uniform Sampling (Max Axis / X / Y / Z Axis + Divs, By Size, Non Uniform) + Uniform Sampling Divs /
Sampling Divs / Div Size, Override Bounds + Minimum / Maximum Bound (or the bounding box of the second input Reference Bounds), Pad Bounds,
Offset, Invert Sign.

**Different from Houdini / decided here**:
- Ray Intersect **is not ray intersection**: it uses the same exact SDF as Convert / Reshape SDF (exact narrow-band distance + pseudo-normal / flood fill for the sign).
  Closed meshes give the same result; for open meshes that can be flooded into, the result is unsigned (Houdini's ray method decides inside/outside from intersections). Laser Scan / Fix Signs /
  Force Bounds / Tolerance / Sign Sweep are parameters of the ray method and sign fixing; not done.
- Divs is the **number of grid points** (this plugin's volumes sample at grid points, with the end grid points on the bounding-box corners); Houdini's is the voxel count. When not an integer multiple, the bounding box is expanded symmetrically on both sides to whole cells.
- The docs don't give Offset's sign: decided as "positive grows outwards", field = distance − Offset; the default bounding box is expanded by max(Offset, 0).
- Pad Bounds adds one voxel (docs: "a layer of voxels outside the boundary").
- Fog: clamp(½ − field / voxel size), a linear transition one voxel wide at the surface (the docs only say "boundary cells have interpolated values").
- The bounding sphere of Implicit Sphere: centre = bounding-box centre, radius = the maximum distance of the points from it (the docs don't say how it's chosen).
- Point Cloud: distance to the nearest point, signed by (x − p)·N when there is N. Num Neighbour (estimating the local surface from k neighbours) not done.

**Not done**: Tetra Mesh / Tetra Skeleton / Tetra Solid / Cubes outputs; Meta Balls, Implicit Plane (the docs don't say which plane),
Volume Sample, Rebuild Volume Sample modes; Override Output Divs; Build Polygon Soup (we have no polygon soup prim);
the whole File Mode tab (reading/writing .simdata / .sdf).

**Mutations**: 17, 3 survived → all got tests (Non Uniform voxel size / origin, Implicit Sphere taking the maximum distance, an error on reversed Bounds), killed.

## [C] Intersection Analysis → new node PCG_IntersectionAnalysis

Per rule [C], PCG_Boolean is untouched (seam mode unchanged); a new PCG_IntersectionAnalysis is added (nodes_sop2.py + geo/intersectanalysis.py,
icon bool, panel g12), and sop_map now points to it.

**Done**: Group A / Group B; only the first input connected = find self-intersections (skipping edges and triangles that share points), second input connected = find intersections between the two; the output is points only
(without the input geometry); point attributes Input Number / Primitive Number / Primitive UVW (empty attribute name = not written, corresponding to Houdini's toggles).
- Intersection point = where an edge of one prim (or a segment of a polyline) passes through a triangle of another prim (Möller–Trumbore, t ∈ [0, 1]). The two endpoints of the
  intersection segment of two triangles are such points, so all are found. Shared edges are counted once; when an edge passes exactly through a fan diagonal, both fan triangles hit
  once each, so (same edge × same prim × same position) is deduplicated.
- Pairs are first filtered by bounding box, then computed vectorized in chunks. No BVH, so it's slow at scale (edge count × triangle count).

**Decided here (the docs don't say)**: attributes all come in **pairs**: [the prim the edge belongs to, the prim of the triangle passed through]. Input Number / Primitive
Number are int ×2, Primitive UVW is float ×6 (the two uvw laid out in sequence). The uvw on a polygon = the barycentric coordinates (u, v, 0) in the triangle of its fan triangulation
(Houdini's polygon prim uv is defined differently); on a polyline = (segment number + t, 0, 0).

**Not done**: Point Num (the docs only say "point numbers related to the intersection point", not which point); intersections between two polylines; when an edge and a triangle are coplanar
(the intersection is a segment) no point is output. Houdini requires closed polygons to be triangles; for non-triangles we compute on the fan triangulation anyway (wrong for concave polygons).

**Mutations**: 12, 5 survived → handled as follows:
- The upper bound t ≤ 1 for segments: the old test was blocked by the bounding-box prefilter → added a test "only the extension of the line touches a slanted plane", killed.
- The fan triangle number / barycentric coordinates of the closing edge (n−1 → 0), and skipping the closing edge: in the old test the intersection points all lay on edges already claimed by other faces → added
  a test on a single quad's closing edge; all three killed.
- The guard `|a| > eps` (edge parallel to the triangle): without it, a = 0 gives 1/0 = inf and u becomes nan, all comparisons are False, so the result is equivalent,
  but a division-by-zero warning is raised → **kept**, noted here.

## [C] File Merge → new node PCG_FileMerge

Per rule [C], PCG_ImportMesh is untouched; a new PCG_FileMerge is added (nodes_sop2.py + geo/filemerge.py, icon filecache, panel g12),
and sop_map now points to it.

**Done**: Geometry File (with `$SLICE`, also accepts `${SLICE}`), Reload Geometry (changing the number forces a re-read), Merge Range (start / end / inc,
end inclusive, inc may be negative), Merge Variable, Delete Points from Other Files, Missing File (Report Error / No Geometry).
- Each file: .npz is read as this plugin's geometry cache (written by File Cache); everything else goes through Import Mesh's format sniffing (all parameters at defaults).
  Relative paths are looked up in input / output / the current directory per Import Mesh's rules.
- IS_CHANGED uses the mtime + size of all slice files as the fingerprint (recomputed after a file is rewritten).
- The report lists which files were read and which were skipped.

**Decided here**: the point attribute name used by Delete Points is `slice` (the docs only say "the particle slice attribute"); if a file doesn't have this attribute, nothing is deleted.
Zero-padded forms like `$SLICE4` aren't mentioned in the docs; not supported.

**Not done**: Load (All Geometry / Info / Info Bounding Box -- our readers don't read file-header metadata); Cache Length (ComfyUI
caches by input; no counterpart); bgeo and other Houdini formats (the readers don't support them anyway).

**Existing tests changed in passing**: test_nodes.py's EXPECT_REFUSE gained PCG_FileMerge (the default file doesn't exist, error).

**Mutations**: 7, all killed.

## [C] Intersection Stitch → skipped

What it would take: "cut two geometries at their intersection lines, stitch the intersection lines into both meshes and share the points" (Group A / B, Proximity Tolerance, Split Curves).
That needs re-triangulating polygons along the intersection lines (constrained triangulation / polygon splitting) and handling nearly coincident points; it's a standalone mesh-editing project, not something
that can be done right by adding parameters to an existing node; a "look-alike" version (e.g. only outputting the intersection lines) would be misleading. That sop_map row is left as it was (partial → PCG_Boolean seam).

## [C] Lidar Import → skipped

It needs LAS / LAZ (LAZ is a compressed format needing a dedicated decoder) / E57 (XML + binary blocks) readers, plus a whole set of attributes for classification, returns, scan angle etc.,
beyond the plugin's scope (the brief also explicitly names "lidar formats"). Import Mesh can already read PLY point clouds; that sop_map row is left as it was.

## Behaviour differences between the code and Houdini (found while reading the code, not changed)

- **PCG_VoronoiFracture**: piece number = after `np.unique` deduplicates and **sorts** the seeds, non-empty cells are numbered in order; Houdini goes by cell point number.
  Feed the same points in a different order and the piece numbers change. Default behaviour not changed; Primitive Cell Point was added so users can get the point number.
- **PCG_Boolean** (including shatter): manifold only carries back positions, so the input's point / vertex / prim attributes and groups are all lost (Houdini carries them).
  The new Boolean Fracture brings prim attributes and prim groups back via face_id; Boolean itself is untouched -- the same approach could be used on Boolean.
- **PCG_Convert's volume_fog**: for meshes it goes through `points_to_volume` (splatting density from points), not a solid fog with "inside = 1";
  dense and sparse meshes give very different results. Houdini IsoOffset's Fog is 1 inside. The new IsoOffset node is solid.
- **PCG_VolumeMix**: geo_b is a required input; with only one input connected Houdini looks for the Mix Group in the first input.
- **PCG_VoronoiSplit**: cuts by the full Voronoi between all pairs of cell points; Houdini 2.0 only cuts between point pairs connected by a clip polyline (the second input is polylines).

## Wrap-up

- 6 new nodes: Volume Smooth SDF, Boolean Fracture, IsoOffset, Intersection Analysis, File Merge (plus the [C]
  Intersection Stitch and Lidar Import, skipped). Icons, panel specs (g12) and sop_map are all set up; tools/nodes.json has been regenerated,
  test_icons.mjs passes.
- Existing tests changed: test_nodes.py's EXPECT_REFUSE gained PCG_VolumeSmoothSDF / PCG_BooleanFracture / PCG_FileMerge.
- Regressions run: test_audit_s9_volume_fracture.py, test_nodes.py, test_panel.py, test_panel.mjs, test_icons.mjs,
  test_sop_map.py, test_sop_volume.py, test_behavior_fixes.py, test_houdini_fixes.py, test_geoattrs.py,
  test_options98.py, test_options99.py, test_sop_meshedit.py, test_meshio.py, test_geocache.py, all green.
