"""
pcg100 c7_filter_sim: a batch of COP filters / simulations added from the SideFX docs whose "semantics differ from the old nodes".

The old nodes (COP Feather / Smooth Fill / Contour / Dither / Heat Distort ...) are the plugin's own
algorithms, rated [C] by the audit (not the same thing as Houdini), so the **old nodes are not changed**; new functions are added here,
with new node classes (nodes_cop2.py).

━━ Common conventions
  · Distance unit "image coordinates": consistent with the plugin's existing image space (see coordspace /
    transform.crop_window) -- origin at the image centre, −1 ... 1 spans the **long side**, so
    1 pixel = 2 / max(W, H) image units.
  · Array row 0 is at the **bottom** (v up), +Y = increasing row index.
  · The `mask` input + Mask parameter on Houdini nodes: result = original + (new − original)·Mask·mask layer.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage
from .pixel import getn, put
from .fx import pad as _pad, CONV_BORDERS


def _px(W, H):
    """How many image units one pixel is."""
    return 2.0 / max(int(W), int(H))


def _mask_mix(img, src, new, mask, mask_layer):
    """Houdini's Mask parameter + mask input: blends from the original to the new value by mask·mask layer."""
    m = float(mask)
    if str(mask_layer).strip():
        m = m * getn(img, mask_layer)[..., :1]
    return src + (new - src) * m


# ═══════════════════════════════════════════════════════════ Feather
FEATHER_DIRS = ("diamond", "square", "octagon", "custom", "circle")
FEATHER_METHODS = ("distance_for_unit_change", "change_per_distance")
# Sweep Directions (Custom mode): token -> sweep direction (dx, dy), +Y = increasing row index (up)
SWEEPS = {"nx": (-1, 0), "px": (1, 0), "ny": (0, -1), "py": (0, 1),
          "nxny": (-1, -1), "nxpy": (-1, 1), "pxny": (1, -1), "pxpy": (1, 1)}
_AXIAL = ("nx", "px", "ny", "py")
_DIAG = ("nxny", "nxpy", "pxny", "pxpy")
# Circle: adds 8 "knight's move" directions; the convex hull is a 16-gon (see the notes in feather_slope)
_KNIGHT = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2),
           (-2, -1)]


def _sweep(a, dx, dy, cost):
    """
    One sweep towards (dx, dy): a[p] = max(a[p], a[p − (dx,dy)] − cost), **serial in sweep order**
    (the previous pixel has already been updated before passing on to the next), so a single sweep propagates the value all the way along this ray.

    Axis-aligned (dy = 0) is done in one go with the accumulate identity: the serial recurrence along +x
    out[x] = max(a[x], out[x−1] − c) has the solution max_{k<=x}(a[k] − c(x−k))
    = cummax(a + c·x) − c·x. Other directions loop row by row (vectorized within a row). a (H,W,C) is modified in place.
    """
    H, W = a.shape[:2]
    if dy == 0:
        n = W
        x = np.arange(n, dtype=np.float64)[None, :, None] * (cost / abs(dx))
        if dx > 0:
            a[:] = np.maximum.accumulate(a + x, axis=1) - x
        else:
            b = a[:, ::-1]
            a[:] = (np.maximum.accumulate(b + x, axis=1) - x)[:, ::-1]
        return a
    rows = range(H) if dy > 0 else range(H - 1, -1, -1)
    quad = abs(dx) == 1 and abs(dy) == 1
    if quad:
        xr = np.arange(W, dtype=np.float64)[:, None] * cost
    for y in rows:
        ys = y - dy
        if ys < 0 or ys >= H:
            if quad:
                _row_acc(a, y, dx, xr)
            continue
        src = a[ys]
        if quad:
            # A diagonal sweep = a "king's move" sweep in this quadrant: three predecessors, the diagonal neighbour (x−dx, y−dy), the vertical neighbour
            # (x, y−dy) and the horizontal neighbour (x−dx, y), **all costing s·sqrt(2) pixels**. With diagonal
            # steps only, an isolated pixel only reaches grid points of the same parity (a checkerboard; the first version did this);
            # charging sqrt(2) for horizontal/vertical steps too gives the distance sqrt(2)·max(|dx|, |dy|) -- its unit ball is exactly
            # the convex hull of the four diagonal unit vectors (that square), the same shape as "diagonal steps only".
            a[y] = np.maximum(a[y], src - cost)
            if dx > 0:
                a[y, 1:] = np.maximum(a[y, 1:], src[:-1] - cost)
            else:
                a[y, :-1] = np.maximum(a[y, :-1], src[1:] - cost)
            _row_acc(a, y, dx, xr)
            continue
        if dx > 0:
            a[y, dx:] = np.maximum(a[y, dx:], src[:W - dx] - cost)
        elif dx < 0:
            a[y, :W + dx] = np.maximum(a[y, :W + dx], src[-dx:] - cost)
        else:
            a[y] = np.maximum(a[y], src - cost)
    return a


def _row_acc(a, y, dx, xr):
    """One serial propagation pass along dx on row y (accumulate identity, see _sweep)."""
    r = a[y]
    if dx > 0:
        a[y] = np.maximum.accumulate(r + xr, axis=0) - xr
    else:
        a[y] = (np.maximum.accumulate(r[::-1] + xr, axis=0) - xr)[::-1]


