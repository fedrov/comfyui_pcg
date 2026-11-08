# s1_group_delete audit notes (pcg100)

The docs for all seven nodes were re-fetched with WebFetch (grouppromote / delete / blastbyattribute / dissolve /
normal / clip / mirror). **None** of these SideFX pages give default values, so every "default" below was chosen by us to keep old graphs unchanged.

The previous agent left the work half done: Group Promote's geo implementation, Delete's geo + node, the new Blast by Attribute
node (without a panel spec), Dissolve's geo (node not wired up), compute_normals' name parameter (node not wired up),
no tests, and no mutation testing. I read, tested and kept all of this code; changes are listed in each section under "changed from the previous agent".

Tests: `test_audit_s1_group_delete.py`, 208 checks. "Bit-for-bit identical to before the change at default values" runs the same set of calls using only old parameters on the baseline a9e114d
(24 calls, covering six of the seven nodes that are old), with digests of the output geometry hard-coded in GOLDEN;
`--digests` reprints them.
Also changed two old tests that pinned numbers: the spec total in test_panel.py 367 → 368 (new node), and the tail of PCG_Normal's "new widgets at the end"
list in test_options98.py (six more).

---

## Group Promote → PCG_GroupPromote

**Done**
- 11 items appended to the Conversion dropdown: point/prim/edge/vertex converted pairwise, plus `prim_to_prim` (only meaningful with Boundary:
  a primitive group → the ring of primitives along its outline). Houdini has two dropdowns, From / To; here it is still **one** dropdown:
  old graphs store the value by token, so splitting it would break them. The panel label reads "Convert From / To".
- New toggles (all at the end): Keep Original Group, Include Only Elements Entirely Contained, Include Only
  Primitives Sharing an Edge, Include Only Elements on the Boundary, Include Unshared Edges,
  Include All Unshared Curve Edges, Output as Integer Attribute.

**Different from Houdini**
- Keep Original and Entirely Contained **default to on** (in Houdini they are presumably off): this node never deleted the original group before,
  and point → prim always required all points to be in. Changing the defaults would change old graphs.
- Boundary is only supported starting from primitive groups; the docs don't define the "boundary" of point / edge / vertex groups, so turning it on raises an error.
- Output as Integer Attribute raises an error when the target is edges (there are no edge attributes).

**Not made clear by the docs, decided here**: the exact rules for each direction are in the table at the top of geo/grouppromote.py; those marked * are our choice
(edge → vertex = the corners touching the selected edges; vertex → edge = two adjacent corners in the same primitive both selected; vertex → prim is unaffected by
Entirely Contained). Per the docs, Entirely Contained also applies to To = Edges: I changed the previous agent's hard-coded
"point → edge requires both endpoints" to be controlled by this toggle (default on = the previous result).

**Not done**: Number of Promotions (multiple rules; just chain a few nodes), Connectivity Attribute + Tolerance,
Include All Primitives Sharing Attribute Boundary Points, Remove Degenerate Bridges (the docs have only one sentence).

## Delete → PCG_Delete

**Done**: Edges appended to Entity (per the docs: deletes the **endpoints** of the selected edges); Delete by Pattern + a Pattern field appended to the Number page's Operation;
Select _ of _ added to Delete by Range; the Degenerate page (Delete Degenerate Primitives /
Delete Zero-Area Faces / Treat Open Faces as Closed / Tolerance); the Random page (Global Seed /
Use Seed Attribute / Seed Attribute / Percent); Delete Unused Groups.

**Changed from the previous agent**: the Zero-Area criterion changed from "area < tol" to "area < tol²" -- the docs state area has squared units
and Tolerance is the side length of the smallest square. The redundant `| ~seg` in the degenerate criterion was removed (proof in the code comment).

**Different from Houdini / decided here**
- Edges only recognize Group (edge groups); how the Number / Bounding / Normal / Expression / Degenerate / Random pages apply to edges
  isn't implemented, and using them raises an error (the docs only say "Edges are ranged by primitive number").
- Pattern only recognizes plain index syntax (`0 5`, `a-b`, `a-b:step`, `!`/`^`, `*`); Houdini's `a-b:n,m` isn't done and
  raises an error. The default `!*` (select nothing) is from memory; the docs don't give it.
- Degenerate only "selects" degenerate primitives; unlike Houdini it doesn't first remove duplicate point references.
- The random numbers in Random are not Houdini's: the proportion is right, but the selected elements won't be the same ones. The docs say "less than or equal to Percent";
  here `<` is used so that 0% deletes nothing.
