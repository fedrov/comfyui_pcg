"""
World Manifest (geo/worldmanifest.py): a small world written by the real export nodes into a temporary output
folder, then read back; every number checked against what was written.

  1. Terrain: a 2 x 2 tiled 16-bit height (height = 100 x u) -> the terrain section, and per tile the decoded height
     range (left tiles 0..50 m, right tiles 50..100 m, at the pixel centres); negative control: the ranges differ
     between the columns; the tile bounds join the terrain and the contents
  2. Instances: 7 points of 3 assets -> the totals, the per-tile counts (by position) and the tiles' files
  3. Meshes: a town with two LOD levels (Export Mesh + LOD manifest) -> its nodes, bounds, materials; placed in the
     tile of its centre, nowhere else; a water quad over two tiles is listed in both
  4. Polylines: an 1800 m road from x = 100 to 1900 every 100 m -> length 1800, 900 m in each tile of its row
  5. Other files are listed; Extra JSON adds keys and may not replace the coordinates; a missing folder, bad JSON
     and a bad Origin raise; Origin = center moves the tile grid (the same town lands in another tile)
"""
import json
import os
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


tmp = tempfile.mkdtemp(prefix="pcg_wm_")
os.chdir(tmp)                                    # output_dir() outside ComfyUI = ./output
OUT = os.path.join(tmp, "output")
F = "pcg/w"

# 1. the height: 129 x 129 samples over 2048 m, height = 100 u, two by two tiles of 65 with a shared edge
cop = nrun("COPConstant", resolution_x=129, resolution_y=129, layer="base", device="numpy")[0]
cop = nrun("COPWrangle", cop=cop, code="@C = @u")[0]
nrun("COPWriteFile", cop=cop, filename=F + "/height/Height_x{tx}_y{ty}", channels="C", format="png", bit_depth="16",
     encode="linear", remap="normalize", tiles_x=2, tiles_y=2, shared_edge=True, value_scale=100.0)

# 2. instances (world metres, the corner at 0): tile (0, 0) 3, (1, 0) 1, (0, 1) 2, (1, 1) 1
pts = np.array([[10, 5, 10], [500, 5, 900], [1000, 5, 20], [1500, 9, 300], [20, 3, 1100], [700, 3, 2000],
                [1800, 7, 1900]], np.float32)
names = np.array(["Tree_A", "Tree_A", "Rock_A", "Tree_B", "Rock_A", "Tree_A", "Tree_B"])
ig = Geometry.from_points(pts)
ig.set_string(POINT, "name", names)
nrun("ExportInstances", points=ig, filename=F + "/instances/Instances_x{tx}_y{ty}", format="csv", asset_attribute="name",
     extra_attributes="", tile_size=1024.0)

# 3. a town (LOD0 a 40 m box, LOD1 a 30 m box) round (300, 10, 1500): tile (0, 1); and a water quad across x = 1024
def named_box(size, center, name, mat):
    b = build.box(size=size, center=center)
    b.set_string(PRIM, "name", np.full(b.nprims, name))
    b.set_string(PRIM, "material", np.full(b.nprims, mat))
    return b


town = merge(named_box((40, 20, 40), (300, 10, 1500), "Town_01_LOD0", "M_Wall"),
             named_box((30, 15, 30), (300, 7.5, 1500), "Town_01_LOD1", "M_Roof"))
town.set(PRIM, "lod_distance", np.array([0.0] * 6 + [400.0] * 6, np.float32))
nrun("ExportMesh", geo=town, filename=F + "/buildings/Towns", format="glb", split_attribute="name",
     lod_manifest=True)
wq = build.grid(size_x=400.0, size_z=100.0, cols=2, rows=2, center=(1000.0, 1.0, 600.0))
wq.set_string(PRIM, "name", np.full(wq.nprims, "River"))
nrun("ExportMesh", geo=wq, filename=F + "/water/Water", format="glb", split_attribute="name")

# 4. a road along z = 100 from x = 100 to 1900, a point every 100 m
road = nrun("Line", dx=1.0, dy=0.0, dz=0.0, length=1800.0, points=19, origin_x=100.0, origin_y=0.0,
            origin_z=100.0)[0]