def feather_dirs(direction, sweeps=()):
    """Feather Direction -> the list of directions to sweep for this mode [(dx, dy), ...]."""
    if direction == "diamond":
        return [SWEEPS[k] for k in _AXIAL]
    if direction == "square":
        return [SWEEPS[k] for k in _DIAG]
    if direction == "octagon":
        return [SWEEPS[k] for k in _AXIAL + _DIAG]
    if direction == "circle":
        return [SWEEPS[k] for k in _AXIAL + _DIAG] + list(_KNIGHT)
    return [SWEEPS[k] for k in SWEEPS if k in set(sweeps)]


def feather_slope(img, layer="mask", out_layer="", high_to_low=True,
                  include_border=False, border="black", direction="diamond",
                  sweeps=(), method="distance_for_unit_change",
                  distance=0.1, change=10.0, mask=1.0, mask_layer=""):
    """
    Houdini Feather: **limits the maximum rate of change between neighbouring pixels** (maximum slope).

    High to Low (Feather from High to Low on): bright pixels stay, surrounding dark pixels are raised to
    satisfy the slope -- out(p) = max_q (v(q) − s·d(p, q)); off: dark pixels stay, bright pixels are pressed down,
    out(p) = min_q (v(q) + s·d(p, q)). s = how much change is allowed per image unit
    (Distance for Unit Change = 1/s, Change per Distance = s; docs' wording: "the two are reciprocals").

    What kind of distance d is depends on Feather Direction -- the docs only say "two horizontal/vertical passes -> diamond islands, diagonal ->
    square islands, horizontal/vertical + diagonal -> octagonal islands, Circle uses another algorithm -> round islands", **without formulas**.
    Our approach (our own choice): each sweep direction u is one serial propagation pass along u, with the cost of a step =
    s x the step's **Euclidean length** (1 pixel axis-aligned, sqrt(2) pixels diagonal). Running several passes in turn gives
    the shortest path "restricted to these directions", whose unit ball is the convex hull of the directions' unit vectors:
      Diamond  ±X ±Y            -> diamond (L1)
      Square   four diagonals    -> square (sides parallel to the axes, vertices in the diagonal directions)
      Octagon  eight directions  -> regular octagon
      Circle   eight directions + 8 knight's-move directions (±1,±2)(±2,±1) -> 16-gon, max deviation from a true circle
               1 − cos(13.3°) ≈ 2.7%. Houdini's Circle "uses a different algorithm"; what exactly
               the docs don't say; ours is an approximate circle, not an exact Euclidean cone.
      Custom   sweeps only the checked Sweep Directions (one-sided feathering, e.g. for ramps)
    The vertices of all three polygons lie on the same circle (the slope in each direction is exactly s).
    A diagonal pass is in fact a "king's move" sweep in the quadrant (horizontal / vertical / diagonal predecessors all charged s·sqrt(2) pixels),
    distance = sqrt(2)·max(|dx|, |dy|); the unit ball is still that square, but without the checkerboard (see _sweep).

    Include Border (docs: "take initial pixel values from outside the image border"): when on, the image is padded outward by Border
    by one ring, feathered, then cropped back. Our layers have no border metadata, so Border is a parameter
    (black = constant 0 / clamp / wrap / mirror); values padded by clamp are all farther away than the same-valued
    pixels inside the image, so it has no effect. wrap matches the usage "turn on Include Border for seamless textures".

    Mask: result = original + (feathered − original)·Mask·mask layer. Multiple channels are processed independently.
    """
    if img is None:
        return CopImage()
    if direction not in FEATHER_DIRS:
        raise ValueError(f"Feather Direction must be one of {FEATHER_DIRS}")
    if method not in FEATHER_METHODS:
        raise ValueError(f"Feather Method must be one of {FEATHER_METHODS}")
    if border not in CONV_BORDERS:
        raise ValueError(f"Border must be one of {CONV_BORDERS}")
    bad = [k for k in sweeps if k not in SWEEPS]
    if bad:
        raise ValueError(f"Sweep Directions must be among {tuple(SWEEPS)}")
    if method == "distance_for_unit_change":
        D = float(distance)
        if not D > 0:
            raise ValueError("Distance for Unit Change must be > 0")
        s = 1.0 / D
    else:
        s = float(change)
        if s < 0:
            raise ValueError("Change per Distance cannot be negative")
    W, H = img.xres, img.yres
    px = _px(W, H)
    src = getn(img, layer)
    sg = 1.0 if high_to_low else -1.0
    a = sg * src
    dirs = feather_dirs(direction, sweeps)
    r = 0
    if include_border and dirs:
        # Padding width: value range / cost of the cheapest step = how far an outside pixel can reach at most,
        # then capped at the image size (for wrap, padding one whole image is enough -- the docs say seamless textures need "two passes")
        rng = float(src.max() - src.min()) if src.size else 0.0
        r = max(W, H) if s * px <= 0 else int(min(math.ceil(
            rng / (s * px)) + 1, max(W, H)))
        a = _pad(a, r, border)         # black pads 0, which is 0 both before and after negation
    a = np.array(a, np.float64)
    for dx, dy in dirs:
        _sweep(a, dx, dy, s * px * math.hypot(dx, dy))
    if r:
        a = a[r:r + H, r:r + W]
    new = sg * a
    res = _mask_mix(img, src, new, mask, mask_layer)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, res, img)


