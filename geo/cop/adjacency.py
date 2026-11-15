"""
Adjacency (Copernicus, Houdini 22): image processing across texture seams.

A texture of a mesh is a set of UV islands; a blur, a distortion or a simulation that runs in the image stops at
each island's edge, and the seam shows on the model. The adjacency layers record, for every texel outside an
island, which place of the *neighbouring* island (the one that shares that edge on the mesh) it stands for, so a
filter can read across the seam.

Houdini carries this in an "adjacency cable". Our COP image is multi-layer already, so Geometry to Adjacency
writes layers with a prefix (default `adj_`) into one image, and the other nodes read them from the image they
process (they must have the same resolution, as Houdini asks of the target texture):

    adj_mask      1 inside the islands (rasterised with half a texel of margin, like the bakers), else 0
    adj_uv        where to read instead: inside an island the texel's own uv; outside, within Padding texels of an
                  island edge, the uv of the point across the seam -- the continuation of the surface on the island
                  that shares the edge in 3D, at the same distance along and beyond the edge (scaled by the two
                  islands' texel densities). At a mesh border (no neighbour) the nearest point of the island's edge.
    adj_valid     1 where adj_uv points across a seam, 0 where it clamps (mesh border) or is out of reach
    adj_jac       d(adj position) / d(position), in texels, 2 x 2 (m00 m01 m10 m11): how a step here moves there
                  (the neighbour island's rotation and scale against this one). Identity inside.
    adj_near      the nearest point on the own island's edge (uv): the fallback when adj_uv lands off the mesh
    adj_tri       triangle number per texel (of geo.spatial.tri_soup), adj_bary its barycentric weights,
    adj_primid    the source primitive
    adj_P, adj_N  world position and normal; adj_tanU, adj_tanV = dP/du, dP/dv; adj_uvscale = world units per uv
                  unit (the texel density)

Houdini's cable also holds `uv_derivative`, `tangent_xform` and the geometry itself; adj_jac plays the part of the
first two, and the nodes that need the geometry (Attribute Sample) take it as an input.

Edges are matched in 3D by position (welded or not): an edge whose two triangles have different uvs along it is a
seam, an edge with one triangle is a border. One hop only: a read that crosses a seam and then leaves the
neighbour island as well falls back to the nearest edge point.
"""
from __future__ import annotations

import numpy as np

from ..core import POINT, VERTEX, PRIM

PREFIX = "adj_"
TRANSFORMS = ("world_to_tangent", "tangent_to_world")
SIGNATURES = ("rgb", "uv")


def _tex(uv, W, H):
    """uv -> texel coordinates (pixel centres at integers)."""
    return np.stack([uv[..., 0] * W - 0.5, uv[..., 1] * H - 0.5], -1)


