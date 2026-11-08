"""
Mesh export (pcg84): glTF 2.0 (.glb) and OBJ, with UV / normals / tangents / vertex colors, split by attribute.

The original Export Mesh: OBJ wrote only points and faces, GLB via trimesh also only points and faces -- UVs and normals all lost,
so nothing could be texture-mapped in an engine. Anything an asset pipeline exports needs at least:

  UV            uv on vertices (one copy for each side of a seam); uv on points is accepted too
  normals       vertex N (hard edges) > point N > area-weighted point normals computed on the spot
  tangents      **the same scheme COP Bake Textures uses to bake normal maps** (corner_frames):
                each triangle computes dP/du from uv, accumulated onto corners with "the same point + same uv + same normal",
                Gram-Schmidt against the normal, w = bitangent handedness. When the engine imports with "use tangents from
                file", the baked tangent-space normal map matches pixel for pixel
  vertex color  Cd (vertex / point / prim all accepted; prim values are spread onto corners)
  material slots if prims have a string attribute material, primitives are split by it, one material slot per value (glTF
                material name / OBJ usemtl); the engine matches materials by name on import
  splitting     Split Attribute names a prim attribute (string or integer): one mesh + one
                node per value (named by that value -- LOD and collision naming conventions rely on it); if File Attribute is given,
                one file per value of it is written, filename_value.glb ({name} in the file name is replaced by the value,
                with no extra suffix; one file per rock, with
                one node each for LOD0 / LOD1 / LOD2 / collision inside)

textures (pcg84) Textures has one `slot = path` per line; slot is basecolor / normal / orm / emissive; paths are relative to
                the exported file and may contain {material} (replaced by the material slot name):
                    basecolor = T_{material}_BaseColor.png
                    normal    = T_{material}_Normal.png
                    orm       = T_{material}_ORM.png
                written as external images (uri) in glTF, so textures attach directly when Blender / three.js / engines import the glb;
                per glTF convention orm is used as both occlusion (R) and metallicRoughness (G roughness,
                B metallic) -- the same channel order as the ORM packed by COP Write File; normal must be
                the OpenGL (+Y) one. Texture Materials only attaches to material slots whose names match (space-separated
                wildcards, default *); other slots only get color factors. OBJ additionally writes a .mtl of the same name (map_Kd / norm).
                Doesn't check whether the images exist (the node writing the textures in the same graph doesn't necessarily run first)

glTF by spec is Y-up, right-handed, meters; the UV origin is at the **top left**, while here (as in Houdini) it's at the bottom left,
so v -> 1 - v on write. OBJ's UV origin is at the bottom left, written as is. Triangulation borrows Divide's ear clipping (correct for concave polygons
too); OBJ keeps the original polygons, not triangulated.
"""
from __future__ import annotations

import json
import os
import struct

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string


# ═══════════════════════════════════════════════════════════ per-corner normals / tangents
def corner_normals(geo):
    """(NV, 3) per-corner normals: vertex N > point N > area-weighted point normals computed on the spot."""
    vn = geo.get(VERTEX, "N")
    if vn is not None and vn.shape[1] >= 3:
        N = np.asarray(vn[:, :3], np.float64)
    else:
        pn = geo.get(POINT, "N")
        if pn is None or pn.shape[1] < 3:
            from .ops import compute_normals
            pn = compute_normals(geo, add_to="point").get(POINT, "N")
        N = np.asarray(pn[:, :3], np.float64)[geo.vertex_point]
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    bad = ln[:, 0] < 1e-8
    if bad.any():
        # the incoming N contains zero vectors (newly created points from convex hull, boolean etc. can't interpolate normals): compute these corners on the spot
        from .ops import compute_normals
        fresh = np.asarray(compute_normals(geo, add_to="point").get(POINT, "N"),
                           np.float64)[geo.vertex_point]
        N[bad] = fresh[bad]
        ln = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.where(ln < 1e-12, 1.0, ln)


def corner_uv(geo, name="uv"):
    a = geo.get(VERTEX, name)
    if a is not None and a.shape[1] >= 2:
        return np.asarray(a[:, :2], np.float64)
    p = geo.get(POINT, name)
    if p is not None and p.shape[1] >= 2:
        return np.asarray(p[:, :2], np.float64)[geo.vertex_point]
    return None


