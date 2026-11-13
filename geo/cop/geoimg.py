"""
Geometry <-> image (half of batch F): Layer to Points / Point Generate, Points from Blobs,
Rasterize Curves (Layer / Mask from Curves), Rasterize GSplats, Bake Geometry
Textures.

All coordinate conventions go through `stamp.frame / to_uv / from_uv` (see the stamp.py header): xz plane +
world mode, strictly consistent with HeightField to Mesh, so "image -> points -> stamped back onto the image" is closed;
the tests pin this down.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, check_res
from .pattern import _base, rnd
from .pixel import getn, put, _vec
from .stamp import frame, to_uv, from_uv, PLANES, MAPPINGS
from ..core import Geometry, POINT

# The first two modes are the plugin's originals; the last five are Houdini Layer to Points' Method (All Pixel is the pixels mode
# without a mask and with Stride 1, so it didn't get its own mode). Append only at the end (workflows save the value by token).
POINT_MODES = ("pixels", "scatter", "nonzero", "count_per_pixel", "unique_values",
               "count_first", "count_last")
# These modes take points from "source pixels", reading the Mask Layer layer (empty = C) as Houdini's input layer
_HOU_MODES = POINT_MODES[2:]


def _attr_name(layer):
    """The C layer is written as Cd (Houdini's colour attribute name); the rest keep their names."""
    return "Cd" if layer == "C" else layer


def _gather(img, layers, ii, jj):
    out = {}
    for n in [x for x in str(layers).split() if x]:
        a = getn(img, n)
        out[_attr_name(n)] = a[ii, jj]
    return out


# ═══════════════════════════════════════════════════════════ image -> points
def layer_to_points(img, mode="pixels", mask_layer="", threshold=0.5,
                    stride=1, count=1000, density_layer="", height_layer="",
                    height_scale=1.0, attribs="C", plane="xz", world_size=1.0,
                    jitter=0.0, seed=0, layer_attrib="", index_attrib="",
                    set_positions=True, ignore_minus_one=True):
    """
    Layer to Points / Point Generate.
      pixels   one point per pixel centre (Stride skips some), only where Mask Layer >
               Threshold
      scatter  scatters Count random points by Density Layer (uniform if not given), positions
               continuous within the pixel (not only at pixel centres)
    Position: plane + world mapping (consistent with HeightField to Mesh, image width = World Size);
    if a Height Layer is given, the axis out of the plane is set to value x Height Scale (Y for the xz plane).
    Layers listed in Attribs are sampled per point into attributes (C -> Cd), and uv (the point's uv on the image) is also written.

    Houdini's Method (source layer = Mask Layer, empty = C; multi-channel layers use channel 0 as the "value",
    only nonzero looks at all channels):
      nonzero          one point per pixel whose value is not 0
      count_per_pixel  each pixel emits floor(value) points (negative counts as 0; the docs don't say how fractions round)
      unique_values    one point per distinct value, placed at the pixel where it **first appears** (in buffer-offset
                       x + y*xres order; the docs don't say where or in what order, so this is our choice);
                       with Ignore Minus One on, -1 is not counted
      count_first / count_last
                       the value of the first / last pixel (offset 0 / xres*yres - 1), floored, is the
                       total point count. These points have no corresponding pixel position (the docs only say "determines the point count"),
                       P is always placed at the origin, uv / attributes come from that source pixel
    Layer Attrib / Index Attrib (empty = not written): integer point attributes, the source pixel's value (rint) / offset
    x + y*xres (our row 0 is the bottom, matching Houdini's buffer). Set Positions off: P is all 0
    (Height Layer not read), uv is still written.
    """
    if img is None:
        return Geometry()
    if mode not in POINT_MODES:
        raise ValueError(f"Mode must be one of {POINT_MODES}")
    if plane not in PLANES:
        raise ValueError(f"Plane must be one of {PLANES}")
    W, H = img.xres, img.yres
    fr = frame(None, W, H, plane, "world", world_size)
    nojit = False
    if mode in _HOU_MODES:
        ii, jj, key = _hou_pixels(img, mode, mask_layer, ignore_minus_one)
        uv = np.stack([(jj + 0.5) / W, (ii + 0.5) / H], -1)
        nojit = mode in ("count_first", "count_last")
        if float(jitter) > 0 and not nojit:
            # When one pixel emits several points (count_per_pixel), the random number is keyed by point index, otherwise they all stack up
            uv = uv + (np.stack([rnd(key, seed, 1), rnd(key, seed, 2)], -1)
                       - 0.5) * float(jitter) / np.array([W, H])
    elif mode == "pixels":
        s = max(1, int(stride))
        I, J = np.mgrid[0:H:s, 0:W:s]
        ii, jj = I.ravel(), J.ravel()
        if str(mask_layer).strip():
            keep = getn(img, mask_layer)[ii, jj, 0] > float(threshold)
            ii, jj = ii[keep], jj[keep]
        uv = np.stack([(jj + 0.5) / W, (ii + 0.5) / H], -1)
        if float(jitter) > 0:
            k = ii * W + jj
            uv = uv + (np.stack([rnd(k, seed, 1), rnd(k, seed, 2)], -1)
                       - 0.5) * float(jitter) * s / np.array([W, H])
    else:
        n = int(count)
        k = np.arange(n * 8)
        u = rnd(k, seed, 1)
        v = rnd(k, seed, 2)
        if str(density_layer).strip():
            d = np.clip(getn(img, density_layer)[..., 0], 0, None)
            dm = max(float(d.max()), 1e-12)
            jj0 = np.clip((u * W).astype(int), 0, W - 1)
            ii0 = np.clip((v * H).astype(int), 0, H - 1)
            acc = rnd(k, seed, 3) * dm < d[ii0, jj0]
            u, v = u[acc], v[acc]
        u, v = u[:n], v[:n]
        uv = np.stack([u, v], -1)
        jj = np.clip((u * W).astype(int), 0, W - 1)
        ii = np.clip((v * H).astype(int), 0, H - 1)
    if nojit or not set_positions:
        P = np.zeros((len(uv), 3))
    else:
        h = None
        if str(height_layer).strip():
            from .filters import sample
            h = sample(getn(img, height_layer), uv[:, 0], uv[:, 1],
                       "clamp")[:, 0] * float(height_scale)
        P = from_uv(uv, W, H, plane, fr, h)
    g = Geometry.from_points(P.astype(np.float32))
    g.set(POINT, "uv", uv.astype(np.float32))
    for nm, val in _gather(img, attribs, ii, jj).items():
        g.set(POINT, nm, np.asarray(val, np.float32))
    if str(layer_attrib).strip():
        v = getn(img, mask_layer)[ii, jj, 0]
        g.set(POINT, str(layer_attrib).strip(), np.rint(v).astype(np.int32))
    if str(index_attrib).strip():
        g.set(POINT, str(index_attrib).strip(),
              (jj + ii * W).astype(np.int32))
    return g


def _hou_pixels(img, mode, layer, ignore_minus_one):
    """
    Houdini Method modes -> (rows ii, columns jj, per-point random key).
    Order is always ascending buffer offset x + y*xres (row 0 at the bottom).
    """
    a = getn(img, layer)
    W, H = img.xres, img.yres
    v = a[..., 0].ravel()                       # offset = jj + ii*W is exactly the C-order flattening
    off = np.arange(W * H)
    if mode == "nonzero":
        sel = off[(a != 0).any(-1).ravel()]
    elif mode == "count_per_pixel":
        n = np.floor(np.clip(np.nan_to_num(v), 0, None)).astype(np.int64)
        sel = np.repeat(off, n)
    elif mode == "unique_values":
        ok = ~(v == -1) if ignore_minus_one else np.ones(v.size, bool)
        _, first = np.unique(v[ok], return_index=True)
        sel = np.sort(off[ok][first])
    else:                                       # count_first / count_last
        src = 0 if mode == "count_first" else W * H - 1
        n = int(np.floor(max(float(np.nan_to_num(v[src])), 0.0)))
        sel = np.full(n, src, np.int64)
    sel = np.asarray(sel, np.int64)
    return sel // W, sel % W, np.arange(sel.size)


def points_from_blobs(img, layer="mask", threshold=0.5, connectivity=8,
                      min_area=1, value_layer="", plane="xz",
                      world_size=1.0, height_layer="", height_scale=1.0):
    """
    Points from Blobs: one point per connected piece of the mask, placed at the piece's **centroid** (average of pixel
    centres). Attributes: area (pixel count), world_area (square units), radius (radius of the equal-area circle,
    in world units -- use it as pscale), blob_id (by descending area, from 1), bbox (uv
    x0 y0 x1 y1); if a Value Layer is given, its mean within the piece is also written (C -> Cd).
    """
    if img is None:
        return Geometry(), 0
    from .analysis import label
    W, H = img.xres, img.yres
    m = getn(img, layer)[..., 0] > float(threshold)
    lab = label(m, int(connectivity))
    K = int(lab.max())
    fr = frame(None, W, H, plane, "world", world_size)
    I, J = np.mgrid[0:H, 0:W]
    flat = lab.ravel()
    area = np.bincount(flat, minlength=K + 1)[1:].astype(np.float64)
    cx = np.bincount(flat, (J.ravel() + 0.5), K + 1)[1:] / np.maximum(area, 1)
    cy = np.bincount(flat, (I.ravel() + 0.5), K + 1)[1:] / np.maximum(area, 1)
    keep = area >= int(min_area)
    idx = np.nonzero(keep)[0]
    uv = np.stack([cx[idx] / W, cy[idx] / H], -1)
    h = None
    if str(height_layer).strip():
        hv = getn(img, height_layer)[..., 0].ravel()
        h = (np.bincount(flat, hv, K + 1)[1:] / np.maximum(area, 1))[idx] \
            * float(height_scale)
    P = from_uv(uv, W, H, plane, fr, h)
    g = Geometry.from_points(P.astype(np.float32))
    px_area = (fr[2] / W) * (fr[3] / H)
    g.set(POINT, "area", area[idx].astype(np.float32))
    g.set(POINT, "world_area", (area[idx] * px_area).astype(np.float32))
    g.set(POINT, "radius", np.sqrt(area[idx] * px_area / math.pi)
          .astype(np.float32))
    g.set(POINT, "blob_id", (idx + 1).astype(np.int32))
    g.set(POINT, "uv", uv.astype(np.float32))
    bb = np.zeros((len(idx), 4))
    for n_, k in enumerate(idx):
        ys, xs = np.nonzero(lab == k + 1)
        bb[n_] = [xs.min() / W, ys.min() / H, (xs.max() + 1) / W,
                  (ys.max() + 1) / H]
    g.set(POINT, "bbox", bb.astype(np.float32))
    if str(value_layer).strip():
        a = getn(img, value_layer)
        C = a.shape[2]
        mv = np.stack([np.bincount(flat, a[..., c].ravel(), K + 1)[1:]
                       / np.maximum(area, 1) for c in range(C)], -1)[idx]
        g.set(POINT, _attr_name(value_layer), mv.astype(np.float32))
    return g, int(len(idx))


# ═══════════════════════════════════════════════════════════ curves -> image
def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from point to segment and segment parameter t in [0, 1]."""
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / np.where(ll > 0, ll, 1),
                0, 1)
    qx, qy = ax + t * dx - px, ay + t * dy - py
    return np.sqrt(qx * qx + qy * qy), t


def rasterize_curves(img=None, geo=None, width=2.0, width_attrib="",
                     fill=False, attrib="", plane="xz", mapping="world",
                     world_size=1.0, out_layer="curves", xres=512, yres=512):
    """
    Rasterize Curves / Layer from Curves / Mask from Curves. Each prim in the geometry is treated as
    a polyline (closed ones joined end to start), drawn as an anti-aliased line by pixel distance: coverage =
    clamp(Width/2 - d + 1/2). Width is in pixels; if Width Attrib is given (e.g. pscale / width)
    it is multiplied per point, interpolated linearly along the segment.
    Fill: closed prims are filled inside as well (even-odd rule) -- Mask from Curves.
    Attrib: interpolates this point attribute along the line and writes it as out_layer_attr (from the segment nearest the pixel).
    """
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    cov = np.zeros((H, W), np.float32)
    if geo is None or geo.npoints == 0:
        put(out, str(out_layer).strip() or "curves", cov, like)
        return out
    P = geo.get(POINT, "P")
    fr = frame(P, W, H, plane, mapping, world_size)
    uv = to_uv(P, W, H, plane, fr=fr)
    px = uv[:, 0] * W - 0.5                         # pixel index coordinates
    py = uv[:, 1] * H - 0.5
    wa = str(width_attrib).strip()
    wmul = np.ones(len(P))
    if wa:
        w_ = geo.get(POINT, wa)
        if w_ is None:
            raise ValueError(f"Geometry has no point attribute '{wa}'")
        wmul = np.asarray(w_, np.float64).reshape(len(P), -1)[:, 0]
    at = str(attrib).strip()
    av = None
    if at:
        a_ = geo.get(POINT, at)
        if a_ is None:
            raise ValueError(f"Geometry has no point attribute '{at}'")
        av = np.asarray(a_, np.float64).reshape(len(P), -1)
        attr = np.zeros((H, W, av.shape[1]), np.float32)
        best = np.full((H, W), np.inf, np.float32)
    inside = np.zeros((H, W), bool) if fill else None
    # pixel-coordinate grids are made per window (a full-image pair was 270 MB at 4096², for a few pixels per segment)

    def grid(y0, y1, x0, x1):
        return np.meshgrid(np.arange(x0, x1, dtype=np.float64), np.arange(y0, y1, dtype=np.float64))
    for pi in range(geo.nprims):
        idx = np.asarray(geo.prim_points(pi))
        if idx.size < 2:
            continue
        closed = bool(geo.prim_closed[pi]) and idx.size > 2
        segs = list(zip(idx[:-1], idx[1:])) + ([(idx[-1], idx[0])] if closed
                                               else [])
        if fill and closed:
            # Even-odd rule: cast a ray from the pixel centre towards +x and count crossings with edges (within the
            # polygon's bounding box: nothing outside it is inside)
            by0 = int(max(math.floor(py[idx].min()), 0))
            by1 = int(min(math.ceil(py[idx].max()) + 1, H))
            bx0 = int(max(math.floor(px[idx].min()), 0))
            bx1 = int(min(math.ceil(px[idx].max()) + 1, W))
            if by0 < by1 and bx0 < bx1:
                J, I = grid(by0, by1, bx0, bx1)
                cnt = np.zeros(J.shape, np.int64)
                for a, b in segs:
                    ya, yb = py[a], py[b]
                    if ya == yb:
                        continue
                    crs = ((I >= min(ya, yb)) & (I < max(ya, yb)))
                    xt = px[a] + (I - ya) / (yb - ya) * (px[b] - px[a])
                    cnt += crs & (xt > J)
                inside[by0:by1, bx0:bx1] ^= (cnt % 2 == 1)
        for a, b in segs:
            hw = 0.5 * float(width) * max(wmul[a], wmul[b]) + 1.5
            x0 = int(max(math.floor(min(px[a], px[b]) - hw), 0))
            x1 = int(min(math.ceil(max(px[a], px[b]) + hw) + 1, W))
            y0 = int(max(math.floor(min(py[a], py[b]) - hw), 0))
            y1 = int(min(math.ceil(max(py[a], py[b]) + hw) + 1, H))
            if x0 >= x1 or y0 >= y1:
                continue
            sj, si = grid(y0, y1, x0, x1)
            d, t = _seg_dist(sj, si, px[a], py[a], px[b], py[b])
            wl = float(width) * (wmul[a] * (1 - t) + wmul[b] * t)
            c = np.clip(wl * 0.5 - d + 0.5, 0, 1)
            sl = (slice(y0, y1), slice(x0, x1))
            cov[sl] = np.maximum(cov[sl], c)
            if av is not None:
                closer = d < best[sl]
                val = av[a][None, None, :] * (1 - t[..., None]) \
                    + av[b][None, None, :] * t[..., None]
                attr[sl] = np.where(closer[..., None], val, attr[sl])
                best[sl] = np.where(closer, d, best[sl])
    if inside is not None:
        cov = np.maximum(cov, inside.astype(np.float32))
    name = str(out_layer).strip() or "curves"
    put(out, name, cov, like)
    if av is not None:
        put(out, f"{name}_{at}", attr, like)
    return out


# ═══════════════════════════════════════════════════════════ Gaussian splats
def _quat_to_mat(q):
    """(n,4) quaternion (x, y, z, w) -> (n,3,3). Houdini's orient convention."""
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w),
                  2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z),
                  2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w),
                  1 - 2 * (x * x + y * y)], -1)], 1)


