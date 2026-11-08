"""
Server side of the 3D viewport embedded in a node.

Idea:
  Geometry objects live in the Python process; frontend JS cannot see them. So a transport channel is needed.
  Two options:
    (a) write a glb to output/, put the path into {"ui": ...}, and the frontend loads it with GLTFLoader
        -- simple, but every cook writes to disk, and point clouds / polylines cannot be expressed
    (b) serialize into compact binary in an in-memory cache and register an HTTP route for the frontend to fetch
        -- 50 more lines, but zero disk IO, and point clouds and polylines both work

(b) is used here. Format:
    [uint32 header length][utf-8 JSON header][buffers packed tightly]
The JSON header records each buffer's offset/length/dtype; the frontend slices the ArrayBuffer as needed
and feeds it straight to THREE.BufferAttribute, with no per-element parsing.
"""
from __future__ import annotations

import json
import struct
import threading

import numpy as np

from .geo import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .geo import ops as _ops
from .geo.core import (PRIM_NURBS_CURVE, PRIM_NURBS_SURF,
                       PRIM_BEZIER_CURVE, PRIM_BEZIER_SURF, SPLINE_TYPES)

# node_id -> (rev, bytes). Only the latest result is kept, so it never grows unbounded.
_CACHE: dict[str, tuple[int, bytes]] = {}
_REV = [0]
_LOCK = threading.Lock()

MAGIC = b"PCGB"
NURBS_DISPLAY_DIVS = 33      # subdivision density of NURBS in the viewport, display only


def polygon_edges(geo: Geometry) -> np.ndarray:
    """
    (E,2) deduplicated polygon edges. The frontend must not derive them from triangles with WireframeGeometry --
    quads would get an extra diagonal, which ruins inspecting topology in PCG.
    """
    if not geo.nvertices:
        return np.zeros((0, 2), np.uint32)
    vp = geo.vertex_point
    e = np.stack([vp, vp[geo.next_corner()]], 1)
    # The last corner of an open polyline wraps back to the start; that edge does not exist
    last = np.zeros(geo.nvertices, bool)
    last[geo.prim_offset[1:] - 1] = True
    e = e[~(last & ~np.repeat(geo.prim_closed, geo.prim_sizes()))]
    return np.unique(np.sort(e, axis=1), axis=0)


