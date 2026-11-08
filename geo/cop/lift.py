"""
Depth / MoGe -> height field: "lift" an (AI-generated) landscape image into terrain.

In the AI -> procedural direction, the most direct source of terrain is an image: a diffusion model paints a valley, a monocular
geometry model (MoGe / Depth Anything) estimates how far each pixel is from the camera, and here it is **flattened back into a top-down
height field** -- after which erosion, river networks, Splat Map, conversion to mesh, the whole terrain chain can follow.

The models themselves are not reimplemented here: ComfyUI core already ships MoGe (`MoGeInference` outputs
MOGE_GEOMETRY), and comfyui_controlnet_aux ships Depth Anything V2. This file only does
geometry: back-projection, finding the ground, top-down rasterization, hole filling.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two kinds of input, with very different reliability
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MoGe (recommended)  gives **camera-space points** directly (OpenCV: x right, y down, z forward); MoGe-2
                 is metric scale and also provides intrinsics and a sky mask. Nothing needs guessing here
  depth IMAGE     Depth Anything and similar output **relative inverse depth** (disparity, near = white),
                 determined only up to an unknown scale and offset: d = a/z + b. Here we take
                 z = 1 / (d + shift), where shift is a guess at b; FOV must also be entered by hand. Guessing wrong
                 **bends** the terrain (the distance gets stretched or squashed), not a uniform scale -- so
                 in perspective mode use MoGe whenever possible. Depth maps suit top_down mode better: the image itself is
                 top-down (satellite image / AI-painted orthographic map), and depth is used directly as height

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Finding the ground: plane fit weighted by ground area
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The camera usually looks down, so "up" isn't the camera's −y. fit_plane does one weighted
PCA over all valid points; the smallest eigenvector is the ground normal. **The weight is z²**: in perspective the ground area a pixel covers
∝ z²; without weighting the near field (many pixels) dominates the fit and distant mountains, however large, get no say. Then the 20% of points highest
above the plane (peaks) are removed and the fit repeated twice -- one big mountain at the back would tilt the plane backward. In tests:
camera pitch 35.5°, recovered on flat ground within 8e-7°; with a big distant mountain off by 0.34° (2.2° without removing peaks);
a near slope 0.15 high (many pixels, little area) skews it by 2.8° (6.3° without weighting).

**What it can't handle**: a large near **depression**. Peak removal only removes the "higher" side, so a depression tilts the plane
downward -- a depression band of the same scale skews it by 10°. In that case switch to camera_level (landscape shots taken with a level camera
are usually level), or crop out the near field first.

When the normal is more than 70° from the camera's −y (it's a shot of a cliff face), plane fitting is meaningless; it falls back to
camera_level (assume the camera is level), and the report says so.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Top-down rasterization
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
World frame: X = camera right projected onto the ground, Y = ground normal, Z = toward the camera (south). The height field's
u runs along +X, v along −Z (far = north = top of the image), the same convention as HeightField to Mesh,
so after conversion to a mesh the camera stands in the south looking north.

Each cell takes the **mean** Y and mean colour of the points that land in it. The first version took the highest (thinking "what's visible is the
surface"), but these points are **all** visible surface points -- taking the highest just picks the point at the top of the slope in the cell,
so neighbouring cells alternately pick the upper and lower edge, giving moiré patterns on the hillshade. In perspective, distant cells get ever sparser points, and whole areas behind mountains are invisible -- these cells are filled with push-pull
(smooth, not nearest-neighbour steps); the `mask` layer marks which cells were actually measured. **What's filled in is
a guess**: the back sides of mountains simply have no information in the image.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8-bit depth maps: dequantize first
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Depth preprocessors (comfyui_controlnet_aux's Depth Anything V2 among them) hand over an 8-bit image: 256 disparity
levels. z = 1/(d + shift) turns each level into one distance, so the points of a level form a thin arc on the ground
with an empty band before the next one -- the far field, where one level covers many rows, comes out as horizontal
streaks and terraces (seen top-down; in top_down mode the same steps are height terraces). When the values sit on a
1/255 lattice, `dequantize` replaces them by the smoothest image that still rounds to the same levels: coarse-to-fine
masked box blurs, each followed by a clamp into the pixel's own quantization bin [d - q/2, d + q/2]. The clamp is what
keeps edges: across a silhouette the blur can move a value by at most half a level. Float depth (MoGe, a 16-bit or
float map) is not on the lattice and passes through untouched.

The extent is the 1~99 percentile of X / Z (dropping stray far points at the horizon), then far_quantile drops the farthest
slice of points -- the ring of points along the horizon is sparse and inaccurate; keeping it only inflates the grid with holes.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage
from . import backend as bk

MODES = ("perspective", "top_down")
DEPTH_KINDS = ("disparity", "depth")
UP_MODES = ("fit_plane", "camera_level")
_CAM_UP = np.array([0.0, -1.0, 0.0])          # OpenCV: y points down


def _to_np(a):
    if a is None:
        return None
    if hasattr(a, "detach"):
        a = a.detach().cpu().float().numpy()
    return np.asarray(a, np.float64)


def _pick(batch, index):
    a = _to_np(batch)
    if a is None:
        return None
    if a.ndim >= 3 and a.shape[0] >= 1 and a.ndim in (3, 4):
        b = min(max(int(index), 0), a.shape[0] - 1)
        return a[b]
    return a


def _resize_to(a, H, W):
    """(h,w,C) -> (H,W,C) bilinear (pixel centres). Returned as is if the size is the same."""
    if a.shape[0] == H and a.shape[1] == W:
        return a
    from .filters import resize
    tmp = CopImage(a.shape[1], a.shape[0], {"a": a})
    return np.asarray(resize(tmp, W, H).need("a"), np.float64)


# ═══════════════════════════════════════════════════════════════ dequantize
def quantization_step(d, valid=None, levels=255, tol=1e-3, share=0.98):
    """1/levels when (nearly) all finite values sit on the k/levels lattice, else 0."""
    d = np.asarray(d, np.float64)
    m = np.isfinite(d) if valid is None else (np.asarray(valid, bool) & np.isfinite(d))
    v = d[m]
    if v.size < 16 or v.min() < -tol or v.max() > 1.0 + tol:
        return 0.0
    k = v * levels
    on = np.abs(k - np.round(k)) < tol
    # a constant or two-level image is "on the lattice" without telling anything about quantization
    if on.mean() < share or np.unique(np.round(k[on])).size < 4:
        return 0.0
    return 1.0 / levels


def _box(a, r):
    """Box sum over a (2r+1)² window, zero outside (summed-area table)."""
    H, W = a.shape
    S = np.zeros((H + 1, W + 1))
    S[1:, 1:] = a.cumsum(0).cumsum(1)
    i0 = np.clip(np.arange(H) - r, 0, H); i1 = np.clip(np.arange(H) + r + 1, 0, H)
    j0 = np.clip(np.arange(W) - r, 0, W); j1 = np.clip(np.arange(W) + r + 1, 0, W)
    return (S[i1][:, j1] - S[i0][:, j1] - S[i1][:, j0] + S[i0][:, j0])


def dequantize(d, valid=None, step=None, radii=(32, 16, 8, 4, 2, 1), iters=10):
    """
    -> (dequantized d, step used). step=None detects it (quantization_step); 0 = not quantized, d is returned as is.
    Only valid pixels take part and change; the result never leaves a pixel's bin [d - step/2, d + step/2].
    """
    d = np.asarray(d, np.float64)
    m = np.isfinite(d) if valid is None else (np.asarray(valid, bool) & np.isfinite(d))
    q = quantization_step(d, m) if step is None else float(step)
    if q <= 0 or not m.any():
        return d, 0.0
    lo, hi = d - q * 0.5, d + q * 0.5
    w = m.astype(np.float64)
    x = np.where(m, d, 0.0)
    for r in radii:
        cnt = np.maximum(_box(w, r), 1e-12)
        for _ in range(int(iters)):
            x = np.clip(_box(x * w, r) / cnt, lo, hi)
            x = np.where(m, x, 0.0)
    return np.where(m, x, d), q


# ═══════════════════════════════════════════════════════════════ points
def points_from_depth(d, fov_x=60.0, kind="disparity", shift=0.05,
                      sky=0.02):
    """
    Depth map (H,W) -> points in OpenCV camera space (H,W,3) + valid mask. row 0 = top of the image
    (the IMAGE convention, which conveniently is also OpenCV's y down).
    """
    if kind not in DEPTH_KINDS:
        raise ValueError(f"Depth Kind must be one of {DEPTH_KINDS}")
    f_ = float(fov_x)
    if not 1.0 <= f_ <= 170.0:
        raise ValueError("FOV X must be between 1 and 170 degrees")
    d = np.asarray(d, np.float64)
    H, W = d.shape
    if kind == "disparity":
        valid = np.isfinite(d) & (d > float(sky))
        den = d + float(shift)
        valid &= den > 0
        z = np.where(valid, 1.0 / np.where(valid, den, 1.0), np.nan)
    else:
        valid = np.isfinite(d) & (d > 0)
        z = np.where(valid, d, np.nan)
    fx = (W * 0.5) / math.tan(math.radians(f_) * 0.5)
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    x = (J + 0.5 - W * 0.5) / fx * z
    y = (I + 0.5 - H * 0.5) / fx * z
    return np.stack([x, y, z], -1), valid


def points_from_moge(geom, batch_index=0):
    """MOGE_GEOMETRY (dict) -> (points (H,W,3), valid mask, colour (H,W,3) or None)."""
    if not isinstance(geom, dict) or "points" not in geom:
        raise ValueError("MoGe Geometry has no points -- connect the output of MoGeInference "
                         "(the panorama node's output also has points)")
    P = _pick(geom["points"], batch_index)
    valid = np.isfinite(P).all(-1)
    m = _pick(geom.get("mask"), batch_index)
    if m is not None:
        valid &= np.asarray(m, bool)
    col = _pick(geom.get("image"), batch_index)
    if col is not None:
        col = _resize_to(col[..., :3], P.shape[0], P.shape[1])
    return P, valid, col


# ═══════════════════════════════════════════════════════════════ ground
def ground_frame(P, valid, mode="fit_plane", trim=0.8, trim_iters=2):
    """
    -> (origin, ex, ey, ez, report). ey = ground normal (up), ez toward the camera, ex = ey × ez.
    """
    if mode not in UP_MODES:
        raise ValueError(f"Up must be one of {UP_MODES}")
    pts = P[valid]
    if len(pts) < 3:
        raise ValueError("fewer than 3 valid points -- is the depth map all sky / all masked out?")
    w = pts[:, 2] ** 2
    w = w / w.sum()
    o = (pts * w[:, None]).sum(0)
    rep = {"up_mode": mode}
    n = _CAM_UP.copy()
    if mode == "fit_plane":
        keep = np.ones(len(pts), bool)
        for it in range(1 + int(trim_iters)):
            wk = w * keep
            wk = wk / wk.sum()
            o = (pts * wk[:, None]).sum(0)
            q = pts - o
            C = (q * wk[:, None]).T @ q
            evals, evecs = np.linalg.eigh(C)
            n = evecs[:, 0]
            if n @ _CAM_UP < 0:
                n = -n
            if it < int(trim_iters):
                # Remove the slice highest above the plane (peaks) and refit. One big mountain at the back would
                # tilt the plane backward -- measured: a 35.5° pitch was fitted as 37.7° (2.2° off);
                # removing the 20% with the highest residual each round gives 0.64° after one round, 0.34° after two. Only the
                # "higher" side is removed: the ground is the layer pressed down under the mountains, not the one dug out by
                # valleys. On flat ground this step changes nothing (8e-7° off, the magnitude of float32 depth)
                r = q @ n
                keep = r <= np.quantile(r, float(trim))
        tilt = math.degrees(math.acos(min(1.0, abs(float(n @ _CAM_UP)))))
        rep["camera_pitch_deg"] = tilt
        if tilt > 70.0:
            n = _CAM_UP.copy()
            rep["up_mode"] = "camera_level (the plane-fit normal is " \
                f"{tilt:.0f}° from the camera up direction, not trustworthy, fell back)"
    fwd = np.array([0.0, 0.0, 1.0])
    f = fwd - (fwd @ n) * n
    f = f / np.linalg.norm(f)
    ez = -f
    ex = np.cross(n, ez)
    return o, ex, n, ez, rep


# ═══════════════════════════════════════════════════════════ rasterization
def rasterize(X, Y, Z, colors, resolution=512, extent=None):
    """
    Top-down rasterization. X/Y/Z are 1D world coordinates. Returns (height (R,R), coverage (R,R) bool,
    colour (R,R,3) or None, world width). row 0 = south (near), consistent with COP's v up.

    extent = (x0, x1, z0, z1) is used if given, otherwise the 1~99 percentiles.
    """
    R = int(resolution)
    if extent is not None:
        x0, x1, z0, z1 = (float(e) for e in extent)
    else:
        x0, x1 = np.percentile(X, [1, 99])
        z0, z1 = np.percentile(Z, [1, 99])
    L = max(x1 - x0, z1 - z0, 1e-9)
    cx, cz = (x0 + x1) * 0.5, (z0 + z1) * 0.5
    cell = L / R
    # u along +X; v along −Z (far = north = up)
    j = np.floor((X - (cx - L * 0.5)) / cell).astype(np.int64)
    i = np.floor(((cz + L * 0.5) - Z) / cell).astype(np.int64)
    ok = (j >= 0) & (j < R) & (i >= 0) & (i < R)
    k = i[ok] * R + j[ok]
    cn = np.bincount(k, minlength=R * R).astype(np.float64)
    hs = np.bincount(k, Y[ok], minlength=R * R)
    cov = cn > 0
    Hm = np.where(cov, hs / np.maximum(cn, 1.0), -np.inf)
    col = None
    if colors is not None:
        cs = np.stack([np.bincount(k, colors[ok][:, c], minlength=R * R)
                       for c in range(3)], -1)
        col = (cs / np.maximum(cn, 1.0)[:, None]).reshape(R, R, 3)
    return Hm.reshape(R, R), cov.reshape(R, R), col, L


def heightfield_from_points(P, valid, colors=None, resolution=512,
                            up="fit_plane", far_quantile=0.95,
                            fill_holes=True, height_layer="C",
                            mask_layer="mask", color_layer="albedo"):
    """-> (CopImage, world width, report)."""
    R = int(resolution)
    if not 8 <= R <= 8192:
        raise ValueError("Resolution must be between 8 and 8192")
    v = np.asarray(valid, bool).copy()
    fq = float(far_quantile)
    if not 0.05 <= fq <= 1.0:
        raise ValueError("Far Quantile must be between 0.05 and 1")
    if fq < 1.0 and v.any():
        v &= P[..., 2] <= np.quantile(P[..., 2][v], fq)
    o, ex, ey, ez, rep = ground_frame(P, v, up)
    q = P[v] - o
    X, Y, Z = q @ ex, q @ ey, q @ ez
    col = colors[v] if colors is not None else None
    Hm, cov, cimg, L = rasterize(X, Y, Z, col, R)
    if not cov.any():
        raise ValueError("no point landed in the grid")
    base = float(Hm[cov].min())
    Hm = np.where(cov, Hm - base, 0.0)
    from ..backproject import _push_pull
    if fill_holes:
        Hm = _push_pull(Hm[:, :, None], cov)[:, :, 0]
        if cimg is not None:
            cimg = _push_pull(cimg, cov)
    out = CopImage(R, R)
    out.set(str(height_layer).strip() or "C", Hm[:, :, None])
    if str(mask_layer).strip():
        out.set(str(mask_layer).strip(), cov.astype(np.float64)[:, :, None])
    if cimg is not None and str(color_layer).strip():
        out.set(str(color_layer).strip(), np.clip(cimg, 0.0, 1.0))
    rep.update({"world_size": float(L), "points": int(v.sum()),
                "coverage": float(cov.mean()),
                "height_range": float(Hm.max() - Hm.min())})
    return out, float(L), rep


def heightfield_top_down(d, kind="disparity", relief=0.25, colors=None,
                         height_layer="C", color_layer="albedo"):
    """
    Use a top-down depth map directly as height. disparity: bright = near = high; depth: dark = near = high.
    Normalized to 0~relief. Flips v: IMAGE's row 0 is the top, COP's is the bottom.
    """
    if kind not in DEPTH_KINDS:
        raise ValueError(f"Depth Kind must be one of {DEPTH_KINDS}")
    d = np.asarray(d, np.float64)
    fin = np.isfinite(d)
    if not fin.any():
        raise ValueError("depth map has no finite values")
    lo, hi = float(d[fin].min()), float(d[fin].max())
    t = (np.where(fin, d, lo) - lo) / (hi - lo) if hi > lo \
        else np.zeros_like(d)
    if kind == "depth":
        t = 1.0 - t
    H, W = d.shape
    out = CopImage(W, H)
    out.set(str(height_layer).strip() or "C",
            (t * float(relief))[::-1][:, :, None].copy())
    if colors is not None and str(color_layer).strip():
        c = _resize_to(np.asarray(colors, np.float64)[..., :3], H, W)
        out.set(str(color_layer).strip(), np.clip(c[::-1], 0.0, 1.0).copy())
    return out, {"mode": "top_down", "input_range": [lo, hi]}


def lift(depth=None, moge_geometry=None, image=None, mode="perspective",
         resolution=512, depth_kind="disparity", fov_x=60.0, shift=0.05,
         sky=0.02, up="fit_plane", far_quantile=0.95, fill_holes=True,
         relief=0.25, world_size=1.0, batch_index=0, dequant=True):
    """
    Node entry point. Returns (CopImage, world width, report dict).

    moge_geometry takes priority over depth. top_down only takes depth (MoGe points are inherently perspective).
    dequant: smooth an 8-bit depth map back into continuous values first (see the module notes); no effect on float input.
    """
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    col = _pick(image, batch_index)
    if col is not None:
        col = col[..., :3]
    if mode == "top_down":
        if depth is None:
            raise ValueError("top_down needs depth (a top-down depth map)")
        d = _pick(depth, batch_index)
        d = d[..., 0] if d.ndim == 3 else d
        q = 0.0
        if dequant:
            d, q = dequantize(d)
        out, rep = heightfield_top_down(d, depth_kind, relief * world_size,
                                        col)
        rep["world_size"] = float(world_size)
        rep["dequantized"] = q
        return out, float(world_size), rep
    if moge_geometry is not None:
        P, valid, mcol = points_from_moge(moge_geometry, batch_index)
        if col is None:
            col = mcol
        src = "moge"
    elif depth is not None:
        d = _pick(depth, batch_index)
        d = d[..., 0] if d.ndim == 3 else d
        q = 0.0
        if dequant:
            # sky pixels stay out of the blur, so the horizon does not pull the far ground toward zero disparity
            fin = np.isfinite(d)
            keep = fin & (d > float(sky)) if depth_kind == "disparity" else fin & (d > 0)
            q = quantization_step(d)
            if q:
                d, _ = dequantize(d, keep, q)
        P, valid = points_from_depth(d, fov_x, depth_kind, shift, sky)
        src = f"depth({depth_kind})"
    else:
        raise ValueError("connect at least one of depth and moge_geometry")
    if col is not None:
        col = _resize_to(col, P.shape[0], P.shape[1])
    out, L, rep = heightfield_from_points(P, valid, col, resolution, up,
                                          far_quantile, fill_holes)
    rep["source"] = src
    rep["dequantized"] = q if src.startswith("depth") else 0.0
    return out, L, rep
