"""
PolyWire SOP (pcg121): tubes along every edge of a curve network.

Sweep makes one tube per curve; PolyWire works on the **edge graph**: polylines and polygon edges together, shared
points joined, branches allowed (trees, wire frames, L-systems, road graphs).

  chains     the graph is cut at every point whose valence is not 2 (ends and junctions); each chain becomes one tube
             with rotation-minimising frames (no twisting along the chain), loops become closed tubes
  joints     where chains meet (valence >= 3) or at bends sharper than Joint Angle a sphere of the wire radius is added,
             so branches have no gaps and no spikes; open ends get a flat cap or a round (half-sphere) end
  radius     Wire Radius, or per point from an attribute (width is a diameter like Houdini's, pscale a radius)
Point attributes of the curve (Cd, ...) are carried to the tube points made from each curve point.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, PRIM_POLY
from .groups import resolve

END_CAPS = ("round", "flat", "none")
RADIUS_FROM = ("constant", "width", "pscale")


def _segments(geo, group):
    sel = resolve(geo, PRIM, group)
    sizes = geo.prim_sizes()
    segs = []
    for i in np.nonzero(sel & (geo.prim_type == PRIM_POLY) & (sizes >= 2))[0]:
        p = geo.prim_points(int(i)).astype(np.int64)
        if geo.prim_closed[i] and len(p) >= 3:
            segs.append(np.stack([p, np.roll(p, -1)], 1))
        else:
            segs.append(np.stack([p[:-1], p[1:]], 1))
    if not segs:
        return np.zeros((0, 2), np.int64)
    s = np.sort(np.concatenate(segs), 1)
    s = s[s[:, 0] != s[:, 1]]
    return np.unique(s, axis=0)


def _chains(segs, n):
    """Cut the edge graph at points of valence != 2. Returns [(points, closed)]."""
    adj = [[] for _ in range(n)]
    for e, (a, b) in enumerate(segs):
        adj[a].append((b, e))
        adj[b].append((a, e))
    deg = np.array([len(x) for x in adj])
    used = np.zeros(len(segs), bool)
    out = []
    for start in np.nonzero((deg > 0) & (deg != 2))[0]:
        for nb, e in adj[start]:
            if used[e]:
                continue
            chain, cur, prev_e = [int(start)], int(nb), e
            used[e] = True
            while True:
                chain.append(cur)
                if deg[cur] != 2:
                    break
                nxt = [(b, f) for b, f in adj[cur] if f != prev_e and not used[f]]
                if not nxt:
                    break
                cur, prev_e = nxt[0]
                used[prev_e] = True
            out.append((np.array(chain), False))
    for e in np.nonzero(~used)[0]:                      # pure loops (every point valence 2)
        if used[e]:
            continue
        a, b = segs[e]
        chain, cur, prev_e = [int(a)], int(b), e
        used[e] = True
        while cur != a:
            chain.append(cur)
            nxt = [(c, f) for c, f in adj[cur] if f != prev_e and not used[f]]
            if not nxt:
                break
            cur, prev_e = nxt[0]
            used[prev_e] = True
        out.append((np.array(chain), True))
    return out, deg


def _sphere(c, r, div):
    """UV sphere (div around, div//2 + 1 rings incl. poles as rings of coincident points kept simple): quads + tris."""
    rows = max(2, div // 2)
    th = np.linspace(0, np.pi, rows + 1)
    ph = np.linspace(0, 2 * np.pi, div, endpoint=False)
    pts = [c + r * np.array([0.0, 1.0, 0.0])]
    for t in th[1:-1]:
        pts += list(c + r * np.stack([np.sin(t) * np.cos(ph), np.cos(t) * np.ones_like(ph), np.sin(t) * np.sin(ph)], 1))
    pts.append(c + r * np.array([0.0, -1.0, 0.0]))
    P = np.array(pts)
    faces = []
    nring = rows - 1
    for j in range(div):
        faces.append([0, 1 + (j + 1) % div, 1 + j])
    for k in range(nring - 1):
        a0, b0 = 1 + k * div, 1 + (k + 1) * div
        for j in range(div):
            j1 = (j + 1) % div
            faces.append([a0 + j, a0 + j1, b0 + j1, b0 + j])
    last = len(P) - 1
    base = 1 + (nring - 1) * div
    for j in range(div):
        faces.append([base + j, base + (j + 1) % div, last])
    return P, faces


def polywire(geo, group="", radius=0.05, radius_from="constant", divisions=8, end_caps="round", joints=True,
             joint_angle=45.0, carry_attributes=True):
    """Returns (geometry, report)."""
    from .curveframe import curve_frames
    if end_caps not in END_CAPS:
        raise ValueError(f"End Caps must be one of {END_CAPS}")
    if radius_from not in RADIUS_FROM:
        raise ValueError(f"Radius From must be one of {RADIUS_FROM}")
    div = max(3, int(divisions))
    n = geo.npoints
    segs = _segments(geo, group)
    if not len(segs):
        raise ValueError("PolyWire needs curves or polygons (edges to put wires on)")
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    R = np.full(n, float(radius))
    if radius_from != "constant":
        a = geo.get(POINT, radius_from)
        if a is None:
            raise ValueError(f"Radius From = {radius_from}: the curve has no point attribute '{radius_from}'")
        R = np.asarray(a, np.float64)[:, 0] * (0.5 if radius_from == "width" else 1.0)
    chains, deg = _chains(segs, n)

    allP, faces, src = [], [], []          # src: curve point each new point came from
    nb = 0
    ph = np.linspace(0, 2 * np.pi, div, endpoint=False)
    cs, sn = np.cos(ph), np.sin(ph)
    sphere_at = set()
    for ids, closed in chains:
        Q = P[ids]
        T, U, _ = curve_frames(Q, closed)
        X = np.cross(U, T)
        X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-30)
        r = R[ids][:, None, None]
        ring = Q[:, None, :] + r * (cs[None, :, None] * X[:, None, :] + sn[None, :, None] * U[:, None, :])
        m = len(ids)
        allP.append(ring.reshape(-1, 3))
        src.append(np.repeat(ids, div))
        rows = m if closed else m - 1
        for i in range(rows):
            a0, b0 = nb + i * div, nb + ((i + 1) % m) * div
            for j in range(div):
                j1 = (j + 1) % div
                faces.append([a0 + j, a0 + j1, b0 + j1, b0 + j])
        if not closed:
            for end, k in ((ids[0], 0), (ids[-1], m - 1)):
                if deg[end] >= 3 and joints:
                    sphere_at.add(int(end))
                elif deg[end] == 1:
                    if end_caps == "round":
                        sphere_at.add(int(end))
                    elif end_caps == "flat":
                        cap = [nb + k * div + j for j in range(div)]
                        faces.append(cap[::-1] if k == 0 else cap)
        if joints and m >= 3:
            Qc = np.vstack([Q[-1:], Q, Q[:1]]) if closed else Q
            d0 = Qc[1:-1] - Qc[:-2]
            d1 = Qc[2:] - Qc[1:-1]
            cosang = np.einsum("ij,ij->i", d0, d1) / np.maximum(
                np.linalg.norm(d0, axis=1) * np.linalg.norm(d1, axis=1), 1e-30)
            bend = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
            inner = ids if closed else ids[1:-1]
            for p in inner[bend > float(joint_angle)]:
                sphere_at.add(int(p))
        nb += m * div
    for p in sorted(sphere_at):
        SP, SF = _sphere(P[p], R[p], div)
        allP.append(SP)
        src.append(np.full(len(SP), p))
        faces += [[nb + v for v in f] for f in SF]
        nb += len(SP)
    NP = np.concatenate(allP)
    out = Geometry.from_mesh(NP, faces)
    srcs = np.concatenate(src)
    if carry_attributes:
        for k, v in geo.attribs[POINT].items():
            if k in ("P", "N", "width", "pscale", "up", "orient"):
                continue
            out.set(POINT, k, v[srcs], owned=True)
    rep = {"chains": len(chains), "joints": len(sphere_at), "points": out.npoints, "prims": out.nprims}
    return out, rep
