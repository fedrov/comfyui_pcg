"""
Scatter SOP -- scatter points on a surface.

The ops.scatter() version only does the core thing (area-weighted sampling); this module is the full version:

    density         by total count / by density per unit area / density attribute / override prim area
    determinism     global seed + a per-prim seed
    relaxation      Relax Iterations, pushes random points toward an approximate Poisson distribution
    output attribs  N / sourceprim / sourceprimuv, plus barycentric interpolation of source attributes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two places where this is more careful than ops.scatter
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) **Triangulation uses Divide's ear clipping**, not core.triangles()' fan. A fan on a concave ngon
   grows triangles that stick outside the shape, so points get scattered outside the face -- and this kind of
   error takes a long stare at the preview to notice.

2) **Relax really projects back onto the surface**. If you only push apart in the tangent plane and leave it there,
   points slowly drift off the surface; here every round reprojects the points onto the nearest triangle, using the
   same uniform grid hash as Fuse to find candidate triangles, then an exact point-triangle closest point.

   The relax radius is estimated from the target density: r = sqrt(total area / (N*pi)) -- the radius at which N
   non-overlapping disks tile that area. Multiplied by Scale Radii By, then clamped by Max Relax Radius.
"""
from __future__ import annotations

import numpy as np

from .npcompat import select as _select  # np.select breaks if a node pack rebinds np.bool

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .ops import prim_normals, _gather_blocks
from . import divide as _divide

MAX_POINTS_HARD = 20_000_000


# ═══════════════════════════════════════════════════════════ triangulation + weights
def _triangulate(geo, group, want_corners=False):
    """
    Cut the selected primitives into triangles, return (triangle point numbers (T,3), which original prim each triangle came from).

    Borrows Divide's ear clipping: concave ngons are cut correctly too. A temporary prim attribute carries the original prim number
    across and is read back after cutting -- the only reliable way to recover "which face this triangle belongs to".

    want_corners=True additionally returns (the triangulated geometry, each triangle's three **corner**
    indices (T,3)). Corners index the vertex array of the triangulated result -- interpolating **vertex attributes**
    (uv lives on vertices) must go this way: at a uv seam a point number is **one point with two uvs**,
    so point numbers alone cannot get back to it.
    """
    sel = resolve(geo, PRIM, group)
    empty = (np.zeros((0, 3), np.int32), np.zeros(0, np.int64))
    if geo.nprims == 0 or not sel.any():
        return empty + ((None, np.zeros((0, 3), np.int64)) if want_corners
                        else ())
    tmp = geo.copy()
    tmp.set(PRIM, "__srcprim__", np.arange(geo.nprims, dtype=np.int32),
            owned=True)
    tmp.set_group(PRIM, "__scatsel__", sel)
    tri = _divide.convex_polygons(tmp, "__scatsel__", 3, False, 1e-4,
                                  False, False, True)
    keep = (tri.prim_sizes() == 3) & tri.prim_closed \
        & tri.get_group(PRIM, "__scatsel__")
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return empty + ((tri, np.zeros((0, 3), np.int64)) if want_corners
                        else ())
    corner = _gather_blocks(tri.prim_offset[:-1][idx], np.full(len(idx), 3))
    out = (tri.vertex_point[corner].reshape(-1, 3).astype(np.int32),
           tri.get(PRIM, "__srcprim__")[idx, 0].astype(np.int64))
    if want_corners:
        out = out + (tri, corner.reshape(-1, 3).astype(np.int64))
    return out


def _weights(geo, tri, src, density_attrib="", area_attrib=""):
    """Per-triangle sampling weight = area x density. Returns (weights, geometric area)."""
    P = geo.get(POINT, "P").astype(np.float64)
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    w = area.copy()

    if density_attrib.strip():
        d = geo.get(POINT, density_attrib.strip())
        if d is None:
            have = sorted(geo.attribs[POINT].keys())
            raise KeyError(f"No point attribute '{density_attrib}'. Existing: "
                           f"{have or '(none)'}")
        w = w * np.clip(d[tri, 0].mean(1), 0, None)

    if area_attrib.strip():
        # Override Prim Area: the attribute value replaces the prim's geometric area, distributed proportionally to its triangles
        pa = geo.get(PRIM, area_attrib.strip())
        if pa is None:
            have = sorted(geo.attribs[PRIM].keys())
            raise KeyError(f"No prim attribute '{area_attrib}'. Existing: "
                           f"{have or '(none)'}")
        geom = np.bincount(src, weights=area, minlength=geo.nprims)
        scale = np.where(geom > 0, pa[:, 0] / np.where(geom > 0, geom, 1), 0.0)
        w = w * scale[src]
    return w, area


# ═══════════════════════════════════════════════════════════════ sampling
def _sample(tri, w, n, rng):
    """Pick triangles by weight, then take uniform barycentric coordinates inside the triangle."""
    total = float(w.sum())
    if total <= 0 or n <= 0:
        return (np.zeros(0, np.int64), np.zeros(0), np.zeros(0))
    cdf = np.cumsum(w)
    t = np.clip(np.searchsorted(cdf, rng.random(n) * total), 0, len(w) - 1)
    u = rng.random(n)
    v = rng.random(n)
    flip = u + v > 1.0                            # fold into the triangle
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    return t, u, v


