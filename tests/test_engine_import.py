"""
The engine import examples (engine/unreal/pcg_world_import.py, engine/unity/Editor/*.cs) against a small world
written by the real export nodes and described by World Manifest. What runs outside the engines is checked:

  Unreal (the pure part of the script)
    1. coordinates: X = x, Y = z, Z = y in cm; the quaternion conversion is the same rotation seen through the axis
       swap (its matrix = P R P for random rotations); negative control: plain (x, y, z, w) is not
    2. Landscape settings: Unreal's height of a 16-bit value with the given Scale Z and location equals the
       manifest's metres for v = 0, 32768, 65535 (and the heightmap's own min / max)
    3. instances read per tile and in all: the manifest's counts; LOD plan: the town's nodes and screen sizes;
       roads: the class's lines, width and length; asset fallback to the proxies
  Unity (with Mono, when installed: the C# core compiled and run, the Editor importer compiled against stubs)
    4. every tile's terrain samples land on the heightmap: the Unity point (x, y, -z) of a sample is the manifest's
       height there; negative control: the rows read the other way round are off
    5. instance positions (x, y, -z) and rotations (matrix = P R P with P = diag(1, 1, -1)); road polylines
    6. the Editor importer compiles against Unity's signatures (stubs)
"""
import json
import math
import os
import shutil
import subprocess
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
from comfyui_pcg.geo import build, Geometry  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM  # noqa: E402
from comfyui_pcg.geo.ops import merge  # noqa: E402

PKG = os.path.dirname(_R)
sys.path.insert(0, os.path.join(PKG, "engine", "unreal"))
import pcg_world_import as UE  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def nrun(name, **kw):
    c = N["PCG_" + name]
    args = {}
    for sec in ("required", "optional"):
        for k, spec in c.INPUT_TYPES().get(sec, {}).items():
            t = spec[0]
            opt = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(t, list):
                args[k] = t[0]
            elif "default" in opt:
                args[k] = opt["default"]
    args.update(kw)
    out = getattr(c(), c.FUNCTION)(**args)
    return out["result"] if isinstance(out, dict) else out


def qmat(q):
    return np.array(UE.quat_matrix(q))


tmp = tempfile.mkdtemp(prefix="pcg_eng_")
os.chdir(tmp)
OUT = os.path.join(tmp, "output")
F = "pcg/e"
# a 2048 m world: 129 samples (16 m), tiles of 65 with a shared edge; height = 100 u + 40 v (both axes matter)
cop = nrun("COPConstant", resolution_x=129, resolution_y=129, layer="base", device="numpy")[0]
cop = nrun("COPWrangle", cop=cop, code="@C = 100 * @u + 40 * @v")[0]
nrun("COPWriteFile", cop=cop, filename=F + "/height/Height_x{tx}_y{ty}", channels="C", format="png", bit_depth="16",
     encode="linear", remap="normalize", tiles_x=2, tiles_y=2, shared_edge=True)
nrun("COPWriteFile", cop=cop, filename=F + "/height/Height_full", channels="C", format="raw", bit_depth="16",
     remap="normalize")
rng = np.random.default_rng(3)
pts = np.c_[rng.uniform(0, 2048, 40), rng.uniform(0, 50, 40), rng.uniform(0, 2048, 40)].astype(np.float32)
ig = Geometry.from_points(pts)
ig.set_string(POINT, "name", np.array(["Tree_Pine_A", "SM_Bridge", "Tree_Broadleaf_B", "Odd"] * 10))
ax = rng.normal(size=(40, 3))
ax /= np.linalg.norm(ax, axis=1, keepdims=True)
ig.set(POINT, "N", ax.astype(np.float32))
up = np.cross(ax, rng.normal(size=(40, 3)))
ig.set(POINT, "up", (up / np.linalg.norm(up, axis=1, keepdims=True)).astype(np.float32))
nrun("ExportInstances", points=ig, filename=F + "/instances/Instances_x{tx}_y{ty}", format="csv",
     asset_attribute="name", extra_attributes="", tile_size=1024.0)


def named_box(size, center, name):
    b = build.box(size=size, center=center)
    b.set_string(PRIM, "name", np.full(b.nprims, name))
    return b


town = merge(named_box((40, 20, 40), (300, 10, 1500), "Town_01_LOD0"),
             named_box((30, 15, 30), (300, 7.5, 1500), "Town_01_LOD1"))
town.set(PRIM, "lod_distance", np.array([0.0] * 6 + [400.0] * 6, np.float32))
nrun("ExportMesh", geo=town, filename=F + "/buildings/Towns", format="glb", split_attribute="name", lod_manifest=True)
road = nrun("Line", dx=1.0, dy=0.0, dz=0.0, length=1800.0, points=19, origin_x=100.0, origin_y=3.0,
            origin_z=100.0)[0]
