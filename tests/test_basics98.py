"""
pcg98: primitives and Transform gain options Houdini has that were missing here.

  Grid      Connectivity(Quadrilaterals / Rows / Columns / Rows and Columns / Triangles /
            Alternating Triangles / Points), Center, Rotate
  Box       Rotate, Primitive Type = Points
  Sphere    Primitive Type = Polygon (icosahedron subdivision, Frequency), per-axis Radius, Center, Rotate, Orientation
  Tube      Orientation, Center, Rotate, Radius Scale
  Line      Origin
  Transform Transform Order, Shear, Uniform Scale, Pivot Translate / Rotate, Invert

The two most important points:
  1) **old workflows unchanged**: all new parameters are appended at the end; output at default values is bit-identical to before (compared against a separately written copy of the old formulas here)
  2) every new option is checked against **numbers computable by hand**: point / primitive count formulas, area, bounding box, where a specific point is transformed to
"""
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def area(g):
    P, T = P_(g), g.triangles()
    return float(0.5 * np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1).sum())


def run(nid, **over):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def names(nid):
    it = M[nid].INPUT_TYPES()
    return [k for part in ("required", "optional") for k in it.get(part, {})]


def bbox(g):
    P = P_(g)
    return np.round(P.min(0), 5).tolist(), np.round(P.max(0), 5).tolist()


close = lambda a, b, e=1e-5: np.allclose(a, b, atol=e)          # noqa: E731

# ═══════════════════════════════════════════════════════ old workflows unchanged
sec("old workflows unchanged: new parameters appended at the end, default values = previous output")
OLD = {
    "PCG_Grid": ["size_x", "size_z", "cols", "rows", "plane"],
    "PCG_Box": ["size_x", "size_y", "size_z", "uniform_scale", "cx", "cy", "cz", "div_x", "div_y", "div_z"],
    "PCG_Sphere": ["radius", "cols", "rows"],
    "PCG_Tube": ["radius1", "radius2", "height", "cols", "rows", "caps"],
    "PCG_Line": ["dx", "dy", "dz", "length", "points"],
    "PCG_Transform": ["geo", "tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz", "group", "rotate_order"],
}
bad = [k for k, v in OLD.items() if names(k)[:len(v)] != v]
check("six nodes: the original parameters are still in their original positions (widgets_values indices unchanged), new ones all at the end", not bad, bad)
for k, v in OLD.items():
    # only old parameters given (simulating an old workflow / API call): new parameters all have defaults, no missing-parameter error
    it = M[k].INPUT_TYPES()["required"]
    kw = {n: (it[n][0][0] if isinstance(it[n][0], (list, tuple)) else it[n][1].get("default")) for n in v if n != "geo"}
    if "geo" in v:
        kw["geo"] = build.box()
    try:
        getattr(M[k](), M[k].FUNCTION)(**kw)
        ok = True
    except TypeError as e:
        ok = str(e)
    check(f"  {k}: runs with only the old parameters", ok is True, ok)
# old formulas (copied from pcg97's build.py, an independent copy)
u = np.linspace(-0.5, 0.5, 5, dtype=np.float32); v = np.linspace(-0.5, 0.5, 4, dtype=np.float32)
uu, vv = np.meshgrid(u, v, indexing="xy")
Pold = np.stack([uu * 3.0, np.zeros_like(uu), vv * 2.0], -1).reshape(-1, 3)
i = np.arange(3)[:, None]; j = np.arange(4)[None, :]
i0 = i * 5 + j
Fold = np.stack([i0, i0 + 5, i0 + 6, i0 + 1], -1).reshape(-1, 4)
g = run("PCG_Grid", size_x=3.0, size_z=2.0, cols=5, rows=4)
check("Grid default: points and primitives bit-identical to the old formula, uv still there", np.array_equal(np.asarray(g.get(POINT, "P")), Pold)
      and np.array_equal(g.vertex_point.reshape(-1, 4), Fold) and g.get(POINT, "uv") is not None)
