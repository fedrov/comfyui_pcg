"""
Exploded View -- pushes fragments apart for inspection. Matches Houdini's Exploded View SOP.

Earlier batches added Voronoi Fracture, Voronoi Cluster and Convex Decompose, which all output pieces fitted
seamlessly together -- that is, they **look exactly as if nothing was cut**. To check that the cut is right you have to
push them apart.

The node itself has little algorithm, but it is the "eyes" of those nodes, and there are two easy ways to get it wrong.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each piece must move **rigidly**, never by global scaling
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The laziest "push apart" scales the whole geometry by k about the centre -- the pieces do separate, but each piece itself
is also scaled by k, so its volume becomes k^3 times. It looks convincing in a picture, but any measurement taken from it is wrong.

The right way is **per-piece translation**: each piece moves along "centre -> that piece's centroid", with no deformation inside the piece.
That gives a very clean criterion: **every piece's volume is unchanged, piece by piece** (not the total, every single piece).

Uniform Distance is "every piece moves the same distance", Proportional is "the distance is proportional to its distance from the
centre" (equivalent to scaling the centroids as a whole, without deforming the pieces). The former suits inspecting layers of thin shells, the latter
gives an explosion feel.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The centroid must be integrated over **triangles**; neither level can be skipped
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A point-position average is biased by mesh density: if one face of a fragment is subdivided especially densely, the centroid shifts towards
that face. Voronoi fragments have exactly this problem -- the fracture face is one whole n-gon (very few points), while the outer shell
inherits the original model's subdivision (many points), so the point-average "centroid" leans clearly towards the shell.

Falling back to "face centroid x area" is still not enough: `prim_centers` gives the **vertex average**, which for an n-gon
is not its area centroid. Subdividing the same face changes the centroid -- measured: a 0.3-wide
Voronoi fragment linearly subdivided twice moved its centroid computed this way by **0.04**. Subdivision must not change the centroid;
this is a hard requirement, and the first version failed on exactly this.

So after fan triangulation we integrate over triangles, weighted by **signed** area (the area vector projected onto the face
normal); for planar polygons this is exact, and concave n-gons also come out right thanks to positive/negative cancellation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Where pieces come from
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    attribute     by prim attribute (name / piece / cluster -- all written by the upstream nodes)
    connectivity  by connected components, no attribute needed

Shrink additionally scales each piece a little about **its own centroid**, leaving gaps between fracture faces so the structure is clearer --
that is an obvious deformation, not contradicting the rule above: it has its own control, and the default 1.0 changes nothing.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .ops import prim_centers
from .measure import prim_areas

MODES = ("uniform", "proportional")
PIECE_FROM = ("attribute", "connectivity")
CENTERS = ("centroid", "origin", "bbox")


def piece_ids(geo, kind="attribute", attrib="name"):
    """(nprims,) which piece each primitive belongs to."""
    if kind not in PIECE_FROM:
        raise ValueError(f"Piece From must be one of {PIECE_FROM}")
    if kind == "connectivity":
        from .pieces import connectivity
        c = connectivity(geo, cls="prim", name="__ex_class")
        return c.get(PRIM, "__ex_class")[:, 0].astype(np.int64)
    name = str(attrib).strip() or "name"
    a = geo.get(PRIM, name)
    if a is None:
        have = sorted(geo.attribs[PRIM].keys())
        raise KeyError(
            f"prim has no '{name}' attribute -- Voronoi Fracture / Voronoi Cluster /"
            f" Convex Decompose all write name and piece. Switching Piece From ="
            f" connectivity also works. Existing: {have or '(none)'}")
    if is_string(a):
        _, inv = np.unique(np.asarray(a)[:, 0], return_inverse=True)
        return inv.reshape(-1).astype(np.int64)
    return a[:, 0].astype(np.int64)


def piece_centroids(geo, pid):
    """
    Surface-area-weighted centroid of each piece -- integrated over **triangles**, not over faces.

    Neither level can be skipped:

    A point-position average is biased by mesh density. Voronoi fragments have exactly this problem -- the fracture face is one whole
    n-gon (very few points), the shell side inherits the original model's subdivision (many points), and the averaged "centroid"
    leans clearly towards the shell.

    Falling back to "face centroid x area" is still not enough: `prim_centers` gives the **vertex average**, which for
    an n-gon is not its area centroid. So subdividing the same face changes the centroid -- measured:
    a Voronoi fragment linearly subdivided twice moved its centroid computed this way by 0.04 (the piece itself is only
    0.3 wide). Subdivision must not change the centroid; this is a hard requirement.

    So after fan triangulation we integrate per triangle, weighted by **signed** area (the area vector projected onto the face
    normal); for planar polygons this is exact -- concave n-gons also come out right thanks to positive/negative cancellation.
    """
    tri, cor = geo.triangles(with_corners=True)
    k = int(pid.max()) + 1 if len(pid) else 0
    if not len(tri):
        C = np.asarray(prim_centers(geo), np.float64)
        return np.stack([C[pid == j].mean(0) if (pid == j).any()
                         else np.zeros(3) for j in range(k)], 0)
    from .ops import prim_normals
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    A, B, C3 = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    av = 0.5 * np.cross(B - A, C3 - A)
    fp = geo.vertex_prim()[cor[:, 0]]                 # which face each triangle comes from
    FN = np.asarray(prim_normals(geo), np.float64)
    w = np.einsum("ij,ij->i", av, FN[fp])             # signed area
    tc = (A + B + C3) / 3.0
    tp = pid[fp]
    tot = np.bincount(tp, weights=w, minlength=k)
    bad = np.abs(tot) <= 1e-30
    num = np.stack([np.bincount(tp, weights=w * tc[:, j], minlength=k)
                    for j in range(3)], 1)
    out = num / np.where(bad, 1.0, tot)[:, None]
    if bad.any():                    # degenerate (zero-area) pieces fall back to the point-position average
        Cc = np.asarray(prim_centers(geo), np.float64)
        for j in np.nonzero(bad)[0]:
            out[j] = Cc[pid == j].mean(0) if (pid == j).any() else 0.0
    return out


def explode(geo, mode="uniform", distance=0.25, shrink=1.0,
            piece_from="attribute", piece_attrib="name", center="centroid",
            center_point=(0.0, 0.0, 0.0), relative=True, up_bias=0.0):
    """
    Translates each piece away along "centre -> that piece's centroid". Each piece moves **rigidly**; volumes are unchanged piece by piece.
    """
    if geo is None:
        return Geometry()
    if mode not in MODES:
        raise ValueError(f"Mode must be one of {MODES}")
    if center not in CENTERS:
        raise ValueError(f"Center must be one of {CENTERS}")
    if geo.nprims == 0 or geo.npoints == 0:
        return geo.copy()

    pid = piece_ids(geo, piece_from, piece_attrib)
    _, pid = np.unique(pid, return_inverse=True)
    pid = pid.reshape(-1).astype(np.int64)
    PC = piece_centroids(geo, pid)

    mn, mx = geo.bbox()
    mn = np.asarray(mn, np.float64)
    mx = np.asarray(mx, np.float64)
    scale = float(np.max(mx - mn)) or 1.0
    if center == "origin":
        c0 = np.asarray(center_point, np.float64).reshape(3)
    elif center == "bbox":
        c0 = (mn + mx) / 2
    else:
        c0 = PC.mean(0)

    v = PC - c0
    ln = np.linalg.norm(v, axis=1)
    dirs = v / np.where(ln > 1e-12, ln, 1.0)[:, None]
    # Pieces whose centroid sits exactly on the centre have no direction to push in; give them a deterministic direction instead of leaving them in place
    dirs[ln <= 1e-12] = np.array([0.0, 1.0, 0.0])

    d = float(distance) * (scale if relative else 1.0)
    off = dirs * d if mode == "uniform" else v * float(distance)
    if up_bias:
        off = off + np.array([0.0, 1.0, 0.0]) * (
            float(up_bias) * (scale if relative else 1.0))

    P = np.asarray(geo.get(POINT, "P"), np.float64)
    # A point's piece comes from the primitive it belongs to. Points straddling two pieces don't exist -- each fragment has its own points
    pp = np.zeros(geo.npoints, np.int64)
    pp[geo.vertex_point] = pid[geo.vertex_prim()]
    s = float(shrink)
    Q = P if s == 1.0 else PC[pp] + (P - PC[pp]) * s
    out = geo.copy()
    out.set(POINT, "P", (Q + off[pp]).astype(np.float32), owned=True)
    return out
