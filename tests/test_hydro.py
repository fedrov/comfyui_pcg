"""
Hydraulic erosion (with deposition).

━━ Criteria
  · brush: weights sum to 1, cone-shaped; radius 1 is only the center cell
  · **mass conservation**: computed directly from the output layers (not trusting the report's own bookkeeping) -- change in total terrain =
    -(material flowing off the image edges); unchanged with tile; in lose mode also minus what was dropped; holds with bedrock, with a deposit
    brush, and with an existing debris layer
  · flat ground does not change bit for bit; bedrock (hardness = 1) does not change bit for bit
  · Strength and World Size both x2: output identical bit for bit (negative control: changing only World Size changes it)
  · with batch = 1 matches a reference implementation that writes droplet by droplet in order (tests the batching machinery: scatter,
    indexing, masking, limiting, take-back)
  · physics: steep slope meeting a plain, material piles up at the slope foot (alluvial fan); pits get filled in; wetness higher in valleys than on ridges
  · limiting: a large batch of droplets walking at once on converging terrain does not blow up the height range (negative control: without limiting, the first version blew up to 1e15
    on 256^2)
  · spread at end of lifetime: high-frequency noise on a slope over an order of magnitude smaller than dropping at a single bilinear point
  · torch and numpy agree statistically, mass conserved to float32 precision
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
from comfyui_pcg.geo.cop import hydro as HY              # noqa: E402
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


def blur(a, s):
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(a, s, mode="nearest")


rng = np.random.default_rng(5)
n = 96
x = (np.arange(n) + 0.5) / n
X, Y = np.meshgrid(x, x)
terr = blur(rng.standard_normal((n, n)), 4) * 0.08 \
    + 0.1 * np.exp(-((X - 0.4) ** 2 + (Y - 0.6) ** 2) / 0.03)

# ═══════════════════════════════════════════════════ 1. brush
sec("brush")
dy, dx, w = HY.brush(3.0)
d = np.hypot(dx, dy)
check("r = 3: weights sum to 1, decrease linearly with distance (cone), farthest cell distance < 3",
      abs(w.sum() - 1) < 1e-15 and np.allclose(w / w.max(), (3 - d) / 3)
      and d.max() < 3, len(w))
dy1, dx1, w1 = HY.brush(1.0)
check("r = 1: only the center cell", len(w1) == 1 and dy1[0] == 0 and dx1[0] == 0)

# ═══════════════════════════════════════════════════ 2. mass conservation
sec("mass conservation (computed directly from the output layers)")


def mass(img, s=1.0, ws=1.0):
    t = ws / img.xres
    return float(L(img, "C").sum()) * s * t * t


im = himg(terr)
for tile in (False, True):
    for extra in ({}, {"deposit_radius": 2.0}, {"end_mode": "lose"},
                  {"hardness_layer": "hard"}):
        src = himg(terr, hard=np.clip(X * 1.5, 0, 1)) if extra.get(
            "hardness_layer") else im
        out, rp = HY.hydraulic_erode(src, tile=tile, seed=3,
                                     droplets_per_pixel=0.5, **extra)
        dm = mass(out) - mass(src)
        bal = dm + rp["outflow"] + rp["lost"]
        tag = ("tile " if tile else "") + (",".join(extra) or "default")
        check(f"{tag}: Δterrain {dm:+.3e} = -(outflow {rp['outflow']:.2e} + lost "
              f"{rp['lost']:.2e}), diff {bal:.1e}",
              abs(bal) < 1e-12 * max(abs(rp["eroded"]), 1e-12) * 1e3
              and (not tile or rp["outflow"] == 0.0))
_ls = HY.hydraulic_erode(im, end_mode="lose", droplets_per_pixel=0.5)[1]
_sp = HY.hydraulic_erode(im, droplets_per_pixel=0.5)[1]
check(f"  lose drops all material at end of lifetime ({_ls['lost']:.2e}); spread spreads out "
      f"{_sp['dropped_at_end']:.2e}, only losing what limiting cannot place {_sp['lost']:.2e}",
      _ls["lost"] > 0 and _ls["dropped_at_end"] == 0
      and _sp["lost"] < 0.6 * _ls["lost"] and _sp["dropped_at_end"] > 0)
check("  the report's own bookkeeping balances too: before - after = eroded - deposited en route - spread at end of lifetime",
      abs((rp["mass_before"] - rp["mass_after"]) - (
          rp["eroded"] - rp["deposited"] - rp["dropped_at_end"])) < 1e-12)

# ═══════════════════════════════════════════════════ 3. identity / scale
sec("identity and scale")
flat = np.full((40, 50), 0.3)
for tile in (False, True):
    o, r_ = HY.hydraulic_erode(himg(flat), tile=tile)
    check(f"flat ground{'(tile)' if tile else ''}: does not change bit for bit (bilinear interpolation rounding gives -Δh of"
          " order 1e-17; limiting -- never digging below the lowest neighbour -- blocks it)",
          bool((L(o, "C")[..., 0] == flat).all())
          and r_["eroded"] == 0.0)
o, _ = HY.hydraulic_erode(himg(terr, hard=np.ones((n, n))),
                          hardness_layer="hard")
check("hardness = 1 everywhere: unchanged bit for bit", bool((L(o, "C")[..., 0] == terr).all()))
a1, r1 = HY.hydraulic_erode(im, seed=4, droplets_per_pixel=0.5)
a2, r2 = HY.hydraulic_erode(himg(terr), strength=2.0, world_size=2.0, seed=4,
                            droplets_per_pixel=0.5)
check("Strength and World Size both x2: output identical bit for bit (simulation unit = height / image width)",
      bool((L(a1, "C") == L(a2, "C")).all()))
check("  world-volume bookkeeping x8 (height x2, pixel area x4)",
      abs(r2["eroded"] / r1["eroded"] - 8) < 1e-9)
a3, _ = HY.hydraulic_erode(himg(terr), world_size=2.0, seed=4,
                           droplets_per_pixel=0.5)
check("  negative control: changing only World Size (= terrain half as steep) changes the result",
      float(np.abs(L(a3, "C") - L(a1, "C")).max()) > 1e-6)
b1, _ = HY.hydraulic_erode(im, seed=4, droplets_per_pixel=0.5)
b2, _ = HY.hydraulic_erode(im, seed=5, droplets_per_pixel=0.5)
check("same seed reproducible bit for bit, a different seed changes it",
      bool((L(b1, "C") == L(a1, "C")).all())
      and not bool((L(b2, "C") == L(a1, "C")).all()))

# ═══════════════════════════════════════════════════ 4. sequential reference implementation
sec("batch = 1 vs droplet-by-droplet reference implementation")


def reference(h, n_drops, seed, life=30, inertia=0.05, capf=4.0, mins=0.01,
              er=0.3, dr=0.3, ev=0.01, g=4.0, rad=3.0):
    """The original algorithm written droplet by droplet, step by step, in plain scalars (including limiting and spread at end of lifetime), non-tile."""
    Hh, Ww = h.shape
    hp = h.ravel().copy()
    rng_ = np.random.default_rng(seed)
    bdy, bdx, bw = HY.brush(rad)
    edy, edx, ew = HY.brush(2 * rad)

    def nbr(c):
        cy, cx = divmod(c, Ww)
        vs = [hp[(cy + a) * Ww + cx + b] for a in (-1, 0, 1)
              for b in (-1, 0, 1) if (a or b) and 0 <= cy + a < Hh
              and 0 <= cx + b < Ww]
        return min(vs), max(vs)

    def brush_at(cy, cx, amt, by, bx, bwt):
        cells = [((cy + a) * Ww + cx + b, wt) for a, b, wt in zip(by, bx, bwt)
                 if 0 <= cy + a < Hh and 0 <= cx + b < Ww]
        s_ = sum(wt for _, wt in cells)
        return [(c, amt * wt / s_) for c, wt in cells]

    out = 0.0
    lost = 0.0
    for _ in range(n_drops):
        px = rng_.random(1)[0] * (Ww - 1)
        py = rng_.random(1)[0] * (Hh - 1)
        ang = rng_.random(1)[0] * 2 * math.pi
        ddx = ddy = 0.0
        vel, wat, sed = 1.0, 1.0, 0.0
        alive = True
        for _ in range(life):
            ix, iy = int(math.floor(px)), int(math.floor(py))
            ox, oy = px - ix, py - iy
            i00, i10 = iy * Ww + ix, iy * Ww + ix + 1
            i01, i11 = (iy + 1) * Ww + ix, (iy + 1) * Ww + ix + 1
            h00, h10, h01, h11 = hp[i00], hp[i10], hp[i01], hp[i11]
            gx = (h10 - h00) * (1 - oy) + (h11 - h01) * oy
            gy = (h01 - h00) * (1 - ox) + (h11 - h10) * ox
            hc = (h00 * (1 - ox) * (1 - oy) + h10 * ox * (1 - oy)
                  + h01 * (1 - ox) * oy + h11 * ox * oy)
            ddx = ddx * inertia - gx * (1 - inertia)
            ddy = ddy * inertia - gy * (1 - inertia)
            ln = math.hypot(ddx, ddy)
            if ln <= 0:
                ddx, ddy = math.cos(ang), math.sin(ang)
            else:
                ddx, ddy = ddx / ln, ddy / ln
            nx, ny = px + ddx, py + ddy
            if not (0 <= nx < Ww - 1 and 0 <= ny < Hh - 1):
                out += sed
                alive = False
                break
            jx, jy = int(math.floor(nx)), int(math.floor(ny))
            qx, qy = nx - jx, ny - jy
            hn = (hp[jy * Ww + jx] * (1 - qx) * (1 - qy)
                  + hp[jy * Ww + jx + 1] * qx * (1 - qy)
                  + hp[(jy + 1) * Ww + jx] * (1 - qx) * qy
                  + hp[(jy + 1) * Ww + jx + 1] * qx * qy)
            dh = hn - hc
            cap = max(-dh, mins) * vel * wat * capf
            if sed > cap or dh > 0:
                a = min(dh, sed) if dh > 0 else (sed - cap) * dr
                parts = [(i00, a * (1 - ox) * (1 - oy)),
                         (i10, a * ox * (1 - oy)),
                         (i01, a * (1 - ox) * oy), (i11, a * ox * oy)]
                want = {}
                for c, v in parts:
                    want[c] = want.get(c, 0.0) + v
                ratio = {}
                for c, v in want.items():
                    if v > 0:
                        lo, hi = nbr(c)
                        ratio[c] = min((max(hi - hp[c], 0.0) + HY.PILE_STEP)
                                       / v, 1.0)
                got = 0.0
                for c, v in parts:
                    got += v * ratio.get(c, 1.0)
                for c, v in want.items():
                    hp[c] += v * ratio.get(c, 1.0)
                sed -= got
            else:
                a = max(min((cap - sed) * er, -dh), 0.0)
                parts = brush_at(iy, ix, a, bdy, bdx, bw)
                want = {}
                for c, v in parts:
                    want[c] = want.get(c, 0.0) + v
                ratio = {}
                for c, v in want.items():
                    if v > 0:
                        lo, hi = nbr(c)
                        ratio[c] = min(max(hp[c] - lo, 0.0) / v, 1.0)
                got = sum(v * ratio.get(c, 1.0) for c, v in parts)
                for c, v in want.items():
                    hp[c] -= v * ratio.get(c, 1.0)
                sed += got
            vel = math.sqrt(max(vel * vel - dh * g, 0.0))
            wat *= (1 - ev)
            px, py = nx, ny
        if alive:
            ix, iy = int(math.floor(px)), int(math.floor(py))
            parts = brush_at(iy, ix, sed, edy, edx, ew)
            want = {}
            for c, v in parts:
                want[c] = want.get(c, 0.0) + v
            ratio = {}
            for c, v in want.items():
                if v > 0:
                    lo, hi = nbr(c)
                    ratio[c] = min((max(hi - hp[c], 0.0) + HY.PILE_STEP) / v,
                                   1.0)
            got = sum(v * ratio.get(c, 1.0) for c, v in parts)
            for c, v in want.items():
                hp[c] += v * ratio.get(c, 1.0)
            lost += sed - got
    return hp.reshape(Hh, Ww), out, lost


small = terr[:32, :40].copy()
t0 = time.time()
ref_h, ref_out, ref_lost = reference(small, 60, seed=9)
got, rp = HY.hydraulic_erode(himg(small), droplets_per_pixel=60 / (32 * 40),
                             batch=1, seed=9, wet_layer="")
dd = float(np.abs(L(got, "C")[..., 0] - ref_h).max())
ro = rp["outflow"] * 40 ** 2
rl = rp["lost"] * 40 ** 2
check(f"60 droplets, batch = 1: matches the droplet-by-droplet reference (diff {dd:.1e}; outflow {ro:.3e} vs "
      f"{ref_out:.3e};lost {rl:.3e} vs {ref_lost:.3e})",
      dd < 1e-12 and abs(ro - ref_out) < 1e-12 and abs(rl - ref_lost) < 1e-12,
      f"{time.time() - t0:.1f} s")
check("  and the terrain really changed (not both sides untouched)",
      float(np.abs(ref_h - small).max()) > 1e-4)

# ═══════════════════════════════════════════════════ 5. physics
sec("physics")
nf = 120
xf = (np.arange(nf) + 0.5) / nf
XF, YF = np.meshgrid(xf, xf)
brk = 0.45
fan = np.where(XF < brk, 0.25 * (brk - XF), 0.0) \
    + 0.002 * blur(rng.standard_normal((nf, nf)), 2)
of, rf = HY.hydraulic_erode(himg(fan), droplets_per_pixel=2.0, seed=1)
dep = L(of, "debris")[..., 0]
ero = np.maximum(fan - L(of, "C")[..., 0], 0)
jb = int(brk * nf)
slope_e = ero[:, 8:jb - 3].sum()
plain_e = ero[:, jb + 3:].sum()
foot = dep[:, jb:jb + 25].sum()
far = dep[:, jb + 50:].sum()
up = dep[:, 8:jb - 3].sum()
check(f"steep slope meeting a plain: erosion on the slope ({slope_e:.2f} vs plain {plain_e:.2f})",
      slope_e > 5 * plain_e)
check(f"  deposition at the slope foot (25 cells at the foot {foot:.2f} > farther plain {far:.2f},"
      f" > on the slope {up:.2f}) -- alluvial fan", foot > far and foot > up)
pit = 0.05 * (1 - XF) - 0.03 * np.exp(-((XF - 0.5) ** 2 + (YF - 0.5) ** 2)
                                      / 0.004)
op, _ = HY.hydraulic_erode(himg(pit), droplets_per_pixel=2.0, seed=2)
hp_ = L(op, "C")[..., 0]
c_ = nf // 2


base_ = 0.05 * (1 - XF)
ctr = np.hypot(XF - 0.5, YF - 0.5) < 0.02
b0 = float((pit - base_)[ctr].mean())
b1 = float((hp_ - base_)[ctr].mean())
check(f"a pit gets filled: pit bottom relative to the original slope {b0:.4f} -> {b1:.4f}, without piling up a mound"
      f" (max above the original slope {(hp_ - base_).max():.4f})",
      b1 > b0 + 0.02 and float((hp_ - base_).max()) < 0.005)
vall = 0.08 * np.abs(XF - 0.5) + 0.05 * YF
ov, _ = HY.hydraulic_erode(himg(vall), droplets_per_pixel=1.0, seed=3)
wv = L(ov, "wetness")[..., 0]
check(f"V-shaped valley: wetness at the valley floor ({wv[:, 55:65].mean():.2f}) higher than on the ridges on both sides"
      f" ({np.r_[wv[:, :8].ravel(), wv[:, -8:].ravel()].mean():.2f})",
      wv[:, 55:65].mean() > 3 * np.r_[wv[:, :8].ravel(),
                                        wv[:, -8:].ravel()].mean())

# ═══════════════════════════════════════════════════ 6. limiting / spread
sec("limiting and spread at end of lifetime")
fun = 0.2 * np.hypot(XF - 0.5, YF - 0.5)            # funnel, everything converges to the center
oF, rF = HY.hydraulic_erode(himg(fun), droplets_per_pixel=4.0,
                            batch=1 << 16, seed=4)
hr0, hr1 = np.ptp(fun), np.ptp(L(oF, "C"))
check(f"funnel, a batch of 65536 droplets converging on the center at once: height range {hr0:.3f} -> {hr1:.3f}, no blow-up,"
      f" no mound piled up in the basin (demand removed by limiting {rF['limited']:.2e}; with spread also unlimited it"
      " is 0.52)", hr1 < 1.05 * hr0)
pl = 0.1 * (1 - XF)
o_s, _ = HY.hydraulic_erode(himg(pl), seed=6)
a_s = L(o_s, "C")[..., 0]
noise_s = float((a_s - blur(a_s, 2)).std())
check(f"spread at end of lifetime on a slope: high-frequency noise {noise_s:.1e} (the first version dropping at a single bilinear point gave "
      "1.7e-2)", noise_s < 2e-3)

# ═══════════════════════════════════════════════════ 7. layers
sec("output layers")
deb = np.full((n, n), 0.01)
o1, _ = HY.hydraulic_erode(himg(terr, debris=deb), droplets_per_pixel=0.3,
                           seed=2, erosion_layer="ero")
o2, _ = HY.hydraulic_erode(himg(terr, debris=deb), droplets_per_pixel=0.3,
                           seed=2, accumulate_deposit=False)
dC = L(o1, "C")[..., 0] - terr
check("debris accumulates onto the existing layer (thermal erosion talus + alluvium), turned off it overwrites",
      np.allclose(L(o1, "debris")[..., 0], deb + np.maximum(dC, 0))
      and np.allclose(L(o2, "debris")[..., 0], np.maximum(dC, 0)))
check("  erosion layer = net erosion", np.allclose(L(o1, "ero")[..., 0],
                                          np.maximum(-dC, 0)))
wt = L(o1, "wetness")
check(f"  wetness in 0~1, with the background subtracted (median {np.median(wt):.1e} ≈ 0: uniformly scattered"
      " water leaves a share everywhere; without subtracting, most of the image is squeezed into 0.5~1)",
      float(wt.min()) >= 0 and float(wt.max()) <= 1
      and float(np.median(wt)) < 1e-3)
o3, _ = HY.hydraulic_erode(himg(terr), deposit_layer="", wet_layer="",
                           keep=False, droplets_per_pixel=0.1)
check("  empty layer name gives no layer; keep = False leaves only the output layers", o3.names == ["C"])

# ═══════════════════════════════════════════════════ 8. torch / errors / node
sec("torch / errors / node")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    i32 = CopImage(n, n, {"C": terr.astype(np.float32)[:, :, None]})
    for tile in (False, True):
        a_, ra_ = HY.hydraulic_erode(i32, tile=tile, seed=1)
        b_, rb_ = HY.hydraulic_erode(i32.to_device("cpu"), tile=tile, seed=1)
        A_, B_ = L(a_, "C"), L(b_, "C")
        chg = float(np.abs(A_ - terr[:, :, None]).mean())
        dif = float(np.abs(A_ - B_).mean())
        bal = rb_["mass_after"] - rb_["mass_before"] + rb_["outflow"] \
            + rb_["lost"]
        check(f"[torch]{' tile' if tile else ''}: mean diff from numpy {dif:.1e}"
              f" (change {chg:.1e}, so {dif / chg * 100:.1f}% of it; droplet paths are sensitive to float32 "
              f"rounding), mass diff {bal:.1e}, output still on torch",
              dif < 0.05 * chg and abs(bal) < 1e-6 * rb_["eroded"] * 1e3
              and b_.backend.is_torch)
err("Lifetime = 0", lambda: HY.hydraulic_erode(im, lifetime=0), "Lifetime")
err("Inertia = 1", lambda: HY.hydraulic_erode(im, inertia=1.0), "Inertia")
err("Erode Rate > 1", lambda: HY.hydraulic_erode(im, erode_rate=2), "Erode")
err("Radius < 1", lambda: HY.hydraulic_erode(im, radius=0.5), "Radius")
err("bad End Mode", lambda: HY.hydraulic_erode(im, end_mode="x"), "End Mode")
err("Strength = 0", lambda: HY.hydraulic_erode(im, strength=0), "Strength")
check("None input -> empty image", HY.hydraulic_erode(None)[0].xres == 0)
nd = MAP["PCG_COPHydraulicErosion"]
check("node registered, under PCG/cop", nd.CATEGORY == "PCG/cop")
r = nd().run(im, "C", 1.0, 1.0, 0.3, 30, 0.3, 0.3, 4.0, 0.05, 0.01, 0.01,
             4.0, 3.0, 0.0, "spread", 16384, False, "", 0, "C", "debris",
             True, "", "wetness", True)
r = tuple(r["result"]) if isinstance(r, dict) else r
check("  report includes the mass balance", "mass balance error" in r[1] and "debris" in r[0], r[1][:80])

# ═══════════════════════════════════════════════════ 9. timing
sec("timing")
big = blur(np.random.default_rng(1).standard_normal((512, 512)), 8) * 0.1
t0 = time.time()
_, rb = HY.hydraulic_erode(himg(big))
dt = time.time() - t0
check(f"512^2, one droplet per pixel ({rb['droplets']} droplets) numpy {dt:.1f} s (limit 120 s)",
      dt < 120)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
