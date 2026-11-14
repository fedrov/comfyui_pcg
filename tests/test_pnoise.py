"""
pcg111: Wrangle pnoise(p, period) -- periodic Perlin noise like VEX's -- and the rand() wrapper fix.

pnoise: with period 0 it is noise() bit for bit; with a period it repeats exactly (p and p + k·period give the same
value, to rounding) per axis, for a scalar and a vector period; an image made from it in a COP Wrangle is seamless on all four
sides, while the same image from noise() is not (negative control).
rand(): rand() of an attribute column used to come back as a plain (N,1) array, so rand(@id) + noise(...) broadcast to
N x N; now it is per element in the COP and the SOP Wrangle.
"""
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

from comfyui_pcg.geo import wrangle as WR  # noqa: E402
from comfyui_pcg.geo import build  # noqa: E402
from comfyui_pcg.geo.core import POINT  # noqa: E402
from comfyui_pcg.geo.cop import pixel as PX  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and not extra else "   " + str(extra)))


r = np.random.default_rng(7)
p = r.uniform(-40, 40, (20000, 3))

print("\n[pnoise: periodic Perlin]")
check("period 0 = noise() bit for bit", np.array_equal(WR.perlin3_periodic(p, 0), WR.perlin3(p)))
a = WR.perlin3_periodic(p, 4)
check("scalar period 4: f(p + 4·k) == f(p) on every axis (to float rounding of p + 4k)",
      all(np.allclose(a, WR.perlin3_periodic(p + d, 4), rtol=0, atol=1e-12)
          for d in ([4, 0, 0], [0, -8, 0], [0, 0, 12], [4, 4, -4])))
b = WR.perlin3_periodic(p, [3, 5, 0])
check("vector period (3, 5, 0): periodic in x by 3 and y by 5",
      np.allclose(b, WR.perlin3_periodic(p + [3, -10, 0], [3, 5, 0]), rtol=0, atol=1e-12))
check("  ... and not periodic in z (period 0 there): shifting z by 3 or 5 changes it (Perlin's own lattice repeats at 256)",
      all(np.abs(b - WR.perlin3_periodic(p + [0, 0, d], [3, 5, 0])).mean() > 0.05 for d in (3, 5)))
check("negative control: noise() is not 4-periodic", np.abs(WR.perlin3(p) - WR.perlin3(p + [4, 0, 0])).mean() > 0.05)
check("  a 4-periodic pnoise differs from noise() (the wrap is not a no-op)", np.abs(a - WR.perlin3(p)).mean() > 0.05)
check("range 0..1 and a Perlin-like spread (std 0.1-0.2, mean 0.5)",
      a.min() >= 0 and a.max() <= 1 and 0.1 < a.std() < 0.2 and abs(a.mean() - 0.5) < 0.02,
      (round(float(a.min()), 3), round(float(a.max()), 3), round(float(a.std()), 3)))
q = np.array([[0.3, 0.7, 0.2]])
check("continuous across the wrap: f(4 - ε) → f(0 + ε) along x",
      abs(float(WR.perlin3_periodic(q + [3.999999, 0, 0], 4)[0])
          - float(WR.perlin3_periodic(q + [-0.000001, 0, 0], 4)[0])) < 1e-5)


def seam(a):
    inner = np.abs(np.diff(a, axis=1)).mean()
    wrap = np.abs(a[:, 0] - a[:, -1]).mean()
    inner_v = np.abs(np.diff(a, axis=0)).mean()
    wrap_v = np.abs(a[0] - a[-1]).mean()
    return wrap / inner, wrap_v / inner_v


p0 = p.copy()
WR.perlin3(p)
WR.perlin3_periodic(p, 4)
check("noise() / pnoise() leave their input unchanged", np.array_equal(p, p0))
im = CopImage(8, 8)
im.set("P", r.random((8, 8, 3)) * 5)
P1 = im.get("P").copy()
t = PX.wrangle(im, "@h = noise(@P) + pnoise(@P, 4)", 0, {})
check("  COP Wrangle: @h = noise(@P) keeps the P layer (it was overwritten by its fractional part)",
      np.array_equal(t.get("P"), P1) and np.array_equal(t.get("h")[..., 0], (WR.perlin3(P1.reshape(-1, 3))
                                                         + WR.perlin3_periodic(P1.reshape(-1, 3), 4)).reshape(8, 8)))

print("\n[pnoise in a COP Wrangle: a tileable image]")
img = CopImage(256, 192)
img.set("C", np.zeros((192, 256, 1)))
t = PX.wrangle(img, "@n = pnoise(set(@u * 8, @v * 6, 0.37), set(8, 6, 0))", 0, {})
n = t.get("n")[..., 0]
sr = seam(n)
check("pnoise image: the jump across the wrapped column / row is like any other (ratio < 1.5)",
      max(sr) < 1.5, [round(x, 2) for x in sr])
t2 = PX.wrangle(img, "@n = noise(set(@u * 8, @v * 6, 0.37))", 0, {})
sr2 = seam(t2.get("n")[..., 0])
check("negative control: the same with noise() has a seam (ratio > 5)", min(sr2) > 5, [round(x, 2) for x in sr2])
t3 = PX.wrangle(img, "@n = pnoise(set(@u * 8, @v * 6, 0.37), set(8, 6, 0))", 0, {}, chunk_rows=50)
check("  Rows per Pass gives the identical image", np.array_equal(t3.get("n"), t.get("n")))

