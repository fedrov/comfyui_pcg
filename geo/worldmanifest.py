"""
World Manifest: one JSON file that describes a world written to disk by the other export nodes -- the height and
texture tiles (their sidecar JSONs), the instance tables, the building and asset glbs (their nodes, bounds and LOD
manifests), the road polylines, the water meshes -- with the coordinate convention, plus one JSON per tile for
streaming (what lies in that tile: its terrain files, instance counts, the building nodes, road length, the bounds).

Everything is read back from the files themselves, so the manifest describes what is really there:

  *.json sidecars of COP Write File  -> image sets (terrain height, colour, normal, splat, layers ...); a set with
                                        tiles names the files per tile
  Instances_index.json (Export Instances) and its per-tile CSVs -> instance counts per asset and tile, bounds
  *.glb (Export Mesh)                -> nodes, meshes, materials, bounds (POSITION min / max); a .lods.json beside it
                                        (LOD Manifest) adds each asset's LOD nodes and switch distances
  *.obj polylines                    -> the number of lines, their length, bounds
  anything else                      -> listed under files

The role of a file is its first folder under the world folder (height, texture, instances, buildings, roads, water,
assets ...). Coordinates: the files' own (metres, +Y up); Origin says where (0, 0) lies -- the north-west corner
(x east, z south, the world in [0, size]) or the centre ([-size/2, size/2]).
"""
from __future__ import annotations

import csv
import json
import math
import os
import struct

ORIGINS = ("north_west_corner", "center")


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _key(path):
    """One spelling per file: on Windows os.walk gives back-slashed paths while the sidecars' relative paths are joined
    on with forward slashes ("...\\output\\pcg/world/height/Height.json"); as dict keys the two never met."""
    return os.path.normcase(os.path.normpath(path))


class _PathSet(set):
    """A set of files that compares them by _key."""

    def add(self, p):
        super().add(_key(p))

    def __contains__(self, p):
        return super().__contains__(_key(p))


def _glb_json(path):
    with open(path, "rb") as f:
        head = f.read(20)
        if len(head) < 20 or head[:4] != b"glTF":
            raise ValueError("not a glb")
        n = struct.unpack("<I", head[12:16])[0]
        return json.loads(f.read(n).decode("utf-8"))


def _bounds_union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return {"min": [min(x, y) for x, y in zip(a["min"], b["min"])],
            "max": [max(x, y) for x, y in zip(a["max"], b["max"])]}


def _r(v, k=3):
    return [round(float(x), k) for x in v]


def read_glb(path):
    """-> {nodes: [{name, mesh, bounds, materials, instances}], materials, bounds} (bounds from POSITION min/max,
    translations and scales of the nodes applied; GPU-instanced nodes list their instance count)."""
    j = _glb_json(path)
    acc = j.get("accessors", [])
    mats = [m.get("name", f"material_{i}") for i, m in enumerate(j.get("materials", []))]
    meshes = []
    for m in j.get("meshes", []):
        b, ms, tris = None, set(), 0
        for p in m.get("primitives", []):
            a = acc[p["attributes"]["POSITION"]] if "POSITION" in p.get("attributes", {}) else None
            if a is not None and "min" in a and "max" in a:
                b = _bounds_union(b, {"min": list(a["min"]), "max": list(a["max"])})
            if "material" in p and p["material"] < len(mats):
                ms.add(mats[p["material"]])
            if "indices" in p:
                tris += int(acc[p["indices"]]["count"]) // 3
            elif a is not None:
                tris += int(a["count"]) // 3
        meshes.append((b, sorted(ms), tris))
    nodes, allb = [], None
    for nd in j.get("nodes", []):
        e = {"name": nd.get("name", "")}
        if "mesh" in nd and nd["mesh"] < len(meshes):
            b, ms, tris = meshes[nd["mesh"]]
            e["mesh"] = j["meshes"][nd["mesh"]].get("name", f"mesh_{nd['mesh']}")
            e["materials"] = ms
            e["triangles"] = tris
            inst = nd.get("extensions", {}).get("EXT_mesh_gpu_instancing")
            if inst is not None:
                ta = inst.get("attributes", {}).get("TRANSLATION")
                e["instances"] = int(acc[ta]["count"]) if ta is not None else 0
                if ta is not None and "min" in acc[ta] and b is not None:
                    tmn, tmx = acc[ta]["min"], acc[ta]["max"]
                    b = {"min": [b["min"][i] + tmn[i] for i in range(3)], "max": [b["max"][i] + tmx[i] for i in range(3)]}
            elif b is not None:
                t = nd.get("translation", [0.0, 0.0, 0.0])
                s = nd.get("scale", [1.0, 1.0, 1.0])
                lo = [b["min"][i] * s[i] + t[i] for i in range(3)]
                hi = [b["max"][i] * s[i] + t[i] for i in range(3)]
                b = {"min": [min(lo[i], hi[i]) for i in range(3)], "max": [max(lo[i], hi[i]) for i in range(3)]}
            if b is not None:
                e["bounds"] = {"min": _r(b["min"]), "max": _r(b["max"])}
                allb = _bounds_union(allb, e["bounds"])
        nodes.append(e)
    return {"nodes": nodes, "materials": mats, "bounds": allb}


