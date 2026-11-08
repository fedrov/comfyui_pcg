"""
Remesh (pcg68, the star of SOP gap batch D): isotropic remeshing.

━━ Algorithm: Botsch & Kobbelt 2004, five steps per iteration
  1 split    edges longer than 4/3.L are split at the midpoint
  2 collapse edges shorter than 4/5.L are collapsed to a point (a collapse must not create edges longer than 4/3.L)
  3 flip     flip diagonals so each point's neighbour count approaches 6 (4 for boundary points)
  4 relax    tangential smoothing: each point moves toward the average of its neighbours, but only within the tangent plane
  5 project  project back onto the **original** surface (closest point) -- relaxing moves points off the surface, this step pulls them back
L is the target edge length. The thresholds 4/3 and 4/5 are derived in the paper: the two halves of a split are >= 2/3.L,
collapsed edges are <= 4/3.L, so the two operations do not fight back and forth.

━━ Features (hard edges and boundaries) must be preserved
Edges with a dihedral angle above feature_angle, and boundary edges, are **feature edges**. Rules:
  . when a feature edge is split, the new point is also on the feature;
  . collapses do not cross features: if one end of an ordinary edge is a feature point, collapse onto that feature point (feature points do not move);
    if both ends are feature points but the edge is not a feature edge -- do not collapse (it would break the feature line);
  . feature points connected to a number of feature edges other than exactly two are **corners** (the 8 corners of a cube); corners
    never move and are never collapsed;
  . flips only flip non-feature edges; relaxing does not move feature points. So feature points never change position from start to finish (new points
    from splits are on the original feature segments), feature polylines are preserved exactly point by point, and no projection back is needed.
So after remeshing a cube the 8 corners are intact and the 12 edges are still on mesh edges (verified in tests).

━━ Implementation: each step applies a batch of "mutually non-adjacent" operations
Split, collapse and flip are all local topology changes; two adjacent operations done at once would trample each other. Each step first greedily
picks a batch that do not affect each other (split: not sharing a face; collapse, flip: non-overlapping one-ring neighbourhoods), applies them all at once, rebuilds adjacency,
then picks the next batch. The picking order is fixed (by edge length / by number), so results are reproducible.

━━ Not implemented
  . uv seams are not preserved: point attributes are interpolated by barycentric coordinates of the nearest triangle, and vertex attributes (uv)
    are also interpolated by the triangle the new point is in -- both sides of a seam get values from the same side. If you need uv, unwrap again
    after remeshing
  . only polygon faces are processed; curves and isolated points are dropped (since pcg100 giving a group means local remeshing, and unselected
    prims including curves are kept as they are -- see remesh's docstring and _stitch)
"""
from __future__ import annotations

import math

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string
from . import spatial as _sp


# ═══════════════════════════════════════════════════════════ small helpers
def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n < 1e-300, 1.0, n)


def _edges(F):
    """(m,3) triangles -> unique edges (E,2) (sorted), the three edge numbers of each triangle (m,3)."""
    he = np.stack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 1).reshape(-1, 2)
    key = np.sort(he, axis=1)
    E, inv = np.unique(key, axis=0, return_inverse=True)
    return E, inv.reshape(-1, 3)


def _face_normals(V, F):
    return np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])


def _edge_faces(FE, nE):
    """Which faces each edge borders (the first two), and how many faces it borders."""
    cnt = np.bincount(FE.reshape(-1), minlength=nE)
    ef = np.full((nE, 2), -1, np.int64)
    fid = np.repeat(np.arange(len(FE)), 3)
    e = FE.reshape(-1)
    order = np.argsort(e, kind="stable")
    es, fs = e[order], fid[order]
    first = np.searchsorted(es, es, side="left")
    rank = np.arange(len(es)) - first
    ok = rank < 2
    ef[es[ok], rank[ok]] = fs[ok]
    return ef, cnt


class _Feat:
    """Set of feature edges (point-pair keys) and feature points / corners."""

    def __init__(self, nV):
        self.keys = set()
        self.nV = nV

    def key(self, a, b):
        return (min(a, b), max(a, b))

    def has(self, a, b):
        return (min(a, b), max(a, b)) in self.keys

    def add(self, a, b):
        self.keys.add((min(a, b), max(a, b)))

    def discard(self, a, b):
        self.keys.discard((min(a, b), max(a, b)))

    def degree(self, n):
        d = np.zeros(n, np.int64)
        for a, b in self.keys:
            d[a] += 1
            d[b] += 1
        return d


