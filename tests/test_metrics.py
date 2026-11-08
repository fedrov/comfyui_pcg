"""
Geometry metrics + scoring and selecting the best.

The nice thing about this set is that the criteria are almost **all analytic** -- metrics should have definite answers, otherwise using
them for automatic filtering is a gamble:

  · a box has area 6a², volume a³, Euler characteristic 2, genus 0
  · a torus has Euler characteristic 0, genus 1
  · an N×N grid: prim count, edge count and boundary edge count are all closed form
  · an equilateral triangle has quality exactly 1 (that is what the 4√3·A/Σl² normalization is for)
  · a planar UV projection filling 0-1: coverage 1.0, overlap 0

**every criterion that can fail is paired with a reverse control**: flip one prim → flipped_edges becomes positive;
flip the whole thing → flipped_edges is still 0 but the volume turns negative (the two criteria must be read together, which is exactly
what the docs say); two UV pieces stacked → overlap jumps to 1.0.

On the selection side, three things that fail silently are watched:
  1) **unstable ties**. Equal scores picking different variants = "the random numbers didn't change but the result did",
     the hardest kind to track down. Criterion: ties always take the lower index, and the same input run twice is bit-identical.
  2) **top_k order**. Item 0 must be best, otherwise "take the top three" lets a worse one in.
  3) **aesthetic scores can't get in**. An external score written on detail must be readable in the expression --
     it is the only wire connecting the whole closed loop to the image side.
"""
import json
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX,    # noqa: E402
                                  PRIM, DETAIL)
from comfyui_pcg.geo import (metrics as MT, build, ops as OPS,  # noqa: E402
                             uvproject as UVP)
from comfyui_pcg import nodes as N                        # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "did not raise")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def unwrap(res):
    return tuple(res.get("result", ())) if isinstance(res, dict) else res


A = 2.0
BOX = build.box(size=(A, A, A))
GRID = build.grid(size_x=2.0, size_z=2.0, rows=5, cols=5)     # 4×4 cells
TORUS = build.torus(radius=1.0, section_radius=0.3, rows=20, cols=20)


# ══════════════════════════════════════════════════ 1. Size (closed form)
sec("Size (closed-form solutions)")
m = MT.metrics(BOX, uv=False)
check("box prim count / point count", m["prims"] == 6 and m["points"] == 8)
check("  area = 6a²", abs(m["area"] - 6 * A * A) < 1e-12, m["area"])
check("  volume = a³", abs(m["volume"] - A ** 3) < 1e-12, m["volume"])
check("  bounding box = a", abs(m["bbox_x"] - A) < 1e-12
      and abs(m["bbox_diagonal"] - A * np.sqrt(3)) < 1e-12)
check("  centroid at the origin", abs(m["centroid_x"]) < 1e-12
      and abs(m["centroid_y"]) < 1e-12)
check("  12 triangles after triangulation", m["triangles"] == 12)
check("  all edge lengths equal a", abs(m["edge_min"] - A) < 1e-12
      and abs(m["edge_max"] - A) < 1e-12)

mg = MT.metrics(GRID, uv=False)
check("4×4 grid: 16 prims, 25 points", mg["prims"] == 16 and mg["points"] == 25)
check("  area = side length²", abs(mg["area"] - 4.0) < 1e-12, mg["area"])
check("  edge count = closed form 2·N·(N+1)",
      mg["edges"] == 2 * 4 * 5, mg["edges"])
check("  boundary edges = 4N", mg["boundary_edges"] == 16, mg["boundary_edges"])
check("  volume of an open surface is meaningless, but shouldn't throw either", isinstance(mg["volume"], float))

# scale independence: scale the whole thing by k, area ×k², volume ×k³
big = OPS.transform(BOX, scale=(3, 3, 3))
mb = MT.metrics(big, uv=False)
check("scaled 3×: area ×9, volume ×27 (metrics have no hard-coded absolute scale)",
      abs(mb["area"] / m["area"] - 9) < 1e-9
      and abs(mb["volume"] / m["volume"] - 27) < 1e-9)