# ═══════════════════════════════════════════════════ Extrapolate Boundaries
_INF = 1.0e20


def _edt1d_arg(f):
    """
    One-dimensional squared distance transform along axis=1, **also returning the index attaining the minimum**:
    d[q] = min_p ((q−p)² + f[p]), arg[q] = the p attaining the minimum.

    The same lower-envelope algorithm as sdf._edt1d_sq (Felzenszwalb & Huttenlocher), except the read-out
    stage also hands over the vertex positions in the stack -- edge padding needs "which interior pixel is nearest",
    not just "how far". The one in sdf is left unchanged (it is a hot path for other nodes).
    """
    f = np.ascontiguousarray(np.asarray(f, np.float64))
    R, N = f.shape
    rows = np.arange(R)
    if N == 1:
        return f.copy(), np.zeros((R, 1), np.int64)
    v = np.zeros((R, N), np.int64)
    z = np.empty((R, N + 1), np.float64)
    z[:, 0] = -_INF
    z[:, 1] = _INF
    k = np.zeros(R, np.int64)
    for q in range(1, N):
        fq = f[:, q] + float(q) * q
        while True:
            vk = v[rows, k]
            s = (fq - (f[rows, vk] + vk.astype(np.float64) ** 2)) \
                / (2.0 * (q - vk))
            pop = (k > 0) & (s <= z[rows, k])
            if not pop.any():
                break
            k = np.where(pop, k - 1, k)
        k = k + 1
        v[rows, k] = q
        z[rows, k] = s
        z[rows, k + 1] = _INF
    d = np.empty((R, N), np.float64)
    arg = np.empty((R, N), np.int64)
    k = np.zeros(R, np.int64)
    for q in range(N):
        while True:
            adv = z[rows, k + 1] < q
            if not adv.any():
                break
            k = np.where(adv, k + 1, k)
        vk = v[rows, k]
        d[:, q] = (q - vk) ** 2 + f[rows, vk]
        arg[:, q] = vk
    return d, arg


def nearest_seed(seed):
    """
    Squared distance (pixels²) from each pixel to the nearest True pixel, and that pixel's (row, column).
    Separable: first per row find "the nearest seed column in this row", then the lower envelope along columns (squared Euclidean distance is separable).
    """
    seed = np.asarray(seed, bool)
    f = np.where(seed, 0.0, _INF)
    d1, ax = _edt1d_arg(f)                         # within rows: column of the nearest seed
    d2, ay = _edt1d_arg(np.ascontiguousarray(d1.T))  # along columns: which row
    d2, ay = d2.T, ay.T
    cols = np.broadcast_to(np.arange(seed.shape[1])[None, :], seed.shape)
    return d2, ay, ax[ay, cols]


EXTRAP_EXTERIOR = ("unchanged", "black", "diffuse_fill")
EXTRAP_SIDES = ("below_threshold", "above_threshold")


def _bilerp_masked(a, inside, y, x, only_inside):
    """
    Bilinear sample of a at (y, x) (pixel coordinates, pixel centres are integers). only_inside: of the four corners, only those
    inside are used (weights renormalized); if none are, returns None so the caller falls back.
    """
    H, W = inside.shape
    y0 = np.floor(y).astype(np.int64)
    x0 = np.floor(x).astype(np.int64)
    fy, fx = y - y0, x - x0
    acc = np.zeros(y.shape + (a.shape[2],))
    wsum = np.zeros(y.shape)
    for dy, dx, w in ((0, 0, (1 - fy) * (1 - fx)), (0, 1, (1 - fy) * fx),
                      (1, 0, fy * (1 - fx)), (1, 1, fy * fx)):
        yy = np.clip(y0 + dy, 0, H - 1)
        xx = np.clip(x0 + dx, 0, W - 1)
        if only_inside:
            w = w * inside[yy, xx]
        acc += a[yy, xx] * w[..., None]
        wsum += w
    return acc, wsum