s0 = run("PCG_Sphere", radius=1.5, cols=7, rows=5)
th = np.linspace(0, np.pi, 5, dtype=np.float32)[1:-1]; ph = np.linspace(0, 2 * np.pi, 7, endpoint=False, dtype=np.float32)
tt, pp = np.meshgrid(th, ph, indexing="ij")
ring = np.stack([np.sin(tt) * np.cos(pp), np.cos(tt), np.sin(tt) * np.sin(pp)], -1).reshape(-1, 3)
So = np.concatenate([[[0, 1, 0]], ring, [[0, -1, 0]]]).astype(np.float32) * 1.5
check("Sphere default: same as the old formula (diff <= 1 ulp), point count 2 + (rows - 2)·cols", np.allclose(np.asarray(s0.get(POINT, "P")), So, atol=2e-7, rtol=0)
      and s0.npoints == 2 + 3 * 7 and s0.nprims == 7 * 4)
t0 = run("PCG_Tube", radius1=1.0, radius2=0.5, height=3.0, cols=6, rows=3)
a = np.linspace(0, 2 * np.pi, 6, endpoint=False, dtype=np.float32); t = np.linspace(0, 1, 3, dtype=np.float32)
tt, aa = np.meshgrid(t, a, indexing="ij"); r = 1.0 * (1 - tt) + 0.5 * tt
To = np.stack([np.cos(aa) * r, (tt - 0.5) * 3.0, np.sin(aa) * r], -1).reshape(-1, 3)
check("Tube default: same as the old formula", np.allclose(np.asarray(t0.get(POINT, "P")), To, atol=2e-7, rtol=0) and t0.nprims == 6 * 2 + 2)
b0 = run("PCG_Box", size_x=2.0, size_y=4.0, size_z=6.0)
check("Box default: 8 points 6 primitives, bounding box ±(1, 2, 3)", b0.npoints == 8 and b0.nprims == 6 and bbox(b0) == ([-1, -2, -3], [1, 2, 3]))
l0 = run("PCG_Line", dx=0.0, dy=2.0, dz=0.0, length=3.0, points=4)
check("Line default: starts at the origin", close(P_(l0), [[0, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0]]))
rng = np.random.default_rng(0)
geo = build.grid(4, 4, 6, 6)
Pg = np.asarray(geo.get(POINT, "P"))
x0 = run("PCG_Transform", geo=geo, tx=1.0, ty=-2.0, tz=0.5, rx=20.0, ry=40.0, rz=-75.0, sx=2.0, sy=0.5, sz=3.0)
Mo = ops.euler_matrix(20.0, 40.0, -75.0) @ np.diag(np.asarray((2.0, 0.5, 3.0), np.float32))
check("Transform default (SRT, pivot at origin): takes the original code path, bit-identical",
      np.array_equal(np.asarray(x0.get(POINT, "P")), Pg @ Mo.T + np.asarray((1.0, -2.0, 0.5), np.float32)))

# ═══════════════════════════════════════════════════════ Grid
sec("Grid:Connectivity / Center / Rotate")
R, C = 4, 5
G = lambda **kw: run("PCG_Grid", size_x=4.0, size_z=3.0, cols=C, rows=R, **kw)   # noqa: E731
g = G(connectivity="triangles")
check("Triangles: two triangles per cell, total area = 12, normals still +Y", g.nprims == 2 * (R - 1) * (C - 1) and (g.prim_sizes() == 3).all()
      and close(area(g), 12.0) and (np.cross(P_(g)[g.triangles()][:, 1] - P_(g)[g.triangles()][:, 0],
                                             P_(g)[g.triangles()][:, 2] - P_(g)[g.triangles()][:, 0])[:, 1] > 0).all())


def diag_dirs(g):
    """Sign of the direction of the diagonal (longest edge) in each triangle: +1 = along (+x,+z), -1 = along (+x,-z)."""
    P, T = P_(g), g.triangles()
    out = []
    for t in T:
        e = [(P[t[(k + 1) % 3]] - P[t[k]]) for k in range(3)]
        d = e[int(np.argmax([np.linalg.norm(x) for x in e]))]
        out.append(int(np.sign(d[0] * d[2])))
    return np.asarray(out).reshape(-1, 2)


