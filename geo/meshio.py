"""
Mesh / point cloud **import** -- OBJ / PLY / STL / GLB, pure python, zero dependencies.

This was the biggest gap in the AI -> procedural direction: there was only the `ExportMesh` exit, no
entrance. And the image-to-3D generation of models (Hunyuan3D / Trellis / TripoSR and the like) output
exactly "**right shape, rotten topology**": triangle soup, duplicate points, no UVs, runaway primitive counts -- and this plugin itself
is a toolkit for fixing topology (Fuse / Facet / PolyReduce / Convert / Boolean /
UVAutoSeams / UVFlatten / UVLayout / Subdivide). Only with this chain connected does "AI makes the shape,
procedural makes the usable asset" hold.

Zero dependencies is deliberate: trimesh can read these formats, but it's an optional dependency, and **import** is the entrance --
if the entrance breaks, nothing in the chain gets in. So all four formats are parsed in-house; trimesh is only relevant to the "accept in-memory objects from the ComfyUI 3D
ecosystem" mode (and that mode is duck-typed, no import).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Four decisions that "go silently wrong if not made this way"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**1) No triangulation at the door.** OBJ ngons are kept as ngons. This package's Geometry already
supports variable-length prims, and triangulating at the entrance throws away information: PolyReduce's quad preservation, Dissolve's
coplanar merging, PolyBevel's edge detection all need the original primitive structure. Houdini's File SOP
does the same.

**2) STL welds points by default.** STL is **triangle soup** -- each triangle carries its own three points, nothing shared.
Without welding, the point count is tripled and connectivity is zero, so Subdivide / PolyReduce /
Connectivity / Normal (cusp) after Fuse all **quietly do nothing**: no error, just "why are there still cracks after
subdividing". So STL welds by default and other formats don't (they share points already).

The weld tolerance is **relative to the bounding box**, not absolute -- an absolute tolerance would weld a model at 1e-3 scale
entirely into one point, and at 1e4 scale wouldn't weld a single point. This pitfall was hit once in the Voronoi 2D batch;
not hitting it a second time.

**3) UVs are written on vertices, not points.** OBJ's `vt` indices are **per corner**
(the same point can have different uvs on different primitives -- that is exactly the definition of a UV seam). Written to points,
the seams would be silently smoothed over, and you'd only notice the blurry texture at UVLayout / baking time.
glTF uvs are per point to begin with, but here they're also **expanded to vertices**: the default
class of every UV node in this package is VERTEX (see the signature of uvproject.project); mixing the two conventions would leave downstream nodes
"blind" to the imported uv -- again with no error. The cost is a bit more memory; worth it.
glTF's v axis points down (origin at the texture's top left); on read it's flipped to 1 - v (origin at bottom left, the same convention as OBJ,
COP baking and Export Mesh); without the flip, glb models come in with textures upside down.

**4) The up axis isn't guessed.** The glTF spec is Y-up (matching the viewport here); OBJ / PLY / STL
have **no** convention -- Blender exports are often Z-up. Guessing wrong leaves the model lying down, and that
is "obvious at a glance", so it's an explicit parameter rather than a heuristic: a heuristic that's right nine times and wrong
the tenth is worse than choosing yourself every time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Format detection uses **magic numbers**, not extensions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Renamed extensions are common in AI pipelines (a downloaded .glb that is really gltf+json, an .obj that is really ply).
So auto mode looks at content: `ply` / `glTF` / `{` (gltf json) are unambiguous magic numbers.

**Detecting binary STL is a classic trap**: its 80-byte header often starts with "solid"
(many exporters write that), so "starts with solid means ascii" is wrong. The only reliable criterion is
**length**: a binary STL is exactly `84 + 50 x triangle count` bytes. That's what's used here.
"""
from __future__ import annotations

import base64
import json
import os
import struct

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, PRIM_POLY
from . import ops as _ops

FORMATS = ("auto", "obj", "ply", "stl", "glb", "las")
UP_AXES = ("as_is", "z_up_to_y_up", "y_up_to_z_up")
WELD_MODES = ("auto", "on", "off")

# Weld tolerance: this fraction of the bounding box diagonal. 1e-5 is a comfortable divide between "the same vertex written twice" and
# "two genuinely different but close vertices" -- exporter duplicates are **bitwise
# identical** or differ only in the last few bits, while points placed close on purpose while modelling are rarely within 1/10,000
WELD_REL = 1e-5

# Spherical harmonics degree-0 basis function. In 3DGS .ply files f_dc_* stores SH coefficients, not the color itself
SH_C0 = 0.28209479177387814


# ═══════════════════════════════════════════════════════════ format detection
def sniff(data: bytes, path: str = "") -> str:
    """Detect the format by content. Fall back to the extension if that fails, and finally raise."""
    head = bytes(data[:16])
    if head[:4] == b"LASF":
        return "las"
    if head[:3] == b"ply" and head[3:4] in (b"\n", b"\r"):
        return "ply"
    if head[:4] == b"glTF":
        return "glb"
    if _is_binary_stl(data):
        return "stl"
    txt = head.lstrip()
    if txt[:1] == b"{":                       # .gltf (pure JSON)
        return "glb"
    low = bytes(data[:4096]).lower()
    if low.lstrip()[:5] == b"solid" or b"\nfacet normal" in low:
        return "stl"
    # OBJ has no magic number; we can only look for typical lines. Placed last so it doesn't swallow other formats
    for tok in (b"\nv ", b"\nf ", b"\nvt ", b"\nvn ", b"\no ", b"\ng "):
        if low.startswith(tok[1:]) or tok in low:
            return "obj"
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in ("obj", "ply", "stl"):
        return ext
    if ext in ("las", "laz"):
        return "las"
    if ext in ("glb", "gltf"):
        return "glb"
    raise ValueError(
        f"Can't recognize this file's format (first 16 bytes {head!r}). "
        f"Supported: obj / ply / stl / glb (gltf) / las (laz); you can specify it with the format parameter.")


