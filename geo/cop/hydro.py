"""
Hydraulic erosion (with deposition): batches of droplets run downhill, eroding and depositing as they go.

The earlier items in the terrain chain each handle one part: the erosion filter carves gullies (stateless, moves no material), thermal erosion slumps steep slopes to
the angle of repose, stream power cuts a connected river network -- but **none of them transport sediment**: stream power only cuts
and never piles, and lakes are simply treated as "filled by deposition". This one adds **transport + deposition**: water speeds up on steep parts, picks up
material, and drops it where the slope eases and it can no longer carry it -- that is how alluvial fans, floodplains and flat valley floors
form.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Model: Beyer 2015 droplet erosion (with the parameter names of Sebastian Lague's version)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each step, for each droplet:

    direction  <- old direction · inertia − gradient · (1 − inertia), normalized, move one pixel
    Δh         = height at new position − height at old position
    capacity   = max(−Δh, min_slope) · speed · water · capacity
    moving uphill (Δh > 0)   drop min(Δh, sediment) at the old position -- fill the pit first
    sediment > capacity      drop (sediment − capacity) · deposit_rate
    otherwise                erode min((capacity − sediment) · erode_rate, −Δh),
                             taking material from around it with a cone brush of radius radius
    speed²     <- speed² − Δh · gravity (speeds up downhill; Lague's original code has the sign flipped here, so it would
             slow down downhill -- this follows Beyer's paper)
    water      <- water · (1 − evaporate)

Erosion never exceeds −Δh: a droplet never digs below its own next step -- otherwise it would dig a pit, fall
in and dig back and forth. Deposition is spread bilinearly over the four corners, erosion uses a cone brush (when edge cells are outside the image the remaining
weights are renormalized, **not a grain of material is lost**).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Parallelism: a batch of droplets moves in lockstep
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The original algorithm runs droplets one at a time, each seeing the terrain modified by the previous one. Here a batch of batch droplets moves **simultaneously**:
within a step everyone reads the same terrain, and their erosion / deposition is written back together via scatter-add (np.bincount /
torch.index_add_). So the Python loop count = batches x lifetime, not droplets x
lifetime; on the GPU a batch of tens of thousands of droplets is still a single kernel.

The cost is "not seeing each other within a step". A single droplet's change per step is small (at most −Δh), so the effect is limited --
but the larger the batch, the further it deviates from the sequential algorithm. In the tests, with batch = 1 it matches a droplet-by-droplet sequential reference implementation bit for bit;
default batch 16384.

**Not bit-for-bit reproducible on the GPU.** The torch path is float32 and scatters with index_add_ -- on CUDA that is
an atomic add, the order in which the several contributions to one cell are added can differ on every run, and the float32 rounding
changes with it; erosion is also a process that amplifies small differences. On real hardware (4090, 1024², 1 droplet per pixel): CPU
and CUDA means differ by 1.4e-5, and running the same image twice on CUDA differs by 1.7e-6 -- the terrain looks the same, but
it can't be used for per-pixel regression comparison. For bit-for-bit reproducibility use Compute = cpu (numpy's bincount
adds in order). Thermal erosion has no scatter and is unaffected (on real hardware the CPU / CUDA statistics match to the last digit).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Units: height normalized by image width, one pixel per step
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Simulation height = height value x Strength / World Size (whole image width = 1), one pixel per step. This matches
Lague's dimensions (heightmap 0..1, image width a few hundred pixels), so his tuned default parameters work as-is.

The first version used "pixel units" (height / pixel spacing, so slope is the true slope). Physically cleaner, but
typical terrain in the terrain chain has slopes of 0.1..3 in pixel units, two or three orders of magnitude steeper than Lague's dimensions:
the gravity term pushed speeds into the tens and capacity into the hundreds, every step eroded right at the −Δh limit, and one run on 256² doubled
the height range.

So **scaling Strength and World Size up together is exactly equivalent** (x2 is bit-identical in the tests); but
changing resolution is not equivalent -- the height difference per step shrinks with the pixel size, and droplet lifetime and brush radius are in pixels.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Criteria
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · **Mass conservation**: change in total terrain = −(material flowing out over the image edges). Material still carried when lifetime ends is
    dropped in place, not made to vanish. With tile there are no edges, and the total is unchanged step by step
  · Flat ground is bit-for-bit unchanged (no slope means no capacity, and erosion is capped by −Δh = 0)
  · Steep slope meeting flat ground: material comes from the slope and piles at its foot -- an alluvial fan
  · A pit gets filled shallower
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from . import accel as AC
from .heightmap import _texel


END_MODES = ("spread", "lose")


# ═══════════════════════════════════════════════════════════ backend shims
class _NP:
    """numpy path: float64, scatter with bincount (an order of magnitude faster than np.add.at)."""
    is_torch = False

    def arr(self, a, dtype=None):
        return np.asarray(a, dtype or np.float64)

    def iarr(self, a):
        return np.asarray(a, np.int64)

    def zeros(self, n):
        return np.zeros(n)

    def floor_i(self, a):
        return np.floor(a).astype(np.int64)

    def scatter(self, n, idx, w):
        if idx.size == 0:
            return np.zeros(n)
        return np.bincount(idx, w, minlength=n)

    def to_np(self, a):
        return np.asarray(a, np.float64)

    def rand_to(self, a):
        return np.asarray(a, np.float64)

    where = staticmethod(np.where)
    sqrt = staticmethod(np.sqrt)
    minimum = staticmethod(np.minimum)
    maximum = staticmethod(np.maximum)
    hypot = staticmethod(np.hypot)
    cos = staticmethod(np.cos)
    sin = staticmethod(np.sin)

    def any(self, m):
        return bool(m.any())

    def nonzero(self, m):
        return np.flatnonzero(m)

    def sum(self, a):
        return float(np.sum(a))


class _TO:
    """torch path: float32, scatter with index_add_ (an atomic add on CUDA, not bit-for-bit reproducible; see the file header)."""
    is_torch = True

    def __init__(self, t, device):
        self.t = t
        self.dev = device

    def arr(self, a, dtype=None):
        a = np.asarray(a)
        return self.t.as_tensor(a, dtype=self.t.float32, device=self.dev)

    def iarr(self, a):
        return self.t.as_tensor(np.asarray(a), dtype=self.t.int64,
                                device=self.dev)

    def zeros(self, n):
        return self.t.zeros(n, dtype=self.t.float32, device=self.dev)

    def floor_i(self, a):
        return self.t.floor(a).long()

    def scatter(self, n, idx, w):
        out = self.zeros(n)
        if idx.numel():
            out.index_add_(0, idx, w)
        return out

    def to_np(self, a):
        return a.detach().cpu().double().numpy()

    def rand_to(self, a):
        return self.arr(a)

    def where(self, c, a, b):
        t = self.t
        if not isinstance(a, t.Tensor):
            a = t.full_like(c, float(a), dtype=t.float32)
        if not isinstance(b, t.Tensor):
            b = t.full_like(c, float(b), dtype=t.float32)
        return t.where(c, a, b)

    def sqrt(self, a):
        return self.t.sqrt(a)

    def minimum(self, a, b):
        t = self.t
        if not isinstance(b, t.Tensor):
            return t.clamp(a, max=float(b))
        return t.minimum(a, b)

    def maximum(self, a, b):
        t = self.t
        if not isinstance(b, t.Tensor):
            return t.clamp(a, min=float(b))
        return t.maximum(a, b)

    def hypot(self, a, b):
        return self.t.hypot(a, b)

    def cos(self, a):
        return self.t.cos(a)

    def sin(self, a):
        return self.t.sin(a)

    def any(self, m):
        return bool(m.any().item())

    def nonzero(self, m):
        return self.t.nonzero(m).flatten()

    def sum(self, a):
        return float(a.double().sum().item())


def brush(radius):
    """Cone brush: three arrays (dy, dx, weight), weight = max(0, r − distance), summing to 1."""
    r = float(radius)
    k = max(0, int(math.ceil(r)) - 1)
    dy, dx = np.mgrid[-k:k + 1, -k:k + 1]
    d = np.hypot(dx, dy)
    w = np.maximum(r - d, 0.0)
    keep = w > 0
    w = w[keep]
    return dy[keep].astype(np.int64), dx[keep].astype(np.int64), w / w.sum()


# ═══════════════════════════════════════════════════════════════ simulation
def simulate(hp, W, H, n_drops, ops, lifetime=30, inertia=0.05,
             capacity=4.0, min_slope=0.01, erode_rate=0.3, deposit_rate=0.3,
             evaporate=0.01, gravity=4.0, radius=3.0, batch=16384,
             tile=False, soft=None, seed=0, init_speed=1.0, init_water=1.0,
             wet=None, deposit_radius=0.0, end_mode="spread"):
    """
    hp: flattened heights (pixel units, an ops array, updated **in place**).
    Returns a report dict (outflow, amount dropped in place, etc.). If wet is given (an array of length N), water amounts are accumulated
    into it (spread bilinearly at the current position each step).
    """
    N = W * H
    rng = np.random.default_rng(int(seed))
    bdy, bdx, bw = brush(radius)
    K = len(bw)
    bdy_t, bdx_t, bw_t = ops.iarr(bdy), ops.iarr(bdx), ops.arr(bw)
    dbrush = None
    if float(deposit_radius) > 1.0:
        ddy, ddx, dw = brush(deposit_radius)
        dbrush = (ops.iarr(ddy), ops.iarr(ddx), ops.arr(dw))
    edy, edx, ew = brush(max(2.0 * float(radius), float(deposit_radius)))
    ebrush = (ops.iarr(edy), ops.iarr(edx), ops.arr(ew))
    out_flow = 0.0
    dropped = 0.0
    lost = 0.0
    limited = 0.0
    eroded = 0.0
    deposited = 0.0
    steps = 0
    lim_x, lim_y = W - 1, H - 1
    done = 0
    while done < n_drops:
        B = min(int(batch), n_drops - done)
        done += B
        # Spawn points: when not tiling, in [0, W−1) × [0, H−1) -- bilinear needs the +1 neighbour
        sx = rng.random(B) * (W if tile else lim_x)
        sy = rng.random(B) * (H if tile else lim_y)
        ang = rng.random(B) * (2.0 * math.pi)
        px, py = ops.rand_to(sx), ops.rand_to(sy)
        rx, ry = ops.cos(ops.rand_to(ang)), ops.sin(ops.rand_to(ang))
        dx = ops.arr(np.zeros(B))
        dy = ops.arr(np.zeros(B))
        vel = ops.arr(np.full(B, float(init_speed)))
        water = ops.arr(np.full(B, float(init_water)))
        sed = ops.arr(np.zeros(B))
        alive = ops.arr(np.ones(B)) > 0.5
        for _ in range(int(lifetime)):
            if not ops.any(alive):
                break
            steps += 1
            ix, iy = ops.floor_i(px), ops.floor_i(py)
            ox, oy = px - ix, py - iy
            if tile:
                # A float modulo occasionally yields exactly W (−1e-17 % 512 = 512.0), so take the integer part
                # modulo once more to avoid going out of bounds
                ix, iy = ix % W, iy % H
                ix1, iy1 = (ix + 1) % W, (iy + 1) % H
            else:
                ix1, iy1 = ix + 1, iy + 1
            i00, i10 = iy * W + ix, iy * W + ix1
            i01, i11 = iy1 * W + ix, iy1 * W + ix1
            h00, h10, h01, h11 = hp[i00], hp[i10], hp[i01], hp[i11]
            gx = (h10 - h00) * (1 - oy) + (h11 - h01) * oy
            gy = (h01 - h00) * (1 - ox) + (h11 - h10) * ox
            hc = (h00 * (1 - ox) * (1 - oy) + h10 * ox * (1 - oy)
                  + h01 * (1 - ox) * oy + h11 * ox * oy)
            dx = dx * inertia - gx * (1 - inertia)
            dy = dy * inertia - gy * (1 - inertia)
            ln = ops.hypot(dx, dy)
            z = ln <= 0
            dx = ops.where(z, rx, dx / ops.where(z, 1.0, ln))
            dy = ops.where(z, ry, dy / ops.where(z, 1.0, ln))
            nx, ny = px + dx, py + dy
            if tile:
                nx, ny = nx % W, ny % H
                inside = alive
            else:
                inside = alive & (nx >= 0) & (nx < lim_x) & (ny >= 0) \
                    & (ny < lim_y)
                # Those that walk off the image: the carried material flows out
                gone = alive & ~inside
                if ops.any(gone):
                    out_flow += ops.sum(ops.where(gone, sed, 0.0))
            # Height at the new position (out-of-bounds ones are clamped only so a value can be read; they are all masked by inside below)
            if tile:
                qx, qy = nx, ny
            else:
                # 1e-3 rather than 1e-6: in float32, 511 − 1e-6 is just 511.0, and after floor
                # the +1 neighbour goes out of bounds
                qx = ops.minimum(ops.maximum(nx, 0.0), lim_x - 1e-3)
                qy = ops.minimum(ops.maximum(ny, 0.0), lim_y - 1e-3)
            jx, jy = ops.floor_i(qx), ops.floor_i(qy)
            px2, py2 = qx - jx, qy - jy
            if tile:
                jx, jy = jx % W, jy % H
            jx1 = (jx + 1) % W if tile else jx + 1
            jy1 = (jy + 1) % H if tile else jy + 1
            hn = (hp[jy * W + jx] * (1 - px2) * (1 - py2)
                  + hp[jy * W + jx1] * px2 * (1 - py2)
                  + hp[jy1 * W + jx] * (1 - px2) * py2
                  + hp[jy1 * W + jx1] * px2 * py2)
            dh = hn - hc
            cap = ops.maximum(-dh, float(min_slope)) * vel * water \
                * float(capacity)
            dep = inside & ((sed > cap) | (dh > 0))
            ero = inside & ~dep
            a_dep = ops.where(dh > 0, ops.minimum(dh, sed),
                              (sed - cap) * float(deposit_rate))
            a_dep = ops.where(dep, a_dep, 0.0)
            a_ero = ops.minimum((cap - sed) * float(erode_rate), -dh)
            if soft is not None:
                a_ero = a_ero * soft[i00]
            a_ero = ops.where(ero, ops.maximum(a_ero, 0.0), 0.0)
            # ── Deposition: spread bilinearly over the four corners of the old position; erosion: cone brush centred on the cell
            # containing the old position. First scatter the amount each droplet "wants", then clamp per cell (see _limit), and finally
            # **pull back** the fraction actually honoured per cell onto each droplet -- the material accounting balances droplet by droplet
            D = E = None
            if ops.any(dep):
                kd = ops.nonzero(dep)
                a = a_dep[kd]
                if dbrush is None:
                    idx_d = _cat(ops, [i00[kd], i10[kd], i01[kd], i11[kd]])
                    val_d = _cat(ops, [a * (1 - ox[kd]) * (1 - oy[kd]),
                                       a * ox[kd] * (1 - oy[kd]),
                                       a * (1 - ox[kd]) * oy[kd],
                                       a * ox[kd] * oy[kd]]).reshape(4, -1) \
                        .T.reshape(-1)
                    idx_d = idx_d.reshape(4, -1).T.reshape(-1)
                    kdw = 4
                else:
                    idx_d, val_d = _brush_scatter(ops, iy[kd], ix[kd], a,
                                                  dbrush, W, H, tile)
                    kdw = len(dbrush[2])
                D = ops.scatter(N, idx_d, val_d)
            if ops.any(ero):
                ke = ops.nonzero(ero)
                idx_e, val_e = _brush_scatter(ops, iy[ke], ix[ke], a_ero[ke],
                                              (bdy_t, bdx_t, bw_t), W, H,
                                              tile)
                E = ops.scatter(N, idx_e, val_e)
            act_dep = a_dep * 0.0
            act_ero = a_ero * 0.0
            if D is not None:
                rD = _limit(ops, hp, D, W, H, tile, "deposit")
                got = (val_d * rD[idx_d]).reshape(-1, kdw).sum(1)
                act_dep[kd] = got
                hp += D * rD
                deposited += ops.sum(got)
            if E is not None:
                rE = _limit(ops, hp, E, W, H, tile, "erode")
                got = (val_e * rE[idx_e]).reshape(-1, K).sum(1)
                act_ero[ke] = got
                hp -= E * rE
                eroded += ops.sum(got)
            limited += ops.sum(a_dep) - ops.sum(act_dep) \
                + ops.sum(a_ero) - ops.sum(act_ero)
            if wet is not None:
                k = ops.nonzero(alive)
                w_ = water[k]
                wet += ops.scatter(N, _cat(ops, [i00[k], i10[k], i01[k],
                                                 i11[k]]),
                                   _cat(ops, [w_ * (1 - ox[k]) * (1 - oy[k]),
                                              w_ * ox[k] * (1 - oy[k]),
                                              w_ * (1 - ox[k]) * oy[k],
                                              w_ * ox[k] * oy[k]]))
            sed = sed - act_dep + act_ero
            vel = ops.sqrt(ops.maximum(vel * vel - dh * float(gravity), 0.0))
            water = water * (1.0 - float(evaporate))
            px, py = ops.where(inside, nx, px), ops.where(inside, ny, py)
            alive = inside
        # Droplets whose lifetime ended while still carrying material. See "what happens when lifetime ends" in the file header
        if ops.any(alive):
            k = ops.nonzero(alive)
            a = sed[k]
            if end_mode == "lose":
                lost += ops.sum(a)
            else:
                ix, iy = ops.floor_i(px[k]), ops.floor_i(py[k])
                if tile:
                    ix, iy = ix % W, iy % H
                idx, val = _brush_scatter(ops, iy, ix, a, ebrush, W, H,
                                          tile)
                Dd = ops.scatter(N, idx, val)
                # Spreading is clamped too: in a closed basin a whole batch of droplets dies at the basin floor, and unclamped the material would all
                # be dumped in one spot, piling a mound higher than the basin rim (the funnel in the tests: a 0.14 basin piled up to
                # 0.52). What doesn't fit counts as suspended load carried off with the evaporating water, recorded in lost
                rDd = _limit(ops, hp, Dd, W, H, tile, "deposit")
                hp += Dd * rDd
                placed = ops.sum(val * rDd[idx])
                dropped += placed
                lost += ops.sum(a) - placed
    return {"droplets": int(n_drops), "steps": steps,
            "outflow": out_flow, "dropped_at_end": dropped, "lost": lost,
            "eroded": eroded, "deposited": deposited, "brush_cells": K,
            "limited": limited}


PILE_STEP = 1e-3     # max height a cell may rise above its highest neighbour in one step (simulation units, image width = 1)


def _iwhere(ops, m, a):
    if ops.is_torch:
        return ops.t.where(m, a, ops.t.zeros_like(a))
    return np.where(m, a, 0)


def _limit(ops, hp, want, W, H, tile, kind):
    """
    Clamps per cell, returning the fraction r each cell can honour (0..1, a dense array).

    This is the price that "a batch of droplets moving at once" must pay. In the sequential algorithm a droplet erodes at most −Δh and never digs
    a pit of its own; but when hundreds of droplets converge on the same gully within a step, **each sees the same −Δh**, and eroding together gives
    hundreds of times that -- the first version dug 1e15-deep pits within a few steps on 256², and the whole image blew up. So:

      erosion     in one step a cell is dug at most as low as its lowest neighbour (no new pits -- the same
             invariant as "downstream strictly lower" in the stream power batch)
      deposition  in one step a cell piles at most PILE_STEP above its highest neighbour (no spikes; a little
             margin is left so alluvial fans can grow on flat ground)

    The excess is not honoured and stays with the droplet (for erosion, it simply wasn't picked up), so the accounting still balances per droplet.
    """
    cells = ops.nonzero(want > 0)
    r = want * 0.0 + 1.0
    if cells.shape[0] == 0:
        return r
    cy, cx = cells // W, cells % W
    lo = hp[cells] * 0.0 + np.inf
    hi = hp[cells] * 0.0 - np.inf
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            ny, nx = cy + dy, cx + dx
            if tile:
                v = hp[(ny % H) * W + nx % W]
            else:
                ok = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
                v = hp[_iwhere(ops, ok, ny) * W + _iwhere(ops, ok, nx)]
                v_lo = ops.where(ok, v, np.inf)
                v_hi = ops.where(ok, v, -np.inf)
                lo = ops.minimum(lo, v_lo)
                hi = ops.maximum(hi, v_hi)
                continue
            lo = ops.minimum(lo, v)
            hi = ops.maximum(hi, v)
    hc = hp[cells]
    if kind == "erode":
        allow = ops.maximum(hc - lo, 0.0)
    else:
        allow = ops.maximum(hi - hc, 0.0) + PILE_STEP
    w = want[cells]
    r[cells] = ops.minimum(allow / w, 1.0)
    return r


def _brush_scatter(ops, iy, ix, amount, br, W, H, tile):
    """Spreads amount with the brush centred at (iy, ix). Returns (flat indices, values), one row per droplet."""
    bdy, bdx, bw = br
    cy = iy[:, None] + bdy[None, :]
    cx = ix[:, None] + bdx[None, :]
    if tile:
        cy, cx = cy % H, cx % W
        wk = bw[None, :] + cy * 0.0
    else:
        ok = (cy >= 0) & (cy < H) & (cx >= 0) & (cx < W)
        wk = ops.where(ok, bw[None, :] + cy * 0.0, 0.0)
        # At the edge: renormalize by the weights remaining inside the image, not a grain of material lost
        wk = wk / (wk.sum(1, keepdim=True) if ops.is_torch
                   else wk.sum(1, keepdims=True))
        cy = _iwhere(ops, ok, cy)
        cx = _iwhere(ops, ok, cx)
    return (cy * W + cx).reshape(-1), (amount[:, None] * wk).reshape(-1)


def _cat(ops, xs):
    if ops.is_torch:
        return ops.t.cat(xs)
    return np.concatenate(xs)


# ═══════════════════════════════════════════════════════════════ entry point
def hydraulic_erode(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0,
                    droplets_per_pixel=1.0, lifetime=30, inertia=0.05,
                    capacity=4.0, min_slope=0.01, erode_rate=0.3,
                    deposit_rate=0.3, evaporate=0.01, gravity=4.0,
                    radius=3.0, deposit_radius=0.0, end_mode="spread",
                    batch=16384, tile=False,
                    hardness_layer="",
                    seed=0, out_layer=DEFAULT_LAYER, deposit_layer="debris",
                    erosion_layer="", wet_layer="wetness",
                    accumulate_deposit=True, keep=True, compute="auto"):
    """
    Returns (image, report). Parameters are described in the file header; simulated with height normalized by image width, output divided back to height values.

    Output layers (empty = not output):
      deposit_layer  net deposition (height values, >= 0). Named debris by default, and **accumulated** onto an existing
                     debris layer (accumulate_deposit) -- thermal erosion's talus and the
                     alluvium here share one layer, and Splat Map's deposition reads it by default
      erosion_layer  net erosion (height values, >= 0)
      wet_layer      the part of accumulated water from passing droplets **above the baseline** (median), normalized to 0..1
                     by the 99.5th percentile. Where water often flows = rivers and gullies, usable as a mask

    end_mode: a droplet's lifetime ends while it still carries material --
      spread (default) spreads it in place with a 2 x radius brush, clamped just like deposition en route (a cell
             piles at most PILE_STEP above its highest neighbour); what doesn't fit is recorded in lost
      lose   discards it all, as in the original Beyer / Lague (suspended load leaves with the evaporated water), recorded in lost
    Both satisfy Δterrain = −(outflow + lost), verified directly from the output layers in the tests.

    This was changed twice. The first version dropped it bilinearly on four cells: on slopes droplets only eroded and never deposited, and at the end of lifetime
    dumped a whole trip's material on one point, covering the hillshade with pockmarks (std of high-frequency noise on slopes 0.017,
    0.0005 after spreading). The second version spread it without clamping: in closed basins a whole batch of droplets died at the floor, piling a mound
    higher than the rim (funnel 0.14 piled to 0.52).

    compute (pcg65): auto = if the image is on torch, compute there; if on numpy but large enough (>= 256²)
    and CUDA is available, move it over, compute, and move back (only the newly written layers). Real hardware 1024²: numpy 160 s,
    CUDA 12 s -- previously you had to connect COP To Device in front manually to use the GPU. cpu = always numpy.
    """
    if img is None:
        return CopImage(), {}
    orig = img
    img, home, why = AC.pick_backend(img, compute, 24)
    lt = int(lifetime)
    if not 1 <= lt <= 10000:
        raise ValueError("Lifetime must be between 1 and 10000")
    if not 0.0 <= float(inertia) < 1.0:
        raise ValueError("Inertia must be in [0, 1)")
    if not 0.0 <= float(evaporate) < 1.0:
        raise ValueError("Evaporate must be in [0, 1)")
    for nm, v in (("Erode Rate", erode_rate), ("Deposit Rate", deposit_rate)):
        if not 0.0 <= float(v) <= 1.0:
            raise ValueError(f"{nm} must be between 0 and 1")
    if not float(radius) >= 1.0:
        raise ValueError("Radius must be at least 1 pixel")
    if int(batch) < 1:
        raise ValueError("Batch must be at least 1")
    if end_mode not in END_MODES:
        raise ValueError(f"End Mode must be one of {END_MODES}")
    s = float(strength)
    if s == 0.0:
        raise ValueError("Strength cannot be 0 (the output is divided back to height values)")
    xp = img.backend
    W, H = img.xres, img.yres
    N = W * H
    texel = _texel(world_size, W)
    ws = float(world_size)
    if not ws > 0:
        raise ValueError("World Size must be > 0")
    k = s / ws                                   # height value -> simulation units (image width = 1)
    lay = img.need(layer)
    if getattr(xp, "is_torch", False):
        ops = _TO(xp.t, xp.device)
        h0 = lay[:, :, 0].reshape(-1).to(xp.t.float32) * k
        hp = h0.clone()
    else:
        ops = _NP()
        h0 = np.asarray(bk.backend_of(lay).to_numpy(lay),
                        np.float64)[:, :, 0].reshape(-1) * k
        hp = h0.copy()
    soft = None
    hl = str(hardness_layer or "").strip()
    if hl:
        hv = img.need(hl)
        hv = ops.arr(bk.backend_of(hv).to_numpy(hv)[:, :, 0].reshape(-1))
        soft = 1.0 - ops.minimum(ops.maximum(hv, 0.0), 1.0)
    n = max(0, int(round(float(droplets_per_pixel) * N)))
    wet = ops.zeros(N) if str(wet_layer or "").strip() else None
    rep = simulate(hp, W, H, n, ops, lt, float(inertia), float(capacity),
                   float(min_slope), float(erode_rate), float(deposit_rate),
                   float(evaporate), float(gravity), float(radius),
                   int(batch), bool(tile), soft, int(seed), wet=wet,
                   deposit_radius=float(deposit_radius), end_mode=end_mode)
    out = img.copy() if keep else CopImage(W, H)
    inv = 1.0 / k

    def put(name, a):
        a = a.reshape(H, W, 1)
        out.set(name, a if ops.is_torch else xp.asarray(a))

    put(str(out_layer).strip() or DEFAULT_LAYER, hp * inv)
    d = hp - h0
    dl = str(deposit_layer or "").strip()
    if dl:
        dep = ops.maximum(d, 0.0) * inv
        if accumulate_deposit and dl in img:
            prev = img.need(dl)
            prev = ops.arr(bk.backend_of(prev).to_numpy(prev)[:, :, 0]
                           .reshape(-1))
            dep = dep + prev
        put(dl, dep)
    el = str(erosion_layer or "").strip()
    if el:
        put(el, ops.maximum(-d, 0.0) * inv)
    if wet is not None:
        # Droplets are scattered uniformly, so every pixel gets a "baseline" amount of water; rivers / gullies are the **extra**
        # part. So subtract the median and normalize by the 99.5th percentile -- dividing by the maximum directly would
        # squeeze most of the image into 0.5..1, with no contrast as a mask
        wn = ops.to_np(wet)
        base = float(np.median(wn))
        ref = float(np.percentile(wn, 99.5)) - base
        ref = ref if ref > 0 else 1.0
        wv = ops.minimum(ops.maximum((wet - base) * (1.0 / ref), 0.0), 1.0)
        put(str(wet_layer).strip(), wv)
    # Mass accounting converted to world volume: height in simulation units × world width = world height, then × pixel area
    v3 = ws * texel * texel
    rep["mass_before"] = ops.sum(h0) * v3
    rep["mass_after"] = ops.sum(hp) * v3
    for key in ("outflow", "dropped_at_end", "lost", "eroded", "deposited",
                "limited"):
        rep[key] = rep[key] * v3
    rep["compute"] = why
    return AC.bring_back(orig if keep else CopImage(W, H), img, out, home), rep
