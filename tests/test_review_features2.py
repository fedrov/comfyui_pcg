"""
pcg122: the second round of review features, checked against analytic values and against the unpacked path.

  1. Export Mesh GPU instancing: the glb carries EXT_mesh_gpu_instancing, one mesh per distinct piece, and every
     instance's T * R * S applied to the piece mesh reproduces the unpacked export point for point (also with Scale,
     mirrored copies, two pieces, packed + polygons); sheared copies fall back to unpacking; negative controls:
     unpacked input / option off / OBJ have no instancing
  2. Export Instances reads packed primitives: rows equal the table of the target points; asset fallback piece0..
  3. Assemble: pieces numbered by first primitive, group respected, Create Packed -> Unpack gives the points back
  4. Spreadsheet paging: page() == the table the node would build at that start row; unknown node -> None; LRU
  5. PolyDoctor Self-Intersecting: exactly the faces two overlapping boxes cross; separated boxes / a single box: none
  6. LAS: a hand-written LAS 1.2 (format 3) and 1.4 (format 6) file read back exactly; recentring; truncation raises;
     cross-check against laspy (also LAZ) when it is installed
  7. VDB Clip to a camera frustum: the active voxels are exactly those inside |x| <= z tan(fov/2) aspect, |y| <= z tan
     (fov/2); Keep Inside off is the complement; Padding grows it; no camera raises
"""
import io
import json
import os
import struct
import sys
import tempfile

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

import comfyui_pcg  # noqa: E402,F401
from comfyui_pcg import spreadsheet as SS  # noqa: E402
from comfyui_pcg.geo import (build, ops, packed as PK, copyto as CT, meshexport as MX, instances as INS,  # noqa: E402
                             polydoctor as PDOC, meshio as MIO, vdb as V, vdbcore as VC, render as RN, Geometry)
from comfyui_pcg.geo.core import POINT, PRIM, DETAIL  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []
rng = np.random.default_rng(7)


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


# ─────────────────────────────────────────────────────────── glb reader (independent of meshexport)
def read_glb(b):
    jl = struct.unpack("<I", b[12:16])[0]
    js = json.loads(b[20:20 + jl])
    bin_ = b[20 + jl + 8:]

    def acc(i):
        a = js["accessors"][i]
        v = js["bufferViews"][a["bufferView"]]
        k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        dt = np.float32 if a["componentType"] == 5126 else np.uint32
        return np.frombuffer(bin_, dt, a["count"] * k, v["byteOffset"]).reshape(a["count"], k)
    return js, acc


def quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def world_points(b):
    """Every triangle corner position in world space (instances expanded), sorted rows; plus the json."""
    js, acc = read_glb(b)
    out = []
    for node in js["nodes"]:
        mesh = js["meshes"][node["mesh"]]
        pos = [acc(p["attributes"]["POSITION"])[acc(p["indices"])[:, 0]] for p in mesh["primitives"]]
        pos = np.concatenate(pos).astype(np.float64)
        ext = node.get("extensions", {}).get("EXT_mesh_gpu_instancing")
        if ext is None:
            out.append(pos)
            continue
        a = ext["attributes"]
        T, R, S = acc(a["TRANSLATION"]), acc(a["ROTATION"]), acc(a["SCALE"])
        for t, r, s in zip(T, R, S):
            out.append((pos * s) @ quat_mat(r.astype(np.float64)).T + t)
    W = np.concatenate(out)
    return W[np.lexsort(W.T[::-1])], js


def same_world(a, b, tol=2e-4):
    wa, _ = world_points(a)
    wb, _ = world_points(b)
    return wa.shape == wb.shape and float(np.abs(wa - wb).max()) < tol, (wa.shape, wb.shape)


