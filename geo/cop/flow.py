"""
Flow accumulation and river networks: depression filling, flow direction (D8 / MFD), flow accumulation, and fluvial erosion (stream power).

The erosion filter batch noted what it lost: **no continuous river network**; gully depth depends only on local slope, not on how much
water accumulates upstream. This batch fills exactly that gap -- each pixel knows how large an area lies upstream of it, and rivers
grow from there.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The hard part: flow accumulation is an **order-dependent** global operation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A pixel's flow = its own rain + the flow of all upstream pixels. To compute it, upstream must be finished first.
The textbook approach sorts by height from high to low and adds to downstream pixel by pixel -- in numpy that's a
million-iteration Python loop (1024^2).

Here it's done in **topological batches** (a batched Kahn's algorithm): all pixels whose "upstream is all done" form
a batch; pixels within a batch are independent, so the whole batch hands its water downstream vectorized; downstream in-degrees are decremented, and those reaching zero
go into the next batch. The number of Python loop iterations is **the length of the longest flow path** (thousands on real 1024^2 terrain),
not the pixel count.

Walking the same batches in reverse gives exactly the "downstream before upstream" order stream power's implicit solve needs --
one schedule, two uses.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Depression filling: Priority-Flood + ε (Barnes, Lehman & Mulla 2014)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pits in the terrain (local minima) trap water and the river breaks off in the pit. Starting from the outlets (by default the four image edges),
flood inward with a min-heap: each pixel is flooded by its **lowest** processed neighbor, and if it is lower than that
neighbor it is raised to "one ulp above it" (math.nextafter). Result:

  · pits are filled flat and become lakes -- the `lake` layer = fill depth
  · **every non-outlet pixel has a strictly lower neighbor** (the one that flooded it), so
    steepest descent always finds a receiver and water always reaches an outlet. The same holds on flat lake surfaces (a one-ulp
    slope points to the outlet). Flow accumulation does not route lake water down that slope, though: it would draw straight
    0° / 45° lines across every lake. lake_routes sends it along the drowned valley instead

The heap part is sequential and unavoidable: about 3-4 s at 1024^2 (pure Python). But it runs only **once** per run
-- stream power's implicit scheme **never creates new pits** (proof in stream_power's notes),
so later steps never need refilling.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Outlets
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
By default all four image edges are outlets (water flows off the map). With tile there are no edges, so the outlet is the lowest pixel in the image.
If base_layer is given (pixels > 0.5), only it is used -- e.g. water drains only off the south edge, or a
lake / sea mask. Outlet pixels don't send water downstream themselves; in stream power they're the fixed base level.

All numpy-only: both the heap and the batch scheduling are sequential, so an image on CUDA makes one round trip.
"""
from __future__ import annotations

import heapq
import math
from collections import deque

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from .heightmap import _texel

METHODS = ("d8", "rho8", "mfd")
ROUTINGS = ("d8", "rho8")
# (dx, dy): the first 4 are orthogonal directions, the last 4 diagonal
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1),
         (1, 1), (1, -1), (-1, 1), (-1, -1))
_DIST = tuple(math.hypot(dx, dy) for dx, dy in _DIRS)


def _np(a):
    return np.asarray(bk.backend_of(a).to_numpy(a)
                      if not isinstance(a, np.ndarray) else a, np.float64)


# ═══════════════════════════════════════════════════════════════ Outlets
def seeds(shape, tile=False, base=None, h=None):
    """Boolean image of outlet pixels. See "Outlets" in the file header."""
    H, W = shape
    if base is not None:
        s = np.asarray(base, bool)
        if not s.any():
            raise ValueError("Base Layer has no outlets at all (no pixels > 0.5)"
                             " -- the water has nowhere to go")
        return s
    s = np.zeros((H, W), bool)
    if tile:
        s.ravel()[int(np.argmin(h))] = True
    else:
        s[0, :] = s[-1, :] = s[:, 0] = s[:, -1] = True
    return s