def rasterize_splats(img=None, geo=None, plane="xz", mapping="world",
                     world_size=1.0, scale_mult=1.0, opacity_mult=1.0,
                     cutoff=3.0, background="0 0 0", out_layer="C",
                     xres=512, yres=512):
    """
    Rasterize GSplats: 3D Gaussian splats (3DGS convention: P, scale (3, standard deviations), orient
    (quaternion xyzw), Cd, opacity) projected **orthographically** onto plane. Covariance Sigma = R*S^2*R^T;
    after projection take the 2x2 block on the plane; alpha-composite **front to back** sorted along the axis out of the plane
    (the xz plane looks down from +Y, near = larger Y).

    Missing attributes: scale uses pscale (isotropic), orient uses the identity quaternion, Cd uses white, opacity
    uses 1. Cutoff is the truncation in sigmas. Outputs out_layer (RGB) and out_layer_alpha.
    There is no perspective projection and no SH view-dependent colour here -- orthographic baking onto a plane (for textures / top views) is enough;
    for portrait-style views use a dedicated 3DGS renderer.
    """
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    rgb = np.zeros((H, W, 3))
    T = np.ones((H, W))                               # remaining transmittance
    name = str(out_layer).strip() or "C"
    if geo is None or geo.npoints == 0:
        bg = _vec(background, 3)
        put(out, name, np.broadcast_to(bg, (H, W, 3)), like)
        put(out, name + "_alpha", np.zeros((H, W)), like)
        return out, 0
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    n = len(P)
    sc = geo.get(POINT, "scale")
    if sc is not None:
        sc = np.asarray(sc, np.float64).reshape(n, -1)
        if sc.shape[1] == 1:
            sc = np.repeat(sc, 3, 1)
    else:
        ps = geo.get(POINT, "pscale")
        base = np.asarray(ps, np.float64).reshape(n) if ps is not None \
            else np.full(n, 0.01)
        sc = np.repeat(base[:, None], 3, 1)
    sc = sc * float(scale_mult)
    ori = geo.get(POINT, "orient")
    R = _quat_to_mat(np.asarray(ori, np.float64).reshape(n, 4)) \
        if ori is not None else np.repeat(np.eye(3)[None], n, 0)
    cd = geo.get(POINT, "Cd")
    col = np.asarray(cd, np.float64).reshape(n, -1)[:, :3] if cd is not None \
        else np.ones((n, 3))
    op = geo.get(POINT, "opacity")
    alpha = np.asarray(op, np.float64).reshape(n) if op is not None \
        else np.ones(n)
    alpha = np.clip(alpha * float(opacity_mult), 0, 1)
    Sig = R @ (np.eye(3)[None] * (sc ** 2)[:, None, :]) @ np.transpose(
        R, (0, 2, 1))
    # Plane coordinates (a, b) and the "depth" axis, consistent with stamp._plane_ab
    if plane == "xz":
        ia, ib, id_, sa, sb, sd = 0, 2, 1, 1.0, -1.0, 1.0
    elif plane == "xy":
        ia, ib, id_, sa, sb, sd = 0, 1, 2, 1.0, 1.0, 1.0
    elif plane == "zy":
        ia, ib, id_, sa, sb, sd = 2, 1, 0, 1.0, 1.0, 1.0
    else:
        raise ValueError(f"Plane must be one of {PLANES}")
    fr = frame(P, W, H, plane, mapping, world_size)
    uv = to_uv(P, W, H, plane, fr=fr)
    ppu = W / fr[2]                                   # pixels per world unit
    cxp, cyp = uv[:, 0] * W - 0.5, uv[:, 1] * H - 0.5
    A = np.array([sa, sb])
    S2 = np.stack([np.stack([Sig[:, ia, ia], Sig[:, ia, ib]], -1),
                   np.stack([Sig[:, ib, ia], Sig[:, ib, ib]], -1)], 1)
    S2 = S2 * (A[None, :, None] * A[None, None, :]) * ppu * ppu
    order = np.argsort(-P[:, id_] * sd, kind="stable")   # nearest drawn first
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    drawn = 0
    for k in order:
        s = S2[k] + np.eye(2) * 0.09                  # anti-aliasing: add a 0.3-pixel floor
        det = s[0, 0] * s[1, 1] - s[0, 1] ** 2
        if det <= 0:
            continue
        inv = np.array([[s[1, 1], -s[0, 1]], [-s[0, 1], s[0, 0]]]) / det
        rx = float(cutoff) * math.sqrt(s[0, 0])
        ry = float(cutoff) * math.sqrt(s[1, 1])
        x0 = int(max(math.floor(cxp[k] - rx), 0))
        x1 = int(min(math.ceil(cxp[k] + rx) + 1, W))
        y0 = int(max(math.floor(cyp[k] - ry), 0))
        y1 = int(min(math.ceil(cyp[k] + ry) + 1, H))
        if x0 >= x1 or y0 >= y1:
            continue
        dx = J[y0:y1, x0:x1] - cxp[k]
        dy = I[y0:y1, x0:x1] - cyp[k]
        q = inv[0, 0] * dx * dx + 2 * inv[0, 1] * dx * dy + inv[1, 1] * dy * dy
        a = alpha[k] * np.exp(-0.5 * q) * (q <= float(cutoff) ** 2)
        sl = (slice(y0, y1), slice(x0, x1))
        rgb[sl] += (T[sl] * a)[..., None] * col[k]
        T[sl] *= (1 - a)
        drawn += 1
    bg = _vec(background, 3)
    rgb = rgb + T[..., None] * bg
    put(out, name, rgb, like)
    put(out, name + "_alpha", 1 - T, like)
    return out, drawn


