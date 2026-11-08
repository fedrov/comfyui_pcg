"""
pcg81: Shrinkwrap -- the boundary of the region a ball of radius Radius rolling from outside cannot reach (morphological closing).

Checks do not rely on the implementation itself:
  convex input (sphere mesh)   the hull is the input itself: closed manifold, chi = 2, every point lies on the surface (distance ~0), volume difference < 1%
  two boxes 0.4 apart          2r < 0.4 wraps each separately (two pieces, volume = 2); 2r > 0.4 bridges into one piece, volume between 2 and 2.4,
                       points on the bridge all lie in the gap, no farther than r from the input
  L shape                      the fillet radius on the concave edge is exactly r (error < 0.2 voxel), points on the fillet are not snapped to faces, volume =
                       L + r^2(1 - pi/4); the volume increments for r = 0.5 / 1 / 2 = the analytic notch fill (fillet / circular segment)
  weighted JFA                 phi = max_c (d_c - |x - c|) vs brute-force pairwise max: only ever smaller, <= 0.15 voxel
  open box                     hole smaller than the ball: closed manifold; hole larger than the ball: the ball gets in, volume drops below 0.3 (negative control)
  interpenetrating parts       hull = union, inner faces gone, closed manifold
  Offset                       every point is exactly Offset from the input surface
  translate by whole voxels    result translates exactly (grid aligned to world coordinates)
"""
import math
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo import build, ops, hull            # noqa: E402
from comfyui_pcg.geo import shrinkwrap as SW            # noqa: E402
from comfyui_pcg.geo.ops import delete_prims            # noqa: E402
from comfyui_pcg.geo.topology import topology, connectivity  # noqa: E402
from comfyui_pcg.geo.spatial import closest_surface, tri_soup  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM            # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def PP(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def vol(g):
    X = PP(g)
    s = 0.0
    for i in range(g.nprims):
        Y = X[g.prim_points(i)]
        for k in range(1, len(Y) - 1):
            s += np.dot(Y[0], np.cross(Y[k], Y[k + 1])) / 6
    return s


def dist_to(g, src):
    return closest_surface(PP(g), PP(src), tri_soup(src)[0])[1]


def manifold(g):
    t = topology(g)
    chi = g.npoints - t.nedges + g.nprims
    return int(t.boundary.sum()) == 0 and int((t.edge_count > 2).sum()) == 0, chi


def ncomp(g):
    return len(np.unique(np.asarray(connectivity(g).get(POINT, "class"))))


def raises(fn, msg=""):
    try:
        fn()
    except (ValueError, KeyError) as ex:
        return msg in str(ex)
    return False


# ═══════════════════════════════════════════════════════ weighted JFA
print("═" * 28, "weighted JFA")
rng = np.random.default_rng(5)
shp = (14, 11, 17)
Z, Y, X_ = np.meshgrid(*[np.arange(n) for n in shp], indexing="ij")
Cg = np.stack([Z, Y, X_], -1).reshape(-1, 3) * 0.1
# a real distance field as weights: min distance to a few random points (neighbouring cells differ by at most one voxel, as in real use)
anchors = rng.uniform(0, 1.4, (4, 3))
wd = np.linalg.norm(Cg[:, None] - anchors[None], axis=2).min(1).reshape(shp)
seed = wd > 0.35
phi = SW._weighted_jfa(seed, wd, 0.1)
sc = Cg[seed.reshape(-1)]
brute = (wd.reshape(-1)[seed.reshape(-1)][None, :]
         - np.linalg.norm(Cg[:, None] - sc[None], axis=2)).max(1).reshape(shp)
seed2 = seed.copy()
seed2[0, 0, 0] = False
w2 = wd.copy()
w2[0, 0, 0] = 100.0                                    # a cell that is not a seed must never be picked, however large its weight
phi2 = SW._weighted_jfa(seed2, w2, 0.1)
check("  cells that are not seeds do not take part (even with weight 100)", phi2.max() < 5, float(phi2.max()))
err = brute - phi
check("phi = max_c (d_c - |x - c|): JFA vs brute-force pairwise max, only ever smaller (conservative), at most 0.15 voxel, "
      "over 90% of cells match exactly",
      err.min() > -1e-12 and err.max() < 0.015 and (err < 1e-9).mean() > 0.9,
      (float(err.max()), float((err < 1e-9).mean())))

