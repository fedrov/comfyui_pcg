"""
Four deformers that "drive this geometry with another one": Lattice, Point Deform, Blend Shapes,
Transform Pieces.

━━ Lattice (FFD, free-form deformation)
First, Lattice From Bound lays a lattice of (nx+1)(ny+1)(nz+1) control points over the geometry's bounding box,
point number = i + (nx+1)*(j + (ny+1)*k). Each point carries a `rest` attribute (= its original position), and the lattice
carries a detail attribute `lattice_div`. Then move the lattice points with any node you like (Transform,
Soft Transform, Attribute Noise, Wrangle...), and connect the result to Lattice's lattice input:
the geometry deforms with the lattice. The rest positions are read from the lattice's own `rest` attribute, so no third input is needed
(rest_lattice can still be connected if you really want to give it separately).

Two interpolations:
  trilinear  each point only looks at the 8 control points of its cell. Local, C0 continuous across cells (creases on
             cell edges, less visible with more divisions)
  bezier     Sederberg-Parry 1986's original FFD: the whole lattice is one Bernstein polynomial volume of degree (nx,ny,nz).
             Smooth everywhere, but **global** -- moving one control point moves the whole block;
             with many divisions (> 6) the degree is high and control weakens. Suited to "large form" adjustments with 2~4 cells
Both have **linear precision**: when the lattice as a whole undergoes an affine transform, the geometry undergoes exactly the same affine transform
(verified in the tests, error on the order of 1e-15). This is the prerequisite for FFD being usable -- moving nothing must leave things unchanged.

Points outside the lattice: with outside = deform they are extrapolated by the formula as well (trilinear uses the linear extension of the nearest cell,
continuous); with keep they stay as they are (there will be a step at the lattice boundary, unless the boundary control points didn't move).
Direction attributes like N / up are fixed by the inverse transpose of the deformation's Jacobian (the same code as Twist / Bend).

━━ Point Deform
The high-res mesh follows a low-res point cloud: rest (the low-res mesh's original points) and deformed (the low-res points after deformation, same point count and
order). Each high-res point finds its k nearest points in rest and weights them with a smooth kernel:

    w = (1 - (d / h)^2)^2,  h = distance of the (k+1)-th nearest

h is the "(k+1)-th nearest" for **continuity**: at the moment a moving high-res point's neighbour set swaps a member, the k-th nearest
and the (k+1)-th nearest are equally far, so the weight of the one swapped out is exactly 0 -- no jump.

rigid mode (default): each low-res point first fits a local rigid transform from its own k neighbours (Kabsch:
optimal rotation + translation from the rest neighbourhood -> the deformed neighbourhood), and high-res points blend these local rigid transforms by weight.
So when the low-res mesh rotates as a whole, the high-res mesh rotates **exactly** with it (not just translates). translate mode only blends
the displacement d - r: cheap, but once the low-res mesh rotates the high-res mesh gets stretched / squashed (a negative control in the tests).
In rigid mode normals are rotated by the blended rotation.

Nearest neighbours are found by brute force in chunks (<= 4M distances per chunk): the low-res mesh usually has a few hundred to a few thousand points, which is enough;
with tens of thousands of low-res points and hundreds of thousands of high-res points it gets slow.

━━ Blend Shapes
Blends attributes of several geometries with the same topology by weight (default P; N is renormalized after blending).
  additive    base + sum w_i (target_i - base)   -- the standard approach for facial blending; weights may exceed 0~1
  sequential  one Blend value walks through a series of shapes: 0 = base, 1 = target1, 1.5 = halfway between target1 and 2
Point correspondence: point number, or the id attribute (selectable when both sides have id; matches even if the point order is shuffled).

━━ Transform Pieces
Splits geometry into pieces by name; each piece finds the template point of the same name and is transformed with that template point's instance attributes (P / orient / N+up /
scale / pscale / pivot / transform, the same set as Copy to Points).
  - with rest connected (same-named "initial" template points): piece = X_template . X_rest^-1 -- points and bones exported from RBD
    simulations are this kind of "relative to the initial state" transform. When rest and template are the same, nothing moves
  - without rest: the piece is first moved to its own centre (bounding box centre), then placed on the template point
    the way Copy to Points does
Pieces without a same-named template point stay as they are and are listed in the report. When pieces share points (not disconnected fragments),
pieces processed later override those processed earlier.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, VERTEX, DETAIL, is_string
from .groups import resolve
from . import deform as _df
from . import xform as _xf

LATTICE_INTERP = ("trilinear", "bezier")
OUTSIDE = ("deform", "keep")
PD_MODES = ("rigid", "translate")
BLEND_MODES = ("additive", "sequential")
BLEND_MATCH = ("point_number", "id")


# ═══════════════════════════════════════════════════════════ Lattice
def lattice_from_bound(geo, divisions=(2, 2, 2), padding=0.0):
    """Lays a control lattice over geo's bounding box (each side padded outward by padding)."""
    nx, ny, nz = (max(1, int(d)) for d in divisions)
    if geo is None or geo.npoints == 0:
        lo, hi = np.full(3, -0.5), np.full(3, 0.5)
    else:
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        lo, hi = P.min(0), P.max(0)
    pad = float(padding)
    lo, hi = lo - pad, hi + pad
    flat = hi - lo < 1e-9                        # flat directions are opened up a little, otherwise division by zero
    lo[flat] -= 0.5
    hi[flat] += 0.5
    xs = np.linspace(lo[0], hi[0], nx + 1)
    ys = np.linspace(lo[1], hi[1], ny + 1)
    zs = np.linspace(lo[2], hi[2], nz + 1)
    Z, Y, X = np.meshgrid(zs, ys, xs, indexing="ij")
    P = np.c_[X.ravel(), Y.ravel(), Z.ravel()]
    idx = lambda i, j, k: i + (nx + 1) * (j + (ny + 1) * k)   # noqa: E731
    lines = []
    for k in range(nz + 1):
        for j in range(ny + 1):
            lines.append([idx(i, j, k) for i in range(nx + 1)])
    for k in range(nz + 1):
        for i in range(nx + 1):
            lines.append([idx(i, j, k) for j in range(ny + 1)])
    for j in range(ny + 1):
        for i in range(nx + 1):
            lines.append([idx(i, j, k) for k in range(nz + 1)])
    g = Geometry.from_mesh(P, lines, closed=False)
    g.set(POINT, "rest", P.astype(np.float32))
    g.set(DETAIL, "lattice_div", np.array([[nx, ny, nz]], np.int32))
    return g


