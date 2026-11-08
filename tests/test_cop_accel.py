"""
pcg65: GPU + algorithmic speed-ups on heavy nodes (geo/cop/accel.py and the 10 functions wired into it).

On an RTX 4090 at 1024²: reaction diffusion 70 s, Stream Power 31 s, Noise Extra 7.7 s,
TV denoise 6.1 s, HF Project 5.9 s, hydraulic erosion 160 s (no GPU unless COP To Device is wired in by hand).
This batch puts the iterative nodes on a compute engine with a numpy / torch dual path, and removes some waste in the
algorithms themselves. The sandbox has no CUDA, so the GPU path is verified by running the same code on **torch:cpu**
-- the two differ only in device, not a single line of code.

━━ Criteria
  · Operator table: every Engine method agrees element-wise on numpy / torch (pad's three modes vs
    np.pad, flip / roll / where with scalars / maximum with scalars / rfft2 round trip / fftfreq /
    iclip keeps integer dtype / arctan2)
  · pick decisions: cpu -> numpy; auto follows torch inputs; auto "with CUDA" decides by pixel count
    and VRAM budget (thresholds verified on both sides with a stubbed CUDA); cuda without a GPU falls back and says so; garbage raises
  · **numpy and torch results agree to 1e-9** (float64 on both): Gray-Scott (wrap / clamp /
    per-pixel feed), Turing, ripple (three edge modes, walls, drivers), flow (simulate / project, two
    edge modes, external force), TV denoise, directional blur (three boundaries, two modes), the six Noise Extra kinds (including phasor
    with a direction field)
  · the numpy path matches the pcg64 implementation: TV / directional blur / Noise Extra bit-identical (reference
    implementations written in this file), Gray-Scott to 1e-12 (the Laplacian's summation order changed)
  · Output goes back to the original backend: numpy in numpy out (float32), exact in exact out, torch in torch out
  · pick_backend for thermal / hydraulic erosion: the working image moves to torch, the result moves back to the original backend, **untouched
    float64 layers are bit-identically the original** (no float32 round trip); thermal erosion differs from numpy
    at float32 rounding magnitude; hydraulic erosion's mass balance still adds up on torch
  · Turing FFT counts: per step rfft2 = 1 + number of scales, irfft2 = 2 × number of scales (stubbed counters) --
    prevents anyone from reverting "shared spectrum" to recomputing per scale; agrees with the old "three blurs" code within 5 steps to 1e-9
  · d8: the new code (pad once, compare in place) is bit-identical to the old "pad with nan per direction" code, including ties,
    plateaus, Rho8, tile
  · tree_levels: levels partition all pixels, each level's receivers are in the previous level, a cycle raises
  · batched quad ear clipping: identical one by one to per-quad ear clipping on smooth / rough / planar concave / twisted quads;
    degenerate ones like collinear / duplicate points are marked unsafe (the caller sends them back to per-quad ear clipping); with convex_polygons, before and after
    the batched path, the heightfield mesh triangles are identical one by one
  · Nodes: all 8 nodes gain Compute, placed last among the widgets, options = auto / cpu / cuda
"""
import math
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo.cop import CopImage                 # noqa: E402
from comfyui_pcg.geo.cop import accel as AC              # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg.geo.cop import sim as SM                # noqa: E402
from comfyui_pcg.geo.cop import fx as FX                 # noqa: E402
from comfyui_pcg.geo.cop import noisex as NX             # noqa: E402
from comfyui_pcg.geo.cop import flow as FL               # noqa: E402
from comfyui_pcg.geo.cop import terrain as TR            # noqa: E402
from comfyui_pcg.geo.cop import hydro as HY              # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
from comfyui_pcg.geo.cop.noise import cell_hash, _to01   # noqa: E402
from comfyui_pcg.geo import divide as DV                 # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP       # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
        check(name, False, "did not raise")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def L(img, name):
    return PX.getn(img, name)


def ex(**lay):
    """float64 layers -> image on the exact backend (output also kept as float64, comparisons don't go through float32)."""
    first = next(iter(lay.values()))
    H, W = first.shape[:2]
    return CopImage(W, H, {k: np.asarray(v, np.float64) for k, v in
                           lay.items()})


HAS_TORCH = BK.torch_module() is not None
rng = np.random.default_rng(65)

# ═══════════════════════════════════════════════════════ Operator table
sec("Engine operator table: numpy and torch agree element-wise")
X0 = AC.NUMPY
check("default engine is numpy float64, operator table is the exact backend",
      X0.name == "numpy" and X0.ops is BK.EXACT and not X0.is_torch)
