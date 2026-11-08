"""Basic geometry generators, matching Houdini's Grid / Box / Sphere / Line / Circle SOPs."""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM

CONNECTIVITY = ("quadrilaterals", "rows", "columns", "rows_and_columns", "triangles",
                "alternating_triangles", "points")
SPHERE_TYPES = ("polygon_mesh", "polygon")
AXES = ("y", "x", "z")


def _place(P, center=(0, 0, 0), rotate=(0, 0, 0)):
    """Primitive Rotate (about its own centre, Rx Ry Rz) then move to Center -- the order used by Houdini's primitives."""
    P = np.asarray(P, np.float32)
    if any(float(r) != 0.0 for r in rotate):
        from .ops import euler_matrix
        P = P @ euler_matrix(*rotate).T
    return (P + np.asarray(center, np.float32)).astype(np.float32)


def _orient(P, axis):
    """Turns a primitive that is natively along +Y to lie along +X / +Z (coordinate rotation, no flipping)."""
    if axis not in AXES:
        raise ValueError(f"Orientation must be one of {AXES}, got {axis!r}")
    if axis == "x":
        return P[:, [1, 2, 0]]            # (x,y,z) -> (y,z,x): the original Y axis lands on X
    if axis == "z":
        return P[:, [2, 0, 1]]            # the original Y axis lands on Z
    return P


def grid_prims(rows, cols, connectivity="quadrilaterals"):
    """
    Connects rows x cols points (row-major numbering) following Houdini Grid's Connectivity.
    Returns (point-number lists of the prims, closed or not).

        quadrilaterals         one quad per cell (default)
        triangles              each cell split into two triangles along the same diagonal
        alternating_triangles  diagonal alternates per cell (checkerboard), the mesh has no directional bias
        rows / columns         one open polyline per row / per column
        rows_and_columns       both
        points                 points only, no prims
    """
    if connectivity not in CONNECTIVITY:
        raise ValueError(f"Connectivity must be one of {CONNECTIVITY}, got {connectivity!r}")
    idx = np.arange(rows * cols, dtype=np.int32).reshape(rows, cols)
    if connectivity == "points":
        return [], True
    if connectivity in ("rows", "columns", "rows_and_columns"):
        out = []
        if connectivity != "columns":
            out += [idx[i] for i in range(rows)]
        if connectivity != "rows":
            out += [idx[:, j] for j in range(cols)]
        return out, False
    i0 = idx[:-1, :-1]; i1 = idx[:-1, 1:]; i2 = idx[1:, 1:]; i3 = idx[1:, :-1]
    quads = np.stack([i0, i3, i2, i1], -1).reshape(-1, 4)       # same winding as the original grid
    if connectivity == "quadrilaterals":
        return quads, True
    a, b, c, d = quads.T
    t1 = np.stack([a, b, c], 1); t2 = np.stack([a, c, d], 1)    # split along a-c
    if connectivity == "alternating_triangles":
        ii, jj = np.meshgrid(np.arange(rows - 1), np.arange(cols - 1), indexing="ij")
        odd = ((ii + jj) % 2 == 1).reshape(-1)
        t1 = np.where(odd[:, None], np.stack([a, b, d], 1), t1)  # odd cells split along b-d
        t2 = np.where(odd[:, None], np.stack([b, c, d], 1), t2)
    return np.stack([t1, t2], 1).reshape(-1, 3), True


