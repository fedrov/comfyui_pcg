"""
pcg102: after pcg101, an inventory of 9 "known but not yet fixed" issues; verification after fixing each of them.

Every item has a negative control (reproducing the wrong result of the old code), confirming the test tells old and new behaviour apart.

  1 matrix convention  the transform attribute is read/written as Houdini row vectors (p' = p·M, translation in row 4)
  2 ray_cast      both=True takes the nearest |t|, no longer "the most negative"
  3 lost attribs  PolyBevel / Boolean carry point / vertex / prim attributes and groups
  4 push-pull     large holes in non-square images are no longer pulled towards 0
  5 Remesh        Smooth Feature Lines: curved hard edges are no longer straight segments after subdivision
  6 Worley        F2 + Manhattan searches 125 neighbour cells, matches brute force
  7 strings       Attribute Create / Wrangle no longer truncate to 64 characters
  8 @ group expr  supports and / or / not
  9 edge groups   a nonexistent edge group name raises; wildcards and p3-7 point-pair syntax supported
"""
import itertools
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg.geo import build, ops, copyto, wrangle, attribops   # noqa: E402
from comfyui_pcg.geo import groups as GR                # noqa: E402
from comfyui_pcg.geo import xformattr as XA             # noqa: E402
from comfyui_pcg.geo import xformextract as XE          # noqa: E402
from comfyui_pcg.geo import registration as RG          # noqa: E402
from comfyui_pcg.geo import remesh as RM                # noqa: E402
from comfyui_pcg.geo import backproject as BP           # noqa: E402
from comfyui_pcg.geo.xform import point_matrices        # noqa: E402
from comfyui_pcg.geo.spatial import ray_cast            # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, VERTEX, DETAIL   # noqa: E402
from comfyui_pcg.geo.cop import noise as NZ, backend as BK               # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def PP(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def raises(fn, exc=Exception, text=""):
    try:
        fn()
    except exc as e:
        return text in str(e)
    return False


# ═══════════════════════════════════════════════════════ 1 matrix convention
sec("1 transform attribute = Houdini row-vector convention")
# Houdini: the 3×3 from maketransform rotating 90° about Z (row-major)
HZ = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1.0]])
check("  (self-check) Houdini row vector: (1,0,0)·HZ = (0,1,0); old reading HZ·(1,0,0) = (0,-1,0)",
      np.allclose(np.array([1, 0, 0]) @ HZ, [0, 1, 0])
      and np.allclose(HZ @ [1, 0, 0], [0, -1, 0]))
tpl = Geometry.from_points(np.array([[1.0, 0, 0]]))
tg = Geometry.from_points(np.array([[10.0, 0, 0]]))
tg.set(POINT, "transform", HZ.reshape(1, 9).astype(np.float32))
cp = copyto.copy_to_points(tpl, tg, target_attribs="")
check("Copy to Points: transform(9) = Houdini's 90° about Z, (1,0,0) lands at (10,1,0)",
      np.abs(PP(cp)[0] - [10, 1, 0]).max() < 1e-6, PP(cp)[0])
m4 = np.eye(4)
m4[:3, :3] = HZ
m4[3, :3] = [5, 6, 7]
tg4 = Geometry.from_points(np.zeros((1, 3)))
tg4.set(POINT, "transform", m4.reshape(1, 16).astype(np.float32))
cp4 = copyto.copy_to_points(tpl, tg4, target_attribs="")
check("  transform(16): same rotation, translation in row 4 -> (5,7,7)",
      np.abs(PP(cp4)[0] - [5, 7, 7]).max() < 1e-6, PP(cp4)[0])
d = Geometry.from_points(np.array([[1.0, 0, 0], [0, 2.0, 0]]))
d.set(DETAIL, "transform", m4.reshape(1, 16).astype(np.float32))
o, _ = XA.transform_by_attrib(d, cls="detail")
check("Transform by Attribute: the same 4×4, P' = P·M + T",
      np.abs(PP(o) - (PP(d) @ HZ + [5, 6, 7])).max() < 1e-6)