def _is_binary_stl(data: bytes) -> bool:
    """
    The **only** reliable criterion for binary STL: length is exactly 84 + 50 x triangle count.

    You can't check "starts with solid" -- a binary STL's 80-byte header is often exactly
    "solid xxx" (written by the exporter in passing), so it gets parsed as ascii, yielding an empty mesh,
    with no error.
    """
    if len(data) < 84:
        return False
    n = struct.unpack_from("<I", data, 80)[0]
    return n > 0 and len(data) == 84 + 50 * n


# ═════════════════════════════════════════════════════════════════ OBJ
def _obj_index(tok, n):
    """OBJ index: 1-based, **negative values are relative to the count read so far** (-1 = the last one)."""
    i = int(tok)
    if i > 0:
        return i - 1
    if i < 0:
        return n + i
    raise ValueError("OBJ indices can't be 0 (they are 1-based)")


def load_obj(text):
    """
    -> dict(P, Cd, faces, closed, uv_corner, n_corner, names, materials)

    faces is a variable-length list (ngons kept as is); uv_corner / n_corner are per-corner indices.
    """
    P, VT, VN, CD = [], [], [], []
    faces, closed, fuv, fvn, fname, fmat = [], [], [], [], [], []
    name, mat = "", ""
    has_cd = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] == "#":
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            # Some exporters (MeshLab / some 3D generation models) append vertex colors right after v:
            # v x y z r g b. The extra three numbers are color, not w
            P.append([float(parts[1]), float(parts[2]), float(parts[3])])
            if len(parts) >= 7:
                CD.append([float(parts[4]), float(parts[5]), float(parts[6])])
                has_cd = True
            else:
                CD.append([1.0, 1.0, 1.0])
        elif tag == "vt":
            VT.append([float(parts[1]),
                       float(parts[2]) if len(parts) > 2 else 0.0])
        elif tag == "vn":
            VN.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif tag in ("f", "l"):
            idx, uvs, nrm = [], [], []
            for tok in parts[1:]:
                a = tok.split("/")
                idx.append(_obj_index(a[0], len(P)))
                uvs.append(_obj_index(a[1], len(VT))
                           if len(a) > 1 and a[1] else -1)
                nrm.append(_obj_index(a[2], len(VN))
                           if len(a) > 2 and a[2] else -1)
            if len(idx) < 2:
                continue                       # single-point f/l: meaningless, skip
            faces.append(idx)
            closed.append(tag == "f")
            fuv.append(uvs)
            fvn.append(nrm)
            fname.append(name)
            fmat.append(mat)
        elif tag in ("g", "o"):
            name = " ".join(parts[1:]) if len(parts) > 1 else ""
        elif tag == "usemtl":
            mat = " ".join(parts[1:]) if len(parts) > 1 else ""
    return {"P": np.asarray(P, np.float64).reshape(-1, 3),
            "Cd": np.asarray(CD, np.float64).reshape(-1, 3) if has_cd else None,
            "faces": faces, "closed": closed,
            "uv": np.asarray(VT, np.float64).reshape(-1, 2),
            "N": np.asarray(VN, np.float64).reshape(-1, 3),
            "uv_corner": fuv, "n_corner": fvn,
            "names": fname, "materials": fmat}


# ═════════════════════════════════════════════════════════════════ PLY
_PLY_DTYPE = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}


def _ply_header(data):
    """-> (elements, fmt, header_len). elements keep the file's order."""
    end = data.find(b"end_header")
    if end < 0:
        raise ValueError("PLY file has no end_header; the file may be truncated")
    nl = data.find(b"\n", end)
    head = data[:nl].decode("ascii", "replace")
    lines = [l.strip() for l in head.splitlines()]
    if not lines or lines[0].strip() != "ply":
        raise ValueError("A PLY file must start with 'ply'")
    fmt, elements = None, []
    for l in lines[1:]:
        p = l.split()
        if not p:
            continue
        if p[0] == "format":
            fmt = p[1]
        elif p[0] == "element":
            elements.append({"name": p[1], "count": int(p[2]), "props": []})
        elif p[0] == "property" and elements:
            if p[1] == "list":
                elements[-1]["props"].append(
                    {"list": True, "count_type": p[2], "item_type": p[3],
                     "name": p[4]})
            else:
                elements[-1]["props"].append(
                    {"list": False, "type": p[1], "name": p[2]})
        elif p[0] == "comment" and len(p) > 1:
            pass
    if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise ValueError(f"Unsupported PLY format: {fmt}")
    return elements, fmt, nl + 1


def _ply_faces_binary(buf, off, n, cnt_dt, item_dt):
    """
    Variable-length face list. First take the **vectorized fast path** (all faces the same size, true for 99% of files),
    verified by "are the count bytes at every stride position all equal"; if not, fall back to a per-face loop.

    With only the loop, 500k faces take seconds (python level); with only the fast path, files with mixed face sizes
    would be **silently misaligned** -- the faces read are still "presentable" triangles, just connected to the wrong points.
    """
    if n == 0:
        return [], off
    cs = np.dtype(cnt_dt).itemsize
    isz = np.dtype(item_dt).itemsize
    if off + cs > len(buf):
        raise ValueError("PLY face list data is short (can't even read the first face's count) -- "
                         "the file may be truncated")
    k = int(np.frombuffer(buf, cnt_dt, 1, off)[0])
    stride = cs + k * isz
    if k > 0 and off + n * stride <= len(buf):
        counts = np.frombuffer(buf, np.uint8, n * stride,
                               off).reshape(n, stride)[:, :cs]
        want = counts[0:1]
        if np.array_equal(counts, np.repeat(want, n, axis=0)):
            raw = np.frombuffer(buf, np.uint8, n * stride, off)
            idx = raw.reshape(n, stride)[:, cs:].copy().view(item_dt)
            return [row.tolist() for row in idx.reshape(n, k)], \
                off + n * stride
    out = []
    for i in range(n):
        # Check bounds at every step. Otherwise numpy raises "buffer is smaller than
        # requested size" -- which says neither which file nor which face,
        # while "file truncated" is the most common way mesh files break (incomplete download)
        if off + cs > len(buf):
            raise ValueError(f"PLY face list runs out of data at face {i} "
                             f"({n} declared in total) -- the file is truncated")
        k = int(np.frombuffer(buf, cnt_dt, 1, off)[0])
        off += cs
        if off + k * isz > len(buf):
            raise ValueError(f"PLY face {i} declares {k} points, "
                             f"but the file only has {len(buf) - off} bytes left -- the file is truncated")
        out.append(np.frombuffer(buf, item_dt, k, off).tolist())
        off += k * isz
    return out, off