# ═══════════════════════════════════════════════════════════════ Depression filling
def priority_fill(h, seed_mask, tile=False):
    """
    Priority-Flood + ε. Returns the filled height (float64, same shape as h).

    Without tile, a ring of "closed" sentinels is padded around, so neighbor indices need no bounds checks -- one fewer
    comparison in the inner loop, about 30% faster at 1024^2. With tile it honestly takes the modulo.

    Barnes 2014's Algorithm 3: raised pixels go into a FIFO (pit queue) instead of the heap and are
    processed before the heap -- large lake surfaces cost O(1) per pixel, not O(log N).
    """
    h = np.asarray(h, np.float64)
    H, W = h.shape
    nxt = math.nextafter
    inf = math.inf
    push, pop = heapq.heappush, heapq.heappop
    if not tile:
        Wp = W + 2
        f = np.full((H + 2) * Wp, np.nan)
        f.reshape(H + 2, Wp)[1:-1, 1:-1] = h
        cl = np.zeros((H + 2, Wp), np.uint8)
        cl[0, :] = cl[-1, :] = cl[:, 0] = cl[:, -1] = 1
        closed = bytearray(cl.ravel().tobytes())
        fl = f.tolist()
        offs = [dy * Wp + dx for dx, dy in _DIRS]
        heap = []
        ii, jj = np.nonzero(seed_mask)
        for p, v in zip(((ii + 1) * Wp + (jj + 1)).tolist(),
                        h[ii, jj].tolist()):
            closed[p] = 1
            heap.append((v, p))
        heapq.heapify(heap)
        pit = deque()
        while heap or pit:
            if pit:
                c = pit.popleft()
                v = fl[c]
            else:
                v, c = pop(heap)
            for o in offs:
                n = c + o
                if closed[n]:
                    continue
                closed[n] = 1
                hn = fl[n]
                if hn <= v:
                    fl[n] = nxt(v, inf)
                    pit.append(n)
                else:
                    push(heap, (hn, n))
        return np.asarray(fl).reshape(H + 2, Wp)[1:-1, 1:-1].copy()
    # tile: modulo
    N = H * W
    fl = h.ravel().tolist()
    closed = bytearray(N)
    heap = []
    for p in np.flatnonzero(seed_mask).tolist():
        closed[p] = 1
        heap.append((fl[p], p))
    heapq.heapify(heap)
    pit = deque()
    while heap or pit:
        if pit:
            c = pit.popleft()
            v = fl[c]
        else:
            v, c = pop(heap)
        cy, cx = divmod(c, W)
        for dx, dy in _DIRS:
            n = ((cy + dy) % H) * W + (cx + dx) % W
            if closed[n]:
                continue
            closed[n] = 1
            hn = fl[n]
            if hn <= v:
                fl[n] = nxt(v, inf)
                pit.append(n)
            else:
                push(heap, (hn, n))
    return np.asarray(fl).reshape(H, W)


# ═══════════════════════════════════════════════════════════════ Flow direction
def _shifted(f, dx, dy, tile):
    """Value of f at (x+dx, y+dy); nan outside the image."""
    H, W = f.shape
    if tile:
        return np.roll(np.roll(f, -dy, 0), -dx, 1)
    p = np.pad(f, 1, constant_values=np.nan)
    return p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]


def _target(dx, dy, H, W, tile):
    """Flat index of each pixel's neighbor toward (dx,dy) (-1 outside the image without tile)."""
    I, J = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    ty, tx = I + dy, J + dx
    if tile:
        return (ty % H) * W + (tx % W)
    ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
    return np.where(ok, ty * W + tx, -1)


