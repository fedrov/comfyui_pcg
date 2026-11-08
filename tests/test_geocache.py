"""
On-disk geometry cache -- full .npz round trip.

The core criterion of this suite is just one, but it has to be **very strict**:

    the round trip is **bit-for-bit** identical.

"Looks the same" is not enough. The easiest mistake in a round trip is **silent degradation**: dtype quietly dropping from float64
back to float32, string attribute width changing, edge group point pairs being treated as edge indices, prim_data being
skipped. None of these raise; they only show up when precision or geometry goes wrong downstream, by which time it is far from the real cause.

So the criterion is: serialize every component of the geometry (attribute tables of all four classes including dtype and shape,
the three kinds of groups, edge groups, the four topology arrays, prim_data, point count) into bytes and compare as dicts,
listing every place that differs.

Three easy-to-miss things are also pinned down separately:
  · **no pickle** (readable with `allow_pickle=False`), since cache files travel
    with the project and get copied around
  · writing is **atomic** (write .part first, then rename), otherwise an interruption leaves a truncated file,
    and the next read finds a broken file instead of "no file" -- the latter can be recomputed automatically
  · the read mode **really does not touch upstream** (via lazy inputs); that is the whole reason the cache saves time
"""
import os
import shutil
import tempfile
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import json                                             # noqa: E402
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX,   # noqa: E402
                                  PRIM, DETAIL)
from comfyui_pcg.geo import (geocache as GC, build,      # noqa: E402
                             attribops as AO, volume as VOL)

# a **new** temp directory every run. It used to be hard-coded to /tmp/pcg_geocache_test: two regression runs in parallel (sandbox +
# device mirror) rmtree'd each other's files, which happened once in pcg61; also on Windows
# "/tmp/…" lands at the root of the drive
TMP = tempfile.mkdtemp(prefix="pcg_geocache_")
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn(); check(name, False, "no error raised")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:90]}")


def snap(g):
    """
    A **full** fingerprint of the geometry. A change in any component shows up.

    dtype and shape are deliberately included -- comparing only tobytes(),
    a float32 (8,3) and a float64 (4,3) could collide on the same bytes.
    """
    out = {"npoints": g.npoints, "nprims": g.nprims,
           "nvertices": g.nvertices}
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for n, a in sorted(g.attribs[cls].items()):
            a = np.asarray(a)
            out[("attrib", cls, n)] = (a.dtype.str, a.shape, a.tobytes())
    for cls in (POINT, VERTEX, PRIM):
        for n, m in sorted(g.groups[cls].items()):
            m = np.asarray(m)
            out[("group", cls, n)] = (m.dtype.str, m.shape, m.tobytes())
    for n, e in sorted(g.edge_groups.items()):
        e = np.asarray(e)
        out[("edgegroup", n)] = (e.dtype.str, e.shape, e.tobytes())
    for pi in sorted(g.prim_data):
        for n, v in sorted(g.prim_data[pi].items()):
            v = np.asarray(v)
            out[("pdata", pi, n)] = (v.dtype.str, v.shape, v.tobytes())
    for n in ("vertex_point", "prim_offset", "prim_closed", "prim_type"):
        a = np.asarray(getattr(g, n))
        out[("topo", n)] = (a.dtype.str, a.shape, a.tobytes())
    return out


def diff(a, b):
    return sorted(str(k) for k in set(a) | set(b) if a.get(k) != b.get(k))