def load_ply(data):
    """-> dict(props={name: (N,) array}, faces=[[...]], edges=[[a,b]])"""
    elements, fmt, off = _ply_header(data)
    big = fmt == "binary_big_endian"
    props, faces, lines = {}, [], []
    if fmt == "ascii":
        toks = data[off:].split()
        pos = 0
        for el in elements:
            if el["props"] and el["props"][0]["list"]:
                for _ in range(el["count"]):
                    k = int(toks[pos]); pos += 1
                    row = [int(toks[pos + j]) for j in range(k)]
                    pos += k
                    (lines if el["name"] == "edge" else faces).append(row)
                continue
            cols = {p["name"]: np.empty(el["count"], np.float64)
                    for p in el["props"] if not p["list"]}
            names = [p["name"] for p in el["props"] if not p["list"]]
            w = len(names)
            block = np.asarray(toks[pos:pos + el["count"] * w], dtype=np.float64
                               ) if el["count"] else np.zeros((0,))
            if el["count"] and len(block) < el["count"] * w:
                raise ValueError(
                    f"PLY {el['name']} data is short: needs {el['count'] * w} values, "
                    f"only {len(block)} present. The file may be truncated.")
            pos += el["count"] * w
            block = block.reshape(-1, w) if el["count"] else block.reshape(0, w)
            for j, nm in enumerate(names):
                cols[nm] = block[:, j]
            if el["name"] == "vertex":
                props.update(cols)
            else:
                props.update({f"{el['name']}:{k}": v for k, v in cols.items()})
        return {"props": props, "faces": faces, "edges": lines}

    buf = data
    for el in elements:
        if el["props"] and el["props"][0]["list"]:
            p = el["props"][0]
            cdt = (">" if big else "<") + _PLY_DTYPE[p["count_type"]]
            idt = (">" if big else "<") + _PLY_DTYPE[p["item_type"]]
            rows, off = _ply_faces_binary(buf, off, el["count"], cdt, idt)
            (lines if el["name"] == "edge" else faces).extend(rows)
            continue
        dt = np.dtype([(p["name"], (">" if big else "<") + _PLY_DTYPE[p["type"]])
                       for p in el["props"]])
        need = dt.itemsize * el["count"]
        if off + need > len(buf):
            raise ValueError(
                f"PLY {el['name']} data is short: needs {need} bytes, "
                f"only {len(buf) - off} left. The file may be truncated.")
        arr = np.frombuffer(buf, dt, el["count"], off)
        off += need
        for p in el["props"]:
            key = p["name"] if el["name"] == "vertex" \
                else f"{el['name']}:{p['name']}"
            props[key] = np.asarray(arr[p["name"]], np.float64)
    return {"props": props, "faces": faces, "edges": lines}


# ═════════════════════════════════════════════════════════════════ STL
def load_stl(data):
    """-> (P (3T,3) triangle soup, faces)"""
    if _is_binary_stl(data):
        n = struct.unpack_from("<I", data, 80)[0]
        dt = np.dtype([("n", "<3f4"), ("v", "<3f4", 3), ("a", "<u2")])
        arr = np.frombuffer(data, dt, n, 84)
        P = np.asarray(arr["v"], np.float64).reshape(-1, 3)
        return P, [[3 * i, 3 * i + 1, 3 * i + 2] for i in range(n)]
    txt = data.decode("utf-8", "replace") if isinstance(data, (bytes,
                                                               bytearray)) \
        else data
    pts = []
    for line in txt.splitlines():
        s = line.strip()
        if s[:6].lower() == "vertex":
            p = s.split()
            pts.append([float(p[1]), float(p[2]), float(p[3])])
    if len(pts) % 3:
        raise ValueError(
            f"ascii STL vertex count {len(pts)} is not a multiple of 3 -- "
            f"the file may be incomplete, or not a triangle mesh.")
    P = np.asarray(pts, np.float64).reshape(-1, 3)
    n = len(P) // 3
    return P, [[3 * i, 3 * i + 1, 3 * i + 2] for i in range(n)]


# ═════════════════════════════════════════════════════════════ GLB/glTF
_GL_DTYPE = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2",
             5125: "u4", 5126: "f4"}
_GL_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
             "MAT2": 4, "MAT3": 9, "MAT4": 16}


def _glb_chunks(data):
    """GLB container -> (json dict, BIN chunk). Plain .gltf is read directly as JSON."""
    if data[:4] != b"glTF":
        return json.loads(bytes(data).decode("utf-8")), None
    ver, total = struct.unpack_from("<II", data, 4)
    if ver != 2:
        raise ValueError(f"Only glTF 2.0 is supported (glb version={ver})")
    off, js, bin_ = 12, None, None
    while off + 8 <= min(total, len(data)):
        ln, kind = struct.unpack_from("<II", data, off)
        body = data[off + 8:off + 8 + ln]
        if kind == 0x4E4F534A:                 # 'JSON'
            js = json.loads(bytes(body).decode("utf-8"))
        elif kind == 0x004E4942:               # 'BIN\0'
            bin_ = body
        off += 8 + ln + (-ln) % 4              # chunks are 4-byte aligned
    if js is None:
        raise ValueError("No JSON chunk in the GLB")
    return js, bin_


