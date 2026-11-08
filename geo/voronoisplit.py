"""
Voronoi Split (pcg74): splits a **surface** by the Voronoi cells of a set of points.

Voronoi Fracture cuts solids (cells intersected with a closed volume, cuts must be capped); this cuts the surface itself --
every spot on the mesh belongs to its nearest cell point, and the cut lines lie exactly on the bisector planes of two cell points. The result is
patches lying on the original surface, with the shape completely unchanged.

━━ How it cuts
  · If all points of a face belong to the same cell point -> the whole face goes to it unchanged, no cut, no triangulation. This step is **exact**:
    cells are convex, the face lies in the convex hull of its points, the points are all in the cell, so the face is in the cell
  · The other faces are cut into triangles, each triangle compared only with cells that "may touch it" (candidates = cell points no farther from the triangle than
    "the max distance from a vertex to its nearest cell point + the triangle diameter" -- the nearest cell point of any spot in the triangle is
    within this range, by the triangle inequality); for each candidate cell k the triangle is clipped successively by the bisector planes between it and the other candidates
    (Sutherland–Hodgman)
  · Triangle fragments from the same original face belonging to the same cell are stitched back into one polygon (removing interior diagonals) --
    a cut quad comes out as a polygon, not a pile of triangles

━━ How cut points are shared
Each new point carries a **composite key**: original edge × bisector plane {i,j}, or triangle × three cells {i,j,k} (the point where three cells
meet inside a face). The same point computed by fragments on both sides has the same key and is created only once -- so
with split_points off the two sides of a cut share points and the mesh stays connected; with it on, each cell gets its own copy of the points,
and the patches are truly separated (Houdini's default). Point attributes are interpolated linearly on edges and by barycentric coordinates in triangles;
vertex attributes likewise.

━━ Output
piece_attribute (default name) is written as "piece<k>", k being the cell point's index; an integer prim attribute
cell is also written. Faces not selected by the group and curves are kept as they are, with cell = −1. If cut_group is named, the cut edges are written as
an edge group.

━━ Not done
  · When the bisector planes of three cells meet exactly on an original edge (degenerate), triangles on both sides may give the same point different keys,
    so in shared mode an extra coincident point appears there
  · Only polygon faces are cut; curves are not
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .core import POINT, PRIM
from .groups import resolve
from .meshedit import _Build


def _clip(poly, k, j, S, eps, plane=None):
    """
    poly = [(position, key, barycentric coordinates, outgoing edge label)]. Keeps the side closer to k than to j.
    If plane (pcg100 s9) is given it is used for the cut plane: plane(k, j) -> c, the cut plane is x·(S_j − S_k) = c.
    """
    d = S[j] - S[k]
    c = 0.5 * (S[j] @ S[j] - S[k] @ S[k]) if plane is None else plane(k, j)
    f = [float(p[0] @ d - c) for p in poly]
    lab_new = ("b", frozenset((k, j)))
    out = []
    n = len(poly)
    for i in range(n):
        A, B = poly[i], poly[(i + 1) % n]
        fa, fb = f[i], f[(i + 1) % n]
        ina, inb = fa <= eps, fb <= eps
        if ina and inb:
            out.append(A)
        elif ina and not inb:
            if fa < -eps:
                t = fa / (fa - fb)
                out.append(A)
                out.append(_cross(A, B, t, k, j, lab_new))
            else:
                out.append((A[0], A[1], A[2], lab_new))
        elif not ina and inb:
            if fb < -eps:
                t = fa / (fa - fb)
                X = _cross(A, B, t, k, j, A[3])
                out.append(X)
    return out


def _cross(A, B, t, k, j, out_label):
    lab = A[3]
    if lab[0] == "o":
        key = ("e", lab[1], frozenset((k, j)))
    else:
        key = ("t", None, frozenset(lab[1] | {k, j}))
    pos = A[0] + t * (B[0] - A[0])
    bw = A[2] + t * (B[2] - A[2])
    return (pos, key, bw, out_label)


def _merge(frags):
    """Stitch fragments (point-number loops) of the same face and the same cell into one loop. Returns None if they do not form a single loop."""
    he = defaultdict(int)
    for f in frags:
        for a, b in zip(f, f[1:] + f[:1]):
            he[(a, b)] += 1
    rest = []
    for (a, b), c in he.items():
        if c and not he.get((b, a)):
            rest.append((a, b))
    nxt = {}
    for a, b in rest:
        if a in nxt:
            return None
        nxt[a] = b
    if not nxt:
        return None
    start = min(nxt)
    loop = [start]
    while True:
        b = nxt.get(loop[-1])
        if b is None:
            return None
        if b == start:
            break
        loop.append(b)
        if len(loop) > len(nxt):
            return None
    if len(loop) != len(nxt):
        return None
    return loop


METHODS = ("power", "ratio")


def _plane_fn(S, w, method, offset):
    """
    pcg100 s9: cut planes under Weight Attribute (Method = Power Distance / Ratio) and Offset.
    One plane per pair of cell points {a, b}, normal along the connecting line, position:
      power   equal power: |x − S_a|² − w_a² = |x − S_b|² − w_b² (weights are sphere radii, power diagram; with all weights equal
              it is the ordinary Voronoi)
      ratio   the ratio of the plane's distances to the two points = the ratio of weights (the side with the smaller weight is closer to the plane):
              fraction from a t = w_a / (w_a + w_b)
      offset  then move by offset along the "lower index -> higher index" direction. The docs only say "along the segment direction"; we have no clip
              polyline, so the direction is set by point number -- that way (a, b) and (b, a) use the same plane on both sides and no gap opens
    Returns plane(k, j) -> c (cut plane x·(S_j − S_k) = c).
    """
    def plane(k, j):
        d = S[j] - S[k]
        if w is None:
            c = 0.5 * (S[j] @ S[j] - S[k] @ S[k])
        elif method == "power":
            c = 0.5 * (S[j] @ S[j] - S[k] @ S[k] - w[j] ** 2 + w[k] ** 2)
        else:
            t = w[k] / (w[k] + w[j])
            c = (S[k] + t * d) @ d
        if offset:
            lo, hi = min(k, j), max(k, j)
            u = S[hi] - S[lo]
            c += float(offset) * (u @ d) / max(np.linalg.norm(u), 1e-300)
        return c
    return plane


def voronoi_split(geo, points, group="", split_points=True,
                  piece_attribute="name", cut_group="", use_weight=False,
                  weight_attribute="weight", method="power", offset=0.0):
    """
    See the file header. Returns (geometry, report).
    pcg100 s9: use_weight / method / offset (see _plane_fn). With these on, cells are no longer "nearest to which point",
    so the two shortcuts below (whole face to one cell, filtering candidate cells by nearest distance) do not hold, and all selected faces
    take the cutting path, each triangle compared with all cells -- slow (triangles × cells²), but correct.
    """
    if method not in METHODS:
        raise ValueError(f"Method must be one of {METHODS}")
    from .spatial import tri_soup
    if points is None or not points.npoints:
        raise ValueError("Cell Points has no points -- connect something like Scatter to the second input")
    S = np.asarray(points.get(POINT, "P"), np.float64)
    w = None
    if use_weight:
        wa = points.get(POINT, str(weight_attribute).strip())
        if wa is None or wa.dtype.kind not in "fiu":
            raise ValueError(f"No numeric attribute '{weight_attribute}' on Cell Points")
        w = np.asarray(wa, np.float64).reshape(len(S), -1)[:, 0]
        if method == "ratio" and np.any(w <= 0):
            raise ValueError("Ratio weights must all be greater than 0")
    general = w is not None or float(offset) != 0.0
    plane = _plane_fn(S, w, method, offset) if general else None
    P = np.asarray(geo.get(POINT, "P"), np.float64) if geo.npoints else \
        np.zeros((0, 3))
    sel = resolve(geo, PRIM, group)
    sizes = geo.prim_sizes()
    face = geo.prim_closed & (sizes >= 3) & (geo.prim_type == 0)
    sel = sel & face
    scale = max(1.0, float(np.abs(P).max()) if len(P) else 1.0,
                float(np.abs(S).max()))
    eps = 1e-12 * scale * scale
    # nearest cell point of each point
    near = np.zeros(len(P), np.int64)
    dnear = np.zeros(len(P))
    for s in range(0, len(P), 4096):
        D = ((P[s:s + 4096, None, :] - S[None]) ** 2).sum(-1)
        near[s:s + 4096] = D.argmin(1)
        dnear[s:s + 4096] = np.sqrt(D.min(1))
    vp = np.asarray(geo.vertex_point, np.int64)
    vpr = geo.vertex_prim()
    pmin = np.full(geo.nprims, np.iinfo(np.int64).max)
    pmax = np.full(geo.nprims, -1)
    if len(vp):
        np.minimum.at(pmin, vpr, near[vp])
        np.maximum.at(pmax, vpr, near[vp])
    whole = sel & (pmin == pmax) & (not general)
    cutp = sel & ~whole
    B = _Build(geo)
    newpt = {}                                     # key -> new point number
    rep = {"cells_used": 0, "cut_prims": int(cutp.sum()),
           "whole_prims": int(whole.sum()), "fragments": 0}
    faces = []                                     # (point list, vertex list, source prim, closed, cell)
    for i in range(geo.nprims):
        if cutp[i]:
            continue
        o0, o1 = int(geo.prim_offset[i]), int(geo.prim_offset[i + 1])
        cs = list(range(o0, o1))
        faces.append(([int(vp[c]) for c in cs], cs, i, bool(geo.prim_closed[i]),
                      int(pmin[i]) if whole[i] else -1))
    if cutp.any():
        tri, tsrc, tcor = tri_soup(geo)
        keep = cutp[tsrc]
        tri, tsrc, tcor = tri[keep], tsrc[keep], tcor[keep]
        frag = defaultdict(list)                   # (prim, cell) -> [(point loop, vertex loop)]
        for ti in range(len(tri)):
            a, b, c = (int(x) for x in tri[ti])
            X = P[[a, b, c]]
            diam = max(np.linalg.norm(X[0] - X[1]), np.linalg.norm(X[1] - X[2]),
                       np.linalg.norm(X[2] - X[0]))
            R = float(dnear[[a, b, c]].max()) + diam
            dS = np.sqrt(((S[:, None, :] - X[None]) ** 2).sum(-1)).min(1)
            cand = (np.nonzero(dS - diam <= R + 1e-9 * scale)[0].tolist() if not general
                    else list(range(len(S))))
            I3 = np.eye(3)
            base = [(X[0], ("v", a), I3[0], ("o", (min(a, b), max(a, b)))),
                    (X[1], ("v", b), I3[1], ("o", (min(b, c), max(b, c)))),
                    (X[2], ("v", c), I3[2], ("o", (min(c, a), max(c, a))))]
            for k in cand:
                poly = base
                for j in cand:
                    if j == k:
                        continue
                    poly = _clip(poly, k, j, S, eps, plane)
                    if len(poly) < 3:
                        break
                if len(poly) < 3:
                    continue
                Y = np.array([p[0] for p in poly])
                ar = 0.5 * np.linalg.norm(np.cross(Y, np.roll(Y, -1, 0)).sum(0))
                if ar <= 1e-14 * scale * scale:
                    continue
                pts, cor = [], []
                cw = tcor[ti]
                for pos, key, bw, _ in poly:
                    if key[0] == "v":
                        pid = key[1]
                    else:
                        if key[0] == "t":
                            key = ("t", ti, key[2])
                        pid = newpt.get(key)
                        if pid is None:
                            pid = B.add_point([a, b, c], list(bw))
                            newpt[key] = pid
                    if pts and pts[-1] == pid:
                        continue
                    pts.append(pid)
                    cor.append((tuple(int(x) for x in cw), tuple(bw)))
                if len(pts) > 2 and pts[0] == pts[-1]:
                    pts.pop()
                    cor.pop()
                if len(pts) < 3:
                    continue
                frag[(int(tsrc[ti]), k)].append((pts, cor))
                rep["fragments"] += 1
        for (pr, k), fl in sorted(frag.items()):
            loop = _merge([f[0] for f in fl]) if len(fl) > 1 else None
            if loop is not None:
                cmap = {}
                for pts, cor in fl:
                    for p, cc in zip(pts, cor):
                        cmap.setdefault(p, cc)
                faces.append((loop, [cmap[p] for p in loop], pr, True, k))
            else:
                for pts, cor in fl:
                    faces.append((pts, cor, pr, True, k))
    # Point splitting: one copy per (point, cell); the first cell using a point keeps the original, the rest get copies
    owner, claimed = {}, set()
    ecell = defaultdict(set)                       # pre-cut edge -> cells adjacent to it
    for pts, cor, pr, cl, k in faces:
        if cl:
            for x, y in zip(pts, pts[1:] + pts[:1]):
                ecell[(min(x, y), max(x, y))].add(k)
    cells = []
    for pts, cor, pr, cl, k in faces:
        if split_points and k >= 0:
            q = []
            for p in pts:
                if (p, k) not in owner:
                    if p not in claimed:
                        claimed.add(p)
                        owner[(p, k)] = p
                    else:
                        owner[(p, k)] = B.copy_point(p)
                q.append(owner[(p, k)])
            pts = q
        B.add_face(pts, cor, pr, cl)
        cells.append(k)
    out = B.geometry(sort=False)
    cells = np.asarray(cells, np.int64)
    out.set(PRIM, "cell", cells.astype(np.int32), owned=True)
    name = str(piece_attribute).strip()
    if name:
        out.set_string(PRIM, name, np.array([f"piece{k}" if k >= 0 else ""
                                             for k in cells]))
    rep["cells_used"] = int(len(np.unique(cells[cells >= 0])))
    cg = str(cut_group).strip()
    if cg:
        pairs = []
        for (x, y), ks in ecell.items():
            if len(ks) < 2:
                continue
            for k in ks:
                if split_points and k >= 0:
                    pairs.append((owner[(x, k)], owner[(y, k)]))
                else:
                    pairs.append((x, y))
        pr_ = np.unique(np.sort(np.asarray(pairs, np.int64).reshape(-1, 2),
                                axis=1), axis=0)
        out.set_edge_group(cg, pr_.astype(np.int32))
    return out, rep