def d8(f, seed_mask, tile=False, rho=None):
    """
    Steepest descent: each non-outlet pixel -> its **strictly lower** neighbor with the largest slope (height difference / distance).

    Returns (receiver flat index, -1 = sends nowhere; distance to the receiver, pixels). Ties go to the
    earlier direction in _DIRS -- orthogonal before diagonal, deterministic.

    If rho is given (one [0,1) random number r per pixel) this is **Rho8** (Fairfield & Leymarie
    1991): when comparing slopes in diagonal directions, the distance √2 is replaced by 2 - r. D8 has only 8 directions; on a 15°
    slope all water goes orthogonally and the river network is pulled into 0° / 45° straight lines; under Rho8 the probability of picking the diagonal is exactly
    tan θ, so **the mean flow direction equals the true aspect** (derivation: pick diagonal ⇔ (c+s)/(2-r) > c ⇔
    r > 1 - tan θ, 0 <= θ <= 45°). Verified on a 15° slope in the tests. The returned distance is still the true √2.
    """
    H, W = f.shape
    dg = None if rho is None else 2.0 - np.asarray(rho, np.float64).reshape(H, W)
    # pad a ring of +inf as "outside the image": f - inf = -inf, never picked (it used to pad nan, once per direction;
    # now it pads only once, the 8 directions are slice views of it, and temporaries are reused in place).
    # with tile, padded by wrapping
    p = np.pad(f, 1, mode="wrap") if tile else \
        np.pad(f, 1, constant_values=np.inf)
    best = np.zeros((H, W))
    bd = np.full((H, W), -1, np.int64)
    sl = np.empty((H, W))
    for k, (dx, dy) in enumerate(_DIRS):
        dk = dg if (dg is not None and k >= 4) else _DIST[k]
        np.subtract(f, p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W], out=sl)
        if not (isinstance(dk, float) and dk == 1.0):
            np.divide(sl, dk, out=sl)
        # replace only on strictly greater: ties go to the earlier direction in _DIRS (orthogonal before diagonal);
        # pixels whose max slope <= 0 have no receiver (best starts from 0)
        m = sl > best
        bd[m] = k
        np.maximum(best, sl, out=best)
    # compute the receiver's flat index directly instead of building an index table per direction (that would be 8 HxW tables per step)
    k = bd.ravel()
    sel = np.flatnonzero(k >= 0)
    ks = k[sel]
    DX = np.array([d[0] for d in _DIRS])
    DY = np.array([d[1] for d in _DIRS])
    ty, tx = np.divmod(sel, W)
    ty = ty + DY[ks]
    tx = tx + DX[ks]
    if tile:
        ty %= H
        tx %= W
    rcv = np.full(H * W, -1, np.int64)
    rcv[sel] = ty * W + tx          # without tile the selected neighbor is always inside the image (outside is nan)
    dist = np.ones(H * W)
    dist[sel] = np.asarray(_DIST)[ks]
    rcv[seed_mask.ravel()] = -1
    return rcv, dist


def mfd(f, seed_mask, tile=False, exponent=1.1):
    """
    Multiple flow direction (Freeman 1991): water is split among **all** lower neighbors in proportion to slope^exponent.

    Returns an edge list (src, dst, w), w summing to 1 per src. Larger exponent is closer to D8;
    1.1 is Freeman's empirical value. D8 rivers are one-pixel-wide lines at multiples of 45°; MFD is diffuse "sheet flow" on
    slopes that converges again in channels -- more realistic, but river edges are soft.
    """
    H, W = f.shape
    p = float(exponent)
    S, T = [], []
    for k, (dx, dy) in enumerate(_DIRS):
        s = (f - _shifted(f, dx, dy, tile)) / _DIST[k]
        s = np.where(s > 0, s, 0.0)             # nan -> 0
        S.append(s.ravel())
        T.append(_target(dx, dy, H, W, tile).ravel())
    S = np.stack(S, 1)
    T = np.stack(T, 1)
    S[seed_mask.ravel()] = 0.0
    wgt = S ** p
    tot = wgt.sum(1, keepdims=True)
    wgt = np.where(tot > 0, wgt / np.where(tot > 0, tot, 1.0), 0.0)
    src, kk = np.nonzero(wgt > 0)
    return src, T[src, kk], wgt[src, kk]


