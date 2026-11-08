"""
UV Flatten -- LSCM conformal flattening. Mirrors Houdini's UV Flatten.

Projections can only handle things that are "roughly a plane/cylinder/sphere". Really unwrapping UVs for an arbitrary shape means solving an
optimization problem: find (u,v) such that each triangle mapped from 3D to 2D is **as close as possible to just rotation + scaling, no shear**.
That is Lévy 2002's LSCM (Least Squares Conformal Maps), still the default UV unwrapping algorithm
almost everywhere.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Conformal = the Cauchy-Riemann equations, and they are **linear**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Lay the triangle flat in its own local 2D coordinate system, and treat (u,v) as a complex number w = u + iv. The map
is conformal if and only if ∂w/∂z̄ = 0 -- expanded into reals that is two **linear** equations:

    ∂u/∂x = ∂v/∂y        ∂u/∂y = -∂v/∂x

On a linear triangle the gradient is constant, so each triangle gives 2 equations in 6 unknowns
(u and v of its 3 corners). **The whole thing is one sparse least-squares problem**, not iterative optimization -- that is why LSCM
is much cheaper than nonlinear methods like ABF/ARAP, and why it has not been replaced in over twenty years.

Coefficients are normalized by √(2·area): without it a large triangle's say in the energy is proportional to its area,
small triangles can distort however they like, and fine detail turns to mush.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two points must be pinned, not one fewer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The conformal energy is invariant under **similarity transforms**: global translation (2 degrees of freedom), rotation (1) and scaling (1)
all leave the energy unchanged. So the system has a 4-dimensional null space, and solving it directly gives the trivial solution "everything collapses to one point" --
whose energy really is 0.

Pinning two points removes exactly these 4 degrees of freedom. Which two matters: **pick the farthest pair**. Picking two nearby
points means fixing the scale and orientation of the whole patch with a very short segment, which numerically amplifies errors by several orders of magnitude.
This uses two farthest-point passes (pick any point, find its farthest point, then the farthest point from there).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Seams" do not require actually cutting the geometry
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Flattening needs a surface **with a boundary** (a sphere cannot be flattened; that is Gauss's Theorema Egregium). The usual approach is to cut the geometry along
seams, but that changes the point count and scrambles downstream point numbers.

No cutting here: the unknowns are not "points" but **wedges** (equivalence classes of corners) -- two corners belong to the same
wedge if and only if they are on the same geometric point and the edge between them is **not** a seam. The two sides of a seam
are naturally two different wedges, each with its own (u,v). Not one point of the geometry moves, and since uv is a
vertex attribute anyway, it can store them.

This also explains why uv must be a vertex attribute: the wedge is its reason to exist.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Solver: CGNR + Jacobi preconditioning, the matrix is never assembled explicitly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sparse least squares means either scipy or writing it yourself. The convention here is no added dependencies, so it is hand-written:

    M stored as COO triplets (row, column, value)
    Mx  = np.bincount(row, weights=value * x[column])
    Mᵀy = np.bincount(column, weights=value * y[row])

The normal equations A = MᵀM are symmetric positive definite, solvable directly by conjugate gradient, and **A never has to be multiplied out** --
each step needs only two bincounts. The cost is κ(MᵀM) = κ(M)², i.e. slow convergence; Jacobi preconditioning with diag(MᵀM)
helps a great deal (diag is also a single bincount).

See the README for measurements.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string
from .groups import resolve, resolve_edges, edge_mask
from .topology import topology


def _jump(lab, a, b, rounds=64):
    """Label merging by pointer jumping, the same as Connectivity."""
    if not len(a):
        return lab
    for _ in range(rounds):
        prev = lab
        m = np.minimum(lab[a], lab[b])
        lab = lab.copy()
        np.minimum.at(lab, a, m)
        np.minimum.at(lab, b, m)
        lab = lab[lab]
        if np.array_equal(lab, prev):
            break
    return lab


def wedges(geo, seam_pairs=()):
    """
    (nvertices,) wedge numbers + (nprims,) connected piece numbers.

    Two corners are in the same wedge <=> same geometric point + the edge between them is not a seam. So the two sides of a seam
    separate naturally, and **not a single point of the geometry has to move**.
    """
    nv = geo.nvertices
    t = topology(geo)
    if nv == 0 or t.nedges == 0:
        return np.arange(nv), np.arange(geo.nprims)
    seam = np.zeros(t.nedges, bool)
    if len(seam_pairs):
        seam = edge_mask(geo, seam_pairs)
    seam |= t.edge_count != 2                 # boundary and non-manifold edges are seams by nature

    ok = np.nonzero(~seam)[0]
    lab = np.arange(nv, dtype=np.int64)
    comp = np.arange(geo.nprims, dtype=np.int64)
    if not len(ok):
        return lab, comp
    h1 = t.edge_he[t.edge_he_off[ok]].astype(np.int64)
    h2 = t.edge_he[t.edge_he_off[ok] + 1].astype(np.int64)
    vp = geo.vertex_point
    nxt = geo.next_corner().astype(np.int64)
    # each interior edge pairs up two corners on each side: the two corners on the same geometric point merge
    a1, b1 = h1, np.where(vp[h1] == vp[h2], h2, nxt[h2])
    a2, b2 = nxt[h1], np.where(vp[nxt[h1]] == vp[h2], h2, nxt[h2])
    lab = _jump(lab, np.concatenate([a1, a2]), np.concatenate([b1, b2]))
    _, lab = np.unique(lab, return_inverse=True)

    vprim = geo.vertex_prim().astype(np.int64)
    comp = _jump(comp, vprim[h1], vprim[h2])
    _, comp = np.unique(comp, return_inverse=True)
    return lab.reshape(-1), comp.reshape(-1)


def _fan_tris(geo, wid):
    """Fan-triangulate each face, returning (T,3) **wedge numbers** and (T,) source face numbers."""
    sizes = geo.prim_sizes().astype(np.int64)
    starts = geo.prim_offset[:-1].astype(np.int64)
    keep = sizes >= 3
    if not keep.any():
        return np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    n_t = (sizes - 2)[keep]
    src = np.repeat(np.nonzero(keep)[0], n_t)
    k = (np.arange(int(n_t.sum()))
         - np.repeat(np.cumsum(n_t) - n_t, n_t))     # index of the fan triangle within the face
    s = starts[src]
    return np.stack([wid[s], wid[s + k + 1], wid[s + k + 2]], 1), src


def _local2d(P, tri):
    """Lay a triangle flat in its own local 2D frame. Returns (x2, x3, y3)."""
    p1, p2, p3 = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    e1 = p2 - p1
    e2 = p3 - p1
    x2 = np.linalg.norm(e1, axis=1)
    inv = 1.0 / np.maximum(x2, 1e-30)
    x3 = np.einsum("ij,ij->i", e2, e1) * inv
    y3 = np.linalg.norm(np.cross(e1, e2), axis=1) * inv
    return x2, x3, y3


def _build(P3, tri, loc=None):
    """
    Assemble the LSCM coefficients. Returns (rows, columns, values, row count, column count).

    Columns are laid out as [all u, all v], so the column of v_j is n + j.

    When loc gives (x2, x3, y3) the triangle shapes are not taken from 3D, it is used directly -- after ABF solves the angles,
    coordinates are rebuilt from "the virtual triangles defined by those angles", through this path.
    """
    x2, x3, y3 = _local2d(P3, tri) if loc is None else loc
    area = 0.5 * x2 * y3
    good = area > 1e-30
    tri, x2, x3, y3, area = tri[good], x2[good], x3[good], y3[good], area[good]
    if not len(tri):
        return (np.zeros(0, np.int64),) * 2 + (np.zeros(0),) + (0, 0)
    # normalize each triangle to √(2·area): without it the energy is proportional to area,
    # small triangles get twisted with no penalty, and all detail turns to mush
    s = 1.0 / np.sqrt(2.0 * area)
    Wx = np.stack([(x3 - x2), -x3, x2], 1) * s[:, None]
    Wy = np.stack([y3, -y3, np.zeros_like(y3)], 1) * s[:, None]

    n = int(tri.max()) + 1
    m = len(tri)
    ti = np.arange(m, dtype=np.int64)
    rows, cols, vals = [], [], []
    for j in range(3):
        # real part row: Wx·u - Wy·v = 0
        rows += [2 * ti, 2 * ti]
        cols += [tri[:, j], n + tri[:, j]]
        vals += [Wx[:, j], -Wy[:, j]]
        # imaginary part row: Wy·u + Wx·v = 0
        rows += [2 * ti + 1, 2 * ti + 1]
        cols += [tri[:, j], n + tri[:, j]]
        vals += [Wy[:, j], Wx[:, j]]
    return (np.concatenate(rows), np.concatenate(cols),
            np.concatenate(vals), 2 * m, 2 * n)


def _far_pair(P):
    """Two farthest-point passes: pick any point, find its farthest point, then the farthest point from there."""
    i = 0
    for _ in range(2):
        d = np.linalg.norm(P - P[i], axis=1)
        j = int(np.argmax(d))
        i, prev = j, i
    return prev, i


def _cg(rows, cols, vals, nrow, ncol, rhs, x0, iters, tol):
    """
    CGNR + Jacobi preconditioning. A = MᵀM is never assembled explicitly; each step needs only two bincounts.

    Returns (solution, steps used, final residual).
    """
    def mv(x):
        return np.bincount(rows, weights=vals * x[cols], minlength=nrow)

    def mtv(y):
        return np.bincount(cols, weights=vals * y[rows], minlength=ncol)

    diag = np.bincount(cols, weights=vals * vals, minlength=ncol)
    inv = 1.0 / np.where(diag > 1e-300, diag, 1.0)

    x = x0.copy()
    r = rhs - mtv(mv(x))
    z = inv * r
    p = z.copy()
    rz = float(r @ z)
    n0 = max(float(np.linalg.norm(rhs)), 1e-300)
    k = 0
    for k in range(1, int(iters) + 1):
        Ap = mtv(mv(p))
        pAp = float(p @ Ap)
        if pAp <= 1e-300:
            break
        a = rz / pAp
        x += a * p
        r -= a * Ap
        if float(np.linalg.norm(r)) / n0 < tol:
            break
        z = inv * r
        rz2 = float(r @ z)
        p = z + (rz2 / max(rz, 1e-300)) * p
        rz = rz2
    return x, k, float(np.linalg.norm(r)) / n0


def _plane_init(P3, pa, pb, d):
    """
    Use **the projection onto the best-fit plane** as the CG initial guess, then put the two pinned points in place.

    This is not just a speedup: for developable surfaces (plane, cone, cylinder) the projection is already near the exact solution, and CG
    converges almost immediately; planar input is done in one step. A zero initial guess takes more than ten times longer on the same mesh.
    """
    Q = P3 - P3.mean(0)
    # basis of the fitted plane = the two largest eigenvectors of the 3x3 covariance matrix.
    # **Do not** SVD the (n,3) directly: full_matrices=True allocates an n x n U,
    # 12 GB at 40k points. The covariance is 3x3, a single O(n) pass is enough
    try:
        w, V = np.linalg.eigh(Q.T @ Q)
    except np.linalg.LinAlgError:
        return np.zeros((len(P3), 2))
    xy = Q @ V[:, ::-1][:, :2]
    a, b = xy[pa], xy[pb]
    e = b - a
    L = float(np.linalg.norm(e))
    if L < 1e-12:
        return xy
    # rotate the line a->b to the +u direction and scale its length to d, matching the pinned values
    c, sn = e[0] / L, e[1] / L
    k = d / L
    r = xy - a
    return np.stack([(r[:, 0] * c + r[:, 1] * sn) * k,
                     (-r[:, 0] * sn + r[:, 1] * c) * k], 1)


def _plane_init_pins(P3, pidx, pval):
    """
    CG initial guess with >= 2 pinned points: the projection onto the fitted plane, placed onto the pins with a least-squares **similarity transform** (complex
    a·z + b). It is only an initial guess; the solution does not depend on it.
    """
    Q = P3 - P3.mean(0)
    try:
        _, V = np.linalg.eigh(Q.T @ Q)
    except np.linalg.LinAlgError:
        return np.zeros((len(P3), 2))
    xy = Q @ V[:, ::-1][:, :2]
    z = xy[:, 0] + 1j * xy[:, 1]
    zp = z[pidx]
    wp = pval[:, 0] + 1j * pval[:, 1]
    zc, wc = zp.mean(), wp.mean()
    den = float(np.sum(np.abs(zp - zc) ** 2))
    a = np.sum(np.conj(zp - zc) * (wp - wc)) / den if den > 1e-24 else 1.0
    w = a * (z - zc) + wc
    return np.stack([w.real, w.imag], 1)


def _pcg(matvec, diag, b, x0, iters, tol):
    """Jacobi-preconditioned conjugate gradient for symmetric positive semi-definite systems. Returns (solution, steps)."""
    inv = 1.0 / np.where(diag > 1e-300, diag, 1.0)
    x = x0.copy()
    r = b - matvec(x)
    z = inv * r
    p = z.copy()
    rz = float(r @ z)
    nb = max(float(np.linalg.norm(b)), 1e-300)
    k = 0
    for k in range(1, int(iters) + 1):
        if float(np.linalg.norm(r)) / nb < tol:
            break
        Ap = matvec(p)
        pAp = float(p @ Ap)
        if pAp <= 1e-300:
            break
        a = rz / pAp
        x += a * p
        r -= a * Ap
        z = inv * r
        rz2 = float(r @ z)
        p = z + (rz2 / max(rz, 1e-300)) * p
        rz = rz2
    return x, k


def _tri_edges(tri):
    """(T,3) triangles -> undirected edges (E,2), how many triangles use each edge, and the edge numbers of each triangle's three edges (T,3)."""
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    key = np.sort(e, 1)
    uq, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return uq, cnt, inv.reshape(-1).reshape(3, -1).T


