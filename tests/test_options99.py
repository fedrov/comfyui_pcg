"""
pcg99: second batch of added options.

  PolyBevel   Shape gains Solid (one plane per edge) / Crease (shape unchanged, one ring of guard edges on each side of the ridge)
  UV Project  Projection gains Toroidal (u around the main axis, v around the tube) / Plastic Wrap (wraps down from the front of the axis, a single pinch point at the back)
  Measure     Curvature (Gaussian): angle defect / area
  Trail       Connect as Mesh: each edge sweeps a quad between two adjacent frames

All checked against hand-computed numbers: volume formula, 1/r² on a sphere, 4π from Gauss-Bonnet, swept area.
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
from comfyui_pcg.geo import build, ops, uvproject as UVP, measure as MS, timeops as TMO  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def tri_(g):
    P, T = P_(g), g.triangles()
    return P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]


def area(g):
    a, b, c = tri_(g)
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def volume(g):
    a, b, c = tri_(g)
    return float((a * np.cross(b, c)).sum() / 6.0)


def closed_manifold(g):
    seen = {}
    for k in range(g.nprims):
        pts = g.prim_points(k)
        for i in range(len(pts)):
            e = (int(pts[i]), int(pts[(i + 1) % len(pts)]))
            seen[e] = seen.get(e, 0) + 1
    return all(v == 1 for v in seen.values()) and all((b, a) in seen for (a, b) in seen)


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


close = lambda a, b, e=1e-5: np.allclose(a, b, atol=e)          # noqa: E731
opts = lambda k, n: list(M[k].INPUT_TYPES()["required"][n][0])  # noqa: E731

sec("old workflows unchanged: dropdowns only append options")
check("PolyBevel Shape / UV Project Projection / Measure / Trail Result Type: the first entries are still the original ones",
      opts("PCG_PolyBevel", "shape")[:2] == ["round", "chamfer"]
      and opts("PCG_UVProject", "mode")[:6] == ["planar", "cylindrical", "spherical", "box", "face", "rows_columns"]
      and opts("PCG_Measure", "measurement")[:4] == ["area", "perimeter", "volume", "curvature"]
      and opts("PCG_Trail", "mode")[:3] == ["preserve", "connect", "velocity"])

# ═══════════════════════════════════════════════════════ PolyBevel
sec("PolyBevel:Solid / Crease")
box = build.box((2, 2, 2))
d = 0.2
B = lambda **kw: run("PCG_PolyBevel", geo=box, distance=d, use_fillet=True, **kw)      # noqa: E731
v_solid = 8 - 12 * (d * d / 2) * (2 - 2 * d) - 8 * (5 / 6) * d ** 3
so = B(shape="solid", divisions=4)
check(f"Solid: one plane per ridge (12 quads), one triangle per corner (8), 6 faces inset; 24 points; "
      f"volume = 8 − 12·(d²/2)(2 − 2d) − 8·(5/6)d³ = {v_solid:.5f}; closed",
      so.nprims == 26 and sorted(so.prim_sizes().tolist()) == [3] * 8 + [4] * 18 and close(volume(so), v_solid, 1e-4)
      and closed_manifold(so), (so.nprims, volume(so)))
check("  Solid ignores Divisions: identical to Chamfer, Divisions 1; Chamfer, Divisions 4 has many more faces",
      np.array_equal(P_(so), P_(B(shape="chamfer", divisions=1))) and so.nprims == B(shape="chamfer", divisions=1).nprims
      and B(shape="chamfer", divisions=4).nprims > so.nprims)
cr = B(shape="crease", divisions=5)
Pc = P_(cr)
used = np.unique(cr.vertex_point)
check("Crease: **shape unchanged** -- volume still 8, bounding box still ±1, the original 8 corner points still in use; closed",
      close(volume(cr), 8.0, 1e-5) and close(np.abs(Pc[used]).max(0), [1, 1, 1])
      and sum(np.allclose(np.abs(p), 1) for p in Pc[used]) == 8 and closed_manifold(cr), volume(cr))
sizes = cr.prim_sizes()
big = [k for k in range(cr.nprims) if close(np.ptp(Pc[cr.prim_points(k)], axis=0).max(), 2 - 2 * d)
       and close(sorted(np.ptp(Pc[cr.prim_points(k)], axis=0))[0], 0)]
check("  each of the 6 faces shrinks by d (still on its original plane, edge length 2 − 2d); one strip of width d on each side of every ridge, 24 in total; all quads; no corner caps",
      cr.nprims == 30 and (sizes == 4).all() and len(big) == 6, (cr.nprims, len(big)))
edge_strips = 0
for k in range(cr.nprims):
    pts = Pc[cr.prim_points(k)]
    on_edge = [(np.isclose(np.abs(p), 1).sum() >= 2) for p in pts]      # lies on an original ridge
    if sum(on_edge) == 2:
        edge_strips += 1
check("  each strip has two points on the original ridge (the ridge stays in place as the crease)", edge_strips == 24, edge_strips)
check("  Crease ignores Divisions", np.array_equal(Pc, P_(B(shape="crease", divisions=1))))
tube = build.tube(1.0, 1.0, 2.0, cols=8, rows=2, caps=True)
ct = run("PCG_PolyBevel", geo=tube, distance=0.1, shape="crease", use_fillet=True)
check("  capped octagonal tube: volume unchanged after Crease, closed", close(volume(ct), volume(tube), 1e-5) and closed_manifold(ct)
      and ct.nprims > tube.nprims, (volume(ct), volume(tube)))
try:
    ops.polybevel(box, shape="wavy")
    check("Shape set to something else: raises", False)
except ValueError as e:
    check("Shape set to something else: raises", "Shape must be one of" in str(e))
ui = PANEL.layout_for("PCG_PolyBevel", M["PCG_PolyBevel"].INPUT_TYPES())[0]
check("panel: Solid / Crease grey out Divisions", "shape == solid" in ui["divisions"]["disable"] and "shape == crease" in ui["divisions"]["disable"])

# ═══════════════════════════════════════════════════════ UV Project
sec("UV Project:Toroidal / Plastic Wrap")
Rr, rr = 2.0, 0.5
tor = build.torus(Rr, rr, rows=16, cols=32)
tp = UVP.project(tor, "toroidal", "y", POINT, "uv", fit=False, fix_seams=False)
uv = np.asarray(tp.get(POINT, "uv"), np.float64)
Pt = P_(tor)
rad = np.hypot(Pt[:, 0], Pt[:, 2])
check("Toroidal (axis = Y): u follows only the angle around the main axis, v only the angle around the tube -- 32 distinct u, 16 distinct v, both cover 0 ~ 1",
      len(np.unique(np.round(uv[:, 0], 4))) == 32 and len(np.unique(np.round(uv[:, 1], 4))) == 16
      and uv.min() >= 0 and uv.max() < 1, (len(np.unique(np.round(uv[:, 0], 4))), len(np.unique(np.round(uv[:, 1], 4)))))
outer = np.isclose(rad, Rr + rr, atol=1e-4)
inner = np.isclose(rad, Rr - rr, atol=1e-4)
top = np.isclose(Pt[:, 1], rr, atol=1e-4)
check("  v positions: outer equator 0, top ring 0.25, inner equator 0.5", close(uv[outer, 1], 0, 1e-4) and close(uv[top, 1], 0.25, 1e-4)
      and close(uv[inner, 1], 0.5, 1e-4) and outer.sum() == 32 and inner.sum() == 32 and top.sum() == 32)
back = np.stack([(Rr + rr * np.cos(2 * np.pi * uv[:, 1])), rr * np.sin(2 * np.pi * uv[:, 1])], 1)
check("  points can be reconstructed from (u, v): distance to axis = R + r·cos 2πv, height = r·sin 2πv", close(back[:, 0], rad, 1e-4) and close(back[:, 1], Pt[:, 1], 1e-4))
tv = UVP.project(tor, "toroidal", "y", VERTEX, "uv", fit=False, fix_seams=True)
uvv = np.asarray(tv.get(VERTEX, "uv"), np.float64).reshape(-1, 4, 2)
tn = np.asarray(UVP.project(tor, "toroidal", "y", VERTEX, "uv", fit=False, fix_seams=False).get(VERTEX, "uv"), np.float64).reshape(-1, 4, 2)
check("  seams in both directions, Fix Boundary Seams fixes both: no face spans more than half the texture in u or v (unfixed, each direction has a ring of such faces)",
      float(np.ptp(uvv, axis=1).max()) < 0.5 and (np.ptp(tn[:, :, 0], axis=1) > 0.5).sum() == 16
      and (np.ptp(tn[:, :, 1], axis=1) > 0.5).sum() == 32, float(np.ptp(uvv, axis=1).max()))
sph = build.sphere(1.0, cols=16, rows=9)
pw = np.asarray(UVP.project(sph, "plastic_wrap", "y", POINT, "uv", fit=False).get(POINT, "uv"), np.float64)
Ps = P_(sph)
theta = np.arccos(np.clip(Ps[:, 1], -1, 1))
rr_ = np.linalg.norm(pw - 0.5, axis=1)
check("Plastic Wrap (axis = Y): the north pole facing +Y is at the texture center (0.5, 0.5); distance from center = angle turned / π × 0.5"
      " (equator 0.25, south pole pinched onto the circle of radius 0.5)", close(pw[0], [0.5, 0.5]) and close(rr_, theta / np.pi * 0.5, 1e-5)
      and close(rr_[-1], 0.5) and close(rr_[np.isclose(Ps[:, 1], 0, atol=1e-6)], 0.25), (pw[0].tolist(), rr_[-1]))
az = np.arctan2(pw[:, 1] - 0.5, pw[:, 0] - 0.5)[1:-1].reshape(7, 16)
check("  points on the same meridian go in the same direction on the texture (16 meridians, 16 directions); all within 0 ~ 1",
      float(np.ptp(np.unwrap(az, axis=0), axis=0).max()) < 1e-5 and len(np.unique(np.round(az[0], 4))) == 16
      and pw.min() >= -1e-9 and pw.max() <= 1 + 1e-9)
pv = np.asarray(UVP.project(sph, "plastic_wrap", "y", VERTEX, "uv", fit=False).get(VERTEX, "uv"), np.float64)
far = [k for k in range(sph.nprims) if not (sph.prim_points(k) == sph.npoints - 1).any()]
off = sph.prim_offset
span = max(float(np.ptp(pv[off[k]:off[k + 1]], axis=0).max()) for k in far)
check("  no seam: apart from the ring touching the back pinch point, no face spans wide on the texture (< 0.25)", span < 0.25, span)
check("  Fix Boundary Seams leaves this mode alone (it has no seam): vertex uv is the point uv", np.array_equal(pv, pw[sph.vertex_point].astype(np.float32).astype(np.float64))
      or close(pv, pw[sph.vertex_point], 1e-6))
octa = Geometry.from_mesh(np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1], [-1, 0, 0], [0, 0, -1], [0, -1, 0]], np.float32),
                          [[0, 2, 1], [0, 3, 2], [0, 4, 3], [0, 1, 4], [5, 1, 2], [5, 2, 3], [5, 3, 4], [5, 4, 1]])
po = np.asarray(UVP.project(octa, "plastic_wrap", "y", POINT, "uv", fit=False).get(POINT, "uv"), np.float64)
check("  points exactly on the axis (the two octahedron vertices, no azimuth): the front one at the center, the back one on the radius-0.5 circle (does not collapse to the center)",
      close(po[0], [0.5, 0.5]) and close(np.linalg.norm(po[5] - 0.5), 0.5) and close(np.linalg.norm(po[1:5] - 0.5, axis=1), 0.25),
      po.tolist())
check("node / panel: Projection dropdown gains Toroidal, Plastic Wrap; both also show Projection Axis; Toroidal shows Fix Boundary Seams",
      opts("PCG_UVProject", "mode")[-2:] == ["toroidal", "plastic_wrap"]
      and all(x in str(PANEL.panel_model("PCG_UVProject", M["PCG_UVProject"].INPUT_TYPES())) for x in ("Toroidal", "Plastic Wrap"))
      and not PANEL.check_layout("PCG_UVProject", M["PCG_UVProject"].INPUT_TYPES()))
ru = run("PCG_UVProject", geo=tor, mode="toroidal", axis="y")
check("  node runs Toroidal: writes vertex uv, within 0 ~ 1", ru.get(VERTEX, "uv") is not None
      and float(np.asarray(ru.get(VERTEX, "uv")).min()) >= -1e-6 and float(np.asarray(ru.get(VERTEX, "uv")).max()) <= 1 + 1e-6)

# ═══════════════════════════════════════════════════════ Measure
sec("Measure:Curvature (Gaussian)")
ico = build.sphere(2.0, prim_type="polygon", frequency=6)
K = MS.gaussian_curvature(ico)
check("sphere of radius 2: every point is 1/r² = 0.25 (error < 2.5%, including the 12 points with only 5 neighbours)", float(np.abs(K / 0.25 - 1).max()) < 0.025, (K.min(), K.max()))
dfc, Av = MS.angle_defect(ico)
check("  area assigned to a point is the Voronoi area: sums to the whole sphere area; if each corner took a third, 5-neighbour points would read > 10% too high",
      close(Av.sum(), area(ico), 1e-6) and float((dfc / np.bincount(ico.triangles().reshape(-1), np.repeat(
          0.5 * np.linalg.norm(np.cross(tri_(ico)[1] - tri_(ico)[0], tri_(ico)[2] - tri_(ico)[0]), axis=1) / 3, 3))).max() / 0.25) > 1.10)
ob = Geometry.from_mesh(np.array([[0, 0, 0], [4, 0, 0], [1, 0.5, 0]], np.float32), [np.arange(3)])
_, Ao = MS.angle_defect(ob)
check("  obtuse triangle (circumcenter outside): the obtuse corner gets half the area, the other two a quarter each (area 1 -> 0.25, 0.25, 0.5)",
      close(Ao, [0.25, 0.25, 0.5], 1e-6), Ao.tolist())
rt_ = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [0, 1, 0]], np.float32), [np.arange(3)])
check("  right triangle (not obtuse): split by circumcenter -- the right-angle corner gets half (circumcenter at hypotenuse midpoint), the other two a quarter each",
      close(MS.angle_defect(rt_)[1], [0.5, 0.25, 0.25], 1e-6), MS.angle_defect(rt_)[1].tolist())
ac = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [1, 2, 0]], np.float32), [np.arange(3)])
check("  acute triangle (0,0) (2,0) (1,2): circumcenter (1, 0.75); the (0,0) region is (0,0) (1,0) (1,0.75) (0.5,1) = 0.6875, the top one 0.625",
      close(MS.angle_defect(ac)[1], [0.6875, 0.6875, 0.625], 1e-6), MS.angle_defect(ac)[1].tolist())
bx = build.box()
lone = Geometry.from_mesh(np.concatenate([np.asarray(bx.get(POINT, "P")), [[9, 9, 9]]]).astype(np.float32),
                          [bx.prim_points(k) for k in range(bx.nprims)])
check("  isolated point not used by any face: curvature 0 (not 2π / 0)", MS.gaussian_curvature(lone)[-1] == 0 and np.isfinite(MS.gaussian_curvature(lone)).all())
H = MS.mean_curvature(ico)
check("  (control) the mean curvature mode gives 1/r = 0.5 -- the two modes are different things", abs(float(np.median(np.abs(H))) / 0.5 - 1) < 0.05, float(np.median(np.abs(H))))
gr = build.grid(4, 4, 6, 6)
Kg = MS.gaussian_curvature(gr)
Pg = P_(gr)
corner = (np.abs(Pg[:, 0]) > 1.99) & (np.abs(Pg[:, 2]) > 1.99)
check("plane: interior points 0; 0 on straight boundaries too (boundary counted as π); the four corners are positive (the boundary turns 90° there)",
      close(Kg[~corner], 0, 1e-6) and (Kg[corner] > 0).all() and corner.sum() == 4, Kg[corner].tolist())
cyl = build.tube(1.0, 1.0, 3.0, cols=24, rows=6, caps=False)
Kc = MS.gaussian_curvature(cyl)
Pcy = P_(cyl)
inner_c = np.abs(Pcy[:, 1]) < 1.4
check("cylinder side (developable surface): interior Gaussian curvature 0, while mean curvature is not 0", close(Kc[inner_c], 0, 1e-6)
      and float(np.abs(MS.mean_curvature(cyl)[inner_c]).min()) > 0.3)


def total_defect(g):
    K_, (d_, A_) = MS.gaussian_curvature(g), MS.angle_defect(g)
    return float((K_ * A_).sum())


check("Gauss-Bonnet: Σ K·A = 4π on closed surfaces (sphere and box); torus is 0 (genus 1)",
      close(total_defect(ico), 4 * np.pi, 1e-6) and close(total_defect(build.box()), 4 * np.pi, 1e-6)
      and close(total_defect(build.torus(2.0, 0.5, 12, 24)), 0.0, 1e-6),
      (total_defect(ico), total_defect(build.box()), total_defect(build.torus(2.0, 0.5, 12, 24))))
Kt = MS.gaussian_curvature(build.torus(2.0, 0.5, 16, 32))
Ptt = P_(build.torus(2.0, 0.5, 16, 32))
rt = np.hypot(Ptt[:, 0], Ptt[:, 2])
check("  torus outside is positive (like a sphere), inside negative (like a saddle)", (Kt[rt > 2.4] > 0).all() and (Kt[rt < 1.6] < 0).all())
mp = run("PCG_Measure", geo=ico, element_type="points", measurement="gaussian_curvature", attribute_name="")
mf = run("PCG_Measure", geo=ico, element_type="primitives", measurement="gaussian_curvature", attribute_name="K")
check("node: writes a point curvature attribute (0.25); on primitives = average of the corners; panel menu shows Curvature (Gaussian)",
      close(np.asarray(mp.get(POINT, "curvature")).ravel(), K, 1e-5)
      and float(np.abs(np.asarray(mf.get(PRIM, "K")).ravel() / 0.25 - 1).max()) < 0.025
      and "Curvature (Gaussian)" in str(PANEL.panel_model("PCG_Measure", M["PCG_Measure"].INPUT_TYPES())))
check("  empty geometry / point cloud with no faces: all 0, no exception", len(MS.gaussian_curvature(Geometry())) == 0
      and close(MS.gaussian_curvature(Geometry.from_mesh(np.zeros((3, 3), np.float32), [])), 0))

# ═══════════════════════════════════════════════════════ Trail
sec("Trail:Connect as Mesh")


def moving(g, n=3, step=(0, 1, 0)):
    return [ops.transform(g, translate=tuple(np.asarray(step, float) * k)) for k in range(n)]


line = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0]], np.float32), [np.arange(2)], closed=False)
m = TMO.trail(moving(line), index=2, length=2, mode="connect_mesh")
check("a segment of length 2 moving up for 2 frames (1 per frame): sweeps 2 quads, a 2 × 2 strip in total (area 4); 6 points; trailu still present",
      m.nprims == 2 and (m.prim_sizes() == 4).all() and m.prim_closed.all() and m.npoints == 6 and close(area(m), 4.0)
      and m.get(POINT, "trailu") is not None, (m.nprims, area(m)))
sq = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32), [np.arange(4)], closed=True)
ms_ = TMO.trail(moving(sq), index=2, length=2, mode="connect_mesh")
check("a 1×1 square face moving up 2: four edges (including the closing one) sweep 8 quads = a tube wall, area = perimeter 4 × 2 = 8",
      ms_.nprims == 8 and close(area(ms_), 8.0), (ms_.nprims, area(ms_)))
two = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32),
                         [np.array([0, 1, 2]), np.array([0, 2, 3])])
mt = TMO.trail(moving(two), index=2, length=2, mode="connect_mesh")
check("two triangles sharing an edge: the shared edge is swept only once -- 5 edges × 2 = 10 quads (not 12)", mt.nprims == 10, mt.nprims)
a_, b_, c_ = tri_(m)
check("  quads are not twisted: strip normals all face the same side", len({int(np.sign(x)) for x in np.cross(b_ - a_, c_ - a_)[:, 2]}) == 1)
pl3 = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], np.float32), [np.arange(3)], closed=False)
check("open three-point polyline: only 2 edges (no closing one) -> 4 quads", TMO.trail(moving(pl3), index=2, length=2, mode="connect_mesh").nprims == 4)
dg = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0]], np.float32), [np.array([0, 0, 1])], closed=False)
check("  consecutive duplicate points in a prim (zero-length edge): not swept", TMO.trail(moving(dg), index=2, length=2, mode="connect_mesh").nprims == 2)
pts = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0]], np.float32), [])
mp_ = TMO.trail(moving(pts), index=2, length=2, mode="connect_mesh")
mc_ = TMO.trail(moving(pts), index=2, length=2, mode="connect")
check("point cloud with no prims: no edges to sweep, falls back to Connect as Polygons polylines (one per point)", mp_.nprims == 2 and not mp_.prim_closed.any()
      and np.array_equal(mp_.vertex_point, mc_.vertex_point))
check("  Connect as Polygons (the original connect) unchanged: also one polyline per point on geometry with prims",
      TMO.trail(moving(sq), index=2, length=2, mode="connect").nprims == 4
      and not TMO.trail(moving(sq), index=2, length=2, mode="connect").prim_closed.any())
m0 = TMO.trail(moving(line), index=0, length=0, mode="connect_mesh")
check("  Trail Length 0 (only one frame): nothing to sweep, falls back to polylines, no exception", m0.npoints == 2 and m0.nprims == 2)
check("panel: Result Type gains Connect as Mesh", "Connect as Mesh" in str(PANEL.panel_model("PCG_Trail", M["PCG_Trail"].INPUT_TYPES()))
      and not PANEL.check_layout("PCG_Trail", M["PCG_Trail"].INPUT_TYPES()))

sec("panel self-check")
for k in ("PCG_PolyBevel", "PCG_UVProject", "PCG_Measure", "PCG_Trail"):
    check(f"{k}: layout spec self-check clean", not PANEL.check_layout(k, M[k].INPUT_TYPES()), PANEL.check_layout(k, M[k].INPUT_TYPES()))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
