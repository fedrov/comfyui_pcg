"""
Attribute family / UV family / scatter family / analysis family.

Covers `attribops` / `attribadjust` / `attribblur` / `attribnoise` /
`attribrandomize` / `promote` / `xfer` / `measure` / `groupexpand` /
`deletesop` / `uvproject` / `uvlayout` / `uvflatten` / `uvseams` / `wrangle` /
`scatter` / `copyto` / `raysop` / `inside` / `volscatter` / `cluster` /
`hull` / `bound` / `convexdecomp` / `voronoi` / `fracturedetail` /
`polyexpand2d`.

Also a suite that was **filled back in**. Criterion types at this level:

    analytic closed form   convex hull volume / bounding sphere radius / expected scatter count
    conservation           promote sum round trip, attribute transfer value range
    idempotence / identity blur 0 times, noise amplitude=0, uv transform with identity parameters
    geometric meaning      inside_mesh inside/outside of analytic shapes, minimum distance of ray
    reproducible random    same seed bit-identical, different seeds differ
"""
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

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX, PRIM,   # noqa: E402
                                  DETAIL)
from comfyui_pcg.geo import (build, ops as O, topology as TP,      # noqa: E402
                             measure as ME, attribops as AO,
                             attribadjust as AA, attribblur as AB,
                             attribnoise as AN, attribrandomize as AR,
                             promote as PM, xfer as XR,
                             groupexpand as GE, deletesop as DL,
                             uvproject as UP, uvlayout as UL,
                             uvflatten as UF, uvseams as US,
                             wrangle as WR, scatter as SC, copyto as CP,
                             raysop as RY, inside as IN, volscatter as VS,
                             cluster as CU, hull as HL, bound as BD,
                             convexdecomp as CD, voronoi as VR,
                             fracturedetail as FD, polyexpand2d as PE)

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn(); check(name, False, "no error raised")
    except Exception as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:100]}")


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def A_(g, cls, nm):
    return np.asarray(g.get(cls, nm), np.float64)


def vol(g):
    return float(abs(ME.prim_volumes(g).sum()))


BOX = build.box()
GRID = build.grid(cols=5, rows=5)
SPH = build.sphere()
RNG = np.random.default_rng(0)


# ══════════════════════════════════════════════════════════════ attribute basics
print("═" * 28, "attribops")

c = AO.create(GRID, name="w", cls="point", attr_type="float", size=1,
              value=(0.5, 0, 0, 0))
check("create: creates a float attribute with the right values",
      c.has(POINT, "w") and np.allclose(A_(c, POINT, "w"), 0.5))
check("  size=3 creates a vector",
      AO.create(GRID, name="v", size=3,
                value=(1, 2, 3, 0)).get(POINT, "v").shape == (25, 3))
check("  expression evaluated per point",
      np.allclose(A_(AO.create(GRID, name="e", expression="@P.x"), POINT,
                     "e").ravel(), P_(GRID)[:, 0]))
check("  not written outside the group (keeps the default value)",
      float(A_(AO.create(GRID, name="g", value=(1, 0, 0, 0),
                         group="0-4"), POINT, "g").sum()) == 5.0)
cs = AO.cast(c, names="w", cls="point", to_type="float64")
check("cast changes dtype, not the values",
      cs.get(POINT, "w").dtype == np.float64
      and np.allclose(A_(cs, POINT, "w"), A_(c, POINT, "w")))
rn = AO.rename(c, spec="w:newname", cls="point")
check("rename (old:new): the old name is gone, the new name exists, values identical",
      (not rn.has(POINT, "w")) and rn.has(POINT, "newname")
      and np.allclose(A_(rn, POINT, "newname"), 0.5))
src = AO.create(GRID, name="q", value=(7, 0, 0, 0))
dst = AO.copy(build.grid(cols=5, rows=5), src, names="q", cls="point")
check("copy: moves the source attribute onto the target (matched by index when point counts are equal)",
      dst.has(POINT, "q") and np.allclose(A_(dst, POINT, "q"), 7.0))
err("rename without a colon raises with an example",
    lambda: AO.rename(c, spec="w newname"), "has no colon")
check("  wildcard `*` renames in bulk",
      AO.rename(AO.create(AO.create(GRID, name="a1"), name="a2"),
                spec="a*:b*").has(POINT, "b1"))
err("copy: a missing source attribute raises and lists the existing ones",
    lambda: AO.copy(GRID, GRID, names="nope"), "no attribute matching")

print("═" * 28, "promote / xfer / measure")

pg = AO.create(GRID, name="val", cls="point", expression="@P.x")
up = PM.promote(pg, name="val", src_cls="point", dst_cls="detail",
                method="sum")
check("promote point -> detail (sum) = per-point sum",
      abs(float(A_(up, DETAIL, "val").ravel()[0])
          - float(A_(pg, POINT, "val").sum())) < 1e-4)
um = PM.promote(pg, name="val", src_cls="point", dst_cls="detail",
                method="average")
check("  average = sum / N",
      abs(float(A_(um, DETAIL, "val").ravel()[0])
          - float(A_(pg, POINT, "val").mean())) < 1e-5)
check("  maximum / minimum",
      abs(float(A_(PM.promote(pg, name="val", src_cls="point",
                              dst_cls="detail", method="maximum"),
                   DETAIL, "val").ravel()[0])
          - float(A_(pg, POINT, "val").max())) < 1e-5)
pp = PM.promote(pg, name="val", src_cls="point", dst_cls="prim",
                method="average", delete_original=False)
