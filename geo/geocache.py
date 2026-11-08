"""
Geometry disk cache -- a **complete** round trip Geometry <-> .npz.

Why it's needed: Geometry is an object living in the Python process and can't go into the workflow json.
So after closing and reopening ComfyUI the whole chain must be recomputed from scratch. With a long chain (boolean, reduce, UV unwrap and the like,
which are slow to begin with) every session start means waiting several minutes, while most of it hasn't changed at all.

Modelled on Houdini's File Cache SOP: compute once and write to disk, then read from disk afterwards.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Format: a JSON manifest + a set of npz arrays. **No pickle.**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`np.savez` only accepts arrays, so the structural information (which attribute belongs to which class, which prim a prim_data entry hangs
on) is written separately as a JSON manifest, itself stored as a 0-d string array.

**Why no pickle**: `np.load(allow_pickle=True)` amounts to executing arbitrary code from the file.
Cache files travel with projects, get copied around, may come from someone else -- a geometry cache shouldn't have
that much power. The cost is that prim_data only accepts numpy arrays: measured across the whole repo there are only three uses, `voxels` /
`knots_u` / `knots_v`, all arrays, so this restriction costs nothing for now.
Other types **raise an explicit error** rather than being silently dropped -- if silently dropped, the geometry read back would lack the voxel data,
and the error downstream would be miles away from the real cause.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What must round-trip -- nothing may be missed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    attribs       attribute tables of the four classes, including **<U string** attributes (dtype must be stored as is)
    groups        bool masks for point / vertex / prim
    edge_groups   name -> (E,2) point pairs
    topology       vertex_point / prim_offset / prim_closed / prim_type
    prim_data      per-prim variable-length side channel
    npoints       point count. **Cannot** be inferred from P -- pure-topology geometry without P is valid too

`_topo` is an adjacency cache derived from topology; not stored (rebuilt automatically on read).

dtypes must be preserved exactly. The first version cut corners and stored every float attribute as float32, so attributes `cast` to
float64 came back as float32 -- the round trip wasn't the identity, and it **didn't error**;
you'd only find out when precision went wrong downstream. Now each array's dtype is written into the manifest and reads back bit-identical.
"""
import json
import os

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, CLASSES, freeze

annotations = {}

MAGIC = "comfyui_pcg.geocache"
VERSION = 1
MANIFEST = "__manifest__"


def _key(*parts):
    return "/".join(str(p) for p in parts)


# ══════════════════════════════════════════════════════════════════ write
def dumps(geo: Geometry):
    """
    Geometry -> (manifest dict, {npz key: array}).
    Used by both save() and the unit tests, so "what was stored" can be asserted directly.
    """
    if geo is None:
        raise ValueError("No geometry to write -- is the upstream empty?")
    man = {"magic": MAGIC, "version": VERSION,
           "npoints": int(geo.npoints),
           "attribs": [], "groups": [], "edge_groups": [], "prim_data": []}
    arr = {}

    for cls in CLASSES:
        for name, a in sorted(geo.attribs[cls].items()):
            k = _key("a", cls, len(man["attribs"]))
            a = np.asarray(a)
            man["attribs"].append({"cls": cls, "name": name, "key": k,
                                   "dtype": a.dtype.str, "shape": list(a.shape)})
            arr[k] = a

    for cls in (POINT, VERTEX, PRIM):
        for name, m in sorted(geo.groups[cls].items()):
            k = _key("g", cls, len(man["groups"]))
            man["groups"].append({"cls": cls, "name": name, "key": k})
            arr[k] = np.asarray(m, bool)

    for name, pairs in sorted(geo.edge_groups.items()):
        k = _key("e", len(man["edge_groups"]))
        man["edge_groups"].append({"name": name, "key": k})
        arr[k] = np.asarray(pairs, np.int32).reshape(-1, 2)

    for pi in sorted(geo.prim_data):
        for name, v in sorted(geo.prim_data[pi].items()):
            if not isinstance(v, np.ndarray):
                raise ValueError(
                    f"prim {pi}'s prim_data['{name}'] is "
                    f"{type(v).__name__}, not a numpy array.\n"
                    f"  The cache format **deliberately avoids pickle** (see the module docstring), "
                    f"so only arrays can be stored.\n"
                    f"  This is not silently skipped -- if dropped silently, the geometry read back would be missing data, "
                    f"and the error would surface far from the real cause.")
            k = _key("p", pi, len(man["prim_data"]))
            man["prim_data"].append({"prim": int(pi), "name": name, "key": k,
                                     "dtype": v.dtype.str,
                                     "shape": list(v.shape)})
            arr[k] = v

    for name, a, dt in (("vertex_point", geo.vertex_point, np.int32),
                        ("prim_offset", geo.prim_offset, np.int32),
                        ("prim_closed", geo.prim_closed, bool),
                        ("prim_type", geo.prim_type, np.uint8)):
        arr[_key("t", name)] = np.asarray(a, dt)
    return man, arr