if not HAS_TORCH:
    print("  (no torch, skipping the torch half)")
else:
    XT, why = AC.pick(None, "torch_cpu")
    check("torch_cpu gets the torch engine (internal option for tests only)",
          XT.is_torch and XT.name == "torch:cpu", why)
    a = rng.standard_normal((7, 9))
    a3 = rng.standard_normal((7, 9, 3))
    for m in ("edge", "wrap", "zero"):
        ok = all(np.array_equal(XT.np(XT.pad(XT.arr(z), r, m)),
                                X0.pad(z, r, m)) for z in (a, a3)
                 for r in (1, 3))
        ref = np.pad(a, 2, mode={"zero": "constant"}.get(m, m))
        check(f"pad {m}: both sides identical, and equal to np.pad (2D / 3D, r = 1 / 3)",
              ok and np.array_equal(X0.pad(a, 2, m), ref))
    err("pad with a garbage mode raises", lambda: XT.pad(XT.arr(a), 1, "reflect"), "mode")
    t = XT.arr(a)
    check("flip (single axis / both axes), roll identical on both sides",
          np.array_equal(XT.np(XT.flip(t, 1)), a[:, ::-1])
          and np.array_equal(XT.np(XT.flip(t, (0, 1))), a[::-1, ::-1])
          and np.array_equal(XT.np(XT.roll(t, -2, 0)), np.roll(a, -2, 0)))
    check("where / maximum / minimum accept Python scalars",
          np.array_equal(XT.np(XT.where(t > 0, 1.5, t)),
                         np.where(a > 0, 1.5, a))
          and np.array_equal(XT.np(XT.maximum(t, 0.25)), np.maximum(a, 0.25))
          and np.array_equal(XT.np(XT.minimum(0.25, t)), np.minimum(0.25, a)))
    A_t = XT.rfft2(t)
    check("rfft2 -> irfft2 round trip 1e-14, spectrum matches numpy",
          np.abs(XT.np(XT.irfft2(A_t, a.shape)) - a).max() < 1e-14
          and np.allclose(A_t.cpu().numpy(), np.fft.rfft2(a), atol=1e-12))
    check("fftfreq / rfftfreq identical on both sides",
          np.allclose(XT.np(XT.fftfreq(9)), np.fft.fftfreq(9))
          and np.allclose(XT.np(XT.rfftfreq(9)), np.fft.rfftfreq(9)))
    ii = XT.ops.to_i64(XT.floor(XT.arr(a * 5)))
    cl = XT.iclip(ii, 0, 3)
    check("iclip stays integer after clamping (torch.clamp with float bounds promotes to float, which crashes when used as an index)",
          str(cl.dtype) == "torch.int64" and int(cl.max()) == 3)
    check("arctan2 identical on both sides (numpy calls it arctan2, torch atan2)",
          np.allclose(XT.np(XT.arctan2(t, XT.flip(t, 0))),
                      np.arctan2(a, a[::-1])))
    h = cell_hash(XT.ops, ii, ii + 1, ii * 0, 7, 3)
    hn = cell_hash(BK.EXACT, np.floor(a * 5).astype(np.int64),
                   np.floor(a * 5).astype(np.int64) + 1,
                   np.zeros_like(a, np.int64), 7, 3)
    check("lattice hash bit-identical on the float64 torch operator table",
          np.array_equal(h.numpy(), hn)
          and np.array_equal(XT.np(_to01(XT.ops, h)), _to01(BK.EXACT, hn)))

# ═══════════════════════════════════════════════════════ pick
sec("pick: where to compute")
X, why = AC.pick(None, "cpu", 4096 * 4096)
check("cpu -> numpy, no matter how large", X is AC.NUMPY and "cpu" in why)
err("garbage Compute raises", lambda: AC.pick(None, "gpu"), "Compute")
if not BK.cuda_available():
    X, why = AC.pick(None, "auto", 1024 * 1024)
    check("auto, no CUDA -> numpy, with the reason in the explanation", X is AC.NUMPY
          and "CUDA" in why, why)
    X, why = AC.pick(None, "cuda", 1024 * 1024)
    check("cuda, no CUDA -> falls back to numpy, no error, says so", X is AC.NUMPY
          and "no CUDA available" in why, why)
