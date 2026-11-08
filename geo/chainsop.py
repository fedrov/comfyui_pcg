"""
pcg100: Chain with Houdini semantics (Mode = Deform Along Curve). The old copyxform.chain (rigid links placed on chords) is left as is.

━━ How it differs from the old mode
Houdini's Chain is "a Path Deform repeated by pattern": the source geometry is split into pieces, laid out in a chain by pattern
(cycle / specified / random / weighted random), and the chain runs link after link along the Forward axis in **the chain's own coordinates**
(each link's length = its bounding box length along Forward * Uniform Piece Scale, plus Piece Spacing between links); then the whole chain
is mapped onto the curve: chain coordinate t in [0, G] (G = natural length of the chain) -> curve arc length
s = Offset + t * (Map Length / G), and every point is placed by its (side, up) offset in the curve's frame at s
-- so every link **bends with the curve** (the old mode keeps each link rigid and only places it on the chord).

━━ Frames
The curve tangent is the average tangent at each vertex, linearly interpolated within a segment and normalized (continuous within segments,
no tearing at kinks); up is the start up given by Curve Up Control, carried along the curve by RMF and likewise interpolated within segments.
Local axes of the chain: Forward direction f, Up direction u (orthogonalized against f first),
side = u x f -- the same [X, Y, Z] = [up x tangent, up, tangent] convention as every frame in the plugin.

━━ Beyond the ends of the curve (Start / End Behavior)
  extend  extend along the end tangent (an invisible straight line)
  clamp   stop at the end point (geometry piles up)
  clip    cut the geometry in chain coordinates at the planes corresponding to s = 0 / s = L (clip.clip_plane), then deform
Closed curves have no ends: s wraps around modulo the perimeter.
"""
from __future__ import annotations

import math

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .groups import resolve
from . import curveframe as _cf

CHAIN_MODES = ("rigid_links", "deform_along_curve")
FIND_PIECES = ("connectivity", "piece_attribute")
NUM_PIECES = ("fit", "explicit")
MAP_LENGTH = ("fraction_curve", "fraction_geo", "distance")
OFFSET_USING = ("curve_u", "fraction_geo", "distance")
END_BEHAVIOR = ("extend", "clamp", "clip")
REPEAT_PATTERN = ("cycle", "explicit", "random", "weighted_random", "weighted_random_attrib")
AXIS_DIRS = ("x", "y", "z", "custom")
CURVE_UP = ("curve_normal", "x", "y", "z", "custom")
_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _pieces(src, how, attr):
    """Source pieces: [(key, sub-geometry)], in order of first occurrence."""
    from .ops import delete_prims, delete_points
    from .topology import connectivity
    if how == "piece_attribute" and str(attr).strip():
        from . import copyto as _cp
        cls, key = _cp._source_piece_keys(src, str(attr).strip())
        if key is None:
            raise KeyError(f"Source geometry has no piece attribute '{attr}'")
    else:
        cls = PRIM if src.nprims else POINT
        lab = np.asarray(connectivity(src, cls, "__chain_cc").get(cls, "__chain_cc"))[:, 0]
        key = lab
    out = []
    for v in list(dict.fromkeys(np.asarray(key).tolist())):
        m = np.asarray(key) == v
        sub = delete_prims(src, m) if cls == PRIM else delete_points(src, m)
        out.append((v, sub))
    return out


def _sampler(P, closed, up):
    """Curve arc length s -> (position, tangent T, up U); interpolated within segments and normalized."""
    T, U, _ = _cf.curve_frames(P, closed, up=up)
    Q = np.vstack([P, P[:1]]) if closed else P
    Tq = np.vstack([T, T[:1]]) if closed else T
    Uq = np.vstack([U, U[:1]]) if closed else U
    seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    sc = np.concatenate([[0.0], np.cumsum(seg)])
    L = float(sc[-1])

    def at(s):
        s = np.asarray(s, np.float64)
        k = np.clip(np.searchsorted(sc, s, side="right") - 1, 0, len(seg) - 1)
        w = np.where(seg[k] > 0, (s - sc[k]) / np.where(seg[k] > 0, seg[k], 1.0), 0.0)
        pos = Q[k] + (Q[k + 1] - Q[k]) * w[:, None]
        t = _cf._unit(Tq[k] * (1 - w[:, None]) + Tq[k + 1] * w[:, None])
        u = Uq[k] * (1 - w[:, None]) + Uq[k + 1] * w[:, None]
        u = _cf._unit(u - t * np.einsum("ij,ij->i", u, t)[:, None])
        return pos, t, u
    return at, L