def _bernstein(n, t):
    """(m,) parameters -> (m, n+1) Bernstein basis."""
    from math import comb
    t = np.asarray(t, np.float64)[:, None]
    i = np.arange(n + 1)[None]
    c = np.array([comb(n, k) for k in range(n + 1)], np.float64)[None]
    return c * t ** i * (1 - t) ** (n - i)


def _lattice_setup(lat, rest):
    div = lat.get(DETAIL, "lattice_div")
    if div is None:
        raise ValueError("lattice has no detail attribute lattice_div -- the lattice must be built with "
                         "Lattice From Bound (move points freely afterwards, but don't delete or merge points)")
    nx, ny, nz = (int(v) for v in np.asarray(div).ravel()[:3])
    n = (nx + 1) * (ny + 1) * (nz + 1)
    D = np.asarray(lat.get(POINT, "P"), np.float64)
    if len(D) != n:
        raise ValueError(f"lattice should have {n} points ({nx}x{ny}x{nz} cells), but has "
                         f"{len(D)} -- lattice points must not be added or removed")
    if rest is not None:
        R = np.asarray(rest.get(POINT, "P"), np.float64)
        if len(R) != n:
            raise ValueError(f"rest_lattice has {len(R)} points, which doesn't match lattice's {n} "
                             f"points")
    else:
        r = lat.get(POINT, "rest")
        if r is None:
            raise ValueError("lattice has no rest attribute (deleted?); connect a "
                             "rest_lattice")
        R = np.asarray(r, np.float64)
    lo, hi = R.min(0), R.max(0)
    return (nx, ny, nz), D.reshape(nz + 1, ny + 1, nx + 1, 3), lo, hi