def rich():
    """A geometry using as many kinds of Geometry components as possible."""
    g = build.box(size=(2, 2, 2), divisions=(3, 3, 3))
    g = AO.create(g, name="w", cls="point", expression="@P.x")
    g = AO.create(g, name="v3", cls="point", size=3, value=(1, 2, 3, 0))
    g = AO.create(g, name="pf", cls="prim", value=(0.5, 0, 0, 0))
    g = AO.create(g, name="vu", cls="vertex", value=(0.25, 0, 0, 0))
    # float64: the first version stored all floats as float32; this pins down that pitfall
    g = AO.cast(AO.create(g, name="d64", cls="point", expression="@P.z"),
                names="d64", cls="point", to_type="float64")
    # integer attribute
    g = g.copy()
    g.set(PRIM, "cls", np.arange(g.nprims, dtype=np.int32).reshape(-1, 1))
    # string attribute: the <U width must be preserved too
    g.set_string(PRIM, "name", np.array([f"face_{i}" for i in range(g.nprims)]))
    g.set_string(POINT, "tag", np.array(["a" * (i % 5 + 1)
                                         for i in range(g.npoints)]))
    # detail
    g.set(DETAIL, "meta", np.array([[3.5, -1.0]]))
    g.set_string(DETAIL, "who", np.array(["pcg"]))
    # three kinds of groups
    g.set_group(POINT, "half", np.arange(g.npoints) < g.npoints // 2)
    g.set_group(VERTEX, "vsome", np.arange(g.nvertices) % 3 == 0)
    g.set_group(PRIM, "few", np.arange(g.nprims) < 3)
    # edge groups (stored as point pairs, not edge indices)
    g.set_edge_group("seam", np.array([[0, 1], [1, 2], [3, 5]], np.int32))
    g.set_edge_group("empty", np.zeros((0, 2), np.int32))
    # prim_data: variable-length side channel
    g.set_pdata(0, "knots_u", np.linspace(0, 1, 7))
    g.set_pdata(0, "knots_v", np.linspace(0, 1, 5).astype(np.float32))
    g.set_pdata(2, "voxels", np.arange(24, dtype=np.float32).reshape(2, 3, 4))
    return g


def _topo_only():
    g = Geometry()
    g._resize_points(4)
    g.set_topology(np.array([0, 1, 2, 0, 2, 3], np.int32),
                   np.array([0, 3, 6], np.int32),
                   np.array([True, True]))
    return g


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)

# ══════════════════════════════════════════════════════════════ round trip
print("═" * 28, "bit-for-bit round trip")

G = rich()
P1 = os.path.join(TMP, "rich.npz")
GC.save(P1, G)
H = GC.load(P1)
_d = diff(snap(G), snap(H))
check("a geometry using all components, saved and read back, is **bit-identical**",
      not _d, _d or f"file {os.path.getsize(P1)} bytes")
check("  float64 attributes did not silently drop back to float32",
      np.asarray(H.get(POINT, "d64")).dtype == np.float64,
      np.asarray(H.get(POINT, "d64")).dtype)
check("  dtype width of string attributes preserved",
      np.asarray(H.get(PRIM, "name")).dtype
      == np.asarray(G.get(PRIM, "name")).dtype,
      (str(np.asarray(H.get(PRIM, "name")).dtype),
       str(np.asarray(G.get(PRIM, "name")).dtype)))
check("  integer attributes are still integers",
      np.asarray(H.get(PRIM, "cls")).dtype == np.int32)
check("  all three kinds of groups present", "half" in H.groups[POINT]
      and "vsome" in H.groups[VERTEX] and "few" in H.groups[PRIM])
check("  edge groups all present, **including empty edge groups** (if lost, downstream lookups by name raise KeyError)",
      set(H.edge_groups) == {"seam", "empty"}, sorted(H.edge_groups))
check("  prim_data attached to the right prim, with the right dtype",
      sorted(H.prim_data) == [0, 2]
      and sorted(H.prim_data[0]) == ["knots_u", "knots_v"]
      and np.asarray(H.prim_data[0]["knots_v"]).dtype == np.float32
      and np.asarray(H.prim_data[2]["voxels"]).shape == (2, 3, 4),
      {k: sorted(v) for k, v in H.prim_data.items()})
check("  detail attributes (including strings) present too",
      np.allclose(np.asarray(H.get(DETAIL, "meta")), [[3.5, -1.0]])
      and str(np.asarray(H.get(DETAIL, "who")).ravel()[0]) == "pcg")