print("\n[1. Export Mesh GPU instancing]")
box = build.box(divisions=(2, 2, 2))
tp = Geometry.from_points(rng.uniform(-3, 3, (40, 3)).astype(np.float32))
tp.set(POINT, "N", rng.normal(size=(40, 3)).astype(np.float32))
tp.set(POINT, "pscale", rng.uniform(0.3, 1.2, (40, 1)).astype(np.float32))
pk = CT.copy_to_points(box, tp, pack=True)
gi, gu = MX.build_glb(pk), MX.build_glb(pk, gpu_instancing=False)
js, _ = read_glb(gi)
ext_nodes = [n for n in js["nodes"] if "extensions" in n]
check("extensionsUsed lists EXT_mesh_gpu_instancing, one mesh, one instanced node",
      js.get("extensionsUsed") == ["EXT_mesh_gpu_instancing"] and len(js["meshes"]) == 1 and len(ext_nodes) == 1)
_, acc = read_glb(gi)
check("  40 instances", acc(ext_nodes[0]["extensions"]["EXT_mesh_gpu_instancing"]["attributes"]["TRANSLATION"])
      .shape == (40, 3))
ok, why = same_world(gi, gu)
check("  every instance's T*R*S on the piece == the unpacked export (all corners)", ok, why)
check("  the instanced file is much smaller", len(gi) * 3 < len(gu), (len(gi), len(gu)))
ok, why = same_world(MX.build_glb(pk, scale=2.5), MX.build_glb(pk, scale=2.5, gpu_instancing=False))
check("  Scale 2.5 scales mesh and translations alike", ok, why)
mir = ops.transform(pk, (0, 0, 0), (0, 0, 0), (-1, 1, 1))
gm = MX.build_glb(mir)
ok, why = same_world(gm, MX.build_glb(mir, gpu_instancing=False))
check("mirrored copies (negative determinant) stay instanced and correct",
      ok and "extensionsUsed" in read_glb(gm)[0], why)
two_src = ops.merge(box, build.sphere(radius=0.5, cols=8, rows=4))
two_src.set_string(PRIM, "name", np.array(["rock"] * box.nprims + ["ball"] * (two_src.nprims - box.nprims), dtype=object))
tp2 = tp.copy()
tp2.set_string(POINT, "name", np.array(["rock", "ball"] * 20, dtype=object))
pk2 = CT.copy_to_points(two_src, tp2, piece_attrib="name", pack=True)
g2 = MX.build_glb(pk2)
js2, _ = read_glb(g2)
ok, why = same_world(g2, MX.build_glb(pk2, gpu_instancing=False))
check("two pieces: two meshes, two instanced nodes named after the pieces, geometry identical",
      ok and len(js2["meshes"]) == 2 and sorted(n["name"] for n in js2["nodes"]) == ["ball", "rock"],
      (why, [n["name"] for n in js2["nodes"]]))
mixed = ops.merge(pk, build.sphere(radius=2, center=(10, 0, 0)))
gx = MX.build_glb(mixed)
jx, _ = read_glb(gx)
ok, why = same_world(gx, MX.build_glb(mixed, gpu_instancing=False))
check("packed + ordinary polygons: one plain node and one instanced node, identical geometry",
      ok and len(jx["nodes"]) == 2 and sum("extensions" in n for n in jx["nodes"]) == 1, why)
shear = ops.transform(ops.transform(pk, (0, 0, 0), (0, 0, 35), (1, 1, 1)), (0, 0, 0), (0, 0, 0), (1, 2.5, 1))
gs = MX.build_glb(shear)
ok, why = same_world(gs, MX.build_glb(shear, gpu_instancing=False))
check("sheared copies (rotate then non-uniform scale) are unpacked instead: no extension, geometry right",
      ok and "extensionsUsed" not in read_glb(gs)[0], why)
T_, R_, S_ = MX.decompose_trs(np.array([[[2, 0, 0, 1], [0, 3, 0, 2], [0, 0, 4, 3], [0, 0, 0, 1.0]]]))
check("decompose_trs: diag(2,3,4) + (1,2,3) -> T, identity rotation, S",
      np.allclose(T_, [[1, 2, 3]]) and np.allclose(R_, [[0, 0, 0, 1]]) and np.allclose(S_, [[2, 3, 4]]))
