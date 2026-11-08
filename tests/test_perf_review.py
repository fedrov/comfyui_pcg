"""
pcg120: speed-ups from the code review. Every faster path is checked against brute force and against the path it
replaced (still in the code as the no-scipy fallback), plus a time budget the old code missed by a wide margin.

  1. spatial.nearest: KD-tree finish == level-grid fallback == brute force (meshes, points, Max Distance, a ground plane
     far larger than the rest); Ray minimum distance, 10k points on a 7.2k-face sphere: < 6 s (was 31 s, 3.8 GB)
  2. spatial.neighbors_within: KD-tree pairs == bucket pairs (random, self, exact-radius grid, duplicates);
     22.5k points with a tiny radius (Triangulate2D's weld): < 1 s (was 11 s)
  3. volume.signed_distance: in-band values == brute force; far_field=False == far_field=True inside the band, ±inf
     outside with the right sign; VDB from Polygons gives the same grid with and without the far field
  4. triangulate2d.delaunay: the Qhull path is exact Delaunay (empty circumcircles), has the same triangle count as the
     Python hull, keeps every point; a looser tolerance keeps the Python hull; 22.5k points: < 3 s (was 7 s)
  5. COP Noise panel: Tile U is disabled for Torus again (a repeated dict key had dropped the rule)
pcg122 (second round):
  6. PolyBevel: per-point corner lists and vectorized corner candidates -- 3.1k-face sphere < 1.2 s (was 3.4 s)
  7. Volume Rasterize Particles: batched small kernels == a per-particle reference; 10k particles < 0.5 s
  8. Voronoi Fracture: cuts that change nothing are skipped -- bit-identical, pieces == exact box ∩ cell
  9. Intersection Analysis: KD-tree candidate pairs == the all-pairs box test (same order); 16k faces < 1.5 s
"""
import os
import sys
import time

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

from comfyui_pcg.geo import spatial as S, volume as V, triangulate2d as T2, build, vdbsdf  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM, Geometry  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if extra == "" else "   " + str(extra)))


class no_scipy_spatial:
    """Make `from scipy.spatial import ...` fail, to run the fallback paths."""
    def __enter__(self):
        self.old = sys.modules.get("scipy.spatial", "missing")
        sys.modules["scipy.spatial"] = None
        return self

    def __exit__(self, *a):
        if self.old == "missing":
            del sys.modules["scipy.spatial"]
        else:
            sys.modules["scipy.spatial"] = self.old


def mesh(g):
    tri, _ = g.triangles(with_corners=True)
    return np.asarray(g.get(POINT, "P"), np.float64), np.asarray(tri, np.int64)


def brute_dist(Q, P, tri):
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    best = np.full(len(Q), np.inf)
    for t in range(len(tri)):
        a, b, c = A[t], B[t], C[t]
        ab, ac = np.broadcast_to(b - a, Q.shape), np.broadcast_to(c - a, Q.shape)
        e = lambda x, y: np.einsum("ij,ij->i", x, y)  # noqa: E731
        v, w = S.closest_on_tri(Q, ab, ac, e(ab, Q - a), e(ac, Q - a), e(ab, Q - b), e(ac, Q - b),
                                e(ab, Q - c), e(ac, Q - c))
        best = np.minimum(best, np.linalg.norm(a + v[:, None] * ab + w[:, None] * ac - Q, axis=1))
    return best


rng = np.random.default_rng(3)
sphere = build.sphere(radius=1.0, cols=40, rows=20)