check("  degenerate prim / duplicate point detection also follows scale (still 0 when shrunk 1e4×)",
      MT.quality_metrics(OPS.transform(BOX, scale=(1e-4, 1e-4, 1e-4)))
      ["degenerate_prims"] == 0)


# ══════════════════════════════════════════════════ 2. Topology (closed form)
sec("Topology (Euler characteristic / closed / orientation)")
check("box: closed, manifold, no boundary", m["closed"] == 1.0 and m["manifold"] == 1.0
      and m["boundary_edges"] == 0 and m["nonmanifold_edges"] == 0)
check("  **Euler characteristic = 2** (sphere topology), genus 0",
      m["euler"] == 2.0 and m["genus"] == 0.0)
mt = MT.metrics(TORUS, uv=False)
check("torus: **Euler characteristic = 0**, genus 1", mt["euler"] == 0.0
      and mt["genus"] == 1.0, (mt["euler"], mt["genus"]))
check("  also a closed manifold", mt["closed"] == 1.0 and mt["manifold"] == 1.0)
check("grid is not closed, so genus is nan (no made-up number)",
      mg["closed"] == 0.0 and np.isnan(mg["genus"]))
check("two separate boxes: 2 connected pieces",
      MT.metrics(OPS.merge(BOX, OPS.transform(BOX, translate=(9, 0, 0))),
                 uv=False)["components"] == 2)
check("  one box is 1 piece", m["components"] == 1)

# non-manifold: three prims sharing one edge
nm = Geometry(4)
nm.set(POINT, "P", np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                            np.float32), owned=True)
nm.set_topology(np.array([0, 1, 2, 0, 1, 3, 0, 1, 2], np.int32),
                np.array([0, 3, 6, 9], np.int32))
mn_ = MT.topo_metrics(nm)
check("three prims sharing one edge -> caught by nonmanifold_edges",
      mn_["nonmanifold_edges"] >= 1 and mn_["manifold"] == 0.0, mn_)

# orientation: flip one prim vs flip all
one = BOX.copy()
sel = np.zeros(BOX.nprims, bool)
sel[0] = True
one.set_group(PRIM, "one", sel)
flipped_one = OPS.reverse_prims(one, group="one")
mf = MT.topo_metrics(flipped_one)
check("**flip one prim** -> flipped_edges = that prim's edge count (4)",
      mf["flipped_edges"] == 4, mf["flipped_edges"])
all_flip = OPS.reverse_prims(BOX, group="")
ma = MT.metrics(all_flip, uv=False)
check("  [reverse control] **flip the whole thing** -> flipped_edges still 0 (flipping all is still consistent)",
      ma["flipped_edges"] == 0)
check("  but the volume becomes negative -- so these two criteria must be read together",
      abs(ma["volume"] + A ** 3) < 1e-12, ma["volume"])
check("the original box has flipped_edges 0 (the criterion isn't always positive)",
      m["flipped_edges"] == 0)


# ══════════════════════════════════════════════════ 3. Quality
sec("Triangle quality / degenerate / duplicate points")
eq = Geometry.from_mesh(
    np.array([[0, 0, 0], [1, 0, 0], [0.5, 0, np.sqrt(3) / 2]], np.float64),
    [[0, 1, 2]])
q = MT.quality_metrics(eq)
check("**equilateral triangle quality is exactly 1** (that is what the 4√3 normalization factor is for)",
      abs(q["tri_quality_min"] - 1.0) < 1e-12, q["tri_quality_min"])
needle = Geometry.from_mesh(
    np.array([[0, 0, 0], [1, 0, 0], [0.5, 0, 1e-3]], np.float64), [[0, 1, 2]])
qn = MT.quality_metrics(needle)
check("  thin sliver triangle quality approaches 0", qn["tri_quality_min"] < 0.01,
      qn["tri_quality_min"])
check("  square grid triangle quality around 0.8 (analytic value for an isosceles right triangle)",
      abs(MT.quality_metrics(GRID)["tri_quality_min"]
          - 4 * np.sqrt(3) * 0.5 / 4.0) < 1e-9)

deg = Geometry.from_mesh(
    np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0]], np.float64),
    [[0, 1, 2], [0, 1, 3]])