check("  a sheared matrix -> None", MX.decompose_trs(np.array([[[1, 0.5, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0],
                                                                [0, 0, 0, 1.0]]])) is None)
plain = MX.build_glb(CT.copy_to_points(box, tp))
check("negative control: unpacked input has no instancing", "extensionsUsed" not in read_glb(plain)[0])
check("negative control: gpu_instancing off has no instancing", "extensionsUsed" not in read_glb(gu)[0])
with tempfile.TemporaryDirectory() as d:
    paths = MX.export(pk, os.path.join(d, "m"), "obj")
    txt = open(paths[0]).read()
    nv = sum(1 for ln in txt.splitlines() if ln.startswith("v "))
    check("OBJ unpacks packed primitives (all copies' points written)", nv == 40 * box.npoints, nv)
    out = N["PCG_ExportMesh"]().run(pk, os.path.join(d, "n"), "glb")
    check("Export Mesh node writes the instanced glb by default (packed input reaches it, not auto-unpacked)",
          "extensionsUsed" in read_glb(open(os.path.join(d, "n.glb"), "rb").read())[0])

print("\n[2. Export Instances on packed primitives]")
cols, rows_pts, _ = INS.table(tp, asset_attribute="")
cols2, rows_pk, _ = INS.table(pk, asset_attribute="name")
A = np.array([r[1:] for r in rows_pts], np.float64)
B = np.array([r[1:] for r in rows_pk], np.float64)
check("rows of the packed copies == rows of the target points (position, quaternion, Euler, scale)",
      A.shape == B.shape and np.abs(A - B).max() < 1e-4, np.abs(A - B).max() if A.shape == B.shape else A.shape)
check("  no name attribute -> asset piece0", {r[0] for r in rows_pk} == {"piece0"})
_, rows2, _ = INS.table(pk2, asset_attribute="name")
pn = PK.transforms(pk2)[1]
want_names = [str(x) for x in np.asarray(pk2.get(POINT, "name"), dtype=object)[pn, 0]]
check("  two pieces: asset from the point name attribute", [r[0] for r in rows2] == want_names
      and set(want_names) == {"rock", "ball"})
pkd, _ = PK.pack(ops.merge(box, build.sphere(radius=0.5, cols=8, rows=4, center=(3, 0, 0))), pack_by="connectivity")
_, rows3, _ = INS.table(pkd, asset_attribute="")
check("  Pack (connectivity) output: assets piece0 / piece1, positions at the centroids",
      [r[0] for r in rows3] == ["piece0", "piece1"] and abs(rows3[1][1] - 3.0) < 1e-5)

print("\n[3. Assemble]")
parts = ops.merge(box, build.sphere(radius=0.5, cols=8, rows=4, center=(3, 0, 0)), build.torus(center=(0, 4, 0))
                  if "center" in build.torus.__code__.co_varnames else build.tube())
g, r = PK.assemble(parts)
nm = [str(x) for x in np.asarray(g.get(PRIM, "name"))[:, 0]]
n0, n1 = box.nprims, box.nprims + 32
check("three loose pieces -> piece0 / piece1 / piece2 in primitive order",
      r["pieces"] == 3 and set(nm[:n0]) == {"piece0"} and set(nm[n0:n0 + 1]) == {"piece1"} and nm[-1] == "piece2",
      (r, nm[0], nm[n0], nm[-1]))
g, r = PK.assemble(parts, group=f"0-{n0 - 1}", name_prefix="rock_")
nm = [str(x) for x in np.asarray(g.get(PRIM, "name"))[:, 0]]
check("  group: only the box is named (rock_0), the rest pass through with empty names",
      r["pieces"] == 1 and set(nm[:n0]) == {"rock_0"} and set(nm[n0:]) == {""})