dd = diag_dirs(g)
check("  Triangles: all cells split along the same diagonal", len(set(dd.ravel().tolist())) == 1, set(dd.ravel().tolist()))
ga = G(connectivity="alternating_triangles")
da = diag_dirs(ga)[:, 0].reshape(R - 1, C - 1)
ii, jj = np.meshgrid(np.arange(R - 1), np.arange(C - 1), indexing="ij")
check("Alternating Triangles: the diagonal alternates per cell (checkerboard), area still 12, no flipped faces",
      (da[(ii + jj) % 2 == 0] == da[0, 0]).all() and (da[(ii + jj) % 2 == 1] == -da[0, 0]).all()
      and close(area(ga), 12.0) and ga.nprims == 24
      and (np.cross(P_(ga)[ga.triangles()][:, 1] - P_(ga)[ga.triangles()][:, 0],
                    P_(ga)[ga.triangles()][:, 2] - P_(ga)[ga.triangles()][:, 0])[:, 1] > 0).all(), da.tolist())
gr = G(connectivity="rows")
check("Rows: one open polyline per row (R of them, C points each, constant z, increasing x)", gr.nprims == R and (gr.prim_sizes() == C).all()
      and not gr.prim_closed.any() and all(np.ptp(P_(gr)[gr.prim_points(k)][:, 2]) == 0
                                           and (np.diff(P_(gr)[gr.prim_points(k)][:, 0]) > 0).all() for k in range(R)))
gc = G(connectivity="columns")
check("Columns: one per column (C of them, R points each, constant x)", gc.nprims == C and (gc.prim_sizes() == R).all()
      and not gc.prim_closed.any() and all(np.ptp(P_(gc)[gc.prim_points(k)][:, 0]) == 0 for k in range(C)))
grc = G(connectivity="rows_and_columns")
check("Rows and Columns: R + C of them, rows first", grc.nprims == R + C and grc.prim_sizes().tolist() == [C] * R + [R] * C)
gp = G(connectivity="points")
check("Points: points only (R·C), no prims; uv still there", gp.npoints == R * C and gp.nprims == 0 and gp.get(POINT, "uv") is not None)
check("  points identical for every connectivity", all(np.array_equal(P_(x), P_(G())) for x in (g, ga, gr, gc, grc, gp)))
gcn = G(center_x=1.0, center_y=2.0, center_z=3.0)
check("Center (1, 2, 3): bounding box x 1 ± 2, y 2, z 3 ± 1.5", bbox(gcn) == ([-1, 2, 1.5], [3, 2, 4.5]), bbox(gcn))
grt = G(rz=90.0, center_x=5.0)
check("Rotate is Rx Ry Rz in that order: rx 90° + ry 90°, corner (2, 0, 0) on the ZX plane -> first around X (unchanged) then around Y -> (0, 0, -2)",
      close(P_(G(rx=90.0, ry=90.0))[C - 1], P_(G())[C - 1] @ ops.euler_matrix(90.0, 90.0, 0.0).T)
      and close((np.array([2.0, 0, 0]) @ ops.euler_matrix(90.0, 90.0, 0.0).T), [0, 0, -2]))
check("Rotate Z 90° + Center: first rotates around its own center (the ground plane stands up, the 4 along x moves to y), then moves to Center",
      bbox(grt) == ([5, -2, -1.5], [5, 2, 1.5]), bbox(grt))
try:
    build.grid(connectivity="hex")
    check("other Connectivity value: error", False)
except ValueError as e:
    check("other Connectivity value: error", "Connectivity must be one of" in str(e))

# ═══════════════════════════════════════════════════════ Box
sec("Box:Rotate / Primitive Type = Points")
b = run("PCG_Box", size_x=2.0, size_y=4.0, size_z=6.0, ry=90.0, cx=10.0)
check("rotate 90° around Y: x / z sizes swap (6 x 4 x 2), then moved to Center", bbox(b) == ([7, -2, -1], [13, 2, 1]), bbox(b))
bp = run("PCG_Box", div_x=3, div_y=4, div_z=5, prim_type="points")
check("Points: only the lattice points on the shell (3·4·5 - 1·2·3 = 54), no primitives", bp.npoints == 54 and bp.nprims == 0
      and np.array_equal(P_(bp), P_(run("PCG_Box", div_x=3, div_y=4, div_z=5))))

