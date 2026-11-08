"""
Pattern generation (batch C): checker / brick tiles / cells / UV grid / Julia fractal / Chladni modes /
knit / weave, plus text.

All are "one closed form per pixel center" -- no simulation, no iteration (except Julia's escape iteration).
Besides the main layer each pattern emits a set of auxiliary layers (id, one random number per piece, in-piece uv, distance
to the edge...), and those are the real material ingredients: random color by id, bevel normals from edge distance,
textures by in-piece uv.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tiling
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Counts gives "how many pieces across, how many down". All patterns are periodic on [0,1)^2 (cell pattern feature points are also taken modulo
the grid), so as long as the counts are integers the output is **seamless left/right and top/bottom**. The tests compare directly: shift the image
by half (np.roll), and the difference between the edge column and its neighbor is on the same order as between adjacent columns inside the image.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Anti-aliasing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Patterns with edges (checker, tile grout, cell edges, weave threads) all do a 1-pixel-wide linear transition by **distance in pixel units**,
rather than producing a hard edge and blurring it. The checker uses Quilez's analytic box filter: integrating the square wave over the pixel
footprint, so edge softness doesn't change with resolution.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, check_res
from .pixel import getn, put, _vec, _hash64

PATTERNS = ("checker", "tile", "cell", "uv_grid", "julia", "chladni", "knit",
            "weave")
WEAVES = ("plain", "twill", "satin",
          # pcg100 c4: Houdini Weave's pattern input -- which thread is on top at each crossing is decided by an image
          "custom")
# pcg100 c4: Tile Pattern's bonds (the Bonds in Pattern Type). offset = the original
# "shift each row by Row Offset pieces"; the rest are laid out per the bricklaying definitions (see _BONDS)
# Labs UV Grid Texture (pcg100 c4): tile / marker coloring, marker type, text content
UVG_TILE_COLORING = ("hue", "uniform", "checker", "gradient")
UVG_MARKER_COLORING = ("uniform", "checker", "gradient")
UVG_MARKERS = ("text", "cross", "arrow")
UVG_TEXT = ("letters", "coordinates")
# Cell Pattern's Metric / Lattice Type (pcg100 c4)
CELL_METRICS = ("euclidean", "manhattan", "chebyshev")
CELL_LATTICES = ("grid", "hexagonal")
# Chladni's Output Mode: pixel_lines = the original "draw nodal lines by pixel width"; the other three are Houdini's
CHLADNI_OUT = ("pixel_lines", "nodal_lines", "absolute", "signed")
BONDS = ("offset", "stack", "stretcher", "header", "flemish", "english",
         "american")


# ═══════════════════════════════════════════════════════════ Basics
def _base(img, xres, yres):
    """With an input, add layers on top of it (resolution follows it); without one, create new."""
    if img is not None and len(img):
        return img.copy(), img
    x, y = check_res(xres, yres)
    return CopImage(x, y), None


def _pix(W, H):
    """(u, v) of pixel centers, v up (row 0 = smallest v)."""
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    return (J + 0.5) / W, (I + 0.5) / H


def rnd(ids, seed=0, salt=0):
    """Integer id (may be negative) -> [0,1) hash random number. Bit-reproducible and resolution independent."""
    k = np.asarray(ids).astype(np.int64).view(np.uint64)
    with np.errstate(over="ignore"):
        k = k * np.uint64(4) + np.uint64(int(salt) & 3)
    z = _hash64(k, int(seed) + 7919 * (int(salt) >> 2))
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def _counts(spec):
    nu, nv = (max(1, int(round(v))) for v in _vec(spec, 2))
    return nu, nv


def _aa(d):
    """Signed distance in pixels (negative inside, positive outside) -> coverage, 1-pixel-wide linear transition."""
    return np.clip(0.5 - d, 0.0, 1.0)


def _put_all(out, like, prefix, layers):
    for k, v in layers.items():
        put(out, prefix if k == "" else f"{prefix}_{k}", v, like)
    return out


# ═══════════════════════════════════════════════════════════ Patterns
def _checker(u, v, W, H, nu, nv):
    """Quilez's analytic box-filtered checker: integrate the square wave over the pixel footprint."""
    x, y = u * nu, v * nv
    wx, wy = nu / W, nv / H            # how wide one pixel is in cell units

    def tri(p, w):
        return 2.0 * (np.abs(np.mod((p - 0.5 * w) * 0.5, 1.0) - 0.5)
                      - np.abs(np.mod((p + 0.5 * w) * 0.5, 1.0) - 0.5)) / w

    val = 0.5 - 0.5 * tri(x, wx) * tri(y, wy)
    cx = np.floor(x).astype(np.int64) % nu
    cy = np.floor(y).astype(np.int64) % nv
    return {"": val, "id": (cy * nu + cx).astype(np.float64)}