- The Expression page was already unique to this plugin (Houdini puts it in the Number page's Operation); left as is.

**Not done**: Geometry Type (the docs don't list the options), the Normal page's Backface From (needs a camera).

## Blast by Attribute → new node PCG_BlastByAttribute (nodes_sop2.py)

The sop_map row changed from `done / PCG_Blast` (meaning "write an @attr expression in the group") to `new / PCG_BlastByAttribute`.
Icon `blast_attr`. PCG_Blast itself is untouched.

Parameters per the docs: Group / Run Over / Attribute Name / Output (Blast | Group) / Mode (Threshold | Range | Width) /
Invert / Threshold / Min / Max / Center / Width / Output Group / Remove Unused Points.
**Decided here**: Threshold is strictly less-than (the docs say "lower than"); Range includes both ends (the docs only say "within",
and the Width entry describes a closed interval, so that is followed); Invert doesn't touch elements outside Group; vector attributes raise an error directly (the docs don't say which component to use);
the defaults of the numeric values are our choice. Remove Unused Points only takes effect when deleting primitives.
The previous agent's docstring said "the docs state inclusive"; the docs say no such thing, fixed.

## Dissolve → PCG_Dissolve

**Done**: Operation (Dissolve Selected / Non-Selected), the Bridge dropdown (`leave` / Create Bridged
Polygons / Delete Polygons), Recompute Normals. Default `leave` = what this node did before (pieces with holes are left as is);
Houdini doesn't have this option.

**Changed the previous agent's Create Bridged Polygons implementation** (places where the original went wrong):
- With inconsistent primitive winding the original merged into a primitive with the wrong area (flip one primitive in a 3×3 ring, 8 becomes 6). Now this is detected and handled as leave.
- Removing "spikes" originally removed them regardless of whether the edge was selected, dissolving **unselected** edges in the piece; now only selected edges are removed.
- The spike at the wrap-around point was only half handled, and the "spike tip at the start" case does happen (the first non-tree corner isn't necessarily on primitive 0,
  so the previous agent's reasoning didn't hold); found with a test that shuffles primitive order randomly 60 times, fixed.
- The corner left after removing a spike is now "the one whose outgoing edge still exists", so vertex attributes follow correctly.
- Removed several guards proven redundant (spanning tree + consistent winding ⇒ the boundary is always a single loop; the reasoning is in the comments).

**Different from Houdini**: the bridge follows the selected edges remaining in the spanning tree, not necessarily the shortest (in a 5×5 with the hole in a corner the bridge has 3 segments);
the docs don't say how Houdini picks bridges. Recompute Normals only recomputes the class that already had N, and doesn't create new ones
(the docs only say "recompute normals").

**Not done**: Create Disjoint Polygons (the docs only say "produces disconnected surfaces", without saying which primitives or how holes are handled),
Remove Degenerate Bridges, Create Curves When Dissolving Boundary.

## Normal → PCG_Normal

**Done** (all at the end, implemented in ops.normal_sop): Group Type (Guess / Points / Vertices / Primitives /
Edges), Override Normal (which attribute to write), Compute Normals, Keep Original Normal Where Computed Normal Is
Zero, Make Normals Unit Length (docs: grayed out when Compute is on, so it only takes effect with Compute off),
Reverse Normals (done last, only touches what is in the group).

**Different from Houdini**
- Guess = old behaviour (Group is parsed as the Add Normals to class), not Houdini's "treat as a primitive group when ambiguous".
- When Group Type is given explicitly, expansion to the Add Normals to class uses "touching counts".
- The docs say: with no existing normals and Add to = Vertices, all vertices are first computed with cusp 180, then the group's.
  Not followed here (outside Group it's the computed value directly, as before). Changing it would alter old behaviour; left for the coordinator to decide.

## Clip → PCG_Clip

**Done** (all at the end): Orient Plane with (Direction / Transform + Translate / Rotate),
Snapping Tolerance, Fill Polygons along Clipping Plane, Split Connectivity, Clip Attribute,
two output groups Clipped Primitives / Filled Polygons (governed by the Create Groups toggle like the original three groups;
default names left empty = not created, so old graphs with Create Groups on don't get extra groups).

**Not made clear by the docs, decided here**
- Transform's base normal is (0,1,0), i.e. Direction's default; rotation order X→Y→Z (Houdini's Rx Ry Rz).
  Distance applies in both modes.
- Snapping only moves points used by the primitives being clipped (in Group).
- Fill: the open edges on the plane are joined into loops; counterclockwise ones are outer outlines, clockwise ones are holes; a hole is merged by one shortest bridge into the
  **innermost** outer outline containing it (a prim has only one vertex loop). Where two openings meet at a point, they are cut apart at that point and each is filled separately.
  The number that can't be filled (holes without an outer outline, open chains) is written to the detail `clip_fill_skipped`. Where there is already a primitive on the plane, nothing is filled.
  With Keep All, each side gets its own fill, belonging to its own above / below group.
- Split Connectivity: points used by both sides get a separate copy for the above side; primitives outside the group don't count as either side.
- Clip Attribute uses only the first three components, padding with 0 if there are fewer (the docs' wording); the cut seam / fill are also found in attribute space.

**Not done**: Replace Existing (set_group here always overwrites; the meaning of that sentence in the docs is unclear).
The bridge is "the closest pair of points"; in extreme cases with several holes crowded together bridges may cross; not handled.

## Mirror → PCG_Mirror

**Done** (all at the end): Group, Operation (Mirror All Primitives / Clip Primitives and Mirror),
Orient Plane with (Direction / Transform + Translate / Rotate), Distance, Reverse Normals (default on =
the winding was always flipped before). The original `mode` dropdown (mirror | append) is really Houdini's Keep Original; the panel label was changed to
"Keep Original", the tokens are unchanged.

**Decided here / uncertain**
- With Group + Keep Original off (mode = mirror), the output is **only** the mirrored copies of the primitives in the group; primitives outside the group are dropped too.
  This is based on the docs' sentence "when off, only the selected geometry remains" (paraphrased version); I couldn't check the original wording verbatim. **The coordinator / author needs to confirm**:
  Houdini may instead be "primitives outside the group are kept as is, only those in the group are replaced by their mirror".
- Clip and Mirror clips with the mirror plane and keeps the half on the normal's front side (docs: "removes primitives below the plane");
  the original is the clipped copy too.
- Transform's base normal is (1,0,0) (Direction's default), rotation order X→Y→Z.

**Not done**: Only Consolidate Unshared Edges (our welding is a global fuse, not "weld only with its own mirrored points";
doing it would require changing the welding method first), Reverse U / V (only useful for mesh surfaces like NURBS).

---

## Mutation testing

The script is in the scratchpad; 206 hand-written mutants cover every function / branch newly written or changed in this package, plus the node wiring
(swapped parameters) and sop_map. All run with `PYTHONDONTWRITEBYTECODE=1 python3 -B`, deleting
`__pycache__` after each mutant, and `git diff` at the end to confirm the source files were restored. One round was at risk of being hit by another agent's `pkill -f mut.py`,
so at the end the whole table was run again in full.

48 survived the first round, handled as follows:
- Targeted tests added (the majority): boundary → vertex / prim, vertex → prim, open-curve perimeter counting only the segments that actually exist,
  Delete Unused Groups on a point cloud, Override Normal under each Add to, Compute off + Reverse only,
  Make Unit having no effect with Compute on, the Rotate X field on its own (X / Y swapped), Snapping tolerance boundary,
  Snapping moving only the points in the group, Split with primitives outside the group, nested outer outlines, two holes in one ring, openings that meet,
  bridged Dissolve with random shuffling / unselected edges / corner identity, and so on.
- Error guards: the assertions now match our own error text (downstream would also have raised, just with an unclear message).
- Code proven redundant was deleted: `| ~seg` in Delete's degenerate criterion, the "take only one half-edge per edge" filter in Dissolve,
  the three guards in Dissolve's loop walk (`not keep`, `hops`, the length check), the second equality of the winding check, `~flat` in Clip's openings,
  `on[vp]` in Split, `dpt != 0` in Snapping, the duplicated `make_unit and not compute` in Normal,
  `len >= 3` for opening loops. The reasons are written in the code comments.

**2 remained at the end, both equivalent:**
1. deletesop `cnt < where(closed, 3, 2)` changed to an open-curve threshold of 1: with the current counting, an open curve's "distinct point count" is only ever
   0 or ≥ 2, so a threshold of 1 or 2 gives the same result (explained in the comment). Kept 2, matching the docs literally.
2. clip `split_connectivity and keep == "both"` with the keep condition removed: when only one side is kept the other side's primitives are already gone,
   so nothing can be split. The condition is kept so that the panel's "hide when keep != both" matches how the code reads the parameter.

## Side findings (not in this package, not changed)

- **PCG_Delete's Expression page**: the default expression `@P.y > 0` raises an error right away with Entity = Primitives
  (primitives have no P attribute, and group expressions don't automatically take the primitive center). The baseline is like this.
- PCG_Delete's first Entity item is `point`, so a freshly created node deletes points by default; Houdini's default is Primitives.
  This is old behaviour, left alone.
- The Number page's every_nth mode is labelled "Delete by Pattern (Every Nth)", which is easy to confuse with the newly added real Delete by Pattern.
  It's only a panel label and changing it wouldn't affect workflows, but I didn't change it; left for the coordinator to decide.