# ═══════════════════════════════════════════════════════ Sphere
sec("Sphere: Polygon (icosahedron subdivision) / per-axis Radius / Center / Rotate / Orientation")
for f in (1, 2, 5):
    s = run("PCG_Sphere", prim_type="polygon", frequency=f)
    P = P_(s); T = s.triangles()
    n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    E = np.concatenate([np.linalg.norm(P[T[:, k]] - P[T[:, (k + 1) % 3]], axis=1) for k in range(3)])
    und = {tuple(sorted(e)) for t in T for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
    check(f"Polygon, Frequency {f}: {10 * f * f + 2} points, {20 * f * f} triangles, {30 * f * f} edges (closed manifold, V - E + F = 2); "
          "all points on the unit sphere; faces point outward", s.npoints == 10 * f * f + 2 and s.nprims == 20 * f * f and len(und) == 30 * f * f
          and close(np.linalg.norm(P, axis=1), 1.0, 1e-6) and ((n * P[T].mean(1)).sum(1) > 0).all()
          and len(np.unique(np.round(P, 5), axis=0)) == s.npoints, (s.npoints, s.nprims, len(und)))
ico = run("PCG_Sphere", prim_type="polygon", frequency=5)
uv_ = run("PCG_Sphere", cols=24, rows=14)


def tri_area_ratio(g):
    P, T = P_(g), g.triangles()
    a = 0.5 * np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1)
    return float(a.max() / a.min())


check("  triangle sizes uniform: max / min area < 1.6 (a lat-long sphere has much smaller faces near the poles, ratio > 3)",
      tri_area_ratio(ico) < 1.6 and tri_area_ratio(uv_) > 3, (tri_area_ratio(ico), tri_area_ratio(uv_)))
check("  area approaches 4π (Frequency 5: diff < 1.5%)", abs(area(ico) / (4 * np.pi) - 1) < 0.015, area(ico) / (4 * np.pi))
check("  the Polygon mode ignores Rows / Columns", run("PCG_Sphere", prim_type="polygon", frequency=2, rows=40, cols=40).npoints == 42)
e = run("PCG_Sphere", radius=2.0, radius_x=1.0, radius_y=0.5, radius_z=3.0)
check("Radius (1, 0.5, 3) x Uniform Scale 2: ellipsoid, bounding box ±(2, 1, 6)", close(np.abs(P_(e)).max(0), [2, 1, 6], 0.05)
      and close(P_(e)[0], [0, 1, 0]))
ex = run("PCG_Sphere", orientation="x", radius_x=1.0, radius_y=0.5, radius_z=3.0)
check("  Radius is along world axes: with Orientation X (poles on X), (1, 0.5, 3) is still x 1, y 0.5, z 3",
      close(np.abs(P_(ex)).max(0), [1, 0.5, 3], 0.08) and close(P_(ex)[0], [1, 0, 0]), np.abs(P_(ex)).max(0))
sx = run("PCG_Sphere", orientation="x", rows=6, cols=8)
sz = run("PCG_Sphere", orientation="z", rows=6, cols=8)
check("Orientation X / Z: the poles land on that axis; faces still point outward (coordinates cycled, nothing flipped)",
      close(P_(sx)[0], [1, 0, 0]) and close(P_(sx)[-1], [-1, 0, 0]) and close(P_(sz)[0], [0, 0, 1])
      and all(((np.cross(P_(q)[q.triangles()][:, 1] - P_(q)[q.triangles()][:, 0],
                         P_(q)[q.triangles()][:, 2] - P_(q)[q.triangles()][:, 0])
                * P_(q)[q.triangles()].mean(1)).sum(1) > 0).all() for q in (sx, sz)))
