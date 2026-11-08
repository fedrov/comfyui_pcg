# s2_poly audit notes (pcg100)

Handover note: when the previous agent was interrupted it had only done PolySpline (curves2.py / nodes_sop2.py / panel_specs_g12.py uncommitted,
plus a test_audit_s2_poly.py with only a PolySpline section, 2 of its 47 checks red, no mutation testing, no notes).
I read it and checked it against freshly fetched docs, **kept its implementation**, and fixed:

- A real bug in `_march` (equal-chord stepping): when the start of a new segment lies exactly on the sphere, the larger root computed in floating point came out ≤ 0 and was
  rejected by `u0 < u`, so the next segment's "start outside the sphere" branch connected it to the **next** vertex -- that step's chord was a whole short segment too long.
  Its own test (unit circle in 6 segments) was red because of this. Changed so that a larger root ≤ 0 on the new segment also counts as exiting at this vertex.
- The expected value of its Cardinal Tension 0.5 test was wrong (written as (2, 0.5), by hand it's (2, 0.46875)); the test was fixed.
- Removed two pieces of unreachable code (found by mutation testing, see the last section).
The other 6 nodes are my work.

Tests: `test_audit_s2_poly.py`, 230 checks (each section can run on its own: shared helpers are at the top of the file).
"Bit-for-bit identical to before the change at default values" takes the baseline implementation with `git archive a9e114d comfyui_pcg/geo`, imports it under a different package name,
and compares it bit-for-bit with the current nodes on the same inputs (sha1 of topology + all attributes + groups + edge groups).

Doc fetching: the PolyBevel URLs given in the task, `polybevel--3.0.html` and `polybevel-3.0.html`, are both 404;
`polybevel.html` is the 3.0 page, and the work follows it.

## PolySpline → PCG_PolySpline (done)

Done (new widgets all at the end, default = old behaviour):
- `bezier / degree2_bezier / cardinal / linear` appended to the end of Spline Type. The existing catmull_rom / bspline /
  interpolate are kept (they are this plugin's extensions; BSpline's label changed to Houdini's "BSpline").
- `close` (Off / On / If polygon does, default If polygon does = old behaviour).
- `division_method` (Standard / Even Length / Even X / Even Y / Even Z) + `segment_length` + `output_divisions`.
- `first_cv_count / last_cv_count`, `tension` (CV Tension, only read by Cardinal).

Still different from Houdini / not done:
- **Special Bezier and Special Smooth Bezier not done**: the docs have only the names, no definition.
- Houdini's Spline Type has no Catmull-Rom Alpha; our Alpha is an extension.

Not made clear by the docs, decided here:
- Bezier: the polygon's points are the control points, one segment per 3 (2) with shared endpoints between segments; a trailing incomplete segment is computed at a lower degree
  (so the curve still reaches the last point). When closed it wraps back to the first control point.
- Cardinal: Hermite with tangent (1 − tension)(p₊ − p₋)/2; tension 0 = uniform Catmull-Rom, 1 = zero tangents.
  The default 0.5 is my choice (the docs give no default).
- Even Length means equal **chord** lengths (straight-line distance between adjacent output points), not arc length along the curve; Even X/Y/Z = distance along that axis only.
  A non-zero Segment Length is used directly, with a tail shorter than a step left as a short final segment; otherwise Output Divisions is used (bisection finds the step that gives exactly n steps);
  with both 0 there is no resampling (the docs say each derives the other; both 0 is undefined). When the curve has no extent on that axis (Even X with
  constant x) only the start and end points are output.
- When the step count jumps with the step size and no step gives exactly n divisions (zigzag lines), the missing points are added at the end point (producing coincident points).
- More than 2 million points is treated as a mistyped Segment Length and raises an error (the limit is the module constant `_MARCH_LIMIT`).
- Integer / string point attributes and point groups take the nearest source point; vertex attributes take the nearest source corner (same as the three existing bases).

## PolyCut → PCG_PolyCut (done, [C] class: the existing three modes untouched, two modes added)

Houdini's PolyCut has different semantics from our existing three modes (cut_points / keep_points / threshold), which are left unchanged.
Houdini's **Remove / Cut** were appended to the end of `mode` (panel label Strategy); these two modes run the new function `_poly_cut_hou`:
- New widgets: `cut_type` (Points / Edges), `cut_edges` (edge group), `detect` (Crossing / Change),
  `cut_threshold`, `keep_closed` (Keep Polygons Closed).
- These two modes reuse existing parameters: `points` = Cut Points, `attribute` = Cut Attribute, `threshold` = Cut Value; `keep` isn't read.
- The panel hides according to the code: Type / Cut Edges / Detect / Cut Threshold / Keep Closed only appear in these two modes; Cut Points only appears with
  Points; Cut Value is hidden with Change.

Not made clear by the docs, decided here:
- Crossing with only one end exactly equal to Cut Value: doesn't count as crossing (product = 0). Crossing on a vector attribute uses component 0.
- Edges + Cut without a Cut Attribute (every edge qualifies, but there is no "position in between"), or both ends equal to Cut Value:
  handled as the docs say for the latter, "removed but not cut".
- Edges + Cut + Change: the edge is divided into ⌈difference/threshold⌉ segments, **broken at every inserted point** (the docs only say "split into shorter edges").
  Cut Threshold = 0 raises an error; needing more than 100k segments raises an error.
- At a break the two pieces share that point (consistent with the existing cut_points). With Points + Remove a deleted point is only really removed when no other prim uses it;
  pieces with only one point aren't output. With Keep Polygons Closed, pieces with fewer than 3 points aren't closed; a closed primitive broken at only one place is joined back into its original ring.
- Cut Threshold defaults to 0.1, Keep Polygons Closed to off: the docs give no defaults.

## PolySplit → PCG_PolySplit (partial)

Done:
- `path_type` (Shortest Path / Edge Loop). **Shortest Path only matches by name: we don't search for a path**; adjacent positions
  must still be on the same primitive (existing behaviour). Edge Loop: each position on an edge inserts a ring of edges along the quad loop (stopping at non-quads /
  boundaries / non-manifold edges; returning to the start makes a closed loop).
- `num_loops` (only read by Edge Loop; > 1 inserts at equal spacing k/(n+1) along the edge), `use_edge_percentage` + `edge_percentage`.
- Position syntax additionally accepts Houdini's `pa-b`, `pa-b:t`, `avb`, `aeb`, `aeb:t` (the existing `12 / p12 / 3-7@0.25` still works).

Not done:
- **`af:u,v` (positions inside a face) / Allow split points on faces**: raises an error explaining so.
- Real path finding for Shortest Path, Match Profile / Switch Profile, Quad autocompletion, Update Point Normals,
  Append to group / Exclude Extra Edges, Tolerance, the Projection Curve input.

Not made clear by the docs, decided here:
- `aeb` edge numbering: from vertex b to the next vertex, with t measured from vertex b's end.
- Edge Loop: positions are processed in order, each on the result of the previous; positions falling on a loop already traversed are skipped (reported as skipped).
  With one loop the position's own t (or Edge Percentage) is used; with several loops they are equally spaced and Edge Percentage is ignored. The direction of t is carried consistently around the loop
  (so all new points are "on the same side"). A self-intersecting loop (passing through the same quad twice) raises an error; not implemented.
- Open curves in the loop aren't treated as faces, but curves lying on loop edges also get points inserted (no T-junctions left).

## Primitive → PCG_Primitive (partial)

Done (Transform page): `xform_order`, `rotate_order`, `shear_xy/xz/yz`, `pivot_x/y/z`. The matrix is the same as the Transform
node's (`ops.xform_matrix`), applied in local coordinates "with the prim center as origin"; Pivot is an offset relative to the center.
Default values take the original path (bit-for-bit unchanged). On the new path the Scale Attribute factor is handled like uniform scale (depending on Transform
Order, the translation is scaled by it too).
Attributes page: `color_mode` (Keep / Add / Remove) + `color_r/g/b`, `alpha_mode` + `alpha`, writing the prim attributes
`Cd` / `Alpha` (with Add, when the attribute didn't exist, unselected prims get 1; Remove deletes the whole prim attribute).
Face/Hull page: `close_u` (No Change / Open / Close, polygons only), `vertex_op` (No Change / Reverse /
Reverse U / Reverse V / Swap UV / Shift) + `u_offset / v_offset`, the same implementation as the Reverse node, applied after the transform.

Not done: Rotate to Template / Match Normals, Lookat Object, Up-Vector, Vector Attributes to Transform (we still
only rotate N / up / v), Crease, Texture, Close U's two Unroll modes, Clamp U/V, Preserve Shape, the Meta / Particles /
Volumes / VDB pages, the Do Transformation toggle, Pivot Rotate.

Not made clear by the docs, decided here:
- The doc page doesn't list the options of Transform Order / Rotate Order, nor Color / Alpha's Keep / Add / Remove;
  options and labels follow Houdini's UI (consistent with our Transform node). Close U's label is my choice too.
- Pivot is an offset relative to the prim center (the docs only say "local pivot point").

Problem found (not changed): the node docstring used to say "rotation ZYX", but it has always been Rx Ry Rz (xyz); noted at the end of the docstring.

## PolyReduce → PCG_PolyReduce (partial)

Done:
- `point_percentage` (Percentage of Point Count) and `point_count` (Output Point Count) appended to the end of Target;
  the existing two modes count triangles (we triangulate first), and their panel labels say Triangle. When targeting points, at least 3 points (one triangle) are kept --
  otherwise the last triangle would be collapsed and the output would be empty.
- `hard_edges` (edge group: both endpoints locked, neither moved nor removed, so the edge naturally stays).
- `soft_points` + `soft_weight`: adds weight · A · |x − p₀|² to these points' quadrics (A = ⅓ of the area of the surrounding triangles,
  the same units as the face quadrics). The formula is my choice; the docs only say "the larger the weight, the more it is kept".

Not done: Continue reducing within quality tolerance, the Limit Using Normal Deviation toggle (ours is always on),
Only use original point positions (we have Point Position = Endpoint, an approximation), Preserve Quads, Equalize Lengths,
Vertex attribute seams weight (we have Preserve UVs, which hard-locks seams), Retain Density by Attribute / View,
Make Reduction Sensitive to Attributes, the Rest / View inputs. The existing Hard Boundary Points (boolean) coexists with
Houdini's Boundaries (a weight; ours is Boundary Weight).

## Remesh → PCG_Remesh (partial)

Done (new widgets at the end, default = old behaviour, bit-for-bit identical):
- `group`: local remeshing. Unselected prims (including curves) are kept as is. With `detach` (Detach From Nongroup Geometry) off:
  original points on the interface are corners (not moved or collapsed), interface edges are hard edges, and new points from splitting are also inserted into the adjacent unselected primitives (quads become pentagons,
  exactly as the docs say); the two sides share points, vertex attributes interpolated by t. With it on, the two sides are disconnected.
- `hard_edges` (Hard Edges Group: may be split but always kept), `hard_points` (Hard Points Group).
- `uv_seams` (Ignore / Harden) + `uv_attribute`: edges where uv is discontinuous become hard edges.
- `out_hard_edges`: writes the final hard edges (including boundaries and seams) as an edge group (Houdini's output Hard Edges group).

Not done: **Edge Lengths = Adaptive** (Relative Density's "about 16 points on a sphere" can't be turned into a formula; not done rather than done wrong),
UV Seams = Resample, Boundary Deviation, Use Input Points Only, Recompute Normals, Max / Min Size,
Gradation, Mesh Size / Min / Max Size Attribute, the Mesh Size / Mesh Quality outputs.
Our Hard Edge Angle, Keep Boundary and Transfer Attributes are extensions, kept.

Not made clear by the docs, decided here: original points on the interface are identified in the remesh by coordinates (corners never move); two different original points with exactly the same
coordinates might be confused (not handled). Unmatched interface edges are counted in the report (`unmatched_interface_edges`, always 0 in the tests).

## PolyBevel → PCG_PolyBevel (partial)

Done (new widgets at the end, default = old behaviour):
- `none` appended to the end of Shape (only insets the primitives, no bevel faces; gaps are left at edges and vertices).
- `ignore_flat` + `max_normal_angle` (edges whose two side normals differ by less than it aren't beveled; the default 2° is my choice, the docs give none).
- `distance_scaling` (No Scaling / Scale by Attribute) + `scale_attribute` (default pscale): each point's distance =
  Distance × attribute; when the two ends of an edge have different distances the inset line is no longer parallel to the original edge; Limit Distance still clips.
- `convexity` (−1..1, Round only): 1 = the original circular arc, 0 = chord (= Chamfer with the same number of segments), −1 = an inward arc.
  Intermediate values interpolate linearly between chord and arc (the docs only define the three points). When not 1, no spherical patch is laid at vertices; an n-gon cap is used instead.
- `offset_group`: the edges between the bevel faces and the inset primitives are written as an edge group.

Not done: Slide on Ring Edges / Asymmetry Tolerance / Always Slide On, Detect Collisions / Restrict Sliding /
Stop Offsetting Loops (we only have the simplified Limit Distance), Profile (Ramp / Curve) and its Scale /
Reverse / Symmetrize / Direction Overrides.
Group Type's "prims" option isn't in the docs (the docs only mention edges or points); it's an extension, kept.

## Behaviour differences between the code and Houdini (found while reading the code, not changed)

- PolyBevel: the output only has P; all other point / prim / vertex attributes of the input are lost (the end of `polybevel` creates a new Geometry and writes only P).
- PolyBevel: when beveling a single edge, the edge's two endpoints stay on the end faces, and the end face gets an extra coplanar triangle cap (in Houdini the end face
  just loses a corner). The geometry is closed and the volume is right, but the topology differs.
- PolyBevel: the node docstring says "there are no edge groups in this data model", long out of date (Group Type = edges works).
- Remesh: when collapsing edges along feature lines (both ends are degree-2 feature points), points on the feature line get collapsed, so curved features (the rim of a cylinder)
  become chorded; the file header's "feature polylines are preserved exactly point by point" isn't entirely true.
- Primitive: the docstring says ZYX, but it is actually Rx Ry Rz (noted in the docstring).

## Mutation testing

The script makes single-point mutations in a copy of the worktree (comparison operators, +−×÷, constants, and/or, True/False, deleted lines...), running only the test section
for the corresponding node (`PYTHONDONTWRITEBYTECODE=1 python3 -B`; the worktree itself was never modified).
First-round results: curves2 238/293, meshedit 210/259, cutsplit 207/255, deform2 66/77, polyreduce 39/46,
remesh 172/225, ops 99/114 killed. About 45 tests were added for the survivors, and two pieces of unreachable code were removed
(the guard `mid <= tot·1e-9` in the bisection: halving tot 80 times never reaches 0; the `"P" not in names` branch in `pcol`),
plus the line `keep[n0:] = True` (points + remove inserts no points, so it's always an empty slice). Second-round results and the remaining mutants are below.

Second round (after adding the tests, same mutation operators; a few more tests added for the survivors and re-checked): 1265 mutants in total, 1175 killed.
The remaining 90 were inspected one by one and classified as follows (line numbers as of the commit):

- **Equivalent (changing them affects no output)**:
  - Constants in function signatures that are only "another copy of a default" (Convexity 1.0 → 2.0 is clamped back to 1); `owned=True/False`;
    the −1 in `reshape(-1, 2)` changed to −2 (numpy still treats it as an unknown dimension); `set_edge_group` re-sorts and deduplicates edge groups when they are stored.
  - The point-pair encoding `a·(n+1)+b` changed to `n−1` / `n+2`: point pairs are sorted (a < b ≤ n−1), proven never to collide.
  - Several comparison operators in `curves2._march` that only differ when u is exactly 1 / the discriminant is exactly 0 / the quadratic's a is exactly 1e-300;
    the initial value of `fresh`, the reset of `u0` on changing segment (after a segment change `fresh = True`, so u0 isn't read); in the resampling bisection, the "steps > n" upper limit
    `limit = n + 1`, the fake return value when it is exceeded, `> n` changed to `≥ n` (they only decide which side to converge from, converging to the same step);
    `n_first > 1` changed to `≥ 1` (repeat is the identity when all are 1). `near[:1]` changed to `near[:2]` when resampling closed curves (the extra one
    is only used by the end point, which gets removed).
  - PolyCut: `va * vb < 0` changed to `va / vb < 0` (same sign test; both are False when vb = 0); `p < q` changed to `≤`
    (the two ends of an edge are never the same point); two variants of `j < len(order) − 1` for a closed primitive broken at only one place (the extra single-point piece is never output anyway).
  - PolySplit: `(i + 2) % 4` changed to `(i − 2) % 4` (equal modulo 4); `i > j` changed to `≥` (A ≠ B);
    the first tuple element in the `locs` rewrite (not read afterward).
  - Primitive: with the two Transform / Rotate Order checks before `raise` removed, `xform_matrix` raises the same error itself.
  - PolyReduce: Soft Weight `> 0` changed to `≥ 0` (a weight of 0 adds a zero matrix).
  - PolyBevel: inset direction normalization `/` changed to `*` (the later intersection solve only uses the direction, independent of length); removing the `convexity == 1.0`
    fast path (1·(arc − chord) + chord = arc, consistent in floating point too); the spherical-patch condition `D > 1` changed to `≥ 1` (at D = 1 the next line falls back to an n-gon again).
  - Remesh: the initialization `iface_pts = iface_edges = None` (only read when partial); the `he >= 0` filter on the hard-edge group
    (keys encoded from −1 never land on a valid edge).
- **Unreachable defensive branches (kept; inputs can't be constructed reliably)**:
  - `>` / `≥` of PolyCut's 100k-segment limit; in PolySplit `_cut_piece`, the guard for "the two points aren't both on this piece / adjacent",
    the self-intersecting-loop error and `seen` (a self-intersecting quad loop can't be constructed), the `break` after one cut;
  - several guards of `chain()` in Remesh `_stitch` (path not on the segment, wrapping back to a non-corner point, length limit), the `missed` count and `continue` when no interface chain is found
    (`unmatched_interface_edges` is always 0 in the tests); the open-curve "last vertex doesn't connect back" check
    `j == m − 1` changed to `j == m + 1` (the edge back isn't an interface edge, same result);
  - in PolyReduce's point-count mode, the term "the third point of a removed triangle is also orphaned" (almost never hit under the link condition; when hit it only affects when it stops);
  - the return in PolyBevel's spherical patch for a degenerate direction (angle < 1e-7).
- **Equivalent under the test data; no distinguishing input was constructed**: several variants of half-edge start/end points in Remesh `_uv_seam_edges` (in the triangulated output
  every triangle's first edge happens to have the smaller point number first, even with primitives reversed), and `> 1e-6` changed to `≥`.

Deleted code: `if mid <= tot·1e-9: break` in the bisection (halving tot 80 times never reaches 0), the `"P" not in names`
branch in `pcol` (P is always among the float attributes), `keep[n0:] = True` (points + remove inserts no points, so it's always an empty slice).
