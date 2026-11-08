"""
pcg72: volume batch -- Volume / Volume Blur / Volume Mix / Volume Resample /
Volume Wrangle / Volume Reshape SDF, plus Convert's exact SDF.

The reference does not rely on the implementation itself:
  SDF       in the narrow band, compared point by point against brute force (each grid point finds the nearest of all triangles, spatial.closest_surface);
            sign compared point by point against ray-voting inside_mesh (sphere, tilted torus, cuboid, thin slab);
            open meshes fall back to unsigned distance
  Blur      constant field unchanged; linear field unchanged in the interior (symmetric kernel); second moment of the impulse response = σ² (world units,
            same in x / z on an anisotropic grid); two Gaussians = one with σ√2
  Mix       on the same grid equals the formula bit for bit; on different grids linear fields are exact; union of two spheres against the analytic min
  Resample  linear fields exact at any resolution; integer refinement keeps old grid points bit for bit
  Wrangle   formula checked against numpy by hand; volsample reads another volume
  Reshape   sphere dilated by d has its zero at r = 1 + d; SDF×3 redistance back to an SDF; open shaves off thin spikes,
            close fills narrow gaps, large shapes unchanged
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

from comfyui_pcg.geo import volume as VO                # noqa: E402
from comfyui_pcg.geo import volops as VP                # noqa: E402
from comfyui_pcg.geo import attribsample as AS          # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import spatial as SP               # noqa: E402
from comfyui_pcg.geo.inside import inside_mesh          # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402
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


def info(g, i=0):
    v, o, c = VO.volume_info(g, i)
    return np.asarray(v, np.float64), o, c


def grid_pts(v, o, c):
    return VP._grid_points(v, o, c)[0]


def with_field(res, size, center, fn, name=""):
    g = VP.create_volume(res, size, center, 0.0, False, name)
    v, o, c = info(g)
    Q = grid_pts(v, o, c)
    g.set_pdata(0, "voxels", fn(Q).reshape(v.shape).astype(np.float32))
    return g


rng = np.random.default_rng(72)

# ═══════════════════════════════════════════════════════ Convert's exact SDF
sec("Convert: exact SDF")
def prism(apex_deg, L=1.0):
    """A right prism whose cross section is an isosceles triangle with apex angle apex_deg (a very sharp edge)."""
    h = 1.0
    w = h * math.tan(math.radians(apex_deg) / 2)
    tri2 = [(0, h / 2), (-w, -h / 2), (w, -h / 2)]
    P_ = [(x, y, z) for z in (-L / 2, L / 2) for x, y in tri2]
    F_ = [[0, 1, 2], [5, 4, 3], [0, 3, 4, 1], [1, 4, 5, 2], [2, 5, 3, 0]]
    return Geometry.from_mesh(np.array(P_, float), [f[::-1] for f in F_],
                              closed=True)


def needle():
    """A very sharp tetrahedron (the tip is a "sharp" vertex)."""
    P_ = np.array([[0, 1.5, 0], [-0.15, 0, -0.1], [0.15, 0, -0.1], [0, 0, 0.2]])
    return Geometry.from_mesh(P_, [[0, 2, 1], [0, 3, 2], [0, 1, 3], [1, 2, 3]],
                              closed=True)


cases = [("sphere", build.sphere(1, 32, 24)),
         ("20° sharp prism (edges need the sum of the two adjacent face normals)", prism(20)),
         ("sharp tetrahedron (the tip needs an angle-weighted vertex normal)", needle()),
         ("tilted torus", ops.transform(build.torus(1, 0.3, 12, 24), rotate=(30, 10, 0))),
         ("cuboid", build.box((1, 2, 0.5))),
         ("thin slab (thickness 0.04 < voxel)", build.box((1.5, 0.04, 1.0)))]
for name, g in cases:
    v = VO.mesh_to_volume(g, (28, 28, 28))
    f, o, c = info(v)
    Q = grid_pts(f, o, c)
    T, _, _ = SP.tri_soup(g)
    P = np.asarray(g.get(POINT, "P"), np.float64)
    _, d, _, _ = SP.closest_surface(Q, P, T)
    band = d <= 2.5 * c.max()
    eb = np.abs(np.abs(f.ravel()) - d)[band].max() / c.max()
    ef = np.abs(np.abs(f.ravel()) - d)[~band].max() / c.max() if (~band).any() else 0
    ins = inside_mesh(Q, g)
    bad = int(((f.ravel() < 0) != ins)[d > 1e-6].sum())
    ef99 = np.percentile(np.abs(np.abs(f.ravel()) - d)[~band], 99) / c.max() \
        if (~band).any() else 0
    check(f"{name}: distance in the narrow band vs brute force {eb:.1e} voxels, max outside the band {ef:.3f}, 99% "
          f"{ef99:.3f} voxels; sign vs ray voting all correct ({bad} wrong)",
          eb < 1e-4 and ef < 0.09 and ef99 < 0.035 and bad == 0)
nm2 = ops.fuse(ops.merge(build.box((1, 1, 1), center=(-0.5, -0.5, 0)),
                        build.box((1, 1, 1), center=(0.5, 0.5, 0))), 1e-6)
# ↑ the two cubes touch along one edge only; after welding that edge has 4 faces -- non-manifold
vn2 = VO.mesh_to_volume(nm2, (24, 24, 12))
fn2, on2, cn2 = info(vn2)
Q2 = grid_pts(fn2, on2, cn2)
inb = lambda c_: np.all(np.abs(Q2 - c_) < 0.5, axis=1)   # noqa: E731
ins2 = inb([-0.5, -0.5, 0]) | inb([0.5, 0.5, 0])
_, d2_, _, _ = SP.closest_surface(Q2, np.asarray(nm2.get(POINT, "P"), np.float64),
                                  SP.tri_soup(nm2)[0])
bad2 = int(((fn2.ravel() < 0) != ins2)[d2_ > 1e-6].sum())
check(f"two cubes touching along one edge only (non-manifold, pseudo-normals don't apply -> flood fill decides the sign): sign vs analytic "
      f"judgement all correct ({bad2} wrong), non-cubic resolution 24×24×12 also runs (JFA steps beyond the shortest "
      f"axis must be skipped)", bad2 == 0 and
      np.abs(np.abs(fn2.ravel()) - d2_).max() < 0.1 * cn2.max())
op = build.grid(2, 2, 6, 6)
vo = VO.mesh_to_volume(op, (16, 16, 16))
fo, oo, co = info(vo)
_, do, _, _ = SP.closest_surface(grid_pts(fo, oo, co), np.asarray(
    op.get(POINT, "P"), np.float64), SP.tri_soup(op)[0])
check("open mesh (a single plane): no inside/outside, falls back to unsigned distance",
      (fo >= 0).all() and np.abs(fo.ravel() - do).max() < 0.1 * co.max())
bx4 = build.box((1, 1, 1), divisions=(6, 6, 6))
cz = ops.prim_centers(bx4)
hole = (np.abs(cz[:, 1] - 0.5) < 1e-6) & (np.abs(cz[:, 0]) < 0.1) & \
    (np.abs(cz[:, 2]) < 0.1)
cup = ops.delete_prims(bx4, ~hole)                   # a small hole 1/5 of the edge length on top
fc_ = info(VO.mesh_to_volume(cup, (24, 24, 24)))[0]
check(f"box with a small hole 1/5 of the edge length on top ({int(hole.sum())} faces): water can get in -> the whole field is positive"
      f"(not just a negative layer hugging the inner wall -- the winding number of that layer is close to 1)", (fc_ >= 0).all())

# ═══════════════════════════════════════════════════════ Volume
sec("Volume")
g = VP.create_volume((5, 6, 7), (2, 3, 4), (1, 2, 3), 0.5, True, "dens")
f, o, c = info(g)
check("Resolution / Size / Center / Value / Fog / Name all correct",
      f.shape == (7, 6, 5) and np.allclose(o, [0, 0.5, 1]) and
      np.allclose(c, [0.5, 0.6, 4 / 6]) and (f == 0.5).all() and
      int(g.get(PRIM, "fog")[0, 0]) == 1 and g.get(PRIM, "name")[0, 0] == "dens")
bnd = Geometry.from_points(np.array([[0, 0, 0], [1.0, 0.45, 2.0]]))
g = VP.create_volume(bound=bnd, padding=0.1, voxel_size=0.1)
f, o, c = info(g)
Q = grid_pts(f, o, c)
check(f"bound + Voxel Size 0.1 connected: voxels are cubes, covering the bounding box expanded by 0.1 (resolution "
      f"{list(f.shape[::-1])})",
      np.allclose(c, 0.1) and (Q.min(0) <= [-0.1 + 0.051, -0.1 + 0.051, -0.1 + 0.051]).all()
      and (Q.max(0) >= [1.1 - 0.051, 0.55 - 0.051, 2.1 - 0.051]).all())

# ═══════════════════════════════════════════════════════ Blur
sec("Volume Blur")
cst = VP.create_volume((12, 10, 8), (1, 1, 1), (0, 0, 0), 3.0)
check("constant field unchanged after blur (boundary extends the edge value, doesn't pull in 0 from outside)",
      np.allclose(info(VP.blur(cst, 0.3))[0], 3.0))
lin = with_field((30, 30, 30), (3, 3, 3), (0, 0, 0),
                 lambda Q: 0.5 * Q[:, 0] - 2 * Q[:, 1] + Q[:, 2])
fl = info(lin)[0]
fb = info(VP.blur(lin, 0.2))[0]
m = 8
check("linear field unchanged in the interior (symmetric kernel)",
      np.abs(fb[m:-m, m:-m, m:-m] - fl[m:-m, m:-m, m:-m]).max() < 1e-5)
imp = VP.create_volume((61, 41, 31), (6.0, 6.0, 6.0), (0, 0, 0), 0.0)
fi, oi, ci = info(imp)
fi[15, 20, 30] = 1.0
imp.set_pdata(0, "voxels", fi.astype(np.float32))
R = 0.8
fb, _, _ = info(VP.blur(imp, R))
Q = grid_pts(fb, oi, ci)
w = fb.ravel()
mx = (w * Q[:, 0] ** 2).sum() / w.sum()
mz = (w * Q[:, 2] ** 2).sum() / w.sum()
sig = R / 2
check(f"impulse response: sum conserved ({w.sum():.6f}), second moment in x / z = σ² = {sig ** 2:.4f}"
      f"({mx:.4f} / {mz:.4f}), x and z voxel sizes differ ({ci[0]:.3f} / {ci[2]:.3f})",
      abs(w.sum() - 1) < 1e-5 and abs(mx - sig ** 2) < 0.01 * sig ** 2 + 1e-4 and
      abs(mz - sig ** 2) < 0.01 * sig ** 2 + 1e-4)
fb2 = info(VP.blur(imp, R, iterations=2))[0].ravel()
m2 = (fb2 * Q[:, 0] ** 2).sum() / fb2.sum()
check(f"two Gaussians = one with σ√2 (second moment {m2:.4f} ≈ 2σ² = {2 * sig ** 2:.4f})",
      abs(m2 - 2 * sig ** 2) < 0.02 * sig ** 2 + 1e-4)
small = VP.create_volume((5, 5, 5), (4, 4, 4), (0, 0, 0), 0.0)
fs = info(small)[0]
fs[2, 2, 2] = 27.0
small.set_pdata(0, "voxels", fs.astype(np.float32))
bx = info(VP.blur(small, 1.0, "box"))[0]
check("box radius 1 voxel: 3×3×3 mean (center 27 -> all 27 surrounding cells are 1)",
      np.allclose(bx[1:4, 1:4, 1:4], 1.0) and abs(bx.sum() - 27) < 1e-4)

# ═══════════════════════════════════════════════════════ Mix
sec("Volume Mix")
A_ = with_field((20, 20, 20), (2, 2, 2), (0, 0, 0), lambda Q: np.linalg.norm(Q, axis=1) - 0.6)
B_ = with_field((20, 20, 20), (2, 2, 2), (0, 0, 0),
                lambda Q: np.linalg.norm(Q - [0.5, 0, 0], axis=1) - 0.4)
fa, fbb = info(A_)[0], info(B_)[0]
ok_ = True
for op_, fn in [("add", lambda a, b: a + b), ("subtract", lambda a, b: a - b),
                ("multiply", lambda a, b: a * b), ("union", np.minimum),
                ("intersect", np.maximum), ("difference", lambda a, b: np.maximum(a, -b)),
                ("blend", lambda a, b: a * 0.7 + b * 0.3)]:
    gm, r = VP.mix(A_, B_, op_, factor=0.3)
    ok_ &= np.abs(info(gm)[0] - fn(fa, fbb)).max() < 1e-5 and not r["resampled_b"]
check("same grid: add / subtract / multiply / union / intersect / difference / blend equal the formula point by point",
      ok_)
k = 0.2
su = info(VP.mix(A_, B_, "smooth_union", k=k)[0])[0]
hard = np.minimum(fa, fbb)
far = np.abs(fa - fbb) >= k
eq = np.abs(fa - fbb) < 1e-9
check("smooth_union: equals hard min where |a − b| ≥ k, ≤ min everywhere, exactly min − k/4 where a = b",
      np.abs(su[far] - hard[far]).max() < 1e-5 and (su <= hard + 1e-6).all() and
      (not eq.any() or np.abs(su[eq] - (hard[eq] - k / 4)).max() < 1e-5))
si = info(VP.mix(A_, B_, "smooth_intersect", k=k)[0])[0]
hmax = np.maximum(fa, fbb)
check("smooth_intersect: equals hard max far away, ≥ max everywhere",
      np.abs(si[far] - hmax[far]).max() < 1e-5 and (si >= hmax - 1e-6).all())
check("  k = 0 falls back to hard union",
      np.abs(info(VP.mix(A_, B_, "smooth_union", k=0)[0])[0] - hard).max() < 1e-6)
L1 = with_field((17, 13, 11), (2, 2, 2), (0, 0, 0), lambda Q: Q @ [1, 2, 3])
L2 = with_field((9, 23, 7), (3, 3, 3), (0.2, 0, 0), lambda Q: Q @ [-1, 0.5, 2])
gm, r = VP.mix(L1, L2, "add")
f1, o1, c1 = info(gm)
Q1 = grid_pts(f1, o1, c1)
check("different grids: B resampled by world coordinates, sum of two linear fields exact",
      r["resampled_b"] and np.abs(f1.ravel() - (Q1 @ [0, 2.5, 5])).max() < 1e-4)

# ═══════════════════════════════════════════════════════ Resample
sec("Volume Resample")
L = with_field((11, 9, 7), (2, 2, 2), (0, 0, 0), lambda Q: Q @ [1, -2, 0.5] + 1)
ok_ = True
for res in [(4, 4, 4), (23, 5, 31)]:
    gr, _ = VP.resample(L, "resolution", res)
    fr, orr, cr = info(gr)
    ok_ &= fr.shape == res[::-1] and np.abs(fr.ravel() - (grid_pts(fr, orr, cr) @
                                                         [1, -2, 0.5] + 1)).max() < 1e-5
check("linear field exact at any resolution (including coarser)", ok_)
g2, r2 = VP.resample(L, "scale", scale=2.0)
f2 = info(g2)[0]
check(f"integer refinement (scale 2 -> {r2['resolutions'][0]}): old grid points kept bit for bit",
      np.array_equal(f2[::2, ::2, ::2], info(L)[0]))
g3, r3 = VP.resample(L, "voxel_size", voxel_size=0.25)
check("by voxel size: 2 / 0.25 + 1 = 9, bounding box unchanged",
      r3["resolutions"][0] == [9, 9, 9] and
      np.allclose(g3.get(PRIM, "vsize"), L.get(PRIM, "vsize")))
gn, _ = VP.resample(L, "resolution", (13, 13, 13), interpolation="nearest")
check("nearest: new values are all among the old values",
      np.isin(info(gn)[0], info(L)[0]).all())

# ═══════════════════════════════════════════════════════ Wrangle
sec("Volume Wrangle")
two = ops.merge(with_field((8, 9, 10), (1, 1, 1), (0, 0, 0), lambda Q: Q[:, 0], "a"),
                with_field((6, 6, 6), (2, 2, 2), (0, 0, 0), lambda Q: Q[:, 1] * 10, "b"))
gw, rw = VP.wrangle(two, "@value = @value * 2 + @P.y + @iz * 0.5", "a")
fw, ow, cw = info(gw, 0)
Qw = grid_pts(fw, ow, cw)
iz = np.indices(fw.shape)[0].ravel()
check("formula vs numpy: @value * 2 + @P.y + @iz * 0.5; unselected volume b untouched",
      np.abs(fw.ravel() - (Qw[:, 0] * 2 + Qw[:, 1] + iz * 0.5)).max() < 1e-5 and
      np.array_equal(info(gw, 1)[0], info(two, 1)[0]) and rw["volumes"] == [0])
gw2, _ = VP.wrangle(two, "@value = volsample('b', @P)", "a")
gw3, _ = VP.wrangle(two, "@value = volsample(1, @P)", "a")
check("volsample('b', @P) and volsample(1, @P): sampling another volume (b = 10·y)",
      np.abs(info(gw2, 0)[0].ravel() - Qw[:, 1] * 10).max() < 1e-4 and
      np.array_equal(info(gw2, 0)[0], info(gw3, 0)[0]))
three = ops.merge(build.box(), two)                  # 6 polygon faces in front
gw4, _ = VP.wrangle(three, "@value = volsample(1, @P)", "a")
check("  volsample(1, …) counts volumes only: still gets b with polygon faces in front",
      np.array_equal(info(gw4, 6)[0], info(gw2, 0)[0]))
err("broken code errors (with the transpiled Python)",
    lambda: VP.wrangle(two, "@value = nope", "a"), "nope")
err("no match by name errors", lambda: VP.wrangle(two, "@value = 1", "zz"), "zz")

# ═══════════════════════════════════════════════════════ Reshape SDF
sec("Volume Reshape SDF")
sph = VO.mesh_to_volume(build.sphere(1, 48, 32), (40, 40, 40), pad=0.4)
fs0, os0, cs0 = info(sph)


def val_at(g, pts):
    f, o, c = info(g)
    return AS.sample_volume(f, o, c, np.asarray(pts, np.float64))[0]


dirs = rng.normal(size=(200, 3))
dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
for op_, r_ in (("dilate", 1.2), ("erode", 0.8)):
    gd = VP.reshape_sdf(sph, op_, 0.2)
    e = np.abs(val_at(gd, dirs * r_)).max()
    check(f"{op_} 0.2: zero moves to r = {r_} (max value there {e:.4f})", e < 0.1 * cs0.max())
s3 = sph.copy()
s3.set_pdata(0, "voxels", (fs0 * 3).astype(np.float32))
rd = info(VP.reshape_sdf(s3, "redistance"))[0]
err_rd = np.abs(rd - fs0).max() / cs0.max()
check(f"SDF × 3 redistance: back to the original SDF (diff {err_rd:.3f} voxels)", err_rd < 0.2)
# A sphere with a thin spike: open shaves off the spike; two spheres separated by a narrow gap: close fills it
ball = with_field((48, 48, 48), (3, 3, 3), (0, 0, 0),
                  lambda Q: np.linalg.norm(Q, axis=1) - 0.8)
spike = with_field((48, 48, 48), (3, 3, 3), (0, 0, 0),
                   lambda Q: np.maximum(np.hypot(Q[:, 1], Q[:, 2]) - 0.06,
                                        np.abs(Q[:, 0] - 0.9) - 0.45))
sp_ = VP.mix(ball, spike, "union")[0]
tip = [[1.2, 0, 0]]
op_g = VP.reshape_sdf(sp_, "open", 0.12)
side = dirs[np.abs(dirs[:, 0]) < 0.5] * 0.8
check(f"open 0.12: the spike of radius 0.06 is gone (on the spike {val_at(sp_, tip)[0]:.3f} -> "
      f"{val_at(op_g, tip)[0]:.3f}), sphere surface unchanged (max {np.abs(val_at(op_g, side)).max():.3f})",
      val_at(sp_, tip)[0] < 0 < val_at(op_g, tip)[0] and
      np.abs(val_at(op_g, side)).max() < 0.2 * info(sp_)[2].max())
b1 = with_field((48, 48, 48), (3, 3, 3), (0, 0, 0),
                lambda Q: np.linalg.norm(Q - [-0.55, 0, 0], axis=1) - 0.5)
b2 = with_field((48, 48, 48), (3, 3, 3), (0, 0, 0),
                lambda Q: np.linalg.norm(Q - [0.55, 0, 0], axis=1) - 0.5)
gap = VP.mix(b1, b2, "union")[0]
cl = VP.reshape_sdf(gap, "close", 0.1)
check(f"close 0.1: the 0.1-wide gap is filled (gap center {val_at(gap, [[0, 0, 0]])[0]:.3f} -> "
      f"{val_at(cl, [[0, 0, 0]])[0]:.3f}), far end unchanged",
      val_at(gap, [[0, 0, 0]])[0] > 0 > val_at(cl, [[0, 0, 0]])[0] and
      abs(val_at(cl, [[-1.05, 0, 0]])[0]) < 0.2 * info(gap)[2].max())
fog = VO.points_to_volume(Geometry.from_points(rng.random((50, 3))), (8, 8, 8))
err("Reshape on a fog volume errors", lambda: VP.reshape_sdf(fog, "dilate", 0.1), "fog")
err("no volume errors", lambda: VP.blur(build.box(), 0.1), "no volume")

# ═══════════════════════════════════════════════════════ Nodes
sec("Nodes")
NEW = {"PCG_Volume": "PCG/generate", "PCG_VolumeBlur": "PCG/modify",
       "PCG_VolumeMix": "PCG/modify", "PCG_VolumeResample": "PCG/modify",
       "PCG_VolumeWrangle": "PCG/modify", "PCG_VolumeReshapeSDF": "PCG/modify"}
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
    return kw


bad = []
for k, kw in {"PCG_Volume": {}, "PCG_VolumeBlur": dict(geo=sph),
              "PCG_VolumeMix": dict(geo_a=A_, geo_b=B_),
              "PCG_VolumeResample": dict(geo=sph),
              "PCG_VolumeWrangle": dict(geo=sph),
              "PCG_VolumeReshapeSDF": dict(geo=sph)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("all 6 nodes run with default parameters (volume connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