def _boundary_edges(tri, uvc, Ppos):
    """
    Island boundary edges of a triangulated mesh. tri (T, 3) point numbers, uvc (T, 3, 2) corner uvs.
    -> a, b, opp (E, 2): the edge's uv ends and its triangle's third corner; a2, b2, opp2: the same edge on the
    neighbouring island (matched end for end), valid where partner; partner (E,) bool.
    """
    T = len(tri)
    # weld by position: a seam in a mesh with split points still shares its edge in space
    q = np.round(Ppos / max(float(np.ptp(Ppos)), 1e-12) * 1e6).astype(np.int64)
    _, pid = np.unique(q, axis=0, return_inverse=True)
    pid = pid.reshape(-1)[tri]                                      # (T, 3) welded ids
    k = np.arange(3)
    pa, pb = pid[:, k], pid[:, (k + 1) % 3]                         # (T, 3) per edge
    ua, ub, uo = uvc[:, k], uvc[:, (k + 1) % 3], uvc[:, (k + 2) % 3]
    pa, pb = pa.reshape(-1), pb.reshape(-1)
    ua, ub, uo = ua.reshape(-1, 2), ub.reshape(-1, 2), uo.reshape(-1, 2)
    lo, hi = np.minimum(pa, pb), np.maximum(pa, pb)
    key = lo * (int(pid.max()) + 1) + hi
    order = np.argsort(key, kind="stable")
    ks = key[order]
    start = np.r_[True, ks[1:] != ks[:-1]]
    gid = np.cumsum(start) - 1
    cnt = np.bincount(gid)
    E = 3 * T
    partner = np.full(E, -1, np.int64)
    two = cnt[gid] == 2
    first = order[two & start]                                      # the pair's two edges
    second = order[np.nonzero(two & start)[0] + 1]
    partner[first], partner[second] = second, first
    has = partner >= 0
    pe = np.where(has, partner, 0)
    same = pa == pa[pe]                                             # same direction, or (usually) reversed
    a2 = np.where(same[:, None], ua[pe], ub[pe])
    b2 = np.where(same[:, None], ub[pe], ua[pe])
    interior = has & (np.abs(a2 - ua).max(1) < 1e-9) & (np.abs(b2 - ub).max(1) < 1e-9)
    deg = np.abs(ub - ua).max(1) < 1e-12                            # an edge collapsed in uv bounds nothing
    keep = ~interior & ~deg
    return (ua[keep], ub[keep], uo[keep], a2[keep], b2[keep], uo[pe][keep], has[keep])


