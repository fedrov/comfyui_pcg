"""
UV back-projection -- render an image, let AI make a texture, **project it back into UV space by visibility**. With this step
the "geometry -> image -> geometry" chain is closed.

The preceding nodes are one-directional: Render Pass renders geometry into depth / normal / lineart,
Control Image packs it per ControlNet conventions, the diffusion model outputs an image -- and then that image just
sits there. It is laid out in **screen pixels**, while the asset needs a texture laid out in **uv**.
This file is that conversion.

    uv_rasterize       rasterizes in **uv space**; each texel looks up its world position / normal
    project_texture    forward: renders a uv texture to the screen (the other half of the loop, and also the test criterion)
    backproject        backward: projects a screen image into uv space, weighted by visibility + facing
    resolve            accumulator -> texture (divide by weight + hole filling + dilation)

Multiple views are chained through an **accumulator**: each `backproject` takes the previous one's accumulator and adds its own
view's contribution. N cameras means N chained nodes, the same as for-each over views in Houdini.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Visibility criterion: **compare triangle numbers first, then depth**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The textbook approach projects the texel's world position to the screen and compares its camera-space z with the pixel's depth buffer;
if it differs by much it counts as occluded. The problem is that the two depths are **sampled at different positions**: the projected texel centre
lands near the pixel centre but not on it, and on a slanted surface the depth range of one pixel can span several units.
Too small a bias gives self-occlusion (patches of black spots on the texture, the same disease as shadow acne), too large lets
truly occluded areas leak in (an arm in front prints its colour onto the torso behind it).

So an extra criterion is added: uv rasterization already knows **which triangle** each texel belongs to, and screen rasterization
also knows **which triangle is visible** on each pixel. Same -> visible right away, without looking at depth.

Measured (a sphere mostly hidden behind a blocking board, 512^2 texture; occlusion ground truth computed analytically as "does the segment from
the texel to the eye pass through the board"; 51350 texels, of which 10307 should be visible and 41043 occluded):

    depth_bias (fraction of bound. radius) depth only false occl.   + triangle false occl.
    0.0005                            44.8%              6.2%
    0.001                             39.5%              5.5%
    0.005                              6.2%              1.1%
    0.02 (default)                      0%                0%
    1.0                                 0%                0%   <- but 95% leaks in

"Leaking in" (occluded but accepted) is **0.40%** for both criteria and independent of the bias -- it is
a thin band of pixels along the board's silhouette that every depth-buffer-based criterion has; it can only be reduced by raising the render
resolution.

To be honest about the conclusion: triangle numbers do **not** make the bias irrelevant; they make small biases **7 times
more forgiving** (at 0.001: 39.5% -> 5.5%). At a bias of 0.02 both are clean. The real value is
not getting a screen full of acne right away when the scene scale is unknown.

Conversely, **triangle numbers alone are not enough either**: measured 15.2% false occlusion. Texels and pixels are not one-to-one
(a 512^2 texture projected onto a 512^2 screen can cram several texels into one pixel), and the pixel a texel centre
projects into may well be occupied by an **adjacent** triangle. Hence "or", not "and".

The unit of `depth_bias` is a **fraction of the bounding sphere radius**, not world units -- if the scene is scaled up 100 times
the bias has to scale with it; hard-coding world units would require retuning for every model.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Blending must happen in **linear** space
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Images from diffusion models are sRGB encoded. When two views each have half the weight in an overlap region, averaging
the encoded values directly:

    encoded 0.2 and 0.8 -> average first (0.50) then decode -> linear 0.2140
                        -> decode first then average        -> linear 0.3185

A difference of **1.49x**. It shows up as the overlap band being darker overall, and **only the overlap band** is off, so it looks like a seam.
Hence the default `decode="srgb_to_linear"`: accumulation happens in linear space, and `encode` decides whether to encode back
on output.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Weights
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    facing  (N . direction towards the camera) ^ facing_power. At grazing angles a texel covers only a tiny area
            on screen and is heavily stretched; it should give way to the view facing it head-on
    border  fade-out within the border_fade band at the edge of the frame. Without it there is a hard edge
            at the seam between two views -- and the edges are exactly where the diffusion model is least reliable
    visible the scheme above, 0 or 1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hole filling uses push-pull, not flood fill
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Texels seen by no view (back faces, fully occluded, seams between uv islands) must be filled, otherwise black edges
bleed in when sampling. Push-pull downsamples the "weighted image" level by level into a pyramid and upsamples back level by level;
weighted areas keep their original values, unweighted ones are filled with the interpolation from the level above -- O(n), fills arbitrarily
large holes in one go, and the fill is **smooth**. Flood fill / round-by-round dilation needs as many rounds as the hole's radius,
is much slower on large holes, and leaves concentric ring patterns.

Dilation (gutter / padding) is a separate matter: a few extra rings must be written outside uv island boundaries, otherwise bilinear sampling
picks up the background colour at island edges. The default dilates by 4 texels, done before hole filling.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .cop.core import CopImage, DEFAULT_LAYER
from . import render as _rnd
from . import frommap as _fm

MAX_PAIRS = 1 << 24
VISIBILITY = ("triangle+depth", "triangle", "depth", "none")
SUM_LAYER = "Csum"
WEIGHT_LAYER = "Wsum"
COUNT_LAYER = "views"


# ═════════════════════════════════════════════════════════ uv-space rasterization
def _corner_uv(geo, uv_attrib="uv"):
    """uv of each corner. If not on vertices, taken from points (degenerates at seams)."""
    name = str(uv_attrib).strip() or "uv"
    a = geo.get(VERTEX, name)
    if a is not None and a.shape[1] >= 2:
        return np.asarray(a[:, :2], np.float64)
    p = geo.get(POINT, name)
    if p is None:
        raise KeyError(
            f"The geometry has no '{name}' attribute (neither on vertex nor point) --"
            f" back-projection needs a UV Project / UV Flatten (PCG) upstream first.")
    return np.asarray(p[:, :2], np.float64)[geo.vertex_point]


def uv_rasterize(geo, xres, yres, group="", uv_attrib="uv",
                 conservative=0.5, max_pairs=MAX_PAIRS):
    """
    Rasterizes in uv space. Returns a dict:

        hit   (H,W) int64   which triangle this texel belongs to, -1 if none
        bary  (H,W,3)       barycentric weights
        tri/cor/src         same as in render.rasterize

    Barycentrics are **affine**, without perspective correction -- uv space is the parameter domain, there is no projection here.

    Where uvs overlap, the **lowest triangle number** wins. The overlap itself means the uvs are broken (needs UV Layout),
    but the result must be deterministic: "last written wins" would make the output change with the triangulation order, and the triangulation order
    changes with any upstream node.

    conservative is the outward margin (in texels). A texel whose centre lies just half a texel outside the triangle
    is still read by GPU bilinear sampling -- strict rasterization would leave a ring of
    unwritten texels along every uv edge. The default 0.5 texel exactly covers bilinear's footprint.
    """
    from .spatial import tri_soup
    W, H = int(xres), int(yres)
    hit = np.full((H, W), -1, np.int64)
    bary = np.zeros((H, W, 3))
    out = {"hit": hit, "bary": bary, "tri": np.zeros((0, 3), np.int64),
           "cor": np.zeros((0, 3), np.int64), "src": np.zeros(0, np.int64)}
    if geo is None or geo.nprims == 0 or geo.npoints == 0:
        return out
    tri, src, cor = tri_soup(geo, group)
    out["tri"], out["src"], out["cor"] = tri, src, cor
    if not len(tri):
        return out

    uv = _corner_uv(geo, uv_attrib)
    tx = uv[:, 0] * W - 0.5
    ty = uv[:, 1] * H - 0.5
    X = tx[cor]                                    # (T,3)
    Y = ty[cor]
    area2 = ((X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0])
             - (Y[:, 1] - Y[:, 0]) * (X[:, 2] - X[:, 0]))
    keep = np.abs(area2) > 1e-12                   # triangles degenerate in uv are skipped
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return out

    c = float(conservative)
    x0 = np.maximum(np.floor(X[idx].min(1) - c).astype(np.int64), 0)
    x1 = np.minimum(np.ceil(X[idx].max(1) + c).astype(np.int64) + 1, W)
    y0 = np.maximum(np.floor(Y[idx].min(1) - c).astype(np.int64), 0)
    y1 = np.minimum(np.ceil(Y[idx].max(1) + c).astype(np.int64) + 1, H)
    bw = np.maximum(x1 - x0, 0)
    bh = np.maximum(y1 - y0, 0)
    area = bw * bh
    live = area > 0
    idx, x0, y0, bw, bh, area = (idx[live], x0[live], y0[live], bw[live],
                                 bh[live], area[live])
    if not len(idx):
        return out

    best = np.full(H * W, np.iinfo(np.int64).max, np.int64)
    cum = np.cumsum(area)
    total = int(cum[-1])
    nb = max(1, int(np.ceil(total / float(max(max_pairs, 1024)))))
    bounds = np.searchsorted(cum, np.linspace(0, total, nb + 1)[1:])
    start = 0
    for stop in bounds:
        stop = int(min(max(stop + 1, start + 1), len(idx)))
        _uv_batch(best, X, Y, area2, idx[start:stop], x0[start:stop],
                  y0[start:stop], bw[start:stop], bh[start:stop],
                  area[start:stop], W, c)
        start = stop
        if start >= len(idx):
            break

    won = best < np.iinfo(np.int64).max
    if not won.any():
        return out
    pix = np.nonzero(won)[0]
    t = best[pix]
    py = pix // W
    px = pix - py * W
    b = _bary_at(X, Y, area2, t, px.astype(np.float64),
                 py.astype(np.float64))
    hit.reshape(-1)[pix] = t
    bary.reshape(-1, 3)[pix] = b
    return out


def _edges(X, Y, t, px, py):
    """Three edge functions (unnormalized) + three edge lengths. Counter-clockwise-positive is absorbed by the sign of area2."""
    x0, x1, x2 = X[t, 0], X[t, 1], X[t, 2]
    y0, y1, y2 = Y[t, 0], Y[t, 1], Y[t, 2]
    e0 = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    e1 = (x0 - x2) * (py - y2) - (y0 - y2) * (px - x2)
    e2 = (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)
    L0 = np.hypot(x2 - x1, y2 - y1)
    L1 = np.hypot(x0 - x2, y0 - y2)
    L2 = np.hypot(x1 - x0, y1 - y0)
    return e0, e1, e2, L0, L1, L2


def _uv_batch(best, X, Y, area2, idx, x0, y0, bw, bh, area, W, c):
    from .ops import _gather_blocks
    flat = _gather_blocks(np.zeros(len(area), np.int64), area)
    t = np.repeat(idx, area)
    bwr = np.repeat(bw, area)
    px = np.repeat(x0, area) + (flat % bwr)
    py = np.repeat(y0, area) + (flat // bwr)
    fx, fy = px.astype(np.float64), py.astype(np.float64)
    e0, e1, e2, L0, L1, L2 = _edges(X, Y, t, fx, fy)
    s = np.where(area2[t] < 0, -1.0, 1.0)
    # Signed distance to an edge = e/|edge|; expand outward by c texels
    inside = ((s * e0 >= -c * L0) & (s * e1 >= -c * L1)
              & (s * e2 >= -c * L2))
    if not inside.any():
        return
    np.minimum.at(best, (py[inside] * W + px[inside]), t[inside])


def _bary_at(X, Y, area2, t, px, py):
    e0, e1, e2, _, _, _ = _edges(X, Y, t, px, py)
    a = area2[t]
    return np.stack([e0 / a, e1 / a, e2 / a], 1)


def texel_surface(geo, rast, uv_attrib="uv", normal_attrib="N"):
    """
    World position and normal of each texel. Returns (P (H,W,3), N (H,W,3), mask (H,W)).

    Point normals are preferred (interpolated, they are smooth); otherwise primitive normals -- with those the facing
    weight makes every face a constant block and transitions in overlap regions look stepped, so it is better to compute a set on the spot.
    """
    hit, bary, tri = rast["hit"], rast["bary"], rast["tri"]
    m = hit >= 0
    H, W = hit.shape
    P = np.zeros((H, W, 3))
    N = np.zeros((H, W, 3))
    if not m.any():
        return P, N, m
    t = hit[m]
    w = bary[m]
    Pw = np.asarray(geo.get(POINT, "P"), np.float64)
    P[m] = (Pw[tri[t, 0]] * w[:, 0:1] + Pw[tri[t, 1]] * w[:, 1:2]
            + Pw[tri[t, 2]] * w[:, 2:3])
    nm = str(normal_attrib).strip() or "N"
    pn = geo.get(POINT, nm)
    if pn is None or pn.shape[1] < 3:
        from .ops import compute_normals
        pn = compute_normals(geo, add_to="point").get(POINT, "N")
    Nw = np.asarray(pn[:, :3], np.float64)
    N[m] = (Nw[tri[t, 0]] * w[:, 0:1] + Nw[tri[t, 1]] * w[:, 1:2]
            + Nw[tri[t, 2]] * w[:, 2:3])
    ln = np.linalg.norm(N, axis=-1, keepdims=True)
    N = N / np.where(ln < 1e-12, 1.0, ln)
    return P, N, m


# ═══════════════════════════════════════════════════════════ forward: texture -> screen
def project_texture(geo, cam, texture, group="", uv_attrib="uv",
                    layer=DEFAULT_LAYER, border="clamp", filter="bilinear",
                    background=0.0, with_mask=True, device="numpy"):
    """
    Renders a uv texture to the screen. The **other half** of the loop, and the best test of back-projection:

        known texture -> project_texture -> back-projection -> should reproduce the original texture

    The two directions take completely different code paths (here screen rasterization + sampling by uv, there uv
    rasterization + sampling by screen), so the round trip tests something real, not the same bug cancelling itself out.
    """
    from .cop import backend as _bk
    rast = _rnd.rasterize(geo, cam, group)
    hit = rast["hit"]
    m = hit >= 0
    H, W = hit.shape
    a = texture.need(layer)
    if not isinstance(a, np.ndarray):
        a = texture.to_device("numpy").need(layer)
    C = int(np.asarray(a).shape[2])
    out = np.full((H, W, C), float(background))
    if m.any():
        uvv = _corner_uv(geo, uv_attrib)
        t = hit[m]
        w = rast["bary"][m]
        cor = rast["cor"]
        uvp = (uvv[cor[t, 0]] * w[:, 0:1] + uvv[cor[t, 1]] * w[:, 1:2]
               + uvv[cor[t, 2]] * w[:, 2:3])
        out[m] = _fm.sample_layer(texture, uvp, layer, border, filter)
    xp = _bk.get(device, W * H, 2, C)
    img = CopImage(W, H)
    img.set(DEFAULT_LAYER, xp.asarray(out.astype(np.float32)))
    if with_mask:
        img.set("mask", xp.asarray(m.astype(np.float32)[:, :, None]))
    return img


# ═══════════════════════════════════════════════════════════ backward: screen -> uv
def backproject(geo, cam, image, accum=None, xres=1024, yres=1024,
                group="", uv_attrib="uv", normal_attrib="N",
                layer=DEFAULT_LAYER, decode="srgb_to_linear",
                facing_power=2.0, facing_min=0.2,
                border_fade=0.05, visibility="triangle+depth",
                depth_bias=0.02, silhouette_guard=1, conservative=0.5,
                weight_scale=1.0, filter="bilinear"):
    """
    Projects a screen image into uv space weighted by visibility + facing, accumulating into accum.

    Returns a CopImage with layers `Csum` (accumulated weight * colour), `Wsum` (accumulated weight),
    `views` (number of views that saw this texel). The actual texture needs one pass of `resolve`.

    The accumulator is separate from the texture so that **multiple views can be chained**: N cameras means N chained nodes, each handling only
    its own contribution. Merged into one "outputs the texture directly" node, the second view could not know
    what weight the first view used on each texel, and overlap regions could only be overwritten.
    """
    rast = uv_rasterize(geo, xres, yres, group, uv_attrib, conservative)
    P, N, m = texel_surface(geo, rast, uv_attrib, normal_attrib)
    H, W = int(yres), int(xres)

    a = image.need(layer)
    if not isinstance(a, np.ndarray):
        a = image.to_device("numpy").need(layer)
    C = int(np.asarray(a).shape[2])

    Csum = np.zeros((H, W, C))
    Wsum = np.zeros((H, W, 1))
    Vcnt = np.zeros((H, W, 1))
    if accum is not None:
        Csum = np.asarray(accum.need(SUM_LAYER), np.float64).copy()
        Wsum = np.asarray(accum.need(WEIGHT_LAYER), np.float64).copy()
        if COUNT_LAYER in accum:
            Vcnt = np.asarray(accum.get(COUNT_LAYER), np.float64).copy()
        if Csum.shape[:2] != (H, W):
            raise ValueError(
                f"The accumulator is {Csum.shape[1]}x{Csum.shape[0]}, this step needs {W}x{H}"
                f" -- all nodes on one back-projection chain must use the same texture resolution.")
        if Csum.shape[2] != C:
            raise ValueError(
                f"The accumulator has {Csum.shape[2]} channels, this image has {C} channels.")

    if not m.any():
        return _pack(W, H, Csum, Wsum, Vcnt)

    sel = np.nonzero(m.reshape(-1))[0]
    Pf = P.reshape(-1, 3)[sel]
    Nf = N.reshape(-1, 3)[sel]
    sx, sy, z = _rnd.project(cam, Pf)

    iw, ih = int(cam["xres"]), int(cam["yres"])
    w = np.ones(len(sel))

    # ── inside the frame + in front of the near plane
    w *= ((sx >= -0.5) & (sx <= iw - 0.5) & (sy >= -0.5) & (sy <= ih - 0.5)
          & (z > max(cam["near"], 1e-9)))

    # ── facing: N . (texel -> camera)
    if cam["projection"] == "perspective":
        vd = cam["eye"][None, :] - Pf
        ln = np.linalg.norm(vd, axis=1, keepdims=True)
        vd = vd / np.where(ln < 1e-12, 1.0, ln)
    else:
        vd = np.broadcast_to(-cam["forward"][None, :], Pf.shape)
    cosang = np.clip((Nf * vd).sum(1), 0.0, 1.0)
    w *= np.where(cosang <= float(facing_min), 0.0,
                  cosang ** float(facing_power))

    # ── border fade: linear fade-out over the border_fade band at the frame's outer edge
    f = float(border_fade)
    if f > 0:
        du = np.minimum(sx + 0.5, iw - 0.5 - sx) / max(iw * f, 1e-9)
        dv = np.minimum(sy + 0.5, ih - 0.5 - sy) / max(ih * f, 1e-9)
        w *= np.clip(np.minimum(du, dv), 0.0, 1.0)

    # ── visibility
    if visibility not in VISIBILITY:
        raise ValueError(f"Visibility must be one of {VISIBILITY}")
    if visibility != "none" or int(silhouette_guard) > 0:
        srast = _rnd.rasterize(geo, cam, group)
        iw2, ih2 = srast["hit"].shape[1], srast["hit"].shape[0]
        xi = np.clip(np.rint(sx).astype(np.int64), 0, iw2 - 1)
        yi = np.clip(np.rint(sy).astype(np.int64), 0, ih2 - 1)
        if visibility != "none":
            # Bias scaled by the bounding sphere radius -- in hard-coded world units a model at a different scale would need retuning
            bias = float(depth_bias) * max(float(cam.get("radius", 1.0)),
                                           1e-9)
            w *= _visible(rast, srast, sel, xi, yi, z, bias, visibility)
        if int(silhouette_guard) > 0:
            w *= _erode(srast["hit"] >= 0,
                        int(silhouette_guard))[yi, xi]

    live = w > 0
    if live.any():
        u = (sx[live] + 0.5) / iw
        v = (sy[live] + 0.5) / ih
        col = _fm.sample_layer(image, np.stack([u, v], 1), layer,
                               "clamp", filter, "", decode)
        ww = (w[live] * float(weight_scale))[:, None]
        np.add.at(Csum.reshape(-1, C), sel[live], col * ww)
        np.add.at(Wsum.reshape(-1, 1), sel[live], ww)
        np.add.at(Vcnt.reshape(-1, 1), sel[live], np.ones_like(ww))
    return _pack(W, H, Csum, Wsum, Vcnt)


def _pack(W, H, Csum, Wsum, Vcnt):
    img = CopImage(W, H)
    img.set(SUM_LAYER, Csum.astype(np.float32))
    img.set(WEIGHT_LAYER, Wsum.astype(np.float32))
    img.set(COUNT_LAYER, Vcnt.astype(np.float32))
    return img


def _visible(rast, srast, sel, xi, yi, z, depth_bias,
             mode="triangle+depth"):
    """
    Visibility. **Triangle number OR depth** -- reasons and measured numbers in the file header.

    Same number = the triangle this texel lies on is exactly the one visible at that pixel; exact,
    no bias needed. Otherwise fall back to the depth comparison. The two are "or", not "and": texels and pixels are not
    one-to-one, and numbers alone misjudge 15% of the visible texels.
    """
    front = srast["hit"][yi, xi]
    mine = rast["hit"].reshape(-1)[sel]
    same = (front == mine)
    near_enough = (front >= 0) & (z <= srast["z"][yi, xi] + float(depth_bias))
    if mode == "triangle":
        vis = same
    elif mode == "depth":
        vis = near_enough
    else:
        vis = same | near_enough
    return vis.astype(np.float64)


def _erode(mask, n):
    """
    Shrinks the coverage mask inward by n pixels -- the **silhouette guard**.

    The ring of pixels on the silhouette is partially covered: rasterization gives it a "hit", but its colour is mixed with the background.
    AI-generated images are likewise least trustworthy at object edges (the edge is where it negotiates with the background). Excluding this ring
    outright costs each view a one-pixel-wide border, and those places are always faced head-on by some other view.

    Measured (6 views, round-trip criterion "known texture -> render -> back-project -> compare", error > 0.05
    counts as bad):

        guard    cube (box uv)            flat grid
        0        5.01%  max error 0.756     0.33%  max 0.497
        1        0.08%  max error 0.449     0.00%  max 2e-5
        2        0.00%  max error 1.2e-7    0.00%  max 2.4e-7

    The cost is coverage: cube 1.000 -> 0.969 -> 0.954. With a single view it is a trade-off; with multiple views
    it is basically free -- what one view drops at its edge, another view always faces head-on.

    The sphere (spherical uv) is **completely insensitive** to the guard; the residual 0.14% stays: measured, of it
    96.7% lies on the two polar caps with |y| > 0.95, where the spherical uv parameterization itself degenerates
    (the whole ring of pole triangles is smeared into a thin long strip in uv); not a back-projection problem.
    """
    m = np.asarray(mask, bool)
    for _ in range(int(n)):
        m = (m & np.roll(m, 1, 0) & np.roll(m, -1, 0)
             & np.roll(m, 1, 1) & np.roll(m, -1, 1))
        m[0, :] = m[-1, :] = False
        m[:, 0] = m[:, -1] = False
    return m.astype(np.float64)


# ═══════════════════════════════════════════════════════════════ finishing
def resolve(accum, layer=DEFAULT_LAYER, encode="none", dilate=4,
            fill_holes=True, background=0.5, min_weight=1e-8,
            device="numpy"):
    """
    Accumulator -> texture. Divide by weight -> dilate -> fill holes.

    Output layers: `C` (texture), `mask` (which texels were actually seen; those produced by dilation and hole filling
    don't count), `views` (how many views saw it -- for diagnosing "is this area held up by
    only one view").
    """
    from .cop import backend as _bk
    Cs = np.asarray(accum.need(SUM_LAYER), np.float64)
    Ws = np.asarray(accum.need(WEIGHT_LAYER), np.float64)
    H, W, C = Cs.shape
    m = (Ws[:, :, 0] > float(min_weight))
    col = np.where(m[:, :, None], Cs / np.where(Ws > 0, Ws, 1.0),
                   float(background))

    if int(dilate) > 0:
        col, filled = _dilate(col, m, int(dilate))
    else:
        filled = m
    if fill_holes and not filled.all():
        col = _push_pull(col, filled)

    if encode == "srgb":
        col = _fm.srgb_encode(np.clip(col, 0.0, None))
    elif encode == "linear":
        col = _fm.srgb_decode(col)

    xp = _bk.get(device, W * H, 3, C)
    out = CopImage(W, H)
    out.set(str(layer).strip() or DEFAULT_LAYER,
            xp.asarray(col.astype(np.float32)))
    out.set("mask", xp.asarray(m.astype(np.float32)[:, :, None]))
    if COUNT_LAYER in accum:
        out.set(COUNT_LAYER, xp.asarray(
            np.asarray(accum.get(COUNT_LAYER), np.float32)))
    return out


def _dilate(col, mask, n):
    """
    Pushes n rings outward from the uv islands (gutter). Each round fills a ring with the average of valued 4-neighbours.

    Without it bilinear sampling picks up the background colour at island edges -- more visible at low mips, because one
    texel mixes in background from farther and farther away.
    """
    c = col.copy()
    m = mask.copy()
    H, W = m.shape
    for _ in range(n):
        # Only compute this ring (pixels without a value but with valued neighbours): a 4096x1024 image has tens of thousands of points per ring,
        # no need to roll the whole image eight times as before (that was the bulk of the bake time). Image edges don't wrap around:
        # the left and right sides of an atlas are unrelated islands, wrapping would bleed in colour from the opposite side
        mp = np.pad(m, 1)
        k = (mp[:-2, 1:-1].astype(np.int8) + mp[2:, 1:-1] + mp[1:-1, :-2]
             + mp[1:-1, 2:])
        new = (~m) & (k > 0)
        if not new.any():             # purely a speed-up: filled / nothing left to grow (without the break it would just spin idle)
            break
        ys, xs = np.nonzero(new)
        s = np.zeros((len(ys), c.shape[2]))
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = ys + dy, xs + dx
            ok = (yy >= 0) & (yy < H) & (xx >= 0) & (xx < W)
            ok[ok] = m[yy[ok], xx[ok]]
            s[ok] += c[yy[ok], xx[ok]]
        c[ys, xs] = s / k[ys, xs][:, None]
        m[ys, xs] = True
    return c, m


def _push_pull(col, mask):
    """
    Push-pull hole filling. Weighted downsampling into a pyramid, then upsampling back level by level to fill holes.

    O(n) and the fill is smooth; round-by-round dilation needs as many rounds as the hole's radius, and on large holes it is both slow
    and leaves concentric rings.
    """
    H, W, C = col.shape
    w = mask.astype(np.float64)[:, :, None]
    levels = [(col * w, w)]
    # Stop only when both directions have shrunk to 1. Previously it stopped when either side reached 1: a non-square image (1024x64) stopped at 16x1,
    # top-level positions whose whole cell had no valid pixels = 0, and large holes got pulled towards 0 (black)
    while levels[-1][0].shape[0] > 1 or levels[-1][0].shape[1] > 1:
        cw, ww = levels[-1]
        cw = _down(cw)
        ww = _down(ww)
        levels.append((cw, ww))
    cw, ww = levels[-1]
    up = np.where(ww > 0, cw / np.where(ww > 0, ww, 1.0), 0.0)
    for i in range(len(levels) - 2, -1, -1):
        cw, ww = levels[i]
        h, wd = cw.shape[0], cw.shape[1]
        coarse = _up(up, h, wd)
        fine = np.where(ww > 0, cw / np.where(ww > 0, ww, 1.0), 0.0)
        up = np.where(ww > 0, fine, coarse)
    return np.where(mask[:, :, None], col, up)


def _down(a):
    """2x2 sum downsampling (odd sides padded)."""
    h, w = a.shape[0], a.shape[1]
    if h % 2:
        a = np.concatenate([a, a[-1:]], 0); h += 1
    if w % 2:
        a = np.concatenate([a, a[:, -1:]], 1); w += 1
    return (a[0::2, 0::2] + a[1::2, 0::2]
            + a[0::2, 1::2] + a[1::2, 1::2]) * 0.25


def _up(a, h, w):
    """
    **Bilinear** upsampling to (h,w), converted by pixel centres.

    The first version was nearest neighbour (np.repeat twice); filled holes were blocky 2^k-sized squares,
    with obvious steps. Each pyramid level up doubles the step, so it is most visible on large holes, and large holes are exactly
    why this function exists. Measured 99.9th percentile of the gradient between adjacent texels inside holes:

        nearest   0.837
        bilinear  0.0088      <- 95 times smaller

    (A percentile rather than the maximum, because the wrap seams of a texture atlas genuinely have real jumps.)
    """
    H2, W2 = a.shape[0], a.shape[1]
    x = (np.arange(w) + 0.5) * (W2 / float(w)) - 0.5
    y = (np.arange(h) + 0.5) * (H2 / float(h)) - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[None, :, None]
    fy = (y - y0)[:, None, None]
    x1 = np.clip(x0 + 1, 0, W2 - 1)
    y1 = np.clip(y0 + 1, 0, H2 - 1)
    x0 = np.clip(x0, 0, W2 - 1)
    y0 = np.clip(y0, 0, H2 - 1)
    return (a[np.ix_(y0, x0)] * (1 - fy) * (1 - fx)
            + a[np.ix_(y0, x1)] * (1 - fy) * fx
            + a[np.ix_(y1, x0)] * fy * (1 - fx)
            + a[np.ix_(y1, x1)] * fy * fx)


def coverage(accum, min_weight=1e-8):
    """Fraction of texels seen by at least one view -- the most direct number for judging "are views still missing"."""
    Ws = np.asarray(accum.need(WEIGHT_LAYER), np.float64)
    return float((Ws[:, :, 0] > float(min_weight)).mean())