def save(path, geo: Geometry, compress=True):
    """Write to disk. Returns the path actually written."""
    man, arr = dumps(geo)
    path = str(path)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    payload = dict(arr)
    # the manifest itself goes in as a 0-d <U array
    payload[MANIFEST] = np.array(json.dumps(man, ensure_ascii=False))
    # **Write a temporary file, then rename.** Writing straight to the target file, a crash midway (or the user pressing
    # cancel) would leave a truncated npz, and the next read would hit a broken file rather than "no file" --
    # the latter can be recomputed automatically, the former only raises an incomprehensible zip error.
    tmp = path + ".part"
    try:
        (np.savez_compressed if compress else np.savez)(tmp, **payload)
        # numpy automatically appends .npz when there's no extension
        real_tmp = tmp if os.path.exists(tmp) else tmp + ".npz"
        os.replace(real_tmp, path)
    finally:
        for leftover in (tmp, tmp + ".npz"):
            if os.path.exists(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
    return path


# ══════════════════════════════════════════════════════════════════ read
def loads(man, get):
    """(manifest, array getter) -> Geometry. Used by both load() and the unit tests."""
    if man.get("magic") != MAGIC:
        raise ValueError(
            f"Not a PCG geometry cache (magic = {man.get('magic')!r}).")
    v = int(man.get("version", 0))
    if v > VERSION:
        raise ValueError(
            f"The cache was written by version {v}; this plugin only understands up to {VERSION} -- "
            f"the plugin is older than the cache. Regenerate the cache, or update the plugin.")

    g = Geometry()
    g._resize_points(int(man["npoints"]))

    for rec in man["attribs"]:
        a = np.asarray(get(rec["key"]))
        # restore dtype exactly. Without this, attributes cast to float64 silently drop back to float32
        want = np.dtype(rec["dtype"])
        if a.dtype != want:
            a = a.astype(want)
        g.attribs[rec["cls"]][rec["name"]] = freeze(a)

    for rec in man["groups"]:
        g.groups[rec["cls"]][rec["name"]] = freeze(
            np.asarray(get(rec["key"]), bool))

    for rec in man["edge_groups"]:
        g.edge_groups[rec["name"]] = freeze(
            np.asarray(get(rec["key"]), np.int32).reshape(-1, 2))

    for rec in man["prim_data"]:
        a = np.asarray(get(rec["key"]))
        want = np.dtype(rec["dtype"])
        if a.dtype != want:
            a = a.astype(want)
        g.prim_data.setdefault(int(rec["prim"]), {})[rec["name"]] = freeze(a)

    g.set_topology(np.asarray(get(_key("t", "vertex_point")), np.int32),
                   np.asarray(get(_key("t", "prim_offset")), np.int32),
                   np.asarray(get(_key("t", "prim_closed")), bool),
                   np.asarray(get(_key("t", "prim_type")), np.uint8))
    return g


def load(path):
    """Read from disk. A missing file / a file that isn't a cache both raise actionable errors."""
    path = str(path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Cache file does not exist: {path}\n"
            f"  Mode = read requires the file to already exist. For "
            f"\"read if present, otherwise compute and write it\", set Mode to auto.")
    try:
        z = np.load(path, allow_pickle=False)
    except Exception as ex:
        raise ValueError(
            f"Can't read {path} ({type(ex).__name__}: {ex}).\n"
            f"  The file may be truncated (interrupted while writing). Delete it to have it recomputed.") from ex
    with z:
        if MANIFEST not in z.files:
            raise ValueError(
                f"{path} has no manifest -- this isn't a PCG geometry cache, "
                f"just an ordinary npz.")
        man = json.loads(str(z[MANIFEST]))
        return loads(man, lambda k: z[k])


# ══════════════════════════════════════════════════════════════ path expansion
def expand(path, frame=None, version=None):
    """
    `$F` / `$F4` -> frame number, `$V` -> version number. Copies Houdini's syntax.

    `$F4` is zero-padded to 4 digits. Without it, per-frame cache file names would be cache_1.npz,
    cache_10.npz and so on, which sort out of order in a file manager.
    """
    s = str(path)
    if version is not None:
        s = s.replace("$V", str(int(version)))
    if frame is not None:
        f = int(frame)
        out, i = [], 0
        while i < len(s):
            if s[i] == "$" and s[i + 1:i + 2] == "F":
                j = i + 2
                dig = ""
                while j < len(s) and s[j].isdigit():
                    dig += s[j]
                    j += 1
                out.append(str(f).zfill(int(dig)) if dig else str(f))
                i = j
            else:
                out.append(s[i])
                i += 1
        s = "".join(out)
    return s


# ══════════════════════════════════════════════════════════ node-side logic
MODES = ("auto", "write", "read")


def output_root():
    """
    Root directory for relative paths.

    Prefer ComfyUI's own output directory -- it only makes sense for the cache to travel with the project, and users
    already know to look for files there. Outside ComfyUI (unit tests) fall back to the current directory.
    """
    try:
        import folder_paths
        return folder_paths.get_output_directory()
    except Exception:
        return os.getcwd()


def resolve(file, frame=None, version=None, root=None):
    """Turn the path from the widget into an absolute path. Relative paths hang under the output directory."""
    s = expand(file, frame, version).strip()
    if not s:
        raise ValueError("File is empty -- enter a file name, e.g. "
                         "pcg_cache/geo_$F4.npz")
    if not os.path.splitext(s)[1]:
        s += ".npz"
    if os.path.isabs(s):
        return s
    return os.path.join(root if root is not None else output_root(), s)


def will_read(mode, file, frame=None, version=None, root=None):
    """
    Is this a read or a write? **check_lazy_status relies on this to decide whether to touch the upstream.**

    This function must agree with run_cache's decision **exactly**. Disagreement has nasty consequences:
    check_lazy_status says "no upstream needed" while run_cache decides to write to disk -- so it writes with
    geo=None and raises an error unrelated to the real cause. That's why both sides call this one function.
    """
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if mode == "read":
        return True
    if mode == "write":
        return False
    try:
        return os.path.exists(resolve(file, frame, version, root))
    except ValueError:
        return False            # if the path can't even be filled in correctly, leave the error to run_cache


def run_cache(mode, file, frame=None, version=None, compress=True, geo=None,
              root=None):
    """The node's execution body. Returns (geo, actual path)."""
    path = resolve(file, frame, version, root)
    if will_read(mode, file, frame, version, root):
        return load(path), path
    if geo is None:
        raise ValueError(
            f"Mode = {mode} needs to write to disk, but the geo input is empty.\n"
            f"  Connect the geometry to cache; to only read from disk, set Mode to read.")
    save(path, geo, compress=compress)
    return geo.copy(), path