nrun("ExportMesh", geo=road, filename=F + "/roads/Roads", format="obj")

# 5. other files
os.makedirs(os.path.join(OUT, F, "notes"), exist_ok=True)
with open(os.path.join(OUT, F, "notes", "readme.txt"), "w") as f:
    f.write("hello")
with open(os.path.join(OUT, F, "notes", "settings.json"), "w") as f:
    json.dump({"a": 1}, f)

path, rep = nrun("WorldManifest", folder=F, world_size=2048.0, tile_size=1024.0, origin="north_west_corner",
                 extra_json='{"roads_classes": {"main": {"width": 6.5}}}', after1="x")
W = json.load(open(os.path.join(OUT, path)))
T = {tuple(t["tile"]): json.load(open(os.path.join(OUT, t["file"]))) for t in W["tiles"]}

print("\n[1. Terrain]")
ter = W.get("terrain") or {}
u0, u1 = 0.5 / 129 * 100, 128.5 / 129 * 100          # the pixel centres' u at the edges
check("World.json at the folder, 2 x 2 tiles; the terrain section: 129 samples, 16 m a sample, 65 per tile, "
      "the range of the samples (100 u at the pixel centres)", path == F + "/World.json" and len(T) == 4
      and ter.get("samples") == [129, 129] and abs(ter.get("metres_per_sample", 0) - 16.0) < 1e-9
      and ter.get("tile_samples") == 65 and np.allclose(ter.get("range_metres"), [u0, u1], atol=1e-3), ter)
rng = {k: tuple(t.get("height_range", (None, None))) for k, t in T.items()}
mid = 64.5 / 129 * 100                                 # the shared column
check("per tile the decoded height range: left column u0..mid, right column mid..u1 (u runs along x, the shared "
      "edge in both)", all(np.allclose(rng[(0, j)], [u0, mid], atol=0.01) and np.allclose(rng[(1, j)], [mid, u1],
                                                                                         atol=0.01) for j in (0, 1)),
      rng)
check("  negative control: the two columns' ranges differ", rng[(0, 0)] != rng[(1, 0)])
check("  the tile bounds join the terrain with the contents (tile (1, 0): the 9 m tree under the terrain's 50 m)",
      abs(T[(1, 0)]["bounds"]["min"][1] - 9.0) < 1e-6 and abs(T[(1, 0)]["bounds"]["max"][1] - u1) < 0.01,
      T[(1, 0)]["bounds"])
check("  each tile names its own height file", all(T[(i, j)]["terrain"].get("height/Height", "").endswith(
    f"_x{i}_y{j}.png") for i in (0, 1) for j in (0, 1)), {k: t["terrain"] for k, t in T.items()})

print("\n[2. Instances]")
ins = W.get("instances") or {}
check("totals: 7 instances, Tree_A 3, Tree_B 2, Rock_A 2", ins.get("count") == 7
      and ins.get("assets") == {"Rock_A": 2, "Tree_A": 3, "Tree_B": 2}, ins.get("assets"))
cnt = {k: t["instances"]["count"] for k, t in T.items()}
check("per tile by position: (0,0) 3, (1,0) 1, (0,1) 2, (1,1) 1, with their own CSV",
      cnt == {(0, 0): 3, (1, 0): 1, (0, 1): 2, (1, 1): 1}
      and all(len(t["instances"]["files"]) == 1 for t in T.values()), cnt)
check("  the per-tile asset counts: (0,0) Tree_A 2 + Rock_A 1", T[(0, 0)]["instances"]["assets"] ==
      {"Rock_A": 1, "Tree_A": 2}, T[(0, 0)]["instances"]["assets"])

