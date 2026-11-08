"""
pcg113: Wrangle type prefixes, @group_ and vertex @P -- the behaviours the Wrangle syntax page documents.

  · a typed write converts to the declared type, as in VEX: i@ truncates to int32, f@ makes float32 from ints / bools,
    v@ / 2@ / 3@ / 4@ / p@ spread a single number over their components, s@ turns numbers into text; a value with the
    wrong number of components (f@a = @P) is an error naming the attribute
  · p@ has 4 components (VEX's quaternion, p@orient)
  · @group_name reads the group as 0 / 1 and writing it sets the group (no attribute called group_name appears);
    with the node's Group field, rows outside it keep their old membership
  · @P in a vertex wrangle is the position of the vertex's point
  · untyped writes are unchanged (size and dtype follow the value)
  · round() works on columns (it failed: Python's round has no array version), halves away from zero
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

from comfyui_pcg.geo import build  # noqa: E402
from comfyui_pcg.geo import wrangle as WR  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM, VERTEX  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if isinstance(extra, str) and not extra else "   " + str(extra)))


g = build.grid(size_x=2, size_z=2, cols=3, rows=3)          # 9 points, x and z in -1, 0, 1
P = g.get(POINT, "P")


def run(code, cls=POINT, geo=g, **kw):
    return WR.run_wrangle(geo, code, cls, **kw)


print("\n[typed writes convert]")
a = run("i@k = @P.x * 10 + 0.7").get(POINT, "k")
check("i@k = @P.x * 10 + 0.7 → int32, truncated like VEX (-9, 0, 10)",
      a.dtype == np.int32 and a.shape == (9, 1) and np.array_equal(a[:3, 0], [-9, 0, 10]), (a.dtype, a[:3, 0]))
a = run("f@a = @ptnum % 2").get(POINT, "a")
check("f@a = @ptnum % 2 → float32", a.dtype == np.float32 and np.array_equal(a[:4, 0], [0, 1, 0, 1]))
a = run("f@a = @P.x > 0").get(POINT, "a")
check("f@a = (a comparison) → float32 0 / 1", a.dtype == np.float32 and set(np.unique(a)) == {0.0, 1.0})
a = run("v@c = 0.5").get(POINT, "c")
check("v@c = 0.5 → (0.5, 0.5, 0.5) on every point", a.shape == (9, 3) and np.all(a == 0.5))
a = run("2@w = @P.x").get(POINT, "w")
check("2@w = @P.x → two equal floats", a.shape == (9, 2) and np.array_equal(a[:, 0], a[:, 1]))
a = run("p@orient = set(0, 0, 0, 1)").get(POINT, "orient")
check("p@orient has 4 components (VEX's quaternion)", a.shape == (9, 4) and np.all(a[:, 3] == 1))
a = run('s@n = @ptnum').get(POINT, "n")
check("s@n = @ptnum → text '0', '1', ...", a.dtype.kind == "U" and list(a[:3, 0]) == ["0", "1", "2"])
a = run('s@n = @P.x * 0.5').get(POINT, "n")
check("  floats become short text ('-0.5', '0', '0.5')", list(a[:3, 0]) == ["-0.5", "0", "0.5"], list(a[:3, 0]))
try:
    run("f@a = @P")
    err = ""
except Exception as e:
    err = str(e)
check("f@a = @P (3 components into 1) is an error naming the attribute", "a: declared with 1" in err, err[:80])
try:
    run('f@a = "x"')
    err = ""
except Exception as e:
    err = str(e)
check("f@a = \"x\" (text into a number) is an error", "declared as a number" in err, err[:80])

print("\n[untyped writes unchanged]")
a = run("@q = @ptnum % 2").get(POINT, "q")
check("@q = @ptnum % 2 keeps the value's int type", a.dtype.kind == "i")
a = run("@Cd = set(1, 0, 0)").get(POINT, "Cd")
check("@Cd = set(1, 0, 0) → 3 components", a.shape == (9, 3))
a = run("@foo = 1").get(POINT, "foo")
check("@foo = 1 → 1 component", a.shape == (9, 1))

print("\n[@group_]")
r = run("@group_top = @P.z > 0")
check("@group_top = @P.z > 0 makes the point group top (the 3 points with z = 1)",
      np.array_equal(np.asarray(r.get_group(POINT, "top")), P[:, 2] > 0))
check("  and no attribute called group_top", r.get(POINT, "group_top") is None)
r2 = run("@Cd = set(@group_top, 0, 0)", geo=r)
check("reading @group_top gives 0 / 1 per point", np.array_equal(r2.get(POINT, "Cd")[:, 0], (P[:, 2] > 0) * 1.0))
r3 = run("@group_top = 1", geo=r, group="@P.x > 0")
want = (P[:, 2] > 0) | (P[:, 0] > 0)
check("with Group = '@P.x > 0', only those points are added; the rest keep their membership",
      np.array_equal(np.asarray(r3.get_group(POINT, "top")), want))
r4 = run("f@a = @group_none")
check("a group that does not exist reads as 0", np.all(r4.get(POINT, "a") == 0) and r4.get_group(POINT, "none") is None)
r5 = run("@group_big = @P.x > 0", cls=PRIM)
check("on primitives it is a primitive group (centre x > 0: 2 of the 4 quads)",
      np.count_nonzero(r5.get_group(PRIM, "big")) == 2)

print("\n[vertex @P]")
r = run("v@q = @P", cls=VERTEX)
vp = np.asarray(g.vertex_point)
check("@P in a vertex wrangle is the vertex's point position",
      np.allclose(r.get(VERTEX, "q"), P[vp]) and r.get(VERTEX, "P") is None)

print("\n[round() on columns]")
g2 = build.grid(size_x=3, size_z=2, cols=4, rows=3)          # x = -1.5, -0.5, 0.5, 1.5
r = run("f@a = round(@P.x)\nf@b = round(2.5) + 10 * round(-2.5)\nf@c = round(@P.x * 0.37, 1)", geo=g2)
check("round(@P.x) works per point, halves away from zero (-2, -1, 1, 2) like VEX",
      np.array_equal(r.get(POINT, "a")[:4, 0], [-2, -1, 1, 2]), r.get(POINT, "a")[:4, 0])
check("  round() of a single number rounds the same way (2.5 → 3, -2.5 → -3)", r.get(POINT, "b")[0, 0] == -27)
check("  round(x, 1) keeps one decimal", np.allclose(r.get(POINT, "c")[:4, 0], [-0.6, -0.2, 0.2, 0.6]))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
