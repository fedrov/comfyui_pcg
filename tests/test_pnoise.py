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

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
