"""
pcg121: the nodes added after the code review, checked against analytic values and against brute force.

  1. Distance from Geometry: surface / edges / points against brute force and closed forms, Max Distance, mask ramp
  2. Distance along Geometry: edges = Manhattan on a quad grid; geodesic on a sphere = R * angle (< 1%), on a plane
     = Euclidean (< 8%, median 2%); unreachable points -1; the negative control (Edges) misses the diagonal by 41%
  3. Path Deform: identity on a straight curve; on a circle the axis lands on the circle at the right arc length;
     straight extension past the ends; normals turn with the frame
  4. PolyWire: chains / joints / caps of a Y junction; every ring point is exactly the radius away from its segment;
     a loop becomes a closed tube without caps; width / pscale radii
  5. Thicken: both / outward / inward extents, groups, a closed sphere becomes a hollow shell
  6. Curve Fillet: arcs tangent to both segments at distance r from the centre; Limit Radius; ends kept;
     straight corners untouched; a square gets four arcs
  7. Pack / Unpack: Copy to Points (packed) -> Unpack == Copy to Points (every attribute, piece attribute, prim
     attributes, multiply); Transform commutes with packing; Pack -> Unpack gives the input back; Merge / Blast keep
     packed primitives; non-aware nodes get unpacked input automatically; packed targets of Copy to Points are points;
     the viewport payload carries one instance set with the right matrices and a bounding box covering the copies
"""
import os
import sys
import json
import struct

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.dirname(_R), os.path.dirname(os.path.dirname(_R))):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy  # noqa: F401,E402
import numpy as np  # noqa: E402

import comfyui_pcg  # noqa: E402,F401  (registers every node and the auto-unpack wrapper)
from comfyui_pcg import viewport as VP  # noqa: E402
from comfyui_pcg.geo import (build, ops, distgeo as DG, pathdeform as PD, polywire as PW, thicken as TH,  # noqa: E402
                             curvefillet as CF, packed as PK, copyto as CT, Geometry)
from comfyui_pcg.geo.core import POINT, PRIM, PRIM_PACKED  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def node(name, **kw):
    """Run a registered node with its defaults filled in (like the frontend does)."""
    c = N["PCG_" + name]
    it = c.INPUT_TYPES()
    args = {}
    for sec in ("required", "optional"):
        for k, spec in it.get(sec, {}).items():
            if k in kw:
                continue
            t = spec[0]
            opt = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(t, list):
                args[k] = t[0]
            elif "default" in opt:
                args[k] = opt["default"]
    args.update(kw)
    out = getattr(c(), c.FUNCTION)(**args)
    return out["result"] if isinstance(out, dict) else out


def polyline(pts, closed=False):
    pts = np.asarray(pts, np.float32)
    g = Geometry(len(pts))
    g.set(POINT, "P", pts)
    g.set_topology(np.arange(len(pts), dtype=np.int32), np.array([0, len(pts)], np.int32),
                   np.array([closed]), np.zeros(1, np.uint8))
    return g


rng = np.random.default_rng(5)

# ═════════════════════════════════════════════ 1
print("\n[1. Distance from Geometry]")
sph = build.sphere(radius=1.0, cols=96, rows=48)
q = build.grid(size_x=4, size_z=4, rows=30, cols=30, center=(0, 0.3, 0))
d, rep = DG.distance_from_geometry(q, sph, metric="surface")
dd = np.asarray(d.get(POINT, "dist"))[:, 0]
an = np.abs(np.linalg.norm(P_(q), axis=1) - 1.0)
check("surface: |r - 1| to the unit sphere within the tessellation error (< 0.002)",
      np.abs(dd - an).max() < 2e-3, np.abs(dd - an).max())
dp, _ = DG.distance_from_geometry(q, sph, metric="points")
bf = np.linalg.norm(P_(q)[:, None] - P_(sph)[None], axis=2).min(1)
check("points: == brute-force nearest point", np.allclose(np.asarray(dp.get(POINT, "dist"))[:, 0], bf, atol=1e-5))
seg = polyline([[0, 0, 0], [1, 0, 0]])
pts = Geometry.from_points(np.array([[0.5, 2, 0], [-1, 0, 0], [3, 0, 4]], np.float32))
de, _ = DG.distance_from_geometry(pts, seg, metric="edges")
check("edges: distances to a segment (inside, before the start, past the end) = 2, 1, sqrt(20)",
      np.allclose(np.asarray(de.get(POINT, "dist"))[:, 0], [2, 1, np.sqrt(20)], atol=1e-5))