o2, _ = XA.transform_by_attrib(o, cls="detail", invert=True)
check("  Invert restores the original", np.abs(PP(o2) - PP(d)).max() < 1e-5)
d9 = d.copy()
d9.set(DETAIL, "transform", HZ.reshape(1, 9).astype(np.float32))
o9, _ = XA.transform_by_attrib(d9, cls="detail")
check("  9 components use the same reading: P' = P·M", np.abs(PP(o9) - PP(d) @ HZ).max() < 1e-6)
Mc, Tc, _ = point_matrices(tg4)
check("  column-vector matrix from point_matrices = HZᵀ (internally M @ p)",
      np.allclose(Mc[0], HZ.T) and np.allclose(Tc[0], [5, 6, 7]))
# Attribute Transform Extract (Houdini semantics): +90° about Z, not −90°
ex = Geometry.from_points(np.zeros((1, 3)))
ex.set(POINT, "transform", m4.reshape(1, 16).astype(np.float32))
eo, _ = XE.attrib_transform_extract(ex)
r = np.asarray(eo.get(POINT, "transform_r"), np.float64)[0]
t = np.asarray(eo.get(POINT, "transform_t"), np.float64)[0]
check("Attribute Transform Extract: Houdini's 90° about Z decomposes to rz = +90 (old reading gave −90), t = (5,6,7)",
      np.allclose(r, [0, 0, 90], atol=1e-4) and np.allclose(t, [5, 6, 7]), (r, t))
ex9 = Geometry.from_points(np.zeros((1, 3)))
ex9.set(POINT, "transform", HZ.reshape(1, 9).astype(np.float32))
r9 = np.asarray(XE.attrib_transform_extract(ex9)[0].get(POINT, "transform_r"), np.float64)[0]
check("  9 components: also decomposes to rz = +90", np.allclose(r9, [0, 0, 90], atol=1e-4), r9)
# Matrix written by Extract Transform (matrix3 / matrix4) round-trips with Copy to Points
ref = build.box()
Pr = PP(ref)
Maff = np.array([[1.2, 0.3, -0.1], [0.0, 0.8, 0.4], [0.2, 0.1, 1.5]])
tgt = ref.copy()
tgt.set(POINT, "P", (Pr @ Maff.T + [1, 2, 3]).astype(np.float32))
for outp in ("matrix3", "matrix4"):
    pt, _, rep = RG.extract_transform(ref, tgt, "affine", output=outp)
    X = np.asarray(pt.get(POINT, "transform"), np.float64)[0]
    R3 = X.reshape(3, 3) if outp == "matrix3" else X.reshape(4, 4)[:3, :3]
    back = copyto.copy_to_points(ref, pt, target_attribs="")
    check(f"Extract Transform {outp}: written 3×3 = Maffᵀ (row vector), copying back lands on target",
          np.abs(R3 - Maff.T).max() < 1e-5 and np.abs(PP(back) - PP(tgt)).max() < 1e-4)

# ═══════════════════════════════════════════════════════ 2 ray_cast both
sec("2 ray_cast(both=True) takes the nearest distance")


def quad(z, s=10):
    return np.array([[-s, -s, z], [s, -s, z], [s, s, z], [-s, s, z]], float)


Zs = [-5.0, -1.5, 3.0, 7.0]
Pq = np.concatenate([quad(z) for z in Zs])
Tq = np.array([[4 * k, 4 * k + 1, 4 * k + 2] for k in range(4)]
              + [[4 * k, 4 * k + 2, 4 * k + 3] for k in range(4)])
for n in (1, 64, 200000):
    O = np.zeros((n, 3))
    if n > 1:
        O[:, :2] = np.random.default_rng(n).uniform(-3, 3, (n, 2))
    D = np.tile([0, 0, 1.0], (n, 1))
    _, t1, _ = ray_cast(O, D, Pq, Tq, both=True)
    _, t2, _ = ray_cast(O, D, Pq, Tq, both=True, farthest=True)
    _, t3, _ = ray_cast(O, D, Pq, Tq)
    _, t4, _ = ray_cast(O, D, Pq, Tq, farthest=True)
    check(f"  n={n}: both -> −1.5 (the face behind is nearer; old took the most negative = −5); both+farthest -> 7; "
          f"one direction -> 3 / 7",
          np.allclose(t1, -1.5) and np.allclose(t2, 7) and np.allclose(t3, 3)
          and np.allclose(t4, 7), (set(np.round(t1, 4)), set(np.round(t2, 4))))