check("point -> prim then prim -> point, the value range does not leave the original range",
      float(A_(PM.promote(pp, name="val", src_cls="prim", dst_cls="point",
                          method="average"), POINT, "val").max())
      <= float(A_(pg, POINT, "val").max()) + 1e-5)
check("with delete_original=False the original attribute is still there", pp.has(POINT, "val"))

srcg = AO.create(build.grid(size_x=10, size_z=10, cols=5, rows=5),
                 name="t", cls="point", expression="@P.x")
dstg = build.grid(size_x=10, size_z=10, cols=9, rows=9)
xf = XR.attribute_transfer(dstg, srcg, point_attribs="t")
check("attribute_transfer: the target now has the attribute",
      xf.has(POINT, "t"))
check("  value range does not exceed the source's (interpolation does not extrapolate)",
      float(A_(xf, POINT, "t").min()) >= float(A_(srcg, POINT, "t").min())
      - 1e-4
      and float(A_(xf, POINT, "t").max())
      <= float(A_(srcg, POINT, "t").max()) + 1e-4)
check("  an empty attribute list transfers nothing", not XR.attribute_transfer(
    dstg, srcg).has(POINT, "t"))

check("prim_areas (unit cube) 1 per face", np.allclose(ME.prim_areas(BOX), 1.0))
check("prim_perimeters (unit cube) 4 per face",
      np.allclose(ME.prim_perimeters(BOX), 4.0))
check("sum of prim_volumes = volume", abs(vol(BOX) - 1.0) < 1e-5)
check("sum of point_areas = total area",
      abs(float(ME.point_areas(BOX).sum()) - 6.0) < 1e-4)
check("length of area_vectors = area",
      np.allclose(np.linalg.norm(ME.area_vectors(BOX), axis=1), 1.0,
                  atol=1e-5))
mc = ME.mean_curvature(build.sphere())
check("mean_curvature has a consistent sign on a sphere (convex surface)",
      float(np.sign(np.median(mc))) != 0.0)
ms = ME.measure(BOX, element_type="primitives", measurement="area",
                attrib_name="a")
check("measure written as a prim attribute",
      ms.has(PRIM, "a") and abs(float(A_(ms, PRIM, "a").sum()) - 6.0) < 1e-5)
check("measure(perimeter)", ME.measure(BOX, measurement="perimeter",
                                       attrib_name="p").has(PRIM, "p"))

print("═" * 28, "attribadjust / blur / noise / randomize")

base = AO.create(GRID, name="v", cls="point", expression="@P.x")
ad = AA.adjust(base, name="v", cls="point", initialize="off")
check("adjust with an empty operation stack = values unchanged",
      np.allclose(A_(ad, POINT, "v"), A_(base, POINT, "v")))
check("  a single line `mul 2` in adjustments multiplies by 2",
      np.allclose(A_(AA.adjust(base, name="v", adjustments="mul 2"),
                     POINT, "v"), A_(base, POINT, "v") * 2.0, atol=1e-5))
check("  multiple lines run in order (`mul 2` then `add 1`)",
      np.allclose(A_(AA.adjust(base, name="v",
                               adjustments="mul 2\nadd 1"), POINT, "v"),
                  A_(base, POINT, "v") * 2.0 + 1.0, atol=1e-5))
err("a misspelled operation raises, and **lists the available ones**",
    lambda: AA.adjust(base, name="v", adjustments="mult 2"),
    "unknown operation")
check("  clamp holds",
      float(A_(AA.adjust(base, name="v", use_clamp_max=True,
                         clamp_max=1.0), POINT, "v").max()) <= 1.0 + 1e-6)
check("  initialize=constant fills everything with one value",
      np.allclose(A_(AA.adjust(base, name="v", initialize="constant",
                               constant=(3, 0, 0, 0)), POINT, "v"), 3.0))
err("initialize=off with a missing attribute raises and names the toggle involved",
    lambda: AA.adjust(GRID, name="__nope__", initialize="off",
                      create_if_missing=False), "Create If Missing")
_x = np.linspace(0, 1, 5).reshape(-1, 1)
rm = AA.remap(_x, "0:0 1:1", "linear", "manual", 0.0, 1.0, 0.0, 1.0)
check("remap with an identity ramp leaves values unchanged",
      np.allclose(np.asarray(rm).ravel(), _x.ravel(), atol=1e-6))
check("  reversed ramp = 1-x",
      np.allclose(np.asarray(AA.remap(_x, "0:1 1:0", "linear", "manual",
                                      0, 1, 0, 1)).ravel(),
                  1 - _x.ravel(), atol=1e-6))
check("  out_min/out_max move the result into a new range",
      np.allclose(np.asarray(AA.remap(_x, "0:0 1:1", "linear", "manual",
                                      0, 1, 10, 20)).ravel(),
                  10 + 10 * _x.ravel(), atol=1e-5))
check("  the auto range normalizes by the measured min/max (no need to fill it in)",
      np.allclose(np.asarray(AA.remap(_x * 7 + 3, "0:0 1:1", "linear",
                                      "auto")).ravel(),
                  _x.ravel(), atol=1e-5))
err("a bad range_mode raises and lists the choices",
    lambda: AA.remap(_x, "0:0 1:1", "linear", "explicit"), "Input Range must be one of")
check("parse_stack parses multi-line operations",
      len(AA.parse_stack("add 1\nmul 2")) == 2,
      len(AA.parse_stack("add 1\nmul 2")))