if HAS_TORCH:
    ti = CopImage(8, 8, {"C": np.ones((8, 8, 1), np.float32)}).to_device("cpu")
    X, why = AC.pick(ti, "auto", 64)
    check("auto, input already on torch -> computes on that device (however small)",
          X.is_torch and X.name == "torch:cpu" and "follows input image" in why, why)
    # Stub a "CUDA": cuda_available -> True, the cuda engine impersonated by torch:cpu, only the decision is verified
    _ca, _te = BK.cuda_available, AC._torch_engine
    BK.cuda_available = lambda: True
    AC._torch_engine = lambda dev: _te("cpu")
    try:
        X1, w1 = AC.pick(None, "auto", BK.AUTO_PIXELS - 1)
        X2, w2 = AC.pick(None, "auto", BK.AUTO_PIXELS)
        big = int(BK.VRAM_BUDGET_MB * 1e6 / 8 / 8) + 1
        X3, w3 = AC.pick(None, "auto", big, 8)
        X4, w4 = AC.pick(None, "cuda", 16)
    finally:
        BK.cuda_available, AC._torch_engine = _ca, _te
    check("(stubbed CUDA) auto: fewer than AUTO_PIXELS pixels -> numpy", X1 is AC.NUMPY
          and "pixels" in w1, w1)
    check("(stubbed CUDA) auto: equal to AUTO_PIXELS -> GPU", X2.is_torch, w2)
    check("(stubbed CUDA) auto: estimated VRAM over VRAM_BUDGET_MB -> numpy, says how many MB",
          X3 is AC.NUMPY and "MB" in w3, w3)
    check("(stubbed CUDA) cuda: GPU however small", X4.is_torch, w4)

# ═══════════════════════════════════════════════════════ Consistency
sec("numpy and torch agree (float64 on both, threshold 1e-9)")
N = 48
J, I = np.meshgrid(np.arange(N), np.arange(N))
base = ex(seed=np.zeros((N, N, 1)),
          feed=(0.03 + 0.03 * J / N)[..., None],
          mask=(((J - 15) ** 2 + (I - 20) ** 2) < 20).astype(float)[..., None],
          wall=((J == 30) & (I > 8)).astype(float)[..., None],
          vel=rng.standard_normal((N, N, 2)),
          force=rng.standard_normal((N, N, 2)) * 0.1,
          density=rng.random((N, N, 3)),
          C=np.stack([np.sin(J / 4.0) * np.cos(I / 5.0)
                      + 0.2 * rng.standard_normal((N, N)) for _ in range(3)],
                     -1),
          dir=rng.standard_normal((N, N, 2)))
CASES = [
    ("Gray-Scott wrap", lambda c: SM.reaction_diffusion(
        base, steps=400, compute=c), ["rd_u", "rd_v"]),
    ("Gray-Scott clamp + per-pixel feed", lambda c: SM.reaction_diffusion(
        base, steps=300, edge="clamp", preset="custom", feed_layer="feed",
        compute=c), ["rd_u", "rd_v"]),
    ("Turing", lambda c: SM.reaction_diffusion(
        base, mode="turing", steps=15, scales="12 6 3", compute=c), ["rd_g"]),
    ("ripple reflect + walls", lambda c: SM.ripple(
        base, "mask", "wall", steps=150, compute=c),
     ["ripple", "ripple_prev"]),
    ("ripple wrap", lambda c: SM.ripple(base, "mask", "", steps=150,
                                      edge="wrap", compute=c), ["ripple"]),
    ("ripple absorb + driver", lambda c: SM.ripple(
        base, "mask", "", steps=120, edge="absorb", drive_frequency=0.05,
        damping=0.01, compute=c), ["ripple", "ripple_prev"]),
    ("flow simulate wrap + external force", lambda c: SM.flow(
        base, "vel", "density", steps=8, force_layer="force", dissipation=0.01,
        compute=c), ["vel", "density"]),
    ("flow simulate clamp", lambda c: SM.flow(
        base, "vel", "density", steps=8, edge="clamp", compute=c),
     ["vel", "density"]),
    ("flow project clamp", lambda c: SM.flow(
        base, "vel", "", mode="project", edge="clamp", compute=c), ["vel"]),
    ("TV denoise (three channels together)", lambda c: (FX.denoise_tv(
        base, "C", 0.3, 40, compute=c), {}), ["C"]),
    ("directional blur centered clamp", lambda c: (FX.directional_blur(
        base, "C", 7.0, 25.0, compute=c), {}), ["C"]),
    ("directional blur streak black", lambda c: (FX.directional_blur(
        base, "C", 9.0, 200.0, "streak", border="black", compute=c), {}),
     ["C"]),
    ("directional blur wrap", lambda c: (FX.directional_blur(
        base, "C", 5.5, -40.0, border="wrap", compute=c), {}), ["C"]),
]
for k in NX.NOISE_KINDS:
    CASES.append((f"Noise Extra {k}", (lambda kk: lambda c: (NX.noise_extra(
        base, kk, frequency=5.0, offset="0.3 -0.2 0.7",
        direction_layer="dir" if kk == "phasor" else "", compute=c), {}))(k),
        None))
