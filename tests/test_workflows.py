"""
Example workflows (pcg83): rock garden / city block (pure SOP), brick wall PBR / full terrain texture set (pure COP),
plus the four bugs found while building them.

Bugs (references are all hand-computed, not relying on the implementation itself):
  Wrangle broadcast  {1,0,0} * @P.y per row = (y, 0, 0); @pscale * @P.x is (N,1), not N×N;
                  lerp(vector, vector, @P.x); @P.y -= @h (@h is (N,1)); where(per-element condition, vector, vector);
                  getbbox_size() * @P.x; 1-D vector + 1-D vector still per component (not mistakenly turned into a column)
                  negative control: the same arrays handed straight to numpy, (N,1) × (N,) is N×N
  constant assignment  @Cd = set(1,0,0) with a group: unselected ones restored to 0, selected ones get the constant (it used to blow up on (1,3))
  prim @P          = face center (vertex average), and no prim attribute called P is written out of thin air
  Poly Extrude     prim attributes carried onto front / back / side walls (side walls take the face owning that edge); vertex attributes per vertex on the front,
                  reversed on the back, side walls take the edge's two ends; detail attributes unchanged; faces not extruded untouched
Workflows:
  all six generated, UI format self-check, regenerating is byte-identical, layout without overlap, the four new ones actually run, then a few checks each
  of properties that only hold "when done right" (no big rocks in the stream, the 81 buildings' lot still there after extrusion, brick wall seamless across edges,
  the five splat layers sum to 1 everywhere ...)
"""
import os
import sys
import tempfile
import time

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import wrangle as WR               # noqa: E402
from comfyui_pcg.geo.groups import resolve              # noqa: E402
from comfyui_pcg.geo.cop import CopImage                # noqa: E402
from comfyui_pcg.geo.cop.pixel import getn, put, wrangle as cop_wrangle  # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM, VERTEX, DETAIL  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402
import make_workflows as MW                             # noqa: E402

try:
    import torch
except ImportError:                                     # pragma: no cover
    torch = None

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def A(g, name, cls=POINT):
    return np.asarray(g.get(cls, name), np.float64)


def W(g, code, cls=POINT, group=None):
    return WR.run_wrangle(g, code, cls, group=group)


# ═══════════════════════════════════════════════════ 1. Wrangle broadcast
sec("Wrangle: per-element scalar × vector")
g = build.grid(4.0, 4.0, 3, 3)                          # 9 points, which collides with the component count 3
g.set(POINT, "h", np.arange(9, dtype=np.float32)[:, None] * 0.5)
P = A(g, "P")
h = A(g, "h")[:, 0]

r = W(g, "@Cd = set(1, 0, 0) * @P.x")
check("{1,0,0} * @P.x -> per row (x, 0, 0)",
      np.allclose(A(r, "Cd"), np.stack([P[:, 0], 0 * P[:, 0], 0 * P[:, 0]], 1)))
r = W(g, "@a = @h * @P.x")
check("@h * @P.x is (N,1) = h·x (not 9×9)",
      A(r, "a").shape == (9, 1) and np.allclose(A(r, "a")[:, 0], h * P[:, 0]))
r = W(g, "@Cd = lerp(set(1, 0, 0), set(0, 0, 1), @h / 4)")
t = h / 4
check("lerp(vector, vector, per-element t)",
      np.allclose(A(r, "Cd"), np.stack([1 - t, 0 * t, t], 1)))
r = W(g, "@P.y -= @h")
check("@P.y -= @h (right side (N,1), left side a 1-D slice)", np.allclose(A(r, "P")[:, 1], P[:, 1] - h)
      and np.allclose(A(r, "P")[:, [0, 2]], P[:, [0, 2]]))
r = W(g, "@P.y = @h * 2")
check("@P.y = @h * 2 (same for assignment)", np.allclose(A(r, "P")[:, 1], 2 * h))
r = W(g, "@Cd = where(@P.x > 0, set(1, 0, 0), set(0, 0, 1))")
exp = np.where((P[:, 0] > 0)[:, None], [1.0, 0, 0], [0, 0, 1.0])
check("where(per-element condition, vector, vector) picks per row", np.allclose(A(r, "Cd"), exp))
r = W(g, "@q = getbbox_size() * @P.x")
check("getbbox_size() * @P.x → (N,3)",
      np.allclose(A(r, "q"), np.outer(P[:, 0], [4.0, 0.0, 4.0])))
