"""
Cook statistics (cookstats.py): what every node reports after it ran, for the time / badges on the nodes, the
middle-button info and the performance pane (web/pcg_cook.js).

  1. every node function carries the wrapper once, transparently (same result, signature visible)
  2. a geometry node reports its id, a positive time, exact counts, bounding box, attributes by class with size and
     type, groups and memory; a COP node its resolution and layers with their channel counts
  3. warnings (Python's warnings module, cookstats.warn) are reported with the node; a failing node reports its error
     and still raises (negative controls: warn() outside a node goes nowhere; a clean node has no warnings)
"""
import inspect
import os
import sys
import types
import warnings

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402

SENT = []


class _Server:
    client_id = "c1"
    last_node_id = None

    def send_sync(self, event, data, sid=None):
        SENT.append((event, data, sid))


import comfyui_pcg  # noqa: E402
from comfyui_pcg import cookstats as CS  # noqa: E402

# after the import: the other modules register HTTP routes on a real server only (cookstats imports it per message)
_srv = types.ModuleType("server")
_srv.PromptServer = types.SimpleNamespace(instance=_Server())
sys.modules["server"] = _srv

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def run(type_, nid, **kw):
    _srv.PromptServer.instance.last_node_id = nid
    c = N[type_]()
    return getattr(c, c.FUNCTION)(**kw)


def defaults(type_):
    out = {}
    for g in ("required", "optional"):
        for k, v in (N[type_].INPUT_TYPES().get(g) or {}).items():
            if isinstance(v, (list, tuple)) and len(v) > 1 and isinstance(v[1], dict) and "default" in v[1]:
                out[k] = v[1]["default"]
            elif isinstance(v, (list, tuple)) and isinstance(v[0], list):
                out[k] = v[0][0]
    return out


print("── 1. Wrapping")
fns = [getattr(c, c.FUNCTION) for c in N.values() if getattr(c, "FUNCTION", None)]
check(f"all {len(fns)} node functions carry the cook wrapper", all(getattr(f, CS._MARK, False) for f in fns))
before = {k: getattr(c, c.FUNCTION) for k, c in N.items()}
CS.attach_cookstats(N)
check("  attaching again wraps nothing twice", all(getattr(c, c.FUNCTION) is before[k] for k, c in N.items()))
sig = inspect.signature(N["PCG_Box"].run)
check("  the signature shows through", "size_x" in sig.parameters or len(sig.parameters) > 3, list(sig.parameters)[:4])

print("── 2. What a node reports")
SENT.clear()
r = run("PCG_Box", "7", **defaults("PCG_Box"))
geo = r["result"][0] if isinstance(r, dict) else r[0]
msg = [d for e, d, s in SENT if e == "pcg.cook"]
check("one pcg.cook message, to this client, with the node id", len(msg) == 1 and msg[0]["node"] == "7"
      and SENT[-1][2] == "c1", SENT[-1:])
m = msg[0]
o = m["outputs"][0]
check("  ok, positive time, exact counts of the result", m["ok"] and m["time"] > 0 and o["kind"] == "geometry"
      and (o["npoints"], o["nprims"], o["nvertices"]) == (geo.npoints, geo.nprims, geo.nvertices),
      (o["npoints"], o["nprims"], o["nvertices"]))
mn, mx = geo.bbox()
check("  bounding box, P a float of size 3 among the point attributes, memory > 0",
      abs(o["bbox"][0][0] - float(mn[0])) < 1e-6 and abs(o["bbox"][1][1] - float(mx[1])) < 1e-6
      and o["attribs"]["point"]["P"] == {"size": 3, "type": "float"} and o["bytes"] > 0, o["attribs"]["point"])
check("  a clean node has no warnings (negative control)", m["warnings"] == [])

from comfyui_pcg.geo.cop.core import CopImage  # noqa: E402
import numpy as np  # noqa: E402
im = CopImage(64, 32)
im.set("C", np.zeros((32, 64, 3), np.float32))
im.set("mask", np.zeros((32, 64), np.float32))
d = CS.describe((im,))[0]
check("a COP image: resolution and layers with channel counts", d == {"kind": "cop", "xres": 64, "yres": 32,
      "layers": {"C": 3, "mask": 1}}, d)

print("── 3. Warnings and errors")


class _Warn:
    FUNCTION = "run"
    RETURN_TYPES = ("INT",)

    def run(self, n):
        warnings.warn(f"careful with {n}")
        CS.warn("and this too")
        return (n,)


class _Fail:
    FUNCTION = "run"
    RETURN_TYPES = ("INT",)

    def run(self):
        raise ValueError("no input geometry")


CS.attach_cookstats({"W": _Warn, "F": _Fail})
SENT.clear()
_srv.PromptServer.instance.last_node_id = "12:5"
_Warn().run(3)
m = SENT[-1][1]
check("warnings.warn and cookstats.warn reach the node's report (subgraph id kept)",
      m["node"] == "12:5" and m["warnings"] == ["and this too", "careful with 3"]
      or m["warnings"] == ["careful with 3", "and this too"], m)
_srv.PromptServer.instance.last_node_id = "9"
raised = False
try:
    _Fail().run()
except ValueError:
    raised = True
m = SENT[-1][1]
check("a failing node reports its error and still raises", raised and not m["ok"]
      and m["error"] == "ValueError: no input geometry" and m["node"] == "9", m)
n0 = len(SENT)
CS.warn("outside a node")
check("  warn() outside a node goes nowhere (negative control)", len(SENT) == n0 and CS._LOCAL["warn"] is None)

kept = CS.last(["7", "9", "nope"])
check("the last report of each node is kept for cached runs (the route /pcg/cookstats)",
      set(kept) == {"7", "9"} and kept["9"]["ok"] is False and kept["7"]["outputs"][0]["npoints"] == 8, list(kept))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
