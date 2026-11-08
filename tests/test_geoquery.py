"""
pcg93: server side of querying geometry from parameter fields (geoquery.py).

  summary    point / prim / vertex counts, bounding box (computed by hand), detail attributes (strings and small vectors go in, more than 16 components do not)
  element    point / prim attributes fetched by index; out of range / no such attribute gives None (the frontend gives 0, like Houdini)
  LRU        evicts by count and by bytes; the entry just inserted is never evicted (even if it alone exceeds the byte limit)
  key        every run gets a new key (two results never mix); unknown key gives 404
  wrapping   nodes that output geometry get an extra pcg_geoq in their ui; nodes that do not are left alone; idempotent; signature is see-through;
             nodes that already return a dict (with ui) are merged, not overwritten; a summary error does not affect the node itself
"""
import inspect
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
from comfyui_pcg import geoquery as Q                   # noqa: E402
from comfyui_pcg.geo import build                       # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def defaults(nid, **over):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    return kw


def call(nid, **over):
    return getattr(M[nid](), M[nid].FUNCTION)(**defaults(nid, **over))


sec("summary")
box = build.box((2, 4, 6), center=(1, 0, -1))
s = Q.summary(box)
check("box 2x4x6, center (1,0,-1): 8 points 6 prims 24 vertices, bounding box computed by hand",
      s["npoints"] == 8 and s["nprims"] == 6 and s["nvertices"] == 24
      and s["bbox"] == [[0, -2, -4], [2, 2, 2]], s)
g = box.copy()
g.set(DETAIL, "scale", np.array([[2.5, 3.0]], np.float32))
g.set_string(DETAIL, "label", ["hello"])
g.set(DETAIL, "big", np.zeros((1, 17), np.float32))
d = Q.summary(g)["detail"]
check("detail: small vector goes in (2 components), string goes in, more than 16 components does not",
      d.get("scale") == [2.5, 3.0] and d.get("label") == "hello" and "big" not in d, d)
check("  empty geometry: bounding box None, all counts 0", Q.summary(Geometry()) == {"npoints": 0, "nprims": 0,
      "nvertices": 0, "bbox": None, "detail": {}}, Q.summary(Geometry()))

sec("element")
P = np.asarray(box.get(POINT, "P"), np.float64)
check("P of point 3: same as in the geometry", Q.element(box, POINT, 3, "P") == P[3].tolist(), Q.element(box, POINT, 3, "P"))
gp = box.copy()
gp.set_string(PRIM, "name", [f"f{i}" for i in range(6)])
check("string attribute name of prim 4", Q.element(gp, PRIM, "4", "name") == "f4")
check("  out of range, negative, no such attribute: None", Q.element(box, POINT, 8, "P") is None
      and Q.element(box, POINT, -1, "P") is None and Q.element(box, POINT, 0, "nope") is None)
try:
    Q.element(box, "vertex", 0, "P")
    check("  cls can only be point / prim", False)
except ValueError as e:
    check("  cls can only be point / prim", "point / prim" in str(e), e)

sec("key / routes")
k1 = Q.remember(box)
k2 = Q.remember(box)
check("a new key every time", k1 != k2 and len(k1) == 16)
st, body = Q.handle(k1, {})
check("default op = summary", st == 200 and body["npoints"] == 8)
st, body = Q.handle(k1, {"op": "elem", "cls": "point", "n": "3", "name": "P"})
check("op=elem: fetch an element", st == 200 and body == {"value": P[3].tolist()}, body)
check("  unknown key: 404", Q.handle("nope", {})[0] == 404)
check("  bad op: 400", Q.handle(k1, {"op": "x"})[0] == 400)
check("  bad cls / n not a number: 400 (does not raise)", Q.handle(k1, {"op": "elem", "cls": "edge"})[0] == 400
      and Q.handle(k1, {"op": "elem", "n": "abc"})[0] == 400)

sec("LRU")
old = (Q.MAX_ITEMS, Q.MAX_BYTES)
Q.MAX_ITEMS = 3
keys = [Q.remember(box) for _ in range(5)]
check("evict by count: only the last 3 remain", [Q.lookup(k) is not None for k in keys] == [False, False, True, True, True])
Q.lookup(keys[2])                                       # use it once, moves it to newest
Q.remember(box)
check("  a used entry moves to newest: inserting one more evicts keys[3], not keys[2]",
      Q.lookup(keys[2]) is not None and Q.lookup(keys[3]) is None)