r = W(g, "@q = getbbox_max() - getbbox_min() + point('P', 0)")
check("between 1-D vectors still per component (not mistaken for a per-element scalar)",
      np.allclose(A(r, "q"), np.tile(np.array([4.0, 0, 4.0]) + P[0], (9, 1))))
r = W(g, "@q = (getbbox_size() * 2).x + @P.x * 0")
check("a 1-D vector is still a vector after computing: (getbbox_size() * 2).x", np.allclose(A(r, "q"), 8.0))
r = W(g, "@d = dot(@P, set(1, 0, 0)) * @h")
check("dot(...) * @h", np.allclose(A(r, "d")[:, 0], P[:, 0] * h))
r = W(g, "@Cd = (@P * 2) * rand(@ptnum)")
rp = WR._hash01(np.arange(9), 0)
check("a computed (N,3) is still a Vec: (@P * 2) * rand(@ptnum)",
      np.allclose(A(r, "Cd"), 2 * P * np.asarray(rp).reshape(-1, 1)))
r = W(g, "@a = smoothstep(0, 4, @h) * rand(@ptnum)")
sm = np.clip(h / 4, 0, 1)
check("smoothstep keeps the (N,1) type: multiplied by a per-element scalar it is still (N,1)",
      A(r, "a").shape == (9, 1)
      and np.allclose(A(r, "a")[:, 0], sm * sm * (3 - 2 * sm) * np.asarray(rp).ravel()))
g2 = g.copy()
g2.set(POINT, "k", np.full((9, 1), 0.25, np.float32))
r = WR.run_wrangle(g2, "@h -= @k", POINT, squeeze=("h",))
check("a flattened single-component attribute (@value of a volume Wrangle) subtracts (N,1) in place",
      np.allclose(A(r, "h")[:, 0], h - 0.25))
r = W(g, "@P = @P * @h")
check("@P * @h (already correct before, must not break)", np.allclose(A(r, "P"), P * h[:, None]))
check("  negative control: the same arrays handed straight to numpy, (N,1) × (N,) broadcasts to N×N",
      (h[:, None] * P[:, 0]).shape == (9, 9))

sec("Wrangle: constant assignment / prim @P")
r = W(g, "@Cd = set(0.2, 0.4, 0.6)", group="0-3")
cd = A(r, "Cd")
check("@Cd = set(...) with a group: selected ones get the constant, unselected restored to 0",
      np.allclose(cd[:4], [0.2, 0.4, 0.6]) and np.allclose(cd[4:], 0))
r = W(g, "@Cd = set(0.2, 0.4, 0.6)")
check("without a group it fills every point", A(r, "Cd").shape == (9, 3)
      and np.allclose(A(r, "Cd"), [0.2, 0.4, 0.6]))
r = W(g, "@cx = @P.x\n@cz = @P.z", cls=PRIM)
ctr = ops.prim_centers(g)
check("in prim context @P = face center (vertex average)",
      np.allclose(A(r, "cx", PRIM)[:, 0], ctr[:, 0])
      and np.allclose(A(r, "cz", PRIM)[:, 0], ctr[:, 2])
      and len(np.unique(ctr[:, 0])) == 2)
check("  read-only: no prim attribute called P is written out of thin air", r.get(PRIM, "P") is None)

sec("COP Wrangle")
img = CopImage(4, 3)
put(img, "C", np.zeros((3, 4, 1)))
o = cop_wrangle(img, "@C = set(1, 0.5, 0) * @u")
u = (np.arange(4) + 0.5) / 4
c = getn(o, "C")
check("@C = vector * @u", c.shape == (3, 4, 3)
      and np.allclose(c[..., 0], np.tile(u, (3, 1)))
      and np.allclose(c[..., 1], 0.5 * np.tile(u, (3, 1))))
o = cop_wrangle(img, "@m = set(0.1, 0.2, 0.3)")
check("@m = constant vector fills the whole image", np.allclose(getn(o, "m"), [0.1, 0.2, 0.3]))
put(img, "h", np.arange(12, dtype=np.float64).reshape(3, 4, 1))
o = cop_wrangle(img, "@k = @h * @u\n@k = @h * @u")      # the second read of @h goes through the cache
check("single-channel layer × @u is (pixels, 1)", getn(o, "k").shape == (3, 4, 1)
      and np.allclose(getn(o, "k")[..., 0],
                      np.arange(12).reshape(3, 4) * np.tile(u, (3, 1))))