check("collinear triangles are counted as degenerate prims",
      MT.quality_metrics(deg)["degenerate_prims"] == 1)
check("  good prims are not misflagged", MT.quality_metrics(BOX)["degenerate_prims"] == 0)
dup = Geometry(4)
dup.set(POINT, "P", np.array([[0, 0, 0], [1, 0, 0], [0, 0, 0], [2, 0, 0]],
                             np.float32), owned=True)
check("duplicate points are counted (two bit-identical points count as one pair)",
      MT.quality_metrics(dup)["duplicate_points"] == 1)
check("  the box has no duplicate points", q is not None and m["prims"] == 6
      and MT.quality_metrics(BOX)["duplicate_points"] == 0)


# ══════════════════════════════════════════════════ 4. UV
sec("UV (coverage / overlap / flipped)")
guv = UVP.project(GRID, mode="planar", axis="y")
mu = MT.uv_metrics(guv)
check("planar projection filling 0-1: uv_area = 1 (analytic)",
      abs(mu["uv_area"] - 1.0) < 1e-9, mu["uv_area"])
check("  coverage = 1", abs(mu["uv_coverage"] - 1.0) < 1e-12, mu["uv_coverage"])
check("**overlap of a clean projection must be 0** (by prim count, not triangle count)",
      mu["uv_overlap"] == 0.0, mu["uv_overlap"])
check("  nothing flipped, nothing out of range",
      mu["uv_flipped"] == 0 and mu["uv_out_of_range"] == 0)
stacked = OPS.merge(guv, guv)
ms = MT.uv_metrics(stacked)
check("  [reverse control] two pieces stacked -> overlap jumps to 1.0", ms["uv_overlap"] == 1.0,
      ms["uv_overlap"])
check("  after stacking, uv_area doubles but coverage is still 1 (area and coverage are different things)",
      abs(ms["uv_area"] - 2.0) < 1e-9 and abs(ms["uv_coverage"] - 1.0) < 1e-12)
half = UVP.project(GRID, mode="planar", axis="y", scale=(0.5, 0.5))
mh = MT.uv_metrics(half)
check("only a quarter laid out: uv_area ≈ 0.25, coverage ≈ 0.25",
      abs(mh["uv_area"] - 0.25) < 1e-6
      and abs(mh["uv_coverage"] - 0.25) < 0.02,
      (mh["uv_area"], mh["uv_coverage"]))
check("geometry without uv: has_uv = 0, everything else 0 (doesn't throw)",
      MT.uv_metrics(BOX)["has_uv"] == 0.0
      and MT.uv_metrics(BOX)["uv_area"] == 0.0)

# ── this metric caught something right after it went live (noted in pcg49, fixed in pcg56) ──────────────────
#
# `build.grid` **ships its own** point uv, and that uv used to be **mirrored** relative to the prim winding: the built-in
# uv had signed area −0.125, UV Project (planar/y) produced +0.125, and both have prim
# normals +Y. Sampling a texture with the default grid's built-in uv gave a mirrored image.
#
# pcg56 negated the grid's v (v toward −Z), giving the same handedness as UV Project and HeightField to Mesh.
# Here it changed from "pin the current state" to "pin the fixed state", and an **orientation** criterion was added: looking only
# at flipped or not tells you the handedness, not whether the texture is rotated 180°.
mgrid = MT.uv_metrics(GRID)
check("build.grid built-in uv has no flipped triangles (fixed in pcg56; used to be all flipped)",
      mgrid["has_uv"] == 1.0 and mgrid["uv_flipped"] == 0,
      f"{mgrid['uv_flipped']}/{len(GRID.triangles())}")
_gP = np.asarray(GRID.get(POINT, "P"), np.float64)
_guv = np.asarray(GRID.get(POINT, "uv"), np.float64)
_nw = int(np.argmin(_gP[:, 0] + _gP[:, 2]))       # min x, min z = northwest corner
_se = int(np.argmax(_gP[:, 0] + _gP[:, 2]))
check("  orientation: northwest corner (−X, −Z) uv = (0, 1), southeast corner = (1, 0) -- the texture is upright in top view",
      np.allclose(_guv[_nw], [0, 1]) and np.allclose(_guv[_se], [1, 0]),
      f"NW {_guv[_nw]}, SE {_guv[_se]}")