def geometry_to_adjacency(geo, xres=1024, yres=1024, uv_attrib="uv", padding=16, prefix=PREFIX, img=None):
    """Rasterise geo's uv into the adjacency layers (module docstring). img: add them to this image."""
    from ..backproject import uv_rasterize, _corner_uv
    from .pattern import _base
    from .pixel import put
    out, like = _base(img, xres, yres)
    W, H = out.xres, out.yres
    pre = str(prefix)
    rast = uv_rasterize(geo, W, H, "", uv_attrib)
    hit, bary, tri, cor, src = rast["hit"], rast["bary"], rast["tri"], rast["cor"], rast["src"]
    m = hit >= 0
    J, I = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    own = np.stack([(J + 0.5) / W, (I + 0.5) / H], -1)
    auv = own.copy()
    near = own.copy()
    jac = np.zeros((H, W, 4))
    jac[..., 0] = jac[..., 3] = 1.0
    valid = np.zeros((H, W))
    Pw = np.zeros((H, W, 3))
    Nw = np.zeros((H, W, 3))
    tU = np.zeros((H, W, 3))
    tV = np.zeros((H, W, 3))
    usc = np.zeros((H, W))
    pidl = np.full((H, W), -1.0)
    if len(tri) and m.any():
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        uvc = _corner_uv(geo, uv_attrib)[cor]                       # (T, 3, 2)
        Pt = P[tri]                                                  # (T, 3, 3)
        t = hit[m]
        b = bary[m]
        Pw[m] = (Pt[t] * b[:, :, None]).sum(1)
        E1, E2 = Pt[:, 1] - Pt[:, 0], Pt[:, 2] - Pt[:, 0]
        d1, d2 = uvc[:, 1] - uvc[:, 0], uvc[:, 2] - uvc[:, 0]
        det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        dsafe = np.where(np.abs(det) < 1e-20, 1.0, det)[:, None]
        tanU = (E1 * d2[:, 1:2] - E2 * d1[:, 1:2]) / dsafe
        tanV = (E2 * d1[:, 0:1] - E1 * d2[:, 0:1]) / dsafe
        fn = np.cross(E1, E2)
        area = np.linalg.norm(fn, axis=1)
        fn = fn / np.maximum(area, 1e-20)[:, None]
        fn = fn * np.where(det < 0, -1.0, 1.0)[:, None]             # the side the uv is laid out on
        n_attr = geo.get(POINT, "N")
        if n_attr is not None and np.asarray(n_attr).shape[1] >= 3:
            nn = (np.asarray(n_attr, np.float64)[:, :3][tri][t] * b[:, :, None]).sum(1)
            ln = np.linalg.norm(nn, axis=1, keepdims=True)
            Nw[m] = np.where(ln > 1e-12, nn / np.maximum(ln, 1e-12), fn[t])
        else:
            Nw[m] = fn[t]
        tU[m], tV[m] = tanU[t], tanV[t]
        usc[m] = np.sqrt(area[t] / np.maximum(np.abs(det[t]), 1e-20))
        pidl[m] = src[t]
        ea, eb, eo, a2, b2, o2, has = _boundary_edges(tri, uvc, P)
        outside = ~m
        if len(ea) and outside.any() and float(padding) > 0:
            from scipy.spatial import cKDTree
            A, B, O = _tex(ea, W, H), _tex(eb, W, H), _tex(eo, W, H)
            L = np.linalg.norm(B - A, axis=1)
            ns = np.maximum(np.ceil(L / 0.5).astype(np.int64), 1) + 1
            eid = np.repeat(np.arange(len(A)), ns)
            first = np.cumsum(ns) - ns
            tt = (np.arange(len(eid)) - first[eid]) / np.maximum(ns[eid] - 1, 1)
            samples = A[eid] + (B[eid] - A[eid]) * tt[:, None]
            oi, oj = np.nonzero(outside)
            q = np.stack([oj.astype(np.float64), oi.astype(np.float64)], -1)
            dist, k = cKDTree(samples).query(q, distance_upper_bound=float(padding))
            ok = np.isfinite(dist)
            oi, oj, q, e = oi[ok], oj[ok], q[ok], eid[k[ok]]
            eh = (B[e] - A[e]) / np.maximum(L[e], 1e-12)[:, None]
            nr = np.stack([eh[:, 1], -eh[:, 0]], -1)
            nr = nr * np.where(((O[e] - A[e]) * nr).sum(1) > 0, -1.0, 1.0)[:, None]   # away from the island
            s_ = ((q - A[e]) * eh).sum(1)
            d_ = ((q - A[e]) * nr).sum(1)
            clamp = A[e] + eh * np.clip(s_, 0.0, L[e])[:, None]
            near[oi, oj] = (clamp + 0.5) / np.array([W, H])
            A2, B2, O2 = _tex(a2[e], W, H), _tex(b2[e], W, H), _tex(o2[e], W, H)
            L2 = np.linalg.norm(B2 - A2, axis=1)
            eh2 = (B2 - A2) / np.maximum(L2, 1e-12)[:, None]
            ni = np.stack([eh2[:, 1], -eh2[:, 0]], -1)
            ni = ni * np.where(((O2 - A2) * ni).sum(1) < 0, -1.0, 1.0)[:, None]       # into the neighbour
            ratio = L2 / np.maximum(L[e], 1e-12)
            across = A2 + eh2 * (s_ * ratio)[:, None] + ni * (d_ * ratio)[:, None]
            hs = has[e] & (L2 > 1e-9)
            tgt = np.where(hs[:, None], across, clamp)
            auv[oi, oj] = (tgt + 0.5) / np.array([W, H])
            valid[oi, oj] = hs
            # the map's Jacobian (texels): along the edge to along the neighbour's, outward here to inward there
            j00 = ratio * (eh2[:, 0] * eh[:, 0] + ni[:, 0] * nr[:, 0])
            j01 = ratio * (eh2[:, 0] * eh[:, 1] + ni[:, 0] * nr[:, 1])
            j10 = ratio * (eh2[:, 1] * eh[:, 0] + ni[:, 1] * nr[:, 0])
            j11 = ratio * (eh2[:, 1] * eh[:, 1] + ni[:, 1] * nr[:, 1])
            jj = np.stack([j00, j01, j10, j11], -1)
            jac[oi, oj] = np.where(hs[:, None], jj, 0.0)            # a clamped texel does not move with the step
    put(out, pre + "mask", m.astype(np.float64), like)
    put(out, pre + "uv", auv, like)
    put(out, pre + "valid", valid, like)
    put(out, pre + "jac", jac, like)
    put(out, pre + "near", near, like)
    put(out, pre + "tri", np.where(m, hit, -1).astype(np.float64), like)
    put(out, pre + "bary", bary, like)
    put(out, pre + "primid", pidl, like)
    put(out, pre + "P", Pw, like)
    put(out, pre + "N", Nw, like)
    put(out, pre + "tanU", tU, like)
    put(out, pre + "tanV", tV, like)
    put(out, pre + "uvscale", usc, like)
    return out