def _boundary_wedges(n, tri):
    """(n,) bool: wedges on an island boundary (endpoints of an edge used by only one triangle)."""
    uq, cnt, _ = _tri_edges(tri)
    out = np.zeros(n, bool)
    out[uq[cnt == 1].reshape(-1)] = True
    return out


def _solve_scp(P3, tri, iters, tol, outer=100):
    """
    Spectral Conformal Parameterization (Mullen, Tong, Alliez, Desbrun 2008).

    LSCM's root problem is "pin two points": which two and how far apart directly decides the result, and bad pins drag the boundary askew.
    SCP pins nothing: subject to "orthogonal to the constant", minimize the conformal energy E_C(x) = xᵀAx relative to the **boundary mass**
    xᵀBx -- the smallest non-trivial eigenvector of the generalized eigenproblem A x = λ B x. A is LSCM's
    MᵀM (the normal equations are never assembled, still two bincounts), B is diagonal: the mass of a boundary wedge is half the length of its two adjacent
    boundary edges (Mullen's paper uses a mass matrix on the boundary; the docs do not say how Houdini does it,
    here it is length weighted, so mesh density does not affect the result).

    The solver is **shifted inverse iteration**: y = (A + σB)⁻¹ B x, projecting out the constant component each step and normalizing in the B norm.
    σ is a very small positive shift: besides constants, A's null space also contains "global similarity transforms" (the isometric flattening of a developable surface
    has zero energy by itself), so σ makes A + σB positive definite and solvable by CG; the constant component is projected out exactly each step and cannot grow.
    The smallest eigenvalue is double (x and "x rotated by 90°" have the same energy); what it converges to is some vector in that 2D eigen-subspace
    -- differing only by a similarity transform, and flatten() rescales and translates by world area afterwards anyway.

    Difference from Houdini: Houdini says SCP is the faster option; here each inverse iteration step is a full CG,
    several times slower than two-pin LSCM (in exchange for a boundary that does not depend on pin choice).
    """
    rows, cols, vals, nrow, ncol = _build(P3, tri)
    n = ncol // 2
    if n < 3 or nrow == 0:
        return np.zeros((max(n, 0), 2)), 0, 0.0
    uq, cnt, _ = _tri_edges(tri)
    be = uq[cnt == 1]
    if not len(be):
        return _solve_island(P3, tri, iters, tol)
    L = np.linalg.norm(P3[be[:, 0]] - P3[be[:, 1]], axis=1)
    m = (np.bincount(be[:, 0], weights=0.5 * L, minlength=n)
         + np.bincount(be[:, 1], weights=0.5 * L, minlength=n))
    Bd = np.concatenate([m, m])

    def A(x):
        return np.bincount(cols, weights=vals * np.bincount(
            rows, weights=vals * x[cols], minlength=nrow)[rows], minlength=ncol)

    dA = np.bincount(cols, weights=vals * vals, minlength=ncol)
    # shift = 1e-6 of the ratio of A's and B's diagonals: enough to make the system positive definite, yet far below meaningful eigenvalue gaps
    sigma = 1e-6 * float(dA.sum()) / max(float(Bd.sum()), 1e-300)
    e1 = np.concatenate([np.ones(n), np.zeros(n)])
    e2 = np.concatenate([np.zeros(n), np.ones(n)])

    def proj(x):
        for e in (e1, e2):
            x = x - (float(e @ (Bd * x)) / float(e @ (Bd * e))) * e
        nb = float(np.sqrt(max(x @ (Bd * x), 0.0)))
        return x / nb if nb > 1e-300 else x

    used = np.unique(tri)
    a, b = _far_pair(P3[used])
    g0 = _plane_init(P3, int(used[a]), int(used[b]), 1.0)
    x = proj(np.concatenate([g0[:, 0], g0[:, 1]]))
    rq_prev = np.inf
    k_tot = 0
    for it in range(int(outer)):
        y, k = _pcg(lambda z: A(z) + sigma * Bd * z, dA + sigma * Bd, Bd * x,
                    x, iters, tol)
        k_tot += k
        x = proj(y)
        rq = float(x @ A(x))
        if abs(rq_prev - rq) <= 1e-10 * max(abs(rq), 1e-12) and it >= 2:
            break
        rq_prev = rq
    return np.stack([x[:n], x[n:]], 1), k_tot, float(rq_prev)


