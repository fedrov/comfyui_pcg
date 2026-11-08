"""
Server side of geometry queries in parameter fields (npoints / bbox / centroid / point / prim / detail).

Houdini's `npoints("../box1")` cooks on demand: whichever node is asked gets cooked. ComfyUI submits the whole graph
and only has results after it runs; the frontend cannot get the "current" geometry, so a field reads **the result of that node's last run**
(for the frontend half see "geometry queries in fields" in web/pcg_params.js).

The approach wraps each node's execution function (same pattern as groups_report.py): if the output has a Geometry,

  - generate a key and put the geometry into a bounded LRU (limited both by count and by bytes)
  - send a **summary** in ui (point / primitive / vertex counts, bounding box, detail attributes) plus the key -- ComfyUI sends an executed
    message for any node that returns ui, and the frontend records the key on that node
  - queries for specific elements (`point("../box1", 3, "P", 1)`) make the frontend GET /pcg/geoq/<key> with the key

**Why a key and not the node id**: a node's execution function cannot get its own id unless a hidden UNIQUE_ID
is added to INPUT_TYPES -- and as soon as ComfyUI sees UNIQUE_ID it folds the node id into the cache key, so every PCG node's
cache is invalidated once after the upgrade, and two nodes with identical parameters no longer share results. The key does not touch the cache key.

**Extra memory held by the LRU**: ComfyUI's own cache already keeps every node's output for the current graph; most of the LRU is the same
objects and takes no extra memory. The extra is only "replaced old results", evicted by a byte cap (default 512 MB) and a count cap (256).
Asking for an evicted key gives 404, and the frontend says "run again".
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict

import numpy as np

from .geo import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string

_MARK = "_pcg_geo_query"
MAX_ITEMS = 256
MAX_BYTES = 512 << 20
DETAIL_MAX_COMPS = 16          # detail attributes with more components than this are left out of the summary (the summary must stay small)

_LOCK = threading.Lock()
_STORE: "OrderedDict[str, tuple[Geometry, int]]" = OrderedDict()
_BYTES = [0]


def _nbytes(geo):
    n = 0
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for a in geo.attribs.get(cls, {}).values():
            n += getattr(a, "nbytes", 0)
    return n + getattr(geo.vertex_point, "nbytes", 0)


def remember(geo):
    """Put geometry into the LRU and return the key."""
    key = uuid.uuid4().hex[:16]
    size = _nbytes(geo)
    with _LOCK:
        _STORE[key] = (geo, size)
        _BYTES[0] += size
        while _STORE and (len(_STORE) > MAX_ITEMS or _BYTES[0] > MAX_BYTES) \
                and next(iter(_STORE)) != key:
            _, (_, s) = _STORE.popitem(last=False)
            _BYTES[0] -= s
    return key


def lookup(key):
    with _LOCK:
        item = _STORE.get(str(key))
        if item is not None:
            _STORE.move_to_end(str(key))
    return item[0] if item else None


def _py(v):
    """One numpy row -> something JSON can hold (string attributes give strings)."""
    a = np.asarray(v)
    if a.dtype.kind in "OUS":
        return str(a.reshape(-1)[0]) if a.size else ""
    return [float(x) for x in a.reshape(-1)]


def summary(geo):
    """Summary: point / primitive / vertex counts, bounding box, detail attributes (small ones)."""
    out = {"npoints": int(geo.npoints), "nprims": int(geo.nprims),
           "nvertices": int(geo.nvertices), "bbox": None, "detail": {}}
    if geo.npoints:
        mn, mx = geo.bbox()
        out["bbox"] = [[float(x) for x in mn], [float(x) for x in mx]]
    for name, a in geo.attribs.get(DETAIL, {}).items():
        if len(a) and (is_string(a) or a.shape[1] <= DETAIL_MAX_COMPS):
            out["detail"][name] = _py(a[0])
    return out


def element(geo, cls, n, name):
    """One attribute of one element. Missing attribute / out of range gives None (the frontend then gives 0 / empty string like Houdini)."""
    if cls not in (POINT, PRIM):
        raise ValueError(f"cls must be point / prim, got {cls}")
    a = geo.get(cls, name)
    n = int(n)
    if a is None or not 0 <= n < len(a):
        return None
    return _py(a[n])


def _first_geo(value):
    if isinstance(value, Geometry):
        return value
    if isinstance(value, (tuple, list)):
        for v in value:
            g = _first_geo(v)
            if g is not None:
                return g
    return None


def attach_geo_query(mappings):
    """Wrap each node's execution function: record geometry in the output and send summary and key in ui. Idempotent."""
    for cls in mappings.values():
        fn_name = getattr(cls, "FUNCTION", None)
        fn = getattr(cls, fn_name, None) if fn_name else None
        if fn is None or getattr(fn, _MARK, False):
            continue

        def make(orig):
            def wrapped(self, *args, **kwargs):
                out = orig(self, *args, **kwargs)
                res = out.get("result") if isinstance(out, dict) else out
                g = _first_geo(res)
                if g is None:
                    return out
                try:
                    payload = {"pcg_geoq": [{"key": remember(g), "summary": summary(g)}]}
                except Exception:              # a summary failure must not break the node itself
                    return out
                if isinstance(out, dict):
                    return {**out, "ui": {**(out.get("ui") or {}), **payload}}
                return {"ui": payload, "result": out}
            # Carry out the markers of the inner layers (groups_report etc.): they use markers to tell "already wrapped",
            # and if this layer hid them, calling attach again would wrap twice, and the test checking the production setup could not see it
            wrapped.__dict__.update(getattr(orig, "__dict__", {}))
            setattr(wrapped, _MARK, True)
            wrapped.__wrapped__ = orig            # let inspect.signature see through this layer (see groups_report.py)
            wrapped.__name__ = getattr(orig, "__name__", "run")
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            return wrapped

        setattr(cls, fn_name, make(fn))


# ------------------------------------------------------------ HTTP routes
def handle(key, query):
    """Pure-function part of the route (called directly by unit tests): -> (status code, JSON)."""
    geo = lookup(key)
    if geo is None:
        return 404, {"error": "no such key (the server restarted, or it was evicted by newer results)"}
    op = query.get("op", "summary")
    try:
        if op == "summary":
            return 200, summary(geo)
        if op == "elem":
            return 200, {"value": element(geo, query.get("cls", POINT), query.get("n", 0),
                                          query.get("name", "P"))}
        return 400, {"error": f"op must be summary / elem, got {op}"}
    except (ValueError, TypeError) as e:
        return 400, {"error": str(e)}


def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return False                      # silently skip when unit-testing outside ComfyUI

    @PromptServer.instance.routes.get("/pcg/geoq/{key}")
    async def _pcg_geoq(request):
        status, body = handle(request.match_info["key"], dict(request.query))
        return web.json_response(body, status=status, headers={"Cache-Control": "no-store"})
    return True


_ROUTES_OK = _register_routes()