def _neighbors(F, n):
    nb = [set() for _ in range(n)]
    for a, b, c in F.tolist():
        nb[a].update((b, c))
        nb[b].update((a, c))
        nb[c].update((a, b))
    return nb


def _vert_faces(F, n):
    vf = [[] for _ in range(n)]
    for i, (a, b, c) in enumerate(F.tolist()):
        vf[a].append(i)
        vf[b].append(i)
        vf[c].append(i)
    return vf


# ═══════════════════════════════════════════════════════════ the five steps
_SMOOTH_COS = math.cos(math.radians(60.0))   # a turn below 60 deg on a feature line counts as "bending smoothly"


def _feat_mids(V, E, pick, feat, corner):
    """
    New points from splitting feature edges land on the **interpolating curve** through the feature polyline (the midpoint of four-point subdivision / Catmull-Rom:
    (-p0 + 9a + 9b - p3)/16), not the chord midpoint. Only the smooth side of the feature line is used:
    when an end is a corner, or the feature line turns >= 60 deg there (a polyline corner, a right-angle boundary corner of a grid), that side
    falls back to a straight line. With both sides falling back it is the ordinary midpoint.

    Previously the chord midpoint was always used: a curved edge on a coarse mesh (the rim of a 16-sided cylinder) was still a series of straight segments after splitting,
    the curve "flattened" into a polygon.
    """
    adj = {}
    for a, b in feat.keys:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    a_, b_ = E[pick, 0], E[pick, 1]
    mids = 0.5 * (V[a_] + V[b_])
    for j, (a, b) in enumerate(zip(a_.tolist(), b_.tolist())):
        if not feat.has(a, b):
            continue

        def far(x, y):
            # The "previous point" along the feature line at end x; None if not smooth
            if corner[x]:
                return None
            nb = adj.get(x, ())
            if len(nb) != 2:
                return None
            w = nb[0] if nb[1] == y else nb[1] if nb[0] == y else None
            if w is None:
                return None
            d0, d1 = V[x] - V[w], V[y] - V[x]
            n0, n1 = np.linalg.norm(d0), np.linalg.norm(d1)
            if n0 < 1e-12 or n1 < 1e-12 or d0 @ d1 < _SMOOTH_COS * n0 * n1:
                return None
            return w
        pa, pb = far(a, b), far(b, a)
        A, B = V[a], V[b]
        if pa is not None and pb is not None:
            mids[j] = (-V[pa] + 9 * A + 9 * B - V[pb]) / 16.0
        elif pa is not None:
            mids[j] = (-V[pa] + 6 * A + 3 * B) / 8.0       # quadratic through pa, a, b
        elif pb is not None:
            mids[j] = (3 * A + 6 * B - V[pb]) / 8.0
    return mids


def _split(V, F, feat, hi, corner=None):
    """
    Split long edges. Each batch picks edges not sharing a face, until there are no long edges (or the batch count is exhausted).
    When corner is not None (smooth_features), new points of feature edges land on the interpolating curve, see _feat_mids.
    """
    n_split = 0
    for _ in range(64):
        E, FE = _edges(F)
        L = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
        cand = np.nonzero(L > hi)[0]
        if not len(cand):
            break
        ef, _ = _edge_faces(FE, len(E))
        cand = cand[np.argsort(-L[cand], kind="stable")]
        used = np.zeros(len(F), bool)
        pick = []
        for e in cand.tolist():
            f = ef[e]
            fs = f[f >= 0]
            if used[fs].any():
                continue
            used[fs] = True
            pick.append(e)
        if not pick:
            break
        pick = np.array(pick)
        nv0 = len(V)
        if corner is None:
            mids = 0.5 * (V[E[pick, 0]] + V[E[pick, 1]])
        else:
            mids = _feat_mids(V, E, pick, feat, corner)
            corner = np.concatenate([corner, np.zeros(len(pick), bool)])
        V = np.vstack([V, mids])
        newF = []
        kill = np.zeros(len(F), bool)
        for j, e in enumerate(pick.tolist()):
            a, b = int(E[e, 0]), int(E[e, 1])
            m = nv0 + j
            if feat.has(a, b):
                feat.discard(a, b)
                feat.add(a, m)
                feat.add(m, b)
            for f in ef[e]:
                if f < 0:
                    continue
                tri = F[f].tolist()
                # Make (x, y) this edge as it appears in the triangle's winding order
                for k in range(3):
                    x, y, z = tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]
                    if {x, y} == {a, b}:
                        break
                newF.append([x, m, z])
                newF.append([m, y, z])
                kill[f] = True
        F = np.vstack([F[~kill], np.array(newF, np.int64).reshape(-1, 3)])
        n_split += len(pick)
    return V, F, n_split