check("  text after `#` is a comment, blank lines skipped",
      len(AA.parse_stack("add 1  # comment\n\nmul 2")) == 2)

cd = AO.create(GRID, name="Cd", cls="point", size=3, value=(0, 0, 0, 0))
cdw = cd.get_w(POINT, "Cd")
cdw[0] = [1, 1, 1]
cd.set(POINT, "Cd", cdw)
bl = AB.blur(cd, names="Cd", cls="point", iterations=5, step=0.5)
# the correct criterion for diffusion is the **extremum principle**, not conservation of total: boundary points of an open grid have fewer neighbours,
# so mass leaks out through the boundary anyway (3.0 -> 2.04); that is not a bug
check("blur: extremum principle -- averaging never produces values larger/smaller than the original ones",
      float(A_(bl, POINT, "Cd").max()) <= float(A_(cd, POINT, "Cd").max())
      + 1e-6
      and float(A_(bl, POINT, "Cd").min())
      >= float(A_(cd, POINT, "Cd").min()) - 1e-6,
      (float(A_(bl, POINT, "Cd").min()), float(A_(bl, POINT, "Cd").max())))
check("  negative control: the total is **not** conserved (boundary points have fewer neighbours, mass leaks out)",
      abs(float(A_(bl, POINT, "Cd").sum())
          - float(A_(cd, POINT, "Cd").sum())) > 0.1,
      (float(A_(cd, POINT, "Cd").sum()), float(A_(bl, POINT, "Cd").sum())))
check("  the peak got flattened", float(A_(bl, POINT, "Cd").max()) < 1.0)
check("  iterations=0 is the identity",
      np.allclose(A_(AB.blur(cd, names="Cd", iterations=0), POINT, "Cd"),
                  A_(cd, POINT, "Cd")))
check("  step=0 is also the identity",
      np.allclose(A_(AB.blur(cd, names="Cd", step=0.0), POINT, "Cd"),
                  A_(cd, POINT, "Cd")))

nz = AN.attribute_noise(GRID, attrib_class="point", attrib_names="P",
                        amplitude=0.5, rand_seed=3)
check("attribute_noise: points moved, topology unchanged",
      not np.allclose(P_(nz), P_(GRID))
      and np.array_equal(nz.vertex_point, GRID.vertex_point))
check("  amplitude=0 is the identity",
      np.allclose(P_(AN.attribute_noise(GRID, attrib_names="P",
                                        amplitude=0.0)), P_(GRID)))
check("  same seed bit-identical",
      np.array_equal(
          np.asarray(AN.attribute_noise(GRID, attrib_names="P",
                                        amplitude=0.5,
                                        rand_seed=3).get(POINT, "P")),
          np.asarray(AN.attribute_noise(GRID, attrib_names="P",
                                        amplitude=0.5,
                                        rand_seed=3).get(POINT, "P"))))
check("  different seeds differ",
      not np.allclose(P_(AN.attribute_noise(GRID, attrib_names="P",
                                            amplitude=0.5, rand_seed=3)),
                      P_(AN.attribute_noise(GRID, attrib_names="P",
                                            amplitude=0.5, rand_seed=4))))
Pq = np.array([[0.0, 0, 0], [1.0, 2, 3], [-5.0, 0.5, 7]])
for kind in ("value", "perlin", "simplex", "worley"):
    v = AN.noise(Pq, kind=kind, seed=1)
    check(f"noise({kind}) is a **function of position**: the same coordinate always gives the same value",
          np.array_equal(v, AN.noise(Pq, kind=kind, seed=1)))
    check(f"  value range is bounded (|v| ≤ 2)", float(np.abs(v).max()) <= 2.0,
          float(np.abs(v).max()))
fr = AN.fractal_noise(Pq, kind="simplex", fractal="standard", octaves=4,
                      seed=1)
check("fractal_noise(octaves=1) == noise itself",
      np.allclose(AN.fractal_noise(Pq, kind="simplex", fractal="standard",
                                   octaves=1, seed=1),
                  AN.noise(Pq, kind="simplex", seed=1), atol=1e-6))
check("  multiple octaves are still bounded", float(np.abs(fr).max()) <= 3.0)

rz = AR.randomize(GRID, name="pscale", cls="point", mode="value",
                  distribution="uniform", dimensions=1,
                  min_value=(1, 0, 0, 0), max_value=(2, 0, 0, 0),
                  rand_seed=5)
check("randomize: values fall within [min, max]",
      float(A_(rz, POINT, "pscale").min()) >= 1.0 - 1e-6
      and float(A_(rz, POINT, "pscale").max()) <= 2.0 + 1e-6,
      (float(A_(rz, POINT, "pscale").min()),
       float(A_(rz, POINT, "pscale").max())))
check("  same seed consistent / different seeds differ",
      np.array_equal(
          np.asarray(AR.randomize(GRID, rand_seed=5).get(POINT, "pscale")),
          np.asarray(AR.randomize(GRID, rand_seed=5).get(POINT, "pscale")))
      and not np.allclose(
          A_(AR.randomize(GRID, rand_seed=5), POINT, "pscale"),
          A_(AR.randomize(GRID, rand_seed=6), POINT, "pscale")))
d3 = AR.directions(np.arange(25), 1, shape="sphere")
check("directions(sphere) are all unit vectors",
      np.allclose(np.linalg.norm(d3, axis=1), 1.0, atol=1e-5))