Q.MAX_ITEMS = 100
nb = Q._nbytes(box)
Q.MAX_BYTES = nb * 2 + 1
ks = [Q.remember(box) for _ in range(4)]
check("evict by bytes: limit a bit over two entries, only 2 kept", sum(Q.lookup(k) is not None for k in ks) == 2
      and Q.lookup(ks[-1]) is not None)
Q.MAX_BYTES = 1
kb = Q.remember(box)
check("  the entry just inserted is not evicted even if it exceeds the limit (otherwise the key would be 404 as soon as it is handed out)", Q.lookup(kb) is not None)
check("  byte counter never goes negative / never misses", Q._BYTES[0] == sum(s for _, s in Q._STORE.values()), Q._BYTES[0])
Q.MAX_ITEMS, Q.MAX_BYTES = old

sec("wrapped nodes")
r = call("PCG_Box", size_x=2.0) if "size_x" in defaults("PCG_Box") else call("PCG_Box")
d = r["ui"]["pcg_geoq"][0]
check("node that outputs geometry: ui has pcg_geoq (key + summary), result unchanged", isinstance(r, dict)
      and isinstance(r["result"][0], Geometry) and d["summary"]["npoints"] == r["result"][0].npoints
      and Q.lookup(d["key"]) is r["result"][0], d)
check("  coexists with other ui (pcg_attribs), does not overwrite", "pcg_attribs" in r["ui"] or "pcg_groups" in r["ui"], list(r["ui"]))
nogeo = [k for k, c in M.items() if "GEOMETRY" not in [str(t) for t in getattr(c, "RETURN_TYPES", ())]]
check("  nodes that do not output geometry (Value etc.) have no pcg_geoq", "PCG_Value" in nogeo
      and "pcg_geoq" not in str(call("PCG_Value")))
fn = getattr(M["PCG_Box"], M["PCG_Box"].FUNCTION)
check("  wrapping is see-through (inspect.signature is the original function's)", "self" in str(inspect.signature(fn))
      and "kwargs" not in str(inspect.signature(fn)))


class Fake:
    FUNCTION = "run"
    RETURN_TYPES = ("GEOMETRY",)

    def run(self, mode="tuple"):
        g = build.box((1, 1, 1))
        if mode == "dict":
            return {"ui": {"text": ["hi"]}, "result": (g,)}
        return (g,)


Q.attach_geo_query({"F": Fake})
Q.attach_geo_query({"F": Fake})
out = Fake().run(mode="dict")
check("idempotent: wrapping twice gives one layer; a node that returned a dict with ui gets its ui merged", out["ui"]["text"] == ["hi"]
      and len(out["ui"]["pcg_geoq"]) == 1 and getattr(Fake.run, "_pcg_geo_query", False), out["ui"].keys())
orig = Q.summary
Q.summary = lambda g: (_ for _ in ()).throw(RuntimeError("summary broken"))
out = Fake().run()
Q.summary = orig
check("summary error: node still returns its original result, without pcg_geoq", isinstance(out, tuple) and isinstance(out[0], Geometry))
gl = build.box((1, 1, 1))
check("finding the geometry: tuple / list (OUTPUT_IS_LIST nodes give a list) / nested all find the first one",
      Q._first_geo((1, [None, gl])) is gl and Q._first_geo([gl]) is gl and Q._first_geo(("x", 2)) is None)
check("routes: registration is silently skipped outside ComfyUI (does not raise)", Q._ROUTES_OK in (True, False))

from comfyui_pcg.groups_report import attach_group_reporting   # noqa: E402
from comfyui_pcg.coppreview import attach_cop_preview          # noqa: E402
before = {k: getattr(c, c.FUNCTION) for k, c in M.items()}
for f in (Q.attach_geo_query, attach_group_reporting, attach_cop_preview):
    f(M)
changed = [k for k, c in M.items() if getattr(c, c.FUNCTION) is not before[k]]
check("the three wrappers (group names / geometry query / COP thumbnail) wrapping the real node table once more: nothing changes"
      " (the outer wrapper carries the inner markers out; previously the outer wrapper hid the markers of COP nodes, so wrapping again gave two layers)", not changed,
      f"{len(changed)} changed")

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