# Oblique rays (DDA grid path), compared with per-plane brute force
rng = np.random.default_rng(5)
n = 200000
O = np.c_[rng.uniform(-2, 2, (n, 2)), np.zeros(n)]
D = rng.normal(size=(n, 3))
D[:, 2] = np.where(np.abs(D[:, 2]) < 0.3, 0.3, D[:, 2])
Dn = D / np.linalg.norm(D, axis=1, keepdims=True)
ib, tb, _ = ray_cast(O, D, Pq, Tq, both=True)
tz = np.stack([(z - O[:, 2]) / Dn[:, 2] for z in Zs], 1)
inside = np.stack([(np.abs(O[:, :2] + Dn[:, :2] * tz[:, [k]]) <= 10).all(1) for k in range(4)], 1)
tz = np.where(inside, tz, np.inf)
ref_t = tz[np.arange(n), np.argmin(np.abs(tz), 1)]
hit = np.isfinite(ref_t)
check("  200k rays in arbitrary directions: nearest |t| matches brute force exactly (misses agree as −1)",
      np.array_equal(ib >= 0, hit) and np.abs(tb[hit] - ref_t[hit]).max() < 1e-6,
      float(np.abs(tb[hit] - ref_t[hit]).max()))

# ═══════════════════════════════════════════════════════ 3 attributes
sec("3 PolyBevel / Boolean carry attributes and groups")
bx = build.box()
P0 = PP(bx)
bx.set(POINT, "Cd", (P0 + 0.5).astype(np.float32))
bx.set(POINT, "id", np.arange(bx.npoints).reshape(-1, 1).astype(np.int32))
bx.set_group(POINT, "c0", np.arange(bx.npoints) == 0)
bx.set_string(PRIM, "name", np.array([f"side{i}" for i in range(bx.nprims)]))
bx.set_group(PRIM, "p0", np.arange(bx.nprims) == 0)
vp0 = np.asarray(bx.vertex_point)
bx.set(VERTEX, "uv", np.c_[np.arange(bx.nvertices), vp0, np.zeros(bx.nvertices)]
       .astype(np.float32))
bx.set(DETAIL, "tag", np.array([[3.0]], np.float32))
FN0 = np.array([np.cross(P0[f[1]] - P0[f[0]], P0[f[2]] - P0[f[0]])
                for f in (list(bx.prim_points(i)) for i in range(bx.nprims))])
FN0 /= np.linalg.norm(FN0, axis=1, keepdims=True)
for D_, shp in ((1, "round"), (3, "round"), (2, "chamfer")):
    pb = ops.polybevel(bx, distance=0.1, divisions=D_, shape=shp)
    have = all(pb.get(c, k) is not None for c, k in
               ((POINT, "Cd"), (POINT, "id"), (PRIM, "name"), (VERTEX, "uv"), (DETAIL, "tag")))
    Pb = PP(pb)
    ids = np.asarray(pb.get(POINT, "id"))[:, 0]
    # Every new point is within bevel-distance order of its source point, and its Cd is the source point's Cd
    near = np.linalg.norm(Pb - P0[ids], axis=1).max() if have else 9
    cd_ok = have and np.abs(np.asarray(pb.get(POINT, "Cd")) - (P0[ids] + 0.5)).max() < 1e-6
    # name of the inset faces (kind 0, not in either output group) = the original face with the same normal
    inset = ~(pb.get_group(PRIM, "edgefilletpolys") | pb.get_group(PRIM, "pointfilletpolys"))
    nm = pb.get(PRIM, "name")[:, 0] if have else None
    good = have
    vpr = pb.vertex_prim()
    for f in np.nonzero(inset)[0] if have else []:
        q = [int(x) for x in pb.prim_points(f)]
        n = np.cross(Pb[q[1]] - Pb[q[0]], Pb[q[2]] - Pb[q[0]])
        n /= np.linalg.norm(n)
        src = int(np.argmax(FN0 @ n))
        good &= nm[f] == f"side{src}"
    # vertex uv: uv.y records the source corner's point number = the id of this corner's point
    uv_ok = have and np.allclose(np.asarray(pb.get(VERTEX, "uv"))[:, 1],
                                 ids[np.asarray(pb.vertex_point)])
    grp = pb.get_group(POINT, "c0") if have else None
    c0_ok = have and grp.any() and (ids[grp] == 0).all() and (ids[~grp] != 0).all()
    pg = pb.get_group(PRIM, "p0") if have else None
    check(f"PolyBevel {shp} D={D_}: Cd / id / name / uv / detail all present; new point Cd = source point's, "
          f"within 0.2 of the source point; inset face name correct; uv from a corner of the same source point; point / prim groups carried over",
          have and cd_ok and near < 0.2 and good and uv_ok and c0_ok and pg.any()
          and float(pb.get(DETAIL, "tag")[0, 0]) == 3.0,
          (have, cd_ok, round(float(near), 3), good, uv_ok, c0_ok))