print("\n[1. spatial.nearest]")
P, tri = mesh(sphere)
ground = np.array([[-20, -1.5, -20], [20, -1.5, -20], [20, -1.5, 20], [-20, -1.5, 20]], np.float64)
P2 = np.concatenate([P, ground])
tri2 = np.concatenate([tri, len(P) + np.array([[0, 1, 2], [0, 2, 3]])])
Q = rng.uniform(-3, 3, (1500, 3))
for nm, (PP, TT) in (("sphere", (P, tri)), ("sphere + a 40 m ground plane", (P2, tri2))):
    ref = brute_dist(Q, PP, TT)
    for md in (0.0, 0.4):
        _, d_kd, _, _ = S.closest_surface(Q, PP, TT, max_dist=md)
        with no_scipy_spatial():
            _, d_lv, _, _ = S.closest_surface(Q, PP, TT, max_dist=md)
        want = np.where(ref > md, np.inf, ref) if md else ref
        fin = np.isfinite(want)
        check(f"{nm}, max_dist={md}: KD path == brute force",
              np.array_equal(np.isfinite(d_kd), fin) and np.allclose(d_kd[fin], want[fin], rtol=0, atol=1e-12))
        check("  KD path == level-grid fallback (bit for bit)", np.array_equal(d_kd, d_lv))
pts = rng.uniform(-1, 1, (1500, 3))
Qp = rng.uniform(-2, 2, (800, 3))
ev = lambda qi, ti: (np.linalg.norm(Qp[qi] - pts[ti], axis=1), np.zeros((len(qi), 0)))  # noqa: E731
_, dp, _ = S.nearest(Qp, pts, pts, ev)
check("points as items: == brute force", np.allclose(dp, np.linalg.norm(Qp[:, None] - pts[None], axis=2).min(1),
                                                       rtol=0, atol=1e-12))

from comfyui_pcg.geo import raysop  # noqa: E402
big = build.sphere(radius=1.0, cols=120, rows=60)
gq = build.grid(size_x=2, size_z=2, rows=100, cols=100, center=(0, 2, 0))
t = time.time()
raysop.ray(gq, big, method="minimum_distance")
dt = time.time() - t
check("Ray minimum distance, 10k points on a 7.2k-face sphere: < 6 s (was 31 s)", dt < 6.0, f"{dt:.2f}s")

print("\n[2. spatial.neighbors_within]")
g = np.stack(np.meshgrid(np.arange(20), np.arange(20), [0.0]), -1).reshape(-1, 3) * 0.1
cases = [("random", rng.uniform(0, 1, (2000, 3)), rng.uniform(0, 1, (1500, 3)), 0.05),
         ("self", *(lambda X: (X, X))(rng.uniform(0, 1, (2000, 3))), 0.04),
         ("grid, radius == spacing (boundary pairs kept)", g, g, 0.1),
         ("duplicates", np.repeat(g, 2, 0), np.repeat(g, 2, 0), 1e-4)]
for nm, A_, B_, r in cases:
    a = S.neighbors_within(A_, B_, r)
    with no_scipy_spatial():
        b = S.neighbors_within(A_, B_, r)
    sa = set(zip(a[0].tolist(), a[1].tolist()))
    sb = set(zip(b[0].tolist(), b[1].tolist()))
    da = dict(zip(zip(a[0].tolist(), a[1].tolist()), a[2].tolist()))
    check(f"{nm}: KD pairs == bucket pairs ({len(sa)})", sa == sb and len(sa) == len(a[0])
          and all(abs(da[k] - v) < 1e-12 for k, v in zip(zip(b[0].tolist(), b[1].tolist()), b[2].tolist())))
check("  output sorted by (query, source)", np.all(np.diff(a[0] * (len(B_) + 1) + a[1]) > 0))
X = rng.uniform(0, 1, (22500, 3))
t = time.time()
S.neighbors_within(X, X, 1e-6)
dt = time.time() - t
check("22.5k points, tiny radius: < 1 s (was 11 s)", dt < 1.0, f"{dt:.3f}s")

print("\n[3. volume.signed_distance]")
vs = 0.08
lo = P.min(0) - 5 * vs
n = tuple(int(x) for x in np.ceil((P.max(0) - P.min(0) + 10 * vs) / vs) + 1)
band = 3.0
full = V.signed_distance(P, tri, lo, np.full(3, vs), n, band=band)
near = V.signed_distance(P, tri, lo, np.full(3, vs), n, band=band, far_field=False)
Xw = (lo + np.stack(np.meshgrid(np.arange(n[0]), np.arange(n[1]), np.arange(n[2]), indexing="ij"), -1)
      .reshape(-1, 3) * vs)