gp, rp = PK.assemble(parts, create_packed=True)
back = PK.unpack(gp)[0]
check("Create Packed: 3 packed prims; Unpack gives every point back",
      rp["packed"] == 3 and PK.is_packed(gp) and gp.nprims == 3 and back.npoints == parts.npoints
      and np.abs(np.sort(P_(back), 0) - np.sort(P_(parts), 0)).max() < 1e-5)
gq, _ = PK.assemble(parts, group=f"0-{n0 - 1}", create_packed=True)
check("  with a group: one packed primitive + the other pieces as polygons",
      int((gq.prim_type == 1).sum()) == 1 and gq.nprims == 1 + parts.nprims - box.nprims)
check("negative control: one connected mesh is one piece", PK.assemble(box)[1]["pieces"] == 1)
ga = N["PCG_Assemble"]().run(parts, "", "name", "piece", False, "centroid")
ga = ga["result"] if isinstance(ga, dict) else ga
check("  node runs, report counts 3", json.loads(ga[1])["pieces"] == 3)

print("\n[4. Spreadsheet paging]")
grid = build.grid(rows=60, cols=60) if "rows" in build.grid.__code__.co_varnames else build.grid()
node = SS.PCG_GeoSpreadsheet()
res = node.run(grid, 50, 0, unique_id="77")
pl = res["ui"]["pcg_spreadsheet"][0]
pg = SS.page("77", "point", 120, 50)
want = SS._table(grid, "point", 50, 120)
check("page(start 120) == the table the node would build at Start Row 120",
      pg["table"]["start"] == 120 and pg["table"]["rows"] == want["rows"] and pg["rev"] == pl["rev"])
check("  payload carries rev and rows for the frontend", pl["rows"] == 50 and "rev" in pl)
check("  vertex and prim pages too", SS.page("77", "prim", 7, 3)["table"]["rows"] == SS._table(grid, "prim", 3, 7)["rows"])
check("  past the end clamps to the last row", SS.page("77", "point", 10 ** 9, 50)["table"]["start"] == grid.npoints - 1)
check("unknown node -> None (route answers 404)", SS.page("nope", "point", 0, 10) is None)
try:
    SS.page("77", "edge", 0, 10)
    bad = False
except ValueError:
    bad = True
check("  unknown class raises", bad)
for k in range(SS.CACHE_NODES):
    SS.remember(f"x{k}", grid)
check("  least recently used node dropped after CACHE_NODES more", SS.page("77", "point", 0, 5) is None)

print("\n[5. PolyDoctor Self-Intersecting]")
A_ = build.box()
B_ = ops.transform(build.box(), (0.5, 0.25, 0.25))
two = ops.merge(A_, B_)
bad = PDOC.self_intersecting(two)
c = ops.prim_centers(two)
nA = A_.nprims
check("both boxes have flagged faces", bad[:nA].any() and bad[nA:].any(), np.nonzero(bad)[0])
check("  A's -x face (x = -0.5) and B's +x face (x = 1.0) are clean, A's +x face is flagged",
      not bad[np.argmin(c[:nA, 0])] and not bad[nA + np.argmax(c[nA:, 0])] and bad[np.argmax(c[:nA, 0])])
far = ops.merge(A_, ops.transform(build.box(), (3, 0, 0)))
check("negative control: separated boxes -> nothing flagged", not PDOC.self_intersecting(far).any())
check("negative control: a single closed box -> nothing flagged (adjacent faces are skipped)",
      not PDOC.self_intersecting(build.sphere(cols=12, rows=6)).any())
g, rr = PDOC.polydoctor(two, ill_formed_mode="ignore", overlapping_mode="ignore", disconnected_mode="ignore",
                        self_intersecting_mode="mark")
vp = np.asarray(g.get(PRIM, "valid_poly"))[:, 0]
check("polydoctor(mark): valid_poly = 0 exactly on the self-intersecting faces, counted in the report",
      np.array_equal(vp == 0, bad) and rr["found"]["self_intersecting"] == int(bad.sum()))
