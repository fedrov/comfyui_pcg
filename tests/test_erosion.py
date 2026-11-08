"""
Erosion filter (COP Erosion Filter).

━━ "Correct" for this node is hard to write as an analytic criterion -- it is a "looks right" thing by nature
so the criteria come in three tiers:

  1. **structural properties** (bit for bit / machine precision): the stripes are unit vectors; the 4x4 kernel block matches the 9x9 brute force
     exactly (proves the coverage argument for the 1.5-cell weight radius); with tile the stripe field is strictly periodic; flat ground
     (fade=none) does not change a single bit; amplitude 0 / 0 octaves returns the input unchanged; tiled generation matches
     bit for bit in the interior
  2. **mechanism**: gullies run downhill (cross variation more than 5x the along variation); gully spacing = wavelength (power peak and zero-crossing
     count averaged over 16 seeds); the second octave's flow direction is **bent by the first octave** (remove that step
     and it is straight) -- that is where the branching comes from
  3. **the step this version adds itself (flow_blur) really solves the problem it is meant to solve**: on input with fine noise
     the local coherence of the first octave's flow direction rises from 0.70 to 0.92; on smooth input it barely changes
     (negative control: it is not just smoothing everything out)

Also: scale invariance (height, world_size, amplitude all x s, output exactly x s), linear in amplitude with a single octave,
determinism, torch agreement, error messages, 1024^2 timing.
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
from comfyui_pcg.geo.cop import erosion as ER            # noqa: E402
from comfyui_pcg.geo.cop import noise as NZ              # noqa: E402
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


def himg(h):
    return CopImage(h.shape[1], h.shape[0],
                    {"C": np.asarray(h, np.float64)[:, :, None]})


XP = BK.EXACT


# ═══════════════════════════════════════════════════ 1. the stripes themselves
sec("direction stripes")
Ws = Hs = 128
lam = 16.0
u = (np.arange(Ws) + 0.5) / lam
v = (np.arange(Hs) + 0.5) / lam
th = math.radians(30)
n = (math.cos(th), math.sin(th))
NX = np.full((Hs, Ws), n[0])
NY = np.full((Hs, Ws), n[1])
c, s = ER.stripes(XP, u, v, NX, NY, lam, lam, lam, 0, seed=1)
check("output is a unit vector (cos Φ, sin Φ)",
      float(np.abs(np.hypot(c, s) - 1).max()) < 1e-12)


def brute(px, py, seed=1, octave=0):
    """Brute-force version that computes all 9x9 neighbouring cells. Weights are 0 beyond 1.5 cells, so it should be identical."""
    C = S = 0.0
    for cy in range(int(math.floor(py)) - 4, int(math.floor(py)) + 5):
        for cx in range(int(math.floor(px)) - 4, int(math.floor(px)) + 5):
            T = ER._pivot_table(cx, cx, cy, cy, octave, seed, None, None)[0, 0]
            du, dv = px - (cx + T[0]), py - (cy + T[1])
            w = max(math.exp(-2 * (du * du + dv * dv)) - ER._W_FLOOR, 0.0)
            ph = (du * lam * n[0] + dv * lam * n[1]) * 2 * math.pi / lam
            C += w * math.cos(ph)
            S += w * math.sin(ph)
    ln = math.hypot(C, S)
    return C / ln, S / ln


rng = np.random.default_rng(0)
e = 0.0
for _ in range(300):
    j, i = int(rng.integers(0, Ws)), int(rng.integers(0, Hs))
    bc, bs = brute(u[j], v[i])
    e = max(e, abs(bc - c[i, j]), abs(bs - s[i, j]))
check("4x4 kernel block and 9x9 brute force **match exactly** (weights reach zero at 1.5 cells -> any block choice gives the same)",
      e < 1e-12, f"{e:.1e}")

dn_ = np.abs((c[1:-1, 2:] - c[1:-1, :-2]) / 2 * n[0]
             + (c[2:, 1:-1] - c[:-2, 1:-1]) / 2 * n[1]).mean()
dd_ = np.abs((c[1:-1, 2:] - c[1:-1, :-2]) / 2 * (-n[1])
             + (c[2:, 1:-1] - c[:-2, 1:-1]) / 2 * n[0]).mean()
check("stripes vary mainly along n: cross variation > 3x the along variation", dn_ / dd_ > 3.0,
      f"{dn_ / dd_:.2f}x")

cw, sw = ER.stripes(XP, u, v, NX, NY, lam, lam, lam, 0, 1, wrap=(8, 8))
cw2, sw2 = ER.stripes(XP, u + 8, v + 8, NX, NY, lam, lam, lam, 0, 1,
                      wrap=(8, 8))
check("tile: stripe field strictly periodic (shifting by a whole period is bit-identical)",
      float(np.abs(cw - cw2).max()) == 0.0
      and float(np.abs(sw - sw2).max()) == 0.0)
cn2, _ = ER.stripes(XP, u + 8, v + 8, NX, NY, lam, lam, lam, 0, 1)
check("  negative control: without the modulo, shifting by one period gives a different pattern",
      float(np.abs(c - cn2).max()) > 0.5)

W2 = 256
for lam_ in (16.0, 32.0):
    uu = (np.arange(W2) + 0.5) / lam_
    NX0, NY0 = np.zeros((W2, W2)), np.ones((W2, W2))
    spec = 0.0
    zc = []
    for sd in range(16):
        cc, _ = ER.stripes(XP, uu, uu, NX0, NY0, lam_, lam_, lam_, 0, sd)
        spec = spec + np.abs(np.fft.rfft(cc - cc.mean(), axis=0)) ** 2
        # average over all columns. The first version only counted the middle column, so 16 seeds gave only 16 samples, and at λ=32
        # drawing 5.6% turned it red; averaged over all columns it is a stable +2%~+4% (with mixed phases there is occasionally
        # an extra small jitter, so zero crossings slightly exceed the nominal value)
        zc.append((np.diff(np.sign(cc), axis=0) != 0).sum(0).mean())
    pk = int(spec.mean(1).argmax())
    nom = W2 / lam_
    check(f"wavelength {lam_:.0f}: power peak averaged over 16 seeds within ±1 bin of the nominal frequency",
          abs(pk - nom) <= 1, f"peak {pk}, nominal {nom:.0f}")
    check(f"  zero-crossing count = 2 x number of periods (±5%, averaged over all columns)",
          abs(np.mean(zc) - 2 * nom) <= 0.05 * 2 * nom,
          f"{np.mean(zc):.1f} vs {2 * nom:.0f}")


# ═══════════════════════════════════════════════════ 2. when nothing should change
sec("not a single bit changes where nothing should change")
W = H = 96
TEX = 1.0 / W
J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                   np.arange(H, dtype=np.float64))
flat = np.full((H, W), 0.3)
for fd in ER.FADES:
    o = ER.erode(himg(flat), fade=fd)
    check(f"flat ground (fade={fd}): unchanged bit for bit", bool((L(o, "C")[..., 0] == 0.3).all()))
hill = 0.2 * np.sin(J * TEX * 5) * np.cos(I * TEX * 4)
check("Amplitude = 0: unchanged bit for bit",
      bool((L(ER.erode(himg(hill), amplitude=0.0), "C")[..., 0]
            == hill).all()))
o0 = ER.erode(himg(hill), octaves=0)
check("Octaves = 0: unchanged bit for bit, erosion layer all 0",
      bool((L(o0, "C")[..., 0] == hill).all())
      and float(np.abs(L(o0, "erosion")).max()) == 0.0)

plat = np.where(J < 48, 0.2, 0.2 + (J - 48) * TEX * 0.8)
o = L(ER.erode(himg(plat), fade="none", flow_blur=0.0), "C")[..., 0]
check("fade=none: on the plateau (>= 2 pixels from the slope) unchanged bit for bit, the slope did change",
      bool((o[:, :46] == 0.2).all()) and float(np.abs(o[:, 60:]
                                                      - plat[:, 60:]).max())
      > 1e-4)
o = L(ER.erode(himg(plat), fade="none"), "C")[..., 0]
r3 = int(math.ceil(3 * 0.25 * 48)) + 1
check(f"  with flow_blur on, >= 3σ+1 = {r3} pixels from the slope unchanged bit for bit (outside the blur radius)",
      bool((o[:, :48 - r3] == 0.2).all()))
check("  negative control: plateau within the blur radius was touched (the blur really brings the slope over)",
      float(np.abs(o[:, 48 - r3:46] - 0.2).max()) > 0.0)


# ═══════════════════════════════════════════════════ 3. mechanism
sec("mechanism: downhill gullies, fine gullies bent by coarse ones")
Wp = Hp = 128
Tp = 1.0 / Wp
Jp, Ip = np.meshgrid(np.arange(Wp, dtype=np.float64),
                     np.arange(Hp, dtype=np.float64))
plane = 0.8 * Jp * Tp
o = L(ER.erode(himg(plane), octaves=1, wavelength=16, fade="none"),
      "C")[..., 0]
off = o - plane
ry = np.abs(np.diff(off, axis=0)).mean() / np.abs(np.diff(off, axis=1)).mean()
check("slope along x: gullies run **downhill** (variation along y over 3x that along x)", ry > 3.0,
      f"{ry:.2f}x")
o2 = L(ER.erode(himg(0.8 * Ip * Tp), octaves=1, wavelength=16, fade="none"),
       "C")[..., 0] - 0.8 * Ip * Tp
rx = np.abs(np.diff(o2, axis=1)).mean() / np.abs(np.diff(o2, axis=0)).mean()
check("  rotate the slope 90°, the gullies rotate with it", rx > 3.0, f"{rx:.2f}x")

tr = []
ER.erode(himg(plane), octaves=2, wavelength=16, fade="none", trace=tr)
a0 = np.degrees(np.arctan2(tr[0]["ny"], tr[0]["nx"]))
a1 = np.degrees(np.arctan2(tr[1]["ny"], tr[1]["nx"]))
check("on a slope the first octave's flow direction is the same everywhere", float(a0.std()) < 1e-9)
check("the second octave's flow direction is **bent by the first octave's gullies** (the source of branching)", float(a1.std()) > 10.0,
      f"std {float(a1.std()):.1f}°")
tr = []
ER.erode(himg(plane), octaves=2, wavelength=16, fade="none", amplitude=1e-7,
         trace=tr)
check("  negative control: as the first octave's amplitude goes to 0 the second octave is straight too",
      float(np.degrees(np.arctan2(tr[1]["ny"], tr[1]["nx"])).std()) < 0.01)

# flow_blur: fine noise makes big gullies curl into worms; the problem this step solves
Nn = 256
Jn, In = np.meshgrid(np.arange(Nn, dtype=np.float64),
                     np.arange(Nn, dtype=np.float64))
un, vn = Jn / Nn, In / Nn


def terrain(noise_amp):
    r = np.random.default_rng(11)
    h = np.zeros((Nn, Nn))
    for _ in range(5):
        cx, cy = r.random(2)
        rr = 0.1 + 0.15 * r.random()
        h += (0.1 + 0.12 * r.random()) * np.exp(
            -((un - cx) ** 2 + (vn - cy) ** 2) / (2 * rr * rr))
    for oo in range(4):
        f = 3 * 2 ** oo
        h += noise_amp * 0.5 ** oo * np.asarray(
            NZ.simplex(XP, un * f, vn * f, np.zeros_like(un), seed=oo))
    return h * 0.5


def coherence(h, fb):
    """Mean resultant length of the first octave's flow direction within 8x8 blocks (2θ handles the ±n symmetry). 1 = fully coherent."""
    t = []
    ER.erode(himg(h), wavelength=24, flow_blur=fb, trace=t)
    a2 = np.arctan2(t[0]["ny"], t[0]["nx"]) * 2
    cc, ss = np.cos(a2), np.sin(a2)
    B = 8
    R = [math.hypot(cc[i:i + B, j:j + B].mean(), ss[i:i + B, j:j + B].mean())
         for i in range(0, Nn, B) for j in range(0, Nn, B)]
    return float(np.mean(R))


