"""
Tangent Field (pcg76): the smoothest n-fold symmetric direction field on a surface (the method of Knöppel et al. 2013).

━━ Representation
Each point has its own tangent-plane frame (e1, e2) (e1 = the first adjacent edge projected onto the tangent plane). A direction at a point is the complex number
z = e^{i·n·α}, with α the direction's angle in its own frame -- taking the n-th power turns the n mutually equivalent directions of an n-fold symmetry (n = 1 arrow,
2 line, 4 cross, 6 snowflake) into the same number, so there is no need to "pick one".
Carrying a vector along edge i->j from i's frame to j's frame rotates it by an angle r_ij (discrete Levi-Civita transport:
the edge's angle is θ_ij in i's frame and θ_ji + π in j's frame, so r_ij = θ_ji + π − θ_ij).

━━ Smoothest
Energy E = Σ_edges |z_j − e^{i·n·r_ij} z_i|² -- zero when the field transported along an edge equals its neighbour.
  With guidance (guide attribute / curvature alignment): solve (L + λD) z = λD c, c the guide direction, λ the Guide
  Weight, D non-zero only at guided points. Complex Hermitian positive definite, conjugate gradient
  Without guidance: the smoothest field is the eigenvector of L's smallest eigenvalue, inverse power iteration
Outputs a unit tangent vector per point (for n > 1, one of the n equivalent directions).
Note "smoothest" is in the relaxed sense with |z| unconstrained (Knöppel's approach): |z| may shrink in places,
and pairs of cancelling singularities can pop up there -- e.g. 4 on a thick torus with n = 2. To suppress them add
guidance or curvature alignment.

━━ Curvature alignment
At each point fit the shape operator from the one-ring: the normal curvature along an adjacent edge κ = 2 N·(p_j − p_i)/|p_j − p_i|²,
least-squares fit κ(φ) = a cos²φ + 2b cosφ sinφ + c sin²φ over angle; the eigenvectors are the principal directions.
max_curvature aligns to the direction of larger |κ| (around a cylinder), min_curvature to the smaller one
(along the cylinder axis); the weight is multiplied by the relative anisotropy |k1 − k2| / (|k1| + |k2|) -- isotropic places like spheres and planes
get no direction forced on them.
Principal directions are "lines" (sign does not matter), so curvature alignment needs Symmetry ≥ 2.

━━ Singularities
A direction field on a closed surface necessarily has singularities (hairy ball theorem); the sum of singularity indices = n·χ (Poincaré–Hopf; in units of 1/n
turn). The report gives the singularity count and index sum: on a sphere 2 for n = 1, 8 for n = 4.
"""
from __future__ import annotations

import math

import numpy as np

from .core import POINT
from .topology import topology

SYMMETRIES = (1, 2, 4, 6)
ALIGN_MODES = ("none", "max_curvature", "min_curvature")


