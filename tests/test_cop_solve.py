"""
Completing Copernicus batch D: analysis / solvers / simulation (solve.py + sim.py + the 11 nodes in
nodes_cop2.py).

━━ Criteria
  · FFT: forward -> inverse round trip 1e-12; DC = pixel sum; Parseval; low-pass cutoff above
    Nyquist = identity; high-pass removes the mean; a single-frequency sine passes / doesn't pass depending on the cutoff
  · prefix sum: differencing gives back the image; integral image four lookups = rectangle sum; exclusive = inclusive − itself;
    reverse's first element = whole-row sum; integrate multiplies by the pixel width
  · Poisson: u -> ∇²u -> solved back to u (periodic and neumann are both direct solves, exact to 1e-10, up to a
    constant); gradient mode: height -> forward-difference gradient -> solved back to height; dirichlet: boundary fixed to a linear
    function, the interior solves to that same linear function (harmonic); fixed pixels untouched bit for bit
  · eikonal: single point source F = 1 -> Euclidean distance (first-order scheme, relative error far away < 3%); F = 2 -> time
    halved (per pixel); detours around walls (longer than a straight line), sealed regions unreachable (−1); id propagation
  · segmentation: same value but not connected -> two pieces; unique mode = Mono to ID; bounding box pixels / uv range
  · compare: the four ops pick right; Softness gives ½ where the difference is 0
  · Gray-Scott: the uniform state (U, V) = (1, 0) is a fixed point; translation-equivariant under wrap (np.roll
    bit for bit); resuming = running in one go (100 + 100 steps = 200 steps, bit for bit); dt too large errors
  · Turing: output 0-1; translation-equivariant
  · ripple: without damping the leapfrog discrete energy is strictly conserved (1e-10); symmetric initial state -> symmetric; wavefront speed ≈ c; always 0
    on walls; resuming = running in one go; CFL exceeded errors
  · fluid: divergence after projection (backward difference) = 0 (wrap and walls both to 1e-12); projection is idempotent; a pure gradient field
    projects to 0; advection with integer velocity = translation; density conserved under wrap (±5%)
  · ocean: imaginary residual 1e-12; significant wave height ≈ 4L√(πA) (closed-form integral of the Phillips spectrum, ±10%);
    Amplitude ×4 -> height ×2 (per pixel); slope variance downwind > crosswind; with choppiness 0
    the Jacobian = 1; single mode: back to the original after one period 2π/ω
"""
import json
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
from comfyui_pcg.geo.cop import solve as SV              # noqa: E402
from comfyui_pcg.geo.cop import sim as SM                # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
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
    return PX.getn(img, name)


def mk(**lay):
    first = next(iter(lay.values()))
    H, W = first.shape[:2]
    return CopImage(W, H, {k: np.asarray(v, np.float64) for k, v in
                           lay.items()})


rng = np.random.default_rng(7)
H, W = 40, 56
J, I = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))

# ═══════════════════════════════════════════════════════ FFT
sec("FFT")
a = rng.random((H, W, 1))
im = mk(C=a)
for cen in (True, False):
    f = SV.fft(im, "C", "forward", cen, out_layer="F")
    b = L(SV.fft(f, "F", "inverse", cen, out_layer="R"), "R")
    check(f"forward -> inverse round trip (centered={cen})",
          np.abs(b - a).max() < 1e-12)
F = L(SV.fft(im, "C", "forward", False, out_layer="F"), "F")
check("DC = pixel sum", abs(F[0, 0, 0] - a.sum()) < 1e-9 and
      abs(F[0, 0, 1]) < 1e-9)
check("Parseval:Σ|F|² = N·Σa²", abs((F ** 2).sum() - H * W * (a ** 2).sum())
      < 1e-6 * H * W * (a ** 2).sum())