noisy = terrain(0.03)
c0, c1 = coherence(noisy, 0.0), coherence(noisy, 0.25)
check("input with fine noise: flow_blur clearly raises the local coherence of the first octave's flow direction",
      c1 - c0 > 0.15, f"{c0:.3f} -> {c1:.3f}")
smooth_t = terrain(0.0)
s0, s1 = coherence(smooth_t, 0.0), coherence(smooth_t, 0.25)
check("  negative control: on smooth input it barely changes (it is not just smoothing everything out)",
      abs(s1 - s0) < 0.02, f"{s0:.3f} -> {s1:.3f}")


# ═══════════════════════════════════════════════════ 4. scale / linearity / determinism
sec("scale invariance, linearity, determinism")
base = 0.15 * np.sin(J * TEX * 6 + 0.3) + 0.1 * np.cos(I * TEX * 7)
o1 = L(ER.erode(himg(base)), "C")[..., 0]
o3 = L(ER.erode(himg(base * 3), world_size=3.0, amplitude=0.03), "C")[..., 0]
check("height, World Size, Amplitude all x3: output exactly x3",
      float(np.abs(o3 - 3 * o1).max()) < 1e-12,
      f"{float(np.abs(o3 - 3 * o1).max()):.1e}")
os_ = L(ER.erode(himg(base), strength=3.0, world_size=3.0, amplitude=0.03),
        "C")[..., 0]
