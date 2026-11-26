"""
City Block (nodes_sop3.PCG_CityBlock): the modular city's generator as one node, expanding the network stored in
data/city_block.json into the graph when it runs (run through fakecomfy's Executor, which does node expansion).

  stored  data/city_block.json is exactly what make_workflows.city_block_prompt() writes now (run make_workflows.py
          after changing the city), and holds no output node (an expansion runs every output node it carries)
  table   Layout Table: the buildings are exactly CITY_LOTS' (bld), each at its floors (top floor = floors - 1, the
          setback row lower); every placed piece is a kit piece, its asset the glb name
  params  Generated: a seed gives the same block, another seed another one; Min = Max Floors = 5 tops every building
          out at floor 4; Setback Floors 0 vs 3: the street-front rows of tall buildings lose their top floors only
          with setbacks (negative control)
  kit     a kit linked in replaces the built one: a 1 m box named as each piece -> every placed piece is that box (6
          faces each, its material); the link is reused, not copied (the expansion points at the kit's node)
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
import fakecomfy  # noqa: E402
import numpy as np  # noqa: E402

import comfyui_pcg  # noqa: E402
from comfyui_pcg.geo import build, ops  # noqa: E402,F401
from comfyui_pcg.geo.core import POINT, PRIM  # noqa: E402
import make_workflows as MW  # noqa: E402

MAP = dict(comfyui_pcg.NODE_CLASS_MAPPINGS)
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and extra == "" else "   " + str(extra)))


DEF = {"layout": "table", "rand_seed": 1, "density": 0.85, "min_floors": 3, "max_floors": 12, "setback_floors": 3,
       "setback_min": 9}


def block(extra_nodes=None, **kw):
    api = {"cb": {"class_type": "PCG_CityBlock", "inputs": dict(DEF, **kw)}}
    api.update(extra_nodes or {})
    ex = fakecomfy.Executor(api, MAP, release=True)
    return ex.run("cb"), ex


def pts(g, name):
    return np.asarray(g.get(POINT, name)).reshape(-1)


print("── the stored network")
path = os.path.join(os.path.dirname(_R), "data", "city_block.json")
with open(path, encoding="utf-8") as f:
    stored = json.load(f)
now = json.loads(json.dumps(MW.city_block_prompt()))
check("data/city_block.json is what make_workflows writes now", stored == now, len(stored["prompt"]))
outs = [v["class_type"] for v in stored["prompt"].values() if getattr(MAP[v["class_type"]], "OUTPUT_NODE", False)]
check("  no output node in it (exports, previews)", not outs, outs)

print("── Layout Table")
(b0, p0), _ = block()
bld = pts(p0, "bld").astype(int)
want = {b for b, *_ in MW.CITY_LOTS}
check("the buildings are exactly CITY_LOTS'", set(bld.tolist()) == want, sorted(set(bld.tolist())))
fl = pts(p0, "floor").astype(int)
nm = pts(p0, "name").astype(str)
walls = np.char.startswith(nm, "Wall_") | np.char.startswith(nm, "Corner_")
top = {b: int(fl[walls & (bld == b)].max()) for b in want}
check("  each building's top wall floor is its floors - 1", all(top[b] == f_ - 1 for b, *_, f_ in MW.CITY_LOTS),
      top)
check("  every piece a kit piece, asset = SM_Kit_<name>", set(nm.tolist()) <= set(MW.CITY_KIT)
      and (pts(p0, "asset").astype(str) == np.char.add("SM_Kit_", nm)).all())
mats = set(np.asarray(b0.get(PRIM, "material")).reshape(-1).astype(str).tolist())
check("  buildings: the kit placed, facade variants swapped in", b0.nprims > 10000 and
      {MW.CITY_FACADE_MAT[1], MW.CITY_FACADE_MAT[2]} <= mats, sorted(mats))

print("── Generated")
(_, pa), _ = block(layout="generated", rand_seed=5)
(_, pb), _ = block(layout="generated", rand_seed=5)
(_, pc), _ = block(layout="generated", rand_seed=6)
sig = lambda p: np.asarray(p.get(POINT, "P")).round(3).tobytes()        # noqa: E731
check("a seed gives the same block", sig(pa) == sig(pb), pa.npoints)
check("  another seed another one", sig(pa) != sig(pc))
(_, p5), _ = block(layout="generated", rand_seed=5, min_floors=5, max_floors=5, setback_floors=0)
nm5, fl5 = pts(p5, "name").astype(str), pts(p5, "floor").astype(int)
w5 = np.char.startswith(nm5, "Wall_") | np.char.startswith(nm5, "Corner_")
check("Min = Max Floors = 5: every wall at floors 0..4, the top floor 4 everywhere",
      fl5[w5].max() == 4 and all(fl5[w5 & (pts(p5, "bld") == b)].max() == 4 for b in np.unique(pts(p5, "bld"))))
(_, s3), _ = block(setback_floors=3)
(_, s0), _ = block(setback_floors=0)
tall = [b for b, *_, f_ in MW.CITY_LOTS if f_ >= 9]
n3 = sum(int(((pts(s3, "bld") == b)).sum()) for b in tall)
n0 = sum(int(((pts(s0, "bld") == b)).sum()) for b in tall)
check("Setback Floors 3: the tall buildings' street fronts stop lower (fewer pieces than with 0)", tall and n3 < n0,
      (n3, n0))
short = [b for b, *_, f_ in MW.CITY_LOTS if f_ < 9]
def wall_slots(p, b):
    n_ = pts(p, "name").astype(str)
    w_ = (np.char.startswith(n_, "Wall_") | np.char.startswith(n_, "Corner_")) & (pts(p, "bld") == b)
    return int(w_.sum())


same = all(wall_slots(s3, b) == wall_slots(s0, b) for b in short)
check("  negative control: the buildings under Setback Min keep their walls either way", same,
      [(b, wall_slots(s3, b), wall_slots(s0, b)) for b in short])

def node(ct, **inputs):
    """An API node with every widget at its default, then inputs."""
    it = MAP[ct].INPUT_TYPES()
    d = {}
    for sec in ("required", "optional"):
        for k, spec in it.get(sec, {}).items():
            if isinstance(spec[0], list):
                d[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                d[k] = spec[1]["default"]
    d.update(inputs)
    return {"class_type": ct, "inputs": d}


print("── a kit linked in")
code = ("names = np.array([" + ", ".join(f'"{n}"' for n in MW.CITY_KIT) + "])\n"
        "s@name = names[@ptnum]\n")
kit_nodes = {
    "pts": node("PCG_Add", points="\n".join(f"{3 * i} 0 0" for i in range(len(MW.CITY_KIT)))),
    "nm": node("PCG_Wrangle", geo=["pts", 0], code=code),
    "bx": node("PCG_Box", size_x=1.0, size_y=1.0, size_z=1.0),
    "mt": node("PCG_Wrangle", geo=["bx", 0], run_over="prim", code='s@material = "X"'),
    "cp": node("PCG_CopyToPoints", source=["mt", 0], points=["nm", 0], target_point_attributes="name",
               target_prim_attributes="name"),
}
api_in = dict(DEF)
api_in["kit"] = ["cp", 0]
api = {"cb": {"class_type": "PCG_CityBlock", "inputs": api_in}, **kit_nodes}
ex = fakecomfy.Executor(api, MAP, release=True)
bk, pk = ex.run("cb")
mk = set(np.asarray(bk.get(PRIM, "material")).reshape(-1).astype(str).tolist())
check("every placed piece is the linked box: 6 faces each, its material", bk.nprims == 6 * pk.npoints
      and mk == {"X"} and pk.npoints == p0.npoints, (bk.nprims, pk.npoints, sorted(mk)))
kit_calls = [c for c in ex.calls if c[0] == "PCG_Boolean"]
check("  the built kit does not run (its nodes are left out of the expansion)", not kit_calls, len(kit_calls))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