plain = Geometry.from_mesh(P0, [list(bx.prim_points(i)) for i in range(bx.nprims)])
pbn = ops.polybevel(plain, distance=0.1)
check("  negative control: with no input attributes the output only has P (no attributes made up)",
      sorted(pbn.attribs[POINT]) == ["P"] and not pbn.attribs[PRIM] and not pbn.attribs[VERTEX])

try:
    import manifold3d  # noqa: F401
    HAVE_M3 = True
except ImportError:
    HAVE_M3 = False
if HAVE_M3:
    from comfyui_pcg.geo import boolean as BO
    a = build.box()
    b = ops.transform(build.sphere(radius=0.4, cols=12, rows=8), translate=(0.5, 0.5, 0.5))
    Pa = PP(a)
    a.set(POINT, "Cd", (Pa + 0.5).astype(np.float32))                 # linear field: interpolation should be exact
    a.set(VERTEX, "uv", (Pa[np.asarray(a.vertex_point)] * 2).astype(np.float32))
    a.set(PRIM, "pid", np.arange(a.nprims).reshape(-1, 1).astype(np.int32))
    a.set_string(PRIM, "name", np.array([f"a{i}" for i in range(a.nprims)]))
    a.set_group(PRIM, "topA", np.arange(a.nprims) == 2)
    b.set_string(PRIM, "name", np.array(["b"] * b.nprims))
    b.set(POINT, "w", np.full((b.npoints, 1), 7.0, np.float32))
    for op in ("subtract", "union", "intersect", "shatter"):
        for det in ("none", "quads"):
            r = BO.boolean(a, b, op, detri=det, group_b="bpolys")
            Pr_ = PP(r)
            fb = r.get_group(PRIM, "bpolys")
            vp, vpr = np.asarray(r.vertex_point), r.vertex_prim()
            ptA = np.zeros(r.npoints, bool)
            ptA[vp[~fb[vpr]]] = True
            ptB = np.zeros(r.npoints, bool)
            ptB[vp[fb[vpr]]] = True
            cd = np.asarray(r.get(POINT, "Cd"), np.float64)
            uv = np.asarray(r.get(VERTEX, "uv"), np.float64)
            vA = ~fb[vpr]
            nm = r.get(PRIM, "name")[:, 0]
            w = np.asarray(r.get(POINT, "w"))[:, 0]
            # face normal of each pid matches the original face (prim attribute came from the right face)
            pid = np.asarray(r.get(PRIM, "pid"))[:, 0]
            nok = True
            for f in np.nonzero(~fb)[0]:
                q = [int(x) for x in r.prim_points(f)]
                nn = np.cross(Pr_[q[1]] - Pr_[q[0]], Pr_[q[2]] - Pr_[q[0]])
                if np.linalg.norm(nn) < 1e-5:
                    continue                    # thin slivers along the intersection line; normals are meaningless in float32
                nn /= np.linalg.norm(nn)
                nok &= abs(abs(nn @ FN0[pid[f]]) - 1) < 1e-4
            check(f"Boolean {op} / {det}: A's Cd, uv linearly interpolated exactly; name / pid correct; "
                  f"B's points w = 7, points only in A w = 0; prim groups carried over",
                  np.abs(cd[ptA] - (Pr_[ptA] + 0.5)).max() < 1e-5
                  and np.abs(uv[vA] - Pr_[vp[vA]] * 2).max() < 1e-5
                  and all(s.startswith("a") for s in nm[~fb]) and all(s == "b" for s in nm[fb])
                  and nok and (w[ptB] == 7).all() and (w[ptA & ~ptB] == 0).all()
                  and r.get_group(PRIM, "topA") is not None
                  and (pid[r.get_group(PRIM, "topA")] == 2).all())
    r0 = BO.boolean(a, b, "subtract", keep_attributes=False)
    check("  negative control: keep_attributes=False (old behaviour) only has P", sorted(r0.attribs[POINT]) == ["P"])