nrun("ExportMesh", geo=road, filename=F + "/roads/Roads_Main", format="obj")
extra = {"road_classes": {"main": {"polylines": "roads/Roads_Main", "width_m": 6.5, "material": "M_Road_Main"}}}
path, _ = nrun("WorldManifest", folder=F, world_size=2048.0, tile_size=1024.0, origin="north_west_corner",
               extra_json=json.dumps(extra))
WJ = os.path.join(OUT, path)
world, root = UE.load(WJ)
full = np.fromfile(os.path.join(OUT, F, "height", "Height_full.r16"), "<u2").reshape(129, 129)
r0, r1 = world["terrain"]["range_metres"]


def metres_at(x, z):
    """The manifest's height at world (x, z) (World.json metres), row = z / 16, column = x / 16, bilinear."""
    fx, fz = x / 16.0, z / 16.0
    c0, rw0 = int(min(math.floor(fx), 127)), int(min(math.floor(fz), 127))
    tx, tz = fx - c0, fz - rw0
    v = (full[rw0, c0] * (1 - tx) * (1 - tz) + full[rw0, c0 + 1] * tx * (1 - tz) + full[rw0 + 1, c0] * (1 - tx) * tz
         + full[rw0 + 1, c0 + 1] * tx * tz)
    return r0 + v / 65535.0 * (r1 - r0)


print("\n[1. Unreal: coordinates]")
check("UE.load finds ComfyUI's output folder from World.json and its folder", os.path.samefile(root, OUT), root)
check("location: metres (x, y, z) -> cm (X = x, Y = z, Z = y)", UE.location((1.5, 2.0, -3.0)) == (150.0, -300.0, 200.0))
P = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], float)          # the y <-> z swap
ok_q, ok_neg = True, True
for _ in range(50):
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    R = qmat(q)
    ok_q &= np.allclose(qmat(UE.rotation_quat(q)), P @ R @ P, atol=1e-9)
    ok_neg &= np.allclose(qmat(q), P @ R @ P, atol=1e-3)
check("the quaternion conversion is the rotation seen through the axis swap (matrix = P R P, 50 random rotations); "
      "negative control: the unconverted quaternion is not", ok_q and not ok_neg)

print("\n[2. Unreal: Landscape settings]")
ls = UE.landscape_settings(world, root)
hs = [UE.landscape_height_cm(ls, v) / 100.0 for v in (0, 32768, 65535)]
exp = [r0 + v / 65535.0 * (r1 - r0) for v in (0, 32768, 65535)]
check("Unreal's height of a 16-bit value (actor Z + (v - 32768) / 128 * Scale Z) = the manifest's metres at 0, 32768, "
      "65535", np.allclose(hs, exp, atol=1e-6), (np.round(hs, 4), np.round(exp, 4)))
check("  the heightmap is the full-map .r16, 129 x 129, 16 m (1600 cm) a sample",
      ls["heightmap_r16"].endswith("Height_full.r16") and ls["resolution"] == [129, 129]
      and abs(ls["scale_xy"] - 1600.0) < 1e-9)
lo_, hi_ = UE.landscape_height_cm(ls, full.min()) / 100, UE.landscape_height_cm(ls, full.max()) / 100
check("  the heightmap's own lowest and highest pixels come out at the manifest's range", abs(lo_ - r0) < 1e-6
      and abs(hi_ - r1) < 1e-6, (lo_, hi_, r0, r1))

print("\n[3. Unreal: instances, LODs, roads, assets]")
alli = UE.read_instances(world, root)
per_tile = sum(sum(len(v) for v in UE.read_instances(world, root, t["tile"]).values()) for t in world["tiles"])
check("instances: 40 in all, the same 40 read tile by tile, 10 per asset", sum(len(v) for v in alli.values()) == 40
      and per_tile == 40 and sorted(len(v) for v in alli.values()) == [10, 10, 10, 10])
x0 = alli["Tree_Pine_A"][0]
check("  an instance's location is its table row in cm with Y = z", any(np.allclose(x0[0], (p[0] * 100, p[2] * 100,
                                                                                      p[1] * 100), atol=0.5)
                                                                       for p in pts))
lp = UE.lod_plan(world)
check("LOD plan: the town's two nodes in order, screen sizes from the manifest (1 then less)",
      len(lp) == 1 and lp[0]["nodes"] == ["Town_01_LOD0", "Town_01_LOD1"] and lp[0]["screen_sizes"][0] == 1.0
      and 0 < lp[0]["screen_sizes"][1] < 1, lp)