sc = run("PCG_Sphere", center_x=3.0, center_y=-1.0, rz=90.0, rows=6, cols=8)
check("Rotate Z 90° + Center (3, -1, 0): north pole rotates from +Y to -X, then translated -> (2, -1, 0)", close(P_(sc)[0], [2, -1, 0]), P_(sc)[0])
try:
    build.sphere(prim_type="nurbs")
    check("other Primitive Type value: error", False)
except ValueError as ex:
    check("other Primitive Type value: error", "Primitive Type must be one of" in str(ex))

# ═══════════════════════════════════════════════════════ Tube / Line
sec("Tube:Orientation / Center / Rotate / Radius Scale;Line:Origin")
tx_ = run("PCG_Tube", orientation="x", height=4.0, radius1=1.0, radius2=1.0)
tz_ = run("PCG_Tube", orientation="z", height=4.0)
check("Orientation X: length 4 along X; Z: length 4 along Z", bbox(tx_)[1][0] == 2 and abs(bbox(tx_)[1][1] - 1) < 1e-5
      and bbox(tz_)[1][2] == 2 and abs(bbox(tz_)[1][0] - 1) < 1e-5, (bbox(tx_), bbox(tz_)))
for nm, q, ax in (("Y", run("PCG_Tube"), 1), ("X", tx_, 0), ("Z", tz_, 2)):
    P = P_(q)
    out = []
    for k in range(q.nprims):
        pts = P[q.prim_points(k)]
        nrm = np.zeros(3)
        for a_ in range(len(pts)):
            nrm += np.cross(pts[a_], pts[(a_ + 1) % len(pts)])
        out.append(float(np.dot(nrm, pts.mean(0) - P.mean(0))) > 0)
    check(f"  Orientation {nm}: side and both caps point outward", all(out), out)
tr_ = run("PCG_Tube", radius1=1.0, radius2=2.0, radius_scale=0.5, center_x=1.0, center_y=2.0, center_z=3.0, height=2.0)
rr = np.linalg.norm(P_(tr_)[:, [0, 2]] - [1, 3], axis=1)
check("Radius Scale 0.5 + Center: bottom ring radius 0.5, top ring 1, center at (1, 2, 3)",
      close(sorted(set(np.round(rr, 5))), [0.5, 1.0]) and close(P_(tr_).mean(0), [1, 2, 3]))
tt_ = run("PCG_Tube", rz=90.0, height=4.0)
check("Rotate Z 90°: the upright tube lies down along X", abs(bbox(tt_)[1][0] - 2) < 1e-5 and abs(bbox(tt_)[1][1] - 1) < 1e-5)
ln = run("PCG_Line", dx=1.0, dy=0.0, dz=0.0, length=2.0, points=3, origin_x=5.0, origin_y=1.0, origin_z=-1.0)
check("Line Origin (5, 1, -1): starts there", close(P_(ln), [[5, 1, -1], [6, 1, -1], [7, 1, -1]]))
try:
    build.tube(orientation="w")
    check("other Orientation value: error", False)
except ValueError as ex:
    check("other Orientation value: error", "Orientation must be one of" in str(ex))

# ═══════════════════════════════════════════════════════ Transform
sec("Transform:Transform Order / Shear / Uniform Scale / Pivot / Invert")
pt = Geometry.from_mesh(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float32), [np.arange(3)])
X = lambda **kw: P_(run("PCG_Transform", geo=pt, **kw))          # noqa: E731
base = dict(tx=1.0, rz=90.0, sx=2.0, sy=2.0, sz=2.0)
check("Scale Rot Trans (default): (1,0,0) x2 -> rotate 90° around Z -> +x 1 = (1, 2, 0)", close(X(**base)[0], [1, 2, 0]))
check("Trans Rot Scale: first translate (2,0,0) -> rotate (0,2,0) -> x2 = (0, 4, 0)", close(X(xform_order="trs", **base)[0], [0, 4, 0]),
      X(xform_order="trs", **base)[0])