# ═══════════════════════════════════════════════════════════ Routing across lakes
def lake_routes(f, h, seed_mask, tile=False):
    """
    Receivers for the pixels of filled lakes, following the **drowned valley** instead of the ε slope.

    After Priority-Flood + ε a lake is flat up to a few ulp, and those ulp increase with breadth-first distance from the
    spill point. Steepest descent on that surface walks Chebyshev rings: every lake turns into ruler-straight 0° / 45° lines
    and parallel hatching, and a long filled valley floor into one straight diagonal. The water level says nothing about
    where the water goes, so this ignores it and looks at the terrain under the water:

      a second priority flood, restricted to lake pixels (f > h), starting from the lake's **exit pixels** (a lake pixel
      with a strictly lower non-lake neighbour, which is its receiver) and always expanding the pixel with the lowest
      **original** height h. Each pixel's receiver is the pixel that reached it.

    The flood runs from the exit down the deepest channel to the bottom of the basin and then spreads up the sides, so
    the tree drains every lake pixel down into the drowned thalweg and along it to the exit -- one channel through the
    lake that bends with the valley, not a hatch of lines. The tree is rooted at the exits, so it has no cycles, and an
    exit's receiver is strictly lower than it, so water still always reaches an outlet.

    Returns (pixel flat indices, their receiver flat indices); empty if there are no lakes. numpy + a heap over lake pixels only.
    """
    f = np.asarray(f, np.float64)
    h = np.asarray(h, np.float64)
    H, W = f.shape
    N = H * W
    fl, hl = f.ravel(), h.ravel()
    lake = (fl > hl) & ~np.asarray(seed_mask).ravel()
    ids = np.flatnonzero(lake)
    if not ids.size:
        return ids, ids
    # neighbour table of the lake pixels only: (8, n_lake), -1 outside the image
    cy, cx = np.divmod(ids, W)
    T = np.empty((8, ids.size), np.int64)
    for k, (dx, dy) in enumerate(_DIRS):
        ty, tx = cy + dy, cx + dx
        if tile:
            T[k] = (ty % H) * W + tx % W
        else:
            ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
            T[k] = np.where(ok, ty * W + tx, -1)
    Tc = np.maximum(T, 0)
    dist = np.asarray(_DIST)[:, None]
    # exits: steepest strictly lower non-lake neighbour
    s = np.where((T >= 0) & ~lake[Tc] & (fl[Tc] < fl[ids]), (fl[ids] - fl[Tc]) / dist, -np.inf)
    k = np.argmax(s, 0)
    ex = np.isfinite(s[k, np.arange(ids.size)])
    rcv = np.full(N, -1, np.int64)
    rcv[ids[ex]] = T[k[ex], np.flatnonzero(ex)]
    pos = np.full(N, -1, np.int64)
    pos[ids] = np.arange(ids.size)
    done = bytearray(ids.size)
    heap = []
    for i in np.flatnonzero(ex).tolist():
        done[i] = 1
        heap.append((hl[ids[i]], fl[ids[i]], i))
    heapq.heapify(heap)
    Tl = T.T.tolist()
    posl = pos.tolist()
    hll = hl.tolist()
    fll = fl.tolist()
    idl = ids.tolist()
    push, pop = heapq.heappush, heapq.heappop
    while heap:
        _, _, i = pop(heap)
        c = idl[i]
        for n in Tl[i]:
            if n < 0:
                continue
            j = posl[n]
            if j < 0 or done[j]:
                continue
            done[j] = 1
            rcv[n] = c
            push(heap, (hll[n], fll[n], j))   # ties (dead-flat floors): the ε order, as before
    return ids, rcv[ids]


# ═══════════════════════════════════════════════════════════ Topological batches
def schedule(N, src, dst):
    """
    Batched Kahn: returns a list of batches (each an index array), upstream batches first.

    Pixels in the same batch are independent (none is upstream of another), so a whole batch can be computed together. Batch count =
    the length of the longest flow path.
    """
    indeg = np.bincount(dst, minlength=N).astype(np.int64)
    order = np.argsort(src, kind="stable")
    dst_s = dst[order]
    outdeg = np.bincount(src, minlength=N)
    start = np.cumsum(outdeg) - outdeg
    frontier = np.flatnonzero(indeg == 0)
    batches = []
    seen = 0
    while frontier.size:
        batches.append(frontier)
        seen += frontier.size
        cnt = outdeg[frontier]
        m = cnt > 0
        fr, cnt = frontier[m], cnt[m]
        if not fr.size:
            break
        tot = int(cnt.sum())
        e = np.repeat(start[fr] - (np.cumsum(cnt) - cnt), cnt) \
            + np.arange(tot)
        d = dst_s[e]
        np.subtract.at(indeg, d, 1)
        frontier = np.unique(d[indeg[d] == 0])
    if seen != N:
        # the flow graph has a cycle -- only possible on unfilled flats where pixels are "each other's receiver". Steepest descent
        # only sends to **strictly lower** neighbors, so normally this can't happen; if it does, report it
        # rather than silently skipping half the pixels
        raise RuntimeError(f"The flow graph has a cycle: {N - seen} pixels can't be placed in topological order")
    return batches


