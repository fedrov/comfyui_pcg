"""
Unreal Engine import of a comfyui_pcg world (World.json, written by the World Manifest node).

Run it in the Unreal Editor's Python console (Edit > Plugins: Python Editor Script Plugin, glTF Importer / Interchange):

    import sys; sys.path.append(r"<this folder>")
    import pcg_world_import as W
    W.run(r"D:/ComfyUI/output/pcg/world/World.json")

What it does, all from World.json:

  terrain     the full-map 16-bit heightmap and the Landscape settings that reproduce the heights exactly (resolution,
              Scale X / Y / Z, location; printed, and applied when a Landscape is created with the editor's import
              dialog -- Unreal exposes no Python call that builds a Landscape from a file), plus the splat maps and
              layer textures, imported as textures for the landscape material's layers
  meshes      every glb (buildings, water, the asset library) imported as static meshes; each building asset's LOD
              chain (LOD Create -> Export Mesh's LOD manifest) set up on its LOD0 mesh with the manifest's Unreal
              screen sizes; the towns and the water placed in the level, one folder per tile
  collision   an asset whose LOD manifest lists collision nodes (UCX_<asset>_NN) gets a convex collision built on
              its LOD0 mesh (one hull, as the UCX was), and the UCX meshes the glb import made are deleted
  instances   the instance tables as Hierarchical Instanced Static Mesh components, one actor per tile and asset;
              an asset is the static mesh of that name under content_root (import or make your own), else skipped.
              With World.json's city key (the modular city), an instance's facade column picks a material that
              replaces the wall slot: one component per asset and facade, the override set on it (the material
              found by name anywhere under content_root, e.g. imported with the material library's textures)
  roads       the road classes' polylines as spline actors (a Spline component per line) with the class's width
              and material in their tags, for a road tool to sweep

Coordinates: World.json's are metres, +Y up, x east, z south, the world in 0..size from the north-west corner.
Unreal: X = x, Y = z, Z = y, centimetres. The map is not mirrored (Y runs south in both), rotations follow the
same axis swap (a reflection: quaternion (x, y, z, w) -> (-x, -z, -y, w)).

The pure part (reading World.json, converting coordinates, the plans) runs without Unreal and is what the plugin's
tests check; the part that calls Unreal is run().
"""
from __future__ import annotations

import csv
import json
import math
import os

CM = 100.0


# ── the pure part ────────────────────────────────────────────────────────────────────────────────────────────────
def load(world_json):
    """-> (world dict, the folder the paths in it are relative to: ComfyUI's output folder)."""
    with open(world_json, encoding="utf-8") as f:
        world = json.load(f)
    if world.get("format") != "pcg-world":
        raise ValueError(f"{world_json}: not a pcg-world manifest")
    here = os.path.dirname(os.path.abspath(world_json))
    folder = str(world.get("folder", "")).strip("/")
    root = here
    for _ in [p for p in folder.split("/") if p]:
        root = os.path.dirname(root)
    return world, root


def location(p):
    """World.json metres (x, y, z) -> Unreal centimetres (X, Y, Z)."""
    return (float(p[0]) * CM, float(p[2]) * CM, float(p[1]) * CM)


def rotation_quat(q):
    """World.json quaternion (x, y, z, w) -> Unreal's (X, Y, Z, W): the y <-> z swap is a reflection, so the axis
    turns as a pseudovector (-swap(axis)) and the angle keeps its sign."""
    x, y, z, w = (float(v) for v in q)
    return (-x, -z, -y, w)


def scale(s):
    return (float(s[0]), float(s[2]), float(s[1]))


