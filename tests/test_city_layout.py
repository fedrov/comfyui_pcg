"""
The modular city's block rules (make_workflows.city_rules_code, a Wrangle over the 4 m grid), run on the grid
directly, for the table (Layout 0) and generated blocks (Layout 1, several seeds):

  roads   every cell's road class: the main street (|z| < 8) 1, the side street (|x| < 8) 2; Layout 1 adds secondary
          streets (3: straight two-cell bands across a quarter, from the side street to the plot's edge) and lanes (4)
  lots    no building on a road cell; no two buildings share a wall (negative control: a grid with two touching
          buildings is caught); every building touches a road (a street or a lane) -- negative control: with the
          lanes counted out, some generated buildings have no street frontage, so the lanes are what serve them
  table   Layout 0 is exactly CITY_LOTS (the production test checks the pipeline on it)
  seeds   a seed gives the same block every time, and another seed another block
  towns   Layout 2 (a block in a town of the open world): the roads are the cells of a given road mask (ext_road;
          here a diagonal road and a bend), nothing is built where ext_off is set (outside the town); every
          building touches a road or a lane -- negative control: without the mask the same seed builds on the road
"""
import json
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
from comfyui_pcg.geo import build  # noqa: E402
from comfyui_pcg.geo.core import PRIM  # noqa: E402
import make_workflows as MW  # noqa: E402

N = comfyui_pcg.NODE_CLASS_MAPPINGS
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


NX, NZ = MW.CITY_GRID["cols"] - 1, MW.CITY_GRID["rows"] - 1
GX, GZ = MW.CITY_GRID["size_x"] / 2, MW.CITY_GRID["size_z"] / 2
ST = MW.CITY_STREET
CX = -GX + 2 + 4 * np.arange(NX)
CZ = -GZ + 2 + 4 * np.arange(NZ)
GRID = build.grid(**MW.CITY_GRID)


def rules(grid=None, seed_in=0, **ch):
    r = N["PCG_Wrangle"]().run(grid if grid is not None else GRID, "prim", MW.city_rules_code(), "", seed_in,
                               ch_params=json.dumps(ch))
    g = r["result"][0] if isinstance(r, dict) else r[0]
    # the grid's prims run along x, then z: (z, x) arrays -> transposed to [i (x), j (z)]
    get = lambda n: np.asarray(g.get(PRIM, n)).reshape(NZ, NX).T          # noqa: E731
    return get("bld").astype(int), get("road").astype(int), get("floors").astype(int)


def touching_pairs(B):
    """Cell edges between two different buildings."""
    n = 0
    for a, b in ((B[1:, :], B[:-1, :]), (B[:, 1:], B[:, :-1])):
        n += int(((a >= 0) & (b >= 0) & (a != b)).sum())
    return n


def frontage(B, R, classes):
    """{building: touches a cell of one of the road classes}."""
    out = {}
    for b in np.unique(B[B >= 0]):
        m = B == b
        nb = np.zeros_like(m)
        nb[1:, :] |= m[:-1, :]
        nb[:-1, :] |= m[1:, :]
        nb[:, 1:] |= m[:, :-1]
        nb[:, :-1] |= m[:, 1:]
        out[int(b)] = bool((nb & np.isin(R, classes)).any())
    return out


print("── Layout 0: the table")
B0, R0, F0 = rules()
X, Z = np.meshgrid(CX, CZ, indexing="ij")
want = np.full(B0.shape, -1)
wf = np.zeros(B0.shape, int)
for b, x0, x1, z0, z1, fl in MW.CITY_LOTS:
    m = (X >= x0) & (X <= x1) & (Z >= z0) & (Z <= z1)
    want[m] = b
    wf[m] = fl
check("the buildings and floors are exactly CITY_LOTS", (B0 == want).all() and (F0[B0 >= 0] == wf[B0 >= 0]).all())
rw = np.where(np.abs(Z) < ST, 1, np.where(np.abs(X) < ST, 2, 0))
check("road classes: the main street 1, the side street 2, nothing else", (R0 == rw).all(), np.bincount(R0.ravel()))

print("── Layout 1: generated blocks")
det = True
blocks = {}
for seed in (1, 2, 3, 5, 8, 13):
    B, R, F = rules(layout=1, seed=seed)
    B2, R2, _ = rules(layout=1, seed=seed)
    det &= (B == B2).all() and (R == R2).all()
    blocks[seed] = (B, R, F)