# ══════════════════════════════════════════════════════════════════ reading across the seams
class _Adj:
    def __init__(self, img, prefix):
        from .pixel import getn
        pre = str(prefix)
        for n in ("mask", "uv", "jac"):
            if (pre + n) not in img:
                raise ValueError(f"No adjacency layers '{pre}*' in this image: connect COP Geometry to Adjacency "
                                 f"(same resolution) upstream")
        self.mask = getn(img, pre + "mask")[..., 0] > 0.5
        self.uv = getn(img, pre + "uv")[..., :2]
        self.jac = getn(img, pre + "jac")
        self.valid = getn(img, pre + "valid")[..., 0] > 0.5
        self.near = getn(img, pre + "near")[..., :2]
        self.H, self.W = self.mask.shape
        self.pre = pre

    def sample(self, a, x, y):
        """Bilinear at texel coordinates (x, y), weighted by the island mask. -> values (n, C), weight (n,)."""
        H, W = self.H, self.W
        x0 = np.floor(x).astype(np.int64)
        y0 = np.floor(y).astype(np.int64)
        fx, fy = x - x0, y - y0
        val = np.zeros((len(x), a.shape[2]))
        wsum = np.zeros(len(x))
        for dy, wy in ((0, 1 - fy), (1, fy)):
            for dx, wx in ((0, 1 - fx), (1, fx)):
                xi, yi = x0 + dx, y0 + dy
                inb = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
                xc, yc = np.clip(xi, 0, W - 1), np.clip(yi, 0, H - 1)
                w = wx * wy * inb * self.mask[yc, xc]
                val += a[yc, xc] * w[:, None]
                wsum += w
        return val / np.maximum(wsum, 1e-12)[:, None], wsum

    def read(self, a, x, y, transform_vectors=False):
        """
        The layer a at texel coordinates (x, y) as the surface continues there: inside an island a plain (masked)
        bilinear read; outside, through adj_uv and its Jacobian to the neighbouring island; where that lands off the
        mesh too, the nearest point of the own island's edge. -> values, found (False: beyond Padding, nothing to
        read). transform_vectors turns 2- and 3-channel values
        (their first two components: a direction in texture space) from the neighbour's frame into this one's.
        """
        H, W = self.H, self.W
        ci = np.clip(np.rint(y).astype(np.int64), 0, H - 1)
        cj = np.clip(np.rint(x).astype(np.int64), 0, W - 1)
        val, w = self.sample(a, x, y)
        need = ~self.mask[ci, cj] | (w < 1e-6)
        if need.any():
            i, j = ci[need], cj[need]
            dx, dy = x[need] - j, y[need] - i
            jc = self.jac[i, j]
            tx = self.uv[i, j, 0] * W - 0.5 + jc[:, 0] * dx + jc[:, 1] * dy
            ty = self.uv[i, j, 1] * H - 0.5 + jc[:, 2] * dx + jc[:, 3] * dy
            v2, w2 = self.sample(a, tx, ty)
            if transform_vectors and a.shape[2] in (2, 3):
                det = jc[:, 0] * jc[:, 3] - jc[:, 1] * jc[:, 2]
                r = np.sqrt(np.maximum(np.abs(det), 1e-20))
                on = self.valid[i, j] & (np.abs(det) > 1e-12)
                # there -> here: the transpose of the (scaled) rotation, in texels; uv components scale by W, H
                vx, vy = v2[:, 0] * W, v2[:, 1] * H
                hx = (jc[:, 0] * vx + jc[:, 2] * vy) / r / W
                hy = (jc[:, 1] * vx + jc[:, 3] * vy) / r / H
                v2[:, 0] = np.where(on, hx, v2[:, 0])
                v2[:, 1] = np.where(on, hy, v2[:, 1])
            bad = w2 < 1e-6
            if bad.any():                                           # off the neighbour as well: clamp
                nx_ = self.near[i[bad], j[bad], 0] * W - 0.5
                ny_ = self.near[i[bad], j[bad], 1] * H - 0.5
                v3, w3 = self.sample(a, nx_, ny_)
                v2[bad] = v3
                w2[bad] = w3
            val[need] = v2
            found = np.ones(len(x), bool)
            found[need] = w2 >= 1e-6
            return val, found
        return val, np.ones(len(x), bool)