def quat_matrix(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def landscape_settings(world, root):
    """The Landscape import settings that reproduce the heightmap: the full-map r16 (or the tiles), resolution,
    Scale X / Y (cm a sample), Scale Z and the actor's Z so that pixel value v lands at the manifest's metres.
    Unreal: Z = actor Z + (v - 32768) / 128 * ScaleZ (cm); the manifest: metres = r0 + v / 65535 * (r1 - r0)."""
    t = world.get("terrain")
    if not t:
        return None
    r0, r1 = (float(v) for v in t["range_metres"])
    sz = 12800.0 * (r1 - r0) / 65535.0
    z0 = CM * r0 + 32768.0 * CM * (r1 - r0) / 65535.0
    raw = None
    for name, img in world.get("images", {}).items():
        fs = img.get("files", [])
        if img.get("role") == "height" and len(fs) == 1 and fs[0]["file"].endswith(".r16"):
            raw = os.path.join(root, fs[0]["file"])
    n = int(t["samples"][0])
    mps = float(t.get("metres_per_sample") or 1.0)
    return {"heightmap_r16": raw, "resolution": [n, int(t["samples"][1])], "scale_xy": mps * CM, "scale_z": sz,
            "location": [0.0, 0.0, z0], "range_metres": [r0, r1],
            "note": "Landscape mode > Import from File: this .r16, the resolution above (fit to data), Location "
                    "and Scale as given; the actor's X / Y at the world's minimum corner"}


def landscape_height_cm(settings, v):
    """Unreal's height of 16-bit value v with these settings (for checking)."""
    return settings["location"][2] + (float(v) - 32768.0) / 128.0 * settings["scale_z"]


def instance_groups(world, root, tile=None):
    """-> {(asset, override material or ""): [(location cm, quaternion, scale), ...]}: as read_instances, split by
    the material World.json's city key gives the instance's facade value (0, or no city key: no override)."""
    city = world.get("city") or {}
    col = city.get("instances_facade_column", "facade")
    fm = city.get("facade_materials") or {}
    wall = city.get("wall_material", "")
    out = {}
    for fn in _instance_files(world, root, tile):
        with open(fn, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ov = ""
                if city and row.get(col) not in (None, ""):
                    m = fm.get(str(int(float(row[col]))), "")
                    ov = "" if m in ("", wall) else m
                out.setdefault((row["asset"], ov), []).append(
                    (location((row["px"], row["py"], row["pz"])),
                     rotation_quat((row["qx"], row["qy"], row["qz"], row["qw"])),
                     scale((row["sx"], row["sy"], row["sz"]))))
    return out


def _instance_files(world, root, tile=None):
    ins = world.get("instances") or {}
    files = ins.get("files", [])
    if tile is not None:
        t = next((x for x in world["tiles"] if list(x["tile"]) == list(tile)), None)
        if t is None:
            return []
        with open(os.path.join(root, t["file"]), encoding="utf-8") as f:
            files = json.load(f)["instances"]["files"]
    return [os.path.join(root, fn) for fn in files if os.path.exists(os.path.join(root, fn))]


def read_instances(world, root, tile=None):
    """-> {asset: [(location cm, quaternion, scale), ...]} from the instance tables (one tile, or all)."""
    out = {}
    ins = world.get("instances") or {}
    files = ins.get("files", [])
    if tile is not None:
        t = next((x for x in world["tiles"] if list(x["tile"]) == list(tile)), None)
        if t is None:
            return out
        with open(os.path.join(root, t["file"]), encoding="utf-8") as f:
            files = json.load(f)["instances"]["files"]
    for fn in files:
        p = os.path.join(root, fn)
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                loc = location((row["px"], row["py"], row["pz"]))
                q = rotation_quat((row["qx"], row["qy"], row["qz"], row["qw"]))
                s = scale((row["sx"], row["sy"], row["sz"]))
                out.setdefault(row["asset"], []).append((loc, q, s))
    return out


def lod_plan(world):
    """-> [{asset, file, nodes: [LOD0 node, LOD1 ...], screen_sizes}] for every mesh with a LOD manifest."""
    plan = []
    for key, m in world.get("meshes", {}).items():
        for a in m.get("assets", []) or []:
            lods = sorted(a.get("lods", []), key=lambda l_: l_.get("lod", 0))
            plan.append({"asset": a["name"], "file": m["file"], "role": m.get("role"),
                         "nodes": [l_["node"] for l_ in lods],
                         "screen_sizes": [float(l_.get("screen_size", 1.0)) for l_ in lods],
                         "bounds": a.get("bounds"), "collision": list(a.get("collision") or [])})
    return plan


def read_obj_lines(path):
    vs, lines = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.startswith("v "):
                p = ln.split()
                vs.append((float(p[1]), float(p[2]), float(p[3])))
            elif ln.startswith("l "):
                idx = [int(t.split("/")[0]) for t in ln.split()[1:]]
                lines.append([vs[i - 1 if i > 0 else len(vs) + i] for i in idx])
    return lines


def road_plan(world, root):
    """-> [{class, width_cm, material, lines: [[(X, Y, Z) cm ...], ...]}] from the road classes in World.json
    (Extra JSON's road_classes), or every polyline set as one class when there are none."""
    classes = world.get("road_classes") or {k: {"polylines": k} for k in world.get("polylines", {})}
    plan = []
    for cls, c in classes.items():
        pl = world.get("polylines", {}).get(c.get("polylines", ""))
        if not pl:
            continue
        lines = [[location(p) for p in ln] for ln in read_obj_lines(os.path.join(root, pl["file"]))]
        plan.append({"class": cls, "width_cm": float(c.get("width_m", 4.0)) * CM, "material": c.get("material", ""),
                     "lamp": c.get("lamp"), "lines": lines})
    return plan


# instance assets without a mesh of their own name use the exported proxies (prefix -> static mesh)
ASSET_FALLBACK = (("Tree_Pine", "SM_Proxy_Pine_LOD0"), ("Tree_Broadleaf", "SM_Proxy_Broadleaf_LOD0"),
                  ("Tree_Fruit", "SM_Proxy_Fruit"), ("Hedge", "SM_Proxy_Hedge"))


def asset_mesh_name(asset, available, fallback=ASSET_FALLBACK):
    """The static mesh an instance asset uses: its own name when there is such a mesh, else <asset>_LOD0 (its LOD
    chain), else the first fallback
    whose prefix it starts with and that exists, else None (skipped)."""
    if asset in available:
        return asset
    if asset + "_LOD0" in available:            # a LOD chain (LOD Create's <asset>_LOD0 carries the others)
        return asset + "_LOD0"
    for pre, m in fallback:
        if asset.startswith(pre) and m in available:
            return m
    return None


def texture_plan(world, root):
    """-> [(file, srgb)] of the terrain's image sets worth importing: colour (sRGB), normal, splat, layers."""
    out = []
    for name, img in world.get("images", {}).items():
        if img.get("role") not in ("texture", "water"):
            continue
        srgb = img.get("encode") == "srgb"
        for fe in img.get("files", []):
            out.append((os.path.join(root, fe["file"]), srgb))
    return out


# ── the Unreal part ──────────────────────────────────────────────────────────────────────────────────────────────
def run(world_json, content_root="/Game/PCGWorld", meshes=True, textures=True, instances=True, roads=True,
        max_instances_per_asset=None, mesh_yaw=0.0):
    """mesh_yaw: a turn (degrees about Z) for the placed glb meshes, should your glTF importer convert the axes
    differently from World.json's X = x, Y = z (the towns then lie off the landscape: try 90 or -90)."""
    import unreal                                                   # noqa: F401 -- only inside the editor
    world, root = load(world_json)
    log = unreal.log
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    def import_files(files, dest):
        tasks = []
        for fp in files:
            t = unreal.AssetImportTask()
            t.set_editor_property("filename", fp)
            t.set_editor_property("destination_path", dest)
            t.set_editor_property("automated", True)
            t.set_editor_property("replace_existing", True)
            t.set_editor_property("save", True)
            tasks.append(t)
        if tasks:
            tools.import_asset_tasks(tasks)
        return [p for t in tasks for p in t.get_editor_property("imported_object_paths")]

    ls = landscape_settings(world, root)
    if ls:
        log("PCG World: Landscape -- " + json.dumps(ls, indent=1))
    if textures:
        tex = texture_plan(world, root)
        paths = import_files([f for f, _ in tex], content_root + "/Textures")
        for (f, srgb), p in zip(tex, paths):
            a = unreal.load_asset(p)
            if a is not None and not srgb:
                a.set_editor_property("srgb", False)
        log(f"PCG World: {len(paths)} textures")
    if meshes:
        for key, m in world.get("meshes", {}).items():
            import_files([os.path.join(root, m["file"])], f"{content_root}/{m.get('role', 'meshes').capitalize()}")
        sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        for p in lod_plan(world):
            dest = f"{content_root}/{(p['role'] or 'meshes').capitalize()}"
            base = unreal.load_asset(f"{dest}/{p['nodes'][0]}")
            if base is None:
                unreal.log_warning(f"PCG World: no static mesh {p['nodes'][0]} under {dest}")
                continue
            for k, node in enumerate(p["nodes"][1:], 1):
                src = unreal.load_asset(f"{dest}/{node}")
                if src is not None:
                    sub.set_lod_from_static_mesh(base, k, src, 0, True)
            base.set_editor_property("auto_compute_lod_screen_size", False)
            sm = base.get_editor_property("source_models")
            for k, ssz in enumerate(p["screen_sizes"][:len(sm)]):
                sm[k].set_editor_property("screen_size", unreal.PerPlatformFloat(default=ssz))
            base.set_editor_property("source_models", sm)
            if p["collision"]:
                # the UCX was the piece's convex hull: the same, built on the mesh (glTF imports keep UCX_ a mesh)
                try:
                    sub.set_convex_decomposition_collisions(base, len(p["collision"]), 32, 100000)
                except Exception as e:                              # noqa: BLE001 -- an engine without the call
                    unreal.log_warning(f"PCG World: no convex collision for {p['asset']}: {e}")
                for u in p["collision"]:
                    if unreal.EditorAssetLibrary.does_asset_exist(f"{dest}/{u}"):
                        unreal.EditorAssetLibrary.delete_asset(f"{dest}/{u}")
            if p["role"] == "buildings":
                a = actors.spawn_actor_from_object(base, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, mesh_yaw))
                a.set_actor_label(p["asset"])
                b = p.get("bounds") or {}
                c = b.get("center")
                if c:
                    a.set_folder_path(f"PCGWorld/Tile_x{int(c[0] // world['coordinates']['tile_size'])}"
                                      f"_y{int(c[2] // world['coordinates']['tile_size'])}")
        log("PCG World: meshes and LODs")
    if instances:
        subd = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        reg = unreal.AssetRegistryHelpers.get_asset_registry()
        avail = {str(d.asset_name) for d in reg.get_assets_by_path(f"{content_root}/Assets", recursive=True)}
        mats = {str(d.asset_name): str(d.package_name) for d in reg.get_assets_by_path(content_root, recursive=True)
                if str(d.asset_class_path.asset_name if hasattr(d, "asset_class_path") else d.asset_class)
                in ("Material", "MaterialInstanceConstant")}
        wall = (world.get("city") or {}).get("wall_material", "")
        for t in world.get("tiles", []):
            for (asset, ov), xs in instance_groups(world, root, t["tile"]).items():
                mn = asset_mesh_name(asset, avail)
                mesh = unreal.load_asset(f"{content_root}/Assets/{mn}") if mn else None
                if mesh is None:
                    continue
                if max_instances_per_asset:
                    xs = xs[:max_instances_per_asset]
                actor = actors.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0))
                actor.set_actor_label(f"{asset}{'_' + ov if ov else ''}_x{t['tile'][0]}_y{t['tile'][1]}")
                actor.set_folder_path(f"PCGWorld/Tile_x{t['tile'][0]}_y{t['tile'][1]}")
                root_h = subd.k2_gather_subobject_data_for_instance(actor)[0]
                params = unreal.AddNewSubobjectParams(parent_handle=root_h,
                                                      new_class=unreal.HierarchicalInstancedStaticMeshComponent)
                h, _ = subd.add_new_subobject(params)
                comp = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
                    unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h))
                comp.set_static_mesh(mesh)
                if ov:
                    m_ = unreal.load_asset(mats[ov]) if ov in mats else None
                    k_ = mesh.get_material_index(wall) if wall else -1
                    if m_ is not None and k_ >= 0:
                        comp.set_material(k_, m_)
                    else:
                        unreal.log_warning(f"PCG World: no material {ov} under {content_root} (or no slot {wall})")
                for loc, q, s in xs:
                    comp.add_instance(unreal.Transform(unreal.Vector(*loc), unreal.Quat(*q).rotator(),
                                                       unreal.Vector(*s)), True)
        log("PCG World: instances")
    if roads:
        for rc in road_plan(world, root):
            for i, ln in enumerate(rc["lines"]):
                a = actors.spawn_actor_from_class(unreal.Actor, unreal.Vector(*ln[0]))
                a.set_actor_label(f"Road_{rc['class']}_{i:03d}")
                a.set_folder_path(f"PCGWorld/Roads/{rc['class']}")
                a.tags = [f"road_class={rc['class']}", f"width_cm={rc['width_cm']:.0f}", f"material={rc['material']}"]
                subd = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
                root_h = subd.k2_gather_subobject_data_for_instance(a)[0]
                h, _ = subd.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=root_h,
                                                                           new_class=unreal.SplineComponent))
                sp = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
                    unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h))
                sp.set_spline_points([unreal.Vector(*p) for p in ln], unreal.SplineCoordinateSpace.WORLD, True)
        log("PCG World: road splines")
    return world