Xw = Xw.reshape(n[0], n[1], n[2], 3).transpose(2, 1, 0, 3).reshape(-1, 3)        # (z, y, x) order like the SDF
ref = brute_dist(Xw, P, tri).reshape(full.shape)
inb = ref <= band * vs
check("in-band |d| == brute force distance", np.allclose(np.abs(full[inb]), ref[inb], rtol=0, atol=1e-12))
Rw = np.linalg.norm(Xw.reshape(full.shape + (3,)), axis=-1)
clear = inb & (ref > 0.03)                    # away from the facets, where the tessellation and the unit sphere differ
check("sign: negative exactly inside the sphere", np.array_equal(full[clear] < 0, Rw[clear] < 1.0))
check("far_field=False == far_field=True inside the band", np.allclose(near[inb], full[inb], rtol=0, atol=1e-12))
check("  outside the band: ±inf with the far field's sign",
      np.all(np.isinf(near[~inb])) and np.array_equal(np.sign(near[~inb]), np.sign(full[~inb])))
check("  far_field=True is finite everywhere (negative control: the flag is what removes the far field)",
      np.all(np.isfinite(full)))
orig = V.signed_distance
V.signed_distance = lambda *a, **k: orig(*a, **{**k, "far_field": True})
try:
    ref_vdb = vdbsdf.from_polygons(sphere, voxel_size=vs)
finally:
    V.signed_distance = orig
new_vdb = vdbsdf.from_polygons(sphere, voxel_size=vs)
from comfyui_pcg.geo import vdb as _vdb  # noqa: E402
ra, rb = _vdb.grid(ref_vdb, _vdb.volume_prims(ref_vdb)[0]), _vdb.grid(new_vdb, _vdb.volume_prims(new_vdb)[0])
check("VDB from Polygons (no Fill Interior): same grid with and without the far field",
      ra[0].shape == rb[0].shape and np.allclose(ra[0], rb[0], rtol=0, atol=1e-12))

print("\n[4. triangulate2d.delaunay]")
XY = rng.uniform(0, 1, (2000, 2))
tq = T2.delaunay(XY)
with no_scipy_spatial():
    tp = T2.delaunay(XY)


def worst_incircle(XY, tri):
    a, b, c = XY[tri[:, 0]], XY[tri[:, 1]], XY[tri[:, 2]]
    worst = -np.inf
    for s in range(0, len(XY), 200):
        d = XY[s:s + 200, None, :]
        m = np.stack([a - d, b - d, c - d], 2)                                       # (q, t, 3, 2)
        l2 = (m ** 2).sum(-1)
        det = (m[..., 0, 0] * (m[..., 1, 1] * l2[..., 2] - l2[..., 1] * m[..., 2, 1])
               - m[..., 0, 1] * (m[..., 1, 0] * l2[..., 2] - l2[..., 1] * m[..., 2, 0])
               + l2[..., 0] * (m[..., 1, 0] * m[..., 2, 1] - m[..., 1, 1] * m[..., 2, 0]))
        worst = max(worst, float(det.max()))
    return worst


check("Qhull path: empty circumcircles (worst incircle <= 1e-12)", worst_incircle(XY, tq) <= 1e-12,
      worst_incircle(XY, tq))
check("  same triangle count as the Python hull", len(tq) == len(tp), (len(tq), len(tp)))
check("  every point used", len(np.unique(tq)) == len(XY))
check("  counter-clockwise",
      np.all((lambda u, v: u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])(XY[tq[:, 1]] - XY[tq[:, 0]],
                                                                  XY[tq[:, 2]] - XY[tq[:, 0]]) > 0))