def _tile(u, v, W, H, nu, nv, offset, gap, bevel, seed):
    """
    Bricks / tiles. Each row is shifted by offset pieces (0.5 = running bond). gap and bevel are given as fractions of **one piece's short side**
    and converted to pixels internally -- so the same parameters look the same at any resolution.
    """
    y = v * nv
    row = np.floor(y).astype(np.int64)
    x = u * nu + row * float(offset)
    col = np.floor(x).astype(np.int64)
    fx, fy = x - col, y - row
    col = col % nu
    row = row % nv
    tw, th = W / nu, H / nv                        # pixel width and height of one piece
    dpx = np.minimum(np.minimum(fx, 1 - fx) * tw, np.minimum(fy, 1 - fy) * th)
    short = min(tw, th)
    g = float(gap) * short * 0.5                   # each piece gives up half the gap
    mask = _aa(g - dpx)
    b = max(float(bevel) * short, 1e-9)
    t = np.clip((dpx - g) / b, 0.0, 1.0)
    hgt = t * t * (3 - 2 * t) * (dpx > g)
    ids = row * nu + col
    return {"": mask, "id": ids.astype(np.float64), "height": hgt,
            "edge": dpx - g, "rand": rnd(ids, seed),
            "uv": np.stack([fx, fy], -1)}


# each bond: the sequence of brick widths in a row (in units of stretcher length = 1, repeating) and how far the whole row shifts right.
# a header shows the brick's end face, so its length counts as half a piece (real bricks length : width ≈ 2 : 1).
def _bond_rows(bond, row, header_every):
    """
    Returns [(boolean mask for this class of rows, width sequence, per-row right shift)]. row is the integer row number (0 at the bottom).
    The right shift is written in "accumulates with row number" form (like -0.5·row), exactly the same expression as the original offset mode's
    `x = u·nu + row·offset` -- so stretcher with Row Offset 0.5 and
    stack with Row Offset 0 give identical outputs (including id / rand) pixel by pixel; the tests use this to cross-check.

      stack      stretchers, no offset
      stretcher  stretchers, each row shifted by half a piece (running bond)
      header     all headers, each row shifted by 1/4 piece (= half a header)
      flemish    stretchers and headers alternate within a row (1, ½); alternate rows shift by ¾, so a header sits right at the center of the stretcher in the next row
      english    stretcher rows and header rows alternate; stretcher rows shift right by ¾ (docs: "each row starts with 3/4 of a piece"), so stretchers' vertical joints
                 fall at the center of the headers
      american   one header row every Header Interval rows (starting at row 0), the rest are stretchers offset by half a piece
    """
    rf = row.astype(np.float64)
    allr = np.ones(row.shape, bool)
    if bond == "stack":
        return [(allr, (1.0,), 0.0 * rf)]
    if bond == "stretcher":
        return [(allr, (1.0,), -0.5 * rf)]
    if bond == "header":
        return [(allr, (0.5,), -0.25 * rf)]
    if bond == "flemish":
        return [(allr, (1.0, 0.5), -0.75 * rf)]
    odd = (row % 2) == 1
    if bond == "english":
        return [(~odd, (1.0,), 0.75 + 0.0 * rf), (odd, (0.5,), 0.0 * rf)]
    n = max(1, int(header_every))
    hdr = (row % n) == 0
    return [(hdr, (0.5,), 0.0 * rf), (~hdr, (1.0,), -0.5 * rf)]


def _tile_bond(u, v, W, H, nu, nv, bond, gap, bevel, seed, header_every):
    """
    Bricks laid by bond. Outputs the same set of layers as _tile; gap width / bevel are still converted to pixels from the short side of
    a **stretcher** cell, so headers and stretchers get the same mortar width.

    Seamless tiling: vertically nv must be a multiple of 2 (for American, a common multiple of Header Interval and 2);
    horizontally nu must be an integer multiple of a row's period (a Flemish stretcher+header pair = 1.5 pieces, so nu must be a multiple of 3).
    id is numbered "row x pieces per row + piece number mod pieces per row"; when pieces per row isn't an integer (not tileable)
    the piece at the right edge collides in id with the piece at the left edge.
    """
    y = v * nv
    row = np.floor(y).astype(np.int64)
    fy = y - row
    X = u * nu
    fx = np.zeros(u.shape)
    wid = np.ones(u.shape)
    idx = np.zeros(u.shape, np.int64)
    per_row = 1
    groups = _bond_rows(bond, row, header_every)
    for _, widths, _ in groups:
        P = float(sum(widths))
        per_row = max(per_row, int(math.ceil(nu * len(widths) / P - 1e-9)))
    for m, widths, shift in groups:
        wv = np.asarray(widths, np.float64)
        edges = np.concatenate([[0.0], np.cumsum(wv)])
        P = edges[-1]
        x = X[m] - shift[m]
        k = np.floor(x / P)
        r = x - k * P
        j = np.clip(np.searchsorted(edges[1:], r, side="right"), 0,
                    len(wv) - 1)
        w = wv[j]
        fx[m] = (r - edges[j]) / w
        wid[m] = w
        idx[m] = k.astype(np.int64) * len(wv) + j
    tw, th = W / nu, H / nv
    dpx = np.minimum(np.minimum(fx, 1 - fx) * wid * tw,
                     np.minimum(fy, 1 - fy) * th)
    short = min(tw, th)
    g = float(gap) * short * 0.5
    mask = _aa(g - dpx)
    b = max(float(bevel) * short, 1e-9)
    t = np.clip((dpx - g) / b, 0.0, 1.0)
    hgt = t * t * (3 - 2 * t) * (dpx > g)
    ids = (row % nv) * per_row + idx % per_row
    return {"": mask, "id": ids.astype(np.float64), "height": hgt,
            "edge": dpx - g, "rand": rnd(ids, seed),
            "uv": np.stack([fx, fy], -1)}