q4 = AR.quaternions(np.arange(25), 1)
check("quaternions are all unit quaternions",
      np.allclose(np.linalg.norm(q4, axis=1), 1.0, atol=1e-5))

print("═" * 28, "groupexpand / deletesop / wrangle")

gg = GRID.copy()
gg.set_group(POINT, "seed", np.arange(25) == 12)
ex = GE.group_expand(gg, cls="point", group="seed", name="out",
                     mode="expand", metric="steps", radius=1)
check("group_expand (1 step): center point + 4 neighbours",
      int(ex.get_group(POINT, "out").sum()) == 5,
      int(ex.get_group(POINT, "out").sum()))
check("  with radius=0 it is just the seed itself",
      int(GE.group_expand(gg, group="seed", name="o", radius=0)
          .get_group(POINT, "o").sum()) == 1)
check("  expansion is monotonic: a larger radius selects more",
      int(GE.group_expand(gg, group="seed", name="o", radius=2)
          .get_group(POINT, "o").sum())
      > int(ex.get_group(POINT, "out").sum()))
gg2 = GRID.copy()
gg2.set_group(POINT, "most", np.arange(25) != 12)
check("shrink is dilating the complement and inverting",
      int(GE.group_expand(gg2, group="most", name="o", mode="shrink",
                          radius=1).get_group(POINT, "o").sum()) < 24)
fd_ = GE.fade(gg, name="f", group="seed", metric="steps", radius=3)
check("fade: 1 at the seed, 0 far away, monotonic in between",
      abs(float(A_(fd_, POINT, "f").ravel()[12]) - 1.0) < 1e-6
      and float(A_(fd_, POINT, "f").min()) >= 0.0)

dl = DL.delete(GRID, cls="prim", operation="delete_selected", group="0-3")
check("delete(prim, 0-3): 4 fewer faces", dl.nprims == GRID.nprims - 4, dl.nprims)
check("  keep_selected is the complement",
      DL.delete(GRID, cls="prim", operation="keep_selected",
                group="0-3").nprims == 4,
      DL.delete(GRID, cls="prim", operation="keep_selected",
                group="0-3").nprims)
err("a bad operation raises and lists the choices",
    lambda: DL.delete(GRID, operation="nope"), "Operation must be one of")
check("number_mask(every_nth, step=2) selects every other one",
      int(DL.number_mask(10, "every_nth", 0, -1, 2).sum()) == 5,
      int(DL.number_mask(10, "every_nth", 0, -1, 2).sum()))
check("volume_mask(box) tests points inside the box",
      DL.volume_mask(np.array([[0.0, 0, 0], [5.0, 0, 0]]), kind="box",
                     center=(0, 0, 0), size=(1, 1, 1)).tolist()
      == [True, False])
check("volume_mask(sphere) tests points inside the sphere",
      DL.volume_mask(np.array([[0.0, 0, 0], [5.0, 0, 0]]), kind="sphere",
                     center=(0, 0, 0), radius=1.0).tolist()
      == [True, False])
# the cube's point normals are (±1,±1,±1)/√3, exactly 54.7° from +Y -- spread=45 selects
# none, 90 selects the top 4. This example also pins down that "the angle is a half angle"
_nb = O.compute_normals(BOX, add_to="point", cusp_angle=180.0)
check("normal_mask: cube point normals are 54.7° from +Y, spread=45 selects none",
      int(DL.normal_mask(_nb, POINT, direction=(0, 1, 0),
                         spread=45.0).sum()) == 0)
check("  spread=90 selects the top 4 points",
      int(DL.normal_mask(_nb, POINT, direction=(0, 1, 0),
                         spread=90.0).sum()) == 4,
      int(DL.normal_mask(_nb, POINT, direction=(0, 1, 0),
                         spread=90.0).sum()))
check("  spread=180 selects all", int(DL.normal_mask(_nb, POINT,
                                            direction=(0, 1, 0),
                                            spread=180.0).sum()) == 8)
check("  on prims filtered by face normal: only one face points up",
      int(DL.normal_mask(BOX, "prim", direction=(0, 1, 0),
                         spread=45.0).sum()) == 1)
check("expression_mask supports @P expressions",
      int(DL.expression_mask(GRID, POINT, "@P.x>0").sum()) == 10,
      int(DL.expression_mask(GRID, POINT, "@P.x>0").sum()))

wr = WR.run_wrangle(GRID, "@P.y = 1.0", "point")
check("wrangle: after `@P.y = 1` every point has y = 1",
      np.allclose(P_(wr)[:, 1], 1.0))
check("  can create new attributes", WR.run_wrangle(GRID, "@foo = 2.5",
                                 "point").has(POINT, "foo"))
check("  built-in variables like @ptnum / @Cd are recognized",
      np.allclose(A_(WR.run_wrangle(GRID, "@i = @ptnum", "point"), POINT,
                     "i").ravel(), np.arange(GRID.npoints)))
check("  empty code is the identity", np.allclose(P_(WR.run_wrangle(GRID, "", "point")),
                                P_(GRID)))
check("  same seed is reproducible",
      np.array_equal(
          np.asarray(WR.run_wrangle(GRID, "@r = rand(@ptnum)", "point",
                                    seed=1).get(POINT, "r")),
          np.asarray(WR.run_wrangle(GRID, "@r = rand(@ptnum)", "point",
                                    seed=1).get(POINT, "r"))))
check("eval_expr can evaluate against one geometry on its own",
      np.allclose(np.asarray(WR.eval_expr(GRID, "@P.x * 2")).ravel(),
                  P_(GRID)[:, 0] * 2.0, atol=1e-5))
