"""
HeightField Erode: grid-based hydraulic erosion (virtual pipes) with sediment transport, plus thermal slumping, in one solver.

Why another erosion node. The terrain chain already has four, each missing what this one does:

  · Stream Power      rivers by catchment area, the large-scale dendritic network -- but no water, no deposition
  · Hydraulic Erosion droplets: gullies and deposits, but water exists only along each droplet's path, so there is no
                      water / flow field to texture with, and gullies stay one droplet wide
  · Thermal Erosion   slumping to the angle of repose, debris only
  · Erosion filter    looks eroded, simulates nothing

This is the model behind Houdini's HeightField Erode (Hydro): rain falls on **every cell every step**, water is a real
height field moving through pipes between neighbours, it picks up material where it runs fast and deep, drops it where it
slows, and the same pass slumps over-steep slopes. Its by-products are the masks terrain texturing is built from:
flow (where water ran), water (where it stands), sediment (where water dropped material: valley floors, fans) and
debris (where slopes slumped: scree aprons).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One step (Mei, Decaudin & Hu 2007, "Fast Hydraulic Erosion Simulation and Visualization on GPU"; the sediment is moved
with the water fluxes instead of a semi-Lagrangian back-trace so that material is conserved exactly)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. rain        w += rain (× rain layer)
  2. pipes       each cell has four outflow fluxes; f ← max(0, damping · f + 0.2 · Δ(h + w)) toward each neighbour, then all
                 four are scaled down together so a cell never sends more water than it has
  3. move        water and suspended sediment leave through the same pipes in the same proportion (a cell sending 30 %
                 of its water sends 30 % of its sediment), so sediment is advected by the flow and conserved exactly
  4. velocity    from the net flux through the cell divided by its mean depth (capped at 2 cells / step)
  5. capacity    C = Capacity · max(sin(tilt), Min Slope) · |v| · min(w, Max Depth)
                 below capacity the water erodes Erode Rate × (C − s), above it deposits Deposit Rate × (s − C).
                 A cell is never dug below its lowest 4-neighbour in one step (no pits drilled by a single fast cell)
  6. evaporate   w ← w · (1 − Evaporation); material the shrinking water can no longer carry is dropped next step
  7. thermal     where a slope is steeper than the Talus Angle a fraction (Thermal Rate) of the excess slides to the
                 lower neighbours, in proportion to how much each is too low (mass conserving, Musgrave 1989)

At the end the suspended sediment is deposited where it is, so the terrain balance is exact:
Δ(total terrain) = −(sediment carried off the image edges), as written in the report and checked in the tests.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Units
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Internally heights are in **cells** (world height / pixel size), so slopes are true slopes, the Talus Angle is a real
angle, and rain / Max Depth are in cells of water. Changing the resolution of the same terrain changes the number of
cells a feature spans, so the same parameters carve proportionally finer gullies at a higher resolution -- run a few
hundred steps at low resolution for the big valleys, upsample, then fewer at full resolution for the detail (the
"erode, upres, erode" Houdini workflow).

Edges: water and sediment drain off the image edges (the outside is one cell lower and dry); with Tile they wrap.

numpy (float64) or torch (float32 on CUDA). Each step is ~60 whole-image operations; numpy at 1024² is about 0.25 s per
step, CUDA a few ms.
"""
from __future__ import annotations

import math

import numpy as np

from .core import CopImage, DEFAULT_LAYER
from . import backend as bk
from . import accel as AC
from .heightmap import _texel

_D4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_OPP4 = (1, 0, 3, 2)
_D8 = _D4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))
_OPP8 = (1, 0, 3, 2, 7, 6, 5, 4)


class _Ops:
    """The handful of array operations the solver needs, for numpy or torch."""

    def __init__(self, xp):
        self.torch = bool(getattr(xp, "is_torch", False))
        if self.torch:
            self.t = xp.t
            self.dev = xp.device
            self.dt = xp.t.float32
        else:
            self.dt = np.float64

    def asarr(self, a):
        if self.torch:
            if not hasattr(a, "to"):
                a = self.t.as_tensor(np.asarray(a), device=self.dev)
            return a.to(device=self.dev, dtype=self.dt)
        return np.asarray(bk.backend_of(a).to_numpy(a) if not isinstance(a, np.ndarray) else a, np.float64)

    def idx(self, a):
        return self.t.as_tensor(a, device=self.dev, dtype=self.t.long) if self.torch else a

    def mask(self, a):
        return self.t.as_tensor(a, device=self.dev) if self.torch else a

    def zeros(self, shape):
        return self.t.zeros(shape, device=self.dev, dtype=self.dt) if self.torch else np.zeros(shape)

    def pos(self, a):
        return self.t.clamp(a, min=0.0) if self.torch else np.maximum(a, 0.0)

    def maximum(self, a, b):
        if self.torch:
            return self.t.maximum(a, b) if hasattr(b, "shape") else self.t.clamp(a, min=b)
        return np.maximum(a, b)

    def minimum(self, a, b):
        if self.torch:
            return self.t.minimum(a, b) if hasattr(b, "shape") else self.t.clamp(a, max=b)
        return np.minimum(a, b)

    def where(self, c, a, b):
        if self.torch:
            return self.t.where(c, a, b if hasattr(b, "shape") else self.t.full_like(a, float(b)))
        return np.where(c, a, b)

    def sqrt(self, a):
        return self.t.sqrt(a) if self.torch else np.sqrt(a)

    def stack(self, xs):
        return self.t.stack(xs) if self.torch else np.stack(xs)

    def total(self, a):
        return float(a.double().sum()) if self.torch else float(np.sum(a))

    def np(self, a):
        return a.detach().cpu().numpy().astype(np.float64) if self.torch else a


