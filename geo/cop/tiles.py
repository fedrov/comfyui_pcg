"""
HeightField Tile Split / Tile Splice (pcg77): process a height field (any COP image) in tiles and splice it back.

━━ Split
Split the image into Columns x Rows tiles: each tile's "core" is [x0, x1) x [y0, y1) (even integer split,
x0 = floor(c*W/cols)), padded by Overlap pixels on every side (no padding at the image border). Outputs a sequence;
the first tile is bottom-left, row-major (tile = r*cols + c). Each tile is an independent image that can be eroded,
noised or detail-upscaled on its own -- the way to go when a large image is too big to compute in one pass.

━━ Splice
Splice the sequence back using the same Columns / Rows / Overlap. Each tile's size (minus the Overlap padding) gives back
the original image size and the core positions; no extra information is needed. Overlap bands are weight-blended:
    along x: the seam between left and right tiles is on the core boundary x0; over [x0 - b, x0 + b] the left tile's weight
    falls smoothly from 1 to 0 (smoothstep), the right tile's the other way, summing to 1 everywhere; b = Overlap x Feather
    the 2D weight is the product of the x and y weights -- at corners where four tiles meet the four weights also sum to 1
Feather = 0 is a hard splice (direct switch at the seam); when tiles processed separately don't match across a seam,
a larger Feather gives a longer transition. Split then splice with nothing in between is **pixel-identical** to the input (verified in tests).
"""
from __future__ import annotations

import numpy as np

from .core import CopImage
from .pixel import getn, put


def _cuts(n, k):
    return [(i * n) // k for i in range(k + 1)]


def tile_split(img, columns=2, rows=2, overlap=16):
    cols, rws, ov = max(1, int(columns)), max(1, int(rows)), max(0, int(overlap))
    W, H = img.xres, img.yres
    if cols > W or rws > H:
        raise ValueError(f"cannot split a {W}x{H} image into {cols}x{rws} tiles")
    xc, yc = _cuts(W, cols), _cuts(H, rws)
    layers = {n: getn(img, n) for n in img.names}
    seq = []
    for r in range(rws):
        for c in range(cols):
            xa = max(0, xc[c] - ov)
            xb = min(W, xc[c + 1] + ov)
            ya = max(0, yc[r] - ov)
            yb = min(H, yc[r + 1] + ov)
            t = CopImage(xb - xa, yb - ya)
            for n, a in layers.items():
                put(t, n, a[ya:yb, xa:xa + (xb - xa)], like=img)
            seq.append(t)
    return seq


def _ramp(n, a0, a1, lo_edge, hi_edge, b):
    """1D weights of length n. The tile's core is [a0, a1) (in tile-local coordinates)."""
    x = np.arange(n) + 0.5
    w = np.ones(n)

    def smooth(t):
        t = np.clip(t, 0.0, 1.0)
        return t * t * (3 - 2 * t)
    if lo_edge:
        w *= (smooth((x - (a0 - b)) / (2 * b)) if b > 0 else (x >= a0) * 1.0)
    if hi_edge:
        w *= (1 - smooth((x - (a1 - b)) / (2 * b)) if b > 0 else (x < a1) * 1.0)
    return w


def tile_splice(seq, columns=2, rows=2, overlap=16, feather=1.0):
    cols, rws, ov = max(1, int(columns)), max(1, int(rows)), max(0, int(overlap))
    if len(seq) != cols * rws:
        raise ValueError(f"sequence has {len(seq)} tiles, Columns x Rows = {cols * rws}")
    b = float(np.clip(feather, 0.0, 1.0)) * ov

    def core_w(c):
        t = seq[c]
        return t.xres - (ov if c > 0 else 0) - (ov if c < cols - 1 else 0)

    def core_h(r):
        t = seq[r * cols]
        return t.yres - (ov if r > 0 else 0) - (ov if r < rws - 1 else 0)
    W = sum(core_w(c) for c in range(cols))
    H = sum(core_h(r) for r in range(rws))
    xc, yc = _cuts(W, cols), _cuts(H, rws)
    for c in range(cols):
        if xc[c + 1] - xc[c] != core_w(c):
            raise ValueError("tile width does not match Columns / Overlap (was it split with different parameters?)")
    for r in range(rws):
        if yc[r + 1] - yc[r] != core_h(r):
            raise ValueError("tile height does not match Rows / Overlap (was it split with different parameters?)")
    names = list(seq[0].names)
    acc = {}
    for r in range(rws):
        for c in range(cols):
            t = seq[r * cols + c]
            xa = max(0, xc[c] - ov)
            ya = max(0, yc[r] - ov)
            if (t.xres, t.yres) != (min(W, xc[c + 1] + ov) - xa,
                                    min(H, yc[r + 1] + ov) - ya):
                raise ValueError(f"tile {r * cols + c} has the wrong size")
            wx = _ramp(t.xres, xc[c] - xa, xc[c + 1] - xa, c > 0, c < cols - 1, b)
            wy = _ramp(t.yres, yc[r] - ya, yc[r + 1] - ya, r > 0, r < rws - 1, b)
            w = wy[:, None] * wx[None, :]
            for n in names:
                a = getn(t, n)
                if n not in acc:
                    acc[n] = np.zeros((H, W, a.shape[2]))
                acc[n][ya:ya + t.yres, xa:xa + t.xres] += w[..., None] * a
    # weights sum to exactly 1 everywhere (the left/right transition is t and 1 - t of the same smoothstep,
    # 2D is the product of both directions), so no need to divide by the total weight again
    out = CopImage(W, H)
    for n in names:
        put(out, n, acc[n], like=seq[0])
    return out