def _collapse(V, F, feat, lo, hi, corner):
    """Collapse short edges (greedy, non-overlapping one-ring neighbourhoods)."""
    E, FE = _edges(F)
    L = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    cand = np.nonzero(L < lo)[0]
    if not len(cand):
        return V, F, 0, corner
    cand = cand[np.argsort(L[cand], kind="stable")]
    n = len(V)
    nb = _neighbors(F, n)
    vf = _vert_faces(F, n)
    fdeg = feat.degree(n)
    isf = fdeg > 0
    ef_, cnt_ = _edge_faces(FE, len(E))
    bnd = np.zeros(n, bool)
    bnd[E[cnt_ == 1].reshape(-1)] = True
    lock = np.zeros(n, bool)
    FN = _face_normals(V, F)
    remap = np.arange(n)
    newpos = {}
    dead = np.zeros(len(F), bool)
    done = 0
    for e in cand.tolist():
        a, b = int(E[e, 0]), int(E[e, 1])
        if lock[a] or lock[b] or corner[a] and corner[b]:
            continue
        fe = feat.has(a, b)
        if bnd[a] and bnd[b] and cnt_[e] != 1:
            continue                      # an interior edge between two boundary points: collapsing would pinch out a non-manifold
        # Decide which one stays and where
        if fe:
            if corner[a] or corner[b]:
                keep, gone = (a, b) if corner[a] else (b, a)
            elif fdeg[a] == 2 and fdeg[b] == 2:
                keep, gone = a, b
            else:
                continue
            x = V[keep]
        else:
            if isf[a] and isf[b]:
                continue
            if isf[a] or corner[a]:
                keep, gone, x = a, b, V[a]
            elif isf[b] or corner[b]:
                keep, gone, x = b, a, V[b]
            else:
                keep, gone, x = a, b, 0.5 * (V[a] + V[b])
        if corner[gone]:
            continue
        # link condition: common neighbours = the third points of the faces bordering this edge (2 for interior edges, 1 for boundary edges)
        common = nb[a] & nb[b]
        faces_ab = [f for f in vf[a] if b in F[f]]
        if len(common) != len(faces_ab):
            continue
        ring = (nb[a] | nb[b]) - {a, b}
        if any(np.linalg.norm(V[r] - x) > hi for r in ring):
            continue
        ok = True
        for f in set(vf[a]) | set(vf[b]):
            if f in faces_ab:
                continue
            tri = F[f].copy()
            tri[tri == gone] = keep
            P3 = V[tri].copy()
            P3[tri == keep] = x
            nn = np.cross(P3[1] - P3[0], P3[2] - P3[0])
            if float(nn @ FN[f]) <= 0.2 * np.linalg.norm(nn) * np.linalg.norm(FN[f]):
                ok = False
                break
        if not ok:
            continue
        for r in ring | {a, b}:
            lock[r] = True
        remap[gone] = keep
        newpos[keep] = x
        for f in faces_ab:
            dead[f] = True
        # Move feature edges: feature edges on gone are reattached to keep
        for r in list(nb[gone]):
            if feat.has(gone, r):
                feat.discard(gone, r)
                if r != keep:
                    feat.add(keep, r)
        done += 1
    if not done:
        return V, F, 0, corner
    for k, x in newpos.items():
        V[k] = x
    F = remap[F[~dead]]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    # Compact away unused points
    used = np.zeros(len(V), bool)
    used[F.reshape(-1)] = True
    idx = np.nonzero(used)[0]
    new = np.full(len(V), -1, np.int64)
    new[idx] = np.arange(len(idx))
    feat2 = _Feat(len(idx))
    for a, b in feat.keys:
        if used[a] and used[b]:
            feat2.add(int(new[a]), int(new[b]))
    feat.keys = feat2.keys
    return V[idx], new[F], done, corner[idx]