# ═══════════════════════════════════════════════════ 2. Poly Extrude carries attributes
sec("Poly Extrude: prim / vertex / detail attributes follow their source")
g = build.grid(2.0, 2.0, 3, 3)                          # 4 faces
g.set(PRIM, "h", np.array([[1.0], [2.0], [3.0], [4.0]], np.float32))
nv = g.nvertices
g.set(VERTEX, "vid", np.arange(nv, dtype=np.float32)[:, None])
g.set(DETAIL, "tag", np.array([[7.0]], np.float32))
e = ops.polyextrude(g, group="1 2", distance=1.0, divide_into="individual",
                    output_back=True)
kind = np.full(e.nprims, -1)
for nm, k in (("extrudeFront", 0), ("extrudeBack", 1), ("extrudeSide", 2)):
    kind[resolve(e, PRIM, nm)] = k
hh = A(e, "h", PRIM)[:, 0]
check("faces not extruded (0, 3) keep h unchanged", sorted(hh[kind == -1].tolist()) == [1.0, 4.0])
check("front / back faces inherit h from the extruded face", sorted(hh[kind == 0].tolist()) == [2.0, 3.0]
      and sorted(hh[kind == 1].tolist()) == [2.0, 3.0])
side_h = hh[kind == 2]
check("every side wall face carries h too (4 + 4 edges, individual mode)",
      len(side_h) == 8 and sorted(side_h.tolist()) == [2.0] * 4 + [3.0] * 4)
vid = A(e, "vid", VERTEX)[:, 0]
po = e.prim_offset
fr = [i for i in range(e.nprims) if kind[i] == 0]
bk = [i for i in range(e.nprims) if kind[i] == 1]
src_front = [vid[po[i]:po[i + 1]].tolist() for i in fr]
g_po = g.prim_offset
want = [list(range(g_po[i], g_po[i + 1])) for i in (1, 2)]
check("front vertex attributes correspond vertex by vertex", sorted(src_front) == sorted(want))
check("back faces reversed", sorted(vid[po[i]:po[i + 1]].tolist() for i in bk)
      == sorted(w[::-1] for w in want))
sd = [vid[po[i]:po[i + 1]] for i in range(e.nprims) if kind[i] == 2]
check("side walls take the vertices at both ends of that edge (a, b, b, a)",
      all(s[0] == s[3] and s[1] == s[2] and s[0] != s[1] for s in sd))
check("detail attributes unchanged", np.allclose(A(e, "tag", DETAIL), 7.0))
e2 = ops.polyextrude(g, group="1", distance=1.0, dist_attrib="h")
top = A(e2, "P")[e2.prim_points(int(np.nonzero(resolve(e2, PRIM, "extrudeFront"))[0][0]))]
check("  Local Control reads prim h: face 1 extruded height 2", np.allclose(np.abs(top[:, 1]), 2.0))

sec("Poly Extrude: Limit Insetting (uncovered by the row of thin window panes on the city block rooftops)")
# two faces: left x ∈ [-1, 0] (1×1), right x ∈ [0, 3] (3×1). inset 5 far exceeds both limits
# (both half the short side = 0.5)
g = build.grid(2.0, 1.0, 3, 2)
Pg = A(g, "P")
Pg[Pg[:, 0] > 0.5, 0] = 3.0                                 # move the rightmost column of points to x = 3
g.set(POINT, "P", Pg.astype(np.float32))


def fronts(e):
    fm = resolve(e, PRIM, "extrudeFront")
    Pe = A(e, "P")
    out = {}
    for i in np.nonzero(fm)[0]:
        q = Pe[e.prim_points(i)]
        out["L" if q[:, 0].mean() < 0 else "R"] = q
    return out


e = ops.polyextrude(g, distance=0.0, inset=5.0, divide_into="individual",
                    limit_inset=True)
f = fronts(e)
wL = np.ptp(f["L"][:, 0]) + np.ptp(f["L"][:, 2])
wR = np.ptp(f["R"][:, 0])
check("clamped before the edges flip: the left face shrinks to a point, the right one to a segment of length 2 (3 - 2×0.5)",
      wL < 0.01 and abs(wR - 2.0) < 0.01, (round(wL, 4), round(wR, 4)))
inside = (f["R"][:, 0].min() > 0.0 - 1e-6 and f["R"][:, 0].max() < 3.0 + 1e-6
          and f["L"][:, 0].min() > -1.0 - 1e-6 and f["L"][:, 0].max() < 0.0 + 1e-6)