check("a seed gives the same block every time", det)
check("  and other seeds other blocks", len({blocks[s][0].tobytes() for s in blocks}) == len(blocks))
okr = okt = okf = oks = okm = True
nofront = 0
for seed, (B, R, F) in blocks.items():
    okm &= (R[np.abs(Z) < ST] == 1).all() and (R[(np.abs(X) < ST) & (np.abs(Z) >= ST)] == 2).all()
    okr &= not ((B >= 0) & (R > 0)).any()
    okt &= touching_pairs(B) == 0
    fr = frontage(B, R, [1, 2, 3, 4])
    okf &= all(fr.values())
    nofront += sum(not v for v in frontage(B, R, [1, 2, 3]).values())
    # secondary streets: each a band two cells wide along x, from the side street to the plot's edge, per quarter
    for sx in (-1, 1):
        for sz in (-1, 1):
            q = (np.sign(X) == sx) & (np.sign(Z) == sz) & (np.abs(X) > ST) & (np.abs(Z) > ST)
            rows = sorted({int(j) for i, j in zip(*np.nonzero(q & (R == 3)))})
            if rows:
                full = all(((R[:, j] == 3) | ~q[:, j]).all() for j in rows)
                oks &= len(rows) == 2 and rows[1] - rows[0] == 1 and full
check("the main and side streets are class 1 and 2 in every block", okm)
check("no building on a road cell", okr)
check("no two buildings share a wall (the lanes keep them apart)", okt)
tp = np.full((4, 4), -1)
tp[1, 1], tp[2, 1] = 0, 1
check("  negative control: two touching buildings are caught", touching_pairs(tp) == 1)
check("every building touches a road (a street or a lane)", okf)
check("  negative control: without the lanes, some buildings have no street at all (the lanes serve them)",
      nofront > 0, nofront)
check("secondary streets: two-cell bands right across their quarter (side street to the edge)", oks and any(
    (blocks[s][1] == 3).any() for s in blocks))
check("floors within Min / Max Floors (defaults 3..12)", all(
    ((F[B >= 0] >= 3) & (F[B >= 0] <= 12)).all() for B, R, F in blocks.values()))
Bm, _, Fm = rules(layout=1, seed=3, min_floors=6, max_floors=6)
check("  Min = Max Floors = 6: every building 6 floors", (Fm[Bm >= 0] == 6).all() and (Bm >= 0).any())

print("── Layout 2: a block in a town (roads from a map mask)")
Xc, Zc = np.meshgrid(CX, CZ, indexing="xy")              # in the grid's prim order (along x, then z)
road_m = (np.abs(Xc - 0.6 * Zc - 6) < 5) | (np.abs(Zc + 20) < 4) & (Xc > 0)
off_m = Xc ** 2 + Zc ** 2 > 50 ** 2
gt = GRID.copy()
gt.set(PRIM, "ext_road", road_m.reshape(-1, 1).astype(np.float32))
gt.set(PRIM, "ext_off", off_m.reshape(-1, 1).astype(np.float32))
B2, R2, F2 = rules(gt, 4, layout=2)
rm, om = road_m.T, off_m.T
check("roads exactly the masked cells (class 1), no building on them nor outside the town", (R2[rm] == 1).all()
      and (R2[~rm] != 1).all() and not (B2[rm | om] >= 0).any() and (B2 >= 0).sum() > 20, int((B2 >= 0).sum()))
check("  no secondary streets of its own; lanes only inside the town",
      not (R2 == 2).any() and not (R2 == 3).any() and not ((R2 == 4) & om).any())
fr2 = frontage(B2, R2, [1, 4])
check("  every building touches a road or a lane; no two share a wall", all(fr2.values()) and touching_pairs(B2) == 0)
B2b, _, _ = rules(gt, 5, layout=2)
check("  the for-each iteration (rand_seed) gives each town its own block", (B2b != B2).any())
gn = GRID.copy()
gn.set(PRIM, "ext_off", off_m.reshape(-1, 1).astype(np.float32))
Bn, _, _ = rules(gn, 4, layout=2)
check("  negative control: without the road mask the same seed builds on the road", (Bn[rm] >= 0).any())
ga = GRID.copy()
ga.set(PRIM, "ext_off", np.ones((GRID.nprims, 1), np.float32))
Ba, _, _ = rules(ga, 4, layout=2)
check("  a town block with nowhere to build keeps one small building at its middle (what follows needs one)",
      len(np.unique(Ba[Ba >= 0])) == 1 and (Ba >= 0).sum() == 1)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