Fc = L(SV.fft(im, "C", "forward", True, out_layer="F"), "F")
check("centered: DC at (H/2, W/2)", abs(Fc[H // 2, W // 2, 0] - a.sum())
      < 1e-9)
r = L(SV.fft(im, "C", "filter", filter="lowpass", cutoff=1000), "C")
check("low-pass cutoff above Nyquist = identity", np.abs(r - a).max() < 1e-12)
r = L(SV.fft(im, "C", "filter", filter="highpass", cutoff=0.5,
             softness=0.5), "C")
check("high-pass (cutoff ½ cycle) removes the mean, leaves the rest",
      abs(r.mean()) < 1e-12 and np.abs(r - (a - a.mean())).max() < 1e-12)
s3 = np.sin(2 * math.pi * 3 * J / W)[..., None]
s12 = np.sin(2 * math.pi * 12 * J / W)[..., None]
mix = mk(C=s3 + s12)
lp = L(SV.fft(mix, "C", "filter", filter="lowpass", cutoff=7, softness=2),
       "C")
check("low-pass 7: the 3-cycle sine stays, the 12-cycle one goes", np.abs(lp - s3).max() < 1e-12)
bp = L(SV.fft(mix, "C", "filter", filter="bandpass", cutoff=7,
              cutoff_high=20, softness=2), "C")
check("band-pass 7-20: only the 12-cycle one remains", np.abs(bp - s12).max() < 1e-12)
bs = L(SV.fft(mix, "C", "filter", filter="bandstop", cutoff=7,
              cutoff_high=20, softness=2), "C")
check("band-stop 7-20: only the 3-cycle one remains", np.abs(bs - s3).max() < 1e-12)
sv5 = np.sin(2 * math.pi * 5 * I / H)[..., None]
lph = L(SV.fft(mk(C=sv5), "C", "filter", filter="lowpass", cutoff=6.5,
               softness=0.5), "C")
check("  frequencies are per axis: 5 cycles along v (height 40) pass low-pass 6.5",
      np.abs(lph - sv5).max() < 1e-12)
lph = L(SV.fft(mk(C=sv5), "C", "filter", filter="lowpass", cutoff=4.5,
               softness=0.5), "C")
check("  ...but not low-pass 4.5", np.abs(lph).max() < 1e-12)
ao = rng.random((41, 57, 1))
fo = SV.fft(mk(C=ao), "C", "forward", True, out_layer="F")
check("odd size (41×57) centered round trip (the case where fftshift ≠ ifftshift)",
      np.abs(L(SV.fft(fo, "F", "inverse", True, out_layer="R"), "R") - ao)
      .max() < 1e-12)
err("inverse needs 2 channels", lambda: SV.fft(im, "C", "inverse"), "2-channel")

# ═══════════════════════════════════════════════════════ prefix sum
sec("prefix sum")
p = L(SV.prefix_sum(im, "C", "u"), "C")
check("u: differencing along rows gives back the image", np.allclose(np.diff(p, axis=1), a[:, 1:])
      and np.allclose(p[:, 0], a[:, 0]))
sat = L(SV.prefix_sum(im, "C", "both"), "C")[..., 0]
y0, y1, x0, x1 = 5, 20, 7, 33


def rect_sum(S, y0, y1, x0, x1):
    tot = S[y1, x1]
    if y0 > 0:
        tot -= S[y0 - 1, x1]
    if x0 > 0:
        tot -= S[y1, x0 - 1]
    if y0 > 0 and x0 > 0:
        tot += S[y0 - 1, x0 - 1]
    return tot


check("integral image: sum of any rectangle with four lookups", abs(rect_sum(sat, y0, y1, x0, x1)
                                    - a[y0:y1 + 1, x0:x1 + 1].sum()) < 1e-9)
ex = L(SV.prefix_sum(im, "C", "v", exclusive=True), "C")
inc = L(SV.prefix_sum(im, "C", "v"), "C")
check("exclusive = inclusive − itself", np.allclose(ex, inc - a))
rv = L(SV.prefix_sum(im, "C", "u_reverse"), "C")
check("u_reverse: first column = whole-row sum", np.allclose(rv[:, 0, 0], a.sum(1)[:, 0]))
it_ = L(SV.prefix_sum(mk(C=np.ones((H, W, 1))), "C", "u", integrate=True),
        "C")
check("integrate: constant 1 integrated along u to the end = 1", np.allclose(it_[:, -1], 1.0))

# ═══════════════════════════════════════════════════════ Poisson
sec("Poisson")
u0 = rng.random((H, W))
f_per = SV.laplacian(u0, "periodic")
o, rep = SV.solve_poisson(mk(rhs=f_per[..., None]), "rhs",
                          boundary="periodic")
us = L(o, "solution")[..., 0]
check("periodic: ∇²u -> solved back to u (up to a constant, 1e-10)",
      np.abs((us - us.mean()) - (u0 - u0.mean())).max() < 1e-10)
f_nm = SV.laplacian(u0, "neumann")
o, rep = SV.solve_poisson(mk(rhs=f_nm[..., None]), "rhs",
                          boundary="neumann")
us = L(o, "solution")[..., 0]
check("neumann (mirror extension + direct FFT solve): ∇²u -> solved back to u (up to a constant, 1e-10)",
      np.abs((us - us.mean()) - (u0 - u0.mean())).max() < 1e-10,
      (np.abs((us - us.mean()) - (u0 - u0.mean())).max(), rep))
fz = rng.random((96, 70))
uz = SV._solve_neumann(fz)
check("  the direct solve satisfies ∇²u = f − mean(f) (residual 1e-10), mean 0, no iteration",
      np.abs(SV.laplacian(uz, "neumann") - (fz - fz.mean())).max() < 1e-10
      and abs(uz.mean()) < 1e-12 and rep["iterations"] == 0)
hgt = np.sin(J / 7.0) * np.cos(I / 5.0) + 0.02 * J
gx, gy = SV.grad_fwd(hgt, "neumann")
o, rep = SV.solve_poisson(mk(g=np.stack([gx, gy], -1)), "g", "gradient",
                          "neumann")
us = L(o, "solution")[..., 0]
check("gradient: height -> gradient -> solved back to height (up to a constant, 1e-10)",
      np.abs((us - us.mean()) - (hgt - hgt.mean())).max() < 1e-10)
fix = np.zeros((H, W, 1)); fix[0] = fix[-1] = 1; fix[:, 0] = fix[:, -1] = 1
lin = (0.3 * J - 0.2 * I + 1)[..., None]
o, rep = SV.solve_poisson(mk(rhs=np.zeros((H, W, 1)), fx=fix, val=lin),
                          "rhs", boundary="dirichlet", fixed_layer="fx",
                          value_layer="val", tolerance=1e-12)
us = L(o, "solution")
check("dirichlet: boundary fixed to a linear function -> the interior is that linear function (harmonic, 1e-8)",
      np.abs(us - lin).max() < 1e-8, np.abs(us - lin).max())
check("  fixed pixels untouched bit for bit", np.array_equal(us[fix > 0.5],
                                           lin[fix > 0.5]))
Rd = 128
fxd = np.zeros((Rd, Rd, 1)); fxd[0] = fxd[-1] = 1; fxd[:, 0] = fxd[:, -1] = 1
fxd[40:60, 50:90] = 1
Jd, Id = np.meshgrid(np.arange(Rd), np.arange(Rd))
vd = np.sin(Jd / 9.0)[..., None]
o, rep = SV.solve_poisson(mk(rhs=np.zeros((Rd, Rd, 1)), fx=fxd, val=vd),
                          "rhs", boundary="dirichlet", fixed_layer="fx",
                          value_layer="val", tolerance=1e-8)
ud = L(o, "solution")[..., 0]
lap = SV.laplacian(ud, "neumann")
check("dirichlet (with obstacles, 128²): FFT-preconditioned CG converges within 150 iterations, ∇²u = 0 on free pixels",
      rep["iterations"] < 150 and np.abs(lap[fxd[..., 0] < 0.5]).max() < 1e-6,
      (rep, np.abs(lap[fxd[..., 0] < 0.5]).max()))
err("dirichlet without a Fixed Layer -> error", lambda: SV.solve_poisson(
    mk(rhs=np.zeros((4, 4, 1))), "rhs", boundary="dirichlet"), "Fixed")

# ═══════════════════════════════════════════════════════ eikonal
sec("eikonal equation")
N = 121
Jn, In = np.meshgrid(np.arange(N, dtype=float), np.arange(N, dtype=float))
sd = np.zeros((N, N, 1)); sd[60, 60] = 1
o, rep = SV.eikonal(mk(seed=sd), "seed")
T = L(o, "arrival")[..., 0]
d = np.hypot(Jn - 60, In - 60)
rel = np.abs(T - d)[d > 40] / d[d > 40]
check("F = 1 single point source -> Euclidean distance (relative error far away < 3%), exact on the axes",
      rel.max() < 0.03 and abs(T[60, 120] - 60) < 1e-9 and rep["converged"],
      (rel.max(), rep))
check("  four-quadrant Gauss–Seidel: a point source converges in ≤ 3 sweeps", rep["sweeps"] <= 3,
      rep["sweeps"])
check("  T ≥ true distance (a first-order upwind scheme only overestimates)", np.all(T >= d - 1e-9))
o2, _ = SV.eikonal(mk(seed=sd), "seed", speed=2.0)
check("F = 2 -> arrival time halved (per pixel)", np.allclose(L(o2, "arrival")[..., 0],
                                            T / 2, atol=1e-12))
wall = np.ones((N, N, 1)); wall[20:101, 80] = 0
o3, _ = SV.eikonal(mk(seed=sd, sp=wall), "seed", "sp")
T3 = L(o3, "arrival")[..., 0]
check("walls block: points behind the wall must detour (over 20% longer than straight)",
      T3[60, 100] > 1.2 * 40 and T3[60, 80] == -1, T3[60, 100])
box = np.ones((N, N, 1)); box[10:30, 10] = 0; box[10:30, 30] = 0
box[10, 10:31] = 0; box[29, 10:31] = 0
o4, _ = SV.eikonal(mk(seed=sd, sp=box), "seed", "sp")
check("  sealed region unreachable (−1)", np.all(L(o4, "arrival")[15:25, 15:25] == -1))
s2 = np.zeros((N, N, 1)); s2[60, 10] = 1; s2[60, 110] = 1
o5, _ = SV.eikonal(mk(seed=s2), "seed", id_layer="nearest")
nid = L(o5, "nearest")[..., 0]
check("id propagation: left half belongs to the left seed, right half to the right one",
      len(np.unique(nid[:, :55])) == 1 and len(np.unique(nid[:, 66:])) == 1
      and nid[0, 0] != nid[0, -1])

# ═══════════════════════════════════════════════════════ segmentation / bounding box / compare
sec("segmentation / bounding box / compare")
two = np.zeros((20, 20, 1)); two[2:6, 2:6] = 0.5; two[12:18, 12:18] = 0.5
o, n = SV.segment_by_value(mk(C=two), "C", "bins", 2)
ids = L(o, "id")[..., 0]
check("same value, not connected -> two pieces (plus one for the background)", n == 3 and ids[3, 3] != ids[14, 14])
check("  numbered by descending area: background 1, large piece 2, small piece 3",
      ids[0, 0] == 1 and ids[14, 14] == 2 and ids[3, 3] == 3)
o, n = SV.segment_by_value(mk(C=two), "C", "bins", 2, connected=False)
check("connected off: one piece per value", n == 2 and L(o, "id")[3, 3, 0]
      == L(o, "id")[14, 14, 0])
mono = np.array([[3, 3, 7], [7, 9, 3]], float)[..., None]
o, n = SV.segment_by_value(mk(C=mono), "C", "unique", connected=False)
check("unique (Mono to ID): 3 distinct values -> 3 ids", n == 3 and
      L(o, "id")[0, 0, 0] == L(o, "id")[1, 2, 0])
o, txt = SV.bounding_rect(mk(mask=two), "mask", 0.25)
bx = json.loads(txt)
check("bounding box: pixel range [2, 2, 17, 17], uv [0.1, 0.1, 0.9, 0.9]",
      bx[0]["pixels"] == [2, 2, 17, 17] and np.allclose(bx[0]["uv"],
                                                          [0.1, 0.1, 0.9, 0.9]))
o, txt = SV.bounding_rect(mk(id=L(SV.segment_by_value(mk(C=two), "C", "bins",
                                                      2)[0], "id")),
                          "id", per_id=True)
check("  per id: 3 boxes, the small piece's is [2, 2, 5, 5]",
      len(json.loads(txt)) == 3 and
      [b["pixels"] for b in json.loads(txt) if b["id"] == 3] == [[2, 2, 5, 5]])
A_ = rng.random((8, 8, 3)); B_ = rng.random((8, 8, 3))
ci = mk(A=A_, B=B_)
r = L(SV.compare_blend(ci, op="a_greater"), "result")
check("a_greater: A where A[0] > B[0]", np.array_equal(
    r, np.where((A_[..., 0] > B_[..., 0])[..., None], A_, B_)))
r = L(SV.compare_blend(ci, op="brighter"), "result")
lum = lambda x: x @ [0.2126, 0.7152, 0.0722]           # noqa: E731
check("brighter: pick the brighter one by Rec.709 luminance", np.array_equal(
    r, np.where((lum(A_) > lum(B_))[..., None], A_, B_)))
r = L(SV.compare_blend(ci, op="closer_to_value", value=0.5), "result")
check("closer_to_value", np.array_equal(r, np.where(
    (np.abs(A_[..., 0] - 0.5) < np.abs(B_[..., 0] - 0.5))[..., None], A_,
    B_)))
eq = mk(A=np.full((2, 2, 1), 0.3), B=np.full((2, 2, 1), 0.3))
check("Softness > 0: ½ where the difference is 0", np.allclose(L(SV.compare_blend(
    eq, softness=0.1), "select_mask"), 0.5))

# ═══════════════════════════════════════════════════════ reaction-diffusion
sec("reaction-diffusion / Turing")
o, _ = SM.reaction_diffusion(None, spots=0, steps=50, xres=32, yres=32)
check("Gray-Scott: the uniform state (1, 0) is a fixed point", np.all(L(o, "rd_u") == 1) and
      np.all(L(o, "rd_v") == 0))
seedm = np.zeros((48, 48, 1)); seedm[20:26, 18:24] = 1
b0 = mk(s=seedm)
o1, _ = SM.reaction_diffusion(b0, seed_layer="s", steps=150)
o2, _ = SM.reaction_diffusion(mk(s=np.roll(seedm, (7, 11), (0, 1))),
                              seed_layer="s", steps=150)
check("wrap: initial state translated -> result translated (bit for bit)", np.array_equal(
    np.roll(L(o1, "rd"), (7, 11), (0, 1)), L(o2, "rd")))
check("  and a pattern really grows (V's variance increases, spreads beyond the seed area)",
      (L(o1, "rd") > 0.1).sum() > 36)
oa, _ = SM.reaction_diffusion(b0, seed_layer="s", steps=100)
ob, rp = SM.reaction_diffusion(oa, seed_layer="s", steps=100)
oc, _ = SM.reaction_diffusion(b0, seed_layer="s", steps=200)
check("resume: 100 + 100 steps = 200 steps in one go (bit for bit)",
      rp["continued"] and np.array_equal(L(ob, "rd"), L(oc, "rd")))
err("dt too large -> error", lambda: SM.reaction_diffusion(None, dt=1.0, du=1.5,
                                              xres=8, yres=8), "Unstable")
fk = np.full((32, 32, 1), 0.03)
o, _ = SM.reaction_diffusion(mk(f=fk, k=np.full((32, 32, 1), 0.2)),
                             preset="custom", feed_layer="f",
                             kill_layer="k", steps=300)
check("Feed / Kill Layer take effect per pixel (V dies out when kill is large)",
      L(o, "rd").max() < 1e-3)
t1, _ = SM.reaction_diffusion(None, "turing", steps=20, xres=64, yres=64,
                              scales="16 8 4")
tv = L(t1, "rd")
check("Turing: output 0-1, both ends reached", tv.min() == 0 and tv.max() == 1)
g0 = L(t1, "rd_g")
ta, _ = SM.reaction_diffusion(mk(rd_g=g0), "turing", steps=5, scales="16 8 4")
tb, _ = SM.reaction_diffusion(mk(rd_g=np.roll(g0, (5, 9), (0, 1))), "turing",
                              steps=5, scales="16 8 4")
check("  translation-equivariant (1e-9)", np.abs(np.roll(L(ta, "rd"), (5, 9), (0, 1))
                                 - L(tb, "rd")).max() < 1e-9)

# ═══════════════════════════════════════════════════════ ripple
sec("ripple")
Nw = 96
Jw, Iw = np.meshgrid(np.arange(Nw, dtype=float), np.arange(Nw, dtype=float))
bump = np.exp(-((Jw - 47.5) ** 2 + (Iw - 47.5) ** 2) / 8.0)[..., None]
o, r0 = SM.ripple(mk(s=bump), "s", speed=0.5, steps=1, edge="wrap")
o, r1 = SM.ripple(mk(s=bump), "s", speed=0.5, steps=150, edge="wrap")
check("undamped wrap: leapfrog discrete energy strictly conserved (1 step vs 150 steps, 1e-10)",
      abs(r1["energy"] / r0["energy"] - 1) < 1e-10, (r0["energy"],
                                                     r1["energy"]))
o_, r2 = SM.ripple(mk(s=bump), "s", speed=0.5, steps=150, edge="reflect")
check("  reflect borders conserve too (neumann's ∇² is also −∇ᵀ∇)",
      abs(r2["energy"] / r0["energy"] - 1) < 1e-10)
hh = L(o, "ripple")[..., 0]
check("symmetric initial state -> symmetric (up/down, left/right, transpose)", np.allclose(hh, hh[::-1]) and
      np.allclose(hh, hh[:, ::-1]) and np.allclose(hh, hh.T))
o, _ = SM.ripple(mk(s=bump), "s", speed=0.5, steps=60, edge="reflect")
hh = np.abs(L(o, "ripple")[..., 0])
rad = np.hypot(Jw - 47.5, Iw - 47.5)
ring = [hh[(rad >= r_) & (rad < r_ + 1)].max() for r_ in range(45)]
peak = int(np.argmax(ring))
check("wavefront near c·t = 30 pixels (±4)", abs(peak - 30) <= 4, peak)
wl = np.zeros((Nw, Nw, 1)); wl[:, 70] = 1
o, _ = SM.ripple(mk(s=bump, w=wl), "s", "w", speed=0.5, steps=80)
check("always 0 on the wall", np.all(L(o, "ripple")[:, 70] == 0))
oa, _ = SM.ripple(mk(s=bump), "s", speed=0.6, steps=40, damping=0.01)
ob, rb = SM.ripple(oa, "s", speed=0.6, steps=40, damping=0.01)
oc, _ = SM.ripple(mk(s=bump), "s", speed=0.6, steps=80, damping=0.01)
check("resume 40 + 40 = 80 in one go (bit for bit), step count stored in _t",
      np.array_equal(L(ob, "ripple"), L(oc, "ripple")) and rb["steps"] == 80
      and np.all(L(ob, "ripple_t") == 80))
src = np.zeros((Nw, Nw, 1)); src[48, 20] = 1
da, _ = SM.ripple(mk(s=src), "s", speed=0.5, steps=30, drive_frequency=0.05)
db, _ = SM.ripple(da, "s", speed=0.5, steps=30, drive_frequency=0.05)
dc, _ = SM.ripple(mk(s=src), "s", speed=0.5, steps=60, drive_frequency=0.05)
check("resuming with continuous driving is also bit-identical (the driving phase continues from _t)",
      np.array_equal(L(db, "ripple"), L(dc, "ripple")))
o, rd_ = SM.ripple(mk(s=bump), "s", speed=0.5, steps=200, damping=0.05)
check("damped: energy decays", rd_["energy"] < 0.01 * r0["energy"])
o, ra = SM.ripple(mk(s=bump), "s", speed=0.5, steps=300, edge="absorb",
                  absorb_width=20)
o, rr = SM.ripple(mk(s=bump), "s", speed=0.5, steps=300, edge="reflect")
check("absorb: the sponge layer eats most of the energy (relative to reflect)",
      ra["energy"] < 0.3 * rr["energy"], (ra["energy"], rr["energy"]))
err("CFL exceeded -> error", lambda: SM.ripple(None, speed=0.8), "CFL")

# ═══════════════════════════════════════════════════════ fluid
sec("fluid")
Hf, Wf = 32, 48
v = rng.normal(size=(Hf, Wf, 2))
for edge, tol in (("wrap", 1e-12), ("clamp", 1e-12)):
    vx, vy = SM.project(v[..., 0], v[..., 1], edge, 1e-13, 20000)
    bnd = "periodic" if edge == "wrap" else "neumann"
    dv = SV.divergence(vx, vy, bnd)
    check(f"{edge}: divergence after projection = 0 (< {tol:g})", np.abs(dv).max() < tol,
          np.abs(dv).max())
    vx2, vy2 = SM.project(vx, vy, edge, 1e-13, 20000)
    check(f"  {edge}: projection is idempotent", np.abs(vx2 - vx).max() < 1e-6 and
          np.abs(vy2 - vy).max() < 1e-6)
pg = rng.random((Hf, Wf))
gx, gy = SV.grad_fwd(pg, "periodic")
vx, vy = SM.project(gx, gy, "wrap")
check("a pure gradient field projects to 0", np.abs(vx).max() < 1e-12 and np.abs(vy).max()
      < 1e-12)
den = rng.random((Hf, Wf, 1))
uni = np.zeros((Hf, Wf, 2)); uni[..., 0] = 3.0
o, rep = SM.flow(mk(vel=uni, density=den), steps=2, edge="wrap")
check("uniform velocity (3, 0) for 2 steps = translation by 6 pixels (per pixel, wrap)",
      np.allclose(L(o, "density"), np.roll(den, 6, 1), atol=1e-12))
check("  the velocity field itself is unchanged", np.allclose(L(o, "vel"), uni))
sw = np.zeros((Hf, Wf, 2))
sw[..., 0] = np.sin(2 * math.pi * np.arange(Hf) / Hf)[:, None] * 1.5
o, rep = SM.flow(mk(vel=sw, density=den), steps=10, edge="wrap")
check("shear flow 10 steps: total density conserved (±5%, semi-Lagrangian is not strictly conservative)",
      abs(L(o, "density").sum() / den.sum() - 1) < 0.05)
check("  divergence in the report ≈ 0", rep["max_divergence"] < 1e-10)
o, rep = SM.flow(mk(vel=v), mode="project", edge="clamp")
check("project mode: normal flux through clamp walls is 0",
      np.all(L(o, "vel")[:, -1, 0] == 0) and np.all(L(o, "vel")[-1, :, 1]
                                                    == 0))

# ═══════════════════════════════════════════════════════ ocean
sec("ocean")
o, rep = SM.ocean(None, size=1000, wind_speed=12, xres=128, yres=128)
hh = L(o, "ocean")[..., 0]
Lw = 144 / 9.81
Hs_ana = 4 * Lw * math.sqrt(math.pi * 8.8e-4)
check("the inverse transform is real (imaginary residual < 1e-9)", rep["imag_residual"] < 1e-9,
      rep["imag_residual"])
check(f"significant wave height 4σ ≈ 4L√(πA) = {Hs_ana:.2f} m (±10%)",
      abs(4 * hh.std() / Hs_ana - 1) < 0.1, 4 * hh.std())
check("  mean 0 (no DC)", abs(hh.mean()) < 1e-9)
o4, _ = SM.ocean(None, size=1000, wind_speed=12, amplitude=4 * 8.8e-4,
                 xres=128, yres=128)
check("Amplitude ×4 -> height ×2 (per pixel)", np.allclose(
    L(o4, "ocean"), 2 * L(o, "ocean"), atol=1e-6))
h0, KX, KY, w = SM.ocean_spectrum(128, 128, 200, 12, 0, 8.8e-4, 2, 0.0, 1)
fl = SM.ocean_fields(h0, KX, KY, w, 0.0, 0.0)
check("slope variance downwind (u) > 3× crosswind", fl["sx"].var() > 3 *
      fl["sy"].var(), (fl["sx"].var(), fl["sy"].var()))
check("choppiness 0: Jacobian ≡ 1", np.allclose(fl["jacobian"], 1.0))
fl1 = SM.ocean_fields(h0, KX, KY, w, 0.0, 1.5)
check("choppiness 1.5: the Jacobian's mean is still 1 (periodic displacement field, no net compression)",
      abs(fl1["jacobian"].mean() - 1) < 1e-9)
one = np.zeros_like(h0); one[0, 5] = 0.3 + 0.1j
per = 2 * math.pi / w[0, 5]
fa = SM.ocean_fields(one, KX, KY, w, 1.3, 1.0)
fb = SM.ocean_fields(one, KX, KY, w, 1.3 + per, 1.0)
check("single mode: back to the original after one period 2π/ω (dispersion ω = √(gk))",
      np.allclose(fa["height"], fb["height"], atol=1e-12) and
      abs(w[0, 5] - math.sqrt(9.81 * 2 * math.pi * 5 / 200)) < 1e-12)
fh = SM.ocean_fields(one, KX, KY, w, 1.3 + per / 2, 1.0)
check("  negated after half a period", np.allclose(fh["height"], -fa["height"],
                                      atol=1e-12))
check("normal layer is unit length and points up", np.allclose(np.linalg.norm(
    L(o, "ocean_N"), axis=-1), 1, atol=1e-5) and L(o, "ocean_N")[..., 2]
      .min() > 0)

# ═══════════════════════════════════════════════════════ torch / nodes
sec("torch / nodes")
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
if BK.get("cpu") is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    ti = CopImage(W, H, {"C": a.astype(np.float32)}).to_device("cpu")
    for nm, fn in (("fft filter", lambda z: SV.fft(z, "C", "filter")),
                   ("prefix", lambda z: SV.prefix_sum(z, "C", "both"))):
        o_t = fn(ti)
        o_n = fn(CopImage(W, H, {"C": a.astype(np.float32)}))
        check(f"[torch] {nm}: output still on torch and matches numpy",
              o_t.backend.is_torch and np.allclose(L(o_t, "C"), L(o_n, "C"),
                                                   atol=1e-3))
D_ = ["PCG_COPFFT", "PCG_COPPrefixSum", "PCG_COPSolvePoisson",
      "PCG_COPEikonal", "PCG_COPSegmentByValue", "PCG_COPBoundingRect",
      "PCG_COPSelect", "PCG_COPReactionDiffusion", "PCG_COPRipple",
      "PCG_COPFlowSolve", "PCG_COPOcean"]
check(f"all {len(D_)} nodes of batch D registered, all in PCG/cop",
      all(k in MAP and MAP[k].CATEGORY == "PCG/cop" for k in D_))
bad = [k for k in D_ for nm in MAP[k].INPUT_TYPES()["required"]
       if nm == "seed"]
check("  no widget called seed", not bad, bad)
r = MAP["PCG_COPOcean"]().run(100.0, 12.0, 0.0, 8.8e-4, 2.0, 0.1, 0.0, 1.0,
                              0.3, 0, "ocean", 32, 32)
r = tuple(r["result"]) if isinstance(r, dict) else r
check("  Ocean's second output is a JSON report", "imag_residual" in json.loads(r[1]))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
