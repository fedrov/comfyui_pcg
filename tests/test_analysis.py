"""
The image analysis family: Slope & Aspect / Curvature / Statistics / Histogram /
Segment by Connectivity / Compare.

━━ Criteria
  · Slope / aspect: exact per pixel on a plane; on a quadric the derivatives are **exact even at the border** (quadratic extrapolation
    for padding) -- negative control: the naive difference with clamp padding is wrong at the border
  · Curvature: on a quadric all five curvatures equal the analytic values per pixel; on a spherical cap mean curvature converges to 1/R at second order;
    (profile + tangential)/2 ≡ mean; tangential > 0 on ridges, < 0 in valleys
  · Statistics: mean / std of an arithmetic sequence have a closed form; quantiles match numpy.percentile;
    nan is excluded but counted
  · Histogram: after equalization it is an arithmetic sequence, order preserved, flat colors not stretched into gradients (negative control: a naive
    implementation without average ranks stretches them into gradients); matching to itself is the identity; with the same sample count, sorted output equals the reference one by one
  · Connectivity segmentation: on random masks **labels identical one by one** to a naive per-pixel BFS (4/8-connectivity ×
    tile on/off × three densities)
  · Compare: self vs self SSIM = 1, PSNR = inf; uniform +0.1 gives PSNR exactly 20 dB; SSIM
    matches a naive per-window implementation to 1e-12
"""
import math
import os
import sys
import time
from collections import deque

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
from comfyui_pcg.geo.cop import analysis as AN           # noqa: E402
from comfyui_pcg.geo.cop import backend as BK            # noqa: E402
from comfyui_pcg.geo.cop.filters import gaussian_kernel  # noqa: E402
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


def himg(h, name="C"):
    h = np.asarray(h, np.float64)
    if h.ndim == 2:
        h = h[:, :, None]
    return CopImage(h.shape[1], h.shape[0], {name: h})


W, H = 64, 48
TEX = 1.0 / W
J, I = np.meshgrid(np.arange(W, dtype=np.float64),
                   np.arange(H, dtype=np.float64))
X, Y = (J + 0.5) * TEX, (I + 0.5) * TEX          # world coordinates of pixel centers
rng = np.random.default_rng(5)


# ═══════════════════════════════════════════════════ 1. Slope & Aspect
sec("Slope & Aspect")
a, b = 0.7, -0.4
o = AN.slope_aspect(himg(a * X + b * Y))
sl, asp, dr = L(o, "slope")[..., 0], L(o, "aspect")[..., 0], L(o, "slope_dir")
check("slope on a plane per pixel = atan(√(a²+b²)) (including border)",
      float(np.abs(sl - math.degrees(math.atan(math.hypot(a, b)))).max())
      < 1e-10)
check("  aspect = downhill direction atan2(−b, −a)",
      float(np.abs(asp - math.degrees(math.atan2(-b, -a))).max()) < 1e-10)
check("  downhill direction is a unit vector pointing to (−a, −b)",
      float(np.abs(dr - np.array([-a, -b]) / math.hypot(a, b)).max()) < 1e-12)
check("units=tangent gives |∇h|",
      float(np.abs(L(AN.slope_aspect(himg(a * X + b * Y), units="tangent"),
                     "slope") - math.hypot(a, b)).max()) < 1e-12)
check("units=normalized = degrees / 90",
      float(np.abs(L(AN.slope_aspect(himg(a * X + b * Y),
                                     units="normalized"), "slope") * 90
                   - sl[..., None]).max()) < 1e-10)
qa, qb, qc, qd, qe = 1.3, -0.8, 0.6, 0.2, -0.1
quad = qa * X ** 2 + qb * Y ** 2 + qc * X * Y + qd * X + qe * Y
hx_t, hy_t = 2 * qa * X + qc * Y + qd, 2 * qb * Y + qc * X + qe
d = L(AN.slope_aspect(himg(quad), units="tangent"), "slope")[..., 0]
check("slope on a quadric exact per pixel, **including the border** (quadratic extrapolation padding)",
      float(np.abs(d - np.hypot(hx_t, hy_t)).max()) < 1e-10,
      f"{float(np.abs(d - np.hypot(hx_t, hy_t)).max()):.1e}")