def extrapolate_boundaries(img, layers="", fillarea_layer="mask",
                           inner_side="above_threshold", threshold=0.5,
                           exterior="unchanged", edge_padding=0.05,
                           edge_offset=0.0, sample_only_present=True,
                           diffuse_iterations=50, mask=1.0, mask_layer=""):
    """
    Houdini Extrapolate Boundaries: extends the "interior" defined by fillarea outward (texture bleed).

      interior Inner Side = Above Threshold: pixels with fillarea > Threshold;
               Below Threshold: pixels < Threshold (docs: "fill the white area").
               Exactly equal to Threshold counts as exterior (not in the docs, our choice).
      padding  exterior pixels within Edge Padding (image units) of the interior directly copy the value of the **nearest
               interior pixel** (exact Euclidean nearest point).
      Edge Offset  from the nearest point, steps back into the interior by Offset (image units, along the "exterior pixel -> nearest point"
               direction) before sampling, bilinear. Docs: "values at the padded edge may already have exterior colour mixed in".
      Sample Only Present  on: bilinear uses interior pixels only (weights renormalized; when none of the four corners are
               interior, falls back to the nearest point's value) -- black exterior edges can't leak in; off: ordinary bilinear,
               blending smoothly with exterior values at the edge (docs' wording).
      Exterior exterior pixels beyond the padding: Unchanged as-is / Black set to 0 / Diffuse Fill
               smooth fill using "interior + padding" as known values (nearest known value as the base, then Diffuse
               Iterations of Jacobi relaxation -- solving ∇²f = 0, the same equation as COP Smooth Fill's
               laplace).

    Interior pixels stay bit-for-bit unchanged. layers empty = all layers except fillarea. Mask blends by the common convention.
    """
    if img is None:
        return CopImage()
    if inner_side not in EXTRAP_SIDES:
        raise ValueError(f"Inner Side must be one of {EXTRAP_SIDES}")
    if exterior not in EXTRAP_EXTERIOR:
        raise ValueError(f"Exterior must be one of {EXTRAP_EXTERIOR}")
    from .fx import pad as _p
    W, H = img.xres, img.yres
    px = _px(W, H)
    fa = getn(img, fillarea_layer)[..., 0]
    t = float(threshold)
    inside = fa > t if inner_side == "above_threshold" else fa < t
    if not inside.any():
        raise ValueError(f"'{fillarea_layer}' has no interior pixels (Threshold = {t:g})")
    d2, ny, nx = nearest_seed(inside)
    dist = np.sqrt(d2) * px                          # image units
    padz = (~inside) & (dist <= float(edge_padding) + 1e-12)
    known = inside | padz
    off = float(edge_offset) / px                    # pixels
    fname = str(fillarea_layer).strip()
    out = img.copy()
    ns = [n for n in str(layers).split() if n] or \
        [n for n in img.names if n != fname]
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    for n in ns:
        a = getn(img, n)
        r = a.copy()
        if padz.any():
            yy, xx = np.nonzero(padz)
            qy, qx = ny[yy, xx].astype(np.float64), nx[yy, xx].astype(np.float64)
            vy, vx = qy - I[yy, xx], qx - J[yy, xx]
            ln = np.hypot(vy, vx)
            ln = np.where(ln > 0, ln, 1.0)
            sy, sx = qy + vy / ln * off, qx + vx / ln * off
            acc, ws = _bilerp_masked(a, inside, sy, sx, bool(sample_only_present))
            near_ = a[ny[yy, xx], nx[yy, xx]]
            ok = ws > 1e-12
            val = np.where(ok[:, None], acc / np.where(ok, ws, 1.0)[:, None], near_)
            r[yy, xx] = val
        if exterior == "black":
            r = np.where(known[..., None], r, 0.0)
        elif exterior == "diffuse_fill":
            # The base is the value of the "nearest known pixel", then Jacobi. The plugin's existing
            # backproject._push_pull is not used: on non-square images its pyramid top level is left with weightless cells
            # (treated as 0), pulling large exterior areas towards 0 (noted in the notes; that function is not this package's to change)
            _, ky, kx = nearest_seed(known)
            f = r[ky, kx]
            kn = known[..., None]
            for _ in range(int(diffuse_iterations)):
                p = _p(f, 1, "clamp")
                avg = (p[1:-1, 2:] + p[1:-1, :-2] + p[2:, 1:-1]
                       + p[:-2, 1:-1]) * 0.25
                f = np.where(kn, r, avg)
            r = f          # at known cells f always equals r (the base and every iteration put the known values back)
        # Interior pixels are never written at any point (r is a copy of a, padding / exterior only write ~inside),
        # so they are unchanged bit for bit with no extra safeguard needed
        put(out, n, _mask_mix(img, a, r, mask, mask_layer), img)
    return out


# ═══════════════════════════════════════════ Edge Detect by Contour / Depth / Normal
EDGE_KINDS = ("contour", "depth", "normal")
_EDGE_RMAX = 64


