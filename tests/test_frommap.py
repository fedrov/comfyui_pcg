import os
import sys
# Package root: first search upwards from this file's location, fall back to the old sandbox path if not found.
# These suites are now the **only** copy (the sandbox gets reclaimed), so paths can no longer be hard-coded
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import time
import numpy as np
from comfyui_pcg.geo import (Geometry, POINT, VERTEX, PRIM, build, ops,
                             uvproject as U, scatter as S,
                             frommap as FM, trace as T)
from comfyui_pcg.geo.cop.core import CopImage

OK = []
def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)

def RUN(fn, *a, **k):
    """
    Call a node's execution function and **unpack** the return value.

    In production comfyui_pcg/__init__.py wraps every node's execution function with attach_group_reporting /
    attach_cop_preview, and the wrapped function returns
    {"ui": ..., "result": (...)}. A direct `a, b = node.run(...)` would get
    **the dict's key names** ("ui", "result") as two strings, and then fail with
    `'str' object has no attribute ...`, an error that does not point to the real cause.
    """
    return fakecomfy.unwrap(fn(*a, **k))


def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


def img_from(f):
    """(H,W) or (H,W,C) -> CopImage, float64 keeps analytic precision."""
    a = np.asarray(f, np.float64)
    if a.ndim == 2:
        a = a[:, :, None]
    return CopImage(a.shape[1], a.shape[0], {"C": a})


def uvgrid(N, M=None):
    """(u,v) pixel-center grid, v points up (row 0 = smallest v)."""
    M = M or N
    y, x = np.mgrid[0:M, 0:N]
    return (x + 0.5) / N, (y + 0.5) / M


GRID = U.project(build.grid(2, 2, 17, 13), mode="planar", axis="y")
SPH = U.project(ops.compute_normals(build.sphere(1.0, 32, 24)),
                mode="spherical", axis="y")


print("═" * 28, "sRGB encode / decode")

check("srgb_decode is piecewise, not a 2.2 power",
      abs(FM.srgb_decode(0.5) - 0.21404114) < 1e-8, FM.srgb_decode(0.5))
tab = FM.srgb_decode(np.array([0.25, 0.5, 0.75]))
check("matches the table in the docs (0.0509 / 0.2140 / 0.5225)",
      np.allclose(tab, [0.05087609, 0.21404114, 0.52252155], atol=1e-7), tab)
r = np.linspace(0, 1, 2001)
check("encode(decode(x)) == x round trip < 1e-9",
      np.abs(FM.srgb_encode(FM.srgb_decode(r)) - r).max() < 1e-9,
      np.abs(FM.srgb_encode(FM.srgb_decode(r)) - r).max())
check("the dark segment really is a straight line (slope at 0.02 = 1/12.92)",
      abs((FM.srgb_decode(0.021) - FM.srgb_decode(0.019)) / 0.002
          - 1 / 12.92) < 1e-9)
check("counterexample: a 2.2 power and true sRGB differ by 2.6× in the darks (so a power function cannot stand in)",
      0.05 ** 2.2 / FM.srgb_decode(0.05) < 0.4,
      (0.05 ** 2.2, FM.srgb_decode(0.05)))
check("apply_decode('none') does nothing",
      FM.apply_decode(0.5, "none") == 0.5)


print("═" * 28, "uv lookup (vertex / point / prim)")

vuv = FM.uv_of(GRID, VERTEX)[0]
check("vertex mode is the vertex attribute itself",
      np.abs(vuv - np.asarray(GRID.get(VERTEX, "uv"), np.float64)).max() < 1e-9)
puv, pvalid, seams = FM.uv_of(GRID, POINT)
first = FM._first_vertex_of_point(GRID)
check("point mode takes the uv of the first incident vertex",
      np.abs(puv - vuv[first]).max() < 1e-9)
check("a planar grid has no uv seams", seams == 0, seams)
check("every point has an incident vertex", pvalid.all())

pruv = FM.uv_of(GRID, PRIM)[0]
pr = GRID.vertex_prim()
man = np.stack([np.bincount(pr, weights=vuv[:, k], minlength=GRID.nprims)
                for k in range(2)], 1) / GRID.prim_sizes()[:, None]
check("prim mode = average uv of the face's vertices",
      np.abs(pruv - man).max() < 1e-9)

# artificial uv seam: one quad, u of two vertices changed from 0 to 1
seam = build.grid(2, 2, 3, 3)
seam = U.project(seam, mode="planar", axis="y")
vv = np.array(seam.get(VERTEX, "uv"), np.float64)
hit = np.nonzero(vv[:, 0] < 1e-6)[0]
vv[hit[:2], 0] = 1.0
seam.set(VERTEX, "uv", vv.astype(np.float32), owned=True)
suv0, _, ns = FM.uv_of(seam, POINT)
vp_s = np.asarray(seam.vertex_point, np.int64)
exp_seam = int(np.count_nonzero(np.bincount(
    vp_s, weights=(np.abs(vv[:, 0] - suv0[vp_s][:, 0]) > 1e-6).astype(float),
    minlength=seam.npoints) > 0))