def _flip(V, F, feat, boundary_pt):
    """Edge flips: toward the target valence (6 interior, 4 boundary)."""
    E, FE = _edges(F)
    ef, cnt = _edge_faces(FE, len(E))
    n = len(V)
    val = np.bincount(E.reshape(-1), minlength=n)
    target = np.where(boundary_pt, 4, 6)
    eset = set(map(tuple, E.tolist()))
    used = np.zeros(len(F), bool)
    flips = 0
    Fl = F.tolist()
    for e in np.nonzero(cnt == 2)[0].tolist():
        a, b = int(E[e, 0]), int(E[e, 1])
        if feat.has(a, b):
            continue
        f1, f2 = int(ef[e, 0]), int(ef[e, 1])
        if used[f1] or used[f2]:
            continue
        t1 = Fl[f1]
        k = t1.index(a)
        if t1[(k + 1) % 3] != b:                  # make f1 contain a -> b
            a, b = b, a
            k = t1.index(a)
        c = t1[(k + 2) % 3]
        t2 = Fl[f2]
        d = [v for v in t2 if v != a and v != b]
        if len(d) != 1:
            continue
        d = d[0]
        if c == d or (min(c, d), max(c, d)) in eset:
            continue
        before = sum(abs(int(val[v]) - int(target[v])) for v in (a, b, c, d))
        after = (abs(int(val[a]) - 1 - int(target[a])) +
                 abs(int(val[b]) - 1 - int(target[b])) +
                 abs(int(val[c]) + 1 - int(target[c])) +
                 abs(int(val[d]) + 1 - int(target[d])))
        if after >= before:
            continue
        n_old = np.cross(V[b] - V[a], V[c] - V[a]) + \
            np.cross(V[a] - V[b], V[d] - V[b])
        na = np.cross(V[d] - V[a], V[c] - V[a])
        nb_ = np.cross(V[b] - V[d], V[c] - V[d])
        if na @ n_old <= 0 or nb_ @ n_old <= 0:
            continue
        Fl[f1] = [a, d, c]
        Fl[f2] = [d, b, c]
        used[f1] = used[f2] = True
        val[a] -= 1
        val[b] -= 1
        val[c] += 1
        val[d] += 1
        eset.discard((min(a, b), max(a, b)))
        eset.add((min(c, d), max(c, d)))
        flips += 1
    return np.array(Fl, np.int64).reshape(-1, 3), flips


def _relax(V, F, movable, lam):
    """Tangential smoothing: move toward the neighbour average by lambda, removing the normal component."""
    E, _ = _edges(F)
    n = len(V)
    s = np.zeros((n, 3))
    np.add.at(s, E[:, 0], V[E[:, 1]])
    np.add.at(s, E[:, 1], V[E[:, 0]])
    c = np.bincount(E.reshape(-1), minlength=n)
    q = s / np.maximum(c, 1)[:, None]
    FN = _face_normals(V, F)
    VN = np.zeros((n, 3))
    for k in range(3):
        np.add.at(VN, F[:, k], FN)
    VN = _unit(VN)
    d = q - V
    d = d - VN * np.einsum("ij,ij->i", d, VN)[:, None]
    V = V.copy()
    V[movable] += lam * d[movable]
    return V


# ═══════════════════════════════════════════════════════════ entry
UV_SEAMS = ("ignore", "harden")


def _other_side(geo, sel):
    """Points used by unselected prims (mask) and their edges (set of sorted point pairs)."""
    vp = geo.vertex_point.astype(np.int64)
    vsel = np.repeat(sel, geo.prim_sizes())
    pts = np.zeros(geo.npoints, bool)
    pts[vp[~vsel]] = True
    edges = set()
    for i in np.nonzero(~sel)[0].tolist():
        c = geo.prim_points(i).tolist()
        m = len(c) if geo.prim_closed[i] else len(c) - 1
        for j in range(m):
            a, b = int(c[j]), int(c[(j + 1) % len(c)])
            edges.add((min(a, b), max(a, b)))
    return pts, edges