def edge_detect_probe(img, kind="contour", layer="id", thickness_scale=2.0,
                      thickness_layer="", edge_spread=0.5, blur=0.0,
                      contour_tolerance=0.5, depth_tolerance=0.01,
                      normal_tolerance=0.9, min_probe_radius=1.0,
                      out_layer="edges"):
    """
    Houdini's three Edge Detect by Contour / Depth / Normal combined into one node, chosen by Kind.

    The docs only say "uses **ray differentials of neighbouring pixels** to compare the current pixel with neighbours (Contour compares primitive
    id, Depth compares Z, Normal compares normals), with variable line width"; the parameters are Thickness Scale (radius of the probe
    kernel in pixels; a multiplier of the thickness layer if connected), Edge Spread (spread factor of the Gaussian weight),
    Blur (blur before detection), the respective Tolerance, Min Probe Radius (lower limit of the probe radius).
    **How exactly it is computed the docs don't say**; below is our definition:

      R(p) = max(Thickness Scale × thickness(p), Min Probe Radius)  pixels, capped at 64
      a neighbour o (integer offset with |o| <= R(p)) counts as "on a line" when
        contour  ‖v(p+o) − v(p)‖ > Contour Tolerance (Euclidean distance for multiple channels)
        depth    |z(p+o) − z(p)| > Depth Tolerance (both sides are drawn; the docs don't say only the near side)
        normal   n̂(p+o)·n̂(p) < Normal Tolerance (the docs' wording is "minimum dot product ... to count as a line";
                 taken literally that would not be crease detection, so it is implemented as "dot product below it = sharp enough fold")
      edges(p) = max over on-line neighbours of exp(−½·((|o| − 1)/σ)²), σ = Edge Spread × R(p)
        -- pixels right next to the discontinuity = 1, falling off outward as a Gaussian truncated at R; the larger Edge Spread,
        the more "solid" the line (less falloff before truncation). With Edge Spread = 0 only the immediately adjacent pixels = 1.

    We have no camera / ray differentials; Tolerance is absolute (not scaled by distance or slope).
    Outside the border, clamp (replicate the edge).
    """
    if img is None:
        return CopImage()
    if kind not in EDGE_KINDS:
        raise ValueError(f"Kind must be one of {EDGE_KINDS}")
    a = getn(img, layer)
    if kind == "normal" and a.shape[2] < 3:
        raise ValueError("Normal needs a 3-channel normal layer")
    if float(blur) > 0:
        from .filters import gaussian_kernel
        from .fx import convolve
        g = np.asarray(gaussian_kernel(float(blur)), np.float64)
        a = convolve(convolve(a, g[None, :], "clamp"), g[:, None], "clamp")
    H, W = a.shape[:2]
    R = np.full((H, W), float(thickness_scale))
    if str(thickness_layer).strip():
        R = R * getn(img, thickness_layer)[..., 0]
    R = np.clip(np.maximum(R, float(min_probe_radius)), 0.0, _EDGE_RMAX)
    if kind == "normal":
        a = a[..., :3] / np.maximum(np.linalg.norm(a[..., :3], axis=-1,
                                                   keepdims=True), 1e-12)
    r = int(math.ceil(float(R.max()))) if R.size else 0
    P = np.pad(a, ((r, r), (r, r), (0, 0)), mode="edge")
    sig = float(edge_spread) * R
    out = np.zeros((H, W))
    for dy in range(-r, r + 1):
        rx = int(math.isqrt(r * r - dy * dy))      # only offsets inside the disk of radius r
        for dx in range(-rx, rx + 1):
            d = math.hypot(dx, dy)
            if d == 0:
                continue
            nb = P[r + dy:r + dy + H, r + dx:r + dx + W]
            if kind == "contour":
                hit = np.linalg.norm(nb - a, axis=-1) > float(contour_tolerance)
            elif kind == "depth":
                hit = np.abs(nb[..., 0] - a[..., 0]) > float(depth_tolerance)
            else:
                hit = (nb * a).sum(-1) < float(normal_tolerance)
            hit &= d <= R
            if d <= 1.0:
                w = np.ones((H, W))
            else:
                with np.errstate(divide="ignore", invalid="ignore"):
                    w = np.where(sig > 0, np.exp(-0.5 * ((d - 1.0) / np.where(
                        sig > 0, sig, 1.0)) ** 2), 0.0)
            out = np.maximum(out, np.where(hit, w, 0.0))
    res = img.copy()
    return put(res, str(out_layer).strip() or "edges", out, img)


# ═══════════════════════════════════════════════════════════ Surface Dither
DITHER_OUTPUTS = ("mask", "sdf")