check("  arrays read back are **read-only** (consistent with geometry produced elsewhere)",
      not np.asarray(H.get(POINT, "P")).flags.writeable
      and not np.asarray(H.prim_data[0]["knots_u"]).flags.writeable)
check("  topology cache not saved along (it is derived, rebuilt automatically on read)",
      GC.dumps(G)[0].get("topo_cache") is None)

# save and read back once more, still the same -- the round trip is idempotent
GC.save(P1, H)
check("round trip is idempotent: read back, save again, read again, still bit-identical",
      not diff(snap(H), snap(GC.load(P1))))

print("═" * 28, "geometry edge cases")

CASES = {
    "empty geometry": Geometry(),
    "pure point cloud (no primitives)": Geometry.from_points(
        np.arange(30, dtype=np.float32).reshape(10, 3)),
    # topology-only geometry with primitives and vertices but **no P attribute**. Valid, and the point count can only be
    # stored via npoints -- deriving it from the row count of P would give 0 here
    "topology only, no P": _topo_only(),
    "open polyline": build.line((0, 0, 0), (1, 1, 0), length=3.0, points=5),
    "sphere (bigger)": build.sphere(rows=24, cols=48),
    "volume prim (prim_data is a 3D array)": VOL.volume_box(
        (-1, -1, -1), (1, 1, 1), 0.5) if hasattr(VOL, "volume_box") else None,
}
for _nm, _g in CASES.items():
    if _g is None:
        continue
    _p = os.path.join(TMP, "c.npz")
    GC.save(_p, _g)
    _dd = diff(snap(_g), snap(GC.load(_p)))
    check(f"{_nm}: round trip bit-identical", not _dd, _dd or f"{_g.npoints} points")

# point count cannot be derived from P -- topology-only geometry without P is valid too
_np_only = Geometry()
_np_only._resize_points(7)
_p = os.path.join(TMP, "nop.npz")
GC.save(_p, _np_only)
check("geometry without a P attribute also stores the point count correctly (cannot be derived from the row count of P)",
      GC.load(_p).npoints == 7, GC.load(_p).npoints)

print("═" * 28, "no pickle / atomic write")

with np.load(P1, allow_pickle=False) as _z:
    check("file readable with allow_pickle=False"
          " (the cache travels with the project and should not be able to execute arbitrary code)",
          GC.MANIFEST in _z.files, len(_z.files))
    _man = json.loads(str(_z[GC.MANIFEST]))
check("manifest has magic and version number", _man.get("magic") == GC.MAGIC
      and _man.get("version") == GC.VERSION,
      (_man.get("magic"), _man.get("version")))
check("manifest records the dtype of every array (otherwise reading back can only guess)",
      all("dtype" in r for r in _man["attribs"]))

# non-array in prim_data -> explicit error, not silently dropped
_bad = build.box()
_bad.set_pdata(0, "weird", {"not": "an array"})
err("non-numpy object in prim_data -> **explicit error**"
    " (if silently dropped, the geometry read back would be missing things)",
    lambda: GC.save(os.path.join(TMP, "bad.npz"), _bad), "not a numpy array")

check("writing is atomic: no .part leftover after writing",
      not any(f.endswith(".part") or f.endswith(".part.npz")
              for f in os.listdir(TMP)), os.listdir(TMP)[:6])
# a truncated file must give an actionable error, not an incomprehensible zip error
_half = os.path.join(TMP, "half.npz")
with open(_half, "wb") as f:
    f.write(b"PK\x03\x04" + "this is not a complete npz".encode("utf-8"))
err("truncated / corrupted file: the error says what to do (delete it to have it recomputed)",
    lambda: GC.load(_half), "Delete it")
# ordinary npz (no manifest)
_plain = os.path.join(TMP, "plain.npz")
np.savez(_plain, a=np.arange(3))
err("ordinary npz (not a PCG cache) -> says it is not a cache file",
    lambda: GC.load(_plain), "this isn't a PCG geometry cache")
