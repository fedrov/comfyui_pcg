# c4_pattern_shape (pcg100): COP shape / pattern batch

All doc pages were re-checked with WebFetch (sdfshape / uvshape / tilepattern / weave / knit / cellpattern /
chladni / labs--uv_grid_texture-1.1). These SideFX pages **have only parameter names and a one-sentence description each**, no formulas and no defaults,
and many menus (SDF Shape's Marker class, Knit's Preset) only show even their option names in screenshots. That is why everything below marked "decided here" exists.

Tests: `test_audit_c4_pattern_shape.py`. "Bit-for-bit identical to before the change at default values" uses the hard-coded digests GOLDEN (the same set of calls on the pre-change commit
c87c5d9, arrays rounded to 5 decimals before sha1 to dodge last-digit differences between machines' libm; recomputed with `--digests`),
independent of git, and also runs in the `comfyui_pcg/tests/` layout. During development I also compared bit-for-bit once against the full pre-change arrays (an npz in the
scratchpad): the old 5 shapes × numpy / exact and the old 8 patterns were bit-for-bit identical.

---

## SDF Shape → PCG_COPShape (shapes / parameters added)

Done (all appended to the end of INPUT_TYPES, defaults = old behaviour):
- 11 entries appended to the end of the Shape dropdown: `polygon` `squircle` `trapezoid` `triangle` `diamond` (Basic),
  `egg` `moon` `vesica` `cross` `arch` `arrow` (Compound). Implemented in the new file `geo/cop/sdf2d.py`, computed in numpy
  float64 and then handed to the backend (these formulas have many branches; not worth writing them twice in both the numpy and torch operator tables).
- Circle: `arc`, `thickness`, `round_ends`.
- Rectangle (both box and rounded_box): `separate_corners` + `corner_tl/tr/bl/br`.
- Line: `separate_thickness` (Houdini's Add Thickness) + `start_thickness` / `end_thickness`.
- Transform: `shear`, `uniform_scale`.
- Per-shape parameters: `squircle_blend`, `trap_top`, `use_points` + `tri_p0/1/2`, `roundness` (shared by Egg /
  Vesica), `moon_inner` / `moon_offset`, `cross_inset` / `cross_bevel`, `arrow_shaft` /
  `arrow_head` / `arrow_head_ratio`. Old parameters reused: Polygon's side count uses `points` (Houdini's Star and Polygon
  both call it Number of Sides; the panel label was changed to that), Radius serves Polygon / Squircle / Egg / Moon (outer radius) / Vesica /
  Cross (Size), Size serves Trapezoid (bottom half-length / half-height) / Triangle / Diamond / Arch, Start / End serve Arrow.
- Panel (g8): each new parameter is hidden / disabled according to whether the code actually reads it (Radius disabled for Line + Add Thickness;
  Size disabled for Triangle + Use Points; Corner Radius disabled when Separate Controls is on; Round Ends
  disabled with Arc or Thickness ≥ 1).

Accuracy: everything except Squircle is an **exact SDF**; the tests check point by point against hand-computed values (apothem, corner distance, end-cap distance …), and during development
I also compared against a brute-force distance to the zero isoline on a 900² grid (all errors within one grid step). Squircle has no closed-form distance, so it uses
the first-order correction f/|∇f|: the zero isoline is exact, and it is an exact circle at Blend = 2 and also exact at Blend = 1 (a diamond).

Decided here (not specified by the docs):
- Arc / Thickness use a value instead of "toggle + value": 1 = off (Houdini has toggle + value and the value only has an effect below 1, so it's equivalent).
  Arc is the fraction kept (Arc × 360°), opening toward −y; Thickness is the ring width as a fraction of the radius, outer edge fixed. Round Ends only takes effect when
  both are < 1 (the docs' wording).
- The four corner radii 0~1 are fractions of the **shorter half side** (docs: "1 with equal sides is a circle").
- Start / End Thickness are full widths.
- Trapezoid's Top Length is a **half-length** (consistent with Size, both are half-sizes).
- Triangle without Use Points has vertices (−sx,−sy), (0,sy), (sx,−sy) (Width / Height use twice Size).
- Egg: the lower circle's center is at the origin, tip toward +y (the natural origin of Quílez's sdEgg, not centered by bounding box). Roundness = top circle radius /
  Radius.
- Vesica: Roundness → the distance between the two circle centers d = Radius·(1 − Roundness); 1 is a circle. The docs only say "vertical thickness".
- Moon: a negative Inner Offset cuts to the left (mirrored). Offset = 0 gives a concentric ring (the formula divides by zero, nudged by 1e-9).
- Cross: Size = arm tip to center (uses Radius), Inset = side length of the square cut from each corner (arm half-width = Size − Inset), Bevel
  = the fillet radius of the concave corners, clamped to ≤ min(Inset, arm half-width). Inset ≥ Size degenerates to the distance to the cross lines (no error).
- Arch: a rectangle of width 2·size_x (height 2·size_y) topped by a semicircle, centered by bounding box; Height 0 = a semicircle (the docs' wording).
- Arrow: head length = total length × Head Ratio; coincident start and end degenerate to the distance to that point.
- Shear is a single number, a horizontal shear in local coordinates (after rotation) x' = x + Shear·y; Uniform Scale is divided out before the inverse of the shear
  and the distance multiplied back (keeping the SDF exact). The docs don't give Houdini's Transform order. Uniform Scale = 0 raises an error.

Still different from Houdini / not done:
- **No Shape Class level**; one dropdown lists every shape (the old token order can't change).
- **Not done**: the whole Marker class (the docs don't even list the shape names), Spiral (geometric definition of Arc Bend / Number of Arcs unclear),
  Wave (Arc "0.5 looks like a sine, 1 folds" -- construction unclear), Fishscale / Octagon-dot (only "for fish-scale / octagon-dot
  tiling", no shape definition), Horseshoe (mapping from Separation to opening angle unclear), Quadratic Circle (one sentence in the docs),
  Line's Bulge, Line's Length (we always use start and end points, equivalent to Use Points always on), Star's Angle Factor
  (our Star uses an Inner ratio, a different parameterization; a second set wasn't added).
- The size_ref input (we build the image from Resolution).

Mutation testing: about 50 mutations of the newly written branches in sdf2d / generate. Of the first round's 40, 7 survived, handled as follows:
- Squircle's Blend lower bound, Arc boundary comparison, the interior branch of the flat-capped ring sector, Moon's ε when concentric, the "outside the circle" test
  in the cross corner fill -- all got targeted tests (a point on the concave side at Blend 0.5, two points 0.05° off the 45° edge, an interior point beside the end cap, a concentric ring,
  0.0005 outside the arc midpoint) and were killed.
- The cross arc segment's "one-eighth truncation" and arc endpoint distance, the fill's `y ≥ a` condition, the two special cases `a ≤ 0` and `a ≥ s`: proven
  **redundant** (after folding, the distance from a point to the other half of the arc is the distance to the whole arc; the arc endpoints are covered by the segments along the arms; the y < a part is already
  inside the arm; the two special cases are continuous limits of the general formula) -- code removed and rewritten more simply; the brute-force grid check is still exact.

Side finding:
- The node's `numpy` backend computes the SDF in float32 (old behaviour); only `exact` is float64. The new shapes follow the same rule.

---

## [C] UV Shape → new node PCG_COPUVShape

The audit concluded "not the same algorithm" (COP Shape outputs an SDF, UV Shape outputs parametric coordinates inside the shape), so per [C] COP Shape is left alone
and a new node was added (nodes_cop2.py, implemented in `geo/cop/uvshape.py`); copernicus_map's UV Shape now points to it,
icon `ux_uvshape` (a polar grid inside a disk).

Done:
- Shapes: `disk`, `annulus`.
- Disk Mode: `linear` (Fong's Simple Stretching, concentric circles → concentric squares), `polar` (U = angle/π,
  V = 2r − 1), `equal_area` (inverse of the Shirley–Chiu concentric mapping; the test verifies the Jacobian determinant = 4/π everywhere),
  `squircle` (Fong's FG-squircular), `elliptic_arc` (Fong's Elliptical Grid: grid lines map to elliptical arcs).
- Annulus Mode: `polar` (V maps [inner, outer] linearly → [−1, 1]), `log` (by ln r).
- Transform: Offset (`"x y"`), Angle, Shear; UV section: U / V Border (clamp / mirror / wrap / extend),
  U / V Scale, UV Filter Bound.
- Output layers uv / uvscale / mask (empty layer name = not output). When a cop is connected, its resolution is used and its layers are kept (Houdini's size_ref).

Decided here (not specified by the docs):
- Coordinate system matches COP Shape (centered, normalized by the short side); Radius / Inner / Outer are measured in it.
- uv value range: by default the docs' [−1, 1] (`uv_range = signed`); our UV Sample takes 0~1, so an extra mode
  `unit` = (uv + 1)/2 was added -- **this is our extension**, Houdini doesn't have it. Border is applied in [−1, 1] before the conversion.
- Formulas for the five disk mappings: the docs give one sentence each; we use the standard formulas matching the names (see above). Elliptic Arc is interpreted as Fong's
  Elliptical Grid (under that mapping the grid lines become elliptical arcs); **not certain** it matches Houdini exactly.
- Polar's U starts from +x, counterclockwise positive; V = 2r − 1 (−1 at the center). Annulus likewise.
- Transform order: shear → rotate → translate, then multiply by U/V Scale, finally Border.
- uvscale = the largest singular value of the Jacobian of uv with respect to pixel coordinates (uv units / pixel, central differences with a half-pixel step); for the modes where U is an angle,
  the jump at ±1 is removed using the period 2·U Scale, then clamped to UV Filter Bound. The docs only say "shows how much the uv is stretched".
- mask is judged at the pixel center, r ≤ Radius, 0 / 1 without anti-aliasing (docs: "1 inside and 0 outside").

Not done:
- Disk's Conformal (Schwarz–Christoffel; needs elliptic integrals / Jacobi elliptic functions, which numpy doesn't provide).
- Square (2-fold / 4-fold folding, Vertex orientation, Flip Tile Orientation -- the docs don't make clear how the folded regions
  map), Horseshoe (one sentence on what U Adjust means), Spiral (three spirals + Arc Length mode, a lot of work,
  and the docs don't give the Loxodrome's Möbius transform parameters), Fishscale (depends on the Disk mapping + a grid; the formula for the Center Blend exponent
  is unclear).

Mutation testing: 31 mutations. 10 survived the first round:
- Killed with added tests: x coordinates on non-square images (compared point by point with generate.aspect_coords), squircle quadrant signs, the annulus seam,
  mirror's m ≤ 2, uvscale's step based on the short side, the cross term in the singular value (Shear 1 → golden ratio, rotation invariant),
  the seam period at U Scale 2.5 (3 is a multiple of 2 and can't kill it, so 2.5), mask's ≤.
- Equivalent, kept with an explanation: linear's k at the origin (r = 0, the product is 0 either way; removed the where while at it);
  equal_area's `ax >= ay` (both branches give the same value on the diagonal); mirror's `m <= 2` (at m = 2 both branches are 1).

---

## Tile Pattern → PCG_COPPattern (kind = tile) gets Bond

The audit said our Pattern collection and Houdini's Tile Pattern "are really different nodes". True: Houdini's Tile Pattern is
"lay out tiles → stamp an SDF Shape into each → composite by Draw As / Blend", plus the two big Prune / Split sections. Our tile
mode is "brick face mask + bevel height + id/uv". By priority, only the most central and best-defined part of the layout was added -- **bonds**.

Done:
- `bond` (appended at the end, default `offset` = the original "each row shifted by Row Offset bricks"): `stack`, `stretcher`, `header`,
  `flemish`, `english`, `american`; `header_interval` (American: a header course every N rows, default 6).
- Implementation `_tile_bond`: each bond = a periodic sequence of brick widths within a row + a per-row right shift; outputs the same set of layers as the original tile mode
  (main / _id / _height / _edge / _rand / _uv). The right shift is written as the same expression as the original offset mode, so
  stretcher ≡ Row Offset 0.5 and stack ≡ Row Offset 0 are **pixel-for-pixel identical on all six layers** (the tests use this to cross-check).
- Panel: Bond / Header Interval; with Bond ≠ offset, Row Offset is grayed out (the code doesn't read it).

Decided here (not specified by the docs):
- Units: the horizontal Tile Count = the number of stretchers in a row; a header's exposed face is half a brick wide (real bricks are 2:1).
- Header alternates rows offset by ¼ brick (half a header); Flemish alternates by ¾ so the headers sit centered on the stretchers of the next row; English row 0 is
  a stretcher course shifted right by ¾ (docs: "each row starts with a 3/4 brick"); American has a header course every Header Interval rows from row 0,
  the rest are stretchers offset by half a brick.
- Mortar width / bevel are converted from the short side of a **stretcher cell**; joints for headers and stretchers are equally wide.
- Tiling: one Flemish stretcher+header group = 1.5 bricks, so the horizontal brick count must be a multiple of 3 to be seamless; when it can't tile, the id of the brick on the right edge
  collides with the one on the left edge (noted in the docstring).

Not done (amount of work / unclear definition in the docs):
- Monk (a Flemish variant; the docs don't say the row offset), Double English, Windmill (Iris ratio), Cross Hatch,
  Basketwave, Hopscotch, Herringbone N:1 / 3:2 (diagonal laying, needs rotated cells and an id scheme), French, Custom
  Pattern (nested multi-parameters / expressions).
- The whole Shape / Drawing / Stamping section (stamping an SDF shape into each tile, Draw As Filled / Distance / Gradient /
  Outline, 7 Blend Methods) -- that amounts to writing a separate "stamp per cell" node; our COP Scatter Shapes
  does something similar.
- Value (Tile Value / Variation / Background), Position (column offset, jitter), Rotate, Size, Prune Tiles,
  Split Tiles, Pattern Size / Clip, Flip Pattern.

Mutation testing: 18 mutations, 2 survived: `if not m.any(): continue` is a pure optimization (assigning an empty mask has no side effect) -- removed;
`searchsorted(side="right")` only differs when a pixel center falls exactly on the joint between two kinds of brick within a row -- added a
flemish 6×2 / 9-pixel-wide test (x = 1 is exactly a pixel center), killed.

---

## Chladni Cymatic Patterns → PCG_COPPattern (kind = chladni)

Done (appended at the end):
- `chladni_output`: `pixel_lines` (default = the original "draw nodal lines by pixel width", our extension), `nodal_lines`
  (Houdini's Nodal Lines: threshold + smoothing), `absolute`, `signed` (one-to-one with Houdini's Output Mode).
- `amplitude` (scales the a wave, and therefore the whole output), `amplitude_ratio` (weight of the b wave relative to a), `threshold`,
  `smoothing_width`.
- Panel: Line Width is editable only in pixel_lines, Threshold / Smoothing only in nodal_lines (disabled,
  not hidden, so they can be compared when switching).

Formula: f = A·[cos(nπx)cos(mπy) ± k·cos(mπx)cos(nπy)], A = Amplitude, k = Amplitude Ratio;
A = k = 1 is the original formula (the GOLDEN digests verify it is bit-for-bit unchanged at default values).

Decided here (not specified by the docs, and the docs give no formula either):
- "b is a scaled version of a": interpreted as our existing two-term symmetric mode shape, with the b term multiplied by k.
- Nodal Lines' transition band sits **below** the threshold: |f| ≤ T − W is white, ≥ T is black, smoothstep in between; W = 0 is a hard edge
  (|f| < T white). This way the docs' "everything above the threshold is black" holds strictly.
- In the pixel_lines mode Amplitude only affects the _value layer (line width is based on |f|/|∇f|, independent of amplitude).

Still different from Houdini / not done:
- Different frequency parameterization: we use Modes "n m" (both may be non-integers) + Sign, Houdini uses Frequency + Frequency
  Anisotropy (logarithmic) + Tile Size. The two can express each other (n and m are the frequencies in the two directions); a second set wasn't added.
- The pos / a / b / m / n input layers (per-pixel modulation) not done.

Mutation testing: 11 mutations, 2 survived (the hard-edge guard `w <= 0`, the comparison `af < T`) -- both only differ when |f| exactly equals the threshold;
killed after adding a test that "sets the threshold to some pixel's |f|" (that pixel must be black, no NaN anywhere in the image).

---

## Cell Pattern → PCG_COPPattern (kind = cell)

Done (appended at the end, defaults = old behaviour):
- `cell_metric`: `euclidean` (the original) / `manhattan` / `chebyshev`.
- `lattice`: `grid` (the original) / `hexagonal` (feature points on odd rows shifted right by half a cell).
- `density` + `density_seed`: each cell is culled by `rnd(id, density_seed)`; cells whose random number ≥ Density get their main layer
  (mask) set to 0; 1 = keep all. Only the main layer changes; id / edge / dist / rand are unchanged.

Tests: with Jitter 0 the cells are square under all three metrics, _edge = pixel distance to the cell edge, _dist = distance to the cell center under each metric (hand-computed);
with Jitter 1, 3 metrics × 2 lattices compared pixel by pixel with a brute-force nearest-point search (id, _dist, non-Euclidean _edge = (F2−F1)/2,
Euclidean _edge = distance to the nearest bisector). During development the same brute-force comparison was also run on 12 seeds × 2 cell counts.

Decided here / different from Houdini:
- Under Manhattan / Chebyshev the "bisector" isn't a straight line, so _edge uses (F2 − F1)/2: exact along the line joining the two points, approximate elsewhere
  (edge thickness will vary). Euclidean is still the true distance to the bisector. Houdini's Smooth Edge only works for Euclidean;
  we didn't do Smooth Edge.
- Hexagonal: the docs say "simplex grid (triangles)"; we implement it as "odd rows offset by half a cell", which gives regular
  hexagons at a cell aspect ratio of 2 : √3. Vertically it needs an even row count to tile seamlessly.
- Cells culled by Density are "hollowed out" (main layer 0); neighbours don't grow into them. The docs only say "randomly culled".

Not done: Amplitude / Shift / Element Scale (anisotropic) / Jitter Scale / Smooth Edge / Offset / Tile Size /
Shape Mode (Absolute / Relative) / Random Height / Bevel Ramp / Orient (tilt) / Distort / post-processing
(Fold / Complement / Bias / Gain / Gamma / Contrast / Clamp -- these can be done with COP Levels / Remap nodes) /
the direction, density, height, rotation input layers / the border, center outputs (our _edge is the SDF of border;
center isn't output).

Mutation testing: 13 mutations, 3 survived:
- Neighbourhood windows: euclid + hex uses ±3, non-Euclidean grid ±3, non-Euclidean hex ±4 (the original euclid + grid is still ±2). The mutation changing all of them back to
  ±2 survived -- a brute-force comparison over 60 seeds × 3 cell counts × 5 combinations **found no counterexample**, but I can only prove that the wider
  windows are always enough (derivation in the code comment), not that ±2 is always enough. **Kept the wider windows** to be safe, at the cost of the non-default modes being
  2~3× slower. The coordinator needs to know about this one.
- `if not euclid:` only skips the F2 computation the Euclidean mode doesn't use (removing the guard doesn't change the result); it is a performance guard, kept.

---

## Labs UV Grid Texture → PCG_COPPattern (kind = uv_grid)

Done (appended at the end, defaults = the original look, verified by GOLDEN + the bit-for-bit baseline during development):
- `tile_coloring`: `hue` (default = the original "hue by column, brightness checkerboard", our extension) / `uniform` / `checker` /
  `gradient`; `tile_color1` / `tile_color2`.
- Outlines: `outlines` (toggle, default on = the original 1-pixel line), `outline_width` (pixels), `outline_color`.
- Markers: `marker_type` (`text` default / `cross` / `arrow`), `text_mode` (`letters` default / `coordinates`),
  `marker_size` (default 0.32 = the original font-size ratio), `marker_coloring` (uniform / checker / gradient),
  `marker_color` / `marker_color2`. The original `labels` toggle is kept, with the panel label changed to Draw Markers (off = no markers
  at all).
- Panel: colors use colorstr; each parameter is disabled according to whether the code reads it (the hue mode doesn't read the two tile colors, uniform doesn't read color 2,
  outlines off doesn't read width / color, non-text markers don't read Text Mode / Font …).

Decided here (not specified by the docs, which give no defaults either):
- Gradient: linear from color 1 to color 2 by tile index (starting at the lower left, rows first then columns), one color per tile.
- Coordinates text is "i,j" (from 0, lower left is 0,0).
- Cross: full length = Marker Size × the tile's short side, arm width = full length × 0.16; Arrow: points to +v (shows whether the UVs are rotated / flipped),
  shaft width 0.16, head width 0.6, head length 0.4 (all relative to the full length). Both are analytic SDFs with anti-aliasing (reusing sdf2d).
- Outline coverage = clip(0.5 − (distance to tile edge − line width/2)); at line width 1 this is the original formula.

Not done: Add Rounded Corners / Corner Radius / Background Color (the background color only matters with rounded corners), Grid Divisions
(subdivision inside each tile -- our Tile Count is the tile count), Output File / Render (export goes through the COP Export node).

Mutation testing: 13 mutations, 2 survived (the cross arm-width constant, anti-aliasing replaced with a hard edge) -- killed after adding analytic coverage values (two pixels, on the arm / beside the
concave corner).

---

## Weave → PCG_COPPattern (kind = weave)

The audit said "our plain / twill / satin don't match Houdini's Arrangement". Checking the docs: Houdini's Checkerboard
is our plain (1/1 plain weave); Every Nth Column / Every Nth Tile are two toggles + N, but the docs **don't say** how multiple toggles
combine when on together, or what happens to columns other than "only every Nth column crosses on top" -- not done, to avoid building something just for show.

Done (appended at the end):
- `custom` appended to Weave Type: the over/under arrangement comes from a layer on the input cop (`weave_layer`, Houdini's pattern input).
  At each crossing center ((i+½)/nu, (j+½)/nv) the nearest pixel is taken; channel 0 > 0.5 = warp (vertical) on top. The layer can be any
  resolution. custom + a checkerboard image ≡ plain, custom + a twill image ≡ twill (all five layers pixel-for-pixel identical, verified in the tests).
- `separate_widths` + `weft_width`: a separate thread width for the weft (horizontal), corresponding to Houdini setting Row Inset / Column Inset
  separately (gap = 1 − thread width). When off, Thread Width is shared by both directions (old behaviour).

Decided here: the sample position (nearest pixel to the crossing center) and threshold 0.5; Inset is expressed as "thread width" (we already had Thread Width).

Not done: Every Nth Column / Every Nth Tile (combination rules unclear), Weave Multiplier (multiplies the number of interlacings; the docs don't say
how), Edge Gradient / Overlap Gradient + Ramp (our cross-section is fixed as a semicircle + cosine undulation), Fiber Scale /
Fiber Strength (fiber detail), the uv output (per-thread uv). Our twill / satin are extensions, kept.

Mutation testing: 8 mutations, 2 survived (sampling the crossing at the cell origin, horizontal scaled by image height) -- killed after adding "only the single pixel at the crossing center
is 1" and "an 8×4 non-square layer".

---

## Knit → PCG_COPPattern (kind = knit): **skipped**

The core gaps are Knit Shape Type's Purl (the docs only say "bulging stitches controlled by bulge and wrinkle", no shape definition) and
a whole Transform set (Uniform / Variance / Min-Max for Scale / Stretch / Angle, Jitter, Round to Multiples)
+ 8 modulation input layers + Preset (the preset names are only in the screenshot). The docs themselves say these transforms are best left at default in Knit mode (they break
the interlocking of the loops). Our knit mode is a stockinette (V-shaped) height map, the same kind of thing as Houdini's Knit shape, but with a completely different parameterization
(Weave Width / Height / Radius, Fiber Strength / Cycles / Twist, Double Knit / Invert Knit each have only one sentence of
description). Without a reproducible definition, not done. The audit says the knit mode "only has Weave Type / Thread Width" -- that's a misreading caused by the panel
not hiding them properly: in the code the knit mode only reads Counts and Seed (Weave Type / Thread Width are already hidden by kind).

---

## Side findings / things the coordinator needs to know

- PCG_COPPattern alone covers 8 Houdini nodes, and this package appended another 25 widgets to its end (23 → 48),
  all hidden / grayed by kind. The panel is fine, but this node's positional array in workflow JSON will be long; if it is ever to be split into separate
  nodes (Tile Pattern / Cell Pattern / UV Grid …), now is the last cheap moment.
- Cell Pattern's non-default modes use larger neighbourhood windows than before (see above), a conservative choice.
- `test_panel_e2e.py` is 0/0 on this machine (needs a browser), so the panel's actual rendering wasn't covered.
