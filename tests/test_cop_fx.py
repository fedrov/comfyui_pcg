"""
Complete Copernicus batch B: filters / effects / distortion (the 24 nodes of fx.py + nodes_cop2.py).

━━ Criteria (everything that can be written in closed form is)
  · Convolution: the shift-and-add and FFT paths agree per pixel; identity kernel is bit-exact; with clamp borders a bright column
    on the right does not bleed in from the left (FFT is circular convolution, it would without padding); kernel orientation = as written
  · Shape kernels sum to 1 and are symmetric; depth of field leaves a constant image unchanged, all-in-focus is bit-exact identity, Highlight Gain
    restores a flat bright area exactly
  · Directional blur only moves along its direction (an image varying only in v blurred horizontally is unchanged); mean preserved under wrap
  · Kuwahara keeps step edges; TV denoise: ∇ and div strictly adjoint, mean preserved, constants untouched,
    noise reduced, steps survive
  · Glow: an image below threshold is unchanged; drop shadow: offset position correct, foreground untouched, error without alpha
  · Feather: inward does not grow, outward does not shrink, both keeps a thin strip's center line > 0.5; pixelate = block mean
  · Distortions are all verified with a **coordinate image** (the layer value is the pixel coordinate -- bilinear is exact on a linear field,
    so the output value is the input position it looked up): swirl angle = θ·(1 − r/R)², unchanged outside the radius;
    lens distort lookup points satisfy f(r_u) = r_d; corner pin sends the four corners to the given positions,
    straight lines stay straight; constant lattice displacement = translation; mirror is symmetric
  · Derivatives: dx / dy of a slope are constant, Laplacian of x²+y² = 4, div(x, y) = 2,
    divergence of a curl = 0, curl of (−y, x) = 2
  · Corners: a white square gives exactly 4 corners, all at the corners; a half-plane (edge only) gives 0
  · Fill holes: known pixels bit-exact untouched; laplace fill of a linear function = the linear function; nearest extrapolates
  · Flood fill: selects only the seed's piece; 4- vs 8-connectivity differ where pieces touch diagonally
  · Contours: h and 3h (spacing also ×3) are identical per pixel -- line width is in pixels, independent of slope
  · Dither: only Levels values come out; bayer4 on a constant 0.3 gives exactly 5/16 ones; FS preserves the mean
  · Planar inflate: poisson solution on a disc = 1 − (r/R)² (analytic); round peaks at Height
  · Copy transform: 1 copy = identity; add + translate 0 = n times; fade is a geometric series
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
from comfyui_pcg.geo.cop import fx as FX                 # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX              # noqa: E402
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
        check(name, False, "did not raise")
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


def coord(W, H):
    """Coordinate image: the P layer value is the pixel coordinate (j, i)."""
    J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                       np.arange(H, dtype=np.float64))
    return np.stack([J, I], -1), J, I


def inner(a, m=3):
    return a[m:-m, m:-m]


rng = np.random.default_rng(5)
H, W = 40, 48
noise = rng.random((H, W, 3))

# ═══════════════════════════════════════════════════════ Convolution basics
sec("Convolution basics")
k9 = rng.random((9, 9))
a = rng.random((30, 34, 2))
direct = np.zeros_like(a)
p = FX.pad(a, 4, "clamp")
for i in range(9):
    for j in range(9):
        direct += k9[i, j] * p[i:i + 30, j:j + 34]
check("9×9 kernel goes through FFT, matches shift-and-add (1e-10)",
      np.abs(FX.convolve(a, k9, "clamp") - direct).max() < 1e-10,
      np.abs(FX.convolve(a, k9, "clamp") - direct).max())
k7 = rng.random((7, 7))
d7 = np.zeros_like(a)
p7 = FX.pad(a, 3, "wrap")
for i in range(7):
    for j in range(7):
        d7 += k7[i, j] * p7[i:i + 30, j:j + 34]
check("7×7 kernel goes through shift-and-add, wrap border matches hand computation",
      np.abs(FX.convolve(a, k7, "wrap") - d7).max() < 1e-12)
one = np.zeros((3, 3)); one[1, 1] = 1
check("identity kernel is bit-exact identity", np.array_equal(FX.convolve(a, one), a))
col = np.zeros((20, 20, 1)); col[:, -1] = 1.0
big = np.ones((11, 11)) / 121
r = FX.convolve(col, big, "clamp")
check("clamp + FFT: a bright column on the right does not bleed in from the left (circular convolution pitfall)",
      np.abs(r[:, :5]).max() < 1e-12, np.abs(r[:, :5]).max())
r = FX.convolve(col, big, "wrap")
check("  negative control: with wrap it should bleed over", r[:, 0].min() > 0.05)
for sh in FX.BLUR_SHAPES:
    ks = FX.kernel_shape(5.3, sh, 6, 0)
    check(f"shape kernel {sh}: sums to 1, symmetric up/down/left/right",
          abs(ks.sum() - 1) < 1e-12 and np.allclose(ks, ks[::-1])
          and np.allclose(ks, ks[:, ::-1]))
check("radius < 0.5 is a unit impulse", FX.kernel_shape(0.3).shape == (1, 1))
kd = FX.kernel_shape(8, "disc")
area = kd.sum() / kd.max()            # interior pixel coverage is 1, so total coverage is the area
check("disc kernel coverage area = πR² (supersampled, ±1%)",
      abs(area - math.pi * 64) / (math.pi * 64) < 0.01, area)
kh = FX.kernel_shape(8, "hexagon", 6)
ah = kh.sum() / kh.max()
check("  hexagonal aperture area = (3√3/2)·R² (circumradius R, ±1.5%)",
      abs(ah - 1.5 * math.sqrt(3) * 64) / (1.5 * math.sqrt(3) * 64) < 0.015,
      ah)

# orientation: the first row written is the top
ramp = mk(C=np.repeat(np.arange(H, dtype=np.float64)[:, None, None], W, 1))
r = L(FX.convolve_layer(ramp, "C", kernel="0 1 0 0 0 0 0 0 0"), "C")
check("the weight written in the Kernel's first row takes the cell **above** (larger v): out(i) = in(i+1)",
      np.allclose(inner(r)[..., 0], inner(L(ramp, "C"))[..., 0] + 1))
rx = mk(C=np.repeat(np.arange(W, dtype=np.float64)[None, :, None] * 0.5, H, 0))
r = L(FX.convolve_layer(rx, "C", preset="sobel_x"), "C")
check("sobel_x on a slope of 0.5 = 8 × 0.5", np.allclose(inner(r), 4.0))
r = L(FX.convolve_layer(noise_img := mk(C=noise), "C", preset="gaussian3",
                        normalize=True), "C")
check("normalized kernel preserves the mean (clamp outside wrap, only the smooth interior is checked)",
      abs(inner(r).mean() - inner(noise).mean()) < 0.01)
err("kernel count not an odd square raises",
    lambda: FX.convolve_layer(noise_img, "C", kernel="1 2 3 4"), "n²")

# ═══════════════════════════════════════════════════════ Depth of field / blur
sec("Depth of field / directional blur / Kuwahara")
const = mk(C=np.full((H, W, 3), 0.37))
r = L(FX.defocus(const, "C", radius=7), "C")
check("depth of field: constant image unchanged (clamp)", np.abs(r - 0.37).max() < 1e-12)
wrapm = L(FX.defocus(noise_img, "C", radius=6, border="wrap"), "C")
check("depth of field wrap: mean preserved", abs(wrapm.mean() - noise.mean()) < 1e-10)
check("  and it really blurred (variance drops)", wrapm.var() < noise.var() * 0.3)
dep = mk(C=noise, depth=np.full((H, W, 1), 0.5))
r = L(FX.defocus(dep, "C", radius=9, depth_layer="depth", focus=0.5), "C")
check("all in focus (CoC = 0) → bit-exact identity", np.array_equal(r, noise))
dd = np.zeros((H, W, 1)); dd[:, W // 2:] = 1.0
r = L(FX.defocus(mk(C=noise, depth=dd), "C", radius=6, depth_layer="depth",
                 focus=0.0, focus_range=0.1, falloff=0.2), "C")
check("left half in focus (bit-exact), right half blurred",
      np.array_equal(r[:, :W // 2 - 8], noise[:, :W // 2 - 8])
      and r[:, W // 2 + 8:].var() < noise[:, W // 2 + 8:].var() * 0.5)
# CoC: |d − f| = range + falloff/2 → half the radius. With Levels 3 the steps are 0 / R/2 / R,
# it lands exactly on the middle step, so it matches "no depth input, R/2 directly" per pixel
r = L(FX.defocus(mk(C=noise, depth=np.full((H, W, 1), 0.2)), "C", radius=8,
                 depth_layer="depth", focus=0.0, focus_range=0.1,
                 falloff=0.2, levels=3), "C")
r2 = L(FX.defocus(noise_img, "C", radius=4), "C")
check("CoC = (|d − f| − range) / falloff × R: lands on the R/2 step",
      np.abs(r - r2).max() < 1e-12, np.abs(r - r2).max())
hot = mk(C=np.full((H, W, 3), 2.0))
r = L(FX.defocus(hot, "C", radius=5, highlight_threshold=1.0,
                 highlight_gain=3.0), "C")
check("Highlight Gain: a flat bright area goes through boost → blur → inverse map and returns exactly to its value",
      np.abs(r - 2.0).max() < 1e-9, np.abs(r - 2.0).max())
spot = np.zeros((H, W, 3)); spot[20, 24] = 5.0
g0 = L(FX.defocus(mk(C=spot), "C", radius=5), "C")
g3 = L(FX.defocus(mk(C=spot), "C", radius=5, highlight_gain=3.0,
                  highlight_threshold=0.01), "C")
check("  bright spots are brighter with Gain (bokeh aperture is clear)", g3.max() > g0.max() * 1.2,
      (g0.max(), g3.max()))

vonly = mk(C=np.repeat(rng.random((H, 1, 3)), W, 1))
r = L(FX.directional_blur(vonly, "C", length=15, angle=0), "C")
check("directional blur angle = 0: an image varying only in v blurred horizontally is unchanged",
      np.abs(r - L(vonly, "C")).max() < 1e-12)
r = L(FX.directional_blur(vonly, "C", length=15, angle=90), "C")
check("  negative control: angle = 90 changes it", np.abs(r - L(vonly, "C")).max() > 0.05)
r = L(FX.directional_blur(noise_img, "C", length=9, angle=30,
                          border="wrap"), "C")
check("  mean preserved under wrap (1e-3, bilinear)", abs(r.mean() - noise.mean()) < 1e-3)
dot = np.zeros((H, W, 1)); dot[20, 10] = 1
r = L(FX.directional_blur(mk(C=dot), "C", length=10, angle=0,
                          mode="streak"), "C")[..., 0]
check("  streak only drags to one side (+u direction)", r[20, 12:21].min() > 0 and
      r[20, :9].max() == 0)

step = np.zeros((H, W, 1)); step[:, W // 2:] = 1
st_n = step + rng.normal(0, 0.08, step.shape)
r = L(FX.kuwahara(mk(C=st_n), "C", 3), "C")[..., 0]
check("Kuwahara keeps edges: the difference across the step is still ≈ 1",
      r[:, W // 2 + 1].mean() - r[:, W // 2 - 2].mean() > 0.85)
check("  and noise dropped", r[:, 5:W // 2 - 5].std() < st_n[:, 5:W // 2 - 5, 0]
      .std() * 0.6)
r = L(FX.kuwahara(const, "C", 4), "C")
check("  constant image unchanged", np.abs(r - 0.37).max() < 1e-12)

# ═══════════════════════════════════════════════════════ TV denoise
sec("TV denoise")
u_ = rng.random((13, 17))
px_, py_ = rng.random((13, 17)), rng.random((13, 17))
gx_, gy_ = FX._grad(u_)
lhs = (gx_ * px_ + gy_ * py_).sum()
rhs = -(u_ * FX._div(px_, py_)).sum()
check("⟨∇u, p⟩ = −⟨u, div p⟩ (strictly adjoint, the precondition for Chambolle convergence)",
      abs(lhs - rhs) < 1e-10, (lhs, rhs))
r = L(FX.denoise_tv(mk(C=st_n), "C", 0.15, 100), "C")[..., 0]
check("mean preserved", abs(r.mean() - st_n.mean()) < 1e-10)
check("noise reduced (flat-area std below 1/3)",
      r[:, 3:W // 2 - 3].std() < st_n[:, 3:W // 2 - 3, 0].std() / 3,
      (r[:, 3:W // 2 - 3].std(), st_n[:, 3:W // 2 - 3, 0].std()))
check("step survives (jump across the edge > 0.7)",
      r[:, W // 2].mean() - r[:, W // 2 - 1].mean() > 0.7)
check("constant image unchanged", np.abs(L(FX.denoise_tv(const, "C", 0.2, 30), "C")
                       - 0.37).max() < 1e-12)
check("weight 0 = identity", np.array_equal(
    L(FX.denoise_tv(noise_img, "C", 0.0), "C"), noise))
err("negative weight raises", lambda: FX.denoise_tv(noise_img, "C", -1), "negative")

# ═══════════════════════════════════════════════════════ Glow / drop shadow / feather / pixelate
sec("Glow / drop shadow / feather / pixelate")
dim = np.concatenate([noise * 0.5, rng.random((H, W, 1))], -1)
r = L(FX.glow(mk(C=dim), "C", threshold=0.8), "C")
check("glow: all below threshold → unchanged", np.array_equal(r, dim))
br = dim.copy(); br[20, 24, :3] = 4.0
for m in ("glow", "star"):
    r = L(FX.glow(mk(C=br), "C", mode=m, threshold=0.8), "C")
    check(f"  {m}: brighter around the bright point, alpha untouched",
          r[20, 28, 0] > br[20, 28, 0] + 1e-3 and
          np.array_equal(r[..., 3], br[..., 3]))

al = np.zeros((H, W, 1)); al[10:20, 10:20] = 1
rgba = np.concatenate([np.full((H, W, 3), 0.8), al], -1)
r = L(FX.drop_shadow(mk(C=rgba), "C", offset="6 -4", blur=0, color="0 0 1",
                     opacity=1.0), "C")
check("drop shadow: foreground pixel color / alpha untouched", np.allclose(r[12, 12], [0.8, 0.8,
                                                             0.8, 1]))
check("  shadow at (+6, −4), with the given color", np.allclose(r[8, 24], [0, 0, 1, 1]),
      r[8, 24])
check("  outside the shadow is still transparent", r[30, 40, 3] == 0)
err("  raises without alpha", lambda: FX.drop_shadow(noise_img, "C"), "alpha")

m = np.zeros((H, W, 1)); m[8:32, 10:38] = 1
line2 = np.zeros((H, W, 1)); line2[:, 20:22] = 1
fi = mk(mask=m, line=line2)
r_in = L(FX.feather(fi, "mask", 6, "inward"), "mask")[..., 0]
r_out = L(FX.feather(fi, "mask", 6, "outward"), "mask")[..., 0]
r_b = L(FX.feather(fi, "mask", 6, "both"), "mask")[..., 0]
mb = m[..., 0] > 0.5
check("feather inward does not grow (all 0 outside the mask)", r_in[~mb].max() == 0)
check("  outward does not shrink (all 1 inside the mask)", r_out[mb].min() == 1)
check("  both: 1 deep inside, 0 far away, monotonic in between",
      r_b[20, 24] == 1 and r_b[0, 0] == 0 and
      np.all(np.diff(r_b[20, :24]) >= -1e-12))
rl = L(FX.feather(fi, "line", 8, "both"), "line")[..., 0]
check("  with both, the center line of a 2-pixel strip is still > 0.5 (a Gaussian blur would drop to 0.2)",
      rl[:, 20:22].min() > 0.5, rl[:, 20:22].min())

pv = rng.random((32, 48, 2))
r = L(FX.pixelate(mk(C=pv), "C", 8), "C")
blk = pv.reshape(4, 8, 6, 8, 2).mean((1, 3))
check("pixelate average: each block = that block's mean, image mean unchanged",
      np.allclose(r[::8, ::8], blk) and abs(r.mean() - pv.mean()) < 1e-12)
check("  constant within a block", np.all(r.reshape(4, 8, 6, 8, 2).std((1, 3)) < 1e-12))
r = L(FX.pixelate(mk(C=pv), "C", 8, "sample"), "C")
check("  sample: takes the block's center pixel", np.allclose(r[0, 0], pv[4, 4]))

# ═══════════════════════════════════════════════════════ Distortion (coordinate image)
sec("Distortion (coordinate image: value = input position looked up)")
P, J, I = coord(W, H)
ci = mk(P=P)
for fn, kw in ((FX.swirl, dict(amount=0.0)), (FX.swirl, dict(mode="pinch",
               amount=0.0)), (FX.swirl, dict(mode="bend", amount=0.0)),
               (FX.lattice_deform, {}), (FX.corner_pin, {}),
               (FX.heat_distort, dict(amount=0.0)),
               (FX.lens_distort, dict(k1=0.0, k2=0.0))):
    r = L(fn(ci, "P", **kw), "P")
    check(f"{fn.__name__} {kw} is identity (1e-9)", np.abs(r - P).max() < 1e-9,
          np.abs(r - P).max())

Rr, amt = 0.35, 120.0
r = L(FX.swirl(ci, "P", amount=amt, radius=Rr), "P")
asp = W / H
x = ((J + 0.5) / W - 0.5) * asp
y = (I + 0.5) / H - 0.5
rad = np.hypot(x, y)
sx = (r[..., 0] + 0.5) / W
sy = (r[..., 1] + 0.5) / H
xs, ys = (sx - 0.5) * asp, sy - 0.5
ang = np.angle(np.exp(1j * (np.arctan2(y, x) - np.arctan2(ys, xs))))
exp_ = math.radians(amt) * np.clip(1 - rad / Rr, 0, 1) ** 2
sel = (rad > 0.02) & (rad < Rr)
check("swirl: lookup point rotated θ·(1 − r/R)² relative to the output point (counterclockwise = positive)",
      np.abs(ang[sel] - exp_[sel]).max() < 1e-9)
check("  lookup point radius unchanged", np.abs(np.hypot(xs, ys) - rad).max() < 1e-9)
check("  unchanged outside the radius", np.abs(r[rad >= Rr] - P[rad >= Rr]).max() < 1e-9)
for mode, sgn in (("pinch", 1), ("bulge", -1)):
    r = L(FX.swirl(ci, "P", mode=mode, amount=0.8, radius=0.4), "P")
    xs = ((r[..., 0] + 0.5) / W - 0.5) * asp
    ys = (r[..., 1] + 0.5) / H - 0.5
    rs = np.hypot(xs, ys)
    s2 = (rad > 0.03) & (rad < 0.37)
    check(f"  {mode}: lookup radius {'>' if sgn > 0 else '<'} output radius, and monotonic",
          np.all((rs[s2] - rad[s2]) * sgn > 0))

k1, k2 = -0.2, 0.05
r = L(FX.lens_distort(ci, "P", k1, k2, "distort", border="clamp"), "P")
norm = math.hypot(W, H) / 2
rd = np.hypot(J + 0.5 - W / 2, I + 0.5 - H / 2) / norm
ru = np.hypot(r[..., 0] + 0.5 - W / 2, r[..., 1] + 0.5 - H / 2) / norm
fr = ru * (1 + k1 * ru ** 2 + k2 * ru ** 4)
inb = (r[..., 0] > 0.5) & (r[..., 0] < W - 1.5) & (r[..., 1] > 0.5) & \
    (r[..., 1] < H - 1.5)      # clamped to the edge (value ≈ W−1 off by one ulp) does not count
check("lens distort: lookup radius satisfies f(r_u) = r_d (Newton solve is right)",
      np.abs(fr - rd)[inb].max() < 1e-9, np.abs(fr - rd)[inb].max())
r = L(FX.lens_distort(ci, "P", k1, k2, "undistort", border="clamp"), "P")
ru2 = np.hypot(J + 0.5 - W / 2, I + 0.5 - H / 2) / norm
rd2 = np.hypot(r[..., 0] + 0.5 - W / 2, r[..., 1] + 0.5 - H / 2) / norm
inb = (r[..., 0] > 0.5) & (r[..., 0] < W - 1.5) & (r[..., 1] > 0.5) & \
    (r[..., 1] < H - 1.5)      # clamped to the edge (value ≈ W−1 off by one ulp) does not count
check("  undistort: lookup radius = f(r_u)",
      np.abs(rd2 - ru2 * (1 + k1 * ru2 ** 2 + k2 * ru2 ** 4))[inb].max()
      < 1e-9)
r = L(FX.lens_distort(mk(C=np.full((H, W, 1), 0.5)), "C", -0.35, 0,
                      "distort", border="black"), "C")[..., 0]
rdd = np.hypot(J + 0.5 - W / 2, I + 0.5 - H / 2) / norm
rmax = (1 / math.sqrt(1.05)) * (1 - 0.35 / 1.05)      # vertex of f
check("  strong barrel: corners with no preimage (r_d > max f) are black borders, not snow",
      np.all(r[rdd > rmax + 0.02] == 0) and
      np.abs(r[rdd < 0.45] - 0.5).max() < 1e-12,
      (rmax, np.unique(np.round(r, 3))[:6]))
sm = mk(C=np.sin(J / 5.0)[..., None] * np.cos(I / 7.0)[..., None])
rt = L(FX.lens_distort(FX.lens_distort(sm, "C", -0.1, 0, "distort"), "C",
                       -0.1, 0, "undistort"), "C")
check("  distort → undistort round trip (smooth image, interior 2e-2)",
      np.abs(inner(rt, 8) - inner(L(sm, "C"), 8)).max() < 2e-2,
      np.abs(inner(rt, 8) - inner(L(sm, "C"), 8)).max())

dst = np.array([[0.1, 0.05], [0.95, 0.2], [0.8, 0.9], [0.15, 0.7]])
cp = FX.corner_pin(ci, "P", corners=" ".join(map(str, dst.ravel())),
                   border="clamp")
Hm = FX.homography(np.array([[0, 0], [1, 0], [1, 1], [0, 1.0]]), dst)
for (u0, v0), (u1, v1) in zip([[0, 0], [1, 0], [1, 1], [0, 1.0]], dst):
    q = Hm @ [u0, v0, 1]
    ok = abs(q[0] / q[2] - u1) < 1e-9 and abs(q[1] / q[2] - v1) < 1e-9
    if not ok:
        break
check("homography sends the four source corners to the four target corners", ok)
r = L(cp, "P")
Hi = np.linalg.inv(Hm)
u, v = (J + 0.5) / W, (I + 0.5) / H
q = np.einsum("ij,jhw->ihw", Hi, np.stack([u, v, np.ones_like(u)]))
eu, ev = q[0] / q[2], q[1] / q[2]
inside = (eu > 0.02) & (eu < 0.98) & (ev > 0.02) & (ev < 0.98)
check("corner pin: every output pixel looks up H⁻¹(uv)",
      np.abs((r[..., 0] + 0.5) / W - eu)[inside].max() < 1e-9 and
      np.abs((r[..., 1] + 0.5) / H - ev)[inside].max() < 1e-9)
r = L(FX.corner_pin(ci, "P", mode="rotate_3d", rotate="0 0 0",
                    border="clamp"), "P")
check("rotate_3d at 0° with distance = focal length → identity", np.abs(r - P).max() < 1e-9)
r = L(FX.corner_pin(ci, "P", mode="rotate_3d", rotate="0 0 90",
                    border="clamp"), "P")
ox, oy = J - (W / 2 - 0.5), I - (H / 2 - 0.5)      # pixel offset from the image center
sxo, syo = r[..., 0] - (W / 2 - 0.5), r[..., 1] - (H / 2 - 0.5)
ins = (np.abs(oy) < W / 2 - 2) & (np.abs(ox) < H / 2 - 2)
check("  rotate_3d 90° about z: lookup offset = (oy, −ox) (content rotates counterclockwise; in pixels"
      " it is a pure rotation because aspect goes into the homography)",
      np.abs(sxo - oy)[ins].max() < 1e-9 and
      np.abs(syo + ox)[ins].max() < 1e-9)
err("  rotating behind the camera raises", lambda: FX.corner_pin(
    ci, "P", mode="rotate_3d", rotate="100 0 0", distance=0.3), "behind the camera")

r = L(FX.lattice_deform(ci, "P", "3 2", " ".join(["0.1 0"] * 12),
                        border="clamp"), "P")
check("lattice: all control points with the same displacement = translation (lookup u − 0.1)",
      np.abs(r[:, 8:, 0] - (J[:, 8:] - 0.1 * W)).max() < 1e-9)

r = L(FX.mirror(ci, "P", "left_to_right"), "P")
check("mirror left_to_right: left half untouched, right half = mirror of the left half (bit-exact)",
      np.array_equal(r[:, :W // 2], P[:, :W // 2]) and
      np.array_equal(r[:, ::-1, 0][:, :W // 2], P[:, :W // 2, 0]))
r = L(FX.mirror(ci, "P", "quad"), "P")
check("  quad: four-way symmetric", np.array_equal(r[::-1, :, 1], r[..., 1]) and
      np.array_equal(r[:, ::-1, 0], r[..., 0]))

r1 = L(FX.heat_distort(ci, "P", amount=3, time=0.0), "P")
r2 = L(FX.heat_distort(ci, "P", amount=3, time=0.0), "P")
r3 = L(FX.heat_distort(ci, "P", amount=3, time=1.0), "P")
check("heat distortion: same parameters reproducible bit-for-bit, changing time changes it",
      np.array_equal(r1, r2) and np.abs(r1 - r3).max() > 0.1)
check("  displacement does not exceed Amount·max|noise| (simplex ≤ 1)",
      np.abs(inner(r1, 4) - inner(P, 4)).max() <= 3.0 + 1e-9)
fl = np.zeros((H, W, 1)); fl[:, :W // 2] = 1
r = L(FX.heat_distort(mk(P=P, f=fl), "P", amount=3, field_layer="f"), "P")
check("  no distortion where Field Layer = 0", np.array_equal(r[:, W // 2:],
                                                   P[:, W // 2:]))

ca = mk(C=noise)
r = L(FX.chromatic_aberration(ca, "C", 0.03), "C")
check("chromatic aberration: G bit-exact untouched", np.array_equal(r[..., 1], noise[..., 1]))
check("  R / B changed", np.abs(r[..., 0] - noise[..., 0]).max() > 0.05)
check("  amount 0 → identity (1e-9)",
      np.abs(L(FX.chromatic_aberration(ca, "C", 0.0), "C") - noise).max()
      < 1e-9)

# ═══════════════════════════════════════════════════════ Derivatives
sec("Derivatives")
lin = mk(h=(0.3 * J - 0.7 * I)[..., None])
check("slope dx = 0.3, dy = −0.7 (interior)",
      np.allclose(inner(L(FX.derivative(lin, "h", "dx"), "h_dx")), 0.3) and
      np.allclose(inner(L(FX.derivative(lin, "h", "dy"), "h_dy")), -0.7))
g = L(FX.derivative(lin, "h", "magnitude", scale=2), "h_magnitude")
check("  magnitude × scale", np.allclose(inner(g), 2 * math.hypot(0.3, 0.7)))
q2 = mk(h=(J ** 2 + I ** 2)[..., None])
check("Laplacian of x² + y² = 4",
      np.allclose(inner(L(FX.derivative(q2, "h", "laplacian"),
                          "h_laplacian")), 4.0))
vf = mk(v=np.stack([J, I], -1))
check("div(x, y) = 2", np.allclose(inner(L(FX.derivative(
    vf, "v", "divergence"), "v_divergence")), 2.0))
rot = mk(v=np.stack([-I, J], -1))
check("curl of (−y, x) = 2", np.allclose(inner(L(FX.derivative(
    rot, "v", "curl"), "v_curl")), 2.0))
f = mk(h=rng.random((H, W, 1)))
cv = FX.derivative(f, "h", "curl", out_layer="vel")
dv = L(FX.derivative(cv, "vel", "divergence"), "vel_divergence")
check("curl of a scalar field is divergence-free (interior, exact in the discrete sense)",
      np.abs(inner(dv, 3)).max() < 1e-12, np.abs(inner(dv, 3)).max())
err("divergence needs 2 channels", lambda: FX.derivative(f, "h", "divergence"),
    "2-channel")

# ═══════════════════════════════════════════════════════ Corners
sec("Corners")
sq = np.zeros((64, 64, 1)); sq[20:44, 16:40] = 1
out, n = FX.corner_detect(mk(C=sq), "C", sigma=1.5, radius=4)
ys_, xs_ = np.nonzero(L(out, "corners")[..., 0])
cs = [(20, 16), (20, 39), (43, 16), (43, 39)]
check("white square has exactly 4 corners", n == 4, n)
check("  each within 2 pixels of a true corner", n == 4 and all(
    min(math.hypot(y - cy, x - cx) for cy, cx in cs) <= 2.0
    for y, x in zip(ys_, xs_)), list(zip(ys_, xs_)))
hp = np.zeros((64, 64, 1)); hp[:, 32:] = 1
check("half-plane (straight edge only) has 0 corners", FX.corner_detect(mk(C=hp), "C")[1] == 0)

# ═══════════════════════════════════════════════════════ Fill holes / flood fill
sec("Fill holes / flood fill")
kn = np.ones((H, W, 1)); kn[8:32, 10:38] = 0
linv = (0.02 * J + 0.05 * I + 0.3)[..., None]
hole = np.where(kn > 0.5, linv, 7.0)
img_h = mk(C=hole, mask=kn)
for mode in FX.FILL_MODES:
    r = L(FX.smooth_fill(img_h, "C", "mask", mode, iterations=3000), "C")
    check(f"{mode}: known pixels bit-exact untouched",
          np.array_equal(r[kn[..., 0] > 0.5], hole[kn[..., 0] > 0.5]))
r = L(FX.smooth_fill(img_h, "C", "mask", "laplace", iterations=3000), "C")
check("laplace fill of a linear function = the linear function (harmonic)",
      np.abs(r - linv).max() < 2e-3, np.abs(r - linv).max())
r = L(FX.smooth_fill(img_h, "C", "mask", "pushpull"), "C")
check("pushpull fill values fall within the range of known values",
      r.min() >= linv.min() - 1e-9 and r.max() <= linv.max() + 1e-9)
half = np.zeros((H, W, 1)); half[:, :10] = 1
vals = np.where(half > 0.5, np.repeat(rng.random((H, 1, 1)), W, 1), 0.0)
r = L(FX.smooth_fill(mk(C=vals, mask=half), "C", "mask", "nearest"), "C")
check("nearest: each row pushes the nearest known value to the right",
      np.allclose(r[:, 25], vals[:, 9]))
err("no known pixels raises", lambda: FX.smooth_fill(
    mk(C=vals, mask=np.zeros((H, W, 1))), "C", "mask"), "no known pixels")

two = np.zeros((H, W, 1)); two[5:15, 5:15] = 1; two[20:30, 25:35] = 1
out, n = FX.flood_fill(mk(C=two), "C", seed_uv=f"{10 / W} {10 / H}",
                       tolerance=0.1)
mm = L(out, "fill_mask")[..., 0]
check("flood fill selects only the seed's piece (the other piece has the same value but is not connected)",
      n == 100 and mm[5:15, 5:15].all() and not mm[20:30, 25:35].any())
dg = np.zeros((10, 10, 1)); dg[0:5, 0:5] = 1; dg[5:10, 5:10] = 1
n4 = FX.flood_fill(mk(C=dg), "C", "0.1 0.1", connectivity=4)[1]
n8 = FX.flood_fill(mk(C=dg), "C", "0.1 0.1", connectivity=8)[1]
check("diagonal contact: 4-connected 25, 8-connected 50", (n4, n8) == (25, 50), (n4, n8))
sl = np.zeros((10, 10, 1)); sl[2, 2] = 1
n = FX.flood_fill(mk(C=dg, s=sl), "C", seed_layer="s", connectivity=4)[1]
check("Seed Layer as seed", n == 25)

# ═══════════════════════════════════════════════════════ Contours / dither / inflate / copy
sec("Contours / dither / inflate / copy transform")
hh = np.sin(J / 9.0) * np.cos(I / 6.0) + J / 40.0
c1 = L(FX.contour(mk(h=hh[..., None]), "h", 0.1, width=1.5), "contour")
c3 = L(FX.contour(mk(h=3 * hh[..., None]), "h", 0.3, width=1.5), "contour")
check("h with spacing 0.1 and 3h with spacing 0.3 are identical per pixel (line width in pixels, independent of slope)",
      np.abs(c1 - c3).max() < 1e-9, np.abs(c1 - c3).max())
rmp = mk(h=(J / W)[..., None])
cc = L(FX.contour(rmp, "h", 0.25, width=1.0), "contour")[0, :, 0]
peaks = [j for j in range(W) if cc[j] > 0.75]
check("slope h = j/W, spacing 0.25: lines land exactly on j = 0 / 12 / 24 / 36",
      peaks == [0, 12, 24, 36], peaks)
check("  line width 1: the two adjacent pixels get 0.5 each (the line sits exactly on pixel centers)",
      abs(cc[11] - 0.5) < 1e-9 and abs(cc[13] - 0.5) < 1e-9)

c03 = mk(C=np.full((32, 32, 1), 0.3))
r = L(FX.dither(c03, "C", "bayer4"), "C")
check("bayer4 on a constant 0.3: exactly 5/16 are 1", abs(r.mean() - 5 / 16) < 1e-12
      and set(np.unique(r)) <= {0.0, 1.0})
r = L(FX.dither(mk(C=noise[..., :1]), "C", "floyd_steinberg", 4), "C")
check("FS 4 levels: only {0, ⅓, ⅔, 1} come out", np.allclose(
    np.unique(np.round(r * 3)), np.unique(np.round(r * 3)).astype(int))
      and len(np.unique(r)) <= 4)


def fs_ref(x, lv):
    """Independently written reference: numpy array, rows from top (larger row) down, per pixel."""
    e = x.astype(np.float64).copy()
    o = np.zeros_like(e)
    hh, ww = e.shape
    for yy in range(hh - 1, -1, -1):
        for xx in range(ww):
            q = min(max(round(e[yy, xx]), 0), lv - 1)
            d = e[yy, xx] - q
            o[yy, xx] = q
            for dy, dx, wgt in ((0, 1, 7), (-1, -1, 3), (-1, 0, 5), (-1, 1, 1)):
                y2, x2 = yy + dy, xx + dx
                if 0 <= y2 < hh and 0 <= x2 < ww:
                    e[y2, x2] += d * wgt / 16
    return o / (lv - 1)


check("  matches the independently written Floyd–Steinberg reference per pixel",
      np.array_equal(r[..., 0], fs_ref(np.clip(noise[..., 0], 0, 1) * 3, 4)))
check("  mean preserved (error diffusion, ±0.01)", abs(r.mean() - noise[..., :1].mean())
      < 0.01, (r.mean(), noise[..., :1].mean()))
g_ = np.repeat(np.linspace(0, 1, 64)[None, :, None], 32, 0)
for meth, tol in (("bayer8", 0.03), ("white_noise", 0.12)):
    r = L(FX.dither(mk(C=g_), "C", meth), "C")[..., 0]
    blk_r = r.reshape(32, 8, 8).mean((0, 2))      # one block per 8 columns
    blk_g = g_[..., 0].reshape(32, 8, 8).mean((0, 2))
    check(f"  {meth} on a gradient: the mean of each 8 columns follows the input (±{tol})",
          np.abs(blk_r - blk_g).max() < tol, np.abs(blk_r - blk_g).max())

S = 96
Jd, Id = np.meshgrid(np.arange(S) + 0.5 - S / 2, np.arange(S) + 0.5 - S / 2)
Rd = 40.0
disc = (np.hypot(Jd, Id) < Rd)[..., None].astype(float)
r = L(FX.planar_inflate(mk(mask=disc), "mask", "poisson", 1.0, 200),
      "height")[..., 0]
ana = np.clip(1 - (np.hypot(Jd, Id) / Rd) ** 2, 0, None)
check("poisson: disc solution = 1 − (r/R)² (analytic, ±0.04)",
      np.abs(r - ana).max() < 0.04, np.abs(r - ana).max())
r = L(FX.planar_inflate(mk(mask=disc), "mask", "round", 2.5), "height")
check("round: peak = Height, 0 outside the mask",
      abs(r.max() - 2.5) < 1e-9 and r[disc == 0].max() == 0)
rr_ = r[S // 2, S // 2:, 0]
dpx = FX.planar_inflate(mk(mask=disc), "mask", "round", 1.0)
hr = L(dpx, "height")[S // 2, S // 2 + 20, 0]
from comfyui_pcg.geo.cop.sdf import edt_sq                 # noqa: E402
dd_ = np.sqrt(edt_sq(disc[..., 0] < 0.5)) - 0.5
Rm = dd_[disc[..., 0] > 0.5].max()
d0 = dd_[S // 2, S // 2 + 20]
check("  profile is a circular arc √(2Rd − d²)/R (not a straight line)",
      abs(hr - math.sqrt(2 * Rm * d0 - d0 * d0) / Rm) < 1e-9, (hr, d0, Rm))
check("  profile decreases monotonically from the center outward", np.all(np.diff(rr_[:int(Rd) - 2]) <= 1e-12))

one_ = mk(C=noise)
check("copy transform 1 copy = identity (1e-9)",
      np.abs(L(FX.copy_transform(one_, "C", 1), "C") - noise).max() < 1e-9)
r = L(FX.copy_transform(one_, "C", 4, translate="0 0", op="add"), "C")
check("  add + translate 0 = 4 times", np.abs(r - 4 * noise).max() < 1e-9)
r = L(FX.copy_transform(one_, "C", 3, translate="0 0", op="add",
                        fade=0.5), "C")
check("  fade 0.5:1 + ½ + ¼", np.abs(r - 1.75 * noise).max() < 1e-9)
dt = np.zeros((H, W, 1)); dt[20, 10] = 1
r = L(FX.copy_transform(mk(C=dt), "C", 3, translate=f"{5 / W} 0",
                        op="max"), "C")[..., 0]
check("  max + translate 5 pixels: three dots at 10 / 15 / 20",
      r[20, 10] == 1 and abs(r[20, 15] - 1) < 1e-9 and
      abs(r[20, 20] - 1) < 1e-9 and r.sum() - 3 < 1e-6)

# ═══════════════════════════════════════════════════════ torch / nodes
sec("torch / nodes")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    ti = CopImage(W, H, {"C": noise.astype(np.float32)}).to_device("cpu")
    for fn in (lambda z: FX.swirl(z, "C"), lambda z: FX.defocus(z, "C"),
               lambda z: FX.denoise_tv(z, "C", 0.1, 10)):
        o = fn(ti)
        ref = fn(mk(C=noise.astype(np.float32)))
        check("[torch] input on torch, output stays on torch, matches numpy",
              o.backend.is_torch and np.allclose(L(o, "C"), L(ref, "C"),
                                                 atol=1e-4))
from comfyui_pcg import nodes_cop2 as N2                  # noqa: E402
B = ["PCG_COPDefocus", "PCG_COPDirectionalBlur", "PCG_COPKuwahara",
     "PCG_COPConvolve", "PCG_COPDenoiseTV", "PCG_COPGlow",
     "PCG_COPDropShadow", "PCG_COPFeather", "PCG_COPPixelate",
     "PCG_COPChromaticAberration", "PCG_COPHeatDistort", "PCG_COPSwirl",
     "PCG_COPLensDistort", "PCG_COPDerivative", "PCG_COPCornerDetect",
     "PCG_COPSmoothFill", "PCG_COPFloodFill", "PCG_COPContour",
     "PCG_COPDither", "PCG_COPMirror", "PCG_COPCornerPin",
     "PCG_COPLatticeDeform", "PCG_COPPlanarInflate", "PCG_COPCopyTransform"]
check(f"all {len(B)} batch B nodes registered, all under PCG/cop",
      all(k in MAP and MAP[k].CATEGORY == "PCG/cop" for k in B))
bad = [k for k in B for nm in MAP[k].INPUT_TYPES()["required"]
       if nm == "seed"]
check("  no widget named seed (it would get control_after_generate attached)", not bad, bad)
r = MAP["PCG_COPConvolve"]().run(mk(C=noise), "C", "custom",
                                 "0 0 0\n0 2 0\n0 0 0", False, "clamp")
r = tuple(r["result"]) if isinstance(r, dict) else r
check("node runs (Convolve, multi-line kernel)", np.allclose(L(r[0], "C"), 2 * noise))
r = MAP["PCG_COPCornerDetect"]().run(mk(C=sq), "C", 0.05, 1.5, 0.01, 4,
                                     "corners", "")
r = tuple(r["result"]) if isinstance(r, dict) else r
check("  Corner Detect second output is an INT count", r[1] == 4)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
