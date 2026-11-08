"""
Platonic Solids SOP -- the five regular polyhedra, plus the soccer ball (truncated icosahedron).

━━ How they are built: two "raw materials" + two operations
The tetrahedron, cube and icosahedron have their coordinates written directly (the icosahedron uses three golden-ratio phi rectangles);
the other three are produced by **operations**, no hand-copied coordinate tables:

    octahedron     = dual of the cube
    dodecahedron   = dual of the icosahedron
    soccer ball    = icosahedron with corners truncated at 1/3 and 2/3 along each edge

Dual: each face center becomes a new point, the ring of faces around each old point becomes a new face. Truncation: on each directed
edge a->b take a + t(b-a); old faces become faces with twice the edges, old points become a small face.
With t = 1/3 the truncated hexagons are exactly regular (all edges equal, verified in tests).

The easiest thing to get wrong in hand-copied coordinate tables is **winding** (12 pentagons on a dodecahedron, copy one wrong and one face points inward).
Here all faces finally go through a single "face normal points the same way as the face center" check and inward ones are flipped -- a convex polyhedron
is star-shaped about its center, so this criterion holds for every face.

━━ Output conventions
- circumscribed sphere radius = Radius (every point is at that distance from the center)
- polygons are all closed, normals point outward (counter-clockwise seen from outside, consistent with Box / Sphere)
- points are shared (watertight, Euler characteristic 2)
- prim attribute `sides`: how many edges this face has (on the soccer ball 5 = black patch, 6 = white patch, for coloring)
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, PRIM

TYPES = ("tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron",
         "soccer_ball")


def _tetra():
    V = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], float)
    F = [[0, 1, 2], [0, 3, 1], [0, 2, 3], [1, 3, 2]]
    return V, F


def _cube():
    V = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)],
                 float)
    # point number = 4x + 2y + z (0/1)
    F = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6],
         [0, 2, 6, 4], [1, 5, 7, 3]]
    return V, F


def _icosa():
    p = (1 + 5 ** 0.5) / 2
    V = []
    for a in (-1, 1):
        for b in (-p, p):
            V += [[0, a, b], [a, b, 0], [b, 0, a]]
    V = np.array(V, float)
    # faces = triples with pairwise distance 2 (edge length 2)
    D = np.linalg.norm(V[:, None] - V[None], axis=2)
    adj = np.abs(D - 2.0) < 1e-9
    F = []
    for i in range(12):
        for j in range(i + 1, 12):
            if not adj[i, j]:
                continue
            for k in range(j + 1, 12):
                if adj[i, k] and adj[j, k]:
                    F.append([i, j, k])
    return V, F


def _orient_out(V, F):
    """For each face: the face normal and face center (relative to the origin) must point the same way, otherwise flip."""
    out = []
    for f in F:
        P = V[f]
        c = P.mean(0)
        n = np.zeros(3)
        for i in range(len(f)):                      # Newell normal
            a, b = P[i], P[(i + 1) % len(f)]
            n += np.cross(a, b)
        out.append(list(f) if n @ c > 0 else list(f)[::-1])
    return out


def _ring(V, F, v):
    """The faces around point v, ordered around v (adjacent faces share an edge through v)."""
    inc = [fi for fi, f in enumerate(F) if v in f]
    nxt = {}
    for fi in inc:
        f = F[fi]
        k = f.index(v)
        nxt[fi] = f[(k + 1) % len(f)]                # the point after v in this face
    # Face fi's edge v->nxt appears as nxt->v in the face on the other side, i.e. prev(v) = nxt
    prev = {}
    for fi in inc:
        f = F[fi]
        k = f.index(v)
        prev[f[(k - 1) % len(f)]] = fi
    order = [inc[0]]
    while True:
        g = prev.get(nxt[order[-1]])
        if g is None or g == order[0]:
            break
        order.append(g)
    return order


def _dual(V, F):
    F = _orient_out(V, F)                    # _ring requires faces already oriented outward
    C = np.array([V[f].mean(0) for f in F])
    C /= np.linalg.norm(C, axis=1, keepdims=True)
    G = [_ring(V, F, v) for v in range(len(V))]
    return C, _orient_out(C, G)


def _truncate(V, F, t):
    F = _orient_out(V, F)
    key = {}
    pts = []

    def pid(a, b):                                   # the point on edge a->b near a
        k = (a, b)
        if k not in key:
            key[k] = len(pts)
            pts.append(V[a] + t * (V[b] - V[a]))
        return key[k]

    G = []
    for f in F:
        n = len(f)
        g = []
        for i in range(n):
            a, b = f[i], f[(i + 1) % n]
            g += [pid(a, b), pid(b, a)]
        G.append(g)
    for v in range(len(V)):
        ring = _ring(V, F, v)
        g = []
        for fi in ring:
            f = F[fi]
            k = f.index(v)
            g.append(pid(v, f[(k + 1) % len(f)]))
        G.append(g)
    P = np.array(pts)
    return P, _orient_out(P, G)


def solid(kind="icosahedron", radius=1.0, center=(0.0, 0.0, 0.0)):
    """Build a regular polyhedron. Returns a Geometry (prim attribute sides)."""
    if kind not in TYPES:
        raise ValueError(f"Type must be one of {TYPES}")
    if kind == "tetrahedron":
        V, F = _tetra()
    elif kind == "cube":
        V, F = _cube()
    elif kind == "octahedron":
        V, F = _dual(*_cube())
    elif kind == "icosahedron":
        V, F = _icosa()
    elif kind == "dodecahedron":
        V, F = _dual(*_icosa())
    else:
        V, F = _truncate(*_icosa(), 1.0 / 3.0)
    F = _orient_out(V, F)
    V = V / np.linalg.norm(V, axis=1).max() * float(radius) + \
        np.asarray(center, float)
    g = Geometry.from_mesh(V, F, closed=True)
    g.set(PRIM, "sides", np.array([len(f) for f in F], np.int32)[:, None],
          owned=True)
    return g
