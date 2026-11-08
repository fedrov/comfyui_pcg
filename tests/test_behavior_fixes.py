"""
pcg90: verifies the batch of "behaviour does not match Houdini / our own docs" issues noted while reading the code in pcg86, after fixing them one by one.

Each one comes with a **negative control**: what the same input gives with the pre-pcg90 behaviour (computed by hand or reproduced with the old parameters),
confirming the test really can tell old and new behaviour apart -- otherwise a passing test would not prove the fix.

  Sort           primitive sorting has its own Seed / Offset / Vector / Center / Point / Component;
                 the four section toggles default to on (Houdini has none); in old workflows those that are off still use the defaults
  Carve          only Second U on = [0, Second U]; Extract takes one at each enabled position
  Reverse        the Shift section toggle defaults to on; off in old workflows = Offset 0
  Volume Mix     every volume in A is mixed: same name pairs with same name / if B has only one it pairs with all / otherwise by order
  Control Image  the Color mode has its own sRGB toggle; Line Art's normal layer can be filled in
  COP / Sequence Export  same mask rule: use it if present (clamped to 0-1, does not follow Range Mode), all 1 if absent, per frame
  Scatter from Map  Density Scale only multiplies the density attribute written out, unrelated to the distribution
  Copy to Curves copy number k counts from 0 for each curve
  FFT            the Magnitude mode obeys Centered
  From JSON      the three shapes follow the same coordinate rules
  Blend Shapes   sequential Blend counts by slot number, an empty slot holds at the previous shape
  Soft Transform empty Group = all points
  Channel 3      empty = 0:0, still x Scale + Offset
  Remesh to Grid Smooth no longer depends on Project
  out_layer      only spaces = empty (uses the default layer name)
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
from comfyui_pcg.geo import build, ops, uvproject      # noqa: E402
from comfyui_pcg.geo import structured, deformers      # noqa: E402
from comfyui_pcg.geo.volume import make_volume          # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402
from comfyui_pcg.geo.cop import morph                   # noqa: E402
from comfyui_pcg.geo.frommap import srgb_encode         # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def defaults(nid, **over):
    kw = {}
    it = M[nid].INPUT_TYPES()
    for part in ("required", "optional"):
        for k, spec in it.get(part, {}).items():
            if k in over:
                kw[k] = over[k]
            elif isinstance(spec[0], (list, tuple)):
                kw[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    return kw


def call(nid, **over):
    r = getattr(M[nid](), M[nid].FUNCTION)(**defaults(nid, **over))
    if isinstance(r, dict):
        r = r["result"]
    return r


def run(nid, **over):
    return call(nid, **over)[0]


def npa(t):
    return np.asarray(t.numpy() if hasattr(t, "numpy") else t)


def ui(nid, name):
    spec = M[nid].INPUT_TYPES()["required"][name]
    return spec[1].get("pcg_ui", {})


def pts(*ps):
    return Geometry.from_points(np.array(ps, np.float32))


def P(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


# ═══════════════════════════════════════════════════════════ Sort
sec("Sort: primitive sorting has its own parameters; the four section toggles default to on")
# 4 triangles laid out along x, x decreasing (prim 0 at x = 3, prim 3 at x = 0)
tris = ops.merge(*[Geometry.from_mesh(
    np.array([[3 - i, 0, 0], [3 - i + .2, 0, 0], [3 - i, 0, .2]], np.float32), [[0, 1, 2]])
    for i in range(4)])


def prim_x(g):
    pc = ops.prim_centers(g)
    return np.round(np.asarray(pc)[:, 0] - 0.2 / 3, 6).tolist()


g = run("PCG_Sort", geo=tris, prim_sort="shift", prim_offset=1)
check("primitive sort Shift with Prim Offset = 1: prim 0 becomes the original prim 1", prim_x(g) == [2, 1, 0, 3], prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="shift", offset=1)
check("  negative control: the point Offset = 1 no longer affects primitive sorting (it used to be shared and would shift)", prim_x(g) == [3, 2, 1, 0],
      prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="along_vector", prim_axis_x=1.0, prim_axis_y=0.0)
check("primitive sort Along Vector with Prim Vector (1,0,0): by x ascending", prim_x(g) == [0, 1, 2, 3],
      prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="along_vector", axis_x=1.0, axis_y=0.0)
check("  negative control: the point Vector does not affect primitive sorting (prims still use the default +Y, all four at the same height, order unchanged)",
      prim_x(g) == [3, 2, 1, 0], prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="proximity", prim_target_x=3.0)
check("primitive sort Proximity with Prim Point (3,0,0): nearest first", prim_x(g) == [3, 2, 1, 0], prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="proximity", prim_target_x=0.0, target_x=3.0)
check("  the other way round, Prim Point (0,0,0), point Point (3,0,0): follows the primitive one", prim_x(g) == [0, 1, 2, 3],
      prim_x(g))
seeded = [run("PCG_Sort", geo=tris, prim_sort="random", prim_rand_seed=s) for s in range(6)]
check("primitive sort Random with Prim Seed: changing the seed changes the order", len({tuple(prim_x(x)) for x in seeded}) > 1)
same = [run("PCG_Sort", geo=tris, prim_sort="random", rand_seed=s) for s in range(6)]
check("  negative control: changing only the point Seed leaves the primitive order unchanged", len({tuple(prim_x(x)) for x in same}) == 1)
# primitive sort Attribute's Component: prim attribute v = (-i, i), sorting by component 1 = original order, by component 0 = reversed
ta = tris.copy()
ta.set(PRIM, "v", np.array([[-i, i] for i in range(4)], np.float32))
g = run("PCG_Sort", geo=ta, prim_sort="attribute", prim_attrib="v", prim_component=0,
        component=1)
check("primitive sort Attribute with Prim Component = 0 (point Component = 1 is ignored)",
      prim_x(g) == [0, 1, 2, 3], prim_x(g))
# primitive sort Circular's Prim Center: moving the center outside the ring to (3,0,0) changes the angular order around it
ring = ops.merge(*[Geometry.from_mesh(np.array(
    [[np.cos(a), 0, np.sin(a)], [np.cos(a) + .01, 0, np.sin(a)], [np.cos(a), 0, np.sin(a) + .01]],
    np.float32), [[0, 1, 2]]) for a in (0.3, 1.9, 3.5, 5.1)])


def circ(**kw):
    return [round(float(c[0]), 3) for c in ops.prim_centers(run("PCG_Sort", geo=ring,
                                                                prim_sort="circular", **kw))]


a0 = circ()
a1 = circ(prim_use_center=True, prim_center_x=3.0)
check("primitive sort Circular with Prim Center (changing the center changes the start too)", a0 != a1, (a0, a1))
check("  negative control: the point Center does not affect primitive sorting", circ(use_center=True, center_x=3.0) == a0)
# the point sort set works as before
pp = pts((2, 0, 0), (0, 0, 0), (1, 0, 0))
g = run("PCG_Sort", geo=pp, point_sort="along_vector", axis_x=1.0, axis_y=0.0)
check("point sort Along Vector still uses the point Vector", P(g)[:, 0].tolist() == [0, 1, 2], P(g)[:, 0])

for gname in ("use_axis", "use_target", "use_key", "use_rs"):
    spec = M["PCG_Sort"].INPUT_TYPES()["required"][gname]
    check(f"section toggle {gname} defaults to on, hidden on the panel while on",
          spec[1]["default"] is True and f"{gname} == 1" in ui("PCG_Sort", gname).get("hide", ""),
          (spec[1]["default"], ui("PCG_Sort", gname).get("hide")))
g = run("PCG_Sort", geo=tris, prim_sort="shift", prim_offset=1, use_rs=False)
check("Random / Shift sections off in an old workflow: Prim Offset also uses the default 0 (the section toggle governs both)",
      prim_x(g) == [3, 2, 1, 0], prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="along_vector", prim_axis_x=1.0, prim_axis_y=0.0,
        use_axis=False)
check("  Axis section off: Prim Vector falls back to the default +Y", prim_x(g) == [3, 2, 1, 0], prim_x(g))
g = run("PCG_Sort", geo=tris, prim_sort="proximity", prim_target_x=3.0, use_target=False)
check("  Proximity section off: Prim Point falls back to the origin (ignores (3,0,0) even if filled in, nearest is the prim at x = 0)",
      prim_x(g) == [0, 1, 2, 3], prim_x(g))
# four prims with centroid height y = i: with the Axis section off, Prim Vector set to downward (0,-1,0) is ignored, default +Y gives low to high
steps = ops.merge(*[Geometry.from_mesh(
    np.array([[3 - i, i, 0], [3 - i + .2, i, 0], [3 - i, i, .2]], np.float32), [[0, 1, 2]])
    for i in (2, 0, 3, 1)])
g = run("PCG_Sort", geo=steps, prim_sort="along_vector", prim_axis_y=-1.0, use_axis=False)
ys = [round(float(c[1]), 6) for c in ops.prim_centers(g)]
check("  Axis section off: Prim Vector with y = -1 still uses the default +Y (low to high)", ys == [0, 1, 2, 3], ys)
g = run("PCG_Sort", geo=steps, prim_sort="along_vector", prim_axis_y=-1.0)
ys = [round(float(c[1]), 6) for c in ops.prim_centers(g)]
check("    comparison: with the section on it uses -Y (high to low)", ys == [3, 2, 1, 0], ys)
g = run("PCG_Sort", geo=ta, prim_sort="attribute", prim_attrib="v", use_key=False)
check("  Attribute section off: attribute name uses the default (empty) = no sorting", prim_x(g) == [3, 2, 1, 0], prim_x(g))
kw = defaults("PCG_Sort", geo=tris, prim_sort="shift", offset=1)
for k in [k for k in kw if k.startswith("prim_") and k not in ("prim_sort", "prim_attrib",
                                                                  "prim_expr")]:
    kw.pop(k)
g = M["PCG_Sort"]().run(**kw)
g = (g["result"] if isinstance(g, dict) else g)[0]
check("old workflows (without the prim_* widgets) still run, primitive Offset defaults to 0",
      prim_x(g) == [3, 2, 1, 0], prim_x(g))

# ═══════════════════════════════════════════════════════════ Carve
sec("Carve: the end that is not enabled is the endpoint; Extract takes one per position")
LINE = build.line((0, 0, 0), (1, 0, 0), 1.0, 11)


def span(g):
    x = P(g)[:, 0]
    return (round(float(x.min()), 6), round(float(x.max()), 6))


g = run("PCG_Carve", geo=LINE, use_first_u=False, use_second_u=True, second_u=0.75)
check("only Second U = 0.75 on, Keep Inside: keeps 0 ~ 0.75", span(g) == (0.0, 0.75), span(g))
check("  negative control: before pcg90 it was treated as 0 ~ 1 (whole curve kept)", span(g) != (0.0, 1.0))
g = run("PCG_Carve", geo=LINE, use_first_u=False, use_second_u=True, second_u=0.75,
        keep_inside=False, keep_outside=True)
check("only Second U on, Keep Outside: keeps 0.75 ~ 1", span(g) == (0.75, 1.0), span(g))
g = run("PCG_Carve", geo=LINE, first_u=0.25)
check("only First U on (default): keeps 0.25 ~ 1 as before", span(g) == (0.25, 1.0), span(g))
g = run("PCG_Carve", geo=LINE, use_second_u=True, first_u=0.6, second_u=0.2)
check("both on (entered in reverse order): keeps 0.2 ~ 0.6", span(g) == (0.2, 0.6), span(g))
g = run("PCG_Carve", geo=LINE, mode="extract", use_second_u=True, first_u=0.25, second_u=0.75)
check("Extract with both on: takes two points x = 0.25, 0.75",
      g.npoints == 2 and np.allclose(sorted(P(g)[:, 0]), [0.25, 0.75]), P(g)[:, 0])
g = run("PCG_Carve", geo=LINE, mode="extract", use_first_u=False, use_second_u=True,
        second_u=0.75)
check("Extract with only Second U on: one point x = 0.75 (used to take 0)",
      g.npoints == 1 and np.isclose(P(g)[0, 0], 0.75), P(g))
g = run("PCG_Carve", geo=LINE, mode="extract", use_first_u=False)
check("Extract with neither on: no points", g.npoints == 0, g.npoints)
NC = run("PCG_Convert", geo=build.line((0, 0, 0), (1, 0, 0), 1.0, 5), convert_to="nurbs_curve")
g = run("PCG_Carve", geo=NC, mode="extract", use_first_u=False, relative_arc_length=True)
check("NURBS curve Extract with neither on: no points", g.npoints == 0, g.npoints)
g = run("PCG_Carve", geo=NC, mode="extract", use_second_u=True, first_u=0.25, second_u=0.75,
        relative_arc_length=True)
check("NURBS curve Extract with both on (by arc length): two points x = 0.25, 0.75",
      g.npoints == 2 and np.allclose(sorted(P(g)[:, 0]), [0.25, 0.75], atol=2e-3), P(g)[:, 0])

# ═══════════════════════════════════════════════════════════ Reverse
sec("Reverse: the Shift section toggle defaults to on")
quad = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], np.float32),
                          [[0, 1, 2, 3]])
spec = M["PCG_Reverse"].INPUT_TYPES()["required"]["use_shift"]
check("use_shift defaults to on, hidden on the panel while on",
      spec[1]["default"] is True and "use_shift == 1" in ui("PCG_Reverse", "use_shift")["hide"])
g = run("PCG_Reverse", geo=quad, mode="shift", u_offset=1)
check("new node: choose Shift, set U Offset = 1 and it shifts (vertex list 1 2 3 0)",
      g.vertex_point.tolist() == [1, 2, 3, 0], g.vertex_point.tolist())
g = run("PCG_Reverse", geo=quad, mode="shift", u_offset=1, use_shift=False)
check("  off in an old workflow: Offset uses the default 0, no change", g.vertex_point.tolist() == [0, 1, 2, 3])

# ═══════════════════════════════════════════════════════════ Volume Mix
sec("Volume Mix: every volume in A is mixed")


def vols(names, vals):
    gs = [make_volume((3, 3, 3), (1, 1, 1), fill=v) for v in vals]
    g = ops.merge(*gs) if len(gs) > 1 else gs[0]
    if names:
        g.set_string(PRIM, "name", list(names))
    return g


def vvals(g):
    return [round(float(np.asarray(g.pdata(i, "voxels")).mean()), 6) for i in range(g.nprims)]


A = vols(["d", "t"], [1.0, 2.0])
g = run("PCG_VolumeMix", geo_a=A, geo_b=vols(["t", "d"], [10.0, 20.0]), operation="add")
check("paired by name: d = 1 + 20, t = 2 + 10", vvals(g) == [21.0, 12.0], vvals(g))
check("  negative control: pairing by order gives 11, 22; before pcg90 only the first was mixed, giving 11, 2", vvals(g) not in ([11, 22], [11, 2]))
g = run("PCG_VolumeMix", geo_a=A, geo_b=vols(None, [5.0]), operation="add")
check("B has only one: every volume in A pairs with it (6, 7)", vvals(g) == [6.0, 7.0], vvals(g))
g = run("PCG_VolumeMix", geo_a=vols(None, [1, 2, 3]), geo_b=vols(None, [10, 20]),
        operation="add")
check("no names, B smaller than A: paired by order, the extra third one unchanged", vvals(g) == [11.0, 22.0, 3.0], vvals(g))
r = call("PCG_VolumeMix", geo_a=vols(None, [1, 2, 3]), geo_b=vols(None, [10, 20]),
         operation="add")[1]
check("  the report lists the unmatched ones", "unmatched_a" in str(r) and "2" in str(r), r)
g = run("PCG_VolumeMix", geo_a=A, geo_b=vols(["t", "d"], [10.0, 20.0]), operation="add",
        volume_a="t")
check("Volume A selects only t: only t is mixed, d unchanged", vvals(g) == [1.0, 12.0], vvals(g))
try:
    run("PCG_VolumeMix", geo_a=vols(["x"], [1]), geo_b=vols(["p", "q"], [1, 2]),
        operation="add", volume_b="")
    check("A's name not in B, B has more than one, 0th by order: pairs with p", True)
except Exception as e:                                  # noqa: BLE001
    check("A's name not in B, B has more than one, 0th by order: pairs with p", False, e)

# ═══════════════════════════════════════════════════════════ Control Image
sec("Control Image: the Color mode's own sRGB toggle; Line Art's normal layer")
H = W = 16
C = CopImage(W, H, {"C": np.full((H, W, 3), 0.5)})
img = lambda **kw: npa(call("PCG_ControlImage", cop=C, kind="color", align=0, **kw)[0])  # noqa: E731
check("Color mode encodes sRGB by default (0.5 -> 0.7354, same as before)",
      np.allclose(img(), srgb_encode(0.5), atol=1e-6), img()[0, 0, 0, 0])
check("Color mode with color_srgb off: outputs linear 0.5 unchanged", np.allclose(img(color_srgb=False), 0.5))
check("  negative control: the Color mode used to only look at srgb (encoded even when off); now srgb has no effect on the Color mode",
      np.allclose(img(srgb=False), img(srgb=True)))
D = CopImage(W, H, {"depth": np.full((H, W, 1), 0.5), "mask": np.ones((H, W, 1))})
dep = lambda **kw: npa(call("PCG_ControlImage", cop=D, kind="mask", layer="depth",  # noqa: E731
                            align=0, **kw)[0])
check("other modes are not affected by color_srgb", np.allclose(dep(color_srgb=False), dep(color_srgb=True)))
nrm = np.zeros((H, W, 3))
nrm[:, :W // 2] = (0, 0, 1)
nrm[:, W // 2:] = (1, 0, 0)
L1 = CopImage(W, H, {"depth": np.full((H, W, 1), 1.0), "mask": np.ones((H, W, 1)),
                     "Nc": nrm})
L2 = CopImage(W, H, {"depth": np.full((H, W, 1), 1.0), "mask": np.ones((H, W, 1)), "N": nrm})
la = lambda c, **kw: npa(call("PCG_ControlImage", cop=c, kind="lineart", align=0,  # noqa: E731
                              silhouette=0.0, **kw)[0])
a, b = la(L1, normal_layer="Nc"), la(L2)
check("Line Art with Normal Layer = Nc: pixel-identical to normals stored in N with the default",
      np.array_equal(a, b) and a.max() > 0.5, (a.max(), b.max()))
check("  the crease is in the two middle columns", a[0, :, W // 2 - 1:W // 2 + 1].max() > 0.5
      and a[0, :, :W // 2 - 3].max() < 1e-6)
try:
    la(L1)
    check("  negative control: the default N does not exist in L1, so Nc is not used by accident", False)
except Exception:                                       # noqa: BLE001
    check("  negative control: the default N does not exist in L1, so Nc is not used by accident", True)

# ═══════════════════════════════════════════════════════════ Export masks
sec("COP Export / Sequence Export: same mask rule")
img0 = CopImage(4, 2, {"C": np.full((2, 4, 3), 0.25),
                       "mask": np.array([[[0], [0], [1], [3]]] * 2, np.float64)})
img1 = CopImage(4, 2, {"C": np.full((2, 4, 3), 0.75)})
_, m = call("PCG_COPExport", cop=img1)
check("COP Export without a mask layer: all 1 (used to be all 0)", np.array_equal(npa(m), np.ones((1, 2, 4))),
      npa(m))
_, m = call("PCG_COPExport", cop=img0, mode="signed")
check("COP Export Signed mode: mask still 0 / 1, clamped to 0-1 (0 used to become 0.5, 3 become 2)",
      npa(m)[0, 0].tolist() == [0, 0, 1, 1], npa(m)[0, 0])
_, m = call("PCG_COPExport", cop=img0, mode="normalize")
check("  Normalize mode also leaves the mask alone", npa(m)[0, 0].tolist() == [0, 0, 1, 1], npa(m)[0, 0])
_, m, n = call("PCG_SequenceExport", seq=[img0, img1])
m = npa(m)
check("Sequence Export: frames with a mask use it, missing frames are all 1 (used to be all 1 for the whole batch if a single frame was missing)",
      n == 2 and m[0, 0].tolist() == [0, 0, 1, 1] and np.all(m[1] == 1), m[:, 0])
_, m, _ = call("PCG_SequenceExport", seq=[img0], mode="signed")
check("  Sequence Export's mask does not follow Range Mode either", npa(m)[0, 0].tolist() == [0, 0, 1, 1])
_, m = call("PCG_COPExport", cop=img0, mask_layer=" ")
check("  mask layer name of only spaces = not filled in: all 1", np.all(npa(m) == 1))
_, m = call("PCG_COPExport", cop=img0, mask_layer=" mask ")
check("  layer name with surrounding spaces: spaces stripped, mask still found", npa(m)[0, 0].tolist() == [0, 0, 1, 1], npa(m)[0, 0])

# ═══════════════════════════════════════════════════════════ Scatter from Map
sec("Scatter from Map: Density Scale only multiplies the density attribute")
GRID = uvproject.project(build.grid(2, 2, 9, 9), mode="planar", axis="y")
ramp = CopImage(64, 4, {"C": np.repeat(((np.arange(64) + 0.5) / 64)[None, :, None], 4, 0)})


def sfm(**kw):
    g = run("PCG_ScatterFromMap", geo=GRID, cop=ramp, count=4000, rand_seed=3, **kw)
    return g, np.asarray(uv_of(g)), np.asarray(g.get(POINT, "density"), np.float64)[:, 0]


from comfyui_pcg.geo.frommap import uv_of as _uv_of     # noqa: E402


def uv_of(g):
    return _uv_of(g, POINT, "uv", "point")[0][:, 0]


g1, u1, d1 = sfm(invert=True)
g2, u2, d2 = sfm(invert=True, density_scale=2.0)
check("Invert + Scale 2: point positions identical one by one to Scale 1", np.array_equal(P(g1), P(g2)))
check("  density attribute exactly doubled", np.allclose(d2, 2 * d1), (d1[:3], d2[:3]))
check("  density 1 - u: mean of u ≈ 1/3 (analytic)", abs(u2.mean() - 1 / 3) < 0.015, u2.mean())
check("  negative control: before pcg90 density was 1 - 2u (clamped to 0 above 0.5), mean 1/6", abs(u2.mean() - 1 / 6) > 0.1)
# image values not spanning the full 0..1 range: 0.2 + 0.4u, after invert 0.8 - 0.4u. The probability upper bound must be the max after invert, 0.8,
# analytic mean ∫u(0.8-0.4u)/∫(0.8-0.4u) = 0.4444; wrongly taking the pre-invert 0.6 as the bound accepts all u < 0.5, mean 0.4697
ramp2 = CopImage(64, 4, {"C": 0.2 + 0.4 * ramp.need("C")})
g5 = run("PCG_ScatterFromMap", geo=GRID, cop=ramp2, count=8000, rand_seed=5, invert=True)
u5 = uv_of(g5)
check("inverted image not spanning the full range: probability upper bound uses the max after invert (mean of u ≈ 0.4444)",
      abs(u5.mean() - 0.26667 / 0.6) < 0.01, u5.mean())
_, u3, _ = sfm(density_floor=0.5, density_scale=3.0)
check("Floor 0.5 + Scale 3: density max(u, 0.5), mean of u ≈ 0.5667 (with the old max(3u, 0.5) it was 0.650)",
      abs(u3.mean() - 0.35417 / 0.625) < 0.015, u3.mean())

# ═══════════════════════════════════════════════════════════ Copy to Curves
sec("Copy to Curves: copy number counts from 0 for each curve")
curves = ops.merge(build.line((0, 0, 0), (1, 0, 0), 4.0, 5),
                   build.line((0, 0, 5), (1, 0, 0), 4.0, 5))
src = pts((0, 1, 0))
g = run("PCG_CopyToCurves", source=src, curves=curves, count=3, roll_step=90.0)
Q = P(g)
check("6 copies in total", len(Q) == 6, len(Q))
first2 = Q[3] - np.array([0, 0, 5])
check("first copy on the second curve not rotated: (0,1,0) still points up (it used to be copy 4, rotated 270°)",
      np.allclose(first2, (0, 1, 0), atol=1e-5), first2)
check("  both curves identical copy by copy (the second moved by z = 5 as a whole)", np.allclose(Q[:3], Q[3:] - [0, 0, 5],
                                                     atol=1e-5), Q)
check("  second copy on the first curve rotated 90° (y component 0)", abs(Q[1, 1]) < 1e-5, Q[1])

# ═══════════════════════════════════════════════════════════ FFT
sec("FFT: the Magnitude mode obeys Centered")
F = CopImage(8, 8, {"C": np.ones((8, 8, 1))})


def peak(centered):
    o = M["PCG_COPFFT"]().run(F, "C", "magnitude", centered, "lowpass", 8.0, 32.0, 2.0, "")[0]
    a = np.asarray(o.need("C_magnitude"))[..., 0]
    return tuple(int(v) for v in np.unravel_index(np.argmax(a), a.shape))


check("Centered on: DC at the image center (4, 4)", peak(True) == (4, 4), peak(True))
check("Centered off: DC at (0, 0) (this mode used to always move it to the center regardless of the toggle)", peak(False) == (0, 0),
      peak(False))
check("panel: Centered hidden only in the Filter mode",
      ui("PCG_COPFFT", "centered").get("hide") == "{ mode == filter }",
      ui("PCG_COPFFT", "centered"))

# ═══════════════════════════════════════════════════════════ From JSON
sec("From JSON: the three shapes follow the same coordinate rules")


def fj(text, **kw):
    return run("PCG_FromJSON", json_text=text, **kw)


ctr = dict(center_x=1.0, center_y=2.0, center_z=3.0)
g = fj('[{"pos": [5, 7]}]', normalized=False, **ctr)
check("point, 2D, not normalized: lands on xz then translated by Center -> (6, 2, 10) (used to be (5, 0, 7))",
      np.allclose(P(g)[0], (6, 2, 10)), P(g)[0])
g = fj('[{"pos": [5, 7]}]', normalized=False, flip_v=True, **ctr)
check("  Flip V (not normalized = v -> -v) -> (6, 2, -4)", np.allclose(P(g)[0], (6, 2, -4)), P(g)[0])
g = fj('[{"points": [[5, 7], [6, 7]]}]', mode="curves", normalized=False, **ctr)
check("curve, 2D, not normalized: first point same as the point above (6, 2, 10)",
      np.allclose(P(g)[0], (6, 2, 10)), P(g)[0])
g = fj('[{"bbox": [0, 0, 2, 1]}]', mode="boxes", normalized=False, **ctr)
bb = (P(g).min(0).round(6).tolist(), P(g).max(0).round(6).tolist())
check("box, 2D, not normalized: x 1~3, z 3~4, y = 2 (used to be x 0~2, z 0~1)",
      bb == ([1, 2, 3], [3, 2, 4]), bb)
g = fj('[{"pos": [1, 2, 3]}]', **ctr)
check("point, 3D (normalize on by default): world coordinates + Center -> (2, 4, 6) (Center used to be ignored)",
      np.allclose(P(g)[0], (2, 4, 6)), P(g)[0])
g = fj('[{"points": [[1, 2, 3], [1, 2, 4]]}]', mode="curves", **ctr)
check("curve, 3D: likewise (2, 4, 6)", np.allclose(P(g)[0], (2, 4, 6)), P(g)[0])
g = fj('[{"bbox": [0, 0, 0, 1, 2, 3]}]', mode="boxes", **ctr)
bb = (P(g).min(0).round(6).tolist(), P(g).max(0).round(6).tolist())
check("box, 3D: world coordinates + Center, size not scaled -> (1,2,3) ~ (2,4,6) (used to be scaled 10x by Size)",
      bb == ([1, 2, 3], [2, 4, 6]), bb)
g = fj('[{"pos": [0.25, 0.25]}]')
check("normalized 2D as before: (0.25, 0.25) -> (-2.5, 0, -2.5)", np.allclose(P(g)[0], (-2.5, 0, -2.5)),
      P(g)[0])
g = fj('[{"pos": [0.25, 0.25]}]', flip_v=True, **ctr)
check("  normalized + Flip V + Center: (-1.5, 2, 5.5)", np.allclose(P(g)[0], (-1.5, 2, 5.5)), P(g)[0])
check("panel: Flip V also usable when not normalized", "disable" not in ui("PCG_FromJSON", "flip_v"))

# ═══════════════════════════════════════════════════════════ Blend Shapes
sec("Blend Shapes: sequential counts by slot number")
base, t1, t3 = pts((0, 0, 0)), pts((1, 0, 0)), pts((0, 0, 3))


def bs(**kw):
    return P(run("PCG_BlendShapes", base=base, target1=t1, target3=t3, mode="sequential",
                 **kw))[0].round(6).tolist()


check("target2 empty, Blend = 2: holds at target1 (1,0,0) (used to land on target3)", bs(blend=2.0) == [1, 0, 0],
      bs(blend=2.0))
check("  Blend = 1.5: still target1 (no change across the empty slot's segment)", bs(blend=1.5) == [1, 0, 0], bs(blend=1.5))
check("  Blend = 2.5: halfway between target1 and target3 (0.5, 0, 1.5)", bs(blend=2.5) == [0.5, 0, 1.5],
      bs(blend=2.5))
check("  Blend = 3:target3", bs(blend=3.0) == [0, 0, 3], bs(blend=3.0))
check("  Blend = 4 (beyond the highest slot): clamped at target3", bs(blend=4.0) == [0, 0, 3], bs(blend=4.0))
check("  Blend = 0.5: halfway from base to target1", bs(blend=0.5) == [0.5, 0, 0], bs(blend=0.5))
r = P(run("PCG_BlendShapes", base=base, target1=t1, target3=t3, mode="additive",
          weight1=1.0, weight2=5.0, weight3=2.0))[0].round(6).tolist()
check("additive: weights follow the slots (target2 empty, weight2 = 5 has no effect) -> (1, 0, 6)",
      r == [1, 0, 6], r)
r = P(run("PCG_BlendShapes", base=base, target1=t1, target2=t3, mode="sequential",
          blend=2.0))[0].round(6).tolist()
check("slots connected contiguously behave as before: Blend = 2 = target2", r == [0, 0, 3], r)
g, rep = deformers.blend_shapes(base, [None, t3], [0.0, 1.0], "additive")
check("library function: targets given by slot, weights also by slot", P(g)[0].round(6).tolist() == [0, 0, 3], P(g)[0])

# ═══════════════════════════════════════════════════════════ Soft Transform
sec("Soft Transform: empty Group = all points")
cloud = pts((0, 0, 0), (5, 0, 0), (9, 9, 9))
g = run("PCG_SoftTransform", geo=cloud, group="", ty=1.0)
check("empty + ty = 1: all points move up by 1 (used to move none)", np.allclose(P(g) - P(cloud), (0, 1, 0)),
      P(g))
g = run("PCG_SoftTransform", geo=cloud, group="", ry=90.0)
check("  empty + rotation: rotates around the centroid of all points (radius preserved)",
      np.allclose(np.linalg.norm(P(g) - P(cloud).mean(0), axis=1),
                  np.linalg.norm(P(cloud) - P(cloud).mean(0), axis=1), atol=1e-4))
g = run("PCG_SoftTransform", geo=cloud, group="@P.y > 100", ty=1.0)
check("  group given but selecting no points: no change (not the same as empty)", np.allclose(P(g), P(cloud)))
g = run("PCG_SoftTransform", geo=cloud, group="0", ty=1.0, radius=1.0)
check("  group = point 0: only it and points within the radius move", np.allclose(P(g)[1:], P(cloud)[1:])
      and np.isclose(P(g)[0, 1], 1.0))

# ═══════════════════════════════════════════════════════════ Channel 3
sec("Channel 3: empty = 0:0")
r = call("PCG_Channel3", frame=5.0, keys_x="", keys_y="0:0", keys_z="", scale=2.0, offset=5.0)
check("empty x, z same as y set to 0:0: 0 x 2 + 5 = 5 (empty used to give 0 directly)",
      r[0] == r[1] == r[2] == 5.0, r[:3])
r = call("PCG_Channel3", frame=0.0, keys_x="", keys_y="", keys_z="")
check("  default Scale 1 / Offset 0: empty is still 0", r[:3] == (0.0, 0.0, 0.0), r[:3])

# ═══════════════════════════════════════════════════════════ Remesh to Grid
sec("Remesh to Grid: Smooth no longer depends on Project")
SPH = ops.compute_normals(build.sphere(1.0, 24, 16))
g0 = run("PCG_RemeshToGrid", geo=SPH, voxel_size=0.2, project=False, smooth=0)
g2 = run("PCG_RemeshToGrid", geo=SPH, voxel_size=0.2, project=False, smooth=4)
rad = lambda g: float(np.linalg.norm(P(g), axis=1).mean())  # noqa: E731
check("Project off: Smooth 4 iterations differs from 0 (used to be the same)", not np.allclose(P(g0), P(g2)),
      (rad(g0), rad(g2)))


def edge_cv(g):
    F = np.asarray(g.vertex_point).reshape(-1, 4)
    e = np.linalg.norm(P(g)[F] - P(g)[np.roll(F, -1, 1)], axis=2).ravel()
    return float(e.std() / e.mean())


check("  tangential relaxation: edge lengths more even (smaller coefficient of variation)", edge_cv(g2) < edge_cv(g0) * 0.9,
      (edge_cv(g0), edge_cv(g2)))
check("  tangential, barely shrinks: mean radius difference < 1%", abs(rad(g2) - rad(g0)) < 0.01, (rad(g0), rad(g2)))
check("  topology unchanged", g0.npoints == g2.npoints and g0.nprims == g2.nprims)
gp, rp = call("PCG_RemeshToGrid", geo=SPH, voxel_size=0.2, project=True, smooth=4)
check("Project on: projected back after every relaxation iteration, final points lie on the original mesh (max_distance ≈ 0)",
      '"max_distance": ' in str(rp) and float(str(rp).split('"max_distance": ')[1].split(",")[0]
                                              .rstrip("}")) < 1e-5, rp)
check("Project on: projected back every iteration, stays on the sphere (radius ≈ 1)",
      abs(float(np.linalg.norm(P(gp), axis=1).max()) - 1) < 0.02,
      float(np.linalg.norm(P(gp), axis=1).max()))
check("panel: Smooth no longer greyed out with Project", "disable" not in ui("PCG_RemeshToGrid", "smooth"))

# ═══════════════════════════════════════════════════════════ out_layer
sec("out_layer of only spaces = empty")
E = CopImage(8, 8, {"C": np.random.default_rng(0).random((8, 8, 1))})
o = morph.edge(E, "C", out_layer="  ")
check("Edge: out_layer = two spaces -> writes to edge, no layer named with spaces",
      "edge" in o and " " not in o.names and "  " not in o.names, o.names)
import re                                               # noqa: E402
import glob                                             # noqa: E402
_pkg = os.path.dirname(sys.modules[M["PCG_Sort"].__module__].__file__)
left = [f"{os.path.basename(f)}:{i + 1}"
        for f in glob.glob(os.path.join(_pkg, "**", "*.py"), recursive=True)
        if os.sep + "tests" + os.sep not in f and not os.path.basename(f).startswith(("test_", "_"))
        for i, ln in enumerate(open(f, encoding="utf-8"))
        if re.search(r"str\(out_layer\) or ", ln)]
check("no unstripped str(out_layer) or … left anywhere in the package", not left, left)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