# ═══════════════════════════════════════════════════════════ bake
BAKE_LAYERS = ("P", "N", "mask", "primid", "tangent", "bitangent", "normal_ts",
               "displacement", "high_attr")


BAKE_TRACING = ("surface_normal", "cage_mesh", "single_mesh")
BAKE_CULL = ("none", "back", "front")
BAKE_NSPACE = ("signed", "offset")
BAKE_PSPACE = ("absolute", "relative")
BAKE_BBOX = ("fit", "uniform")
BAKE_HSPACE = ("true_displacement", "custom")
_CULL = {"none": 0, "back": 1, "front": -1}


def _hemi_dirs(N, k, ns, seed):
    """
    Each normal N (n,3) is paired with the k-th cosine-weighted hemisphere direction (Malley: uniform points on the unit disk lifted to the hemisphere).
    Random numbers are hashed by (point number, sample number), bit-for-bit reproducible.
    """
    n = len(N)
    key = np.arange(n, dtype=np.int64) * int(ns) + int(k)
    u1, u2 = rnd(key, seed, 1), rnd(key, seed, 2)
    r, ph = np.sqrt(u1), 2 * math.pi * u2
    x, y = r * np.cos(ph), r * np.sin(ph)
    z = np.sqrt(np.maximum(1 - u1, 0))
    a = np.where((np.abs(N[:, 0]) < 0.9)[:, None], [1.0, 0, 0], [0, 1.0, 0])
    T = np.cross(a, N)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-30)
    B = np.cross(N, T)
    return T * x[:, None] + B * y[:, None] + N * z[:, None]