def _curve_up(P, kind, custom):
    if kind in _AXES:
        return np.array(_AXES[kind])
    if kind == "custom":
        return np.asarray(custom, np.float64).reshape(3)
    n = np.cross(P, np.roll(P, -1, axis=0)).sum(0)             # curve_normal: Newell; straight lines fall back to Y
    ln = float(np.linalg.norm(n))
    diag = float(np.linalg.norm(np.ptp(P, axis=0)))
    return n / ln if ln > 1e-5 * max(diag, float(np.abs(P).max())) * diag else np.array([0.0, 1.0, 0.0])


def _sequence(npieces, mode, k_count, offset, pattern, rng, repeat_len, weights, choices):
    """Pattern: the first k_count piece indices. choices = piece indices allowed in the pattern (end pieces excluded)."""
    ch = list(choices)
    if not ch:
        return []
    if mode == "cycle":
        return [ch[(i + offset) % len(ch)] for i in range(k_count)]
    if mode == "explicit":
        pat = [int(x) for x in str(pattern).split() if x.strip().lstrip("-").isdigit()]
        pat = [p % npieces for p in pat] or ch
        return [pat[(i + offset) % len(pat)] for i in range(k_count)]
    w = np.ones(len(ch)) if mode == "random" else np.maximum(np.asarray([weights[c] for c in ch], np.float64), 0)
    if w.sum() <= 0:
        w = np.ones(len(ch))
    period = int(repeat_len) if int(repeat_len) > 0 else k_count + abs(int(offset))
    base = rng.choice(len(ch), size=max(period, 1), p=w / w.sum())
    return [ch[int(base[(i + offset) % len(base)])] for i in range(k_count)]