dm, _ = DG.distance_from_geometry(q, sph, use_max=True, max_dist=0.5, output_mask=True, mask_radius=0.5)
v = np.asarray(dm.get(POINT, "dist"))[:, 0]
m = np.asarray(dm.get(POINT, "mask"))[:, 0]
check("Max Distance clamps at 0.5 (farther points get exactly 0.5)", v.max() <= 0.5 + 1e-6 and np.any(v == 0.5))
check("  mask = 1 - d / radius with the default ramp", np.allclose(m, 1 - np.minimum(v, 0.5) / 0.5, atol=1e-5))
dg_, _ = DG.distance_from_geometry(q, sph, group="0-9")
check("group: only the selected points get a distance (others 0)",
      np.all(np.asarray(dg_.get(POINT, "dist"))[10:, 0] == 0) and np.any(np.asarray(dg_.get(POINT, "dist"))[:10, 0] > 0))

# ═════════════════════════════════════════════ 2
print("\n[2. Distance along Geometry]")
g = build.grid(size_x=2, size_z=2, rows=41, cols=41)
Pg = P_(g)
c = int(np.argmin(np.linalg.norm(Pg, axis=1)))
de, _ = DG.distance_along_geometry(g, str(c), method="edges")
man = np.abs(Pg - Pg[c]).sum(1)
check("edges on a quad grid: Manhattan distance exactly", np.allclose(np.asarray(de.get(POINT, "dist"))[:, 0], man,
                                                                      atol=1e-5))
dg2, _ = DG.distance_along_geometry(g, str(c), method="geodesic")
eu = np.linalg.norm(Pg - Pg[c], axis=1)
far = eu > 0.2
rel = np.abs(np.asarray(dg2.get(POINT, "dist"))[:, 0] - eu)[far] / eu[far]
check("geodesic on a plane: Euclidean within 8% at worst, 2% median (heat method, fan-triangulated grid)",
      rel.max() < 0.08 and np.median(rel) < 0.02, (rel.max(), np.median(rel)))
rel_e = np.abs(man - eu)[far] / eu[far]
check("  negative control: Edges misses the diagonal by sqrt(2) - 1 = 41%", abs(rel_e.max() - (np.sqrt(2) - 1)) < 1e-6)
Ps = P_(sph)
top = int(np.argmax(Ps[:, 1]))
gs, _ = DG.distance_along_geometry(sph, str(top), method="geodesic")
ang = np.arccos(np.clip(Ps[:, 1] / np.linalg.norm(Ps, axis=1), -1, 1))
er = np.abs(np.asarray(gs.get(POINT, "dist"))[:, 0] - ang)
check("geodesic on the unit sphere: = polar angle within 1% of pi", er.max() < 0.01 * np.pi, er.max())
two = ops.merge(build.grid(size_x=1, size_z=1, rows=5, cols=5),
                build.grid(size_x=1, size_z=1, rows=5, cols=5, center=(5, 0, 0)))
du, ru = DG.distance_along_geometry(two, "0", method="geodesic")
dv = np.asarray(du.get(POINT, "dist"))[:, 0]
check("unreachable points (the second grid) get -1, the first grid >= 0",
      np.all(dv[25:] == -1) and np.all(dv[:25] >= 0) and ru["unreachable"] == 25)

# ═════════════════════════════════════════════ 3
print("\n[3. Path Deform]")
strip = build.grid(size_x=0.2, size_z=2, rows=3, cols=11)
line = polyline([[0, 0, -1], [0, 0, 0], [0, 0, 1]])
o, _ = PD.path_deform(strip, line, stretch=True)
check("straight curve along z covering the input: identity", np.abs(P_(o) - P_(strip)).max() < 1e-6)
t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
circ = polyline(np.stack([np.cos(t), np.zeros_like(t), np.sin(t)], 1), closed=True)
axis_pts = Geometry.from_points(np.stack([np.zeros(5), np.zeros(5), np.linspace(0, 3, 5)], 1).astype(np.float32))
oc, rc = PD.path_deform(axis_pts, circ, stretch=False)
Pc = P_(oc)
check("on the unit circle: axis points land on the circle", np.abs(np.linalg.norm(Pc, axis=1) - 1).max() < 1e-3,
      np.abs(np.linalg.norm(Pc, axis=1) - 1).max())
arc = np.unwrap(np.arctan2(Pc[:, 2], Pc[:, 0]))
check("  at arc length = the axis coordinate (0, .75, 1.5, 2.25, 3 rad)",
      np.abs((arc - arc[0]) - np.linspace(0, 3, 5)).max() < 2e-3, np.round(arc - arc[0], 4))