class _Grid:
    """Neighbour gathers: sh(a, k) = value of a at the k-th neighbour (edge-clamped, or wrapped with tile)."""

    def __init__(self, ops, H, W, tile, dirs):
        self.dirs = dirs
        self.iy, self.ix, self.out = [], [], []
        for dx, dy in dirs:
            ys, xs = np.arange(H) + dy, np.arange(W) + dx
            if tile:
                self.iy.append(ops.idx(ys % H))
                self.ix.append(ops.idx(xs % W))
                self.out.append(None)
            else:
                self.iy.append(ops.idx(np.clip(ys, 0, H - 1)))
                self.ix.append(ops.idx(np.clip(xs, 0, W - 1)))
                o = np.zeros((H, W), bool)
                if dx > 0:
                    o[:, -dx:] = True
                if dx < 0:
                    o[:, :-dx] = True
                if dy > 0:
                    o[-dy:, :] = True
                if dy < 0:
                    o[:-dy, :] = True
                self.out.append(ops.mask(o))

    def sh(self, a, k):
        return a[self.iy[k]][:, self.ix[k]]


METHOD_KEYS = ("iterations", "rain", "evaporation", "capacity", "erode_rate", "deposit_rate", "min_slope",
               "max_depth", "damping", "talus_angle", "thermal_rate")