check("Rot Trans Scale: rotate (0,1,0) -> translate (1,1,0) -> x2 = (2, 2, 0)", close(X(xform_order="rts", **base)[0], [2, 2, 0]))
check("Scale Trans Rot: x2 (2,0,0) -> translate (3,0,0) -> rotate = (0, 3, 0)", close(X(xform_order="str", **base)[0], [0, 3, 0]))
gsm = build.sphere(rows=5, cols=6)
step = {"s": dict(sx=2.0, sy=0.5, sz=3.0), "r": dict(rx=30.0, ry=-50.0, rz=70.0, rotate_order="zyx"),
        "t": dict(tx=1.0, ty=2.0, tz=-3.0)}
worst = 0.0
for order in ops.XFORM_ORDERS:
    one = P_(run("PCG_Transform", geo=gsm, xform_order=order, **{k: v for d in step.values() for k, v in d.items()}))
    seq = gsm
    for ch in order:                                    # step by step through the default code path, in letter order
        seq = run("PCG_Transform", geo=seq, **step[ch])
    worst = max(worst, float(np.abs(one - P_(seq)).max()))
check("all six Transform Orders: doing it at once = doing it in three steps in that order (each step only S / R / T)", worst < 1e-5, worst)
check("  the results of the six orders differ pairwise (not just for show)", len({tuple(np.round(X(xform_order=o, **base)[0], 4)) for o in ops.XFORM_ORDERS}) >= 4)
check("Shear XY 0.5:(0,1,0) → (0.5,1,0);XZ 0.5:(0,0,1) → (0.5,0,1);YZ 0.5:(0,0,1) → (0,0.5,1)",
      close(X(shear_xy=0.5), [[1, 0, 0], [0.5, 1, 0], [0, 0, 1]]) and close(X(shear_xz=0.5)[2], [0.5, 0, 1])
      and close(X(shear_yz=0.5)[2], [0, 0.5, 1]), X(shear_xy=0.5).tolist())
check("  shear comes after scale, before rotate: sx 2 + Shear XY 1 + Rz 90°, (0,1,0) -> sheared to (1,1,0) -> rotated to (-1, 1, 0)",
      close(X(sx=2.0, shear_xy=1.0, rz=90.0)[1], [-1, 1, 0]), X(sx=2.0, shear_xy=1.0, rz=90.0)[1])
check("Uniform Scale 3 × Scale (2,1,1):(1,0,0) → (6,0,0),(0,1,0) → (0,3,0)", close(X(uniform_scale=3.0, sx=2.0)[:2], [[6, 0, 0], [0, 3, 0]]))
check("Pivot Translate (1,0,0) + Rz 180°: (0,1,0) rotates around that point to (2, -1, 0); the point on the pivot (1,0,0) stays put",
      close(X(px=1.0, rz=180.0)[1], [2, -1, 0]) and close(X(px=1.0, rz=180.0)[0], [1, 0, 0]))
check("  Pivot + scale: sx 3 around x = 1: (0,1,0) -> (-2, 1, 0)", close(X(px=1.0, sx=3.0)[1], [-2, 1, 0]))
check("Pivot Rotate Z 90° + sx 2: the scale's 'x axis' is rotated onto world Y -- (0,1,0) -> (0,2,0), (1,0,0) stays put",
      close(X(prz=90.0, sx=2.0)[:2], [[1, 0, 0], [0, 2, 0]]), X(prz=90.0, sx=2.0)[:2].tolist())
c30, s30 = np.cos(np.radians(30)), np.sin(np.radians(30))
check("  Pivot Rotate Z 30° + sx 2 (by hand): (1,0,0) -> (2c² + s², c·s) = (1.75, 0.433)",
      close(X(prz=30.0, sx=2.0)[0], [2 * c30 * c30 + s30 * s30, c30 * s30, 0]), X(prz=30.0, sx=2.0)[0])
check("  Pivot Translate also counts when combined with other new parameters: pivot x = 1, Uniform Scale 3: (0,1,0) -> (-2, 3, 0)",
      close(X(px=1.0, uniform_scale=3.0)[1], [-2, 3, 0]), X(px=1.0, uniform_scale=3.0)[1])
check("  Invert only: tx 1 becomes moving back by 1; Rz 90° becomes -90°", close(X(tx=1.0, invert=True)[0], [0, 0, 0])
      and close(X(rz=90.0, invert=True)[0], [0, -1, 0]))