rp = UE.road_plan(world, root)
L = sum(math.dist(a, b) for a, b in zip(rp[0]["lines"][0][:-1], rp[0]["lines"][0][1:])) / 100 if rp else 0
check("roads: class main, 650 cm wide, one 1800 m line at Z = 300 cm", len(rp) == 1 and rp[0]["class"] == "main"
      and rp[0]["width_cm"] == 650.0 and abs(L - 1800) < 0.01 and rp[0]["lines"][0][0][2] == 300.0, (len(rp), L))
av = {"SM_Bridge", "SM_Proxy_Pine_LOD0"}
check("assets: its own mesh, else the proxy by prefix, else none", UE.asset_mesh_name("SM_Bridge", av) == "SM_Bridge"
      and UE.asset_mesh_name("Tree_Pine_A", av) == "SM_Proxy_Pine_LOD0"
      and UE.asset_mesh_name("Tree_Broadleaf_B", av) is None and UE.asset_mesh_name("Odd", av) is None)
check("  a LOD chain: an asset with only <asset>_LOD0 uses it (the modular kit's glbs), not the bare name",
      UE.asset_mesh_name("SM_Kit_Wall_Window", av | {"SM_Kit_Wall_Window_LOD0", "SM_Kit_Wall_Window_LOD1"})
      == "SM_Kit_Wall_Window_LOD0" and UE.asset_mesh_name("SM_Kit_Wall_Door", av | {"SM_Kit_Wall_Window_LOD0"}) is None)

# the modular city: the facade column picks the wall's override material (World.json's city key); collision nodes
cdir = os.path.join(tmp, "citycase")
os.makedirs(cdir, exist_ok=True)
with open(os.path.join(cdir, "I.csv"), "w", newline="") as f:
    f.write("asset,px,py,pz,qx,qy,qz,qw,sx,sy,sz,facade\n")
    for k, fa in enumerate([0, 1, 1, 2, 0]):
        f.write(f"SM_Kit_Wall_Window,{4 * k},0,0,0,0,0,1,1,1,1,{fa}\n")
cw_ = {"instances": {"files": ["I.csv"]}, "city": {"instances_facade_column": "facade", "wall_material": "M_Wall",
                                                   "facade_materials": {"0": "M_Wall", "1": "M_BrickBuff", "2": "M_Stucco"}}}
ig = {k: len(v) for k, v in UE.instance_groups(cw_, cdir).items()}
check("city facades: one group per asset and override (facade 0 keeps the wall: no override)",
      ig == {("SM_Kit_Wall_Window", ""): 2, ("SM_Kit_Wall_Window", "M_BrickBuff"): 2,
             ("SM_Kit_Wall_Window", "M_Stucco"): 1}, ig)
ig0 = {k: len(v) for k, v in UE.instance_groups({"instances": cw_["instances"]}, cdir).items()}
check("  negative control: without the city key, no overrides (the column is just data)",
      ig0 == {("SM_Kit_Wall_Window", ""): 5}, ig0)
lpc = UE.lod_plan({"meshes": {"a": {"file": "a.glb", "role": "assets", "assets": [
    {"name": "SM_Kit_X", "lods": [{"lod": 0, "node": "SM_Kit_X_LOD0"}, {"lod": 1, "node": "SM_Kit_X_LOD1"}],
     "collision": ["UCX_SM_Kit_X_00"]}]}}})
check("  LOD plan carries the collision nodes (built as convex collision, the UCX meshes deleted)",
      lpc and lpc[0]["collision"] == ["UCX_SM_Kit_X_00"] and lpc[0]["nodes"] == ["SM_Kit_X_LOD0", "SM_Kit_X_LOD1"]
      and lp[0]["collision"] == [], lpc)

# a facade material the project lacks is made from the material library's textures (city key: facade_textures)
os.makedirs(os.path.join(cdir, "pcg", "materials"), exist_ok=True)
for f_ in ("T_M_BrickBuff_BaseColor.png", "T_M_BrickBuff_Normal_GL.png", "T_M_Stucco_Normal_GL.png"):
    open(os.path.join(cdir, "pcg", "materials", f_), "wb").close()
ft_ = {m: {"basecolor": f"pcg/materials/T_{m}_BaseColor.png", "normal": f"pcg/materials/T_{m}_Normal_GL.png",
           "orm": f"pcg/materials/T_{m}_ORM.png"} for m in ("M_BrickBuff", "M_Stucco")}
cwf_ = dict(cw_, city=dict(cw_["city"], facade_textures=ft_))
fp_ = UE.facade_material_plan(cwf_, cdir)
check("facade materials to make: those whose textures are exported (base colour + normal; the missing ORM left "
      "out; M_Stucco without a base colour: not made)", sorted(fp_) == ["M_BrickBuff"]
      and sorted(fp_["M_BrickBuff"]) == ["basecolor", "normal"]
      and fp_["M_BrickBuff"]["normal"] == os.path.join(cdir, "pcg/materials/T_M_BrickBuff_Normal_GL.png"), fp_)