# ═══════════════════════════════════════════════════════ convex
print("═" * 28, "convex input")
sph = build.sphere(1.0, 32, 20)
o, rep = SW.shrinkwrap(sph, 0.05, 0.15)
mf, chi = manifold(o)
d = dist_to(o, sph)
check("sphere mesh: closed manifold, chi = 2, one piece", mf and chi == 2 and ncomp(o) == 1, (mf, chi))
check("  every point lies on the input surface (Project)", d.max() < 1e-6
      and rep["contact_points"] == o.npoints, float(d.max()))
check("  volume difference < 1%", abs(vol(o) / vol(sph) - 1) < 0.01, (vol(o), vol(sph)))
o2, rep2 = SW.shrinkwrap(sph, 0.05, 0.15, project=False, smooth=0)
d2 = dist_to(o2, sph)
check("  without Project: about one voxel off the surface (Project really does something)",
      1e-3 < d2.max() < 0.05, float(d2.max()))
check("  without Project the contact group is empty", rep2["contact_points"] == 0
      and not np.asarray(o2.get_group(POINT, "contact")).any())

# ═══════════════════════════════════════════════════════ two boxes
print("═" * 28, "two boxes 0.4 apart")
two = ops.merge(build.box((1, 1, 1), (-0.7, 0, 0)), build.box((1, 1, 1), (0.7, 0, 0)))
o, rep = SW.shrinkwrap(two, 0.05, 0.1)
check("2r = 0.2 < gap 0.4: each wrapped separately, two pieces, volume = 2 (difference < 1%)",
      ncomp(o) == 2 and abs(vol(o) - 2) < 0.02 and manifold(o)[0], (ncomp(o), vol(o)))
o, rep = SW.shrinkwrap(two, 0.05, 0.3)
check("2r = 0.6 > gap 0.4: bridged into one piece, volume between 2 and 2.4",
      ncomp(o) == 1 and 2.05 < vol(o) < 2.4 and manifold(o)[0], (ncomp(o), vol(o)))
cg = np.asarray(o.get_group(POINT, "contact"))
X = PP(o)
d = dist_to(o, two)
check("  points on the bridge (not in the contact group) all lie in the gap, no farther than r from the input; contact points ~0 from the input",
      (~cg).any() and np.abs(X[~cg, 0]).max() < 0.2 + 0.05
      and d[~cg].max() <= 0.3 + 0.05 and d[cg].max() < 1e-6,
      (int((~cg).sum()), float(np.abs(X[~cg, 0]).max()), float(d[~cg].max())))

# ═══════════════════════════════════════════════════════ L shape
print("═" * 28, "L shape")
L = ops.merge(build.box((2, 1, 1), (0.5, 0, 0)), build.box((1, 2, 1), (0, 0.5, 0)))
o, rep = SW.shrinkwrap(L, 0.05, 0.5)
X = PP(o)
cg = np.asarray(o.get_group(POINT, "contact"))
fil = (X[:, 0] > 0.5) & (X[:, 1] > 0.5) & (np.abs(X[:, 2]) < 0.4)
rr = np.hypot(X[fil, 0] - 1, X[fil, 1] - 1)
check("concave fillet: a ball of radius 0.5 rolling over a 90° concave edge, fillet points are exactly 0.5 from the ball-center line (error < 0.2 voxel)",
      fil.sum() > 50 and np.abs(rr - 0.5).max() < 0.01, (int(fil.sum()), float(np.abs(rr - 0.5).max())))
