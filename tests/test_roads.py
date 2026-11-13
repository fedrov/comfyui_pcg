"""
COP HeightField Road Network (geo/cop/roads.py), checked against geometry.

  1. Flat ground: the road between two places is the straight line (length within 3 %); negative control: a wall
     (Block Layer) with one gap makes it go through the gap
  2. Grade: on a slope four times steeper than Max Grade the road climbs in switchbacks: its steepest stretch stays
     near Max Grade and it is at least rise / Max Grade long; negative control: with Max Grade 10 it goes straight up
  3. Network: three places in a row make two roads whose total is the outer distance (the middle one is on the way);
     a place behind the Block Layer is reported unreachable and skipped
  4. road_h is the ground smoothed along the road (on a plane: the plane); coordinates match HeightField to Mesh and
     COP Rasterize Curves (the mask is 1 under the destinations); road_t is the unit direction along the road
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

import comfyui_pcg  # noqa: E402,F401
from comfyui_pcg.geo import Geometry  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM  # noqa: E402
from comfyui_pcg.geo.cop import CopImage, geoimg  # noqa: E402
from comfyui_pcg.geo.cop import roads as RD  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


def img(h, **more):
    lay = {"C": np.asarray(h, np.float32)[:, :, None]}
    for k, v in more.items():
        lay[k] = np.asarray(v, np.float32)[:, :, None]
    return CopImage(h.shape[1], h.shape[0], lay)


def pts(*xz):
    return Geometry.from_points(np.array([[x, 0.0, z] for x, z in xz], np.float32))


def polylines(g):
    P = np.asarray(g.get(POINT, "P"), np.float64)
    return [P[np.asarray(g.prim_points(i))] for i in range(g.nprims)]


def length(p):
    return float(np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=1).sum())


N, WS = 129, 1000.0                       # 129 px over 1000 m: 7.75 m texels
J, I = np.meshgrid(np.arange(N), np.arange(N))
X = (J + 0.5) * WS / N - WS / 2           # HeightField to Mesh, Center on
Z = WS / 2 - (I + 0.5) * WS / N

print("── 1. Flat ground")
flat = img(np.zeros((N, N)))
g, rep = RD.road_network(flat, pts((-400, 0), (400, 0)), world_size=WS, step=1)
L1 = length(polylines(g)[0])
check(f"two places 800 m apart: one road, {L1:.0f} m long (straight within 3 %)", g.nprims == 1 and abs(L1 - 800) < 24,
      rep)
wall = (np.abs(X) < 40) & (Z < 250)       # a wall across the way, open only beyond z = 250
g2, _ = RD.road_network(img(np.zeros((N, N)), wall=wall), pts((-400, 0), (400, 0)), world_size=WS, step=1,
                        block_layer="wall")
p2 = polylines(g2)[0]
cross = p2[np.abs(p2[:, 0]) < 40]
check("  negative control: a wall with a gap -- the road goes round through the gap (z > 225 where it crosses: the gap is z > 250, less the road smoothing)",
      len(cross) > 0 and cross[:, 2].min() > 225 and length(p2) > 900, (round(length(p2)), round(float(cross[:, 2].min()))))

print("── 2. Grade")
slope = 0.4                               # 40 % up toward +x
hs = img((X + WS / 2) * slope)
start, top = (-300, 0), (300, 0)
g3, _ = RD.road_network(hs, pts(start, top), world_size=WS, step=1, max_grade=0.10, smooth=2)
p3 = polylines(g3)[0]
ground = np.interp(p3[:, 0], [-WS, WS], [(-WS + WS / 2) * slope, (WS + WS / 2) * slope])
seg = np.linalg.norm(np.diff(p3[:, [0, 2]], axis=0), axis=1)
gr = np.abs(np.diff(ground)) / np.maximum(seg, 1e-9)
rise = 600 * slope
check(f"40 % slope, Max Grade 10 %: switchbacks -- {length(p3):.0f} m for a {rise:.0f} m rise (at least 80 % of rise / "
      f"0.10 = {rise / 0.1:.0f}: the planned path is that long, the relaxing rounds the hairpins)",
      length(p3) > 0.8 * rise / 0.10, round(length(p3)))
check("  the 90th-percentile grade along it stays near Max Grade (under 0.16)", np.percentile(gr, 90) < 0.16,
      round(float(np.percentile(gr, 90)), 3))
g4, _ = RD.road_network(hs, pts(start, top), world_size=WS, step=1, max_grade=10.0)
check("  negative control: Max Grade 10 -- straight up (within 5 % of 600 m)", abs(length(polylines(g4)[0]) - 600) < 30,
      round(length(polylines(g4)[0])))

print("── 3. Network")
g5, rep5 = RD.road_network(flat, pts((-400, 0), (400, 0), (0, 0)), world_size=WS, step=1)
tot = sum(length(p) for p in polylines(g5))
check(f"three places in a row: {g5.nprims} roads, {tot:.0f} m in all (the outer distance, 800 m, within 4 %)",
      g5.nprims == 2 and abs(tot - 800) < 32, rep5)
served = np.asarray(g5.get(PRIM, "served"))[:, 0] if np.asarray(g5.get(PRIM, "served")).ndim > 1 \
    else np.asarray(g5.get(PRIM, "served"))
check("  prims know the destination they join (1 and 2; 0 started the network)", sorted(served.tolist()) == [1, 2])
island = (np.abs(X - 350) < 60) & (np.abs(Z) < 60)
ring = (np.abs(X - 350) < 120) & (np.abs(Z) < 120) & ~island
g6, rep6 = RD.road_network(img(np.zeros((N, N)), sea=ring), pts((-400, 0), (350, 0), (0, 300)), world_size=WS,
                           step=1, block_layer="sea")
check("a place walled in by the Block Layer: reported unreachable, the others joined",
      rep6["unreachable"] == 1 and rep6["joined"] == 2 and g6.nprims == 1, rep6)

print("── 4. Height and coordinates")
hp = img((X + WS / 2) * 0.05 + 10)
g7, _ = RD.road_network(hp, pts((-400, -200), (400, 250)), world_size=WS, step=1, profile=40.0)
P7 = np.asarray(g7.get(POINT, "P"), np.float64)
expect = (P7[:, 0] + WS / 2) * 0.05 + 10
rh = np.asarray(g7.get(POINT, "road_h"), np.float64).reshape(-1)
inner = slice(8, -8)                      # the moving average is clipped at the ends
check("on a 5 % plane road_h is the plane under the road (within 0.3 m away from the ends)",
      np.abs(rh[inner] - expect[inner]).max() < 0.3, round(float(np.abs(rh[inner] - expect[inner]).max()), 3))
ras = geoimg.rasterize_curves(img(np.zeros((N, N))), g7, width=2.0, plane="xz", mapping="world", world_size=WS,
                              out_layer="road")
m = np.asarray(ras.need("road"))[:, :, 0]


def pix(x, z):
    return int(round(WS / 2 - z) / (WS / N) - 0.5 + 0.5), int((x + WS / 2) / (WS / N) - 0.5 + 0.5)


i0, j0 = int((WS / 2 - (-200)) / (WS / N)), int((-400 + WS / 2) / (WS / N))
i1, j1 = int((WS / 2 - 250) / (WS / N)), int((400 + WS / 2) / (WS / N))
check("Rasterize Curves (xz, world) draws the road onto the same image: mask ~1 at both destinations",
      m[i0 - 1:i0 + 2, j0 - 1:j0 + 2].max() > 0.9 and m[i1 - 1:i1 + 2, j1 - 1:j1 + 2].max() > 0.9,
      (round(float(m[i0 - 1:i0 + 2, j0 - 1:j0 + 2].max()), 2), round(float(m[i1 - 1:i1 + 2, j1 - 1:j1 + 2].max()), 2)))
check("  negative control: far from the road (the opposite corners) the mask is 0",
      m[i0, j1] == 0 and m[i1, j0] == 0)

T7 = np.asarray(g7.get(POINT, "road_t"), np.float64)
D7 = np.gradient(P7[:, [0, 2]], axis=0)
D7 /= np.linalg.norm(D7, axis=1, keepdims=True)
check("road_t: unit length, horizontal, along the road (cosine to the point-to-point direction > 0.99)",
      np.allclose(np.linalg.norm(T7, axis=1), 1, atol=1e-5) and np.allclose(T7[:, 1], 0)
      and ((T7[:, [0, 2]] * D7).sum(1) > 0.99).all())

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