check("  Strength is the same thing as multiplying into the height values (output is still height values)",
      float(np.abs(os_ - o1).max()) < 1e-12)
a_ = L(ER.erode(himg(base), octaves=1, fade="none", amplitude=0.01),
       "C")[..., 0] - base
b_ = L(ER.erode(himg(base), octaves=1, fade="none", amplitude=0.02),
       "C")[..., 0] - base
check("with a single octave the erosion amount is linear in Amplitude", float(np.abs(b_ - 2 * a_).max())
      < 1e-12)
a5 = L(ER.erode(himg(base), amplitude=0.01), "C")[..., 0] - base
b5 = L(ER.erode(himg(base), amplitude=0.02), "C")[..., 0] - base
check("  with several octaves it is **not** linear (gully slopes feed back into the flow direction, intentionally)",
      float(np.abs(b5 - 2 * a5).max()) > 1e-4)
check("same seed bit-identical", bool((L(ER.erode(himg(base), seed=7), "C")
                             == L(ER.erode(himg(base), seed=7), "C")).all()))
check("a different seed changes the pattern", float(np.abs(
    L(ER.erode(himg(base), seed=7), "C")
    - L(ER.erode(himg(base), seed=8), "C")).max()) > 1e-3)
em = L(ER.erode(himg(base)), "erosion")
check("erosion layer within [-1, 1], with both ends used",
      float(em.min()) >= -1 and float(em.max()) <= 1
      and float(em.min()) < -0.5 and float(em.max()) > 0.5,
      f"[{float(em.min()):.2f}, {float(em.max()):.2f}]")