def _layers(img, layers, prefix):
    names = [n for n in str(layers).split() if n] or [n for n in img.names if not n.startswith(str(prefix))]
    for n in names:
        if n not in img:
            raise KeyError(f"No layer '{n}' in the image (it has: {', '.join(img.names)})")
    return names


def extrapolate(img, layers="", transform_vectors=False, prefix=PREFIX):
    """Fill the texels outside the islands from the neighbouring islands (Extrapolate with Adjacency): each layer
    keeps its values inside, and outside reads the surface's continuation across the seam."""
    from .pixel import getn, put
    adj = _Adj(img, prefix)
    out = img.copy()
    oi, oj = np.nonzero(~adj.mask)
    for n in _layers(img, layers, prefix):
        a = getn(img, n)
        if len(oi):
            a = a.copy()
            v, ok = adj.read(a, oj.astype(np.float64), oi.astype(np.float64), transform_vectors)
            a[oi[ok], oj[ok]] = v[ok]                               # beyond Padding: left as it was
        put(out, n, a, img)
    return out


def distort(img, layer="C", direction="0.05 0", dir_layer="", scale=1.0, transform_vectors=False, out_layer="",
            prefix=PREFIX):
    """
    Distort with Adjacency: every texel reads the layer at its position + Direction (texture space, in uv units;
    or the first two channels of Dir Layer) x Scale, following the surface across the seams.
    """
    from .pixel import getn, put, _vec
    adj = _Adj(img, prefix)
    a = getn(img, layer)
    H, W = adj.H, adj.W
    dl = str(dir_layer).strip()
    if dl:
        d = getn(img, dl)
        if d.shape[2] < 2:
            raise ValueError("Dir Layer needs at least 2 channels")
        du, dv = d[..., 0] * float(scale), d[..., 1] * float(scale)
    else:
        d = _vec(direction, 2)
        du = np.full((H, W), d[0] * float(scale))
        dv = np.full((H, W), d[1] * float(scale))
    J, I = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64))
    x = (J + du * W).reshape(-1)
    y = (I + dv * H).reshape(-1)
    res, ok = adj.read(a, x, y, transform_vectors)
    res = np.where(ok[:, None], res, a.reshape(H * W, -1)).reshape(H, W, -1)   # nothing there: undistorted
    out = img.copy()
    put(out, str(out_layer).strip() or str(layer).strip() or "C", res, img)
    return out