def _smoothstep(a, b, x):
    if b <= a:
        return (x >= b).astype(np.float64)
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def surface_dither(img, uv_layer="", dotscale_layer="", density_scale=8.0,
                   pattern_scale=1.0, pattern_scale_xy="1 1",
                   pattern_offset="0 0", pattern_rotate=0.0, dot_scale=0.5,
                   output_type="mask", iso_offset=0.0, smooth=1.0,
                   level_transition=0.5, out_layer="dither", uv_out_layer="",
                   level_layer="", scale_layer="", xres=256, yres=256):
    """
    Houdini Surface Dither: halftone dots stuck to the **surface (uv)** that never shrink below a pixel
    (fractal / surface-stable dithering). The docs only give the parameters and the sentence "levels by uv, avoids aliasing from
    getting too small"; the approach below is ours:

      q = Rotate(uv ⊙ Pattern Scale·Pattern Scale XY) + Pattern Offset   pattern coordinates
      ρ = largest singular value of ∂q/∂pixel (central differences)      how many q units one pixel is
      λ = log2(Density Scale · ρ),k = floor(λ),f = λ − k
      level k: dots at q grid points m·2^k, on-screen dot spacing = Density Scale · 2^(−f) pixels
                (between D/2 ... D). When shrinking to f -> 1 it switches to level k + 1, the spacing returns to D,
                and only the 1/4 of dots with both components even are kept (they are exactly all grid points of the next level).
      Level Transition: the other 3/4 "disappearing" dots shrink away over the last T portion of this level -- no jump at level changes.
                t = 1 − smoothstep(1 − T, 1, f), radius = (r0 + Rb)·t − Rb, Rb = sqrt(2) × cell
                pixels (at t = 0 these dots no longer contribute anything to the SDF). With T = 0 they vanish suddenly only at f = 1.
      radius (pixels) = ½ · Dot Scale · dotscale layer · Density Scale, so the surviving dots keep the same
                screen size before and after the level change.
      SDF (pixels) = min over the four corners of the containing cell (|q − dot|/ρ − radius); exactly one of the four corners is
                a "kept dot", and the nearest of both kinds of dot is among these four corners (Voronoi of the grid), so it is exact.
      Mask = 1 − smoothstep(Iso − Smooth/2, Iso + Smooth/2, SDF): Iso Offset > 0 makes dots larger,
                without affecting level changes.

    Extra outputs (empty layer name = not output): uv (local coordinates in the cell frac(q / 2^k)), level (k),
    scale (2^(−f) = this block's dot spacing / Density Scale). Without a uv layer, the pixel-centre texture uv is used
    (u = (x + ½)/W). Where uv has seams (jumps) the derivatives are huge and a very coarse level gets chosen there --
    the docs don't say how Houdini handles seams. The shape input / Shape Resolution (custom dot shapes) are not implemented.
    """
    from .pattern import _base
    from .pixel import _vec
    if output_type not in DITHER_OUTPUTS:
        raise ValueError(f"Output Type must be one of {DITHER_OUTPUTS}")
    D = float(density_scale)
    if not D > 0:
        raise ValueError("Density Scale must be > 0")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    if str(uv_layer).strip():
        uv = getn(out, uv_layer)[..., :2]
    else:
        J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                           np.arange(H, dtype=np.float64))
        uv = np.stack([(J + 0.5) / W, (I + 0.5) / H], -1)
    sxy = _vec(pattern_scale_xy, 2) * float(pattern_scale)
    off = _vec(pattern_offset, 2)
    th = math.radians(float(pattern_rotate))
    c, s = math.cos(th), math.sin(th)
    a0, a1 = uv[..., 0] * sxy[0], uv[..., 1] * sxy[1]
    qx = c * a0 - s * a1 + off[0]
    qy = s * a0 + c * a1 + off[1]
    # Jacobian (q with respect to pixels), central differences; one-sided at the edges (np.gradient's default)
    if W > 1:
        jxx, jyx = np.gradient(qx, axis=1), np.gradient(qy, axis=1)
    else:
        jxx = jyx = np.zeros_like(qx)
    if H > 1:
        jxy, jyy = np.gradient(qx, axis=0), np.gradient(qy, axis=0)
    else:
        jxy = jyy = np.zeros_like(qx)
    # Largest singular value of a 2x2 matrix: sqrt(½(‖J‖²_F + sqrt(‖J‖⁴_F − 4 det²)))
    fro = jxx ** 2 + jxy ** 2 + jyx ** 2 + jyy ** 2
    det = jxx * jyy - jxy * jyx
    rho = np.sqrt(0.5 * (fro + np.sqrt(np.maximum(fro * fro - 4 * det * det,
                                                  0.0))))
    rho = np.maximum(rho, 1e-12)
    lam = np.log2(D * rho)
    k = np.floor(lam)
    f = lam - k
    cell = np.exp2(k)
    gx, gy = qx / cell, qy / cell
    bx, by = np.floor(gx), np.floor(gy)
    ds = getn(out, dotscale_layer)[..., 0] if str(dotscale_layer).strip() \
        else 1.0
    r0 = 0.5 * float(dot_scale) * ds * D
    T = min(max(float(level_transition), 0.0), 1.0)
    shrink = 1.0 - _smoothstep(1.0 - T, 1.0, f)
    # Disappearing dots: radius falls linearly from r0 to −Rb (Rb = sqrt(2)·cell pixels >= the distance from any pixel to the nearest kept dot).
    # Falling only to 0 is not enough: a dot of radius 0 has SDF = 0 at its centre, smaller than the value given by kept dots,
    # so the SDF would jump across a level change (caught by the first test version with λ exactly an integer, under the float error of a 90° rotation)
    Rb = math.sqrt(2.0) * cell / rho
    r_go = (r0 + Rb) * shrink - Rb
    sdf = np.full((H, W), np.inf)
    for ox in (0.0, 1.0):
        for oy in (0.0, 1.0):
            mx, my = bx + ox, by + oy
            keep = (np.mod(mx, 2) == 0) & (np.mod(my, 2) == 0)
            rad = np.where(keep, r0, r_go)
            dist = np.hypot(gx - mx, gy - my) * cell / rho
            sdf = np.minimum(sdf, dist - rad)
    if output_type == "sdf":
        res = sdf
    else:
        sm = max(float(smooth), 0.0)
        iso = float(iso_offset)
        res = 1.0 - _smoothstep(iso - sm / 2, iso + sm / 2, sdf)
    put(out, str(out_layer).strip() or "dither", res, like)
    if str(uv_out_layer).strip():
        put(out, uv_out_layer, np.stack([gx - bx, gy - by], -1), like)
    if str(level_layer).strip():
        put(out, level_layer, k, like)
    if str(scale_layer).strip():
        put(out, scale_layer, np.exp2(-f), like)
    return out


