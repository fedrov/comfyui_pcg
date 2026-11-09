"""
Flow and river networks: Priority-Flood pit filling / D8 / MFD / flow accumulation / stream power fluvial erosion.

━━ Criteria
  · pit filling: matches the brute-force relaxation solution of "minimax path" (within a few ulp); terrain without pits is
    untouched bit for bit; after filling every non-outlet pixel has a **strictly lower** neighbor; lake depth in a bowl = spill point
    height − h
  · accumulation: **water conservation** (D8 / MFD × tile / non-tile, outlet total = total rainfall); on a slope
    D8 accumulation per pixel equals "how many pixels are upstream"; MFD conserves the total per column; the floor of a V-shaped valley
    equals the area of the whole upstream rectangle, consistent between 65² and 129²; matches a naive implementation computed pixel by pixel in order;
    a cycle errors instead of under-counting
  · stream power: after each step the downstream neighbor is strictly lower; pit filling done only once (also with diffusion);
    one step matches a naive per-pixel ordered implicit update; on a slope with fixed flow directions run to steady state,
    **equals the analytic solution per pixel** h_j = Σ U / F_k (negative control: not equal before convergence);
    with m = 0.5 scale ×2 is **bit-for-bit** equivalent; flat ground without uplift stays flat
"""
import math
import os
import sys
import time

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo.cop import CopImage                 # noqa: E402
from comfyui_pcg.geo.cop import flow as FL               # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def L(img, name):
    a = img.need(name)
    if not isinstance(a, np.ndarray):
        a = BK.backend_of(a).to_numpy(a)
    return np.asarray(a, np.float64)


def himg(h, name="C", **more):
    h = np.asarray(h, np.float64)
    lay = {name: h[:, :, None] if h.ndim == 2 else h}
    for k, v in more.items():
        v = np.asarray(v, np.float64)
        lay[k] = v[:, :, None] if v.ndim == 2 else v
    return CopImage(h.shape[1], h.shape[0], lay)


def smooth_noise(rng, H, W, passes=3):
    a = rng.random((H, W))
    for _ in range(passes):
        a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1)
             + np.roll(a, -1, 1)) / 5
    return a


def nbrs(H, W, tile):
    """Flattened index table of each pixel's 8 neighbors (N, 8), −1 outside the image."""
    I, J = np.divmod(np.arange(H * W), W)
    out = np.full((H * W, 8), -1)
    for k, (dx, dy) in enumerate(FL._DIRS):
        ty, tx = I + dy, J + dx
        if tile:
            out[:, k] = (ty % H) * W + tx % W
        else:
            ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
            out[:, k] = np.where(ok, ty * W + tx, -1)
    return out


def minimax_fill(h, seed, tile):
    """Brute force: each pixel = minimum over all paths to an outlet of the path's "highest point" (no ε)."""
    H, W = h.shape
    nb = nbrs(H, W, tile)
    hf = h.ravel()
    w = np.where(seed.ravel(), hf, np.inf)
    while True:
        m = np.full(hf.size, np.inf)
        for k in range(8):
            ok = nb[:, k] >= 0
            m[ok] = np.minimum(m[ok], w[nb[ok, k]])
        w2 = np.where(seed.ravel(), hf, np.maximum(hf, m))
        if np.array_equal(w2, w):
            return w.reshape(H, W)
        w = w2


def has_lower(f, seed, tile):
    H, W = f.shape
    nb = nbrs(H, W, tile)
    ff = f.ravel()
    low = np.zeros(ff.size, bool)
    for k in range(8):
        ok = nb[:, k] >= 0
        low[ok] |= ff[nb[ok, k]] < ff[ok]
    return bool((low | seed.ravel()).all())


def naive_accumulate(f, src, dst, w, rain):
    """Textbook version: by (filled) height from high to low, add to downstream one pixel at a time."""
    A = np.asarray(rain, np.float64).ravel().copy()
    out = {}
    for s_, d_, w_ in zip(src.tolist(), dst.tolist(), w.tolist()):
        out.setdefault(s_, []).append((d_, w_))
    for p in np.argsort(-f.ravel(), kind="stable").tolist():
        for d_, w_ in out.get(p, ()):
            A[d_] += A[p] * w_
    return A


rng = np.random.default_rng(7)

# ═══════════════════════════════════════════════════ 1. Outlets
sec("Outlets")
s = FL.seeds((5, 6))
check("default: all four borders are outlets, the interior isn't",
      bool(s[0].all() and s[-1].all() and s[:, 0].all() and s[:, -1].all()
           and not s[1:-1, 1:-1].any()))