def _lattice_eval(Q, div, D, lo, hi, interp):
    nx, ny, nz = div
    s = (Q - lo) / (hi - lo)
    if interp == "bezier":
        Bx, By, Bz = _bernstein(nx, s[:, 0]), _bernstein(ny, s[:, 1]), \
            _bernstein(nz, s[:, 2])
        return np.einsum("mk,mj,mi,kjic->mc", Bz, By, Bx, D)
    n = np.array([nx, ny, nz], np.float64)
    u = s * n
    c = np.clip(np.floor(u), 0, n - 1).astype(np.int64)
    t = u - c                                     # outside the lattice t beyond [0,1] = linear extrapolation
    out = np.zeros_like(Q)
    for dz in (0, 1):
        wz = t[:, 2] if dz else 1 - t[:, 2]
        for dy in (0, 1):
            wy = t[:, 1] if dy else 1 - t[:, 1]
            for dx in (0, 1):
                wx = t[:, 0] if dx else 1 - t[:, 0]
                out += (wx * wy * wz)[:, None] * \
                    D[c[:, 2] + dz, c[:, 1] + dy, c[:, 0] + dx]
    return out


def lattice(geo, lat, rest=None, interpolation="trilinear", outside="deform",
            group=""):
    """FFD. Returns the deformed geometry."""
    if interpolation not in LATTICE_INTERP:
        raise ValueError(f"Interpolation must be one of {LATTICE_INTERP}")
    if outside not in OUTSIDE:
        raise ValueError(f"Outside must be one of {OUTSIDE}")
    if geo is None or geo.npoints == 0:
        return geo.copy() if geo is not None else Geometry()
    div, D, lo, hi = _lattice_setup(lat, rest)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    sel = resolve(geo, POINT, group) if str(group).strip() else \
        np.ones(geo.npoints, bool)
    if outside == "keep":
        inside = np.all((P >= lo - 1e-9) & (P <= hi + 1e-9), axis=1)
        sel = sel & inside

    def f(Q):
        return _lattice_eval(Q, div, D, lo, hi, interpolation)

    return _df._apply(geo, f, sel)