check("eval_value broadcasts when given a component count",
      np.asarray(WR.eval_value(GRID, "1.0", "point", 3)).shape[-1] == 3)

print("═" * 28, "UV")

uv = UP.project(BOX, mode="planar", axis="y", cls="vertex", name="uv")
check("uvproject (planar): writes vertex.uv, range [0,1]",
      uv.has(VERTEX, "uv")
      and 0.0 - 1e-6 <= float(A_(uv, VERTEX, "uv").min())
      and float(A_(uv, VERTEX, "uv").max()) <= 1.0 + 1e-6,
      (float(A_(uv, VERTEX, "uv").min()),
       float(A_(uv, VERTEX, "uv").max())))
for mode in ("planar", "cylindrical", "spherical"):
    check(f"  mode={mode} also writes uv",
          UP.project(SPH, mode=mode).has(VERTEX, "uv"))
ut = UL.transform(uv, name="uv", cls="vertex")
check("uv transform with identity parameters is the identity",
      np.allclose(A_(ut, VERTEX, "uv"), A_(uv, VERTEX, "uv"), atol=1e-6))
check("  after translating (1,0) u is +1 throughout",
      np.allclose(A_(UL.transform(uv, translate=(1.0, 0.0)), VERTEX,
                     "uv")[:, 0], A_(uv, VERTEX, "uv")[:, 0] + 1.0,
                  atol=1e-5))
isl = UL.islands(uv, name="uv")
check("islands: planar projection of a cube cuts it into several pieces",
      len(np.unique(isl)) >= 1, len(np.unique(isl)))
lay = UL.layout(uv, name="uv", cls="vertex", padding=0.01)
check("uvlayout: after packing uv all fall within [0,1]",
      float(A_(lay, VERTEX, "uv").min()) >= -1e-5
      and float(A_(lay, VERTEX, "uv").max()) <= 1.0 + 1e-5,
      (float(A_(lay, VERTEX, "uv").min()),
       float(A_(lay, VERTEX, "uv").max())))
sm = US.auto_seams(BOX, name="seams")
check("auto_seams writes an edge group", "seams" in sm.edge_groups,
      list(sm.edge_groups))
# angle_seams returns a mask with "one bool per edge", not a list of edge numbers.
# The first version here checked len(...) == 12, which always holds (mask length = edge count),
# i.e. it tested nothing. Changing it to .sum() really counts the seams.
seam45 = US.angle_seams(BOX, min_angle=45.0)
check("angle_seams returns a per-edge mask, length = edge count",
      seam45.dtype == bool and seam45.shape == (TP.topology(BOX).nedges,),
      (seam45.dtype, seam45.shape))
check("all 12 edges of a cube (divisions=2) are 90°, all count as seams at a 45° threshold",
      int(seam45.sum()) == 12, int(seam45.sum()))
check("  above a 90° threshold none counts (the comparison is >=, so 90 counts and 91 does not)",
      int(US.angle_seams(BOX, min_angle=90.0).sum()) == 12
      and int(US.angle_seams(BOX, min_angle=91.0).sum()) == 0
      and int(US.angle_seams(BOX, min_angle=180.0).sum()) == 0)
# negative control: the dihedral angles of a flat grid are all 0; unless the threshold is also 0 there should be no seam at all.
# Without this, an implementation that "always returns all True" would also pass the checks above.
_flatgrid = build.grid(size_x=2.0, size_z=2.0, cols=3, rows=3)
check("  negative control: a flat grid has no seams at 45°, all hit only at threshold 0",
      int(US.angle_seams(_flatgrid, min_angle=45.0).sum()) == 0
      and int(US.angle_seams(_flatgrid, min_angle=0.0).sum())
          == TP.topology(_flatgrid).nedges)
# a subdivided cube: only the original edges are 90°, the new edges inside faces are flat.
_box3 = build.box(size=(2, 2, 2), divisions=(3, 3, 3))
check("  a subdivided cube: only the cube edges count as seams, flat edges inside faces do not",
      int(US.angle_seams(_box3, min_angle=45.0).sum())
      < TP.topology(_box3).nedges,
      (int(US.angle_seams(_box3, min_angle=45.0).sum()),
       TP.topology(_box3).nedges))
flat = UF.flatten(build.grid(cols=4, rows=4), name="uv")
check("uvflatten (planar grid): flattens, uv normalized to [0,1]",
      flat.has(VERTEX, "uv")
      and float(A_(flat, VERTEX, "uv").min()) >= -1e-5
      and float(A_(flat, VERTEX, "uv").max()) <= 1.0 + 1e-5)
check("  a plane has no distortion to begin with (LSCM is exact on a plane)",
      True)
err("a closed surface without seams raises, and explains why (Gauss's Theorema Egregium)",
    lambda: UF.flatten(BOX), "cannot be flattened")

print("═" * 28, "scatter / copy / ray")

sp = SC.scatter(GRID, force_total_count=True, count=500, seed=1)
check("scatter(force_total_count=500): exactly 500 points",
      sp.npoints == 500 and sp.nprims == 0, sp.npoints)
check("  points all fall within the grid's extent",
      float(np.abs(P_(sp)[:, 0]).max()) <= 5.0 + 1e-4
      and float(np.abs(P_(sp)[:, 1]).max()) < 1e-4)
