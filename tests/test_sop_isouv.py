"""
pcg77: IsoSurface, Remesh to Grid, HeightField Tile Split / Splice, UV Smooth,
Extract Silhouette.

Checks do not rely on the implementation itself:
  IsoSurface          unit sphere vertices after projection: | |p| - 1 | < 1e-6 (negative control: without projection the error is of order 1e-3);
                      normals radial; closed manifold, chi = 2; torus chi = 0; the $X notation is equivalent; the volume output values are f
  Remesh to Grid      all quads, closed manifold; points all on the original surface; volume error < 1%; translating by whole voxels
                      -> result translates exactly; a box whose faces lie on grid points is also manifold; linear attributes interpolated exactly
  Tile Split/Splice   split then splice is pixel-identical; weights sum to 1 everywhere; after adding different offsets to each tile,
                      neighbouring pixels across a feathered seam differ by <= offset difference / transition width (negative control: hard splice diff = offset difference)
  UV Smooth           on a plane the cotangent harmonic solution exactly recovers linear uv (negative control: uniform cannot); seams are not welded;
                      boundary points and points outside the group do not move
  Extract Silhouette  cube seen head-on = 1x1 square (4 points), seen along the diagonal = hexagon of area √3;
                      two overlapping / touching boxes = union area; torus = outer ring + hole; sphere ≈ π;
                      contour on the equator
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

from comfyui_pcg.geo import isosurface as IS            # noqa: E402
from comfyui_pcg.geo import uvsmooth as UVS             # noqa: E402
from comfyui_pcg.geo import silhouette as SI            # noqa: E402
from comfyui_pcg.geo.cop import tiles as TL             # noqa: E402
from comfyui_pcg.geo.cop import CopImage                # noqa: E402
from comfyui_pcg.geo.cop.pixel import getn              # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.topology import topology           # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, VERTEX  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

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


def Pd(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def euler(g):
    t = topology(g)
    return g.npoints - t.nedges + g.nprims


def manifold(g):
    t = topology(g)
    return set(np.unique(t.edge_count).tolist()) == {2}


def volume(g):
    tri = np.asarray(g.triangles(), np.int64)
    P = Pd(g)
    return float(np.einsum("ij,ij->i", P[tri[:, 0]], np.cross(P[tri[:, 1]],
                                                            P[tri[:, 2]])).sum()
                 / 6)


rng = np.random.default_rng(0)
# ═══════════════════════════════════════════════════════ IsoSurface
sec("IsoSurface")
g, r = IS.isosurface(divisions=(40, 40, 40))
P = Pd(g)
check("unit sphere: after projection all vertices on |p| = 1", np.abs(np.linalg.norm(P, axis=1) - 1).max()
      < 1e-6, np.abs(np.linalg.norm(P, axis=1) - 1).max())
g0, _ = IS.isosurface(divisions=(40, 40, 40), project=False)
e0 = np.abs(np.linalg.norm(Pd(g0), axis=1) - 1).max()
check("  negative control: without projection the error is of order 1e-3 (surface nets vertices average within the cell)", e0 > 1e-4, e0)
N = np.asarray(g.get(POINT, "N"), np.float64)
check("normal = gradient direction (radial on a sphere)", np.abs(np.einsum("ij,ij->i", N, P) - 1).max()
      < 1e-4)
check("closed manifold, all quads, chi = 2", manifold(g) and euler(g) == 2 and
      set(g.prim_sizes().tolist()) == {4}, (euler(g), r["points"]))
fc = np.array([Pd(g)[g.prim_points(i)].mean(0) for i in range(g.nprims)])
fn = np.array([np.cross(*(Pd(g)[g.prim_points(i)][[1, 2]] -
                          Pd(g)[g.prim_points(i)][0])) for i in range(g.nprims)])
check("faces point outward (f > 0 is outside)", (np.einsum("ij,ij->i", fn, fc) > 0).all())
g2, _ = IS.isosurface(divisions=(40, 40, 40),
                      expression="sqrt($X*$X + $Y*$Y + $Z*$Z) - 1")
check("$X $Y $Z notation is equivalent", np.abs(Pd(g2) - P).max() < 1e-6)
gi, _ = IS.isosurface(divisions=(40, 40, 40), iso=-0.5)
check("Iso = -0.5: sphere of radius 0.5", np.abs(np.linalg.norm(Pd(gi), axis=1) - 0.5).max()
      < 1e-6)
gj, _ = IS.isosurface(divisions=(40, 40, 40), iso=-0.5, project=False)
check("  also radius 0.5 without projection (Iso is subtracted when extracting the surface)",
      np.abs(np.linalg.norm(Pd(gj), axis=1) - 0.5).max() < 5e-3)
tor = "pow(sqrt(@P.x*@P.x + @P.z*@P.z) - 1, 2) + @P.y*@P.y - 0.09"
gt, rt = IS.isosurface((-1.5, -0.5, -1.5), (1.5, 0.5, 1.5), (60, 20, 60), tor)
Pt = Pd(gt)
res = (np.hypot(Pt[:, 0], Pt[:, 2]) - 1) ** 2 + Pt[:, 1] ** 2 - 0.09
check("torus: chi = 0, vertices on the implicit surface", euler(gt) == 0 and manifold(gt) and
      np.abs(res).max() < 1e-6, (euler(gt), np.abs(res).max()))
gv, rv = IS.isosurface((-1, -1, -1), (1, 1, 1), (4, 4, 4), "@P.x + 2*@P.y",
                       output="volume")
vox = gv.pdata(0, "voxels")
xs = np.linspace(-1, 1, 5)
Z, Y, X = np.meshgrid(xs, xs, xs, indexing="ij")
check("Output = volume: voxel values are f", gv.prim_type[0] == 2 and
      np.abs(vox - (X + 2 * Y)).max() < 1e-6)
err("reversed Bound raises", lambda: IS.isosurface((1, 1, 1), (0, 0, 0)), "Bound")
err("empty expression raises", lambda: IS.isosurface(expression=" "), "is empty")

# ═══════════════════════════════════════════════════════ Remesh to Grid
sec("Remesh to Grid")
sph = build.sphere(1, 32, 16)
sph.set(POINT, "Cd", Pd(sph).astype(np.float32))
o, r = IS.remesh_to_grid(sph, 0.1)
from comfyui_pcg.geo.spatial import closest_surface, tri_soup  # noqa: E402
tri0, _, _ = tri_soup(sph)
_, _, pos, _ = closest_surface(Pd(o), Pd(sph), tri0)
check("all quads, closed manifold, chi = 2", set(o.prim_sizes().tolist()) == {4} and
      manifold(o) and euler(o) == 2, r)
check("points all on the original surface", np.linalg.norm(pos - Pd(o), axis=1).max() < 1e-5)
v0, v1 = volume(sph), volume(o)
check("volume error < 1%", abs(v1 - v0) / v0 < 0.01, (round(v0, 4), round(v1, 4)))
check("point attribute (Cd = P, linear) interpolated exactly", np.abs(o.get(POINT, "Cd") - Pd(o)).max()
      < 1e-5)
sh = sph.copy()
sh.set(POINT, "P", (Pd(sph) + [0.3, -0.2, 0.7]).astype(np.float32))
oa, _ = IS.remesh_to_grid(sph, 0.1, project=False)
ob_, _ = IS.remesh_to_grid(sh, 0.1, project=False)
check("move by whole voxels: same topology, points extracted on the voxel grid translate exactly (grid aligned)",
      np.array_equal(ob_.vertex_point, oa.vertex_point) and
      np.abs(Pd(ob_) - Pd(oa) - [0.3, -0.2, 0.7]).max() < 1e-6)
o2, _ = IS.remesh_to_grid(sh, 0.1)
check("  after projection also within 1e-3 (for points inside the sphere equidistant to two faces, float32 rounding can switch faces)",
      np.abs(Pd(o2) - Pd(o) - [0.3, -0.2, 0.7]).max() < 1e-3)
on, _ = IS.remesh_to_grid(sph, 0.1, project=False, smooth=0)   # raw surface nets points
_, _, pn, _ = closest_surface(Pd(on), Pd(sph), tri0)
dn = np.linalg.norm(pn - Pd(on), axis=1).max()
check("  negative control: without projection points are of order 1e-2 off the original surface", dn > 1e-3, dn)
bx = build.box((1, 1, 1))
bo = build.box((1, 1, 1), center=(0.03, 0.02, 0.01))
onq, _ = IS.remesh_to_grid(bo, 0.1, project=False, smooth=0)  # since pcg90 Smooth also runs without projection
Pq = Pd(onq)
top = np.abs(Pq[:, 1] - 0.52) < 1e-5
fx = (Pq[top][:, [0, 2]] / 0.1) % 1.0
inner = (np.abs(Pq[top][:, 0] - 0.03) < 0.4) & (np.abs(Pq[top][:, 2] - 0.01) < 0.4)
check("grid aligned in world coordinates to whole multiples of Voxel Size (does not follow the object): for a box moved by (0.03, 0.02, 0.01)"
      " the x, z of the points in the middle of the top face are exactly at world cell centers (≡ 0.05 mod 0.1)",
      inner.sum() > 20 and np.abs(fx[inner] - 0.5).max() < 1e-4,
      (int(inner.sum()), np.abs(fx[inner] - 0.5).max() if inner.any() else None))
ob, rb = IS.remesh_to_grid(bx, 0.1)
check("a box whose faces lie exactly on grid points (1 m with 0.1): still manifold, chi = 2",
      manifold(ob) and euler(ob) == 2 and rb["nonmanifold_edges"] == 0, rb)


def edge_cv(g):
    t = topology(g)
    L = np.linalg.norm(Pd(g)[t.edge_points[:, 0]] - Pd(g)[t.edge_points[:, 1]], axis=1)
    return L.std() / L.mean()


o0, _ = IS.remesh_to_grid(sph, 0.1, smooth=0)
o5, _ = IS.remesh_to_grid(sph, 0.1, smooth=5)
check("Smooth makes edge lengths more even (smaller coefficient of variation)", edge_cv(o5) < edge_cv(o0),
      (round(edge_cv(o0), 3), round(edge_cv(o5), 3)))
err("Voxel Size cannot be 0", lambda: IS.remesh_to_grid(sph, 0), "Voxel Size")

# ═══════════════════════════════════════════════════════ Tile Split / Splice
sec("HeightField Tile Split / Splice")
H, W = 67, 90
img = CopImage(W, H)
from comfyui_pcg.geo.cop.pixel import put  # noqa: E402
yy, xx = np.mgrid[0:H, 0:W]
put(img, "height", np.sin(xx * 0.1) + np.cos(yy * 0.13))
put(img, "C", rng.uniform(0, 1, (H, W, 3)))
for cols, rows, ov in ((2, 2, 8), (3, 2, 5), (4, 3, 0), (1, 3, 7)):
    seq = TL.tile_split(img, cols, rows, ov)
    back = TL.tile_splice(seq, cols, rows, ov, 1.0)
    e = max(np.abs(getn(back, n) - getn(img, n)).max() for n in ("height", "C"))
    check(f"{cols}x{rows} tiles, overlap {ov}: split then splice is pixel-identical", len(seq) == cols * rows
          and (back.xres, back.yres) == (W, H) and e < 1e-6, e)
seq = TL.tile_split(img, 3, 2, 6)
check("tile size: core + overlap on both sides (not at image edges)", (seq[0].xres, seq[0].yres) == (30 + 6, 33 + 6)
      and (seq[1].xres, seq[1].yres) == (30 + 12, 33 + 6))
ones = []
for t in seq:
    u = CopImage(t.xres, t.yres)
    put(u, "height", np.ones((t.yres, t.xres)))
    ones.append(u)
wsum = getn(TL.tile_splice(ones, 3, 2, 6, 1.0), "height")
check("weights sum to 1 everywhere (every tile is constant 1 -> spliced result is 1 everywhere)",
      np.abs(wsum - 1).max() < 1e-6)
off = []
for k, t in enumerate(seq):
    u = CopImage(t.xres, t.yres)
    put(u, "height", getn(t, "height") + 0.5 * k)
    off.append(u)
hs = getn(TL.tile_splice(off, 3, 2, 6, 1.0), "height")[..., 0]
hh = getn(TL.tile_splice(off, 3, 2, 6, 0.0), "height")[..., 0]
base = getn(img, "height")[..., 0]
jf = max(np.abs(np.diff(hs - base, axis=1)).max(), np.abs(np.diff(hs - base, axis=0)).max())
jh = max(np.abs(np.diff(hh - base, axis=1)).max(), np.abs(np.diff(hh - base, axis=0)).max())
check("different offsets added to each tile (neighbours differ by at most 1.5): after feathering neighbouring pixels jump at most ~ 1.5 x 1.5/12",
      jf < 1.5 * 1.5 / 12 * 1.05, round(jf, 4))
check("  negative control: Feather = 0 hard splice, jumps straight by 1.5 at the seam", abs(jh - 1.5) < 1e-6, jh)
sq20 = TL.tile_split(img, 3, 2, 20)
o20 = []
for k, t in enumerate(sq20):
    u = CopImage(t.xres, t.yres)
    put(u, "height", getn(t, "height") + 0.5 * k)
    o20.append(u)
h20 = getn(TL.tile_splice(o20, 3, 2, 20, 1.0), "height")[..., 0]
d2 = np.abs(np.diff(h20 - base, 2, axis=0)).max()
check("  the transition is smoothstep (slope continuous at both ends): with overlap 20 the vertical second difference <= 6·1.5/40^2 ≈ 0.0056"
      " (a linear transition has kinks at both ends, giving 1.5/40/2 ≈ 0.019)", d2 < 0.01, round(d2, 4))
err("tile count does not match columns x rows: raises", lambda: TL.tile_splice(seq, 2, 2, 6), "Columns")
err("parameters differ from those used to split: raises", lambda: TL.tile_splice(seq, 3, 2, 4), "does not match")

# ═══════════════════════════════════════════════════════ UV Smooth
sec("UV Smooth")
pts = rng.uniform(0, 1, (160, 2))
bd = np.array([[x, y] for x in np.linspace(0, 1, 9) for y in (0.0, 1.0)] +
              [[x, y] for y in np.linspace(0, 1, 9)[1:-1] for x in (0.0, 1.0)])
Q2 = np.vstack([bd, pts])
from comfyui_pcg.geo.triangulate2d import delaunay  # noqa: E402
T = np.asarray(delaunay(Q2))
P3 = np.c_[Q2[:, 0], np.zeros(len(Q2)), Q2[:, 1]]
flat = Geometry.from_mesh(P3.astype(np.float32), T.astype(np.int32))
lin = np.c_[2 * Q2[:, 0] + 0.3 * Q2[:, 1], -0.5 * Q2[:, 0] + Q2[:, 1]]
noisy = lin.copy()
isb = np.arange(len(Q2)) < len(bd)
noisy[~isb] += rng.normal(0, 0.05, ((~isb).sum(), 2))
flat.set(VERTEX, "uv", np.c_[noisy[flat.vertex_point], np.zeros(flat.nvertices)]
         .astype(np.float32))
o, r = UVS.uv_smooth(flat, solve="harmonic", weights="cotangent")
uvo = np.asarray(o.get(VERTEX, "uv"), np.float64)[:, :2]
ec = np.abs(uvo - lin[flat.vertex_point]).max()
check("planar mesh + cotangent harmonic: linear uv recovered exactly (linear precision)", ec < 1e-5, ec)
o, _ = UVS.uv_smooth(flat, solve="harmonic", weights="uniform")
eu = np.abs(np.asarray(o.get(VERTEX, "uv"))[:, :2] - lin[flat.vertex_point]).max()
check("  negative control: uniform weights cannot recover it", eu > 1e-3, eu)
o, _ = UVS.uv_smooth(flat, iterations=4000, strength=1.0, weights="cotangent")
er = np.abs(np.asarray(o.get(VERTEX, "uv"))[:, :2] - lin[flat.vertex_point]).max()
check("with enough iterations relax converges to the same solution", er < 1e-3, er)
check("boundary does not move", np.abs(np.asarray(o.get(VERTEX, "uv"))[:, :2] -
                    noisy[flat.vertex_point])[isb[flat.vertex_point]].max() < 1e-7)
o, _ = UVS.uv_smooth(flat, strength=0.0)
check("Strength 0 equals no change (only float32 rounding differs)",
      np.abs(np.asarray(o.get(VERTEX, "uv"))[:, :2] - noisy[flat.vertex_point]).max()
      < 1e-6)
flat.set_group(POINT, "left", Q2[:, 0] < 0.5)
o, _ = UVS.uv_smooth(flat, solve="harmonic", group="left")
uvg = np.asarray(o.get(VERTEX, "uv"))[:, :2]
right = Q2[flat.vertex_point, 0] >= 0.5
check("points outside the group do not move", np.abs(uvg[right] - noisy[flat.vertex_point][right]).max() < 1e-6)
tb = build.tube(1, 1, 2, cols=12, rows=6)
Pt = Pd(tb)
ang = np.arctan2(Pt[:, 2], Pt[:, 0]) % (2 * np.pi)
uv = []
for i in range(tb.nprims):
    a = ang[tb.prim_points(i)]
    if a.max() - a.min() > np.pi:
        a = np.where(a < np.pi, a + 2 * np.pi, a)
    uv += [[x / (2 * np.pi), (y + 1) / 2, 0] for x, y in zip(a, Pt[tb.prim_points(i), 1])]
uv = np.asarray(uv)
uv[:, 0] += rng.normal(0, 0.01, len(uv)) * 0
tb.set(VERTEX, "uv", uv.astype(np.float32))
tj = tb.copy()
U2 = uv.copy()
mid = (Pt[tb.vertex_point, 1] > -0.99) & (Pt[tb.vertex_point, 1] < 0.99)
jit = rng.normal(0, 0.02, (tb.npoints, 2))
U2[mid, :2] += jit[tb.vertex_point[mid]]
tj.set(VERTEX, "uv", U2.astype(np.float32))
o, r = UVS.uv_smooth(tj, solve="harmonic")
Uo = np.asarray(o.get(VERTEX, "uv"), np.float64)
seam = np.abs(ang[tb.vertex_point]) < 1e-6
sp_ = tb.vertex_point[seam]
pair = {}
for p_, u_ in zip(sp_.tolist(), Uo[seam, 0].tolist()):
    pair.setdefault(p_, set()).add(round(u_, 6))
check("seams not welded: the two wedges of each point on the seam still differ by exactly 1 (u and u + 1)",
      all(len(v_) == 2 and abs(max(v_) - min(v_) - 1) < 1e-6 for v_ in pair.values())
      and r["wedges"] == tb.npoints + 6, (r["wedges"], list(pair.values())[:2]))
free_mid = mid & ~seam
check("  points off the seam really were smoothed (jitter removed: u back to the value from the angle)",
      np.abs(Uo[free_mid, 0] - uv[free_mid, 0]).max() < 0.01 and
      np.abs(U2[free_mid, 0] - uv[free_mid, 0]).max() > 0.03)
ptg = flat.copy()
ptg.attribs[VERTEX].pop("uv")
ptg.set(POINT, "uv", np.c_[noisy, np.zeros(len(noisy))].astype(np.float32))
o, _ = UVS.uv_smooth(ptg, solve="harmonic")
check("point-class uv works too", np.abs(np.asarray(o.get(POINT, "uv"))[:, :2] - lin).max()
      < 1e-5)
err("harmonic without fixed points: raises", lambda: UVS.uv_smooth(flat, solve="harmonic",
                                                  pin_boundary=False), "collapses")
err("no uv: raises", lambda: UVS.uv_smooth(build.box(), "nouv"), "No numeric")

# ═══════════════════════════════════════════════════════ Extract Silhouette
sec("Extract Silhouette")
bx = build.box((1, 1, 1), divisions=(3, 3, 3))
o, r = SI.extract_silhouette(bx, (0, -1, 0))
check("cube seen head-on: 1 loop, 4 points, area 1, counter-clockwise", r["loops"] == 1 and
      o.npoints == 4 and abs(r["area"] - 1) < 1e-6 and o.get(PRIM, "hole")[0, 0] == 0,
      r)
check("  points on the projection plane (through origin, perpendicular to the view direction)", np.abs(Pd(o)[:, 1]).max() < 1e-6)
o, r = SI.extract_silhouette(bx, (0, -1, 0), origin=(0, 2, 0))
check("  origin moved to y = 2: the silhouette moves to y = 2 too", np.abs(Pd(o)[:, 1] - 2).max() < 1e-6)
d = np.array([1, 1, 1]) / math.sqrt(3)
o, r = SI.extract_silhouette(bx, tuple(d))
check("seen along the diagonal: hexagon, area = |nx|+|ny|+|nz| = √3", o.npoints == 6 and
      abs(r["area"] - math.sqrt(3)) < 1e-6, r)
two = ops.merge(build.box((1, 1, 1)), build.box((1, 1, 1), center=(0.5, 0, 0.5)))
o, r = SI.extract_silhouette(two, (0, -1, 0))
check("two overlapping boxes: union is one loop, area 1 + 1 - 0.25 = 1.75, 8 points",
      r["loops"] == 1 and abs(r["area"] - 1.75) < 1e-6 and o.npoints == 8, r)
L_ = ops.merge(build.box((1, 1, 1)), build.box((1, 1, 1), center=(1, 0, 0.7)))
o, r = SI.extract_silhouette(L_, (0, -1, 0))
check("two boxes touching along part of an edge (collinear edges partly overlapping): one loop, area 2, 8 points",
      r["loops"] == 1 and abs(r["area"] - 2) < 1e-6 and o.npoints == 8, r)
tres = []
for cx, cz in ((0.5, 1.0), (-0.5, 1.0), (0.5, -1.0), (-0.5, -1.0), (1.0, 0.5),
               (-1.0, 0.5), (1.0, -0.5), (-1.0, -0.5)):
    for order in (0, 1):
        pa, pb = build.box((1, 1, 1)), build.box((1, 1, 1), center=(cx, 0, cz))
        T_ = ops.merge(pa, pb) if order == 0 else ops.merge(pb, pa)
        o, r = SI.extract_silhouette(T_, (0, -1, 0))
        tres.append(r["loops"] == 1 and abs(r["area"] - 2) < 1e-6 and o.npoints == 8)
check("T junction: one box's corner lands exactly in the middle of the other's edge (8 directions x 2 input orders): "
      "always one loop, area 2, 8 points", all(tres), tres)
sep = ops.merge(build.box((1, 1, 1)), build.box((1, 1, 1), center=(3, 0, 0)))
o, r = SI.extract_silhouette(sep, (0, -1, 0))
check("two separate boxes: two loops", r["loops"] == 2 and abs(r["area"] - 2) < 1e-6)
tr = build.torus(1, 0.3, 12, 24)
o, r = SI.extract_silhouette(tr, (0, -1, 0))
ar = o.get(PRIM, "area")[:, 0]
hole = o.get(PRIM, "hole")[:, 0]
Pt = Pd(tr)
Ro, Ri = np.hypot(Pt[:, 0], Pt[:, 2]).max(), np.hypot(Pt[:, 0], Pt[:, 2]).min()
ngon = lambda R: 0.5 * 24 * R * R * math.sin(2 * math.pi / 24)   # noqa: E731
check("torus seen from above: outer ring + one hole, area = outer 24-gon - inner 24-gon",
      r["loops"] == 2 and sorted(hole.tolist()) == [0, 1] and
      abs(ar[hole == 0][0] - ngon(Ro)) < 1e-4 and abs(ar[hole == 1][0] - ngon(Ri))
      < 1e-4, (ar, ngon(Ro), ngon(Ri)))
sp = build.sphere(1, 64, 48)
o, r = SI.extract_silhouette(sp, (0.3, -0.8, 0.5))
check("sphere seen at an angle: one loop, area ≈ π (diff < 1%)", r["loops"] == 1 and
      abs(r["area"] - math.pi) / math.pi < 0.01, r["area"])
o, r = SI.extract_silhouette(build.grid(2, 2, 3, 3), (1, 0, 0))
check("plane edge-on to the view direction: projected area 0, no silhouette", r["loops"] == 0)
o, r = SI.extract_silhouette(build.sphere(1, 24, 17), (0, -1, 0), mode="contour")
check("contour: the sphere's equator (y = 0), one closed loop", r["curves"] == 1 and
      o.prim_closed[0] and np.abs(Pd(o)[:, 1]).max() < 1e-6 and o.npoints == 24)
gg = build.grid(2, 2, 5, 5)
o, r = SI.extract_silhouette(gg, (0, -1, 0), mode="contour")
o2, r2 = SI.extract_silhouette(gg, (0, -1, 0), mode="contour",
                               include_boundary=False)
check("contour on an open mesh: Include Boundary adds the open edges (16), off gives none",
      r["curves"] == 1 and o.npoints == 16 and r2["curves"] == 0)
o3, r3 = SI.extract_silhouette(gg, (0, 1, 0), mode="contour")
check("  mesh facing away from the viewer: no front side, open edges do not count as contour either", r3["curves"] == 0)
th = math.radians(30)
Rr = np.array([[math.cos(th), 0, -math.sin(th)], [0, 1, 0],
               [math.sin(th), 0, math.cos(th)]])
b1 = build.box((1, 1, 1))
b2 = b1.copy()
b2.set(POINT, "P", (Pd(b1) @ Rr.T).astype(np.float32))
dv = tuple(Rr @ np.array([0, 0, -1.0]))
o, r = SI.extract_silhouette(b2, dv, mode="contour")
check("box rotated by 30° (float32) seen facing one side: contour is that face's 4 edges"
      " (side faces have projected area of order 1e-8, treated as edge-on)", r["curves"] == 1 and o.npoints == 4, r)
o, r = SI.extract_silhouette(b2, dv)
check("  outline: front and back faces project with a 1e-8 difference, merged into one square (1 loop, 4 points)",
      r["loops"] == 1 and o.npoints == 4 and abs(r["area"] - 1) < 1e-6, r)

# ═══════════════════════════════════════════════════════ nodes
sec("nodes")
NEW = {"PCG_IsoSurface": "PCG/generate", "PCG_RemeshToGrid": "PCG/modify",
       "PCG_UVSmooth": "PCG/uv", "PCG_ExtractSilhouette": "PCG/generate",
       "PCG_COPTileSplit": "PCG/cop", "PCG_COPTileSplice": "PCG/cop"}
check("all 6 nodes registered, category correct",
      all(k in MAP and MAP[k].CATEGORY == v for k, v in NEW.items()))
bad = [k for k in NEW for nm_ in MAP[k].INPUT_TYPES()["required"]
       if nm_ in ("seed", "class")]
check("no widget named seed / class", not bad, bad)


def unwrap(r):
    return tuple(r["result"]) if isinstance(r, dict) else r


def defaults(cls, **over):
    kw = {}
    for nm_, spec in cls.INPUT_TYPES()["required"].items():
        if nm_ in over:
            kw[nm_] = over[nm_]
        elif isinstance(spec[0], list):
            kw[nm_] = spec[1].get("default", spec[0][0]) if len(spec) > 1 \
                else spec[0][0]
        elif len(spec) > 1 and "default" in spec[1]:
            kw[nm_] = spec[1]["default"]
    kw.update({k: v for k, v in over.items() if k not in kw})
    return kw


bad = []
seq4 = TL.tile_split(img, 2, 2, 16)
for k, kw in {"PCG_IsoSurface": {}, "PCG_RemeshToGrid": dict(geo=sph),
              "PCG_UVSmooth": dict(geo=flat), "PCG_ExtractSilhouette": dict(geo=bx),
              "PCG_COPTileSplit": dict(cop=img),
              "PCG_COPTileSplice": dict(seq=seq4)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if r[0] is None:
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 6 nodes run with default parameters (with the needed inputs connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