check("  front points all stay within their own face", inside)
e = ops.polyextrude(g, distance=0.0, inset=5.0, divide_into="individual")
f = fronts(e)
check("  negative control: without the limit points run outside the face", f["L"][:, 0].max() > 1.0)
g3 = build.grid(3.0, 1.0, 4, 2)                            # 3 faces; point numbers and new point numbers are offset
e = ops.polyextrude(g3, group="1 2", distance=0.0, inset=5.0,
                    divide_into="individual", limit_inset=True)
fm = resolve(e, PRIM, "extrudeFront")
Pe = A(e, "P")
spans = [np.ptp(Pe[e.prim_points(i)][:, 0]) for i in np.nonzero(fm)[0]]
check("  extruding only the last two faces (new point numbers ≠ original point numbers) also clamps by each face's own edge lengths (used to go out of bounds / measure the wrong edge)",
      len(spans) == 2 and max(spans) < 0.01, [round(x, 4) for x in spans])

# ═══════════════════════════════════════════════════ 3. Workflows: generation + self-check
sec("Example workflows: generation + UI self-check")
tmpd = tempfile.mkdtemp(prefix="pcg_wf_")
tmpd2 = tempfile.mkdtemp(prefix="pcg_wf_")
paths = MW.main(tmpd)
paths2 = MW.main(tmpd2)
check(f"all {len(paths)} workflows generated, regenerating is byte-identical",
      len(paths) == len(MW.WORKFLOWS) == 16 and all(open(a, "rb").read() == open(b, "rb").read()
                              for a, b in zip(paths, paths2)))
import json                                              # noqa: E402
wfs = {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8"))
       for p in paths}
for name, wf in wfs.items():
    pr = MW.validate_ui(wf)
    check(f"{name}: widgets, combos and links all correct ({len(wf['nodes'])} nodes / "
          f"{len(wf['links'])} links)", not pr, "; ".join(pr[:3]))
    rects = [(n["pos"][0], n["pos"][1], n["pos"][0] + n["size"][0],
              n["pos"][1] + n["size"][1], n["id"]) for n in wf["nodes"]]
    ov = [(a[4], b[4]) for i, a in enumerate(rects) for b in rects[i + 1:]
          if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]]
    check("  nodes do not overlap (height estimated from the frontend's collapsed sections + COP thumbnails)", not ov, ov[:4])
    miss = [n["type"] for n in wf["nodes"] if n["type"].startswith("PCG_")
            and n["type"] not in MAP]
    check("  all PCG nodes registered", not miss, miss)

# value ranges: the frontend validates INPUT_TYPES min / max on submit, the executor does not, so the self-check must
gb = MW.Graph()
gb.add("PCG_Tube", (0, 0), title="bad", rows=1)
gb.add("PCG_Tube", (0, 400), title="good", rows=2)
prb = MW.validate_ui(gb.to_ui())
check("UI self-check checks value ranges: Tube rows = 1 (minimum 2) is reported, rows = 2 is not",
      prb == ["bad.rows = 1 below minimum 2"], prb)
gc2 = MW.Graph()
gc2.add("PCG_Tube", (0, 0), title="too big", cols=10 ** 9)
check("  above the maximum is reported too", any("above maximum" in x for x in MW.validate_ui(gc2.to_ui())),
      MW.validate_ui(gc2.to_ui()))

# est_height rules (since pcg84 PCG nodes are estimated from the parameter panel, see panel.py): rows that follow a mode on the panel
# (hidewhen) are counted by the current value; COP nodes add a thumbnail about as tall as the width; non-PCG nodes still count native widgets
from comfyui_pcg.panel import H as PH                   # noqa: E402
gg = MW.Graph()
n1 = gg.add("PCG_Color", (0, 0))
n2 = gg.add("PCG_Color", (0, 0), mode="ramp_by_attribute")
n3 = gg.add("PCG_COPBlur", (0, 0))
h1, h2 = MW.est_height(n1, 340), MW.est_height(n2, 340)
# constant -> ramp_by_attribute: hides the Color row, shows the Attribute row (cancels out), adds a separator + Compute Range,
# Range, Attribute Ramp
check("layout height estimate (panel): Color switched to Ramp from Attribute adds a separator + two rows + a ramp",
      h2 - h1 == PH["sep"] + 2 * PH["row"] + PH["ramp"], (h1, h2))
check("  COP nodes add a thumbnail as tall as the width (panel at least 340, narrower counts as 340)",
      MW.est_height(n3, 520) - MW.est_height(n3, 340) == 180
      and MW.est_height(n3, 200) == MW.est_height(n3, 340))
