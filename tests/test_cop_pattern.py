"""
Copernicus completion batch C: patterns / five more noises / text / scatter shapes / autostereogram
(pattern.py + noisex.py + stamp.py + the 5 nodes in nodes_cop2.py).

━━ Criteria
  · Periodicity: every tiling pattern shifted by a whole tile in u and v (u + 1) leaves main and auxiliary layers unchanged -- calls
    the internal functions directly with shifted coordinates, stricter than "looking at the seam"
  · Checker: when the tile count divides the resolution there are only 0 / 1, mean ½, every id has the same area; otherwise edges carry
    coverage (analytic box filter), whole-image mean still ≈ ½
  · Brick: 0 in the mortar, 1 at brick centers; the random value is constant within an id; with a ½-brick offset the second row's joints sit exactly on
    the center lines of the first row's bricks
  · Cell: _edge is the true pixel distance to "another cell" (compared with brute-force search, ±1 pixel),
    not F2 − F1 (negative control: F2 − F1 reads too high mid-edge)
  · UV grid: A1 at the bottom-left corner; ids increase by column
  · Julia c = 0: smooth iteration count is exactly 1 − log₂ ln|z₀| (independent of the step at which it escapes),
    interior = unit circle
  · Chladni: the "−" mode is antisymmetric f(x,y) = −f(y,x), the diagonal is a nodal line; "+" is symmetric
  · Weave: plain has the warp on top at crossings where (i + j) is even; satin has each warp thread over exactly 1 of every 5
    crossings
  · Crystal: a single cell is one flat plane (second difference = 0)
  · Phasor: with angle 0, spread 0 stripes run along x, FFT main peak at Frequency × Stripe
  · Curl: the 2D field = (∂ψ/∂y, −∂ψ/∂x) (compared with differences of the _potential layer), divergence ≈ 0;
    3D divergence in 3D ≈ 0 (z direction by differencing two slices)
  · Cloud: coverage 0 all empty, 1 all full, monotonic in between
  · Text: position / alignment / row 0 at the top (the bar of T is on top)
  · Scatter shapes: area of a single circle stamp = πr² (±1%), stamps touching the edge conserve area after tiling, pscale ×2
    area ×4, Min Distance keeps every pair far enough apart, Count + 1 leaves earlier positions unchanged; geometry coordinate convention
    strictly identical to HeightField to Mesh
  · Stereogram: every pixel has the same colour as the pixel s to its left; the separation solved back from the image = the _sep layer
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
from comfyui_pcg.geo.cop import pattern as PT            # noqa: E402
from comfyui_pcg.geo.cop import noisex as NX             # noqa: E402
from comfyui_pcg.geo.cop import stamp as ST              # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT         # noqa: E402
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


def P(kind, W=64, H=64, **kw):
    return PT.pattern(None, kind, xres=W, yres=H, **kw)


# ═══════════════════════════════════════════════════════ Periodicity
sec("Periodicity (unchanged under u + 1, v + 1)")
W, H = 96, 64
u, v = PT._pix(W, H)
cases = {
    "checker": lambda a, b: PT._checker(a, b, W, H, 6, 4),
    "tile": lambda a, b: PT._tile(a, b, W, H, 4, 8, 0.5, 0.05, 0.1, 3),
    "cell": lambda a, b: PT._cell(a, b, W, H, 5, 3, 1.0, 0.05, 3),
    "knit": lambda a, b: PT._knit(a, b, W, H, 6, 5, 3),
    "weave": lambda a, b: PT._weave(a, b, W, H, 8, 6, "twill", 0.8, 3),
}
for k, fn in cases.items():
    r0, r1 = fn(u, v), fn(u + 1.0, v + 1.0)
    bad = [n for n in r0 if not np.allclose(r0[n], r1[n], atol=1e-6)]
    check(f"{k}: all layers unchanged at (u+1, v+1)", not bad, bad)

# ═══════════════════════════════════════════════════════ Checker / brick / cell
sec("Checker / brick / cell")
c = P("checker", counts="8 8")
a = L(c, "pattern")[..., 0]
check("8×8 dividing 64: only 0 / 1 (1e-9), mean ½",
      np.all(np.minimum(np.abs(a), np.abs(a - 1)) < 1e-9)
      and abs(a.mean() - 0.5) < 1e-12)
ids = L(c, "pattern_id")[..., 0].astype(int)
check("  64 ids with 64 pixels each", np.all(np.bincount(ids.ravel(),
                                                 minlength=64) == 64))
check("  the bottom-left cell is 0, adjacent cells are opposite", a[0, 0] < 0.5 and a[0, 8] > 0.5
      and a[8, 0] > 0.5)
a7 = L(P("checker", counts="7 7"), "pattern")[..., 0]
frac = ((a7 > 1e-9) & (a7 < 1 - 1e-9)).mean()
check("7 cells not dividing: edges carry coverage (0 < value < 1), whole-image mean ≈ ½",
      frac > 0.05 and abs(a7.mean() - 0.5) < 0.02, (frac, a7.mean()))

# 7×5 tiles, 64×48: non-square cells, edges not on pixel boundaries. Compared against a 64×64 supersampled hard-edged checker
a75 = L(P("checker", 64, 48, counts="7 5"), "pattern")[..., 0]
ss = 64
jj, ii = np.meshgrid((np.arange(64 * ss) + 0.5) / (64 * ss),
                     (np.arange(48 * ss) + 0.5) / (48 * ss))
hard = ((np.floor(jj * 7) + np.floor(ii * 5)) % 2).reshape(48, ss, 64, ss) \
    .mean((1, 3))
check("checker coverage = area of the value-1 cells within the pixel (vs supersampling, ±0.02; non-square cells)",
      np.abs(a75 - hard).max() < 0.02, np.abs(a75 - hard).max())
t = P("tile", 128, 128, counts="4 8", offset=0.5, gap=0.25, bevel=0.2,
      seed=1)
m = L(t, "pattern")[..., 0]
check("brick: brick center = 1", m[8, 16] == 1 and m[8, 48] == 1)
check("  first row's vertical joint (x = 32) is 0, the second row's vertical joint offset by half a brick (x = 16)",
      m[4, 31] == 0 and m[4, 32] == 0 and m[20, 15] == 0 and m[20, 16] == 0
      and m[20, 31] == 1)
check("  horizontal joints are 0", np.all(m[15:17, :] == 0))
check("  joint width: Gap 0.25 × short side 16 = 4 pixels -- 2 pixels on each side of the joint are 0, the 3rd is 1",
      m[4, 30] == 0 and m[4, 33] == 0 and m[4, 29] == 1 and m[4, 34] == 1)
tid = L(t, "pattern_id")[..., 0]
tr = L(t, "pattern_rand")[..., 0]
cst = all(np.ptp(tr[tid == k]) == 0 for k in np.unique(tid))
check("  one random value per brick (constant within a brick), 32 bricks", cst and len(np.unique(tid)) == 32)
hg = L(t, "pattern_height")[..., 0]
check("  bevel: 0~1, 0 in the joints, 1 at brick centers", hg.min() >= 0 and hg.max() <= 1 and
      hg[16, 0] == 0 and hg[8, 16] == 1)

S = 96
cl = P("cell", S, S, counts="5 5", gap=0.0, seed=4)
cid = L(cl, "pattern_id")[..., 0].astype(int)
ce = L(cl, "pattern_edge")[..., 0]
J, I = np.meshgrid(np.arange(S) + 0.5, np.arange(S) + 0.5)
rng = np.random.default_rng(0)
errs = []
f2f1 = []
for _ in range(60):
    i, j = rng.integers(0, S, 2)
    other = cid != cid[i, j]
    # Periodic: tile the image 3×3 before searching
    dd = np.inf
    for oy in (-S, 0, S):
        for ox in (-S, 0, S):
            d2 = (J[other] + ox - J[i, j]) ** 2 + (I[other] + oy - I[i, j]) ** 2
            dd = min(dd, np.sqrt(d2.min()))
    errs.append(abs(ce[i, j] - (dd - 0.5)))
check("cell _edge = pixel distance to another cell (brute-force search, ±1 pixel)",
      max(errs) < 1.0, max(errs))
# Anisotropic cells (8×3 tiles -> 12×32 pixels) must find the right nearest point too: compared with brute force
ua, va = PT._pix(96, 96)
la = PT._cell(ua, va, 96, 96, 8, 3, 1.0, 0.0, 9)
oxp, oyp = PT._cell_points(8, 3, 1.0, 9)
best_d = np.full((96, 96), np.inf)
best_i = np.zeros((96, 96), int)
for cj in range(3):
    for ci in range(8):
        for sy in (-1, 0, 1):
            for sx in (-1, 0, 1):
                px_ = (ci + oxp[cj, ci] + 8 * sx) * 12
                py_ = (cj + oyp[cj, ci] + 3 * sy) * 32
                d_ = (ua * 96 - px_) ** 2 + (va * 96 - py_) ** 2
                mm = d_ < best_d
                best_d = np.where(mm, d_, best_d)
                best_i = np.where(mm, cj * 8 + ci, best_i)
check("  anisotropic cells (12×32 pixels): id matches the brute-force nearest point",
      np.array_equal(la["id"].astype(int), best_i),
      (la["id"].astype(int) != best_i).mean())
ux, vx = PT._pix(S, S)
lay = PT._cell(ux, vx, S, S, 5, 5, 1.0, 0.0, 4)
check("  _dist ≈ 0 at its minimum within a cell (feature point)", lay["dist"].min() < 0.05)
cr = L(cl, "pattern_rand")[..., 0]
check("  one random value per cell", all(np.ptp(cr[cid == k]) == 0
                              for k in np.unique(cid)))

ug = P("uv_grid", 128, 128, counts="4 4")
gid = L(ug, "pattern_id")[..., 0]
check("UV grid: bottom-left id 0, +1 to the right, +4 upwards",
      gid[0, 0] == 0 and gid[0, 40] == 1 and gid[40, 0] == 4)
rgb = L(ug, "pattern")
cellA1 = rgb[4:28, 4:28]
dark = (cellA1.min(-1) < 0.2).astype(float)
check("  there is text in cell A1 (bottom-left, v up)", dark.mean() > 0.02)
gA = PT.render_text("A1", max(6, int(32 * 0.32)), "")
iy, ix = np.nonzero(dark)
blk = dark[iy.min():iy.max() + 1, ix.min():ix.max() + 1]
gv = (gA[::-1] > 0.5).astype(float)
gy_, gx_ = np.nonzero(gv)
gv = gv[gy_.min():gy_.max() + 1, gx_.min():gx_.max() + 1]
gs = (gA > 0.5).astype(float)
sy_, sx_ = np.nonzero(gs)
gs = gs[sy_.min():sy_.max() + 1, sx_.min():sx_.max() + 1]
same_shape = blk.shape == gv.shape
check("  text is upright (matches the glyphs flipped to v up, not the unflipped ones)",
      same_shape and (blk == gv).mean() > 0.9 and
      (blk.shape != gs.shape or (blk == gs).mean() < 0.9),
      blk.shape)
check("  cell names: A1 … Z1, AA1", PT._label(0, 0) == "A1" and
      PT._label(25, 0) == "Z1" and PT._label(26, 2) == "AA3")

# ═══════════════════════════════════════════════════════ Julia / Chladni
sec("Julia / Chladni")
Wj = 80
jl = PT.pattern(None, "julia", c="0 0", zoom=1.0, iterations=40, xres=Wj,
                yres=Wj)
uj, vj = PT._pix(Wj, Wj)
zr, zi = (uj - 0.5) * 3, (vj - 0.5) * 3
az = np.hypot(zr, zi)
it = L(jl, "pattern")[..., 0] * 40
sel = az > 1.02
ana = 1 - np.log2(np.log(az[sel]))
check("c = 0: smooth iteration count = 1 − log₂ ln|z₀| (independent of the step at which it escapes)",
      np.abs(it[sel] - ana).max() < 2e-5, np.abs(it[sel] - ana).max())  # stored as float32
ins = L(jl, "pattern_inside")[..., 0] > 0.5
check("  interior = unit circle", np.array_equal(ins[(az < 0.98) | (az > 1.02)],
                                   (az < 1)[(az < 0.98) | (az > 1.02)]))
mb = PT.pattern(None, "julia", mode="mandelbrot", center="-0.5 0",
                iterations=60, xres=81, yres=81)
mi = L(mb, "pattern_inside")[..., 0]
# x = −0.5 + (u − ½)·3: column 53 x ≈ −0.02 (in the set), column 80 x ≈ 0.98 (escapes)
check("Mandelbrot: c ≈ 0 is in the set, c ≈ 1 is not",
      mi[40, 53] == 1 and mi[40, 80] == 0)

ch = PT.pattern(None, "chladni", modes="2 5", sign="-", xres=64, yres=64)
fv = L(ch, "pattern_value")[..., 0]
check("Chladni −:f(x,y) = −f(y,x)", np.allclose(fv, -fv.T, atol=1e-12))
check("  the diagonal is a nodal line (line layer = 1)", np.all(L(ch, "pattern")[..., 0]
                                  [np.arange(64), np.arange(64)] == 1))
chp = PT.pattern(None, "chladni", modes="2 5", sign="+", xres=64, yres=64)
check("Chladni +: symmetric", np.allclose(L(chp, "pattern_value")[..., 0],
                                   L(chp, "pattern_value")[..., 0].T))
w1 = L(PT.pattern(None, "chladni", modes="3 4", line_width=1.0, xres=128,
                  yres=128), "pattern").sum()
w3 = L(PT.pattern(None, "chladni", modes="3 4", line_width=3.0, xres=128,
                  yres=128), "pattern").sum()
check("  line width in pixels: total of a width-3 line ≈ 3x that of width 1 (±15%)",
      abs(w3 / w1 - 3) < 0.45, w3 / w1)
w256 = L(PT.pattern(None, "chladni", modes="3 4", line_width=1.0, xres=256,
                    yres=256), "pattern").sum()
check("  doubling the resolution doubles the line total (lines get longer, width in pixels unchanged; ±10%)",
      abs(w256 / w1 - 2) < 0.2, w256 / w1)

# ═══════════════════════════════════════════════════════ Knit / weave
sec("Knit / weave")
kn = P("knit", 96, 96, counts="6 6")
kh = L(kn, "pattern")[..., 0]
check("knit: height 0~1, _mask ⇔ height > 0",
      kh.min() >= 0 and kh.max() <= 1 and np.array_equal(
          L(kn, "pattern_mask")[..., 0] > 0.5, kh > 0))
check("  coverage high enough (the loops cover most of the fabric)", (kh > 0).mean() > 0.5,
      (kh > 0).mean())
def cross(kind, n):
    """Read the crossings off the rendered image: [j, i] = warp thread i and weft thread j, is the warp on top?"""
    wv = PT.pattern(None, "weave", counts=f"{n} {n}", weave=kind,
                    xres=n * 10, yres=n * 10)
    return L(wv, "pattern_warp")[..., 0][5::10, 5::10] > 0.5


# Weave draft hard-coded (not computed from _over, so it doesn't test itself)
PLAIN = np.array([[1, 0], [0, 1]], bool)
TWILL = np.array([[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1], [1, 0, 0, 1]],
                 bool)
check("weave plain: crossings match the 1/1 draft", np.array_equal(
    cross("plain", 8), np.tile(PLAIN, (4, 4))))
check("weave twill: crossings match the 2/2 twill draft (shifted one cell per row)", np.array_equal(
    cross("twill", 8), np.tile(TWILL, (2, 2))))
sat = cross("satin", 10)
check("weave satin: each warp thread over exactly 1 of every 5 crossings, each weft thread too, period 5",
      np.all(sat.sum(0) == 2) and np.all(sat.sum(1) == 2) and
      np.array_equal(sat[:5], sat[5:]) and np.array_equal(sat[:, :5],
                                                          sat[:, 5:]))
err("mistyped weave name raises", lambda: P("weave", weave="x"), "Weave")

# ═══════════════════════════════════════════════════════ Five noises
sec("Five noises")
N = lambda k, W=96, H=96, **kw: NX.noise_extra(None, k, xres=W, yres=H,  # noqa
                                               **kw)
b0 = L(N("bubble", density=0.0), "noise")
b5 = L(N("bubble", density=0.5), "noise")
b1 = L(N("bubble", density=1.0), "noise")
check("bubble: 0~1; density 0 all empty, higher gives more coverage",
      b0.max() == 0 and 0 <= b1.min() and b1.max() <= 1
      and (b5 > 0).mean() < (b1 > 0).mean())
rect_ = L(N("bubble", 128, 64, frequency=5), "noise")
sq_ = L(N("bubble", 128, 128, frequency=5), "noise")
check("  coordinates by image width, aspect preserved: a 128×64 image = the lower half of 128×128 (bit-identical)",
      np.array_equal(rect_, sq_[:64]))
ba = L(N("bubble", offset="0 0 0.3"), "noise")
bb = L(N("bubble", offset="0 0 0.31"), "noise")
check("  a small step in z changes the slice only slightly (continuous)", np.abs(ba - bb).max() < 0.35
      and np.abs(ba - bb).mean() < 0.02, (np.abs(ba - bb).max(),
                                          np.abs(ba - bb).mean()))

cr_ = N("crystal", 128, 128, frequency=4)
cv = L(cr_, "noise")[..., 0]
cidn = L(cr_, "noise_id")[..., 0]
same = np.ones_like(cv, bool)[1:-1, 1:-1]
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        same &= cidn[1 + dy:127 + dy, 1 + dx:127 + dx] == cidn[1:-1, 1:-1]
d2x = cv[1:-1, 2:] - 2 * cv[1:-1, 1:-1] + cv[1:-1, :-2]
d2y = cv[2:, 1:-1] - 2 * cv[1:-1, 1:-1] + cv[:-2, 1:-1]
check("crystal: flat within a cell (second difference = 0, float32 storage 1e-5)",
      np.abs(d2x[same]).max() < 1e-5 and np.abs(d2y[same]).max() < 1e-5,
      (np.abs(d2x[same]).max(), np.abs(d2y[same]).max()))
d2n = cv[1:-1, 2:] - 2 * cv[1:-1, 1:-1] + cv[1:-1, :-2]
check("  negative control: second difference is nonzero across cells (creases)", np.abs(d2n[~same]).max() > 1e-3)
check("  _edge ≥ 0", L(cr_, "noise_edge").min() >= 0)

ph = N("phasor", 128, 128, frequency=4, stripe_freq=3, spread=0, angle=0)
pv = L(ph, "noise")[..., 0]
check("phasor:0~1", pv.min() >= 0 and pv.max() <= 1)
spec = np.abs(np.fft.rfft(pv - pv.mean(), axis=1)).mean(0)
kpk = int(np.argmax(spec))
check("  angle 0: main frequency along x = Frequency × Stripe = 12 (±1)",
      abs(kpk - 12) <= 1, kpk)
check("  consistent contrast: more than half the pixels below 0.1 or above 0.9",
      ((pv < 0.1) | (pv > 0.9)).mean() > 0.4,
      ((pv < 0.1) | (pv > 0.9)).mean())
dfld = np.zeros((128, 128, 2)); dfld[..., 1] = 1.0
phd = NX.noise_extra(CopImage(128, 128, {"dir": dfld}), "phasor", 4,
                     stripe_freq=3, direction_layer="dir")
pvd = L(phd, "noise")[..., 0]
spy = np.abs(np.fft.rfft(pvd - pvd.mean(), axis=0)).mean(1)
check("  Direction Layer = +v: stripes run along y instead", abs(int(np.argmax(spy)) - 12)
      <= 1, int(np.argmax(spy)))

f = 3.0
Wc = 128
cu = N("curl", Wc, Wc, frequency=f, octaves=2)
vel = L(cu, "noise")
psi = L(cu, "noise_potential")[..., 0]
hstep = f / Wc                               # how far one pixel moves in noise space
dpy = (psi[2:, 1:-1] - psi[:-2, 1:-1]) / (2 * hstep)
dpx = (psi[1:-1, 2:] - psi[1:-1, :-2]) / (2 * hstep)
ref = np.abs(vel).mean()
check("curl 2D: v = (∂ψ/∂y, −∂ψ/∂x) (vs differences of _potential, ±3%)",
      np.abs(vel[1:-1, 1:-1, 0] - dpy).mean() < 0.03 * ref and
      np.abs(vel[1:-1, 1:-1, 1] + dpx).mean() < 0.03 * ref)
div = ((vel[1:-1, 2:, 0] - vel[1:-1, :-2, 0]) + (vel[2:, 1:-1, 1]
                                                 - vel[:-2, 1:-1, 1])) \
    / (2 * hstep)
grad = np.abs((vel[1:-1, 2:, 0] - vel[1:-1, :-2, 0]) / (2 * hstep)).mean()
check("  divergence ≈ 0 (< 3% relative to the magnitude of the component derivatives)",
      np.abs(div).mean() < 0.03 * grad, (np.abs(div).mean(), grad))
dz = 0.01
c0 = L(N("curl_3d", Wc, Wc, frequency=f, octaves=1, offset=f"0 0 {-dz}"),
       "noise")
c1 = L(N("curl_3d", Wc, Wc, frequency=f, octaves=1, offset="0 0 0"),
       "noise")
c2 = L(N("curl_3d", Wc, Wc, frequency=f, octaves=1, offset=f"0 0 {dz}"),
       "noise")
div3 = ((c1[1:-1, 2:, 0] - c1[1:-1, :-2, 0]) / (2 * hstep)
        + (c1[2:, 1:-1, 1] - c1[:-2, 1:-1, 1]) / (2 * hstep)
        + (c2[1:-1, 1:-1, 2] - c0[1:-1, 1:-1, 2]) / (2 * dz))
g3 = np.abs((c1[1:-1, 2:, 0] - c1[1:-1, :-2, 0]) / (2 * hstep)).mean()
check("curl 3D: 3D divergence ≈ 0 (< 5%)", np.abs(div3).mean() < 0.05 * g3,
      (np.abs(div3).mean(), g3))
d2 = ((c1[1:-1, 2:, 0] - c1[1:-1, :-2, 0]) + (c1[2:, 1:-1, 1]
                                              - c1[:-2, 1:-1, 1])) / (2 * hstep)
check("  negative control: looking only at (vx, vy) on the slice is **not** divergence-free",
      np.abs(d2).mean() > 0.2 * g3)

cov = [L(N("cloud", coverage=cv_), "noise").mean() for cv_ in
       (0.0, 0.25, 0.5, 0.75, 1.0)]
check("cloud: coverage 0 all empty, 1 all full, monotonic in between",
      cov[0] == 0 and cov[-1] == 1 and all(np.diff(cov) > 0), cov)
check("  billow satisfies both ends too", L(N("cloud", coverage=0.0, billow=True),
                            "noise").max() == 0 and
      L(N("cloud", coverage=1.0, billow=True), "noise").min() == 1)
err("mistyped kind raises", lambda: N("xyz"), "Kind")

# ═══════════════════════════════════════════════════════ Text
sec("Text")
tx = PT.text(None, "T", "", 48, "0.5 0.5", xres=128, yres=128)
tm = L(tx, "text")[..., 0]
ys, xs = np.nonzero(tm > 0.5)
check("text present, coverage 0~1", tm.max() > 0.9 and tm.min() >= 0)
check("  center alignment: bounding box center at (64, 64) ±3",
      abs((xs.min() + xs.max()) / 2 - 63.5) <= 3 and
      abs((ys.min() + ys.max()) / 2 - 63.5) <= 6,
      ((xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2))
rows_ = (tm > 0.5).sum(1)
top_bar = rows_[ys.max() - 3:ys.max() + 1].max()
bottom = rows_[ys.min():ys.min() + 4].max()
check("  the row-0-at-top screen convention is flipped to v up: the bar of T is at the high-v end",
      top_bar > 3 * bottom, (top_bar, bottom))
tl = L(PT.text(None, "T", "", 48, "0.1 0.5", align="left", xres=128,
               yres=128), "text")[..., 0]
xl = np.nonzero(tl > 0.5)[1].min()
check("  left alignment: the left edge of the text near x = 12.8 (±4)", abs(xl - 12.8) <= 4, xl)
t2 = L(PT.text(None, "T\nT", "", 48, xres=128, yres=160), "text")[..., 0]
check("  two lines are taller than one", np.ptp(np.nonzero(t2 > 0.5)[0]) >
      1.6 * np.ptp(ys))
comp = PT.text(CopImage(64, 64, {"C": np.zeros((64, 64, 3))}), "A", "", 40,
               color="1 0 0", composite_layer="C")
cc = L(comp, "C")
check("  Composite: red where the text is, unchanged elsewhere",
      cc[..., 0].max() > 0.9 and cc[..., 1].max() == 0)
err("  font not found raises", lambda: PT.text(None, "x", "no_such_font_zz"),
    "not found")

# ═══════════════════════════════════════════════════════ Scatter shapes
sec("Scatter shapes / geometry coordinates")
Wm = 128
g1 = Geometry.from_points(np.array([[0.0, 0.0, 0.0]]))
im, n = ST.scatter_shapes(None, shape="circle", size=0.25, size_random=0,
                          softness=1.0, geo=g1, xres=Wm, yres=Wm)
cv1 = L(im, "shapes")[..., 0]
r = 0.25 * Wm / 2
check("single circle stamp (geometry origin -> image center): area = πr² (±1%)",
      n == 1 and abs(cv1.sum() / (math.pi * r * r) - 1) < 0.01,
      cv1.sum() / (math.pi * r * r))
yy, xx = np.nonzero(cv1 > 0)
w_ = cv1[yy, xx]
check("  centroid at (63.5, 63.5)", abs((xx * w_).sum() / w_.sum() - 63.5) < 1e-6
      and abs((yy * w_).sum() / w_.sum() - 63.5) < 1e-6)
for shp, area in (("box", 4 * r * r), ("diamond", 2 * r * r),
                  ("ring", math.pi * r * r * (1 - 0.25)),
                  ("triangle", 3 * math.sqrt(3) / 4 * r * r)):
    im, _ = ST.scatter_shapes(None, shape=shp, size=0.25, size_random=0,
                              rotation_random=0, geo=g1, xres=Wm, yres=Wm)
    a_ = L(im, "shapes").sum()
    check(f"  {shp} area = analytic value (±2%)", abs(a_ / area - 1) < 0.02,
          a_ / area)
g1.set(POINT, "pscale", np.array([2.0], np.float32))
im, _ = ST.scatter_shapes(None, shape="circle", size=0.25, size_random=0,
                          geo=g1, xres=Wm, yres=Wm)
check("  pscale = 2: area ×4 (±1%)", abs(L(im, "shapes").sum()
                                     / cv1.sum() - 4) < 0.04)
ge = Geometry.from_points(np.array([[0.49, 0.0, 0.0]]))
im, _ = ST.scatter_shapes(None, shape="circle", size=0.25, size_random=0,
                          geo=ge, tile=True, xres=Wm, yres=Wm)
check("stamp touching the right edge tiled: wraps around from the left, area conserved",
      abs(L(im, "shapes").sum() / cv1.sum() - 1) < 0.01 and
      L(im, "shapes")[64, 5, 0] > 0)
im, _ = ST.scatter_shapes(None, shape="circle", size=0.25, size_random=0,
                          geo=ge, tile=False, xres=Wm, yres=Wm)
check("  negative control: with tile off only a bit over half remains", L(im, "shapes").sum()
      < 0.7 * cv1.sum())

p100 = ST._positions(128, 128, 100, 5, None, 0.0)
p101 = ST._positions(128, 128, 101, 5, None, 0.0)
check("Count 100 -> 101: the first 100 positions bit-identical", np.array_equal(p100,
                                                          p101[:100]))
pm = ST._positions(128, 128, 300, 5, None, 0.08)
dmin = min(np.hypot(*(pm[i] - pm[j])) for i in range(len(pm))
           for j in range(i))
check("Min Distance 0.08: every pairwise distance ≥ 0.08", dmin >= 0.08 - 1e-12, dmin)
dens = np.zeros((128, 128, 1)); dens[:, 64:] = 1
im, n = ST.scatter_shapes(CopImage(128, 128, {"d": dens}), 200, "circle",
                          0.02, density_layer="d", tile=False)
check("Density Layer: left half 0 -> no stamps in the left half",
      L(im, "shapes")[:, :60].max() == 0 and n > 20)
idl = L(im, "shapes_id")[..., 0]
check("  _id ≥ 1 where there are stamps, 0 elsewhere",
      np.all((idl > 0) == (L(im, "shapes")[..., 0] > 0)))

th = np.linspace(0, 1, 11)
gc = Geometry.from_points(np.stack([th * 0.8 - 0.4, 0 * th, 0 * th], -1))
gc.set_topology(np.arange(11, dtype=np.int32), np.array([0, 11], np.int32),
                np.array([False]))
uvs, ang, _ = ST.curve_samples(gc, 0.1, 128, 128, "xz",
                               ST.frame(None, 128, 128, "xz", "world", 1.0))
check("along a curve: length 0.8, spacing 0.1 -> 9 points, tangent angle 0°",
      len(uvs) == 9 and np.allclose(ang, 0) and
      np.allclose(np.diff(uvs[:, 0]), 0.1))

from comfyui_pcg.geo.cop import terrain as TR            # noqa: E402
hf = CopImage(40, 24, {"h": np.random.default_rng(1).random((24, 40, 1))})
mesh = TR.to_mesh(hf, "h", 1.0, 3.0, 1, True, False)
uvm = ST.to_uv(mesh.get(POINT, "P"), 40, 24, "xz", "world", 3.0)
check("geometry coordinate convention: HeightField to Mesh points through to_uv = their uv attribute",
      np.allclose(uvm, mesh.get(POINT, "uv"), atol=1e-6))
fr = ST.frame(mesh.get(POINT, "P"), 40, 24, "xz", "fit")
check("  fit keeps aspect: one unit maps to the same number of pixels in u and v",
      abs(fr[2] / 40 - fr[3] / 24) < 1e-12)
back = ST.from_uv(ST.to_uv(mesh.get(POINT, "P"), 40, 24, "xz", fr=fr), 40,
                  24, "xz", fr, mesh.get(POINT, "P")[:, 1])
check("  fit: to_uv -> from_uv round trip", np.allclose(back, mesh.get(POINT, "P"),
                                            atol=1e-5))
uvf = ST.to_uv(mesh.get(POINT, "P"), 40, 24, "xz", fr=fr)
check("  fit: everything lands inside the image", uvf.min() > 0 and uvf.max() < 1)

stp = np.zeros((32, 32, 4)); stp[8:24, 8:24] = [0.3, 0.2, 0.9, 1]
im, _ = ST.scatter_shapes(None, shape="layer", size=0.5, size_random=0,
                          rotation_random=0, stamp=CopImage(32, 32,
                                                            {"C": stp}),
                          geo=Geometry.from_points(np.zeros((1, 3))),
                          xres=64, yres=64)
check("Shape = layer: the stamp image's alpha as shape, RGB as colour (area ≈ 16², ±5%)",
      abs(L(im, "shapes").sum() / 256 - 1) < 0.05 and
      np.allclose(L(im, "shapes_color")[32, 32], [0.3, 0.2, 0.9], atol=1e-6))
err("layer without Stamp connected raises", lambda: ST.scatter_shapes(None, shape="layer"),
    "Stamp")

# ═══════════════════════════════════════════════════════ Stereogram
sec("Autostereogram")
Ws, Hs = 160, 48
yy, xx = np.mgrid[0:Hs, 0:Ws]
dep = np.clip(1 - np.hypot(xx - 90, yy - 24) / 30, 0, 1)[..., None]
sg = ST.stereogram(CopImage(Ws, Hs, {"depth": dep}), "depth", strip=24,
                   seed=2)
o = L(sg, "stereogram")
sp = L(sg, "stereogram_sep")[..., 0].astype(int)
okc = True
for x in range(Ws):
    s_ = sp[:, x]
    m_ = x - s_ >= 0
    if m_.any():
        okc &= np.array_equal(o[np.arange(Hs)[m_], x],
                              o[np.arange(Hs)[m_], x - s_[m_]])
check("every pixel = the pixel s to its left (constraint holds)", okc)
smin, smax = sp.min(), sp.max()
nmatch = np.zeros_like(sp)
truth_hit = True
for x in range(smax, Ws):
    for p_ in range(smin, smax + 1):
        hit = np.all(o[:, x] == o[:, x - p_], -1)
        nmatch[:, x] += hit
        truth_hit &= bool(np.all(hit[sp[:, x] == p_]))
uniq = (nmatch[:, smax:] == 1).mean()
check("solved back from the image: equal at the true separation; for over 90% of pixels it's the only equal separation"
      " (the rest are where two copy chains merge onto the same source pixel at depth changes -- an echo inherent to single-image stereograms)",
      truth_hit and uniq > 0.9, (smin, smax, uniq))
flat_o = L(ST.stereogram(CopImage(Ws, Hs, {"depth": np.full((Hs, Ws, 1),
                                                            0.5)}),
                         "depth", strip=24, seed=2), "stereogram")
s5 = int(np.rint(2 * 24 * (1 - 0.33 * 0.5) / (2 - 0.33 * 0.5)))
um = sum(int(np.all(flat_o[:, 40:] == flat_o[:, 40 - p_:Ws - p_]))
         for p_ in range(15, 30))
check("  constant depth 0.5: the only period is s(0.5)", um == 1 and np.all(
    flat_o[:, 40:] == flat_o[:, 40 - s5:Ws - s5]), (um, s5))
check("  smaller separation up close (parallel viewing)", sp[24, 90] < sp[24, 10])
flat = ST.stereogram(CopImage(64, 8, {"depth": np.zeros((8, 64, 1))}),
                     "depth", strip=16)
fo = L(flat, "stereogram")
check("flat depth: the pattern repeats with the Strip period", np.array_equal(fo[:, 16:],
                                                  fo[:, :-16]))
cx_ = ST.stereogram(CopImage(Ws, Hs, {"depth": dep}), "depth", strip=24,
                    cross_eyed=True)
check("cross eyed: depth reversed (separation larger up close)",
      L(cx_, "stereogram_sep")[24, 90, 0] > L(cx_, "stereogram_sep")[24, 10, 0])

# ═══════════════════════════════════════════════════════ torch / nodes
sec("torch / nodes")
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
if BK.get("cpu") is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    ti = CopImage(64, 64, {"C": np.zeros((64, 64, 3), np.float32)}) \
        .to_device("cpu")
    for fn in (lambda z: PT.pattern(z, "cell", counts="4 4"),
               lambda z: NX.noise_extra(z, "bubble"),
               lambda z: ST.scatter_shapes(z, 20)[0]):
        o = fn(ti)
        ref = fn(CopImage(64, 64, {"C": np.zeros((64, 64, 3), np.float32)}))
        nm = [n for n in o.names if n != "C"][0]
        check(f"[torch] layers added on a torch image stay on torch, match numpy ({nm})",
              o.backend.is_torch and np.allclose(L(o, nm), L(ref, nm),
                                                 atol=1e-5))
C_ = ["PCG_COPPattern", "PCG_COPNoiseExtra", "PCG_COPText",
      "PCG_COPScatterShapes", "PCG_COPStereogram"]
check(f"all {len(C_)} batch C nodes registered, all under PCG/cop",
      all(k in MAP and MAP[k].CATEGORY == "PCG/cop" for k in C_))
bad = [k for k in C_ for nm in MAP[k].INPUT_TYPES()["required"]
       if nm == "seed"]
check("  no widget named seed", not bad, bad)
r = MAP["PCG_COPScatterShapes"]().run(
    10, "circle", 0.05, 0.5, 1.0, 0.0, 180.0, 1.0, "", 0.0, "max", True, 0,
    "C", "xz", "world", 1.0, 0.0, True, "shapes", 64, 64)
r = tuple(r["result"]) if isinstance(r, dict) else r
check("  Scatter Shapes' second output is INT", isinstance(r[1], int) and r[1] == 10)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