def _sample_per_prim(tri, src, w, n_total, nprims, seed, seed_vals):
    """
    Each prim uses its own random stream -- changing one face does not reshuffle the points on all the others.

    First split the total across prims by area with the **largest remainder method** (plain proportional rounding loses/adds a few points),
    then sample prim by prim. The per-prim Python loop is the cost of this mode, in exchange for stability:
    in a procedural workflow "change one place, the rest stays put" matters far more than being a bit faster.
    """
    pw = np.bincount(src, weights=w, minlength=nprims)
    tot = float(pw.sum())
    if tot <= 0 or n_total <= 0:
        return (np.zeros(0, np.int64), np.zeros(0), np.zeros(0))
    exact = pw / tot * n_total
    base = np.floor(exact).astype(np.int64)
    rem = n_total - int(base.sum())
    if rem > 0:
        order = np.argsort(-(exact - base))
        base[order[:rem]] += 1
    return _sample_prim_counts(tri, src, w, base, nprims, seed, seed_vals)


def _sample_prim_counts(tri, src, w, base, nprims, seed, seed_vals):
    """
    Given how many points each prim gets (base, length nprims), sample each prim with its own random stream.

    Split out of _sample_per_prim so Count per Primitive can reuse it: in that mode the point counts are given by the user
    per prim, so there is no need to split by area.
    """
    order = np.argsort(src, kind="stable")
    counts = np.bincount(src, minlength=nprims)
    off = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    ti, ui, vi = [], [], []
    for p in np.nonzero(base > 0)[0]:
        loc = order[off[p]:off[p + 1]]
        if not len(loc):
            continue
        sv = int(seed_vals[p]) if seed_vals is not None else int(p)
        r = np.random.default_rng((int(seed) * 1000003) ^ (sv * 2654435761))
        t, u, v = _sample(tri[loc], w[loc], int(base[p]), r)
        ti.append(loc[t]); ui.append(u); vi.append(v)
    if not ti:
        return (np.zeros(0, np.int64), np.zeros(0), np.zeros(0))
    return np.concatenate(ti), np.concatenate(ui), np.concatenate(vi)


# ═══════════════════════════════════════════════════════════════ relaxation
def _grid_pairs(P, d):
    """Point pairs (i<j) within radius d. Uniform grid hash, the same one Fuse uses."""
    if len(P) < 2 or d <= 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    c = np.floor(P / d).astype(np.int64)
    key = (c[:, 0] * 73856093) ^ (c[:, 1] * 19349663) ^ (c[:, 2] * 83492791)
    order = np.argsort(key, kind="stable")
    ks = key[order]
    uniq, starts = np.unique(ks, return_index=True)
    ends = np.append(starts[1:], len(ks)).astype(np.int64)
    starts = starts.astype(np.int64)
    ia, ib = [], []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k = ((c[:, 0] + dx) * 73856093) ^ ((c[:, 1] + dy) * 19349663) \
                    ^ ((c[:, 2] + dz) * 83492791)
                pos = np.searchsorted(uniq, k)
                pc = np.clip(pos, 0, max(len(uniq) - 1, 0))
                hit = np.nonzero((pos < len(uniq)) & (uniq[pc] == k))[0]
                if not len(hit):
                    continue
                p = pos[hit]
                cnt = ends[p] - starts[p]
                if not cnt.sum():
                    continue
                ia.append(np.repeat(hit, cnt))
                ib.append(order[_gather_blocks(starts[p], cnt)])
    if not ia:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    A = np.concatenate(ia); B = np.concatenate(ib)
    m = A < B
    A, B = A[m], B[m]
    m = np.linalg.norm(P[A] - P[B], axis=1) <= d
    return A[m], B[m]


