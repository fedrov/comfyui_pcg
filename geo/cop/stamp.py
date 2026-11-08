"""
Scatter shapes / stamping / autostereograms (batch C), plus the geometry ↔ image coordinate convention (also used by batch F).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Geometry ↔ image: which plane, how big
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  plane  xz  top view, u = +X, v = −Z -- consistent with HeightField to Mesh (the image's "up"
             is north = −Z), so points scattered on the terrain line up when stamped back onto the height map
         xy  front view, u = +X, v = +Y
         zy  side view, u = +Z, v = +Y
  mapping world  centred on the origin, image width = World Size units (height by aspect ratio) --
                 the same as HeightField to Mesh (with center on)
          fit    fit the geometry's bounding box (plus a 5% margin) into the image, keeping the aspect ratio

Pinned by tests: for a mesh from HeightField to Mesh, the uv each point gets back from to_uv is exactly
its own uv attribute.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage
from .pattern import _base, rnd
from .pixel import getn, put, _vec
from .filters import sample

PLANES = ("xz", "xy", "zy")
MAPPINGS = ("world", "fit")
SHAPES = ("circle", "box", "ring", "star", "triangle", "diamond", "layer")
BLENDS = ("max", "add", "over")


# ═══════════════════════════════════════════════════════════ coordinate convention
def _plane_ab(P, plane):
    P = np.asarray(P, np.float64).reshape(-1, 3)
    if plane == "xz":
        return P[:, 0], -P[:, 2]
    if plane == "xy":
        return P[:, 0], P[:, 1]
    if plane == "zy":
        return P[:, 2], P[:, 1]
    raise ValueError(f"Plane must be one of {PLANES}")


def frame(P, W, H, plane="xz", mapping="world", world_size=1.0, margin=0.05):
    """
    -> (a0, b0, span_a, span_b): affine from plane coordinates (a, b) to uv, u = (a − a0)/span_a.
    world: centred on the origin, width world_size; fit: bounding box plus margin, aspect ratio kept.
    """
    if mapping not in MAPPINGS:
        raise ValueError(f"Mapping must be one of {MAPPINGS}")
    if mapping == "world":
        sa = float(world_size)
        if not sa > 0:
            raise ValueError("World Size must be > 0")
        sb = sa * H / W
        return -sa / 2, -sb / 2, sa, sb
    a, b = _plane_ab(P, plane)
    if a.size == 0:
        raise ValueError("fit needs points to know the bounding box")
    amin, amax, bmin, bmax = a.min(), a.max(), b.min(), b.max()
    ra = max(amax - amin, 1e-9)
    rb = max(bmax - bmin, 1e-9)
    # keep the aspect ratio: one unit maps to the same number of pixels in u and v
    upp = max(ra / W, rb / H) * (1 + 2 * float(margin))
    sa, sb = upp * W, upp * H
    return (amin + amax) / 2 - sa / 2, (bmin + bmax) / 2 - sb / 2, sa, sb


def to_uv(P, W, H, plane="xz", mapping="world", world_size=1.0, fr=None):
    """points -> (N,2) uv."""
    a, b = _plane_ab(P, plane)
    a0, b0, sa, sb = fr or frame(P, W, H, plane, mapping, world_size)
    return np.stack([(a - a0) / sa, (b - b0) / sb], -1)


def from_uv(uv, W, H, plane="xz", fr=None, height=None):
    """uv -> (N,3) points; the third axis (out of plane) is filled with height (default 0)."""
    a0, b0, sa, sb = fr
    uv = np.asarray(uv, np.float64).reshape(-1, 2)
    a = a0 + uv[:, 0] * sa
    b = b0 + uv[:, 1] * sb
    h = np.zeros(len(uv)) if height is None else np.asarray(height,
                                                            np.float64)
    if plane == "xz":
        return np.stack([a, h, -b], -1)
    if plane == "xy":
        return np.stack([a, b, h], -1)
    return np.stack([h, b, a], -1)


def curve_samples(geo, spacing_uv, W, H, plane, fr):
    """
    Points taken along each curve (or a polygon's boundary, closed end to start) at equal arc-length spacing in uv space
    -> (uv (N,2), tangent angle (degrees, uv space), owning prim).
    """
    from ..core import POINT
    P = geo.get(POINT, "P")
    uv = to_uv(P, W, H, plane, fr=fr)
    # measure arc length in pixels: only then is it truly equidistant when u and v pixel sizes differ (non-square images)
    px = uv * np.array([W, H], np.float64)
    step = float(spacing_uv) * W
    outs, angs, prs = [], [], []
    for i in range(geo.nprims):
        idx = np.asarray(geo.prim_points(i))
        if idx.size < 2:
            continue
        q = px[idx]
        if bool(geo.prim_closed[i]) and idx.size > 2:
            q = np.vstack([q, q[:1]])
        seg = np.diff(q, axis=0)
        ln = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.r_[0.0, np.cumsum(ln)]
        if cum[-1] <= 0:
            continue
        t = np.arange(0.0, cum[-1] + 1e-9, step)
        k = np.clip(np.searchsorted(cum, t, side="right") - 1, 0, len(ln) - 1)
        f = (t - cum[k]) / np.maximum(ln[k], 1e-12)
        pts = q[k] + seg[k] * f[:, None]
        outs.append(pts / np.array([W, H]))
        angs.append(np.degrees(np.arctan2(seg[k, 1], seg[k, 0])))
        prs.append(np.full(len(t), i))
    if not outs:
        return np.zeros((0, 2)), np.zeros(0), np.zeros(0, int)
    return np.vstack(outs), np.concatenate(angs), np.concatenate(prs)


# ═══════════════════════════════════════════════════════════ shapes
def _sdf(shape, x, y):
    """Signed distance in local coordinates (radius = 1), also in units of "radius"."""
    if shape == "circle":
        return np.hypot(x, y) - 1.0
    if shape == "box":
        qx, qy = np.abs(x) - 1.0, np.abs(y) - 1.0
        return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(
            np.maximum(qx, qy), 0)
    if shape == "ring":
        return np.abs(np.hypot(x, y) - 0.75) - 0.25
    if shape == "diamond":
        return (np.abs(x) + np.abs(y) - 1.0) / math.sqrt(2)
    if shape == "triangle":
        return _tri(x, y)
    if shape == "star":
        from .generate import sdf_star
        q = np.stack([x, y], -1)
        return np.asarray(sdf_star(q, 1.0, 5, 0.5))
    raise ValueError(f"Shape must be one of {SHAPES}")


def _tri(x, y):
    """Exact SDF of an equilateral triangle (Quílez), circumradius 1, apex toward +y."""
    k = math.sqrt(3.0)
    r = 1.0 * k / 2                     # half the side length (side is √3 for circumradius 1)
    px = np.abs(x) - r
    py = y + 0.5
    m = px + k * py > 0
    px2 = np.where(m, (px - k * py) / 2, px)
    py2 = np.where(m, (-k * px - py) / 2, py)
    px2 = px2 - np.clip(px2, -2 * r, 0.0)
    return -np.hypot(px2, py2) * np.sign(py2)


def _stamp_cov(shape, lx, ly, r_px, soft, stamp_img):
    """local coordinates -> (coverage, colour or None)."""
    if shape == "layer":
        u = (lx + 1) * 0.5
        v = (ly + 1) * 0.5
        a = sample(stamp_img, u, v, "black")
        C = a.shape[-1]
        cov = a[..., 3] if C >= 4 else (a[..., 0] if C == 1 else
                                        a[..., :3].mean(-1))
        col = a[..., :3] if C >= 3 else None
        return np.clip(cov, 0, 1), col
    d = _sdf(shape, lx, ly) * r_px
    return np.clip(0.5 - d / max(float(soft), 1e-3), 0.0, 1.0), None


def _positions(W, H, count, seed, density, min_dist):
    """
    Random positions: the uv of candidate k is hashed from (seed, k), independent of the total -- changing Count
    from 100 to 101 leaves the first 100 untouched. Density Layer rejects by probability; Min Distance
    (uv, relative to image width) uses a grid hash for "dart throwing" rejection, processed in order, earlier ones win.
    """
    k = np.arange(int(count) * (4 if (density is not None or min_dist > 0)
                                else 1))
    u = rnd(k, seed, 1)
    v = rnd(k, seed, 2)
    keep = np.ones(k.size, bool)
    if density is not None:
        jj = np.clip((u * W).astype(int), 0, W - 1)
        ii = np.clip((v * H).astype(int), 0, H - 1)
        keep &= rnd(k, seed, 3) < np.clip(density[ii, jj], 0, 1)
    u, v = u[keep], v[keep]
    if min_dist > 0:
        md = float(min_dist)
        cell = md / math.sqrt(2)
        grid = {}
        acc = []
        ar = H / W
        for a, b in zip(u, v):
            if len(acc) >= count:
                break
            gx, gy = int(a / cell), int(b * ar / cell)
            ok = True
            for dy in (-2, -1, 0, 1, 2):
                for dx in (-2, -1, 0, 1, 2):
                    q = grid.get((gx + dx, gy + dy))
                    if q is not None and (q[0] - a) ** 2 + (
                            (q[1] - b) * ar) ** 2 < md * md:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                grid[(gx, gy)] = (a, b)
                acc.append((a, b))
        return np.asarray(acc, np.float64).reshape(-1, 2)
    return np.stack([u, v], -1)[:int(count)]


def scatter_shapes(img=None, count=100, shape="circle", size=0.05,
                   size_random=0.5, aspect=1.0, rotation=0.0,
                   rotation_random=180.0, softness=1.0, density_layer="",
                   min_distance=0.0, blend="max", tile=True, seed=0,
                   stamp=None, stamp_layer="C", geo=None, plane="xz",
                   mapping="world", world_size=1.0, spacing=0.0,
                   align_to_curve=True, out_layer="shapes", xres=512,
                   yres=512):
    """
    Scatter Shapes / Stamp Points / Scatter on Curves / Configure Stamps.

    Three sources of positions:
      · no geometry connected: scatter Count randomly (filtered by Density Layer probability, spread by Min Distance)
      · geometry connected, Spacing = 0: one stamp per point (Stamp Points). pscale, if present, multiplies
        Size; Cd, if present, is used as the colour
      · geometry connected, Spacing > 0: equidistant points along each curve (polygons use their boundary) (Scatter on
        Curves); with Align to Curve the shape rotates along the tangent

    Size is the **diameter**, as a fraction of the image width. Size Random 0.5 = size between (1 − 0.5)~1 times.
    With Shape = layer the stamp is the Stamp Layer from the Stamp input (4 channels: alpha as the shape,
    RGB as the colour; single channel is just the shape).

    Outputs: out_layer (coverage), _id (index + 1 of the dominant stamp, 0 = empty),
    _color (RGB: geometry Cd / stamp colour / one random colour per stamp), _rand (one per stamp).
    Returns (image, number of stamps).
    """
    if shape not in SHAPES:
        raise ValueError(f"Shape must be one of {SHAPES}")
    if blend not in BLENDS:
        raise ValueError(f"Blend must be one of {BLENDS}")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    stamp_a = None
    if shape == "layer":
        if stamp is None:
            raise ValueError("Shape = layer needs a Stamp image connected")
        stamp_a = getn(stamp, stamp_layer)
    sizes_mul = None
    cols = None
    angs = None
    if geo is not None:
        from ..core import POINT
        P = geo.get(POINT, "P")
        if P is None or len(P) == 0:
            raise ValueError("geometry has no points")
        fr = frame(P, W, H, plane, mapping, world_size)
        if float(spacing) > 0:
            pos, angs, _ = curve_samples(geo, spacing, W, H, plane, fr)
            if not align_to_curve:
                angs = None
        else:
            pos = to_uv(P, W, H, plane, fr=fr)
            ps = geo.get(POINT, "pscale")
            if ps is not None:
                sizes_mul = np.asarray(ps, np.float64).reshape(-1)
            cd = geo.get(POINT, "Cd")
            if cd is not None:
                cols = np.asarray(cd, np.float64).reshape(len(P), -1)[:, :3]
    else:
        dens = None
        if str(density_layer).strip():
            dens = getn(out, density_layer)[..., 0]
        pos = _positions(W, H, count, seed, dens, float(min_distance))
    n = len(pos)
    idx = np.arange(n)
    r_ = rnd(idx, seed, 5)
    sz = float(size) * (1 - float(size_random) * rnd(idx, seed, 6))
    if sizes_mul is not None:
        sz = sz * sizes_mul
    rot = float(rotation) + float(rotation_random) * (rnd(idx, seed, 7) * 2
                                                      - 1)
    if angs is not None:
        rot = rot + angs
    if cols is None:
        from .pattern import _hsv
        cols = _hsv(rnd(idx, seed, 8), np.full(n, 0.6), np.full(n, 0.9))

    cov_acc = np.zeros((H, W))
    top = np.zeros((H, W))
    idl = np.zeros((H, W))
    col_l = np.zeros((H, W, 3))
    rnd_l = np.zeros((H, W))
    asp = max(float(aspect), 1e-6)
    drawn = 0
    for k in range(n):
        r_px = 0.5 * sz[k] * W
        if r_px <= 0:
            continue
        ext = r_px * max(asp, 1.0) * (1.5 if shape == "star" else 1.42) + 2
        cxp, cyp = pos[k, 0] * W, pos[k, 1] * H
        shifts = [(0.0, 0.0)]
        if tile:
            sx = [0.0] + ([W] if cxp - ext < 0 else []) + \
                ([-W] if cxp + ext > W else [])
            sy = [0.0] + ([H] if cyp - ext < 0 else []) + \
                ([-H] if cyp + ext > H else [])
            shifts = [(a, b) for a in sx for b in sy]
        th = math.radians(rot[k])
        c, s = math.cos(th), math.sin(th)
        hit = False
        for ox, oy in shifts:
            x0 = int(math.floor(cxp + ox - ext))
            x1 = int(math.ceil(cxp + ox + ext))
            y0 = int(math.floor(cyp + oy - ext))
            y1 = int(math.ceil(cyp + oy + ext))
            xa, xb, ya, yb = max(x0, 0), min(x1, W), max(y0, 0), min(y1, H)
            if xa >= xb or ya >= yb:
                continue
            J, I = np.meshgrid(np.arange(xa, xb) + 0.5,
                               np.arange(ya, yb) + 0.5)
            dx, dy = J - (cxp + ox), I - (cyp + oy)
            lx = (dx * c + dy * s) / (r_px * asp)
            ly = (-dx * s + dy * c) / r_px
            cv, scol = _stamp_cov(shape, lx, ly, r_px, softness, stamp_a)
            if not (cv > 0).any():
                continue
            hit = True
            colk = scol if scol is not None else cols[k]
            sl = (slice(ya, yb), slice(xa, xb))
            if blend == "add":
                cov_acc[sl] += cv
                win = cv >= top[sl]
            elif blend == "max":
                win = cv > top[sl]
                cov_acc[sl] = np.maximum(cov_acc[sl], cv)
            else:
                cov_acc[sl] = cv + cov_acc[sl] * (1 - cv)
                win = cv > 0.5
            if blend == "over":
                cl = col_l[sl]
                col_l[sl] = cl * (1 - cv[..., None]) + (
                    colk if np.ndim(colk) == 3 else colk[None, None, :]) \
                    * cv[..., None]
            else:
                cc = colk if np.ndim(colk) == 3 else np.broadcast_to(
                    colk, cv.shape + (3,))
                col_l[sl] = np.where(win[..., None], cc, col_l[sl])
            top[sl] = np.where(win, cv, top[sl])
            idl[sl] = np.where(win, k + 1, idl[sl])
            rnd_l[sl] = np.where(win, r_[k], rnd_l[sl])
        drawn += hit
    name = str(out_layer).strip() or "shapes"
    put(out, name, cov_acc, like)
    put(out, name + "_id", idl, like)
    put(out, name + "_color", col_l, like)
    put(out, name + "_rand", rnd_l, like)
    return out, int(drawn)


# ═══════════════════════════════════════════════════════════ autostereogram
def stereogram(img, depth_layer="depth", pattern_layer="", strip=0,
               depth_scale=0.33, cross_eyed=False, color=True, seed=0,
               out_layer="stereogram"):
    """
    Auto Stereogram (single-image random-dot stereogram). Depth 0 = farthest (background), 1 = nearest.

    Constraint: in each row, two pixels s(z) apart have the same colour; when each eye looks at one of them the lines of sight
    intersect at depth z. s(z) = 2·Strip·(1 − μz)/(2 − μz) (Thimbleby 1994), μ =
    Depth Scale; at z = 0, s = Strip (one pattern strip width). Strip 0 = image width / 8.

    Implemented as "copy from left to right": out[x] = out[x − s], with the pattern or random dots in the first strip. Scans
    column by column, vectorized over all rows. Depth is taken at **the midpoint of the pixel pair** (first estimate s from the depth at x,
    then recompute with the depth at x − s/2), reducing the half-strip misalignment of a pure left anchor.

    Limitations (honestly): no hidden-surface removal (points behind the edges of near objects that one eye shouldn't see are
    still constrained), so there is a bit of ghosting at depth discontinuities; this is the usual compromise for such single-image stereograms.

    cross_eyed: cross-eyed viewing (depth reversed). Default is parallel viewing (wall-eyed).
    """
    if img is None:
        return CopImage()
    W, H = img.xres, img.yres
    z = np.clip(getn(img, depth_layer)[..., 0], 0, 1)
    if cross_eyed:
        z = 1.0 - z
    E = int(strip) or max(8, W // 8)
    mu = min(max(float(depth_scale), 0.0), 0.9)

    def sep(zz):
        return np.rint(2 * E * (1 - mu * zz) / (2 - mu * zz)).astype(np.int64)

    s0 = sep(z)
    J = np.arange(W)[None, :]
    mid = np.clip(J - s0 // 2, 0, W - 1)
    s = sep(np.take_along_axis(z, mid, 1))
    C = 3 if color else 1
    rows = np.arange(H)
    if str(pattern_layer).strip():
        pa = getn(img, pattern_layer)
        C = pa.shape[2]
        ph, pw = pa.shape[:2]
        jj = (np.arange(W) % E) * pw // E
        ii = (rows * pw // E) % ph        # scaled vertically by the same ratio, tiled
        pat = pa[ii][:, jj]
    else:
        k = (rows[:, None] * W + np.arange(W)[None, :]).astype(np.int64)
        pat = np.stack([rnd(k, seed, c) for c in range(C)], -1)
    out = np.empty((H, W, C))
    for x in range(W):
        sx = s[:, x]
        src = x - sx
        ok = src >= 0
        col = pat[:, x].copy()
        col[ok] = out[rows[ok], src[ok]]
        out[:, x] = col
    res = img.copy()
    put(res, str(out_layer).strip() or "stereogram", out, img)
    put(res, (str(out_layer).strip() or "stereogram") + "_sep",
        s.astype(np.float64), img)
    return res
