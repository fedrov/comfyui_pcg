"""
Server side of the Geometry Spreadsheet node.

Mirrors Houdini's Geometry Spreadsheet: one tab per attribute class (four), one table per tab,
rows are elements, columns are attribute components, plus a few pseudo-columns (pt/prim for vertex, nvtx for prim).

The first page goes straight into {"ui": ...}. pcg122: the geometry is also kept (a reference -- geometry is never
mutated in place) in a small per-node cache, and GET /pcg/sheet/{node_id}?cls=point&start=0&rows=64 serves any other
page as JSON, so the frontend pages / jumps through millions of rows without re-running the graph.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np

from .geo import POINT, VERTEX, PRIM, DETAIL, is_string
from .geo.core import PRIM_TYPE_NAMES

CLASS_ORDER = (POINT, VERTEX, PRIM, DETAIL)
CACHE_NODES = 16                       # spreadsheets kept for paging (least recently used dropped)
MAX_PAGE = 5000

_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_LOCK = threading.Lock()
_REV = [0]


def remember(node_id, geo):
    """Keep geo for paging; returns its revision number."""
    with _LOCK:
        _REV[0] += 1
        _CACHE[str(node_id)] = (_REV[0], geo)
        _CACHE.move_to_end(str(node_id))
        while len(_CACHE) > CACHE_NODES:
            _CACHE.popitem(last=False)
        return _REV[0]


def page(node_id, cls="point", start=0, rows=64):
    """One page of a cached spreadsheet: {"rev", "cls", "table"}; None when the node has nothing cached."""
    if cls not in CLASS_ORDER:
        raise ValueError(f"class must be one of {CLASS_ORDER}")
    with _LOCK:
        item = _CACHE.get(str(node_id))
        if item is not None:
            _CACHE.move_to_end(str(node_id))
    if item is None:
        return None
    rev, geo = item
    rows = max(1, min(int(rows), MAX_PAGE))
    return {"rev": rev, "cls": cls, "table": _table(geo, cls, rows, max(0, int(start)))}


def _table(geo, cls, max_rows, start):
    """Flatten one attribute class into {column definitions, row data}."""
    n = geo.count(cls)
    start = max(0, min(int(start), max(0, n - 1)))
    take = int(min(max_rows, max(0, n - start)))

    cols, mats = [], []

    # Pseudo-columns: Houdini's spreadsheet also puts this topology info right in the table
    if cls == VERTEX and n:
        cols += [{"name": "pt", "size": 1, "kind": "i", "meta": True},
                 {"name": "prim", "size": 1, "kind": "i", "meta": True}]
        mats += [geo.vertex_point[start:start + take, None],
                 geo.vertex_prim()[start:start + take, None]]
    elif cls == PRIM and n:
        cols += [{"name": "type", "size": 1, "kind": "s", "meta": True},
                 {"name": "nvtx", "size": 1, "kind": "i", "meta": True},
                 {"name": "closed", "size": 1, "kind": "i", "meta": True}]
        mats += [np.array([[PRIM_TYPE_NAMES.get(int(t), t)]
                           for t in geo.prim_type[start:start + take]]),
                 geo.prim_sizes()[start:start + take, None],
                 geo.prim_closed[start:start + take, None].astype(np.int32)]

    # Group membership columns. In Houdini's spreadsheet each group is a 0/1 column,
    # and rows in the group are highlighted -- that is how you confirm the selection when tuning Group Create.
    for gname in sorted(geo.groups.get(cls, {}).keys()):
        cols.append({"name": f"group:{gname}", "size": 1, "kind": "g",
                     "meta": False})
        mats.append(geo.get_group(cls, gname)[start:start + take, None]
                    .astype(np.int32))

    for name in geo.names(cls):
        a = geo.get(cls, name)
        cols.append({"name": name, "size": int(a.shape[1]),
                     "kind": "s" if is_string(a) else a.dtype.kind,
                     "meta": False})
        mats.append(a[start:start + take] if cls != DETAIL else a)

    # String columns cannot be astype(float64) together with numeric ones, so convert column by column to Python values and join.
    if mats and take:
        cooked = []
        for m in mats:
            if m.dtype.kind == "U":
                cooked.append([[str(x) for x in r] for r in m])
            else:
                cooked.append([[None if not np.isfinite(v) else round(float(v), 6)
                                for v in r] for r in m.astype(np.float64)])
        rows = [sum((c[i] for c in cooked), []) for i in range(take)]
    else:
        rows = []

    return {"count": int(n), "start": start, "cols": cols, "rows": rows,
            "groups": sorted(geo.groups.get(cls, {}).keys())}


class PCG_GeoSpreadsheet:
    """Shows a geometry data table inside the node. Also outputs a plain-text summary for wiring into other nodes."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "geo": ("GEOMETRY",),
                "max_rows": ("INT", {"default": 64, "min": 1, "max": 2000}),
                "start_row": ("INT", {"default": 0, "min": 0, "max": 1 << 24}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("info",)
    FUNCTION = "run"
    CATEGORY = "PCG/output"
    OUTPUT_NODE = True


    def run(self, geo, max_rows, start_row, unique_id=None):
        rev = remember(unique_id, geo)
        payload = {
            "node_id": str(unique_id), "rev": rev, "rows": int(max_rows),
            "counts": {POINT: geo.npoints, VERTEX: geo.nvertices,
                       PRIM: geo.nprims, DETAIL: 1},
            "bbox": [np.asarray(x).tolist() for x in geo.bbox()],
            "tables": {c: _table(geo, c, max_rows, start_row)
                       for c in CLASS_ORDER},
        }
        return {"ui": {"pcg_spreadsheet": [payload]},
                "result": (geo.info(),)}


def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return False                      # outside ComfyUI (unit tests)

    @PromptServer.instance.routes.get("/pcg/sheet/{node_id}")
    async def _pcg_sheet(request):
        q = request.rel_url.query
        try:
            r = page(request.match_info["node_id"], q.get("cls", POINT), int(q.get("start", 0)),
                     int(q.get("rows", 64)))
        except (ValueError, TypeError) as e:
            return web.Response(status=400, text=str(e))
        if r is None:
            return web.Response(status=404, text="no spreadsheet data for this node -- run it once")
        return web.json_response(r, headers={"Cache-Control": "no-store"})
    return True


_ROUTES_OK = _register_routes()

NODE_CLASS_MAPPINGS = {"PCG_GeoSpreadsheet": PCG_GeoSpreadsheet}
NODE_DISPLAY_NAME_MAPPINGS = {"PCG_GeoSpreadsheet": "Geometry Spreadsheet (PCG)"}