def _closest_on_tris(Q, A, B, C, cand_i, cand_t):
    """
    Among candidate pairs (point cand_i, triangle cand_t), for each point take the closest point on its nearest triangle.

    Uses Ericson's region classification (vertex regions / three edge regions / interior); the seven cases are
    picked in one go with np.select. Taking the lazy route of computing interior barycentrics and clamping to [0,1] is wrong: when a point lies
    outside a vertex region, the clamped position lands at the wrong place on an edge, and after a few relax rounds points start
    piling up along the edges.
    """
    a, b, c = A[cand_t], B[cand_t], C[cand_t]
    p = Q[cand_i]
    ab, ac = b - a, c - a
    ap, bp, cp = p - a, p - b, p - c
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    def _div(x, y):
        return x / np.where(np.abs(y) < 1e-30, 1e-30, y)

    den = va + vb + vc
    v_in, w_in = _div(vb, den), _div(vc, den)
    t_ab = np.clip(_div(d1, d1 - d3), 0, 1)
    t_ac = np.clip(_div(d2, d2 - d6), 0, 1)
    t_bc = np.clip(_div(d4 - d3, (d4 - d3) + (d5 - d6)), 0, 1)

    conds = [
        (d1 <= 0) & (d2 <= 0),                                   # vertex A
        (d3 >= 0) & (d4 <= d3),                                  # vertex B
        (d6 >= 0) & (d5 <= d6),                                  # vertex C
        (vc <= 0) & (d1 >= 0) & (d3 <= 0),                       # edge AB
        (vb <= 0) & (d2 >= 0) & (d6 <= 0),                       # edge AC
        (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0),         # edge BC
    ]
    v = _select(conds, [np.zeros_like(d1), np.ones_like(d1),
                          np.zeros_like(d1), t_ab, np.zeros_like(d1),
                          1 - t_bc], default=v_in)
    w = _select(conds, [np.zeros_like(d1), np.zeros_like(d1),
                          np.ones_like(d1), np.zeros_like(d1), t_ac,
                          t_bc], default=w_in)
    pos = a + v[:, None] * ab + w[:, None] * ac
    dist = np.linalg.norm(pos - p, axis=1)

    n = len(Q)
    best = np.full(n, np.inf)
    np.minimum.at(best, cand_i, dist)
    idx = np.nonzero(dist <= best[cand_i] + 1e-30)[0]
    out_pos = Q.copy()
    out_tri = np.full(n, -1, np.int64)
    out_uv = np.zeros((n, 2))
    out_pos[cand_i[idx]] = pos[idx]
    out_tri[cand_i[idx]] = cand_t[idx]
    out_uv[cand_i[idx]] = np.stack([v[idx], w[idx]], 1)
    return out_pos, out_tri, out_uv


def _relax(P, tri_idx, uv, verts, iterations, radius, cell):
    """
    Push apart + project back onto the surface. Each round: push apart within the radius -> drop back onto the nearest triangle.

    Two optimizations that make it run at usable speed:

    1) **The displacement is first projected into the current triangle's tangent plane**. The moved point then stays
       coplanar with its original triangle, so "is it still inside the original triangle" reduces to a zero-distance test.
    2) **The vast majority of points are still in their original triangle** (one step moves at most r, and triangles are usually larger than r),
       so first compute the closest point on the current triangle once; only the ones that actually left go search the grid.
       On a 100k-point mesh this cuts candidate pairs from over 5 million to a few hundred thousand -- the difference between 40 s and 4 s.
    """
    if iterations <= 0 or len(P) < 2 or radius <= 0:
        return P, tri_idx, uv
    A, B, C = verts
    fn = np.cross(B - A, C - A)
    l = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = fn / np.where(l == 0, 1, l)
    scale = float(np.max(np.abs(np.concatenate([A, B, C])))) or 1.0
    tol = scale * 1e-7

    cen = (A + B + C) / 3.0
    ck = np.floor(cen / cell).astype(np.int64)
    tkey = (ck[:, 0] * 73856093) ^ (ck[:, 1] * 19349663) ^ (ck[:, 2] * 83492791)
    torder = np.argsort(tkey, kind="stable")
    tks = tkey[torder]
    tuniq, tstart = np.unique(tks, return_index=True)
    tend = np.append(tstart[1:], len(tks)).astype(np.int64)
    tstart = tstart.astype(np.int64)
    n = len(P)
    allidx = np.arange(n, dtype=np.int64)

    for _ in range(int(iterations)):
        ia, ib = _grid_pairs(P, 2 * radius)
        if not len(ia):
            break
        d = P[ia] - P[ib]
        dl = np.linalg.norm(d, axis=1)
        dl = np.where(dl < 1e-12, 1e-12, dl)
        push = np.clip(2 * radius - dl, 0, None)[:, None] * (d / dl[:, None]) * 0.5
        disp = np.zeros_like(P)
        np.add.at(disp, ia, push)
        np.add.at(disp, ib, -push)
        cnt = np.maximum(np.bincount(ia, minlength=n)
                         + np.bincount(ib, minlength=n), 1)[:, None]
        step = disp / cnt
        nrm = fn[tri_idx]
        step -= nrm * np.einsum("ij,ij->i", step, nrm)[:, None]   # move only within the tangent plane
        sl = np.linalg.norm(step, axis=1, keepdims=True)
        step = np.where(sl > radius, step / np.where(sl == 0, 1, sl) * radius, step)
        Q = P + step

        # --- try the current triangle first ---
        pos0, t0, uv0 = _closest_on_tris(Q, A, B, C, allidx, tri_idx)
        stay = np.linalg.norm(pos0 - Q, axis=1) <= tol
        P = np.where(stay[:, None], pos0, P)
        uv = np.where(stay[:, None], uv0, uv)

        # --- only the ones that left search the grid ---
        need = np.nonzero(~stay)[0]
        if not len(need):
            continue
        Qn = Q[need]
        qc = np.floor(Qn / cell).astype(np.int64)
        cand_i, cand_t = [], []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    k = ((qc[:, 0] + dx) * 73856093) ^ ((qc[:, 1] + dy) * 19349663) \
                        ^ ((qc[:, 2] + dz) * 83492791)
                    pos = np.searchsorted(tuniq, k)
                    pc = np.clip(pos, 0, max(len(tuniq) - 1, 0))
                    hit = np.nonzero((pos < len(tuniq)) & (tuniq[pc] == k))[0]
                    if not len(hit):
                        continue
                    p = pos[hit]
                    c = tend[p] - tstart[p]
                    if not c.sum():
                        continue
                    cand_i.append(np.repeat(hit, c))
                    cand_t.append(torder[_gather_blocks(tstart[p], c)])
        if not cand_i:
            continue
        ci = np.concatenate(cand_i)
        ct = np.concatenate(cand_t)
        newP, newT, newUV = _closest_on_tris(Qn, A, B, C, ci, ct)
        ok = newT >= 0
        sub = need[ok]
        P[sub] = newP[ok]
        tri_idx[sub] = newT[ok]
        uv[sub] = newUV[ok]
    return P, tri_idx, uv