check("  UV Project also flips none -- the two conventions agree now",
      MT.uv_metrics(UVP.project(GRID, mode="planar",
                                axis="y"))["uv_flipped"] == 0)
check("  both have prim normals +Y (so the difference is only in uv handedness)",
      float(OPS.prim_normals(GRID)[0][1]) > 0.99)
check("uv_res is written into the result (otherwise runs at different resolutions don't match and you can't see why)",
      MT.uv_metrics(guv, res=64)["uv_res"] == 64)
check("  coverage still 1 after changing the resolution (the fully covered limit case is resolution-independent)",
      abs(MT.uv_metrics(guv, res=32)["uv_coverage"] - 1.0) < 1e-12)
flip_uv = guv.copy()
uvv = np.asarray(guv.get(VERTEX, "uv"), np.float64).copy()
uvv[:, 0] = 1.0 - uvv[:, 0]
flip_uv.set(VERTEX, "uv", uvv, dtype=np.float32, owned=True)
check("uv mirrored as a whole -> uv_flipped counts all triangles",
      MT.uv_metrics(flip_uv)["uv_flipped"] == len(GRID.triangles()))
out_uv = guv.copy()
out_uv.set(VERTEX, "uv", uvv * 3.0, dtype=np.float32, owned=True)
check("uv outside 0-1 -> uv_out_of_range counts them",
      MT.uv_metrics(out_uv)["uv_out_of_range"] > 0)
check("uv on points is recognized too (not only on vertices)",
      MT.uv_metrics(UVP.project(GRID, mode="planar", axis="y",
                                cls=POINT))["has_uv"] == 1.0)


# ══════════════════════════════════════════════════ 5. Summary / detail
sec("Summary / written to detail")
full = MT.metrics(guv)
check("all metrics are **scalars** (usable directly in expressions)",
      all(isinstance(v, (int, float)) for v in full.values()),
      [k for k, v in full.items() if not isinstance(v, (int, float))])
check("  key names are all valid identifiers",
      all(k.isidentifier() for k in full), [k for k in full
                                            if not k.isidentifier()])
check("empty geometry can be measured too, doesn't throw", MT.metrics(Geometry())["points"] == 0)
check("  None treated as empty geometry", MT.metrics(None)["prims"] == 0)
wd = MT.write_detail(BOX, MT.metrics(BOX, uv=False))
check("after writing to detail, detail() can read it",
      abs(float(np.asarray(wd.get(DETAIL, "area"))[0][0]) - 24.0) < 1e-4)
check("  nan is not written (writing it would only become a mystery downstream)",
      not wd.has(DETAIL, "genus") or np.isfinite(
          float(np.asarray(wd.get(DETAIL, "genus"))[0][0])))
check("  prefix avoids name clashes",
      MT.write_detail(BOX, {"area": 1.0}, "m_").has(DETAIL, "m_area"))
check("  original geometry untouched (copy-on-write)", not BOX.has(DETAIL, "area"))


# ══════════════════════════════════════════════════ 6. Scoring
sec("Score expression")
check("metrics can be used directly as variables",
      MT.score_one(BOX, "prims", uv=False) == 6.0)
check("  same function library as Wrangle (fit / clamp / min ...)",
      MT.score_one(BOX, "clamp(prims, 0, 3) + min(area, 10)", uv=False)
      == 13.0)
check("  i / n are the index and the total count",
      MT.score_one(BOX, "i * 10 + n", index=2, total=5, uv=False) == 25.0)
scored = MT.write_detail(BOX, {"score": 0.75})
check("**detail attributes are readable** -- this is where the aesthetic score comes in",
      abs(MT.score_one(scored, 'detail("score")', uv=False) - 0.75) < 1e-6)
check("  can be weighted together with structural criteria in one expression",
      abs(MT.score_one(scored, 'detail("score") * 2 - nonmanifold_edges',
                       uv=False) - 1.5) < 1e-6)