g0, _ = PDOC.polydoctor(two, ill_formed_mode="ignore", overlapping_mode="ignore", disconnected_mode="ignore")
check("  default (ignore) marks nothing", np.all(np.asarray(g0.get(PRIM, "valid_poly")) == 1))


print("\n[6. LAS import]")


def write_las(P, fmt, ver, scale=(0.001, 0.001, 0.001), offset=(0, 0, 0), extra=None):
    """Minimal LAS writer: header + no VLRs + records (formats 3 and 6 only)."""
    n = len(P)
    hsize = 375 if ver == (1, 4) else 227
    rec = {3: 34, 6: 30}[fmt]
    X = np.round((P - offset) / scale).astype("<i4")
    h = bytearray(hsize)
    h[0:4] = b"LASF"
    h[24], h[25] = ver
    struct.pack_into("<H", h, 94, hsize)
    struct.pack_into("<I", h, 96, hsize)
    struct.pack_into("<I", h, 100, 0)
    h[104] = fmt
    struct.pack_into("<H", h, 105, rec)
    struct.pack_into("<I", h, 107, n if ver != (1, 4) else 0)
    struct.pack_into("<3d", h, 131, *scale)
    struct.pack_into("<3d", h, 155, *offset)
    lo, hi = P.min(0), P.max(0)
    struct.pack_into("<6d", h, 179, hi[0], lo[0], hi[1], lo[1], hi[2], lo[2])
    if ver == (1, 4):
        struct.pack_into("<Q", h, 247, n)
    body = bytearray(n * rec)
    for i in range(n):
        o = i * rec
        struct.pack_into("<3i", body, o, *X[i])
        struct.pack_into("<H", body, o + 12, extra["intensity"][i])
        if fmt == 3:
            body[o + 14] = extra["ret"][i] | (extra["nret"][i] << 3)
            body[o + 15] = extra["cls"][i]
            struct.pack_into("<d", body, o + 20, extra["gps"][i])
            struct.pack_into("<3H", body, o + 28, *extra["rgb"][i])
        else:
            body[o + 14] = extra["ret"][i] | (extra["nret"][i] << 4)
            body[o + 16] = extra["cls"][i]
            struct.pack_into("<d", body, o + 22, extra["gps"][i])
    return bytes(h) + bytes(body)


n = 200
P = rng.uniform(0, 50, (n, 3))
ex = {"intensity": rng.integers(0, 65535, n), "ret": rng.integers(1, 4, n), "nret": np.full(n, 4),
      "cls": rng.integers(0, 12, n), "gps": rng.uniform(0, 1e6, n), "rgb": rng.integers(0, 65535, (n, 3))}
d3 = MIO.load_las(write_las(P, 3, (1, 2), extra=ex))
check("LAS 1.2 format 3: positions to the scale step, intensity / class / returns / gps exact, RGB / 65535",
      np.abs(d3["P"] - P).max() <= 0.0005 + 1e-9 and np.array_equal(d3["attrs"]["intensity"], ex["intensity"])
      and np.array_equal(d3["attrs"]["classification"], ex["cls"])
      and np.array_equal(d3["attrs"]["return_number"], ex["ret"])
      and np.array_equal(d3["attrs"]["number_of_returns"], ex["nret"])
      and np.allclose(d3["attrs"]["gps_time"], ex["gps"]) and np.allclose(d3["Cd"], ex["rgb"] / 65535.0))
d6 = MIO.load_las(write_las(P, 6, (1, 4), extra=ex))
check("LAS 1.4 format 6 (64-bit point count, 4-bit return fields)",
      len(d6["P"]) == n and np.abs(d6["P"] - P).max() <= 0.0005 + 1e-9
      and np.array_equal(d6["attrs"]["return_number"], ex["ret"]) and d6["Cd"] is None)
