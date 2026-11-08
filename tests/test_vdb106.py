"""
pcg106: VDB semantics, the VDB / Volume SOP nodes, and how volumes are shown in the viewport.

Analytic checks (sphere SDFs, linear fields, uniform flows ...) with negative controls. Sections:
  data model   active mask + background, vector grids, growing grids, existing volume ops keep masks
  viewport     fog = smoke (also when positive everywhere), SDF = closed iso-surface, bounds, Volume Visualization
  VDB nodes    create / activate / topology / level sets / fields
  Volume SOPs  the rest of Houdini's Volume family
"""
import json
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
from comfyui_pcg.geo import vdb as V, vdbcore as C, vdbsdf as S, vdbfield as F    # noqa: E402
from comfyui_pcg.geo import volmore as VM, volvis as VV, volops as VO, build      # noqa: E402
from comfyui_pcg.geo import volume as VOL, render                                   # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM, DETAIL, Geometry                      # noqa: E402
from comfyui_pcg.geo.ops import merge                                               # noqa: E402
from comfyui_pcg import viewport as VP                                              # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print("\n── " + t)


def raises(fn, text=""):
    try:
        fn()
    except Exception as e:
        return text in str(e)
    return False


def smp(g, i, P):
    vox, o, c = V.grid(g, i)
    return V.sample(vox, o, c, np.asarray(P, np.float64))


def run(node, **kw):
    c = M[node]
    it = c.INPUT_TYPES()
    args = {}
    for grp in ("required", "optional"):
        for k, s in (it.get(grp) or {}).items():
            if k in kw:
                args[k] = kw[k]
            elif grp == "required":
                t = s[0]
                o = s[1] if len(s) > 1 and isinstance(s[1], dict) else {}
                args[k] = t[0] if isinstance(t, (list, tuple)) else o.get("default")
    out = c().run(**args)
    if isinstance(out, dict):
        out = out["result"]
    return out


SPH = S.platonic("sphere", 0.6, (0, 0, 0), 0.05)          # SDF VDB, r = 0.6, band 3 voxels
VS = 0.05

# ═══════════════════════════════════════════════════════════════ data model
sec("data model: mask + background")
g = V.make((8, 8, 8), (0.7, 0.7, 0.7), (0, 0, 0), 2.0, V.CLASS_FOG, "d", True, 0.5)
m = np.zeros((8, 8, 8), bool)
m[2:4, 2:4, 2:4] = True
V.set_active(g, 0, m)
v = g.pdata(0, "voxels")
check("inactive voxels take the background, active ones keep their values",
      np.allclose(v[~m], 0.5) and np.allclose(v[m], 2.0))
check("  negative control: a dense volume (vdb = 0) is never rewritten",
      np.allclose(V.make((4, 4, 4), (1, 1, 1), fill=2.0, vdb=False).pdata(0, "voxels"), 2.0))
s = V.make((6, 6, 6), (1, 1, 1), (0, 0, 0), 0.0, V.CLASS_SDF, "s", True, 0.3)
vv = np.linspace(-1, 1, 216).reshape(6, 6, 6).astype(np.float32)
V.set_voxels(s, 0, vv, mask=np.abs(vv) < 0.2)
sv = s.pdata(0, "voxels")
check("an SDF's inactive voxels keep their sign: inside −background, outside +background",
      np.allclose(sv[(vv < -0.2)], -0.3) and np.allclose(sv[(vv > 0.2)], 0.3))
gg = g.copy()
V.grow(gg, 0, (-1, -1, -1), (1, 1, 1))
check("grow: the grid covers the box on its own lattice; new samples are inactive background",
      tuple(V.bounds(gg)[0]) <= (-1, -1, -1) and V.active(gg, 0).sum() == m.sum()
      and np.isclose(smp(gg, 0, [[0.9, 0.9, 0.9]])[0], 0.5))
vec = V.make((5, 5, 5), (1, 1, 1), (0, 0, 0), (1.0, 2.0, 3.0), V.CLASS_NONE, "vel", True, 0.0, True)
bl = VO.blur(vec, 0.2)
check("vector grids: Volume Blur works per component (a constant stays constant)",
      np.allclose(bl.pdata(0, "voxels"), [1, 2, 3], atol=1e-6))
rs, _ = VO.resample(g, "resolution", (16, 16, 16))
check("Volume Resample carries the active mask along (nearest)",
      V.has_mask(rs, 0) and V.active(rs, 0).shape == (16, 16, 16) and 0 < V.active(rs, 0).sum() < 16 ** 3)
w, _ = VO.wrangle(vec, "@value = @value * 2")
check("Volume Wrangle: @value is (N, 3) on a vector grid", np.allclose(w.pdata(0, "voxels"), [2, 4, 6]))

# ═══════════════════════════════════════════════════════════════ viewport
sec("viewport: smoke / closed iso-surface / bounds")
fog = VO.create_volume((16, 16, 16), (1, 1, 1), (0, 0, 0), 1.0, True, "density", None, 0, 0)
mesh, vols = VV.prepare(fog)
check("a fog volume that is positive everywhere is drawn as smoke (before pcg106: nothing at all)",
      len(vols) == 1 and vols[0]["mode"] == "smoke" and vols[0]["dmax"] > 0.99 and mesh.nprims == 0)
