"""
Cook statistics (Houdini's node info and Performance Monitor): every PCG node reports, after it ran,

  - how long it took (its own execution function, wall clock)
  - what it made: geometry -> point / primitive / vertex counts, bounding box, attributes by class (name, size,
    type), memory; a COP image -> resolution and layers (channels each)
  - warnings it raised (Python's warnings module, or cookstats.warn() from node code), or the error it failed with

as a websocket message "pcg.cook" {node, ...}. web/pcg_cook.js draws the time and a warning / error badge on the
node, shows the full report while the middle button is held on a node, and lists a run in the performance pane.

Why a message and not the node's ui output (as geoquery does): ui is cached with the outputs and only sent for nodes
that return it, and an error has no output at all. The node id comes from ComfyUI's execution context (or the
server's last_node_id on older versions); inside a subgraph it is the execution id ("12:5").
"""
from __future__ import annotations

import time
import warnings as _warnings

import numpy as np

_MARK = "_pcg_cookstats"
MAX_ATTRIBS = 64                 # per class, so a message stays small
_LOCAL = {"warn": None}          # warnings collected for the node running now


def warn(message):
    """Called from node code: a warning shown on the node (yellow badge) and in its info."""
    lst = _LOCAL["warn"]
    if lst is not None:
        lst.append(str(message))


def _node_id():
    try:
        from comfy_execution.utils import get_executing_context
        c = get_executing_context()
        if c is not None and getattr(c, "node_id", None) is not None:
            return str(c.node_id)
    except Exception:
        pass
    try:
        from server import PromptServer
        v = PromptServer.instance.last_node_id
        return None if v is None else str(v)
    except Exception:
        return None


_LAST = {}                       # node id -> its last report (a cached node is not run: the frontend asks here)
MAX_KEPT = 4096


def last(ids):
    """The last reports of these node ids (those known)."""
    return {str(i): _LAST[str(i)] for i in ids if str(i) in _LAST}


def _send(payload):
    if payload.get("node") is not None:
        _LAST.pop(payload["node"], None)
        _LAST[payload["node"]] = payload
        while len(_LAST) > MAX_KEPT:
            _LAST.pop(next(iter(_LAST)))
    try:
        from server import PromptServer
        s = PromptServer.instance
        s.send_sync("pcg.cook", payload, getattr(s, "client_id", None))
        return True
    except Exception:
        return False


def _attr_info(a):
    a = np.asarray(a)
    kind = "string" if a.dtype.kind in "OUS" else ("int" if a.dtype.kind in "iub" else "float")
    size = 1 if a.ndim < 2 else int(a.shape[1])
    return {"size": size, "type": kind}


def describe(value):
    """What a node's outputs are, for the info popup (geometry and COP images; other outputs by type name)."""
    from .geo import Geometry, POINT, VERTEX, PRIM, DETAIL
    try:
        from .geo.cop.core import CopImage
    except Exception:                                       # pragma: no cover
        CopImage = ()
    from .geoquery import _nbytes
    outs = []
    for v in (value if isinstance(value, (tuple, list)) else (value,)):
        if isinstance(v, Geometry):
            d = {"kind": "geometry", "npoints": int(v.npoints), "nprims": int(v.nprims),
                 "nvertices": int(v.nvertices), "bytes": int(_nbytes(v)), "bbox": None, "attribs": {}}
            if v.npoints:
                mn, mx = v.bbox()
                d["bbox"] = [[round(float(x), 6) for x in mn], [round(float(x), 6) for x in mx]]
            for cls, nm in ((POINT, "point"), (VERTEX, "vertex"), (PRIM, "prim"), (DETAIL, "detail")):
                items = list(v.attribs.get(cls, {}).items())[:MAX_ATTRIBS]
                d["attribs"][nm] = {k: _attr_info(a) for k, a in items}
            try:
                d["groups"] = {nm: sorted(v.groups.get(cls, {}).keys())[:MAX_ATTRIBS]
                               for cls, nm in ((POINT, "point"), (PRIM, "prim"))} if hasattr(v, "groups") else {}
            except Exception:
                d["groups"] = {}
            outs.append(d)
        elif CopImage and isinstance(v, CopImage):
            layers = {}
            for k in list(v.names)[:MAX_ATTRIBS]:
                a = v.get(k)
                shp = tuple(getattr(a, "shape", ()))
                layers[k] = int(shp[2]) if len(shp) > 2 else 1
            outs.append({"kind": "cop", "xres": int(v.xres), "yres": int(v.yres), "layers": layers})
        elif v is not None:
            outs.append({"kind": type(v).__name__})
    return outs


def attach_cookstats(mappings):
    """Wrap each node's execution function (idempotent): time it, describe its result, send pcg.cook."""
    for cls in mappings.values():
        fn_name = getattr(cls, "FUNCTION", None)
        fn = getattr(cls, fn_name, None) if fn_name else None
        if fn is None or getattr(fn, _MARK, False):
            continue

        def make(orig):
            def wrapped(self, *args, **kwargs):
                nid = _node_id()
                outer = _LOCAL["warn"]
                mine = _LOCAL["warn"] = []
                t0 = time.perf_counter()
                try:
                    with _warnings.catch_warnings(record=True) as caught:
                        _warnings.simplefilter("always")
                        out = orig(self, *args, **kwargs)
                except Exception as e:
                    _send({"node": nid, "ok": False, "time": time.perf_counter() - t0,
                           "error": f"{type(e).__name__}: {e}"[:2000], "warnings": mine[:20]})
                    raise
                finally:
                    _LOCAL["warn"] = outer
                dt = time.perf_counter() - t0
                for w in caught:
                    if not issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning)):
                        mine.append(str(w.message))
                try:
                    res = out.get("result") if isinstance(out, dict) else out
                    outs = describe(res)
                except Exception:                  # describing must never break the node itself
                    outs = []
                _send({"node": nid, "ok": True, "time": dt, "outputs": outs, "warnings": mine[:20]})
                return out
            wrapped.__dict__.update(getattr(orig, "__dict__", {}))
            setattr(wrapped, _MARK, True)
            wrapped.__wrapped__ = orig
            wrapped.__name__ = getattr(orig, "__name__", "run")
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            return wrapped
        setattr(cls, fn_name, make(fn))


def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return False                      # outside ComfyUI (unit tests)

    @PromptServer.instance.routes.get("/pcg/cookstats")
    async def _pcg_cookstats(request):
        ids = [x for x in str(request.query.get("ids", "")).split(",") if x][:2000]
        return web.json_response(last(ids), headers={"Cache-Control": "no-store"})
    return True


_ROUTES_OK = _register_routes()