CASES.append(("Noise Extra phasor without direction field", lambda c: (NX.noise_extra(
    base, "phasor", frequency=4.0, compute=c), {}), None))
for name, fn, lays in CASES:
    on, rn = fn("cpu")
    if lays is None:
        lays = [n for n in on.names if n.startswith("noise")]
    if not HAS_TORCH:
        continue
    ot, rt = fn("torch_cpu")
    d = max(float(np.abs(L(on, n) - L(ot, n)).max()) for n in lays)
    same_backend = on.backend is BK.EXACT and ot.backend is BK.EXACT
    check(f"{name}: diff {d:.1e}", d < 1e-9 and same_backend,
          "" if not rt else rt.get("compute", ""))

if HAS_TORCH:
    # Matching results are not enough: we must confirm the torch path **really computes on torch**, rather than computing on numpy
    # and converting afterwards (results would match, but on the GPU it would be wasted transfers). Listen to the arrays received by bilinear sampling
    from comfyui_pcg.geo.cop import filters as _FT
    seen = []
    _smp = _FT.sample

    def _spy(a, u, v, border="clamp", xp=None):
        seen.append(type(a).__module__.split(".")[0])
        return _smp(a, u, v, border, xp)
    _FT.sample = _spy
    try:
        FX.directional_blur(base, "C", 5.0, 10.0, compute="torch_cpu")
        k1 = set(seen)
        seen.clear()
        SM.flow(base, "vel", "density", steps=2, compute="torch_cpu")
        k2 = set(seen)
    finally:
        _FT.sample = _smp
    check("directional blur / flow advection sample torch tensors under the torch engine (not converted after computing)",
          k1 == {"torch"} and k2 == {"torch"}, f"{k1} {k2}")

# ═══════════════════════════════════════════════════════ Against the pcg64 implementation
sec("numpy path vs the pcg64 implementation")


def tv_ref(f, lam, it):
    """pcg64's denoise_tv: one channel at a time."""
    def grad(u):
        gx = np.zeros_like(u)
        gy = np.zeros_like(u)
        gx[:, :-1] = u[:, 1:] - u[:, :-1]
        gy[:-1, :] = u[1:, :] - u[:-1, :]
        return gx, gy

    def div(px, py):
        d = np.zeros_like(px)
        d[:, 0] += px[:, 0]
        d[:, 1:-1] += px[:, 1:-1] - px[:, :-2]
        d[:, -1] += -px[:, -2]
        d[0, :] += py[0, :]
        d[1:-1, :] += py[1:-1, :] - py[:-2, :]
        d[-1, :] += -py[-2, :]
        return d
    res = np.empty_like(f)
    for c in range(f.shape[2]):
        g = f[..., c]
        px = np.zeros_like(g)
        py = np.zeros_like(g)
        for _ in range(it):
            gx, gy = grad(div(px, py) - g / lam)
            nrm = 1.0 + 0.125 * np.hypot(gx, gy)
            px = (px + 0.125 * gx) / nrm
            py = (py + 0.125 * gy) / nrm
        res[..., c] = g - lam * div(px, py)
    return res


C0 = L(base, "C")
check("TV denoise: three channels together = one channel at a time (bit-identical)",
      np.array_equal(L(FX.denoise_tv(base, "C", 0.3, 40, compute="cpu"), "C"),
                     tv_ref(C0, 0.3, 40)))


def lap9_ref(a):
    p = np.pad(a, 1, mode="wrap")
    return (0.2 * (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])
            + 0.05 * (p[:-2, :-2] + p[:-2, 2:] + p[2:, :-2] + p[2:, 2:]) - a)


A_ = rng.random((33, 40))
check("nine-point Laplacian (adding the rows above and below first) matches the old neighbour-by-neighbour sum to 1e-15",
      np.abs(SM._lap9(AC.NUMPY, A_, "wrap") - lap9_ref(A_)).max() < 1e-15)