# ═══════════════════════════════════════════════════════════════ Generate
# The Generate menu of Houdini Scatter 2.0. Scatter on Voxels Independently is not implemented:
# our Scatter only scatters on polygon surfaces (volume prims are not triangulated), so that mode has nothing to act on.
GENERATES = ("by_density", "count_per_primitive", "in_texture_space")

# Approximation from the docs: on surfaces radius ≈ 0.537 / sqrt(density). We only scatter on surfaces,
# so the curve (0.5/density) and volume (0.561/∛density) formulas are unused.
RADIUS_K_SURFACE = 0.537


def _tex_grid(image):
    """
    Density texture -> (H, W) float64, negative values clamped to 0.

    Takes channel 0 of the default layer (C): the docs only say "texture times Density Scale is the density", not
    how to combine multiple channels -- a grayscale image has three identical channels, so channel 0 and luminance are the same; for color images
    using channel 0 is our choice.
    """
    from .cop.core import CopImage, DEFAULT_LAYER
    if not isinstance(image, CopImage):
        raise TypeError("Density Texture needs a COPIMAGE (convert one with COP Import)")
    a = image.need(DEFAULT_LAYER)
    if not isinstance(a, np.ndarray):
        a = image.to_device("numpy").need(DEFAULT_LAYER)
    a = np.asarray(a, np.float64)
    return np.clip(a[:, :, 0], 0.0, None)


def _tex_at(grid, uv):
    """
    Nearest-pixel lookup, clamped at the border. Same convention as the closest mode of frommap.sample_layer
    (pixel x covers [x/W, (x+1)/W), row 0 is v ∈ [0, 1/H)) -- so the texture is per-pixel
    constant, the per-pixel CDF sampling in texture space and the lookup here are the same function, and the density output matches.
    """
    H, W = grid.shape
    x = np.clip(np.floor(uv[:, 0] * W).astype(np.int64), 0, W - 1)
    y = np.clip(np.floor(uv[:, 1] * H).astype(np.int64), 0, H - 1)
    return grid[y, x]


def _corner_uv(tgeo, tcorner, name):
    """uv of the three corners of every triangle of the triangulated result, (T, 3, 2). Vertex first, then point."""
    from .frommap import uv_of                      # frommap imports this module in turn
    vuv, _, _ = uv_of(tgeo, VERTEX, str(name).strip() or "uv")
    return vuv[tcorner]