def accumulate(N, src, dst, w, rain, batches):
    """Hand water downstream batch by batch. Returns each pixel's flow (including its own rain)."""
    A = np.asarray(rain, np.float64).ravel().copy()
    order = np.argsort(src, kind="stable")
    src_s, dst_s, w_s = src[order], dst[order], w[order]
    outdeg = np.bincount(src, minlength=N)
    start = np.cumsum(outdeg) - outdeg
    for b in batches:
        cnt = outdeg[b]
        m = cnt > 0
        fr, cnt = b[m], cnt[m]
        if not fr.size:
            continue
        tot = int(cnt.sum())
        e = np.repeat(start[fr] - (np.cumsum(cnt) - cnt), cnt) \
            + np.arange(tot)
        np.add.at(A, dst_s[e], A[src_s[e]] * w_s[e])
    return A


def tree_levels(rcv):
    """
    A single-receiver (D8 / Rho8) flow tree is layered by **number of steps to the outlet**: layer 0 is the roots (rcv < 0,
    outlets), layer k is the donors of layer k-1. Returns a list of layers, downstream first.

    As with schedule (Kahn, layered by "how far from the farthest source"), no pixel in a layer is another's
    receiver, so a whole layer can be computed together; the layer count is also the longest flow path. The difference is that this is a tree: each pixel has only
    one receiver, so "the donors of layer k-1" are naturally distinct -- no need for the np.unique and in-degree decrement schedule does
    per layer. On real hardware 1024^2 Stream Power sorts once per step, and this is the bulk of
    its cost (before pcg65, 100 steps took 31 s).
    """
    N = rcv.size
    src = np.flatnonzero(rcv >= 0)
    dst = rcv[src]
    order = np.argsort(dst, kind="stable")
    don = src[order]                                  # donors sorted by receiver
    ndon = np.bincount(dst, minlength=N)
    start = np.cumsum(ndon) - ndon
    fr = np.flatnonzero(rcv < 0)
    levels = []
    seen = 0
    while fr.size:
        levels.append(fr)
        seen += fr.size
        cnt = ndon[fr]
        tot = int(cnt.sum())
        if tot == 0:
            break
        m = cnt > 0
        f2, c2 = fr[m], cnt[m]
        e = np.repeat(start[f2] - (np.cumsum(c2) - c2), c2) + np.arange(tot)
        fr = don[e]
    if seen != N:
        # some pixels can't reach a root along the receiver chain -- the chain has a cycle. Steepest descent only sends strictly lower,
        # so normally this can't happen; if it does, report it instead of silently undercounting
        raise RuntimeError(f"The flow graph has a cycle: {N - seen} pixels can't reach an outlet")
    return levels