hh = rng.random((5, 6))
s = FL.seeds((5, 6), tile=True, h=hh)
check("tile: only the lowest pixel in the whole image",
      int(s.sum()) == 1 and bool(s.ravel()[np.argmin(hh)]))
err("no outlet at all in Base -> error",
    lambda: FL.seeds((4, 4), base=np.zeros((4, 4))), "no outlets at all")

# ═══════════════════════════════════════════════════ 2. Pit filling
sec("Priority-Flood + ε")
for tile in (False, True):
    for trial in range(3):
        Hh, Ww = 17 + trial * 5, 23 - trial * 3
        h = rng.random((Hh, Ww)) * 10
        sd = FL.seeds((Hh, Ww), tile, None, h)
        f = FL.priority_fill(h, sd, tile)
        ref = minimax_fill(h, sd, tile)
        d = float(np.abs(f - ref).max())
        check(f"{'tile ' if tile else ''}{Hh}×{Ww} random: matches the minimax-path brute-force solution"
              f" (diff {d:.1e})", d < 1e-9 and bool((f >= ref).all()))
        check("  after filling every non-outlet pixel has a strictly lower neighbor",
              has_lower(f, sd, tile))
        check("  outlet pixels and unfilled pixels untouched bit for bit",
              bool((f[sd] == h[sd]).all()
                   and (f[ref == h] - h[ref == h] < 1e-9).all()))
# No pits: a slope is untouched bit for bit
Hh, Ww = 20, 30
JJ, II = np.meshgrid(np.arange(Ww, dtype=float), np.arange(Hh, dtype=float))
plane = 0.1 * JJ + 0.01 * II
f = FL.priority_fill(plane, FL.seeds(plane.shape))
check("terrain without pits (a slope) untouched bit for bit", bool((f == plane).all()))
# Bowl: lake depth = spill point − h
n = 41
yy, xx = (np.mgrid[0:n, 0:n] + 0.5) / n - 0.5
r = np.hypot(xx, yy)
bowl = 1.0 - np.exp(-(r / 0.25) ** 2)
out, rep = FL.flow_accumulation(himg(bowl))
spill = min(bowl[0].min(), bowl[-1].min(), bowl[:, 0].min(),
            bowl[:, -1].min())
want = np.maximum(spill - bowl, 0.0)
lake = L(out, "lake")[..., 0]
check(f"bowl: lake depth = spill point − h (diff {np.abs(lake - want).max():.1e})",
      float(np.abs(lake - want).max()) < 1e-9)
check(f"  lake pixel count matches the report ({rep['lake_pixels']}; analytic lake {(want > 0).sum()}"
      "; the extra ones are pixels whose height exactly equals the spill point and got raised by a few ulp)",
      rep["lake_pixels"] == int((lake > 0).sum())
      and bool((lake > 0)[want > 0].all())
      and float(lake[(lake > 0) & (want == 0)].max(initial=0)) < 1e-12)

o_s, _ = FL.flow_accumulation(himg(bowl), strength=2.5)
check("  Strength = 2.5: lake layer still in input units (same as Strength = 1)",
      float(np.abs(L(o_s, "lake")[..., 0] - lake).max()) < 1e-12)

# ═══════════════════════════════════════════════════ 3. Accumulation
sec("Flow accumulation")
W_, H_ = 24, 10
JJ, II = np.meshgrid(np.arange(W_, dtype=float), np.arange(H_, dtype=float))
ramp = (JJ + 0.5) / W_                     # downhill towards −x
base = np.zeros((H_, W_))
base[:, 0] = 1
tex = 1.0 / W_
out, rep = FL.flow_accumulation(himg(ramp, base=base), base_layer="base")
A = L(out, "flow")[..., 0]
check("slope D8: accumulation per pixel = (W − j) × pixel area",
      float(np.abs(A - (W_ - JJ) * tex * tex).max()) < 1e-15)
dv = L(out, "flow_dir")
check("  flow_dir: (−1, 0) everywhere except outlets, 0 at outlets",
      bool((dv[:, 1:, 0] == -1).all() and (dv[:, 1:, 1] == 0).all()
           and (dv[:, 0] == 0).all()))
out2, _ = FL.flow_accumulation(
    himg(ramp, base=base, rain=np.full((H_, W_), 2.0)), base_layer="base",
    rain_layer="rain")
check("  Rain Layer = 2: accumulation exactly doubles",
      bool((L(out2, "flow") == 2 * L(out, "flow")).all()))
out3, rep3 = FL.flow_accumulation(
    himg(ramp, base=base, rain=np.full((H_, W_), -1.0)), base_layer="base",
    rain_layer="rain")