Pu = P + np.array([512345.0, 4123456.0, 200.0])
raw = write_las(Pu, 3, (1, 2), offset=(512000, 4123000, 0), extra=ex)
g, info = MIO.load(data=raw)
org = np.asarray(g.get(DETAIL, "las_origin"), np.float64)[0]
check("auto-detected (LASF); survey coordinates recentred: P + las_origin == world to the centimetre",
      info.startswith("las") and np.abs(P_(g) + org - Pu).max() < 0.01 and np.abs(P_(g)).max() < 100,
      np.abs(P_(g) + org - Pu).max())
gs_, _ = MIO.load(data=write_las(P, 3, (1, 2), extra=ex))
check("  small coordinates are not moved (las_origin = 0)", np.all(np.asarray(gs_.get(DETAIL, "las_origin")) == 0))
check("  attributes land on points; Keep Extra off keeps only P and Cd",
      gs_.has(POINT, "intensity") and set(MIO.load(data=raw, keep_extra=False)[0].attribs[POINT]) == {"P", "Cd"})
try:
    MIO.load_las(raw[:-10])
    trunc = False
except ValueError:
    trunc = True
check("negative control: a truncated file raises", trunc)
try:
    import laspy
    las = laspy.read(io.BytesIO(raw))
    check("laspy reads our test file the same way (cross-check of the writer)",
          np.abs(np.c_[las.x, las.y, las.z] - MIO.load_las(raw)["P"]).max() < 1e-9)
    b = io.BytesIO()
    las.write(b, do_compress=True)
    dz = MIO.load_las(b.getvalue())
    check("  LAZ through laspy == the LAS read", np.abs(dz["P"] - MIO.load_las(raw)["P"]).max() < 1e-9
          and np.array_equal(dz["attrs"]["classification"], ex["cls"]))
except ImportError:
    print("  (laspy not installed: LAZ cross-check skipped)")

print("\n[7. VDB Clip to a camera frustum]")
vol = VC.create("density", "fog", False, 0.25, size=(4, 4, 4), fill=True, value=1.0)
cam = RN.camera(eye=(0, 0, 5), target=(0, 0, 0), fov=30, xres=200, yres=100)
gcl, rcl = VC.clip(vol, "", True, "camera", None, "", 0.0, cam)
i = V.volume_prims(gcl)[0]
vox, origin, cell = V.grid(gcl, i)
Q = V.world_points(origin, cell, vox.shape[:3]).reshape(-1, 3)
z = 5.0 - Q[:, 2]
t = np.tan(np.radians(15.0))
want = (np.abs(Q[:, 0]) <= z * t * 2.0) & (np.abs(Q[:, 1]) <= z * t) & (z >= 0.01)
act = V.active(gcl, i).reshape(-1)
check("active voxels == analytic frustum |x| <= z tan(15) * 2, |y| <= z tan(15)",
      np.array_equal(act, want) and 0 < act.sum() < len(act), (int(act.sum()), int(want.sum()), len(act)))
gout, _ = VC.clip(vol, "", False, "camera", None, "", 0.0, cam)
check("  Keep Inside off: the complement", np.array_equal(V.active(gout, i).reshape(-1), ~want))
gpad, _ = VC.clip(vol, "", True, "camera", None, "", 0.3, cam)
check("  Padding 0.3 keeps more voxels, all of the unpadded ones",
      V.active(gpad, i).sum() > act.sum() and np.all(V.active(gpad, i).reshape(-1)[act]))
try:
    VC.clip(vol, "", True, "camera", None, "", 0.0, None)
    nocam = False
except ValueError:
    nocam = True
check("negative control: Clip To camera without a camera raises", nocam)
def res0(o):
    return (o["result"] if isinstance(o, dict) else o)[0]


gnode = res0(N["PCG_VDBClip"]().run(vol, "", True, "camera", "", 0.0, camera=cam))
check("  node: camera input, no clip geometry needed", np.array_equal(V.active(gnode, i).reshape(-1), want))
gb = res0(N["PCG_VDBClip"]().run(vol, "", True, "geometry", "", 0.0, clip=build.box()))
check("  geometry mode still works with the clip input", 0 < V.active(gb, i).sum() < len(act))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
