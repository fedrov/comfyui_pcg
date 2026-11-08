# s5_deform_paths audit notes (pcg100)

Tests: `test_audit_s5_deform_paths.py` (runs in both layouts: the package path walks up to find `comfyui_pcg`, no git needed).
"Bit-for-bit identical to before the change at default values": CASES at the top of the file registers a set of node calls **using only old widgets**;
GOLDEN holds the digests (first 16 hex chars of sha1) obtained by running the same file with `--digests` on the pre-change commit 9e3fb92 (`git archive`d into the scratchpad),
hard-coded in the file. `--digests` exits before running any new feature.

The mutation-testing script is in the scratchpad (replaces [file, original string, mutant string] one at a time, runs the tests, restores,
`PYTHONDONTWRITEBYTECODE=1 python3 -B`, clearing `__pycache__` after each); after the run `git diff --stat` confirms everything is restored.

## Smooth → PCG_Smooth (main gaps done; Filter Quality not done)

Docs re-fetched from the Smooth 2.0 page. "Constrained Boundary: … Constrained Points" in the audit record is actually two parameters:
the Constrained Boundary menu has only three items, None / Unshared Edges / Group Boundary; Constrained Points is a separate point list.

Done (new widgets all at the end of INPUT_TYPES, default = old behaviour):
- `method` (Method): `uniform` (old behaviour, first item) / `scale_dominant` / `curvature_dominant`.
- `pin_group_boundary` (the Group Boundary part of Constrained Boundary): additionally pins the points on the outer rim of the selection.
  The old `pin_boundary` (Pin Border Points) is exactly Unshared Edges; both on = Houdini's Group Boundary,
  both off = None. Not turned into one menu, because the old toggle can't change and a new menu mustn't fight with it (the panel label reads
  "Pin Border Points (Unshared Edges)", and the help explains the combinations). Pin Group Boundary on with Pin Border
  Points off is an extra combination of ours (pins only the selection rim, not the mesh border).
- `constrained_points` (Constrained Points): a group specifier (group name / indices / @expression); these points don't move.
- `attributes` (Attributes, default "P"): space-separated, wildcards allowed. Supports float **point attributes** and **vertex attributes**.
  Vertex attributes (uv) are smoothed on a graph where "vertices on the same point with the same value merge into one node": the two sides of a uv seam are different nodes,
  each smoothed separately, and are not pulled together; with Pin Border Points on, nodes used by only one edge in this graph (uv island borders,
  seams) are pinned too -- otherwise uv islands shrink inwards every iteration. Int / string attributes and prim / detail attributes are not smoothed (an error if a specific name
  is given and no smoothable float point / vertex attribute is found; no error if a wildcard matches nothing).
- `use_weight_attribute` / `weight_attribute` (Use Weight Attribute / Weight Attribute, default name weight):
  per-point strength multiplier; must be a numeric point attribute.
- `recompute_normals` (Recompute Affected Normals, off by default = old behaviour; Houdini defaults to on):
  when P was smoothed, N is not in Attributes, and the input has N (point or vertex), recomputes N for the **affected** points / vertices --
  affected = points sharing a face with a moved point; other points keep their N unchanged.

Still different from Houdini / not done:
- **Filter Quality not done**: the docs only say "high = preserves detail, low = faster and smoother", no algorithm. We keep the old
  Iterations (explicit iteration count) and the per-iteration step Strength -- Houdini's Strength is not a per-iteration step, so the values aren't comparable.
- The docs give no formulas for the weights of the three Methods; implemented as the three classic umbrella-operator weights (Desbrun 1999 / Fujiwara):
  Uniform w=1, Scale-Dominant w=1/|e|, Curvature-Dominant w=cot α+cot β (cotangent, clamped to ≥0).
  The names and descriptions ("even distribution / preserve relative distances / smooth curvature while keeping the layout as much as possible") match, but whether Houdini internally uses
  these three weights, or also does anti-shrinking (Taubin λ|μ), is unknown.