check("empty Mask Layer gives no output", "erosion" not in
      ER.erode(himg(base), mask_layer="").names)
check("overwrites the input layer by default (feeding Height to Normal needs no parameter change)",
      ER.erode(himg(base)).names == ["C", "erosion"])


# ═══════════════════════════════════════════════════ 5. tiled / seamless
sec("tiled generation and tile")
Wf, Hf = 96, 64
TX = 1.0 / 64
Jf, If = np.meshgrid(np.arange(Wf, dtype=np.float64),
                     np.arange(Hf, dtype=np.float64))
# add a trend along x: lowest point at the far left, highest at the far right -- so the block made of only the right 64 columns
# computes a min / max of its own that differs from the whole image. The first version had no trend, the two sides'
# min / max happened to be equal, so the negative control "does not match without an explicit range" could never go red
hf = (0.2 * np.sin(Jf * TX * 4) + 0.15 * np.cos(If * TX * 5 + 1)
      + 0.05 * np.sin((Jf + If) * TX * 9) + 0.4 * Jf * TX)
kw = dict(wavelength=12, fade="altitude", height_min=-0.4, height_max=1.0)


def full_and_crop(fb):
    f = L(ER.erode(himg(hf), world_size=Wf * TX, flow_blur=fb, **kw),
          "C")[..., 0]
    c_ = L(ER.erode(himg(hf[:, 32:]), world_size=64 * TX, origin_x=32 * TX,
                    flow_blur=fb, **kw), "C")[..., 0]
    return f[:, 32:], c_


f_, c_ = full_and_crop(0.0)
check("flow_blur=0: the right 64 columns computed alone match the whole image **bit for bit** in the interior",
      bool((f_[1:-1, 1:-1] == c_[1:-1, 1:-1]).all()))
check("  only the outermost ring differs (the input slope there is a one-sided difference)",
      float(np.abs(f_[:, 0] - c_[:, 0]).max()) > 0.0)
f_, c_ = full_and_crop(0.25)
mg = int(math.ceil(3 * 0.25 * 12)) + 1
check(f"flow_blur=0.25: bit-identical beyond >= 3σ+1 = {mg} columns from the cut (the overlap needs to be this large)",
      bool((f_[1:-1, mg:-1] == c_[1:-1, mg:-1]).all()))
check("  negative control: near the cut it really differs (the blur crosses the cut)",
      float(np.abs(f_[:, 1:mg - 3] - c_[:, 1:mg - 3]).max()) > 1e-6)
err_auto = float(np.abs(
    L(ER.erode(himg(hf), world_size=Wf * TX, flow_blur=0.0, wavelength=12),
      "C")[..., 0][1:-1, 33:-1]
    - L(ER.erode(himg(hf[:, 32:]), world_size=64 * TX, origin_x=32 * TX,
                 flow_blur=0.0, wavelength=12), "C")[..., 0][1:-1, 1:-1]).max())