check("  not a single fillet point is snapped to the faces below (the ball does not fit at the closest point -> no snap)", not cg[fil].any())
area_fil = 0.5 ** 2 * (1 - math.pi / 4)                   # cross-section area filled by the fillet x edge length 1
check("  volume = L + the fillet fill r^2(1 - pi/4) (difference < 1%; the rest is convex edges shaved off by voxelization)",
      abs(vol(o) - (3 + area_fil)) / 3 < 0.01, (vol(o), 3 + area_fil))
vh = vol(hull.convex_hull(L))
rs = (0.1, 0.5, 1.0, 2.0)
vs = [vol(SW.shrinkwrap(L, 0.1, r)[0]) for r in rs]


def fill(r):
    """Volume of a notch (a 1 x 1 square corner, depth 1) filled by a ball of radius r: r <= 1 is a fillet r^2(1 - pi/4);
    r > 1 the ball rests on the two outer corners, and the fill is half the square corner minus a circular segment of radius r"""
    if r <= 1:
        return r * r * (1 - math.pi / 4)
    th = 2 * math.asin(math.sqrt(2) / (2 * r))
    return 0.5 - r * r / 2 * (th - math.sin(th))


# at voxel 0.1 the bit of convex edge shaved off by surface nets is the same amount (independent of r); subtract r = 0.1 as the baseline
dv = [v - vs[0] for v in vs]
da = [fill(r) - fill(rs[0]) for r in rs]
check("volume increment = analytic notch fill (r = 0.5 fillet, r = 1 fillet that exactly fills it, r = 2 circular segment resting on the outer corners)",
      max(abs(a - b) for a, b in zip(dv, da)) < 0.02,
      [(round(a, 4), round(b, 4)) for a, b in zip(dv[1:], da[1:])])
check("  volume strictly increasing with Radius, all below the convex hull (Radius -> inf is the convex hull)",
      all(vs[i] < vs[i + 1] for i in range(3)) and vs[-1] < vh and abs(vh - 3.5) < 1e-9)

# ═══════════════════════════════════════════════════════ open box
print("═" * 28, "open box / separate parts")
b = build.box((1, 1, 1))
top = np.asarray(ops.prim_centers(b))[:, 1] > 0.4
openb = delete_prims(b, ~top)
check("premise: the box lacks its top face, 4 boundary edges", int(topology(openb).boundary.sum()) == 4)
o, rep = SW.shrinkwrap(openb, 0.05, 0.6)
mf, chi = manifold(o)
check("hole (1 x 1) smaller than the ball (diameter 1.2): closed manifold, chi = 2, volume between 0.8 and 1 (the ball presses a dent in the top)",
      mf and chi == 2 and 0.8 < vol(o) < 1.0, (mf, chi, vol(o)))
o, rep = SW.shrinkwrap(openb, 0.05, 0.2)
check("  negative control: a ball (diameter 0.4) smaller than the hole gets in, volume drops below 0.3", vol(o) < 0.3, vol(o))
soup = ops.merge(build.box((1, 1, 1)), build.box((1, 1, 1), (0.5, 0.3, 0.2)))
o, rep = SW.shrinkwrap(soup, 0.05, 0.1)
union = 1 + 1 - 0.5 * 0.7 * 0.8
check("two interpenetrating boxes: hull = union (volume difference < 2%), inner faces gone, closed manifold, one piece",
      abs(vol(o) / union - 1) < 0.02 and manifold(o)[0] and ncomp(o) == 1, (vol(o), union))

# ═══════════════════════════════════════════════════════ Offset / alignment / smoothing
print("═" * 28, "Offset / alignment / smoothing")
o, rep = SW.shrinkwrap(sph, 0.05, 0.2, offset=0.1)
d = dist_to(o, sph)
check("Offset 0.1: every point exactly 0.1 from the input surface", np.abs(d - 0.1).max() < 1e-5, float(np.abs(d - 0.1).max()))
o, _ = SW.shrinkwrap(sph, 0.05, 0.2, offset=0.1, project=False, smooth=0)
d = dist_to(o, sph)
check("  also 0.1 without Project (error < 0.2 voxel) -- the push-out comes from the field, not only from the push during snapping",
      np.abs(d - 0.1).max() < 0.01, float(np.abs(d - 0.1).max()))