def encode(geo: Geometry, template: Geometry | None = None) -> bytes:
    """
    Pack Geometry into binary the frontend can consume directly.

    template is Houdini's template display: only positions and edges are sent, no normals/colours --
    it is only used to draw a grey wireframe; extra data is a waste of bandwidth.
    """
    buffers, header = [], {"buffers": {}}
    offset = 0

    def put(name, arr, dtype):
        nonlocal offset
        a = np.ascontiguousarray(arr, dtype)
        b = a.tobytes()
        header["buffers"][name] = {
            "offset": offset, "length": len(b),
            "dtype": np.dtype(dtype).name,
            "itemsize": int(a.shape[1]) if a.ndim > 1 else 1,
        }
        # Pad each buffer to a 4-byte boundary. Group masks are uint8 and their length is usually not a multiple of 4;
        # without padding the byteOffset of every float32/uint32 after them is off,
        # and the frontend's new Float32Array(buf, offset) throws RangeError.
        pad = (-len(b)) % 4
        buffers.append(b + b"\0" * pad)
        offset += len(b) + pad

    # NURBS must be **auto-subdivided for display** in the viewport -- that is what Houdini does, otherwise the user
    # sees only a bunch of control points. The original geometry is kept as the control mesh, drawn as another layer.
    # counts still reports the original geometry's numbers; that is "what this prim really is".
    src = geo
    hull = None
    # Volume prims (pcg106): SDFs are drawn as closed iso-surfaces, fog as ray-marched smoke (web/pcg_volume.js),
    # following Volume Visualization when it is upstream. See geo/volvis.py. Before, every volume was its 0
    # iso-surface, so fog that is positive everywhere showed nothing at all.
    # Packed primitives (pcg121): every distinct piece is sent once, with one 4x4 matrix per copy; the frontend
    # draws them as an InstancedMesh. See geo/packed.py
    insts = []
    if geo.nprims and (geo.prim_type == 1).any():
        from .geo import packed as _pk
        insts = _pk.instances(geo)
    vols = []
    if geo.nprims and (geo.prim_type == 2).any():
        from .geo import volvis as _vv
        geo, vols = _vv.prepare(geo)
    if geo.nprims and np.isin(geo.prim_type, SPLINE_TYPES).any():
        hull = geo
        geo = _ops.compute_normals(
            _ops.spline_to_polygons(geo, None, NURBS_DISPLAY_DIVS,
                                   NURBS_DISPLAY_DIVS), "point")

    P = geo.get(POINT, "P")
    if P is None:
        P = np.zeros((0, 3), np.float32)
    put("position", P, np.float32)

    # Triangulate and get corner indices at the same time -- vertex normal display and hard-edge shading depend on it
    tri, tri_corner = geo.triangles(with_corners=True)
    if len(tri):
        put("index", tri, np.uint32)
        put("tri_corner", tri_corner, np.uint32)

    e = polygon_edges(geo)
    if len(e):
        put("edges", e, np.uint32)

    # Polylines are sent separately; the frontend draws them with LineSegments
    seg = []
    for i in range(geo.nprims):
        if not geo.prim_closed[i]:
            idx = geo.prim_points(i)
            if len(idx) >= 2:
                seg.append(np.stack([idx[:-1], idx[1:]], 1))
    if seg:
        put("lines", np.concatenate(seg), np.uint32)

    # corner -> point, used for positioning when drawing vertex normals and labelling vertex numbers
    if geo.nvertices:
        put("vertex_point", geo.vertex_point, np.uint32)
        # Which prim a corner belongs to. When the frontend draws vertex normals / labels vertex numbers,
        # the corners on the same point overlap exactly, and must be nudged toward their own face centres to be told apart.
        put("vertex_prim", geo.vertex_prim(), np.uint32)
    if geo.nprims:
        put("prim_center", _ops.prim_centers(geo), np.float32)

    # Normals of the three classes are sent separately; the frontend shows them on demand. Missing ones are not sent.
    if geo.has(POINT, "N"):
        put("normal", geo.get(POINT, "N"), np.float32)
    if geo.has(VERTEX, "N"):
        put("vnormal", geo.get(VERTEX, "N"), np.float32)
    if geo.has(PRIM, "N"):
        put("pnormal", geo.get(PRIM, "N"), np.float32)
    # Cd in the shaded view, like Houdini: one class is drawn, picked with Houdini's precedence vertex > point >
    # primitive > detail (pcg109; before, only a point Cd was sent and only the "color" shading mode used it).
    # The frontend looks colours up per point, per triangle corner (vertex) or per face (primitive).
    for cls in (VERTEX, POINT, PRIM, DETAIL):
        cd = geo.get(cls, "Cd") if geo.has(cls, "Cd") else None
        if cd is None or is_string(cd):
            continue
        cd = np.asarray(cd, np.float32)
        if cd.ndim != 2 or cd.shape[1] < 3 or not len(cd):
            continue
        put("color", np.clip(cd[:, :3], 0, 1), np.float32)
        header["color_class"] = cls
        break

    if template is not None and template.npoints:
        put("t_position", template.get(POINT, "P"), np.float32)
        te = polygon_edges(template)
        if len(te):
            put("t_edges", te, np.uint32)
        header["t_counts"] = {"points": template.npoints,
                              "prims": template.nprims}

    # Group masks are sent in full. The frontend highlights from them, so switching groups needs no re-execution -- one group is
    # one byte per element, a few tens of KB for tens of thousands of elements, far cheaper than a round trip.
    gmeta = {}
    for cls in (POINT, VERTEX, PRIM):
        names = sorted(geo.groups[cls].keys())
        if not names:
            continue
        gmeta[cls] = names
        for i, nm in enumerate(names):
            put(f"g_{cls}_{i}", geo.get_group(cls, nm)[:, None], np.uint8)
    if gmeta:
        header["groups"] = gmeta

    # Control mesh: grid lines + control points. Surfaces connect into a (nu,nv) lattice, curves connect in order.
    if hull is not None and hull.npoints:
        put("h_position", hull.get(POINT, "P"), np.float32)
        nu_a, nv_a = hull.get(PRIM, "nu"), hull.get(PRIM, "nv")
        seg = []
        for i in range(hull.nprims):
            idx = hull.prim_points(i)
            t = int(hull.prim_type[i])
            if t in (PRIM_NURBS_SURF, PRIM_BEZIER_SURF) and nu_a is not None:
                nu, nv = int(nu_a[i, 0]), int(nv_a[i, 0])
                if nu * nv != len(idx):
                    continue
                gidx = idx.reshape(nv, nu)
                seg.append(np.stack([gidx[:, :-1], gidx[:, 1:]], -1).reshape(-1, 2))
                seg.append(np.stack([gidx[:-1, :], gidx[1:, :]], -1).reshape(-1, 2))
            elif t in (PRIM_NURBS_CURVE, PRIM_BEZIER_CURVE) and len(idx) >= 2:
                seg.append(np.stack([idx[:-1], idx[1:]], 1))
        if seg:
            put("h_edges", np.concatenate(seg), np.uint32)
        header["counts_hull"] = {"points": hull.npoints, "prims": hull.nprims}

    # Attribute values are sent in full; the frontend visualizes them (like Houdini's attribute visualization).
    # String attributes are converted to integer codes -- they have no ordering and can only be coloured by category; once encoded,
    # the frontend handles them with the same "discrete colour" logic, without a separate path for strings.
    ameta = {}
    budget = 24 << 20                      # cap on total attribute size, so a large mesh cannot blow up the payload
    for cls in (POINT, VERTEX, PRIM):
        for name in geo.names(cls):
            a = geo.get(cls, name)
            if a is None or not len(a):
                continue
            if is_string(a):
                _, codes = np.unique(a[:, 0], return_inverse=True)
                arr = codes.reshape(-1, 1).astype(np.float32)
                meta = {"size": 1, "kind": "cat", "levels": int(codes.max()) + 1}
            else:
                arr = np.asarray(a, np.float32)
                col = arr.shape[1]
                # Integer types with few distinct values are more useful coloured by category (class / index and the like)
                uniq = np.unique(arr) if col == 1 and arr.size <= 4_000_000 else None
                cat = (uniq is not None and len(uniq) <= 256
                       and np.all(uniq == np.round(uniq)))
                meta = {"size": col, "kind": "cat" if cat else "num",
                        "min": [float(v) for v in arr.min(0)],
                        "max": [float(v) for v in arr.max(0)]}
                if cat:
                    meta["levels"] = int(len(uniq))
            nbytes = arr.size * 4
            if nbytes > budget:
                continue
            budget -= nbytes
            put(f"a_{cls}_{name}", arr, np.float32)
            ameta.setdefault(cls, {})[name] = meta
    if ameta:
        header["attrib_meta"] = ameta

    if insts:
        imeta, ilo, ihi = [], [], []
        for k, (piece, X, pts) in enumerate(insts):
            info = _encode_instance(piece, X, pts, geo, k, put)
            if info is None:
                continue
            imeta.append(info)
            ilo.append(info.pop("lo"))
            ihi.append(info.pop("hi"))
        if imeta:
            header["instances"] = imeta
            mn_i, mx_i = np.min(ilo, 0), np.max(ihi, 0)
    if vols:
        meta = []
        for v in vols:
            for nm, (arr, dt) in v.pop("arrays", {}).items():
                put(nm, arr.reshape(-1), dt)
            meta.append(v)
        header["volumes"] = meta
    mn, mx = geo.bbox()
    if vols:
        lo = np.min([v["box"][0] for v in vols], 0)
        hi = np.max([v["box"][1] for v in vols], 0)
        if geo.npoints:
            mn, mx = np.minimum(mn, lo), np.maximum(mx, hi)
        else:
            mn, mx = lo, hi
    if insts and "instances" in header:
        mn, mx = np.minimum(mn, mn_i), np.maximum(mx, mx_i)
    if template is not None and template.npoints:
        # Merge the bbox in, so both are in frame when focusing with F -- same as Houdini
        tmn, tmx = template.bbox()
        mn, mx = np.minimum(mn, tmn), np.maximum(mx, tmx)
    header["bbox"] = [np.asarray(mn).tolist(), np.asarray(mx).tolist()]
    header["counts"] = {"points": src.npoints, "verts": src.nvertices,
                        "prims": src.nprims, "tris": int(len(tri))}
    header["attribs"] = {c: src.names(c) for c in ("point", "vertex", "prim")}

    hj = json.dumps(header).encode("utf-8")
    # Pad the header with spaces to 4-byte alignment -- otherwise the frontend's new Float32Array(buf, offset)
    # throws right away because byteOffset is misaligned. This pit is well hidden; do not skip these two lines.
    hj += b" " * ((-(8 + len(hj))) % 4)
    return MAGIC + struct.pack("<I", len(hj)) + hj + b"".join(buffers)


