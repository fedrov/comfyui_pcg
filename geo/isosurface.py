"""
pcg77: IsoSurface, Remesh to Grid.

━━ IsoSurface
Implicit function f(x, y, z) = 0 -> mesh. The function uses wrangle expression syntax (@P, @P.x, length(),
sin() ...; the Houdini-style $X $Y $Z are accepted too and become @P.x @P.y @P.z). Written over several lines it is a piece of
wrangle code ending with @value = function value (room for intermediate variables, layers of noise, a few max cuts). Evaluated at grid points
in the bounding box by Divisions, with surface nets extracting the iso-surface (quads), positive outside, negative inside (f > 0 is outside).
With Project on, each vertex then takes a few Newton steps along the numerical gradient p <- p - f*grad(f)/|grad(f)|^2, landing on the **true**
iso-surface (in the tests unit-sphere vertices satisfy | |p| - 1 | < 1e-7; without projection the error is on the order of a voxel).
With Normals on, point normals N are written from the gradient (exactly radial on a sphere).
With Output = volume no surface is extracted; the volume is output directly (its value is f; it can feed the Volume family of nodes).

━━ Remesh to Grid
Rebuilds the mesh from voxels: first an exact SDF (same as pcg72's mesh_to_volume); voxels are cubes with edge Voxel Size,
and grid points are aligned to integer multiples of Voxel Size (moving the same object by a whole number of voxels translates the extracted mesh
exactly, with unchanged topology); surface nets yield an **all-quad**, closed mesh. Project moves each vertex back to the
nearest point on the original surface (points all lie on the original surface); Smooth does a few rounds of tangential relaxation + reprojection for more even edge flow. Point attributes are
interpolated from the original mesh using the barycentric coordinates of the nearest point.
Cost: surface nets round off sharp edges (projection pulls points back to the surface, but there are no points at corners to pull) -- for hard surfaces
that must keep their creases use Remesh.
"""
from __future__ import annotations


import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from .volume import make_volume, volume_to_polygons, signed_distance

ISO_OUTPUTS = ("polygons", "volume")


def _expr(expr):
    s = str(expr)
    for a, b in (("$X", "@P.x"), ("$Y", "@P.y"), ("$Z", "@P.z")):
        s = s.replace(a, b)
    if not s.strip():
        raise ValueError("Expression is empty (e.g. length(@P) - 1)")
    return s


def _eval(expr, Q):
    from .wrangle import eval_value, run_wrangle
    g = Geometry.from_points(np.zeros((len(Q), 3), np.float32))
    g.set(POINT, "P", np.asarray(Q, np.float64))
    if "\n" in expr.strip():
        # Multi-line = a piece of code (intermediate variables, a few max / min SDF combinations), ending with @value.
        # A single-line expression can't hold real modelling: rock = ellipsoid + three layers of noise + two cuts, unreadable on one line
        r = run_wrangle(g, expr, POINT)
        v = r.get(POINT, "value")
        if v is None:
            raise ValueError("A multi-line Expression must end with @value = ... (function value, positive outside, negative inside)")
        return np.asarray(v, np.float64)[:, 0]
    return eval_value(g, expr, POINT, ncomp=1)[:, 0]


def _grad(expr, X, h):
    cols = []
    for k in range(3):
        d = np.zeros(3)
        d[k] = h
        cols.append((_eval(expr, X + d) - _eval(expr, X - d)) / (2 * h))
    return np.stack(cols, 1)


def isosurface(bound_min=(-1.5, -1.5, -1.5), bound_max=(1.5, 1.5, 1.5),
               divisions=(48, 48, 48), expression="length(@P) - 1",
               iso=0.0, project=True, normals=True, output="polygons"):
    """See the file header. Returns (geometry, report)."""
    if output not in ISO_OUTPUTS:
        raise ValueError(f"Output must be one of {ISO_OUTPUTS}")
    ex = _expr(expression)
    lo = np.asarray(bound_min, np.float64)
    hi = np.asarray(bound_max, np.float64)
    if not (hi > lo).all():
        raise ValueError("Every component of Bound Max must be greater than Bound Min")
    res = np.maximum(np.asarray(divisions, np.int64), 1) + 1      # number of grid points
    size = hi - lo
    cell = size / (res - 1)
    xs = [lo[k] + cell[k] * np.arange(res[k]) for k in range(3)]
    Z, Y, X = np.meshgrid(xs[2], xs[1], xs[0], indexing="ij")
    Q = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
    val = _eval(ex, Q).reshape(Z.shape) - float(iso)
    vol = make_volume(tuple(int(r) for r in res), size, lo + size / 2)
    vol.set_pdata(0, "voxels", val.astype(np.float32))
    rep = {"voxels": int(val.size), "cell": [float(c) for c in cell]}
    if output == "volume":
        return vol, rep
    g = volume_to_polygons(vol, 0.0)
    rep["points"], rep["prims"] = int(g.npoints), int(g.nprims)
    if not g.npoints:
        return g, rep
    P = np.asarray(g.get(POINT, "P"), np.float64)
    h = 1e-3 * float(cell.min())
    if project:
        for _ in range(8):
            f = _eval(ex, P) - float(iso)
            G = _grad(ex, P, h)
            gg = np.einsum("ij,ij->i", G, G)
            step = np.where(gg > 1e-300, f / np.where(gg > 1e-300, gg, 1.0), 0.0)
            # No step limit: surface nets vertices are less than a voxel from the iso-surface, and the Newton step is that distance;
            # tried a cone tip (zero gradient), a triple root, two roots in one cell and a steep sine: the step never exceeded
            # one voxel, so the old "at most one voxel per step" clamp was redundant and has been removed
            P = P - step[:, None] * G
            if np.abs(f).max() < 1e-12:
                break
        rep["max_residual"] = float(np.abs(_eval(ex, P) - float(iso)).max())
    g.set(POINT, "P", P.astype(np.float32), owned=True)
    if normals:
        G = _grad(ex, P, h)
        G /= np.maximum(np.linalg.norm(G, axis=1, keepdims=True), 1e-300)
        g.set(POINT, "N", G.astype(np.float32), owned=True)
    return g, rep