lin = polyline([[0, 0, 0], [0, 0, 1]])
ex = Geometry.from_points(np.array([[0, 0, 2.5]], np.float32))
oe, re_ = PD.path_deform(ex, lin, stretch=False)
check("past the end: continues straight along the end tangent", np.abs(P_(oe)[0] - [0, 0, 2.5]).max() < 1e-6
      and re_["beyond_ends"] == 1)
gn = ops.compute_normals(build.grid(size_x=0.2, size_z=1, rows=3, cols=5), "point")
bend = polyline([[0, 0, 0], [0, 0, 0.5], [0, 0.5, 1.0], [0, 1.0, 1.0]])
ob, _ = PD.path_deform(gn, bend, stretch=True)
Nn = np.asarray(ob.get(POINT, "N"), np.float64)
check("normals turn with the frame and stay unit length", np.allclose(np.linalg.norm(Nn, axis=1), 1, atol=1e-5)
      and np.abs(Nn - [0, 1, 0]).max() > 0.5)

# ═════════════════════════════════════════════ 4
print("\n[4. PolyWire]")
Y = ops.merge(polyline([[0, 0, 0], [0, 1, 0]]), polyline([[0, 0, 0], [0.7, -0.7, 0]]),
              polyline([[0, 0, 0], [-0.7, -0.7, 0]]))
from comfyui_pcg.geo import fusesop  # noqa: E402
Yf = node("Fuse", geo=Y)[0] if "PCG_Fuse" in N else Y
w, rw = PW.polywire(Yf, radius=0.05, divisions=8)
check("Y junction: 3 chains, 4 spheres (junction + 3 round ends)", rw["chains"] == 3 and rw["joints"] == 4, rw)
w2, _ = PW.polywire(Yf, radius=0.05, divisions=8, end_caps="none", joints=False)
Pw = P_(w2)
segs = [(np.zeros(3), np.array([0, 1, 0.])), (np.zeros(3), np.array([0.7, -0.7, 0])),
        (np.zeros(3), np.array([-0.7, -0.7, 0]))]


def seg_dist(p, a, b):
    ab = b - a
    tt = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(a + tt[:, None] * ab - p, axis=1)


dmin = np.min([seg_dist(Pw, a, b) for a, b in segs], 0)
away = np.linalg.norm(Pw, axis=1) > 0.15          # at the junction a ring point is also near the other branches
check("without joints / caps: every ring point exactly the radius from the network",
      np.abs(dmin[away] - 0.05).max() < 1e-5 and away.sum() == 24, np.abs(dmin[away] - 0.05).max())
loop = polyline(np.stack([np.cos(t[::40]), np.sin(t[::40]), np.zeros(10)], 1), closed=True)
wl, rl = PW.polywire(loop, radius=0.05, divisions=6, joint_angle=60.0)
check("a loop: one closed tube, m * divisions points, all quads, no caps",
      rl["chains"] == 1 and rl["joints"] == 0 and wl.npoints == 60 and np.all(wl.prim_sizes() == 4) and wl.nprims == 60)
Yw = Yf.copy()
Yw.set(POINT, "width", np.full((Yw.npoints, 1), 0.2, np.float32))
ww, _ = PW.polywire(Yw, radius_from="width", divisions=8, end_caps="none", joints=False)
dmin2 = np.min([seg_dist(P_(ww), a, b) for a, b in segs], 0)
away2 = np.linalg.norm(P_(ww), axis=1) > 0.3
check("width attribute is a diameter (width 0.2 -> radius 0.1)", np.abs(dmin2[away2] - 0.1).max() < 1e-5)

# ═════════════════════════════════════════════ 5
print("\n[5. Thicken]")
gr = build.grid(size_x=2, size_z=2, rows=5, cols=5)
for mode, lo, hi in (("both", -0.1, 0.1), ("outward", 0.0, 0.2), ("inward", -0.2, 0.0)):
    o, _ = TH.thicken(gr, thickness=0.2, mode=mode)
    y = P_(o)[:, 1]
    check(f"{mode}: y spans [{lo}, {hi}]", abs(y.min() - lo) < 1e-5 and abs(y.max() - hi) < 1e-5, (y.min(), y.max()))
check("  groups thickenFront / Back / Side; 16 front + 16 back + 16 side faces",
      all(o.get_group(PRIM, n).sum() == 16 for n in ("thickenFront", "thickenBack", "thickenSide")))