n4 = gg.add("KSampler", (0, 0))
check("  non-PCG nodes still one row per widget", MW.est_height(n4, 340) ==
      34 + 22 * 4 + 25 * sum(1 for _, t, _ in n4["ins"] if MW.is_widget(t)))

# ═══════════════════════════════════════════════════ 4. Actually run
IMGS = []


class _Img:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}
    RETURN_TYPES = ()
    FUNCTION = "run"

    def run(self, images, filename_prefix=None):
        IMGS.append((filename_prefix, images))
        return ()


def run(name):
    api = MW.ui_to_api(wfs[name])
    classes = dict(MAP)
    classes["PreviewImage"] = _Img
    classes["SaveImage"] = _Img
    IMGS.clear()
    old = os.getcwd()
    os.chdir(tmpd)
    t0 = time.time()
    try:
        ex = fakecomfy.Executor(api, classes)
        res = {nid: ex.run(nid) for nid in api}
    finally:
        os.chdir(old)
    byt = {}
    for k, v in api.items():
        byt.setdefault(v["class_type"], []).append(k)
    return api, res, byt, time.time() - t0


def title_of(name, tt):
    return [str(n["id"]) for n in wfs[name]["nodes"] if n.get("title") == tt]


if torch is None or os.environ.get("PCG_TEST_QUICK"):
    print("  (no torch / PCG_TEST_QUICK, skipping execution)")