# ═══════════════════════════════════════════════════════════ Remesh to Grid
def _relax(V, F, movable, lam):
    from .remesh import _relax as rr
    return rr(V, F, movable, lam)


def remesh_to_grid(geo, voxel_size=0.1, project=True, smooth=2,
                   smooth_strength=0.5, transfer_attributes=True, group=""):
    from . import spatial as _sp
    from .groups import resolve
    from .ops import delete_prims
    vs = float(voxel_size)
    if not vs > 0:
        raise ValueError("Voxel Size must be > 0")
    sel = resolve(geo, PRIM, group)
    src = delete_prims(geo, sel) if not sel.all() else geo
    tri, _, _ = _sp.tri_soup(src)
    if not len(tri):
        raise ValueError("No polygons to rebuild")
    P0 = np.asarray(src.get(POINT, "P"), np.float64)
    used = np.unique(tri)
    mn = np.floor(P0[used].min(0) / vs) - 2
    mx = np.ceil(P0[used].max(0) / vs) + 2
    res = (mx - mn + 1).astype(np.int64)
    if np.prod(res) > 400 ** 3:
        raise ValueError(f"Too many voxels ({res.tolist()}); increase Voxel Size")
    origin = mn * vs
    cell = np.full(3, vs)
    sdf = signed_distance(P0, tri.astype(np.int64), origin, cell,
                          tuple(int(r) for r in res), 2.5)
    # When the surface passes exactly through grid points (object faces at integer multiples of the voxel size, e.g. a 1 m box with 0.1 voxels)
    # those grid points have value 0, and surface nets get ambiguous cells on edges and corners ("two diagonal cells with the same sign"),
    # producing non-manifold edges shared by four faces. Pushing every tiny |d| slightly outwards removes the ambiguity
    tiny = 1e-6 * vs
    sdf = np.where(np.abs(sdf) < tiny, tiny, sdf)
    size = (res - 1) * vs
    vol = make_volume(tuple(int(r) for r in res), size, origin + size / 2)
    vol.set_pdata(0, "voxels", sdf.astype(np.float32))
    g = volume_to_polygons(vol, 0.0)
    rep = {"resolution": res.tolist()}
    if not g.npoints:
        rep["points"] = 0
        return g, rep
    V = np.asarray(g.get(POINT, "P"), np.float64)
    F4 = np.asarray(g.vertex_point, np.int64).reshape(-1, 4)
    # Smooth and Project are independent (same as Shrinkwrap): both on = one round of relaxation, one round of projection back;
    # only Smooth = tangential relaxation (points spread evenly over the surface without projection, drifting slightly off the original surface).
    # Before pcg90, turning Project off disabled Smooth entirely
    F3 = np.concatenate([F4[:, [0, 1, 2]], F4[:, [0, 2, 3]]])
    if project:
        _, _, V, _ = _sp.closest_surface(V, P0, tri)
    for _ in range(max(0, int(smooth))):
        V = _relax(V, F3, np.ones(len(V), bool), float(smooth_strength))
        if project:
            _, _, V, _ = _sp.closest_surface(V, P0, tri)
    if project:
        d = _sp.closest_surface(V, P0, tri)
        rep["max_distance"] = float(np.linalg.norm(d[2] - V, axis=1).max())
    out = g.copy()
    out.set(POINT, "P", V.astype(np.float32), owned=True)
    if transfer_attributes:
        ti, _, _, uv = _sp.closest_surface(V, P0, tri)
        w = np.stack([1 - uv[:, 0] - uv[:, 1], uv[:, 0], uv[:, 1]], 1)
        sp = tri[np.maximum(ti, 0)]
        for k, v in src.attribs[POINT].items():
            if k in ("P", "N") or is_string(v):
                continue
            vv = np.asarray(v, np.float64)
            val = (vv[sp] * w[:, :, None]).sum(1)
            out.set(POINT, k, (np.rint(val) if v.dtype.kind in "iub" else val)
                    .astype(v.dtype), owned=True)
    from .topology import topology
    t = topology(out)
    rep.update({"points": int(out.npoints), "prims": int(out.nprims),
                "nonmanifold_edges": int((t.edge_count > 2).sum())})
    return out, rep