def heightfield_erode(img, layer=DEFAULT_LAYER, strength=1.0, world_size=1.0, iterations=200, rain=0.02,
                      evaporation=0.02, capacity=1.0, erode_rate=0.1, deposit_rate=0.1, min_slope=0.03,
                      max_depth=2.0, damping=0.9, talus_angle=52.0, thermal_rate=0.05, tile=False,
                      hardness_layer="", rain_layer="", out_layer=DEFAULT_LAYER, flow_layer="flow",
                      water_layer="water", sediment_layer="sediment", debris_layer="debris",
                      erosion_layer="", accumulate_debris=True, keep=True, compute="auto", trace=None):
    """
    Returns (image, report). See the file header for the model; all parameters are in cells (pixel size) and steps.

    Output layers (empty name = not written; heights are converted back to height values):
      out_layer       the eroded height
      flow            where water ran: the water leaving each cell summed over the steps, divided by its 99.5th percentile,
                      clipped to 1 and square-rooted (a 0..1 mask: faint sheet flow on slopes, dendritic rills, solid
                      rivers; discharge grows downstream like a catchment area)
      water           the standing water depth at the end (lakes, rivers), height values
      sediment        net deposition by water (valley floors, alluvial fans), height values, >= 0
      debris          net deposition by thermal slumping (scree aprons), height values, >= 0; added onto an existing
                      debris layer when accumulate_debris (the same layer Thermal Erosion / Hydraulic Erosion write)
      erosion         net removal (water and thermal together), height values, >= 0
    """
    if img is None:
        return CopImage(), {}
    it = int(iterations)
    if not 0 <= it <= 100000:
        raise ValueError("Iterations must be between 0 and 100000")
    for nm, v, lo, hi in (("Evaporation", evaporation, 0.0, 1.0), ("Erode Rate", erode_rate, 0.0, 1.0),
                          ("Deposit Rate", deposit_rate, 0.0, 1.0), ("Damping", damping, 0.0, 1.0),
                          ("Thermal Rate", thermal_rate, 0.0, 1.0)):
        if not lo <= float(v) <= hi:
            raise ValueError(f"{nm} must be between {lo:g} and {hi:g}")
    if float(rain) < 0 or float(capacity) < 0 or float(min_slope) < 0:
        raise ValueError("Rain, Capacity and Min Slope can't be negative")
    if not float(max_depth) > 0:
        raise ValueError("Max Depth must be > 0")
    if not 0.0 <= float(talus_angle) < 90.0:
        raise ValueError("Talus Angle must be in [0, 90)")
    s_ = float(strength)
    if s_ == 0.0:
        raise ValueError("Strength can't be 0 (the output is divided back to height values)")
    orig = img
    img, home, why = AC.pick_backend(img, compute, 24)
    xp = img.backend
    W, H = img.xres, img.yres
    texel = _texel(world_size, W)
    k = s_ / texel                                     # height value -> cells
    ops = _Ops(xp)
    h = ops.asarr(img.need(layer)[:, :, 0]) * k
    h0 = h + 0.0
    soft = None
    hl = str(hardness_layer or "").strip()
    if hl:
        soft = 1.0 - ops.minimum(ops.pos(ops.asarr(img.need(hl)[:, :, 0])), 1.0)
    rl = str(rain_layer or "").strip()
    rain_ = float(rain)
    rain_a = ops.pos(ops.asarr(img.need(rl)[:, :, 0])) * rain_ if rl else None
    g4 = _Grid(ops, H, W, bool(tile), _D4)
    g8 = _Grid(ops, H, W, bool(tile), _D8) if float(thermal_rate) > 0 else None
    tan_t = math.tan(math.radians(float(talus_angle)))
    dist8 = [math.hypot(dx, dy) for dx, dy in _D8]
    w = ops.zeros((H, W))
    s = ops.zeros((H, W))
    f = [ops.zeros((H, W)) for _ in range(4)]
    flow = ops.zeros((H, W))
    deb = ops.zeros((H, W))
    lost = 0.0
    lost_w = 0.0
    damp = float(damping)
    cap, ks, kd = float(capacity), float(erode_rate), float(deposit_rate)
    msin, wmax, ke, tr = float(min_slope), float(max_depth), float(evaporation), float(thermal_rate)
    tiny = 1e-12 if not ops.torch else 1e-8
    for step in range(it):
        w = w + (rain_a if rain_a is not None else rain_)
        Ht = h + w
        # deep water keeps more of its momentum: the steady flux of a pipe is 0.2·Δ/(1 − damping), so with a fixed
        # damping (as in Mei et al.) a river conveys no more than a sheet one cell deep and ponds metres deep along every
        # valley floor. Damping is relaxed with depth (steady flux ∝ 1 + depth, capped at ×3, cf. Manning's
        # q ∝ depth^(5/3)). Raising the pipe gain itself instead goes unstable (odd-even checkerboard in the water)
        dmp = 1.0 - (1.0 - damp) / ops.minimum(1.0 + w, 3.0)
        for i in range(4):
            Hn = g4.sh(h, i) + g4.sh(w, i)
            if g4.out[i] is not None:
                Hn = ops.where(g4.out[i], h - 1.0, Hn)      # outside: one cell lower and dry -> drains off the edge
            f[i] = ops.pos(dmp * f[i] + 0.2 * (Ht - Hn))
        tot = f[0] + f[1] + f[2] + f[3]
        K = ops.where(tot > w, w / ops.maximum(tot, tiny), 1.0)
        f = [fi * K for fi in f]
        frac = [fi / ops.maximum(w, tiny) for fi in f]
        sout = [fr * s for fr in frac]
        win = ops.zeros((H, W))
        sin_ = ops.zeros((H, W))
        for i in range(4):
            j = _OPP4[i]                    # neighbour i sends toward me through its pipe j
            fi = g4.sh(f[j], i)
            si = g4.sh(sout[j], i)
            if g4.out[i] is not None:
                lost += ops.total(ops.where(g4.out[i], sout[i], 0.0))
                lost_w += ops.total(ops.where(g4.out[i], f[i], 0.0))
                fi = ops.where(g4.out[i], 0.0, fi)
                si = ops.where(g4.out[i], 0.0, si)
            win = win + fi
            sin_ = sin_ + si
        wold = w
        w = ops.pos(w - (f[0] + f[1] + f[2] + f[3]) + win)
        s = ops.pos(s - (sout[0] + sout[1] + sout[2] + sout[3]) + sin_)
        wav = ops.maximum(0.5 * (wold + w), 1e-4)
        # velocity from the net flux through the cell (in from the left + out to the right, etc.)
        fl_in = g4.sh(f[0], 1)                              # left neighbour's pipe toward +x
        fr_in = g4.sh(f[1], 0)                              # right neighbour's pipe toward -x
        fu_in = g4.sh(f[2], 3)
        fd_in = g4.sh(f[3], 2)
        if g4.out[0] is not None:
            fl_in = ops.where(g4.out[1], 0.0, fl_in)
            fr_in = ops.where(g4.out[0], 0.0, fr_in)
            fu_in = ops.where(g4.out[3], 0.0, fu_in)
            fd_in = ops.where(g4.out[2], 0.0, fd_in)
        qx = 0.5 * (fl_in - f[1] + f[0] - fr_in)            # discharge (cells² of water per step)
        qy = 0.5 * (fu_in - f[3] + f[2] - fd_in)
        q = ops.sqrt(qx * qx + qy * qy)
        spd = ops.minimum(q / wav, 2.0)
        dep = ops.minimum(w, wmax)
        flow = flow + (f[0] + f[1] + f[2] + f[3])          # water passing through (outflow), any direction
        gx = 0.5 * (g4.sh(h, 0) - g4.sh(h, 1))
        gy = 0.5 * (g4.sh(h, 2) - g4.sh(h, 3))
        g2 = gx * gx + gy * gy
        sina = ops.maximum(ops.sqrt(g2 / (1.0 + g2)), msin)
        C = cap * sina * spd * dep
        er = ks * (C - s)
        if soft is not None:
            er = er * soft
        d = ops.where(s < C, er, -kd * (s - C))              # > 0 erodes
        hmin = ops.minimum(ops.minimum(g4.sh(h, 0), g4.sh(h, 1)), ops.minimum(g4.sh(h, 2), g4.sh(h, 3)))
        d = ops.minimum(d, ops.pos(h - hmin) * 0.5)
        d = ops.maximum(d, -s)                               # can't drop more than it carries (rounding)
        # what is picked up / dropped is taken from / spread over the cell and its 4 neighbours (1/2 + 4 × 1/8): done in
        # place, the 4-pipe flow builds axis-aligned terraces and one-cell step lines on pond floors and plains. Shares that would land outside
        # the image stay in the cell, so material is still conserved exactly
        spread = 0.5 * d
        for i in range(4):
            gi = g4.sh(d, i) * 0.125
            if g4.out[i] is not None:
                gi = ops.where(g4.out[i], d * 0.125, gi)
            spread = spread + gi
        h = h - spread
        s = s + d
        w = w * (1.0 - ke)
        if g8 is not None:
            exc = []
            for i in range(8):
                e = ops.pos(h - g8.sh(h, i) - tan_t * dist8[i])
                if g8.out[i] is not None:
                    e = ops.where(g8.out[i], 0.0, e)
                exc.append(e)
            tot8 = exc[0]
            mx = exc[0]
            for e in exc[1:]:
                tot8 = tot8 + e
                mx = ops.maximum(mx, e)
            mv = tr * 0.5 * mx
            if soft is not None:
                mv = mv * soft
            inv = mv / ops.maximum(tot8, tiny)
            got = ops.zeros((H, W))
            for i in range(8):
                gi = g8.sh(exc[_OPP8[i]] * inv, i)           # neighbour i sends toward me through its direction OPP
                if g8.out[i] is not None:
                    gi = ops.where(g8.out[i], 0.0, gi)       # (the clamped gather would read some other cell)
                got = got + gi
            h = h - mv + got
            deb = deb + got - mv
        if trace is not None:
            trace.append({"h": ops.np(h), "w": ops.np(w), "s": ops.np(s)})
    h = h + s                                                # leftover suspended load settles in place
    inv_k = 1.0 / k
    out = img.copy() if keep else CopImage(W, H)

    def put(name, a):
        out.set(name, a.reshape(H, W, 1) if ops.torch else xp.asarray(a.reshape(H, W, 1)))

    put(str(out_layer).strip() or DEFAULT_LAYER, h * inv_k)
    if str(flow_layer or "").strip():
        fn = ops.np(flow)
        ref = float(np.percentile(fn, 99.5)) if fn.size else 0.0
        put(str(flow_layer).strip(), ops.sqrt(ops.minimum(flow * (1.0 / ref if ref > 0 else 0.0), 1.0)))
    if str(water_layer or "").strip():
        put(str(water_layer).strip(), w * inv_k)
    dtot = h - h0
    if str(sediment_layer or "").strip():
        put(str(sediment_layer).strip(), ops.pos(dtot - deb) * inv_k)
    dl = str(debris_layer or "").strip()
    if dl:
        dd = ops.pos(deb) * inv_k
        if accumulate_debris and dl in img:
            dd = dd + ops.asarr(img.need(dl)[:, :, 0])
        put(dl, dd)
    if str(erosion_layer or "").strip():
        put(str(erosion_layer).strip(), ops.pos(-dtot) * inv_k)
    v3 = texel * texel * texel                               # cells³ -> world volume
    rep = {"iterations": it, "compute": why,
           "mass_before": ops.total(h0) * v3, "mass_after": ops.total(h) * v3,
           "sediment_out": lost * v3, "water_out": lost_w * v3,
           "water_left": ops.total(w) * v3}
    return AC.bring_back(orig if keep else CopImage(W, H), img, out, home), rep
