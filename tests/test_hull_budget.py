"""
pcg111: Convex Decomposition "Max Hull Points" (geo/hull.reduce_hull_points): a vertex budget per collision hull.

The reduced hull is a subset of the full hull's vertices, so it lies inside it; the reported error is the distance of
the farthest point left outside; more points never make it worse; a cube's 8 corners are found exactly. On the node,
every hull keeps at most the budget (32 points -> at most 60 triangles, under Unity's 255) and 0 is the old result.
"""
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP  # noqa: E402
from comfyui_pcg.geo import build  # noqa: E402
from comfyui_pcg.geo import hull as H  # noqa: E402
from comfyui_pcg.geo.core import POINT  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and not extra else "   " + str(extra)))


def planes(Q):
    tri = H.convex_hull_indices(Q)
    A, B, C = (Q[tri[:, j]] for j in range(3))
    N = np.cross(B - A, C - A)
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    return N, np.einsum("ij,ij->i", N, A)


def outside(P, Q):
    """Largest distance of points P outside the hull of Q (<= 0: all inside)."""
    N, off = planes(Q)
    return float((P @ N.T - off).max())


print("\n[reduce_hull_points]")
r = np.random.default_rng(5)
P = r.normal(size=(4000, 3)) * [1.2, 0.6, 0.9]
full = P[np.unique(H.convex_hull_indices(P))]
errs = {}
for k in (8, 16, 32, 64):
    idx, err = H.reduce_hull_points(full, k)
    Q = full[idx]
    errs[k] = err
    if k == 32:
        q32 = Q
        e_true = outside(full, Q)
        sub = all((np.abs(full - q).sum(1) == 0).any() for q in Q)
        inside = outside(Q, full) <= 1e-9
        check("32: at most 32 points, all of them points of the input (a subset)", len(Q) <= 32 and sub, len(Q))
        check("  ... so the reduced hull is inside the full hull (never grows)", inside)
        check("  the reported error is the farthest input point outside the reduced hull",
              abs(e_true - err) < 1e-9, (round(err, 4), round(e_true, 4)))
ks = sorted(errs)
check("more points never make it worse (8 → 16 → 32 → 64), and 32 points stay within 10 % of the size",
      all(errs[a] >= errs[b] - 1e-12 for a, b in zip(ks, ks[1:])) and errs[32] < 0.1 * 2.4,
      {k: round(v, 3) for k, v in errs.items()})
check("  negative control: 8 points is clearly worse than 64", errs[8] > 2 * errs[64])
cube = np.concatenate([np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float),
                       r.uniform(0, 1, (300, 3)),
                       np.c_[r.uniform(0, 1, (200, 2)), np.zeros(200)]])
idx, err = H.reduce_hull_points(cube, 8)
check("a cube with points inside and on its faces: budget 8 finds the 8 corners, error 0",
      sorted(map(tuple, cube[idx].tolist())) == sorted((x, y, z) for x in (0., 1.) for y in (0., 1.) for z in (0., 1.))
      and err < 1e-9)
idx0, e0 = H.reduce_hull_points(full, 0)
check("budget 0 or a budget above the count keeps everything",
      len(idx0) == len(full) and e0 == 0 and len(H.reduce_hull_points(full, 10 ** 6)[0]) == len(full))

print("\n[Convex Decomposition node]")
sph = build.sphere(radius=1.0, cols=48, rows=32)
geo = sph.copy()
Pm = geo.get(POINT, "P").copy()
Pm[:, 1] *= 0.6
geo.set(POINT, "P", Pm)
node = MAP["PCG_ConvexDecompose"]()


def run(**kw):
    out = node.run(geo, **kw)
    return (out["result"] if isinstance(out, dict) else out)[0]


base = dict(mode="hull", max_concavity=0.05, max_pieces=4, resolution=8, split_axes="oriented",
            min_fraction=0.02, cap_mode="ngon", tolerance=1e-5, piece_attribute="piece",
            name_attribute="name", name_prefix="convex")
old = run(**base)
same = run(**base, max_hull_points=0)
check("Max Hull Points 0 = the old result, bit for bit",
      np.array_equal(old.get(POINT, "P"), same.get(POINT, "P")) and old.nprims == same.nprims)
new = run(**base, max_hull_points=32)
pc = new.get("prim", "piece")[:, 0]
counts = []
for p in np.unique(pc):
    sel = np.nonzero(pc == p)[0]
    pts = np.unique(np.concatenate([new.prim_points(i) for i in sel]))
    counts.append(len(pts))
check("Max Hull Points 32: every hull has at most 32 points (at most 60 triangles)", max(counts) <= 32, counts)
check("  negative control: without the budget the ellipsoid's hull has hundreds of points",
      old.npoints > 300, old.npoints)
Pn = new.get(POINT, "P").astype(np.float64)
check("  and the reduced hull lies inside the original's (all its points are on the ellipsoid)",
      np.abs(Pn[:, 0] ** 2 + (Pn[:, 1] / 0.6) ** 2 + Pn[:, 2] ** 2 - 1).max() < 1e-4)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