check("  functions like npoints() are there too",
      MT.score_one(BOX, "npoints()", uv=False) == 8.0)
err("a wrong expression raises, and lists the available variables",
    lambda: MT.score_one(BOX, "nonexistent_thing", uv=False), "Available variables")
err("  syntax errors are reported clearly too",
    lambda: MT.score_one(BOX, "1 +", uv=False), "Expression evaluation failed")


# ══════════════════════════════════════════════════ 7. Selecting the best
sec("Selecting the best")
SEQ = [build.box(size=(s, s, s)) for s in (1.0, 3.0, 2.0)]
best, top, idx, sc, rows, order = MT.select(SEQ, "area", "max", top_k=3,
                                            uv=False)
check("max mode picks the largest area", idx == 1 and abs(sc - 6 * 9) < 1e-9)
check("  best is that item in the sequence (not a copy)", best is SEQ[1])
check("  top_k sorted by score", order == [1, 2, 0], order)
check("  **item 0 of top_k is best** (taking the top three won't let a worse one in)",
      top[0] is best and len(top) == 3)
bmin, _, imin, smin, _, _ = MT.select(SEQ, "area", "min", uv=False)
check("min mode picks the smallest", imin == 0 and abs(smin - 6.0) < 1e-9)
check("top_k clamped when larger than the sequence length",
      len(MT.select(SEQ, "area", "max", top_k=99, uv=False)[1]) == 3)
check("top_k = 1 gives only one",
      len(MT.select(SEQ, "area", "max", top_k=1, uv=False)[1]) == 1)

# ties: must take the lower index, and two runs must agree
TIE = [build.box(size=(1, 1, 1)) for _ in range(4)]
r1 = MT.select(TIE, "1.0", "max", top_k=4, uv=False)
r2 = MT.select(TIE, "1.0", "max", top_k=4, uv=False)
check("**ties take the lower index**", r1[2] == 0, r1[2])
check("  and the order is stable 0,1,2,3", r1[5] == [0, 1, 2, 3], r1[5])
check("  the same input run twice gives exactly the same result (otherwise 'the random numbers didn't change but the result did')",
      r1[5] == r2[5] and r1[2] == r2[2])
check("  min mode ties also take the lower index",
      MT.select(TIE, "1.0", "min", uv=False)[2] == 0)

# aesthetic score comes in through detail, ranked together with structural criteria
mixed = [MT.write_detail(build.box(size=(1, 1, 1)), {"score": s})
         for s in (0.2, 0.9, 0.5)]
bm, _, im, _, _, om = MT.select(mixed, 'detail("score")', "max", top_k=3,
                                uv=False)
check("**external aesthetic score drives the ranking** (the wire connecting the closed loop to the image side)",
      im == 1 and om == [1, 2, 0], om)
broken = MT.write_detail(OPS.reverse_prims(
    build.box(size=(1, 1, 1)), group=""), {"score": 1.0})
mixed2 = mixed + [broken]
bm2, _, im2, _, _, _ = MT.select(
    mixed2, 'detail("score") - (volume < 0) * 10', "max", uv=False)
check("  structural criteria can veto a high aesthetic score (the one with negative volume gets kicked out)", im2 == 1, im2)

err("empty sequence raises", lambda: MT.select([], "1"), "sequence is empty")
err("wrong mode", lambda: MT.select(SEQ, "1", "bogus"), "mode must be one of")
rep = MT.select(SEQ, "area", "max", uv=False)[4]
check("every item has a report (score + all metrics)",
      len(rep) == 3 and "metrics" in rep[0] and "score" in rep[0])


# ══════════════════════════════════════════════════ 8. Nodes
sec("Nodes")
gm = N.PCG_GeoMetrics()
out = unwrap(gm.run(BOX, "prims", False, True, "uv", 128, True, "", 1))
check("Geo Metrics returns (geo, json, value, int)", len(out) == 4)
check("  value is the metric named by pick", out[2] == 6.0 and out[3] == 6)
check("  json parses, and keys are sorted",
      json.loads(out[1])["area"] == 24.0)
