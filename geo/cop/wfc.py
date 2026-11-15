"""
Wave Function Collapse (after SideFX Labs 2D Wave Function Collapse / WFC Initialize Grid), on images.

The overlapping model (Gumin 2016): the sample image is cut into every N x N window (Pattern Search Size); the
output is a grid where every N x N window is one of those patterns. Each output cell starts as "any pattern", the
cell with the fewest choices left is fixed to one of them (weighted by how often the pattern occurs in the sample,
if Use Observed Sample Pattern Frequency), and the consequence is propagated: a neighbour keeps only the patterns
that agree with some remaining pattern here on their overlap. A cell with no pattern left is a contradiction: the
solve starts again with the next seed, up to Number Of Solve Attempts.

Houdini solves on a point grid and paints the sample in the viewport; here both are images: one pixel (or, with
Sample Grid Size, one cell of a larger picture) is one grid cell, colours are the cell values. The sample's colours
are matched at 8 bits per channel.

    constraints     an optional image at the output grid's resolution: where Constraint Mask (a layer, > 0.5) is
                    set, the cell is fixed to the constraint layer's colour, which must be one of the sample's
                    (Respect User Provided Constraints, WFC Initialize Grid's overrides)
    output layers   the solved colours (Output Layer), and `<layer>_id`: the colour's number in the sample's
                    palette (in order of first appearance, row 0 first), for scattering or instancing by value

A cell's colour is the top-left pixel of its pattern, so with a non-tileable output the last N - 1 rows and columns
are constrained only by the windows that start inside the grid.
"""
from __future__ import annotations

import numpy as np

MAX_PATTERNS = 4096
MAX_CELLS = 512 * 512


def _palette(img8):
    """(H, W, C) uint8 -> ids (H, W), palette (K, C), in order of first appearance."""
    H, W, C = img8.shape
    flat = img8.reshape(-1, C)
    key = np.zeros(len(flat), np.int64)
    for c in range(C):
        key = key * 256 + flat[:, c]
    _, first, inv = np.unique(key, return_index=True, return_inverse=True)
    order = np.argsort(first)
    rank = np.empty(len(order), np.int64)
    rank[order] = np.arange(len(order))
    return rank[inv.reshape(-1)].reshape(H, W), flat[first[order]]


def patterns(ids, n=3, wrap=False, rotations=False):
    """Every n x n window of ids. -> patterns (P, n, n), counts (P,)."""
    H, W = ids.shape
    n = int(n)
    if n < 1 or (not wrap and (n > H or n > W)):
        raise ValueError(f"Pattern Search Size {n} does not fit the {W} x {H} sample")
    src = np.pad(ids, ((0, n - 1), (0, n - 1)), mode="wrap") if wrap else ids
    win = np.lib.stride_tricks.sliding_window_view(src, (n, n)).reshape(-1, n, n)
    if rotations:
        alls = []
        for k in range(4):
            r = np.rot90(win, k, axes=(1, 2))
            alls += [r, r[:, :, ::-1]]
        win = np.concatenate(alls)
    pat, cnt = np.unique(win.reshape(len(win), -1), axis=0, return_counts=True)
    return pat.reshape(-1, n, n), cnt.astype(np.float64)


def _compat(pat):
    """compat[d][a, b]: pattern b may sit at offset d from pattern a. d: 0 = +x, 1 = -x, 2 = +y, 3 = -y."""
    P, n, _ = pat.shape
    if n == 1:
        full = np.ones((P, P), bool)
        return [full, full, full, full]
    r = pat[:, :, 1:].reshape(P, -1)                                # a's right part = b's left part
    l_ = pat[:, :, :-1].reshape(P, -1)
    cx = (r[:, None, :] == l_[None, :, :]).all(-1)
    d = pat[:, 1:, :].reshape(P, -1)
    u = pat[:, :-1, :].reshape(P, -1)
    cy = (d[:, None, :] == u[None, :, :]).all(-1)
    return [cx, cx.T.copy(), cy, cy.T.copy()]


def _solve(pat, cnt, H, W, tile, fixed, rng):
    """One attempt. fixed: (H, W) palette ids, -1 = free. -> (H, W) pattern numbers, or None on a contradiction."""
    P = len(pat)
    comp = _compat(pat)
    wave = np.ones((H, W, P), bool)
    stack = []
    if fixed is not None and (fixed >= 0).any():
        ok = pat[:, 0, 0][None, None, :] == fixed[:, :, None]
        wave = np.where((fixed >= 0)[:, :, None], ok, wave)
        if not wave.any(-1).all():
            return None
        stack = [(int(i), int(j)) for i, j in zip(*np.nonzero(fixed >= 0))]
    left = wave.sum(-1)
    logw = cnt * np.log(cnt)
    noise = rng.random((H, W)) * 1e-6
    DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))

    def propagate():
        while stack:
            i, j = stack.pop()
            here = wave[i, j]
            for d, (di, dj) in enumerate(DIRS):
                a, b = i + di, j + dj
                if tile:
                    a %= H
                    b %= W
                elif a < 0 or a >= H or b < 0 or b >= W:
                    continue
                cur = wave[a, b]
                new = cur & comp[d][here].any(0)
                k = int(new.sum())
                if k == left[a, b]:
                    continue
                if k == 0:
                    return False
                wave[a, b] = new
                left[a, b] = k
                stack.append((a, b))
        return True

    if not propagate():
        return None
    while True:
        open_ = left > 1
        if not open_.any():
            break
        # Shannon entropy of the remaining patterns' weights; the lowest goes first
        wsum = wave @ cnt
        ent = np.log(wsum) - (wave @ logw) / wsum
        ent = np.where(open_, ent + noise, np.inf)
        i, j = np.unravel_index(int(np.argmin(ent)), ent.shape)
        w = wave[i, j] * cnt
        pick = int(rng.choice(P, p=w / w.sum()))
        wave[i, j] = False
        wave[i, j, pick] = True
        left[i, j] = 1
        stack.append((int(i), int(j)))
        if not propagate():
            return None
    return wave.argmax(-1)