def _corner_angles(P3, tri):
    """(T,3) interior angles (radians) of each triangle's three corners, corner k at point tri[:, k]."""
    out = np.zeros(tri.shape)
    for k in range(3):
        a = P3[tri[:, k]]
        u = P3[tri[:, (k + 1) % 3]] - a
        v = P3[tri[:, (k + 2) % 3]] - a
        out[:, k] = np.arctan2(np.linalg.norm(np.cross(u, v), axis=1),
                               (u * v).sum(1))
    return out


def _abf_shape(P3, tri, iters, tol, sqp=30):
    """
    Angle Based Flattening: first solve for **angles**, then rebuild coordinates from the angles.

    ABF (Sheffer & de Sturler 2001) has as unknowns the three interior angles α of each triangle, aiming to stay as close as possible to the 3D
    "ideal angles" β: min Σ (α − β)² / β², subject to the three things a planar triangulation must satisfy:
      · the interior angles of each triangle sum to π
      · the angles around each interior point sum to 2π (flat)
      · the "sine wheel" around each interior point: Π sin(next angle) = Π sin(previous angle) (edge lengths close up going around)
    β is the 3D angle, scaled proportionally around interior points to sum to 2π (as in the original ABF paper).

    The third is nonlinear. SQP is used here: linearize the constraints at the current α (the derivative of log sin is cot, i.e.
    the linearized ABF of Zayer et al. 2007), minimize the same quadratic objective, closed-form solution
        d = g − W⁻¹Jᵀλ,  (J W⁻¹ Jᵀ) λ = C + J g,  g = β − α
    J W⁻¹ Jᵀ is symmetric positive definite and solved with Jacobi-PCG (still unassembled, two bincounts). Re-linearize repeatedly
    until the constraint residual < 1e-10 -- what it converges to is the ABF solution (not the single-step LinABF).

    Returns the virtual triangles (x2, x3, y3) defined by the angles, for _build to rebuild (the same least squares as LSCM;
    when the angles satisfy all constraints the virtual triangles fit seamlessly and the rebuild is exact). The triangle size is taken from the 0->1 edge in 3D.

    Difference from Houdini: Houdini's ABF is its own implementation (the docs only say "slower, may fail to solve");
    here, if SQP does not converge, the angles of the last step are returned anyway -- the rebuild step is least squares and does not fail because the angles
    are slightly off.
    """
    T = len(tri)
    n = int(tri.max()) + 1
    th = np.clip(_corner_angles(P3, tri), 1e-4, np.pi - 1e-4)
    bnd = _boundary_wedges(n, tri)
    cw = tri.reshape(-1)                                   # corner -> wedge
    inner = ~bnd[cw]
    tot = np.bincount(cw, weights=th.reshape(-1), minlength=n)
    beta = th.reshape(-1).copy()
    beta[inner] *= 2 * np.pi / np.maximum(tot[cw[inner]], 1e-12)
    Winv = beta * beta                                     # W = 1/β²
    iid = np.full(n, -1, np.int64)
    Vi = int((~bnd).sum())
    iid[~bnd] = np.arange(Vi)

    ci = np.arange(3 * T, dtype=np.int64)
    t_of = ci // 3
    k_of = ci % 3
    nxt = 3 * t_of + (k_of + 1) % 3                        # the next corner in the same triangle
    prv = 3 * t_of + (k_of + 2) % 3
    ic = ci[inner]
    row_plan = T + iid[cw[ic]]
    row_len = T + Vi + iid[cw[ic]]
    nrow = T + 2 * Vi
    a = beta.copy()
    for _ in range(int(sqp)):
        sa = np.sin(a)
        ls = np.log(np.maximum(sa, 1e-300))
        C = np.concatenate([
            a.reshape(T, 3).sum(1) - np.pi,
            np.bincount(iid[cw[ic]], weights=a[ic], minlength=Vi) - 2 * np.pi,
            np.bincount(iid[cw[ic]], weights=ls[nxt[ic]] - ls[prv[ic]], minlength=Vi)])
        if float(np.abs(C).max(initial=0.0)) < 1e-10:
            break
        cot = np.cos(a) / np.maximum(sa, 1e-300)
        rows = np.concatenate([t_of, row_plan, row_len, row_len])
        cols = np.concatenate([ci, ic, nxt[ic], prv[ic]])
        vals = np.concatenate([np.ones(3 * T), np.ones(len(ic)),
                               cot[nxt[ic]], -cot[prv[ic]]])

        def J(x):
            return np.bincount(rows, weights=vals * x[cols], minlength=nrow)

        def Jt(y):
            return np.bincount(cols, weights=vals * y[rows], minlength=3 * T)

        g = beta - a
        rhs = C + J(g)
        dS = np.bincount(rows, weights=vals * vals * Winv[cols], minlength=nrow)
        lam, _ = _pcg(lambda y: J(Winv * Jt(y)), dS, rhs, np.zeros(nrow),
                      max(int(iters), 1), min(float(tol), 1e-12))
        a = np.clip(a + g - Winv * Jt(lam), 1e-6, np.pi - 1e-6)
    a = a.reshape(T, 3)
    l01 = np.linalg.norm(P3[tri[:, 1]] - P3[tri[:, 0]], axis=1)
    sc = l01 / np.maximum(np.sin(a[:, 2]), 1e-12)
    return (l01, sc * np.sin(a[:, 1]) * np.cos(a[:, 0]),
            sc * np.sin(a[:, 1]) * np.sin(a[:, 0]))


