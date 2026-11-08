"""
Timeline -- sequences, camera paths, **exact motion vectors**.

ComfyUI's IMAGE is (B,H,W,C), and that B dimension is video. Up to the previous batch every node in this plugin
was single-frame and the B dimension went completely unused. This file adds time.

    camera_path      one camera path -> a list of cameras
    render_sequence  a list of cameras -> a list of CopImages (computing per-frame motion vectors along the way)
    motion_vectors   **exact** screen-space displacement between two frames + disocclusion regions
    warp             warp one frame to another frame's position using motion vectors
    to_batch/from_batch   COP sequence <-> ComfyUI's (B,H,W,C)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Motion vectors are the one thing here that **nobody else can compute**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every temporal-consistency scheme on the video side -- optical-flow warp, token merge, FreeNoise -- needs to
know "where this pixel was last frame". The image side can only **estimate** it: RAFT / neural optical flow goes wrong in low texture, large displacement,
specular and transparent regions, and it gives no error when it is wrong.

Procedural generation knows where every vertex was last frame. So the displacement here is **analytic**: the same triangle,
the same barycentric weights, project the vertex positions of both frames once each, subtract. No search, no smoothing term, no
confidence -- the only error is floating-point error. The tests use "an orthographic camera with pure translation" as the criterion; measured 1e-13.

The only thing that really needs deciding is **disocclusion**. Places invisible in the previous frame
are necessarily wrong after warping and must be marked so downstream can repaint them. This uses the trick already validated by the
back-projection batch: compare triangle IDs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Forward and backward are images on two **different grids**, not one negated
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    motion       on the pixel grid of **frame t**, "where do I go next frame"
    motion_bwd   on the pixel grid of **frame t+1**, "where did I come from last frame"

warp needs the backward one: each output pixel fetches one value from the input image. Using the negated forward as backward is
a common mistake -- that negation is only right when displacement is zero; once objects move, even the sets of covered pixels differ
(the forward one has values where frame t has coverage, the backward one where frame t+1 does). So both are computed, each
rasterized once on its own grid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Units are **pixels**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Normalizing (dividing by resolution) looks more "general" but is a trap: when resolution changes the normalized values stay the same, but
the warped result changes, because x and y are not divided by the same number. Pixels are unambiguous; if you need normalization,
convert once at the exit (the `units` parameter), and state clearly whether it divides by W or H.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .cop.core import CopImage, DEFAULT_LAYER
from . import render as _rnd

PATHS = ("orbit", "interpolate")
UNITS = ("pixels", "normalized", "uv")
EDGES = ("clamp", "black", "wrap")
MOTION_LAYER = "motion"
MOTION_BWD_LAYER = "motion_bwd"
DISOCC_LAYER = "disocclusion"


# ═══════════════════════════════════════════════════════════════ camera path
def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * t


def camera_path(geo=None, frames=24, mode="orbit", projection="perspective",
                xres=512, yres=512, fov=45.0, ortho_size=2.0,
                elev=25.0, elev_end=None, azim=0.0, azim_end=360.0,
                distance=5.0, distance_end=None, margin=1.15,
                target=(0.0, 0.0, 0.0), target_end=None,
                eye=(0.0, 0.0, 5.0), eye_end=None,
                frame_geometry=True, near=0.01, far=0.0, loop=True):
    """
    One camera path -> `frames` cameras.

    With loop=True **the last frame does not repeat the first**: when azim sweeps from 0 to 360, frame N−1
    stops at 360x(N−1)/N, not 360. Otherwise the exported loop would contain a duplicated frame,
    showing up as a "hitch" at the loop point -- a one-frame hitch is visible to the eye but hard to pin down.

    With loop=False sampling is over the closed interval (frame N−1 lands exactly on the end), suitable for a one-shot dolly.
    """
    n = max(1, int(frames))
    if mode not in PATHS:
        raise ValueError(f"Path must be one of {PATHS}")
    den = n if (loop and n > 1) else max(n - 1, 1)
    out = []
    for i in range(n):
        t = i / den if n > 1 else 0.0
        if mode == "orbit":
            cam = _rnd.camera(
                geo, projection=projection, fov=fov, ortho_size=ortho_size,
                xres=xres, yres=yres, near=near, far=far, orbit=True,
                elev=_lerp(elev, elev if elev_end is None else elev_end, t),
                azim=_lerp(azim, azim_end, t),
                distance=_lerp(distance,
                               distance if distance_end is None
                               else distance_end, t),
                target=target, frame_geometry=frame_geometry, margin=margin)
        else:
            e0 = np.asarray(eye, np.float64)
            e1 = e0 if eye_end is None else np.asarray(eye_end, np.float64)
            t0 = np.asarray(target, np.float64)
            t1 = t0 if target_end is None else np.asarray(target_end,
                                                          np.float64)
            cam = _rnd.camera(
                geo, projection=projection, eye=e0 + (e1 - e0) * t,
                target=t0 + (t1 - t0) * t, fov=fov, ortho_size=ortho_size,
                xres=xres, yres=yres, near=near, far=far,
                frame_geometry=False, margin=margin)
        out.append(cam)
    return out


# ═══════════════════════════════════════════════════════════ motion vectors
def _check_pair(geo, geo_next):
    """Both frames must have **the same topology**, otherwise the barycentric weights correspond to nothing."""
    if geo_next is None:
        return geo
    if (geo_next.npoints != geo.npoints
            or geo_next.nprims != geo.nprims
            or len(geo_next.vertex_point) != len(geo.vertex_point)):
        raise ValueError(
            f"Both frames must have the same topology: frame t has {geo.npoints} points / {geo.nprims} prims, "
            f"frame t+1 has {geo_next.npoints} points / {geo_next.nprims} prims. "
            f"Motion vectors are computed from the same barycentric weights on the same triangle; once the topology changes there is"
            f" no correspondence -- deformation must be topology-preserving (Transform / Wrangle / "
            f"Attribute Blur), not a re-triangulated result.")
    return geo_next


def _screen_of(cam, geo_src, rast, P_other):
    """
    On pixels hit by rast, interpolate the **other frame's** vertex positions with the same barycentric weights and project them.

    The barycentric weights are perspective-corrected, so using them directly to interpolate the other frame's positions mathematically means "evaluating at the same
    surface parameter point" -- which is exactly the definition of a motion vector.
    """
    hit, bary, tri = rast["hit"], rast["bary"], rast["tri"]
    m = hit >= 0
    H, W = hit.shape
    sx = np.zeros((H, W))
    sy = np.zeros((H, W))
    z = np.zeros((H, W))
    if not m.any():
        return sx, sy, z, m
    t = hit[m]
    w = bary[m]
    Pp = (P_other[tri[t, 0]] * w[:, 0:1] + P_other[tri[t, 1]] * w[:, 1:2]
          + P_other[tri[t, 2]] * w[:, 2:3])
    a, b, c = _rnd.project(cam, Pp)
    sx[m], sy[m], z[m] = a, b, c
    return sx, sy, z, m


def motion_vectors(geo, cam, geo_next=None, cam_next=None, group="",
                   units="pixels", depth_bias=0.02, silhouette_guard=1,
                   device="numpy"):
    """
    Exact screen-space displacement between two frames. Returns a CopImage with layers:

        motion        (2)  on frame t's grid, "where it goes next frame" (pixels)
        motion_bwd    (2)  on frame t+1's grid, "where it came from last frame" (pixels)
        mask          (1)  coverage of frame t
        mask_next     (1)  coverage of frame t+1
        disocclusion  (1)  places in frame t+1 not visible in the previous frame (= must be repainted)

    If the geometry does not move pass only cam_next (camera motion); if the camera does not move pass only geo_next (object motion);
    pass both when both move.
    """
    gn = _check_pair(geo, geo_next)
    cn = cam_next if cam_next is not None else cam
    if (int(cn["xres"]), int(cn["yres"])) != (int(cam["xres"]),
                                              int(cam["yres"])):
        raise ValueError(
            f"Both frames must have the same resolution: {cam['xres']}x{cam['yres']} vs "
            f"{cn['xres']}x{cn['yres']}. Motion vectors are a per-pixel correspondence; "
            f"if the two grids differ, that correspondence is undefined.")
    W, H = int(cam["xres"]), int(cam["yres"])
    P0 = np.asarray(geo.get(POINT, "P"), np.float64)
    P1 = np.asarray(gn.get(POINT, "P"), np.float64)

    px = np.arange(W, dtype=np.float64)[None, :]
    py = np.arange(H, dtype=np.float64)[:, None]

    # ── forward: on frame t's grid
    r0 = _rnd.rasterize(geo, cam, group)
    fx, fy, _, m0 = _screen_of(cn, geo, r0, P1)
    fwd = np.zeros((H, W, 2))
    fwd[:, :, 0] = np.where(m0, fx - px, 0.0)
    fwd[:, :, 1] = np.where(m0, fy - py, 0.0)

    # ── backward: on frame t+1's grid. **Must be rasterized again**, cannot use the negated forward
    r1 = _rnd.rasterize(gn, cn, group)
    bx, by, _, m1 = _screen_of(cam, gn, r1, P0)
    bwd = np.zeros((H, W, 2))
    bwd[:, :, 0] = np.where(m1, bx - px, 0.0)
    bwd[:, :, 1] = np.where(m1, by - py, 0.0)

    # ── disocclusion: a frame t+1 pixel, following its backward vector back to frame t -- is it visible there?
    #    The criterion uses triangle IDs (same trick as UV back-projection): if the triangle visible at the pixel it lands on
    #    is this very triangle, then it really was visible in the previous frame
    dis = np.zeros((H, W, 1))
    if m1.any():
        xi = np.clip(np.rint(bx[m1]).astype(np.int64), 0, W - 1)
        yi = np.clip(np.rint(by[m1]).astype(np.int64), 0, H - 1)
        inframe = ((bx[m1] >= -0.5) & (bx[m1] <= W - 0.5)
                   & (by[m1] >= -0.5) & (by[m1] <= H - 0.5))
        front = r0["hit"][yi, xi]
        mine = r1["hit"][m1]
        _, _, zback, _ = _screen_of(cam, gn, r1, P0)
        near = (front >= 0) & (zback[m1] <= r0["z"][yi, xi]
                               + float(depth_bias)
                               * max(float(cam.get("radius", 1.0)), 1e-9))
        ok = inframe & ((front == mine) | near)
        if int(silhouette_guard) > 0:
            # **Silhouettes also count as "cannot warp".** If going back to frame t lands within one or two pixels
            # of an object edge, the fetched color is mixed with background, and the warp gives a dirty fringe -- the same
            # guard as on the back-projection side. Measured (sphere rotating 10°/frame, 256²): without the guard the valid pixels'
            # error p99 is 0.0714, a 1-pixel guard brings it to 0.0011, and the 1182 rejected pixels
            # themselves have mean error 0.0277 (an order of magnitude above the kept ones)
            er = _erode(r0["hit"] >= 0, int(silhouette_guard))
            ok = ok & er[yi, xi]
        d = np.zeros((H, W))
        d[m1] = (~ok).astype(np.float64)
        dis[:, :, 0] = np.where(m1, d, 1.0)     # places not covered at t+1 count as "disoccluded"
    else:
        dis[:, :, 0] = 1.0

    fwd, bwd = _convert_units(fwd, W, H, units), _convert_units(bwd, W, H,
                                                                units)
    from .cop import backend as _bk
    xp = _bk.get(device, W * H, 5, 2)
    img = CopImage(W, H)
    img.set(MOTION_LAYER, xp.asarray(fwd.astype(np.float32)))
    img.set(MOTION_BWD_LAYER, xp.asarray(bwd.astype(np.float32)))
    img.set("mask", xp.asarray(m0.astype(np.float32)[:, :, None]))
    img.set("mask_next", xp.asarray(m1.astype(np.float32)[:, :, None]))
    img.set(DISOCC_LAYER, xp.asarray(dis.astype(np.float32)))
    return img


def _erode(mask, n):
    """Shrink the coverage mask inward by n pixels. Same meaning as backproject._erode."""
    m = np.asarray(mask, bool)
    for _ in range(int(n)):
        m = (m & np.roll(m, 1, 0) & np.roll(m, -1, 0)
             & np.roll(m, 1, 1) & np.roll(m, -1, 1))
        m[0, :] = m[-1, :] = False
        m[:, 0] = m[:, -1] = False
    return m


def _convert_units(mv, W, H, units):
    if units == "pixels":
        return mv
    if units == "uv":
        return mv / np.array([float(W), float(H)])
    if units == "normalized":
        # consistent with NDC: the whole frame spans 2, so divide by W/2 / H/2
        return mv / np.array([W * 0.5, H * 0.5])
    raise ValueError(f"Units must be one of {UNITS}")


def _to_pixels(mv, W, H, units):
    if units == "pixels":
        return mv
    if units == "uv":
        return mv * np.array([float(W), float(H)])
    if units == "normalized":
        return mv * np.array([W * 0.5, H * 0.5])
    raise ValueError(f"Units must be one of {UNITS}")


# ═══════════════════════════════════════════════════════════════ warp
def warp(image, motion, layer=DEFAULT_LAYER, motion_layer=MOTION_BWD_LAYER,
         units="pixels", edge="clamp", filter="bilinear", device="numpy"):
    """
    **Backward** warp: every output pixel fetches one value from the input image according to motion.

        out[p] = image[p + motion[p]]

    So the motion passed in must be `motion_bwd` ("where it came from last frame" on frame t+1's grid);
    passing the forward one gives a reverse-warped image -- and at small displacements it looks "about right"; only once it moves
    do you notice the smear goes the wrong way. The default layer name is motion_bwd to head this off.

    This is the most direct use for temporal consistency: warp the previous frame's AI output to this frame's position, as
    the img2img init or a ControlNet reference; the `disocclusion` layer is exactly the inpaint mask.
    """
    a = image.need(layer)
    if not isinstance(a, np.ndarray):
        a = image.to_device("numpy").need(layer)
    a = np.asarray(a, np.float64)
    mv = motion.need(motion_layer)
    if not isinstance(mv, np.ndarray):
        mv = motion.to_device("numpy").need(motion_layer)
    mv = np.asarray(mv, np.float64)
    H, W = a.shape[0], a.shape[1]
    if mv.shape[:2] != (H, W):
        raise ValueError(
            f"The image is {W}x{H}, the motion vectors are {mv.shape[1]}x{mv.shape[0]} -- "
            f"warp is per-pixel, the two must have the same resolution.")
    if mv.shape[2] < 2:
        raise ValueError(f"Layer '{motion_layer}' has only {mv.shape[2]} channels, "
                         f"motion vectors need 2 (x,y).")
    mvp = _to_pixels(mv[:, :, :2], W, H, units)
    gx = np.arange(W, dtype=np.float64)[None, :] + mvp[:, :, 0]
    gy = np.arange(H, dtype=np.float64)[:, None] + mvp[:, :, 1]
    # pixel coordinates -> uv, handed to the same sampler used elsewhere (there can only be one pixel-center convention)
    from .cop import filters as _flt
    from .cop import backend as _bk
    u = (gx + 0.5) / W
    v = (gy + 0.5) / H
    if filter == "closest":
        xi = np.floor(gx + 0.5).astype(np.int64)
        yi = np.floor(gy + 0.5).astype(np.int64)
        if edge == "wrap":
            out = a[np.mod(yi, H), np.mod(xi, W)]
        else:
            oob = (xi < 0) | (xi >= W) | (yi < 0) | (yi >= H)
            out = a[np.clip(yi, 0, H - 1), np.clip(xi, 0, W - 1)]
            if edge == "black":
                out = np.where(oob[:, :, None], 0.0, out)
    else:
        out = np.asarray(_flt.sample(a, u, v, border=edge, xp=_bk.EXACT),
                         np.float64)
    xp = _bk.get(device, W * H, 1, a.shape[2])
    img = image.copy()
    img.set(layer, xp.asarray(out.astype(np.float32)))
    return img


# ═══════════════════════════════════════════════════════════════ sequence
def render_sequence(geo, cams, group="", passes=("depth", "mask", "normal"),
                    normal_space="camera", normal_source="auto",
                    id_attrib="name", uv_attrib="uv", cull="none",
                    motion=False, motion_units="pixels", loop=False,
                    device="numpy"):
    """
    A list of cameras -> a list of CopImages.

    With motion=True each frame gains three layers motion / motion_bwd / disocclusion, computed from
    **this frame to the next**. The last frame has no next frame: with loop=True it wraps to frame 0 (exactly what a looping
    animation needs), otherwise all zeros + an all-1 disocclusion -- zeros rather than copying the previous
    frame, because downstream should be able to see that "the last frame's motion is undefined".
    """
    seq = []
    n = len(cams)
    for i, cam in enumerate(cams):
        img = _rnd.render(geo, cam, group, tuple(passes), normal_space,
                          normal_source, id_attrib, uv_attrib, cull, device)
        if motion:
            nxt = None
            if i + 1 < n:
                nxt = cams[i + 1]
            elif loop and n > 1:
                nxt = cams[0]
            if nxt is None:
                W, H = int(cam["xres"]), int(cam["yres"])
                z2 = np.zeros((H, W, 2), np.float32)
                img.set(MOTION_LAYER, z2)
                img.set(MOTION_BWD_LAYER, z2.copy())
                img.set(DISOCC_LAYER, np.ones((H, W, 1), np.float32))
            else:
                mv = motion_vectors(geo, cam, None, nxt, group,
                                    motion_units, device=device)
                for k in (MOTION_LAYER, MOTION_BWD_LAYER, DISOCC_LAYER):
                    img.set(k, mv.need(k))
        seq.append(img)
    return seq


def to_batch(seq, layer=DEFAULT_LAYER, mode="clamp", flip=True):
    """
    COP sequence -> (B,H,W,C), for ComfyUI's IMAGE.

    The v flip still only happens here (the bridge's rule), and `mode` keeps the bridge's four modes.
    **The normalizing modes are computed over the whole sequence at once**, not per frame -- per-frame normalization makes brightness
    jump from frame to frame, the easiest pitfall when doing animation.
    """
    from .cop import bridge as _br
    if not seq:
        raise ValueError("The sequence is empty")
    if mode == "normalize":
        lo = min(float(np.min(_np_of(im.need(layer)))) for im in seq)
        hi = max(float(np.max(_np_of(im.need(layer)))) for im in seq)
        rng = (hi - lo) or 1.0
        out = []
        for im in seq:
            a = (_np_of(im.need(layer)) - lo) / rng
            out.append(_br.to_comfy(CopImage(im.xres, im.yres, {layer: a}),
                                    layer, "clamp", flip))
        return np.concatenate([np.asarray(o) for o in out], 0)
    return np.concatenate(
        [np.asarray(_br.to_comfy(im, layer, mode, flip)) for im in seq], 0)


def _np_of(a):
    if isinstance(a, np.ndarray):
        return np.asarray(a, np.float64)
    from .cop import backend as _bk
    return np.asarray(_bk.backend_of(a).to_numpy(a), np.float64)


def from_batch(image, name=DEFAULT_LAYER, flip=True, device="numpy"):
    """(B,H,W,C) -> COP sequence. B is the frame."""
    from .cop import bridge as _br
    a = image
    if hasattr(a, "cpu"):
        a = a.cpu().numpy()
    a = np.asarray(a)
    if a.ndim == 3:
        a = a[None]
    return [_br.from_comfy(a, name, i, flip, device) for i in range(len(a))]



def motion_sequence(geos, cams, group="", units="pixels", depth_bias=0.02,
                    silhouette_guard=1, loop=False, device="numpy"):
    """
    A list of geometries + a list of cameras -> a list of motion vectors. **The moving geometry + moving camera case.**

    The motion vectors of `render_sequence` can only capture camera motion (the geometry is a single copy). This function takes
    the geometry sequence from For-Each Frame End, so motion vectors of deformation, growth and fracture can all be computed.

    The geometry and camera sequences must have the same length, or only 1 camera is given (fixed camera). The last frame
    has no next frame: loop=True wraps to frame 0, otherwise all zeros + an all-1 disocclusion --
    downstream should be able to see that it is "undefined".
    """
    n = len(geos)
    if n == 0:
        return []
    cs = list(cams) if cams else []
    if not cs:
        raise ValueError("Motion vectors need a camera -- connect a Camera Path.")
    if len(cs) == 1:
        cs = cs * n
    if len(cs) != n:
        raise ValueError(
            f"The geometry sequence has {n} frames, the camera sequence {len(cs)} cameras -- they must match"
            f" (or give only 1 as a fixed camera). The symptom of a frame offset is motion vectors shifted by one frame overall, "
            f"and the warp shows double images.")
    out = []
    for i in range(n):
        j = i + 1 if i + 1 < n else (0 if (loop and n > 1) else None)
        if j is None:
            W, H = int(cs[i]["xres"]), int(cs[i]["yres"])
            img = CopImage(W, H)
            z2 = np.zeros((H, W, 2), np.float32)
            img.set(MOTION_LAYER, z2)
            img.set(MOTION_BWD_LAYER, z2.copy())
            img.set(DISOCC_LAYER, np.ones((H, W, 1), np.float32))
            img.set("mask", np.zeros((H, W, 1), np.float32))
            img.set("mask_next", np.zeros((H, W, 1), np.float32))
            out.append(img)
            continue
        out.append(motion_vectors(geos[i], cs[i], geos[j], cs[j], group,
                                  units, depth_bias, silhouette_guard,
                                  device))
    return out


def stack_layer(seq, layer):
    """Stack one layer of a list of CopImages into raw (B,H,W,C) values (no flip, no clamp)."""
    return np.stack([_np_of(im.need(layer)) for im in seq], 0)
