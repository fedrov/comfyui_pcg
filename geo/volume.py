"""
Dense volumes.

Storage: a volume prim has **one vertex** (a point at the volume's centre), as in Houdini.
The prim attributes res (resolution, 3 ints) and vsize (world size, 3 floats) define the sample grid;
the voxel array itself lives in the side channel prim_data[i]["voxels"], shape (rz, ry, rx) float32.

Voxel data must go through the side channel: its length differs per prim, while attribute tables are fixed-size (N,C) arrays.

Isosurface extraction uses **surface nets**, not marching cubes. Reasons:
  · marching cubes needs a 256-entry triangle lookup table; surface nets needs no table at all
  · surface nets naturally produces quads, which fits this model's CSR topology better
  · its vertices sit inside cells rather than on edges, so topology is more regular and a later subdivide works better
The cost is that sharp features get rounded a little, which does not matter for fog/SDF uses.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_VOLUME


def make_volume(res, size, center=(0, 0, 0), fill=0.0, fog=False) -> Geometry:
    """
    Create an empty volume prim.

    fog marks the field's polarity: SDF is positive outside, fog (density) is positive inside. This difference must
    be recorded -- when the isosurface is oriented by the gradient the two have opposite outward directions; guessing leaves half the faces
    pointing inward, with no error, only visible when shading.
    """
    rx, ry, rz = [max(2, int(v)) for v in res]
    g = Geometry.from_points(np.asarray([center], np.float32))
    g.set_topology(np.zeros(1, np.int32), np.array([0, 1], np.int32),
                   np.zeros(1, bool), np.array([PRIM_VOLUME], np.uint8))
    g.set(PRIM, "res", np.array([[rx, ry, rz]], np.int32), owned=True)
    g.set(PRIM, "vsize", np.array([list(size)], np.float32), owned=True)
    g.set(PRIM, "fog", np.array([[1 if fog else 0]], np.int32), owned=True)
    g.set_pdata(0, "voxels", np.full((rz, ry, rx), float(fill), np.float32))
    return g


def volume_info(geo, i):
    """Returns (voxels, origin, cell) -- the voxel array, grid origin and voxel size."""
    vox = geo.pdata(i, "voxels")
    if vox is None:
        return None
    res = geo.get(PRIM, "res")[i].astype(np.int64)
    size = geo.get(PRIM, "vsize")[i].astype(np.float64)
    ctr = geo.get(POINT, "P")[geo.prim_points(i)[0]].astype(np.float64)
    cell = size / np.maximum(res - 1, 1)
    return vox, ctr - size * 0.5, cell


def points_to_volume(geo, res=(32, 32, 32), radius=0.0, pad=0.15,
                     attribute="", group=None) -> Geometry:
    """
    Point cloud -> density volume (fog). Each point is splatted as a sphere by its radius.

    Splatting "iterates over points and writes only the small block covered by its radius", instead of querying
    the nearest point for every voxel -- the latter is O(voxels × points), the former O(points × kernel volume); for sparse
    point clouds it is orders of magnitude faster.
    """
    from . import groups as _grp
    mask = _grp.resolve(geo, POINT, group)
    P = geo.get(POINT, "P")[mask].astype(np.float64)
    if not len(P):
        raise RuntimeError("No points to rasterize (check group)")

    rx, ry, rz = [max(2, int(v)) for v in res]
    mn, mx = P.min(0), P.max(0)
    ext = np.maximum(mx - mn, 1e-6)
    mn -= ext * pad
    mx += ext * pad
    size = mx - mn
    cell = size / np.array([rx - 1, ry - 1, rz - 1])
    if radius <= 0:
        radius = float(cell.max() * 1.5)

    w = geo.get(POINT, attribute)
    w = (w[mask][:, 0].astype(np.float64) if (attribute and w is not None)
         else np.ones(len(P)))

    vox = np.zeros((rz, ry, rx), np.float32)
    ridx = np.ceil(radius / cell).astype(int)
    ox = np.arange(-ridx[0], ridx[0] + 1)
    oy = np.arange(-ridx[1], ridx[1] + 1)
    oz = np.arange(-ridx[2], ridx[2] + 1)
    dz, dy, dx = np.meshgrid(oz, oy, ox, indexing="ij")
    # actual distance from each kernel offset to the centre, used for the falloff
    dist = np.sqrt((dx * cell[0]) ** 2 + (dy * cell[1]) ** 2 + (dz * cell[2]) ** 2)
    kern = np.clip(1.0 - dist / radius, 0.0, 1.0) ** 2      # smooth falloff
    ker_flat = kern.reshape(-1)
    ddx, ddy, ddz = dx.reshape(-1), dy.reshape(-1), dz.reshape(-1)

    base = np.round((P - mn) / cell).astype(np.int64)
    for k in range(len(ker_flat)):
        if ker_flat[k] <= 0:
            continue
        ix = base[:, 0] + ddx[k]
        iy = base[:, 1] + ddy[k]
        iz = base[:, 2] + ddz[k]
        ok = ((ix >= 0) & (ix < rx) & (iy >= 0) & (iy < ry) &
              (iz >= 0) & (iz < rz))
        if not ok.any():
            continue
        np.add.at(vox, (iz[ok], iy[ok], ix[ok]), (w[ok] * ker_flat[k]).astype(np.float32))

    g = make_volume((rx, ry, rz), size, mn + size * 0.5, fog=True)
    g.set_pdata(0, "voxels", vox)
    return g


def mesh_to_volume(geo, res=(32, 32, 32), pad=0.15, group=None,
                   band=2.5) -> Geometry:
    """
    Polygons -> signed distance field (SDF, positive outside, negative inside). **Exact** since pcg72.

    ━━ The old approach and its problems
    Random points were scattered on the triangles and each voxel took the distance to the nearest sample; the sign came from a "shell" plus flood
    fill. The distance error was about half a voxel, and **wavy** (from the density of the random points) -- the values were passable,
    but the gradient within one or two voxels of the surface could be off by tens of degrees (the pcg71 tests measured this).

    ━━ Now: exact narrow band + jump flooding (JFA) + pseudo-normal sign
    1. Narrow band: each triangle's bounding box is expanded by band voxels, and every grid point in the box computes the **exact**
       point-to-triangle distance to that triangle (Ericson's seven regions); each grid point keeps the nearest.
       No BVH; pairing is one "expand by bounding box" repeat, chunked to bound memory
    2. Outside the narrow band: JFA propagates the band grid points' "nearest surface point" step by step (step N/2, N/4, ..., 1); each grid point takes, among the nearest points brought by its neighbours, the one nearest to itself. Distance = the true distance to that
       surface point (computed exactly once more against the triangle it came from) -- an upper bound of the true distance,
       measured < 0.08 voxel from brute force (exact inside the band, off by 1e-6, just float32)
    3. Sign: inside the band, Bærentzen–Aanæs **angle-weighted pseudo-normals** (nearest point inside a face uses the face
       normal, on an edge the sum of the two adjacent face normals, on a vertex the angle-weighted vertex normal):
       for a closed manifold mesh the sign of (x − nearest point)·pseudo-normal is inside/outside, without exception. Outside the band
       flood fill is used (flooding inward from the border, with band grid points at d <= half a voxel acting as walls: if two adjacent grid points
       are separated by the surface, at least one of them is within half a voxel of it, so the wall is 6-connected and sealed).
       When the mesh is not a closed manifold (boundary edges or non-manifold edges) pseudo-normals are not guaranteed correct, and the whole field uses
       the flood fill sign; wall grid points (undecidable by flooding) use the generalized winding number (sum of solid angles / 4π).
       An open mesh lets the flood in, so everything is positive (unsigned distance)
    """
    from . import groups as _grp
    from . import ops as _ops
    from . import spatial as _sp
    sel = _grp.resolve(geo, PRIM, group)
    src = _ops.delete_prims(geo, sel) if geo.nprims else geo
    tri, _, _ = _sp.tri_soup(src) if src.nprims else (None, None, None)
    if tri is None or not len(tri):
        raise RuntimeError("No usable triangles (Convert NURBS to polygons first)")

    rx, ry, rz = [max(2, int(v)) for v in res]
    P = src.get(POINT, "P").astype(np.float64)
    used = np.unique(tri)
    mn, mx = P[used].min(0), P[used].max(0)
    ext = np.maximum(mx - mn, 1e-6)
    mn -= ext * pad
    mx += ext * pad
    size = mx - mn
    cell = size / np.array([rx - 1, ry - 1, rz - 1])
    sdf = signed_distance(P, tri.astype(np.int64), mn, cell, (rx, ry, rz),
                          float(band))
    g = make_volume((rx, ry, rz), size, mn + size * 0.5)
    g.set_pdata(0, "voxels", sdf.astype(np.float32))
    return g


def _pseudonormals(P, tri):
    """Face normals, edge normals (sum of the two adjacent faces), angle-weighted vertex normals; and whether the mesh is closed."""
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    fn = np.cross(B - A, C - A)
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = np.where(ln > 0, fn / np.where(ln > 0, ln, 1), 0.0)
    vn = np.zeros_like(P)
    for k in range(3):
        a, b, c = tri[:, k], tri[:, (k + 1) % 3], tri[:, (k + 2) % 3]
        e1, e2 = P[b] - P[a], P[c] - P[a]
        cosang = np.einsum("ij,ij->i", e1, e2) / np.maximum(
            np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1), 1e-300)
        ang = np.arccos(np.clip(cosang, -1, 1))
        np.add.at(vn, a, fn * ang[:, None])
    E = np.sort(np.stack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]], 1),
                axis=2).reshape(-1, 2)                      # (3T,2):ab, bc, ca
    key = E[:, 0] * (len(P) + 1) + E[:, 1]
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    en_u = np.zeros((len(uk), 3))
    np.add.at(en_u, inv, np.repeat(fn, 3, axis=0))
    en = en_u[inv].reshape(-1, 3, 3)                        # (T, edge ab/bc/ca, 3)
    closed = bool((cnt == 2).all())
    return fn, en, vn, closed


def signed_distance(P, tri, origin, cell, res, band=2.5, unsigned=False, far_field=True):
    """
    SDF of shape (rz,ry,rx). See mesh_to_volume's notes. unsigned=True returns distance only.

    far_field=False: only the narrow band (|d| <= band voxels) gets exact distances; everything outside it is ±inf
    (the sign is still right). For callers that clamp to the band anyway (VDB from Polygons without Fill Interior) this
    skips the jump-flood pass over the whole grid.
    """
    from .spatial import closest_on_tri
    rx, ry, rz = res
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    # Expand by the largest voxel size -- "is it inside the band" below is judged by it too; expanding each axis by its own size
    # would leave grid points closer than band to a triangle unpaired with it on anisotropic grids
    ext = band * float(np.max(cell))
    lo = np.minimum(np.minimum(A, B), C) - ext
    hi = np.maximum(np.maximum(A, B), C) + ext
    ilo = np.clip(np.ceil((lo - origin) / cell - 1e-9).astype(np.int64), 0,
                  [rx - 1, ry - 1, rz - 1])
    ihi = np.clip(np.floor((hi - origin) / cell + 1e-9).astype(np.int64), 0,
                  [rx - 1, ry - 1, rz - 1])
    span = np.maximum(ihi - ilo + 1, 0)
    cnt = span.prod(1)
    N = rx * ry * rz
    best = np.full(N, np.inf)
    btri = np.full(N, -1, np.int64)
    bvw = np.zeros((N, 2))
    order = np.arange(len(tri))
    lim = 3_000_000
    cmin = np.full(N, np.inf)            # per-chunk scatter-min buffer; reset after each chunk
    # Bounding sphere of each triangle: a grid point farther than radius + band from its centre cannot be within the band
    # of that triangle, so the pair is dropped before the exact closest-point test. The AABB expanded by the band is a
    # cube around a ball -- about half of its grid points fail this test for small triangles. Dropped pairs are never
    # in-band, and only in-band pairs reach the output, so the result is bit-identical.
    tcen = (A + B + C) / 3.0
    trad = np.sqrt(np.max(np.stack([((X - tcen) ** 2).sum(1) for X in (A, B, C)], 1), 1))
    reach = band * float(np.max(cell)) * (1 + 1e-9)
    s = 0
    while s < len(order):                                  # chunk by pair count
        e = s
        tot = 0
        while e < len(order) and (tot + cnt[order[e]] <= lim or e == s):
            tot += cnt[order[e]]
            e += 1
        ids = order[s:e]
        s = e
        c = cnt[ids]
        if not c.sum():
            continue
        owner = np.repeat(ids, c)
        off = np.concatenate([[0], np.cumsum(c)])
        local = np.arange(int(c.sum())) - np.repeat(off[:-1], c)
        sx = np.repeat(span[ids, 0], c)
        sy = np.repeat(span[ids, 1], c)
        ix = ilo[owner, 0] + local % sx
        iy = ilo[owner, 1] + (local // sx) % sy
        iz = ilo[owner, 2] + local // (sx * sy)
        q = origin + np.stack([ix, iy, iz], 1) * cell
        dc = q - tcen[owner]
        keep = np.einsum("ij,ij->i", dc, dc) <= (trad[owner] + reach) ** 2
        if not keep.all():
            owner, ix, iy, iz, q = owner[keep], ix[keep], iy[keep], iz[keep], q[keep]
            if not len(owner):
                continue
        a, b, cc = A[owner], B[owner], C[owner]
        ab, ac = b - a, cc - a
        ap, bp, cp = q - a, q - b, q - cc
        v, w = closest_on_tri(
            q, ab, ac, np.einsum("ij,ij->i", ab, ap),
            np.einsum("ij,ij->i", ac, ap), np.einsum("ij,ij->i", ab, bp),
            np.einsum("ij,ij->i", ac, bp), np.einsum("ij,ij->i", ab, cp),
            np.einsum("ij,ij->i", ac, cp))
        d = np.linalg.norm(a + v[:, None] * ab + w[:, None] * ac - q, axis=1)
        flat = (iz * ry + iy) * rx + ix
        # Per grid point keep the closest pair of this chunk (scatter-min instead of a lexsort: ~3x faster).
        # Ties go to the first pair, and an earlier chunk keeps the point unless this one is strictly closer --
        # the same choices the sort made.
        np.minimum.at(cmin, flat, d)
        k = np.nonzero((d == cmin[flat]) & (d < best[flat]))[0][::-1]   # reversed: the first pair is written last
        cmin[flat] = np.inf
        fu = flat[k]
        best[fu] = d[k]
        btri[fu] = owner[k]
        bvw[fu] = np.c_[v[k], w[k]]

    Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx),
                          indexing="ij")
    Xw = origin + np.stack([X, Y, Z], -1).reshape(-1, 3) * cell
    inband = best <= band * float(cell.max())
    # nearest surface point
    cpt = np.full((N, 3), np.nan)
    t = btri[inband]
    vw = bvw[inband]
    cpt[inband] = A[t] + vw[:, :1] * (B[t] - A[t]) + vw[:, 1:] * (C[t] - A[t])
    # -- band sign: pseudo-normals
    fn, en, vn, closed = _pseudonormals(P, tri)
    sgn = np.ones(N)
    if inband.any() and not unsigned:
        v, w = vw[:, 0], vw[:, 1]
        eps = 1e-9
        pn = fn[t].copy()
        on_ab = (w <= eps)
        on_ac = (v <= eps)
        on_bc = (v + w >= 1 - eps)
        pn = np.where(on_ab[:, None], en[t, 0], pn)
        pn = np.where(on_bc[:, None], en[t, 1], pn)
        pn = np.where(on_ac[:, None], en[t, 2], pn)
        va = on_ab & on_ac
        vb = on_ab & on_bc
        vc = on_ac & on_bc
        pn = np.where(va[:, None], vn[tri[t, 0]], pn)
        pn = np.where(vb[:, None], vn[tri[t, 1]], pn)
        pn = np.where(vc[:, None], vn[tri[t, 2]], pn)
        side = np.einsum("ij,ij->i", Xw[inband] - cpt[inband], pn)
        sgn[inband] = np.where(side < 0, -1.0, 1.0)
    # -- distance outside the band: JFA propagates the nearest surface point
    cp3 = cpt.reshape(rz, ry, rx, 3)
    tr3 = np.where(inband, btri, -1).reshape(rz, ry, rx)
    X3 = Xw.reshape(rz, ry, rx, 3)
    D = np.where(inband, best, np.inf).reshape(rz, ry, rx)
    if far_field and (~inband).any() and inband.any():
        k = 1 << int(np.floor(np.log2(max(rx, ry, rz))))
        steps = []
        while k >= 1:
            steps.append(k)
            k //= 2
        # The two extra step-1 passes of JFA+1 are not added: after the exact recompute against the carried triangle below,
        # measured no difference (sphere 28³: max error 0.0787 vs 0.0794 voxel)
        offs = [(dz, dy, dx) for dz in (-1, 0, 1) for dy in (-1, 0, 1)
                for dx in (-1, 0, 1) if (dz, dy, dx) != (0, 0, 0)]
        for k in steps:
            for dz, dy, dx in offs:
                if abs(dz) * k >= rz or abs(dy) * k >= ry or abs(dx) * k >= rx:
                    continue                    # this step goes beyond the whole grid (the slice would get negative indices)
                sz = slice(max(0, dz * k), rz + min(0, dz * k))
                tz = slice(max(0, -dz * k), rz + min(0, -dz * k))
                sy_ = slice(max(0, dy * k), ry + min(0, dy * k))
                ty = slice(max(0, -dy * k), ry + min(0, -dy * k))
                sx_ = slice(max(0, dx * k), rx + min(0, dx * k))
                tx = slice(max(0, -dx * k), rx + min(0, -dx * k))
                cand = cp3[sz, sy_, sx_]
                dt = D[tz, ty, tx]                          # basic slices: views, written in place below
                dd = np.linalg.norm(X3[tz, ty, tx] - cand, axis=-1)
                upd = dd < dt                               # nan comparisons are always False
                if upd.any():
                    # masked in-place writes instead of rebuilding three whole slices with np.where; the
                    # right-hand sides are copies (fancy indexing), so overlapping source / target slices still
                    # read the values from before this step, exactly as before
                    newc = cand[upd]
                    newt = tr3[sz, sy_, sx_][upd]
                    dt[upd] = dd[upd]
                    cp3[tz, ty, tx][upd] = newc
                    tr3[tz, ty, tx][upd] = newt
    D = D.reshape(-1)
    # Outside the band: what is carried over is only "some surface point"; the true nearest point is usually elsewhere on the same triangle --
    # so compute exactly once more against the carried triangle (can only get closer, never farther)
    far = (~inband) & (tr3.reshape(-1) >= 0)
    if far.any():
        t2 = tr3.reshape(-1)[far]
        q = Xw[far]
        a, b, cc = A[t2], B[t2], C[t2]
        ab, ac = b - a, cc - a
        ap, bp, cp_ = q - a, q - b, q - cc
        v2, w2 = closest_on_tri(
            q, ab, ac, np.einsum("ij,ij->i", ab, ap),
            np.einsum("ij,ij->i", ac, ap), np.einsum("ij,ij->i", ab, bp),
            np.einsum("ij,ij->i", ac, bp), np.einsum("ij,ij->i", ab, cp_),
            np.einsum("ij,ij->i", ac, cp_))
        d2 = np.linalg.norm(a + v2[:, None] * ab + w2[:, None] * ac - q, axis=1)
        D[far] = np.minimum(D[far], d2)
    if unsigned:
        return D.reshape(rz, ry, rx)
    # -- sign outside the band (or for non-closed meshes): flood fill
    wall = (best <= 0.5 * float(cell.max()) * (1 + 1e-6)).reshape(rz, ry, rx)
    outside = _flood_outside(~wall)
    inside = (~wall) & (~outside)
    flood_sgn = np.where(outside, 1.0, -1.0).reshape(-1)
    if closed:
        sgn = np.where(inband, sgn, flood_sgn)
    else:
        # Wall grid points (within half a voxel of the surface) cannot be decided by flood fill. Use the **generalized winding number**:
        # the sum of solid angles subtended by all triangles at the point / 4π -- for non-manifold but closed meshes (two cubes sharing
        # an edge) it is 1 inside and 0 outside, independent of manifold adjacency. There are not many wall grid points
        # (surface area / voxel²), so per-triangle evaluation is affordable. If flooding finds no "inside" it is an open mesh, and all of it is positive
        w = wall.reshape(-1)
        if inside.any() and w.any():
            wn = _winding(Xw[w], A, B, C)
            wsg = np.where(wn > 0.5, -1.0, 1.0)
        else:
            wsg = np.ones(int(w.sum()))
        sgn = flood_sgn.copy()
        sgn[w] = wsg
    return (sgn * D).reshape(rz, ry, rx)


def _winding(Q, A, B, C):
    """Generalized winding number (Van Oosterom–Strackee solid-angle formula), chunked."""
    out = np.zeros(len(Q))
    step = max(1, 4_000_000 // max(len(A), 1))
    for s in range(0, len(Q), step):
        q = Q[s:s + step, None, :]
        a, b, c = A[None] - q, B[None] - q, C[None] - q
        la, lb, lc = (np.linalg.norm(x, axis=2) for x in (a, b, c))
        num = np.einsum("qtk,qtk->qt", a, np.cross(b, c))
        den = la * lb * lc + np.einsum("qtk,qtk->qt", a, b) * lc + \
            np.einsum("qtk,qtk->qt", b, c) * la + np.einsum("qtk,qtk->qt", c, a) * lb
        out[s:s + step] = (2 * np.arctan2(num, den)).sum(1) / (4 * np.pi)
    return out


def _flood_outside(free):
    """Flood the free region 6-connected from the border; return the reachable cells."""
    try:
        from scipy import ndimage
        lab, _ = ndimage.label(free)
        border = np.unique(np.concatenate([
            lab[0].ravel(), lab[-1].ravel(), lab[:, 0].ravel(),
            lab[:, -1].ravel(), lab[:, :, 0].ravel(), lab[:, :, -1].ravel()]))
        border = border[border > 0]
        return np.isin(lab, border)
    except ImportError:
        pass
    out = np.zeros_like(free)
    out[0], out[-1] = free[0], free[-1]
    out[:, 0] |= free[:, 0]
    out[:, -1] |= free[:, -1]
    out[:, :, 0] |= free[:, :, 0]
    out[:, :, -1] |= free[:, :, -1]
    while True:
        g = out.copy()
        g[1:] |= out[:-1]
        g[:-1] |= out[1:]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        g[:, :, 1:] |= out[:, :, :-1]
        g[:, :, :-1] |= out[:, :, 1:]
        g &= free
        if np.array_equal(g, out):
            return out
        out = g


def volume_to_polygons(geo, iso=0.0, group=None, close=False, prims=None) -> Geometry:
    """
    Isosurface extraction (surface nets). Non-volume prims are kept as they are.

    Each cell with a sign change gets one vertex, positioned at the average of the zero crossings on its 12 edges;
    then for each edge with a sign change, the vertices of the 4 cells around it are joined into a quad.

    close (pcg106): treat everything beyond the grid as "outside" (an SDF / fog background), so a surface the
    grid boundary cuts through is capped with a flat face on the boundary instead of being left open. The grid is
    padded with one layer of outside samples and the vertices are clamped back onto the bounding box. This is how a
    VDB behaves (beyond its active region is background), and what the viewport uses for display.
    prims: only these volume prim indices (None = all selected by group); vector volumes are skipped.
    """
    from . import groups as _grp
    from . import ops as _ops
    sel = _grp.resolve(geo, PRIM, group)
    isv = sel & (geo.prim_type == PRIM_VOLUME)
    if not isv.any():
        return geo.copy()

    parts = [_ops.delete_prims(geo, ~isv)] if (~isv).any() else []
    EDGES = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3),
             (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
    CORN = np.array([(i & 1, (i >> 1) & 1, (i >> 2) & 1) for i in range(8)])

    fogm = geo.get(PRIM, "fog")
    for pi in np.nonzero(isv)[0]:
        if prims is not None and int(pi) not in prims:
            continue
        info = volume_info(geo, pi)
        if info is None or np.ndim(info[0]) != 3:
            continue
        vox, origin, cell = info
        f = np.asarray(vox, np.float64) - float(iso)
        is_fog = fogm is not None and int(fogm[pi, 0]) == 1
        lo_box, hi_box = origin, origin + cell * (np.array(vox.shape[::-1]) - 1)
        if close:
            # outside = positive for an SDF (and "none" grids), non-positive for fog (density below the iso value)
            big = float(np.max(np.abs(f))) + 1.0
            f = np.pad(f, 1, constant_values=(-big if is_fog else big))
            origin = origin - cell
        rz, ry, rx = f.shape

        # values at each cell's eight corners
        corner = np.stack([f[c[2]:c[2] + rz - 1, c[1]:c[1] + ry - 1,
                             c[0]:c[0] + rx - 1] for c in CORN], -1)
        sign = corner > 0
        active = sign.any(-1) & (~sign.all(-1))          # surface cells have both positive and negative
        if not active.any():
            continue

        acc = np.zeros(corner.shape[:3] + (3,), np.float64)
        cnt = np.zeros(corner.shape[:3], np.float64)
        for e0, e1 in EDGES:
            v0, v1 = corner[..., e0], corner[..., e1]
            cross = (v0 > 0) != (v1 > 0)
            if not cross.any():
                continue
            t = np.where(cross, v0 / np.where(v0 - v1 == 0, 1e-9, v0 - v1), 0.0)
            p = CORN[e0] + t[..., None] * (CORN[e1] - CORN[e0])
            acc += np.where(cross[..., None], p, 0.0)
            cnt += cross
        cnt = np.maximum(cnt, 1e-9)
        local = acc / cnt[..., None]

        ci, cj, ck = np.nonzero(active)          # z, y, x
        vid = np.full(active.shape, -1, np.int64)
        vid[ci, cj, ck] = np.arange(len(ci))
        pts = (np.stack([ck, cj, ci], -1) + local[ci, cj, ck]) * cell + origin
        if close:
            pts = np.clip(pts, lo_box, hi_box)

        faces = []
        # Array indices are (z, y, x), so axis ax (0=x, 1=y, 2=z) maps to index 2-ax,
        # and the perpendicular plane is the other two indices. It used to be written ((1,2),(0,2),(0,1)), swapping x and z,
        # so the quads spanned the wrong cells.
        for ax, (d0, d1) in enumerate(((0, 1), (0, 2), (1, 2))):
            # edges along ax: the two end corners are 0 and 1<<ax
            v0 = corner[..., 0]
            v1 = corner[..., 1 << ax]
            cross = (v0 > 0) != (v1 > 0)
            idx = np.nonzero(cross)
            if not len(idx[0]):
                continue
            offs = [(0, 0, 0)]
            o1 = [0, 0, 0]; o1[d0] = -1
            o2 = [0, 0, 0]; o2[d1] = -1
            o3 = [0, 0, 0]; o3[d0] = -1; o3[d1] = -1
            quad = []
            ok = np.ones(len(idx[0]), bool)
            for off in (offs[0], tuple(o1), tuple(o3), tuple(o2)):
                z = idx[0] + off[0]; y = idx[1] + off[1]; x = idx[2] + off[2]
                inb = (z >= 0) & (y >= 0) & (x >= 0)
                z = np.clip(z, 0, vid.shape[0] - 1)
                y = np.clip(y, 0, vid.shape[1] - 1)
                x = np.clip(x, 0, vid.shape[2] - 1)
                q = vid[z, y, x]
                ok &= inb & (q >= 0)
                quad.append(q)
            if ok.any():
                faces.append(np.stack([q[ok] for q in quad], 1))

        if not faces:
            continue
        fq = np.concatenate(faces).astype(np.int32)

        # Winding is **oriented by the field gradient**, not by hand-deriving the index handedness per axis.
        # The perpendicular planes of the three axes each have their own right-hand order, easy to get wrong by hand (and when wrong it only shows as
        # half the faces pointing inward, no error). The gradient is a ready, unambiguous ground truth: the normal should point
        # toward increasing field value; if the dot product is negative, flip the quad.
        fc = pts[fq].mean(1)
        n = np.cross(pts[fq[:, 1]] - pts[fq[:, 0]],
                     pts[fq[:, 2]] - pts[fq[:, 0]])
        gi = np.clip(np.round((fc - origin) / cell).astype(int), 1,
                     np.array([rx, ry, rz]) - 2)
        grad = np.stack([
            f[gi[:, 2], gi[:, 1], gi[:, 0] + 1] - f[gi[:, 2], gi[:, 1], gi[:, 0] - 1],
            f[gi[:, 2], gi[:, 1] + 1, gi[:, 0]] - f[gi[:, 2], gi[:, 1] - 1, gi[:, 0]],
            f[gi[:, 2] + 1, gi[:, 1], gi[:, 0]] - f[gi[:, 2] - 1, gi[:, 1], gi[:, 0]],
        ], -1)
        # a fog field is positive inside and its gradient points inward, so the outward direction must be flipped
        pol = -1.0 if is_fog else 1.0
        flip = (n * grad).sum(1) * pol < 0
        fq[flip] = fq[flip][:, ::-1]

        parts.append(Geometry.from_mesh(pts.astype(np.float32), fq))

    return _ops.merge(*parts) if parts else Geometry()
