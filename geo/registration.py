"""
"Correspondence between two geometries": Extract Transform, Attribute Transform Extract, Match Axis,
Match Topology, Topo Transfer.

━━ Extract Transform
reference and target have the same point count with one-to-one point numbers (the same geometry before and after a transform). Solves for the best
  rigid       rotation + translation (Kabsch)
  similarity  plus a uniform scale (Umeyama 1991)
  affine      general 3x3 linear + translation (least squares)
Outputs one "instance point": P = translation, orient = rotation, pscale = scale (for affine, writes the 3x3 attribute transform,
consistent with Copy to Points' convention, pivot = origin). Feeding it to Copy to Points
to copy reference lands it exactly on target (verified in tests). Also outputs reference transformed directly,
and the report includes the residual RMS. A Weight point attribute can weight points (e.g. to trust only some of them).

━━ Attribute Transform Extract
Does the same per piece (name): rest and animated share topology, one rigid transform per piece. Outputs two sets of points:
template (one point per piece, at the center of that piece in animated, with orient) and rest (one point per piece, at the center
of that piece in rest, identity orientation) -- exactly the two inputs Transform Pieces needs: use them to transform another
geometry (high-res fragments, a version with different materials), and every piece follows exactly.

━━ Match Axis
Minimally rotate From Axis onto To Axis (when opposite, rotate 180 deg about a perpendicular axis), about origin /
centroid / bbox_center. Optional Up: align the main axis first, then rotate about it so that Up From's projection in the perpendicular plane
matches Up To. Direction attributes (N / up / v) rotate along, orient is left-multiplied.

━━ Match Topology
target and reference are the same mesh, but point numbers, prim numbers and each prim's starting corner are scrambled (export /
import, edited in other software). Renumber target to match reference.
  topology  start from a pair of "seed" corners and walk both meshes in sync via half-edge opposites: on ref from prim A across
            an edge to prim B, on target likewise from the corresponding prim across the corresponding edge -- covering the whole connected piece.
            **Positions are ignored**, target can be deformed any way. With seeds left at -1 they are found automatically: for ref's prim 0,
            pick the prim in target with the same edge count and nearest center, with the starting corner aligned by point distance
            (so automatic seeding requires at least one face of target to roughly coincide with ref; otherwise fill them in by hand)
  position  each ref point finds the nearest point in target (within tolerance) -- for when the shape did not change, only the numbering is scrambled
The report says how many points / prims matched and whether there were contradictions (which occur when topology differs). Unmatched points and prims
are appended at the end, not lost.

━━ Topo Transfer
Apply source's topology (edge flow) onto target's shape -- "wrap" a retopologized mesh onto a new scan,
or fit a standard edge flow onto different characters.
  1. Align first: landmark is an integer point attribute (named landmark by default); points with the same value (>= 0) on both sides
     are a pair -- not paired by point number or group order, so one wrong label does not shift everything. With >= 3 pairs,
     Umeyama solves a similarity transform; otherwise align by bounding box center and diagonal length
  2. Iterate: each point is projected to the nearest point on target's surface, and the displacement field is Laplacian-smoothed a few rounds and then added
     (what is smoothed is the **displacement**, not the position -- edge-flow density is preserved while the whole is pulled toward target). The smoothing
     strength decreases over iterations, the last round is pure projection, and the points all land on target. Landmarks are pinned every round
This is not full non-rigid ICP (no per-point affine stiffness); places with large stretching (fingers, ears) need
more landmarks.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, VERTEX, is_string
from .groups import resolve
from . import xform as _xf

XF_MODES = ("rigid", "similarity", "affine", "nonuniform")
XF_OUTPUTS = ("standard", "matrix3", "matrix4")
XF_CLASSES = ("prim", "point")
PIVOTS = ("origin", "centroid", "bbox_center")
MT_MODES = ("topology", "position")


# ═══════════════════════════════════════════════════════════ common
def umeyama(A, B, w=None, mode="rigid"):
    """Minimize sum w_i|s.R.a_i + t - b_i|^2. Returns (M = s.R or the affine matrix, t, rms)."""
    A = np.asarray(A, np.float64)
    B = np.asarray(B, np.float64)
    w = np.ones(len(A)) if w is None else np.maximum(np.asarray(w, np.float64), 0)
    if w.sum() <= 0:
        raise ValueError("All weights are 0")
    w = w / w.sum()
    ca, cb = w @ A, w @ B
    a, b = A - ca, B - cb
    if mode == "affine":
        H = (a * w[:, None]).T @ a
        M = np.linalg.lstsq(H, (a * w[:, None]).T @ b, rcond=None)[0].T
    else:
        S = (b * w[:, None]).T @ a                      # Σ w b aᵀ
        U, D, Vt = np.linalg.svd(S)
        d = np.sign(np.linalg.det(U @ Vt)) or 1.0
        E = np.diag([1.0, 1.0, d])
        R = U @ E @ Vt
        s = 1.0
        if mode == "similarity":
            va = float((w * (a ** 2).sum(1)).sum())
            s = float(np.trace(np.diag(D) @ E)) / va if va > 0 else 1.0
        M = s * R
    t = cb - M @ ca
    res = A @ M.T + t - B
    return M, t, float(np.sqrt((w * (res ** 2).sum(1)).sum()))


def _decompose(M):
    """M = s.R (similarity) -> (R, s)."""
    s = float(np.cbrt(abs(np.linalg.det(M))))
    return M / (s if s > 0 else 1.0), s


def _rotate_attrs(src, g, Mpt, sel=None):
    """N (inverse transpose) and up / v (M) on points / vertices transform along; orient is left-multiplied by the rotation."""
    from .deformers import _rotate_dirs
    from .curveframe import mat_to_quat
    _rotate_dirs(src, g, Mpt, sel)
    o = src.get(POINT, "orient")
    if o is not None and o.shape[1] == 4:
        R = np.array([_decompose(m)[0] for m in Mpt])
        q = mat_to_quat(np.einsum("nij,njk->nik", R, _xf.quat_to_mat(
            np.asarray(o, np.float64))))
        if sel is not None:
            q = np.where(sel[:, None], q, np.asarray(o, np.float64))
        g.set(POINT, "orient", q.astype(o.dtype), owned=True)


# ═══════════════════════════════════════════════════════════ Extract Transform
def _fit_nonuniform(A, B, w=None, iters=60):
    """
    Translation, Rotation, and Non-Uniform Scale: minimize sum w_i|R.diag(s).a_i + t - b_i|^2.

    No closed-form solution, so alternate: with R fixed, s on each axis is a 1D least squares; with s fixed, R is the Kabsch of (a.s, b).
    Starts from the similarity solution. s may be negative (mirroring along some axis); R keeps det = +1.
    """
    A = np.asarray(A, np.float64)
    B = np.asarray(B, np.float64)
    w = np.ones(len(A)) if w is None else np.maximum(np.asarray(w, np.float64), 0)
    if w.sum() <= 0:
        raise ValueError("All weights are 0")
    w = w / w.sum()
    ca, cb = w @ A, w @ B
    a, b = A - ca, B - cb
    M0, _, _ = umeyama(A, B, w, "similarity")
    R, s0 = _decompose(M0)
    s = np.full(3, s0)
    den = (w[:, None] * a * a).sum(0)
    for _ in range(int(iters)):
        bl = b @ R                                        # each row R^T.b
        s = np.where(den > 0, (w[:, None] * bl * a).sum(0) / np.where(den > 0, den, 1), 1.0)
        U, _, Vt = np.linalg.svd((b * w[:, None]).T @ (a * s))
        d = np.sign(np.linalg.det(U @ Vt)) or 1.0
        R = U @ np.diag([1.0, 1.0, d]) @ Vt
    M = R @ np.diag(s)
    t = cb - M @ ca
    res = A @ M.T + t - B
    return M, t, float(np.sqrt((w * (res ** 2).sum(1)).sum()))


def _fit(A, B, w, mode):
    return _fit_nonuniform(A, B, w) if mode == "nonuniform" else umeyama(A, B, w, mode)


def _rs(M):
    """R.diag(s) -> (R, s); s is taken as column lengths, and with mirroring the sign goes on the last axis."""
    s = np.linalg.norm(M, axis=0)
    R = M / np.where(s > 0, s, 1.0)
    if np.linalg.det(R) < 0:
        R[:, 2] *= -1
        s[2] *= -1
    return R, s


def extract_transform(reference, target, mode="rigid", weight_attribute="",
                      piece_attribute="", piece_class="prim", output="standard",
                      distortion_attrib=""):
    """
    Returns (instance points, transformed reference, report).

    piece_attribute non-empty (Use Piece Attribute): split into pieces by this prim / point attribute, one transform per piece,
    one output point each (carrying the attribute of the same name); the point is placed at the **transformed piece center**, pivot = the (weighted) center of that piece in reference,
    so Copy to Points copying that piece of reference lands it exactly on target. Pieces with too few points to fit
    (rigid / uniform / non-uniform scale < 3, affine < 4) only solve for translation, counted in the report.
    Whole mode (old behaviour): the point is at translation t, pivot = origin.

    output(Output Attributes):
        standard  old behaviour: orient + pscale (uniform) / scale (non-uniform); affine writes a 3x3 transform
        matrix3   Transform Matrix (3×3) and Translation:transform(9)+ P
        matrix4   Transform Matrix (4x4): transform (16 values, translation in the 4th row, read the same way as point_matrices),
                  P at the origin, no pivot written -- the whole transform is in the matrix
    distortion_attrib non-empty (Compute Distortion): each output point gets this piece's residual RMS
    (weighted root mean square of distances from transformed reference points to target points).
    """
    if mode not in XF_MODES:
        raise ValueError(f"Mode must be one of {XF_MODES}")
    if output not in XF_OUTPUTS:
        raise ValueError(f"Output Attributes must be one of {XF_OUTPUTS}")
    if piece_class not in XF_CLASSES:
        raise ValueError(f"Attribute Class must be one of {XF_CLASSES}")
    if reference.npoints != target.npoints:
        raise ValueError(f"reference has {reference.npoints} points, target has "
                         f"{target.npoints} -- they must be the same geometry before and after a transform (one-to-one point numbers)")
    need = 4 if mode == "affine" else 3
    pa = str(piece_attribute).strip()
    if not pa and reference.npoints < need:
        raise ValueError(f"{mode} needs at least {need} points")
    A = np.asarray(reference.get(POINT, "P"), np.float64)
    B = np.asarray(target.get(POINT, "P"), np.float64)
    w = None
    wn = str(weight_attribute).strip()
    if wn:
        a = reference.get(POINT, wn)
        if a is None:
            raise KeyError(f"No point attribute '{wn}' on reference")
        w = np.asarray(a, np.float64)[:, 0]
    if pa:
        return _extract_pieces(reference, A, B, w, mode, pa, piece_class, output,
                               distortion_attrib, need)
    M, t, rms = _fit(A, B, w, mode)
    pt = Geometry.from_points(t[None])                  # pivot defaults to the origin
    rep = {"mode": mode, "rms": rms, "translate": t.tolist()}
    _write_xform(pt, M[None], t[None], None, mode, output, rep)
    if str(distortion_attrib).strip():
        pt.set(POINT, str(distortion_attrib).strip(), np.array([[rms]], np.float32))
    out = reference.copy()
    out.set(POINT, "P", (A @ M.T + t).astype(np.float32), owned=True)
    _rotate_attrs(reference, out, np.tile(M, (reference.npoints, 1, 1)))
    return pt, out, rep


def _write_xform(pt, Ms, ts, pivots, mode, output, rep):
    """Write n transforms onto n points according to Output Attributes (P is already placed by the caller)."""
    from .curveframe import mat_to_quat
    n = len(Ms)
    if pivots is not None and output != "matrix4":
        pt.set(POINT, "pivot", pivots.astype(np.float32))
    if output == "matrix4":
        m4 = np.zeros((n, 4, 4))
        m4[:, :3, :3] = np.transpose(Ms, (0, 2, 1))   # Houdini row-vector convention: p' = p.M
        m4[:, 3, :3] = ts
        m4[:, 3, 3] = 1.0
        pt.set(POINT, "P", np.zeros((n, 3), np.float32))
        pt.set(POINT, "transform", m4.reshape(n, 16).astype(np.float32))
    elif output == "matrix3" or mode == "affine":
        pt.set(POINT, "transform", np.transpose(Ms, (0, 2, 1)).reshape(n, 9)
               .astype(np.float32))                     # row-vector convention, consistent with Houdini
        if n == 1:
            rep["matrix"] = Ms[0].T.tolist()
    elif mode == "nonuniform":
        R, S = zip(*[_rs(m) for m in Ms])
        pt.set(POINT, "orient", mat_to_quat(np.array(R)).astype(np.float32))
        pt.set(POINT, "scale", np.array(S).astype(np.float32))
        if n == 1:
            rep["scale"] = list(map(float, S[0]))
    else:
        R, s = zip(*[_decompose(m) for m in Ms])
        pt.set(POINT, "orient", mat_to_quat(np.array(R)).astype(np.float32))
        pt.set(POINT, "pscale", np.array(s, np.float64)[:, None].astype(np.float32))
        if n == 1:
            rep["scale"] = float(s[0])


def _extract_pieces(reference, A, B, w, mode, pa, piece_class, output, dattr, need):
    cls = PRIM if piece_class == "prim" else POINT
    key = reference.get(cls, pa)
    if key is None:
        raise KeyError(f"No {cls} attribute '{pa}' on reference")
    k = key[:, 0]
    n = reference.npoints
    if cls == PRIM:
        vp = reference.vertex_point.astype(np.int64)
        vpr = reference.vertex_prim()
    names, Ms, ts, cs, rms = [], [], [], [], []
    Mall = np.tile(np.eye(3), (n, 1, 1))
    tall = np.zeros((n, 3))
    sel = np.zeros(n, bool)
    short = 0
    for u in np.unique(k).tolist():
        pts = np.unique(vp[k[vpr] == u]) if cls == PRIM else np.nonzero(k == u)[0]
        if not len(pts):
            continue
        wp = None if w is None else w[pts]
        ww = np.ones(len(pts)) if wp is None else np.maximum(wp, 0)
        if ww.sum() <= 0:
            raise ValueError(f"All weights of piece {u!r} are 0")
        ww = ww / ww.sum()
        if len(pts) >= need:
            M, t, e = _fit(A[pts], B[pts], wp, mode)
        else:                                            # too few points: translation only
            short += 1
            M = np.eye(3)
            t = ww @ (B[pts] - A[pts])
            res = A[pts] + t - B[pts]
            e = float(np.sqrt((ww * (res ** 2).sum(1)).sum()))
        names.append(u)
        Ms.append(M)
        ts.append(t)
        cs.append(ww @ A[pts])
        rms.append(e)
        Mall[pts] = M
        tall[pts] = t
        sel[pts] = True
    Ms, ts, cs = np.array(Ms).reshape(-1, 3, 3), np.array(ts).reshape(-1, 3), \
        np.array(cs).reshape(-1, 3)
    # The point is placed at the transformed piece center; the instance transform M(p - pivot) + P equals exactly M p + t
    P = np.einsum("nij,nj->ni", Ms, cs) + ts
    pt = Geometry.from_points(P.astype(np.float32))
    if is_string(key):
        pt.set_string(POINT, pa, np.array(names))
    else:
        pt.set(POINT, pa, np.array(names).reshape(-1, 1).astype(key.dtype))
    rep = {"mode": mode, "pieces": len(names), "translation_only_pieces": short,
           "max_rms": float(max(rms)) if rms else 0.0}
    # The translation in the instance transform must be converted by pivot: M(p - c) + P; in matrix 4x4 mode the translation is just t
    _write_xform(pt, Ms, ts, cs, mode, output, rep)
    if str(dattr).strip():
        pt.set(POINT, str(dattr).strip(), np.array(rms, np.float32)[:, None])
    out = reference.copy()
    out.set(POINT, "P", (np.einsum("nij,nj->ni", Mall, A) + tall).astype(np.float32),
            owned=True)
    _rotate_attrs(reference, out, Mall, sel)
    return pt, out, rep


def attribute_transform_extract(rest, animated, piece_attribute="name"):
    """One rigid transform per piece. Returns (template points, rest points, report)."""
    if rest.npoints != animated.npoints:
        raise ValueError(f"rest has {rest.npoints} points, animated has "
                         f"{animated.npoints} -- they must share topology")
    nm = str(piece_attribute).strip() or "name"
    key, cls = rest.get(PRIM, nm), PRIM
    if key is None:
        key, cls = rest.get(POINT, nm), POINT
    if key is None:
        raise KeyError(f"No prim / point attribute '{nm}' on rest")
    k = key[:, 0]
    A = np.asarray(rest.get(POINT, "P"), np.float64)
    B = np.asarray(animated.get(POINT, "P"), np.float64)
    if cls == PRIM:
        vp = rest.vertex_point.astype(np.int64)
        vpr = rest.vertex_prim()
    names, Pt, Pr, Q, rms = [], [], [], [], []
    from .curveframe import mat_to_quat
    for u in np.unique(k).tolist():
        pts = np.unique(vp[k[vpr] == u]) if cls == PRIM else np.nonzero(k == u)[0]
        if not len(pts):
            continue
        a, b = A[pts], B[pts]
        if len(pts) >= 3:
            M, t, e = umeyama(a, b, None, "rigid")
        else:
            M, t, e = np.eye(3), b.mean(0) - a.mean(0), 0.0
        ca = a.mean(0)
        names.append(u)
        Pr.append(ca)
        Pt.append(M @ ca + t)
        Q.append(mat_to_quat(M[None])[0])
        rms.append(e)
    tmpl = Geometry.from_points(np.array(Pt).reshape(-1, 3))
    rst = Geometry.from_points(np.array(Pr).reshape(-1, 3))
    for g in (tmpl, rst):
        if is_string(key):
            g.set_string(POINT, nm, np.array(names))
        else:
            g.set(POINT, nm, np.array(names).reshape(-1, 1).astype(key.dtype))
    tmpl.set(POINT, "orient", np.array(Q).reshape(-1, 4).astype(np.float32))
    rst.set(POINT, "orient", np.tile([0, 0, 0, 1.0], (len(names), 1))
            .astype(np.float32))
    return tmpl, rst, {"pieces": len(names),
                       "max_rms": float(max(rms)) if rms else 0.0}


# ═══════════════════════════════════════════════════════════ Match Axis
def _min_rot(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        ax = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(ax) < 1e-6:
            ax = np.cross(a, [0, 1.0, 0])
        ax /= np.linalg.norm(ax)
        return 2 * np.outer(ax, ax) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)


def match_axis(geo, from_axis=(0, 1, 0), to_axis=(0, 0, 1), pivot="origin",
               up_from=(0, 0, 0), up_to=(0, 0, 0), group=""):
    if pivot not in PIVOTS:
        raise ValueError(f"Pivot must be one of {PIVOTS}")
    fa, ta = np.asarray(from_axis, float), np.asarray(to_axis, float)
    if np.linalg.norm(fa) < 1e-12 or np.linalg.norm(ta) < 1e-12:
        raise ValueError("From Axis / To Axis cannot be a zero vector")
    R = _min_rot(fa, ta)
    uf, ut = np.asarray(up_from, float), np.asarray(up_to, float)
    if np.linalg.norm(uf) > 1e-12 and np.linalg.norm(ut) > 1e-12:
        t = ta / np.linalg.norm(ta)
        u1 = R @ uf
        u1 = u1 - (u1 @ t) * t
        u2 = ut - (ut @ t) * t
        if np.linalg.norm(u1) > 1e-9 and np.linalg.norm(u2) > 1e-9:
            u1 /= np.linalg.norm(u1)
            u2 /= np.linalg.norm(u2)
            ang = np.arctan2(np.cross(u1, u2) @ t, u1 @ u2)
            K = np.array([[0, -t[2], t[1]], [t[2], 0, -t[0]], [-t[1], t[0], 0]])
            R = (np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K) @ R
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    sel = resolve(geo, POINT, group) if str(group).strip() else \
        np.ones(geo.npoints, bool)
    if pivot == "origin" or not len(P):
        c = np.zeros(3)
    elif pivot == "centroid":
        c = P[sel].mean(0)
    else:
        c = 0.5 * (P[sel].min(0) + P[sel].max(0))
    out = P.copy()
    out[sel] = (P[sel] - c) @ R.T + c
    g = geo.copy()
    g.set(POINT, "P", out.astype(np.float32), owned=True)
    _rotate_attrs(geo, g, np.tile(R, (geo.npoints, 1, 1)), sel)
    return g


# ═══════════════════════════════════════════════════════════ Match Topology
def _auto_seed(ref, tgt):
    from .ops import prim_centers
    Pr = np.asarray(ref.get(POINT, "P"), np.float64)
    Pt = np.asarray(tgt.get(POINT, "P"), np.float64)
    n0 = int(ref.prim_sizes()[0])
    c0 = prim_centers(ref)[0].astype(np.float64)
    ct = prim_centers(tgt).astype(np.float64)
    cand = np.nonzero(tgt.prim_sizes() == n0)[0]
    if not len(cand):
        raise ValueError("target has no face with the same edge count as ref's prim 0; automatic seeding failed")
    tp = int(cand[np.argmin(np.linalg.norm(ct[cand] - c0, axis=1))])
    rv = Pr[ref.prim_points(0)]
    tv = Pt[tgt.prim_points(tp)]
    cost = [float(((rv - np.roll(tv, -s, 0)) ** 2).sum()) for s in range(n0)]
    s = int(np.argmin(cost))
    return 0, int(ref.prim_offset[0]), tp, int(tgt.prim_offset[tp]) + s


def match_topology(ref, tgt, mode="topology", ref_prim=-1, ref_point=-1,
                   tgt_prim=-1, tgt_point=-1, tolerance=1e-4):
    """Returns (renumbered tgt, report)."""
    if mode not in MT_MODES:
        raise ValueError(f"Mode must be one of {MT_MODES}")
    nr, nt = ref.npoints, tgt.npoints
    pmap = np.full(nr, -1, np.int64)                 # ref point -> tgt point
    fmap = np.full(ref.nprims, -1, np.int64)         # ref prim -> tgt prim
    cmap = np.full(ref.nvertices, -1, np.int64)      # ref corner -> tgt corner
    conflicts = 0
    if mode == "position":
        from . import spatial as _sp
        Pr = np.asarray(ref.get(POINT, "P"), np.float64)
        Pt = np.asarray(tgt.get(POINT, "P"), np.float64)
        qi, pi, d = _sp.neighbors_within(Pr, Pt, float(tolerance))
        if len(qi):
            o = np.lexsort((d, qi))
            q_, f_ = np.unique(qi[o], return_index=True)
            pmap[q_] = pi[o][f_]
        used = pmap[pmap >= 0]
        conflicts = int(len(used) - len(np.unique(used)))
    else:
        if ref.nprims == 0 or tgt.nprims == 0:
            raise ValueError("topology mode requires faces")
        if min(ref_prim, tgt_prim) < 0:
            rp, rc, tp, tc = _auto_seed(ref, tgt)
        else:
            rp, tp = int(ref_prim), int(tgt_prim)
            rpts = ref.prim_points(rp).tolist()
            tpts = tgt.prim_points(tp).tolist()
            if int(ref_point) not in rpts or int(tgt_point) not in tpts:
                raise ValueError("The seed point must be in the seed prim")
            if len(rpts) != len(tpts):
                raise ValueError("The two seed prims have different edge counts")
            rc = int(ref.prim_offset[rp]) + rpts.index(int(ref_point))
            tc = int(tgt.prim_offset[tp]) + tpts.index(int(tgt_point))
        from .topology import topology
        Tr, Tt = topology(ref), topology(tgt)
        rvp = ref.vertex_prim()
        tvp = tgt.vertex_prim()
        rsz, tsz = ref.prim_sizes(), tgt.prim_sizes()
        roff, toff = ref.prim_offset, tgt.prim_offset

        def map_prim(pr, cr, pt, ct):
            n = int(rsz[pr])
            if n != int(tsz[pt]):
                return False
            kr, kt = cr - roff[pr], ct - toff[pt]
            for i in range(n):
                cmap[roff[pr] + (kr + i) % n] = toff[pt] + (kt + i) % n
            fmap[pr] = pt
            return True

        tused = np.zeros(tgt.nprims, bool)
        if not map_prim(rp, rc, tp, tc):
            raise ValueError("The seed prims have different edge counts")
        tused[tp] = True
        queue = [rp]
        while queue:
            pr = queue.pop()
            for c in range(roff[pr], roff[pr + 1]):
                tw = Tr.he_twin[c]
                if tw < 0:
                    continue
                pr2 = int(rvp[tw])
                ctw = Tt.he_twin[cmap[c]]
                if ctw < 0:
                    conflicts += 1
                    continue
                pt2 = int(tvp[ctw])
                if fmap[pr2] >= 0:
                    if fmap[pr2] != pt2 or cmap[tw] != ctw:
                        conflicts += 1
                    continue
                if tused[pt2] or not map_prim(pr2, tw, pt2, ctw):
                    conflicts += 1
                    continue
                tused[pt2] = True
                queue.append(pr2)
        ok = cmap >= 0
        rvp_pts = ref.vertex_point.astype(np.int64)
        tvp_pts = tgt.vertex_point.astype(np.int64)
        pmap[rvp_pts[ok]] = tvp_pts[cmap[ok]]
        # The same ref point mapped to different tgt points = inconsistent topology
        chk = np.full(nr, -1, np.int64)
        chk[rvp_pts[ok]] = tvp_pts[cmap[ok]]
        conflicts += int((chk[rvp_pts[ok]] != tvp_pts[cmap[ok]]).sum())

    # ── Reorder tgt by the mapping: new point i = the tgt point matched to ref point i; ref point numbers left unmatched are filled
    #    with the remaining tgt points in original order, and any left over are appended (no point lost)
    seen = np.zeros(nt, bool)
    for i in range(nr):                                # the same tgt point is only taken the first time
        if pmap[i] >= 0:
            if seen[pmap[i]]:
                pmap[i] = -1
                conflicts += 1
            else:
                seen[pmap[i]] = True
    if mode == "position" and (pmap < 0).any() and (~seen).any():
        # Second pass: coincident points (two points at the same position) get only one matched in the first pass; the rest search for the nearest
        # among "target points not yet used"
        Pr_ = np.asarray(ref.get(POINT, "P"), np.float64)
        Pt_ = np.asarray(tgt.get(POINT, "P"), np.float64)
        for i in np.nonzero(pmap < 0)[0]:
            free = np.nonzero(~seen)[0]
            if not len(free):
                break
            d_ = np.linalg.norm(Pt_[free] - Pr_[i], axis=1)
            j = int(np.argmin(d_))
            if d_[j] <= float(tolerance):
                pmap[i] = free[j]
                seen[free[j]] = True
    matched = pmap >= 0
    rest = list(np.nonzero(~seen)[0])
    src = []
    for i in range(nr):
        if matched[i]:
            src.append(int(pmap[i]))
        elif rest:
            src.append(int(rest.pop(0)))
    src += [int(r) for r in rest]
    src_pts = np.array(src, np.int64)
    remap = np.full(nt, -1, np.int64)
    remap[src_pts] = np.arange(len(src_pts))
    # prim order and starting corners
    if mode == "topology":
        prim_src = [int(fmap[p]) for p in range(ref.nprims) if fmap[p] >= 0]
        corners = [cmap[ref.prim_offset[p]:ref.prim_offset[p + 1]]
                   for p in range(ref.nprims) if fmap[p] >= 0]
        left = np.setdiff1d(np.arange(tgt.nprims), prim_src)
        for p in left:
            prim_src.append(int(p))
            corners.append(np.arange(tgt.prim_offset[p], tgt.prim_offset[p + 1]))
    else:
        prim_src = list(range(tgt.nprims))
        corners = [np.arange(tgt.prim_offset[p], tgt.prim_offset[p + 1])
                   for p in range(tgt.nprims)]
    corner_src = np.concatenate(corners).astype(np.int64) if corners else \
        np.zeros(0, np.int64)
    out = Geometry()
    out._resize_points(len(src_pts))
    sizes = np.array([len(c) for c in corners], np.int64)
    out.set_topology(remap[tgt.vertex_point[corner_src]].astype(np.int32),
                     np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32),
                     tgt.prim_closed[prim_src], tgt.prim_type[prim_src])
    for k_, v in tgt.attribs[POINT].items():
        out.set(POINT, k_, v[src_pts], owned=True)
    for k_, v in tgt.attribs[VERTEX].items():
        out.set(VERTEX, k_, v[corner_src], owned=True)
    for k_, v in tgt.attribs[PRIM].items():
        out.set(PRIM, k_, v[prim_src], owned=True)
    for k_, v in tgt.groups[POINT].items():
        out.set_group(POINT, k_, v[src_pts])
    for k_, v in tgt.groups[PRIM].items():
        out.set_group(PRIM, k_, v[prim_src])
    out.attribs["detail"] = dict(tgt.attribs["detail"])
    return out, {"mode": mode, "points_matched": int(matched.sum()),
                 "points_ref": nr, "prims_matched": int((fmap >= 0).sum())
                 if mode == "topology" else None, "conflicts": int(conflicts)}


# ═══════════════════════════════════════════════════════════ Topo Transfer
def _landmark_pairs(source, target, name):
    """Pair by integer point attribute: points with the same value (and >= 0) on both sides are a landmark pair."""
    nm = str(name).strip()
    if not nm:
        return None, None
    a, b = source.get(POINT, nm), target.get(POINT, nm)
    if a is None and b is None:
        return None, None
    if a is None or b is None:
        raise ValueError(f"landmark attribute '{nm}' must exist on both sides (only one side has it)")
    a = np.asarray(a).ravel().astype(np.int64)
    b = np.asarray(b).ravel().astype(np.int64)
    ids = np.intersect1d(a[a >= 0], b[b >= 0])
    if len(np.unique(a[a >= 0])) != int((a >= 0).sum()) or \
            len(np.unique(b[b >= 0])) != int((b >= 0).sum()):
        raise ValueError(f"landmark attribute '{nm}' has duplicate ids (each id may mark only one point)")
    if not len(ids):
        raise ValueError("Not a single landmark id matches between the two sides")
    ia = {v: i for i, v in enumerate(a)}
    ib = {v: i for i, v in enumerate(b)}
    return (np.array([ia[v] for v in ids]), np.array([ib[v] for v in ids]))


def topo_transfer(source, target, iterations=20, smoothing=10, stiffness=0.5,
                  landmark_attribute="landmark", prealign=True):
    """Returns (fitted source, report)."""
    from .spatial import tri_soup, closest_surface
    from .topology import point_neighbours
    X = np.asarray(source.get(POINT, "P"), np.float64).copy()
    T, _, _ = tri_soup(target)
    if not len(T):
        raise ValueError("target has no faces")
    Pt = np.asarray(target.get(POINT, "P"), np.float64)
    ls, lt = _landmark_pairs(source, target, landmark_attribute)
    if prealign:
        if ls is not None and len(ls) >= 3:
            M, t, _ = umeyama(X[ls], Pt[lt], None, "similarity")
        else:
            used = np.unique(T)
            lo_s, hi_s = X.min(0), X.max(0)
            lo_t, hi_t = Pt[used].min(0), Pt[used].max(0)
            s = np.linalg.norm(hi_t - lo_t) / max(np.linalg.norm(hi_s - lo_s), 1e-12)
            M = np.eye(3) * s
            t = 0.5 * (lo_t + hi_t) - M @ (0.5 * (lo_s + hi_s))
        X = X @ M.T + t
    off, nb = point_neighbours(source)
    cnt = np.maximum(np.diff(off), 1)
    src_i = np.repeat(np.arange(source.npoints), np.diff(off))
    its = max(1, int(iterations))
    for it in range(its):
        _, _, proj, _ = closest_surface(X, Pt, T)
        D = proj - X
        # Smooth the displacement field; strength decreases linearly from smoothing to 0 (last round is pure projection)
        k = int(round(float(smoothing) * (1 - it / max(its - 1, 1))))
        for _ in range(k):
            acc = np.zeros_like(D)
            np.add.at(acc, src_i, D[nb])
            D = D + float(stiffness) * (acc / cnt[:, None] - D)
        X = X + D
        if ls is not None:
            X[ls] = Pt[lt]
    _, dist, _, _ = closest_surface(X, Pt, T)
    g = source.copy()
    g.set(POINT, "P", X.astype(np.float32), owned=True)
    return g, {"iterations": its, "max_distance": float(dist.max()),
               "mean_distance": float(dist.mean()),
               "landmarks": 0 if ls is None else int(len(ls))}