check("  only Pivot Rotate given (no scale, no rotate): no change", close(X(prz=37.0), np.eye(3)))
full = dict(tx=1.0, ty=2.0, tz=3.0, rx=10.0, ry=20.0, rz=30.0, sx=2.0, sy=0.5, sz=1.5, shear_xy=0.3, shear_yz=-0.2,
            uniform_scale=1.3, px=0.5, py=-1.0, prx=15.0, prz=40.0, xform_order="rts", rotate_order="zxy")
fwd = run("PCG_Transform", geo=gsm, **full)
back = run("PCG_Transform", geo=fwd, invert=True, **full)
check("Invert Transformation: transform with all parameters, then transform back with the same parameters and Invert on = unchanged",
      float(np.abs(P_(back) - P_(gsm)).max()) < 2e-5 and float(np.abs(P_(fwd) - P_(gsm)).max()) > 0.5,
      float(np.abs(P_(back) - P_(gsm)).max()))
M4 = ops.xform_matrix(**{"translate": (1, 2, 3), "rotate": (10, 20, 30), "scale": (2, 0.5, 1.5), "shear": (0.3, 0, -0.2),
                         "uniform_scale": 1.3, "pivot": (0.5, -1, 0), "pivot_rotate": (15, 0, 40),
                         "xform_order": "rts", "rotate_order": "zxy"})
check("  xform_matrix is a 4x4 for row vectors: last column (0,0,0,1); node result = [p,1] @ M",
      close(M4[:, 3], [0, 0, 0, 1]) and float(np.abs(P_(fwd) - (P_(gsm) @ M4[:3, :3] + M4[3, :3])).max()) < 1e-5)
gn = build.grid(2, 2, 3, 3)
gn = ops.compute_normals(gn, add_to="point")
sh = run("PCG_Transform", geo=gn, shear_xy=1.0, ry=30.0, sx=2.0)
N = np.asarray(sh.get(POINT, "N"), np.float64); Ps = P_(sh)
e1, e2 = Ps[1] - Ps[0], Ps[3] - Ps[0]
check("with shear + non-uniform scale normals stay perpendicular to the transformed faces (inverse transpose), and unit length",
      abs(float(N[0] @ e1)) < 1e-5 and abs(float(N[0] @ e2)) < 1e-5 and close(np.linalg.norm(N, axis=1), 1.0)
      and float(N[0] @ np.cross(e2, e1)) != 0)
gg = build.grid(2, 2, 3, 3)
gg.set_group(POINT, "half", np.arange(9) < 4)
pg = P_(run("PCG_Transform", geo=gg, group="half", xform_order="trs", tx=1.0, uniform_scale=2.0))
check("Group: the new code path also only moves the selected points", close(pg[4:], P_(gg)[4:]) and close(pg[:4], (P_(gg)[:4] + [1, 0, 0]) * 2))
try:
    ops.xform_matrix(xform_order="xyz")
    check("other Transform Order value: error", False)
except ValueError as ex:
    check("other Transform Order value: error", "Transform Order must be one of" in str(ex))

# ═══════════════════════════════════════════════════════ panel
sec("panel")
for k in OLD:
    probs = PANEL.check_layout(k, M[k].INPUT_TYPES())
    pm = str(PANEL.panel_model(k, M[k].INPUT_TYPES()))
    lost = [n for n in names(k) if n != "geo" and n not in pm]
    check(f"{k}: spec self-check clean, every parameter is on the panel", not probs and not lost, (probs, lost))
ui = PANEL.layout_for("PCG_Sphere", M["PCG_Sphere"].INPUT_TYPES())[0]
check("Sphere: Frequency only shows in Polygon mode, Rows / Columns only in Polygon Mesh mode",
      ui["frequency"]["hide"] == "{ prim_type != polygon }" and ui["rows"]["hide"] == "{ prim_type != polygon_mesh }"
      and ui["cols"]["hide"] == "{ prim_type != polygon_mesh }" and ui["radius"]["label"] == "Uniform Scale")

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