def chain_deform(source, curves, group="", geometry_group="", find_pieces="connectivity",
                 piece_attribute="", enable_deformation=True, number_of_pieces="fit",
                 fraction_of_curve=1.0, only_full_pattern=False, num_pieces=10, piece_scale=1.0,
                 map_length_using="fraction_curve", map_length=1.0, map_length_attrib="",
                 offset_using="curve_u", offset=0.0, offset_attrib="",
                 start_behavior="extend", end_behavior="extend", repeat_pattern="cycle",
                 class_pattern="", pattern_offset=0, seed=0, repeat_length=0, piece_weights="",
                 weight_attrib="weight", use_start_cap=False, start_cap=0, use_end_cap=False, end_cap=0,
                 exclude_end_pieces=True, rigid_end_pieces=False, enable_scale=False, base_scale=1.0,
                 scale_attrib="", enable_rotation=False, base_rotation=0.0, rotation_attrib="",
                 forward_dir="z", forward_vec=(0, 0, 1), up_dir="y", up_vec=(0, 1, 0),
                 center_on_curve=False, spacing=0.0, piece_rotation=0.0, curve_up="curve_normal",
                 curve_up_vec=(0, 1, 0), attribs_to_transform="N", pos_attrib="", index_attrib="",
                 curvenum_attrib="", copy_attribute="copynum"):
    """See the file header. Returns (geometry, report)."""
    from .ops import merge, delete_prims, match_names
    from .clip import clip_plane
    for v, ok, nm in ((find_pieces, FIND_PIECES, "Find Pieces"), (number_of_pieces, NUM_PIECES, "Number of Pieces"),
                      (map_length_using, MAP_LENGTH, "Map Length Using"), (offset_using, OFFSET_USING, "Offset Using"),
                      (start_behavior, END_BEHAVIOR, "Start Behavior"), (end_behavior, END_BEHAVIOR, "End Behavior"),
                      (repeat_pattern, REPEAT_PATTERN, "Repeat Pattern"), (forward_dir, AXIS_DIRS, "Forward"),
                      (up_dir, AXIS_DIRS, "Up"), (curve_up, CURVE_UP, "Curve Up Control")):
        if v not in ok:
            raise ValueError(f"{nm} must be one of {ok}")
    if source is None or curves is None or source.npoints == 0:
        return Geometry(), {"pieces": 0}
    src = source
    if str(geometry_group).strip():
        src = delete_prims(source, resolve(source, PRIM, geometry_group)) if source.nprims else source
    # Local axes of the chain
    f = _cf._unit(np.asarray(_AXES.get(forward_dir, forward_vec), np.float64).reshape(3))
    u0 = np.asarray(_AXES.get(up_dir, up_vec), np.float64).reshape(3)
    u = u0 - f * float(u0 @ f)
    if float(np.linalg.norm(u)) < 1e-9:
        u = _cf._any_perp(f)
    u = _cf._unit(u)
    x = np.cross(u, f)
    ps = float(piece_scale)
    table = []                                             # [(key, sub-geometry, local coords (n,3), [cmin, cmax])]
    for key, sub in _pieces(src, find_pieces, piece_attribute):
        Pl = np.asarray(sub.get(POINT, "P"), np.float64)
        L3 = np.stack([Pl @ x, Pl @ u, Pl @ f], 1) * ps
        if center_on_curve:
            L3[:, :2] -= 0.5 * (L3[:, :2].min(0) + L3[:, :2].max(0))
        table.append((key, sub, L3, (float(L3[:, 2].min()), float(L3[:, 2].max()))))
    npc = len(table)
    lens = np.array([max(t[3][1] - t[3][0], 1e-9) for t in table])
    # Weights for weighted random: a string (in piece order) or a prim attribute (averaged per piece)
    weights = np.ones(npc)
    if repeat_pattern == "weighted_random":
        ws = [float(w) for w in str(piece_weights).split()]
        for i in range(min(npc, len(ws))):
            weights[i] = ws[i]
    elif repeat_pattern == "weighted_random_attrib":
        for i, (_, sub, _, _) in enumerate(table):
            a = sub.get(PRIM, str(weight_attrib).strip()) if str(weight_attrib).strip() else None
            weights[i] = float(np.asarray(a, np.float64).mean()) if a is not None and not is_string(a) and len(a) else 1.0
    caps = ({int(start_cap) % npc} if use_start_cap else set()) | ({int(end_cap) % npc} if use_end_cap else set())
    choices = [i for i in range(npc) if not (exclude_end_pieces and i in caps)] or list(range(npc))
    sp = float(spacing)
    Pall = np.asarray(curves.get(POINT, "P"), np.float64)
    aname = match_names([k for k in src.attribs[POINT] if k != "P"], attribs_to_transform)
    parts, n_out = [], 0
    for ci, (pi, pts, closed) in enumerate(_cf.curve_prims(curves, group)):
        P = Pall[pts]
        at, L = _sampler(P, closed, _curve_up(P, curve_up, curve_up_vec))
        rng = np.random.default_rng([int(seed) & 0xFFFFFFFF, int(pi)])
        # -- which pieces to lay out
        head = [int(start_cap) % npc] if use_start_cap else []
        tail = [int(end_cap) % npc] if use_end_cap else []
        if number_of_pieces == "explicit":
            nmid = max(0, int(num_pieces) - len(head) - len(tail))
            seq = head + _sequence(npc, repeat_pattern, nmid, int(pattern_offset), class_pattern, rng,
                                   repeat_length, weights, choices) + tail
        else:
            budget = float(fraction_of_curve) * L
            cand = _sequence(npc, repeat_pattern, 100000 if L > 0 else 0, int(pattern_offset), class_pattern, rng,
                             repeat_length, weights, choices) if budget > 0 else []
            used = sum(lens[h] for h in head) + sum(lens[t] for t in tail) + sp * (len(head) + len(tail) - 1)
            mid = []
            tol = 1e-6 * max(budget, 1.0)                   # piece lengths come from float32 points; an exact fit can overshoot by ~1e-7
            for c in cand:
                need = lens[c] + sp
                if used + need > budget + tol:
                    break
                mid.append(c)
                used += need
            if only_full_pattern:
                per = (len([t for t in str(class_pattern).split() if t.strip().lstrip("-").isdigit()]) or len(choices)) \
                    if repeat_pattern in ("cycle", "explicit") else int(repeat_length)
                if per > 0:
                    mid = mid[:len(mid) - len(mid) % per]
            seq = head + mid + tail if (mid or head or tail) else []
            if used > budget + tol and not mid:
                seq = []                                    # not even the end pieces fit
        if not seq:
            continue
        starts = np.concatenate([[0.0], np.cumsum(lens[seq] + sp)[:-1]])
        G = float(starts[-1] + lens[seq[-1]])
        # -- map onto the curve: s = s0 + t * (Lmap / G)
        mlen = float(map_length)
        if str(map_length_attrib).strip():
            a = curves.get(PRIM, str(map_length_attrib).strip())
            if a is not None and not is_string(a):
                mlen = float(np.asarray(a)[pi, 0])
        Lmap = {"fraction_curve": mlen * L, "fraction_geo": mlen * G, "distance": mlen}[map_length_using]
        off = float(offset)
        if str(offset_attrib).strip():
            a = curves.get(PRIM, str(offset_attrib).strip())
            if a is not None and not is_string(a):
                off = float(np.asarray(a)[pi, 0])
        s0 = {"curve_u": off * L, "fraction_geo": off * G, "distance": off}[offset_using]
        ratio = Lmap / G if G > 0 else 1.0
        for k, w in enumerate(seq):
            _, sub, L3, (cmin, _) = table[w]
            g = sub.copy()
            loc = L3.copy()
            ang = math.radians(float(piece_rotation)) * k
            if ang:
                c_, s_ = math.cos(ang), math.sin(ang)
                loc[:, 0], loc[:, 1] = c_ * L3[:, 0] - s_ * L3[:, 1], s_ * L3[:, 0] + c_ * L3[:, 1]
            t_ = starts[k] + (loc[:, 2] - cmin)
            s = s0 + t_ * ratio
            if not enable_deformation:
                # No deformation: lay out in a straight line along world Z (then follow with Path Deform or similar). z = curve arc length coordinate
                g.set(POINT, "P", np.stack([loc[:, 0], loc[:, 1], s], 1).astype(np.float32), owned=True)
                _write_out(g, s, L, k, pi, pos_attrib, index_attrib, curvenum_attrib, copy_attribute)
                parts.append(g)
                continue
            if not closed:
                cut = []
                # Only clip when actually out of range (clipping doesn't affect in-range links; this just saves a clip_plane -- the docs also say Clip is expensive)
                if start_behavior == "clip" and s.min() < 0:
                    cut.append((-1.0, (0.0 - s0) / ratio - starts[k] + cmin))
                if end_behavior == "clip" and s.max() > L:
                    cut.append((1.0, (L - s0) / ratio - starts[k] + cmin))
                if cut:
                    gl = g.copy()
                    gl.set(POINT, "P", loc.astype(np.float32), owned=True)
                    for sgn, c0 in cut:
                        gl, _ = clip_plane(gl, (0.0, 0.0, sgn), (0.0, 0.0, c0), keep="below")
                    loc = np.asarray(gl.get(POINT, "P"), np.float64)
                    # New points from the cut: carry the attributes in the original frame along (clip_plane already interpolated them), move positions back to world space, then deform
                    g = gl
                    t_ = starts[k] + (loc[:, 2] - cmin)
                    s = s0 + t_ * ratio
            if closed and L > 0:
                s = np.mod(s, L)
            ra = None
            if rigid_end_pieces and ((use_start_cap and k == 0) or (use_end_cap and k == len(seq) - 1)):
                smid = s0 + (starts[k] + 0.5 * lens[w]) * ratio
                sm = np.full(len(s), smid)
                pos, T, U = _eval(at, L, closed, sm, start_behavior, end_behavior)
                X = np.cross(U, T)
                d = (loc[:, 2] - (cmin + 0.5 * lens[w])) * ratio
                newP = pos + loc[:, :1] * X + loc[:, 1:2] * U + d[:, None] * T
            else:
                pos, T, U = _eval(at, L, closed, s, start_behavior, end_behavior)
                X = np.cross(U, T)
                a_, b_ = loc[:, 0].copy(), loc[:, 1].copy()
                if enable_scale:
                    sc = float(base_scale) * _curve_attr(curves, scale_attrib, pts, at, L, s, closed)
                    a_, b_ = a_ * sc, b_ * sc
                if enable_rotation:
                    ra = np.radians(float(base_rotation) * _curve_attr(curves, rotation_attrib, pts, at, L, s, closed))
                    a_, b_ = np.cos(ra) * a_ - np.sin(ra) * b_, np.sin(ra) * a_ + np.cos(ra) * b_
                newP = pos + a_[:, None] * X + b_[:, None] * U
            g.set(POINT, "P", newP.astype(np.float32), owned=True)
            # Attributes to Transform: three-component vectors are decomposed along the local axes and moved into the curve frame (piece rotation included)
            for nm in aname:
                v = g.get(POINT, nm)
                if v is None or is_string(v) or v.shape[1] != 3:
                    continue
                v = np.asarray(v, np.float64)
                va, vb, vc = v @ x, v @ u, v @ f
                if ang:
                    va, vb = math.cos(ang) * va - math.sin(ang) * vb, math.sin(ang) * va + math.cos(ang) * vb
                if ra is not None:
                    va, vb = np.cos(ra) * va - np.sin(ra) * vb, np.sin(ra) * va + np.cos(ra) * vb
                w3 = va[:, None] * X + vb[:, None] * U + vc[:, None] * T
                g.set(POINT, nm, w3.astype(np.float32), owned=True)
            _write_out(g, s, L, k, pi, pos_attrib, index_attrib, curvenum_attrib, copy_attribute)
            parts.append(g)
        n_out += len(seq)
    return (merge(*parts) if parts else Geometry()), {"pieces": n_out}