def read_obj_lines(path):
    """-> list of polylines ((n, 3) lists) of an OBJ's 'l' records (1-based, negative indices allowed)."""
    vs, lines = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.startswith("v "):
                p = ln.split()
                vs.append((float(p[1]), float(p[2]), float(p[3])))
            elif ln.startswith("l "):
                idx = []
                for t in ln.split()[1:]:
                    k = int(t.split("/")[0])
                    idx.append(k - 1 if k > 0 else len(vs) + k)
                lines.append([vs[i] for i in idx])
    return lines


def _poly_stats(lines):
    n, length, b = len(lines), 0.0, None
    for pl in lines:
        for a, c in zip(pl[:-1], pl[1:]):
            length += math.dist(a, c)
        if pl:
            xs = list(zip(*pl))
            b = _bounds_union(b, {"min": [min(x) for x in xs], "max": [max(x) for x in xs]})
    return n, length, b


def _tile_of(x, z, x0, z0, ts, nt):
    i = int(math.floor((x - x0) / ts))
    j = int(math.floor((z - z0) / ts))
    return min(max(i, 0), nt[0] - 1), min(max(j, 0), nt[1] - 1)


def _image_range(path, side, tile):
    """Decoded min / max of a 16-bit (or 8-bit) one-channel tile, with its sidecar's range and scale."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    try:
        a = np.asarray(Image.open(path))
    except Exception:                                   # noqa: BLE001 -- unreadable: no range
        return None
    if a.ndim == 3:
        a = a[..., 0]
    mx = 65535.0 if int(side.get("bits", 8)) == 16 else 255.0
    lo, hi = side.get("range", [0.0, 1.0])
    vs = float(side.get("value_scale", 1.0))
    v = lambda p: (lo + float(p) / mx * (hi - lo)) * vs        # noqa: E731
    return [v(a.min()), v(a.max())]


def build_manifest(root, folder, world_size=4096.0, tile_size=1024.0, origin="north_west_corner", extra=None):
    """Scan <root>/<folder>, write <folder>/World.json and <folder>/tiles/Tile_x{i}_y{j}.json. -> (world, report)"""
    if origin not in ORIGINS:
        raise ValueError(f"World Manifest: Origin must be one of {ORIGINS}, got {origin!r}")
    base = os.path.join(root, folder)
    if not os.path.isdir(base):
        raise ValueError(f"World Manifest: no folder {folder!r} under the output folder -- run the exports first "
                         "(link their outputs to this node's after inputs so they run before it)")
    ws, ts = float(world_size), float(tile_size)
    if ws <= 0 or ts <= 0:
        raise ValueError("World Manifest: World Size and Tile Size must be positive")
    nt = (max(1, int(math.ceil(ws / ts - 1e-9))),) * 2
    x0 = z0 = 0.0 if origin == "north_west_corner" else -ws / 2
    files = []
    for dp, dn, fn in os.walk(base):
        dn[:] = sorted(d for d in dn if not (dp == base and d == "tiles"))
        for f in sorted(fn):
            if dp == base and f == "World.json":
                continue
            files.append(os.path.join(dp, f))
    used = _PathSet()
    tiles = {(i, j): {"tile": [i, j], "terrain": {}, "instances": {"count": 0, "assets": {}, "files": []},
                      "buildings": [], "roads": {}, "water": [], "assets": [], "bounds": None}
             for i in range(nt[0]) for j in range(nt[1])}

    def role(p):
        r = _rel(p, base).split("/")
        return r[0] if len(r) > 1 else "root"

    def file_ref(p):
        return _rel(p, root)

    world = {
        "format": "pcg-world", "version": 1, "generator": "comfyui_pcg World Manifest",
        "folder": folder,
        "units": "metres", "up": "+Y",
        "coordinates": {
            "origin": origin,
            "x": "east", "z": "south (x cross z = -y: a right-handed frame with +Y up, as glTF)",
            "world_min": [x0, z0], "world_max": [x0 + ws, z0 + ws],
            "tile_size": ts, "tiles": list(nt),
            "tile_index": "tile (i, j) covers x in [x0 + i*tile, x0 + (i+1)*tile], z in [z0 + j*tile, ...]; "
                          "file suffix _x{i}_y{j}",
            "images": "image row 0 at the tile's smallest z, column 0 at its smallest x (rows run south)",
            "paths": "relative to ComfyUI's output folder",
            "unreal": "X = x, Y = z, Z = y, centimetres = metres * 100 (Unreal is left-handed with Z up: x east, "
                      "y south keeps the map unmirrored)",
            "unity": "x = x, y = y, z = -z (Unity is left-handed with Y up), metres",
        },
        "terrain": None, "images": {}, "instances": None, "meshes": {}, "polylines": {}, "files": [],
        "tiles": [],
    }
    # ── image sets (COP Write File sidecars)
    sidecars = {}
    for p in files:
        if not p.endswith(".json") or p.endswith(".lods.json") or os.path.basename(p) == "Instances_index.json":
            continue
        try:
            with open(p, encoding="utf-8") as f:
                side = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(side, dict) or "files" not in side or "channels" not in side:
            continue
        sidecars[_key(p)] = side
        used.add(p)
        name = os.path.splitext(_rel(p, base))[0]
        ent = {"sidecar": file_ref(p), "role": role(p), "channels": side.get("channels"),
               "bits": side.get("bits"), "encode": side.get("encode"), "range_scaled": side.get("range_scaled"),
               "decode": side.get("decode"), "source_size": side.get("source_size"), "tiles": side.get("tiles"),
               "shared_edge": side.get("shared_edge"), "files": []}
        tl = side.get("tiles") or [1, 1]
        for fe in side["files"]:
            fp = os.path.join(root, fe["file"])
            if os.path.exists(fp):
                used.add(fp)
            ent["files"].append({k: fe[k] for k in ("file", "tx", "ty", "width", "height") if k in fe})
            if list(tl) == list(nt):
                t = tiles.get((int(fe.get("tx", 0)), int(fe.get("ty", 0))))
                if t is not None:
                    t["terrain"][name] = fe["file"]
        world["images"][name] = ent
    # the height: the image set whose single channel is the height ('height' folder first)
    hs = [n for n, e in world["images"].items() if e["role"] == "height" and e["tiles"] and list(e["tiles"]) == list(nt)]
    if hs:
        h = world["images"][hs[0]]
        sz = h["source_size"] or [0, 0]
        world["terrain"] = {
            "heightmap": hs[0], "sidecar": h["sidecar"], "range_metres": h["range_scaled"], "bits": h["bits"],
            "samples": sz, "metres_per_sample": ws / max(int(sz[0]) - 1, 1) if sz and sz[0] else None,
            "tile_samples": (h["files"][0].get("width") if h["files"] else None),
            "shared_edge": h["shared_edge"],
            "decode": "metres = range_metres[0] + pixel / (2^bits - 1) * (range_metres[1] - range_metres[0])",
        }
        side = sidecars[_key(os.path.join(root, h["sidecar"]))]
        for fe in h["files"]:
            t = tiles.get((int(fe.get("tx", 0)), int(fe.get("ty", 0))))
            if t is None:
                continue
            rng = _image_range(os.path.join(root, fe["file"]), side, fe)
            if rng is not None:
                t["height_range"] = [round(rng[0], 3), round(rng[1], 3)]
                i, j = t["tile"]
                t["bounds"] = _bounds_union(t["bounds"], {"min": [x0 + i * ts, rng[0], z0 + j * ts],
                                                          "max": [x0 + (i + 1) * ts, rng[1], z0 + (j + 1) * ts]})
    # ── instance tables
    for p in files:
        if os.path.basename(p) != "Instances_index.json":
            continue
        used.add(p)
        with open(p, encoding="utf-8") as f:
            idx = json.load(f)
        tot, per = 0, {}
        for fe in idx.get("files", []):
            fp = os.path.join(root, fe["file"])
            if not os.path.exists(fp):
                continue
            used.add(fp)
            with open(fp, newline="", encoding="utf-8") as f:
                rd = csv.DictReader(f)
                for row in rd:
                    try:
                        x, y, z = float(row["px"]), float(row["py"]), float(row["pz"])
                    except (KeyError, ValueError):
                        continue
                    a = row.get("asset", "")
                    t = tiles[_tile_of(x, z, x0, z0, ts, nt)]
                    ti = t["instances"]
                    ti["count"] += 1
                    ti["assets"][a] = ti["assets"].get(a, 0) + 1
                    if fe["file"] not in ti["files"]:
                        ti["files"].append(fe["file"])
                    t["bounds"] = _bounds_union(t["bounds"], {"min": [x, y, z], "max": [x, y, z]})
                    per[a] = per.get(a, 0) + 1
                    tot += 1
        world["instances"] = {"index": file_ref(p), "columns": idx.get("columns"), "euler": idx.get("euler"),
                              "quaternion": idx.get("quaternion"), "unit_scale": idx.get("unit_scale"),
                              "count": tot, "assets": dict(sorted(per.items())),
                              "files": [fe["file"] for fe in idx.get("files", [])]}
    # ── meshes (glb) and their LOD manifests
    for p in files:
        if not p.endswith(".glb"):
            continue
        used.add(p)
        try:
            g = read_glb(p)
        except (OSError, ValueError, KeyError, IndexError) as e:
            world["meshes"][_rel(p, base)] = {"file": file_ref(p), "role": role(p), "error": str(e)}
            continue
        ent = {"file": file_ref(p), "role": role(p), "materials": g["materials"], "bounds": g["bounds"],
               "nodes": g["nodes"]}
        lp = p[:-4] + ".lods.json"
        lods = None
        if os.path.exists(lp):
            used.add(lp)
            with open(lp, encoding="utf-8") as f:
                lods = json.load(f)
            ent["lods"] = file_ref(lp)
            ent["assets"] = [{"name": a["name"], "bounds": a.get("bounds"), "materials": a.get("materials"),
                              "lods": [{k: l_[k] for k in ("lod", "node", "distance", "triangles", "screen_size",
                                                           "unity_transition") if k in l_} for l_ in a.get("lods", [])],
                              **({"collision": a["collision"]} if a.get("collision") else {})}
                             for a in lods.get("assets", [])]
        world["meshes"][_rel(p, base)] = ent
        # into the tiles: LOD assets by their bounds' centre; other nodes with bounds by theirs; instanced and
        # boundless nodes (an asset library) are not placed
        if lods is not None:
            for a in ent["assets"]:
                b = a.get("bounds")
                if not b:
                    continue
                c = b.get("center") or [(b["min"][k] + b["max"][k]) / 2 for k in range(3)]
                t = tiles[_tile_of(c[0], c[2], x0, z0, ts, nt)]
                t["buildings" if role(p) == "buildings" else "assets"].append(
                    {"file": file_ref(p), "name": a["name"], "nodes": [l_["node"] for l_ in a["lods"]],
                     "distances": [l_.get("distance") for l_ in a["lods"]],
                     "bounds": {"min": b["min"], "max": b["max"]}})
                t["bounds"] = _bounds_union(t["bounds"], {"min": b["min"], "max": b["max"]})
        elif role(p) not in ("assets",):
            for nd in g["nodes"]:
                b = nd.get("bounds")
                if not b or "instances" in nd:
                    continue
                key = "water" if role(p) == "water" else ("buildings" if role(p) == "buildings" else "assets")
                for (i, j), t in tiles.items():
                    tb = (x0 + i * ts, z0 + j * ts, x0 + (i + 1) * ts, z0 + (j + 1) * ts)
                    if b["max"][0] < tb[0] or b["min"][0] > tb[2] or b["max"][2] < tb[1] or b["min"][2] > tb[3]:
                        continue
                    t[key].append({"file": file_ref(p), "node": nd["name"], "bounds": b})
    # ── polylines (obj)
    for p in files:
        if not p.endswith(".obj"):
            continue
        used.add(p)
        mtl = p[:-4] + ".mtl"
        if os.path.exists(mtl):
            used.add(mtl)
        lines = read_obj_lines(p)
        if not lines:
            world["files"].append({"file": file_ref(p), "role": role(p)})
            continue
        n, length, b = _poly_stats(lines)
        name = os.path.splitext(_rel(p, base))[0]
        world["polylines"][name] = {"file": file_ref(p), "role": role(p), "lines": n, "length_m": round(length, 1),
                                    "bounds": {"min": _r(b["min"]), "max": _r(b["max"])} if b else None}
        for pl in lines:
            for a, c in zip(pl[:-1], pl[1:]):
                t = tiles[_tile_of((a[0] + c[0]) / 2, (a[2] + c[2]) / 2, x0, z0, ts, nt)]
                t["roads"][name] = t["roads"].get(name, 0.0) + math.dist(a, c)
    # ── everything else
    for p in files:
        if p not in used:
            world["files"].append({"file": file_ref(p), "role": role(p)})
    if extra:
        for k, v in extra.items():
            if k in ("format", "version", "tiles", "coordinates"):
                raise ValueError(f"World Manifest: Extra JSON may not replace {k!r}")
            world[k] = v
    # ── the tiles
    tdir = os.path.join(base, "tiles")
    os.makedirs(tdir, exist_ok=True)
    for (i, j), t in sorted(tiles.items()):
        t["roads"] = {k: round(v, 1) for k, v in sorted(t["roads"].items())}
        t["instances"]["assets"] = dict(sorted(t["instances"]["assets"].items()))
        t["extent"] = {"min": [x0 + i * ts, z0 + j * ts], "max": [x0 + (i + 1) * ts, z0 + (j + 1) * ts]}
        if t["bounds"] is not None:
            t["bounds"] = {"min": _r(t["bounds"]["min"]), "max": _r(t["bounds"]["max"])}
        fn = os.path.join(tdir, f"Tile_x{i}_y{j}.json")
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(t, f, indent=1, ensure_ascii=False)
        world["tiles"].append({"tile": [i, j], "file": file_ref(fn), "extent": t["extent"], "bounds": t["bounds"],
                               "instances": t["instances"]["count"], "buildings": len(t["buildings"])})
    out = os.path.join(base, "World.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(world, f, indent=1, ensure_ascii=False)
    rep = {"world": file_ref(out), "tiles": len(world["tiles"]), "image_sets": len(world["images"]),
           "meshes": len(world["meshes"]), "polylines": len(world["polylines"]),
           "instances": (world["instances"] or {}).get("count", 0), "other_files": len(world["files"])}
    return file_ref(out), world, rep