def _locate_uv(S, UA, UB, UC):
    """
    Which uv triangles the texture-space samples S (M,2) fall into. Returns (sample index, triangle index, u, v),
    with u / v the barycentric coordinates relative to (A, B, C) (same convention as _sample).

    When uv islands overlap, one sample produces a point on each triangle covering it -- the docs say "the surface
    takes the points that fall within its uv region", and every overlapping piece counts; the docs do not say so explicitly, this is how we implement it.
    A uniform grid (√T x √T cells) finds candidates, then barycentric coordinates are computed exactly.
    """
    T, M = len(UA), len(S)
    if not T or not M:
        z = np.zeros(0, np.int64)
        return z, z, np.zeros(0), np.zeros(0)
    G = int(np.clip(np.sqrt(T), 1, 1024))
    lo = np.minimum(np.minimum(UA, UB), UC)
    hi = np.maximum(np.maximum(UA, UB), UC)
    live = (hi >= 0).all(1) & (lo <= 1).all(1)       # those entirely outside the unit square can be ignored
    c0 = np.clip(np.floor(lo * G), 0, G - 1).astype(np.int64)
    c1 = np.clip(np.floor(hi * G), 0, G - 1).astype(np.int64)
    nx = c1[:, 0] - c0[:, 0] + 1
    ny = c1[:, 1] - c0[:, 1] + 1
    cnt = np.where(live, nx * ny, 0)
    ti = np.repeat(np.arange(T, dtype=np.int64), cnt)
    k = np.arange(int(cnt.sum()), dtype=np.int64) - \
        np.repeat(np.cumsum(cnt) - cnt, cnt)
    key = (c0[ti, 1] + k // nx[ti]) * G + (c0[ti, 0] + k % nx[ti])
    order = np.argsort(key, kind="stable")
    ks, ts = key[order], ti[order]
    cells = np.arange(G * G, dtype=np.int64)
    st = np.searchsorted(ks, cells, "left")
    en = np.searchsorted(ks, cells, "right")
    sc = np.clip(np.floor(S * G), 0, G - 1).astype(np.int64)
    skey = sc[:, 1] * G + sc[:, 0]
    nc = en[skey] - st[skey]
    si = np.repeat(np.arange(M, dtype=np.int64), nc)
    tj = ts[_gather_blocks(st[skey], nc)]
    e1, e2 = UB[tj] - UA[tj], UC[tj] - UA[tj]
    d = S[si] - UA[tj]
    den = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    sden = np.where(den == 0, 1.0, den)
    u = (d[:, 0] * e2[:, 1] - d[:, 1] * e2[:, 0]) / sden
    v = (e1[:, 0] * d[:, 1] - e1[:, 1] * d[:, 0]) / sden
    ok = (den != 0) & (u >= 0) & (v >= 0) & (u + v <= 1)
    return si[ok], tj[ok], u[ok], v[ok]


def _counts_per_prim(geo, spec):
    """
    Count per Prim Attribute: the docs say "an integer, or the name of an integer prim attribute".
    If it parses as an integer it is a constant; otherwise an attribute name (error if missing, rather than silently scattering 0).
    Negative counts scatter nothing (_sample_prim_counts only samples prims with base > 0), so no clamping needed here.
    """
    s = str(spec).strip()
    try:
        c = int(s)
        return np.full(geo.nprims, c, np.int64)
    except ValueError:
        pass
    a = geo.get(PRIM, s)
    if a is None or is_string(a):
        have = sorted(k for k, v in geo.attribs[PRIM].items() if not is_string(v))
        raise KeyError(f"Count per Prim Attribute '{s}' is neither an integer nor a numeric prim"
                       f" attribute. Existing: {have or '(none)'}")
    return np.rint(a[:, 0]).astype(np.int64)


def _relax_radius(area_sum, n, scale_radii_by, use_max, max_r):
    r = float(np.sqrt(area_sum / (n * np.pi))) * float(scale_radii_by)
    return min(r, float(max_r)) if use_max else r


def _relax_on(pos, t, u, v, A, B, C, iterations, r):
    """Run _relax on a set of triangles; the cell size is chosen as in the original main entry."""
    edge = np.linalg.norm(B - A, axis=1)
    cell = max(float(np.max(edge)) if len(edge) else 1.0, 2 * r, 1e-9)
    pos, t, uvw = _relax(pos, t, np.stack([u, v], 1), (A, B, C),
                         iterations, r, cell)
    return pos, t, uvw[:, 0], uvw[:, 1]


def _seed_vals(geo, prim_seed_attrib):
    if not prim_seed_attrib.strip():
        return None
    sv = geo.get(PRIM, prim_seed_attrib.strip())
    if sv is None:
        have = sorted(geo.attribs[PRIM].keys())
        raise KeyError(f"No prim attribute '{prim_seed_attrib}'. Existing: "
                       f"{have or '(none)'}")
    if is_string(sv):                          # string seed: number by grouped value
        _, vals = np.unique(sv[:, 0], return_inverse=True)
        return vals.reshape(-1).astype(np.int64)
    return sv[:, 0].astype(np.int64)


def _draw(tri, src, w, n, nprims, seed, vals):
    """Scatter n candidates by weight: with a prim seed each prim uses its own stream, otherwise one global stream."""
    if vals is not None:
        return _sample_per_prim(tri, src, w, n, nprims, seed, vals)
    return _sample(tri, w, n, np.random.default_rng(int(seed)))


def _uv_area(cuv):
    e1, e2 = cuv[:, 1] - cuv[:, 0], cuv[:, 2] - cuv[:, 0]
    return 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])


def _bary_uv(cuv, t, u, v):
    c = cuv[t]
    return c[:, 0] + u[:, None] * (c[:, 1] - c[:, 0]) + v[:, None] * (c[:, 2] - c[:, 0])