check("seam points are counted", ns == exp_seam and ns > 0, (ns, exp_seam))
amb = np.nonzero(np.bincount(
    vp_s, weights=(np.abs(vv[:, 0] - suv0[vp_s][:, 0]) > 1e-6).astype(float),
    minlength=seam.npoints) > 0)[0]
check("seam points take the true value of one side (0 or 1), not the 0.5 average of both sides",
      np.all(np.minimum(np.abs(suv0[amb, 0]), np.abs(suv0[amb, 0] - 1.0))
             < 1e-6), suv0[amb, 0])

iso = Geometry.from_points(np.zeros((3, 3), np.float32))
iso.set(POINT, "uv", np.zeros((3, 2), np.float32), owned=True)
check("a point cloud (no vertices) can still get uv through point mode",
      FM.uv_of(iso, POINT)[1].all())
nouv = Geometry.from_mesh(np.zeros((4, 3), np.float32),
                          np.array([[0, 1, 2, 3]]))
err("missing uv attribute: the error lists the existing attribute names",
    lambda: FM.uv_of(nouv, POINT), "uv attribute 'uv' not found")


print("═" * 28, "Sampling: bilinear is exact inside the image")

N = 64
u, v = uvgrid(N)
BIL = 0.3 + 0.5 * u - 0.2 * v + 0.7 * u * v      # bilinear -> exactly reconstructible
IB = img_from(BIL)
g, info = FM.attribute_from_map(GRID, IB, cls=VERTEX, name="h")
got = g.get(VERTEX, "h")[:, 0]
exp = 0.3 + 0.5 * vuv[:, 0] - 0.2 * vuv[:, 1] + 0.7 * vuv[:, 0] * vuv[:, 1]
h = 0.5 / N
inner = ((vuv[:, 0] > h) & (vuv[:, 0] < 1 - h)
         & (vuv[:, 1] > h) & (vuv[:, 1] < 1 - h))
e_in = float(np.abs(got[inner] - exp[inner]).max())
check("interior error < 1e-6 (bilinear reconstruction of a bilinear function is exact)", e_in < 1e-6, e_in)
e_all = float(np.abs(got - exp).max())
check("the half pixel at the edge is the clamp zone, error O(1/N) rather than O(eps)",
      e_all > 100 * e_in and e_all < 3.0 / N, (e_all, 1.0 / N))

VR = img_from(np.broadcast_to(v, (N, N)))
gv, _ = FM.attribute_from_map(GRID, VR, cls=VERTEX, name="h")
hv = gv.get(VERTEX, "h")[:, 0]
d_ok = float(np.abs(hv - vuv[:, 1]).max())
d_flip = float(np.abs(hv - (1 - vuv[:, 1])).max())
check("v points up: sampling f(u,v)=v gives back v", d_ok < 2.0 / N, d_ok)
check("counterexample: flipping v one time too many/few gives an O(1) error, detectable",
      d_flip > 0.9, d_flip)

uvc = np.stack([u.ravel(), v.ravel()], 1)
sb = FM.sample_layer(IB, uvc, filter="bilinear")[:, 0]
sc = FM.sample_layer(IB, uvc, filter="closest")[:, 0]
check("at pixel centers closest == bilinear == original value (same center convention)",
      np.abs(sb - BIL.ravel()).max() < 1e-12
      and np.abs(sc - BIL.ravel()).max() < 1e-12)

q = np.array([[0.31, 0.77], [0.02, 0.5], [0.9, 0.12]])
check("wrap: adding an integer period to uv does not change the result",
      np.abs(FM.sample_layer(IB, q, border="wrap")
             - FM.sample_layer(IB, q + np.array([3.0, -2.0]),
                               border="wrap")).max() < 1e-12,
      np.abs(FM.sample_layer(IB, q, border="wrap")
             - FM.sample_layer(IB, q + np.array([3.0, -2.0]),
                               border="wrap")).max())
check("clamp: outside the image takes the border value",
      np.abs(FM.sample_layer(IB, np.array([[-5.0, 0.5]]), border="clamp")
             - FM.sample_layer(IB, np.array([[0.0, 0.5]]),
                               border="clamp")).max() < 1e-12)
check("black: outside the image is 0",
      abs(float(FM.sample_layer(IB, np.array([[-5.0, 0.5]]),
                                border="black")[0, 0])) < 1e-12)
check("closest also respects wrap",
      np.abs(FM.sample_layer(IB, q, border="wrap", filter="closest")
             - FM.sample_layer(IB, q + 1.0, border="wrap",
                               filter="closest")).max() < 1e-12)