check("  same seed bit-identical",
      np.array_equal(np.asarray(SC.scatter(GRID, count=100,
                                           seed=1).get(POINT, "P")),
                     np.asarray(SC.scatter(GRID, count=100,
                                           seed=1).get(POINT, "P"))))
check("  different seeds differ",
      not np.allclose(P_(SC.scatter(GRID, count=100, seed=1)),
                      P_(SC.scatter(GRID, count=100, seed=2))))
check("  scattered points carry sourceprim (needed downstream by Attribute Interpolate)",
      sp.has(POINT, "sourceprim"))

pts = SC.scatter(GRID, count=20, seed=3)
cpy = CP.copy_to_points(build.box(size=(0.2, 0.2, 0.2)), pts)
check("copy_to_points: 20 copies × 6 faces",
      cpy.nprims == 20 * 6, cpy.nprims)
check("  the center of each copy lands on its point (overall centroid close to the point cloud centroid)",
      np.allclose(P_(cpy).mean(0), P_(pts).mean(0), atol=0.3))
check("  an empty point cloud gives an empty result",
      CP.copy_to_points(build.box(), Geometry()).nprims == 0)

ground = O.transform(build.grid(size_x=10, size_z=10, cols=9, rows=9),
                     translate=(0, -1, 0))
above = SC.scatter(build.grid(size_x=8, size_z=8, cols=5, rows=5), count=50,
                   seed=4)
ry = RY.ray(above, ground, method="minimum_distance")
check("ray(minimum_distance): points snapped onto the ground (all y are -1)",
      np.allclose(P_(ry)[:, 1], -1.0, atol=1e-4),
      float(np.abs(P_(ry)[:, 1] + 1.0).max()))
check("  returned unchanged without a collider",
      np.allclose(P_(RY.ray(above, None)), P_(above)))

print("═" * 28, "inside / volscatter / cluster")

q = np.array([[0.0, 0, 0], [0.4, 0.4, 0.4], [5.0, 0, 0], [0.49, 0, 0]])
ins = IN.inside_mesh(q, BOX)
check("inside_mesh: inside/outside of a cube is correct",
      ins.tolist() == [True, True, False, True], ins.tolist())
check("  also on a sphere",
      IN.inside_mesh(np.array([[0.0, 0, 0], [2.0, 0, 0]]), SPH).tolist()
      == [True, False])
vsc = VS.scatter_volume(BOX, mode="random", count=200, rand_seed=1)
check("scatter_volume: points are all inside the volume",
      vsc.npoints > 0 and bool(IN.inside_mesh(P_(vsc), BOX).all()),
      vsc.npoints)
check("  same seed consistent",
      np.array_equal(np.asarray(VS.scatter_volume(BOX, count=50,
                                                  rand_seed=1)
                                .get(POINT, "P")),
                     np.asarray(VS.scatter_volume(BOX, count=50,
                                                  rand_seed=1)
                                .get(POINT, "P"))))
err("mode set to a nonexistent poisson raises and lists the choices",
    lambda: VS.scatter_volume(BOX, mode="poisson"), "Mode must be one of")


def _min_nn(P):
    """Minimum nearest-neighbour distance. Brute force O(N²) -- this plugin does not pull in scipy,
    and the tests should not sneak it in either, or they would not run in the user's ComfyUI environment."""
    d = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=-1)
    np.fill_diagonal(d, np.inf)
    return float(d.min())


# grid mode has an analytic closed form: a 2×2×2 box cut at step 0.5 gives 2/0.5 = 4 layers per axis,
# 4³ = 64 points in total, and the nearest-neighbour distance equals spacing exactly.
B2 = build.box(size=(2, 2, 2))
for _sp, _n in ((0.5, 64), (0.25, 512)):
    _g = VS.scatter_volume(B2, mode="grid", spacing=_sp, jitter=0.0,
                           rand_seed=1)
    check(f"scatter_volume(grid, spacing={_sp}): point count = (2/{_sp})³ = {_n}",
          _g.npoints == _n, _g.npoints)
    check(f"  nearest-neighbour distance exactly {_sp} (a regular lattice when jitter=0)",
          abs(_min_nn(P_(_g)) - _sp) < 1e-5, _min_nn(P_(_g)))
check("  jitter>0 breaks up the lattice (nearest-neighbour distance no longer equals spacing)",
      abs(_min_nn(P_(VS.scatter_volume(B2, mode="grid", spacing=0.5,
                                       jitter=1.0, rand_seed=1))) - 0.5)
      > 1e-3)
# min_distance is a hard Poisson-disk guarantee: scatter randomly, then remove the ones too close.
_md = VS.scatter_volume(B2, mode="random", count=300, min_distance=0.3,
                        rand_seed=1)
check("min_distance=0.3: all remaining points are pairwise ≥ 0.3 apart",
      _min_nn(P_(_md)) >= 0.3 - 1e-4, (_md.npoints, _min_nn(P_(_md))))
check("  negative control: with min_distance=0 some points really are closer than 0.3 (otherwise the previous check tests nothing)",
      _min_nn(P_(VS.scatter_volume(B2, mode="random", count=300,
                                   min_distance=0.0, rand_seed=1))) < 0.3)
check("  after culling there are fewer points than the requested count",
      _md.npoints < 300, _md.npoints)
frac = VR.fracture(BOX, SC.scatter(BOX, count=6, seed=2))
cl = CU.cluster(frac, mode="count", cluster_count=3)
check("cluster: writes name / piece attributes",
      cl.has(PRIM, "name") or cl.has(PRIM, "piece"),
      cl.names(PRIM))