err("file does not exist -> FileNotFoundError, with a hint about auto mode",
    lambda: GC.load(os.path.join(TMP, "nope.npz")), "auto",
    FileNotFoundError)
# future version
_man2, _arr2 = GC.dumps(build.box())
_man2["version"] = GC.VERSION + 5
err("cache written by a newer version -> says the plugin is too old",
    lambda: GC.loads(_man2, lambda k: _arr2[k]), "the plugin is older than the cache")
_man3, _arr3 = GC.dumps(build.box())
_man3["magic"] = "something else"
err("wrong magic -> rejected outright", lambda: GC.loads(_man3, lambda k: _arr3[k]),
    "Not a PCG geometry cache")

print("═" * 28, "path expansion / the three Modes")

check("$F replaced by the frame number", GC.expand("c_$F.npz", frame=12) == "c_12.npz",
      GC.expand("c_$F.npz", frame=12))
check("$F4 zero-padded to 4 digits (without padding the sort order in a file manager is a mess)",
      GC.expand("c_$F4.npz", frame=7) == "c_0007.npz",
      GC.expand("c_$F4.npz", frame=7))
check("  $F2 / $F6 also padded by digit count",
      GC.expand("$F2", frame=5) == "05" and GC.expand("$F6", frame=5)
      == "000005")
check("$V replaced by the version number", GC.expand("c_v$V.npz", version=3) == "c_v3.npz")
check("  both together", GC.expand("c_$F4_v$V.npz", frame=7, version=2)
      == "c_0007_v2.npz")
check("  negative frame numbers recognized too", GC.expand("c_$F.npz", frame=-3) == "c_-3.npz")
check("  path without $ returned unchanged",
      GC.expand("plain/name.npz", frame=1, version=1) == "plain/name.npz")
check("resolve appends the .npz suffix automatically",
      GC.resolve("d", root=TMP).endswith("d.npz"))
check("  absolute paths are not put under the output directory",
      GC.resolve(os.path.join(TMP, "abs.npz"), root="/nowhere")
      == os.path.join(TMP, "abs.npz"))
err("empty File -> error with an example",
    lambda: GC.resolve("   ", root=TMP), "enter a file name")

MP = os.path.join(TMP, "mode")
shutil.rmtree(MP, ignore_errors=True)
G2 = build.box(size=(3, 3, 3))
check("auto + file missing -> decides to **write**",
      GC.will_read("auto", "m.npz", root=MP) is False)
_g, _pth = GC.run_cache("auto", "m.npz", geo=G2, root=MP)
check("  after writing the file exists, and the input geometry is passed through",
      os.path.exists(_pth) and _g.npoints == G2.npoints)
check("auto + file present -> decides to **read**",
      GC.will_read("auto", "m.npz", root=MP) is True)
_g2, _ = GC.run_cache("auto", "m.npz", geo=None, root=MP)
check("  when reading, geo = None still gives a result (this is exactly the mode that saves compute)",
      not diff(snap(G2), snap(_g2)))
check("write always decides to write, even if the file already exists",
      GC.will_read("write", "m.npz", root=MP) is False)
check("read always decides to read, even if the file is missing"
      " (so a missing file raises, instead of quietly computing upstream)",
      GC.will_read("read", "nope.npz", root=MP) is True)
err("read + file missing -> error", lambda: GC.run_cache("read", "nope.npz",
                                                  root=MP), "auto",
    FileNotFoundError)
err("write but geo not connected -> error that explains both options",
    lambda: GC.run_cache("write", "w.npz", geo=None, root=MP), "the geo input is empty")
err("bad Mode lists the options",
    lambda: GC.will_read("oops", "m.npz", root=MP), "Mode must be one of")
_ncp = os.path.join(MP, "nc.npz")
GC.save(_ncp, G2, compress=False)
check("compress=False also round-trips (bit for bit)",
      not diff(snap(G2), snap(GC.load(_ncp))),
      diff(snap(G2), snap(GC.load(_ncp))) or f"{os.path.getsize(_ncp)} bytes")