called = []
_orig_q = T2._qhull_delaunay
T2._qhull_delaunay = lambda U: called.append(1) or _orig_q(U)
T2.delaunay(XY[:300], tol=1e-6)
T2.delaunay(XY[:300])
T2._qhull_delaunay = _orig_q
check("a looser tolerance keeps the Python hull; the default uses Qhull", called == [1], called)
from comfyui_pcg.geo import scatter as SC  # noqa: E402
sc = SC.scatter(build.grid(size_x=2, size_z=2, rows=300, cols=300), count=22500)
sc = sc[0] if isinstance(sc, tuple) else sc
t = time.time()
out = T2.triangulate2d(sc)
out = out[0] if isinstance(out, tuple) else out
dt = time.time() - t
check("Triangulate2D, 22.5k points: < 3 s (was 7 s)", dt < 3.0 and out.nprims > 40000, f"{dt:.2f}s {out.nprims}")

print("\n[5. panel]")
from comfyui_pcg import panel_specs_g4 as G4  # noqa: E402
spec = G4.SPECS["PCG_COPNoise"]["inputs"]
check("COP Noise: Tile U disabled for Torus", spec is not None and "torus" in str(spec["tile_u"].get("disable", "")),
      spec and spec.get("tile_u"))
check("  Tile U keeps its section and help", spec is not None and spec["tile_u"].get("section") == "Pattern"
      and "Loop Frames" in spec["tile_u"].get("help", ""))

# ═════════════════════════════════════════════ pcg122: second performance round
print("\n[6. PolyBevel]")
from comfyui_pcg.geo import ops as OPS  # noqa: E402
sph80 = build.sphere(radius=1.0, cols=80, rows=40)
t = time.time()
pb = OPS.polybevel(sph80)
dt = time.time() - t
check("PolyBevel of every edge, 3.1k-face sphere: < 1.2 s (was 3.4 s)", dt < 1.2 and pb.nprims > sph80.nprims, f"{dt:.2f}s")

print("\n[7. Volume Rasterize Particles]")
from comfyui_pcg.geo import volmore as VM, vdb as VDB  # noqa: E402
rng7 = np.random.default_rng(7)
n7 = 300
pts7 = Geometry.from_points(rng7.normal(0, 0.4, (n7, 3)).astype(np.float32))
pts7.set(POINT, "pscale", rng7.uniform(0.03, 0.4, (n7, 1)).astype(np.float32))   # small and large kernels mixed
pts7.set(POINT, "Cd", rng7.uniform(0, 1, (n7, 3)).astype(np.float32))
r7 = VM.rasterize_particles(None, pts7, filt="cubic", attributes="Cd", voxel_size=0.05)
dvox, o7, c7 = VDB.grid(r7, 0)
# reference: the straightforward per-particle loop over the whole grid
X7 = VDB.world_points(o7, c7, np.asarray(dvox).shape)
P7 = np.asarray(pts7.get(POINT, "P"), np.float64)
R7 = np.maximum(np.asarray(pts7.get(POINT, "pscale"), np.float64)[:, 0], np.min(c7))
ref = np.zeros(np.asarray(dvox).shape)
for p_, r_ in zip(P7, R7):
    ref += VM._kernel(np.linalg.norm(X7 - p_, axis=-1), r_, "cubic")
check("density == per-particle reference over the whole grid (small + large kernels)",
      np.allclose(np.asarray(dvox), ref, rtol=1e-6, atol=1e-6), float(np.abs(np.asarray(dvox) - ref).max()))
big = Geometry.from_points(rng7.normal(0, 0.5, (10000, 3)).astype(np.float32))
big.set(POINT, "pscale", np.full((10000, 1), 0.03, np.float32))
t = time.time()
VM.rasterize_particles(None, big, voxel_size=0.05)
dt = time.time() - t
check("10k small particles: < 0.5 s (per-particle loop: ~1 s at voxel 0.05, 5x slower at finer grids)", dt < 0.5,
      f"{dt:.2f}s")