RGB = img_from(np.stack([u, v, np.full_like(u, 0.25)], -1))
check("empty channels = all", FM.sample_layer(RGB, q).shape[1] == 3)
check("channels='0,2' takes the given channels",
      np.allclose(FM.sample_layer(RGB, q, channels="0,2")[:, 1], 0.25))
check("channels='-1' supports negative indices",
      np.allclose(FM.sample_layer(RGB, q, channels="-1")[:, 0], 0.25))
err("out-of-range channel raises right away, not silently clamped",
    lambda: FM.sample_layer(RGB, q, channels="7"), "out of range")
err("passing IMAGE instead of COPIMAGE gives an actionable hint",
    lambda: FM.sample_layer(np.zeros((4, 4, 3)), q), "COPIMAGE")


print("═" * 28, "Attribute from Map")

g3, i3 = FM.attribute_from_map(GRID, RGB, cls=POINT, name="Cd")
check("component count follows the layer", g3.get(POINT, "Cd").shape[1] == 3, i3)
check("info reports the right element count", i3["count"] == GRID.npoints, i3)
check("the original geometry was not modified", GRID.get(POINT, "Cd") is None)

gs, _ = FM.attribute_from_map(GRID, VR, cls=VERTEX, name="h",
                              scale=3.0, offset=-1.0)
check("scale / offset take effect",
      np.abs(gs.get(VERTEX, "h")[:, 0] - (hv * 3.0 - 1.0)).max() < 1e-6)

base = GRID.copy()
base.set(VERTEX, "h", np.ones((GRID.nvertices, 1), np.float32), owned=True)
gb, _ = FM.attribute_from_map(base, VR, cls=VERTEX, name="h", blend=0.25)
check("blend=0.25 is a linear blend with the original value",
      np.abs(gb.get(VERTEX, "h")[:, 0] - (1.0 + (hv - 1.0) * 0.25)).max()
      < 1e-6)
gb0, _ = FM.attribute_from_map(base, VR, cls=VERTEX, name="h", blend=0.0)
check("blend=0 leaves the original value completely alone",
      np.abs(gb0.get(VERTEX, "h")[:, 0] - 1.0).max() < 1e-6)

sel = GRID.copy()
sel.set_group(POINT, "half", np.asarray(GRID.get(POINT, "P"))[:, 0] > 0)
gg, ig = FM.attribute_from_map(sel, VR, cls=POINT, name="h", group="half")
m = np.asarray(GRID.get(POINT, "P"))[:, 0] > 0
check("elements outside the group stay 0 (the attribute did not exist before)",
      np.abs(gg.get(POINT, "h")[~m, 0]).max() < 1e-12
      and np.abs(gg.get(POINT, "h")[m, 0]).max() > 0.1)
check("info only counts elements in the group", ig["count"] == int(m.sum()), ig)

# tiling needs a periodic function to be continuous: a v ramp has a jump at the wrap seam anyway
PER = img_from(np.sin(2 * np.pi * v))
g1, _ = FM.attribute_from_map(GRID, PER, cls=VERTEX, name="h1",
                              border="wrap")
g2, _ = FM.attribute_from_map(GRID, PER, cls=VERTEX, name="h2",
                              uv_scale_v=3.0, border="wrap")
e_tile = float(np.abs(g2.get(VERTEX, "h2")[:, 0]
                      - np.sin(2 * np.pi * 3 * vuv[:, 1])).max())
check("uv_scale=3 tiles, the period becomes exactly 3×", e_tile < 5e-3, e_tile)
check("counterexample: without tiling the same criterion is off by O(1)",
      float(np.abs(g1.get(VERTEX, "h1")[:, 0]
                   - np.sin(2 * np.pi * 3 * vuv[:, 1])).max()) > 0.5)

gd, _ = FM.attribute_from_map(GRID, VR, cls=VERTEX, name="h",
                              decode="srgb_to_linear")
check("decode is applied after sampling",
      np.abs(gd.get(VERTEX, "h")[:, 0]
             - FM.srgb_decode(hv)).max() < 1e-6)
err("an empty attribute name raises",
    lambda: FM.attribute_from_map(GRID, VR, name=" "), "must not be empty")


print("═" * 28, "Displace from Map")

ONE = img_from(np.ones((8, 8)))
sp = FM.displace_from_map(SPH, ONE, amount=0.1, midpoint=0.0)
P0 = np.asarray(SPH.get(POINT, "P"), np.float64)
P1 = np.asarray(sp.get(POINT, "P"), np.float64)
Ns = np.asarray(SPH.get(POINT, "N"), np.float64)
step = P1 - P0
check("constant-1 image × amount 0.1: every point moves exactly 0.1",
      float(np.abs(np.linalg.norm(step, axis=1) - 0.1).max()) < 1e-6,
      float(np.abs(np.linalg.norm(step, axis=1) - 0.1).max()))
check("the direction is the point normal",
      float(np.abs(step / 0.1 - Ns).max()) < 1e-5)