check("  the smoke box is the volume's extent", np.allclose(vols[0]["box"][0], -0.5) and np.allclose(vols[0]["box"][1], 0.5))
mesh, vols = VV.prepare(SPH)
check("an SDF is drawn as its iso-surface (no smoke)", mesh.nprims > 0 and vols[0]["mode"] == "iso")
cut = S.platonic("sphere", 0.6, (0, 0, 0), 0.05)
vx, o, c = V.grid(cut, 0)
sub = V.from_grid(vx[:, :, : vx.shape[2] // 2], o, c, V.CLASS_SDF, "half", False)   # the grid cuts the sphere in half


def boundary_edges(g):
    tri = g.triangles()
    e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), 1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    return int((cnt == 1).sum())


closed = VOL.volume_to_polygons(sub, 0.0, close=True)
openm = VOL.volume_to_polygons(sub, 0.0, close=False)
check("an SDF cut by the grid boundary is capped (closed: no boundary edges)", boundary_edges(closed) == 0,
      boundary_edges(closed))
check("  negative control: without closing the cut is an open hole", boundary_edges(openm) > 0)
P = np.asarray(closed.get(POINT, "P"))
vmesh, _ = VV.prepare(sub)
check("  the viewport uses the closed surface (no holes where the grid cuts the SDF)",
      vmesh.nprims > 0 and boundary_edges(vmesh) == 0, boundary_edges(vmesh))
check("  the cap lies on the grid boundary (vertices clamped into the box)",
      P[:, 0].max() <= o[0] + c[0] * (vx.shape[2] // 2 - 1) + 1e-5)
bb = VP.bbox_with_volumes(fog)
check("the published bounding box covers the volume (its single point is only the centre)",
      np.allclose(bb[0], -0.5) and np.allclose(bb[1], 0.5))
blob = VO.blur(VOL.points_to_volume(build.sphere(0.5), (24, 24, 24)), 0.3)
enc = VP.encode(blob)
hl = int.from_bytes(enc[4:8], "little")
hdr = json.loads(enc[8:8 + hl])
check("encode: smoke volumes come with a half-float density buffer of the display resolution",
      "volumes" in hdr and hdr["buffers"][hdr["volumes"][0]["density_buf"]]["dtype"] == "uint16"
      and hdr["buffers"][hdr["volumes"][0]["density_buf"]]["length"] == 2 * int(np.prod(hdr["volumes"][0]["res"])))
big = VO.create_volume((200, 40, 40), (5, 1, 1), (0, 0, 0), 1.0, True, "density", None, 0, 0)
_, bv = VV.prepare(big)
check("large grids are resampled for display only (≤ 128 per axis)", max(bv[0]["res"]) <= 128 and bv[0]["res_full"][0] == 200)
check("vector grids are invisible by default (box only)", VV.prepare(vec)[1][0]["mode"] == "invisible")
vis = VV.visualize(merge(fog, SPH), "rainbow", density_field="density")
_, vv = VV.prepare(vis)
check("Volume Visualization: only the density field is drawn, in its mode",
      len(vv) == 1 and vv[0]["mode"] == "rainbow" and "color_buf" in vv[0])
vis2 = VV.visualize(SPH, "iso", iso=0.1)
m2, _ = VV.prepare(vis2)
r2 = np.linalg.norm(np.asarray(m2.get(POINT, "P")), axis=1)
check("  Iso Surface at Iso Value 0.1 is the sphere of radius r + 0.1", abs(np.median(r2) - 0.7) < 0.02, np.median(r2))
cd = merge(fog, V.make((16, 16, 16), (1, 1, 1), (0, 0, 0), (1.0, 0.0, 0.0), V.CLASS_NONE, "Cd", False, 0.0, True))
_, vv3 = VV.prepare(VV.visualize(cd, "smoke", "density", "Cd"))
ab = vv3[0]["arrays"][vv3[0]["color_buf"]][0]
check("  a vector diffuse field colours the smoke (Cd = red)", np.all(ab[..., 0] == 255) and np.all(ab[..., 1] == 0))

# ═══════════════════════════════════════════════════════════════ VDB: create / topology
sec("VDB / Activate / Densify / Prune / Clip / Fill")
e = C.create("density", "fog", False, 0.1, None, (1, 1, 1))
check("VDB: empty by default (no active voxels), every voxel = background",
      V.active(e, 0).sum() == 0 and np.allclose(e.pdata(0, "voxels"), 0))
e2 = C.create("surface", "sdf", False, 0.1, None, (1, 1, 1))
check("  an SDF's default background is 3 voxels", np.isclose(V.background(e2, 0), 0.3))
e3 = C.create("density", "fog", False, 0.1, None, (1, 1, 1), fill=True, value=2.0)
check("  Fill Active: every voxel active with Value", V.active(e3, 0).all() and np.allclose(e3.pdata(0, "voxels"), 2))
a, r = C.activate(e, "", "union", "voxel", True, 3.0, vmin=(2, 2, 2), vmax=(4, 5, 6))
check("Activate Voxel: the inclusive index box (3 × 4 × 5 = 60) becomes active with Value",
      r["active_voxels"] == [60] and np.isclose(a.pdata(0, "voxels")[2, 2, 2], 3.0))
one, _ = C.activate(e, "", "union", "voxel", vmin=(5, 5, 5), vmax=(5, 5, 5))
x1, _ = C.activate(one, "", "union", "expand", expand=1, pattern="face")
x3, _ = C.activate(one, "", "union", "expand", expand=1, pattern="faceedgevertex")
check("Expand: one voxel + 1 face neighbour = 7, with edges and vertices = 27",
      V.active(x1, 0).sum() == 7 and V.active(x3, 0).sum() == 27)
i2, _ = C.activate(a, "", "intersect", "voxel", vmin=(0, 0, 0), vmax=(2, 2, 2))
s2, _ = C.activate(a, "", "subtract", "voxel", vmin=(0, 0, 0), vmax=(2, 2, 2))
c2, _ = C.activate(a, "", "copy", "voxel", vmin=(0, 0, 0), vmax=(1, 1, 1))
check("Intersect / A − B / Copy follow their definitions (1, 59, 8 voxels)",
      (V.active(i2, 0).sum(), V.active(s2, 0).sum(), V.active(c2, 0).sum()) == (1, 59, 8))
check("  intersect resets the dropped voxels to the background", np.isclose(i2.pdata(0, "voxels")[3, 3, 3], 0.0))
pos, _ = C.activate(e, "", "union", "position", center=(0, 0, 0), size=(0.1, 0.1, 0.1))
check("Position: voxels touching the box (centre ± 0.05 with 0.1 voxels -> 2³ = 8 cells... touching -> 27 or 8)",
      V.active(pos, 0).sum() in (8, 27), V.active(pos, 0).sum())
dz, _ = C.activate(e3, "", "union", "deactivate", bg_tolerance=0.5)
check("Deactivate: values within tolerance of the background turn inactive (2 vs 0: none)", V.active(dz, 0).all())
dz2, _ = C.activate(e3, "", "union", "deactivate", bg_tolerance=2.5)
check("  with a tolerance above 2 all turn inactive", V.active(dz2, 0).sum() == 0)
pr, _ = C.prune_vdb(SPH, "", "levelset")
check("Prune Level Set: no active voxel at |φ| ≥ background", (np.abs(pr.pdata(0, "voxels")[V.active(pr, 0)])
                                                          < V.background(pr, 0)).all())
fs, _ = C.activate(SPH, "", "union", "fillsdf")
check("Activate Fill SDF: the whole inside becomes active", V.active(fs, 0)[fs.pdata(0, "voxels") < 0].all())
dn = C.densify(SPH)
check("Densify: everything active", not V.has_mask(dn, 0))
cl, _ = C.clip(SPH, "", True, "geometry", build.box(size=(0.6, 0.6, 0.6)))
Pc = V.world_points(*V.grid(cl, 0)[1:], cl.pdata(0, "voxels").shape)[V.active(cl, 0)]
check("Clip: only voxels inside the clip box stay active", len(Pc) > 0 and (np.abs(Pc) <= 0.3 + 1e-6).all())
cl2, _ = C.clip(SPH, "", False, "geometry", build.box(size=(0.6, 0.6, 0.6)))
check("  Keep Inside off keeps the complement", V.active(cl2, 0).sum() + V.active(cl, 0).sum() == V.active(SPH, 0).sum())
big = S.platonic("sphere", 0.6, (0, 0, 0), 0.05)
half, _ = C.clip(big, "", True, "geometry", build.box(size=(2, 2, 1), center=(0, 0, 0.5)))
vin = smp(half, 0, [[0, 0, 0.3], [0, 0, -0.3], [0, 0, 0.0]])
check("pcg108 Clip on a level set: the cut-away interior reads outside (+background), the kept part inside",
      vin[0] < 0 and vin[1] > 0 and np.isclose(vin[1], V.background(half, 0)), vin)
naive = big.copy()
V.set_active(naive, 0, V.active(big, 0) & (V.world_points(*V.grid(big, 0)[1:], V.grid(big, 0)[0].shape)[..., 2] >= 0))
check("  negative control: deactivating alone (pcg106) keeps the cut-away part inside", smp(naive, 0, [[0, 0, -0.3]])[0] < 0)
fl = C.fill(e, "", "index", np.array([0, 0, 0]), np.array([1, 1, 1]), value=(7, 0, 0))
check("Fill index box: 8 voxels active with 7", V.active(fl, 0).sum() == 8 and np.isclose(fl.pdata(0, "voxels")[0, 0, 0], 7))

sec("Topology to SDF / Activate SDF / Diagnostics / Visualize Tree")
blk, _ = C.activate(C.create("d", "fog", False, 0.1, None, (2, 2, 2)), "", "union", "voxel",
                    vmin=(5, 5, 5), vmax=(14, 14, 14))
t2s = C.topology_to_sdf(blk, "", 3, None, 0, 0, 0)
vx, o, c = V.grid(t2s, 0)
ctr = o + c * 9.5
# the solid's faces are half a voxel outside the outermost active samples: half size = 5 voxels
check("Topology to SDF: zero crossing half a voxel outside the active block",
      abs(smp(t2s, 0, [ctr + [0.5, 0, 0]])[0]) < 0.02 and smp(t2s, 0, [ctr + [0.3, 0, 0]])[0] < 0)
asd, _ = C.activate_sdf(SPH, "", 2.0)
act = V.active(asd, 0)
d = asd.pdata(0, "voxels")
P = V.world_points(*V.grid(asd, 0)[1:], d.shape)
true = np.linalg.norm(P, axis=-1) - 0.6
check("Activate SDF: active voxels lie in the band |φ| ≤ 2 voxels, inactive ones hold ±(band width)",
      (np.abs(d[act]) <= 2 * VS + 1e-6).all() and np.allclose(np.abs(d[~act]), 2 * VS))
check("  with distances within 0.1 voxel of the exact sphere distance", np.abs(d[act] - true[act]).max() < 0.1 * VS,
      np.abs(d[act] - true[act]).max())
bad = SPH.copy()
bv = np.array(bad.pdata(0, "voxels"))
bv[3, 3, 3] = np.nan
bad.set_pdata(0, "voxels", bv)
dg, rep = C.diagnostics(bad)
check("Diagnostics: a NaN is found", rep["volumes"][0]["non_finite"] == 1 and not rep["all_passed"])
dg2, rep2 = C.diagnostics(bad, repair=True)
check("  Repair replaces it (a second pass is clean)", C.diagnostics(dg2)[1]["volumes"][0]["non_finite"] == 0)
check("  a valid SDF passes the gradient test", C.diagnostics(SPH)[1]["volumes"][0].get("gradient_off", 1) == 0)
mk = np.zeros((16, 16, 16), bool)
mk[0, 0, 0] = mk[15, 15, 15] = mk[9, 1, 1] = True
tg = V.make((16, 16, 16), (1.5, 1.5, 1.5), mask=mk)
tree = C.visualize_tree(tg, "", "boxes", "none", "none", False)
check("Visualize Tree: one wireframe box (12 edges) per 8³ leaf holding active voxels (3 leaves)",
      tree.nprims == 3 * 12, tree.nprims)

sec("Metadata / Vector Merge & Split / Transform / LOD / Merge / Segment / Remap / Convert")
md = C.metadata(e, "", True, "fooname", True, "sdf", True, 0.25)
check("Metadata: name, class, background", V.name_of(md, 0) == "fooname" and V.grid_class(md, 0) == 0
      and np.isclose(V.background(md, 0), 0.25))
comps = [V.make((4, 5, 6), (1, 1, 1), (0, 0, 0), float(k + 1), V.CLASS_NONE, f"vel.{a}", False) for k, a in enumerate("xyz")]
vm = C.vector_merge(merge(*comps))
check("Vector Merge: vel.x / vel.y / vel.z -> one vector grid 'vel' = (1, 2, 3)",
      vm.nprims == 1 and V.name_of(vm, 0) == "vel" and np.allclose(vm.pdata(0, "voxels"), [1, 2, 3]))
sp = C.vector_split(vm)
check("Vector Split undoes it", sorted(V.name_of(sp, i) for i in range(sp.nprims)) == ["vel.x", "vel.y", "vel.z"]
      and np.allclose(sp.pdata([V.name_of(sp, i) for i in range(3)].index("vel.y"), "voxels"), 2))
tr = C.transform(SPH, "", (0.5, 0, 0))
check("Transform translate: exact (φ(p + t) = φ(p))", np.isclose(smp(tr, 0, [[1.1, 0, 0]])[0], smp(SPH, 0, [[0.6, 0, 0]])[0]))
tr2 = C.transform(SPH, "", (0, 0, 0), (0, 0, 0), (2, 2, 2))
check("  scale 2: the surface at radius 1.2", abs(smp(tr2, 0, [[1.2, 0, 0]])[0]) < 0.02)
trr = C.transform(SPH, "", (0, 0, 0), (0, 0, 45))
check("  rotation resamples (a sphere stays a sphere)", abs(smp(trr, 0, [[0.6, 0, 0]])[0]) < 0.02)
lod = C.lod(SPH, "", "single", 1.0)
check("LOD level 1: every second sample", lod.pdata(0, "voxels").shape[0] == (SPH.pdata(0, "voxels").shape[0] + 1) // 2)
two = merge(S.platonic("sphere", 0.3, (-0.5, 0, 0), 0.05), S.platonic("sphere", 0.3, (0.5, 0, 0), 0.05))
mg, mr = C.merge_vdbs(two)
check("VDB Merge (same name, SDF union): one prim covering both, φ = min",
      mg.nprims == 1 and smp(mg, 0, [[-0.5, 0, 0]])[0] < 0 and smp(mg, 0, [[0.5, 0, 0]])[0] < 0)
sg, sr = C.segment(mg)
check("Segment: the union splits back into its two pieces", sr["pieces"] == [2] and sg.nprims == 2)
rm = C.remap(SPH, "", "clamp", "clamp", (-0.15, 0.15), (0, 1))
check("Remap: linear input range -> output range", np.isclose(smp(rm, 0, [[0.6, 0, 0]])[0], 0.5, atol=0.03))
rm2 = C.remap(SPH, "", "preserve", "preserve", (-0.05, 0.05), (0, 1))
check("  Preserve keeps values outside the input range", np.isclose(smp(rm2, 0, [[0, 0, 0]])[0], -0.15))
cf = C.convert(SPH, "", "fog")
check("Convert SDF -> fog: 0 outside, 1 deep inside, 0.5 halfway through the interior band",
      np.isclose(smp(cf, 0, [[0.8, 0, 0]])[0], 0) and np.isclose(smp(cf, 0, [[0, 0, 0]])[0], 1)
      and abs(smp(cf, 0, [[0.6 - 0.075, 0, 0]])[0] - 0.5) < 0.05)
cs = C.convert(cf, "", "sdf", fog_iso=0.5)
check("Convert fog -> SDF: the 0.5 contour is the new surface", abs(smp(cs, 0, [[0.525, 0, 0]])[0]) < 0.01,
      smp(cs, 0, [[0.525, 0, 0]])[0])
cp = C.convert(SPH, "", "polygons")
check("Convert to polygons: closed, at radius 0.6", boundary_edges(cp) == 0
      and abs(np.median(np.linalg.norm(cp.get(POINT, "P"), axis=1)) - 0.6) < 0.01)
cv = C.convert(SPH, "", "volume")
check("Convert to volume: no mask, not a VDB", not V.has_mask(cv, 0) and not V.is_vdb(cv, 0))

# ═══════════════════════════════════════════════════════════════ VDB: level sets
sec("from Polygons / Particles / Particle Fluid / Platonic")
sm = build.sphere(0.6, cols=48, rows=32)
fp = S.from_polygons(sm, 0.05, 3, 3, False, True, False, True, "surface", True, "density", "P")
names = [V.name_of(fp, i) for i in range(fp.nprims)]
check("from Polygons: SDF + fog + one attribute VDB per listed attribute", names == ["surface", "density", "P"])
check("  Fill Interior: the centre is at −r (exact distance to the faceted mesh)",
      abs(smp(fp, 0, [[0, 0, 0]])[0] + 0.6) < 0.01, smp(fp, 0, [[0, 0, 0]])[0])
fp2 = S.from_polygons(sm, 0.05, 3, 3)
check("  without it the inside is clamped to −interior band", np.isclose(smp(fp2, 0, [[0, 0, 0]])[0], -0.15))
Pa = fp.pdata(2, "voxels")
act = V.active(fp, 2)
Pw = V.world_points(*V.grid(fp, 2)[1:], Pa.shape[:3])
nrm = Pw / np.maximum(np.linalg.norm(Pw, axis=-1, keepdims=True), 1e-9)
err = np.linalg.norm(Pa[act] - 0.6 * nrm[act], axis=-1)
check("  attribute P: the closest surface point (≈ 0.6 × the direction) within the band (faceted mesh)",
      np.median(err) < 0.005 and err.max() < 0.04, (np.median(err), err.max()))
ub = S.from_polygons(sm, 0.05, 3, 3, unsigned=True)
check("  Unsigned: no negative values", (ub.pdata(0, "voxels") >= 0).all())
pt = build.points_from_array(np.array([[0.0, 0, 0]]))
pt.set(POINT, "pscale", np.array([[0.4]], np.float32))
fpp, _ = S.from_particles(pt, 0.05)
check("from Particles: one particle = a sphere of radius pscale", abs(smp(fpp, 0, [[0.4, 0, 0]])[0]) < 1e-3)
small = pt.copy()
small.set(POINT, "pscale", np.array([[0.01]], np.float32))
check("  particles below Minimum Radius are ignored (here: all -> clear error)",
      raises(lambda: S.from_particles(small, 0.05), "large enough"))
cloud = build.points_from_array(np.random.default_rng(0).uniform(-0.3, 0.3, (2000, 3)))
pf = S.from_particle_fluid(cloud, 0.06)
check("from Particle Fluid: one closed blob around the particles", smp(pf, 0, [[0, 0, 0]])[0] < 0
      and smp(pf, 0, [[0.6, 0, 0]])[0] > 0)
cube = S.platonic("cube", 0.6 * np.sqrt(3), (0, 0, 0), 0.05)
check("Platonic cube (circumradius r√3 -> half size r): φ = 0 at a face centre, −r at the centre",
      abs(smp(cube, 0, [[0.6, 0, 0]])[0]) < 1e-3 and np.isclose(smp(cube, 0, [[0, 0, 0]])[0], -0.15))

sec("Renormalize / Rebuild / Morph / Fracture / to Spheres / Noise / Extrapolate")
def gradlen(g, p):
    v, o, c = V.grid(g, 0)
    gr = V.grad(v, c)
    return float(np.linalg.norm([V.sample(gr[..., k], o, c, np.array([p]))[0] for k in range(3)]))


blurred = VO.blur(S.platonic("sphere", 0.6, (0, 0, 0), 0.05, half_width=8), 0.3)
check("  (setup: a blurred SDF has |∇φ| < 1 near its surface)", gradlen(blurred, [0.6, 0, 0]) < 0.95,
      gradlen(blurred, [0.6, 0, 0]))
rn = S.renormalize(blurred)
check("Renormalize SDF: |∇φ| back to ≈ 1 near the surface", abs(gradlen(rn, [0.6, 0, 0]) - 1) < 0.05,
      gradlen(rn, [0.6, 0, 0]))
fogs = S.platonic("sphere", 0.5, (0, 0, 0), 0.05, fog=True)
rb = S.rebuild(fogs, "", 0.5)
check("Rebuild SDF from fog at 0.5: an SDF with the surface on that contour", V.grid_class(rb, 0) == 0
      and abs(smp(rb, 0, [[0.5 - 0.075, 0, 0]])[0]) < 0.01)
tgt = S.platonic("sphere", 0.45, (0, 0, 0), 0.05)
src = S.platonic("sphere", 0.6, (0, 0, 0), 0.05)
mo, mr = S.morph(src, tgt, "", "", 3.0)
check("Morph SDF: a long timestep ends at the target surface", abs(smp(mo, 0, [[0.45, 0, 0]])[0]) < 0.02,
      smp(mo, 0, [[0.45, 0, 0]])[0])
mo0, _ = S.morph(src, tgt, "", "", 0.0)
check("  timestep 0 changes nothing", np.allclose(mo0.pdata(0, "voxels"), src.pdata(0, "voxels")))
fr, frr = S.fracture(src, build.box(size=(3, 3, 3), center=(0, 1.5, 0)))
check("Fracture with a half-space cutter: two fragments", frr["volumes"][0]["fragments"] == 2 and fr.nprims == 2)
uni = np.minimum(fr.pdata(0, "voxels"), fr.pdata(1, "voxels"))
Pfr = V.world_points(*V.grid(fr, 0)[1:], uni.shape)
away = np.abs(Pfr[..., 1]) > 0.16                    # away from the cut plane y = 0 (beyond the band)
check("  together they are the original away from the cut (min of the fragments = φ)",
      np.allclose(uni[away], src.pdata(0, "voxels")[away], atol=1e-5))
spf = S.to_spheres(src, "", 0.0, False, True, 1.0, False, 100, True, 1, True, 20, 4000, False)
Ps = np.asarray(spf.get(POINT, "P"))
Rs = np.asarray(spf.get(POINT, "pscale"))[:, 0]
dd = np.linalg.norm(Ps[:, None] - Ps[None], axis=-1) - Rs[:, None] - Rs[None]
np.fill_diagonal(dd, 1)
check("to Spheres: the first sphere is the deepest (≈ the sphere radius)", Rs[0] > 0.5, Rs[0])
check("  non-overlapping spheres do not intersect", dd.min() > -0.02, dd.min())
check("  all spheres are inside", (np.linalg.norm(Ps, axis=1) + Rs <= 0.6 + 0.03).all())
nz0 = S.noise(src, "", 0.0)
nz = S.noise(src, "", 0.05, 4.0)
check("Noise: amplitude 0 changes nothing, > 0 moves the surface",
      np.allclose(nz0.pdata(0, "voxels"), src.pdata(0, "voxels"))
      and not np.allclose(nz.pdata(0, "voxels"), src.pdata(0, "voxels")))
ex = S.extrapolate(src, "", "dilate", 2)
check("Extrapolate: Expand SDF Narrowband widens the band by 2 voxels", np.isclose(V.background(ex, 0), 0.25)
      and V.active(ex, 0).sum() > V.active(src, 0).sum())
field = V.from_grid(V.world_points(*V.grid(src, 0)[1:], src.pdata(0, "voxels").shape)[..., 1],
                    V.grid(src, 0)[1], V.grid(src, 0)[2], V.CLASS_NONE, "f", True)
ext = S.extrapolate(merge(src, field), "0", "sdfext", ext_group="f")
check("  Extend Fields: values are copied from the closest surface voxel (f = y extended along normals: f(0, 0.9, 0) ≈ 0.6)",
      abs(smp(ext, 1, [[0, 0.75, 0]])[0] - 0.6) < 0.06, smp(ext, 1, [[0, 0.75, 0]])[0])

sec("Occlusion Mask / Ray / Volume SDF")
cam = render.camera(None, "perspective", (0, 0, 5))
om = S.occlusion_mask(src, cam, "", 0, 64)
check("Occlusion Mask: behind the sphere hidden, in front visible",
      smp(om, 1, [[0, 0, -0.65]])[0] > 0.5 and smp(om, 1, [[0, 0, 0.7]])[0] < 0.5)
pts = build.points_from_array(np.array([[0, 0, 0.7], [0.1, 0.0, 0.72]]))
pts.set(POINT, "N", np.array([[0, 0, -1], [0, 0, -1]], np.float32))
ry, rr = S.ray(pts, src, store_dist=True)
check("Ray Intersection along N: lands on the surface", rr["hits"] == 2
      and np.allclose(np.linalg.norm(ry.get(POINT, "P"), axis=1), 0.6, atol=0.01))
ry2, _ = S.ray(pts, src, method="closestpoint")
check("  Closest Surface Point: radially onto the sphere",
      np.allclose(np.linalg.norm(ry2.get(POINT, "P"), axis=1), 0.6, atol=0.01))
far_pts = build.points_from_array(np.array([[2.0, 0, 0], [0, -1.5, 0.5], [0.05, 0.02, 0.0]]))
ry3, rr3 = S.ray(far_pts, src, method="closestpoint")
check("  pcg108 Closest Surface Point far outside the narrow band (and deep inside): onto the sphere",
      np.allclose(np.linalg.norm(ry3.get(POINT, "P"), axis=1), 0.6, atol=0.01) and rr3["hits"] == 3,
      np.linalg.norm(ry3.get(POINT, "P"), axis=1))
check("  negative control: the narrow band really is narrower than those distances (gradient 0 out there)",
      abs(smp(src, 0, [[2.0, 0, 0]])[0] - V.background(src, 0)) < 1e-6 and V.background(src, 0) < 1.0)
vsdf = S.volume_sdf(fogs, "", 0.5, True)
check("Volume SDF (fog, invert): the 0.5 contour becomes φ = 0", abs(smp(vsdf, 0, [[0.425, 0, 0]])[0]) < 0.01)


def band_ok(g, i):
    """pcg108: an SDF VDB has a positive background, its corners (far outside) read +background, and the active
    voxels are exactly those with |φ| < background."""
    vx, o, c = V.grid(g, i)
    bg = V.background(g, i)
    m = V.active(g, i)
    return (bg > 0 and np.isclose(vx[0, 0, 0], bg) and np.isclose(vx[-1, -1, -1], bg) and m.any()
            and bool(np.all(np.abs(vx[m]) < bg)) and np.allclose(np.abs(vx[~m]), bg, atol=1e-5))


check("  pcg108 Volume SDF on a fog VDB: proper narrow band (background > 0, outside reads +background)",
      band_ok(vsdf, 0), (V.background(vsdf, 0), float(V.grid(vsdf, 0)[0][0, 0, 0])))
naive = fogs.copy()
V.set_class(naive, 0, V.CLASS_SDF)
V.set_voxels(naive, 0, 0.5 - V.grid(fogs, 0)[0], mask="keep")
check("  negative control: the pcg106 result (background 0 kept from the fog) fails the band check",
      not band_ok(naive, 0))
sph = S.platonic("sphere", 0.5, (0, 0, 0), 0.05)          # background 3 voxels = 0.15
dil = VO.reshape_sdf(sph, "dilate", 0.3)
check("pcg108 Reshape SDF dilate by twice the band on a VDB: surface at r + d, still a narrow band",
      abs(smp(dil, 0, [[0.8, 0, 0]])[0]) < 0.02 and smp(dil, 0, [[0.6, 0, 0]])[0] < -0.05
      and smp(dil, 0, [[0.95, 0, 0]])[0] > 0.1 and band_ok(dil, 0),
      [float(smp(dil, 0, [[x, 0, 0]])[0]) for x in (0.6, 0.8, 0.95)])
ero = VO.reshape_sdf(sph, "erode", 0.25)
check("  erode by more than the band: surface at r − d", abs(smp(ero, 0, [[0.25, 0, 0]])[0]) < 0.02
      and smp(ero, 0, [[0.45, 0, 0]])[0] > 0.1 and band_ok(ero, 0))
bad = sph.copy()
V.set_voxels(bad, 0, V.grid(sph, 0)[0] - 0.3, mask="keep")
check("  negative control: the pcg106 offset (values only) puts the whole grid inside",
      smp(bad, 0, [[0.95, 0, 0]])[0] < 0 and not band_ok(bad, 0))
dense = VOL.make_volume((30, 30, 30), (2, 2, 2), (0, 0, 0))
Pd = V.world_points(*V.grid(dense, 0)[1:], (30, 30, 30))
dense.set_pdata(0, "voxels", (np.linalg.norm(Pd, axis=-1) - 0.5).astype(np.float32))
dd = VO.reshape_sdf(dense, "dilate", 0.2)
check("  dense SDF volumes unchanged by the fix: plain offset", np.allclose(V.grid(dd, 0)[0],
                                                                          V.grid(dense, 0)[0] - 0.2, atol=1e-5))

# ═══════════════════════════════════════════════════════════════ fields
sec("Analysis / Smooth / Advect / Advect Points")
lin = V.make((10, 10, 10), (1, 1, 1))
Pl = V.world_points(*V.grid(lin, 0)[1:], (10, 10, 10))
V.set_voxels(lin, 0, 2 * Pl[..., 0] + 3 * Pl[..., 1] - Pl[..., 2])
ga, _ = F.analysis(lin, "", "gradient")
check("Analysis gradient of 2x + 3y − z = (2, 3, −1) everywhere", np.allclose(ga.pdata(0, "voxels"), [2, 3, -1], atol=1e-4))
cu, _ = F.analysis(src, "", "curvature")
check("  curvature of a sphere of radius 0.6 = 2 / 0.6", abs(smp(cu, 0, [[0.6, 0, 0]])[0] - 2 / 0.6) < 0.1)
pv = V.from_grid(Pl, V.grid(lin, 0)[1], V.grid(lin, 0)[2], V.CLASS_NONE, "p")
dv, _ = F.analysis(pv, "", "divergence")
check("  divergence of (x, y, z) = 3", np.allclose(dv.pdata(0, "voxels"), 3, atol=1e-4))
rot = V.from_grid(np.stack([-Pl[..., 1], Pl[..., 0], 0 * Pl[..., 0]], -1), V.grid(lin, 0)[1], V.grid(lin, 0)[2],
                  V.CLASS_NONE, "r")
cr, _ = F.analysis(rot, "", "curl")
check("  curl of (−y, x, 0) = (0, 0, 2)", np.allclose(cr.pdata(0, "voxels"), [0, 0, 2], atol=1e-4))
ln, _ = F.analysis(rot, "", "length")
check("  length of (−y, x, 0) = √(x² + y²)", np.allclose(ln.pdata(0, "voxels"), np.hypot(Pl[..., 0], Pl[..., 1]), atol=1e-5))
check("  a scalar-only operator on a vector grid is refused clearly", raises(lambda: F.analysis(rot, "", "gradient"), "scalar"))
delta = V.make((9, 9, 9), (1, 1, 1))
dvv = np.zeros((9, 9, 9), np.float32)
dvv[4, 4, 4] = 27
V.set_voxels(delta, 0, dvv)
smo = F.smooth(delta, "", "mean", False, 1, 0.1, 1)
check("Smooth mean (radius 1, 1 pass): a spike of 27 becomes 1 over its 3³ neighbourhood",
      np.allclose(smo.pdata(0, "voxels")[3:6, 3:6, 3:6], 1))
dm = delta.copy()
mm = np.zeros((9, 9, 9), bool)
mm[4, 4, 4] = True
V.set_vdb(dm, 0, True)
V.set_active(dm, 0, mm)
check("  only active voxels change", np.allclose(F.smooth(dm, "", "mean", False, 1, 0.1, 1).pdata(0, "voxels")[0, 0, 0], 0))
blob = S.platonic("sphere", 0.3, (0, 0, 0), 0.05, fog=True)
velf = V.make((20, 20, 20), (3, 3, 3), (0, 0, 0), (1.0, 0.0, 0.0), V.CLASS_NONE, "vel", True, 0.0, True)
adv = F.advect(blob, velf, "", "", True, 0.4)


def centroid(g, i):
    v, o, c = V.grid(g, i)
    Pw = V.world_points(o, c, v.shape)
    return (Pw * v[..., None]).sum((0, 1, 2)) / v.sum()


check("Advect: a uniform velocity moves the blob by v·t (the VDB grid grows to keep it)",
      np.allclose(centroid(adv, 0), [0.4, 0, 0], atol=0.01), centroid(adv, 0))
pts = build.points_from_array(np.array([[0.0, 0, 0]]))
ap = F.advect_points(pts, velf, "", "", "advection", "rk4", 0.5, 5)
check("Advect Points: uniform flow moves points by v·t", np.allclose(ap.get(POINT, "P"), [[0.5, 0, 0]], atol=1e-5))
swirl = V.make((40, 40, 4), (4, 4, 0.3), (0, 0, 0), 0.0, V.CLASS_NONE, "vel", False, 0.0, True)
Pw = V.world_points(*V.grid(swirl, 0)[1:], swirl.pdata(0, "voxels").shape[:3])
V.set_voxels(swirl, 0, np.stack([-Pw[..., 1], Pw[..., 0], 0 * Pw[..., 0]], -1))
p1 = build.points_from_array(np.array([[1.0, 0, 0]]))
r4 = np.linalg.norm(F.advect_points(p1, swirl, "", "", "advection", "rk4", 3.0, 6).get(POINT, "P")[0, :2])
r1 = np.linalg.norm(F.advect_points(p1, swirl, "", "", "advection", "rk1", 3.0, 6).get(POINT, "P")[0, :2])
check("  RK4 keeps a point on its circle in a rotation field; RK1 (negative control) spirals out",
      abs(r4 - 1) < 0.02 and r1 > 1.2, (r4, r1))

sec("Project Non-Divergent / Potential Flow")
gridP = V.make((24, 24, 24), (1, 1, 1), (0, 0, 0), 0.0, V.CLASS_NONE, "vel", False, 0.0, True)
Pw = V.world_points(*V.grid(gridP, 0)[1:], (24, 24, 24))
u = np.stack([np.sin(3 * Pw[..., 0]), np.cos(2 * Pw[..., 1]), Pw[..., 2] ** 2], -1)
V.set_voxels(gridP, 0, u)
pn, pr = F.project_non_divergent(gridP, "", 2000, 1e-8)
before = np.abs(F.divergence(u, V.grid(gridP, 0)[2]))[3:-3, 3:-3, 3:-3].mean()
after = np.abs(F.divergence(pn.pdata(0, "voxels"), V.grid(gridP, 0)[2]))[3:-3, 3:-3, 3:-3].mean()
check("Project Non-Divergent: the interior divergence drops by more than 10×", after < before / 10, (before, after))
pfl = F.potential_flow(src, "", 24, 4000, 1e-9, (1.0, 0.0, 0.0))
vp, op_, cp_ = V.grid(pfl, 1)
pv = pfl.pdata(1, "voxels")


def ux(p):
    return float(V.sample(pv, op_, cp_, np.array([p]))[0][0])


# flow past a sphere (radius R): on the axis u = U(1 − R³/r³), at the side u = U(1 + R³/(2r³))
R = 0.6
check("Potential Flow matches flow past a sphere: side r = 0.95",
      abs(ux([0, 0.95, 0]) - (1 + R ** 3 / (2 * 0.95 ** 3))) < 0.06, ux([0, 0.95, 0]))
check("  front stagnation side r = 0.65", abs(ux([-0.65, 0, 0]) - (1 - R ** 3 / 0.65 ** 3)) < 0.06, ux([-0.65, 0, 0]))
check("  near the side of the sphere faster than the background", ux([0, 0.65, 0]) > 1.2, ux([0, 0.65, 0]))

sec("Combine / Resample / Points Group / Scatter")
A = V.make((5, 5, 5), (1, 1, 1), fill=2.0)
B = V.make((5, 5, 5), (1, 1, 1), fill=3.0)
check("Combine add / multiply / maximum / copy B",
      [float(F.combine(A, B, op=o).pdata(0, "voxels")[0, 0, 0]) for o in ("add", "multiply", "maximum", "copyb")]
      == [5.0, 6.0, 3.0, 3.0])
check("  A × A Multiplier with B × B Multiplier", np.isclose(F.combine(A, B, op="add", amult=2, bmult=-1).pdata(0, "voxels")[0, 0, 0], 1))
a1, b1 = S.platonic("sphere", 0.3, (-0.2, 0, 0), 0.05), S.platonic("sphere", 0.3, (0.6, 0, 0), 0.05)
un = F.combine(a1, b1, op="sdfunion")
check("  SDF Union: A's grid grows to hold B; inside both spheres", smp(un, 0, [[0.6, 0, 0]])[0] < -0.1
      and smp(un, 0, [[-0.2, 0, 0]])[0] < -0.1)
diff = F.combine(a1, S.platonic("sphere", 0.3, (0.0, 0, 0), 0.05), op="sdfdifference")
check("  SDF Difference: the overlap is removed", smp(diff, 0, [[0.0, 0, 0]])[0] > 0 and smp(diff, 0, [[-0.4, 0, 0]])[0] < 0)
ma = V.make((6, 6, 6), (1, 1, 1), mask=np.arange(216).reshape(6, 6, 6) < 100)
mb = V.make((6, 6, 6), (1, 1, 1), mask=np.arange(216).reshape(6, 6, 6) >= 50)
check("  Activity Union / Intersection / Difference work on the masks",
      [int(V.active(F.combine(ma, mb, op=o), 0).sum()) for o in ("topounion", "topointersect", "topodifference")]
      == [216, 50, 50])
rsm = F.resample(src, "", "voxelsizeonly", voxel_size=0.025)
check("Resample to half the voxel size: twice the samples, same surface",
      rsm.pdata(0, "voxels").shape[0] == 2 * src.pdata(0, "voxels").shape[0] - 1 and abs(smp(rsm, 0, [[0.6, 0, 0]])[0]) < 0.01)
rnd = build.points_from_array(np.random.default_rng(3).uniform(-1, 1, (4000, 3)))
pg, pgr = F.points_group(rnd, "in", enable_sdf=True, sdf=src, use_min=False, sdf_max=0.0)
inside = (np.linalg.norm(rnd.get(POINT, "P"), axis=1) < 0.6).sum()
check("Points Group by SDF ≤ 0 = the points inside the sphere", abs(pgr["points"] - inside) <= 3, (pgr["points"], inside))
pg2, pgr2 = F.points_group(rnd, "few", enable_number=True, number_mode="total", count=123)
check("  Number / Total: exactly the count", pgr2["points"] == 123)
sc = F.scatter(src, "", False, "count", 500, sdf_domain="interior")
check("Scatter: exactly Point Total points, all inside for the Interior domain",
      sc.npoints == 500 and (np.linalg.norm(sc.get(POINT, "P"), axis=1) < 0.6 + VS).all())
scs = F.scatter(src, "", False, "count", 300, sdf_domain="surface")
check("  Isosurface domain: points projected onto the surface",
      np.allclose(np.linalg.norm(scs.get(POINT, "P"), axis=1), 0.6, atol=0.01))

# ═══════════════════════════════════════════════════════════════ Volume SOPs
sec("Volume SOPs")
fogc = VO.create_volume((11, 11, 11), (1, 1, 1), (0, 0, 0), 0.5, True, "density", None, 0, 0)
af = VM.adjust_fog(fogc, "", "add", 1.0, "constant", 0.2, 0.2)
check("Adjust Fog: add 1 × constant pattern in range 0.2 -> +0.2", np.allclose(af.pdata(0, "voxels"), 0.7))
af2 = VM.adjust_fog(fogc, "", "add", 1.0, "constant", 0, 1, blend_amount=0.5)
check("  Blend 0.5 = halfway", np.allclose(af2.pdata(0, "voxels"), 1.0))
bd, br = VM.bound(src, "", "lessequal", 0.0)
check("Bound: the box of the inside voxels (on voxel edges) ≈ ±(0.6 + ½ voxel)",
      np.allclose(np.abs(br["bounds"][0]), 0.6 - 0.025 + 0.025, atol=0.03))
grid2 = build.grid(2, 2, 20, 20)
brk = VM.volume_break(grid2, src, "", "both")
check("Volume Break: a plane through the sphere is cut into inside / outside parts",
      brk.get_group(PRIM, "inside").any() and brk.get_group(PRIM, "outside").any())
cm, _ = VM.compress(lin, "", 0.0, 0.5)
check("Compress: quantisation to multiples of 0.5", np.allclose(cm.pdata(0, "voxels") * 2, np.round(cm.pdata(0, "voxels") * 2)))
cv3 = VM.convolve3(lin, "", [0] * 13 + [1] + [0] * 13, False)
check("Convolve with the identity kernel changes nothing", np.allclose(cv3.pdata(0, "voxels"), lin.pdata(0, "voxels")))
fe = VM.feather(delta, "", "change_per_voxel", 1.0)
check("Feather (high to low, 1 per voxel): the spike of 27 decays by 1 per voxel step",
      np.isclose(fe.pdata(0, "voxels")[4, 4, 6], 25))
ffw = VM.fft(lin)
fbk = VM.fft(ffw, "", False, True)
check("FFT forward then inverse (normalised) returns the input", np.allclose(fbk.pdata(0, "voxels"), lin.pdata(0, "voxels"), atol=1e-4))
pp = build.points_from_array(np.array([[0.0, 0, 0]]))
pp.set(POINT, "density", np.array([[4.0]], np.float32))
fa = VM.from_attrib(fogc, pp, accumulated=False, extrapolate=True, max_cells=100)
check("from Attrib, extrapolated: every voxel takes the nearest point's value", np.allclose(fa.pdata(0, "voxels"), 4))
mgv = VM.merge_volumes(fogc, fogc, method="add")
check("Volume Merge add: A + B", np.allclose(mgv.pdata(0, "voxels"), 1.0))
s0 = S.platonic("sphere", 0.35, (0, 0, 0), 0.04, fog=True)
s1 = S.platonic("sphere", 0.35, (0.08, 0, 0), 0.04, fog=True)
s0 = V.from_grid(s0.pdata(0, "voxels"), *V.grid(s0, 0)[1:], V.CLASS_FOG, "density")
of = VM.optical_flow(s0, s1)
check("Optical Flow: a blob shifted by 0.08 in x -> displacement ≈ (0.08, 0, 0) at its edge",
      abs(smp(of, 0, [[0.35, 0, 0]])[0] - 0.08) < 0.03 and abs(smp(of, 1, [[0.35, 0, 0]])[0]) < 0.02,
      smp(of, 0, [[0.35, 0, 0]])[0])
bgp = V.from_grid(Pl[..., 0], V.grid(lin, 0)[1], V.grid(lin, 0)[2], V.CLASS_NONE, "bg", False)
fgp = V.make((10, 10, 10), (1, 1, 1), fill=5.0, cls=V.CLASS_NONE, name="fg", vdb=False)
mkv = V.make((10, 10, 10), (1, 1, 1), fill=0.0, cls=V.CLASS_NONE, name="mask", vdb=False)
mv = mkv.pdata(0, "voxels").copy()
mv[3:7, 3:7, 3:7] = 1
V.set_voxels(mkv, 0, mv)
pa = VM.patch(merge(bgp, fgp, mkv), "bg", "fg", "mask")
check("Patch: a flat foreground fills the hole harmonically -- the linear background x is restored",
      np.allclose(pa.pdata(0, "voxels"), Pl[..., 0], atol=1e-4))
vr = VM.volume_ramp(fogc, "", "Cd", 0, 1, 0, 1, True, "", "0:1,0,0 1:0,0,1")
check("Volume Ramp (color): three volumes Cd.x / .y / .z (0.5 -> (0.5, 0, 0.5))",
      [V.name_of(vr, i) for i in range(3)] == ["Cd.x", "Cd.y", "Cd.z"]
      and np.allclose([vr.pdata(i, "voxels")[0, 0, 0] for i in range(3)], [0.5, 0, 0.5]))
ln2 = build.line() if "line" in dir(build) else None
crv = Geometry.from_points(np.array([[-1, 0, 0], [1, 0, 0]], np.float32))
crv.set_topology(np.array([0, 1], np.int32), np.array([0, 2], np.int32), np.zeros(1, bool), np.zeros(1, np.uint8))
crv.set(POINT, "width", np.array([[0.2], [0.2]], np.float32))
rcs = VM.rasterize_curve(crv, "sdf", 0.02)
check("Rasterize Curve SDF: −radius on the axis, 0 at the tube surface",
      np.isclose(smp(rcs, 0, [[0, 0, 0]])[0], -0.1, atol=1e-3) and abs(smp(rcs, 0, [[0, 0.1, 0]])[0]) < 1e-3)
rcm = VM.rasterize_curve(crv, "mask", 0.02)
check("  Mask: 1 on the axis, 0 outside", np.isclose(smp(rcm, 0, [[0, 0, 0]])[0], 1) and smp(rcm, 0, [[0, 0.11, 0]])[0] < 0.05)
pq = build.points_from_array(np.array([[0.0, 0, 0]]))
pq.set(POINT, "pscale", np.array([[0.4]], np.float32))
rpt = VM.rasterize_points(None, pq, smooth=False, voxel_size=0.05)
check("Rasterize Points (linear): 1 at the centre, 0.5 halfway, 0 at the radius",
      np.allclose(smp(rpt, 0, [[0, 0, 0], [0.2, 0, 0], [0.4, 0, 0]]), [1, 0.5, 0], atol=1e-3))
rpb = VM.rasterize_particles(None, pq, filt="box", voxel_size=0.05)
check("Rasterize Particles (box): coverage 1 inside the radius", np.isclose(smp(rpb, 0, [[0.1, 0, 0]])[0], 1))
rd, rdr = VM.reduce(lin, "", "average")
check("Reduce average of a linear field over a symmetric box = 0 (detail attribute)",
      abs(rdr["values"][0]) < 1e-5 and rd.get(DETAIL, "average") is not None)
rz = VM.resize(fogc, None, "", "replace", (0.4, 0.4, 0.4))
check("Resize: new bounds on the same lattice, values kept", V.bounds(rz)[1][0] <= 0.21
      and np.allclose(rz.pdata(0, "voxels"), 0.5))
sl = VM.slice_volumes(lin, plane="xy", visualize=False)
Psl = np.asarray(sl.get(POINT, "P"), np.float64)
vals = np.asarray(sl.get(POINT, "value"))[:, 0] if sl.get(POINT, "value") is not None else None
an = [k for k in sl.names(POINT) if k not in ("P",)][0]
vals = np.asarray(sl.get(POINT, an))[:, 0]
check("Slice (mesh): the plane's points carry the field values (2x + 3y − z)",
      np.allclose(vals, 2 * Psl[:, 0] + 3 * Psl[:, 1] - Psl[:, 2], atol=1e-4))
ta = V.make((11, 11, 11), (1, 1, 1), (0, 0, 0), 1.0, V.CLASS_FOG, "d", False)
tb = V.make((11, 11, 11), (1, 1, 1), (1, 0, 0), 2.0, V.CLASS_FOG, "d", False)
spl = VM.splice(merge(ta, tb))
check("Splice: one volume covering both; overlap from the nearer centre",
      spl.nprims == 1 and np.isclose(smp(spl, 0, [[0.3, 0, 0]])[0], 1) and np.isclose(smp(spl, 0, [[0.7, 0, 0]])[0], 2))
stp = build.points_from_array(np.array([[0.2, 0, 0]]))
stp.set(POINT, "pscale", np.array([[1.0]], np.float32))
st = VM.stamp(fogc, stp, S.platonic("sphere", 0.2, (0, 0, 0), 0.05, fog=True))
check("Stamp: the stamp volume appears around the point (maximum)", np.isclose(smp(st, 0, [[0.2, 0, 0]])[0], 1)
      and np.isclose(smp(st, 0, [[-0.4, 0, 0]])[0], 0.5))
trl = VM.trail(pts, velf, "", "", "time", 0.5)
check("Trail: in a uniform flow the streamline is straight, length v·t",
      np.isclose(np.linalg.norm(trl.get(POINT, "P")[-1] - trl.get(POINT, "P")[0]), 0.5, atol=1e-5))
vz = VM.velocity(V.make((21, 21, 3), (2, 2, 0.2), (0, 0, 0), 0.0, V.CLASS_NONE, "vel", False, 0.0, True),
                 vortex=True, angular=2.0)
check("Velocity vortex: speed = angular × distance from the axis",
      np.isclose(np.linalg.norm(smp(vz, 0, [[0.5, 0, 0]])[0]), 1.0, atol=1e-3))
cn = VM.velocity(V.make((24, 24, 24), (2, 2, 2), (0, 0, 0), 0.0, V.CLASS_NONE, "vel", False, 0.0, True),
                 curl=True, swirl_size=1.0, turbulence=1)
cnv = cn.pdata(0, "voxels")
cdiv = np.abs(F.divergence(cnv, V.grid(cn, 0)[2]))[3:-3, 3:-3, 3:-3].mean()
cmag = np.abs(F.analysis(cn, "", "curl")[0].pdata(0, "voxels")).mean()
check("  curl noise is (nearly) divergence free", cdiv < 0.1 * cmag, (cdiv, cmag))
vfc = VM.velocity_from_curves(crv, voxel_size=0.05, radius=0.2)
check("Velocity from Curves: along a straight curve the velocity is its tangent",
      np.allclose(smp(vfc, 0, [[0, 0.05, 0]])[0], [1, 0, 0], atol=1e-6))
bx = build.box(size=(1, 1, 1), divisions=(4, 4, 4))
dva = np.where(np.asarray(bx.get(POINT, "P"))[:, 1:2] > 0.4, 1.0, 0.0).astype(np.float32)
dva -= np.where(np.asarray(bx.get(POINT, "P"))[:, 1:2] < -0.4, 1.0, 0.0).astype(np.float32)
bx.set(POINT, "divergence", dva)
vfs = VM.velocity_from_surface(bx, 0.1, 0.2, 400)
check("Velocity from Surface: flow from the high-divergence top to the low bottom",
      smp(vfs, 0, [[0, 0, 0]])[0][1] < 0)
vz2 = run("PCG_VolumeVisualization", geo=src, mode="iso", iso=0.05)[0]
check("Volume Visualization node writes the detail attributes", str(vz2.get(DETAIL, "volvis_mode")[0, 0]) == "iso")

sec("nodes")
outs = {k: run(k, geo=src) for k in ("PCG_VDBDensify", "PCG_VDBRenormalizeSDF")}
check("nodes run with their defaults on an SDF", all(isinstance(v[0], Geometry) for v in outs.values()))
check("every pcg106 node is in PCG/volume", all(M[k].CATEGORY == "PCG/volume" for k in M
                                                 if k.startswith(("PCG_VDB", "PCG_ConvertVDB")) or k in (
                                                     "PCG_VolumeSDF", "PCG_VolumeVisualization")))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