def _cell_points(nu, nv, jitter, seed):
    """One feature point per cell (in cell units), periodic: the point of cell (i mod nu, j mod nv)."""
    j = np.arange(nv)[:, None]
    i = np.arange(nu)[None, :]
    ids = j * nu + i
    ox = 0.5 + (rnd(ids, seed, 1) - 0.5) * float(jitter)
    oy = 0.5 + (rnd(ids, seed, 2) - 0.5) * float(jitter)
    return ox, oy


def _cell(u, v, W, H, nu, nv, jitter, gap, seed, metric="euclidean",
          lattice="grid", density=1.0, density_seed=0):
    """
    Periodic Voronoi cells. Two passes (Quilez): the first searches 5x5 neighbor cells for the nearest point; the second, in the 5x5
    around the nearest point, takes the min distance to each **bisector** -- that's the true distance to the cell edge,
    not F2 - F1 (which is too large mid-edge and too small at corners).

    Distances are measured in **pixel space**: when cells have different pixel width and height (e.g. 1024x512 with 8x8) cells
    are stretched, but edge thickness stays uniform everywhere.

    pcg100 c4 (matching Houdini Cell Pattern, defaults = the original behaviour):
      metric   euclidean (original) / manhattan / chebyshev. Under the latter two the "bisector"
               isn't a straight line, so the distance to the cell edge uses (F2 - F1) / 2 instead -- exact along the line joining the two points,
               approximate elsewhere (edge thickness will vary). The _dist layer uses the chosen metric
      lattice  grid (original) / hexagonal: odd rows' feature points shift right by half a cell, making cells hexagonal
               (regular hexagons at a cell aspect ratio of 2 : √3). Vertically needs an even number of rows to tile seamlessly
      density  each cell is culled by its own random number: cells with random number >= Density get main layer (mask) set to 0,
               other layers unchanged. 1 = keep all. Density Seed is a separate seed (same as Houdini)
    """
    if metric not in CELL_METRICS:
        raise ValueError(f"Metric must be one of {CELL_METRICS}")
    if lattice not in CELL_LATTICES:
        raise ValueError(f"Lattice Type must be one of {CELL_LATTICES}")
    ox, oy = _cell_points(nu, nv, jitter, seed)
    tw, th = W / nu, H / nv
    x, y = u * nu, v * nv
    hexa = lattice == "hexagonal"
    cx0 = np.floor(x).astype(np.int64)
    cy0 = np.floor(y).astype(np.int64)
    euclid = metric == "euclidean"
    # how large the neighborhood must be: a feature point is at most 1 cell from its own cell (Jitter 1), hexagonal adds half a cell.
    #   euclid + grid: nearest point <= √2, points outside the window >= 2 -> ±2 (the original, unchanged)
    #   euclid + hex: outside the window >= 1.5 isn't safe enough -> ±3 (>= 2.5)
    #   manhattan / chebyshev need the second nearest (F2): within one row there are always two points horizontally <= 2, vertically <= 1,
    #   F2 <= 3 (manhattan) -> grid ±3 (outside the window >= 3, can only tie), hex ±4 (>= 3.5)
    if euclid:
        rad = 3 if hexa else 2
    else:
        rad = 4 if hexa else 3

    def dmet(px, py):
        if euclid:
            return px * px + py * py
        if metric == "manhattan":
            return np.abs(px) + np.abs(py)
        return np.maximum(np.abs(px), np.abs(py))

    def pt(ci, cj):
        sx = ci + ox[cj % nv, ci % nu]
        if hexa:
            sx = sx + 0.5 * (cj % 2)
        return (sx - x) * tw, (cj + oy[cj % nv, ci % nu] - y) * th

    best = np.full(u.shape, np.inf)
    second = np.full(u.shape, np.inf)
    bx = np.zeros(u.shape)
    by = np.zeros(u.shape)
    bi = np.zeros(u.shape, np.int64)
    bj = np.zeros(u.shape, np.int64)
    R = range(-rad, rad + 1)
    for dj in R:
        for di in R:
            ci, cj = cx0 + di, cy0 + dj
            px, py = pt(ci, cj)
            d = dmet(px, py)
            m = d < best
            if not euclid:
                second = np.where(m, best, np.minimum(second, d))
            best = np.where(m, d, best)
            bx = np.where(m, px, bx)
            by = np.where(m, py, by)
            bi = np.where(m, ci, bi)
            bj = np.where(m, cj, bj)
    if euclid:
        edge = np.full(u.shape, np.inf)
        for dj in R:
            for di in R:
                ci, cj = bi + di, bj + dj
                px, py = pt(ci, cj)
                dx, dy = px - bx, py - by
                ll = dx * dx + dy * dy
                ok = ll > 1e-12
                # distance to the bisector = ((mr + mo)/2)·n, n = (mo - mr)/|mo - mr|
                e = ((bx + px) * 0.5 * dx + (by + py) * 0.5 * dy) \
                    / np.sqrt(np.where(ok, ll, 1.0))
                edge = np.where(ok, np.minimum(edge, e), edge)
        dist = np.sqrt(best)
    else:
        edge = (second - best) * 0.5
        dist = best
    ids = (bj % nv) * nu + (bi % nu)
    g = float(gap) * min(tw, th) * 0.5
    main = _aa(g - edge)
    if float(density) < 1.0:
        keep = rnd(ids, density_seed, 3) < float(density)
        main = np.where(keep, main, 0.0)
    return {"": main, "id": ids.astype(np.float64),
            "edge": edge - g, "dist": dist / min(tw, th),
            "rand": rnd(ids, seed)}


