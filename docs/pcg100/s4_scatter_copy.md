# s4_scatter_copy audit notes (pcg100)

Tests: `test_audit_s4_scatter_copy.py` (runs in both layouts: the package path walks up to find `comfyui_pcg`, no git needed).
"Bit-for-bit identical to before the change at default values": CASES at the top of the file registers a set of node calls **using only old widgets**;
GOLDEN holds the digests (first 16 hex chars of sha1) obtained by running the same file with `--digests` on the pre-change commit c87c5d9, hard-coded in the file.
`--digests` exits before running any new feature, so the file can produce digests against the old code too.

The mutation-testing script is in the scratchpad (replaces [file, original string, mutant string] one at a time, runs the tests, restores); after each run
`git diff --stat` confirms the source files are restored and `__pycache__` is cleared.

## Scatter → PCG_Scatter (done, Scatter on Voxels skipped)

Docs re-fetched from the Scatter 2.0 page.

Done (new widgets all at the end of INPUT_TYPES, default = old behaviour; the new input `density_texture` is an optional COP connection):
- `generate` (Generate): `by_density` (old behaviour, first item) / `count_per_primitive` / `in_texture_space`.
- `count_per_prim_attribute` (Count per Prim Attribute): an integer, or the name of an integer prim attribute; error if it is neither.
  Exactly that many points per prim; Relax runs per prim (points don't wander onto other prims). Error if the total exceeds the hard cap (20 million).
- `density_texture` (Density Texture, optional COP input) + `texture_uv_attribute` (UV Attribute, default uv).
  - By Density: the texture is sampled at **the scattered points' own uv**, rejection-sampled by tex / max(tex) (same idea as Scatter from Map;
    density precision isn't limited by mesh resolution). With Force Total Count, scatter in several rounds until there are enough, then truncate; without it, candidate count =
    Density Scale × weighted area × max(tex), and the expected number of accepted points is exactly Density Scale × ∫(density × texture).
  - In Texture Space: exact sampling by the per-pixel CDF (texture constant per pixel).
- In Texture Space: scatter in the uv unit square; each sample produces a point in every uv triangle it lands in (uniform grid for candidates +
  exact barycentric coordinates); Relax runs in texture space (the uv triangles are fed to the existing `_relax` as flat triangles at z=0).
  Relax radius √(1/(Nπ)); Max Relax Radius clamps in texture-space units (as the docs say).
- Output: `use_out_density/out_density_name` (Output Density Attribute, default name density),
  `use_out_radius/out_radius_name` (Output Radius Attribute, default name pscale), `use_out_id/out_id_name`
  (Output ID Attribute, default name id), `out_texture_space` (Output Radius and Density in Texture Space).
  On the panel these are Houdini-style "☑ Label [name]" rows.
- Attributes tab: `point_attributes` ("*"), `vertex_attributes` ("*"), `primitive_attributes` (""),
  `detail_attributes` (""), `detail_as_detail` (""). The first two filter the existing interpolation; prim / detail attributes are copied as-is
  (prim from the source prim the point lies on, detail broadcast to every point, strings copied too; output attributes already written are not overwritten);
  Detail as Detail stays on the detail.
- Panel: Generate / Count per Prim Attribute / UV Attribute go into the Density tab; the Count per Primitive mode hides
  Force Total Count / Density Scale / Max Point Limit (the code really doesn't read them in that mode); the In Texture Space mode greys out
  the density attribute / Override Prim Area / Primitive Seed (not read in that mode, see "still different" below).

Still different from Houdini / not done:
- **Scatter on Voxels Independently skipped**: our Scatter only scatters on polygon surfaces, not on volume prims.
  Likewise the docs' density and radius formulas for curves (per unit length) and volumes (per unit volume), and Use Area for 2D Volumes, are not done.
- The In Texture Space mode **does not read the density attribute / Override Prim Area / Primitive Seed** (the docs say the density attribute also applies in this mode;
  not done, greyed out on the panel).
- With a texture (or density attribute), Relax still uses a **uniform radius** (that was the old behaviour), which flattens density gradients somewhat;
  Houdini sets the radius from the local density.
- In Houdini the four Attributes-tab fields also accept **group names**; we only copy attributes, not groups.
- Vertex attribute interpolation has **never been controlled** by the Interpolate Source Attributes toggle (old behaviour: the node only passed the toggle to
  the point-attribute path; the vertex path defaults to True). Old behaviour kept; you can now clear Vertex Attributes to turn it off.
- The audit said count's label "Force Total Count" clashes with the toggle's name: that is just how the "☑ Force Total Count [1000]" row is displayed
  (toggle drawn inside the value row), not two parameters with the same name; not changed.

Not made clear by the docs, decided here:
- The texture uses **channel 0** of the default layer (C), negative values treated as 0; nearest pixel (pixel x covers [x/W,(x+1)/W), row 0 = smallest v).
- In In Texture Space, the point count means the count **in the unit square** (the docs describe Max Point Limit as "in the unit square");
  when the uv doesn't fill the square, the actual count is lower than Total Count. Where uv islands overlap, one sample produces a point on each of them.
- Without Force Total Count: with no texture, Density Scale = expected total in the square; with a texture, total = Density Scale × mean(tex).
- Density output (computed at the points' **final** positions, "measured after relaxation"): physical density = K × (density attribute × area coverage ratio) ×
  texture value; K is Density Scale without Force Total Count, and = actual point count / ∫relative density when Force Total Count is on or Max Point Limit truncated it
  (with a texture, ∫ is estimated from the acceptance rate). Count per Primitive: that prim's point count / that prim's weighted area × relative density.
  Texture-space density = physical density × 3D area / uv area. Triangles with zero 3D area give inf.
- Radius = 0.537/√density (the surface approximation given in the docs), clamped to Max Relax Radius when that is on; not multiplied by Scale Radii By.
- ID = 0..n-1 in output order (after shuffling).
- Count per Primitive doesn't read Density Texture (docs: only used by the other two modes); not subject to Max Point Limit (docs don't say;
  the counts are given per prim by the user), only the hard cap. Negative counts scatter no points.

Mutation testing: first round, 22 of 43 mutants survived; handled as follows:
- Killed by new tests (14): negative texture values clamped to 0, Max Relax Radius clamping the relax radius, two `capped` sites (after Max Point Limit truncation
  K is derived back from the actual count), texture-space relax radius (nearest-neighbour distance falls in (r, 2r]), t/u/v updated after per-prim Relax
  (interpolated uv consistent with position), density divided by prim area (using a 2×2 grid), rejection probability divided by max (texture max 0.5),
  Max Point Limit truncating the texture mode, the rejection random stream decorrelated from the triangle-picking stream (with a ramp texture the mean of v must be 1/2),
  density multiplied by relative density / by texture value, a prim attribute with the same name not overwriting an output attribute, the total cap counting only positive counts (the test temporarily sets
  MAX_POINTS_HARD to 100).
- Proven equivalent, code removed (4 sites): the "clamp negatives to 0" in both the constant and attribute paths (_sample_prim_counts already only samples prims with base > 0),
  `np.where(wp > 0, cp, 0)` (prims with zero weight can't produce points; K has its own where), `len(idx) < 2` before per-prim Relax
  (_relax itself returns < 2 points unchanged), the condition that reads the texture only when `generate != count_per_primitive`
  (that mode never touches grid).
- Equivalent, kept (only affect speed): the grid resolution G in `_locate_uv` (setting it to 1 gives the same result, slower), `live` which drops triangles entirely outside the unit square
  (they'd be rejected by the barycentric test anyway), the `break` once rejection sampling has enough (without it we just scatter a few more rounds and keep the first n),
  the early return for an all-black texture (without it, 32 rounds all rejected → empty). The pixel CDF's searchsorted "right"/"left" differ only when the random number
  exactly equals a cumulative value (measure zero); "right" kept (semantically it can never pick a zero-weight pixel).

Changes to existing tests: the hard-coded Scatter tab list in `test_panel.mjs` gained "Attributes".

## Scatter and Align → PCG_ScatterAlign (partial)

Docs re-fetched. Our existing `mode` (panel label Point Count Method) is Houdini's Point Count Method,
not Houdini's Mode; Houdini's Mode is the newly added `scatter_mode`.

Done (new widgets all at the end, default = old behaviour; the new input `points` is an optional GEO):
- `scatter_mode` (Mode): `surface` (Scatter Points on Geometry Surface, old behaviour) / `existing_points`
  (Add Attributes to Existing Point Cloud) + `point_group` (Point Group).
- `by_spacing` (By Point Spacing) appended to `mode` + `spacing`.
- `use_density_attribute` + `density_attribute` (Use Density Attribute).
- `use_emergency_limit` + `emergency_limit` (Emergency Limit; the report records the point count before truncation).
- `normal_direction` (Z / X / Y / Custom) + `normal_custom_*`, `forward_direction` (Y / X / Z / Custom)
  + `forward_custom_*`: which axis of the instance aligns to the normal / forward. Only orient changes (R = M·Iᵀ); the N / up attributes are still
  the world-space normal and forward (Copy to Points reads orient first).
- `rotation_range` (symmetric = the old ±Random/2; min_max = Houdini's Min Angle / Max Angle),
  `min_angle` / `max_angle`, `round_rotation` + `round_to` (Round Rotation Around Normal / Round to
  Multiple Of), `offset_angle` (Offset Angle, after the random rotation, before the Cone tilt).
- Attributes tab: `use_radius_attribute/radius_attribute` (Output Radius Attribute, default pscale),
  `use_orient_attribute/orient_attribute` (Output Orient Attribute, default orient), `use_prim_uvw/
  prim_uvw_attribute` (Prim UVW, off by default, name sourceprimuv), `surface_point/vertex/primitive/
  detail_attributes` (Surface ... Attributes, same interpolation / copy-as-is path as Scatter).
- `tag_name` (Tag Name): when non-empty, writes a string point attribute tag.
- Panel: split into Orientation / Point Generation / Attributes tabs as in Houdini; the existing_points mode hides parameters the code
  doesn't read in that mode (Group, Point Count Method and its parameters, the Point Generation tab, Prim UVW, Surface attributes).

Still different from Houdini / not done:
- **Scatter Points Around Constraint Points not done** (along with Scatter Radius Scale, Add Scatter Noise's
  Roughness / Amplitude / Element Size, Avoid Constraint Points): it needs a whole "constraint points attract / repel" relaxation,
  not just a few extra parameters.
- Target Forward Vector (No Target / X / Y / Z / Custom / Attribute) and the whole Blend Normals With set not done;
  our Up Vector is equivalent to Target = Custom. Scale Cone / Offset / Blend by Attribute,
  Remap Using Distribution Ramp (Rotation Distribution Ramp) not done.
- In Houdini Coverage is a separate parameter + Coverage Attribute; ours is still a mode of Point Count Method
  (By Size (Coverage)); Coverage Attribute not done. By Size's Uniform Scale not done.
- By Point Spacing's Scale Mode / Spacing Attribute / Minimum Spacing and "multiply by pscale when the points have it" not done.
- Overlap Tolerance not done (our Remove Overlapping pushes points apart rather than deleting them -- old behaviour).
- Defaults differ from Houdini: Normal Direction defaults to Z (Houdini: Y), Surface Point / Vertex Attributes
  default to empty (Houdini: *), Tag Name defaults to empty and no tag is written when empty (Houdini: $OS and always written) -- all so that default = old behaviour.
- Match Groups not done.

Not made clear by the docs, decided here:
- By Point Spacing point count = area / ((√3/2)·Spacing²) (hexagonal close packing, which relaxed points tend towards).
- Density attribute: in By Density, count = Density × Σ(triangle area × mean of the attribute at its three corners, negatives as 0);
  the other three modes keep their count, it only affects the distribution (the docs say under Number of Points "density only affects the distribution").
- The Forward axis is first orthogonalized against the Normal axis; error if they are parallel (no silent axis swap).
- Round rounds to the nearest multiple; the symmetric mode can Round too.
- existing_points: normal = face normal of the triangle containing the nearest surface point on the first input (also writes sourceprim, −1 for unselected points);
  if the first input has no faces, use the point's own N, failing that +Y. Unselected points: attributes they already had are kept, ones they didn't have get the "unit instance" value
  (pscale 1, orient (0,0,0,1), N +Z, up +Y, tag empty string). If nothing is selected, output unchanged.
  Relax / Remove Overlapping / Emergency Limit are not used in this mode (docs: the Point Generation tab is unavailable in this mode).

Mutation testing: 8 of 37 mutants survived →
- Killed by new tests: density attribute averaged per triangle with negatives clamped to 0 (exact integral of a linear attribute 64 / 16), Round rounds to nearest
  (50..80 → 90), face normal direction not flipped (the old test used abs), "unselected get 1" for a renamed radius, nothing selected → output unchanged.
- Equivalent, code removed: `interpolate_attribs=bool(pattern)` (an empty pattern selects nothing anyway; changed to always True);
  the special case `R = M if I is identity else M·Iᵀ` (after removing it the 7 old-call digests are still bit-identical); "pscale" in the unit table
  (when the radius name is pscale it's overwritten by the radius_attrib entry; when renamed, pscale has already been deleted).

## Point Replicate → PCG_PointReplicate (partial)

Docs re-fetched: the page **doesn't list the Shape / Orientation menu items** and gives no defaults; it only says the cloud is generated in local space
(centred at the origin, aligned along the z axis) and then placed on each input point by the Copy / instancing rules, with Center Z along the alignment vector (N or v).
The names Circle / Line / Grid come from the audit record.

Done (new widgets all at the end, default = old behaviour):
- `circle / line / grid` appended to `shape`: generated in local space, Size × → + Center → × Uniform Scale →
  Velocity Stretch → the source point's instance transform (`xform.point_matrices`: transform / orient / N or v + up / rot /
  scale / pscale / trans / pivot, the same set as Copy to Points).
- `orientation` (XY / YZ / ZX Plane), `center_*`, `size_*`, `uniform_scale`, `velocity_stretch`
  (None / Scaled / Ignore Geometry Scale) + `velocity_scale`. These only apply to circle / line / grid
  (hidden on the panel for the old four shapes; the old four shapes still use Radius × radius attribute, and Radius is hidden for the new three).
- Attributes tab: `copy_source_attributes` + `source_attributes` (Copy Source Attributes / Attributes,
  default "*"), `inherit_velocity` (1), `radial_velocity` (0), `keep_source_attributes` +
  `source_point_attribute` ("source", always written in the old behaviour) + `source_index_attribute` (empty = not written),
  `create_output_group` + `output_group`.

Still different from Houdini / not done:
- Our existing sphere / shell / disk / gaussian are not Houdini shapes (this plugin's extension, kept); Houdini's
  Sphere is presumably also "local space + instance transform", while our sphere is in world space with Radius × pscale -- old behaviour not changed,
  and no separate Houdini-semantics sphere added (the docs don't give its size convention).
- **File / SOP shapes not done** (reading the cloud from a file / external SOP, writing shapeptnum): the docs don't say how each point takes points from the shape.
- The Noise tab (Add Noise, Noise Type, Frequency, Offset, Amplitude, Roughness, Attenuation, Turbulence) not done.
- Quasi-Stratified Sampling not done.
- In Houdini Generate From Attribute is "attribute as probability × Points per Point"; our Count Attribute is
  "attribute used directly as the point count" (old behaviour), not changed; stated in the panel help.
- Attributes to Transform not done (we don't transform inherited direction attributes like N / v -- old behaviour).
- With Copy Source Attributes off, groups are still copied (it only covers attributes).

Not made clear by the docs, decided here:
- Local cloud: circle = uniform over a disc of diameter 1 in the plane; grid = uniform over a square of side 1 in the plane; line = uniform along a segment of length 1 along the plane's **normal axis**
  (XY → local Z → along N / v by default, for trail-like uses). All are random (the docs say Seed is for random clouds).
- Center is added after Size (Size doesn't scale Center), then the whole thing is multiplied by Uniform Scale.
- Velocity Stretch: local z × |v| × Velocity Scale; with Ignore Geometry Scale, pscale and
  scale are removed from the instance transform. Error if the input points have no 3-component v (no silent flattening).
- Radial Velocity: v += radial × (new point − source point) (the offset vector, not normalized); created if there is no 3-component v.
  The original points kept by Keep Input are not affected by Inherit / Radial.
- With Copy Source Attributes off and Keep Input on: attributes not copied keep their original values on the original points and get 0 / empty string on the copies.
- Source Index: counts from 0 within each cluster; kept original points get −1.

Mutation testing: 9 of 27 survived → 6 killed by new tests (grid covers both sides, two illegal menu tokens raise errors, Radial creates v when it isn't
3-component, Ignore Geometry Scale also removes scale, pivot subtracted first, Stretch errors when v isn't 3-component);
code removed at 1 site (the len check in `if local and len(src)`: an empty array gives the same result going through);
1 equivalent kept: swapping the two in-plane axes of the ZX plane (circle / square are symmetric in both axes, same distribution).

## Transform Pieces → PCG_TransformPieces (partial)

Docs re-fetched using the xformpieces.html given by the audit (transformpieces.html is a 404). The docs don't list the Point Velocities menu items
(they only point to the DOP Import page).

Done (new widgets all at the end, default = old behaviour):
- `attribute_mode`: `match` (Match by Attribute, old behaviour) / `index` (Index by Attribute: the integer
  attribute value on the piece is the template point number, rest uses the same point number; rounded to nearest; out-of-range / negative pieces are left in place and recorded in the report;
  string attributes raise an error; this mode doesn't require an attribute of the same name on the template).
- `invert_transformation` (Invert Transformation): inverse transform. With rest connected, p = Mr(Mt⁻¹(q − Tt) + pvt − pvr) + Tr,
  direction attributes use Mr·Mt⁻¹; without rest, p = Mt⁻¹(q − Tt) + pvt. Chained with the forward transform they cancel out (tested with
  pivot / rest rotation).
- `center_pieces` (a toggle that is this plugin's extension, default True = old behaviour): without rest, the old implementation first moves the piece's bounding-box centre to
  the origin and then applies the template transform -- **this is not Houdini's behaviour** (Houdini does p' = M(p − pivot) + T directly). Turning it off gives
  Houdini's behaviour. Invert doesn't move the centre (that step isn't invertible); greyed out on the panel.
- `attributes_to_transform` (Attributes to Transform, default "N up v" = old behaviour).
- `copy_template_attributes` + `attributes_to_copy` ("*") + `groups_to_copy` ("").

Still different from Houdini / not done:
- **Point Velocities / Integrate Over Time not done**: needs the difference of transforms between frames, and the docs don't list the menu items.
- Attributes to Transform: our attributes have no type info, so we can only go by name -- the one named N is treated as a normal (inverse transpose + normalize),
  all other 3-component attributes as vectors (multiplied by M only); point-type attributes of the "point" kind (which need the translation added) can't be done. P is always transformed,
  not controlled by this pattern (in Houdini, if P doesn't match, positions don't move and prims aren't rotated either).
- The default Attributes to Transform is "N up v" (the docs don't give Houdini's default).

Not made clear by the docs, decided here:
- Copy Template Attributes: P is not copied (copying it would collapse all points onto the template points). When the geometry already has an attribute with the same name, component count and kind (numeric /
  string), unmatched points keep their original value, otherwise they get 0 / empty string; groups likewise (unmatched points keep their original group membership).

Mutation testing: 12 of 20 survived → 10 killed by new tests (under non-uniform scale N must go through the inverse transpose, illegal Attribute Mode,
Index = template point count also counts as out of range, point-number mapping for Index + rest, rounding of float indices, template / rest pivot in Invert,
the direction matrix for Invert with rest connected, with "* ^v" P must not be rotated again as a vector, existing groups kept, groups not copied when the toggle is off);
code removed at 1 site (the special case taking the old `_rotate_dirs` path for "N up v": the generic path selects exactly these three, 7 old-call digests unchanged).

In passing: `_rotate_dirs` (shared by deform2 / registration / deformers) gained an optional parameter names, default = the original
("N", "up", "v"); other callers behave the same (test_sop_xform / test_deform / test_audit_s2_poly all green).

## Extract Transform → PCG_ExtractTransform (core done, two items not done)

Docs re-fetched. Four Extraction Methods: Translation and Rotation / … and Uniform Scale /
… and Non-Uniform Scale / Full Transform. Our existing rigid / similarity / affine map exactly to methods 1, 2 and 4;
the panel labels were changed to Houdini's names (tokens unchanged).

Done (new widgets all at the end, default = old behaviour):
- `nonuniform` appended to `mode` (Translation, Rotation, and Non-Uniform Scale): fits R·diag(s). No closed-form solution;
  starting from the similarity solution, alternate (fix R, least-squares s per axis; fix s, Kabsch for R), 60 rounds. s may be negative
  (mirroring); R keeps determinant +1. The Standard output writes orient + scale (3 components), not pscale.
- `use_piece_attribute` + `piece_attribute` + `attribute_class` (Primitive / Point): one transform and one
  output point per piece (carrying the attribute of the same name). The point is placed at the **transformed piece centre**, pivot = the (weighted) centre of the reference piece -- Copy to Points
  copying the reference piece then lands it exactly on the target (the test checks all three Outputs the way point_matrices reads them). Pieces with too few points to fit
  only solve for translation, reported as `translation_only_pieces`. In the geo output each piece moves by its own transform; points not in any piece are unchanged.
- `output_attributes`: Standard Instance Attributes (old behaviour) / Transform Matrix (3×3) and Translation /
  Transform Matrix (4×4) (16 components, translation in row 4 -- matching the 4×4 convention point_matrices reads in this plugin; P at the origin,
  no pivot written, the whole transform is in the matrix).
- `compute_distortion` + `distortion_attribute` (default name distortion): per-piece residual RMS.

Still different from Houdini / not done:
- Standard output + Full Transform still writes a 3×3 transform (old behaviour); it is **not** decomposed into P / pivot / orient /
  scale / shear as Houdini does.
- "When a piece is a single packed prim, compare the prim transforms directly" not done (we have no packed prim transforms).
- The docs give no formula for the Distortion measure; we use the residual RMS (weighted root mean square of the distances from transformed reference points to target points).
- weight_attribute is this plugin's extension (Houdini doesn't have it), kept; in per-piece mode weights are normalized per piece.
- In whole mode (not per piece) the output point is still at t with pivot at the origin (old behaviour); only per-piece mode places it at the piece centre.

Mutation testing: 10 of 24 survived → 8 killed by new tests (illegal Attribute Class, no error when the whole point count is < 3 in per-piece mode, distortion of translation-only pieces,
pivot and translation for per-piece + weights, error when a piece's weights are all 0, N of points not in any piece not normalized, matrix4 doesn't write pivot);
code removed at 1 site (the bit in matrix4 that wrote pivot and then deleted it; now it's never written); 1 equivalent kept: the determinant correction of Kabsch in `_fit_nonuniform`
(without it R may be a reflection, but the final `_rs` moves the sign onto s, so M is unchanged).

## Cluster Points → PCG_ClusterPoints (partial)

Docs re-fetched. The page says the algorithm is k-means (random initial centres, determined by Seed), consistent with ours (we use k-means++ for initialization).

Done (new widgets all at the end, default = old behaviour; the second output "centre points" unchanged):
- `output` (Output): Cluster points (old behaviour) / Average points (one point per cluster, P = cluster mean, writes Size Attribute =
  bounding-box size + Padding) / Both (merged, groups clusterpoints / averagepoints) / Boxes (one bounding box per cluster + Padding,
  prim attribute cluster).
- `color_output` (Points / Colored Points / Colored Particles): one random Cd per cluster (average points and boxes get the same colour),
  points outside the group are white.
- `cluster_filter` (Cluster Filter): a cluster-number pattern, same syntax as point numbers (borrows groups.resolve); after filtering, points outside the group aren't output either.
- `weight` + `control_attribute2/3` + `weight2/3` (Control Attributes + Weight): each attribute multiplied by its weight, concatenated into the feature vector.
- `build_clusters` (Build Clusters): when off, the Output Attribute already on the points is used directly (points outside the group don't count);
  the second output still gives centre points + count.
- Averaging: `copy_point_attributes` (Copy Point Attributes from Cluster) + `max_sample_count`,
  `size_attribute` (default scale), `padding_min_*` / `padding_max_*`.

Still different from Houdini / not done:
- **Threshold Attribute / Weight / Initial Threshold / Goal Threshold not done**: they require changing the distance in the Lloyd iteration
  (adding a penalty term, threshold lowered each round from Initial to Goal), and the docs don't give the form of the penalty term.
- Control Attributes is "multiple" (a multiparm); we have a fixed three (the first is the original attribute).
- Colored Particles is the same as Colored Points (this plugin has no particle system).
- Our existing Group (not in the docs) and the second output (centre points) are kept.

Not made clear by the docs, decided here:
- The average point's P is the cluster mean (not the bounding-box centre); Padding is added at both ends of the bounding box, the average point doesn't move.
- Copy Point Attributes: a centre point's numeric attributes = mean over the Max Sample Count points in the cluster nearest to it; strings take the nearest point;
  attributes already written (Cd cluster colour, size, cluster) aren't overwritten. Max Sample Count defaults to 10 (the docs give no default).
- Cluster colour: random colour determined by (Seed, cluster number); same cluster, same colour.
- With Build Clusters off, cluster numbers may have gaps (e.g. only 0 and 2); average points / boxes are output only for non-empty clusters; the centre-point output is ordered 0..max,
  empty clusters with count 0.

Mutation testing: 10 of 22 survived → 9 killed by new tests (Build Clusters off + Group, with an existing cluster attribute points outside the group keep their original value and
don't enter the mean, gaps in cluster numbers, points outside the group are white, Boxes coloured, Copy doesn't overwrite already-written attributes, strings take the nearest point, Weight 2 takes effect);
code removed at 1 site (the useless built field in the report).

## HeightField Scatter → PCG_ScatterFromMap (partial)

Docs re-fetched (HeightField Scatter 2.0). The page **gives no point-count formula at all** and doesn't mention pscale / orient / N attribute names; it only mentions
footprint and tag. Our node takes a COP image + surface uv (not a heightfield mask layer); decode / filter / border /
oversample / uv scale and offset / Max Rounds are this plugin's extensions, kept.

Done (new widgets all at the end, default = old behaviour):
- `scatter_method`: `count` (Total Point Count using Mask Layer, old behaviour) / `density` (By Density using Mask
  Layer) / `coverage` (By Coverage using Mask Layer) + `density`, `coverage`, `outer_radius`.
- `variability`: `none` (old behaviour: no pscale written) / `uniform` / `normal` / `exact` + `range_min/max`, `spread`,
  `exact_scale`; writes pscale and footprint (= Outer Radius × scale).
- `randomize_orients` + `match_normals` (Match Normals with Terrain) + `randomize_up` + `randomize_yaw`:
  writes N and orient.
- `max_points` (Max Points, 0 = unlimited, old behaviour), `quantization`, `tag_name`.

Still different from Houdini / not done:
- **Per Point Count using Source Points not done** (along with Source Point Tag, Per Point Count Method (Poisson /
  Exact), Positioning Method (Offset / Origin / Ratio), Source Origin / Inner Radius): needs source points from a second input and
  ring placement, a whole separate generation logic.
- **Relaxation tab not done** (Relax Points, Self Overlap, Avoid Point Tag, Mask Cut Off, Iterations, Removing Rate,
  Stepping Ratio, Allow Out of Bounds Points, Point Removal Method): it's a "push apart by footprint + delete points at a rate"
  relaxation, and the docs give no algorithm; our node has always explicitly not done relax.
- Match Direction with Slope not done. Falloff (inner radius) not done.
- Keep Incoming Scatter Points / Keep Incoming Terrain / Instance on New Points / Define Pieces / Piece Attribute
  not done (that's the Copy to Points side, not part of this node).
- Defaults differ from Houdini: Variability defaults to none, Tag Name defaults to empty (both so that default = old output).

Not made clear by the docs, decided here:
- By Density: λ = Density (points per unit area where the mask value is 1), expected count = λ × ∫mask dA. Implemented as one round of
  "candidate count = λ × area × max(mask), keep by mask/max"; the count is random (this mode is inherently inexact).
- By Coverage: λ = Coverage / (π · Outer Radius² · E[scale²]) (each point's disc covers the Coverage fraction of the mask-weighted area).
  E[scale²]: uniform uses the analytic value (a² + ab + b²)/3; normal uses the pre-truncation approximation mean² + spread²; exact uses s²; none counts as 1.
- Normal Distribution: mean = midpoint of Range, standard deviation = Spread, then clamped to Range.
- Randomize Orients: the instance's +Y aligns to the normal (trees / rocks on terrain are modelled Y-up), +Z is forward (world +Z projected onto the tangent plane;
  when the normal is parallel to Z, use +X), then rotated about the normal by ±Randomize Yaw degrees; Randomize Up tilts the normal in a random direction by 0..value degrees.
  With Match Normals off, normal = +Y.
- Quantization quantizes all three axes (rounded to the nearest multiple); the docs only say "positions are quantized to this value".

Mutation testing: 4 of 20 survived, all killed by new tests (in By Density, the rejection random stream must be decorrelated from the triangle-picking stream -- with a ramp mask the mean of v
must be 1/2; the density attribute multiplies Density Scale; when the normal is parallel to +Z the tangent reference switches; Quantization rounds to nearest, not floor).

## Summary

- Tests: `test_audit_s4_scatter_copy.py`, all 303 green; also run in the git-less device layout (`comfyui_pcg/tests/`),
  303/303. GOLDEN has 45 old-call digests in total (7 nodes; both outputs of Extract Transform / Cluster Points covered).
- Regression: test_houdini_fixes, test_frommap, test_behavior_fixes, test_geoattrs, test_sop_attribgroup,
  test_sop_deform82, test_sop_xform, test_sop_shapes, test_deform, test_sop_repair, test_audit_s2_poly,
  test_params (.py / .mjs), test_paramui.mjs, test_nodes, test_panel, test_panel.mjs all green; check_layout is empty for all 375 panel specs.
  No new nodes were added, so test_sop_map / test_icons were not run.
- Existing tests changed: the hard-coded Scatter tab list in `test_panel.mjs` (gained Attributes).
- Shared-code changes: `deformers._rotate_dirs` gained an optional parameter names (default = the original N / up / v);
  `_sample_prim_counts` split out of `scatter._sample_per_prim` (behaviour unchanged, verified by bit-for-bit regression).

## Behaviour differences from Houdini found while reading the code (not changed, left for the coordinator to decide)

- PCG_Scatter: vertex attribute interpolation is not controlled by the Interpolate Source Attributes toggle (the toggle only covers point attributes);
  with use_out_attribs off, vertex attributes are still interpolated onto the points. Old behaviour kept.
- PCG_TransformPieces: without rest, the piece centre is moved to the origin before transforming, which is not Houdini's behaviour; a center_pieces
  toggle now lets you turn it off, but the default is still the old behaviour. Whether to switch the default to Houdini's needs the coordinator's decision (it would change the results of existing workflows).
- PCG_ScatterAlign: the coverage mode in our `mode` (Point Count Method) is a separate parameter in Houdini; Up Vector is equivalent to
  Target Forward = Custom; Normal Direction defaults to Z (Houdini: Y).
- PCG_ExtractTransform: in whole mode the instance point is placed at the translation t with pivot at the origin; in per-piece mode at the piece centre (the Houdini page doesn't say).
- PCG_ScatterFromMap: the relax_iterations argument of `geo/frommap.scatter_from_map` has no widget and isn't used in the function (the comment
  says explicitly it doesn't relax); it's a dead parameter.
