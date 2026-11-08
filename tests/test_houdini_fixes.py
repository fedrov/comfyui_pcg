"""
pcg85: verification after fixing, one by one, the implementation differences found while building parameter panels against Houdini.

None of the references rely on the implementation itself:
  rotation order     (0,0,1) rotated by rx = ry = 90°: Houdini's Rx Ry Rz gives (0,−1,0); all six orders
               compared one by one against single-axis matrices multiplied in sequence; Rotate Order = zyx reproduces the pre-pcg85 (1,0,0) (negative control);
               Soft Transform / Copy and Transform use the same convention as Transform
  section toggles       every widget in the run() signature is read in the function body (static check over all nodes; counter-proof: removing one
               read gets reported); PolyExtrude / Convert / Carve with a section toggle off = that section uses default values
  Boolean face groups two unit boxes offset by half a cell: counted by area -- A Outside B / B Outside A / A Inside B /
               B Inside A are each 3 or 0 under union / intersect / subtract, matching hand calculation; area unchanged after Detriangulate;
               Shatter: three mutually disconnected pieces, no groups written with the toggle off
  Group Create Include by Edges is a union: with only it on, start from the empty set; Random doesn't filter out edge-selected ones;
               Unshared and the angle rule select independently and are unioned; Keep still available (extra in this plugin)
  Extract Centroid  detail mode respects group; when splitting by points, Bounding Box is the bounding box center, not the point average;
               Centroid Attribute off writes nothing
  Scatter      Use Geometric Normals takes effect without Relax
  COP Light    point light + Shadows no longer errors (the analytic shadow reference is in test_cop_geoimg.py)
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
from comfyui_pcg.nodes_common import _sec_defaults      # noqa: E402
from comfyui_pcg.geo import build, ops, groups as GR    # noqa: E402
from comfyui_pcg.geo import deform, copyxform, centroid  # noqa: E402
from comfyui_pcg.geo import boolean as BL               # noqa: E402
from comfyui_pcg.geo import topology as TP              # noqa: E402
from comfyui_pcg.geo.measure import prim_areas          # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, PRIM  # noqa: E402
from comfyui_pcg.geo.cop.core import CopImage           # noqa: E402

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


def run(nid, **over):
    r = getattr(M[nid](), M[nid].FUNCTION)(**defaults(nid, **over))
    if isinstance(r, dict):                # nodes with a preview return {"ui": ..., "result": (...)}
        r = r["result"]
    return r[0]


def one_point(p):
    return Geometry.from_points(np.array([p], np.float32))


# ═══════════════════════════════════════════════════════════ Rotation order
sec("Rotation order = Houdini's Rx Ry Rz (X first)")
P1 = one_point((0, 0, 1))
r = run("PCG_Transform", geo=P1, rx=90.0, ry=90.0).get(POINT, "P")[0]
check("Transform: (0,0,1) rotated by rx = ry = 90° -> (0,−1,0) (Houdini's result)",
      np.allclose(r, (0, -1, 0), atol=1e-6), r)
r_old = run("PCG_Transform", geo=P1, rx=90.0, ry=90.0,
            rotate_order="zyx").get(POINT, "P")[0]
check("  negative control: Rotate Order = zyx reproduces the pre-pcg85 (1,0,0)",
      np.allclose(r_old, (1, 0, 0), atol=1e-6), r_old)


def axis(ax, deg):
    return ops.euler_matrix(*[deg if a == ax else 0.0 for a in "xyz"])


ang = {"x": 23.0, "y": -41.0, "z": 67.0}
bad = []
for order in ops.ROTATE_ORDERS:
    want = np.eye(3)
    for a in order:                           # the first rotation is rightmost
        want = axis(a, ang[a]) @ want
    got = ops.euler_matrix(ang["x"], ang["y"], ang["z"], order=order)
    if not np.allclose(got, want, atol=1e-6):
        bad.append(order)
check("six orders: each equals single-axis matrices multiplied in sequence", not bad, bad)
check("  the six orders all differ pairwise (when all three angles are nonzero)",
      len({np.round(ops.euler_matrix(23, -41, 67, order=o), 5).tobytes()
           for o in ops.ROTATE_ORDERS}) == 6)
try:
    ops.euler_matrix(1, 2, 3, order="xxz")
    check("invalid order errors", False)
except ValueError as e:
    check("invalid order errors", "Rotate Order" in str(e))

box = build.box()
st = deform.soft_transform(box, "*", rotate=(30, 40, 50), use_group_center=False,
                           normals="none")                 # group = all, weights all 1
tr = ops.transform(box, rotate=(30, 40, 50))
check("Soft Transform (weights all 1) uses the same convention as Transform",
      np.allclose(st.get(POINT, "P"), tr.get(POINT, "P"), atol=1e-5))
cx = copyxform.copy_and_transform(box, copies=2, rotate=(30, 40, 50))
n = box.npoints
check("Copy and Transform's first copy uses the same convention as Transform",
      np.allclose(cx.get(POINT, "P")[n:2 * n], tr.get(POINT, "P"), atol=1e-5))
Rinst = ops.euler_matrix(30, 40, 50)[None].astype(np.float64)
from comfyui_pcg.geo import instances as INS            # noqa: E402
check("ExportInstances' Euler angles (R = Rz·Ry·Rx) invert back to the same angles",
      np.allclose(INS.euler_xyz(Rinst)[0], (30, 40, 50), atol=1e-4),
      INS.euler_xyz(Rinst)[0])

# ═══════════════════════════════════════════════════════════ Section toggles
sec("Section toggles: every parameter in the signature is read; off = that section uses defaults")
import ast, inspect, textwrap                            # noqa: E401,E402


def unused_params(cls):
    fn = getattr(cls, cls.FUNCTION)
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return []
    f = ast.parse(src).body[0]
    params = [a.arg for a in f.args.args + f.args.kwonlyargs][1:]
    body = ast.Module(body=f.body, type_ignores=[])
    used = {x.id for x in ast.walk(body) if isinstance(x, ast.Name)}
    it = cls.INPUT_TYPES()
    widgets = {**it.get("required", {}), **it.get("optional", {})}
    return [p for p in params if p in widgets and p not in used]


# FileCache.reload is only used by IS_CHANGED (changing the number re-reads from disk); run() never looks at it
ALLOW = {("PCG_FileCache", "reload")}
dead = [(nid, p) for nid, cls in M.items() for p in unused_params(cls)
        if (nid, p) not in ALLOW]
check("all nodes: widgets in the run() signature are all read in the function body", not dead, dead)


class _Probe:
    """Counter-proof: the check itself catches dead parameters."""
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"a": ("INT", {}), "use_b": ("BOOLEAN", {})}}

    def run(self, a, use_b):
        return (a,)


check("  counter-proof: a node deliberately not reading use_b is caught", unused_params(_Probe) == ["use_b"])

d = _sec_defaults(M["PCG_PolyExtrude"], "use_output")
check("_sec_defaults: defaults of the other parameters in the section, excluding the toggle itself",
      d.get("output_front") is True and d.get("output_back") is False
      and d.get("front_group") == "extrudeFront" and "use_output" not in d
      and "distance" not in d, d)
check("  combos take the first item", _sec_defaults(M["PCG_GroupCreate"], "use_edges")
      ["edge_combine"] == "include")

grid = build.grid(2, 2, 3, 3)
pe_on = run("PCG_PolyExtrude", geo=grid, output_back=True, back_group="bb",
            front_group="ff")
pe_off = run("PCG_PolyExtrude", geo=grid, output_back=True, back_group="bb",
             front_group="ff", use_output=False)
pe_def = run("PCG_PolyExtrude", geo=grid)
check("PolyExtrude: with Output on, Output Back / group names take effect",
      pe_on.nprims == pe_def.nprims + grid.nprims
      and pe_on.get_group(PRIM, "ff") is not None)
check("  Output off = defaults (same as changing nothing)",
      pe_off.nprims == pe_def.nprims and pe_off.get_group(PRIM, "ff") is None
      and pe_off.get_group(PRIM, "extrudeFront") is not None)

crv = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 1, 0], [3, 0, 0]],
                                  np.float32), [[0, 1, 2, 3]], closed=False)
nb = run("PCG_Convert", geo=crv, convert_to="nurbs_curve")
c_on = run("PCG_Convert", geo=nb, convert_to="polylines", u_divs=5)
c_off = run("PCG_Convert", geo=nb, convert_to="polylines", u_divs=5,
            use_tessellation=False)
c_def = run("PCG_Convert", geo=nb, convert_to="polylines")
check("Convert: with Tessellation on Divisions takes effect, off = default 16",
      c_on.npoints != c_def.npoints and c_off.npoints == c_def.npoints,
      (c_on.npoints, c_off.npoints, c_def.npoints))
o2 = run("PCG_Convert", geo=crv, convert_to="nurbs_curve", u_order=2)
o2_off = run("PCG_Convert", geo=crv, convert_to="nurbs_curve", u_order=2,
             use_nurbs_opts=False)
o_def = run("PCG_Convert", geo=crv, convert_to="nurbs_curve")
same = lambda a, b: (a.npoints == b.npoints and a.nprims == b.nprims and  # noqa: E731
                     np.allclose(a.get(POINT, "P"), b.get(POINT, "P")) and
                     sorted(a.attribs[PRIM]) == sorted(b.attribs[PRIM]) and all(
                         np.array_equal(np.asarray(a.attribs[PRIM][k]),
                                        np.asarray(b.attribs[PRIM][k]))
                         for k in a.attribs[PRIM]))
check("  NURBS section off = default order", same(o2_off, o_def) and not same(o2, o_def))
line = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]],
                                   np.float32), [[0, 1, 2, 3]], closed=False)
k_on = run("PCG_Carve", geo=line, keep_inside=False, keep_outside=True,
           use_second_u=True)
k_off = run("PCG_Carve", geo=line, keep_inside=False, keep_outside=True,
            use_second_u=True, use_keep=False)
k_def = run("PCG_Carve", geo=line, use_second_u=True)
check("Carve: Keep section off = default (keep only the middle part)",
      same(k_off, k_def) and not same(k_on, k_def), (k_on.nprims, k_def.nprims))

# ═══════════════════════════════════════════════════════════ Boolean
sec("Boolean face groups: per face, by Houdini's definition")
# B is one size smaller than A in yz: no coplanar faces between them (who gets a coplanar patch is decided by manifold and can't be computed by hand)
A = build.box()                                           # [-.5,.5]³, area 6
B = build.box(size=(1, 0.5, 0.5), center=(0.5, 0, 0))    # [0,1]×[-.25,.25]², area 2.5
NAMES = dict(a_inside_b="ainsideb", a_outside_b="aoutsideb",
             b_inside_a="binsidea", b_outside_a="boutsidea", b_polys="bpolys")


def garea(g, name):
    m = g.get_group(PRIM, name)
    return 0.0 if m is None else float(prim_areas(g)[np.asarray(m, bool)].sum())


def bool_areas(op, direction="a-b", detri=False):
    g = run("PCG_Boolean", a=A, b=B, operation=op, direction=direction,
            use_out_groups=True, detriangulate=detri)
    return g, {k: round(garea(g, v), 6) for k, v in NAMES.items()}


# By hand: B pokes out through A's x = 0.5 face. A inside B = a 0.5×0.5 patch on that face (0.25),
# A outside B = 6 − 0.25; B inside A = the four side strips for x∈[0,0.5] (4×0.25) + the end face at x=0 (0.25),
# B outside A likewise = 1.25
EXPECT = {
    "union": dict(a_inside_b=0, a_outside_b=5.75, b_inside_a=0, b_outside_a=1.25,
                  b_polys=1.25),
    "intersect": dict(a_inside_b=0.25, a_outside_b=0, b_inside_a=1.25, b_outside_a=0,
                      b_polys=1.25),
    "subtract": dict(a_inside_b=0, a_outside_b=5.75, b_inside_a=1.25, b_outside_a=0,
                     b_polys=1.25),
}
for op, want in EXPECT.items():
    g, got = bool_areas(op)
    check(f"{op}: areas of the four face groups match hand calculation", got == {k: float(v) for k, v in want.items()},
          got)
    tot = float(prim_areas(g).sum())
    check(f"  {op}: A's two groups + B's two groups = all faces (no overlap, nothing missing)", abs(
        got["a_inside_b"] + got["a_outside_b"] + got["b_inside_a"] + got["b_outside_a"]
        - tot) < 1e-6)
g, got = bool_areas("subtract", "b-a")
check("B − A: A Inside B = the cut (0.25), B Outside A = 1.25",
      got["a_inside_b"] == 0.25 and got["b_outside_a"] == 1.25 and got["a_outside_b"] == 0,
      got)
gq, gotq = bool_areas("union", detri=True)
check("after Detriangulate the face groups are kept and areas unchanged (triangles from A and B are not merged into one quad)",
      gotq == {k: float(v) for k, v in EXPECT["union"].items()}
      and gq.nprims < bool_areas("union")[0].nprims, (gotq, gq.nprims))
# Same size, offset by half a cell: the two boxes have coplanar adjacent faces (a patch of A and a patch of B in the same plane).
# Who gets the coplanar patch can't be computed by hand, but each group's area must be the same before and after Detriangulate -- without
# looking at the source, one triangle each from A and B would get merged into a quad and the group areas would shift
B2 = ops.transform(build.box(), translate=(0.5, 0, 0))
ga = {k: [garea(run("PCG_Boolean", a=A, b=B2, operation="union", use_out_groups=True,
                    detriangulate=d), v) for d in (False, True)] for k, v in NAMES.items()}
check("  coplanar adjacent A / B faces: each group's area unchanged before and after Detriangulate",
      all(abs(x - y) < 1e-6 for x, y in ga.values()), ga)
g_old_style = run("PCG_Boolean", a=A, b=B, operation="union", use_out_groups=True)
check("  negative control: before pcg85 the whole Union result went into aoutsideb (area 7), now only A's 5.75",
      abs(garea(g_old_style, "aoutsideb") - 5.75) < 1e-6
      and abs(float(prim_areas(g_old_style).sum()) - 7.0) < 1e-6)
sh = run("PCG_Boolean", a=A, b=B, operation="shatter")
cls_ = np.asarray(TP.connectivity(sh, PRIM).get(PRIM, "class")).reshape(-1)
check("Shatter: three mutually disconnected pieces (distinguished by Connectivity, as in Houdini)",
      len(np.unique(cls_)) == 3)
check("  Output Groups off: no face groups written (before pcg85 Shatter always wrote them)",
      not any(sh.get_group(PRIM, v) is not None for v in NAMES.values()))
sd = run("PCG_Boolean", a=A, b=B, operation="subtract", use_out_groups=False)
check("  other operations off: nothing written either", not sd.groups[PRIM])

# ═══════════════════════════════════════════════════════════ Group Create
sec("Group Create: Include by Edges is a union")
bx = build.box()
opn = ops.delete_prims(bx, np.array([True] * 5 + [False]))  # open box, 5 faces
hole = set(bx.prim_points(5).tolist())                       # the four points of the deleted face
share = np.array([len(hole & set(opn.prim_points(i).tolist()))
                  for i in range(opn.nprims)])
rim = share >= 2                                             # the 4 side faces next to the opening
bottom = int(np.nonzero(share == 0)[0][0])                   # the one opposite the opening


def gc(**kw):
    g = run("PCG_GroupCreate", geo=kw.pop("geo", opn), cls="prim", **kw)
    return np.asarray(g.get_group(PRIM, "group1"), bool)


check("open box: only Unshared on, angle off -> only the 4 side faces next to the opening (starting from the empty set)",
      np.array_equal(gc(use_edges=True, unshared=True, use_angle=False), rim),
      gc(use_edges=True, unshared=True, use_angle=False))
check("  Unshared + angle (90° edges) select independently and are unioned -> all 5 faces in",
      gc(use_edges=True, unshared=True).all())
flat = build.grid(2, 2, 4, 4)
fb = gc(geo=flat, use_edges=True, unshared=True)
check("  flat grid: Unshared selects only the 8 outer cells, not all (negative control: before, with Unshared on the angle was ignored; "
      "a flat grid has no angles, so both semantics give the same result -- the difference is in the previous check)",
      fb.sum() == 8 and not fb.all(), fb.sum())
b0 = gc(base="%d" % bottom, use_edges=True, unshared=True, use_angle=False)
check("Include: Base ∪ edges (bottom + four sides)", b0.all())
b0k = gc(base="%d" % bottom, use_edges=True, unshared=True, use_angle=False,
         edge_combine="keep")
check("  Keep (extra in this plugin): Base ∩ edges = empty (the bottom doesn't touch the opening)", not b0k.any())
rr = gc(use_random=True, percent=0.0, use_edges=True, unshared=True,
        use_angle=False)
check("Random doesn't filter out what Include by Edges selected (Houdini: it goes into the group regardless of other tabs)",
      np.array_equal(rr, rim))
check("  only Random, no edges: 0% is empty", not gc(use_random=True, percent=0.0).any())
check("  Random is a Keep tab: at 100% it starts from everything, then unioned with edges = everything",
      gc(use_random=True, percent=100.0, use_edges=True, unshared=True,
         use_angle=False).all())
quad = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]],
                                   np.float32), [[0, 1, 2, 3]])
check("the angle rule doesn't select boundary edges (no second adjacent face, so no angle): an isolated quad with Min = 0 stays out of the group",
      not gc(geo=quad, use_edges=True, min_angle=0.0).any())
check("nothing on = everything (empty Base means no restriction)", gc().all())

# ═══════════════════════════════════════════════════════════ Extract Centroid
sec("Extract Centroid")
two = ops.merge(build.box(), ops.transform(build.box(), translate=(10, 0, 0)))
half = np.zeros(two.nprims, bool); half[6:] = True
two.set_group(PRIM, "right", half)
cd = centroid.extract_centroid(two, "detail", group="right")
check("detail mode respects group: only the right box counted -> (10,0,0)",
      np.allclose(cd.get(POINT, "P")[0], (10, 0, 0), atol=1e-5), cd.get(POINT, "P"))
cd_all = centroid.extract_centroid(two, "detail")
check("  negative control: without group it's the midpoint of the two boxes (5,0,0)",
      np.allclose(cd_all.get(POINT, "P")[0], (5, 0, 0), atol=1e-5))
two.set_group(PRIM, "none", np.zeros(two.nprims, bool))
check("  empty group selection -> no points", centroid.extract_centroid(
    two, "detail", group="none").npoints == 0)
pts = Geometry.from_points(np.array([[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0],
                                     [4, 0, 0]], np.float32))
pts.set_string(POINT, "name", np.array(["a"] * 4))
bb = centroid.extract_centroid(pts, "pieces", "name", "points", "bounding_box")
av = centroid.extract_centroid(pts, "pieces", "name", "points", "average_position")
check("splitting by points: Bounding Box = bounding box center 2.0, not the point average 1.075",
      np.isclose(bb.get(POINT, "P")[0, 0], 2.0) and
      np.isclose(av.get(POINT, "P")[0, 0], 1.075), (bb.get(POINT, "P")[0], av.get(POINT, "P")[0]))
ea = run("PCG_ExtractCentroid", geo=two, run_over="connectivity", output="attribute")
ea_off = run("PCG_ExtractCentroid", geo=two, run_over="connectivity",
             output="attribute", use_attrib_out=False)
check("Centroid Attribute on writes centroid, off writes nothing",
      ea.get(PRIM, "centroid") is not None and ea_off.get(PRIM, "centroid") is None)

# ═══════════════════════════════════════════════════════════ Scatter
sec("Scatter: Use Geometric Normals doesn't depend on Relax")
gN = build.grid(2, 2, 3, 3)
gN.set(POINT, "N", np.tile(np.float32([1, 0, 0]), (gN.npoints, 1)), owned=True)
s_i = run("PCG_Scatter", geo=gN, count=50)
s_g = run("PCG_Scatter", geo=gN, count=50, use_geometric_normals=True)
gn = np.abs(s_g.get(POINT, "N"))
check("Relax off: off = N of the interpolation source (+x), on = geometric face normal (±y)",
      np.allclose(s_i.get(POINT, "N"), (1, 0, 0), atol=1e-6)
      and np.allclose(gn, (0, 1, 0), atol=1e-6))

# ═══════════════════════════════════════════════════════════ COP Light
sec("COP Light: point light + shadows")
Wd, Hd = 16, 16
img = CopImage(Wd, Hd, {"N": np.dstack([np.zeros((Hd, Wd, 2)), np.ones((Hd, Wd, 1))]),
                        "h": np.zeros((Hd, Wd, 1))})
try:
    out = run("PCG_COPLight", cop=img, light_type="point", shadows=True,
              height_layer="h")
    check("point light + Shadows + Height Layer no longer errors; on flat ground same as without shadows",
          np.allclose(out.need("lit"),
                      run("PCG_COPLight", cop=img, light_type="point",
                          height_layer="h").need("lit")))
except Exception as e:                                    # noqa: BLE001
    check("point light + Shadows + Height Layer no longer errors", False, repr(e))

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