p = np.pad(quad, 1, mode="edge")
nx_ = (p[1:-1, 2:] - p[1:-1, :-2]) / 2 / TEX
check("  negative control: naive difference with clamp padding is wrong at the border (right in the interior)",
      float(np.abs(nx_[:, 0] - hx_t[:, 0]).max()) > 0.1
      and float(np.abs(nx_[:, 1:-1] - hx_t[:, 1:-1]).max()) < 1e-10)
of = AN.slope_aspect(himg(np.zeros((H, W))))
check("flat ground: slope 0, aspect 0, direction (0,0)",
      float(np.abs(L(of, "slope")).max()) == 0.0
      and float(np.abs(L(of, "aspect")).max()) == 0.0
      and float(np.abs(L(of, "slope_dir")).max()) == 0.0)
check("empty layer name: that layer isn't output",
      AN.slope_aspect(himg(quad), aspect_layer="", dir_layer="").names
      == ["C", "slope"])
bump = rng.random((H, W)) * 0.02
check("scale invariance: height and World Size both ×4, slope and aspect unchanged",
      float(np.abs(L(AN.slope_aspect(himg(bump)), "slope")
                   - L(AN.slope_aspect(himg(bump * 4), world_size=4.0),
                       "slope")).max()) < 1e-9)
err("wrong Units errors", lambda: AN.slope_aspect(himg(quad), units="rad"),
    "Units")


# ═══════════════════════════════════════════════════ 2. Curvature
sec("Curvature")


def analytic(hx, hy, hxx, hyy, hxy, kind):
    return AN.curvature_from(BK.EXACT, hx, hy, hxx, hyy, hxy, kind)


hxx_t = np.full_like(X, 2 * qa)
hyy_t = np.full_like(X, 2 * qb)
hxy_t = np.full_like(X, qc)
for kd in AN.CURVATURES:
    cv = L(AN.curvature(himg(quad), kind=kd), "curvature")[..., 0]
    ref = analytic(hx_t, hy_t, hxx_t, hyy_t, hxy_t, kd)
    e = float(np.abs(cv - ref).max() / max(1.0, float(np.abs(ref).max())))
    check(f"[{kd}] equals the analytic value per pixel on a quadric (including border)", e < 1e-8, f"{e:.1e}")
for kd in AN.CURVATURES:
    cv = L(AN.curvature(himg(a * X + b * Y), kind=kd), "curvature")
    check(f"  [{kd}] 0 on a plane", float(np.abs(cv).max()) < 1e-6,
          f"{float(np.abs(cv).max()):.1e}")

smoothh = (0.05 * np.sin(6 * X + 1) * np.cos(5 * Y) + 0.03 * np.sin(9 * X * Y)
           + 0.2 * X)
cm = L(AN.curvature(himg(smoothh), kind="mean"), "curvature")
cp = L(AN.curvature(himg(smoothh), kind="profile"), "curvature")
ct = L(AN.curvature(himg(smoothh), kind="tangential"), "curvature")
check("(profile + tangential) / 2 ≡ mean (Euler: normal curvatures in two orthogonal directions)",
      float(np.abs((cp + ct) / 2 - cm).max()) < 1e-9,
      f"{float(np.abs((cp + ct) / 2 - cm).max()):.1e}")


def cap_err(N):
    """Top of a spherical cap with radius 1: mean curvature error over [-0.3,0.3]² (within 2 pixels of the edge excluded)."""
    t = 0.6 / N
    c = (np.arange(N) + 0.5) * t - 0.3
    XX, YY = np.meshgrid(c, c)
    h = np.sqrt(1.0 - XX ** 2 - YY ** 2)
    m = L(AN.curvature(himg(h), world_size=0.6, kind="mean"),
          "curvature")[..., 0]
    g = L(AN.curvature(himg(h), world_size=0.6, kind="gaussian"),
          "curvature")[..., 0]
    return float(np.abs(m[2:-2, 2:-2] - 1.0).max()), \
        float(np.abs(g[2:-2, 2:-2] - 1.0).max())