# ═══════════════════════════════════════════════════════════ Turing Patterns
TURING_FILTERS = ("box", "gaussian")
TURING_UNITS = ("image", "pixels")


def _blur_axis(a, r, axis, filt, read_outside, border):
    """Blur along one axis, radius r pixels. With read_outside off, only pixels inside the image are used (weights renormalized)."""
    from .fx import convolve
    if r <= 0:
        return a
    if filt == "box":
        n = int(round(r))                 # with n = 0 the kernel is [1], identity
        k = np.ones(2 * n + 1)
    else:
        # Gaussian: kernel half-width = radius, σ = radius/3 (3σ truncation, same as the plugin's gaussian_kernel)
        n = int(math.ceil(r))
        t = np.arange(-n, n + 1, dtype=np.float64)
        k = np.exp(-0.5 * (t / (r / 3.0)) ** 2)
    k = k / k.sum()
    k2 = k[None, :] if axis == 1 else k[:, None]
    if read_outside:
        return convolve(a, k2, border)
    num = convolve(a, k2, "black")
    den = convolve(np.ones(a.shape[:2] + (1,)), k2, "black")
    return num / den


def turing_patterns(img, layer="C", out_layer="", filter="gaussian",
                    read_outside=False, border="clamp", units="pixels",
                    iterations=10, radius=4.0, power=2.0, gain=1.0,
                    scale="1 1", mask=1.0, mask_layer=""):
    """
    Houdini Turing Patterns (22.0): repeatedly "blur + sharpen" the input to grow stripes / spots while keeping
    the large-scale shape of the original. The docs only say "blur then sharpen, repeated Iterations times", with parameters Filter / Read Pixels
    outside Image / Units / Radius / Power / Gain / Scale, **without a formula**. Our approach:

        x₀ = Gain · source
        each iteration: b = Blur(x, Radius); x = clip(b + Power·(b − Blur(b, Radius)), 0, 1)

    "Sharpen" is an unsharp mask of the same radius: equivalent to an "activation − inhibition" difference of Gaussians, amplifying components with wavelength ≈ Radius;
    clamping to 0..1 is the nonlinearity that saturates it into two phases (the larger Power, the more "solid", docs' wording). The clamp range is
    our choice (HDR input gets squeezed into 0..1).
      Filter    Box (mean over 2n+1, n = round(radius)) / Gaussian (kernel half-width = radius, σ = radius/3)
      Units     Pixels / Image (image units, long side = 2: radius in pixels = r·max(W,H)/2)
      Scale     radius multipliers in x and y (0 = no blur in that direction)
      Read Pixels outside Image  off: only pixels inside the image (weights renormalized); on: pad by Border
    Not implemented: the radius input layer (per-pixel radius needs variable-radius blur), per-channel RGBA toggles (we process every channel,
    and Layer selects the layer). Mask blends with the **original** by the common convention.
    """
    if img is None:
        return CopImage()
    if filter not in TURING_FILTERS:
        raise ValueError(f"Filter must be one of {TURING_FILTERS}")
    if units not in TURING_UNITS:
        raise ValueError(f"Units must be one of {TURING_UNITS}")
    if border not in CONV_BORDERS:
        raise ValueError(f"Border must be one of {CONV_BORDERS}")
    from .pixel import _vec
    W, H = img.xres, img.yres
    r = float(radius)
    if units == "image":
        r = r * max(W, H) / 2.0
    sx, sy = _vec(scale, 2)
    rx, ry = r * float(sx), r * float(sy)
    src = getn(img, layer)
    x = src * float(gain)

    def blur(a):
        a = _blur_axis(a, rx, 1, filter, read_outside, border)
        return _blur_axis(a, ry, 0, filter, read_outside, border)

    p = float(power)
    for _ in range(int(iterations)):
        b = blur(x)
        x = np.clip(b + p * (b - blur(b)), 0.0, 1.0)
    res = _mask_mix(img, src, x, mask, mask_layer)
    out = img.copy()
    return put(out, str(out_layer).strip() or layer, res, img)


# ═══════════════════════════════════════════════════════ Heat Distort by Layer
def _gauss(a, sigma, border="clamp"):
    from .filters import gaussian_kernel
    from .fx import convolve
    if sigma <= 0:
        return a
    g = np.asarray(gaussian_kernel(float(sigma)), np.float64)
    return convolve(convolve(a, g[None, :], border), g[:, None], border)