def _solve_island(P3, tri, iters, tol, pins=None, loc=None):
    """
    A surface with a boundary -> (n,2) uv.

    pins = (index array, (k,2) target uv); when k >= 2 they are used instead of "the farthest pair" for pinning -- this is
    Houdini's Vertex Pins: pinned wedges land on the given uv, the rest follow by conformal energy.
    For loc see _build (used by the ABF rebuild).
    """
    rows, cols, vals, nrow, ncol = _build(P3, tri, loc)
    n = ncol // 2
    if n < 3 or nrow == 0:
        return np.zeros((max(n, 0), 2)), 0, 0.0
    if pins is not None and len(pins[0]) >= 2:
        pidx = np.asarray(pins[0], np.int64)
        pval = np.asarray(pins[1], np.float64).reshape(-1, 2)
        pin = np.concatenate([pidx, n + pidx])
        pin_val = np.concatenate([pval[:, 0], pval[:, 1]])
        pa, pb = int(pidx[0]), int(pidx[1])
        d = None
    else:
        # pin the farthest pair: picking two nearby points means fixing the scale and orientation of the whole patch with a very short segment,
        # which numerically amplifies errors by several orders of magnitude
        used = np.unique(tri)
        a, b = _far_pair(P3[used])
        pa, pb = int(used[a]), int(used[b])
        d = float(np.linalg.norm(P3[pb] - P3[pa]))
        d = d if d > 1e-12 else 1.0
        pin = np.array([pa, pb, n + pa, n + pb])
        pin_val = np.array([0.0, d, 0.0, 0.0])

    free = np.ones(ncol, bool)
    free[pin] = False
    newcol = np.full(ncol, -1, np.int64)
    newcol[free] = np.arange(int(free.sum()))

    ispin = ~free[cols]
    xp = np.zeros(ncol)
    xp[pin] = pin_val
    rhs_vec = np.bincount(rows[ispin], weights=vals[ispin] * xp[cols[ispin]],
                          minlength=nrow)
    fr, fc, fv = rows[~ispin], newcol[cols[~ispin]], vals[~ispin]
    nfree = int(free.sum())
    b_ = -np.bincount(fc, weights=fv * rhs_vec[fr], minlength=nfree)

    if d is None:
        # >= 2 points pinned: the initial guess places the fitted-plane projection with the least-squares similarity transform between the pins
        guess = _plane_init_pins(P3, pidx, pval)
    else:
        guess = _plane_init(P3, pa, pb, d)
    full0 = np.concatenate([guess[:, 0], guess[:, 1]])
    full0[pin] = pin_val
    sol, k, res = _cg(fr, fc, fv, nrow, nfree, b_, full0[free], iters, tol)
    full = xp.copy()
    full[free] = sol
    return np.stack([full[:n], full[n:]], 1), k, res