e32, g32 = cap_err(32)
e64, g64 = cap_err(64)
check("spherical cap (R=1, convex): mean curvature -> +1, Gaussian curvature -> +1",
      e64 < 1e-3 and g64 < 2e-3, f"mean error {e64:.1e}, gaussian {g64:.1e}")
check("  doubling the resolution drops the error to about 1/4 (second-order convergence)",
      e32 / e64 > 3.5 and g32 / g64 > 3.5,
      f"mean {e32 / e64:.2f}×,gaussian {g32 / g64:.2f}×")
bowl = L(AN.curvature(himg(-np.sqrt(np.maximum(1 - (X - 0.5) ** 2
                                                - (Y - 0.4) ** 2, 0)))),
         "curvature")
check("sign: mean curvature of a bowl (concave) < 0", float(bowl[5:-5, 5:-5].max()) < 0)
sad = L(AN.curvature(himg((X - 0.5) ** 2 - (Y - 0.4) ** 2), kind="gaussian"),
        "curvature")
check("  Gaussian curvature of a saddle < 0", float(sad.max()) < 0)
ridge = -(X - 0.5) ** 2 + 0.5 * Y
valley = (X - 0.5) ** 2 + 0.5 * Y
tr_ = L(AN.curvature(himg(ridge), kind="tangential"), "curvature")[..., 0]
tv_ = L(AN.curvature(himg(valley), kind="tangential"), "curvature")[..., 0]
pr_ = L(AN.curvature(himg(ridge), kind="profile"), "curvature")[..., 0]
check("tangential > 0 on ridges, < 0 in valleys (use it to separate ridges and valleys, not elevation)",
      float(tr_[:, W // 2 - 1:W // 2 + 1].min()) > 0
      and float(tv_[:, W // 2 - 1:W // 2 + 1].max()) < 0)
check("  near the ridge line it's almost straight along the slope: |profile| < 1e-2 (pixel centers aren't exactly on the ridge line, analytic value ≈ 1.9e-3)",
      float(np.abs(pr_[:, 31:33]).max()) < 1e-2,
      f"{float(np.abs(pr_[:, 31:33]).max()):.1e}")
bw = (X - 0.5) ** 2 + (Y - 0.4) ** 2
p2 = np.pad(bw, 1, mode="edge")
hxx_naive = (p2[1:-1, 2:] - 2 * p2[1:-1, 1:-1] + p2[1:-1, :-2]) / TEX ** 2
check("negative control: naive second difference with clamp padding is wrong at the border (bowl edge reports a fake ridge)",
      float(np.abs(hxx_naive[:, 0] - 2.0).max()) > 10.0,
      f"border h_xx {hxx_naive[5, 0]:.1f} vs true value 2")
check("Scale is the final multiplier",
      float(np.abs(L(AN.curvature(himg(smoothh), scale=3.0), "curvature")
                   - 3 * cm).max()) < 1e-12)
err("wrong Kind errors", lambda: AN.curvature(himg(quad), kind="shape"), "Kind")


# ═══════════════════════════════════════════════════ 3. Statistics
sec("Statistics")
ramp = np.arange(W * H, dtype=np.float64).reshape(H, W)
N_ = W * H
st = AN.statistics(himg(ramp), percentiles=(1, 25, 50, 99))["layers"]["C"]
check("arithmetic sequence 0..N−1: mean = (N−1)/2", abs(st["mean"][0] - (N_ - 1) / 2)
      < 1e-9)
check("  std(÷N)= √((N²−1)/12)", abs(st["std"][0] - math.sqrt((N_ ** 2 - 1)
                                                             / 12)) < 1e-6)
check("  min / max", st["min"][0] == 0 and st["max"][0] == N_ - 1)
check("  quantiles match numpy.percentile (linear interpolation)",
      all(abs(st["percentiles"][str(float(p_))][0]
              - float(np.percentile(ramp, p_))) < 1e-9
          for p_ in (1, 25, 50, 99)))
rgb = np.stack([ramp, ramp * 2, np.full_like(ramp, 7.0)], -1)
st = AN.statistics(himg(rgb))["layers"]["C"]
check("per channel: each of the three channels has its own set", st["channels"] == 3
      and abs(st["mean"][1] - (N_ - 1)) < 1e-9 and st["std"][2] == 0.0)
withnan = ramp.copy()
withnan[0, :5] = np.nan
withnan[1, 0] = np.inf
st = AN.statistics(himg(withnan))["layers"]["C"]
check("nan / inf excluded from the stats, but their count is reported", st["nonfinite"][0] == 6
      and math.isfinite(st["mean"][0]))
rep = AN.stats_report(AN.statistics(himg(withnan)))
check("  written in the report", "6 non-finite values" in rep, rep.splitlines()[-1][:80])
mk = CopImage(W, H, {"C": ramp[:, :, None], "mask":
                     (J < 16).astype(np.float64)[:, :, None]})
st = AN.statistics(mk, "C", "mask")
check("Mask Layer: only the masked area is counted, coverage reported",
      abs(st["coverage"] - 0.25) < 1e-12
      and st["layers"]["C"]["max"][0] == float(ramp[:, :16].max()))
r = MAP["PCG_COPStatistics"]().run(himg(ramp), "", "", "1 50 99", "C", 0,
                                   "p50")
r = r["result"] if isinstance(r, dict) else r
check("node's value output: the picked number is exactly that one",
      abs(r[3] - float(np.percentile(ramp, 50))) < 1e-9)
check("  json is valid JSON, the report is human-readable", r[1].startswith("{") and "mean" in r[2])
err("node: Value Layer not in the stats errors and lists the existing ones",
    lambda: MAP["PCG_COPStatistics"]().run(himg(ramp), "", "", "50", "N", 0,
                                           "mean"), "is not among the layers in the statistics")


# ═══════════════════════════════════════════════════ 4. Histogram
sec("Histogram (equalize / match)")
dist = rng.permutation(W * H).astype(np.float64).reshape(H, W) ** 1.7
eq = L(AN.histogram(himg(dist), "equalize"), "C")[..., 0]
lo, hi = float(dist.min()), float(dist.max())
check("equalize: sorted it's exactly an arithmetic sequence over [min, max] (without ties)",
      float(np.abs(np.sort(eq.ravel()) - np.linspace(lo, hi, W * H)).max())
      < 1e-6 * hi)
check("  order preserved: original order = output order",
      bool((np.argsort(dist.ravel()) == np.argsort(eq.ravel())).all()))
blk = rng.random((H, W))
blk[:, :20] = 0.5                                    # a big flat-color block
eqb = L(AN.histogram(himg(blk), "equalize"), "C")[..., 0]
check("flat-color region is still flat after equalization (ties get the average rank)",
      float(np.ptp(eqb[:, :20])) == 0.0)
naive = np.empty(W * H)
naive[np.argsort(blk.ravel(), kind="stable")] = np.arange(W * H)
naive = naive.reshape(H, W)
check("  negative control: a naive implementation without average ranks stretches the flat color into a gradient",
      float(np.ptp(naive[:, :20])) > 100)
check("Amount = 0: bit-identical",
      bool((L(AN.histogram(himg(dist), amount=0.0), "C")[..., 0]
            == dist).all()))
check("Amount = 0.5: midpoint of the original and the result",
      float(np.abs(L(AN.histogram(himg(dist), amount=0.5), "C")[..., 0]
                   - (dist + eq) / 2).max()) < 1e-6 * hi)
ref = rng.normal(3.0, 2.0, (H, W))
m_self = L(AN.histogram(himg(dist), "match", himg(dist)), "C")[..., 0]
check("matching to itself: identity", float(np.abs(m_self - dist).max()) == 0.0)
m_ref = L(AN.histogram(himg(dist), "match", himg(ref)), "C")[..., 0]
check("same sample count: sorted output **equals** the sorted reference one by one",
      bool((np.sort(m_ref.ravel()) == np.sort(ref.ravel())).all()))
check("  and order preserved", bool((np.argsort(dist.ravel())
                         == np.argsort(m_ref.ravel(), kind="stable")).all()))
small_ref = himg(rng.normal(-1.0, 0.5, (17, 23)))
m2 = L(AN.histogram(himg(dist), "match", small_ref), "C")[..., 0]
sr = np.sort(L(small_ref, "C").ravel())
check("different sample counts: output falls within the reference's range, quantiles match",
      float(m2.min()) >= sr[0] and float(m2.max()) <= sr[-1]
      and abs(float(np.median(m2)) - float(np.median(sr))) < 0.05)
mask_img = CopImage(W, H, {"C": dist[:, :, None],
                           "m": (J < 32).astype(np.float64)[:, :, None]})
mm = L(AN.histogram(mask_img, "equalize", mask_layer="m", layers="C"),
       "C")[..., 0]
check("Mask Layer: outside the mask unchanged bit for bit", bool((mm[:, 32:] == dist[:, 32:]).all())
      and float(np.abs(mm[:, :32] - dist[:, :32]).max()) > 0)
rgb3 = np.stack([dist, dist * 0.5, dist * 2], -1)
check("1-channel reference: all channels match to it",
      float(np.abs(L(AN.histogram(himg(rgb3), "match", himg(ref)), "C")
                   - np.sort(ref.ravel())[np.argsort(np.argsort(
                       dist.ravel()))].reshape(H, W)[:, :, None]).max())
      < 1e-12)
err("Match without a reference image errors", lambda: AN.histogram(himg(dist), "match"),
    "reference image")
err("mismatched reference channel count errors", lambda: AN.histogram(
    himg(rgb3), "match", himg(np.stack([ref, ref], -1))), "channels")


# ═══════════════════════════════════════════════════ 5. Segment
sec("Segment by Connectivity")


def bfs_label(m, conn, tile):
    """Naive per-pixel BFS; label ordering follows the same rule as the implementation under test."""
    Hh, Ww = m.shape
    lab = np.zeros((Hh, Ww), np.int64)
    nb = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if conn == 8:
        nb += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    comps = []
    cur = 0
    for y in range(Hh):
        for x in range(Ww):
            if m[y, x] and lab[y, x] == 0:
                cur += 1
                q = deque([(y, x)])
                lab[y, x] = cur
                n = 0
                while q:
                    cy, cx = q.popleft()
                    n += 1
                    for dy, dx in nb:
                        ny_, nx2 = cy + dy, cx + dx
                        if tile:
                            ny_ %= Hh
                            nx2 %= Ww
                        elif not (0 <= ny_ < Hh and 0 <= nx2 < Ww):
                            continue
                        if m[ny_, nx2] and lab[ny_, nx2] == 0:
                            lab[ny_, nx2] = cur
                            q.append((ny_, nx2))
                comps.append((n, y * Ww + x, cur))
    # Area descending, then by first pixel (the first pixel in scan order is the first pixel)
    order = sorted(comps, key=lambda c: (-c[0], c[1]))
    remap = np.zeros(cur + 1, np.int64)
    for i, c in enumerate(order):
        remap[c[2]] = i + 1
    return remap[lab]


mism = []
for dens in (0.3, 0.5, 0.62):
    for conn in (4, 8):
        for tl in (False, True):
            for trial in range(3):
                m = np.random.default_rng(100 + trial).random((37, 53)) < dens
                if not (AN.label(m, conn, tl) == bfs_label(m, conn, tl)).all():
                    mism.append((dens, conn, tl, trial))
check("on random masks **labels identical one by one** to per-pixel BFS"
      " (3 densities × 4/8-connectivity × tile on/off × 3 runs)", not mism,
      f"mismatch: {mism[:4]}" if mism else "all 36 sets match")
sq = np.zeros((20, 30), bool)
sq[2:6, 2:6] = True
sq[6:12, 6:14] = True                                 # touching only diagonally at (5,5)-(6,6)
check("two blocks touching diagonally: 4-connectivity counts two, 8-connectivity one",
      AN.label(sq, 4).max() == 2 and AN.label(sq, 8).max() == 1)
lb = AN.label(sq, 4)
check("  ids by area, largest first: the big block is 1", lb[8, 8] == 1 and lb[3, 3] == 2)
seam = np.zeros((20, 30), bool)
seam[5:9, :3] = True
seam[5:9, -3:] = True
check("a block across the left/right seam: one with tile, two without",
      AN.label(seam, 8, True).max() == 1 and AN.label(seam, 8, False).max()
      == 2)
seam2 = np.zeros((20, 30), bool)
seam2[:2, 10:14] = True
seam2[-2:, 10:14] = True
check("  same for the top/bottom seam", AN.label(seam2, 4, True).max() == 1)
corner = np.zeros((20, 30), bool)
corner[0, 0] = corner[-1, -1] = True
check("  diagonal across both seams (corner to corner): tile + 8-connectivity counts one, 4-connectivity two",
      AN.label(corner, 8, True).max() == 1 and AN.label(corner, 4, True).max()
      == 2)
check("empty mask -> 0 pieces", AN.label(np.zeros((8, 8), bool)).max() == 0)
dots = np.zeros((40, 40))
dots[5:15, 5:15] = 1
dots[20, 20] = 1
dots[30:32, 30:32] = 1
o, rep = AN.segment(himg(dots, "mask"), min_area=5)
idl = L(o, "id")[..., 0]
check("Min Area: small fragments merged into the background, the rest renumbered contiguously",
      rep["count"] == 1 and rep["removed"] == 2 and idl.max() == 1
      and idl[20, 20] == 0, rep)
nd = MAP["PCG_COPSegment"]().run(himg(dots, "mask"), "mask", 0.5, "8", 0,
                                 False, "id", True)
nd = nd["result"] if isinstance(nd, dict) else nd
check("node outputs the piece count and report", nd[1] == 3 and "3 pieces" in nd[2], nd[2])
bigm = np.random.default_rng(9).random((1024, 1024)) < 0.5
t0 = time.time()
kk = AN.label(bigm, 8)
dt = time.time() - t0
check(f"1024² 50% noise mask {dt:.2f} s (limit 20 s)", dt < 20.0,
      f"{int(kk.max())} pieces")


# ═══════════════════════════════════════════════════ 6. Compare
sec("Compare")
A = rng.random((H, W, 3))
o, m = AN.compare(himg(A), himg(A))
check("self vs self: MAE = 0, SSIM = 1, PSNR = +inf",
      m["mae"] == 0.0 and abs(m["ssim"] - 1.0) < 1e-12
      and math.isinf(m["psnr"]))
check("  inf written as a string in json (standard JSON has no inf)",
      '"psnr": "inf"' in AN.dumps(m))
Bn = np.clip(A + rng.normal(0, 0.05, A.shape), 0, 1)
_, m1 = AN.compare(himg(A), himg(Bn))
_, m2 = AN.compare(himg(Bn), himg(A))
check("symmetric", all(abs(m1[k] - m2[k]) < 1e-12 for k in ("mae", "rmse", "ssim")))
_, mo = AN.compare(himg(A), himg(A + 0.1))
check("uniform +0.1: RMSE = 0.1, PSNR exactly 20 dB",
      abs(mo["rmse"] - 0.1) < 1e-12 and abs(mo["psnr"] - 20.0) < 1e-9,
      f"{mo['psnr']:.12f}")
ss = [AN.compare(himg(A), himg(np.clip(A + rng.normal(0, s_, A.shape), 0,
                                      1)))[1]["ssim"]
      for s_ in (0.01, 0.05, 0.2)]
check("more noise, lower SSIM", ss[0] > ss[1] > ss[2],
      " > ".join(f"{v:.3f}" for v in ss))


def ssim_naive(a, b, L_=1.0, sigma=1.5):
    """Naive per-pixel, per-window SSIM (clamp border), used for cross-checking."""
    k = gaussian_kernel(sigma)
    r = (len(k) - 1) // 2
    w2 = np.outer(k, k)
    Hh, Ww = a.shape
    C1, C2 = (0.01 * L_) ** 2, (0.03 * L_) ** 2
    out = np.zeros_like(a)
    for y in range(Hh):
        for x in range(Ww):
            ys = np.clip(np.arange(y - r, y + r + 1), 0, Hh - 1)
            xs = np.clip(np.arange(x - r, x + r + 1), 0, Ww - 1)
            pa, pb = a[np.ix_(ys, xs)], b[np.ix_(ys, xs)]
            ma, mb = (w2 * pa).sum(), (w2 * pb).sum()
            va = (w2 * pa * pa).sum() - ma * ma
            vb = (w2 * pb * pb).sum() - mb * mb
            cab = (w2 * pa * pb).sum() - ma * mb
            out[y, x] = ((2 * ma * mb + C1) * (2 * cab + C2)
                         / ((ma * ma + mb * mb + C1) * (va + vb + C2)))
    return out


sa, sb = rng.random((16, 20)), rng.random((16, 20))
o, mm_ = AN.compare(himg(sa), himg(sb))
nv = ssim_naive(sa, sb)
check("SSIM map matches the naive per-window implementation (1e-12)",
      float(np.abs(L(o, "ssim")[..., 0] - nv).max()) < 1e-12,
      f"{float(np.abs(L(o, 'ssim')[..., 0] - nv).max()):.1e}")
check("  mean SSIM is the mean of the SSIM map", abs(mm_["ssim"] - nv.mean()) < 1e-12)
o, _ = AN.compare(himg(A), CopImage(32, 24, {"C": A[:24, :32]}))
check("b with a different resolution is resampled to a first", o.res == (W, H))
_, mg = AN.compare(himg(A[..., :1]), himg(np.repeat(A[..., :1], 3, -1)))
check("1 channel broadcasts against 3 channels", mg["mae"] == 0.0)
r = MAP["PCG_COPCompare"]().run(himg(A), himg(A), "C", "", 1.0, "diff",
                                "ssim", True)
r = r["result"] if isinstance(r, dict) else r
check("node: PSNR output clamped to 999 when identical (inf going downstream causes trouble), json written as is",
      r[3] == 999.0 and '"inf"' in r[4] and "∞" in r[1])
err("mismatched channel counts error", lambda: AN.compare(himg(A), himg(A[..., :2])),
    "channel counts")


# ═══════════════════════════════════════════════════ 7. Backends
sec("Backend consistency (numpy float32 vs torch CPU)")
tb = BK.get("cpu")
if tb is BK.NUMPY:
    print("  (no torch, skipped)")
else:
    b32 = CopImage(W, H, {"C": smoothh.astype(np.float32)[:, :, None],
                          "mask": (rng.random((H, W)) < 0.5)
                          .astype(np.float32)[:, :, None]})
    tbase = b32.to_device("cpu")
    ops = [
        ("slope", lambda i: AN.slope_aspect(i), "slope"),
        ("curvature/mean", lambda i: AN.curvature(i), "curvature"),
        ("curvature/plan", lambda i: AN.curvature(i, kind="plan"),
         "curvature"),
        ("compare", lambda i: AN.compare(i, i)[0], "ssim"),
        ("histogram (numpy-only)", lambda i: AN.histogram(i, layers="C"),
         "C"),
        ("segment (numpy-only)", lambda i: AN.segment(i)[0], "id"),
    ]
    for nm, fn, lay in ops:
        try:
            g, c = fn(tbase), fn(b32)
            d_ = float(np.abs(L(g, lay) - L(c, lay)).max())
            sc = max(1.0, float(np.abs(L(c, lay)).max()))
            check(f"[torch] {nm}: results match, and still on torch",
                  d_ / sc < 1e-4 and g.backend.is_torch, f"{d_ / sc:.1e}")
        except Exception as ex:
            check(f"[torch] {nm}", False, f"{type(ex).__name__}: {ex}")
    st_t = AN.statistics(tbase)["layers"]["C"]["mean"][0]
    st_n = AN.statistics(b32)["layers"]["C"]["mean"][0]
    check("[torch] statistics computes fine on torch input", abs(st_t - st_n) < 1e-9)

names = ["Slope", "Curvature", "Statistics", "Histogram", "Segment",
         "Compare"]
check("all six nodes registered, all under PCG/cop",
      all(MAP[f"PCG_COP{n}"].CATEGORY == "PCG/cop" for n in names))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