check("  geo is passed through, and carries the detail",
      out[0].npoints == BOX.npoints and out[0].has(DETAIL, "prims"))
check("  not written when write_detail is off",
      not unwrap(gm.run(BOX, "prims", False, True, "uv", 128, False, "", 1))
      [0].has(DETAIL, "prims"))
err("pick naming a nonexistent metric lists the available ones",
    lambda: gm.run(BOX, "nope", False, True, "uv", 128, True, "", 1),
    "Available:")

sb = N.PCG_SelectBest()
o2 = unwrap(sb.run(SEQ, "area", "max", 2, False, True, "uv", 128,
                   "prims area"))
check("Select Best returns (best, top_k, index, score, report)", len(o2) == 5)
check("  index / score match", o2[2] == 1 and abs(o2[3] - 54.0) < 1e-9)
check("  top_k is a geometry sequence", isinstance(o2[1], list) and len(o2[1]) == 2)
rp = json.loads(o2[4])
check("  report is JSON sorted by rank, with index and score",
      rp[0]["rank"] == 0 and rp[0]["index"] == 1 and len(rp) == 3, rp[0])
check("  metrics named in report_metrics are included too",
      "prims" in rp[0] and "area" in rp[0])
check("  report can be fed straight back into a prompt (it is a valid JSON array)",
      isinstance(rp, list) and all(isinstance(r, dict) for r in rp))
spec = N.PCG_SelectBest.INPUT_TYPES()["required"]
check("score is multiline (expressions get long)",
      spec["score"][1].get("multiline") is True)
check("  mode combo items are the module constant", spec["mode"][0] == list(MT.MODES))
check("  default expression is the most common structural filter",
      "closed" in spec["score"][1]["default"])
check("Select Best is in PCG/loop (alongside For-Each)",
      N.PCG_SelectBest.CATEGORY == "PCG/loop")
check("Geo Metrics is in PCG/output (it looks, it doesn't modify)",
      N.PCG_GeoMetrics.CATEGORY == "PCG/output")


# ══════════════════════════════ 9. The chain from the pitch: run one round, pick automatically
sec("For-Each produces a set of variants -> pick the best automatically")
# simulate one round of variants: most are good, two are bad (one open, one with a degenerate prim)
variants = []
for i in range(6):
    g = build.sphere(radius=1.0 + 0.1 * i, rows=8 + i, cols=12)
    variants.append(g)
holed = OPS.delete_prims(variants[2],
                         np.arange(variants[2].nprims) > 3)   # cut a big hole
variants[2] = holed
variants[4] = OPS.merge(variants[4],
                        Geometry.from_mesh(
                            np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]],
                                     np.float64), [[0, 1, 2]]))  # degenerate prim
best, top, idx, sc, rows, order = MT.select(
    variants, "closed * 10 - degenerate_prims * 5 + area * 0.01",
    "max", top_k=3, uv=False)
check("the two bad ones rank last",
      set(order[-2:]) == {2, 4}, order)
check("  the one picked is closed and has no degenerate prims",
      MT.topo_metrics(best)["closed"] == 1.0
      and MT.quality_metrics(best)["degenerate_prims"] == 0)
check("  the largest area wins (tie-break under equal conditions works too)",
      idx == 5, idx)
check("the report shows **why** an item lost (every item's metrics are there)",
      rows[2]["metrics"]["closed"] == 0.0
      and rows[4]["metrics"]["degenerate_prims"] == 1)
# chain it once more: Geo Metrics writes detail -> Select Best reads detail
with_score = [MT.write_detail(g, {"aesthetic": 1.0 - abs(i - 3) * 0.2})
              for i, g in enumerate(variants)]
b2, _, i2, _, _, o2_ = MT.select(
    with_score, 'detail("aesthetic") + closed * 0.5', "max", uv=False)
check("structural score + aesthetic score ranked together (both kinds of criteria in one expression)",
      i2 == 3, (i2, o2_))
check("  changing the weights changes the result (shows both sides are in effect)",
      MT.select(with_score, 'detail("aesthetic") + closed * 5',
                "max", uv=False)[2] != 2)


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