rad = np.linalg.norm(P1, axis=1)
# point normals averaged from face normals deviate from radial by at most 1.95°, so the radius increment is 0.1·cos(1.95°)
check("unit sphere radius grows to ~1.1 (the 5e-5 shortfall is because point normals are not exactly radial)",
      abs(float(rad.mean()) - 1.1) < 2e-4, rad.mean())
HALF = img_from(np.full((8, 8), 0.5))
sp0 = FM.displace_from_map(SPH, HALF, amount=1.0, midpoint=0.5)
check("no movement at all at the midpoint",
      float(np.abs(np.asarray(sp0.get(POINT, "P"))
                   - np.asarray(SPH.get(POINT, "P"))).max()) < 1e-6)
spd = FM.displace_from_map(SPH, HALF, amount=1.0, midpoint=0.0,
                           decode="srgb_to_linear")
rd = np.linalg.norm(np.asarray(spd.get(POINT, "P"), np.float64), axis=1)
check("counterexample: without decoding 0.5 pushes 0.5, decoded it only pushes 0.214 -- more than 2× apart",
      abs(float(rd.mean()) - 1.21404) < 1e-4, rd.mean())

gv2 = FM.displace_from_map(GRID, ONE, amount=0.5, direction="vector",
                           dir_x=3.0, dir_y=4.0, dir_z=0.0)
dP = (np.asarray(gv2.get(POINT, "P"), np.float64)
      - np.asarray(GRID.get(POINT, "P"), np.float64))
check("direction=vector normalizes the direction (3,4,0 -> 0.5*(0.6,0.8,0))",
      np.abs(dP - np.array([0.3, 0.4, 0.0])).max() < 1e-6, dP[0])

gsel = GRID.copy()
gsel.set_group(POINT, "half", np.asarray(GRID.get(POINT, "P"))[:, 0] > 0)
gs2 = FM.displace_from_map(gsel, ONE, amount=1.0, direction="vector",
                           dir_y=1.0, group="half")
mv = np.abs(np.asarray(gs2.get(POINT, "P"), np.float64)[:, 1]) > 1e-6
check("points outside the group do not move", np.array_equal(mv, m))

noN = build.grid(2, 2, 5, 5)
noN = U.project(noN, mode="planar", axis="y")
gnn = FM.displace_from_map(noN, ONE, amount=1.0)
check("without an N attribute point normals are computed on the spot (planar grid -> everything pushed 1 along +Y)",
      np.abs(np.asarray(gnn.get(POINT, "P"), np.float64)[:, 1] - 1.0).max()
      < 1e-6)
check("and the temporarily computed N is not written back to the geometry", not gnn.has(POINT, "N"))


print("═" * 28, "Scatter now interpolates vertex attributes (uv)")

pl = S.scatter(GRID, count=3000, seed=5)
check("scattered points carry uv", pl.has(POINT, "uv"))
# on the source geometry uv is an affine function of P; fit it and apply to the scattered points -- with correct interpolation they must coincide
vP = np.asarray(GRID.get(POINT, "P"), np.float64)[GRID.vertex_point]
Av = np.c_[vP, np.ones(len(vP))]
coef = np.linalg.lstsq(Av, np.asarray(GRID.get(VERTEX, "uv"), np.float64),
                       rcond=None)[0]
Pp = np.asarray(pl.get(POINT, "P"), np.float64)
uvp = np.asarray(pl.get(POINT, "uv"), np.float64)
e_uv = float(np.abs(np.c_[Pp, np.ones(len(Pp))] @ coef - uvp).max())
check("scattered uv coincides everywhere with the affine uv field of the source", e_uv < 1e-5, e_uv)
nopt = GRID.copy(); nopt.remove(POINT, "uv")
pl_off = S.scatter(nopt, count=100, seed=5,
                   interpolate_vertex_attribs=False)
check("can be turned off (backwards compatible)", not pl_off.has(POINT, "uv"))
check("only present when on", S.scatter(nopt, count=100, seed=5).has(POINT, "uv"))

# seams: interpolating by point number produces a uv spanning the whole texture, by corner it does not
sc = S.scatter(seam, count=4000, seed=7)
su = np.asarray(sc.get(POINT, "uv"), np.float64)
check("no out-of-range uv interpolated across a uv seam (taken per corner, not per point)",
      su[:, 0].min() > -1e-6 and su[:, 0].max() < 1 + 1e-6,
      (su[:, 0].min(), su[:, 0].max()))


print("═" * 28, "Scatter from Map")

