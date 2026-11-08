"""
pcg100: Cross Section Surface with Houdini semantics (unrelated to the Gordon surface in curves2.cross_section_surface).

━━ What Houdini's Cross Section Surface is
Docs: it equals Sweep with only the second input -- no backbone curve, no guide curves, no resampling. One cross section is one
row of the grid, and point c of a cross section is column c; consecutive cross sections are joined by point number into quads (or triangles / row/column curves).
So **all cross sections must have the same point count** (the docs don't say what happens otherwise; Houdini's Sweep adds points, here it raises an error
that says so clearly, rather than guessing). When all cross sections are closed the column direction wraps (a tube); Close Implicit Backbone Curve wraps the row direction
(the last section connects back to the first: a torus).

━━ Orientation
Quads go (r,c) -> (r,c+1) -> (r+1,c+1) -> (r+1,c): normal = U x V (this plugin's right-hand rule), U along the cross section,
V pointing from one cross section to the next. Reverse Cross Sections reverses the point order of every cross section (normals flip with it);
Swap Rows and Columns makes points and faces column-major, flipping normals. End caps wind opposite to the sides along
the shared edges, so a capped tube is a closed manifold (verified in the tests).

━━ End caps (where the docs give no formula we decided ourselves; see the notes)
  single_polygon       closed cross sections, open backbone: one polygon at each end
  grid                 closed cross sections, open backbone: Cap Divisions rings added at each end: ring k (t = k/D, theta = t*pi/2)
                       is shrunk towards the centre by a factor s in the cross section's plane and raised by h along the section normal (away from the neighbouring section):
                         s = (1 - r)(1 - t) + r*cos(theta),  h = Scale*R*((1 - r)t + r*sin(theta))
                       R is the maximum distance from the section to its centre (bounding circle radius), r is Roundness: 1 = quarter circle (hemisphere),
                       0 = straight line (cone), negative reverses the curvature (concave). The last ring collapses to a pole: with Triangular Poles
                       there are triangles around the pole, otherwise quads with two duplicate vertices (the docs' wording)
  side_single_polygon  closed backbone, open cross sections: one polygon each for the first and last column
"""
from __future__ import annotations

import math

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, PRIM_POLY, is_string
from .groups import resolve

CSS_CAPS = ("none", "single_polygon", "grid", "side_single_polygon")
# Order of the Houdini menu; default is Quadrilaterals (set via default in the node)
CSS_SURFACES = ("points", "rows", "columns", "rows_and_columns", "triangles", "quads",
                "alt_triangles", "reverse_triangles")


def _newell(Q):
    n = np.zeros(3)
    m = len(Q)
    for i in range(m):
        a, b = Q[i], Q[(i + 1) % m]
        n += np.cross(a, b)
    return n


def _cap_rings(Q, Qadj, D, scale, rnd, sign):
    """grid end cap at one end: returns D - 1 rings (D-1, C, 3) (outwards from the section) and the pole (3,)."""
    C0 = Q.mean(0)
    Rb = float(np.linalg.norm(Q - C0, axis=1).max())
    n = _newell(Q)
    nn = float(np.linalg.norm(n))
    away = C0 - Qadj.mean(0) if Qadj is not None else None
    if nn <= 1e-12:
        n = away if away is not None else np.array([0.0, 0.0, 1.0])
        nn = max(float(np.linalg.norm(n)), 1e-300)
    n = n / nn
    if away is not None:
        if float(n @ away) < 0:
            n = -n
    else:
        n = n * sign                               # only one cross section: the two ends face opposite directions
    rings = []
    for k in range(1, D):
        t = k / D
        th = t * math.pi / 2
        s = (1 - rnd) * (1 - t) + rnd * math.cos(th)
        h = scale * Rb * ((1 - rnd) * t + rnd * math.sin(th))
        rings.append(C0 + (Q - C0) * s + n * h)
    pole = C0 + n * (scale * Rb)
    return (np.array(rings).reshape(-1, len(Q), 3), pole)


