"""
Unsubdivide (pcg74): undo one level of Catmull-Clark subdivision.

━━ Topology: recognize three kinds of points in the fine mesh
After one Catmull-Clark subdivision, every fine quad is [original vertex V, edge point E, face point F, edge point E].
So the fine mesh's points naturally fall into three classes, and:
  · fine mesh edges only join V–E and E–F -- two-colouring by edges, one colour is E, the other V∪F
  · of each quad's two diagonals, one joins V–F and one joins E–E -- two-colouring the V∪F colour again by diagonals
    separates V from F
Each of the two two-colourings has two choices (at most 4 combinations per connected piece). Hard conditions filter first: each quad must have exactly
one V, one F and two Es (V, F diagonal), each E connects to exactly two Vs, boundary Es touch exactly one F,
interior Es touch two. "F cannot be on the boundary" need not be checked separately, it is implied by the first two: suppose F point f is on the boundary;
its boundary neighbour x is a boundary E (degree 3: two Vs and one F), x's other boundary edge can only connect to a V point y,
and x's interior neighbour is a V point z; of the two quads containing (x,z), one is (f,x,z,·) -- f, z diagonal, fine,
the other is (y,x,z,·) -- two Vs y, z on a diagonal, violating the first condition. Among the rest pick the one with "fewest non-quads in the coarse
mesh" (cube subdivided once: taking the 8 corners as V gives 6 quads; taking the 6 face centers instead
as V gives 8 triangles -- the former is right); if still tied, pick the one where the lowest-numbered point of the piece is a V (in this plugin's
Subdivide output the original vertices come first, so point numbers are restored exactly).
Coarse faces: the ring of quads around each F point, chained by "previous E₂ = next E₁", taking from each quad
the V opposite F. A face starts at its lowest-numbered fine quad -- which likewise restores the pre-Subdivide
prim order and starting corner.

━━ Positions: fit (default) is an exact inverse, not "keep the V points where they are"
Subdivision moves the original vertices (V' = (F̄ + 2R̄ + (n−3)V)/n), so using the V points directly as the coarse mesh shrinks the shape
all over. Here subdivision is written as a linear map X_fine = S · X_coarse (S assembled row by row from the same
three stencils and boundary rules as Subdivide), and X_coarse is solved in the least-squares sense (conjugate gradient
on the normal equations). If the input really is a subdivision result, the solution is the original mesh (verified in the tests to float32
precision); if it was sculpted after subdividing, the solution is the coarse mesh "whose subdivision is closest to it". All numeric point
attributes go through the same solve (matching how Subdivide sends all point attributes through the same stencils).
keep mode just keeps the V points where they are (Houdini's Unsubdivide does this).

━━ Not implemented
  · creases: only Subdivide's three boundary modes are recognized (boundary as crease / corners pinned); subdivision with crease edge groups and
    auto crease angle cannot be undone (on the fine mesh you can no longer tell which edges were creases)
  · fine meshes whose topology was edited (faces deleted, loops added) are not recognized -- the error says which condition failed
  · edge groups are dropped (fine edges and coarse edges do not correspond one to one)
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, PRIM_POLY, is_string
from .topology import topology

POSITIONS = ("fit", "keep")
BOUNDARY = ("edge_corner", "edge_only", "smooth")


def _two_color(n, nbr_off, nbr):
    """BFS two-colouring of a CSR adjacency. Returns (colour 0/1/-1, connected piece number, whether bipartite)."""
    col = np.full(n, -1, np.int64)
    comp = np.full(n, -1, np.int64)
    ok = True
    k = 0
    for s in range(n):
        if col[s] >= 0 or nbr_off[s + 1] == nbr_off[s]:
            continue
        col[s] = 0
        comp[s] = k
        dq = deque([s])
        while dq:
            u = dq.popleft()
            for v in nbr[nbr_off[u]:nbr_off[u + 1]]:
                if col[v] < 0:
                    col[v] = 1 - col[u]
                    comp[v] = k
                    dq.append(v)
                elif col[v] == col[u]:
                    ok = False
        k += 1
    return col, comp, ok


def _csr(a, b, n):
    s = np.concatenate([a, b])
    d = np.concatenate([b, a])
    o = np.argsort(s, kind="stable")
    off = np.concatenate([[0], np.cumsum(np.bincount(s, minlength=n))])
    return off.astype(np.int64), d[o].astype(np.int64)


def _classify(geo):
    """Fine mesh points -> 0=V 1=E 2=F."""
    n = geo.npoints
    t = topology(geo)
    ep = t.edge_points.astype(np.int64)
    off, nb = _csr(ep[:, 0], ep[:, 1], n)
    col, comp, ok = _two_color(n, off, nb)
    if not ok:
        raise ValueError("Points cannot be two-coloured by edges -- this is not a mesh produced by Catmull-Clark subdivision"
                         " (after subdividing, every edge is attached to an edge point)")
    Q = np.asarray(geo.vertex_point, np.int64).reshape(-1, 4)
    deg = np.diff(off)
    bnd = np.zeros(n, bool)
    bnd[ep[t.boundary].reshape(-1)] = True
    cls = np.full(n, -1, np.int64)
    ncomp = int(comp.max()) + 1 if n else 0
    qcomp = comp[Q[:, 0]]
    for k in range(ncomp):
        qs = Q[qcomp == k]
        if not len(qs):
            continue
        best = None
        for a_col in (0, 1):
            # A = the V∪F colour: in each quad take the diagonal that lies on A
            onA = col[qs[:, 0]] == a_col
            d0 = np.where(onA, qs[:, 0], qs[:, 1])
            d1 = np.where(onA, qs[:, 2], qs[:, 3])
            doff, dnb = _csr(d0, d1, n)
            dcol, _, dok = _two_color(n, doff, dnb)
            if not dok:
                continue
            for v_col in (0, 1):
                c = np.full(n, -1, np.int64)
                members = np.nonzero(comp == k)[0]
                inA = col[members] == a_col
                c[members[~inA]] = 1
                va = members[inA]
                c[va] = np.where(dcol[va] == v_col, 0, 2)
                qc = np.sort(c[qs], axis=1)
                if not (qc == [0, 1, 1, 2]).all():
                    continue
                Es = members[c[members] == 1]
                good = True
                for e in Es.tolist():
                    ns = nb[off[e]:off[e + 1]]
                    nv = int((c[ns] == 0).sum())
                    nf = int((c[ns] == 2).sum())
                    if nv != 2 or nf not in (1, 2) or nv + nf != deg[e] or \
                            (nf == 1) != bool(bnd[e]):
                        good = False
                        break
                if not good:
                    continue
                Fs = members[c[members] == 2]
                nonquad = int((deg[Fs] != 4).sum())
                first_is_v = int(c[members.min()] == 0)
                score = (nonquad, -first_is_v)
                if best is None or score < best[0]:
                    best = (score, c)
        if best is None:
            raise ValueError("Cannot recognize the subdivision structure: no V / E / F assignment satisfies"
                             " 'each quad has one original vertex, one face point and two edge points'")
        m = comp == k
        cls[m] = best[1][m]
    return cls


def _coarse_topology(geo, cls):
    """Coarse mesh: points = V points (by fine point number), faces = the ring around each F point."""
    Q = np.asarray(geo.vertex_point, np.int64).reshape(-1, 4)
    nq = len(Q)
    # rotate each quad so F is at position 0: (f, e1, v, e2)
    kf = np.argmax(cls[Q] == 2, axis=1)
    idx = (kf[:, None] + np.arange(4)[None, :]) % 4
    R = np.take_along_axis(Q, idx, 1)
    corner_v = np.arange(nq) * 4 + (kf + 2) % 4       # corner number of the V corner
    Vpts = np.nonzero(cls == 0)[0]
    newid = np.full(geo.npoints, -1, np.int64)
    newid[Vpts] = np.arange(len(Vpts))
    byf = {}
    for q in range(nq):
        byf.setdefault(int(R[q, 0]), []).append(q)
    faces = []
    for f, qs in byf.items():
        nxt = {}
        for q in qs:
            e1 = int(R[q, 1])
            if e1 in nxt:
                raise ValueError("The quads around a face point cannot be chained (the same edge point appears twice)")
            nxt[e1] = q
        q0 = min(qs)
        ring = [q0]
        while True:
            e2 = int(R[ring[-1], 3])
            q = nxt.get(e2)
            if q is None:
                raise ValueError("The quads around a face point do not form a closed ring")
            if q == q0:
                break
            ring.append(q)
            if len(ring) > len(qs):
                raise ValueError("The quads around a face point do not form a closed ring")
        if len(ring) != len(qs):
            raise ValueError("The quads around a face point form more than one ring")
        faces.append((q0, ring))
    faces.sort()
    pts = [[int(newid[R[q, 2]]) for q in ring] for _, ring in faces]
    corners = [[int(corner_v[q]) for q in ring] for _, ring in faces]
    fpt = [int(R[q0, 0]) for q0, _ in faces]
    src_quad = [q0 for q0, _ in faces]
    return Vpts, pts, corners, fpt, src_quad, R


def _stencil(coarse, boundary):
    """Rows of the subdivision map: (fine point order: V points, F points, E points). Returns COO and the row index tables for each class."""
    from .subdivide import _crease_edges
    t = topology(coarse)
    n, nf, ne = coarse.npoints, coarse.nprims, t.nedges
    vp = np.asarray(coarse.vertex_point, np.int64)
    vprim = coarse.vertex_prim().astype(np.int64)
    sizes = coarse.prim_sizes().astype(np.float64)
    rows, cols, vals = [], [], []

    def add(r, c, w):
        rows.append(np.asarray(r, np.int64))
        cols.append(np.asarray(c, np.int64))
        vals.append(np.asarray(w, np.float64))

    # face points (row n + j): average of the face's corners
    fr = n + vprim
    add(fr, vp, 1.0 / sizes[vprim])
    # the face mean must be referenced by other rows as a "virtual row": expand into (face, point, weight)
    fm_f, fm_p, fm_w = vprim, vp, 1.0 / sizes[vprim]
    order = np.argsort(fm_f, kind="stable")
    fm_f, fm_p, fm_w = fm_f[order], fm_p[order], fm_w[order]
    foff = np.concatenate([[0], np.cumsum(np.bincount(fm_f, minlength=nf))])

    def face_rows(fs, scale, r):
        """Add scale[i] * face mean (fs[i]) to row r[i]."""
        cnt = foff[fs + 1] - foff[fs]
        rr = np.repeat(r, cnt)
        sc = np.repeat(scale, cnt)
        from .ops import _gather_blocks
        g = _gather_blocks(foff[fs], cnt)
        add(rr, fm_p[g], fm_w[g] * sc)

    crease = _crease_edges(coarse, t, "", -1.0, boundary)
    ep = t.edge_points.astype(np.int64)
    er = n + nf + np.arange(ne)
    inner = (t.edge_count == 2) & ~crease
    ii = np.nonzero(inner)[0]
    oo = np.nonzero(~inner)[0]
    add(np.r_[er[oo], er[oo]], np.r_[ep[oo, 0], ep[oo, 1]],
        np.full(2 * len(oo), 0.5))
    add(np.r_[er[ii], er[ii]], np.r_[ep[ii, 0], ep[ii, 1]],
        np.full(2 * len(ii), 0.25))
    if len(ii):
        f1 = vprim[t.edge_he[t.edge_he_off[ii]]]
        f2 = vprim[t.edge_he[t.edge_he_off[ii] + 1]]
        face_rows(f1, np.full(len(ii), 0.25), er[ii])
        face_rows(f2, np.full(len(ii), 0.25), er[ii])

    # vertices
    pe_cnt = np.diff(t.pt_edge_off)
    pp_cnt = np.diff(t.pt_prim_off)
    ce = np.nonzero(crease)[0]
    ends = np.concatenate([ep[ce, 0], ep[ce, 1]])
    other = np.concatenate([ep[ce, 1], ep[ce, 0]])
    ccnt = np.bincount(ends, minlength=n)
    on_crease = ccnt > 0
    use = ccnt == 2
    if boundary == "edge_corner":
        use &= pe_cnt != 2
    ident = (pe_cnt == 0) | (on_crease & ~use)
    add(np.nonzero(ident)[0], np.nonzero(ident)[0], np.ones(int(ident.sum())))
    # crease rule: (previous + 6 self + next)/8
    m = use[ends]
    add(ends[m], other[m], np.full(int(m.sum()), 1 / 8))
    u = np.nonzero(use)[0]
    add(u, u, np.full(len(u), 6 / 8))
    # smooth rule: (F̄ + 2R̄ + (n−3)P)/n
    sm = (pe_cnt > 0) & ~on_crease
    s_ = np.nonzero(sm)[0]
    if len(s_):
        val = pe_cnt[s_].astype(np.float64)
        # F̄/n: 1/(k·n) per adjacent face, k = number of adjacent faces
        cnt = pp_cnt[s_]
        from .ops import _gather_blocks
        g = _gather_blocks(t.pt_prim_off[s_], cnt)
        fs = t.pt_prim[g].astype(np.int64)
        r = np.repeat(s_, cnt)
        sc = np.repeat(1.0 / (np.maximum(cnt, 1) * val), cnt)
        face_rows(fs, sc, r)
        # 2R̄/n: R = adjacent edge midpoints, each edge (P + Q)/2, weight 2/(n·n)·1/2
        cnt = pe_cnt[s_]
        g = _gather_blocks(t.pt_edge_off[s_], cnt)
        es = t.pt_edge[g].astype(np.int64)
        r = np.repeat(s_, cnt)
        w = np.repeat(1.0 / (val * val), cnt)
        add(r, ep[es, 0], w)
        add(r, ep[es, 1], w)
        add(s_, s_, (val - 3.0) / val)
    R = np.concatenate(rows)
    C = np.concatenate(cols)
    W = np.concatenate(vals)
    return R, C, W, n + nf + ne, ep


def _solve(R, C, W, nrow, ncol, X, x0):
    """
    min ||S x − X||², S being COO. Conjugate gradient on the normal equations SᵀS x = SᵀX (several columns at once).
    Tried a Jacobi preconditioner: the iteration count did not drop (torus 49 -> 49, grid actually 26 -> 38),
    so it was dropped -- SᵀS is not badly conditioned to begin with (every coarse point is constrained by its own vertex row and the surrounding face / edge rows).
    """
    def Sx(x):
        out = np.zeros((nrow, x.shape[1]))
        np.add.at(out, R, W[:, None] * x[C])
        return out

    def STy(y):
        out = np.zeros((ncol, y.shape[1]))
        np.add.at(out, C, W[:, None] * y[R])
        return out
    x = x0.copy()
    b = STy(X)
    r = b - STy(Sx(x))
    p = r.copy()
    rr = np.einsum("ij,ij->j", r, r)
    bn = np.maximum(np.linalg.norm(b, axis=0), 1e-300)
    it = 0
    for it in range(5000):
        if (np.linalg.norm(r, axis=0) <= 1e-14 * bn).all():
            break
        Ap = STy(Sx(p))
        pAp = np.einsum("ij,ij->j", p, Ap)
        a = rr / np.where(pAp != 0, pAp, 1.0)
        x += a * p
        r -= a * Ap
        rr2 = np.einsum("ij,ij->j", r, r)
        p = r + (rr2 / np.where(rr != 0, rr, 1.0)) * p
        rr = rr2
    return x, it


def _once(geo, positions, boundary):
    if not geo.nprims:
        raise ValueError("No primitives")
    sizes = geo.prim_sizes()
    if not ((sizes == 4) & geo.prim_closed
            & (geo.prim_type == PRIM_POLY)).all():
        raise ValueError("The result of Catmull-Clark subdivision is all quads; this mesh has other primitives "
                         "-- it was not produced by subdivision (or was edited afterwards)")
    cls = _classify(geo)
    Vpts, faces, corners, fpt, src_quad, _ = _coarse_topology(geo, cls)
    nc = len(Vpts)
    out = Geometry()
    out._resize_points(nc)
    sz = np.array([len(f) for f in faces], np.int64)
    out.set_topology(np.concatenate([np.asarray(f) for f in faces])
                     .astype(np.int32),
                     np.concatenate([[0], np.cumsum(sz)]).astype(np.int32),
                     np.ones(len(faces), bool))
    for k, v in geo.attribs[POINT].items():
        out.set(POINT, k, v[Vpts], owned=True)
    for k, m in geo.groups[POINT].items():
        out.set_group(POINT, k, np.asarray(m)[Vpts])
    cor = np.concatenate([np.asarray(c) for c in corners]).astype(np.int64)
    for k, v in geo.attribs[VERTEX].items():
        out.set(VERTEX, k, v[cor], owned=True)
    for k, m in geo.groups[VERTEX].items():
        out.set_group(VERTEX, k, np.asarray(m)[cor])
    sq = np.asarray(src_quad, np.int64)
    for k, v in geo.attribs[PRIM].items():
        out.set(PRIM, k, v[sq], owned=True)
    for k, m in geo.groups[PRIM].items():
        out.set_group(PRIM, k, np.asarray(m)[sq])
    out.attribs[DETAIL] = dict(geo.attribs[DETAIL])
    rep = {"coarse_points": int(nc), "coarse_prims": int(len(faces))}
    if positions == "fit":
        R, C, W, nrow, ep = _stencil(out, boundary)
        # fine point row numbers: V in order = 0..nc-1; F = nc + coarse face number; E = nc + nf + coarse edge number
        fine_of_row = np.full(nrow, -1, np.int64)
        fine_of_row[:nc] = Vpts
        fine_of_row[nc:nc + len(faces)] = fpt
        # the fine edge point of coarse edge (a,b): the E point adjacent to both V a and V b
        t = topology(geo)
        fep = t.edge_points.astype(np.int64)
        newid = np.full(geo.npoints, -1, np.int64)
        newid[Vpts] = np.arange(nc)
        vend = np.where(cls[fep[:, 0]] == 0, fep[:, 0], fep[:, 1])
        eend = np.where(cls[fep[:, 0]] == 1, fep[:, 0], fep[:, 1])
        m = (cls[vend] == 0) & (cls[eend] == 1)
        e_ids = eend[m]
        v_ids = newid[vend[m]]
        o = np.lexsort((v_ids, e_ids))
        e_s, v_s = e_ids[o], v_ids[o]
        # each E has exactly two Vs (verified by _classify)
        a, b = v_s[0::2], v_s[1::2]
        epts = e_s[0::2]
        key = np.minimum(a, b) * (nc + 1) + np.maximum(a, b)
        ck = ep[:, 0] * (nc + 1) + ep[:, 1]
        so = np.argsort(key)
        pos = np.searchsorted(key[so], ck)
        pos = np.clip(pos, 0, max(len(key) - 1, 0))
        if len(key) == 0 or not (key[so][pos] == ck).all():
            raise ValueError("No fine edge point found for a coarse edge")
        fine_of_row[nc + len(faces):] = epts[so][pos]
        names = [k for k, v in geo.attribs[POINT].items() if not is_string(v)]
        cols = [geo.attribs[POINT][k].shape[1] for k in names]
        Xf = np.concatenate([np.asarray(geo.attribs[POINT][k], np.float64)
                             for k in names], 1)
        X = Xf[fine_of_row]
        x0 = Xf[Vpts]
        sol, its = _solve(R, C, W, nrow, nc, X, x0)
        res = np.zeros((nrow, X.shape[1]))
        np.add.at(res, R, W[:, None] * sol[C])
        rep["fit_rms"] = float(np.sqrt(np.mean((res - X) ** 2))) if X.size \
            else 0.0
        rep["cg_iterations"] = int(its)
        off = 0
        for k, c in zip(names, cols):
            dt = geo.attribs[POINT][k].dtype
            col = sol[:, off:off + c]
            out.set(POINT, k, (np.rint(col) if dt.kind in "iub" else col)
                    .astype(dt), owned=True)
            off += c
    return out, rep


def unsubdivide(geo, levels=1, positions="fit", boundary="edge_corner"):
    """See the file header. Returns (geometry, report)."""
    if positions not in POSITIONS:
        raise ValueError(f"Positions must be one of {POSITIONS}")
    if boundary not in BOUNDARY:
        raise ValueError(f"Boundary must be one of {BOUNDARY}")
    g = geo
    reps = []
    for _ in range(max(1, int(levels))):
        g, r = _once(g, positions, boundary)
        reps.append(r)
    rep = dict(reps[-1])
    rep["levels"] = len(reps)
    return g, rep