check("  negative rain counts as 0", float(L(out3, "flow").max()) == 0.0
      and rep3["rain_total"] == 0.0)
outm, repm = FL.flow_accumulation(himg(ramp, base=base), base_layer="base",
                                  method="mfd")
Am = L(outm, "flow")[..., 0]
cs = Am.sum(0) / (tex * tex)
check(f"slope MFD: total per column = H × (W − j) (diff {np.abs(cs - H_ * (W_ - np.arange(W_))).max():.1e})",
      float(np.abs(cs - H_ * (W_ - np.arange(W_))).max()) < 1e-9)
for ex_ in (1.1, 4.0):
    sd_ = np.zeros((H_, W_), bool)
    sd_[:, 0] = True
    src_, dst_, w_ = FL.mfd(ramp, sd_, False, ex_)
    p0 = 5 * W_ + 7                        # a pixel in the middle
    ww = dict(zip(dst_[src_ == p0].tolist(), w_[src_ == p0].tolist()))
    ratio = ww[p0 - 1] / ww[p0 - 1 + W_]
    check(f"  MFD exponent {ex_}: orthogonal / diagonal weight ratio = √2^p = "
          f"{2 ** (ex_ / 2):.4f}", abs(ratio - 2 ** (ex_ / 2)) < 1e-12,
          f"{ratio:.6f}")
check("  MFD really disperses (middle rows < border rows, not the per-pixel D8 value)",
      float(np.abs(Am - A).max()) > 1e-6)
dvm = L(outm, "flow_dir")
check("  flow_dir of MFD middle rows is also (−1, 0) (up/down symmetry cancels)",
      float(np.abs(dvm[1:-1, 1:, 0] + 1).max()) < 1e-12
      and float(np.abs(dvm[1:-1, 1:, 1]).max()) < 1e-12)

# Water conservation
for method in ("d8", "mfd"):
    for tile in (False, True):
        h = smooth_noise(rng, 40, 52) + 0.05 * rng.random((40, 52))
        _, rp = FL.flow_accumulation(himg(h), method=method, tile=tile,
                                     world_size=3.0)
        rel = abs(rp["outlet_total"] - rp["rain_total"]) / rp["rain_total"]
        check(f"{method.upper()} {'tile' if tile else 'non-tile'}: outlet total = "
              f"total rainfall (relative diff {rel:.1e}, {rp['batches']} batches)", rel < 1e-12)