def attribute_sample(img, geo, attrib="P", attrib_geo=None, out_layer="", extrapolate_seams=True, prefix=PREFIX):
    """
    Attribute Sample with Adjacency: a geometry attribute as a texture, through the adjacency layers' triangle and
    barycentric weights. attrib_geo: read the attribute from this geometry instead (same topology, e.g. a deformed
    copy). Point, vertex and primitive attributes; outside the islands the neighbouring island's values.
    """
    from ..spatial import tri_soup
    from .pixel import getn, put
    adj = _Adj(img, prefix)
    pre = str(prefix)
    if (pre + "tri") not in img:
        raise ValueError(f"No '{pre}tri' layer: connect COP Geometry to Adjacency upstream")
    g = attrib_geo if attrib_geo is not None else geo
    if g is None:
        raise ValueError("Attribute Sample with Adjacency needs the geometry the adjacency was made from")
    tri, src, cor = tri_soup(g, "")
    t = np.rint(getn(img, pre + "tri")[..., 0]).astype(np.int64)
    b = getn(img, pre + "bary")
    m = t >= 0
    if m.any() and int(t.max()) >= len(tri):
        raise ValueError("The geometry does not match the adjacency layers (fewer triangles than they refer to)")
    name = str(attrib).strip() or "P"
    if g.has(VERTEX, name):
        vals = np.asarray(g.get(VERTEX, name), np.float64)[cor]
    elif g.has(POINT, name):
        vals = np.asarray(g.get(POINT, name), np.float64)[tri]
    elif g.has(PRIM, name):
        vals = np.repeat(np.asarray(g.get(PRIM, name), np.float64)[src][:, None], 3, 1)
    else:
        raise KeyError(f"The geometry has no numeric attribute '{name}' on vertices, points or primitives")
    if vals.ndim == 2:
        vals = vals[:, :, None]
    C = vals.shape[2]
    a = np.zeros(m.shape + (C,))
    a[m] = (vals[t[m]] * b[m][:, :, None]).sum(1)
    if extrapolate_seams:
        oi, oj = np.nonzero(~m)
        if len(oi):
            v, ok = adj.read(a, oj.astype(np.float64), oi.astype(np.float64), False)
            a[oi[ok], oj[ok]] = v[ok]
    out = img.copy()
    put(out, str(out_layer).strip() or name, a, img)
    return out


def space_transform(img, layer="C", transformation="world_to_tangent", signature="rgb", out_layer="",
                    prefix=PREFIX):
    """
    Space Transform with Adjacency: a vector layer between world space and the surface's tangent space (x along
    increasing u, y along increasing v, z the normal), from adj_N / adj_tanU / adj_tanV. Signature uv keeps x, y.
    Outside the islands the result is 0 (extrapolate afterwards).
    """
    from .pixel import getn, put
    if transformation not in TRANSFORMS:
        raise ValueError(f"Transformation must be one of {TRANSFORMS}")
    if signature not in SIGNATURES:
        raise ValueError(f"Signature must be one of {SIGNATURES}")
    pre = str(prefix)
    for n in ("N", "tanU", "tanV", "mask"):
        if (pre + n) not in img:
            raise ValueError(f"No '{pre}{n}' layer: connect COP Geometry to Adjacency upstream")
    v = getn(img, layer)
    if v.shape[2] < 3:
        v = np.concatenate([v, np.zeros(v.shape[:2] + (3 - v.shape[2],))], -1)
    v = v[..., :3]
    N = getn(img, pre + "N")[..., :3]
    tu = getn(img, pre + "tanU")[..., :3]
    tv = getn(img, pre + "tanV")[..., :3]
    m = getn(img, pre + "mask")[..., 0] > 0.5
    T = tu - N * (tu * N).sum(-1, keepdims=True)
    T = T / np.maximum(np.linalg.norm(T, axis=-1, keepdims=True), 1e-12)
    B = np.cross(N, T)
    B = B * np.where((B * tv).sum(-1, keepdims=True) < 0, -1.0, 1.0)   # toward increasing v
    if transformation == "world_to_tangent":
        r = np.stack([(v * T).sum(-1), (v * B).sum(-1), (v * N).sum(-1)], -1)
    else:
        r = T * v[..., 0:1] + B * v[..., 1:2] + N * v[..., 2:3]
    r = np.where(m[..., None], r, 0.0)
    out = img.copy()
    put(out, str(out_layer).strip() or str(layer).strip() or "C", r[..., :2] if signature == "uv" else r, img)
    return out