METHODS = ("lscm", "scp", "abf")


def flatten(geo, seam_group="", name="uv", cls=VERTEX, iterations=2000,
            tolerance=1e-8, normalize=True, pack=False, padding=0.01,
            distortion_attrib="", group="", arap_iterations=0, method="lscm",
            flatten_group="", preserve_seams=False, pin_group="",
            output_seams="", output_constrained=""):
    """
    Conformal flattening. Seams are given by an edge group; without seams the geometry's own boundary is used.

    Each connected piece is solved on its own. **Closed pieces (without any boundary/seam) cannot be flattened** -- that is Gauss's
    Theorema Egregium, not an implementation problem; here it errors and explains how to cut, rather than producing a heap of overlapping uvs.

    Added in pcg100 (against Houdini UV Flatten 3.0):
      method          lscm (the original, pins the two farthest points) / scp (spectral conformal, no pins) / abf (angle-based flattening)
      flatten_group   flatten only these faces; other faces keep their uvs. Edges between selection and non-selection automatically become seams
      preserve_seams  edges that are split in the existing uvs also become seams (Houdini's Preserve Seams)
      pin_group       corners on these points are pinned at their **existing** uv (Houdini's Vertex Pins also pin in place by default;
                      no per-pin coordinate multiparm here, to move them use UV Transform first)
      output_seams / output_constrained   Houdini's Output Groups: Seams / Constrained Islands
    """
    if geo is None:
        return Geometry()
    if cls != VERTEX:
        raise ValueError(
            "UV Flatten only writes vertex attributes: the same point on both sides of a seam needs two uvs, "
            "which a point attribute cannot store.")
    if method not in METHODS:
        raise ValueError(f"Flattening Method must be one of {METHODS}")
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    P = geo.get(POINT, "P")
    if P is None:
        raise KeyError("The geometry has no P attribute.")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("Attribute Name is empty.")

    pairs = (resolve_edges(geo, seam_group) if str(seam_group).strip()
             else np.zeros((0, 2), np.int32))
    user_pairs = pairs
    t = topology(geo)
    sel = resolve(geo, PRIM, flatten_group)
    vprim = geo.vertex_prim().astype(np.int64)
    extra = np.zeros(t.nedges, bool)
    preserved = np.zeros(t.nedges, bool)
    if preserve_seams and geo.get(VERTEX, nm) is not None:
        from .uvlayout import uv_seam_edges
        preserved = uv_seam_edges(geo, nm)
        extra |= preserved
    if not sel.all() and t.nedges:
        # selection boundary: edges selected on one side and not the other become seams; the selected faces form their own piece, unconnected to unselected ones
        two = np.nonzero(t.edge_count == 2)[0]
        s1 = sel[vprim[t.edge_he[t.edge_he_off[two]]]]
        s2 = sel[vprim[t.edge_he[t.edge_he_off[two] + 1]]]
        extra[two[s1 != s2]] = True
    if extra.any():
        pairs = np.concatenate([np.asarray(pairs, np.int32).reshape(-1, 2),
                                t.edge_points[extra].astype(np.int32)])
    wid, comp = wedges(geo, pairs)
    tri, tsrc = _fan_tris(geo, wid)
    if not sel.all():
        keep_t = sel[tsrc]
        tri, tsrc = tri[keep_t], tsrc[keep_t]
    if not len(tri):
        return geo.copy()

    # a wedge's 3D position = the position of the geometric point it is on
    nw = int(wid.max()) + 1
    wpt = np.zeros(nw, np.int64)
    wpt[wid] = geo.vertex_point
    P3 = P.astype(np.float64)[wpt]

    seam = edge_mask(geo, pairs) if len(pairs) else np.zeros(t.nedges, bool)
    seam |= t.edge_count != 2
    open_comp = np.zeros(comp.max() + 1, bool)
    if seam.any():
        he = t.edge_he[np.repeat(seam, t.edge_count)]
        open_comp[comp[geo.vertex_prim()[he]]] = True
    closed = np.nonzero(~open_comp)[0]
    if not sel.all():
        closed = closed[np.isin(closed, comp[sel])]
    if len(closed):
        nfaces = int(np.count_nonzero(np.isin(comp, closed)))
        raise ValueError(
            f"{len(closed)} connected pieces are closed ({nfaces} faces in total) and cannot be flattened -- "
            f"a sphere has no isometric planar unwrap; this is Gauss's Theorema Egregium, not an implementation problem.\n"
            f"  Give it a seam first: select a loop of edges with Group Edges (PCG) and put the group name in Seam Group.")

    # ── Vertex Pins: pinned corners land on the existing uv. If any corner in a wedge is pinned, the whole wedge is pinned
    wpin = np.zeros(nw, bool)
    wpin_val = np.zeros((nw, 2))
    if str(pin_group).strip():
        old = geo.get(VERTEX, nm)
        if old is None and geo.get(POINT, nm) is not None:
            old = geo.get(POINT, nm)[geo.vertex_point]
        if old is None or old.shape[1] < 2:
            raise KeyError(f"Vertex Pins pin to the existing uv, but the geometry has no '{nm}'. "
                           f"Connect a UV Project first to give an initial value.")
        # no need to intersect with Group again: the selection boundary is a seam, corners on unselected faces form their own wedges and join no island
        pmask = resolve(geo, POINT, pin_group)[geo.vertex_point]
        pc = np.nonzero(pmask)[0]
        wpin[wid[pc]] = True
        wpin_val[wid[pc]] = np.asarray(old, np.float64)[pc, :2]

    uv_w = np.zeros((nw, 2))
    fixed = np.zeros(nw, bool)          # islands with pins: excluded from Normalize's global scaling
    stats = []
    tri_comp = comp[tsrc]
    spans = []
    for c in np.unique(tri_comp):
        sub = tri[tri_comp == c]
        used = np.unique(sub)
        remap = np.full(nw, -1, np.int64)
        remap[used] = np.arange(len(used))
        pw = used[wpin[used]]
        shape = (_abf_shape(P3[used], remap[sub], iterations, tolerance)
                 if method == "abf" else None)
        if len(pw) >= 2:
            # two or more pins: the pins themselves fix position, orientation and scale, so solve the pinned conformal least squares directly
            # (SCP is designed for "no pins"; the Houdini docs do not say how SCP solves with pins,
            # so here it solves with pins just like LSCM)
            loc, k, res = _solve_island(P3[used], remap[sub], iterations, tolerance,
                                        pins=(remap[pw], wpin_val[pw]), loc=shape)
        elif method == "scp":
            loc, k, res = _solve_scp(P3[used], remap[sub], iterations, tolerance)
        else:
            loc, k, res = _solve_island(P3[used], remap[sub], iterations,
                                        tolerance, loc=shape)
        if arap_iterations > 0 and len(loc) >= 3 and len(pw) < 2:
            loc = _arap(P3[used], remap[sub], loc, arap_iterations)
        if len(loc) and len(pw) < 2:
            # The LSCM solution is only determined up to a similarity transform, the scale is arbitrary. First scale each island so UV area =
            # 3D area (world scale), so texel density is consistent across islands. Previously each island was normalized to 0..1 on its own,
            # so a small triangle island took up as much of the image as a whole large island -- after packing densities differed by tens of times
            a3 = _tri_area3(P3[sub[:, 0]], P3[sub[:, 1]], P3[sub[:, 2]])
            l2 = loc[remap[sub]]
            a2 = 0.5 * np.abs(((l2[:, 1] - l2[:, 0])[:, 0] * (l2[:, 2] - l2[:, 0])[:, 1]
                               - (l2[:, 1] - l2[:, 0])[:, 1] * (l2[:, 2] - l2[:, 0])[:, 0]
                               ).sum())
            if a2 > 1e-30:
                loc = loc * np.sqrt(a3 / a2)
            if len(pw) == 1:
                # only one pin: orientation and scale cannot be fixed (Houdini uses Reference UV for that, not implemented here),
                # so after flattening at world scale the whole island is translated to the pin position
                loc = loc - loc[remap[pw[0]]] + wpin_val[pw[0]]
            else:
                loc = loc - loc.min(0)
                spans.append(float((loc.max(0)).max()))
        if len(pw):
            fixed[used] = True
        uv_w[used] = loc
        stats.append((int(c), k, res))
    if normalize and spans:
        # all islands **share one** scale: the largest island fills 0..1, the others follow at world scale
        # (with only one island this is the same as the old per-island normalization). Islands with pins do not move
        if fixed.any():
            uv_w[~fixed] = uv_w[~fixed] / max(max(spans), 1e-12)
        else:
            uv_w = uv_w / max(max(spans), 1e-12)

    uv = uv_w[wid]
    g = geo.copy()
    cur = geo.get(cls, nm)
    if not sel.all():
        # unselected faces: uv kept as is (0 if the attribute did not exist before)
        keep_v = ~sel[vprim]
        if cur is not None and cur.shape[1] >= 2:
            uv[keep_v] = np.asarray(cur, np.float64)[keep_v, :2]
        elif geo.get(POINT, nm) is not None and geo.get(POINT, nm).shape[1] >= 2:
            uv[keep_v] = np.asarray(geo.get(POINT, nm), np.float64)[geo.vertex_point[keep_v], :2]
        else:
            uv[keep_v] = 0.0
    if cur is not None and cur.shape[1] > 2:
        col = np.array(cur, np.float64)
        col[:, :2] = uv
        g.set(cls, nm, col.astype(cur.dtype), owned=True)
    else:
        g.set(cls, nm, uv.astype(np.float32), owned=True)

    if str(distortion_attrib).strip():
        g.set(PRIM, str(distortion_attrib).strip(),
              _distortion(geo, uv)[:, None].astype(np.float32), owned=True)
    if str(output_seams).strip():
        # output seams = user-given + those found by Preserve Seams, only interior edges (one face on each side),
        # with at least one side in Group; the geometry's own boundary is not a "cut" seam and does not count
        sm = (edge_mask(geo, user_pairs) if len(user_pairs) else np.zeros(t.nedges, bool))
        sm |= preserved
        sm &= t.edge_count == 2
        if not sel.all():
            touch = np.zeros(t.nedges, bool)
            np.logical_or.at(touch, np.repeat(np.arange(t.nedges), t.edge_count),
                             sel[vprim[t.edge_he]])
            sm &= touch
        g.set_edge_group(str(output_seams).strip(), t.edge_points[sm])
    if str(output_constrained).strip():
        pc_comp = np.unique(comp[vprim[np.nonzero(fixed[wid])[0]]])
        g.set_group(PRIM, str(output_constrained).strip(),
                    np.isin(comp, pc_comp) & sel)
    if pack:
        from .uvlayout import layout
        g = layout(g, nm, cls, "uniform", padding, True, group)
    return g