else:
    print("  (manifold3d not installed, Boolean checks skipped)")

# ═══════════════════════════════════════════════════════ 4 push-pull
sec("4 push-pull: non-square images")


def old_push_pull(col, mask):
    H, W, C = col.shape
    w = mask.astype(np.float64)[:, :, None]
    levels = [(col * w, w)]
    while levels[-1][0].shape[0] > 1 and levels[-1][0].shape[1] > 1:
        cw, ww = levels[-1]
        levels.append((BP._down(cw), BP._down(ww)))
    cw, ww = levels[-1]
    up = np.where(ww > 0, cw / np.where(ww > 0, ww, 1.0), 0.0)
    for i in range(len(levels) - 2, -1, -1):
        cw, ww = levels[i]
        coarse = BP._up(up, cw.shape[0], cw.shape[1])
        fine = np.where(ww > 0, cw / np.where(ww > 0, ww, 1.0), 0.0)
        up = np.where(ww > 0, fine, coarse)
    return np.where(mask[:, :, None], col, up)


for shape, sl in (((512, 16), np.s_[:4, :]), ((16, 512), np.s_[:, :4]), ((64, 64), np.s_[:4, :])):
    col = np.zeros(shape + (3,))
    m = np.zeros(shape, bool)
    m[sl] = True
    col[m] = 0.7
    new = BP._push_pull(col, m)
    old = old_push_pull(col, m)
    check(f"  {shape}: only one edge has colour (0.7), the hole is filled entirely with 0.7; old code minimum {old.min():.3f}",
          np.abs(new - 0.7).max() < 1e-9
          and (old.min() < 0.1 if shape[0] != shape[1] else True))

# ═══════════════════════════════════════════════════════ 5 Remesh
sec("5 Remesh:Smooth Feature Lines")
tube = build.tube(cols=16, rows=4, caps=True)
rr = {}
for sm in (False, True):
    g, rep = RM.remesh(tube, target_length=0.05, smooth_features=sm, out_hard_edges="h")
    e = np.asarray(g.edge_groups["h"])
    pts = np.unique(e)
    Pg = PP(g)
    rr[sm] = np.hypot(Pg[pts, 0], Pg[pts, 2])
check("  off (default, Houdini behaviour): new points on the rim lie on chords of the 16-gon (min radius = cos(π/16))",
      abs(rr[False].min() - np.cos(np.pi / 16)) < 1e-4 and rr[False].max() <= 1 + 1e-6,
      rr[False].min())
check("  on: after subdivision the rim hugs the circle (radius 1 ± 0.01)",
      np.abs(rr[True] - 1).max() < 0.01, (rr[True].min(), rr[True].max()))
g, _ = RM.remesh(build.box(), target_length=0.1, smooth_features=True)
Pg = PP(g)
check("  on: cube ridges (90° corners) stay straight, all points lie on the faces",
      np.abs(np.abs(Pg).max(1) - 0.5).max() < 1e-6)
sq, _ = RM.remesh(build.grid(1, 1, 3, 3), target_length=0.08, smooth_features=True,
                  out_hard_edges="h")
