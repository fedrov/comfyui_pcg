# Loops

For-each loops and frame loops.

9 nodes.

[Back to the reference index](README.md)

## Contents

- [For-Each Begin (PCG)](#pcg-foreachbegin) — Starts a for-each loop block and hands each piece, point, primitive or iteration index to the loop body.
- [For-Each End (PCG)](#pcg-foreachend) — Ends a for-each loop block and gathers the results of all iterations.
- [For-Each Frame Begin (PCG)](#pcg-foreachframebegin) — Starts a per-frame loop that re-evaluates the loop body for each frame and outputs the frame number and time.
- [For-Each Frame End (PCG)](#pcg-foreachframeend) — Ends a per-frame loop and collects each frame's geometry and/or COP image into sequences.
- [Geo Sequence Pick (PCG)](#pcg-geosequencepick) — Picks one frame from a geometry sequence by index, wrapping around at the end.
- [Retime (PCG)](#pcg-retime) — Remaps the timing of a geometry sequence to a new sequence, by speed, by target length or by a time-warp curve.
- [Select Best (PCG)](#pcg-selectbest) — Scores every geometry in a sequence with an expression and outputs the best one, the top K and a ranked report.
- [Time Blend (PCG)](#pcg-timeblend) — Extracts one geometry at a fractional frame of a sequence by interpolating between the two neighbouring frames.
- [Trail (PCG)](#pcg-trail) — Builds a trail from the previous frames of a geometry sequence, as stacked copies, polylines, a swept mesh or a velocity attribute.

## Nodes

### For-Each Begin (PCG)

<a id="pcg-foreachbegin"></a>

`PCG_ForEachBegin` · category `PCG/loop`

Starts a for-each loop block and hands each piece, point, primitive or iteration index to the loop body.

Equivalent of Houdini's Block Begin. It decides how the input is cut into pieces and how many times the chain between Begin and For-Each End runs. Connect Begin's `loop` output to For-Each End's `loop` input; that link is how End finds its Begin, and without it there is no loop.

Iteration Method: **By Pieces** makes one iteration per distinct value of Piece Attribute (typically `name` or `class`), on primitives or points; **By Primitives** and **By Points** make one iteration per element; **By Connectivity** makes one per connected component; **By Count** does not cut the geometry and simply runs Iterations times with the whole input. Group restricts the elements that are cut (all other modes except count). Pieces on points keep isolated points and only primitives whose points are all in the piece.

Method controls what the `geo` output carries: the current piece (**Extract Piece or Point**), the result of the previous iteration (**Fetch Feedback**, the original input on the first iteration), or always the original input (**Fetch Input**, equal to the `input` output). The `input` output always carries the uncut input, so no second Begin is needed for that.

Iteration metadata is written as detail attributes on `geo`: `iteration`, `numiterations`, `value` (string) and `ivalue`, so Wrangles inside the loop can read them with `detail()`. `value` is the piece attribute value in piece mode and the element or iteration number otherwise; `ivalue` is that value as an integer when it is numeric, else the iteration index.

The loop is realised by expanding the loop body one iteration at a time, so with many iterations the node ids grow longer; Max Iterations is the safety stop. Nested loops are supported. If there are zero pieces, the body still runs once on an empty geometry that keeps the input's attribute layout, and End outputs an empty result.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to iterate over. |
| `_state` *(optional)* | PCG_LOOP | Internal. Injected by For-Each End when it expands the loop; not shown or used manually. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `loop` | PCG_LOOP | Loop state. Connect to the `loop` input of the matching For-Each End. |
| `geo` | GEOMETRY | Geometry for the current iteration, depending on Method. Carries the iteration detail attributes. |
| `input` | GEOMETRY | The complete, uncut input geometry. |
| `iteration` | INT | Current iteration index, starting at 0. |
| `numiterations` | INT | Total number of iterations. |
| `value` | STRING | Value of the current piece as text: the attribute value in piece mode, otherwise the element or iteration number. |
| `ivalue` | INT | `value` as an integer when it is numeric, otherwise the iteration index. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Method `method` | menu | Extract Piece or Point | What the `geo` output provides. Extract Piece or Point gives the current piece; Fetch Feedback gives the previous iteration's result (the original input in the first iteration) for feedback loops together with End's `feedback` gather; Fetch Input always gives the original input. Options: Extract Piece or Point (`fetch_piece`), Fetch Feedback (`fetch_feedback`), Fetch Input (`fetch_input`). |
| Iteration Method `iterate_over` | menu | By Pieces (Attribute) | How the input is split into iterations: by distinct values of an attribute, per primitive, per point, per connected component, or by a plain count with no splitting. Options: By Pieces (Attribute) (`pieces`), By Primitives (`primitives`), By Points (`points`), By Connectivity (`connectivity`), By Count (`count`). |
| Piece Elements `piece_elements` | menu | Primitives | Whether pieces are formed on primitives or points. Only used with By Pieces and By Connectivity; the other modes imply their element class. Options: Primitives (`primitives`), Points (`points`). *Hidden when iterate_over ≠ pieces iterate_over ≠ connectivity.* |
| Piece Attribute `piece_attribute` | string | `name` | Attribute whose distinct values define the pieces, for example `name` or `class`. It must be a scalar or string attribute on the chosen element class, otherwise the node errors. *Hidden when iterate_over ≠ pieces.* |
| Iterations `iterations` | int [0..] | 10 | Number of iterations for By Count. The geometry is not cut. *Hidden when iterate_over ≠ count.* |
| Group `group` | string | *(empty)* | Group pattern limiting which elements are split into pieces. Empty uses all elements. Not used by By Count. *Hidden when iterate_over = count.* |
| Max Iterations `max_iterations` | int [1..] | 1000 | Safety limit: the loop stops after this many iterations even if more pieces exist. |
| Single Pass `single_pass` | int [0..] | 0 | Iteration index to run when Use Single Pass is on. Clamped to the last iteration. |
| Use Single Pass `use_single_pass` | toggle | off | Debug switch. Runs only the iteration given by Single Pass instead of the whole loop, which is useful for checking the loop body on one piece. |

**Compared with Houdini**

In Houdini, Iteration Method, Piece Attribute and similar settings live on Block End, and Block Begin looks them up. Here they are on Begin and End keeps only Gather Method, so the settings are part of Begin's cache signature. The extra `input` output replaces a second Begin set to Fetch Input, and the Fetch Metadata method is replaced by detail attributes on `geo`. Zero iterations cannot skip the loop body entirely; it runs once on empty geometry.

**Tips**

- Use Single Pass to debug the loop body on one piece before running everything.
- To process fractured pieces separately, run Voronoi Fracture into By Pieces on the `name` attribute.

---

### For-Each End (PCG)

<a id="pcg-foreachend"></a>

`PCG_ForEachEnd` · category `PCG/loop`

Ends a for-each loop block and gathers the results of all iterations.

Equivalent of Houdini's Block End. The geometry connected to `geo` is the result of one iteration. `loop` must come directly from the paired For-Each Begin; it tells End which Begin to loop back to.

With **Merge Each Iteration** every iteration's result is merged into one geometry. With **Feedback Each Iteration** only the last result is kept; combined with Begin's Fetch Feedback method this makes an iterative feedback loop. The number of iterations and how the input is split are set on Begin, not here.

End's `geo` input has to be downstream of Begin: a link that comes from outside the loop body raises an error, because the loop would silently recompute the same result each time.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Result of the loop body for the current iteration. |
| `loop` | PCG_LOOP | Loop state from the paired For-Each Begin's `loop` output. |
| `_accum` *(optional)* | PCG_LOOPACC | Internal. Accumulator injected while the loop expands; not used manually. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The merged results of all iterations, or the last result in feedback mode. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Gather Method `gather` | menu | Merge Each Iteration | `merge` merges every iteration's result (Houdini's Merge Each Iteration). `feedback` keeps only the final iteration's result (Feedback Each Iteration), for use with Begin's Fetch Feedback. Options: Merge Each Iteration (`merge`), Feedback Each Iteration (`feedback`). |

**Compared with Houdini**

Iteration settings are on For-Each Begin rather than End; see the note on For-Each Begin.

---

### For-Each Frame Begin (PCG)

<a id="pcg-foreachframebegin"></a>

`PCG_ForEachFrameBegin` · category `PCG/loop`

Starts a per-frame loop that re-evaluates the loop body for each frame and outputs the frame number and time.

The way to make geometry change over frames. Connect `frame`, `frame_f`, `t` or `seconds` to parameters inside the loop body (convert the widget to an input; put an Expression in between to shape a curve) and the geometry follows the frame. The whole body is re-evaluated for every frame; nodes outside the block run once and stay cached. Connect `loop` to the `loop` input of For-Each Frame End.

**Method**: `input` starts every frame from the original input, so frame N depends only on `frame` (keyframe animation, procedural deformation) and frames are independent. `feedback` starts every frame from the previous frame's result and frame 0 from the original input, which is what Houdini's SOP Solver does (growth, accumulation, progressive fracture). Feedback is truly sequential.

**Cams**: connect a Camera Path and `cam` outputs the camera for the current frame, so a Render Pass in the body gets both moving geometry and a moving camera. The camera count must equal the frame count, or be 1 for a fixed camera; anything else is an error.

Frame metadata is also stored as detail attributes on `geo`: `frame`, `frameindex`, `numframes`, `t` and `time`, readable with `detail()` in a Wrangle. If no geometry is connected, an empty geometry is used.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` *(optional)* | GEOMETRY | Optional starting geometry. If not connected, the loop starts from empty geometry. |
| `cams` *(optional)* | PCGCAMSEQ | Optional camera sequence from Camera Path. Its length must equal Frames, or be 1. |
| `_state` *(optional)* | PCG_FRAMELOOP | Internal. Injected by For-Each Frame End while the loop expands. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `loop` | PCG_FRAMELOOP | Loop state. Connect to the `loop` input of For-Each Frame End. |
| `geo` | GEOMETRY | Geometry for this frame (original input, or previous frame's result in feedback mode), with frame detail attributes. |
| `frame` | INT | Current frame number (Start plus the iteration index), as an integer. |
| `frame_f` | FLOAT | The same frame number as a float, for float parameters. |
| `t` | FLOAT | Normalised time from 0 to 1 across the loop. 0 when there is only one frame. |
| `frames` | INT | Total number of frames in the loop. |
| `seconds` | FLOAT | Time in seconds since Start: (frame - start) / fps. |
| `cam` | PCGCAM | Camera for the current frame (or the single camera) when `cams` is connected. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Method `method` | menu | Fetch Input (Each Frame) | `input` starts each frame from the original input; frames are independent. `feedback` starts each frame from the previous frame's result (frame 0 from the original input), like a SOP Solver. Options: Fetch Input (Each Frame) (`input`), Fetch Feedback (Solver) (`feedback`). |
| Start Frame `start` | int | 0 | Frame number of the first iteration. |
| Frames `frames` | int [0..65536] | 24 | Number of frames to run. |
| FPS `fps` | float [0.01..1000.0] | 24 | Frames per second, used for the `seconds` output and the `time` detail attribute. |
| Max Iterations `max_iterations` | int [1..65536] | 1000 | Safety limit on the number of frames run. |
| Single Pass `single_pass` | int [0..65536] | 0 | Frame index (counted from 0, not the frame number) to run when Use Single Pass is on. Clamped to the last frame. |
| Use Single Pass `use_single_pass` | toggle | off | Debug switch. Runs only the frame given by Single Pass, so the chain can be checked before running everything. |

**Compared with Houdini**

The `feedback` method corresponds to a SOP Solver. The timeline is not read from a global `$F`; time comes only from this node's outputs.

---

### For-Each Frame End (PCG)

<a id="pcg-foreachframeend"></a>

`PCG_ForEachFrameEnd` · category `PCG/loop`

Ends a per-frame loop and collects each frame's geometry and/or COP image into sequences.

Collects the result of every frame into sequences. Connect `geo`, `cop` or both; at least one is required, and whatever is connected is collected. A typical setup sends `cop` to Sequence Export for video and `geoseq` to Sequence Motion for motion vectors.

The accumulated frames are held in memory as literals in the expanded graph. Memory is counted as the loop runs, and when it exceeds about 1 GB the node raises an error that explains the options: lower the resolution, keep fewer layers, use fewer frames or run in several segments. (240 frames of 1024x1024 with five layers is about 4.7 GB.)

**Inputs**

| Input | Type | Description |
|---|---|---|
| `loop` | PCG_FRAMELOOP | Loop state from the paired For-Each Frame Begin. |
| `geo` *(optional)* | GEOMETRY | Optional. Geometry result for the current frame, collected into `geoseq`. |
| `cop` *(optional)* | COPIMAGE | Optional. COP image result for the current frame, collected into `seq`. |
| `_accum` *(optional)* | PCG_FRAMEACC | Internal. Accumulator injected while the loop expands. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence, one geometry per frame. Feed to Geo Sequence Pick, Trail, Time Blend, Retime or Sequence Motion. |
| `seq` | COPSEQUENCE | COP image sequence, one image per frame. Feed to Sequence Export. |
| `merged` | GEOMETRY | All frames merged into one geometry when Merge Output is on. Otherwise the last frame's geometry is returned. |
| `frames` | INT | Number of frames actually collected. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Output Merged Geometry `merge_output` | toggle | off | Also merge all frames into one geometry on the `merged` output, for ghosting or seeing the whole motion at once. Off by default. |

---

### Geo Sequence Pick (PCG)

<a id="pcg-geosequencepick"></a>

`PCG_GeoSequencePick` · category `PCG/loop`

Picks one frame from a geometry sequence by index, wrapping around at the end.

Takes one geometry out of a geometry sequence such as the `geoseq` output of For-Each Frame End. The index wraps around (modulo the sequence length) instead of raising an error, because going out of range is normal while scrubbing an index. An empty sequence is an error.

A common use is checking an animation: pick frame 0 and frame 5 into two Viewports and compare.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence to pick from. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The selected frame's geometry. |
| `frames` | INT | Number of frames in the sequence. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Index `index` | int [0..] | 0 | Zero-based frame index. Values at or beyond the sequence length wrap around. |

---

### Retime (PCG)

<a id="pcg-retime"></a>

`PCG_Retime` · category `PCG/loop` · Houdini: Time Shift (SOP)

Remaps the timing of a geometry sequence to a new sequence, by speed, by target length or by a time-warp curve.

Builds a new sequence by choosing, for each output frame `i`, a (possibly fractional) source frame.

- **Speed**: source = `start + i * speed`. A speed of 0.5 is half speed, a negative speed plays backwards.
- **Output Length**: spreads `frames` output frames evenly over the whole source sequence. Changes duration only, not content.
- **Time Warp Channel**: source = a keyframe channel evaluated at `i`, for time warps such as rush, hold, ease out: `0:0  6:12  14:12  24:23`. This is the only mode that can express a pause.

Interpolation: **Integer Frames (Hold)** takes the nearest source frame, **Blend Subframes** interpolates between source frames and requires all frames to have the same topology (an error names the offending frame). Integer, boolean and string attributes are not interpolated but taken from the nearer frame. Source frames outside the sequence are clamped to the ends, or wrapped when Loop is on.

An identity mapping is exactly the identity: with channel `0:0 n-1:n-1` (or speed 1 and start 0) every output frame is bit-identical to the input frame, with no multiply-add.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence to retime. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | The retimed sequence. |
| `frames` | INT | Number of frames in the new sequence. |
| `info` | STRING | Text summary: input and output frame count, range of source frames used, mode and interpolation. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Retime Method `mode` | menu | Speed | How output frames are mapped to source frames: constant speed, evenly stretched to a given length, or by a keyframed time-warp curve. Options: Speed (`speed`), Output Length (`length`), Time Warp Channel (`channel`). |
| Output Frames `frames` | int [0..65536] | 0 | Number of output frames. 0 means automatic: for Speed the source length divided by the absolute speed (rounded up), otherwise the source length. |
| Speed `speed` | float [-100.0..100.0] | 1 | Source frames advanced per output frame. Below 1 is slow motion, above 1 is faster, negative plays backwards. Used in Speed mode. *Hidden when mode ≠ speed.* |
| Start Frame `start` | float | 0 | Source frame at which output frame 0 starts. Used in Speed mode (and for a single-frame Output Length). Hidden in Time Warp Channel mode. *Hidden when mode = channel.* |
| Time Warp Keys `keys` | string | `0:0  23:23` | Time-warp keys as `output_frame:source_frame`, for example `0:0  6:12  14:12  24:23` (same key syntax as Channel (PCG)). Only used in Time Warp Channel mode. *Hidden when mode ≠ channel.* |
| Key Interpolation `channel_interp` | menu | Linear | Default interpolation for keys of the time-warp curve that do not name their own. Linear is the default. Only used in Time Warp Channel mode. Options: Constant (`constant`), Linear (`linear`), Ease (`ease`), Ease In (`easein`), Ease Out (`easeout`), Cubic (`cubic`), Quintic (`quintic`). *Hidden when mode ≠ channel.* |
| Extrapolation `extrapolate` | menu | Hold | Behaviour of the time-warp curve past its first and last key. Only used in Time Warp Channel mode. Options: Hold (`hold`), Linear (`linear`), Cycle (`cycle`), Cycle with Offset (`cycleoffset`), Mirror (`mirror`). *Hidden when mode ≠ channel.* |
| Interpolation `interp` | menu | Integer Frames (Hold) | How fractional source frames are resolved. Hold takes the nearest integer frame and works with changing topology. Blend interpolates positions and other float attributes and needs identical topology in every frame. Options: Integer Frames (Hold) (`hold`), Blend Subframes (`blend`). |
| Cycle Source `loop` | toggle | off | Wrap source frame numbers outside the sequence around instead of clamping them to the first and last frame. |

**Compared with Houdini**

Based on the Retime SOP; the time-warp channel mode takes the place of animating the retime with a curve.

---

### Select Best (PCG)

<a id="pcg-selectbest"></a>

`PCG_SelectBest` · category `PCG/loop`

Scores every geometry in a sequence with an expression and outputs the best one, the top K and a ranked report.

Closes the loop for automatic variant selection: run many variants (for example a For-Each over N seeds), collect them as a geometry sequence, and let the node choose.

The score is an expression evaluated for each geometry. It can use every metric from Geo Metrics (`prims`, `closed`, `flipped_edges`, `uv_overlap`, `genus` ...), `i` and `n` (index and count) and the geometry-reading functions of Wrangle / Switch (`detail("score")`, `npoints()`, `prim("area", 0, 0)`).

Aesthetic scores (CLIP, aesthetic predictors, human preference) are image-side and not computed here. Write them in the loop as a detail attribute on the geometry (Attribute Create, detail class), then weight them with structural criteria in one expression, e.g. `detail("score") * 2 - nonmanifold_edges * 0.1 - degenerate_prims`. Carrying the score on the geometry keeps score and geometry together; separate parallel lists drift out of step.

Ties are broken by taking the lower index, so the same input always selects the same variant. `report` is a JSON list sorted by rank with the score and the metrics named in Report Metrics.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence of variants to score. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `best` | GEOMETRY | The geometry with the best score. |
| `top_k` | GEOSEQUENCE | The best K geometries as a sequence, in rank order. |
| `index` | INT | Index of the best geometry in the input sequence. |
| `score` | FLOAT | The best geometry's score. |
| `report` | STRING | JSON list in rank order with `rank`, `index`, `score` and the requested metrics for each geometry. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Score Expression `score` | string | *(see panel)* | Expression giving a number for each geometry. Can use all metrics, `i`, `n`, the Wrangle function library and geometry-reading functions such as `detail()`. |
| Select `mode` | menu | Highest Score | Whether the highest or the lowest score wins. Options: Highest Score (`max`), Lowest Score (`min`). |
| Keep Top `top_k` | int [1..4096] | 1 | How many of the best geometries to return in `top_k`. Capped at the sequence length. |
| Compute Quality Metrics `compute_quality` | toggle | on | Compute triangle quality metrics (`tri_quality_min`, `tri_quality_mean`). |
| Compute UV Metrics `compute_uv` | toggle | off | Compute UV metrics (`uv_area`, `uv_coverage`, `uv_overlap`, ...), counted on a texel grid. Off by default because it is slower. |
| UV Attribute `uv_attrib` | string | `uv` | Vertex attribute holding UVs. Only used when Compute UV is on. *Hidden when compute_uv is off.* |
| UV Raster Resolution `uv_res` | int [8..2048] | 128 | Grid resolution for UV coverage and overlap; precision is 1 / resolution. Only used when Compute UV is on. *Hidden when compute_uv is off.* |
| Report Metrics `report_metrics` | string | `prims points closed flipped_edges` | Space-separated metric names listed for each geometry in the report, in addition to rank and score. |

**Tips**

- Make a hard gate by multiplying the score by a metric such as `closed`.

---

### Time Blend (PCG)

<a id="pcg-timeblend"></a>

`PCG_TimeBlend` · category `PCG/loop` · Houdini: Sequence Blend (SOP)

Extracts one geometry at a fractional frame of a sequence by interpolating between the two neighbouring frames.

The counterpart of Houdini's Time Blend: samples a sequence at a possibly fractional frame. Typical uses are rendering a 24 fps sequence at 48 fps, and slow motion, where `frame` is driven by a Channel whose curve advances slower than one frame per frame.

**Blend Subframes** requires the whole sequence to have the same topology (point i is the same point in every frame) and raises an error naming the frame that differs. Sequences whose topology changes, such as fracturing or growth, must use **Integer Frames (Hold)**, which takes the nearest integer frame without interpolating. Integer, boolean and string attributes (`id`, `class`, `name`) are never interpolated and come from the nearer frame, as do groups; they therefore switch when the position passes halfway between two frames.

Outside the sequence the frame is clamped to the first or last frame, or wrapped when Loop is on.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence to sample. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The geometry at the requested frame. |
| `frames` | INT | Number of frames in the sequence. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Frame `frame` | float | 0 | Frame to sample, counted from 0 in the sequence. Fractional values interpolate. |
| Interpolation `interp` | menu | Integer Frames (Hold) | Hold takes the nearest integer frame. Blend linearly interpolates float attributes between the two frames and needs identical topology. Options: Integer Frames (Hold) (`hold`), Blend Subframes (`blend`). |
| Cycle Source `loop` | toggle | off | Wrap out-of-range frames around instead of clamping to the first and last frame. |

**Compared with Houdini**

Corresponds to Time Blend. Houdini also requires matching topology but reports a mismatch less clearly; here the error names the offending frame.

---

### Trail (PCG)

<a id="pcg-trail"></a>

`PCG_Trail` · category `PCG/loop` · Houdini: Trail (SOP)

Builds a trail from the previous frames of a geometry sequence, as stacked copies, polylines, a swept mesh or a velocity attribute.

Takes the frame at `index` as the current frame and looks back `length` frames, stepping `increment` frames at a time. Frame numbers outside the sequence are clamped to the ends (or wrapped with Loop), not dropped, so the trail has constant length at the start of the sequence.

Modes: **Preserve Original** merges every frame of the trail unchanged, for ghosting or motion-blur reference, and adds a point attribute `trailframe` (0 is the current frame, -1 the previous one, ...) to fade by. **Connect as Polygons** joins the positions of each point over the trail into one open polyline, with a point attribute `trailu` from 0 (oldest) to 1 (current). **Connect as Mesh** sweeps every primitive edge between consecutive trail frames into a quad (a curve becomes a ribbon, an outline becomes a tube wall); an edge shared by two faces is swept once, and geometry with no edges, such as a point cloud, falls back to the polylines. It also writes `trailu`. **Compute Velocity** outputs the current frame with a velocity attribute in units per frame: a backward difference from the previous frame (spaced `increment` apart), or a forward difference on the first frame of the sequence.

The Connect modes require the frames used to have the same topology; Compute Velocity requires the two frames compared to match.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence to build the trail from. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | The trail geometry. |
| `frames` | INT | Number of frames in the sequence. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Current Frame `index` | int | 0 | Frame of the sequence treated as the current frame, counted from 0. |
| Result Type `mode` | menu | Preserve Original | Preserve Original stacks the frames as they are, Connect as Polygons makes one polyline per point, Compute Velocity adds a velocity attribute to the current frame, Connect as Mesh sweeps edges into quads. Options: Preserve Original (`preserve`), Connect as Polygons (`connect`), Compute Velocity (`velocity`), Connect as Mesh (`connect_mesh`). |
| Trail Length `length` | int [0..4096] | 4 | Number of frames to look back. 0 gives only the current frame for Preserve and Connect modes. |
| Trail Increment `increment` | int [1..4096] | 1 | Step between sampled frames. A larger step gives a sparser trail that reads better for fast motion. In Compute Velocity it is also the frame distance of the difference. |
| Cycle Source `loop` | toggle | off | Wrap out-of-range frame numbers around instead of clamping to the first frame. |
| Velocity Attribute `velocity_attrib` | string | `v` | Name of the point attribute written in Compute Velocity mode. *Hidden when mode ≠ velocity.* |

**Compared with Houdini**

Corresponds to Trail. Houdini's Connect as Mesh on point clouds is the same as Connect as Polygons here; on geometry with edges, Connect as Mesh sweeps edges into quads.

---