def cross_section_grid(geo, group="", reverse=False, cap_type="none", cap_divisions=3,
                       triangular_poles=False, cap_scale=1.0, cap_roundness=1.0, cap_group="",
                       surface="quads", unique_seam=False, swap=False, close_backbone=False,
                       compute_uvs=False, override_uvs=False, length_weighted=True,
                       normalize_u=True, normalize_v=False, wrap_u=True, wrap_v=True,
                       use_max_length=False, flip_u=True, uv_scale=(1.0, 1.0),
                       from_sections="*", point_row="", point_col="", prim_row="", prim_col="",
                       section_num=""):
    """See the file header. Returns (geometry, report dict)."""
    from .ops import match_names
    if cap_type not in CSS_CAPS:
        raise ValueError(f"End Cap Type must be one of {CSS_CAPS}")
    if surface not in CSS_SURFACES:
        raise ValueError(f"Surface Type must be one of {CSS_SURFACES}")
    sel = resolve(geo, PRIM, group) if geo is not None and geo.nprims else np.zeros(0, bool)
    secs = [i for i in np.nonzero(sel)[0].tolist() if int(geo.prim_type[i]) == PRIM_POLY
            and len(geo.prim_points(i)) >= 1]
    if not secs:
        return Geometry(), {"sections": 0}
    counts = {len(geo.prim_points(i)) for i in secs}
    if len(counts) > 1:
        raise ValueError(f"Cross sections have different point counts ({sorted(counts)}): Cross Section Surface connects rows and columns by point number, "
                         "so point counts must match. Put a Resample (Segment Count) first to equalize them")
    R, C = len(secs), counts.pop()
    S = np.array([geo.prim_points(i) for i in secs], np.int64).reshape(R, C)
    if reverse:
        S = S[:, ::-1]
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    wrapU = all(bool(geo.prim_closed[i]) for i in secs) and C >= 3
    wrapV = bool(close_backbone) and R >= 3
    poly_surf = surface in ("triangles", "quads", "alt_triangles", "reverse_triangles")

    # -- extended grid: cross section rows + (for grid caps) rings and poles at both ends. E is the output point number (Re, C); src is the source point for attributes
    src_rows = []
    grid_caps = cap_type == "grid" and wrapU and not wrapV and poly_surf and int(cap_divisions) >= 1
    D = max(1, int(cap_divisions))
    if grid_caps:
        rings0, pole0 = _cap_rings(P[S[0]], P[S[1]] if R > 1 else None, D, float(cap_scale),
                                   float(cap_roundness), -1.0)
        rings1, pole1 = _cap_rings(P[S[-1]], P[S[-2]] if R > 1 else None, D, float(cap_scale),
                                   float(cap_roundness), 1.0)
        pre = [("pole", pole0, S[0], secs[0])] + [("ring", r, S[0], secs[0]) for r in rings0[::-1]]
        post = [("ring", r, S[-1], secs[-1]) for r in rings1] + [("pole", pole1, S[-1], secs[-1])]
    else:
        pre, post = [], []
    body = [("row", P[S[r]], S[r], secs[r]) for r in range(R)]
    ext = pre + body + post
    Re = len(ext)
    npt = 0
    E = np.zeros((Re, C), np.int64)
    new_P, new_src, new_sec = [], [], []
    for r, (kind, Q, src, sn) in enumerate(ext):
        if kind == "pole":
            E[r] = npt
            new_P.append(Q[None])
            new_src.append(src[:1])
            new_sec.append([sn])
            npt += 1
        else:
            E[r] = npt + np.arange(C)
            new_P.append(Q)
            new_src.append(src)
            new_sec.append([sn] * C)
            npt += C
    NP = np.concatenate(new_P)
    NSRC = np.concatenate(new_src)
    NSEC = np.concatenate([np.asarray(s, np.int64) for s in new_sec])
    row_of = np.concatenate([[r] * (1 if ext[r][0] == "pole" else C) for r in range(Re)]).astype(np.int64)
    col_of = np.concatenate([[0] if ext[r][0] == "pole" else np.arange(C) for r in range(Re)]).astype(np.int64)
    first_body, last_body = len(pre), len(pre) + R - 1

    # -- topology. Each vertex records its "virtual" coordinate (vr, vc) in the extended grid: the wrapped ring has vc = C / vr = Re (seam)
    faces, vrc, prc, kinds = [], [], [], []          # kinds: 0 side 1 end cap 2 row curve 3 column curve
    fsec = []                                         # cross section each face takes prim attributes from
    closed_flags = []
    nr = Re if wrapV else Re - 1
    nc = C if wrapU else C - 1

    def at(vr, vc):
        return int(E[vr % Re, vc % C])

    if poly_surf:
        for r in range(nr):
            for c in range(nc):
                q = [(r, c), (r, c + 1), (r + 1, c + 1), (r + 1, c)]
                if surface == "quads":
                    tris = [q]
                elif surface == "triangles" or (surface == "alt_triangles" and (r + c) % 2 == 0):
                    tris = [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
                else:                                 # reverse_triangles, or the other half of alternating
                    tris = [[q[0], q[1], q[3]], [q[1], q[2], q[3]]]
                for f in tris:
                    ids = [at(*v) for v in f]
                    if triangular_poles:
                        keep = [k for k in range(len(f)) if ids[k] != ids[k - 1]]
                        f = [f[k] for k in keep]
                        ids = [ids[k] for k in keep]
                    if len(set(ids)) < 3:
                        continue                      # triangle with two vertices on the pole: degenerate, drop it
                    faces.append(ids)
                    vrc.append(f)
                    prc.append((r, c))
                    kinds.append(0)
                    fsec.append(ext[r % Re][3])
                    closed_flags.append(True)
        caps = []
        if cap_type == "single_polygon" and wrapU and not wrapV:
            caps = [[(first_body, c) for c in range(C)][::-1], [(last_body, c) for c in range(C)]]
        elif cap_type == "side_single_polygon" and wrapV and not wrapU and C >= 1:
            caps = [[(r, 0) for r in range(Re)], [(r, C - 1) for r in range(Re)][::-1]]
        for f, sn in zip(caps, (secs[0], secs[-1])):     # the wrapping direction has at least 3 points, so caps aren't degenerate
            faces.append([at(*v) for v in f])
            fsec.append(sn)
            vrc.append(None)                          # the docs don't specify end cap uv: write 0
            prc.append((-1, -1))
            kinds.append(1)
            closed_flags.append(True)
    else:
        if surface in ("rows", "rows_and_columns") and C >= 2:
            for r in range(Re):
                f = [(r, c) for c in range(C)]
                cl = wrapU
                if wrapU and unique_seam:
                    f, cl = f + [(r, C)], False       # one extra vertex at the seam (referencing the first point), so u = 0 and 1 are separate
                faces.append([at(*v) for v in f])
                fsec.append(ext[r][3])
                vrc.append(f)
                prc.append((r, 0))
                kinds.append(2)
                closed_flags.append(cl)
        if surface in ("columns", "rows_and_columns") and Re >= 2:
            for c in range(C):
                f = [(r, c) for r in range(Re)]
                cl = wrapV
                if wrapV and unique_seam:
                    f, cl = f + [(Re, c)], False
                faces.append([at(*v) for v in f])
                fsec.append(secs[0])
                vrc.append(f)
                prc.append((0, c))
                kinds.append(3)
                closed_flags.append(cl)

    # -- Swap Rows and Columns (docs: points and faces go from row-major to column-major, normals flip with it): each face's vertex order is
    #    reversed, points are reordered column-major, side faces are ordered by (column, row) (reshuffled within the slots they occupied). Row curves are still
    #    "one per cross section" and the row/column attributes keep their original meaning -- the docs only say "reorder", not that rows and columns swap meaning
    if swap:
        faces = [f[::-1] for f in faces]
        vrc = [v[::-1] if v is not None else None for v in vrc]
        side = [i for i, k in enumerate(kinds) if k == 0]
        perm = list(range(len(faces)))
        for dst, src in zip(side, sorted(side, key=lambda i: (prc[i][1], prc[i][0]))):
            perm[dst] = src
        faces, vrc, prc, kinds, closed_flags, fsec = ([L[i] for i in perm] for L in
                                                      (faces, vrc, prc, kinds, closed_flags, fsec))
        order = []
        seen = np.zeros(npt, bool)
        for k in E.T.ravel():
            if not seen[k]:
                seen[k] = True
                order.append(int(k))
        order = np.asarray(order, np.int64)
        remap = np.empty(npt, np.int64)
        remap[order] = np.arange(npt)
        NP, NSRC, NSEC = NP[order], NSRC[order], NSEC[order]
        row_of, col_of = row_of[order], col_of[order]
        faces = [[int(remap[i]) for i in f] for f in faces]

    out = Geometry()
    out._resize_points(npt)
    out.set(POINT, "P", NP.astype(np.float32), owned=True)
    if faces:
        sizes = np.array([len(f) for f in faces], np.int64)
        out.set_topology(np.concatenate([np.asarray(f, np.int32) for f in faces]),
                         np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                         np.asarray(closed_flags, bool), np.full(len(faces), PRIM_POLY, np.uint8))

    # -- attributes: From Cross Sections (point attributes from the source point, prim attributes from that row's cross section)
    for k in match_names([n for n in geo.attribs[POINT] if n != "P"], from_sections):
        v = geo.attribs[POINT][k]
        if is_string(v):
            out.set_string(POINT, k, np.asarray(v)[NSRC, 0])
        else:
            out.set(POINT, k, np.asarray(v)[NSRC], owned=True)
    if faces:
        fsec = np.asarray(fsec, np.int64)
        for k in match_names(list(geo.attribs[PRIM]), from_sections):
            v = geo.attribs[PRIM][k]
            if is_string(v):
                out.set_string(PRIM, k, np.asarray(v)[fsec, 0])
            else:
                out.set(PRIM, k, np.asarray(v)[fsec], owned=True)
        if cap_group:
            out.set_group(PRIM, cap_group, np.array([kd == 1 for kd in kinds]))
            if grid_caps:                              # grid caps are faces of the extended grid: decided per row
                m = np.array([kd == 0 and not (first_body <= rc[0] < last_body)
                              for kd, rc in zip(kinds, prc)])
                out.set_group(PRIM, cap_group, m)
        if prim_row:
            out.set(PRIM, prim_row, np.array([[p[0]] for p in prc], np.int32), owned=True)
        if prim_col:
            out.set(PRIM, prim_col, np.array([[p[1]] for p in prc], np.int32), owned=True)
    if point_row:
        out.set(POINT, point_row, row_of[:, None].astype(np.int32), owned=True)
    if point_col:
        out.set(POINT, point_col, col_of[:, None].astype(np.int32), owned=True)
    if section_num:
        out.set(POINT, section_num, NSEC[:, None].astype(np.int32), owned=True)

    # ── UV
    if compute_uvs:
        EP = NP if not swap else NP[np.argsort(order)]  # take positions in the pre-transpose point order
        Epos = EP[E]                                   # (Re, C, 3)
        seg_u = np.linalg.norm(np.diff(np.concatenate([Epos, Epos[:, :1]], 1) if wrapU else Epos, axis=1), axis=2)
        if not length_weighted:
            seg_u = np.ones_like(seg_u)
        Uraw = np.concatenate([np.zeros((Re, 1)), np.cumsum(seg_u, 1)], 1)     # (Re, C+1 or C)
        if not wrapU:
            Uraw = np.concatenate([Uraw, Uraw[:, -1:]], 1)                       # add a column so indices line up
        Ltot = Uraw[:, -1] if wrapU else Uraw[:, C - 1]
        stepv = (np.linalg.norm(np.diff(np.concatenate([Epos, Epos[:1]], 0) if wrapV else Epos, axis=0), axis=2).mean(1)
                 if length_weighted else np.ones(Re if wrapV else Re - 1))
        Vraw = np.concatenate([[0.0], np.cumsum(stepv)])
        if not wrapV:
            Vraw = np.append(Vraw, Vraw[-1])
        Vtot = float(Vraw[Re] if wrapV else Vraw[Re - 1])
        # U already on the input (Override unchecked): only used for open cross sections -- the seam ring of a closed section can't get its U from points
        uin = geo.get(POINT, "uv")
        copied = (not override_uvs) and uin is not None and not wrapU
        if copied:
            src_rows = np.array([e[2] if e[0] != "pole" else np.repeat(e[2][:1], C) for e in ext])
            Ucp = np.asarray(uin, np.float64)[src_rows][..., 0]
            U = np.concatenate([Ucp, Ucp[:, -1:]], 1)
        else:
            idxfrac = np.arange(C + 1) / max(nc, 1)
            Ln = np.where(Ltot > 1e-12, Ltot, 1.0)
            U = Uraw.copy()
            if normalize_u:
                U = np.where((Ltot > 1e-12)[:, None], Uraw / Ln[:, None], idxfrac[None, :])
            elif normalize_v:
                U = Uraw / (Vtot if Vtot > 1e-12 else 1.0)
            if wrap_u:                                # normalized U spans exactly 1, rounding doesn't change it -- no further check needed
                rng = U[:, nc]
                k = np.maximum(1.0, np.round(rng))
                U = U * np.where(rng > 1e-12, k / np.where(rng > 1e-12, rng, 1.0), 1.0)[:, None]
            if flip_u:
                U = U[:, nc:nc + 1] - U
        V = Vraw.copy()
        if normalize_v:
            V = V / (Vtot if Vtot > 1e-12 else 1.0)
        elif normalize_u:
            # V follows the physical proportion of U: each step divided by the average length of the two adjacent cross sections (or the longest one)
            if use_max_length:
                V = Vraw / max(float(Ltot.max()), 1e-12)
            else:
                avg = 0.5 * (Ltot + np.roll(Ltot, -1))
                if not wrapV:
                    avg = avg[:Re - 1]
                avg = np.where(avg > 1e-12, avg, 1.0)
                V = np.concatenate([[0.0], np.cumsum(np.diff(Vraw[:len(avg) + 1]) / avg)])
                if not wrapV:
                    V = np.append(V, V[-1])
        if wrap_v:                                    # same as above: normalized V spans 1
            rng = float(V[nr])
            if rng > 1e-12:
                V = V * (max(1.0, round(rng)) / rng)
        su, sv = float(uv_scale[0]), float(uv_scale[1])
        U, V = U * su, V * sv
        if surface == "points" or not faces:
            pr, pc = row_of, col_of
            out.set(POINT, "uv", np.stack([U[pr, pc], V[pr]], 1).astype(np.float32), owned=True)
        else:
            uv = []
            for f, vv in zip(faces, vrc):
                if vv is None:
                    uv.append(np.zeros((len(f), 2)))
                else:
                    uv.append(np.array([(U[r % Re, c], V[r]) for r, c in vv]))
            out.set(VERTEX, "uv", np.concatenate(uv).astype(np.float32), owned=True)
    return out, {"sections": R, "rows": int(Re), "cols": int(C)}