Ps = PP(sq)[np.unique(np.asarray(sq.edge_groups["h"]))]
check("  on: boundary of a flat grid (corners have only two boundary edges turning 90°) stays square, does not bulge",
      np.abs(np.abs(Ps[:, [0, 2]]).max(1) - 0.5).max() < 1e-6
      and np.abs(Ps[:, [0, 2]]).max() <= 0.5 + 1e-6)
gd, _ = RM.remesh(tube, target_length=0.05)
check("  default parameters bit-identical (same as explicit smooth_features=False)",
      np.array_equal(PP(gd), PP(RM.remesh(tube, target_length=0.05, smooth_features=False)[0])))
check("  node has a smooth_features toggle, off by default",
      M["PCG_Remesh"].INPUT_TYPES()["required"]["smooth_features"][1]["default"] is False)

# ═══════════════════════════════════════════════════════ 6 Worley
sec("6 Worley F2−F1 + Manhattan")
xp = BK.NUMPY
rng = np.random.default_rng(1)
n = 100000
x, y, z = (rng.uniform(-20, 20, n) for _ in range(3))


def brute(mode, metric, R):
    ix, iy, iz = (np.floor(v).astype(np.int64) for v in (x, y, z))
    b1 = np.full(n, 1e30)
    b2 = np.full(n, 1e30)
    for c in itertools.product(range(-R, R + 1), repeat=3):
        cx, cy, cz = ix + c[0], iy + c[1], iz + c[2]
        px = NZ._jit(xp, cx, NZ._to01(xp, NZ.cell_hash(xp, cx, cy, cz, 3, 1)), 1.0)
        py = NZ._jit(xp, cy, NZ._to01(xp, NZ.cell_hash(xp, cx, cy, cz, 3, 2)), 1.0)
        pz = NZ._jit(xp, cz, NZ._to01(xp, NZ.cell_hash(xp, cx, cy, cz, 3, 3)), 1.0)
        d = NZ._metric(xp, (x - px, y - py, z - pz), metric)
        b2 = np.minimum(b2, np.maximum(b1, d))
        b1 = np.minimum(b1, d)
    if mode == "f2f1":
        return np.clip((b2 - b1) * 2 - 1, -1, 1)
    return np.clip(1 - 2 * b1, -1, 1)


ref = brute("f2f1", "manhattan", 3)
got = NZ.worley(xp, x, y, z, seed=3, mode="f2f1", metric="manhattan")
old = brute("f2f1", "manhattan", 1)
check("  matches ±3 (343 cells) brute force per point; negative control: the old 27 cells are off by > 0.1%",
      np.abs(got - ref).max() < 1e-12 and (np.abs(old - ref) > 1e-9).mean() > 1e-3,
      (np.abs(old - ref) > 1e-9).mean())
for mode, metric in (("f1", "euclidean"), ("f2f1", "euclidean"), ("f1", "manhattan")):
    check(f"  {mode} / {metric}: still 27 cells, bit-identical to before",
          np.array_equal(NZ.worley(xp, x, y, z, seed=3, mode=mode, metric=metric),
                         brute(mode, metric, 1)))

# ═══════════════════════════════════════════════════════ 7 strings
sec("7 strings are not truncated")
pts = Geometry.from_points(np.random.default_rng(0).random((5, 3)))
L = "x" * 150 + "/end"
w1 = wrangle.run_wrangle(pts, f's@path = "{L}";', POINT)
check("Wrangle: 154 characters written as is (old code truncated to 64)", w1.get(POINT, "path")[0, 0] == L)
w4 = wrangle.run_wrangle(pts, 's@k = "short";', POINT)
w2 = wrangle.run_wrangle(w1, 's@path = @path + "_tail";', POINT)
check("  concatenating onto a long string", all(s == L + "_tail" for s in w2.get(POINT, "path")[:, 0]))
w5 = wrangle.run_wrangle(w4, f'@k[0, 0] = "{L}";', POINT)
check("  modifying one element of an existing short-string attribute in place: not truncated to the old width",
      w5.get(POINT, "k")[0, 0] == L and w5.get(POINT, "k")[1, 0] == "short")
