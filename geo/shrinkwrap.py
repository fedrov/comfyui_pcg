"""
Shrinkwrap (pcg81): a closed hull that tightens around the shape -- "wraps the whole thing" like a convex hull, but follows into concavities that are wide enough.

━━ What "wrapping" means
Imagine a ball of radius Radius rolling in from infinity; wherever it can roll, it occupies (the ball center may not be closer than Radius
to the input surface). Hull = the boundary of the region the ball can never touch. Hence:
    · gaps, holes and grooves narrower than 2 x Radius are **bridged** (the ball cannot squeeze in)
    · concavities wider than that are followed by the hull
    · it does not matter whether the input is an open mesh, has holes, or is several interpenetrating loose pieces (triangle soup) -- as long as holes are smaller than the ball,
      the output is **one closed, manifold** mesh (collision bodies / proxy models in games, 3D-printing shells, clean
      input for Remesh)
Radius -> ∞ gives the convex hull; Radius -> 0 gives the original shape (open meshes then leak: the ball gets in through the holes).
Mathematically this is a morphological **closing** (dilate by r then erode by r); CGAL's Alpha Wrap is the same idea.

━━ Implementation
Cubic voxels (Voxel Size; the grid is aligned to integer multiples in world space, same as Remesh to Grid):
    1. **exact** unsigned distance from each grid point to the input triangles (same as volume.signed_distance)
    2. grid points with d > Radius are "where a ball center can go"; flood fill from the outer border and keep only those reachable from outside
    3. the region swept by the ball is taken as ∪ B(c, d_c) (d_c is the true distance from the ball center to the surface, see code comments):
       φ(x) = max_c (d_c − |x − c|) − Offset, solved with 3D Jump Flooding
    4. surface nets extract φ = 0 -> an all-quad mesh
    5. Project: vertices whose closest point is "exposed" (a ball of radius r fits along the direction from the closest point to the vertex) snap to
       the closest point (then pushed out by Offset along the outward normal) -- contact areas fit exactly, bridged areas keep the shape the ball
       rolled out; these points go into the point group contact
    6. Smooth: a few rounds of tangential relaxation (contact points are snapped back after relaxing)
Offset > 0 pushes the whole hull outward (leaves margin for collision bodies). Accuracy is on the order of one voxel; contact areas are exact after Project.
Cost: voxel count ∝ (size / Voxel Size)³, capped at 400³.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM
from .volume import make_volume, volume_to_polygons, signed_distance, _flood_outside


def _weighted_jfa(seed, w, h):
    """
    φ(x) = max_c (w_c − |x − c|), with c ranging over the seed cells (3D Jump Flooding, 26-neighbourhood,
    step halving from the largest power of 2 down to 1). Returns φ (same shape as seed).
    The additively weighted "nearest seed" regions (Apollonius diagram) can be disconnected, and the candidates JFA propagates from neighbours may not contain
    the true maximum, so it is **not guaranteed exact everywhere**: tests compare against brute-force pairwise max; a few cells come out low, by at most
    0.1 voxel; adding extra step-1 passes or running the whole thing twice changes nothing (the maximum for those cells is simply not on the propagation path),
    so the JFA+1 pass was removed too (mutation testing confirmed removing it makes no difference).
    The error can only make φ smaller (it picks up some real seed's value) = swept region slightly smaller = hull slightly further out, i.e. the conservative direction.
    """
    shp = seed.shape
    rz, ry, rx = shp
    Z, Y, X = np.meshgrid(np.arange(rz), np.arange(ry), np.arange(rx), indexing="ij")
    C = np.stack([Z, Y, X], -1).astype(np.float64)
    best = np.where(seed, np.arange(seed.size).reshape(shp), -1)
    score = np.where(seed, -w, np.inf)
    wf = w.reshape(-1)
    Cf = C.reshape(-1, 3)
    k = 1 << int(np.floor(np.log2(max(shp))))
    steps = []
    while k >= 1:
        steps.append(k)
        k //= 2
    offs = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)
            if (a, b, c) != (0, 0, 0)]
    for k in steps:
        for dz, dy, dx in offs:
            if abs(dz) * k >= rz or abs(dy) * k >= ry or abs(dx) * k >= rx:
                continue
            sz = slice(max(0, dz * k), rz + min(0, dz * k))
            tz = slice(max(0, -dz * k), rz + min(0, -dz * k))
            sy = slice(max(0, dy * k), ry + min(0, dy * k))
            ty = slice(max(0, -dy * k), ry + min(0, -dy * k))
            sx = slice(max(0, dx * k), rx + min(0, dx * k))
            tx = slice(max(0, -dx * k), rx + min(0, -dx * k))
            cand = best[sz, sy, sx]
            ok = cand >= 0
            if not ok.any():
                continue
            cc = np.where(ok, cand, 0)
            sc = np.linalg.norm(C[tz, ty, tx] - Cf[cc], axis=-1) * h - wf[cc]
            sc = np.where(ok, sc, np.inf)
            upd = sc < score[tz, ty, tx]
            if upd.any():
                score[tz, ty, tx] = np.where(upd, sc, score[tz, ty, tx])
                best[tz, ty, tx] = np.where(upd, cand, best[tz, ty, tx])
    return -score


def shrinkwrap(geo, voxel_size=0.05, radius=0.15, offset=0.0, project=True,
               smooth=2, smooth_strength=0.5, group=""):
    """Returns (geometry, report)."""
    from . import spatial as _sp
    from .ops import delete_prims
    from .groups import resolve
    from .topology import topology
    vs = float(voxel_size)
    r = float(radius)
    off = float(offset)
    if not vs > 0:
        raise ValueError("Voxel Size must be > 0")
    if not r > 0:
        raise ValueError("Radius must be > 0 (with a zero-size ball there is no wrapping)")
    if off < 0:
        raise ValueError("Offset cannot be negative")
    if off > r:
        raise ValueError("Offset cannot exceed Radius (the hull shrinks inward from the ball-swept boundary by Radius − Offset;"
                         " for a larger margin increase Radius as well)")
    sel = resolve(geo, PRIM, group)
    src = delete_prims(geo, sel) if not sel.all() else geo
    tri, _, _ = _sp.tri_soup(src)
    if not len(tri):
        raise ValueError("No polygon primitives to wrap")
    P0 = np.asarray(src.get(POINT, "P"), np.float64)
    used = np.unique(tri)
    # A border of ⌈r / voxel⌉ is enough: grid points x on the outermost ring are ≥ r from the bounding box, so d(x) ≥ r, and x is itself a
    # reachable ball center, φ(x) ≥ d(x) − Offset ≥ r − Offset ≥ 0 -- the hull lies strictly inside the grid and closes.
    # (It used to be (r + Offset) / voxel + 3; mutation testing said the extra was redundant, and working it out confirms it)
    pad = int(np.ceil(r / vs))
    # The grid is aligned to integer multiples of Voxel Size (world space). float32 points dividing to things like 31.0000014 make ceil
    # add one layer of cells -- an extra empty layer does not affect the result (grid points stay on the same world grid), so ignore it
    mn = np.floor(P0[used].min(0) / vs) - pad
    mx = np.ceil(P0[used].max(0) / vs) + pad
    res = (mx - mn + 1).astype(np.int64)
    if np.prod(res) > 400 ** 3:
        raise ValueError(f"Too many voxels ({res.tolist()}), increase Voxel Size")
    origin = mn * vs
    cell = np.full(3, vs)
    d = signed_distance(P0, tri.astype(np.int64), origin, cell,
                        tuple(int(x) for x in res), 2.5, unsigned=True)
    # A ball exactly touching the surface (d = r) also counts as fitting. Loosen by 1e-4 voxel: grid points exactly r from the surface are very common
    # (box faces land on grid points), and a 1e-7 difference in float32 points flips them either way, so results stop matching after translating by whole voxels
    free = d >= r - 1e-4 * vs
    reach = _flood_outside(free)
    if not reach.any():
        raise ValueError("The ball fits at not a single grid point from outside (Radius too large, or Voxel Size too coarse?)")
    # Region swept by the ball = ∪ B(c, d_c), c ranging over reachable ball centers. Use d_c (true distance from ball center to surface,
    # ≥ r) rather than r as the radius: B(c, d_c) contains no surface, so all of it can be swept by a ball of radius r, i.e. it is
    # a subset of the exact swept region; and because it just touches the surface, in contact areas the hull lies **exactly** on the surface.
    # The first version used "distance to a ball-center cell ≤ r" (separable EDT), which discretized ball centers to grid points, so at fillets the hull
    # shifted outward by a voxel diagonal (a fillet of radius 0.5 measured 0.43)
    phi = _weighted_jfa(reach, d, vs) - off
    tiny = 1e-4 * vs
    phi = np.where(np.abs(phi) < tiny, tiny, phi)       # same as Remesh to Grid: ambiguity when a grid point lies exactly on the surface
    size = (res - 1) * vs
    vol = make_volume(tuple(int(x) for x in res), size, origin + size / 2)
    vol.set_pdata(0, "voxels", phi.astype(np.float32))
    g = volume_to_polygons(vol, 0.0)
    rep = {"resolution": res.tolist(), "reachable_voxels": int(reach.sum())}
    if not g.npoints:
        raise ValueError("No hull extracted (Radius − Offset smaller than one voxel?)")
    V = np.asarray(g.get(POINT, "P"), np.float64)
    F4 = np.asarray(g.vertex_point, np.int64).reshape(-1, 4)
    contact = np.zeros(len(V), bool)

    def snap(V):
        # Snap only when the closest point is "exposed": place a ball of radius r in the direction from the closest point
        # to the vertex; it counts only if the ball does not touch the surface. For vertices on a fillet (bridge) near the tangent point, the closest point is on the face
        # under the fillet -- no ball fits there, no snapping, so the fillet shape is kept; on convex corners the closest point is the corner itself,
        # the ball fits, it snaps, and the corner surface nets cut off comes back
        _, dd, cp, _ = _sp.closest_surface(V, P0, tri)
        u = V - cp
        ln = np.linalg.norm(u, axis=1, keepdims=True)
        u = np.where(ln > 1e-12, u / np.maximum(ln, 1e-300), 0.0)
        # Only consider points within Offset + r of the surface: for points further away, "a ball fits at the closest point" does not imply they belong on the closest point.
        # The threshold itself does not matter -- the exposure test is the criterion (it started as "one voxel" and was changed to 3 voxels, mutation testing
        # gives the same result): for a hull point V with closest point cp, if a ball of radius r fits along cp->V, V is inside that ball
        # and hence inside the swept region, which is only possible if V = cp
        c = dd <= off + r
        if c.any():
            # A vertex may be slightly inside the surface (discretization error; where surface nets cut off convex edges it is 0.67 voxel from the face),
            # in which case u points inward -- points less than one voxel from the surface try both directions
            # and use the one where the ball fits. Points further away must not try the reverse: on an open box, the part of the hull dipping into the opening
            # has its closest point on the inner side of the thin wall, and the reverse (outside the wall) of course fits a ball, so trying it would snap everything onto the wall
            idx = np.nonzero(c)[0]
            tol = r - 1e-4 * vs
            fit_p = _sp.closest_surface(cp[idx] + r * u[idx], P0, tri)[1] >= tol
            fit_m = (_sp.closest_surface(cp[idx] - r * u[idx], P0, tri)[1] >= tol) \
                & (dd[idx] <= vs)
            flip = ~fit_p & fit_m
            u[idx[flip]] *= -1.0
            c[idx] = fit_p | fit_m | (ln[idx, 0] <= 1e-12)
        W = np.where(c[:, None], cp + off * u, V)
        return W, c
    if project:
        V, contact = snap(V)
    if int(smooth) > 0:
        from .remesh import _relax
        F3 = np.concatenate([F4[:, [0, 1, 2]], F4[:, [0, 2, 3]]])
        for _ in range(int(smooth)):
            V = _relax(V, F3, np.ones(len(V), bool), float(smooth_strength))
            if project:
                V2, _ = snap(V)
                V = np.where(contact[:, None], V2, V)
    out = g.copy()
    out.set(POINT, "P", V.astype(np.float32), owned=True)
    out.set_group(POINT, "contact", contact)
    t = topology(out)
    rep.update({"points": int(out.npoints), "prims": int(out.nprims),
                "contact_points": int(contact.sum()),
                "boundary_edges": int(t.boundary.sum()),
                "nonmanifold_edges": int((t.edge_count > 2).sum())})
    return out, rep
