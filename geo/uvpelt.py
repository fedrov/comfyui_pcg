"""
UV Pelt -- mirrors Houdini's UV Pelt SOP (2.0).

Not the same as UV Flatten: Flatten solves the conformal energy with a free boundary (or a few pinned points); Pelt is like stretching a hide --
first cut along seams into a topological disk, pin its **longest boundary loop** by arc length onto a frame (a circle by default), then use
springs to pull the interior points flat. The boundary shape is fixed (the frame's shape); how the interior is distributed depends on the spring weights:

    Spring Relaxation   weights depend on edge length and the area of adjacent faces (wording from the docs; no exact formula given,
                        here (sum of the two adjacent triangle areas) / edge length², see _weights)
    Tutte Barycentric   unit weights: each interior point lands at the centroid of its neighbours. With a convex frame it is **guaranteed not to flip faces**
                        (Tutte's 1963 embedding theorem)
    Discrete Harmonic   cotangent weights (discrete harmonic map), least angle distortion

The boundary is not hard-pinned: each boundary point is tied to its position on the frame by a spring of strength Boundary Springs, with energy

    Σ_edges w_ij |u_i − u_j|²  +  k Σ_boundary points |u_b − f_b|²

Quadratic in u, its minimum is a symmetric positive definite linear system (L + k·D_b) u = k·f. The larger k, the closer the boundary hugs the frame
(docs: "increase it to enlarge the pelt"); with small k the whole patch is pulled inward by the interior springs. Here PCG solves it directly to convergence,
and Iterations is CG's maximum step count -- Houdini's iterations are its own relaxation solver, which is not converged with few steps, so the two
will not match "with very few iterations".

As in UV Flatten, the unknowns are wedges (two on the two sides of a seam), and the geometry is not cut.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM
from .groups import resolve_edges
from .uvflatten import wedges, _fan_tris, _pcg, _corner_angles

METHODS = ("spring_relaxation", "tutte_barycentric", "discrete_harmonic")


def _loops(tri):
    """
    Directed triangle edges that occur only once (no reverse edge) = boundary, chained into loops.
    Returns [wedge index array, ...], following the triangle winding.
    """
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    key = np.sort(e, 1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    b = e[cnt[inv.reshape(-1)] == 1]
    nxt = {}
    for a, c in b.tolist():
        nxt.setdefault(a, []).append(c)
    seen = set()
    out = []
    for a0 in list(nxt):
        if a0 in seen:
            continue
        loop = [a0]
        seen.add(a0)
        cur = a0
        while True:
            cand = [c for c in nxt.get(cur, []) if c not in seen]
            if not cand:
                break
            cur = cand[0]
            seen.add(cur)
            loop.append(cur)
        out.append(np.asarray(loop, np.int64))
    return out


def _weights(P3, tri, method, stiff=None):
    """Each undirected edge (i, j) and its spring weight."""
    e = np.concatenate([tri[:, [1, 2]], tri[:, [2, 0]], tri[:, [0, 1]]])   # edge k is opposite corner k
    key = np.sort(e, 1)
    uq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    if method == "tutte_barycentric":
        w = np.ones(len(uq))
    elif method == "discrete_harmonic":
        ang = _corner_angles(P3, tri)                                      # (T,3)
        cot = (np.cos(ang) / np.maximum(np.sin(ang), 1e-12)).T.reshape(-1)  # same order as e
        w = 0.5 * np.bincount(inv, weights=cot, minlength=len(uq))
    else:
        # Docs: "spring weights depend on edge length and the area of the incident faces". No exact formula: use sum of adjacent triangle areas / edge length²
        # (dimensionless, so uniformly scaling the geometry does not change the result; short edges of thin triangles are stiffer)
        a = 0.5 * np.linalg.norm(np.cross(P3[tri[:, 1]] - P3[tri[:, 0]],
                                          P3[tri[:, 2]] - P3[tri[:, 0]]), axis=1)
        area = np.bincount(inv, weights=np.tile(a, 3), minlength=len(uq))
        L2 = ((P3[uq[:, 0]] - P3[uq[:, 1]]) ** 2).sum(1)
        w = area / np.maximum(L2, 1e-30)
    if stiff is not None:
        w = w * 0.5 * (stiff[uq[:, 0]] + stiff[uq[:, 1]])
    return uq, w


def _frame_curve(frame):
    """
    Frame: an (m,2) closed polyline, counter-clockwise. (Without a frame the docs say the default is a circle: pelt() uses the circle with center (0.5, 0.5),
    radius 0.5 directly, without going through here.) With frame geometry: take the first prim with ≥ 3 points, U = P.x, V = P.y (the docs do not list
    the options of Houdini's U From / V From menus; implemented as "take P's x / y").
    """
    P = frame.get(POINT, "P")
    if P is None or frame.nprims == 0:
        raise ValueError("The Frame input has no primitives: the frame must be a closed polygon.")
    sizes = frame.prim_sizes()
    k = np.nonzero(sizes >= 3)[0]
    if not len(k):
        raise ValueError("The Frame input has no primitive with >= 3 points.")
    pts = np.asarray(P, np.float64)[frame.prim_points(int(k[0]))][:, :2]
    area = 0.5 * float(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1)
                              - np.roll(pts[:, 0], -1) * pts[:, 1]))
    if abs(area) < 1e-18:
        raise ValueError("The Frame primitive has zero projected area in the XY plane (U = P.x, V = P.y).")
    # a frame given clockwise is walked in reverse; the start (frame parameter 0) is still the first point
    return pts if area > 0 else np.roll(pts[::-1], 1, axis=0)


def _on_frame(curve, t):
    """Take points on a closed polyline by arc-length parameter t ∈ [0,1)."""
    seg = np.roll(curve, -1, 0) - curve
    L = np.linalg.norm(seg, axis=1)
    cum = np.concatenate([[0.0], np.cumsum(L)])
    s = (np.asarray(t) % 1.0) * cum[-1]
    i = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(curve) - 1)
    f = (s - cum[i]) / np.maximum(L[i], 1e-30)
    return curve[i] + f[:, None] * seg[i]


def pelt(geo, frame=None, name="uv", seam_group="", method="spring_relaxation",
         iterations=1000, boundary_springs=10.0, stiffness_attrib="", hint_prim=0,
         use_range=False, u_range=(0.0, 1.0), v_range=(0.0, 1.0), orientation=0.0,
         output_group=""):
    if geo is None:
        return Geometry()
    if method not in METHODS:
        raise ValueError(f"Pelting Method must be one of {METHODS}")
    nm = str(name or "").strip()
    if not nm:
        raise ValueError("UV Attribute is empty.")
    if geo.nprims == 0 or geo.nvertices == 0:
        return geo.copy()
    P = geo.get(POINT, "P")
    pairs = (resolve_edges(geo, seam_group) if str(seam_group).strip()
             else np.zeros((0, 2), np.int32))
    wid, comp = wedges(geo, pairs)
    tri, tsrc = _fan_tris(geo, wid)
    h = int(np.clip(int(hint_prim), 0, geo.nprims - 1))
    region = comp == comp[h]
    keep_t = region[tsrc]
    tri = tri[keep_t]
    if not len(tri):
        raise ValueError(f"The piece containing Hint Primitive {h} has no primitive with >= 3 points.")

    nw = int(wid.max()) + 1
    wpt = np.zeros(nw, np.int64)
    wpt[wid] = geo.vertex_point
    used = np.unique(tri)
    remap = np.full(nw, -1, np.int64)
    remap[used] = np.arange(len(used))
    T = remap[tri]
    P3 = np.asarray(P, np.float64)[wpt[used]]
    n = len(used)

    loops = _loops(T)
    if not loops:
        raise ValueError(
            "The piece containing Hint Primitive is closed, with no boundary to pin to the frame -- first give an Edge Cut Group "
            "(e.g. the output of UV Autoseam) to cut it into a disk.")
    # Docs: the **longest** boundary loop of the piece containing the hint primitive is attached to the frame
    lens = [float(np.linalg.norm(P3[lp] - P3[np.roll(lp, -1)], axis=1).sum()) for lp in loops]
    loop = loops[int(np.argmax(lens))]
    # Docs: Orientation sets where "the first boundary point" (the one nearest the hint primitive) lies on the frame
    c = np.asarray(P, np.float64)[geo.prim_points(h)].mean(0)
    st = int(np.argmin(np.linalg.norm(P3[loop] - c, axis=1)))
    loop = np.roll(loop, -st)
    seg = np.linalg.norm(P3[loop] - P3[np.roll(loop, -1)], axis=1)
    t = np.concatenate([[0.0], np.cumsum(seg)[:-1]]) / max(float(seg.sum()), 1e-30)
    if frame is None:
        # the default circle frame is sampled by angle directly, not via the polyline (the polyline's chords would pull boundary points in by ~1e-5)
        a = 2 * np.pi * ((t + float(orientation)) % 1.0)
        f = np.stack([0.5 + 0.5 * np.cos(a), 0.5 + 0.5 * np.sin(a)], 1)
    else:
        f = _on_frame(_frame_curve(frame), t + float(orientation))

    stiff = None
    if str(stiffness_attrib).strip():
        a = geo.get(POINT, str(stiffness_attrib).strip())
        if a is None:
            raise KeyError(f"No point attribute '{stiffness_attrib}'.")
        stiff = np.asarray(a, np.float64)[:, 0][wpt[used]]
    E, w = _weights(P3, T, method, stiff)
    k = float(boundary_springs)
    if k <= 0:
        raise ValueError("Boundary Springs must be > 0: with no springs tied to the frame, the whole patch collapses to a point.")
    bd = np.zeros(n)
    bd[loop] = k
    diag = (np.bincount(E[:, 0], weights=w, minlength=n)
            + np.bincount(E[:, 1], weights=w, minlength=n) + bd)

    def A(x):
        y = diag * x
        y -= np.bincount(E[:, 0], weights=w * x[E[:, 1]], minlength=n)
        y -= np.bincount(E[:, 1], weights=w * x[E[:, 0]], minlength=n)
        return y

    uv = np.zeros((n, 2))
    x0 = np.full(n, 0.0)
    for d in range(2):
        rhs = np.zeros(n)
        rhs[loop] = k * f[:, d]
        x0[:] = float(f[:, d].mean())
        uv[:, d], _ = _pcg(A, diag, rhs, x0, max(int(iterations), 1), 1e-12)

    if use_range:
        lo, hi = uv.min(0), uv.max(0)
        span = np.where(hi - lo > 1e-30, hi - lo, 1.0)
        r0 = np.array([u_range[0], v_range[0]], np.float64)
        r1 = np.array([u_range[1], v_range[1]], np.float64)
        uv = r0 + (uv - lo) / span * (r1 - r0)

    full = np.zeros((nw, 2))
    full[used] = uv
    out = full[wid]
    vreg = np.repeat(region, geo.prim_sizes())
    cur = geo.get(VERTEX, nm)
    g = geo.copy()
    if cur is not None and cur.shape[1] >= 2:
        base = np.array(cur, np.float64)
        base[vreg, :2] = out[vreg]
        g.set(VERTEX, nm, base.astype(cur.dtype), owned=True)
    else:
        if geo.get(POINT, nm) is not None and geo.get(POINT, nm).shape[1] >= 2:
            old = np.asarray(geo.get(POINT, nm), np.float64)[geo.vertex_point, :2]
            out = np.where(vreg[:, None], out, old)    # same as UV Flatten: point uv is kept, not deleted
        else:
            out = np.where(vreg[:, None], out, 0.0)
        g.set(VERTEX, nm, out.astype(np.float32), owned=True)
    if str(output_group).strip():
        g.set_group(PRIM, str(output_group).strip(), region)
    return g