print("\n[rand() of an attribute column stays per element]")
img = CopImage(64, 48)
ids = np.floor(np.linspace(0, 12, 64 * 48)).reshape(48, 64, 1)
img.set("id", ids)
t = PX.wrangle(img, "@a = rand(@id + 0.5) + noise(set(@u * 4, @v * 4, 0))", 3, {})
a = t.get("a")
uu = (np.arange(64) + 0.5) / 64
vv = (np.arange(48) + 0.5) / 48
U, V = np.meshgrid(uu, vv)
want = WR._hash01(ids[..., 0] + 0.5, 3) + WR.perlin3(np.stack([U * 4, V * 4, np.zeros_like(U)], -1).reshape(-1, 3)
                                                     ).reshape(48, 64)
check("COP Wrangle: rand(@id) + noise(...) is one channel, per pixel (was N x N)",
      a.shape == (48, 64, 1) and np.allclose(a[..., 0], want), a.shape)
check("  rand(@id) is the same for the same id and differs between ids",
      np.ptp(PX.wrangle(img, "@b = rand(@id)", 3, {}).get("b")[ids[..., 0] == 5]) == 0
      and len(np.unique(PX.wrangle(img, "@b = rand(@id)", 3, {}).get("b"))) == 13)
g = build.grid(size_x=4, size_z=4, cols=9, rows=9)
g.set(POINT, "id", (np.arange(g.npoints) % 5).astype(np.float64).reshape(-1, 1))
g2 = WR.run_wrangle(g, "@h = rand(@id) + noise(@P)", POINT, seed=1)
h = g2.get(POINT, "h")
P = g.get(POINT, "P")
check("SOP Wrangle: rand(@id) + noise(@P) per point",
      h.shape == (81, 1) and np.allclose(h[:, 0], WR._hash01(np.arange(81) % 5, 1) + WR.perlin3(P)), h.shape)


print("\n[worley / pworley: cellular noise]")
rng = np.random.default_rng(5)
q = rng.random((4000, 3)) * np.array([6.0, 6.0, 2.0])
f1, f2, cid, dv = WR.worley3_periodic(q, 0)
check("f1 <= f2, and the vector to the feature point is f1 long", (f1 <= f2 + 1e-12).all()
      and np.allclose(np.linalg.norm(dv, axis=1), f1))
g1 = WR.worley3_periodic(q + dv, 0)
check("  the point it leads to is a feature point (f1 = 0 there) of the same cell (same id)",
      np.allclose(g1[0], 0, atol=1e-9) and np.allclose(g1[2], cid))
check("  f1 is under a cell diagonal (sqrt 3): the own cell's feature point bounds it", f1.max() < np.sqrt(3))
pf = WR.worley3_periodic(q, 6)
pg = WR.worley3_periodic(q + np.array([6.0, -12.0, 0.0]), 6)
nf = WR.worley3_periodic(q + np.array([6.0, -12.0, 0.0]), 0)
check("pworley(p, 6) repeats every 6 units: f1, f2 and id equal", np.allclose(pf[0], pg[0]) and np.allclose(pf[1], pg[1])
      and np.array_equal(pf[2], pg[2]))
check("  negative control: worley(p) (not periodic) is different there", not np.allclose(f1, nf[0], atol=1e-3))
q2 = rng.random((3000, 2)) * 5
a2 = WR.worley3_periodic(q2, 5)
b2 = WR.worley3_periodic(q2 + np.array([5.0, 10.0]), 5)
c3 = WR.worley3_periodic(np.c_[q2, np.zeros(len(q2))], 5)
check("a 2-vector gives the 2D pattern: it tiles, |dir| = f1 with dir (N, 2), and it is not the 3D one cut at z = 0",
      np.allclose(a2[0], b2[0]) and np.array_equal(a2[2], b2[2]) and a2[3].shape == (3000, 2)
      and np.allclose(np.linalg.norm(a2[3], axis=1), a2[0]) and not np.allclose(a2[0], c3[0], atol=1e-3))
img = CopImage(96, 64)
t = PX.wrangle(img, "w = pworley(set(@u * 6, @v * 4, 0.5), set(6, 4, 0))\n@f = w.x\n@e = w.y - w.x\n"
               "@d = length(pworley_dir(set(@u * 6, @v * 4, 0.5), set(6, 4, 0)))", 0, {})
f_, d_ = t.get("f")[..., 0], t.get("d")[..., 0]
sr = [np.abs(f_[:, 0] - f_[:, -1]).mean() / np.abs(np.diff(f_, axis=1)).mean(),
      np.abs(f_[0] - f_[-1]).mean() / np.abs(np.diff(f_, axis=0)).mean()]
check("COP Wrangle: pworley tiles (the jump across the wrapped edge is like a step between pixels)",
      max(sr) < 2.0, [round(x, 2) for x in sr])
check("  pworley and pworley_dir agree (|dir| = f1) and e = f2 - f1 >= 0", np.allclose(d_, f_, atol=1e-5)
      and (t.get("e") >= -1e-9).all())

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