def _gl_buffer(js, bin_, i, base_dir):
    b = js["buffers"][i]
    uri = b.get("uri")
    if uri is None:
        # An empty BIN chunk and a missing BIN chunk must be treated alike. Checking only `is None`, a zero-length
        # BIN chunk would be passed down as a valid buffer, and the error would eventually surface from the accessor bounds check
        # ("the file may be truncated") -- while the real problem is that this glb carries no data at all
        if not bin_:
            raise ValueError("glTF references an embedded buffer, but the file has no BIN chunk"
                             " (or the BIN chunk is empty)")
        return bin_
    if uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    p = os.path.join(base_dir or ".", uri.replace("/", os.sep))
    if not os.path.isfile(p):
        raise ValueError(
            f"glTF buffer is an external file '{uri}', not found at {p}. "
            f"Using .glb (single file) avoids this kind of problem entirely.")
    with open(p, "rb") as f:
        return f.read()


def _gl_accessor(js, bufs, i):
    """accessor -> float64 array of (count, ncomp). byteStride handled."""
    a = js["accessors"][i]
    if "sparse" in a:
        raise ValueError("glTF sparse accessors aren't implemented here (very rare). "
                         "Use another exporter, or convert to obj / ply first.")
    n = int(a["count"])
    nc = _GL_NCOMP[a["type"]]
    dt = np.dtype("<" + _GL_DTYPE[int(a["componentType"])])
    if "bufferView" not in a:                  # all-zero accessor (valid)
        out = np.zeros((n, nc), np.float64)
        return out
    bv = js["bufferViews"][int(a["bufferView"])]
    buf = bufs[int(bv.get("buffer", 0))]
    base = int(bv.get("byteOffset", 0)) + int(a.get("byteOffset", 0))
    stride = int(bv.get("byteStride", 0)) or dt.itemsize * nc
    if base + (n - 1) * stride + dt.itemsize * nc > len(buf):
        raise ValueError("glTF accessor exceeds the buffer -- the file may be truncated")
    raw = np.frombuffer(buf, np.uint8, (n - 1) * stride + dt.itemsize * nc,
                        base) if n else np.zeros(0, np.uint8)
    if n == 0:
        return np.zeros((0, nc), np.float64)
    rows = np.lib.stride_tricks.as_strided(
        raw, shape=(n, dt.itemsize * nc), strides=(stride, 1))
    vals = np.ascontiguousarray(rows).view(dt).reshape(n, nc).astype(np.float64)
    if a.get("normalized") and dt.kind in "iu":
        vals = vals / float(np.iinfo(dt).max if dt.kind == "u"
                            else np.iinfo(dt).max)
        if dt.kind == "i":
            vals = np.maximum(vals, -1.0)
    return vals


def _gl_node_matrix(node):
    if "matrix" in node:
        # glTF matrices are **column-major**. Read as row-major, the translation ends up in the wrong place,
        # while the rotation "still looks like a rotation" -- the hardest kind of error to spot
        return np.asarray(node["matrix"], np.float64).reshape(4, 4).T
    M = np.eye(4)
    if "scale" in node:
        M[:3, :3] = M[:3, :3] @ np.diag(node["scale"])
    if "rotation" in node:
        x, y, z, w = node["rotation"]           # glTF uses (x,y,z,w)
        R = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ])
        M[:3, :3] = R @ M[:3, :3]
    if "translation" in node:
        M[:3, 3] = node["translation"]
    return M


def load_glb(data, base_dir=None):
    """-> [dict(P, faces, closed, uv, N, Cd, name), ...] one per primitive."""
    js, bin_ = _glb_chunks(data)
    bufs = [_gl_buffer(js, bin_, i, base_dir)
            for i in range(len(js.get("buffers", [])))]
    meshes = js.get("meshes", [])
    nodes = js.get("nodes", [])
    out = []

    def emit(mesh_i, M, node_name):
        mesh = meshes[mesh_i]
        for pi, prim in enumerate(mesh.get("primitives", [])):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            P = _gl_accessor(js, bufs, attrs["POSITION"])
            P = P @ M[:3, :3].T + M[:3, 3]
            mode = int(prim.get("mode", 4))
            if "indices" in prim:
                idx = _gl_accessor(js, bufs,
                                   prim["indices"])[:, 0].astype(np.int64)
            else:
                idx = np.arange(len(P), dtype=np.int64)
            faces, closed = _gl_topology(mode, idx, len(P))
            N = None
            if "NORMAL" in attrs:
                A = np.linalg.inv(M[:3, :3]).T      # normals use the inverse transpose
                N = _gl_accessor(js, bufs, attrs["NORMAL"]) @ A.T
            uv = _gl_accessor(js, bufs, attrs["TEXCOORD_0"]) \
                if "TEXCOORD_0" in attrs else None
            if uv is not None:
                # glTF's uv origin is at the texture's top left (v down); this package, like Houdini, has it at the bottom left:
                # flip back on read, Export Mesh flips again on write, so uv is unchanged on a round trip
                uv = np.column_stack([uv[:, 0], 1.0 - uv[:, 1]])
            Cd = None
            if "COLOR_0" in attrs:
                c = _gl_accessor(js, bufs, attrs["COLOR_0"])
                Cd = c[:, :3]
            nm = node_name or mesh.get("name") or f"mesh{mesh_i}"
            out.append({"P": P, "faces": faces, "closed": closed,
                        "uv": uv, "N": N, "Cd": Cd,
                        "name": nm if len(mesh.get("primitives", [])) == 1
                        else f"{nm}.{pi}"})

    def walk(i, parent):
        node = nodes[i]
        M = parent @ _gl_node_matrix(node)
        if "mesh" in node:
            emit(int(node["mesh"]), M, node.get("name"))
        for c in node.get("children", []):
            walk(int(c), M)

    scenes = js.get("scenes", [])
    roots = None
    if scenes:
        si = int(js.get("scene", 0))
        if 0 <= si < len(scenes):
            roots = scenes[si].get("nodes", [])
    if roots:
        for r in roots:
            walk(int(r), np.eye(4))
    elif nodes:
        for i in range(len(nodes)):
            walk(i, np.eye(4))
    else:
        for i in range(len(meshes)):            # bare files with no scene / node
            emit(i, np.eye(4), None)
    if not out:
        raise ValueError("This glTF has no mesh with POSITION")
    return out