def _eval(at, L, closed, s, start_behavior, end_behavior):
    """(position, tangent, up) at arc length s, handling out-of-range values per the end behaviors."""
    if closed:
        return at(s)
    ss = np.clip(s, 0.0, L)
    pos, T, U = at(ss)
    if start_behavior == "extend":
        m = s < 0
        pos[m] = pos[m] + T[m] * s[m][:, None]
    if end_behavior == "extend":
        m = s > L
        pos[m] = pos[m] + T[m] * (s[m] - L)[:, None]
    return pos, T, U


def _curve_attr(curves, name, pts, at, L, s, closed):
    """Value of a numeric attribute on the curve points at arc length s (linear in arc length); empty name / missing attribute = 1."""
    name = str(name).strip()
    v = curves.get(POINT, name) if name else None
    if v is None or is_string(v):
        return np.ones(len(s))
    vv = np.asarray(v, np.float64)[pts, 0]
    P = np.asarray(curves.get(POINT, "P"), np.float64)[pts]
    Q = np.vstack([P, P[:1]]) if closed else P
    if closed:
        vv = np.concatenate([vv, vv[:1]])
    sc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))])
    return np.interp(np.clip(s, 0.0, L), sc, vv)


def _write_out(g, s, L, k, pi, pos_attrib, index_attrib, curvenum_attrib, copy_attribute):
    n = g.npoints
    if str(pos_attrib).strip():
        g.set(POINT, str(pos_attrib).strip(), (s / L if L > 0 else s)[:, None].astype(np.float32), owned=True)
    if str(index_attrib).strip():
        g.set(POINT, str(index_attrib).strip(), np.full((n, 1), k, np.int32), owned=True)
    if str(curvenum_attrib).strip():
        g.set(POINT, str(curvenum_attrib).strip(), np.full((n, 1), pi, np.int32), owned=True)
    if str(copy_attribute).strip():
        g.set(POINT, str(copy_attribute).strip(), np.full((n, 1), k, np.int32), owned=True)
        if g.nprims:
            g.set(PRIM, str(copy_attribute).strip(), np.full((g.nprims, 1), k, np.int32), owned=True)