def grid(size_x=10.0, size_z=10.0, cols=11, rows=11, center=(0, 0, 0),
         plane="zx", rotate=(0, 0, 0), connectivity="quadrilaterals"):
    """
    cols/rows = point counts (consistent with Houdini's Grid SOP, not cell counts).
    plane: "zx" (Y-up ground) / "xy" / "yz"
    Comes with a point uv attribute.
    """
    cols, rows = max(2, int(cols)), max(2, int(rows))
    u = np.linspace(-0.5, 0.5, cols, dtype=np.float32)
    v = np.linspace(-0.5, 0.5, rows, dtype=np.float32)
    uu, vv = np.meshgrid(u, v, indexing="xy")       # (rows, cols)
    zero = np.zeros_like(uu)

    a = uu * size_x
    b = vv * size_z
    if plane == "zx":
        P = np.stack([a, zero, b], -1)
    elif plane == "xy":
        P = np.stack([a, b, zero], -1)
    else:
        P = np.stack([zero, b, a], -1)
    P = _place(P.reshape(-1, 3), center, rotate)

    # The quad winding [i0,i3,i2,i1] determines the normal direction (zx faces +Y), see grid_prims
    faces, closed = grid_prims(rows, cols, connectivity)
    g = Geometry.from_mesh(P, faces, closed=closed)
    # uv: u along the first axis, v along the second axis **negated**. That way (u, v, face normal) is right-handed, the same
    # handedness as UV Project (planar) and HeightField to Mesh: on the zx plane v points towards -Z (north),
    # and the texture is upright in the top view. The issue recorded in pcg49 and fixed in pcg56 -- before, v pointed to +Z,
    # uv was mirrored relative to the face winding, and textures sampled with the built-in uv came out flipped
    g.set(POINT, "uv", np.stack([uu + 0.5, 0.5 - vv], -1).reshape(-1, 2))
    return g


def box(size=(1, 1, 1), center=(0, 0, 0), divisions=(2, 2, 2),
        uniform_scale=1.0, rotate=(0, 0, 0), points_only=False):
    """
    Counterpart of Houdini's Box SOP: Size / Center / Uniform Scale / Axis Divisions.

    divisions is the **number of points per axis**, not the number of cells -- consistent with Houdini; the default 2 is
    a plain box (one cell per face). This also matches the rows/cols convention of grid / sphere / tube
    in this package. Houdini allows 1 (the whole box collapses into a line / a point); here the minimum
    is pinned at 2: degenerate geometry is of no use downstream and only turns into hard-to-trace empty output.

    Divisions are not done by building a grid for each of the six faces and welding -- that duplicates points at the seams. Instead,
    the cells on the "shell" of the (nx,ny,nz) lattice are marked and numbered once, and the six faces look up this table directly,
    so points on shared edges naturally exist only once.
    """
    nx, ny, nz = [max(2, int(d)) for d in divisions]
    s = np.asarray(size, np.float32) * float(uniform_scale) * 0.5
    xs = np.linspace(-1, 1, nx, dtype=np.float32) * s[0]
    ys = np.linspace(-1, 1, ny, dtype=np.float32) * s[1]
    zs = np.linspace(-1, 1, nz, dtype=np.float32) * s[2]

    shell = np.zeros((nx, ny, nz), bool)
    shell[[0, -1], :, :] = True
    shell[:, [0, -1], :] = True
    shell[:, :, [0, -1]] = True
    ii, jj, kk = np.nonzero(shell)
    idx = np.full((nx, ny, nz), -1, np.int32)
    idx[ii, jj, kk] = np.arange(len(ii), dtype=np.int32)
    P = _place(np.stack([xs[ii], ys[jj], zs[kk]], 1), center, rotate)
    if points_only:                       # Primitive Type = Points: only the lattice points on the shell
        return Geometry.from_mesh(P, [])

    faces = []

    def side(get, na, nb, flip):
        for a in range(na - 1):
            for b in range(nb - 1):
                q = [int(idx[get(a, b)]), int(idx[get(a + 1, b)]),
                     int(idx[get(a + 1, b + 1)]), int(idx[get(a, b + 1)])]
                faces.append(q[::-1] if flip else q)

    side(lambda a, b: (0, a, b), ny, nz, True)            # -X
    side(lambda a, b: (nx - 1, a, b), ny, nz, False)        # +X
    side(lambda a, b: (a, 0, b), nx, nz, False)             # -Y
    side(lambda a, b: (a, ny - 1, b), nx, nz, True)       # +Y
    side(lambda a, b: (a, b, 0), nx, ny, True)            # -Z
    side(lambda a, b: (a, b, nz - 1), nx, ny, False)        # +Z
    return Geometry.from_mesh(P, np.asarray(faces, np.int32))