def _encode_instance(piece, X, pts, geo, k, put):
    """
    One distinct packed piece: split triangles (so vertex / primitive Cd and hard edges survive) + per-copy
    matrices (column-major, what three.js Matrix4.fromArray reads) + per-copy Cd from the packed points.
    Returns the header entry with the instances' bounding box, or None for a piece without faces.
    """
    from .geo import packed as _pk
    if _pk.is_packed(piece):
        piece = _pk.unpack(piece)[0]
    tri, cor = piece.triangles(with_corners=True)
    if not len(tri):
        return None
    P = np.asarray(piece.get(POINT, "P"), np.float32)
    pos = P[tri].reshape(-1, 3)
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    fn = np.cross(b - a, c - a)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-20)
    if piece.has(VERTEX, "N"):
        nrm = np.asarray(piece.get(VERTEX, "N"), np.float32)[cor].reshape(-1, 3)
    elif piece.has(POINT, "N"):
        nrm = np.asarray(piece.get(POINT, "N"), np.float32)[tri].reshape(-1, 3)
    else:
        nrm = np.repeat(fn, 3, axis=0)
    put(f"i{k}_position", pos, np.float32)
    put(f"i{k}_normal", nrm, np.float32)
    col = None
    for cls in (VERTEX, POINT, PRIM):
        cd = piece.get(cls, "Cd") if piece.has(cls, "Cd") else None
        if cd is None or is_string(cd) or cd.shape[1] < 3:
            continue
        cd = np.clip(np.asarray(cd, np.float32)[:, :3], 0, 1)
        if cls == VERTEX:
            col = cd[cor].reshape(-1, 3)
        elif cls == POINT:
            col = cd[tri].reshape(-1, 3)
        else:
            tri_prim = piece.vertex_prim()[cor[:, 0]]
            col = np.repeat(cd[tri_prim], 3, axis=0)
        break
    if col is not None:
        put(f"i{k}_color", col, np.float32)
    n = len(X)
    put(f"i{k}_matrix", np.ascontiguousarray(X.transpose(0, 2, 1)).reshape(n, 16), np.float32)
    icd = geo.get(POINT, "Cd") if geo.has(POINT, "Cd") else None
    has_icol = icd is not None and not is_string(icd) and icd.shape[1] >= 3
    if has_icol:
        put(f"i{k}_icolor", np.clip(np.asarray(icd, np.float32)[pts, :3], 0, 1), np.float32)
    lo, hi = P.min(0).astype(np.float64), P.max(0).astype(np.float64)
    corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    W = np.einsum("nij,cj->nci", X, corners)[..., :3].reshape(-1, 3)
    return {"id": k, "count": n, "tris": int(len(tri)), "color": col is not None, "icolor": bool(has_icol),
            "lo": W.min(0), "hi": W.max(0)}