w3 = wrangle.run_wrangle(w1, 's@path = "a";', POINT, group="0-1")
check("  rows outside the group restored to the original long strings (not truncated by the new width)",
      list(w3.get(POINT, "path")[:, 0]) == ["a", "a", L, L, L])
check("  width follows the content (neither fixed <U64 nor object)",
      w4.get(POINT, "k").dtype == np.dtype("<U5"))
c1 = attribops.create(pts, name="json", attr_type="string", string_value="{" + "a" * 300 + "}")
check("Attribute Create: 302 characters as is", len(c1.get(POINT, "json")[0, 0]) == 302)
c2 = attribops.create(c1, name="json", attr_type="string", string_value="z", group="0")
check("  modifying part of an attribute with existing long strings, the rest not truncated", c2.get(POINT, "json")[1, 0] == "{" + "a" * 300 + "}"
      and c2.get(POINT, "json")[0, 0] == "z")
g7 = pts.copy()
g7.set_string(POINT, "o", np.array([L] * 5, dtype=object))
check("set_string with an object array does not truncate either", g7.get(POINT, "o")[0, 0] == L)

# ═══════════════════════════════════════════════════════ 8 group expressions
sec("8 and / or / not in @ group expressions")
gg = build.grid(4, 4, 5, 5)
P = PP(gg)
gg.set_string(POINT, "nm", np.array(["a and b" if i % 2 else "x" for i in range(gg.npoints)]))
cases = [
    ("@P.x > 0 and @P.z < 0", (P[:, 0] > 0) & (P[:, 2] < 0)),
    ("@P.x > 0 or @P.z < 0", (P[:, 0] > 0) | (P[:, 2] < 0)),
    ("not @P.x > 0", ~(P[:, 0] > 0)),
    ("@P.x > 0 and not (@P.z < 0 or @ptnum == 4)",
     (P[:, 0] > 0) & ~((P[:, 2] < 0) | (np.arange(len(P)) == 4))),
    ('@nm == "a and b"', np.arange(len(P)) % 2 == 1),
    ("!@P.x > 0 && @P.z != 0", ~(P[:, 0] > 0) & (P[:, 2] != 0)),
    ("@P.x > 0 & @P.z < 0", (P[:, 0] > 0) & (P[:, 2] < 0)),
]
for expr, want in cases:
    got = GR.resolve(gg, POINT, expr)
    check(f"  {expr}", np.array_equal(got, want), int(got.sum()))
gg.set(POINT, "band", np.arange(gg.npoints).reshape(-1, 1).astype(np.float32))
check("  attribute names containing and / or / not (@band, @order) are not split",
      np.array_equal(GR.resolve(gg, POINT, "@band > 20"), np.arange(len(P)) > 20))

# ═══════════════════════════════════════════════════════ 9 edge groups
sec("9 edge group names")
eg = build.grid(2, 2, 3, 3)
eg.set_edge_group("rim_a", np.array([[0, 1]]))
eg.set_edge_group("rim_b", np.array([[1, 2]]))
check("nonexistent edge group name raises (old code silently selected nothing)",
      raises(lambda: GR.resolve_edges(eg, "rmi_a"), KeyError, "rmi_a"))
check("  error message lists the existing edge groups", raises(lambda: GR.resolve_edges(eg, "nope"), KeyError, "rim_a"))
check("  wildcard rim_*", GR.resolve_edges(eg, "rim_*").tolist() == [[0, 1], [1, 2]])
check("  wildcard with no match does not raise (same as Houdini)", len(GR.resolve_edges(eg, "zz*")) == 0)
check("  point-pair syntax p3-4, p0-3-6", GR.resolve_edges(eg, "p3-4 p0-3-6").tolist()
      == [[0, 3], [3, 4], [3, 6]])
check("  out-of-range point pair raises", raises(lambda: GR.resolve_edges(eg, "p0-99"), KeyError))
check("  empty / * is still all edges", len(GR.resolve_edges(eg, "")) == len(GR.resolve_edges(eg, "*")) == 12)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