def _occlusion(Pp, Nn, VP, vtri, samples, max_dist, cull, seed=0):
    """
    Ambient occlusion: each point casts samples rays over the cosine-weighted hemisphere; result = unoccluded fraction (1 = fully lit).
    The origin is offset along the normal by 1e-4 x the bounding-box diagonal to avoid self-hits. Max Distance 0 = unlimited.
    """
    from ..spatial import ray_cast
    n = len(Pp)
    if not n or samples < 1:
        return np.ones(n)
    diag = float(np.linalg.norm(VP.max(0) - VP.min(0))) or 1.0
    O = Pp + Nn * (1e-4 * diag)
    free = np.zeros(n)
    for k in range(int(samples)):
        D = _hemi_dirs(Nn, k, samples, seed)
        hit, _, _ = ray_cast(O, D, VP, vtri, False, float(max_dist), False, cull)
        free += hit < 0
    return free / int(samples)


def bake_textures(low, high=None, xres=512, yres=512, uv_attrib="uv",
                  attribs="", high_attribs="", max_distance=0.0,
                  both_sides=True, dilate=4, tracing_mode="surface_normal",
                  cage=None, face_culling="none", visibility_culling="none",
                  ray_bias=0.0, normal_space="signed", world_normal=False,
                  world_normal_space="signed", position=False,
                  position_space="absolute", bounding_box="fit", occlusion=False,
                  occlusion_samples=16, occlusion_max_distance=0.0,
                  sample_multiplier=1.0, height=False, height_space="true_displacement",
                  inner_distance=-0.1, outer_distance=0.1, alpha=False,
                  alpha_mask_high=False):
    """
    Bake Geometry Textures / Bake Pre-Process. Rasterizes by the low mesh's uv; each texel looks up
    its position / normal on low, and outputs:

      P / N          world position, world normal (point normals interpolated, computed if absent)
      mask           whether the texel is covered by a triangle
      primid         which original prim it belongs to
      tangent        tangent (dP/du Gram-Schmidt against N)
      bitangent      w * (N x T) with the handedness w of the uv layout (pcg110): the third axis of the tangent frame, so
                     detail computed in texture space can be written into normal_ts's frame exactly
      those in attribs  low's point attributes interpolated barycentrically (original names, C written as Cd and the like)

    If high (the high-poly mesh) is given, rays are cast from each texel along +/-N to find the high-poly surface (Max Distance 0 =
    unlimited):
      normal_ts      high-poly normal in the low-poly tangent space (T, B, N) -- a tangent-space
                     normal map (unencoded, -1..1; for engine use, connect COP Convert Normal /
                     Control Image to encode it)
      displacement   signed distance along N (positive when the high poly is outside)
      high_attribs   high-poly point attributes interpolated at the hit point

    Dilate: grows outward along uv islands by a few texels (Bake Pre-Process padding), to prevent mipmap
    bleeding. mask is not dilated. Returns (image, report).

    Houdini parameters added in pcg100 c8 (defaults = the original behaviour):
      tracing_mode   surface_normal: along +/-N as above; cage_mesh: from the corresponding point on cage (same point numbers
                     and topology as low) cast a one-way ray **towards that point on the low poly**; single_mesh: no primary rays,
                     the high poly is the low poly (only maps like AO make sense; normal_ts / displacement are not output)
      face_culling   primary rays ignore hits on back / front faces (the cull of spatial.ray_cast)
      ray_bias       under surface_normal the ray origin is pushed out this far along N; displacement is still measured from the low-poly surface
      normal_space   encoding of normal_ts: signed (-1..1) / offset (x0.5 + 0.5)
      world_normal   outputs a worldnormal layer: the high poly's interpolated normal at the hit point (no hit / no high poly -> low-poly N)
      position       outputs a position layer: world position of the hit point (no hit / no high poly -> low-poly surface point);
                     when relative, normalized by the **low-poly** bounding box: fit scales each axis independently to 0..1,
                     uniform uses the longest axis with the bounding-box centre at 0.5 (no stretching)
      occlusion      outputs an occlusion layer: cosine-weighted hemisphere rays from the worldnormal point and normal,
                     unoccluded fraction (1 = lit); rays hit the high poly (the low poly for single_mesh / no high poly connected),
                     visibility_culling applies to these secondary rays; samples x sample_multiplier
      height         outputs a height layer: true_displacement = displacement; custom =
                     (d - inner) / (outer - inner) (inner -> 0, outer -> 1, not clamped)
      alpha          outputs an alpha layer: low-poly uv coverage (= mask); with alpha_mask_high on only texels where the primary ray
                     hit the high poly are 1
    These new layers go through Dilate just like the old ones.
    """
    from ..backproject import uv_rasterize, texel_surface, _dilate
    check_res(xres, yres)
    for v, ok, nm in ((tracing_mode, BAKE_TRACING, "Tracing Mode"),
                      (face_culling, BAKE_CULL, "Face Culling"),
                      (visibility_culling, BAKE_CULL, "Visibility Culling"),
                      (normal_space, BAKE_NSPACE, "Normal Space"),
                      (world_normal_space, BAKE_NSPACE, "World Normal Space"),
                      (position_space, BAKE_PSPACE, "Position Space"),
                      (bounding_box, BAKE_BBOX, "Bounding Box"),
                      (height_space, BAKE_HSPACE, "Height Space")):
        if v not in ok:
            raise ValueError(f"{nm} must be one of {ok}")
    W, H = int(xres), int(yres)
    if low is None or low.nprims == 0:
        raise ValueError("Low geometry is empty")
    single = tracing_mode == "single_mesh"
    if tracing_mode == "cage_mesh":
        if cage is None or cage.npoints != low.npoints:
            raise ValueError("Cage Mesh needs the cage input connected, with the same point count / topology as the low poly "
                             f"(low poly {low.npoints} points, cage "
                             f"{'not connected' if cage is None else cage.npoints})")
        if high is None or not high.nprims:
            raise ValueError("Cage Mesh needs a high poly connected")
    rast = uv_rasterize(low, W, H, "", uv_attrib)
    Pm, Nm, m = texel_surface(low, rast, uv_attrib)
    hit, bary, tri, src = rast["hit"], rast["bary"], rast["tri"], rast["src"]
    out = CopImage(W, H)
    rep = {"texels": int(m.sum())}
    lay = {"P": Pm, "N": Nm}
    pid = np.full((H, W), -1.0)
    pid[m] = src[hit[m]]
    # Normals / tangents use the **per-corner** set (meshexport.corner_frames), interpolated barycentrically --
    # the same numbers Export Mesh writes into the file as NORMAL / TANGENT. Previously each triangle computed its own
    # dP/du, the tangent jumped across triangle edges, and the baked map in the engine (which interpolates vertex tangents)
    # showed a thin seam on every edge. vertex N (hard edges) is honoured as well.
    from ..meshexport import corner_frames
    Nc, T4 = corner_frames(low, uv_attrib, tri, rast["cor"])
    corm = rast["cor"][hit[m]]
    wb = bary[m]
    nn = (Nc[corm[:, 0]] * wb[:, 0:1] + Nc[corm[:, 1]] * wb[:, 1:2]
          + Nc[corm[:, 2]] * wb[:, 2:3])
    nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12)
    Nm = np.zeros((H, W, 3))
    Nm[m] = nn
    lay["N"] = Nm
    tt = (T4[corm[:, 0], :3] * wb[:, 0:1] + T4[corm[:, 1], :3] * wb[:, 1:2]
          + T4[corm[:, 2], :3] * wb[:, 2:3])
    T = np.zeros((H, W, 3))
    T[m] = tt
    # Gram-Schmidt: T perpendicular to N; B = w * (N x T), w is the handedness stored on the corner (same for all three corners of a triangle)
    T = T - (T * Nm).sum(-1, keepdims=True) * Nm
    T /= np.maximum(np.linalg.norm(T, axis=-1, keepdims=True), 1e-12)
    hand = np.zeros((H, W, 1))
    hand[m] = T4[corm[:, 0], 3:4]
    Bc = np.cross(Nm, T) * np.where(hand == 0, 1.0, hand)
    lay["tangent"] = T
    lay["bitangent"] = Bc
    for nm in [x for x in str(attribs).split() if x]:
        a = low.get(POINT, nm)
        if a is None:
            raise ValueError(f"Low poly has no point attribute '{nm}'")
        a = np.asarray(a, np.float64).reshape(low.npoints, -1)
        v = np.zeros((H, W, a.shape[1]))
        t = hit[m]
        w = bary[m]
        v[m] = (a[tri[t, 0]] * w[:, 0:1] + a[tri[t, 1]] * w[:, 1:2]
                + a[tri[t, 2]] * w[:, 2:3])
        lay[nm] = v
    # Origin / normal of secondary rays (AO): the low-poly surface by default; texels whose primary ray hit the high poly use the hit point
    surfP, surfN = Pm[m].copy(), Nm[m].copy()
    got = np.zeros(int(m.sum()), bool)
    from ..spatial import tri_soup, ray_cast
    if high is not None and high.nprims and not single:
        htri, _, _ = tri_soup(high)
        HP = np.asarray(high.get(POINT, "P"), np.float64)
        md = float(max_distance)
        cull = _CULL[face_culling]
        if tracing_mode == "cage_mesh":
            # The point on cage in the same triangle with the same barycentrics as the texel -> cast one-way towards that low-poly point
            CP = np.asarray(cage.get(POINT, "P"), np.float64)
            tt_ = hit[m]
            O = (CP[tri[tt_, 0]] * wb[:, 0:1] + CP[tri[tt_, 1]] * wb[:, 1:2]
                 + CP[tri[tt_, 2]] * wb[:, 2:3])
            D = Pm[m] - O
            hi_i, hi_t, hi_uv = ray_cast(O, D, HP, htri, False, md, False, cull)
            Dn = D / np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-30)
            hitP = O + Dn * hi_t[:, None]
            got = hi_i >= 0
            dsub = np.where(got, ((hitP - Pm[m]) * Nm[m]).sum(1), 0.0)
        else:
            bias = float(ray_bias)
            O = Pm[m] + Nm[m] * bias if bias else Pm[m]
            D = Nm[m]
            hi_i, hi_t, hi_uv = ray_cast(O, D, HP, htri, False, md,
                                         bool(both_sides), cull)
            got = hi_i >= 0
            hitP = O + D * hi_t[:, None]
            dsub = np.zeros(len(O))
            dsub[got] = hi_t[got] + bias
        rep["ray_hits"] = int(got.sum())
        rep["ray_miss"] = int((~got).sum())
        disp = np.zeros((H, W))
        nts = np.zeros((H, W, 3))
        nts[..., 2] = 1.0
        disp[m] = dsub
        # High-poly normal: face normal (of the hit triangle); with point normals, interpolated barycentrically
        hn = high.get(POINT, "N")
        u_, v_ = hi_uv[:, 0], hi_uv[:, 1]
        ht = np.where(got, hi_i, 0)
        a0, a1, a2 = htri[ht, 0], htri[ht, 1], htri[ht, 2]
        if hn is not None:
            hn = np.asarray(hn, np.float64)[:, :3]
            nh = hn[a0] * (1 - u_ - v_)[:, None] + hn[a1] * u_[:, None] \
                + hn[a2] * v_[:, None]
        else:
            nh = np.cross(HP[a1] - HP[a0], HP[a2] - HP[a0])
        nh /= np.maximum(np.linalg.norm(nh, axis=1, keepdims=True), 1e-12)
        Tm, Bm, Nmm = T[m], Bc[m], Nm[m]
        ts = np.stack([(nh * Tm).sum(1), (nh * Bm).sum(1), (nh * Nmm).sum(1)],
                      -1)
        ts = np.where(got[:, None], ts, np.array([0.0, 0.0, 1.0]))
        nts[m] = ts
        lay["normal_ts"] = nts * 0.5 + 0.5 if normal_space == "offset" else nts
        lay["displacement"] = disp
        surfP[got] = hitP[got]
        surfN[got] = nh[got]
        for nm in [x for x in str(high_attribs).split() if x]:
            a = high.get(POINT, nm)
            if a is None:
                raise ValueError(f"High poly has no point attribute '{nm}'")
            a = np.asarray(a, np.float64).reshape(high.npoints, -1)
            vv = a[a0] * (1 - u_ - v_)[:, None] + a[a1] * u_[:, None] \
                + a[a2] * v_[:, None]
            full = np.zeros((H, W, a.shape[1]))
            full[m] = np.where(got[:, None], vv, 0.0)
            lay["high_" + nm] = full
    if world_normal:
        wn = np.zeros((H, W, 3))
        wn[m] = surfN
        lay["worldnormal"] = wn * 0.5 + 0.5 if world_normal_space == "offset" else wn
    if position:
        pp = np.zeros((H, W, 3))
        if position_space == "relative":
            lo, hi = (np.asarray(x, np.float64) for x in low.bbox())
            if bounding_box == "fit":
                pp[m] = (surfP - lo) / np.maximum(hi - lo, 1e-12)
            else:
                pp[m] = (surfP - (lo + hi) / 2) / max(float((hi - lo).max()), 1e-12) + 0.5
        else:
            pp[m] = surfP
        lay["position"] = pp
    if occlusion:
        tgt = low if (single or high is None or not high.nprims) else high
        vtri, _, _ = tri_soup(tgt)
        ns = max(1, int(round(int(occlusion_samples) * float(sample_multiplier))))
        oc = np.zeros((H, W))
        oc[m] = _occlusion(surfP, surfN, np.asarray(tgt.get(POINT, "P"), np.float64), vtri,
                           ns, occlusion_max_distance, _CULL[visibility_culling])
        lay["occlusion"] = oc
        rep["occlusion_samples"] = ns
    if height:
        d = lay["displacement"] if "displacement" in lay else np.zeros((H, W))
        if height_space == "custom":
            span = float(outer_distance) - float(inner_distance)
            if span == 0:
                raise ValueError("Inner Distance and Outer Distance cannot be equal")
            d = (d - float(inner_distance)) / span
        lay["height"] = np.where(m, d, 0.0)
    if alpha:
        am = np.zeros((H, W))
        am[m] = got if alpha_mask_high else 1.0
        lay["alpha"] = am
    n_d = int(dilate)
    for k, v in lay.items():
        if v.ndim == 2:
            v = v[..., None]
        if n_d > 0 and m.any() and not m.all():
            v, _ = _dilate(v, m, n_d)
        put(out, k, v)
    put(out, "mask", m.astype(np.float64))
    put(out, "primid", pid)
    return out, rep