- Curvature-Dominant: cotangents are computed on the triangles of a fan triangulation; weights on diagonals (edges not in the original topology) are dropped;
  negative weights from obtuse angles are clamped to 0 (otherwise it diverges); the cotangent of a zero-area triangle counts as 0; edges not on any triangle (curves) use 1/|e|.
  A point whose edge weights are all 0 doesn't move. Weights are recomputed from the current P each iteration.
- Zero-length edges get weight 0 in Scale-Dominant / on curves (coincident neighbours don't take part).
- Weight Attribute: Houdini says the value can be large and isn't a [0,1] mask; our Strength is a per-iteration step, so
  strength × weight is clamped to [0, 1] (above 1 the explicit iteration overshoots the target and diverges).
- Group is still parsed as **points** (old behaviour); Houdini's Group is a primitive group. The "selection rim" of Group Boundary is therefore defined as
  "the selected points that have at least one unselected neighbour".
- When Recompute Affected Normals recomputes, point N uses the default area weighting and vertex N uses cusp 60° (what parameters the input N was
  originally computed with is unknown).

Not made clear by the docs, decided here: the weight formulas above, the clamping, zero-length / zero-area handling, the vertex-attribute graph, pinning uv island borders.

Mutation testing: first round 31, 13 survived; handled as follows:
- Killed by new tests (9): zero-length edge weight (coincident neighbours), zero-area triangle cotangent, diagonal dropping (`==` changed to `>=`),
  negative cotangent clamped to 0 (two variants), staying put when all weights are 0, weight attribute type check (a string attribute raises our own error),
  vertex attributes reusing the point edge weights (uv = (0.4, 0.5) under Scale-Dominant, worked out by hand), recomputing N only for affected points
  (input N deliberately all set to +X). The cotangent-related ones are compared against a pure-Python per-face, per-corner reference implementation on a jittered quad mesh
  (a seed was picked that really produces 2 negative weights).
- Proven equivalent, code removed / rewritten (4 sites): removing self-loops in the vertex graph (they only occur on degenerate polygons; the point graph doesn't remove them either,
  so after removal the two agree); `~(sel & outer)` → `~outer` (unselected points aren't in the mask anyway); the "only parse when non-empty" check for Constrained Points
  (check removed; `empty_is_all=False` is now covered by tests); `aff |= moved` (a moved point is always
  on some face, already covered by `hitp`). Second round: all 11 killed.

Found in passing: nothing.

## Soft Peak → PCG_SoftPeak (main gaps done; Surface distance, Visualize Falloff not done)

Docs re-fetched. New widgets all at the end of INPUT_TYPES, default = old behaviour. The falloff part lives in `deform.soft_falloff` /
`deform.rolloff`, shared with Soft Transform.

Done:
- `attribute` (Attribute) and `radius_with_connectivity` (Radius with Connectivity,
  marked deprecated in the docs but still listed) appended to Distance Metric. Old tokens unchanged; panel labels changed to Houdini's: euclidean = **Radius**,
  distance = **Edge**; steps is ours (Edge Steps).
- `soft_type` (Soft Type): `ramp` (old behaviour: Ramp curve + interpolation, panel label "Ramp (PCG)") / `linear` /
  `quadratic` / `cubic` / `metaball`.
- `tangent_far` / `tangent_near` (Tangent Angles, two in one row, degrees; only read by Cubic).
- `kernel` (Kernel Function, only read by Metaball): `links` / `renderman` / `hart`.
- `distance_attribute` (Distance Attribute, default dist), `apply_rolloff` (Apply Rolloff, on by default):
  only read when Metric = Attribute.
- `translate_along_lead_normal` (Translate Along Lead Normal), `lead_point_attribute` (Lead Point
  Attribute, default lead, integer point number, −1 = use own normal; only read when Metric = Attribute).
- `use_mask` / `mask_attribute` (Mask: Scale by Attribute + Mask Attribute, default name mask): displacement × attribute value.

Not made clear by the docs, decided here:
- The docs **give no formulas** for the Soft Types: Linear = 1 − t; **Quadratic = 1 − t²** (the docs only say "falls off more slowly than Cubic,
  far points are affected more"; 1 − t² ≥ smoothstep over the whole range, which satisfies that -- this is an inference); Cubic = a cubic Hermite on s = 1 − t
  (endpoints 0 → 1), far / near slopes = tan(Tangent Angles[0] / [1]); with both angles 0 it's smoothstep;
  the docs don't give the zero / direction of the angles, interpreted as "inclination relative to the horizontal", widget limited to ±89°. With large tangents Cubic can go outside [0,1];
  not clamped.
- Metaball kernels: in the Metaball SOP docs only Links, RenderMan and Hart have formulas, so only these three are done; **Blinn / Wyvill /
  Elendt not done** (no formulas in the docs, not invented). t is interpreted as "normalized distance" (Links' two pieces are continuous at 1/3, which confirms this).
- Metric = Attribute: this mode has no "handle"; Group only limits which points can move (empty = all points; still required under other Metrics),
  and points in the group are **not** forced to weight 1; negative distances count as 0; with Apply Rolloff off the attribute value is used directly as the weight, not clamped.
- Radius with Connectivity: straight-line distance ≤ radius, and reachable from the handle along edges passing only through points with "straight-line distance ≤ radius".
- The Lead's "nearest handle" is computed by the selected Metric: straight-line kinds take the nearest handle point; along-edge kinds (Edge / Steps) trace back to the root in the shortest-path tree.
  On equal distance, the handle with the lower point number wins.

Still different from Houdini / not done:
- **Surface** (geodesic distance along the surface) not done: we only have Dijkstra-style along-edge distances; geodesic distance across face interiors needs
  a dedicated algorithm (heat method / MMP and the like), and passing off along-edge distance as it would be "looks right but isn't".
- Visualize Falloff (Never / Always / When Viewport Tool Is Active) not done; our Output Weight Attribute
  (`weight_attribute`) serves the same purpose.
- Recompute Affected Normals: not done separately. The old Recompute Normals (`update_normals`), when the input has N,
  recomputes **all** point normals (closer to Houdini's Recompute Point Normals).
- Normals are still used at unit length (old behaviour); the docs don't say whether Houdini normalizes N.

Mutation testing: first round 30, 9 survived; handled as follows:
- Killed by new tests (6): negative distance attribute (the clamp in rolloff), still 0 outside the radius when the Ramp isn't 0 at 0, adjacent handles can't
  be each other's parent (`~sel[v]`), zero-length edges don't form cycles (point order deliberately gives the downstream point a lower number), parent picked as "the closest fit" (two upstream neighbours,
  one exact and one detouring), Lead / Mask attribute type checks.
- Proven equivalent, removed (2 sites): the `clip` at the Attribute-mode call site (clamped uniformly in rolloff); "unreachable → inf" under steps in `nearest_handle`
  (unreachable points have weight 0, so whatever their lead is doesn't affect the result; comment added). Second round: all 7 killed.

In passing: Soft Transform's Distance Metric menu shares `deform.METRICS` with Soft Peak, so it gained the same two items
(panel menu completed too); Soft Transform's other gaps are in the next section.

## Soft Transform → PCG_SoftTransform (main gaps done; Local Space / Attributes list / Surface not done)

Docs re-fetched. The docs page **doesn't list** the Transform Order / Rotate Order options; the Transform SOP's standard menus are used
(shared with our PCG_Transform via `ops.XFORM_ORDERS` / `ops.ROTATE_ORDERS`).

Done (new widgets all at the end, default = old behaviour):
- `xform_order` (Transform Order, default srt), `rotate_order` (Rotate Order, default xyz = Rx Ry Rz).
- `shear_xy` / `shear_xz` / `shear_yz` (Shear, one row), `prx` / `pry` / `prz` (Pivot Rotate, one row).
  The matrix follows the same convention as the Transform node (`ops.xform_matrix`); the test compares all 36 order combinations (with shear, pivot, Pivot Rotate)
  point by point against the Transform node at weight 1.
- Soft Type / Tangent Angles / Kernel Function / Distance Attribute / Apply Rolloff shared with Soft Peak,
  plus Distance Metric's Attribute / Radius with Connectivity (see the previous section). With Metric = Attribute, an empty group =
  all points, falling off by attribute (no longer "a plain transform with weight 1 for everyone"); consistent with the docs' wording "only points in the input group are transformed".
- `recompute_point` (Recompute Point Normals: if there is N, recompute everything as point normals and delete the original
  vertex N) and `recompute_affected` (Recompute Affected Normals: recompute only the affected point / vertex N,
  sharing `topology.recompute_affected_normals` with Smooth) appended to the Normals menu.
- `preserve_normal_length` (Preserve Normal Length, off by default = old behaviour, normalized): in the jacobian mode, transforming N
  keeps its original length (`_fix_directions` gained a keep_length parameter; other nodes' calls are unaffected).

Not made clear by the docs, decided here:
- How the soft weight applies to shear: × w like displacement / angles (the old node's "interpolate the parameters, not the result" convention);
  **Pivot Rotate is not interpolated by weight** (it defines the pivot coordinate frame).
- When only Pivot Rotate is non-zero and everything else is identity, return directly (the identity transform is still identity in the rotated frame).
- With the default SRT / xyz / no shear / no Pivot Rotate, the old code path is taken (bit-for-bit unchanged); otherwise the generic per-point 4×4 path.

Still different from Houdini / not done:
- **Local Space + Up Vector not done**: the docs say "operates in the frame defined by the selected points' average normal, local Y aligned to Up as far as possible",
  but don't say which local axis the average normal corresponds to (Z?), nor whether the average is weighted -- not invented.
- **Attributes list** (transforming Position / Vector / Normal / Quaternion / Matrix by the attribute's type info) not done:
  we have no type info; still the old behaviour, where the jacobian mode only transforms N / up / tangentu / tangentv.
- Surface distance and Visualize Falloff, as for Soft Peak, not done.
- Pivot Translate is the old pivot_x/y/z (plus the Pivot at Group Centroid toggle, our extension).
- Houdini's Recompute Point Normals and Recompute Affected Normals are two toggles that coexist with the attribute list for "transform N";
  ours is one Normals menu, pick one of four.

Mutation testing: 25, 4 survived; handled as follows:
- Killed by new tests (3): scale lerp(1, s, w) and displacement × w in the generic matrix path (with soft weights, Rotate Order switched to zyx but no rotation,
  compared with the old path + hand-computed coordinates), Distance Attribute rename passed through.
- Proven equivalent, removed (1 site): the "return if there is no N" at the start of `recompute_affected_normals` (the two branches after it each check has;
  it only saved one shallow copy). Second round: all 3 killed.

## Twist → PCG_Deform (partial: only Pivot done)

Docs re-fetched: the Twist SOP **is marked deprecated** (the docs recommend the Bend SOP instead), the page has **no formulas at all**,
and the Primary / Secondary Axis options aren't listed. "Twist Source: Centroid of the input / X extents …" in the audit record
is actually the page's **Locals** (CEX/CEY/CEZ, XMIN/XMAX… expression variables) and the "description of the Twist Source input", not a menu;
what the audit calls "Origin" is called **Pivot** on the page.

Done:
- `pivot_x/y/z` (Pivot, one row, default origin = old behaviour): the deformation axis passes through the pivot. Implemented as translate into pivot coordinates, deform, translate back;
  the capture range (automatic extent or absolute coordinates given by Range) is converted accordingly, so the pivot's component along the primary axis has no effect.
  With pivot 0 the original code is used (bit-for-bit unchanged).

Skipped / still different from Houdini (all because the docs give no formulas; not invented):
- **Taper vs Linear Taper**: the docs' two descriptions are nearly identical ("scale along the length" / "scale linearly along the length") and don't say what differs.
  Our `taper` is linear and already labelled Linear Taper on the panel; a non-linear Taper is not done.
- **Strength / Rolloff**: the docs only say Rolloff is "usually exponential" and that for Bend it varies along the secondary axis from Rolloff−0.5 to Rolloff+0.5,
  which isn't enough to reproduce it; ours is still the direct parameterization by the two quantities Angle / Scale / Shear.
- **Secondary Axis menu**: our Up vector (any direction) covers it; no menu added.
- Locals (CEX, XMIN…) are expression variables, not parameters; not done.

Mutation testing: all 6 killed (axial component conversion, translating back, range shift, toggle, parameter order).

## Edge Transport → PCG_EdgeTransport (main gaps done; Rotate by Edge Angle, vertex attributes not done)

Docs re-fetched. The old four Operations (distance / copy / sum / average) have **different semantics** from Houdini's five
(the old sum includes itself; Houdini's Total doesn't and the root is 0; Houdini's Transport "takes the parent's original value" rather than copying the root all the way down),
so the **old four are not changed**; Houdini-semantics versions of the five are appended to Operation, and the old four are labelled "(PCG)" on the panel.

Done (new widgets all at the end, default = old behaviour):
- Operation gains `transport` / `transport_from_root` / `total` / `maximum` / `minimum` (following the docs item by item:
  Transport takes the parent's **original** value, the root takes New Root Value; Transport from Root takes the root's value; Total = sum of ancestors excluding itself,
  root 0; Maximum / Minimum = extreme over itself and its ancestors, root kept). The docs' "point number → parent" recipe (Transport + Hold)
  is reproduced in the tests; integer attribute output stays integer.
- Method gains `parent_attribute` (Parent Attribute) + `parent_attribute` (attribute name, default parent): illegal point numbers and
  self-references → root; points unreachable because of cycles are not processed (go into the unreached group). Panel labels: network = Edge Network,
  curves = Each Curve.
- `root_choice` (Root Choice, Edge Network only): `group` (old behaviour) / `first_point` / `last_point`.
- `point_group` (Point Group, network / parent_attribute), `curve_group` (Curve Group, curves).
- `direction` (Forward / Backward), `new_root_value` (Zero / Hold), `integrate_constant`,
  `scale_by_edge_length`, `split_method` (Copy / Split), `merge_method` (Add / Maximum / Minimum).
- `use_normalization` / `normalization` (Per-Component / Global), one "☑ Normalization [menu]" row.

Not made clear by the docs, decided here:
- direction / new_root_value / integrate / scale / split / merge **only apply to the new five**; the old four keep the old behaviour.
  Normalization applies to all nine (post-processing).
- Backward: points without children (tips) are the starting points, and New Root Value applies to tips; Total backward = sum of descendants (excluding itself),
  Transport backward = takes the child's original value; multiple children are combined by Merge. Maximum / Minimum ignore Split / Merge
  (they are extremes by nature).
- Split: the amount passed to children ÷ number of children (Transport passes the parent's original value, Transport from Root the parent's current value, Total passes
  "parent's current value + parent's value × edge length"). Transport from Root + Split is therefore an even split at each level.
- Integrate a Constant Value only applies to Total; if the attribute doesn't exist it is created (float32); if it exists its value is ignored and its component count kept.
- The "pieces" for Per-Component: network / curves use geometric connected pieces; parent_attribute has no edges, so it goes by tree (root).
  A constant piece normalizes to 0.
- Output type: float attributes keep their original precision; integer attributes stay integer only when the result is necessarily integer (Transport / Max / Min, no Split, not normalized),
  otherwise float32.
- First / Last Point: after a pass, the lowest / highest point number among points not yet reached (and in Point Group) becomes the new root.
  Points outside Point Group are not walked and never become roots.
- Edge Network still builds the tree by shortest paths over **edge length** (old behaviour). The docs say "edges at the same level are sorted by edge distance", which sounds like a BFS
  layered by hop count; not changed, noted here.

Still different from Houdini / not done:
- **Rotate by Edge Angle** not done (vectors / the orient attribute would need rotating by the turn angle between adjacent edges; the docs don't define the turn angle).
- Each Curve only handles point attributes (Houdini also supports vertex attributes); closed curves are still walked as open polylines (no closing edge).
  The docs say Each Curve "walks from the lowest point number to the highest"; we walk in vertex order (from the end in the group when Root Group is given).
- The old Output Attribute / Unreached Group / transport_root outputs are our extensions, kept.

Fixed an old bug in passing: Edge Network's processing order was sorted only by distance, so on **zero-length edges** (coincident points) a child could come before its parent
and accumulation lost values (chain 0–2–1–3 with 1/2 coincident: the old sum gave [1,2,4,6], should be [1,6,4,10]). Now sorted by "distance, then level";
the order is unchanged in all other cases (GOLDEN all pass).

Mutation testing: first round 34, 13 survived; handled as follows:
- Killed by new tests (8): a point whose parent isn't in Point Group becomes a root, a constant piece normalizes to 0, normalization subtracts the minimum, Total + Hold root still 0
  (one each for forward / backward), Total backward multiplies by edge length, Integrate only for Total, Parent Attribute's Per-Component
  splits pieces by tree. Plus a test for float precision being kept.
- Proven equivalent, removed / rewritten (5 sites): "sort by pass" for First / Last Point (sorting by distance already guarantees parents come first -- later changed to
  distance + level), `par[~allowed] = -1` (points outside the group are already excluded when building the child table and finding roots), "Integrate + Total doesn't keep integer" in the
  integer-keeping condition (Total isn't among the integer-keeping modes anyway), "iuf" in keep (changed to: floats always keep their precision).
  Second and third rounds: all 12 killed.

## Find Shortest Path → PCG_FindShortestPath (three Output Paths modes + cost / surface constraints done; the output-attribute group not done)

Docs re-fetched. The page is divided into Parameters / Output / Path Costs / Surface Constraints / Locals.

Done (new widgets all at the end, default = old behaviour):
- Output Paths (our `mode`) gains `any_to_any` (From Any Start to Any End, only one path),
  `any_start_to_each_end` (one path per end, from the cheapest start, a single multi-source Dijkstra), `corresponding`
  (starts / ends paired one-to-one in the order written; error if the counts differ). The old `nearest_end` is From Each Start to Any End,
  `each_pair` is From Each Start to Each End, and their panel labels changed to Houdini's; `sequence` is ours, labelled (PCG).
- `use_max_cost` / `max_cost` (Max Search Path Cost): paths with cost > it count as unreachable (equal to it is not over).
- `point_cost_attribute` (Point Cost Attribute, **additive**: added when entering the point), `prim_cost_attribute`
  (Primitive Cost Attribute: added on the edge; when several prims share an edge the one with the lowest number is used), `omit_distance`
  (Omit Distance from Cost).
- `surface_prims` (Surface Primitives), `directed_prims` (Directed Primitives: edges that appear only in directed prims
  can only be walked in the prim's direction; if the same edge is also in a non-directed prim, both directions are allowed), `edges_to_avoid` (Edges to Avoid, edge group name,
  error if it doesn't exist). When directed, "From Each Start to Any End" expands backwards from the ends on the reversed graph.

Not made clear by the docs, decided here:
- The start point's own Point Cost isn't counted (the docs don't say whether "passing through the point" includes the start); the end point's is.
- The old cost model is **multiplicative** (edge length or step count × (1 + Cost Weight·cost) × (1 + Slope Weight·slope)); Houdini's is additive.
  Both coexist: the old multiplicative part serves as the "edge length" term, and Houdini's Point / Primitive Cost is added on top; Omit Distance sets
  the whole multiplicative part to 0. On the panel the old cost_attribute is relabelled "Cost Attribute (PCG, Multiplier)" (the parameter itself unchanged).
- Costs may be 0 (with Omit Distance); negative ones raise an error.
- any_to_any on equal cost takes the end written first.

Still different from Houdini / not done:
- **The output group not done**: Keep Original Geometry (Houdini's paths **share points** with the surface; our merge copies points),
  Cost Attribute (per-point accumulated cost, a tuple with multiple starts), Previous Point Number, **renaming** of the Point Number / Start Point /
  End Point / Path Cost attributes (we always write srcpt / startpt / endpt / cost / length), Paths Group
  (we only write edge / point groups when output = group). These are output attribute names / toggles, deprioritized per the brief.
- Consider Turning Costs / Angular Cost Attribute, Custom Edge Cost / Override Heuristic (expressions),
  Enable Primitive Variables, Adjacency Array Attribute, and the second input (start / end taken as nearest surface points) are not done.
- Start / End only accept point groups / point numbers (we have no second input).

Mutation testing: 20, 5 survived; handled as follows:
- Killed by new tests (4): Primitive Cost takes the lowest number only within Surface Primitives, any_start_to_each_end uses the forward graph
  (when directed), any_to_any takes the cheapest rather than the first, Omit Distance on its own also takes the new cost path.
- Proven equivalent, rewritten (1 site): with multiple sources, "which start it came from" via dijkstra's root is equivalent to the path's first point; changed to the latter.
  Second round: all 4 killed.

## Group Find Path → PCG_GroupFindPath (partial: Start/End Pairs, Avoid Self Intersection, Collision Group)

Docs re-fetched. The page doesn't list the Group Type options and **doesn't define** loop / ring (what they mean for edges, points, faces);
the algorithm is only described as "minimizing the number of turns and the distance".

Done (new widgets all at the end, default = old behaviour; all points only):
- Path Type (our `mode`) gains `start_end_pairs` (Paths between Start/End Pairs in Base Group):
  Base Group paired two by two, one path per pair; error on an odd number of points. The old `shortest_path` = Paths through Each Base Group Element
  in Order; `boundary_loop` is ours (labelled PCG).
- `avoid_self_intersection` (Avoid Self Intersection): later segments avoid points used by earlier segments (except this segment's own endpoints),
  with priority in Base Group order. Combined with `close` it is Houdini's Close Path ("find a return path that doesn't cross the way out") --
  in that case two points can also form a loop (the old behaviour doesn't close with two points, and that is kept without Avoid). With Pairs + Close each pair forms its own loop.
- `collision_group` (Collision Group, point group) + `contain_within_collision` (Contain within Collision Group).
  Endpoints in the Collision Group are still used as endpoints (the docs don't say; allowed here).
- Panel labels changed to Houdini's: Points → Base Group, Mode → Path Type, Output Group → Group Name.

Still different from Houdini / not done:
- **Group Type is points only**: paths when Base Group is edges / faces (face loops, edge loops) not done.
- **Loops or Rings Starting from Elements**, **Edge Path Style** (rings / loops), Path Ending's
  **Extend to Edge** ("extend as far as possible without sharp turns"): the docs don't define loop / ring or give a "sharp turn" threshold; not done.
- Our Close Path is still a toggle (`close`), not a Path Ending menu; closing without Avoid is the old behaviour (the return path may overlap the way out).
- Path cost is still edge length (or step count) × the cost attribute multiplier; Houdini's is "number of turns and distance".
- UV Attribute (restricting to uv-connected regions), Collision Group Type (faces / edges), Allow Paths along Collision Group
  Boundary not done.
- Unreachable segments are skipped, with an unreachable count in the report; Houdini gives a warning.

Mutation testing: 12, 2 survived: added the tests "with Pairs and no Avoid, the second pair may overlap the first" (negative control) and "no points written when a whole row is blocked",
second round all killed.