check("  negative control: without facade_textures, nothing to make", UE.facade_material_plan(cw_, cdir) == {})
cwj_ = os.path.join(cdir, "pcg", "city", "World.json")
os.makedirs(os.path.dirname(cwj_), exist_ok=True)
with open(cwj_, "w") as f_:
    json.dump(dict(cwf_, format="pcg-world", folder="pcg/city", tiles=[]), f_)

print("\n[4-6. Unity (C# with Mono)]")
mcs, mono = shutil.which("mcs"), shutil.which("mono")
if not (mcs and mono):
    print("  (no Mono: the C# part is not compiled here)")
else:
    U = os.path.join(PKG, "engine", "unity", "Editor")
    exe = os.path.join(tmp, "probe.exe")
    r = subprocess.run([mcs, "-out:" + exe, os.path.join(U, "PcgWorldCore.cs"), os.path.join(_R, "engine",
                                                                                           "CoreProbe.cs")],
                       capture_output=True, text=True)
    check("the core compiles (C#, no UnityEngine)", r.returncode == 0, r.stdout[-400:] + r.stderr[-400:])
    out = subprocess.run([mono, exe, WJ], capture_output=True, text=True)
    pr = json.loads(out.stdout) if out.returncode == 0 else {}
    sm = pr.get("samples", [])
    err = [abs(y - metres_at(x, -z)) for _, _, x, y, z in sm]
    errf = [abs(y - metres_at(x, 2048 - (-z))) for _, _, x, y, z in sm]
    check("every tile's samples land on the heightmap: the Unity point (x, y, -z) carries the manifest's height "
          f"there ({len(sm)} samples over 4 tiles, max error {max(err or [9]):.4f} m)", len(sm) == 16 and max(err) < 0.01)
    check("  negative control: rows read the other way round are metres off", len(errf) and max(errf) > 5,
          round(max(errf or [0]), 2))
    ins = pr.get("instances", [])
    rows = {}
    import csv
    for fn in world["instances"]["files"]:
        with open(os.path.join(root, fn), newline="") as f:
            for row in csv.DictReader(f):
                rows[(row["asset"], round(float(row["px"]), 2))] = row
    Pz = np.diag([1.0, 1.0, -1.0])
    okp = okr = len(ins) == 40
    for a, x, y, z, qx, qy, qz, qw in ins:
        row = rows.get((a, round(x, 2)))
        if row is None:
            okp = False
            continue
        okp &= np.allclose([x, y, z], [float(row["px"]), float(row["py"]), -float(row["pz"])], atol=1e-4)
        q = [float(row[k]) for k in ("qx", "qy", "qz", "qw")]
        okr &= np.allclose(qmat([qx, qy, qz, qw]), Pz @ qmat(q) @ Pz, atol=1e-5)
    check("instances: Unity position (x, y, -z) and rotation (matrix = P R P, P = diag(1, 1, -1)) for all 40",
          okp and okr)
    ln = pr.get("lines", [])
    check("road polylines: one of 19 points starting at (100, 3, -100)", ln == [[19, 100.0, 3.0, -100.0]], ln)
    of_ = subprocess.run([mono, exe, cwj_, "facade", "M_BrickBuff"], capture_output=True, text=True)
    pf_ = json.loads(of_.stdout) if of_.returncode == 0 else {}
    of2_ = subprocess.run([mono, exe, cwj_, "facade", "M_Stucco"], capture_output=True, text=True)
    pf2_ = json.loads(of2_.stdout) if of2_.returncode == 0 else {}
    check("Unity: a facade material's textures from World.json (the files that exist, under the output folder); "
          "M_Stucco: only its normal", sorted(pf_) == ["basecolor", "normal"]
          and pf_["basecolor"].endswith("pcg/materials/T_M_BrickBuff_BaseColor.png") and sorted(pf2_) == ["normal"],
          (pf_, pf2_, of_.stderr[-300:]))
    r2 = subprocess.run([mcs, "-target:library", "-define:UNITY_EDITOR", "-out:" + os.path.join(tmp, "imp.dll"),
                         os.path.join(_R, "engine", "UnityStubs.cs"), os.path.join(U, "PcgWorldCore.cs"),
                         os.path.join(U, "PcgWorldImporter.cs")], capture_output=True, text=True)
    check("the Editor importer compiles against Unity's signatures (stubs)", r2.returncode == 0,
          r2.stdout[-600:] + r2.stderr[-600:])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