def _arap(P3, tri, uv, iters=10, cg_iters=400):
    """
    ARAP flattening (Liu et al. 2008's local / global alternation), starting from the LSCM solution.

    LSCM preserves angles but not area: a large island (rocks, terrain and other surfaces with few seams) cut open and laid flat
    gets compressed far from the seams and stretched near them; measured texel density within one island varying by more than 10x.
    ARAP wants each triangle's map from 3D to UV to be **just a rotation** as far as possible (no scaling, no shear):
      local   per triangle, take the rotation closest between the current UV and its 3D shape (2x2 SVD)
      global  with those rotations fixed, solve a cotangent-Laplacian Poisson equation for new UVs
    The two steps alternate and the energy decreases monotonically. Cotangent weights are not clamped: negative cotangents of obtuse angles and large cotangents of thin triangles are both correct;
    clamping them keeps even planar meshes from being restored to isometry (see the comment below); triangles with area ≈ 0 are excluded outright.
    """
    n = len(P3)
    if n < 3 or not len(tri):
        return uv
    a, b, c = P3[tri[:, 0]], P3[tri[:, 1]], P3[tri[:, 2]]
    e1, e2 = b - a, c - a
    l1 = np.linalg.norm(e1, axis=1)
    nrm = np.cross(e1, e2)
    # Degenerate (area ≈ 0) triangles are excluded: cotangent -> ∞, and a single face can drag the whole island askew. After reducing / welding
    # faces with three collinear points are occasionally left behind
    lmax = np.maximum(l1, np.linalg.norm(e2, axis=1))
    ok = (l1 > 1e-15) & (np.linalg.norm(nrm, axis=1) > 1e-10 * lmax * lmax)
    ex = e1 / np.where(ok, l1, 1.0)[:, None]
    ey = np.cross(nrm, e1)
    ey /= np.maximum(np.linalg.norm(ey, axis=1, keepdims=True), 1e-30)
    X = np.zeros((len(tri), 3, 2))                         # isometric 2D unfolding of each triangle
    X[:, 1, 0] = l1
    X[:, 2, 0] = (e2 * ex).sum(1)
    X[:, 2, 1] = (e2 * ey).sum(1)
    # cotangent: the angle at vertex k opposite edge (i, j)
    cot = np.zeros((len(tri), 3))
    for k in range(3):
        i, j = (k + 1) % 3, (k + 2) % 3
        u_ = X[:, i] - X[:, k]
        v_ = X[:, j] - X[:, k]
        cr = u_[:, 0] * v_[:, 1] - u_[:, 1] * v_[:, 0]
        cot[:, k] = (u_ * v_).sum(1) / np.where(np.abs(cr) < 1e-30, 1e-30, np.abs(cr))
    EI = np.stack([tri[:, 1], tri[:, 2], tri[:, 0]], 1)     # the two ends (i, j) of edge k
    EJ = np.stack([tri[:, 2], tri[:, 0], tri[:, 1]], 1)
    # Cotangent weights are **not clamped**: the cotangent on the obtuse side is negative anyway, yet the Dirichlet energy of a PL function
    # Σ w_ij |u_i − u_j|² is positive semi-definite for any triangulation without flipped faces (negative weights only break the maximum principle,
    # not definiteness), CG still converges, and on planar meshes ARAP restores isometry exactly (linear precision). It used to clamp to
    # [1e-3, 1e3], which lifted obtuse angles to positive and shrank thin triangles, so even planar meshes were not restored
    w = np.where(ok[:, None], cot, 0.0)
    DX = np.stack([X[:, 1] - X[:, 2], X[:, 2] - X[:, 0], X[:, 0] - X[:, 1]], 1)
    ei, ej, wv = EI.reshape(-1), EJ.reshape(-1), w.reshape(-1)
    diag = np.bincount(ei, weights=wv, minlength=n) + np.bincount(ej, weights=wv, minlength=n)
    pin = 0
    free = np.ones(n, bool)
    free[pin] = False

    def Lmul(x):
        y = diag * x
        y -= np.bincount(ei, weights=wv * x[ej], minlength=n)
        y -= np.bincount(ej, weights=wv * x[ei], minlength=n)
        y[pin] = x[pin]
        return y

    u = uv.astype(np.float64).copy()
    for _ in range(int(iters)):
        S = np.einsum("tk,tka,tkb->tab", w, u[EI] - u[EJ], DX)
        U_, _, Vt = np.linalg.svd(S)
        R = U_ @ Vt
        neg = np.linalg.det(R) < 0
        if neg.any():
            U_[neg, :, 1] *= -1
            R[neg] = U_[neg] @ Vt[neg]
        RX = np.einsum("tab,tkb->tka", R, DX) * w[:, :, None]   # w R (x_i − x_j)
        rhs = np.zeros((n, 2))
        np.add.at(rhs, ei, RX.reshape(-1, 2))
        np.add.at(rhs, ej, -RX.reshape(-1, 2))
        for d in range(2):
            b_ = rhs[:, d].copy()
            b_[pin] = u[pin, d]
            x = u[:, d].copy()
            r = b_ - Lmul(x)
            z = r / np.where(diag > 0, diag, 1.0)
            z[pin] = 0.0
            r[pin] = 0.0
            p = z.copy()
            rz = float(r @ z)
            nb = max(float(np.linalg.norm(b_)), 1e-300)
            for _ in range(int(cg_iters)):
                Ap = Lmul(p)
                pAp = float(p @ Ap)
                if pAp <= 1e-300:
                    break
                al = rz / pAp
                x += al * p
                r -= al * Ap
                if float(np.linalg.norm(r)) / nb < 1e-9:
                    break
                z = r / np.where(diag > 0, diag, 1.0)
                z[pin] = 0.0
                rz2 = float(r @ z)
                p = z + (rz2 / max(rz, 1e-300)) * p
                rz = rz2
            u[:, d] = x
    return u


def _tri_area3(a, b, c):
    return 0.5 * float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def _distortion(geo, uv):
    """
    **Area distortion** per face: UV area / 3D area, divided by the global median.

    1 = texel density consistent with most places, >1 = stretched in UV (gets more pixels),
    <1 = compressed. Conformal maps preserve angles but not area, so this value is not 1 everywhere to begin with --
    it is for finding "which part is stretched absurdly", not for judging right or wrong.
    """
    from .measure import prim_areas
    sizes = geo.prim_sizes()
    src = np.repeat(np.arange(geo.nprims), sizes)
    nxt = geo.next_corner().astype(np.int64)
    cross = uv[:, 0] * uv[nxt, 1] - uv[nxt, 0] * uv[:, 1]
    a_uv = 0.5 * np.abs(np.bincount(src, weights=cross,
                                    minlength=geo.nprims))
    a_3d = np.asarray(prim_areas(geo), np.float64)
    r = a_uv / np.maximum(a_3d, 1e-30)
    med = float(np.median(r[a_3d > 1e-30])) if (a_3d > 1e-30).any() else 1.0
    return r / max(med, 1e-30)