# ═══════════════════════════════════════════════════════════════ main entry
def scatter(geo, group="", force_total_count=True, count=1000,
            density_scale=10.0, density_attrib="", area_attrib="",
            use_max_points=True, max_points=1000000,
            seed=0, prim_seed_attrib="", randomize_order=True,
            relax_iterations=0, use_geometric_normals=False,
            scale_radii_by=1.0, use_max_relax_radius=True,
            max_relax_radius=10.0,
            out_normal="N", out_sourceprim="sourceprim",
            out_uv="sourceprimuv", interpolate_attribs=True,
            interpolate_vertex_attribs=True,
            generate="by_density", count_per_prim="1",
            density_texture=None, texture_uv_attrib="uv",
            out_density="", out_radius="", out_id="",
            out_texture_space=False,
            point_attribs="*", vertex_attribs="*",
            prim_attribs="", detail_attribs="", detail_as_detail=""):
    """
    Scatter points on the selected primitives, output a point cloud.

    With force_total_count off, point count = density_scale x weighted total area -- that is the
    real meaning of "density": at the same density_scale, larger faces get more points.

    relax_iterations > 0 pushes random points toward an approximate Poisson distribution (blue noise), visually much more even,
    at the cost of one neighbour search + one projection per round.

    generate (Houdini's Generate menu):
        by_density           Old behaviour. When density_texture is given, do one more rejection sampling by the texture value at the surface uv
                             (texture x density attribute x Density Scale)
        count_per_primitive  Exactly count_per_prim points per prim (an integer or prim attribute name),
                             Relax is done per prim, so points do not wander onto other prims
        in_texture_space     Scatter in the uv unit square; each surface takes the points that fall in its own uv region;
                             Relax is done in texture space
    """
    if generate not in GENERATES:
        raise ValueError(f"generate must be one of {GENERATES}, got {generate!r}")
    tri, src, tgeo, tcorner = _triangulate(geo, group, True)
    if not len(tri):
        return Geometry()
    w, area = _weights(geo, tri, src, density_attrib, area_attrib)
    total_w = float(w.sum())
    if total_w <= 0:
        return Geometry()

    P = geo.get(POINT, "P").astype(np.float64)
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    # Count per Primitive does not read the texture (docs: Density Texture is only used by By Density /
    # In Texture Space); that branch and its density output never touch grid
    grid = _tex_grid(density_texture) if density_texture is not None else None
    cuv = None
    # Per-point density = K x (relative density), the relative density is evaluated at the point's **final** position (docs:
    # "measured after relaxation"). How K and the relative density are defined: see each branch.
    K = None

    if generate == "in_texture_space":
        cuv = _corner_uv(tgeo, tcorner, texture_uv_attrib)
        mean_t = float(grid.mean()) if grid is not None else 1.0
        if force_total_count:
            n0 = int(count)
        else:
            # Docs: without a texture Density Scale is "the expected total point count in the unit square";
            # with a texture, texture x Density Scale is the density, total = Density Scale x texture mean
            n0 = int(round(float(density_scale) * mean_t))
        capped = bool(use_max_points and n0 > int(max_points))
        if use_max_points:
            n0 = min(n0, int(max_points))
        n0 = max(0, min(n0, MAX_POINTS_HARD))
        if n0 == 0 or mean_t <= 0:
            return Geometry()
        rng = np.random.default_rng(int(seed))
        if grid is None:
            S = rng.random((n0, 2))
        else:                                      # exact sampling by per-pixel CDF (per-pixel constant)
            H, W = grid.shape
            cdf = np.cumsum(grid.ravel())
            pix = np.searchsorted(cdf, rng.random(n0) * cdf[-1], "right")
            pix = np.clip(pix, 0, H * W - 1)
            py, px = np.divmod(pix, W)
            S = np.stack([(px + rng.random(n0)) / W,
                          (py + rng.random(n0)) / H], 1)
        UA, UB, UC = cuv[:, 0], cuv[:, 1], cuv[:, 2]
        si, t, u, v = _locate_uv(S, UA, UB, UC)
        if not len(t):
            return Geometry()
        if relax_iterations > 0 and len(t) > 1:
            z = np.zeros((len(UA), 1))
            A2, B2, C2 = (np.concatenate([X, z], 1) for X in (UA, UB, UC))
            q = np.concatenate([S[si], np.zeros((len(si), 1))], 1)
            r = _relax_radius(1.0, n0, scale_radii_by,
                              use_max_relax_radius, max_relax_radius)
            _, t, u, v = _relax_on(q, t, u, v, A2, B2, C2, relax_iterations, r)
        pos = A[t] + u[:, None] * (B[t] - A[t]) + v[:, None] * (C[t] - A[t])
        K = float(density_scale) if not (force_total_count or capped) \
            else n0 / mean_t

    elif generate == "count_per_primitive":
        cp = _counts_per_prim(geo, count_per_prim)
        wp = np.bincount(src, weights=w, minlength=geo.nprims)
        # prims with zero (weighted) area cannot get points: _sample returns empty for all-zero weights
        tot = int(cp[cp > 0].sum())
        if tot > MAX_POINTS_HARD:
            raise ValueError(f"Count per Primitive totals {tot} points, exceeding the limit "
                             f"{MAX_POINTS_HARD}")
        vals = _seed_vals(geo, prim_seed_attrib)
        t, u, v = _sample_prim_counts(tri, src, w, cp, geo.nprims, seed, vals)
        if not len(t):
            return Geometry()
        pos = A[t] + u[:, None] * (B[t] - A[t]) + v[:, None] * (C[t] - A[t])
        if relax_iterations > 0:
            # Docs: in this mode Relax is done per prim, points stay on their own prim
            sp = src[t]
            for p in np.unique(sp):
                idx = np.nonzero(sp == p)[0]           # with only 1 point _relax returns it unchanged
                tl = np.nonzero(src == p)[0]
                r = _relax_radius(wp[p], len(idx), scale_radii_by,
                                  use_max_relax_radius, max_relax_radius)
                q, tt, uu, vv = _relax_on(pos[idx], np.searchsorted(tl, t[idx]),
                                          u[idx], v[idx], A[tl], B[tl], C[tl],
                                          relax_iterations, r)
                pos[idx], t[idx], u[idx], v[idx] = q, tl[tt], uu, vv
        # Per-prim density = its point count / its weighted area
        K = np.where(wp > 0, cp / np.where(wp > 0, wp, 1), 0.0)

    else:
        if force_total_count:
            n = int(count)
        else:
            n = int(round(float(density_scale) * total_w))
        capped = bool(use_max_points and n > int(max_points))
        if use_max_points:
            n = min(n, int(max_points))
        n = max(0, min(n, MAX_POINTS_HARD))
        if n == 0:
            return Geometry()
        vals = _seed_vals(geo, prim_seed_attrib)

        if grid is None:
            t, u, v = _draw(tri, src, w, n, geo.nprims, seed, vals)
            integral = total_w
        else:
            # The texture is sampled at **the surface point's own uv**, kept with probability tex / max (rejection sampling):
            # density accuracy is limited only by texture resolution, not by mesh density (same as Scatter from Map).
            # The random stream used for rejection is offset from the triangle-picking stream; see frommap.scatter_from_map for why.
            cuv = _corner_uv(tgeo, tcorner, texture_uv_attrib)
            tmax = float(grid.max())
            if tmax <= 0:
                return Geometry()
            acc_rng = np.random.default_rng(int(seed) ^ 0x7E57)
            if not force_total_count:
                # Total count not forced: candidates = Density Scale x weighted area x texture max,
                # so after acceptance the expected count is exactly Density Scale x ∫(density x texture)
                m = min(int(round(float(density_scale) * total_w * tmax)),
                        MAX_POINTS_HARD)
                t, u, v = _draw(tri, src, w, m, geo.nprims, seed, vals)
                p = _tex_at(grid, _bary_uv(cuv, t, u, v)) / tmax
                keep = acc_rng.random(len(t)) < p
                t, u, v = t[keep], u[keep], v[keep]
                if len(t) > n:                      # Max Point Limit
                    t, u, v = t[:n], u[:n], v[:n]
                ncand, nacc = max(m, 1), int(keep.sum())
            else:
                ts, us, vs, got, ncand, nacc = [], [], [], 0, 0, 0
                m = int(np.ceil(n * 1.2)) + 16
                for rd in range(32):
                    tt, uu, vv = _draw(tri, src, w, m, geo.nprims,
                                       int(seed) + rd * 7919, vals)
                    p = _tex_at(grid, _bary_uv(cuv, tt, uu, vv)) / tmax
                    keep = acc_rng.random(len(tt)) < p
                    ncand += len(tt); nacc += int(keep.sum())
                    ts.append(tt[keep]); us.append(uu[keep]); vs.append(vv[keep])
                    got += int(keep.sum())
                    if got >= n:
                        break
                    rate = max(nacc / max(ncand, 1), 1e-3)
                    m = min(int(np.ceil((n - got) / rate * 1.2)) + 16,
                            MAX_POINTS_HARD)
                t = np.concatenate(ts)[:n]
                u = np.concatenate(us)[:n]
                v = np.concatenate(vs)[:n]
            # Estimate of ∫(relative density): weighted area x texture max x acceptance rate
            integral = total_w * tmax * nacc / max(ncand, 1)
        if not len(t):
            return Geometry()

        pos = A[t] + u[:, None] * (B[t] - A[t]) + v[:, None] * (C[t] - A[t])

        if relax_iterations > 0:
            r = _relax_radius(total_w, len(pos), scale_radii_by,
                              use_max_relax_radius, max_relax_radius)
            pos, t, u, v = _relax_on(pos, t, u, v, A, B, C, relax_iterations, r)
        K = float(density_scale) if not (force_total_count or capped) \
            else (len(t) / integral if integral > 0 else 0.0)

    if randomize_order:
        rs = np.random.default_rng(int(seed) ^ 0x5EED)
        perm = rs.permutation(len(pos))
        pos, t, u, v = pos[perm], t[perm], u[perm], v[perm]

    out = Geometry.from_points(pos.astype(np.float32))
    if out_normal.strip():
        if use_geometric_normals or not geo.has(POINT, "N"):
            cr = np.cross(B[t] - A[t], C[t] - A[t])
        else:                                      # interpolate the source geometry's point normals
            N = geo.get(POINT, "N").astype(np.float64)
            wgt = np.stack([1 - u - v, u, v], 1)[:, :, None]
            cr = (N[tri[t]] * wgt).sum(1)
        l = np.linalg.norm(cr, axis=1, keepdims=True)
        out.set(POINT, out_normal.strip(),
                (cr / np.where(l == 0, 1, l)).astype(np.float32), owned=True)
    if out_sourceprim.strip():
        out.set(POINT, out_sourceprim.strip(), src[t].astype(np.int32),
                owned=True)
    if out_uv.strip():
        out.set(POINT, out_uv.strip(),
                np.stack([u, v, np.zeros(len(u))], 1).astype(np.float32),
                owned=True)

    on_d, on_r = out_density.strip(), out_radius.strip()
    if on_d or on_r:
        _write_density(out, on_d, on_r, generate, K, grid, cuv, tgeo, tcorner,
                       texture_uv_attrib, out_texture_space, w, area, src, t, u, v,
                       use_max_relax_radius, max_relax_radius)
    if out_id.strip():
        # Docs: each point gets a unique integer id that stays the same after downstream deletes -- it is simply the scatter index
        out.set(POINT, out_id.strip(), np.arange(len(t), dtype=np.int32),
                owned=True)

    skip = {"P", out_normal.strip(), out_sourceprim.strip(), out_uv.strip(),
            on_d, on_r, out_id.strip()} - {""}
    if interpolate_attribs or interpolate_vertex_attribs:
        from .ops import match_names
        wgt = np.stack([1 - u - v, u, v], 1)[:, :, None]
        skip0 = {"P", out_normal.strip(), out_sourceprim.strip(), out_uv.strip()}
        if interpolate_attribs:
            # Point Attributes: in Houdini a name pattern; default "*" = the old "all"
            pick = set(match_names(list(geo.attribs[POINT]), point_attribs))
            for k, arr in geo.attribs[POINT].items():
                if k in skip0 or is_string(arr) or k not in pick:
                    continue
                out.set(POINT, k, (arr[tri[t]] * wgt).sum(1).astype(arr.dtype),
                        owned=True)
        # vertex attributes (uv lives here) are also interpolated onto the points -- Houdini's Scatter does the same.
        # They must be fetched per **corner**: at a uv seam one point carries two different uvs, fetching per point
        # number interpolates a value spanning the whole texture in seam triangles, with no error at all.
        # On a name clash vertex overrides point, consistent with Houdini's promotion rules.
        if interpolate_vertex_attribs and tgeo is not None:
            pick = set(match_names(list(tgeo.attribs[VERTEX]), vertex_attribs))
            for k, arr in tgeo.attribs[VERTEX].items():
                if k in skip0 or is_string(arr) or k not in pick:
                    continue
                out.set(POINT, k,
                        (arr[tcorner[t]] * wgt).sum(1).astype(arr.dtype),
                        owned=True)
    _copy_prim_detail(geo, out, src[t], prim_attribs, detail_attribs,
                      detail_as_detail, skip)
    return out