def bbox_with_volumes(geo: Geometry):
    """Bounding box that includes the full extent of volume prims (their single point is only the centre)."""
    mn, mx = geo.bbox()
    if not geo.nprims or not (geo.prim_type == 2).any():
        return mn, mx
    from .geo import vdb as _v
    los, his = [], []
    for i in _v.volume_prims(geo):
        vox, o, c = _v.grid(geo, i)
        los.append(o)
        his.append(o + c * (np.array(_v.res_of(vox)) - 1))
    if not los:
        return mn, mx
    lo, hi = np.min(los, 0), np.max(his, 0)
    others = geo.prim_type != 2
    if others.any():
        return np.minimum(mn, lo), np.maximum(mx, hi)
    return lo, hi


def _bbox_with_instances(geo, mn, mx):
    if not geo.nprims or not (geo.prim_type == 1).any():
        return mn, mx
    from .geo import packed as _pk
    for piece, X, _ in _pk.instances(geo):
        P = piece.get(POINT, "P")
        if P is None or not len(P):
            continue
        lo, hi = np.asarray(P, np.float64).min(0), np.asarray(P, np.float64).max(0)
        c = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        W = np.einsum("nij,cj->nci", X, c)[..., :3].reshape(-1, 3)
        mn, mx = np.minimum(mn, W.min(0)), np.maximum(mx, W.max(0))
    return mn, mx


def publish(node_id: str, geo: Geometry, template: Geometry | None = None) -> dict:
    """Store in the cache and return the metadata for the frontend."""
    with _LOCK:
        _REV[0] += 1
        rev = _REV[0]
        _CACHE[str(node_id)] = (rev, encode(geo, template))
    mn, mx = _bbox_with_instances(geo, *bbox_with_volumes(geo))
    return {"node_id": str(node_id), "rev": rev,
            "points": geo.npoints, "prims": geo.nprims,
            "bbox": [np.asarray(mn).tolist(), np.asarray(mx).tolist()]}


