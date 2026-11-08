# Render & View

Preview images, 3D viewport, cameras and render passes.

11 nodes.

[Back to the reference index](README.md)

## Contents

- [Camera (PCG)](#pcg-camera) — Builds a single camera that Render Sequence, Texture Render, Motion Vectors and UV Backproject can all share.
- [Camera from Points (PCG)](#pcg-camerafrompoints) — Turns points, taken in point-number order, into a sequence of cameras.
- [Camera Path (PCG)](#pcg-camerapath) — Generates a sequence of cameras along an orbit or an interpolated fly-through.
- [Camera Pick (PCG)](#pcg-camerapick) — Picks one camera out of a camera sequence.
- [Camera To Points (PCG)](#pcg-cameratopoints) — Converts cameras into points (one per camera) plus optional path and frustum wireframes.
- [Motion Vectors (PCG)](#pcg-motionvectors) — Computes exact screen-space motion vectors between two frames from geometry and cameras.
- [Render Sequence (PCG)](#pcg-rendersequence) — Renders a geometry through every camera of a camera sequence into a sequence of images.
- [Sequence Motion (PCG)](#pcg-sequencemotion) — Computes a sequence of exact motion vector images from a geometry sequence and cameras.
- [Texture Render (PCG)](#pcg-texturerender) — Renders a UV texture onto the geometry through a camera.
- [UV Backproject (PCG)](#pcg-uvbackproject) — Projects a screen-space image back into UV space, weighted by visibility and facing, into an accumulator.
- [UV Resolve (PCG)](#pcg-uvresolve) — Turns a back-projection accumulator into a finished texture: divide by weight, dilate, fill holes.

## Nodes

### Camera (PCG)

<a id="pcg-camera"></a>

`PCG_Camera` · category `PCG/render` · Houdini: Camera (SOP)

Builds a single camera that Render Sequence, Texture Render, Motion Vectors and UV Backproject can all share.

The camera is a standalone node so that the view used to render an image and the view used to project it back into UV space are literally the same wire. Entering the same parameters twice in two nodes invites a mismatch, and the result is a smoothly misaligned texture that looks like the diffusion model drew it crooked and is very hard to trace back to the camera.

Three placement modes: `frame` places the camera on an orbit around the bounding sphere of the connected geometry and picks the distance (perspective) or the orthographic size automatically; `orbit` uses the same elevation / azimuth / distance parametrisation around an explicit target; `look_at` uses an explicit eye position, target and up vector. For multiple views use several Camera nodes, or one Camera with different `azim` values, each feeding its own render branch.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` *(optional)* | GEOMETRY | Geometry to frame. Required for the Frame Geometry mode; in the other modes it is optional and only supplies the bounding-sphere radius stored on the camera. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `cam` | PCGCAM | The camera, to be wired to render, projection and motion nodes. |
| `info` | STRING | One-line summary: projection, resolution, eye, target, distance and bounding radius. |

**Parameters**

*View*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Projection `projection` | menu | Perspective | Perspective or orthographic projection. Options: Perspective (`perspective`), Orthographic (`orthographic`). |
| Resolution `resolution_x` `resolution_y` | int [8..16384] | 512, 512 | Image width and height in pixels of whatever is rendered through this camera. Back-projection nodes must use the same resolution as the image they are given. |
| Field of View `fov` | float [1.0..179.0] | 45 | Vertical field of view in degrees (perspective only). The horizontal angle follows from the aspect ratio. *Hidden when projection ≠ perspective.* |
| Ortho Width `ortho_size` | float [0.0001..] | 2 | World-space height of the view (orthographic only); the width follows from the aspect ratio. Ignored in Frame Geometry mode, where it is derived from the bounding sphere. *Hidden when projection ≠ orthographic } { mode = frame.* |
| Near Clipping `near` | float [1e-06..] | 0.01 | Near clipping distance. |
| Far Clipping `far` | float [0.0..] | 0 | Far clipping distance. 0 disables far clipping. |

*Transform*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Placement `mode` | menu | Frame Geometry | Frame Geometry orbits the bounding-sphere center of the input geometry at an automatically computed distance. Orbit uses Target, Elevation, Azimuth and Distance as given. Look At uses Eye, Target and Up and ignores the orbit angles. Options: Frame Geometry (`frame`), Orbit (`orbit`), Look At (`look_at`). |
| Target `target_x` `target_y` `target_z` | float | 0, 0, 0 | Point the camera looks at. In Frame Geometry mode with geometry connected, the bounding-sphere center replaces it. |
| Elevation `elev` | float [-89.9..89.9] | 25 | Elevation angle above the horizontal plane, in degrees (orbit and frame modes). *Hidden when mode = look_at.* |
| Azimuth `azim` | float [-3600.0..3600.0] | 35 | Azimuth angle around the vertical axis, in degrees (orbit and frame modes). *Hidden when mode = look_at.* |
| Distance `distance` | float [0.0001..] | 5 | Distance from the target to the eye (orbit mode). Frame Geometry computes its own distance and ignores this value. *Hidden when mode ≠ orbit.* |
| Frame Margin `margin` | float [0.5..10.0] | 1.15 | Frame Geometry only. Multiplier on the fitting distance (or orthographic size); values above 1 leave empty border around the object. *Hidden when mode ≠ frame.* |
| Eye `eye_x` `eye_y` `eye_z` | float | 0, 0, 5 | Camera position in world space (Look At mode). *Hidden when mode ≠ look_at.* |
| Up Vector `up_x` `up_y` `up_z` | float [-1.0..1.0] | 0, 1, 0 | Up direction used to roll the camera (Look At mode). If it is parallel to the view direction a substitute up vector is chosen instead of producing NaNs. |

**Tips**

- Use one Camera node per view and wire the same node to both the render and the back-projection of that view.

---

### Camera from Points (PCG)

<a id="pcg-camerafrompoints"></a>

`PCG_CameraFromPoints` · category `PCG/render` · Houdini: Camera from Points (SOP)

Turns points, taken in point-number order, into a sequence of cameras.

The curve-driven counterpart of Camera Path. Each point (or, with `frames` > 0, each sample along the polyline through the points) becomes one camera.

Orientation modes: `auto` tries the `orient` attribute, then `N`, then a `target` attribute, then the path tangent, in that order; `orient` uses the orient quaternion; `normal` looks along `N` with the Up vector; `target` looks at the `target` point attribute or the Target parameter; `path` follows the path tangent. With Look Ahead above 0 the path mode looks at the point that far ahead along the path, which steadies the shot.

With Frames = 0 there is one camera per point. With Frames > 0 the path is sampled at equal arc-length steps: `orient` is interpolated with slerp, other quantities linearly. Loop joins the end back to the start without repeating the first frame at the end. With Use Point Attributes on, the point attributes `fov`, `ortho_size`, `near`, `far`, `radius`, `resx`, `resy`, `projection` and `distance` override the matching parameters, so Camera To Points followed by Camera from Points round-trips exactly.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Points that define the camera positions (and optionally orientations and settings). |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `cams` | PCGCAMSEQ | Camera sequence, one camera per frame. |
| `frames` | INT | Number of cameras produced. |
| `report` | STRING | Text report of what was built. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Point Group `group` | string | *(empty)* | Point group pattern; only these points are used. |
| Frames `frames` | int [0..16384] | 0 | 0 creates one camera per point. A value above 0 samples that many cameras evenly by arc length along the path. |
| Closed Path `loop` | toggle | off | Closes the path from the last point back to the first; the final frame does not repeat the first. |
| Orientation `orientation` | menu | Automatic | How each camera is aimed. Automatic tries orient, then N, then a target attribute, then the path tangent. Options: Automatic (`auto`), orient Attribute (`orient`), N + up (`normal`), Look at Target (`target`), Along Path (`path`). |
| Look Ahead `look_ahead` | float [0.0..] | 0 | Along Path only. Distance ahead on the path to look at; 0 looks along the local tangent. *Hidden when orientation ≠ path orientation ≠ auto.* |
| Target `target_x` `target_y` `target_z` | float | 0, 0, 0 | World position to look at in Look at Target mode. A `target` point attribute takes precedence when present. *Hidden when orientation ≠ target orientation ≠ auto.* |
| Up Vector `up_x` `up_y` `up_z` | float | 0, 1, 0 | Up direction used to roll the cameras in the N + up, target and path modes. *Hidden when orientation = orient.* |
| Focus Distance `focus_distance` | float [0.0001..] | 5 | Distance from the eye to the look-at point that is stored on the camera in the orient, N + up and path-tangent modes, where no explicit target exists. Overridden by a `distance` point attribute when Use Point Attributes is on. *Hidden when orientation = target.* |
| Projection `projection` | menu | Perspective | Perspective or orthographic projection. Options: Perspective (`perspective`), Orthographic (`orthographic`). |
| Resolution `resolution_x` `resolution_y` | int [8..16384] | 512, 512 | Image width and height in pixels. |
| Field of View `fov` | float [1.0..179.0] | 45 | Vertical field of view in degrees (perspective). *Hidden when projection ≠ perspective use_point_attributes is off.* |
| Ortho Width `ortho_size` | float [0.0001..] | 2 | World-space height of the view (orthographic). *Hidden when projection ≠ orthographic use_point_attributes is off.* |
| Near Clipping `near` | float [1e-06..] | 0.01 | Near clipping distance. |
| Far Clipping `far` | float [0.0..] | 0 | Far clipping distance. 0 disables far clipping. |
| Use Point Attributes `use_point_attributes` | toggle | on | Lets point attributes (`fov`, `ortho_size`, `near`, `far`, `radius`, `resx`, `resy`, `projection`, `distance`) override the parameters on this node. |

**Compared with Houdini**

Matches Houdini's Camera from Points in intent; the camera sequence is a ComfyUI-side list rather than camera objects.

---

### Camera Path (PCG)

<a id="pcg-camerapath"></a>

`PCG_CameraPath` · category `PCG/render`

Generates a sequence of cameras along an orbit or an interpolated fly-through.

The entry point of the video side of the plugin. Orbit mode sweeps elevation, azimuth and distance from their start to their end values around a target. Interpolate mode moves the eye linearly from Eye to End Eye while looking at a fixed Target. The output is a camera list to be wired to Render Sequence; wire it to Camera Pick to use a single frame.

With Loop on, the last frame does not repeat the first: sweeping azimuth 0 to 360 over 24 frames ends at 345 degrees, not 360, so a looping playback has no duplicated frame (a one-frame stutter that is easy to see and hard to diagnose). Turn Loop off for a one-shot move where the last frame should land exactly on the end value.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` *(optional)* | GEOMETRY | Geometry to frame. Optional; without it Frame Geometry treats the scene as a unit sphere. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `cams` | PCGCAMSEQ | Camera sequence. |
| `frames` | INT | Number of cameras. |
| `info` | STRING | One-line summary: frame count, mode, resolution and loop behaviour. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Frames `frames` | int [1..16384] | 24 | Number of cameras to generate. |
| Loop `loop` | toggle | on | On: the last frame stops one step short of the end value so a looping animation has no repeated frame. Off: closed interval, the last frame lands exactly on the end value. |
| Path `mode` | menu | Orbit | Orbit sweeps the Orbit parameters around a target. Interpolate (Look At) moves the eye from Eye to End Eye while looking at a fixed Target. Options: Orbit (`orbit`), Interpolate (Look At) (`interpolate`). |
| Projection `projection` | menu | Perspective | Perspective or orthographic projection. Options: Perspective (`perspective`), Orthographic (`orthographic`). |
| Resolution `resolution_x` `resolution_y` | int [8..16384] | 512, 512 | Image width and height in pixels. |
| Field of View `fov` | float [1.0..179.0] | 45 | Vertical field of view in degrees. *Hidden when projection = orthographic.* |
| Ortho Height `ortho_size` | float [0.0001..] | 2 | World-space height of the view (orthographic); the width follows from the aspect ratio. *Hidden when projection = perspective.* *Disabled when mode = orbit frame_geometry is on.* |
| Target `target_x` `target_y` `target_z` | float | 0, 0, 0 | Orbit mode: center of the orbit (replaced by the bounding-box center when Frame Geometry is on and geometry is connected). Interpolate mode: the point being looked at. |

*Orbit*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Frame Geometry `frame_geometry` | toggle | on | Orbit mode. Chooses the distance (perspective) or orthographic size automatically from the bounding sphere of the geometry; without geometry a unit sphere is assumed. *Hidden when mode ≠ orbit.* |
| Frame Margin `margin` | float [0.5..10.0] | 1.15 | Orbit mode with Frame Geometry. Multiplier on the fitting distance; values above 1 leave a border around the object. *Hidden when mode ≠ orbit.* *Disabled when frame_geometry is off.* |
| Elevation `elev` `elev_end` | float [-89.9..89.9] | 25, 25 | Start and end elevation in degrees (orbit). *Hidden when mode ≠ orbit.* |
| Azimuth `azim` `azim_end` | float [-3600.0..3600.0] | 0, 360 | Start and end azimuth in degrees (orbit). The default 0 to 360 is a full turn. *Hidden when mode ≠ orbit.* |
| Distance `distance` `distance_end` | float [0.0001..] | 5, 5 | Start and end distance from the target (orbit). Ignored when Frame Geometry is on. *Hidden when mode ≠ orbit.* *Disabled when frame_geometry is on.* |

*Interpolate*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Eye Start `eye_x` `eye_y` `eye_z` | float | 0, 0, 5 | Start position of the eye (Interpolate mode). *Hidden when mode ≠ interpolate.* |
| Eye End `eye_end_x` `eye_end_y` `eye_end_z` | float | 0, 0, 5 | End position of the eye (Interpolate mode). *Hidden when mode ≠ interpolate.* |

*Clipping*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Near Clipping `near` | float [1e-06..] | 0.01 | Near clipping distance. |
| Far Clipping `far` | float [0.0..] | 0 | Far clipping distance. 0 disables far clipping. |

**Tips**

- For a seamless turntable keep Loop on and azimuth 0 to 360.

---

### Camera Pick (PCG)

<a id="pcg-camerapick"></a>

`PCG_CameraPick` · category `PCG/render`

Picks one camera out of a camera sequence.

The index wraps around the number of cameras instead of raising an error, so dragging the index while previewing never breaks the chain.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `cams` | PCGCAMSEQ | Camera sequence. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `cam` | PCGCAM | The selected camera. |
| `frames` | INT | Number of cameras in the input sequence. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Index `index` | int [0..] | 0 | Zero-based index of the camera. Out-of-range values wrap around by the number of cameras. |

---

### Camera To Points (PCG)

<a id="pcg-cameratopoints"></a>

`PCG_CameraToPoints` · category `PCG/render` · Houdini: Camera To Points (SOP)

Converts cameras into points (one per camera) plus optional path and frustum wireframes.

Each camera in the sequence, and/or the single camera input, becomes one point whose point number equals the frame number. Point attributes: `P`, `orient` (+Z is the view direction and +Y is up, the same convention as N, Orient Along Curve and Copy to Points), `N`, `up`, `target`, `distance`, `fov`, `ortho_size`, `near`, `far`, `radius`, `resx`, `resy`, `projection` and `frame`.

The `frustums` output is a line wireframe of each view frustum; its far rectangle matches the image corners exactly. Moving or rotating the points and feeding them to Camera from Points is a way to place cameras directly in the viewport.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `cams` *(optional)* | PCGCAMSEQ | Camera sequence. Optional if `cam` is connected. |
| `cam` *(optional)* | PCGCAM | A single camera, appended after the sequence. At least one of `cams` and `cam` is required. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | One point per camera, plus a connecting polyline when Path is on. |
| `frustums` | GEOMETRY | Frustum wireframes, one per camera. |
| `report` | STRING | Text report. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Create Path `path` | toggle | on | Also outputs a polyline that connects the camera points in frame order. |
| Frustum Depth `frustum_depth` | float [0.0..] | 0.5 | Depth of the frustum wireframes in world units. 0 produces no frustums. |

---

### Motion Vectors (PCG)

<a id="pcg-motionvectors"></a>

`PCG_MotionVectors` · category `PCG/render`

Computes exact screen-space motion vectors between two frames from geometry and cameras.

Optical flow has to estimate where a pixel was in the previous frame, and neural flow fails on weak texture, large motion, reflections and transparency without warning. Here the position is known: the same triangle and the same barycentric weights are projected once with the frame-t vertices and once with the frame-(t+1) vertices, and the two screen positions are subtracted. There is no search and no smoothing.

Forward and backward vectors live on different meshes and are rasterized separately. `motion` is defined on the frame-t image ("where do I go next"); `motion_bwd` on the frame-(t+1) image ("where did I come from"). Warping needs the backward one, and negating the forward map is only correct when nothing moves.

Output layers: `motion`, `motion_bwd`, `mask` (coverage at t), `mask_next` (coverage at t+1) and `disocclusion`, the area of frame t+1 that was not visible in frame t and must be repainted. Disocclusion is decided by triangle id, with a depth test (Depth Bias) and a silhouette guard as safety layers.

If only the camera moves, connect only `cam_next`; if only the object moves, connect only `geo_next`. The two frames must have identical topology so that barycentric weights correspond, and both cameras must have the same resolution.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry at frame t. |
| `cam` | PCGCAM | Camera at frame t. |
| `geo_next` *(optional)* | GEOMETRY | Geometry at frame t+1. Must have the same topology as `geo`. Omit if the geometry is static. |
| `cam_next` *(optional)* | PCGCAM | Camera at frame t+1. Omit if the camera is static. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `cop` | COPIMAGE | Image with the layers `motion`, `motion_bwd`, `mask`, `mask_next` and `disocclusion`. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Group `group` | string | *(empty)* | Primitive group pattern; only these primitives are rendered. |
| Units `units` | menu | Pixels | Unit of the vectors. Pixels: screen pixels. Normalized: the whole image width / height equals 2 (as NDC). UV: the whole image equals 1. Options: Pixels (`pixels`), Normalized (NDC) (`normalized`), UV (0-1) (`uv`). |
| Depth Bias `depth_bias` | float [0.0..10.0] | 0.02 | Depth tolerance of the disocclusion test, as a fraction of the bounding-sphere radius (not world units). |
| Silhouette Guard `silhouette_guard` | int [0..64] | 1 | Number of pixels the silhouette is eroded by; pixels on the edge count as needing repaint. |
| Device `device` | menu | NumPy | Backend that holds the output image. Auto uses CUDA when available and the image is large enough (at least 256x256 pixels); Exact is float64 numpy, bit-identical to the geometry side but slowest. Options: NumPy (`numpy`), Auto (`auto`), CPU (`cpu`), CUDA (`cuda`), Exact (float64) (`exact`). |

---

### Render Sequence (PCG)

<a id="pcg-rendersequence"></a>

`PCG_RenderSequence` · category `PCG/render`

Renders a geometry through every camera of a camera sequence into a sequence of images.

The B dimension of an IMAGE is the video; this node fills it. Each camera produces one image with the selected passes (layers `mask`, `depth`, `N`, `P`, `uv`, `id`, `facing`, and `C` for shade). Frames are rendered serially, since geometry is a Python object and cannot be batched as a tensor. If no pass is ticked, only Mask is rendered.

With Motion on, every frame also gets `motion`, `motion_bwd` and `disocclusion` layers describing the step from this frame to the next one. This only captures camera motion, because the geometry is a single static object; use Sequence Motion for moving geometry. The last frame has no successor: with Loop on it is connected back to frame 0, otherwise it gets zero motion and a fully set disocclusion, so that undefined motion is visible downstream instead of being faked by repeating the previous frame.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry to render. The same geometry is used for every frame. |
| `cams` | PCGCAMSEQ | Camera sequence, one image per camera. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `seq` | COPSEQUENCE | Sequence of images. |
| `frames` | INT | Number of frames. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Group `group` | string | *(empty)* | Primitive group pattern; only these primitives are rendered. |
| Depth `pass_depth` | toggle | on | Depth along the view axis in camera space (layer `depth`), unclamped. |
| Mask `pass_mask` | toggle | on | Coverage mask (layer `mask`). |
| Normal `pass_normal` | toggle | on | Normals (layer `N`), in the space given by Normal Space. |
| Shaded Preview `pass_shade` | toggle | off | Simple gray shading from a light near the camera, for a quick look at the shape (layer `C`). Not a final render. |

*More Passes*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Position (P) `pass_position` | toggle | off | World position (layer `P`). |
| UV `pass_uv` | toggle | off | Interpolated UV (layer `uv`), read from the attribute named in UV Attribute. |
| Piece ID `pass_id` | toggle | off | Integer primitive id (layer `id`, -1 where empty) from the attribute in ID Attribute; string attributes are numbered in order of appearance. |
| Facing Ratio `pass_facing` | toggle | off | Absolute cosine between the normal and the view direction (layer `facing`), useful for rim lights and silhouette masks. |

*Motion Vectors*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Motion Vectors `motion` | toggle | off | Adds `motion`, `motion_bwd` and `disocclusion` layers from each frame to the next (camera motion only). |
| Units `motion_units` | menu | Pixels | Unit of the motion vectors: pixels, normalized (whole image = 2) or UV (whole image = 1). Options: Pixels (`pixels`), Normalized (NDC) (`normalized`), UV (0-1) (`uv`). |
| Loop `loop` | toggle | on | Connects the motion of the last frame back to frame 0. Off: the last frame gets zero motion and full disocclusion. |

*Attributes*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Normal Space `normal_space` | menu | Camera | Camera: +Z points toward the viewer, so a face looking at the camera is (0,0,1), the usual normal map convention. World: world-space normals. Options: Camera (`camera`), World (`world`). *Hidden when pass_normal is off pass_shade is off.* |
| Normal Source `normal_source` | menu | Auto (Point N or Face) | Point `N` or face normals. Auto uses point normals if the geometry has them and face normals otherwise; Point computes point normals if missing; Face always uses face normals. Options: Auto (Point N or Face) (`auto`), Point (`point`), Face (`face`). *Hidden when pass_normal is off.* |
| ID Attribute `id_attribute` | string | `name` | Primitive attribute used by the id pass (needs to exist, e.g. from Voronoi Fracture, Convex Decompose or Connectivity). *Hidden when pass_id is off.* |
| UV Attribute `uv_attribute` | string | `uv` | UV attribute (vertex or point) used by the uv pass. *Hidden when pass_uv is off.* |
| Backface Culling `cull` | menu | None | Back-face culling: drop back-facing or front-facing triangles. Options: None (`none`), Back Faces (`back`), Front Faces (`front`). |

| Parameter | Type | Default | Description |
|---|---|---|---|
| Device `device` | menu | NumPy | Backend that holds the output image. Auto uses CUDA when available and the image is large enough (at least 256x256 pixels); Exact is float64 numpy, bit-identical to the geometry side but slowest. Options: NumPy (`numpy`), Auto (`auto`), CPU (`cpu`), CUDA (`cuda`), Exact (float64) (`exact`). |

---

### Sequence Motion (PCG)

<a id="pcg-sequencemotion"></a>

`PCG_SequenceMotion` · category `PCG/render`

Computes a sequence of exact motion vector images from a geometry sequence and cameras.

The moving-geometry counterpart of the motion option in Render Sequence, which can only express camera motion. It takes the geometry sequence produced by For-Each Frame End, so deformation, growth and fracture all get exact vectors. For every frame, motion between that frame and the next is computed as in Motion Vectors (layers `motion`, `motion_bwd`, `mask`, `mask_next`, `disocclusion`).

There must be as many cameras as geometries, or exactly one camera for a fixed viewpoint. A mismatch by one frame shifts the vectors by a whole frame and produces ghosting when warping, so it raises an error. The last frame has no successor: with Loop on it is connected to frame 0, otherwise it gets zero motion and a fully set disocclusion. Consecutive frames must share one topology.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geoseq` | GEOSEQUENCE | Geometry sequence, one geometry per frame. |
| `cams` | PCGCAMSEQ | Camera sequence with the same length as the geometry sequence, or a single camera. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `seq` | COPSEQUENCE | Sequence of motion images. |
| `frames` | INT | Number of frames. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Group `group` | string | *(empty)* | Primitive group pattern; only these primitives are rendered. |
| Units `units` | menu | Pixels | Unit of the vectors: pixels, normalized (whole image = 2) or UV (whole image = 1). Options: Pixels (`pixels`), Normalized (NDC) (`normalized`), UV (0-1) (`uv`). |
| Loop `loop` | toggle | on | Connects the last frame to frame 0. Off: the last frame gets zero motion and full disocclusion. |
| Depth Bias `depth_bias` | float [0.0..10.0] | 0.02 | Depth tolerance of the disocclusion test, as a fraction of the bounding-sphere radius. |
| Silhouette Guard `silhouette_guard` | int [0..64] | 1 | Number of pixels the silhouette is eroded by; pixels on the edge count as needing repaint. |
| Device `device` | menu | NumPy | Backend that holds the output image. Auto uses CUDA when available and the image is large enough (at least 256x256 pixels); Exact is float64 numpy, bit-identical to the geometry side but slowest. Options: NumPy (`numpy`), Auto (`auto`), CPU (`cpu`), CUDA (`cuda`), Exact (float64) (`exact`). |

---

### Texture Render (PCG)

<a id="pcg-texturerender"></a>

`PCG_TextureRender` · category `PCG/render` · Houdini: UV Quick Shade (SOP)

Renders a UV texture onto the geometry through a camera.

The forward half of the texture projection loop. It lets you check a back-projected texture without leaving ComfyUI, and it is the honest test of back-projection: a known texture rendered and back-projected should come back unchanged. The two directions use different code paths (screen rasterization plus UV sampling here, UV rasterization plus screen sampling there), so a round trip checks real behaviour rather than one bug cancelling itself.

The output has the color in layer `C` and a coverage `mask`.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry with a vertex or point UV attribute. |
| `cam` | PCGCAM | Camera to render through. |
| `texture` | COPIMAGE | Image holding the texture in UV space. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `cop` | COPIMAGE | Rendered image with layers `C` and `mask`. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Group `group` | string | *(empty)* | Primitive group pattern; only these primitives are rendered. |
| Texture Layer `layer` | string | `C` | Layer of the texture image to sample. |
| UV Attribute `uv_attrib` | string | `uv` | Name of the UV attribute on the geometry. |
| Filter `filter` | menu | Bilinear | Texture sampling filter: bilinear interpolation or nearest texel. Options: Bilinear (`bilinear`), Closest (`closest`). |
| Border `border` | menu | Clamp | Behaviour outside 0..1: clamp to the edge, wrap (repeat), or black. Options: Clamp (`clamp`), Wrap (`wrap`), Black (`black`). |
| Background `background` | float | 0 | Value written to pixels that are not covered by geometry. |
| Device `device` | menu | NumPy | Backend that holds the output image. Auto uses CUDA when available and the image is large enough (at least 256x256 pixels); Exact is float64 numpy, bit-identical to the geometry side but slowest. Options: NumPy (`numpy`), Auto (`auto`), CPU (`cpu`), CUDA (`cuda`), Exact (float64) (`exact`). |

**Compared with Houdini**

Corresponds to UV Quick Shade.

---

### UV Backproject (PCG)

<a id="pcg-uvbackproject"></a>

`PCG_UVBackproject` · category `PCG/render`

Projects a screen-space image back into UV space, weighted by visibility and facing, into an accumulator.

Until this step the chain is one-way: geometry, render pass, control image, diffusion model. The generated image is laid out in screen pixels, but an asset needs a texture laid out in UV. This node does that conversion.

**Accumulator.** The output is an accumulator (layers `Csum`, `Wsum` and `views`), not a texture. Connect it to the `accum` input of the next view's Backproject so each view adds its contribution on top of the previous ones, and finish with UV Resolve to get a texture. A single node that outputs textures directly could not know how much weight earlier views had at each texel and would have to overwrite in overlaps, producing a visible seam.

**Visibility.** UV rasterization knows which triangle each texel belongs to, and the screen rasterization knows which triangle is visible at each pixel; when they match the texel is visible without any depth comparison. Pure depth bias is a bad trade: too small gives self-occlusion speckles (the same disease as shadow acne), too large leaks through occluders. The default `triangle+depth` accepts a texel if its triangle matches or its depth is within the bias; triangle only is too strict.

**Silhouette guard.** Pixels on the silhouette are partially covered and blend in the background, and generated images are least reliable at object edges, so pixels within a number of pixels of the silhouette are discarded.

**Linear blending.** Averaging encoded values gives different results than averaging linear values, and the error shows up only in overlaps as a seam. So the image is decoded to linear before accumulation by default.

Texel weight is the facing term (N dot view direction) raised to Facing Power, zero at or below Facing Min, times a fade over the outer Border Fade fraction of the image, times 1 or 0 for visibility.

**Inputs**

| Input | Type | Description |
|---|---|---|
| `geo` | GEOMETRY | Geometry with UVs and normals. |
| `cam` | PCGCAM | The camera that rendered `cop`. It must be exactly the same camera (use one Camera node for both). |
| `cop` | COPIMAGE | The screen-space image to project, e.g. the diffusion output. |
| `accum` *(optional)* | COPIMAGE | Accumulator from a previous view, to add this view's contribution to. Optional for the first view. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `accum` | COPIMAGE | Accumulator with the layers `Csum`, `Wsum` and `views`. |
| `coverage` | FLOAT | Fraction of texels that have been seen by at least one view so far. |
| `info` | STRING | Coverage, maximum number of views per texel and texture resolution. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Group `group` | string | *(empty)* | Primitive group pattern; only these primitives take part. |
| Source Layer `layer` | string | `C` | Layer of the input image to project. |
| Texture Resolution `resolution_x` `resolution_y` | int [8..16384] | 1024, 1024 | Width and height of the UV-space accumulator in texels. Every node on one back-projection chain must use the same values. |
| Decode `decode` | menu | None | Conversion applied to the image before accumulating. Images from diffusion models are sRGB encoded, so use sRGB to Linear to blend linearly; None accumulates the values unchanged. Options: None (`none`), sRGB to Linear (`srgb_to_linear`), Linear to sRGB (`linear_to_srgb`). |

*Weighting*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Facing Power `facing_power` | float [0.0..16.0] | 2 | Exponent of the facing weight. Larger values favour views that look straight at the surface. |
| Facing Cutoff `facing_min` | float [0.0..1.0] | 0.2 | Texels whose N dot view value is at or below this get weight 0. |
| Border Fade `border_fade` | float [0.0..0.5] | 0.05 | Fraction of the image width at the outer border over which the weight fades linearly to 0. Edges are where diffusion output is least reliable. |

*Visibility*

| Parameter | Type | Default | Description |
|---|---|---|---|
| Visibility `visibility` | menu | Triangle ID or Depth | How occlusion is decided: triangle id or depth within bias, triangle id only, depth only, or no occlusion test. Options: Triangle ID or Depth (`triangle+depth`), Triangle ID (`triangle`), Depth (`depth`), None (`none`). |
| Depth Bias `depth_bias` | float [0.0..10.0] | 0.02 | Depth tolerance of the visibility test, as a fraction of the bounding-sphere radius (not world units). *Hidden when visibility = triangle } { visibility = none.* |
| Silhouette Guard `silhouette_guard` | int [0..64] | 1 | Number of pixels the silhouette is eroded by. Higher values trade single-view coverage for fewer edge artifacts; with several views the cost is small. |

*Advanced*

| Parameter | Type | Default | Description |
|---|---|---|---|
| View Weight `weight_scale` | float [0.0..10000.0] | 1 | Multiplier on this view's weights relative to other views in the accumulator. |
| Conservative Dilation `conservative` | float [0.0..4.0] | 0.5 | Number of pixels triangles are expanded by during UV rasterization, so texels whose center lies just outside a triangle are still filled. |
| Filter `filter` | menu | Bilinear | Sampling filter for the screen image: bilinear or closest. Options: Bilinear (`bilinear`), Closest (`closest`). |
| UV Attribute `uv_attrib` | string | `uv` | Name of the UV attribute on the geometry. |
| Normal Attribute `normal_attrib` | string | `N` | Name of the point normal attribute used for the facing weight. |

---

### UV Resolve (PCG)

<a id="pcg-uvresolve"></a>

`PCG_UVResolve` · category `PCG/render`

Turns a back-projection accumulator into a finished texture: divide by weight, dilate, fill holes.

Divides the summed color by the summed weight, writes a gutter around UV islands, and fills regions that no view saw.

Dilation and hole filling are different things. Dilation writes a few extra texels outside the UV islands; without it, bilinear sampling at island edges picks up background, especially in low mips. Hole filling covers texels that were never seen by any view (back sides, fully occluded areas, large gaps between islands) with push-pull: the weighted image is downsampled into a pyramid and upsampled again, keeping original values where weight exists and filling elsewhere from coarser levels. It costs O(n), fills arbitrarily large holes in one pass and is smooth, unlike iterative dilation, which needs as many rounds as the hole radius and leaves concentric rings.

Output layers: the texture in the chosen layer, `mask` (texels actually seen by a view; dilated and filled texels are not counted, so it shows where another view is needed) and `views` (number of views per texel, to find areas held up by a single view).

**Inputs**

| Input | Type | Description |
|---|---|---|
| `accum` | COPIMAGE | Accumulator from UV Backproject. |

**Outputs**

| Output | Type | Description |
|---|---|---|
| `texture` | COPIMAGE | The finished texture with layers `C`, `mask` and `views`. |
| `coverage` | FLOAT | Fraction of texels seen by at least one view. |

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| Output Layer `layer` | string | `C` | Name of the output color layer. |
| Encode `encode` | menu | None | Color conversion on output. Accumulation is linear, so choose sRGB when the result goes back to ComfyUI as an image. Linear applies the opposite (sRGB to linear) conversion. Options: None (`none`), Linear to sRGB (`srgb`), sRGB to Linear (`linear`). |
| Dilate (Gutter) `dilate` | int [0..256] | 4 | Number of texel rings written outside the UV islands (gutter). 0 disables it. |
| Fill Holes `fill_holes` | toggle | on | Fills texels that no view saw with push-pull. |
| Background `background` | float | 0.5 | Value used for unseen texels before dilation; also what remains there when Fill Holes is off. *Disabled when fill_holes is on.* |
| Device `device` | menu | NumPy | Backend that holds the output image. Auto uses CUDA when available and the image is large enough (at least 256x256 pixels); Exact is float64 numpy, bit-identical to the geometry side but slowest. Options: NumPy (`numpy`), Auto (`auto`), CPU (`cpu`), CUDA (`cuda`), Exact (float64) (`exact`). |

---