def _icosphere(freq):
    """
    Houdini Sphere's Primitive Type = Polygon: each edge of an icosahedron split into freq segments, points pushed onto the unit sphere.
    20*f^2 triangles, 10*f^2 + 2 points, triangles of nearly equal size, no poles.

    Each face gets (f+1)(f+2)/2 lattice points by barycentric coordinates; points on edges / corners shared by adjacent faces must be merged into one --
    numbered by "which division point between which two (or one) original vertices it is", not by comparing coordinates.
    """
    f = max(1, int(freq))
    t = (1.0 + 5.0 ** 0.5) / 2.0
    V = np.array([[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
                  [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]], np.float64)
    F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
         (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
         (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    ids, pts, tris = {}, [], []

    def pid(key, pos):
        if key not in ids:
            ids[key] = len(pts)
            pts.append(pos)
        return ids[key]

    for fi, (a, b, c) in enumerate(F):
        loc = {}
        for i in range(f + 1):
            for j in range(f + 1 - i):
                k = f - i - j                        # barycentric (k, i, j)/f corresponds to vertices (a, b, c)
                w = sorted(((a, k), (b, i), (c, j)))
                nz = [(v, n) for v, n in w if n]
                if len(nz) == 1:
                    key = ("v", nz[0][0])
                elif len(nz) == 2:
                    key = ("e", nz[0][0], nz[1][0], nz[0][1])   # on edge (lower id, higher id), f - n segments from the lower vertex
                else:
                    key = ("f", fi, i, j)
                loc[i, j] = pid(key, (k * V[a] + i * V[b] + j * V[c]) / f)
        for i in range(f):
            for j in range(f - i):
                tris.append((loc[i, j], loc[i + 1, j], loc[i, j + 1]))
                if j < f - i - 1:
                    tris.append((loc[i + 1, j], loc[i + 1, j + 1], loc[i, j + 1]))
    P = np.asarray(pts, np.float64)
    P /= np.linalg.norm(P, axis=1, keepdims=True)
    return P.astype(np.float32), np.asarray(tris, np.int32)


def sphere(radius=1.0, cols=24, rows=16, center=(0, 0, 0), prim_type="polygon_mesh",
           frequency=2, radii=(1, 1, 1), rotate=(0, 0, 0), orientation="y"):
    """
    prim_type = polygon_mesh (default): UV sphere, rows x cols. Each pole has **only one point**.
    prim_type = polygon: icosahedral subdivision sphere, frequency = segments per edge (see _icosphere).
    radius is the overall scale (Houdini's Uniform Scale), radii are the per-axis radii (Houdini's Radius).

    Previously linspace(0, pi, rows) treated the poles as full rows too, so each pole produced cols
    coincident points. The consequence was not just an inflated point count: points near the poles were dragged by those degenerate faces and their averaged normals
    were skewed (measured: 24 points on a sphere had normal z component computed as -0.1), so grouping by normal missed them.
    """
    if prim_type not in SPHERE_TYPES:
        raise ValueError(f"Primitive Type must be one of {SPHERE_TYPES}, got {prim_type!r}")
    xform = lambda U: _place(_orient(U, orientation) * (np.asarray(radii, np.float32) * float(radius)),  # noqa: E731
                             center, rotate)
    if prim_type == "polygon":
        U, T = _icosphere(frequency)
        return Geometry.from_mesh(xform(U), T)
    cols, rows = max(3, int(cols)), max(3, int(rows))
    nring = rows - 2                                   # number of full latitude rings in between
    theta = np.linspace(0, np.pi, rows, dtype=np.float32)[1:-1]
    phi = np.linspace(0, 2 * np.pi, cols, endpoint=False, dtype=np.float32)
    tt, pp = np.meshgrid(theta, phi, indexing="ij")     # (nring, cols)

    ring = np.stack([np.sin(tt) * np.cos(pp),
                     np.cos(tt),
                     np.sin(tt) * np.sin(pp)], -1).reshape(-1, 3)
    P = xform(np.concatenate([[[0, 1, 0]], ring, [[0, -1, 0]]]).astype(np.float32))

    north, south = 0, 1 + nring * cols
    idx = lambda i, j: 1 + i * cols + (j % cols)        # noqa: E731

    faces = []
    for j in range(cols):                              # north pole fan
        faces.append([north, idx(0, j + 1), idx(0, j)])
    for i in range(nring - 1):                         # quads in between
        for j in range(cols):
            faces.append([idx(i, j), idx(i, j + 1),
                          idx(i + 1, j + 1), idx(i + 1, j)])
    for j in range(cols):                              # south pole fan
        faces.append([south, idx(nring - 1, j), idx(nring - 1, j + 1)])
    return Geometry.from_mesh(P, faces)


def line(origin=(0, 0, 0), direction=(0, 1, 0), length=1.0, points=2):
    n = max(2, int(points))
    t = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    d = np.asarray(direction, np.float32)
    d = d / (np.linalg.norm(d) or 1.0)
    P = np.asarray(origin, np.float32) + t * d * length
    g = Geometry.from_mesh(P, [np.arange(n, dtype=np.int32)], closed=False)
    return g


def circle(radius=(1.0, 1.0), center=(0, 0, 0), rotate=(0, 0, 0),
           uniform_scale=1.0, plane="xy", reverse=False, divisions=12,
           arc_type="closed", arc_angles=(0.0, 360.0), filled=None,
           divs=None):
    """
    Counterpart of Houdini's Circle SOP.

    radius is two numbers -- a circle is a special case of an ellipse, and separate values are needed to draw ellipses; Houdini also has
    two fields. plane decides which plane the circle lies in; rotate is an Euler rotation stacked on afterwards.

    arc_type:
        closed      full circle, closed polygon (arc_angles has no effect)
        open_arc    an arc, open polyline
        closed_arc  an arc + a chord closing it (closed face)
        sliced_arc  an arc + two radii back to the centre (a sector, closed face)

    reverse flips the winding -- circles are often used as Sweep cross-sections or PolyExtrude input,
    and with the wrong orientation all normals point inward, so this toggle is needed.

    divs / filled are aliases from the old signature, kept so existing calls don't break.
    """
    if divs is not None:
        divisions = divs
    if filled is not None and arc_type == "closed":
        arc_type = "closed" if filled else "open_arc"
        if not filled:
            arc_angles = (0.0, 360.0)

    n = max(3, int(divisions))
    r = np.asarray(radius, np.float64).reshape(-1)
    if r.size == 1:
        r = np.array([r[0], r[0]], np.float64)
    a0, a1 = float(arc_angles[0]), float(arc_angles[1])

    if arc_type == "closed":
        ang = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    else:
        # Both endpoints of an open arc must land on the given angles, so it is n points and n-1 segments
        ang = np.radians(np.linspace(a0, a1, n))
    x = np.cos(ang) * r[0]
    y = np.sin(ang) * r[1]
    z = np.zeros_like(x)

    if plane == "xy":
        P = np.stack([x, y, z], -1)
    elif plane == "yz":
        P = np.stack([z, x, y], -1)
    else:                                        # zx
        P = np.stack([x, z, y], -1)

    closed = arc_type in ("closed", "closed_arc", "sliced_arc")
    if arc_type == "sliced_arc":                 # add a centre point and connect into a sector
        P = np.concatenate([P, np.zeros((1, 3))])

    P = P * float(uniform_scale)
    if any(abs(float(v)) > 1e-12 for v in rotate):
        from .ops import euler_matrix
        P = P @ euler_matrix(*rotate).T
    P = (P + np.asarray(center, np.float64)).astype(np.float32)

    idx = np.arange(len(P), dtype=np.int32)
    if reverse:
        idx = idx[::-1].copy()
    return Geometry.from_mesh(P, [idx], closed=closed)


def tube(radius1=1.0, radius2=1.0, height=2.0, cols=16, rows=2,
         center=(0, 0, 0), caps=False, rotate=(0, 0, 0), orientation="y", radius_scale=1.0):
    cols, rows = max(3, int(cols)), max(2, int(rows))
    a = np.linspace(0, 2 * np.pi, cols, endpoint=False, dtype=np.float32)
    t = np.linspace(0, 1, rows, dtype=np.float32)
    tt, aa = np.meshgrid(t, a, indexing="ij")
    r = (radius1 * (1 - tt) + radius2 * tt) * float(radius_scale)
    P = np.stack([np.cos(aa) * r,
                  (tt - 0.5) * height,
                  np.sin(aa) * r], -1).reshape(-1, 3)
    P = _place(_orient(P, orientation), center, rotate)

    faces = []
    for i in range(rows - 1):
        for j in range(cols):
            jn = (j + 1) % cols
            faces.append([i * cols + j, (i + 1) * cols + j,
                          (i + 1) * cols + jn, i * cols + jn])
    if caps:
        faces.append(list(range(cols)))                       # bottom cap faces -Y
        faces.append([(rows - 1) * cols + j
                      for j in range(cols)][::-1])            # top cap faces +Y
    return Geometry.from_mesh(P, faces)


def torus(radius=1.0, section_radius=0.3, rows=12, cols=24,
          center=(0, 0, 0), plane="zx"):
    """
    Torus. rows = points around the **cross-section**, cols = points around the **main circle**.

    Both directions are periodic, so both use `endpoint=False`: an extra duplicate point would create a ring of
    zero-area quads along the seam -- the normals there are nan, and it is only visible when the model is turned with the seam
    facing the camera. This is also where the meaning of rows/cols differs slightly from grid/tube: for those two
    rows is the **number of endpoints** (not periodic), here it is the **number of segments** (periodic).

    `plane` is the **plane of the main circle** (default zx = Y-up ground); the cross-section bulges along the remaining
    axis.

    Comes with uv (0-1 in both directions), so a seamless texture applied to it is right straight away.
    """
    rows, cols = max(3, int(rows)), max(3, int(cols))
    R, r = float(radius), float(section_radius)
    th = np.linspace(0, 2 * np.pi, cols, endpoint=False,
                     dtype=np.float64)              # around the main circle
    ph = np.linspace(0, 2 * np.pi, rows, endpoint=False,
                     dtype=np.float64)              # around the cross-section
    PH, TH = np.meshgrid(ph, th, indexing="ij")     # (rows, cols)
    rad = R + r * np.cos(PH)
    a = rad * np.cos(TH)
    b = rad * np.sin(TH)
    h = r * np.sin(PH)
    if plane == "zx":
        P = np.stack([a, h, b], -1)
    elif plane == "xy":
        P = np.stack([a, b, h], -1)
    elif plane == "yz":
        P = np.stack([h, a, b], -1)
    else:
        raise ValueError("plane must be one of zx / xy / yz")
    P = P.reshape(-1, 3).astype(np.float32) + np.asarray(center, np.float32)

    i = np.arange(rows)[:, None]
    j = np.arange(cols)[None, :]
    i1, j1 = (i + 1) % rows, (j + 1) % cols
    faces = np.stack(np.broadcast_arrays(i * cols + j, i1 * cols + j,
                                         i1 * cols + j1, i * cols + j1),
                     -1).reshape(-1, 4).astype(np.int32)
    g = Geometry.from_mesh(P, faces)
    g.set(POINT, "uv", np.stack([TH / (2 * np.pi), PH / (2 * np.pi)],
                                -1).reshape(-1, 2).astype(np.float32))
    return g


def points_from_array(P):
    return Geometry.from_points(P)