def _gl_topology(mode, idx, npts):
    """glTF primitive mode -> (faces, closed)."""
    if mode == 4:                                          # TRIANGLES
        k = (len(idx) // 3) * 3
        return idx[:k].reshape(-1, 3).tolist(), True
    if mode == 5:                                          # TRIANGLE_STRIP
        f = []
        for i in range(len(idx) - 2):
            a, b, c = idx[i], idx[i + 1], idx[i + 2]
            f.append([int(a), int(b), int(c)] if i % 2 == 0
                     else [int(b), int(a), int(c)])         # keep winding consistent
        return f, True
    if mode == 6:                                          # TRIANGLE_FAN
        return [[int(idx[0]), int(idx[i]), int(idx[i + 1])]
                for i in range(1, len(idx) - 1)], True
    if mode == 1:                                          # LINES
        k = (len(idx) // 2) * 2
        return idx[:k].reshape(-1, 2).tolist(), False
    if mode == 3:                                          # LINE_STRIP
        return ([idx.tolist()] if len(idx) >= 2 else []), False
    if mode == 2:                                          # LINE_LOOP
        return ([idx.tolist()] if len(idx) >= 2 else []), True
    if mode == 0:                                          # POINTS
        return [], True
    raise ValueError(f"Unrecognized glTF primitive mode {mode}")


# ══════════════════════════════════════════════════════════════ assembly
def _rot_up(P, mode):
    """Z-up <-> Y-up. Rotate -+90 deg about X: a pure permutation + negation, **no floating-point error**."""
    if mode == "as_is" or P is None or not len(P):
        return P
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    if mode == "z_up_to_y_up":
        return np.stack([x, z, -y], 1)
    if mode == "y_up_to_z_up":
        return np.stack([x, -z, y], 1)
    raise ValueError(f"up_axis must be one of {UP_AXES}")


def _build(P, faces, closed, *, uv_point=None, uv_corner=None, uv_table=None,
           N_point=None, N_corner=None, N_table=None, Cd=None,
           names=None, materials=None, extra=None) -> Geometry:
    """
    The unified assembly point. All parsers converge here, so the placement rules for uv / normals / colors
    exist only once -- written separately in three parsers, they'd drift sooner or later.
    """
    P = np.asarray(P, np.float64).reshape(-1, 3)
    g = Geometry(len(P))
    g.set(POINT, "P", P, dtype=np.float32, owned=True)
    if faces:
        flat, offs = [], [0]
        for f in faces:
            flat.extend(int(x) for x in f)
            offs.append(len(flat))
        vp = np.asarray(flat, np.int64)
        if len(vp) and (vp.min() < 0 or vp.max() >= len(P)):
            bad = int(vp.max()) if vp.max() >= len(P) else int(vp.min())
            raise ValueError(
                f"A primitive references a nonexistent point (point number {bad}, {len(P)} points in total). "
                f"The file is broken, or the indices aren't 0-based.")
        cl = np.asarray(closed, bool) if isinstance(closed, (list, np.ndarray)) \
            else np.full(len(faces), bool(closed))
        g.set_topology(vp.astype(np.int32), np.asarray(offs, np.int32),
                       prim_closed=cl,
                       prim_type=np.full(len(faces), PRIM_POLY, np.uint8))
    if Cd is not None and len(Cd) == len(P):
        g.set(POINT, "Cd", np.clip(np.asarray(Cd, np.float64), 0.0, 1.0),
              dtype=np.float32, owned=True)
    # uv / N: per-corner ones are expanded to vertices, per-point ones are also expanded to vertices (see item 3 in the module header)
    for name, pt, corner, table, ncomp in (
            ("uv", uv_point, uv_corner, uv_table, 2),
            ("N", N_point, N_corner, N_table, 3)):
        if g.nvertices == 0:
            if pt is not None and len(pt) == len(P):
                g.set(POINT, name, pt, dtype=np.float32, owned=True)
            continue
        if corner is not None and table is not None and len(table):
            flat = [i for row in corner for i in row]
            ci = np.asarray(flat, np.int64)
            if len(ci) != g.nvertices:
                continue
            vals = np.zeros((g.nvertices, ncomp), np.float64)
            ok = (ci >= 0) & (ci < len(table))
            vals[ok] = table[ci[ok]]
            g.set(VERTEX, name, vals, dtype=np.float32, owned=True)
        elif pt is not None and len(pt) == len(P):
            g.set(VERTEX, name, np.asarray(pt, np.float64)[g.vertex_point],
                  dtype=np.float32, owned=True)
    if names and g.nprims == len(names) and any(names):
        g.set_string(PRIM, "name", names)
    if materials and g.nprims == len(materials) and any(materials):
        g.set_string(PRIM, "material", materials)
    for k, v in (extra or {}).items():
        v = np.asarray(v, np.float64)
        if len(v) == len(P):
            g.set(POINT, k, v, dtype=np.float32, owned=True)
    return g


# ══════════════════════════════════════════════════════════ PLY -> geometry
# PLY attribute names vary by vendor. On the left, names that may appear in the file; on the right, this package's attributes
_PLY_UV = (("s", "t"), ("u", "v"), ("texture_u", "texture_v"))
_PLY_SKIP = {"x", "y", "z", "nx", "ny", "nz", "red", "green", "blue",
             "alpha", "diffuse_red", "diffuse_green", "diffuse_blue"}


def _ply_to_geo(d, splat_color=True, keep_extra=True):
    p = d["props"]
    for k in ("x", "y", "z"):
        if k not in p:
            raise ValueError("PLY has no x/y/z properties; can't read point positions")
    P = np.stack([p["x"], p["y"], p["z"]], 1)
    N = np.stack([p["nx"], p["ny"], p["nz"]], 1) \
        if all(k in p for k in ("nx", "ny", "nz")) else None
    Cd = None
    for r, gr, b in (("red", "green", "blue"),
                     ("diffuse_red", "diffuse_green", "diffuse_blue")):
        if all(k in p for k in (r, gr, b)):
            c = np.stack([p[r], p[gr], p[b]], 1)
            # uchar stores 0-255, float stores 0-1. The criterion is "are there values greater than 1"
            Cd = c / 255.0 if c.max() > 1.0 else c
            break
    uv = None
    for a, b in _PLY_UV:
        if a in p and b in p:
            uv = np.stack([p[a], p[b]], 1)
            break
    extra = {}
    if keep_extra:
        used = set(_PLY_SKIP) | {a for pair in _PLY_UV for a in pair}
        for k, v in p.items():
            if k in used or ":" in k:
                continue
            extra[k.replace(".", "_")] = v.reshape(-1, 1)
    # 3DGS .ply: f_dc_* are degree-0 spherical harmonic **coefficients**, not colors. One conversion makes them directly viewable
    if splat_color and Cd is None \
            and all(f"f_dc_{i}" in p for i in range(3)):
        Cd = np.stack([p[f"f_dc_{i}"] for i in range(3)], 1) * SH_C0 + 0.5
    faces = d["faces"]
    g = _build(P, faces, True, uv_point=uv, N_point=N, Cd=Cd, extra=extra)
    if d["edges"]:
        pairs = np.asarray([r[:2] for r in d["edges"] if len(r) >= 2], np.int32)
        if len(pairs):
            g.set_edge_group("ply_edges", pairs)
    return g


# ═══════════════════════════════════════════════════════════ LAS / LAZ (pcg122)
# LiDAR point clouds. Uncompressed .las (point formats 0-3 and 6-8, LAS 1.0-1.4) is read here with numpy -- no
# dependency. Compressed .laz needs the optional `laspy` package (with a LAZ backend: `pip install laspy[lazrs]`).
# Coordinates are integers x scale + offset; survey data sits at UTM-sized numbers (500 000 m) that float32 P cannot
# hold to the centimetre, so when any coordinate exceeds RECENTER_ABOVE the cloud is moved to the rounded centre of
# its bounding box and that origin is kept in the detail attribute las_origin (float64): world = P + las_origin.
# LAS is Z-up by convention -- use up_axis = z_up_to_y_up for the Y-up viewport.
RECENTER_ABOVE = 1e4

_LAS_BASE = {   # point format -> [(name, dtype, byte offset)] after X Y Z (i4 each, offsets 0 / 4 / 8)
    0: [("intensity", "<u2", 12), ("_ret", "u1", 14), ("classification", "u1", 15),
        ("scan_angle", "i1", 16), ("user_data", "u1", 17), ("point_source_id", "<u2", 18)],
    6: [("intensity", "<u2", 12), ("_ret6", "u1", 14), ("_flags6", "u1", 15), ("classification", "u1", 16),
        ("user_data", "u1", 17), ("scan_angle", "<i2", 18), ("point_source_id", "<u2", 20), ("gps_time", "<f8", 22)],
}
_LAS_FMT = {0: (0, None, None), 1: (0, 20, None), 2: (0, None, 20), 3: (0, 20, 28),
            6: (6, None, None), 7: (6, None, 30), 8: (6, None, 30)}
_LAS_MIN_LEN = {0: 20, 1: 28, 2: 26, 3: 34, 6: 30, 7: 36, 8: 38}


def load_las(data):
    """bytes -> {"P": (n,3) float64 world coordinates, "attrs": {name: (n,k)}, "Cd": (n,3) or None, "format": int}."""
    buf = memoryview(data)
    if bytes(buf[:4]) != b"LASF":
        raise ValueError("not a LAS file (no LASF signature)")
    vmaj, vmin = buf[24], buf[25]
    off_pts = struct.unpack_from("<I", buf, 96)[0]
    fmt_raw = buf[104]
    rec_len = struct.unpack_from("<H", buf, 105)[0]
    n = struct.unpack_from("<I", buf, 107)[0]
    scale = np.array(struct.unpack_from("<3d", buf, 131))
    offset = np.array(struct.unpack_from("<3d", buf, 155))
    if (vmaj, vmin) >= (1, 4) and len(buf) >= 255:
        n14 = struct.unpack_from("<Q", buf, 247)[0]
        if n14:
            n = n14
    fmt = fmt_raw & 0x3F
    if fmt_raw & 0x80 or fmt_raw & 0x40:
        return _load_laz(data)                      # LAZ sets the high bits of the point format
    if fmt not in _LAS_FMT:
        raise ValueError(f"LAS point format {fmt} is not supported (0-3, 6-8 are)")
    if rec_len < _LAS_MIN_LEN[fmt]:
        raise ValueError(f"LAS record length {rec_len} too short for point format {fmt}")
    if off_pts + n * rec_len > len(buf):
        raise ValueError("LAS file is truncated")
    base, gps_at, rgb_at = _LAS_FMT[fmt]
    fields = [("X", "<i4", 0), ("Y", "<i4", 4), ("Z", "<i4", 8)] + _LAS_BASE[base]
    if gps_at is not None:
        fields.append(("gps_time", "<f8", gps_at))
    if rgb_at is not None:
        fields += [("red", "<u2", rgb_at), ("green", "<u2", rgb_at + 2), ("blue", "<u2", rgb_at + 4)]
    if fmt == 8:
        fields.append(("nir", "<u2", 36))
    dt = np.dtype({"names": [f[0] for f in fields], "formats": [f[1] for f in fields],
                   "offsets": [f[2] for f in fields], "itemsize": rec_len})
    rec = np.frombuffer(data, dt, count=n, offset=off_pts)
    P = np.stack([rec["X"], rec["Y"], rec["Z"]], 1).astype(np.float64) * scale + offset
    attrs = {}
    for nm in ("intensity", "classification", "user_data", "point_source_id", "nir"):
        if nm in dt.names:
            attrs[nm] = rec[nm].astype(np.int32)
    if "scan_angle" in dt.names:
        a = rec["scan_angle"].astype(np.float64)
        attrs["scan_angle"] = (a * 0.006 if base == 6 else a).astype(np.float32)   # 1.4 stores 0.006 deg units
    if "_ret" in dt.names:
        attrs["return_number"] = (rec["_ret"] & 7).astype(np.int32)
        attrs["number_of_returns"] = ((rec["_ret"] >> 3) & 7).astype(np.int32)
    if "_ret6" in dt.names:
        attrs["return_number"] = (rec["_ret6"] & 15).astype(np.int32)
        attrs["number_of_returns"] = ((rec["_ret6"] >> 4) & 15).astype(np.int32)
    if "gps_time" in dt.names:
        attrs["gps_time"] = rec["gps_time"].astype(np.float64)
    Cd = None
    if "red" in dt.names:
        c = np.stack([rec["red"], rec["green"], rec["blue"]], 1).astype(np.float64)
        Cd = c / (255.0 if c.max(initial=0) <= 255 else 65535.0)   # the spec says 16 bit; some writers store 8
    return {"P": P, "attrs": attrs, "Cd": Cd, "format": int(fmt)}


def _load_laz(data):
    try:
        import io
        import laspy
    except ImportError:
        raise ImportError("Reading .laz (compressed LAS) needs the optional laspy package: "
                          "pip install \"laspy[lazrs]\"  (uncompressed .las is read without it)") from None
    las = laspy.read(io.BytesIO(bytes(data)))
    P = np.stack([np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)], 1).astype(np.float64)
    dims = set(las.point_format.dimension_names)
    attrs = {}
    for nm in ("intensity", "classification", "user_data", "point_source_id", "return_number",
               "number_of_returns", "nir"):
        if nm in dims:
            attrs[nm] = np.asarray(las[nm]).astype(np.int32)
    for nm, out in (("scan_angle", "scan_angle"), ("scan_angle_rank", "scan_angle")):
        if nm in dims and out not in attrs:
            a = np.asarray(las[nm]).astype(np.float64)
            attrs[out] = (a * 0.006 if nm == "scan_angle" else a).astype(np.float32)
    if "gps_time" in dims:
        attrs["gps_time"] = np.asarray(las.gps_time, np.float64)
    Cd = None
    if {"red", "green", "blue"} <= dims:
        c = np.stack([np.asarray(las.red), np.asarray(las.green), np.asarray(las.blue)], 1).astype(np.float64)
        Cd = c / (255.0 if c.max(initial=0) <= 255 else 65535.0)
    return {"P": P, "attrs": attrs, "Cd": Cd, "format": int(las.point_format.id)}


def _las_to_geo(d, keep_extra=True):
    P = d["P"]
    origin = np.zeros(3)
    if len(P) and np.abs(P).max() > RECENTER_ABOVE:
        origin = np.round((P.min(0) + P.max(0)) / 2)
    g = Geometry(len(P))
    g.set(POINT, "P", (P - origin).astype(np.float32), owned=True)
    if d["Cd"] is not None:
        g.set(POINT, "Cd", d["Cd"].astype(np.float32), owned=True)
    if keep_extra:
        for k, v in d["attrs"].items():
            g.set(POINT, k, np.asarray(v).reshape(len(P), -1), owned=True)
    from .core import DETAIL
    g.set(DETAIL, "las_origin", origin.reshape(1, 3).astype(np.float64), owned=True)
    return g


# ══════════════════════════════════════════════════════════════ entry point
def _weld(g, mode, rel=WELD_REL):
    """
    Weld points. The tolerance is **relative to the bounding box diagonal** -- an absolute tolerance would weld a small model
    entirely into one point, and on a large model wouldn't weld any point (hit in the Voronoi 2D batch).
    """
    if mode == "off" or g.npoints == 0:
        return g, 0.0
    mn, mx = g.bbox()
    span = float(np.linalg.norm(np.asarray(mx, np.float64)
                                - np.asarray(mn, np.float64)))
    tol = max(span * rel, 1e-9)
    before = g.npoints
    g = _ops.fuse(g, tol)
    return g, (before - g.npoints)


def load(path=None, data=None, fmt="auto", weld="auto", weld_rel=WELD_REL,
         up_axis="as_is", scale=1.0, flip_winding=False, merge=True,
         splat_color=True, keep_extra=True):
    """
    Read a mesh / point cloud file -> (Geometry, info string).

    weld="auto": STL welds, others don't. See item 2 in the module header for why.
    With merge=False only the first of several glTF primitives is taken (to process them individually, group by
    the `name` prim attribute).
    """
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    if weld not in WELD_MODES:
        raise ValueError(f"weld must be one of {WELD_MODES}")
    if data is None:
        if not path:
            raise ValueError("Give either path or data")
        with open(path, "rb") as f:
            data = f.read()
    if not data:
        raise ValueError(f"File is empty: {path}")
    kind = sniff(data, path or "") if fmt == "auto" else fmt
    base_dir = os.path.dirname(os.path.abspath(path)) if path else None

    parts = []
    if kind == "obj":
        d = load_obj(data.decode("utf-8", "replace")
                     if isinstance(data, (bytes, bytearray)) else data)
        parts.append(_build(
            d["P"], d["faces"], d["closed"],
            uv_corner=d["uv_corner"], uv_table=d["uv"],
            N_corner=d["n_corner"], N_table=d["N"], Cd=d["Cd"],
            names=d["names"], materials=d["materials"]))
    elif kind == "ply":
        parts.append(_ply_to_geo(load_ply(data), splat_color, keep_extra))
    elif kind == "stl":
        P, faces = load_stl(data)
        parts.append(_build(P, faces, True))
    elif kind == "las":
        parts.append(_las_to_geo(load_las(data), keep_extra))
    else:
        chunks = load_glb(data, base_dir)
        if not merge:
            chunks = chunks[:1]
        for c in chunks:
            g = _build(c["P"], c["faces"], c["closed"], uv_point=c["uv"],
                       N_point=c["N"], Cd=c["Cd"],
                       names=[c["name"]] * len(c["faces"]))
            parts.append(g)
    g = _ops.merge(*parts) if len(parts) > 1 else parts[0]

    welded = 0
    if weld == "on" or (weld == "auto" and kind == "stl"):
        g, welded = _weld(g, "on", weld_rel)
    if up_axis != "as_is":
        g.set(POINT, "P", _rot_up(np.asarray(g.get(POINT, "P"), np.float64),
                                  up_axis), dtype=np.float32, owned=True)
        for cls, nm in ((POINT, "N"), (VERTEX, "N")):
            if g.has(cls, nm):
                g.set(cls, nm, _rot_up(np.asarray(g.get(cls, nm), np.float64),
                                       up_axis), dtype=np.float32, owned=True)
    if scale != 1.0:
        g.set(POINT, "P",
              np.asarray(g.get(POINT, "P"), np.float64) * float(scale),
              dtype=np.float32, owned=True)
    if flip_winding and g.nprims:
        g = _ops.reverse_prims(g, mode="reverse")
    info = (f"{kind}  points {g.npoints}  prims {g.nprims}"
            + (f"  welded -{int(welded)}" if welded else "")
            + (f"  uv({'vertex' if g.has(VERTEX, 'uv') else 'point'})"
               if (g.has(VERTEX, "uv") or g.has(POINT, "uv")) else "")
            + ("  N" if (g.has(POINT, "N") or g.has(VERTEX, "N")) else "")
            + ("  Cd" if g.has(POINT, "Cd") else ""))
    return g, info


# ════════════════════════════════════════════ in-memory objects from the ComfyUI 3D ecosystem
def from_object(obj, weld="off", weld_rel=WELD_REL, up_axis="as_is",
                scale=1.0, flip_winding=False):
    """
    In-memory meshes passed from other 3D plugins -> Geometry. **Duck-typed, imports nothing.**

    Accepts these:
      - objects with .vertices / .faces (trimesh.Trimesh and the various wrappers imitating it)
      - {"vertices": ..., "faces": ...} dicts (v/f, verts/faces accepted too)
      - lists of the above two (several meshes -> merged)

    It isn't written as `isinstance(obj, trimesh.Trimesh)` because the mesh classes of the various 3D plugins
    are all over the place (some have their own Mesh class, some are dataclasses), but they all have
    vertices / faces. Duck typing accepts a much wider range, and adds no dependency to this plugin.

    torch tensors are accepted too: anything with .detach().cpu().numpy() is converted to numpy first.
    """
    if isinstance(obj, (list, tuple)):
        parts = [from_object(o, "off", weld_rel) for o in obj if o is not None]
        if not parts:
            raise ValueError("The list of meshes passed in is empty")
        g = _ops.merge(*parts) if len(parts) > 1 else parts[0]
    else:
        V, F, C = _duck(obj)
        g = _build(V, F, True, Cd=C)
    if weld == "on":
        g, _ = _weld(g, "on", weld_rel)
    if up_axis != "as_is":
        g.set(POINT, "P", _rot_up(np.asarray(g.get(POINT, "P"), np.float64),
                                  up_axis), dtype=np.float32, owned=True)
    if scale != 1.0:
        g.set(POINT, "P",
              np.asarray(g.get(POINT, "P"), np.float64) * float(scale),
              dtype=np.float32, owned=True)
    if flip_winding and g.nprims:
        g = _ops.reverse_prims(g, mode="reverse")
    return g


def _np(a):
    """torch tensors / various arrays -> numpy."""
    if a is None:
        return None
    for meth in ("detach", "cpu", "numpy"):
        if hasattr(a, meth):
            try:
                a = getattr(a, meth)()
            except TypeError:
                pass
    return np.asarray(a)


def _duck(obj):
    """-> (vertices, faces, colors). When unrecognized, the error must state which names were tried."""
    def pick(*names):
        for n in names:
            if isinstance(obj, dict):
                if n in obj:
                    return obj[n]
            elif hasattr(obj, n):
                return getattr(obj, n)
        return None

    V = _np(pick("vertices", "verts", "v", "points", "P"))
    F = _np(pick("faces", "f", "triangles", "indices"))
    C = _np(pick("vertex_colors", "colors", "Cd"))
    if V is None or not len(np.asarray(V).reshape(-1)):
        raise ValueError(
            "Can't find vertices in this object. Names tried: vertices / verts / v / "
            "points / P. If it's another 3D plugin's mesh type, write it out with that plugin's export node as "
            ".glb / .obj first, then read it with the filename mode.")
    V = np.asarray(V, np.float64).reshape(-1, 3)
    if F is None:
        F = np.zeros((0, 3), np.int64)
    F = np.asarray(F, np.int64).reshape(-1, 3) if np.asarray(F).size else []
    faces = [list(map(int, r)) for r in F] if len(F) else []
    if C is not None and len(C):
        C = np.asarray(C, np.float64).reshape(len(V), -1)[:, :3]
        if C.max() > 1.0:
            C = C / 255.0
    else:
        C = None
    return V, faces, C


# ═════════════════════════════════════════════════════════════ path resolution
def input_roots():
    """ComfyUI's input / output directories + the current directory. Works even without folder_paths."""
    roots = []
    try:
        import folder_paths
        roots.append(folder_paths.get_input_directory())
        roots.append(folder_paths.get_output_directory())
    except Exception:
        roots.append(os.path.abspath("input"))
        roots.append(os.path.abspath("output"))
    roots.append(os.path.abspath("."))
    return [r for r in roots if r]


def resolve(path):
    """
    Relative paths are searched in input / output / current directory, in that order.

    When not found, **list every path tried**. Saying only "file does not exist", users in
    ComfyUI have no idea what the relative path is relative to -- this is the most common sticking point with this kind of node.
    """
    p = str(path or "").strip().strip('"')
    if not p:
        raise ValueError("filename is empty")
    p = os.path.expanduser(p)
    if os.path.isabs(p):
        if os.path.isfile(p):
            return p
        raise ValueError(f"File does not exist: {p}")
    tried = []
    for r in input_roots():
        full = os.path.normpath(os.path.join(r, p))
        tried.append(full)
        if os.path.isfile(full):
            return full
    raise ValueError("File '" + p + "' not found. Locations tried:\n  "
                     + "\n  ".join(tried)
                     + "\n(you can also enter an absolute path)")