sp = build.sphere(radius=1.0, cols=24, rows=12)
os_, _ = TH.thicken(sp, thickness=0.1, mode="inward")
r = np.linalg.norm(P_(os_), axis=1)
check("closed sphere, inward: hollow shell with skins at r = 1 and r ~ 0.9, no side walls",
      abs(r.max() - 1) < 1e-4 and abs(r.min() - 0.9) < 0.01 and os_.get_group(PRIM, "thickenSide").sum() == 0)

# ═════════════════════════════════════════════ 6
print("\n[6. Curve Fillet]")
L = polyline([[0, 0, 0], [1, 0, 0], [1, 0, 1]])
fo, fr = CF.curve_fillet(L, radius=0.3, divisions=8)
Pf = P_(fo)
C = np.array([0.7, 0, 0.3])
arcp = Pf[1:-1]
check("90 deg corner: 9 arc points, all 0.3 from the centre (0.7, 0, 0.3)",
      len(arcp) == 9 and np.abs(np.linalg.norm(arcp - C, axis=1) - 0.3).max() < 1e-5)
check("  tangent points on the segments (0.7, 0, 0) and (1, 0, 0.3); ends kept",
      np.allclose(arcp[0], [0.7, 0, 0], atol=1e-6) and np.allclose(arcp[-1], [1, 0, 0.3], atol=1e-6)
      and np.allclose(Pf[0], [0, 0, 0]) and np.allclose(Pf[-1], [1, 0, 1]))
fl, _ = CF.curve_fillet(L, radius=5.0, divisions=4)
check("Limit Radius: setback capped at half the shorter segment (tangent points at the midpoints)",
      np.allclose(P_(fl)[1], [0.5, 0, 0], atol=1e-6) and np.allclose(P_(fl)[-2], [1, 0, 0.5], atol=1e-6))
st = polyline([[0, 0, 0], [1, 0, 0], [2, 0, 0]])
so, srp = CF.curve_fillet(st, radius=0.3)
check("straight corner untouched", srp["corners_filleted"] == 0 and so.npoints == 3)
sq = polyline([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], closed=True)
qo, qr = CF.curve_fillet(sq, radius=0.2, divisions=4)
check("closed square: 4 arcs, 20 points, one closed primitive", qr["corners_filleted"] == 4 and qo.npoints == 20
      and qo.nprims == 1 and bool(qo.prim_closed[0]))
z0, zr = CF.curve_fillet(L, radius=0.0)
check("negative control: radius 0 changes nothing", zr["corners_filleted"] == 0 and np.allclose(P_(z0), P_(L)))

# ═════════════════════════════════════════════ 7
print("\n[7. Pack / Unpack]")


def same(a, b):
    if a.npoints != b.npoints or a.nprims != b.nprims or not np.array_equal(a.vertex_point, b.vertex_point):
        return False, "topology"
    for cls in ("point", "vertex", "prim"):
        if set(a.attribs[cls]) != set(b.attribs[cls]):
            return False, (cls, set(a.attribs[cls]) ^ set(b.attribs[cls]))
        for k in a.attribs[cls]:
            x, y = a.attribs[cls][k], b.attribs[cls][k]
            if not np.array_equal(np.asarray(x), np.asarray(y)):
                return False, (cls, k)
    return True, ""


box = build.box(divisions=(2, 2, 2)) if hasattr(build, "box") else node("Box")[0]
src = box.copy()
src.set(PRIM, "Cd", rng.uniform(0, 1, (src.nprims, 3)).astype(np.float32))
tp = Geometry.from_points(rng.uniform(-2, 2, (150, 3)).astype(np.float32))
tp.set(POINT, "pscale", rng.uniform(0.2, 1, (150, 1)).astype(np.float32))
tp.set(POINT, "N", rng.normal(size=(150, 3)).astype(np.float32))
tp.set(POINT, "Cd", rng.uniform(0, 1, (150, 3)).astype(np.float32))
tp.set(POINT, "w", rng.uniform(0, 1, (150, 1)).astype(np.float32))
for kw in ({}, {"target_prim_attribs": "w", "mult_attribs": "Cd"}):
    a = CT.copy_to_points(src, tp, **kw)
    p = CT.copy_to_points(src, tp, pack=True, **kw)
    u, _ = PK.unpack(p)
    ok, why = same(a, u)
    check(f"Copy to Points packed -> Unpack == Copy to Points {kw or ''}", ok and p.nprims == 150
          and np.all(p.prim_type == PRIM_PACKED), why)