check("  compressed file is smaller (otherwise the compress switch is pointless)",
      os.path.getsize(os.path.join(MP, "m.npz"))
      < os.path.getsize(os.path.join(MP, "nc.npz")),
      (os.path.getsize(os.path.join(MP, "m.npz")),
       os.path.getsize(os.path.join(MP, "nc.npz"))))
check("directories are created automatically (a user entering pcg_cache/xxx.npz does not need to create it first)",
      os.path.isdir(os.path.dirname(
          GC.save(os.path.join(MP, "deep/er/x.npz"), G2))))

print("═" * 28, "lazy inputs: reading from disk **really does not touch upstream**")

# this is the node's core promise. If "reading from disk" alone does not stop upstream from recomputing, the cache is useless --
# it just writes a file for nothing. So use a fake upstream that keeps count and really run a graph to verify.
import comfyui_pcg as _PKG                              # noqa: E402

CACHE_CLS = _PKG.NODE_CLASS_MAPPINGS["PCG_FileCache"]


class _Spy:
    """An upstream that keeps count: records one entry every time it is executed."""
    ran = []

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"n": ("INT", {"default": 6})}}
    RETURN_TYPES = ("GEOMETRY",)
    FUNCTION = "run"

    def run(self, n):
        _Spy.ran.append(n)
        return (build.box(size=(n, n, n)),)


LP = os.path.join(TMP, "lazy")
shutil.rmtree(LP, ignore_errors=True)
os.makedirs(LP, exist_ok=True)
_abs = os.path.join(LP, "cache.npz")


def graph(mode):
    return {"1": {"class_type": "Spy", "inputs": {"n": 6}},
            "2": {"class_type": "PCG_FileCache",
                  "inputs": {"mode": mode, "file": _abs, "frame": 0,
                             "version": 1, "compress": True, "reload": 0,
                             "geo": ["1", 0]}}}


CLASSES = {"Spy": _Spy, "PCG_FileCache": CACHE_CLS}

_Spy.ran = []
_r = fakecomfy.Executor(graph("auto"), CLASSES).run("2")
check("first auto (file missing): upstream ran once, geometry written to disk",
      len(_Spy.ran) == 1 and os.path.exists(_abs), _Spy.ran)
check("  the output geo matches what upstream computed", _r[0].npoints == 8)
check("  the second output is the actual path", _r[1] == _abs, _r[1])

_Spy.ran = []
_r2 = fakecomfy.Executor(graph("auto"), CLASSES).run("2")
check("second auto (file now present): upstream **did not run once** -- that is the whole point of the cache",
      _Spy.ran == [], _Spy.ran)
check("  but the geometry is still correct (read back from disk)",
      not diff(snap(_r[0]), snap(_r2[0])))

_Spy.ran = []
fakecomfy.Executor(graph("read"), CLASSES).run("2")
check("read mode: upstream did not run once either", _Spy.ran == [], _Spy.ran)

_Spy.ran = []
fakecomfy.Executor(graph("write"), CLASSES).run("2")
check("write mode: upstream **must** run (needs the new geometry to overwrite)",
      len(_Spy.ran) == 1, _Spy.ran)

check("check_lazy_status and run use **the same** decision function -- "
      "if the two disagree it would write to disk with geo=None and raise an error unrelated to the real cause",
      CACHE_CLS().check_lazy_status(
          "read", _abs, 0, 1, True, 0) == []
      and CACHE_CLS().check_lazy_status(
          "write", _abs, 0, 1, True, 0) == ["geo"])
check("  the geo input declares lazy (otherwise upstream gets computed anyway)",
      CACHE_CLS.INPUT_TYPES()["optional"]["geo"][1].get("lazy") is True,
      CACHE_CLS.INPUT_TYPES()["optional"]["geo"])

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