def _hsv(h, s, v):
    """Vectorized HSV -> RGB, h ∈ [0,1)."""
    h6 = (h % 1.0) * 6.0
    c = v * s
    xx = c * (1 - np.abs(h6 % 2 - 1))
    m = v - c
    z = np.zeros_like(h6)
    k = np.floor(h6).astype(int) % 6
    r = np.choose(k, [c, xx, z, z, xx, c])
    g = np.choose(k, [xx, c, c, xx, z, z])
    b = np.choose(k, [z, z, xx, c, c, xx])
    return np.stack([r + m, g + m, b + m], -1)


def _label(ci, cj):
    """Columns use letters (A, B ... Z, AA ...), rows use numbers, starting from the bottom-left (v up)."""
    s, n = "", int(ci)
    while True:
        s = chr(65 + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return f"{s}{int(cj) + 1}"


def _tile_colors(mode, ci, cj, nu, nv, c1, c2):
    """
    uniform is all c1; checker: (i + j) even c1, odd c2; gradient goes linearly from c1 to c2 by cell index
    (from the bottom-left, row-major). The docs only say "uses a color ramp", not which direction the ramp runs
    -- following the cell index is our own choice (one color per cell, easy to identify cells).
    """
    c1 = np.asarray(c1, np.float64).reshape(1, 1, 3)
    c2 = np.asarray(c2, np.float64).reshape(1, 1, 3)
    if mode == "uniform":
        return np.broadcast_to(c1, ci.shape + (3,))
    if mode == "checker":
        return np.where(((ci + cj) % 2 == 0)[..., None], c1, c2)
    t = ((cj * nu + ci) / max(nu * nv - 1, 1))[..., None]
    return c1 * (1 - t) + c2 * t


def _uv_grid(u, v, W, H, nu, nv, font, labels, tile_coloring="hue",
             tile_color1="0.85 0.85 0.85", tile_color2="0.6 0.6 0.6",
             outlines=True, outline_width=1.0, outline_color="0.08 0.08 0.08",
             marker_type="text", text_mode="letters", marker_size=0.32,
             marker_coloring="uniform", marker_color="0.05 0.05 0.05",
             marker_color2="1 1 1"):
    """
    UV checker image (Labs UV Grid Texture style): columns cycle through hue, rows alternate in value, 1-pixel
    grid lines, each cell labeled with its name. Cell names start at A1 in the **bottom-left** -- the bottom-left in UV space (v up),
    so once applied to a model you can tell at a glance whether the UVs are mirrored or how many degrees they're rotated.

    pcg100 c4 (matching Labs UV Grid Texture, defaults = the original look):
      Tile Coloring  hue (original: hue by column, value checker-alternating) / uniform / checker / gradient
      Outlines       toggle, line width (pixels), color
      Marker Type    text (cell name) / cross / arrow (points to +v, to see whether UVs are rotated)
      Text Mode      letters (A1, B1 ...) / coordinates ("i,j", from 0, bottom-left is 0,0)
      Marker Size    marker size relative to the cell's short side (font size for text, full length for cross / arrow)
      Marker Coloring uniform / checker / gradient, same rules as the cells
    With Draw Labels off no markers are drawn at all (the original toggle, kept).
    """
    x, y = u * nu, v * nv
    ci = np.floor(x).astype(np.int64) % nu
    cj = np.floor(y).astype(np.int64) % nv
    if tile_coloring == "hue":
        hue = (ci + 0.5) / nu
        val = np.where((ci + cj) % 2 == 0, 0.85, 0.6)
        rgb = _hsv(hue, np.full_like(hue, 0.55), val)
    else:
        rgb = _tile_colors(tile_coloring, ci, cj, nu, nv,
                           _vec(tile_color1, 3), _vec(tile_color2, 3))
    fx, fy = x - np.floor(x), y - np.floor(y)
    cw, ch = W / nu, H / nv
    if outlines:
        lp = np.minimum(np.minimum(fx, 1 - fx) * (W / nu),
                        np.minimum(fy, 1 - fy) * (H / nv))
        line = _aa(lp - float(outline_width) * 0.5)
        oc = _vec(outline_color, 3)
        rgb = rgb * (1 - line[..., None]) + oc * line[..., None]
    if labels:
        if marker_type == "text":
            size = max(6, int(min(cw, ch) * float(marker_size)))
            tm = np.zeros((H, W))
            for j in range(nv):
                for i in range(nu):
                    txt = _label(i, j) if text_mode == "letters" else f"{i},{j}"
                    g = render_text(txt, size, font)
                    gh, gw = g.shape
                    x0 = int(round((i + 0.5) * cw - gw / 2))
                    y0 = int(round((j + 0.5) * ch - gh / 2))
                    _stamp_max(tm, g[::-1], x0, y0)   # text row 0 is at the top, flip to v up
        else:
            from .sdf2d import cross, arrow
            S = float(marker_size) * min(cw, ch)       # full marker length (pixels)
            q = np.stack([(fx - 0.5) * cw, (fy - 0.5) * ch], -1)
            if marker_type == "cross":
                d = cross(q, S * 0.5, S * 0.5 - S * 0.08)
            else:
                d = arrow(q, (0.0, -S * 0.5), (0.0, S * 0.5), S * 0.16,
                          S * 0.6, 0.4)
            tm = _aa(d)
        mc = _vec(marker_color, 3)
        if marker_coloring != "uniform":
            mc = _tile_colors(marker_coloring, ci, cj, nu, nv, mc,
                              _vec(marker_color2, 3))
        rgb = rgb * (1 - tm[..., None]) + mc * tm[..., None]
    return {"": rgb, "id": (cj * nu + ci).astype(np.float64),
            "uv": np.stack([fx, fy], -1)}


def _julia(u, v, W, H, mode, c, center, zoom, iterations):
    """
    Julia / Mandelbrot, smooth iteration count n + 1 - log₂(log|z|) (escape radius 256, large enough
    for the smoothing term to be continuous). View width is 3/zoom complex-plane units, height by aspect ratio.
    """
    cx, cy = _vec(center, 2)
    span = 3.0 / max(float(zoom), 1e-12)
    zr = cx + (u - 0.5) * span
    zi = cy + (v - 0.5) * span * (H / W)
    if mode == "mandelbrot":
        c0r, c0i = zr.copy(), zi.copy()
        zr, zi = np.zeros_like(zr), np.zeros_like(zi)
    else:
        cc = _vec(c, 2)
        c0r = np.full_like(zr, cc[0])
        c0i = np.full_like(zi, cc[1])
    n = int(iterations)
    it = np.full(zr.shape, float(n))
    alive = np.ones(zr.shape, bool)
    trap = np.full(zr.shape, np.inf)
    for k in range(n):
        zr2, zi2 = zr * zr, zi * zi
        esc = alive & (zr2 + zi2 > 65536.0)
        if esc.any():
            lz = 0.5 * np.log(zr2[esc] + zi2[esc])
            it[esc] = k + 1 - np.log2(np.maximum(lz, 1e-12))
            alive &= ~esc
        if not alive.any():
            break
        nz = zr * zi
        zr = np.where(alive, zr2 - zi2 + c0r, zr)
        zi = np.where(alive, 2 * nz + c0i, zi)
        trap = np.where(alive, np.minimum(trap, np.hypot(zr, zi)), trap)
    return {"": np.clip(it / n, 0, 1), "inside": alive.astype(np.float64),
            "trap": np.where(np.isfinite(trap), trap, 0.0)}


def _chladni(u, v, W, H, n, m, sign, width, output="pixel_lines",
             amplitude=1.0, ratio=1.0, threshold=0.1, smooth=0.05):
    """
    Chladni modes of a square plate: f = A·[cos(nπx)cos(mπy) ± k·cos(mπx)cos(nπy)]. Sand settles on
    the nodal lines (f = 0). Coordinates are normalized by the short side (centered), so non-square images don't squash the mode.

    Houdini's description is "amplitudes of two waves a and b, b is a scaled version of a": A = Amplitude (scales a, and so
    the whole output), k = Amplitude Ratio (weight of b relative to a; larger means more b). k = 1,
    A = 1 is the original formula.

    Output (the last three modes, added in pcg100 c4, are Houdini's Output Mode):
      pixel_lines  the original: line width in **pixels**, |f| / |∇f|₍px₎ < width/2, same thickness on steep and gentle parts
      nodal_lines  Houdini's Nodal Lines: |f| <= Threshold - Smoothing Width is white,
                   >= Threshold is black, smoothstep in between. The docs only say "below the threshold fades from white to black, above
                   is black, Smoothing Width controls how soft the transition is"; putting the transition band **below** the threshold is our own choice
                   (so "above the threshold is all black" holds strictly); Width 0 = hard edge
      absolute     |f|
      signed       f (signed)
    """
    s = min(W, H)
    x = (u - 0.5) * (W / s) + 0.5
    y = (v - 0.5) * (H / s) + 0.5
    a, b = math.pi * float(n), math.pi * float(m)
    sg = 1.0 if sign == "+" else -1.0
    sg = sg * float(ratio)
    f = np.cos(a * x) * np.cos(b * y) + sg * np.cos(b * x) * np.cos(a * y)
    amp = float(amplitude)
    if amp != 1.0:
        f = f * amp
    if output == "absolute":
        return {"": np.abs(f), "value": f}
    if output == "signed":
        return {"": f, "value": f}
    if output == "nodal_lines":
        T, w = float(threshold), max(float(smooth), 0.0)
        af = np.abs(f)
        if w <= 0:
            line = (af < T).astype(np.float64)
        else:
            t = np.clip((af - (T - w)) / w, 0.0, 1.0)
            line = 1.0 - t * t * (3 - 2 * t)
        return {"": line, "value": f}
    fx = -a * np.sin(a * x) * np.cos(b * y) - sg * b * np.sin(b * x) \
        * np.cos(a * y)
    fy = -b * np.cos(a * x) * np.sin(b * y) - sg * a * np.cos(b * x) \
        * np.sin(a * y)
    gpx = np.hypot(fx, fy) / s                     # change per pixel
    if amp != 1.0:
        gpx = gpx * abs(amp)
    d = np.abs(f) / np.maximum(gpx, 1e-12)
    return {"": _aa(d - float(width) * 0.5), "value": f}


def _knit(u, v, W, H, nu, nv, seed):
    """
    Stockinette (knit stitch) V-shaped loops: each stitch has two slanted "legs", each a flattened ellipsoid profile,
    the left leg leaning up-right and the right leg up-left. Legs are longer than a cell and reach into the row above -- that's how
    loops in adjacent rows hook together, so each pixel looks at the legs of its own cell and the cell below and takes the higher.
    """
    x, y = u * nu, v * nv
    ci0 = np.floor(x).astype(np.int64)
    cj0 = np.floor(y).astype(np.int64)
    best = np.zeros(u.shape)
    bid = np.zeros(u.shape, np.int64)
    leg = np.zeros(u.shape)
    A, B = 0.62, 0.2                               # ellipse semi-axes (cell units)
    ang = math.radians(58.0)
    for dj in (-1, 0, 1):
        for di in (-1, 0, 1):
            ci, cj = ci0 + di, cj0 + dj
            for side, sgn in ((0, 1.0), (1, -1.0)):
                cxl = ci + 0.5 - sgn * 0.2
                cyl = cj + 0.62
                px, py = x - cxl, y - cyl
                c, s = math.cos(sgn * ang), math.sin(sgn * ang)
                ax = px * c + py * s
                ay = -px * s + py * c
                q = 1 - (ax / A) ** 2 - (ay / B) ** 2
                hgt = np.sqrt(np.maximum(q, 0.0))
                m = hgt > best
                best = np.where(m, hgt, best)
                idv = (cj % nv) * nu + (ci % nu)
                bid = np.where(m, idv, bid)
                leg = np.where(m, float(side), leg)
    return {"": best, "mask": (best > 0).astype(np.float64),
            "id": bid.astype(np.float64), "leg": leg,
            "rand": rnd(bid, seed)}


def _over(kind, i, j, table=None):
    """
    Is the warp on top at crossing (i, j)? plain 1/1, twill 2/2, 5-harness satin (skip 2).
    custom: looks up table[j, i] (the caller has already taken it modulo nu / nv).
    """
    if kind == "custom":
        return table[j, i]
    if kind == "plain":
        return (i + j) % 2 == 0
    if kind == "twill":
        return (i - j) % 4 < 2
    return (i * 2 - j) % 5 == 0


def _weave(u, v, W, H, nu, nv, kind, width, seed, weft_width=None,
           table=None):
    """
    Weave. nu warp threads (vertical), nv weft threads (horizontal), thread width width (as a fraction of one pitch). Each thread's
    cross-section is a semicircular profile; along the thread it undulates with a cosine between crossings: raised at crossings where it's on top,
    pressed down where it's below. Each pixel takes the higher of warp and weft -- what you see is the one on top.

    pcg100 c4: if weft_width is given it's the weft's (horizontal) own thread width (Houdini's Row Inset /
    Column Inset set gaps separately, 1 - thread width = gap); with kind = custom, over/under is looked up in table
    (an nv x nu boolean table, True = warp on top).
    """
    x, y = u * nu, v * nv
    i = np.floor(x).astype(np.int64)
    j = np.floor(y).astype(np.int64)
    fx, fy = x - i, y - j
    w = min(max(float(width), 0.05), 1.0) * 0.5
    wf = w if weft_width is None else \
        min(max(float(weft_width), 0.05), 1.0) * 0.5
    pw = np.sqrt(np.maximum(1 - ((fx - 0.5) / w) ** 2, 0.0))   # warp cross-section
    pf = np.sqrt(np.maximum(1 - ((fy - 0.5) / wf) ** 2, 0.0))  # weft cross-section

    def undulate(along, idx_fixed, warp):
        # along: continuous coordinate along the thread (cell units); crossing centers at k + 0.5
        t = along - 0.5
        k0 = np.floor(t).astype(np.int64)
        f = t - k0
        s = f * f * (3 - 2 * f)
        if warp:
            e0 = np.where(_over(kind, idx_fixed % nu, k0 % nv, table), 1.0,
                          -1.0)
            e1 = np.where(_over(kind, idx_fixed % nu, (k0 + 1) % nv, table),
                          1.0, -1.0)
        else:
            e0 = np.where(_over(kind, k0 % nu, idx_fixed % nv, table), -1.0,
                          1.0)
            e1 = np.where(_over(kind, (k0 + 1) % nu, idx_fixed % nv, table),
                          -1.0, 1.0)
        return e0 * (1 - s) + e1 * s

    ew = undulate(y, i, True)
    ef = undulate(x, j, False)
    hw = np.where(pw > 0, 0.5 + 0.25 * ew + 0.25 * pw, 0.0)
    hf = np.where(pf > 0, 0.5 + 0.25 * ef + 0.25 * pf, 0.0)
    warp_top = hw >= hf
    h = np.maximum(hw, hf)
    ids = np.where(warp_top, i % nu, nu + j % nv)
    cov = ((pw > 0) | (pf > 0)).astype(np.float64)
    return {"": h, "mask": cov, "warp": (warp_top & (pw > 0)).astype(
        np.float64), "id": ids.astype(np.float64), "rand": rnd(ids, seed)}


def _weave_table(img, layer, nu, nv):
    """
    Custom weave: takes the over/under of each crossing from a layer. At the center of crossing (i, j)
    ((i + ½)/nu, (j + ½)/nv) the nearest pixel is taken; channel 0 > 0.5 = warp (vertical) on top.
    Houdini's pattern input only says "a Mono layer gives the over/under arrangement", not how it's sampled -- sampling at crossing
    centers with threshold 0.5 is our own choice. The layer can be any resolution (e.g. paint a small nu x nv image
    and scale it up, or just use a checker / noise).
    """
    name = str(layer).strip()
    if not name:
        raise ValueError("Weave = custom needs a Weave Layer (a layer on the input image)")
    a = getn(img, name)
    Hh, Ww = a.shape[:2]
    jj = np.minimum(((np.arange(nv) + 0.5) / nv * Hh).astype(np.int64), Hh - 1)
    ii = np.minimum(((np.arange(nu) + 0.5) / nu * Ww).astype(np.int64), Ww - 1)
    return a[jj[:, None], ii[None, :], 0] > 0.5


def pattern(img=None, kind="checker", counts="8 8", offset=0.5, gap=0.05,
            bevel=0.1, jitter=1.0, weave="plain", width=0.8, mode="julia",
            c="-0.8 0.156", center="0 0", zoom=1.0, iterations=100,
            modes="3 5", sign="-", line_width=1.5, font="", labels=True,
            seed=0, out_layer="pattern", xres=512, yres=512, bond="offset",
            header_interval=6, chladni_output="pixel_lines", amplitude=1.0,
            amplitude_ratio=1.0, threshold=0.1, smoothing_width=0.05,
            cell_metric="euclidean", lattice="grid", density=1.0,
            density_seed=0, tile_coloring="hue",
            tile_color1="0.85 0.85 0.85", tile_color2="0.6 0.6 0.6",
            outlines=True, outline_width=1.0,
            outline_color="0.08 0.08 0.08", marker_type="text",
            text_mode="letters", marker_size=0.32, marker_coloring="uniform",
            marker_color="0.05 0.05 0.05", marker_color2="1 1 1",
            separate_widths=False, weft_width=0.8, weave_layer=""):
    """
    Pattern entry point. out_layer is the main layer; auxiliary layers are named out_layer_xxx:

      checker  main layer 0/1 (analytic anti-aliasing), _id
      tile     main layer = brick face mask (gaps are 0), _id, _height (bevel), _edge (pixel distance
               to the gap), _rand (one per piece), _uv (0-1 within the piece)
      cell     main layer = cell face mask, _id, _edge (true pixel distance to the cell edge), _dist
               (to the feature point, normalized by the cell's short side), _rand
      uv_grid  main layer = RGB checker image, _id, _uv
      julia    main layer = smooth iteration count / Iterations, _inside, _trap (orbit trap)
      chladni  main layer = nodal lines, _value (the mode itself, signed)
      knit     main layer = height, _mask, _id (stitch), _leg (left 0 right 1), _rand
      weave    main layer = height, _mask, _warp (where the warp is on top), _id (warps 0..nu-1,
               wefts nu..), _rand
    """
    if kind not in PATTERNS:
        raise ValueError(f"Pattern must be one of {PATTERNS}")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    u, v = _pix(W, H)
    nu, nv = _counts(counts)
    if kind == "checker":
        lay = _checker(u, v, W, H, nu, nv)
    elif kind == "tile":
        if bond not in BONDS:
            raise ValueError(f"Bond must be one of {BONDS}")
        if bond == "offset":
            lay = _tile(u, v, W, H, nu, nv, offset, gap, bevel, seed)
        else:
            lay = _tile_bond(u, v, W, H, nu, nv, bond, gap, bevel, seed,
                             header_interval)
    elif kind == "cell":
        lay = _cell(u, v, W, H, nu, nv, jitter, gap, seed, cell_metric,
                    lattice, density, density_seed)
    elif kind == "uv_grid":
        for val_, ok_, nm_ in ((tile_coloring, UVG_TILE_COLORING, "Tile Coloring"),
                               (marker_coloring, UVG_MARKER_COLORING,
                                "Marker Coloring"),
                               (marker_type, UVG_MARKERS, "Marker Type"),
                               (text_mode, UVG_TEXT, "Text Mode")):
            if val_ not in ok_:
                raise ValueError(f"{nm_} must be one of {ok_}")
        lay = _uv_grid(u, v, W, H, nu, nv, font, labels, tile_coloring,
                       tile_color1, tile_color2, outlines, outline_width,
                       outline_color, marker_type, text_mode, marker_size,
                       marker_coloring, marker_color, marker_color2)
    elif kind == "julia":
        if mode not in ("julia", "mandelbrot"):
            raise ValueError("Mode must be one of julia / mandelbrot")
        lay = _julia(u, v, W, H, mode, c, center, zoom, iterations)
    elif kind == "chladni":
        n_, m_ = _vec(modes, 2)
        if sign not in ("+", "-"):
            raise ValueError("Sign must be one of + / -")
        if chladni_output not in CHLADNI_OUT:
            raise ValueError(f"Output Mode must be one of {CHLADNI_OUT}")
        lay = _chladni(u, v, W, H, n_, m_, sign, line_width, chladni_output,
                       amplitude, amplitude_ratio, threshold, smoothing_width)
    elif kind == "knit":
        lay = _knit(u, v, W, H, nu, nv, seed)
    else:
        if weave not in WEAVES:
            raise ValueError(f"Weave must be one of {WEAVES}")
        table = None
        if weave == "custom":
            table = _weave_table(out, weave_layer, nu, nv)
        lay = _weave(u, v, W, H, nu, nv, weave, width, seed,
                     weft_width if separate_widths else None, table)
    return _put_all(out, like, str(out_layer).strip() or "pattern", lay)


# ═══════════════════════════════════════════════════════════ Text
_FONT_CACHE = {}


def _font(font, size):
    """
    Find a font. Empty = Pillow's built-in default font (in Pillow >= 10.1 it's a scalable vector font;
    older versions only have an 11-pixel bitmap font, in which case size has no effect, and the report says so).
    Given a name: first try it as a path, then let Pillow search the system font directories (on Windows, writing
    "arial.ttf" or "msyh.ttc" is enough).
    """
    from PIL import ImageFont
    key = (str(font), int(size))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    name = str(font).strip()
    f = None
    if name:
        for cand in (name, name + ".ttf", name + ".ttc", name + ".otf"):
            try:
                f = ImageFont.truetype(cand, int(size))
                break
            except OSError:
                continue
        if f is None:
            raise ValueError(f"Font '{name}' not found (tried as a path and in the system font directories)")
    else:
        try:
            f = ImageFont.load_default(int(size))
        except TypeError:                       # Pillow < 10.1
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def render_text(text, size, font="", spacing=1.2, align="left"):
    """
    Text -> (h, w) float coverage, **row 0 at the top** (screen convention; the caller flips it).
    FreeType provides anti-aliasing. Multiple lines are laid out at spacing x font size.
    """
    from PIL import Image, ImageDraw
    f = _font(font, size)
    lines = str(text).split("\n")
    d0 = ImageDraw.Draw(Image.new("L", (1, 1)))
    boxes = [d0.textbbox((0, 0), ln or " ", font=f) for ln in lines]
    lh = max(1, int(round(float(size) * float(spacing))))
    wmax = max(b[2] for b in boxes)
    # lay out by the **ink** bounding box, not the line box: the line box has a strip of ascender space at the top, so a single-line
    # "T" centered by line box shifts down 6 pixels (caught by the first draft's tests)
    top = min(b[1] for b in boxes)
    Hh = lh * (len(lines) - 1) + max(b[3] for b in boxes) - top
    im = Image.new("L", (max(1, wmax + 2), max(1, Hh + 2)), 0)
    d = ImageDraw.Draw(im)
    for k, (ln, b) in enumerate(zip(lines, boxes)):
        w = b[2]
        x = {"left": 0, "center": (wmax - w) / 2, "right": wmax - w}[align]
        d.text((x + 1, k * lh - top + 1), ln, fill=255, font=f)
    return np.asarray(im, np.float64) / 255.0


def _stamp_max(canvas, g, x0, y0):
    """Stamp g onto canvas with max, starting at (x0, y0) (may go partly out of bounds)."""
    H, W = canvas.shape[:2]
    gh, gw = g.shape[:2]
    xa, ya = max(0, x0), max(0, y0)
    xb, yb = min(W, x0 + gw), min(H, y0 + gh)
    if xa >= xb or ya >= yb:
        return
    sub = g[ya - y0:yb - y0, xa - x0:xb - x0]
    canvas[ya:yb, xa:xb] = np.maximum(canvas[ya:yb, xa:xb], sub)


ALIGNS = ("left", "center", "right")


def text(img=None, text="Text", font="", size=64, position="0.5 0.5",
         align="center", valign="center", spacing=1.2, color="1 1 1",
         composite_layer="", out_layer="text", xres=512, yres=512):
    """
    Font. Lays text out on the image: out_layer is the coverage mask (0-1, FreeType anti-aliased).
    Position is uv (v up); Align / VAlign pick which point of the text block is aligned to it. If
    Composite Layer is given, Color is composited over that layer by the mask (otherwise a new black layer is created).
    Size is the font size in pixels -- text is inherently laid out in pixels, so adjust it yourself when changing resolution.
    """
    if align not in ALIGNS:
        raise ValueError(f"Align must be one of {ALIGNS}")
    if valign not in ("top", "center", "bottom"):
        raise ValueError("VAlign must be one of top / center / bottom")
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    g = render_text(text, int(size), font, spacing, align)[::-1]  # flip to v up
    gh, gw = g.shape
    pu, pv = _vec(position, 2)
    x0 = pu * W - {"left": 0, "center": gw / 2, "right": gw}[align]
    y0 = pv * H - {"bottom": 0, "center": gh / 2, "top": gh}[valign]
    m = np.zeros((H, W))
    _stamp_max(m, g, int(round(x0)), int(round(y0)))
    put(out, str(out_layer).strip() or "text", m, like)
    cl = str(composite_layer).strip()
    if cl:
        col = _vec(color, 3)
        base = getn(out, cl) if cl in out else np.zeros((H, W, 3))
        C = base.shape[2]
        cc = np.resize(col, C) if C != 4 else np.r_[col, 1.0]
        put(out, cl, base * (1 - m[..., None]) + cc * m[..., None], like)
    return out