def _frames(P, N, t):
    n = len(P)
    ep = t.edge_points.astype(np.int64)
    first = np.full(n, -1, np.int64)
    has = np.diff(t.pt_edge_off) > 0
    first[has] = t.pt_edge[t.pt_edge_off[:-1][has]]
    other = np.where(ep[np.maximum(first, 0), 0] == np.arange(n),
                     ep[np.maximum(first, 0), 1], ep[np.maximum(first, 0), 0])
    d = P[other] - P
    e1 = d - np.einsum("ij,ij->i", d, N)[:, None] * N
    ln = np.linalg.norm(e1, axis=1)
    bad = ln < 1e-12
    if bad.any():
        a = np.where(np.abs(N[bad, 0:1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
        e1[bad] = np.cross(N[bad], a)
        ln[bad] = np.linalg.norm(e1[bad], axis=1)
    e1 = e1 / ln[:, None]
    e2 = np.cross(N, e1)
    return e1, e2


def _angle_in(v, e1, e2):
    return np.arctan2(np.einsum("ij,ij->i", v, e2), np.einsum("ij,ij->i", v, e1))


def _wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def _cg(apply, b, x0, tol=1e-10, maxit=5000):
    x = x0.copy()
    r = b - apply(x)
    p = r.copy()
    rr = np.vdot(r, r).real
    bn = max(np.linalg.norm(b), 1e-300)
    for _ in range(maxit):
        if math.sqrt(rr) <= tol * bn:
            break
        Ap = apply(p)
        a = rr / np.vdot(p, Ap).real
        x = x + a * p
        r = r - a * Ap
        rr2 = np.vdot(r, r).real
        p = r + (rr2 / rr) * p
        rr = rr2
    return x


def _curvature_dirs(P, N, e1, e2, ep, n):
    """Per-point principal direction angle (in its own frame), anisotropy, and the two principal curvatures."""
    i = np.concatenate([ep[:, 0], ep[:, 1]])
    j = np.concatenate([ep[:, 1], ep[:, 0]])
    d = P[j] - P[i]
    L2 = np.einsum("ij,ij->i", d, d)
    kap = 2 * np.einsum("ij,ij->i", N[i], d) / np.maximum(L2, 1e-300)
    phi = _angle_in(d, e1[i], e2[i])
    c, s = np.cos(phi), np.sin(phi)
    Aij = np.stack([c * c, 2 * c * s, s * s], 1)
    M = np.zeros((n, 3, 3))
    rhs = np.zeros((n, 3))
    np.add.at(M, i, Aij[:, :, None] * Aij[:, None, :])
    np.add.at(rhs, i, Aij * kap[:, None])
    M += 1e-12 * np.eye(3)
    abc = np.linalg.solve(M, rhs[..., None])[..., 0]
    a, b, cc = abc[:, 0], abc[:, 1], abc[:, 2]
    mean = 0.5 * (a + cc)
    rad = np.sqrt((0.5 * (a - cc)) ** 2 + b * b)
    k1, k2 = mean + rad, mean - rad                  # k1 ≥ k2
    ang1 = 0.5 * np.arctan2(2 * b, a - cc)           # direction of k1
    return ang1, k1, k2


def tangent_field(geo, symmetry=1, guide_attribute="", guide_weight=1.0,
                  align="none", output="tangent", rand_seed=0):
    """See the file header. Returns (geometry, report)."""
    from .peak import point_normals
    n = int(symmetry)
    if n not in SYMMETRIES:
        raise ValueError(f"Symmetry must be one of {SYMMETRIES}")
    if align not in ALIGN_MODES:
        raise ValueError(f"Align must be one of {ALIGN_MODES}")
    if align != "none" and n == 1:
        raise ValueError("Principal curvature directions are lines (both signs equal); curvature alignment needs Symmetry ≥ 2")
    if not geo.nprims:
        raise ValueError("Needs a polygon mesh")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    N = point_normals(geo)
    N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-300)
    t = topology(geo)
    ep = t.edge_points.astype(np.int64)
    npt = len(P)
    e1, e2 = _frames(P, N, t)
    d = P[ep[:, 1]] - P[ep[:, 0]]
    th_ij = _angle_in(d, e1[ep[:, 0]], e2[ep[:, 0]])
    th_ji = _angle_in(-d, e1[ep[:, 1]], e2[ep[:, 1]])
    r = th_ji + np.pi - th_ij                        # transport angle of edge (a->b)
    rho = np.exp(1j * n * r)
    a_, b_ = ep[:, 0], ep[:, 1]
    deg = np.bincount(ep.reshape(-1), minlength=npt).astype(np.float64)

    def apply_L(z):
        out = deg * z
        np.add.at(out, b_, -rho * z[a_])
        np.add.at(out, a_, -np.conj(rho) * z[b_])
        return out

    # constraints
    w = np.zeros(npt)
    c = np.zeros(npt, complex)
    gname = str(guide_attribute).strip()
    rep = {"symmetry": n, "guided_points": 0}
    if gname:
        G = geo.get(POINT, gname)
        if G is None or G.shape[1] < 3:
            raise KeyError(f"No point vector attribute '{gname}'")
        G = np.asarray(G[:, :3], np.float64)
        Gt = G - np.einsum("ij,ij->i", G, N)[:, None] * N
        # guides with almost nothing left after projecting onto the tangent plane (guide roughly along the normal) do not count: their direction is noise
        m = np.linalg.norm(Gt, axis=1) > 1e-5 * np.linalg.norm(G, axis=1)
        c[m] = np.exp(1j * n * _angle_in(Gt[m], e1[m], e2[m]))
        w[m] = float(guide_weight)
        rep["guided_points"] = int(m.sum())
    if align != "none":
        ang1, k1, k2 = _curvature_dirs(P, N, e1, e2, ep, npt)
        # the direction of larger |κ|
        bigger1 = np.abs(k1) >= np.abs(k2)
        amax = np.where(bigger1, ang1, ang1 + np.pi / 2)
        ang = amax if align == "max_curvature" else amax + np.pi / 2
        # relative anisotropy |k1 − k2| / (|k1| + |k2|) ∈ [0,1]: 1 on a cylinder, 0 on a sphere.
        # Must not be normalized by the global maximum -- on a sphere the anisotropy is all noise, and after normalizing the noise weight
        # is blown up to 1, so the field gets pulled into a pile of singularities by noise (tried: 46 on a sphere)
        s = np.abs(k1 - k2) / np.maximum(np.abs(k1) + np.abs(k2), 1e-300)
        cw = float(guide_weight) * s
        # combine with attribute guidance: weighted average by weight
        tot = w + cw
        cc = np.where(tot > 0, (w * c + cw * np.exp(1j * n * ang)) /
                      np.where(tot > 0, tot, 1.0), 0)
        c, w = cc, tot
    if (w > 0).any():
        z = _cg(lambda x: apply_L(x) + w * x, w * c, c.copy())
    else:
        rng = np.random.default_rng(int(rand_seed))
        z = rng.normal(size=npt) + 1j * rng.normal(size=npt)
        shift = 1e-3 * float(deg.mean() if npt else 1.0)
        for _ in range(60):
            z0 = z
            z = _cg(lambda x: apply_L(x) + shift * x, z, z, tol=1e-8)
            z /= np.linalg.norm(z)
            if np.linalg.norm(z - z0) < 1e-7:
                break
    mag = np.abs(z)
    alpha = np.angle(z) / n
    V = np.cos(alpha)[:, None] * e1 + np.sin(alpha)[:, None] * e2
    out = geo.copy()
    out.set(POINT, str(output).strip() or "tangent", V.astype(np.float32),
            owned=True)
    rep["energy"] = float(np.vdot(z / np.maximum(mag, 1e-300),
                                  apply_L(z / np.maximum(mag, 1e-300))).real)
    # singularities: going around each face, the number of turns of the field relative to transport (in units of 1/n turn)
    closed = geo.prim_closed & (geo.prim_sizes() >= 3)
    if closed.any():
        vp = np.asarray(geo.vertex_point, np.int64)
        nxt = geo.next_corner().astype(np.int64)
        vpr = geo.vertex_prim().astype(np.int64)
        ca, cb = vp, vp[nxt]
        dd = P[cb] - P[ca]
        rr = (_angle_in(-dd, e1[cb], e2[cb]) + np.pi -
              _angle_in(dd, e1[ca], e2[ca]))
        arg = np.angle(z)
        dl = _wrap(arg[cb] - arg[ca] - n * rr)
        ok = closed[vpr]
        np_ = geo.nprims
        sdl = np.bincount(vpr[ok], weights=dl[ok], minlength=np_)
        hol = _wrap(np.bincount(vpr[ok], weights=rr[ok], minlength=np_))
        idx = np.rint((sdl + n * hol) / (2 * np.pi)).astype(int)
        idx[~closed] = 0
        rep["singularities"] = int((idx != 0).sum())
        rep["index_sum"] = int(idx.sum())
    return out, rep