check("  negative control: without an explicit height range (each block uses its own min/max) it does not match",
      err_auto > 1e-4, f"{err_auto:.1e}")

per = 0.15 * np.sin(2 * np.pi * 2 * J / W) * np.cos(2 * np.pi * 3 * I / H)
ot = L(ER.erode(himg(per), tile=True, wavelength=16), "C")[..., 0]
seam = float(np.abs(ot[:, 0] - ot[:, -1]).max())
inner = float(np.abs(np.diff(ot, axis=1)).max())
check("tile: the jump at the seam is no larger than the max difference between interior neighbouring pixels",
      seam <= inner * 1.0001, f"seam {seam:.4f} vs interior {inner:.4f}")
seam_v = float(np.abs(ot[0] - ot[-1]).max())
check("  same for the top/bottom seam", seam_v <= float(np.abs(np.diff(ot, axis=0)).max())
      * 1.0001)
on = L(ER.erode(himg(per), tile=False, wavelength=16), "C")[..., 0]
check("  negative control: without tile there is a clear jump at the seam",
      float(np.abs(on[:, 0] - on[:, -1]).max()) > seam * 1.5,
      f"{float(np.abs(on[:, 0] - on[:, -1]).max()):.4f}")


# ═══════════════════════════════════════════════════ 6. node / errors
sec("node and errors")
nd = MAP["PCG_COPErosion"]
spec = nd.INPUT_TYPES()["required"]
check("registered, under PCG/cop", nd.CATEGORY == "PCG/cop")
check("the random seed is called rand_seed (if called seed ComfyUI attaches randomize, endless re-runs)",
      "rand_seed" in spec and "seed" not in spec)
check("scale parameters consistent with the heightfield family (strength = world_size = 1)",
      spec["strength"][1]["default"] == 1.0
      and spec["world_size"][1]["default"] == 1.0)
r = nd().run(himg(base), "C", 1.0, 1.0, 0.01, 48.0, 5, 2.0, 0.35, 2.0, 0.25,
             "altitude", 0.0, 0.0, 0, False, 0.0, 0.0, "C", "erosion", True)
r = r["result"] if isinstance(r, dict) else r
check("node runs, result matches calling the function directly",
      float(np.abs(L(r[0], "C") - L(ER.erode(himg(base)), "C")).max()) == 0.0)
err("Strength = 0 raises", lambda: ER.erode(himg(base), strength=0), "Strength")
err("Lacunarity <= 1 raises", lambda: ER.erode(himg(base), lacunarity=1.0),
    "Lacunarity")
err("Octaves out of range raises", lambda: ER.erode(himg(base), octaves=13), "Octaves")
err("Wavelength < 1 raises", lambda: ER.erode(himg(base), wavelength=0.5),
    "Wavelength")
err("bad Fade raises", lambda: ER.erode(himg(base), fade="curv"), "Fade")
err("negative Flow Blur raises", lambda: ER.erode(himg(base), flow_blur=-1),
    "Flow Blur")


# ═══════════════════════════════════════════════════ 7. backends
sec("backend consistency (numpy float32 vs torch CPU)")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    b32 = CopImage(W, H, {"C": base.astype(np.float32)[:, :, None]})
    for nm, kw_ in (("default", {}), ("tile", {"tile": True}),
                    ("fade=none, flow_blur=0", {"fade": "none",
                                                "flow_blur": 0.0})):
        try:
            g = ER.erode(b32.to_device("cpu"), **kw_)
            cpu = ER.erode(b32, **kw_)
            d = max(float(np.abs(L(g, k) - L(cpu, k)).max())
                    for k in ("C", "erosion"))
            check(f"[torch] {nm}: results match, and still on torch",
                  d < 1e-4 and g.backend.is_torch, f"{d:.1e}")
        except Exception as ex:
            check(f"[torch] {nm}", False, f"{type(ex).__name__}: {ex}")


# ═══════════════════════════════════════════════════ 8. timing
sec("1024^2 timing (numpy, recorded only)")
big = CopImage(1024, 1024, {"C": (np.random.default_rng(1).random(
    (1024, 1024)) * 0.01).astype(np.float32)[:, :, None]})
t0 = time.time()
ER.erode(big)
dt = time.time() - t0
check(f"default parameters, 5 octaves  {dt:.2f} s (limit 20 s)", dt < 20.0)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