bo = build.box((1, 1, 1), (0.013, 0.021, -0.007))
o0, _ = SW.shrinkwrap(bo, 0.05, 0.15, offset=0.002, project=False, smooth=0)
o1, _ = SW.shrinkwrap(bo, 0.05, 0.15, offset=0.002, smooth=0)
m0 = np.abs(PP(o0) - [0.013, 0.021, -0.007]).max(1)
m1 = np.abs(PP(o1) - [0.013, 0.021, -0.007]).max(1)
check("  Offset smaller than the discretization error (0.002): without Project some points fall inside the box; after Project all are outside, exactly 0.002"
      " (points that fell inside are pushed along the outward normal, not along the direction pointing at them)",
      (m0 < 0.5).sum() > 0 and np.abs(m1 - 0.502).max() < 1e-5, ((m0 < 0.5).sum(), float(m1.min())))
sh = ops.transform(two, translate=(0.35, -0.2, 0.15))              # 7 / -4 / 3 voxels
a_, _ = SW.shrinkwrap(two, 0.05, 0.3, project=False, smooth=0)
b_, _ = SW.shrinkwrap(sh, 0.05, 0.3, project=False, smooth=0)
check("translate by whole voxels: topology unchanged, points translated exactly (grid aligned to world coordinates)",
      a_.npoints == b_.npoints and np.abs(PP(b_) - PP(a_) - [0.35, -0.2, 0.15]).max() < 1e-5)
o, rep = SW.shrinkwrap(two, 0.05, 0.3, smooth=5)
cg = np.asarray(o.get_group(POINT, "contact"))
d = dist_to(o, two)
check("after Smooth the contact points are still on the surface, still a closed manifold", d[cg].max() < 1e-6 and manifold(o)[0])
gg = two.copy()
gg.set_group(PRIM, "left", np.asarray(ops.prim_centers(two))[:, 0] < 0)
o, _ = SW.shrinkwrap(gg, 0.05, 0.3, group="left")
check("group: only wraps the primitives in the group (the left box)", ncomp(o) == 1 and PP(o)[:, 0].max() < -0.2 + 0.05
      and abs(vol(o) - 1) < 0.01)
o, rep = SW.shrinkwrap(build.box((1, 1, 1)), 0.05, 0.1, offset=0.1, project=False, smooth=0)
check("Offset = Radius (hull farthest from the surface, outer border keeps only ceil(r / voxel) layers): still closed",
      manifold(o)[0] and rep["resolution"][0] == 1 / 0.05 + 2 * 2 + 1, rep["resolution"])
check("errors: Voxel Size <= 0, Radius <= 0, negative Offset, Offset > Radius, no primitives, too many voxels",
      raises(lambda: SW.shrinkwrap(sph, 0, 0.1))
      and raises(lambda: SW.shrinkwrap(sph, 0.05, -1))
      and raises(lambda: SW.shrinkwrap(sph, 0.05, 0.0), "Radius must be > 0")
      and raises(lambda: SW.shrinkwrap(sph, 0.05, 0.1, offset=-0.01))
      and raises(lambda: SW.shrinkwrap(sph, 0.05, 0.1, offset=0.2))
      and raises(lambda: SW.shrinkwrap(build.line(), 0.05, 0.1))
      and raises(lambda: SW.shrinkwrap(sph, 0.001, 0.1)))

# ═══════════════════════════════════════════════════════ node
N = MAP["PCG_Shrinkwrap"]
kw = {}
for k, spec in N.INPUT_TYPES()["required"].items():
    if k == "geo":
        kw[k] = sph
    elif isinstance(spec[0], list):
        kw[k] = spec[0][0]
    else:
        kw[k] = spec[1]["default"]
r = N().run(**kw)
r = tuple(r["result"]) if isinstance(r, dict) else r
check("node runs with default parameters", r[0].npoints > 0 and manifold(r[0])[0])

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