# ------------------------------------------------------------ HTTP routes
def _register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return False                      # silently skip when unit-testing outside ComfyUI

    @PromptServer.instance.routes.get("/pcg/geo/{node_id}")
    async def _pcg_geo(request):
        nid = request.match_info["node_id"]
        with _LOCK:
            item = _CACHE.get(nid)
        if item is None:
            return web.Response(status=404, text="no geometry for node " + nid)
        return web.Response(body=item[1],
                            content_type="application/octet-stream",
                            headers={"Cache-Control": "no-store",
                                     "X-PCG-Rev": str(item[0])})
    return True


_ROUTES_OK = _register_routes()


# ------------------------------------------------------------ nodes
class PCG_Viewport:
    """
    A three.js viewport embedded in the node body.
    Every cook puts the geometry into the cache; the frontend fetches the binary after onExecuted and rebuilds.
    """
    @classmethod
    def INPUT_TYPES(cls):
        # Only geo. shading / show_points / show_grid are frontend-only widgets;
        # putting them here would recompute the whole chain just for changing the shading mode.
        return {
            "required": {"geo": ("GEOMETRY",)},
            # template: like Houdini's template display. Grey wireframe, for reference only.
            # Houdini uses a node flag; in ComfyUI a wire is more explicit -- the dependency is visible.
            "optional": {"template": ("GEOMETRY",)},
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("GEOMETRY",)
    RETURN_NAMES = ("geo",)
    FUNCTION = "run"
    CATEGORY = "PCG/output"
    OUTPUT_NODE = True

    def run(self, geo, template=None, unique_id=None):
        meta = publish(unique_id, geo, template)
        # Pass geo through, so the viewport can sit in the middle of a chain as a "display flag" rather than as an end node
        return {"ui": {"pcg_viewport": [meta]}, "result": (geo,)}


class PCG_Display:
    """
    Landing point of the display flag -- like Houdini's display / template flag.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Why such a node is needed, rather than "just click a flag"
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Houdini and ComfyUI are **opposite** on "who drives evaluation":

        Houdini    The display flag itself is the reason to cook. Whichever node it is on, the chain is cooked up to there.
        ComfyUI    Only the part of the graph **leading to output nodes** is evaluated. An intermediate node whose output
                   is not wired to any terminal is never executed at all.

    So "make any intermediate node the visible one" cannot be a frontend-only matter -- the flagged node must
    actually enter the execution subgraph. The approach is to place this sink node in the graph, and when a flag is clicked use litegraph's
    connect() to **rewire** its input to the flagged node.

    This was chosen because it is WYSIWYG: the wire in the graph is the actual execution dependency, it is saved into the workflow
    correctly by nature, and undo / redo / copy-paste all work as usual.
    The other route is hooking the frontend's graphToPrompt() to temporarily insert a sink into the submitted prompt --
    a cleaner graph, but it depends on a hook point with no stable contract, and "dependencies you cannot see in the graph"
    are very painful when troubleshooting.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Division of labour with Viewport (PCG)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Viewport (PCG)  has its **own** three.js canvas in the node body. Use it to pin two branches side by side
                    in the graph for comparison.
    Display (PCG)   has no canvas, it is just a landing point -- the picture is in the **docked panel**.
                    Usually one per graph is enough; it is wired to wherever the flag is clicked.

    Both use the same transport channel (publish -> /pcg/geo/<node_id>), and the frontend reuses the same
    Viewport class, so both sides display pixel-identical results.

    Passes geo through, so it can sit in the middle of a chain instead of being forced to be an end node.
    """
    @classmethod
    def INPUT_TYPES(cls):
        # Like Viewport, frontend-only shading / wireframe options are kept out of INPUT_TYPES --
        # putting them in would invalidate and recompute the whole chain just for changing the shading mode.
        return {
            "required": {"geo": ("GEOMETRY",)},
            "optional": {"template": ("GEOMETRY",)},
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("GEOMETRY",)
    RETURN_NAMES = ("geo",)
    FUNCTION = "run"
    CATEGORY = "PCG/output"
    OUTPUT_NODE = True

    def run(self, geo, template=None, unique_id=None):
        meta = publish(unique_id, geo, template)
        return {"ui": {"pcg_display": [meta]}, "result": (geo,)}


NODE_CLASS_MAPPINGS = {"PCG_Viewport": PCG_Viewport,
                       "PCG_Display": PCG_Display}
NODE_DISPLAY_NAME_MAPPINGS = {"PCG_Viewport": "Viewport (PCG)",
                              "PCG_Display": "Display (PCG)"}