def _wedges(geo, *cols):
    """Group corners by (point number, all columns bitwise equal). Returns (NV,) group ids and the group count."""
    parts = [geo.vertex_point.astype(np.float64)[:, None]]
    for c in cols:
        if c is not None:
            parts.append(np.round(np.asarray(c, np.float64), 7))
    key = np.ascontiguousarray(np.concatenate(parts, 1))
    _, inv = np.unique(key.view(np.dtype((np.void, key.dtype.itemsize * key.shape[1]))),
                       return_inverse=True)
    inv = inv.reshape(-1)
    return inv, int(inv.max()) + 1 if len(inv) else 0


def corner_frames(geo, uv_name="uv", tri=None, cor=None):
    """
    Per-corner (N (NV,3), T (NV,4)). T's xyz is perpendicular to N and unit length; w = +-1 is the bitangent handedness:
    B = w * (N x T). Without uv, T is 0.

    Approach (same idea as MikkTSpace, but without its angle weighting and degenerate splitting): each triangle computes
    dP/du, dP/dv from uv (naturally area-weighted -- just summed without normalizing), accumulated onto the same wedge
    (corners with identical point + uv + normal), then orthogonalized against N.
    """
    N = corner_normals(geo)
    uv = corner_uv(geo, uv_name)
    nv = geo.nvertices
    T4 = np.zeros((nv, 4))
    if uv is None or nv == 0:
        return N, T4
    if tri is None:
        from .spatial import tri_soup
        tri, _, cor = tri_soup(geo)
    if not len(tri):
        return N, T4
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    p0, p1, p2 = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    t0, t1, t2 = uv[cor[:, 0]], uv[cor[:, 1]], uv[cor[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = t1 - t0, t2 - t0
    det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    # don't divide by |det|: direction set by sign(det), naturally weighted by area (|e1 x e2|)
    sgn = np.where(det < 0, -1.0, 1.0)
    Tu = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * sgn[:, None]
    Bv = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * sgn[:, None]
    wid, nw = _wedges(geo, uv, N)
    accT = np.zeros((nw, 3))
    accB = np.zeros((nw, 3))
    for k in range(3):
        np.add.at(accT, wid[cor[:, k]], Tu)
        np.add.at(accB, wid[cor[:, k]], Bv)
    T = accT[wid]
    B = accB[wid]
    T = T - (T * N).sum(1, keepdims=True) * N
    ln = np.linalg.norm(T, axis=1, keepdims=True)
    bad = ln[:, 0] < 1e-12
    if bad.any():                              # corners with degenerate uv: take any direction perpendicular to N
        a = np.where(np.abs(N[bad, 0:1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
        t = a - (a * N[bad]).sum(1, keepdims=True) * N[bad]
        T[bad] = t
        ln[bad] = np.linalg.norm(t, axis=1, keepdims=True)
    T = T / ln
    w = np.sign((np.cross(N, T) * B).sum(1))
    T4[:, :3] = T
    T4[:, 3] = np.where(w == 0, 1.0, w)
    return N, T4


def _corner_color(geo):
    for cls in (VERTEX, POINT, PRIM):
        a = geo.get(cls, "Cd")
        if a is None or is_string(a):
            continue
        a = np.asarray(a, np.float64)
        if a.shape[1] == 1:
            a = np.repeat(a, 3, 1)
        a = a[:, :4]
        if cls == VERTEX:
            return a
        if cls == POINT:
            return a[geo.vertex_point]
        return a[geo.vertex_prim()]
    return None


def _split_values(geo, attr):
    """(nprims,) per-primitive split key (string), and the key table in order of appearance."""
    if not str(attr).strip():
        return np.zeros(geo.nprims, np.int64), ["mesh"]
    a = geo.get(PRIM, attr)
    if a is None:
        raise KeyError(f"Split Attribute: prims have no '{attr}'")
    if is_string(a):
        vals = [str(x) for x in np.asarray(a)[:, 0]]
    else:
        v = np.asarray(a)[:, 0]
        vals = [str(int(x)) if float(x).is_integer() else str(x) for x in v]
    order, idx = [], {}
    lab = np.zeros(geo.nprims, np.int64)
    for i, s in enumerate(vals):
        if s not in idx:
            idx[s] = len(order)
            order.append(s)
        lab[i] = idx[s]
    return lab, order


# ═══════════════════════════════════════════════════════════ glTF
def _pad4(b, fill=b"\0"):
    return b + fill * ((4 - len(b) % 4) % 4)


TEX_SLOTS = ("basecolor", "normal", "orm", "emissive")


def parse_textures(spec):
    """One 'slot = path' per line (lines starting with # are comments) -> {slot: path template}."""
    out = {}
    for ln in str(spec or "").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        if "=" not in ln:
            raise ValueError(f"Textures lines are 'slot = path'; this line has no '=': '{ln}'")
        k, v = (x.strip() for x in ln.split("=", 1))
        k = k.lower().replace("_", "").replace("basecolour", "basecolor")
        if k not in TEX_SLOTS:
            raise ValueError(f"Textures slot must be one of {TEX_SLOTS}; '{k}' is not recognized")
        if not v:
            raise ValueError(f"Textures: the path for {k} is empty")
        out[k] = v
    return out


def _tex_for(mname, textures, filt):
    """Which textures this material slot gets: {slot: path} (empty if nothing matches)."""
    import fnmatch
    if not textures or mname is None:
        return {}
    pats = str(filt or "*").split() or ["*"]
    if not any(fnmatch.fnmatchcase(mname, p) for p in pats):
        return {}
    return {k: v.replace("{material}", mname) for k, v in textures.items()}


def build_glb(geo, split_attribute="", uv_name="uv", scale=1.0,
              material_attribute="material", textures=None, texture_materials="*",
              gpu_instancing=True):
    """
    Returns glb bytes: one mesh + node per value of Split Attribute; within a mesh, split further by the prims'
    material attribute (string) into several primitives, one material slot per primitive (name = attribute value;
    the engine matches materials by name on import). Without a material attribute, one mesh gets one material, named after the mesh.

    Packed primitives (geo/packed.py) with gpu_instancing: one mesh per distinct piece, drawn by one node carrying
    EXT_mesh_gpu_instancing (TRANSLATION / ROTATION / SCALE per instance) -- 10 000 rocks are one mesh + 10 000
    transforms instead of 10 000 copies. A piece whose instances have shear (not expressible as T * R * S) is
    unpacked into ordinary geometry instead. Without gpu_instancing every packed primitive is unpacked.
    """
    from .packed import is_packed, unpack, instances
    from .core import PRIM_PACKED
    from .ops import delete_prims
    inst_meshes = []
    if is_packed(geo):
        if not gpu_instancing:
            geo = unpack(geo)[0]
        else:
            pk = geo.prim_type == PRIM_PACKED
            fallback = np.zeros(geo.nprims, bool)
            for piece, X, pts in instances(geo):
                trs = decompose_trs(X)
                if trs is None:
                    fallback[np.isin(geo.vertex_point[geo.prim_offset[:-1].astype(np.int64)], pts) & pk] = True
                    continue
                parts = _mesh_parts(piece, "", uv_name, scale, material_attribute)
                if not parts:
                    continue
                prims = [pr for _, ps in parts for pr in ps]
                T, R, S = trs
                nm = _instance_name(geo, pts, len(inst_meshes))
                inst_meshes.append((nm, prims, {"TRANSLATION": (T * float(scale)).astype("<f4"),
                                                "ROTATION": R.astype("<f4"), "SCALE": S.astype("<f4")}))
            keep = ~pk
            if fallback.any():
                geo = unpack(geo, group=_mask_group(geo, fallback))[0]
                pk = geo.prim_type == PRIM_PACKED
                keep = ~pk
            geo = delete_prims(geo, keep) if keep.any() else None
    meshes = _mesh_parts(geo, split_attribute, uv_name, scale, material_attribute) if geo is not None else []
    uv_any = geo is not None and corner_uv(geo, uv_name) is not None
    meshes = meshes + inst_meshes
    if not meshes:
        raise ValueError("No closed polygons to export (polylines aren't written to glTF)")
    tex = textures if isinstance(textures, dict) else parse_textures(textures)
    uv_any = uv_any or any("TEXCOORD_0" in a for m in inst_meshes for _, a, _ in m[1])
    return _glb(meshes, {m: _tex_for(m, tex, texture_materials)
                         for mm in meshes for m, _, _ in mm[1]} if uv_any else {})


def decompose_trs(X):
    """
    (n,4,4) column-vector matrices -> (T (n,3), R quaternions x y z w (n,4), S (n,3)), or None when any matrix has
    shear (columns not orthogonal) and so isn't T * R * S. A mirror (negative determinant) goes into a negative X scale.
    """
    from .curveframe import mat_to_quat
    X = np.asarray(X, np.float64)
    M = X[:, :3, :3]
    S = np.linalg.norm(M, axis=1)
    if (S < 1e-12).any():
        return None
    R = M / S[:, None, :]
    G = np.einsum("nji,njk->nik", R, R)
    if np.abs(G - np.eye(3)).max() > 1e-4:
        return None
    neg = np.linalg.det(R) < 0
    if neg.any():
        R[neg, :, 0] *= -1
        S[neg, 0] *= -1
    return X[:, :3, 3].copy(), mat_to_quat(R), S


def _instance_name(geo, pts, k):
    """Node name of an instanced piece: the packed points' / prims' name when they all share one, else piece{k}."""
    a = geo.get(POINT, "name")
    if a is not None and is_string(a):
        vals = {str(x) for x in np.asarray(a)[pts, 0]}
        if len(vals) == 1:
            return vals.pop()
    a = geo.get(PRIM, "name")
    if a is not None and is_string(a):
        from .core import PRIM_PACKED
        prim_of_pt = np.full(geo.npoints, -1, np.int64)
        pk = np.nonzero(geo.prim_type == PRIM_PACKED)[0]
        prim_of_pt[geo.vertex_point[geo.prim_offset[pk].astype(np.int64)]] = pk
        vals = {str(x) for x in np.asarray(a)[prim_of_pt[pts], 0]}
        if len(vals) == 1:
            return vals.pop()
    return f"piece{k}"


def _mask_group(geo, mask):
    """Prim mask -> a group expression of prim numbers (for unpack's group parameter)."""
    return " ".join(str(int(i)) for i in np.nonzero(mask)[0])


def _mesh_parts(geo, split_attribute="", uv_name="uv", scale=1.0, material_attribute="material"):
    """[(mesh name, [(material name, attributes, indices)])] for the closed polygons of geo."""
    from .spatial import tri_soup
    tri, src, cor = tri_soup(geo)
    N, T4 = corner_frames(geo, uv_name, tri, cor)
    uv = corner_uv(geo, uv_name)
    col = _corner_color(geo)
    P = np.asarray(geo.get(POINT, "P"), np.float64) * float(scale)
    lab, keys = _split_values(geo, split_attribute)
    tlab = lab[src] if len(src) else np.zeros(0, np.int64)
    mat_lab, mat_keys = (_split_values(geo, material_attribute)
                         if geo.get(PRIM, material_attribute) is not None
                         else (None, None))
    tmat = mat_lab[src] if mat_lab is not None and len(src) else None
    wid, _ = _wedges(geo, uv, N, col)
    meshes = []
    for k, key in enumerate(keys):
        prims = []
        slots = [(None, key)] if tmat is None else list(enumerate(mat_keys))
        for mi, mname in slots:
            m_ = tlab == k if mi is None else (tlab == k) & (tmat == mi)
            sel = np.nonzero(m_)[0]
            if not len(sel):
                continue
            c = cor[sel].reshape(-1)
            # wedges used by this primitive; each wedge takes its first corner as representative
            w = wid[c]
            uw, first, inv = np.unique(w, return_index=True, return_inverse=True)
            rep_c = c[first]
            attrs = {"POSITION": P[geo.vertex_point[rep_c]].astype("<f4"),
                     "NORMAL": N[rep_c].astype("<f4")}
            if uv is not None:
                t = uv[rep_c].copy()
                t[:, 1] = 1.0 - t[:, 1]
                attrs["TEXCOORD_0"] = t.astype("<f4")
                attrs["TANGENT"] = T4[rep_c].astype("<f4")
            if col is not None:
                cc = col[rep_c]
                if cc.shape[1] == 3:
                    cc = np.concatenate([cc, np.ones((len(cc), 1))], 1)
                attrs["COLOR_0"] = np.clip(cc, 0, 1).astype("<f4")
            prims.append((mname, attrs, inv.reshape(-1).astype("<u4")))
        if prims:
            meshes.append((key, prims))
    return meshes


def _material(mname, tex, tex_index):
    """One glTF material. tex = {slot: uri}; tex_index(uri) -> texture index."""
    pbr = {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 1.0}
    m = {"name": mname, "pbrMetallicRoughness": pbr}
    if "basecolor" in tex:
        pbr["baseColorTexture"] = {"index": tex_index(tex["basecolor"])}
    if "orm" in tex:
        # factors multiply the textures: the metallic factor must be 1, otherwise the texture's metallic gets multiplied to 0
        pbr["metallicFactor"] = 1.0
        i = tex_index(tex["orm"])
        pbr["metallicRoughnessTexture"] = {"index": i}
        m["occlusionTexture"] = {"index": i}
    if "normal" in tex:
        m["normalTexture"] = {"index": tex_index(tex["normal"])}
    if "emissive" in tex:
        m["emissiveTexture"] = {"index": tex_index(tex["emissive"])}
        m["emissiveFactor"] = [1.0, 1.0, 1.0]
    return m


def _uri(path):
    from urllib.parse import quote
    return quote(str(path).replace("\\", "/"), safe="/._-~")


def _glb(meshes_in, mat_tex=None):
    bin_, views, accs, meshes, nodes, mats = b"", [], [], [], [], []
    images, textures, img_index = [], [], {}
    mat_index = {}
    mat_tex = mat_tex or {}

    def tex_index(path):
        u = _uri(path)
        if u not in img_index:
            img_index[u] = len(images)
            images.append({"uri": u})
            textures.append({"sampler": 0, "source": img_index[u]})
        return img_index[u]
    types = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4"}

    def add(arr, target, minmax=False):
        nonlocal bin_
        off = len(bin_)
        bin_ = _pad4(bin_ + arr.tobytes())
        v = {"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes}
        if target:
            v["target"] = target
        views.append(v)
        a = {"bufferView": len(views) - 1, "count": int(arr.shape[0]),
             "componentType": 5126 if arr.dtype.kind == "f" else 5125,
             "type": types[1 if arr.ndim == 1 else arr.shape[1]]}
        if minmax:
            a["min"] = [float(x) for x in arr.min(0)]
            a["max"] = [float(x) for x in arr.max(0)]
        accs.append(a)
        return len(accs) - 1

    inst_used = False
    for item in meshes_in:
        key, prims = item[0], item[1]
        inst = item[2] if len(item) > 2 else None
        plist = []
        for mname, attrs, idx in prims:
            if mname not in mat_index:
                mat_index[mname] = len(mats)
                mats.append(_material(mname, mat_tex.get(mname, {}), tex_index))
            prim = {"attributes": {}, "mode": 4, "material": mat_index[mname]}
            for name, arr in attrs.items():
                prim["attributes"][name] = add(arr, 34962, name == "POSITION")
            prim["indices"] = add(idx, 34963)
            plist.append(prim)
        meshes.append({"name": key, "primitives": plist})
        node = {"name": key, "mesh": len(meshes) - 1}
        if inst is not None:
            node["extensions"] = {"EXT_mesh_gpu_instancing": {"attributes": {
                k: add(np.ascontiguousarray(v), None) for k, v in inst.items()}}}
            inst_used = True
        nodes.append(node)
    js = {"asset": {"version": "2.0", "generator": "comfyui_pcg"},
          "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
          "nodes": nodes, "meshes": meshes, "materials": mats,
          "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(bin_)}]}
    if inst_used:
        js["extensionsUsed"] = ["EXT_mesh_gpu_instancing"]
    if images:
        # 10497 = REPEAT, 9987 / 9729 = trilinear / linear
        js.update(images=images, textures=textures,
                  samplers=[{"magFilter": 9729, "minFilter": 9987,
                             "wrapS": 10497, "wrapT": 10497}])
    jb = _pad4(json.dumps(js, separators=(",", ":")).encode(), b" ")
    total = 12 + 8 + len(jb) + 8 + len(bin_)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<I", len(jb)) + b"JSON" + jb
            + struct.pack("<I", len(bin_)) + b"BIN\0" + bin_)


# ═══════════════════════════════════════════════════════════ OBJ
def build_mtl(names, textures=None, texture_materials="*"):
    """OBJ .mtl: one newmtl per material slot; slots with textures get map_Kd / norm (orm has no standard
    keyword, so it's written as a comment + map_Pr / map_Pm for roughness / metallic, the PBR extension)."""
    tex = textures if isinstance(textures, dict) else parse_textures(textures)
    lines = ["# comfyui_pcg"]
    for m in names:
        t = _tex_for(m, tex, texture_materials)
        lines += [f"newmtl {m}", "Kd 1 1 1", "Ks 0 0 0", "illum 1"]
        if "basecolor" in t:
            lines.append(f"map_Kd {t['basecolor']}")
        if "normal" in t:
            lines.append(f"norm {t['normal']}")
        if "orm" in t:
            lines.append(f"# ORM: R = AO, G = roughness, B = metallic  {t['orm']}")
        if "emissive" in t:
            lines.append(f"map_Ke {t['emissive']}")
        lines.append("")
    return "\n".join(lines)


def build_obj(geo, split_attribute="", uv_name="uv", scale=1.0, mtllib=None):
    """Returns OBJ text. Polygons as is (not triangulated), one o block per value of Split Attribute."""
    N = corner_normals(geo)
    uv = corner_uv(geo, uv_name)
    P = np.asarray(geo.get(POINT, "P"), np.float64) * float(scale)
    lab, keys = _split_values(geo, split_attribute)
    po = geo.prim_offset
    closed = geo.prim_closed

    def one(sel_keys):
        lines = ["# comfyui_pcg  (uv origin at bottom left)"]
        if mtllib:
            lines.append(f"mtllib {mtllib}")
        lines += [f"v {p[0]:.9g} {p[1]:.9g} {p[2]:.9g}" for p in P]
        ti = ni = None
        if uv is not None:
            tu, ti = np.unique(np.round(uv, 9), axis=0, return_inverse=True)
            ti = ti.reshape(-1)
            lines += [f"vt {t[0]:.9g} {t[1]:.9g}" for t in tu]
        nu, ni = np.unique(np.round(N, 7), axis=0, return_inverse=True)
        ni = ni.reshape(-1)
        lines += [f"vn {n[0]:.7g} {n[1]:.7g} {n[2]:.7g}" for n in nu]
        mat = geo.get(PRIM, "material")
        mat = [str(x) for x in np.asarray(mat)[:, 0]] if mat is not None and is_string(mat) \
            else None
        for k in sel_keys:
            lines.append(f"o {keys[k]}")
            cur = None
            for f in np.nonzero(lab == k)[0]:
                if mat is not None and mat[f] != cur:
                    cur = mat[f]
                    lines.append(f"usemtl {cur}")
                cs = range(po[f], po[f + 1])
                if not closed[f]:
                    lines.append("l " + " ".join(str(geo.vertex_point[c] + 1) for c in cs))
                    continue
                if ti is not None:
                    lines.append("f " + " ".join(
                        f"{geo.vertex_point[c] + 1}/{ti[c] + 1}/{ni[c] + 1}" for c in cs))
                else:
                    lines.append("f " + " ".join(
                        f"{geo.vertex_point[c] + 1}//{ni[c] + 1}" for c in cs))
        return "\n".join(lines) + "\n"

    return one(range(len(keys)))


# ═══════════════════════════════════════════════════════════ main entry point
def export(geo, full_base, fmt="glb", split_attribute="", file_attribute="",
           scale=1.0, uv_name="uv", textures="", texture_materials="*", gpu_instancing=True):
    """
    Write files; returns the list of full paths written. full_base has no extension.
    split_attribute decides how many meshes / nodes are **inside** a file; file_attribute decides how many
    **files** (one full_base_value.ext per value). Used together: one file per rock, with
    one node each for LOD0 / LOD1 / LOD2 / collision inside.
    """
    if geo is None or geo.nprims == 0:
        raise ValueError("No primitives to export")
    from .packed import is_packed, unpack
    if is_packed(geo) and (fmt != "glb" or not gpu_instancing):
        geo = unpack(geo)[0]                          # OBJ has no instancing
    fa = str(file_attribute).strip()
    if fa:
        lab, keys = _split_values(geo, fa)
        from .ops import delete_prims
        subs = [(k, delete_prims(geo, lab == i)) for i, k in enumerate(keys)]
    else:
        subs = [(None, geo)]
    tex = parse_textures(textures)                     # parse first: if one is wrong, no file is written at all
    paths = []
    for fkey, sub in subs:
        if fkey is None:
            path = full_base
        elif "{name}" in full_base:
            path = full_base.replace("{name}", _safe(fkey))
        else:
            path = f"{full_base}_{_safe(fkey)}"
        path += "." + fmt
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if fmt == "glb":
            blob = build_glb(sub, split_attribute, uv_name, scale,
                             textures=tex, texture_materials=texture_materials,
                             gpu_instancing=gpu_instancing)
        else:
            mat = sub.get(PRIM, "material")
            mtl = None
            if mat is not None and is_string(mat):
                names = list(dict.fromkeys(str(x) for x in np.asarray(mat)[:, 0]))
                mtl = os.path.splitext(os.path.basename(path))[0] + ".mtl"
                with open(os.path.join(os.path.dirname(path), mtl), "w",
                          encoding="utf-8") as f:
                    f.write(build_mtl(names, tex, texture_materials))
            blob = build_obj(sub, split_attribute, uv_name, scale, mtllib=mtl)
        if isinstance(blob, str):
            with open(path, "w", encoding="utf-8") as f:
                f.write(blob)
        else:
            with open(path, "wb") as f:
                f.write(blob)
        paths.append(path)
    return paths


def _safe(s):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))