two_src = ops.merge(box, build.sphere(radius=0.5, cols=8, rows=4))
two_src.set_string(PRIM, "name", np.array(["a"] * box.nprims + ["b"] * (two_src.nprims - box.nprims), dtype=object))
tp2 = tp.copy()
tp2.set_string(POINT, "name", np.array(["a", "b"] * 75, dtype=object))
a = CT.copy_to_points(two_src, tp2, piece_attrib="name")
u, ru = PK.unpack(CT.copy_to_points(two_src, tp2, piece_attrib="name", pack=True))
ok, why = same(a, u)
check("  with a piece attribute (two pieces, two instance sets)", ok and ru["pieces"] == 2, why)
p = CT.copy_to_points(src, tp, pack=True)
args = ((0.5, -1, 2), (15, 30, 45), (1, 2, 0.5))
ta = ops.transform(CT.copy_to_points(src, tp), *args)
tu, _ = PK.unpack(ops.transform(p, *args))
check("Transform on packed copies then Unpack == Transform on the copies", np.abs(P_(ta) - P_(tu)).max() < 1e-5,
      np.abs(P_(ta) - P_(tu)).max())
tg = ops.transform(p, (5, 0, 0), group="0-9")
tgu, _ = PK.unpack(tg)
moved = np.abs(P_(tgu) - P_(PK.unpack(p)[0]))[:, 0].reshape(150, -1).max(1)
check("  Transform with a point group moves only those copies", np.all(moved[:10] > 4.9) and np.all(moved[10:] < 1e-6))
pieces = ops.merge(box, build.sphere(radius=0.5, cols=8, rows=4, center=(3, 0, 0)))
pk, rp = PK.pack(pieces, pack_by="connectivity")
back, _ = PK.unpack(pk)
check("Pack (connectivity) -> Unpack gives the input's points back", rp["packed"] == 2 and back.npoints == pieces.npoints
      and np.abs(np.sort(P_(back), 0) - np.sort(P_(pieces), 0)).max() < 1e-5)
check("  packed points sit at the piece centroids", np.allclose(np.sort(P_(pk), 0),
                                                                np.sort([P_(box).mean(0), [3, 0, 0]], 0), atol=1e-5))
mg = ops.merge(p, box)
check("Merge keeps packed primitives (and the polygons)", PK.is_packed(mg) and PK.unpack(mg)[0].nprims ==
      PK.unpack(p)[0].nprims + box.nprims)
bl = node("Blast", geo=p, group="0-49", cls="prim")[0]
check("Blast removes packed primitives like any other", bl.nprims == 100 and PK.is_packed(bl))
fac = node("Facet", geo=p, unique_points=True)[0] if "PCG_Facet" in N else None
ref = node("Facet", geo=PK.unpack(p)[0], unique_points=True)[0] if fac is not None else None
check("a node that does not know packed primitives (Facet) gets them unpacked automatically",
      fac is not None and not PK.is_packed(fac) and fac.npoints == ref.npoints)
tr = node("Transform", geo=p, tx=1.0, ty=0.0, tz=0.0, rx=0.0, ry=0.0, rz=0.0, sx=1.0, sy=1.0, sz=1.0)[0]
check("  an aware node (Transform) keeps them packed", PK.is_packed(tr))
cp = node("CopyToPoints", source=box, points=p, source_group="", target_group="", transform_using_orientations=False,
          up_x=0.0, up_y=1.0, up_z=0.0, piece_attribute="", target_point_attributes="", target_prim_attributes="",
          multiply_attributes="", rotate_attributes="N v up")[0]
check("Copy to Points onto packed targets: one copy per packed point", cp.npoints == 150 * box.npoints)
raw = VP.encode(p)
hl = struct.unpack("<I", raw[4:8])[0]
hdr = json.loads(raw[8:8 + hl])
inst = hdr.get("instances", [])
check("viewport payload: one instance set of 150 copies of the box", len(inst) == 1 and inst[0]["count"] == 150
      and inst[0]["tris"] == len(box.triangles()), inst)
b = hdr["buffers"]["i0_matrix"]
mtx = np.frombuffer(raw, np.float32, b["length"] // 4, 8 + hl + b["offset"]).reshape(150, 4, 4).transpose(0, 2, 1)
pt0 = np.r_[P_(box)[0], 1.0]
want = P_(PK.unpack(p)[0])[0]
check("  matrices (column-major) put a piece point where Unpack puts it", np.abs((mtx[0] @ pt0)[:3] - want).max() < 1e-4)
allu = P_(PK.unpack(p)[0])
check("  bounding box covers every copy", np.all(np.asarray(hdr["bbox"][0]) <= allu.min(0) + 1e-4)
      and np.all(np.asarray(hdr["bbox"][1]) >= allu.max(0) - 1e-4))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