# ═══════════════════════════════════════════════════════════ Point Deform
def _knn(Q, P, k):
    """The k nearest in P for each Q: returns (indices (m,k), distances (m,k)), sorted by ascending distance."""
    m, n = len(Q), len(P)
    k = min(k, n)
    idx = np.empty((m, k), np.int64)
    dist = np.empty((m, k))
    step = max(1, int(4_000_000 // max(n, 1)))
    for s in range(0, m, step):
        q = Q[s:s + step]
        d2 = ((q[:, None, :] - P[None]) ** 2).sum(2)
        if k < n:
            part = np.argpartition(d2, k - 1, axis=1)[:, :k]
        else:
            part = np.tile(np.arange(n), (len(q), 1))
        dd = np.take_along_axis(d2, part, 1)
        o = np.argsort(dd, axis=1, kind="stable")
        idx[s:s + step] = np.take_along_axis(part, o, 1)
        dist[s:s + step] = np.sqrt(np.take_along_axis(dd, o, 1))
    return idx, dist


def _kabsch(A, B):
    """Two sets of centred points (n,k,3) -> (n,3,3) rotations R such that R*a ~ b."""
    H = np.einsum("nki,nkj->nij", A, B)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(np.einsum("nij,njk->nik", Vt.transpose(0, 2, 1),
                                        U.transpose(0, 2, 1))))
    d[d == 0] = 1
    Dm = np.tile(np.eye(3), (len(H), 1, 1))
    Dm[:, 2, 2] = d
    return np.einsum("nij,njk,nkl->nil", Vt.transpose(0, 2, 1), Dm,
                     U.transpose(0, 2, 1))


def point_deform(geo, rest, deformed, max_points=8, mode="rigid", group=""):
    """Returns (geo, report)."""
    if mode not in PD_MODES:
        raise ValueError(f"Mode must be one of {PD_MODES}")
    if rest is None or deformed is None or rest.npoints == 0:
        raise ValueError("Both rest and deformed point sets must be connected (the low-res mesh's initial and deformed states)")
    R = np.asarray(rest.get(POINT, "P"), np.float64)
    Dp = np.asarray(deformed.get(POINT, "P"), np.float64)
    if len(R) != len(Dp):
        raise ValueError(f"rest has {len(R)} points, deformed has {len(Dp)} -- "
                         f"the two must correspond one to one (the same point cloud before and after deformation)")
    g = geo.copy()
    if geo.npoints == 0:
        return g, {"points": 0}
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    sel = resolve(geo, POINT, group) if str(group).strip() else \
        np.ones(geo.npoints, bool)
    Q = P[sel]
    k = max(1, int(max_points))
    n = len(R)
    kk = min(k + 1, n)
    idx, dist = _knn(Q, R, kk)
    if kk > k:
        h = dist[:, k:k + 1]
        idx, dist = idx[:, :k], dist[:, :k]
    else:
        h = dist[:, -1:] * 1.5 + 1e-12
    h = np.maximum(h, 1e-12)
    w = np.clip(1 - (dist / h) ** 2, 0, None) ** 2
    zero = w.sum(1) <= 1e-300
    w[zero, 0] = 1.0                              # all on the kernel's edge: fall back to the nearest point
    w /= w.sum(1, keepdims=True)
    if mode == "translate":
        disp = Dp - R
        out = Q + np.einsum("mk,mkc->mc", w, disp[idx])
        rot = None
    else:
        kr = min(max(k, 4), n)
        ridx, _ = _knn(R, R, kr)
        A = R[ridx]
        B = Dp[ridx]
        ca, cb = A.mean(1), B.mean(1)
        if n >= 3:
            Rj = _kabsch(A - ca[:, None], B - cb[:, None])
        else:
            Rj = np.tile(np.eye(3), (n, 1, 1))
        # Local rigid transform of each low-res point j: x -> Rj (x - ca_j) + cb_j
        loc = np.einsum("mkij,mkj->mki", Rj[idx], Q[:, None, :] - ca[idx]) + \
            cb[idx]
        out = np.einsum("mk,mkc->mc", w, loc)
        rot = np.einsum("mk,mkij->mij", w, Rj[idx])
    Pn = P.copy()
    Pn[sel] = out
    g.set(POINT, "P", Pn.astype(np.float32), owned=True)
    if rot is not None:
        full = np.tile(np.eye(3), (geo.npoints, 1, 1))
        full[sel] = rot
        _rotate_dirs(geo, g, full)
    return g, {"points": int(sel.sum()), "rest_points": n, "k": k,
               "mode": mode}


def _rotate_dirs(src, g, M, sel=None, names=("N", "up", "v")):
    """
    N on point / vertex uses M's inverse transpose, up / v use M (nothing outside sel moves).

    names (pcg100, used by Transform Pieces' Attributes to Transform): names of 3-component attributes to transform.
    Our attributes have no Houdini type info, so they can only be split by name: one named N is treated as a normal (inverse transpose + normalize),
    everything else as a vector (multiplied by M only, no translation).
    """
    NM = _xf.normal_matrices(M)
    vp = src.vertex_point.astype(np.int64)
    for cls, ix in ((POINT, None), (VERTEX, vp)):
        for name, mats in ((n, NM if n == "N" else M) for n in names):
            a = src.get(cls, name)
            if a is None or a.shape[1] != 3:
                continue
            m = mats if ix is None else mats[ix]
            v = np.asarray(a, np.float64)
            r = np.einsum("nij,nj->ni", m, v)
            if name == "N":
                ln = np.linalg.norm(r, axis=1, keepdims=True)
                r = np.where(ln > 1e-20, r / np.maximum(ln, 1e-20), v)
            if sel is not None:
                s = sel if ix is None else sel[ix]
                r = np.where(s[:, None], r, v)
            g.set(cls, name, r.astype(a.dtype), owned=True)


def _copy_template(template, g, tsrc, moved, attrib_pat, group_pat):
    """
    Copy Template Attributes: matching attributes / point groups on the template point are copied onto every point of the matched piece.
    When the geometry already has a same-named attribute (same component count and type), unmatched points keep their original values, otherwise get 0 / empty string;
    P is not copied (copying it would collapse every point onto the template point).
    """
    from .ops import match_names
    if str(attrib_pat).strip():
        for k in match_names([k for k in template.attribs[POINT] if k != "P"], attrib_pat):
            tv = np.asarray(template.get(POINT, k))
            cur = g.get(POINT, k)
            if cur is not None and cur.shape[1] == tv.shape[1] and \
                    (cur.dtype.kind == "U") == (tv.dtype.kind == "U"):
                full = np.array(cur).astype(np.result_type(cur.dtype, tv.dtype))
            else:
                full = np.zeros((g.npoints, tv.shape[1]), tv.dtype) if tv.dtype.kind != "U" \
                    else np.full((g.npoints, tv.shape[1]), "", tv.dtype)
            full[moved] = tv[tsrc[moved]]
            g.set(POINT, k, full, owned=True)
    if str(group_pat).strip():
        for k in match_names(list(template.groups[POINT]), group_pat):
            tm = np.asarray(template.get_group(POINT, k), bool)
            cur = g.get_group(POINT, k)
            full = np.array(cur, bool) if cur is not None else np.zeros(g.npoints, bool)
            full[moved] = tm[tsrc[moved]]
            g.set_group(POINT, k, full)


# ═══════════════════════════════════════════════════════════ Blend Shapes
def _match(base, tgt, how, k):
    if tgt.npoints != base.npoints:
        raise ValueError(f"target{k} has {tgt.npoints} points, base has {base.npoints}"
                         f" -- Blend Shapes needs the same topology")
    if how == "point_number":
        return np.arange(base.npoints)
    ib, it = base.get(POINT, "id"), tgt.get(POINT, "id")
    if ib is None or it is None:
        raise ValueError(f"Matching by id: base and target{k} both need a point attribute id")
    ib, it = np.asarray(ib).ravel(), np.asarray(it).ravel()
    o = np.argsort(it, kind="stable")
    pos = np.searchsorted(it[o], ib)
    pos = np.clip(pos, 0, len(it) - 1)
    m = o[pos]
    if not np.array_equal(it[m], ib):
        raise ValueError(f"The ids of target{k} don't match base's (some ids not found)")
    return m


def blend_shapes(base, targets, weights=(), mode="additive", blend=0.0,
                 attributes="P N", match="point_number"):
    """
    Returns (geo, report). targets are given by **slot** (the k-th = targetk), unconnected ones are None;
    weights are also by slot, corresponding one to one with targets.

    sequential's Blend counts by slot number: Blend = 2 is target2, whether or not target1 is connected.
    An empty slot in between = holds the previous shape (with target2 unconnected, the 1 -> 2 stretch doesn't move, and 2 -> 3 then
    goes from target1 to target3). Before pcg90 unconnected ones were removed before counting, so with target2 empty
    Blend = 2 landed on target3, which didn't match the numbering in the panel.
    """
    if mode not in BLEND_MODES:
        raise ValueError(f"Mode must be one of {BLEND_MODES}")
    if match not in BLEND_MATCH:
        raise ValueError(f"Match must be one of {BLEND_MATCH}")
    T = [(k + 1, t) for k, t in enumerate(targets) if t is not None]
    if not T:
        raise ValueError("Connect at least one target")
    maps = [_match(base, t, match, k) for k, t in T]
    names = [a for a in str(attributes).split() if a]
    out = base.copy()
    done = []
    wl = list(weights)
    w = [float(wl[k - 1]) if k - 1 < len(wl) else 0.0 for k, _ in T]
    for nm in names:
        b = base.get(POINT, nm)
        if b is None or is_string(b):
            continue
        tv = []
        for (k, t), m in zip(T, maps):
            a = t.get(POINT, nm)
            if a is None or a.shape[1] != b.shape[1]:
                raise ValueError(f"target{k} has no attribute '{nm}' with the same dimension as base")
            tv.append(np.asarray(a, np.float64)[m])
        bb = np.asarray(b, np.float64)
        if mode == "additive":
            r = bb.copy()
            for wi, a in zip(w, tv):
                r += float(wi) * (a - bb)
        else:
            # Slot 0 = base, slot k = targetk; empty slots keep the previous shape
            by_slot = dict(zip((k for k, _ in T), tv))
            top = T[-1][0]
            chain = [bb]
            for k in range(1, top + 1):
                chain.append(by_slot.get(k, chain[-1]))
            x = float(np.clip(blend, 0.0, top))
            i = min(int(np.floor(x)), top - 1)
            f = x - i
            r = (1 - f) * chain[i] + f * chain[i + 1]
        if nm == "N" and r.shape[1] == 3:
            ln = np.linalg.norm(r, axis=1, keepdims=True)
            r = np.where(ln > 1e-20, r / np.maximum(ln, 1e-20), bb)
        out.set(POINT, nm, r.astype(b.dtype), owned=True)
        done.append(nm)
    return out, {"targets": len(T), "attributes": done, "mode": mode}


# ═══════════════════════════════════════════════════════════ Transform Pieces
def _xforms(pts):
    M, T, pv = _xf.point_matrices(pts)
    return M, T, pv


PIECE_MODES = ("match", "index")


def transform_pieces(geo, template, rest=None, piece_attribute="name",
                     attribute_mode="match", invert=False, center_pieces=True,
                     transform_attribs="N up v", copy_attribs="", copy_groups=""):
    """
    Returns (geo, report).

    attribute_mode (Houdini's Attribute Mode):
        match  old behaviour = Match by Attribute: a piece is paired when its attribute value equals the value of the **same-named attribute** on the template point
        index  Index by Attribute: the piece's integer attribute value is the template point number (same number for rest); out-of-range pieces don't move
    center_pieces (this plugin's extension, old behaviour True): without rest, first moves the piece's bounding box centre to the origin, then applies the template
        transform. Off = Houdini: pieces directly get the template point's instance transform p' = M(p - pivot) + T.
    invert (Invert Transformation): uses the inverse transform -- two nodes differing only in this item, chained, cancel each other.
        The inverse transform doesn't "move to the centre" (that step itself is not invertible), so with invert center_pieces has no effect.
    transform_attribs (Attributes to Transform): name pattern of the point / vertex 3-component attributes to rotate along,
        default "N up v" = old behaviour. P is always transformed.
    copy_attribs / copy_groups (Copy Template Attributes / Attributes to Copy / Groups to Copy):
        attributes / point groups on the template point are copied onto the points of the matched piece (P is not copied).
    """
    if attribute_mode not in PIECE_MODES:
        raise ValueError(f"Attribute Mode must be one of {PIECE_MODES}")
    nm = str(piece_attribute).strip() or "name"
    a = geo.get(PRIM, nm)
    cls = PRIM
    if a is None:
        a = geo.get(POINT, nm)
        cls = POINT
    if a is None:
        raise KeyError(f"The geometry has no prim / point attribute '{nm}' -- name the fragments first with Connectivity"
                       f" / Name")
    key = a[:, 0]
    Mt, Tt, pvt = _xforms(template)
    rmap = None
    if attribute_mode == "match":
        ta = template.get(POINT, nm)
        if ta is None:
            raise KeyError(f"The template points have no point attribute '{nm}'")
        tmap = {v: i for i, v in enumerate(ta[:, 0].tolist())}
        if rest is not None:
            ra = rest.get(POINT, nm)
            if ra is None:
                raise KeyError(f"The rest points have no point attribute '{nm}'")
            rmap = {v: i for i, v in enumerate(ra[:, 0].tolist())}
    else:
        if is_string(a):
            raise TypeError(f"Index by Attribute needs an integer attribute; '{nm}' is a string")
        tmap = {i: i for i in range(template.npoints)}
        if rest is not None:
            rmap = {i: i for i in range(rest.npoints)}
        key = np.rint(np.asarray(key, np.float64)).astype(np.int64)
    if rest is not None:
        Mr, Tr, pvr = _xforms(rest)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    out = P.copy()
    Mall = np.tile(np.eye(3), (geo.npoints, 1, 1))
    moved = np.zeros(geo.npoints, bool)
    tsrc = np.full(geo.npoints, -1, np.int64)              # template point number matched to each point
    if cls == PRIM:
        vp = geo.vertex_point.astype(np.int64)
        vprim = geo.vertex_prim()
        pt_key_prim = vprim
    uniq = np.unique(key)
    unmatched = []
    for u in uniq.tolist():
        if cls == PRIM:
            prims = np.nonzero(key == u)[0]
            pts = np.unique(vp[np.isin(pt_key_prim, prims)])
        else:
            pts = np.nonzero(key == u)[0]
        if not len(pts):
            continue
        ti = tmap.get(u)
        if ti is None or (rmap is not None and u not in rmap):
            unmatched.append(str(u))
            continue
        p = P[pts]
        if invert:
            Mti = np.linalg.inv(Mt[ti])
            q = (p - Tt[ti]) @ Mti.T + pvt[ti]
            if rmap is not None:
                ri = rmap[u]
                out[pts] = (q - pvr[ri]) @ Mr[ri].T + Tr[ri]
                A = Mr[ri] @ Mti
            else:
                out[pts] = q
                A = Mti
        elif rmap is not None:
            ri = rmap[u]
            Minv = np.linalg.inv(Mr[ri])
            local = (p - Tr[ri]) @ Minv.T + pvr[ri]
            A = Mt[ti] @ Minv
            out[pts] = (local - pvt[ti]) @ Mt[ti].T + Tt[ti]
        else:
            if center_pieces:
                lo, hi = p.min(0), p.max(0)
                local = p - 0.5 * (lo + hi)
            else:
                local = p
            A = Mt[ti]
            out[pts] = (local - pvt[ti]) @ Mt[ti].T + Tt[ti]
        Mall[pts] = A
        moved[pts] = True
        tsrc[pts] = ti
    g = geo.copy()
    g.set(POINT, "P", out.astype(np.float32), owned=True)
    # The default "N up v" selects exactly the three handled by the old _rotate_dirs (processing order doesn't affect the result)
    from .ops import match_names
    cand = sorted({k for c in (POINT, VERTEX) for k, v in geo.attribs[c].items()
                   if k != "P" and getattr(v, "ndim", 0) == 2 and v.shape[1] == 3
                   and not is_string(v)})
    _rotate_dirs(geo, g, Mall, moved, tuple(match_names(cand, transform_attribs)))
    _copy_template(template, g, tsrc, moved, copy_attribs, copy_groups)
    return g, {"pieces": int(len(uniq)), "moved_points": int(moved.sum()),
               "unmatched": unmatched[:50], "unmatched_count": len(unmatched),
               "relative_to_rest": rest is not None, "piece_class": cls}