# ═════════════════════════════════════════════════════ Flow Accumulation
def flow_accumulation(img, layer=DEFAULT_LAYER, strength=1.0,
                      world_size=1.0, method="d8", exponent=1.1,
                      fill=True, tile=False, base_layer="", rain_layer="",
                      river_area=0.002, river_softness=0.5,
                      flow_layer="flow", river_layer="river",
                      lake_layer="lake", dir_layer="flow_dir", keep=True,
                      rand_seed=0):
    """
    Flow accumulation. Returns (image, report dict). Adds four layers to the image (leave a layer name empty to skip it):

      flow      upstream catchment area, **world units²** (= upstream pixel count x pixel area x rainfall).
                **In channels** it's resolution independent -- the same river at a different resolution gives about the same number at the same point
                (V-shaped valley 65^2 vs 129^2 in the tests). Not on slopes: parallel sheet flow means each pixel only
                receives a one-pixel-wide strip, which halves when the resolution doubles. So river_area
                is only stable when chosen at "channel magnitude"
      river     river network mask: soft transition to 1 around river_area on a **log** scale.
                softness is the transition width, in "orders of magnitude" (0.5 = half an order of magnitude)
      lake      fill depth from depression filling (height values). Where > 0 is a lake
      flow_dir  unit vector (u, v) of the downstream direction. For D8 it's the direction of that one neighbor; for MFD the
                weighted mean direction. 0 at outlets

    Criteria (in tests): **water conservation** -- the total flowing out of all outlets exactly equals total rainfall; on a slope D8's
    flow equals, pixel by pixel, "how many pixels are upstream in this row"; matches a naive pixel-by-pixel sequential implementation.

    method: d8 = the single steepest neighbor (rivers are one-pixel-wide lines, only 0° / 45° directions);
    rho8 = randomized D8, unbiased mean direction (see d8's notes), rand_seed sets the random numbers;
    mfd = split among all lower neighbors by slope^exponent.

    With fill off, pits aren't filled and water stops when it reaches a pit (flow piles up at the pit bottom and never reaches an outlet).
    """
    if img is None:
        return CopImage(), {}
    if method not in METHODS:
        raise ValueError(f"Method must be one of {METHODS}")
    xp = img.backend
    W, H = img.xres, img.yres
    texel = _texel(world_size, W)
    h = _np(img.need(layer))[:, :, 0] * float(strength)
    tile = bool(tile)
    base = None
    if str(base_layer).strip():
        base = _np(img.need(str(base_layer).strip()))[:, :, 0] > 0.5
    sm = seeds((H, W), tile, base, h)
    f = priority_fill(h, sm, tile) if fill else h
    N = H * W
    if method in ("d8", "rho8"):
        rho = (np.random.default_rng(int(rand_seed)).random(N)
               if method == "rho8" else None)
        rcv, dist = d8(f, sm, tile, rho)
        if fill:
            li, lr = lake_routes(f, h, sm, tile)
            rcv[li] = lr
        src = np.flatnonzero(rcv >= 0)
        dst = rcv[src]
        wts = np.ones(src.size)
    else:
        src, dst, wts = mfd(f, sm, tile, exponent)
        if fill:
            li, lr = lake_routes(f, h, sm, tile)
            if li.size:
                # lake pixels: one receiver along the drowned valley instead of sheet flow on the ε slope
                inl = np.zeros(N, bool)
                inl[li] = True
                keep_ = ~inl[src]
                src = np.concatenate([src[keep_], li])
                dst = np.concatenate([dst[keep_], lr])
                wts = np.concatenate([wts[keep_], np.ones(li.size)])
    rain = np.ones(N)
    rl = str(rain_layer).strip()
    if rl:
        rain = np.maximum(_np(img.need(rl))[:, :, 0].ravel(), 0.0)
    batches = schedule(N, src, dst)
    A = accumulate(N, src, dst, wts, rain, batches) * (texel * texel)
    out = img.copy() if keep else CopImage(W, H)
    A2 = A.reshape(H, W)
    if str(flow_layer).strip():
        out.set(str(flow_layer).strip(), xp.asarray(A2[:, :, None]))
    if str(river_layer).strip():
        ra = float(river_area)
        if not ra > 0:
            raise ValueError("River Area must be > 0")
        sft = max(float(river_softness), 1e-9)
        t = np.clip((np.log10(np.maximum(A2, 1e-300)) - math.log10(ra))
                    / sft + 0.5, 0.0, 1.0)
        out.set(str(river_layer).strip(),
                xp.asarray((t * t * (3 - 2 * t))[:, :, None]))
    if str(lake_layer).strip():
        out.set(str(lake_layer).strip(), xp.asarray(
            (np.maximum(f - h, 0.0) / float(strength))[:, :, None]))
    if str(dir_layer).strip():
        vx = np.zeros(N)
        vy = np.zeros(N)
        I_, J_ = np.divmod(np.arange(N), W)
        ti, tj = np.divmod(dst, W)
        ddx, ddy = tj - J_[src], ti - I_[src]
        if tile:
            ddx = (ddx + W // 2) % W - W // 2
            ddy = (ddy + H // 2) % H - H // 2
        np.add.at(vx, src, wts * ddx)
        np.add.at(vy, src, wts * ddy)
        ln = np.hypot(vx, vy)
        ok = ln > 0
        vx[ok] /= ln[ok]
        vy[ok] /= ln[ok]
        out.set(str(dir_layer).strip(), xp.asarray(
            np.stack([vx, vy], -1).reshape(H, W, 2)))
    outlet_total = float(A[np.flatnonzero(sm.ravel())].sum()) \
        if fill else float("nan")
    rep = {"batches": len(batches), "outlets": int(sm.sum()),
           "rain_total": float(rain.sum() * texel * texel),
           "outlet_total": outlet_total,
           "max_flow": float(A.max()),
           "lake_pixels": int((f > h).sum()) if fill else 0}
    return out, rep


# ═════════════════════════════════════════════════════ Stream Power Erosion
def stream_power(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                 iterations=100, erodibility=0.02, m=0.5, uplift=0.0,
                 uplift_layer="", diffusion=0.0, tile=False, base_layer="",
                 out_layer=DEFAULT_LAYER, flow_layer="flow", routing="rho8",
                 rand_seed=0, trace=None):
    """
    Fluvial erosion (stream power law), FastScape-style implicit solve (Braun & Willett 2013).
    Returns (image, report).

        ∂h/∂t = U − K · A^m · S        (n = 1)

    U is uplift, A is upstream catchment area (world units²), S is the downstream slope. Big rivers (large A) cut
    deep, slopes (small A) barely move -- so a genuinely **continuous, hierarchical river network** grows, which the erosion filter
    can't do.

    ━━ The implicit scheme: why it's unconditionally stable, and why it never creates new pits
    Each step first sets downstream by steepest descent, then updates batch by batch **from downstream to upstream**:

        h_i ← (h_i + U + F_i · h_down) / (1 + F_i)      F_i = K · A_i^m / L_i

    Downstream already has its new value, so this is an exact linear solve, not an explicit difference -- no matter how large the step
    it won't oscillate. And the new h_i is a weighted average of (h_i + U) and h_down: as long as originally
    h_i > h_down old, the new one is also > h_down new (downstream rises by at most U). **Every pixel's original receiver
    is still strictly lower** -- so no new pits appear and depression filling happens only once at the start. In floating point this
    is broken by rounding (the one-ulp lake slope left by filling gets eaten once U is added -- the earliest version
    refilled 19 times at 128^2), so updated values are also clamped above nextafter(h_down), making the inequality strict
    in floating point too.

    Diffusion (explicit Laplacian) raises the floor of V-shaped valleys and really does create pits -- the first version had to
    refill every step and was 4x slower at 256^2. Now diffusion is also added batch by batch **from downstream to upstream**, likewise clamped
    above nextafter(h_down): it diffuses a bit less only on the few pixels where "diffusion would make water flow backwards", and everywhere else
    it's ordinary explicit diffusion. So refills is always 1 (verified in tests); the refill branch is just
    insurance.

    ━━ Slow convergence is real
    The river network **reroutes**: divides creep bit by bit, and one river captures another's headwaters (stream capture). This is
    the native behaviour of stream power landscapes, not a numerical issue -- so on real terrain steady state takes many steps
    to reach. The tests verify the analytic steady-state solution on a slope with fixed downstream direction.

    ━━ Steady state
    After prolonged uplift, the erosion rate equals the uplift rate everywhere. In the discrete scheme this is an **exact** equation:
    F_i · (h_i - h_down) = U. The tests run to steady state and verify it pixel by pixel.

    ━━ Parameters
      erodibility  K. At m = 0.5, K is dimensionless, so results agree across resolutions / world scales
      m            exponent of catchment area; in geomorphology m/n ≈ 0.5
      uplift       uplift per step (world units). 0 = cut only, no growth: carve river valleys into
                   existing terrain. If uplift_layer is given it's multiplied in (0-1, e.g. uplift only the middle)
      routing      d8 / rho8. D8's river network is pulled into 0° / 45° straight lines, rows of parallel gullies
                   (most visible when carving valleys into existing terrain); rho8 (default) re-randomizes the diagonal choice
                   each step, unbiased mean direction, rivers meander. rand_seed sets the random numbers, results
                   are reproducible. Cost: flow directions jitter every step, and the discrete steady-state equation is exact only for d8
      diffusion    hillslope diffusion coefficient (0-0.25, explicit, once per step, pixel units). Rounds slopes and
                   blunts divides; 0 = pure fluvial erosion, knife-cut slopes. Note it's computed per pixel,
                   so the same value rounds differently at a different resolution

    Outlets (the four edges by default) are the fixed base level, neither uplifted nor cut. Depressions are filled once at the start -- lakes are treated as
    **filled by sedimentation** (height is taken directly from the filled surface), a common simplification in terrain generation.

    numpy-only; each step's main cost is the per-layer loop (layer count = longest flow path). pcg65 switched each step's
    layering from Kahn (schedule, one np.unique per layer) to depth layering of the tree (tree_levels),
    and steepest descent's 8 directions to one padding + argmax; several times faster at 1024^2. The order of flow additions
    changed, so results differ from before at rounding level, not bit-identical.
    """
    if img is None:
        return CopImage(), {}
    it = int(iterations)
    if not 0 <= it <= 100000:
        raise ValueError("Iterations must be between 0 and 100000")
    K = float(erodibility)
    if K < 0:
        raise ValueError("Erodibility can't be negative")
    D = float(diffusion)
    if not 0.0 <= D <= 0.25:
        raise ValueError("Diffusion must be between 0 and 0.25 (explicit scheme, > 0.25 is unstable)")
    if routing not in ROUTINGS:
        raise ValueError(f"Routing must be one of {ROUTINGS}")
    rng = np.random.default_rng(int(rand_seed)) if routing == "rho8" else None
    s_ = float(strength)
    if s_ == 0.0:
        raise ValueError("Strength can't be 0")
    xp = img.backend
    W, H = img.xres, img.yres
    N = H * W
    texel = _texel(world_size, W)
    tile = bool(tile)
    h = _np(img.need(layer))[:, :, 0] * s_
    base = None
    if str(base_layer).strip():
        base = _np(img.need(str(base_layer).strip()))[:, :, 0] > 0.5
    sm = seeds((H, W), tile, base, h)
    smf = sm.ravel()
    U = np.full(N, float(uplift))
    ul = str(uplift_layer).strip()
    if ul:
        U = U * np.clip(_np(img.need(ul))[:, :, 0].ravel(), 0.0, None)
    U[smf] = 0.0        # outlets aren't updated anyway (rcv = -1); this line just keeps U itself honest
    h = priority_fill(h, sm, tile)
    refills = 1
    hf = h.ravel().copy()
    A = np.full(N, texel * texel)
    nb_last = 0
    for step in range(it):
        f2 = hf.reshape(H, W)
        rho = None if rng is None else rng.random(N)
        rcv, dist = d8(f2, sm, tile, rho)
        if bool(((rcv < 0) & ~smf).any()):
            # given the two clamps above, this shouldn't be reached; it's just insurance -- if there really is a pit, fill again
            f2 = priority_fill(f2, sm, tile)
            hf = f2.ravel().copy()
            refills += 1
            rcv, dist = d8(f2, sm, tile, rho)
        src = np.flatnonzero(rcv >= 0)
        # layered by "steps to the outlet" (tree_levels), downstream first. Each layer's receiver indices are fetched up front,
        # shared by the three loops below (accumulation, implicit update, diffusion)
        levels = tree_levels(rcv)[1:]                # layer 0 is the outlets, not updated
        lr = [(b, rcv[b]) for b in levels]
        nb_last = len(levels) + 1
        A = np.full(N, texel * texel)
        for b, r in reversed(lr):                    # upstream hands over first
            np.add.at(A, r, A[b])
        F = np.zeros(N)
        F[src] = K * A[src] ** float(m) / (dist[src] * texel)
        hf = hf + 0.0                                # copy, don't modify the previous step's
        for b, r in lr:
            hr = hf[r]
            # in exact arithmetic the new value is always > the receiver's new value (see above); in floating point the
            # "one-ulp slope" left by filling gets eaten by rounding once U is added. Clamping to nextafter
            # keeps "receiver strictly lower" true in floating point too -- otherwise every step would need refilling
            Fb = F[b]
            hf[b] = np.maximum((hf[b] + U[b] + Fb * hr) / (1.0 + Fb),
                               np.nextafter(hr, np.inf))
        if D > 0.0:
            f2 = hf.reshape(H, W)
            p = np.pad(f2, 1, mode="wrap" if tile else "edge")
            lap = (p[1:-1, 2:] + p[1:-1, :-2] + p[2:, 1:-1] + p[:-2, 1:-1]
                   - 4.0 * f2)
            lap = D * lap.ravel()
            for b, r in lr:
                hf[b] = np.maximum(hf[b] + lap[b],
                                   np.nextafter(hf[r], np.inf))
        if trace is not None:
            trace.append({"h": hf.copy(), "rcv": rcv, "F": F, "U": U})
    out = img.copy()
    out.set(str(out_layer).strip() or DEFAULT_LAYER,
            xp.asarray((hf / s_).reshape(H, W, 1)))
    if str(flow_layer).strip():
        out.set(str(flow_layer).strip(), xp.asarray(A.reshape(H, W, 1)))
    return out, {"iterations": it, "batches": nb_last, "refills": refills}