# V-shaped valley: floor = whole upstream rectangle, consistent across two resolutions
for n_ in (65, 129):
    JJ, II = np.meshgrid(np.arange(n_, dtype=float),
                         np.arange(n_, dtype=float))
    x, y = (JJ + 0.5) / n_, (II + 0.5) / n_
    vv = np.abs(x - 0.5) + 0.2 * y
    b = np.zeros((n_, n_))
    b[0, :] = 1
    o, _ = FL.flow_accumulation(himg(vv, base=b), base_layer="base",
                                world_size=2.0)
    Av = L(o, "flow")[..., 0]
    c = (n_ - 1) // 2
    t_ = 2.0 / n_
    want = (n_ - np.arange(n_)) * n_ * t_ * t_
    check(f"V-shaped valley {n_}²: floor per pixel = area of the whole upstream rectangle",
          float(np.abs(Av[1:, c] - want[1:]).max()) < 1e-12)
    mid = Av[n_ // 2, c]
    check(f"  catchment area at the valley midpoint {mid:.4f} ≈ half the world area 2.0 (independent of resolution)",
          abs(mid - 2.0) < 0.05)

# Matches the naive implementation
for method in ("d8", "mfd"):
    for tile in (False, True):
        h = smooth_noise(rng, 21, 27) * 3 + rng.random((21, 27)) * 0.1
        sd = FL.seeds(h.shape, tile, None, h)
        f = FL.priority_fill(h, sd, tile)
        if method == "d8":
            rcv, _ = FL.d8(f, sd, tile)
            src = np.flatnonzero(rcv >= 0)
            dst, w = rcv[src], np.ones(src.size)
        else:
            src, dst, w = FL.mfd(f, sd, tile, 1.1)
        rain = rng.random(h.size)
        got = FL.accumulate(h.size, src, dst, w, rain,
                            FL.schedule(h.size, src, dst))
        ref = naive_accumulate(f, src, dst, w, rain)
        d = float(np.abs(got - ref).max() / ref.max())
        check(f"{method.upper()} {'tile' if tile else 'non-tile'}: batched accumulation = "
              f"naive per-pixel ordered implementation (relative diff {d:.1e})", d < 1e-12)
        if method == "mfd":
            tot = np.bincount(src, w, minlength=h.size)
            ns = ~sd.ravel()
            check("  MFD weights of each non-outlet pixel sum to 1, outlets send nothing",
                  float(np.abs(tot[ns] - 1).max()) < 1e-12
                  and float(tot[sd.ravel()].max(initial=0)) == 0.0)
err("cycle in the flow graph -> error, not silent under-counting",
    lambda: FL.schedule(3, np.array([0, 1]), np.array([1, 0])), "has a cycle")

# No pit filling
out, rp = FL.flow_accumulation(himg(bowl), fill=False)
Ab = L(out, "flow")[..., 0]
cz = np.unravel_index(np.argmin(bowl), bowl.shape)
check("no pit filling: water stays at the pit bottom (accumulation there = area of the whole basin, far more than 1 pixel)",
      Ab[cz] > 50 / n ** 2 and float(L(out, "lake").max()) == 0.0)
check("  without pit filling the outlet total in the report is nan (meaningless)",
      math.isnan(rp["outlet_total"]))

# Ties: on a ridge left and right are equally steep; take (+1, 0), which comes first in _DIRS -- deterministic
rg = -np.abs(np.arange(15.0) - 7)[None, :].repeat(9, 0)
rcv_, _ = FL.d8(rg, FL.seeds(rg.shape))
ridge = np.arange(1, 8) * 15 + 7
check("D8 ties: ridge pixels always go +x (the one earlier in _DIRS)",
      bool((rcv_[ridge] == ridge + 1).all()))

# Rho8: mean flow direction on a 15° slope is unbiased; D8 all goes orthogonal (22.5° is exactly a D8 tie point, don't use it)
th = math.radians(15.0)
Rn = 200
JJ, II = np.meshgrid(np.arange(Rn, dtype=float), np.arange(Rn, dtype=float))
tilt = -(math.cos(th) * JJ + math.sin(th) * II)       # downhill towards (cos θ, sin θ)
sdr = FL.seeds(tilt.shape)
inner = ~sdr.ravel()
for nm, rho in (("D8", None),
                ("Rho8", np.random.default_rng(5).random(Rn * Rn))):
    rc_, _ = FL.d8(tilt, sdr, False, rho)
    q = np.flatnonzero(inner)
    dy_, dx_ = np.divmod(rc_[q], Rn)
    ang = math.degrees(math.atan2((dy_ - q // Rn).mean(),
                                  (dx_ - q % Rn).mean()))
    if rho is None:
        check(f"15° slope D8: mean flow direction {ang:.2f}° (all orthogonal = 0°, biased)",
              abs(ang) < 1e-9)
    else:
        pd = float(((dy_ - q // Rn) != 0).mean())
        check(f"  Rho8: fraction choosing diagonal {pd:.4f} ≈ tan 15° = "
              f"{math.tan(th):.4f}, mean flow direction {ang:.2f}° ≈ 15° (unbiased)",
              abs(pd - math.tan(th)) < 0.01 and abs(ang - 15.0) < 0.5)
r1 = L(FL.flow_accumulation(himg(bowl), method="rho8", rand_seed=3)[0],
       "flow")
r2 = L(FL.flow_accumulation(himg(bowl), method="rho8", rand_seed=3)[0],
       "flow")
r3, rp3 = FL.flow_accumulation(himg(bowl), method="rho8", rand_seed=4)
check("Rho8: same rand_seed reproducible bit for bit, different seed changes it; water still conserved",
      bool((r1 == r2).all()) and not bool((r1 == L(r3, "flow")).all())
      and abs(rp3["outlet_total"] - rp3["rain_total"]) < 1e-12)

# No pit filling + flats: pixels on a flat have no strictly lower neighbor and must not point at each other in a cycle
pl = np.minimum(ramp, 0.5)
pl[:, :] = np.where(ramp > 0.5, ramp, 0.5)
out, rp = FL.flow_accumulation(himg(pl), fill=False)
Ap = L(out, "flow")[..., 0]
check("no pit filling, with flats: no cycle reported; pixels inside the flat only have their own rain (no downstream, no upstream)",
      bool(np.all(Ap[3:-3, 3:W_ // 2 - 2] == tex * tex)))

# River mask
out, _ = FL.flow_accumulation(himg(ramp, base=base), base_layer="base",
                              river_area=4 * tex * tex, river_softness=0.5)
rv = L(out, "river")[..., 0]
Ar = L(out, "flow")[..., 0]
at = np.isclose(Ar, 4 * tex * tex)
check("river: exactly 0.5 where catchment area = River Area",
      bool(np.abs(rv[at] - 0.5).max() < 1e-12))
o_ = np.argsort(Ar.ravel())
check("  monotonically non-decreasing with catchment area", bool((np.diff(rv.ravel()[o_]) >= -1e-15).all()))
check("  saturates to 1 / 0 at softness/2 orders of magnitude above / below",
      bool((rv[Ar >= 4 * tex * tex * 10 ** 0.25] == 1).all()
           and (rv[Ar <= 4 * tex * tex * 10 ** -0.25] == 0).all()))
# Across a lake: water follows the drowned valley, not the ε slope of pit filling.
# A V-shaped valley whose floor snakes (centre y = 64 + 18 sin(x / 14)) and drains to the left edge, dammed at x = 16:
# behind the dam a winding lake ~90 px long. The ε slope (breadth-first distance to the spill point) sends the water
# across the lake in straight lines; the drowned valley floor is the sine curve.
nl_ = 128
yy_, xx_ = np.mgrid[0:nl_, 0:nl_].astype(float)
dv_ = yy_ - (64 + 18 * np.sin(xx_ / 14.0))
hv = 0.001 * xx_ + 0.002 * np.abs(dv_) + 0.1 * (np.abs(xx_ - 16) < 1.5)
smv = FL.seeds(hv.shape, False, None, hv)
fv = FL.priority_fill(hv, smv)
lkv = fv > hv


def _acc(r):
    s_ = np.flatnonzero(r >= 0)
    return FL.accumulate(r.size, s_, r[s_], np.ones(s_.size), np.ones(r.size),
                         FL.schedule(r.size, s_, r[s_])).reshape(hv.shape)


def _off(A_):     # per lake column x = 30..99: how far the column's biggest flow is from the drowned valley floor
    return [abs(dv_[np.argmax(np.where(lkv[:, c], A_[:, c], -1)), c]) for c in range(30, 100)]


ov, _ = FL.flow_accumulation(himg(hv))
offv = _off(L(ov, "flow")[..., 0])
check("lake: the main channel follows the drowned valley floor (every column within 1 px of the sine centre)",
      bool(lkv.sum() > 3000 and max(offv) <= 1.0), (int(lkv.sum()), round(max(offv), 2)))
r_eps, _ = FL.d8(fv, smv)
off_eps = _off(_acc(r_eps))
check("  negative control: steepest descent on the ε slope cuts straight across (> 15 px off the floor somewhere)",
      max(off_eps) > 15, round(max(off_eps), 1))
li_, lr_ = FL.lake_routes(fv, hv, smv)
check("  every lake pixel gets a receiver; water is conserved for D8, Rho8 and MFD",
      bool(li_.size == lkv.sum() and (lr_ >= 0).all()) and all(
          abs(FL.flow_accumulation(himg(hv), method=mt)[1]["outlet_total"] - 1.0) < 1e-9
          for mt in ("d8", "rho8", "mfd")))
rnd = np.random.default_rng(3).random((48, 48))
for _ in range(3):
    rnd = (rnd + np.roll(rnd, 1, 0) + np.roll(rnd, 1, 1)) / 3
okr = True
for mt in ("d8", "rho8", "mfd"):
    for tl in (False, True):
        _, rp_ = FL.flow_accumulation(himg(rnd), method=mt, tile=tl)
        okr &= rp_["lake_pixels"] > 50 and abs(rp_["outlet_total"] - rp_["rain_total"]) < 1e-12
check("  pitted noise (with and without tile): no cycle, water conserved, for all three methods", bool(okr))

o4, _ = FL.flow_accumulation(himg(ramp), flow_layer="", river_layer="",
                             lake_layer="", dir_layer="flow_dir",
                             keep=False)
check("empty layer name: not output; keep = False leaves only the output layers",
      sorted(o4.names) == ["flow_dir"])

# tile: flow_dir across the seam
Tn = 32
JJ, II = np.meshgrid(np.arange(Tn, dtype=float), np.arange(Tn, dtype=float))
wave = -np.cos(2 * np.pi * (JJ - 0.3) / Tn) + 0.001 * II   # valley floor near j = 0
o, _ = FL.flow_accumulation(himg(wave), tile=True)
dt_ = L(o, "flow_dir")
check("tile: flow_dir across the seam is still a unit-length neighbor direction (not ±(W−1))",
      float(np.abs(dt_).max()) <= 1.0 + 1e-12
      and float(np.abs(np.hypot(dt_[..., 0], dt_[..., 1])[
          np.hypot(dt_[..., 0], dt_[..., 1]) > 0] - 1).max()) < 1e-12)
check("  direction across the seam is right: the rightmost column goes +x (across the left/right seam to j = 0), column 1 goes −x; "
      "the top pixel of the valley floor column goes +v (across the top/bottom seam to the lower row 0)",
      bool((dt_[:, -1, 0] > 0).all() and (dt_[:-1, 1, 0] < 0).all()
           and dt_[-1, 0, 1] == 1.0))

# ═══════════════════════════════════════════════════ 4. Stream power
sec("Stream power")
h0 = smooth_noise(rng, 40, 48) * 0.05
tr = []
o, rp = FL.stream_power(himg(h0), iterations=40, erodibility=0.05,
                        uplift=1e-3, trace=tr)
okk = True
for t_ in tr:
    hh_, rc = t_["h"], t_["rcv"]
    s_ = rc >= 0
    okk &= bool((hh_[s_] > hh_[rc[s_]]).all())
check("after each step, every pixel is strictly higher than its downstream neighbor", okk)
check(f"pit filling done only once (refills = {rp['refills']})", rp["refills"] == 1)
tr = []
o, rp = FL.stream_power(himg(h0), iterations=40, erodibility=0.05,
                        uplift=1e-3, diffusion=0.1, trace=tr)
okk = all(bool((t_["h"][t_["rcv"] >= 0] > t_["h"][t_["rcv"][
    t_["rcv"] >= 0]]).all()) for t_ in tr)
check(f"also with diffusion: strictly higher than downstream, filled once (refills = {rp['refills']})",
      okk and rp["refills"] == 1)
for rt in FL.ROUTINGS:
    tr = []
    o, rp = FL.stream_power(himg(h0), iterations=25, erodibility=0.05,
                            uplift=1e-3, diffusion=0.05, routing=rt,
                            rand_seed=9, trace=tr)
    okk = all(bool((t_["h"][t_["rcv"] >= 0] > t_["h"][t_["rcv"][
        t_["rcv"] >= 0]]).all()) for t_ in tr)
    o2, _ = FL.stream_power(himg(h0), iterations=25, erodibility=0.05,
                            uplift=1e-3, diffusion=0.05, routing=rt,
                            rand_seed=9)
    check(f"routing = {rt}: strictly higher than downstream, filled once, same seed reproducible bit for bit",
          okk and rp["refills"] == 1
          and bool((L(o, "C") == L(o2, "C")).all()))
_sp = lambda rt, sd: L(FL.stream_power(
    himg(h0), iterations=10, erodibility=0.05, uplift=1e-3, routing=rt,
    rand_seed=sd)[0], "C")
check("  rho8 really uses random numbers: differs from d8 and with a different seed; d8 ignores seed",
      not bool((_sp("rho8", 1) == _sp("d8", 1)).all())
      and not bool((_sp("rho8", 1) == _sp("rho8", 2)).all())
      and bool((_sp("d8", 1) == _sp("d8", 2)).all()))
err("unknown Routing", lambda: FL.stream_power(himg(h0), routing="x"),
    "Routing")
# Bug in pcg55's first version: ulp lake surfaces left by pit filling got eaten by rounding once uplift was added -> refilled every step
hn = np.random.default_rng(1).random((64, 64)) * 1e-3
o, rp = FL.stream_power(himg(hn), iterations=30, erodibility=0.05,
                        uplift=1e-3)
check(f"large ulp lake surfaces + uplift: pit filling still done only once (refills = {rp['refills']}; "
      "over ten times without clamping)", rp["refills"] == 1)
# One step = naive per-pixel implicit update
hs = smooth_noise(rng, 15, 19) * 0.3
sd = FL.seeds(hs.shape)
f = FL.priority_fill(hs, sd)
tex = 1.0 / 19
rcv, dist = FL.d8(f, sd)
src = np.flatnonzero(rcv >= 0)
Aa = FL.accumulate(hs.size, src, rcv[src], np.ones(src.size),
                   np.full(hs.size, tex * tex),
                   FL.schedule(hs.size, src, rcv[src]))
U_, K_ = 2e-3, 0.3
ref = f.ravel().copy()
for p in np.argsort(f.ravel(), kind="stable").tolist():
    if rcv[p] >= 0:
        F_ = K_ * Aa[p] ** 0.5 / (dist[p] * tex)
        ref[p] = max((ref[p] + U_ + F_ * ref[rcv[p]]) / (1 + F_),
                     np.nextafter(ref[rcv[p]], np.inf))
o, _ = FL.stream_power(himg(hs), iterations=1, erodibility=K_, uplift=U_,
                       routing="d8")
d = float(np.abs(L(o, "C")[..., 0].ravel() - ref).max())
check(f"one step = implicit update per pixel from low to high (diff {d:.1e})", d < 1e-15)
o, _ = FL.stream_power(himg(hs), iterations=0)
check("0 steps: output = pit-filled input",
      bool((L(o, "C")[..., 0] == FL.priority_fill(hs, sd)).all()))

# Steady-state analytic solution: slope with fixed flow directions
Wn, Hn = 24, 6
JJ, II = np.meshgrid(np.arange(Wn, dtype=float), np.arange(Hn, dtype=float))
sl = 1e-3 * (JJ + 0.5) / Wn
bs = np.zeros((Hn, Wn))
bs[:, 0] = 1
K_, U_ = 0.05, 1e-3
Fk = K_ * np.sqrt(Wn - np.arange(Wn))           # A = (W−j)·tex²,L = tex
want = sl[0, 0] + np.concatenate([[0.0], np.cumsum(U_ / Fk[1:])])
for its, conv in ((30, False), (4000, True)):
    tr = []
    o, _ = FL.stream_power(himg(sl, base=bs), iterations=its,
                           erodibility=K_, uplift=U_, base_layer="base",
                           routing="d8", trace=tr)
    got = L(o, "C")[..., 0]
    d = float(np.abs(got - want[None, :]).max() / want.max())
    if conv:
        check(f"slope run for {its} steps: equals the steady-state analytic solution h_j = Σ U/F_k per pixel"
              f" (relative diff {d:.1e})", d < 1e-9)
        t_ = tr[-1]
        s_ = np.flatnonzero(t_["rcv"] >= 0)
        res = t_["F"][s_] * (t_["h"][s_] - t_["h"][t_["rcv"][s_]]) - U_
        check(f"  discrete steady-state equation F·(h − h_downstream) = U holds per pixel"
              f" (diff {np.abs(res).max():.1e})", float(np.abs(res).max()) < 1e-12)
        check("  outlet column never moved (fixed base level)",
              bool((got[:, 0] == sl[:, 0]).all()))
    else:
        check(f"  negative control: after only {its} steps not equal yet (relative diff {d:.2f})", d > 0.05)

# Scale invariance (m = 0.5)
hq = smooth_noise(rng, 30, 34) * 0.2
up = smooth_noise(rng, 30, 34)
base_o, _ = FL.stream_power(himg(hq, up=up), iterations=15, erodibility=0.1,
                            uplift=1e-3, uplift_layer="up", diffusion=0.05)
for s_, exact in ((2.0, True), (3.0, False)):
    oo, _ = FL.stream_power(himg(hq, up=up), strength=s_, world_size=s_,
                            iterations=15, erodibility=0.1, uplift=1e-3 * s_,
                            uplift_layer="up", diffusion=0.05)
    d = float(np.abs(L(oo, "C") - L(base_o, "C")).max())
    if exact:
        check("m = 0.5: height / world scale / uplift all ×2, output unchanged bit for bit",
              d == 0.0, f"{d:.1e}")
    else:
        check(f"  at ×3 the diff is at rounding level ({d:.1e})", d < 1e-12)
oo, _ = FL.stream_power(himg(hq), iterations=15, erodibility=0.1,
                        uplift=1e-3, m=0.7, world_size=2.0)
oo1, _ = FL.stream_power(himg(hq), iterations=15, erodibility=0.1,
                         uplift=1e-3, m=0.7, world_size=1.0)
check("  negative control: with m = 0.7 changing the world scale changes the result",
      float(np.abs(L(oo, "C") - L(oo1, "C")).max()) > 1e-6)

fl = np.zeros((16, 16))
o, _ = FL.stream_power(himg(fl), iterations=20, erodibility=0.1)
check("flat ground, no uplift: stays flat (only pit-filling ulp left)",
      float(np.abs(L(o, "C")).max()) < 1e-300)
o, _ = FL.stream_power(himg(hq, z=np.zeros_like(hq)), iterations=10,
                       erodibility=0.1, uplift=1e-2, uplift_layer="z")
o2, _ = FL.stream_power(himg(hq), iterations=10, erodibility=0.1)
check("Uplift Layer all 0 = no uplift", bool((L(o, "C") == L(o2, "C")).all()))
check("K = 0 and no uplift: only pit-filling changes",
      bool((L(FL.stream_power(himg(hq), iterations=5, erodibility=0.0)[0],
               "C")[..., 0] == FL.priority_fill(hq, FL.seeds(hq.shape)))
           .all()))
check("Flow Layer: catchment area from the last step, outlet sum = whole image area",
      abs(float(L(o2, "flow")[..., 0][FL.seeds(hq.shape)].sum())
          - 1.0 * hq.shape[0] / hq.shape[1]) < 1e-12)

# ═══════════════════════════════════════════════════ 5. Errors / backends / nodes
sec("Errors / backends / nodes")
im = himg(hq)
err("unknown Method", lambda: FL.flow_accumulation(im, method="x"), "Method")
err("River Area = 0", lambda: FL.flow_accumulation(im, river_area=0),
    "River Area")
err("Diffusion > 0.25", lambda: FL.stream_power(im, diffusion=0.3),
    "Diffusion")
err("Erodibility < 0", lambda: FL.stream_power(im, erodibility=-1),
    "Erodibility")
err("Strength = 0", lambda: FL.stream_power(im, strength=0), "Strength")
err("Base Layer all 0", lambda: FL.flow_accumulation(
    himg(hq, b=np.zeros_like(hq)), base_layer="b"), "no outlets at all")
check("None input -> empty image", FL.flow_accumulation(None)[0].xres == 0
      and FL.stream_power(None)[0].xres == 0)

tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    i32 = CopImage(34, 30, {"C": hq.astype(np.float32)[:, :, None]})
    it_ = i32.to_device("cpu")
    for nm, fn, lays in (
            ("flow d8", lambda i: FL.flow_accumulation(i)[0],
             ("flow", "river", "lake", "flow_dir")),
            ("flow mfd", lambda i: FL.flow_accumulation(i, method="mfd")[0],
             ("flow", "flow_dir")),
            ("stream power", lambda i: FL.stream_power(
                i, iterations=5, uplift=1e-3, diffusion=0.05)[0],
             ("C", "flow"))):
        try:
            gg_, cc_ = fn(it_), fn(i32)
            d_ = max(float(np.abs(L(gg_, k) - L(cc_, k)).max()) for k in lays)
            check(f"[torch] {nm}: matches numpy, and output still on torch",
                  d_ < 1e-6 and gg_.backend.is_torch, f"{d_:.1e}")
        except Exception as ex:
            check(f"[torch] {nm}", False, f"{type(ex).__name__}: {ex}")

names = ["FlowAccumulation", "StreamPower"]
check("both nodes registered, both under PCG/cop",
      all(MAP[f"PCG_COP{n}"].CATEGORY == "PCG/cop" for n in names))
r = MAP["PCG_COPFlowAccumulation"]().run(
    himg(hq), "C", 1.0, 1.0, "d8", 1.1, True, False, "", "", 0.002, 0.5,
    "flow", "river", "lake", "flow_dir", True, 0)
r = r["result"] if isinstance(r, dict) else r
check("Flow Accumulation node: report states rainfall → outlets", "→ outlets" in r[1]
      and "flow" in r[0], r[1][:70])
r = MAP["PCG_COPStreamPower"]().run(
    himg(hq), "C", 1.0, 1.0, 5, "rho8", 0.02, 0.5, 1e-3, "", 0.0, False, "",
    "C", "flow", 3)
r = r["result"] if isinstance(r, dict) else r
check("Stream Power node: report + output layer", "pit refills 1" in r[1]
      and "flow" in r[0], r[1])

# ═══════════════════════════════════════════════════ 6. Timing
sec("Timing")
if os.environ.get("PCG_SKIP_TIMING"):          # skipped during mutation testing
    print(f"\n{sum(OK)}/{len(OK)} passed")
    sys.exit(0 if all(OK) else 1)
big = smooth_noise(np.random.default_rng(1), 1024, 1024, 6) \
    + np.random.default_rng(2).random((1024, 1024)) * 0.01
t0 = time.time()
_, rp = FL.flow_accumulation(himg(big))
dt = time.time() - t0
check(f"Flow Accumulation D8 1024²  {dt:.2f} s ({rp['batches']} batches, limit 60 s)",
      dt < 60)
t0 = time.time()
FL.flow_accumulation(himg(big), method="mfd")
dt = time.time() - t0
check(f"Flow Accumulation MFD 1024²  {dt:.2f} s (limit 60 s)", dt < 60)
b2 = big[:512, :512]
t0 = time.time()
FL.stream_power(himg(b2), iterations=20, uplift=1e-4, diffusion=0.02)
dt = time.time() - t0
check(f"Stream Power 512² × 20 steps  {dt:.2f} s ({dt / 20:.2f} s per step, limit 60 s)",
      dt < 60)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