def wfc(sample, constraints=None, layer="C", sample_cols=0, sample_rows=0, pattern_size=3, wrap_input=False,
        xres=48, yres=48, rotations=False, respect_constraints=True, constraint_layer="C",
        constraint_mask="mask", tileable=False, seed=0, use_frequency=True, attempts=10, cell_pixels=1,
        out_layer="C"):
    """Solve an output grid from a sample image; see the module docstring. -> CopImage, report dict."""
    from .core import CopImage
    from .pixel import getn, put
    a = getn(sample, layer)
    Hs, Ws = a.shape[:2]
    cols = int(sample_cols) or Ws
    rows = int(sample_rows) or Hs
    if cols > Ws or rows > Hs:
        raise ValueError(f"Sample Grid Size {cols} x {rows} is larger than the {Ws} x {Hs} sample image")
    jj = np.minimum(((np.arange(cols) + 0.5) * Ws / cols).astype(np.int64), Ws - 1)   # cell centres
    ii = np.minimum(((np.arange(rows) + 0.5) * Hs / rows).astype(np.int64), Hs - 1)
    img8 = np.clip(np.rint(a[ii][:, jj] * 255.0), 0, 255).astype(np.int64)
    ids, pal = _palette(img8)
    pat, cnt = patterns(ids, pattern_size, wrap_input, rotations)
    if len(pat) > MAX_PATTERNS:
        raise ValueError(f"The sample has {len(pat)} different {pattern_size} x {pattern_size} patterns (limit "
                         f"{MAX_PATTERNS}): use a smaller sample, fewer colours, or a smaller Pattern Search Size")
    if not use_frequency:
        cnt = np.ones_like(cnt)
    H, W = int(yres), int(xres)
    fixed = None
    if constraints is not None and respect_constraints:
        H, W = constraints.yres, constraints.xres
        cm = str(constraint_mask).strip()
        if cm and cm in constraints:
            msk = getn(constraints, cm)[..., 0] > 0.5
            c8 = np.clip(np.rint(getn(constraints, constraint_layer) * 255.0), 0, 255).astype(np.int64)
            C = pal.shape[1]
            if c8.shape[2] < C:
                c8 = np.concatenate([c8] + [c8[..., -1:]] * (C - c8.shape[2]), -1)
            eq = (c8[:, :, None, :C] == pal[None, None, :, :]).all(-1)        # (H, W, K)
            fid = np.where(eq.any(-1), eq.argmax(-1), -2)
            if (msk & (fid == -2)).any():
                i, j = [int(v[0]) for v in np.nonzero(msk & (fid == -2))]
                raise ValueError(f"Constraint at column {j}, row {i} has a colour the sample does not contain "
                                 f"({(c8[i, j, :C] / 255).round(3).tolist()})")
            fixed = np.where(msk, fid, -1)
    elif constraints is not None:
        H, W = constraints.yres, constraints.xres
    if H * W > MAX_CELLS:
        raise ValueError(f"Output grid {W} x {H} is too large (limit {MAX_CELLS} cells)")
    res = None
    used = 0
    for k in range(max(1, int(attempts))):
        used = k + 1
        res = _solve(pat, cnt, H, W, bool(tileable), fixed, np.random.default_rng([int(seed), k]))
        if res is not None:
            break
    if res is None:
        raise ValueError(f"WFC found no solution in {used} attempts: raise Number Of Solve Attempts, lower Pattern "
                         f"Search Size, turn on Allow Rotations, or relax the constraints / Produce Tileable Output")
    oid = pat[res, 0, 0]
    col = pal[oid].astype(np.float64) / 255.0
    z = max(1, int(cell_pixels))
    if z > 1:
        col = np.repeat(np.repeat(col, z, 0), z, 1)
        oid = np.repeat(np.repeat(oid, z, 0), z, 1)
    out = CopImage(W * z, H * z)
    name = str(out_layer).strip() or "C"
    put(out, name, col)
    put(out, name + "_id", oid.astype(np.float64))
    return out, {"patterns": int(len(pat)), "colours": int(len(pal)), "attempts": used, "grid": [W, H]}