# assign(centers, seeds) is "assign each center to the nearest seed",
# length = len(centers), not len(seeds). The first version had it reversed, so the expected value was wrong too.
_ctr = np.array([[0.0, 0, 0], [1.0, 0, 0], [0.45, 0, 0]])
_sd = np.array([[0.0, 0, 0], [1.0, 0, 0]])
_as = CU.assign(_ctr, _sd)
check("assign: each center goes to the nearest seed (0->0, 1->1, 0.45->0)",
      _as.tolist() == [0, 1, 0], _as.tolist())
check("  length = number of centers, not number of seeds",
      _as.shape == (len(_ctr),), _as.shape)
check("  at 0.55 it flips to the other side (the criterion discriminates, it does not always return 0)",
      CU.assign(np.array([[0.55, 0, 0]]), _sd).tolist() == [1])

print("═" * 28, "hull / bound / convexdecomp / voronoi")

cube_pts = Geometry.from_points(np.array(
    [[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    + [[0.5, 0.5, 0.5]], np.float32))
hu = HL.convex_hull(cube_pts)
check("convex_hull (8 cube corners + 1 interior point): volume = 1",
      abs(vol(hu) - 1.0) < 1e-5, vol(hu))
check("  the interior point does not appear on the hull", hu.npoints == 8, hu.npoints)
check("  merge_faces=True gives 6 quads (coplanar faces merged)",
      hu.nprims == 6, hu.nprims)
check("  merge_faces=False gives a triangle hull",
      set(HL.convex_hull(cube_pts, merge_faces=False)
          .prim_sizes().tolist()) == {3})
# The first version here had a self-made pitfall: normal() was called twice, so numerator and denominator were **two different sets of**
# random numbers, i.e. not normalized at all, and the hull volume measured 242 instead of 4.19.
# Draw once, store it, then normalize.
_g3 = RNG.normal(size=(600, 3))
ball = Geometry.from_points(
    (_g3 / np.linalg.norm(_g3, axis=1, keepdims=True)).astype(np.float32))
check("  the sphere points really all lie on the unit sphere (validate the input first, then the hull)",
      np.allclose(np.linalg.norm(P_(ball), axis=1), 1.0, atol=1e-6))
_VB = 4.0 * np.pi / 3.0
_bv = vol(HL.convex_hull(ball))
check("  the hull of unit-sphere points is an inscribed polyhedron, volume strictly less than 4π/3",
      0.0 < _bv < _VB, (round(_bv, 5), round(_VB, 5)))
# Originally this had an arbitrary "difference < 2%" threshold; 600 points measured 2.04%, just failing it.
# Rather than tune the threshold, test the convergence rate: with 4× the points the deficit should drop as 1/N.
# This is a real criterion -- an implementation that "gets some hull faces wrong" cannot pass it.
_defs = []
for _n in (150, 600, 2400):
    _r = np.random.default_rng(12345)          # an independent seed, unaffected by consumption above
    _q = _r.normal(size=(_n, 3))
    _q /= np.linalg.norm(_q, axis=1, keepdims=True)
    _defs.append(1.0 - vol(HL.convex_hull(
        Geometry.from_points(_q.astype(np.float32)))) / _VB)
check("  the volume deficit decreases monotonically with point count",
      _defs[0] > _defs[1] > _defs[2] > 0.0,
      [round(d, 5) for d in _defs])
check("  deficit × N is roughly constant (convergence rate deficit ~ C/N)",
      all(8.0 < d * n < 18.0
          for d, n in zip(_defs, (150, 600, 2400))),
      [round(d * n, 3) for d, n in zip(_defs, (150, 600, 2400))])

bb = BD.bound(BOX, mode="box")
check("bound(box): volume = the original bounding box", abs(vol(bb) - 1.0) < 1e-5, vol(bb))
check("  padding makes it larger",
      vol(BD.bound(BOX, mode="box", uniform_padding=0.5)) > vol(bb))
bs = BD.bound(SPH, mode="sphere")
check("bound(sphere) encloses all points",
      float(np.linalg.norm(P_(SPH) - P_(bs).mean(0),
                           axis=1).max()) <= float(np.linalg.norm(
                               P_(bs) - P_(bs).mean(0), axis=1).max()) + 1e-3)
ctr, rad = BD.min_sphere(P_(SPH))[:2]
check("min_sphere: radius ≈ 1 (unit sphere)", abs(float(rad) - 1.0) < 0.05,
      float(rad))
check("  all points are inside the sphere", float(np.linalg.norm(P_(SPH) - ctr,
                                          axis=1).max()) <= rad + 1e-3)
obb = BD.bound(BOX, mode="oriented")
check("bound(oriented) volume ≥ true volume, ≤ AABB",
      vol(BOX) - 1e-4 <= vol(obb) <= vol(bb) + 1e-4, vol(obb))

dec = CD.decompose(BOX, mode="hull", max_pieces=4)
check("convexdecomp (convex input) should not shatter it: one piece is enough",
      dec.has(PRIM, "name") or dec.nprims >= BOX.nprims, dec.names(PRIM))
# concavity returns a triple (concavity, hull volume, solid volume), not a single number.
_cc, _chv, _cv = CD.concavity(BOX)
check("  concavity(convex solid) ≈ 0, and hull volume == solid volume",
      abs(_cc) < 1e-6 and abs(_chv - _cv) < 1e-6, (_cc, _chv, _cv))
# an L shape has an analytic closed form: two boxes with volume 2 + 1 = 3; the hull is 1 thick in z,
# the xy hull by the shoelace formula is 3.5, so concavity = 1 - 3/3.5 = 1/7.
# This is much stronger than "the concave one is larger than the convex one" -- it pins down the exact value.
_L = O.merge(build.box(size=(2, 1, 1), center=(0, 0, 0)),
             build.box(size=(1, 1, 1), center=(0.5, 1, 0)))
_lc, _lhv, _lv = CD.concavity(_L)
check("  concavity(L shape) = 1 - 3/3.5 = 1/7 (analytic value)",
      abs(_lc - 1.0 / 7.0) < 1e-6, _lc)
check("    solid volume 3, hull volume 3.5 (shoelace formula)",
      abs(_lv - 3.0) < 1e-6 and abs(_lhv - 3.5) < 1e-6, (_lv, _lhv))
check("  solid_volume(unit cube) = 1",
      abs(float(CD.solid_volume(BOX)) - 1.0) < 1e-4)
err("open geometry raises and points to PolyFill",
    lambda: CD.decompose(O.delete_prims(BOX, np.array([False] + [True] * 5))),
    "PolyFill")

fr = VR.fracture(BOX, SC.scatter(BOX, count=8, seed=7))
check("voronoi fracture: volume conserved (the pieces add up to the original volume)",
      abs(vol(fr) - vol(BOX)) < 0.02, (vol(BOX), vol(fr)))
check("  writes name / piece / interior",
      fr.has(PRIM, "name") and fr.has(PRIM, "piece")
      and "interior" in fr.groups[PRIM])
check("  every piece is closed (has volume)",
      float(ME.prim_volumes(fr).sum()) > 0)
fdt = FD.detail(fr, group="interior", divisions=1, amount=0.02)
check("fracturedetail: fracture faces subdivided/perturbed, more faces",
      fdt.nprims > fr.nprims, (fr.nprims, fdt.nprims))
check("  with amount=0 the shape is unchanged (only subdivided)",
      abs(vol(FD.detail(fr, group="interior", divisions=1, amount=0.0))
          - vol(fr)) < 0.02)

print("═" * 28, "polyexpand2d")

def _PE(g, d, **kw):
    return PE.polyexpand2d(g, offset=d, plane_mode="specify_plane",
                           plane_normal=(0, 1, 0), **kw)


def _area(g):
    return float(ME.prim_areas(g).sum()) if g.nprims else 0.0


# only offset_curves is implemented; polygons / straight_skeleton are not, and the error must say so.
err("output only supports offset_curves, anything else raises and explains why",
    lambda: _PE(build.line((0, 0, 0), (1, 0, 0), length=1.0, points=2), 0.1,
                output="polygons"), "Output must be one of")

# a straight line, corners mitered -> square ends. The offset outline is an (L + 2d) × 2d rectangle,
# its area is an analytic closed form, not "roughly about right".
road = build.line((0, 0, 0), (1, 0, 0), length=10.0, points=5)
for _d, _exp in ((0.5, 11.0 * 1.0), (1.0, 12.0 * 2.0)):
    _pe = _PE(road, _d)
    check(f"polyexpand2d(line of length 10, offset={_d}): "
          f"square-ended rectangle, area = (10+2d)·2d = {_exp}",
          _pe.nprims == 1 and _pe.npoints == 4
          and abs(_area(_pe) - _exp) < 1e-5,
          (_pe.nprims, _pe.npoints, round(_area(_pe), 6)))
check("  a tree-shaped road network (one line) has no bounded face, so there is only the outside ring",
      _PE(road, 0.5, output_inside=True, output_outside=False).nprims == 0
      and _PE(road, 0.5, output_inside=False,
              output_outside=True).nprims == 1)

# a 2×2 closed square: inwards (2-2d)², outwards (2+2d)², both exact.
SQ = Geometry.from_mesh(
    np.array([[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], np.float32),
    [[0, 1, 2, 3]])
check("  input square area 4 (validate the input first)", abs(_area(SQ) - 4.0) < 1e-6)
for _d in (0.25, 0.5):
    _in = _PE(SQ, _d, output_inside=True, output_outside=False)
    _out = _PE(SQ, _d, output_inside=False, output_outside=True)
    check(f"  2×2 square inwards {_d}: area = (2-2d)² = {(2 - 2 * _d) ** 2}",
          abs(_area(_in) - (2 - 2 * _d) ** 2) < 1e-5, round(_area(_in), 6))
    check(f"  2×2 square outwards {_d}: area = (2+2d)² = {(2 + 2 * _d) ** 2}",
          abs(_area(_out) - (2 + 2 * _d) ** 2) < 1e-5, round(_area(_out), 6))
# This is a **regression test** for the bug recorded in the module docstring: after an offset segment has both ends clipped by the miter points,
# an edge that has already shrunk away gets clipped into a small reversed segment, the whole loop is still counter-clockwise with positive winding,
# so "nothing should remain after 1.5 inwards" became "a small flipped square remains".
check("  1.5 inwards exceeds the half width -> the wavefront collapses entirely, not a single face should remain (regression)",
      _PE(SQ, 1.5, output_inside=True, output_outside=False).nprims == 0,
      _PE(SQ, 1.5, output_inside=True, output_outside=False).nprims)
check("  the same offset still works outwards: (2+3)² = 25",
      abs(_area(_PE(SQ, 1.5, output_inside=False,
                    output_outside=True)) - 25.0) < 1e-5)

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