print("\n[3. Meshes]")
tw = W["meshes"].get("buildings/Towns.glb", {})
nodes = {n["name"]: n for n in tw.get("nodes", [])}
b0 = nodes.get("Town_01_LOD0", {}).get("bounds", {})
check("the town's glb: two nodes, LOD0's bounds (280, 0, 1480)..(320, 20, 1520), materials M_Wall and M_Roof",
      set(nodes) == {"Town_01_LOD0", "Town_01_LOD1"} and np.allclose(b0.get("min", [0] * 3), [280, 0, 1480], atol=1e-3)
      and np.allclose(b0.get("max", [0] * 3), [320, 20, 1520], atol=1e-3)
      and set(tw.get("materials", [])) == {"M_Wall", "M_Roof"}, b0)
la = (tw.get("assets") or [{}])[0]
check("  its LOD manifest: asset Town_01, LOD nodes in order, distances 0 and 400",
      la.get("name") == "Town_01" and [l_["node"] for l_ in la.get("lods", [])] == ["Town_01_LOD0", "Town_01_LOD1"]
      and [l_["distance"] for l_ in la["lods"]] == [0.0, 400.0], la)
bt = {k: [b["name"] for b in t["buildings"]] for k, t in T.items()}
check("  placed in the tile of its centre (0, 1) and nowhere else", bt == {(0, 0): [], (1, 0): [], (0, 1): ["Town_01"],
                                                                           (1, 1): []}, bt)
wt = {k: [w["node"] for w in t["water"]] for k, t in T.items()}
check("the water quad (x 800..1200 at z 600) is listed in both tiles of row 0 and not in row 1",
      wt == {(0, 0): ["River"], (1, 0): ["River"], (0, 1): [], (1, 1): []}, wt)

print("\n[4. Polylines]")
rd = W["polylines"].get("roads/Roads", {})
check("the road: 1 line, 1800 m, bounds x 100..1900", rd.get("lines") == 1 and abs(rd.get("length_m", 0) - 1800) < 0.5
      and np.allclose([rd["bounds"]["min"][0], rd["bounds"]["max"][0]], [100, 1900], atol=1e-3), rd)
rl = {k: t["roads"].get("roads/Roads", 0.0) for k, t in T.items()}
check("  per tile: 900 m in (0,0) and (1,0), none in row 1", abs(rl[(0, 0)] - 900) < 0.5
      and abs(rl[(1, 0)] - 900) < 0.5 and rl[(0, 1)] == 0 and rl[(1, 1)] == 0, rl)

print("\n[5. The rest]")
other = sorted(f["file"] for f in W["files"])
check("other files listed (a text file, a JSON that is not a sidecar), nothing the manifest read",
      other == [F + "/notes/readme.txt", F + "/notes/settings.json"], other)
check("Extra JSON adds keys; the coordinates say metres, +Y up, the corner origin, 1024 m tiles",
      W.get("roads_classes") == {"main": {"width": 6.5}} and W["units"] == "metres" and W["up"] == "+Y"
      and W["coordinates"]["origin"] == "north_west_corner" and W["coordinates"]["tile_size"] == 1024.0)


def raises(**kw):
    try:
        nrun("WorldManifest", **kw)
        return False
    except ValueError:
        return True


check("a missing folder, bad Extra JSON, Extra JSON replacing the coordinates and a bad Origin raise",
      raises(folder="pcg/nothing_here") and raises(folder=F, extra_json="{not json")
      and raises(folder=F, extra_json='{"coordinates": 1}') and raises(folder=F, origin="south"))
_, rep2 = nrun("WorldManifest", folder=F, world_size=2048.0, tile_size=1024.0, origin="center")
W2 = json.load(open(os.path.join(OUT, F, "World.json")))
T2 = {tuple(t["tile"]): json.load(open(os.path.join(OUT, t["file"]))) for t in W2["tiles"]}
bt2 = [k for k, t in T2.items() if t["buildings"]]
# with the centre at (0, 0) the world spans -1024..1024: the town at (300, 1500) is beyond the edge and clamps to
# the last row, column 1 (x 300 > 0)
check("Origin = center: the grid spans -1024..1024, the same town lands in tile (1, 1) instead of (0, 1)",
      W2["coordinates"]["world_min"] == [-1024.0, -1024.0] and bt2 == [(1, 1)], bt2)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
