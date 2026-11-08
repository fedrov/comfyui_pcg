"""
pcg71: the two nodes that finish P2 -- Attribute from Volume, Attribute Transfer by UV.

The reference doesn't rely on the implementation itself:
  Volume   a linear field a·x + b is exact under trilinear interpolation (at any point), the gradient is exactly a; on grid points
           trilinear / nearest both return the voxel values bit for bit; a sphere's SDF samples ≈ |p| − 1 (within half a
           voxel), gradient ≈ radial unit vector; one step along the gradient puts the point on the sphere surface
  by UV    a linear function of uv on the source -> interpolation is exact on a target of any topology; moving P by uv wraps a fine
           grid onto a coarse grid bent into a half cylinder, every point lands on the source surface; across seams (vertex uv)
           each side takes its own; for a source with stacked UVs, the overlap count in the report = number of queries
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

from comfyui_pcg.geo import attribsample as AS          # noqa: E402
from comfyui_pcg.geo import volume as VO                # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import spatial as SP               # noqa: E402
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


def A(g, cls, name):
    return np.asarray(g.get(cls, name), np.float64)


def Pd(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


rng = np.random.default_rng(71)

# ═══════════════════════════════════════════════════════ Attribute from Volume
sec("Attribute from Volume")
vol = VO.make_volume((9, 7, 5), (4.0, 3.0, 2.0), (0.5, 0.0, -1.0))
vox, org, cell = VO.volume_info(vol, 0)
rz, ry, rx = vox.shape
Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx), indexing="ij")
W = np.stack([X * cell[0] + org[0], Y * cell[1] + org[1], Z * cell[2] + org[2]],
             -1)
a_ = np.array([0.3, -1.2, 2.0])
field = (W @ a_ + 0.7).astype(np.float32)
vol.set_pdata(0, "voxels", field)
Q = rng.random((2000, 3)) * [4, 3, 2] + org
pts = Geometry.from_points(Q)
Qf = Pd(pts)
o, r = AS.attribute_from_volume(pts, vol, "d")
e = np.abs(A(o, POINT, "d").ravel() - (Qf @ a_ + 0.7)).max()
check(f"linear field a·x + b: trilinear interpolation exact at any point (diff {e:.1e}, voxels are float32)",
      e < 2e-6 and r["outside"] == 0)
o, _ = AS.attribute_from_volume(pts, vol, "g", mode="gradient")
eg = np.abs(A(o, POINT, "g") - a_).max()
check(f"gradient: gradient of a linear field = a everywhere (diff {eg:.1e})", eg < 1e-5)
nodes = Geometry.from_points(W.reshape(-1, 3))
ot, _ = AS.attribute_from_volume(nodes, vol, "d")
on, _ = AS.attribute_from_volume(nodes, vol, "d", mode="nearest")
check("on grid points trilinear and nearest both return the voxel values bit for bit",
      np.array_equal(A(ot, POINT, "d").ravel(), field.ravel().astype(np.float64))
      and np.array_equal(A(on, POINT, "d").ravel(),
                         field.ravel().astype(np.float64)))
k = np.rint((Qf - org) / cell).astype(int)
on, _ = AS.attribute_from_volume(pts, vol, "d", mode="nearest")
check("nearest = voxel value of the nearest grid point (rounded)",
      np.array_equal(A(on, POINT, "d").ravel(),
                     field[k[:, 2], k[:, 1], k[:, 0]].astype(np.float64)))
check("  negative control: nearest is not exact between grid points (detectable on a linear field)",
      np.abs(A(on, POINT, "d").ravel() - (Qf @ a_ + 0.7)).max() > 0.1)
out_pts = Geometry.from_points(np.array([[10.0, 0, -1], [0.5, 0, -1]]))
out_pts.set(POINT, "d", np.array([[42.0], [42.0]], np.float32))
oc, rc = AS.attribute_from_volume(out_pts, vol, "d", outside="clamp")
edge = np.array([org[0] + 4.0, 0, -1])
check("clamp: points outside the volume take the border value (x clamped to the +x border)",
      abs(A(oc, POINT, "d")[0, 0] - (edge @ a_ + 0.7)) < 1e-5 and rc["outside"] == 1)
ok_, _ = AS.attribute_from_volume(out_pts, vol, "d", outside="constant",
                                  outside_value=-5)
ok2, _ = AS.attribute_from_volume(out_pts, vol, "d", outside="keep")
check("constant gives Outside Value; keep keeps the original value; points inside the volume sample as usual",
      A(ok_, POINT, "d")[0, 0] == -5 and A(ok2, POINT, "d")[0, 0] == 42 and
      abs(A(ok2, POINT, "d")[1, 0] - (np.array([0.5, 0, -1]) @ a_ + 0.7)) < 1e-5)
edge_out = Geometry.from_points(np.array([[org[0] + 4.0 + 0.5 * cell[0], 0, -1]]))
edge_out.set(POINT, "d", np.array([[42.0]], np.float32))
oe, re_ = AS.attribute_from_volume(edge_out, vol, "d", outside="keep")
check("a point just half a voxel outside the border also counts as outside (keep doesn't write)",
      A(oe, POINT, "d")[0, 0] == 42 and re_["outside"] == 1)
mixed = ops.merge(build.box(), vol)
omx, rmx = AS.attribute_from_volume(pts, mixed, "d", volume="0")
check("Volume = 0 counts only volume prims: picks that volume even with 6 polygon faces in front of it",
      rmx["volume_prim"] == 6 and np.array_equal(
          A(omx, POINT, "d"),
          A(AS.attribute_from_volume(pts, vol, "d")[0], POINT, "d")))
sph = build.sphere(1.0, 64, 48)
sdf = VO.mesh_to_volume(sph, (48, 48, 48))
_, _, cs = VO.volume_info(sdf, 0)
d_ = rng.normal(size=(800, 3))
d_ /= np.linalg.norm(d_, axis=1, keepdims=True)
rr = rng.uniform(0.4, 1.2, (800, 1))
qs = Geometry.from_points(d_ * rr)
Qs = Pd(qs)
os_, _ = AS.attribute_from_volume(qs, sdf, "s")
es = np.abs(A(os_, POINT, "s").ravel() - (np.linalg.norm(Qs, axis=1) - 1)).max()
check(f"sphere SDF: samples ≈ |p| − 1 (max diff {es:.4f}, one voxel {cs.max():.3f}; "
      f"since pcg72 Convert's SDF is exact)", es < 0.1 * cs.max())
# in pcg71 Convert's SDF was approximated from random surface sample points, and the gradient near the surface could be off by 80°, so this only dared to
# test the interior; since pcg72 switched to an exact narrow band + JFA + pseudo-normals it's accurate near the surface too, so the full range is tested
og, _ = AS.attribute_from_volume(qs, sdf, "g", mode="gradient")
G = A(og, POINT, "g")
cosang = np.einsum("ij,ij->i", G / np.linalg.norm(G, axis=1, keepdims=True), d_)
near = np.abs(rr[:, 0] - 1) < 0.1
check(f"  gradient ≈ radial: max angle over the full range {math.degrees(math.acos(cosang.min())):.1f}°, "
      f"within ±0.1 of the surface max {math.degrees(math.acos(cosang[near].min())):.1f}°; "
      f"median length {np.median(np.linalg.norm(G, axis=1)):.3f}",
      cosang.min() > math.cos(math.radians(4)) and
      cosang[near].min() > math.cos(math.radians(2)) and
      abs(np.median(np.linalg.norm(G, axis=1)) - 1) < 0.02)
Pp = Qs - A(os_, POINT, "s") * G / np.linalg.norm(G, axis=1, keepdims=True)
ep = np.abs(np.linalg.norm(Pp, axis=1) - 1).max()
check(f"  every point pushed one step of −sdf along the gradient: lands on the sphere (|p| − 1 max {ep:.4f})",
      ep < 0.1 * cs.max())
bx = build.box((1, 1, 1), center=(0.5, 0.0, -1.0), divisions=(3, 3, 3))
opm, _ = AS.attribute_from_volume(bx, vol, "d", attribute_class="prim")
C = ops.prim_centers(bx).astype(np.float64)
check("prim class: sampled at prim centers", np.abs(A(opm, PRIM, "d").ravel() -
                                  (C @ a_ + 0.7)).max() < 2e-6)
pts.set_group(POINT, "half", Qf[:, 0] > 0.5)
og_, rg = AS.attribute_from_volume(pts, vol, "d", group="half")
dv = A(og_, POINT, "d").ravel()
check("group: only selected points written (the rest are 0)",
      (dv[Qf[:, 0] <= 0.5] == 0).all() and rg["sampled"] == int((Qf[:, 0] > 0.5).sum()))
two = ops.merge(vol, sdf)
two.set_string(PRIM, "name", np.array(["lin", "sdf"]))
o1, r1 = AS.attribute_from_volume(qs, two, "s", volume="1")
o2, r2 = AS.attribute_from_volume(qs, two, "s", volume="sdf")
check("two volumes: index 1 and name sdf pick the same one (the second)",
      r1["volume_prim"] == r2["volume_prim"] == 1 and
      np.array_equal(A(o1, POINT, "s"), A(os_, POINT, "s")))
err("no volume -> error", lambda: AS.attribute_from_volume(pts, bx, "d"), "no volume prims")
err("index out of range -> error", lambda: AS.attribute_from_volume(pts, vol, "d", volume="3"),
    "out of range")
err("name not found -> error", lambda: AS.attribute_from_volume(pts, two, "d", volume="x"),
    "No volume named")

# ═══════════════════════════════════════════════════════ Attribute Transfer by UV
sec("Attribute Transfer by UV")
src = build.grid(2, 2, 11, 11)
Ps = Pd(src)
src.set(POINT, "uv", (Ps[:, [0, 2]] * 0.5 + 0.5).astype(np.float32))


def lin(uv):
    x = uv * 2 - 1
    return np.c_[x[:, 0], x[:, 1], 0.3 * x[:, 0] - 2 * x[:, 1] + 1]


src.set(POINT, "Cd", lin(A(src, POINT, "uv")).astype(np.float32))
dst = build.grid(3, 1, 37, 23)
U = rng.random((dst.npoints, 2))
dst.set(POINT, "uv", U.astype(np.float32))
Uf = A(dst, POINT, "uv")
o, r = AS.attribute_transfer_by_uv(dst, src, "Cd")
e = np.abs(A(o, POINT, "Cd") - lin(Uf)).max()
check(f"linear function of uv on the source -> exact on a target with completely different topology (diff {e:.1e})",
      e < 1e-5 and r["point_inside"] == dst.npoints and r["point_nearest"] == 0)
check("  report: none landed in a UV overlap region", r["point_in_overlap"] == 0)
src.set(PRIM, "pid", np.arange(src.nprims, dtype=np.int32)[:, None])
op_, _ = AS.attribute_transfer_by_uv(dst, src, "pid")
cellx = np.minimum((Uf[:, 0] * 10).astype(int), 9)
celly = np.minimum((Uf[:, 1] * 10).astype(int), 9)
pid_s = A(src, PRIM, "pid").ravel()
Cp = ops.prim_centers(src)[:, [0, 2]] * 0.5 + 0.5
cell_of = {(int(cx * 10), int(cy * 10)): p for (cx, cy), p in zip(Cp, pid_s)}
exp = np.array([cell_of[(a, b)] for a, b in zip(cellx, celly)])
check("prim attribute: takes the value of the source face the uv lies in",
      np.array_equal(A(op_, PRIM if False else POINT, "pid").ravel(), exp))
src.set_string(PRIM, "name", np.where(Cp[:, 0] < 0.5, "L", "R"))
osn, _ = AS.attribute_transfer_by_uv(dst, src, "name")
nm = np.asarray(osn.get(POINT, "name")).ravel()
check("string attribute: left half L, right half R",
      (nm[Uf[:, 0] < 0.49] == "L").all() and (nm[Uf[:, 0] > 0.51] == "R").all())
src.set_string(POINT, "side", np.where(Ps[:, 0] < -1e-9, "L", "R"))
osd, _ = AS.attribute_transfer_by_uv(dst, src, "side")
sd = np.asarray(osd.get(POINT, "side")).ravel()
band = (Uf[:, 0] > 0.4) & (Uf[:, 0] < 0.5)
check("strings on points take the corner with the largest weight: u ∈ (0.4, 0.42) next to the L column, (0.48, 0.5) next to"
      " the x = 0 column (R)",
      (sd[band & (Uf[:, 0] < 0.42)] == "L").all() and
      (sd[band & (Uf[:, 0] > 0.48)] == "R").all())
# wrapping: a fine grid wrapped by uv onto a coarse grid bent into a half cylinder
bent = src.copy()
th = (Ps[:, 0] + 1) / 2 * math.pi
bent.set(POINT, "P", np.c_[np.cos(th), Ps[:, 2], np.sin(th)].astype(np.float32))
fine = build.grid(2, 2, 41, 41)
Pf = Pd(fine)
fine.set(POINT, "uv", (Pf[:, [0, 2]] * 0.5 + 0.5).astype(np.float32))
ow, rw = AS.attribute_transfer_by_uv(fine, bent, "P")
Pw = Pd(ow)
T, _, _ = SP.tri_soup(bent)
_, dist, _, _ = SP.closest_surface(Pw, Pd(bent), T)
check(f"moving P: a flat 41×41 grid wrapped by uv onto the half cylinder, every point on the source surface (max distance "
      f"{dist.max():.1e})", dist.max() < 1e-5)
corner = [(0, 0), (40, 0), (0, 40), (40, 40)]
ids_f = [j * 41 + i for i, j in corner]
Ub = A(bent, POINT, "uv")
ids_b = [int(np.argmin(np.linalg.norm(Ub - A(fine, POINT, "uv")[k], axis=1)))
         for k in ids_f]
check("  the four corners land exactly on the source's four corners",
      np.abs(Pw[ids_f] - Pd(bent)[ids_b]).max() < 1e-6)
# outside the islands
far = Geometry.from_points(np.zeros((3, 3)))
far.set(POINT, "uv", np.array([[1.5, 0.5], [0.5, -0.2], [0.3, 0.3]], np.float32))
far.set(POINT, "Cd", np.full((3, 3), 9.0, np.float32))
on_, rn = AS.attribute_transfer_by_uv(far, src, "Cd", outside="nearest")
check("nearest: points outside the UVs use the nearest triangle (value = linear function of the uv clamped to the edge)",
      np.abs(A(on_, POINT, "Cd")[:2] - lin(np.array([[1.0, 0.5], [0.5, 0.0]])))
      .max() < 1e-5 and rn["point_nearest"] == 2)
ok_, rk = AS.attribute_transfer_by_uv(far, src, "Cd", outside="keep")
check("keep: points outside the UVs keep their values, those inside move as usual",
      (A(ok_, POINT, "Cd")[:2] == 9).all() and
      np.abs(A(ok_, POINT, "Cd")[2] - lin(np.array([[0.3, 0.3]]))[0]).max() < 1e-5
      and rk["point_missed"] == 2)
om_, rm = AS.attribute_transfer_by_uv(far, src, "Cd", max_distance=0.3)
check("Max Distance 0.3: the one 0.5 away doesn't move, the one 0.2 away does",
      (A(om_, POINT, "Cd")[0] == 9).all() and
      np.abs(A(om_, POINT, "Cd")[1] - lin(np.array([[0.5, 0.0]]))[0]).max() < 1e-5)
# overlapping UVs
dup = ops.merge(src, ops.transform(src, translate=(0, 1, 0)))
od, rd = AS.attribute_transfer_by_uv(dst, dup, "Cd")
check(f"source with two stacked UV layers: report says {rd['point_in_overlap']} landed in the overlap ≈ all "
      f"(those not on shared edges)", rd["point_in_overlap"] > 0.95 * dst.npoints)
odp, _ = AS.attribute_transfer_by_uv(dst, dup, "P")
check("  on overlap the layer with the lower index wins (first layer y = 0, second layer y = 1)",
      np.abs(Pd(odp)[:, 1]).max() < 1e-6)
# vertex uv seams: each of a cube's 6 faces is its own island, laid out in a row
cube = build.box((1, 1, 1))
uvv = np.zeros((cube.nvertices, 2))
Cdv = np.zeros((cube.nvertices, 3))
Pc = Pd(cube)
for p in range(cube.nprims):
    vs = np.arange(cube.prim_offset[p], cube.prim_offset[p + 1])
    q = Pc[cube.vertex_point[vs]]
    ax = [i for i in range(3) if np.ptp(q[:, i]) > 1e-9]
    uvv[vs] = (q[:, ax] + 0.5) * 0.9 + [1.0 * p, 0]
    Cdv[vs] = [p, p * 2, 1]
cube.set(VERTEX, "uv", uvv.astype(np.float32))
cube.set(VERTEX, "Cd", Cdv.astype(np.float32))
dcube = cube.copy()
dcube.remove(VERTEX, "Cd")
ov, rv = AS.attribute_transfer_by_uv(dcube, cube, "Cd", attribute_class="vertex")
check("vertex class: across seams (the same point on 3 islands) each side takes its own, per vertex equal to the source",
      np.abs(A(ov, VERTEX, "Cd") - Cdv).max() < 1e-6 and rv["vertex_inside"] ==
      cube.nvertices)
opc, _ = AS.attribute_transfer_by_uv(dcube, cube, "Cd")
first = np.full(cube.npoints, -1)
for vv in range(cube.nvertices - 1, -1, -1):
    first[cube.vertex_point[vv]] = vv
check("point class on vertex uv: each point takes the uv of its first vertex (on a seam, the color of that side)",
      np.abs(A(opc, POINT, "Cd") - Cdv[first]).max() < 1e-6)
ost, _ = AS.attribute_transfer_by_uv(dcube, cube, "*")
check("Attributes = *: the source's vertex uv is not transferred as an extra point uv on the target",
      ost.get(POINT, "uv") is None and
      np.array_equal(np.asarray(ost.get(VERTEX, "uv")), np.asarray(dcube.get(VERTEX, "uv"))))
opp, _ = AS.attribute_transfer_by_uv(dcube, cube, "P")
check("moving P on vertex uv (by each point's first vertex uv): the cube is unchanged",
      np.abs(Pd(opp) - Pc).max() < 1e-6)
nsrc = src.copy()
nsrc.set(POINT, "N", np.c_[Ps[:, 0], np.ones(len(Ps)), Ps[:, 2]].astype(np.float32))
onn, _ = AS.attribute_transfer_by_uv(dst, nsrc, "N")
check("N normalized after interpolation", np.abs(np.linalg.norm(A(onn, POINT, "N"), axis=1) - 1).max()
      < 1e-5)
oall, _ = AS.attribute_transfer_by_uv(dst, src, "*")
check("Attributes = * also doesn't transfer the source uv over the target's own uv",
      np.array_equal(np.asarray(oall.get(POINT, "uv")), np.asarray(dst.get(POINT, "uv"))))
err("target has no uv -> error",
    lambda: AS.attribute_transfer_by_uv(Geometry.from_points(np.zeros((2, 3))),
                                        src, "Cd"), "uv")
err("no matching attribute -> error",
    lambda: AS.attribute_transfer_by_uv(dst, src, "nope*"), "nope")

# ═══════════════════════════════════════════════════════ nodes
sec("nodes")
NEW = {"PCG_AttribFromVolume": "PCG/attribute",
       "PCG_AttribTransferByUV": "PCG/attribute"}
check("both nodes registered, in the right category",
      all(k in MAP and MAP[k].CATEGORY == v for k, v in NEW.items()))
bad = [k for k in NEW for nm_ in MAP[k].INPUT_TYPES()["required"]
       if nm_ in ("seed", "class")]
check("no widget called seed / class", not bad, bad)


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
for k, kw in {"PCG_AttribFromVolume": dict(geo=pts, volume=vol),
              "PCG_AttribTransferByUV": dict(geo=dst, source=src)}.items():
    try:
        r = unwrap(MAP[k]().run(**defaults(MAP[k], **kw)))
        if not isinstance(r[0], Geometry):
            bad.append(k)
    except Exception as ex:                       # noqa: BLE001
        bad.append(f"{k}: {ex}")
check("both nodes cook with default parameters (with a volume / source connected)", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