print("\n[8. Voronoi Fracture: no-op cuts skipped]")
from comfyui_pcg.geo import voronoi as VO  # noqa: E402
from scipy.spatial import ConvexHull, HalfspaceIntersection  # noqa: E402
S8 = np.unique(np.random.default_rng(8).uniform(-0.5, 0.5, (30, 3)), axis=0)
boxg = build.box(divisions=(3, 3, 3))
fr = VO.fracture(boxg, Geometry.from_points(S8.astype(np.float32)))
P8 = np.asarray(fr.get(POINT, "P"), np.float64)
pc = np.asarray(fr.get(PRIM, "piece"))[:, 0]
err = []
for i in range(len(S8)):
    hs = [[1, 0, 0, -0.5], [-1, 0, 0, -0.5], [0, 1, 0, -0.5], [0, -1, 0, -0.5], [0, 0, 1, -0.5], [0, 0, -1, -0.5]]
    for j in range(len(S8)):
        if j != i:
            nn = S8[j] - S8[i]
            hs.append([*nn, -nn @ ((S8[i] + S8[j]) / 2)])
    vt = ConvexHull(HalfspaceIntersection(np.array(hs), S8[i]).intersections).volume
    ids = np.unique(np.concatenate([fr.prim_points(int(k)) for k in np.nonzero(pc == i)[0]]))
    err.append(abs(ConvexHull(P8[ids]).volume - vt))
check("every piece of a box == the exact box ∩ Voronoi cell (scipy halfspace intersection)", max(err) < 1e-6, max(err))
spn = build.sphere(radius=1.0, cols=40, rows=20)
rngv = np.random.default_rng(10)
pin = rngv.normal(size=(80, 3))
pin = pin / np.linalg.norm(pin, axis=1, keepdims=True) * 0.95 * rngv.uniform(0, 1, (80, 1)) ** (1 / 3)
seeds80 = Geometry.from_points(pin.astype(np.float32))
t = time.time()
fa = VO.fracture(spn, seeds80)
t_skip = time.time() - t
VO._SKIP_NOOP = False
try:
    t = time.time()
    fb = VO.fracture(spn, seeds80)
    t_all = time.time() - t
finally:
    VO._SKIP_NOOP = True


def _bits(g):
    return (g.npoints, g.nprims, g.vertex_point.tobytes(),
            tuple((c, k, np.asarray(v).tobytes()) for c in ("point", "vertex", "prim") for k, v in sorted(g.attribs[c].items())
                  if np.asarray(v).dtype != object),
            tuple((c, k, np.asarray(v).tobytes()) for c in ("point", "prim") for k, v in sorted(g.groups[c].items())))


check("80 seeds inside a sphere: skipping no-op cuts gives a bit-identical result", _bits(fa) == _bits(fb))
check("  and is faster (negative control: every cut performed)", t_skip < t_all, f"{t_skip:.2f}s vs {t_all:.2f}s")

print("\n[9. Intersection Analysis]")
from comfyui_pcg.geo import intersectanalysis as IA  # noqa: E402
s1 = build.sphere(radius=1.0, cols=100, rows=50)
s2 = build.sphere(radius=0.7, cols=80, rows=40, center=(0.8, 0, 0))
t = time.time()
o_kd, r_kd = IA.intersection_analysis(s1, s2)
dt = time.time() - t
# force the brute-force candidate path (the KD path is taken only above 4M box tests)
_orig_pairs = IA._candidate_pairs


def _brute(elo, ehi, tlo, thi, pad, chunk):
    step = max(1, chunk // max(len(tlo), 1))
    for s_ in range(0, len(elo), step):
        ei = np.arange(s_, min(s_ + step, len(elo)))
        ov = np.all((elo[ei, None] <= thi[None] + pad) & (ehi[ei, None] >= tlo[None] - pad), axis=2)
        ie, it = np.nonzero(ov)
        yield ei[ie], it


IA._candidate_pairs = _brute
try:
    o_bf, r_bf = IA.intersection_analysis(s1, s2)
finally:
    IA._candidate_pairs = _orig_pairs
check("KD candidate pairs == all-pairs box test (same points, same order, same attributes)",
      o_kd.npoints == o_bf.npoints > 0 and all(np.array_equal(np.asarray(o_kd.attribs["point"][k]),
                                                              np.asarray(o_bf.attribs["point"][k]))
                                               for k in o_kd.attribs["point"]), (r_kd, r_bf))
check("two spheres (10k + 6.4k faces): < 1.5 s (all pairs: ~16 s)", dt < 1.5, f"{dt:.2f}s")

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