def blur_ref(a, sigma):
    H, W = a.shape
    fy = np.fft.fftfreq(H)[:, None]
    fx = np.fft.fftfreq(W)[None, :]
    g = np.exp(-2 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    return np.fft.ifft2(np.fft.fft2(a) * g).real


def turing_ref(g, sc, amt, n):
    """pcg64's Turing: three complex FFT blurs per scale."""
    for _ in range(n):
        best = None
        for r, st in zip(sc, amt):
            act = blur_ref(g, r / 2)
            inh = blur_ref(g, r)
            var = blur_ref(np.abs(act - inh), 1.0)
            inc = np.where(act > inh, st, -st)
            if best is None:
                best, bi = var, inc
            else:
                m = var < best
                best = np.where(m, var, best)
                bi = np.where(m, inc, bi)
        g = g + bi
        lo, hi = g.min(), g.max()
        g = (g - lo) / max(hi - lo, 1e-12) * 2 - 1
    return g


sc = [12.0, 6.0, 3.0]
amt = [0.02 * (0.5 + 0.5 * i / 2) for i in range(3)][::-1]
g0 = rng.random((N, N)) * 2 - 1
o, _ = SM.reaction_diffusion(ex(rd_g=g0[..., None]), mode="turing", steps=5,
                             scales="12 6 3", compute="cpu")
d = np.abs(L(o, "rd_g")[..., 0] - turing_ref(g0, sc, amt, 5)).max()
check(f"Turing: shared spectrum + kernel subtraction + rfft2 agrees with the old three-blur code over 5 steps (diff {d:.1e})",
      d < 1e-9)



def gs_ref(U, V, F, K, n, Du=1.0, Dv=0.5, h=1.0):
    """pcg64's Gray-Scott loop (nine-point Laplacian summed neighbour by neighbour, wrap)."""
    for _ in range(n):
        uvv = U * V * V
        U = U + h * (Du * lap9_ref(U) - uvv + F * (1 - U))
        V = V + h * (Dv * lap9_ref(V) + uvv - (F + K) * V)
    return U, V


U0 = 1 - 0.5 * rng.random((N, N))
V0 = 0.5 * rng.random((N, N))
o, _ = SM.reaction_diffusion(ex(rd_u=U0[..., None], rd_v=V0[..., None]),
                             preset="custom", feed=0.037, kill=0.06,
                             steps=200, compute="cpu")
Ur, Vr = gs_ref(U0, V0, 0.037, 0.06, 200)
d = max(np.abs(L(o, "rd_u")[..., 0] - Ur).max(),
        np.abs(L(o, "rd_v")[..., 0] - Vr).max())
check(f"Gray-Scott: agrees with the old code over 200 steps (diff {d:.1e}, only summation order differs)",
      d < 1e-12)


def h01_ref(cx, cy, cz, seed, salt):
    return np.asarray(_to01(BK.EXACT, cell_hash(BK.EXACT, cx, cy, cz,
                                                 int(seed), salt)))


def bubble_ref(x, y, z, seed, radius, density):
    """pcg64's bubble (copied verbatim, numpy)."""
    import itertools
    best = np.zeros_like(x)
    bid = np.zeros_like(x)
    ix, iy, iz = (np.floor(t).astype(np.int64) for t in (x, y, z))
    for c in itertools.product((-1, 0, 1), repeat=3):
        cx, cy, cz = ix + c[0], iy + c[1], iz + c[2]
        dx = x - (cx + h01_ref(cx, cy, cz, seed, 1))
        dy = y - (cy + h01_ref(cx, cy, cz, seed, 2))
        dz = z - (cz + h01_ref(cx, cy, cz, seed, 3))
        on = h01_ref(cx, cy, cz, seed, 4) < float(density)
        r = float(radius) * (0.5 + 0.5 * h01_ref(cx, cy, cz, seed, 5))
        q = 1.0 - (dx * dx + dy * dy + dz * dz) / np.maximum(r * r, 1e-12)
        hh = np.where(on, np.sqrt(np.maximum(q, 0.0)), 0.0)
        m = hh > best
        best = np.where(m, hh, best)
        cid = (np.asarray(cell_hash(BK.EXACT, cx, cy, cz, 0, 7)) & 0xFFFFFF
               ).astype(np.float64)
        bid = np.where(m, cid, bid)
    return best, bid


u_, v_ = np.meshgrid((np.arange(N) + 0.5) / N, (np.arange(N) + 0.5) / N)
xb, yb = u_ * 5.0 + 0.3, v_ * 5.0 - 0.2
zb = np.full_like(xb, 0.7)
br, bi_ = bubble_ref(xb, yb, zb, 3, 0.8, 0.7)
o = NX.noise_extra(base, "bubble", frequency=5.0, offset="0.3 -0.2 0.7",
                   seed=3, compute="cpu")
check("Noise Extra bubble: bit-identical to the old code (slice height and id)",
      np.array_equal(L(o, "noise")[..., 0], br)
      and np.array_equal(L(o, "noise_id")[..., 0], bi_))

# FFT counts: stubbed counters
cnt = {"f": 0, "i": 0}
_rf, _irf = AC.Engine.rfft2, AC.Engine.irfft2


def _crf(self, a):
    cnt["f"] += 1
    return _rf(self, a)


def _cirf(self, A, shape):
    cnt["i"] += 1
    return _irf(self, A, shape)


AC.Engine.rfft2, AC.Engine.irfft2 = _crf, _cirf
try:
    SM.reaction_diffusion(base, mode="turing", steps=4, scales="12 6 3",
                          compute="cpu")
finally:
    AC.Engine.rfft2, AC.Engine.irfft2 = _rf, _irf
check(f"Turing per step rfft2 = 1 + number of scales, irfft2 = 2 × number of scales"
      f" (4 steps 3 scales: {cnt['f']} / {cnt['i']}, should be 16 / 24)",
      cnt == {"f": 16, "i": 24})

# Gray-Scott: output backend / resuming
o1, _ = SM.reaction_diffusion(None, steps=50, xres=40, yres=30, compute="cpu")
check("numpy in numpy out (float32 layers)",
      o1.backend is BK.NUMPY and o1.get("rd").dtype == np.float32)
if HAS_TORCH:
    ti = CopImage(40, 30, {"seed": np.zeros((30, 40, 1), np.float32)}) \
        .to_device("cpu")
    o2, r2 = SM.reaction_diffusion(ti, steps=50, compute="auto")
    check("torch in torch out (auto follows the input)",
          o2.backend.is_torch and "follows input image" in r2["compute"], r2["compute"])
    o3, r3 = SM.reaction_diffusion(None, steps=50, xres=40, yres=30,
                                   compute="torch_cpu")
    check("computed on torch with numpy input -> output put back on numpy",
          o3.backend is BK.NUMPY and np.abs(L(o3, "rd") - L(o1, "rd")).max()
          < 1e-6)

# ═══════════════════════════════════════════════════════ Thermal / hydraulic
sec("Thermal / hydraulic erosion: move over, compute, move back")
hgt = np.clip(0.5 + 0.35 * np.sin(J / 6.0) * np.cos(I / 7.0)
              + 0.05 * rng.standard_normal((N, N)), 0, None)
himg = ex(C=hgt[..., None], keepme=rng.random((N, N, 2)))
tn = TR.thermal_erode(himg, "C", strength=0.3, iterations=30, compute="cpu")
check("thermal erosion cpu: result on the exact backend", tn.backend is BK.EXACT)
if HAS_TORCH:
    tt = TR.thermal_erode(himg, "C", strength=0.3, iterations=30,
                          compute="torch_cpu")
    dd = np.abs(L(tt, "C") - L(tn, "C")).max()
    check(f"thermal erosion torch: result back on the exact backend, diff from numpy {dd:.1e}"
          " (float32 rounding magnitude, < 1e-4)",
          tt.backend is BK.EXACT and dd < 1e-4)
    check("  untouched float64 layers bit-identically the original (no float32 round trip)",
          tt.get("keepme") is himg.get("keepme"))
    check("  the debris layer is moved back too", "debris" in tt and tt.get("debris").dtype
          == np.float64)
    ht, rh = HY.hydraulic_erode(himg, "C", strength=0.3, droplets_per_pixel=0.5,
                                lifetime=12, compute="torch_cpu")
    bal = rh["mass_after"] - rh["mass_before"] + rh["outflow"] + rh["lost"]
    check(f"hydraulic erosion torch: result back on the exact backend, mass balance diff {bal:.1e}",
          ht.backend is BK.EXACT and abs(bal) < 1e-5
          and ht.get("keepme") is himg.get("keepme"), rh["compute"])
    ti = himg.to_device("cpu")
    ht2, rh2 = HY.hydraulic_erode(ti, "C", strength=0.3,
                                  droplets_per_pixel=0.2, lifetime=8,
                                  compute="cpu")
    check("hydraulic erosion: torch input + Compute = cpu -> computed on numpy, result put back on torch",
          ht2.backend.is_torch and rh2["compute"].startswith("numpy"),
          rh2["compute"])

# ═══════════════════════════════════════════════════════ d8 / levels
sec("Stream Power: d8 and depth levels")


def d8_ref(f, sm, tile=False, rho=None):
    """pcg64's d8: pad with nan once per direction, switch only on strictly greater."""
    H, W = f.shape
    best = np.zeros((H, W))
    bd = np.full((H, W), -1, np.int64)
    dg = None if rho is None else 2.0 - rho.reshape(H, W)
    for k, (dx, dy) in enumerate(FL._DIRS):
        dk = dg if (dg is not None and k >= 4) else FL._DIST[k]
        if tile:
            nb = np.roll(np.roll(f, -dy, 0), -dx, 1)
        else:
            p = np.pad(f, 1, constant_values=np.nan)
            nb = p[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
        s = (f - nb) / dk
        better = s > best
        best = np.where(better, s, best)
        bd = np.where(better, k, bd)
    return bd


def rcv_to_k(rcv, f):
    """d8 receiver -> direction number (for comparison)."""
    H, W = f.shape
    out = np.full(H * W, -1)
    ok = rcv >= 0
    src = np.flatnonzero(ok)
    ty, tx = np.divmod(rcv[ok], W)
    sy, sx = np.divmod(src, W)
    for k, (dx, dy) in enumerate(FL._DIRS):
        m = (((tx - sx) % W) == dx % W) & (((ty - sy) % H) == dy % H)
        out[src[m & (out[src] < 0)]] = k
    return out.reshape(H, W)


allok = True
for trial in range(6):
    f = np.round(rng.random((23, 31)) * (3 if trial % 2 else 1e6)) / 7.0
    f[5:9, 5:9] = f[5, 5]                         # plateau
    sm = np.zeros_like(f, bool)
    rho = rng.random(f.size) if trial >= 3 else None
    tile = trial in (1, 4)
    rcv, _ = FL.d8(f, sm, tile, rho)
    allok &= np.array_equal(rcv_to_k(rcv, f), d8_ref(f, sm, tile, rho))
check("new d8 code identical per pixel to the old code (integer heights create ties, plateaus, Rho8, tile)",
      allok)
f = rng.random((40, 50))
sm = FL.seeds(f.shape, False, None, f)
f = FL.priority_fill(f, sm, False)
rcv, _ = FL.d8(f, sm, False)
lv = FL.tree_levels(rcv)
flat = np.concatenate(lv)
check("tree_levels: levels partition all pixels exactly once",
      np.array_equal(np.sort(flat), np.arange(f.size)))
check("  level 0 = outlets (rcv < 0), all receivers of level k are in level k−1",
      bool((rcv[lv[0]] < 0).all()) and all(
          np.isin(rcv[lv[k]], lv[k - 1]).all() for k in range(1, len(lv))))
bad = rcv.copy()
a0 = int(lv[2][0])
b0 = int(rcv[a0])
bad[b0] = a0                                     # create a two-point cycle
err("  a cycle raises (doesn't silently compute less)", lambda: FL.tree_levels(bad), "cycle")

# ═══════════════════════════════════════════════════════ Quad ear clipping
sec("Batched quad ear clipping")


def quads():
    Q = 3000
    sq = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    for rough in (0.01, 1.0, 30.0):
        y = rough * rng.standard_normal((Q, 4))
        yield f"heightfield quads (roughness {rough})", np.stack(
            [np.broadcast_to(sq[:, 0], (Q, 4)), y,
             np.broadcast_to(sq[:, 1], (Q, 4))], -1)
    P = rng.random((Q, 4, 2)) * 2 - 1
    yield "random planar quads (both concave and self-intersecting)", np.concatenate(
        [P, np.zeros((Q, 4, 1))], -1)
    yield "random twisted 3D quads", rng.standard_normal((Q, 4, 3))


for name, P4 in quads():
    tq, uns = DV._ear_clip_quads(P4)
    old = np.array([DV._ear_clip(DV._plane_basis(p)) for p in P4])
    mism = int(((tq != old).any((1, 2)) & ~uns).sum())
    check(f"{name}: identical one by one to per-quad ear clipping (mismatched {mism}, unsafe {int(uns.sum())})",
          mism == 0 and uns.sum() < len(P4) * 0.01)
P = rng.random((400, 4, 3))
P[:200, 2] = 0.5 * (P[:200, 1] + P[:200, 3])     # three collinear points
P[200:, 1] = P[200:, 0]                          # duplicate point
_, uns = DV._ear_clip_quads(P)
check("degenerate quads with collinear / duplicate points all marked unsafe (sent back to per-quad ear clipping)", bool(uns.all()))
Pl = rng.integers(0, 3, (3000, 4, 3)).astype(float)
tq, uns = DV._ear_clip_quads(Pl)
old = np.array([DV._ear_clip(DV._plane_basis(p)) for p in Pl])
check("integer-lattice quads (many degenerate): those not unsafe identical one by one",
      not ((tq != old).any((1, 2)) & ~uns).any(), f"unsafe {int(uns.sum())}")

# Before and after the batched path behind convex_polygons: heightfield mesh
hq = ex(C=(0.3 * rng.standard_normal((20, 24)))[..., None])
g = TR.to_mesh(hq, "C", 1.0, 1.0, 1, True, False)
t_fast = DV.convex_polygons(g, "", 3)
_orig = DV._ear_clip_quads
DV._ear_clip_quads = lambda P4: None             # force per-quad ear clipping
try:
    t_slow = DV.convex_polygons(g, "", 3)
finally:
    DV._ear_clip_quads = _orig
check("convex_polygons: batched path and per-quad ear clipping produce identical meshes one by one (rough heightfield)",
      np.array_equal(t_fast.vertex_point, t_slow.vertex_point)
      and np.array_equal(t_fast.prim_offset, t_slow.prim_offset))
nconc = int((~DV.convex_mask(g)).sum())
check(f"  this mesh really has concave quads ({nconc} of them), the batched path really was taken", nconc > 16)

# ═══════════════════════════════════════════════════════ VRAM estimate
sec("auto's VRAM estimate uses the real channel count")
# Measured on the real machine (4090): Denoise TV / directional blur estimated VRAM with a hard-coded 4 channels, so single-channel
# 2048² was estimated at 1.3~1.6 GB > VRAM_BUDGET_MB and auto silently fell back to CPU (30x+ slower).
# Here pick's arguments are intercepted, no real CUDA needed.
_seen = []
_orig_pick = AC.pick


def _spy(img=None, compute="auto", pixels=0, arrays=8):
    _seen.append((int(pixels), int(arrays)))
    return _orig_pick(img, "cpu", pixels, arrays)


AC.pick = _spy
try:
    est = {}
    for ch in (1, 4):
        im = CopImage(16, 16, {"C": np.random.default_rng(0).random((16, 16, ch))})
        for nm, fn in (("tv", lambda im: FX.denoise_tv(im, "C", 0.1, 3)),
                       ("blur", lambda im: FX.directional_blur(im, "C", 4.0))):
            _seen.clear()
            fn(im)
            est[(nm, ch)] = _seen[-1][1]
finally:
    AC.pick = _orig_pick
px2k = 2048 * 2048
for nm in ("tv", "blur"):
    mb1 = px2k * est[(nm, 1)] * 8 / 1e6
    check(f"{nm}: single-channel 2048² estimated {mb1:.0f} MB ≤ budget {BK.VRAM_BUDGET_MB} MB (auto would use the GPU)",
          mb1 <= BK.VRAM_BUDGET_MB)
    check(f"{nm}: 4-channel estimate > single-channel ({est[(nm, 4)]} > {est[(nm, 1)]} images)",
          est[(nm, 4)] > est[(nm, 1)])

# ═══════════════════════════════════════════════════════ Nodes
sec("Nodes: Compute widget")
NODES = ["PCG_COPReactionDiffusion", "PCG_COPRipple", "PCG_COPFlowSolve",
         "PCG_COPDenoiseTV", "PCG_COPDirectionalBlur", "PCG_COPNoiseExtra",
         "PCG_COPThermalErosion", "PCG_COPHydraulicErosion"]
bad = []
for k in NODES:
    req = MAP[k].INPUT_TYPES()["required"]
    names = list(req)
    # pcg100 c3_noise, following the "new widgets are always appended at the end" rule, appended another batch after Noise Extra's compute
    # (Metric / Phasor Type / Post Processing …), so for that node the check is
    # "compute is still in its original position (after resolution_y)"; if the position doesn't move old workflows don't shift
    # pcg100 c5_heightfield likewise appended the Slump batch after Thermal Erosion's compute
    # (Slump Mode / Debris Source …); the check is that compute still directly follows keep_layers
    # pcg100 c7_filter_sim likewise appended the Maginu / Boundary /
    # Output Correction batch after Reaction Diffusion's compute; the check is that compute still directly follows resolution_y
    last = (names[names.index("resolution_y") + 1]
            if k in ("PCG_COPNoiseExtra", "PCG_COPReactionDiffusion")
            else names[names.index("keep_layers") + 1]
            if k == "PCG_COPThermalErosion" else names[-1])
    if last != "compute" or list(req["compute"][0]) != list(AC.COMPUTES):
        bad.append(k)
check(f"the last widget of all {len(NODES)} nodes is Compute (auto / cpu / cuda)"
      " -- placed last so other widgets don't shift when old workflows are opened", not bad, bad)


def unwrap(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


r = unwrap(MAP["PCG_COPReactionDiffusion"]().run(
    "gray_scott", "coral", 0.055, 0.062, 1.0, 0.5, 1.0, 20, "", 5, 3.0, "",
    "", "wrap", "32 16", 0.02, 0, "rd", 32, 32, "cpu"))
check("Reaction Diffusion node: the report says where it computed",
      "compute" in r[1] and "numpy" in r[1], r[1][:120])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