else:
    # ── rock garden
    sec("Rock garden")
    nm = "pcg_sop_rock_garden"
    api, res, byt, dt = run(nm)
    check(f"runs ({len(api)} nodes, {dt:.1f} s)", True)
    lib = res[title_of(nm, "Rock library (8 pieces)")[0]][0]
    cls_ = A(lib, "class", PRIM)[:, 0].astype(int)
    check("For-Each produced 8 rocks, class = 0..7", sorted(set(cls_)) == list(range(8)))
    Pl = A(lib, "P")
    lows, shapes = [], []
    for k in range(8):
        pts = np.unique(np.concatenate([lib.prim_points(i)
                                        for i in np.nonzero(cls_ == k)[0]]))
        q = Pl[pts]
        lows.append(q[:, 1].min())
        shapes.append(np.round(q.max(0) - q.min(0), 4).tolist())
    check("  every rock's bottom is at y = -0.15 (Match Size puts it on the ground, then buries it a bit)",
          np.allclose(lows, -0.15, atol=1e-4))
    check("  the 8 shapes differ pairwise (rand_seed really is wired to iteration)",
          len({tuple(s) for s in shapes}) == 8)
    pts = res[title_of(nm, "Pick a random piece")[0]][0]
    Pb = A(pts, "P")
    dstream = np.abs(Pb[:, 2] - 5 * np.sin(Pb[:, 0] * 0.16) - 2)
    check("big rocks all at distance ≥ 2 from the stream (the boulder weight is multiplied by smoothstep(3, 4.5, d), "
          "face averaging leaks inwards a little)", dstream.min() > 2.0, round(float(dstream.min()), 2))
    peb = res[title_of(nm, "Pick a random piece")[1]][0]
    Pp = A(peb, "P")
    dp = np.abs(Pp[:, 2] - 5 * np.sin(Pp[:, 0] * 0.16) - 2)
    check("pebbles all along the stream banks (d < 4)", dp.max() < 4.0, round(float(dp.max()), 2))
    rocks = res[title_of(nm, "All rocks")[0]][0]
    n_expect = sum(int((cls_ == c).sum()) for c in
                   A(pts, "class")[:, 0].astype(int)) + \
        sum(int((A(res[title_of(nm, "Low-poly library (for pebbles)")[0]][0], "class", PRIM)[:, 0]
                 .astype(int) == c).sum()) for c in A(peb, "class")[:, 0].astype(int))
    check("Copy to Points picks pieces by class: face count = Σ faces of the piece each point picks",
          rocks.nprims == n_expect, (rocks.nprims, n_expect))
    ter = res[title_of(nm, "Colour + scatter weights")[0]][0]
    Pt, Ct = A(ter, "P"), A(ter, "Cd")
    dt_ = A(ter, "dstream")[:, 0]
    check("the stream is water-coloured (points with d < 0.7 are bluer than red)", np.all(Ct[dt_ < 0.7, 2] > Ct[dt_ < 0.7, 0]))
    img = IMGS[0][1]
    check("the preview image came out, not empty", tuple(img.shape) == (1, 1066, 1600, 3)
          and float(img.std()) > 0.05)

    # ── city block
    sec("City block")
    nm = "pcg_sop_city_block"
    api, res, byt, dt = run(nm)
    check(f"runs ({len(api)} nodes, {dt:.1f} s)", True)
    lots = res[title_of(nm, "Per lot: height / crown / number")[0]][0]
    H = A(lots, "height", PRIM)[:, 0]
    NL = 81
    check(f"{NL} lots", lots.nprims == NL)
    fin = res[title_of(nm, "Sidewalk")[0]][0]
    lot = A(fin, "lot", PRIM)[:, 0].astype(int)
    check("lot still on every face after 7 extrusions (Poly Extrude carries prim attributes)",
          sorted(set(lot)) == list(range(NL)) and fin.nprims > 10000, fin.nprims)
    Pf = A(fin, "P")
    ok_h = []
    for k in range(NL):
        top = max(Pf[fin.prim_points(i)][:, 1].max() for i in np.nonzero(lot == k)[0])
        want = H[k] * (1.35 if H[k] > 28 else 1.0)
        ok_h.append(abs(top - want) < 1e-3)
    check("each building's highest point = height (tall buildings add a crown of 0.35 × height)", all(ok_h),
          int(sum(ok_h)))
    glass = resolve(fin, PRIM, "glass")
    lit = A(fin, "Cd", PRIM)[glass, 0] > 0.9
    check("about 12% of windows lit", 0.07 < lit.mean() < 0.18, round(float(lit.mean()), 3))
    trees = res[byt["PCG_AttribRandomize"][0]][0]
    Pt = A(trees, "P")
    cell = 12.0
    fx = np.abs(((Pt[:, 0] + 54) % cell) - cell / 2)
    fz = np.abs(((Pt[:, 2] + 54) % cell) - cell / 2)
    inner = cell / 2 - 1.4 - 0.9
    check("street trees all on the sidewalks (not in building footprints, not on the road)",
          np.all(np.maximum(fx, fz) >= inner - 1e-3)
          and np.all(np.maximum(fx, fz) <= cell / 2 - 1.4 + 1e-3))
    mg = res[title_of(nm, "Everything")[0]][0]
    check("after merging Cd is all on prims (not half point colour, half face colour)",
          mg.get(PRIM, "Cd") is not None and mg.get(POINT, "Cd") is None)

    # ── brick wall
    sec("Brick wall PBR")
    nm = "pcg_cop_brick_material"
    api, res, byt, dt = run(nm)
    check(f"runs ({len(api)} nodes, {dt:.1f} s)", True)
    lt = res[title_of(nm, "Light to check the look")[0]][0]
    names = [p for p, _ in IMGS]
    check("saved 5 textures + 1 preview",
          sorted(n for n in names if n) == sorted(
              f"pcg/brick_{k}" for k in ("albedo", "normal", "roughness",
                                         "height", "ao")) and len(names) == 6)
    hgt = getn(lt, "height")[..., 0]
    alb = getn(lt, "albedo")

    def seam(a):
        """Jump across the edges / mean jump between neighbouring columns inside the image: same magnitude when seamless."""
        inner = np.abs(np.diff(a, axis=1)).mean()
        edge = np.abs(a[:, 0] - a[:, -1]).mean()
        inner_v = np.abs(np.diff(a, axis=0)).mean()
        edge_v = np.abs(a[0] - a[-1]).mean()
        return edge / inner, edge_v / inner_v
    su, sv = seam(hgt)
    check("height seamless across left/right and top/bottom edges (jump of the same magnitude as neighbouring pixels inside)",
          su < 2.0 and sv < 2.0, (round(su, 2), round(sv, 2)))
    su, sv = seam(alb[..., 0])
    check("albedo equally seamless", su < 2.0 and sv < 2.0, (round(su, 2), round(sv, 2)))
    su0, _ = seam(hgt)
    su2, _ = seam(hgt[:, : hgt.shape[1] * 2 // 3])
    check("  negative control: cropping off 1/3 and measuring again (no longer a whole period), the edge jump is much larger", su2 > 3 * su0,
          (round(su0, 2), round(su2, 2)))
    Nn = getn(lt, "N")
    check("normals unit length, pointing outwards (z > 0)",
          np.allclose(np.linalg.norm(Nn, axis=-1), 1, atol=1e-4)
          and Nn[..., 2].min() > 0)
    rough = getn(lt, "roughness")[..., 0]
    brick = getn(lt, "brick")[..., 0]
    check("mortar is rougher than brick faces", rough[brick < 0.1].mean() > rough[brick > 0.9].mean() + 0.1)
    tl = res[title_of(nm, "2×2 seamless check")[0]][0]
    check("Tile 2×2 = 4096² (textures are 2048²)", (tl.xres, tl.yres) == (4096, 4096))

    # ── terrain
    sec("Full terrain texture set")
    nm = "pcg_cop_terrain_maps"
    api, res, byt, dt = run(nm)
    check(f"runs ({len(api)} nodes, {dt:.1f} s)", True)
    vis = res[title_of(nm, "Contour map")[0]][0]
    tot = sum(getn(vis, f"splat_{k}")[..., 0] for k in
              ("grass", "sediment", "rock", "snow", "water"))
    check("the five splat layers sum to 1 everywhere", np.allclose(tot, 1.0, atol=1e-5))
    hC = getn(vis, "C")[..., 0]
    snow = getn(vis, "splat_snow")[..., 0]
    check("snow up high (mean height of snowy pixels > the 90th percentile of the whole image)",
          hC[snow > 0.5].mean() > np.percentile(hC, 90))
    check("the mountain is in the middle (peak less than 1/4 of the width from the center)",
          np.hypot(*(np.array(np.unravel_index(hC.argmax(), hC.shape))
                     - np.array(hC.shape) / 2)) < hC.shape[0] / 4)
    names = sorted(p for p, _ in IMGS)
    check("saved 6 images", names == sorted(f"pcg/terrain_{k}" for k in (
        "lit", "topo", "albedo", "height", "normal", "splat")))
    lit_img = [im for p, im in IMGS if p == "pcg/terrain_lit"][0]
    check("  the rendered image is neither all black nor all white", 0.1 < float(lit_img.mean()) < 0.8,
          round(float(lit_img.mean()), 3))

# ═══════════════════════════════════════════════════ 5. English tutorials
sec("Tutorials: size, English-only text, panel bindings")
TUT = [n for n in wfs if n.startswith("tutorial_")]
check("6 tutorials generated", sorted(TUT) == sorted(MW.TUTORIALS) and len(TUT) == 6, TUT)


def _cjk(s):
    return any("\u3000" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef" for ch in s)


for nm in sorted(TUT):
    wf = wfs[nm]
    real = [n for n in wf["nodes"] if n["type"] != "Note"]
    notes = [n for n in wf["nodes"] if n["type"] == "Note"]
    texts = [n.get("title") or "" for n in wf["nodes"]] + \
        [str(v) for n in wf["nodes"] for v in n.get("widgets_values", [])
         if isinstance(v, str)]
    check(f"{nm}: 6-15 nodes and exactly one Note, all text English",
          6 <= len(real) <= 15 and len(notes) == 1 and not any(_cjk(t) for t in texts),
          (len(real), len(notes)))
    check("  no model files: only PCG nodes + PreviewImage / SaveImage",
          all(n["type"].startswith("PCG_") or n["type"] in ("PreviewImage", "SaveImage")
              for n in real))

# Bindings are materialized by the front end; in the saved workflow every bound widget
# must already hold the panel's value, otherwise API runs and UI runs disagree
from comfyui_pcg.params import parse as _pparse, merge as _pmerge   # noqa: E402
wf = wfs["tutorial_06_controller"]
panel = [n for n in wf["nodes"] if n["type"] == "PCG_Parameters"]
pvals = _pmerge(_pparse(panel[0]["widgets_values"][0]),
                json.loads(panel[0]["widgets_values"][1])) if panel else {}
bad, nb = [], 0
for n in wf["nodes"]:
    for wname, ref in (n.get("properties", {}).get("pcg_bind") or {}).items():
        nb += 1
        ins, _ = MW.spec_of(n["type"])
        wn = [x for x, t, _ in ins if MW.is_widget(t)]
        v = n["widgets_values"][wn.index(wname)]
        if ref not in pvals or v != pvals[ref]:
            bad.append((n.get("title"), wname, ref, v, pvals.get(ref)))
check("controller: one panel, 6 bindings, every bound widget holds the panel value",
      len(panel) == 1 and nb == 6 and not bad, bad)
check("  existing (non-tutorial) workflows carry no bindings",
      not any("pcg_bind" in n.get("properties", {}) for k, w in wfs.items()
              if not k.startswith("tutorial_") for n in w["nodes"]))

if torch is None or os.environ.get("PCG_TEST_QUICK"):
    print("  (no torch / PCG_TEST_QUICK: tutorials not executed)")
else:
    sec("Tutorials: execute")
    for nm in sorted(TUT):
        api, res, byt, dt = run(nm)
        check(f"{nm}: ran ({len(api)} nodes, {dt:.1f} s)", True)
        prev = [im for p, im in IMGS if p is None]
        check("  preview image is not empty", len(prev) == 1
              and float(prev[0].std()) > 0.03, [tuple(i.shape) for i in prev])

        def out(title, nm=nm, res=res):
            return res[title_of(nm, title)[0]][0]
        if nm == "tutorial_01_first_geometry":
            geo = out("Paint")
            Pg = A(geo, "P")
            check("  two extrusions on the top face: top at y = 0.5 + 0.8 + 0.6 = 1.9",
                  abs(Pg[:, 1].max() - 1.9) < 1e-3 and abs(Pg[:, 1].min() + 0.5) < 1e-3,
                  (round(float(Pg[:, 1].min()), 3), round(float(Pg[:, 1].max()), 3)))
            check("  only one face was in 'top'",
                  int(resolve(out("Group 'top' (faces facing up)"), PRIM, "top").sum()) == 1)
        elif nm == "tutorial_02_scatter_copy":
            pts = out("Random rotation (orient)")
            ps = A(pts, "pscale")[:, 0]
            check("  250 points, pscale in [0.15, 0.6], orient is unit quaternions",
                  pts.npoints == 250 and ps.min() >= 0.15 and ps.max() <= 0.6
                  and np.allclose(np.linalg.norm(A(pts, "orient"), axis=1), 1, atol=1e-4))
            rock = out("Rock colour")
            cp = res[byt["PCG_CopyToPoints"][0]][0]
            check("  one rock per point", cp.nprims == 250 * rock.nprims,
                  (cp.nprims, rock.nprims))
        elif nm == "tutorial_03_attributes_wrangle":
            pm = out("height: points to faces")
            hgt = A(pm, "height", PRIM)[:, 0]
            gr = out("Group 'tall'")
            tall = resolve(gr, PRIM, "tall")
            check("  group 'tall' = faces with height > 0.35 (some, not all)",
                  np.array_equal(tall, hgt > 0.35) and 0 < tall.sum() < len(hgt),
                  int(tall.sum()))
            check("  edge faces faded to 0 by the Wrangle",
                  float(A(out("Fade towards the edge"), "height")[:, 0][
                      A(out("Fade towards the edge"), "dist")[:, 0] > 6.0].max()) < 1e-6)
            ex = out("Raise 'tall' by its height")
            check("  highest face raised by 3 x its height",
                  abs(A(ex, "P")[:, 1].max() - 3.0 * hgt[tall].max()) < 1e-3)
        elif nm == "tutorial_04_foreach_variations":
            geo = res[byt["PCG_ForEachEnd"][0]][0]
            Pg = A(geo, "P")
            k = np.round(Pg[:, 0] / 2.3 + 2.5).astype(int)
            shapes = {tuple(np.round(np.ptp(Pg[k == i], axis=0), 4)) for i in range(6)}
            check("  six stones, one per 2.3 m slot, all with different shapes",
                  sorted(set(k.tolist())) == list(range(6)) and len(shapes) == 6)
        elif nm == "tutorial_05_cop_texture":
            names = sorted(p for p, _ in IMGS if p)
            check("  saved normal + height", names == ["pcg/tutorial_tiles_height",
                                                       "pcg/tutorial_tiles_normal"], names)
            lt = res[byt["PCG_COPLight"][0]][0]
            Nn = getn(lt, "N")
            check("  normals unit length", np.allclose(np.linalg.norm(Nn, axis=-1), 1,
                                                       atol=1e-4))
            check("  tile colour is RGB after Remap", getn(lt, "tile_rand").shape[-1] == 3)
        elif nm == "tutorial_06_controller":
            cp = out("Pillars on the circle")
            tb = out("Base at y = 0")
            ring = out("Lift to the pillar tops")
            check("  12 pillars of height 3, ring lifted to y = 3, radius 4",
                  cp.nprims == 12 * tb.nprims
                  and abs(A(cp, "P")[:, 1].max() - 3.0) < 1e-4
                  and abs(A(ring, "P")[:, 1].mean() - 3.0) < 1e-4
                  and abs(np.hypot(A(cp, "P")[:, 0], A(cp, "P")[:, 2]).mean() - 4.0) < 0.3)

import shutil                                             # noqa: E402
for _d in (tmpd, tmpd2):
    shutil.rmtree(_d, ignore_errors=True)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