def _uv_seam_edges(E, FE, F, UV):
    """
    UV island boundaries: the faces on the two sides of an edge have different uv at its two endpoints. UV is (m,3,C), the values at each triangle's three corners.
    Each half-edge is laid out as "lower point number end / higher point number end"; the half-edges of the same edge take per-component max and min, and any difference is a seam.
    """
    C = UV.shape[2]
    v0 = np.stack([F[:, 0], F[:, 1], F[:, 2]], 1).reshape(-1)
    v1 = np.stack([F[:, 1], F[:, 2], F[:, 0]], 1).reshape(-1)
    u0 = UV.reshape(-1, C)
    u1 = UV[:, [1, 2, 0]].reshape(-1, C)
    sw = (v0 > v1)[:, None]
    rec = np.concatenate([np.where(sw, u1, u0), np.where(sw, u0, u1)], 1)
    e = FE.reshape(-1)
    lo = np.full((len(E), 2 * C), np.inf)
    hi = np.full((len(E), 2 * C), -np.inf)
    np.minimum.at(lo, e, rec)
    np.maximum.at(hi, e, rec)
    return ((hi - lo) > 1e-6).any(1)


def _stitch(geo, sel, out, V, feat, corner, iface_pts, iface_edges, weld):
    """
    Wrap-up of local remeshing: unselected prims are kept as they are and stitched back to the remeshed piece (out).
    weld = True (Houdini's Detach From Nongroup Geometry off): new points split on the border are also inserted into the
    edges of the unselected faces (triangles may become quads / N-gons -- that is what the Houdini docs say), with points shared by both sides;
    False: each side has its own copy of the border points, unconnected.
    Original points on the border are corners in the remesh and never move, so they can be identified in V by coordinates.
    """
    from .meshedit import _Build
    from .ops import merge, delete_points
    P0 = np.asarray(geo.get(POINT, "P"), np.float64)
    n0 = geo.npoints
    B = _Build(geo)
    weld_pairs = []                       # (point number kept after stitching, point number in out)
    missed = 0
    if weld:
        at = {tuple(V[i]): int(i) for i in np.nonzero(corner)[0]}
        fin = {int(p): at[tuple(P0[p])] for p in np.nonzero(iface_pts)[0]
               if tuple(P0[p]) in at}
        weld_pairs = [(p, i) for p, i in fin.items()]
        adj = {}
        for a, b in feat.keys:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)

        def chain(fa, fb):
            """The chain fa -> fb on the feature graph passing only through split points (all on segment fa-fb)."""
            A, D = V[fa], V[fb] - V[fa]
            L2 = float(D @ D)
            for nx in adj.get(fa, ()):
                path, prev, cur = [], fa, nx
                while cur != fb and not corner[cur] and len(adj[cur]) == 2 \
                        and len(path) < len(V):
                    path.append(cur)
                    prev, cur = cur, (adj[cur][0] if adj[cur][0] != prev else adj[cur][1])
                if cur != fb:
                    continue
                ts = [float((V[x] - A) @ D) / L2 for x in path]
                if all(0 < t < 1 and np.linalg.norm(V[x] - A - t * D) <= 1e-9 * math.sqrt(L2)
                       for x, t in zip(path, ts)):
                    return list(zip(path, ts))
            return None

        made = {}
    vp = geo.vertex_point.astype(np.int64)
    off = geo.prim_offset.astype(np.int64)
    for f in np.nonzero(~sel)[0].tolist():
        cs = list(range(int(off[f]), int(off[f + 1])))
        cl = bool(geo.prim_closed[f])
        pts, cor = [], []
        m = len(cs)
        for j in range(m):
            c = cs[j]
            p = int(vp[c])
            pts.append(p)
            cor.append(c)
            if not weld or (j == m - 1 and not cl):
                continue
            c2 = cs[(j + 1) % m]
            q = int(vp[c2])
            if (min(p, q), max(p, q)) not in iface_edges:
                continue
            ch = chain(fin[p], fin[q]) if p in fin and q in fin else None
            if ch is None:
                missed += 1
                continue
            for x, t in ch:
                if x not in made:
                    made[x] = B.add_point([p, q], [1.0 - t, t])
                    weld_pairs.append((made[x], x))
                pts.append(made[x])
                cor.append(((c, c2), (1.0 - t, t)))
        B.add_face(pts, cor, f, cl)
    rest = B.geometry()
    g = merge(rest, out)
    nr = rest.npoints
    pm = np.arange(g.npoints, dtype=np.int64)
    keep = np.ones(g.npoints, bool)
    for kp, x in weld_pairs:
        pm[nr + x] = kp
        keep[nr + x] = False
    # Original points used only by selected faces: their faces were replaced by the remesh result, so nothing uses these points anymore
    vsel = np.repeat(sel, geo.prim_sizes())
    only = np.zeros(n0, bool)
    only[vp[vsel]] = True
    only[vp[~vsel]] = False
    keep[:n0] &= ~only
    if weld_pairs:
        eg = g.remap_edge_groups(pm.astype(np.int32), g.npoints)
        g.set_topology(pm[g.vertex_point].astype(np.int32), g.prim_offset,
                       g.prim_closed, g.prim_type)
        g.edge_groups = eg
    return delete_points(g, keep), missed