def heat_distort_by_layer(img, layers="", noise_layer="noise", effect_layer="",
                          dir_layer="", scale=0.05, angle=0.0, accurate=False,
                          step_pixels=1.0, streak_blur=False,
                          scale_by_timestep=False, timestep=1.0 / 24,
                          blur_source=False, blur_source_size=0.01,
                          blur_noise=False, blur_noise_size=0.01,
                          chromatic=False, ca_scale=1.0, ca_red=1.2,
                          ca_green=1.0, ca_blue=0.8, border="clamp", mask=1.0,
                          mask_layer=""):
    """
    Houdini Heat Distort by Layer: pushes pixels using an **input** noise layer (and optional direction / strength layers).
    The docs only give the parameters with one sentence each, no formulas; our definition (image units: long side = 2, +y up):

      direction g   uses the dir layer if connected (2 channels, a vector in image units); otherwise the gradient of the noise layer
               ∇noise (change per image unit; with Blur Noise on, noise is Gaussian-blurred first,
               σ = Blur Size image units). Docs: "without dir, the direction is computed from noise".
      displacement D   = Scale · effect · Rot(Angle)·g (× Timestep, when Scale by Timestep is on).
               Angle 0 = no rotation (docs "0 corresponds to +X in image space": g's +X component stays +X).
      sampling out(p) = src(p − D(p)) (bilinear, Border outside the image).
      Accurate Distortion  on: walks backwards along the field in n = ceil(|D| / Step Pixels) steps, each step moving D/n using the D
               at the **current position** (bilinear) -- the trajectory curves where the field bends (docs: "traces curved trajectories"). Off: one step.
      Streak Blur  averages n+1 points taken evenly along this trajectory (n+1 points on a straight line when Accurate is off).
      Blur Source  Gaussian-blurs source first (σ = Blur Size), then interpolates between the original and the blurred image by |D| / max|D|
               -- "blur by distortion strength". The normalization is our choice.
      Chromatic Aberration  layers with >= 3 channels: R / G / B each use D × Scale × their own multiplier (default 1.2 / 1.0 /
               0.8, not given by the docs). alpha (channel 4) follows G.
    Mask by the common convention. layers empty = all layers except the noise / effect / dir / mask layers.
    """
    if img is None:
        return CopImage()
    from .filters import sample, BORDERS
    from .pixel import names_of
    if border not in BORDERS:
        raise ValueError(f"Border must be one of {BORDERS}")
    W, H = img.xres, img.yres
    ppu = max(W, H) / 2.0                 # pixels per image unit
    if str(dir_layer).strip():
        g = getn(img, dir_layer)[..., :2]
    else:
        n = getn(img, noise_layer)[..., :1]
        if blur_noise:
            n = _gauss(n, float(blur_noise_size) * ppu)
        p = np.pad(n[..., 0], 1, mode="edge")
        gx = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5 * ppu
        gy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5 * ppu
        g = np.stack([gx, gy], -1)
    th = math.radians(float(angle))
    c, s = math.cos(th), math.sin(th)
    D = np.stack([c * g[..., 0] - s * g[..., 1], s * g[..., 0] + c * g[..., 1]],
                 -1) * float(scale)
    if str(effect_layer).strip():
        D = D * getn(img, effect_layer)[..., :1]
    if scale_by_timestep:
        D = D * float(timestep)
    Dp = D * ppu                                       # pixels
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    mag = np.hypot(Dp[..., 0], Dp[..., 1])
    st = max(float(step_pixels), 1e-6)
    nmax = int(min(math.ceil(float(mag.max()) / st), 256)) if mag.size else 0
    nsteps = max(nmax, 1)

    def path(Dc):
        """Returns the points along the trajectory [(x, y), ...] (pixel coordinates); index 0 is the start and the last is the end."""
        if not accurate:
            if not streak_blur:            # only the end point is needed
                return [(J - Dc[..., 0], I - Dc[..., 1])]
            return [(J - Dc[..., 0] * t / nsteps, I - Dc[..., 1] * t / nsteps)
                    for t in range(nsteps + 1)]
        pts = [(J, I)]
        x, y = J, I
        for _ in range(nsteps):
            d = sample(Dc, (x + 0.5) / W, (y + 0.5) / H, border)
            x = x - d[..., 0] / nsteps
            y = y - d[..., 1] / nsteps
            pts.append((x, y))
        return pts

    skip = {str(x).strip() for x in (noise_layer, effect_layer, dir_layer,
                                       mask_layer)} - {""}
    ns = [n for n in str(layers).split() if n] or \
        [n for n in img.names if n not in skip]
    names_of(img, " ".join(ns))
    mmax = float(mag.max()) if mag.size else 0.0
    out = img.copy()
    mults = (float(ca_red), float(ca_green), float(ca_blue))
    for name in ns:
        a = getn(img, name)
        srcs = a
        if blur_source:
            b = _gauss(a, float(blur_source_size) * ppu, border)
            w = (mag / mmax)[..., None] if mmax > 0 else 0.0
            srcs = a + (b - a) * w
        C = a.shape[2]
        if chromatic and C >= 3:
            groups = [([0], mults[0]), ([1] + ([3] if C > 3 else []), mults[1]),
                      ([2], mults[2])]
            groups = [(ch, m * float(ca_scale)) for ch, m in groups]
        else:
            groups = [(list(range(C)), 1.0)]
        r = np.empty_like(a)
        for ch, m in groups:
            pts = path(Dp * m)
            sub_ = srcs[..., ch]
            if streak_blur:
                acc = 0.0
                for x, y in pts:
                    acc = acc + sample(sub_, (x + 0.5) / W, (y + 0.5) / H,
                                       border)
                v = acc / len(pts)
            else:
                x, y = pts[-1]
                v = sample(sub_, (x + 0.5) / W, (y + 0.5) / H, border)
            r[..., ch] = v
        put(out, name, _mask_mix(img, a, r, mask, mask_layer), img)
    return out