NN = 256
u2, v2 = uvgrid(NN)
RAMP = img_from(np.broadcast_to(u2, (NN, NN)))
MASKL = np.zeros((NN, NN)); MASKL[:, :NN // 2] = 1.0
IML = img_from(MASKL)

t0 = time.time()
pm = FM.scatter_from_map(GRID, IML, count=5000, seed=1)
dt = time.time() - t0
check("mask: point count reached", pm.npoints == 5000, pm.npoints)
# the upper bound is 0.5 plus one pixel: with bilinear, density has not dropped to 0 within the one pixel at the mask edge
check("mask: no point lands outside the mask (tolerance = 1 pixel)",
      float(np.asarray(pm.get(POINT, "uv"))[:, 0].max()) <= 0.5 + 1.0 / NN,
      float(np.asarray(pm.get(POINT, "uv"))[:, 0].max()))
check(f"speed {dt*1000:.0f} ms / 5000 points", dt < 3.0)

mus, mvs = [], []
for sd in (3, 11, 29, 47):
    p = FM.scatter_from_map(GRID, RAMP, count=40000, seed=sd)
    q2 = np.asarray(p.get(POINT, "uv"), np.float64)
    mus.append(q2[:, 0].mean()); mvs.append(q2[:, 1].mean())
mu, mv = float(np.mean(mus)), float(np.mean(mvs))
# with density ∝ u, E[u] = ∫u·u / ∫u = 2/3; the half pixel at the edge is clamped, bias ~ +0.0014
check("ramp density: E[u] = 2/3 (analytic)", abs(mu - 2 / 3) < 0.005, mu)
check("the axis independent of density must be 0.5 -- this one specifically catches correlated random streams",
      abs(mv - 0.5) < 0.004, mv)

# counterexample: make the rejection random stream the same as Scatter's seed
def correlated(seed, n):
    pts = S.scatter(GRID, count=n, seed=seed, randomize_order=False)
    q = np.asarray(pts.get(POINT, "uv"), np.float64)
    d = FM.sample_layer(RAMP, q)[:, 0]
    keep = np.random.default_rng(seed).random(len(d)) < d / d.max()
    return q[keep]
cq = correlated(3, 160000)
check("counterexample: a rejection stream with the same seed skews u to ~0.60 and v to ~0.38, the criterion catches it",
      abs(cq[:, 0].mean() - 2 / 3) > 0.05 and abs(cq[:, 1].mean() - 0.5) > 0.05,
      (cq[:, 0].mean(), cq[:, 1].mean()))

pa = FM.scatter_from_map(GRID, RAMP, count=2000, seed=9)
pb = FM.scatter_from_map(GRID, RAMP, count=2000, seed=9)
pc = FM.scatter_from_map(GRID, RAMP, count=2000, seed=10)
check("same seed is bit-identical",
      np.array_equal(np.asarray(pa.get(POINT, "P")),
                     np.asarray(pb.get(POINT, "P"))))
check("a different seed gives a different result",
      not np.array_equal(np.asarray(pa.get(POINT, "P")),
                         np.asarray(pc.get(POINT, "P"))))
dens = np.asarray(pa.get(POINT, "density"), np.float64)[:, 0]
uva = np.asarray(pa.get(POINT, "uv"), np.float64)
check("out_density records the sampled density",
      float(np.abs(dens - FM.sample_layer(RAMP, uva)[:, 0]).max()) < 1e-6)

DARK = img_from(np.zeros((32, 32)))
check("all black + floor=0: no point kept",
      FM.scatter_from_map(GRID, DARK, count=500, seed=1).npoints == 0)
check("all black + floor>0: degenerates to uniform scattering",
      FM.scatter_from_map(GRID, DARK, count=500, seed=1,
                          density_floor=0.2).npoints == 500)
pinv = FM.scatter_from_map(GRID, IML, count=3000, seed=1, invert=True)
check("invert flips the mask",
      float(np.asarray(pinv.get(POINT, "uv"))[:, 0].min()) >= 0.5 - 1.0 / NN,
      float(np.asarray(pinv.get(POINT, "uv"))[:, 0].min()))
check("count=0 gives empty geometry",
      FM.scatter_from_map(GRID, RAMP, count=0).npoints == 0)


print("═" * 28, "Trace: analytic shapes")

R0, RIN = 0.3, 0.2
NT = 256
ut, vt = uvgrid(NT)
rr = np.sqrt((ut - 0.5) ** 2 + (vt - 0.5) ** 2)
DISK = img_from(R0 - rr)                       # >0 inside the circle
tg = T.trace(DISK, threshold=0.0, simplify=0.0, size=1.0)
check("circle: one closed loop", tg.nprims == 1 and bool(tg.prim_closed[0]),
      (tg.nprims, tg.prim_closed))
per = float(tg.get(PRIM, "perimeter")[0, 0])
are = float(tg.get(PRIM, "area")[0, 0])
check("perimeter = 2πr, relative error < 1e-4",
      abs(per / (2 * np.pi * R0) - 1) < 1e-4, (per, 2 * np.pi * R0))
check("signed area = +πr² (outer contour counter-clockwise)",
      abs(are / (np.pi * R0 ** 2) - 1) < 1e-4, (are, np.pi * R0 ** 2))

ANN = img_from(np.minimum(0.4 - rr, rr - RIN))
ta = T.trace(ANN, threshold=0.0, simplify=0.0, size=1.0)
A = np.sort(np.asarray(ta.get(PRIM, "area"), np.float64).ravel())
check("annulus: two loops", ta.nprims == 2, ta.nprims)
check("the hole is clockwise (negative area), the outer ring counter-clockwise (positive area)",
      A[0] < 0 < A[1], A)
check("sum of signed areas = π(R²-r²), error < 1e-4",
      abs(A.sum() / (np.pi * (0.16 - RIN ** 2)) - 1) < 1e-4,
      (A.sum(), np.pi * (0.16 - RIN ** 2)))
check("all loops are closed", bool(ta.prim_closed.all()))

HALF2 = img_from(ut - 0.5)
th = T.trace(HALF2, threshold=0.0, simplify=0.0, size=1.0)
check("half plane: one open line, not closed",
      th.nprims == 1 and not bool(th.prim_closed[0]))
Ph = np.asarray(th.get(POINT, "P"), np.float64)
check("the open line lies exactly on x=0", float(np.abs(Ph[:, 0]).max()) < 1e-6)
check("both ends of the open line reach the image border",
      Ph[:, 1].max() > 0.49 and Ph[:, 1].min() < -0.49)

check("everything below the threshold -> empty geometry",
      T.trace(img_from(np.zeros((16, 16))), threshold=0.5).nprims == 0)
check("everything above the threshold -> empty geometry",
      T.trace(img_from(np.ones((16, 16))), threshold=0.5).nprims == 0)

ti = T.trace(DISK, threshold=0.0, simplify=0.0, size=1.0, invert=True)
check("invert swaps inside and outside -> the same loop, opposite orientation",
      abs(float(ti.get(PRIM, "area")[0, 0]) + are) < 1e-5,
      (float(ti.get(PRIM, "area")[0, 0]), -are))

areas = []
for thv in (-0.1, 0.0, 0.1, 0.2):
    g4 = T.trace(img_from(R0 - rr), threshold=thv, simplify=0.0, size=1.0)
    areas.append(float(np.asarray(g4.get(PRIM, "area")).sum()))
check("raising the threshold decreases the enclosed area monotonically",
      all(areas[i] > areas[i + 1] for i in range(3)),
      [round(a, 4) for a in areas])
check("the area at every level matches π(R-thr)²",
      max(abs(areas[i] / (np.pi * (R0 - t) ** 2) - 1)
          for i, t in enumerate((-0.1, 0.0, 0.1, 0.2))) < 2e-3)


print("═" * 28, "Trace: saddle points")

# a clean saddle criterion: two 2×2 squares touching diagonally at a single **grid point**.
# the four corners of that cell alternate exactly -> case 5. The center value (average of the corners) decides whether the two connect.
def diag_blobs(corner, case10=False):
    f = np.zeros((6, 6))
    if case10:
        f[3:5, 1:3] = 1.0; f[1:3, 3:5] = 1.0; f[2, 3] = corner
    else:
        f[1:3, 1:3] = 1.0; f[3:5, 3:5] = 1.0; f[3, 3] = corner
    return img_from(f)

for tag, c10 in (("case 5", False), ("case 10", True)):
    a = T.trace(diag_blobs(1.0, c10), threshold=0.5, simplify=0.0, size=1.0)
    b = T.trace(diag_blobs(0.9, c10), threshold=0.5, simplify=0.0, size=1.0)
    check(f"{tag}: center average 0.500 >= threshold -> the two connect, 1 closed loop",
          a.nprims == 1 and bool(a.prim_closed.all()), a.nprims)
    check(f"{tag}: center average 0.475 < threshold -> separated, 2 closed loops",
          b.nprims == 2 and bool(b.prim_closed.all()), b.nprims)
    check(f"{tag}: both decisions give the same total area (only the topology differs)",
          abs(float(np.asarray(a.get(PRIM, "area")).sum())
              - float(np.asarray(b.get(PRIM, "area")).sum())) < 0.02,
          (float(np.asarray(a.get(PRIM, "area")).sum()),
           float(np.asarray(b.get(PRIM, "area")).sum())))

# counterexample: ignore the center value and always use the SPLIT table, the connected case splits into two
_j5, _j10 = T._SADDLE_5_JOIN, T._SADDLE_10_JOIN
T._SADDLE_5_JOIN, T._SADDLE_10_JOIN = T._SADDLE_5_SPLIT, T._SADDLE_10_SPLIT
bad5 = T.trace(diag_blobs(1.0), threshold=0.5, simplify=0.0).nprims
bad10 = T.trace(diag_blobs(1.0, True), threshold=0.5, simplify=0.0).nprims
T._SADDLE_5_JOIN, T._SADDLE_10_JOIN = _j5, _j10
check("counterexample: a saddle that ignores the center value picks the wrong topology (1 loop becomes 2), the criterion catches it",
      bad5 == 2 and bad10 == 2, (bad5, bad10))
check("after restoring, the result is unchanged (the counterexample did not pollute later checks)",
      T.trace(diag_blobs(1.0), threshold=0.5, simplify=0.0).nprims == 1
      and T.trace(diag_blobs(1.0, True), threshold=0.5,
                  simplify=0.0).nprims == 1)

# two discs touching diagonally: the center decision determines whether they are one blob or two
def two_disks(gap, n=128):
    uu, vv2 = uvgrid(n)
    d1 = 0.2 - np.sqrt((uu - 0.35) ** 2 + (vv2 - 0.35) ** 2)
    d2 = 0.2 - np.sqrt((uu - 0.65 + gap) ** 2 + (vv2 - 0.65 + gap) ** 2)
    return img_from(np.maximum(d1, d2))
check("two separate discs -> 2 loops",
      T.trace(two_disks(-0.05), threshold=0.0, simplify=0.0).nprims == 2)
check("two overlapping discs -> 1 loop",
      T.trace(two_disks(0.10), threshold=0.0, simplify=0.0).nprims == 1)


print("═" * 28, "Trace: simplify / placement / uv")

raw = T.trace(DISK, threshold=0.0, simplify=0.0, size=1.0)
for tol in (0.5, 2.0, 8.0):
    sm = T.trace(DISK, threshold=0.0, simplify=tol, size=1.0)
    check(f"simplify={tol} reduces the point count ({raw.npoints} -> {sm.npoints})",
          sm.npoints < raw.npoints and sm.npoints >= 3)
    # max distance from the simplified polyline to the original points <= tolerance (in world units: 1 pixel = 1/N)
    Q = np.asarray(sm.get(POINT, "P"), np.float64)[:, [0, 1]]
    Praw = np.asarray(raw.get(POINT, "P"), np.float64)[:, [0, 1]]
    seg_a = Q
    seg_b = np.roll(Q, -1, 0)
    d = seg_b - seg_a
    L2 = (d * d).sum(1)
    w = Praw[:, None, :] - seg_a[None, :, :]
    t = np.clip((w * d[None]).sum(2) / np.where(L2 == 0, 1, L2)[None], 0, 1)
    dist = np.linalg.norm(w - t[:, :, None] * d[None], axis=2).min(1)
    check(f"  the RDP tolerance is a true upper bound (max {dist.max():.4f} <= {tol/NT:.4f})",
          dist.max() <= tol / NT + 1e-6)

ang = []
sm2 = T.trace(DISK, threshold=0.0, simplify=4.0, size=1.0)
Q = np.asarray(sm2.get(POINT, "P"), np.float64)[:, :2]
e1 = np.roll(Q, -1, 0) - Q
e0 = Q - np.roll(Q, 1, 0)
cosang = ((e0 * e1).sum(1)
          / (np.linalg.norm(e0, axis=1) * np.linalg.norm(e1, axis=1) + 1e-30))
check("closed-loop RDP leaves no sharp corner at the start point (max turn angle < 45°)",
      float(np.degrees(np.arccos(np.clip(cosang, -1, 1))).max()) < 45.0,
      float(np.degrees(np.arccos(np.clip(cosang, -1, 1))).max()))

WIDE = img_from(np.pad(np.ones((30, 60)), ((10, 10), (20, 20))))
tw = T.trace(WIDE, threshold=0.5, simplify=0.0, size=2.0)
Pw = np.asarray(tw.get(POINT, "P"), np.float64)
ext = Pw.max(0) - Pw.min(0)
check("keep_aspect: a 100x50 image -> x extent is 2× the y extent",
      abs(ext[0] / ext[1] - 2.0) < 0.05, ext[:2])
check("size is the world size of the long side (the rectangle occupies 60/100)",
      abs(ext[0] - 2.0 * 60 / 100) < 0.05, ext[0])
tw2 = T.trace(WIDE, threshold=0.5, simplify=0.0, size=2.0, keep_aspect=False)
Pw2 = np.asarray(tw2.get(POINT, "P"), np.float64)
e2 = Pw2.max(0) - Pw2.min(0)
check("with keep_aspect=False each axis fills independently",
      abs(e2[0] / e2[1] - (60 / 100) / (30 / 50)) < 0.05, e2[:2])

txz = T.trace(DISK, threshold=0.0, simplify=0.0, size=1.0, plane="xz")
Pz = np.asarray(txz.get(POINT, "P"), np.float64)
check("plane=xz lies on the y=0 plane", float(np.abs(Pz[:, 1]).max()) < 1e-6)
th2 = T.trace(DISK, threshold=0.0, simplify=0.0, size=1.0, height=1.5,
              center_x=2.0)
Ph2 = np.asarray(th2.get(POINT, "P"), np.float64)
check("height / center translation take effect",
      abs(float(Ph2[:, 2].mean()) - 1.5) < 1e-5
      and abs(float(Ph2[:, 0].mean()) - 2.0) < 1e-3)

tu = T.trace(DISK, threshold=0.0, simplify=0.0, size=1.0)
suv = np.asarray(tu.get(POINT, "uv"), np.float64)
back = FM.sample_layer(DISK, suv)[:, 0]
check("self-consistent: sampling the original image at the uv of the traced points gives the threshold",
      float(np.abs(back).max()) < 2e-3, float(np.abs(back).max()))

SPECK = img_from(np.maximum(R0 - rr,
                            0.02 - np.sqrt((ut - 0.9) ** 2
                                           + (vt - 0.9) ** 2)))
check("min_length filters out small stray loops",
      T.trace(SPECK, threshold=0.0, simplify=0.0, size=1.0).nprims == 2
      and T.trace(SPECK, threshold=0.0, simplify=0.0, size=1.0,
                  min_length=0.5).nprims == 1)
check("min_points filters short chains",
      T.trace(SPECK, threshold=0.0, simplify=6.0, size=1.0,
              min_points=40).nprims <= 1)
tc = T.trace(HALF2, threshold=0.0, simplify=0.0, size=1.0, close_open=True)
check("close_open forces open lines closed", bool(tc.prim_closed.all()))

t0 = time.time()
big = T.trace(img_from(np.sin(np.mgrid[0:1024, 0:1024][0] * 0.05)
                       * np.sin(np.mgrid[0:1024, 0:1024][1] * 0.05)),
              threshold=0.0, simplify=0.5)
dtb = time.time() - t0
check(f"1024² complex contours {dtb:.2f}s / {big.nprims} curves / {big.npoints} points",
      dtb < 8.0)


print("═" * 28, "Node layer")

import fakecomfy                                    # noqa: E402
from comfyui_pcg import nodes as ND                 # noqa: E402
NM = ND.NODE_CLASS_MAPPINGS
for k in ("PCG_AttribFromMap", "PCG_DisplaceFromMap", "PCG_ScatterFromMap",
          "PCG_Trace"):
    check(f"{k} registered and has a display name",
          k in NM and k in ND.NODE_DISPLAY_NAME_MAPPINGS)
    NM[k].INPUT_TYPES()

afm = NM["PCG_AttribFromMap"]()
go, txt = RUN(afm.run, GRID, RGB, "C", **{"class": VERTEX}, name="Cd", channels="",
                  decode="none", filter="bilinear", border="clamp",
                  scale=1.0, offset=0.0, blend=1.0, uv_attrib="uv",
                  uv_from="auto", uv_scale_u=1.0, uv_scale_v=1.0,
                  uv_offset_u=0.0, uv_offset_v=0.0, group="")
check("Attribute from Map node runs", go.get(VERTEX, "Cd").shape[1] == 3, txt)

dfm = NM["PCG_DisplaceFromMap"]()
(gd2,) = RUN(dfm.run, SPH, ONE, "C", channel=0, amount=0.1, midpoint=0.0,
                 decode="none", direction="normal", dir_x=0.0, dir_y=1.0,
                 dir_z=0.0, normal_attrib="N", filter="bilinear",
                 border="clamp", uv_attrib="uv", uv_from="auto",
                 uv_scale_u=1.0, uv_scale_v=1.0, uv_offset_u=0.0,
                 uv_offset_v=0.0, group="")
check("Displace from Map node runs",
      abs(float(np.linalg.norm(np.asarray(gd2.get(POINT, "P")),
                               axis=1).mean()) - 1.1) < 1e-4)

sfm = NM["PCG_ScatterFromMap"]()
gp, cnt = RUN(sfm.run, GRID, IML, "C", 0, channel=0, count=1200,
                  density_scale=1.0, density_floor=0.0, invert=False,
                  decode="none", oversample=4.0, max_rounds=6,
                  filter="bilinear", border="clamp", out_density="density",
                  uv_attrib="uv", uv_scale_u=1.0, uv_scale_v=1.0,
                  uv_offset_u=0.0, uv_offset_v=0.0, group="")
check("Scatter from Map node runs (the seed widget is called rand_seed)",
      cnt == 1200 and "rand_seed" in NM["PCG_ScatterFromMap"].INPUT_TYPES()
      ["required"], cnt)
check("no widget named seed (it would clash with ComfyUI's control)",
      "seed" not in NM["PCG_ScatterFromMap"].INPUT_TYPES()["required"])

trn = NM["PCG_Trace"]()
gc, nc = RUN(trn.run, DISK, layer="C", channel=0, threshold=0.0, invert=False,
                 simplify=0.5, min_points=3, min_length=0.0,
                 close_open=False, plane="xy", size=2.0, keep_aspect=True,
                 height=0.0, center_x=0.0, center_y=0.0, center_z=0.0,
                 add_uv=True, uv_attrib="uv")
check("Trace node runs", nc == 1 and gc.npoints > 8, (nc, gc.npoints))

print(f"\n{sum(OK)}/{len(OK)} passed")