def _write_density(out, on_d, on_r, generate, K, grid, cuv, tgeo, tcorner,
                   texture_uv_attrib, tex_space, w, area, src, t, u, v,
                   use_max_r, max_r):
    """
    Output Density / Radius.

    Physical-space density (points per unit area):
        by_density           K x (w/area)[t] x texture value (with a texture)
        count_per_primitive  (points of that prim / weighted area of that prim) x (w/area)[t]
        in_texture_space     texture-space density x uv area / 3D area
    K: without forced total it is just Density Scale; with forced total (or when clipped by Max Point Limit)
    = actual point count / ∫relative density, i.e. "derived back from the points actually scattered".
    Texture-space density = physical density x 3D area / uv area.
    Radius = 0.537 / √density, then clamped to Max Relax Radius when that is on (wording from the docs).
    """
    rel = np.where(area > 0, w / np.where(area > 0, area, 1), 0.0)[t]
    if generate == "count_per_primitive":
        phys = K[src[t]] * rel
    elif generate == "in_texture_space":
        tex = _tex_at(grid, _bary_uv(cuv, t, u, v)) if grid is not None else 1.0
        tdens = K * tex * np.ones(len(t))
        ua = _uv_area(cuv)[t]
        phys = np.where(area[t] > 0, tdens * ua / np.where(area[t] > 0, area[t], 1),
                        np.inf)
    else:
        phys = K * rel
        if grid is not None:
            phys = phys * _tex_at(grid, _bary_uv(cuv, t, u, v))
    if tex_space:
        if generate != "in_texture_space":
            if cuv is None:
                cuv = _corner_uv(tgeo, tcorner, texture_uv_attrib)
            ua = _uv_area(cuv)[t]
            tdens = np.where(ua > 0, phys * area[t] / np.where(ua > 0, ua, 1),
                             np.inf)
        d = tdens
    else:
        d = phys
    if on_d:
        out.set(POINT, on_d, d.astype(np.float32)[:, None], owned=True)
    if on_r:
        with np.errstate(divide="ignore"):
            r = np.where(d > 0, RADIUS_K_SURFACE / np.sqrt(np.where(d > 0, d, 1)),
                         np.inf)
        if use_max_r:
            r = np.minimum(r, float(max_r))
        out.set(POINT, on_r, r.astype(np.float32)[:, None], owned=True)


def _copy_prim_detail(geo, out, sp, prim_pat, det_pat, det_as_det, skip):
    """
    Attributes tab Primitive / Detail / Detail as Detail: **copied as is** by name pattern
    (no interpolation); prim attributes come from the source prim the point sits on, detail attributes are broadcast to every point. Strings are copied too.
    Houdini also accepts group names in these fields; we only copy attributes, not groups (not implemented).
    Output attributes already written (N, sourceprim ...) are not overwritten.
    """
    from .ops import match_names
    n = out.npoints
    for k in match_names(list(geo.attribs[PRIM]), prim_pat):
        if k in skip:
            continue
        out.set(POINT, k, geo.get(PRIM, k)[sp], owned=True)
    for k in match_names(list(geo.attribs[DETAIL]), det_pat):
        if k in skip:
            continue
        a = geo.get(DETAIL, k)
        out.set(POINT, k, np.repeat(a[:1], n, 0), owned=True)
    for k in match_names(list(geo.attribs[DETAIL]), det_as_det):
        out.set(DETAIL, k, geo.get(DETAIL, k), owned=False)