def remesh(geo, target_length=0.0, iterations=6, feature_angle=45.0,
           keep_boundary=True, relax=0.5, transfer_attributes=True,
           group="", hard_edges="", hard_points="", uv_seams="ignore",
           uv_attribute="uv", detach=False, out_hard_edges="",
           smooth_features=False):
    """
    pcg100 additions to match Houdini's Remesh (with all defaults the original path runs, results are bit-identical):
      group        remesh only these faces; other prims (including curves) are kept as they are. With detach = False, points split on the border
                   are also inserted into the neighbouring unselected faces, with points shared by both sides; with True the two sides are disconnected
      hard_edges   edge group: may be split, but always stays in the output (same rules as hard edges detected by angle)
      hard_points  point group: these points always stay in the output (not moved, not collapsed)
      uv_seams     harden: edges where uv_attribute (a vertex attribute) is discontinuous are treated as hard edges; Houdini's Resample is not implemented
      out_hard_edges  non-empty: write the final hard edges (including boundaries and seams, after splitting) as an edge group with this name
      smooth_features (pcg102) when feature edges are split, new points land on the interpolating curve through the feature polyline (four-point subdivision),
                   so curved edges / boundaries come out round after refining, not the original few straight segments. Off by default = Houdini's
                   behaviour (new points on the original polyline). No interpolation on either side of corners (corner points, turns >= 60 deg);
                   with local remeshing and no detach, border edges are not interpolated (they must match the neighbouring faces)

    Matches Houdini's Remesh: retile a polygon mesh into a triangle mesh with edge lengths close to target_length
    (see the file header). With target_length <= 0 the average edge length of the triangulated input is used.

    feature_angle: edges with a dihedral angle above it are kept as hard edges (>= 180 means no hard edges are detected).
    keep_boundary: boundaries are features (the outline of an open mesh does not move).
    relax: step size of the tangential smoothing (0~1).
    transfer_attributes: point, prim and vertex attributes are interpolated from the nearest original triangle
    (see "Not implemented" in the file header).
    Returns (geometry, report).
    """
    from .spatial import tri_soup
    from .groups import resolve, resolve_edges
    if uv_seams not in UV_SEAMS:
        raise ValueError(f"UV Seams must be one of {UV_SEAMS}")
    P0 = np.asarray(geo.get(POINT, "P"), np.float64) if geo.npoints else \
        np.zeros((0, 3))
    sel = resolve(geo, PRIM, group) if str(group).strip() else None
    partial = sel is not None and not sel.all()
    if partial and not sel.any():
        return geo.copy(), {"target_length": float(target_length), "splits": 0,
                            "collapses": 0, "flips": 0, "points": int(geo.npoints),
                            "triangles": 0, "edge_mean": 0.0, "within_range": 0.0}
    tri0, src_prim0, corner0 = tri_soup(geo, group if partial else "")
    if not len(tri0):
        raise ValueError("No polygon faces to remesh (curves and point clouds are not processed)")
    used = np.unique(tri0.reshape(-1))
    new = np.full(len(P0), -1, np.int64)
    new[used] = np.arange(len(used))
    V = P0[used].copy()
    F = new[tri0].astype(np.int64)
    E, FE = _edges(F)
    L0 = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    L = float(target_length) if float(target_length) > 0 else float(L0.mean())
    if not L > 0:
        raise ValueError("Target Length computed to 0 (degenerate mesh?)")
    hi, lo = 4.0 / 3.0 * L, 4.0 / 5.0 * L

    # ── features
    ef, cnt = _edge_faces(FE, len(E))
    FN = _unit(_face_normals(V, F))
    feat = _Feat(len(V))
    fmask = np.zeros(len(E), bool)
    two = cnt == 2
    if float(feature_angle) < 180:
        cosang = np.einsum("ij,ij->i", FN[ef[two, 0]], FN[ef[two, 1]])
        sharp = cosang < math.cos(math.radians(float(feature_angle)))
        fmask[np.nonzero(two)[0][sharp]] = True
    if keep_boundary:
        fmask |= cnt == 1
    fmask |= cnt > 2                              # non-manifold edges are always features
    if str(hard_edges).strip():
        he = new[np.asarray(resolve_edges(geo, hard_edges), np.int64).reshape(-1, 2)]
        he = np.sort(he[(he >= 0).all(1)], axis=1)
        nV = len(V) + 1
        fmask |= np.isin(E[:, 0] * nV + E[:, 1], he[:, 0] * nV + he[:, 1])
    if uv_seams == "harden":
        uvn = str(uv_attribute).strip()
        uva = geo.get(VERTEX, uvn) if uvn else None
        if uva is None or is_string(uva):
            raise KeyError(f"UV Seams = Harden: no numeric vertex attribute '{uvn}'")
        fmask |= two & _uv_seam_edges(E, FE, F, np.asarray(uva, np.float64)[corner0])
    iface_pts = iface_edges = None
    if partial:
        iface_pts, iface_edges = _other_side(geo, sel)
    stitch = partial and not detach
    if stitch:
        # Edges shared with unselected faces: always features (splitting allowed, no flipping, no collapsing away)
        oe = np.array(sorted(iface_edges), np.int64).reshape(-1, 2)
        nP = len(P0) + 1
        shared = np.isin(used[E[:, 0]] * nP + used[E[:, 1]], oe[:, 0] * nP + oe[:, 1])
        fmask |= shared
        # The true border edges = those present on both sides (used is monotonic, so point pairs are still sorted)
        iface_edges = set(map(tuple, used[E[shared]].tolist()))
    for a, b in E[fmask].tolist():
        feat.add(a, b)
    corner = np.array([d not in (0, 2) for d in feat.degree(len(V))])
    if str(hard_points).strip():
        corner |= resolve(geo, POINT, hard_points)[used]
    if stitch:
        # All original points on the border are corners: not moved, not removed, so they can be recognized when stitching back
        corner |= iface_pts[used]
    orig_tri = F.copy()
    Vorig = V.copy()

    rep = {"target_length": L, "splits": 0, "collapses": 0, "flips": 0}
    for _ in range(max(0, int(iterations))):
        corner_pos = {tuple(V[i]) for i in np.nonzero(corner)[0]}
        if smooth_features:
            cs = corner.copy()
            if stitch:
                # Border edges stay on the original polyline: both ends count as "not smooth", border points fall back to the midpoint
                for a, b in feat.keys:
                    if (int(used[a]), int(used[b])) in iface_edges or \
                            (int(used[b]), int(used[a])) in iface_edges:
                        cs[a] = cs[b] = True
            V, F, ns = _split(V, F, feat, hi, cs)
        else:
            V, F, ns = _split(V, F, feat, hi)
        corner = np.array([tuple(v) in corner_pos for v in V]) \
            if corner_pos else np.zeros(len(V), bool)
        V, F, nc, corner = _collapse(V, F, feat, lo, hi, corner)
        E, FE = _edges(F)
        _, cnt = _edge_faces(FE, len(E))
        bpt = np.zeros(len(V), bool)
        bpt[E[cnt == 1].reshape(-1)] = True
        F, nf = _flip(V, F, feat, bpt)
        fdeg = feat.degree(len(V))
        movable = (fdeg == 0) & ~corner
        V = _relax(V, F, movable, float(relax))
        # Projection: ordinary points are projected back onto the original surface. Feature points need no projection: they are never moved --
        # splitting only inserts points at feature edge midpoints (still on the original polyline), collapses always keep the feature point as "the one that stays"
        # in place, and relaxing excludes feature points. So feature polylines are preserved exactly point by point.
        if movable.any():
            _, _, pos, _ = _sp.closest_surface(V[movable], Vorig, orig_tri)
            V[movable] = pos
        rep["splits"] += ns
        rep["collapses"] += nc
        rep["flips"] += nf

    out = Geometry.from_mesh(V, F, closed=True)
    if transfer_attributes:
        ti, _, pos, uv = _sp.closest_surface(V, Vorig, orig_tri)
        ti = np.maximum(ti, 0)
        w = np.stack([1 - uv[:, 0] - uv[:, 1], uv[:, 0], uv[:, 1]], 1)
        src_pts = used[orig_tri[ti]]                      # (n,3) original point numbers
        for k, v in geo.attribs[POINT].items():
            if k == "P" or is_string(v):
                continue
            vv = np.asarray(v, np.float64)
            out.set(POINT, k, (vv[src_pts] * w[:, :, None]).sum(1)
                    .astype(v.dtype), owned=True)
        # prim attributes: each new triangle takes the prim of the original triangle nearest its center
        C = V[F].mean(1)
        tf, _, _, uvf = _sp.closest_surface(C, Vorig, orig_tri)
        tf = np.maximum(tf, 0)
        for k, v in geo.attribs[PRIM].items():
            out.set(PRIM, k, v[src_prim0[tf]], owned=True)
        # vertex attributes: each corner is interpolated by its point's barycentric coordinates on "the original triangle nearest this face"
        if geo.attribs[VERTEX]:
            cor = corner0[tf]                               # (m,3) original corners
            A_, B_, C_ = (Vorig[orig_tri[tf, k]] for k in range(3))
            for k, v in geo.attribs[VERTEX].items():
                if is_string(v):
                    continue
                vv = np.asarray(v, np.float64)
                vals = []
                for j in range(3):
                    p = V[F[:, j]]
                    bw = _bary(p, A_, B_, C_)
                    vals.append((vv[cor] * bw[:, :, None]).sum(1))
                out.set(VERTEX, k, np.stack(vals, 1).reshape(-1, vv.shape[1])
                        .astype(v.dtype), owned=True)
    E, _ = _edges(F)
    Lf = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    rep.update({"points": int(len(V)), "triangles": int(len(F)),
                "edge_mean": float(Lf.mean()),
                "within_range": float(((Lf >= 0.5 * L) & (Lf <= hi + 1e-9))
                                      .mean())})
    ohe = str(out_hard_edges).strip()
    if ohe:
        out.set_edge_group(ohe, np.array(sorted(feat.keys), np.int32).reshape(-1, 2))
    if partial:
        out, missed = _stitch(geo, sel, out, V, feat, corner, iface_pts, iface_edges,
                              stitch)
        rep["points"] = int(out.npoints)
        rep["unmatched_interface_edges"] = int(missed)
    return out, rep


def _bary(p, A, B, C):
    """Barycentric coordinates of p in the plane of triangle ABC (clamped into the triangle)."""
    v0, v1, v2 = B - A, C - A, p - A
    d00 = np.einsum("ij,ij->i", v0, v0)
    d01 = np.einsum("ij,ij->i", v0, v1)
    d11 = np.einsum("ij,ij->i", v1, v1)
    d20 = np.einsum("ij,ij->i", v2, v0)
    d21 = np.einsum("ij,ij->i", v2, v1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) > 1e-300,
                   d00 * d11 - d01 * d01, 1.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1 - v - w
    bw = np.clip(np.stack([u, v, w], 1), 0, None)
    return bw / np.maximum(bw.sum(1, keepdims=True), 1e-300)
