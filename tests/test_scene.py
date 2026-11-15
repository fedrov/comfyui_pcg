"""
Scene generation after SideFX Labs: Lot Subdivision, Building Generator, COP WFC, LOD Create, Impostor Textures.
Analytic checks (areas, counts, directions, coverage) with negative controls.
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
import json
import numpy as np
import fakecomfy  # noqa: F401
from comfyui_pcg import nodes as N, panel_specs as PS
from comfyui_pcg.geo import Geometry, POINT, VERTEX, PRIM, DETAIL, build, ops
from comfyui_pcg.geo import lotsubdiv as L, building as B, lodcreate as LC, impostor as IM
from comfyui_pcg.geo.cop import wfc as W
from comfyui_pcg.geo.cop.core import CopImage
from comfyui_pcg.geo.cop.pixel import getn

OK = []
def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)

def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


def poly(pts, y=0.0):
    p = np.array([[x, y, z] for x, z in pts], float)
    return Geometry.from_mesh(p, [list(range(len(p)))[::-1]])        # normal up


def prim_pts(g, i):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    return P[np.asarray(g.vertex_point)[g.prim_offset[i]:g.prim_offset[i + 1]]]


def area3(q):
    return 0.5 * np.linalg.norm(np.cross(q - q.mean(0), np.roll(q, -1, 0) - q.mean(0)).sum(0))


M = N.NODE_CLASS_MAPPINGS
print("-- Lot Subdivision")
RECT = poly([(0, 0), (40, 0), (40, 30), (0, 30)])
for it in (0, 1, 2, 4):
    o, rep = L.lot_subdivision(RECT, iterations=it)
    ar = np.asarray(o.get(PRIM, "area")).reshape(-1)
    check(f"{it} iterations give {2 ** it} lots of equal area, the block's area in all",
          o.nprims == 2 ** it and abs(ar.sum() - 1200) < 1e-3 and np.allclose(ar, 1200 / 2 ** it, rtol=1e-5))
o, _ = L.lot_subdivision(RECT, iterations=1)
xs = sorted(round(float(prim_pts(o, i)[:, 0].max()), 4) for i in range(2))
check("Bounding Box cuts across the longer side (x = 20 on a 40 x 30 block)", xs == [20.0, 40.0], xs)
o, _ = L.lot_subdivision(RECT, iterations=4)
real = [area3(prim_pts(o, i)) for i in range(o.nprims)]
check("the area attribute is each lot's real area", np.allclose(real, np.asarray(o.get(PRIM, "area")).reshape(-1), rtol=1e-4))
check("lots share points: 16 lots on a 5 x 5 lattice of 25 points (negative control: 64 if unshared)", o.npoints == 25, o.npoints)
check("lot / block attributes: lot = 0..15, block = the source prim",
      sorted(np.asarray(o.get(PRIM, "lot")).reshape(-1).tolist()) == list(range(16))
      and (np.asarray(o.get(PRIM, "block")) == 0).all())
up = np.asarray(ops.compute_normals(o, add_to="prim").get(PRIM, "N"))
check("the lots keep the block's winding (normal up)", (up[:, 1] > 0.99).all())
o, _ = L.lot_subdivision(RECT, iterations=4, min_lot_size=200)
ar = np.asarray(o.get(PRIM, "area")).reshape(-1)
check("Minimum Lot Size stops the cutting: lots of 150 (cut from 300) are left, none smaller",
      o.nprims == 8 and np.allclose(ar, 150), (o.nprims, ar.min()))
a0 = np.asarray(L.lot_subdivision(RECT, iterations=4)[0].get(PRIM, "area")).reshape(-1)
a1 = np.asarray(L.lot_subdivision(RECT, iterations=4, irregularity=1.0, seed=3)[0].get(PRIM, "area")).reshape(-1)
check("Irregularity gives lots of varying size, the total unchanged", a0.std() < 1e-3 and a1.std() > 20 and abs(a1.sum() - 1200) < 1e-2,
      round(float(a1.std()), 1))
a2 = np.asarray(L.lot_subdivision(RECT, iterations=4, irregularity=1.0, seed=3)[0].get(PRIM, "area")).reshape(-1)
a3 = np.asarray(L.lot_subdivision(RECT, iterations=4, irregularity=1.0, seed=4)[0].get(PRIM, "area")).reshape(-1)
check("the same seed repeats, another seed differs", np.allclose(a1, a2) and not np.allclose(np.sort(a1), np.sort(a3)))
SLANT = poly([(0, 0), (40, 10), (36, 26), (-4, 16)])               # a block turned off the axes
ob, _ = L.lot_subdivision(SLANT, iterations=1, alignment="bounding_box")
ol, _ = L.lot_subdivision(SLANT, iterations=1, alignment="longest_edge")
def cut_dir(o):
    P = np.asarray(o.get(POINT, "P"))
    a, b = [set(np.asarray(o.vertex_point)[o.prim_offset[i]:o.prim_offset[i + 1]].tolist()) for i in range(2)]
    s = sorted(a & b)
    d = P[s[1]] - P[s[0]]
    return d / np.linalg.norm(d)
long_dir = np.array([40, 0, 10]) / np.linalg.norm([40, 0, 10])
check("Longest Edge cuts perpendicular to the longest edge", abs(cut_dir(ol) @ long_dir) < 1e-5)
check("negative control: Bounding Box cuts along an axis instead", abs(abs(cut_dir(ob)[2]) - 1) < 1e-6 and abs(cut_dir(ob) @ long_dir) > 0.1)
UU = poly([(0, 0), (50, 0), (50, 40), (40, 40), (40, 10), (10, 10), (10, 40), (0, 40)])
pc = L.split_polygon(np.array([(0, 0), (50, 0), (50, 40), (40, 40), (40, 10), (10, 10), (10, 40), (0, 40)], float), [0, 20], [1, 0])
check("a cut through a concave (U-shaped) block gives three pieces whose areas add up (2 x 200 + 700 = 1100)",
      len(pc) == 3 and sorted(round(abs(L._area(q))) for q in pc) == [200, 200, 700])
ou, _ = L.lot_subdivision(UU, iterations=3)
check("... and the node keeps the total area on it", abs(np.asarray(ou.get(PRIM, "area")).sum() - 1100) < 1e-2, ou.nprims)
oc, rep = L.lot_subdivision(RECT, iterations=4, cluster_lots=True, clusters=5, cluster_seed=1)
ar = np.asarray(oc.get(PRIM, "area")).reshape(-1)
check("Cluster Lots joins 16 lots into Number of Clusters parcels, area kept, each a whole number of lots",
      oc.nprims == 5 and abs(ar.sum() - 1200) < 1e-2 and np.allclose(ar / 75, np.rint(ar / 75), atol=1e-4), ar.tolist())
check("... as single outlines: their real areas match", np.allclose([area3(prim_pts(oc, i)) for i in range(5)], ar, rtol=1e-4))
g2 = Geometry.from_mesh(np.array([[0, 0, 0], [40, 0, 0], [40, 0, 30], [0, 0, 30], [100, 0, 0], [140, 0, 0], [140, 0, 30], [100, 0, 30]], float),
                        [[3, 2, 1, 0], [7, 6, 5, 4]])
g2.set_string(PRIM, "zone", np.array(["res", "com"]))
o2, rep2 = L.lot_subdivision(g2, group="0", iterations=2)
z = np.asarray(o2.get(PRIM, "zone")).reshape(-1)
check("Group: only those polygons are cut, the rest pass through; prim attributes are copied to the lots",
      o2.nprims == 5 and (z == "res").sum() == 4 and (z == "com").sum() == 1 and rep2["lots"] == 4)
TILT = Geometry.from_mesh(np.array([[0, 0, 0], [10, 5, 0], [10, 5, 8], [0, 0, 8]], float), [[3, 2, 1, 0]])
ot, _ = L.lot_subdivision(TILT, iterations=3)
Pt = np.asarray(ot.get(POINT, "P"), np.float64)
check("a tilted block is cut in its own plane", np.abs(Pt[:, 1] - 0.5 * Pt[:, 0]).max() < 1e-5 and ot.nprims == 8)
err("an unknown alignment is refused", lambda: L.lot_subdivision(RECT, alignment="diagonal"), "one of")

print("-- Building Generator")
FP = poly([(0, 0), (12, 0), (12, 9), (0, 9)])
b, rep = B.building_generator(FP, floors_min=3, floors_max=3, corners=False, top_ledge=False, roof="flat",
                              facade_pattern="wall")
P = np.asarray(b.get(POINT, "P"), np.float64)
part = np.asarray(b.get(PRIM, "part")).reshape(-1)
check("3 floors x 3 m: the building is 9 m tall on its footprint", np.allclose(P.min(0), [0, 0, 0]) and np.allclose(P.max(0), [12, 9, 9]))
check("blank walls: 3 floors x (4 + 3 + 4 + 3) bays of 3 m = 42 wall quads and one roof",
      (part == "wall").sum() == 42 and (part == "roof").sum() == 1 and b.nprims == 43, dict(rep["parts"]))
wa = sum(area3(prim_pts(b, i)) for i in np.nonzero(part == "wall")[0])
check("the walls' area = perimeter x height (42 x 9 = 378 m²), the roof's = the footprint's (108 m²)",
      abs(wa - 378) < 1e-3 and abs(area3(prim_pts(b, int(np.nonzero(part == "roof")[0][0]))) - 108) < 1e-3)
nrm = np.asarray(ops.compute_normals(b, add_to="prim").get(PRIM, "N"), np.float64)
cen = np.array([prim_pts(b, i).mean(0) for i in range(b.nprims)])
out = cen - np.array([6, 0, 4.5]); out[:, 1] = 0
wl = part == "wall"
check("walls face out of the building, the roof up", ((nrm[wl] * out[wl]).sum(1) > 0).all() and nrm[part == "roof"][0, 1] > 0.99)
uv = np.asarray(b.get(VERTEX, "uv"), np.float64)
check("uv is in metres: v runs 0..9 up the wall, u along it", abs(uv[:, 1][np.repeat(wl, 4)].max() - 9) < 1e-5
      and abs(np.ptp(uv[:, 0][np.repeat(wl, 4)]) - 12) < 1e-5)
bw, repw = B.building_generator(FP, floors_min=2, floors_max=2, corners=False, top_ledge=False, roof="flat",
                                facade_pattern="window", window_width=0.5, window_height=0.5, inset=0.2)
pw = np.asarray(bw.get(PRIM, "part")).reshape(-1)
ga = sum(area3(prim_pts(bw, i)) for i in np.nonzero(pw == "glass")[0])
wa2 = sum(area3(prim_pts(bw, i)) for i in np.nonzero(pw == "wall")[0])
check("windows: one pane per bay (28), glass = 1/4 of the wall (width 0.5 x height 0.5), wall + glass = the facade",
      (pw == "glass").sum() == 28 and abs(ga - 252 * 0.25) < 1e-3 and abs(wa2 + ga - 252) < 1e-3)
Pw = np.asarray(bw.get(POINT, "P"), np.float64)
gi = np.nonzero(pw == "glass")[0]
gc = np.array([prim_pts(bw, i).mean(0) for i in gi])
depth = np.minimum.reduce([gc[:, 0], 12 - gc[:, 0], gc[:, 2], 9 - gc[:, 2]])
check("the glass is recessed by Inset (0.2 m behind the wall plane)", np.allclose(depth, 0.2, atol=1e-5))
check("frames are the four reveal faces of every opening", (pw == "frame").sum() == 4 * 28)
bp, _ = B.building_generator(FP, floors_min=1, floors_max=1, corners=False, top_ledge=False, roof="flat",
                             facade_pattern="door wall wall wall")
md = np.asarray(bp.get(PRIM, "module")).reshape(-1)
pp = np.asarray(bp.get(PRIM, "part")).reshape(-1)
check("the pattern repeats along the wall: on the 12 m walls 1 bay in 4 is a door",
      (pp == "door").sum() == 4 and set(md) == {"door", "wall", "roof"}, int((pp == "door").sum()))
bo, repo = B.building_generator(FP, floors_min=3, floors_max=3, corners=False, top_ledge=False, roof="flat",
                                facade_pattern="wall", floor_overrides="0: height=4.5 pattern=shopfront\n-1: height=2")
po = np.asarray(bo.get(PRIM, "part")).reshape(-1)
fo = np.asarray(bo.get(PRIM, "floor")).reshape(-1)
check("Floor Overrides: ground floor 4.5 m with shopfronts, top floor 2 m -> 9.5 m; glass only on floor 0",
      abs(np.asarray(bo.get(POINT, "P"))[:, 1].max() - 9.5) < 1e-5 and set(fo[po == "glass"]) == {0})
bh = FP.copy(); bh.set(PRIM, "height", np.array([20.0]))
check("Height Attribute sets the floors (20 m / 3 m -> 7 floors, 21 m)",
      abs(np.asarray(B.building_generator(bh, roof="flat", top_ledge=False)[0].get(POINT, "P"))[:, 1].max() - 21) < 1e-5)
bf = FP.copy(); bf.set(PRIM, "floors", np.array([4.0]))
check("Floors Attribute sets them otherwise", B.building_generator(bf)[1]["floors"] == 4)
fl = [B.building_generator(FP, floors_min=2, floors_max=8, seed=s)[1]["floors"] for s in range(12)]
check("without either, a seeded number between Floors Min and Max", min(fl) >= 2 and max(fl) <= 8 and len(set(fl)) > 2, fl)
bc, repc = B.building_generator(FP, floors_min=2, floors_max=2, facade_pattern="wall", corner_width=0.5, top_ledge=False, roof="flat")
pcn = np.asarray(bc.get(PRIM, "part")).reshape(-1)
ca = sum(area3(prim_pts(bc, i)) for i in np.nonzero(pcn == "corner")[0])
check("Corners: a strip at both ends of every wall (2 x 4 walls x 2 floors, 0.5 m x 3 m each)",
      (pcn == "corner").sum() == 16 and abs(ca - 16 * 1.5) < 1e-4)
bl, _ = B.building_generator(FP, floors_min=2, floors_max=2, facade_pattern="wall", corners=False, roof="flat",
                             top_ledge=True, top_ledge_height=0.25, ledge_depth=0.15)
Pl = np.asarray(bl.get(POINT, "P"), np.float64)
check("the top ledge stands out by Ledge Depth all round (mitred corners)",
      np.allclose(Pl.min(0)[[0, 2]], -0.15) and np.allclose(Pl.max(0)[[0, 2]], [12.15, 9.15]))
br, _ = B.building_generator(FP, floors_min=2, floors_max=2, facade_pattern="wall", corners=False, top_ledge=False,
                             roof="parapet", parapet_height=0.8, parapet_thickness=0.3)
pr = np.asarray(br.get(PRIM, "part")).reshape(-1)
ra = area3(prim_pts(br, int(np.nonzero(pr == "roof")[0][0])))
check("Parapet: 0.8 m above the roof, the roof inside it (11.4 x 8.4 m)",
      abs(np.asarray(br.get(POINT, "P"))[:, 1].max() - 6.8) < 1e-5 and abs(ra - 11.4 * 8.4) < 1e-3)
# a module library: a panel with a box standing 0.5 m out of the wall
LIB = Geometry.from_mesh(np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0], [0.5, 0.25, 0.5], [1.5, 0.25, 0.5], [1.5, 0.75, 0.5], [0.5, 0.75, 0.5]], float),
                         [[0, 1, 2, 3], [4, 5, 6, 7]])
LIB.set_string(PRIM, "name", np.array(["bay", "bay"]))
LIB.set_string(PRIM, "part", np.array(["wall", "balcony"]))
bm, repm = B.building_generator(FP, LIB, floors_min=1, floors_max=1, corners=False, top_ledge=False, roof="flat",
                                facade_pattern="bay")
pm = np.asarray(bm.get(PRIM, "part")).reshape(-1)
Pm = np.asarray(bm.get(POINT, "P"), np.float64)
check("a library module is fitted to the bay (x to the width, y to the floor) and keeps its parts",
      (pm == "balcony").sum() == 14 and abs(sum(area3(prim_pts(bm, i)) for i in np.nonzero(pm == "wall")[0]) - 126) < 1e-3)
check("... +z of the module points out of the building (the balcony stands 0.5 m proud)",
      np.allclose(Pm.min(0)[[0, 2]], -0.5) and np.allclose(Pm.max(0)[[0, 2]], [12.5, 9.5]))
err("an unknown module names what exists", lambda: B.building_generator(FP, facade_pattern="portcullis"), "portcullis")
CW = Geometry.from_mesh(np.asarray(FP.get(POINT, "P")), [[0, 1, 2, 3]])          # the other winding
Pc = np.asarray(B.building_generator(CW, floors_min=3, floors_max=3, corners=False, top_ledge=False, roof="flat", facade_pattern="wall")[0].get(POINT, "P"))
check("the footprint's winding does not matter", np.allclose(np.sort(Pc, axis=0), np.sort(P, axis=0), atol=1e-6))
lots, _ = L.lot_subdivision(poly([(0, 0), (60, 0), (60, 40), (0, 40)]), iterations=3)
town, rt = B.building_generator(lots, seed=2)
bid = np.asarray(town.get(PRIM, "building")).reshape(-1)
check("lots -> buildings: one per lot, numbered, a prim group per part",
      rt["buildings"] == 8 and set(bid) == set(range(8)) and all(town.get_group(PRIM, k) is not None for k in ("wall", "glass", "roof")))
cf = np.asarray(B.building_generator(FP, floors_min=3, floors_max=3, color_floors=True)[0].get(PRIM, "Cd"))
check("Color Floors colours by floor", len(np.unique(cf.round(3), axis=0)) >= 4)

bi_, _ = B.building_generator(FP, floors_min=2, floors_max=2, corners=False, top_ledge=False, roof="flat",
                              facade_pattern="wall", footprint_inset=1.5)
Pi_ = np.asarray(bi_.get(POINT, "P"), np.float64)
check("Footprint Inset sets the walls back from the footprint (12 x 9 -> 9 x 6 m)",
      np.allclose(Pi_.min(0)[[0, 2]], 1.5) and np.allclose(Pi_.max(0)[[0, 2]], [10.5, 7.5]))
check("... and a footprint too small for it gets no building",
      B.building_generator(poly([(0, 0), (3, 0), (3, 3), (0, 3)]), footprint_inset=1.6)[1]["buildings"] == 0)
bpl, rpl = B.building_generator(FP, floors_min=2, floors_max=2, corners=False, top_ledge=False, roof="flat",
                                facade_pattern="wall", foundation_depth=3.0)
ppl = np.asarray(bpl.get(PRIM, "part")).reshape(-1)
npl = np.asarray(ops.compute_normals(bpl, add_to="prim").get(PRIM, "N"), np.float64)
cpl = np.array([prim_pts(bpl, i).mean(0) for i in range(bpl.nprims)]) - np.array([6, 0, 4.5])
cpl[:, 1] = 0
mpl = ppl == "plinth"
check("Foundation Depth: a 3 m plinth below the base round the footprint, facing out, floor -2",
      mpl.sum() == 4 and abs(np.asarray(bpl.get(POINT, "P"))[:, 1].min() + 3) < 1e-6
      and ((npl[mpl] * cpl[mpl]).sum(1) > 0).all() and (np.asarray(bpl.get(PRIM, "floor")).reshape(-1)[mpl] == -2).all())
check("negative control: without it nothing goes below the base", np.asarray(b.get(POINT, "P"))[:, 1].min() >= -1e-9)
FA = FP.copy()
FA.set_string(PRIM, "name", np.array(["Town_07"]))
FA.set(PRIM, "lot", np.array([42], np.int32))
ba_, _ = B.building_generator(FA, floors_min=1, floors_max=1)
check("the footprint's prim attributes go to every face of its building",
      set(np.asarray(ba_.get(PRIM, "name")).reshape(-1)) == {"Town_07"} and (np.asarray(ba_.get(PRIM, "lot")) == 42).all())

print("-- COP WFC")
s = np.zeros((8, 8, 3), np.float32); s[3, :] = 1; s[:, 5] = 1                    # two crossing roads
S = CopImage(8, 8, {"C": s})
o, rep = W.wfc(S, xres=40, yres=30, pattern_size=3, wrap_input=True, seed=1)
a = getn(o, "C")[..., 0]
ids = getn(o, "C_id")[..., 0]
check("the output grid has the asked size and only the sample's colours", a.shape == (30, 40) and set(np.unique(a)) <= {0.0, 1.0})
pat, _ = W.patterns((s[..., 0] > 0.5).astype(int), 3, True)
have = {tuple(p.reshape(-1)) for p in pat}
win = np.lib.stride_tricks.sliding_window_view((a > 0.5).astype(int), (3, 3)).reshape(-1, 9)
check("every 3 x 3 window of the output is a window of the sample", all(tuple(w) in have for w in win), len(have))
rnd = (np.random.default_rng(0).random((30, 40)) > 0.5).astype(int)
wr = np.lib.stride_tricks.sliding_window_view(rnd, (3, 3)).reshape(-1, 9)
check("negative control: a random image is not", sum(tuple(w) in have for w in wr) < 0.5 * len(wr))
check("the id layer numbers the colours in order of appearance (0 = grass, 1 = road)", np.array_equal(ids, (a > 0.5).astype(float)))
o2, _ = W.wfc(S, xres=40, yres=30, wrap_input=True, seed=1)
o3, _ = W.wfc(S, xres=40, yres=30, wrap_input=True, seed=2)
check("the same seed repeats, another seed differs", np.array_equal(getn(o2, "C"), getn(o, "C")) and not np.array_equal(getn(o3, "C"), getn(o, "C")))
ot, _ = W.wfc(S, xres=24, yres=24, wrap_input=True, tileable=True, seed=3)
at = (getn(ot, "C")[..., 0] > 0.5).astype(int)
wt = np.lib.stride_tricks.sliding_window_view(np.pad(at, ((0, 2), (0, 2)), mode="wrap"), (3, 3)).reshape(-1, 9)
check("Produce Tileable Output: the windows across the wrap are sample windows too", all(tuple(w) in have for w in wt))
c = np.zeros((20, 20, 3), np.float32); mk = np.zeros((20, 20, 1), np.float32)
c[10, :] = 1; mk[10, :] = 1                                                      # a road pinned along row 10
mk[2:5, 2:5] = 1                                                                 # and a pinned patch of grass
CN = CopImage(20, 20, {"C": c, "mask": mk})
oc, _ = W.wfc(S, CN, wrap_input=True, seed=5)
ac = getn(oc, "C")[..., 0]
check("constraints fix cells (a road along row 10, grass in a patch) and set the grid size",
      ac.shape == (20, 20) and (ac[10] == 1).all() and (ac[2:5, 2:5] == 0).all())
on, _ = W.wfc(S, CN, wrap_input=True, seed=5, respect_constraints=False)
check("negative control: with Respect Constraints off the row is not all road", not (getn(on, "C")[10, :, 0] == 1).all())
bad = CopImage(20, 20, {"C": np.full((20, 20, 3), 0.5, np.float32), "mask": mk})
err("a constraint colour the sample lacks is reported with its cell", lambda: W.wfc(S, bad, wrap_input=True), "does not contain")
p0, c0 = W.patterns(np.array([[0, 1], [1, 0]]), 2, True)
check("pattern counts: a 2 x 2 checker has 2 wrapping 2 x 2 patterns, each seen twice", len(p0) == 2 and c0.tolist() == [2, 2])
pr_, _ = W.patterns(np.array([[0, 0, 1], [0, 0, 0], [0, 0, 0]]), 2, False, True)
pn_, _ = W.patterns(np.array([[0, 0, 1], [0, 0, 0], [0, 0, 0]]), 2, False, False)
check("Allow Rotations adds the turned and mirrored patterns (2 -> 5)", len(pn_) == 2 and len(pr_) == 5, (len(pn_), len(pr_)))
big = np.kron(s, np.ones((4, 4, 1), np.float32))                                 # the sample drawn at 4 px per cell
ob, repb = W.wfc(CopImage(32, 32, {"C": big}), sample_cols=8, sample_rows=8, xres=40, yres=30, wrap_input=True, seed=1)
check("Sample Grid Size reads a picture drawn at 4 pixels per cell as the same 8 x 8 sample", np.array_equal(getn(ob, "C"), getn(o, "C")))
oz, _ = W.wfc(S, xres=10, yres=6, wrap_input=True, cell_pixels=4)
check("Cell Pixels enlarges the output image", (oz.xres, oz.yres) == (40, 24) and np.array_equal(getn(oz, "C")[::4, ::4], getn(W.wfc(S, xres=10, yres=6, wrap_input=True)[0], "C")))
imp = np.zeros((4, 4, 3), np.float32); imp[0, 0] = 1; imp[3, 3] = (0, 1, 0)      # a red and a green cell that never meet
err("an unsolvable set-up says what to change",
    lambda: W.wfc(CopImage(4, 4, {"C": imp}), CopImage(6, 1, {"C": np.array([[[1, 1, 1], [0, 1, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]]], np.float32),
                                                                 "mask": np.array([[[1], [1], [0], [0], [0], [0]]], np.float32)}),
                  pattern_size=2, attempts=3), "no solution")
err("a pattern size larger than the sample is refused", lambda: W.wfc(S, pattern_size=9), "does not fit")

print("-- LOD Create")
SPH = build.sphere(1.0, 48, 32)
T0 = int((SPH.prim_sizes() - 2).sum())
o, rep = LC.lod_create(SPH, "100 50 25 10")
tr = [r["triangles"] for r in rep["lods"]]
check("four levels at 100 / 50 / 25 / 10 % of the triangles", tr[0] == T0 and all(abs(t / T0 - p) < 0.01 for t, p in zip(tr, (1, .5, .25, .1))), tr)
lod = np.asarray(o.get(PRIM, "lod")).reshape(-1)
nm = np.asarray(o.get(PRIM, "name")).reshape(-1)
check("lod / part / name attributes and LODn groups", set(nm) == {"LOD0", "LOD1", "LOD2", "LOD3"}
      and all(int(o.get_group(PRIM, f"LOD{k}").sum()) == int((lod == k).sum()) for k in range(4))
      and set(np.asarray(o.get(PRIM, "part")).reshape(-1)) == set(nm))
dd = [r["distance"] for r in rep["lods"]]
check("Threshold Distance defaults to 0, then First Distance doubling (0 20 40 80)", dd == [0, 20, 40, 80]
      and np.allclose(np.unique(np.asarray(o.get(PRIM, "lod_distance"))), dd))
check("... or is given per level", [r["distance"] for r in LC.lod_create(SPH, "100 50", "0 35")[1]["lods"]] == [0, 35])
Pl = np.asarray(ops.delete_prims(o, lod == 3).get(POINT, "P"), np.float64)
used = np.unique(np.asarray(ops.delete_prims(o, lod == 3).vertex_point))
check("the reduced level still lies on the sphere (radius within 4 %)", np.abs(np.linalg.norm(Pl[used], axis=1) - 1).max() < 0.04)
check("Recalculate Normals writes unit vertex normals on every level", o.has(VERTEX, "N")
      and np.allclose(np.linalg.norm(np.asarray(o.get(VERTEX, "N"))[:, :3], axis=1), 1, atol=1e-3))
os_, _ = LC.lod_create(SPH, "100 50 25", view="single", level=2)
check("Single LOD shows only that level", set(np.asarray(os_.get(PRIM, "lod")).reshape(-1)) == {2})
od, _ = LC.lod_create(SPH, "100 50 25", view="debug", spacing=1.5)
Pd = np.asarray(od.get(POINT, "P")); ld = np.asarray(od.get(PRIM, "lod")).reshape(-1)
cx = [float(prim_pts(od, int(np.nonzero(ld == k)[0][0]))[:, 0].mean()) for k in range(3)]
check("Debug All LOD lays the levels out side by side (steps of 1.5 widths = 3)", abs(Pd[:, 0].max() - Pd[:, 0].min() - 8) < 0.05)
oi, ri = LC.lod_create(SPH, "100 50 10", last_lod_impostor=True)
li = np.asarray(oi.get(PRIM, "lod")).reshape(-1)
check("Last LOD is Impostor: two crossed cards with uv 0..1, flagged",
      int((li == 2).sum()) == 2 and (np.asarray(oi.get(PRIM, "impostor")).reshape(-1)[li == 2] == 1).all()
      and ri["lods"][2]["impostor"] and ri["lods"][2]["triangles"] == 4)
two = ops.merge(SPH, build.box(size=(1, 1, 1)))
two.set_string(PRIM, "name", np.array(["ball"] * SPH.nprims + ["crate"] * (two.nprims - SPH.nprims)))
oa, ra = LC.lod_create(two, "100 50")
check("assets (prim name) get their own chains: ball_LOD0, ball_LOD1, crate_LOD0, crate_LOD1",
      set(np.asarray(oa.get(PRIM, "name")).reshape(-1)) == {"ball_LOD0", "ball_LOD1", "crate_LOD0", "crate_LOD1"})
err("distances must match the levels", lambda: LC.lod_create(SPH, "100 50", "0 10 20"), "2 LODs")
err("a level that does not exist is named", lambda: LC.lod_create(SPH, "100 50", view="single", level=5), "does not exist")

print("-- Impostor Textures")
D = IM.frame_directions("octahedron", 5)
check("octahedron: unit directions; centre frame = up, corners = down, edge centres = the four horizontal axes",
      np.allclose(np.linalg.norm(D, axis=-1), 1) and np.allclose(D[2, 2], [0, 1, 0]) and np.allclose(D[0, 0], [0, -1, 0])
      and np.allclose(D[2, 4], [1, 0, 0]) and np.allclose(D[4, 2], [0, 0, 1]) and np.allclose(D[2, 0], [-1, 0, 0]))
Hd = IM.frame_directions("hemi_octahedron", 5)
check("hemi-octahedron: never below the horizon, centre = up, the border on the horizon",
      Hd[..., 1].min() > -1e-9 and np.allclose(Hd[2, 2], [0, 1, 0]) and np.allclose(Hd[0, :, 1], 0, atol=1e-9))
Fd = IM.frame_directions("fixed_axis", 4, 2, elevation=30)
check("fixed axis: 8 views 45° apart, all at the elevation",
      np.allclose(Fd[..., 1], 0.5) and np.allclose((Fd.reshape(-1, 3)[:-1] * Fd.reshape(-1, 3)[1:]).sum(1), 0.75 * np.cos(np.pi / 4) + 0.25))
Td = IM.frame_directions("3d", 8, 4)
check("3d: rows are elevations -67.5 .. 67.5°, columns azimuths", np.allclose(np.degrees(np.arcsin(Td[:, 0, 1])), [-67.5, -22.5, 22.5, 67.5]))
img, card, rep = IM.impostor_textures(ops.compute_normals(SPH), "octahedron", 64, 4, 4)
al = getn(img, "alpha")[..., 0]
check("a sphere fills π/4 of every frame (framed on its bounding sphere)",
      (img.xres, img.yres) == (256, 256) and all(abs(al[j * 64:(j + 1) * 64, i * 64:(i + 1) * 64].mean() - np.pi / 4) < 0.01
                                                  for i in range(4) for j in range(4)), round(float(al.mean()), 4))
Nw = getn(img, "N")
D4 = IM.frame_directions("octahedron", 4)
ok = all(np.allclose(Nw[j * 64 + 32, i * 64 + 32], D4[j, i], atol=0.06) for i in range(4) for j in range(4))
check("world normals: at each frame's centre the sphere's normal is the direction to the camera", ok)
iv, _, _ = IM.impostor_textures(ops.compute_normals(SPH), "octahedron", 64, 4, 4, normal_space="view")
check("view normals: there it is (0, 0, 1) in every frame",
      all(np.allclose(getn(iv, "N")[j * 64 + 32, i * 64 + 32], [0, 0, 1], atol=0.06) for i in range(4) for j in range(4)))
dp = getn(img, "depth")[..., 0]
check("depth: 1 at the nearest point (frame centre), 0.5 at the silhouette, 0 off the object",
      abs(dp[32, 32] - 1) < 0.01 and dp[0, 0] == 0 and 0.48 <= dp[al > 0].min() < 0.56)
BOXC = build.box(size=(1, 1, 1))
fn = np.asarray(ops.compute_normals(BOXC, add_to="prim").get(PRIM, "N"))
BOXC.set(PRIM, "Cd", np.abs(fn))                                    # x faces red, y green, z blue
ib, _, _ = IM.impostor_textures(BOXC, "octahedron", 32, 5, 5)
Cb = getn(ib, "C")
check("base colour comes from Cd: the frame from +x shows red, from above green, from +z blue",
      np.allclose(Cb[2 * 32 + 16, 4 * 32 + 16], [1, 0, 0]) and np.allclose(Cb[2 * 32 + 16, 2 * 32 + 16], [0, 1, 0])
      and np.allclose(Cb[4 * 32 + 16, 2 * 32 + 16], [0, 0, 1]))
bt = getn(ib, "beauty")
check("beauty is the base colour lit: never brighter, darker on faces turned from the sun",
      (bt <= Cb + 1e-6).all() and bt[2 * 32 + 16, 0 * 32 + 16].sum() < bt[2 * 32 + 16, 4 * 32 + 16].sum())
P_ = np.asarray(card.get(POINT, "P"))
check("the card: a quad the size of the bounding sphere, uv 0..1, the settings as detail attributes",
      card.nprims == 1 and np.allclose(np.ptp(P_, axis=0), [2, 2, 0], atol=1e-5)
      and int(np.asarray(card.get(DETAIL, "frames_x")).reshape(-1)[0]) == 4
      and str(np.asarray(card.get(DETAIL, "impostor_type")).reshape(-1)[0]) == "octahedron")
iz, _, _ = IM.impostor_textures(SPH, "fixed_axis", 32, 4, 1, zoom=2.0)
check("Zoom 2 crops the sphere: the frame is covered", getn(iz, "alpha").mean() > 0.99)
err("an atlas above the limit is refused", lambda: IM.impostor_textures(SPH, "3d", 2048, 8, 8), "out of range")

print("-- nodes")
NODES = ("PCG_LotSubdivision", "PCG_BuildingGenerator", "PCG_LODCreate", "PCG_ImpostorTextures", "PCG_COPWFC")
check("the five nodes are registered, each with a panel spec that covers its widgets",
      all(n in M and set(PS.SPECS[n]["order"]) == {k for k, v in M[n].INPUT_TYPES()["required"].items()
                                                    if v[0] not in ("COPIMAGE", "GEOMETRY")} for n in NODES))
def dflt(n, **kw):
    a = {k: (s_[1]["default"] if len(s_) > 1 and isinstance(s_[1], dict) and "default" in s_[1] else s_[0][0])
         for k, s_ in M[n].INPUT_TYPES()["required"].items() if s_[0] not in ("COPIMAGE", "GEOMETRY")}
    a.update(kw)
    return a
def call(n, **kw):
    r = M[n]().run(**kw)
    return r["result"] if isinstance(r, dict) else r           # nodes with a UI part return {"ui", "result"}
g1, r1 = call("PCG_LotSubdivision", geo=RECT, **dflt("PCG_LotSubdivision"))
check("Lot Subdivision (node): defaults give 8 equal lots and a report", g1.nprims == 8 and json.loads(r1)["lots"] == 8)
g2_, r2_ = call("PCG_BuildingGenerator", geo=g1, **dflt("PCG_BuildingGenerator"))
check("Building Generator (node) on those lots: 8 buildings", json.loads(r2_)["buildings"] == 8)
g3, r3 = call("PCG_LODCreate", geo=SPH, **dflt("PCG_LODCreate"))
check("LOD Create (node): four levels", len(json.loads(r3)["lods"]) == 4)
c4, k4, r4 = call("PCG_ImpostorTextures", geo=g2_, **dflt("PCG_ImpostorTextures", sprite_resolution=32, frames_x=4))
check("Impostor Textures (node) of the buildings: a 128² atlas with the five layers and a card",
      (c4.xres, c4.yres) == (128, 128) and all(k in c4 for k in ("C", "alpha", "N", "depth", "beauty")) and k4.nprims == 1)
c5, r5 = call("PCG_COPWFC", sample=S, **dflt("PCG_COPWFC", wrap_input=True, grid_x=40, grid_y=30, rand_seed=1))
check("COP WFC (node) = the engine", np.array_equal(getn(c5, "C"), getn(o if False else W.wfc(S, xres=40, yres=30, wrap_input=True, seed=1)[0], "C")))

n = len(OK)
print(f"\n{sum(OK)}/{n} passed")
sys.exit(0 if all(OK) else 1)
