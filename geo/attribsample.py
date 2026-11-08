"""
Two nodes that fetch values from other data by "coordinates": Attribute from Volume, Attribute Transfer
by UV. They differ from Attribute Transfer in that **the correspondence is not spatial proximity**:

  Attribute from Volume        by the point's world position, trilinear interpolation in a dense volume
  Attribute Transfer by UV     by uv: find in the source geometry's uv layout "which triangle the same uv falls in
                               and with which barycentric coordinates", then interpolate with those barycentric coordinates

━━ Attribute from Volume
Volume storage: see volume.py: voxel values sit on grid points (Houdini's "vertex sampling"); position of grid point k =
origin + k * voxel size, origin = centre - size / 2. Sampling:
  trilinear   interpolation of 8 grid points. Linear fields (a*x + b) are exact within a cell -- the tests check exactly this
  nearest     nearest grid point (no interpolation, blocky)
  gradient    writes a vec3: central-difference gradient of the trilinear field (step = half a voxel). On an SDF it is the
              surface normal direction with length ~ 1; use it to push points onto the surface: P -= sdf * grad
Points outside the volume: clamp (take the border value; an SDF's "outside" gets underestimated -- hence the other options) /
constant (use Outside Value) / keep (attribute not written, original value kept).
Which volume: empty Volume = the first volume prim; a number = the n-th volume (in prim order, counting only
volumes); a name = the one whose prim attribute name equals it.

━━ Attribute Transfer by UV
Typical uses:
  - moving attributes between two versions with the same UVs: Cd / masks baked on the high-poly moved onto the retopologized low-poly;
    topology, point counts and positions can be completely different as long as the UV layout is the same
  - moving P = "wrapping" one geometry onto another by UV (a pattern laid out on a plane applied to a curved surface by UV)
For each target element take its uv and find the source uv triangle **containing** it (grid bucketing + barycentric
test, with a relative tolerance on edges), then interpolate the source's point / vertex attributes by the barycentric coordinates (prim attributes take the value of the containing
face, strings take the corner with the largest weight). Elements not inside any source triangle (seams between UV islands, outside the UVs):
  nearest   use the nearest triangle in uv space (barycentric coordinates clamped onto the triangle); with Max Distance > 0
            only within that distance
  keep      not written, original value kept
When source UVs overlap (mirrored islands, stacked islands) one uv falls in several triangles -- the lowest-numbered one is taken
and **the report gives the number landing in overlap regions**, since in that case "which copy to take" has no right answer anyway.

Whether the target is written on points or vertices (Attribute Class):
  point    each point uses its uv (with uv on vertices the point's first vertex is used -- points on seams have
           different uvs on the two sides; either side maps to the same spatial position, which doesn't matter for P-like attributes, but for colour it is
           one side's colour)
  vertex   each vertex uses its own uv, the two sides of a seam each take their own, written as a vertex attribute
P is always written on points (uv taken by the point rule). Interpolated N is renormalized.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM, VERTEX, is_string, PRIM_VOLUME
from .groups import resolve
from .ops import match_names, prim_centers
from . import spatial as _sp
from .volume import volume_info

VOL_MODES = ("trilinear", "nearest", "gradient")
OUTSIDE = ("clamp", "constant", "keep")
UV_OUTSIDE = ("nearest", "keep")
CLASSES = ("point", "prim")
UV_CLASSES = ("point", "vertex")


# ═══════════════════════════════════════════════════════════ Volume
def _pick_volume(vol, which):
    vp = [i for i in range(vol.nprims) if vol.prim_type[i] == PRIM_VOLUME
          and vol.pdata(i, "voxels") is not None]
    if not vp:
        raise ValueError("The volume input has no volume prims (use Convert to turn geometry into "
                         "volume_sdf / volume_fog)")
    w = str(which).strip()
    if not w:
        return vp[0]
    if w.lstrip("-").isdigit():
        k = int(w)
        if not -len(vp) <= k < len(vp):
            raise ValueError(f"There are only {len(vp)} volumes; Volume = {k} is out of range")
        return vp[k]
    nm = vol.get(PRIM, "name")
    if nm is not None:
        for i in vp:
            if str(nm[i, 0]) == w:
                return i
    have = [str(nm[i, 0]) for i in vp] if nm is not None else []
    raise ValueError(f"No volume named '{w}'; existing names: {have or '(volumes have no name)'}")


def sample_volume(vox, origin, cell, Q, mode="trilinear", outside="clamp",
                  outside_value=0.0):
    """
    Samples a (rz,ry,rx) grid-point field. Returns (values (n,) or gradients (n,3), inside the volume (n,)).
    """
    V = np.asarray(vox, np.float64)
    rz, ry, rx = V.shape
    res = np.array([rx, ry, rz])
    u = (np.asarray(Q, np.float64) - origin) / cell           # continuous grid coordinates (x,y,z)
    inside = np.all((u >= -1e-9) & (u <= res - 1 + 1e-9), axis=1)
    uc = np.clip(u, 0, res - 1)

    def tri(uu):
        i0 = np.clip(np.floor(uu).astype(np.int64), 0, res - 2)
        t = uu - i0
        out = np.zeros(len(uu))
        for dz in (0, 1):
            wz = t[:, 2] if dz else 1 - t[:, 2]
            for dy in (0, 1):
                wy = t[:, 1] if dy else 1 - t[:, 1]
                for dx in (0, 1):
                    wx = t[:, 0] if dx else 1 - t[:, 0]
                    out += wx * wy * wz * V[i0[:, 2] + dz, i0[:, 1] + dy,
                                            i0[:, 0] + dx]
        return out

    if mode == "nearest":
        k = np.rint(uc).astype(np.int64)
        val = V[k[:, 2], k[:, 1], k[:, 0]]
    elif mode == "trilinear":
        val = tri(uc)
    else:
        g = np.zeros((len(u), 3))
        for a in range(3):
            d = np.zeros(3)
            d[a] = 0.5
            g[:, a] = (tri(np.clip(uc + d, 0, res - 1)) -
                       tri(np.clip(uc - d, 0, res - 1))) / \
                (np.clip(uc + d, 0, res - 1) - np.clip(uc - d, 0, res - 1))[:, a] \
                / cell[a]
        val = g
    if outside == "constant":
        val = val.copy()
        val[~inside] = float(outside_value)
    return val, inside


def attribute_from_volume(geo, vol, attribute="density", volume="", mode="trilinear",
                          outside="clamp", outside_value=0.0,
                          attribute_class="point", group=""):
    """Returns (geo, report)."""
    if mode not in VOL_MODES:
        raise ValueError(f"Mode must be one of {VOL_MODES}")
    if outside not in OUTSIDE:
        raise ValueError(f"Outside must be one of {OUTSIDE}")
    if attribute_class not in CLASSES:
        raise ValueError(f"Attribute Class must be one of {CLASSES}")
    name = str(attribute).strip()
    if not name:
        raise ValueError("Attribute name is empty")
    vi = _pick_volume(vol, volume)
    vox, origin, cell = volume_info(vol, vi)
    cls = POINT if attribute_class == "point" else PRIM
    Q = (np.asarray(geo.get(POINT, "P"), np.float64) if cls == POINT
         else prim_centers(geo).astype(np.float64))
    sel = resolve(geo, cls, group) if str(group).strip() else \
        np.ones(len(Q), bool)
    val, inside = sample_volume(vox, origin, cell, Q[sel], mode, outside,
                                outside_value)
    dim = 3 if mode == "gradient" else 1
    cur = geo.get(cls, name)
    if cur is not None and cur.shape[1] == dim and not is_string(cur):
        out = np.asarray(cur, np.float32).copy()
    else:
        out = np.zeros((len(Q), dim), np.float32)
    v = val.reshape(-1, dim)
    w = np.ones(len(v), bool) if outside != "keep" else inside
    idx = np.nonzero(sel)[0]
    out[idx[w]] = v[w]
    g = geo.copy()
    g.set(cls, name, out, owned=True)
    return g, {"volume_prim": int(vi), "resolution": list(vox.shape[::-1]),
               "sampled": int(sel.sum()), "outside": int((~inside).sum()),
               "mode": mode}


# ═══════════════════════════════════════════════════════════ by UV
def _uv_of(geo, name, what):
    """Returns (class, (n,2) uv). Looks on vertices first, then points."""
    for cls in (VERTEX, POINT):
        a = geo.get(cls, name)
        if a is not None and not is_string(a) and a.shape[1] >= 2:
            return cls, np.asarray(a, np.float64)[:, :2]
    raise KeyError(f"{what} has no uv attribute '{name}' (on vertex or point, at least 2-D)")


def _locate(uvq, T2):
    """
    Which triangle each uv point falls in. Returns (triangle (n,), -1 if none, barycentric (n,3), number of triangles it falls in (n,)).
    """
    n = len(uvq)
    A, B, C = T2[:, 0], T2[:, 1], T2[:, 2]
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    span = float(np.max(hi.max(0) - lo.min(0))) if len(T2) else 1.0
    ext = np.median(np.max(hi - lo, axis=1)) if len(T2) else 1.0
    h = max(float(ext), span * 1e-6, 1e-12)
    z = np.zeros((len(T2), 1))
    # No need to pad the bounding boxes: the cell a query point on a box edge floors into is always covered by the box;
    # points a hair beyond the barycentric tolerance that aren't found are caught by nearest
    bucket, big = _sp._box_bucket(np.c_[lo, z], np.c_[hi, z], h)
    cq = np.floor(np.c_[uvq, np.zeros(n)] / h).astype(np.int64)
    qi, ti = bucket.query(_sp.cell_key(cq), np.arange(n, dtype=np.int64))
    if len(big):                                     # very large triangles: paired with all queries
        qi = np.concatenate([qi, np.repeat(np.arange(n), len(big))])
        ti = np.concatenate([ti, np.tile(big, n)])
    a, b, c = A[ti], B[ti], C[ti]
    p = uvq[qi]
    v0, v1, v2 = b - a, c - a, p - a
    den = v0[:, 0] * v1[:, 1] - v0[:, 1] * v1[:, 0]
    ok = np.abs(den) > 1e-300
    dd = np.where(ok, den, 1.0)
    w1 = (v2[:, 0] * v1[:, 1] - v2[:, 1] * v1[:, 0]) / dd
    w2 = (v0[:, 0] * v2[:, 1] - v0[:, 1] * v2[:, 0]) / dd
    w0 = 1 - w1 - w2
    # Tolerance in the triangle's own scale: barycentric coordinates >= -eps
    eps = 1e-9
    inside = ok & (w0 >= -eps) & (w1 >= -eps) & (w2 >= -eps)
    qi, ti = qi[inside], ti[inside]
    W = np.c_[w0, w1, w2][inside]
    tri_of = np.full(n, -1, np.int64)
    bary = np.zeros((n, 3))
    hits = np.bincount(qi, minlength=n)
    if len(qi):
        o = np.lexsort((ti, qi))                      # per query take the lowest-numbered triangle
        qs, first = np.unique(qi[o], return_index=True)
        tri_of[qs] = ti[o][first]
        bary[qs] = W[o][first]
    return tri_of, bary, hits


def _overlap_count(hits, tri_of, bary, T2):
    """Number of queries falling in >= 2 triangles, other than just sitting on shared edges / vertices."""
    inner = (tri_of >= 0) & (bary.min(1) > 1e-6)
    return int(((hits >= 2) & inner).sum())


def attribute_transfer_by_uv(dest, source, attributes="Cd", uv="uv",
                             source_uv="", attribute_class="point",
                             outside="nearest", max_distance=0.0, group=""):
    """Returns (geo, report)."""
    if outside not in UV_OUTSIDE:
        raise ValueError(f"Outside must be one of {UV_OUTSIDE}")
    if attribute_class not in UV_CLASSES:
        raise ValueError(f"Attribute Class must be one of {UV_CLASSES}")
    suv_name = str(source_uv).strip() or str(uv).strip()
    scls, suv = _uv_of(source, suv_name, "source")
    dcls, duv = _uv_of(dest, str(uv).strip(), "target geometry")
    tri, tprim, tcorner = _sp.tri_soup(source)
    if not len(tri):
        raise ValueError("source has no polygons (finding triangles by UV needs faces)")
    T2 = suv[tcorner] if scls == VERTEX else suv[tri]          # (T,3,2)

    # Attributes to move
    cand = {}
    for cls in (POINT, VERTEX, PRIM):
        for k in source.attribs[cls]:
            if k == suv_name and cls == scls:
                continue
            cand.setdefault(k, cls)
    names = match_names(list(cand), attributes)
    if not names:
        raise ValueError(f"source has no attribute matching '{attributes}'; existing: "
                         f"{sorted(cand)}")

    # Target queries: one uv per point for the point class, one per vertex for the vertex class
    def point_uv():
        if dcls == POINT:
            return duv
        out = np.full((dest.npoints, 2), np.nan)
        vp = dest.vertex_point.astype(np.int64)
        first = np.full(dest.npoints, -1, np.int64)
        order = np.arange(len(vp))[::-1]
        first[vp[order]] = order                          # first vertex of each point
        has = first >= 0
        out[has] = duv[first[has]]
        return out

    queries = {}
    want_pt = attribute_class == "point" or "P" in names
    if want_pt:
        queries[POINT] = point_uv()
    if attribute_class == "vertex":
        queries[VERTEX] = duv if dcls == VERTEX else \
            duv[dest.vertex_point.astype(np.int64)]

    g = dest.copy()
    rep = {"attributes": names, "source_uv_class": scls, "dest_uv_class": dcls}
    for qcls, UVq in queries.items():
        n = len(UVq)
        valid = np.all(np.isfinite(UVq), axis=1)
        if qcls == POINT and str(group).strip():
            valid &= resolve(dest, POINT, group)
        vidx = np.nonzero(valid)[0]
        tq, bq, hits = _locate(UVq[vidx], T2)
        found = tq >= 0
        nearest_used = 0
        if (~found).any() and outside == "nearest":
            miss = np.nonzero(~found)[0]
            P3 = np.c_[T2.reshape(-1, 2), np.zeros(len(T2) * 3)]
            tri3 = np.arange(len(T2) * 3).reshape(-1, 3)
            ti, dist, _, bw = _sp.closest_surface(
                np.c_[UVq[vidx][miss], np.zeros(len(miss))], P3, tri3,
                float(max_distance))
            okm = ti >= 0                      # closest_surface already cut off by max_dist
            m2 = miss[okm]
            tq[m2] = ti[okm]
            bq[m2] = np.c_[1 - bw[okm].sum(1), bw[okm]]
            found[m2] = True
            nearest_used = int(okm.sum())
        rows = vidx[found]
        T = tq[found]
        Wt = bq[found]
        rep[f"{qcls}_queries"] = int(len(vidx))
        rep[f"{qcls}_inside"] = int((tq >= 0).sum() - nearest_used)
        rep[f"{qcls}_nearest"] = nearest_used
        rep[f"{qcls}_missed"] = int(len(vidx) - len(rows))
        rep[f"{qcls}_in_overlap"] = _overlap_count(hits, tq, bq, T2)
        for nm in names:
            if nm == "P" and qcls != POINT:
                continue
            if nm != "P" and qcls == POINT and attribute_class == "vertex":
                continue
            scl = cand[nm]
            src = source.get(scl, nm)
            if scl == PRIM:
                vals = src[tprim[T]]
                s_ = is_string(src)
            else:
                ids = tri[T] if scl == POINT else tcorner[T]      # (m,3)
                s_ = is_string(src)
                if s_:
                    vals = src[ids[np.arange(len(T)), Wt.argmax(1)]]
                else:
                    sv = np.asarray(src, np.float64)
                    vals = np.einsum("mk,mkc->mc", Wt, sv[ids])
            if nm == "N" and not s_ and vals.shape[1] == 3:
                ln = np.linalg.norm(vals, axis=1, keepdims=True)
                vals = np.where(ln > 1e-20, vals / np.maximum(ln, 1e-20), vals)
            cur = g.get(qcls, nm)
            if s_:
                base = (np.asarray(cur).copy() if cur is not None and is_string(cur)
                        else np.full((n, src.shape[1]), "", dtype=src.dtype))
                base = base.astype(np.result_type(base.dtype, src.dtype))
                base[rows] = vals
                g.set_string(qcls, nm, base)
            else:
                if cur is not None and not is_string(cur) and \
                        cur.shape[1] == src.shape[1]:
                    base = np.asarray(cur).astype(src.dtype).copy()
                else:
                    base = np.zeros((n, src.shape[1]), src.dtype)
                base[rows] = vals.astype(src.dtype)
                g.set(qcls, nm, base, owned=True)
    return g, rep
